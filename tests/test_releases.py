"""kit/releases.py: the release list and the README section written from it.

The same file runs in both repositories; the repository check below applies wherever docs/releases.json exists.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from kit import releases as r

ROOT = Path(__file__).resolve().parent.parent


def entry(**over):
    e = {"id": "demo-tool", "title": "Demo tool", "released": "2026-10-14",
         "summary": "Does one thing on public data (Model output). Not a reading.",
         "commands": ["python -m pip install numpy", "python demo.py --help   # a comment"],
         "details": "Guide: [`docs/demo.md`](docs/demo.md).", "where": "main"}
    e.update(over)
    return {k: v for k, v in e.items() if v is not None}


PACKAGE = {"branch": "submission/progress-2026-10", "commit": "faada83287d39bbd4c7fd88c7ab0e75f3f1ff284",
           "path": "submissions/progress-2026-10"}
README = "# Title\n\nIntro.\n\n## Released tools\n\n" + r.START + "\nold text\n" + r.END + "\n\n## After\n\nKept.\n"


class ValidateTest(unittest.TestCase):
    def test_good_entries_pass(self):
        r.validate(entry())
        r.validate(entry(commands=None, details=None))
        r.validate(entry(where=PACKAGE, details=None))
        r.validate(entry(where=PACKAGE, details="Guide: [README](https://github.com/ChaseHendrick/Scrolls/blob/"
                                                 "faada83287d39bbd4c7fd88c7ab0e75f3f1ff284/README.md)."))
        r.validate(entry(commands=["python -m kit prizes"], summary="Under 5 minutes, see <https://example.org>."))

    def test_bad_entries_fail(self):
        bad = [entry(id="Demo"), entry(id="-x"), entry(id="a" * 64), entry(title=""), entry(title="a\nb"),
               entry(title="x" * 81), entry(summary="two\n\nparagraphs"), entry(summary=7), entry(released="14 Oct 2026"),
               entry(released="2026-02-30"), entry(commands="python x"), entry(commands=["a\nb"]),
               entry(commands=["```"]), entry(commands=[""]), entry(commands=["x"] * 13), entry(details="a\nb"),
               entry(summary="a" + chr(0x2014) + "b"), entry(details="en" + chr(0x2013) + "dash"),
               entry(commands=["x " + chr(0x2014)]), entry(summary="hides <!-- releases:end --> a marker"),
               entry(where="develop"), entry(where=dict(PACKAGE, commit="faada83")),
               entry(where=dict(PACKAGE, path="../x")), entry(where=dict(PACKAGE, path="/abs")),
               entry(where=dict(PACKAGE, branch="main")), entry(where=dict(PACKAGE, branch="-x")),
               entry(where=dict(PACKAGE, branch="a..b")), entry(where=dict(PACKAGE, extra=1)),
               entry(unknown="field"), {k: v for k, v in entry().items() if k != "summary"}, ["not", "an", "object"],
               entry(summary="~~~ approximate"), entry(summary="``` x"), entry(summary="<pre> shows the layout"),
               entry(summary="<?xml version"), entry(summary="    indented code"), entry(details="\tTabbed"),
               entry(details="<details> more"),
               entry(where=PACKAGE, commands=["cd pkg && python -m kit " + "autopipeline defaults"]),
               entry(where=PACKAGE, details="Then run python3 -m kit " + "demo."),
               entry(where=PACKAGE, details="Guide: [README](README.md)."), entry(where=PACKAGE, summary="See [x](http://a.b).")]
        for e in bad:
            with self.subTest(entry=e), self.assertRaises(r.ReleaseListError):
                r.validate(e)

    def test_list_rejects_duplicates_and_wrong_shape(self):
        for registry in ({"schema_version": 1, "releases": [entry(), entry()]},
                         {"schema_version": 2, "releases": []}, {"releases": []},
                         {"schema_version": 1, "releases": {}}, {"schema_version": 1, "releases": [], "x": 1}):
            with self.subTest(registry=registry), self.assertRaises(r.ReleaseListError):
                r.validate_list(registry)


class RenderTest(unittest.TestCase):
    def test_main_entry(self):
        text = "\n".join(r.render_entry(entry()))
        self.assertEqual(text, "### Demo tool\n\nReleased 14 October 2026.\n\nDoes one thing on public data (Model output). "
                               "Not a reading.\n\n```bash\npython -m pip install numpy\npython demo.py --help   # a comment\n"
                               "```\n\nGuide: [`docs/demo.md`](docs/demo.md).")

    def test_package_entry_links_its_commit(self):
        text = "\n".join(r.render_entry(entry(where=PACKAGE, commands=None, details=None)))
        self.assertIn("Released 14 October 2026 as a reviewed package on branch `submission/progress-2026-10`: "
                      "[`submissions/progress-2026-10/` at commit `faada83`](https://github.com/ChaseHendrick/Scrolls/tree/"
                      "faada83287d39bbd4c7fd88c7ab0e75f3f1ff284/submissions/progress-2026-10).", text)
        self.assertNotIn("```", text)

    def test_newest_first_and_later_entry_first_on_the_same_day(self):
        registry = {"schema_version": 1, "releases": [entry(id="old", released="2026-09-01"), entry(id="a"),
                                                      entry(id="b"), entry(id="mid", released="2026-10-01")]}
        self.assertEqual([e["id"] for e in r.ordered(registry["releases"])], ["b", "a", "mid", "old"])

    def test_render_is_wrapped_in_the_markers(self):
        block = r.render({"schema_version": 1, "releases": [entry()]})
        lines = block.split("\n")
        self.assertEqual((lines[0], lines[1], lines[-1]), (r.START, r.INTRO, r.END))
        self.assertEqual(r.render({"schema_version": 1, "releases": []}), r.START + "\n" + r.INTRO + "\n" + r.END)


class ApplyTest(unittest.TestCase):
    def test_apply_rewrites_only_the_section(self):
        registry = {"schema_version": 1, "releases": [entry()]}
        out = r.apply(README, registry)
        self.assertTrue(out.startswith("# Title\n\nIntro.\n\n## Released tools\n\n" + r.START + "\n"))
        self.assertTrue(out.endswith(r.END + "\n\n## After\n\nKept.\n"))
        self.assertNotIn("old text", out)
        self.assertIn("### Demo tool", out)
        self.assertEqual(r.apply(out, registry), out)

    def test_apply_needs_one_pair_of_markers_in_order(self):
        registry = {"schema_version": 1, "releases": []}
        for text in ("no markers", r.START + "\n", r.END + "\n", r.END + "\n" + r.START + "\n",
                     README + README):
            with self.subTest(text=text), self.assertRaises(r.ReleaseListError):
                r.apply(text, registry)

    def test_upsert_adds_then_replaces(self):
        registry = {"schema_version": 1, "releases": [entry(id="first")]}
        registry2, action = r.upsert(registry, entry())
        self.assertEqual((action, [e["id"] for e in registry2["releases"]]), ("added", ["first", "demo-tool"]))
        registry3, action = r.upsert(registry2, entry(title="Demo tool 2"))
        self.assertEqual((action, [e["title"] for e in registry3["releases"]]), ("replaced", ["Demo tool", "Demo tool 2"]))
        self.assertEqual(len(registry["releases"]), 1, "the input list is not changed")

    def test_updated_gives_both_files(self):
        registry_text = r.dumps({"schema_version": 1, "releases": []})
        new_registry, new_readme, action = r.updated(registry_text, README, entry(where=PACKAGE, details=None))
        self.assertEqual(action, "added")
        self.assertEqual(json.loads(new_registry)["releases"][0]["where"], PACKAGE)
        self.assertEqual(new_readme, r.apply(README, json.loads(new_registry)))
        self.assertEqual(new_registry, r.dumps(json.loads(new_registry)))


class CommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.registry, self.readme = self.dir / "releases.json", self.dir / "README.md"
        self.registry.write_text(r.dumps({"schema_version": 1, "releases": []}))
        self.readme.write_text(README)

    def call(self, *argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = r.main(["--list", str(self.registry), "--readme", str(self.readme), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_no_list_points_to_a_clone(self):
        """An installed package has no docs/: the command says it needs a clone, not a bare file error."""
        self.registry = self.dir / "docs" / "releases.json"
        for action in ("check", "render", "list"):
            code, _, err = self.call(action)
            self.assertEqual(code, 2, action)
            self.assertIn("run it from a clone", err)
        self.assertEqual(self.readme.read_text(), README)

    def test_check_render_add_list(self):
        self.assertEqual(self.call("check")[0], 1)
        self.assertEqual(self.call("render")[0], 0)
        self.assertEqual(self.call("check")[0], 0)
        f = self.dir / "entry.json"
        f.write_text(json.dumps(entry()))
        code, out, _ = self.call("add", str(f))
        self.assertEqual((code, json.loads(out)["action"]), (0, "added"))
        self.assertEqual(self.call("check")[0], 0)
        self.assertIn("### Demo tool", self.readme.read_text())
        f.write_text(json.dumps(entry(title="Renamed")))
        code, out, _ = self.call("add", str(f))
        self.assertEqual((code, json.loads(out)["action"]), (0, "replaced"))
        self.assertIn("### Renamed", self.readme.read_text())
        self.assertIn("demo-tool", self.call("list")[1])

    def test_hand_edits_are_caught(self):
        self.call("render")
        self.readme.write_text(self.readme.read_text().replace(r.INTRO, r.INTRO + " Edited by hand."))
        code, _, err = self.call("check")
        self.assertEqual(code, 1)
        self.assertIn("python -m kit releases render", err)
        self.call("render")
        self.registry.write_text(json.dumps({"schema_version": 1, "releases": []}))   # valid but not written by dumps
        self.assertEqual(self.call("check")[0], 1)

    def test_bad_entry_changes_nothing(self):
        self.call("render")
        before = (self.registry.read_text(), self.readme.read_text())
        f = self.dir / "entry.json"
        f.write_text(json.dumps(entry(summary="a" + chr(0x2014) + "b")))
        code, _, err = self.call("add", str(f))
        self.assertEqual(code, 2)
        self.assertIn("long dash", err)
        self.assertEqual(before, (self.registry.read_text(), self.readme.read_text()))

    def test_kit_command_is_registered(self):
        from kit import cli
        args = cli.build_parser().parse_args(["releases", "--list", str(self.registry), "--readme", str(self.readme), "check"])
        self.assertIs(args.func, r.run)


class RepositoryTest(unittest.TestCase):
    def test_readme_section_matches_the_list(self):
        if not (ROOT / "docs" / "releases.json").is_file():
            self.skipTest("this repository keeps no release list")
        self.assertEqual(r.check(ROOT / "docs" / "releases.json", ROOT / "README.md"), [])


if __name__ == "__main__":
    unittest.main()
