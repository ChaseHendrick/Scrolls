import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import tracemalloc
import unittest
from pathlib import Path

from kit import cli

try:
    import numpy as np
    from kit import strokenet as N
except ImportError:  # the core kit is standard library only
    np = N = None
try:
    from scipy import ndimage as ndi
except ImportError:
    ndi = None
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts" / "strokenet"
D = NL = torch = None
if N is not None:
    try:
        sys.path.insert(0, str(SCRIPTS))
        import data as D
    except ImportError:
        D = None
    try:
        import torch
        import nulls as NL
    except ImportError:
        torch = NL = None
    finally:
        if str(SCRIPTS) in sys.path:
            sys.path.remove(str(SCRIPTS))


def write_random_net(path, chans=(4, 8), seed=0, meta=None):
    """A StrokeNet weights file with random weights in the training script's layout."""
    rng = np.random.default_rng(seed)
    arrs, cin, k = {}, 1, 0
    for c in chans:
        for _ in range(2):
            arrs[f"conv{k}_w"] = rng.normal(0, 0.3, (c, cin, 3, 3)).astype(np.float32)
            arrs[f"conv{k}_b"] = rng.normal(0, 0.1, c).astype(np.float32)
            cin, k = c, k + 1
        arrs[f"pool_after_{k - 1}"] = np.array(1)
    arrs["head_w"] = rng.normal(0, 0.3, (1, 2 * cin)).astype(np.float32)
    arrs["head_b"] = np.zeros(1, np.float32)
    arrs["n_conv"] = np.array(k)
    arrs["meta"] = np.array(json.dumps(meta if meta is not None else {"platt": [1.0, 0.0], "val_blank_logit_q99": 0.0}))
    np.savez(path, **arrs)


def naive_conv(x, w, b):
    n, c, h, wd = x.shape
    xp = np.pad(x, ((0, 0), (0, 0), (1, 1), (1, 1)))
    out = np.zeros((n, w.shape[0], h, wd))
    for o in range(w.shape[0]):
        for ci in range(c):
            for dy in range(3):
                for dx in range(3):
                    out[:, o] += w[o, ci, dy, dx] * xp[:, ci, dy:dy + h, dx:dx + wd]
        out[:, o] += b[o]
    return out


def brute_area(a, n_out, axis):
    """Area average along one axis by explicit overlap of each output cell with each input cell."""
    a = np.moveaxis(np.asarray(a, np.float64), axis, 0)
    n = a.shape[0]
    f = n / n_out
    out = np.zeros((n_out,) + a.shape[1:])
    for j in range(n_out):
        lo, hi = j * f, (j + 1) * f
        for i in range(n):
            ov = min(hi, i + 1) - max(lo, i)
            if ov > 0:
                out[j] += ov * a[i]
        out[j] /= f
    return np.moveaxis(out, 0, axis)


class LazyMap:
    """A 2D uint8 array-like that builds each requested slice from one stored row and records the
    largest number of rows read at once (a stand-in for a zarr view of a whole segment)."""

    def __init__(self, H, W, seed=0):
        self.shape, self.dtype = (H, W), np.dtype(np.uint8)
        self.row = np.random.default_rng(seed).integers(0, 256, W).astype(np.uint8)
        self.max_rows = 0

    def __getitem__(self, key):
        ys, xs = key if isinstance(key, tuple) else (key, slice(None))
        n = len(range(*ys.indices(self.shape[0])))
        self.max_rows = max(self.max_rows, n)
        r = self.row[xs]
        return np.broadcast_to(r, (n, r.size))


def corner_cut_square(n, size, at):
    """Expected usable mask of a size x size square of ink in an n x n map: the opening removes the
    six pixels of each corner further than 3 (L1) from the square shrunk by 3 px."""
    m = np.zeros((n, n), bool)
    y0, x0 = at
    m[y0:y0 + size, x0:x0 + size] = True
    for cy, cx, sy, sx in ((y0, x0, 1, 1), (y0, x0 + size - 1, 1, -1), (y0 + size - 1, x0, -1, 1),
                           (y0 + size - 1, x0 + size - 1, -1, -1)):
        for dy, dx in ((0, 0), (0, 1), (1, 0), (0, 2), (1, 1), (2, 0)):
            m[cy + sy * dy, cx + sx * dx] = False
    return m


def structured_maps():
    """Maps that exercise the usable rule: holes, holes open to the edge or only diagonally
    connected, thin necks the opening removes, a spiral, ink on the border, and tiny maps."""
    out = []
    a = np.zeros((60, 60), np.uint8)
    a[5:50, 5:50] = 200
    a[20:30, 20:30] = 0                          # closed hole: filled
    a[40:46, 44:50] = 0                          # notch open to the outside: not a hole
    out.append(a)
    b = np.full((40, 50), 100, np.uint8)         # ink touching every edge
    b[10:20, 0:15] = 2                           # background touching the left edge: kept out
    b[25:32, 30:37] = 3                          # value 3 is not usable (strictly above 3)
    out.append(b)
    c = np.zeros((40, 40), np.uint8)
    c[2:38, 2:38] = 150
    c[10:20, 10:20] = 0                          # hole joined to a second hole only at one corner
    c[20:30, 20:30] = 0
    c[19, 19] = c[20, 20] = 0
    out.append(c)
    d = np.zeros((70, 70), np.uint8)             # square spiral wall, 8 px thick
    y, x = 2, 2
    for k, (h, w) in enumerate(((8, 66), (60, 8), (8, 58), (52, 8), (8, 50), (44, 8), (8, 42))):
        if k % 4 == 0:
            d[y:y + h, x:x + w] = 220
            y, x = y, x + w - 8
        elif k % 4 == 1:
            d[y:y + h, x:x + w] = 220
            y, x = y + h - 8, x
        elif k % 4 == 2:
            d[y:y + h, x - w + 8:x + 8] = 220
            y, x = y, x - w + 8
        else:
            d[y - h + 8:y + 8, x:x + w] = 220
            y, x = y - h + 16, x + 8
    out.append(d)
    e = np.zeros((30, 30), np.uint8)
    e[5:25, 5:25] = 90
    e[5:25, 14:16] = 1                           # a 2 px gap the opening widens into a split
    out.append(e)
    out += [np.full((1, 9), 50, np.uint8), np.full((7, 7), 50, np.uint8), np.full((8, 9), 50, np.uint8)]
    return out


@unittest.skipIf(N is None, "numpy not installed")
class StrokeNetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "net.npz")
        write_random_net(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def ink(self, shape, seed):
        """A usable map on the organisers' 0 to 255 scale (every value above 3)."""
        return np.random.default_rng(seed).integers(4, 256, shape).astype(np.uint8)

    # -------------------------------------------------------------- network
    def test_conv_matches_naive(self):
        rng = np.random.default_rng(1)
        x = rng.normal(size=(2, 3, 9, 11)).astype(np.float32)
        w = rng.normal(size=(5, 3, 3, 3)).astype(np.float32)
        b = rng.normal(size=5).astype(np.float32)
        self.assertTrue(np.allclose(N._conv3(x, w, b), naive_conv(x, w, b), atol=1e-4))

    def test_normalise_uses_lower_median_and_unbiased_sd(self):
        rng = np.random.default_rng(2)
        x = rng.normal(size=(3, 8, 8)).astype(np.float32)
        z = N.normalise(x)
        f = x.reshape(3, -1)
        med = np.sort(f, axis=1)[:, 31:32]                     # 64 values: the lower of the two middle ones
        mad = np.sort(np.abs(f - med), axis=1)[:, 31:32] * 1.4826
        ref = (np.clip((f - med) / mad, -3, 20) / 5.0).reshape(x.shape)
        self.assertTrue(np.allclose(z, ref, atol=1e-6))
        flat = np.zeros((1, 8, 8), np.float32)
        flat[0, 0, :4] = [1, 2, 3, 4]                          # MAD 0: falls back to the unbiased SD
        sd = flat.reshape(1, -1).std(ddof=1)
        self.assertAlmostEqual(float(N.normalise(flat)[0, 0, 3]), min(4 / (sd + 1e-3), 20) / 5.0, places=5)

    def test_logits_ignore_gain_and_offset_and_normalise_per_batch(self):
        net = N.StrokeNet(self.path)
        crops = np.random.default_rng(3).uniform(0, 255, (5, 128, 128)).astype(np.float32)
        l1, l2 = net.logits(crops), net.logits(crops * 0.5 + 10)
        self.assertEqual(l1.shape, (5,))
        self.assertTrue(np.allclose(l1, l2, atol=1e-3))
        seen, real = [], N.normalise
        try:
            N.normalise = lambda w: (seen.append(len(w)), real(w))[1]
            l3 = net.logits(crops, batch=2)
        finally:
            N.normalise = real
        self.assertEqual(seen, [2, 2, 1])                      # never the whole stack at once
        self.assertTrue(np.allclose(l1, l3, atol=1e-5))
        self.assertEqual(net.logits(crops[:0]).shape, (0,))

    def test_calibrate_is_documented_as_mixture_only(self):
        net = N.StrokeNet(self.path)
        p = net.calibrate(np.array([-2.0, 0.0, 2.0]))
        self.assertTrue(((p > 0) & (p < 1)).all())
        doc = " ".join(net.calibrate.__doc__.split())
        self.assertIn("fixed evaluation mixture", doc)
        self.assertIn("not P(text) on a real map", doc)
        for part in ("text 0.5", "blank, dense, IAAFT, shuffle and rot90 copies 0.1 each"):
            self.assertIn(part, doc)

    # -------------------------------------------------------------- resampling
    def test_area_resampling_matches_brute_force(self):
        rng = np.random.default_rng(4)
        a = rng.uniform(0, 1, (17, 23))
        for n_out in (5, 7, 16, 30, 41):                       # down and up, whole and fractional factors
            self.assertTrue(np.allclose(N._area_axis(a, n_out, 0), brute_area(a, n_out, 0), atol=1e-9))
            self.assertTrue(np.allclose(N._area_axis(a, n_out, 1), brute_area(a, n_out, 1), atol=1e-9))
        r = N._area_axis(a, 7, 0)
        self.assertAlmostEqual(r.sum() * 17 / 7, a.sum(), places=9)     # mass is kept

    def test_to_working(self):
        a = np.arange(40 * 60, dtype=np.float32).reshape(40, 60)
        same = N.to_working(a, N.PIXEL_MM)
        self.assertIs(same.dtype, np.dtype(np.float32))
        self.assertTrue(np.array_equal(same, a))
        b = N.to_working(a, N.PIXEL_MM / 4)                      # whole 4 x 4 block means, float kept unrounded
        self.assertEqual(b.shape, (10, 15))
        self.assertAlmostEqual(float(b[0, 0]), float(a[:4, :4].mean()), places=4)
        c = N.to_working(a, N.PIXEL_MM / 2.5)                    # fractional: area average
        self.assertEqual(c.shape, (16, 24))
        self.assertAlmostEqual(float(c.mean()), float(a.mean()), places=2)
        ref = N._area_axis(N._area_axis(a, 16, 0), 24, 1)
        for strip in (3, 7, None):                               # strip-wise area average is the same
            self.assertTrue(np.allclose(N.to_working(a, N.PIXEL_MM / 2.5, strip=strip), ref, atol=1e-3))
        up = N.to_working(a, N.PIXEL_MM * 1.5, strip=5)          # coarser map: upsampled by area
        self.assertEqual(up.shape, (60, 90))
        self.assertTrue(np.allclose(up, N._area_axis(N._area_axis(a, 60, 0), 90, 1), atol=1e-3))
        u8 = (a % 251).astype(np.uint8)                          # integer input: area average, then rounded
        r = N.to_working(u8, N.PIXEL_MM / 2.5, strip=7)
        f = N._area_axis(N._area_axis(u8, 16, 0), 24, 1)
        self.assertTrue(np.array_equal(r, np.round(r)))
        clear = np.abs(f % 1 - 0.5) > 1e-6                       # away from a tie, float rounding cannot matter
        self.assertTrue(np.array_equal(r[clear], np.rint(f[clear]).astype(np.float32)))
        self.assertLessEqual(float(np.abs(r - f).max()), 0.5 + 1e-6)
        with self.assertRaises(ValueError):
            N.to_working(a, 0)
        with self.assertRaises(ValueError):
            N.to_working(a[0], N.PIXEL_MM)

    def test_integer_block_mean_rounds_half_to_even(self):
        a = np.zeros((10, 10), np.uint8)
        a[:5, :5] = np.array([3] * 13 + [4] * 12).reshape(5, 5)       # mean 3.48 -> 3
        a[:5, 5:] = np.array([2] * 12 + [3] * 13).reshape(5, 5)       # mean 2.52 -> 3
        a[5:, :5] = 7
        w = N.to_working(a, N.PIXEL_MM / 5)
        self.assertEqual(w.tolist(), [[3.0, 3.0], [7.0, 0.0]])
        t = np.zeros((4, 4), np.uint8)
        t[:2, :2] = [[2, 3], [2, 3]]                                   # 2.5 -> 2
        t[:2, 2:] = [[3, 4], [3, 4]]                                   # 3.5 -> 4
        self.assertEqual(N.to_working(t, N.PIXEL_MM / 2)[0].tolist(), [2.0, 4.0])

    @unittest.skipIf(D is None, "scripts/strokenet/data.py not importable")
    def test_to_working_reproduces_data_pool_array(self):
        rng = np.random.default_rng(10)
        tile = rng.integers(0, 256, (20 * 13 + 11, 20 * 9 + 7)).astype(np.uint8)   # ragged edges are dropped
        ties = 0
        for by in range(0, 20 * 13, 40):
            for bx in range(0, 20 * 9, 40):
                n = int(rng.integers(0, 255))
                blk = np.full(400, n, np.uint8)
                blk[::2] = n + 1                                       # block mean n + 0.5 exactly
                tile[by:by + 20, bx:bx + 20] = blk.reshape(20, 20)
                ties += 1
        ref = D.pool_array(tile)
        means = tile[:260, :180].reshape(13, 20, 9, 20).mean(axis=(1, 3))
        self.assertGreaterEqual(int((means % 1 == 0.5).sum()), ties)
        for strip in (None, 20, 40, 100, 1000):
            w = N.to_working(tile, 0.0024, strip=strip)
            self.assertIs(w.dtype, np.dtype(np.float32))
            self.assertTrue(np.array_equal(w, ref.astype(np.float32)), strip)
        self.assertTrue(np.array_equal(D.pool_array(tile, strip=40), ref))
        self.assertFalse(np.array_equal(means.astype(np.float32), N.to_working(tile, 0.0024)))   # rounding matters

    def test_to_working_reads_in_strips_without_a_full_copy(self):
        z = LazyMap(20000, 20000, seed=11)                     # 400 MB as uint8, 1.6 GB as float32
        tracemalloc.start()
        try:
            w = N.to_working(z, 0.0024, strip=200)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(w.shape, (1000, 1000))
        self.assertLessEqual(z.max_rows, 200)
        self.assertLess(peak, 40e6)                            # output is 4 MB; a float copy would be 1600 MB
        row = np.round(z.row.reshape(1000, 20).astype(np.int64).sum(axis=1) * 20 / 400.0)
        self.assertTrue(np.array_equal(w[0], row.astype(np.float32)))
        self.assertTrue(np.array_equal(w[-1], w[0]))
        z = LazyMap(3000, 300, seed=12)                        # fractional factor: area average in strips
        w = N.to_working(z, N.PIXEL_MM / 2.5, strip=200)
        self.assertLessEqual(z.max_rows, 200)
        ref = np.rint(N._area_axis(np.broadcast_to(z.row, (1, 300)), 120, 1))[0]
        self.assertEqual(w.shape, (1200, 120))
        self.assertTrue(np.array_equal(w[0], ref.astype(np.float32)))
        self.assertTrue(np.array_equal(w[-1], w[0]))

    # -------------------------------------------------------------- usable papyrus and windows
    def test_usable_mask_numpy_fallback_by_hand(self):
        a = np.zeros((40, 40), np.uint8)
        a[8:28, 6:26] = 200
        a[15:19, 14:18] = 0                                    # a closed hole is filled
        a[0, 0] = 255                                          # a lone pixel is opened away
        got = N.usable_mask(a, use_scipy=False)
        self.assertTrue(np.array_equal(got, corner_cut_square(40, 20, (8, 6))))
        self.assertEqual(int(got.sum()), 400 - 24)
        saved = {k: sys.modules.get(k) for k in ("scipy", "scipy.ndimage")}
        try:                                                   # no scipy: the default falls back to numpy
            sys.modules["scipy"] = sys.modules["scipy.ndimage"] = None
            self.assertTrue(np.array_equal(N.usable_mask(a), got))
            with self.assertRaises(ImportError):
                N.usable_mask(a, use_scipy=True)
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        full = N.usable_mask(np.full((12, 12), 9, np.uint8), use_scipy=False)
        self.assertEqual(int((~full).sum()), 24)               # only the four map corners are lost
        self.assertFalse(N.usable_mask(np.full((12, 12), 3, np.uint8), use_scipy=False).any())

    @unittest.skipIf(ndi is None, "scipy not installed")
    def test_usable_mask_numpy_fallback_matches_scipy(self):
        rng = np.random.default_rng(13)
        maps = structured_maps()
        for _ in range(60):                                    # random maps, blobby and speckled
            H, W = rng.integers(1, 70, 2)
            p = rng.uniform(0.3, 0.97)
            m = rng.uniform(size=(H, W)) < p
            if rng.uniform() < 0.5:
                m = np.kron(m, np.ones((3, 3), bool))
            maps.append(np.where(m, rng.integers(4, 256, m.shape), rng.integers(0, 4, m.shape)).astype(np.uint8))
        maps.append(N.to_working(rng.integers(0, 256, (800, 800)).astype(np.uint8) // 60 * 60, 0.0096))
        for a in maps:
            ref = ndi.binary_fill_holes(ndi.binary_opening(np.asarray(a, np.float32) > 3, iterations=3))
            self.assertTrue(np.array_equal(N.usable_mask(a, use_scipy=False), ref), a.shape)
            self.assertTrue(np.array_equal(N.usable_mask(a), ref))
        self.assertTrue(np.array_equal(N.usable_mask(maps[0], use_scipy=True), N.usable_mask(maps[0], use_scipy=False)))

    def test_window_starts_cover_the_end_and_refuse_small_maps(self):
        self.assertEqual(N.window_starts(128, 32), [0])
        self.assertEqual(N.window_starts(200, 32), [0, 32, 64, 72])
        self.assertEqual(N.window_starts(256, 64), [0, 64, 128])
        self.assertEqual(N.window_starts(129, 200), [0, 1])
        with self.assertRaises(ValueError):
            N.window_starts(127, 32)
        with self.assertRaises(ValueError):
            N.window_starts(300, 0)
        net = N.StrokeNet(self.path)
        for shape in ((127, 400), (400, 100), (10, 10)):
            with self.assertRaises(ValueError):
                net.score_map(self.ink(shape, 0), N.PIXEL_MM)
        with self.assertRaises(ValueError):                    # 128 px at 2.4 um is under 7 px at 0.048 mm
            net.region_score(self.ink((128, 128), 0), 0.0024)

    def test_layout_skips_windows_under_99_percent_core(self):
        a = np.full((300, 260), 120, np.float32)
        a[100:140, 0:80] = 0                                   # empty band joined to the left edge: not a hole
        a[250:252, 200:202] = 0                                # 4 px hole: filled, so usable
        ys, xs, keep = N.layout(a, 32)
        self.assertEqual(ys, [0, 32, 64, 96, 128, 160, 172])
        self.assertEqual(xs, [0, 32, 64, 96, 128, 132])
        c = N.core_mask(a)
        self.assertTrue(c[250:252, 200:202].all())
        self.assertFalse(c[120, 110])                          # 31 px from the band: inside 1.5 mm
        self.assertTrue(c[120, 111])                           # 32 px: core
        want = np.array([[c[y:y + 128, x:x + 128].mean() >= 0.99 for x in xs] for y in ys])
        self.assertTrue(np.array_equal(keep, want))
        self.assertGreater(int((~keep).sum()), 0)
        self.assertGreater(int(keep.sum()), 0)
        for row, n, bad in ((52, 19, 163), (51, 20, 164)):    # the 99 % line: at most 163 of 16384 not core
            edge = np.full((256, 200), 120, np.float32)
            edge[:, 0] = 0
            edge[row, :n] = 0
            self.assertEqual(int((~N.core_mask(edge)[64:192, 32:160]).sum()), bad)
            ys, xs, keep = N.layout(edge, 32)
            self.assertEqual(bool(keep[ys.index(64), xs.index(32)]), bad <= 163)

    def test_core_mask_matches_training_labels_rule(self):
        """core_mask is the nonzero part of data.py label_map: usable papyrus more than 1.5 mm in."""
        rng = np.random.default_rng(3)
        for t in range(25):
            H, W = (int(v) for v in rng.integers(40, 220, 2))
            a = np.full((H, W), 120, np.uint8)
            for _ in range(int(rng.integers(0, 6))):
                y, x = int(rng.integers(0, H)), int(rng.integers(0, W))
                a[y:y + int(rng.integers(1, 60)), x:x + int(rng.integers(1, 60))] = 0
            if t % 4 == 0:
                a[:, :int(rng.integers(1, 10))] = 0
            got = N.core_mask(a, use_scipy=False)
            if ndi is not None:
                u = N.usable_mask(a)
                ref = (ndi.distance_transform_edt(u) > 1.5 / 0.048) if not u.all() else u
                self.assertTrue(np.array_equal(got, ref), (H, W))
                self.assertTrue(np.array_equal(N.core_mask(a), ref))
        self.assertFalse(N.core_mask(np.zeros((50, 50), np.uint8), use_scipy=False).any())
        one = np.full((120, 120), 9, np.uint8)
        one[:, 0] = 0                                          # 1.5 mm (31.25 px) next to the empty column is lost
        c = N.core_mask(one, use_scipy=False)
        self.assertFalse(c[:, :32].any())
        self.assertTrue(c[40:80, 32:80].all())

    def test_nan_reads_as_unusable(self):
        a = np.full((300, 300), 120.0, np.float32)
        a[:, :20] = np.nan                                     # no data along the left edge
        a[150, 150] = np.inf
        w = N.to_working(a, N.PIXEL_MM)
        self.assertTrue(np.isfinite(w).all())
        self.assertEqual(float(w[0, 0]), 0.0)
        self.assertFalse(N.core_mask(w)[:, :20 + 31].any())
        fine = np.full((600, 600), 120.0, np.float32)
        fine[300, :] = np.nan                                  # a NaN row must not spread down the sums
        g = N.to_working(fine, 0.024 * 1.1)
        self.assertTrue(np.isfinite(g).all())
        self.assertAlmostEqual(float(g[-1, -1]), 120.0, places=3)
        net = N.StrokeNet(self.path)
        grid = net.score_map(a, N.PIXEL_MM)
        self.assertTrue(np.isfinite(grid[~np.isnan(grid)]).all())
        self.assertTrue(np.isnan(grid[:, 0]).all())

    def test_score_map_and_region_score_keys(self):
        net = N.StrokeNet(self.path)
        ink = self.ink((600, 700), 5)
        ink[:200, :250] = 0                                    # an empty corner
        g = net.score_map(ink, 0.024)
        a = N.to_working(ink, 0.024)
        ys, xs, keep = N.layout(a, 32)
        self.assertEqual(g.shape, (len(ys), len(xs)))
        self.assertEqual(xs[-1], a.shape[1] - 128)             # the last window is aligned to the end
        self.assertTrue(np.array_equal(np.isnan(g), ~keep))
        r = net.region_score(ink, 0.024)
        self.assertEqual(set(r), {"learned_mean", "learned_max", "learned_top10", "learned_n", "learned_n_skipped",
                                  "learned_frac_above_val_blank_q99"})
        self.assertEqual(r["learned_n"], int(keep.sum()))
        self.assertEqual(r["learned_n_skipped"], int((~keep).sum()))
        self.assertGreater(r["learned_n_skipped"], 0)
        kept = g[keep]
        self.assertAlmostEqual(r["learned_mean"], float(kept.mean()), places=5)
        self.assertAlmostEqual(r["learned_frac_above_val_blank_q99"], float(np.mean(kept > 0.0)), places=9)
        i, j = np.argwhere(keep)[0]
        one = net.logits(a[None, ys[i]:ys[i] + 128, xs[j]:xs[j] + 128])[0]
        self.assertAlmostEqual(float(g[i, j]), float(one), places=4)
        p = os.path.join(self.tmp.name, "noq99.npz")
        write_random_net(p, meta={})
        r2 = N.StrokeNet(p).region_score(ink, 0.024)
        self.assertIsNone(r2["learned_frac_above_val_blank_q99"])
        empty = net.region_score(np.zeros((200, 200), np.uint8), N.PIXEL_MM)
        self.assertEqual((empty["learned_n"], empty["learned_n_skipped"], empty["learned_mean"]), (0, 16, None))

    # -------------------------------------------------------------- IAAFT
    def test_iaaft_keeps_values_and_spectrum_better_than_a_shuffle(self):
        self.assertEqual(N.IAAFT_ITERS, 200)
        rng = np.random.default_rng(7)
        y, x = np.mgrid[:64, :64]
        w = (np.sin(y / 3.0) > 0.3).astype(float) * 200 + rng.integers(0, 20, (64, 64))
        s = N.iaaft(w, np.random.default_rng(0), iters=50)
        self.assertEqual(s.shape, w.shape)
        self.assertTrue(np.array_equal(np.sort(s.ravel()), np.sort(w.ravel())))
        perm = w.ravel()[np.random.default_rng(1).permutation(w.size)].reshape(w.shape)
        amp = lambda a: np.abs(np.fft.rfft2(a))
        self.assertLess(np.abs(amp(s) - amp(w)).sum(), 0.5 * np.abs(amp(perm) - amp(w)).sum())
        stack = np.stack([w, w.T, w[::-1]])
        t = N.iaaft(stack, np.random.default_rng(2), iters=10)
        self.assertEqual(t.shape, stack.shape)
        for a, b in zip(t, stack):
            self.assertTrue(np.array_equal(np.sort(a.ravel()), np.sort(b.ravel())))
        again = N.iaaft(stack, np.random.default_rng(2), iters=10)
        self.assertTrue(np.array_equal(t, again))              # seeded
        self.assertEqual(N.iaaft(stack[:0], np.random.default_rng(0), iters=3).shape, (0, 64, 64))
        doc = " ".join(N.iaaft.__doc__.split())
        self.assertIn("excess of high-frequency power", doc)

    @unittest.skipIf(NL is None, "torch or scripts/strokenet/nulls.py not importable")
    def test_iaaft_follows_nulls_iaaft(self):
        rng = np.random.default_rng(14)
        y, x = np.mgrid[:128, :128]
        w = np.stack([((np.sin(y / 4.0 + i) > 0.2) * 120 + rng.integers(0, 40, (128, 128))) for i in range(3)])
        w = w.astype(np.float32)

        class SamePermutations:                                # the start permutations nulls.iaaft draws
            def __init__(self, seed):
                gen = torch.Generator().manual_seed(seed)
                self.p = list(torch.argsort(torch.rand((len(w), w[0].size), generator=gen), dim=1).numpy())

            def permutation(self, n):
                return self.p.pop(0)

        for iters, agree in ((0, 1.0), (1, 0.999), (5, 0.95)):
            ref = NL.iaaft(torch.from_numpy(w)[:, None], torch.Generator().manual_seed(0), iters)[:, 0].numpy()
            got = N.iaaft(w, SamePermutations(0), iters)
            # float64 here against float32 there: near-ties of the rank remap may resolve differently
            self.assertGreaterEqual(float((got == ref).mean()), agree, iters)

    # -------------------------------------------------------------- analyze and the CLI
    def test_analyze_controls_on_a_random_sample(self):
        ref = {"text": {"above_rot90": 0.9, "above_iaaft": 0.8, "mean_drop_iaaft": 1.5}, "blank": {"above_rot90": 0.5}}
        p = os.path.join(self.tmp.name, "ref.npz")
        write_random_net(p, meta={"val_blank_logit_q99": 0.0, "val_ref": ref})
        net = N.StrokeNet(p)
        ink = self.ink((300, 260), 8)
        ink[:, :20] = 0
        res, grid = N.analyze(ink, N.PIXEL_MM, net, sample=5, seed=3, iaaft_iters=10, with_grid=True)
        for k in ("map", "rotated_90", "controls", "orientation_hint", "note", "top_windows", "grid_shape"):
            self.assertIn(k, res)
        self.assertNotIn("arrangement", res)
        self.assertTrue(np.array_equal(np.isnan(grid), np.isnan(net.score_map(ink, N.PIXEL_MM))))
        kept = grid[np.isfinite(grid)]
        self.assertEqual(res["map"]["learned_n"], kept.size)
        self.assertEqual(res["map"]["learned_n_skipped"], int(np.isnan(grid).sum()))
        self.assertEqual(res["rotated_90"]["learned_n"], kept.size)
        c = res["controls"]
        self.assertEqual((c["windows"], c["seed"], c["iaaft"]["iterations"]), (5, 3, 10))
        for name in ("rot90", "iaaft"):
            self.assertTrue(0 <= c[name]["frac_above_copy"] <= 1)
        self.assertEqual(c["rot90"]["val_ref"], {"text": {"frac_above_copy": 0.9}, "blank": {"frac_above_copy": 0.5}})
        self.assertEqual(c["iaaft"]["val_ref"], {"text": {"frac_above_copy": 0.8, "mean_logit_drop": 1.5}})
        # the sample is drawn at random from the kept windows, not chosen by score
        pick = np.sort(np.random.default_rng(3).choice(kept.size, 5, replace=False))
        a = N.to_working(ink, N.PIXEL_MM)
        ys, xs, keep = N.layout(a, 32)
        pos = np.argwhere(keep)[pick]
        w = np.stack([a[ys[i]:ys[i] + 128, xs[j]:xs[j] + 128] for i, j in pos])
        turned = net.logits(np.rot90(w, 1, axes=(1, 2)))
        self.assertAlmostEqual(c["rot90"]["mean_logit_drop"], float(np.mean(kept[pick] - turned)), places=4)
        top = res["top_windows"]
        self.assertEqual(len(top), min(10, kept.size))
        self.assertAlmostEqual(top[0]["logit"], float(kept.max()), places=5)
        self.assertEqual([t["logit"] for t in top], sorted([t["logit"] for t in top], reverse=True))
        again = N.analyze(ink, N.PIXEL_MM, net, sample=5, seed=3, iaaft_iters=10)
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(res, sort_keys=True))
        s = N.text_summary(res)
        self.assertIn("not a reading", s)
        self.assertIn(f"{res['map']['learned_n_skipped']} skipped", s)
        self.assertIn("validation: blank 0.50, text 0.90", s)
        json.dumps(res)
        doc = " ".join(N.analyze.__doc__.split()) + " ".join(N.__doc__.split())
        self.assertIn("carry a small excess of high-frequency power", doc)
        self.assertNotIn("isolates", doc)

    def test_orientation_hint_ties_and_empty_maps(self):
        net = N.StrokeNet(self.path)
        flat = np.full((200, 200), 100, np.uint8)              # every window and its turned copy score the same
        res = N.analyze(flat, N.PIXEL_MM, net, sample=2, iaaft_iters=2)
        self.assertEqual(res["orientation_hint"], "no difference between the map as given and turned by 90 degrees")
        empty = N.analyze(np.ones((200, 200), np.float32), N.PIXEL_MM, net, sample=4)
        self.assertEqual((empty["map"]["learned_n"], empty["controls"]["windows"]), (0, 0))
        self.assertEqual(empty["orientation_hint"], "no window was scored")
        self.assertEqual(empty["top_windows"], [])
        self.assertIn("0 to 255 scale", N.text_summary(empty))
        json.dumps(empty)

    def test_open_map_keeps_the_dtype(self):
        with tempfile.TemporaryDirectory() as d:
            a = self.ink((30, 40), 15)
            np.save(os.path.join(d, "m.npy"), a)
            np.savez(os.path.join(d, "m.npz"), first=a.astype(np.uint16), second=a)
            with N.open_map(os.path.join(d, "m.npy")) as m:
                self.assertEqual((m.dtype, m.shape), (np.dtype(np.uint8), (30, 40)))
                self.assertTrue(np.array_equal(np.asarray(m), a))
            with N.open_map(os.path.join(d, "m.npz")) as m:
                self.assertEqual(m.dtype, np.dtype(np.uint16))
            with N.open_map(os.path.join(d, "m.npz"), "second") as m:
                self.assertEqual(m.dtype, np.dtype(np.uint8))
            try:
                import tifffile
            except ImportError:
                tifffile = None
            if tifffile is not None:                           # tiled TIFF, read lazily through zarr when present
                tifffile.imwrite(os.path.join(d, "m.tif"), a, tile=(16, 16))
                with N.open_map(os.path.join(d, "m.tif")) as m:
                    self.assertEqual((np.dtype(m.dtype), tuple(m.shape)), (np.dtype(np.uint8), (30, 40)))
                    got = N.to_working(m, N.PIXEL_MM / 2, strip=4)
                self.assertTrue(np.array_equal(got, N.to_working(a, N.PIXEL_MM / 2)))
            try:
                from PIL import Image
            except ImportError:
                return
            Image.fromarray(a).save(os.path.join(d, "m.png"))
            Image.fromarray(np.stack([a] * 3, axis=-1)).save(os.path.join(d, "rgb.png"))
            for name in ("m.png", "rgb.png"):
                with N.open_map(os.path.join(d, name)) as m:
                    self.assertEqual(m.dtype, np.dtype(np.uint8))
                    self.assertTrue(np.array_equal(m, a))

    def test_resolve_weights_checks_sha256(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cache = d / "cache"
            cache.mkdir()
            data = Path(self.path).read_bytes()
            (cache / "net.npz").write_bytes(data)
            reg = d / "reg.json"
            entry = {"file": "net.npz", "sha256": hashlib.sha256(data).hexdigest(), "url": ""}
            reg.write_text(json.dumps({"models": {"demo": entry}}))
            self.assertEqual(N.resolve_weights("demo", cache=cache, registry=reg), cache / "net.npz")
            self.assertEqual(N.resolve_weights(self.path, registry=reg), Path(self.path))
            entry["sha256"] = "0" * 64
            reg.write_text(json.dumps({"models": {"demo": entry}}))
            with self.assertRaises(ValueError):
                N.resolve_weights("demo", cache=cache, registry=reg)
            with self.assertRaises(ValueError):
                N.resolve_weights("other", cache=cache, registry=reg)
            (cache / "net.npz").unlink()
            with self.assertRaises(ValueError):                  # no address yet
                N.resolve_weights("demo", cache=cache, registry=reg)

    def test_registry_names_a_default_model(self):
        models = N.released_weights()
        self.assertIn(N.DEFAULT, models)
        m = models[N.DEFAULT]
        for k in ("file", "sha256", "url", "licence", "card"):
            self.assertIn(k, m)

    def test_orientation_hint_falls_back_to_the_mean_logit(self):
        p = os.path.join(self.tmp.name, "q99.npz")
        write_random_net(p, meta={"val_blank_logit_q99": 50.0})   # no window reaches it, as given or turned
        net = N.StrokeNet(p)
        y = np.arange(400)[:, None] + np.zeros((1, 400))
        ink = np.where((y // 6) % 2 == 0, 200, 30).astype(np.uint8)   # horizontal bands
        res = N.analyze(ink, N.PIXEL_MM, net, sample=4)
        self.assertEqual(res["map"]["learned_frac_above_val_blank_q99"], res["rotated_90"]["learned_frac_above_val_blank_q99"])
        self.assertEqual(res["orientation_hint_from"], "learned_mean")
        if res["map"]["learned_mean"] != res["rotated_90"]["learned_mean"]:
            self.assertNotIn("no difference", res["orientation_hint"])
        a = N.to_working(ink, N.PIXEL_MM)
        ys, xs, _ = N.layout(a, 32)
        self.assertEqual((res["window_y_px"], res["window_x_px"]), (ys, xs))

    def test_snap_crop_keeps_the_training_lattice(self):
        self.assertEqual(N.snap_crop((700, 2000, 1300, 3000), 0.0024), ([640, 2000, 1280, 3000], True))
        self.assertEqual(N.snap_crop((1280, 2000, 640, 3000), 0.0024), ([1280, 2000, 640, 3000], False))
        self.assertEqual(N.snap_crop((40, 300, 70, 300), N.PIXEL_MM), ([32, 300, 64, 300], True))
        self.assertEqual(N.snap_crop((7, 300, 9, 300), 0.005), ([7, 300, 9, 300], False))   # not a whole fraction
        self.assertEqual(N.snap_crop((0, 5000, 33, 200), N.PIXEL_MM, shape=(300, 300)), ([0, 300, 32, 200], True))
        for bad in ((10, 5, 0, 9), (0, 9, 4, 4), (-1, 9, 0, 9)):
            with self.assertRaises(ValueError):
                N.snap_crop(bad, 0.0024)
        with self.assertRaises(ValueError):                    # wholly outside the map
            N.snap_crop((400, 500, 0, 9), N.PIXEL_MM, shape=(300, 300))
        # where a snapped crop and the full map both keep a window, its logit is the same
        net = N.StrokeNet(self.path)
        ink = self.ink((900, 900), 4)
        full = net.score_map(ink, 0.024)
        used, _ = N.snap_crop((100, 900, 130, 900), 0.024)
        part = net.score_map(ink[used[0]:used[1], used[2]:used[3]], 0.024)
        oy, ox = used[0] // 2 // 32, used[2] // 2 // 32
        a, b = full[oy:oy + part.shape[0] - 1, ox:ox + part.shape[1] - 1], part[:-1, :-1]
        both = ~np.isnan(a) & ~np.isnan(b)
        self.assertGreater(int(both.sum()), 0)
        self.assertTrue(np.allclose(a[both], b[both], atol=1e-5))

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "map.npy")
            ink = self.ink((200, 200), 9)
            ink[:, :30] = 0
            np.save(mp, ink)
            gp = os.path.join(d, "grid.npy")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.main(["strokenet", mp, "--pixel-mm", "0.048", "--weights", self.path, "--json",
                               "--sample", "2", "--grid", gp])
            self.assertEqual(rc, 0)
            res = json.loads(out.getvalue())
            self.assertEqual((res["controls"]["windows"], res["controls"]["iaaft"]["iterations"]), (2, 200))
            g = np.load(gp)
            self.assertEqual(int(np.isnan(g).sum()), res["map"]["learned_n_skipped"])
            self.assertGreater(res["map"]["learned_n_skipped"], 0)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):                # np.save adds .npy; the result names the real file
                rc = cli.main(["strokenet", mp, "--pixel-mm", "0.048", "--weights", self.path, "--json",
                               "--sample", "1", "--grid", os.path.join(d, "g2"), "--crop", "0", "200", "20", "200"])
            self.assertEqual(rc, 0)
            res = json.loads(out.getvalue())
            self.assertEqual(res["grid_file"], os.path.join(d, "g2.npy"))
            self.assertTrue(os.path.exists(res["grid_file"]))
            self.assertEqual(res["crop"], {"requested": [0, 200, 20, 200], "used": [0, 200, 0, 200],
                                           "origin_moved_to_lattice": True})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):                # the old option name still works
                rc = cli.main(["strokenet", mp, "--pixel-mm", "0.048", "--weights", self.path, "--top", "1",
                               "--crop", "0", "200", "20", "200"])
            self.assertEqual(rc, 0)
            self.assertIn("skipped (under 99 % core papyrus)", out.getvalue())
            self.assertIn("1 random windows above their IAAFT copies", out.getvalue())
            self.assertIn("not a reading", out.getvalue())
            for argv in (["--weights", os.path.join(d, "missing.npz")],
                         ["--weights", self.path, "--crop", "0", "100", "0", "200"]):     # missing file; map too small
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = cli.main(["strokenet", mp, "--pixel-mm", "0.048"] + argv)
                self.assertEqual(rc, 2)
                self.assertTrue(err.getvalue())


if __name__ == "__main__":
    unittest.main()
