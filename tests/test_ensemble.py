import contextlib
import io
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
