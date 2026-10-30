"""kit stagereg: the stage registry every workflow chooses from. The shipped catalogue passes its rules; a pick by
name, by environment and by default; refusals for unknown, pending and unrunnable options; AutoPipeline's --use."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kit import stagereg  # noqa: E402


class TestCatalogue(unittest.TestCase):
    def test_the_shipped_catalogue_has_no_problems(self):
        self.assertEqual(stagereg.check(), [])

    def test_ink_readers_say_their_dims_and_the_default_is_2_5d(self):
        ink = {r["name"]: r for r in stagereg.options("ink")}
        self.assertEqual(stagereg.default("ink", "autopipeline"), "reader-v3")
        self.assertEqual(ink["reader-v3"]["dims"], "2.5d")
        threes = [r for r in ink.values() if r.get("dims") == "3d"]
        self.assertTrue(threes)
        self.assertTrue(all(r["maturity"] in ("experimental", "pending", "failed") for r in threes))

    def test_every_stage_a_workflow_defaults_runs_there(self):
        _, d = stagereg.catalogue()
        for wf, st in d.items():
            for stage, name in st.items():
                r = stagereg.find(stage, name)
                self.assertIn(wf, r.get("use") or {}, (wf, stage, name))

    def test_rules_catch_a_bad_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"stage": "trace", "name": "mystery", "by": "x", "origin": "aliens", "maturity": "great"},
                    {"stage": "trace", "name": "nolicence", "by": "y", "origin": "ours", "maturity": "failed",
                     "use": {"cli": {}}},
                    {"stage": "trace", "name": "copied", "by": "z", "origin": "community",
                     "licence": "none stated", "maturity": "experimental", "why": "w", "reach": "url"},
                    {"stage": "trace", "name": "copied", "by": "z", "origin": "community", "licence": "MIT",
                     "maturity": "validated", "reach": "url"},
                    {"stage": "trace", "name": "scraped", "by": "q", "origin": "community", "licence": "none stated",
                     "maturity": "experimental", "why": "w", "reach": "url"},
                    {"stage": "trace", "name": "fine", "by": "f", "origin": "ours", "licence": "MIT",
                     "maturity": "validated", "reach": "url"}]
            Path(tmp, "stages.json").write_text(json.dumps({"schema": stagereg.SCHEMA, "options": rows,
                                                            "defaults": {"cli": {"trace": "absent"}}}))
            # a second file may annotate an option of the first (no `by`), never list it again
            later = [{"stage": "trace", "name": "scraped", "maturity": "failed", "why": "a planted note"},
                     {"stage": "trace", "name": "fine", "by": "x again", "origin": "ours", "licence": "MIT",
                     "maturity": "validated", "reach": "url"}]
            Path(tmp, "more.json").write_text(json.dumps({"schema": stagereg.SCHEMA, "options": later}))
            problems = stagereg.check(files=("stages.json", "more.json"), folder=tmp)
            cat, _ = stagereg.catalogue(refresh=True, files=("stages.json", "more.json"), folder=tmp)
            self.assertEqual(cat[("trace", "scraped")]["maturity"], "failed")
            stagereg.catalogue(refresh=True)
        text = "\n".join(problems)
        for want in ("maturity 'great'", "origin 'aliens'", "no workflow runs it", "no licence", "says why",
                     "fetched at run time only", "listed twice", "default cli trace: no option absent",
                     "more.json: trace fine is listed twice"):
            self.assertIn(want, text)
        self.assertNotIn("trace scraped is listed twice", text)


class TestPick(unittest.TestCase):
    def test_named_env_and_default(self):
        r = stagereg.pick("ink", "autopipeline", env={})
        self.assertEqual((r["name"], r["picked_by"]), ("reader-v3", "default"))
        self.assertNotIn("warning", r)
        r = stagereg.pick("ink", "autopipeline", env={"KIT_STAGE_INK": "team-3d-paris4"})
        self.assertEqual((r["name"], r["picked_by"]), ("team-3d-paris4", "KIT_STAGE_INK"))
        self.assertIn("experimental", r["warning"])
        two = stagereg.pick("ink", "autopipeline", "reader-v3,team-3d-paris4", env={})
        self.assertEqual([o["name"] for o in two], ["reader-v3", "team-3d-paris4"])
        rec = stagereg.record(two)
        self.assertEqual([o["dims"] for o in rec], ["2.5d", "3d"])

    def test_refusals(self):
        with self.assertRaisesRegex(stagereg.StageError, "no option nope"):
            stagereg.pick("ink", "autopipeline", "nope", env={})
        with self.assertRaisesRegex(stagereg.StageError, "no stage"):
            stagereg.pick("magic", "autopipeline", "x", env={})
        with self.assertRaisesRegex(stagereg.StageError, "cannot run it"):
            stagereg.pick("trace", "autopipeline", "villa-neural", env={})
        with self.assertRaisesRegex(stagereg.StageError, "has no default"):
            stagereg.pick("letters", "autopipeline", env={})

    def test_pending_is_refused_with_why(self):
        pending = [r for r in stagereg.options() if r.get("maturity") == "pending"]
        for r in pending:
            with self.assertRaisesRegex(stagereg.StageError, "pending"):
                stagereg.pick(r["stage"], "autopipeline", r["name"], env={})

    def test_use_arguments(self):
        self.assertEqual(stagereg.uses(["ink=reader-v3", "trace=villa"]), {"ink": "reader-v3", "trace": "villa"})
        for bad in (["ink"], ["=x"], ["magic=x"], ["ink=a", "ink=b"]):
            with self.assertRaises(stagereg.StageError):
                stagereg.uses(bad)

    def test_ap_settings(self):
        picked = stagereg.picks(["ink=reader-v3,team-3d-paris4", "flatten=off", "surface=catalog"], "autopipeline",
                                env={})
        self.assertEqual(stagereg.ap_settings(picked), {"backends": {"ink": ["reader-v3", "team-3d-paris4"],
                                                                     "flatten": "off"}})
        with self.assertRaisesRegex(stagereg.StageError, "AutoPipeline cannot run"):
            stagereg.ap_settings({"trace": stagereg.find("trace", "villa-neural")})


class TestAutoPipelineUse(unittest.TestCase):
    def test_plan_takes_use_and_the_environment(self):
        from kit import autopipe
        s = autopipe.with_stage_picks({"purpose": "smoke"}, ["ink=team-3d-paris4"], env={})
        self.assertEqual(s, {"purpose": "smoke", "backends": {"ink": ["team-3d-paris4"]}})
        self.assertEqual(autopipe.with_stage_picks(None, [], env={}), None)
        self.assertEqual(stagereg.picks([], "autopipeline", env={"KIT_STAGE_FLATTEN": "off"})["flatten"]["picked_by"],
                         "KIT_STAGE_FLATTEN")
        s = autopipe.with_stage_picks({}, [], env={"KIT_STAGE_FLATTEN": "off"})
        self.assertEqual(s, {"backends": {"flatten": "off"}})
        with self.assertRaisesRegex(autopipe.AutoError, "one way"):
            autopipe.with_stage_picks({"backends": {"flatten": "villa"}}, ["flatten=off"], env={})
        # the shorthand becomes the plan's ordinary settings, as any backends choice does
        from kit import apbackends
        self.assertEqual(apbackends.apply(s)["flatten"], {"enabled": False})

    def test_the_command_line(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(stagereg.main(["pick", "ink", "--workflow", "autopipeline", "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["name"], "reader-v3")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(stagereg.main(["pick", "ink", "--workflow", "autopipeline", "--use", "nope"]), 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(stagereg.main(["list", "ink"]), 0)
        self.assertIn("team-3d-paris4", out.getvalue())


if __name__ == "__main__":
    unittest.main()
