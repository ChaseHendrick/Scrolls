import contextlib
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from kit import auc, aucreport, finite, verify

try:
    import numpy as np
    import tifffile
    import zarr
except ImportError:  # the core kit is standard library only
    np = tifffile = zarr = None


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = aucreport.main(argv)
    return code, out.getvalue(), err.getvalue()


@unittest.skipIf(np is None, "numpy is needed for kit.aucreport")
class CurvesTest(unittest.TestCase):
    def _hist(self, a, b):
        return (np.bincount(a, minlength=aucreport.LEVELS).astype(float),
                np.bincount(b, minlength=aucreport.LEVELS).astype(float))

    def test_roc_area_is_the_mann_whitney_auc_and_ap_matches_the_step_sum(self):
        rng = np.random.default_rng(3)
        a = rng.integers(20, 60, 400)          # few levels: many ties
        b = rng.integers(0, 50, 900)
        cs = aucreport.curve_stats(*self._hist(a, b))
        self.assertAlmostEqual(cs["auc"], round(auc.auc_scores(a.astype(np.int64), b.astype(np.int64)), 4), places=4)
        ap, prev_r = 0.0, 0.0
        for t in sorted(set(a) | set(b), reverse=True):   # brute force, one threshold per distinct score
            tp, fp = (a >= t).sum(), (b >= t).sum()
            r = tp / len(a)
            ap += (r - prev_r) * tp / (tp + fp)
            prev_r = r
        self.assertAlmostEqual(cs["ap"], round(ap, 4), places=4)
        self.assertEqual(cs["ink_px"], 400)
        self.assertAlmostEqual(cs["ink_share"], round(400 / 1300, 4))

    def test_constant_map_is_all_ties(self):
        cs = aucreport.curve_stats(*self._hist(np.full(10, 7), np.full(30, 7)))
        self.assertEqual(cs["auc"], 0.5)
        self.assertEqual(cs["ties"]["tied_pair_share"], 1.0)
        self.assertEqual(cs["ties"]["auc_ties_as_losses"], 0.0)
        self.assertEqual(cs["ties"]["auc_ties_as_wins"], 1.0)
        self.assertEqual(cs["levels_used"], 1)

    def test_perfect_map(self):
        cs = aucreport.curve_stats(*self._hist(np.array([200, 210]), np.array([1, 2, 3])))
        self.assertEqual((cs["auc"], cs["ap"]), (1.0, 1.0))
        self.assertEqual(cs["tpr_at_fpr"]["0.01"], 1.0)
        self.assertEqual(cs["best_f1"]["f1"], 1.0)
        self.assertEqual(cs["roc"][:2], [[0.0, 0.0], [0.0, 1.0]])
        self.assertEqual(cs["roc"][-1], [1.0, 1.0])

    def test_one_class_gives_none(self):
        self.assertIsNone(aucreport.curve_stats(*self._hist(np.array([], int), np.array([3]))))


@unittest.skipIf(np is None, "numpy is needed for kit.aucreport")
class ReportArraysTest(unittest.TestCase):
    def setUp(self):
        self.pred, self.rev, self.ink, self.sup = aucreport.demo_arrays(0)

    def test_map_number_is_kit_auc_number_and_control_is_behind(self):
        r = aucreport.report_arrays(self.pred, self.ink, self.sup, self.rev, null=40, bootstrap=40)
        self.assertEqual(r["map"]["auc"], auc.score_array(self.pred, self.ink, self.sup)["auc"])
        self.assertAlmostEqual(r["map"]["curves"]["auc"], r["map"]["auc"], places=3)
        self.assertGreater(r["control_gap"]["ci95"][0], 0)
        self.assertTrue(r["finite"]["map"]["ok"])

    def test_nan_is_refused(self):
        bad = self.pred.copy()
        bad[5, 5] = np.nan
        with self.assertRaises(finite.NonFinite):
            aucreport.report_arrays(bad, self.ink, self.sup, null=0, bootstrap=0, tiles=0)
        with self.assertRaises(finite.NonFinite):
            aucreport.report_arrays(self.pred, self.ink, self.sup, control=bad, null=0, bootstrap=0, tiles=0)

    def test_tiles_find_the_half_where_the_map_fails(self):
        pred = self.pred.copy()
        pred[:, 320:] = 1 - pred[:, 320:]          # inverted on the right half
        r = aucreport.report_arrays(pred, self.ink, self.sup, null=0, bootstrap=0, tiles=320, tile_min_px=100)
        t = r["tiles"]
        left = [x["auc"] for x in t["tiles"] if x["x1"] <= 320]
        right = [x["auc"] for x in t["tiles"] if x["x0"] >= 320]
        self.assertTrue(left and right)
        self.assertGreater(min(left), 0.75)
        self.assertLess(max(right), 0.25)
        self.assertEqual(t["at_or_below_half"], len(right))
        self.assertGreaterEqual(t["worst"]["x0"], 320)

    def test_null_can_fail_and_can_pass(self):
        good = aucreport.report_arrays(self.pred, self.ink, self.sup, null=60, bootstrap=0, tiles=0)["null"]
        self.assertEqual(good["p"], round(1 / 61, 4))
        noise = np.random.default_rng(9).random(self.pred.shape).astype(np.float32)
        bad = aucreport.report_arrays(noise, self.ink, self.sup, null=60, bootstrap=0, tiles=0)["null"]
        self.assertGreater(bad["p"], 0.05)
        self.assertLess(abs(bad["null_mean"] - 0.5), 0.05)

    def test_null_refuses_a_box_too_small_to_shift(self):
        sup = np.zeros_like(self.sup)
        sup[100:180, 100:180] = True
        with self.assertRaises(verify.VerifyError):
            aucreport.report_arrays(self.pred, self.ink, sup, null=30, bootstrap=0, tiles=0)

    def test_offset_scan_finds_a_planted_registration_error(self):
        # the map sees each stroke 3 px lower and 2 px left of its label: label[y, x] = ink[y - 3, x + 2] fits
        pred = aucreport._shift(np, self.pred, 3, -2)
        r = aucreport.report_arrays(pred, self.ink, self.sup, null=0, bootstrap=0, tiles=0, scan=4)
        s = r["offset_scan"]
        self.assertEqual((s["best"]["dy"], s["best"]["dx"]), (3, -2))
        self.assertGreater(s["gain"], 0)
        self.assertFalse(s["best_at_scan_edge"])

    def test_uint8_map_reports_its_ties(self):
        q = np.round(self.pred * 15).astype(np.uint8)   # 16 gray levels
        cs = aucreport.report_arrays(q, self.ink, self.sup, null=0, bootstrap=0, tiles=0)["map"]["curves"]
        self.assertLessEqual(cs["levels_used"], 16)
        self.assertGreater(cs["ties"]["tied_pair_share"], 0.01)
        self.assertLess(cs["ties"]["auc_ties_as_losses"], cs["auc"])


@unittest.skipIf(zarr is None, "numpy, tifffile and zarr are needed for kit.aucreport files")
class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        pred, rev, ink, sup = aucreport.demo_arrays(1, shape=(320, 400))
        for name, data in (("inklabels", ink), ("supervision", sup)):
            g = zarr.open_group(str(self.root / f"{name}.zarr"), mode="w")
            g.create_array("2", data=data.astype(np.uint8) * 255)
        self.map = self.root / "map.tif"
        self.rev = self.root / "rev.tif"
        tifffile.imwrite(self.map, np.round(pred * 65535).astype(np.uint16))
        tifffile.imwrite(self.rev, np.round(rev * 65535).astype(np.uint16))
        self.common = ["--labels", str(self.root / "inklabels.zarr"), "--mask", str(self.root / "supervision.zarr")]

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_number_as_kit_auc(self):
        r = aucreport.score_files(self.map, self.root / "inklabels.zarr", self.root / "supervision.zarr",
                                  control=self.rev, null=30, bootstrap=30)
        k = auc.score_files(self.map, self.root / "inklabels.zarr", self.root / "supervision.zarr", control=self.rev)
        self.assertEqual(r["map"]["auc"], k["forward"]["auc"])
        self.assertEqual(r["control"]["auc"], k["control"]["auc"])

    def test_exclude_and_offset(self):
        r = aucreport.score_files(self.map, self.root / "inklabels.zarr", self.root / "supervision.zarr",
                                  exclude=[[0, 160, 0, 400]], exclude_margin=10, offset=(0, 0), null=0,
                                  bootstrap=0, tiles=0)
        self.assertEqual(r["excluded"]["grown"], [[0, 170, 0, 400]])
        self.assertLess(r["excluded"]["ink_share_kept"], 0.7)
        self.assertEqual(r["label_offset"], [0, 0])
        moved = aucreport.score_files(self.map, self.root / "inklabels.zarr", self.root / "supervision.zarr",
                                      offset=(6, 0), null=0, bootstrap=0, tiles=0)
        self.assertLess(moved["map"]["auc"], r["map"]["auc"])
        with self.assertRaises(verify.VerifyError):
            aucreport.score_files(self.map, self.root / "inklabels.zarr", self.root / "supervision.zarr",
                                  exclude_margin=5)

    def test_cli_score_plot_csv_json_and_pool(self):
        svg, csv, js = self.root / "c.svg", self.root / "c.csv", self.root / "r.json"
        code, out, err = _run(["score", str(self.map), *self.common, "--control", str(self.rev), "--null", "30",
                               "--bootstrap", "30", "--plot", str(svg), "--curves", str(csv), "--out", str(js)])
        self.assertEqual(code, 0, err)
        self.assertIn("shifted-label null", out)
        self.assertEqual(ET.parse(svg).getroot().tag, "{http://www.w3.org/2000/svg}svg")
        self.assertTrue(csv.read_text().startswith("map,curve,x,y\nmap,roc,"))
        code, out, err = _run(["pool", str(js), str(js), str(js), "--json"])
        self.assertEqual(code, 0, err)
        p = json.loads(out)
        self.assertEqual(p["segments"], 3)
        self.assertIsNone(p["segment_bootstrap"])
        code, out, _ = _run(["pool"] + [str(js)] * 5 + ["--json"])
        self.assertEqual(json.loads(out)["segment_bootstrap"]["ci95"][0], json.loads(out)["mean_auc"])

    def test_cli_refuses_nan_with_exit_1(self):
        bad = self.root / "bad.npy"
        arr = np.zeros((320, 400), np.float32)
        arr[3, 3] = np.inf
        np.save(bad, arr)
        code, _, err = _run(["score", str(bad), *self.common])
        self.assertEqual(code, aucreport.EXIT_NONFINITE)
        self.assertIn("Inf", err)

    def test_pool_reads_kit_auc_json(self):
        k = auc.score_files(self.map, self.root / "inklabels.zarr", self.root / "supervision.zarr", control=self.rev)
        p = aucreport.pool([("a", k), ("b", k)])
        self.assertEqual(p["mean_auc"], k["forward"]["auc"])
        self.assertEqual(p["control"]["segments_map_ahead"], 2)


@unittest.skipIf(np is None, "numpy is needed for kit.aucreport")
class DemoTest(unittest.TestCase):
    def test_demo_json(self):
        code, out, err = _run(["demo", "--json", "--null", "30", "--bootstrap", "30"])
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertGreater(r["map"]["auc"], r["control"]["auc"])
        self.assertEqual(r["tool"], "aucreport")


if __name__ == "__main__":
    unittest.main()
