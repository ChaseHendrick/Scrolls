"""Tool docs: one page per tool under docs/tools/, written to docs/TOOL-DOCS.md and checked against the code.

  python -m kit.tooldocs check [--page ID ...] [--json]   every page, the index and coverage, or only the pages
                                             named (quick, while you write); exit 1 on any problem. A unit test
                                             runs the full check.
  python -m kit.tooldocs index               rewrite the generated table in docs/tools/README.md and docs/tools/index.json
  python -m kit.tooldocs list [--json]       every tool: id, status, area, how to run it, one-line summary
  python -m kit.tooldocs show ID [--section NAME | --field NAME]   one page, one of its sections or one field
  python -m kit.tooldocs new ID --kind K --area A [--command "CMD [ACTION]" ...] [--code PATH ...] [--status S]
                                             start docs/tools/ID.md from the template, prefilled from the code:
                                             usage lines, option tables with defaults, public functions, error
                                             messages, environment variables, tests and history
  python -m kit.tooldocs stale               pages whose main code file changed after the page did (a report; exit 0)

What check enforces is listed, with the reasons, in docs/TOOL-DOCS.md ("What the checker checks"). In short:
the page's shape (title, summary, the At a glance fields in order, the sections in order, the fixed table headers,
the For agents labels, the claim label, dated History bullets with a commit or link), that every path, symbol,
commit and link it names exists, that every option, positional argument and default of each kit command it runs
matches the parser, that every public function, error message and environment variable of the code it names is on
the page, and that every kit module, script, command, release, skill and workflow has a page (docs/tools/pending.json
lists pages still to be written; it can only shrink).

Standard library only. Scrolls-private carries a copy of this module; keep the two the same.
"""

import argparse
import ast
import difflib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

__all__ = ["Page", "Commands", "Context", "kit_commands", "check_page", "check_all", "coverage", "coverage_targets",
           "uncovered", "load_pages", "load_pending", "render_index", "render_json", "write_index", "stale", "new_page",
           "main"]

ROOT = Path(__file__).resolve().parent.parent
STANDARD = "docs/TOOL-DOCS.md"
SCHEMA_VERSION = 1

FIELDS = ("Id", "Status", "Kind", "Area", "Run", "Code", "Tests", "Needs", "Runs on", "Network", "Writes",
          "Go-ahead", "Released", "Checked")
OPTIONAL_FIELDS = ("Guide", "License", "Replaced by", "Branch", "Public page", "Release id")
STATUSES = ("Current", "Experimental", "Retired", "Branch only")
KINDS = ("kit command", "kit module", "kit entry point", "script", "script folder", "agent tool", "app", "model",
         "package", "skill", "patch", "workflow", "data")
RUNNABLE = ("kit command", "kit entry point", "script", "script folder")
LICENSED = ("model", "app", "package", "data")
AREAS = ("Pipeline and agents", "Data and downloads", "Surfaces and tracing", "Ink maps and models",
         "Scoring and controls", "Letters and titles", "Training", "Compute and cost", "Records and provenance",
         "Planning and prizes", "Releases and repository", "Viewers and apps")
CLAIM_LABELS = ("Sourced fact", "Organizer result", "Community report", "Model output", "Null",
                "Candidate (private)", "Interpretation", "Untested idea", "None")
SECTIONS = ("What it does", "When to use it", "Quick start", "Checks and controls", "Commands and options",
            "Inputs", "Outputs", "Failure modes", "How it works", "Cost and time", "For agents", "Tests",
            "History", "Related")
# A library has a Python API where a command has options; a page may have both, in that order.
ALTERNATIVES = {"Commands and options": ("Commands and options", "Python API")}
BRANCH_SECTIONS = ("What it does", "Where the code is", "How to run it", "Inputs and outputs",
                   "Why it is not on the default branch", "For agents", "History", "Related")
NEVER_NOT_APPLICABLE = ("What it does", "When to use it", "For agents", "History", "Related", "Where the code is",
                        "Why it is not on the default branch")
AGENT_LABELS = ("Command", "Parse", "Rerun", "Success", "Not a pass", "Go-ahead", "Never")
BRANCH_AGENT_LABELS = ("Revive", "Check first", "Never")
HEADERS = {
    "Failure modes": "| What you see | Why | What to do |",
    "Python API": "| Function | Returns | Raises | Notes |",
}
EXIT_HEADER = "| Exit code | Meaning |"
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
CHECKED_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) against commit `([0-9a-f]{7,40})`")
BRANCH_RE = re.compile(r"`([^`]+)` at `([0-9a-f]{7,40})`")
HISTORY_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}): ")
HEXSPAN = re.compile(r"`[0-9a-f]{7,40}`")
NOT_APPLICABLE = re.compile(r"^Not applicable: \S.*\.$")
SUMMARY_MAX = 300
LEFTOVER = "<!-- Write:"
PROSE_LEFTOVERS = re.compile(r"\b(TODO|TBD|FIXME|XXX)\b|\{(id|kind|status|area|date)\}")
START = "<!-- tooldocs:start (generated by python -m kit.tooldocs index; do not edit by hand) -->"
END = "<!-- tooldocs:end -->"
KIT_RUN = re.compile(r"^python3? -m kit ([a-z0-9][a-z0-9-]*)(?: ([a-z0-9][a-z0-9-]*))?")
ENTRY_RUN = re.compile(r"^python3? -m (kit\.[a-z0-9_]+)\b")
SCRIPT_RUN = re.compile(r"^(?:python3? |bash |sh |\./)?(scripts/[^\s`]+)")
PATHLIKE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./*-]*$")
FILE_SUFFIX = re.compile(r"\.(py|sh|md|json|jsonl|ya?ml|toml|txt|cfg|html|js|css|csv|tsv|ipynb|cff)$")
FENCE = re.compile(r"^(`{3,}|~{3,}).*?^\1[`~]*[ \t]*$", re.S | re.M)
SPAN = re.compile(r"`([^`\n]+)`")
CODE_ITEM = re.compile(r"`([^`\n]+)`(?:\s*\(([^()]*)\))?")
MD_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
AGENT_LINE = re.compile(r"^- \*\*([^*]+?):\*\*")
CLAIM_LINE = re.compile(r"^(?:- )?Claim label: (.+)$", re.M)
DASHES = (chr(0x2014), chr(0x2013))
MIN_MESSAGE = 9

INTRO = """# Tool pages

One page per tool, current, retired or only on another branch, written to the standard in
[`../TOOL-DOCS.md`](../TOOL-DOCS.md) and checked against the code by `python -m kit.tooldocs check`, which the tests
run. Every page answers the same questions under the same headings, in the same order: what the tool does, when to
use it, a quick start, the checks and controls that let its result fail, every command and option, inputs, outputs,
failure modes, how it works, cost and time, rules for agents, tests, history and related tools.

For agents: `python -m kit.tooldocs list --json` (or [`index.json`](index.json)) lists every tool with its status,
area, entry points, code, side effects and the line range of each section, `python -m kit.tooldocs show ID` prints a
page and `python -m kit.tooldocs show ID --section "For agents"` prints one section.

The tables below are generated from the pages by `python -m kit.tooldocs index`; edit the pages, never the tables.
"""


# ---------------------------------------------------------------- parsing


def _collapse(text):
    return " ".join(text.split())


def _cells(row):
    """Cells of one Markdown table row; a `\\|` inside a cell is a literal pipe."""
    parts = re.split(r"(?<!\\)\|", row.strip())
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [p.strip().replace("\\|", "|") for p in parts]


def _is_path(span):
    return bool(PATHLIKE.match(span)) and ("/" in span or bool(FILE_SUFFIX.search(span)))


class Page:
    """One parsed tool page."""

    def __init__(self, path, text):
        self.path = Path(path)
        self.text = text
        self.problems = []
        self.title = ""
        self.summary = ""
        self.fields = {}
        self.order = []
        self.sections = []
        self.bodies = {}
        self.lines = {}
        self.unclosed_fence = False
        self._parse()

    @property
    def id(self):
        return self.path.stem

    def field(self, name):
        return self.fields.get(name, "")

    def spans(self, name):
        return SPAN.findall(self.field(name))

    def code_items(self):
        """[(path, [symbols])] from the Code field: `PATH` optionally followed by (`SYM`, `SYM`)."""
        items = []
        for m in CODE_ITEM.finditer(self.field("Code")):
            if _is_path(m.group(1)):
                items.append((m.group(1), SPAN.findall(m.group(2) or "")))
        return items

    def runs(self):
        return [s for s in self.spans("Run") if not s.startswith(("from ", "import "))]

    def body(self, name):
        return "\n".join(self.bodies.get(name, []))

    def _parse(self):
        lines = FENCE.sub("", self.text).splitlines()
        if not lines or not lines[0].startswith("# "):
            self.problems.append("the first line is not a '# Title' heading")
        else:
            self.title = lines[0][2:].strip()
        para, i = [], 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(("|", "#")):
            para.append(lines[i].strip())
            i += 1
        self.summary = " ".join(para)
        while i < len(lines) and not lines[i].lstrip().startswith("|") and not lines[i].startswith("## "):
            i += 1
        rows = []
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            rows.append(lines[i].strip())
            i += 1
        if len(rows) < 2 or _cells(rows[0]) != ["Field", "Value"]:
            self.problems.append("no 'At a glance' table with the header | Field | Value | after the summary")
        elif not re.match(r"^\|?\s*:?-{3,}:?\s*\|\s*:?-{3,}:?\s*\|?$", rows[1]):
            self.problems.append("the At a glance table needs | --- | --- | under its header")
        else:
            for row in rows[2:]:
                cells = _cells(row)
                if len(cells) != 2:
                    self.problems.append(f"table row {row[:60]!r} does not have exactly two cells "
                                         "(write a | inside a value as \\|)")
                    continue
                name, value = cells
                if name in self.fields:
                    self.problems.append(f"field {name!r} appears twice")
                self.fields[name] = value
                self.order.append(name)
        # Sections, their bodies and line numbers, from the full text: a heading inside a fenced block is not a
        # heading, but the block belongs to its section.
        current, fence = None, None
        for n, line in enumerate(self.text.splitlines(), 1):
            marker = re.match(r"^(`{3,}|~{3,})", line)
            if fence is None and line.startswith("## "):
                current = line[3:].strip()
                self.sections.append(current)
                self.bodies.setdefault(current, [])
                self.lines.setdefault(current, [n, n])
                continue
            if marker:
                if fence is None:
                    fence = marker.group(1)[0] * 3
                elif line.startswith(fence):
                    fence = None
            if current is not None:
                self.bodies[current].append(line)
                self.lines[current][1] = n
        self.unclosed_fence = fence is not None

    def prose(self):
        """The page without fenced blocks and code spans."""
        return SPAN.sub("", FENCE.sub("", self.text))

    def code_text(self):
        """Everything inside code spans and fenced blocks."""
        blocks = [m.group(0) for m in FENCE.finditer(self.text)]
        return "\n".join(blocks + SPAN.findall(FENCE.sub("", self.text)))

    def subsections(self, section):
        """[(heading line, [body lines])] for each ### under a ## section."""
        out = []
        for line in self.bodies.get(section, []):
            if line.startswith("### "):
                out.append((line[4:].strip(), []))
            elif out:
                out[-1][1].append(line)
        return out


def _table_rows(lines):
    """[(cells)] of every table row in these lines, header and separator rows left out."""
    rows, header = [], None
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            header = None
            continue
        cells = _cells(s)
        if header is None:
            header = cells
            continue
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def _tables(lines):
    """[(header cells, [row cells])] of each table in these lines, separator rows left out."""
    tables, current = [], None
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            current = None
            continue
        cells = _cells(s)
        if current is None:
            current = (cells, [])
            tables.append(current)
        elif not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            current[1].append(cells)
    return tables


def _has_header(lines, header):
    want = _cells(header)
    return any(_cells(line) == want for line in lines if line.strip().startswith("|"))


def _not_applicable(page, name):
    body = [l for l in page.bodies.get(name, []) if l.strip()]
    return len(body) == 1 and bool(NOT_APPLICABLE.match(body[0].strip()))


# ---------------------------------------------------------------- the code side


class Commands:
    """kit's parser: canonical command -> {None: parser, action: parser}, and alias -> canonical name."""

    def __init__(self, parser):
        self.top = parser
        subs = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        self.parsers, self.aliases, seen = {}, {}, {}
        for name, sub in subs.choices.items():
            canon = seen.setdefault(id(sub), name)
            self.aliases[name] = canon
            if canon != name:
                continue
            entry = {None: sub}
            for act in sub._actions:
                if isinstance(act, argparse._SubParsersAction):
                    for aname, asub in act.choices.items():
                        entry.setdefault(aname, asub)
            self.parsers[name] = entry

    def target(self, span):
        """(canonical command, action or None) for a `python -m kit ...` span, or None."""
        m = KIT_RUN.match(span)
        if not m or m.group(1) not in self.aliases:
            return None
        command, action = self.aliases[m.group(1)], m.group(2)
        actions = self.parsers[command]
        if action and action not in actions and list(actions) == [None]:
            action = None          # a positional argument, such as `python -m kit fetch w035 DEST`
        return command, action


def kit_commands():
    from . import cli
    build = getattr(cli, "build_parser", None) or getattr(cli, "_parser")
    return Commands(build())


def _arguments(parser):
    """(name, action, positional) for every documented argument of a parser."""
    out = []
    for act in parser._actions:
        if isinstance(act, (argparse._HelpAction, argparse._SubParsersAction)) or act.help == argparse.SUPPRESS:
            continue
        if act.option_strings:
            longs = [s for s in act.option_strings if s.startswith("--")]
            out.append(((longs or act.option_strings)[0], act, False))
        else:
            out.append((act.metavar if isinstance(act.metavar, str) else act.dest, act, True))
    return out


def render_default(act, positional=False):
    """How the Default cell shows an argument's default: required, off, on, none, or the value in code."""
    if positional:
        return "required" if act.nargs in (None, "+") or isinstance(act.nargs, int) else _value(act.default)
    if act.required:
        return "required"
    if isinstance(act, argparse._StoreTrueAction):
        return "off"
    if isinstance(act, argparse._StoreFalseAction):
        return "on"
    return _value(act.default)


def _value(default):
    """A default as the page writes it: none for None, "" or an empty list; a path inside the checkout relative to it."""
    if default is None or default == argparse.SUPPRESS or default == "" or (isinstance(default, (list, tuple)) and not default):
        return "none"
    if isinstance(default, (list, tuple)):
        return " ".join(str(v) for v in default)
    if isinstance(default, (str, Path)) and Path(default).is_absolute():
        try:
            return Path(default).relative_to(ROOT).as_posix()
        except ValueError:
            pass
    return str(default)


def _default_ok(cell, expected):
    if expected in ("required", "off", "on", "none"):
        return cell.lower().startswith(expected) or (SPAN.findall(cell)[:1] == [expected])
    spans = SPAN.findall(cell)
    return bool(spans) and spans[0] == expected


def _module_tree(root, rel):
    try:
        return ast.parse((root / rel).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None


def _scoped(tree, symbols):
    """The top-level nodes named in symbols, or the whole module when there are none."""
    if not symbols:
        return [tree]
    return [n for n in tree.body if getattr(n, "name", None) in symbols
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in symbols for t in n.targets))]


def top_names(tree):
    names = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
    return names


def public_api(tree):
    """Public functions and classes: __all__ when the module sets it, else top-level names without a leading _."""
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "__all__" for t in n.targets):
            try:
                return [str(v) for v in ast.literal_eval(n.value)]
            except ValueError:
                break
    return [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not n.name.startswith("_")]


def _literal_fragment(node):
    """The longest literal stretch of a str constant or an f-string, or ''."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        parts = [node.value]
    elif isinstance(node, ast.JoinedStr):
        parts, cur = [], ""
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                cur += v.value
            else:
                parts.append(cur)
                cur = ""
        parts.append(cur)
    else:
        return ""
    return max((p.strip() for p in parts), key=len, default="")


def _literal_parts(node):
    """The literal stretches of a str constant or an f-string, in order, with a placeholder between each two; []
    for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if not isinstance(node, ast.JoinedStr):
        return []
    parts, cur = [], ""
    for v in node.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            cur += v.value
        else:
            parts.append(cur)
            cur = ""
    parts.append(cur)
    return parts


def message_in(parts, text):
    """True when a message's literal stretches (whitespace collapsed) appear in text in order, anything (an option
    value, a path, NAME) between them: how a page writes a message with placeholders."""
    pos = 0
    for word in (_collapse(p) for p in parts):
        if not word:
            continue
        at = text.find(word, pos)
        if at < 0:
            return False
        pos = at + len(word)
    return True


def _is_stderr_print(node):
    return (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print" and node.args
            and any(k.arg == "file" and isinstance(k.value, ast.Attribute) and k.value.attr == "stderr"
                    for k in node.keywords))


def _ends_badly(stmt):
    """True for `return N` with N a nonzero int, `sys.exit(...)`, `raise ...`, or `exit(...)`."""
    if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Constant):
        return isinstance(stmt.value.value, int) and not isinstance(stmt.value.value, bool) and stmt.value.value != 0
    if isinstance(stmt, ast.Raise):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        f = stmt.value.func
        return (isinstance(f, ast.Attribute) and f.attr == "exit") or getattr(f, "id", "") in ("exit", "quit")
    return False


def error_messages(trees, parts=False):
    """Literal fragments of the messages a failure shows: raise X("..."), sys.exit("..."), parser.error("..."),
    and print(..., file=sys.stderr) inside an except block or right before a nonzero return, an exit or a raise.
    A message counts when its literal text adds up to MIN_MESSAGE characters. With parts=True, each message is the
    list of its literal stretches (for message_in) instead of its longest stretch."""
    found = []

    def add(arg):
        stretches = _literal_parts(arg)
        if len("".join(stretches).strip()) < MIN_MESSAGE:
            return
        item = stretches if parts else _literal_fragment(arg)
        if item not in found:
            found.append(item)

    for tree in trees:
        for n in ast.walk(tree):
            if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) and n.exc.args:
                add(n.exc.args[0])
            elif isinstance(n, ast.Call) and n.args and isinstance(n.func, ast.Attribute):
                f = n.func
                owner = getattr(f.value, "id", "")
                if f.attr == "exit" and owner == "sys":
                    add(n.args[0])
                elif f.attr == "error" and (owner.endswith("parser") or owner in ("ap", "p", "argp")):
                    add(n.args[0])
            for field in ("body", "orelse", "finalbody", "handlers"):
                stmts = getattr(n, field, None)
                if not isinstance(stmts, list):
                    continue
                in_except = isinstance(n, ast.ExceptHandler) and field == "body"
                for i, stmt in enumerate(stmts):
                    if isinstance(stmt, ast.Expr) and _is_stderr_print(stmt.value):
                        nxt = stmts[i + 1] if i + 1 < len(stmts) else None
                        if in_except or (nxt is not None and _ends_badly(nxt)):
                            add(stmt.value.args[0])
    return found


def _constants(tree):
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = n.value.value
    return out


def env_names_py(tree, consts=None):
    """Environment variables read with os.environ or os.getenv; consts maps module constants to their strings."""
    if consts is None:
        consts = _constants(tree) if isinstance(getattr(tree, "body", None), list) else {}
    names = []

    def name_of(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return consts.get(node.id)
        return None

    for n in ast.walk(tree):
        key = None
        if isinstance(n, ast.Call) and n.args:
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr in ("get", "setdefault", "pop") \
                    and isinstance(f.value, ast.Attribute) and f.value.attr == "environ":
                key = name_of(n.args[0])
            elif isinstance(f, ast.Attribute) and f.attr == "getenv":
                key = name_of(n.args[0])
        elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute) and n.value.attr == "environ":
            key = name_of(n.slice if not isinstance(n.slice, ast.Index) else n.slice.value)  # ast.Index on 3.8
        if key and re.fullmatch(r"[A-Z][A-Z0-9_]*", key) and key not in names:
            names.append(key)
    return names


def env_names_sh(text):
    names = []
    for m in re.finditer(r"\$\{([A-Z][A-Z0-9_]*):?[-=]", text):
        if m.group(1) not in names:
            names.append(m.group(1))
    return names


def _sh_parts(arg):
    """The literal stretches of shell words, in order, split where a $VAR, ${...} or $(...) expansion stands."""
    parts, cur, i, quote = [], "", 0, None
    while i < len(arg):
        c = arg[i]
        if quote != "'" and c == "\\" and i + 1 < len(arg):
            cur += arg[i + 1]
            i += 2
            continue
        if c in "\"'" and quote in (None, c):
            quote = None if quote == c else c
            i += 1
            continue
        if c == "$" and quote != "'" and i + 1 < len(arg):
            nxt = arg[i + 1]
            if nxt in "{(":
                close, depth, j = "}" if nxt == "{" else ")", 0, i + 1
                while j < len(arg):
                    if arg[j] == nxt:
                        depth += 1
                    elif arg[j] == close:
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                i = j + 1
            else:
                m = re.match(r"[A-Za-z_][A-Za-z0-9_]*|[0-9#?@*!$-]", arg[i + 1:])
                i += 1 + (len(m.group(0)) if m else 0)
            parts.append(cur)
            cur = ""
            continue
        cur += c
        i += 1
    parts.append(cur)
    return parts


SH_COMMAND = re.compile(r"(?:^|[;{&|()]\s*|\b(?:then|else|do)\s+)(echo|printf)\s+(?:-[ne]+\s+)?")
SH_EXIT = re.compile(r"(?:^|[;{&|]\s*|\bthen\s+)exit\s+([1-9][0-9]*)\b")


def _sh_stderr_echoes(line):
    """(arguments, end, is printf) of each echo or printf in a shell line whose output goes to stderr (`>&2`)."""
    out = []
    for m in SH_COMMAND.finditer(line):
        i, quote = m.end(), None
        while i < len(line):
            c = line[i]
            if quote:
                if c == "\\" and quote == '"':
                    i += 2
                    continue
                if c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == "\\":
                i += 2
                continue
            elif line.startswith(">&2", i) or line.startswith("1>&2", i):
                out.append((line[m.end():i], i + (3 if line[i] == ">" else 4), m.group(1) == "printf"))
                break
            elif c in ";|&}\n" or line.startswith(">", i):
                break
            i += 1
    return out


def sh_error_messages(text, parts=False):
    """Literal fragments of the messages a shell script prints on stderr just before it exits nonzero: an
    `echo ... >&2` (or printf) with `exit N` later on the same line, or followed only by more stderr lines and
    then a line that starts with `exit N`. With parts=True, each is the list of its literal stretches."""
    lines = [l.strip() for l in text.splitlines()]
    found = []
    for i, line in enumerate(lines):
        if line.startswith("#"):
            continue
        for args, stop, printf in _sh_stderr_echoes(line):
            after = line[stop:]
            ends = bool(SH_EXIT.search(after))
            j = i + 1
            while not ends and j < len(lines):
                nxt = lines[j]
                if not nxt or nxt.startswith("#"):
                    j += 1
                    continue
                if SH_EXIT.match(nxt):
                    ends = True
                elif ">&2" in nxt and not SH_EXIT.search(nxt):
                    j += 1           # more of the same message, such as a second line or a log's tail
                    continue
                break
            if ends:
                stretches = _sh_parts(args)
                if printf:           # a format string: %s and the like stand for values, \n ends a line
                    stretches = [s for part in stretches
                                 for s in re.split(r"%[-+ #0]*[0-9]*(?:\.[0-9]+)?[a-zA-Z]|\\[nt]", part)]
                if len("".join(stretches).strip()) < MIN_MESSAGE:
                    continue
                item = stretches if parts else max((s.strip() for s in stretches), key=len, default="")
                if item not in found:
                    found.append(item)
    return found


def script_options(tree):
    """Long options a script's argparse code defines (add_argument("--x", ...)), hidden ones left out."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_argument":
            if any(k.arg == "help" and isinstance(k.value, ast.Attribute) and k.value.attr == "SUPPRESS"
                   for k in n.keywords):
                continue
            for a in n.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith("--") \
                        and a.value not in out:
                    out.append(a.value)
    return out


# ---------------------------------------------------------------- argparse read statically (scripts, entry points)


UNREAD = object()      # a value the checker cannot read without running the code


class StaticArg:
    """One add_argument call as written: option strings or a positional, and what the code says of it."""

    def __init__(self, strings, kw):
        self.strings = tuple(strings)
        self.positional = bool(strings) and not strings[0].startswith("-")
        self.kw = kw
        dest = kw.get("dest")
        if not isinstance(dest, str):
            dest = strings[0] if self.positional else \
                next((s for s in strings if s.startswith("--")), strings[0] if strings else "").lstrip("-")
            dest = dest.replace("-", "_") if not self.positional else dest
        self.dest = dest
        self.suppressed = kw.get("help") is argparse.SUPPRESS

    @property
    def options(self):
        return () if self.positional else self.strings

    @property
    def shown(self):
        """The names usage shows for a positional: its metavar (or each of a tuple of them), else its dest."""
        mv = self.kw.get("metavar")
        if isinstance(mv, str):
            return (mv,)
        if isinstance(mv, tuple) and all(isinstance(m, str) for m in mv):
            return mv
        return (self.dest,)

    def usage_names(self):
        """What usage shows for a positional: {a,b} for literal choices without a metavar, else shown; () when the
        checker cannot tell."""
        choices = self.kw.get("choices")
        if self.kw.get("metavar") is None and choices is not None:
            if isinstance(choices, (list, tuple)):
                return ("{" + ",".join(str(c) for c in choices) + "}",)
            return ()
        return self.shown

    @property
    def name(self):
        if self.positional:
            return self.shown[0]
        return next((s for s in self.strings if s.startswith("--")), self.strings[0] if self.strings else "")

    def default(self):
        """The default as code: UNREAD when the checker cannot tell; for a flag, False or True."""
        action = self.kw.get("action")
        if action in ("store_true", "store_false") and "default" not in self.kw:
            return action == "store_false"
        return self.kw.get("default")


class StaticParser:
    """One parser found in a file: its program name, its subcommand path and its arguments in order."""

    def __init__(self, prog, path=(), add_help=True):
        self.prog = prog
        self.path = tuple(path)
        self.args = []
        self.subcommands = []
        self.add_help = add_help

    @property
    def label(self):
        return " ".join([self.prog or "?", *self.path])


def _literal_value(node, consts):
    if node is None:
        return None
    if isinstance(node, ast.Attribute) and node.attr == "SUPPRESS":
        return argparse.SUPPRESS
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return UNREAD


def _literal_constants(tree):
    """Module-level names bound once to a literal (str, number, tuple, list, bool, None)."""
    out, seen = {}, set()
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            name = n.targets[0].id
            if name in seen:
                out.pop(name, None)
                continue
            seen.add(name)
            try:
                out[name] = ast.literal_eval(n.value)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                pass
    return out


def argparse_parsers(tree):
    """The argparse parsers a module builds, read without running it: ([StaticParser], complete). Parsers made with
    ArgumentParser() and add_subparsers().add_parser(), arguments added through groups and through local helper
    functions that receive a parser, and loops over a literal tuple are followed. complete is False when some
    add_argument call could not be tied to a parser, so a usage comparison would be unsafe."""
    consts = _literal_constants(tree)
    parsers = []
    state = {"complete": True}
    module_funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    done = {}

    def new_parser(call, parent=None, name=None):
        kw = {k.arg: k.value for k in call.keywords if k.arg}
        if parent is None:
            p_prog = _literal_value(kw.get("prog"), consts)
            p = StaticParser(p_prog if isinstance(p_prog, str) else None,
                             add_help=_literal_value(kw.get("add_help"), consts) is not False)
        else:
            p = StaticParser(parent.prog, parent.path + (name,),
                             add_help=_literal_value(kw.get("add_help"), consts) is not False)
            parent.subcommands.append(name)
        if "parents" in kw and isinstance(kw["parents"], (ast.List, ast.Tuple)):
            state["complete"] = False          # inherited arguments are not followed
        parsers.append(p)
        return ("parser", p)

    def evaluate(node, env, funcs, depth):
        if not isinstance(node, ast.Call):
            return None
        f = node.func
        if isinstance(f, ast.Attribute):
            if f.attr == "ArgumentParser" and getattr(f.value, "id", "") == "argparse":
                return new_parser(node)
            if isinstance(f.value, ast.Call):
                handle = evaluate(f.value, env, funcs, depth)
            else:
                handle = env.get(f.value.id) if isinstance(f.value, ast.Name) else None
            if handle == "param":          # a helper's parameter: followed when a caller passes a parser
                return "param" if f.attr in ("add_argument_group", "add_mutually_exclusive_group", "add_subparsers",
                                             "add_parser") else None
            if handle is None:
                if f.attr == "add_argument":
                    state["complete"] = False
                return None
            kind, p = handle
            if kind == "parser" and f.attr == "add_subparsers":
                return ("subs", p)
            if kind == "subs" and f.attr == "add_parser" and node.args:
                name = _literal_value(node.args[0], consts)
                if not isinstance(name, str):
                    state["complete"] = False
                    return None
                return new_parser(node, p, name)
            if kind in ("parser", "group") and f.attr in ("add_argument_group", "add_mutually_exclusive_group"):
                return ("group", p)
            if kind in ("parser", "group") and f.attr == "add_argument":
                strings = [_literal_value(a, consts) for a in node.args]
                if not strings or not all(isinstance(s, str) for s in strings):
                    state["complete"] = False
                    return None
                kw = {k.arg: _literal_value(k.value, consts) for k in node.keywords if k.arg}
                p.args.append(StaticArg(strings, kw))
            return None
        if isinstance(f, ast.Name):
            if f.id == "ArgumentParser":
                return new_parser(node)
            fn = funcs.get(f.id)
            handles = [env.get(a.id) if isinstance(a, ast.Name) else None for a in node.args]
            if fn is None or depth >= 6:
                return None
            if any(isinstance(h, tuple) for h in handles):
                params = [a.arg for a in fn.args.args]
                inner = dict(env)
                for pname, h in zip(params, handles):
                    inner[pname] = h if isinstance(h, tuple) else None
                return run(fn.body, inner, dict(funcs), depth + 1)
            return once(fn, env if fn not in module_funcs.values() else {}, funcs, depth + 1)
        return None

    def once(fn, env, funcs, depth):
        """A function called without a parser argument runs once; later calls get the parser it returned."""
        if id(fn) not in done:
            done[id(fn)] = None
            inner = dict(env)
            inner.update({a.arg: "param" for a in fn.args.args})
            done[id(fn)] = run(fn.body, inner, dict(funcs), depth)
        return done[id(fn)]

    def run(stmts, env, funcs, depth):
        returned = None
        for st in stmts:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs[st.name] = st
            elif isinstance(st, ast.ClassDef):
                continue
            elif isinstance(st, ast.Assign):
                h = evaluate(st.value, env, funcs, depth)
                for t in st.targets:
                    if isinstance(t, ast.Name):
                        env[t.id] = h
            elif isinstance(st, (ast.AnnAssign, ast.AugAssign)) and isinstance(st.target, ast.Name):
                env[st.target.id] = evaluate(st.value, env, funcs, depth) if st.value is not None else None
            elif isinstance(st, ast.Expr):
                evaluate(st.value, env, funcs, depth)
            elif isinstance(st, ast.Return):
                h = evaluate(st.value, env, funcs, depth) if isinstance(st.value, ast.Call) else \
                    (env.get(st.value.id) if isinstance(st.value, ast.Name) else None)
                returned = returned or (h if isinstance(h, tuple) else None)
            elif isinstance(st, ast.For):
                items = st.iter.elts if isinstance(st.iter, (ast.Tuple, ast.List)) else None
                if isinstance(st.target, ast.Name) and items is not None:
                    for item in items:
                        env[st.target.id] = env.get(item.id) if isinstance(item, ast.Name) else None
                        returned = run(st.body, env, funcs, depth) or returned
                else:
                    returned = run(st.body, env, funcs, depth) or returned
                returned = run(st.orelse, env, funcs, depth) or returned
            elif isinstance(st, (ast.If, ast.While)):
                returned = run(st.body, env, funcs, depth) or returned
                returned = run(st.orelse, env, funcs, depth) or returned
            elif isinstance(st, (ast.With, ast.AsyncWith)):
                returned = run(st.body, env, funcs, depth) or returned
            elif isinstance(st, ast.Try):
                for block in (st.body, *[h.body for h in st.handlers], st.orelse, st.finalbody):
                    returned = run(block, env, funcs, depth) or returned
        return returned

    run(tree.body, {}, dict(module_funcs), 0)
    for fn in module_funcs.values():
        once(fn, {}, dict(module_funcs), 0)
    return parsers, state["complete"]


def _progs(rel, prog):
    """How a usage line may spell the program of a file: its prog when the code sets one, else the names argparse
    and the pages use for a script (foo.py, scripts/foo.py, python scripts/foo.py) or an entry point."""
    if prog:
        return [prog.split()]
    out = [[Path(rel).name], [rel], ["python", rel], ["python3", rel]]
    if rel.startswith("kit/"):
        mod = "kit." + Path(rel).stem if Path(rel).name != "__main__.py" else "kit." + Path(rel).parent.name
        out += [["python", "-m", mod], ["python3", "-m", mod]]
    return out


def usage_blocks(lines):
    """Every usage block pasted in fenced code in these lines: 'usage: ...' and its indented continuation lines."""
    blocks, cur, fence = [], None, None
    for line in lines:
        m = re.match(r"^\s*(`{3,}|~{3,})", line)
        if m:
            fence = None if fence else m.group(1)[0]
            if cur:
                blocks.append(" ".join(cur))
                cur = None
            continue
        if not fence:
            continue
        s = line.strip()
        if s.startswith("usage:"):
            if cur:
                blocks.append(" ".join(cur))
            cur = [s[len("usage:"):].strip()]
        elif cur is not None and s and line[:1] in (" ", "\t"):
            cur.append(s)
        elif cur is not None:
            blocks.append(" ".join(cur))
            cur = None
    if cur:
        blocks.append(" ".join(cur))
    return blocks


def _usage_parser(block, candidates):
    """The (parser, spelled program) a usage block belongs to: the longest program spelling it starts with."""
    tokens = block.split()
    best = None
    for p, spellings in candidates:
        for sp in spellings:
            full = sp + list(p.path)
            if tokens[:len(full)] == full and (best is None or len(full) > best[2]):
                best = (p, " ".join(full), len(full))
    return best[:2] if best else None


def _word_in(word, text):
    return re.search(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", text) is not None


def compare_usage(block, parser, spelled):
    """Problems with one pasted usage block against the parser it names: options it lacks or names wrongly,
    positionals it lacks, and a list of subcommands that differs."""
    problems = []
    body = block.split(None, len(spelled.split()))[-1] if len(block.split()) > len(spelled.split()) else ""
    shown = set(re.findall(r"(?<![\w-])(--?[A-Za-z][\w-]*)", body))
    known = {s for a in parser.args for s in a.options}
    if parser.add_help:
        known |= {"-h", "--help"}
    for opt in sorted(shown - known):
        problems.append(f"the usage block for `{spelled}` names `{opt}`, which it does not define")
    for a in parser.args:
        if a.suppressed:
            continue
        if a.options and not set(a.options) & shown:
            problems.append(f"the usage block for `{spelled}` lacks `{a.name}`; paste `{spelled} --help`'s usage")
        elif a.positional and not all(_word_in(n, body) or n in body for n in a.usage_names()):
            problems.append(f"the usage block for `{spelled}` lacks the positional `{a.shown[0]}`")
    m = re.search(r"\{([\w.,-]+)\}", body)
    if parser.subcommands and m:
        listed = m.group(1).split(",")
        if sorted(listed) != sorted(parser.subcommands):
            problems.append(f"the usage block for `{spelled}` lists the subcommands {{{m.group(1)}}}; the code has "
                            f"{{{','.join(parser.subcommands)}}}")
    return problems


def _default_text(value):
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _number(token):
    try:
        return float(token)
    except ValueError:
        return None


def static_default_ok(cell, value):
    """True when a Default cell shows a literal default from the code: the value as a code span or a word, a number
    equal to it, every item of a list, off for a flag that defaults to False and on for one that defaults to True."""
    plain = cell.replace("`", " ")
    if value is False:
        return not cell.lower().startswith("on")
    if value is True:
        return cell.lower().startswith("on") or "on" in plain.lower().split()
    numbers = [n for n in (_number(t.strip(",;()")) for t in plain.split()) if n is not None]
    for item in _default_text(value):
        if _word_in(item, plain) or item in SPAN.findall(cell):
            continue
        n = _number(item)
        if n is not None and any(abs(n - x) <= 1e-12 * max(1.0, abs(n)) for x in numbers):
            continue
        return False
    return True


def _positional_row(rows, arg):
    """The row whose first cell names the positional (its metavar or dest, any case) as a word of a code span, not
    inside an option such as `--name`."""
    names = {n.lower() for n in arg.shown} | {arg.dest.lower()}
    for row in rows:
        for span in SPAN.findall(row[0] if row else ""):
            words = {w.strip("[](){}<>,.|:").lower() for w in span.split() if not w.lstrip("[").startswith("-")}
            if names & words:
                return row
    return None


def _option_row(rows, arg):
    for row in rows:
        for span in SPAN.findall(row[0] if row else ""):
            if any(re.search(r"(?<![\w-])" + re.escape(s) + r"(?![\w-])", span) for s in arg.options):
                return row
    return None


FILE_WORD = re.compile(r"[\w./-]+\.(?:py|sh)")


def _file_names(rel):
    """The ways a page names this file: its path, its file name and, for kit/, its module."""
    names = [rel, Path(rel).name]
    if rel.startswith("kit/"):
        names.append("kit." + (Path(rel).stem if Path(rel).name != "__main__.py" else Path(rel).parent.name))
    return names


def _named_files(text):
    """The script files (`*.py`, `*.sh`) the code spans of a heading or table cell name, in order, by file name."""
    out = []
    for span in SPAN.findall(text):
        for word in span.split():
            word = word.strip("[](){}<>,.|:")
            if FILE_WORD.fullmatch(word) and Path(word).name not in out:
                out.append(Path(word).name)
    return out


def _owned_rows(heading, rows, rel):
    """The rows under one heading that may hold a positional of this file. A row whose first cell names a script
    file belongs to that file. A row that names no file belongs to the first file the heading names, or to any
    file when the heading names none; so when one heading names several files, the positional of any file but
    the first needs a row that names its file."""
    me = Path(rel).name
    listed = _named_files(heading)
    out = []
    for row in rows:
        named = _named_files(row[0]) if row else []
        if me in named or (not named and (not listed or listed[0] == me)):
            out.append(row)
    return out


def _all_owned_rows(page, rel):
    """Every row under '## Commands and options' that may hold a positional of this file, heading by heading."""
    body = page.bodies.get("Commands and options", [])
    top = []
    for line in body:
        if line.startswith("### "):
            break
        top.append(line)
    rows = _owned_rows("", _table_rows(top), rel)
    for h, b in page.subsections("Commands and options"):
        rows += _owned_rows(h, _table_rows(b), rel)
    return rows


def _rows_for(page, rel, path, positional=False):
    """The table rows under the '### ...' headings that name this file (and its subcommand, when the headings say),
    and True; or every row under '## Commands and options' and False when no heading names it. With positional,
    only the rows that may hold this file's positionals (see _owned_rows)."""
    names = _file_names(rel)
    mine = [(h, b) for h, b in page.subsections("Commands and options")
            if any(re.search(r"(?<![\w./-])" + re.escape(n) + r"(?![\w/-])", h) for n in names)]
    if path:
        narrowed = [(h, b) for h, b in mine if all(_word_in(x, h) for x in path)]
        mine = narrowed or mine
    if mine:
        if positional:
            return [r for h, b in mine for r in _owned_rows(h, _table_rows(b), rel)], True
        return _table_rows([line for _, b in mine for line in b]), True
    if positional:
        return _all_owned_rows(page, rel), False
    return _table_rows(page.bodies.get("Commands and options", [])), False


def _check_static_parsers(page, rel, label, tree):
    """Positional rows, literal defaults and pasted usage blocks of a script's or entry point's argparse code."""
    problems = []
    parsers, complete = argparse_parsers(tree)
    if not parsers:
        return problems
    every = _table_rows(page.bodies.get("Commands and options", []))
    every_owned = _all_owned_rows(page, rel)
    for p in parsers:
        rows, scoped = _rows_for(page, rel, p.path)
        owned, _ = _rows_for(page, rel, p.path, positional=True)
        for a in p.args:
            if a.suppressed:
                continue
            row = _positional_row(owned, a) if a.positional else _option_row(rows, a)
            if row is None and scoped:
                row = _positional_row(every_owned, a) if a.positional else None
                scoped = scoped if row is None else False
            elif not scoped and not a.positional and sum(_option_row([r], a) is not None for r in every) > 1:
                continue          # the option has rows for several tools and no heading says which is this one
            if a.positional and row is None:
                where = f"{label} {' '.join(p.path)}".strip()
                problems.append(f"positional `{a.shown[0]}` of {where} has no row in a table under "
                                "'## Commands and options'")
                continue
            if row is None or len(row) < 2:
                continue
            value = a.default()
            if value is UNREAD or value is None or value is argparse.SUPPRESS or value == "" or \
                    (a.positional and a.kw.get("nargs") not in ("?", "*")):
                continue
            if a.kw.get("action") in ("store_true", "store_false") and "default" in a.kw:
                continue
            if not static_default_ok(row[1], value):
                shown = ("on" if value else "off") if isinstance(value, bool) else " ".join(_default_text(value))
                where = f"{label} {' '.join(p.path)}".strip()
                problems.append(f"default of `{a.name}` in {where} is `{shown}` in the code; the page says "
                                f"{row[1][:40]!r}")
    if complete:
        candidates = [(p, _progs(rel, p.prog)) for p in parsers]
        for block in usage_blocks(page.bodies.get("Commands and options", [])):
            found = _usage_parser(block, candidates)
            if found:
                problems += compare_usage(block, *found)
    return problems


# ---------------------------------------------------------------- git


def _git(root, *args):
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return out


def git_usable(root):
    """True when commits can be looked up: git works and the clone is not shallow (CI clones at depth 1)."""
    out = _git(root, "rev-parse", "--is-shallow-repository")
    return out is not None and out.returncode == 0 and out.stdout.strip() == "false"


def commit_exists(root, rev):
    out = _git(root, "cat-file", "-e", f"{rev}^{{commit}}")
    return out is not None and out.returncode == 0


def in_history(root, rev):
    """True when commit rev is HEAD or one of its ancestors, so its changes are on the checked-out branch."""
    out = _git(root, "merge-base", "--is-ancestor", rev, "HEAD")
    return out is not None and out.returncode == 0


def repo_kind(root):
    out = _git(root, "remote", "get-url", "origin")
    if out is None or out.returncode != 0:
        return None
    return "private" if "scrolls-private" in out.stdout.lower() else "public"


def tracked(root=ROOT):
    out = _git(root, "ls-files", "--cached", "--others", "--exclude-standard")
    if out is not None and out.returncode == 0:
        files = [f for f in out.stdout.split("\n") if f]
    else:
        files = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    return [f for f in files if (root / f).exists()
            and not any(part == "__pycache__" or (part.startswith(".") and part not in (".claude", ".github"))
                        for part in f.split("/"))]


# ---------------------------------------------------------------- checks


class Context:
    """What a page check needs besides the page: the repository and the code."""

    def __init__(self, root=ROOT, commands=None, pending=(), kind=None, git=False):
        self.root = Path(root)
        self.commands = commands
        self.pending = set(pending)
        self.kind = kind
        self.git = git


def check_page(page, ctx):
    """Problems with one page, each a short sentence."""
    problems = list(page.problems)
    status = page.field("Status")
    kinds = [k.strip() for k in page.field("Kind").split(",") if k.strip()]
    runnable = any(k in RUNNABLE for k in kinds)
    branch_only = status == "Branch only"
    if not ID_RE.fullmatch(page.id):
        problems.append(f"file name {page.path.name!r}: an id is lowercase letters, digits and hyphens")
    if page.title and not re.match(r"^\S.*: \S", page.title):
        problems.append("the title must read `# NAME: what it does in a few words`")
    if not page.summary:
        problems.append("no one-sentence summary between the title and the table")
    elif len(page.summary) > SUMMARY_MAX:
        problems.append(f"the summary is {len(page.summary)} characters; keep it to {SUMMARY_MAX} (one sentence)")
    problems += _check_fields(page, ctx, kinds, status)
    prose = page.prose()
    if LEFTOVER in prose:
        problems.append(f"template guidance ({LEFTOVER} ...) is still on the page; replace it with the text")
    m = PROSE_LEFTOVERS.search(prose)
    if m:
        problems.append(f"{m.group(0)!r} is still on the page; finish that part")
    for ch in DASHES:
        if ch in page.text:
            problems.append(f"the page has U+{ord(ch):04X}; use plain sentences, commas or 'to' (style rule)")
    if page.unclosed_fence:
        problems.append("a code block opened with ``` or ~~~ is never closed")
    dupes = sorted({s for s in page.sections if page.sections.count(s) > 1})
    if dupes:
        problems.append(f"sections appear twice: {dupes}")
    problems += _check_sections(page, kinds, runnable, branch_only)
    problems += _check_links(page, ctx)
    if not branch_only:
        problems += _check_code(page, ctx, detail="data" not in kinds)
        if ctx.commands is not None:
            problems += _check_runs(page, ctx)
    return problems


def _check_fields(page, ctx, kinds, status):
    problems = []
    if not page.fields:
        return problems
    unknown = [f for f in page.order if f not in FIELDS + OPTIONAL_FIELDS]
    if unknown:
        problems.append(f"unknown fields {unknown}; allowed: {list(FIELDS + OPTIONAL_FIELDS)}")
    missing = [f for f in FIELDS if f not in page.fields]
    if missing:
        problems.append(f"missing fields {missing}")
    present = [f for f in page.order if f in FIELDS]
    if not missing and present != list(FIELDS):
        problems.append(f"fields out of order; the order is {list(FIELDS)}")
    empty = [f for f in page.order if not page.fields.get(f)]
    if empty:
        problems.append(f"empty fields {empty}; write 'None' and why when there is nothing")
    if "Id" in page.fields and page.spans("Id") != [page.id]:
        problems.append(f"Id is {page.field('Id')!r}; write `{page.id}`, the file name without .md")
    if status and status not in STATUSES:
        problems.append(f"Status {status!r} is not one of {list(STATUSES)}")
    for kind in kinds:
        if kind not in KINDS:
            problems.append(f"Kind {kind!r} is not one of {list(KINDS)}")
    area = page.field("Area")
    if area and area not in AREAS:
        problems.append(f"Area {area!r} is not one of {list(AREAS)}")
    go = page.field("Go-ahead")
    if go and not go.startswith(("Not needed", "Needed")):
        problems.append("Go-ahead must start with 'Not needed' or 'Needed'")
    checked = page.field("Checked")
    if checked:
        m = CHECKED_RE.match(checked)
        if not m:
            problems.append("Checked must read `YYYY-MM-DD against commit `HASH`` (the commit you read)")
        else:
            try:
                date.fromisoformat(m.group(1))
            except ValueError:
                problems.append(f"Checked date {m.group(1)} is not a real date")
            if ctx.git and not commit_exists(ctx.root, m.group(2)):
                problems.append(f"Checked names commit {m.group(2)}, which is not in this repository")
    if any(k in LICENSED for k in kinds) and not page.field("License"):
        problems.append(f"a page of kind {', '.join(k for k in kinds if k in LICENSED)} needs the field 'License'")
    if status == "Retired" and not page.field("Replaced by"):
        problems.append("a Retired tool needs the field 'Replaced by' (write 'Nothing' if nothing replaced it)")
    if status == "Branch only":
        branch = page.field("Branch")
        m = BRANCH_RE.search(branch)
        if not m:
            problems.append("a Branch only tool needs the field 'Branch': `BRANCH` at `COMMIT`")
        elif ctx.git and not commit_exists(ctx.root, m.group(2)):
            problems.append(f"Branch names commit {m.group(2)}, which is not in this repository "
                            "(fetch the branch, or the code is in another repository)")
        elif ctx.git and in_history(ctx.root, m.group(2)):
            problems.append(f"Branch names commit {m.group(2)}, which this branch already holds: the tool has merged, "
                            "so make the page Current (or Retired if its code was removed since)")
    if page.field("Public page") and ctx.kind == "private" and \
            "### Differences from the public copy" not in page.text:
        problems.append("a page with a Public page field needs '### Differences from the public copy'")
    return problems


def _check_sections(page, kinds, runnable, branch_only):
    problems = []
    want = BRANCH_SECTIONS if branch_only else SECTIONS
    have = page.sections
    pos = -1
    for name in want:
        names = ALTERNATIVES.get(name, (name,)) if not branch_only else (name,)
        found = [have.index(n) for n in names if n in have]
        if not found:
            problems.append(f"missing section '## {' or ## '.join(names)}'")
            continue
        first = min(found)
        if first < pos:
            problems.append(f"section '## {have[first]}' is out of order; the order is in {STANDARD}")
        pos = max(pos, max(found))
        for n in names:
            if n not in page.bodies:
                continue
            body = page.body(n)
            if not body.strip():
                problems.append(f"section '## {n}' is empty")
            elif _not_applicable(page, n):
                if n in NEVER_NOT_APPLICABLE or (runnable and n in ("Quick start", "Commands and options")):
                    problems.append(f"section '## {n}' cannot be 'Not applicable' on this page")
            elif n in HEADERS and not _has_header(page.bodies[n], HEADERS[n]):
                problems.append(f"section '## {n}' needs a table with the header {HEADERS[n]}")
    if branch_only:
        problems += _check_agent_labels(page, BRANCH_AGENT_LABELS)
    else:
        problems += _check_agent_labels(page, AGENT_LABELS)
        if "Checks and controls" in page.bodies and not _not_applicable(page, "Checks and controls"):
            labels = CLAIM_LINE.findall(page.body("Checks and controls"))
            if not labels:
                problems.append("'## Checks and controls' needs a line 'Claim label: LABEL' "
                                f"(one of {list(CLAIM_LABELS)})")
            elif not any(labels[0].startswith(lbl) for lbl in CLAIM_LABELS):
                problems.append(f"claim label {labels[0]!r} is not one of {list(CLAIM_LABELS)}")
        if runnable:
            if "Quick start" in page.bodies and not re.search(r"^```(bash|sh|shell)\b", page.body("Quick start"), re.M):
                problems.append("'## Quick start' needs a ```bash block that can be pasted")
            if "Outputs" in page.bodies and not _not_applicable(page, "Outputs") \
                    and not _has_header(page.bodies["Outputs"], EXIT_HEADER):
                problems.append(f"'## Outputs' needs an exit code table with the header {EXIT_HEADER}")
    bullets = [l for l in page.bodies.get("History", []) if l.startswith("- ")]
    if "History" in page.bodies and not bullets:
        problems.append("'## History' needs dated bullets: - YYYY-MM-DD: what changed (`COMMIT` or a PR link)")
    for b in bullets:
        if not HISTORY_RE.match(b):
            problems.append(f"History bullet {b[:50]!r} does not start with '- YYYY-MM-DD: '")
        elif not (HEXSPAN.search(b) or "](" in b):
            problems.append(f"History bullet {b[:50]!r} names no commit (`abc1234`) or PR link")
    return problems


def _check_agent_labels(page, labels):
    if "For agents" not in page.bodies:
        return []
    used = [m.group(1) for m in (AGENT_LINE.match(l) for l in page.bodies["For agents"]) if m]
    if [u for u in used if u in labels] != list(labels):
        return [f"'## For agents' needs one bullet per label, in this order: "
                + ", ".join(f"- **{lbl}:**" for lbl in labels) + f" (found {used})"]
    return []


def _check_links(page, ctx):
    problems = []
    text = SPAN.sub("", FENCE.sub("", page.text))
    for target in MD_LINK.findall(text):
        if target.startswith("#") or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target):
            continue
        rel = target.split("#", 1)[0].split("?", 1)[0]
        if not rel:
            continue
        resolved = (page.path.parent / rel).resolve()
        if resolved.exists():
            continue
        tools = (ctx.root / "docs" / "tools").resolve()
        if resolved.parent == tools and resolved.suffix == ".md" and resolved.stem in ctx.pending:
            continue
        if f"link ({target}) does not resolve" not in problems:
            problems.append(f"link ({target}) does not resolve")
    if ctx.kind == "public" and re.search(r"Scrolls-private/(blob|tree|commit|pull)/", page.text, re.I):
        problems.append("a public page links into Scrolls-private; name a private tool in words only (hard rule 1)")
    return problems


def _check_code(page, ctx, detail=True):
    """Paths, symbols, public functions, error messages, environment variables and script options of the code the
    page names; with detail=False (a data page, such as saved records), only that the paths exist."""
    problems = []
    root = ctx.root
    code = page.code_text()
    collapsed = _collapse(page.text.replace("\\|", "|"))
    seen_cells = [_collapse(row[0]) for row in _table_rows(page.bodies.get("Failure modes", [])) if row]
    api = "\n".join(SPAN.findall(page.body("Python API")) + [m.group(0) for m in FENCE.finditer(page.body("Python API"))])
    for name in ("Tests",):
        for span in page.spans(name):
            if _is_path(span) and not _exists(root, span):
                problems.append(f"{name} names {span!r}, which is not in the repository")
    files = list(page.code_items())
    for rel in [s for s in (SCRIPT_RUN.match(r) for r in page.runs()) if s]:
        if rel.group(1).rstrip("/") not in [p.rstrip("/") for p, _ in files]:
            files.append((rel.group(1), []))
    for rel, symbols in files:
        if not _exists(root, rel):
            problems.append(f"Code names {rel!r}, which is not in the repository")
            continue
        if any(c in rel for c in "*?[") or not detail:
            continue
        targets = [rel] if not (root / rel).is_dir() else \
            sorted(p.relative_to(root).as_posix() for p in (root / rel).rglob("*")
                   if p.suffix in (".py", ".sh") and "__pycache__" not in p.parts)
        for f in targets:
            if f.endswith(".sh"):
                text = (root / f).read_text(encoding="utf-8", errors="replace")
                for env in env_names_sh(text):
                    if not re.search(r"(?<![A-Z0-9_])" + env + r"(?![A-Z0-9_])", code):
                        problems.append(f"environment variable `{env}`, read by {f}, is not on the page in code")
                for frag in sh_error_messages(text, parts=True):
                    problems += _message_problem(frag, f, seen_cells, collapsed)
                continue
            if not f.endswith(".py"):
                continue
            tree = _module_tree(root, f)
            if tree is None:
                continue
            if symbols:
                names = top_names(tree)
                for s in symbols:
                    if s.split(".")[0] not in names:
                        problems.append(f"Code names `{s}` in {f}, which defines no such top-level name")
            scope = _scoped(tree, symbols)
            if f.startswith("kit/") and not symbols and not (root / rel).is_dir():
                for name in public_api(tree):
                    if not re.search(r"(?<![\w.])" + re.escape(name) + r"\b", api):
                        problems.append(f"public `{name}` of {f} is not in '## Python API' in code")
            for frag in error_messages(scope, parts=True):
                problems += _message_problem(frag, f, seen_cells, collapsed)
            for env in [e for t in scope for e in env_names_py(t, _constants(tree))]:
                if not re.search(r"(?<![A-Z0-9_])" + env + r"(?![A-Z0-9_])", code):
                    problems.append(f"environment variable `{env}`, read by {f}, is not on the page in code")
            if not f.startswith("kit/") or (rel != f):
                rows = [c for row in _table_rows(page.bodies.get("Commands and options", [])) for c in row[:1]]
                for opt in script_options(tree):
                    if not any(re.search(r"(?<![\w-])" + re.escape(opt) + r"(?![\w-])", c) for c in rows):
                        problems.append(f"option `{opt}` of {f} has no row in a table under '## Commands and options'")
                problems += _check_static_parsers(page, f, f, tree)
    seen_entries = set()
    for span in page.runs() if detail else []:
        m = ENTRY_RUN.match(span)
        if m:
            mod = m.group(1).split(".", 1)[1]
            rel = f"kit/{mod}.py" if (root / f"kit/{mod}.py").exists() else f"kit/{mod}/__main__.py"
            tree = _module_tree(root, rel)
            if tree is None:
                problems.append(f"Run names `{m.group(0)}`, but {rel} is not in the repository")
                continue
            rows = [c for row in _table_rows(page.bodies.get("Commands and options", [])) for c in row[:1]]
            for opt in script_options(tree):
                if not any(re.search(r"(?<![\w-])" + re.escape(opt) + r"(?![\w-])", c) for c in rows):
                    problems.append(f"option `{opt}` of `{m.group(0)}` has no row in a table under '## Commands and options'")
            if m.group(0) not in seen_entries:
                seen_entries.add(m.group(0))
                problems += _check_static_parsers(page, rel, f"`{m.group(0)}`", tree)
    return list(dict.fromkeys(problems))


def _message_problem(parts, f, seen, collapsed):
    """A problem when a message (its literal stretches) is not in the What you see column of '## Failure modes'.
    seen holds that column's cells, collapsed the whole page."""
    shown = "...".join(_collapse(p) for p in parts if _collapse(p))
    if any(message_in(parts, cell) for cell in seen):
        return []
    if message_in(parts, collapsed):
        return [f"error message {shown[:60]!r} from {f} is on the page but not in the What you see column of "
                "'## Failure modes'"]
    return [f"error message {shown[:60]!r} from {f} is not in '## Failure modes'"]


def _exists(root, rel):
    if any(c in rel for c in "*?["):
        return any(root.glob(rel))
    return (root / rel.rstrip("/")).exists()


def _heading_matches(heading, want, actions):
    spans = SPAN.findall(heading)
    if not spans:
        return False
    tokens = ["python" if t == "python3" else t for t in spans[0].split()]
    n = len(want)
    return tokens[:n] == want and (len(tokens) == n or tokens[n] not in actions)


HELP_COLUMN = "What it does (`--help`)"


def _check_top(page, cmds, subsections):
    """A page whose Run names bare `python -m kit` documents the top-level parser: its usage block, matching
    --help, and a row for every command (the command's name first in a row under '## Commands and options').
    A column headed 'What it does (`--help`)' holds each command's help from the parser, word for word, in the
    command's first row; later rows of the same command describe some of its actions and are not compared."""
    problems = []
    actions = set(cmds.aliases)
    matches = [body for head, body in subsections if _heading_matches(head, ["python", "-m", "kit"], actions)]
    if not matches:
        return ["no '### `python -m kit`' heading under '## Commands and options'"]
    fences = [_collapse(m.group(0)) for m in FENCE.finditer("\n".join(line for b in matches for line in b))]
    usage = _collapse(cmds.top.format_usage())
    if not any(usage in f for f in fences):
        problems.append(f"the usage block under '### `python -m kit`' differs from --help; paste `python -m kit "
                        f"--help`'s usage line: {usage[:80]}...")
    firsts = set()
    for row in _table_rows(page.bodies.get("Commands and options", [])):
        spans = SPAN.findall(row[0]) if row else []
        if spans:
            firsts.add(spans[0].split()[0])
    for name in cmds.parsers:
        if name not in firsts and not any(a in firsts for a, c in cmds.aliases.items() if c == name):
            problems.append(f"command `{name}` of `python -m kit` has no row (its name first) under "
                            "'## Commands and options'")
    subs = next(a for a in cmds.top._actions if isinstance(a, argparse._SubParsersAction))
    helps = {cmds.aliases.get(c.dest, c.dest): c.help for c in subs._choices_actions if c.help}
    for header, rows in _tables(page.bodies.get("Commands and options", [])):
        if HELP_COLUMN not in header:
            continue
        col, done = header.index(HELP_COLUMN), set()
        for row in rows:
            spans = SPAN.findall(row[0]) if row else []
            name = cmds.aliases.get(spans[0].split()[0]) if spans else None
            if name in done:
                continue
            done.add(name)
            if name in helps and _collapse(row[col] if col < len(row) else "") != _collapse(helps[name]):
                problems.append(f"the {HELP_COLUMN} cell of `{name}` differs from its parser's help; paste "
                                f"it: {helps[name][:80]}")
    return problems


def _check_runs(page, ctx):
    problems = []
    cmds = ctx.commands
    subsections = page.subsections("Commands and options")
    done = set()
    if any(re.fullmatch(r"python3? -m kit", s.strip()) for s in page.runs()):
        problems += _check_top(page, cmds, subsections)
    for span in page.runs():
        if not KIT_RUN.match(span):
            continue
        target = cmds.target(span)
        if target is None:
            problems.append(f"Run names `{KIT_RUN.match(span).group(0)}`, which is not a kit command")
            continue
        command, action = target
        actions = cmds.parsers[command]
        m = KIT_RUN.match(span)
        if action is not None and action not in actions:
            problems.append(f"Run names `{m.group(0)}`, which is not an action of {command}")
            continue
        wanted = [action] if action else ([None] if list(actions) == [None] else [a for a in actions if a])
        for act in wanted:
            if (command, act) in done:
                continue
            done.add((command, act))
            name = f"python -m kit {command}" + (f" {act}" if act else "")
            want = name.split()
            parser = actions[act]
            matches = [body for head, body in subsections if _heading_matches(head, want, actions)]
            if not matches:
                problems.append(f"no '### `{name}`' heading under '## Commands and options'")
                continue
            body = [line for b in matches for line in b]
            fences = [_collapse(m_.group(0)) for m_ in FENCE.finditer("\n".join(body))]
            usage = _collapse(parser.format_usage())
            if not any(usage in f for f in fences):
                problems.append(f"the usage block under '### `{name}`' differs from --help; paste `{name} --help`'s "
                                f"usage line: {usage[:80]}...")
            rows = _table_rows(body)
            seen = []
            for arg, act_, positional in _arguments(parser):
                row = _row_for(rows, arg, positional)
                if row is None:
                    problems.append(f"{'positional' if positional else 'option'} `{arg}` of `{name}` has no row "
                                    f"in the table under its heading")
                    continue
                seen.append(id(row))
                expected = render_default(act_, positional)
                cell = row[1] if len(row) > 1 else ""
                if not _default_ok(cell, expected):
                    problems.append(f"default of `{arg}` in `{name}` is `{expected}` in the code; the page says "
                                    f"{cell[:40]!r}")
            known = {a for a, _, _ in _arguments(parser)}
            for row in rows:
                spans = SPAN.findall(row[0]) if row else []
                if spans and spans[0].split()[0].startswith("-") and id(row) not in seen:
                    first = spans[0].split()[0]
                    if first not in known and first not in {s for _, a, _ in _arguments(parser) for s in a.option_strings}:
                        problems.append(f"row `{first}` under '### `{name}`' is not an option of that command")
    return problems


def _row_for(rows, arg, positional):
    for row in rows:
        for span in SPAN.findall(row[0] if row else ""):
            first = span.split()[0] if span.split() else ""
            if first == arg or (positional and first.lower() == arg.lower()):
                return row
            if not positional and first.rstrip(",") == arg:
                return row
            if not positional and arg in [t.rstrip(",") for t in span.split()]:
                return row
    return None


# ---------------------------------------------------------------- coverage


def coverage_targets(files, commands, releases=()):
    """Every thing that needs a page: (target, kind) pairs."""
    out = []
    for f in files:
        parts = f.split("/")
        if len(parts) == 2 and parts[0] == "kit" and f.endswith(".py") and parts[1] not in ("__init__.py", "__main__.py",
                                                                                          "cli.py"):
            out.append(f)
        elif len(parts) >= 3 and parts[0] == "kit" and parts[1] != "data" and parts[2] == "__init__.py":
            out.append(f"kit/{parts[1]}")
        elif len(parts) >= 2 and parts[0] == "scripts" and parts[1] != "README.md" and not parts[1].startswith("."):
            out.append(f"scripts/{parts[1]}")
        elif len(parts) >= 4 and parts[:2] == [".claude", "skills"]:
            out.append(f".claude/skills/{parts[2]}")
        elif len(parts) == 3 and parts[:2] == [".github", "workflows"] and f.endswith((".yml", ".yaml")):
            out.append(f)
        elif f == "pyproject.toml":
            out.append(f)
    if commands is not None:
        for command, actions in commands.parsers.items():
            if list(actions) == [None]:
                out.append(f"python -m kit {command}")
            else:
                out += [f"python -m kit {command} {a}" for a in actions if a]
    out += [f"release {r}" for r in releases]
    return list(dict.fromkeys(out))


def _covered_by(pages, commands):
    """A function that says whether some page covers a coverage target."""
    named, runs, ids = set(), set(), set()
    for page in pages:
        ids.add(page.id)
        ids.update(SPAN.findall(page.field("Release id")))
        for path, symbols in page.code_items():
            if not symbols:
                named.add(path.rstrip("/"))
        if commands is not None:
            for span in page.runs():
                t = commands.target(span)
                if t:
                    runs.add(t)

    def covered(target):
        if target.startswith("python -m kit "):
            command, *rest = target[len("python -m kit "):].split()
            return (command, None) in runs or (command, rest[0] if rest else None) in runs
        if target.startswith("release "):
            return target[len("release "):] in ids
        return any(n == target or n.startswith(target + "/") for n in named)

    return covered, ids


def uncovered(pages, files, commands, releases=()):
    """Coverage targets that no page names."""
    covered, _ = _covered_by(pages, commands)
    return [t for t in coverage_targets(files, commands, releases) if not covered(t)]


def coverage(pages, files, commands, releases=(), pending=None):
    """Problems: targets no page names and pending.json does not list, and pending entries that are done or stale."""
    pending = pending or {}
    covered, ids = _covered_by(pages, commands)
    waiting = {t: pid for pid, entry in pending.items() for t in entry.get("covers", [])}
    problems = []
    targets = coverage_targets(files, commands, releases)
    for target in targets:
        if covered(target) or target in waiting:
            continue
        stem = Path(target.split()[-1]).stem.lstrip("_").replace("_", "-").lower() or "tool"
        if target.startswith("kit/_"):
            problems.append(f"{target} has no tool page: name `{target}` in the Code field of the page of the tool "
                            f"that uses it ({STANDARD})")
        elif target.startswith("python -m kit "):
            problems.append(f"`{target}` is on no tool page's Run field ({STANDARD})")
        elif target.startswith("release "):
            problems.append(f"docs/releases.json entry {target[8:]!r} has no tool page with that id or Release id")
        else:
            problems.append(f"{target} has no tool page: start one with `python -m kit.tooldocs new {stem} --kind KIND "
                            f"--area AREA` and name `{target}` in its Code field ({STANDARD})")
    for pid, entry in sorted(pending.items()):
        if pid in ids:
            problems.append(f"docs/tools/pending.json lists {pid!r}, which now has a page: remove it")
        for t in entry.get("covers", []):
            if t not in targets:
                problems.append(f"docs/tools/pending.json lists {t!r} under {pid!r}, which no longer needs a page: "
                                "remove it")
            elif covered(t):
                problems.append(f"docs/tools/pending.json lists {t!r} under {pid!r}, which a page now covers: "
                                "remove it")
    return problems


# ---------------------------------------------------------------- index


def load_pages(pages_dir):
    out = []
    for path in sorted(Path(pages_dir).glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            page = Page(path, "")
            page.problems = ["the page is not valid UTF-8"]
            out.append(page)
            continue
        out.append(Page(path, text))
    return out


def load_pending(root):
    path = Path(root) / "docs" / "tools" / "pending.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("pages", {})


def entry(page, root):
    checked = CHECKED_RE.match(page.field("Checked"))
    name, _, tagline = page.title.partition(": ")
    go = page.field("Go-ahead")
    return {
        "id": page.id,
        "name": name,
        "tagline": tagline,
        "summary": page.summary,
        "status": page.field("Status"),
        "kind": [k.strip() for k in page.field("Kind").split(",") if k.strip()],
        "area": page.field("Area"),
        "commands": page.runs(),
        "imports": [s for s in page.spans("Run") if s.startswith(("from ", "import "))],
        "code": [{"path": p, "symbols": s} for p, s in page.code_items()],
        "tests": [s for s in page.spans("Tests") if _is_path(s)],
        "go_ahead": {"needed": go.startswith("Needed"), "text": go},
        "checked": {"date": checked.group(1), "commit": checked.group(2)} if checked else None,
        "license": page.field("License") or None,
        "fields": {k: page.fields[k] for k in page.order},
        "page": page.path.relative_to(root).as_posix(),
        "sections": [{"name": s, "start_line": page.lines[s][0], "end_line": page.lines[s][1],
                      "applicable": not _not_applicable(page, s)} for s in page.sections if s in page.lines],
    }


def render_json(pages, root, kind=None):
    repo = {"public": "Scrolls", "private": "Scrolls-private"}.get(kind)
    data = {"schema_version": SCHEMA_VERSION, "repo": repo,
            "about": ("Every tool's page in docs/tools/, generated by python -m kit.tooldocs index from the pages; "
                      "edit the pages, not this file. The standard is " + STANDARD + ". Line numbers are 1-based "
                      "lines of the page."),
            "tools": [entry(p, root) for p in sorted(pages, key=lambda p: p.id)]}
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def render_table(pages):
    rank = {s: i for i, s in enumerate(STATUSES)}
    out = []
    for area in AREAS + ("",):
        group = [p for p in pages if (p.field("Area") if p.field("Area") in AREAS else "") == area]
        if not group:
            continue
        out.append(f"### {area or 'Other'}\n")
        out.append("| Tool | Status | Run | Go-ahead | What it does |")
        out.append("| --- | --- | --- | --- | --- |")
        for p in sorted(group, key=lambda p: (rank.get(p.field("Status"), len(STATUSES)), p.id)):
            run = p.runs() or p.spans("Run")
            run_cell = f"`{run[0]}`" if run else p.field("Run").replace("|", "\\|")
            go = "Needed" if p.field("Go-ahead").startswith("Needed") else "Not needed"
            out.append(f"| [{p.id}]({p.path.name}) | {p.field('Status')} | {run_cell} | {go} | "
                       f"{p.summary.replace('|', chr(92) + '|')} |")
        out.append("")
    return "\n".join(out).rstrip()


def render_index(pages, current=None):
    block = f"{START}\n\n{render_table(pages)}\n\n{END}"
    if current and START in current and END in current:
        head, rest = current.split(START, 1)
        return head + block + rest.split(END, 1)[1]
    return INTRO + "\n" + block + "\n"


# ---------------------------------------------------------------- whole repository


def releases_ids(root):
    """Ids in docs/releases.json that need a tool page: every entry's, and every tool's in a grouped entry's tools
    (the Scrolls kit entry, 20 October 2026), so a tool that joined a group keeps its page."""
    path = Path(root) / "docs" / "releases.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("releases", [])
        return [r["id"] for r in entries] + [t["id"] for r in entries for t in r.get("tools", [])]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def check_all(root=ROOT, page_ids=None, commands=None):
    """Every problem in the repository's tool docs, or only those of the pages in page_ids."""
    root = Path(root)
    pages_dir = root / "docs" / "tools"
    pages = load_pages(pages_dir)
    if commands is None and root == ROOT:
        try:
            commands = kit_commands()
        except Exception as exc:  # a broken parser is itself a problem to report, not a crash
            return [f"cannot build kit's parser: {exc}"]
    try:
        pending = load_pending(root)
    except ValueError as exc:
        return [f"docs/tools/pending.json does not parse: {exc}"]
    ctx = Context(root, commands, pending, repo_kind(root), git_usable(root))
    chosen = pages
    if page_ids:
        chosen = [p for p in pages if p.id in page_ids]
        missing = sorted(set(page_ids) - {p.id for p in chosen})
        if missing:
            return [f"no page docs/tools/{m}.md" for m in missing]
    problems = []
    for page in chosen:
        problems += [f"{page.path.relative_to(root).as_posix()}: {m}" for m in check_page(page, ctx)]
    if page_ids:
        return problems
    problems += coverage(pages, tracked(root), commands, releases_ids(root), pending)
    index_md = pages_dir / "README.md"
    current = index_md.read_text(encoding="utf-8") if index_md.exists() else None
    if current is not None and (START not in current or END not in current):
        problems.append("docs/tools/README.md has no generated block; add the two marker lines or delete the file "
                        "and run python -m kit.tooldocs index")
    elif current != render_index(pages, current):
        problems.append("docs/tools/README.md is out of date: run python -m kit.tooldocs index")
    index_json = pages_dir / "index.json"
    if not index_json.exists() or index_json.read_text(encoding="utf-8") != render_json(pages, root, ctx.kind):
        problems.append("docs/tools/index.json is out of date: run python -m kit.tooldocs index")
    return problems


def write_index(root=ROOT):
    root = Path(root)
    pages_dir = root / "docs" / "tools"
    pages = load_pages(pages_dir)
    index_md = pages_dir / "README.md"
    current = index_md.read_text(encoding="utf-8") if index_md.exists() else None
    if current is not None and (START not in current or END not in current):
        raise ValueError("docs/tools/README.md has no generated block; refusing to overwrite its text")
    index_md.write_text(render_index(pages, current), encoding="utf-8")
    (pages_dir / "index.json").write_text(render_json(pages, root, repo_kind(root)), encoding="utf-8")
    return len(pages)


def stale(root=ROOT):
    """(page id, main file) where the main code file has a newer commit than the page."""
    root = Path(root)
    out = []
    for page in load_pages(root / "docs" / "tools"):
        items = page.code_items()
        if not items or page.field("Status") == "Branch only":
            continue
        main = items[0][0]
        t_code = _git(root, "log", "-1", "--format=%ct", "--", main)
        t_page = _git(root, "log", "-1", "--format=%ct", "--", page.path.relative_to(root).as_posix())
        if not t_code or not t_page or not t_code.stdout.strip():
            continue
        if not t_page.stdout.strip() or int(t_code.stdout) > int(t_page.stdout):
            out.append((page.id, main))
    return out


# ---------------------------------------------------------------- new pages


def _option_label(arg, act, positional):
    if positional:
        return f"`{arg}`"
    if act.nargs == 0 or isinstance(act, (argparse._StoreTrueAction, argparse._StoreFalseAction,
                                          argparse._CountAction, argparse._StoreConstAction)):
        return f"`{arg}`"
    meta = act.metavar if act.metavar is not None else act.dest.upper()
    if isinstance(meta, tuple):
        meta = " ".join(meta)
    if act.nargs in ("*", "+"):
        meta = f"{meta} ..."
    elif isinstance(act.nargs, int) and act.nargs > 1 and not isinstance(act.metavar, tuple):
        meta = " ".join([meta] * act.nargs)
    return f"`{arg} {meta}`"


def _help(parser, act):
    if not act.help:
        return "<!-- Write: what it does -->"
    text = act.help.replace("%%", "%")
    try:
        text = act.help % {**vars(act), "prog": parser.prog, "default": act.default}
    except (KeyError, TypeError, ValueError):
        pass
    return text.replace("|", "\\|").replace("\n", " ")


def commands_block(commands, specs):
    out = []
    for spec in specs:
        target = commands.target("python -m kit " + spec)
        if target is None:
            raise ValueError(f"`python -m kit {spec}` is not a kit command")
        command, action = target
        actions = commands.parsers[command]
        for act in ([action] if action else ([None] if list(actions) == [None] else [a for a in actions if a])):
            parser = actions[act]
            name = f"python -m kit {command}" + (f" {act}" if act else "")
            out += [f"### `{name}`", "", "```", parser.format_usage().strip(), "```", "",
                    "| Option | Default | Meaning |", "| --- | --- | --- |"]
            for arg, a, positional in _arguments(parser):
                d = render_default(a, positional)
                cell = d if d in ("required", "off", "on", "none") else f"`{d}`"
                out.append(f"| {_option_label(arg, a, positional)} | {cell} | {_help(parser, a)} |")
            out.append("")
    return "\n".join(out).rstrip()


def _signature(node):
    if isinstance(node, ast.ClassDef):
        init = next((n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
        if init is None:
            return f"{node.name}()"
        args = ast.unparse(init.args)
        args = re.sub(r"^self,?\s*", "", args)
        return f"{node.name}({args})"
    return f"{node.name}({ast.unparse(node.args)})"


def api_block(root, paths):
    rows = []
    for rel in paths:
        if not rel.startswith("kit/") or not rel.endswith(".py"):
            continue
        tree = _module_tree(root, rel)
        if tree is None:
            continue
        names = public_api(tree)
        nodes = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        for name in names:
            node = nodes.get(name)
            sig = _signature(node).replace("|", "\\|") if node is not None else name
            doc = (ast.get_docstring(node) or "").strip().split("\n")[0].replace("|", "\\|") if node is not None else ""
            rows.append(f"| `{sig}` | <!-- Write: returns --> | <!-- Write: raises --> | "
                        f"{doc or '<!-- Write: notes -->'} |")
    if not rows:
        return ""
    return "\n".join(["| Function | Returns | Raises | Notes |", "| --- | --- | --- | --- |"] + rows)


def _code_files(root, paths):
    for rel in paths:
        p = root / rel
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.suffix in (".py", ".sh") and "__pycache__" not in f.parts:
                    yield f.relative_to(root).as_posix()
        elif p.exists():
            yield rel


def failures_block(root, items, runnable):
    """A Failure modes table with a row per error message in the code: items are (path, [symbols])."""
    rows = ["| What you see | Why | What to do |", "| --- | --- | --- |"]
    if runnable:
        rows.append("| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | "
                    "Check the command against Commands and options |")
    seen = []
    for rel, symbols in items:
        for f in _code_files(root, [rel]):
            if f.endswith(".sh"):
                messages = sh_error_messages((root / f).read_text(encoding="utf-8", errors="replace"), parts=True)
            elif f.endswith(".py"):
                tree = _module_tree(root, f)
                if tree is None:
                    continue
                messages = error_messages(_scoped(tree, symbols), parts=True)
            else:
                continue
            for parts in messages:
                frag = "...".join(w for w in (_collapse(p) for p in parts) if w)
                if parts and not _collapse(parts[0]):
                    frag = "..." + frag
                if len(parts) > 1 and not _collapse(parts[-1]):
                    frag += "..."
                if frag in seen:
                    continue
                seen.append(frag)
                cell = frag.replace("|", chr(92) + "|").replace("`", "'")
                rows.append(f"| `{cell}` | <!-- Write: why --> | <!-- Write: what to do --> |")
    return "\n".join(rows)


def env_block(root, paths):
    names = []
    for rel in _code_files(root, paths):
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        if rel.endswith(".sh"):
            found = env_names_sh(text)
        else:
            tree = _module_tree(root, rel)
            found = env_names_py(tree) if tree is not None else []
        names += [n for n in found if n not in names]
    if not names:
        return ""
    rows = ["### Environment variables", "", "| Variable | Default | Meaning |", "| --- | --- | --- |"]
    rows += [f"| `{n}` | <!-- Write: default --> | <!-- Write: meaning --> |" for n in names]
    return "\n".join(rows)


def history_block(root, paths, limit=12):
    if not paths:
        return ""
    out = _git(root, "log", f"-{limit}", "--format=%as %h %s", "--", *paths)
    if out is None or out.returncode != 0 or not out.stdout.strip():
        return ""
    lines = []
    for line in out.stdout.strip().split("\n"):
        day, sha, subject = line.split(" ", 2)
        subject = subject.replace(chr(0x2014), ",").replace(chr(0x2013), " to ")
        lines.append(f"- {day}: {subject} (`{sha}`) <!-- Write: say what changed for users, or drop this line -->")
    return "\n".join(lines)


def tests_for(root, paths):
    mods = [Path(p).stem for p in paths if p.endswith(".py") and p.startswith("kit/")]
    if not mods:
        return []
    hits = []
    for t in sorted((root / "tests").glob("test_*.py")) if (root / "tests").exists() else []:
        text = t.read_text(encoding="utf-8", errors="replace")
        if any(re.search(rf"\bkit(\.|\s+import\s+(?:[\w, ]*\b)?){m}\b|from kit\.{m} import|from kit import .*\b{m}\b", text)
               for m in mods):
            hits.append(t.relative_to(root).as_posix())
    return hits


def _drop_section(text, name):
    """The text without the ## section called name (heading and body)."""
    out, skip = [], False
    for line in text.split("\n"):
        if line.startswith("## "):
            skip = line[3:].strip() == name
        if not skip:
            out.append(line)
    return "\n".join(out)


def new_page(page_id, kind="kit command", status="Current", root=ROOT, today=None, area=None, commands=(),
             code=(), command_parser=None):
    """Write docs/tools/ID.md from the template, prefilled from the code; return its path."""
    root = Path(root)
    if not ID_RE.fullmatch(page_id):
        raise ValueError(f"{page_id!r}: an id is lowercase letters, digits and hyphens")
    if status not in STATUSES:
        raise ValueError(f"status {status!r} is not one of {list(STATUSES)}")
    kinds = [k.strip() for k in kind.split(",")]
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        raise ValueError(f"kind {bad} is not in {list(KINDS)}")
    if area is not None and area not in AREAS:
        raise ValueError(f"area {area!r} is not one of {list(AREAS)}")
    path = root / "docs" / "tools" / f"{page_id}.md"
    if path.exists():
        raise ValueError(f"{path.relative_to(root).as_posix()} already exists")
    missing = [c for c in code if not (root / c.rstrip("/")).exists()]
    if missing and status != "Branch only":
        raise ValueError(f"--code {missing[0]!r} is not in the repository")
    branch = status == "Branch only"
    template = "tool-doc-branch.md" if branch else "tool-doc.md"
    text = (root / "templates" / template).read_text(encoding="utf-8")
    items = [(c, []) for c in code]
    cmd_block = api = ""
    run = ""
    if commands:
        command_parser = command_parser or kit_commands()
        cmd_block = commands_block(command_parser, commands)
        run = ", ".join(f"`python -m kit {c}`" for c in commands)
        funcs = []
        for c in commands:
            command, _ = command_parser.target("python -m kit " + c)
            func = command_parser.parsers[command][None].get_default("func")
            if func is not None and func.__name__ != "<lambda>" and func.__name__ not in funcs:
                funcs.append(func.__name__)
        if funcs and "kit/cli.py" not in code:
            items.append(("kit/cli.py", funcs))
    plain = [c for c, symbols in items if not symbols]
    if not branch:
        api = api_block(root, plain)
    head = _git(root, "rev-parse", "--short", "HEAD")
    sha = head.stdout.strip() if head is not None and head.returncode == 0 and head.stdout.strip() else "COMMIT"
    code_cell = ", ".join(f"`{c}`" + (" (" + ", ".join(f"`{s}`" for s in symbols) + ")" if symbols else "")
                          for c, symbols in items)
    tests = tests_for(root, plain)
    runnable = any(k in RUNNABLE for k in kinds)
    subs = {
        "{id}": page_id, "{kind}": kind, "{status}": status,
        "{area}": area or "<!-- Write: one of the Area words in docs/TOOL-DOCS.md -->",
        "{date}": (today or date.today()).isoformat(), "{commit}": sha,
        "{run}": run or "<!-- Write: each entry point in code, or None (library) and the import, such as "
                        "`from kit import auc` -->",
        "{code}": code_cell or "<!-- Write: every file of the tool, in code -->",
        "{tests}": ", ".join(f"`{t}`" for t in tests) or "<!-- Write: test files in code, or None and why -->",
        "{commands_block}": cmd_block or "<!-- Write: a ### heading per command or action, its usage block from "
                                         "--help and a | Option | Default | Meaning | table -->",
        "{api_block}": api or "<!-- Write: a | Function | Returns | Raises | Notes | table for each public "
                              "function -->",
        "{env_block}": env_block(root, plain + [c for c, s in items if s and c != "kit/cli.py"]),
        "{failures_block}": failures_block(root, items, runnable),
        "{history_block}": history_block(root, [c for c, _ in items])
        or "- <!-- Write: YYYY-MM-DD: what changed (`COMMIT` or a PR link) -->",
    }
    for key, value in subs.items():
        text = text.replace(key, value)
    if not branch:
        if commands and not api:
            text = _drop_section(text, "Python API")
        elif api and not commands and not runnable:
            text = _drop_section(text, "Commands and options")
    text = re.sub(r"\n{3,}", "\n\n", text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------- command line


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m kit.tooldocs", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("check", help="check every page, the index and coverage; exit 1 on any problem")
    p.add_argument("--page", metavar="ID", action="append", help="check only this page (repeatable)")
    p.add_argument("--json", action="store_true", help="problems as a JSON list of {page, problem}")
    sub.add_parser("index", help="rewrite docs/tools/README.md's tables and docs/tools/index.json")
    p = sub.add_parser("list", help="every tool, one line each")
    p.add_argument("--json", action="store_true", help="the index as JSON, as in docs/tools/index.json")
    p = sub.add_parser("show", help="print one tool's page, one section of it or one field")
    p.add_argument("id")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--section", metavar="NAME", help="print only this ## section, such as 'For agents'")
    g.add_argument("--field", metavar="NAME", help="print only this At a glance field, such as Writes")
    p = sub.add_parser("new", help="start docs/tools/ID.md from the template, prefilled from the code")
    p.add_argument("id")
    p.add_argument("--kind", default="kit command", help=f"one or more of {', '.join(KINDS)}, comma-separated")
    p.add_argument("--area", choices=AREAS, help="what the tool is for; groups the index")
    p.add_argument("--status", default="Current", choices=STATUSES)
    p.add_argument("--command", action="append", default=[], metavar="CMD [ACTION]",
                   help="a kit command (and action) the page documents, such as 'auc' or 'run init' (repeatable)")
    p.add_argument("--code", action="append", default=[], metavar="PATH",
                   help="a file or folder of the tool, main file first (repeatable)")
    sub.add_parser("stale", help="pages whose main code file changed after the page (a report; exit 0)")
    args = parser.parse_args(argv)

    if args.action == "check":
        problems = check_all(page_ids=args.page)
        if args.json:
            print(json.dumps([{"page": p.split(": ", 1)[0] if p.startswith("docs/tools/") else None,
                               "problem": p.split(": ", 1)[1] if p.startswith("docs/tools/") else p}
                              for p in problems], indent=1))
        else:
            for line in problems:
                print(line)
        if problems:
            print(f"{len(problems)} problem(s); the standard is {STANDARD}", file=sys.stderr)
            return 1
        if not args.json:
            print(f"tool docs pass ({'pages ' + ', '.join(args.page) if args.page else str(len(load_pages(ROOT / 'docs' / 'tools'))) + ' pages'})")
        return 0
    if args.action == "index":
        try:
            n = write_index()
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(f"wrote docs/tools/README.md and docs/tools/index.json from {n} pages")
        return 0
    if args.action == "stale":
        rows = stale()
        for pid, main_file in rows:
            print(f"{pid}: {main_file} changed after docs/tools/{pid}.md; check the page against it")
        if not rows:
            print("no page is older than its main code file")
        return 0
    pages = load_pages(ROOT / "docs" / "tools")
    if args.action == "list":
        if args.json:
            print(render_json(pages, ROOT, repo_kind(ROOT)), end="")
        else:
            for p in sorted(pages, key=lambda p: p.id):
                run = p.runs() or p.spans("Run")
                print(f"{p.id:24} {p.field('Status'):13} {(run[0] if run else p.field('Run'))[:40]:40} {p.summary[:80]}")
        return 0
    if args.action == "show":
        page = next((p for p in pages if p.id == args.id), None)
        if page is None:
            near = difflib.get_close_matches(args.id, [p.id for p in pages], n=5, cutoff=0.4)
            print(f"no tool page {args.id!r}" + (f"; close: {', '.join(near)}" if near else ""), file=sys.stderr)
            return 2
        if args.section:
            if args.section not in page.bodies:
                print(f"no section {args.section!r}; sections: {', '.join(page.sections)}", file=sys.stderr)
                return 2
            print(f"## {args.section}\n" + page.body(args.section).rstrip())
            return 0
        if args.field:
            if args.field not in page.fields:
                print(f"no field {args.field!r}; fields: {', '.join(page.order)}", file=sys.stderr)
                return 2
            print(page.fields[args.field])
            return 0
        print(page.text, end="" if page.text.endswith("\n") else "\n")
        return 0
    try:
        path = new_page(args.id, args.kind, args.status, area=args.area, commands=args.command, code=args.code)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"wrote {path.relative_to(ROOT).as_posix()}; replace every <!-- Write: ... --> with the text, then run "
          f"python -m kit.tooldocs check --page {args.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
