"""Local experiment ledger: one ``run.json`` per experiment under ``experiments/``.

Two rules from the prize page and from published First Letters runs are enforced here:

1. The readout rule (what will count as ink) is written before any target output is
   viewed, and its SHA-256 is stored so a later edit is detectable.
2. A run marked ``candidate`` (possible letters) cannot be marked ``published`` unless
   the prize has been officially announced. The prize rules forbid making a discovery
   public before that.

``experiments/*`` is gitignored. Nothing here is pushed unless you choose to.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import prizes

DEFAULT_ROOT = Path("experiments")
STATUSES = ("planned", "running", "null", "candidate", "submitted", "published")
TRANSITIONS = {
    "planned": {"running", "null"},
    "running": {"null", "candidate", "running"},
    "null": {"published", "running"},
    "candidate": {"submitted", "null"},
    "submitted": {"published", "null"},
    "published": set(),
}


class LedgerError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def path_for(slug, root=DEFAULT_ROOT):
    if not slug or "/" in slug or slug.startswith("."):
        raise LedgerError(f"bad slug: {slug!r}")
    return Path(root) / slug / "run.json"


def load(slug, root=DEFAULT_ROOT):
    path = path_for(slug, root)
    if not path.exists():
        raise LedgerError(f"no experiment at {path}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(record, root=DEFAULT_ROOT):
    path = path_for(record["slug"], root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
        fh.write("\n")
    return path


def init(slug, scroll, question, readout, root=DEFAULT_ROOT, villa_commit=None, snapshot=None):
    if path_for(slug, root).exists():
        raise LedgerError(f"{slug} already exists")
    if not readout.strip():
        raise LedgerError("a readout rule is required before the run starts")
    snapshot = snapshot or prizes.load()
    record = {
        "slug": slug,
        "created": _now(),
        "scroll": scroll,
        "first_letters_volume": prizes.eligible_volume(snapshot, scroll),
        "prize_snapshot": snapshot["checked"],
        "question": question,
        "readout_rule": readout,
        "readout_rule_sha256": _sha(readout),
        "villa_commit": villa_commit,
        "status": "planned",
        "history": [{"at": _now(), "status": "planned", "note": "created"}],
        "costs": [],
    }
    return save(record, root), record


def set_status(slug, status, note="", announced=False, root=DEFAULT_ROOT):
    record = load(slug, root)
    current = record["status"]
    if status not in STATUSES:
        raise LedgerError(f"unknown status {status!r}; use one of {', '.join(STATUSES)}")
    if status not in TRANSITIONS[current]:
        raise LedgerError(f"cannot go from {current} to {status}")
    if status == "published" and current == "submitted" and not announced:
        raise LedgerError(
            "a submitted result stays private until the prize is officially announced; "
            "pass --announced only after Vesuvius Challenge announces it"
        )
    record["status"] = status
    record["history"].append({"at": _now(), "status": status, "note": note})
    save(record, root)
    return record


def add_cost(slug, usd, what, root=DEFAULT_ROOT):
    if usd < 0:
        raise LedgerError("cost cannot be negative")
    record = load(slug, root)
    record["costs"].append({"at": _now(), "usd": round(usd, 2), "what": what})
    save(record, root)
    return record


def total_cost(record):
    return round(sum(item["usd"] for item in record["costs"]), 2)


def check(slug, root=DEFAULT_ROOT):
    """Return a list of problems; empty means the record is consistent."""
    record = load(slug, root)
    problems = []
    if _sha(record.get("readout_rule", "")) != record.get("readout_rule_sha256"):
        problems.append("readout rule was edited after the run was created")
    if record.get("status") not in STATUSES:
        problems.append(f"unknown status {record.get('status')!r}")
    seen = [h["status"] for h in record.get("history", [])]
    for before, after in zip(seen, seen[1:]):
        if after not in TRANSITIONS.get(before, set()):
            problems.append(f"history has an illegal step {before} -> {after}")
    if seen and seen[-1] != record.get("status"):
        problems.append("status does not match the last history entry")
    return problems


def list_runs(root=DEFAULT_ROOT):
    root = Path(root)
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*/run.json")):
        with open(path, encoding="utf-8") as fh:
            out.append(json.load(fh))
    return out
