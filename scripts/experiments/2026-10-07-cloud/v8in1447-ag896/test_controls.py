"""Control selection and scorer reporting tests; no model, labels, or downloads."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3]))
spec = importlib.util.spec_from_file_location("job_controls", HERE / "controls.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReverseSelectionTests(unittest.TestCase):
    def test_matching_preferred_without_relabelling_legacy(self):
        available = {"new_s42": "42.npy", "old_s64": "64.npy"}
        name, path, stride, status, note = module.choose_reverse(available.get, "new_s42", "old_s64")
        self.assertEqual((name, path, stride, status), ("new_s42", "42.npy", 42, "matched"))
        self.assertIn("both use stride 42", note)
        self.assertEqual(available["old_s64"], "64.npy")

    def test_legacy_is_provisional_and_missing_is_explicit(self):
        selected = module.choose_reverse({"old_s64": "64.npy"}.get, "new_s42", "old_s64")
        self.assertEqual(selected[:4], ("old_s64", "64.npy", 64, "provisional_stride_mismatch"))
        self.assertIn("confounded", selected[4])
        selected = module.choose_reverse({}.get, "new_s42", "old_s64")
        self.assertEqual(selected[:4], (None, None, None, "missing"))


class ScorerReportingTests(unittest.TestCase):
    def check_scorer(self, matched, legacy=True, d9_reverse=True):
        from kit import auc, ensemble, hpscore
        w00 = HERE.name.endswith("w00")
        forward = "v8in1447_s42.npy" if w00 else "v8in1447_fwd_s42.npy"
        new = "v8in1447_s42_reverse.npy" if w00 else "v8in1447_rev_s42.npy"
        old = "v8in1447_s64_reverse.npy" if w00 else "v8in1447_rev_s64.npy"
        score_calls, ensemble_calls = [], []

        def score(fwd, labels, mask, control=None, **kw):
            score_calls.append((str(fwd), str(control) if control else None))
            out = {"forward": {"auc": 0.8123, "ink_px": 10}}
            if control:
                out["control"] = {"auc": 0.5123}
            return out

        def hp(fwd, labels, mask, voxel, control=None, **kw):
            out = {"forward": {"hp_r": 0.02, "null_max_abs": 0.01}}
            if control:
                out["control"] = {"hp_r": 0.005}
            return out

        def ens(out, members, method):
            ensemble_calls.append((str(out), list(map(str, members)), method))
            Path(out).write_bytes(b"synthetic ensemble")

        result_path = HERE / "results.json"
        before = result_path.read_bytes() if result_path.exists() else None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                job = root / "job"
                maps = job / "maps"
                maps.mkdir(parents=True)
                for name in [forward, "d9v2.tif"] + ([new] if matched else []) + ([old] if legacy else []) + (["d9v2_reverse.tif"] if d9_reverse else []):
                    (maps / name).write_bytes(b"historical or synthetic map")
                argv = [str(HERE / "score.py"), str(job)]
                captured = io.StringIO()
                with patch.dict(os.environ, {"W": str(root)}), patch.object(sys, "argv", argv), patch.object(sys, "path", [str(HERE)] + sys.path), patch.object(auc, "score_files", side_effect=score), patch.object(hpscore, "score_files", side_effect=hp), patch.object(ensemble, "ensemble_files", side_effect=ens), contextlib.redirect_stdout(captured):
                    runpy.run_path(str(HERE / "score.py"), run_name="__main__")
                rows = json.loads(result_path.read_text() if w00 else captured.getvalue())
                target = [r for r in rows if r["reader"].startswith("v8in-1447")]
                self.assertEqual(len(target), 3)
                expected_status = "matched" if matched else ("provisional_stride_mismatch" if legacy else "missing")
                self.assertEqual(target[0]["control_status"], expected_status)
                stride_key = "reverse_stride" if w00 else "control stride"
                self.assertEqual(target[0]["settings"][stride_key], 42 if matched else (64 if legacy else None))
                selected = new if matched else old
                if matched or legacy:
                    self.assertEqual(target[0]["control_map"], selected)
                    self.assertEqual(target[0]["auc_reversed"], 0.5123)
                    self.assertTrue(any(Path(c).name == selected for _, c in score_calls if c))
                else:
                    self.assertNotIn("auc_reversed", target[0])
                for row in target[1:]:
                    self.assertEqual(row["control_status"], expected_status if d9_reverse else "missing")
                    self.assertEqual(row["settings"]["reverse_stride"], 42 if matched else (64 if legacy else None))
                    if (matched or legacy) and d9_reverse:
                        self.assertIn("_reverse_s42" if matched else "_reverse", row["control_map"])
                reverse_calls = [(out, members, method) for out, members, method in ensemble_calls if "reverse" in out]
                if (matched or legacy) and d9_reverse:
                    self.assertEqual({method for _, _, method in reverse_calls}, {"mean", "rank"})
                    self.assertTrue(all(Path(members[0]).name == selected for _, members, _ in reverse_calls))
                    if matched:
                        self.assertTrue(all("_reverse_s42" in out for out, _, _ in reverse_calls))
                else:
                    self.assertEqual(reverse_calls, [])
                if legacy:
                    self.assertEqual((maps / old).read_bytes(), b"historical or synthetic map")
        finally:
            if before is None:
                result_path.unlink(missing_ok=True)
            else:
                result_path.write_bytes(before)

    def test_new_control_is_selected_for_model_and_ensembles(self):
        self.check_scorer(matched=True)

    def test_legacy_control_remains_provisional(self):
        self.check_scorer(matched=False)

    def test_missing_control_has_no_reverse_metrics(self):
        self.check_scorer(matched=False, legacy=False)

    def test_missing_ensemble_member_cannot_claim_matched_control(self):
        self.check_scorer(matched=True, d9_reverse=False)


if __name__ == "__main__":
    unittest.main()
