import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from kit import cli, rowscore, verify

try:
    import numpy as np
    import tifffile
except ImportError:  # the core kit is standard library only
    np = tifffile = None

VOXEL_UM = 9.362


def rows_map(period_mm=5.0, shape=(1600, 1600), seed=0):
    """Horizontal rows of bright strokes every period_mm on a noisy background, as uint8."""
    rng = np.random.default_rng(seed)
    image = rng.normal(64, 12, size=shape)
    period_px = period_mm * 1000 / VOXEL_UM
    rows = np.arange(shape[0])
    in_row = (rows % period_px) < period_px * 0.35
    strokes = (np.arange(shape[1]) // 12) % 3 != 0
    image[np.ix_(in_row, strokes)] = 190
    return np.clip(image, 3, 255).astype(np.uint8)


def speckle_map(shape=(1600, 1600), seed=1):
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(80, 30, size=shape), 3, 255).astype(np.uint8)


@unittest.skipIf(np is None, "numpy and tifffile are needed for kit rowscore")
class RowScoreArrayTest(unittest.TestCase):
    def test_rows_score_high_at_their_period(self):
        r = rowscore.score_array(rows_map(5.0), VOXEL_UM)
        self.assertGreater(r["score"], 50)
        self.assertAlmostEqual(r["period_mm"], 5.0, delta=0.6)
        self.assertAlmostEqual(abs(r["angle_deg"]), 90, delta=5)

    def test_speckle_scores_low(self):
        r = rowscore.score_array(speckle_map(), VOXEL_UM)
        self.assertLess(r["score"], 20)

    def test_period_outside_band_is_not_rows(self):
        fine = rowscore.score_array(rows_map(1.0), VOXEL_UM)
        self.assertLess(fine["score"], rowscore.score_array(rows_map(5.0), VOXEL_UM)["score"] / 3)

    def test_small_map_gets_no_score(self):
        r = rowscore.score_array(rows_map(5.0, shape=(200, 200)), VOXEL_UM)
        self.assertIsNone(r["score"])
        self.assertIn("too small", r["reason"])

    def test_float_probabilities_match_uint8(self):
        a = rows_map(5.0)
        self.assertAlmostEqual(rowscore.score_array(a, VOXEL_UM)["score"],
                               rowscore.score_array(a.astype(np.float32) / 255, VOXEL_UM)["score"], delta=0.2)

    def test_mean_map_rejects_shape_mismatch(self):
        with self.assertRaises(verify.VerifyError):
            rowscore.mean_map([rows_map(shape=(400, 400)), rows_map(shape=(400, 500))])

    def test_holes_in_the_surface_erode_their_neighbourhood(self):
        a = rows_map(5.0)
        a[::40, ::40] = 0  # outside-surface pixels on a grid: nothing survives a 31 px erosion
        self.assertIsNone(rowscore.score_array(a, VOXEL_UM)["score"])

    def test_area_resize_matches_block_mean_on_whole_factors(self):
        a = np.arange(48, dtype=np.float32).reshape(6, 8)
        expected = a.reshape(3, 2, 4, 2).mean(axis=(1, 3))
        np.testing.assert_allclose(rowscore._area_resize(np, a, 2), expected, rtol=1e-6)

    def test_area_resize_keeps_the_mean_on_fractional_factors(self):
        a = np.random.default_rng(3).random((1503, 1711)).astype(np.float32)
        out = rowscore._area_resize(np, a, 4)
        self.assertEqual(out.shape, (375, 427))
        self.assertAlmostEqual(float(out.mean()), float(a.mean()), places=3)

    def test_erode_square(self):
        mask = np.zeros((9, 9), dtype=bool)
        mask[1:8, 1:8] = True
        eroded = rowscore._erode(np, mask, 3)
        self.assertEqual(int(eroded.sum()), 25)
        self.assertTrue(eroded[2:7, 2:7].all())
        self.assertTrue(rowscore._erode(np, np.ones((5, 5), dtype=bool), 3).all())  # the image edge does not erode


@unittest.skipIf(np is None, "numpy and tifffile are needed for kit rowscore")
class RowScoreCliTest(unittest.TestCase):
    def test_forward_and_reverse(self):
        with tempfile.TemporaryDirectory() as tmp:
            fwd = [Path(tmp, f"f{i}.tif") for i in range(2)]
            for i, path in enumerate(fwd):
                tifffile.imwrite(path, rows_map(5.0, seed=i))
            rev = Path(tmp, "r.tif")
            tifffile.imwrite(rev, speckle_map())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["rowscore", *map(str, fwd), "--reverse", str(rev),
                                 "--voxel-um", str(VOXEL_UM), "--json"])
            self.assertEqual(code, 0)
            result = json.loads(out.getvalue())
            self.assertGreater(result["forward"]["score"], 3 * result["reverse"]["score"])
            self.assertEqual(len(result["files"]["forward"]), 2)


if __name__ == "__main__":
    unittest.main()
