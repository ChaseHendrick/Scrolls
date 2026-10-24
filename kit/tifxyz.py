"""Look at a tifxyz segment without building VC3D: its area, how isometric its grid is, holes and folds, an OBJ, a
picture, and which way its normals face.

A tifxyz segment is a folder of three float32 TIFFs, x.tif, y.tif and z.tif, one grid of 3D points in voxels of one
volume, with meta.json beside them (VC3D and villa write it; "scale" is grid nodes per voxel). Give a local folder
or a folder on the open-data bucket (https:// or s3://), which is fetched once into --cache.

  info     area in cm2 and mm2 (two triangles per complete grid cell), grid size, filled share, bounding box,
           voxel size, and meta.json's own area_vx2 beside ours as a check
  stretch  how close the grid is to isometric: every grid edge's 3D length over the step meta.json's scale promises
           (1.0 is exact), cell area over the promised area, and the angle between the two grid directions
  check    holes inside the sheet, folds (neighboring cells whose normals turn by more than --fold-deg) and
           over-stretched nodes (an edge more than --max-stretch times too long or too short), each with a count, a
           share and a verdict line; --png writes a picture with each problem in its own color
  obj      a Wavefront OBJ (vertices, UVs and triangles) for Blender or MeshLab
  preview  a shaded PNG of the sheet, holes dark
  facing   with the scroll's center line: the share of the grid normals (x-step cross y-step, as in kit stackcheck)
           that point away from the center, and the share of grid columns along which the angle about the center
           grows, so you can tell which side of the sheet a render's layers go toward
  chunks   which chunks of a zarr volume the sheet touches (within --margin voxels), their count and stored bytes
           (one HEAD each on a bucket), and with --fetch a local copy holding the metadata and only those chunks
  diff     two versions of a segment: area change, nodes added and removed, and how far the kept ones moved (node
           by node when the grids match, by position when they do not), with an optional picture

Geometry only: no CT, no ink. Nothing here is an official villa or prize check; the numbers describe the grid.
Standard library plus numpy and tifffile; scipy, when installed, finds holes faster.
"""

import argparse
import json
import math
import re
import struct
import sys
import zlib
from pathlib import Path

from .verify import VerifyError

DEFAULT_CACHE = "work/tifxyz/cache"
MAX_STRETCH = 1.5
FOLD_DEG = 90.0
_UM = re.compile(r"-(\d+(?:\.\d+)?)um\.tifxyz/?$")
_VOL = re.compile(r"-on-(\d{14})-")


def _np():
    try:
        import numpy
    except ImportError as exc:
        raise VerifyError("kit tifxyz needs numpy and tifffile: pip install numpy tifffile") from exc
    return numpy


class Segment:
    """One tifxyz grid: xyz (H, W, 3) float64 in voxels, valid (H, W), meta, the source, voxel size and grid step."""

    def __init__(self, xyz, valid, meta=None, source="", voxel_um=None):
        np = _np()
        self.xyz, self.valid, self.meta, self.source = xyz, valid, dict(meta or {}), str(source)
        scale = self.meta.get("scale") or [1.0, 1.0]
        try:
            sx, sy = (float(v) for v in scale[:2])
        except (TypeError, ValueError):
            sx = sy = float("nan")
        if not (math.isfinite(sx) and math.isfinite(sy) and sx > 0 and sy > 0):
            raise VerifyError(f"{source}: meta.json scale must be two numbers above 0 (got {scale!r})")
        # scale[0] is nodes per voxel along columns (x of the grid), scale[1] along rows
        self.step = (1.0 / sx, 1.0 / sy)
        if voxel_um is None:
            m = _UM.search(self.source.rstrip("/"))
            voxel_um = float(m.group(1)) if m else None
        self.voxel_um = voxel_um
        m = _VOL.search(self.source)
        self.volume = m.group(1) if m else None
        self.shape = valid.shape
        self._np = np


def load(src, cache=DEFAULT_CACHE, voxel_um=None):
    """A Segment from a local tifxyz folder or a bucket URL (fetched once into cache)."""
    from . import meshaudit, stackcheck
    np = _np()
    try:
        import tifffile  # noqa: F401
    except ImportError as exc:
        raise VerifyError("kit tifxyz needs numpy and tifffile: pip install numpy tifffile") from exc
    src = str(src)
    folder = stackcheck.fetch_tifxyz(src, cache) if stackcheck._is_url(src) else Path(src)
    if not folder.is_dir():
        raise VerifyError(f"no tifxyz folder at {src}")
    try:
        arrs = [meshaudit.imread_capped(str(folder / f"{c}.tif")) for c in "xyz"]
    except Exception as exc:  # missing file or unreadable TIFF
        raise VerifyError(f"cannot read the tifxyz folder {src}: {exc}") from exc
    if any(a.ndim != 2 or a.shape != arrs[0].shape for a in arrs):
        raise VerifyError(f"{src}: x.tif, y.tif and z.tif must be 2D grids of one shape")
    xyz = np.stack(arrs, -1).astype(np.float64)
    valid = np.isfinite(xyz).all(-1) & (xyz > -0.5).all(-1) & (np.abs(xyz).sum(-1) > 0)
    meta = {}
    if (folder / "meta.json").is_file():
        try:
            meta = json.loads((folder / "meta.json").read_text())
        except (OSError, ValueError):
            meta = {}
    return Segment(xyz, valid, meta, src, voxel_um)


# ---------------------------------------------------------------- geometry

def _cells(seg):
    """(complete (H-1, W-1), area of each cell in voxels^2, unit normal of each cell)."""
    np = seg._np
    P, v = seg.xyz, seg.valid
    c = v[:-1, :-1] & v[:-1, 1:] & v[1:, :-1] & v[1:, 1:]
    p00, p01, p10, p11 = P[:-1, :-1], P[:-1, 1:], P[1:, :-1], P[1:, 1:]
    with np.errstate(invalid="ignore"):
        t1 = np.cross(p01 - p00, p11 - p00)
        t2 = np.cross(p11 - p00, p10 - p00)
        area = 0.5 * (np.linalg.norm(t1, axis=-1) + np.linalg.norm(t2, axis=-1))
        n = t1 + t2
        nn = np.linalg.norm(n, axis=-1)
        normal = n / np.where(nn > 0, nn, 1.0)[..., None]
    area = np.where(c, area, 0.0)
    c = c & (nn > 0)
    return c, area, normal


def _edges(seg):
    """(along columns (H, W-1), along rows (H-1, W)) edge length over the promised step; NaN where an end is a hole."""
    np = seg._np
    P, v = seg.xyz, seg.valid
    with np.errstate(invalid="ignore"):
        ec = np.linalg.norm(np.diff(P, axis=1), axis=-1) / seg.step[0]
        er = np.linalg.norm(np.diff(P, axis=0), axis=-1) / seg.step[1]
    ec[~(v[:, :-1] & v[:, 1:])] = np.nan
    er[~(v[:-1, :] & v[1:, :])] = np.nan
    return ec, er


def _pct(a, ps=(1, 5, 50, 95, 99), n=3):
    np = _np()
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    if not a.size:
        return None
    return {f"p{p}": round(float(v), n) for p, v in zip(ps, np.percentile(a, ps))}


def _cm2(vox2, um):
    return None if um is None else vox2 * (um * 1e-4) ** 2


def info(seg):
    """Size and area of the segment, as a dict."""
    np = seg._np
    c, area, _ = _cells(seg)
    a = float(area[c].sum())
    out = {"source": seg.source, "grid": list(seg.shape), "nodes_filled": int(seg.valid.sum()),
           "filled_share": round(float(seg.valid.mean()), 4), "complete_cells": int(c.sum()),
           "step_vox": [round(s, 4) for s in seg.step], "voxel_um": seg.voxel_um, "volume": seg.volume,
           "area_vox2": round(a, 1)}
    cm2 = _cm2(a, seg.voxel_um)
    out["area_cm2"] = None if cm2 is None else round(cm2, 3)
    out["area_mm2"] = None if cm2 is None else round(cm2 * 100, 1)
    if seg.valid.any():
        pts = seg.xyz[seg.valid]
        out["bbox_xyz"] = [[round(float(v), 1) for v in pts.min(0)], [round(float(v), 1) for v in pts.max(0)]]
    meta_area = seg.meta.get("area_vx2")
    if isinstance(meta_area, (int, float)) and meta_area > 0:
        out["meta_area_vox2"] = round(float(meta_area), 1)
        out["meta_area_ratio"] = round(a / float(meta_area), 4)
    return out


def stretch(seg):
    """How isometric the grid is: edge length, cell area and grid angle against what meta.json's scale promises."""
    np = seg._np
    ec, er = _edges(seg)
    c, area, _ = _cells(seg)
    ar = area / (seg.step[0] * seg.step[1])
    P = seg.xyz
    with np.errstate(invalid="ignore"):
        u = P[:-1, 1:] - P[:-1, :-1]
        w = P[1:, :-1] - P[:-1, :-1]
        cos = (u * w).sum(-1) / (np.linalg.norm(u, axis=-1) * np.linalg.norm(w, axis=-1))
        ang = np.degrees(np.arccos(np.clip(cos, -1, 1)))
    both = np.concatenate([ec[np.isfinite(ec)], er[np.isfinite(er)]])
    with np.errstate(divide="ignore"):
        logs = np.abs(np.log(both[both > 0])) if both.size else both
    return {"source": seg.source, "step_vox": [round(s, 4) for s in seg.step],
            "edge_columns": _pct(ec), "edge_rows": _pct(er), "cell_area": _pct(ar[c]),
            "grid_angle_deg": _pct(ang[c], n=1),
            "within_10pct": None if not both.size else round(float(((both > 1 / 1.1) & (both < 1.1)).mean()), 4),
            "within_25pct": None if not both.size else round(float(((both > 1 / 1.25) & (both < 1.25)).mean()), 4),
            "median_abs_log": None if not logs.size else round(float(np.median(logs)), 4)}


def _holes(valid):
    """Grid nodes that are holes inside the sheet: missing, and not joined to the grid's border through missing ones."""
    np = _np()
    miss = ~valid
    try:
        from scipy import ndimage
        lab, _ = ndimage.label(miss)
        edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
        return miss & ~np.isin(lab, edge[edge > 0]) & (lab > 0)
    except ImportError:
        pass
    out = np.zeros_like(miss)
    out[0], out[-1], out[:, 0], out[:, -1] = miss[0], miss[-1], miss[:, 0], miss[:, -1]
    while True:
        grow = out.copy()
        grow[1:] |= out[:-1]
        grow[:-1] |= out[1:]
        grow[:, 1:] |= out[:, :-1]
        grow[:, :-1] |= out[:, 1:]
        grow &= miss
        if (grow == out).all():
            break
        out = grow
    return miss & ~out


def check(seg, max_stretch=MAX_STRETCH, fold_deg=FOLD_DEG):
    """Holes, folds and over-stretched nodes: (report dict, {name: (H, W) bool mask})."""
    np = seg._np
    if not max_stretch > 1:
        raise VerifyError(f"--max-stretch must be above 1 (got {max_stretch})")
    if not 0 < fold_deg < 180:
        raise VerifyError(f"--fold-deg must be between 0 and 180 (got {fold_deg})")
    H, W = seg.shape
    holes = _holes(seg.valid)
    c, area, n = _cells(seg)
    lim = math.cos(math.radians(fold_deg))
    fold_cell = np.zeros_like(c)
    with np.errstate(invalid="ignore"):
        d = (n[:, 1:] * n[:, :-1]).sum(-1)
        f = c[:, 1:] & c[:, :-1] & (d < lim)
        fold_cell[:, 1:] |= f
        fold_cell[:, :-1] |= f
        d = (n[1:] * n[:-1]).sum(-1)
        f = c[1:] & c[:-1] & (d < lim)
        fold_cell[1:] |= f
        fold_cell[:-1] |= f
    folds = np.zeros((H, W), bool)
    for dr in (0, 1):
        for dc in (0, 1):
            folds[dr:H - 1 + dr, dc:W - 1 + dc] |= fold_cell
    folds &= seg.valid
    ec, er = _edges(seg)
    with np.errstate(invalid="ignore"):
        bc = (ec > max_stretch) | (ec < 1 / max_stretch)
        br = (er > max_stretch) | (er < 1 / max_stretch)
    bad = np.zeros((H, W), bool)
    bad[:, :-1] |= bc
    bad[:, 1:] |= bc
    bad[:-1] |= br
    bad[1:] |= br
    bad &= seg.valid
    filled = max(int(seg.valid.sum()), 1)
    span = int(seg.valid.sum() + holes.sum()) or 1
    rep = {"source": seg.source, "max_stretch": max_stretch, "fold_deg": fold_deg, "nodes_filled": int(seg.valid.sum())}
    cell_um2 = None if seg.voxel_um is None else seg.step[0] * seg.step[1] * seg.voxel_um ** 2
    for name, m, base in (("holes", holes, span), ("folds", folds, filled), ("stretched", bad, filled)):
        k = int(m.sum())
        rep[name] = {"nodes": k, "share": round(k / base, 4)}
        if cell_um2 is not None:
            rep[name]["area_mm2"] = round(k * cell_um2 * 1e-6, 2)
    rep["clean"] = all(rep[k]["nodes"] == 0 for k in ("holes", "folds", "stretched"))
    return rep, {"holes": holes, "folds": folds, "stretched": bad}


def facing(seg, umb):
    """Normals against the center line: share pointing away from it, and the turning sense along grid columns."""
    from . import stackcheck
    np = seg._np
    normals, _, ok, _ = stackcheck.grid_geometry(seg.xyz, seg.valid)
    P = seg.xyz
    cx, cy = umb.at(P[..., 2])
    rx, ry = P[..., 0] - cx, P[..., 1] - cy
    with np.errstate(invalid="ignore"):
        rad = np.hypot(rx, ry)
        out = (normals[..., 0] * rx + normals[..., 1] * ry) / np.where(rad > 0, rad, np.nan)
    use = ok & np.isfinite(out) & (rad > 0)
    n_use = int(use.sum())
    if not n_use:
        raise VerifyError(f"{seg.source}: no grid normal could be compared with the center line")
    away = float((out[use] > 0).mean())
    theta = np.arctan2(ry, rx)
    dth = np.angle(np.exp(1j * (theta[:, 1:] - theta[:, :-1])))
    pair = use[:, 1:] & use[:, :-1] & np.isfinite(dth)
    grows = float((dth[pair] > 0).mean()) if pair.any() else None
    zr = P[..., 2][seg.valid]
    beyond = float(((zr < umb.z.min()) | (zr > umb.z.max())).mean()) if zr.size else 0.0
    rep = {"source": seg.source, "centerline": umb.source, "nodes_compared": n_use,
           "normals_away_share": round(away, 4), "angle_grows_along_columns_share":
           None if grows is None else round(grows, 4), "median_radius_vox": round(float(np.median(rad[use])), 1),
           "outside_centerline_z_share": round(beyond, 4)}
    rep["normals"] = "away from the center" if away >= 0.9 else "toward the center" if away <= 0.1 else "mixed"
    if seg.volume and umb.volume and seg.volume not in str(umb.volume):
        rep["warning"] = (f"the segment is on volume {seg.volume} but the center line names {umb.volume}: "
                          "both must be in one volume's voxels")
    return rep


# ---------------------------------------------------------------- files

def write_obj(seg, path, stride=1):
    """Wavefront OBJ of the grid's complete cells (two triangles each), UVs from the grid position (0 to 1)."""
    np = seg._np
    if stride < 1:
        raise VerifyError(f"--stride must be 1 or more (got {stride})")
    xyz, valid = seg.xyz[::stride, ::stride], seg.valid[::stride, ::stride]
    H, W = valid.shape
    idx = np.full((H, W), -1, np.int64)
    idx[valid] = np.arange(1, int(valid.sum()) + 1)
    rows, cols = np.nonzero(valid)
    c = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & valid[1:, 1:]
    a, b, d, e = idx[:-1, :-1][c], idx[:-1, 1:][c], idx[1:, :-1][c], idx[1:, 1:][c]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="ascii") as fh:
        fh.write(f"# kit tifxyz obj from {seg.source}\n# grid {H} x {W}, stride {stride}, units: voxels\n")
        for p in xyz[valid]:
            fh.write(f"v {p[0]:.3f} {p[1]:.3f} {p[2]:.3f}\n")
        for r, q in zip(rows, cols):
            fh.write(f"vt {q / max(W - 1, 1):.6f} {1 - r / max(H - 1, 1):.6f}\n")
        for i, j, k, l in zip(a, b, d, e):
            fh.write(f"f {i}/{i} {k}/{k} {j}/{j}\nf {j}/{j} {k}/{k} {l}/{l}\n")
    return {"path": str(path), "vertices": int(valid.sum()), "triangles": int(2 * c.sum()), "stride": stride}


def write_png(path, rgb):
    """An 8-bit RGB PNG from an (H, W, 3) uint8 array, standard library only."""
    np = _np()
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[r].tobytes() for r in range(h))

    def chunk(t, data):
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return str(path)


COLORS = {"hole": (40, 44, 52), "folds": (235, 64, 52), "stretched": (240, 160, 40), "holes": (70, 130, 220)}


def shade(seg, masks=None, size=None):
    """(H, W, 3) uint8 picture: the sheet lit from the viewer's side, missing nodes dark, mask nodes colored."""
    from . import stackcheck
    np = seg._np
    normals, _, ok, _ = stackcheck.grid_geometry(seg.xyz, seg.valid)
    light = np.array([0.35, -0.45, 0.82])
    light /= np.linalg.norm(light)
    with np.errstate(invalid="ignore"):
        lam = np.abs((normals * light).sum(-1))
    g = np.where(ok, 60 + 180 * np.nan_to_num(lam), 0)
    img = np.repeat(g[..., None], 3, -1)
    img[~seg.valid] = COLORS["hole"]
    for name in ("holes", "stretched", "folds"):
        if masks and name in masks:
            img[masks[name]] = COLORS[name]
    return _resize(img.astype(np.uint8), size)


def _resize(img, size):
    """img with its longest side brought to about size pixels: every kth node, or each node repeated."""
    if size:
        H, W = img.shape[:2]
        k = max(1, int(math.ceil(max(H, W) / size)))
        if k > 1:
            img = img[::k, ::k]
        else:
            r = max(1, size // max(H, W))
            img = img.repeat(r, 0).repeat(r, 1)
    return img


# ---------------------------------------------------------------- chunks: the zarr chunks a mesh touches

CHUNK_WORKERS = 32
TRIES = 5                 # attempts per key on 429, 5xx or a dropped connection
MAX_REQUESTS = 20000
SPARE_BYTES = 1 << 30     # --fetch keeps 1 GiB free, as kit fetch does
_ROOT_META = (".zattrs", ".zgroup", ".zmetadata", "zarr.json")


class ZarrSource:
    """A zarr folder on disk or behind a URL (https://, or s3:// on the open-data bucket), read key by key."""

    def __init__(self, root, opener=None):
        from . import stackcheck
        self.root = str(root).rstrip("/")
        self.remote = stackcheck._is_url(self.root)
        self.base = stackcheck._https(self.root) if self.remote else None
        if opener is None:
            import urllib.request
            opener = urllib.request.urlopen
        self.opener = opener

    def _request(self, key, method="GET", tries=TRIES, sleep=None):
        import time
        import urllib.error
        import urllib.request
        sleep = sleep or time.sleep
        for attempt in range(tries):
            req = urllib.request.Request(f"{self.base}/{key}", method=method, headers={"User-Agent": "kit-tifxyz"})
            try:
                with self.opener(req, timeout=60) as resp:
                    return resp.read() if method == "GET" else int(resp.headers.get("Content-Length") or 0)
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 404):     # S3 answers 403 for a missing key in a bucket it will not list
                    return None
                if not (exc.code == 429 or exc.code >= 500) or attempt == tries - 1:
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == tries - 1:
                    raise
            sleep(min(8.0, 0.5 * 2 ** attempt))   # 429, 5xx and dropped connections are asked again

    def read(self, key):
        """The bytes of one key, or None when it is not there."""
        if self.remote:
            return self._request(key)
        p = Path(self.root) / key
        return p.read_bytes() if p.is_file() else None

    def size(self, key):
        """The size in bytes of one key, or None when it is not there (zarr reads a missing chunk as its fill value)."""
        if self.remote:
            return self._request(key, "HEAD")
        p = Path(self.root) / key
        return p.stat().st_size if p.is_file() else None

    def json(self, key):
        raw = self.read(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise VerifyError(f"{self.root}/{key} is not JSON: {exc}") from None


def _multiscales(attrs):
    ms = (attrs or {}).get("multiscales") or ((attrs or {}).get("ome") or {}).get("multiscales")
    return ms[0] if ms else None


def _scale_of(dataset):
    for t in dataset.get("coordinateTransformations") or []:
        if t.get("type") == "scale" and t.get("scale"):
            return [float(v) for v in t["scale"]]
    return None


def zarr_level(src, level=0):
    """One array of a zarr or OME-Zarr volume, as a dict: path, shape, chunks (the stored unit: the shard for a sharded
    v3 array), key scheme, the metadata keys to copy, and its scale against level 0 along z, y, x."""
    root2, root3 = src.json(".zattrs"), src.json("zarr.json")
    if root3 is not None and root3.get("node_type") == "array" or src.json(".zarray") is not None:
        paths, factor = [""], [1.0, 1.0, 1.0]       # a plain array, not a pyramid: --level does not apply
        if level:
            raise VerifyError(f"{src.root} is one array, not a multiscale pyramid: leave out --level")
    else:
        ms = _multiscales((root3 or {}).get("attributes") if root3 is not None else root2)
        if not ms:
            raise VerifyError(f"{src.root}: no .zattrs, zarr.json or multiscales found: is this a zarr volume?")
        ds = ms.get("datasets") or []
        if not 0 <= level < len(ds):
            raise VerifyError(f"{src.root} has levels 0 to {len(ds) - 1}; --level {level} is not one of them")
        paths = [d["path"] for d in ds]
        s0, sl = _scale_of(ds[0]), _scale_of(ds[level])
        factor = [b / a for a, b in zip(s0[-3:], sl[-3:])] if s0 and sl else [2.0 ** level] * 3
    path = paths[level] if paths != [""] else ""
    pre = f"{path}/" if path else ""
    m2, m3 = src.json(pre + ".zarray"), src.json(pre + "zarr.json")
    if m2 is not None:
        sep = m2.get("dimension_separator") or "."
        out = {"format": 2, "shape": m2["shape"], "chunks": m2["chunks"], "dtype": m2.get("dtype"),
               "prefix": pre, "sep": sep, "meta_key": pre + ".zarray"}
    elif m3 is not None and m3.get("node_type") == "array":
        enc = m3.get("chunk_key_encoding") or {"name": "default"}
        conf = enc.get("configuration") or {}
        sep = conf.get("separator") or ("/" if enc.get("name") == "default" else ".")
        out = {"format": 3, "shape": m3["shape"], "chunks": m3["chunk_grid"]["configuration"]["chunk_shape"],
               "dtype": m3.get("data_type"), "prefix": pre + ("c/" if enc.get("name") == "default" else ""),
               "sep": sep, "meta_key": pre + "zarr.json"}
        if any(c.get("name") == "sharding_indexed" for c in m3.get("codecs") or []):
            out["sharded"] = True
    else:
        raise VerifyError(f"{src.root}: no array metadata at level {level} ({pre or 'the root'})")
    if len(out["shape"]) != 3:
        raise VerifyError(f"{src.root}: level {level} has {len(out['shape'])} axes; a scan volume has 3 (z, y, x)")
    out.update(level=level, path=path, factor=factor, levels=paths)
    return out


def chunk_key(arr, idx):
    return arr["prefix"] + arr["sep"].join(str(int(i)) for i in idx)


def touched_chunks(seg, arr, margin=0.0):
    """(sorted (N, 3) int array of z, y, x chunk indices whose box comes within margin voxels of the sheet, number of
    nodes outside the array). The sheet between nodes is covered by adding half a grid cell's diagonal."""
    np = seg._np
    if margin < 0:
        raise VerifyError(f"--margin must be 0 or more voxels (got {margin})")
    pts = seg.xyz[seg.valid][:, ::-1]                     # x, y, z -> z, y, x
    f = np.asarray(arr["factor"], float)
    c = np.asarray(arr["chunks"], float)
    n = np.ceil(np.asarray(arr["shape"], float) / c).astype(np.int64)
    r = (margin + 0.5 * math.hypot(*seg.step)) / f
    q = pts / f
    inside = ((q + r >= 0) & (q - r < np.asarray(arr["shape"], float))).all(1)
    q = q[inside]
    lo = np.clip(np.floor((q - r) / c), 0, n - 1).astype(np.int64)
    hi = np.clip(np.floor((q + r) / c), 0, n - 1).astype(np.int64)
    span = int((hi - lo).max()) if len(lo) else 0
    found = []
    rng = range(span + 1)
    for dz in rng:
        for dy in rng:
            for dx in rng:
                o = np.array([dz, dy, dx])
                idx = lo + o
                keep = (idx <= hi).all(1)
                found.append(idx[keep])
    if not found or not sum(len(a) for a in found):
        return np.zeros((0, 3), np.int64), int((~inside).sum())
    return np.unique(np.concatenate(found), axis=0), int((~inside).sum())


def _sizes(src, keys, workers=CHUNK_WORKERS):
    import concurrent.futures
    if not src.remote or len(keys) < 2:
        return [src.size(k) for k in keys]
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(src.size, keys))


def chunks(seg, volume, level=0, margin=0.0, max_requests=MAX_REQUESTS, src=None):
    """The chunks of `volume` that the segment touches, with their stored sizes: a dict."""
    src = src or ZarrSource(volume)
    arr = zarr_level(src, level)
    idx, outside = touched_chunks(seg, arr, margin)
    keys = [chunk_key(arr, i) for i in idx]
    asked = keys[:max(0, max_requests)]
    sizes = _sizes(src, asked)
    present = [s for s in sizes if s is not None]
    grid = [int(math.ceil(s / c)) for s, c in zip(arr["shape"], arr["chunks"])]
    rep = {"segment": seg.source, "volume": src.root, "level": level, "level_path": arr["path"],
           "level_factor_zyx": [round(v, 4) for v in arr["factor"]], "shape_zyx": arr["shape"],
           "chunk_zyx": arr["chunks"], "sharded": bool(arr.get("sharded")), "margin_vox": margin,
           "chunks": len(keys), "chunks_in_volume": math.prod(grid),
           "sized": len(asked), "present": len(present), "absent": len(asked) - len(present),
           "bytes": int(sum(present)), "nodes_outside_volume": outside}
    if len(asked) < len(keys):
        rep["note"] = (f"sizes asked for the first {len(asked)} of {len(keys)} chunks (--max-requests); bytes covers "
                       "those only")
    if seg.volume and seg.volume not in src.root:
        rep["warning"] = (f"the segment is on volume {seg.volume}, which the volume URL does not name: the mesh's "
                          "voxels must be this volume's")
    return rep, keys, sizes


def fetch_chunks(src, arr_levels, keys, sizes, dest, workers=CHUNK_WORKERS):
    """Copy the volume's metadata (root and every level) and the given chunks into dest, keeping the key layout, so
    a zarr reader opens dest as the same volume with only those chunks filled. Returns (written, skipped, bytes)."""
    import concurrent.futures
    import shutil
    dest = Path(dest)
    need = sum(s for k, s in zip(keys, sizes) if s is not None and not (dest / k).is_file())
    dest.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(dest).free
    if need + SPARE_BYTES > free:
        raise VerifyError(f"--fetch needs {need / 1e9:.2f} GB plus 1 GB spare in {dest}; {free / 1e9:.2f} GB free")
    meta = list(_ROOT_META)
    for path in arr_levels:
        pre = f"{path}/" if path else ""
        meta += [pre + ".zarray", pre + ".zattrs", pre + "zarr.json"]
    for k in dict.fromkeys(meta):
        raw = src.read(k)
        if raw is not None:
            (dest / k).parent.mkdir(parents=True, exist_ok=True)
            (dest / k).write_bytes(raw)

    def one(pair):
        k, s = pair
        out = dest / k
        if s is None:
            return 0, 0
        if out.is_file() and out.stat().st_size == s:
            return 0, 1
        raw = src.read(k)
        if raw is None:
            return 0, 0
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + ".part")
        tmp.write_bytes(raw)
        tmp.replace(out)
        return len(raw), 0

    with concurrent.futures.ThreadPoolExecutor(workers if src.remote else 1) as ex:
        done = list(ex.map(one, zip(keys, sizes)))
    written = sum(1 for b, _ in done if b)
    return written, sum(s for _, s in done), sum(b for b, _ in done)


# ---------------------------------------------------------------- diff: two versions of one segment

DIFF_TOL = 1.0
DIFF_SAMPLE = 2000


def _near(a_pts, b_pts, d):
    """For each row of b_pts: True when some row of a_pts lies in the same or a neighboring cube of side d (so a
    False row is more than d voxels from every point of a_pts; a True one is within 2 sqrt(3) d)."""
    np = _np()
    if not len(a_pts):
        return np.zeros(len(b_pts), bool)
    ka = np.floor(a_pts / d).astype(np.int64)
    lo = ka.min(0) - 1
    span = ka.max(0) - lo + 2
    lin = lambda k: ((k[:, 0] - lo[0]) * span[1] + (k[:, 1] - lo[1])) * span[2] + (k[:, 2] - lo[2])  # noqa: E731
    have = np.unique(lin(ka))
    kb = np.floor(b_pts / d).astype(np.int64)
    out = np.zeros(len(b_pts), bool)
    for dz in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                k = kb + np.array([dz, dy, dx])
                ok = ((k >= lo) & (k < lo + span)).all(1)
                key = lin(k[ok])
                pos = np.searchsorted(have, key)
                hit = np.zeros(len(key), bool)
                inb = pos < len(have)
                hit[inb] = have[pos[inb]] == key[inb]
                out[np.flatnonzero(ok)[hit]] = True
    return out


def _nearest(a_pts, q, block=4):
    """Distance from each row of q to the nearest row of a_pts, by brute force in float32 blocks."""
    np = _np()
    a = a_pts.astype(np.float32)
    out = np.empty(len(q))
    for i in range(0, len(q), block):
        d = ((a[None, :, :] - q[i:i + block, None, :].astype(np.float32)) ** 2).sum(-1)
        out[i:i + block] = np.sqrt(d.min(1))
    return out


def diff(a, b, tol=DIFF_TOL, sample=DIFF_SAMPLE, seed=0):
    """Compare two versions of one segment: (report dict, {name: (H, W) bool mask on b's grid} for a picture).

    Same grid shape: node by node (added, removed, moved more than tol voxels, and the displacement percentiles).
    Different shapes: by position, node to node: b's nodes with no node of a within a cube neighborhood of side
    tol x the grid step count as added, a's with none of b's as removed, and the nearest-node distance of a sample."""
    np = a._np
    if not tol > 0:
        raise VerifyError(f"--tol must be above 0 voxels (got {tol})")
    ia, ib = info(a), info(b)
    rep = {"a": a.source, "b": b.source, "grid_a": list(a.shape), "grid_b": list(b.shape),
           "area_a_vox2": ia["area_vox2"], "area_b_vox2": ib["area_vox2"],
           "area_change_vox2": round(ib["area_vox2"] - ia["area_vox2"], 1), "tol_vox": tol}
    if ia.get("area_mm2") is not None and ib.get("area_mm2") is not None:
        rep.update(area_a_mm2=ia["area_mm2"], area_b_mm2=ib["area_mm2"],
                   area_change_mm2=round(ib["area_mm2"] - ia["area_mm2"], 1))
    if a.volume and b.volume and a.volume != b.volume:
        rep["warning"] = f"a is on volume {a.volume} and b on {b.volume}: positions are not comparable"
    masks = {}
    if a.shape == b.shape:
        both = a.valid & b.valid
        added, removed = b.valid & ~a.valid, a.valid & ~b.valid
        disp = np.linalg.norm(b.xyz - a.xyz, axis=-1)
        moved = both & (disp > tol)
        rep.update(method="same grid: node by node", nodes_a=int(a.valid.sum()), nodes_b=int(b.valid.sum()),
                   added=int(added.sum()), removed=int(removed.sum()), moved=int(moved.sum()),
                   unchanged=int((both & ~moved).sum()), displacement_vox=_pct(disp[both], (50, 90, 99, 100), 2))
        masks = {"added": added, "removed": removed, "moved": moved}
    else:
        step = max(min(a.step + b.step), 1e-9)
        d = tol * step
        pa, pb = a.xyz[a.valid], b.xyz[b.valid]
        near_b, near_a = _near(pa, pb, d), _near(pb, pa, d)
        rng = np.random.default_rng(seed)
        q = pb[rng.choice(len(pb), min(sample, len(pb)), replace=False)] if len(pb) else pb
        dist = _nearest(pa, q) if len(pa) and len(q) else np.zeros(0)
        added_grid = np.zeros(b.shape, bool)
        added_grid[b.valid] = ~near_b
        rep.update(method=f"different grids: by position (a cube neighborhood of {d:g} voxels, {tol:g} grid steps)",
                   nodes_a=int(len(pa)), nodes_b=int(len(pb)), added=int((~near_b).sum()),
                   removed=int((~near_a).sum()), sampled=int(len(q)),
                   nearest_node_vox=_pct(dist, (50, 90, 99, 100), 2))
        masks = {"added": added_grid}
    for k in ("added", "removed"):
        cell_um2 = None if b.voxel_um is None else (b.step[0] * b.step[1] * b.voxel_um ** 2)
        if cell_um2 is not None:
            rep[f"{k}_mm2"] = round(rep[k] * cell_um2 * 1e-6, 2)
    rep["same"] = rep["added"] == 0 and rep["removed"] == 0 and rep.get("moved", 0) == 0
    return rep, masks


DIFF_COLORS = {"added": (60, 180, 90), "removed": (220, 60, 60), "moved": (240, 160, 40)}


def diff_picture(b, masks, size=1200):
    """b shaded, with added nodes green, removed red (at their grid places) and moved orange."""
    img = shade(b, None, None)
    for name in ("moved", "removed", "added"):
        if name in masks:
            img[masks[name]] = DIFF_COLORS[name]
    return b._np.ascontiguousarray(_resize(img, size))


# ---------------------------------------------------------------- text

def format_info(r):
    um = f"{r['voxel_um']} um voxels" if r["voxel_um"] else "voxel size unknown (pass --voxel-um)"
    lines = [f"{r['source']}",
             f"  grid       {r['grid'][0]} x {r['grid'][1]} nodes, {r['filled_share'] * 100:.1f} % filled, "
             f"step {r['step_vox'][0]:g} x {r['step_vox'][1]:g} voxels, {um}"]
    if r["area_cm2"] is not None:
        lines.append(f"  area       {r['area_cm2']:.2f} cm2 ({r['area_mm2']:.0f} mm2), {r['area_vox2']:.0f} voxels^2")
    else:
        lines.append(f"  area       {r['area_vox2']:.0f} voxels^2")
    if "meta_area_ratio" in r:
        lines.append(f"  meta.json  area_vx2 {r['meta_area_vox2']:.0f}: ours is {r['meta_area_ratio']:.4f} of it")
    if r.get("bbox_xyz"):
        lo, hi = r["bbox_xyz"]
        lines.append(f"  bounds     x {lo[0]:.0f} to {hi[0]:.0f}, y {lo[1]:.0f} to {hi[1]:.0f}, z {lo[2]:.0f} to {hi[2]:.0f}")
    if r.get("volume"):
        lines.append(f"  volume     {r['volume']}")
    return "\n".join(lines)


def format_stretch(r):
    def row(name, d, unit=""):
        if not d:
            return f"  {name:<12} none"
        return (f"  {name:<12} median {d['p50']:g}{unit}, 5 to 95 % {d['p5']:g} to {d['p95']:g}{unit}, "
                f"1 to 99 % {d['p1']:g} to {d['p99']:g}{unit}")
    lines = [r["source"], f"  promised step {r['step_vox'][0]:g} x {r['step_vox'][1]:g} voxels (1.0 below is exact)",
             row("edge, cols", r["edge_columns"]), row("edge, rows", r["edge_rows"]),
             row("cell area", r["cell_area"]), row("grid angle", r["grid_angle_deg"], " deg")]
    if r["within_10pct"] is not None:
        lines.append(f"  edges within 10 % of the step: {r['within_10pct'] * 100:.1f} %, within 25 %: "
                     f"{r['within_25pct'] * 100:.1f} %")
    return "\n".join(lines)


def format_check(r):
    lines = [r["source"]]
    for name, what in (("holes", "missing nodes inside the sheet"),
                       ("folds", f"nodes where the sheet turns by more than {r['fold_deg']:g} deg between cells"),
                       ("stretched", f"nodes with an edge over {r['max_stretch']:g}x too long or short")):
        d = r[name]
        mm = f", {d['area_mm2']} mm2" if "area_mm2" in d else ""
        word = "ok  " if d["nodes"] == 0 else "flag"
        lines.append(f"  {word} {name:<9} {d['nodes']} nodes ({d['share'] * 100:.2f} %{mm}): {what}")
    lines.append("  clean" if r["clean"] else "  not clean: see the flags above")
    return "\n".join(lines)


def format_facing(r):
    g = r["angle_grows_along_columns_share"]
    lines = [r["source"], f"  center line {r['centerline']}",
             f"  normals     {r['normals']}: {r['normals_away_share'] * 100:.1f} % of {r['nodes_compared']} point away "
             f"from the center (median radius {r['median_radius_vox']:g} voxels)"]
    if g is not None:
        lines.append(f"  columns     the angle atan2(y - yc, x - xc) grows along columns at {g * 100:.1f} % of steps")
    if r["outside_centerline_z_share"] > 0:
        lines.append(f"  note        {r['outside_centerline_z_share'] * 100:.1f} % of nodes lie above or below the "
                     "center line's points, where it is held constant")
    if r.get("warning"):
        lines.append(f"  warning     {r['warning']}")
    return "\n".join(lines)


def _human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000.0


def format_chunks(r):
    f = r["level_factor_zyx"]
    res = "full resolution" if f[0] == 1 else f"1/{f[0]:g} of level 0"
    lines = [f"{r['segment']}", f"  volume     {r['volume']}, level {r['level']} ({res}), "
             f"chunks {' x '.join(str(c) for c in r['chunk_zyx'])} (z, y, x){', sharded' if r['sharded'] else ''}",
             f"  touched    {r['chunks']} of {r['chunks_in_volume']} chunks within {r['margin_vox']:g} voxels of "
             "the sheet",
             f"  stored     {r['present']} present, {_human(r['bytes'])}; {r['absent']} absent (read as the fill "
             "value)"]
    if r.get("note"):
        lines.append(f"  note       {r['note']}")
    if r["nodes_outside_volume"]:
        lines.append(f"  outside    {r['nodes_outside_volume']} nodes lie outside the volume's shape")
    if r.get("warning"):
        lines.append(f"  warning    {r['warning']}")
    if r.get("fetched"):
        x = r["fetched"]
        lines.append(f"  fetched    {x['written']} chunks ({_human(x['bytes'])}) into {x['dest']}, {x['skipped']} "
                     "already there; every other chunk reads as the fill value")
    return "\n".join(lines)


def format_diff(r):
    mm = lambda k: f" ({r[k + '_mm2']} mm2)" if k + "_mm2" in r else ""  # noqa: E731
    lines = [f"a  {r['a']}", f"b  {r['b']}", f"  method     {r['method']}"]
    if "area_change_mm2" in r:
        lines.append(f"  area       {r['area_a_mm2']:.0f} -> {r['area_b_mm2']:.0f} mm2 "
                     f"({r['area_change_mm2']:+.0f} mm2)")
    else:
        lines.append(f"  area       {r['area_a_vox2']:.0f} -> {r['area_b_vox2']:.0f} voxels^2")
    lines.append(f"  nodes      {r['nodes_a']} -> {r['nodes_b']}: {r['added']} added{mm('added')}, "
                 f"{r['removed']} removed{mm('removed')}")
    if "moved" in r:
        d = r["displacement_vox"]
        lines.append(f"  moved      {r['moved']} nodes by more than {r['tol_vox']:g} voxels; {r['unchanged']} "
                     "unchanged")
        if d:
            lines.append(f"  shift      median {d['p50']:g}, 90 % {d['p90']:g}, 99 % {d['p99']:g}, "
                         f"max {d['p100']:g} voxels")
    elif r.get("nearest_node_vox"):
        d = r["nearest_node_vox"]
        lines.append(f"  distance   from {r['sampled']} of b's nodes to a's nearest node: median {d['p50']:g}, 90 % "
                     f"{d['p90']:g}, 99 % {d['p99']:g}, max {d['p100']:g} voxels")
    if r.get("warning"):
        lines.append(f"  warning    {r['warning']}")
    lines.append("  same" if r["same"] else "  changed")
    return "\n".join(lines)


# ---------------------------------------------------------------- command line

def build_parser(p):
    actions = p.add_subparsers(dest="action", required=True)

    def common(a):
        a.add_argument("segment", help="tifxyz folder, or its https:// or s3:// URL on the open-data bucket")
        a.add_argument("--voxel-um", type=float, help="voxel size (default: the folder name's -N.NNNum.tifxyz)")
        a.add_argument("--cache", default=DEFAULT_CACHE, help="where bucket segments are kept")
        a.add_argument("--json", action="store_true")

    common(actions.add_parser("info", help="area in cm2 and mm2, grid size, filled share, bounds"))
    common(actions.add_parser("stretch", help="how isometric the grid is: edge length, cell area, grid angle"))
    a = actions.add_parser("check", help="holes, folds and over-stretched nodes, with an optional picture")
    common(a)
    a.add_argument("--max-stretch", type=float, default=MAX_STRETCH, help="flag an edge this many times too long or short")
    a.add_argument("--fold-deg", type=float, default=FOLD_DEG, help="flag neighboring cells whose normals differ by more")
    a.add_argument("--png", help="write a picture of the flags here")
    a = actions.add_parser("obj", help="write a Wavefront OBJ with UVs")
    common(a)
    a.add_argument("out", help="the .obj file to write")
    a.add_argument("--stride", type=int, default=1, help="keep every Nth grid row and column")
    a = actions.add_parser("preview", help="write a shaded PNG of the sheet")
    common(a)
    a.add_argument("out", help="the .png file to write")
    a.add_argument("--size", type=int, default=1200, help="longest side in pixels (0 keeps one pixel per node)")
    a = actions.add_parser("facing", help="do the grid normals point toward or away from the center line?")
    common(a)
    a.add_argument("--umbilicus", required=True, help="center line JSON (path or URL) in the segment's volume")
    a = actions.add_parser("chunks", help="the zarr chunks of a volume the segment touches: count and bytes, "
                                          "and --fetch to download only those")
    common(a)
    a.add_argument("volume", help="the volume's zarr folder or URL (the one the mesh's voxels are in)")
    a.add_argument("--level", type=int, default=0, help="pyramid level (0 is full resolution)")
    a.add_argument("--margin", type=float, default=0.0, help="also take chunks this many voxels (of level 0) "
                                                             "from the sheet")
    a.add_argument("--max-requests", type=int, default=MAX_REQUESTS, help="size at most this many chunks")
    a.add_argument("--fetch", metavar="DEST", help="copy the metadata and the touched chunks into this folder")
    a = actions.add_parser("diff", help="compare two versions of a segment on one volume")
    a.add_argument("segment", help="version a: tifxyz folder or bucket URL")
    a.add_argument("other", help="version b: tifxyz folder or bucket URL")
    a.add_argument("--voxel-um", type=float, help="voxel size (default: the folder name's -N.NNNum.tifxyz)")
    a.add_argument("--cache", default=DEFAULT_CACHE, help="where bucket segments are kept")
    a.add_argument("--tol", type=float, default=DIFF_TOL, help="a node moved or new beyond this (voxels on one "
                                                               "grid, grid steps across grids)")
    a.add_argument("--png", help="write a picture of b with the changes colored")
    a.add_argument("--json", action="store_true")
    return p


def run(args):
    seg = load(args.segment, args.cache, args.voxel_um)
    if args.action == "info":
        r = info(seg)
        text = format_info(r)
    elif args.action == "stretch":
        r = stretch(seg)
        text = format_stretch(r)
    elif args.action == "check":
        r, masks = check(seg, args.max_stretch, args.fold_deg)
        if args.png:
            r["png"] = write_png(args.png, shade(seg, masks, 1200))
        text = format_check(r) + (f"\n  picture   {r['png']}" if args.png else "")
    elif args.action == "obj":
        r = write_obj(seg, args.out, args.stride)
        text = f"wrote {r['path']}: {r['vertices']} vertices, {r['triangles']} triangles (stride {r['stride']})"
    elif args.action == "preview":
        img = shade(seg, None, args.size or None)
        r = {"path": write_png(args.out, img), "size": [int(img.shape[1]), int(img.shape[0])]}
        text = f"wrote {r['path']} ({r['size'][0]} x {r['size'][1]} px)"
    elif args.action == "chunks":
        src = ZarrSource(args.volume)
        r, keys, sizes = chunks(seg, args.volume, args.level, args.margin, args.max_requests, src)
        if args.fetch:
            if len(sizes) < len(keys):
                raise VerifyError(f"--fetch needs every chunk sized: {len(keys)} chunks, --max-requests "
                                  f"{args.max_requests}; raise it to {len(keys)} or more")
            arr = zarr_level(src, args.level)
            w, sk, b = fetch_chunks(src, arr["levels"], keys, sizes, args.fetch)
            r["fetched"] = {"dest": str(args.fetch), "written": w, "skipped": sk, "bytes": b}
        text = format_chunks(r)
    elif args.action == "diff":
        other = load(args.other, args.cache, args.voxel_um)
        r, masks = diff(seg, other, args.tol)
        if args.png:
            r["png"] = write_png(args.png, diff_picture(other, masks))
        text = format_diff(r) + (f"\n  picture    {r['png']}" if args.png else "")
    else:
        from . import stackcheck
        r = facing(seg, stackcheck.load_umbilicus(args.umbilicus))
        text = format_facing(r)
    print(json.dumps(r, indent=1) if args.json else text)
    return 1 if args.action == "check" and not r["clean"] else 0


def cmd_tifxyz(args):
    """python -m kit tifxyz ACTION SEGMENT: exit 0 when done (check: when clean), 1 when check flags, 2 on bad input."""
    try:
        return run(args)
    except VerifyError as exc:
        print(f"kit tifxyz: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"kit tifxyz could not read or write a file: {exc}", file=sys.stderr)
        return 2


def main(argv=None):
    p = build_parser(argparse.ArgumentParser(prog="python -m kit.tifxyz", description=__doc__.split("\n\n")[0]))
    return cmd_tifxyz(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
