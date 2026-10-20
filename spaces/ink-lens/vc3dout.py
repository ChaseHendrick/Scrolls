"""Ink Lens: VC3D's own files for one region of a tifxyz segment (numpy and the standard library only).

Every rule below is read from ScrollPrize/villa main 8aa507c12 (volume-cartographer/):

- Ink overlay: VC3D reads SEGDIR/ink-detections.json, a JSON array of records whose local_file is relative to SEGDIR
  (apps/VC3D/OpenDataSegmentCache.cpp:651-694). A non-empty file replaces the catalog's own list, so records already
  there are kept and only a record for the same file is replaced (merge_records). A record is offered on a segment
  only when its segment_id or segment_long_id equals the segment's key (InkDetectionOverlayController.cpp:52-65,
  502-510): the catalog ids in meta.json when present, else the folder name (core/src/Segmentation.cpp:42-56).
- The image is read unchanged; a single-channel 8-bit image is drawn with alpha equal to the pixel value, so 0 is
  transparent (InkDetectionOverlayController.cpp:512-580). It is stretched over the whole segment grid, each axis on
  its own (:395-437), so the PNG covers the whole canvas and its aspect equals the grid's over meta.json's scale.
- Points: a VC3D point collection file {"vc_pointcollections_json_version": "1", "collections": {id: {name, points:
  {id: {p: [x, y, z], creation_time, wind_a}}, metadata, color}}} (core/src/PointCollections.cpp:36-119, 571-662).
  Loading one replaces every current collection (:647), so merge_points adds to a saved file instead.
- Grid to voxels: x.tif, y.tif and z.tif hold the voxel position of each grid vertex; a vertex with a -1 coordinate
  is a hole (core/src/QuadSurface.cpp:279) and one with z <= 0 is dropped on load (:1077-1096).
"""

from __future__ import annotations

import json
import os
import struct
import tempfile
import time
import zlib
from pathlib import Path

POINTS_VERSION = "1"
ASPECT_TOL = 0.02          # the canvas aspect may differ from the grid's by 2 % (whole pixels), as kit.villafmt allows
MAX_CANVAS_SIDE = 16384    # a canvas longer than this is written at a whole-number fraction of the map's resolution
NOTE = "Model output, not a reading."


class VC3DError(ValueError):
    """A segment or file Ink Lens will not write into; the message says why."""


# ---------------------------------------------------------------- small file helpers

def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def png_bytes(gray):
    """A 2-D uint8 array as an 8-bit grayscale PNG (zlib only)."""
    import numpy as np
    a = np.asarray(gray)
    if a.ndim != 2 or a.dtype != np.uint8 or not a.size:
        raise VC3DError(f"a PNG here is a non-empty 2-D uint8 array, not {a.dtype} {a.shape}")
    h, w = a.shape
    rows = np.zeros((h, w + 1), np.uint8)
    rows[:, 1:] = a

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows.tobytes(), 6)) + chunk(b"IEND", b""))


def read_png_gray(data):
    """An 8-bit grayscale, non-interlaced PNG (as png_bytes writes, any filter) as a 2-D uint8 array."""
    import numpy as np
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise VC3DError("not a PNG")
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        n, tag = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos += 12 + n
    if ihdr is None:
        raise VC3DError("a PNG with no IHDR")
    w, h, depth, ctype, _, _, interlace = ihdr
    if (depth, ctype, interlace) != (8, 0, 0):
        raise VC3DError(f"only 8-bit grayscale non-interlaced PNGs are read here (depth {depth}, type {ctype})")
    raw = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(h, w + 1)
    out = np.zeros((h, w), np.uint8)
    prev = np.zeros(w, np.int32)
    for y in range(h):
        f, line = raw[y, 0], raw[y, 1:].astype(np.int32)
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 255
        else:
            cur = np.zeros(w, np.int32)
            for x in range(w):
                a = cur[x - 1] if x else 0
                b = prev[x]
                c = prev[x - 1] if x else 0
                if f == 1:
                    pred = a
                elif f == 3:
                    pred = (a + b) // 2
                elif f == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
                else:
                    raise VC3DError(f"PNG filter type {f}")
                cur[x] = (line[x] + pred) & 255
        out[y] = cur
        prev = cur
    return out


def tiff_size(path):
    """(width, height) of a TIFF from its first IFD (classic or BigTIFF), with no imaging library."""
    with open(path, "rb") as fh:
        head = fh.read(16)
        if head[:2] not in (b"II", b"MM"):
            raise VC3DError(f"{path} is not a TIFF")
        e = "<" if head[:2] == b"II" else ">"
        magic = struct.unpack(e + "H", head[2:4])[0]
        if magic == 42:
            fh.seek(struct.unpack(e + "I", head[4:8])[0])
            n = struct.unpack(e + "H", fh.read(2))[0]
            entries = [fh.read(12) for _ in range(n)]
            fmt = {3: "H", 4: "I"}
            vals = {}
            for ent in entries:
                tag, typ, _ = struct.unpack(e + "HHI", ent[:8])
                if tag in (256, 257) and typ in fmt:
                    vals[tag] = struct.unpack(e + fmt[typ], ent[8:8 + struct.calcsize(fmt[typ])])[0]
        elif magic == 43:
            fh.seek(struct.unpack(e + "Q", head[8:16])[0])
            n = struct.unpack(e + "Q", fh.read(8))[0]
            fmt = {3: "H", 4: "I", 16: "Q"}
            vals = {}
            for _ in range(n):
                ent = fh.read(20)
                tag, typ, _ = struct.unpack(e + "HHQ", ent[:12])
                if tag in (256, 257) and typ in fmt:
                    vals[tag] = struct.unpack(e + fmt[typ], ent[12:12 + struct.calcsize(fmt[typ])])[0]
        else:
            raise VC3DError(f"{path} is not a TIFF (magic {magic})")
    if 256 not in vals or 257 not in vals:
        raise VC3DError(f"{path}: no image width or height tag")
    return int(vals[256]), int(vals[257])


# ---------------------------------------------------------------- the segment

def segment_key(segdir, meta):
    """The key VC3D matches an ink record against: catalog ids in meta.json if any, else the folder name."""
    for k in ("vc_open_data_segment_long_id", "vc_open_data_catalog_segment_lineage_id", "vc_open_data_segment_id"):
        v = meta.get(k) if isinstance(meta, dict) else None
        if isinstance(v, str) and v:
            return v
    return Path(segdir).resolve().name


def segment(segdir):
    """What Ink Lens needs to know of a tifxyz folder: key, grid size, scale and the render canvas in pixels."""
    segdir = Path(segdir)
    meta_path = segdir / "meta.json"
    if not meta_path.is_file():
        raise VC3DError(f"{segdir} has no meta.json; give a tifxyz segment folder")
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise VC3DError(f"{meta_path}: {exc}") from None
    if not isinstance(meta, dict) or meta.get("format") != "tifxyz":
        raise VC3DError(f"{meta_path}: format is {meta.get('format') if isinstance(meta, dict) else None!r}, "
                        "VC3D needs tifxyz")
    for band in ("x.tif", "y.tif", "z.tif"):
        if not (segdir / band).is_file():
            raise VC3DError(f"{segdir} has no {band}")
    cols, rows = tiff_size(segdir / "x.tif")
    sc = meta.get("scale")
    if not (isinstance(sc, list) and len(sc) == 2 and all(isinstance(v, (int, float)) and v > 0 for v in sc)):
        raise VC3DError(f"{meta_path}: scale {sc!r} is not two positive numbers")
    sx, sy = float(sc[0]), float(sc[1])
    return {"dir": str(segdir.resolve()), "key": segment_key(segdir, meta), "meta": meta, "grid": [rows, cols],
            "scale": [sx, sy], "canvas_px": [int(round(cols / sx)), int(round(rows / sy))]}


def canvas(seg, box, map_u8, pool, max_side=MAX_CANVAS_SIDE):
    """(canvas uint8, divisor): the whole segment canvas at the map's resolution, or at 1/k of it when longer than
    max_side, with the region's map placed at box (y, x, h, w) in render pixels and 0 everywhere else."""
    import numpy as np
    cw, ch = seg["canvas_px"]
    k = 1
    while max(cw, ch) / (pool * k) > max_side:
        k += 1
    div = pool * k
    W, H = max(1, int(round(cw / div))), max(1, int(round(ch / div)))
    rows, cols = seg["grid"]
    expected = (cols / seg["scale"][0]) / (rows / seg["scale"][1])
    if abs((W / H) / expected - 1) > ASPECT_TOL:
        raise VC3DError(f"a {W} x {H} canvas would not keep the grid's aspect {expected:.4f}; the segment is too "
                        "small for this map resolution")
    m = np.asarray(map_u8)
    if k > 1:
        hh, ww = m.shape[0] // k * k, m.shape[1] // k * k
        m = m[:hh, :ww].reshape(hh // k, k, ww // k, k).max(axis=(1, 3))
    y, x = int(box[0]) // div, int(box[1]) // div
    out = np.zeros((H, W), np.uint8)
    y1, x1 = min(H, y + m.shape[0]), min(W, x + m.shape[1])
    if y >= H or x >= W or y1 <= y or x1 <= x:
        raise VC3DError(f"the region at rows {box[0]}, columns {box[1]} lies outside the segment's canvas {cw} x {ch}")
    out[y:y1, x:x1] = m[:y1 - y, :x1 - x]
    return out, div


def merge_mosaic(path, new):
    """The running maximum of the mosaic at path and a new canvas; a mosaic of another size is replaced."""
    import numpy as np
    path = Path(path)
    if path.is_file():
        try:
            old = read_png_gray(path.read_bytes())
        except VC3DError:
            old = None
        if old is not None and old.shape == new.shape:
            return np.maximum(old, new), True
    return new, False


def merge_records(segdir, records):
    """Add records to SEGDIR/ink-detections.json, keeping every record already there except one for the same
    local_file. Refuses a file that is not a JSON array (VC3D would ignore it, and overwriting would lose it)."""
    segdir = Path(segdir)
    path = segdir / "ink-detections.json"
    old = []
    if path.exists():
        try:
            old = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise VC3DError(f"{path} is not readable JSON ({exc}); refusing to overwrite it") from None
        if not isinstance(old, list):
            raise VC3DError(f"{path} is not a JSON array; refusing to overwrite it")

    def where(local_file):
        f = Path(local_file)
        return f if f.is_absolute() else (segdir / f).resolve()

    new_files = {where(r["local_file"]) for r in records}
    kept = [r for r in old if not (isinstance(r, dict) and isinstance(r.get("local_file"), str)
                                   and where(r["local_file"]) in new_files)]
    out = kept + list(records)
    atomic_write(path, json.dumps(out, indent=2) + "\n")
    return {"file": str(path), "records": len(out), "kept_existing": len(kept)}


def record(seg, local_file, label, sha256, size, extra=None):
    r = {"local_file": local_file, "label": label, "segment_id": seg["key"], "segment_long_id": seg["key"],
         "sample_id": "", "artifact_type": "ink-lens", "ink_lens": {"sha256": sha256, "size": list(size), "note": NOTE}}
    if extra:
        r["ink_lens"].update(extra)
    return r


# ---------------------------------------------------------------- grid and voxels

def load_xyz(segdir):
    """The x, y and z bands of a tifxyz folder as one (3, rows, cols) float32 array (needs tifffile)."""
    import numpy as np
    try:
        import tifffile
    except ImportError:
        raise VC3DError("mapping pins onto the segment needs tifffile (pip install tifffile)") from None
    bands = [tifffile.imread(str(Path(segdir) / f"{c}.tif")).astype(np.float32) for c in "xyz"]
    if not (bands[0].shape == bands[1].shape == bands[2].shape):
        raise VC3DError(f"{segdir}: x, y and z bands differ in size")
    return np.stack(bands)


def render_to_grid(seg, r, c):
    """Render pixel (row, column) at scale 1 to fractional grid (row, column)."""
    sx, sy = seg["scale"]
    return r * sy, c * sx


def grid_to_voxel(xyz, gr, gc):
    """Bilinear voxel position [x, y, z] at fractional grid (row, column), or None on or next to a hole."""
    import math
    _, rows, cols = xyz.shape
    if not (0 <= gr <= rows - 1 and 0 <= gc <= cols - 1):
        return None
    r0, c0 = int(math.floor(gr)), int(math.floor(gc))
    r1, c1 = min(r0 + 1, rows - 1), min(c0 + 1, cols - 1)
    fr, fc = gr - r0, gc - c0
    corners = [xyz[:, r0, c0], xyz[:, r0, c1], xyz[:, r1, c0], xyz[:, r1, c1]]
    for v in corners:
        if (v == -1).any() or v[2] <= 0:
            return None
    top = corners[0] * (1 - fc) + corners[1] * fc
    bot = corners[2] * (1 - fc) + corners[3] * fc
    p = top * (1 - fr) + bot * fr
    return [round(float(p[0]), 3), round(float(p[1]), 3), round(float(p[2]), 3)]


def voxel_to_grid(xyz, point):
    """The grid vertex nearest a voxel point [x, y, z], as (row, column, distance in voxels); holes are skipped."""
    import numpy as np
    pts = xyz.reshape(3, -1).T
    valid = ~(pts == -1).any(axis=1) & (pts[:, 2] > 0)
    if not valid.any():
        raise VC3DError("the segment has no valid vertex")
    d = np.full(pts.shape[0], np.inf, np.float64)
    d[valid] = np.linalg.norm(pts[valid] - np.asarray(point, np.float32), axis=1)
    i = int(np.argmin(d))
    return divmod(i, xyz.shape[2]) + (float(d[i]),)


# ---------------------------------------------------------------- point collections

def points_doc(name, points, color=(0.2, 0.9, 1.0), metadata=None):
    """A VC3D point collection document with one collection."""
    now = int(time.time())
    pts = {str(i + 1): {"p": list(p), "creation_time": now, "wind_a": None} for i, p in enumerate(points)}
    md = {"winding_is_absolute": False}
    md.update(metadata or {})
    return {"vc_pointcollections_json_version": POINTS_VERSION,
            "collections": {"1": {"name": name, "points": pts, "metadata": md, "color": list(color)}}}


def check_points_doc(doc):
    """Problems VC3D's loader would have with a point collection document (empty list when it loads)."""
    out = []
    if not isinstance(doc, dict) or doc.get("vc_pointcollections_json_version") != POINTS_VERSION:
        return [f"vc_pointcollections_json_version must be {POINTS_VERSION!r}"]
    cols = doc.get("collections")
    if not isinstance(cols, dict):
        return ["collections is not an object"]
    for cid, c in cols.items():
        if not str(cid).isdigit():
            out.append(f"collection id {cid!r} is not a whole number")
        if not isinstance(c, dict) or not isinstance(c.get("name"), str):
            out.append(f"collection {cid} has no name")
            continue
        pts = c.get("points", {})
        if not isinstance(pts, dict):
            out.append(f"collection {cid} points is not an object")
            continue
        for pid, p in pts.items():
            if not str(pid).isdigit():
                out.append(f"point id {pid!r} is not a whole number")
            xyz = p.get("p") if isinstance(p, dict) else None
            if not (isinstance(xyz, list) and len(xyz) == 3 and all(isinstance(v, (int, float)) for v in xyz)):
                out.append(f"collection {cid} point {pid} has no p [x, y, z]")
            elif isinstance(p, dict) and p.get("wind_a") is not None and not isinstance(p["wind_a"], (int, float)):
                out.append(f"collection {cid} point {pid} has a wind_a that is neither a number nor null")
    return out


def merge_points(existing, new):
    """existing (a document VC3D saved, or None) plus every collection of new, renumbered after the existing ids;
    a collection of the same name is replaced."""
    if existing is None:
        existing = {"vc_pointcollections_json_version": POINTS_VERSION, "collections": {}}
    probs = check_points_doc(existing)
    if probs:
        raise VC3DError("the saved point collections are not loadable: " + "; ".join(probs))
    cols = dict(existing["collections"])
    names = {c["name"] for c in new["collections"].values()}
    cols = {k: v for k, v in cols.items() if v.get("name") not in names}
    nxt = max([int(k) for k in cols] + [0]) + 1
    for c in new["collections"].values():
        cols[str(nxt)] = c
        nxt += 1
    return {"vc_pointcollections_json_version": POINTS_VERSION, "collections": cols}
