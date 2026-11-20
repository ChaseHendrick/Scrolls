"""Review pins: tie a review verdict (GO, NO-GO, GO-WITH-NOTES) to the commit it covered, and say whether it still
covers a pull request's head. For any git repository; standard library only.

Independent reviews return their verdict as free text, and then someone asks for "rerun the review at the PR head
before merge", because nobody can tell whether the head moved past what was reviewed, or moved only by merging the
base branch in. This tool records each verdict with its commit, and compares the PR's own patch at that commit with
its own patch at the head:

  python3 -m kit reviewpin [--root DIR] [--log PATH] record PR SHA VERDICT [--scope PATH ...] [--reviewer TEXT]
                                                       [--note TEXT] [--base REF] [--dry-run]
  python3 -m kit reviewpin delta PR [--head REF] [--base REF] [--no-fetch] [--log-from REF] [--json]
  python3 -m kit reviewpin explain PR [--head REF] [--base REF] [--no-fetch] [--log-from REF] [--json]
  python3 -m kit reviewpin list [--pr N] [--json]

A PR's own patch at a commit is `git diff` from the commit's merge base with the base branch to the commit. A commit
that only merges the base branch in moves the merge base with it, so the own patch stays the same and the verdict
carries. Patches are compared file by file and hunk by hunk, each hunk keyed on its changed lines and its three
context lines with line numbers and blob hashes dropped, so a base change elsewhere in a file does not count as a
change of the PR, while moving the PR's own line to another place does.

When the patches differ, a head that only merged the base in may still keep the pin as a derived cover
(derived_cover): every commit after the pin is a two-parent merge of the base, each file's own change is compared by
content (own_change: -U0 lines, or a JSON value for a .json file) and each merge is replayed with git merge-tree, so
a conflict resolved by hand or an edit inside the merge voids the pin. `explain` prints every one of those checks
with OK or FAIL and, for each file, the compare mode and the items only at the head and only at the pin.

Verdicts are appended to freeze/verdicts.jsonl (LOG; --log or KIT_REVIEWPIN_LOG moves it), one JSON object per
line. Nothing is deleted; a later verdict for the same PR supersedes an earlier one. `delta --log-from REF` reads the
log as commit REF has it instead of the working tree; a merge gate should read it from the base branch it fetched,
never from the PR or the merged tree, so a PR cannot record its own GO. The base branch defaults to origin/main
(KIT_REVIEWPIN_BASE, or --base). git is the only outside tool, and the network is used only by `delta` without
`--head` or `--no-fetch` (`git fetch origin` of the PR head and the base branch).
"""

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

LOG_ENV, BASE_ENV = "KIT_REVIEWPIN_LOG", "KIT_REVIEWPIN_BASE"
LOG = os.environ.get(LOG_ENV) or "freeze/verdicts.jsonl"     # relative to the repository root
DEFAULT_BASE = os.environ.get(BASE_ENV) or "origin/main"
VERDICTS = ("GO", "NO-GO", "GO-WITH-NOTES")
EXIT_CARRIES, EXIT_ERROR, EXIT_NO_VERDICT, EXIT_RECHECK, EXIT_NOGO = 0, 1, 2, 3, 4
FETCH_TIMEOUT_S = 120
LINE_CUT = 160
DIFF_ARGS = ("diff", "--no-color", "--no-ext-diff", "--no-renames", "--full-index", "--binary", "--unified=3")


class PinError(Exception):
    """Bad input or a git failure; the message says which."""


def _git(root, *args, check=True, timeout=None):
    """Run git in root and return its stdout; raise PinError when check and git fails."""
    try:
        p = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=str(root), capture_output=True,
                           text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise PinError(f"git {args[0]} failed: {e}")
    if check and p.returncode:
        raise PinError(f"git {' '.join(args[:3])} failed: {p.stderr.strip() or p.returncode}")
    return p.stdout


def default_root(cwd=None):
    """The repository reviewpin works in: the git top level of cwd (default the current folder), else cwd."""
    here = Path(cwd or os.getcwd())
    try:
        p = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(here), capture_output=True, text=True)
    except OSError:
        return here
    return Path(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip() else here


def _resolve(root, ref):
    """The full commit hash of ref, or None when this clone does not have it."""
    try:
        p = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=str(root),
                           capture_output=True, text=True)
    except OSError:
        return None
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def _merge_base(root, a, b):
    p = subprocess.run(["git", "merge-base", a, b], cwd=str(root), capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def parse_pr(text):
    m = re.fullmatch(r"#?(\d+)", str(text).strip())
    if not m or int(m.group(1)) <= 0:
        raise PinError(f"not a PR number: {text}")
    return int(m.group(1))


def parse_verdict(text):
    v = str(text).strip().upper().replace("_", "-").replace(" ", "-")
    if v not in VERDICTS:
        raise PinError(f"verdict must be one of {', '.join(VERDICTS)}: {text}")
    return v


def _now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- the verdict log -------------------------------------------------------------------------------------------------

def read_log(root, log=None):
    """Every verdict in the log, in file order; a malformed line raises PinError with its number."""
    path = Path(root) / (log or LOG)
    if not path.exists():
        return []
    return parse_log_text(path.read_text(encoding="utf-8"), path.name)


def read_log_at(root, ref, log=None):
    """Every verdict in the log as commit REF has it (empty when REF has no log); PinError on a malformed line or an
    unknown REF."""
    log = log or LOG
    if not _resolve(root, ref):
        raise PinError(f"log ref not found: {ref}")
    p = subprocess.run(["git", "cat-file", "-e", f"{ref}:{log}"], cwd=str(root), capture_output=True, text=True)
    if p.returncode:
        return []
    return parse_log_text(_git(root, "show", f"{ref}:{log}"), f"{log} at {ref}")


def parse_log_text(text, name=LOG):
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise PinError(f"{name} line {n} is not JSON: {e}")
        if not isinstance(rec, dict) or "pr" not in rec or "sha" not in rec:
            raise PinError(f"{name} line {n} has no pr or sha")
        out.append(rec)
    return out


def latest(records, pr):
    """The latest verdict for pr: the newest time, the later line on a tie; None when there is none."""
    mine = [(r.get("time") or "", i, r) for i, r in enumerate(records) if r.get("pr") == pr]
    return max(mine, key=lambda t: (t[0], t[1]))[2] if mine else None


def _branches_at(root, sha):
    p = subprocess.run(["git", "branch", "--format=%(refname:short)", "--points-at", sha], cwd=str(root),
                       capture_output=True, text=True)
    return [b for b in p.stdout.split() if b] if p.returncode == 0 else []


def make_record(root, pr, sha, verdict, scope=(), reviewer=None, note=None, base=DEFAULT_BASE, branch=None,
                time=None):
    """The verdict line for pr at sha; raises PinError when the sha is not a commit in this clone."""
    pr, verdict = parse_pr(pr), parse_verdict(verdict)
    full = _resolve(root, sha)
    if not full:
        raise PinError(f"commit not found in this clone: {sha} (fetch it first, for example "
                       f"git fetch origin pull/{pr}/head)")
    if branch is None:
        here = _branches_at(root, full)
        branch = here[0] if len(here) == 1 else None
    mb = _merge_base(root, full, base) if _resolve(root, base) else None
    if mb == full:
        mb = None                       # the commit is already in the base: its own patch is not knowable from it
    return {"pr": pr, "sha": full, "verdict": verdict, "scope": [s for s in scope if s], "reviewer": reviewer,
            "time": time or _now_utc(), "note": note, "base": base, "merge_base": mb, "branch": branch}


def append(root, rec, log=None):
    """Add one verdict line to the log (LOG under root, or log relative to root); returns its path."""
    path = Path(root) / (log or LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    return path


# ---- patches ---------------------------------------------------------------------------------------------------------

def split_patch(text):
    """{path: {"head": [lines], "hunks": [(header, (body lines))]}} from a git diff with context (--unified=3).
    The head keeps mode, new, deleted and binary lines and drops the index line (its blob hashes change when the
    base changes the file); a hunk is keyed by its +, -, context and no-newline lines, without its line numbers,
    so the same added line at another place in the file is a different hunk."""
    files, cur, hunk = {}, None, None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            path = m.group(2) if m else line[len("diff --git "):]
            cur = files.setdefault(path, {"head": [], "hunks": []})
            hunk = None
        elif cur is None:
            continue
        elif line.startswith("@@"):
            hunk = [line, []]
            cur["hunks"].append(hunk)
        elif hunk is not None and line[:1] in ("+", "-", " ", "\\"):
            hunk[1].append(line)
        elif line.startswith("index "):
            continue
        else:
            hunk = None
            cur["head"].append(line)
    for f in files.values():
        f["hunks"] = [(h, tuple(b)) for h, b in f["hunks"]]
    return files


def _own_patch(root, sha, mb):
    return split_patch(_git(root, *DIFF_ARGS, mb, sha, "--"))


def in_scope(path, scope):
    for s in scope:
        s = s.strip()
        if not s:
            continue
        if path == s or path.startswith(s.rstrip("/") + "/") or fnmatch.fnmatchcase(path, s):
            return True
    return False


def compare(old, new):
    """The files whose own patch differs, each with the hunks only in the head and only at the reviewed commit."""
    out = []
    for path in sorted(set(old) | set(new)):
        a, b = old.get(path), new.get(path)
        if a and b and a["head"] == b["head"] and [h[1] for h in a["hunks"]] == [h[1] for h in b["hunks"]]:
            continue
        if a is None:
            kind = "added to the PR since review"
        elif b is None:
            kind = "dropped from the PR since review"
        else:
            kind = "changed since review"
        ah = a["hunks"] if a else []
        bh = b["hunks"] if b else []
        same_head = a is not None and b is not None and a["head"] == b["head"]
        out.append({"path": path, "change": kind, "head_lines": [] if same_head or b is None else b["head"],
                    "new_hunks": [{"at": h, "lines": list(body)} for h, body in _keyed_minus(bh, ah)],
                    "gone_hunks": [{"at": h, "lines": list(body)} for h, body in _keyed_minus(ah, bh)]})
    return out


def _keyed_minus(a, b):
    """Hunks of a whose bodies are not matched one for one by bodies in b (a repeated hunk counts each time)."""
    left = [x[1] for x in b]
    out = []
    for h in a:
        if h[1] in left:
            left.remove(h[1])
        else:
            out.append(h)
    return out


# ---- delta -----------------------------------------------------------------------------------------------------------

def fetch_head(root, pr, base, fetch=True):
    """(sha, ref, notes) for the PR head: refs/pull/PR/head fetched from origin, else the local copy of that ref.
    Fetching also refreshes the base branch when it is origin/NAME, so a head that merged a newer base finds it."""
    notes = []
    ref = f"refs/pull/{pr}/head"
    if fetch:
        try:
            _git(root, "fetch", "-q", "origin", f"+refs/pull/{pr}/head:{ref}", timeout=FETCH_TIMEOUT_S)
            if base.startswith("origin/"):
                name = base[len("origin/"):]
                _git(root, "fetch", "-q", "origin", f"+refs/heads/{name}:refs/remotes/origin/{name}",
                    timeout=FETCH_TIMEOUT_S)
        except PinError as e:
            notes.append(f"fetch failed, using local refs: {e}")
    sha = _resolve(root, ref)
    if sha and not fetch:
        notes.append(f"{ref} as of this clone's last fetch")
    return sha, (ref if sha else None), notes


def delta(root, pr, head=None, base=DEFAULT_BASE, fetch=True, log=None, log_ref=None, always_in_scope=(),
          explain=False):
    """Whether the latest verdict for pr covers the head. Returns a dict with status carries, recheck, nogo or
    no-verdict, the reviewed and head commits, their merge bases and the changed files and hunks. LOG_REF: read the
    verdicts as that commit has them (a merge gate passes the base branch it fetched), not from the working tree.
    ALWAYS_IN_SCOPE: paths counted inside the review's scope whatever it says (such as files a merge gate holds).
    EXPLAIN: run every derived-cover check that can run and keep them under "checks" (kit reviewpin explain); the
    status is the same either way."""
    pr = parse_pr(pr)
    rec = latest(read_log_at(root, log_ref, log) if log_ref else read_log(root, log), pr)
    out = {"pr": pr, "status": "no-verdict", "exit": EXIT_NO_VERDICT, "verdict": None, "notes": [], "changes": []}
    if rec is None:
        out["message"] = f"no verdict recorded for PR {pr} in {log or LOG}" + (f" at {log_ref}" if log_ref else "")
        return out
    out.update(verdict=rec["verdict"], reviewed=rec["sha"], reviewer=rec.get("reviewer"), reviewed_at=rec.get("time"),
               scope=rec.get("scope") or [], base=base)
    if not _resolve(root, rec["sha"]):
        raise PinError(f"the reviewed commit {rec['sha'][:12]} is not in this clone (git fetch origin pull/{pr}/head)")
    if head:
        head_sha, head_ref = _resolve(root, head), head
        if not head_sha:
            raise PinError(f"--head not found: {head}")
    else:
        head_sha, head_ref, notes = fetch_head(root, pr, base, fetch)
        out["notes"] += notes
        if not head_sha and rec.get("branch"):
            head_sha, head_ref = _resolve(root, rec["branch"]), rec["branch"]
            if head_sha:
                out["notes"].append(f"head taken from the local branch {rec['branch']} stored with the verdict")
        if not head_sha:
            raise PinError(f"no head for PR {pr}: pass --head REF (no refs/pull/{pr}/head and no stored branch)")
    if not _resolve(root, base):
        raise PinError(f"base not found: {base}")
    out.update(head=head_sha, head_ref=head_ref)
    old_mb = rec.get("merge_base") if rec.get("merge_base") and _resolve(root, rec["merge_base"]) else None
    if old_mb and rec.get("base") not in (None, base):
        old_mb = None
    old_mb = old_mb or _merge_base(root, rec["sha"], base)
    new_mb = _merge_base(root, head_sha, base)
    if not old_mb or not new_mb:
        raise PinError(f"no merge base with {base}")
    if old_mb == rec["sha"]:
        raise PinError(f"the reviewed commit {old_mb[:12]} is already in {base}, so its own patch cannot be found; "
                       f"pass --base with the base commit from before the merge")
    if new_mb == head_sha:
        raise PinError(f"the head {head_sha[:12]} is already in {base}, so the PR's own patch cannot be found; "
                       f"pass --base with the base commit from before the merge")
    out.update(reviewed_base=old_mb, head_base=new_mb)
    if head_sha == rec["sha"]:
        changes = []
        out["notes"].append("the head is the reviewed commit")
    else:
        changes = compare(_own_patch(root, rec["sha"], old_mb), _own_patch(root, head_sha, new_mb))
        moved = _git(root, "rev-list", "--count", f"{rec['sha']}..{head_sha}", check=False).strip()
        if moved.isdigit():
            out["notes"].append(f"the head is {moved} commit(s) past the reviewed commit")
    scope = out["scope"]
    for c in changes:
        c["in_scope"] = (in_scope(c["path"], scope) if scope else True) or c["path"] in set(always_in_scope)
    out["changes"] = changes
    inside = [c for c in changes if c["in_scope"]]
    outside = [c for c in changes if not c["in_scope"]]
    if outside:
        out["notes"].append(f"{len(outside)} file(s) changed outside the review's scope: "
                            + ", ".join(c["path"] for c in outside))
    if rec["verdict"] == "NO-GO":
        if inside:
            out.update(status="recheck", exit=EXIT_RECHECK,
                       message=f"NO-GO at {rec['sha'][:12]}; the patch changed since, so it needs a recheck")
        else:
            out.update(status="nogo", exit=EXIT_NOGO,
                       message=f"NO-GO stands: the PR's own patch is unchanged since {rec['sha'][:12]}")
    elif inside:
        paths = [c["path"] for c in inside]
        if explain:
            checks = derive_checks(root, rec, head_sha, base, old_mb, new_mb, paths, stop=False)
            ok, why = judge_checks(checks, base, paths)
            for c in checks:
                if c["check"] == "own change":
                    c["compare"] = explain_own_change(c.pop("old"), c.pop("new"))
            out["checks"] = checks
        else:
            ok, why = derived_cover(root, rec, head_sha, base, old_mb, new_mb, paths)
        out["derive"] = why
        if ok:
            out.update(status="carries", exit=EXIT_CARRIES, derived=True,
                       message=f"{rec['verdict']} carries as a derived cover ({why})")
        else:
            out.update(status="recheck", exit=EXIT_RECHECK,
                       message=f"{rec['verdict']} at {rec['sha'][:12]} does not cover the head: "
                               f"{len(inside)} file(s) changed since review")
    else:
        why = "own patch identical" if not changes else "changes only outside the review's scope"
        out.update(status="carries", exit=EXIT_CARRIES, message=f"{rec['verdict']} carries ({why})")
    return out


# ---- derived cover: a head that only merged the default branch in -------------------------------------------------

def _when(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _show(root, commit, path):
    p = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=str(root), capture_output=True)
    return p.stdout if p.returncode == 0 else None


def _canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def json_delta(a, b, path="$"):
    """The change from JSON value A to B as a sorted list of (path, kind, value): objects compared key by key, lists as
    multisets of their entries (so entry order does not matter), anything else by value."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            sub = f"{path}.{k}"
            if k not in a:
                out.append((sub, "added", _canon(b[k])))
            elif k not in b:
                out.append((sub, "removed", _canon(a[k])))
            else:
                out += json_delta(a[k], b[k], sub)
        return sorted(out)
    if isinstance(a, list) and isinstance(b, list):
        left, right = [_canon(x) for x in a], [_canon(x) for x in b]
        gone, came = list(left), []
        for x in right:
            if x in gone:
                gone.remove(x)
            else:
                came.append(x)
        return sorted([(path, "entry removed", x) for x in gone] + [(path, "entry added", x) for x in came])
    return [] if _canon(a) == _canon(b) else [(path, "changed", f"{_canon(a)} -> {_canon(b)}")]


def own_change(root, mb, sha, path):
    """A file's own change from the merge base MB to SHA, by content: for a .json file whose both sides parse, the
    json_delta of the parsed values (so a reordered list or object compares equal); otherwise the file's header
    lines and its -U0 diff lines (+ and - lines only, no line numbers or context). The first item names the mode:
    json or text (MODES)."""
    if path.endswith(".json"):
        a, b = _show(root, mb, path), _show(root, sha, path)
        try:
            return ("json", tuple(json_delta(json.loads(a) if a is not None else None,
                                             json.loads(b) if b is not None else None)))
        except (ValueError, UnicodeDecodeError):
            pass
    text = _git(root, "diff", "--no-color", "--no-ext-diff", "--no-renames", "--binary", "--unified=0", mb, sha,
                "--", path)
    head, body = [], []
    for line in text.splitlines():
        if line.startswith(("diff --git", "index ", "@@")):
            continue
        if line.startswith(("+++", "---")) or line[:1] not in ("+", "-", "\\"):
            head.append(line)
        else:
            body.append(line)
    return ("text", tuple(head), tuple(body))


def replay_differs(root, merge, ours, theirs, paths):
    """Why MERGE's result for any of PATHS is not what an automatic merge of its parents gives (a conflict resolved
    by hand, or a line moved in the resolution), or None. The merge is redone with git merge-tree (git 2.38 or later)
    and the repository's own merge configuration; content compares cannot see a line moved to another place with the
    same text."""
    p = subprocess.run(["git", "-c", "core.quotepath=off", "merge-tree", "--write-tree", ours, theirs],
                       cwd=str(root), capture_output=True, text=True)
    if p.returncode not in (0, 1):
        return f"merge {merge[:12]} could not be replayed: {p.stderr.strip()[:120]}"
    lines = p.stdout.split("\n")
    tree, conflicted = lines[0].strip(), set()
    if not re.fullmatch(r"[0-9a-f]{40,64}", tree) or subprocess.run(
            ["git", "cat-file", "-e", f"{tree}^{{tree}}"], cwd=str(root), capture_output=True).returncode:
        return f"merge {merge[:12]} could not be replayed: git merge-tree gave no tree"
    for ln in lines[1:]:                    # conflicted file info: "<mode> <object> <stage>\t<path>"
        if not ln.strip():
            break
        meta, _, name = ln.partition("\t")
        if len(meta.split()) != 3 or not name:
            return f"merge {merge[:12]} could not be replayed: unreadable conflict line {ln[:80]!r}"
        conflicted.add(name)
    for path in paths:
        if path in conflicted:
            return f"merge {merge[:12]} resolves a conflict in {path} by hand"
        a = subprocess.run(["git", "rev-parse", "-q", "--verify", f"{tree}:{path}"], cwd=str(root),
                           capture_output=True, text=True).stdout.strip()
        b = subprocess.run(["git", "rev-parse", "-q", "--verify", f"{merge}:{path}"], cwd=str(root),
                           capture_output=True, text=True).stdout.strip()
        if a != b:
            return f"merge {merge[:12]} leaves {path} different from an automatic merge of its parents"
    return None


def derive_checks(root, rec, head, base, old_mb, new_mb, paths, stop=True):
    """The checks of a derived cover, in order, as dicts {"check", "ok", "why"} (with "commit" or "path", and for an
    own change "old" and "new", the own_change tuples at the pin and at the head): the pin is an ancestor of the
    head; each commit after the pin is a two-parent merge whose other parent is on BASE, made after the pin was
    recorded; each of PATHS has the same own change by content; each merge's result for PATHS equals an automatic
    merge of its parents. STOP: end at the first failure, as derived_cover does (every path's own change is still
    compared before it stops); without it every check runs that can, for kit reviewpin explain."""
    out = []

    def failed(check, why, **kw):
        out.append({"check": check, "ok": False, "why": why, **kw})
        return stop

    pinned = rec["sha"]
    if subprocess.run(["git", "merge-base", "--is-ancestor", pinned, head], cwd=str(root)).returncode:
        if failed("ancestor", "the pinned commit is not an ancestor of the head"):
            return out
    added = _git(root, "rev-list", "--parents", f"{pinned}..{head}", "--not", base).split("\n")
    added = [ln.split() for ln in added if ln.strip()]
    if not added and failed("history", "no commits after the pin"):
        return out
    try:
        pin_time = _when(rec.get("time") or "")
    except ValueError:
        pin_time = None
        if failed("pin time", f"the pin's time {rec.get('time')!r} is unreadable"):
            return out
    merges = []
    for c in added:
        sha, parents = c[0], c[1:]
        why = None
        if len(parents) < 2:
            why = f"{sha[:12]} after the pin is not a merge"
        elif len(parents) > 2:
            why = f"{sha[:12]} after the pin merges more than two parents"
        else:
            merges.append(c)
            if subprocess.run(["git", "merge-base", "--is-ancestor", parents[1], base], cwd=str(root)).returncode:
                why = f"merge {sha[:12]} brings in {parents[1][:12]}, which is not on {base}"
            elif pin_time is not None:
                made = datetime.fromisoformat(_git(root, "log", "-1", "--format=%cI", sha).strip())
                if made <= pin_time:
                    why = f"the pin was recorded after merge {sha[:12]}: pin the head instead"
        if why:
            if failed("commit", why, commit=sha):
                return out
        else:
            out.append({"check": "commit", "ok": True, "commit": sha,
                        "why": f"{sha[:12]} merges {parents[1][:12]}, which is on {base}"})
    differ = False
    for path in paths:
        old, new = own_change(root, old_mb, pinned, path), own_change(root, new_mb, head, path)
        differ = differ or old != new
        out.append({"check": "own change", "ok": old == new, "path": path, "old": old, "new": new,
                    "why": f"the own change of {path} is {'the same' if old == new else 'different'} "
                           f"by {MODES[new[0]]}"})
    if differ and stop:
        return out
    for c in merges:
        why = replay_differs(root, c[0], c[1], c[2], paths)
        if why:
            if failed("replay", why, commit=c[0]):
                return out
        else:
            out.append({"check": "replay", "ok": True, "commit": c[0],
                        "why": f"merge {c[0][:12]} equals an automatic merge of its parents"})
    return out


def judge_checks(checks, base, paths):
    """(covered, why) from derive_checks: the first failure (every differing own change named together), or the
    derived cover's reason."""
    bad = [c for c in checks if not c["ok"]]
    if bad:
        if bad[0]["check"] == "own change":
            differ = [c["path"] for c in bad if c["check"] == "own change"]
            return False, f"the own change differs in {', '.join(differ[:3])}"
        return False, bad[0]["why"]
    n = sum(1 for c in checks if c["check"] == "commit")
    return True, (f"{n} merge(s) of {base} after the pin; the own change of {len(paths)} file(s) whose "
                  f"patch context moved is identical by content")


def derived_cover(root, rec, head, base, old_mb, new_mb, paths):
    """(covered, why) for a head that differs from the pinned commit only by merges of the base branch: every
    commit after the pin is a merge whose other parents are in BASE, made after the pin was recorded, each of PATHS
    has the same own change by content against each merge base (-U0 lines; JSON by parsed value), and each merge
    equals an automatic merge of its parents."""
    return judge_checks(derive_checks(root, rec, head, base, old_mb, new_mb, paths, stop=True), base, paths)


# ---- explain: why a pin does or does not cover the head ------------------------------------------------------------

MODES = {"json": "JSON value", "text": "-U0 lines"}


def _counted_minus(a, b):
    """Items of a not matched one for one in b, in a's order (a repeated item counts each time)."""
    left = Counter(b)
    out = []
    for x in a:
        if left[x]:
            left[x] -= 1
        else:
            out.append(x)
    return out


def _focus(items, others, keep=28, lead=40):
    """Each item cut to LINE_CUT characters: its first KEEP characters, then from LEAD characters before the first
    character where it differs from the item of OTHERS it shares the longest prefix with, so two long entries that
    differ late show where they differ."""
    out = []
    for x in items:
        k = max((len(os.path.commonprefix([x, o])) for o in others), default=0)
        if k > keep + lead:
            x = x[:keep] + " ... " + x[k - lead:]
        out.append(_cut(x))
    return out


def explain_own_change(old, new):
    """What differs between the own change at the pin (OLD) and at the head (NEW), as own_change gives them: a dict
    with the mode, its name ("compare"), notes, and the items only in the head's own change ("head_only") and only
    in the pin's ("pin_only"), each a short line such as "+ an added line", "- a removed line" or
    "$.key changed 1 -> 2"."""
    out = {"mode": new[0], "compare": MODES[new[0]], "same": old == new, "notes": [], "head_only": [],
           "pin_only": []}
    if old[0] != new[0]:
        out["compare"] = f"{MODES[old[0]]} at the pin, {MODES[new[0]]} at the head"
        out["notes"].append("compared in different modes: one side did not parse")
        return out
    if old[0] == "json":
        out["head_only"] = [" ".join(e) for e in _counted_minus(new[1], old[1])]
        out["pin_only"] = [" ".join(e) for e in _counted_minus(old[1], new[1])]
    else:
        out["head_only"] = [f"header {x}" for x in _counted_minus(new[1], old[1])] + _counted_minus(new[2], old[2])
        out["pin_only"] = [f"header {x}" for x in _counted_minus(old[1], new[1])] + _counted_minus(old[2], new[2])
        if old != new and not out["head_only"] and not out["pin_only"]:
            out["notes"].append("the same lines in another order: the -U0 compare keeps the order of the PR's own "
                                "+ and - lines")
    h, p = out["head_only"], out["pin_only"]
    out["head_only"], out["pin_only"] = _focus(h, p), _focus(p, h)
    return out


def explain(root, pr, head=None, base=DEFAULT_BASE, fetch=True, log=None, log_ref=None, always_in_scope=()):
    """delta with the reasons: every derived-cover check that can run (derive_checks without STOP) under "checks",
    each own change summarized by explain_own_change in place of the raw tuples. Status, message and exit are
    delta's, so explain never covers what delta refuses."""
    return delta(root, pr, head=head, base=base, fetch=fetch, log=log, log_ref=log_ref,
                 always_in_scope=always_in_scope, explain=True)


# ---- output ----------------------------------------------------------------------------------------------------------

def _cut(x):
    return x if len(x) <= LINE_CUT else x[:LINE_CUT] + " ..."


def _header(r):
    lines = [r["message"]]
    if r["status"] == "no-verdict":
        return lines
    lines.append(f"reviewed  {r['reviewed'][:12]}  {r['verdict']}  {r.get('reviewer') or ''}  {r.get('reviewed_at') or ''}"
                 .rstrip())
    lines.append(f"head      {r['head'][:12]}  ({r['head_ref']})")
    lines.append(f"bases     {r['reviewed_base'][:12]} then {r['head_base'][:12]} on {r['base']}")
    if r["scope"]:
        lines.append("scope     " + ", ".join(r["scope"]))
    lines += [f"note      {n}" for n in r["notes"]]
    return lines


def format_explain(r, item_lines=8):
    """kit reviewpin explain as text: delta's header, the files whose own patch moved, then each derived-cover
    check with OK or FAIL, an own change with its compare mode and up to ITEM_LINES items on each side."""
    lines = _header(r)
    if r["status"] == "no-verdict":
        return "\n".join(lines)
    if not r["changes"]:
        lines += ["", "own patch identical at the pin and at the head: nothing to explain"]
        return "\n".join(lines)
    lines += ["", "files whose own patch (-U3 hunks) differs from the pin's:"]
    for c in r["changes"]:
        lines.append(f"  {c['path']}: {c['change']}" + ("" if c["in_scope"] else " (outside scope: ignored)"))
    if "checks" not in r:
        why = ("a NO-GO is never carried as a derived cover" if r["verdict"] == "NO-GO"
               else "every changed file is outside the review's scope")
        lines += ["", f"no derived-cover checks: {why}"]
        return "\n".join(lines)
    lines += ["", f"derived cover: {'yes' if r.get('derived') else 'refused'}: {r['derive']}"]
    for c in r["checks"]:
        mark = "OK  " if c["ok"] else "FAIL"
        if c["check"] != "own change":
            lines.append(f"  {mark} {c['check']:<10} {c['why']}")
            continue
        x = c["compare"]
        lines.append(f"  {mark} own change {c['path']}  [{x['compare']}]")
        lines += [f"         {n}" for n in x["notes"]]
        for label, key in (("only at the head", "head_only"), ("only at the pin", "pin_only")):
            items = x[key]
            if items:
                lines.append(f"         {label}: {len(items)}")
                lines += [f"           {_cut(i)}" for i in items[:item_lines]]
                if len(items) > item_lines:
                    lines.append(f"           ... {len(items) - item_lines} more")
    return "\n".join(lines)


def format_delta(r, hunk_lines=14):
    lines = _header(r)
    if r["status"] == "no-verdict":
        return "\n".join(lines)
    for c in r["changes"]:
        lines.append("")
        lines.append(f"{c['path']}: {c['change']}" + ("" if c["in_scope"] else " (outside scope)"))
        lines += [f"  {h}" for h in c["head_lines"]]
        for label, key in (("new since review", "new_hunks"), ("gone since review", "gone_hunks")):
            for h in c[key]:
                lines.append(f"  {label}: {h['at']}")
                lines += [f"    {_cut(x)}" for x in h["lines"][:hunk_lines]]
                if len(h["lines"]) > hunk_lines:
                    lines.append(f"    ... {len(h['lines']) - hunk_lines} more lines")
    return "\n".join(lines)


def format_list(records):
    if not records:
        return "no verdicts recorded"
    from . import termstyle
    rows = [[r.get("time") or "", str(r["pr"]), r["sha"][:12], r.get("verdict") or "", r.get("reviewer") or "",
             ",".join(r.get("scope") or []) or "all", r.get("note") or ""] for r in records]
    return "\n".join(termstyle.table(rows, ["time", "pr", "sha", "verdict", "reviewer", "scope", "note"]))


# ---- command line ----------------------------------------------------------------------------------------------------

def add_arguments(p):
    p.add_argument("--root", help="the repository (default: the git top level of the current folder)")
    p.add_argument("--log", help=f"the verdict log, relative to the root (default ${LOG_ENV}, else {LOG})")
    sub = p.add_subparsers(dest="what", required=True)
    r = sub.add_parser("record", help="append a verdict, tied to the commit it covered, to the verdict log")
    r.add_argument("pr", help="the PR number, such as 101")
    r.add_argument("sha", help="the commit the review covered (must exist in this clone)")
    r.add_argument("verdict", help="GO, NO-GO or GO-WITH-NOTES")
    r.add_argument("--scope", nargs="+", default=[], metavar="FILE",
                   help="the files, folders or globs the review covered (default: the whole patch)")
    r.add_argument("--reviewer", help="who reviewed, such as a session link or agent name")
    r.add_argument("--note", help="one line: what the review found")
    r.add_argument("--base", default=DEFAULT_BASE, help=f"the base branch (default {DEFAULT_BASE})")
    r.add_argument("--branch", help="the local branch of the PR (default: the one branch at the commit, if any)")
    r.add_argument("--dry-run", action="store_true", help="print the line and write nothing")
    r.add_argument("--json", action="store_true", help="print the line as JSON")
    for name, text in (("delta", "does the PR's latest verdict still cover its head?"),
                       ("explain", "why the PR's latest verdict does or does not cover its head: each file's own "
                                   "change, its compare mode, and every derived-cover check")):
        d = sub.add_parser(name, help=text)
        d.add_argument("pr", help="the PR number")
        d.add_argument("--head", help="the head commit or ref (default: refs/pull/PR/head fetched from origin, "
                                      "else the branch stored with the verdict)")
        d.add_argument("--base", default=DEFAULT_BASE, help=f"the base branch (default {DEFAULT_BASE})")
        d.add_argument("--no-fetch", action="store_true", help="use local refs only, no git fetch")
        d.add_argument("--log-from", metavar="REF", help="read the verdicts as commit REF has them, such as the base "
                                                        "branch a merge gate fetched (default: the working tree)")
        d.add_argument("--json", action="store_true", help="print the result as JSON")
    ls = sub.add_parser("list", help="the recorded verdicts, oldest first")
    ls.add_argument("--pr", help="only this PR")
    ls.add_argument("--json", action="store_true", help="print them as JSON")
    return p


def run(args, root=None):
    root = Path(root or getattr(args, "root", None) or default_root())
    log = getattr(args, "log", None)
    try:
        if args.what == "record":
            rec = make_record(root, args.pr, args.sha, args.verdict, scope=args.scope, reviewer=args.reviewer,
                              note=args.note, base=args.base, branch=args.branch)
            if not args.dry_run:
                append(root, rec, log)
            if not rec["merge_base"]:
                print(f"kit reviewpin: warning: no merge base stored ({rec['sha'][:12]} is already in {args.base}, or "
                      f"{args.base} is not in this clone); delta will compute it then", file=sys.stderr)
            if args.json:
                print(json.dumps(rec, sort_keys=True))
            else:
                print(f"{'dry run, not written' if args.dry_run else 'recorded in ' + (log or LOG)}: PR {rec['pr']} "
                      f"{rec['verdict']} at {rec['sha'][:12]}" + (f", scope {', '.join(rec['scope'])}"
                                                                   if rec["scope"] else ""))
            return EXIT_CARRIES
        if args.what in ("delta", "explain"):
            r = delta(root, args.pr, head=args.head, base=args.base, fetch=not args.no_fetch, log=log,
                      log_ref=args.log_from, explain=args.what == "explain")
            fmt = format_explain if args.what == "explain" else format_delta
            print(json.dumps(r, indent=2) if args.json else fmt(r))
            return r["exit"]
        records = read_log(root, log)
        if args.pr:
            pr = parse_pr(args.pr)
            records = [r for r in records if r.get("pr") == pr]
        print(json.dumps(records, indent=2) if args.json else format_list(records))
        return EXIT_CARRIES
    except PinError as e:
        print(f"kit reviewpin: {e}", file=sys.stderr)
        return EXIT_ERROR


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit reviewpin", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
