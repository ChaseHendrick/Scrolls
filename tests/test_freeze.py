"""kit freeze (kit/freeze.py): the registry commands list, add, check, pin, collect and prereg on throwaway git
repositories (add checks the preregistration's own hash lines, records accepted other_changes, and a spent rerun
reads its entry from the default branch in a real git worktree); the registry shape check and a configurable
registry path; the runner guards executed_check, run_script and launch_check (installed packages inside the
repository are not repository files); and the preregistration hash sets (readout and plumbing; unknown fences and a
path in both sets are errors) and the deviations format."""

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from kit import cli, freeze, preregsets

ROOT = Path(__file__).resolve().parent.parent
HAS_GIT = shutil.which("git") is not None
PREREG = "docs/prereg/2026-11-01-demo.md"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def registry(*entries):
    return {"schema": freeze.SCHEMA, "about": "test registry", "freezes": list(entries)}


class Repo:
    """A throwaway git repository with a registry, a preregistration and two code files."""

    def __init__(self, test):
        self.dir = Path(tempfile.mkdtemp(prefix="freeze-test-"))
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args):
        env = dict(os.environ, GIT_AUTHOR_DATE="2026-11-01T12:00:00+00:00",
                   GIT_COMMITTER_DATE="2026-11-01T12:00:00+00:00")
        return subprocess.run(["git", "-C", str(self.dir), *args], check=True, capture_output=True, text=True,
                              env=env).stdout.strip()

    def write(self, rel, text):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, files, message="change"):
        for rel, text in files.items():
            self.write(rel, text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def seed(self):
        """Code, then a freezing commit that changes only the preregistration; returns that commit."""
        self.commit({"kit/run.py": "print('run')\n", "kit/io.py": "print('io')\n",
                     freeze.FREEZES: json.dumps(registry(), indent=2) + "\n",
                     PREREG: "**Status: Draft**\n"}, "code")
        return self.commit({PREREG: "**Status: Frozen**\n"}, "freeze the preregistration")


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


@unittest.skipUnless(HAS_GIT, "git is not installed")
class RegistryCommandsTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.commit = self.repo.seed()
        self.root = self.repo.dir

    def cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        p = __import__("argparse").ArgumentParser()
        freeze.add_arguments(p)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = freeze.run(p.parse_args(list(argv)), root=self.root)
        return code, out.getvalue(), err.getvalue()

    def add(self, *extra):
        return self.cmd("add", "--id", "demo-v1", "--prereg", PREREG, "--file", "kit/run.py", "--file", "kit/io.py",
                        "--note", "demo freeze", "--run-token", "run-d4e5f6", *extra)

    def test_add_records_hashes_at_the_freezing_commit(self):
        code, out, err = self.add()
        self.assertEqual(code, 0, err)
        self.assertIn("added demo-v1", out)
        data = freeze.load(self.root)
        e = freeze.find(data, "demo-v1")
        self.assertEqual(e["freezing_commit"], self.commit)
        self.assertEqual(e["state"], "live")
        self.assertIsNone(e["collected_on"])
        self.assertEqual(e["frozen_on"], "2026-11-01")
        self.assertEqual(e["run_token"], "run-d4e5f6")
        self.assertEqual(e["files"], {"kit/io.py": sha("print('io')\n"), "kit/run.py": sha("print('run')\n")})
        self.assertEqual(e["prereg_sha256"], sha("**Status: Frozen**\n"))

    def test_a_freeze_cannot_be_dated_before_its_commit(self):
        # 4 Nov 2026 bug sweep: --frozen-on before the commit made a new freeze look older than pass-first
        code, out, err = self.add("--frozen-on", "2026-10-30")
        self.assertNotEqual(code, 0)
        self.assertIn("before the freezing commit", out + err)
        self.assertNotIn("demo-v1", [e["id"] for e in freeze.load(self.root)["freezes"]])
        code, out, err = self.add("--frozen-on", "2026-11-02")             # a later day stays allowed
        self.assertEqual(code, 0, err)
        self.assertEqual(freeze.find(freeze.load(self.root), "demo-v1")["frozen_on"], "2026-11-02")

    def test_add_dry_run_writes_nothing(self):
        before = (self.root / freeze.FREEZES).read_text()
        code, out, _ = self.add("--dry-run", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["id"], "demo-v1")
        self.assertEqual((self.root / freeze.FREEZES).read_text(), before)

    def test_add_refuses_folders_missing_files_and_mixed_commits(self):
        code, _, err = self.cmd("add", "--id", "x", "--prereg", PREREG, "--file", "kit", "--note", "n")
        self.assertEqual(code, 2)
        self.assertIn("never a whole folder", err)
        code, _, err = self.cmd("add", "--id", "x", "--prereg", PREREG, "--file", "kit/", "--note", "n")
        self.assertEqual(code, 2)
        self.assertIn("not a repository file path", err)
        code, _, err = self.cmd("add", "--id", "x", "--prereg", PREREG, "--file", "kit/gone.py", "--note", "n")
        self.assertEqual(code, 2)
        self.assertIn("is not a file at", err)
        code, _, err = self.cmd("add", "--id", "x", "--prereg", PREREG, "--note", "n")
        self.assertEqual(code, 2)
        self.assertIn("guards nothing", err)
        mixed = self.repo.commit({PREREG: "**Status: Frozen** again\n", "kit/run.py": "print('run2')\n"}, "mixed")
        code, _, err = self.cmd("add", "--id", "x", "--prereg", PREREG, "--file", "kit/run.py", "--note", "n",
                                "--commit", mixed)
        self.assertEqual(code, 2)
        self.assertIn("also changes kit/run.py", err)
        code, _, err = self.cmd("add", "--id", "x", "--prereg", PREREG, "--file", "kit/run.py", "--note", "n",
                                "--commit", mixed, "--allow-other-changes")
        self.assertEqual(code, 0, err)

    def test_add_refuses_a_taken_id_and_a_bad_id(self):
        self.assertEqual(self.add()[0], 0)
        code, _, err = self.add()
        self.assertEqual(code, 2)
        self.assertIn("already in", err)
        code, _, err = self.cmd("add", "--id=bad id", "--prereg", PREREG, "--file", "kit/run.py", "--note", "n")
        self.assertEqual(code, 2)
        self.assertIn("use letters, digits", err)

    def test_files_from(self):
        self.repo.write("work/list.txt", "# the files\nkit/run.py\nkit/io.py  # io\n\n")
        code, _, err = self.cmd("add", "--id", "demo-v1", "--prereg", PREREG, "--files-from",
                                str(self.root / "work/list.txt"), "--note", "n")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(freeze.find(freeze.load(self.root), "demo-v1")["files"]), ["kit/io.py", "kit/run.py"])

    def test_check_live_fails_on_a_changed_file_and_names_the_change(self):
        self.add()
        code, out, _ = self.cmd("check", "demo-v1")
        self.assertEqual(code, 0, out)
        self.assertIn("check ok: 2 of 2", out)
        self.repo.write("kit/io.py", "print('io')\nprint('more')\n")
        code, out, _ = self.cmd("check", "demo-v1")
        self.assertEqual(code, 1)
        self.assertIn("kit/io.py changed in the working tree (+1 -0 lines)", out)
        later = self.repo.commit({"kit/io.py": "print('io')\nx\n"}, "edit")
        code, out, _ = self.cmd("check", "demo-v1", "--at", self.commit)
        self.assertNotIn("FAIL: kit/io.py", out)            # at the freezing commit itself the files match
        code, out, _ = self.cmd("check", "demo-v1", "--at", later, "--json")
        r = json.loads(out)
        self.assertEqual(r["exit"], 1)
        self.assertEqual({x["path"]: x["status"] for x in r["files"]}, {"kit/io.py": "changed", "kit/run.py": "ok"})

    def test_check_prereg_amendment_is_attention_and_record_mismatch_fails(self):
        self.add()
        self.repo.write(PREREG, "**Status: Frozen**\n\n## Amendment 1\n")
        code, out, _ = self.cmd("check", "demo-v1")
        self.assertEqual(code, 3)
        self.assertIn("only dated amendments", out)
        data = freeze.load(self.root)
        freeze.find(data, "demo-v1")["files"]["kit/run.py"] = "0" * 64
        freeze.save(self.root, data)
        code, out, _ = self.cmd("check", "demo-v1")
        self.assertEqual(code, 1)
        self.assertIn("the record is wrong", out)

    def test_check_freezing_commit_must_change_only_the_prereg(self):
        mixed = self.repo.commit({PREREG: "**Status: Frozen** v2\n", "kit/io.py": "print('io2')\n"}, "mixed")
        code, _, err = self.cmd("add", "--id", "mixed", "--prereg", PREREG, "--file", "kit/io.py", "--note", "n",
                                "--commit", mixed, "--allow-other-changes")
        self.assertEqual(code, 0, err)
        data = freeze.load(self.root)
        self.assertEqual(freeze.find(data, "mixed")["other_changes"], ["kit/io.py"])
        code, out, _ = self.cmd("check", "mixed")                      # accepted when it was recorded: information
        self.assertEqual(code, 0, out)
        self.assertIn("accepted when the freeze was recorded as it was (other_changes)", out)
        freeze.find(data, "mixed")["other_changes"] = ["kit/run.py"]   # a path the record did not accept still fails
        freeze.save(self.root, data)
        code, out, _ = self.cmd("check", "mixed")
        self.assertEqual(code, 1)
        self.assertIn("changes 1 file(s) besides the preregistration: kit/io.py", out)
        del freeze.find(data, "mixed")["other_changes"]
        freeze.save(self.root, data)
        self.assertEqual(self.cmd("check", "mixed")[0], 1)

    def test_add_checks_the_preregistrations_own_hash_lines(self):
        run, io_ = sha("print('run')\n"), sha("print('io')\n")
        good = (f"**Status: Frozen**\n\n```code-sha256 readout\n{run}  kit/run.py\n```\n\n"
                f"```code-sha256 plumbing\n{io_}  kit/io.py\n```\n")
        hashed = self.repo.commit({PREREG: good}, "freeze with hash lines")
        code, _, err = self.cmd("add", "--id", "h1", "--prereg", PREREG, "--file", "kit/run.py", "--note", "n",
                                "--commit", hashed, "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("hashes kit/io.py, which the file list leaves out", err)
        code, out, err = self.cmd("add", "--id", "h1", "--prereg", PREREG, "--from-prereg", "--note", "n",
                                  "--commit", hashed, "--json", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(json.loads(out)["files"]), ["kit/io.py", "kit/run.py"])
        bad = self.repo.commit({PREREG: good.replace(run, "0" * 64)}, "wrong hash line")
        code, _, err = self.cmd("add", "--id", "h2", "--prereg", PREREG, "--from-prereg", "--note", "n",
                                "--commit", bad)
        self.assertEqual(code, 2)
        self.assertIn("kit/run.py (readout set: 000000000000 in the preregistration", err)
        self.repo.commit({"kit/io.py": "print('io v2')\n"}, "plumbing change")
        new_io = sha("print('io v2')\n")
        line = f"```deviations\n2026-11-01  {new_io}  kit/io.py  image fix\n```\n"
        dev = self.repo.commit({PREREG: good + "\n## Amendment\n\n" + line}, "refreeze with a deviation")
        code, _, err = self.cmd("add", "--id", "h3", "--prereg", PREREG, "--from-prereg", "--note", "n",
                                "--commit", dev, "--dry-run")
        self.assertEqual(code, 0, err)                                 # a dated deviation gives the plumbing hash

    def test_spent_rerun_reads_its_entry_from_the_default_branch_in_a_worktree(self):
        self.add()
        self.repo.write("docs/evidence/demo.json", "{}\n")
        self.cmd("collect", "demo-v1", "--evidence", "docs/evidence/demo.json", "--on", "2026-11-02")
        self.repo.commit({}, "register and collect demo-v1")
        wt = Path(tempfile.mkdtemp(prefix="freeze-wt-")) / "rerun"
        self.addCleanup(shutil.rmtree, wt.parent, True)
        self.repo.git("worktree", "add", "-q", "--detach", str(wt), self.commit)
        self.addCleanup(lambda: self.repo.git("worktree", "remove", "--force", str(wt)))
        with self.assertRaises(freeze.FreezeError):                     # the registry at the freezing commit lacks it
            freeze.find(freeze.load(wt), "demo-v1")
        e = freeze.find(freeze.load(wt, rev="main"), "demo-v1")
        self.assertEqual(e["state"], "spent")
        self.assertEqual(freeze.launch_check(e, wt), 2)                # HEAD of the worktree is the freezing commit
        with self.assertRaises(freeze.FreezeRefused):
            freeze.launch_check(e, self.root)                          # the main checkout has moved on
        code, out, _ = self.cmd("check", "demo-v1", "--registry-rev", "main")
        self.assertEqual(code, 0, out)
        with self.assertRaises(freeze.FreezeError):
            freeze.load(wt, rev="no-such-branch")

    def test_legacy_entry_without_files_reports_info(self):
        mixed = self.repo.commit({PREREG: "v3\n", "kit/io.py": "print('io3')\n"}, "mixed")
        data = freeze.load(self.root)
        data["freezes"].append({"id": "old", "prereg": PREREG, "freezing_commit": mixed[:8], "state": "live",
                                "collected_on": None, "note": "seeded"})
        freeze.save(self.root, data)
        code, out, _ = self.cmd("check", "old")
        self.assertEqual(code, 0, out)
        self.assertIn("predates python -m kit freeze add", out)
        self.assertIn("no file list recorded", out)

    def test_collect_spends_and_spent_changes_are_info(self):
        self.add()
        code, _, err = self.cmd("collect", "demo-v1", "--evidence", "docs/evidence/demo/")
        self.assertEqual(code, 2)
        self.assertIn("is not in the working tree", err)
        self.repo.write("docs/evidence/demo/README.md", "evidence\n")
        code, out, err = self.cmd("collect", "demo-v1", "--evidence", "docs/evidence/demo", "--on", "2026-11-02",
                                  "--note", "run collected")
        self.assertEqual(code, 0, err)
        e = freeze.find(freeze.load(self.root), "demo-v1")
        self.assertEqual((e["state"], e["collected_on"], e["evidence"]), ("spent", "2026-11-02", "docs/evidence/demo/"))
        self.assertTrue(e["note"].endswith("Collected 2026-11-02: run collected"))
        self.repo.write("kit/io.py", "print('changed after the run')\n")
        code, out, _ = self.cmd("check", "demo-v1")
        self.assertEqual(code, 0, out)
        self.assertIn("allowed, the freeze is spent", out)
        code, _, err = self.cmd("collect", "demo-v1", "--evidence", "docs/evidence/demo")
        self.assertEqual(code, 2)
        self.assertIn("already spent", err)

    def test_collect_keep_live_and_date_checks(self):
        self.add()
        self.repo.write("docs/evidence/demo.json", "{}\n")
        code, _, err = self.cmd("collect", "demo-v1", "--evidence", "docs/evidence/demo.json", "--on", "2026-10-01")
        self.assertEqual(code, 2)
        self.assertIn("before the freeze", err)
        code, _, err = self.cmd("collect", "demo-v1", "--evidence", "docs/evidence/demo.json", "--keep-live",
                                "--on", "2026-11-03")
        self.assertEqual(code, 0, err)
        e = freeze.find(freeze.load(self.root), "demo-v1")
        self.assertEqual((e["state"], e["collected_on"]), ("live", "2026-11-03"))

    def test_list_shows_ages_and_states(self):
        self.add()
        rows = freeze.listing(self.root, today=__import__("datetime").date(2026, 11, 11))
        self.assertEqual(rows[0]["age_days"], 10)
        self.assertEqual(rows[0]["files"], 2)
        code, out, _ = self.cmd("list")
        self.assertEqual(code, 0)
        self.assertIn("1 freezes, 1 live, 0 spent", out)
        code, out, _ = self.cmd("list", "--state", "spent", "--json")
        self.assertEqual(json.loads(out), [])

    def test_unknown_id_and_bad_at(self):
        code, _, err = self.cmd("check", "nope")
        self.assertEqual(code, 2)
        self.assertIn("no freeze 'nope'", err)
        self.add()
        code, _, err = self.cmd("check", "demo-v1", "--at", "no-such-rev")
        self.assertEqual(code, 2)

    def test_a_spent_freeze_that_needs_a_new_freeze_is_refused_even_at_its_commit(self):
        """A launcher at the spent commit lacks a guard added since, so a rerun needs a new freeze."""
        self.add()
        e = dict(freeze.find(freeze.load(self.root), "demo-v1"), state="spent", collected_on="2026-11-02",
                 rerun_needs_new_freeze="its launches list is empty there")
        with self.assertRaises(freeze.FreezeRefused) as cm:
            freeze.launch_check(e, self.root)                              # HEAD is the freezing commit here
        self.assertIn("needs a new freeze", str(cm.exception))
        self.assertNotIn("a rerun launches from", str(cm.exception))
        data = freeze.load(self.root)
        data["freezes"][0].update(state="spent", collected_on="2026-11-02", rerun_needs_new_freeze="x")
        self.repo.write("kit/run.py", "print('moved on')\n")
        report = freeze.check(self.root, "demo-v1", data=data)
        self.assertTrue(any("needs a new freeze" in i for i in report["info"]), report["info"])
        self.assertFalse(any("a rerun launches from" in i for i in report["info"]))
        freeze.validate(data)
        data["freezes"][0]["rerun_needs_new_freeze"] = ""
        with self.assertRaises(freeze.FreezeError):
            freeze.validate(data)

    def test_the_rerun_field_is_refused_whatever_the_state(self):
        """Review of #3238: launch_check refuses an entry with rerun_needs_new_freeze when it is live too, and check
        fails such a live entry, with nothing changed since the freeze."""
        self.add()
        e = dict(freeze.find(freeze.load(self.root), "demo-v1"), rerun_needs_new_freeze="its guard came later")
        self.assertEqual(e["state"], "live")
        with self.assertRaises(freeze.FreezeRefused) as cm:
            freeze.launch_check(e, self.root)
        self.assertIn("is live and a rerun needs a new freeze", str(cm.exception))
        plain = freeze.find(freeze.load(self.root), "demo-v1")
        self.assertEqual(freeze.launch_check(plain, self.root), 2)        # without the field the same entry passes
        data = freeze.load(self.root)
        data["freezes"][0]["rerun_needs_new_freeze"] = "its guard came later"
        report = freeze.check(self.root, "demo-v1", data=data)
        self.assertEqual(report["exit"], freeze.EXIT_FAIL)
        self.assertTrue(any("a live freeze cannot carry it" in p for p in report["problems"]), report["problems"])
        data["freezes"][0].update(state="spent", collected_on="2026-11-02")
        report = freeze.check(self.root, "demo-v1", data=data)
        self.assertEqual(report["exit"], freeze.EXIT_OK, report)
        self.assertTrue(any("launch_check refuses this entry" in i for i in report["info"]), report["info"])

    def test_add_refuses_the_freezing_commit_of_an_entry_that_needs_a_new_freeze(self):
        """Review of #3238: a new id on the spent commit would launch the same unguarded code."""
        self.add()
        data = freeze.load(self.root)
        data["freezes"][0].update(state="spent", collected_on="2026-11-02", rerun_needs_new_freeze="no guard there")
        freeze.save(self.root, data)
        code, _, err = self.cmd("add", "--id", "demo-v2", "--prereg", PREREG, "--file", "kit/run.py", "--note", "n",
                                "--commit", self.commit[:12])
        self.assertEqual(code, freeze.EXIT_INPUT)
        self.assertIn("is the freezing commit of demo-v1", err)
        self.assertIsNone(next((f for f in freeze.load(self.root)["freezes"] if f["id"] == "demo-v2"), None))
        for state in ("live", "spent"):                     # whatever the old entry's state, and an abbreviated record
            d = freeze.load(self.root)
            d["freezes"][0].update(state=state, freezing_commit=self.commit[:9],
                                   collected_on=None if state == "live" else "2026-11-02")
            with self.assertRaises(freeze.FreezeError):
                freeze.make_entry(self.root, "demo-v2", PREREG, ["kit/run.py"], "n", self.commit, data=d)
        d["freezes"][0].pop("rerun_needs_new_freeze")      # without the field the same commit may be frozen again
        self.assertEqual(freeze.make_entry(self.root, "demo-v2", PREREG, ["kit/run.py"], "n", self.commit,
                                           data=d)["freezing_commit"], self.commit)

    def test_launch_check_live_and_spent(self):
        self.add()
        e = freeze.find(freeze.load(self.root), "demo-v1")
        self.assertEqual(freeze.launch_check(e, self.root), 2)
        self.repo.write("kit/run.py", "print('edited')\n")
        with self.assertRaises(freeze.FreezeRefused):
            freeze.launch_check(e, self.root)
        self.repo.write("kit/run.py", "print('run')\n")
        e = dict(e, state="spent", collected_on="2026-11-02")
        self.assertEqual(freeze.launch_check(e, self.root), 2)        # HEAD is the freezing commit here
        self.repo.commit({"docs/other.md": "x\n"}, "later")
        with self.assertRaises(freeze.FreezeRefused) as cm:
            freeze.launch_check(e, self.root)
        self.assertIn("git worktree add", str(cm.exception))
        with self.assertRaises(freeze.FreezeRefused):
            freeze.launch_check(dict(e, files=None), self.root)


    def test_freeze_pins_by_commit_check_launch_and_collect_use_the_frozen_commit(self):
        """Freeze pins by commit: a live freeze with frozen_commit runs from that commit, so the
        checkout may move on; pin refuses a commit whose files differ, launch_check refuses any other HEAD, and
        collect verifies against the frozen commit."""
        self.add()
        moved = self.repo.commit({"kit/run.py": "print('main moved on')\n"}, "the default branch moves on")
        code, _, err = self.cmd("pin", "demo-v1", "--commit", moved)
        self.assertEqual(code, 2)
        self.assertIn("cannot be the frozen commit", err)
        code, out, err = self.cmd("pin", "demo-v1")
        self.assertEqual(code, 0, err)
        e = freeze.find(freeze.load(self.root), "demo-v1")
        self.assertEqual(e["frozen_commit"], self.commit)
        code, out, _ = self.cmd("check", "demo-v1", "--at", self.commit)  # the pin itself checks out
        self.assertEqual(code, 0, out)
        # Review fix: with no at, check still vets the working tree, which runner gates (a scorer started with --freeze,
        # a data prep script and others) run from, and fails while HEAD is not the frozen commit.
        r = freeze.check(self.root, "demo-v1")
        self.assertEqual(r["exit"], freeze.EXIT_FAIL)
        self.assertEqual(r["target"], "working tree")
        self.assertTrue(any("kit/run.py changed in the working tree" in p for p in r["problems"]), r["problems"])
        self.assertTrue(any("pinned by commit" in p for p in r["problems"]), r["problems"])
        self.assertEqual(self.cmd("check", "demo-v1")[0], 1)
        self.assertEqual(self.cmd("check", "demo-v1", "--at", moved)[0], 1)
        with self.assertRaises(freeze.FreezeRefused) as cm:
            freeze.launch_check(e, self.root)                          # HEAD is not the frozen commit
        self.assertIn("pinned by commit", str(cm.exception))
        wt = Path(tempfile.mkdtemp(prefix="freeze-wt-")) / "frozen"
        self.addCleanup(shutil.rmtree, wt.parent, True)
        self.repo.git("worktree", "add", "-q", "--detach", str(wt), self.commit)
        self.addCleanup(lambda: self.repo.git("worktree", "remove", "--force", str(wt)))
        self.assertEqual(freeze.launch_check(e, wt), 2)                # the frozen worktree launches
        r = freeze.check(wt, "demo-v1", data=freeze.load(self.root))  # and its gate's no-at check passes there
        self.assertEqual(r["exit"], freeze.EXIT_OK, r["problems"])
        (wt / "kit" / "run.py").write_text("print('edited in the frozen worktree')\n")
        r = freeze.check(wt, "demo-v1", data=freeze.load(self.root))  # HEAD matches, a changed file still fails
        self.assertEqual(r["exit"], freeze.EXIT_FAIL)
        self.assertTrue(any("kit/run.py changed" in p for p in r["problems"]), r["problems"])
        self.repo.git("-C", str(wt), "checkout", "--", "kit/run.py")
        self.repo.write("docs/evidence/demo.json", "{}\n")
        data = freeze.load(self.root)
        freeze.find(data, "demo-v1")["frozen_commit"] = moved          # a frozen commit whose files differ
        freeze.save(self.root, data)
        code, _, err = self.cmd("collect", "demo-v1", "--evidence", "docs/evidence/demo.json", "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("does not pass", err)
        freeze.find(data, "demo-v1")["frozen_commit"] = self.commit
        freeze.save(self.root, data)
        code, _, err = self.cmd("collect", "demo-v1", "--evidence", "docs/evidence/demo.json")
        self.assertEqual(code, 0, err)
        data["freezes"][0]["frozen_commit"] = self.commit[:12]
        with self.assertRaises(freeze.FreezeError):
            freeze.validate(data)


class ValidateTest(unittest.TestCase):
    def entry(self, **over):
        e = {"id": "a", "prereg": PREREG, "freezing_commit": "abcdef12", "state": "live", "collected_on": None,
             "note": "n"}
        e.update(over)
        return e

    def test_base_shape(self):
        with self.assertRaises(freeze.FreezeError) as cm:
            freeze.validate(registry(self.entry(state="frozen")))
        self.assertIn("state must be live or spent", str(cm.exception))
        with self.assertRaises(freeze.FreezeError):
            freeze.validate(registry(self.entry(state="spent")))          # spent needs collected_on
        with self.assertRaises(freeze.FreezeError):
            freeze.validate({"freezes": "x"})

    def test_extra_fields(self):
        freeze.validate(registry(self.entry(files={"kit/a.py": "a" * 64}, run_token="run-d4e5f6",
                                            prereg_sha256="b" * 64)))
        for bad in ({"files": {"kit/": "a" * 64}}, {"files": {"kit/a.py": "short"}}, {"files": {}},
                    {"files": {"../x.py": "a" * 64}}, {"prereg_sha256": "x"}, {"run_token": "has space"},
                    {"evidence": ""}):
            with self.assertRaises(freeze.FreezeError, msg=str(bad)):
                freeze.validate(registry(self.entry(**bad)))

    def test_the_registry_path_is_configurable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(os.environ, {freeze.REGISTRY_ENV: "ops/frozen.json"}):
                self.assertEqual(freeze.registry_path(), "ops/frozen.json")
                freeze.save(root, registry(self.entry()))
                self.assertTrue((root / "ops" / "frozen.json").is_file())
                self.assertEqual(freeze.load(root)["freezes"][0]["id"], "a")
            with self.assertRaises(freeze.FreezeError) as cm:
                freeze.load(root)                                       # the default path holds nothing
            self.assertIn(freeze.FREEZES, str(cm.exception))
            p = __import__("argparse").ArgumentParser()
            freeze.add_arguments(p)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = freeze.run(p.parse_args(["--root", tmp, "--registry", "ops/frozen.json", "list", "--json"]))
            self.assertEqual((code, json.loads(out.getvalue())[0]["id"]), (0, "a"))
            self.assertNotIn(freeze.REGISTRY_ENV, os.environ)


class GuardTest(unittest.TestCase):
    def test_executed_check_refuses_unlisted_repository_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ("kit/__init__.py", "kit/freeze.py", "kit/extra.py"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("")
            outside = Path(tmp).parent / "site.py"
            mods = {"kit": types.SimpleNamespace(__file__=str(root / "kit/__init__.py")),
                    "kit.freeze": types.SimpleNamespace(__file__=str(root / "kit/freeze.py")),
                    "json": types.SimpleNamespace(__file__=str(outside)),
                    "builtin": types.SimpleNamespace()}
            listed = ["kit/__init__.py", "kit/freeze.py"]
            self.assertEqual(freeze.executed_check(listed, root, mods), 2)
            self.assertEqual(freeze.executed_check({"files": {p: "a" * 64 for p in listed}}, root, mods), 2)
            mods["kit.extra"] = types.SimpleNamespace(__file__=str(root / "kit/extra.py"))
            with self.assertRaises(freeze.FreezeRefused) as cm:
                freeze.executed_check(listed, root, mods, when="after the work")
            self.assertIn("after the work: loaded kit/extra.py", str(cm.exception))
            self.assertIsInstance(cm.exception, SystemExit)

    def test_installed_packages_inside_the_repository_are_not_repository_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            for rel in ("kit/freeze.py", ".venv/lib/python3.13/site-packages/numpy/__init__.py",
                        "venv/lib/python3/dist-packages/zarr/core.py", ".conda/lib/python3.13/json/__init__.py",
                        "kit/extra.py"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("")
            files = [str(root / r) for r in (".venv/lib/python3.13/site-packages/numpy/__init__.py",
                                             "venv/lib/python3/dist-packages/zarr/core.py", "kit/freeze.py")]
            self.assertEqual(freeze._repo_paths(files, root), ["kit/freeze.py"])
            conda = [str(root / ".conda/lib/python3.13/json/__init__.py"), str(root / "kit/extra.py")]
            self.assertEqual(len(freeze._repo_paths(conda, root)), 2)
            with mock.patch.object(freeze.sys, "prefix", str(root / ".conda")):   # an interpreter inside the repo
                self.assertEqual(freeze._repo_paths(conda, root), ["kit/extra.py"])
            with mock.patch.object(freeze.sys, "prefix", tmp):                   # a prefix holding the repository
                self.assertEqual(len(freeze._repo_paths(conda, root)), 2)        # hides nothing

    def test_run_script_checks_what_a_child_process_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts" / "helper.py").write_text("VALUE = 1\n")
            (root / "scripts" / "run.py").write_text("import sys, helper\n"
                                                     "assert sys.argv[1:] == ['a'] and helper.VALUE == 1\n")
            script = root / "scripts" / "run.py"
            both = ["scripts/run.py", "scripts/helper.py"]
            self.assertEqual(freeze.run_script(script, ["a"], both, root), 2)
            with self.assertRaises(freeze.FreezeRefused) as cm:
                freeze.run_script(script, ["a"], ["scripts/run.py"], root)
            self.assertIn("loaded scripts/helper.py", str(cm.exception))
            (root / "scripts" / "fail.py").write_text("raise SystemExit(4)\n")
            with self.assertRaises(subprocess.CalledProcessError):
                freeze.run_script(root / "scripts" / "fail.py", [], ["scripts/fail.py"], root)

    def test_executed_files_reads_sys_modules(self):
        self.assertIn("kit/freeze.py", freeze.executed_files(ROOT))

    def test_runner_import_needs_only_init_freeze_and_preregsets(self):
        code = ("import sys, kit.freeze as f; "
                "print(sorted(p for p in f.executed_files(sys.argv[1]) if p.startswith('kit/')))")
        out = subprocess.run([shutil.which("python3") or "python3", "-c", code, str(ROOT)], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(out, "['kit/__init__.py', 'kit/freeze.py', 'kit/preregsets.py']")

    def test_preregsets_imports_nothing_from_the_repository(self):
        pre = (ROOT / "kit" / "preregsets.py").read_text(encoding="utf-8")
        self.assertNotRegex(pre, r"from \. import|from \.\w+ import|import kit")
        self.assertIs(freeze.FreezeError, preregsets.PreregError)


class PreregSetsTest(unittest.TestCase):
    def test_plain_blocks_are_readout_and_split_blocks_name_their_set(self):
        text = "\n".join(["```code-sha256", f"{'a' * 64}  kit/score.py", "```", "",
                          "```code-sha256 plumbing", f"{'b' * 64}  scripts/container_run.py", "```",
                          "```code-sha256 readout", f"{'d' * 64}  docs/labels.json", f"{'c' * 64}  kit/score.py", "```"])
        sets = freeze.prereg_sets(text)
        self.assertEqual(sets["kit/score.py"], ("readout", "c" * 64))   # a later readout block (an amendment) wins
        self.assertEqual(sets["scripts/container_run.py"], ("plumbing", "b" * 64))
        self.assertEqual(sets["docs/labels.json"], ("readout", "d" * 64))

    def test_a_plumbing_block_cannot_rehash_a_readout_file(self):
        for first, second in (("readout", "plumbing"), ("plumbing", "readout"), ("", "plumbing")):
            text = (f"```code-sha256 {first}".rstrip() + f"\n{'a' * 64}  kit/score.py\n```\n"
                    f"```code-sha256 {second}\n{'b' * 64}  kit/score.py\n```\n")
            with self.assertRaises(freeze.FreezeError) as cm:
                freeze.prereg_sets(text)
            self.assertIn("listed in both the readout and the plumbing set", str(cm.exception))

    def test_unknown_fence_qualifier_is_an_error(self):
        for fence in ("```code-sha256 Plumbing", "```code-sha256 readout-set", "```code-sha256 amendment 1",
                      "```code-sha256s"):
            with self.assertRaises(freeze.FreezeError, msg=fence) as cm:
                freeze.prereg_sets(f"{fence}\n{'a' * 64}  kit/score.py\n```\n")
            self.assertIn("unknown code-sha256 block", str(cm.exception))

    def test_malformed_blocks(self):
        for bad in ("```code-sha256\nnot a hash line\n```", "```code-sha256\n" + "a" * 64 + "  x.py\n"):
            with self.assertRaises(freeze.FreezeError):
                freeze.prereg_sets(bad)

    def test_deviations(self):
        good = f"```deviations\n2026-11-02  {'e' * 64}  scripts/container_run.py  image: add numpy\n```\n"
        self.assertEqual(freeze.deviations(good), [{"date": "2026-11-02", "sha256": "e" * 64,
                                                     "path": "scripts/container_run.py", "reason": "image: add numpy"}])
        for bad in (f"```deviations\n2026-11-02  {'e' * 64}  x.py\n```", "```deviations\nnope\n```",
                    f"```deviations\n2026-13-02  {'e' * 64}  x.py  r\n```", "```deviations\n"):
            with self.assertRaises(freeze.FreezeError, msg=bad):
                freeze.deviations(bad)
        self.assertEqual(len(freeze.record_deviations([{"date": "2026-11-02", "sha256": "e" * 64, "path": "x.py",
                                                         "reason": "r"}])), 1)
        for bad in ("x", [{"date": "2026-11-02", "sha256": "e" * 64, "path": "x.py"}], [{"date": "x"}]):
            with self.assertRaises(freeze.FreezeError):
                freeze.record_deviations(bad)

class PreregCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.files = {"kit/score.py": "score\n", "scripts/container_run.py": "image\n"}
        for rel, text in self.files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)

    def prereg(self, split=True, extra=""):
        r, p = self.files["kit/score.py"], self.files["scripts/container_run.py"]
        if split:
            body = (f"```code-sha256 readout\n{sha(r)}  kit/score.py\n```\n\n"
                    f"```code-sha256 plumbing\n{sha(p)}  scripts/container_run.py\n```\n")
        else:
            body = f"```code-sha256\n{sha(r)}  kit/score.py\n{sha(p)}  scripts/container_run.py\n```\n"
        (self.root / PREREG).parent.mkdir(parents=True, exist_ok=True)
        (self.root / PREREG).write_text("**Status: Frozen**\n\n" + body + extra)

    def test_unchanged_passes(self):
        self.prereg()
        r = freeze.check_prereg(self.root, PREREG)
        self.assertEqual((r["exit"], r["sets"], r["split"]), (0, {"readout": 1, "plumbing": 1}, True))

    def test_readout_change_fails(self):
        self.prereg()
        (self.root / "kit/score.py").write_text("score v2\n")
        r = freeze.check_prereg(self.root, PREREG)
        self.assertEqual(r["exit"], 1)
        self.assertIn("readout changed", [x["status"] for x in r["files"]])

    def test_plumbing_change_needs_a_dated_line(self):
        self.prereg()
        new = "image with numpy\n"
        (self.root / "scripts/container_run.py").write_text(new)
        r = freeze.check_prereg(self.root, PREREG)
        self.assertEqual(r["exit"], 3)
        self.assertIn("plumbing deviation", r["attention"][0])
        self.assertIn(sha(new), r["attention"][0])
        line = f"```deviations\n2026-11-02  {sha(new)}  scripts/container_run.py  image: add numpy\n```\n"
        record = self.root / "record.md"
        record.write_text(line)
        r = freeze.check_prereg(self.root, PREREG, records=[record])
        self.assertEqual(r["exit"], 0)
        self.assertEqual(r["files"][1]["status"], "plumbing deviation recorded")
        self.prereg(extra="\n## Amendments\n\n" + line)                 # a deviation line kept in the prereg
        self.assertEqual(freeze.check_prereg(self.root, PREREG)["exit"], 0)
        wrong = f"```deviations\n2026-11-02  {'f' * 64}  scripts/container_run.py  wrong hash\n```\n"
        record.write_text(wrong)
        self.prereg()
        self.assertEqual(freeze.check_prereg(self.root, PREREG, records=[record])["exit"], 3)

    def test_no_split_means_all_readout(self):
        self.prereg(split=False)
        (self.root / "scripts/container_run.py").write_text("image v2\n")
        r = freeze.check_prereg(self.root, PREREG)
        self.assertEqual((r["exit"], r["split"]), (1, False))

    def test_a_prereg_that_hashes_nothing_needs_a_look(self):
        (self.root / PREREG).parent.mkdir(parents=True, exist_ok=True)
        (self.root / PREREG).write_text("**Status: Frozen**\n\nNo hash block in this format.\n")
        r = freeze.check_prereg(self.root, PREREG)
        self.assertEqual(r["exit"], 3)
        self.assertIn("hashes nothing in the code-sha256 format", r["attention"][0])
        self.assertIn("ATTENTION: ", freeze.format_prereg(r))
        code, out, _ = run_cli(["freeze", "--root", str(self.root), "prereg", PREREG])
        self.assertEqual(code, 3, out)

    def test_missing_prereg_and_record(self):
        with self.assertRaises(freeze.FreezeError):
            freeze.check_prereg(self.root, PREREG)
        self.prereg()
        with self.assertRaises(freeze.FreezeError):
            freeze.check_prereg(self.root, PREREG, records=[self.root / "nope.md"])

    def test_freeze_prereg_cli(self):
        self.prereg()
        self.assertEqual(run_cli(["freeze", "--root", str(self.root), "prereg", PREREG])[0], 0)
        (self.root / "scripts/container_run.py").write_text("image v2\n")
        code, out, _ = run_cli(["freeze", "--root", str(self.root), "prereg", PREREG])
        self.assertEqual(code, 3)
        self.assertIn("ATTENTION: scripts/container_run.py (plumbing set) changed", out)
        code, out, _ = run_cli(["freeze", "--root", str(self.root), "prereg", PREREG, "--json"])
        self.assertEqual(json.loads(out)["exit"], 3)
        record = self.root / "record.md"
        new = sha("image v2\n")
        record.write_text(f"```deviations\n2026-11-02  {new}  scripts/container_run.py  image v2\n```\n")
        code, out, _ = run_cli(["freeze", "--root", str(self.root), "prereg", PREREG, "--record", str(record)])
        self.assertEqual(code, 0, out)
        self.assertIn("1 of 2 file(s) unchanged", out)
        (self.root / "kit/score.py").write_text("score v2\n")
        self.assertEqual(run_cli(["freeze", "--root", str(self.root), "prereg", PREREG])[0], 1)


if __name__ == "__main__":
    unittest.main()
