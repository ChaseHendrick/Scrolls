"""Staleness check: what the repository's live pages and registries still say that is no longer true.

The rules review Chase approved on 18 Oct 2026 lists a staleness check at session start among its tooling
(docs/HANDOFF.md, row "Rules relaxed and decisions file"), and the same day he found the private README still using
the reader's old name (docs/DECISIONS.md). Every check reads committed files and local git history only: no network,
no Modal, nothing written. The daily routine `stale` (docs/routines.json) runs it at session start; any agent can
run it by hand:

  python3 -m kit stale [--json] [--only NAME ...] [--now YYYY-MM-DDTHH:MM:SSZ]

The checks, in order (a finding is attention, exit 3; a malformed registry is a failure, exit 1):

  1 handoff-rows   rows of docs/HANDOFF.md not changed for over 7 days (git blame): still current, or done?
  2 branches       branches the handoff's rows name that this clone no longer has (merged branches are deleted
                   automatically since 18 Oct) with no PR or commit named beside them, or that are merged while
                   the clause naming them does not say so (or says not merged, not pushed); a pattern such as
                   `claude/x-wip-<name>` is not a branch, and a branch with no commits of its own is not merged
  3 names          retired names (docs/renames.json) still used on live pages: in a table row always, in prose
                   when the line does not also give the new name
  4 links          relative links on live pages that point at files that are not there
  5 map            docs/MAP.md: paths it names that are gone (a path written after "as" names a file in another
                   tree, such as a released package, and is not checked), and kit modules it has no row for
  6 routines       routines in docs/routines.json still waiting, after 7 days, for a tool that never landed
  7 handoff-paths  handoff rows older than 2 days that name a worktree under /home/user/ or a session scratchpad
                   (neither survives a cloud container)
  8 freezes        docs/compute/freezes.json: a live hash freeze older than 14 days without a collected run, and
                   any freezing commit this clone cannot reach (a spent freeze is checked against it, rule 14)
  9 approvals      docs/compute/modal-approvals.json: an approval in state approved for over 14 days with no
                   Modal ledger row attributed to it since (by ledger_apps or ledger_match, as kit budget
                   attributes rows; it still counts as committed money there)

Live pages (LIVE_PAGES) are the entry files and indexes agents read first plus every tool page. Published records
(docs/prereg/, docs/evidence/, docs/logs/, archives) are byte-frozen and never checked for names or links: a link
there that later moved is corrected by a new note, not by an edit.

A check whose input is absent (no git, no registry file) is skipped and says so. Ages come from git: a row's age is
the committer time of the commit that last changed that line (`git blame`), so a commit that rewrites every row (a
spelling pass) makes them all young again. Branch checks use the refs this clone has, as of its last fetch.

One file in both repositories, as with kit/routines.py. Checks 1 to 7 run wherever their input exists; checks 8
and 9 skip in public Scrolls, which has no docs/compute/freezes.json, no modal-approvals.json and no kit/budget.py.
DEFAULT_BRANCHES lists both repositories' default branches, private first. Standard library only.

History (18 Oct 2026): written in the private workbench, then ported to public Scrolls, where the port added three
changes that both copies now share: check 2 skips in a clone that holds a single branch, such as the depth-1 checkout
of the daily GitHub workflow (.github/workflows/routines.yml), where every other branch a row names would look
deleted; in a shallow clone, checks 1, 6 and 7 add an info line saying ages are lower bounds, because git dates every
line older than the clone's first commit to that commit; and git commit times are read as epoch seconds, because
newer git writes UTC as "Z", which Python 3.10's datetime.fromisoformat refuses. Keep the two files byte-identical.
"""

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from collections import namedtuple
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
EXIT_OK, EXIT_FAIL, EXIT_ATTENTION, EXIT_SKIPPED = 0, 1, 3, 75
OK, ATTENTION, SKIPPED = "ok", "attention", "skipped"

HANDOFF = "docs/HANDOFF.md"
MAP = "docs/MAP.md"
RENAMES = "docs/renames.json"
ROUTINES = "docs/routines.json"
FREEZES = "docs/compute/freezes.json"
APPROVALS = "docs/compute/modal-approvals.json"
LEDGER = "docs/compute/modal-ledger.csv"
PENDING = "docs/tools/pending.json"
DEFAULT_BRANCHES = ("origin/grok/laneJ-title", "grok/laneJ-title", "origin/main", "main")
LIVE_PAGES = ("README.md", "AGENTS.md", "CLAUDE.md", "GLOSSARY.md", "docs/README.md", "docs/MAP.md", HANDOFF,
              "docs/AI-AGENTS.md", "docs/DECISIONS.md", "docs/TOOLBOX.md", "docs/VISION.md", "docs/tools/*.md")
DAYS = {"handoff-rows": 7, "routines": 7, "handoff-paths": 2, "freezes": 14, "approvals": 14}

# Work branches a handoff row may name; the default branch, submission/* and release-readme/* are never deleted.
BRANCH = re.compile(r"(?<![\w/.-])((?:claude|codex|grok|mac-archive)/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)")
KEPT_BRANCHES = ("grok/laneJ-title", "main")
# A name followed by one of these, or ending in "-", is a pattern such as `claude/x-wip-<name>`, not a branch.
PLACEHOLDER_NEXT = "<*{["
# A row splits into clauses at cell borders and sentence ends; a branch mention is judged by its own clause.
CLAUSE_BREAK = re.compile(r"[.;!?](?=\s)|\|")
MERGE_WORD = re.compile(r"\b(?:not\s+(?:yet\s+)?merged|unmerged|not\s+pushed|unpushed|merged)\b", re.I)
PR_OR_COMMIT = re.compile(r"#\d+|/pull/\d+|\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")
# Paths that live only in one container: worktrees under /home/user/ and session scratchpads.
CONTAINER_PATH = re.compile(r"(/home/user/[A-Za-z0-9._/-]*[A-Za-z0-9_/-]"
                            r"|(?:/private)?/tmp/claude-[^\s`)|'\",;]*[^\s`)|'\",;.])")
CHECKOUT_ROOT = re.compile(r"/home/user/Scrolls(?:-private)?(?:/(?!work/|experiments/)[^\s]*)?/?")
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
HISTORY_LINE = re.compile(r"\s*[-*]\s+(\d{4}-\d{2}-\d{2})\b")
MAP_PATH = re.compile(r"`((?:kit|scripts)/[A-Za-z0-9_./-]*[A-Za-z0-9_/])`")
OTHER_TREE = re.compile(r"\bas\s+$", re.I)
KIT_MODULE = re.compile(r"kit/[A-Za-z0-9_]+\.py")
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"), 1)}
TEXT_DATE = re.compile(r"\b(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (\d{4})\b")
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
COMMIT = re.compile(r"[0-9a-f]{7,40}")
FREEZE_STATES = ("live", "spent")

Finding = namedtuple("Finding", "where text")


class StaleError(ValueError):
    """A registry this check reads is malformed: the check fails (exit 1) instead of guessing."""


def utcnow():
    return datetime.now(timezone.utc)


def _day(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _age(now, then):
    return (now - then).total_seconds() / 86400


def _as_time(d):
    """A date (or YYYY-MM-DD) as the start of that UTC day."""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _read(root, rel):
    try:
        return (Path(root) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _load_json(root, rel):
    text = _read(root, rel)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise StaleError(f"{rel} is not JSON: {exc}")


# ---------------------------------------------------------------- git

class Git:
    """Read-only git queries on one clone; every method returns None (or empty) when git cannot answer."""

    def __init__(self, root):
        self.root = Path(root)
        self._refs = None
        self._default = False
        self._first = {}
        self.ok = self.run("rev-parse", "--git-dir") is not None

    def run(self, *args):
        try:
            out = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout if out.returncode == 0 else None

    def blame_times(self, rel):
        """{line number: UTC datetime of the commit that last changed it}; uncommitted lines are left out."""
        out = self.run("blame", "--line-porcelain", "--", rel)
        times, sha, line, when = {}, None, None, None
        for text in (out or "").splitlines():
            if text.startswith("\t"):
                if sha and set(sha) != {"0"} and when is not None:
                    times[line] = when
                sha = None
                continue
            head = text.split(" ")
            if sha is None and len(head) >= 3 and COMMIT.fullmatch(head[0] or "") and len(head[0]) == 40:
                sha, line, when = head[0], int(head[2]), None
            elif head[0] == "committer-time" and len(head) > 1:
                when = datetime.fromtimestamp(int(head[1]), timezone.utc)
        return times

    def refs(self):
        """Short names of the local branches and remote-tracking branches this clone has."""
        if self._refs is None:
            out = self.run("for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes")
            self._refs = set((out or "").split())
        return self._refs

    def default_branch(self):
        if self._default is False:
            self._default = next((b for b in DEFAULT_BRANCHES if b in self.refs()), None)
        return self._default

    def has_branch(self, name):
        return name in self.refs() or f"origin/{name}" in self.refs()

    def branch_ref(self, name):
        return name if name in self.refs() else (f"origin/{name}" if f"origin/{name}" in self.refs() else None)

    def shallow(self):
        """True in a shallow clone, where blame and log -S date older lines to the clone's first commit."""
        return (self.run("rev-parse", "--is-shallow-repository") or "").strip() == "true"

    def has_commit(self, rev):
        return self.run("cat-file", "-e", f"{rev}^{{commit}}") is not None

    def is_ancestor(self, a, b):
        try:
            out = subprocess.run(["git", "-C", str(self.root), "merge-base", "--is-ancestor", a, b],
                                 capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return out.returncode == 0

    def first_parents(self, rev):
        """The commits on rev's first-parent line (the default branch's own history), as a set of full hashes."""
        if rev not in self._first:
            self._first[rev] = set((self.run("rev-list", "--first-parent", rev, "--") or "").split())
        return self._first[rev]

    def merged_into(self, ref, default):
        """True when ref's tip came into default through a merge: an ancestor of default that is not on default's
        first-parent line. A branch with no commits of its own sits on that line (so does a fast-forward merge,
        which GitHub's merge button does not make), and counts as not merged."""
        if not self.is_ancestor(ref, default):
            return False
        tip = (self.run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") or "").strip()
        return bool(tip) and tip not in self.first_parents(default)

    def commit_time(self, rev):
        # Epoch seconds, not %cI: newer git writes UTC as "Z", which Python 3.10's fromisoformat refuses.
        out = self.run("log", "-1", "--format=%ct", rev, "--")
        try:
            return datetime.fromtimestamp(int(out.strip()), timezone.utc) if out and out.strip() else None
        except ValueError:
            return None

    def has_path(self, rev, rel):
        return self.run("cat-file", "-e", f"{rev}:{rel}") is not None

    def first_added(self, rel, needle):
        """UTC time of the first commit whose change to rel added or removed needle, or None."""
        out = self.run("log", "--reverse", "--format=%ct", "-S", needle, "--", rel)
        first = (out or "").strip().splitlines()
        try:
            return datetime.fromtimestamp(int(first[0]), timezone.utc) if first else None
        except ValueError:
            return None

    def tracked(self):
        out = self.run("ls-files", "-z")
        return [p for p in (out or "").split("\0") if p] if out is not None else None


# ---------------------------------------------------------------- shared helpers

def table_rows(text):
    """[(line number, row text, first cell)] of every Markdown table body row (headers and separators left out)."""
    lines = text.splitlines()
    rows = []
    sep = re.compile(r"\|\s*:?-{3,}")
    for i, line in enumerate(lines):
        if not line.startswith("|") or sep.match(line):
            continue
        if i + 1 < len(lines) and sep.match(lines[i + 1]):
            continue   # a header row
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append((i + 1, line, (cells[0] if cells else "")[:70]))
    return rows


def live_pages(root, patterns=LIVE_PAGES):
    root = Path(root)
    out = []
    for pat in patterns:
        hits = sorted(root.glob(pat)) if any(ch in pat for ch in "*?[") else [root / pat]
        out += [p.relative_to(root).as_posix() for p in hits if p.is_file()]
    return list(dict.fromkeys(out))


def _shallow_info(git):
    """An info line for checks that date lines with git, when this clone is shallow; else nothing."""
    if not git.ok or not git.shallow():
        return []
    return ["shallow clone: lines older than its first commit carry that commit's date, so ages are lower bounds"]


def _skip(name, why):
    return {"name": name, "status": SKIPPED, "findings": [], "info": [why]}


def _result(name, findings, info):
    return {"name": name, "status": ATTENTION if findings else OK, "findings": findings, "info": info}


# ---------------------------------------------------------------- 1 handoff-rows

def check_handoff_rows(root, git, now, days=DAYS["handoff-rows"]):
    text = _read(root, HANDOFF)
    if text is None:
        return _skip("handoff-rows", f"no {HANDOFF}")
    if not git.ok:
        return _skip("handoff-rows", "git cannot say when rows changed")
    times = git.blame_times(HANDOFF)
    rows = table_rows(text)
    findings = []
    for n, _, item in rows:
        when = times.get(n)
        if when is not None and _age(now, when) > days:
            findings.append(Finding(f"{HANDOFF}:{n}", f'row "{item}" last changed {_day(when)}, '
                                    f"{_age(now, when):.0f} days ago; check it is current, or move it to the "
                                    "archive when it is done (AGENTS.md rule 14)"))
    return _result("handoff-rows", findings, [f"{len(rows)} rows, {len(findings)} unchanged for over {days:g} days"]
                   + _shallow_info(git))


# ---------------------------------------------------------------- 2 branches

def branch_mentions(row):
    """[(name, start, end)] of the work branches a row names; patterns such as `claude/x-wip-<name>` are left out."""
    out = []
    for m in BRANCH.finditer(row):
        raw = m.group(1)
        if raw.endswith("-") or row[m.end():m.end() + 1] in tuple(PLACEHOLDER_NEXT):
            continue
        name = raw.rstrip(".-/")
        out.append((name, m.start(1), m.start(1) + len(name)))
    return out


def clause(row, start, end):
    """The clause of row around [start, end): from the previous cell border or sentence end to the next one."""
    left = max((m.end() for m in CLAUSE_BREAK.finditer(row, 0, start)), default=0)
    m = CLAUSE_BREAK.search(row, end)
    return row[left:m.start() if m else len(row)], start - left, end - left


def merge_wording(text, start, end):
    """What the clause says about the mention at [start, end): "merged", "not merged" (also unmerged, not pushed)
    or None. The merge word nearest to the mention counts, so "`a` merged, `b` not merged" reads right for both."""
    best = None
    for m in MERGE_WORD.finditer(text):
        dist = start - m.end() if m.end() <= start else max(m.start() - end, 0)
        if best is None or dist < best[0]:
            word = m.group(0).lower()
            best = (dist, "merged" if word == "merged" else "not merged")
    return best[1] if best else None


def check_branches(root, git, now):
    text = _read(root, HANDOFF)
    if text is None:
        return _skip("branches", f"no {HANDOFF}")
    if not git.ok or not git.refs():
        return _skip("branches", "no branch refs in this clone")
    held = {r[len("origin/"):] if r.startswith("origin/") else r for r in git.refs()
            if r != "origin" and not r.endswith("/HEAD")}
    if len(held) < 2:
        return _skip("branches", "this clone holds a single branch (a CI checkout or a single-branch clone), so every "
                     "other branch a row names would look deleted")
    default = git.default_branch()
    findings, named = [], 0
    for n, row, item in table_rows(text):
        mentions = {}
        for name, start, end in branch_mentions(row):
            if name not in KEPT_BRANCHES:
                mentions.setdefault(name, []).append(clause(row, start, end))
        # A branch named twice in one row is judged once: any one mention that records it is enough.
        for name, clauses in mentions.items():
            named += 1
            ref = git.branch_ref(name)
            if ref is None:
                if any(PR_OR_COMMIT.search(said) for said, _, _ in clauses):
                    continue   # its PR or a commit is named beside it: nothing to act on once GitHub deletes it
                findings.append(Finding(f"{HANDOFF}:{n}", f'row "{item}" names branch {name}, which this clone does '
                                        "not have (deleted after its merge, or never pushed), and names no PR or "
                                        "commit beside it; name the merge commit or PR, or push the branch"))
            elif default and git.merged_into(ref, default):
                wordings = [merge_wording(said, s, e) for said, s, e in clauses]
                if "merged" not in wordings:
                    says = "says not merged or not pushed" if "not merged" in wordings else "does not say merged"
                    findings.append(Finding(f"{HANDOFF}:{n}", f'row "{item}" names branch {name}, which is merged '
                                            f"into {default}, but the row {says} beside it"))
    return _result("branches", findings, [f"{named} branch mentions in rows; default branch {default or 'unknown'}; "
                                          "refs as of this clone's last fetch"])


# ---------------------------------------------------------------- 3 names

def load_renames(root):
    data = _load_json(root, RENAMES)
    if data is None:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("renames"), list):
        raise StaleError(f'{RENAMES} needs a list under "renames"')
    out = []
    for i, r in enumerate(data["renames"]):
        if not isinstance(r, dict) or not all(isinstance(r.get(k), str) and r.get(k) for k in
                                              ("old", "new", "since", "source")):
            raise StaleError(f"{RENAMES} renames[{i}] needs old, new, since and source")
        try:
            date.fromisoformat(r["since"])
        except ValueError:
            raise StaleError(f"{RENAMES} renames[{i}].since is not YYYY-MM-DD: {r['since']}")
        keep = r.get("keep", [])
        if not isinstance(keep, list) or not all(isinstance(k, str) and k for k in keep):
            raise StaleError(f"{RENAMES} renames[{i}].keep must be a list of phrases")
        if not isinstance(r.get("allow_formerly", True), bool):
            raise StaleError(f"{RENAMES} renames[{i}].allow_formerly must be true or false")
        out.append(r)
    return out


def _name_pattern(name):
    return re.compile(r"(?<![\w-])" + r"\s+".join(map(re.escape, name.split())), re.I)


def stale_name_hits(text, rename):
    """[(line number, in a table row)] of lines that still use rename's old name. Fenced code, inline code spans
    and the rename's `keep` phrases are left out first, and so are dated history bullets from before the rename.
    A table row is stale whenever the old name remains, even beside the new one, since a table names the thing;
    a prose line that also gives the new name ("X, formerly Y") passes unless the rename sets allow_formerly false."""
    old, new = _name_pattern(rename["old"]), _name_pattern(rename["new"])
    keep = [_name_pattern(k) for k in rename.get("keep", [])]
    formerly = rename.get("allow_formerly", True)
    blanked = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    out = []
    for n, line in enumerate(blanked.splitlines(), 1):
        prose = INLINE_CODE.sub(" ", line)
        for k in keep:
            prose = k.sub(" ", prose)
        if not old.search(prose):
            continue
        m = HISTORY_LINE.match(line)
        if m and m.group(1) < rename["since"]:
            continue
        table = line.lstrip().startswith("|")
        if formerly and not table and new.search(prose):
            continue
        out.append((n, table))
    return out


def stale_name_lines(text, rename):
    """Line numbers of stale_name_hits."""
    return [n for n, _ in stale_name_hits(text, rename)]


def check_names(root, git=None, now=None):
    renames = load_renames(root)
    if renames is None:
        return _skip("names", f"no {RENAMES}")
    findings, pages = [], live_pages(root)
    for rel in pages:
        text = _read(root, rel) or ""
        flagged = {}
        for r in renames:   # registry order: a line that a longer old name flags is not flagged again by a shorter one
            for n, table in stale_name_hits(text, r):
                flagged.setdefault(n, (r, table))
        for n in sorted(flagged):
            r, table = flagged[n]
            renamed = f'renamed "{r["new"]}" on {r["since"]} ({r["source"]})'
            fix = (f'a table row names the thing, so write "{r["new"]}" alone' if table else
                   f'write "{r["new"]}"')
            findings.append(Finding(f"{rel}:{n}", f'says "{r["old"]}", {renamed}; {fix}'))
    return _result("names", findings, [f"{len(renames)} retired names on {len(pages)} live pages"])


# ---------------------------------------------------------------- 4 links

def known_paths(root, git):
    files = git.tracked() if git is not None and git.ok else None
    if files is None:
        return None
    known = set(files)
    for rel in files:
        parts = rel.split("/")
        known.update("/".join(parts[:i]) for i in range(1, len(parts)))
    pending = _load_json(root, PENDING)
    if isinstance(pending, dict):
        known.update(f"docs/tools/{pid}.md" for pid in pending.get("pages", []))
    return known


def dead_links(root, rel, text, known):
    out = []
    root = Path(root).resolve()
    page = root / rel
    for target in MD_LINK.findall(FENCE.sub("", text)):
        if target.startswith("#") or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target):
            continue
        path = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not path:
            continue
        base = root if path.startswith("/") else page.parent
        resolved = (base / path.lstrip("/")).resolve()
        try:
            key = resolved.relative_to(root).as_posix()
        except ValueError:
            key = None
        exists = key is not None and (key == "." or (key in known if known is not None else resolved.exists()))
        if not exists:
            out.append(target)
    return out


def check_links(root, git, now=None):
    pages = live_pages(root)
    if not pages:
        return _skip("links", "no live pages")
    known = known_paths(root, git)
    findings = []
    for rel in pages:
        for target in dead_links(root, rel, _read(root, rel) or "", known):
            findings.append(Finding(rel, f"link to {target} does not resolve"))
    basis = "git's tracked files" if known is not None else "the files on disk"
    return _result("links", findings, [f"{len(pages)} live pages against {basis}"])


# ---------------------------------------------------------------- 5 map

def check_map(root, git, now=None):
    text = _read(root, MAP)
    if text is None:
        return _skip("map", f"no {MAP}")
    root = Path(root)
    known = known_paths(root, git)
    findings = []
    # A path written after "as" names a file in another tree ("shipped in the AutoPipeline cut as
    # `scripts/get_vc3d.py`"), not one in this repository.
    paths = {m.group(1) for m in MAP_PATH.finditer(text) if not OTHER_TREE.search(text[max(0, m.start() - 40):m.start()])}
    for path in sorted(paths):
        key = path.rstrip("/")
        there = key in known if known is not None else (root / key).exists()
        if not there:
            findings.append(Finding(MAP, f"names {path}, which is not in the repository; update or remove its row"))
    modules = sorted(p for p in (known if known is not None else
                                 [q.relative_to(root).as_posix() for q in root.glob("kit/*.py")])
                     if KIT_MODULE.fullmatch(p) and p not in ("kit/__init__.py", "kit/__main__.py"))
    mapped = set(re.findall(r"`(kit/[A-Za-z0-9_]+\.py)`", text))
    missing = [m for m in modules if m not in mapped]
    if missing:
        shown = ", ".join(missing[:12]) + (f" and {len(missing) - 12} more" if len(missing) > 12 else "")
        findings.append(Finding(MAP, f"{len(missing)} kit modules have no row: {shown}"))
    return _result("map", findings, [f"{len(modules)} kit modules, {len(modules) - len(missing)} with a row"])


# ---------------------------------------------------------------- 6 routines

def check_routines(root, git, now, days=DAYS["routines"]):
    data = _load_json(root, ROUTINES)
    if data is None:
        return _skip("routines", f"no {ROUTINES}")
    if not isinstance(data, dict) or not isinstance(data.get("routines"), list):
        raise StaleError(f'{ROUTINES} needs a list under "routines"')
    root = Path(root)
    findings, waiting = [], 0
    for r in data["routines"]:
        missing = [p for p in r.get("requires", []) if not (root / p).exists()]
        if not missing:
            continue
        waiting += 1
        added = git.first_added(ROUTINES, f'"name": "{r.get("name")}"') if git.ok else None
        if added is None:
            continue
        if _age(now, added) > days:
            findings.append(Finding(ROUTINES, f"routine {r.get('name')} has waited {_age(now, added):.0f} days "
                                    f"(since {_day(added)}) for {', '.join(missing)}; land the tool or remove the "
                                    "routine"))
    return _result("routines", findings, [f"{len(data['routines'])} routines, {waiting} waiting for a missing path"]
                   + _shallow_info(git))


# ---------------------------------------------------------------- 7 handoff-paths

def container_paths(row):
    return [p for p in dict.fromkeys(CONTAINER_PATH.findall(row)) if not CHECKOUT_ROOT.fullmatch(p)]


def check_handoff_paths(root, git, now, days=DAYS["handoff-paths"]):
    text = _read(root, HANDOFF)
    if text is None:
        return _skip("handoff-paths", f"no {HANDOFF}")
    if not git.ok:
        return _skip("handoff-paths", "git cannot say when rows changed")
    times = git.blame_times(HANDOFF)
    findings, named = [], 0
    for n, row, item in table_rows(text):
        paths = container_paths(row)
        named += bool(paths)
        when = times.get(n)
        if paths and when is not None and _age(now, when) > days:
            findings.append(Finding(f"{HANDOFF}:{n}", f'row "{item}" (last changed {_day(when)}) names '
                                    f"{', '.join(paths)}, which does not survive the cloud container; record the "
                                    "branch and commit, or a committed path, instead"))
    return _result("handoff-paths", findings, [f"{named} rows name a container path"] + _shallow_info(git))


# ---------------------------------------------------------------- 8 freezes (private)

def load_freezes(root):
    data = _load_json(root, FREEZES)
    if data is None:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("freezes"), list):
        raise StaleError(f'{FREEZES} needs a list under "freezes"')
    problems, seen = [], set()
    for i, f in enumerate(data["freezes"]):
        fid = f.get("id") if isinstance(f, dict) else None
        if not isinstance(fid, str) or not fid:
            problems.append(f"freezes[{i}] needs an id")
            continue
        if fid in seen:
            problems.append(f"{fid} is listed twice")
        seen.add(fid)
        for key in ("prereg", "note"):
            if not isinstance(f.get(key), str) or not f.get(key):
                problems.append(f"{fid}: {key} is required")
        if not isinstance(f.get("freezing_commit"), str) or not COMMIT.fullmatch(f["freezing_commit"]):
            problems.append(f"{fid}: freezing_commit must be a commit hash of 7 to 40 hex digits")
        if f.get("state") not in FREEZE_STATES:
            problems.append(f"{fid}: state must be live or spent")
        if "collected_on" not in f:
            problems.append(f"{fid}: collected_on is required (null when nothing is collected yet)")
        for key in ("collected_on", "frozen_on"):
            if f.get(key) is not None:
                try:
                    date.fromisoformat(f[key])
                except (TypeError, ValueError):
                    problems.append(f"{fid}: {key} must be YYYY-MM-DD or null")
        if f.get("state") == "spent" and not f.get("collected_on"):
            problems.append(f"{fid}: a spent freeze needs collected_on")
    if problems:
        raise StaleError(f"{FREEZES}: " + "; ".join(problems))
    return data["freezes"]


def check_freezes(root, git, now, days=DAYS["freezes"]):
    freezes = load_freezes(root)
    if freezes is None:
        return _skip("freezes", f"no {FREEZES}")
    root = Path(root)
    default = git.default_branch() if git.ok else None
    findings, live = [], 0
    for f in freezes:
        fid, commit, branch = f["id"], f["freezing_commit"], f.get("branch")
        on = f" (branch {branch})" if branch else ""
        present = git.ok and git.has_commit(commit)
        if git.ok and not present:
            findings.append(Finding(FREEZES, f"{fid}: freezing commit {commit}{on} is not in this clone; push or "
                                    "fetch it, since checks of a spent freeze read the recorded files at it (rule 14)"))
        elif present:
            reach = default and git.is_ancestor(commit, default)
            ref = git.branch_ref(branch) if branch else None
            if not reach and not (ref and git.is_ancestor(commit, ref)):
                where = f"branch {branch} is not in this clone" if branch and not ref else "no branch is recorded"
                findings.append(Finding(FREEZES, f"{fid}: freezing commit {commit} is not on "
                                        f"{default or 'the default branch'} and {where}; merge it or record the "
                                        "branch that keeps it"))
        prereg = f["prereg"]
        if not (root / prereg).exists() and not (present and git.has_path(commit, prereg)):
            findings.append(Finding(FREEZES, f"{fid}: prereg {prereg} is neither in the working tree nor at {commit}"))
        if f["state"] != "live":
            continue
        live += 1
        frozen = _as_time(f["frozen_on"]) if f.get("frozen_on") else (git.commit_time(commit) if present else None)
        if frozen is None:
            findings.append(Finding(FREEZES, f"{fid}: cannot date the freeze; add frozen_on"))
            continue
        start = max(frozen, _as_time(f["collected_on"])) if f.get("collected_on") else frozen
        if _age(now, start) > days:
            last = f"last collected {f['collected_on']}" if f.get("collected_on") else "nothing collected"
            findings.append(Finding(FREEZES, f"{fid}: live since {_day(frozen)}, {last}, {_age(now, start):.0f} days "
                                    "without a collected run; collect it and mark it spent (AI-AGENTS.md rule 14), "
                                    "or note why it stays live"))
    return _result("freezes", findings, [f"{len(freezes)} freezes, {live} live"])


# ---------------------------------------------------------------- 9 approvals (private)

def approval_date(a, git=None):
    """The day an approval was given: approved_on, else the first dated phrase in its approved text, else when its
    id first appeared in the approvals file (git); None when none of these says."""
    if a.get("approved_on"):
        return _as_time(a["approved_on"])
    text = a.get("approved") or ""
    hits = []
    m = TEXT_DATE.search(text)
    if m:
        hits.append((m.start(), date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))))
    m = ISO_DATE.search(text)
    if m:
        try:
            hits.append((m.start(), date(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
        except ValueError:
            pass
    if hits:
        return _as_time(min(hits)[1])
    if git is not None and git.ok:
        added = git.first_added(APPROVALS, f'"id": "{a.get("id")}"')
        return _as_time(added.date()) if added else None
    return None


def check_approvals(root, git, now, days=DAYS["approvals"]):
    root = Path(root)
    if not (root / APPROVALS).is_file():
        return _skip("approvals", f"no {APPROVALS}")
    try:
        from . import budget, modalledger
    except ImportError:
        return _skip("approvals", "kit.budget is not in this repository")
    try:
        data = budget.load_approvals(root / APPROVALS)
    except budget.BudgetError as exc:
        raise StaleError(str(exc))
    try:
        _, rows = modalledger.read(root / LEDGER) if (root / LEDGER).is_file() else (None, [])
    except (OSError, modalledger.LedgerRowError) as exc:
        raise StaleError(f"cannot read {LEDGER}: {exc}")
    approvals = data.get("approvals") or []
    last_row = {}
    for row in rows:
        try:
            owner = budget._owner(row, approvals)
        except budget.BudgetError:
            continue
        t = budget.ledger_time(row.get("date_time_et"))
        if owner and t and (owner not in last_row or t > last_row[owner]):
            last_row[owner] = t
    findings, open_ = [], 0
    for a in approvals:
        if a.get("state") != "approved":
            continue
        open_ += 1
        when = approval_date(a, git)
        if when is None:
            findings.append(Finding(APPROVALS, f"{a['id']}: cannot date the approval; add approved_on"))
            continue
        latest = last_row.get(a["id"])
        if _age(now, when) > days and (latest is None or latest < when):
            head = f"{a['id']} (cap {a.get('cap_usd')} USD) approved {_day(when)}, {_age(now, when):.0f} days ago"
            if not (a.get("ledger_apps") or a.get("ledger_match")):
                findings.append(Finding(APPROVALS, f"{head}, names no ledger_apps or ledger_match, so no ledger row "
                                        "can be attributed to it; if it ran, add its app id to ledger_apps and set "
                                        "its state to done, else launch it or set its state to done or blocked (an "
                                        "open approval still counts in kit budget)"))
            else:
                findings.append(Finding(APPROVALS, f"{head}, with no ledger row attributed to it (by ledger_apps or "
                                        "ledger_match) since; launch it, or set its state to done or blocked (an "
                                        "open approval still counts in kit budget)"))
    return _result("approvals", findings, [f"{open_} approvals in state approved"])


# ---------------------------------------------------------------- running

CHECKS = (("handoff-rows", check_handoff_rows), ("branches", check_branches), ("names", check_names),
          ("links", check_links), ("map", check_map), ("routines", check_routines),
          ("handoff-paths", check_handoff_paths), ("freezes", check_freezes), ("approvals", check_approvals))
NAMES = tuple(n for n, _ in CHECKS)


def run_checks(root=ROOT, now=None, only=(), days=None, git=None):
    """{"exit": code, "checks": [results]}; a malformed registry makes its check "fail" and the exit 1."""
    now = now or utcnow()
    git = git or Git(root)
    days = dict(DAYS, **(days or {}))
    results = []
    for name, fn in CHECKS:
        if only and name not in only:
            continue
        kw = {"days": days[name]} if name in days else {}
        try:
            res = fn(root, git, now, **kw)
        except StaleError as exc:
            res = {"name": name, "status": "fail", "findings": [], "info": [str(exc)]}
        res["findings"] = [{"where": f.where, "text": f.text} if isinstance(f, Finding) else f for f in res["findings"]]
        results.append(res)
    statuses = {r["status"] for r in results}
    code = EXIT_FAIL if "fail" in statuses else EXIT_ATTENTION if ATTENTION in statuses else (
        EXIT_SKIPPED if results and statuses == {SKIPPED} else EXIT_OK)
    return {"exit": code, "now": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "checks": results}


def format_report(report):
    checks = report["checks"]
    look = [c for c in checks if c["status"] in (ATTENTION, "fail")]
    lines = [f"kit stale: {len(checks)} checks, {len(look)} need a look ({report['now']})"]
    for c in checks:
        lines.append(f"{c['status']:<9} {c['name']:<13} {'; '.join(c['info'])}")
    for c in look:
        lines.append("")
        lines.append(f"--- {c['name']} ({c['status']}) ---")
        lines += [f"{f['where']}: {f['text']}" for f in c["findings"]] or c["info"]
    return "\n".join(lines)


def add_arguments(p):
    p.add_argument("--only", action="append", default=[], choices=NAMES, help="run only this check (repeatable)")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.add_argument("--now", help="judge ages as of this UTC time, YYYY-MM-DDTHH:MM:SSZ (default: now)")
    for name, d in DAYS.items():
        p.add_argument(f"--{name}-days", type=float, default=d, dest=f"days_{name.replace('-', '_')}",
                       help=f"age threshold of the {name} check in days (default {d:g})")


def run(args):
    now = None
    if args.now:
        try:
            now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        except ValueError:
            print(f"kit stale: --now is not an ISO time: {args.now}", file=sys.stderr)
            return 2
        now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    days = {name: getattr(args, f"days_{name.replace('-', '_')}") for name in DAYS}
    report = run_checks(ROOT, now, tuple(args.only), days)
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return report["exit"]


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit stale", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
