"""kit/freezeguard.py: recording_argv and recording_check (Python children that record the files they loaded, their
flags, exit codes and a missing record kept), guard_record and guard_void (a refusal recorded, not raised), and
import_closure (imports inside functions, folder discovery, top_only dispatchers and the functions in always, and kit's
own cli closure checked against what `python -m kit freeze --help` really loads)."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kit import freeze, freezeguard

ROOT = Path(__file__).resolve().parent.parent


class FreezeGuardTest(unittest.TestCase):
    def test_recording_argv_records_what_python_children_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            (root / "pkg").mkdir(parents=True)
            (root / "pkg" / "__init__.py").write_text("")
            (root / "pkg" / "__main__.py").write_text("import sys, pkg.extra\nsys.exit(3)\n")
            (root / "pkg" / "extra.py").write_text("X = 1\n")
            (root / "tool.py").write_text("import sys\nassert sys.argv[1:] == ['a', '-m', 'x']\n"
                                          "assert sys.path[0] != __import__('os').path.dirname(__file__)\n")
            rec_m, rec_s = Path(tmp) / "m.json", Path(tmp) / "s.json"
            env = dict(os.environ, PYTHONPATH=str(root))
            argv = freezeguard.recording_argv([sys.executable, "-m", "pkg", "b"], rec_m)
            self.assertEqual(argv[:2], [sys.executable, "-c"])
            self.assertEqual(argv[3:6], [str(rec_m), "m", "pkg"])
            got = subprocess.run(argv, cwd=root, env=env)
            self.assertEqual(got.returncode, 3)                 # its exit code is kept, and the record still written
            argv = freezeguard.recording_argv([sys.executable, "-I", str(root / "tool.py"), "a", "-m", "x"], rec_s)
            self.assertEqual(argv[1:3], ["-I", "-c"])          # the child's flags are kept
            self.assertEqual(subprocess.run(argv, cwd=root, env=env).returncode, 0)
            listed = ["pkg/__init__.py", "pkg/__main__.py", "pkg/extra.py", "tool.py"]
            rep = freezeguard.recording_check(listed, root, [rec_m, rec_s, Path(tmp) / "lost.json"])
            self.assertEqual((rep["records"], rep["written"], rep["files"]), (3, 2, 4))
            self.assertEqual(rep["missing"], [str(Path(tmp) / "lost.json")])
            with self.assertRaises(freeze.FreezeRefused) as cm:
                freezeguard.recording_check(["pkg/__init__.py", "tool.py"], root, [rec_m, rec_s])
            self.assertIn("pkg/__main__.py, pkg/extra.py", str(cm.exception))
        for argv in (["vc_grow_seg_from_seed", "-x"], [sys.executable, "-c", "print(1)"], ["bash", "a.py"],
                     [sys.executable], [sys.executable, "-m"]):
            self.assertIsNone(freezeguard.recording_argv(argv, "r.json"), argv)

    def test_import_closure_reads_imports_inside_functions_and_folder_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            (root / "tools").mkdir()
            (root / "pkg" / "__init__.py").write_text("")
            (root / "pkg" / "cli.py").write_text("from . import a\n"
                                                 "def main():\n    import pkg.never\n")
            (root / "pkg" / "a.py").write_text("def f():\n    from .b import g\n    return g\n")
            (root / "pkg" / "b.py").write_text("import importlib\ng = importlib.import_module('pkg.c')\n")
            (root / "pkg" / "c.py").write_text("__import__('json')\n")
            (root / "pkg" / "never.py").write_text("")
            (root / "pkg" / "a_ext_one.py").write_text("from . import d\n")
            (root / "pkg" / "d.py").write_text("")
            (root / "tools" / "run.py").write_text("import helper\n")
            (root / "tools" / "helper.py").write_text("")
            got = freezeguard.import_closure(root, ["pkg/cli.py", "tools/run.py"], top_only=("pkg/cli.py",),
                                        search=("", "tools"), discover=(("pkg/a.py", "pkg/a_ext_*.py"),))
            self.assertEqual(got, ["pkg/__init__.py", "pkg/a.py", "pkg/a_ext_one.py", "pkg/b.py", "pkg/c.py",
                                   "pkg/cli.py", "pkg/d.py", "tools/helper.py", "tools/run.py"])
            self.assertIn("pkg/never.py", freezeguard.import_closure(root, ["pkg/cli.py"]))   # not top_only: followed

    def test_import_closure_follows_what_a_dispatcher_runs_on_every_use(self):
        # kit/cli.py's build_parser builds the whole parser on each `python -m kit` and imports a few subcommands'
        # modules to do it; its lambdas (the named subcommand's function) and nested functions run only when called
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            for name in ("__init__", "top", "guarded", "inparser", "rel", "lazy", "nested", "klass", "method", "cmd",
                         "deep"):
                (root / "pkg" / f"{name}.py").write_text("")
            (root / "pkg" / "rel.py").write_text("import pkg.deep\n")
            (root / "pkg" / "cli.py").write_text(
                "import pkg.top\n"
                "try:\n    import pkg.guarded\nexcept ImportError:\n    pass\n"
                "class P:\n    def go(self):\n        import pkg.method\n"
                "def cmd_x(args):\n    import pkg.cmd\n"
                "def build_parser(lazy=False):\n"
                "    __import__('pkg.inparser', fromlist=['x']).build(1)\n"
                "    from . import rel\n"
                "    f = lambda a: __import__('pkg.lazy', fromlist=['x']).run(a)\n"
                "    def later():\n        import pkg.nested\n"
                "    class Q:\n        import pkg.klass\n"
                "    return f\n")
            top = freezeguard.import_closure(root, ["pkg/cli.py"], top_only=("pkg/cli.py",))
            self.assertEqual(top, ["pkg/__init__.py", "pkg/cli.py", "pkg/guarded.py", "pkg/top.py"])
            got = freezeguard.import_closure(root, ["pkg/cli.py"], top_only=("pkg/cli.py",),
                                        always=(("pkg/cli.py", "build_parser"),))
            self.assertEqual(got, ["pkg/__init__.py", "pkg/cli.py", "pkg/deep.py", "pkg/guarded.py",
                                   "pkg/inparser.py", "pkg/klass.py", "pkg/rel.py", "pkg/top.py"])
            # always names only a top_only file's functions; a function it cannot find is an error, not a skip
            self.assertEqual(freezeguard.import_closure(root, ["pkg/cli.py"], always=(("pkg/cli.py", "build_parser"),)),
                             freezeguard.import_closure(root, ["pkg/cli.py"]))
            with self.assertRaises(freeze.FreezeError):
                freezeguard.import_closure(root, ["pkg/cli.py"], top_only=("pkg/cli.py",),
                                      always=(("pkg/cli.py", "build_parse"),))

    def test_import_closure_of_kit_cli_holds_its_parser_time_imports(self):
        # what `python -m kit freeze --help` really loads from kit/ is inside the closure of kit/__main__.py and
        # kit/cli.py with build_parser followed
        got = set(freezeguard.import_closure(ROOT, ["kit/__main__.py", "kit/cli.py"], top_only=("kit/cli.py",),
                                             discover=(("kit/stagereg.py", "kit/stagereg_ext_*.py"),),
                                             always=(("kit/cli.py", "build_parser"),)))
        for need in ("kit/freeze.py", "kit/preregsets.py", "kit/releases.py"):
            self.assertIn(need, got)
        self.assertNotIn("kit/strokenet.py", got)              # a lambda's module: only when its subcommand is named
        with tempfile.TemporaryDirectory() as tmp:
            rec = Path(tmp) / "r.json"
            argv = freezeguard.recording_argv([sys.executable, "-m", "kit", "freeze", "--help"], rec)
            subprocess.run(argv, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True,
                           timeout=300)
            self.assertEqual(freezeguard.recording_check(sorted(got), ROOT, [rec])["written"], 1)

    def test_guard_record_records_a_refusal_and_guard_void_reads_it_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            (root / "pkg" / "__init__.py").write_text("")
            (root / "pkg" / "extra.py").write_text("")
            rec = Path(tmp) / "child.json"
            rec.write_text('["%s"]' % (root / "pkg" / "extra.py").as_posix())
            ok = freezeguard.guard_record(["pkg/__init__.py", "pkg/extra.py"], root, "after", records=[rec])
            self.assertNotIn("refused", ok)
            self.assertEqual((ok["listed"], ok["children"]["written"]), (2, 1))
            bad = freezeguard.guard_record(["pkg/__init__.py"], root, "after", records=[rec])
            self.assertIn("pkg/extra.py", bad["refused"])
            why = freezeguard.guard_void({"refused": [{"when": "earlier", "refused": "x.py"}]}, [ok, bad, "junk"])
            self.assertEqual(len(why), 2)
            self.assertTrue(why[0].startswith("the executed-files guard refused earlier: x.py"))
            self.assertIn("refused after", why[1])
            self.assertEqual(freezeguard.guard_void(None), [])

    def test_this_module_imports_only_freeze_from_the_repository(self):
        loaded = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                                 "import kit.freezeguard; print(sorted(m for m in sys.modules if m.startswith('kit')))",
                                 str(ROOT)], capture_output=True, text=True, check=True).stdout
        self.assertEqual(eval(loaded), ["kit", "kit.freeze", "kit.freezeguard", "kit.preregsets"])


if __name__ == "__main__":
    unittest.main()
