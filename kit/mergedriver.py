"""Git merge drivers for files that several branches append to: CSV tables by row, JSON registries by entry,
Markdown indexes and JSON-lines logs by line.

  python -m kit.mergedriver install [--csv-key COL,COL] [--check] [--quiet]   set the drivers in this clone's .git/config
  python -m kit.mergedriver status                   say whether they are set
  python -m kit.mergedriver attributes               print example .gitattributes lines
  python -m kit.mergedriver csv [--key COL,COL] BASE OURS THEIRS [PATH]   git calls these, writing the result into OURS
  python -m kit.mergedriver json BASE OURS THEIRS [PATH]
  python -m kit.mergedriver lines BASE OURS THEIRS [PATH]

Why: in a repository where many branches each add a row to a run log, an entry to a JSON registry or a line to an
index, git's line merge calls two different additions at the same place a conflict, though nothing conflicts. In one
busy repository, replaying a week of merges found that in more than half of the merges with textual conflicts every
conflicting file was such a table, registry or index. git's own merge=union is unsafe for a table whose rows are
also edited in place, since it keeps both versions of an edited row.

The drivers are listed in .gitattributes (committed; `attributes` prints examples) and defined in each clone's
.git/config by `install`. A clone without them merges these files as before, so nothing breaks where they are not
set. Each driver merges by identity, not by line:

- csv: rows keyed by the key columns (`--key`, default the column named id, else the first column), with an
  occurrence number for repeats. A row added on one side is kept; a row changed on one side takes that change; a row
  changed on both sides merges field by field. Rows keep their original bytes unless merged field by field. The
  result always has LF line ends.
- json: objects merged key by key, lists of objects that all carry a unique "id" merged by id, other lists merged
  only when one side left them alone. The file is written back only when the format round-trips byte for byte
  (indent and ensure_ascii are detected), so the diff never reformats the file.
- lines: git merge-file first; in each hunk it calls a conflict, lines or table rows that both sides added at the
  same place are all kept, ours first, then theirs (a nonblank line both added is kept once), and an edit on one side
  next to an addition on the other is taken. Both sides editing or removing the same existing line is a real
  conflict. An append-only log (a path ending .jsonl) takes the same driver with the other order: the merge base,
  then theirs' new lines, then ours' new lines that theirs lacks, each side in its own order, so a branch merging the
  main branch in keeps main's log first. KIT_LINES_FIRST=ours or theirs overrides the order for such a log.

Whenever a driver meets a real conflict (the same field changed two ways, a row changed on one side and removed on
the other, a format it does not understand, or any error), it falls back to `git merge-file`, which leaves the usual
conflict markers and exit status. If Python itself fails, the configured command runs git merge-file on the
untouched files, so the worst case is git's own behavior. Standard library only.
Exit codes: 0 merged cleanly, 3 conflict markers left in OURS (git stops the merge), 2 bad arguments; install
--check and status: 1 when a driver is missing.
"""
import argparse
import csv
import io
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

DRIVERS = {
    "kit-csv": ("rows of a CSV table, by key (kit.mergedriver)", "csv"),
    "kit-json": ("entries of a JSON registry, by key and id (kit.mergedriver)", "json"),
    "kit-lines": ("a Markdown record or index, keeping lines added on both sides (kit.mergedriver)", "lines"),
}
EXIT_OK, EXIT_CONFLICT, EXIT_ARGS, EXIT_MARKERS = 0, 1, 2, 3
# the command git runs: a driver that merged (0) or left markers itself (3) is final; any other exit (Python failed
# to start, an import error) falls back to git merge-file on the untouched files, so their side is never lost
DRIVER = ('python3 -m kit.mergedriver {kind}{opts} %O %A %B %P; s=$?; if [ $s -eq 0 ] || [ $s -eq 3 ]; then exit $s; '
          'fi; git merge-file -L ours -L base -L theirs %A %O %B')
ATTRIBUTES = """# Example .gitattributes lines for kit.mergedriver (paths are examples; list your own files)
logs/runs.csv          merge=kit-csv
registry/*.json        merge=kit-json
docs/INDEX.md          merge=kit-lines
logs/*.jsonl           merge=kit-lines
"""


class Conflict(Exception):
    """A real conflict: the caller falls back to git merge-file."""


# ---------------------------------------------------------------- csv

def _key_columns(header, key=None):
    """The key columns: KEY (a list of names, all in the header), else id, else the first column."""
    if key:
        missing = [k for k in key if k not in header]
        if missing:
            raise Conflict(f"csv: no column(s) {', '.join(missing)} to key rows by")
        return list(key)
    return ["id"] if "id" in header else header[:1]


def _csv_rows(text, key=None):
    """(header, [(key, fields, raw_text)]) keeping each record's original bytes; Conflict when it cannot parse."""
    if not text:
        return None, []
    lines = text.splitlines(keepends=True)
    reader = csv.reader(lines)
    try:
        header = next(reader)
    except StopIteration:
        return None, []
    except csv.Error as exc:
        raise Conflict(f"csv: {exc}")
    cols = _key_columns(header, key)
    out, seen, start = [], {}, reader.line_num
    while True:
        try:
            fields = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            raise Conflict(f"csv: {exc}")
        raw = "".join(lines[start:reader.line_num])
        start = reader.line_num
        if not fields:
            continue
        if not raw.endswith(("\n", "\r")):
            raw += "\n"                    # a last record without its newline must not glue onto the next
        rec = dict(zip(header, fields + [""] * (len(header) - len(fields))))
        k = tuple(rec.get(c, "") for c in cols)
        if k == ("",) * len(k):
            k = tuple(fields)
        n = seen.get(k, 0)
        seen[k] = n + 1
        out.append((k + (n,), fields, raw))
    return header, out


def _merge_fields(b, o, t):
    if o == t:
        return o
    if b is not None and o == b:
        return t
    if b is not None and t == b:
        return o
    if b is None or len(b) != len(o) or len(o) != len(t):
        raise Conflict("a row added or changed differently on both sides")
    out = []
    for x, y, z in zip(b, o, t):
        if y == z or x == z:
            out.append(y)
        elif x == y:
            out.append(z)
        else:
            raise Conflict("the same field changed two ways")
    return out


def _format_row(fields, newline):
    buf = io.StringIO()
    csv.writer(buf, lineterminator=newline).writerow(fields)
    return buf.getvalue()


def merge_csv(base, ours, theirs, key=None):
    """The merged text, always with LF line ends; Conflict for a real conflict. Every side is read with CRLF turned
    into LF first, so a hand-resolved merge that wrote CRLF does not make later merges flip the file between the two.
    KEY: the key column names (default id, else the first column)."""
    base, ours, theirs = (x.replace("\r\n", "\n") if x else x for x in (base, ours, theirs))
    hb, rb = _csv_rows(base, key)
    ho, ro = _csv_rows(ours, key)
    ht, rt = _csv_rows(theirs, key)
    if ho is None or ht is None or ho != ht or (hb is not None and hb != ho):
        raise Conflict("csv: the headers differ or a side is empty")
    # a key that repeats in some version and changed count cannot be paired row by row: the whole group goes to the
    # side that changed it, and to a conflict when both sides did
    groups = [{} for _ in range(3)]
    for g, rows in zip(groups, (rb, ro, rt)):
        for k, f, _ in rows:
            g.setdefault(k[:-1], []).append(f)
    whole = {}
    for k in set(groups[1]) | set(groups[2]):
        n = [len(g[k]) for g in groups if k in g]
        if len(n) > 1 and max(n) > 1 and len(set(n)) > 1:
            gb, go, gt = (g.get(k, []) for g in groups)
            if go == gt or gt == gb:
                whole[k] = "ours"
            elif go == gb:
                whole[k] = "theirs"
            else:
                raise Conflict("csv: a repeated row key changed count on both sides, so its rows cannot be paired")
    newline = "\n"
    bmap = {k: f for k, f, _ in rb}
    tmap = {k: (f, raw) for k, f, raw in rt}
    omap = {k: f for k, f, _ in ro}
    first = ours.splitlines(keepends=True)[0]
    out = [first if first.endswith(("\n", "\r")) else first + newline]
    done = set()
    for k, fo, raw in ro:
        side = whole.get(k[:-1])
        if side == "ours":
            out.append(raw)
            continue
        if side == "theirs":
            if k[:-1] not in done:
                out += [traw for tk, _, traw in rt if tk[:-1] == k[:-1]]
                done.add(k[:-1])
            continue
        fb = bmap.get(k)
        if k not in tmap:
            if fb is None:
                out.append(raw)            # added by us
            elif fb != fo:
                raise Conflict("csv: a row we changed was removed by them")
            continue                       # removed by them
        ft, traw = tmap[k]
        merged = _merge_fields(fb, fo, ft)
        out.append(raw if merged == fo else traw if merged == ft else _format_row(merged, newline))
    for k, ft, traw in rt:
        if k in omap or k[:-1] in done or whole.get(k[:-1]) == "ours":
            continue
        if whole.get(k[:-1]) == "theirs":
            out.append(traw)               # a group we no longer have rows of
            continue
        fb = bmap.get(k)
        if fb is None:
            out.append(traw)               # added by them
        elif fb != ft:
            raise Conflict("csv: a row they changed was removed by us")
    if out and not out[-1].endswith(("\n", "\r")):
        out[-1] += newline
    return "".join(out)


# ---------------------------------------------------------------- json

_MISSING = object()


def _ids(v):
    """The ids of a list whose items are all objects with a unique string or int id; None otherwise."""
    if not isinstance(v, list) or not v or not all(isinstance(x, dict) and "id" in x for x in v):
        return None
    ids = [x["id"] for x in v]
    if not all(isinstance(i, (str, int)) for i in ids) or len(set(ids)) != len(ids):
        return None
    return ids


def _merge_value(b, o, t):
    if o == t:
        return o
    if b is _MISSING:
        raise Conflict("json: the same key or id added two ways")
    if o == b:
        return t
    if t == b:
        return o
    if isinstance(o, dict) and isinstance(t, dict) and isinstance(b, dict):
        return _merge_dict(b, o, t)
    if _ids(o) is not None and _ids(t) is not None and isinstance(b, list):
        return _merge_list_by_id(b, o, t)
    raise Conflict("json: a value changed two ways")


def _merge_dict(b, o, t):
    out = {}
    for k in list(o) + [k for k in t if k not in o]:
        bv, ov, tv = b.get(k, _MISSING), o.get(k, _MISSING), t.get(k, _MISSING)
        if ov is _MISSING:
            if bv is _MISSING:
                out[k] = tv                # added by them
            elif bv != tv:
                raise Conflict(f"json: {k!r} removed by us, changed by them")
            continue
        if tv is _MISSING:
            if bv is _MISSING:
                out[k] = ov                # added by us
            elif bv != ov:
                raise Conflict(f"json: {k!r} changed by us, removed by them")
            continue
        out[k] = _merge_value(bv, ov, tv)
    return out


def _merge_list_by_id(b, o, t):
    bmap = {x["id"]: x for x in b if isinstance(x, dict) and "id" in x}
    tmap = {x["id"]: x for x in t}
    omap = {x["id"]: x for x in o}
    out = []
    for x in o:
        i = x["id"]
        if i not in tmap:
            if i in bmap and bmap[i] != x:
                raise Conflict(f"json: entry {i!r} changed by us, removed by them")
            if i not in bmap:
                out.append(x)
            continue
        out.append(_merge_value(bmap.get(i, _MISSING), x, tmap[i]))
    for x in t:
        i = x["id"]
        if i in omap:
            continue
        if i not in bmap:
            out.append(x)
        elif bmap[i] != x:
            raise Conflict(f"json: entry {i!r} changed by them, removed by us")
    return out


def _json_format(text):
    """(indent, ensure_ascii) that reproduce text byte for byte; Conflict when none does."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise Conflict(f"json: {exc}")
    for indent in (1, 2, 4, None):
        for ensure_ascii in (False, True):
            if json.dumps(data, indent=indent, ensure_ascii=ensure_ascii) + "\n" == text:
                return data, indent, ensure_ascii
    raise Conflict("json: the file's format does not round-trip, so it is merged by line")


def merge_json(base, ours, theirs):
    o, indent, ensure_ascii = _json_format(ours)
    try:
        t = json.loads(theirs)
        b = json.loads(base) if base.strip() else _MISSING
    except ValueError as exc:
        raise Conflict(f"json: {exc}")
    return json.dumps(_merge_value(b, o, t), indent=indent, ensure_ascii=ensure_ascii) + "\n"


# ---------------------------------------------------------------- lines

MARK = 31                                  # conflict marker length: few lines of such files start with 31 of one sign


def _union(a, b):
    """Lines a and b both inserted at one place: a, then b's lines (a nonblank line already in a is kept once)."""
    if a == b:
        return list(a)
    seen = {x for x in a if x.strip()}
    return list(a) + [x for x in b if not (x.strip() and x in seen)]


def _edits(b, x):
    """({gap: inserted lines}, [(i1, i2, new lines)]) turning base lines b into x."""
    import difflib
    ins, rep = {}, []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, b, x, autojunk=False).get_opcodes():
        if tag == "insert":
            ins[i1] = x[j1:j2]
        elif tag != "equal":
            rep.append((i1, i2, x[j1:j2]))
    return ins, rep


def _extends(a, b):
    """True when the shorter of a and b starts or ends the longer and holds a nonblank line: one side made the same
    edit as the other and added lines next to it."""
    short, long_ = sorted((a, b), key=len)
    return any(x.strip() for x in short) and (long_[:len(short)] == short or long_[len(long_) - len(short):] == short)


def union_hunk(b, o, t, first="ours"):
    """One conflict hunk (base, ours, theirs as lists of lines) merged by line union; Conflict when both sides edited
    or removed the same existing line, or one side added lines inside a run the other replaced. FIRST ("ours" or
    "theirs") says whose lines added at one place come first."""
    if o == t:
        return list(o)
    oi, orep = _edits(b, o)
    ti, trep = _edits(b, t)
    reps = {}
    for r in orep + trep:
        for i1, (i2, new) in reps.items():
            if r[0] < i2 and i1 < r[1]:
                if (r[0], r[1]) == (i1, i2) and _extends(new, r[2]):
                    reps[i1] = (i2, max(new, r[2], key=len))   # the same edit, one side adding lines to it
                elif (r[0], r[1], r[2]) != (i1, i2, new):
                    raise Conflict("lines: the same existing line edited on both sides")
                break
        else:
            reps[r[0]] = (r[1], r[2])
    for g in list(oi) + list(ti):
        if any(i1 < g < i2 for i1, (i2, _) in reps.items()):
            raise Conflict("lines: lines added inside a run the other side replaced")
    out, g = [], 0
    while True:
        pair = (oi.get(g, []), ti.get(g, []))
        out += _union(*(pair[::-1] if first == "theirs" else pair))
        if g >= len(b):
            return out
        if g in reps:
            g, new = reps[g]
            out += new
        else:
            out.append(b[g])
            g += 1


def append_only(path):
    """True for an append-only JSON-lines log (merged theirs first when a path is given)."""
    return bool(path) and str(path).endswith(".jsonl")


def lines_first(path):
    """Whose added lines come first for PATH: KIT_LINES_FIRST (ours or theirs) for an append-only log, else theirs
    for one and ours for every other file."""
    if not append_only(path):
        return "ours"
    want = os.environ.get("KIT_LINES_FIRST", "theirs").strip().lower()
    return want if want in ("ours", "theirs") else "theirs"


def merge_append(base, ours, theirs, first="theirs"):
    """An append-only log: when both sides only appended to BASE, BASE, then FIRST's new lines, then the other's new
    lines that FIRST lacks (a nonblank line both sides added is kept once), each side in its own order. Otherwise the
    hunk merge of merge_lines with that order."""
    if ours.startswith(base) and theirs.startswith(base) and (not base or base.endswith("\n")):
        a, b = (theirs, ours) if first == "theirs" else (ours, theirs)
        seen = {x.rstrip("\r\n") for x in a[len(base):].splitlines() if x.strip()}
        tail = [x for x in b[len(base):].splitlines(keepends=True)
                if not (x.strip() and x.rstrip("\r\n") in seen)]
        if not tail:
            return a
        nl = "\r\n" if "\r\n" in a else "\n"
        return a + ("" if not a or a.endswith("\n") else nl) + "".join(tail)
    return merge_lines(base, ours, theirs, first)


def merge_lines(base, ours, theirs, first="ours"):
    """git merge-file, then each conflict hunk merged by union_hunk (FIRST: whose added lines lead); Conflict when one
    cannot be."""
    text, n = _merge_file(base, ours, theirs, "--diff3", f"--marker-size={MARK}")
    if n == 0:
        return text
    start, mid, sep, end = ("<" * MARK, "|" * MARK, "=" * MARK, ">" * MARK)
    out, state, hunk = [], None, None
    for line in text.splitlines(keepends=True):
        s = line.rstrip("\r\n")
        if state is None:
            if s.startswith(start):
                state, hunk = "o", {"o": [], "b": [], "t": []}
            else:
                out.append(line)
        elif state == "o" and s.startswith(mid):
            state = "b"
        elif state == "b" and s == sep:
            state = "t"
        elif state == "t" and s.startswith(end):
            out += union_hunk(hunk["b"], hunk["o"], hunk["t"], first)
            state = None
        elif s.startswith((start, mid, sep, end)):
            raise Conflict("lines: a conflict hunk it cannot read")
        else:
            hunk[state].append(line)
    if state is not None:
        raise Conflict("lines: an unfinished conflict hunk")
    return "".join(out)


# ---------------------------------------------------------------- git plumbing

def _merge_file(base, ours, theirs, *opts):
    """(text, conflict count) from git merge-file -p on three strings (opts: extra merge-file options)."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, s in (("ours", ours), ("base", base), ("theirs", theirs)):
            p = Path(d) / name
            p.write_text(s, encoding="utf-8")
            paths.append(str(p))
        r = subprocess.run(["git", "merge-file", "-p", *opts, "-L", "ours", "-L", "base", "-L", "theirs", *paths],
                           capture_output=True, text=True)
    if r.returncode < 0 or r.returncode > 127:
        raise OSError(f"git merge-file failed: {r.stderr.strip()[:200]}")
    return r.stdout, r.returncode


MERGERS = {"csv": merge_csv, "json": merge_json, "lines": merge_lines}


def _git(root, *args, check=True):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise OSError(f"git {' '.join(args)}: {r.stderr.strip()[:200]}")
    return r.stdout


def drive(kind, base_path, ours_path, theirs_path, path=None, key=None):
    """Merge the three files into ours_path; the exit code git expects. PATH (git's %P) picks the order of an
    append-only log; KEY (a list of column names) keys a CSV table's rows."""
    def read(p):
        with open(p, encoding="utf-8", newline="") as f:   # keep CRLF as it is
            return f.read()
    base, ours, theirs = read(base_path), read(ours_path), read(theirs_path)
    try:
        if kind == "lines" and append_only(path):
            merged = merge_append(base, ours, theirs, lines_first(path))
        elif kind == "csv":
            merged = merge_csv(base, ours, theirs, key)
        else:
            merged = MERGERS[kind](base, ours, theirs)
        status = EXIT_OK
    except Exception as exc:               # any surprise: git's line merge, never a silent loss
        print(f"kit.mergedriver {kind}: {exc}; merging by line", file=sys.stderr)
        merged, n = _merge_file(base, ours, theirs)
        status = EXIT_OK if n == 0 else EXIT_MARKERS
    with open(ours_path, "w", encoding="utf-8", newline="") as f:
        f.write(merged)
    return status


def driver_command(kind, csv_key=None):
    """The command git runs for KIND; CSV_KEY (a list of column names) is passed to the csv driver."""
    opts = f" --key {shlex.quote(','.join(csv_key))}" if kind == "csv" and csv_key else ""
    return DRIVER.format(kind=kind, opts=opts)


def installed_key(command):
    """The --key columns of an installed csv driver command, or None."""
    try:
        words = shlex.split(command.split(";", 1)[0])
    except ValueError:
        return None
    if "--key" in words and words.index("--key") + 1 < len(words):
        return _keys(words[words.index("--key") + 1])
    return None


def install(root=".", check_only=False, csv_key=None):
    """[(name, wanted command)] that were missing or wrong; writes them unless check_only. Without CSV_KEY an
    installed csv driver keeps its key columns."""
    todo = []
    for name, (label, kind) in DRIVERS.items():
        have = _git(root, "config", "--local", "--get", f"merge.{name}.driver", check=False).strip()
        key = csv_key if csv_key is not None or kind != "csv" else installed_key(have)
        want = driver_command(kind, key)
        if have != want:
            todo.append((name, want))
            if not check_only:
                _git(root, "config", "--local", f"merge.{name}.name", label)
                _git(root, "config", "--local", f"merge.{name}.driver", want)
    return todo


def _keys(text):
    keys = [k.strip() for k in str(text or "").split(",") if k.strip()]
    if text is not None and not keys:
        raise argparse.ArgumentTypeError("--key takes column names separated by commas")
    return keys or None


# ---------------------------------------------------------------- command line

def add_arguments(p):
    # git runs drivers from the top of the work tree, so the clone is the current directory
    p.add_argument("--root", default=".", help="the clone (default: the current directory)")
    sub = p.add_subparsers(dest="what", required=True)
    i = sub.add_parser("install", help="set the drivers in this clone's .git/config")
    i.add_argument("--check", action="store_true", help="only report, exit 1 when any is missing")
    i.add_argument("--quiet", action="store_true", help="print nothing when all is well")
    i.add_argument("--csv-key", type=_keys, help="key columns for the csv driver, such as date,job_id "
                   "(default: the column named id, else the first column)")
    sub.add_parser("status", help="say whether the drivers are set")
    sub.add_parser("attributes", help="print example .gitattributes lines")
    for kind in MERGERS:
        s = sub.add_parser(kind, help=f"git's {kind} driver: merge BASE, OURS and THEIRS into OURS")
        if kind == "csv":
            s.add_argument("--key", type=_keys, help="key columns, comma-separated (default: id, else the first column)")
        s.add_argument("base")
        s.add_argument("ours")
        s.add_argument("theirs")
        s.add_argument("path", nargs="?", help="the file's path in the repository (git's %%P): for lines, a "
                       "path ending .jsonl is an append-only log merged theirs first (KIT_LINES_FIRST overrides)")
    return p


def run(args):
    root = Path(args.root)
    try:
        if args.what in MERGERS:
            return drive(args.what, args.base, args.ours, args.theirs, args.path, getattr(args, "key", None))
        if args.what == "attributes":
            print(ATTRIBUTES, end="")
            return EXIT_OK
        if args.what == "status":
            missing = install(root, check_only=True)
            for name, _ in missing:
                print(f"missing  merge.{name}.driver")
            print("OK: drivers set" if not missing else "run python3 -m kit.mergedriver install")
            return EXIT_CONFLICT if missing else EXIT_OK
        if args.what == "install":
            missing = install(root, check_only=args.check, csv_key=args.csv_key)
            if args.check:
                for name, _ in missing:
                    print(f"missing  merge.{name}.driver")
                return EXIT_CONFLICT if missing else EXIT_OK
            if missing or not args.quiet:
                print(f"set {len(missing)} driver(s) in .git/config" if missing else "drivers already set")
            return EXIT_OK
    except (Conflict, OSError) as exc:
        print(f"kit.mergedriver: {exc}", file=sys.stderr)
        return EXIT_ARGS
    return EXIT_ARGS


def main(argv=None):
    return run(add_arguments(argparse.ArgumentParser(prog="python -m kit.mergedriver")).parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
