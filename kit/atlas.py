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
           "measured_at")


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
    if filled:
        z = seg.xyz[..., 2][seg.valid]
        out["z_min"], out["z_max"] = round(float(z.min()), 1), round(float(z.max()), 1)
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


def write(out, rows):
    out = Path(out)
    with open(out / "atlas.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({c: r.get(c) for c in COLUMNS}, separators=(",", ":")) + "\n")
    with open(out / "atlas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([";".join(r[c]) if c == "prize_lists" and r.get(c) else r.get(c) for c in COLUMNS])
    summary = summarize(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    (out / "README.md").write_text(card(summary), encoding="utf-8")
    return summary


def card(summary):
    """The dataset card (README.md) for the published atlas, from its summary."""
    rows = [f"| {k} | {v['segments']} | {v['meshes']} | {v['measured']} | {v['clean']} | {v['area_cm2']} | "
            f"{', '.join(v['prize_lists']) or 'none'} |" for k, v in sorted(summary["scrolls"].items())]
    return f"""---
license: cc-by-nc-4.0
pretty_name: Vesuvius Segment Atlas
tags:
- vesuvius-challenge
- herculaneum
- tifxyz
- segmentation
configs:
- config_name: default
  data_files:
  - split: train
    path: atlas.csv
---

# Vesuvius Segment Atlas

The same geometry numbers for every traced segment the [Vesuvius Challenge open data]({_find.BUCKET}/) publishes:
one row per tifxyz mesh (a segment mapped to one scan volume), with its area in cm2, how much of its grid is filled,
how isometric the grid is, and how many grid nodes sit in holes inside the sheet, in folds, or on over-stretched
edges. Built by `python -m kit atlas build` from [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls)
(page: `docs/tools/atlas.md`), refreshed daily by a Hugging Face Job that measures only new or changed meshes.

Built {summary['built']} from commit `{summary['kit_commit']}`: {summary['meshes']} meshes of {summary['segments']}
segments, {summary['errors']} not measured (the `error` column says why).

| Scroll | Segments | Meshes | Measured | Clean | Area, cm2 (each segment once) | Prize lists (kit snapshot) |
| --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(rows)}

## What the numbers mean

- **area_cm2**: two triangles per complete grid cell, in voxels squared, times the voxel size squared. The voxel
  size comes from the folder name (`-N.NNNum.tifxyz`), else from the volume's metadata, else from the scroll's only
  volume (`voxel_um_from` says which); without one the area is empty. **meta_area_ratio** is our area over the
  `area_vx2` VC3D wrote into `meta.json`, where there is one.
- **edge_p5, edge_p50, edge_p95**: every grid edge's 3D length over the step `meta.json`'s `scale` promises (1.0 is
  exact); **within_10pct** and **within_25pct** are the shares of edges that close; **median_abs_log** is the median
  of the absolute log of that ratio; **cell_area_p50** is cell area over the promised area; **angle_p5/p50/p95** is
  the angle between the two grid directions, in degrees (90 is square).
- **holes_nodes**: missing nodes not joined to the grid's border through missing nodes (holes inside the sheet).
  **folds_nodes**: nodes of neighboring cells whose normals turn by more than 90 degrees. **stretched_nodes**: nodes
  on an edge more than 1.5 times too long or too short. Each also in mm2. **clean** is true when all three are 0.
- **kind** is `mesh` for a top-level mesh folder and the subfolder name (such as `intermediate`) otherwise. Area per
  scroll in the table counts each segment once, from its finest-voxel top-level mesh.
- **lens**: for scrolls on no prize list, the file in `lens/` with a small preview grid used by the Segment Lens
  viewer (format in `docs/tools/atlas.md`). Scrolls on a prize list get numbers only.
- **fingerprint** comes from the ETags and sizes of x.tif, y.tif and z.tif; a refresh measures a mesh again only when
  it changes.

These numbers describe the grid, not the papyrus. A clean mesh can still jump from one sheet to the next; nothing
here looks at the CT or judges ink, and none of it is an official villa or prize check.

## License and credit

The meshes are Vesuvius Challenge open data, CC BY-NC 4.0; these derived numbers and preview grids carry the same
license. Credit: Vesuvius Challenge open data, CC BY-NC 4.0. The code that makes them is Apache-2.0.
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
