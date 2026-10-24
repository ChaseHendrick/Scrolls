"""Freeze registry (python -m kit.freeze), preregistration hash sets, and the executed-files guard for runners.

docs/AI-AGENTS.md rule 14 (Chase, 18 Oct 2026, memo a note of the source repository row 1): a hash freeze is
live from its freezing commit until its run's evidence is collected, then spent. A new freeze lists the files its run
executes, never a whole folder, and the run checks inside its container that it loaded nothing else (sys.modules).
The registry is a note of the source repository; kit/stale.py (check freezes) reads the same file, and every write here is
validated by stale.load_freezes first, then by the extra fields this module adds.

  python -m kit.freeze list [--state live|spent] [--json]
  python -m kit.freeze add --id ID --prereg PATH --file PATH [--file PATH ...] --note TEXT [--commit REV]
                           [--files-from FILE] [--from-prereg] [--run-token T] [--spec PATH] [--branch B]
                           [--frozen-on DATE] [--allow-other-changes] [--dry-run] [--json]
  python -m kit.freeze check ID [--at REV] [--json]
  python -m kit.freeze collect ID --evidence PATH [--on DATE] [--note TEXT] [--keep-live] [--dry-run] [--json]

Fields this module adds to an entry (all optional, so older entries stay valid): files ({path: sha256} of each file
the run executes, read with git show at the freezing commit), prereg_sha256 (the preregistration at that commit),
run_token (the launch token, when known) and other_changes (the other paths a freezing commit changes, accepted with
--allow-other-changes when an older freeze is recorded as it was). add also checks the preregistration's own
code-sha256 lines: each hash must match the file at the freezing commit, and each hashed path must be among the files
(--from-prereg adds them). check, for one entry:

  1 the freezing commit changes only the preregistration (diff against its first parent), or besides it only the
    paths its other_changes accepted;
  2 every recorded sha256 equals the file at the freezing commit (the record is true);
  3 a live freeze: every listed file is unchanged in the working tree, or at --at REV (a failure otherwise);
    a spent freeze: changes are listed for information only, since a rerun launches from `git worktree add DIR
    COMMIT` (launch_check refuses a spent freeze anywhere else);
  4 a preregistration changed since the freezing commit is attention: only dated amendments may follow.

Preregistration hash sets (docs/AI-AGENTS.md rule 5, memo row 4; the code is kit/preregsets.py, re-exported here): a
fenced block whose info string is code-sha256
lists frozen files, one "SHA256  PATH" line each. "code-sha256 readout" and plain "code-sha256" are the readout set
(changes only by a dated amendment); "code-sha256 plumbing" is the plumbing set (container image, interpreter path,
package installs, retries, logging, I/O paths), which may change by a dated deviation line with the new hash, in a
"deviations" block ("YYYY-MM-DD  SHA256  PATH  REASON") of the preregistration or of a run record. A later block of
the same set replaces an earlier hash for the same path (a dated amendment); a path listed in both sets, or a fence
with any other qualifier, is an error, so nothing is skipped or moved between the sets silently. A preregistration
with no code-sha256 block makes check_prereg exit 3 (needs a look), never a vacuous pass. check_prereg is what
python -m kit run check --prereg runs. Format: a note of the source repository.

For runners: executed_files, executed_check, run_script and launch_check import nothing from the repository beyond
this file and kit/preregsets.py (kit/stale.py is imported only by the registry functions), so a runner that imports
this module inside its container lists kit/__init__.py, kit/freeze.py and kit/preregsets.py among its files. executed_check sees the modules of its own
process; a script the run starts as a subprocess goes through run_script, which records that child's modules and
checks them the same way. Neither sees a file a process opens or executes without importing it (a data file, a shell
script, a binary). Installed packages (any site-packages or dist-packages folder, and an interpreter prefix inside
the repository, such as a .venv) are not repository files. A rerun of a spent freeze launches from `git worktree add
DIR COMMIT`, where the registry at COMMIT lacks the entry: read it from the default branch with
load(root, rev="origin/grok/laneJ-title"). Standard library only.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

# The preregistration hash sets, and the git and path helpers they share with the registry, live in
# kit/preregsets.py, so `python -m kit run check --prereg` needs only that module; they are re-exported here.
from .preregsets import (EXIT_ATTENTION, EXIT_FAIL, EXIT_INPUT, EXIT_OK, PLUMBING, READOUT, SHA256,  # noqa: F401
                         PreregError, _git, _norm_path, _parse_day, _resolve, _show, _target_bytes, _where,
                         check_prereg, deviations, format_prereg, prereg_sets, record_deviations, sha256_bytes)

ROOT = Path(__file__).resolve().parent.parent
FREEZES = "freezes.json"   # this release ships no registry; a checkout keeps its own here
SCHEMA = "freezes/1"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")

# A registry, preregistration or argument is malformed, or a request is refused (exit 2): the same class as
# preregsets.PreregError, so one except clause catches both modules' errors.
FreezeError = PreregError


class FreezeRefused(SystemExit):
    """A runner's guard refused: it loaded a file its freeze does not list, or a listed file changed."""


# ---------------------------------------------------------------- small helpers

def _utc_today():
    return datetime.now(timezone.utc).date()


def _object_type(root, commit, path):
    return (_git(root, "cat-file", "-t", f"{commit}:{path}") or "").strip() or None


def _commit_day(root, commit):
    out = _git(root, "log", "-1", "--format=%ct", commit, "--")
    try:
        return datetime.fromtimestamp(int(out.strip()), timezone.utc).date() if out and out.strip() else None
    except ValueError:
        return None


def _commit_changes(root, commit):
    """Paths the commit changes against its first parent (every path of a root commit); None when git cannot say."""
    parent = _resolve(root, f"{commit}^1")
    if parent is None:
        out = _git(root, "show", "--name-only", "--format=", commit)
    else:
        out = _git(root, "diff", "--name-only", parent, commit, "--")
    return None if out is None else [p for p in out.splitlines() if p.strip()]


def _numstat(root, commit, path, at=None):
    """'+A -D lines' between path at commit and at `at` (a commit) or the working tree; '' when git cannot say."""
    args = ["diff", "--numstat", commit] + ([at] if at else []) + ["--", path]
    out = (_git(root, *args) or "").split()
    if len(out) >= 2:
        return "binary change" if out[0] == "-" else f"+{out[0]} -{out[1]} lines"
    return ""


# ---------------------------------------------------------------- registry

def validate(data):
    """Check a whole registry document: the shape kit/stale.py enforces (stale.load_freezes, run on a temporary copy
    so both tools read one rule), then the fields this module adds. Returns the list of entries; FreezeError when
    anything is wrong."""
    from . import stale
    if not isinstance(data, dict):
        raise FreezeError(f"{FREEZES} must be a JSON object")
    with tempfile.TemporaryDirectory(prefix="kit-freeze-") as tmp:
        path = Path(tmp) / FREEZES
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        try:
            freezes = stale.load_freezes(tmp)
        except stale.StaleError as exc:
            raise FreezeError(str(exc))
    problems = []
    for f in freezes:
        fid = f["id"]
        files = f.get("files")
        if files is not None:
            if not isinstance(files, dict) or not files:
                problems.append(f"{fid}: files must be a non-empty object of path: sha256")
            else:
                for p, h in files.items():
                    try:
                        if _norm_path(p) != p:
                            problems.append(f"{fid}: files path {p!r} is not normalized")
                    except FreezeError as exc:
                        problems.append(f"{fid}: {exc}")
                    if not isinstance(h, str) or not SHA256.fullmatch(h):
                        problems.append(f"{fid}: files[{p!r}] must be a sha256 of 64 lower-case hex digits")
        other = f.get("other_changes")
        if other is not None:
            if not isinstance(other, list) or not other or not all(isinstance(x, str) for x in other):
                problems.append(f"{fid}: other_changes must be a non-empty list of repository paths")
            else:
                for x in other:
                    try:
                        if _norm_path(x) != x:
                            problems.append(f"{fid}: other_changes path {x!r} is not normalized")
                    except FreezeError as exc:
                        problems.append(f"{fid}: {exc}")
        if f.get("prereg_sha256") is not None and not (isinstance(f["prereg_sha256"], str)
                                                       and SHA256.fullmatch(f["prereg_sha256"])):
            problems.append(f"{fid}: prereg_sha256 must be a sha256 of 64 lower-case hex digits")
        if f.get("run_token") is not None and not (isinstance(f["run_token"], str) and TOKEN.fullmatch(f["run_token"])):
            problems.append(f"{fid}: run_token must be a short token such as launch-1")
        for key in ("spec", "evidence", "branch"):
            if f.get(key) is not None and not (isinstance(f[key], str) and f[key]):
                problems.append(f"{fid}: {key} must be a non-empty string when present")
    if problems:
        raise FreezeError(f"{FREEZES}: " + "; ".join(problems))
    return freezes


def load(root=ROOT, rev=None):
    """The registry document (a dict with schema, about and freezes), validated; FreezeError when it is missing or
    malformed. With rev, the registry as committed at that revision (git show REV:a note of the source repository), for a
    rerun of a spent freeze from a worktree at its freezing commit, whose own registry lacks the entry: pass the
    default branch, such as rev="origin/grok/laneJ-title"."""
    if rev:
        full = _resolve(root, rev)
        if full is None:
            raise FreezeError(f"--registry-rev {rev}: not a commit in this clone (fetch it first)")
        raw = _show(root, full, FREEZES)
        if raw is None:
            raise FreezeError(f"{FREEZES} is not a file at {rev}")
        text, where = raw.decode("utf-8", "replace"), f"{FREEZES} at {rev}"
    else:
        try:
            text, where = (Path(root) / FREEZES).read_text(encoding="utf-8"), FREEZES
        except OSError as exc:
            raise FreezeError(f"cannot read {FREEZES}: {exc}")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise FreezeError(f"{where} is not JSON: {exc}")
    validate(data)
    return data


def save(root, data):
    """Validate, then replace the registry atomically (indented JSON, final newline)."""
    validate(data)
    path = Path(root) / FREEZES
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".freezes-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def find(data, fid):
    for f in data.get("freezes") or []:
        if f.get("id") == fid:
            return f
    raise FreezeError(f"no freeze {fid!r} in {FREEZES}; python -m kit.freeze list shows the ids")


def _age_days(root, entry, today=None):
    """Days since the freeze (frozen_on, else the freezing commit's date); None when neither is known."""
    today = today or _utc_today()
    start = date.fromisoformat(entry["frozen_on"]) if entry.get("frozen_on") else _commit_day(root, entry["freezing_commit"])
    return None if start is None else (today - start).days


def listing(root=ROOT, state=None, today=None):
    """One dict per entry (id, state, frozen_on, age_days, collected_on, collected_age_days, files, prereg,
    freezing_commit), optionally only live or spent ones."""
    today = today or _utc_today()
    out = []
    for f in load(root)["freezes"]:
        if state and f["state"] != state:
            continue
        col = f.get("collected_on")
        out.append({"id": f["id"], "state": f["state"], "freezing_commit": f["freezing_commit"],
                    "frozen_on": f.get("frozen_on"), "age_days": _age_days(root, f, today),
                    "collected_on": col, "collected_age_days": (today - date.fromisoformat(col)).days if col else None,
                    "files": len(f["files"]) if isinstance(f.get("files"), dict) else None,
                    "prereg": f["prereg"], "run_token": f.get("run_token")})
    return out


def make_entry(root, fid, prereg, files, note, commit="HEAD", run_token=None, spec=None, branch=None,
               frozen_on=None, allow_other_changes=False, from_prereg=False):
    """A new live entry, its hashes read with git show at the freezing commit. FreezeError when the commit, the
    preregistration or a file is not there, when a path is a folder, when a hash line of the preregistration does not
    match its file at the freezing commit or names a file the list leaves out (from_prereg adds them), or (unless
    allow_other_changes, which records the extra paths as other_changes) when the freezing commit changes anything but
    the preregistration."""
    if not isinstance(fid, str) or not ID.fullmatch(fid):
        raise FreezeError(f"--id {fid!r}: use letters, digits, dot, dash and underscore, starting with a letter or digit")
    full = _resolve(root, commit)
    if full is None:
        raise FreezeError(f"--commit {commit}: not a commit in this clone")
    prereg = _norm_path(prereg)
    pre = _show(root, full, prereg)
    if pre is None:
        raise FreezeError(f"--prereg {prereg} is not a file at {full[:12]}")
    pre_text = pre.decode("utf-8", "replace")
    sets = prereg_sets(pre_text)
    devs = deviations(pre_text)
    files = list(files) + (sorted(sets) if from_prereg else [])
    if not files:
        raise FreezeError("list the files the run executes with --file (or --files-from); a freeze without files "
                          "guards nothing")
    hashes = {}
    for raw in files:
        p = _norm_path(raw)
        kind = _object_type(root, full, p)
        if kind == "tree":
            raise FreezeError(f"{p} is a folder at {full[:12]}: a freeze lists the files its run executes, never a "
                              "whole folder (docs/AI-AGENTS.md rule 14)")
        data = _show(root, full, p) if kind == "blob" else None
        if data is None:
            raise FreezeError(f"{p} is not a file at {full[:12]}: commit it before the freezing commit")
        hashes[p] = sha256_bytes(data)
    wrong, missing = [], sorted(set(sets) - set(hashes))
    for path, (kind, rec) in sorted(sets.items()):
        if path in missing:
            continue
        now = hashes[path]
        if now != rec and not (kind == PLUMBING and any(d["path"] == path and d["sha256"] == now for d in devs)):
            wrong.append(f"{path} ({kind} set: {rec[:12]} in the preregistration, {now[:12]} at the commit)")
    if wrong:
        raise FreezeError(f"the preregistration's hash lines do not match the files at {full[:12]}: "
                          + "; ".join(wrong) + ". Fix the hash lines (or the files) before the freezing commit")
    if missing:
        raise FreezeError(f"the preregistration hashes {', '.join(missing)}, which the file list leaves out: add each "
                          "with --file, or pass --from-prereg to add every hashed file")
    changed = _commit_changes(root, full)
    if changed is None:
        raise FreezeError(f"git cannot list what {full[:12]} changes")
    others = [p for p in changed if p != prereg]
    if others and not allow_other_changes:
        shown = ", ".join(others[:8]) + (f" and {len(others) - 8} more" if len(others) > 8 else "")
        raise FreezeError(f"the freezing commit {full[:12]} also changes {shown}: a freezing commit changes only the "
                          "preregistration, so commit the code first (or pass --allow-other-changes to record an "
                          "older freeze as it was; the entry then lists those paths as other_changes)")
    day = _parse_day(frozen_on, "--frozen-on") if frozen_on else _commit_day(root, full)
    entry = {"id": fid, "prereg": prereg}
    if spec:
        entry["spec"] = _norm_path(spec)
    entry.update({"freezing_commit": full, "frozen_on": day.isoformat() if day else None})
    if branch:
        entry["branch"] = branch
    entry.update({"state": "live", "collected_on": None})
    if run_token:
        if not TOKEN.fullmatch(run_token):
            raise FreezeError(f"--run-token {run_token!r} is not a short token such as launch-1")
        entry["run_token"] = run_token
    entry.update({"prereg_sha256": sha256_bytes(pre), "files": dict(sorted(hashes.items()))})
    if others:
        entry["other_changes"] = sorted(others)
    entry["note"] = note
    if entry["frozen_on"] is None:
        del entry["frozen_on"]
    return entry


def add(root, entry, dry_run=False):
    """Append entry to the registry and save it (unless dry_run). FreezeError when the id is taken."""
    data = load(root)
    if any(f.get("id") == entry["id"] for f in data["freezes"]):
        raise FreezeError(f"freeze {entry['id']!r} is already in {FREEZES}; pick a new id (a refreeze is a new entry)")
    data["freezes"].append(entry)
    validate(data)
    if not dry_run:
        save(root, data)
    return entry


def collect(root, fid, evidence, on=None, note=None, keep_live=False, dry_run=False):
    """Record a collected run: collected_on and evidence, and state spent (unless keep_live, for a freeze that still
    guards a later run). FreezeError when the entry is already spent, the evidence path is not on disk, or the day
    is before the freeze."""
    data = load(root)
    entry = find(data, fid)
    if entry["state"] == "spent":
        raise FreezeError(f"{fid} is already spent (collected {entry.get('collected_on')}); a rerun is a new freeze")
    ev = _norm_path(str(evidence).rstrip("/") or evidence)
    if not (Path(root) / ev).exists():
        raise FreezeError(f"--evidence {ev} is not in the working tree: commit or copy the collected evidence first")
    if (Path(root) / ev).is_dir():
        ev += "/"   # a folder is written with a final slash, as the registry's other evidence folders are
    day = _parse_day(on, "--on") if on else _utc_today()
    if entry.get("frozen_on") and day < date.fromisoformat(entry["frozen_on"]):
        raise FreezeError(f"--on {day} is before the freeze ({entry['frozen_on']})")
    entry["collected_on"] = day.isoformat()
    entry["evidence"] = ev
    if not keep_live:
        entry["state"] = "spent"
    if note:
        entry["note"] = f"{entry['note'].rstrip()} Collected {day.isoformat()}: {note.strip()}"
    validate(data)
    if not dry_run:
        save(root, data)
    return entry


def check(root, fid, at=None, data=None):
    """The check report of one entry (see the module docstring): a dict with problems (exit 1), attention (exit 3),
    info, one row per file and the exit code. FreezeError for an unknown id or an --at that is not a commit."""
    data = data or load(root)
    entry = find(data, fid)
    target = None
    if at:
        target = _resolve(root, at)
        if target is None:
            raise FreezeError(f"--at {at}: not a commit in this clone")
    problems, attention, info, rows = [], [], [], []
    commit, prereg, live = entry["freezing_commit"], entry["prereg"], entry["state"] == "live"
    full = _resolve(root, commit)
    report = {"id": fid, "state": entry["state"], "freezing_commit": commit, "prereg": prereg,
              "target": target or "working tree", "problems": problems, "attention": attention, "info": info,
              "files": rows}
    if full is None:
        problems.append(f"freezing commit {commit} is not in this clone: fetch it (or the branch "
                        f"{entry.get('branch') or 'that keeps it'}); nothing can be checked without it")
        report["exit"] = EXIT_FAIL
        return report
    changed = _commit_changes(root, full)
    if changed is None:
        problems.append(f"git cannot list what {commit} changes")
    else:
        accepted = set(entry.get("other_changes") or [])
        others = [p for p in changed if p != prereg]
        if others:
            fresh = [p for p in others if p not in accepted]
            known = [p for p in others if p in accepted]
            show = lambda ps: ", ".join(ps[:8]) + (f" and {len(ps) - 8} more" if len(ps) > 8 else "")
            if known:
                info.append(f"the freezing commit {commit} also changes {show(known)}, accepted when the freeze was "
                            "recorded as it was (other_changes)")
            if fresh:
                said = (f"the freezing commit {commit} changes {len(fresh)} file(s) besides the preregistration: "
                        f"{show(fresh)}")
                if entry.get("files"):
                    problems.append(said)
                else:   # an entry from before the convention (18 Oct 2026) that a freezing commit changes only the prereg
                    info.append(said + " (the entry predates python -m kit.freeze add and that convention)")
        elif prereg not in changed:
            info.append(f"the freezing commit {commit} does not change the preregistration")
    pre_then = _show(root, full, prereg)
    if pre_then is None:
        problems.append(f"{prereg} is not a file at the freezing commit {commit}")
    else:
        rec = entry.get("prereg_sha256")
        if rec and rec != sha256_bytes(pre_then):
            problems.append(f"prereg_sha256 {rec[:12]} does not match {prereg} at {commit} "
                            f"({sha256_bytes(pre_then)[:12]}): the record is wrong")
        pre_now = _target_bytes(root, target, prereg)
        if pre_now is None:
            (attention if live else info).append(f"{prereg} is gone from the {_where(target)}")
        elif sha256_bytes(pre_now) != sha256_bytes(pre_then):
            (attention if live else info).append(
                f"{prereg} changed since the freezing commit ({_numstat(root, full, prereg, target) or 'changed'}): "
                "only dated amendments at its end may follow (docs/AI-AGENTS.md rule 5)")
    files = entry.get("files")
    if not files:
        info.append("no file list recorded (an entry from before python -m kit.freeze add): only the freezing commit "
                    "and the preregistration are checked; the runner's own freeze check still applies")
    for path, rec in sorted((files or {}).items()):
        then = _show(root, full, path)
        row = {"path": path, "recorded": rec, "at_freeze": sha256_bytes(then) if then is not None else None,
               "now": None, "status": "ok", "change": ""}
        if then is None:
            problems.append(f"{path} is not a file at the freezing commit {commit}")
            row["status"] = "not at freeze"
        elif row["at_freeze"] != rec:
            problems.append(f"{path}: recorded sha256 {rec[:12]} does not match the file at {commit} "
                            f"({row['at_freeze'][:12]}): the record is wrong")
            row["status"] = "record wrong"
        now = _target_bytes(root, target, path)
        row["now"] = sha256_bytes(now) if now is not None else None
        if row["status"] == "ok" and row["now"] != rec:
            row["status"] = "missing" if now is None else "changed"
            row["change"] = "" if now is None else _numstat(root, full, path, target)
            what = f"{path} is gone from the {_where(target)}" if now is None else (
                f"{path} changed in the {_where(target)} ({row['change'] or 'changed'})")
            if live:
                problems.append(f"{what}: a live freeze's files must not change until its run is collected")
            else:
                info.append(f"{what}; allowed, the freeze is spent (a rerun launches from git worktree add DIR "
                            f"{commit})")
        rows.append(row)
    report["exit"] = EXIT_FAIL if problems else EXIT_ATTENTION if attention else EXIT_OK
    return report


# ---------------------------------------------------------------- runner guard (sys.modules)

PACKAGE_DIRS = ("site-packages", "dist-packages")


def _prefixes_inside(roots):
    """Interpreter prefixes (sys.prefix, sys.base_prefix, sys.exec_prefix) that sit inside a root, such as an in-repo
    .venv; a prefix that holds the root (a repository under /usr/local) is never skipped, or nothing would be seen."""
    out = set()
    for pre in {sys.prefix, sys.base_prefix, sys.exec_prefix}:
        for p in {os.path.abspath(pre), os.path.realpath(pre)}:
            if any(p.startswith(r + os.sep) for r in roots):
                out.add(p)
    return out


def _repo_paths(paths, root):
    """Of these file paths, those inside root as repository paths (relative, with /), each path and root taken both
    as given and with symbolic links resolved, so a mounted or linked tree is still seen. Installed packages are not
    repository files: a path with a site-packages or dist-packages folder below root, or under an interpreter prefix
    inside root (an in-repo .venv or conda environment), is left out."""
    roots = {os.path.abspath(root), os.path.realpath(root)}
    prefixes = _prefixes_inside(roots)
    out = set()
    for f in paths:
        for p in {os.path.abspath(f), os.path.realpath(f)}:
            if any(p.startswith(x + os.sep) for x in prefixes):
                continue
            for r in roots:
                if p.startswith(r + os.sep) and os.path.isfile(p):
                    rel = os.path.relpath(p, r).replace(os.sep, "/")
                    if not any(part in PACKAGE_DIRS for part in rel.split("/")[:-1]):
                        out.add(rel)
    return sorted(out)


def executed_files(root, modules=None):
    """The repository files under root that loaded modules came from (sys.modules, or modules: {name: module})."""
    mods = list((sys.modules if modules is None else modules).values())
    return _repo_paths([f for f in (getattr(m, "__file__", None) for m in mods) if f], root)


def _listed(files):
    if isinstance(files, dict) and "files" in files and isinstance(files["files"], dict):
        files = files["files"]
    return set(files)


def executed_check(files, root, modules=None, when="run", loaded=None):
    """Refuse (FreezeRefused, a SystemExit) when this process loaded a repository file under root that files (an
    entry, its files dict, or a list of paths) does not list; returns how many repository files were loaded. Call
    it inside the container after the run's imports, and again after the work. loaded, a list of file paths another
    process recorded (run_script), is checked instead of this process's modules."""
    got = _repo_paths(loaded, root) if loaded is not None else executed_files(root, modules)
    bad = sorted(p for p in got if p not in _listed(files))
    if bad:
        raise FreezeRefused(f"{when}: loaded {', '.join(bad)}, which the freeze does not list, so it does not cover "
                            "it: list it, amend the preregistration and freeze again (docs/AI-AGENTS.md rule 14)")
    return len(got)


# python -c RUNNER RECORD SCRIPT ARGS...: runs SCRIPT as `python SCRIPT ARGS...` would (as __main__, with its folder
# first on sys.path), then writes the files of every module it loaded to RECORD, also when it exits with an error.
# The same runner as a script of the source repository.
RUNNER = """import json, os, runpy, sys
record, script = sys.argv[1], sys.argv[2]
sys.argv = sys.argv[2:]
sys.path[0] = os.path.dirname(os.path.abspath(script))
try:
    runpy.run_path(script, run_name="__main__")
finally:
    files = [script] + [m.__file__ for m in list(sys.modules.values()) if getattr(m, "__file__", None)]
    files = {g(f) for f in files for g in (os.path.abspath, os.path.realpath)}
    with open(record, "w") as fh:
        json.dump(sorted(files), fh)
"""


def run_script(script, args, files, root, python=None, when=None):
    """Run `python SCRIPT ARGS...` as a subprocess through RUNNER (check=True: a failing script raises
    CalledProcessError), then refuse (FreezeRefused) when the child loaded a repository file under root that files
    does not list, the script itself included. Returns how many repository files the child loaded. Use it for every
    script a frozen run starts, since executed_check sees only its own process."""
    with tempfile.TemporaryDirectory(prefix="kit-freeze-run-") as tmp:
        record = os.path.join(tmp, "loaded.json")
        subprocess.run([python or sys.executable, "-c", RUNNER, record, str(script), *map(str, args)], check=True)
        with open(record, encoding="utf-8") as fh:
            loaded = json.load(fh)
    return executed_check(files, root, when=when or f"subprocess {script}", loaded=loaded)


def launch_check(entry, root=ROOT):
    """Refuse (FreezeRefused) a launch the freeze does not allow: a live freeze needs every listed file unchanged in
    the working tree; a spent freeze runs only from a checkout whose HEAD is the freezing commit (git worktree add
    DIR COMMIT), with its listed files unchanged. In such a worktree the registry predates the entry, so take the
    entry from the default branch: find(load(root, rev="origin/grok/laneJ-title"), ID). Returns the number of files
    checked."""
    files = entry.get("files") or {}
    if not files:
        raise FreezeRefused(f"{entry['id']}: no file list recorded, so this guard cannot vouch for the launch")
    if entry["state"] == "spent":
        head, full = _resolve(root, "HEAD"), _resolve(root, entry["freezing_commit"])
        if head is None or full is None or head != full:
            raise FreezeRefused(f"{entry['id']} is spent: a rerun launches from git worktree add DIR "
                                f"{entry['freezing_commit']}, not from {(head or 'this checkout')[:12]}")
    bad = []
    for path, rec in sorted(files.items()):
        p = Path(root) / path
        try:
            ok = p.is_file() and sha256_bytes(p.read_bytes()) == rec
        except OSError:
            ok = False
        if not ok:
            bad.append(path)
    if bad:
        raise FreezeRefused(f"{entry['id']}: {', '.join(bad)} differ from the freeze at {entry['freezing_commit']}")
    return len(files)


# ---------------------------------------------------------------- command line

def _format_list(rows):
    head = ("id", "state", "frozen", "age", "collected", "files", "prereg")
    body = [(r["id"], r["state"], r["frozen_on"] or "?", "?" if r["age_days"] is None else f"{r['age_days']}d",
             r["collected_on"] or "-", "-" if r["files"] is None else str(r["files"]), r["prereg"]) for r in rows]
    widths = [max(len(str(x[i])) for x in [head] + body) for i in range(len(head))]
    line = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip()
    live = sum(1 for r in rows if r["state"] == "live")
    out = [line(head), line(["-" * w for w in widths])] + [line(r) for r in body]
    out.append(f"{len(rows)} freezes, {live} live, {len(rows) - live} spent; files '-' means no file list recorded")
    return "\n".join(out)


def _format_check(r):
    lines = [f"{r['id']} ({r['state']}), freezing commit {r['freezing_commit']}, preregistration {r['prereg']}, "
             f"against the {_where(r['target'] if r['target'] != 'working tree' else None)}"]
    for row in r["files"]:
        if row["status"] != "ok":
            lines.append(f"{row['status']:<14} {row['path']} {row['change']}".rstrip())
    lines += [f"FAIL: {t}" for t in r["problems"]] + [f"ATTENTION: {t}" for t in r["attention"]]
    lines += [f"info: {t}" for t in r["info"]]
    ok = sum(1 for x in r["files"] if x["status"] == "ok")
    lines.append(("check failed" if r["exit"] == EXIT_FAIL else "check needs a look" if r["exit"] == EXIT_ATTENTION
                  else "check ok") + f": {ok} of {len(r['files'])} listed file(s) match")
    return "\n".join(lines)


def add_arguments(p):
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("list", help="every freeze, live and spent, with ages and file counts")
    a.add_argument("--state", choices=("live", "spent"), help="only live or only spent freezes")
    a.add_argument("--json", action="store_true", help="print JSON")
    a = actions.add_parser("add", help="register a new live freeze: its preregistration, freezing commit and the "
                                       "exact files its run executes, hashed at that commit")
    a.add_argument("--id", required=True, help="a new id, such as strokenet-v7")
    a.add_argument("--prereg", required=True, help="the preregistration (or the document that fixes the rule)")
    a.add_argument("--file", action="append", default=[], help="a file the run executes; repeatable, never a folder")
    a.add_argument("--files-from", help="a text file with one path per line (# starts a comment)")
    a.add_argument("--from-prereg", action="store_true",
                   help="also list every file the preregistration's code-sha256 blocks hash")
    a.add_argument("--note", required=True, help="what the freeze is and where its run is recorded")
    a.add_argument("--commit", default="HEAD", help="the freezing commit (default HEAD)")
    a.add_argument("--run-token", help="the launch token, when known")
    a.add_argument("--spec", help="the run spec under a folder of the source repository")
    a.add_argument("--branch", help="the branch that keeps the commit while it is not on the default branch")
    a.add_argument("--frozen-on", help="YYYY-MM-DD (default: the freezing commit's UTC date)")
    a.add_argument("--allow-other-changes", action="store_true",
                   help="accept a freezing commit that changes files besides the preregistration (an older freeze); "
                        "the entry records them as other_changes, which check then reports as information")
    a.add_argument("--dry-run", action="store_true", help="print the entry, write nothing")
    a.add_argument("--json", action="store_true", help="print the entry as JSON")
    a = actions.add_parser("check", help="one freeze: the freezing commit, the recorded hashes and the files now")
    a.add_argument("id")
    a.add_argument("--at", help="compare the listed files at this commit (default: the working tree)")
    a.add_argument("--registry-rev", help="read the registry as committed at this revision, such as "
                                          "origin/grok/laneJ-title (from a worktree at an old freezing commit)")
    a.add_argument("--json", action="store_true", help="print JSON")
    a = actions.add_parser("collect", help="mark a freeze spent: its run's evidence is collected")
    a.add_argument("id")
    a.add_argument("--evidence", required=True, help="the collected evidence, a file or folder in the working tree")
    a.add_argument("--on", help="YYYY-MM-DD (default: today, UTC)")
    a.add_argument("--note", help="appended to the entry's note")
    a.add_argument("--keep-live", action="store_true",
                   help="record the collected run but keep the freeze live (it still guards a later run)")
    a.add_argument("--dry-run", action="store_true", help="print the entry, write nothing")
    a.add_argument("--json", action="store_true", help="print the entry as JSON")


def _files_from(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise FreezeError(f"cannot read --files-from {path}: {exc}")
    return [ln.split("#", 1)[0].strip() for ln in text.splitlines() if ln.split("#", 1)[0].strip()]


def run(args, root=None):
    root = Path(root or ROOT)
    try:
        if args.action == "list":
            rows = listing(root, args.state)
            print(json.dumps(rows, indent=2) if args.json else _format_list(rows))
            return EXIT_OK
        if args.action == "add":
            files = list(args.file) + (_files_from(args.files_from) if args.files_from else [])
            entry = make_entry(root, args.id, args.prereg, files, args.note, args.commit, args.run_token, args.spec,
                               args.branch, args.frozen_on, args.allow_other_changes, args.from_prereg)
            add(root, entry, args.dry_run)
            if args.json:
                print(json.dumps(entry, indent=2))
            else:
                verb = "would add" if args.dry_run else "added"
                print(f"{verb} {entry['id']}: live from {entry['freezing_commit'][:12]}, {len(entry['files'])} "
                      f"file(s), preregistration {entry['prereg']}" + ("" if args.dry_run else f" ({FREEZES})"))
            return EXIT_OK
        if args.action == "check":
            r = check(root, args.id, args.at, load(root, args.registry_rev) if args.registry_rev else None)
            print(json.dumps(r, indent=2) if args.json else _format_check(r))
            return r["exit"]
        if args.action == "collect":
            entry = collect(root, args.id, args.evidence, args.on, args.note, args.keep_live, args.dry_run)
            if args.json:
                print(json.dumps(entry, indent=2))
            else:
                verb = "would record" if args.dry_run else "recorded"
                print(f"{verb} {entry['id']}: collected {entry['collected_on']}, evidence {entry['evidence']}, "
                      f"state {entry['state']}")
            return EXIT_OK
    except FreezeError as exc:
        print(f"kit freeze: {exc}", file=sys.stderr)
        return EXIT_INPUT
    return EXIT_INPUT


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit.freeze", description=__doc__.split("\n\n")[0])
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
