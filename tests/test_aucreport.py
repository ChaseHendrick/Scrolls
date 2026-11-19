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

    def test_map_cannot_be_its_own_control(self):
        with self.assertRaises(verify.VerifyError):
            aucreport.score_files(self.map, self.root / "inklabels.zarr", self.root / "supervision.zarr",
                                  control=self.map, null=0, bootstrap=0, tiles=0)

    def test_vacated_edge_leaves_the_supervision(self):
        full = np.ones((320, 400), np.uint8) * 255   # supervision to the very edge, so a clamped edge would stay in
        g = zarr.open_group(str(self.root / "full.zarr"), mode="w")
        g.create_array("2", data=full)
        args = (self.root / "inklabels.zarr", self.root / "full.zarr", "2", (320, 400), None, (320, 400))
        ink0, sup0 = aucreport.labels_on_map(*args)
        ink, sup = aucreport.labels_on_map(*args, offset=(30, -25))
        self.assertTrue(sup0.all())
        self.assertFalse(sup[:30].any())
        self.assertFalse(sup[:, -25:].any())
        self.assertTrue(sup[30:, :-25].all())
        self.assertTrue((ink[30:, :-25] == ink0[:-30, 25:]).all())

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
class ControlsTest(unittest.TestCase):
    """Every check must be able to fail: the control gap, its interval, and the uncontrolled label."""

    def setUp(self):
        self.pred, self.rev, self.ink, self.sup = aucreport.demo_arrays(0)
        self.kw = dict(null=0, tiles=0)

    def test_gap_is_map_minus_control_on_shared_pixels(self):
        rev = self.rev.copy()
        rev[:, :200] = 0                          # the control predicts on fewer pixels than the map
        g = aucreport.report_arrays(self.pred, self.ink, self.sup, rev, bootstrap=0, **self.kw)["control_gap"]
        shared = self.sup & (self.pred != 0) & (rev != 0)
        a = auc.score_array(self.pred, self.ink, shared)["auc"]
        b = auc.score_array(rev, self.ink, shared)["auc"]
        self.assertEqual(g["shared_px"], int(shared.sum()))
        self.assertAlmostEqual(g["auc_map_shared"], a, places=4)
        self.assertAlmostEqual(g["auc_control_shared"], b, places=4)
        self.assertAlmostEqual(g["difference"], a - b, places=3)
        self.assertGreater(g["difference"], 0.2)
        swapped = aucreport.report_arrays(rev, self.ink, self.sup, self.pred, bootstrap=0, **self.kw)["control_gap"]
        self.assertLess(swapped["difference"], -0.2)

    def test_gap_interval_is_the_paired_bootstrap_against_the_control(self):
        r = aucreport.report_arrays(self.pred, self.ink, self.sup, self.rev, bootstrap=40, seed=3, **self.kw)
        ref = auc.block_bootstrap(self.pred, self.ink, self.sup, 40, auc.BLOCK_PX, 3, self.rev)["compare"]
        self.assertEqual(r["control_gap"]["ci95"], ref["ci95"])
        self.assertLess(r["control_gap"]["ci95"][0], r["control_gap"]["difference"])
        self.assertGreater(r["control_gap"]["ci95"][1], r["control_gap"]["difference"])

    def test_uncontrolled_numbers_are_labeled(self):
        r = aucreport.report_arrays(self.pred, self.ink, self.sup, bootstrap=0, **self.kw)
        self.assertFalse(r["controlled"])
        lines = aucreport.format_report(r).splitlines()
        self.assertTrue(lines[0].startswith("UNCONTROLLED"))
        self.assertTrue(all(x.endswith("[uncontrolled]") for x in lines[1:]))
        ok = aucreport.report_arrays(self.pred, self.ink, self.sup, self.rev, bootstrap=0, **self.kw)
        self.assertTrue(ok["controlled"])
        self.assertNotIn("uncontrolled", aucreport.format_report(ok))

    def test_all_zero_control_is_uncontrolled_not_a_crash(self):
        zero = np.zeros_like(self.rev)
        for b in (0, 30):
            r = aucreport.report_arrays(self.pred, self.ink, self.sup, zero, bootstrap=b, **self.kw)
            self.assertIsNone(r["control_gap"]["difference"])
            self.assertFalse(r["controlled"])
            self.assertTrue(aucreport.format_report(r).startswith("UNCONTROLLED"))

    def test_compare_always_gets_its_interval(self):
        r = aucreport.report_arrays(self.pred, self.ink, self.sup, self.rev, compare=self.rev, bootstrap=0,
                                    **self.kw)
        self.assertIn("compare", r["bootstrap"])
        self.assertEqual(r["bootstrap"]["draws"], 300)

    def test_pool_labels_uncontrolled_segments(self):
        a = aucreport.report_arrays(self.pred, self.ink, self.sup, self.rev, bootstrap=0, **self.kw)
        b = aucreport.report_arrays(self.pred, self.ink, self.sup, bootstrap=0, **self.kw)
        p = aucreport.pool([("a", a), ("b", b)])
        self.assertEqual(p["uncontrolled_segments"], 1)
        self.assertEqual(p["control"]["segments"], 1)
        self.assertEqual(p["control"]["mean_gap"], a["control_gap"]["difference"])
        text = aucreport.format_pool(p)
        self.assertTrue(text.startswith("UNCONTROLLED"))
        self.assertIn("b: AUC", text)
        self.assertNotIn("uncontrolled", aucreport.format_pool(aucreport.pool([("a", a)])))
        self.assertFalse(p["controlled"])
        n = len(p["rows"])
        lines = text.splitlines()
        self.assertTrue(all(x.endswith("[uncontrolled]") for x in lines[1 + n:]))
        self.assertGreaterEqual(len(lines[1 + n:]), 2)
        self.assertTrue(aucreport.pool([("a", a)])["controlled"])

    def test_gap_keeps_zero_pixels_with_keep_zero(self):
        rev = self.rev.copy()
        rev[:, :200] = 0
        g = aucreport.report_arrays(self.pred, self.ink, self.sup, rev, keep_zero=True, bootstrap=0,
                                    **self.kw)["control_gap"]
        self.assertEqual(g["shared_px"], int(self.sup.sum()))

    def test_verdict_follows_the_interval(self):
        r = aucreport.report_arrays(self.pred, self.ink, self.sup, self.rev, bootstrap=30, **self.kw)
        for ci, word in (([0.01, 0.05], "ahead of its control beyond sampling noise"),
                         ([-0.02, 0.03], "not distinguishable from its control"),
                         ([-0.05, -0.01], "behind its control beyond sampling noise")):
            r["control_gap"]["ci95"] = ci
            self.assertIn(word, aucreport.format_report(r))
        r = aucreport.report_arrays(self.pred, self.ink, self.sup, self.rev, compare=self.rev, bootstrap=30,
                                    **self.kw)
        for ci, word in (([0.01, 0.05], "ahead beyond"), ([-0.02, 0.03], "not distinguishable from noise"),
                         ([-0.05, -0.01], "behind beyond")):
            r["bootstrap"]["compare"]["ci95"] = ci
            self.assertIn(word, aucreport.format_report(r))

    def test_constant_control_cannot_fail_so_is_uncontrolled(self):
        flat = np.full_like(self.rev, 0.5)
        r = aucreport.report_arrays(self.pred, self.ink, self.sup, flat, bootstrap=0, **self.kw)
        self.assertTrue(r["control_gap"]["control_constant"])
        self.assertFalse(r["controlled"])
        self.assertIn("constant", r["warning"])
        self.assertTrue(aucreport.format_report(r).startswith("UNCONTROLLED"))
        ok = aucreport.report_arrays(self.pred, self.ink, self.sup, self.rev, bootstrap=0, **self.kw)
        self.assertFalse(ok["control_gap"]["control_constant"])

    def test_compared_map_is_labeled_without_its_own_control(self):
        r = aucreport.report_arrays(self.pred, self.ink, self.sup, self.rev, compare=self.rev, bootstrap=30,
                                    **self.kw)
        self.assertTrue(r["controlled"])
        self.assertFalse(r["compare"]["controlled"])
        self.assertIn("no reverse-depth control of its own", r["compare"]["warning"])
        lines = aucreport.format_report(r).splitlines()
        cmp_lines = [x for x in lines if x.startswith("compared map")]
        self.assertEqual(len(cmp_lines), 1)
        self.assertTrue(cmp_lines[0].endswith("[no control of its own]"))
        self.assertFalse(any("[no control of its own]" in x for x in lines if not x.startswith("compared map")))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.svg"
            aucreport.write_svg(r, path)
            texts = [t.text or "" for t in ET.parse(path).getroot().iter("{http://www.w3.org/2000/svg}text")]
        cmp_legend = [t for t in texts if t.startswith("compare ")]
        self.assertEqual(len(cmp_legend), 2)
        self.assertTrue(all(t.endswith("[no control of its own]") for t in cmp_legend))
        self.assertFalse(any(t.endswith("[no control of its own]") for t in texts if t.startswith("map ")))

    def test_plot_labels_uncontrolled_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            zero = np.zeros_like(self.rev)
            for control, labeled in ((None, True), (zero, True), (self.rev, False)):
                r = aucreport.report_arrays(self.pred, self.ink, self.sup, control, bootstrap=0, **self.kw)
                path = Path(d) / "p.svg"
                aucreport.write_svg(r, path)
                svg = path.read_text()
                ET.fromstring(svg)
                texts = [t.text or "" for t in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}text")]
                legend = [t for t in texts if t.startswith(("map AUC", "map AP"))]
                self.assertEqual(len(legend), 2)
                self.assertEqual("UNCONTROLLED" in svg, labeled)
                self.assertEqual(all(t.endswith("[uncontrolled]") for t in legend), labeled)


@unittest.skipIf(np is None, "numpy is needed for kit.aucreport")
class MasksTest(unittest.TestCase):
    def setUp(self):
        self.pred, self.rev, self.ink, self.sup = aucreport.demo_arrays(0)

    def test_keep_zero_reaches_the_curves(self):
        pred = self.pred.copy()
        pred[100:200, 100:300] = 0
        off = aucreport.report_arrays(pred, self.ink, self.sup, null=0, bootstrap=0, tiles=0)["map"]["curves"]
        on = aucreport.report_arrays(pred, self.ink, self.sup, keep_zero=True, null=0, bootstrap=0,
                                     tiles=0)["map"]["curves"]
        self.assertEqual(on["ink_px"] + on["background_px"], int(self.sup.sum()))
        self.assertEqual(off["ink_px"] + off["background_px"], int((self.sup & (pred != 0)).sum()))

    def test_null_and_tiles_honor_inner(self):
        pred = self.pred.copy()
        e = 60
        pred[:e] = 1 - pred[:e]                   # a wrong edge that --inner leaves out
        r = aucreport.report_arrays(pred, self.ink, self.sup, inner=e, null=30, bootstrap=0, tiles=0)
        self.assertEqual(r["null"]["observed_auc"], r["map"]["auc"])
        self.assertGreaterEqual(r["null"]["box"][0], e)
        full = aucreport.report_arrays(pred, self.ink, self.sup, null=30, bootstrap=0, tiles=0)
        self.assertNotEqual(full["null"]["observed_auc"], r["null"]["observed_auc"])
        q, _ = auc._quantize(np, pred)
        direct = aucreport.shift_null(q, self.ink, auc._edge_mask(np, self.sup, e),
                                      auc._edge_mask(np, pred != 0, e), 30, auc.BLOCK_PX, 0)
        self.assertEqual(r["null"], direct)

    def test_exclusion_box_on_a_crop(self):
        crop = (100, 300, 200, 500)               # y0 y1 x0 x1 of a 640 x 640 surface
        sup = np.ones((200, 300), bool)
        ink = np.zeros_like(sup)
        out, rec = aucreport.exclude_boxes(ink, sup, [[50, 150, 450, 600]], (640, 640), crop, margin=10)
        self.assertEqual(rec["grown"], [[40, 160, 440, 610]])
        expect = np.ones_like(sup)
        expect[0:60, 240:300] = False              # rows 100..160 and columns 440..500 of the surface
        self.assertTrue((out == expect).all())
        self.assertEqual(rec["supervised_px_removed"], 60 * 60)


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
