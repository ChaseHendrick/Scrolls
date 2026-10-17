"""kit.prizewatch: the live prize page against the dated snapshot, with no network (pages are written here)."""

import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from kit import prizes, prizewatch

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
SNAPSHOT = {"checked": "2026-10-11", "prizes": [
    {"id": "grand", "total_usd": 1000000, "tiers_usd": {"1st": 800000, "2nd": 200000},
     "deadline": "2027-06-25T23:59:00-07:00",
     "eligible": [{"scroll": "PHerc0001", "volume": "20250821151825"}]},
    {"id": "progress", "total_usd_per_year": 590000, "monthly_best_usd": 20000, "typical_tiers_usd": [20000, 2500],
     "deadline": "2026-10-31T23:59:00-07:00", "eligible": [{"scroll": "any", "volume": "any"}]},
]}
PAGE = """<html><head><style>.x{content:"$999"}</style><script>var a = "$123,456 March 3rd, 2030";</script></head>
<body><h1>Open prize pool $2,140,000</h1><p>Grand Prize deadline June 25th, 2027 (11:59pm Pacific)</p>
<p>1st place: $800,000 &amp; 2nd: $200k. Total $1 million.</p><p>Volume 20250821151825 is eligible.</p>
<p>Progress prizes up to $20,000, then $2,500. Next deadline: October 31st, 2026.</p></body></html>"""


class FactsTest(unittest.TestCase):
    def test_amounts_dates_and_volumes(self):
        f = prizewatch.facts(PAGE)
        self.assertEqual(f["amounts"], [2500, 20000, 200000, 800000, 1000000, 2140000])
        self.assertEqual(f["dates"], ["2026-10-31", "2027-06-25"])
        self.assertEqual(f["volumes"], ["20250821151825"])

    def test_scripts_and_styles_are_not_page_text(self):
        text = prizewatch.page_text(PAGE)
        self.assertNotIn("123,456", text)
        self.assertNotIn("$999", text)
        self.assertIn("2nd: $200k", text)

    def test_short_month_names(self):
        self.assertEqual(prizewatch.facts("<p>Sept 1, 2027 and Jan 5th 2028</p>")["dates"],
                         ["2027-09-01", "2028-01-05"])


class CompareTest(unittest.TestCase):
    def test_agreeing_page(self):
        code, report = prizewatch.check(PAGE, SNAPSHOT, NOW)
        self.assertEqual((code, report["problems"]), (0, []))

    def test_changed_deadline_amount_and_volumes(self):
        page = (PAGE.replace("June 25th, 2027", "July 30th, 2027").replace("$800,000", "$700,000")
                .replace("20250821151825", "20260101000000"))
        code, report = prizewatch.check(page, SNAPSHOT, NOW)
        self.assertEqual(code, 3)
        text = "\n".join(report["problems"])
        self.assertIn("grand: the snapshot's date 2027-06-25 is not on the page", text)
        self.assertIn("800,000 USD", text)
        self.assertIn("volume 20250821151825 is not on the page", text)
        self.assertIn("names volume 20260101000000, which the snapshot does not list", text)

    def test_passed_deadline(self):
        after = datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc)   # 00:00 on 1 Nov, Pacific
        before = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)  # 23:00 on 31 Oct, Pacific
        self.assertEqual(prizewatch.check(PAGE, SNAPSHOT, before)[0], 0)
        code, report = prizewatch.check(PAGE, SNAPSHOT, after)
        self.assertEqual(code, 3)
        self.assertIn("progress: the snapshot's deadline 2026-10-31 has passed", report["problems"][0])

    def test_state_reports_what_changed_since_the_last_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "work" / "prize-page.json"
            self.assertEqual(prizewatch.check(PAGE, SNAPSHOT, NOW, state)[0], 0)
            self.assertEqual(json.loads(state.read_text())["checked"], "2026-10-16T12:00:00Z")
            self.assertEqual(prizewatch.check(PAGE, SNAPSHOT, NOW, state)[0], 0)
            code, report = prizewatch.check(PAGE.replace("Total $1 million.", "Total $1 million. $5,000 bonus."),
                                            SNAPSHOT, NOW, state)
            self.assertEqual(code, 3)
            self.assertEqual(report["changes"], ["new on the page since the last check: amounts 5000"])

    def test_real_snapshot_expectations_cover_every_prize(self):
        kinds = {(pid, kind) for pid, kind, _ in prizewatch.snapshot_expectations(prizes.load())}
        for p in prizes.load()["prizes"]:
            self.assertIn((p["id"], "date"), kinds)


class MainTest(unittest.TestCase):
    def run_main(self, *argv, page=None, error=None):
        def fetch(url, timeout):
            if error:
                raise error
            return page

        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snapshot.json"
            snap.write_text(json.dumps(SNAPSHOT))
            buf = io.StringIO()
            with mock.patch.object(prizewatch, "fetch", fetch), redirect_stdout(buf):
                code = prizewatch.main(["--snapshot", str(snap), "--today", "2026-10-16", *argv])
        return code, buf.getvalue()

    def test_agrees(self):
        code, out = self.run_main(page=PAGE)
        self.assertEqual(code, 0, out)
        self.assertIn("agrees with the snapshot", out)

    def test_disagrees(self):
        code, out = self.run_main(page=PAGE.replace("$2,500", "$3,000"))
        self.assertEqual(code, 3)
        self.assertIn("2,500 USD is not on the page", out)
        self.assertIn("new dated snapshot", out)

    def test_offline_is_exit_75(self):
        code, out = self.run_main(error=urllib.error.URLError("Name or service not known"))
        self.assertEqual(code, 75)
        self.assertIn("offline", out)

    def test_bad_snapshot_is_exit_2(self):
        self.assertEqual(prizewatch.main(["--snapshot", "/nonexistent.json"]), 2)

    def test_a_page_gone_from_the_site_needs_a_look_not_a_skip(self):
        gone = urllib.error.HTTPError(prizewatch.URL, 404, "Not Found", {}, None)
        code, out = self.run_main(error=gone)
        self.assertEqual(code, 3)
        self.assertIn("may have moved", out)
        busy = urllib.error.HTTPError(prizewatch.URL, 503, "Service Unavailable", {}, None)
        code, out = self.run_main(error=busy)
        self.assertEqual(code, 75)

    def test_bad_today_and_a_snapshot_without_prizes_are_exit_2(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(self.run_main("--today", "16-10-2026", page=PAGE)[0], 2)
            with tempfile.TemporaryDirectory() as tmp:
                snap = Path(tmp) / "s.json"
                snap.write_text("{}")
                self.assertEqual(prizewatch.main(["--snapshot", str(snap)]), 2)


if __name__ == "__main__":
    unittest.main()
