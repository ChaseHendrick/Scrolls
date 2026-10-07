import contextlib
import io
import json
import tempfile
import unittest
import sys
from pathlib import Path
from unittest import mock

from kit import cli, rowscore, verify

try:
    import numpy as np
    import tifffile
    import scipy.sparse
except ImportError:
    np = None


@unittest.skipIf(np is None, "numpy, scipy and tifffile are needed")
class SparseRowResizeTest(unittest.TestCase):
    def test_overlap_coefficients_match_dense_including_fractional_edges(self):
        for n in (64, 65, 83, 639, 641):
            with self.subTest(n=n):
                sparse = rowscore._sparse_area_weights(np, n, n // 4)
                np.testing.assert_array_equal(sparse.toarray(), rowscore._area_weights(np, n, n // 4))
                self.assertLessEqual(sparse.nnz, n + n // 4)

    def test_default_never_calls_sparse_and_keeps_original_record(self):
        a = np.full((256, 320), 128, dtype=np.uint8)
        original = rowscore.score_array(a, 9.362)
        with mock.patch.object(rowscore, "_sparse_area_resize", side_effect=AssertionError("opt-in only")):
            self.assertEqual(rowscore.score_array(a, 9.362, fast_resize=False), original)
        self.assertNotIn("resize_mode", original)
        self.assertNotIn("resize_note", original)
        record = {"forward": original}
        self.assertNotIn("--fast-resize", rowscore.format_result(record))

    def test_finite_probability_resize_matches_with_float32_rounding_tolerance(self):
        a = np.random.default_rng(37).random((65, 83), dtype=np.float32)
        dense = rowscore._area_resize(np, a, 4)
        fast = rowscore._sparse_area_resize(np, a, 4)
        np.testing.assert_allclose(fast, dense, rtol=1e-6, atol=3e-7)
        # A displaced input must fail the same comparison, so the parity check can fail.
        displaced = rowscore._sparse_area_resize(np, np.roll(a, 17, axis=0), 4)
        self.assertFalse(np.allclose(displaced, dense, rtol=1e-6, atol=3e-7))

    def test_nondegenerate_fractional_grid_scores_agree_with_rounding_tolerance(self):
        y, x = np.indices((1023, 1023))
        noise = np.random.default_rng(21).normal(0, .02, y.shape)
        a = (.5 + .15 * np.cos(2 * np.pi * y * 3 / 1023) + noise).astype(np.float32)
        valid = np.ones(a.shape, dtype=bool)
        dense = rowscore.score_array(a, 9.366, valid)
        fast = rowscore.score_array(a, 9.366, valid, fast_resize=True)
        self.assertIsNotNone(dense["score"])
        self.assertAlmostEqual(fast["period_mm"], dense["period_mm"], delta=.01)
        np.testing.assert_allclose(fast["score"], dense["score"], rtol=1e-5, atol=.2)
        angle_gap = (fast["angle_deg"] - dense["angle_deg"] + 90) % 180 - 90
        self.assertLess(abs(angle_gap), .2)
        for key in ("valid_px", "largest_piece", "mean_ink", "p99", "frac_gt_half"):
            self.assertEqual(fast[key], dense[key])
        self.assertEqual(fast["resize_mode"], "sparse_area_float32")
        self.assertIn("near-tied FFT peaks", fast["resize_note"])

    def test_tied_spectrum_allows_either_orientation_and_mirrored_peak(self):
        y, x = np.indices((1023, 1023))
        a = (.5 + .1 * np.cos(2 * np.pi * y * 3 / 1023)
             + .1 * np.cos(2 * np.pi * x * 3 / 1023)).astype(np.float32)
        valid = np.ones(a.shape, dtype=bool)
        for fast in (False, True):
            result = rowscore.score_array(a, 9.366, valid, fast_resize=fast)
            self.assertIsNotNone(result["score"])
            self.assertGreater(result["period_mm"], 3.1)
            self.assertLess(result["period_mm"], 3.3)
            self.assertIn(result["angle_deg"], (0., 90., -90., 180., -180.))

    def test_missing_scipy_is_an_explicit_opt_in_error(self):
        with mock.patch.dict(sys.modules, {"scipy.sparse": None}):
            with self.assertRaisesRegex(verify.VerifyError, "--fast-resize requires scipy"):
                rowscore._sparse_area_weights(np, 65, 16)

    def test_nonfinite_values_keep_dense_propagation_and_abstention(self):
        a = np.full((200, 200), .5, dtype=np.float32)
        a[80, 80] = np.nan
        dense = rowscore.score_array(a, 9.366)
        with mock.patch.object(rowscore, "_sparse_area_resize", side_effect=AssertionError("must fall back")):
            fast = rowscore.score_array(a, 9.366, fast_resize=True)
        self.assertEqual({key: fast[key] for key in dense}, dense)
        self.assertEqual(fast["resize_mode"], "dense_nonfinite_fallback")

    def test_cli_marks_both_depth_directions_only_when_opted_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "map.tif"
            tifffile.imwrite(image, np.full((256, 320), 128, dtype=np.uint8))
            results = {}
            for fast in (False, True):
                args = ["rowscore", str(image), "--reverse", str(image), "--voxel-um", "9.366", "--json"]
                if fast:
                    args.append("--fast-resize")
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream):
                    self.assertEqual(cli.main(args), 0)
                results[fast] = json.loads(stream.getvalue())
            self.assertNotIn("fast_resize", results[False])
            self.assertTrue(results[True]["fast_resize"])
            for direction in ("forward", "reverse"):
                self.assertNotIn("resize_mode", results[False][direction])
                self.assertEqual(results[True][direction]["resize_mode"], "sparse_area_float32")


if __name__ == "__main__":
    unittest.main()
