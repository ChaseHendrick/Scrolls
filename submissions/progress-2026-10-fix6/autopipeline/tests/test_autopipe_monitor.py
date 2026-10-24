"""AutoPipeline's live monitor (kit/autopipe_monitor.py): the summary of a run folder in every state a run can be
in, the read-only local server, the self-contained snapshot, thumbnails, and the running mark and events.jsonl
that Run writes, on the synthetic scroll of tests/test_autopipe.py. The core needs no numpy."""

import argparse
import hashlib
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes as fakes  # noqa: E402
from test_autopipe import AXIS, SHAPE, catalog, scroll  # noqa: E402
from test_vc3d_agent import Base  # noqa: E402

from kit import autopipe, autopipe_monitor as mon, vc3d_agent, vc3d_io  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HOST = socket.gethostname()
T0 = 1791857000.0                     # a fixed "now" for the summaries below
STAMP = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))   # noqa: E731

try:
    import numpy  # noqa: F401
    import tifffile  # noqa: F401
    HAVE_MAPS = True
except ImportError:
    HAVE_MAPS = False


def plan_doc(purpose="smoke", trace_extra=None, models=("fake-ink",), where="local"):
    settings = autopipe._merge(autopipe.DEFAULTS, {"purpose": purpose,
                                                   "ink": {"models": list(models), "where": where}})
    if trace_extra:
        settings["trace"].update(trace_extra)
    resolved = {"sample": "PHercSynthetic", "volume": "V1", "volume_url": "ct.zarr", "voxel_um": 10.0,
                "shape_zyx": SHAPE, "license": None, "prediction_url": "pred.zarr", "prediction_model": "synthetic",
                "prediction_level": 0, "normal_grids_url": None, "normal_grids_model": None,
                "catalog_umbilicus": None, "benchmark": None}
    plan = {"version": autopipe.PLAN_VERSION, "created": "2026-10-13T00:00:00Z", "settings": settings,
            "resolved": resolved}
    plan["digest"] = autopipe.digest({k: plan[k] for k in ("version", "settings", "resolved")})
    return plan


def stage(status, end, seconds, record=None, **extra):
    rec = {"status": status, "at": STAMP(end), "seconds": seconds, **extra}
    if record is not None:
        rec["record"] = record
    return rec


def surface(sid, accepted=True, reasons=(), warnings=(), ink=True, folder=None):
    s = {"surface": f"/x/traces/{sid}", "origin": f"trace from seed [65.0, 103.0, 26.0]", "seed_index": 0,
         "repeat": 0, "trace": {"grid_rows_cols": [9, 9], "valid_fraction": 1.0, "area_cm2": 0.001}}
    s["qa"] = {"accepted": accepted, "reasons": list(reasons), "warnings": list(warnings)}
    if not accepted:
        s["qa"]["failure"] = {"kind": "ours"}
    s["accepted"] = accepted
    if accepted:
        s["flatten"] = {"used": "flattened", "passes": True, "after": {"abs_log_stretch": {"p95": 0.01},
                                                                        "shear_deg": {"p95": 1.5}}}
        s["render"] = {"audit": {"verdict": "clean", "missing_fraction": 0.0}, "exit": 0,
                       "order": "team (--flip-normals)", "zarr": f"/x/renders/{sid}/layers.zarr"}
    if accepted and ink:
        base = Path(folder or "/x") / "ink" / sid / "fake-ink"
        s["ink"] = {"fake-ink": {"exit": 0, "out": str(base), "maps": {
            v: {"path": str(base / f"ink_{v}.tif"), "stats": {"threshold": 0.5}} for v in "frs"},
            "comparison": {"r": {"above_threshold": {"forward": 0.903226, "control": 0.096774},
                                 "mean": {"forward": 0.86, "control": 0.14}, "pearson_r": -1.0}},
            "warnings": None}}
    return s


FULL = {"acquire": {"voxel_um": 10.0}, "umbilicus": {"source": "file", "points": 2},
        "seeds": {"seeds": [[65.0, 103.0, 26.0], [25.0, 66.0, 26.0]], "stats": {"candidates": 4, "refused": 2}},
        "trace": {"surfaces": ["t00", "t01"], "failed": []},
        "bench": {"skipped": "no published windings in this scan's frame to measure traces against"},
        "qa": {"accepted": ["t00", "t01"], "rejected": []}, "flatten": {"t00": "flattened", "t01": "flattened"},
        "render": {"t00": "/x/renders/t00/layers.zarr", "t01": "/x/renders/t01/layers.zarr"},
        "ink": {"t00": {"fake-ink": 0}, "t01": {"fake-ink": 0}},
        "score": {"skipped": "no labels: only published labeled segments are scored"}}


class Folder(unittest.TestCase):
    """A run folder written in the shapes AutoPipeline records (plan.json, state.json, report.json)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name) / "run"
        self.d.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_plan(self, **kw):
        self.plan = plan_doc(**kw)
        (self.d / "plan.json").write_text(json.dumps(self.plan, indent=1))
        return self.plan

    def write_state(self, stages, surfaces=None, running=None, mtime=None, **extra):
        st = {"plan_digest": self.plan["digest"], "stages": stages, "surfaces": surfaces or {}, **extra}
        if surfaces:
            st.setdefault("planned_traces", [{"sid": sid, "seed_index": i, "repeat": 0, "seed": [1, 2, 3]}
                                             for i, sid in enumerate(sorted(s for s in surfaces if s.startswith("t")))])
            st.setdefault("trace_failures", {})
        if running:
            st["running"] = running
        (self.d / "state.json").write_text(json.dumps(st, indent=1))
        if mtime is not None:
            os.utime(self.d / "state.json", (mtime, mtime))
        return st

    def stages_through(self, last, t=T0 - 600):
        out = {}
        for name in autopipe.STAGES[:autopipe.STAGES.index(last) + 1]:
            rec = FULL.get(name)
            status = "skipped" if isinstance(rec, dict) and set(rec) == {"skipped"} else "done"
            t += 5
            out[name] = stage(status, t, 4.0, rec)
        return out

    def running(self, name, pid=None, host=HOST, started=T0 - 720):
        return {"stage": name, "status": "running", "started": STAMP(started), "started_epoch": started,
                "pid": os.getpid() if pid is None else pid, "host": host}

    def summary(self, **kw):
        kw.setdefault("now", T0)
        return mon.summarize(self.d, **kw)


class TestPhases(Folder):
    def test_not_started(self):
        self.write_plan()
        s = self.summary()
        self.assertEqual(s["phase"], "not_started")
        self.assertEqual([r["status"] for r in s["stages"]], ["waiting"] * 11)
        self.assertEqual(s["banner"]["tone"], "blue")
        self.assertIn("python -m kit autopipeline run", s["banner"]["detail"])
        self.assertEqual(s["plan"]["short"], self.plan["digest"][:12])
        self.assertTrue(s["local_only"])
        self.assertIn("not a reading", s["note"])

    def test_running_with_a_live_process(self):
        self.write_plan()
        self.write_state(self.stages_through("seeds"), running=self.running("trace"), mtime=T0 - 8)
        s = self.summary()
        self.assertEqual(s["phase"], "running")
        self.assertEqual(s["current"]["stage"], "trace")
        self.assertEqual(s["current"]["index"], 4)
        self.assertAlmostEqual(s["current"]["elapsed_s"], 720.0)
        self.assertTrue(s["current"]["alive"])
        self.assertEqual(s["banner"]["tone"], "mint")
        self.assertEqual(s["banner"]["title"], "Running Trace for 12 min")
        self.assertIn("Stage 4 of 11", s["banner"]["detail"])
        row = s["stages"][3]
        self.assertEqual((row["status"], row["started_epoch"]), ("running", T0 - 720))
        self.assertEqual([r["status"] for r in s["stages"][4:]], ["waiting"] * 7)
        self.assertEqual(s["stats"]["stages_finished"], 3)

    def test_running_with_a_dead_process_is_stopped(self):
        self.write_plan()
        self.write_state(self.stages_through("seeds"), running=self.running("trace", pid=999999), mtime=T0 - 8)
        s = self.summary(alive=lambda pid: False)
        self.assertEqual(s["phase"], "stopped")
        self.assertEqual(s["banner"]["tone"], "amber")
        self.assertFalse(s["banner"]["title"].startswith("Running"))
        self.assertEqual(s["banner"]["title"], "Stopped at Trace")
        self.assertIn("pid 999999", s["banner"]["detail"])
        self.assertEqual(s["stages"][3]["status"], "stopped")
        # a real process that has ended
        p = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
        self.write_state(self.stages_through("seeds"), running=self.running("trace", pid=int(p.stdout)), mtime=T0)
        self.assertEqual(self.summary()["phase"], "stopped")

    def test_a_stopped_stage_ends_at_its_last_sign_of_life(self):
        # the stage stopped 8 s after the last write: its time is bounded, however long the page is left open
        self.write_plan()
        self.write_state(self.stages_through("seeds"), running=self.running("trace", pid=999999), mtime=T0 - 8)
        for now in (T0, T0 + 3600, T0 + 86400):
            s = self.summary(now=now, alive=lambda pid: False)
            row = s["stages"][3]
            self.assertEqual((row["status"], row["started_epoch"], row["ended_epoch"]), ("stopped", T0 - 720, T0 - 8))
            self.assertEqual((row["seconds"], s["current"]["elapsed_s"]), (712.0, 712.0))
            self.assertIn("stopped after about 11 min 52 s", row["summary"])
            self.assertIn("It ran about 11 min 52 s in Trace", s["banner"]["detail"])
        self.assertEqual(s["stats"]["run_seconds"], 712.0 + 3 * 4.0)
        # looks stopped on another host: the same bound, at least
        self.write_state(self.stages_through("seeds"), running=self.running("trace", host="elsewhere"),
                         mtime=T0 - 7200)
        row = self.summary()["stages"][3]
        self.assertEqual((row["status"], row["ended_epoch"], row["seconds"]), ("unknown", T0 - 720, 0.0))
        self.assertIn("no news for 2 h", row["summary"])

    def test_a_crashed_or_interrupted_mark_is_stopped_while_the_process_lives(self):
        # a stage raised a bug in a process that lives on (the MCP server catches it): stopped, not running
        self.write_plan()
        mark = dict(self.running("flatten"), status="crashed", ended=STAMP(T0 - 600), ended_epoch=T0 - 600,
                    error="KeyError: 'a bug in a stage'")
        self.write_state(self.stages_through("qa"), running=mark, mtime=T0 - 590)
        for now in (T0, T0 + 7200):
            s = self.summary(now=now)          # our own pid: alive
            self.assertEqual(s["phase"], "stopped")
            self.assertEqual(s["banner"]["title"], "Stopped at Flatten: crashed")
            self.assertIn("KeyError: 'a bug in a stage'", s["banner"]["detail"])
            self.assertIn("Flatten runs again", s["banner"]["detail"])
            self.assertEqual(s["stages"][6]["status"], "stopped")
            self.assertEqual(s["stages"][6]["seconds"], 120.0)
            self.assertNotEqual(s["banner"]["badge"], "Live")
        mark.update(status="interrupted", error="KeyboardInterrupt")
        self.write_state(self.stages_through("qa"), running=mark, mtime=T0 - 590)
        s = self.summary()
        self.assertEqual((s["phase"], s["banner"]["title"]), ("stopped", "Interrupted at Flatten"))
        self.assertIn("interrupted after about 2 min", s["stages"][6]["summary"])

    def test_another_host_and_a_quiet_process(self):
        self.write_plan()
        self.write_state(self.stages_through("seeds"), running=self.running("trace", host="elsewhere"),
                         mtime=T0 - 7200)
        s = self.summary()
        self.assertEqual(s["phase"], "looks_stopped")
        self.assertIsNone(s["current"]["alive"])
        self.assertIn("another machine", s["banner"]["detail"])
        self.assertEqual(s["stages"][3]["status"], "unknown")
        os.utime(self.d / "state.json", (T0 - 5, T0 - 5))
        self.assertEqual(self.summary()["phase"], "running")
        # same host, alive, but nothing written for 2 h
        self.write_state(self.stages_through("seeds"), running=self.running("trace"), mtime=T0 - 7200)
        s = self.summary()
        self.assertEqual(s["phase"], "quiet")
        self.assertEqual(s["banner"]["tone"], "amber")
        self.assertIn("quiet for 2 h", s["banner"]["title"])
        # a fresh events.jsonl counts as activity
        (self.d / mon.EVENTS).write_text(json.dumps({"t": T0 - 3, "stage": "trace", "msg": "tick"}) + "\n")
        os.utime(self.d / mon.EVENTS, (T0 - 3, T0 - 3))
        self.assertEqual(self.summary()["phase"], "running")

    def test_failed_ours_and_infrastructure(self):
        self.write_plan()
        stages = self.stages_through("umbilicus")
        stages["seeds"] = {"status": "failed", "at": STAMP(T0 - 100), "error": "no seed passed: {'planes': 23}",
                           "kind": "ours", "seconds": 0.3}
        self.write_state(stages)
        s = self.summary()
        self.assertEqual(s["phase"], "failed")
        self.assertEqual(s["banner"]["title"], "Stopped at Seeds with an error")
        self.assertTrue(s["banner"]["detail"].startswith("No seed passed."))
        self.assertNotIn("planes", s["banner"]["detail"])          # the dict is on the row, the banner says what next
        self.assertIn("planes", s["stages"][2]["error"])
        self.assertIn("AutoPipeline's own rule (ours). Next: check the inputs", s["banner"]["detail"])
        self.assertEqual([r["status"] for r in s["stages"][3:]], ["not_reached"] * 8)
        self.assertEqual(s["stages"][2]["kind"], "ours")
        stages["seeds"]["kind"] = "infrastructure"
        self.write_state(stages)
        detail = self.summary()["banner"]["detail"]
        self.assertIn("(infrastructure). Next: running again may pass", detail)
        self.assertIn(f"python -m kit autopipeline run {self.d.resolve()}", detail)

    def test_handoff(self):
        self.write_plan(where="modal")
        stages = self.stages_through("render")
        stages["ink"] = stage("handoff", T0 - 60, 0.0, {"handoff": "modal", "job": str(self.d / "modal-job.json"),
                                                        "why": "no registered model with torch here; the Modal "
                                                               "runner runs ink on a GPU"})
        stages["report"] = stage("done", T0 - 59, 0.0, {"digest": "0" * 64})
        self.write_state(stages, {"t00": surface("t00", ink=False), "t01": surface("t01", ink=False)})
        s = self.summary()
        self.assertEqual(s["phase"], "handoff")
        self.assertEqual(s["banner"]["tone"], "blue")
        self.assertEqual(s["banner"]["title"], "Handed off at Ink")
        detail = s["banner"]["detail"]
        self.assertTrue(detail.startswith("No registered model with torch here. The run stopped here and wrote "
                                          "modal-job.json."), detail)                        # once, then what next
        self.assertIn("set KIT_INK_PYTHON and run this folder again", detail)
        self.assertIn("Modal runner (a script of the source repository, which starts from the first stage", detail)
        self.assertIn("contacts no runner", detail)
        self.assertNotIn("owner", detail)
        self.assertEqual(detail.count("Modal runner"), 1)
        self.assertEqual(s["stages"][9]["status"], "waiting_runner")
        self.assertEqual(s["stages"][8]["why"], "no registered model with torch here; the Modal runner runs ink on a GPU")

    def test_finished_and_a_changed_report(self):
        self.write_plan()
        stages = self.stages_through("score")
        (self.d / "report.json").write_text(json.dumps({"stages": {k: v["status"] for k, v in stages.items()}}))
        digest = hashlib.sha256((self.d / "report.json").read_bytes()).hexdigest()
        stages["report"] = stage("done", T0 - 1, 0.0, {"digest": digest})
        self.write_state(stages, {"t00": surface("t00", folder=self.d), "t01": surface("t01", folder=self.d)})
        s = self.summary()
        self.assertEqual(s["phase"], "finished")
        self.assertEqual(s["banner"]["tone"], "mint")
        self.assertIn("matches report.json", s["banner"]["detail"])
        self.assertTrue(s["report"]["matches"])
        self.assertEqual(s["stats"]["stages_finished"], 11)
        self.assertEqual(s["stats"]["stages_skipped"], 2)
        self.assertEqual((s["stats"]["surfaces_traced"], s["stats"]["surfaces_accepted"]), (2, 2))
        (self.d / "report.json").write_text("{}")
        s = self.summary()
        self.assertFalse(s["report"]["matches"])
        self.assertEqual(s["banner"]["tone"], "amber")
        self.assertIn("changed", s["banner"]["detail"])

    def test_paused_after_until(self):
        self.write_plan()
        self.write_state(self.stages_through("render"))
        s = self.summary()
        self.assertEqual(s["phase"], "paused")
        self.assertEqual(s["banner"]["title"], "Paused after Render")
        self.assertEqual([r["status"] for r in s["stages"][8:]], ["waiting"] * 3)

    def test_no_plan_and_an_unreadable_state(self):
        s = mon.summarize(self.d)
        self.assertEqual(s["phase"], "error")
        self.assertIn("no plan.json", s["plan"]["error"])
        self.write_plan()
        # unreadable or foreign: said so, never "paused" with "no process is running"
        for raw, title in (('{"stages": ', "Cannot read state.json"), ("[1, 2]", "Cannot read state.json"),
                           (json.dumps({"plan_digest": "0" * 64, "stages": {}}), "state.json belongs to another plan")):
            (self.d / "state.json").write_text(raw)
            s = self.summary()
            self.assertEqual((s["phase"], s["banner"]["title"], s["banner"]["tone"]), ("state_error", title, "amber"))
            self.assertTrue(s["state"]["error"])
            self.assertEqual([r["status"] for r in s["stages"]], ["waiting"] * 11)
            mon.page(s)

    def test_records_of_odd_shapes_never_break_the_page(self):
        self.write_plan()
        good = self.stages_through("ink")
        odd = [
            {"stages": dict(good, trace="done")},
            {"stages": ["acquire"]},
            {"stages": good, "trace_failures": ["x"]},
            {"stages": good, "running": "trace"},
            {"stages": good, "running": {"stage": ["trace"], "pid": "123"}},
            {"stages": good, "running": {"stage": "ink", "pid": os.getpid(), "host": HOST, "started": "garbage",
                                         "started_epoch": "x"}},
            {"stages": good, "surfaces": {"t00": "junk", "t01": {"qa": "no", "ink": [1], "render": 5}}},
            {"stages": good, "planned_traces": {"a": 1}},
            {"stages": dict(good, report={"status": "done", "record": "x"}, score={"status": "done", "record": [1]})},
        ]
        files = [("scores.json", json.dumps({"m": {"whole": {"forward": "x"}}, "n": 5})),
                 ("scores.json", json.dumps({"rule": 1, "references": [1], "surfaces": {
                     "t00": {"segments": {"a": {"scorable": True, "models": {"m": "str"}}, "b": [2]}},
                     "t01": {"segments": [1]}}})),
                 ("scores.json", "[1, 2]"), ("report.json", "[1]"),
                 ("events.jsonl", '{"t": 1, "stage": ["x"], "event": "running"}\n[1]\n"s"\n')]
        for extra in odd:
            st = dict({"plan_digest": self.plan["digest"]}, **extra)
            (self.d / "state.json").write_text(json.dumps(st))
            s = self.summary()
            self.assertNotEqual(s["banner"]["title"], "Cannot read this run", extra)
            json.dumps(s)
            mon.page(s)
        self.write_state(good, {"t00": surface("t00", folder=self.d)})
        for name, text in files:
            (self.d / name).write_text(text)
            s = self.summary()
            self.assertEqual(s["phase"], "paused", name)
            mon.page(s)
        # whatever else goes wrong, summarize says so instead of raising
        with mock.patch.object(mon, "_tool_log", side_effect=RuntimeError("boom")):
            s = self.summary()
        self.assertEqual((s["phase"], s["banner"]["title"]), ("error", "Cannot read this run"))
        mon.page(s)

    def test_files_that_point_outside_the_folder_are_not_read(self):
        self.write_plan()
        outside = Path(self.tmp.name) / "secret"
        outside.mkdir()
        (outside / "secret.log").write_text("TOPSECRET-LOG-LINE\n")
        (outside / "events.jsonl").write_text(json.dumps({"t": T0, "stage": "trace", "msg": "TOPSECRET-EVENT"}) + "\n")
        (outside / "state.json").write_text(json.dumps({"plan_digest": self.plan["digest"], "stages": {
            "acquire": stage("failed", T0, 1.0, error="TOPSECRET-STATE")}}))
        os.symlink(outside / "secret.log", self.d / "tool.log")
        os.symlink(outside / "events.jsonl", self.d / mon.EVENTS)
        os.symlink(outside / "events.jsonl", self.d / mon.EVENTS_OLD)
        os.symlink(outside / "state.json", self.d / "state.json")
        os.symlink(outside / "state.json", self.d / "report.json")
        os.symlink(outside / "state.json", self.d / "scores.json")
        s = self.summary()
        self.assertNotIn("TOPSECRET", json.dumps(s))
        self.assertIsNone(s["tool_log"])
        self.assertFalse(s["events"]["present"])
        self.assertEqual(s["phase"], "state_error")
        self.assertIn("points outside the run folder", s["banner"]["detail"])
        # a symlink that stays inside the folder is read
        (self.d / "logs").mkdir()
        (self.d / "logs" / "real.log").write_text("inside line\n")
        os.symlink(self.d / "logs" / "real.log", self.d / "inside.log")
        os.utime(self.d / "logs" / "real.log", (T0 + 10, T0 + 10))
        mon._LOGS.clear()
        self.assertEqual(self.summary()["tool_log"]["lines"], ["inside line"])

    def test_paths_show_as_run_and_home(self):
        self.write_plan()
        stages = self.stages_through("umbilicus")
        stages["seeds"] = {"status": "failed", "at": STAMP(T0), "kind": "infrastructure", "seconds": 0.1,
                           "error": f"cannot read {self.d.resolve()}/grids/xy and {Path.home()}/models.json"}
        self.write_state(stages)
        (self.d / mon.EVENTS).write_text(json.dumps({"t": T0, "stage": "seeds", "msg": f"wrote {self.d.resolve()}/x"})
                                         + "\n")
        s = self.summary()
        self.assertEqual(s["stages"][2]["error"], "cannot read <run>/grids/xy and ~/models.json")
        self.assertEqual(s["events"]["lines"][-1]["msg"], "wrote <run>/x")
        # a long line keeps its paths whole until they are shortened, then is cut for the page
        mon.EventLog(self.d).line("a" * 400 + f" {self.d.resolve()}/traces/t00 " + "b" * 400)
        msg = self.summary()["events"]["lines"][-1]["msg"]
        self.assertTrue(msg.startswith("a" * 400 + " <run>/traces/t00 b"), msg[390:430])
        self.assertEqual(len(msg), mon.LINE_SHOW)
        self.assertEqual(s["folder"], str(self.d.resolve()))          # named once, in full, on the live page
        self.assertIn(str(self.d.resolve()), s["banner"]["detail"])    # the command to run again is usable
        self.assertEqual(mon._dur(4.5), "4.5 s")
        self.assertEqual([mon._dur(x) for x in (59.7, 60, 725, 3600, 7500)],
                         ["59 s", "1 min", "12 min 5 s", "1 h", "2 h 5 min"])


class TestSurfaces(Folder):
    def test_rejected_surfaces_warnings_and_ink_against_its_control(self):
        self.write_plan()
        stages = self.stages_through("trace")
        stages["qa"] = {"status": "failed", "at": STAMP(T0 - 50), "kind": "ours", "seconds": 1.0,
                        "error": "no surface passed the acceptance rule: t00: self-intersections: 3"}
        self.write_state(stages, {"t00": surface("t00", accepted=False, reasons=["self-intersections: 3"]),
                                  "t01": surface("t01", accepted=False, reasons=["self-intersections: 3"],
                                                 warnings=["winding audit fits no pitch"])})
        s = self.summary()
        t00 = s["surfaces"][0]
        self.assertEqual((t00["id"], t00["status"]), ("t00", "rejected"))
        self.assertEqual(t00["reasons"], ["self-intersections: 3"])
        self.assertEqual(t00["failure"]["kind"], "ours")
        self.assertEqual(s["stats"]["warnings"], 1)
        self.assertEqual(s["stats"]["surfaces_rejected"], 2)
        # an accepted surface with ink: the forward map beside its reversed control
        stages = self.stages_through("ink")
        self.write_state(stages, {"t00": surface("t00", folder=self.d)})
        ink = self.summary()["surfaces"][0]["ink"][0]
        self.assertEqual(ink["model"], "fake-ink")
        self.assertEqual(ink["comparison"]["r"]["forward_share_above"], 0.903226)
        self.assertEqual(ink["comparison"]["r"]["control_share_above"], 0.096774)
        self.assertEqual(ink["variants"], ["f", "r", "s"])
        # the snap check's verdict, as autopipe writes it ("passed")
        for passed in (True, False, None):
            t00 = surface("t00", folder=self.d)
            t00["render"]["snap"] = {"source": "ct", "sham": False, "check": {"passed": passed, "why": []}}
            self.write_state(stages, {"t00": t00})
            self.assertIs(self.summary()["surfaces"][0]["render"]["snap_check"], passed)
        self.assertIn('"Snap check",r.snap_check===true?"Passed"', mon.page(self.summary()))

    def test_a_trace_not_yet_checked_waits(self):
        self.write_plan()
        self.write_state(self.stages_through("trace"), {"t00": {"origin": "trace", "trace": {}}},
                         running=self.running("bench"), mtime=T0)
        s = self.summary()
        self.assertEqual(s["surfaces"][0]["status"], "waiting:qa")
        self.assertIsNone(s["surfaces"][0]["failure"])

    def test_benchmark_scores_whole_and_crop_with_the_reversed_control(self):
        self.write_plan()
        stages = self.stages_through("ink")
        auc = lambda f, c: {"forward": {"auc": f}, "control": {"auc": c}}   # noqa: E731
        scores = {"fake-ink": {"whole": auc(0.71, 0.48), "crop": auc(0.75, 0.46),
                               "shuffled_whole": {"forward": {"auc": 0.52}}}}
        (self.d / "scores.json").write_text(json.dumps(scores))
        stages["score"] = stage("done", T0 - 3, 1.0, scores)
        seg = surface("seg", folder=self.d)
        seg["qa"]["rule_verdict"], seg["qa"]["gated"] = "rejected", False
        self.write_state(stages, {"seg": seg})
        s = self.summary()
        seg = s["surfaces"][0]
        self.assertEqual(seg["status"], "published")
        rows = {r["scope"]: r for r in seg["scores"]}
        self.assertEqual((rows["whole"]["forward_auc"], rows["whole"]["control_auc"]), (0.71, 0.48))
        self.assertEqual((rows["crop"]["forward_auc"], rows["crop"]["control_auc"]), (0.75, 0.46))
        self.assertEqual(rows["whole"]["shuffled_auc"], 0.52)
        self.assertEqual(rows["whole"]["control_name"], "reversed")
        self.assertEqual(s["stats"]["published_segments"], 1)

    def test_transfer_scores_use_the_reverse_map(self):
        self.write_plan()
        m = {"forward": {"auc": 0.66}, "reverse": {"auc": 0.41}, "shuffled": {"auc": 0.5},
             "displaced": {"mean_auc": 0.55}, "reference": {"on_carried_pixels": {"auc": 0.7}}}
        scores = {"rule": {}, "references": {"0841-w00": {"surface": "ref-0841-w00", "models": {
            "fake-ink": {"whole": {"forward": {"auc": 0.8}, "control": {"auc": 0.4}}}}}},
            "surfaces": {"t00": {"segments": {"0841-w00": {"scorable": True, "models": {"fake-ink": m}},
                                              "0841-ag896": {"scorable": False, "why": "0.0 cm2 carried"}}},
                         "t01": {"scorable": False, "why": "no trace: refused"}}}
        (self.d / "scores.json").write_text(json.dumps(scores))
        self.write_state(self.stages_through("ink"), {"t00": surface("t00"), "t01": surface("t01"),
                                                      "ref-0841-w00": surface("ref-0841-w00")})
        s = {x["id"]: x for x in self.summary()["surfaces"]}
        row = next(r for r in s["t00"]["scores"] if r.get("scorable"))
        self.assertEqual((row["forward_auc"], row["control_auc"], row["shuffled_auc"], row["displaced_auc"],
                          row["reference_auc"]), (0.66, 0.41, 0.5, 0.55, 0.7))
        self.assertIn("0841-w00", row["scope"])
        self.assertTrue(any(r.get("scorable") is False and "0.0 cm2" in r["why"] for r in s["t00"]["scores"]))
        self.assertEqual(s["t01"]["scores"][0]["why"], "no trace: refused")
        self.assertEqual(s["ref-0841-w00"]["scores"][0]["forward_auc"], 0.8)

    def test_a_trace_method_is_shown_by_its_own_name(self):
        self.write_plan(trace_extra={"testdouble": {"steps": 3}})
        sur = surface("t00")
        sur["testdouble"] = {"steps_run": 3, "kept": "all", "nested": {"x": 1}, "list": [1, 2]}
        self.write_state(self.stages_through("qa"), {"t00": sur})
        s = self.summary()
        self.assertEqual(s["plan"]["trace_method"], "testdouble")
        self.assertEqual(s["surfaces"][0]["method"], {"name": "testdouble",
                                                      "summary": {"steps_run": 3, "kept": "all"}})

    def test_the_module_names_no_extension(self):
        src = (ROOT / "kit" / "autopipe_monitor.py").read_text()
        self.assertNotIn("autopipe_ext", src)
        self.assertNotIn("innerHTML", src)      # every value reaches the page as text
        builder = ROOT / "scripts" / "release" / "autopipeline.py"
        if not builder.is_file():               # a release cut has no builder; its own scan ran when it was made
            return
        from importlib import util
        spec = util.spec_from_file_location("release_autopipeline", builder)
        release = util.module_from_spec(spec)
        spec.loader.exec_module(release)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "kit").mkdir()
            (Path(tmp) / "kit" / "autopipe_monitor.py").write_text(src)
            self.assertEqual(release.scan(tmp, release.BLOCK), [])

    def test_summarize_writes_nothing(self):
        self.write_plan()
        self.write_state(self.stages_through("ink"), {"t00": surface("t00", folder=self.d)},
                         running=self.running("score"))
        (self.d / mon.EVENTS).write_text(json.dumps({"t": T0, "msg": "x"}) + "\n")

        def files():
            return {str(p.relative_to(self.d)): (p.stat().st_size, p.stat().st_mtime_ns,
                                                  hashlib.sha256(p.read_bytes()).hexdigest())
                    for p in self.d.rglob("*") if p.is_file()}
        before = files()
        for _ in range(3):
            mon.summarize(self.d)
        mon.page(mon.summarize(self.d))
        self.assertEqual(files(), before)


def write_map(path, h, w, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    vc3d_io.write_tiff(path, vc3d_io.Raster(h, w, "f32", __import__("array").array(
        "f", [value(r, c) for r in range(h) for c in range(w)])))


def png_size(blob):
    import struct
    return struct.unpack(">II", blob[16:24])


class TestThumbnails(Folder):
    def maps(self):
        base = self.d / "ink" / "t00" / "fake-ink"
        write_map(base / "ink_f.tif", 300, 500, lambda r, c: 0.2 + 0.6 * (c / 499))
        write_map(base / "ink_r.tif", 300, 500, lambda r, c: 0.1 + 0.3 * (c / 499))
        write_map(base / "ink_s.tif", 300, 500, lambda r, c: 0.5)
        return base

    def test_a_png_on_the_forward_maps_scale(self):
        base = self.maps()
        png, scale = mon.thumb_png(base / "ink_f.tif")
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        w, h = png_size(png)
        self.assertLessEqual(max(w, h), mon.THUMB_SIDE)
        # the control on the forward map's scale stays dark; stretched alone it would look like the forward map
        same, _ = mon.thumb_png(base / "ink_r.tif", scale=scale)
        alone, _ = mon.thumb_png(base / "ink_r.tif")
        import zlib
        raw = lambda b: zlib.decompress(b[b.index(b"IDAT") + 4:b.index(b"IEND") - 8])  # noqa: E731
        self.assertLess(sum(raw(same)), sum(raw(alone)))

    def test_served_and_embedded_only_through_state_and_never_for_a_target(self):
        base = self.maps()
        self.write_plan()
        self.write_state(self.stages_through("ink"), {"t00": surface("t00", folder=self.d)})
        s = self.summary()
        f_ns, r_ns = (base / "ink_f.tif").stat().st_mtime_ns, (base / "ink_r.tif").stat().st_mtime_ns
        self.assertEqual(s["surfaces"][0]["ink"][0]["thumbs"],          # the maps' mtimes: a new map, a new URL
                         {"f": f"thumb/t00/fake-ink/f.png?m={f_ns}", "r": f"thumb/t00/fake-ink/r.png?m={f_ns}.{r_ns}"})
        out = Path(self.tmp.name) / "snap.html"
        mon.snapshot(self.d, out)
        text = out.read_text()
        embedded = re.search(r'<script type="application/json" id="summary">(.*?)</script>', text, re.S).group(1)
        thumbs = json.loads(embedded)["surfaces"][0]["ink"][0]["thumbs"]
        self.assertEqual(sorted(thumbs), ["f", "r"])
        self.assertTrue(all(v.startswith("data:image/png;base64,") for v in thumbs.values()))
        self.assertNotIn("thumb/t00", text)
        # a target run: none, with the reason
        self.write_plan(purpose="target")
        self.write_state(self.stages_through("ink"), {"t00": surface("t00", folder=self.d)})
        s = self.summary()
        self.assertFalse(s["thumbs"]["enabled"])
        self.assertIn("target", s["thumbs"]["why"])
        self.assertIsNone(s["surfaces"][0]["ink"][0]["thumbs"])
        self.assertTrue(self.summary(thumbs="on")["thumbs"]["enabled"])
        self.assertTrue(base.is_dir())

    def test_on_by_default_only_for_smoke_runs_and_labelled_segments(self):
        self.maps()
        self.write_plan(purpose="benchmark")         # a benchmark with no labeled segment: maybe a target scroll
        self.write_state(self.stages_through("ink"), {"t00": surface("t00", folder=self.d)})
        s = self.summary()
        self.assertFalse(s["thumbs"]["enabled"])
        self.assertIn("names no published labeled segment", s["thumbs"]["why"])
        self.assertIsNone(s["surfaces"][0]["ink"][0]["thumbs"])
        self.assertTrue(self.summary(thumbs="on")["surfaces"][0]["ink"][0]["thumbs"])
        out = Path(self.tmp.name) / "snap.html"
        mon.snapshot(self.d, out)
        self.assertNotIn("iVBORw0KGgo", out.read_text())        # no PNG embedded
        self.plan["settings"]["segment"] = "0841-w00"   # a published labeled segment
        self.plan["resolved"]["benchmark"] = {"sample": "PHerc0841", "segment": "w00"}
        (self.d / "plan.json").write_text(json.dumps(self.plan))
        self.assertTrue(self.summary()["thumbs"]["enabled"])

    @unittest.skipUnless(HAVE_MAPS, "numpy and tifffile")
    def test_a_large_map_is_read_through_a_memory_map_or_refused(self):
        import numpy as np
        import tifffile
        base = self.d / "ink" / "t00" / "fake-ink"
        base.mkdir(parents=True)
        a = np.linspace(0, 1, 300 * 500, dtype=np.float32).reshape(300, 500)
        tifffile.imwrite(str(base / "plain.tif"), a)
        tifffile.imwrite(str(base / "packed.tif"), a, compression="zlib")
        with mock.patch.object(mon, "THUMB_MAX_DECODED", 1000), \
                mock.patch.object(tifffile.TiffPage, "asarray", side_effect=AssertionError("decoded whole")):
            png, _ = mon.thumb_png(base / "plain.tif")          # a memory map: only the rows it takes
            self.assertEqual(png_size(png), (167, 100))
            with self.assertRaisesRegex(mon.MonitorError, "a thumbnail may use, and is compressed"):
                mon._plane(base / "packed.tif")
        png2, _ = mon.thumb_png(base / "packed.tif")           # under the budget it decodes
        self.assertEqual(png_size(png2), (167, 100))



def write_mesh(folder, rows=90, cols=140, hole=lambda r, c: 30 < r < 50 and 40 < c < 70):
    """A tifxyz mesh: a quarter turn of a cylinder about z, 4 voxels a row along z, with a hole of x = y = z = -1."""
    import array
    import math
    folder.mkdir(parents=True, exist_ok=True)
    def grid(fn):
        return vc3d_io.Raster(rows, cols, "f32", array.array("f", [-1.0 if hole(r, c) else fn(r, c)
                                                                    for r in range(rows) for c in range(cols)]))
    th = lambda c: c / cols * math.pi / 2     # noqa: E731
    vc3d_io.write_tiff(folder / "x.tif", grid(lambda r, c: 500 + 200 * math.cos(th(c))))
    vc3d_io.write_tiff(folder / "y.tif", grid(lambda r, c: 500 + 200 * math.sin(th(c))))
    vc3d_io.write_tiff(folder / "z.tif", grid(lambda r, c: 1000 + 4 * r))
    return folder


def decode_wire(w):
    import array
    import base64
    q = array.array("h", base64.b64decode(w["q"]))
    if sys.byteorder != "little":
        q.byteswap()
    return [tuple(q[i:i + 3]) for i in range(0, len(q), 3)]


class TestWireframes(Folder):
    def mesh_run(self, purpose="smoke"):
        self.write_plan(purpose=purpose)
        mesh = write_mesh(self.d / "traces" / "t00")
        sur = surface("t00", folder=self.d)
        sur["surface"] = str(mesh)
        outside = write_mesh(Path(self.tmp.name) / "outside")
        evil = surface("t01", folder=self.d)
        evil["surface"] = str(outside)                       # a mesh outside the folder
        if not (self.d / "traces" / "t02").exists():
            (self.d / "traces" / "t02").mkdir()
            for a in "xyz":                                   # a mesh inside whose grids link out of it
                (self.d / "traces" / "t02" / f"{a}.tif").symlink_to(outside / f"{a}.tif")
        link = surface("t02", folder=self.d)
        link["surface"] = str(self.d / "traces" / "t02")
        self.write_state(self.stages_through("ink"), {"t00": sur, "t01": evil, "t02": link})
        return mesh

    def test_strided_centred_scaled_with_its_holes(self):
        mesh = write_mesh(self.d / "m")
        w = mon.wire_data(mesh)
        # 140 columns, every 3rd, to keep at most 64 a side (numpy keeps a partial last block, the plain reader not)
        self.assertEqual((w["rows"], w["cols"]), (30, 47) if HAVE_MAPS else (30, 46))
        self.assertLessEqual(max(w["rows"], w["cols"]), mon.WIRE_SIDE)
        self.assertEqual((w["unit"], w["hole"]), (mon.WIRE_Q, mon.WIRE_HOLE))
        pts = decode_wire(w)
        self.assertEqual(len(pts), w["rows"] * w["cols"])
        holes = [p for p in pts if p[0] == mon.WIRE_HOLE]
        self.assertTrue(holes and all(p == (mon.WIRE_HOLE,) * 3 for p in holes))
        self.assertEqual(w["valid"], len(pts) - len(holes))
        good = [p for p in pts if p[0] != mon.WIRE_HOLE]
        for axis in range(3):                                  # centered on the valid points' box
            lo, hi = min(p[axis] for p in good), max(p[axis] for p in good)
            self.assertLessEqual(abs(lo + hi), 2)
        self.assertEqual(max(max(abs(v) for v in p) for p in good), mon.WIRE_Q)   # the longest side spans 2 * WIRE_Q
        self.assertAlmostEqual(w["extent"][2], 4 * 87, delta=4)                # z: rows 0 to 87, every 3rd, 4 apart
        self.assertIs(mon.wire_data(mesh), w)                                   # cached while the grids are unchanged
        with mock.patch.object(vc3d_io, "numpy_or_none", return_value=None):  # the standard-library reader
            plain = mon.wire_data(write_mesh(self.d / "plain"))
        self.assertEqual((plain["rows"], plain["cols"]), (30, 46))
        self.assertEqual(len(decode_wire(plain)), 30 * 46)
        # a grid of holes only, and grids of different sizes, have none
        bad = write_mesh(self.d / "holes", rows=6, cols=6, hole=lambda r, c: True)
        with self.assertRaisesRegex(mon.MonitorError, "no valid point"):
            mon.wire_data(bad)
        odd = write_mesh(self.d / "odd", rows=6, cols=6)
        vc3d_io.write_tiff(odd / "z.tif", vc3d_io.Raster(3, 3, "f32", __import__("array").array("f", [1.0] * 9)))
        with self.assertRaisesRegex(mon.MonitorError, "differ in size"):
            mon.wire_data(odd)
        state = {"surfaces": {"t": {"surface": str(odd)}}}
        self.assertIsNone(mon._wire_for(self.d.resolve(), state, "t"))

    def test_only_meshes_inside_the_folder_and_never_for_a_target(self):
        mesh = self.mesh_run()
        s = {x["id"]: x for x in self.summary()["surfaces"]}
        ns = ".".join(str((mesh / f"{a}.tif").stat().st_mtime_ns) for a in "xyz")
        self.assertEqual(s["t00"]["wire"], f"wire/t00.json?m={ns}")
        self.assertIsNone(s["t01"]["wire"])
        self.assertIsNone(s["t02"]["wire"])
        m = mon.serve(self.d, port=0).start()
        self.addCleanup(m.stop, 0)
        def get(path):
            c = http.client.HTTPConnection("127.0.0.1", m.port, timeout=10)
            c.request("GET", path)
            r = c.getresponse()
            body = r.read()
            c.close()
            return r.status, dict(r.getheaders()), body
        code, head, body = get("/wire/t00.json?m=1")
        self.assertEqual(code, 200)
        self.assertEqual(head["Cache-Control"], "private, max-age=3600")
        self.assertEqual(json.loads(body)["valid"], mon.wire_data(mesh)["valid"])
        for path in ("/wire/t01.json", "/wire/t02.json", "/wire/t09.json", "/wire/..%2ftraces.json",
                     "/wire/t00", "/traces/t00/x.tif"):
            self.assertEqual(get(path)[0], 404, path)
        out = Path(self.tmp.name) / "snap.html"
        mon.snapshot(self.d, out)
        text = out.read_text()
        embedded = json.loads(re.search(r'<script type="application/json" id="summary">(.*?)</script>', text,
                                        re.S).group(1))
        wires = {x["id"]: x["wire"] for x in embedded["surfaces"]}
        self.assertEqual(wires["t00"]["q"], mon.wire_data(mesh)["q"])
        self.assertIsNone(wires["t01"])
        self.assertNotIn("wire/t00", text)
        with mock.patch.object(mon, "WIRE_SNAPSHOT_MAX", 0):
            mon.snapshot(self.d, out)
        self.assertNotIn(mon.wire_data(mesh)["q"][:40], out.read_text())
        # a target run: no wireframe unless asked for, on the page, the server or a snapshot
        self.mesh_run(purpose="target")
        self.assertIsNone(self.summary()["surfaces"][0]["wire"])
        self.assertEqual(get("/wire/t00.json")[0], 404)
        self.assertTrue(self.summary(thumbs="on")["surfaces"][0]["wire"])
        mon.snapshot(self.d, out)
        self.assertNotIn(mon.wire_data(mesh)["q"][:40], out.read_text())

    def test_the_page_draws_and_keeps_them(self):
        page = mon.page(self.summary_of_nothing())
        for text in ("function wireFigure(", "function wireDraw(", "setPointerCapture", '"ArrowLeft"',
                     "@keyframes shimmer", "prefers-reduced-motion: reduce){.sk::after", "thumbFrame(thumbImg(",
                     "Waiting for the Ink stage", 'el("div","wirebox sk")', "delete WIRES[k]"):
            self.assertIn(text, page)
        # only a wire/ URL of this server is fetched; an inline wireframe (a snapshot) is drawn as it is
        self.assertIn('s.wire.indexOf("wire/")===0', mon._JS)

    def summary_of_nothing(self):
        self.write_plan()
        return self.summary()


class TestTextView(Folder):
    def ramp(self, h=24, w=80, lo=0.2, hi=0.8, zero_cols=10):
        import array
        return vc3d_io.Raster(h, w, "f32", array.array("f", [0.0 if c < zero_cols else lo + (hi - lo) * c / (w - 1)
                                                            for r in range(h) for c in range(w)]))

    def test_characters_follow_the_map_and_the_control_keeps_the_forward_scale(self):
        r = self.ramp()
        lines, scale = mon.ascii_map(r, width=40)
        self.assertEqual(len(lines), round(24 / 80 * 40 / 2))     # a character about twice as tall as wide
        self.assertTrue(all(len(x) == 40 for x in lines))
        row = lines[0]
        self.assertEqual(row[:5], " " * 5)                         # off-surface (zeros) is blank
        ranks = [mon.RAMP.index(ch) for ch in row[5:]]
        self.assertEqual(ranks, sorted(ranks))                     # brighter to the right, as the map
        self.assertEqual((ranks[0], ranks[-1]), (0, len(mon.RAMP) - 1))
        dim = self.ramp(lo=0.2, hi=0.35)
        alone = mon.ascii_map(dim, width=40)[0][0]
        same = mon.ascii_map(dim, width=40, scale=scale)[0][0]
        self.assertGreater(max(mon.RAMP.index(c) for c in alone), max(mon.RAMP.index(c) for c in same))
        # dithering is deterministic, keeps the blanks and differs from plain rounding on a mid gray
        flat = vc3d_io.Raster(16, 32, "f32", __import__("array").array("f", [0.5] * 512))
        plain = mon.ascii_map(flat, width=32, scale=(0.0, 1.0))[0]
        dith = mon.ascii_map(flat, width=32, scale=(0.0, 1.0), dither=True)[0]
        self.assertEqual(dith, mon.ascii_map(flat, width=32, scale=(0.0, 1.0), dither=True)[0])
        self.assertEqual(len(set("".join(plain))), 1)
        self.assertGreater(len(set("".join(dith))), 1)
        self.assertEqual(mon.ascii_map(r, width=40, dither=True)[0][0][:5], " " * 5)

    def test_half_blocks_in_colour(self):
        lines, _ = mon.ascii_map(self.ramp(), width=40, color=True)
        self.assertEqual(len(lines), round(24 / 80 * 40) // 2)     # two pixels a character
        for line in lines:
            self.assertTrue(line.endswith("\x1b[0m"))
            visible = re.sub(r"\x1b\[[0-9;]*m", "", line)
            self.assertEqual(len(visible), 40)
            self.assertTrue(visible.startswith(" " * 5))
            self.assertIn(mon.UPPER, visible)
        self.assertIn("38;5;232;48;5;232m", lines[0])               # the darkest gray at the left edge of the map
        self.assertIn("38;5;255;48;5;255m", lines[0])

    def write_run(self, purpose="smoke"):
        self.write_plan(purpose=purpose)
        base = self.d / "ink" / "t00" / "fake-ink"
        write_map(base / "ink_f.tif", 30, 60, lambda r, c: 0.2 + 0.6 * c / 59)
        write_map(base / "ink_r.tif", 30, 60, lambda r, c: 0.3)
        self.write_state(self.stages_through("ink"), {"t00": surface("t00", folder=self.d),
                                                      "t01": surface("t01", accepted=False, reasons=["too small"])})

    def test_the_run_as_text(self):
        self.write_run()
        text = mon.text_view(self.d, width=30, now=T0)
        for want in ("AP Monitor | run | Plan ", "Stages", "  Acquire    Done", "  QA         Done",
                     "  Score      Not run yet", "Surfaces: 2", "  t00  Accepted", "  t01  Rejected",
                     "    QA: too small", "    fake-ink: forward", "reversed control, same scale", mon.NOTE):
            self.assertIn(want, text)
        art = [x for x in text.splitlines() if x.startswith("    ") and set(x[4:34]) <= set(mon.RAMP)]
        self.assertEqual(len(art), round(30 / 60 * 30 / 2))
        self.assertNotIn("\x1b[", text)
        self.assertIn("\x1b[", mon.text_view(self.d, width=30, color=True, now=T0))
        with mock.patch.object(mon, "TEXT_SURFACES", 0):
            self.assertIn("The maps of 1 more are not drawn here", mon.text_view(self.d, now=T0))

    def test_no_maps_drawn_for_a_target_run(self):
        self.write_run(purpose="target")
        text = mon.text_view(self.d, now=T0)
        self.assertNotIn("reversed control, same scale", text)
        self.assertIn("No maps drawn: a target run", text)
        self.assertIn("reversed control, same scale", mon.text_view(self.d, now=T0, thumbs="on"))

    def test_command_line(self):
        import io
        self.write_run()
        p = argparse.ArgumentParser()
        autopipe.build_parser(p)
        a = p.parse_args(["monitor", str(self.d), "--text", "--width", "24", "--color", "off"])
        out = io.StringIO()
        self.assertEqual(mon._text_cli(self.d, a, {"thumbs": "auto"}, out=out), 0)
        self.assertIn("    fake-ink: forward", out.getvalue())
        calls = []
        def sleep(s):
            calls.append(s)
            if len(calls) == 2:
                raise KeyboardInterrupt
        a = p.parse_args(["monitor", str(self.d), "--text", "--watch", "2"])
        out = io.StringIO()
        self.assertEqual(mon._text_cli(self.d, a, {}, out=out, sleep=sleep), 0)
        self.assertEqual((calls, out.getvalue().count("Stages\n")), ([2.0, 2.0], 2))
        for bad, why in ((["--width", "4"], "--width is at least 8"), (["--watch", "0.5"], "at least 1 second"),
                         (["--snapshot", "x.html"], "do not go together")):
            a = p.parse_args(["monitor", str(self.d), "--text", *bad])
            with mock.patch("sys.stderr", io.StringIO()) as err:
                self.assertEqual(mon._text_cli(self.d, a, {}, out=io.StringIO()), 2, bad)
            self.assertIn(why, err.getvalue())


class TestServer(Folder):
    def setUp(self):
        super().setUp()
        self.write_plan()
        base = self.d / "ink" / "t00" / "fake-ink"
        write_map(base / "ink_f.tif", 20, 30, lambda r, c: c / 30)
        write_map(base / "ink_r.tif", 20, 30, lambda r, c: 0.1)
        sur = surface("t00", folder=self.d)
        outside = Path(self.tmp.name) / "outside.tif"
        write_map(outside, 4, 4, lambda r, c: 0.5)
        evil = surface("t01", folder=self.d)
        evil["ink"]["fake-ink"]["maps"]["f"]["path"] = str(outside)
        evil["ink"]["fake-ink"]["maps"]["r"]["path"] = "../outside.tif"
        self.write_state(self.stages_through("ink"), {"t00": sur, "t01": evil})
        self.m = mon.serve(self.d, port=0).start()
        self.addCleanup(self.m.stop, 0)

    def get(self, path, method="GET", host=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.m.port, timeout=10)
        c.putrequest(method, path, skip_host=True)
        c.putheader("Host", host or f"127.0.0.1:{self.m.port}")
        if body is not None:
            c.putheader("Content-Length", str(len(body)))
        c.endheaders()
        if body is not None:
            c.send(body)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, dict(r.getheaders()), data

    def test_local_read_only_and_nothing_outside_the_folder(self):
        def files():
            return {str(p): p.stat().st_mtime_ns for p in self.d.rglob("*")}
        before = files()
        self.assertEqual(self.m.httpd.server_address[0], "127.0.0.1")
        self.assertTrue(self.m.url.startswith("http://127.0.0.1:"))
        code, head, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertTrue(head["Content-Type"].startswith("text/html"))
        self.assertIn("default-src 'none'", head["Content-Security-Policy"])
        self.assertEqual(head["X-Content-Type-Options"], "nosniff")
        page = body.decode()
        for text in ("model output, not a reading", "Local only", "must not be shared"):
            self.assertIn(text, page)
        code, head, body = self.get("/summary.json")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["plan"]["digest"], self.plan["digest"])
        self.assertEqual(head["Cache-Control"], "no-store")
        code, head, body = self.get("/thumb/t00/fake-ink/f.png?m=1")
        self.assertEqual((code, body[:4]), (200, b"\x89PNG"))
        self.assertEqual(head["Cache-Control"], "private, max-age=3600")
        self.assertEqual(self.get("/thumb/t00/fake-ink/r.png")[0], 200)
        for path in ("/plan.json", "/state.json", "/../plan.json", "/%2e%2e/plan.json", "/thumb/../../x",
                     "/thumb/t00/fake-ink/s.png", "/thumb/t01/fake-ink/f.png", "/thumb/t01/fake-ink/r.png",
                     "/thumb/%2e%2e/fake-ink/f.png", "/thumb/t00/..%2f..%2fplan.json/f.png", "/ink/t00/fake-ink/ink_f.tif"):
            self.assertEqual(self.get(path)[0], 404, path)
        self.assertEqual(self.get("/summary.json", method="POST", body=b"{}")[0], 405)
        self.assertEqual(self.get("/", method="DELETE")[0], 405)
        self.assertEqual(self.get("/summary.json", host="evil.example:80")[0], 403)
        self.assertEqual(self.get("/summary.json", host=f"localhost:{self.m.port}")[0], 200)
        shared = json.loads(self.get("/summary.json?share=1")[2])     # the page's export
        self.assertEqual(shared["folder"], self.d.name)
        self.assertNotIn(str(self.d.resolve()), json.dumps(shared))
        for _ in range(5):
            self.get("/summary.json")
        self.assertEqual(files(), before)
        self.assertFalse((self.d / mon.EVENTS).exists())

    def test_a_busy_port_falls_back_and_start_never_raises(self):
        import io
        err = io.StringIO()
        m2 = mon.start(self.d, self.m.port, out=err)
        self.assertIsNotNone(m2)
        self.addCleanup(m2.stop, 0)
        self.assertNotEqual(m2.port, self.m.port)
        self.assertIn("local only", err.getvalue())
        bad = mon.start(self.d, 80, host="203.0.113.1", out=err)    # an address this machine does not have
        self.assertIsNone(bad)
        self.assertIn("the run goes on", err.getvalue())


class TestSnapshot(Folder):
    def test_self_contained_and_escaped(self):
        self.write_plan()
        stages = self.stages_through("umbilicus")
        stages["seeds"] = {"status": "failed", "at": STAMP(T0), "kind": "ours", "seconds": 0.1,
                           "error": "</script><script>alert(1)</script> & <b>"}
        self.write_state(stages)
        out = Path(self.tmp.name) / "snap" / "run.html"
        got = mon.snapshot(self.d, out)
        self.assertEqual(got, out.resolve())
        text = out.read_text()
        no_comments = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        self.assertNotRegex(no_comments, r"https?://")
        for bad in ("<link", "@import", 'src="http', "href=\"http", "url("):
            self.assertNotIn(bad, text)
        self.assertNotIn("<script>alert(1)", text)
        self.assertEqual(text.count("</script>"), 3)        # the summary's, the console's and the page script's own ends
        m = re.search(r'<script type="application/json" id="summary">(.*?)</script>', text, re.S)
        s = json.loads(m.group(1))
        self.assertEqual(s["phase"], "failed")
        self.assertIn("<script>alert(1)</script>", s["stages"][2]["error"])
        self.assertIn("Content-Security-Policy", text)
        self.assertIn("connect-src 'none'", text)
        self.assertIn("var LIVE = false", text)

    def test_a_snapshot_names_no_path_host_or_process(self):
        self.write_plan()
        self.write_state(self.stages_through("seeds"), running=self.running("trace"), mtime=time.time())
        (self.d / mon.EVENTS).write_text(json.dumps({"t": T0, "stage": "trace", "msg": f"in {self.d.resolve()}/t"})
                                         + "\n")
        out = Path(self.tmp.name) / "share" / "run.html"
        mon.snapshot(self.d, out)
        text = out.read_text()
        s = json.loads(re.search(r'<script type="application/json" id="summary">(.*?)</script>', text, re.S).group(1))
        self.assertEqual(s["phase"], "running")
        self.assertEqual(s["folder"], self.d.name)
        self.assertEqual((s["current"]["pid"], s["current"]["host"]), (None, None))
        for secret in (str(self.d.resolve()), str(Path(self.tmp.name).resolve()), f"Process {os.getpid()}",
                       f"on {HOST}"):
            self.assertNotIn(secret, text)
        self.assertEqual(s["events"]["lines"][-1]["msg"], "in <run>/t")

    def test_a_cut_line_leaves_no_piece_of_the_folder_path(self):
        # a progress line keeps a tool log line's last 200 characters (kit/vc3d_agent.py), which can start inside
        # the folder's path; a line cut at LINE_KEEP can end inside it. Neither piece may name the folder's parents.
        self.d = Path(self.tmp.name) / ("parent-" + "d" * 40) / "deep-scratch-folder" / "run"
        self.d.mkdir(parents=True)
        self.write_plan()
        self.write_state(self.stages_through("render"))
        folder = str(self.d.resolve())
        pieces = [folder[k:] for k in range(1, len(folder)) if folder.find("/", k + 1) != -1]
        heads = [folder[:k] for k in range(2, len(folder)) if folder.find("/", 1, k) != -1]
        log = mon.EventLog(self.d)
        for piece in pieces:
            log.line(f"vc_render_tifxyz: 30 s; {piece}/renders/t00/layers.zarr: [28, 36, 36]")
        (self.d / "tool.log").write_text("".join(f"python: 0 s; {p}/ink/t00\n" for p in pieces[-15:]))
        item = len(folder) + len("/a000 ")
        pad = (mon.LINE_KEEP - 1 - len(folder) // 2) % item       # the cut lands halfway into a path
        repeated = ("x" * (pad - 1) + " " if pad else "") + " ".join(
            f"{folder}/a{i:03d}" for i in range(mon.LINE_KEEP // item + 2))
        log.line(repeated)                 # cut at LINE_KEEP inside a path; short once its whole paths are <run>
        cut = repeated[:mon.LINE_KEEP - 1]
        self.assertTrue(any(cut.endswith(h) for h in heads), cut[-40:])
        mon._LOGS.clear()
        s = self.summary(share=True, tail=len(pieces) + 5)
        out = Path(self.tmp.name) / "share" / "run.html"
        mon.snapshot(self.d, out)
        for text in (json.dumps(s, ensure_ascii=False), out.read_text().replace("\\u003c", "<")
                     .replace("\\u003e", ">").replace("\\u2026", "…")):
            for piece in pieces:
                self.assertNotIn(piece, text)
            for head in heads:
                self.assertNotIn(head + "…", text)
        msgs = [x["msg"] for x in s["events"]["lines"]]
        self.assertIn("vc_render_tifxyz: 30 s; <run>/renders/t00/layers.zarr: [28, 36, 36]", msgs)
        self.assertIn(" <run>/a000 <run>/a001 ", " " + msgs[-1])
        self.assertTrue(msgs[-1].endswith("<run>…"), msgs[-1][-40:])
        self.assertEqual(s["tool_log"]["lines"][-1], "python: 0 s; <run>/ink/t00")
        # a path elsewhere that shares only the folder's last name, or one folder name, is not a piece of it
        log.line("wrote /opt/run/x and run/y and /deep-scratch-folder/z")
        msg = self.summary()["events"]["lines"][-1]["msg"]
        self.assertEqual(msg, "wrote /opt/run/x and run/y and /deep-scratch-folder/z")
        # a snapshot shows any other absolute path by its last name: a tool or model beside the run folder names
        # the folders around it; the live page keeps it whole, and a URL is kept as it is
        beside = f"{self.d.parent.resolve()}/vc3d/checks/t00/profile.tif"
        log.line(f"$ {beside} --model={self.d.parent.resolve()}/fake_ink_model.py {folder}/x s3://b/v/x.zarr /tmp")
        self.assertEqual(self.summary(share=True)["events"]["lines"][-1]["msg"],
                         "$ …/profile.tif --model=…/fake_ink_model.py <run>/x s3://b/v/x.zarr /tmp")
        self.assertIn(beside, self.summary()["events"]["lines"][-1]["msg"])
        out2 = Path(self.tmp.name) / "share" / "run2.html"
        mon.snapshot(self.d, out2)
        self.assertNotIn(str(self.d.parent.resolve()), out2.read_text())
        self.assertNotIn(Path(self.tmp.name).resolve().name, out2.read_text())
        # a progress line's tail that starts inside a path elsewhere (a Python under a home folder) keeps only its
        # last name in a snapshot, so the cut never shows part of a user's name; the live page keeps the line
        log.line(f"python: 0 s; ase-example/miniconda3/bin/python …/fake_ink_model.py {folder}/ink/t00 0")
        self.assertEqual(self.summary(share=True)["events"]["lines"][-1]["msg"],
                         "python: 0 s; …/python …/fake_ink_model.py <run>/ink/t00 0")
        self.assertIn("ase-example/miniconda3", self.summary()["events"]["lines"][-1]["msg"])

    def test_refuses_the_run_folder_and_a_tracked_path(self):
        self.write_plan()
        with self.assertRaisesRegex(mon.MonitorError, "inside the run folder"):
            mon.snapshot(self.d, self.d / "x.html")
        with self.assertRaisesRegex(mon.MonitorError, "inside the run folder"):
            mon.snapshot(self.d, self.d / "sub" / "x.html")
        ctx = vc3d_agent.Context(root=ROOT, env=dict(os.environ, KIT_HOME=str(ROOT)))
        target = ROOT / "kit" / "monitor-snapshot-test.html"
        with self.assertRaises(vc3d_agent.ToolError):
            mon.snapshot(self.d, target, ctx=ctx)
        self.assertFalse(target.exists())
        self.assertFalse((self.d / "x.html").exists())


class TestWording(Folder):
    """The agreed wording (13 Oct 2026; the short name is AP since 14 Oct): title case for the header, stage names
    and statuses with a capital, sentence case for labels and badges, AP Monitor on the tab and at phone width."""

    def test_stage_names(self):
        self.assertEqual([mon._label(n) for n in autopipe.STAGES],
                         ["Acquire", "Umbilicus", "Seeds", "Trace", "Bench", "QA", "Flatten", "Render", "Ink",
                          "Score", "Report"])
        self.assertIn('var STAGE_NAME = {qa:"QA"};', mon._JS)
        self.assertEqual(mon.STAGE_LABELS, {"qa": "QA"})

    def test_statuses_and_badges(self):
        labels = dict(re.findall(r'(\w+):"([^"]+)"', re.search(r"var STAGE_LABEL = \{(.*?)\};", mon._JS,
                                                                   re.S).group(1)))
        self.assertEqual(labels["waiting"], "Not run yet")
        self.assertEqual(labels["done"], "Done")
        for v in labels.values():
            self.assertTrue(v[0].isupper() and v[1:] == v[1:].lower(), v)
        badges = re.findall(r'"badge": "([^"]+)"', Path(mon.__file__).read_text())
        self.assertIn("Handed off", badges)
        for b in badges:
            self.assertTrue(b[0].isupper() and b[1:] == b[1:].lower(), b)

    def test_no_forced_capitals_and_the_short_name(self):
        self.assertNotIn("uppercase", mon._CSS)
        self.assertIn("<title>AP Monitor</title>", mon._HTML)
        self.assertIn('" | AP Monitor"', mon._JS)
        self.assertIn('<span class="full">AutoPipeline Monitor</span><span class="short">AP Monitor</span>',
                      mon._HTML)
        phone = mon._CSS[mon._CSS.index("@media (max-width:600px)"):]
        self.assertIn(".brand .full{display:none}.brand .short{display:inline}", phone)

    def test_one_text_scale_stepped_down_on_small_screens(self):
        # every font size goes through --fz, so a small screen shrinks all text together
        sizes = re.findall(r"font-size:([^;}\"]+)", mon._CSS + mon._HTML)
        self.assertGreater(len(sizes), 30)
        for s in sizes:
            self.assertRegex(s, r"^(calc\([\d.]+px\*var\(--fz\)\)|inherit)$")
        self.assertIn("body{font:calc(13px*var(--fz))/1.45", mon._CSS)
        tail = mon._CSS[mon._CSS.rindex("@media (max-width:1440px),(max-height:820px)"):]
        self.assertIn(":root{--fz:.9}", tail)
        self.assertNotIn("@media (max-width:1000px)", tail)    # last in the sheet, so its rules win

    def test_a_banner_names_the_stage_with_a_capital(self):
        self.write_plan()
        self.write_state(self.stages_through("bench"), running=self.running("qa"), mtime=T0 - 5)
        s = self.summary()
        self.assertTrue(s["banner"]["title"].startswith("Running QA for"), s["banner"]["title"])
        self.assertEqual(s["banner"]["badge"], "Live")


class TestEventLog(unittest.TestCase):
    def test_lines_events_and_the_size_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = mon.EventLog(tmp)
            seen = []
            say = log.tee(seen.append)
            rec = log.running("trace", 1000.0)
            self.assertEqual({k: rec[k] for k in ("stage", "status", "pid", "host")},
                             {"stage": "trace", "status": "running", "pid": os.getpid(), "host": HOST})
            self.assertEqual(rec["started"], "1970-01-01T00:16:40Z")
            say("hello")
            log.stage("trace", "failed", {"seconds": 1.5, "error": "x" * 2000})
            self.assertEqual(seen, ["hello"])
            log.tee(None)("no one listens")
            lines = [json.loads(x) for x in (Path(tmp) / mon.EVENTS).read_text().splitlines()]
            self.assertEqual(lines[1], {"t": lines[1]["t"], "stage": "trace", "msg": "hello"})
            self.assertEqual((lines[2]["event"], lines[2]["seconds"]), ("failed", 1.5))
            self.assertLessEqual(len(lines[2]["error"]), mon.MAX_TEXT)
            self.assertIsNone(lines[3]["stage"])
            for i in range(3000):                       # about 300 KiB
                log.line(f"line {i} " + "y" * 90)
            sizes = [p.stat().st_size for p in Path(tmp).glob("events*.jsonl")]
            self.assertEqual(len(sizes), 2)
            self.assertLessEqual(sum(sizes), 2 * mon.EVENTS_MAX + 1024)
            for p in Path(tmp).glob("events*.jsonl"):
                for x in p.read_text().splitlines():
                    json.loads(x)
            s = mon._events(Path(tmp), 60)
            self.assertEqual(len(s["lines"]), 60)
            self.assertTrue(s["truncated"])
        mon.EventLog(Path(tmp) / "gone" / "deeper").line("never fails")


class TestRun(Base):
    """The running mark and events.jsonl on a whole synthetic run (tests/test_autopipe.py's scroll)."""

    WANT = {"acquire": "done", "umbilicus": "done", "seeds": "done", "trace": "done", "bench": "skipped",
            "qa": "done", "flatten": "done", "render": "done", "ink": "done", "score": "skipped", "report": "done"}

    def setUp(self):
        super().setUp()
        self.pred, self.ct, self.axis = scroll(self.d)
        self.ctx = self.context(FAKE_TRACE_ARC=f"{AXIS[0]},{AXIS[1]}")
        model = self.d / "fake_ink_model.py"
        model.write_text(fakes.INK_MODEL)
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "models.json").write_text(json.dumps({"fake-ink": {
            "engine": "command", "command": [sys.executable, str(model), "{layers}", "{output}", "{reverse}"]}}))

    def plan(self):
        g = self.d / "grids"
        (g / "xy").mkdir(parents=True, exist_ok=True)
        (g / "metadata.json").write_text(json.dumps({"spiral-step": 20, "grid-step": 64}))
        settings = autopipe._merge(autopipe.DEFAULTS, {
            "purpose": "smoke", "umbilicus": {"source": str(self.axis)},
            "seeds": {"count": 2, "z_range": [20, 44], "radius_um": [300.0, 500.0], "level": 0,
                      "min_spacing_um": 80.0},
            "qa": {"require_seated": "none", "windaudit": "off", "windows": 1},
            "ink": {"where": "local", "models": ["fake-ink"], "variants": ["f", "r", "s"]}})
        resolved = {"sample": "PHercFake", "volume": "V1", "volume_url": str(self.ct), "voxel_um": 10.0,
                    "shape_zyx": SHAPE, "license": None, "prediction_url": str(self.pred),
                    "prediction_model": "fake", "prediction_level": 0, "normal_grids_url": str(g),
                    "normal_grids_model": "fake", "catalog_umbilicus": None, "benchmark": None}
        plan = {"version": autopipe.PLAN_VERSION, "created": "2026-10-13T00:00:00Z", "settings": settings,
                "resolved": resolved}
        plan["digest"] = autopipe.digest({k: plan[k] for k in ("version", "settings", "resolved")})
        return plan

    def test_the_running_mark_events_and_a_clean_report(self):
        plan = self.plan()
        out = self.d / "run"
        out.mkdir()
        seen = {}
        real = autopipe.Run.s_qa
        real_ink = autopipe.Run.s_ink
        ink_progress = "deterministic ink-stage progress"

        def s_qa(run):
            seen["state"] = json.loads((out / "state.json").read_text())
            seen["done"] = run.done("qa")
            seen["summary"] = mon.summarize(out)
            return real(run)

        def s_ink(run):
            # A fast fake model can finish before run_logged's first 0.5 s progress poll. Exercise the
            # monitor's tee during this stage without depending on subprocess speed or slowing the fixture.
            # run_logged's polling is covered separately by test_vc3d_agent.TestRunLogged.
            run.ctx.say(ink_progress)
            return real_ink(run)

        said = []
        self.ctx.progress = said.append
        with mock.patch.object(autopipe.Run, "s_qa", s_qa), mock.patch.object(autopipe.Run, "s_ink", s_ink):
            st = autopipe.Run(vc3d_agent, self.ctx, out, plan).run()
        self.assertIs(self.ctx.progress.__self__, said)          # restored after the run
        r = seen["state"]["running"]
        self.assertEqual((r["stage"], r["status"], r["pid"], r["host"]), ("qa", "running", os.getpid(), HOST))
        self.assertNotIn("qa", seen["state"]["stages"])
        self.assertFalse(seen["done"])
        self.assertEqual(seen["summary"]["phase"], "running")
        self.assertEqual(seen["summary"]["current"]["stage"], "qa")
        self.assertEqual({k: v["status"] for k, v in st["stages"].items()}, self.WANT)
        self.assertNotIn("running", st)
        self.assertNotIn("running", json.loads((out / "state.json").read_text()))
        self.assertNotIn("running", (out / "report.json").read_text())
        self.assertEqual(json.loads((out / "plan.json").read_text()), plan)
        events = [json.loads(x) for x in (out / mon.EVENTS).read_text().splitlines()]
        marks = [(e["stage"], e["event"]) for e in events if "event" in e]
        self.assertEqual(marks[:2], [("acquire", "running"), ("acquire", "done")])
        self.assertIn(("report", "done"), marks)
        self.assertTrue(any("msg" in e and e["stage"] == "ink" for e in events))
        self.assertTrue(any(e.get("msg") == ink_progress and e["stage"] == "ink" for e in events))
        self.assertIn(ink_progress, said)
        self.assertTrue(said)                                     # progress still reached the caller
        s = mon.summarize(out)
        self.assertEqual(s["phase"], "finished")
        self.assertEqual(s["stats"]["surfaces_accepted"], 2)
        self.assertTrue(s["events"]["present"])
        # a second run reruns the report only, and its report has no running mark either
        plan_bytes = (out / "plan.json").read_bytes()
        st2 = autopipe.Run(vc3d_agent, self.ctx, out, plan).run()
        self.assertNotIn("running", st2)
        self.assertNotIn("running", (out / "report.json").read_text())
        self.assertEqual((out / "plan.json").read_bytes(), plan_bytes)

    def test_a_crash_ends_the_mark_and_a_resume_clears_it(self):
        plan = self.plan()
        out = self.d / "run"
        out.mkdir()

        def boom(run):
            raise KeyError("a bug in a stage")
        # the caller catches the error and lives on, as the MCP server does: the run must not read as running
        with mock.patch.object(autopipe.Run, "s_flatten", boom):
            with self.assertRaises(KeyError):
                autopipe.Run(vc3d_agent, self.ctx, out, plan).run()
        st = json.loads((out / "state.json").read_text())
        r = st["running"]
        self.assertEqual((r["stage"], r["status"], r["pid"]), ("flatten", "crashed", os.getpid()))
        self.assertEqual(r["error"], "KeyError: 'a bug in a stage'")
        self.assertGreaterEqual(r["ended_epoch"], r["started_epoch"])
        self.assertNotIn("flatten", st["stages"])
        self.assertFalse(autopipe.Run(vc3d_agent, self.ctx, out, plan).done("flatten"))
        for now in (None, time.time() + 3600):
            s = mon.summarize(out, now=now)                 # this process, alive
            self.assertEqual((s["phase"], s["banner"]["title"]), ("stopped", "Stopped at Flatten: crashed"))
        events = [json.loads(x) for x in (out / mon.EVENTS).read_text().splitlines()]
        self.assertEqual((events[-1]["stage"], events[-1]["event"]), ("flatten", "crashed"))
        status = vc3d_agent.call("autopipeline", {"action": "status", "out": str(out)}, self.ctx)
        self.assertEqual(status["running"]["status"], "crashed")
        st = autopipe.Run(vc3d_agent, self.ctx, out, plan).run()
        self.assertNotIn("running", st)
        self.assertEqual(st["stages"]["flatten"]["status"], "done")
        self.assertEqual(mon.summarize(out)["phase"], "finished")
        self.assertIsNone(vc3d_agent.call("autopipeline", {"action": "status", "out": str(out)}, self.ctx)["running"])

    def test_ctrl_c_marks_the_stage_interrupted(self):
        plan = self.plan()
        out = self.d / "run"
        out.mkdir()
        seen = {}

        def stop(run):
            seen["running"] = vc3d_agent.call("autopipeline", {"action": "status", "out": str(out)},
                                              self.ctx)["running"]
            raise KeyboardInterrupt()
        with mock.patch.object(autopipe.Run, "s_trace", stop):
            with self.assertRaises(KeyboardInterrupt):
                autopipe.Run(vc3d_agent, self.ctx, out, plan).run()
        self.assertEqual((seen["running"]["stage"], seen["running"]["status"]), ("trace", "running"))
        st = json.loads((out / "state.json").read_text())
        self.assertEqual((st["running"]["stage"], st["running"]["status"]), ("trace", "interrupted"))
        s = mon.summarize(out)
        self.assertEqual((s["phase"], s["banner"]["title"]), ("stopped", "Interrupted at Trace"))

    def test_a_failed_stage_clears_the_mark(self):
        plan = self.plan()
        out = self.d / "run"
        out.mkdir()

        def refuse(run):
            raise autopipe.AutoError("no seed passed", kind="ours")
        with mock.patch.object(autopipe.Run, "s_seeds", refuse):
            st = autopipe.Run(vc3d_agent, self.ctx, out, plan).run()
        self.assertNotIn("running", st)
        self.assertEqual(st["stages"]["seeds"]["status"], "failed")
        s = mon.summarize(out)
        self.assertEqual(s["phase"], "failed")
        self.assertEqual([r["status"] for r in s["stages"][3:]], ["not_reached"] * 8)


class TestDigests(unittest.TestCase):
    def test_plans_keep_their_digests(self):
        # with ink_9um seed 42, the default reader before 15 Oct 2026, written out
        old = {"models": ["ink_9um-seed42"]}
        self.assertEqual(autopipe.make_plan("PHercTest", {"ink": old}, cat=catalog())["digest"],
                         "33dcf5a71f050b5e12d556f8ef3f59d4cbece1a6f673099842255a512d37566c")
        self.assertEqual(autopipe.make_plan("PHercTest", {"purpose": "smoke", "ink": old}, cat=catalog())["digest"],
                         "c45614274fe03e44b24be22ba31bd5b847f9f75bc4e1a231ca294f62e4b12126")


class TestCommandLine(Base):
    def kit(self, *args, env=None, cwd=None):
        env = dict(env or self.env)
        env["PYTHONPATH"] = str(ROOT)
        return subprocess.run([sys.executable, "-m", "kit", "autopipeline", *args], capture_output=True, text=True,
                              env=env, cwd=cwd or self.d, timeout=300)

    def test_parsing(self):
        p = argparse.ArgumentParser()
        autopipe.build_parser(p)
        self.assertEqual(p.parse_args(["run", "F", "--monitor"]).monitor, mon.DEFAULT_PORT)
        self.assertEqual(p.parse_args(["run", "F", "--monitor", "0"]).monitor, 0)
        self.assertIsNone(p.parse_args(["run", "F"]).monitor)
        a = p.parse_args(["monitor", "F", "--snapshot", "x.html", "--port", "0"])
        self.assertEqual((a.action, a.snapshot, a.port, a.host, a.thumbs), ("monitor", "x.html", 0, "127.0.0.1",
                                                                             "auto"))

    def test_help_snapshot_from_the_kit_home_and_a_folder_without_a_plan(self):
        self.assertEqual(self.kit("monitor", "--help").returncode, 0)
        home = self.d / "kithome"
        run = home / "work" / "autopipe" / "r1"
        run.mkdir(parents=True)
        (run / "plan.json").write_text(json.dumps(plan_doc()))
        env = dict(self.env, KIT_HOME=str(home))
        out = self.d / "snaps" / "r1.html"
        p = self.kit("monitor", "work/autopipe/r1", "--snapshot", str(out), env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["folder"], str(run))
        page = out.read_text()
        self.assertIn('<span class="full">AutoPipeline Monitor</span><span class="short">AP Monitor</span>', page)
        self.assertIn("<title>AP Monitor</title>", page)
        p = self.kit("monitor", "work/autopipe/none", "--snapshot", str(out), env=env)
        self.assertEqual(p.returncode, 2)
        self.assertIn("has no plan.json", p.stderr)

    def test_run_with_the_monitor(self):
        pred, ct, axis = scroll(self.d)
        out = self.d / "run"
        out.mkdir()
        plan = plan_doc()
        plan["settings"]["umbilicus"]["source"] = str(axis)
        plan["resolved"].update(volume_url=str(ct), prediction_url=str(pred))
        plan["digest"] = autopipe.digest({k: plan[k] for k in ("version", "settings", "resolved")})
        (out / "plan.json").write_text(json.dumps(plan))
        p = self.kit("run", str(out), "--until", "acquire", "--monitor", "0")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertRegex(p.stderr, r"monitor: http://127\.0\.0\.1:\d+/ \(local only, stops when the run ends\)")
        st = json.loads((out / "state.json").read_text())
        self.assertEqual(st["stages"]["acquire"]["status"], "done")
        self.assertNotIn("running", st)

    def test_the_monitor_keeps_the_exit_code_and_stops_with_the_run(self):
        import io
        pred, ct, axis = scroll(self.d)
        out = self.d / "run"
        out.mkdir()
        plan = plan_doc()
        plan["settings"]["umbilicus"]["source"] = str(self.d / "no-such-axis.json")     # umbilicus fails
        plan["resolved"].update(volume_url=str(ct), prediction_url=str(pred))
        plan["digest"] = autopipe.digest({k: plan[k] for k in ("version", "settings", "resolved")})
        (out / "plan.json").write_text(json.dumps(plan))
        p = self.kit("run", str(out), "--until", "umbilicus", "--monitor", "0")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertRegex(p.stderr, r"monitor: http://127\.0\.0\.1:\d+/ \(local only, stops when the run ends\)")
        st = json.loads((out / "state.json").read_text())
        self.assertEqual(st["stages"]["umbilicus"]["status"], "failed")
        self.assertNotIn("running", st)
        # in this process: the server the run started is shut when the run returns
        started, real = [], mon.start

        def keep(*a, **k):
            m = real(*a, **k)
            started.append(m)
            return m
        parser = argparse.ArgumentParser()
        autopipe.build_parser(parser)
        args = parser.parse_args(["run", str(out), "--until", "umbilicus", "--monitor", "0"])
        with mock.patch.object(mon, "start", keep), mock.patch.dict(os.environ, self.env), \
                mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(autopipe.cmd_autopipe(args), 1)
        self.assertEqual(len(started), 1)
        # the server thread ends shortly after shutdown returns; on a loaded machine (tests in parallel) it was still
        # finishing when checked at once, so give it up to 5 s before calling it alive
        started[0].thread.join(5)
        self.assertFalse(started[0].thread.is_alive())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", started[0].port), timeout=2).close()


if __name__ == "__main__":
    unittest.main()
