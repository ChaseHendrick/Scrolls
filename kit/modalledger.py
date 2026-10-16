"""Append one row per Modal launch to a Modal cost ledger (docs/compute/modal-ledger.csv), never twice.

The columns come from the ledger's own header, so one writer serves the private ledger (which has lane_branch and
app_id) and the public one (which has neither). Every row this module writes ends its notes with a key,
"autoledger <key>" (for the AutoPipeline runner, modal_autopipe:<launch token>). A row is not written when the
ledger already holds its key, or a row with its app id: a rerun, a resumed launch or a hand-written row of the same
app never makes a duplicate. Writers take an advisory lock where the platform has fcntl (Mac and Linux), and the
file is replaced atomically. Standard library only.

A ledger whose header has no lane_branch column is the public ledger. It takes a row only when the caller passes
public=True (an explicit flag on every command line that writes one) and the row is marked generic: a run of
released data with no title, target, preregistered or held-out work in it (public_refusal). Fields the public
header lacks, such as lane_branch and app_id, are left out of a public row.
"""

import csv
import hashlib
import io
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # other platforms: write the ledger from one process at a time
    fcntl = None

KEY_MARK = "autoledger "
PRIVATE_ONLY = ("lane_branch", "app_id")
# Words that mark work the public ledger never carries, matched in purpose and notes, lower case
PUBLIC_BLOCK = ("title", "target", "prereg", "held out", "held-out", "heldout", "experiment", "candidate")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
NUMBER = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


class LedgerRowError(Exception):
    pass


def read(path):
    """(header, rows) of a ledger CSV; rows are dicts by the header's columns."""
    text = Path(path).read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise LedgerRowError(f"{path} has no header row")
    return list(reader.fieldnames), list(reader)


def is_public(header):
    return "lane_branch" not in header


def holds(rows, key, app_id=None):
    """True when a row carries this key, or this app id (when one is given)."""
    mark = KEY_MARK + key
    for r in rows:
        if mark in [part.strip() for part in (r.get("notes") or "").split(";")]:
            return True
        if app_id and (r.get("app_id") or "") == app_id:
            return True
    return False


def public_refusal(row, generic):
    """Why this row may not go into the public ledger, or None."""
    if not generic:
        return "only a run marked generic goes into the public ledger"
    text = " ".join(str(row.get(k) or "") for k in ("purpose", "notes")).lower()
    hits = [w for w in PUBLIC_BLOCK if w in text]
    if hits:
        return f"the row names {', '.join(hits)} work, which the public ledger never carries"
    return None


def _cell(v):
    """A CSV cell. A text cell a spreadsheet would read as a formula (it starts with = + - @, a tab or a carriage
    return, OWASP's CSV injection list) gets a leading apostrophe; numbers, and text that is a plain number such
    as -0.5, are written as they are."""
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.8f}".rstrip("0").rstrip(".") if v else "0"
    s = str(v)
    if isinstance(v, str) and s[:1] in FORMULA_START and not NUMBER.fullmatch(s):
        return "'" + s
    return s


@contextmanager
def _lock(path):
    digest = hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:16]
    with open(Path(tempfile.gettempdir()) / f"modalledger-{digest}.lock", "a") as fh:
        if fcntl is not None:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)


def append(path, row, key, public=False, generic=False):
    """Write row (column: value) to the ledger at path under key, unless it is there already. Returns True when
    written, False when the ledger already held the key or the row's app id. Refuses a column the header lacks
    (other than the private-only ones, which a public row leaves out), and a public ledger without public=True or
    a row public_refusal turns down. The key goes at the end of the notes."""
    path = Path(path)
    if not key or any(c in key for c in ";\n\r"):
        raise LedgerRowError("a ledger key is a non-empty string without ';' or a line break")
    with _lock(path):
        header, rows = read(path)
        if is_public(header):
            if not public:
                raise LedgerRowError(f"{path} is the public ledger: pass the explicit public flag "
                                     "(--public-generic) for a generic run, or write the private ledger")
            why = public_refusal(row, generic)
            if why:
                raise LedgerRowError(f"{path}: {why}")
            row = {k: v for k, v in row.items() if k not in PRIVATE_ONLY}
        unknown = sorted(set(row) - set(header))
        if unknown:
            raise LedgerRowError(f"{path} has no column {', '.join(unknown)}")
        if holds(rows, key, None if is_public(header) else row.get("app_id")):
            return False
        cells = {k: _cell(row.get(k)) for k in header}
        notes = cells.get("notes", "")
        cells["notes"] = f"{notes}; {KEY_MARK}{key}" if notes else KEY_MARK + key
        text = path.read_text(encoding="utf-8")
        out = io.StringIO()
        if text and not text.endswith("\n"):
            out.write("\n")
        csv.DictWriter(out, fieldnames=header, lineterminator="\n").writerow(cells)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".modal-ledger-",
                                             delete=False) as fh:
                temporary = Path(fh.name)
                fh.write(text + out.getvalue())
            os.chmod(temporary, path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return True
