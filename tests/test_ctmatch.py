"""Tests for kit.ctmatch: CT contrast and noise matching of synthetic tiles."""

import importlib.util
import unittest

import numpy as np

HAVE_SCIPY = importlib.util.find_spec("scipy") is not None
HAVE_SKIMAGE = importlib.util.find_spec("skimage") is not None
HAVE_TORCH = importlib.util.find_spec("torch") is not None


def _fake_ct(seed, n=3, size=300, pitch=9.0, noise=0.12):
    """Bright wavy sheets on a dark background with blurred noise: a stand-in for real CT slices."""
    from scipy import ndimage as nd
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        yy, xx = np.mgrid[0:size, 0:size].astype(float)
        ph = (yy + 6 * np.sin(xx / 40.0 + rng.uniform(0, 6))) / pitch
        sheets = (np.abs(ph - np.round(ph)) < 0.25).astype(float)
        img = 0.2 + 0.6 * nd.gaussian_filter(sheets, 0.8)
        img += nd.gaussian_filter(rng.standard_normal((size, size)), 0.9) * noise
        out.append(img.astype(np.float32))
    return out


@unittest.skipUnless(HAVE_SCIPY, "needs scipy")
class TestReference(unittest.TestCase):
    def test_reference_shapes_and_ranges(self):
        from kit import ctmatch
        ref = ctmatch.reference(_fake_ct(1), n=40, seed=2)
        self.assertEqual(ref["q"].shape, (40, ctmatch.NQ))
        self.assertTrue(np.all(np.diff(ref["q"], axis=1) >= -1e-6))
        self.assertTrue(np.all((ref["bright"] > 0) & (ref["bright"] < 1)))
        self.assertTrue(np.all(ref["noise"] > 0))

    def test_reference_is_seeded(self):
        from kit import ctmatch
        a = ctmatch.reference(_fake_ct(1), n=20, seed=5)
        b = ctmatch.reference(_fake_ct(1), n=20, seed=5)
        np.testing.assert_array_equal(a["q"], b["q"])

    def test_masks_refuse_uncovered_windows(self):
        from kit import ctmatch
        sl = _fake_ct(1, n=1)
        with self.assertRaises(ValueError):
            ctmatch.reference(sl, [np.zeros(sl[0].shape, bool)], n=10)

    def test_grain_tables_invert(self):
        from kit import ctmatch
        for s, c in ctmatch.GRAIN_TABLE:
            self.assertAlmostEqual(ctmatch.grain_sigma(c), s, places=6)
        for s, c in ctmatch.SIM_BLUR_TABLE:
            self.assertAlmostEqual(ctmatch.blur_sigma(c), s, places=6)


@unittest.skipUnless(HAVE_SCIPY and HAVE_TORCH, "needs scipy and torch")
class TestApply(unittest.TestCase):
    def test_lines_stay_put_and_histogram_moves_toward_reference(self):
        import torch
        from kit import ctmatch
        ref = ctmatch.reference(_fake_ct(1, noise=0.2), n=60, seed=1)
        tiles = np.stack([t[:256, :256] for t in _fake_ct(9, n=4, noise=0.02)])
        before = ctmatch.distance(ctmatch.tile_stats(tiles), ref)
        g = torch.Generator().manual_seed(0)
        y = ctmatch.apply(torch.from_numpy(tiles), ref, g, p=1.0).numpy()
        after = ctmatch.distance(ctmatch.tile_stats(y), ref)
        self.assertEqual(y.shape, tiles.shape)
        self.assertTrue(np.isfinite(y).all() and y.min() >= 0 and y.max() <= 255)
        self.assertLess(abs(after["noise"]), abs(before["noise"]))
        # rank-preserving on the clean structure: the bright sheets stay the bright pixels
        for t, m in zip(tiles, y):
            hi = t > np.percentile(t, 75)
            self.assertGreater(m[hi].mean(), m[~hi].mean())

    def test_p_zero_only_rescales(self):
        import torch
        from kit import ctmatch
        ref = ctmatch.reference(_fake_ct(1), n=20, seed=1)
        tiles = np.stack([t[:256, :256] for t in _fake_ct(3, n=2)])
        g = torch.Generator().manual_seed(0)
        y = ctmatch.apply(torch.from_numpy(tiles), ref, g, p=0.0).numpy()
        for t, m in zip(tiles, y):
            self.assertGreater(np.corrcoef(t.ravel(), m.ravel())[0, 1], 0.999)

    def test_crowded_reference_never_paints_an_air_tile(self):
        import torch
        from kit import ctmatch
        ref = ctmatch.reference(_fake_ct(1, pitch=4.0), n=40, seed=1)      # crowded: high bright fraction
        air = np.random.default_rng(0).normal(30, 3, (2, 256, 256)).astype(np.float32)
        air[:, 100:104, :] = 200                                              # one sheet
        g = torch.Generator().manual_seed(0)
        y = ctmatch.apply(torch.from_numpy(air), ref, g, p=1.0, tol=0.15).numpy()
        # the tile kept its own histogram: the air stays dark (a crowded window's map would make half of it bright)
        for m in y:
            self.assertLess(np.median(m), 60)
            self.assertGreater(m[100:104].mean(), np.median(m) + 80)


if __name__ == "__main__":
    unittest.main()
