"""Tool docs: every tool has a page in docs/tools/ that follows docs/TOOL-DOCS.md, and each check can fail."""

import argparse
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from kit import tooldocs

ROOT = Path(__file__).resolve().parent.parent
KIT = "python -m " + "kit"   # kept apart so tests/test_repo.py does not read the fixture commands as real ones

MODULE = '''"""A demo tool for the tests."""
import os


def score(x, level="2"):
    """Score x."""
    if not x:
        raise ValueError("the demo input is empty")
    return os.environ.get("DEMO_HOME"), level


def _helper():
    return None
'''

SCRIPT = '''import argparse
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", default=3)
    parser.add_argument("--secret", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.window < 1:
        print("the window must be at least 1", file=sys.stderr)
        return 2
    print("progress line that is not an error", file=sys.stderr)
    return 0
'''


def cmd_demo(args):
    return 0


def parsers():
    p = argparse.ArgumentParser(prog=KIT)
    sub = p.add_subparsers(dest="command")
    d = sub.add_parser("demo", aliases=["dm"], help="demo")
    d.add_argument("path", help="input file")
    d.add_argument("--flag", action="store_true", help="a flag")
    d.add_argument("--level", default="2", help="a level")
    d.set_defaults(func=cmd_demo)
    o = sub.add_parser("other", help="other")
    actions = o.add_subparsers(dest="action")
    go = actions.add_parser("go")
    go.add_argument("--fast", action="store_true")
    actions.add_parser("stop")
    return tooldocs.Commands(p)


COMMANDS = parsers()
USAGE = COMMANDS.parsers["demo"][None].format_usage().strip()

GOOD = f"""# demo: a demo tool for the tests

Does one thing for the test.

| Field | Value |
| --- | --- |
| Id | `demo` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Scoring and controls |
| Run | `{KIT} demo`, `from kit import demo` |
| Code | `kit/demo.py`, `kit/cli.py` (`cmd_demo`) |
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
{KIT} demo FILE --flag
```

## Checks and controls

A control.

Claim label: Model output

## Commands and options

### `{KIT} demo`

```
{USAGE}
```

| Option | Default | Meaning |
| --- | --- | --- |
| `path` | required | Input file |
| `--flag` | off | A flag |
| `--level LEVEL` | `2` | A level |

`DEMO_HOME` is read from the environment.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `score(x, level="2")` | a pair | `ValueError` | Scores x |

## Inputs

None.

## Outputs

Text.

| Exit code | Meaning |
| --- | --- |
| `0` | Done |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `the demo input is empty` | No input | Give one |

## How it works

Simply.

## Cost and time

Not measured.

## For agents

- **Command:** `{KIT} demo FILE`
- **Parse:** the text.
- **Rerun:** safe.
- **Success:** exit 0.
- **Not a pass:** nothing.
- **Go-ahead:** Nothing.
- **Never:** call it a reading.

## Tests

`python -m unittest tests.test_demo`

## History

- 2026-10-16: first version (`abc1234`).

## Related

None.
"""


class Repo:
    """A small repository in a temporary folder with the demo tool."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.write("kit/demo.py", MODULE)
        self.write("kit/cli.py", "def cmd_demo(args):\n    return 0\n")
        self.write("tests/test_demo.py", "from kit import demo\n")
        self.write("scripts/tool.py", SCRIPT)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def page(self, text, name="demo"):
        return tooldocs.Page(self.write(f"docs/tools/{name}.md", text), text)

    def problems(self, text, name="demo", kind="public", pending=(), commands=COMMANDS):
        ctx = tooldocs.Context(self.root, commands, pending, kind, git=False)
        return tooldocs.check_page(self.page(text, name), ctx)


class RepositoryPages(unittest.TestCase):
    def test_every_tool_has_a_page_that_follows_the_standard(self):
        problems = tooldocs.check_all()
        self.assertEqual(problems, [], "\n" + "\n".join(problems[:60]) +
                         f"\n({len(problems)} problems; see docs/TOOL-DOCS.md)")

    def test_index_json_lists_every_page(self):
        data = json.loads((ROOT / "docs" / "tools" / "index.json").read_text(encoding="utf-8"))
        ids = sorted(p.stem for p in (ROOT / "docs" / "tools").glob("*.md") if p.name != "README.md")
        self.assertEqual([t["id"] for t in data["tools"]], ids)

    def test_templates_carry_every_section_and_label(self):
        for name, sections, labels in (("tool-doc.md", tooldocs.SECTIONS, tooldocs.AGENT_LABELS),
                                       ("tool-doc-branch.md", tooldocs.BRANCH_SECTIONS, tooldocs.BRANCH_AGENT_LABELS)):
            text = (ROOT / "templates" / name).read_text(encoding="utf-8")
            for s in sections:
                self.assertIn(f"\n## {s}\n", text, f"{name} lacks ## {s}")
            for label in labels:
                self.assertIn(f"- **{label}:**", text, f"{name} lacks {label}")
            for field in tooldocs.FIELDS:
                self.assertIn(f"| {field} |", text, f"{name} lacks {field}")


class PageShape(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.tmp.cleanup()

    def found(self, text, **kw):
        return " ".join(self.repo.problems(text, **kw))

    def test_good_page_passes(self):
        self.assertEqual(self.repo.problems(GOOD), [])

    def test_missing_out_of_order_duplicate_and_empty_sections(self):
        self.assertIn("missing section '## Failure modes'", self.found(GOOD.replace("## Failure modes\n", "## Troubles\n")))
        a, b = "## Inputs\n\nNone.\n", "## How it works\n\nSimply.\n"
        self.assertIn("out of order", self.found(GOOD.replace(a, "@@").replace(b, a).replace("@@", b)))
        self.assertIn("sections appear twice", self.found(GOOD + "\n## Tests\n\nAgain.\n"))
        self.assertIn("'## How it works' is empty", self.found(GOOD.replace("Simply.\n", "")))

    def test_a_library_may_drop_commands_and_a_command_may_drop_the_api(self):
        start, end = GOOD.index("## Python API"), GOOD.index("## Inputs")
        no_api = GOOD[:start] + GOOD[end:]
        self.assertIn("public `score` of kit/demo.py is not in '## Python API'", self.found(no_api))
        start, end = GOOD.index("## Commands and options"), GOOD.index("## Python API")
        library = GOOD[:start] + GOOD[end:]
        library = library.replace(f"| Run | `{KIT} demo`, `from kit import demo` |", "| Run | `from kit import demo` |")
        library = library.replace("kit command, kit module", "kit module").replace(", `kit/cli.py` (`cmd_demo`)", "")
        library = library.replace("It demonstrates.", "It demonstrates, reading `DEMO_HOME`.")
        self.assertEqual(self.found(library), "")

    def test_not_applicable_is_allowed_only_where_it_can_be(self):
        self.assertEqual(self.found(GOOD.replace("## Inputs\n\nNone.\n", "## Inputs\n\nNot applicable: it reads only its argument.\n")), "")
        self.assertIn("cannot be 'Not applicable'", self.found(GOOD.replace("Simply.", "Not applicable: magic.").replace(
            "## For agents\n", "## For agents\n\nNot applicable: none.\n\n## Spare\n")))
        quick = GOOD.replace(f"```bash\n{KIT} demo FILE --flag\n```", "Not applicable: nothing to run.")
        self.assertIn("'## Quick start' cannot be 'Not applicable'", self.found(quick))

    def test_fields(self):
        text = GOOD.replace("| Network | None |\n", "").replace("| Status | Current |", "| Status | Fine |")
        text = text.replace("| Kind | kit command, kit module |", "| Kind | gadget |").replace(
            "| Area | Scoring and controls |", "| Area | Misc |").replace("| Go-ahead | Not needed |", "| Go-ahead | maybe |")
        found = self.found(text + "")
        for words in ("missing fields ['Network']", "Status 'Fine'", "Kind 'gadget'", "Area 'Misc'", "Go-ahead must start"):
            self.assertIn(words, found)
        self.assertIn("unknown fields ['Colour']", self.found(GOOD.replace("| Network |", "| Colour | red |\n| Network |")))
        swapped = GOOD.replace("| Needs | Python 3.10 |\n", "").replace("| Network | None |", "| Network | None |\n| Needs | Python 3.10 |")
        self.assertIn("fields out of order", self.found(swapped))
        self.assertIn("empty fields ['Needs']", self.found(GOOD.replace("| Needs | Python 3.10 |", "| Needs |  |")))
        self.assertIn("appears twice", self.found(GOOD.replace("| Network | None |", "| Network | None |\n| Network | Some |")))

    def test_id_title_summary_and_checked(self):
        self.assertIn("Id is", self.found(GOOD.replace("| Id | `demo` |", "| Id | `other` |")))
        self.assertIn("an id is lowercase", " ".join(self.repo.problems(GOOD.replace("`demo`", "`Demo_x`"), name="Demo_x")))
        self.assertIn("the title must read", self.found(GOOD.replace("# demo: a demo tool for the tests", "# Demo tool")))
        self.assertIn("no one-sentence summary", self.found(GOOD.replace("Does one thing for the test.\n\n", "")))
        self.assertIn("summary is", self.found(GOOD.replace("Does one thing for the test.", "word " * 80)))
        self.assertIn("Checked must read", self.found(GOOD.replace("2026-10-16 against commit `abc1234`", "today")))
        self.assertIn("not a real date", self.found(GOOD.replace("2026-10-16 against commit", "2026-13-40 against commit")))

    def test_status_and_kind_rules(self):
        retired = GOOD.replace("| Status | Current |", "| Status | Retired |")
        self.assertIn("Replaced by", self.found(retired))
        self.assertEqual(self.found(retired.replace("| Released |", "| Replaced by | Nothing |\n| Released |")), "")
        model = GOOD.replace("kit command, kit module", "kit command, kit module, model")
        self.assertIn("needs the field 'License'", self.found(model))
        self.assertEqual(self.found(model.replace("| Released |", "| License | MIT |\n| Released |")), "")

    def test_branch_only_pages_have_their_own_sections_and_skip_code_checks(self):
        text = (ROOT / "templates" / "tool-doc-branch.md").read_text(encoding="utf-8")
        for key, value in (("{id}", "demo"), ("{kind}", "kit module"), ("{area}", "Training"), ("{date}", "2026-10-16"),
                           ("{commit}", "abc1234"), ("{history_block}", "- 2026-10-01: made (`abc1234`).")):
            text = text.replace(key, value)
        found = self.found(text)
        self.assertIn("template guidance", found)
        no_branch = "\n".join(line for line in text.split("\n") if not line.startswith("| Branch |"))
        self.assertIn("needs the field 'Branch'", self.found(no_branch))
        self.assertNotIn("missing section '## Quick start'", found)
        self.assertNotIn("not in the repository", found)

    def test_a_branch_only_page_whose_commit_has_merged_must_become_current(self):
        text = (ROOT / "templates" / "tool-doc-branch.md").read_text(encoding="utf-8")
        root = self.repo.root

        def git(*args):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args], cwd=root,
                                  capture_output=True, text=True, check=True).stdout.strip()
        try:
            git("init", "-q")
            git("add", "-A")
            git("commit", "-q", "-m", "tool")
            merged = git("rev-parse", "--short", "HEAD")
            git("checkout", "-q", "-b", "side")
            self.repo.write("kit/side.py", "x = 1\n")
            git("add", "-A")
            git("commit", "-q", "-m", "side tool")
            side = git("rev-parse", "--short", "HEAD")
            git("checkout", "-q", "-")
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git is not available")
        ctx = tooldocs.Context(root, COMMANDS, (), "public", git=True)
        for commit, merged_now in ((merged, True), (side, False)):
            page = text
            for key, value in (("{id}", "demo"), ("{kind}", "kit module"), ("{area}", "Training"),
                               ("{date}", "2026-10-16"), ("{commit}", commit),
                               ("{history_block}", f"- 2026-10-01: made (`{commit}`).")):
                page = page.replace(key, value)
            page = "\n".join(f"| Branch | `side` at `{commit}` |" if line.startswith("| Branch |") else line
                             for line in page.split("\n"))
            found = " ".join(tooldocs.check_page(self.repo.page(page), ctx))
            self.assertEqual("which this branch already holds" in found, merged_now, found)

    def test_leftovers_dashes_and_fences(self):
        self.assertIn("template guidance", self.found(GOOD.replace("It demonstrates.", "<!-- Write: what it does -->")))
        self.assertIn("'TODO' is still on the page", self.found(GOOD.replace("It demonstrates.", "TODO later.")))
        inside = GOOD.replace("```bash\n", "```bash\n# TODO <!-- Write: x --> {id}\n", 1)
        self.assertEqual(self.found(inside), "")
        self.assertIn("U+2014", self.found(GOOD.replace("It demonstrates.", "It " + chr(0x2014) + " works.")))
        self.assertIn("never closed", self.found(GOOD + "\n```\nopen\n"))

    def test_headings_inside_code_blocks_do_not_count(self):
        self.assertEqual(self.found(GOOD.replace(f"{KIT} demo FILE --flag\n", f"{KIT} demo FILE --flag\n## Failure modes\n")), "")

    def test_fixed_tables_claim_label_agent_labels_and_quick_start(self):
        self.assertIn("needs a table with the header | What you see",
                      self.found(GOOD.replace("| What you see | Why | What to do |", "| Problem | Fix | Note |")))
        self.assertIn("| Function | Returns | Raises | Notes |",
                      self.found(GOOD.replace("| Function | Returns | Raises | Notes |", "| Function | Notes | A | B |")))
        self.assertIn("exit code table", self.found(GOOD.replace("| Exit code | Meaning |", "| Code | Meaning |")))
        self.assertIn("Claim label", self.found(GOOD.replace("Claim label: Model output\n", "")))
        self.assertIn("is not one of", self.found(GOOD.replace("Claim label: Model output", "Claim label: Vibes")))
        self.assertIn("one bullet per label", self.found(GOOD.replace("- **Rerun:** safe.\n", "")))
        self.assertIn("one bullet per label", self.found(GOOD.replace("- **Parse:** the text.\n- **Rerun:** safe.\n",
                                                                      "- **Rerun:** safe.\n- **Parse:** the text.\n")))
        self.assertIn("```bash block", self.found(GOOD.replace("```bash\n", "```\n", 1)))

    def test_history_bullets(self):
        self.assertIn("does not start with", self.found(GOOD.replace("- 2026-10-16: first", "- Oct 16: first")))
        self.assertIn("names no commit", self.found(GOOD.replace(" (`abc1234`).", ".")))
        self.assertEqual(self.found(GOOD.replace("(`abc1234`)", "([#1](https://example.org/pull/1))")), "")
        self.assertIn("needs dated bullets", self.found(GOOD.replace("- 2026-10-16: first version (`abc1234`).", "First.")))

    def test_links(self):
        self.assertIn("link (nowhere.md) does not resolve", self.found(GOOD.replace("None.\n", "[x](nowhere.md)\n")))
        self.assertEqual(self.found(GOOD.replace("None.\n", "[x](later.md)\n"), pending={"later"}), "")
        self.assertEqual(self.found(GOOD.replace("In tests.", "In tests, `[x](gone.md)`.")), "")
        private = GOOD.replace("In tests.", "See [it](https://github.com/ChaseHendrick/Scrolls-private/blob/x/a.md).")
        self.assertIn("links into Scrolls-private", self.found(private))
        self.assertEqual(self.found(private, kind="private"), "")

    def test_code_paths_symbols_api_errors_and_environment(self):
        self.assertIn("kit/gone.py", self.found(GOOD.replace("`kit/demo.py`", "`kit/gone.py`")))
        self.assertIn("defines no such top-level name", self.found(GOOD.replace("(`cmd_demo`)", "(`cmd_nothing`)")))
        self.assertIn("public `score`", self.found(GOOD.replace("| `score(x, level=\"2\")` |", "| score |")))
        self.assertIn("'the demo input is empty' from kit/demo.py is not in",
                      self.found(GOOD.replace("| `the demo input is empty` | No input | Give one |\n", "")))
        moved = GOOD.replace("| `the demo input is empty` | No input | Give one |\n", "").replace(
            "It demonstrates.", "It says `the demo input is empty` sometimes.")
        self.assertIn("on the page but not in the What you see column of '## Failure modes'", self.found(moved))
        why_only = GOOD.replace("| `the demo input is empty` | No input | Give one |",
                                "| `a different message` | When the demo input is empty | Give one |")
        self.assertIn("not in the What you see column", self.found(why_only))
        self.assertIn("`DEMO_HOME`", self.found(GOOD.replace("`DEMO_HOME` is read", "DEMO_HOME is read")))
        self.assertIn("Tests names 'tests/test_gone.py'", self.found(GOOD.replace("`tests/test_demo.py` |", "`tests/test_gone.py` |")))
        dotted = GOOD.replace("`kit/cli.py` (`cmd_demo`)", "`kit/cli.py` (`cmd_demo`), `kit.demo`")
        self.assertEqual(self.found(dotted), "")

    def test_a_data_page_needs_only_its_paths(self):
        data = GOOD.replace("kit command, kit module", "kit command, data").replace("| Released |", "| License | CC0 |\n| Released |")
        data = data.replace("| `the demo input is empty` | No input | Give one |\n", "").replace("`DEMO_HOME` is read", "It reads")
        self.assertEqual(self.found(data), "")

    def test_script_options_and_errors(self):
        text = GOOD.replace(", `kit/cli.py` (`cmd_demo`)", ", `kit/cli.py` (`cmd_demo`), `scripts/tool.py`")
        found = self.found(text)
        self.assertIn("option `--window` of scripts/tool.py", found)
        self.assertNotIn("--secret", found)
        self.assertIn("'the window must be at least 1'", found)
        self.assertNotIn("progress line", found)
        text = text.replace("| `--level LEVEL` | `2` | A level |",
                            "| `--level LEVEL` | `2` | A level |\n\n### `scripts/tool.py`\n\n| Option | Default | Meaning |\n"
                            "| --- | --- | --- |\n| `--window N` | `3` | Window |")
        text = text.replace("| Give one |", "| Give one |\n| `the window must be at least 1` | Too small | Use 3 |")
        self.assertEqual(self.found(text), "")


SPACE_SCRIPT = '''import argparse
import sys

DEFAULT_SIZE = 256


def common(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--local", action="store_true")
    g.add_argument("--space", default="me/space")
    p.add_argument("--windows", type=int, default=3, choices=(1, 3))


def parser():
    ap = argparse.ArgumentParser(prog="lens")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate")
    e.add_argument("height", type=int)
    e.add_argument("width", type=int)
    f = sub.add_parser("fetch")
    f.add_argument("reader", choices=["a", "b"])
    r = sub.add_parser("run")
    r.add_argument("--size", type=int, default=DEFAULT_SIZE)
    r.add_argument("--box", type=int, nargs=4, metavar=("X", "Y", "W", "H"))
    for p in (e, r):
        p.add_argument("--json", action="store_true")
    common(r)
    return ap


def main(argv=None):
    a = parser().parse_args(argv)
    if a.cmd == "run" and a.size < 128:
        raise SystemExit(f"size {a.size}: use 128 to {DEFAULT_SIZE} px")
    if a.cmd == "fetch":
        raise ValueError("not a PNG")
    try:
        return 0
    except OSError as exc:
        print(f"lens: {exc}", file=sys.stderr)
        return 2
'''

SHELL_SCRIPT = '''#!/bin/bash
case "$MODE" in
  a|b) ;;
  *) echo "MODE must be a or b, not $MODE" >&2; exit 2 ;;
esac
if busy; then
  echo "Another run holds the lock (pid $pid)." >&2
  echo "Wait for it, or stop it" >&2
  exit 3
fi
echo "progress: still working on it" >&2
echo "file $f has sha256 $got, expected $want; move it aside" >&2; exit 1
printf 'cannot write %s here\\n' "$out" >&2
exit 4
'''


def lens_section(parser_obj):
    """Commands and options for SPACE_SCRIPT, with usage blocks pasted from the real parser."""
    subs = next(a for a in parser_obj._actions if isinstance(a, argparse._SubParsersAction)).choices
    return (f"### `spaces/lens/lens.py`\n\n```\n{parser_obj.format_usage().strip()}\n```\n\n"
            f"### `spaces/lens/lens.py estimate`\n\n```\n{subs['estimate'].format_usage().strip()}\n```\n\n"
            "| Option | Default | Meaning |\n| --- | --- | --- |\n| `HEIGHT` | required | Rows |\n| `WIDTH` | required | Columns |\n"
            "| `--json` | off | JSON |\n\n"
            f"### `spaces/lens/lens.py fetch`\n\n```\n{subs['fetch'].format_usage().strip()}\n```\n\n"
            "| Option | Default | Meaning |\n| --- | --- | --- |\n| `READER` | required | a or b |\n\n"
            f"### `spaces/lens/lens.py run`\n\n```\n{subs['run'].format_usage().strip()}\n```\n\n"
            "| Option | Default | Meaning |\n| --- | --- | --- |\n| `--size` | `256` | Side |\n| `--box X Y W H` | none | Box |\n"
            "| `--json` | off | JSON |\n| `--local` | off | Here |\n| `--space` | `me/space` | Space |\n| `--windows` | `3` | Windows |\n\n")


class CheckerExtensions(unittest.TestCase):
    """The checks added on 2026-10-21: bare kit usage, shell messages, static argparse reading, whole messages."""

    def setUp(self):
        self.repo = Repo()
        self.repo.write("spaces/lens/lens.py", SPACE_SCRIPT)
        self.repo.write("scripts/run.sh", SHELL_SCRIPT)
        ns = {}
        exec(compile(SPACE_SCRIPT, "lens.py", "exec"), ns)
        self.section = lens_section(ns["parser"]())

    def tearDown(self):
        self.repo.tmp.cleanup()

    def found(self, text):
        return " ".join(self.repo.problems(text))

    def lens_page(self):
        text = GOOD.replace(", `kit/cli.py` (`cmd_demo`)", ", `kit/cli.py` (`cmd_demo`), `spaces/lens/lens.py`")
        text = text.replace("`DEMO_HOME` is read from the environment.", self.section + "`DEMO_HOME` is read from the environment.")
        return text.replace("| Give one |", "| Give one |\n| `size N: use 128 to MAX px` | Too small | Use 128 or more |\n"
                                              "| `not a PNG` | Not a PNG | Give a PNG |")

    def test_bare_kit_usage_and_a_row_for_every_command(self):
        usage = COMMANDS.top.format_usage().strip()
        text = GOOD.replace(f"| Run | `{KIT} demo`,", f"| Run | `{KIT}`, `{KIT} demo`,")
        section = (f"### `{KIT}`\n\n```\n{usage}\n```\n\n| Command | Page |\n| --- | --- |\n| `demo` | here |\n"
                   "| `other` | there |\n\n")
        text = text.replace(f"### `{KIT} demo`\n", section + f"### `{KIT} demo`\n")
        self.assertEqual(self.found(text), "")
        self.assertIn(f"command `other` of `{KIT}` has no row", self.found(text.replace("| `other` | there |\n", "")))
        self.assertIn(f"the usage block under '### `{KIT}`' differs from --help",
                      self.found(text.replace(usage, usage.replace("[-h]", "[--help]"))))
        self.assertIn(f"no '### `{KIT}`' heading", self.found(text.replace(f"### `{KIT}`\n", "### Commands\n")))

    def test_shell_messages_before_a_failing_exit(self):
        self.assertEqual(tooldocs.sh_error_messages(SHELL_SCRIPT),
                         ["MODE must be a or b, not", "Another run holds the lock (pid", "Wait for it, or stop it",
                          "; move it aside", "cannot write"])
        parts = tooldocs.sh_error_messages(SHELL_SCRIPT, parts=True)
        self.assertIn(["cannot write ", " here", " ", " "], parts)
        self.assertTrue(tooldocs.message_in(parts[3], "file PATH has sha256 GOT, expected WANT; move it aside"))
        text = GOOD.replace(", `kit/cli.py` (`cmd_demo`)", ", `kit/cli.py` (`cmd_demo`), `scripts/run.sh`")
        found = self.found(text)
        self.assertIn("error message 'MODE must be a or b, not' from scripts/run.sh is not in", found)
        self.assertNotIn("progress", found)
        rows = ("| `MODE must be a or b, not M`, exit code 2 | Wrong mode | Use a or b |\n"
                "| `Another run holds the lock (pid P).` then `Wait for it, or stop it`, exit code 3 | Busy | Wait |\n"
                "| `file PATH has sha256 GOT, expected WANT; move it aside`, exit code 1 | Changed | Move it |\n"
                "| `cannot write OUT here`, exit code 4 | Read-only | Pick another folder |\n")
        self.assertEqual(self.found(text.replace("| Give one |\n", "| Give one |\n" + rows)), "")

    def test_argparse_read_without_running(self):
        import ast
        parsers, complete = tooldocs.argparse_parsers(ast.parse(SPACE_SCRIPT))
        self.assertTrue(complete)
        self.assertEqual([p.label for p in parsers], ["lens", "lens estimate", "lens fetch", "lens run"])
        run = parsers[3]
        self.assertEqual([a.name for a in run.args], ["--size", "--box", "--json", "--local", "--space", "--windows"])
        self.assertEqual(run.args[0].default(), 256)
        self.assertEqual(run.args[2].default(), False)
        self.assertEqual(parsers[0].subcommands, ["estimate", "fetch", "run"])
        self.assertEqual(parsers[2].args[0].usage_names(), ("{a,b}",))
        partial = tooldocs.argparse_parsers(ast.parse("ap = make()\nap.add_argument('--a')\n"))
        self.assertEqual(partial, ([], False))

    def test_positionals_defaults_and_usage_of_scripts_and_spaces(self):
        good = self.lens_page()
        self.assertEqual(self.found(good), "")
        self.assertIn("positional `height` of spaces/lens/lens.py estimate has no row",
                      self.found(good.replace("| `HEIGHT` | required | Rows |\n", "")))
        self.assertIn("default of `--size` in spaces/lens/lens.py run is `256` in the code",
                      self.found(good.replace("| `--size` | `256` |", "| `--size` | `512` |")))
        self.assertIn("option `--windows` of spaces/lens/lens.py has no row",
                      self.found(good.replace("| `--windows` | `3` | Windows |\n", "")))
        self.assertIn("the usage block for `lens run` lacks `--json`", self.found(good.replace("[--json]", "", 2)))
        self.assertIn("the usage block for `lens run` names `--gone`",
                      self.found(good.replace("usage: lens run [-h]", "usage: lens run [-h] [--gone]")))
        self.assertIn("lists the subcommands {estimate,run}",
                      self.found(good.replace("{estimate,fetch,run}", "{estimate,run}")))
        self.assertIn("lacks the positional `height`",
                      self.found(good.replace("usage: lens estimate [-h] [--json] height width",
                                              "usage: lens estimate [-h] [--json] width")))

    def test_whole_messages_with_placeholders(self):
        import ast
        tree = ast.parse(SPACE_SCRIPT)
        self.assertEqual(tooldocs.error_messages([tree], parts=True), [["size ", ": use 128 to ", " px"], ["not a PNG"]])
        self.assertEqual(tooldocs.error_messages([tree]), [": use 128 to", "not a PNG"])   # "lens: " is too short
        self.assertTrue(tooldocs.message_in(["size ", ": use 128 to ", " px"], "`size N: use 128 to MAX px`"))
        self.assertFalse(tooldocs.message_in(["size ", ": use 128 to ", " px"], "`: use 128 to`"))
        self.assertFalse(tooldocs.message_in(["size ", ": use 128 to ", " px"], "`px` then `size N: use 128 to`"))
        good = self.lens_page()
        fragment = good.replace("| `size N: use 128 to MAX px` |", "| `: use 128 to` |")
        self.assertIn("error message 'size...: use 128 to...px' from spaces/lens/lens.py is not in", self.found(fragment))
        self.assertIn("error message 'not a PNG'", self.found(good.replace("| `not a PNG` | Not a PNG | Give a PNG |", "")))
        block = tooldocs.failures_block(self.repo.root, [("spaces/lens/lens.py", [])], False)
        self.assertIn("| `size...: use 128 to...px` |", block)


class CommandChecks(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.tmp.cleanup()

    def found(self, text):
        return " ".join(self.repo.problems(text))

    def test_options_in_the_usage_block_alone_are_not_enough(self):
        text = GOOD.replace("| `--flag` | off | A flag |\n", "")
        self.assertIn("option `--flag` of `" + KIT + " demo` has no row", self.found(text))
        self.assertIn("positional `path`", self.found(GOOD.replace("| `path` | required | Input file |\n", "")))

    def test_usage_block_must_match_the_parser(self):
        self.assertIn("differs from --help", self.found(GOOD.replace("[--flag]", "[--flags]")))
        rewrapped = GOOD.replace(USAGE, " ".join(USAGE.split()))
        self.assertEqual(self.found(rewrapped), "")

    def test_defaults_must_match_the_code(self):
        self.assertIn("default of `--level`", self.found(GOOD.replace("| `--level LEVEL` | `2` |", "| `--level LEVEL` | `3` |")))
        self.assertIn("default of `--flag`", self.found(GOOD.replace("| `--flag` | off |", "| `--flag` | on |")))
        self.assertIn("default of `path`", self.found(GOOD.replace("| `path` | required |", "| `path` | none |")))

    def test_unknown_option_rows_are_caught(self):
        text = GOOD.replace("| `--flag` | off | A flag |", "| `--flag` | off | A flag |\n| `--gone` | off | Removed |")
        self.assertIn("row `--gone`", self.found(text))

    def test_unknown_commands_actions_and_missing_headings(self):
        text = GOOD.replace(f"| Run | `{KIT} demo`,", f"| Run | `{KIT} nosuch`, `{KIT} other halt`, `{KIT} demo`,")
        found = self.found(text)
        self.assertIn(f"`{KIT} nosuch`, which is not a kit command", found)
        self.assertIn("not an action of other", found)
        family = self.found(GOOD.replace(f"| Run | `{KIT} demo`,", f"| Run | `{KIT} demo`, `{KIT} other`,"))
        self.assertIn(f"no '### `{KIT} other go`' heading", family)
        self.assertIn(f"no '### `{KIT} other stop`' heading", family)

    def test_aliases_and_positionals_resolve_to_the_command(self):
        self.assertEqual(self.found(GOOD.replace(f"| Run | `{KIT} demo`,", f"| Run | `{KIT} dm`, `{KIT} demo w035`,")), "")


class Coverage(unittest.TestCase):
    PAGE = tooldocs.Page(Path("demo.md"), GOOD)

    def found(self, files, pages=None, releases=(), pending=None):
        return " ".join(tooldocs.coverage(pages or [self.PAGE], files, COMMANDS, releases, pending))

    def test_everything_without_a_page_is_caught(self):
        files = ["kit/demo.py", "kit/cli.py", "kit/newtool.py", "kit/_helper.py", "kit/pkg/__init__.py",
                 "scripts/newscript.py", "scripts/old/a.py", ".claude/skills/s/SKILL.md", ".github/workflows/ci.yml",
                 "pyproject.toml"]
        found = self.found(files, releases=["fresh"])
        for name in ("kit/newtool.py", "kit/_helper.py has no tool page: name", "kit/pkg", "scripts/newscript.py",
                     "scripts/old", ".claude/skills/s", ".github/workflows/ci.yml", "pyproject.toml",
                     f"`{KIT} other go`", f"`{KIT} other stop`", "entry 'fresh'"):
            self.assertIn(name, found)
        self.assertNotIn("kit/demo.py has no", found)
        self.assertNotIn("kit/cli.py", found)
        self.assertNotIn(f"`{KIT} demo`", found)

    def test_a_folder_covers_its_files_but_kit_does_not_cover_every_module(self):
        folder = tooldocs.Page(Path("demo.md"), GOOD.replace("`kit/demo.py`", "`kit/demo.py`, `scripts/old/`"))
        self.assertNotIn("scripts/old", self.found(["scripts/old/a.py"], [folder]))
        wide = tooldocs.Page(Path("demo.md"), GOOD.replace("`kit/demo.py`", "`kit/demo.py`, `kit/`"))
        self.assertIn("kit/newtool.py", self.found(["kit/newtool.py"], [wide]))
        scoped = tooldocs.Page(Path("demo.md"), GOOD.replace("(`cmd_demo`)", "(`cmd_demo`), `kit/newtool.py` (`f`)"))
        self.assertIn("kit/newtool.py", self.found(["kit/newtool.py"], [scoped]))

    def test_a_release_is_covered_by_the_page_id_or_its_release_id(self):
        self.assertNotIn("entry 'demo'", self.found([], releases=["demo"]))
        tagged = tooldocs.Page(Path("demo.md"), GOOD.replace("| Released |", "| Release id | `demo-tool` |\n| Released |"))
        self.assertNotIn("entry 'demo-tool'", self.found([], [tagged], releases=["demo-tool"]))

    def test_tools_in_a_grouped_release_need_pages_too(self):
        repo = Repo()
        self.addCleanup(repo.tmp.cleanup)
        repo.write("docs/releases.json", json.dumps({"schema_version": 1, "releases": [
            {"id": "solo"}, {"id": "demo-kit", "tools": [{"id": "demo"}, {"id": "lone-cmd"}]}]}))
        ids = tooldocs.releases_ids(repo.root)
        self.assertEqual(ids, ["solo", "demo-kit", "demo", "lone-cmd"])
        found = self.found([], releases=ids)
        self.assertIn("entry 'lone-cmd'", found)
        self.assertNotIn("entry 'demo'", found)
        repo.write("docs/releases.json", "not json")
        self.assertEqual(tooldocs.releases_ids(repo.root), [])

    def test_pending_suppresses_until_the_page_exists_and_then_must_shrink(self):
        pending = {"newtool": {"covers": ["kit/newtool.py", f"{KIT} other go", f"{KIT} other stop"]}}
        self.assertEqual(self.found(["kit/newtool.py"], pending=pending), "")
        self.assertIn("lists 'demo', which now has a page", self.found([], pending={"demo": {"covers": []}}))
        self.assertIn("no longer needs a page", self.found([], pending={"x": {"covers": ["kit/gone.py"]}}))
        self.assertIn("which a page now covers", self.found(["kit/demo.py"], pending={"x": {"covers": ["kit/demo.py"]}}))

    def test_uncovered_lists_the_targets(self):
        self.assertEqual(tooldocs.uncovered([self.PAGE], ["kit/demo.py", "kit/x.py"], COMMANDS),
                         ["kit/x.py", f"{KIT} other go", f"{KIT} other stop"])


class IndexAndNew(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        for name in ("tool-doc.md", "tool-doc-branch.md"):
            self.repo.write(f"templates/{name}", (ROOT / "templates" / name).read_text(encoding="utf-8"))

    def tearDown(self):
        self.repo.tmp.cleanup()

    def test_index_keeps_the_hand_written_intro_and_groups_by_area(self):
        p = tooldocs.Page(Path("demo.md"), GOOD)
        first = tooldocs.render_index([p])
        self.assertIn("### Scoring and controls", first)
        edited = first.replace("One page per tool", "Hand-written intro. One page per tool")
        again = tooldocs.render_index([p], edited)
        self.assertIn("Hand-written intro", again)
        self.assertIn("| [demo](demo.md) | Current |", again)

    def test_index_json_has_sections_with_line_ranges(self):
        page = self.repo.page(GOOD)
        data = json.loads(tooldocs.render_json([page], self.repo.root, "public"))
        self.assertEqual(data["schema_version"], tooldocs.SCHEMA_VERSION)
        self.assertEqual(data["repo"], "Scrolls")
        tool = data["tools"][0]
        self.assertEqual(tool["commands"], [f"{KIT} demo"])
        self.assertEqual(tool["imports"], ["from kit import demo"])
        self.assertEqual(tool["code"][1], {"path": "kit/cli.py", "symbols": ["cmd_demo"]})
        self.assertFalse(tool["go_ahead"]["needed"])
        lines = GOOD.splitlines()
        section = next(s for s in tool["sections"] if s["name"] == "For agents")
        self.assertEqual(lines[section["start_line"] - 1], "## For agents")
        self.assertTrue(lines[section["end_line"] - 1].startswith("- **Never:**") or not lines[section["end_line"] - 1])

    def test_write_index_refuses_a_readme_without_markers_and_check_all_sees_a_stale_index(self):
        self.repo.page(GOOD)
        self.assertEqual(tooldocs.write_index(self.repo.root), 1)
        self.assertNotIn("out of date", " ".join(tooldocs.check_all(self.repo.root, commands=COMMANDS)))
        self.repo.page(GOOD.replace("Does one thing", "Does another thing"))
        self.assertIn("README.md is out of date", " ".join(tooldocs.check_all(self.repo.root, commands=COMMANDS)))
        self.repo.write("docs/tools/README.md", "hand written\n")
        with self.assertRaises(ValueError):
            tooldocs.write_index(self.repo.root)

    def test_new_page_is_prefilled_from_the_code_and_fails_until_written(self):
        path = tooldocs.new_page("demo", "kit command, kit module", root=self.repo.root, area="Scoring and controls",
                                 commands=["demo"], code=["kit/demo.py"], command_parser=COMMANDS)
        text = path.read_text(encoding="utf-8")
        self.assertIn("| Id | `demo` |", text)
        self.assertIn(f"| Run | `{KIT} demo` |", text)
        self.assertIn("| Code | `kit/demo.py`, `kit/cli.py` (`cmd_demo`) |", text)
        self.assertIn("| Tests | `tests/test_demo.py` |", text)
        self.assertIn(USAGE.split("\n")[0], text)
        self.assertIn("| `--level LEVEL` | `2` | a level |", text)
        self.assertIn("| `score(x, level='2')` |", text)
        self.assertIn("| `the demo input is empty` |", text)
        self.assertIn("| `DEMO_HOME` |", text)
        problems = " ".join(self.repo.problems(text))
        self.assertIn("template guidance", problems)
        for absent in ("differs from --help", "has no row", "default of", "not in '## Failure modes'",
                       "not in '## Python API'", "is not on the page in code"):
            self.assertNotIn(absent, problems)

    def test_new_page_skips_a_command_whose_func_is_a_lambda(self):
        p = argparse.ArgumentParser(prog=KIT)
        sub = p.add_subparsers(dest="command")
        sub.add_parser("demo").set_defaults(func=lambda a: 0)
        path = tooldocs.new_page("demo", "kit command", root=self.repo.root, area="Scoring and controls",
                                 commands=["demo"], command_parser=tooldocs.Commands(p))
        self.assertNotIn("<lambda>", path.read_text(encoding="utf-8"))

    def test_new_page_refuses_bad_input(self):
        tooldocs.new_page("fresh-tool", "kit module", root=self.repo.root, code=["kit/demo.py"])
        for kwargs in ({"page_id": "fresh-tool"}, {"page_id": "Bad_Id"}, {"page_id": "x", "kind": "gadget"},
                       {"page_id": "x", "area": "Misc"}, {"page_id": "x", "code": ["kit/gone.py"]},
                       {"page_id": "x", "status": "Fine"}):
            with self.assertRaises(ValueError):
                tooldocs.new_page(root=self.repo.root, **kwargs)


class CommandLine(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tooldocs.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes(self):
        self.assertEqual(self.run_main("check", "--page", "no-such-page")[0], 1)
        self.assertEqual(self.run_main("show", "no-such-page")[0], 2)
        code, out, _ = self.run_main("list", "--json")
        self.assertEqual(code, 0)
        ids = [t["id"] for t in json.loads(out)["tools"]]
        if not ids:
            self.skipTest("no tool pages yet")
        pid = ids[0]
        code, out, _ = self.run_main("check", "--page", pid)
        self.assertEqual((code, out.strip()), (0, f"tool docs pass (pages {pid})"))
        self.assertEqual(self.run_main("show", pid, "--section", "No such section")[0], 2)
        code, out, _ = self.run_main("show", pid, "--section", "For agents")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("## For agents\n"))
        self.assertIn("- **Never:**", out)
        code, out, _ = self.run_main("show", pid, "--field", "Id")
        self.assertEqual((code, out.strip()), (0, f"`{pid}`"))


class CodeScanners(unittest.TestCase):
    def test_environment_variables(self):
        import ast
        tree = ast.parse("import os\nNAME = 'B_VAR'\nos.environ.get('A_VAR')\nos.environ[NAME]\nos.getenv('C_VAR', 1)\n"
                         "os.environ.setdefault('lower', 1)\n")
        self.assertEqual(tooldocs.env_names_py(tree), ["A_VAR", "B_VAR", "C_VAR"])
        self.assertEqual(tooldocs.env_names_sh('W="${WORK:-/tmp}"\nX=${EXPECT_GPU:=mps}\necho $PLAIN\n'),
                         ["WORK", "EXPECT_GPU"])

    def test_defaults_render_as_the_page_writes_them(self):
        self.assertEqual(tooldocs._value([]), "none")
        self.assertEqual(tooldocs._value(""), "none")
        self.assertEqual(tooldocs._value(("a", "b")), "a b")
        self.assertEqual(tooldocs._value(str(tooldocs.ROOT / "docs" / "results.json")), "docs/results.json")
        self.assertEqual(tooldocs._value("/elsewhere/x.json"), "/elsewhere/x.json")
        self.assertTrue(tooldocs._default_ok("none (an empty list)", tooldocs._value([])))

    def test_a_constant_named_in_code_is_scanned_without_error(self):
        import ast
        tree = ast.parse("import os\nNAME = 'B_VAR'\nLEVEL = 2\ndef f():\n    return os.environ.get(NAME)\n")
        scope = tooldocs._scoped(tree, ["LEVEL", "f"])
        self.assertEqual([e for t in scope for e in tooldocs.env_names_py(t, tooldocs._constants(tree))], ["B_VAR"])
        self.assertEqual(tooldocs.env_names_py(scope[0]), [])

    def test_error_messages(self):
        import ast
        tree = ast.parse(
            "import sys\n"
            "def f(p, parser):\n"
            "    if p:\n"
            "        raise ValueError(f'cannot read {p}: it is missing')\n"
            "    try:\n"
            "        pass\n"
            "    except OSError:\n"
            "        print('could not open the store', file=sys.stderr)\n"
            "    print('loading the volume now', file=sys.stderr)\n"
            "    parser.error('give --crop with --surface-shape')\n"
            "    sys.exit('the run has no readout rule')\n")
        self.assertEqual(sorted(tooldocs.error_messages([tree])),
                         [": it is missing", "could not open the store", "give --crop with --surface-shape",
                          "the run has no readout rule"])


if __name__ == "__main__":
    unittest.main()
