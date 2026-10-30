"""AutoPipeline learns from its own runs (kit/aplearn.py): the ledger, what it leaves out, suggestions, time
estimates, reviews and the preregistered check. Run records are built here by hand, plus whole runs on the fakes of
test_autopipe: no villa build, no torch, no network."""

import hashlib
import json
import random
import statistics
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_autopipe as TA

from kit import aplearn, autopipe, vc3d_agent

ROOT = Path(__file__).resolve().parent.parent
SENTINEL = 0.987654321      # planted in maps' scores and triage: never in the ledger


def settings(**over):
    return autopipe._merge(autopipe.DEFAULTS, {"purpose": "benchmark", **over})


def plan(sample="PHercX", version=autopipe.PLAN_VERSION, resolved=None, **over):
    s = settings(**over)
    r = {"sample": sample, "volume": "V1", "voxel_um": 9.4, **(resolved or {})}
    p = {"version": version, "settings": s, "resolved": r}
    p["digest"] = autopipe.digest(p)
    return p


def state(p, traces, at="2026-10-20T01:00:00Z", trace_seconds=600.0, extra_stages=None, ran=None):
    """A state.json for plan p: traces is [(sid, seed_index, repeat, outcome)] with outcome accepted, qa (rejected by
    qa, ours), qa-infra (a qa rejection resting on checks that could not run), tracer (the tracer exited), seed (the
    seed check refused it) or lost (no record). ran: the traces the trace stage says its tracer ran (Run.s_trace's
    record since amendment (e)); left out, the stage names none, as an older kit's did."""
    surfaces, failures, planned = {}, {}, []
    for sid, seed, rep, outcome in traces:
        planned.append({"sid": sid, "seed_index": seed, "repeat": rep})
        if outcome == "accepted":
            surfaces[sid] = {"surface": f"traces/{sid}", "accepted": True,
                             "qa": {"reasons": [], "check_surface": {"grid": {"area_cm2": 1.5, "max_gen": 25}}},
                             "render": {"zarr": f"renders/{sid}.zarr"}, "scores": {"auc": SENTINEL}}
        elif outcome == "qa":
            surfaces[sid] = {"surface": f"traces/{sid}", "accepted": False,
                             "qa": {"reasons": ["self-intersections: 40", "seating: partly seated"],
                                    "failure": {"kind": "ours"}}}
        elif outcome == "qa-infra":
            surfaces[sid] = {"surface": f"traces/{sid}", "accepted": False,
                             "qa": {"reasons": ["valid fraction: not measured"], "failure": {"kind": "infrastructure"}}}
        elif outcome == "tracer":
            failures[sid] = {"kind": "ours", "reason": "the tracer exited 1"}
        elif outcome == "seed":
            failures[sid] = {"kind": "ours", "reason": "seed check refused it: no sheet under the seed"}
    stages = {"acquire": {"status": "done", "at": at, "seconds": 5.0, "record": {}},
              "umbilicus": {"status": "done", "at": at, "seconds": 50.0,
                            "record": {"source": "estimated", "estimator": None, "kept": 30}},
              "seeds": {"status": "done", "at": at, "seconds": 2.0, "record": {}},
              "trace": {"status": "done", "at": at, "seconds": trace_seconds,
                        "record": {} if ran is None else {"ran": list(ran)}},
              "qa": {"status": "done", "at": at, "seconds": 20.0, "record": {}},
              "score": {"status": "done", "at": at, "seconds": 3.0, "record": {"auc": SENTINEL}},
              "report": {"status": "done", "at": at, "seconds": 0.0,
                         "record": {"triage": {"ranking": [{"sid": "t00", "score": SENTINEL}]}}},
              **(extra_stages or {})}
    return {"plan_digest": p["digest"], "stages": stages, "surfaces": surfaces, "trace_failures": failures,
            "planned_traces": planned}


def write_run(folder, p, st):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plan.json").write_text(json.dumps(p))
    (folder / "state.json").write_text(json.dumps(st))
    return folder


def record(run, sample, arm_settings, ys, ended, machine="m1", seeds=None, trace_per=100.0, extra=None):
    """A ledger record built directly: ys are the traces' qa outcomes (1 accepted, 0 rejected), seeds the seed index
    of each (default one seed per trace)."""
    s = settings(**arm_settings)
    arm, key = aplearn.trace_arm(s)
    seeds = seeds if seeds is not None else list(range(len(ys)))
    reps = {}
    traces = []
    for y, sd in zip(ys, seeds):
        reps[sd] = reps.get(sd, -1) + 1
        traces.append({"sid": f"t{sd:02d}-r{reps[sd]}", "seed_index": sd, "repeat": reps[sd],
                       "outcome": "accepted" if y else "rejected", "stage": None if y else "qa", "reasons": []})
    r = {"v": aplearn.VERSION, "kind": "run", "source": "run", "run": run, "plan_digest": f"d-{run}",
         "sample": sample, "volume": "V1", "ingested": ended, "excluded": None, "ended": ended,
         "machine": {"key": machine}, "arm": arm, "arm_key": key, "arm_label": aplearn.arm_label(arm),
         "planned": {"generations": s["trace"]["generations"], "repeats": s["trace"].get("repeats") or 1},
         "stages": {"trace": {"status": "done", "seconds": trace_per * len(ys), "per_trace": trace_per,
                              "traces": len(ys), "traces_from": "ran"}},
         "traces": traces, "umbilicus": None}
    r.update(extra or {})
    return r


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.ctx = vc3d_agent.Context(root=self.d / "kit", home=self.d / "home", env={})
        (self.d / "kit").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def ledger(self):
        return aplearn.load(aplearn.store_path(self.ctx.home))


class TestHarvest(Home):
    def test_each_trace_gets_its_fate_and_infrastructure_is_void(self):
        p = plan(trace={"repeats": 2})
        st = state(p, [("t00-r0", 0, 0, "accepted"), ("t00-r1", 0, 1, "qa"), ("t01-r0", 1, 0, "tracer"),
                       ("t01-r1", 1, 1, "qa-infra"), ("t02-r0", 2, 0, "seed"), ("t02-r1", 2, 1, "lost")])
        rec, why = aplearn.harvest(write_run(self.d / "run", p, st))
        self.assertIsNone(why)
        got = {t["sid"]: t["outcome"] for t in rec["traces"]}
        self.assertEqual(got, {"t00-r0": "accepted", "t00-r1": "rejected", "t01-r0": "rejected", "t01-r1": "void",
                               "t02-r0": "void", "t02-r1": "void"})
        why_void = {t["sid"]: t.get("why", "") for t in rec["traces"]}
        self.assertIn("seed check", why_void["t02-r0"])
        self.assertIn("infrastructure", why_void["t01-r1"])
        self.assertEqual({t["sid"]: t["reasons"] for t in rec["traces"]}["t00-r1"], ["self-intersections", "seating"])
        self.assertEqual(rec["planned"]["repeats"], 2)
        self.assertEqual(rec["machine"], None)              # harvest alone names no machine; record_run does
        self.assertEqual(rec["ended"], "2026-10-20T01:00:00Z")
        # 600 s over the 4 traces the tracer ran: a refused seed and a lost trace never started
        self.assertEqual((rec["stages"]["trace"]["per_trace"], rec["stages"]["trace"]["traces"]), (150.0, 4))
        self.assertEqual(rec["stages"]["trace"]["backend"], "villa")
        self.assertEqual([u["y"] for u in aplearn.units([rec])], [1, 0, 0])

    def test_the_ledger_never_holds_a_map_score_or_triage_list(self):
        p = plan()
        st = state(p, [("t00", 0, 0, "accepted"), ("t01", 1, 0, "qa")])
        rec, _ = aplearn.harvest(write_run(self.d / "run", p, st))
        text = json.dumps(rec)
        self.assertNotIn(str(SENTINEL), text)
        self.assertNotIn("ranking", text)
        self.assertNotIn("auc", text.lower())
        for st_rec in rec["stages"].values():
            self.assertLessEqual(set(st_rec), {"status", "at", "seconds", "backend", "kind", "reused_from",
                                               "per_trace", "traces", "traces_from", "machine"})
        for t in rec["traces"]:
            self.assertLessEqual(set(t), {"sid", "seed_index", "repeat", "outcome", "why", "stage", "reasons",
                                          "rendered", "area_cm2", "max_gen", "review", "review_at"})

    def test_a_target_run_is_never_written(self):
        p = plan(purpose="target", experiment="x")
        rec, why = aplearn.harvest(write_run(self.d / "run", p, state(p, [("t00", 0, 0, "accepted")])))
        self.assertIsNone(rec)
        self.assertIn("target", why)
        # a folder under experiments/ is a target run's whatever its plan says
        p = plan()
        rec, why = aplearn.harvest(write_run(self.d / "experiments" / "e1" / "autopipe" / "r", p,
                                             state(p, [("t00", 0, 0, "accepted")])))
        self.assertIsNone(rec)
        out = aplearn.record_run(self.ctx, self.d / "experiments" / "e1" / "autopipe" / "r")
        self.assertIn("skipped", out)
        self.assertFalse(aplearn.store_path(self.ctx.home).exists())

    def test_held_out_scrolls_reserved_segments_and_the_report_surface_are_excluded(self):
        reserve = self.d / "reserved.json"
        reserve.write_text(json.dumps([{"sample": "PHercHeld", "segment": "w1", "why": "held out"}]))
        with mock.patch.object(autopipe, "RESERVED_FILE", reserve):
            p = plan(sample="PHercHeld")
            rec, _ = aplearn.harvest(write_run(self.d / "a", p, state(p, [("t00", 0, 0, "accepted")])))
            self.assertIn("held-out", rec["excluded"])
            self.assertNotIn("traces", rec)
            p = plan(sample="PHercX", score={"transfer": {"segments": ["0841-ag405"]}})
            rec, _ = aplearn.harvest(write_run(self.d / "b", p, state(p, [("t00", 0, 0, "accepted")])))
            self.assertIn("0841-ag405", rec["excluded"])
            self.assertEqual(aplearn.units([rec]), [])
            self.assertEqual(aplearn.held_out_samples(), ["PHercHeld"])
        # without a reserve file (the public release) no scroll is held out
        self.assertEqual(aplearn.held_out_samples(self.d / "absent.json"), [])

    def test_version_1_plans_and_report_windings_count_no_trace(self):
        p = plan(version=1)
        rec, _ = aplearn.harvest(write_run(self.d / "v1", p, state(p, [("t00", 0, 0, "accepted")])))
        self.assertEqual([t["outcome"] for t in rec["traces"]], ["void"])
        p = plan(resolved={"winding_bench": {"rule_digest": "x"}})
        st = state(p, [("t00", 0, 0, "qa"), ("t01", 1, 0, "qa"), ("t02", 2, 0, "accepted")])
        st["surfaces"]["t00"]["bench"] = {"dominant_split": "tune"}
        st["surfaces"]["t01"]["bench"] = {"dominant_split": "report"}
        rec, _ = aplearn.harvest(write_run(self.d / "bench", p, st))
        self.assertEqual([t["outcome"] for t in rec["traces"]], ["rejected", "void", "void"])

    def test_a_published_segment_run_has_no_trace_arm_but_its_stage_times_count(self):
        p = plan(segment="0841-w00")
        st = state(p, [])
        rec, _ = aplearn.harvest(write_run(self.d / "seg", p, st))
        self.assertIsNone(rec["arm_key"])
        self.assertEqual(aplearn.status([rec])["segment_runs"], 1)
        self.assertIn("umbilicus", {u["stage"] for u in aplearn.time_units([rec])})

    def test_a_stage_carried_over_by_swap_reuse_is_no_time_and_its_traces_are_not_counted_again(self):
        p = plan()
        st = state(p, [("t00", 0, 0, "accepted")])
        st["reused_from"] = {"run": "earlier", "stages": ["acquire", "umbilicus", "seeds", "trace"]}
        rec, _ = aplearn.harvest(write_run(self.d / "swap", p, st))
        self.assertIsNone(rec["stages"]["trace"]["seconds"])
        self.assertEqual(rec["traces"], [])
        self.assertEqual({u["stage"] for u in aplearn.time_units([rec])}, {"qa", "score"})

    def test_axis_reuse_checks_the_completed_stage_receipt_before_offering_its_file(self):
        p = plan()
        st = state(p, [("t00", 0, 0, "accepted")])
        f = write_run(self.d / "axis", p, st)
        axis = f / "umbilicus.json"
        axis.write_text('{"control_points": [[0, 0, 0], [0, 0, 10]]}')
        expected = hashlib.sha256(axis.read_bytes()).hexdigest()
        st["stages"]["umbilicus"]["record"]["sha256"] = expected
        good, _ = aplearn.harvest(f, plan=p, state=st)
        self.assertEqual(good["umbilicus"]["sha256_source"], "stage_receipt")
        change = next(c for c in aplearn.suggest([good], "PHercX")["changes"]
                      if c["key"] == "umbilicus.source")
        self.assertEqual(change["value"], str(axis))
        self.assertEqual(change["evidence"]["sha256"], expected)
        self.assertEqual(change["label"], "Sourced fact (the earlier run's stage receipt)")
        axis.write_text('{"control_points": [[99, 99, 0], [99, 99, 10]]}')
        changed, _ = aplearn.harvest(f, plan=p, state=st)
        self.assertEqual(changed["umbilicus"]["sha256"], expected)
        self.assertNotIn("path", changed["umbilicus"])
        self.assertIn("receipt", changed["umbilicus"]["reuse_refused"])
        self.assertNotIn("umbilicus", aplearn.suggest([changed], "PHercX")["settings"])
        # This guard affects only the offered axis, never the preregistered evaluation units.
        self.assertEqual(aplearn.units([changed]), aplearn.units([good]))
        self.assertEqual(aplearn.time_units([changed]), aplearn.time_units([good]))
        for bad in (None, "", 3, [expected]):
            st["stages"]["umbilicus"]["record"]["sha256"] = bad
            malformed, _ = aplearn.harvest(f, plan=p, state=st)
            self.assertNotIn("path", malformed["umbilicus"], bad)
            self.assertNotIn("umbilicus", aplearn.suggest([malformed], "PHercX")["settings"], bad)

    def test_legacy_axis_without_a_receipt_is_explicitly_a_file_observation(self):
        p = plan()
        st = state(p, [])
        f = write_run(self.d / "legacy-axis", p, st)
        axis = f / "umbilicus.json"
        axis.write_text('{"control_points": [[0, 0, 0], [0, 0, 10]]}')
        rec, _ = aplearn.harvest(f, plan=p, state=st)
        self.assertEqual(rec["umbilicus"]["sha256_source"], "file_at_harvest")
        self.assertEqual(rec["umbilicus"]["sha256"], hashlib.sha256(axis.read_bytes()).hexdigest())
        suggestion = aplearn.suggest([rec], "PHercX")
        change = suggestion["changes"][0]
        self.assertEqual(change["value"], str(axis))
        self.assertEqual(change["evidence"]["sha256_source"], "file_at_harvest")
        self.assertIn("historical stage unverified", change["label"])
        shown = aplearn.summary(suggestion)["changes"][0]
        self.assertIn("historical stage unverified", shown["label"])
        self.assertIn("historical stage's bytes are unverified", shown["why"])
        axis.write_text('{"control_points": [[1, 0, 0], [1, 0, 10]]}')
        self.assertEqual(aplearn.suggest([rec], "PHercX")["settings"], {})


class TestLedger(Home):
    def test_a_folder_read_twice_is_one_record_and_its_latest_wins(self):
        p = plan()
        f = write_run(self.d / "home" / "r1", p, state(p, [("t00", 0, 0, "qa")]))
        aplearn.ingest(self.ctx, [f])
        st = state(p, [("t00", 0, 0, "qa")])
        (f / aplearn.REVIEW).write_text(json.dumps({"sid": "t00", "verdict": "accept"}) + "\n")
        (f / "state.json").write_text(json.dumps(st))
        with mock.patch.object(aplearn, "now", return_value="2099-01-01T00:00:00Z"):
            aplearn.ingest(self.ctx, [f])
        recs = self.ledger()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["traces"][0]["review"], "accept")
        self.assertEqual([u["y"] for u in aplearn.units(recs, "kept")], [1])
        self.assertEqual([u["y"] for u in aplearn.units(recs, "qa")], [0])

    def test_a_backfilled_run_gives_way_to_its_own_folder_and_bad_lines_are_skipped(self):
        path = aplearn.store_path(self.ctx.home)
        back = record("docs/evidence/s.json", "PHercX", {}, [0, 0], "2026-10-10T00:00:00Z")
        back.update(source="backfill", plan_digest="same")
        ran = record(str(self.d / "r"), "PHercX", {}, [1, 1], "2026-10-10T00:00:00Z")
        ran.update(plan_digest="same")
        other = dict(ran, v=aplearn.VERSION + 1, run="other")
        aplearn.append(path, [back])
        with open(path, "a") as fh:
            fh.write("not json\n[1, 2]\n")
        self.assertEqual([r["source"] for r in self.ledger()], ["backfill"])
        aplearn.append(path, [ran, other])
        self.assertEqual([(r["source"], r["run"]) for r in self.ledger()], [("run", str(self.d / "r"))])

    def test_runs_end_with_a_record_on_this_machine_but_not_on_modal_or_when_turned_off(self):
        p = plan()
        f = write_run(self.d / "home" / "r1", p, state(p, [("t00", 0, 0, "qa")]))
        self.ctx.env["KIT_AUTOPIPE_RUNNER"] = "modal"
        self.assertIn("Modal", aplearn.record_run(self.ctx, f)["skipped"])
        self.ctx.env.pop("KIT_AUTOPIPE_RUNNER")
        self.ctx.env[aplearn.ENV_OFF] = "0"
        self.assertIn("skipped", aplearn.record_run(self.ctx, f))
        self.assertEqual(self.ledger(), [])
        self.ctx.env.pop(aplearn.ENV_OFF)
        out = aplearn.record_run(self.ctx, f)
        self.assertEqual(out["traces"], 1)
        self.assertNotEqual(self.ledger()[0]["machine"]["key"], "modal")
        # a folder the Modal runner made says so, when it is read back here
        (f / "driver-cpu.json").write_text("{}")
        aplearn.ingest(self.ctx, [f])
        self.assertEqual(self.ledger()[0]["machine"]["key"], "modal")

    def test_backfill_reads_states_with_their_presets_and_refuses_a_digest_that_does_not_match(self):
        presets = self.d / "presets.py"
        arm = {"purpose": "benchmark", "trace": {"generations": 25, "repeats": 2}}
        p = {"version": autopipe.PLAN_VERSION, "settings": autopipe._merge(autopipe.DEFAULTS, arm),
             "resolved": {"sample": "PHercX", "volume": "V1"}}
        dg = autopipe.digest(p)
        presets.write_text("import modal\nPRESETS = " + repr({"two": {"sample": "PHercX", "arms": {
            "A": {"settings": arm, "digest": dg}}}}) + "\n")
        p["digest"] = dg
        st = state(p, [("t00-r0", 0, 0, "accepted"), ("t00-r1", 0, 1, "qa")])
        man = self.d / "m" / "backfill.json"
        man.parent.mkdir()
        (man.parent / "a.json").write_text(json.dumps(st))
        (man.parent / "b.json").write_text(json.dumps(dict(st, plan_digest="other")))
        man.write_text(json.dumps({"runs": [
            {"state": "a.json", "preset": "two", "arm": "A", "volume": "V1", "machine": {"key": "modal"}},
            {"state": "b.json", "preset": "two", "arm": "A", "volume": "V1"}, {"preset": "two"}]}))
        res = aplearn.backfill(self.ctx, man, presets)
        self.assertEqual([w["traces"] for w in res["written"]], [2])
        self.assertEqual(len(res["skipped"]), 2)
        self.assertIn("plan digest", res["skipped"][0]["why"])
        rec = self.ledger()[0]
        self.assertEqual((rec["source"], rec["settings_source"], rec["machine"]["key"]), ("backfill", "preset", "modal"))
        self.assertEqual(rec["planned"]["repeats"], 2)


class TestSuggest(unittest.TestCase):
    PLAN_ARM = {"trace": {"normal_grids": "required"}}      # the default trace length, 60 generations

    def test_repeats_are_the_fewest_that_reach_the_target(self):
        recs = [record("r1", "PHercX", self.PLAN_ARM, [0, 0, 1, 0, 0, 1], "2026-10-12T00:00:00Z",
                       seeds=[0, 0, 0, 1, 1, 1])]
        sug = aplearn.suggest(recs, "PHercX", self.PLAN_ARM)
        p = (1 + 2) / (2 + 6)
        a, b = 2 * p + 2, 2 * (1 - p) + 4
        want = next(k for k in range(1, 11) if aplearn.p_at_least_one(a, b, k) >= 0.8)
        self.assertEqual(sug["settings"], {"trace": {"repeats": want}})
        self.assertAlmostEqual(aplearn.p_at_least_one(a, b, 1), a / (a + b))
        self.assertEqual(sug["changes"][0]["label"], "Model output")
        self.assertEqual(sug["changes"][0]["evidence"]["seeds_traced_twice_or_more"], {"mixed": 2, "unanimous": 0})
        # the same ledger gives the same suggestion, digest and all
        self.assertEqual(aplearn.suggest(recs, "PHercX", self.PLAN_ARM), sug)
        # a higher target needs more repeats, never fewer
        more = aplearn.suggest(recs, "PHercX", self.PLAN_ARM, target=0.9)["settings"]["trace"]["repeats"]
        self.assertGreaterEqual(more, want)

    def test_a_tracer_that_repeats_itself_gets_one_repeat(self):
        arm = {"trace": {"generations": 25, "repeats": 3}}
        recs = [record("r1", "PHercX", arm, [1, 1, 0, 0, 1, 1], "2026-10-12T00:00:00Z", seeds=[0, 0, 1, 1, 2, 2])]
        sug = aplearn.suggest(recs, "PHercX", {"trace": {"generations": 25}})
        self.assertEqual(sug["settings"], {})        # one repeat is the default
        self.assertIn("deterministic", [k for k in sug["kept"] if k["key"] == "trace.repeats"][0]["why"])
        sug = aplearn.suggest(recs, "PHercX", {"trace": {"generations": 25, "repeats": 3}})
        why = [k for k in sug["kept"] if k["key"] == "trace.repeats"][0]["why"]
        self.assertTrue(why.startswith("given in the settings (3)") and "deterministic" in why, why)

    def test_the_callers_own_settings_always_win(self):
        recs = [record("r1", "PHercX", self.PLAN_ARM, [0, 0, 1, 0, 0, 1], "2026-10-12T00:00:00Z")]
        given = {"trace": {"normal_grids": "required", "repeats": 2}}
        sug = aplearn.suggest(recs, "PHercX", given)
        self.assertEqual(sug["settings"], {})
        self.assertIn("given in the settings", [k for k in sug["kept"] if k["key"] == "trace.repeats"][0]["why"])

    def test_a_trace_length_changes_only_past_the_gate(self):
        good = {"trace": {"generations": 90, "normal_grids": "required"}}
        plan_runs = [record("p1", "PHercX", self.PLAN_ARM, [0, 0, 0, 0, 0], "2026-10-12T00:00:00Z")]
        few = [record("g1", "PHercX", good, [1, 1, 1, 1], "2026-10-12T01:00:00Z")]
        sug = aplearn.suggest(plan_runs + few, "PHercX", self.PLAN_ARM)
        self.assertNotIn("generations", sug["settings"].get("trace", {}))
        self.assertIn("the gate needs", [k for k in sug["kept"] if k["key"] == "trace.generations"][0]["why"])
        enough = [record("g1", "PHercX", good, [1] * 9 + [0], "2026-10-12T01:00:00Z")]
        sug = aplearn.suggest(plan_runs + enough, "PHercX", self.PLAN_ARM)
        self.assertEqual(sug["settings"]["trace"]["generations"], 90)
        change = [c for c in sug["changes"] if c["key"] == "trace.generations"][0]
        self.assertEqual(change["was"], 60)
        # a trace length the caller named is kept
        named = aplearn.suggest(plan_runs + enough, "PHercX", {"trace": {"normal_grids": "required",
                                                                         "generations": 60}})
        self.assertNotIn("generations", named["settings"].get("trace", {}))
        self.assertEqual(sug["warnings"], [])
        # an arm differing in more than the trace length is never a candidate
        other = {"trace": {"generations": 90, "normal_grids": "off"}}
        sug = aplearn.suggest(plan_runs + [record("o1", "PHercX", other, [1] * 10, "2026-10-12T01:00:00Z")],
                              "PHercX", self.PLAN_ARM)
        self.assertNotIn("generations", sug["settings"].get("trace", {}))

    def test_an_arm_known_to_fail_is_flagged_not_repeated_into(self):
        recs = [record("r1", "PHercX", self.PLAN_ARM, [0] * 8, "2026-10-12T00:00:00Z")]
        sug = aplearn.suggest(recs, "PHercX", self.PLAN_ARM)
        self.assertEqual(len(sug["warnings"]), 1)
        self.assertIn("rather than adding repeats", sug["warnings"][0]["why"])
        self.assertEqual(sug["settings"], {})            # repeats stay at 1, never the maximum
        self.assertIn("not the fix", [k for k in sug["kept"] if k["key"] == "trace.repeats"][0]["why"])

    def test_repeats_never_rise_when_no_number_reaches_the_target_or_the_arm_is_flagged(self):
        # 0 of 5: too few traces for the warning, and even 10 repeats fall short of 0.8
        recs = [record("r1", "PHercX", self.PLAN_ARM, [0] * 5, "2026-10-12T00:00:00Z")]
        sug = aplearn.suggest(recs, "PHercX", self.PLAN_ARM)
        self.assertEqual((sug["warnings"], sug["settings"]), ([], {}))
        why = [k for k in sug["kept"] if k["key"] == "trace.repeats"][0]["why"]
        self.assertTrue(why.startswith("even 10 repeats give a chance of only"), why)
        # 1 of 14: flagged as failing, and 0.3 is reachable with a few repeats, but they are not added
        recs = [record("r1", "PHercX", self.PLAN_ARM, [1] + [0] * 13, "2026-10-12T00:00:00Z")]
        sug = aplearn.suggest(recs, "PHercX", self.PLAN_ARM, target=0.3)
        self.assertEqual(len(sug["warnings"]), 1)
        self.assertEqual(sug["settings"], {})
        self.assertIn("flagged as failing", [k for k in sug["kept"] if k["key"] == "trace.repeats"][0]["why"])
        # a flagged arm may still drop repeats it does not need
        down = aplearn.suggest(recs, "PHercX", {**self.PLAN_ARM, "trace": {"normal_grids": "required"}}, target=0.01)
        self.assertEqual(down["settings"], {})

    def test_a_published_segment_and_an_empty_ledger_change_nothing(self):
        self.assertEqual(aplearn.suggest([], "PHercX", {"segment": "0841-w00"})["settings"], {})
        sug = aplearn.suggest([], "PHercX", {})
        self.assertEqual(sug["settings"], {})
        self.assertIn("no trace of this arm", [k["why"] for k in sug["kept"]][0])

    def test_an_earlier_axis_is_reused_only_when_it_is_the_same_estimate_of_the_same_scan(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "umbilicus.json"
            f.write_text('{"control_points": []}')
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            u = autopipe.DEFAULTS["umbilicus"]
            um = {"source": "estimated", "asked": "auto", "path": str(f), "sha256": sha, "seconds": 50.0, "kept": 30,
                  "settings": aplearn.digest({k: v for k, v in u.items() if k not in aplearn.UMB_SKIP})[:16]}
            rec = record("r1", "PHercX", {}, [], "2026-10-12T00:00:00Z", extra={"umbilicus": um})
            sug = aplearn.suggest([rec], "PHercX", {})
            self.assertEqual(sug["settings"], {"umbilicus": {"source": str(f)}})   # the scan is never changed
            # Previously written ledgers have no hash-source field: preserve their file check while clearly
            # distinguishing it from a stage receipt that binds the bytes the historical run actually used.
            self.assertEqual(sug["changes"][0]["evidence"]["sha256_source"], "legacy_file_observation")
            self.assertIn("historical stage unverified", sug["changes"][0]["label"])
            self.assertEqual(aplearn.took_axis(sug), True)
            # the catalog has an axis now: a plan asking auto takes it
            self.assertEqual(aplearn.suggest([rec], "PHercX", {}, axis=False)["settings"], {})
            # an axis from a prediction's own grids or from one box of it, a plan naming an estimator: no reuse
            for extra in ({"box_axis": True}, {"axis_grids": "s3://bucket/grids.zarr"}):
                other = dict(rec, umbilicus=dict(um, **extra))
                self.assertEqual(aplearn.suggest([other], "PHercX", {})["settings"], {}, extra)
            est = aplearn.suggest([rec], "PHercX", {"umbilicus": {"estimator": "normals"}})
            self.assertEqual(est["settings"], {})
            self.assertIn("estimator", [k for k in est["kept"] if k["key"] == "umbilicus.source"][0]["why"])
            # plan --learned plans again without the axis when the plan's scan is another one, or the catalog has it
            self.assertIsNone(aplearn.axis_conflict(sug, {"resolved": {"volume": "V1"}}))
            self.assertIn("scan V1", aplearn.axis_conflict(sug, {"resolved": {"volume": "V9"}}))
            self.assertIn("catalog", aplearn.axis_conflict(sug, {"resolved": {"volume": "V1",
                                                                              "catalog_umbilicus": "u"}}))
            # another scan, other estimate settings, an estimate a plan forced, a changed file: no reuse
            self.assertEqual(aplearn.suggest([rec], "PHercX", {"volume": "V2"})["settings"], {})
            self.assertEqual(aplearn.suggest([rec], "PHercX", {"umbilicus": {"every": 250}})["settings"], {})
            forced = dict(rec, umbilicus=dict(um, asked="estimate"))
            self.assertEqual(aplearn.suggest([forced], "PHercX", {})["settings"], {})
            self.assertEqual(aplearn.suggest([rec], "PHercY", {})["settings"], {})
            f.write_text('{"control_points": [[1, 2, 3]]}')
            self.assertEqual(aplearn.suggest([rec], "PHercX", {})["settings"], {})

    def test_a_suggestion_writes_only_learnable_settings(self):
        for bad in ({"qa": {"max_selfcross": 5}}, {"flatten": {"max_p95_stretch": 1.0}}, {"seeds": {"seed": 3}},
                    {"ink": {"models": ["x"]}}, {"trace": {"timeout": 9}}):
            with self.assertRaises(aplearn.LearnError, msg=bad):
                aplearn.check_overlay(bad)
        self.assertEqual(aplearn.check_overlay({"trace": {"repeats": 2}}), {"trace": {"repeats": 2}})
        for fixed in aplearn.FIXED:
            self.assertNotIn(fixed, aplearn.LEARNABLE)
        with self.assertRaises(aplearn.LearnError):
            aplearn.suggest([], "PHercX", {}, target=1.5)


class TestEstimate(unittest.TestCase):
    def runs(self, machine, per, n=3, sample="PHercX"):
        recs = [record(f"{machine}-{i}", sample, {}, [1, 0], f"2026-10-12T0{i}:00:00Z", machine=machine,
                       trace_per=per) for i in range(n)]
        for r in recs:
            for st in autopipe.STAGES:
                r["stages"].setdefault(st, {"status": "done", "seconds": 1.0})
        return recs

    def test_placement_follows_the_ten_minute_rule_on_this_machine(self):
        e = aplearn.estimate(self.runs("mac", 30.0), "PHercX", {"seeds": {"count": 2}}, machine_key="mac")
        self.assertEqual(e["stages"]["trace"]["seconds"], 60.0)
        self.assertEqual(e["placement"]["where"], "here")
        # ink is GPU work, not counted; score never runs on a plan with no labels (amendment (e))
        self.assertEqual(e["cpu_seconds_here"], 60.0 + 8)
        self.assertIn("no labels", e["stages"]["score"]["skipped"])
        self.assertEqual(e["stages"]["trace"]["basis"], "this machine, this scroll, 60 generations")
        e = aplearn.estimate(self.runs("mac", 600.0), "PHercX", {"seeds": {"count": 4}}, machine_key="mac")
        self.assertEqual(e["placement"]["where"], "modal")
        e = aplearn.estimate(self.runs("modal", 30.0), "PHercX", {"seeds": {"count": 2}}, machine_key="mac")
        self.assertEqual(e["placement"]["where"], "unknown")
        self.assertIn("other machines", e["placement"]["why"])
        part = self.runs("mac", 30.0)
        for r in part:
            r["stages"].pop("qa")
        e = aplearn.estimate(part, "PHercX", {"seeds": {"count": 2}}, machine_key="mac")
        self.assertEqual(e["placement"]["where"], "unknown")
        self.assertIn("qa never", e["placement"]["why"])
        e = aplearn.estimate(self.runs("modal", 30.0), "PHercX", {"seeds": {"count": 2}}, machine_key="modal")
        self.assertIsNone(e["placement"]["where"])
        self.assertIn("Modal", e["placement"]["ink"])

    def test_a_stage_skipped_on_every_earlier_run_of_the_scroll_is_expected_skipped(self):
        recs = self.runs("mac", 30.0)
        for r in recs:
            r["stages"]["bench"] = {"status": "skipped", "seconds": 0.0}
        e = aplearn.estimate(recs, "PHercX", {}, machine_key="mac")
        self.assertIn("skipped on every earlier run", e["stages"]["bench"]["skipped"])
        # only bench, which depends on the scan: stages this plan runs are never skipped from history
        segs = self.runs("mac", 30.0)
        for r in segs:
            for st in ("seeds", "trace", "ink", "score"):
                r["stages"][st] = {"status": "skipped", "seconds": 0.0}
        e = aplearn.estimate(segs + self.runs("mac", 1500.0, sample="PHercY"), "PHercX", {"seeds": {"count": 4}},
                             machine_key="mac")
        self.assertEqual(e["stages"]["trace"]["seconds"], 6000.0)
        self.assertNotIn("skipped", e["stages"]["ink"])
        self.assertIn("Modal", e["placement"]["ink"])
        self.assertEqual(e["stages"]["flatten"]["seconds"], 1.0)
        self.assertIn("ink.where is skip", aplearn.estimate(recs, "PHercX", {"ink": {"where": "skip"}},
                                                             machine_key="mac")["stages"]["ink"]["skipped"])


class TestReviewFixes(Home):
    """The findings of three code reviews of the learner (16 Oct 2026), one test each; prereg amendment (d)."""

    def test_a_resumed_development_run_stays_development_and_units_are_placed_when_known(self):
        p = plan()
        st = state(p, [("t00", 0, 0, "accepted"), ("t01", 1, 0, "qa")], at="2026-10-12T01:00:00Z")
        st["stages"]["render"] = {"status": "done", "at": "2026-10-13T01:00:00Z", "seconds": 40.0, "record": {}}
        st["stages"]["report"].update(at="2026-10-19T08:00:00Z")      # every resume writes the report again
        rec, _ = aplearn.harvest(write_run(self.d / "run", p, st))
        self.assertEqual((rec["started"], rec["decided"], rec["ended"]),
                         ("2026-10-12T01:00:00Z", "2026-10-12T01:00:00Z", "2026-10-13T01:00:00Z"))
        self.assertEqual({u["at"] for u in aplearn.units([rec])}, {"2026-10-12T01:00:00Z"})
        self.assertEqual({u["stage"]: u["at"] for u in aplearn.time_units([rec])}["render"], "2026-10-13T01:00:00Z")
        res = aplearn.evaluate([rec], permutations=9)
        self.assertEqual(res["q1_trace_acceptance"]["fresh"]["units"], 0)
        self.assertEqual(res["q2_stage_time"]["fresh"]["units"], 0)
        # a run whose first stage ended after the cutoff is fresh
        late = aplearn.harvest(write_run(self.d / "late", p, state(p, [("t00", 0, 0, "accepted")])))[0]
        self.assertGreaterEqual(late["started"], aplearn.CUTOFF)
        self.assertEqual(aplearn.status([rec, late])["fresh_runs"], 1)

    def test_one_run_under_two_paths_counts_once_and_a_second_run_of_the_plan_counts_again(self):
        p = plan()
        st = state(p, [("t00", 0, 0, "accepted"), ("t01", 1, 0, "qa")])
        a = write_run(self.d / "home" / "a", p, st)
        b = write_run(self.d / "home" / "b", p, st)          # a copy
        aplearn.ingest(self.ctx, [a, b])
        recs = self.ledger()
        self.assertEqual(len(recs), 1)
        self.assertEqual(len(aplearn.units(recs)), 2)
        c = write_run(self.d / "home" / "c", p, state(p, [("t00", 0, 0, "qa")], at="2026-10-21T01:00:00Z"))
        aplearn.ingest(self.ctx, [c])
        self.assertEqual(len(self.ledger()), 2)
        # a backfilled record gives way only to the same run, not to another run of the same plan
        back = dict(self.ledger()[0], source="backfill", run="docs/evidence/x/state.json", started="2026-10-01T00:00:00Z")
        aplearn.append(aplearn.store_path(self.ctx.home), [back])
        self.assertEqual(len(self.ledger()), 3)

    def test_each_stage_keeps_the_machine_it_ran_on(self):
        p = plan()
        f = write_run(self.d / "home" / "r1", p, state(p, [("t00", 0, 0, "accepted")], ran=["t00"]))
        (f / "driver-cpu.json").write_text("{}")
        aplearn.ingest(self.ctx, [f])
        (f / "driver-cpu.json").unlink()
        aplearn.review(self.ctx, f, "t00", "reject")          # read again on this machine
        recs = self.ledger()
        self.assertEqual({u["machine"] for u in aplearn.time_units(recs)}, {"modal"})
        self.assertEqual(recs[0]["traces"][0]["review"], "reject")
        # a stage run again here takes this machine
        st = json.loads((f / "state.json").read_text())
        st["stages"]["qa"].update(at="2026-10-21T00:00:00Z", seconds=33.0)
        (f / "state.json").write_text(json.dumps(st))
        with mock.patch.object(aplearn, "now", return_value="2099-01-01T00:00:00Z"):
            aplearn.ingest(self.ctx, [f])
        here = aplearn.machine(self.ctx.env)["key"]
        got = {u["stage"]: u["machine"] for u in aplearn.time_units(self.ledger())}
        self.assertEqual((got["qa"], got["trace"]), (here, "modal"))
        # inside any Modal container nothing is written, with or without the runner's own flag
        self.assertTrue(aplearn.on_modal({"MODAL_TASK_ID": "ta-1"}))
        self.ctx.env["MODAL_TASK_ID"] = "ta-1"
        self.assertIn("Modal", aplearn.record_run(self.ctx, f)["skipped"])
        self.assertEqual(aplearn.machine({"MODAL_TASK_ID": "ta-1"})["key"], "modal")

    def test_a_scroll_reserved_later_drops_out_and_an_unreadable_reserve_file_stops_the_learner(self):
        p = plan(sample="PHercLater")
        f = write_run(self.d / "home" / "r1", p, state(p, [("t00", 0, 0, "accepted")]))
        aplearn.ingest(self.ctx, [f])
        self.assertEqual(len(aplearn.units(self.ledger())), 1)
        reserve = self.d / "reserved.json"
        reserve.write_text(json.dumps([{"sample": "PHercLater", "segment": "w1", "why": "held out later"}]))
        with mock.patch.object(autopipe, "RESERVED_FILE", reserve):
            self.assertEqual(aplearn.units(self.ledger()), [])
            self.assertEqual(aplearn.status(self.ledger())["used"], 0)
            self.assertEqual(aplearn.suggest(self.ledger(), "PHercLater", {})["ledger"]["units"], 0)
            reserve.write_text('[{"sample": "PHercLater",}]')
            for call in (lambda: aplearn.usable(self.ledger()), lambda: aplearn.ingest(self.ctx, [f]),
                         lambda: aplearn.harvest(f)):
                with self.assertRaises(aplearn.LearnError):
                    call()

    def test_per_trace_counts_every_trace_the_tracer_ran(self):
        for p in (plan(version=1), plan(resolved={"winding_bench": {"rule_digest": "x"}})):
            st = state(p, [("t00", 0, 0, "qa"), ("t01", 1, 0, "qa"), ("t02", 2, 0, "accepted")], trace_seconds=900.0)
            rec, _ = aplearn.harvest(write_run(self.d / str(p["version"]) / p["digest"][:8], p, st))
            self.assertEqual({t["outcome"] for t in rec["traces"]}, {"void"})
            self.assertEqual((rec["stages"]["trace"]["per_trace"], rec["stages"]["trace"]["traces"]), (300.0, 3))

    def test_stage_times_are_compared_unrounded(self):
        hist = [{"stage": "qa", "machine": "m", "sample": "S", "seconds": x, "generations": None} for x in (0.3, 0.4)]
        got = aplearn.predict_seconds(hist, "qa", "m", "S")
        self.assertEqual((got["exact"], got["basis"]), (statistics.median([0.3, 0.4]), "this machine, this scroll"))
        tu = [dict(u, run=f"r{i}", at=f"2026-10-1{i}", started=f"2026-10-1{i}") for i, u in enumerate(hist)]
        tu.append(dict(hist[0], run="r9", at="2026-10-19", started="2026-10-19", seconds=0.35))
        rows = aplearn.prequential_q2(tu)
        self.assertEqual(rows[-1][1], statistics.median([0.3, 0.4]))
        # with no machine or scroll given, those levels are passed over
        self.assertEqual(aplearn.predict_seconds(hist, "qa")["basis"], "all runs")
        tr = [dict(hist[0], stage="trace", generations=90)]
        self.assertIn("other trace lengths", aplearn.predict_seconds(tr, "trace", "m", "S", 60)["basis"])

    def test_bad_input_never_stops_every_command(self):
        p = plan()
        good = write_run(self.d / "home" / "good", p, state(p, [("t00", 0, 0, "accepted")]))
        bad = write_run(self.d / "home" / "bad", p, dict(state(p, [("t00", 0, 0, "accepted")]), surfaces=["t00"]))
        res = aplearn.ingest(self.ctx, [bad, good])
        self.assertEqual([w["run"] for w in res["written"]], [str(good.resolve())])
        self.assertIn("unreadable", res["skipped"][0]["why"])
        path = aplearn.store_path(self.ctx.home)
        with open(path, "ab") as fh:
            fh.write(b'{"v": 1, "kind": "run", "source": "run", "run": "x", "traces": 5}\n\xff\xfe not text\n')
        self.assertEqual(len(self.ledger()), 1)
        self.assertEqual(aplearn.status(self.ledger())["used"], 1)
        for n in (0, -5, True, 1.5):
            with self.assertRaises(aplearn.LearnError, msg=n):
                aplearn.evaluate(self.ledger(), permutations=n)
        for bad_learn in ({"do": ["status"]}, {"do": "ingest", "folders": False}, "status"):
            with self.assertRaises(vc3d_agent.ToolError, msg=bad_learn):
                aplearn.tool_call(self.ctx, vc3d_agent, {"learn": bad_learn})
        self.assertIn("backfill", aplearn.TOOL_TAKES)

    def test_target_runs_are_found_by_their_layout_and_the_sampler_window_is_part_of_the_arm(self):
        self.assertTrue(aplearn.in_experiment(self.d / "experiments" / "e1" / "autopipe" / "r"))
        self.assertFalse(aplearn.in_experiment(self.d / "experiments" / "Scrolls" / "work" / "autopipe" / "r"))
        a = aplearn.trace_arm(settings(seeds={"z_range": [0, 500]}))[1]
        self.assertNotEqual(a, aplearn.trace_arm(settings(seeds={"z_range": [500, 900]}))[1])

    def test_backfill_outside_the_source_says_what_to_do(self):
        from kit import kithome
        with mock.patch.object(kithome, "source_file", side_effect=kithome.MissingSource("absent")):
            with self.assertRaises(aplearn.LearnError) as err:
                aplearn.backfill(self.ctx)
        self.assertIn("presets", str(err.exception))      # without them no manifest helps (review item 12)


class TestReviewFixesE(Home):
    """The findings of the independent check of 81007a2f (16 Oct 2026), one test each; prereg amendment (e)."""

    def test_a_modal_folder_reviewed_before_any_ingest_keeps_modals_key(self):
        p = plan()
        f = write_run(self.d / "home" / "r1", p, state(p, [("t00", 0, 0, "accepted")]))
        (f / "driver-cpu.json").write_text("{}")
        aplearn.review(self.ctx, f, "t00", "accept")             # the first read of this folder is a review here
        self.assertEqual({u["machine"] for u in aplearn.time_units(self.ledger())}, {"modal"})
        self.assertEqual(self.ledger()[0]["machine"]["key"], "modal")

    def test_a_plan_with_no_labels_expects_no_score_stage(self):
        recs = [record(f"r{i}", "PHercX", {}, [1], f"2026-10-1{i}T00:00:00Z",
                       extra={"stages": {"score": {"status": "done", "seconds": 30.0, "at": "x", "machine": "m1"}}})
                for i in range(3)]
        rows = aplearn.estimate(recs, "PHercX", {}, "m1")["stages"]
        self.assertIn("no labels", rows["score"]["skipped"])
        # a published labeled segment, or labels carried by score.transfer, are scored
        seg = sorted(autopipe.BENCHMARKS)[0]
        self.assertIsNone(aplearn.planned_stages(settings(segment=seg))["score"])
        self.assertIsNone(aplearn.planned_stages(settings(score={"transfer": {"segments": [seg]}}))["score"])
        self.assertIn("target", aplearn.planned_stages(settings(purpose="target",
                                                                score={"transfer": {"segments": [seg]}}))["score"])

    def test_per_trace_counts_the_traces_the_tracer_ran_and_no_other(self):
        p = plan(version=1)        # every trace void, so outcomes cannot stand in for "ran"
        st = state(p, [("t00", 0, 0, "qa"), ("t01", 1, 0, "tracer"), ("t02", 2, 0, "seed"), ("t03", 3, 0, "lost"),
                       ("t04", 4, 0, "tool")], trace_seconds=1000.0)
        st["trace_failures"]["t04"] = {"kind": "infrastructure", "reason": "the trace tool could not run: no CT"}
        rec, _ = aplearn.harvest(write_run(self.d / "run", p, st))
        self.assertEqual({t["outcome"] for t in rec["traces"]}, {"void"})
        tr = rec["stages"]["trace"]
        self.assertEqual(tr["traces"], 2)                      # t00 (qa) and t01 (the tracer exited 1)
        self.assertEqual(tr["per_trace"], 1000.0 / 2)

    def test_a_resumed_trace_stage_divides_by_the_traces_it_ran_itself(self):
        p = plan()
        st = state(p, [("t00", 0, 0, "accepted"), ("t01", 1, 0, "qa"), ("t02", 2, 0, "accepted")], trace_seconds=300.0)
        st["stages"]["trace"]["record"] = {"surfaces": ["t00", "t01", "t02"], "failed": [], "ran": ["t02"]}
        tr = aplearn.harvest(write_run(self.d / "run", p, st))[0]["stages"]["trace"]
        self.assertEqual((tr["traces"], tr["per_trace"]), (1, 300.0))

    def test_trace_units_are_stored_unrounded(self):
        p = plan()
        st = state(p, [("t00", 0, 0, "accepted"), ("t01", 1, 0, "qa"), ("t02", 2, 0, "accepted")], trace_seconds=1000.0)
        tr = aplearn.harvest(write_run(self.d / "run", p, st))[0]["stages"]["trace"]
        self.assertEqual(tr["per_trace"], 1000.0 / 3)
        self.assertNotEqual(tr["per_trace"], round(1000.0 / 3, 1))

    def test_records_from_before_scope_and_stage_machines_are_read_as_they_were_written(self):
        p = plan(sample="PHercOld", segment=None)
        f = write_run(self.d / "home" / "r1", p, state(p, [("t00", 0, 0, "accepted")]))
        old, _ = aplearn.harvest(f, machine_info={"key": "modal", "runner": "modal"})
        old.pop("scope")
        for e in old["stages"].values():
            e.pop("machine", None)
        old["planned"]["segment"] = "wOld"
        aplearn.append(aplearn.store_path(self.ctx.home), [old])
        # read again here, unchanged: its stages keep the machine the record named for the whole run
        with mock.patch.object(aplearn, "now", return_value="2099-01-01T00:00:00Z"):
            aplearn.review(self.ctx, f, "t00", "accept")
        self.assertEqual({u["machine"] for u in aplearn.time_units(self.ledger())}, {"modal"})
        # its segment made a report surface later: the record without scope drops out through planned.segment
        self.assertIsNone(aplearn.excluded_now(old, set()))
        with mock.patch.dict(autopipe.REPORT_ONLY, {"wOld": "a report surface since"}):
            self.assertIn("wOld", aplearn.excluded_now(old, set()))


class TestSmallFixesE(Home):
    """Review items 7, 10 and 12 of the independent check of 81007a2f."""

    def test_a_verdict_on_either_copy_of_one_run_read_in_one_call_counts(self):
        p = plan()
        st = state(p, [("t00", 0, 0, "accepted")])
        a = write_run(self.d / "home" / "a", p, st)
        b = write_run(self.d / "home" / "b", p, st)
        aplearn.ingest(self.ctx, [b])               # the unreviewed copy is on record first
        aplearn.review(self.ctx, a, "t00", "reject")
        with mock.patch.object(aplearn, "now", return_value="2099-01-01T00:00:00Z"):
            aplearn.ingest(self.ctx, [b, a])      # two copies, one read, equal ranks: the first on record is kept
        recs = self.ledger()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["traces"][0]["review"], "reject")

    def test_a_hand_edited_nested_value_is_skipped_not_a_crash(self):
        p = plan()
        f = write_run(self.d / "home" / "r1", p, state(p, [("t00", 0, 0, "accepted")]))
        aplearn.ingest(self.ctx, [f])
        good = self.ledger()[0]
        path = aplearn.store_path(self.ctx.home)
        for k, bad in (("scope", {"segment": ["w1"], "transfer": []}), ("stages", {"qa": {"at": 5, "status": "done"}}),
                       ("stages", {"qa": {"status": "done", "seconds": "1"}}), ("traces", [{"outcome": "x", "sid": 3}]),
                       ("planned", {"segment": 4})):
            aplearn.append(path, [dict(good, run=f"edited-{k}", plan_digest=None, **{k: bad})])
        recs = self.ledger()
        self.assertEqual([r["run"] for r in recs], [good["run"]])
        aplearn.status(recs)
        aplearn.evaluate(recs, permutations=9)

    def test_backfill_without_the_presets_says_it_needs_the_private_source(self):
        # a manifest named that is not there: the presets are the first thing missing, so the error names them, not
        # the manifest. On 81007a2f the manifest was read first and this says "not a backfill manifest" (finding 7
        # of the check of 5190e52e: with a readable manifest, as this test had it, both orders name the presets)
        from kit import kithome
        man = self.d / "absent" / "man.json"
        with mock.patch.object(kithome, "source_file", side_effect=kithome.MissingSource("absent")):
            with self.assertRaises(aplearn.LearnError) as err:
                aplearn.backfill(self.ctx, manifest=man)
        self.assertIn("presets", str(err.exception))
        self.assertNotIn("not a backfill manifest", str(err.exception))


class TestReviewFixesF(Home):
    """The findings of the independent check of 5190e52e (16 Oct 2026); prereg amendment (f). Each fails on 5190e52e."""

    def test_the_runner_marker_alone_reads_as_modal(self):
        # findings 4 and 8: a required arm that failed leaves runner-modal.json and no driver marker
        p = plan()
        f = write_run(self.d / "home" / "r1", p, state(p, [("t00", 0, 0, "accepted")], ran=["t00"]))
        self.assertEqual(aplearn._machine_of(f, {"key": "laptop"})["key"], "laptop")
        (f / "runner-modal.json").write_text("{}")
        self.assertEqual(aplearn._machine_of(f, {"key": "laptop"})["key"], "modal")
        aplearn.ingest(self.ctx, [f])
        self.assertEqual({u["machine"] for u in aplearn.time_units(self.ledger())}, {"modal"})

    def test_the_runner_marker_wins_over_an_old_records_whole_run_machine(self):
        # review item 3: a record from before stages named their machine, written by `learn review` here for a Modal
        # folder (e474a362 tagged it with the reading machine); read again, the folder's marker says Modal
        p = plan()
        f = write_run(self.d / "home" / "r1", p, state(p, [("t00", 0, 0, "accepted")], ran=["t00"]))
        old, _ = aplearn.harvest(f, machine_info={"key": "Darwin-arm64-10cpu", "runner": "local"})
        aplearn.append(aplearn.store_path(self.ctx.home), [old])
        (f / "driver-gpu.json").write_text("{}")
        with mock.patch.object(aplearn, "now", return_value="2099-01-01T00:00:00Z"):
            aplearn.ingest(self.ctx, [f])
        self.assertEqual({u["machine"] for u in aplearn.time_units(self.ledger())}, {"modal"})
        # without a marker the old record's name for the whole run stands (amendment (e))
        (f / "driver-gpu.json").unlink()
        g = write_run(self.d / "home" / "r2", p, state(p, [("t00", 0, 0, "accepted")], at="2026-10-21T01:00:00Z",
                                                       ran=["t00"]))
        old2, _ = aplearn.harvest(g, machine_info={"key": "modal", "runner": "modal"})
        aplearn.append(aplearn.store_path(self.ctx.home), [old2])
        with mock.patch.object(aplearn, "now", return_value="2099-01-01T00:00:01Z"):
            aplearn.ingest(self.ctx, [g])
        self.assertEqual({u["machine"] for u in aplearn.time_units(self.ledger()) if u["run"] == str(g.resolve())},
                         {"modal"})

    def test_a_fresh_trace_stage_that_names_no_ran_gives_no_unit_and_is_counted_apart(self):
        # review item 5: a fresh run made by a kit without "ran" (an older branch or Modal image), whose resumed trace
        # stage grew only t02 in its last 300 s attempt; the count of (d) would give 100 s a trace
        p = plan()
        traces = [("t00", 0, 0, "accepted"), ("t01", 1, 0, "qa"), ("t02", 2, 0, "accepted")]
        st = state(p, traces, trace_seconds=300.0)
        st["stages"]["trace"]["record"] = {"surfaces": ["t00", "t01", "t02"], "failed": []}
        fresh = aplearn.harvest(write_run(self.d / "fresh", p, st))[0]
        self.assertGreaterEqual(fresh["started"], aplearn.CUTOFF)
        self.assertNotIn("trace", {u["stage"] for u in aplearn.time_units([fresh])})
        q2 = aplearn.evaluate([fresh], permutations=9)["q2_stage_time"]["fresh"]
        self.assertEqual(q2["trace_stages_without_ran"], 1)
        # with the list it is a unit, divided by the traces this attempt ran
        st["stages"]["trace"]["record"]["ran"] = ["t02"]
        listed = aplearn.harvest(write_run(self.d / "listed", p, st))[0]
        self.assertEqual([u["seconds"] for u in aplearn.time_units([listed]) if u["stage"] == "trace"], [300.0])
        self.assertEqual(aplearn.evaluate([listed], permutations=9)["q2_stage_time"]["fresh"]
                         ["trace_stages_without_ran"], 0)
        # development data keep the count of (d), and an estimate (not a verdict) keeps the unit
        dev = state(p, traces, at="2026-10-12T01:00:00Z", trace_seconds=300.0)
        dev_rec = aplearn.harvest(write_run(self.d / "dev", p, dev))[0]
        self.assertEqual([u["seconds"] for u in aplearn.time_units([dev_rec]) if u["stage"] == "trace"], [100.0])
        self.assertIn("trace", {u["stage"] for u in aplearn.time_units([fresh], positive=False)})

    def test_the_latest_verdict_wins_by_its_own_time_when_two_copies_are_read_a_second_apart(self):
        # review item 2: one ingest reads the reviewed copy at 10:00:00 and the other at 10:00:01
        p = plan()
        st = state(p, [("t00", 0, 0, "accepted")])
        a = write_run(self.d / "home" / "a", p, st)
        b = write_run(self.d / "home" / "b", p, st)
        (a / aplearn.REVIEW).write_text(json.dumps({"v": 1, "at": "2026-10-20T09:00:00Z", "sid": "t00",
                                                    "verdict": "reject"}) + "\n")
        tick = iter(range(60))
        with mock.patch.object(aplearn, "now", side_effect=lambda: f"2026-10-20T10:00:{next(tick):02d}Z"):
            aplearn.ingest(self.ctx, [a, b])
        recs = self.ledger()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["traces"][0].get("review"), "reject")
        self.assertEqual([u["y"] for u in aplearn.units(recs, "kept")], [0])

    def test_a_verdict_cleared_on_one_copy_never_comes_back_from_another(self):
        p = plan()
        st = state(p, [("t00", 0, 0, "accepted")])
        a = write_run(self.d / "home" / "a", p, st)
        tick = iter(range(60))
        with mock.patch.object(aplearn, "now", side_effect=lambda: f"2026-10-20T10:00:{next(tick):02d}Z"):
            aplearn.review(self.ctx, a, "t00", "reject")
            b = write_run(self.d / "home" / "b", p, st)
            (b / aplearn.REVIEW).write_text((a / aplearn.REVIEW).read_text())     # a copy made before the clear
            aplearn.review(self.ctx, a, "t00", "clear")
            aplearn.ingest(self.ctx, [b])                                          # the copy is read last
        recs = self.ledger()
        self.assertEqual(len(recs), 1)
        self.assertIsNone(recs[0]["traces"][0].get("review"))
        self.assertEqual([u["y"] for u in aplearn.units(recs, "kept")], [1])       # qa's own verdict again


class TestRunRecordsWhatItRan(unittest.TestCase):
    def setUp(self):
        self.h = TA.TestRun("test_end_to_end_to_the_modal_handoff")
        self.h.setUp()
        self.addCleanup(self.h.tearDown)

    def test_the_trace_stage_names_the_traces_the_tracer_ran(self):
        st, out = self.h.run_plan(self.h.plan(), until="trace")
        rec = st["stages"]["trace"]["record"]
        self.assertEqual(sorted(rec["ran"]), sorted(rec["surfaces"]))
        self.assertTrue(rec["ran"])

    def test_ran_holds_only_what_this_attempts_tracer_ran(self):
        # review item 6 of the check of 5190e52e: a resumed attempt with a surface already in state, a seed refusal,
        # a trace tool that could not run and a tracer that exited 1; only this attempt's tracer runs count
        plan = self.h.plan(trace={**autopipe.DEFAULTS["trace"], "repeats": 3})
        real = autopipe.Run.trace_call

        class Stop(BaseException):
            """The process stops in the middle of the trace stage (a resume follows)."""

        def first(run, sid, args):
            if sid == "t00-r1":
                raise Stop()
            return real(run, sid, args)
        with mock.patch.object(autopipe.Run, "trace_call", first):
            with self.assertRaises(Stop):
                self.h.run_plan(plan, until="trace")
        out = self.h.d / "run"
        self.assertEqual(sorted(json.loads((out / "state.json").read_text())["surfaces"]), ["t00-r0"])

        def second(run, sid, args):
            if sid == "t00-r2":
                raise vc3d_agent.ToolError("seed [1, 2, 3] is off the surface prediction (nothing within 8 voxels)")
            if sid == "t01-r0":
                raise vc3d_agent.ToolError("cannot open remote volume: HTTP 503")
            if sid == "t01-r1":
                return {"exit": 1, "surfaces": [], "log_tail": "the tracer failed"}
            return real(run, sid, args)
        with mock.patch.object(autopipe.Run, "trace_call", second):
            st, _ = self.h.run_plan(plan, out, until="trace")
        rec = st["stages"]["trace"]["record"]
        self.assertEqual(sorted(rec["surfaces"]), ["t00-r0", "t00-r1", "t01-r2"])
        self.assertEqual(rec["ran"], ["t00-r1", "t01-r1", "t01-r2"])
        f = st["trace_failures"]
        self.assertIn("seed check refused it", f["t00-r2"]["reason"])
        self.assertIn("the trace tool could not run", f["t01-r0"]["reason"])
        self.assertEqual(f["t01-r1"]["reason"], "the tracer exited 1")
        # the learner divides this attempt's seconds by those three, whatever the earlier attempt made
        st["stages"]["trace"]["seconds"] = 30.0
        tr = aplearn.harvest(out, state=st)[0]["stages"]["trace"]
        self.assertEqual((tr["traces"], tr["per_trace"], tr["traces_from"]), (3, 10.0, "ran"))

    def test_a_modal_folder_run_again_here_names_the_stages_this_process_ran_this_machines(self):
        # finding 1 of the check of 5190e52e: a Modal folder pulled back and resumed on this machine. Its run's own
        # end names the stage it ran this machine's; the stages Modal ran stay Modal's, whether the ledger first
        # hears of them now (the folder's marker) or held them already (read back with `learn ingest`)
        ctx = self.h.ctx
        here = aplearn.machine(ctx.env)["key"]
        self.assertNotEqual(here, "modal")
        p = self.h.plan()
        want = {"acquire": "modal", "umbilicus": "modal", "seeds": "modal", "trace": here}
        for name, read_back in (("first", False), ("ingested", True)):
            out = self.h.d / name
            ctx.env["KIT_AUTOPIPE_RUNNER"] = "modal"       # inside the Modal runner: nothing is written there
            self.h.run_plan(p, out, until="seeds")
            ctx.env.pop("KIT_AUTOPIPE_RUNNER")
            (out / "driver-cpu.json").write_text("{}")     # the driver's marker, as the finding's folder had
            if read_back:
                aplearn.ingest(ctx, [out])
            self.h.run_plan(p, out, until="trace")         # the trace stage runs here, then the run's own end
            rec = aplearn.latest(aplearn.store_path(ctx.home))[("run", str(out.resolve()))]
            self.assertEqual({s: e["machine"] for s, e in rec["stages"].items()}, want, name)
        # a review here afterward changes no stage, so every stage keeps the machine it was named
        sid = sorted(json.loads((out / "state.json").read_text())["surfaces"])[0]
        with mock.patch.object(aplearn, "now", return_value="2099-01-01T00:00:00Z"):
            aplearn.review(ctx, out, sid, "accept")
        rec = aplearn.latest(aplearn.store_path(ctx.home))[("run", str(out.resolve()))]
        self.assertEqual({s: e["machine"] for s, e in rec["stages"].items()}, want)


class TestEvaluate(unittest.TestCase):
    GOOD, BAD = {"trace": {"generations": 30}}, {"trace": {"generations": 90}}

    def planted(self, good_rate, bad_rate, runs=8, per=6, start="2026-10-17"):
        rng = random.Random(7)
        recs = []
        for i in range(runs):
            ended = f"{start}T{i:02d}:00:00Z"
            arm, rate = (self.GOOD, good_rate) if i % 2 == 0 else (self.BAD, bad_rate)
            ys = [1 if rng.random() < rate else 0 for _ in range(per)]
            base = 10.0 if i % 2 == 0 else 1000.0
            recs.append(record(f"r{i}", "PHercX", arm, ys, ended, machine="fast" if i % 2 == 0 else "slow",
                               trace_per=round(base * rng.lognormvariate(0, 0.2), 2)))
        return recs

    def test_a_planted_difference_between_arms_is_found_and_the_shuffled_control_is_not(self):
        res = aplearn.evaluate(self.planted(0.9, 0.1), permutations=199)
        q1 = res["q1_trace_acceptance"]
        self.assertEqual(q1["verdict"], "EVIDENCE", q1)
        self.assertLess(q1["fresh"]["log_loss"]["learner"], q1["fresh"]["log_loss"]["no_learning"])
        self.assertLessEqual(q1["fresh"]["permutation_p"], 0.05)
        none = aplearn.evaluate(self.planted(0.5, 0.5), permutations=199)["q1_trace_acceptance"]
        self.assertNotEqual(none["verdict"], "EVIDENCE", none)

    def test_too_few_fresh_runs_is_insufficient_and_earlier_runs_are_development_only(self):
        res = aplearn.evaluate(self.planted(0.9, 0.1, runs=2), permutations=19)
        self.assertEqual(res["q1_trace_acceptance"]["verdict"], "INSUFFICIENT")
        dev = aplearn.evaluate(self.planted(0.9, 0.1, start="2026-10-12"), permutations=19)
        self.assertEqual(dev["q1_trace_acceptance"]["fresh"]["units"], 0)
        self.assertGreater(dev["q1_trace_acceptance"]["development"]["units"], 0)
        self.assertEqual(dev["q1_trace_acceptance"]["verdict"], "INSUFFICIENT")

    def test_stage_times_per_machine_beat_the_pooled_median(self):
        recs = self.planted(0.5, 0.5, runs=24)
        q2 = aplearn.evaluate(recs, permutations=199)["q2_stage_time"]
        self.assertEqual(q2["verdict"], "EVIDENCE", q2)
        self.assertLess(q2["fresh"]["median_abs_log_error"]["learner"], q2["fresh"]["median_abs_log_error"]["no_learning"])

    def test_each_run_is_predicted_from_earlier_runs_only(self):
        recs = self.planted(0.9, 0.1)
        rows = aplearn.prequential_q1(aplearn.units(recs))
        for u, _, _, b in rows:
            seen = sum(1 for v in aplearn.units(recs) if v["at"] < u["at"])
            self.assertEqual(b["n_pooled"], seen)


class TestReview(Home):
    def test_a_review_overrules_qa_for_kept_outcomes_and_clear_takes_it_back(self):
        p = plan()
        f = write_run(self.d / "home" / "r1", p, state(p, [("t00", 0, 0, "accepted"), ("t01", 1, 0, "qa")]))
        res = aplearn.review(self.ctx, f, "t00", "reject", note="sheet switch at row 40", by="Chase")
        self.assertEqual(res["ledger"]["traces"], 2)
        self.assertEqual([u["y"] for u in aplearn.units(self.ledger(), "kept")], [0, 0])
        self.assertEqual([u["y"] for u in aplearn.units(self.ledger(), "qa")], [1, 0])
        line = json.loads((f / aplearn.REVIEW).read_text().splitlines()[0])
        self.assertEqual((line["verdict"], line["by"], line["plan_digest"]), ("reject", "Chase", p["digest"]))
        with mock.patch.object(aplearn, "now", return_value="2099-01-01T00:00:00Z"):
            aplearn.review(self.ctx, f, "t00", "clear")
        self.assertEqual([u["y"] for u in aplearn.units(self.ledger(), "kept")], [1, 0])
        for sid, verdict in (("t09", "accept"), ("t00", "maybe")):
            with self.assertRaises(aplearn.LearnError):
                aplearn.review(self.ctx, f, sid, verdict)


class TestCommandLineAndTool(Home):
    def test_the_command_line_has_learn_and_plan_learned(self):
        import argparse
        p = argparse.ArgumentParser()
        autopipe.build_parser(p)
        a = p.parse_args(["learn", "suggest", "PHerc0841", "--target", "0.9"])
        self.assertEqual((a.action, a.learn_action, a.sample, a.target), ("learn", "suggest", "PHerc0841", 0.9))
        self.assertTrue(p.parse_args(["plan", "PHerc0841", "--learned"]).learned)
        env = {"KIT_VC3D_HOME": str(self.ctx.home), "PATH": "/usr/bin:/bin"}
        out = subprocess.run([sys.executable, "-m", "kit", "autopipeline", "learn", "status"], cwd=ROOT, env=env,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["records"], 0)
        bad = subprocess.run([sys.executable, "-m", "kit", "autopipeline", "learn", "suggest", "PHercX", "--target",
                              "2"], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertTrue(bad.stderr.startswith("error:"), bad.stderr)

    def test_the_agent_tool_takes_learn(self):
        res = vc3d_agent.call("autopipeline", {"action": "learn", "learn": {"do": "status"}}, self.ctx)
        self.assertEqual(res["records"], 0)
        res = vc3d_agent.call("autopipeline", {"action": "learn", "sample": "PHercX",
                                               "learn": {"do": "estimate", "machine": "mac"}}, self.ctx)
        self.assertEqual(res["sample"], "PHercX")
        for bad in ({"do": "train"}, {"do": "status", "sample": "x"}, {"do": "suggest"},
                    {"do": "evaluate", "permutations": True}):
            with self.assertRaises(vc3d_agent.ToolError, msg=bad):
                vc3d_agent.call("autopipeline", {"action": "learn", "learn": bad}, self.ctx)

    def test_plan_learned_adds_the_suggestion_under_the_given_settings_and_says_so(self):
        aplearn.append(aplearn.store_path(self.ctx.home), [record("r1", "PHercX", {}, [0, 0, 1, 0, 0, 1],
                                                                  "2026-10-12T00:00:00Z", seeds=[0, 0, 0, 1, 1, 1])])
        seen = {}

        def fake_plan(sample, s=None, **kw):
            seen["settings"] = s
            return plan(sample=sample, **(s or {}))
        with mock.patch.object(autopipe, "make_plan", side_effect=fake_plan):
            res = vc3d_agent.call("autopipeline", {"action": "plan", "sample": "PHercX", "learned": True,
                                                   "settings": {"seeds": {"count": 3}},
                                                   "out": str(self.ctx.home / "planned")}, self.ctx)
        self.assertEqual(seen["settings"]["seeds"], {"count": 3})
        self.assertGreater(seen["settings"]["trace"]["repeats"], 1)
        learned = json.loads((self.ctx.home / "planned" / aplearn.LEARNED).read_text())
        self.assertEqual(learned["plan_digest"], res["digest"])
        self.assertEqual(res["learned"]["changes"][0]["key"], "trace.repeats")
        with self.assertRaises(vc3d_agent.ToolError):
            vc3d_agent.call("autopipeline", {"action": "plan", "sample": "PHercX", "learned": True,
                                             "settings": {"purpose": "target", "experiment": "e"}}, self.ctx)


class TestRunHook(unittest.TestCase):
    """Whole runs on test_autopipe's fakes (its TestRun harness, borrowed rather than inherited, so its own tests do
    not run twice)."""

    def setUp(self):
        self.h = TA.TestRun("test_end_to_end_to_the_modal_handoff")
        self.h.setUp()
        self.addCleanup(self.h.tearDown)
        self.ctx, self.plan, self.run_plan = self.h.ctx, self.h.plan, self.h.run_plan

    def test_every_run_ends_with_its_record_in_the_ledger(self):
        st, out = self.run_plan(self.plan(), until="qa")
        recs = aplearn.load(aplearn.store_path(self.ctx.home))
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["run"], str(out.resolve()))
        self.assertEqual(sorted(t["outcome"] for t in recs[0]["traces"]), ["accepted", "accepted"])
        self.assertEqual(recs[0]["stages"]["trace"]["backend"], "villa")
        # resumed, it is the same run: still one record
        self.run_plan(self.plan(), until="flatten")
        self.assertEqual(len(aplearn.load(aplearn.store_path(self.ctx.home))), 1)

    def test_a_ledger_that_cannot_be_written_never_fails_the_run(self):
        with mock.patch.object(aplearn, "record_run", side_effect=OSError("disk full")):
            st, out = self.run_plan(self.plan(), until="seeds")
        self.assertEqual(st["stages"]["seeds"]["status"], "done")
        self.assertFalse(aplearn.store_path(self.ctx.home).exists())


if __name__ == "__main__":
    unittest.main()
