"""kit.mergedriver: CSV tables merge by row, JSON registries by entry, indexes and JSON-lines logs by line, without
reformatting; a real conflict still falls back to git's line merge with markers; real git merges use the drivers."""
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from kit import mergedriver as M

ROOT = Path(__file__).resolve().parent.parent
HEAD = "date,job_id,flavor,cost\n"
BASE = HEAD + "2026-11-01,j1,cpu,\n"


class CsvTest(unittest.TestCase):
    KEY = ["date", "job_id"]

    def merge(self, b, o, t):
        return M.merge_csv(b, o, t, self.KEY)

    def test_rows_added_on_both_sides_are_all_kept_with_their_bytes(self):
        o = BASE + '2026-11-02,j2,cpu,"1.50"\n'
        t = BASE + "2026-11-03,j3,gpu,\n"
        self.assertEqual(self.merge(BASE, o, t), BASE + '2026-11-02,j2,cpu,"1.50"\n' + "2026-11-03,j3,gpu,\n")

    def test_a_fill_on_one_side_and_a_new_row_on_the_other(self):
        o = BASE.replace("cpu,\n", "cpu,0.40\n")
        t = BASE + "2026-11-03,j3,gpu,\n"
        self.assertEqual(self.merge(BASE, o, t), o + "2026-11-03,j3,gpu,\n")

    def test_different_fields_changed_on_each_side_merge_by_field(self):
        o = BASE.replace("cpu,\n", "cpu,0.40\n")
        t = BASE.replace(",cpu,", ",cpu-xl,")
        self.assertEqual(self.merge(BASE, o, t), HEAD + "2026-11-01,j1,cpu-xl,0.40\n")

    def test_the_same_field_changed_two_ways_conflicts(self):
        with self.assertRaises(M.Conflict):
            self.merge(BASE, BASE.replace("cpu,\n", "cpu,1\n"), BASE.replace("cpu,\n", "cpu,2\n"))

    def test_a_row_removed_on_one_side_and_changed_on_the_other_conflicts(self):
        with self.assertRaises(M.Conflict):
            self.merge(BASE, HEAD, BASE.replace("cpu,\n", "cpu,1\n"))
        self.assertEqual(self.merge(BASE, HEAD, BASE), HEAD)          # removed on one side, untouched on the other

    def test_the_default_key_is_id_else_the_first_column(self):
        b = "id,v\na,1\n"
        self.assertEqual(M.merge_csv(b, "id,v\na,2\n", b + "c,3\n"), "id,v\na,2\nc,3\n")
        b = "name,v\nx,1\n"
        self.assertEqual(M.merge_csv(b, "name,v\nx,2\n", b + "y,3\n"), "name,v\nx,2\ny,3\n")
        with self.assertRaises(M.Conflict):
            M.merge_csv(b, b, b, ["missing"])

    def test_different_headers_conflict(self):
        with self.assertRaises(M.Conflict):
            self.merge(BASE, BASE, BASE.replace("cost", "usd"))

    def test_crlf_sides_come_out_lf(self):
        o = (BASE + "2026-11-02,j2,cpu,\n").replace("\n", "\r\n")
        self.assertEqual(self.merge(BASE, o, BASE), BASE + "2026-11-02,j2,cpu,\n")


class JsonTest(unittest.TestCase):
    B = '{\n "tools": [\n  {\n   "id": "a",\n   "v": 1\n  }\n ]\n}\n'

    def test_entries_added_on_both_sides_and_a_change_on_one(self):
        o = self.B.replace('"v": 1', '"v": 2')
        t = '{\n "tools": [\n  {\n   "id": "a",\n   "v": 1\n  },\n  {\n   "id": "c",\n   "v": 3\n  }\n ]\n}\n'
        out = M.merge_json(self.B, o, t)
        self.assertIn('"v": 2', out)
        self.assertIn('"id": "c"', out)
        self.assertTrue(out.startswith('{\n "tools"'))                # indent 1 kept

    def test_the_same_id_added_two_ways_and_a_value_changed_two_ways_conflict(self):
        add = lambda v: self.B.replace("\n ]", ',\n  {\n   "id": "n",\n   "v": %d\n  }\n ]' % v)  # noqa: E731
        with self.assertRaises(M.Conflict):
            M.merge_json(self.B, add(1), add(2))
        with self.assertRaises(M.Conflict):
            M.merge_json(self.B, self.B.replace('"v": 1', '"v": 2'), self.B.replace('"v": 1', '"v": 3'))

    def test_a_format_that_does_not_round_trip_conflicts(self):
        with self.assertRaises(M.Conflict):
            M.merge_json(self.B, '{"tools":  []}\n', self.B)

    def test_a_removed_entry_stays_removed(self):
        empty = '{\n "tools": []\n}\n'
        self.assertEqual(M.merge_json(self.B, empty, self.B), empty)
        with self.assertRaises(M.Conflict):
            M.merge_json(self.B, empty, self.B.replace('"v": 1', '"v": 9'))


class LinesTest(unittest.TestCase):
    B = "| a | 1 |\n| b | 2 |\n"

    def test_rows_added_at_the_end_on_both_sides_are_all_kept_ours_first(self):
        self.assertEqual(M.merge_lines(self.B, self.B + "| o |\n", self.B + "| t |\n"), self.B + "| o |\n| t |\n")

    def test_a_row_both_added_is_kept_once(self):
        self.assertEqual(M.merge_lines(self.B, self.B + "| x |\n", self.B + "| x |\n"), self.B + "| x |\n")

    def test_an_edit_next_to_an_addition_is_taken(self):
        o = self.B.replace("| b | 2 |", "| b | 3 |")
        t = self.B + "| c |\n"
        self.assertEqual(M.merge_lines(self.B, o, t), o + "| c |\n")

    def test_the_same_line_edited_two_ways_conflicts(self):
        with self.assertRaises(M.Conflict):
            M.union_hunk(["x\n"], ["y\n"], ["z\n"])

    def test_an_append_only_log_takes_base_then_theirs_then_ours(self):
        b = '{"n": 0}\n'
        out = M.merge_append(b, b + '{"n": "o"}\n', b + '{"n": "t"}\n', "theirs")
        self.assertEqual(out, b + '{"n": "t"}\n{"n": "o"}\n')
        self.assertEqual(M.lines_first("logs/a.jsonl"), "theirs")
        self.assertEqual(M.lines_first("docs/INDEX.md"), "ours")
        os.environ["KIT_LINES_FIRST"] = "ours"
        try:
            self.assertEqual(M.lines_first("logs/a.jsonl"), "ours")
        finally:
            del os.environ["KIT_LINES_FIRST"]

    def test_drive_leaves_markers_on_a_real_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            p = {n: Path(d) / n for n in ("b", "o", "t")}
            p["b"].write_text("x\n")
            p["o"].write_text("y\n")
            p["t"].write_text("z\n")
            self.assertEqual(M.drive("lines", p["b"], p["o"], p["t"], "docs/INDEX.md"), M.EXIT_MARKERS)
            self.assertIn("<<<<<<<", p["o"].read_text())


def _git(r, *args, env=None):
    return subprocess.run(["git", "-C", str(r), *args], capture_output=True, text=True, env=env)


class GitMergeTest(unittest.TestCase):
    """Real git merges in a scratch repository, with kit importable through PYTHONPATH."""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        r = self.r = Path(self.d.name)
        self.env = dict(os.environ, PYTHONPATH=str(ROOT), GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        _git(r, "init", "-q", "-b", "main", env=self.env)
        (r / ".gitattributes").write_text("runs.csv merge=kit-csv\nreg.json merge=kit-json\nINDEX.md merge=kit-lines\n")
        (r / "runs.csv").write_text(BASE)
        (r / "reg.json").write_text(JsonTest.B)
        (r / "INDEX.md").write_text(LinesTest.B)
        _git(r, "add", "-A", env=self.env)
        _git(r, "commit", "-q", "-m", "base", env=self.env)
        self.assertEqual([n for n, _ in M.install(r, csv_key=["date", "job_id"])], list(M.DRIVERS))
        self.assertEqual(M.install(r, csv_key=["date", "job_id"]), [])

    def tearDown(self):
        self.d.cleanup()

    def branch(self, name, edits):
        r = self.r
        _git(r, "checkout", "-q", "-b", name, "main", env=self.env)
        for f, text in edits.items():
            with open(r / f, "a") as fh:
                fh.write(text)
        _git(r, "commit", "-q", "-am", name, env=self.env)
        _git(r, "checkout", "-q", "main", env=self.env)

    def test_two_branches_merge_without_a_conflict(self):
        self.branch("one", {"runs.csv": "2026-11-02,j2,cpu,\n", "INDEX.md": "| one |\n"})
        self.branch("two", {"runs.csv": "2026-11-03,j3,gpu,\n", "INDEX.md": "| two |\n"})
        for b in ("one", "two"):
            m = _git(self.r, "merge", "-q", "--no-edit", b, env=self.env)
            self.assertEqual(m.returncode, 0, m.stdout + m.stderr)
        self.assertEqual((self.r / "runs.csv").read_text(), BASE + "2026-11-02,j2,cpu,\n2026-11-03,j3,gpu,\n")
        self.assertEqual((self.r / "INDEX.md").read_text(), LinesTest.B + "| one |\n| two |\n")

    def test_a_real_conflict_still_stops_the_merge(self):
        for name, cost in (("one", "1"), ("two", "2")):
            _git(self.r, "checkout", "-q", "-b", name, "main", env=self.env)
            (self.r / "runs.csv").write_text(BASE.replace("cpu,\n", f"cpu,{cost}\n"))
            _git(self.r, "commit", "-q", "-am", name, env=self.env)
            _git(self.r, "checkout", "-q", "main", env=self.env)
        self.assertEqual(_git(self.r, "merge", "-q", "--no-edit", "one", env=self.env).returncode, 0)
        self.assertNotEqual(_git(self.r, "merge", "-q", "--no-edit", "two", env=self.env).returncode, 0)
        self.assertIn("<<<<<<<", (self.r / "runs.csv").read_text())

    def test_a_broken_kit_still_leaves_both_sides(self):
        self.branch("one", {"INDEX.md": "| one |\n"})
        self.branch("two", {"INDEX.md": "| two |\n"})
        env = dict(self.env, PYTHONPATH=str(self.r))            # no kit here: the driver command falls back
        _git(self.r, "merge", "-q", "--no-edit", "one", env=env)
        _git(self.r, "merge", "-q", "--no-edit", "two", env=env)
        text = (self.r / "INDEX.md").read_text()
        self.assertIn("| one |", text)
        self.assertIn("| two |", text)


class CliTest(unittest.TestCase):
    def test_attributes_and_driver_command(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(M.main(["attributes"]), 0)
        self.assertIn("merge=kit-csv", out.getvalue())
        self.assertIn("--key date,job_id", M.driver_command("csv", ["date", "job_id"]))
        self.assertNotIn("--key", M.driver_command("json", ["date"]))

    def test_status_and_a_plain_install_keep_the_installed_csv_key(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(M.main(["--root", d, "install", "--csv-key", "date,job_id"]), 0)
                self.assertEqual(M.main(["--root", d, "status"]), 0)
                self.assertEqual(M.install(d), [])
            have = subprocess.run(["git", "-C", d, "config", "--get", "merge.kit-csv.driver"], capture_output=True,
                                  text=True).stdout.strip()
            self.assertEqual(M.installed_key(have), ["date", "job_id"])
            self.assertIsNone(M.installed_key(M.driver_command("csv")))

    def test_status_in_a_clone_without_drivers(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(M.main(["--root", d, "status"]), M.EXIT_CONFLICT)
                self.assertEqual(M.main(["--root", d, "install", "--check"]), M.EXIT_CONFLICT)


if __name__ == "__main__":
    unittest.main()
