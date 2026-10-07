"""Bounded score provenance and partial coverage tests; no inference or downloads."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import controls
spec = importlib.util.spec_from_file_location("job_results", HERE / "make_results.py")
results = importlib.util.module_from_spec(spec)
spec.loader.exec_module(results)


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scores = Path(self.tmp.name)

    def pair(self, name, reverse_stride=None, has_control=True, metadata=True):
        auc = {"forward": {"auc": 0.8319, "ink_px": 67060}}
        hp = {"forward": {"hp_r": 0.0248, "null_max_abs": 0.0102}}
        if has_control:
            auc["control"] = {"auc": 0.6572}
            hp["control"] = {"hp_r": 0.003}
        for prefix, value in (("auc", auc), ("hp", hp)):
            (self.scores / f"{prefix}_{name}.json").write_text(json.dumps(value))
        if metadata:
            (self.scores / f"control_{name}.json").write_text(json.dumps(
                {"reverse_stride": reverse_stride, "control_map": "selected.npy" if has_control else None}))

    def test_actual_archived_baseline_is_partial_and_unchanged(self):
        historical = [HERE / "results.json", *sorted((HERE / "scores").glob("*.json"))]
        before = {path: path.read_bytes() for path in historical}
        rows, status = results.collect(HERE / "scores")
        self.assertEqual([row["map"] for row in rows], ["d9v2"])
        self.assertEqual(status["status"], "partial")
        self.assertEqual(status["missing_maps"], ["v8in1447_s42", "v8in1447_s21",
            "ens_v8in1447_d9v2_mean", "ens_v8in1447_d9v2_rank"])
        self.assertEqual(len(status["primary_missing_maps"]), 3)
        self.assertEqual((rows[0]["auc_as_stored"], rows[0]["auc_reversed"]), (0.8319, 0.6572))
        self.assertEqual({path: path.read_bytes() for path in historical}, before)

    def test_matched_provisional_missing_and_unverified(self):
        for stride, available, metadata, expected in [
            (42, True, True, "matched"), (64, True, True, "provisional_stride_mismatch"),
            (42, False, True, "missing"), (None, True, False, "provisional_unverified")]:
            with self.subTest(expected=expected):
                for path in self.scores.iterdir():
                    path.unlink()
                self.pair("v8in1447_s42", stride, available, metadata)
                rows, status = results.collect(self.scores)
                self.assertEqual(rows[0]["control_status"], expected)
                self.assertEqual(rows[0]["auc_reversed"], 0.6572 if available else None)
                self.assertEqual(status["unmatched_control_maps"], [] if expected == "matched" else ["v8in1447_s42"])

    def test_primary_complete_with_optional_s21_missing(self):
        for name in results.MAPS:
            if name != "v8in1447_s21":
                self.pair(name, 42)
        rows, status = results.collect(self.scores)
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["missing_maps"], ["v8in1447_s21"])
        for row in rows:
            self.assertEqual(row["control_status"], "matched")
            if row["reader"] == "v8in-1447 + d9v2":
                self.assertEqual(row["settings"]["maps"], ["v8in1447_s42", "d9v2"])

    def test_s21_is_provisional_and_missing_ensemble_member_is_missing(self):
        self.pair("v8in1447_s21", 42)
        self.pair("ens_v8in1447_d9v2_mean", 42, has_control=False)
        rows, status = results.collect(self.scores)
        by_map = {row["map"]: row for row in rows}
        self.assertEqual(by_map["v8in1447_s21"]["control_status"], "provisional_stride_mismatch")
        self.assertEqual(by_map["ens_v8in1447_d9v2_mean"]["control_status"], "missing")
        self.assertEqual(status["status"], "partial")

    def test_single_score_file_does_not_mark_row_completed(self):
        self.pair("d9v2")
        (self.scores / "hp_d9v2.json").unlink()
        rows, status = results.collect(self.scores)
        self.assertEqual(rows, [])
        self.assertIn("d9v2", status["primary_missing_maps"])

    def test_reverse_selection_cli_prefers_matched_and_preserves_legacy(self):
        legacy = self.scores / "v8in1447_s64_reverse.npy"
        matched = self.scores / "v8in1447_s42_reverse.npy"
        def choose():
            return subprocess.check_output([sys.executable, str(HERE / "controls.py"), str(self.scores)], text=True).splitlines()
        self.assertEqual(choose(), ["", ""])
        legacy.write_bytes(b"historical")
        self.assertEqual(choose(), [str(legacy), "64"])
        self.assertEqual(controls.control_status(42, 64, True), "provisional_stride_mismatch")
        matched.write_bytes(b"matched")
        self.assertEqual(choose(), [str(matched), "42"])
        self.assertEqual(legacy.read_bytes(), b"historical")

    def test_collection_cli_leaves_archive_untouched_and_reports_partial(self):
        before = (HERE / "results.json").read_bytes()
        output, status = self.scores / "results.json", self.scores / "status.json"
        subprocess.run([sys.executable, str(HERE / "make_results.py"), "--scores", str(HERE / "scores"),
                        "--output", str(output), "--status", str(status)], check=True, capture_output=True)
        self.assertEqual(json.loads(status.read_text())["status"], "partial")
        self.assertEqual([row["map"] for row in json.loads(output.read_text())], ["d9v2"])
        self.assertEqual((HERE / "results.json").read_bytes(), before)
        self.assertFalse(output.with_name(output.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
