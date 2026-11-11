"""Tests for kit/villaports.py on a tiny fake villa git repository and a fake user folder. No network.

Fixture texts build the villa package name from PKG so that this file itself holds no reference the tool would
find (the tool also never scans its own files).
"""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from collections import Counter
from pathlib import Path

from kit import villaports as vp

PKG = "vesu" + "vius"


def sh(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@e", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    for k in vp.LOCAL_GIT_VARIABLES:
        env.pop(k, None)
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


def write(root, rel, text):
    path = Path(root) / rel.replace("PKG", PKG)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).replace("PKG", PKG), encoding="utf-8")


def make_villa(root):
    """Two commits: the second removes the tifxyz package and read_block, renames old_gen to new_gen and adds
    a vc_reader package."""
    sh(root, "init", "-q", "-b", "main")
    base = "vesuvius/src/PKG/".replace("PKG", PKG)
    write(root, base + "__init__.py", "from .data import Cube\ntry:\n    from . import models\nexcept Exception:\n"
                                      "    models = None\n")
    write(root, base + "data.py", "class Cube:\n    pass\n")
    write(root, base + "models/__init__.py", "")
    write(root, base + "tifxyz/__init__.py", "from .reader import read_tifxyz\nclass Tifxyz:\n    pass\n")
    write(root, base + "tifxyz/reader.py", "def read_tifxyz(p):\n    return p\n")
    write(root, base + "tools/__init__.py", "")
    write(root, base + "tools/preview.py", "def open_source():\n    pass\n\ndef read_block():\n    pass\n"
                                           "LIMIT, OTHER = 1, 2\n")
    write(root, base + "star.py", "from os.path import *\n")
    write(root, base + "cli/__init__.py", "")
    write(root, base + "cli/__main__.py", "print(1)\n")
    write(root, base + "nomain/__init__.py", "")
    write(root, base + "old_gen/__init__.py", "def generate():\n    '''a long docstring so git sees a rename'''\n"
                                              "    return 1\n")
    write(root, base + "stubbed/__init__.py", "globals().update({'Made': 1})\n")
    write(root, base + "stubbed/__init__.pyi", "def Made() -> int: ...\n")
    sh(root, "add", "-A")
    sh(root, "commit", "-q", "-m", "one")
    old = sh(root, "rev-parse", "HEAD")
    sh(root, "rm", "-q", "-r", base + "tifxyz")
    write(root, base + "tools/preview.py", "def open_source():\n    pass\nLIMIT, OTHER = 1, 2\n")
    sh(root, "mv", base + "old_gen", base + "new_gen")
    write(root, base + "helpers.py", "def read_block():\n    pass\n")
    write(root, "vc_reader/src/vc_reader/__init__.py", "")
    write(root, "vc_reader/src/vc_reader/tifxyz.py", "def read(p):\n    return p\nclass Surface:\n    pass\n")
    sh(root, "add", "-A")
    sh(root, "commit", "-q", "-m", "two")
    return old, sh(root, "rev-parse", "HEAD")


OURS_A = '''\
"""Module docstring that mentions `from PKG.tifxyz import read_tifxyz`, which is not a reference."""
import importlib
from PKG.tifxyz import read_tifxyz
import PKG.tools.preview
from PKG.tools.preview import read_block, open_source
from PKG.star import anything
from PKG.stubbed import Made
from PKG import models, Cube
from .local import thing

def f():
    importlib.import_module("PKG.old_gen")
    cmd = ["python", "-m", "PKG.cli"]
    other = ["python", "-m", "PKG.nomain"]
    code = "import sys; from PKG.data import Cube; print(Cube)"
    return cmd, other, code
'''


def make_ours(root):
    """A user's folder: scripts, a shell file, a Dockerfile, a shim, a local copy of vc_reader, a vendored copy of
    the villa package, and folders the default excludes leave out."""
    sh(root, "init", "-q", "-b", "main")
    write(root, ".gitignore", "/scratch/\nignored.py\n")
    write(root, "tools/a.py", OURS_A)
    write(root, "tools/broken.py", "from PKG.tifxyz import read_tifxyz\ndef (:\n")
    write(root, "run.sh", "# python -m PKG.tifxyz is a comment\npython3 -u -m PKG.tools.preview --x\n"
                          "python - <<EOF\nfrom PKG.tifxyz import Tifxyz\nEOF\n")
    write(root, "img/Dockerfile", "RUN python -m PKG.cli\n")
    write(root, "conf.json", '{"argv": ["-m", "PKG.tifxyz"]}\n')
    write(root, "old/legacy.py", "from PKG.tifxyz import read_tifxyz\n")
    write(root, "scratch/x.py", "from PKG.tifxyz import read_tifxyz\n")
    write(root, "ignored.py", "from PKG.tifxyz import read_tifxyz\n")
    write(root, ".venv/lib/site.py", "from PKG.tifxyz import read_tifxyz\n")
    write(root, "build/lib/b.py", "from PKG.tifxyz import read_tifxyz\n")
    write(root, "third_party/PKG/__init__.py", "from PKG.tifxyz import read_tifxyz\n")
    write(root, "third_party/PKG/tifxyz.py", "from PKG.data import Cube\n")
    write(root, "compat.py", "def read_tifxyz(p):\n    return p\n")
    write(root, "shimmed.py", "try:\n    from PKG.tifxyz import read_tifxyz\nexcept ImportError:  # past #2440\n"
                              "    from compat import read_tifxyz\n")
    write(root, "shimbad.py", "try:\n    from PKG.tifxyz import read_tifxyz\nexcept ImportError:\n"
                              "    from nosuch import read_tifxyz\ntry:\n    from PKG.tifxyz import Tifxyz\n"
                              "except (ImportError, OSError):\n    from compat import Tifxyz\n"
                              "try:\n    from PKG.tifxyz import read_tifxyz\nexcept KeyError:\n"
                              "    from compat import read_tifxyz\n")
    write(root, "localpkg/vc_reader/__init__.py", "")
    write(root, "localpkg/vc_reader/transforms.py", "def Normalize():\n    pass\n")
    write(root, "localpkg/job.py", "from vc_reader.transforms import Normalize\nfrom vc_reader.gone import x\n"
          "from vc_reader import transforms\nfrom vc_reader.transforms import Missing\n")
    sh(root, "add", "-A")
    sh(root, "commit", "-q", "-m", "ours")


MAP = {
    "packages": {PKG: ["vesuvius/src/" + PKG], "vc_reader": ["vc_reader/src/vc_reader"]},
    "entries": [
        {"old": PKG + ".tifxyz", "new_module": "vc_reader.tifxyz", "use": "use vc_reader.tifxyz",
         "villa": "vc_reader/src/vc_reader/tifxyz.py", "commit": "c" * 40},
        {"old": PKG + ".tifxyz", "name": "read_tifxyz", "new_module": "vc_reader.tifxyz", "new_name": "read",
         "use": "vc_reader.tifxyz.read", "villa": "vc_reader/src/vc_reader/tifxyz.py", "commit": "c" * 40},
        {"old": PKG + ".tifxyz", "name": "Tifxyz", "new_module": "vc_reader.tifxyz", "new_name": "Gone",
         "use": "vc_reader.tifxyz.Gone", "villa": "vc_reader/src/vc_reader/tifxyz.py", "commit": "c" * 40},
    ],
}


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.villa_dir = Path(cls.tmp.name) / "villa"
        cls.ours = Path(cls.tmp.name) / "ours"
        cls.villa_dir.mkdir()
        cls.ours.mkdir()
        cls.old, cls.new = make_villa(cls.villa_dir)
        make_ours(cls.ours)
        cls.map_path = Path(cls.tmp.name) / "map.json"
        cls.map_path.write_text(json.dumps(MAP), encoding="utf-8")
        cls.data = vp.load_map(cls.map_path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def villa(self):
        return vp.Villa(self.villa_dir, self.data["packages"])

    def refs(self, **kw):
        return vp.find_refs([self.ours], list(self.data["packages"]), **kw)

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = vp.main(list(argv) + ["--villa-git", str(self.villa_dir), "--map", str(self.map_path), "--json"])
        return code, json.loads(out.getvalue())


class FindRefs(Fixture):
    def test_forms(self):
        a = {(r.line, r.module, r.names, r.kind) for r in self.refs() if r.path == "tools/a.py"}
        self.assertNotIn(1, {line for line, *_ in a}, "a docstring is not a reference")
        self.assertIn((3, PKG + ".tifxyz", ("read_tifxyz",), "from"), a)
        self.assertIn((4, PKG + ".tools.preview", (), "import"), a)
        self.assertIn((12, PKG + ".old_gen", (), "import_module"), a)
        self.assertIn((13, PKG + ".cli", (), "-m"), a)
        self.assertIn((15, PKG + ".data", ("Cube",), "string-import"), a)
        self.assertFalse(any(m.startswith(".") or m == "local" for _, m, _, _ in a))

    def test_text_files(self):
        by_path = {}
        for r in self.refs():
            by_path.setdefault(r.path, []).append(r)
        self.assertEqual([(r.line, r.module) for r in by_path["run.sh"]],
                         [(2, PKG + ".tools.preview"), (4, PKG + ".tifxyz")], "the comment line is skipped")
        self.assertEqual(by_path["img/Dockerfile"][0].kind, "-m")
        self.assertEqual(by_path["conf.json"][0].module, PKG + ".tifxyz")
        self.assertEqual(by_path["tools/broken.py"][0].module, PKG + ".tifxyz", "unparsable file read by lines")

    def test_default_excludes(self):
        skipped = Counter()
        paths = {r.path for r in self.refs(skipped=skipped)}
        for gone in ("scratch/x.py", "ignored.py", ".venv/lib/site.py", "build/lib/b.py",
                     "third_party/%s/__init__.py" % PKG):
            self.assertNotIn(gone, paths)
        self.assertEqual(skipped["vendored"], 4, "both vendored copies (vesuvius and vc_reader) are counted")
        self.assertIn("old/legacy.py", paths)
        every = {r.path for r in self.refs(defaults=False)}
        for back in ("scratch/x.py", "ignored.py", ".venv/lib/site.py", "build/lib/b.py",
                     "third_party/%s/tifxyz.py" % PKG):
            self.assertIn(back, every, "--no-default-excludes scans it")

    def test_exclude_glob(self):
        paths = {r.path for r in self.refs(excludes=["old", "*.sh", "img/*"])}
        self.assertNotIn("old/legacy.py", paths)
        self.assertNotIn("run.sh", paths)
        self.assertNotIn("img/Dockerfile", paths)
        self.assertIn("tools/a.py", paths)

    def test_excluded_and_vendored(self):
        self.assertTrue(vp.excluded("a/build/x.py", vp.DEFAULT_EXCLUDES))
        self.assertTrue(vp.excluded("pkg.egg-info/x.py", vp.DEFAULT_EXCLUDES))
        self.assertFalse(vp.excluded("builder/x.py", vp.DEFAULT_EXCLUDES))
        self.assertTrue(vp.excluded("deep/old/x.py", ["deep/old"]))
        self.assertTrue(vp.vendored_copy(self.ours, "third_party/%s/tifxyz.py" % PKG, [PKG]))
        self.assertFalse(vp.vendored_copy(self.ours, "localpkg/job.py", [PKG, "vc_reader"]))

    def test_plain_folder_and_two_roots(self):
        plain = Path(self.tmp.name) / "plain"
        write(plain, "s.py", "from PKG.data import Cube\n")
        write(plain, "venv/x.py", "from PKG.data import Cube\n")
        refs = vp.find_refs([plain], [PKG])
        self.assertEqual([r.path for r in refs], ["s.py"], "outside git a walk, with the folder excludes")
        refs = vp.find_refs([plain, self.ours / "img"], [PKG])
        self.assertEqual({r.path for r in refs}, {"%s/s.py" % plain, "%s/Dockerfile" % (self.ours / "img")})
        with self.assertRaises(ValueError):
            vp.find_refs([plain / "nope"], [PKG])

    def test_never_scans_itself(self):
        paths = {r.path for r in vp.find_refs([vp.ROOT / "tests"], ["vc_reader", PKG], excludes=["*"])}
        self.assertEqual(paths, set())
        self.assertIn(Path(vp.__file__).resolve(), vp.SELF)
        self.assertNotIn("test_villaports.py", {r.path for r in vp.find_refs([vp.ROOT / "tests"], [PKG])})

    def test_split_names(self):
        self.assertEqual(vp._split_names("(a, b as c,\n d)"), ("a", "b", "d"))
        self.assertEqual(vp._split_names("a; print(a)"), ("a",))


class Resolve(Fixture):
    def statuses(self, ref):
        snap = self.villa().snapshot(ref)
        refs = self.refs()
        return {(r.path, r.line, r.module): res for r, res in zip(refs, snap.resolve_all(refs, vp.Shims([self.ours])))}

    def test_old_commit(self):
        s = self.statuses(self.old)
        self.assertEqual(s[("tools/a.py", 3, PKG + ".tifxyz")][0], vp.OK)
        self.assertEqual(s[("tools/a.py", 5, PKG + ".tools.preview")][0], vp.OK)
        self.assertEqual(s[("tools/a.py", 6, PKG + ".star")][0], vp.UNKNOWN, "star import leaves names open")
        self.assertEqual(s[("tools/a.py", 7, PKG + ".stubbed")][0], vp.OK, "names from the .pyi stub count")
        self.assertEqual(s[("tools/a.py", 8, PKG)][0], vp.OK, "names bound under try and submodules count")
        self.assertEqual(s[("tools/a.py", 13, PKG + ".cli")][0], vp.OK)
        self.assertEqual(s[("tools/a.py", 14, PKG + ".nomain")],
                         (vp.MISSING_MODULE, "package %s.nomain has no __main__.py for -m" % PKG))

    def test_new_commit(self):
        s = self.statuses(self.new)
        self.assertEqual(s[("tools/a.py", 3, PKG + ".tifxyz")], (vp.MISSING_MODULE, "no module %s.tifxyz" % PKG))
        self.assertEqual(s[("tools/a.py", 5, PKG + ".tools.preview")],
                         (vp.MISSING_NAME, "no name read_block in %s.tools.preview" % PKG))
        self.assertEqual(s[("tools/a.py", 12, PKG + ".old_gen")][0], vp.MISSING_MODULE)
        self.assertEqual(s[("tools/a.py", 4, PKG + ".tools.preview")][0], vp.OK)

    def test_shims(self):
        s = self.statuses(self.new)
        self.assertEqual(s[("shimmed.py", 2, PKG + ".tifxyz")], (vp.SHIM, "via shim compat.py"))
        status, detail = s[("shimbad.py", 2, PKG + ".tifxyz")]
        self.assertEqual(status, vp.MISSING_MODULE)
        self.assertIn("shim nosuch is not in the scanned folder", detail)
        status, detail = s[("shimbad.py", 6, PKG + ".tifxyz")]
        self.assertEqual(status, vp.MISSING_MODULE)
        self.assertIn("shim compat defines no Tifxyz", detail)
        self.assertEqual(s[("shimbad.py", 10, PKG + ".tifxyz")][0], vp.MISSING_MODULE,
                         "a handler that does not catch ImportError is not a shim")
        self.assertEqual(self.statuses(self.old)[("shimmed.py", 2, PKG + ".tifxyz")][0], vp.OK,
                         "villa's own module wins where it exists")

    def test_without_shims(self):
        snap = self.villa().snapshot(self.new)
        refs = [r for r in self.refs() if r.path == "shimmed.py"]
        self.assertEqual(snap.resolve_all(refs)[0][0], vp.MISSING_MODULE)

    def test_local_copy(self):
        s = self.statuses(self.old)  # villa's first commit has no vc_reader at all
        self.assertEqual(s[("localpkg/job.py", 1, "vc_reader.transforms")],
                         (vp.OK, "local copy localpkg/vc_reader/transforms.py"))
        self.assertEqual(s[("localpkg/job.py", 2, "vc_reader.gone")],
                         (vp.MISSING_MODULE, "no module vc_reader.gone in the local copy localpkg/vc_reader"))
        self.assertEqual(s[("localpkg/job.py", 3, "vc_reader")][0], vp.OK, "a submodule of the copy")
        self.assertEqual(s[("localpkg/job.py", 4, "vc_reader.transforms")][0], vp.MISSING_NAME)

    def test_bad_ref(self):
        with self.assertRaises(vp.VillaError):
            self.villa().resolve("no-such-branch")
        with self.assertRaises(vp.VillaError):
            vp.Villa(Path(self.tmp.name))

    def test_top_level_names(self):
        names, open_ = vp.top_level_names("if X:\n    a = 1\nelse:\n    from m import b as c\n"
                                          "def __getattr__(n):\n    pass\n")
        self.assertEqual(names, {"a", "c", "__getattr__"})
        self.assertTrue(open_)
        self.assertEqual(vp.top_level_names("def (:")[1], True)
        self.assertFalse(vp.top_level_names("if __name__ == '__main__':\n    main(vars(x))\n")[1])
        self.assertEqual(vp.defined_names("import os\ndef f():\n    pass\nX = 1\n__all__ = []\n"), {"f", "X"})


class MapLookup(Fixture):
    def test_lookup(self):
        entries = self.data["entries"]
        self.assertEqual(vp.map_lookup(entries, PKG + ".tifxyz", "read_tifxyz")["new_name"], "read")
        self.assertEqual(vp.map_lookup(entries, PKG + ".tifxyz.reader", "read_tifxyz")["new_name"], "read")
        self.assertEqual(vp.map_lookup(entries, PKG + ".tifxyz.writer", "other")["use"], "use vc_reader.tifxyz")
        self.assertIsNone(vp.map_lookup(entries, PKG + ".tifxyzfoo", None))

    def test_suggestion_checks_target(self):
        snap = self.villa().snapshot(self.new)
        ref = vp.Ref("x", 1, PKG + ".tifxyz", ("read_tifxyz", "Tifxyz"))
        text = vp.suggestion(snap, self.data["entries"], ref, "no module %s.tifxyz" % PKG)
        self.assertIn("read_tifxyz: vc_reader.tifxyz.read", text)
        self.assertNotIn("read [map target", text)
        self.assertIn("vc_reader.tifxyz.Gone (map: villa vc_reader/src/vc_reader/tifxyz.py at ccccccccc) "
                      "[map target not found", text)

    def test_suggestion_from_definitions(self):
        snap = self.villa().snapshot(self.new)
        ref = vp.Ref("x", 1, PKG + ".tools.preview", ("read_block",))
        text = vp.suggestion(snap, [], ref, "no name read_block in %s.tools.preview" % PKG)
        self.assertEqual(text, "read_block is defined at %s in %s.helpers" % (self.new[:9], PKG))

    def test_bad_map(self):
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text(json.dumps({"entries": [{"old": PKG + ".x"}]}), encoding="utf-8")
        with self.assertRaises(ValueError):
            vp.load_map(bad)
        self.assertEqual(vp.load_map(Path(self.tmp.name) / "absent.json")["entries"], [])

    def test_real_map(self):
        data = vp.load_map()
        self.assertIn(PKG, data["packages"])
        self.assertIn("vc_reader", data["packages"])
        self.assertTrue(data["entries"])
        for e in data["entries"]:
            self.assertEqual(e["commit"], vp.TAKEOVER, "every entry cites the #2440 merge commit")
            self.assertTrue(e["villa"].startswith(("vesuvius/src/", "vc_reader/src/")), e["villa"])
            self.assertTrue(e["old"].split(".")[0] in data["packages"])

    def test_real_map_points_at_hints_ask_for_bicubic(self):
        """vc_reader's points_at() accepts "linear" or "bicubic"; villa #2506 (f0e4410) made villa's own callers ask
        for "bicubic", so no hint may suggest "smooth", which raises there."""
        hints = [e["use"] for e in vp.load_map()["entries"] if "points_at(" in e["use"]]
        self.assertEqual(len(hints), 2)
        for use in hints:
            self.assertIn('interpolation="bicubic"', use)
            self.assertNotIn('"smooth"', use)


class Commands(Fixture):
    def test_scan(self):
        code, report = self.run_cli("scan", "--villa", self.new, "--root", str(self.ours))
        self.assertEqual(code, vp.EXIT_ATTENTION)
        summary = report["summary"]
        self.assertGreater(summary["statuses"][vp.MISSING_MODULE], 0)
        self.assertEqual(summary["statuses"][vp.SHIM], 1)
        self.assertEqual(summary["skipped_vendored_files"], 4)
        row = next(r for r in report["references"] if r["path"] == "tools/a.py" and r["line"] == 3)
        self.assertIn("vc_reader.tifxyz.read", row["suggestion"])
        self.assertIn(PKG + ".tifxyz", summary["groups"])
        self.assertEqual(report["scanned"], [str(self.ours.resolve())])

    def test_scan_text(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = vp.main(["scan", "--villa", self.new, "--root", str(self.ours), "--villa-git",
                            str(self.villa_dir), "--map", str(self.map_path), "--exclude", "localpkg"])
        text = out.getvalue()
        self.assertEqual(code, vp.EXIT_ATTENTION)
        self.assertIn("files break", text)
        self.assertIn("skipped 2 files in vendored copies of villa packages", text)
        self.assertIn("ok via shim: 1 references via shim compat.py", text)
        self.assertIn("missing-module tools/a.py:3  %s.tifxyz (read_tifxyz)  no module %s.tifxyz" % (PKG, PKG), text)
        self.assertIn("-> vc_reader.tifxyz.read", text)
        self.assertIn("breaks by removed module or name:", text)
        self.assertNotIn("\x1b[", text, "plain text off a terminal")

    def test_scan_clean(self):
        clean = Path(self.tmp.name) / "clean"
        write(clean, "a.py", "from PKG.data import Cube\n")
        code, report = self.run_cli("scan", "--villa", self.new, "--root", str(clean))
        self.assertEqual(code, vp.EXIT_OK)
        self.assertEqual(report["summary"]["statuses"][vp.OK], 1)

    def test_scan_default_root_is_cwd(self):
        clean = Path(self.tmp.name) / "cwd"
        write(clean, "a.py", "from PKG.tifxyz import read_tifxyz\n")
        before = os.getcwd()
        os.chdir(clean)
        try:
            code, report = self.run_cli("scan", "--villa", self.new)
        finally:
            os.chdir(before)
        self.assertEqual(code, vp.EXIT_ATTENTION)
        self.assertEqual([r["path"] for r in report["references"]], ["a.py"])

    def test_diff(self):
        code, report = self.run_cli("diff", "--from", self.old, "--to", self.new, "--root", str(self.ours))
        self.assertEqual(code, vp.EXIT_ATTENTION)
        changes = {c["removed"]: c for c in report["changes"]}
        self.assertIn(PKG + ".tifxyz", changes)
        self.assertEqual(changes[PKG + ".old_gen"]["renamed_to"], PKG + ".new_gen")
        self.assertEqual(changes[PKG + ".tools.preview.read_block"]["what"], "name")
        self.assertNotIn(PKG + ".nomain", changes, "broken at both commits is not a change")
        shimmed = [r for r in changes[PKG + ".tifxyz"]["references"] if r["shim"]]
        self.assertEqual([(r["path"], r["shim"]) for r in shimmed], [("shimmed.py", "compat.py")])
        self.assertGreater(report["unshimmed"], 0)
        code, report = self.run_cli("diff", "--from", self.new, "--to", self.new, "--root", str(self.ours))
        self.assertEqual((code, report["changes"]), (vp.EXIT_OK, []))

    def test_errors(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = vp.main(["scan", "--villa", "no-such", "--root", str(self.ours), "--villa-git",
                            str(self.villa_dir), "--map", str(self.map_path)])
        self.assertEqual(code, vp.EXIT_FAIL)
        self.assertIn("kit villaports failed: villa has no commit", err.getvalue())
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = vp.main(["scan", "--root", str(self.ours / "nope"), "--villa-git", str(self.villa_dir),
                            "--map", str(self.map_path)])
        self.assertEqual(code, vp.EXIT_FAIL)
        self.assertIn("no folder", err.getvalue())

    def test_offline_without_cache(self):
        with self.assertRaises(vp.Unreachable):
            vp.ensure_clone(Path(self.tmp.name) / "nocache", offline=True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = vp.main(["scan", "--offline", "--cache", str(Path(self.tmp.name) / "empty"), "--map",
                            str(self.map_path), "--root", str(self.ours)])
        self.assertEqual(code, vp.EXIT_UNREACHABLE)
        self.assertIn("villa unreachable", err.getvalue())

    def test_default_cache(self):
        self.assertEqual(vp.default_cache({"XDG_CACHE_HOME": "/c"}), Path("/c/scrolls-villaports/villa.git"))
        self.assertEqual(vp.default_cache({}), Path.home() / ".cache" / "scrolls-villaports" / "villa.git")

    def test_clone_failure_is_unreachable(self):
        with self.assertRaises(vp.Unreachable):
            vp.ensure_clone(Path(self.tmp.name) / "c2", url=str(Path(self.tmp.name) / "no-such-repo"))

    def test_clone_then_cached(self):
        cache = Path(self.tmp.name) / "c3" / "villa.git"
        path, note = vp.ensure_clone(cache, url="file://" + str(self.villa_dir))
        self.assertTrue(note.startswith("cloned "))
        self.assertEqual(vp.ensure_clone(cache, offline=True)[1], "cached clone, not fetched (--offline)")
        self.assertTrue(vp.ensure_clone(cache)[1].startswith("fetched "))

    def test_partial_clone_prefetch(self):
        clone = Path(self.tmp.name) / "partial.git"
        sh(self.villa_dir, "config", "uploadpack.allowFilter", "true")
        sh(self.villa_dir, "config", "uploadpack.allowAnySHA1InWant", "true")
        sh(self.tmp.name, "clone", "-q", "--bare", "--filter=blob:none", "file://" + str(self.villa_dir), str(clone))
        villa = vp.Villa(clone, self.data["packages"])
        snap = villa.snapshot("main")
        ref = vp.Ref("x", 1, PKG + ".tools.preview", ("open_source", "read_block"))
        self.assertEqual(snap.resolve_all([ref])[0][0], vp.MISSING_NAME)


if __name__ == "__main__":
    unittest.main()
