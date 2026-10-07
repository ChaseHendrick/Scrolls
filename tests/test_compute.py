import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from kit import cli, compute


def record(run, start, end, chip="Apple M1 Pro"):
    return {"run": run, "digest": "a" * 64, "operator": {"name": "Op"}, "machine": {"chip": chip},
            "started_utc": start, "finished_utc": end}


class ComputeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "a" / "results").mkdir(parents=True)
        (self.root / "a" / "results" / "provenance.json").write_text(
            json.dumps(record("w045", "2026-10-07T08:00:00Z", "2026-10-07T08:30:00Z")))
        (self.root / "b").mkdir()
        (self.root / "b" / "provenance_s32.json").write_text(
            json.dumps(record("atlas", "2026-10-07T09:00:00Z", "2026-10-07T11:00:00Z")))
        (self.root / "b" / "other.json").write_text("{}")

    def tearDown(self):
        self.tmp.cleanup()

    def test_rows_and_hours(self):
        rows = compute.rows(compute.collect([self.root]), watts=30)
        self.assertEqual([r["run"] for r in rows], ["w045", "atlas"])
        self.assertEqual(rows[0]["hours"], 0.5)
        self.assertEqual(rows[1]["wh_estimate"], 60.0)

    def test_table_totals_and_marks_energy_as_estimate(self):
        text = compute.table(compute.rows(compute.collect([self.root]), watts=30), watts=30)
        self.assertIn("2 runs, 2.50 hours", text)
        self.assertIn("an estimate, not a measurement", text)
        header, rule = text.splitlines()[:2]
        self.assertEqual(header.count("|"), rule.count("|"))

    def test_cli(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["compute", str(self.root)]), 0)
        self.assertIn("| w045 |", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["compute", str(self.root / "missing")]), 2)


if __name__ == "__main__":
    unittest.main()
