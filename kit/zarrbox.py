"""Copy one box of a zarr volume, chunk files byte for byte, with a sha256 list that can be checked later.

  plan    the box's chunks at one pyramid level: count, stored bytes (one HEAD each on a URL) and how many are
          absent, before anything is downloaded
  copy    the volume's metadata and only the box's chunk files into a folder, keeping the zarr key layout, so a zarr
          reader opens the folder as the same volume at the same coordinates (every other chunk reads as the fill
          value); writes zarrbox.json there with each chunk's size and sha256
  verify  a copy against its zarrbox.json: every listed file present with its sha256, no extra chunk files at that
          level; with --source, every chunk read again from the source and compared too

The box is given in level-0 voxels, half-open, Z0-Z1,Y0-Y1,X0-X1, with * for a whole axis, and is widened to the
chosen level's chunk grid. Chunks are never decoded or re-encoded, so compressed volumes stay as stored and a copy
can be checked file by file against the source. A box copy is a copy of the volume, not a reading of it.
Standard library only (the chunk reader is kit.tifxyz's: local folders, https:// and s3:// on the open-data bucket).
"""

import argparse
import datetime
import hashlib
import json
import math
import sys
from pathlib import Path

from . import tifxyz as tx
from .verify import VerifyError

SCHEMA = "scrolls-zarrbox/1"
MANIFEST = "zarrbox.json"


def parse_box(text):
    """'Z0-Z1,Y0-Y1,X0-X1' (level-0 voxels, half-open; '*' for a whole axis) -> [[z0, z1] or None, ...]."""
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 3:
        raise VerifyError(f"--box needs three ranges Z0-Z1,Y0-Y1,X0-X1 (got {text!r})")
    out = []
    for axis, p in zip("zyx", parts):
        if p == "*":
            out.append(None)
            continue
        a, sep, b = p.partition("-")
        try:
            lo, hi = int(a), int(b)
        except ValueError:
            raise VerifyError(f"--box {axis} range {p!r} is not START-END in whole voxels (or *)") from None
        if not sep or lo < 0 or hi <= lo:
            raise VerifyError(f"--box {axis} range {p!r} needs 0 <= START < END")
        out.append([lo, hi])
    return out


def box_chunks(arr, box):
    """(level box [[lo, hi]] * 3 aligned to the chunk grid and clipped to the shape, chunk index ranges, count).
    The level-0 box is divided by the level's scale (lo rounded down, hi up) before alignment."""
    lv, idx = [], []
    for b, f, s, c in zip(box, arr["factor"], arr["shape"], arr["chunks"]):
        lo, hi = (0, s) if b is None else (int(math.floor(b[0] / f)), int(math.ceil(b[1] / f)))
        lo, hi = max(0, lo), min(s, hi)
        if hi <= lo:
            raise VerifyError(f"the box lies outside the volume at level {arr['level']} (shape {arr['shape']})")
        i0, i1 = lo // c, -(-hi // c)
        idx.append((i0, i1))
        lv.append([i0 * c, min(s, i1 * c)])
    return lv, idx, math.prod(i1 - i0 for i0, i1 in idx)


def _keys(arr, idx):
    return [tx.chunk_key(arr, (z, y, x)) for z in range(*idx[0]) for y in range(*idx[1]) for x in range(*idx[2])]


def plan(volume, box, level=0, max_requests=tx.MAX_REQUESTS, src=None, sizes=True):
    """(report dict, chunk keys, sizes) for the box at one level; sizes are None for absent chunks."""
    src = src or tx.ZarrSource(volume)
    arr = tx.zarr_level(src, level)
    lv, idx, n = box_chunks(arr, box)
    keys = _keys(arr, idx)
    if sizes and len(keys) > max_requests:
        raise VerifyError(f"the box holds {len(keys)} chunks at level {level}, over --max-requests {max_requests}: "
                          "raise it, take a coarser --level or a smaller --box")
    got = tx._sizes(src, keys) if sizes else []
    present = [s for s in got if s is not None]
    rep = {"volume": src.root, "level": level, "level_path": arr["path"],
           "level_factor_zyx": [round(v, 4) for v in arr["factor"]], "shape_zyx": arr["shape"],
           "chunk_zyx": arr["chunks"], "dtype": arr.get("dtype"), "sharded": bool(arr.get("sharded")),
           "box_base": box, "box_level": lv, "chunks": n}
    if sizes:
        rep.update(present=len(present), absent=n - len(present), bytes=int(sum(present)))
    return rep, keys, got


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _listing_sha(rows):
    return hashlib.sha256("".join(f"{r['key']} {r['sha256']}\n" for r in sorted(rows, key=lambda r: r["key"]))
                          .encode()).hexdigest()


def copy(volume, box, dest, level=0, max_requests=tx.MAX_REQUESTS, workers=tx.CHUNK_WORKERS, src=None, now=None):
    """Copy the box into dest and write dest/zarrbox.json; returns the manifest."""
    src = src or tx.ZarrSource(volume)
    rep, keys, sizes = plan(volume, box, level, max_requests, src)
    arr = tx.zarr_level(src, level)
    dest = Path(dest)
    written, skipped, nbytes = tx.fetch_chunks(src, arr["levels"], keys, sizes, dest, workers)
    rows, absent = [], []
    for k, s in zip(keys, sizes):
        p = dest / k
        if s is None or not p.is_file():
            absent.append(k)
            continue
        rows.append({"key": k, "bytes": p.stat().st_size, "sha256": _sha(p)})
    meta = [{"key": str(p.relative_to(dest).as_posix()), "sha256": _sha(p)}
            for p in sorted(dest.rglob("*")) if p.is_file() and p.name in tx._ROOT_META + (".zarray",)]
    now = now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    man = dict(schema=SCHEMA, made_utc=now, **rep)
    man.update(present=len(rows), absent=len(absent), bytes=sum(r["bytes"] for r in rows),
               written=written, skipped=skipped, chunks_sha256=_listing_sha(rows),
               files=rows, absent_keys=absent, meta=meta)
    (dest / MANIFEST).write_text(json.dumps(man, indent=1) + "\n")
    return man


def verify(dest, source=False, src=None):
    """Check a copy against its manifest: (report dict, ok)."""
    dest = Path(dest)
    mp = dest / MANIFEST
    if not mp.is_file():
        raise VerifyError(f"{dest} has no {MANIFEST}: is it a kit zarrbox copy?")
    man = json.loads(mp.read_text())
    if man.get("schema") != SCHEMA:
        raise VerifyError(f"{mp} is schema {man.get('schema')!r}, not {SCHEMA}")
    missing, changed = [], []
    for r in man["files"] + man.get("meta", []):
        p = dest / r["key"]
        if not p.is_file():
            missing.append(r["key"])
        elif _sha(p) != r["sha256"]:
            changed.append(r["key"])
    listed = {r["key"] for r in man["files"]} | set(man.get("absent_keys", []))
    level_dir = dest / man["level_path"] if man["level_path"] else dest
    extra = []
    if level_dir.is_dir():
        for p in level_dir.rglob("*"):
            k = p.relative_to(dest).as_posix()
            if p.is_file() and p.name not in tx._ROOT_META + (".zarray",) and k != MANIFEST and k not in listed:
                extra.append(k)
    rep = {"dest": str(dest), "volume": man["volume"], "level": man["level"], "files": len(man["files"]),
           "missing": missing, "changed": changed, "extra": sorted(extra),
           "chunks_sha256_ok": _listing_sha(man["files"]) == man["chunks_sha256"]}
    if source:
        src = src or tx.ZarrSource(man["volume"])
        differ = []
        for r in man["files"]:
            raw = src.read(r["key"])
            if raw is None or hashlib.sha256(raw).hexdigest() != r["sha256"]:
                differ.append(r["key"])
        now_present = [k for k in man.get("absent_keys", []) if src.size(k) is not None]
        rep["source"] = {"checked": len(man["files"]) + len(man.get("absent_keys", [])), "differ": differ,
                         "now_present": now_present}
    ok = not (missing or changed or extra) and rep["chunks_sha256_ok"]
    if source:
        ok = ok and not rep["source"]["differ"] and not rep["source"]["now_present"]
    rep["ok"] = ok
    return rep, ok


def _human(n):
    return tx._human(n)


def _box_text(b):
    return ", ".join(f"{a} {lo}-{hi}" for a, (lo, hi) in zip("zyx", b))


def format_plan(r):
    f = r["level_factor_zyx"]
    res = "full resolution" if f[0] == 1 else f"1/{f[0]:g} of level 0"
    lines = [f"{r['volume']}, level {r['level']} ({res}), chunks {' x '.join(map(str, r['chunk_zyx']))} (z, y, x)"
             f"{', sharded' if r['sharded'] else ''}",
             f"  box        {_box_text(r['box_level'])} (level voxels, widened to the chunk grid)",
             f"  chunks     {r['chunks']}"]
    if "bytes" in r:
        lines.append(f"  stored     {r['present']} present, {_human(r['bytes'])}; {r['absent']} absent (read as the "
                     "fill value)")
    return "\n".join(lines)


def format_copy(m, dest):
    return "\n".join([format_plan(m),
                      f"  copied     {m['written']} chunks written, {m['skipped']} already there, into {dest}",
                      f"  manifest   {Path(dest) / MANIFEST}: {m['present']} sha256 rows, chunks_sha256 "
                      f"{m['chunks_sha256'][:16]}"])


def format_verify(r):
    head = "OK" if r["ok"] else "FAIL"
    lines = [f"{head}  {r['dest']} ({r['files']} chunk files, level {r['level']} of {r['volume']})"]
    for name in ("missing", "changed", "extra"):
        if r[name]:
            lines.append(f"  {name:<10} {len(r[name])}: {', '.join(r[name][:5])}{' ...' if len(r[name]) > 5 else ''}")
    if not r["chunks_sha256_ok"]:
        lines.append("  manifest   its chunks_sha256 does not match its own rows (the manifest was edited)")
    if "source" in r:
        s = r["source"]
        lines.append(f"  source     {s['checked']} keys checked; {len(s['differ'])} differ, {len(s['now_present'])} "
                     "absent then and present now")
    return "\n".join(lines)


def build_parser(p):
    actions = p.add_subparsers(dest="action", required=True)

    def common(a):
        a.add_argument("volume", help="the volume's zarr folder or URL (https://, or s3:// on the open-data bucket)")
        a.add_argument("--box", required=True, help="Z0-Z1,Y0-Y1,X0-X1 in level-0 voxels, half-open; * for a whole "
                                                    "axis")
        a.add_argument("--level", type=int, default=0, help="pyramid level to copy (0 is full resolution)")
        a.add_argument("--max-requests", type=int, default=tx.MAX_REQUESTS, help="refuse a box with more chunks")
        a.add_argument("--json", action="store_true")

    a = actions.add_parser("plan", help="the box's chunks: count, stored bytes, absent ones; downloads nothing")
    common(a)
    a = actions.add_parser("copy", help="copy the metadata and the box's chunk files, with a sha256 manifest")
    common(a)
    a.add_argument("--to", required=True, metavar="DEST", help="the folder to write (created; reruns skip chunks "
                                                               "already there at the same size)")
    a.add_argument("--workers", type=int, default=tx.CHUNK_WORKERS, help="parallel downloads from a URL")
    a = actions.add_parser("verify", help="check a copy against its zarrbox.json (and the source with --source)")
    a.add_argument("dest", help="a folder kit zarrbox copy wrote")
    a.add_argument("--source", action="store_true", help="also read every chunk again from the source and compare")
    a.add_argument("--json", action="store_true")
    return p


def run(args):
    if args.action == "verify":
        r, ok = verify(args.dest, args.source)
        print(json.dumps(r, indent=1) if args.json else format_verify(r))
        return 0 if ok else 1
    box = parse_box(args.box)
    if args.action == "plan":
        r, _, _ = plan(args.volume, box, args.level, args.max_requests)
        print(json.dumps(r, indent=1) if args.json else format_plan(r))
        return 0
    m = copy(args.volume, box, args.to, args.level, args.max_requests, args.workers)
    if args.json:
        print(json.dumps({k: v for k, v in m.items() if k not in ("files", "absent_keys", "meta")}, indent=1))
    else:
        print(format_copy(m, args.to))
    return 0


def cmd_zarrbox(args):
    """python -m kit zarrbox ACTION: exit 0 when done (verify: when the copy matches), 1 when verify finds a
    difference, 2 on bad input or a read or write that failed."""
    try:
        return run(args)
    except VerifyError as exc:
        print(f"kit zarrbox: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"kit zarrbox could not read or write a file: {exc}", file=sys.stderr)
        return 2


def main(argv=None):
    p = build_parser(argparse.ArgumentParser(prog="python -m kit.zarrbox", description=__doc__.split("\n\n")[0]))
    return cmd_zarrbox(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
