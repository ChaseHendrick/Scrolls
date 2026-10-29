"""kit stagereg: the stage registry every workflow chooses from. The shipped catalogue passes its rules; a pick by
name, by environment and by default; refusals for unknown and unrunnable options; scroll2ink's --use."""

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

    def test_ink_readers_say_their_dims(self):
        ink = {r["name"]: r for r in stagereg.options("ink")}
        self.assertEqual(stagereg.default("ink", "scroll2ink"), "reader-v2")
        self.assertTrue(ink)
        self.assertTrue(all(r.get("dims") in ("2.5d", "3d") for r in ink.values()))

    def test_winding_stages_list_ours_beside_the_community_tools(self):
        stages = list(stagereg.STAGES)
        self.assertLess(stages.index("windings"), stages.index("spiral"))
        self.assertLess(stages.index("spiral"), stages.index("spiralcheck"))
        found = {(r["stage"], r["name"]): r for r in stagereg.options()}
        self.assertEqual(found[("windings", "windlabel-box")]["maturity"], "validated")
        for name in ("winding-phase", "constraint-gauge-e1"):
            self.assertEqual(found[("windings", name)]["origin"], "community")
        self.assertEqual(found[("spiralcheck", "seamswitch")]["origin"], "ours")
        self.assertEqual(found[("spiralcheck", "spiral-eval")]["origin"], "community")

    def test_every_stage_a_workflow_defaults_runs_there(self):
        _, d = stagereg.catalogue()
        for wf, st in d.items():
            for stage, name in st.items():
                if wf != "scroll2ink":
                    continue      # this copy runs scroll2ink; the other workflows' defaults live where they run
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
        r = stagereg.pick("ink", "scroll2ink", env={})
        self.assertEqual((r["name"], r["picked_by"]), ("reader-v2", "default"))
        self.assertNotIn("warning", r)
        r = stagereg.pick("ink", "scroll2ink", env={"KIT_STAGE_INK": "d9v2"})
        self.assertEqual((r["name"], r["picked_by"]), ("d9v2", "KIT_STAGE_INK"))
        rec = stagereg.record(stagereg.pick("ink", "scroll2ink", "reader-v2,v8in", env={}))
        self.assertEqual([o["name"] for o in rec], ["reader-v2", "v8in"])

    def test_refusals(self):
        with self.assertRaisesRegex(stagereg.StageError, "no option nope"):
            stagereg.pick("ink", "scroll2ink", "nope", env={})
        with self.assertRaisesRegex(stagereg.StageError, "no stage"):
            stagereg.pick("magic", "scroll2ink", "x", env={})
        with self.assertRaisesRegex(stagereg.StageError, "cannot run it"):
            stagereg.pick("trace", "scroll2ink", "villa-neural", env={})
        with self.assertRaisesRegex(stagereg.StageError, "has no default"):
            stagereg.pick("letters", "scroll2ink", env={})

    def test_use_arguments(self):
        self.assertEqual(stagereg.uses(["ink=reader-v2", "trace=villa"]), {"ink": "reader-v2", "trace": "villa"})
        for bad in (["ink"], ["=x"], ["magic=x"], ["ink=a", "ink=b"]):
            with self.assertRaises(stagereg.StageError):
                stagereg.uses(bad)

    def test_the_command_line(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(stagereg.main(["pick", "ink", "--workflow", "scroll2ink", "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["name"], "reader-v2")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(stagereg.main(["pick", "ink", "--workflow", "scroll2ink", "--use", "nope"]), 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(stagereg.main(["list", "ink"]), 0)
        self.assertIn("v8in", out.getvalue())


class TestScroll2InkUse(unittest.TestCase):
    def args(self, *extra):
        import argparse
        from kit import scroll2ink
        p = argparse.ArgumentParser()
        scroll2ink.add_arguments(p)
        return p.parse_args(["run", "--sample", "PHerc0139", "--seed", "1", "2", "3", *extra])

    def test_use_sets_the_ink_model_and_is_recorded(self):
        from kit import scroll2ink
        a = self.args("--use", "ink=d9v2")
        picks = scroll2ink.apply_stage_picks(a, env={})
        self.assertEqual(a.model, "d9v2")
        self.assertEqual(picks["ink"]["name"], "d9v2")
        a = self.args()
        self.assertEqual(scroll2ink.apply_stage_picks(a, env={"KIT_STAGE_INK": "v8in"})["ink"]["picked_by"],
                         "KIT_STAGE_INK")
        self.assertEqual(a.model, "v8in")
        a = self.args()
        self.assertEqual(scroll2ink.apply_stage_picks(a, env={}), {})       # nothing picked: settings as before
        self.assertEqual(a.model, scroll2ink.DEFAULTS["model"])

    def test_a_contradiction_and_an_unrunnable_pick_are_refused(self):
        from kit import scroll2ink
        with self.assertRaisesRegex(scroll2ink.Scroll2InkError, "one way"):
            scroll2ink.apply_stage_picks(self.args("--model", "v8in", "--use", "ink=d9v2"), env={})
        with self.assertRaises(stagereg.StageError):
            scroll2ink.apply_stage_picks(self.args("--use", "trace=villa-neural"), env={})

    def test_dry_run_records_the_pick(self):
        import contextlib
        import io
        from kit import scroll2ink
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(scroll2ink.run_cli(self.args("--use", "ink=d9v2", "--dry-run")), 0)
        s = json.loads(out.getvalue())["settings"]
        self.assertEqual((s["model"], s["stages"]["ink"]["name"]), ("d9v2", "d9v2"))


if __name__ == "__main__":
    unittest.main()
