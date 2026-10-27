"""kit/hfrows.py and `kit run hf-rows`: rows from Hugging Face's own bill, one per Job, the public ledger only
behind its flag. Offline: a fake GET stands in for the Hub."""
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from kit import cli, hfrows as HR, modalledger as ML

PUBLIC = "date_time_utc,purpose,flavor,minutes,billed_usd,notes\n"
PRIVATE = "date_time_utc,lane_branch,purpose,flavor,minutes,billed_usd,notes\n"
A, B, C, D = "6ae02a893fb22a235dd2568c", "6ae0322c3fb22a235dd25b0c", "6ae0322c3fb22a235dd25b10", "6ae0aaaa3fb22a235dd25b11"
BILL = {"usage": {"totalMinutes": 37, "usedMicroUsd": 6416822, "jobDetails": [
    {"jobId": A, "hardwareFlavor": "l4x1", "totalMinutes": 35, "totalCostMicroUsd": 466667,
     "startedAt": "2026-10-27T04:37:34.000Z", "completedAt": "2026-10-27T05:12:01.000Z"},
    {"jobId": B, "hardwareFlavor": "cpu-basic", "totalMinutes": 1, "totalCostMicroUsd": 167,
     "startedAt": "2026-10-27T05:10:11.000Z", "completedAt": "2026-10-27T05:10:27.000Z"},
    {"jobId": C, "hardwareFlavor": "h200", "totalMinutes": 1, "totalCostMicroUsd": 83333,
     "startedAt": "2026-10-27T05:11:00.000Z", "completedAt": "1970-01-01T00:00:00.000Z"}]}}


def fake_get(pages=None):
    calls = []

    def get(url, token):
        calls.append(url)
        if url.endswith(HR.USAGE):
            return BILL, None
        if url.endswith("/api/whoami-v2"):
            return {"name": "someone"}, None
        return (pages or {})[url]
    get.calls = calls
    return get


def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class HFRowsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.pub, self.priv = d / "hf-public.csv", d / "hf-private.csv"
        self.pub.write_text(PUBLIC, encoding="utf-8")
        self.priv.write_text(PRIVATE, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_row_per_finished_job_from_the_bill(self):
        rep = HR.add(self.priv, [A, B, C, D, A], "lasagna previews", "t", get=fake_get())
        self.assertEqual((rep["added"], rep["running"], rep["missing"]), ([A, B], [C], [D]))
        self.assertAlmostEqual(rep["usd"], 0.466834, places=6)
        r = rows(self.priv)
        self.assertEqual([x["flavor"] for x in r], ["l4x1", "cpu-basic"])
        self.assertEqual(r[0]["date_time_utc"], "2026-10-27 04:37 UTC")
        self.assertEqual((r[0]["minutes"], r[0]["billed_usd"]), ("35", "0.466667"))
        self.assertTrue(r[0]["notes"].endswith(f"autoledger {HR.KEY_PREFIX}{A}"))
        again = HR.add(self.priv, [A, B], "lasagna previews", "t", get=fake_get())
        self.assertEqual((again["added"], again["already"]), ([], [A, B]))
        self.assertEqual(len(rows(self.priv)), 2)

    def test_public_ledger_needs_the_flag_and_a_generic_purpose(self):
        with self.assertRaises(ML.LedgerRowError):
            HR.add(self.pub, [A], "lasagna previews on public scans", "t", get=fake_get())
        with self.assertRaises(ML.LedgerRowError):
            HR.add(self.pub, [A], "held-out check", "t", public=True, get=fake_get())
        with self.assertRaises(ML.LedgerRowError):     # the dry run refuses the same way
            HR.add(self.pub, [A], "target pass", "t", public=True, dry_run=True, get=fake_get())
        self.assertEqual(rows(self.pub), [])
        rep = HR.add(self.pub, [A], "lasagna previews on public scans", "t", public=True, get=fake_get())
        self.assertEqual(rep["added"], [A])
        self.assertEqual(rows(self.pub)[0]["purpose"], "lasagna previews on public scans")

    def test_dry_run_writes_nothing(self):
        rep = HR.add(self.priv, [A, B], "x", "t", dry_run=True, get=fake_get())
        self.assertEqual(rep["added"], [A, B])
        self.assertEqual(rows(self.priv), [])

    def test_inputs_are_checked(self):
        with self.assertRaises(HR.HFRowsError):
            HR.add(self.priv, ["not-an-id"], "x", "t", get=fake_get())
        with self.assertRaises(HR.HFRowsError):
            HR.add(self.priv, [A], "  ", "t", get=fake_get())
        with self.assertRaises(HR.HFRowsError):
            HR.labelled_ids("noequals", "t", get=fake_get())
        with self.assertRaises(HR.HFRowsError):
            HR.billed_jobs("t", get=lambda url, token: ({"usage": {}}, None))

    def test_labels_follow_the_pages(self):
        base = HR.API + "/api/jobs/someone?label=run%3Dprev"
        pages = {base: ([{"id": A}, {"id": B}], "https://huggingface.co/api/jobs/someone?cursor=2"),
                 "https://huggingface.co/api/jobs/someone?cursor=2": ([{"id": C}], None)}
        get = fake_get(pages)
        self.assertEqual(HR.labelled_ids("run=prev", "t", get=get), [A, B, C])
        self.assertEqual(get.calls[0], HR.API + "/api/whoami-v2")

    def test_command_line(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"HF_TOKEN": "t"}), mock.patch.object(HR, "http_get", fake_get()), \
                contextlib.redirect_stdout(out):
            code = cli.main(["run", "hf-rows", "--job", A, "--job", C, "--purpose", "previews",
                             "--ledger", str(self.priv)])
        self.assertEqual(code, 0)
        self.assertIn("added 1 row(s) costing 0.4667 USD", out.getvalue())
        self.assertIn(f"{C}: still running", out.getvalue())
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"HF_TOKEN": ""}), contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["run", "hf-rows", "--job", A, "--purpose", "p", "--ledger", str(self.priv)]), 2)
        self.assertIn("set HF_TOKEN", err.getvalue())

    def test_public_ledger_file_is_header_only(self):
        header, body = ML.read(Path(__file__).resolve().parents[1] / "docs" / "compute" / "hf-jobs-costs.csv")
        self.assertTrue(ML.is_public(header))
        self.assertEqual(header, PUBLIC.strip().split(","))
        self.assertTrue(all(ML.public_refusal(r, True) is None for r in body))


if __name__ == "__main__":
    unittest.main()
