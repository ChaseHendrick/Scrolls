"""Tool docs: every tool has a page in docs/tools/ that follows docs/TOOL-DOCS.md, and the checker can fail."""

import json
import tempfile
import unittest
from pathlib import Path

from kit import tooldocs

ROOT = Path(__file__).resolve().parent.parent

GOOD = """# kit demo: a demo tool

Does one thing for the test.

| Field | Value |
| --- | --- |
| Id | `demo` |
| Status | Current |
| Kind | kit command |
| Run | `python -m kit demo` |
| Code | `kit/demo.py` |
| Tests | `tests/test_demo.py` |
| Needs | Python 3.10 |
| Runs on | CPU, under a second (measured 2026-10-16) |
| Network | None |
| Writes | Nothing (prints only) |
| Go-ahead | Not needed |
| Released | Public `main` |
| Checked | 2026-10-16 against commit `abc1234` |

## What it does

It demonstrates.

## When to use it

In tests.

## Quick start

```bash
python -m kit demo --flag
```

## Commands and options

| Option | Default | Meaning |
| --- | --- | --- |
| `--flag` | off | A flag |

## Inputs

None.

## Outputs

Text.

## How it works

Simply.

## Checks and controls

A control.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `error` | bad | fix |

## Cost and time

Not measured.

## For agents

Run it.

## Tests

`python -m unittest tests.test_demo`

## History

- 2026-10-16: first version.

## Related

None.
"""

COMMANDS = {"demo": {None: ["--flag"]}, "other": {None: [], "go": ["--fast"]}}


def page(root, text, name="demo"):
    path = root / "docs" / "tools" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return tooldocs.Page(path, text)


class RepositoryPages(unittest.TestCase):
    def test_every_tool_has_a_page_that_follows_the_standard(self):
        problems = tooldocs.check_all()
        self.assertEqual(problems, [], "\n" + "\n".join(problems[:60]) +
                         f"\n({len(problems)} problems; see docs/TOOL-DOCS.md)")

    def test_index_json_lists_every_page(self):
        data = json.loads((ROOT / "docs" / "tools" / "index.json").read_text(encoding="utf-8"))
        ids = sorted(p.stem for p in (ROOT / "docs" / "tools").glob("*.md") if p.name != "README.md")
        self.assertEqual([t["id"] for t in data["tools"]], ids)


class CheckerCanFail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in ("kit/demo.py", "tests/test_demo.py"):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def problems(self, text, commands=COMMANDS):
        return tooldocs.check_page(page(self.root, text), self.root, commands)

    def test_good_page_passes(self):
        self.assertEqual(self.problems(GOOD), [])

    def test_missing_section_is_caught(self):
        text = GOOD.replace("## Failure modes\n", "## Troubles\n")
        self.assertTrue(any("Failure modes" in p for p in self.problems(text)))

    def test_section_out_of_order_is_caught(self):
        a, b = "## Inputs\n\nNone.\n", "## Outputs\n\nText.\n"
        text = GOOD.replace(a, "@@").replace(b, a).replace("@@", b)
        self.assertTrue(any("out of order" in p for p in self.problems(text)))

    def test_python_api_replaces_commands_for_a_library(self):
        self.assertEqual(self.problems(GOOD.replace("## Commands and options", "## Python API")), [])

    def test_empty_section_is_caught(self):
        text = GOOD.replace("## How it works\n\nSimply.\n", "## How it works\n\n")
        self.assertTrue(any("'## How it works' is empty" in p for p in self.problems(text)))

    def test_missing_field_and_bad_words_are_caught(self):
        text = GOOD.replace("| Network | None |\n", "").replace("| Status | Current |", "| Status | Fine |")
        text = text.replace("| Kind | kit command |", "| Kind | gadget |")
        found = " ".join(self.problems(text))
        for words in ("missing fields ['Network']", "Status 'Fine'", "Kind 'gadget'"):
            self.assertIn(words, found)

    def test_wrong_id_and_bad_date_are_caught(self):
        text = GOOD.replace("| Id | `demo` |", "| Id | `other` |").replace("| Checked | 2026-10-16", "| Checked | today")
        found = " ".join(self.problems(text))
        self.assertIn("Id is", found)
        self.assertIn("Checked must start with the date", found)

    def test_missing_code_path_is_caught(self):
        text = GOOD.replace("`kit/demo.py`", "`kit/gone.py`")
        self.assertTrue(any("kit/gone.py" in p for p in self.problems(text)))

    def test_undocumented_option_is_caught(self):
        text = GOOD.replace("python -m kit demo --flag", "python -m kit demo").replace("| `--flag` |", "| flag |")
        self.assertTrue(any("`--flag`" in p for p in self.problems(text)))

    def test_unknown_command_and_action_are_caught(self):
        text = GOOD.replace("| Run | `python -m kit demo` |", "| Run | `python -m kit nosuch`, `python -m kit other stop` |")
        found = " ".join(self.problems(text))
        self.assertIn("`python -m kit nosuch`, which is not a kit command", found)
        self.assertIn("not an action of other", found)

    def test_action_options_are_required(self):
        text = GOOD.replace("| Run | `python -m kit demo` |", "| Run | `python -m kit demo`, `python -m kit other go` |")
        self.assertTrue(any("`--fast`" in p for p in self.problems(text)))
        self.assertEqual(self.problems(text.replace("--flag", "--flag --fast go")), [])

    def test_template_leftovers_are_caught(self):
        text = GOOD.replace("It demonstrates.", "<!-- Write: what it does -->")
        self.assertTrue(any("template guidance" in p for p in self.problems(text)))

    def test_long_summary_is_caught(self):
        text = GOOD.replace("Does one thing for the test.", "word " * 80)
        self.assertTrue(any("summary is" in p for p in self.problems(text)))

    def test_retired_needs_replaced_by(self):
        text = GOOD.replace("| Status | Current |", "| Status | Retired |")
        self.assertTrue(any("Replaced by" in p for p in self.problems(text)))
        fixed = text.replace("| Released |", "| Replaced by | Nothing |\n| Released |")
        self.assertEqual(self.problems(fixed), [])

    def test_branch_only_has_its_own_sections_and_skips_paths(self):
        text = (ROOT / "templates" / "tool-doc-branch.md").read_text(encoding="utf-8")
        text = text.replace("{id}", "demo").replace("{kind}", "kit module").replace("{date}", "2026-10-16")
        found = " ".join(self.problems(text))
        self.assertIn("template guidance", found)
        self.assertNotIn("missing section '## Quick start'", found)
        self.assertNotIn("not in the repository", found)

    def test_headings_inside_code_blocks_do_not_count(self):
        text = GOOD.replace("python -m kit demo --flag", "python -m kit demo --flag\n## Failure modes")
        self.assertEqual(self.problems(text), [])


class Coverage(unittest.TestCase):
    def test_new_module_script_and_command_without_a_page_are_caught(self):
        pages = [tooldocs.Page(Path("demo.md"), GOOD)]
        files = ["kit/demo.py", "kit/newtool.py", "kit/pkg/__init__.py", "scripts/newscript.py", "scripts/old/a.py"]
        found = " ".join(tooldocs.coverage(pages, files, COMMANDS))
        for name in ("kit/newtool.py", "kit/pkg", "scripts/newscript.py", "scripts/old", "kit other go"):
            self.assertIn(name, found)
        self.assertNotIn("kit/demo.py has no", found)

    def test_a_folder_in_code_covers_its_files(self):
        text = GOOD.replace("`kit/demo.py`", "`kit/demo.py`, `scripts/old/`")
        found = tooldocs.coverage([tooldocs.Page(Path("demo.md"), text)], ["scripts/old/a.py"], {"demo": {None: []}})
        self.assertEqual(found, [])


class IndexAndNew(unittest.TestCase):
    def test_index_keeps_the_hand_written_intro(self):
        p = tooldocs.Page(Path("demo.md"), GOOD)
        first = tooldocs.render_index([p])
        edited = first.replace("One page per tool", "Hand-written intro. One page per tool")
        again = tooldocs.render_index([p], edited)
        self.assertIn("Hand-written intro", again)
        self.assertIn("[kit demo: a demo tool](demo.md)", again)

    def test_new_page_starts_from_the_template_and_fails_until_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "templates").mkdir()
            for name in ("tool-doc.md", "tool-doc-branch.md"):
                (root / "templates" / name).write_text((ROOT / "templates" / name).read_text(encoding="utf-8"),
                                                       encoding="utf-8")
            path = tooldocs.new_page("fresh-tool", "kit module", root=root)
            text = path.read_text(encoding="utf-8")
            self.assertIn("| Id | `fresh-tool` |", text)
            self.assertIn("| Kind | kit module |", text)
            problems = tooldocs.check_page(tooldocs.Page(path, text), root, {})
            self.assertTrue(any("template guidance" in p for p in problems))
            with self.assertRaises(ValueError):
                tooldocs.new_page("fresh-tool", root=root)
            with self.assertRaises(ValueError):
                tooldocs.new_page("Bad_Id", root=root)


if __name__ == "__main__":
    unittest.main()
