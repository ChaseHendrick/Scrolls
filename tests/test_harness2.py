"""Optional Harness2 adapter (scripts/harness2/).

Local checks run everywhere. The pinned-core checks run the real upstream engine and need
Linux or another POSIX system, Python 3.12 or 3.13, and a Harness2 checkout at the pin, named
by SCROLLS_HARNESS2_UPSTREAM or placed at work/deps/harness2; otherwise they skip.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kit import provenance

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "scripts" / "harness2"


def load(name):
    spec = importlib.util.spec_from_file_location(f"harness2_{name}", FOLDER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = load("run")
engine = load("engine")


def upstream_checkout():
    path = Path(os.environ.get("SCROLLS_HARNESS2_UPSTREAM") or ROOT / "work" / "deps" / "harness2")
    if os.name != "posix" or not (3, 12) <= sys.version_info[:2] < (3, 14) or not path.is_dir():
        return None
    try:
        head = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except OSError:
        return None
    return path.resolve() if head == run.PIN else None


UPSTREAM = upstream_checkout()


class RecipeAndOutputTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_recipe_is_exactly_two_typed_fields(self):
        self.assertEqual(run.recipe('{"recheck_files": true, "schema": 1}'),
                         {"schema": 1, "recheck_files": True})
        for bad in ('{"schema": 1}', '{"schema": 1, "recheck_files": true, "command": "rm"}',
                    '{"schema": true, "recheck_files": true}', '{"schema": 1, "recheck_files": 1}',
                    '{"schema": 2, "recheck_files": false}', '[1]', '"x"'):
            with self.assertRaisesRegex(ValueError, "exactly schema: 1"):
                run.recipe(bad)
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            run.recipe('{"schema": 1, "recheck_files": true, "recheck_files": false}')
        with self.assertRaisesRegex(ValueError, "non-finite"):
            run.recipe('{"schema": NaN, "recheck_files": true}')
        with self.assertRaisesRegex(ValueError, "exceeds 1024 bytes"):
            run.recipe('{"schema": 1, "recheck_files": true' + " " * 1024 + "}")

    def test_paths_refuse_traversal_and_links(self):
        with self.assertRaisesRegex(ValueError, "parent traversal"):
            run.safe_path(self.root / "a" / ".." / "b")
        if hasattr(os, "symlink"):
            (self.root / "real").mkdir()
            (self.root / "link").symlink_to(self.root / "real")
            with self.assertRaisesRegex(ValueError, "symlink is not allowed"):
                run.safe_path(self.root / "link" / "out")

    def test_output_is_new_or_this_finished_intact_run(self):
        out, identity = self.root / "out", {"schema": 1, "k": 1}
        self.assertFalse(run.prepare_output(out, identity))
        self.assertEqual(run.strict_json((out / "manifest.json").read_text()), identity)
        with self.assertRaisesRegex(ValueError, "did not finish"):
            run.prepare_output(out, identity)
        with self.assertRaisesRegex(ValueError, "provenance is incompatible"):
            run.prepare_output(out, {"schema": 1, "k": 2})
        (out / "result.txt").write_text("done\n")
        receipt = run.snapshot(out)
        (out / "receipt.json").write_text(run.json_text(receipt))
        (out / "result.txt").write_text("edited\n")
        with self.assertRaisesRegex(ValueError, "artifacts changed or are incomplete"):
            run.prepare_output(out, identity)
        (out / "result.txt").write_text("done\n")
        self.assertTrue(run.prepare_output(out, identity))
        self.assertFalse((out / "receipt.json").exists(), "a resumed run must earn a new receipt")
        foreign = self.root / "foreign"
        foreign.mkdir()
        (foreign / "notes.txt").write_text("keep\n")
        with self.assertRaisesRegex(ValueError, "holds no run"):
            run.prepare_output(foreign, identity)
        with self.assertRaisesRegex(ValueError, "must be under work/"):
            run.prepare_output(ROOT / "docs" / "harness2-out", identity)

    def test_upstream_must_be_the_pinned_commit(self):
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        repo = self.root / "not-harness2"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        with self.assertRaisesRegex(ValueError, "must be a checkout at"):
            run.upstream_identity(repo)
        with self.assertRaisesRegex(ValueError, "must be a checkout at"):
            run.upstream_identity(self.root / "absent")

    def test_harness2_stays_optional(self):
        self.assertNotIn("harness2", (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower())
        probe = "import sys, kit.cli; print(any(m.split('.')[0] == 'harness2' for m in sys.modules))"
        got = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(got.stdout.strip(), "False", got.stderr)

    def test_cli_refuses_bad_upstream_with_exit_2(self):
        candidate = self.root / "recipe.json"
        candidate.write_text('{"schema": 1, "recheck_files": true}')
        code = subprocess.run([sys.executable, str(FOLDER / "run.py"), "compare", "--upstream",
                               str(self.root / "absent"), "--out", str(self.root / "out"),
                               "--candidate", str(candidate)], capture_output=True, text=True, timeout=120)
        self.assertEqual(code.returncode, 2, code.stderr)
        self.assertIn("harness2:", code.stderr)


class FixtureAndGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name).resolve() / "run"
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_fixture_controls_can_fail_in_kit(self):
        expected = engine.ensure_fixtures(self.out, provenance)
        self.assertEqual(sorted(expected.values()), ["accept", "reject", "reject"])
        for task, control in engine.CONTROLS.items():
            record = json.loads((self.out / "fixtures" / task / "source" / "record.json").read_text())
            self.assertEqual(provenance.verify(record), [], "every record still matches its digest")
            problems = provenance.verify(record, recheck_files=True)
            self.assertEqual(bool(problems), control != "clean", (control, problems))
        self.assertEqual(engine.ensure_fixtures(self.out, provenance), expected)
        (self.out / "fixtures" / "record-a" / "source" / "input.txt").write_text("edited\n")
        with self.assertRaisesRegex(engine.EngineError, "fixtures differ"):
            engine.ensure_fixtures(self.out, provenance)

    def guarded(self, module, setup, action):
        code = (f"import importlib.util, sys\nspec = importlib.util.spec_from_file_location('m', {str(FOLDER / module)!r})\n"
                f"m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n{setup}\n"
                f"try:\n    {action}\nexcept RuntimeError as exc:\n    print('REFUSED', exc)\nelse:\n    print('ALLOWED')\n")
        got = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60,
                             cwd=self.out)
        return got.stdout + got.stderr

    def test_engine_guard_refuses_outside_writes_network_and_other_processes(self):
        setup = f"from pathlib import Path\nm.install_guard(Path({str(self.out)!r}))"
        outside = Path(self.tmp.name).resolve() / "outside.txt"
        self.assertIn("REFUSED", self.guarded("engine.py", setup, f"open({str(outside)!r}, 'w')"))
        self.assertFalse(outside.exists())
        self.assertIn("ALLOWED", self.guarded("engine.py", setup, f"open({str(self.out / 'in.txt')!r}, 'w')"))
        self.assertIn("REFUSED", self.guarded("engine.py", setup, "import socket; socket.socket()"))
        self.assertIn("REFUSED", self.guarded("engine.py", setup,
                                              "import subprocess; subprocess.run(['true'])"))

    def test_worker_guard_refuses_writes_and_processes(self):
        setup = "sys.addaudithook(m.forbid_external)"
        target = self.out / "w.txt"
        self.assertIn("REFUSED", self.guarded("worker.py", setup, f"open({str(target)!r}, 'w')"))
        self.assertFalse(target.exists())
        self.assertIn("REFUSED", self.guarded("worker.py", setup, "import subprocess; subprocess.run(['true'])"))
        self.assertIn("ALLOWED", self.guarded("worker.py", setup, f"open({str(FOLDER / 'run.py')!r}).read()"))


@unittest.skipIf(UPSTREAM is None, "needs POSIX, Python 3.12 or 3.13 and a Harness2 checkout at the pin "
                                   "(SCROLLS_HARNESS2_UPSTREAM or work/deps/harness2)")
class PinnedCoreTest(unittest.TestCase):
    """The real upstream run_domain, both recursion modes, judged after selection."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name).resolve()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cli(self, *args, upstream=None):
        got = subprocess.run([sys.executable, str(FOLDER / "run.py"), *args, "--upstream", str(upstream or UPSTREAM)],
                             capture_output=True, text=True, timeout=600)
        summary = json.loads(got.stdout) if got.stdout.strip().startswith("{") else None
        return got.returncode, summary, got.stderr

    def comparison(self, out):
        return json.loads((out / "comparison.json").read_text())

    def recipe_file(self, recheck):
        path = self.root / f"recipe-{recheck}.json"
        path.write_text(json.dumps({"schema": 1, "recheck_files": recheck}))
        return path

    def test_demo_controls_resume_and_tampering(self):
        out = self.root / "demo"
        code, summary, err = self.cli("demo", "--out", str(out), "--k", "1")
        self.assertEqual(code, 0, err + (out / "engine.log").read_text())
        self.assertEqual((summary["status"], summary["resumed"]), ("ok", False))
        self.assertEqual((summary["new_executions"], summary["new_proposer_calls"]), (21, 24))
        result = self.comparison(out)
        self.assertEqual(result["harness2"]["commit"], run.PIN)
        self.assertEqual((result["harness2"]["done"], result["harness2"]["failed"]), (3, 0))
        self.assertEqual([t["library_entries_before"]["agg"] for t in result["harness2"]["tasks"]], [0, 1, 2])
        rows = {row["control"]: row for row in result["controls"]}
        # The digest-only baseline is kept, and it accepts the changed and missing inputs.
        self.assertEqual([rows[c]["baseline"][0]["verdict"] for c in ("clean", "changed", "missing")],
                         ["accept", "accept", "accept"])
        self.assertEqual(result["summary"]["baseline_correct"], 1)
        for mode in ("agg", "seq"):
            self.assertEqual([rows[c]["adopted"][mode]["verdict"] for c in ("clean", "changed", "missing")],
                             ["accept", "reject", "reject"])
            self.assertEqual(result["recipes"]["adopted"][mode], [{"schema": 1, "recheck_files": True}])

        code, summary, err = self.cli("demo", "--out", str(out), "--k", "1")
        self.assertEqual(code, 0, err)
        self.assertEqual((summary["resumed"], summary["new_executions"], summary["new_proposer_calls"]),
                         (True, 0, 0))
        self.assertEqual(self.comparison(out)["controls"], result["controls"])

        code, _, err = self.cli("demo", "--out", str(out), "--k", "2")
        self.assertEqual(code, 2)
        self.assertIn("provenance is incompatible", err)

        answer = next((out / "executions").rglob("answer.txt"))
        original = answer.read_bytes()
        answer.write_text("verdict: reject\n")
        code, _, err = self.cli("demo", "--out", str(out), "--k", "1")
        self.assertEqual(code, 2)
        self.assertIn("artifacts changed or are incomplete", err)
        answer.write_bytes(original)
        # An engine that never finished leaves no receipt, so its output is never reused.
        (out / "engine.log").write_text("interrupted\n")
        (out / "receipt.json").unlink()
        code, _, err = self.cli("demo", "--out", str(out), "--k", "1")
        self.assertEqual(code, 2)
        self.assertIn("did not finish", err)

    def test_modified_upstream_is_refused(self):
        copy = self.root / "upstream-copy"
        shutil.copytree(UPSTREAM, copy, symlinks=True)
        out = self.root / "refused"
        target = copy / "harness2" / "core" / "selection.py"
        original = target.read_bytes()
        target.write_bytes(original + b"\n# local change\n")
        code, _, err = self.cli("demo", "--out", str(out), upstream=copy)
        self.assertEqual(code, 2)
        self.assertIn("upstream source differs from pin", err)
        target.write_bytes(original)
        (copy / "harness2" / "core" / "__pycache__").mkdir()
        (copy / "harness2" / "core" / "__pycache__" / "x.pyc").write_bytes(b"x")
        code, _, err = self.cli("demo", "--out", str(out), upstream=copy)
        self.assertIn("missing or extra files", err)
        shutil.rmtree(copy / "harness2" / "core" / "__pycache__")
        (copy / ".env").write_text("HARNESS2_SOLVER_MODEL=x/y\n")
        code, _, err = self.cli("demo", "--out", str(out), upstream=copy)
        self.assertEqual(code, 2)
        self.assertIn(".env is not allowed", err)
        self.assertFalse(out.exists(), "a refused upstream must not create output")

    def test_bad_candidate_is_evaluated_exactly(self):
        out = self.root / "bad"
        code, summary, err = self.cli("compare", "--out", str(out), "--candidate", str(self.recipe_file(False)))
        self.assertEqual(code, 1, err)
        self.assertEqual(summary["status"], "candidate-failed")
        result = self.comparison(out)
        bad = {"schema": 1, "recheck_files": False}
        self.assertEqual(result["recipes"]["candidate"], bad)
        self.assertEqual(result["recipes"]["adopted"], {"agg": [bad], "seq": [bad]})
        self.assertEqual(result["summary"]["adopted_correct"], {"agg": 1, "seq": 1})

    def test_good_candidate_k2_uses_selection(self):
        out = self.root / "good"
        code, summary, err = self.cli("compare", "--out", str(out), "--candidate", str(self.recipe_file(True)),
                                      "--k", "2")
        self.assertEqual(code, 0, err)
        self.assertEqual((summary["status"], summary["new_executions"], summary["new_proposer_calls"]),
                         ("ok", 42, 48))
        result = self.comparison(out)
        self.assertEqual(result["summary"]["adopted_correct"], {"agg": 3, "seq": 3})
        selections = list((out / "runs").rglob("selection.json"))
        self.assertTrue(selections)
        self.assertTrue(all(json.loads(p.read_text())["trivial"] is False for p in selections))


if __name__ == "__main__":
    unittest.main()
