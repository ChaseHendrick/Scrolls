"""The 2026-10-09 prize snapshot: villa's eligible lists unchanged, plus the 8 Oct 2026 PHerc. 343 award note."""

import contextlib
import io
import json
import unittest
from datetime import date

from kit import cli, prizes

POST = "https://scrollprize.substack.com/p/50k-first-letters-prize-awarded-for"
OLD = prizes.DATA_DIR / "prizes-2026-10-06.json"
NEW = prizes.DATA_DIR / "prizes-2026-10-09.json"


def without_awards(snapshot):
    copy = json.loads(json.dumps(snapshot))
    for prize in copy["prizes"]:
        for entry in prize["eligible"]:
            entry.pop("award", None)
    return copy


class AwardedSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.snap = prizes.load(NEW)

    def test_default_snapshot_is_the_new_one(self):
        self.assertEqual(prizes.SNAPSHOT, NEW)
        self.assertEqual(prizes.load(), self.snap)
        self.assertEqual(self.snap["checked"], "2026-10-09")
        self.assertEqual(self.snap["bucket_checked"], "2026-10-09")
        self.assertTrue(OLD.exists(), "keep the old snapshot for history")

    def test_pherc0343_award_has_date_and_source(self):
        award = prizes.award(self.snap, "PHerc. 343")
        self.assertEqual(award, {
            "date": "2026-10-08",
            "title": "$50K First Letters Prize awarded for PHerc. 343",
            "source": POST,
            "label": "Sourced fact",
            "checked": "2026-10-09",
        })

    def test_pherc0343_stays_eligible_as_villa_lists_it(self):
        self.assertEqual(prizes.eligible_volume(self.snap, "PHerc0343"), "20250521140437")
        self.assertEqual(len(prizes.find(self.snap, "first-letters-2027")["eligible"]), 22)
        self.assertEqual(len(prizes.find(self.snap, "grand-prize-2027")["eligible"]), 13)

    def test_no_other_scroll_or_prize_carries_an_award(self):
        awarded = [(p["id"], e["scroll"]) for p in self.snap["prizes"] for e in p["eligible"] if "award" in e]
        self.assertEqual(awarded, [("first-letters-2027", "PHerc0343")])
        self.assertIsNone(prizes.award(self.snap, "PHerc0826"))
        self.assertIsNone(prizes.award(self.snap, "PHerc1667"))
        self.assertIsNone(prizes.award(self.snap, "PHerc0343", "grand-prize-2027"))

    def test_only_the_award_dates_and_notes_differ_from_the_old_snapshot(self):
        old, new = prizes.load(OLD), without_awards(self.snap)
        self.assertEqual(new["prizes"], old["prizes"])
        changed = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
        self.assertEqual(changed, {"checked", "bucket_checked", "note", "source_main_check"})
        self.assertEqual(new["source_commit"], old["source_commit"])

    def test_table_prints_the_award_next_to_the_scroll(self):
        out = prizes.format_table(self.snap, date(2026, 10, 9))
        self.assertIn("PHerc0343 (awarded)", out)
        self.assertIn(f"PHerc0343: First Letters awarded 2026-10-08, still on villa's eligible list ({POST})", out)
        self.assertEqual(out.count("(awarded)"), 1)
        self.assertEqual(out.count(POST), 1)

    def test_old_snapshot_prints_no_award(self):
        out = prizes.format_table(prizes.load(OLD), date(2026, 10, 6))
        self.assertNotIn("awarded 2026", out)
        self.assertNotIn("(awarded)", out)

    def test_cli_prints_the_award(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["prizes", "--today", "2026-10-09"])
        self.assertEqual(code, 0)
        self.assertIn("snapshot checked 2026-10-09", buf.getvalue())
        self.assertIn(f"First Letters awarded 2026-10-08, still on villa's eligible list ({POST})", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
