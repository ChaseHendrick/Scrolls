"""The kit home (kit/kithome.py): KIT_HOME, else the source folder when kit runs from one, else the working
directory; files that ship with the source; and the places that write there (a plan folder, the ledger, the
agent tools' work home)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes as fakes  # noqa: E402
from test_autopipe import catalog  # noqa: E402

from kit import autopipe, kithome, vc3d_agent  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class TestHome(unittest.TestCase):
    def test_kit_home_wins(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(kithome.home({"KIT_HOME": d}), Path(d))
            self.assertEqual(kithome.path("work", "x", env={"KIT_HOME": d}), Path(d) / "work" / "x")

    def test_a_source_checkout_keeps_its_own_folder(self):
        # this repository has scripts/ beside kit/, so with no KIT_HOME the home is the repository, as before
        self.assertTrue(kithome.source_checkout())
        self.assertEqual(kithome.SOURCE, ROOT)
        self.assertEqual(kithome.home({}), ROOT)
        self.assertEqual(kithome.home({"KIT_HOME": "  "}), ROOT)

    def test_an_installed_kit_writes_in_the_working_directory(self):
        with tempfile.TemporaryDirectory() as site, tempfile.TemporaryDirectory() as cwd:
            (Path(site) / "kit").mkdir()                  # site-packages: kit/ with no scripts/ beside it
            old = os.getcwd()
            os.chdir(cwd)
            try:
                self.assertFalse(kithome.source_checkout(site))
                self.assertEqual(kithome.home({}, source=site).resolve(), Path(cwd).resolve())
            finally:
                os.chdir(old)

    def test_relative_kit_home_is_made_absolute(self):
        with tempfile.TemporaryDirectory() as cwd:
            old = os.getcwd()
            os.chdir(cwd)
            try:
                got = kithome.home({"KIT_HOME": "runs"})
            finally:
                os.chdir(old)
            self.assertTrue(got.is_absolute())
            self.assertEqual(got.resolve(), (Path(cwd) / "runs").resolve())

    def test_source_files_and_a_clear_message_when_missing(self):
        self.assertEqual(kithome.source_file("scripts/vc3d/ink.py"), ROOT / "scripts" / "vc3d" / "ink.py")
        with tempfile.TemporaryDirectory() as site:
            with self.assertRaises(kithome.MissingSource) as err:
                kithome.source_file("scripts/vc3d/ink.py", "the ink tool", source=site)
        self.assertIn("the ink tool needs it", str(err.exception))
        self.assertIn("pip install -e .", str(err.exception))
        self.assertIsInstance(err.exception, FileNotFoundError)

    def test_python_env_puts_this_kit_first(self):
        env = kithome.python_env({"PYTHONPATH": os.pathsep.join(["/a", str(kithome.SOURCE)])})
        self.assertEqual(env["PYTHONPATH"].split(os.pathsep), [str(kithome.SOURCE), "/a"])
        self.assertEqual(kithome.python_env({})["PYTHONPATH"], str(kithome.SOURCE))

    def test_ledger_default_follows_kit_home(self):
        with tempfile.TemporaryDirectory() as d:
            code = "from kit import ledger, surfbench; print(ledger.DEFAULT_ROOT); print(surfbench.DEFAULT_CACHE)"
            env = dict(os.environ, KIT_HOME=d, PYTHONPATH=str(ROOT))
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                                 cwd=d, check=True).stdout.split()
            self.assertEqual(out, [str(Path(d) / "experiments"), str(Path(d) / "work" / "surfbench" / "cache")])
            env.pop("KIT_HOME")
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                                 cwd=d, check=True).stdout.split()
            self.assertEqual(out, [str(ROOT / "experiments"), str(ROOT / "work" / "surfbench" / "cache")])


class TestAgentHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        fakes.make_bin(self.d / "bin")
        self.env = {k: v for k, v in fakes.env_for(self.d / "bin", self.d / "unused").items() if k != "KIT_VC3D_HOME"}
        self.home = self.d / "kithome"
        self.env["KIT_HOME"] = str(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def test_context_root_and_work_home(self):
        ctx = vc3d_agent.Context(env=self.env)
        self.assertEqual((ctx.root, ctx.home), (self.home, self.home / "work" / "vc3d"))
        self.assertEqual(vc3d_agent.resolve(ctx, "work/autopipe/x"), self.home / "work" / "autopipe" / "x")
        # without KIT_HOME the default is the repository, as it always was
        bare = vc3d_agent.Context(env={k: v for k, v in self.env.items() if k != "KIT_HOME"})
        self.assertEqual((bare.root, bare.home), (ROOT, ROOT / "work" / "vc3d"))

    def test_a_plan_folder_lands_in_kit_home(self):
        ctx = vc3d_agent.Context(env=self.env)
        with mock.patch.object(autopipe.vc3d_catalog, "load", return_value=catalog()) as load:
            res = vc3d_agent.call("autopipeline", {"action": "plan", "sample": "PHercTest"}, ctx)
        self.assertEqual(load.call_args[0][0], self.home / "work" / "vc3d" / "cache")
        out = Path(res["out"])
        self.assertEqual(out.parent, self.home / "work" / "autopipe")
        self.assertEqual(json.loads((out / "plan.json").read_text())["digest"], res["digest"])
        self.assertFalse((ROOT / "work" / "autopipe" / out.name).exists())
        # status reads it back from a path relative to the kit home
        st = vc3d_agent.call("autopipeline", {"action": "status", "out": f"work/autopipe/{out.name}"}, ctx)
        self.assertEqual(st["digest"], res["digest"])

    def test_the_source_folder_stays_guarded(self):
        ctx = vc3d_agent.Context(env=self.env)
        self.assertTrue(vc3d_agent.ignored(ctx, self.home / "anything"))   # the kit home here is not in git
        with self.assertRaises(vc3d_agent.ToolError) as err:
            vc3d_agent.writable(ctx, ROOT / "docs" / "should-not-exist")
        self.assertIn("rule 6", str(err.exception))
        self.assertTrue(vc3d_agent.ignored(ctx, ROOT / "work" / "x"))

    def test_git_errors_fail_closed(self):
        ctx = vc3d_agent.Context(env=self.env)
        self.home.mkdir(parents=True)
        target = self.home / "tracked.txt"

        def git(answer):            # every git call fails (exit 128) with this message
            return lambda ctx, *args, timeout=20, cwd=None: subprocess.CompletedProcess(args, 128, "", answer)

        dubious = "fatal: detected dubious ownership in repository at '/x'\n"
        broken = "fatal: not a git repository: /gone/.git/worktrees/x\n"      # a .git file pointing nowhere
        for answer in (dubious, broken):
            with self.subTest(answer=answer), mock.patch.object(vc3d_agent, "_git", git(answer)):
                self.assertFalse(vc3d_agent.ignored(ctx, target))
                with self.assertRaises(vc3d_agent.ToolError):
                    vc3d_agent.writable(ctx, "tracked.txt")
        nogit = "fatal: not a git repository (or any of the parent directories): .git\n"
        with mock.patch.object(vc3d_agent, "_git", git(nogit)):
            self.assertTrue(vc3d_agent.ignored(ctx, target))
        # git not installed: outside git only when no .git lies above
        exists = Path.exists

        def fixture_exists(path):
            # Model a non-repository fixture even inside a managed host's ancestor checkout.
            # The .git created inside this test's own home must still make the guard refuse.
            if path.name == ".git" and path.parent in self.home.parents:
                return False
            return exists(path)

        with mock.patch.object(vc3d_agent, "_git", return_value=None), \
                mock.patch.object(Path, "exists", fixture_exists):
            self.assertTrue(vc3d_agent.ignored(ctx, target))
            (self.home / ".git").mkdir()
            self.assertFalse(vc3d_agent.ignored(ctx, target))

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "needs root to make a repository git refuses")
    def test_a_repository_git_refuses_is_not_taken_as_outside_git(self):
        repo = self.d / "theirs"
        repo.mkdir()
        q = dict(capture_output=True, text=True, cwd=repo)
        subprocess.run(["git", "init", "-q", "."], check=True, **q)
        (repo / "tracked.txt").write_text("x\n")
        subprocess.run(["git", "add", "tracked.txt"], check=True, **q)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], check=True, **q)
        for p in [repo, *repo.rglob("*")]:
            os.lchown(p, 12345, 12345)
        probe = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], **q)
        if probe.returncode != 128 or "dubious" not in probe.stderr:
            self.skipTest("this git reads repositories of other users (safe.directory)")
        ctx = vc3d_agent.Context(env=dict(self.env, KIT_HOME=str(repo)))
        with self.assertRaises(vc3d_agent.ToolError):
            vc3d_agent.writable(ctx, "tracked.txt")
        self.assertTrue(vc3d_agent.ignored(ctx, repo / "work" / "x"))

    def test_a_source_copy_with_no_git_keeps_to_the_ignored_folders(self):
        # a release downloaded as a zip: the kit home is the source folder, and no repository holds it. The code
        # folder still takes only work/, experiments/ and the like (the release cut's tests run in such a copy)
        src = self.d / "unzipped"
        (src / "scripts").mkdir(parents=True)
        probe = subprocess.run(["git", "-C", str(src), "rev-parse", "--is-inside-work-tree"], capture_output=True,
                               text=True)
        if probe.returncode == 0:
            self.skipTest("the temporary folder lies inside a git repository")
        env = {k: v for k, v in self.env.items() if k != "KIT_HOME"}
        with mock.patch.object(vc3d_agent, "ROOT", src), mock.patch.object(kithome, "SOURCE", src):
            ctx = vc3d_agent.Context(env=env)
            self.assertEqual(ctx.root, src)
            with self.assertRaises(vc3d_agent.ToolError):
                vc3d_agent.writable(ctx, "myruns/x")
            self.assertEqual(vc3d_agent.writable(ctx, "work/x"), src / "work" / "x")

    def test_kit_tool_runs_in_kit_home(self):
        ctx = vc3d_agent.Context(env=self.env)
        self.home.mkdir(parents=True)
        res = vc3d_agent.call("kit", {"args": ["run", "list"]}, ctx)
        self.assertEqual(res["exit"], 0, res["output"])


if __name__ == "__main__":
    unittest.main()
