"""kit.simreal: realism statistics, the linear realism test, and kit.hardcases render bounds."""
import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HAVE = all(importlib.util.find_spec(m) is not None for m in ("numpy", "scipy", "skimage"))


def _sheets(np, pitch=12.0, width=2.0, noise=0.05, seed=0, size=256):
    """Horizontal bright sheets of the given pitch and Gaussian width, plus white noise."""
    rng = np.random.default_rng(seed)
    pitch = pitch * rng.uniform(0.92, 1.08)
    y = np.arange(size)[:, None] * np.ones((1, size)) + rng.uniform(0, pitch)
    d = (y % pitch) - pitch / 2
    img = np.exp(-d * d / (2 * width * width))
    return img + noise * rng.normal(size=img.shape)


@unittest.skipUnless(HAVE, "needs numpy, scipy, scikit-image")
class WindowStatsTest(unittest.TestCase):
    def test_pitch_width_noise_follow_the_image(self):
        import numpy as np
        from kit import simreal
        a = simreal.window_stats(_sheets(np, pitch=12, width=1.5, noise=0.02))
        b = simreal.window_stats(_sheets(np, pitch=20, width=3.0, noise=0.2))
        self.assertAlmostEqual(a["pitch"], 12, delta=2.5)
        self.assertAlmostEqual(b["pitch"], 20, delta=3.5)
        self.assertLess(a["width"], b["width"])
        quiet = simreal.window_stats(_sheets(np, pitch=12, width=2.0, noise=0.01))
        loud = simreal.window_stats(_sheets(np, pitch=12, width=2.0, noise=0.15))
        self.assertLess(quiet["noise"], loud["noise"])

    def test_flat_window_is_none_and_nan_refused(self):
        import numpy as np
        from kit import simreal
        self.assertIsNone(simreal.window_stats(np.ones((64, 64))))
        w = _sheets(np)
        w[3, 3] = np.nan
        with self.assertRaises(simreal.RealError):
            simreal.window_stats(w)

    def test_distance_zero_for_itself_and_grows(self):
        import numpy as np
        from kit import simreal
        ws = [_sheets(np, seed=s) for s in range(4)]
        sm = simreal.summarise([simreal.window_stats(w) for w in ws])
        other = simreal.summarise([simreal.window_stats(_sheets(np, pitch=20, noise=0.3, seed=s)) for s in range(4)])
        self.assertEqual(simreal.distance(sm, sm), 0.0)
        self.assertGreater(simreal.distance(sm, other), 1.0)


@unittest.skipUnless(HAVE, "needs numpy, scipy, scikit-image")
class RealismAucTest(unittest.TestCase):
    def test_same_source_near_half_different_source_near_one(self):
        """The realism test can fail: two draws of one source score near 0.5, two different sources near 1."""
        import numpy as np
        from kit import simreal
        a = np.array([simreal.features(_sheets(np, noise=0.05, seed=s, size=128)) for s in range(40)])
        b = np.array([simreal.features(_sheets(np, noise=0.05, seed=100 + s, size=128)) for s in range(40)])
        c = np.array([simreal.features(_sheets(np, pitch=18, noise=0.25, seed=200 + s, size=128)) for s in range(40)])
        self.assertLess(abs(simreal.realism_auc(a, b) - 0.5), 0.2)
        self.assertGreater(simreal.realism_auc(a, c), 0.95)


@unittest.skipUnless(HAVE, "needs numpy, scipy, scikit-image")
class RealismBoundsTest(unittest.TestCase):
    def test_default_tiles_unchanged_and_bounds_take_effect(self):
        import numpy as np
        from kit import hardcases as H
        a = H.tiles(2, 5, 128)
        with H.realism(sd=None, psf=None):
            b = H.tiles(2, 5, 128)
        self.assertTrue(np.array_equal(a["image"], b["image"]))
        with H.realism(sd=(0.0, 0.001), psf=(2.0, 2.2)):
            c = H.tiles(2, 5, 128)
        self.assertTrue(np.array_equal(a["lines"], c["lines"]))
        self.assertFalse(np.array_equal(a["image"], c["image"]))
        self.assertEqual(H.REAL, {})
        with self.assertRaises(H.SimError):
            with H.realism(bogus=(0, 1)):
                pass
        with self.assertRaises(H.SimError):
            with H.realism(sd=(0.5, 0.1)):
                pass

    def test_pitch_factor_spreads_sheets(self):
        import numpy as np
        from kit import hardcases as H
        rng = np.random.default_rng(1)
        base = H.pitch_draw(rng, 200)
        with H.realism(pitch=(1.3, 1.3)):
            wide = H.pitch_draw(np.random.default_rng(1), 200)
        self.assertGreater(float(np.median(wide)), 1.15 * float(np.median(base)))


if __name__ == "__main__":
    unittest.main()
