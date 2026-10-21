"""Tests for kit/runrecord.py on synthetic temporary git repositories: tokens, start and finish, the context manager
writing a record when its block raises, wrap with a failing command, adopt and its public refusal, check, attach,
the parent token and environment fields, `kit run local` writing a record by default, and the refusals of links
that do not resolve or are private under --public.

Keep this file byte-identical in Scrolls and Scrolls-private, as kit/runrecord.py.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from kit import causal, cli, ledger, localcost, provenance, runrecord

GIT = shutil.which("git")
ENV = dict(os.environ, GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="Test",
           GIT_COMMITTER_EMAIL="test@example.com")


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=ENV, check=True).stdout


class TokenTest(unittest.TestCase):
    def test_token(self):
        now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        self.assertEqual(runrecord.token(now=now), "20260102T030405Z")
        self.assertEqual(runrecord.token("auc-w00", now=now), "20260102T030405Z-auc-w00")
        with self.assertRaises(runrecord.RunRecordError):
            runrecord.token("Bad Slug", now=now)

    def test_attach_keeps_the_digest_valid(self):
        rec = {"schema": 1, "run": "x", "code": [], "models": [], "inputs": [], "outputs": []}
        rec["digest"] = runrecord._digest(rec)
        out = runrecord.attach(rec, ["source docs/logs/x.md", "control field:auc_reversed"])
        self.assertEqual(provenance.verify(out), [])
        self.assertEqual(out["causal"], ["source docs/logs/x.md", "control field:auc_reversed"])
        self.assertNotEqual(out["digest"], rec["digest"])
        with self.assertRaises(causal.CausalError):
            runrecord.attach(rec, ["not a line at all"])


@unittest.skipIf(GIT is None, "git is not installed")
class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        (self.root / "docs/logs").mkdir(parents=True)
        (self.root / "docs/logs/2026-01-01-note.md").write_text("# note\n", encoding="utf-8")
        (self.root / "data.txt").write_text("input\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "base")
        self.out = self.root / "out.txt"
        self.out.write_text("output\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_finish_adopt_check(self):
        rec = runrecord.start(self.root, "kit test", "20260101T000000Z", ["source docs/logs/2026-01-01-note.md"],
                              inputs=[str(self.root / "data.txt")], settings={"a": 1}, public=True)
        self.assertTrue((self.root / runrecord.WORK_RUNS / "20260101T000000Z.open.json").is_file())
        with self.assertRaises(runrecord.RunRecordError):
            runrecord.start(self.root, "kit test", "20260101T000000Z")
        done = runrecord.finish(self.root, "20260101T000000Z", outputs=[str(self.out)], exit_code=3)
        self.assertEqual(provenance.verify(done), [])
        self.assertEqual((done["exit_code"], done["kind"], done["public"]), (3, "run", True))
        self.assertEqual(len(done["inputs"]), 1)
        self.assertEqual(len(done["outputs"]), 1)
        self.assertEqual(len(done["settings_digest"]), 64)
        self.assertFalse((self.root / runrecord.WORK_RUNS / "20260101T000000Z.open.json").exists())
        dst = runrecord.adopt(self.root, "20260101T000000Z", public=True)
        self.assertEqual(dst, self.root / runrecord.ADOPTED / "20260101T000000Z.json")
        self.assertEqual(runrecord.check_record(json.loads(dst.read_text()), name="20260101T000000Z"), [])
        g = causal.load(self.root, public=True)
        self.assertIn(f"sha256:{done['digest']}", g.nodes)
        self.assertEqual(g.nodes["20260101T000000Z"]["record"], f"sha256:{done['digest']}")

    def test_public_refusals(self):
        for line in ("approval approval:x", "run ap-ABCDEFGHIJKLMNOPQRSTUV", "source work/x.json"):
            with self.subTest(line=line):
                with self.assertRaises(runrecord.RunRecordError):
                    runrecord.start(self.root, "kit test", "20260101T000001Z", [line], public=True)
        runrecord.start(self.root, "kit test", "20260101T000002Z", [], public=False)
        runrecord.finish(self.root, "20260101T000002Z")
        with self.assertRaises(runrecord.RunRecordError):
            runrecord.adopt(self.root, "20260101T000002Z", public=True)

    def test_unresolved_links_refused(self):
        for line in ("source r:nothing/here", "source docs/logs/missing.md", "decision D5"):
            with self.subTest(line=line):
                with self.assertRaises(runrecord.RunRecordError):
                    runrecord.start(self.root, "kit test", "20260101T000003Z", [line])

    def test_context_manager_writes_on_exception(self):
        with self.assertRaises(RuntimeError):
            with runrecord.run("kit test", root=self.root, run_token="20260101T000004Z") as r:
                r.output(str(self.out))
                r.app("ap-ABCDEFGHIJKLMNOPQRSTUV")
                raise RuntimeError("boom")
        rec = json.loads((self.root / runrecord.WORK_RUNS / "20260101T000004Z.json").read_text())
        self.assertEqual(rec["exit_code"], 1)
        self.assertIn("run ap-ABCDEFGHIJKLMNOPQRSTUV", rec["causal"])

    def test_check_finds_tampering(self):
        runrecord.start(self.root, "kit test", "20260101T000005Z")
        rec = runrecord.finish(self.root, "20260101T000005Z")
        rec["exit_code"] = 0 if rec["exit_code"] else 9
        self.assertIn("digest does not match the record", runrecord.check_record(rec))
        self.assertTrue(runrecord.check_record({"digest": "x"}))

    def test_wrap_writes_record_when_command_fails(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = runrecord.main(["wrap", "--tool", "false", "--token", "20260101T000006Z", "--root",
                                   str(self.root), "--", sys.executable, "-c", "raise SystemExit(4)"])
        self.assertEqual(code, 4)
        rec = json.loads((self.root / runrecord.WORK_RUNS / "20260101T000006Z.json").read_text())
        self.assertEqual(rec["exit_code"], 4)
        self.assertEqual(rec["argv"][0], sys.executable)

    def test_parent_and_env(self):
        with mock.patch.dict(os.environ, {runrecord.PARENT_ENV: "20260101T000099Z-outer"}):
            rec = runrecord.start(self.root, "kit test", "20260101T000008Z")
        self.assertEqual(rec["parent"], "20260101T000099Z-outer")
        self.assertIn("python", rec["env"])
        done = runrecord.finish(self.root, "20260101T000008Z")
        self.assertEqual(done["parent"], "20260101T000099Z-outer")
        self.assertEqual(provenance.verify(done), [])

    def test_run_local_writes_a_record_by_default(self):
        exp = self.root / "experiments"
        ledger.save({"slug": "t1", "status": "planned", "history": [], "costs": [], "scroll": "s"}, exp)
        config = self.root / "config.json"
        config.write_text("{}", encoding="utf-8")
        base = ["run", "--root", str(exp), "local", "t1", "--rate", "0.25", "--watts", "10"]
        with mock.patch.object(runrecord, "ROOT", self.root), \
                mock.patch.dict(os.environ, {localcost.ENV_CONFIG: str(config)}), redirect_stderr(io.StringIO()):
            code = cli.main(base + ["--causal", "source docs/logs/2026-01-01-note.md", "--adopt", "--",
                                    sys.executable, "-c", "raise SystemExit(5)"])
            self.assertEqual(code, 5)
            adopted = list((self.root / runrecord.ADOPTED).glob("*-t1.json"))
            self.assertEqual(len(adopted), 1)
            rec = json.loads(adopted[0].read_text())
            self.assertEqual((rec["tool"], rec["exit_code"]), ("kit run local t1", 5))
            self.assertEqual(rec["causal"], ["source docs/logs/2026-01-01-note.md"])
            self.assertEqual(cli.main(base + ["--causal", "source docs/logs/missing.md", "--", sys.executable,
                                              "-c", "pass"]), 2)                    # refused before it runs
            self.assertEqual(len(ledger.load("t1", exp)["costs"]), 1)
            self.assertEqual(cli.main(base + ["--no-record", "--", sys.executable, "-c", "pass"]), 0)
            self.assertEqual(len(list((self.root / runrecord.WORK_RUNS).glob("*.json"))), 1)

    def test_cli_check(self):
        runrecord.start(self.root, "kit test", "20260101T000007Z")
        runrecord.finish(self.root, "20260101T000007Z")
        path = str(self.root / runrecord.WORK_RUNS / "20260101T000007Z.json")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(runrecord.main(["check", path, "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())[path], [])


if __name__ == "__main__":
    unittest.main()
