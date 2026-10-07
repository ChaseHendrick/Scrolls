"""Descriptive synthesis must not invent uncertainty or overwrite history."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import patch


PATH = Path(__file__).resolve().parents[1] / "scripts/experiments/2026-10-07-grok-laneA/synth.py"
SPEC = importlib.util.spec_from_file_location("grok_synthesis", PATH)
SYNTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNTH)


class SynthesisTests(unittest.TestCase):
    def test_small_difference_is_not_an_equivalence_or_null_claim(self):
        result = SYNTH.describe_difference({"auc_as_stored": .8061}, {"auc_as_stored": .8062})
        self.assertEqual(result["diff"], -.0001)
        self.assertEqual(result["status"], "descriptive_only_no_paired_uncertainty")
        self.assertNotIn("verdict", result)
        self.assertNotIn("half_width", result)

    def test_large_difference_cannot_invent_significance(self):
        result = SYNTH.describe_difference({"auc_as_stored": .99}, {"auc_as_stored": .1})
        self.assertEqual(result["diff"], .89)
        self.assertEqual(result["status"], "descriptive_only_no_paired_uncertainty")
        self.assertNotIn("verdict", result)

    def test_mismatched_control_status_survives_comparison(self):
        result = SYNTH.describe_difference(
            {"auc_as_stored": .9, "control_status": "provisional_stride_mismatch"},
            {"auc_as_stored": .8})
        self.assertEqual(result["left_control_status"], "provisional_stride_mismatch")
        self.assertEqual(result["right_control_status"], "not_recorded")

    def test_historical_output_alias_is_refused_before_loading(self):
        alias = PATH.parent / ".." / PATH.parent.name / "synth.json"
        with patch.object(SYNTH, "load", side_effect=AssertionError("must not load")):
            with self.assertRaisesRegex(ValueError, "Historical"):
                SYNTH.main(["--json", str(alias)])

    def test_load_uses_immutable_commit_not_branch_tip(self):
        with patch.object(SYNTH.subprocess, "run", return_value=types.SimpleNamespace(stdout="[]")) as run:
            self.assertEqual(SYNTH.load("tricks"), [])
        target = run.call_args.args[0][-1]
        self.assertTrue(target.startswith("a2951681ad1c590bdd4686c5340cfe1226887d60:"))
        self.assertNotIn("origin/", target)


if __name__ == "__main__":
    unittest.main()
