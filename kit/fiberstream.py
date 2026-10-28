"""Fiber streaming: read the AFV fibers in one box of a scan from Hugging Face without downloading the whole scan.

  python -m kit fibers scans                                   the datasets that carry stream shards
  python -m kit fibers stream --scan ID --box Z0 Z1 Y0 Y1 X0 X1 [--family H|V] [--min-len MM] [--out BOX.afv]
                              [--json FIBERS.json] [--repo OWNER/NAME] [--revision REV] [--source DIR]
  python -m kit fibers filter FILE.afv --box Z0 Z1 Y0 Y1 X0 X1 [--family H|V] [--min-len MM] [--out BOX.afv]
                              [--json FIBERS.json]               the same box from a downloaded .afv
  python -m kit fibers parity FILE.afv --box ... [--scan ID | --source DIR]   both ways, compared: exit 0 when equal
  python -m kit fibers build FILE.afv OUT_DIR [--level L] [--scan ID] [--workers N]   write the stream shards

An .afv (VC3D fiber collection, version 1, written by Qual's AVF_SPLINE_GENERATOR) is a SQLite file: `fibers`, one row
per fiber; `blocks`, each fiber's XYZ points as little-endian float64, at most 257 per block, consecutive blocks sharing
one point; and the R-tree `block_bounds`. The stream shards hold the same rows as Parquet (format "afv-stream",
version 1), under stream/ in the dataset:

  stream/index.json                  the scan, the source file (its metadata, schema and counts), the grid, and every
                                     shard file with its box (whole voxels, rounded outward), rows, bytes and sha256
  stream/L{k}/z{Z}_y{Y}_x{X}.parquet one row per fiber, every fiber in exactly one file; a fiber goes to grid level k,
                                     the smallest whose cell (256 * 2**k voxels of the grid the model ran on) is at
                                     least its extent, and to the cell holding its center; one row group per cell

A box is read in three steps: the index names the files whose box meets it; each file's Parquet footer (one ranged
read) names the row groups whose statistics meet it; those row groups are fetched with ranged reads. Then the rule
every reader of these files uses picks the fibers: a fiber is in the box when one of its blocks' R-tree bounds meets it
(max >= lo and min < hi on x, y and z, as load_example.py and the AFV Fibers Space do). Output is the same as filtering
the downloaded whole-scan file: the same fibers, ids, rows and points, and a byte-identical .afv from `write_afv`.

numpy is needed for everything but `scans`; pyarrow for `stream` and `build`. Standard library otherwise.
"""
import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

__all__ = ["FiberStreamError", "Fiber", "SCANS", "box_touches", "read_afv", "afv_source_info", "write_afv",
           "records_digest", "multiset_digest", "Source", "RangeFile", "open_index", "stream", "iter_stream",
           "build", "verify_build", "main"]

FORMAT = "afv-stream"
VERSION = 1
HF = "https://huggingface.co"
INDEX = "stream/index.json"
CELL = 256              # level-0 grid cell edge, in voxels of the grid the model ran on
FILE_CELLS = 4          # a shard file covers FILE_CELLS**3 cells of its level
MAX_LEVEL = 8
ROWS_PER_GROUP = 20000
POINTS_PER_GROUP = 1 << 17   # a row group holds at most this many points (3 MB as float64) unless one fiber is longer
GROUPS_PER_FILE = 32         # a shard file holds at most this many row groups, so its footer stays small
MORTON_STEP = 32             # fibers are ordered inside a cell by the Morton code of their center on this grid
USER_AGENT = "scrolls-kit-fiberstream (github.com/ChaseHendrick/Scrolls)"
TAIL = 1 << 18          # bytes read from a shard's end when the index gives no footer size
BYTE_STREAM_SPLIT = ["points.list.element", "block_bounds.list.element"]   # float columns that compress better split

# The public AFV Fibers datasets (Qual's AFV V2 model and spline generator over six scans). level: the CT level the
# model ran on, so a grid voxel is 2**level level-0 voxels.
SCANS = {
    "PHerc0009B": {"repo": "SharpMeow/pherc0009b-afv-fibers", "level": 0},
    "PHerc0139": {"repo": "SharpMeow/pherc0139-afv-fibers", "level": 0},
    "PHerc0332": {"repo": "SharpMeow/pherc0332-afv-fibers", "level": 2},
    "PHerc0814": {"repo": "SharpMeow/pherc0814-afv-fibers", "level": 0},
    "PHerc0841": {"repo": "SharpMeow/pherc0841-afv-fibers", "level": 0},
    "PHerc1667": {"repo": "SharpMeow/pherc1667-afv-fibers", "level": 2},
}

FIBER_COLUMNS = ("id", "name", "family", "point_count", "length", "min_x", "max_x", "min_y", "max_y", "min_z", "max_z",
                 "annotation")
BOUND_COLUMNS = ("bmin_x", "bmax_x", "bmin_y", "bmax_y", "bmin_z", "bmax_z")
STAT_COLUMNS = ("id", "point_count", "length", "length_mm") + BOUND_COLUMNS
# Fibers whose 1 mm file (SCAN_afv_v2_1mm.afv) holds the same curves numbered again from 1; see --min-len.
RULE = ("a fiber is in the box [z0, z1) x [y0, y1) x [x0, x1) (level-0 voxels) when one of its blocks' R-tree bounds "
        "has max_x >= x0, min_x < x1, max_y >= y0, min_y < y1, max_z >= z0 and min_z < z1")


class FiberStreamError(Exception):
    """A refusal or failure, printed as is."""


def _np():
    try:
        import numpy as np
    except ImportError as exc:          # pragma: no cover - environment
        raise FiberStreamError("numpy is needed: pip install numpy") from exc
    return np


def _pa():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:          # pragma: no cover - environment
        raise FiberStreamError("pyarrow is needed to read or write stream shards: pip install pyarrow") from exc
    return pa, pq


class Fiber:
    """One fiber as the .afv stores it: `row` (the fibers table row, FIBER_COLUMNS), `block_ids` and `block_first`
    (each block's id and first segment), `bounds` ((blocks, 6) float32 R-tree bounds: min_x, max_x, min_y, max_y,
    min_z, max_z) and `points` ((N, 3) float64 x, y, z in level-0 voxels)."""

    __slots__ = ("row", "block_ids", "block_first", "bounds", "points")

    def __init__(self, row, block_ids, block_first, bounds, points):
        self.row, self.block_ids, self.block_first, self.bounds, self.points = \
            tuple(row), list(block_ids), list(block_first), bounds, points

    @property
    def id(self):
        return self.row[0]

    @property
    def family(self):
        return self.row[2]

    @property
    def length_mm(self):
        return _length_mm(self.row[11])

    def blocks(self):
        """[(block id, first segment, points blob)], the blocks table rows."""
        n = self.row[3]
        ends = self.block_first[1:] + [n - 1]
        return [(i, f, self.points[f:e + 1].astype("<f8").tobytes())
                for i, f, e in zip(self.block_ids, self.block_first, ends)]

    def bound_rows(self):
        """[(block id, min_x, max_x, min_y, max_y, min_z, max_z)], the R-tree rows."""
        return [(i, *map(float, b)) for i, b in zip(self.block_ids, self.bounds)]

    def digest(self):
        h = hashlib.sha256()
        h.update(json.dumps(list(self.row), separators=(",", ":")).encode())
        h.update(json.dumps([self.block_ids, self.block_first]).encode())
        h.update(self.bounds.astype("<f4").tobytes())
        h.update(self.points.astype("<f8").tobytes())
        return h.digest()


def _length_mm(annotation):
    try:
        v = json.loads(annotation).get("length_mm")
        return float(v) if v is not None else float("nan")
    except (ValueError, AttributeError, TypeError):
        return float("nan")


def parse_box(values):
    """[z0, z1, y0, y1, x0, x1] as numbers; refuses an empty box."""
    if len(values) != 6:
        raise FiberStreamError("a box is six numbers: Z0 Z1 Y0 Y1 X0 X1 (level-0 voxels)")
    box = [float(v) for v in values]
    box = [int(v) if v.is_integer() else v for v in box]
    if not (box[0] < box[1] and box[2] < box[3] and box[4] < box[5]):
        raise FiberStreamError(f"empty box {box}: each low bound must be below its high bound")
    return box


def box_touches(bounds, box):
    """Which rows of (n, 6) bounds (min_x, max_x, min_y, max_y, min_z, max_z) meet the box (z0, z1, y0, y1, x0, x1),
    by the R-tree rule: max >= lo and min < hi on every axis. Compared in float64, as SQLite's R-tree does."""
    np = _np()
    b = np.asarray(bounds, np.float64).reshape(-1, 6)
    z0, z1, y0, y1, x0, x1 = (float(v) for v in box)
    return ((b[:, 1] >= x0) & (b[:, 0] < x1) & (b[:, 3] >= y0) & (b[:, 2] < y1) & (b[:, 5] >= z0) & (b[:, 4] < z1))


def _keep(fiber, family, min_len):
    if family and fiber.row[2] != family:
        return False
    if min_len is not None and not fiber.length_mm >= float(min_len):
        return False
    return True


# ----------------------------------------------------------------------------------------------- reading an .afv

def _connect(path):
    if not Path(path).is_file():
        raise FiberStreamError(f"no such file: {path}")
    return sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)


def _fiber_from_db(db, fid, check=True):
    np = _np()
    row = db.execute(f"SELECT {', '.join(FIBER_COLUMNS)} FROM fibers WHERE id = ?", (fid,)).fetchone()
    if row is None:
        raise FiberStreamError(f"fiber {fid} has no row in the fibers table")
    blocks = db.execute("SELECT id, first_segment, points FROM blocks WHERE fiber_id = ? ORDER BY first_segment",
                        (fid,)).fetchall()
    if not blocks:
        raise FiberStreamError(f"fiber {fid} has no blocks")
    arrays = [np.frombuffer(b[2], "<f8").reshape(-1, 3) for b in blocks]
    for k in range(1, len(arrays)):
        if check and arrays[k][0].tobytes() != arrays[k - 1][-1].tobytes():
            raise FiberStreamError(f"fiber {fid}: block {blocks[k][0]} does not start on the last point of the block "
                                   "before it")
    points = np.concatenate([arrays[0]] + [a[1:] for a in arrays[1:]]).astype(np.float64)
    if check and len(points) != row[3]:
        raise FiberStreamError(f"fiber {fid}: {len(points)} points in its blocks, point_count says {row[3]}")
    bounds = []
    for b in blocks:
        r = db.execute("SELECT min_x, max_x, min_y, max_y, min_z, max_z FROM block_bounds WHERE id = ?",
                       (b[0],)).fetchone()
        if r is None:
            raise FiberStreamError(f"fiber {fid}: block {b[0]} is missing from block_bounds")
        bounds.append(r)
    f = Fiber(row, [b[0] for b in blocks], [b[1] for b in blocks], np.array(bounds, np.float32), points)
    if check:
        if f.block_first[0] != 0:
            raise FiberStreamError(f"fiber {fid}: its first block starts at segment {f.block_first[0]}, not 0")
        if [x[2] for x in f.blocks()] != [b[2] for b in blocks]:
            raise FiberStreamError(f"fiber {fid}: its blocks cannot be rebuilt from its points")
        if not np.array_equal(np.array(bounds, np.float64), f.bounds.astype(np.float64)):
            raise FiberStreamError(f"fiber {fid}: its R-tree bounds are not float32 values")
    return f


def read_afv(path, box=None, family=None, min_len=None, check=True):
    """The fibers of a downloaded .afv that meet the box (all of them when box is None), with the family and minimum
    length (mm) filters, sorted by id: the reference a stream must equal. A generator."""
    db = _connect(path)
    try:
        if box is None:
            ids = [r[0] for r in db.execute("SELECT id FROM fibers ORDER BY id")]
        else:
            z0, z1, y0, y1, x0, x1 = box
            ids = sorted(r[0] for r in db.execute(
                "SELECT DISTINCT b.fiber_id FROM block_bounds r JOIN blocks b ON b.id = r.id WHERE r.max_x >= ? AND "
                "r.min_x < ? AND r.max_y >= ? AND r.min_y < ? AND r.max_z >= ? AND r.min_z < ?",
                (x0, x1, y0, y1, z0, z1)))
        for fid in ids:
            f = _fiber_from_db(db, fid, check=check)
            if _keep(f, family, min_len):
                yield f
    finally:
        db.close()


def afv_source_info(path, sha256=False):
    """What a writer needs from the source .afv: its file name, metadata (raw text values, in order), schema
    statements, pragmas and counts."""
    db = _connect(path)
    try:
        meta = [list(r) for r in db.execute("SELECT key, value FROM metadata ORDER BY rowid")]
        schema = [r[0] for r in db.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' AND "
            "name NOT LIKE 'block\\_bounds\\_%' ESCAPE '\\' ORDER BY rowid")]
        info = {"file": Path(path).name, "bytes": Path(path).stat().st_size, "metadata": meta, "schema": schema,
                "application_id": db.execute("PRAGMA application_id").fetchone()[0],
                "user_version": db.execute("PRAGMA user_version").fetchone()[0],
                "fiber_count": db.execute("SELECT COUNT(*) FROM fibers").fetchone()[0],
                "block_count": db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0],
                "point_count": db.execute("SELECT COALESCE(SUM(point_count), 0) FROM fibers").fetchone()[0]}
    finally:
        db.close()
    if sha256:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
        info["sha256"] = h.hexdigest()
    return info


def write_afv(fibers, dest, source, box=None, family=None, min_len=None):
    """Write fibers as their own .afv with the source's schema, pragmas and metadata (counts updated, the selection
    added): fibers, blocks and R-tree rows in id order, so the same fibers give the same bytes. Returns the counts."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.unlink(missing_ok=True)
    fibers = sorted(fibers, key=lambda f: f.id)
    db = sqlite3.connect(str(tmp))
    try:
        later = [s for s in source["schema"] if s.lstrip().upper().startswith("CREATE INDEX")]
        for sql in source["schema"]:
            if sql not in later:
                db.execute(sql)
        db.execute(f"PRAGMA application_id={int(source['application_id'])}")
        db.execute(f"PRAGMA user_version={int(source['user_version'])}")
        blocks = []
        bounds = []
        for f in fibers:
            blocks += [(i, f.id, first, blob) for i, first, blob in f.blocks()]
            bounds += f.bound_rows()
        blocks.sort()
        bounds.sort()
        db.executemany(f"INSERT INTO fibers({', '.join(FIBER_COLUMNS)}) VALUES({','.join('?' * 12)})",
                       [f.row for f in fibers])
        db.executemany("INSERT INTO blocks(id, fiber_id, first_segment, points) VALUES(?,?,?,?)", blocks)
        db.executemany("INSERT INTO block_bounds VALUES(?,?,?,?,?,?,?)", bounds)
        meta = dict((k, v) for k, v in source["metadata"])
        for k in ("tile_box_zyx", "tile_of"):
            meta.pop(k, None)
        counts = {"fiber_count": len(fibers), "point_count": sum(f.row[3] for f in fibers), "block_count": len(blocks)}
        for k, v in counts.items():
            meta[k] = json.dumps(v)
        meta["selected_from"] = json.dumps(source["file"])
        if box is not None:
            meta["box_zyx_l0"] = json.dumps(list(box), separators=(",", ":"))
        if family:
            meta["family"] = json.dumps(family)
        if min_len is not None:
            meta["minimum_length_mm"] = json.dumps(float(min_len))
        db.executemany("INSERT INTO metadata(key, value) VALUES(?,?)", list(meta.items()))
        for sql in later:
            db.execute(sql)
        db.commit()
    finally:
        db.close()
    tmp.replace(dest)
    return counts


def records_digest(fibers):
    """sha256 over the fibers in the order given (each fiber's row, blocks, bounds and points)."""
    h = hashlib.sha256()
    n = 0
    for f in fibers:
        h.update(f.digest())
        n += 1
    return h.hexdigest(), n


def multiset_digest(fibers):
    """(hex, count): an order-free digest, the sum of the fibers' sha256 values mod 2**256, so two sets agree only
    when they hold the same fibers the same number of times, whatever order they came in."""
    s = 0
    n = 0
    for f in fibers:
        s = (s + int.from_bytes(f.digest(), "big")) % (1 << 256)
        n += 1
    return f"{s:064x}", n


# ------------------------------------------------------------------------------------------------- remote reading

class Source:
    """Where a dataset's files are: a Hugging Face dataset at a revision, read with HTTP range requests, or a local
    folder with the same layout, or any HTTP server that answers range requests (`base_url`, the folder holding
    stream/). Counts the bytes and requests it makes."""

    def __init__(self, repo=None, revision="main", local=None, base_url=None, timeout=60, tries=4):
        if not repo and not local and not base_url:
            raise FiberStreamError("name a dataset (--scan or --repo) or a local folder (--source)")
        self.repo, self.revision, self.local, self.timeout, self.tries = repo, revision, local, timeout, tries
        self.base_url = base_url.rstrip("/") if base_url else None
        self.bytes = 0
        self.requests = 0
        self._lock = threading.Lock()
        self._final = {}

    def label(self):
        return str(self.local) if self.local else self.base_url or f"{self.repo}@{self.revision}"

    def url(self, path):
        if self.base_url:
            return f"{self.base_url}/{path}"
        rev = urllib.parse.quote(self.revision, safe="")
        return f"{HF}/datasets/{self.repo}/resolve/{rev}/{path}"

    def _count(self, n):
        with self._lock:
            self.bytes += n
            self.requests += 1

    def _get(self, url, start=None, end=None):
        headers = {"User-Agent": USER_AGENT}
        if start is not None:
            headers["Range"] = f"bytes={start}-{end - 1}"
        err = None
        for i in range(self.tries):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=self.timeout) as r:
                    data = r.read()
                    got = len(data)
                    if start is not None and r.status != 206:
                        data = data[start:end]          # a server that ignored the range sent the whole file
                    return data, r.geturl(), got
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise FiberStreamError(f"not found: {url} (no stream shards at this revision?)") from exc
                if exc.code in (401, 403):
                    raise FiberStreamError(f"refused ({exc.code}): {url}") from exc
                err = exc
            except (urllib.error.URLError, OSError) as exc:
                err = exc
            time.sleep(1.0 * (i + 1))
        raise FiberStreamError(f"could not read {url}: {err}")

    def read(self, path, start=None, end=None):
        """Bytes of a file, or of [start, end)."""
        if self.local:
            p = Path(self.local) / path
            if not p.is_file():
                raise FiberStreamError(f"not found: {p}")
            with open(p, "rb") as fh:
                if start is None:
                    data = fh.read()
                else:
                    fh.seek(start)
                    data = fh.read(end - start)
            self._count(len(data))
            return data
        if start is None:
            data, _, got = self._get(self.url(path))
            self._count(got)
            return data
        url = self._final.get(path, self.url(path))
        try:
            data, final, got = self._get(url, start, end)
        except FiberStreamError:
            if path not in self._final:
                raise
            self._final.pop(path, None)            # a signed redirect that expired: resolve again
            data, final, got = self._get(self.url(path), start, end)
        with self._lock:
            self._final[path] = final
        self._count(got)
        return data


class RangeFile:
    """A read-only file object over one shard of a Source, for pyarrow: reads come from ranges fetched earlier
    (`prefetch`) or are fetched on demand."""

    def __init__(self, source, path, size):
        self.source, self.path, self.size_, self.pos = source, path, int(size), 0
        self._parts = []                       # sorted (start, bytes)
        self._lock = threading.Lock()
        self.closed = False
        self.mode = "rb"

    def prefetch(self, spans, threads=8):
        spans = sorted((max(0, int(a)), min(self.size_, int(b))) for a, b in spans if b > a)
        merged = []
        for a, b in spans:
            if merged and a <= merged[-1][1] + 4096:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        need = [(a, b) for a, b in merged if not self._covered(a, b)]
        if not need:
            return
        with ThreadPoolExecutor(max(1, min(threads, len(need)))) as pool:
            for (a, _), data in zip(need, pool.map(lambda s: self.source.read(self.path, *s), need)):
                self._add(a, data)

    def _covered(self, a, b):
        with self._lock:
            return any(s <= a and b <= s + len(d) for s, d in self._parts)

    def _add(self, a, data):
        with self._lock:
            self._parts.append((a, data))
            self._parts.sort(key=lambda p: p[0])

    def _slice(self, a, b):
        with self._lock:
            for s, d in self._parts:
                if s <= a and b <= s + len(d):
                    return d[a - s:b - s]
        return None

    # file protocol
    def readable(self):
        return True

    def seekable(self):
        return True

    def writable(self):
        return False

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size_ + off
        return self.pos

    def size(self):
        return self.size_

    def read(self, n=-1):
        a = self.pos
        b = self.size_ if n is None or n < 0 else min(self.size_, a + n)
        if b <= a:
            return b""
        data = self._slice(a, b)
        if data is None:
            data = self.source.read(self.path, a, b)
            self._add(a, data)
        self.pos = b
        return data

    def close(self):
        self.closed = True


def open_index(source):
    """The dataset's stream/index.json, checked for its format and version."""
    try:
        idx = json.loads(source.read(INDEX))
    except ValueError as exc:
        raise FiberStreamError(f"{source.label()}: {INDEX} is not JSON") from exc
    if idx.get("format") != FORMAT or idx.get("version") != VERSION:
        raise FiberStreamError(f"{source.label()}: {INDEX} is format {idx.get('format')!r} version "
                               f"{idx.get('version')!r}; this reader knows {FORMAT} version {VERSION}")
    return idx


def _meets(lo_hi, box):
    """Does a [z0, z1, y0, y1, x0, x1] extent (inclusive maxima) meet the box by the R-tree rule?"""
    return (lo_hi[1] >= box[0] and lo_hi[0] < box[1] and lo_hi[3] >= box[2] and lo_hi[2] < box[3]
            and lo_hi[5] >= box[4] and lo_hi[4] < box[5])


def _rg_meets(md, rg, names, box, family, min_len):
    g = md.row_group(rg)
    st = {}
    for j in range(g.num_columns):
        c = g.column(j)
        if c.path_in_schema in names and c.statistics is not None and c.statistics.has_min_max:
            st[c.path_in_schema] = (c.statistics.min, c.statistics.max)
    try:
        ext = [st["bmin_z"][0], st["bmax_z"][1], st["bmin_y"][0], st["bmax_y"][1], st["bmin_x"][0], st["bmax_x"][1]]
    except KeyError:
        ext = None
    if ext is not None and not _meets(ext, box):
        return False
    if min_len is not None and "length_mm" in st and not st["length_mm"][1] >= float(min_len):
        return False
    if family and "family" in st and st["family"][0] == st["family"][1] and st["family"][0] != family:
        return False
    return True


def _rg_span(md, rg, columns=None):
    """The byte span [lo, hi) of a row group's column chunks (of the named top-level columns only, when given)."""
    g = md.row_group(rg)
    lo, hi = None, 0
    for j in range(g.num_columns):
        c = g.column(j)
        if columns is not None and c.path_in_schema.split(".")[0] not in columns:
            continue
        start = c.dictionary_page_offset if c.has_dictionary_page and c.dictionary_page_offset else c.data_page_offset
        lo = start if lo is None else min(lo, start)
        hi = max(hi, start + c.total_compressed_size)
    return lo, hi


def _fibers_from_table(table, box, family, min_len):
    np = _np()
    if table.num_rows == 0:
        return []
    col = {n: table.column(n).combine_chunks() for n in table.column_names}

    def lists(name, dtype, width):
        arr = col[name]
        offs = arr.offsets.to_numpy().astype(np.int64)
        offs = offs - offs[0]
        vals = arr.flatten().to_numpy(zero_copy_only=False).astype(dtype, copy=False)
        return offs, vals.reshape(-1, width) if width > 1 else vals

    b_offs, b_vals = lists("block_bounds", np.float32, 6)
    hit_block = box_touches(b_vals, box) if box is not None else np.ones(len(b_vals), bool)
    nblk = np.diff(b_offs // 6)
    starts = b_offs[:-1] // 6
    hits = np.zeros(table.num_rows, bool)
    nz = nblk > 0
    if nz.any():
        hits[nz] = np.logical_or.reduceat(hit_block, starts[nz])
    rows = np.flatnonzero(hits)
    if not len(rows):
        return []
    p_offs, p_vals = lists("points", np.float64, 3)
    i_offs, i_vals = lists("block_ids", np.int64, 1)
    f_offs, f_vals = lists("block_first", np.int64, 1)
    plain = {n: col[n].to_pylist() for n in FIBER_COLUMNS}
    out = []
    for r in rows:
        row = tuple(plain[n][r] for n in FIBER_COLUMNS)
        fb = Fiber(row, i_vals[i_offs[r]:i_offs[r + 1]].tolist(), f_vals[f_offs[r]:f_offs[r + 1]].tolist(),
                   b_vals[b_offs[r] // 6:b_offs[r + 1] // 6].copy(), p_vals[p_offs[r] // 3:p_offs[r + 1] // 3].copy())
        if _keep(fb, family, min_len):
            out.append(fb)
    return out


def iter_stream(box, source, index=None, family=None, min_len=None, threads=8, stats=None, skip=()):
    """Yield, file by file, lists of the fibers that meet the box (None: every fiber) from a dataset's stream shards.
    `stats` (a dict) collects the files and row groups read. `skip` names (file, row group) pairs to leave out, for
    the check that a missing piece is caught."""
    pa, pq = _pa()
    idx = index or open_index(source)
    files = [f for f in idx["files"] if box is None or _meets(f["box_zyx"], box)]
    if stats is not None:
        stats.update(files=0, row_groups=0, row_groups_total=sum(f["row_groups"] for f in idx["files"]),
                     files_total=len(idx["files"]), read=[])
    names = set(BOUND_COLUMNS) | {"length_mm", "family"}

    def one(f):
        rf = RangeFile(source, f["path"], f["bytes"])
        md = None
        if f.get("footer_bytes"):
            # the index gives the footer's size: read exactly it (one request) instead of pyarrow's 64 KB tail
            tail = int(f["footer_bytes"]) + 8
            raw = source.read(f["path"], f["bytes"] - tail, f["bytes"])
            try:
                md = pq.read_metadata(pa.BufferReader(b"PAR1" + raw))
            except Exception:                  # pragma: no cover - a pyarrow that wants the whole file
                rf._add(f["bytes"] - tail, raw)
        if md is None:
            rf.prefetch([(max(0, f["bytes"] - TAIL), f["bytes"])])
        pf = pq.ParquetFile(rf, metadata=md)
        md = pf.metadata
        rgs = [i for i in range(md.num_row_groups)
               if (f["path"], i) not in skip and (box is None or _rg_meets(md, i, names, box, family, min_len))]
        if not rgs:
            return [], 0
        if box is not None:
            # first only the small columns, to keep the row groups where some block meets the box; the points and
            # the rest are fetched for those alone
            small = ("block_bounds",)
            rf.prefetch([_rg_span(md, i, small) for i in rgs], threads=threads)
            keep = []
            for i in rgs:
                t = pf.read_row_group(i, columns=list(small), use_threads=False)
                arr = t.column("block_bounds").combine_chunks().flatten().to_numpy(zero_copy_only=False)
                if len(arr) and box_touches(arr.astype(_np().float32), box).any():
                    keep.append(i)
            rgs = keep
            if not rgs:
                return [], 0
        rf.prefetch([_rg_span(md, i) for i in rgs], threads=threads)
        table = pf.read_row_groups(rgs, use_threads=False)
        if stats is not None:
            stats["read"] += [(f["path"], i) for i in rgs]
        return _fibers_from_table(table, box, family, min_len), len(rgs)

    width = max(1, threads)
    with ThreadPoolExecutor(width) as pool:
        for k in range(0, len(files), width):          # a window at a time, so a whole scan never sits in memory
            for fibers, n in pool.map(one, files[k:k + width]):
                if stats is not None:
                    stats["files"] += 1 if n else 0
                    stats["row_groups"] += n
                yield fibers


def stream(box, scan=None, repo=None, revision="main", local=None, family=None, min_len=None, threads=8,
           base_url=None):
    """The fibers meeting the box from a dataset's stream shards, sorted by id, and a dict of what was read (bytes,
    requests, files, row groups, seconds) and the index's source block."""
    if scan and not repo and not local and not base_url:
        if scan not in SCANS:
            raise FiberStreamError(f"no stream dataset known for {scan!r}; scans: {', '.join(SCANS)} (or give --repo)")
        repo = SCANS[scan]["repo"]
    t0 = time.perf_counter()
    src = Source(repo=repo, revision=revision, local=local, base_url=base_url)
    idx = open_index(src)
    if scan and idx.get("scan") and idx["scan"] != scan:
        raise FiberStreamError(f"{src.label()} holds {idx['scan']}, not {scan}")
    stats = {}
    out = []
    for part in iter_stream(box, src, idx, family=family, min_len=min_len, threads=threads, stats=stats):
        out += part
    out.sort(key=lambda f: f.id)
    for a, b in zip(out, out[1:]):
        if a.id == b.id:
            raise FiberStreamError(f"fiber {a.id} is in two shards: the shards are broken")
    stats.pop("read", None)
    stats.update(bytes=src.bytes, requests=src.requests, seconds=round(time.perf_counter() - t0, 3),
                 source=src.label(), scan=idx.get("scan"))
    return out, stats, idx["source"]


# ------------------------------------------------------------------------------------------------------- building

def _schema():
    pa, _ = _pa()
    return pa.schema([("id", pa.int64()), ("name", pa.string()), ("family", pa.string()),
                      ("point_count", pa.int64()), ("length", pa.float64()),
                      *[(c, pa.float64()) for c in FIBER_COLUMNS[5:11]], ("annotation", pa.string()),
                      ("length_mm", pa.float64()), *[(c, pa.float64()) for c in BOUND_COLUMNS],
                      ("block_ids", pa.list_(pa.int64())), ("block_first", pa.list_(pa.int64())),
                      ("block_bounds", pa.list_(pa.float32())), ("points", pa.list_(pa.float64())),
                      ("grid_level", pa.int8()), ("cell_zyx", pa.list_(pa.int32()))])


def _table(fibers, level, cell):
    pa, _ = _pa()
    np = _np()
    cols = {n: [f.row[i] for f in fibers] for i, n in enumerate(FIBER_COLUMNS)}
    cols["length_mm"] = [f.length_mm for f in fibers]
    bb = np.array([[f.bounds[:, 0].min(), f.bounds[:, 1].max(), f.bounds[:, 2].min(), f.bounds[:, 3].max(),
                    f.bounds[:, 4].min(), f.bounds[:, 5].max()] for f in fibers], np.float64).reshape(-1, 6)
    for i, n in enumerate(BOUND_COLUMNS):
        cols[n] = bb[:, i]
    cols["block_ids"] = [f.block_ids for f in fibers]
    cols["block_first"] = [f.block_first for f in fibers]
    cols["block_bounds"] = [f.bounds.astype(np.float32).ravel() for f in fibers]
    cols["points"] = [f.points.astype(np.float64).ravel() for f in fibers]
    cols["grid_level"] = [level] * len(fibers)
    cols["cell_zyx"] = [list(cell)] * len(fibers)
    return pa.Table.from_pydict(cols, schema=_schema())


def _morton(z, y, x):
    """Interleave the bits of three non-negative ints (21 bits each): nearby points get nearby codes."""
    code = 0
    for b in range(21):
        code |= (((z >> b) & 1) << (3 * b + 2)) | (((y >> b) & 1) << (3 * b + 1)) | (((x >> b) & 1) << (3 * b))
    return code


def _place(bb, f):
    """(level, cell zyx, file zyx, Morton code of the center) for a fiber whose union bounds are bb (min_x, max_x,
    ..., in level-0 voxels)."""
    ext = max(bb[1] - bb[0], bb[3] - bb[2], bb[5] - bb[4]) / f
    level = 0
    while level < MAX_LEVEL and ext > CELL * (1 << level):
        level += 1
    size = CELL * (1 << level) * f
    center = ((bb[4] + bb[5]) / 2, (bb[2] + bb[3]) / 2, (bb[0] + bb[1]) / 2)
    cell = tuple(int(math.floor(c / size)) for c in center)
    key = _morton(*(max(0, int(c // (MORTON_STEP * f))) for c in center))
    return level, cell, tuple(int(math.floor(c / FILE_CELLS)) for c in cell), key


def _file_path(level, fcell, f, part=0):
    size = CELL * (1 << level) * f * FILE_CELLS
    tail = f"-p{part}" if part else ""
    return f"stream/L{level}/z{fcell[0] * size:06d}_y{fcell[1] * size:06d}_x{fcell[2] * size:06d}{tail}.parquet"


def _write_file(job):
    """Worker: the shard files of one file cell from the source .afv, in parts of at most GROUPS_PER_FILE row
    groups. job = (afv, out_dir, level, file cell, f, [(cell, [ids in Morton order])]). Returns their index entries."""
    afv, out_dir, level, fcell, f, cells = job
    _, pq = _pa()
    np = _np()
    opts = dict(compression="zstd", compression_level=9, use_dictionary=["family"],
                write_statistics=list(STAT_COLUMNS) + ["family"])
    db = _connect(afv)
    entries = []
    state = {}

    def open_part():
        path = _file_path(level, fcell, f, len(entries))
        dest = Path(out_dir) / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        try:
            w = pq.ParquetWriter(str(tmp), _schema(), **opts, use_byte_stream_split=BYTE_STREAM_SPLIT)
        except Exception:                      # an older pyarrow without byte stream split for list columns
            w = pq.ParquetWriter(str(tmp), _schema(), **opts)
        state.update(path=path, dest=dest, tmp=tmp, writer=w, rows=0, groups=0, ext=None)

    def close_part():
        state["writer"].close()
        state["tmp"].replace(state["dest"])
        data = state["dest"].read_bytes()
        ext = state["ext"]
        entries.append({"path": state["path"], "level": level,
                        "box_zyx": [math.floor(v) if i % 2 == 0 else math.ceil(v) for i, v in enumerate(ext)],
                        "rows": state["rows"], "row_groups": state["groups"], "bytes": len(data),
                        "footer_bytes": int.from_bytes(data[-8:-4], "little"),
                        "sha256": hashlib.sha256(data).hexdigest()})

    def groups_of(ids):
        cur, npts = [], 0
        for i in ids:
            fb = _fiber_from_db(db, i, check=True)
            if cur and (len(cur) >= ROWS_PER_GROUP or npts + fb.row[3] > POINTS_PER_GROUP):
                yield cur
                cur, npts = [], 0
            cur.append(fb)
            npts += fb.row[3]
        if cur:
            yield cur

    try:
        for cell, ids in cells:
            for fibers in groups_of(ids):
                if state and state["groups"] >= GROUPS_PER_FILE:
                    close_part()
                    state.clear()
                if not state:
                    open_part()
                state["writer"].write_table(_table(fibers, level, cell), row_group_size=len(fibers))
                state["groups"] += 1
                state["rows"] += len(fibers)
                b = np.concatenate([x.bounds for x in fibers]).astype(np.float64)
                e = [b[:, 4].min(), b[:, 5].max(), b[:, 2].min(), b[:, 3].max(), b[:, 0].min(), b[:, 1].max()]
                x = state["ext"]
                state["ext"] = e if x is None else [min(x[i], e[i]) if i % 2 == 0 else max(x[i], e[i])
                                                    for i in range(6)]
        if state:
            close_part()
    finally:
        db.close()
    return entries


def build(afv, out_dir, level=0, scan=None, workers=None, sha256=True, say=print):
    """Write a whole-scan .afv's stream shards and stream/index.json under out_dir. Every fiber goes to exactly one
    file; every block is checked to rebuild from its fiber's points. Returns the index."""
    np = _np()
    _pa()
    f = 2 ** int(level)
    t0 = time.perf_counter()
    source = afv_source_info(afv, sha256=sha256)
    db = _connect(afv)
    try:
        ids = []
        bbs = []
        for r in db.execute("SELECT b.fiber_id, MIN(r.min_x), MAX(r.max_x), MIN(r.min_y), MAX(r.max_y), MIN(r.min_z), "
                            "MAX(r.max_z) FROM blocks b JOIN block_bounds r ON r.id = b.id GROUP BY b.fiber_id "
                            "ORDER BY b.fiber_id"):
            ids.append(r[0])
            bbs.append(r[1:])
    finally:
        db.close()
    if len(ids) != source["fiber_count"]:
        raise FiberStreamError(f"{len(ids)} fibers have blocks, the fibers table has {source['fiber_count']}")
    say(f"{len(ids)} fibers placed on the grid in {time.perf_counter() - t0:.1f} s")
    files = {}
    for fid, bb in zip(ids, bbs):
        lvl, cell, fcell, key = _place(bb, f)
        files.setdefault((lvl, fcell), {}).setdefault(cell, []).append((key, fid))
    jobs = [(str(afv), str(out_dir), lvl, fcell, f, [(c, [i for _, i in sorted(v)]) for c, v in sorted(cells.items())])
            for (lvl, fcell), cells in sorted(files.items())]
    jobs.sort(key=lambda j: -sum(len(ids) for _, ids in j[5]))      # the biggest first, so the pool ends together
    entries = []
    workers = workers or os.cpu_count() or 1
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(workers) as pool:
            for i, es in enumerate(pool.map(_write_file, jobs, chunksize=1)):
                entries += es
                if (i + 1) % 50 == 0:
                    say(f"{i + 1}/{len(jobs)} shard file cells")
    else:
        for j in jobs:
            entries += _write_file(j)
    entries.sort(key=lambda e: e["path"])
    index = {"format": FORMAT, "version": VERSION, "scan": scan, "rule": RULE,
             "grid": {"model_level": int(level), "voxel_l0": f, "cell": CELL, "file_cells": FILE_CELLS,
                      "max_level": MAX_LEVEL,
                      "points_per_group": POINTS_PER_GROUP, "groups_per_file": GROUPS_PER_FILE,
                      "morton_step": MORTON_STEP,
                      "placement": "a fiber goes to the smallest level k whose cell edge (cell * 2**k grid voxels) "
                                   "is at least its largest extent, and to the cell holding the center of its block "
                                   "bounds; inside a cell fibers go in the Morton order of their centers (on a grid "
                                   "of morton_step grid voxels), cut into row groups of at most points_per_group "
                                   "points; a file covers file_cells**3 cells of its level, in parts of at most "
                                   "groups_per_file row groups (-p1, -p2, ...)"},
             "columns": [n for n in _schema().names],
             "source": source,
             "totals": {"files": len(entries), "row_groups": sum(e["row_groups"] for e in entries),
                        "rows": sum(e["rows"] for e in entries), "bytes": sum(e["bytes"] for e in entries)},
             "files": entries}
    if index["totals"]["rows"] != source["fiber_count"]:
        raise FiberStreamError(f"wrote {index['totals']['rows']} rows for {source['fiber_count']} fibers")
    out = Path(out_dir) / INDEX
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, indent=1) + "\n")
    say(f"{len(entries)} files, {index['totals']['row_groups']} row groups, {index['totals']['bytes'] / 1e9:.2f} GB "
        f"in {time.perf_counter() - t0:.1f} s")
    return index


def verify_build(out_dir, afv=None):
    """Check written shards against their index: sizes and sha256, every id once, rows equal to the source's fiber
    count, every file's box holding its rows' bounds. Returns a dict with 'ok' and the problems."""
    _, pq = _pa()
    np = _np()
    out_dir = Path(out_dir)
    idx = json.loads((out_dir / INDEX).read_text())
    problems = []
    ids = []
    for e in idx["files"]:
        p = out_dir / e["path"]
        data = p.read_bytes()
        if len(data) != e["bytes"] or hashlib.sha256(data).hexdigest() != e["sha256"]:
            problems.append(f"{e['path']}: size or sha256 differs from the index")
            continue
        t = pq.read_table(str(p), columns=["id"] + list(BOUND_COLUMNS))
        ids.append(t.column("id").to_numpy())
        if t.num_rows != e["rows"]:
            problems.append(f"{e['path']}: {t.num_rows} rows, the index says {e['rows']}")
        b = {n: t.column(n).to_numpy() for n in BOUND_COLUMNS}
        bx = e["box_zyx"]
        if t.num_rows and (b["bmin_z"].min() < bx[0] or b["bmax_z"].max() > bx[1] or b["bmin_y"].min() < bx[2]
                           or b["bmax_y"].max() > bx[3] or b["bmin_x"].min() < bx[4] or b["bmax_x"].max() > bx[5]):
            problems.append(f"{e['path']}: its rows reach outside its box in the index")
    allids = np.sort(np.concatenate(ids)) if ids else np.zeros(0, np.int64)
    dup = int((allids[1:] == allids[:-1]).sum()) if len(allids) else 0
    if dup:
        problems.append(f"{dup} fiber ids appear in more than one row")
    if len(allids) != idx["source"]["fiber_count"]:
        problems.append(f"{len(allids)} rows for {idx['source']['fiber_count']} fibers")
    if afv is not None:
        db = _connect(afv)
        try:
            src = np.array([r[0] for r in db.execute("SELECT id FROM fibers ORDER BY id")], np.int64)
        finally:
            db.close()
        if not np.array_equal(src, allids):
            problems.append("the shards' ids are not the source's ids")
    return {"ok": not problems, "problems": problems, "rows": int(len(allids)), "files": len(idx["files"])}


# ------------------------------------------------------------------------------------------------------------ CLI

def _summary(fibers, extra):
    fam = {"H": 0, "V": 0}
    for f in fibers:
        fam[f.family] = fam.get(f.family, 0) + 1
    d = {"fibers": len(fibers), **fam, "points": sum(f.row[3] for f in fibers),
         "digest": records_digest(fibers)[0]}
    d.update(extra)
    return d


def _outputs(fibers, a, source, box, d):
    if a.out:
        write_afv(fibers, a.out, source, box=box, family=a.family, min_len=a.min_len)
        d["out"] = str(a.out)
        d["out_sha256"] = hashlib.sha256(Path(a.out).read_bytes()).hexdigest()
    if a.json:
        Path(a.json).write_text(json.dumps([{"id": f.id, "family": f.family, "length_mm": f.length_mm,
                                             "points_xyz": f.points.tolist()} for f in fibers]) + "\n")
        d["json"] = str(a.json)


def _add_selection(p):
    p.add_argument("--box", nargs=6, required=True, metavar=("Z0", "Z1", "Y0", "Y1", "X0", "X1"),
                   help="the box in level-0 voxels, lows inclusive and highs exclusive")
    p.add_argument("--family", choices=("H", "V"), help="only horizontal (H) or vertical (V) fibers")
    p.add_argument("--min-len", type=float, metavar="MM", help="only fibers at least this long, in mm")
    p.add_argument("--out", type=Path, metavar="BOX.afv", help="write the fibers as an .afv that VC3D's importer opens")
    p.add_argument("--json", type=Path, metavar="FIBERS.json", help="write the fibers as JSON: id, family, length, points")


def _add_where(p):
    p.add_argument("--scan", help="a scan with a public dataset (python -m kit fibers scans)")
    p.add_argument("--repo", help="any dataset with stream shards, OWNER/NAME (instead of --scan)")
    p.add_argument("--revision", default="main", help="the dataset's branch, tag, commit or refs/pr/N")
    p.add_argument("--source", type=Path, metavar="DIR", help="a local folder with stream/ (instead of Hugging Face)")
    p.add_argument("--threads", type=int, default=8, help="parallel range requests")


def add_arguments(p):
    sub = p.add_subparsers(dest="action", required=True, metavar="{scans,stream,filter,parity,build}")
    sub.add_parser("scans", help="the datasets with stream shards")
    s = sub.add_parser("stream", help="the fibers in a box, read from the stream shards without a full download")
    _add_selection(s)
    _add_where(s)
    s = sub.add_parser("filter", help="the same box from a downloaded .afv (the reference the stream equals)")
    s.add_argument("afv", type=Path, help="a whole-scan .afv")
    _add_selection(s)
    s = sub.add_parser("parity", help="stream a box and filter the downloaded .afv; exit 0 when they are the same")
    s.add_argument("afv", type=Path, help="the whole-scan .afv the shards were built from")
    _add_selection(s)
    _add_where(s)
    s = sub.add_parser("build", help="write the stream shards and stream/index.json for a whole-scan .afv")
    s.add_argument("afv", type=Path, help="a whole-scan .afv")
    s.add_argument("out_dir", type=Path, help="the folder to write stream/ in (the dataset's root)")
    s.add_argument("--level", type=int, default=0, help="the CT level the fibers were traced on (grid voxel = 2**level)")
    s.add_argument("--scan", help="the scan id written into the index")
    s.add_argument("--workers", type=int, default=0, help="worker processes (0: one per CPU)")
    s.add_argument("--no-sha256", action="store_true", help="skip the source file's sha256 in the index")


def run(a):
    try:
        if a.action == "scans":
            for scan, s in SCANS.items():
                print(f"{scan}\t{s['repo']}\tlevel {s['level']}")
            return 0
        if a.action == "build":
            idx = build(a.afv, a.out_dir, level=a.level, scan=a.scan, workers=a.workers or None,
                        sha256=not a.no_sha256, say=lambda m: print(m, file=sys.stderr))
            v = verify_build(a.out_dir, a.afv)
            print(json.dumps({"totals": idx["totals"], "verify": v}))
            return 0 if v["ok"] else 1
        box = parse_box(a.box)
        if a.action == "filter":
            t0 = time.perf_counter()
            fibers = list(read_afv(a.afv, box, a.family, a.min_len))
            d = _summary(fibers, {"box_zyx": box, "source": str(a.afv), "seconds": round(time.perf_counter() - t0, 3)})
            _outputs(fibers, a, afv_source_info(a.afv), box, d)
            print(json.dumps(d))
            return 0
        if a.action == "stream":
            fibers, st, source = stream(box, scan=a.scan, repo=a.repo, revision=a.revision, local=a.source,
                                        family=a.family, min_len=a.min_len, threads=a.threads)
            d = _summary(fibers, {"box_zyx": box, **st})
            _outputs(fibers, a, source, box, d)
            print(json.dumps(d))
            return 0
        if a.action == "parity":
            fibers, st, source = stream(box, scan=a.scan, repo=a.repo, revision=a.revision, local=a.source,
                                        family=a.family, min_len=a.min_len, threads=a.threads)
            ref = list(read_afv(a.afv, box, a.family, a.min_len))
            same_records = records_digest(fibers) == records_digest(ref)
            d = {"box_zyx": box, "stream": records_digest(fibers), "reference": records_digest(ref),
                 "records_equal": same_records, "bytes": st["bytes"], "requests": st["requests"]}
            if a.out:
                ref_src = afv_source_info(a.afv)
                write_afv(fibers, a.out, source, box=box, family=a.family, min_len=a.min_len)
                ref_out = Path(str(a.out) + ".reference.afv")
                write_afv(ref, ref_out, ref_src, box=box, family=a.family, min_len=a.min_len)
                d["afv_equal"] = Path(a.out).read_bytes() == ref_out.read_bytes()
            ok = same_records and d.get("afv_equal", True)
            d["verdict"] = "PASS" if ok else "FAIL"
            print(json.dumps(d))
            return 0 if ok else 1
    except FiberStreamError as exc:
        print(f"fibers: {exc}", file=sys.stderr)
        return 2
    return 2


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit.fiberstream", description=__doc__.split("\n\n")[0])
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
