"""kit reviewpin (kit/reviewpin.py): verdicts tied to commits, own-patch compares, derived covers by base-only
merges (by content and by merge replay), explain, and the command line, on throwaway git repositories."""

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from kit import reviewpin

ENV = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="T",
           GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

LINES = [f"line {i}" for i in range(1, 21)]


@unittest.skipUnless(shutil.which("git"), "needs git")
class ReviewPinTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.g("init", "-q", "-b", "base")
        self.write("a.txt", LINES)
        self.write("b.txt", ["b1", "b2"])
        self.commit("start")
        self.g("checkout", "-q", "-b", "feat")
        a = list(LINES)
        a[9] = "line 10 changed by the PR"
        self.write("a.txt", a)
        self.write("docs/notes.md", ["notes"])
        self.reviewed = self.commit("the PR")

    def tearDown(self):
        self.tmp.cleanup()

    def g(self, *args):
        p = subprocess.run(["git", *args], cwd=self.root, env=ENV, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def write(self, rel, lines):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")

    def commit(self, msg):
        self.g("add", "-A")
        self.g("commit", "-q", "-m", msg)
        return self.g("rev-parse", "HEAD")

    def record(self, verdict="GO", sha=None, scope=(), time=None):
        rec = reviewpin.make_record(self.root, 7, sha or self.reviewed, verdict, scope=scope, reviewer="tester",
                                    base="base", time=time)
        reviewpin.append(self.root, rec)
        return rec

    def delta(self, head="feat", fetch=False):
        return reviewpin.delta(self.root, 7, head=head, base="base", fetch=fetch)

    def merge_base_in(self):
        """The base moves (b.txt, and a.txt far from the PR's line), then the PR merges it in."""
        self.g("checkout", "-q", "base")
        a = list(LINES)
        a[0] = "line 1 changed on the base"
        self.write("a.txt", a)
        self.write("b.txt", ["b1", "b2", "b3"])
        self.commit("base moves")
        self.g("checkout", "-q", "feat")
        self.g("merge", "-q", "--no-edit", "base")

    def test_log_from_reads_the_verdicts_a_commit_has_not_the_working_tree(self):
        # a merge gate reads pins from the base branch only: a GO the PR's own tree carries is ignored
        self.record()
        self.commit("the PR records its own GO")
        self.assertEqual(reviewpin.delta(self.root, 7, head="feat", base="base", fetch=False)["verdict"], "GO")
        r = reviewpin.delta(self.root, 7, head="feat", base="base", fetch=False, log_ref="base")
        self.assertEqual(r["status"], "no-verdict")
        self.assertEqual(reviewpin.read_log_at(self.root, "feat")[0]["pr"], 7)
        with self.assertRaises(reviewpin.PinError):
            reviewpin.read_log_at(self.root, "no-such-ref")

    OLD = "2020-01-01T00:00:00Z"

    def base_moves_context(self):
        """The base edits line 12, in the context of the PR's line 10, so the hunk context moves; the PR merges it."""
        self.g("checkout", "-q", "base")
        a = list(LINES)
        a[11] = "line 12 changed on the base"
        self.write("a.txt", a)
        self.commit("base edits the context")
        self.g("checkout", "-q", "feat")

    def test_a_merge_that_only_moves_context_is_a_derived_cover(self):
        self.record(time=self.OLD)
        self.base_moves_context()
        self.g("merge", "-q", "--no-edit", "base")
        r = self.delta()
        self.assertEqual((r["status"], r.get("derived")), ("carries", True), r.get("derive"))
        self.assertIn("identical by content", r["derive"])

    def test_a_merge_plus_an_own_edit_is_not_derived(self):
        self.record(time=self.OLD)
        self.base_moves_context()
        self.g("merge", "-q", "--no-edit", "base")
        self.write("docs/notes.md", ["notes", "more"])
        self.commit("own edit after the merge")
        r = self.delta()
        self.assertEqual(r["status"], "recheck")
        self.assertIn("is not a merge", r["derive"])

    def test_an_own_edit_inside_the_merge_is_not_derived(self):
        self.record(time=self.OLD)
        self.base_moves_context()
        self.g("merge", "-q", "--no-commit", "base")
        a = (self.root / "a.txt").read_text().splitlines()
        a[9] = "line 10 changed again in the merge"
        self.write("a.txt", a)
        self.commit("merge with an edit")
        r = self.delta()
        self.assertEqual(r["status"], "recheck")
        self.assertIn("own change differs in a.txt", r["derive"])

    def test_a_merge_resolution_that_moves_a_line_is_not_derived(self):
        # the base swaps two lists; the merge resolution puts the PR's entry in the wrong one. The -U0 lines match by
        # content, but an automatic merge of the parents gives another file.
        self.g("checkout", "-q", "base")
        self.write("g.py", ["LEFT = [", "  'a1',", "]", "", "x = 1", "", "RIGHT = [", "  'b1',", "]"])
        self.commit("guard lists")
        self.g("checkout", "-q", "feat")
        self.g("merge", "-q", "--no-edit", "base")
        self.write("g.py", ["LEFT = [", "  'a1',", "  'c9',", "]", "", "x = 1", "", "RIGHT = [", "  'b1',",
                            "]"])
        self.reviewed = self.commit("add c9 to LEFT")
        self.g("checkout", "-q", "base")
        self.write("g.py", ["RIGHT = [", "  'b1',", "]", "", "x = 1", "", "LEFT = [", "  'a1',", "]"])
        self.commit("base swaps the lists")
        self.g("checkout", "-q", "feat")
        self.g("merge", "-q", "--no-commit", "-s", "ours", "base")
        self.write("g.py", ["RIGHT = [", "  'b1',", "  'c9',", "]", "", "x = 1", "", "LEFT = [", "  'a1',",
                            "]"])
        self.commit("merge, c9 put in RIGHT")
        self.record(time=self.OLD)              # recorded last only so the log stays out of the commits
        r = self.delta()
        self.assertEqual(r["status"], "recheck", r.get("derive"))
        self.assertIn("g.py", r["derive"])

    def test_a_merge_that_cannot_be_replayed_is_refused(self):
        # git merge-tree on an unknown ref gives no tree; reading ":path" would then read the index (fail open)
        why = reviewpin.replay_differs(self.root, "f" * 40, "no-such-ref", "base", ["a.txt"])
        self.assertIn("could not be replayed", why or "")

    def test_always_in_scope_counts_a_file_outside_the_scope(self):
        a = (self.root / "a.txt").read_text().splitlines()
        a[4] = "line 5 changed after the review"
        self.write("a.txt", a)
        self.commit("edit outside the scope")
        self.record(scope=["docs/*"], time=self.OLD)
        self.assertEqual(self.delta()["status"], "carries")
        r = reviewpin.delta(self.root, 7, head="feat", base="base", fetch=False, always_in_scope=["a.txt"])
        self.assertEqual(r["status"], "recheck")

    def test_a_pin_recorded_after_the_merge_is_not_derived(self):
        self.base_moves_context()
        self.g("merge", "-q", "--no-edit", "base")
        self.record(time="2099-01-01T00:00:00Z")
        r = self.delta()
        self.assertEqual(r["status"], "recheck")
        self.assertIn("recorded after merge", r["derive"])

    def json_case(self, change_value):
        """data.json, an object of five keys; the PR appends a key after the last, the base swaps the first two (two
        lines above the PR's hunk, inside its context), the PR merges the base in automatically, optionally then
        changing its own key's value inside the merge."""
        dump = lambda d: [json.dumps(d, indent=1)]
        keys = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
        self.g("checkout", "-q", "base")
        self.write("data.json", dump(keys))
        self.commit("data")
        self.g("checkout", "-q", "feat")
        self.g("merge", "-q", "--no-edit", "base")
        self.write("data.json", dump(dict(keys, x=7)))
        self.reviewed = self.commit("the PR adds a key")
        self.record(time=self.OLD)
        self.g("checkout", "-q", "base")
        self.write("data.json", dump({"b": 2, "a": 1, "c": 3, "d": 4, "e": 5}))
        self.commit("base reorders")
        self.g("checkout", "-q", "feat")
        self.g("merge", "-q", "--no-commit", "base")
        if change_value:
            merged = json.loads((self.root / "data.json").read_text())
            merged["x"] = 8
            self.write("data.json", dump(merged))
        self.commit("merge")
        return self.delta()

    def test_a_json_reorder_is_a_derived_cover(self):
        r = self.json_case(change_value=False)
        self.assertEqual((r["status"], r.get("derived")), ("carries", True), r.get("derive"))

    def test_a_json_value_change_is_not_derived(self):
        r = self.json_case(change_value=True)
        self.assertEqual(r["status"], "recheck")
        self.assertIn("data.json", r["derive"])

    def test_json_delta_ignores_order_not_values(self):
        d = reviewpin.json_delta
        self.assertEqual(d({"a": [1, 2], "b": 1}, {"b": 1, "a": [2, 1]}), [])
        self.assertTrue(d({"a": 1}, {"a": 2}))
        self.assertEqual(d([{"k": 1}], [{"k": 1}, {"k": 2}]), [("$", "entry added", '{"k":2}')])

    def own_edit_in_merge(self):
        self.record(time=self.OLD)
        self.base_moves_context()
        self.g("merge", "-q", "--no-commit", "base")
        a = (self.root / "a.txt").read_text().splitlines()
        a[9] = "line 10 changed again in the merge"
        self.write("a.txt", a)
        self.commit("merge with an edit")
        return self.delta()

    def test_explain_names_each_check_and_the_items_that_differ(self):
        r = self.own_edit_in_merge()
        x = reviewpin.explain(self.root, 7, head="feat", base="base", fetch=False)
        self.assertEqual((x["status"], x["exit"], x["derive"]), (r["status"], r["exit"], r["derive"]))
        kinds = [(c["check"], c["ok"]) for c in x["checks"]]
        self.assertEqual(kinds, [("commit", True), ("own change", False), ("replay", False)])
        own = x["checks"][1]
        self.assertNotIn("old", own)
        self.assertEqual(own["compare"]["mode"], "text")
        self.assertEqual(own["compare"]["head_only"], ["+line 10 changed again in the merge"])
        self.assertEqual(own["compare"]["pin_only"], ["+line 10 changed by the PR"])
        text = reviewpin.format_explain(x)
        for want in ("derived cover: refused", "FAIL own change a.txt", "[-U0 lines]", "only at the head: 1",
                     "OK   commit", "FAIL replay"):
            self.assertIn(want, text)

    def test_explain_agrees_with_delta(self):
        def context():
            self.record(time=self.OLD)
            self.base_moves_context()
            self.g("merge", "-q", "--no-edit", "base")
            return self.delta()

        cases = {"context": context, "json": lambda: self.json_case(False), "json edit": lambda: self.json_case(True),
                 "own edit": self.own_edit_in_merge}
        for name, make in cases.items():
            with self.subTest(case=name):
                self.tearDown()
                self.setUp()
                r = make()
                x = reviewpin.explain(self.root, 7, head="feat", base="base", fetch=False)
                self.assertEqual((x["status"], x.get("derived"), x["derive"]),
                                 (r["status"], r.get("derived"), r["derive"]))
                self.assertTrue(all(c["ok"] for c in x["checks"]) == bool(r.get("derived")))
                json.dumps(x)                                                  # serializable for --json

    def test_a_conflict_resolved_by_hand_is_not_derived(self):
        self.record(time=self.OLD)
        self.g("checkout", "-q", "base")
        a = list(LINES)
        a[9] = "line 10 changed on the base"
        self.write("a.txt", a)
        self.commit("base edits the PR's line")
        self.g("checkout", "-q", "feat")
        subprocess.run(["git", "merge", "-q", "--no-edit", "base"], cwd=self.root, env=ENV, capture_output=True)
        a[9] = "line 10 changed by the PR"
        self.write("a.txt", a)
        self.commit("merge, conflict resolved by hand")
        x = reviewpin.explain(self.root, 7, head="feat", base="base", fetch=False)
        self.assertEqual(x["status"], "recheck")
        self.assertIn("resolves a conflict in a.txt by hand", [c["why"] for c in x["checks"] if c["check"] == "replay"][0])

    def test_explain_runs_every_check_after_a_failure(self):
        self.record(time=self.OLD)
        self.base_moves_context()
        self.g("merge", "-q", "--no-edit", "base")
        self.write("docs/notes.md", ["notes", "more"])
        self.commit("own edit after the merge")
        x = reviewpin.explain(self.root, 7, head="feat", base="base", fetch=False)
        self.assertIn("is not a merge", x["derive"])
        self.assertEqual([c["check"] for c in x["checks"]][0], "commit")
        self.assertIn("own change", [c["check"] for c in x["checks"]])     # stop=True would have ended at the commit
        self.assertIn("replay", [c["check"] for c in x["checks"]])

    def test_explain_focuses_long_items_where_they_differ(self):
        long_a = "+| row | " + "x" * 300 + " old tail"
        long_b = "+| row | " + "x" * 300 + " new tail"
        x = reviewpin.explain_own_change(("text", (), (long_a,)), ("text", (), (long_b,)))
        self.assertTrue(x["head_only"][0].endswith("new tail"), x["head_only"])
        self.assertTrue(x["pin_only"][0].endswith("old tail"))
        self.assertTrue(x["head_only"][0].startswith("+| row | "))
        self.assertLessEqual(len(x["head_only"][0]), reviewpin.LINE_CUT + 4)

    def test_cli_explain(self):
        self.record(time=self.OLD)
        self.base_moves_context()
        self.g("merge", "-q", "--no-edit", "base")
        code, out, _ = self.cli("explain", "7", "--head", "feat", "--base", "base")
        self.assertEqual(code, 0)
        self.assertIn("derived cover: yes", out)
        self.assertIn("OK   own change a.txt  [-U0 lines]", out)
        code, out, _ = self.cli("explain", "7", "--head", "feat", "--base", "base", "--json")
        self.assertEqual(json.loads(out)["checks"][-1]["check"], "replay")
        code, out, _ = self.cli("explain", "9", "--head", "feat", "--base", "base")
        self.assertEqual(code, reviewpin.EXIT_NO_VERDICT)

    def test_the_log_path_is_configurable(self):
        code, _, _ = self.cli("--log", "ops/verdicts.jsonl", "record", "7", self.reviewed, "GO", "--base", "base")
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "ops" / "verdicts.jsonl").is_file())
        self.assertFalse((self.root / reviewpin.LOG).exists())
        code, out, _ = self.cli("--log", "ops/verdicts.jsonl", "delta", "7", "--head", "feat", "--base", "base",
                                "--json")
        self.assertEqual((code, json.loads(out)["status"]), (0, "carries"))
        code, _, _ = self.cli("delta", "7", "--head", "feat", "--base", "base")
        self.assertEqual(code, reviewpin.EXIT_NO_VERDICT)
        self.assertEqual(reviewpin.default_root(self.root / "ops"), Path(self.g("rev-parse", "--show-toplevel")))

    def test_no_verdict(self):
        r = self.delta()
        self.assertEqual((r["status"], r["exit"]), ("no-verdict", reviewpin.EXIT_NO_VERDICT))

    def test_head_is_reviewed_commit(self):
        self.record()
        r = self.delta()
        self.assertEqual((r["status"], r["exit"]), ("carries", 0))
        self.assertIn("the head is the reviewed commit", r["notes"])

    def test_base_merged_in_carries_then_real_edit_needs_recheck(self):
        self.record()
        self.merge_base_in()
        r = self.delta()
        self.assertEqual((r["status"], r["exit"], r["changes"]), ("carries", 0, []), r)
        self.assertIn("own patch identical", r["message"])
        self.assertNotEqual(r["reviewed_base"], r["head_base"])

        a = (self.root / "a.txt").read_text().splitlines()
        a[14] = "line 15 edited after review"
        self.write("a.txt", a)
        self.commit("real edit")
        r = self.delta()
        self.assertEqual((r["status"], r["exit"]), ("recheck", reviewpin.EXIT_RECHECK))
        self.assertEqual([c["path"] for c in r["changes"]], ["a.txt"])
        new = r["changes"][0]["new_hunks"]
        # With three context lines the edit at line 15 joins the PR's hunk at line 10.
        self.assertEqual([x for x in new[0]["lines"] if x[:1] in "+-"],
                         ["-line 10", "+line 10 changed by the PR", "-line 15", "+line 15 edited after review"])
        self.assertIn(" line 12", new[0]["lines"])
        self.assertEqual([len(r["changes"][0]["gone_hunks"]), len(new)], [1, 1])
        self.assertIn("line 15 edited after review", reviewpin.format_delta(r))

    def test_moved_own_line_needs_recheck(self):
        # The PR adds a line, is reviewed, then moves that same line elsewhere: the + body is unchanged, so only
        # the context lines around it tell the two patches apart.
        a = (self.root / "a.txt").read_text().splitlines()
        a.insert(5, "authorize(user)")
        self.write("a.txt", a)
        sha = self.commit("add the check")
        self.record(sha=sha)
        a.remove("authorize(user)")
        a.insert(19, "authorize(user)")
        self.write("a.txt", a)
        self.commit("move the check")
        r = self.delta()
        self.assertEqual((r["status"], r["exit"]), ("recheck", reviewpin.EXIT_RECHECK), r)
        self.assertIn("a.txt", [c["path"] for c in r["changes"]])
        self.assertTrue(any("+authorize(user)" in h["lines"] for c in r["changes"] if c["path"] == "a.txt"
                            for h in c["new_hunks"]))

    def test_reverted_hunk_shows_as_gone(self):
        self.record()
        self.write("a.txt", LINES)
        self.commit("drop the PR's change")
        r = self.delta()
        self.assertEqual(r["status"], "recheck")
        c = r["changes"][0]
        self.assertEqual((c["path"], c["change"]), ("a.txt", "dropped from the PR since review"))
        self.assertEqual(c["gone_hunks"][0]["lines"], [" line 7", " line 8", " line 9", "-line 10",
                                                       "+line 10 changed by the PR", " line 11", " line 12", " line 13"])

    def test_edit_outside_scope_carries(self):
        self.record(scope=["a.txt"])
        self.merge_base_in()
        self.write("docs/notes.md", ["notes", "more notes"])
        self.commit("notes only")
        r = self.delta()
        self.assertEqual((r["status"], r["exit"]), ("carries", 0), r)
        self.assertIn("outside the review's scope", r["message"])
        self.assertEqual([(c["path"], c["in_scope"]) for c in r["changes"]], [("docs/notes.md", False)])
        # The same edit with no scope recorded needs a recheck.
        self.record(time="2099-01-01T00:00:00Z")
        self.assertEqual(self.delta()["status"], "recheck")

    def test_scope_folder_and_glob(self):
        self.assertTrue(reviewpin.in_scope("docs/notes.md", ["docs/"]))
        self.assertTrue(reviewpin.in_scope("docs/notes.md", ["docs"]))
        self.assertTrue(reviewpin.in_scope("kit/x.py", ["kit/*.py"]))
        self.assertFalse(reviewpin.in_scope("docsx/notes.md", ["docs"]))

    def test_nogo_stands_until_the_patch_changes(self):
        self.record("no-go")
        self.merge_base_in()
        r = self.delta()
        self.assertEqual((r["status"], r["exit"]), ("nogo", reviewpin.EXIT_NOGO))
        self.write("a.txt", LINES[:-1])
        self.commit("fix")
        self.assertEqual(self.delta()["exit"], reviewpin.EXIT_RECHECK)

    def test_latest_verdict_wins(self):
        self.record("NO-GO", time="2026-11-01T00:00:00Z")
        self.record("GO", time="2026-11-02T00:00:00Z")
        self.assertEqual(self.delta()["verdict"], "GO")

    def test_head_falls_back_to_stored_branch(self):
        rec = self.record()
        self.assertEqual(rec["branch"], "feat")
        r = self.delta(head=None, fetch=False)
        self.assertEqual((r["head_ref"], r["status"]), ("feat", "carries"))

    def test_fetch_failure_is_a_note(self):
        self.record()
        r = self.delta(head=None, fetch=True)       # no origin remote: the fetch fails, no network is used
        self.assertTrue(any(n.startswith("fetch failed") for n in r["notes"]), r["notes"])
        self.assertEqual(r["head_ref"], "feat")

    def test_record_validates(self):
        with self.assertRaises(reviewpin.PinError):
            reviewpin.make_record(self.root, 7, "0" * 40, "GO", base="base")
        with self.assertRaises(reviewpin.PinError):
            reviewpin.make_record(self.root, 7, self.reviewed, "MAYBE", base="base")
        with self.assertRaises(reviewpin.PinError):
            reviewpin.make_record(self.root, "x7", self.reviewed, "GO", base="base")
        rec = reviewpin.make_record(self.root, "#7", self.reviewed[:9], "go-with-notes", base="base")
        self.assertEqual((rec["pr"], rec["sha"], rec["verdict"]), (7, self.reviewed, "GO-WITH-NOTES"))
        self.assertEqual(rec["merge_base"], self.g("rev-parse", "base"))

    def cli(self, *argv):
        p = argparse.ArgumentParser()
        reviewpin.add_arguments(p)
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = reviewpin.run(p.parse_args(list(argv)), root=self.root)
        return code, buf.getvalue(), err.getvalue()

    def test_cli_record_list_delta(self):
        code, out, _ = self.cli("record", "7", self.reviewed, "GO", "--base", "base", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        self.assertFalse((self.root / reviewpin.LOG).exists())
        code, out, _ = self.cli("record", "7", self.reviewed, "GO", "--base", "base", "--scope", "a.txt",
                                "--reviewer", "r1", "--note", "fine")
        self.assertEqual(code, 0)
        lines = (self.root / reviewpin.LOG).read_text().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        for key in ("pr", "sha", "verdict", "scope", "reviewer", "time", "note"):
            self.assertIn(key, rec)
        self.assertTrue(rec["time"].endswith("Z"))
        code, out, _ = self.cli("list", "--pr", "7", "--json")
        self.assertEqual(json.loads(out)[0]["note"], "fine")
        code, out, _ = self.cli("list", "--pr", "8")
        self.assertIn("no verdicts", out)
        code, out, _ = self.cli("delta", "7", "--head", "feat", "--base", "base", "--json")
        self.assertEqual((code, json.loads(out)["status"]), (0, "carries"))
        code, out, err = self.cli("delta", "7", "--head", "nope", "--base", "base")
        self.assertEqual(code, reviewpin.EXIT_ERROR)
        self.assertIn("--head not found", err)
        code, out, _ = self.cli("delta", "9", "--head", "feat", "--base", "base", "--no-fetch")
        self.assertEqual(code, reviewpin.EXIT_NO_VERDICT)

    def test_head_already_merged_into_base(self):
        self.record()
        self.g("checkout", "-q", "base")
        self.g("merge", "-q", "--no-edit", "feat")
        with self.assertRaisesRegex(reviewpin.PinError, "already in base"):
            self.delta()
        rec = reviewpin.make_record(self.root, 7, self.reviewed, "GO", base="base")
        self.assertIsNone(rec["merge_base"])

    def test_malformed_log(self):
        path = self.root / reviewpin.LOG
        path.parent.mkdir(parents=True)
        path.write_text("{not json\n")
        with self.assertRaises(reviewpin.PinError):
            reviewpin.read_log(self.root)


class SplitPatchTest(unittest.TestCase):
    def test_line_numbers_and_index_dropped(self):
        a = ("diff --git a/x b/x\nindex 111..222 100644\n--- a/x\n+++ b/x\n@@ -5 +5 @@\n-old\n+new\n")
        b = ("diff --git a/x b/x\nindex 333..444 100644\n--- a/x\n+++ b/x\n@@ -9 +9 @@\n-old\n+new\n")
        self.assertEqual(reviewpin.compare(reviewpin.split_patch(a), reviewpin.split_patch(b)), [])


if __name__ == "__main__":
    unittest.main()
