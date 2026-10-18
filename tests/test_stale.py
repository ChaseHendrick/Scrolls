"""kit stale: each of the nine checks finds what it should and passes what it should, on small synthetic git
repositories with commits at fixed dates; the committed registries load (docs/renames.json here; Scrolls-private's
docs/compute/freezes.json where it exists); malformed registries fail instead of passing; exit codes; the CLI wiring
and the routine. Public copy of Scrolls-private's tests/test_stale.py: the approval findings need kit/budget.py
(private only) and are skipped here, and public adds the default-branch-only and shallow-clone tests, the routine's
ci mark and the live pages' names."""

import csv
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kit import routines, stale

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
HAS_GIT = shutil.which("git") is not None
HAS_BUDGET = importlib.util.find_spec("kit.budget") is not None
LEDGER_HEADER = ["date_time_et", "lane_branch", "purpose", "app_id", "gpu_type", "gpu_count", "gpu_seconds",
                 "cpu_seconds", "est_cost_usd", "actual_cost_usd_if_known", "cumulative_usd", "notes"]


def table(*rows):
    return "\n".join(["| Item | State |", "| --- | --- |"] + [f"| {a} | {b} |" for a, b in rows]) + "\n"


class Repo:
    """A throwaway git repository whose commits carry chosen dates."""

    def __init__(self, test):
        self.dir = Path(tempfile.mkdtemp(prefix="stale-test-"))
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args, when=None):
        env = dict(os.environ)
        if when is not None:
            stamp = when.strftime("%Y-%m-%dT%H:%M:%S+00:00")
            env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
        return subprocess.run(["git", "-C", str(self.dir), *args], check=True, capture_output=True, text=True,
                              env=env).stdout.strip()

    def write(self, rel, text):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, when, files, message="change"):
        for rel, text in files.items():
            self.write(rel, text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, when=when)
        return self.git("rev-parse", "HEAD")


def days_ago(n):
    return NOW - timedelta(days=n)


@unittest.skipUnless(HAS_GIT, "git is not installed")
class HandoffChecks(unittest.TestCase):
    def test_table_rows_skip_headers_and_separators(self):
        text = "text\n" + table(("A", "1"), ("B", "2")) + "\n| Other | x |\n| :--- | --- |\n| C | 3 |\n"
        rows = stale.table_rows(text)
        self.assertEqual([r[2] for r in rows], ["A", "B", "C"])
        self.assertEqual(rows[0][0], 4)

    def test_rows_unchanged_for_a_week_need_a_look(self):
        repo = Repo(self)
        repo.commit(days_ago(10), {stale.HANDOFF: table(("Old row", "x"), ("Kept row", "y"))})
        repo.commit(days_ago(1), {stale.HANDOFF: table(("Old row", "x"), ("Kept row", "changed"))})
        res = stale.check_handoff_rows(repo.dir, stale.Git(repo.dir), NOW)
        self.assertEqual(res["status"], stale.ATTENTION)
        self.assertEqual(len(res["findings"]), 1)
        self.assertIn('"Old row"', res["findings"][0].text)
        self.assertTrue(res["findings"][0].where.endswith(":3"))

    def test_uncommitted_rows_are_young(self):
        repo = Repo(self)
        repo.commit(days_ago(10), {stale.HANDOFF: table(("Old row", "x"))})
        repo.write(stale.HANDOFF, table(("Old row", "edited now")))
        self.assertEqual(stale.check_handoff_rows(repo.dir, stale.Git(repo.dir), NOW)["status"], stale.OK)

    def test_missing_handoff_or_git_is_skipped(self):
        empty = Path(tempfile.mkdtemp(prefix="stale-empty-"))
        self.addCleanup(shutil.rmtree, empty, True)
        git = stale.Git(empty)
        self.assertFalse(git.ok)
        self.assertEqual(stale.check_handoff_rows(empty, git, NOW)["status"], stale.SKIPPED)
        (empty / "docs").mkdir()
        (empty / stale.HANDOFF).write_text(table(("Row", "x")), encoding="utf-8")
        self.assertEqual(stale.check_handoff_rows(empty, git, NOW)["status"], stale.SKIPPED)

    def test_branches_gone_or_merged_without_saying_so(self):
        repo = Repo(self)
        repo.commit(days_ago(5), {"a.txt": "a"})
        repo.git("checkout", "-q", "-b", "claude/done")
        repo.commit(days_ago(4), {"b.txt": "b"})
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "-m", "merge", "claude/done", when=days_ago(3))
        repo.git("branch", "-q", "claude/open")
        repo.git("checkout", "-q", "claude/open")
        repo.commit(days_ago(2), {"c.txt": "c"})
        repo.git("checkout", "-q", "main")
        repo.commit(days_ago(1), {stale.HANDOFF: table(
            ("Gone", "on branch `claude/deleted-after-merge`"),
            ("Quiet", "work on `claude/done`, not pushed"),
            ("Said", "`claude/done` merged in #12"),
            ("Open", "branch claude/open, review pending."),
            ("Default", "`grok/laneJ-title` and `main`"))})
        res = stale.check_branches(repo.dir, stale.Git(repo.dir), NOW)
        texts = [f.text for f in res["findings"]]
        self.assertEqual(len(texts), 2, texts)
        self.assertIn("claude/deleted-after-merge, which this clone does not have", texts[0])
        self.assertIn("claude/done, which is merged into main, but the row says not merged", texts[1])

    def merged_repo(self):
        repo = Repo(self)
        repo.commit(days_ago(5), {"a.txt": "a"})
        repo.git("checkout", "-q", "-b", "claude/done")
        repo.commit(days_ago(4), {"b.txt": "b"})
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "-m", "merge", "claude/done", when=days_ago(3))
        return repo

    def branch_texts(self, repo, *rows):
        repo.commit(days_ago(1), {stale.HANDOFF: table(*rows)})
        return [f.text for f in stale.check_branches(repo.dir, stale.Git(repo.dir), NOW)["findings"]]

    def test_merge_wording_is_judged_per_mention(self):
        repo = self.merged_repo()
        texts = self.branch_texts(
            repo,
            ("Not yet", "`claude/done`, not merged yet"),
            ("Unmerged", "`claude/done` (unmerged)"),
            ("Other item", "Fix on `claude/done`, not pushed. Earlier: fix merged (#685)"),
            ("Two in one", "`claude/done` not merged, `claude/other` merged"),
            ("Said", "Fix on `claude/done`, merged in #12"),
            ("Twice", "on `claude/done`. Later `claude/done` merged"))
        texts = [t for t in texts if "claude/done" in t]
        self.assertEqual(len(texts), 4, texts)
        for item, text in zip(("Not yet", "Unmerged", "Other item", "Two in one"), texts):
            self.assertIn(f'row "{item}" names branch claude/done, which is merged into main', text)
        self.assertEqual(stale.merge_wording("a `b` merged, `c` not merged", 3, 4), "merged")
        self.assertEqual(stale.merge_wording("a `b` merged, `c` not merged", 15, 16), "not merged")

    def test_placeholder_patterns_are_not_branches(self):
        repo = self.merged_repo()
        self.assertEqual(stale.branch_mentions("each on `claude/work-<name>` or claude/x-wip-* or claude/y-{a,b}"), [])
        self.assertEqual([m[0] for m in stale.branch_mentions("branch claude/open.")], ["claude/open"])
        self.assertEqual(self.branch_texts(repo, ("Pattern", "on its own `claude/work-<name>` branch")), [])

    def test_gone_branch_with_its_pr_or_commit_is_quiet(self):
        repo = self.merged_repo()
        texts = self.branch_texts(
            repo,
            ("PR", "`claude/x` merged in #12; branch deleted by GitHub"),
            ("Commit", "`claude/y` at `abc1234f`, merged"),
            ("Link", "`claude/z` ([PR](https://github.com/o/r/pull/7))"),
            ("Bare", "`claude/w` merged"),
            ("Elsewhere", "`claude/v`, not pushed. PR #9 is unrelated"))
        self.assertEqual(len(texts), 2, texts)
        self.assertIn("claude/w, which this clone does not have", texts[0])
        self.assertIn("claude/v, which this clone does not have", texts[1])

    def test_branch_without_commits_of_its_own_is_not_merged(self):
        repo = self.merged_repo()
        repo.git("branch", "-q", "claude/fresh")
        git = stale.Git(repo.dir)
        self.assertTrue(git.merged_into("claude/done", "main"))
        self.assertFalse(git.merged_into("claude/fresh", "main"))
        self.assertEqual(self.branch_texts(repo, ("Fresh", "starting on `claude/fresh`")), [])

    def test_default_branch_only_clone_skips_branches_and_notes_shallow(self):
        # The routines workflow checks out main at depth 1: no other branch, and every line dates to the tip.
        repo = Repo(self)
        repo.commit(days_ago(10), {stale.HANDOFF: table(("Old", "on `claude/gone`"))})
        repo.commit(days_ago(9), {"a.txt": "a"})
        tmp = Path(tempfile.mkdtemp(prefix="stale-clone-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        clone = tmp / "c"
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--single-branch", "--branch", "main",
                        repo.dir.as_uri(), str(clone)], check=True, capture_output=True)
        git = stale.Git(clone)
        self.assertTrue(git.shallow())
        res = stale.check_branches(clone, git, NOW)
        self.assertEqual(res["status"], stale.SKIPPED)
        self.assertIn("holds a single branch", res["info"][0])
        # So does a run by hand on another branch: one branch, and main absent.
        repo.git("checkout", "-q", "-b", "claude/manual")
        other = tmp / "o"
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--single-branch", "--branch", "claude/manual",
                        repo.dir.as_uri(), str(other)], check=True, capture_output=True)
        repo.git("checkout", "-q", "main")
        self.assertEqual(stale.check_branches(other, stale.Git(other), NOW)["status"], stale.SKIPPED)
        rows = stale.check_handoff_rows(clone, git, NOW)
        self.assertEqual(len(rows["findings"]), 1)
        self.assertIn("last changed 2026-10-23", rows["findings"][0].text)   # the tip's date: a lower bound
        self.assertIn("ages are lower bounds", rows["info"][-1])
        # The full repository, with two branches, runs the branch check and has no shallow note.
        full = stale.Git(repo.dir)
        self.assertFalse(full.shallow())
        res = stale.check_branches(repo.dir, full, NOW)
        self.assertEqual(res["status"], stale.ATTENTION)
        self.assertIn("claude/gone, which this clone does not have", res["findings"][0].text)
        rows = stale.check_handoff_rows(repo.dir, full, NOW)
        self.assertIn("last changed 2026-10-22", rows["findings"][0].text)
        self.assertEqual(len(rows["info"]), 1)

    def test_container_paths(self):
        row = ("| x | worktree /home/user/sp-strokenet, notes in /tmp/claude-0/-home-user/abc/scratchpad/n.md, "
               "checkout /home/user/Scrolls-private and /home/user/Scrolls/docs/x.md, local /home/user/Scrolls-private/"
               "work/round9/ |")
        self.assertEqual(stale.container_paths(row), ["/home/user/sp-strokenet",
                                                      "/tmp/claude-0/-home-user/abc/scratchpad/n.md",
                                                      "/home/user/Scrolls-private/work/round9/"])

    def test_rows_naming_container_paths_after_two_days(self):
        repo = Repo(self)
        repo.commit(days_ago(3), {stale.HANDOFF: table(("Old path", "in /home/user/sp-x"),
                                                       ("Checkout", "run from /home/user/Scrolls-private"))})
        repo.commit(days_ago(1), {stale.HANDOFF: table(("Old path", "in /home/user/sp-x"),
                                                       ("Checkout", "run from /home/user/Scrolls-private"),
                                                       ("New path", "in /home/user/sp-y"))})
        res = stale.check_handoff_paths(repo.dir, stale.Git(repo.dir), NOW)
        self.assertEqual(len(res["findings"]), 1)
        self.assertIn("/home/user/sp-x", res["findings"][0].text)
        self.assertEqual(stale.check_handoff_paths(repo.dir, stale.Git(repo.dir), NOW, days=5)["status"], stale.OK)


class Names(unittest.TestCase):
    RENAME = {"old": "Greek letter reader", "new": "Scroll Text Reader", "since": "2026-10-18", "source": "test"}

    def test_old_name_alone_is_stale(self):
        text = ("The Greek letter reader reads lines.\n"
                "Scroll Text Reader, formerly the Greek letter reader.\n"
                "```\nGreek letter reader in output\n```\n"
                "- 2026-10-14: released with the Greek letter reader\n"
                "- 2026-10-19: the greek letter reader again\n")
        self.assertEqual(stale.stale_name_lines(text, self.RENAME), [1, 7])

    def test_table_rows_keep_and_inline_code(self):
        rename = dict(self.RENAME, old="letter reader", keep=["letter reader is called Scroll Text Reader"])
        text = ("| Scroll Text Reader, formerly the Greek letter reader | x |\n"
                "| `scrolls-workbench` (letter reader, StrokeNet) | x |\n"
                "| `no public letter reader at` | an error message |\n"
                "| 2026-10-18 | The Greek letter reader is called Scroll Text Reader |\n"
                "Scroll Text Reader was called the letter reader until 17 Oct.\n"
                "A newsletter reader is something else.\n")
        self.assertEqual(stale.stale_name_hits(text, rename), [(1, True), (2, True)])
        strict = dict(rename, allow_formerly=False)
        self.assertEqual(stale.stale_name_lines(text, strict), [1, 2, 5])

    def test_check_names_on_live_pages_only(self):
        d = Path(tempfile.mkdtemp(prefix="stale-names-"))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "docs" / "tools").mkdir(parents=True)
        (d / "docs" / "logs").mkdir()
        (d / stale.RENAMES).write_text(json.dumps({"renames": [self.RENAME]}), encoding="utf-8")
        (d / "docs" / "tools" / "x.md").write_text("Uses the Greek letter reader.\n", encoding="utf-8")
        (d / "docs" / "logs" / "old.md").write_text("Uses the Greek letter reader.\n", encoding="utf-8")
        (d / "README.md").write_text("Scroll Text Reader, formerly the Greek letter reader.\n"
                                     "| Scroll Text Reader, formerly the Greek letter reader | x |\n", encoding="utf-8")
        res = stale.check_names(d)
        self.assertEqual([f.where for f in res["findings"]], ["README.md:2", "docs/tools/x.md:1"])
        self.assertIn('a table row names the thing, so write "Scroll Text Reader" alone', res["findings"][0].text)
        self.assertNotIn("formerly", res["findings"][0].text + res["findings"][1].text)

    def test_a_longer_old_name_flags_a_line_once(self):
        d = Path(tempfile.mkdtemp(prefix="stale-names-"))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "docs").mkdir()
        short = dict(self.RENAME, old="letter reader")
        (d / stale.RENAMES).write_text(json.dumps({"renames": [self.RENAME, short]}), encoding="utf-8")
        (d / "README.md").write_text("The Greek letter reader.\nThe letter reader.\n", encoding="utf-8")
        res = stale.check_names(d)
        self.assertEqual([(f.where, f.text.split(",")[0]) for f in res["findings"]],
                         [("README.md:1", 'says "Greek letter reader"'), ("README.md:2", 'says "letter reader"')])

    def test_bad_renames_fail(self):
        d = Path(tempfile.mkdtemp(prefix="stale-names-"))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "docs").mkdir()
        good = {"old": "a", "new": "b", "since": "2026-10-18", "source": "s"}
        for bad in ({"renames": [{"old": "a", "new": "b", "since": "18 Oct"}]}, {"renames": {}}, [1],
                    {"renames": [dict(good, keep="a b")]}, {"renames": [dict(good, keep=[""])]},
                    {"renames": [dict(good, allow_formerly="no")]}):
            (d / stale.RENAMES).write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(stale.StaleError):
                stale.load_renames(d)
        (d / stale.RENAMES).write_text("{not json", encoding="utf-8")
        with self.assertRaises(stale.StaleError):
            stale.load_renames(d)
        self.assertEqual(stale.run_checks(d, NOW, only=("names",))["exit"], stale.EXIT_FAIL)

    def test_no_renames_file_is_skipped(self):
        d = Path(tempfile.mkdtemp(prefix="stale-names-"))
        self.addCleanup(shutil.rmtree, d, True)
        self.assertEqual(stale.check_names(d)["status"], stale.SKIPPED)


@unittest.skipUnless(HAS_GIT, "git is not installed")
class LinksAndMap(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.repo.commit(days_ago(2), {
            "README.md": "[ok](docs/README.md) [dead](docs/gone.md) [web](https://x.org) [anchor](#top)\n"
                         "```\n[in code](nowhere.md)\n```\n",
            "docs/README.md": "[up](../README.md) [tool](tools/a.md) [pending](tools/later.md) [dir](tools/)\n",
            "docs/tools/a.md": "[wrong](docs/HANDOFF.md)\n",
            "docs/tools/pending.json": json.dumps({"pages": ["later"]}),
            "docs/MAP.md": "| `kit/a.py`, `kit/gone.py` | x |\n| `scripts/s/` | y; shipped in the cut as "
                           "`scripts/other.py` |\n",
            "kit/__init__.py": "", "kit/__main__.py": "", "kit/a.py": "", "kit/b.py": "", "scripts/s/run.py": ""})

    def test_dead_links(self):
        res = stale.check_links(self.repo.dir, stale.Git(self.repo.dir))
        self.assertEqual([(f.where, f.text) for f in res["findings"]],
                         [("README.md", "link to docs/gone.md does not resolve"),
                          ("docs/tools/a.md", "link to docs/HANDOFF.md does not resolve")])

    def test_links_without_git_use_the_disk(self):
        res = stale.check_links(self.repo.dir, None)
        self.assertIn("link to tools/later.md does not resolve", [f.text for f in res["findings"]])

    def test_map(self):
        res = stale.check_map(self.repo.dir, stale.Git(self.repo.dir))
        texts = [f.text for f in res["findings"]]
        self.assertEqual(len(texts), 2, texts)
        self.assertIn("names kit/gone.py", texts[0])
        self.assertIn("1 kit modules have no row: kit/b.py", texts[1])


@unittest.skipUnless(HAS_GIT, "git is not installed")
class RoutinesCheck(unittest.TestCase):
    def registry(self, *names):
        return json.dumps({"routines": [{"name": n, "requires": [f"kit/{n}.py"]} for n in names]}, indent=2)

    def test_routine_waiting_over_a_week(self):
        repo = Repo(self)
        repo.commit(days_ago(10), {stale.ROUTINES: self.registry("old")})
        repo.commit(days_ago(2), {stale.ROUTINES: self.registry("old", "new", "here"), "kit/here.py": ""})
        res = stale.check_routines(repo.dir, stale.Git(repo.dir), NOW)
        self.assertEqual(len(res["findings"]), 1)
        self.assertIn("routine old has waited 10 days", res["findings"][0].text)
        self.assertIn("3 routines, 2 waiting", res["info"][0])

    def test_bad_registry_fails(self):
        repo = Repo(self)
        repo.commit(days_ago(1), {stale.ROUTINES: json.dumps({"routines": {}})})
        with self.assertRaises(stale.StaleError):
            stale.check_routines(repo.dir, stale.Git(repo.dir), NOW)


def freeze(**kw):
    entry = {"id": "f", "prereg": "docs/prereg/p.md", "freezing_commit": "0" * 40, "state": "live",
             "collected_on": None, "note": "n"}
    entry.update(kw)
    return entry


@unittest.skipUnless(HAS_GIT, "git is not installed")
class Freezes(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.main = self.repo.commit(days_ago(20), {"docs/prereg/p.md": "frozen"}, "freeze")
        self.repo.git("checkout", "-q", "-b", "claude/side")
        self.side = self.repo.commit(days_ago(3), {"docs/prereg/side.md": "side"}, "side freeze")
        self.repo.git("checkout", "-q", "main")

    def run_check(self, *entries, days=14):
        self.repo.write(stale.FREEZES, json.dumps({"freezes": list(entries)}))
        return stale.check_freezes(self.repo.dir, stale.Git(self.repo.dir), NOW, days=days)

    def test_live_freeze_older_than_two_weeks(self):
        res = self.run_check(freeze(freezing_commit=self.main))
        self.assertEqual(len(res["findings"]), 1)
        self.assertIn("live since 2026-10-12, nothing collected, 20 days", res["findings"][0].text)

    def test_recent_collection_or_spent_is_quiet(self):
        self.assertEqual(self.run_check(freeze(freezing_commit=self.main, collected_on="2026-10-25"))["status"],
                         stale.OK)
        self.assertEqual(self.run_check(freeze(freezing_commit=self.main, state="spent",
                                               collected_on="2026-10-13"))["status"], stale.OK)

    def test_frozen_on_overrides_the_commit_date(self):
        res = self.run_check(freeze(freezing_commit=self.main, frozen_on="2026-10-30"))
        self.assertEqual(res["status"], stale.OK)

    def test_commit_reachability(self):
        res = self.run_check(freeze(id="side", prereg="docs/prereg/side.md", freezing_commit=self.side[:8],
                                    branch="claude/side", frozen_on="2026-10-29"))
        self.assertEqual(res["status"], stale.OK, res["findings"])
        res = self.run_check(freeze(id="side", prereg="docs/prereg/side.md", freezing_commit=self.side[:8],
                                    frozen_on="2026-10-29"))
        self.assertIn("is not on main and no branch is recorded", res["findings"][0].text)
        self.repo.git("branch", "-q", "-D", "claude/side")
        res = self.run_check(freeze(id="side", prereg="docs/prereg/side.md", freezing_commit=self.side[:8],
                                    branch="claude/side", frozen_on="2026-10-29"))
        self.assertIn("branch claude/side is not in this clone", res["findings"][0].text)

    def test_missing_commit_and_prereg(self):
        res = self.run_check(freeze(freezing_commit="abcdef1234", prereg="docs/prereg/none.md",
                                    frozen_on="2026-10-30", branch="claude/gone"))
        texts = [f.text for f in res["findings"]]
        self.assertIn("freezing commit abcdef1234 (branch claude/gone) is not in this clone", texts[0])
        self.assertIn("prereg docs/prereg/none.md is neither in the working tree nor at abcdef1234", texts[1])

    def test_prereg_only_at_its_commit_is_found(self):
        self.repo.git("checkout", "-q", "claude/side")
        self.repo.git("checkout", "-q", "main")
        res = self.run_check(freeze(prereg="docs/prereg/side.md", freezing_commit=self.side, branch="claude/side",
                                    frozen_on="2026-10-29"))
        self.assertEqual(res["status"], stale.OK, res["findings"])

    def test_malformed_registry_fails(self):
        bad = [freeze(state="frozen"), freeze(state="spent"), freeze(freezing_commit="xyz"), freeze(note=""),
               freeze(collected_on="18 Oct")]
        for entry in bad:
            with self.assertRaises(stale.StaleError, msg=entry):
                self.run_check(entry)
        no_collected = freeze()
        del no_collected["collected_on"]
        with self.assertRaises(stale.StaleError):
            self.run_check(no_collected)
        with self.assertRaises(stale.StaleError):
            self.run_check(freeze(), freeze())

    def test_no_registry_is_skipped(self):
        self.assertEqual(stale.check_freezes(self.repo.dir, stale.Git(self.repo.dir), NOW)["status"], stale.SKIPPED)


class Approvals(unittest.TestCase):
    def approvals(self, *entries):
        return {"ceiling": {"usd": 500}, "billed": [{"usd": 10, "at": "2026-10-10T00:00:00Z", "source": "t"}],
                "approvals": list(entries)}

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="stale-approvals-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / "docs" / "compute").mkdir(parents=True)

    def write(self, approvals, rows=()):
        (self.dir / stale.APPROVALS).write_text(json.dumps(approvals), encoding="utf-8")
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=LEDGER_HEADER)
        w.writeheader()
        for r in rows:
            w.writerow(dict({k: "" for k in LEDGER_HEADER}, **r))
        (self.dir / stale.LEDGER).write_text(buf.getvalue(), encoding="utf-8")

    def entry(self, aid, approved, state="approved", **kw):
        return dict({"id": aid, "title": aid, "cap_usd": 5, "state": state, "approved": approved, "source": "t",
                     "ledger_apps": []}, **kw)

    def test_approval_dates(self):
        self.assertEqual(stale.approval_date({"approved": "Chase, 00:32 UTC 16 Oct 2026, yes"}).day, 16)
        self.assertEqual(stale.approval_date({"approved": "Chase on 18 October 2026"}).day, 18)
        self.assertEqual(stale.approval_date({"approved": "card 2026-10-14, then 16 Oct 2026"}).day, 14)
        self.assertEqual(stale.approval_date({"approved": "x", "approved_on": "2026-10-03"}).day, 3)
        self.assertIsNone(stale.approval_date({"approved": "Covered by the 18 October approval"}))

    @unittest.skipUnless(HAS_BUDGET, "kit/budget.py is in Scrolls-private only")
    def test_old_approval_without_a_ledger_row(self):
        self.write(self.approvals(
            self.entry("old", "Chase, 10 Oct 2026", ledger_apps=["ap-9"]),
            self.entry("unattributed", "Chase, 10 Oct 2026"),
            self.entry("launched", "Chase, 10 Oct 2026", ledger_apps=["ap-1"]),
            self.entry("recent", "Chase, 25 Oct 2026"),
            self.entry("finished", "Chase, 1 Oct 2026", state="done"),
            self.entry("before", "Chase, 12 Oct 2026", ledger_match=["tok-9"])),
            rows=[{"date_time_et": "2026-10-11 10:00 ET", "app_id": "ap-1", "purpose": "run"},
                  {"date_time_et": "2026-10-11 10:00 ET", "app_id": "ap-2", "notes": "token tok-9"},
                  {"date_time_et": "2026-10-11 10:00 ET", "app_id": "ap-3", "purpose": "unattributed run"}])
        res = stale.check_approvals(self.dir, stale.Git(self.dir), NOW)
        self.assertEqual([f.text.split(" ")[0] for f in res["findings"]], ["old", "unattributed", "before"])
        self.assertIn("approved 2026-10-10, 22 days ago, with no ledger row attributed to it (by ledger_apps or "
                      "ledger_match) since", res["findings"][0].text)
        self.assertIn("names no ledger_apps or ledger_match, so no ledger row can be attributed to it",
                      res["findings"][1].text)

    @unittest.skipUnless(HAS_BUDGET, "kit/budget.py is in Scrolls-private only")
    def test_undatable_approval_needs_a_look(self):
        self.write(self.approvals(self.entry("nodate", "Approved, cap 2.5 USD")))
        res = stale.check_approvals(self.dir, stale.Git(self.dir), NOW)
        self.assertIn("cannot date the approval", res["findings"][0].text)

    @unittest.skipUnless(HAS_GIT, "git is not installed")
    def test_undated_text_falls_back_to_when_the_id_was_added(self):
        repo = Repo(self)
        approvals = self.approvals(self.entry("nodate", "Approved, cap 2.5 USD"))
        repo.commit(days_ago(20), {stale.APPROVALS: json.dumps(approvals, indent=2),
                                   stale.LEDGER: ",".join(LEDGER_HEADER) + "\n"})
        self.assertEqual(stale.approval_date(approvals["approvals"][0], stale.Git(repo.dir)).date().isoformat(),
                         "2026-10-12")
        if not HAS_BUDGET:
            return
        res = stale.check_approvals(repo.dir, stale.Git(repo.dir), NOW)
        self.assertIn("nodate (cap 5 USD) approved 2026-10-12", res["findings"][0].text)

    @unittest.skipUnless(HAS_BUDGET, "kit/budget.py is in Scrolls-private only")
    def test_bad_approvals_fail(self):
        self.write({"approvals": []})
        with self.assertRaises(stale.StaleError):
            stale.check_approvals(self.dir, stale.Git(self.dir), NOW)

    def test_no_approvals_file_is_skipped(self):
        self.assertEqual(stale.check_approvals(self.dir, stale.Git(self.dir), NOW)["status"], stale.SKIPPED)

    @unittest.skipIf(HAS_BUDGET, "kit/budget.py is here")
    def test_approvals_without_kit_budget_are_skipped(self):
        self.write(self.approvals(self.entry("old", "Chase, 10 Oct 2026", ledger_apps=["ap-9"])))
        res = stale.check_approvals(self.dir, stale.Git(self.dir), NOW)
        self.assertEqual((res["status"], res["info"]), (stale.SKIPPED, ["kit.budget is not in this repository"]))


class Running(unittest.TestCase):
    def test_exit_codes(self):
        d = Path(tempfile.mkdtemp(prefix="stale-run-"))
        self.addCleanup(shutil.rmtree, d, True)
        self.assertEqual(stale.run_checks(d, NOW)["exit"], stale.EXIT_SKIPPED)
        (d / "docs").mkdir()
        (d / stale.RENAMES).write_text(json.dumps({"renames": [Names.RENAME]}), encoding="utf-8")
        (d / "README.md").write_text("the Scroll Text Reader\n", encoding="utf-8")
        report = stale.run_checks(d, NOW, only=("names",))
        self.assertEqual((report["exit"], [c["name"] for c in report["checks"]]), (stale.EXIT_OK, ["names"]))
        (d / "README.md").write_text("the Greek letter reader\n", encoding="utf-8")
        report = stale.run_checks(d, NOW, only=("names",))
        self.assertEqual(report["exit"], stale.EXIT_ATTENTION)
        self.assertEqual(report["checks"][0]["findings"][0]["where"], "README.md:1")
        text = stale.format_report(report)
        self.assertIn("--- names (attention) ---", text)
        self.assertIn("README.md:1: says", text)

    def test_cli_wiring_and_routine(self):
        from kit import cli
        parser = cli.build_parser()
        args = parser.parse_args(["stale", "--only", "freezes", "--json", "--freezes-days", "10"])
        self.assertEqual((args.only, args.json, args.days_freezes), (["freezes"], True, 10.0))
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            parser.parse_args(["stale", "--only", "nothing"])
        reg = {r["name"]: r for r in routines.load(ROOT / "docs" / "routines.json")}
        self.assertEqual((reg["stale"]["cadence"], reg["stale"]["command"]),
                         ("daily", ["{python}", "-m", "kit", "stale"]))
        # Public: the daily routines workflow runs it (attention fails the job there).
        self.assertTrue(reg["stale"]["ci"])

    def test_bad_now_is_refused(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            stale.main(["--now"])
        with redirect_stderr(io.StringIO()):
            self.assertEqual(stale.main(["--now", "yesterday"]), 2)


class CommittedRegistries(unittest.TestCase):
    @unittest.skipUnless((ROOT / stale.FREEZES).is_file(), "no freeze registry in this repository (Scrolls-private)")
    def test_freezes_registry_is_valid(self):
        freezes = stale.load_freezes(ROOT)
        ids = {f["id"] for f in freezes}
        for fid in ("strokenet-v5", "paris4-staging-2026-10-08", "umbilicus-endcaps", "umbilicus-24um-retest",
                    "surface-arm-a"):
            self.assertIn(fid, ids)
        states = {f["id"]: f["state"] for f in freezes}
        self.assertEqual((states["strokenet-v5"], states["paris4-staging-2026-10-08"]), ("spent", "spent"))
        self.assertEqual({states[i] for i in ("umbilicus-endcaps", "umbilicus-24um-retest", "surface-arm-a")},
                         {"live"})
        for f in freezes:
            self.assertTrue(f.get("frozen_on"), f"{f['id']}: give frozen_on so a clone without the commit can date it")
            if not f.get("branch"):
                self.assertTrue((ROOT / f["prereg"]).exists(), f"{f['id']}: {f['prereg']} is missing")

    def test_renames_registry_names_the_reader(self):
        renames = stale.load_renames(ROOT)
        self.assertIn(("Greek letter reader", "Scroll Text Reader"), [(r["old"], r["new"]) for r in renames])

    def test_live_pages_use_current_names(self):
        # The routines workflow fails on this check, so a change that brings an old name back fails here first.
        res = stale.check_names(ROOT)
        self.assertEqual(res["findings"], [], [f"{f.where}: {f.text[:80]}" for f in res["findings"]])


if __name__ == "__main__":
    unittest.main()
