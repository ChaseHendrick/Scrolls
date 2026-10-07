"""Reporting tests do not run inference or reinterpret historical metrics."""
import contextlib
import io
import json
import os
import runpy
import sys
import tempfile
from unittest.mock import patch
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3]))
spec = importlib.util.spec_from_file_location("job_status", HERE / "status.py")
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)


def row(reader, method="", controls=True):
    out = {"reader": reader, "settings": {"ensemble_method": method}, "auc_as_stored": 0.7, "hp_r": 0.02}
    if controls:
        out.update(auc_reversed=0.5, hp_r_reversed=0.0, auc_shuffled=0.5)
    return out


class StatusTests(unittest.TestCase):
    def test_baseline_only_is_partial_without_v8in_claim(self):
        result = status.build_status([row("ink_9um s42"), row("d9v2")])
        self.assertEqual(result["status"], "partial_results")
        self.assertEqual(result["recorded_rows"], ["ink_9um s42", "d9v2"])
        self.assertEqual(len(result["missing_rows"]), 9)
        self.assertIn("v8in", result["missing_rows"])
        self.assertEqual(result["inference_completion"], "unknown")

    def test_missing_control_fields_keep_rows_partial(self):
        result = status.build_status([row(reader, method, controls=False) for reader, method in status.EXPECTED])
        self.assertEqual(result["missing_rows"], [])
        self.assertEqual(result["status"], "partial_results")
        self.assertIn("v8in: auc_shuffled", result["missing_control_fields"])
        self.assertIn("d9v2: auc_reversed", result["missing_control_fields"])
        self.assertNotIn("v8in reversed: auc_reversed", result["missing_control_fields"])

    def test_recorded_rows_do_not_establish_job_completion(self):
        result = status.build_status([row(reader, method) for reader, method in status.EXPECTED])
        self.assertEqual(result["status"], "recorded_results")
        self.assertEqual(result["missing_rows"], [])
        self.assertEqual(result["missing_control_fields"], [])
        self.assertEqual(result["inference_completion"], "unknown")
        self.assertIn("provisional", result["control_comparability"])

    def test_unknown_or_duplicate_readers_cannot_fill_missing_rows(self):
        result = status.build_status([row("v8in + d9v2", "mean"), row("v8in + d9v2", "mean"), row("other")])
        self.assertEqual(result["recorded_rows"], ["v8in + d9v2 (mean)"])
        self.assertIn("v8in + d9v2 (rank)", result["missing_rows"])


class ScorerStatusTests(unittest.TestCase):
    def run_scorer(self, fail=False):
        from kit import auc, hpscore
        reports = {name: (HERE / name).read_bytes() for name in ("results.json", "status.json")}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                maps = Path(tmp) / "job-v8in-ag896" / "maps"
                maps.mkdir(parents=True)
                for name in ("ink9um_s42.tif", "ink9um_s42_reverse.tif", "d9v2.tif", "d9v2_reverse.tif"):
                    (maps / name).write_bytes(b"synthetic map")
                a = {"forward": {"auc": 0.7, "ink_px": 20}, "control": {"auc": 0.5}}
                h = {"forward": {"hp_r": 0.02, "null_max_abs": 0.01}, "control": {"hp_r": 0.0}}
                captured = io.StringIO()
                with patch.dict(os.environ, {"W": tmp}), patch.object(sys, "path", [str(HERE)] + sys.path), patch.object(auc, "score_files", side_effect=RuntimeError("scoring failed") if fail else None, return_value=a), patch.object(hpscore, "score_files", return_value=h), contextlib.redirect_stdout(captured):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, "scoring failed"):
                            runpy.run_path(str(HERE / "score.py"), run_name="__main__")
                    else:
                        runpy.run_path(str(HERE / "score.py"), run_name="__main__")
                if fail:
                    self.assertEqual({name: (HERE / name).read_bytes() for name in reports}, reports)
                else:
                    result = json.loads((HERE / "status.json").read_text())
                    self.assertEqual(result["status"], "partial_results")
                    self.assertEqual(result["recorded_rows"], ["ink_9um s42", "d9v2"])
                    self.assertEqual(len(json.loads((HERE / "results.json").read_text())), 2)
                    self.assertIn("Missing scored rows: v8in", captured.getvalue())
                    self.assertIn("inference completion: unknown", captured.getvalue())
        finally:
            for name, content in reports.items():
                (HERE / name).write_bytes(content)

    def test_scorer_writes_and_prints_partial_status(self):
        self.run_scorer()

    def test_failed_score_preserves_previous_reports(self):
        self.run_scorer(fail=True)


if __name__ == "__main__":
    unittest.main()
