"""kit/qareasons.py and AutoPipeline's qa failure records (kit/autopipe.py Run.s_qa, trace_entries,
check_settings), on synthetic records only: no scan, no label, no mesh."""

import contextlib
import io
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kit import autopipe, qareasons as Q  # noqa: E402

QA = {"windows": 5, "min_valid_fraction": 0.2, "require_seated": "all", "max_selfcross": 0, "windaudit": "auto",
      "validity": True}


def rejected_rec():
    """A qa record as Run.qa_one writes it, rejected for self-intersections, seating and orientation."""
    return {"data_term": "normal grids",
            "check_surface": {"verdict": "look closer", "grid": {"valid_fraction": 0.55},
                              "selfcross": {"clean": False, "transverse": 2134}},
            "seating": {"verdict": "partly seated", "seated_windows": "4 of 5"},
            "orientation": {"checked": True, "normal": {"outward_share": 0.083, "vote": "inward",
                                                        "confidence": "clear",
                                                        "thresholds": {"clear": 0.8, "weak": 0.65}}},
            "validity": {"worst": "info", "findings": []},
            "windaudit": {"error": "spans 0.55 of a turn", "audited": False, "pitch_fit": "span"},
            "accepted": False,
            "reasons": ["self-intersections: 2134", "seating: partly seated",
                        "orientation: +N points toward the center (standard mirrored)"],
            "warnings": [], "failure": {"kind": "ours"}}


class ChecksTest(unittest.TestCase):
    def test_each_check_has_its_value_threshold_and_verdict(self):
        rows = {c["check"]: c for c in Q.checks(rejected_rec(), QA)}
        self.assertEqual(list(rows), ["data_term", "valid_fraction", "selfcross", "seating", "orientation",
                                      "validity", "windaudit"])
        self.assertTrue(rows["valid_fraction"]["passed"])
        self.assertEqual(rows["valid_fraction"]["measured"], {"valid_fraction": 0.55})
        self.assertEqual(rows["valid_fraction"]["threshold"], {"min_valid_fraction": 0.2})
        self.assertFalse(rows["selfcross"]["passed"])
        self.assertEqual(rows["selfcross"]["measured"]["transverse"], 2134)
        self.assertEqual(rows["selfcross"]["threshold"], {"max_transverse": 0})
        self.assertEqual(rows["seating"]["measured"], {"verdict": "partly seated", "seated_windows": 4,
                                                       "windows": 5})
        self.assertEqual(rows["seating"]["threshold"], {"require_seated": "all"})
        self.assertFalse(rows["orientation"]["passed"])
        self.assertEqual(rows["orientation"]["measured"]["outward_share"], 0.083)
        self.assertTrue(rows["windaudit"]["passed"])        # a span too short to fit is not audited, not failed
        self.assertTrue(rows["validity"]["passed"])

    def test_failed_checks_follow_the_reasons_alone(self):
        # a record from before 22 Oct 2026 or a marker that kept only the reasons still names its checks
        failed = Q.failed_checks({"reasons": ["valid fraction 0.1 is under 0.2", "winding audit: 2 full-turn "
                                              "fusions, 0 broad (a sheet switch or merger)", "something new"]})
        self.assertEqual([c["check"] for c in failed], ["valid_fraction", "windaudit", "other"])

    def test_an_unmeasured_reason_is_marked(self):
        rec = rejected_rec()
        rec["check_surface"]["selfcross"] = {"exit": 3, "error": "no report"}
        rec["reasons"] = ["self-intersections: not measured (vc_tifxyz_selfcross exited 3 with no readable report)"]
        rec["unmeasured"] = list(rec["reasons"])
        sc = [c for c in Q.checks(rec, QA) if c["check"] == "selfcross"][0]
        self.assertTrue(sc["unmeasured"])
        self.assertIsNone(sc["measured"]["transverse"])
        self.assertEqual(sc["measured"]["exit"], 3)

    def test_qa_failure_keeps_the_exception_and_the_repair(self):
        rec = {"accepted": False, "reasons": ["check failed: boom"], "failure": {"kind": "infrastructure"},
               "exception": {"type": "ValueError", "message": "boom"}}
        f = Q.qa_failure(rec, QA)
        self.assertEqual(f["kind"], "infrastructure")
        self.assertEqual(f["exception"], {"type": "ValueError", "message": "boom"})
        self.assertEqual([c["check"] for c in f["checks"]], ["check_error"])
        rec = {**rejected_rec(), "repair": {"method": "barrier", "done": True, "taken": False, "area_share": 0.31,
                                            "why": "the cut keeps 0.310 of the area, under 0.5", "out": "/x"}}
        f = Q.qa_failure(rec, QA)
        self.assertEqual(f["repair"]["taken"], False)
        self.assertNotIn("out", f["repair"])
        self.assertIsNone(Q.qa_failure({"accepted": True}))

    def test_counts_and_log_line(self):
        a = Q.qa_failure(rejected_rec(), QA)
        b = {"stage": "qa", "kind": "infrastructure", "checks": [{"check": "check_error", "passed": False}],
             "exception": {"type": "OSError", "message": "gone"}}
        c = {"stage": "trace", "kind": "not_traced", "reason": "never planned"}
        got = Q.counts([a, None, b, c])
        self.assertEqual(got["traces"], 4)
        self.assertEqual(got["rejected"], 3)
        self.assertEqual(got["by_kind"], {"infrastructure": 1, "not_traced": 1, "ours": 1})
        self.assertEqual(got["by_check"], {"selfcross": 1, "seating": 1, "orientation": 1, "check_error": 1})
        self.assertEqual(got["exceptions"], {"OSError": 1})
        line = Q.log_line("t00", a)
        self.assertTrue(line.startswith("qa t00: rejected at qa, kind ours: selfcross (transverse=2134; "
                                        "limit max_transverse=0)"))
        self.assertEqual(Q.log_line("t01", None), "qa t01: accepted")
        self.assertIn("never planned", Q.log_line("t02", c))

    def test_scalars_leave_out_places_and_coordinates(self):
        doc = {"seed": [1, 2, 3], "rows": [{"surface": "/a", "traced": "/b", "area_cm2": 2.0,
                                           "grid": {"bbox_xyz": [[0, 0, 0]], "valid_fraction": 0.5}}]}
        self.assertEqual(Q.scalars(doc), {"rows": [{"area_cm2": 2.0, "grid": {"valid_fraction": 0.5}}]})


class CommandTest(unittest.TestCase):
    def test_without_the_stage_g_reader_the_command_has_only_state(self):
        # the public AutoPipeline release ships this module without its optional extra reader
        with mock.patch.object(Q, "_stageg", return_value=None), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                Q.main(["stage-g", "results.json", "--markers", "m"])


class AutoPipelineQaTest(unittest.TestCase):
    def run_with(self, qa_one, surfaces=("t00", "t01")):
        run = autopipe.Run.__new__(autopipe.Run)
        run.s = autopipe._merge(autopipe.DEFAULTS, {"qa": {"min_valid_fraction": 0.2}})
        run.state = {"surfaces": {sid: {"surface": f"/nowhere/{sid}"} for sid in surfaces}, "stages": {},
                     "planned_traces": [{"sid": sid, "seed_index": n, "repeat": 0}
                                        for n, sid in enumerate(surfaces)]}
        run.lines = []
        run.log = run.lines.append
        run.save = lambda: None
        run.qa_one = qa_one
        return run

    def test_an_exception_is_kept_on_its_trace_and_counted(self):
        def qa_one(sid, s):
            if sid == "t00":
                raise ValueError("boom")
            return {**rejected_rec(), "checks": Q.checks(rejected_rec(), QA)}
        run = self.run_with(qa_one)
        with self.assertRaises(autopipe.AutoError) as cm:
            run.s_qa()
        detail = cm.exception.detail
        self.assertEqual(detail["failure_counts"]["by_kind"], {"infrastructure": 1, "ours": 1})
        self.assertEqual(detail["failure_counts"]["exceptions"], {"ValueError": 1})
        q0 = run.state["surfaces"]["t00"]["qa"]
        self.assertEqual(q0["exception"], {"type": "ValueError", "message": "boom"})
        self.assertEqual(q0["failure"]["kind"], "infrastructure")
        self.assertEqual(len(run.lines), 2)
        self.assertTrue(run.lines[0].startswith("qa t00: rejected at qa, kind infrastructure"))
        self.assertIn("selfcross (transverse=2134; limit max_transverse=0)", run.lines[1])
        # trace_entries carries the failed checks and the exception into every reader of state.json
        entries = {e["sid"]: e for e in autopipe.trace_entries(run.state)}
        self.assertEqual(entries["t00"]["failure"]["exception"]["type"], "ValueError")
        self.assertEqual([c["check"] for c in entries["t01"]["failure"]["checks"]],
                         ["selfcross", "seating", "orientation"])

    def test_a_rerun_checks_again_only_the_trace_that_raised(self):
        calls = []

        def broken(sid, s):
            calls.append(sid)
            raise OSError("relay down")
        run = self.run_with(broken)
        with self.assertRaises(autopipe.AutoError):
            run.s_qa()

        def fixed(sid, s):
            calls.append(sid)
            return {"accepted": True, "reasons": [], "warnings": [], "checks": []}
        run.qa_one = fixed
        run.state["surfaces"]["t01"]["qa"] = {**rejected_rec()}
        run.state["surfaces"]["t01"]["accepted"] = False
        rec = run.s_qa()
        self.assertEqual(calls, ["t00", "t01", "t00"])
        self.assertEqual(rec["accepted"], ["t00"])
        self.assertEqual(rec["failure_counts"]["by_kind"], {"ours": 1})

    def test_check_settings_refuses_a_dotted_section_setting(self):
        for key, value in (("trace.repeats", 2), ("qa.repair", True), ("qa.crop", True)):
            s = autopipe._merge(autopipe.DEFAULTS, {key: value})
            with self.assertRaises(autopipe.AutoError) as cm:
                autopipe.check_settings(s, "PHercTest")
            self.assertIn("no stage reads", str(cm.exception))
        s = autopipe._merge(autopipe.DEFAULTS, {"trace": {"repeats": 2}, "qa": {"repair": True}})
        autopipe.check_settings(s, "PHercTest")
        self.assertEqual(s["trace"]["repeats"], 2)
        self.assertEqual(s["qa"]["repair"]["min_area_share"], 0.5)


if __name__ == "__main__":
    unittest.main()
