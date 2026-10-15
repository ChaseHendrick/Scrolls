import tempfile
import unittest
from pathlib import Path

from kit import auc, overlap

try:
    import numpy as np
    import scipy  # noqa: F401
    import tifffile
except ImportError:
    np = None


def write_mesh(d, z):
    d.mkdir(parents=True)
    yy, xx = np.mgrid[0:30, 0:40].astype(np.float32)
    for c, a in zip("xyz", (xx * 20 + 100, yy * 20 + 100, np.full_like(xx, z))):
        tifffile.imwrite(str(d / f"{c}.tif"), a)


@unittest.skipIf(np is None, "numpy, scipy and tifffile are needed")
class OverlapTest(unittest.TestCase):
    def test_same_sheet_and_separate(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            write_mesh(t / "a", 500); write_mesh(t / "b", 503); write_mesh(t / "c", 700)
            same = overlap.overlap(t / "a", t / "b", 9.366)
            self.assertAlmostEqual(same["a_to_b"]["median_gap_vox"], 3.0, places=1)
            self.assertEqual(same["same_sheet_share"], 1.0)
            self.assertEqual(overlap.overlap(t / "a", t / "c", 9.366)["same_sheet_share"], 0.0)

    def test_collate_agrees_on_a_copy_not_on_noise(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            write_mesh(t / "a", 500); write_mesh(t / "b", 502)
            rng = np.random.default_rng(0)
            from scipy.ndimage import gaussian_filter
            m = gaussian_filter(rng.random((600, 800)), 8) + 1
            np.save(t / "ma.npy", m); np.save(t / "mb.npy", m)
            np.save(t / "noise.npy", gaussian_filter(rng.random((600, 800)), 8) + 1)
            r = overlap.collate(t / "a", t / "b", t / "ma.npy", t / "mb.npy", 9.366, gaps=(0, 5),
                                control_a=t / "ma.npy", control_b=t / "noise.npy", draws=10)
            row = r["bins"][0]
            self.assertGreater(row["map"]["pearson"], 0.95)
            self.assertGreater(row["map"]["reappear"], 0.8)
            self.assertLess(abs(row["control"]["pearson"]), 0.5)


@unittest.skipIf(np is None, "numpy is needed")
class BootstrapTest(unittest.TestCase):
    def test_interval_holds_the_estimate_and_compare_sees_a_better_map(self):
        rng = np.random.default_rng(0)
        ink = np.zeros((400, 400), bool); ink[:, ::8] = True
        mask = np.ones_like(ink)
        good = np.clip(ink * 120 + rng.normal(100, 30, ink.shape), 1, 255).astype(np.uint8)
        bad = np.clip(ink * 40 + rng.normal(100, 30, ink.shape), 1, 255).astype(np.uint8)
        point = auc.score_array(good, ink, mask)["auc"]
        b = auc.block_bootstrap(good, ink, mask, draws=50, block_px=50, other=bad)
        self.assertLessEqual(b["ci95"][0], point + 0.01)
        self.assertGreaterEqual(b["ci95"][1], point - 0.01)
        self.assertGreater(b["compare"]["ci95"][0], 0)
        same = auc.block_bootstrap(good, ink, mask, draws=50, block_px=50, other=good)
        self.assertEqual(same["compare"]["difference"], 0)


if __name__ == "__main__":
    unittest.main()
