"""kit defectbench: planted mesh defects with known answers (synthetic only)."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import scipy  # noqa: F401
    import tifffile  # noqa: F401
    from kit import defectbench as db
    HAVE = True
except ImportError:  # pragma: no cover
    HAVE = False


@unittest.skipUnless(HAVE, "needs numpy, scipy and tifffile")
class DefectBenchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.root = cls.tmp / "bench"
        db.make(cls.root, tracks=("column",), seeds=1)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def case(self, name, track="column", seed=0):
        return db.load_case(self.root / track / f"{name}-s{seed}")

    def test_check_agrees_and_detects_edits(self):
        self.assertEqual(db.check(self.root), [])
        d = self.tmp / "edited"
        shutil.copytree(self.root, d)
        x = db._read_grid(d / "column" / "clean-s0" / "x.tif")
        v = np.argwhere(x != -1)[100]
        x[tuple(v)] += 23.0                    # one vertex moved a whole pitch out
        db._write_grid(d / "column" / "clean-s0" / "x.tif", x)
        bad = db.check(d)
        self.assertTrue(any("x.tif changed" in b for b in bad), bad)
        self.assertIn("column/clean-s0: 1 labels differ from the coordinates", bad)

    def test_expected_classes(self):
        for name, _lv, _ops, _m, expected in db.CASES:
            _xyz, _v, t, rec = self.case(name)
            tr = rec["truth"]
            bad = tr["wrong"] + tr["gap"] + tr["fold"]
            if expected == "INCORRECT":
                self.assertGreater(bad, 0, name)
            else:
                self.assertEqual(bad, 0, name)
            if expected == "CORRECT":
                self.assertEqual(tr["rough"], 0, name)

    def test_roughness_matches_dev_columns(self):
        # within 25 % of the calibration columns' crease and spike area shares
        for name, level in (("rough-a", "cA"), ("band-b", "cB"), ("rough-light", "light")):
            _x, _v, _t, rec = self.case(name)
            for key in ("crease", "spike"):
                got = rec["mesh"][f"{key}_area_share"]
                want = db.ROUGH[level]["target"][key]
                self.assertLess(abs(got - want) / want, 0.25, (name, key, got, want))

    def test_taubin_matched_variant(self):
        # rough-a-taubin is matched on what taubin5g did to the calibration columns: p95 move 2.0 to 3.5 voxels, about 0.32 % cut
        _x, _v, _t, rec = self.case("rough-a-taubin")
        tb = rec["mesh"]["taubin5g"]
        self.assertTrue(2.0 <= tb["move_p95"] <= 3.5, tb)
        self.assertLess(tb["cut_share"], 0.01, tb)
        _x, _v, _t, rec = self.case("rough-a")
        self.assertGreater(rec["mesh"]["taubin5g"]["cut_share"], 0.02)   # the crease-matched variant is harsher

    def test_band_b_shape(self):
        _x, _v, t, rec = self.case("band-b")
        tr = rec["truth"]
        # one large band (about 1,400 quads, as on column B) and smaller ones
        self.assertGreater(tr["switch_region_sizes"][0], 900)
        self.assertGreaterEqual(tr["switch_regions"], 3)
        self.assertEqual(rec["shape"], [91, 405])

    def test_alarm_controls_fail_and_oracle_passes(self):
        res = {}
        for kind in ("none", "all", "oracle", "wjump"):
            out = self.tmp / f"alarm-{kind}"
            db.baseline(self.root, out, alarm=kind)
            res[kind] = db.score(self.root, alarms=out)["families"]
        band = "column/band-b"
        self.assertEqual(res["none"][band]["recall"], 0.0)
        self.assertEqual(res["all"][band]["false_alarm_clean"], 1.0)
        self.assertEqual(res["oracle"][band]["recall"], 1.0)
        self.assertEqual(res["oracle"][band]["false_alarm_clean"], 0.0)
        # the geometry-only alarm finds the hard switches but not a soft merger's whole far side
        self.assertGreater(res["wjump"]["column/switch-edge"]["recall"], 0.9)
        self.assertEqual(res["wjump"]["column/clean"].get("false_alarm_clean"), 0.0)

    def test_repair_controls(self):
        res = {}
        for kind in ("identity", "oracle", "taubin5g"):
            out = self.tmp / f"rep-{kind}"
            db.baseline(self.root, out, repair=kind)
            res[kind] = db.score(self.root, repaired=out)["families"]
        self.assertGreater(res["identity"]["column/band-b"]["wrong_kept"], 500)
        self.assertEqual(res["oracle"]["column/band-b"]["wrong_kept"], 0)
        self.assertEqual(res["oracle"]["column/rough-a"]["kept_share"], 1.0)
        self.assertEqual(res["identity"]["column/clean"]["kept_share"], 1.0)
        # the fold adds backward row edges over its roughness twin; the oracle removes exactly the fold's share
        self.assertGreater(res["identity"]["column/fold"]["backward_edges"],
                           res["identity"]["column/rough-light"]["backward_edges"] + 100)
        self.assertGreater(res["identity"]["column/fold"]["fold_kept"], 100)
        self.assertEqual(res["oracle"]["column/fold"]["fold_kept"], 0)
        # the oracle removes the fold's backward edges; what is left is background roughness, a random draw that
        # can sit a little above or below the roughness twin's, so it is compared with the fold it repaired
        self.assertLess(res["oracle"]["column/fold"]["backward_edges"],
                        res["identity"]["column/fold"]["backward_edges"] - 100)

    def test_aggregate_means(self):
        rows = [{"track": "column", "case": "x", "recall": 1.0, "regions": 1, "regions_hit": 1},
                {"track": "column", "case": "x", "recall": 0.0, "regions": 2, "regions_hit": 0},
                {"track": "column", "case": "x", "recall": 0.0, "regions": 0, "regions_hit": 0},
                {"track": "column", "case": "y", "missing": "somewhere"}]
        agg = db.aggregate(rows)
        self.assertEqual(agg, {"column/x": {"n": 3, "recall": 0.3333, "regions_hit": "1/3"}})

    def test_grid_mismatch_refused(self):
        out = self.tmp / "badgrid" / "column"
        out.mkdir(parents=True)
        for name in db.CASE_NAMES:
            np.save(out / f"{name}-s0.npy", np.zeros((3, 3), bool))
        with self.assertRaises(db.BenchError):
            db.score(self.root, alarms=out.parent)

    def test_deterministic(self):
        a, _ = db.build("column", "band-b", 0)
        b, _ = db.build("column", "band-b", 0)
        self.assertTrue(np.array_equal(a["xyz"], b["xyz"]))
        c, _ = db.build("column", "band-b", 1)
        self.assertFalse(np.array_equal(a["xyz"][a["valid"] & c["valid"]], c["xyz"][a["valid"] & c["valid"]]))

    def test_mini_prediction_on_sheets(self):
        tmp = self.tmp / "mini"
        db.make(tmp, tracks=("mini",), seeds=1, only=["band-only"])
        d = tmp / "mini" / "band-only-s0"
        import zarr
        arr = zarr.open_group(str(d / "pred.zarr"), mode="r")["0"]
        xyz, valid, t, rec = db.load_case(d)
        clean = valid & (t["label"] == 0)
        pts = np.rint(xyz[clean]).astype(int)
        vals = np.array([arr[z, y, x] for x, y, z in pts[::25]])
        self.assertGreater((vals == 255).mean(), 0.95)       # clean vertices sit on a predicted sheet
        gap = valid & (t["label"] == 3)
        if gap.any():
            pts = np.rint(xyz[gap]).astype(int)
            vals = np.array([arr[z, y, x] for x, y, z in pts])
            self.assertLess((vals == 255).mean(), 0.5)        # gap vertices mostly sit in the void
        self.assertTrue(json.loads((d / "umbilicus.json").read_text())["points_xyz"])


if __name__ == "__main__":
    unittest.main()
