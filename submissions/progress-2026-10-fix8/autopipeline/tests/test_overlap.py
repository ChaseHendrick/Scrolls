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

    def test_union_area_counts_one_sheet_once(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            write_mesh(t / "a", 500); write_mesh(t / "b", 501); write_mesh(t / "c", 700)
            one = overlap.union_area([t / "a", t / "b"], 9.366)
            self.assertAlmostEqual(one["union_cm2"], one["sum_cm2"] / 2, places=4)
            self.assertAlmostEqual(one["double_counted_cm2"], one["sum_cm2"] / 2, places=4)
            two = overlap.union_area([t / "a", t / "c"], 9.366)       # 200 voxels apart: two sheets
            self.assertEqual(two["union_cm2"], two["sum_cm2"])
            given = overlap.union_area([t / "a", t / "b"], 9.366, areas={str(t / "a"): 3.0, str(t / "b"): 2.0})
            self.assertEqual((given["sum_cm2"], given["union_cm2"]), (5.0, 3.0))
            self.assertEqual(given["meshes"][0]["mesh"], str(t / "a"))   # the larger trace counts whole

    def test_union_area_keeps_a_neighbouring_winding(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            write_mesh(t / "a", 500); write_mesh(t / "b", 507)       # 66 um apart at 9.4 um: the next winding
            r = overlap.union_area([t / "a", t / "b"], 9.366)
            self.assertEqual(r["union_cm2"], r["sum_cm2"])

    def test_one_sided_labels_or_control_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            write_mesh(t / "a", 500); write_mesh(t / "b", 502)
            np.save(t / "m.npy", np.ones((600, 800)))
            for kw in ({"labels_a": t / "la"}, {"labels_b": t / "lb"}):
                with self.assertRaisesRegex(overlap.VerifyError, "both"):
                    overlap.overlap(t / "a", t / "b", 9.366, **kw)
            for kw in ({"control_a": t / "m.npy"}, {"control_b": t / "m.npy"}):
                with self.assertRaisesRegex(overlap.VerifyError, "both"):
                    overlap.collate(t / "a", t / "b", t / "m.npy", t / "m.npy", 9.366, gaps=(0, 5), draws=2, **kw)


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
