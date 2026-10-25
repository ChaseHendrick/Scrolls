"""Offline failure and resume contracts for the released scroll2ink driver."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import scroll2ink as s2i


class Scroll2InkFailureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run = s2i.Run(Path(tmp.name) / "run", {
            "sample": "synthetic", "seed": [1, 2, 3], "model": "test-model", "check_windows": 3,
            "extend_rounds": 0,
        })
        # No test in this module may invoke an installed agent or network service.
        patch = mock.patch.object(s2i, "call", side_effect=AssertionError("unexpected agent call"))
        self.call = patch.start()
        self.addCleanup(patch.stop)

    def test_ink_refuses_missing_forward_or_reverse_map_even_on_exit_zero(self):
        for maps in ({"f": {"path": "forward.tif"}}, {"r": {"path": "reverse.tif"}}, {}):
            with self.subTest(maps=maps):
                self.call.side_effect = [(0, {"models": {"test-model": {}}}), (0, {"maps": maps})]
                with self.assertRaisesRegex(s2i.Scroll2InkError, "ink:"):
                    s2i.stage_ink(self.run, [], None, {}, {"zarr": "synthetic.zarr"})

    def test_failed_model_fetch_stops_before_inference(self):
        self.call.side_effect = [(0, {"models": {}}), (1, {"error": "checkpoint unavailable"})]
        with self.assertRaisesRegex(s2i.Scroll2InkError, "checkpoint unavailable"):
            s2i.stage_ink(self.run, [], None, {}, {"zarr": "synthetic.zarr"})
        self.assertEqual([c.args[1] for c in self.call.call_args_list], ["models", "fetch_model"])

    def test_prize_gate_refuses_before_any_model_or_agent_call(self):
        with self.assertRaisesRegex(s2i.Scroll2InkError, "needs a preregistered experiment"):
            s2i.stage_ink(self.run, [], None, {"eligible_prizes": ["synthetic-prize"]}, {"zarr": "unused"})
        self.call.assert_not_called()

    def test_inward_note_does_not_hide_another_failed_check(self):
        inward = s2i.INWARD + " (standard)"
        self.call.side_effect = None
        self.call.return_value = (0, {"verdict": "look closer", "findings": [inward, "seating: not seated"]})
        checked = s2i.check([], None, "surface", {"ct": "ct", "umbilicus": "axis.json"}, 3, "out")
        self.assertEqual(checked["verdict"], "look closer")
        self.assertEqual(checked["findings"], ["seating: not seated"])
        self.assertEqual(checked["notes"], [inward])
        with self.assertRaisesRegex(s2i.Scroll2InkError, "not seated"):
            s2i.stage_check(self.run, [], None, {"ct": "ct", "umbilicus": "axis.json"}, {"surface": "surface"})

    def test_inward_note_cannot_be_ignored_without_an_axis(self):
        self.call.side_effect = None
        self.call.return_value = (0, {"verdict": "look closer", "findings": [s2i.INWARD]})
        checked = s2i.check([], None, "surface", {"ct": "ct"}, 3, "out")
        self.assertEqual(checked["verdict"], "look closer")
        self.assertEqual(checked["findings"], [s2i.INWARD])
        self.assertEqual(checked["notes"], [])

    def test_disabled_extension_keeps_checked_surface_without_calling_agent(self):
        status, result = s2i.stage_extend(self.run, [], None, {}, {"surface": "checked", "area_cm2": 2.0})
        self.assertEqual(status, "skipped")
        self.assertEqual((result["surface"], result["area_cm2"]), ("checked", 2.0))
        self.call.assert_not_called()

    def test_failed_stage_is_saved_and_only_that_stage_retries(self):
        self.run.record("inputs", "done", 0, volume="synthetic", ct="ct", prediction="prediction")
        self.run.record("seed", "done", 0, ok=True)
        with mock.patch.object(s2i, "stage_trace", side_effect=s2i.Scroll2InkError("trace interrupted")) as trace:
            with self.assertRaisesRegex(s2i.Scroll2InkError, "trace interrupted"):
                s2i.execute(self.run, [], until="trace", say=lambda message: None)
            trace.assert_called_once()
        saved = json.loads(self.run.state_path.read_text())["stages"]
        self.assertEqual(saved["trace"]["status"], "failed")
        self.assertNotIn("check", saved)
        resumed = s2i.Run(self.run.dir)
        with mock.patch.object(s2i, "stage_trace", return_value={"surface": "recovered", "area_cm2": 1.0}) as trace:
            result = s2i.execute(resumed, [], until="trace", say=lambda message: None)
            trace.assert_called_once()
        self.assertEqual(result["stages"], {"inputs": "done", "seed": "done", "trace": "done"})
        self.assertNotIn("error", resumed.stage("trace"))
        self.call.assert_not_called()


class Scroll2InkAgentOutputTests(unittest.TestCase):
    def test_non_json_output_preserves_exit_code_and_bounds_diagnostics(self):
        output = "x" * 2500
        for exit_code in (0, 2):
            with self.subTest(exit_code=exit_code), mock.patch.object(
                s2i.subprocess, "run", return_value=subprocess.CompletedProcess([], exit_code, output)
            ):
                code, result = s2i.call(["synthetic-agent"], "trace", {})
            self.assertEqual(code, exit_code)
            self.assertEqual(result, {"error": "not JSON", "stdout_tail": output[-2000:]})

    def test_missing_executable_has_a_domain_error(self):
        with mock.patch.object(s2i.subprocess, "run", side_effect=FileNotFoundError("missing")):
            with self.assertRaisesRegex(s2i.Scroll2InkError, "could not start synthetic-agent"):
                s2i.call(["synthetic-agent"], "trace", {})


if __name__ == "__main__":
    unittest.main()
