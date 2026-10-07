"""Small regression checks for calibration, coverage and incomplete labels.

From the repository root:
  python -m unittest discover -s scripts/experiments/2026-10-07-cloud/thresholds -p 'test_*.py' -v
No maps, volumes or model checkpoints are fetched or inferred.
"""
import json
from pathlib import Path
import unittest
from unittest import mock

import numpy as np

import analyze


def data(F, ink, sup, reverse=None, vox=9.366):
    return {"F": F, "R": np.zeros_like(F) if reverse is None else reverse,
            "ink": ink, "sup": sup, "valid": np.ones(F.shape, dtype=bool),
            "area_cm2": 1.0, "vox": vox}


class CalibrationTests(unittest.TestCase):
    def test_part1_holds_out_the_sheet_and_uses_the_fixed_primary_trace(self):
        # The duplicate trace has very different scores; pooling it changes the threshold.
        records = {}
        for segment, value in [("0841-w00", 51), ("0841-ag896", 230), ("0841-ag405", 153)]:
            F = np.full((2, 2), value, dtype=np.uint8)
            records[segment] = data(F, np.ones_like(F, dtype=bool), np.ones_like(F, dtype=bool))
        with mock.patch.object(analyze, "load", side_effect=lambda work, seg: records[seg]), \
                mock.patch.object(analyze, "mm_rule", return_value={}):
            result = analyze.part1("unused")
        rows = {row["held_out"]: row for row in result["loo"]}
        for seg in ["0841-w00", "0841-ag896"]:
            self.assertEqual(rows[seg]["calibrated_on"], ["0841-ag405"])
            self.assertEqual(rows[seg]["threshold"], 0.6)
            self.assertEqual(rows[seg]["threshold_uint8"], 153)
        self.assertEqual(rows["0841-ag405"]["calibrated_on"], ["0841-w00"])
        self.assertEqual(rows["0841-ag405"]["threshold"], 0.2)
        self.assertEqual(rows["0841-ag405"]["threshold_uint8"], 51)
        self.assertEqual(result["calibration_unit"], "independent sheet")

    def test_split_rejects_a_duplicate_trace_of_the_held_out_sheet(self):
        with mock.patch.dict(analyze.CALIBRATION_TRACES, {"0841-w00": ("0841-ag896",)}):
            with self.assertRaisesRegex(ValueError, "held-out sheet"):
                analyze.calibration_traces("0841-w00")

    def test_split_rejects_pooling_the_selection_sheet_twice(self):
        with mock.patch.dict(analyze.CALIBRATION_TRACES, {"0841-ag405": ("0841-w00", "0841-ag896")}):
            with self.assertRaisesRegex(ValueError, "duplicate traces"):
                analyze.calibration_traces("0841-ag405")

    def test_uint8_cutoff_matches_float32_comparison_for_all_bins(self):
        grid = np.arange(256, dtype=np.float32) / 255
        for value in range(256):
            self.assertEqual(analyze.threshold_uint8(float(grid[value])), value)
        self.assertEqual(analyze.threshold_uint8(0.7843), 200)
        midpoint = float(np.median(grid[51:53]))
        self.assertEqual(analyze.threshold_uint8(midpoint), 52)


class CoverageTests(unittest.TestCase):
    def test_remainder_footprints_cover_each_pixel_once(self):
        counts = np.zeros((5, 7), dtype=int)
        for sl in analyze.site_slices(counts.shape, (2, 3)):
            counts[sl] += 1
        np.testing.assert_array_equal(counts, np.ones_like(counts))
        w00 = list(analyze.site_slices((4220, 4760), (1281, 1602)))
        self.assertEqual(len(w00), 12)
        self.assertEqual(sum((y.stop-y.start) * (x.stop-x.start) for y, x in w00), 4220 * 4760)

    def test_padded_boundary_has_no_artificial_evidence_and_reports_coverage(self):
        F = np.zeros((5, 7), dtype=np.uint8)
        F[-1, -1] = 255  # This actual boundary pixel was dropped by the historical tiler.
        d = data(F, np.zeros_like(F, dtype=bool), np.zeros_like(F, dtype=bool), vox=3000)
        seen = []

        def score(prob, valid, px_mm):
            self.assertEqual(prob.shape, (4, 5))
            self.assertEqual(valid.shape, (4, 5))
            self.assertTrue(np.all(prob[~valid] == 0))
            seen.append(int((prob[valid] > 0.5).sum()))
            return {"best_2mm": float((prob[valid] > 0.5).any()), "frac": 0.0}

        with mock.patch.object(analyze, "best2mm", side_effect=score), \
                mock.patch.object(analyze, "band_score", return_value=0), \
                mock.patch.object(analyze, "slab_fraction", return_value=0):
            result = analyze.tauil_sites(d, np.ones_like(F))
        self.assertEqual(result["sites"], 4)
        self.assertEqual(result["coverage"]["covered_canvas_px"], 35)
        self.assertEqual(result["coverage"]["covered_valid_px"], 35)
        self.assertEqual(result["coverage"]["valid_fraction"], 1)
        self.assertEqual(sum(seen), 1)
        last = result["site_rows"][-1]
        self.assertEqual(last["shape_px"], [1, 2])
        self.assertEqual(last["padded_px"], 18)
        self.assertEqual(last["valid_frac"], 0.1)
        self.assertEqual(last["fwd"]["best_2mm"], 1)

    def test_low_valid_sites_are_accounted_for(self):
        F = np.zeros((5, 7), dtype=np.uint8)
        d = data(F, np.zeros_like(F, dtype=bool), np.zeros_like(F, dtype=bool), vox=3000)
        mid = np.zeros_like(F)
        mid[0, 0] = 1  # Exactly 5% of its nominal site: include it.
        with mock.patch.object(analyze, "best2mm", return_value={"best_2mm": 0, "frac": 0}), \
                mock.patch.object(analyze, "band_score", return_value=0), \
                mock.patch.object(analyze, "slab_fraction", return_value=0):
            result = analyze.tauil_sites(d, mid)
        coverage = result["coverage"]
        self.assertEqual(result["sites"], 1)
        self.assertEqual(coverage["skipped_sites_below_5pct_valid"], 3)
        self.assertEqual(coverage["covered_canvas_px"] + coverage["skipped_canvas_px"], 35)
        self.assertEqual(coverage["covered_valid_px"] + coverage["skipped_valid_px"], 1)
        self.assertEqual(coverage["valid_fraction"], 1)

    def test_empty_surface_has_undefined_valid_coverage(self):
        F = np.zeros((2, 2), dtype=np.uint8)
        d = data(F, np.zeros_like(F, dtype=bool), np.zeros_like(F, dtype=bool), vox=3000)
        result = analyze.tauil_sites(d, F)
        self.assertEqual(result["sites"], 0)
        self.assertEqual(result["coverage"]["covered_valid_px"], 0)
        self.assertIsNone(result["coverage"]["valid_fraction"])


class LabelEvidenceTests(unittest.TestCase):
    def test_unknown_is_not_background_and_precision_is_undefined_without_labels(self):
        partial = analyze.component_label_evidence(100, 8, 10)
        self.assertEqual(partial["ink_frac"], 0.08)
        self.assertEqual(partial["sup_frac"], 0.1)
        self.assertEqual(partial["known_label_precision"], 0.8)
        self.assertEqual(partial["supervised_background_px"], 2)
        self.assertEqual(partial["unknown_px"], 90)
        unknown = analyze.component_label_evidence(100, 0, 0)
        self.assertIsNone(unknown["known_label_precision"])
        self.assertEqual(unknown["supervised_background_px"], 0)
        self.assertEqual(unknown["unknown_px"], 100)

    def test_three_candidate_rules_keep_historical_counts_and_add_label_evidence(self):
        # The component is mostly unknown; of the 100 known pixels, 80 are ink.
        F = np.zeros((260, 260), dtype=np.uint8)
        F[64:184, 64:184] = 255
        sup = np.zeros_like(F, dtype=bool)
        sup[80:85, 80:100] = True
        ink = np.zeros_like(sup)
        ink[80:84, 80:100] = True
        d = data(F, ink, sup)
        summaries = [analyze.mm_rule(d, 0.7843)["forward"],
                     analyze.bnleft_rule(d, np.ones_like(F))["forward"],
                     analyze.nerln_rule(d)["forward"]]
        for summary in summaries:
            self.assertEqual(summary["candidates"], 1)
            self.assertEqual(summary["mostly_on_ink"], 0)
            self.assertEqual(summary["candidates_with_partial_supervision"], 1)
            evidence = summary["label_evidence"][0]
            self.assertEqual(evidence["known_label_precision"], 0.8)
            self.assertEqual(evidence["supervised_background_px"], 20)
            self.assertEqual(evidence["unknown_px"], 14300)
            self.assertAlmostEqual(evidence["sup_frac"], 100 / 14400)


class HistoricalRecordsTests(unittest.TestCase):
    def test_paired_counts_come_from_unchanged_saved_windows(self):
        saved = json.loads((Path(__file__).parent / "part3_w00.json").read_text())["0841-w00"]
        for area, count, auc_wins, row_wins in [("2.0", 114, 111, 52), ("4.0", 152, 152, 58)]:
            rows = [r for r in saved[area]["rows"] if "auc_fwd" in r and "auc_rev" in r
                    and r["row_fwd"] is not None and r["row_rev"] is not None]
            self.assertEqual(len(rows), count)
            self.assertEqual(sum(r["auc_fwd"] > r["auc_rev"] for r in rows), auc_wins)
            self.assertEqual(sum(r["row_fwd"] > r["row_rev"] for r in rows), row_wins)


if __name__ == "__main__":
    unittest.main()
