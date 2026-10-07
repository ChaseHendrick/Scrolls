import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from kit import auc, cli, verify

try:
    import numpy as np
    import tifffile
    import zarr
except ImportError:  # the core kit is standard library only
    np = tifffile = zarr = None


@unittest.skipIf(zarr is None, "numpy, tifffile and zarr are needed for kit auc")
class AucScoresTest(unittest.TestCase):
    def test_perfect_random_and_inverted(self):
        self.assertEqual(auc.auc_scores(np.array([200, 210], np.uint8), np.array([10, 20, 30], np.uint8)), 1.0)
        self.assertEqual(auc.auc_scores(np.array([10], np.uint8), np.array([200], np.uint8)), 0.0)
        self.assertEqual(auc.auc_scores(np.array([5, 5], np.uint8), np.array([5], np.uint8)), 0.5)

    def test_matches_pairwise_definition(self):
        rng = np.random.default_rng(0)
        a = rng.integers(0, 256, 300).astype(np.uint8)
        b = rng.integers(0, 200, 400).astype(np.uint8)
        pairs = (a[:, None] > b[None, :]).mean() + 0.5 * (a[:, None] == b[None, :]).mean()
        self.assertAlmostEqual(auc.auc_scores(a, b), float(pairs), places=10)

    def test_floats_and_uint16_agree(self):
        rng = np.random.default_rng(1)
        p = rng.random(500).astype(np.float32)
        ink, bg = p[:200] * 0.5 + 0.5, p[200:] * 0.6
        u16 = lambda x: np.round(x * 65535).astype(np.uint16)
        self.assertAlmostEqual(auc.auc_scores(ink, bg), auc.auc_scores(u16(ink), u16(bg)), places=6)

    def test_empty_class_gives_none(self):
        self.assertIsNone(auc.auc_scores(np.array([], np.uint8), np.array([1], np.uint8)))


@unittest.skipIf(zarr is None, "numpy, tifffile and zarr are needed for kit auc")
class AucFilesTest(unittest.TestCase):
    """Labels on a grid 0.97 the size of the map, as for w045 (5,820 x 8,020 vs 5,980 x 8,240)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.surface = (300, 400)
        lh, lw = 291, 388
        labels = np.zeros((lh, lw), np.uint8)
        labels[50:60, :] = 255
        labels[150:160, :] = 255
        mask = np.zeros((lh, lw), np.uint8)
        mask[30:200, 20:360] = 255
        for name, data in (("inklabels", labels), ("supervision", mask)):
            g = zarr.open_group(str(self.root / f"{name}.zarr"), mode="w")
            g.create_array("0", data=np.repeat(np.repeat(data, 4, 0), 4, 1))
            g.create_array("2", data=data)
        rows = np.arange(self.surface[0])[:, None] * lh / self.surface[0]
        on_ink = ((rows >= 50) & (rows < 60)) | ((rows >= 150) & (rows < 160))
        self.forward = np.where(on_ink, 200, 70).astype(np.uint8) * np.ones(self.surface, np.uint8)
        self.reverse = np.full(self.surface, 90, np.uint8)
        self.reverse[::2] = 91
        tifffile.imwrite(self.root / "fwd.tif", self.forward)
        tifffile.imwrite(self.root / "rev.tif", self.reverse)

    def tearDown(self):
        self.tmp.cleanup()

    def files(self, **kw):
        r = self.root
        return auc.score_files(r / "fwd.tif", r / "inklabels.zarr", r / "supervision.zarr", **kw)

    def test_forward_reads_ink_and_reverse_does_not(self):
        result = self.files(control=self.root / "rev.tif")
        self.assertGreater(result["forward"]["auc"], 0.95)
        self.assertLess(abs(result["control"]["auc"] - 0.5), 0.1)
        self.assertGreater(result["forward"]["ink_px"], 0)

    def test_crop_lines_up_with_the_full_map(self):
        crop = (40, 200, 50, 300)
        y0, y1, x0, x1 = crop
        tifffile.imwrite(self.root / "crop.tif", self.forward[y0:y1, x0:x1])
        full = self.files()["forward"]
        part = auc.score_files(self.root / "crop.tif", self.root / "inklabels.zarr", self.root / "supervision.zarr",
                               crop=crop, surface_shape=self.surface)["forward"]
        self.assertGreater(part["auc"], 0.95)
        self.assertAlmostEqual(part["auc"], full["auc"], delta=0.02)

    def test_unpredicted_pixels_are_left_out(self):
        zeroed = self.forward.copy()
        zeroed[:, :100] = 0
        tifffile.imwrite(self.root / "fwd.tif", zeroed)
        r = self.files()["forward"]
        self.assertGreater(r["unpredicted_px_in_mask"], 0)
        self.assertGreater(r["auc"], 0.95)

    def test_anisotropic_grid_is_refused(self):
        with self.assertRaises(verify.VerifyError):
            auc.label_grid((291, 388), (300, 300), None, (300, 300))

    def test_crop_needs_surface_shape(self):
        with self.assertRaises(verify.VerifyError):
            self.files(crop=(0, 10, 0, 10))

    def test_cli(self):
        r = self.root
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["auc", str(r / "fwd.tif"), "--labels", str(r / "inklabels.zarr"),
                             "--mask", str(r / "supervision.zarr"), "--control", str(r / "rev.tif"), "--json"])
        self.assertEqual(code, 0)
        self.assertGreater(json.loads(out.getvalue())["forward"]["auc"], 0.95)


if __name__ == "__main__":
    unittest.main()
