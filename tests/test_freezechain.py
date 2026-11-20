"""The freeze chain's outside check of 20 Nov 2026, as tests: kit freeze, kit/freezeguard.py and kit reviewpin on toy
git repositories that hold a small evaluation (a threshold rule's accuracy on a CSV), with no scroll data.

Freeze bars: a one-byte change to the frozen script, to a module it imports, and to a module imported inside a
function is each refused by check and launch_check, and the run goes ahead after the revert; a one-byte change to an
unlisted file that is never executed does not stop the run; a freeze whose hand-written list leaves out the imported
modules launches but is refused by run_script, which names the modules; import_closure finds the import inside a
function. Review-pin bars: GO carries after base-only merges (another file, and the same file far from the PR's
hunk), is dropped by a one-byte change in the PR's own line and by a merge commit that also edits that line, and
carries again after a revert."""

import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from kit import freeze, freezeguard, reviewpin

ENV = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="T",
           GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

EVAL = """# version 1
# toy evaluation: accuracy of a fixed threshold rule on data/toy.csv
import os
import metrics

HERE = os.path.dirname(os.path.abspath(__file__))
rows = [l.split(",") for l in open(os.path.join(HERE, "..", "data", "toy.csv")).read().split("\\n")[1:] if l]
x = [float(r[0]) for r in rows]
y = [int(r[1]) for r in rows]
pred = [1 if v > 0.5 else 0 for v in x]
print("accuracy", metrics.accuracy(y, pred))
"""
METRICS = """# version 1
def accuracy(y, p):
    from helpers import mean      # imported inside a function, as late imports are
    return round(mean([int(a == b) for a, b in zip(y, p)]), 4)
"""
HELPERS = """# version 1
def mean(v):
    return sum(v) / len(v)
"""
README = "# version 1\nA toy evaluation for the freeze chain tests.\n"
DATA = "x,y\n" + "".join(f"{(i * 37 % 100) / 100:.2f},{int((i * 37 % 100) / 100 > 0.45)}\n" for i in range(40))
PREREG = "# Toy evaluation preregistration\n\nStatus: {status}\n\nRule: report accuracy of the threshold rule.\n{hashes}"


def git(repo, *a):
    p = subprocess.run(["git", *a], cwd=repo, env=ENV, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(a)}: {p.stderr}")
    return p.stdout.strip()


def write(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def one_byte(repo, rel, old=b"version 1", new=b"version 2"):
    """Change exactly one byte of repo/rel."""
    p = Path(repo) / rel
    a = p.read_bytes()
    assert a.count(old) == 1, rel
    b = a.replace(old, new)
    assert len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1
    p.write_bytes(b)


@unittest.skipUnless(shutil.which("git"), "needs git")
class FreezeChainOutsideCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    # ---- freeze and freezeguard ------------------------------------------------------------------------------

    def build_freeze_repo(self):
        repo = self.base / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        for rel, t in (("toy/eval.py", EVAL), ("toy/metrics.py", METRICS), ("toy/helpers.py", HELPERS),
                       ("README.md", README), ("data/toy.csv", DATA),
                       (freeze.FREEZES, json.dumps({"freezes": []}, indent=1) + "\n"),
                       ("prereg/toy-eval.md", PREREG.format(status="Draft", hashes="")),
                       ("prereg/toy-eval-hand.md", PREREG.format(status="Draft", hashes=""))):
            write(repo, rel, t)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "toy evaluation code and drafts")
        closure = freezeguard.import_closure(str(repo), ["toy/eval.py"], search=("toy",))
        self.assertEqual(closure, ["toy/eval.py", "toy/helpers.py", "toy/metrics.py"])
        files = sorted(set(closure) | {"data/toy.csv"})
        block = "\n```code-sha256\n" + "".join(
            f"{hashlib.sha256((repo / f).read_bytes()).hexdigest()}  {f}\n" for f in files) + "```\n"
        write(repo, "prereg/toy-eval.md", PREREG.format(status="Frozen", hashes=block))
        git(repo, "commit", "-q", "-am", "freeze toy-eval-f1")
        self.assertEqual(self.cli(repo, "add", "--id", "toy-eval-f1", "--prereg", "prereg/toy-eval.md",
                                  "--from-prereg", "--note", "toy eval, files from import_closure"), 0)
        git(repo, "commit", "-q", "-am", "register toy-eval-f1")
        write(repo, "prereg/toy-eval-hand.md", PREREG.format(status="Frozen", hashes=""))
        git(repo, "commit", "-q", "-am", "freeze toy-eval-hand")
        self.assertEqual(self.cli(repo, "add", "--id", "toy-eval-hand", "--prereg", "prereg/toy-eval-hand.md",
                                  "--file", "toy/eval.py", "--file", "data/toy.csv",
                                  "--note", "a hand list that leaves out the imported modules"), 0)
        git(repo, "commit", "-q", "-am", "register toy-eval-hand")
        return repo

    def cli(self, repo, *argv):
        p = argparse.ArgumentParser()
        freeze.add_arguments(p)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return freeze.run(p.parse_args(list(argv)), root=repo)

    def guarded(self, repo, fid):
        """kit freeze check, then launch_check, then run_script of toy/eval.py under the freeze."""
        r = {"check": freeze.check(repo, fid)["exit"]}
        entry = freeze.find(freeze.load(repo), fid)
        try:
            freeze.launch_check(entry, repo)
        except freeze.FreezeRefused as exc:
            return dict(r, outcome="launch refused", why=str(exc))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                freeze.run_script(str(repo / "toy" / "eval.py"), [], entry, repo)
        except freeze.FreezeRefused as exc:
            return dict(r, outcome="run refused", why=str(exc))
        return dict(r, outcome="ran")

    def test_one_byte_changes_are_refused_and_reverts_run(self):
        repo = self.build_freeze_repo()
        self.assertEqual(self.guarded(repo, "toy-eval-f1"), {"check": 0, "outcome": "ran"})
        for rel in ("toy/eval.py", "toy/metrics.py", "toy/helpers.py"):
            with self.subTest(changed=rel):
                one_byte(repo, rel)
                got = self.guarded(repo, "toy-eval-f1")
                self.assertEqual((got["check"], got["outcome"]), (1, "launch refused"))
                self.assertIn(f"{rel} differ from the freeze", got["why"])
                git(repo, "checkout", "--", rel)
                self.assertEqual(self.guarded(repo, "toy-eval-f1"), {"check": 0, "outcome": "ran"})

    def test_controls_an_unlisted_file_and_a_short_hand_list(self):
        repo = self.build_freeze_repo()
        one_byte(repo, "README.md")                     # never executed, not listed: the run goes ahead
        self.assertEqual(self.guarded(repo, "toy-eval-f1")["outcome"], "ran")
        git(repo, "checkout", "--", "README.md")
        got = self.guarded(repo, "toy-eval-hand")       # launches, then the child loads modules the list leaves out
        self.assertEqual(got["outcome"], "run refused")
        self.assertIn("loaded toy/helpers.py, toy/metrics.py", got["why"])

    # ---- reviewpin -------------------------------------------------------------------------------------------

    def build_pr_repo(self):
        repo = self.base / "prrepo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        body = "".join(f"# filler line {i}\n" for i in range(30))
        write(repo, "toy/metrics.py", "# version 1\n" + body + METRICS.split("\n", 1)[1])
        write(repo, "README.md", README)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        git(repo, "checkout", "-q", "-b", "pr")
        p = repo / "toy" / "metrics.py"
        p.write_text(p.read_text() + "\n\ndef error_rate(y, p):\n    return 1 - accuracy(y, p)  # pr version 1\n")
        git(repo, "commit", "-q", "-am", "PR: add error_rate")
        return repo

    def rp(self, repo, *argv):
        p = argparse.ArgumentParser()
        reviewpin.add_arguments(p)
        log = str(self.base / "verdicts.jsonl")          # outside the repository, so git add -A never takes it
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = reviewpin.run(p.parse_args(["--root", str(repo), "--log", log, *argv]))
        try:
            return code, json.loads(buf.getvalue())
        except ValueError:
            return code, buf.getvalue()

    def delta(self, repo):
        code, j = self.rp(repo, "delta", "101", "--head", "HEAD", "--base", "main", "--no-fetch", "--json")
        return code, j["status"], [x["path"] for x in j["changes"] if x["in_scope"]]

    def test_go_carries_over_base_only_merges_and_drops_on_one_byte(self):
        repo = self.build_pr_repo()
        p1 = git(repo, "rev-parse", "HEAD")
        self.assertEqual(self.rp(repo, "record", "101", p1, "GO", "--base", "main", "--reviewer", "test")[0], 0)
        self.assertEqual(self.delta(repo), (0, "carries", []))
        git(repo, "checkout", "-q", "main")
        write(repo, "README.md", README + "base change 1\n")
        git(repo, "commit", "-q", "-am", "base: readme")
        git(repo, "checkout", "-q", "pr")
        git(repo, "merge", "-q", "--no-edit", "main")
        self.assertEqual(self.delta(repo), (0, "carries", []))           # base-only merge, another file
        git(repo, "checkout", "-q", "main")
        one_byte(repo, "toy/metrics.py", b"# filler line 3\n", b"# filler line X\n")
        git(repo, "commit", "-q", "-am", "base: metrics far from the PR hunk")
        git(repo, "checkout", "-q", "pr")
        git(repo, "merge", "-q", "--no-edit", "main")
        self.assertEqual(self.delta(repo), (0, "carries", []))           # same file, far from the hunk
        one_byte(repo, "toy/metrics.py", b"pr version 1", b"pr version 2")
        git(repo, "commit", "-q", "-am", "PR: one byte in its own line")
        p2 = git(repo, "rev-parse", "HEAD")
        self.assertEqual(self.delta(repo), (3, "recheck", ["toy/metrics.py"]))
        git(repo, "revert", "--no-edit", p2)
        self.assertEqual(self.delta(repo), (0, "carries", []))
        git(repo, "checkout", "-q", "main")
        write(repo, "README.md", README + "base change 1\nbase change 2\n")
        git(repo, "commit", "-q", "-am", "base: readme again")
        git(repo, "checkout", "-q", "pr")
        git(repo, "merge", "-q", "--no-commit", "--no-ff", "main")
        one_byte(repo, "toy/metrics.py", b"pr version 1", b"pr version 3")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "--no-edit")
        self.assertEqual(self.delta(repo), (3, "recheck", ["toy/metrics.py"]))   # an edit inside a merge commit


if __name__ == "__main__":
    unittest.main()
