import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import cli, ensemble, verify

try:
    import numpy as np
    import tifffile
except ImportError:  # the core kit is standard library only
    np = tifffile = None


@unittest.skipIf(tifffile is None, "numpy and tifffile are needed for kit ensemble")
class EnsembleTest(unittest.TestCase):
    def test_mean_scales_each_dtype_and_keeps_no_prediction_pixels_out(self):
        a = np.array([[255, 0], [51, 102]], np.uint8)
        b = np.array([[65535, 65535], [0, 13107]], np.uint16)
        out, valid = ensemble.combine([a, b])
        self.assertEqual(valid.tolist(), [[True, False], [False, True]])
        self.assertAlmostEqual(out[0, 0], 1.0)
        self.assertAlmostEqual(out[1, 1], (0.4 + 0.2) / 2)
        self.assertEqual(out[0, 1], 0.0)

    def test_weights(self):
        a = np.full((2, 2), 255, np.uint8)
        b = np.full((2, 2), 51, np.uint8)
        out, _ = ensemble.combine([a, b], weights=[3, 1])
        self.assertAlmostEqual(out[0, 0], (3 * 1.0 + 0.2) / 4)

    def test_rank_ignores_each_map_s_scale(self):
        rng = np.random.default_rng(0)
        x = rng.integers(1, 256, (16, 16)).astype(np.uint8)
        squeezed = (30000 + x.astype(np.uint16))  # same order, a narrow band of the uint16 range
        out, _ = ensemble.combine([x, squeezed], method="rank")
        alone, _ = ensemble.combine([x, x], method="rank")
        np.testing.assert_allclose(out, alone)

    def test_rank_ties_share_a_rank(self):
        a = np.array([[5, 5, 9]], np.uint8)
        out, _ = ensemble.combine([a, a], method="rank")
        self.assertEqual(out[0, 0], out[0, 1])
        self.assertEqual(out[0, 2], 1.0)

    def test_refuses_bad_input(self):
        a = np.ones((2, 2), np.uint8)
        with self.assertRaises(verify.VerifyError):
            ensemble.combine([a])
        with self.assertRaises(verify.VerifyError):
            ensemble.combine([a, np.ones((2, 3), np.uint8)])
        with self.assertRaises(verify.VerifyError):
            ensemble.combine([a, a], weights=[1])
        with self.assertRaises(verify.VerifyError):
            ensemble.combine([a, a], method="median")

    def test_files_round_trip_keeps_valid_pixels_above_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = np.array([[1, 0], [200, 255]], np.uint8)
            b = np.array([[1, 7], [100, 255]], np.uint8)
            tifffile.imwrite(root / "a.tif", a)
            tifffile.imwrite(root / "b.tif", b)
            for name in ("e.tif", "e.npy"):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = cli.main(["ensemble", str(root / name), str(root / "a.tif"), str(root / "b.tif")])
                self.assertEqual(code, 0)
                self.assertIn("3 valid px", out.getvalue())
                got = np.load(root / name) if name.endswith(".npy") else tifffile.imread(root / name)
                self.assertEqual(got[0, 1], 0)
                self.assertTrue((got[np.array([[1, 0], [1, 1]], bool)] > 0).all())
                self.assertGreater(got[1, 1], got[1, 0])



def reference_ranks(np, v, valid, a=None):
    """ensemble._ranks as it was: a stable argsort, then np.unique and bincount for the tie means."""
    out = np.zeros_like(v)
    x = v[valid]
    if x.size:
        order = np.argsort(x, kind="stable")
        r = np.empty(x.size, np.float64)
        r[order] = np.arange(x.size, dtype=np.float64)
        uniq, inv = np.unique(x, return_inverse=True)
        sums = np.bincount(inv, weights=r, minlength=uniq.size)
        counts = np.bincount(inv, minlength=uniq.size)
        r = (sums / counts)[inv]
        out[valid] = r / max(x.size - 1, 1)
    return out


@unittest.skipIf(np is None, "numpy is needed for kit ensemble")
class RankFastPathTest(unittest.TestCase):
    """The histogram ranks of integer maps give the same bits as the sort they replace."""

    def assertSameBits(self, got, want):
        self.assertEqual((got.dtype, got.shape), (want.dtype, want.shape))
        self.assertEqual(got.tobytes(), want.tobytes())

    def maps(self):
        rng = np.random.default_rng(21)
        yield rng.integers(0, 256, (60, 70)).astype(np.uint8)
        yield rng.integers(0, 65536, (60, 70)).astype(np.uint16)
        yield rng.integers(0, 3, (40, 40)).astype(np.uint16)            # heavy ties
        yield np.full((9, 9), 200, np.uint8)                             # constant
        yield np.zeros((5, 5), np.uint8)                                 # nothing valid
        one = np.zeros((4, 4), np.uint16)
        one[2, 1] = 40000
        yield one                                                        # one valid pixel

    def test_ranks_match_the_sort(self):
        rng = np.random.default_rng(22)
        for a in self.maps():
            for valid in (a != 0, (a != 0) & (rng.random(a.shape) < 0.5)):
                v = ensemble._unit(np, a)
                with mock.patch("numpy.unique", side_effect=AssertionError("the sort path ran")):
                    got = ensemble._ranks(np, v, valid, a)
                self.assertSameBits(got, reference_ranks(np, v, valid))
                with mock.patch.object(ensemble, "_EXACT_SUM", 0):   # group sums too big: the sort path
                    self.assertSameBits(ensemble._ranks(np, v, valid, a), reference_ranks(np, v, valid))
                self.assertSameBits(ensemble._ranks(np, v, valid), reference_ranks(np, v, valid))

    def test_exact_sum_guard_boundary(self):
        # The histogram path runs only while the largest tie group's rank sum, the biggest number the sort
        # path's float64 bincount adds up, stays below _EXACT_SUM; at the sum itself the sort path runs.
        rng = np.random.default_rng(24)
        a = rng.integers(0, 3, (40, 40)).astype(np.uint16)
        for valid in (a != 0, (a != 0) & (rng.random(a.shape) < 0.5)):
            counts = np.bincount(a[valid]).tolist()
            below = [sum(counts[:i]) for i in range(len(counts))]
            biggest = max(sum(range(b, b + c)) for b, c in zip(below, counts))   # 0-based ranks, Python ints
            self.assertGreater(biggest, max(counts))
            v = ensemble._unit(np, a)
            want = reference_ranks(np, v, valid)
            for limit, sort_path in ((biggest, True), (biggest + 1, False)):
                with mock.patch.object(ensemble, "_EXACT_SUM", limit), \
                        mock.patch("numpy.unique", wraps=np.unique) as unique:
                    got = ensemble._ranks(np, v, valid, a)
                self.assertEqual(unique.called, sort_path, limit)
                self.assertSameBits(got, want)

    def test_rank_combine_matches_the_sort(self):
        rng = np.random.default_rng(23)
        f = rng.random((60, 70)).astype(np.float32)
        f[5, 5] = np.nan
        f[::9] = 0.0
        maps = list(self.maps())[:3]
        mixed = [maps[0], maps[1], f]
        ties = [maps[2], maps[2][::-1].copy()]
        for arrays in (mixed, ties):
            for weights in (None, [2.0] + [1.0] * (len(arrays) - 1)):
                got = ensemble.combine(arrays, "rank", weights)
                with mock.patch.object(ensemble, "_ranks", reference_ranks):
                    want = ensemble.combine(arrays, "rank", weights)
                self.assertSameBits(got[0], want[0])
                self.assertSameBits(got[1], want[1])


if __name__ == "__main__":
    unittest.main()
