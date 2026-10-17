"""The daily routines workflow (.github/workflows/routines.yml): scheduled, read-only, no secrets, and it runs the
routines marked ci and the test suite. Public Scrolls only; Scrolls-private has no scheduled workflow."""

import re
import unittest
from pathlib import Path

from kit import routines

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "routines.yml"


class RoutinesWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_runs_daily_and_by_hand(self):
        self.assertRegex(self.text, r"(?m)^  schedule:\n    - cron: '\d+ \d+ \* \* \*'$")
        self.assertIn("workflow_dispatch:", self.text)

    def test_read_only_and_no_secrets(self):
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read\n\n")
        self.assertEqual(re.findall(r"(?m)^\s+[a-z-]+: write\b", self.text), [])
        self.assertNotIn("secrets.", self.text)
        self.assertNotIn("pull_request_target", self.text)
        self.assertIn("persist-credentials: false", self.text)

    def test_runs_the_ci_routines_strictly_and_the_tests(self):
        self.assertIn("python -m kit routines run --ci --strict", self.text)
        self.assertIn("python -m unittest discover -s tests", self.text)

    def test_some_routines_are_marked_ci_and_none_needs_state(self):
        ci = [r["name"] for r in routines.load(routines.REGISTRY) if r["ci"]]
        self.assertIn("prize-page", ci)
        # A runner keeps no state, so the watcher would report every volume as new each day.
        self.assertNotIn("autopipeline-watch", ci)


if __name__ == "__main__":
    unittest.main()
