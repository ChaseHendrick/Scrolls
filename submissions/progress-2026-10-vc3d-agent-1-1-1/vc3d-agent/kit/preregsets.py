"""Preregistration hash sets: the readout and plumbing sets of a preregistration, checked against the files
(python -m kit run check --prereg; the full freeze registry is kit/freeze.py, which imports this module).

A preregistration pins the files a run executes in fenced blocks whose info string is code-sha256, one
"SHA256  PATH" line each (as sha256sum prints). "code-sha256 readout" and plain "code-sha256" are the readout set: the
data split, held-out list, labels, thresholds, metrics and scoring code, model and training configuration, controls
and bars, which change only by a dated amendment that gives the new hash. "code-sha256 plumbing" is the plumbing set:
the container image, interpreter path, package installs, retries, logging and I/O paths, which may change by a dated
deviation line with the new hash, in a "deviations" block ("YYYY-MM-DD  SHA256  PATH  REASON") of the preregistration
or of a run record, or in a run record's JSON "deviations" list.

A later block of the same set replaces an earlier hash for the same path (a dated amendment). A path listed in both
sets, or a code-sha256 fence with any other qualifier, is an error, so nothing is skipped or moved between the sets
silently. check_prereg fails (exit 1) on a changed readout file, needs a look (exit 3) for a changed plumbing file
without a matching deviation line, and also needs a look when the preregistration hashes nothing in this format, so
the check never passes with nothing checked. A preregistration with only plain blocks is all readout.

Standard library only; it imports nothing else from the repository.
"""

import hashlib
import os
import re
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXIT_OK, EXIT_FAIL, EXIT_INPUT, EXIT_ATTENTION = 0, 1, 2, 3
SHA256 = re.compile(r"[0-9a-f]{64}")
HASH_FENCE = re.compile(r"^```code-sha256(?:\s+(readout|plumbing))?\s*$")
ANY_HASH_FENCE = re.compile(r"^```code-sha256")
DEVIATION_FENCE = re.compile(r"^```deviations\s*$")
HASH_LINE = re.compile(r"^([0-9a-f]{64})\s+(\S.*?)\s*$")
DEVIATION_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+([0-9a-f]{64})\s+(\S+)(?:\s+(.*?))?\s*$")
READOUT, PLUMBING = "readout", "plumbing"


class PreregError(ValueError):
    """A preregistration, record, path or argument is malformed, or a request is refused (exit 2). kit/freeze.py
    raises the same class as PreregError."""


# ---------------------------------------------------------------- small helpers (git and paths)

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _git(root, *args, binary=False):
    """stdout of a git command in root (bytes with binary), or None when git fails."""
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def _resolve(root, rev):
    """The full hash of rev's commit, or None."""
    out = _git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return out.strip() if out and out.strip() else None


def _show(root, commit, path):
    """The bytes of path at commit, or None when it is not a file there."""
    if (_git(root, "cat-file", "-t", f"{commit}:{path}") or "").strip() != "blob":
        return None
    return _git(root, "show", f"{commit}:{path}", binary=True)


def _norm_path(path):
    """A repository path as given on the command line: relative, with /, no . or .. parts, not a folder."""
    p = str(path).replace(os.sep, "/").strip()
    while p.startswith("./"):
        p = p[2:]
    if not p or p.startswith("/") or p.endswith("/") or any(part in ("", ".", "..") for part in p.split("/")):
        raise PreregError(f"{path!r} is not a repository file path (relative, no . or .. parts, not a folder)")
    return p


def _parse_day(text, what):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        raise PreregError(f"{what} is not YYYY-MM-DD: {text}")


def _where(target):
    return f"commit {target[:12]}" if target else "working tree"


def _target_bytes(root, target, path):
    if target:
        return _show(root, target, path)
    p = Path(root) / path
    try:
        return p.read_bytes() if p.is_file() else None
    except OSError:
        return None


# ---------------------------------------------------------------- preregistration hash sets

def prereg_sets(text):
    """{path: (set, sha256)} from every code-sha256 block of a preregistration. A plain or `readout` block is the
    readout set, a `plumbing` block the plumbing set; a later block of the same set replaces an earlier hash for the
    same path. PreregError for a code-sha256 fence with any other qualifier (it would be skipped silently), for a path
    listed in both sets (a plumbing block must not re-hash a readout file), or for a malformed block."""
    out, fence, listed = {}, None, {READOUT: set(), PLUMBING: set()}
    for line in text.splitlines():
        t = line.strip()
        if fence is None:
            m = HASH_FENCE.match(t)
            if m:
                fence = m.group(1) or READOUT
            elif ANY_HASH_FENCE.match(t):
                raise PreregError(f"unknown code-sha256 block {t[3:][:60]!r}: its fence takes no qualifier, or "
                                  "readout or plumbing in lower case, so no hashed file is skipped")
            continue
        if t.startswith("```"):
            fence = None
            continue
        if not t:
            continue
        m = HASH_LINE.match(t)
        if not m:
            raise PreregError(f"a code-sha256 block holds a line that is not 'SHA256  PATH': {t[:80]}")
        path = m.group(2).strip()
        listed[fence].add(path)
        out[path] = (fence, m.group(1))
    if fence is not None:
        raise PreregError("a code-sha256 block is not closed")
    both = sorted(listed[READOUT] & listed[PLUMBING])
    if both:
        raise PreregError(f"{', '.join(both)} listed in both the readout and the plumbing set: a file is in one set "
                          "only, and a readout file changes only by a dated amendment in a readout block")
    return out


def deviations(text):
    """[{date, sha256, path, reason}] from every deviations block of a text (a preregistration or a run record)."""
    out, inside = [], False
    for line in text.splitlines():
        t = line.strip()
        if not inside:
            inside = bool(DEVIATION_FENCE.match(t))
            continue
        if t.startswith("```"):
            inside = False
            continue
        if not t:
            continue
        m = DEVIATION_LINE.match(t)
        if not m:
            raise PreregError(f"a deviations block holds a line that is not 'YYYY-MM-DD  SHA256  PATH  REASON': {t[:80]}")
        _parse_day(m.group(1), "a deviation's date")
        if not (m.group(4) or "").strip():
            raise PreregError(f"the deviation of {m.group(3)} on {m.group(1)} gives no reason")
        out.append({"date": m.group(1), "sha256": m.group(2), "path": m.group(3), "reason": m.group(4).strip()})
    if inside:
        raise PreregError("a deviations block is not closed")
    return out


def record_deviations(items):
    """Deviation lines kept as JSON in a run record (a run.json "deviations" list of {date, sha256, path, reason}),
    checked and returned in the form deviations() gives."""
    if not isinstance(items, list):
        raise PreregError('"deviations" must be a list of {date, sha256, path, reason}')
    out = []
    for i, d in enumerate(items):
        if not isinstance(d, dict):
            raise PreregError(f"deviations[{i}] must be an object with date, sha256, path and reason")
        _parse_day(d.get("date"), f"deviations[{i}].date")
        if not isinstance(d.get("sha256"), str) or not SHA256.fullmatch(d["sha256"]):
            raise PreregError(f"deviations[{i}].sha256 must be a sha256 of 64 lower-case hex digits")
        if not isinstance(d.get("path"), str) or not d["path"] or not isinstance(d.get("reason"), str) \
                or not d["reason"].strip():
            raise PreregError(f"deviations[{i}] needs a path and a reason")
        out.append({"date": d["date"], "sha256": d["sha256"], "path": d["path"], "reason": d["reason"].strip()})
    return out


def check_prereg(root, prereg, at=None, records=(), extra=()):
    """Every file a preregistration's code-sha256 blocks hash, against the working tree or --at REV: a readout file
    that changed is a failure (exit 1); a plumbing file that changed is a plumbing deviation, accepted when a dated
    deviation line (in the preregistration, a record file, or extra) gives its new hash, else attention (exit 3).
    No split (only plain blocks) means every file is readout. PreregError when a file cannot be read."""
    root = Path(root)
    target = None
    if at:
        target = _resolve(root, at)
        if target is None:
            raise PreregError(f"--at {at}: not a commit in this clone")
    pre = _target_bytes(root, target, _norm_path(prereg))
    if pre is None:
        raise PreregError(f"{prereg} is not a file in the {_where(target)}")
    text = pre.decode("utf-8", "replace")
    sets = prereg_sets(text)
    devs = deviations(text)
    for rec in records:
        try:
            devs += deviations(Path(rec).read_text(encoding="utf-8"))
        except OSError as exc:
            raise PreregError(f"cannot read --record {rec}: {exc}")
    devs += list(extra)
    rows, failures, attention = [], [], []
    for path, (kind, rec) in sorted(sets.items()):
        now = _target_bytes(root, target, path)
        cur = sha256_bytes(now) if now is not None else None
        row = {"path": path, "set": kind, "recorded": rec, "now": cur, "status": "ok", "deviation": None}
        if cur != rec:
            gone = cur is None
            if kind == READOUT:
                row["status"] = "readout changed"
                failures.append(f"{path} (readout set) {'is gone' if gone else 'changed'}: a readout file changes only "
                                "by a dated amendment that gives its new hash")
            else:
                hit = [d for d in devs if d["path"] == path and d["sha256"] == cur]
                if hit:
                    row["status"] = "plumbing deviation recorded"
                    row["deviation"] = hit[-1]
                else:
                    row["status"] = "plumbing deviation"
                    attention.append(f"{path} (plumbing set) {'is gone' if gone else 'changed'}: a plumbing deviation; "
                                     f"record a dated deviation line with the new hash ({cur or 'none'}), allowed only "
                                     "before any map, model or score of the run exists, or when a fixed test input "
                                     "gives identical output before and after (the plumbing rule)")
        rows.append(row)
    counts = {READOUT: sum(1 for k, _ in sets.values() if k == READOUT),
              PLUMBING: sum(1 for k, _ in sets.values() if k == PLUMBING)}
    if not sets:
        attention.append(f"{prereg} hashes nothing in the code-sha256 format, so this check cannot vouch for any file: "
                         "add code-sha256 readout and plumbing blocks (a note of the source repository), or check it "
                         "with its own runner's freeze check")
    code = EXIT_FAIL if failures else EXIT_ATTENTION if attention else EXIT_OK
    return {"prereg": str(prereg), "target": target or "working tree", "sets": counts, "files": rows,
            "failures": failures, "attention": attention, "deviations": len(devs),
            "split": counts[PLUMBING] > 0, "exit": code}


def format_prereg(report):
    c = report["sets"]
    head = (f"{report['prereg']}: {c[READOUT]} readout and {c[PLUMBING]} plumbing file(s) against the "
            f"{_where(report['target'] if report['target'] != 'working tree' else None)}")
    if not c[READOUT] and not c[PLUMBING]:
        return "\n".join([head] + [f"ATTENTION: {t}" for t in report["attention"]])
    lines = [head]
    for r in report["files"]:
        if r["status"] == "ok":
            continue
        d = r["deviation"]
        extra = f" ({d['date']}: {d['reason']})" if d else ""
        lines.append(f"{r['status']:<28} {r['path']}{extra}")
    lines += [f"FAIL: {t}" for t in report["failures"]] + [f"ATTENTION: {t}" for t in report["attention"]]
    ok = sum(1 for r in report["files"] if r["status"] == "ok")
    lines.append(f"{ok} of {len(report['files'])} file(s) unchanged")
    return "\n".join(lines)
