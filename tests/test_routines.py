"""kit routines: the registry's guards, cadence by UTC date, timeouts, fail-soft results, the state file, the lock,
the built-in handoff check, and the session-start entry points (the Claude Code hook and docs/AI-AGENTS.md).

Fake commands (python -c ...) stand in for the real routines, so these tests need no network."""

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from kit import routines

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)
# Every command a registry may hold, as its words after "{python} -m". A new routine has to be added here, so the
# test that pins them fails until someone has looked at what the new command does.
READ_ONLY = {
    "kit.prizewatch --state work/routines/prize-page.json",
    "kit prizes",
    "kit prizetrack check",
    "kit run watch --exit-code",
    "kit patchdrift",
    "kit leaderboard check",
    "kit releases check",
    "kit routines check handoff",
    "unittest tests.test_repo",
}


def running(pid):
    """True while pid runs; a zombie (killed, not yet reaped by its new parent) counts as stopped."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    stat = Path(f"/proc/{pid}/stat")
    try:
        return stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def fake(name, code="", cadence="daily", timeout=20, requires=None, ci=False):
    return {"name": name, "cadence": cadence, "timeout_s": timeout, "command": ["{python}", "-c", code],
            "why": "test", "requires": requires or [], "ci": ci}


def good(**kw):
    r = {"name": "x", "cadence": "daily", "timeout_s": 10, "command": ["{python}", "-m", "kit", "prizes"],
         "why": "test"}
    r.update(kw)
    return {"routines": [r]}


class RegistryTest(unittest.TestCase):
    def test_repo_registry_loads_and_holds_only_read_only_commands(self):
        loaded = routines.load(routines.REGISTRY)
        self.assertTrue(loaded)
        for r in loaded:
            self.assertEqual(r["command"][:2], ["{python}", "-m"])
            self.assertIn(" ".join(r["command"][2:]), READ_ONLY, f"{r['name']}: a new command; review it first")

    def test_no_villa_pull_request_keep_alive_or_watcher(self):
        # Chase rejected keeping villa pull requests alive by machine (16 Oct 2026).
        for r in routines.load(routines.REGISTRY):
            words = " ".join([r["name"], *r["command"]]).lower()
            for bad in ("keep-alive", "keepalive", "keep-open", "villa-pr", "prwatch", "pr-watch"):
                self.assertNotIn(bad, words, r["name"])

    def test_good_entry_passes(self):
        (r,) = routines.validate(good())
        self.assertEqual(r["requires"], [])
        self.assertFalse(r["ci"])

    def test_bad_entries_are_refused(self):
        bad = [
            good(name="Has Space"), good(name="x" * 41), good(cadence="hourly"), good(timeout_s=0),
            good(timeout_s=routines.MAX_TIMEOUT + 1), good(timeout_s=True), good(command=[]),
            good(command=["python3", "-m", "kit", "prizes"]), good(command=["{python}", "-c", "print(1)"]),
            good(command=["{python}", "-m", "pip", "install", "x"]),
            good(command=["{python}", "-m", "kit", "hfsync", "pull"]),
            good(command=["{python}", "-m", "kit.hfsync"]),
            good(command=["{python}", "-m", "kit.submission_release", "plan"]),
            good(command=["{python}", "-m", "kit", "releases", "render"]),
            good(command=["{python}", "-m", "kit", "run", "all", "--approve", "abc"]),
            good(command=["{python}", "-m", "kit", "zerogpu", "run"]),
            good(command=["{python}", "-m", "kit", "x", "push"]),
            good(requires=["/etc/passwd"]), good(requires=["../Scrolls/x"]), good(why=""),
        ]
        for registry in bad:
            with self.assertRaises(routines.RoutineError, msg=json.dumps(registry)):
                routines.validate(registry)
        with self.assertRaises(routines.RoutineError):
            routines.validate({"routines": good()["routines"] * 2})
        with self.assertRaises(routines.RoutineError):
            routines.validate({"routine": []})

    def test_missing_registry_says_to_use_a_clone(self):
        with self.assertRaisesRegex(routines.RoutineError, "clone"):
            routines.load("/nonexistent/routines.json")


class CadenceTest(unittest.TestCase):
    daily, weekly = fake("d"), fake("w", cadence="weekly")

    def entry(self, completed=None, attempt=None):
        e = {}
        if completed:
            e["last_completed"] = completed
        if attempt:
            e["last_attempt"] = attempt
        return e

    def test_never_run_is_due(self):
        self.assertTrue(routines.is_due(self.daily, None, NOW))
        self.assertTrue(routines.is_due(self.weekly, {}, NOW))

    def test_daily_counts_utc_dates(self):
        self.assertFalse(routines.is_due(self.daily, self.entry("2026-10-16", "2026-10-16T00:05:00Z"), NOW))
        self.assertTrue(routines.is_due(self.daily, self.entry("2026-10-15", "2026-10-15T23:59:00Z"), NOW))
        # 00:10 UTC on the 16th: a run at 23:50 on the 15th was yesterday, but under an hour ago, so it waits.
        early = datetime(2026, 10, 16, 0, 10, tzinfo=timezone.utc)
        self.assertFalse(routines.is_due(self.daily, self.entry("2026-10-15", "2026-10-15T23:50:00Z"), early))
        self.assertTrue(routines.is_due(self.daily, self.entry("2026-10-15", "2026-10-15T23:50:00Z"),
                                        early + timedelta(hours=1)))

    def test_weekly_waits_seven_days(self):
        self.assertFalse(routines.is_due(self.weekly, self.entry("2026-10-10", "2026-10-10T09:00:00Z"), NOW))
        self.assertTrue(routines.is_due(self.weekly, self.entry("2026-10-09", "2026-10-09T09:00:00Z"), NOW))

    def test_skipped_retries_after_an_hour(self):
        recent = self.entry(None, "2026-10-16T09:30:00Z")
        self.assertFalse(routines.is_due(self.daily, recent, NOW))
        self.assertTrue(routines.is_due(self.daily, self.entry(None, "2026-10-16T08:30:00Z"), NOW))

    def test_damaged_dates_make_it_due(self):
        self.assertTrue(routines.is_due(self.daily, self.entry("yesterday", "soon"), NOW))


class ClassifyTest(unittest.TestCase):
    def test_exit_codes(self):
        self.assertEqual(routines.classify(0, "")[0], routines.OK)
        self.assertEqual(routines.classify(3, "")[0], routines.ATTENTION)
        self.assertEqual(routines.classify(75, "")[0], routines.SKIPPED)
        self.assertEqual(routines.classify(None, "")[0], routines.TIMEOUT)
        self.assertEqual(routines.classify(1, "AssertionError")[0], routines.FAIL)
        self.assertEqual(routines.classify(-9, "")[0], routines.FAIL)

    def test_fail_soft_offline_and_missing_dependency(self):
        status, note = routines.classify(2, "<urlopen error [Errno 111] Connection refused>")
        self.assertEqual((status, "offline" in note), (routines.SKIPPED, True))
        status, note = routines.classify(1, "ModuleNotFoundError: No module named 'numpy'")
        self.assertEqual(status, routines.SKIPPED)
        self.assertIn("numpy", note)

    def test_a_missing_kit_module_is_a_real_failure(self):
        self.assertEqual(routines.classify(1, "ModuleNotFoundError: No module named 'kit.gone'")[0], routines.FAIL)
        self.assertEqual(routines.classify(1, "ModuleNotFoundError: No module named 'tests.x'")[0], routines.FAIL)


class ExecuteTest(unittest.TestCase):
    def test_output_and_exit_code(self):
        code, out = routines.execute([sys.executable, "-c", "print('hi'); raise SystemExit(3)"], ROOT, 20)
        self.assertEqual((code, out.strip()), (3, "hi"))

    def test_missing_program_is_skipped_not_raised(self):
        code, out = routines.execute(["/nonexistent/program"], ROOT, 5)
        self.assertEqual(code, routines.EXIT_SKIPPED)
        self.assertIn("cannot start", out)

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX")
    def test_timeout_stops_the_whole_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / "grandchild.pid"
            code = ("import subprocess, sys, time\n"
                    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                    f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
                    "print('started', flush=True)\n"
                    "time.sleep(60)\n")
            t0 = time.monotonic()
            status, out = routines.execute([sys.executable, "-c", code], ROOT, 2)
            self.assertIsNone(status)
            self.assertLess(time.monotonic() - t0, 20)
            self.assertIn("started", out)
            self.assertIn("timeout", out)
            pid = int(pidfile.read_text())
            for _ in range(50):
                if not running(pid):
                    break
                time.sleep(0.1)
            else:
                self.fail("the grandchild outlived the timeout")

    def test_child_environment_has_no_credentials(self):
        base = {"PATH": "/bin", "HTTPS_PROXY": "http://proxy:3128", "GITHUB_TOKEN": "t", "GH_TOKEN": "t",
                "HF_TOKEN": "t", "AWS_SECRET_ACCESS_KEY": "s", "AWS_ACCESS_KEY_ID": "a", "MODAL_TOKEN_ID": "m",
                "MODAL_TOKEN_SECRET": "m", "KIT_ALLOW_MODAL": "1", "ANTHROPIC_API_KEY": "k", "SSH_AUTH_SOCK": "/s",
                "DISCORD_TOKEN": "d", "MY_PASSWORD": "p"}
        env = routines.child_env(base)
        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["HTTPS_PROXY"], "http://proxy:3128")
        self.assertEqual(env["SCROLLS_ROUTINE"], "1")
        for k in base:
            if k not in ("PATH", "HTTPS_PROXY"):
                self.assertNotIn(k, env)

    def test_a_routine_cannot_see_a_token(self):
        r = fake("env", "import os; print(os.environ.get('GITHUB_TOKEN'), os.environ.get('KIT_ALLOW_MODAL'))")
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "secret", "KIT_ALLOW_MODAL": "1"}):
            result = routines.run_one(r, ROOT, NOW)
        self.assertEqual(result["output"].strip(), "None None")


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "work" / "routines"
        self.lines = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_all(self, selected, **kw):
        return routines.run_routines(selected, ROOT, self.state, now=NOW, log=self.lines.append, **kw)

    def test_results_state_and_summary(self):
        selected = [fake("good", "print('fine')"), fake("look", "print('new volume'); raise SystemExit(3)"),
                    fake("bad", "print('broken'); raise SystemExit(1)"),
                    fake("slow", "import time; time.sleep(30)", timeout=1),
                    fake("later", "print(1)", requires=["kit/not_here_yet.py"]),
                    fake("offline", "print('<urlopen error [Errno -2] Name or service not known>'); "
                                    "raise SystemExit(2)")]
        results = self.run_all(selected)
        self.assertEqual({k: v["status"] for k, v in results.items()},
                         {"good": "ok", "look": "attention", "bad": "fail", "slow": "timeout", "later": "skipped",
                          "offline": "skipped"})
        self.assertIn("not here yet", results["later"]["note"])
        state = json.loads((self.state / "state.json").read_text())
        good = state["routines"]["good"]
        self.assertEqual(good["last"]["started"], "2026-10-16T10:00:00Z")
        self.assertEqual(good["last_completed"], "2026-10-16")
        self.assertEqual(good["last"]["output"], "fine")
        self.assertNotIn("last_completed", state["routines"]["later"])
        self.assertEqual(state["routines"]["slow"]["last_completed"], "2026-10-16")
        summary = (self.state / "summary.md").read_text()
        self.assertIn("| look | daily | 2026-10-16T10:00:00Z | attention |", summary)
        self.assertIn("## Needs a look", summary)
        self.assertIn("broken", summary)
        self.assertNotIn("### good", summary)
        self.assertFalse((self.state / "run.lock").exists())
        # Within the hour nothing is due; next UTC day the completed ones are due again, and the skipped ones
        # already after an hour.
        self.assertEqual(routines.due(selected, routines.load_state(self.state), NOW + timedelta(minutes=30)), [])
        later = [r["name"] for r in routines.due(selected, routines.load_state(self.state), NOW + timedelta(hours=2))]
        self.assertEqual(later, ["later", "offline"])
        tomorrow = routines.due(selected, routines.load_state(self.state), NOW + timedelta(days=1))
        self.assertEqual(len(tomorrow), len(selected))

    def test_lock_held_runs_nothing(self):
        self.assertTrue(routines.acquire_lock(self.state, 600))
        self.assertFalse(routines.acquire_lock(self.state, 600))
        self.assertIsNone(self.run_all([fake("good", "print(1)")]))
        self.assertIn("another run", self.lines[-1])
        self.assertFalse((self.state / "state.json").exists())
        routines.release_lock(self.state)
        self.assertIsNotNone(self.run_all([fake("good", "print(1)")]))

    def test_stale_or_dead_lock_is_taken_over(self):
        self.state.mkdir(parents=True)
        (self.state / "run.lock").write_text(json.dumps({"pid": os.getpid(), "t": time.time() - 10_000}))
        self.assertTrue(routines.acquire_lock(self.state, 600))
        routines.release_lock(self.state)
        (self.state / "run.lock").write_text("not json")
        self.assertTrue(routines.acquire_lock(self.state, 600))

    def test_budget_leaves_the_rest_due(self):
        ticks = iter([0, 0, 100, 100, 100])
        results = self.run_all([fake("a", "print(1)"), fake("b", "print(2)")], budget=50,
                               clock=lambda: next(ticks))
        self.assertEqual(list(results), ["a"])
        self.assertIn("left for next time", self.lines[-1])

    def test_damaged_state_file_starts_over(self):
        self.state.mkdir(parents=True)
        (self.state / "state.json").write_text("{broken")
        self.assertEqual(routines.load_state(self.state), {"version": 1, "routines": {}})
        self.run_all([fake("a", "print(1)")])
        self.assertIn("a", routines.load_state(self.state)["routines"])

    def test_history_keeps_ten(self):
        state = {"version": 1, "routines": {}}
        for i in range(12):
            routines.record(state, fake("a"), {"status": "ok", "started": f"2026-10-{i + 1:02d}T00:00:00Z"})
        self.assertEqual(len(state["routines"]["a"]["history"]), 10)

    def test_status_views(self):
        selected = [fake("good", "print('fine')"), fake("look", "print('one new scan'); raise SystemExit(3)"),
                    fake("never", "print(1)")]
        self.run_all(selected[:2])
        state = routines.load_state(self.state)
        brief = routines.status_text(selected, state, NOW, brief=True)
        self.assertIn("1 of 3 need a look", brief)
        self.assertIn("never run here: never", brief)
        self.assertIn("look: attention at 2026-10-16T10:00:00Z. one new scan", brief)
        full = routines.status_text(selected, state, NOW)
        self.assertIn("--- look (attention) ---", full)


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.registry = self.dir / "routines.json"
        self.registry.write_text(json.dumps({"routines": [
            {"name": "prizes", "cadence": "daily", "timeout_s": 60, "command": ["{python}", "-m", "kit", "prizes"],
             "why": "test", "ci": True},
            {"name": "later", "cadence": "weekly", "timeout_s": 60, "command": ["{python}", "-m", "kit", "prizes"],
             "why": "test", "requires": ["kit/not_here_yet.py"]}]}))
        self.state = self.dir / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def kit(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = routines.main(["--registry", str(self.registry), "--state", str(self.state), *argv])
        return code, buf.getvalue()

    def test_due_run_status(self):
        code, out = self.kit("due", "--json")
        self.assertEqual((code, json.loads(out)), (0, ["prizes", "later"]))
        code, out = self.kit("run", "--due")
        self.assertEqual(code, 0, out)
        code, out = self.kit("due")
        self.assertEqual(out.strip(), "nothing is due")
        code, out = self.kit("status", "--json")
        self.assertEqual({r["name"]: r["status"] for r in json.loads(out)}, {"prizes": "ok", "later": "skipped"})
        code, out = self.kit("run", "--due")
        self.assertIn("nothing is due", out)

    def test_run_by_name_and_ci(self):
        self.assertEqual(self.kit("run", "--name", "later")[0], 0)
        self.assertEqual(json.loads((self.state / "state.json").read_text())["routines"]["later"]["last"]["status"],
                         "skipped")
        code, out = self.kit("run", "--ci", "--strict")
        self.assertEqual(code, 0, out)
        self.assertIn("running 1: prizes", out)
        self.assertEqual(self.kit("run", "--name", "nope")[0], 2)

    def test_fail_and_strict_exit_codes(self):
        fail = {"status": "fail"}
        attention = {"status": "attention"}
        for results, strict, want in (([fail], False, 1), ([attention], False, 0), ([attention], True, 1)):
            with mock.patch.object(routines, "run_routines", return_value={"a": results[0]}):
                args = ["run", "--name", "prizes"] + (["--strict"] if strict else [])
                self.assertEqual(self.kit(*args)[0], want)

    def test_background_returns_at_once_and_finishes_later(self):
        t0 = time.monotonic()
        code, out = self.kit("run", "--due", "--background")
        self.assertEqual(code, 0)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertIn("started in the background: prizes, later", out)
        for _ in range(300):
            if (self.state / "summary.md").exists() and not (self.state / "run.lock").exists():
                break
            time.sleep(0.1)
        state = json.loads((self.state / "state.json").read_text())
        self.assertEqual(state["routines"]["prizes"]["last"]["status"], "ok")
        self.assertIn("run --due", (self.state / "last-run.log").read_text())
        code, out = self.kit("run", "--due", "--background")
        self.assertNotIn("started", out)

    def test_spawn_detaches(self):
        seen = {}

        def popen(argv, **kw):
            seen.update(kw, argv=argv)

        args = types.SimpleNamespace(state=str(self.state), registry=str(self.registry), due=True, ci=False, name=[],
                                     budget=None)
        routines.spawn_background(args, popen=popen)
        self.assertEqual(seen["argv"][1:5], ["-m", "kit", "routines", "--registry"])
        self.assertEqual(seen["argv"][-2:], ["run", "--due"])
        self.assertIs(seen["stdin"], subprocess.DEVNULL)
        if os.name == "posix":
            self.assertTrue(seen["start_new_session"])

    def test_kit_cli_has_routines(self):
        from kit import cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["routines", "--registry", str(self.registry), "--state", str(self.state), "list"])
        self.assertEqual(code, 0)
        self.assertIn("prizes", buf.getvalue())


class HandoffCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "tests").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "tests" / "test_repo.py").write_text(
            'for rel, limit in {"AGENTS.md": 1_000, "docs/HANDOFF.md": 2_000}.items():\n    pass\n')

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, agents, handoff, when=NOW - timedelta(hours=5), dirty=False):
        (self.root / "AGENTS.md").write_bytes(b"a" * agents)
        (self.root / "docs" / "HANDOFF.md").write_bytes(b"h" * handoff)
        return routines.check_handoff(self.root, 3, 0.9, NOW, last_change=lambda root, rel: (when, dirty))

    def test_ok(self):
        code, lines = self.check(100, 100)
        self.assertEqual(code, 0, lines)

    def test_near_the_limit_needs_a_look(self):
        code, lines = self.check(950, 100)
        self.assertEqual(code, 3)
        self.assertIn("only 50 left", lines[-1])

    def test_over_the_limit_fails(self):
        code, lines = self.check(100, 2001, when=NOW - timedelta(days=9))
        self.assertEqual(code, 1)
        self.assertTrue(any("over its 2000-byte limit" in line for line in lines))

    def test_old_handoff_needs_a_look_unless_being_edited(self):
        self.assertEqual(self.check(100, 100, when=NOW - timedelta(days=4))[0], 3)
        self.assertEqual(self.check(100, 100, when=NOW - timedelta(days=4), dirty=True)[0], 0)

    def test_limits_not_found_needs_a_look(self):
        (self.root / "tests" / "test_repo.py").write_text("nothing here\n")
        self.assertEqual(self.check(100, 100)[0], 3)

    def test_repo_limits_parse(self):
        limits = routines.size_limits(ROOT)
        self.assertIn("AGENTS.md", limits)
        self.assertIn("docs/HANDOFF.md", limits)


class EntryPointsTest(unittest.TestCase):
    def test_claude_code_session_start_hook(self):
        settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        hooks = [h for group in settings["hooks"]["SessionStart"] for h in group["hooks"]]
        ours = [h for h in hooks if "kit routines run --due --background" in h["command"]]
        self.assertEqual(len(ours), 1)
        self.assertTrue(ours[0]["command"].rstrip().endswith("exit 0"), "the hook must never fail the session")
        self.assertLessEqual(ours[0]["timeout"], 30)

    def test_rulebook_tells_every_agent(self):
        text = (ROOT / "docs" / "AI-AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("python3 -m kit routines run --due", text)
        self.assertIn("python3 -m kit routines status", text)

    def test_state_folder_is_ignored(self):
        r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "work/routines/state.json"])
        if r.returncode == 128:
            self.skipTest("not a git checkout")
        self.assertEqual(r.returncode, 0, "work/routines/ must be git-ignored")


if __name__ == "__main__":
    unittest.main()
