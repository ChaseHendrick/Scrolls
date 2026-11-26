"""Segment Atlas: the same geometry numbers for every traced segment on the open-data bucket.

`kit tifxyz` measures one segment. The atlas runs those measures over every tifxyz mesh the bucket publishes
(SCROLL/segments/SEGMENT/mesh/..., one folder per volume a segment was mapped to) and keeps one row per mesh:
area in cm2, grid size and filled share, how isometric the grid is (edge length over the promised step, grid angle),
holes inside the sheet, folds and over-stretched nodes, with the voxel size and the prize lists its scroll is on.

  build   list the bucket, measure every mesh (or --scroll ones), write atlas.jsonl, atlas.csv and summary.json to
          OUT; --previous ATLAS reuses rows whose x, y and z files have not changed (same ETag and size), so a
          daily refresh measures only new or changed meshes. --lens also writes a small preview grid per mesh of
          a scroll on no prize list, for the Segment Lens viewer (spaces/segment-lens/)
  show    print the atlas (the published one by default) for one scroll or all, sorted by a column

Numbers describe the grid, not the papyrus: a clean mesh can still jump between sheets, and nothing here looks at
the CT or judges ink. Very large meshes are measured in bands of rows, so percentiles come from a regular sample of
up to SAMPLE_CAP values (holes are always found on the full grid). Needs numpy and tifffile, like kit tifxyz.
"""

import argparse
import concurrent.futures
import csv
import datetime
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

from . import find as _find
from . import tifxyz
from .verify import VerifyError

DATASET = "SharpMeow/vesuvius-segment-atlas"
ATLAS_URL = f"{_find.HUB}/datasets/{DATASET}/resolve/main/atlas.jsonl"
SCHEMA = "segment-atlas/1"
BAND_ROWS = 1024              # rows per band for large meshes
BAND_NODES = 12_000_000       # meshes with more nodes than this are measured in bands
SAMPLE_CAP = 2_000_000        # values kept per distribution for the percentiles
LENS_SIDE = 256               # longest side of a Segment Lens preview grid
LENS_MAGIC = b"SLG1"
TIFF_LIMIT = "1000000000"     # KIT_MAX_TIFF_ELEMENTS for the atlas: the largest published mesh has about 116 million
_UM = re.compile(r"-(\d+(?:\.\d+)?)um\.tifxyz$")
_VOL = re.compile(r"-on-(\d{14})-")
COLUMNS = ("id", "scroll", "segment", "mesh", "kind", "volume", "voxel_um", "voxel_um_from", "prize_lists",
           "grid_h", "grid_w", "nodes_filled", "filled_share", "area_cm2", "meta_area_ratio",
           "edge_p5", "edge_p50", "edge_p95", "within_10pct", "within_25pct", "median_abs_log",
           "cell_area_p50", "angle_p5", "angle_p50", "angle_p95",
           "holes_nodes", "holes_mm2", "folds_nodes", "folds_mm2", "stretched_nodes", "stretched_mm2", "clean",
           "z_min", "z_max", "bytes", "banded", "lens", "seconds", "error", "url", "fingerprint", "last_modified",
           "measured_at", "x_min", "x_max", "y_min", "y_max", "extent_x_mm", "extent_y_mm", "extent_z_mm")
# Columns added after the first release go at the end, so code that reads the CSV by position keeps working. A row
# measured before a column in NEWER existed is measured again on the next refresh (once), so every row has it.
NEWER = ("x_min", "extent_x_mm")


# ---------------------------------------------------------------- listing

def list_keys(prefix, get=_find.http_get):
    """(sub-folders, [{"key", "size", "etag", "modified"}]) directly under a bucket prefix."""
    folders, keys, token = [], [], None
    while True:
        q = {"list-type": "2", "delimiter": "/", "prefix": prefix}
        if token:
            q["continuation-token"] = token
        x = get(f"{_find.BUCKET}/?{urllib.parse.urlencode(q)}").decode("utf-8")
        folders += [p for p in re.findall(r"<Prefix>(.*?)</Prefix>", x) if p != prefix]
        for c in re.findall(r"<Contents>(.*?)</Contents>", x, re.S):
            k = re.search(r"<Key>(.*?)</Key>", c)
            s = re.search(r"<Size>(\d+)</Size>", c)
            e = re.search(r"<ETag>(.*?)</ETag>", c)
            m = re.search(r"<LastModified>(.*?)</LastModified>", c)
            if k and s:
                keys.append({"key": k.group(1), "size": int(s.group(1)),
                             "etag": (e.group(1) if e else "").replace("&quot;", "").strip('"'),
                             "modified": m.group(1) if m else None})
        m = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", x)
        if not m:
            return folders, keys
        token = m.group(1)


def _mesh_folders(prefix, get, depth=3):
    """Every folder under prefix (depth levels down) that holds x.tif, y.tif and z.tif: [(folder, {name: key})]."""
    folders, keys = list_keys(prefix, get)
    files = {k["key"][len(prefix):]: k for k in keys}
    out = []
    if all(f in files for f in ("x.tif", "y.tif", "z.tif")):
        out.append((prefix, files))
    if depth > 0:
        for f in folders:
            out += _mesh_folders(f, get, depth - 1)
    return out


def prize_lists():
    """{normalized scroll or volume id: [prize ids]} from kit's newest prize snapshot (kit/data/prizes-*.json)."""
    snaps = sorted((Path(__file__).parent / "data").glob("prizes-*.json"))
    if not snaps:
        raise VerifyError("no prize snapshot (kit/data/prizes-*.json): the atlas needs it to mark prize-eligible "
                          "scrolls and to keep Segment Lens previews to the others")
    snap = json.loads(snaps[-1].read_text(encoding="utf-8"))
    table = {}
    for prize in snap.get("prizes", []):
        for entry in prize.get("eligible") or []:
            for key in (entry.get("scroll"), entry.get("volume")):
                if key and key != "any":
                    table.setdefault(norm_scroll(key), set()).add(prize["id"])
    return {k: sorted(v) for k, v in table.items()}


def norm_scroll(name):
    """'PHerc. 139', 'pherc0139', 'PHerc0175A', 'PHercParis4' to one spelling each (PHERC0139, PHERCPARIS4)."""
    text = re.sub(r"[\s._-]", "", str(name)).upper()
    m = re.fullmatch(r"PHERC(PARIS)?0*(\d+)([A-Z0-9]*)", text)
    if not m:
        return text
    return f"PHERCPARIS{int(m.group(2))}{m.group(3)}" if m.group(1) else f"PHERC{int(m.group(2)):04d}{m.group(3)}"


def lists_for(scroll, volume, table):
    """The prize lists a scroll (or one of its volumes) is on. A part letter or suffix on the scroll id
    (PHerc0343P, PHerc0175A) is matched with and without it, so a listed scroll is never missed."""
    key = norm_scroll(scroll)
    hits = set(table.get(key, [])) | set(table.get(str(volume), []) if volume else [])
    base = re.match(r"(PHERC(?:PARIS)?\d+)", key)
    if base:
        for other, prizes in table.items():
            if other == base.group(1) or (other.startswith(base.group(1)) and not other[len(base.group(1)):][:1].isdigit()):
                hits |= set(prizes)
    return sorted(hits)


def survey(scrolls=None, get=_find.http_get, workers=16):
    """Every mesh on the bucket: [{"id", "scroll", "segment", "mesh", "url", "files", "volume", ...}] sorted by id."""
    meta = _find.get_json(_find.METADATA, get)
    samples = meta.get("samples") or {}
    names = sorted(samples) if not scrolls else [_find.sample(meta, s)[0] for s in scrolls]
    table = prize_lists()
    segs = []
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        for s, (sub, _) in zip(names, ex.map(lambda s: list_keys(f"{s}/segments/", get), names)):
            segs += [(s, p) for p in sub]
    rows = []
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        found = ex.map(lambda sp: _mesh_folders(sp[1] + "mesh/", get), segs)
        for (scroll, seg_prefix), meshes in zip(segs, found):
            segment = seg_prefix.rstrip("/").rsplit("/", 1)[-1]
            for folder, files in meshes:
                rel = folder[len(seg_prefix) + len("mesh/"):].rstrip("/")
                rows.append(_mesh_row(scroll, segment, rel, folder, files, samples.get(scroll) or {}, table))
    return sorted(rows, key=lambda r: r["id"])


def _mesh_row(scroll, segment, rel, folder, files, sample, table):
    xyz = [files[f] for f in ("x.tif", "y.tif", "z.tif")]
    name = rel.rsplit("/", 1)[-1]
    um, src = None, None
    m = _UM.search(name)
    if m:
        um, src = float(m.group(1)), "folder name"
    vol = _VOL.search(name)
    volume = vol.group(1) if vol else None
    vols = sample.get("volumes") or {}
    if um is None and volume and volume in vols:
        um = (vols[volume].get("properties") or {}).get("pixel_size_um")
        src = "volume metadata" if um else None
    if um is None and volume is None and len(vols) == 1:
        only = next(iter(vols.values()))
        um = (only.get("properties") or {}).get("pixel_size_um")
        volume = only.get("id") if um else None
        src = "the scroll's only volume" if um else None
    fp = hashlib.sha256("|".join(f"{k['etag']}:{k['size']}" for k in xyz).encode()).hexdigest()[:16]
    return {"id": f"{scroll}/{segment}/{rel}", "scroll": scroll, "segment": segment, "mesh": rel,
            "kind": "mesh" if "/" not in rel else rel.split("/", 1)[0],
            "url": f"{_find.BUCKET}/{folder.rstrip('/')}", "volume": volume, "voxel_um": um, "voxel_um_from": src,
            "prize_lists": lists_for(scroll, volume, table), "bytes": sum(k["size"] for k in xyz),
            "fingerprint": fp, "last_modified": max((k["modified"] or "") for k in xyz) or None}


# ---------------------------------------------------------------- measuring

class _Sample:
    """A regular sample of values for percentiles: every k-th value, k chosen from the expected count."""

    def __init__(self, expected, cap=SAMPLE_CAP):
        self.k = max(1, int(math.ceil(expected / cap)))
        self.parts = []

    def add(self, a):
        np = tifxyz._np()
        a = np.asarray(a, float).ravel()
        a = a[np.isfinite(a)]
        if a.size:
            self.parts.append(a[::self.k].copy())

    def values(self):
        np = tifxyz._np()
        return np.concatenate(self.parts) if self.parts else np.zeros(0)


def masks(seg, band_rows=BAND_ROWS):
    """tifxyz.check's flag masks for a mesh of any size: holes on the full grid, folds and stretched nodes band by
    band, each band read with one row of its neighbors on both sides so the flags at its edges are exact."""
    np = seg._np
    H, W = seg.shape
    folds = np.zeros((H, W), bool)
    bad = np.zeros((H, W), bool)
    for r0 in range(0, H, band_rows):
        r1 = min(H, r0 + band_rows)
        lo, hi = max(0, r0 - 1), min(H, r1 + 1)
        part = tifxyz.Segment(seg.xyz[lo:hi], seg.valid[lo:hi], seg.meta, seg.source, seg.voxel_um)
        _, m = tifxyz.check(part)
        folds[r0:r1] = m["folds"][r0 - lo:r1 - lo]
        bad[r0:r1] = m["stretched"][r0 - lo:r1 - lo]
    return {"holes": tifxyz._holes(seg.valid), "folds": folds, "stretched": bad}


def measure(seg, band_rows=BAND_ROWS, band_nodes=BAND_NODES):
    """(info, stretch and check numbers of a Segment as one flat dict, the flag masks). Meshes over band_nodes
    nodes are measured in bands of band_rows rows; each cell and edge is counted in exactly one band."""
    np = seg._np
    H, W = seg.shape
    banded = H * W > band_nodes
    step = band_rows if banded else H
    edges, cells, angles = (_Sample(2 * H * W), _Sample(H * W), _Sample(H * W))
    area = 0.0
    for r0 in range(0, H, step):
        r1 = min(H, r0 + step)
        hi = min(H, r1 + 1)               # one extra row so cells and row edges across the band boundary count once
        part = tifxyz.Segment(seg.xyz[r0:hi], seg.valid[r0:hi], seg.meta, seg.source, seg.voxel_um)
        c, a, _ = tifxyz._cells(part)
        own = slice(0, r1 - r0)           # cell, edge and angle rows r0..r1-1 belong to this band
        area += float(a[own][c[own]].sum())
        ec, er = tifxyz._edges(part)
        edges.add(ec[own])
        edges.add(er[own])
        cells.add((a / (seg.step[0] * seg.step[1]))[own][c[own]])
        P = part.xyz
        with np.errstate(invalid="ignore", divide="ignore"):
            u = P[:-1, 1:] - P[:-1, :-1]
            w = P[1:, :-1] - P[:-1, :-1]
            cos = (u * w).sum(-1) / (np.linalg.norm(u, axis=-1) * np.linalg.norm(w, axis=-1))
            angles.add(np.degrees(np.arccos(np.clip(cos, -1, 1)))[own][c[own]])
        del part, c, a, ec, er, P, u, w, cos
    m = masks(seg, band_rows)
    holes, folds, stretched = (int(m[k].sum()) for k in ("holes", "folds", "stretched"))
    e = edges.values()
    with np.errstate(divide="ignore"):
        logs = np.abs(np.log(e[e > 0]))

    def pct(a, p, n=3):
        return None if not a.size else round(float(np.percentile(a, p)), n)

    um = seg.voxel_um
    cell_um2 = None if um is None else seg.step[0] * seg.step[1] * um ** 2
    mm2 = (lambda k: None if cell_um2 is None else round(k * cell_um2 * 1e-6, 2))
    filled = int(seg.valid.sum())
    out = {"grid_h": H, "grid_w": W, "nodes_filled": filled, "filled_share": round(filled / max(1, H * W), 4),
           "area_cm2": None if um is None else round(area * (um * 1e-4) ** 2, 3),
           "edge_p5": pct(e, 5), "edge_p50": pct(e, 50), "edge_p95": pct(e, 95),
           "within_10pct": None if not e.size else round(float(((e > 1 / 1.1) & (e < 1.1)).mean()), 4),
           "within_25pct": None if not e.size else round(float(((e > 1 / 1.25) & (e < 1.25)).mean()), 4),
           "median_abs_log": None if not logs.size else round(float(np.median(logs)), 4),
           "cell_area_p50": pct(cells.values(), 50), "angle_p5": pct(angles.values(), 5, 1),
           "angle_p50": pct(angles.values(), 50, 1), "angle_p95": pct(angles.values(), 95, 1),
           "holes_nodes": holes, "holes_mm2": mm2(holes), "folds_nodes": folds, "folds_mm2": mm2(folds),
           "stretched_nodes": stretched, "stretched_mm2": mm2(stretched),
           "clean": holes == 0 and folds == 0 and stretched == 0, "banded": banded}
    meta_area = seg.meta.get("area_vx2")
    out["meta_area_ratio"] = (round(area / float(meta_area), 4)
                              if isinstance(meta_area, (int, float)) and meta_area > 0 else None)
    out.update({k: None for k in ("x_min", "x_max", "y_min", "y_max", "extent_x_mm", "extent_y_mm", "extent_z_mm")})
    if filled:
        for i, axis in enumerate("xyz"):
            v = seg.xyz[..., i][seg.valid]
            lo, hi = float(v.min()), float(v.max())
            out[f"{axis}_min"], out[f"{axis}_max"] = round(lo, 1), round(hi, 1)
            if um is not None:     # the bounding box of the filled nodes, in mm of the scan
                out[f"extent_{axis}_mm"] = round((hi - lo) * um * 1e-3, 2)
    return out, m


def lens_grid(seg, flags_masks, side=LENS_SIDE):
    """A small preview grid for Segment Lens, as gzip'd bytes (format under "Lens files" in docs/tools/atlas.md):
    every k-th row and column, k so the longest side is at most `side`; positions quantized to 16 bits inside the
    bounding box of the kept nodes (65535 marks a missing node); and a flag byte per kept node, the OR over the
    k x k block it stands for: 1 hole, 2 fold, 4 stretched."""
    np = seg._np
    H, W = seg.shape
    k = max(1, int(math.ceil(max(H, W) / side)))
    flags = np.zeros((H, W), np.uint8)
    flags[flags_masks["holes"]] |= 1
    flags[flags_masks["folds"]] |= 2
    flags[flags_masks["stretched"]] |= 4
    h, w = -(-H // k), -(-W // k)
    pad = np.zeros((h * k, w * k), np.uint8)
    pad[:H, :W] = flags
    pooled = np.bitwise_or.reduce(np.bitwise_or.reduce(pad.reshape(h, k, w, k), axis=3), axis=1)
    sub = seg.xyz[::k, ::k].astype(np.float64)
    ok = seg.valid[::k, ::k]
    pts = sub[ok]
    lo = pts.min(0) if pts.size else np.zeros(3)
    hi = pts.max(0) if pts.size else np.ones(3)
    span = np.where(hi - lo > 0, hi - lo, 1.0)
    q = np.clip(np.round((sub - lo) / span * 65534), 0, 65534).astype("<u2")
    q[~ok] = 65535
    head = LENS_MAGIC + struct.pack("<HHH", h, w, k) + struct.pack("<6f", *lo, *hi)
    raw = head + b"".join(np.ascontiguousarray(q[..., i]).tobytes() for i in range(3)) + pooled.astype(np.uint8).tobytes()
    return gzip.compress(raw, 6, mtime=0)


def read_lens(blob):
    """(h, w, k, lo, hi, xyz (h, w, 3) float64 with NaN for missing nodes, flags (h, w) uint8) from lens bytes."""
    np = tifxyz._np()
    raw = gzip.decompress(blob)
    if raw[:4] != LENS_MAGIC:
        raise VerifyError("not a Segment Lens grid (bad magic)")
    h, w, k = struct.unpack("<HHH", raw[4:10])
    v = struct.unpack("<6f", raw[10:34])
    lo, hi = np.array(v[:3]), np.array(v[3:])
    n = h * w
    q = np.frombuffer(raw, "<u2", 3 * n, 34).reshape(3, h, w)
    flags = np.frombuffer(raw, np.uint8, n, 34 + 6 * n).reshape(h, w)
    span = np.where(hi - lo > 0, hi - lo, 1.0)
    xyz = np.stack([lo[i] + q[i] / 65534.0 * span[i] for i in range(3)], -1)
    xyz[q[0] == 65535] = np.nan
    return h, w, k, lo, hi, xyz, flags


def load32(src, cache, voxel_um=None):
    """tifxyz.load, but positions kept as float32: half the memory, enough for these numbers on the largest
    published meshes (about 116 million nodes)."""
    from . import meshaudit, stackcheck
    np = tifxyz._np()
    folder = stackcheck.fetch_tifxyz(src, cache) if stackcheck._is_url(src) else Path(src)
    try:
        arrs = [meshaudit.imread_capped(str(folder / f"{c}.tif")).astype(np.float32, copy=False) for c in "xyz"]
    except Exception as exc:  # missing file or unreadable TIFF
        raise VerifyError(f"cannot read the tifxyz folder {src}: {exc}") from exc
    if any(a.ndim != 2 or a.shape != arrs[0].shape for a in arrs):
        raise VerifyError(f"{src}: x.tif, y.tif and z.tif must be 2D grids of one shape")
    xyz = np.stack(arrs, -1)
    del arrs
    valid = np.isfinite(xyz).all(-1) & (xyz > -0.5).all(-1) & (np.abs(xyz).sum(-1) > 0)
    meta = {}
    if (Path(folder) / "meta.json").is_file():
        try:
            meta = json.loads((Path(folder) / "meta.json").read_text())
        except (OSError, ValueError):
            meta = {}
    return tifxyz.Segment(xyz, valid, meta, src, voxel_um)


def lens_name(row):
    return hashlib.sha256(row["id"].encode()).hexdigest()[:16] + ".slg.gz"


def measure_row(row, lens_dir=None, workdir=None):
    """Fetch one mesh into a temporary folder, measure it, delete the copy: the row with its numbers (or error)."""
    os.environ.setdefault("KIT_MAX_TIFF_ELEMENTS", TIFF_LIMIT)
    t0 = time.time()
    out = dict(row)
    tmp = tempfile.mkdtemp(prefix="atlas-", dir=workdir)
    try:
        seg = load32(row["url"], tmp, row.get("voxel_um"))
        seg.volume = seg.volume or row.get("volume")
        nums, m = measure(seg)
        out.update(nums)
        if lens_dir and not row.get("prize_lists"):
            blob = lens_grid(seg, m)
            Path(lens_dir).mkdir(parents=True, exist_ok=True)
            (Path(lens_dir) / lens_name(row)).write_bytes(blob)
            out["lens"] = lens_name(row)
        out["error"] = None
    except (VerifyError, OSError, ValueError, MemoryError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out["seconds"] = round(time.time() - t0, 2)
    out["measured_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


# ---------------------------------------------------------------- build and files

def read_atlas(src, get=_find.http_get):
    """Rows of an atlas.jsonl, local path or URL."""
    if "://" in str(src):
        text = get(str(src)).decode("utf-8")
    else:
        text = Path(src).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).parent, timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def build(out_dir, scrolls=None, previous=None, workers=None, lens=False, limit=None, get=_find.http_get,
          progress=print, measure_fn=measure_row, workdir=None):
    """List the bucket, measure what is new or changed, write the atlas files. Returns the summary dict."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = survey(scrolls, get)
    if limit:
        rows = rows[:limit]
    old = {}
    if previous:
        try:
            old = {r["id"]: r for r in read_atlas(previous, get)}
        except (OSError, ValueError) as exc:
            progress(f"previous atlas not read ({exc}); measuring everything")
    lens_dir = out / "lens" if lens else None
    done, todo = [], []
    for r in rows:
        prev = old.get(r["id"])
        keep = prev and prev.get("fingerprint") == r["fingerprint"] and not prev.get("error")
        if keep and not all(k in prev for k in NEWER):
            keep = False                  # measured before a newer column existed: measure again to fill it
        if keep and lens and not r["prize_lists"] and not prev.get("lens"):
            keep = False                  # measured before without a preview: measure again to make one
        if keep and lens and prev.get("lens") and not (lens_dir / prev["lens"]).is_file():
            keep = False                  # its preview file is not in OUT: make it again
        (done if keep else todo).append({**prev, **{k: r[k] for k in ("prize_lists", "url")}} if keep else r)
    progress(f"{len(rows)} meshes on the bucket; {len(done)} unchanged, {len(todo)} to measure")
    workers = workers or max(1, min(4, os.cpu_count() or 1))
    order = sorted(todo, key=lambda r: -r["bytes"])     # big first, so one large mesh does not finish last
    def note(i, res):
        done.append(res)
        progress(f"PROGRESS {i}/{len(order)} {res['id']} {res.get('seconds', '?')} s"
                 + (f" ERROR {res['error']}" if res.get("error") else ""))

    if workers == 1:
        for i, r in enumerate(order, 1):
            note(i, measure_fn(r, lens_dir, workdir))
    else:
        with concurrent.futures.ProcessPoolExecutor(workers) as ex:
            futs = {ex.submit(measure_fn, r, lens_dir, workdir): r for r in order}
            for i, f in enumerate(concurrent.futures.as_completed(futs), 1):
                try:
                    res = f.result()
                except Exception as exc:  # a worker that died (out of memory) is one failed row, not a failed build
                    res = {**futs[f], "error": f"{type(exc).__name__}: {exc}"[:300]}
                note(i, res)
    done.sort(key=lambda r: r["id"])
    return write(out, done)


SEGMENT_COLUMNS = ("scroll", "segment", "meshes", "volumes", "best_mesh", "volume", "voxel_um", "area_cm2",
                   "filled_share", "within_10pct", "median_abs_log", "holes_mm2", "folds_mm2", "stretched_mm2", "clean",
                   "extent_x_mm", "extent_y_mm", "extent_z_mm", "z_min", "z_max", "prize_lists", "lens", "url")
SCROLL_COLUMNS = ("scroll", "segments", "meshes", "measured", "errors", "clean_meshes", "clean_segments", "area_cm2",
                  "largest_segment_cm2", "median_segment_cm2", "median_within_10pct", "voxel_sizes_um", "prize_lists")
FIRST_RELEASE = "2026-10-24"
CHANGELOG = (
    ("2026-11-26", "Segment and scroll tables (`segments.csv`, `scrolls.csv`, configs `segments` and `scrolls`); "
                   "bounding box and physical extent columns on every mesh (`x_min` to `extent_z_mm`, added at the "
                   "end so column positions do not move); figures in `assets/`; a fuller card. Every existing "
                   "file, path and column is unchanged."),
    (FIRST_RELEASE, "First release: one row per tifxyz mesh on the open-data bucket, Segment Lens previews, daily "
                    "refresh."),
)
RELATED = (
    ("SharpMeow/first-letters-ink-atlas", "dataset", "public ink models run on the same public First Letters "
                                                     "surfaces, on one shared canvas"),
    ("SharpMeow/vesuvius-snapped-labels", "dataset", "published ink labels snapped onto public traced surfaces"),
    ("SharpMeow/segment-lens", "space", "browse this atlas in 3D in the browser: every mesh's preview grid "
                                        "with its holes, folds and stretched nodes"),
)
# (type, unit, meaning) for every column of atlas.csv; a test requires one entry per column
COLUMN_DOCS = {
    "id": ("string", "", "SCROLL/SEGMENT/MESH, unique per row"),
    "scroll": ("string", "", "scroll id as the bucket spells it, such as PHerc0139"),
    "segment": ("string", "", "segment folder name on the bucket"),
    "mesh": ("string", "", "mesh folder under the segment's `mesh/`, such as `SEG-on-VOLUME-2.399um.tifxyz`"),
    "kind": ("string", "", "`mesh` for a top-level mesh folder, else the subfolder name (such as `intermediate`)"),
    "volume": ("number", "", "id of the scan volume the mesh is mapped to (a 14-digit timestamp), when known"),
    "voxel_um": ("number", "um", "voxel size of that volume"),
    "voxel_um_from": ("string", "", "where the voxel size came from: `folder name`, `volume metadata` or "
                                   "`the scroll's only volume`"),
    "prize_lists": ("string", "", "prize lists the scroll is on in kit's dated snapshot; `[]` when none, else ids "
                                 "joined by `;`"),
    "grid_h": ("integer", "nodes", "grid rows"),
    "grid_w": ("integer", "nodes", "grid columns"),
    "nodes_filled": ("integer", "nodes", "grid nodes with a position"),
    "filled_share": ("number", "0 to 1", "nodes_filled over grid_h times grid_w"),
    "area_cm2": ("number", "cm2", "surface area: two triangles per complete grid cell, times the voxel size squared"),
    "meta_area_ratio": ("number", "ratio", "area_cm2 over the `area_vx2` VC3D wrote into `meta.json`, where there "
                                          "is one"),
    "edge_p5": ("number", "ratio", "5th percentile of grid edge length over the step `meta.json` promises (1.0 is "
                                   "exact)"),
    "edge_p50": ("number", "ratio", "median of the same"),
    "edge_p95": ("number", "ratio", "95th percentile of the same"),
    "within_10pct": ("number", "0 to 1", "share of edges within 10 % of the promised step"),
    "within_25pct": ("number", "0 to 1", "share of edges within 25 % of the promised step"),
    "median_abs_log": ("number", "", "median of the absolute log of edge length over step (0 is exact)"),
    "cell_area_p50": ("number", "ratio", "median cell area over the promised cell area"),
    "angle_p5": ("number", "degrees", "5th percentile of the angle between the two grid directions (90 is square)"),
    "angle_p50": ("number", "degrees", "median of the same"),
    "angle_p95": ("number", "degrees", "95th percentile of the same"),
    "holes_nodes": ("integer", "nodes", "missing nodes not joined to the grid's border through missing nodes"),
    "holes_mm2": ("number", "mm2", "the same as an area"),
    "folds_nodes": ("integer", "nodes", "nodes of neighboring cells whose normals turn by more than 90 degrees"),
    "folds_mm2": ("number", "mm2", "the same as an area"),
    "stretched_nodes": ("integer", "nodes", "nodes on an edge more than 1.5 times too long or too short"),
    "stretched_mm2": ("number", "mm2", "the same as an area"),
    "clean": ("boolean", "", "true when holes, folds and stretched nodes are all 0"),
    "z_min": ("number", "voxels", "lowest z of the filled nodes, in the volume's voxels"),
    "z_max": ("number", "voxels", "highest z of the filled nodes"),
    "bytes": ("integer", "bytes", "size of x.tif, y.tif and z.tif together"),
    "banded": ("boolean", "", "true when the mesh was measured in bands of 1,024 rows (over 12 million nodes)"),
    "lens": ("string", "", "preview file in `lens/`, for scrolls on no prize list; empty otherwise"),
    "seconds": ("number", "s", "time to fetch and measure the mesh"),
    "error": ("string", "", "why the mesh was not measured; empty when it was"),
    "url": ("string", "", "the mesh folder on the open-data bucket"),
    "fingerprint": ("string", "", "hash of the ETags and sizes of x.tif, y.tif and z.tif"),
    "last_modified": ("string", "UTC", "newest Last-Modified of the three files on the bucket"),
    "measured_at": ("string", "UTC", "when this row was measured"),
    "x_min": ("number", "voxels", "lowest x of the filled nodes"),
    "x_max": ("number", "voxels", "highest x of the filled nodes"),
    "y_min": ("number", "voxels", "lowest y of the filled nodes"),
    "y_max": ("number", "voxels", "highest y of the filled nodes"),
    "extent_x_mm": ("number", "mm", "(x_max minus x_min) times the voxel size: the width of the mesh's bounding "
                                    "box in the scan"),
    "extent_y_mm": ("number", "mm", "the same along y"),
    "extent_z_mm": ("number", "mm", "the same along z (the scroll's long axis on most scans)"),
}


def _prize_text(v):
    return ";".join(v) if isinstance(v, (list, tuple)) else (v or "")


def _median(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def _best(rows):
    """The row that stands for a segment: its finest-voxel measured top-level mesh (as the per-scroll area), else
    any measured top-level mesh, else None."""
    top = [r for r in rows if r.get("kind") == "mesh" and r.get("grid_h") is not None and not r.get("error")]
    with_area = [r for r in top if r.get("area_cm2") is not None]
    pool = with_area or top
    return min(pool, key=lambda r: (r.get("voxel_um") or 99, r["id"])) if pool else None


def segment_rows(rows):
    """One row per segment (SEGMENT_COLUMNS), its numbers from the mesh _best picks."""
    by = {}
    for r in rows:
        by.setdefault((r["scroll"], r["segment"]), []).append(r)
    out = []
    for (scroll, segment), rs in sorted(by.items()):
        b = _best(rs) or {}
        row = {"scroll": scroll, "segment": segment, "meshes": len(rs),
               "volumes": len({r.get("volume") for r in rs if r.get("volume")}), "best_mesh": b.get("id"),
               "prize_lists": _prize_text(rs[0].get("prize_lists"))}
        for c in ("volume", "voxel_um", "area_cm2", "filled_share", "within_10pct", "median_abs_log", "holes_mm2",
                  "folds_mm2", "stretched_mm2", "clean", "extent_x_mm", "extent_y_mm", "extent_z_mm", "z_min",
                  "z_max", "lens", "url"):
            row[c] = b.get(c)
        out.append(row)
    return out


def scroll_rows(rows, segs=None):
    """One row per scroll (SCROLL_COLUMNS)."""
    segs = segment_rows(rows) if segs is None else segs
    summary = summarize(rows)["scrolls"]
    out = []
    for scroll, s in sorted(summary.items()):
        mine = [g for g in segs if g["scroll"] == scroll]
        areas = [g["area_cm2"] for g in mine if g.get("area_cm2") is not None]
        top = [r for r in rows if r["scroll"] == scroll and r.get("kind") == "mesh" and not r.get("error")]
        out.append({"scroll": scroll, "segments": s["segments"], "meshes": s["meshes"], "measured": s["measured"],
                    "errors": s["errors"], "clean_meshes": s["clean"],
                    "clean_segments": sum(1 for g in mine if g.get("clean")), "area_cm2": s["area_cm2"],
                    "largest_segment_cm2": round(max(areas), 3) if areas else None,
                    "median_segment_cm2": round(_median(areas), 3) if areas else None,
                    "median_within_10pct": _median([r.get("within_10pct") for r in top]),
                    "voxel_sizes_um": ";".join(f"{v:g}" for v in sorted({r["voxel_um"] for r in rows if
                                                                         r["scroll"] == scroll and r.get("voxel_um")})),
                    "prize_lists": _prize_text(s["prize_lists"])})
    return out


def _write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in rows:
            w.writerow([r.get(c) for c in columns])


def write(out, rows, figures=True):
    out = Path(out)
    with open(out / "atlas.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({c: r.get(c) for c in COLUMNS}, separators=(",", ":")) + "\n")
    with open(out / "atlas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([";".join(r[c]) if c == "prize_lists" and r.get(c) else r.get(c) for c in COLUMNS])
    segs = segment_rows(rows)
    _write_csv(out / "segments.csv", SEGMENT_COLUMNS, segs)
    _write_csv(out / "scrolls.csv", SCROLL_COLUMNS, scroll_rows(rows, segs))
    summary = summarize(rows)
    summary["figures"] = []
    if figures:
        try:
            from . import atlasfig
            summary["figures"] = atlasfig.write_all(out, rows, segs)
        except ImportError:
            pass                          # no matplotlib: the card is written without figures
        except Exception as exc:          # a figure must never stop the tables from being published
            summary["figure_error"] = f"{type(exc).__name__}: {exc}"[:300]
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    (out / "README.md").write_text(card(summary, segs), encoding="utf-8")
    return summary


FIGURE_TEXT = {
    "hero": ("Preview grids of the largest top-level mesh of twelve public segments, shaded by surface direction, "
             "with holes, folds and stretched nodes marked"),
    "by_scroll": "Traced area and clean share per scroll",
    "quality": "How isometric the grids are, and how much of each mesh is a hole, fold or stretched node",
}


def _num(v, n=1):
    return "" if v is None else f"{v:,.{n}f}"


def card(summary, segs=None):
    """The dataset card (README.md) for the published atlas, from its summary (and the segment rows, for the
    per-scroll largest segment)."""
    segs = segs or []
    largest = {}
    for g in segs:
        if g.get("area_cm2") is not None and g["area_cm2"] > largest.get(g["scroll"], -1):
            largest[g["scroll"]] = g["area_cm2"]
    rows = [f"| {k} | {v['segments']} | {v['meshes']} | {v['measured']} | {v['clean']} | {_num(v['area_cm2'])} | "
            f"{_num(largest.get(k))} | {', '.join(v['prize_lists']) or 'none'} |"
            for k, v in sorted(summary["scrolls"].items())]
    total_area = sum(v["area_cm2"] for v in summary["scrolls"].values())
    clean = sum(v["clean"] for v in summary["scrolls"].values())
    figs = set(summary.get("figures") or [])

    def fig(name):
        return f"\n![{FIGURE_TEXT[name]}](assets/{name}.png)\n" if name in figs else ""

    cols = "\n".join(f"| `{c}` | {COLUMN_DOCS[c][0]} | {COLUMN_DOCS[c][1]} | {COLUMN_DOCS[c][2]} |" for c in COLUMNS)
    related = "\n".join(f"- [{rid}]({_find.HUB}/{'spaces/' if kind == 'space' else 'datasets/'}{rid}): {text}"
                        for rid, kind, text in RELATED)
    changes = "\n".join(f"- **{d}**: {t}" for d, t in CHANGELOG)
    base = f"hf://datasets/{DATASET}"
    return f"""---
license: cc-by-nc-4.0
pretty_name: Vesuvius Segment Atlas
language:
- en
size_categories:
- 1K<n<10K
tags:
- vesuvius-challenge
- herculaneum
- papyrus
- x-ray-ct
- tifxyz
- mesh
- segmentation
- geometry
- tabular
configs:
- config_name: default
  default: true
  data_files:
  - split: train
    path: atlas.csv
- config_name: segments
  data_files:
  - split: train
    path: segments.csv
- config_name: scrolls
  data_files:
  - split: train
    path: scrolls.csv
---

# Vesuvius Segment Atlas

One table of geometry numbers for every traced segment the [Vesuvius Challenge open data]({_find.BUCKET}/)
publishes, measured the same way: one row per tifxyz mesh (a segment mapped to one scan volume) with its area, how
much of its grid is filled, how isometric the grid is, how many nodes sit in holes, folds or over-stretched edges,
and where it lies in the scan. Use it to pick segments to work on, to compare tracing quality across scrolls and
volumes, or to cite a segment's size with a fixed method and a dated source. A Hugging Face Job rebuilds it every
day at 06:17 UTC and measures only new or changed meshes.
{fig("hero")}
**At a glance** (built {summary['built']}, kit commit `{summary['kit_commit']}`): {summary['meshes']:,} meshes of
{summary['segments']:,} segments on {len(summary['scrolls'])} scrolls, {_num(total_area)} cm2 of traced surface
(each segment counted once), {clean:,} meshes with no holes, folds or stretched nodes, and {summary['errors']} not
measured (the `error` column says why).

## Quick start

```python
import pandas as pd   # hf:// paths need huggingface_hub installed

meshes = pd.read_csv("{base}/atlas.csv")         # one row per mesh
segments = pd.read_csv("{base}/segments.csv")    # one row per segment
scrolls = pd.read_csv("{base}/scrolls.csv")      # one row per scroll

# the ten largest clean segments
print(segments[segments.clean == True].nlargest(10, "area_cm2")[["scroll", "segment", "area_cm2", "voxel_um"]])
```

```python
from datasets import load_dataset

meshes = load_dataset("{DATASET}", split="train")                # config "default"
segments = load_dataset("{DATASET}", "segments", split="train")
```

```python
import polars as pl

pl.read_csv("{base}/scrolls.csv").sort("area_cm2", descending=True)
```

```sql
-- DuckDB
SELECT scroll, count(*) AS segments, round(sum(area_cm2), 1) AS cm2
FROM '{base}/segments.csv' GROUP BY scroll ORDER BY cm2 DESC;
```

Each mesh's `url` is its folder on the open-data bucket (x.tif, y.tif, z.tif and meta.json), so a row leads straight
to the mesh. The same numbers on the command line come from [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls):
`python -m kit atlas show PHerc0139 --top 5`.

## What is in it

| File | Rows | What |
| --- | --- | --- |
| `atlas.csv` (config `default`) | one per mesh | every column below |
| `atlas.jsonl` | one per mesh | the same rows as JSON lines; `prize_lists` is a list there |
| `segments.csv` (config `segments`) | one per segment | the segment's finest-voxel measured top-level mesh, with mesh and volume counts |
| `scrolls.csv` (config `scrolls`) | one per scroll | counts, traced area, largest and median segment, voxel sizes |
| `summary.json` | | the per-scroll counts of the table below, build time and kit commit |
| `lens/NAME.slg.gz` | one per mesh of a scroll on no prize list | a small preview grid of the mesh, read by the Segment Lens viewer (format below) |
| `assets/*.png` | | the figures on this page |

| Scroll | Segments | Meshes | Measured | Clean | Area, cm2 (each segment once) | Largest segment, cm2 | Prize lists (kit snapshot) |
| --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(rows)}

A segment often has several meshes: one per volume it was mapped to (different voxel sizes or scan energies), plus
any intermediate meshes the publisher kept. Area per scroll counts each segment once, from its finest-voxel
top-level mesh, the same mesh `segments.csv` uses.
{fig("by_scroll")}
## Columns

`atlas.csv` and `atlas.jsonl`, in file order. Columns added after the first release are appended at the end, so
code that reads by position keeps working. Empty means not known or not measured.

| Column | Type | Unit | Meaning |
| --- | --- | --- | --- |
{cols}

`segments.csv` has `scroll`, `segment`, `meshes` (rows of the segment), `volumes` (distinct volumes), `best_mesh` (the
`id` of the mesh it stands for) and that mesh's `{"`, `".join(c for c in SEGMENT_COLUMNS[5:] if c != "prize_lists")}`;
`prize_lists` there and in `scrolls.csv` is empty when none. `scrolls.csv` has `{"`, `".join(SCROLL_COLUMNS)}`:
`clean_meshes` counts every measured mesh, `clean_segments` the segments whose standing mesh is clean, and
`median_within_10pct` is over top-level meshes.
{fig("quality")}
### Lens files

`lens/NAME.slg.gz` (NAME is the first 16 hex digits of the SHA-256 of the row's `id`) is gzip over: the 4 bytes
`SLG1`; uint16 `h`, `w`, `k` (little-endian); six float32, `lo` x, y, z then `hi` x, y, z; three planes of h x w
uint16 (x, y and z of every k-th node, `lo + q / 65534 * (hi - lo)`, 65535 for a missing node); then h x w uint8
flags, the OR over the k x k block each node stands for (1 hole, 2 fold, 4 stretched). `k` makes the longest side at
most 256.

```python
import gzip, struct
import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download

def read_lens(path):
    raw = gzip.open(path).read()
    assert raw[:4] == b"SLG1"
    h, w, k = struct.unpack("<HHH", raw[4:10])
    lo, hi = np.array(struct.unpack("<6f", raw[10:34])).reshape(2, 3)
    q = np.frombuffer(raw, "<u2", 3 * h * w, 34).reshape(3, h, w)
    flags = np.frombuffer(raw, np.uint8, h * w, 34 + 6 * h * w).reshape(h, w)
    xyz = lo + np.moveaxis(q, 0, -1) / 65534.0 * np.where(hi > lo, hi - lo, 1.0)
    xyz[q[0] == 65535] = np.nan
    return xyz, flags, k          # positions in voxels, (h, w, 3); flags (h, w); stride k

row = pd.read_csv("{base}/atlas.csv").dropna(subset=["lens"]).iloc[0]
xyz, flags, k = read_lens(hf_hub_download("{DATASET}", "lens/" + row.lens, repo_type="dataset"))
```

## How it was made

1. **List.** Read the bucket's `metadata.json` and list `SCROLL/segments/` for every scroll; every folder under a
   segment's `mesh/` (up to three levels down) that holds `x.tif`, `y.tif` and `z.tif` is one row.
2. **Voxel size.** From the folder name (`-N.NNNum.tifxyz`), else the volume's metadata, else the scroll's only
   volume; `voxel_um_from` says which.
3. **Measure.** Fetch the three files, run the checks of `kit tifxyz` (`info`, `stretch`, `check`, default settings;
   a test requires the same numbers), and delete the copy. Meshes over 12 million nodes are measured in bands of
   1,024 rows, each cell and edge in exactly one band, with the same counts as the whole grid; their percentiles come
   from every k-th value, at most 2 million kept.
4. **Previews.** For scrolls on no prize list in kit's dated snapshot of https://scrollprize.org/prizes, write a
   preview grid to `lens/`. Scrolls on a prize list get numbers only.
5. **Refresh.** Each row keeps a `fingerprint` of its files' ETags and sizes; the daily Job measures a mesh again
   only when that changes, when its row has an error or a missing preview, or when a newer column was added.

The code is `kit/atlas.py` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls) (tool page
`docs/tools/atlas.md`, tests `tests/test_atlas.py`); the Job is `scripts/atlas/hf_atlas.py`, run on a Hugging Face
`cpu-upgrade` machine from the repository's public `main`.

## Limits

- The numbers describe the grid, not the papyrus. A clean mesh can still jump from one sheet to the next: nothing
  here looks at the CT, detects sheet switches or judges ink, and none of it is an official villa or prize check.
- `extent_*_mm` is the axis-aligned bounding box of the filled nodes in scan coordinates. A rolled sheet fills
  only part of its box, so the box is not the size of the flattened papyrus; `area_cm2` is.
- Area counts complete grid cells only, so a mesh with many holes reads a little small. Without a known voxel size
  the area and extents are empty.
- Meshes of one segment on different volumes, and intermediate meshes, are separate rows: sum `segments.csv`, or
  filter `kind == "mesh"` and pick one volume, to avoid counting a segment twice.
- Prize lists come from a dated snapshot in kit, not the live prize page.

## License and credit

The meshes are Vesuvius Challenge open data, CC BY-NC 4.0 (non-commercial); these derived numbers and preview grids
carry the same license. Credit: Vesuvius Challenge open data, CC BY-NC 4.0. The segments are those the Vesuvius
Challenge publishes on its open-data bucket; this dataset only measures them. The code that builds the atlas is
Apache-2.0.

## Citation

```bibtex
@misc{{sharpmeow2026segmentatlas,
  author       = {{SharpMeow}},
  title        = {{Vesuvius Segment Atlas}},
  year         = {{2026}},
  howpublished = {{\\url{{{_find.HUB}/datasets/{DATASET}}}}},
  note         = {{Hugging Face dataset, rebuilt daily from the Vesuvius Challenge open data}}
}}
```

## Changelog

{changes}

## Related

{related}
"""


def summarize(rows):
    by = {}
    for r in rows:
        s = by.setdefault(r["scroll"], {"segments": set(), "meshes": 0, "measured": 0, "errors": 0, "clean": 0,
                                        "area_cm2": 0.0, "prize_lists": r.get("prize_lists") or []})
        s["segments"].add(r["segment"])
        s["meshes"] += 1
        if r.get("error"):
            s["errors"] += 1
        elif "grid_h" in r and r.get("grid_h") is not None:
            s["measured"] += 1
            s["clean"] += bool(r.get("clean"))
    # area per scroll: each segment once, from its finest-voxel measured top-level mesh
    best = {}
    for r in rows:
        if r.get("area_cm2") is None or r.get("kind") != "mesh":
            continue
        key = (r["scroll"], r["segment"])
        if key not in best or (r.get("voxel_um") or 99) < (best[key].get("voxel_um") or 99):
            best[key] = r
    for (scroll, _), r in best.items():
        by[scroll]["area_cm2"] += r["area_cm2"]
    scrolls = {k: {**v, "segments": len(v["segments"]), "area_cm2": round(v["area_cm2"], 1)} for k, v in by.items()}
    return {"schema": SCHEMA, "built": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "kit_commit": _commit(), "bucket": _find.BUCKET, "meshes": len(rows),
            "segments": sum(v["segments"] for v in scrolls.values()),
            "errors": sum(v["errors"] for v in scrolls.values()), "scrolls": scrolls}


# ---------------------------------------------------------------- show

SORTS = ("area_cm2", "holes_mm2", "folds_mm2", "stretched_mm2", "within_10pct", "median_abs_log", "id")


def show(rows, scroll=None, sort="area_cm2", top=None, kind="mesh"):
    """Rows of one scroll (or all), top-level meshes only unless kind is None, sorted (largest first, id A to Z)."""
    if scroll:
        rows = [r for r in rows if r["scroll"].lower() == scroll.lower()]
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    rev = sort != "id"
    rows = sorted(rows, key=lambda r: (r.get(sort) is None, -(r.get(sort) or 0) if rev else r.get(sort) or ""))
    if sort == "id":
        rows = sorted(rows, key=lambda r: r["id"])
    return rows[:top] if top else rows


def format_show(rows, total):
    if not rows:
        return "no meshes match"
    lines = [f"{len(rows)} of {total} meshes  (area cm2, filled, edges within 10% of the step, holes, folds and "
             "stretched in mm2)"]
    for r in rows:
        if r.get("error"):
            lines.append(f"  {r['id']}  not measured: {r['error']}")
            continue
        f = (lambda v, n=2: "-" if v is None else f"{v:.{n}f}")
        lines.append(f"  {r['scroll']:<12} {r['segment'][:34]:<34} {f(r.get('voxel_um'), 3):>7} um "
                     f"{f(r.get('area_cm2')):>8} cm2  {f(r.get('filled_share'), 2):>5}  "
                     f"{f(r.get('within_10pct'), 2):>5}  holes {f(r.get('holes_mm2'))} folds {f(r.get('folds_mm2'))} "
                     f"stretched {f(r.get('stretched_mm2'))}" + ("  clean" if r.get("clean") else ""))
    return "\n".join(lines)


# ---------------------------------------------------------------- command line

def build_parser(p):
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("build", help="measure every mesh on the bucket and write the atlas files")
    a.add_argument("out", help="folder for atlas.jsonl, atlas.csv, summary.json and lens/")
    a.add_argument("--scroll", action="append", help="only this scroll (repeat for more)")
    a.add_argument("--previous", help="an earlier atlas.jsonl (path or URL): unchanged meshes are not measured again")
    a.add_argument("--workers", type=int, help="meshes measured at once (default: CPUs, at most 4)")
    a.add_argument("--lens", action="store_true", help="also write Segment Lens preview grids (scrolls on no prize list)")
    a.add_argument("--limit", type=int, help="only the first N meshes (for a test)")
    a.add_argument("--workdir", help="where each mesh is fetched while it is measured (default: the system temp)")
    a = actions.add_parser("show", help="print the atlas for one scroll or all")
    a.add_argument("scroll", nargs="?", help="a scroll id, such as PHerc0139 (default: all)")
    a.add_argument("--atlas", default=ATLAS_URL, help="atlas.jsonl path or URL (default: the published dataset)")
    a.add_argument("--sort", default="area_cm2", choices=SORTS, help="column to sort by")
    a.add_argument("--top", type=int, help="only the first N rows")
    a.add_argument("--all-kinds", action="store_true", help="include intermediate meshes, not only top-level ones")
    a.add_argument("--json", action="store_true")
    return p


def cmd_atlas(args):
    """python -m kit atlas build|show: exit 0 when done, 1 when build measured nothing, 2 on bad input or network."""
    try:
        if args.action == "build":
            s = build(args.out, args.scroll, args.previous, args.workers, args.lens, args.limit,
                      workdir=args.workdir)
            print(f"atlas: {s['meshes']} meshes of {s['segments']} segments, {s['errors']} not measured; "
                  f"wrote {Path(args.out) / 'atlas.jsonl'}")
            return 0 if s["meshes"] else 1
        rows = read_atlas(args.atlas)
        picked = show(rows, args.scroll, args.sort, args.top, None if args.all_kinds else "mesh")
        print(json.dumps(picked, indent=1) if args.json else format_show(picked, len(rows)))
        return 0
    except VerifyError as exc:
        print(f"kit atlas: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"kit atlas could not read the bucket or the atlas: {exc}", file=sys.stderr)
        return 2


def main(argv=None):
    p = build_parser(argparse.ArgumentParser(prog="python -m kit.atlas", description=__doc__.split("\n\n")[0]))
    return cmd_atlas(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
