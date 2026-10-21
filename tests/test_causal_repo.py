"""kit causal on this repository itself: the check rule applies to everything added after the causal cutover
(docs/causal/baseline.json, made 2026-10-21), while the gaps that existed then sit in the baseline, which may only
shrink. INITIAL_SHA256 and BASELINE_MAX pin that baseline: a change that grows it fails here (rule E11), and a
deliberate rebuild (`python -m kit causal ratchet --repin --reason TEXT`) changes them in the same commit.

The test also records the gap counts (printed with -v) without failing on old entries.
"""

import unittest
from pathlib import Path

from kit import causal

ROOT = Path(__file__).resolve().parent.parent
INITIAL_SHA256 = "938b1e0acdab80e2f6b2d7b48bad1710bf6c8324d33c6e87babfe5a424278d23"
BASELINE_MAX = 207


class CausalRepoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = causal.load(ROOT)

    def test_check_passes_for_new_entries(self):
        rep = causal.check(ROOT, hash_pins=False, graph=self.graph, pinned_sha=INITIAL_SHA256,
                           pinned_max=BASELINE_MAX)
        errors = [f"{f['rule']} {f['where']}: {f['text']}" for f in rep["findings"] if f["level"] == "error"]
        self.assertEqual(errors, [], "kit causal check found errors; run `python -m kit causal check` and fix "
                                     "each line (docs/causal/README.md)")

    def test_gap_counts_are_recorded(self):
        counts = causal.gaps(self.graph)["counts"]
        self.assertEqual(counts["new_pairs"], 0)
        self.assertLessEqual(counts["old_pairs"], BASELINE_MAX)
        print(f"\nkit causal gaps: {counts['pairs']} pairs over {counts['nodes']} nodes; by kind "
              f"{counts['by_kind']}; by gap {counts['by_gap']}")


if __name__ == "__main__":
    unittest.main()
