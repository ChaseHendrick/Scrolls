"""What a user gets from pip install: pyproject.toml, its console scripts, its data files, and line endings."""

import contextlib
import fnmatch
import io
import json
import re
import unittest
from pathlib import Path

from kit import cli, prizes

try:
    import tomllib
except ImportError:  # Python 3.10
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
AUTOPIPELINE = {"name": "vc-autopipeline", "scripts": {"scrolls-kit"}}   # its pyproject on every release branch so far


def req_name(requirement):
    """The distribution name of a requirement string such as "zarr>=3; python_version >= '3.11'"."""
    return re.split(r"[\s;<>=!~\[]", requirement, maxsplit=1)[0]


@unittest.skipIf(tomllib is None, "tomllib needs Python 3.11 or newer")
class PyprojectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        cls.project = cls.data["project"]

    def test_name_and_version(self):
        self.assertEqual(self.project["name"], "scrolls-workbench")
        self.assertNotEqual(self.project["name"], AUTOPIPELINE["name"])
        self.assertEqual(self.project["dynamic"], ["version"])
        self.assertEqual(self.data["tool"]["setuptools"]["dynamic"]["version"], {"attr": "kit.__version__"})

    def test_python_floor_is_the_documented_one(self):
        self.assertEqual(self.project["requires-python"], ">=3.10")
        guide = (ROOT / "docs" / "letter-reader.md").read_text(encoding="utf-8")
        self.assertIn("Python 3.10 or newer", guide)
        workflow = (ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
        self.assertIn("'3.10'", workflow)

    def test_core_has_no_dependencies_and_extras_cover_the_tools(self):
        self.assertEqual(self.project["dependencies"], [])
        extras = self.project["optional-dependencies"]
        self.assertTrue({"numpy", "pillow", "tifffile"} <= set(extras["reader"]))
        self.assertTrue({"numpy", "tifffile", "zarr"} <= {req_name(r) for r in extras["maps"]})
        self.assertEqual(set(extras["all"]), set(extras["reader"]) | set(extras["maps"]))
        # zarr 2 lacks create_array (kit shuffle, the zarr outputs): only zarr 3, which needs Python 3.11
        for extra in ("maps", "all"):
            (z,) = [r for r in extras[extra] if req_name(r) == "zarr"]
            self.assertEqual(z.replace(" ", ""), "zarr>=3;python_version>='3.11'", extra)

    def test_console_scripts_exist_and_do_not_clash_with_autopipeline(self):
        scripts = self.project["scripts"]
        self.assertFalse(set(scripts) & AUTOPIPELINE["scripts"])
        for name, target in scripts.items():
            module, func = target.split(":")
            self.assertEqual(module, "kit.cli", name)
            self.assertTrue(callable(getattr(cli, func)), name)
        one_command = {n: t for n, t in scripts.items() if n != "scrolls-workbench"}
        self.assertEqual(set(one_command), set(cli.CONSOLE_SCRIPTS))
        self.assertEqual(scripts["scrolls-workbench"], "kit.cli:workbench_main")

    def test_every_package_and_data_file_is_packaged(self):
        st = self.data["tool"]["setuptools"]
        packages = sorted(".".join(p.parent.relative_to(ROOT).parts) for p in (ROOT / "kit").rglob("__init__.py"))
        self.assertEqual(sorted(st["packages"]), packages)
        globs = st["package-data"]["kit"]
        files = [p.relative_to(ROOT / "kit").as_posix() for p in (ROOT / "kit").rglob("*")
                 if p.is_file() and p.suffix not in (".py", ".pyc") and "__pycache__" not in p.parts]
        self.assertTrue(files)
        for f in files:
            self.assertTrue(any(fnmatch.fnmatch(f, g) for g in globs), f"{f} is not in the package data")

    def test_licence_files_exist(self):
        for name in self.project["license-files"]:
            self.assertTrue((ROOT / name).is_file(), name)


class ConsoleScriptTest(unittest.TestCase):
    def run_script(self, func, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = func(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_one_command_scripts_show_their_own_name(self):
        for script, command in cli.CONSOLE_SCRIPTS.items():
            func = getattr(cli, command + "_main")
            code, out, _ = self.run_script(func, ["--help"])
            self.assertEqual(code, 0, script)
            self.assertTrue(out.startswith(f"usage: {script} "), out[:80])
            code, _, err = self.run_script(func, ["--no-such-option"])
            self.assertEqual(code, 2, script)
            self.assertIn(f"{script}: error", err)

    def test_python_m_kit_keeps_its_name(self):
        code, out, _ = self.run_script(cli.main, ["letterdemo", "--help"])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("usage: python -m kit letterdemo"), out[:80])

    def test_workbench_runs_every_command(self):
        code, out, _ = self.run_script(cli.workbench_main, ["prizes", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), prizes.load())
        code, _, err = self.run_script(cli.workbench_main, ["no-such-command"])
        self.assertEqual(code, 2)
        self.assertIn("scrolls-workbench: error", err)

    def test_data_the_package_reads_lives_in_kit_data(self):
        data = ROOT / "kit" / "data"
        self.assertEqual(Path(prizes.DATA_DIR).resolve(), data.resolve())
        source = (ROOT / "kit" / "letterread.py").read_text(encoding="utf-8")
        self.assertIn('WEIGHTS_REGISTRY = Path(__file__).parent / "data" / "letter-weights.json"', source)
        self.assertTrue((data / "letter-weights.json").is_file())


class LineEndingsTest(unittest.TestCase):
    def test_text_files_check_out_with_lf_everywhere(self):
        lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
        self.assertIn("* text=auto eol=lf", lines)
        for ext in ("png", "npz", "tif", "pdf"):
            self.assertIn(f"*.{ext} binary", lines)

    def test_ci_runs_the_reader_and_its_demo_on_three_systems(self):
        text = (ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
        self.assertNotIn("\t", text)
        for needed in ("ubuntu-latest", "macos-latest", "windows-latest", "scrolls-letterdemo", ".[reader]",
                       "--weights letters-v2-ccby"):                     # the default weights, from the release
            self.assertIn(needed, text)
        try:
            import yaml
        except ImportError:
            return
        jobs = yaml.safe_load(text)["jobs"]
        reader = jobs["reader"]
        self.assertEqual(set(reader["strategy"]["matrix"]["os"]), {"ubuntu-latest", "macos-latest", "windows-latest"})
        runs = "\n".join(step.get("run", "") for step in reader["steps"])
        self.assertIn("scrolls-letterdemo", runs)
        self.assertNotRegex(runs, re.compile(r"test_repo|bash -n"))


if __name__ == "__main__":
    unittest.main()
