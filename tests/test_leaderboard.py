"""kit/leaderboard.py: the ink reader leaderboard written from docs/results.json, and its check."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from kit import leaderboard as lb

ROOT = Path(__file__).resolve().parent.parent


def data(**extra):
    d = {
        "schema": 1, "updated": "2026-10-16",
        "held_out_by_reader": {
            "PHerc0841": {"ink_9um": "held out", "v8in": "held out", "v8in-1447": "held out",
                          "Reader v2": "held out", "Hecate": "possibly not held out"},
            "w045": {"ink_9um": "not held out", "v8in": "held out"},
        },
        "segments": {"0841-w00": {"segment": "S", "voxel_um": 9.366, "crop": [0, 640, 0, 640]},
                     "w045": {"segment": "W", "voxel_um": 9.362, "crop": [0, 640, 0, 640]}},
        "results": [
            {"segment": "0841-w00", "window": "crop", "inner_px": 64, "map_from": "bare-crop", "reader": "ink_9um seed42",
             "device": "cpu", "auc_as_stored": 0.8061, "auc_reversed": 0.5361, "source": "docs/logs/2026-10-07-x.md"},
            {"segment": "0841-w00", "window": "crop", "inner_px": 64, "map_from": "bare-crop", "reader": "Reader v2",
             "device": "cpu", "auc_as_stored": 0.9269, "auc_reversed": 0.8500, "auc_shuffled": 0.5681,
             "source": "scripts/experiments/2026-10-07-cloud/r.json"},
            {"segment": "0841-w00", "window": "whole", "inner_px": 0, "map_from": "full", "reader": "ink_9um seed42",
             "device": "cuda", "auc_as_stored": 0.7479, "auc_reversed": 0.5012, "date": "2026-10-09",
             "source": "https://example.org/readme"},
            {"segment": "w045", "window": "crop", "inner_px": 0, "map_from": "full", "reader": "ink_9um seed43",
             "device": "cpu", "auc_as_stored": 0.9098, "auc_reversed": 0.4347, "source": "docs/logs/2026-10-07-x.md"},
            {"segment": "w045", "window": "crop", "inner_px": 0, "map_from": "bare-crop", "reader": "v8in d89166b",
             "device": "mps", "auc_as_stored": 0.7382, "auc_reversed": 0.3269, "source": "docs/logs/2026-10-07-x.md"},
            {"segment": "w045", "window": "whole", "reader": "ink_9um seeds 42+43 mean", "row_score_as_stored": 95.9,
             "source": "docs/logs/2026-10-07-x.md"},
        ],
        "community": [
            {"reader": "Hecate + Reader v2 mean", "test": "PHerc0841 whole, human labels", "auc": 0.866,
             "source": "https://huggingface.co/x"},
            {"reader": "v8in d89166b", "test": "PHerc0841 w00, labels' bounding box", "auc": 0.837,
             "auc_reversed": 0.562, "source": "https://github.com/x", "date": "2026-10-01"},
        ],
    }
    d.update(extra)
    return d


class StatusTest(unittest.TestCase):
    def test_families(self):
        self.assertEqual(lb.family("v8in-1447 stride 42"), "v8in-1447")
        self.assertEqual(lb.family("v8in d89166b"), "v8in")
        self.assertEqual(lb.family("ink_9um seed42"), "ink_9um")
        self.assertIsNone(lb.family("Mystery reader"))

    def test_ensemble_takes_the_least_held_out_part(self):
        table = data()["held_out_by_reader"]
        self.assertEqual(lb.status("Hecate + Reader v2 mean", "PHerc0841", table), "possibly not held out")
        self.assertEqual(lb.status("Reader v2", "PHerc0841", table), "held out")
        self.assertEqual(lb.status("ink_9um seed42", "w045", table), "not held out")

    def test_a_reader_without_a_status_is_an_error(self):
        table = data()["held_out_by_reader"]
        with self.assertRaisesRegex(lb.BoardError, "no status for 'Reader v2'"):
            lb.status("Reader v2", "w045", table)
        with self.assertRaisesRegex(lb.BoardError, "no known family"):
            lb.status("Mystery reader", "PHerc0841", table)
        bad = data()
        bad["held_out_by_reader"]["w045"]["v8in"] = "maybe"
        with self.assertRaises(lb.BoardError):
            lb.render(bad)

    def test_a_row_without_a_date_is_an_error(self):
        d = data()
        d["results"][2].pop("date")
        with self.assertRaisesRegex(lb.BoardError, "no date"):
            lb.render(d)

    def test_no_status_table_is_an_error(self):
        d = data()
        d.pop("held_out_by_reader")
        with self.assertRaises(lb.BoardError):
            lb.render(d)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.text = lb.render(data())
        self.lines = self.text.split("\n")

    def row(self, *needles):
        hits = [l for l in self.lines if l.startswith("| ") and all(n in l for n in needles)]
        self.assertEqual(len(hits), 1, (needles, hits))
        return [c.strip() for c in hits[0].strip("|").split(" | ")]

    def test_not_held_out_pairs_are_marked(self):
        self.assertEqual(self.row("ink_9um seed43")[1], "**NOT held out**")
        self.assertEqual(self.row("v8in d89166b", "mps")[1], "held out")
        self.assertEqual(self.row("Hecate + Reader v2 mean")[2], "**possibly NOT held out**")

    def test_controls_and_columns(self):
        cells = self.row("Reader v2", "bare-crop")
        self.assertEqual(cells[2:6], ["0.9269", "0.8500", "+0.0769 (weak control)", "0.5681"])
        cells = self.row("ink_9um seed42", "bare-crop")
        self.assertEqual(cells[2:6], ["0.8061", "0.5361", "+0.2700", ""])
        self.assertEqual(cells[-1], "2026-10-07")
        self.assertEqual(self.row("ink_9um seed42", "cuda")[-1], "2026-10-09")
        self.assertEqual(self.row("v8in d89166b", "bound")[-2], "2026-10-01")
        self.assertEqual(self.row("Hecate + Reader v2 mean")[-2], "not recorded")

    def test_windows_split_and_sort_by_forward(self):
        w00 = self.text.index("### PHerc0841 w00")
        whole, crop = self.text.index("Window: whole", w00), self.text.index("Window: crop, inner 64", w00)
        self.assertLess(whole, crop)
        self.assertLess(self.text.index("| Reader v2", crop), self.text.index("| ink_9um seed42 | held out | 0.8061"))

    def test_rows_without_auc_stay_out_and_missing_readers_are_named(self):
        self.assertNotIn("seeds 42+43 mean", self.text)
        self.assertIn("Not scored here yet: `v8in-1447`, `Hecate`, `v8in`.", self.text)
        self.assertIn("### PHerc0841 auto-grown 405 (ag405)\n\nNo row yet.", self.text)

    def test_sources_link(self):
        self.assertIn("[`logs/2026-10-07-x.md`](logs/2026-10-07-x.md)", self.text)
        self.assertIn("(../scripts/experiments/2026-10-07-cloud/r.json)", self.text)
        self.assertIn("](https://example.org/readme)", self.text)

    def test_long_dash_is_refused(self):
        d = data()
        d["results"][0]["map_from"] = "bare" + chr(0x2014) + "crop"
        with self.assertRaisesRegex(lb.BoardError, "long dash"):
            lb.render(d)


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.results = self.dir / "results.json"
        self.board = self.dir / "leaderboard.md"
        self.results.write_text(json.dumps(data()), encoding="utf-8")

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lb.main(["--results", str(self.results), "--out", str(self.board), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_check_fails_until_rendered_and_after_a_change(self):
        self.assertEqual(self.call("check")[0], 1)
        self.assertEqual(self.call("render")[0], 0)
        self.assertEqual(self.call("check")[0], 0)
        # A number changed in the data, not the page: the check fails.
        d = data()
        d["results"][0]["auc_as_stored"] = 0.8062
        self.results.write_text(json.dumps(d), encoding="utf-8")
        code, _, err = self.call("check")
        self.assertEqual(code, 1)
        self.assertIn("differs", err)
        self.assertEqual(self.call("render")[0], 0)
        # The page edited by hand: the check fails.
        self.board.write_text(self.board.read_text().replace("0.8062", "0.9000"), encoding="utf-8")
        self.assertEqual(self.call("check")[0], 1)

    def test_bad_data_fails_check_and_render(self):
        d = data()
        d["results"][0]["reader"] = "Mystery reader"
        self.results.write_text(json.dumps(d), encoding="utf-8")
        code, _, err = self.call("check")
        self.assertEqual(code, 1)
        self.assertIn("no known family", err)
        self.assertEqual(self.call("render")[0], 2)

    def test_a_row_missing_a_field_is_a_problem_not_a_traceback(self):
        d = data()
        del d["community"][0]["auc"]
        self.results.write_text(json.dumps(d), encoding="utf-8")
        code, _, err = self.call("check")
        self.assertEqual(code, 1)
        self.assertIn("has no 'auc' field", err)
        code, _, err = self.call("render")
        self.assertEqual(code, 2)
        self.assertIn("has no 'auc' field", err)

    def test_render_counts_rows_and_refuses_a_missing_folder(self):
        code, out, _ = self.call("render")
        self.assertEqual(code, 0)
        rec = json.loads(out)
        text = self.board.read_text(encoding="utf-8")
        body = [l for l in text.split("\n") if l.startswith("| ") and not l.startswith("| ---")]
        self.assertEqual(rec["rows"] + rec["tables"], len(body))      # every table has one header line
        self.board = self.dir / "no-such-folder" / "leaderboard.md"
        code, _, err = self.call("render")
        self.assertEqual(code, 2)
        self.assertIn("leaderboard: ", err)

    def test_no_results_file(self):
        self.results = self.dir / "missing.json"
        self.assertEqual(self.call("check")[0], 2)

    def test_kit_command_is_registered(self):
        from kit import cli
        args = cli.build_parser().parse_args(["leaderboard", "--results", str(self.results), "check"])
        self.assertIs(args.func, lb.run)


class RepositoryTest(unittest.TestCase):
    def test_leaderboard_matches_results(self):
        self.assertEqual(lb.check(ROOT / "docs" / "results.json", ROOT / "docs" / "leaderboard.md"), [])

    def test_every_held_out_family_is_in_the_prose(self):
        results = json.loads((ROOT / "docs" / "results.json").read_text(encoding="utf-8"))
        prose = results["held_out"]
        for group, table in results["held_out_by_reader"].items():
            if group == "about":
                continue
            self.assertIn(group, prose)
            for fam in table:
                self.assertIn(fam, prose[group], f"held_out.{group} does not name {fam}")


if __name__ == "__main__":
    unittest.main()
