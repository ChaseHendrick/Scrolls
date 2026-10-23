"""Tests for kit.termstyle (the shared terminal look) and kit.termview (the mouse viewer's pure parts)."""
import io
import os
import select
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from kit import termstyle as ts
from kit import termview as tv

ROOT = Path(__file__).resolve().parent.parent


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


class ClassifyTest(unittest.TestCase):
    def test_segments_join_back_exactly(self):
        for ln in ts.demo() + ["", "   ", "plain words", "\x1b[31mred\x1b[0m", "50%\r", "a | b", "x: y: z"]:
            self.assertEqual("".join(t for t, _ in ts.classify(ln)), ln, ln)

    def test_roles(self):
        roles = lambda ln: {r for _, r in ts.classify(ln)}  # noqa: E731
        self.assertIn("head", roles("## Results"))
        self.assertEqual(roles("Summary:"), {"section"})
        self.assertEqual(roles("-----"), {"rule"})
        self.assertTrue({"key", "ok"} <= roles("  verdict: PASS"))
        self.assertIn("bad", roles("3 tests FAILED"))
        self.assertIn("warn", roles("WARNING: stale file"))
        self.assertIn("money", roles("cost 0.72 USD"))
        self.assertIn("link", roles("see https://scrollprize.org/prizes now"))
        self.assertEqual(roles("\x1b[1mbold already\x1b[0m"), {"plain"})

    def test_status_words_need_boundaries(self):
        self.assertNotIn("ok", {r for _, r in ts.classify("tokens booked, smoke")})
        self.assertNotIn("bad", {r for _, r in ts.classify("terrorist")})

    def test_ansi_keeps_the_text(self):
        for ln in ts.demo():
            self.assertEqual(ts.width(ts.ANSI.sub("", ts.ansi(ln, links=False))) >= 1, True)
        self.assertIn("\x1b]8;;https://x.y/z", ts.ansi("go https://x.y/z"))


class WrapTest(unittest.TestCase):
    def test_soft_wrap_keeps_spacing_and_width(self):
        line = "  name     value with several words that keep going past the edge of a narrow terminal"
        parts = ts.soft_wrap(line, 30)
        self.assertTrue(parts[0].startswith("  name     value"))
        self.assertTrue(all(ts.width(p) <= 30 for p in parts))
        self.assertEqual(" ".join(p.strip() for p in parts).split(), line.split())
        self.assertTrue(all(p.startswith("    ") for p in parts[1:]))

    def test_long_word_is_split(self):
        parts = ts.soft_wrap("x" * 70, 30)
        self.assertEqual("".join(p.strip() for p in parts), "x" * 70)
        self.assertTrue(all(ts.width(p) <= 30 for p in parts))

    def test_wide_characters(self):
        self.assertEqual(ts.width("文字"), 4)
        self.assertTrue(all(ts.width(p) <= 9 for p in ts.soft_wrap("文字 文字 文字 文字 文字", 9)))


class StreamTest(unittest.TestCase):
    def test_lines_styled_partials_and_codes_passed(self):
        raw = FakeTTY()
        s = ts.StyledStream(raw, wrap_width=200)
        s.write("verdict: PASS\nhalf")
        self.assertIn("\x1b[", raw.getvalue())
        self.assertNotIn("half", raw.getvalue())
        s.flush()                                   # a prompt is written at once, unstyled
        self.assertTrue(raw.getvalue().endswith("half"))
        raw2 = FakeTTY()
        s2 = ts.StyledStream(raw2, wrap_width=200)
        s2.write("\x1b[32mgreen\x1b[0m\n 40%\r 50%\r")
        self.assertEqual(raw2.getvalue(), "\x1b[32mgreen\x1b[0m\n 40%\r 50%\r")

    def test_attributes_pass_through(self):
        raw = FakeTTY()
        self.assertTrue(ts.StyledStream(raw).isatty())

    def test_hugging_face_sync_folds_to_one_line(self):
        raw = FakeTTY()
        s = ts.StyledStream(raw, wrap_width=300)
        s.write("Scanning local directory (240 files)\nScanning remote bucket (0 files)\nComparing files (240 paths)\n"
                "Sync plan: /x/stage -> hf://buckets/o/b/jobs/r\n  Uploads: 240\n  Downloads: 0\n  Deletes: 0\n"
                "  Skips: 0\nSyncing...\nUploading 240 files\nSync completed.\nHint: use logs\n")
        text = ts.ANSI.sub("", raw.getvalue())
        self.assertEqual(text.splitlines(), ["  sync /x/stage -> hf://buckets/o/b/jobs/r: 240 uploads",
                                             "Sync completed.", "Hint: use logs"])
        raw2 = FakeTTY()
        s2 = ts.StyledStream(raw2, wrap_width=300)
        s2.write("Sync plan: a -> b\n  Uploads: 0\nverdict: PASS\n")
        self.assertEqual(ts.ANSI.sub("", raw2.getvalue()).splitlines(), ["  sync a -> b: nothing to do", "verdict: PASS"])

    def test_pipes_keep_the_sync_lines(self):
        # folding lives in the styled stream only, so logs and pipes keep every byte
        self.assertFalse(ts.wanted(["x"], [io.StringIO()]))


class SwitchTest(unittest.TestCase):
    def test_not_on_a_pipe_or_when_plain(self):
        with mock.patch.object(ts, "_STATE", {"on": False, "t0": None, "code": 0}):
            self.assertFalse(ts.wanted(["x"], [io.StringIO()]))
            with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
                self.assertFalse(ts.wanted(["x"], [FakeTTY()]))
            with mock.patch.dict(os.environ, {"NO_COLOR": "", "SCROLLS_PLAIN": "", "TERM": "xterm"}):
                self.assertTrue(ts.wanted(["x"], [FakeTTY()]))
                self.assertFalse(ts.wanted(["x", "--json"], [FakeTTY()]))
                self.assertFalse(ts.wanted(["scripts/atrium/atrium.py"], [FakeTTY()]))

    def test_auto_only_for_kit_commands(self):
        for orig, expect in ((["py", "-m", "unittest"], False), (["py", "-m", "kit", "live", "--", "x"], False),
                             (["py", "-m", "kit.auc", "x"], False),
                             (["py", "-m", "kit.termstyle", "demo"], False), (["py", "x.py"], False)):
            with mock.patch.object(sys, "orig_argv", orig, create=True), \
                    mock.patch.object(ts, "ensure_hook", return_value=False), \
                    mock.patch.object(ts, "install", return_value=True) as inst:
                self.assertEqual(ts.auto(), expect, orig)
                self.assertEqual(inst.called, expect)
        with mock.patch.object(sys, "orig_argv", ["py", "-m", "kit", "prizes"], create=True), \
                mock.patch.object(ts, "ensure_hook", return_value=False) as hook, \
                mock.patch.object(ts, "install", return_value=True) as inst:
            self.assertTrue(ts.auto())
            self.assertTrue(hook.called)                # a kit command also writes the hook for later scripts

    def test_command_title(self):
        with mock.patch.object(sys, "orig_argv", ["py", "-m", "kit", "auc", "MAP.tif"], create=True):
            self.assertEqual(ts.command_title(), "kit auc")
        with mock.patch.object(sys, "orig_argv", ["py", "s.py"], create=True):
            self.assertEqual(ts.command_title([str(ROOT / "scripts" / "soup.py"), "--x", "go"]), "scripts/soup.py go")

    def test_checkout_root(self):
        self.assertEqual(ts.checkout_root(ROOT / "scripts" / "soup.py"), ROOT)
        self.assertIsNone(ts.checkout_root("/"))


class FreezeSafetyTest(unittest.TestCase):
    def test_package_init_does_not_load_the_look(self):
        # importing kit (or kit.cli) must never load the look; only a kit command on a terminal does
        init = (ROOT / "kit" / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("termstyle", init)
        out = subprocess.run([sys.executable, "-c", "import sys, kit.cli; print('kit.termstyle' in sys.modules)"],
                             cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "False")

    def test_hook_registers_its_copy(self):
        self.assertIn('sys.modules["_scrolls_termstyle"] = style', ts.HOOK)


class HookTest(unittest.TestCase):
    def test_install_status_remove(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(ts.hook_status(d))
            ts.hook_install(d)
            self.assertTrue(ts.hook_status(d))
            self.assertEqual((Path(d) / "scrolls_termhook.pth").read_text(), "import scrolls_termhook\n")
            compile((Path(d) / "scrolls_termhook.py").read_text(), "hook", "exec")
            self.assertEqual((Path(d) / "scrolls_termhook_look.py").read_text(),
                             (ROOT / "kit" / "termstyle.py").read_text())
            self.assertEqual(sorted(ts.hook_remove(d)),
                             ["scrolls_termhook.pth", "scrolls_termhook.py", "scrolls_termhook_look.py"])
            self.assertFalse(ts.hook_status(d))

    def test_ensure_installs_once_and_never_downgrades(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"SCROLLS_NO_HOOK": ""}):
            self.assertTrue(ts.ensure_hook(d))
            self.assertFalse(ts.ensure_hook(d))
            look = Path(d) / "scrolls_termhook_look.py"
            look.write_text(f"LOOK_VERSION = {ts.LOOK_VERSION + 1}\n")
            self.assertFalse(ts.ensure_hook(d))
            self.assertIn(str(ts.LOOK_VERSION + 1), look.read_text())       # a newer copy is left alone
            look.write_text("LOOK_VERSION = 1\n")
            ts.ensure_hook(d)
            self.assertEqual(look.read_text(), (ROOT / "kit" / "termstyle.py").read_text())
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"SCROLLS_NO_HOOK": "1"}):
            self.assertFalse(ts.ensure_hook(d))
            self.assertFalse(ts.hook_status(d))

    def test_hook_leaves_a_pipe_alone(self):
        with tempfile.TemporaryDirectory() as d:
            ts.hook_install(d)
            env = dict(os.environ, PYTHONPATH=d)
            out = subprocess.run([sys.executable, "-c", "import scrolls_termhook; print('plain')"], env=env,
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout, "plain\n")


@unittest.skipUnless(os.path.exists("/dev/ptmx"), "needs a pseudo-terminal")
class TerminalTest(unittest.TestCase):
    def run_pty(self, argv, keys=(), wait=3.0, cwd=None, **extra):
        import fcntl
        import pty
        import struct
        import termios
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 90, 0, 0))
        env = dict(os.environ, TERM="xterm-256color", NO_COLOR="", SCROLLS_PLAIN="", SCROLLS_NO_HOOK="1", **extra)
        proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=cwd or ROOT,
                                close_fds=True)
        os.close(slave)
        seen = b""

        def pump(t):
            nonlocal seen
            end = time.time() + t
            while time.time() < end:
                r, _, _ = select.select([master], [], [], 0.1)
                if r:
                    try:
                        seen += os.read(master, 65536)
                    except OSError:
                        return
        try:
            pump(wait)
            for k in keys:
                os.write(master, k)
                pump(0.5)
            proc.wait(timeout=20)
        finally:
            if proc.poll() is None:
                proc.kill()
            os.close(master)
        return proc.returncode, seen

    def test_kit_command_styled_on_a_terminal(self):
        code, seen = self.run_pty([sys.executable, "-m", "kit", "style", "demo"])
        self.assertEqual(code, 0)
        self.assertIn(b"kit.termstyle demo", seen)
        self.assertIn(b"\x1b[", seen)
        self.assertIn("done".encode(), seen)

    def test_kit_command_plain_on_a_pipe(self):
        out = subprocess.run([sys.executable, "-m", "kit", "prizes"], cwd=ROOT, capture_output=True, timeout=60)
        self.assertNotIn(b"\x1b[", out.stdout)
        self.assertNotIn("◆ SCROLLS".encode(), out.stdout)

    def test_script_call_styles_and_children_join(self):
        with tempfile.TemporaryDirectory() as d:
            s = Path(d) / "s.py"
            s.write_text("import sys\nsys.path.insert(0, %r)\nfrom kit import termstyle\ntermstyle.script()\n"
                         "print('verdict: PASS')\nsys.exit(termstyle.run([sys.executable, '-c', "
                         "'print(\\'Sync plan: a -> b\\'); print(\\'  Uploads: 3\\'); import sys; sys.exit(4)']))\n"
                         % str(ROOT))
            code, seen = self.run_pty([sys.executable, str(s)])
        self.assertEqual(code, 4)
        plain = ts.ANSI.sub("", seen.decode("utf-8", "replace")).replace("\r", "")
        self.assertIn("◆ SCROLLS", plain)
        self.assertIn("sync a -> b: 3 uploads", plain)
        self.assertIn("exit 4", plain)

    def test_hook_styles_a_branch_older_than_the_look(self):
        # a fresh Python environment with the hook, and a checkout that has no kit/termstyle.py at all
        import venv
        with tempfile.TemporaryDirectory() as d:
            env_dir, repo = Path(d) / "venv", Path(d) / "old"
            venv.create(env_dir, with_pip=False)
            py = env_dir / "bin" / "python"
            site = subprocess.run([str(py), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                                  capture_output=True, text=True, timeout=60).stdout.strip()
            with mock.patch.dict(os.environ, {"SCROLLS_NO_HOOK": ""}):
                self.assertTrue(ts.ensure_hook(site))
            (repo / "kit").mkdir(parents=True)
            (repo / "kit" / "cli.py").write_text("")
            (repo / "AGENTS.md").write_text("")
            (repo / "scripts").mkdir()
            (repo / "scripts" / "go.py").write_text("print('status: PASS')\n")
            code, seen = self.run_pty([str(py), str(repo / "scripts" / "go.py")], cwd=repo)
            out = subprocess.run([str(py), str(repo / "scripts" / "go.py")], capture_output=True, timeout=60)
        self.assertEqual(code, 0)
        self.assertIn("◆ SCROLLS".encode(), ts.ANSI.sub("", seen.decode()).encode())
        self.assertIn(b"scripts/go.py", seen)
        self.assertEqual(out.stdout, b"status: PASS\n")                 # a pipe still gets the plain bytes

    def test_live_viewer_runs_and_quits(self):
        code, seen = self.run_pty([sys.executable, "-m", "kit", "live", "--", sys.executable, "-c",
                                   "print('verdict: PASS'); print('https://x.y/z')"], keys=(b"/", b"PASS", b"\r", b"q"))
        self.assertEqual(code, 0)
        self.assertIn(b"verdict", seen)
        self.assertIn(b"PASS", seen)


class ViewerTest(unittest.TestCase):
    def test_visual_lines_and_find(self):
        vis = tv.visual_lines(["alpha", "\x1b[31mbeta\x1b[0m gamma " * 6, "delta"], 20)
        self.assertEqual(vis[0], (0, "alpha"))
        self.assertTrue(all(ts.width(t) <= 20 for _, t in vis))
        self.assertNotIn("\x1b", "".join(t for _, t in vis))
        self.assertEqual(vis[tv.find(vis, "DELTA", 0)][0], 2)
        self.assertIsNone(tv.find(vis, "zeta", 0))
        self.assertEqual(tv.find(vis, "alpha", 3), 0)          # wraps round

    def test_source_collects_and_exits(self):
        src = tv.Source(argv=[sys.executable, "-c", "print('a'); print('b'); raise SystemExit(4)"])
        src.start()
        for _ in range(100):
            if src.code is not None:
                break
            time.sleep(0.05)
        self.assertEqual(src.lines, ["a", "b"])
        self.assertEqual(src.state, "exit 4")


if __name__ == "__main__":
    unittest.main()
