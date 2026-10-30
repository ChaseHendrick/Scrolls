"""AutoPipeline's ink stage with a 3D ink model (kit/ink3d.py) beside a 2.5D one, on the fake scroll of
tests/test_autopipe.py: the plan names it, the stage reads the scan around each accepted trace onto the render's own
canvas with the moved-sheet control as its r map, and the 2.5D default is unchanged."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_autopipe as TA  # noqa: E402
import vc3d_fakes as fakes  # noqa: E402

from kit import apbackends, autopipe, ink3d  # noqa: E402


class TestPlanNames3D(unittest.TestCase):
    def test_default_is_still_the_2_5d_reader(self):
        self.assertEqual(autopipe.DEFAULTS["ink"]["models"], ["reader-v3"])
        c = apbackends.ink_choices()
        self.assertEqual((c["reader-v3"]["dims"], c["reader-v3"]["maturity"]), ("2.5d", "default"))
        three = [n for n, v in c.items() if v["dims"] == "3d"]
        self.assertIn("team-3d-paris4", three)
        self.assertTrue(all(c[n]["maturity"] in ("experimental", "pending", "failed") for n in three))

    def test_backends_shorthand_names_a_3d_reader(self):
        self.assertEqual(apbackends.translate({"ink": ["reader-v3", "team-3d-paris4"]}),
                         {"ink": {"models": ["reader-v3", "team-3d-paris4"]}})
        self.assertEqual(autopipe.ink_3d_resolved(["reader-v3", "team-3d-paris4"])["team-3d-paris4"]["status"],
                         "experimental")
        self.assertEqual(autopipe.ink_3d_resolved(["reader-v3"]), {})

    def test_check_models_knows_the_3d_readers(self):
        s = autopipe._merge(autopipe.DEFAULTS, {"ink": {"models": ["team-3d-paris4"]}})
        autopipe.check_models(s, {})
        s = autopipe._merge(autopipe.DEFAULTS, {"ink": {"models": ["no-such-3d"]}})
        with self.assertRaisesRegex(autopipe.AutoError, "no-such-3d"):
            autopipe.check_models(s, {})

    def test_pitch_setting_is_optional_and_checked(self):
        self.assertNotIn("pitch_um", autopipe._merge(autopipe.DEFAULTS, {})["ink"])
        s = autopipe._merge(autopipe.DEFAULTS, {"ink": {"pitch_um": 1.0}})
        self.assertEqual(s["ink"]["pitch_um"], 1.0)


@unittest.skipUnless(TA.HAVE_LABELXFER, "kit ink3d needs numpy, tifffile and zarr")
class TestInkStage3D(TA.Base):
    def setUp(self):
        TA.Base.setUp(self)
        self.pred, self.ct, self.axis = TA.scroll(self.d)
        self.ctx = self.context(FAKE_TRACE_ARC=f"{TA.AXIS[0]},{TA.AXIS[1]}")

    grids = TA.TestRun.grids
    plan = TA.TestRun.plan
    run_plan = TA.TestRun.run_plan

    def test_a_3d_reader_beside_a_2_5d_one(self):
        import numpy as np
        import tifffile
        model = self.d / "model.py"
        model.write_text(fakes.INK_MODEL)
        self.home.mkdir(parents=True, exist_ok=True)
        flat = {"engine": "command", "command": [sys.executable, str(model), "{layers}", "{output}", "{reverse}"]}
        # the fake scroll's surface prediction stands for a published 3D ink volume: ink on the traced sheet only
        shell = {"dims": "3d", "engine": "published", "status": "experimental", "origin": "ours", "licence": "test",
                 "volumes": {str(self.ct): str(self.pred)}, "map_factor": 1, "value_range": [0, 200]}
        (self.home / "models.json").write_text(json.dumps({"fake": flat, "shell-3d": shell}))
        self.ctx = self.context(FAKE_TRACE_ARC=f"{TA.AXIS[0]},{TA.AXIS[1]}", KIT_AUTOPIPE_RUNNER="modal")
        ink = autopipe._merge(autopipe.DEFAULTS["ink"], {"where": "modal", "models": ["fake", "shell-3d"],
                                                         "variants": ["f", "r"], "pitch_um": 30.0}, "ink.")
        st, out = self.run_plan(self.plan(ink=ink), self.d / "run3d", until="ink")
        self.assertEqual(st["stages"]["ink"]["status"], "done", st["stages"]["ink"])
        for sid in ("t00", "t01"):
            s = st["surfaces"][sid]
            flat_rec, three = s["ink"]["fake"], s["ink"]["shell-3d"]
            self.assertEqual(flat_rec["exit"], 0, flat_rec)
            self.assertNotIn("dims", flat_rec)                 # the 2.5D reader's record is as before
            self.assertEqual((three["exit"], three["dims"], three["control"]), (0, "3d", "moved-sheet"), three)
            self.assertEqual(three["pitch"], {"pitch_um": 30.0, "source": "given"})
            self.assertEqual(three["model"]["status"], "experimental")
            f = tifffile.imread(three["maps"]["f"]["path"]).astype(float)
            r = tifffile.imread(three["maps"]["r"]["path"]).astype(float)
            flat_f = tifffile.imread(flat_rec["maps"]["f"]["path"])
            self.assertEqual(f.shape, flat_f.shape[-2:])        # the same canvas as the 2.5D map
            ok = f > 0
            self.assertGreater(ok.mean(), 0.3)
            self.assertGreater(np.median(f[ok]), 30000)        # the traced sheet carries the stand-in's ink
            self.assertLess(np.median(r[ok]), 5000)             # two pitches out and in it does not
            self.assertEqual(three["maps"]["f"]["path"], str(out / "ink" / sid / "shell-3d" / "ink_f.tif"))
            self.assertEqual(sorted(three["maps"]), ["f", "r"])
        # the maps are found by the scorer as any reader's
        paths = autopipe.Run.map_paths(st["surfaces"]["t00"], "shell-3d", out)
        self.assertTrue(paths["f"] and paths["r"])

    def test_a_3d_reader_without_its_volume_records_why(self):
        self.home.mkdir(parents=True, exist_ok=True)
        shell = {"dims": "3d", "engine": "published", "status": "experimental", "volumes": {}}
        (self.home / "models.json").write_text(json.dumps({"shell-3d": shell}))
        self.ctx = self.context(FAKE_TRACE_ARC=f"{TA.AXIS[0]},{TA.AXIS[1]}", KIT_AUTOPIPE_RUNNER="modal")
        ink = autopipe._merge(autopipe.DEFAULTS["ink"], {"where": "modal", "models": ["shell-3d"],
                                                         "variants": ["f", "r"], "pitch_um": 30.0}, "ink.")
        st, _ = self.run_plan(self.plan(ink=ink), self.d / "nothing", until="ink")
        rec = st["surfaces"]["t00"]["ink"]["shell-3d"]
        self.assertIn("no published 3D prediction", rec["exit"])
        self.assertEqual(rec["dims"], "3d")

    def test_where_auto_needs_the_weights_of_a_learned_3d_reader(self):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "models.json").write_text(json.dumps({"b-3d": {
            "dims": "3d", "engine": "villa-full3d", "status": "pending", "checkpoint": str(self.d / "absent.pth")}}))
        ink = autopipe._merge(autopipe.DEFAULTS["ink"], {"where": "auto", "models": ["b-3d"],
                                                         "variants": ["f", "r"]}, "ink.")
        (self.d / "w").mkdir()
        run = autopipe.Run(TA.vc3d_agent, self.ctx, self.d / "w", self.plan(ink=ink))
        self.assertEqual(run.ink_where(), "modal")       # no weights here: handed off, never run without them


if __name__ == "__main__":
    unittest.main()
