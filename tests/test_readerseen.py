"""kit readerseen: Reader V3's published training list as a registry, and its site check (metadata only)."""

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from kit import readerseen as rs


def _v(reader, scroll, segments=()):
    return rs.check(reader, scroll, segments)


class Build(unittest.TestCase):
    def test_registry_is_a_rebuild_of_the_pinned_copies(self):
        files = [rs.EVIDENCE / rs.SOURCES[k]["file"] for k in ("reader_v3_config", "reader_v2_config",
                                                                "ink9um_readme")]
        self.assertEqual(json.loads(rs.REGISTRY.read_text()), rs.build(*files))

    def test_other_bytes_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "c.json"
            shutil.copy(rs.EVIDENCE / rs.SOURCES["reader_v3_config"]["file"], bad)
            bad.write_bytes(bad.read_bytes() + b" ")
            with self.assertRaises(rs.SeenError):
                rs.build(bad, rs.EVIDENCE / rs.SOURCES["reader_v2_config"]["file"],
                         rs.EVIDENCE / rs.SOURCES["ink9um_readme"]["file"])

    def test_counts_and_lineage(self):
        reg = rs.load()
        self.assertEqual(reg["counts"]["keys"], 99)
        self.assertEqual(reg["counts"]["public_segments"], 91)
        self.assertEqual(reg["counts"]["per_scroll"]["PHerc0139"], {"public_segments": 26, "representations": 34})
        self.assertEqual(reg["counts"]["per_scroll"]["PHerc0814"]["public_segments"], 9)
        self.assertTrue(reg["lineage"][2]["same_keys_as_reader_v2"])
        self.assertTrue(reg["ink_9um_sets_all_in_reader_v3"])
        self.assertEqual(reg["digest"], rs.digest(reg))

    def test_readme_names_map_to_public_ids(self):
        table = rs.parse_readme((rs.EVIDENCE / rs.SOURCES["ink9um_readme"]["file"]).read_text())
        self.assertEqual(table[("PHerc0139", "pherc0139-w016", "aligned")], "20250108000004-w029_2025010827")
        self.assertEqual(table[("PHerc0139", "pherc0139-w029", "aligned")], "20260126000000-w045_2026012619")
        self.assertEqual(table[("PHerc0139", "w044", "native9")], "20260115000000-w044_2026011522")
        self.assertEqual(len([k for k in table if k[2] == "aligned"]), 24)
        self.assertEqual(len([k for k in table if k[2] == "native9"]), 5)

    def test_ink9um_human_labels_inherited_on_pseudo_rows(self):
        row = next(r for r in rs.load()["surfaces"] if r["public_segment"] == "20260226000000-46527_2um_try2")
        self.assertEqual(row["labels"], ["pseudo"])
        self.assertIn("ink_9um", row["readers"])
        self.assertIn("inherited_human_labels", row)


class Names(unittest.TestCase):
    def test_windows_and_short_ids(self):
        self.assertTrue(rs.name_meets("w45", "20260126000000-w045_2026012619"))
        self.assertTrue(rs.name_meets("ｗ０４５", "20260126000000-w045_2026012619"))
        self.assertFalse(rs.name_meets("w46", "20260126000000-w045_2026012619"))
        # an organizer annotation name carries no public window
        self.assertFalse(rs.name_meets("pherc0139-w029", "20250108000004-w029_2025010827"))
        self.assertTrue(rs.name_meets("46527", "20260226000000-46527_2um_try2"))
        self.assertFalse(rs.name_meets("2um", "20260226000000-46527_2um_try2"))

    def test_scroll_spellings(self):
        for s in ("0139", "PHerc139", "pherc0139", "PHerc 0139"):
            self.assertEqual(rs.scroll_key(s), "pherc0139", s)
        self.assertEqual(rs.scroll_key("Paris4"), "phercparis4")
        self.assertEqual(rs.roll_of("PHerc0500P2"), rs.roll_of("PHerc0500"))


class Check(unittest.TestCase):
    def test_trained_by_public_short_and_organizer_names(self):
        for seg in ("w045", "w45", "20260126000000-w045_2026012619", "pherc0139-w029"):
            r = _v("reader-v3", "PHerc0139", [seg])
            self.assertEqual(r["verdict"], "TRAINED", seg)
            self.assertEqual([h["public_segment"] for h in r["segments"][0]["surfaces"]],
                             ["20260126000000-w045_2026012619"], seg)
        # public w029 is the organizers' pherc0139-w016, not w045
        r = _v("reader-v3", "PHerc0139", ["w029"])
        self.assertEqual([h["public_segment"] for h in r["segments"][0]["surfaces"]],
                         ["20250108000004-w029_2025010827"])

    def test_possible_reading_is_never_fresh(self):
        self.assertEqual(_v("reader-v3", "PHerc0139", ["w017"])["verdict"], "TRAINED-POSSIBLE")

    def test_same_scroll_is_not_held_out(self):
        r = _v("reader-v3", "PHerc0139", ["w046"])
        self.assertEqual((r["verdict"], r["exit"], r["held_out_by_list"]), ("SAME-SCROLL", 3, False))
        self.assertEqual(_v("reader-v3", "PHerc0139")["verdict"], "TRAINED")

    def test_selection_rows(self):
        self.assertEqual(_v("reader-v3", "PHerc0009B", ["ag487"])["verdict"], "SELECTED")
        self.assertEqual(_v("reader-v3", "PHerc0009B", ["20250919064353-auto_grown_x"])["verdict"], "TRAINED")
        self.assertEqual(_v("reader-v3", "PHerc0841", ["ag405"])["verdict"], "SELECTED")
        self.assertEqual(_v("reader-v3", "PHerc0139", ["w053"])["verdict"], "SELECTED")
        # the suite is Reader V3's: Reader v2 shares the training list, not the selection
        self.assertEqual(_v("reader-v2", "PHerc0841", ["ag405"])["verdict"], "FRESH-BY-LIST")

    def test_selected_units_on_a_scroll(self):
        self.assertEqual(_v("reader-v3", "PHerc0841")["verdict"], "SELECTED")
        self.assertEqual(_v("reader-v3", "PHerc0841", ["20260301000000-auto_grown_new"])["verdict"], "SAME-SCROLL")

    def test_same_roll(self):
        r = _v("reader-v3", "PHerc0343")
        self.assertEqual(r["other_roll_pieces_trained"], ["PHerc0343P"])
        self.assertEqual(r["verdict"], "SAME-ROLL")

    def test_derived_reader_never_fresh(self):
        self.assertEqual(_v("reader-v3", "PHerc0332")["verdict"], "FRESH-BY-LIST")
        self.assertEqual(_v("argus-v2", "PHerc0332")["verdict"], "DERIVED-UNKNOWN")
        self.assertEqual(_v("argus-v2", "PHerc0139", ["w045"])["verdict"], "TRAINED")

    def test_short_ids_and_scroll_spellings(self):
        self.assertEqual(_v("reader-v3", "PHerc0814", ["46527"])["verdict"], "TRAINED")
        self.assertEqual(_v("reader-v3", "0139", ["w045"])["verdict"], "TRAINED")
        self.assertEqual(_v("rv3", "PHerc0500P2", ["20250611153340-z_dbg_gen_00275"])["reader"], "reader-v3")

    def test_fresh_flags(self):
        r = _v("reader-v3", "PHerc0332")
        self.assertEqual((r["exit"], r["held_out_by_list"]), (0, True))
        self.assertFalse(_v("argus-v2", "PHerc0332")["held_out_by_list"])

    def test_empty_scroll_refused(self):
        with self.assertRaises(rs.SeenError):
            rs.check("reader-v3", "")

    def test_unknown_reader_refused(self):
        with self.assertRaises(rs.SeenError):
            rs.reader_of("ink_9um")

    def test_cli_exit_codes(self):
        cases = ((["check", "--reader", "reader-v3", "--scroll", "PHerc0139", "--segment", "w045"], 5),
                 (["check", "--reader", "reader-v3", "--scroll", "PHerc0332", "--json"], 0),
                 (["check", "--reader", "nobody", "--scroll", "PHerc0332"], 2),
                 (["verify"], 0))
        for argv, want in cases:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(rs.main(argv), want, argv)


if __name__ == "__main__":
    unittest.main()
