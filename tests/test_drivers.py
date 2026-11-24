import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from kit import drivers as D

PY = sys.executable


class _Pgid:
    """A process group started by a CLI child, so tearDown can kill it like a Popen."""

    def __init__(self, pid):
        self.pid = pid

    def wait(self):
        pass


class DriversTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "drivers"
        self.env = mock.patch.dict(os.environ, {})
        self.env.start()
        os.environ.pop("KIT_FREEZE", None)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait()
        self.env.stop()
        self.tmp.cleanup()

    def start(self, did, cmd, mode="restartable", **kw):
        d, p = D.start(did, cmd, mode, where=self.dir, cwd=self.tmp.name, **kw)
        self.procs.append(p)
        return d, p

    def wait_state(self, did, states, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            row = D.drivers(self.dir, [did])[0]
            if row["state"] in states:
                return row
            time.sleep(0.1)
        self.fail(f"{did} never reached {states}: {D.drivers(self.dir, [did])[0]}")

    def test_finish_records_exit_and_own_run_dir(self):
        d, p = self.start("t1", [PY, "-c", "import os,sys; open(os.path.join(os.environ['KIT_RUN_DIR'], 'x'), 'w')"
                                           ".write(os.environ['TMPDIR'] + ' ' + os.environ['KIT_DRIVER_ATTEMPT']);"
                                           " sys.exit(4)"])
        row = self.wait_state("t1", {D.FINISHED})
        self.assertEqual(row["exit"], 4)
        self.assertEqual((d / "run" / "x").read_text(), f"{d / 'run' / 'tmp'} 1")
        rec = json.loads((d / "attempt-01.json").read_text())
        self.assertEqual(rec["boot_id"], D.boot_id())
        self.assertIn("pid", rec["child"])
        self.assertIn("exit 4", (d / "attempt-01.log").read_text())

    def test_two_drivers_never_share_a_work_folder(self):
        d1, _ = self.start("a", [PY, "-c", "pass"])
        d2, _ = self.start("b", [PY, "-c", "pass"])
        self.assertNotEqual(d1 / "run", d2 / "run")
        with self.assertRaises(D.DriverError):
            self.start("a", [PY, "-c", "pass"])            # an id starts once; a lost one is revived instead

    def test_stop(self):
        self.start("s", [PY, "-c", "import time; time.sleep(60)"])
        self.wait_state("s", {D.RUNNING})
        row = D.stop("s", self.dir, grace=5)
        self.assertEqual(row["state"], D.STOPPED)

    def test_lost_then_revived_up_to_max_attempts(self):
        d, p = self.start("l", [PY, "-c", "import time; time.sleep(60)"], max_attempts=2)
        self.wait_state("l", {D.RUNNING})
        os.killpg(p.pid, signal.SIGKILL)                   # what a container restart does to the whole tree
        p.wait()
        row = self.wait_state("l", {D.LOST})
        self.assertIn("no exit record", row["reason"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(D.EXIT_LOST,
                             D.run(D.add_arguments(__import__("argparse").ArgumentParser()).parse_args(
                                 ["--dir", str(self.dir), "status"])))
        out = []
        revived, refused = D.revive(where=self.dir, say=out.append)
        self.assertEqual((revived, refused), (["l"], []))
        self.assertIn("lost:", json.loads((d / "attempt-01.json").read_text())["ended"])
        row = self.wait_state("l", {D.RUNNING})
        self.assertEqual(row["attempts"], 2)
        rec = json.loads((d / "attempt-02.json").read_text())
        os.killpg(os.getpgid(rec["supervisor"]["pid"]), signal.SIGKILL)
        self.wait_state("l", {D.LOST})
        revived, refused = D.revive(where=self.dir, say=out.append)
        self.assertEqual((revived, refused), ([], ["l"]))
        self.assertIn("all 2 attempts", out[-1])

    def test_boot_id_change_is_lost_even_with_a_live_pid(self):
        spec = {"mode": "restartable"}
        me = {"pid": os.getpid(), "start": D.proc_start(os.getpid())}
        rec = {"attempt": 1, "host": "vm", "boot_id": "linux-old", "supervisor": me}
        state, why = D.judge(spec, [rec], here={"host": "vm", "boot_id": "linux-new"})
        self.assertEqual(state, D.LOST)
        self.assertIn("restarted", why)
        state, _ = D.judge(spec, [dict(rec, boot_id="linux-new")], here={"host": "vm", "boot_id": "linux-new"})
        self.assertEqual(state, D.RUNNING)

    def test_reused_pid_is_not_running(self):
        rec = {"attempt": 1, "host": "vm", "boot_id": "b", "requested": "2000-01-01T00:00:00Z",
               "supervisor": {"pid": os.getpid(), "start": "not-this-process"}}
        state, _ = D.judge({}, [rec], here={"host": "vm", "boot_id": "b"})
        self.assertEqual(state, D.LOST)

    def test_starting_grace(self):
        rec = {"attempt": 1, "host": "vm", "boot_id": "b", "requested": D._now()}
        self.assertEqual(D.judge({}, [rec], here={"host": "vm", "boot_id": "b"})[0], D.STARTING)
        self.assertEqual(D.judge({}, [rec], here={"host": "vm", "boot_id": "b"}, now=time.time() + 60)[0], D.LOST)

    def test_a_single_driver_is_never_revived_and_a_finished_one_is_left_alone(self):
        d, p = self.start("o", [PY, "-c", "import time; time.sleep(60)"], mode="single")
        self.start("fin", [PY, "-c", "import sys; sys.exit(4)"])
        self.wait_state("o", {D.RUNNING})
        self.wait_state("fin", {D.FINISHED})
        self.assertEqual(json.loads((d / D.SPEC).read_text())["max_attempts"], 1)
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        self.wait_state("o", {D.LOST})
        out = []
        self.assertEqual(D.revive(where=self.dir, say=out.append), ([], ["o"]))
        self.assertIn("without --restartable", out[0])
        self.assertEqual(D.revive(["fin"], where=self.dir, say=out.append), ([], ["fin"]))
        self.assertIn("finished, not lost", out[-1])
        self.assertEqual(D.drivers(self.dir, ["fin"])[0]["attempts"], 1)

    def test_frozen_command_cannot_be_restartable(self):
        for cmd in ([PY, "run.py", "--frozen", "toy-eval-f1"], [PY, "run.py", "--freeze=toy-eval-f1"],
                    [PY, "run.py", "--prereg", "prereg/x.md"], ["docker", "run", "-e", "KIT_FREEZE=toy-eval-f1", "img"],
                    ["KIT_FREEZE=toy-eval-f1", PY, "run.py"]):
            with self.assertRaises(D.DriverError) as c:
                D.start("f", cmd, "restartable", where=self.dir)
            self.assertIn("without --restartable", str(c.exception))
        self.assertFalse((self.dir / "f").exists())
        self.assertIsNone(D.frozen([PY, "run.py", "--freeze", "notes.md"], env={}))   # a file path, not an id
        self.assertEqual(D.frozen([PY, "run.py"], env={"KIT_FREEZE": "f1"}), "f1")
        with mock.patch.dict(os.environ, {"KIT_FREEZE": "f1"}):
            with self.assertRaises(D.DriverError):
                D.start("g", [PY, "run.py"], "restartable", where=self.dir)

    def test_cli_status_after_a_boot_id_change_and_in_a_fresh_process_table(self):
        """The outside check of 20 Nov 2026 from the command line: lost after a boot id change, and from a new pid
        namespace (skipped where unshare is not allowed); revive then starts attempt 2 of the restartable one."""
        root = Path(__file__).resolve().parent.parent
        env = dict(os.environ, KIT_DRIVERS_DIR=str(self.dir), PYTHONPATH=str(root))

        def cli(args, boot=None, pre=()):
            code = ("import sys, kit.drivers as D\n"
                    + (f"D.boot_id = lambda: {boot!r}\n" if boot else "")
                    + "sys.exit(D.main(sys.argv[1:]))")
            p = subprocess.run([*pre, PY, "-c", code, *args], env=env, capture_output=True, text=True, timeout=60)
            return p.returncode, p.stdout

        long = ["sh", "-c", 'echo "$KIT_DRIVER_ATTEMPT" >> "$KIT_RUN_DIR/attempts"; exec sleep 60']
        self.assertEqual(cli(["start", "kill", "--restartable", "--", *long])[0], 0)
        self.assertEqual(cli(["start", "one", "--", "sleep", "60"])[0], 0)
        self.wait_state("kill", {D.RUNNING})
        self.wait_state("one", {D.RUNNING})
        for did in ("kill", "one"):
            self.procs.append(_Pgid(json.loads((self.dir / did / "attempt-01.json").read_text())["supervisor"]["pid"]))
        self.assertEqual(cli(["status"])[0], 0)
        rc, out = cli(["status", "--json"], boot="linux-new-boot")
        rows = {r["id"]: r for r in json.loads(out)}
        self.assertEqual(rc, D.EXIT_LOST)
        self.assertTrue(all(rows[i]["state"] == D.LOST and "boot id changed" in rows[i]["reason"]
                            for i in ("kill", "one")))
        rc, out = cli(["status", "--hook"], boot="linux-new-boot")
        self.assertEqual((rc, len(out.splitlines())), (0, 4))
        if subprocess.run(["unshare", "--pid", "--fork", "--mount-proc", "true"], capture_output=True).returncode == 0:
            rc, out = cli(["status", "--json"], pre=["unshare", "--pid", "--fork", "--mount-proc"])
            self.assertEqual(rc, D.EXIT_LOST)
            self.assertEqual({r["state"] for r in json.loads(out)}, {D.LOST})
        for did in ("kill", "one"):
            os.killpg(json.loads((self.dir / did / "attempt-01.json").read_text())["supervisor"]["pid"],
                      signal.SIGKILL)
        self.wait_state("kill", {D.LOST})
        rc, out = cli(["revive"])
        self.assertEqual(rc, D.EXIT_PROBLEM)                 # the single driver was refused
        self.assertIn("one: not revived", out)
        self.wait_state("kill", {D.RUNNING})
        self.procs.append(_Pgid(json.loads((self.dir / "kill" / "attempt-02.json").read_text())["supervisor"]["pid"]))
        end = time.time() + 20
        while time.time() < end and (self.dir / "kill" / "run" / "attempts").read_text() != "1\n2\n":
            time.sleep(0.1)
        self.assertEqual((self.dir / "kill" / "run" / "attempts").read_text(), "1\n2\n")

    def test_hook_prints_only_lost(self):
        rows = [{"id": "a", "state": D.RUNNING}, {"id": "b", "state": D.LOST, "mode": "restartable", "attempts": 1,
                                                  "max_attempts": 3, "reason": "the machine restarted"}]
        lines = D.hook_lines(rows)
        self.assertEqual(len(lines), 3)
        self.assertIn("b (restartable", lines[1])
        self.assertEqual(D.hook_lines(rows[:1]), [])

    def test_ids_and_command_line(self):
        for bad in ("", "-x", "a b", "../x", None):
            with self.assertRaises(D.DriverError):
                D.check_id(bad)
        p = D.add_arguments(__import__("argparse").ArgumentParser())
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(D.run(p.parse_args(["--dir", str(self.dir), "status", "--hook"])), 0)
            self.assertEqual(D.run(p.parse_args(["--dir", str(self.dir), "whereami", "--json"])), 0)
        self.assertIn("boot_id", out.getvalue())
        a = p.parse_args(["--dir", str(self.dir), "start", "c", "--restartable", "--max-attempts", "2", "--",
                          PY, "-c", "pass", "--restartable"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(D.run(a), 0)
        spec = json.loads((self.dir / "c" / D.SPEC).read_text())
        self.assertEqual((spec["mode"], spec["max_attempts"], spec["command"][-1]), ("restartable", 2, "--restartable"))
        self.wait_state("c", {D.FINISHED})


if __name__ == "__main__":
    unittest.main()
