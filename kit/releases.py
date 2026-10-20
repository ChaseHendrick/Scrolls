"""The list of released tools, and the README section made from it.

docs/releases.json lists this project's released tools and packages, including curated private-to-public releases,
since the list began on 14 October 2026, and README.md's "Released tools" section, between the two marker lines below, is written
from it, newest first:

  python -m kit releases add ENTRY.json   add one entry, or replace the entry with its id, then rewrite the section
  python -m kit releases render           rewrite the section from the list
  python -m kit releases check            exit 1 when the section and the list disagree (a unit test runs this)
  python -m kit releases pin ID           show that entry first, above newer ones, until unpinned; unpin ID undoes it

An entry: {"id": "letter-reader", "title": "Greek letter reader", "released": "2026-10-14",
           "summary": "One paragraph: what it does, the measured result with its claim label, the main limit.",
           "commands": ["python -m pip install numpy", "..."],          (optional; shown as a bash block)
           "details": "One line of links, such as the guide.",           (optional)
           "image": {"src": "docs/assets/letter-reader/reader-hero.webp",  (optional; shown under the title)
                     "alt": "What the picture shows, for screen readers.",
                     "caption": "Synthetic demo. What it is and where it came from."},
           "where": "main"}
"where" is "main" for files merged here, or {"branch": B, "commit": C, "path": P} for a reviewed package that lives on
its own branch (the Progress Prize exporter's submission/<submission_id> branches), which the section links at that
commit.

A grouped entry adds "tools": one line each for command-line tools that share one entry (Chase, 20 October 2026:
"consolidate some releases like some of the released stuff on our scrolls readme seems more like kit tools"), the
"Scrolls kit" entry. Each tool keeps its own id, date, version and links:
  "tools": [{"id": "strokenet", "name": "StrokeNet text-likeness score", "released": "2026-10-14",
             "version": "weights `strokenet-paris4-v1`",                     (optional)
             "summary": "One or two sentences: what it does, its result with its claim label, its main limit.",
             "command": "python -m kit strokenet MAP.tif --pixel-mm 0.0024 --json",
             "page": "docs/tools/strokenet.md",
             "evidence": "[model card](docs/strokenet.md)"}]                 (optional)
A grouped entry is on main, its "released" is its newest tool's date, and a tool's id is unique across entries and
tools, so the id of an entry that became a tool still names it: find() resolves either kind, and add, pin and unpin
refuse a tool's id with the entry to edit instead. check() fails when a tool's page is missing.

The list's optional "pinned" holds entry ids shown first, in that order, above the newest (Chase, 14 October 2026:
keep AutoPipeline on top "so people see it"). A pin belongs to the list, not the entry, so a new version that replaces
a pinned entry stays pinned.

An entry's optional "image" is shown under its title, with its caption in italics below. The caption starts with one of
the media labels in LABELS (Chase, 18 October 2026: every released tool gets a hero image, and each picture says what it
is). Its src is a path under docs/assets/ on main, which also serves package entries, since the README that shows the
picture is on main, or a full https:// URL. check() fails when a docs/assets/ picture is missing.

The private repository's submission exporter carries an identical copy of this module and writes the entry of each
package it releases with it, so keep the two copies the same. Standard library only.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "docs" / "releases.json"
README = ROOT / "README.md"
REPO_URL = "https://github.com/ChaseHendrick/Scrolls"
START = ("<!-- releases:start (generated from docs/releases.json by python -m kit releases render; "
         "edit that list, not this section) -->")
END = "<!-- releases:end -->"
INTRO = "Released tools, newest first. Each entry comes from [`docs/releases.json`](docs/releases.json)."
FIELDS = {"id", "title", "released", "summary", "commands", "details", "image", "tools", "where"}
REQUIRED = ("id", "title", "released", "summary", "where")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
LONG_DASHES = (chr(0x2014), chr(0x2013))
# Summary and details start their own Markdown paragraph. A code fence, an HTML block or an indented code block opened
# there would run on past the end marker and swallow the rest of the README, so a value may not start with one.
BLOCK_OPENER = re.compile(r"\s|```|~~~|<")
# A package keeps its own kit; public tests check every "python -m kit X" in README.md against this repository's kit.
KIT_COMMAND = re.compile(r"python3? -m kit ")
# A package's files are not on main, so a relative link in its entry would point at the wrong tree.
RELATIVE_LINK = re.compile(r"\]\((?!https://)")
# Inline raw HTML anywhere in a title, summary or details (an unclosed <details> or <a href> hides or relinks the rest of
# the README), and link targets other than https:// or a relative path (javascript:, http:, //host), are refused.
INLINE_HTML = re.compile(r"<\s*[A-Za-z/!?]")
HTTPS_AUTOLINK = re.compile(r"<https://[^\s<>]*>")
LINK_TARGET = re.compile(r"\]\(\s*<?([^)\s>]*)|^\s{0,3}\[[^\]]*\]:\s*<?(\S*)")
URL_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:|//|\\")
# A picture: a file under docs/assets/ on main, or a full https:// URL, ending in a format GitHub shows inline.
IMAGE_FIELDS = {"src", "alt", "caption"}
IMAGE_SRC = re.compile(r"(?:docs/assets/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*|https://[A-Za-z0-9.-]+/[A-Za-z0-9_.~%/+-]+)"
                       r"\.(?:webp|png|jpg|jpeg|gif)")
# Every picture says what it is (docs/assets/README.md); a caption starts with one of these.
LABELS = ("Concept illustration", "Real data render", "Model output", "Synthetic demo")
# A grouped entry's tools: one line each in the section.
TOOL_FIELDS = {"id", "name", "released", "version", "summary", "command", "page", "evidence"}
TOOL_REQUIRED = ("id", "name", "released", "summary", "command", "page")
TOOL_PAGE = re.compile(r"docs/tools/[a-z0-9][a-z0-9-]*\.md")
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
MAX_TOOLS = 12


class ReleaseListError(ValueError):
    pass


def _text(entry, key, limit, required=True):
    value = entry.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ReleaseListError(f"{entry.get('id', '?')}: {key} must be a non-empty string")
    if len(value) > limit:
        raise ReleaseListError(f"{entry.get('id', '?')}: {key} is longer than {limit} characters")
    if "\n" in value or "\r" in value:
        raise ReleaseListError(f"{entry.get('id', '?')}: {key} must be one line or one paragraph")
    _plain(entry, key, value)
    return value


def _plain(entry, key, value):
    if "<!--" in value or "-->" in value:
        raise ReleaseListError(f"{entry.get('id', '?')}: {key} may not hold an HTML comment")
    for ch in LONG_DASHES:
        if ch in value:
            raise ReleaseListError(f"{entry.get('id', '?')}: {key} has a long dash (house style: none)")
    if key == "commands":   # shown inside a bash code block, where Markdown and HTML are plain text
        return
    if INLINE_HTML.search(HTTPS_AUTOLINK.sub("", value)):
        raise ReleaseListError(f"{entry.get('id', '?')}: {key} may not hold raw HTML")
    for m in LINK_TARGET.finditer(value):
        target = m[1] if m[1] is not None else m[2]
        if not target.startswith("https://") and URL_SCHEME.match(target):
            raise ReleaseListError(f"{entry.get('id', '?')}: {key} links must be https:// or relative, not {target[:40]!r}")


def _image(entry):
    image = entry["image"]
    name = entry.get("id", "?")
    if not isinstance(image, dict) or set(image) != IMAGE_FIELDS:
        raise ReleaseListError(f"{name}: image is {{src, alt, caption}}")
    src = image["src"]
    if not isinstance(src, str) or not IMAGE_SRC.fullmatch(src) or ".." in src.split("/"):
        raise ReleaseListError(f"{name}: image.src is a docs/assets/ path or an https:// URL ending in .webp, .png, "
                               ".jpg, .jpeg or .gif")
    for key, limit in (("alt", 300), ("caption", 500)):
        value = image[key]
        if not isinstance(value, str) or not value.strip() or len(value) > limit or "\n" in value or "\r" in value:
            raise ReleaseListError(f"{name}: image.{key} must be one line of at most {limit} characters")
        _plain(entry, f"image.{key}", value)
    if any(ch in image["alt"] for ch in "[]*`"):
        raise ReleaseListError(f"{name}: image.alt is plain text, without square brackets, asterisks or backticks")
    if "*" in image["caption"] or image["caption"] != image["caption"].strip():
        raise ReleaseListError(f"{name}: image.caption has no asterisks and no leading or trailing space")
    if not image["caption"].startswith(LABELS):
        raise ReleaseListError(f"{name}: image.caption starts with its label, one of {', '.join(LABELS)}")
    if entry.get("where", "main") != "main" and RELATIVE_LINK.search(image["caption"]):
        raise ReleaseListError(f"{name}: a package's links are full https:// URLs at its commit")


def _date(name, key, value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise ReleaseListError(f"{name}: {key} must be a date, YYYY-MM-DD") from None


def _tools(entry):
    """Check a grouped entry's tools list."""
    name = entry["id"]
    tools = entry["tools"]
    if not isinstance(tools, list) or not 1 <= len(tools) <= MAX_TOOLS:
        raise ReleaseListError(f"{name}: tools must be a list of 1 to {MAX_TOOLS} tools")
    if entry["where"] != "main":
        raise ReleaseListError(f"{name}: an entry with tools lists tools merged here; its where is \"main\"")
    seen = set()
    for tool in tools:
        if not isinstance(tool, dict):
            raise ReleaseListError(f"{name}: each tool is a JSON object")
        unknown = set(tool) - TOOL_FIELDS
        if unknown:
            raise ReleaseListError(f"{name}: tool {tool.get('id', '?')}: unknown fields {sorted(unknown)}")
        missing = [k for k in TOOL_REQUIRED if k not in tool]
        if missing:
            raise ReleaseListError(f"{name}: tool {tool.get('id', '?')}: missing {missing}")
        tid = tool["id"]
        if not isinstance(tid, str) or not ID.fullmatch(tid):
            raise ReleaseListError(f"{name}: tool id {tid!r} must be lowercase letters, digits and hyphens")
        if tid == name or tid in seen:
            raise ReleaseListError(f"{name}: tool {tid}: listed twice")
        seen.add(tid)
        label = {"id": f"{name}: tool {tid}"}
        for key, limit in (("name", 80), ("version", 120), ("summary", 800), ("command", 300), ("evidence", 400)):
            value = _text(dict(tool, **label), key, limit, required=key in TOOL_REQUIRED)
            if value is not None and value != value.strip():
                raise ReleaseListError(f"{name}: tool {tid}: {key} has a leading or trailing space")
        if "*" in tool["name"]:
            raise ReleaseListError(f"{name}: tool {tid}: name has no asterisks (it is shown in bold)")
        if "`" in tool["command"]:
            raise ReleaseListError(f"{name}: tool {tid}: command has no backticks (it is shown as inline code)")
        _date(f"{name}: tool {tid}", "released", tool["released"])
        if not isinstance(tool["page"], str) or not TOOL_PAGE.fullmatch(tool["page"]):
            raise ReleaseListError(f"{name}: tool {tid}: page is a tool page, docs/tools/NAME.md")
    newest = max(t["released"] for t in tools)
    if entry["released"] != newest:
        raise ReleaseListError(f"{name}: released is its newest tool's date, {newest}")


def validate(entry):
    """Return the entry if it is well formed, else raise ReleaseListError naming the field."""
    if not isinstance(entry, dict):
        raise ReleaseListError("an entry must be a JSON object")
    unknown = set(entry) - FIELDS
    if unknown:
        raise ReleaseListError(f"{entry.get('id', '?')}: unknown fields {sorted(unknown)}")
    missing = [k for k in REQUIRED if k not in entry]
    if missing:
        raise ReleaseListError(f"{entry.get('id', '?')}: missing {missing}")
    if not isinstance(entry["id"], str) or not ID.fullmatch(entry["id"]):
        raise ReleaseListError(f"id {entry['id']!r} must be lowercase letters, digits and hyphens")
    _text(entry, "title", 80)
    for key, limit in (("summary", 1500), ("details", 500)):
        value = _text(entry, key, limit, required=key == "summary")
        if value is not None and BLOCK_OPENER.match(value):
            raise ReleaseListError(f"{entry['id']}: {key} may not start with a space, a code fence or an HTML tag")
    _date(entry["id"], "released", entry["released"])
    if "image" in entry:
        _image(entry)
    commands = entry.get("commands", [])
    if not isinstance(commands, list) or len(commands) > 12:
        raise ReleaseListError(f"{entry['id']}: commands must be a list of at most 12 lines")
    for line in commands:
        if not isinstance(line, str) or not line.strip() or "\n" in line or "\r" in line or "```" in line:
            raise ReleaseListError(f"{entry['id']}: each command is one non-empty line with no code fence")
        if len(line) > 300:
            raise ReleaseListError(f"{entry['id']}: a command is longer than 300 characters")
        _plain(entry, "commands", line)
    where = entry["where"]
    if where != "main":
        if not isinstance(where, dict) or set(where) != {"branch", "commit", "path"}:
            raise ReleaseListError(f"{entry['id']}: where is \"main\" or {{branch, commit, path}}")
        if not isinstance(where["branch"], str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,99}", where["branch"]) \
                or ".." in where["branch"] or where["branch"] == "main":
            raise ReleaseListError(f"{entry['id']}: where.branch is not a plain branch name")
        if not isinstance(where["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", where["commit"]):
            raise ReleaseListError(f"{entry['id']}: where.commit must be a full 40-character commit")
        path = where["path"]
        if not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", path) \
                or any(part in (".", "..") for part in path.split("/")):
            raise ReleaseListError(f"{entry['id']}: where.path must be a simple relative path")
        if any(KIT_COMMAND.search(text) for text in [entry["summary"], entry.get("details") or "", *commands]):
            raise ReleaseListError(f"{entry['id']}: a package's commands run its own files (python scripts/...), never "
                                   "\"python -m kit\", which the README checks against this repository's kit")
        if any(RELATIVE_LINK.search(text) for text in (entry["summary"], entry.get("details") or "")):
            raise ReleaseListError(f"{entry['id']}: a package's links are full https:// URLs at its commit")
    if "tools" in entry:
        _tools(entry)
    return entry


def validate_list(registry):
    if not isinstance(registry, dict) or registry.get("schema_version") != 1 \
            or set(registry) - {"pinned"} != {"schema_version", "releases"}:
        raise ReleaseListError("the list is {\"schema_version\": 1, \"pinned\": [ids, optional], \"releases\": [...]}")
    entries = registry["releases"]
    if not isinstance(entries, list):
        raise ReleaseListError("releases must be a list")
    seen, tool_ids = set(), set()
    for entry in entries:
        validate(entry)
        if entry["id"] in seen or entry["id"] in tool_ids:
            raise ReleaseListError(f"{entry['id']}: listed twice")
        seen.add(entry["id"])
        for tool in entry.get("tools", []):
            if tool["id"] in seen or tool["id"] in tool_ids:
                raise ReleaseListError(f"{tool['id']}: listed twice")
            tool_ids.add(tool["id"])
    pinned = registry.get("pinned", [])
    if not isinstance(pinned, list) or not all(isinstance(i, str) and i in seen for i in pinned) \
            or len(set(pinned)) != len(pinned):
        raise ReleaseListError("pinned must list ids of entries in the list, each once")
    return registry


def dumps(registry):
    """The list as written to docs/releases.json (both copies of this module write it the same way)."""
    validate_list(registry)
    written = {"schema_version": 1, **({"pinned": registry["pinned"]} if registry.get("pinned") else {}),
               "releases": registry["releases"]}
    return json.dumps(written, indent=2, ensure_ascii=False) + "\n"


def _with(registry, entries):
    """A new list holding entries, with registry's pins kept."""
    pinned = list(registry.get("pinned", []))
    return {"schema_version": 1, **({"pinned": pinned} if pinned else {}), "releases": entries}


def find(registry, some_id):
    """(entry, tool) for an id: (the entry, None) for an entry's id, (its grouped entry, the tool) for a tool's id, such
    as an entry that became a line of the Scrolls kit entry. Raises ReleaseListError for an unknown id."""
    for entry in validate_list(registry)["releases"]:
        if entry["id"] == some_id:
            return entry, None
        for tool in entry.get("tools", []):
            if tool["id"] == some_id:
                return entry, tool
    raise ReleaseListError(f"{some_id}: no entry or tool with that id")


def _not_a_tool(registry, some_id, what):
    for entry in registry["releases"]:
        if any(t["id"] == some_id for t in entry.get("tools", [])):
            raise ReleaseListError(f"{some_id}: a tool in the {entry['id']} entry, not an entry of its own; {what}")


def upsert(registry, entry):
    """A new list with entry added at the end, or in place of the entry with its id (keeping its pin); and "added" or
    "replaced"."""
    validate(entry)
    entries = [dict(e) for e in validate_list(registry)["releases"]]
    _not_a_tool(registry, entry["id"], "change its line in that entry's tools and add the whole entry")
    for i, old in enumerate(entries):
        if old["id"] == entry["id"]:
            entries[i] = dict(entry)
            return validate_list(_with(registry, entries)), "replaced"
    return validate_list(_with(registry, entries + [dict(entry)])), "added"


def pin(registry, entry_id, on=True):
    """A new list with entry_id pinned after any earlier pins, or unpinned."""
    registry = validate_list(registry)
    _not_a_tool(registry, entry_id, "pin or unpin that entry")
    if entry_id not in {e["id"] for e in registry["releases"]}:
        raise ReleaseListError(f"{entry_id}: no entry with that id")
    pinned = [i for i in registry.get("pinned", []) if i != entry_id] + ([entry_id] if on else [])
    return validate_list(_with({"pinned": pinned}, [dict(e) for e in registry["releases"]]))


def _day(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def render_tool(tool):
    """One tool of a grouped entry, as one markdown list line."""
    label = f"released {_day(tool['released'])}"
    if tool.get("version"):
        label = f"{tool['version']}, {label}"
    line = (f"- **{tool['name']}** ({label}). {tool['summary']} Run `{tool['command']}`; "
            f"[tool page]({tool['page']})")
    return line + (f", {tool['evidence']}." if tool.get("evidence") else ".")


def render_entry(entry):
    """One entry's part of the section, as markdown lines."""
    validate(entry)
    where = entry["where"]
    first = min((t["released"] for t in entry.get("tools", [])), default=entry["released"])
    if entry.get("tools") and first != entry["released"]:
        when = (f"Its tools were released from {_day(first)} to {_day(entry['released'])}; each line gives its tool's "
                "date.")
    elif where == "main":
        when = f"Released {_day(entry['released'])}."
    else:
        url = f"{REPO_URL}/tree/{where['commit']}/{where['path']}"
        when = (f"Released {_day(entry['released'])} as a reviewed package on branch `{where['branch']}`: "
                f"[`{where['path']}/` at commit `{where['commit'][:7]}`]({url}).")
    lines = [f"### {entry['title']}", ""]
    if entry.get("image"):
        image = entry["image"]
        lines += [f"![{image['alt']}]({image['src']})", "", f"*{image['caption']}*", ""]
    lines += [when, "", entry["summary"]]
    if entry.get("commands"):
        lines += ["", "```bash", *entry["commands"], "```"]
    if entry.get("tools"):
        lines += [""] + [render_tool(t) for t in entry["tools"]]
    if entry.get("details"):
        lines += ["", entry["details"]]
    return lines


def ordered(entries, pinned=()):
    """Pinned entries first, in pin order; then newest first, and on the same day the entry added to the list later."""
    by_id = {e["id"]: e for e in entries}
    rest = [e for e in entries if e["id"] not in pinned]
    return [by_id[i] for i in pinned] + [e for _, _, e in sorted(((e["released"], i, e) for i, e in enumerate(rest)),
                                                                key=lambda t: t[:2], reverse=True)]


def intro(registry):
    """The section's first line, which says what comes first."""
    title = {e["id"]: e["title"] for e in registry["releases"]}
    titles = [title[i] for i in registry.get("pinned", [])]
    if not titles:
        return INTRO
    names = titles[0] if len(titles) == 1 else ", ".join(titles[:-1]) + " and " + titles[-1]
    return INTRO.replace(", newest first.", f", {names} first and the rest newest first.")


def render(registry):
    """The whole generated section, marker lines included."""
    registry = validate_list(registry)
    lines = [START, intro(registry)]
    for entry in ordered(registry["releases"], registry.get("pinned", [])):
        lines += [""] + render_entry(entry)
    return "\n".join(lines + [END])


def _span(readme):
    lines = readme.split("\n")
    starts = [i for i, line in enumerate(lines) if line.startswith("<!-- releases:start")]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise ReleaseListError("README needs exactly one releases:start line followed by one releases:end line")
    return lines, starts[0], ends[0]


def apply(readme, registry):
    """README text with its generated section rewritten from the list; everything outside the markers kept."""
    lines, start, end = _span(readme)
    return "\n".join(lines[:start] + render(registry).split("\n") + lines[end + 1:])


def updated(registry_text, readme_text, entry):
    """(new docs/releases.json text, new README text, "added" or "replaced") with entry in the list."""
    registry, action = upsert(json.loads(registry_text), entry)
    return dumps(registry), apply(readme_text, registry), action


def check(registry_path=REGISTRY, readme_path=README):
    """Problems, as a list of strings; empty when the README section matches the list."""
    try:
        registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        readme = Path(readme_path).read_text(encoding="utf-8")
        if apply(readme, registry) != readme:
            return [f"{readme_path}'s releases section is not what {registry_path} gives; "
                    "run python -m kit releases render"]
        if Path(registry_path).read_text(encoding="utf-8") != dumps(registry):
            return [f"{registry_path} is not in its written form; run python -m kit releases render"]
        missing = [e["image"]["src"] for e in registry["releases"] if e.get("image")
                   and not e["image"]["src"].startswith("https://")
                   and not (Path(readme_path).parent / e["image"]["src"]).is_file()]
        if missing:
            return [f"{registry_path} shows pictures that are not in the tree: {', '.join(missing)}"]
        pages = [t["page"] for e in registry["releases"] for t in e.get("tools", [])
                 if not (Path(readme_path).parent / t["page"]).is_file()]
        if pages:
            return [f"{registry_path} links tool pages that are not in the tree: {', '.join(pages)}"]
    except (OSError, ValueError) as exc:
        return [str(exc)]
    return []


def write(registry_path, readme_path, registry):
    readme = Path(readme_path).read_text(encoding="utf-8")
    new_readme = apply(readme, registry)
    Path(registry_path).write_text(dumps(registry), encoding="utf-8")
    Path(readme_path).write_text(new_readme, encoding="utf-8")


def add_arguments(p):
    p.add_argument("--list", dest="registry", default=str(REGISTRY), help="the release list (default docs/releases.json)")
    p.add_argument("--readme", default=str(README), help="the README to rewrite (default README.md)")
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("add", help="add an entry from a JSON file (- for stdin), or replace the one with its id")
    a.add_argument("entry")
    actions.add_parser("render", help="rewrite the README's releases section from the list")
    actions.add_parser("check", help="exit 1 when the README's releases section and the list disagree")
    actions.add_parser("list", help="one line per release, in the section's order")
    for name, text in (("pin", "show this entry first, above newer ones"), ("unpin", "stop showing this entry first")):
        actions.add_parser(name, help=text).add_argument("id")


CLONE_HINT = ("it reads the repository's docs/releases.json and README.md, which an installed package does not have: "
              "run it from a clone (git clone https://github.com/ChaseHendrick/Scrolls), or give --list and --readme")


def run(args):
    if not Path(args.registry).is_file():
        print(f"releases: no release list at {args.registry}; {CLONE_HINT}", file=sys.stderr)
        return 2
    try:
        if args.action == "check":
            problems = check(args.registry, args.readme)
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1 if problems else 0
        registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
        if args.action == "list":
            pinned = validate_list(registry).get("pinned", [])
            for e in ordered(registry["releases"], pinned):
                print(f"{e['released']}  {e['id']:<24} {e['title']}" + ("  (pinned)" if e["id"] in pinned else ""))
                for t in e.get("tools", []):
                    print(f"{t['released']}    {t['id']:<22} {t['name']}  (in {e['id']})")
            return 0
        if args.action in ("pin", "unpin"):
            registry = pin(registry, args.id, on=args.action == "pin")
        if args.action == "add":
            raw = sys.stdin.read() if args.entry == "-" else Path(args.entry).read_text(encoding="utf-8")
            registry, action = upsert(registry, json.loads(raw))
            entry_id = json.loads(raw)["id"]
        write(args.registry, args.readme, registry)
        out = {"releases": len(registry["releases"]), "readme": args.readme}
        if args.action == "add":
            out.update(id=entry_id, action=action)
        print(json.dumps(out))
        return 0
    except (OSError, ValueError) as exc:
        print(f"releases: {exc}", file=sys.stderr)
        return 2


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit releases", description=__doc__.split("\n")[0])
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
