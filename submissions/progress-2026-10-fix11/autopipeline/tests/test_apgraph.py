"""Causal links for AutoPipeline runs (kit/apgraph.py): the provenance graph every run writes, why, swap and diff.
Whole runs on the fakes of test_autopipe: no villa build, no torch."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -m unittest tests.test_apgraph
import test_autopipe as TA  # noqa: E402
from test_autopipe_extensions import Doubler  # noqa: E402

from kit import apbackends, apgraph, autopipe, vc3d_agent

ROOT = Path(__file__).resolve().parent.parent


class TestGraph(TA.TestRun):
    def register_trace_fixture(self):
        # Isolate extension registration from every other test and from the repository's optional extensions.
        for name in ("TRACE_METHODS", "OPTIONAL"):
            patcher = mock.patch.object(autopipe, name, dict(getattr(autopipe, name)))
            patcher.start()
            self.addCleanup(patcher.stop)
        autopipe.register_trace_method(Doubler)

    def full_run(self):
        st, out = self.run_plan(self.plan())
        self.assertEqual(st["stages"]["render"]["status"], "done", st["stages"])
        return st, out

    def test_every_run_writes_a_graph_of_stages_backends_inputs_and_outputs(self):
        st, out = self.full_run()
        g = json.loads((out / "graph.json").read_text())
        nodes = {n["id"]: n for n in g["nodes"]}
        edges = {(e["from"], e["to"], e["rel"]) for e in g["edges"]}
        self.assertEqual(g["plan_digest"], json.loads((out / "plan.json").read_text())["digest"])
        self.assertEqual(nodes["stage:umbilicus"]["backend"]["name"], "file")    # the plan's own axis file
        self.assertEqual(nodes["stage:trace"]["backend"]["name"], "villa")
        self.assertEqual(nodes["stage:flatten"]["backend"]["name"], "villa")
        self.assertEqual(nodes["stage:ink"]["status"], "handoff")
        settings = json.loads((out / "plan.json").read_text())["settings"]
        self.assertEqual(nodes["stage:trace"]["settings"], {"trace": settings["trace"]})
        self.assertIn(("input:prediction_url", "stage:trace", "read"), edges)
        self.assertIn(("stage:trace", "file:traces", "made"), edges)
        self.assertIn(("stage:seeds", "stage:trace", "after"), edges)
        self.assertEqual(nodes["file:traces"]["made_by"], "trace")
        # each surface's render is a file node made by render, tied to its surface; the trace it read is upstream
        zarr = Path(st["surfaces"]["t00"]["render"]["zarr"])
        rel = str(zarr.resolve().relative_to(out.resolve()))
        self.assertEqual(nodes[f"file:{rel}"]["made_by"], "render")
        self.assertIn(("stage:render", f"file:{rel}", "made"), edges)
        self.assertIn((f"file:{rel}", "surface:t00", "of"), edges)
        self.assertIn("t00", nodes[f"file:{rel}"]["surfaces"])
        flat = str(Path(st["surfaces"]["t00"]["render_surface"]).resolve().relative_to(out.resolve()))
        self.assertEqual(flat, "flat/t00.tifxyz")
        self.assertIn((f"file:{flat}", "stage:render", "read"), edges)
        self.assertIn(("file:traces/t00", "stage:flatten", "read"), edges)
        self.assertIn("sha256", nodes["file:seeds.json"])
        # the graph of an unchanged folder is the same graph
        self.assertEqual(apgraph.build(out)["digest"], g["digest"])

    def test_a_graph_that_cannot_be_written_never_fails_the_run(self):
        with mock.patch.object(apgraph, "write", side_effect=OSError("disk full")):
            st, out = self.run_plan(self.plan(), until="seeds")
        self.assertEqual(st["stages"]["seeds"]["status"], "done")
        self.assertFalse((out / "graph.json").exists())

    def test_graph_catalog_model_metadata_is_not_claimed_as_the_actual_registered_weights(self):
        # A command-engine fixture deliberately registers itself under a downloadable model's name.
        st, out, _ = self.orient_run(0, None, "custom-reader", models=("reader-v2",))
        self.assertEqual(st["stages"]["ink"]["status"], "done")
        node = {n["id"]: n for n in apgraph.build(out)["nodes"]}["model:reader-v2"]
        self.assertIn("catalog_reference", node)
        self.assertTrue(node["catalog_reference"]["repo"])
        self.assertFalse({"repo", "revision", "sha256"} & node.keys())
        self.assertIn("actual weights are not verified", node["note"])

    def test_why_names_the_stage_backend_settings_inputs_and_the_swaps_that_would_test_it(self):
        st, out = self.full_run()
        zarr = Path(st["surfaces"]["t00"]["render"]["zarr"])
        w = apgraph.why(out, str(zarr))
        self.assertEqual(w["made_by"], "render")
        self.assertEqual([c["stage"] for c in w["upstream"]],
                         ["acquire", "umbilicus", "seeds", "trace", "bench", "qa", "flatten", "render"])
        self.assertEqual(w["surfaces"], ["t00"])
        self.assertIn("render", w["settings"])
        self.assertIn("input:volume_url", [i["id"] for i in w["inputs"]])
        tests = {t["stage"]: t for t in w["swap_tests"]}
        self.assertEqual(set(tests), {"umbilicus", "trace", "selfcross", "flatten", "snap", "repair"})  # not ink or triage
        self.assertIn("off", tests["flatten"]["try"])
        self.assertNotIn("villa", tests["flatten"]["try"])      # the backend in use is not a test of itself
        # a relative path inside a known folder, and a file the run never made
        self.assertEqual(apgraph.why(out, "seeds.json")["made_by"], "seeds")
        self.assertEqual(apgraph.why(out, "renders/nothing-here")["made_by"], "render")
        with self.assertRaises(apgraph.GraphError):
            apgraph.why(out, "somewhere-else/x.tif")
        with self.assertRaises(apgraph.GraphError):
            apgraph.why(out, str(self.d / "outside.tif"))

    def test_a_swap_with_reuse_starts_at_the_swapped_stage_and_diff_puts_the_change_on_it(self):
        st, out = self.full_run()
        rec = apgraph.swap(out, "flatten", "off", reuse=True, created="2026-10-15T00:00:00Z")
        new = Path(rec["out"])
        self.assertEqual(new, out.parent / "run-swap-flatten-off")
        plan = autopipe.check_plan(json.loads((new / "plan.json").read_text()))
        old = json.loads((out / "plan.json").read_text())
        self.assertNotEqual(plan["digest"], old["digest"])
        self.assertEqual(plan["resolved"], old["resolved"])
        self.assertFalse(plan["settings"]["flatten"]["enabled"])
        self.assertEqual({**plan["settings"], "flatten": old["settings"]["flatten"]}, old["settings"])
        self.assertEqual(plan["swap_of"]["digest"], old["digest"])
        self.assertEqual((plan["swap_of"]["from"]["name"], plan["swap_of"]["to"]), ("villa", "off"))
        self.assertEqual(rec["reused_stages"], ["acquire", "umbilicus", "seeds", "trace", "bench", "qa"])
        self.assertTrue((new / "traces").is_symlink())
        self.assertFalse((new / "umbilicus.json").is_symlink())     # a small file is copied, not linked
        self.assertFalse((new / "flat").exists())
        log = self.d / "fake.log"
        self.ctx.env["FAKE_LOG"] = str(log)
        st2 = autopipe.Run(vc3d_agent, self.ctx, new, plan).run()
        self.assertFalse(log.exists() and "vc_grow_seg_from_seed" in log.read_text())   # nothing traced again
        self.assertEqual(st2["stages"]["render"]["status"], "done", st2["stages"])
        self.assertEqual(st2["surfaces"]["t00"]["flatten"]["used"], "original")
        self.assertEqual(st2["surfaces"]["t00"]["trace"], st["surfaces"]["t00"]["trace"])
        g = json.loads((new / "graph.json").read_text())
        nodes = {n["id"]: n for n in g["nodes"]}
        self.assertEqual(nodes["stage:trace"]["reused_from"], str(out))
        self.assertEqual(nodes["stage:flatten"]["backend"]["name"], "off")
        d = apgraph.diff(out, new)
        self.assertEqual(d["first_divergent_stage"], "flatten")
        self.assertIn("one stage's backend changed", d["reading"])
        self.assertEqual(d["stages"]["flatten"]["backend"][0]["name"], "villa")
        self.assertFalse({"acquire", "umbilicus", "seeds", "trace", "qa"} & set(d["stages"]))
        self.assertEqual(d["surfaces"]["t00"]["accepted"], [True, True])
        self.assertIn("flatten", d["surfaces"]["t00"]["changes_by_stage"])
        self.assertNotIn("trace", d["surfaces"]["t00"]["changes_by_stage"])
        self.assertEqual(d["settings_changes"], [{"key": "flatten.enabled", "a": True, "b": False}])
        # the original run is untouched
        self.assertEqual(json.loads((out / "state.json").read_text())["plan_digest"], old["digest"])

    def test_a_swap_without_reuse_is_a_fresh_plan(self):
        _, out = self.run_plan(self.plan(), until="seeds")
        rec = apgraph.swap(out, "snap", "ct", new_out=self.d / "arm")
        self.assertEqual(rec["reused_stages"], [])
        self.assertEqual(sorted(p.name for p in (self.d / "arm").iterdir()), ["plan.json", "swap.json"])
        plan = json.loads((self.d / "arm" / "plan.json").read_text())
        self.assertEqual(plan["settings"]["render"]["snap"]["source"], "ct")
        self.assertEqual(plan["swap_of"]["acts_at"], "render")

    def test_refusals(self):
        _, out = self.run_plan(self.plan(), until="seeds")
        with self.assertRaisesRegex(apgraph.GraphError, "nothing to swap"):
            apgraph.swap(out, "flatten", "villa")
        with self.assertRaisesRegex(apgraph.GraphError, "stage is one of"):
            apgraph.swap(out, "bench", "villa")
        with self.assertRaisesRegex(apgraph.GraphError, "no backend"):
            apgraph.swap(out, "flatten", "magic")
        with self.assertRaisesRegex(apgraph.GraphError, "publishes no axis"):
            apgraph.swap(out, "umbilicus", "catalog")
        with self.assertRaisesRegex(apgraph.GraphError, "not offered for a qa swap"):
            apgraph.swap(out, "repair", "switchfix", reuse=True)
        with self.assertRaisesRegex(apgraph.GraphError, "trace is not run"):
            apgraph.swap(out, "flatten", "off", reuse=True)     # the run stopped at seeds
        (self.d / "full").mkdir()
        (self.d / "full" / "x").write_text("")
        with self.assertRaisesRegex(apgraph.GraphError, "not empty"):
            apgraph.swap(out, "flatten", "off", new_out=self.d / "full")
        with self.assertRaisesRegex(apgraph.GraphError, "not an AutoPipeline run folder"):
            apgraph.build(self.d / "full")
        # a frozen plan edited by hand is refused before anything is derived from it
        plan = json.loads((out / "plan.json").read_text())
        plan["settings"]["seeds"]["count"] = 3
        (out / "plan.json").write_text(json.dumps(plan))
        with self.assertRaises(autopipe.AutoError):
            apgraph.swap(out, "flatten", "off")

    def test_diff_of_two_unrelated_runs_is_not_read_as_one_stage(self):
        _, a = self.run_plan(self.plan(), self.d / "a", until="seeds")
        p = self.plan()
        p["settings"]["seeds"]["count"] = 1
        p["settings"]["flatten"]["enabled"] = False
        p["digest"] = autopipe.digest({k: p[k] for k in ("version", "settings", "resolved")})
        _, b = self.run_plan(p, self.d / "b", until="seeds")
        d = apgraph.diff(a, b)
        self.assertIsNone(d["swap"])
        self.assertEqual(d["first_divergent_stage"], "seeds")
        self.assertIn("not a one-factor comparison", d["reading"])
        self.assertEqual(d["settings_changed"], 2)


    def test_the_agent_tool_and_the_command_line_take_them(self):
        _, out = self.full_run()
        call = lambda **a: vc3d_agent.call("autopipeline", a, self.ctx)     # noqa: E731
        g = call(action="graph", out=str(out))
        self.assertEqual(g["stages"]["flatten"], {"status": "done", "backend": "villa"})
        self.assertEqual(g["nodes"]["stage"], len(autopipe.STAGES))
        self.assertEqual(call(action="status", out=str(out))["graph"], str(out / "graph.json"))
        self.assertEqual(call(action="why", out=str(out), path="seeds.json")["made_by"], "seeds")
        sw = call(action="swap", out=str(out), stage="flatten", backend=["off"], reuse=True, to=str(self.d / "arm"))
        self.assertEqual(sw["out"], str(self.d / "arm"))
        d = call(action="diff", out=str(out), other=str(self.d / "arm"))
        self.assertEqual(d["first_divergent_stage"], "flatten")
        pf = call(action="preflight", out=str(out))
        self.assertTrue({r["stage"] for r in pf["rows"]} >= {"trace", "flatten", "ink"})
        self.assertIn("flatten", call(action="backends")["stages"])
        for bad, why in (({"action": "why"}, "why needs path"), ({"action": "swap", "stage": "flatten"},
                                                                 "swap needs stage and backend"),
                         ({"action": "diff"}, "diff needs other"),
                         ({"action": "swap", "stage": "flatten", "backend": ["villa"]}, "nothing to swap")):
            with self.assertRaisesRegex(vc3d_agent.ToolError, why):
                call(out=str(out), **bad)
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        p = subprocess.run([sys.executable, "-m", "kit", "autopipeline", "why", str(out), "seeds.json"],
                           capture_output=True, text=True, cwd=str(ROOT), env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["made_by"], "seeds")
        p = subprocess.run([sys.executable, "-m", "kit", "autopipeline", "swap", str(out), "--stage", "snap",
                            "--backend", "ct", "--to", str(self.d / "arm2")],
                           capture_output=True, text=True, cwd=str(ROOT), env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["swap_of"]["to"], "ct")
        p = subprocess.run([sys.executable, "-m", "kit", "autopipeline", "swap", str(out), "--stage", "snap",
                            "--backend", "nope"], capture_output=True, text=True, cwd=str(ROOT), env=env)
        self.assertEqual(p.returncode, 2)
        self.assertIn("no backend nope", p.stderr)

    # Findings 13 to 21 of an earlier review and regressions for their boundary cases.

    def frozen(self, plan, name):
        """A run folder holding only a frozen plan: what swap and diff read (a state is written beside it by hand)."""
        out = self.d / name
        out.mkdir(parents=True)
        plan["digest"] = autopipe.digest({k: plan[k] for k in ("version", "settings", "resolved")})
        (out / "plan.json").write_text(json.dumps(plan))
        return out

    def test_a_snap_or_repair_swap_holds_the_arm_and_diff_checks_that_it_did(self):
        # finding 13: the new backend takes its own defaults; the arm's check, reference, sham and repair share stay
        qa = {"require_seated": "none", "windaudit": "off", "windows": 1, "repair": {"min_area_share": 0.3}}
        out = self.frozen(self.plan(render={"snap": {"source": "pred", "sham": True, "check": "record", "level": 1}},
                                    qa=qa), "orig")
        apgraph.swap(out, "snap", "ct", new_out=self.d / "ct")
        arm = json.loads((self.d / "ct" / "plan.json").read_text())
        self.assertEqual(arm["settings"]["render"]["snap"],
                         {**autopipe.OPTIONAL["render.snap"], "source": "ct", "sham": True, "check": "record"})
        self.assertEqual(arm["settings"]["qa"]["repair"]["min_area_share"], 0.3)
        with self.assertRaisesRegex(apgraph.GraphError, "nothing to swap"):
            apgraph.swap(out, "repair", "barrier")         # the repair as it was (the default method) is no swap
        self.assertIn("one stage's backend changed", apgraph.diff(out, self.d / "ct")["reading"])
        # an arm that names the swap but changed more (the sham arm made a real snap) is not read as one factor
        arm["settings"]["render"]["snap"] = {**autopipe.OPTIONAL["render.snap"], "source": "ct"}
        bad = self.frozen(arm, "bad")
        d = apgraph.diff(out, bad)
        self.assertEqual(d["swap"]["stage"], "snap")
        self.assertIn("not a one-factor comparison", d["reading"])
        self.assertIn("beyond the swap", d["reading"])

    def test_diff_reads_a_swap_as_one_factor_only_when_the_stages_before_it_held(self):
        # finding 14: an arm made without reuse traces again, and the tracer does not give the same surface twice
        st, out = self.run_plan(self.plan(), until="qa")
        arm = Path(apgraph.swap(out, "flatten", "off", new_out=self.d / "arm")["out"])
        held = json.loads(json.dumps(st))
        held["plan_digest"] = json.loads((arm / "plan.json").read_text())["digest"]
        for s in held["surfaces"].values():
            s["flatten"] = {"used": "original"}
        (arm / "state.json").write_text(json.dumps(held))
        same = apgraph.diff(out, arm)
        self.assertIn("one stage's backend changed", same["reading"])
        held["surfaces"]["t00"]["trace"]["area_cm2"] = 99.0
        (arm / "state.json").write_text(json.dumps(held))
        d = apgraph.diff(out, arm)
        self.assertEqual(d["first_divergent_stage"], "flatten")
        self.assertIn("not a one-factor comparison", d["reading"])
        self.assertIn("--reuse", d["reading"])
        self.assertEqual((same["upstream_changed"], same["one_factor"]), ([], True))
        self.assertEqual((d["upstream_changed"], d["one_factor"]), (["trace"], False))
        rep = Path(apgraph.swap(out, "repair", "switchfix", new_out=self.d / "rep")["out"])
        (rep / "state.json").write_text(json.dumps(held))
        d = apgraph.diff(out, rep)
        self.assertEqual((d["first_divergent_stage"], d["upstream_changed"]), ("qa", ["trace"]))
        self.assertNotIn("--reuse", d["reading"])                   # a qa swap is never reused
        self.assertIn("trace.repeats", d["reading"])
        # a surface only one run traced is a trace difference too
        held["surfaces"]["t00"]["trace"] = st["surfaces"]["t00"]["trace"]
        del held["surfaces"]["t01"]
        (arm / "state.json").write_text(json.dumps(held))
        self.assertEqual(apgraph.diff(out, arm)["upstream_changed"], ["trace"])

    def test_diff_checks_upstream_backends_before_the_declared_swap_even_with_no_details(self):
        st, out = self.run_plan(self.plan(), until="qa")
        arm = Path(apgraph.swap(out, "flatten", "off", reuse=True)["out"])
        held = json.loads((arm / "state.json").read_text())
        # A fallback chose another upstream backend during a rerun of the same plan. That earlier divergence
        # must not become the purported one-factor swap, even when the caller suppresses change details.
        held["stages"]["umbilicus"]["record"] = {"source": "estimate", "estimator": "normals"}
        held["stages"]["seeds"]["record"]["seeds"] = ["different"]
        (arm / "state.json").write_text(json.dumps(held))
        for a, b in ((out, arm), (arm, out)):
            d = apgraph.diff(a, b, limit=0)
            self.assertEqual(d["first_divergent_stage"], "umbilicus")
            self.assertIn("not a one-factor comparison", d["reading"])
            self.assertEqual(d["upstream_changed"], ["umbilicus", "seeds"])
            self.assertFalse(d["one_factor"])
            self.assertGreater(d["stages"]["seeds"]["record_changes"], 0)
            self.assertEqual(d["stages"]["seeds"]["changes"], [])
            self.assertIn("before flatten differ", d["reading"])

    def test_reuse_and_the_graph_place_a_trace_method_record_and_a_repaired_surface(self):
        # finding 15: s_trace writes a trace method's record under its name, a qa repair writes surface_traced
        self.register_trace_fixture()
        st, out = self.run_plan(self.plan(), until="qa")
        self.assertEqual(apgraph.surface_key_stage("t00", "testdouble"), "trace")
        self.assertEqual(apgraph.surface_key_stage("t00", "surface_traced"), "qa")
        rep = out / "repaired" / "t00"
        rep.mkdir(parents=True)
        (rep / "x.tif").write_text("")
        t00 = st["surfaces"]["t00"]
        t00.update(testdouble={"steps": 2}, surface_traced=t00["surface"], surface=str(rep))
        (out / "state.json").write_text(json.dumps(st))
        edges = {(e["from"], e["to"], e["rel"]) for e in apgraph.build(out)["edges"]}
        self.assertIn(("stage:qa", "file:repaired/t00", "made"), edges)
        self.assertIn(("file:traces/t00", "stage:qa", "read"), edges)
        self.assertNotIn(("file:repaired/t00", "stage:trace", "read"), edges)    # no edge back into the trace
        arm = Path(apgraph.swap(out, "flatten", "off", reuse=True)["out"])
        kept = json.loads((arm / "state.json").read_text())["surfaces"]["t00"]
        self.assertEqual((kept["testdouble"], kept["surface"], kept["surface_traced"]),
                         ({"steps": 2}, str(rep), t00["surface_traced"]))

    def test_why_explains_the_outputs_a_reused_swap_linked(self):
        # finding 16: a linked entry resolves into the original folder, but it is the arm's own
        _, out = self.run_plan(self.plan(), until="qa")
        arm = Path(apgraph.swap(out, "flatten", "off", reuse=True)["out"])
        self.assertTrue((arm / "traces").is_symlink())
        w = apgraph.why(arm, "traces/t00")
        self.assertEqual(w["made_by"], "trace")
        self.assertEqual(w["upstream"][-1]["reused_from"], str(out))
        self.assertEqual(apgraph.why(arm, str(arm / "traces"))["made_by"], "trace")
        node = {n["id"]: n for n in apgraph.build(arm)["nodes"]}["file:traces"]
        self.assertEqual(node["made_by"], "trace")
        self.assertNotIn("outside_run", node)

    def test_why_offers_only_the_swaps_swap_would_take(self):
        # finding 17: each stage's own backend in use is left out, and so is a swap the plan's checks refuse
        _, out = self.run_plan(self.plan(), until="seeds")
        tests = {t["stage"]: t for t in apgraph.why(out, "renders/nothing-here")["swap_tests"]}
        self.assertEqual(tests["snap"]["try"], ["pred", "ct"])
        # barrier (the default method since 22 Oct 2026) and switchfix first, then the tool registry's repair
        # backends (reg:ID, added by an AutoPipeline extension)
        self.assertEqual(tests["repair"]["try"][:2], ["barrier", "switchfix"])
        self.assertEqual(set(tests["repair"]["try"][2:]),
                         {n for n in apbackends.choices("repair") if n.startswith("reg:")})
        self.assertEqual(tests["umbilicus"]["try"], ["villa", "centrenet", "normals"])
        self.assertIn("publishes no axis", tests["umbilicus"]["refused"]["catalog"])
        self.assertNotIn("--reuse", tests["repair"]["command"])     # a qa swap is never reused
        self.assertNotIn("--reuse", tests["flatten"]["command"])    # the run stopped before trace
        self.assertIn("--reuse", tests["trace"]["command"])
        for t in tests.values():
            for name in t["try"]:
                apgraph.swap(out, t["stage"], name, new_out=self.d / f"arm-{t['stage']}-{name}")

    def test_a_swap_names_the_swapped_stages_own_backend_as_from(self):
        # finding 18: a snap, repair or triage swap acts at render, qa or report, whose own backend is another
        out = self.frozen(self.plan(), "orig")
        sw = apgraph.swap(out, "snap", "ct", new_out=self.d / "a")["swap_of"]
        self.assertEqual((sw["from"]["name"], sw["to"], sw["acts_at"]), ("off", "ct", "render"))
        self.assertEqual(sw["acts_at_backend"]["name"], "villa")
        self.assertEqual(apgraph.swap(out, "repair", "switchfix", new_out=self.d / "b")["swap_of"]["from"]["name"],
                         "off")
        self.assertEqual(apgraph.swap(out, "flatten", "off", new_out=self.d / "c")["swap_of"]["from"]["name"], "villa")
        tri = apgraph.swap(out, "triage", "rowscore", new_out=self.d / "tri")["swap_of"]
        self.assertEqual((tri["from"]["name"], tri["acts_at"], tri["acts_at_backend"]["name"]),
                         ("off", "report", "kit"))

    def test_a_swap_to_the_backend_the_run_already_uses_is_refused(self):
        # finding 19: the settings differ, the backend in effect does not
        plan = self.plan(umbilicus={"source": "auto"})
        plan["resolved"]["catalog_umbilicus"] = "https://example.invalid/umbilicus.json"
        out = self.frozen(plan, "cat")
        with self.assertRaisesRegex(apgraph.GraphError, "nothing to swap"):
            apgraph.swap(out, "umbilicus", "catalog")      # auto takes the published axis
        (out / "state.json").write_text(json.dumps({"stages": {"umbilicus": {
            "status": "done", "record": {"source": "catalog"}}}}))
        with self.assertRaisesRegex(apgraph.GraphError, "already used catalog in this run: nothing to swap"):
            apgraph.swap(out, "umbilicus", "catalog")
        out = self.frozen(self.plan(umbilicus={"source": "auto"}), "est")
        (out / "state.json").write_text(json.dumps({"stages": {"umbilicus": {
            "status": "done", "record": {"source": "estimate", "estimator": "villa"}}}}))
        with self.assertRaisesRegex(apgraph.GraphError, "already used villa in this run: nothing to swap"):
            apgraph.swap(out, "umbilicus", "villa")
        apgraph.swap(out, "umbilicus", "centrenet", new_out=self.d / "c")
        # a list that starts with the backend in use changes only what runs when it gives no axis
        with self.assertRaisesRegex(apgraph.GraphError, "already used villa in this run: nothing to swap"):
            apgraph.swap(out, "umbilicus", ["villa", "normals"])
        apgraph.swap(out, "umbilicus", ["centrenet", "villa"], new_out=self.d / "cv")
        out = self.frozen(plan, "cat2")
        with self.assertRaisesRegex(apgraph.GraphError, "already uses catalog in this plan: nothing to swap"):
            apgraph.swap(out, "umbilicus", ["catalog", "centrenet"])
        # the same snap source with other parameters is the same backend
        out = self.frozen(self.plan(render={"snap": {"source": "pred", "max_off": 9}}), "snap")
        with self.assertRaisesRegex(apgraph.GraphError, "nothing to swap"):
            apgraph.swap(out, "snap", "pred")

    def test_graph_and_diff_resolve_the_planned_auto_axis_from_the_frozen_catalog(self):
        plan = self.plan(umbilicus={"source": "auto"})
        plan["resolved"]["catalog_umbilicus"] = "https://example.invalid/axis.json"
        out = self.frozen(plan, "catalog")
        nodes = {n["id"]: n for n in apgraph.build(out)["nodes"]}
        self.assertEqual(nodes["stage:umbilicus"]["backend"]["name"], "catalog")
        arm = apgraph.swap(out, "umbilicus", "villa")["out"]
        d = apgraph.diff(out, arm)
        self.assertEqual([v["name"] for v in d["stages"]["umbilicus"]["backend"]], ["catalog", "villa"])
        self.assertTrue(d["one_factor"])

    def test_a_trace_swap_to_a_method_with_its_own_resolved_inputs_is_one_factor(self):
        # finding 20: a trace extension freezes its rule identity in resolved, which the swap itself adds
        self.register_trace_fixture()
        _, out = self.run_plan(self.plan(), until="seeds")
        arm = Path(apgraph.swap(out, "trace", "testdouble", reuse=True)["out"])
        for a, b in ((out, arm), (arm, out)):
            d = apgraph.diff(a, b)
            self.assertEqual([c["key"] for c in d["resolved_changes"]], ["testdouble_rule"])
            self.assertIn("one stage's backend changed", d["reading"])
        # Ownership of the key is insufficient: its frozen value must be the one this swap derives.
        plan = json.loads((arm / "plan.json").read_text())
        plan["resolved"]["testdouble_rule"] = "another-rule"
        bad = self.frozen(plan, "bad-rule")
        for a, b in ((out, bad), (bad, out)):
            d = apgraph.diff(a, b, limit=0)
            self.assertFalse(d["one_factor"])
            self.assertIn("resolved inputs differ beyond the swap (testdouble_rule)", d["reading"])

    def test_a_nontrace_swap_keeps_frozen_trace_inputs_without_resolving_them_again(self):
        self.register_trace_fixture()
        plan = self.plan(trace={"testdouble": True})
        autopipe.check_settings(plan["settings"], plan["resolved"]["sample"])
        plan["resolved"].update(autopipe.trace_method_resolved(plan["settings"]))
        out = self.frozen(plan, "orig")
        # A plugin's resolver can change between kit versions. A swap of another stage still holds its inputs.
        with mock.patch.object(autopipe, "trace_method_resolved", return_value={"testdouble_rule": "new-rule"}):
            arm = Path(apgraph.swap(out, "flatten", "off")["out"])
            self.assertEqual(json.loads((arm / "plan.json").read_text())["resolved"], plan["resolved"])
            self.assertTrue(apgraph.diff(out, arm)["one_factor"])

    def test_an_ink_swap_to_a_model_this_machine_cannot_get_is_refused(self):
        # finding 21: the models this machine has registered are checked, as make_plan checks them (own-reader is
        # neither a model kit can fetch nor a built-in one, as reader-v3-koine has been since 23 Oct 2026)
        out = self.frozen(self.plan(), "orig")
        with self.assertRaisesRegex(apgraph.GraphError, "check the spelling"):
            apgraph.swap(out, "ink", "own-reader", models={})
        apgraph.swap(out, "ink", "own-reader", models={"own-reader": {}}, new_out=self.d / "mine")
        with self.assertRaisesRegex(vc3d_agent.ToolError, "check the spelling"):
            vc3d_agent.call("autopipeline", {"action": "swap", "out": str(out), "stage": "ink",
                                             "backend": ["own-reader"]}, self.ctx)
        # the models a swap holds passed make_plan where the plan was made: another stage's swap does not ask again
        held = self.frozen(self.plan(ink={"where": "modal", "models": ["mine"]}), "held")
        apgraph.swap(held, "flatten", "off", models={}, new_out=self.d / "held-arm")


for _name in dir(TA.TestRun):      # TestGraph borrows TestRun's fixtures, not its tests
    if _name.startswith("test_"):
        setattr(TestGraph, _name, None)


class TestPieces(unittest.TestCase):
    def test_every_run_folder_entry_has_its_writers(self):
        self.assertEqual(apgraph.entry_writers("labels", {"score": {}}), ("score",))
        self.assertEqual(apgraph.entry_writers("labels", {"score": {"transfer": {"segments": ["x"]}}}),
                         ("acquire", "score"))
        self.assertEqual(apgraph.entry_writers("transfer", {"score": {}}), ("render", "score"))
        self.assertEqual(apgraph.entry_writers("nothing", {}), ())
        self.assertEqual(set(apgraph.STAGE_SETTINGS), set(autopipe.STAGES))
        self.assertEqual(set(apgraph.STAGE_INPUTS), set(autopipe.STAGES))
        self.assertTrue(set(apgraph.OUT_STAGE.values()) <= set(autopipe.STAGES))
        self.assertTrue(set(apgraph.SURFACE_KEY_STAGE.values()) <= set(autopipe.STAGES))

    def test_flat_leaves_out_volatile_fields_and_the_run_folder(self):
        f = apgraph._flat({"a": {"at": 1, "b": "/r/x/y", "seconds": 2}, "c": [{"d": 1}]}, root=["/r/x"])
        self.assertEqual(f, {"a.b": "<run>/y", "c[0].d": 1})


if __name__ == "__main__":
    unittest.main()
