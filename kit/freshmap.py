"""kit freshmap: map where a scroll's predicted papyrus lies away from every surface already made.

Tracing time is best spent on papyrus nobody has traced yet. Asking "is this new trace on fresh papyrus?" one
candidate at a time comes after the work of making it. This tool asks once per scroll: of all the papyrus the
organizers' m7 surface prediction shows, which parts does no listed surface come near, and where are they?

  python -m kit.freshmap index SRC [SRC ...] --cache DIR [--json]
  python -m kit.freshmap build --scroll S --read SRC [SRC ...] [--traced SRC ...] --out DIR
                               [--level 2] [--fresh-vox 20] [--sum-level 5] [--z L0:L1] [--jobs 4]
                               [--volume URL_OR_DIR] [--frame SCAN] [--voxel-um UM] [--umbilicus JSON]
                               [--boxes JSON] [--targets 25]
  python -m kit.freshmap summarise DIR [--targets 25] [--umbilicus JSON]
  python -m kit.freshmap show DIR [--json]
  python -m kit.freshmap query DIR MESH [MESH ...] [--json]

SRC is a tifxyz folder (x.tif, y.tif, z.tif in level-0 voxels), a folder holding such folders at any depth, or a
.tar of them; from a tar only x.tif, y.tif, z.tif and meta.json are taken (never maps or renders), into --cache
(default OUT/cache). A mesh's name is its folder's name. The two layers are yours to fill: `--read` for surfaces
already rendered and read, `--traced` for traced surfaces not yet read (both may be the same published segments).

How a map is made:
1. Papyrus: the scroll's m7 surface prediction (the public one for scrolls in M7_PUBLIC, else --volume) at --level
   (default 2, 4 level-0 voxels a side, so neighbouring sheets about 21 level-0 voxels apart stay apart), above 0.
   Each papyrus voxel stands for an area: its exposed faces (6-neighbours that are not papyrus, inside the same
   192-voxel chunk) times the level voxel's face area, divided by 2 (a sheet has two sides) and by 4/pi (the mean
   of |nx| + |ny| when sheet normals lie evenly spread in the horizontal plane, as a rolled scroll's point about
   radially; summary.json's faces_by_axis shows how far the z faces break that). This is an estimate: sheets that
   touch at the prediction's threshold lose their shared faces and count low, and a steep sheet counts high.
2. Covered: each --read and --traced mesh is densified to half a level voxel and rasterised into level voxels. A
   papyrus voxel is READ when its centre lies within --fresh-vox level-0 voxels (default 20, about one sheet pitch)
   of a read voxel's centre, by an exact Euclidean distance transform; else TRACED when within that of a traced
   voxel; else BOXED when inside one of the --boxes regions (areas you want left alone); else FRESH.
3. Sums: area per class on a coarse grid (--sum-level, default 5, 32 level-0 voxels a side), and per band (z), angle
   sector and radius ring about a centre line (--umbilicus, else the area-weighted centroid of the papyrus per
   coarse z layer, smoothed).
4. Targets: the --targets (band, sector, ring) bins with the most thick FRESH area, each with its class areas and the
   level-0 box of its fresh cells. Angles count from +x toward +y in the scan's voxel frame.

Reads only geometry and the m7 prediction; never CT and never an ink map. A FRESH cell is where m7 predicts papyrus
that no listed surface comes near: model output about geometry, not evidence of ink, of text, or of a traceable
sheet. The map is only as complete as the surfaces you list: a surface left out shows as FRESH.

`query` measures meshes against a built map exactly: the share of each mesh's area within --fresh-vox of the map's
read or traced voxels, and the share seated on papyrus (within one level voxel of m7), so you can ask whether a new
trace lands on fresh papyrus.

Outputs in DIR: summary.json (inputs, totals, per band, sector and ring, targets), grid.npz (the coarse class
areas), occ-read.bits and occ-traced.bits (the rasterised level voxels, one bit each, for query; with their .json
shapes), unrolled.png (z down, angle across) and side.png (z down, radius across), both coloured by class. numpy,
scipy (distance transform, labels), tifffile, numcodecs. No GPU.
"""

import argparse
import hashlib
import json
import math
import os
import struct
import sys
import tarfile
import time
import urllib.request
import zlib
from pathlib import Path

VERSION = 1
LEVEL = 2
SUM_LEVEL = 5
FRESH_VOX = 20.0          # level-0 voxels: about one sheet pitch
PROJ = 4 / math.pi        # mean |nx| + |ny| for normals spread evenly in the horizontal plane (papyrus normals of a
                          # rolled scroll point about radially); faces_by_axis in summary.json checks the assumption
TARGETS = 25
SECTORS = 16
RING_MM = 2.0
BAND_L0 = 1024
CLASSES = ("read", "traced", "boxed", "fresh")
THICK_L0 = 96             # level-0 voxels of z a FRESH run needs to count as thick (3 coarse cells at level 5)
QUERY_TILE = 128          # level voxels: query reads the occupancy a tile at a time
LONG_CELL = 4.0           # cells with an edge over 4 times the mesh's median cell edge are left out of the raster
MESH_FILES = ("x.tif", "y.tif", "z.tif", "meta.json")
RETRIES = 5
OPEN = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
RULE = {"version": VERSION, "papyrus": "m7 > 0", "area": "exposed faces / 2 / (4 / pi) x face area",
        "fresh_vox_l0": FRESH_VOX, "classes_in_order": list(CLASSES), "targets": "(band, sector, ring) bins by thick FRESH area (FRESH-led coarse cells in z runs of thick_l0)",
        "boxes": "level-0 boxes from --boxes (regions to leave alone)"}
# Public m7 surface predictions (scan id of the prediction's frame) for scrolls this tool was tried on; any other
# scroll takes --volume and --frame.
M7_PUBLIC = {"PHerc0343": "20250521140437"}


class FreshMapError(ValueError):
    pass


def _np():
    import numpy
    return numpy


# ------------------------------------------------------------------ meshes

GENERIC = {"snap", "mesh", "follow", "follow_trim", "seat", "trace.tifxyz", "raw", "filled", "surface"}
CONTROLS = {"sham", "sham_trim"}     # displaced control copies of a surface: never a surface of their own


def mesh_name(folder):
    """A mesh's name: its folder's name, or the nearest ancestor's when the folder has a generic name (seat/NAME/snap
    is NAME); None for a displaced control copy (sham, sham_trim)."""
    parts = Path(folder).parts
    if any(q in CONTROLS for q in parts):
        return None
    for q in reversed(parts):
        if q not in GENERIC:
            return q
    return parts[-1]


def _walk(root):
    out = []
    for r, dirs, files in os.walk(root):
        dirs.sort()
        if {"x.tif", "y.tif", "z.tif"} <= set(files):
            n = mesh_name(Path(r).relative_to(root.parent) if Path(r) != root else Path(r))
            if n:
                out.append((n, Path(r)))
    return out


def find_meshes(srcs, cache):
    """[(name, folder)] of every tifxyz folder under srcs (folders, or tars unpacked into cache, mesh files only);
    displaced control copies are left out."""
    out, cache = [], Path(cache)
    for s in srcs:
        s = Path(s)
        if s.is_file() and (s.suffix == ".tar" or s.name.endswith((".tar.gz", ".tgz"))):
            out += _walk(unpack(s, cache))
        elif s.is_dir():
            out += _walk(s)
        else:
            raise FreshMapError(f"{s}: not a folder or a tar")
    return out


def unpack(tar, cache, dest=None):
    """Mesh files (x.tif, y.tif, z.tif, meta.json) of a tar, unpacked once into a folder of cache; the folder."""
    tar = Path(tar)
    if dest is None:
        h = hashlib.sha256(str(tar.resolve()).encode() + str(tar.stat().st_size).encode()).hexdigest()[:12]
        dest = Path(cache) / f"{tar.name}-{h}"
    dest = Path(dest)
    done = dest / ".done"
    if not done.exists():
        with tarfile.open(tar) as t:
            for m in t:
                name = Path(m.name)
                if not m.isfile() or name.name not in MESH_FILES or ".." in name.parts or name.is_absolute():
                    continue
                q = dest / name
                q.parent.mkdir(parents=True, exist_ok=True)
                q.write_bytes(t.extractfile(m).read())
        dest.mkdir(parents=True, exist_ok=True)
        done.write_text("ok\n")
    return dest








def load_xyz(folder):
    import tifffile
    np = _np()
    x, y, z = (tifffile.imread(str(Path(folder) / f"{c}.tif")).astype(np.float64) for c in "xyz")
    if not (x.shape == y.shape == z.shape) or x.ndim != 2:
        raise FreshMapError(f"{folder}: x, y, z grids differ in shape or are not 2D")
    return x, y, z


def valid_of(x, y, z):
    np = _np()
    return (x > -0.5) & (y > -0.5) & (z > -0.5) & np.isfinite(x) & np.isfinite(y) & np.isfinite(z)


def _unique_rows(v):
    """np.unique(v, axis=0) for int64 (N, 3) rows of non-negative-ish voxel indices, through one int64 key."""
    np = _np()
    if not len(v):
        return v.reshape(0, 3)
    lo = v.min(0)
    d = v.max(0) - lo + 1
    k = np.unique(((v[:, 0] - lo[0]) * d[1] + (v[:, 1] - lo[1])) * d[2] + (v[:, 2] - lo[2]))
    z, r = np.divmod(k, d[1] * d[2])
    y, x = np.divmod(r, d[2])
    return np.stack([z + lo[0], y + lo[1], x + lo[2]], 1)


def dense_voxels(x, y, z, spacing, s):
    """Unique level voxels (z, y, x int64 rows, voxel side s level-0 voxels) of a mesh's valid vertices and of
    bilinear points in every cell with four valid corners, at most `spacing` apart (level-0 voxels; each cell is
    split by its own longest edge, at most 64 ways). Points are made and floored a batch at a time."""
    np = _np()
    P = np.stack([x, y, z], -1)
    ok = valid_of(x, y, z)
    parts = [_unique_rows(np.floor(P[ok][:, ::-1] / s).astype(np.int64))]
    if P.shape[0] > 1 and P.shape[1] > 1:
        cell = ok[:-1, :-1] & ok[1:, :-1] & ok[:-1, 1:] & ok[1:, 1:]
        if cell.any():
            a, b, c, d = (q[cell] for q in (P[:-1, :-1], P[1:, :-1], P[:-1, 1:], P[1:, 1:]))
            edge = np.max([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - a, axis=1),
                           np.linalg.norm(d - b, axis=1), np.linalg.norm(d - c, axis=1)], 0)
            # a cell far longer than the mesh's usual cell joins two separate pieces (a seam or a wrap), not a
            # surface: it is left out (its vertices stay)
            long = edge > max(LONG_CELL * float(np.median(edge)), 4 * spacing)
            a, b, c, d, edge = a[~long], b[~long], c[~long], d[~long], edge[~long]
            ups = np.clip(np.ceil(edge / spacing), 1, 64).astype(int)
            for up in np.unique(ups):
                sel = ups == up
                t = np.arange(up) / float(up)
                u, v = np.meshgrid(t, t, indexing="ij")
                u, v = u.ravel()[None, :, None], v.ravel()[None, :, None]
                A0, B0, C0, D0 = a[sel], b[sel], c[sel], d[sel]
                batch = max(1, 2_000_000 // (up * up))
                for i in range(0, len(A0), batch):
                    sl = slice(i, i + batch)
                    A, B, C, D = A0[sl][:, None], B0[sl][:, None], C0[sl][:, None], D0[sl][:, None]
                    pts = (A * (1 - u) * (1 - v) + B * u * (1 - v) + C * (1 - u) * v + D * u * v).reshape(-1, 3)
                    parts.append(_unique_rows(np.floor(pts[:, ::-1] / s).astype(np.int64)))
    return _unique_rows(np.concatenate(parts))


def mesh_cells(x, y, z):
    """(area cm2 per valid vertex given voxel cm2 = 1: the product of half-step neighbour distances) as a grid."""
    np = _np()
    P = np.stack([x, y, z], -1)
    ok = valid_of(x, y, z)
    out = []
    for ax in (0, 1):
        d = np.full(x.shape, np.nan)
        a = np.take(P, range(P.shape[ax] - 1), axis=ax)
        b = np.take(P, range(1, P.shape[ax]), axis=ax)
        m = np.take(ok, range(P.shape[ax] - 1), axis=ax) & np.take(ok, range(1, P.shape[ax]), axis=ax)
        step = np.where(m, np.linalg.norm(b - a, axis=-1), np.nan)
        med = np.nanmedian(step) if np.isfinite(step).any() else 1.0
        sl0 = [slice(None)] * 2
        sl1 = [slice(None)] * 2
        sl0[ax] = slice(0, -1)
        sl1[ax] = slice(1, None)
        acc = np.zeros(x.shape)
        cnt = np.zeros(x.shape)
        s = np.nan_to_num(step)
        f = np.isfinite(step).astype(float)
        acc[tuple(sl0)] += s
        cnt[tuple(sl0)] += f
        acc[tuple(sl1)] += s
        cnt[tuple(sl1)] += f
        d = np.where(cnt > 0, acc / np.maximum(cnt, 1), med)
        out.append(d)
    return np.where(ok, out[0] * out[1], 0.0)


def rasterise(folder, level, dims=None):
    """Unique level voxels of a mesh's densified surface, and the mesh's summary: (z, y, x) int64 rows, or with dims
    (Z, Y, X) one sorted int64 key per voxel, (z * Y + y) * X + x, voxels outside the dims dropped."""
    np = _np()
    x, y, z = load_xyz(folder)
    s = 2 ** level
    vox = dense_voxels(x, y, z, s / 2.0, s)
    info = {"valid_vertices": int(valid_of(x, y, z).sum()), "voxels": int(len(vox)),
            "area_vox2": float(mesh_cells(x, y, z).sum())}
    if dims is None:
        return vox, info
    d = np.asarray(dims)
    inside = ((vox >= 0) & (vox < d)).all(1)
    info["outside"] = int((~inside).sum())
    v = vox[inside]
    return np.unique((v[:, 0] * d[1] + v[:, 1]) * d[2] + v[:, 2]), info   # d[2] the padded width


def keys_to_rows(k, dims):
    np = _np()
    z, r = np.divmod(k, dims[1] * dims[2])
    y, x = np.divmod(r, dims[2])
    return np.stack([z, y, x], 1).astype(np.int64)


class Occ:
    """A bit-packed occupancy volume of level voxels on disk (one bit a voxel, x padded to a multiple of 8): the
    rasterised surfaces of one layer. Several processes read it at once; only build writes it."""

    def __init__(self, path, dims=None, create=False):
        np = _np()
        self.path = Path(path)
        meta = self.path.with_suffix(".json")
        if create:
            Z, Y, X = (int(v) for v in dims)
            self.dims = (Z, Y, -(-X // 8) * 8)
            meta.write_text(json.dumps({"dims": self.dims, "shape": [Z, Y, X]}))
            self.mm = np.memmap(self.path, np.uint8, "w+", shape=(Z, Y, self.dims[2] // 8))
        else:
            self.dims = tuple(json.loads(meta.read_text())["dims"])
            self.mm = np.memmap(self.path, np.uint8, "r", shape=(self.dims[0], self.dims[1], self.dims[2] // 8))

    def key(self, rows):
        return (rows[:, 0] * self.dims[1] + rows[:, 1]) * self.dims[2] + rows[:, 2]

    def add(self, keys):
        """Set the bits of sorted level-voxel keys ((z * Y + y) * Xp + x, Xp the padded width)."""
        np = _np()
        flat = self.mm.reshape(-1)
        np.bitwise_or.at(flat, keys >> 3, (1 << (keys & 7)).astype(np.uint8))

    def box(self, lo, hi):
        """bool array of the box [lo, hi) (level zyx), zeros outside the volume."""
        np = _np()
        lo, hi = np.asarray(lo, int), np.asarray(hi, int)
        out = np.zeros(tuple(hi - lo), bool)
        a = np.maximum(lo, 0)
        b = np.minimum(hi, self.dims)
        if (b <= a).any():
            return out
        xb0, xb1 = a[2] // 8, -(-b[2] // 8)
        bits = np.unpackbits(np.asarray(self.mm[a[0]:b[0], a[1]:b[1], xb0:xb1]), axis=2, bitorder="little")
        sub = bits[:, :, a[2] - xb0 * 8:b[2] - xb0 * 8].astype(bool)
        out[a[0] - lo[0]:b[0] - lo[0], a[1] - lo[1]:b[1] - lo[1], a[2] - lo[2]:b[2] - lo[2]] = sub
        return out

    def count(self):
        np = _np()
        n = 0
        for z in range(0, self.dims[0], 64):
            n += int(np.bitwise_count(np.asarray(self.mm[z:z + 64])).sum())
        return n


# ------------------------------------------------------------------ volume

class Chunks:
    """One level of a zarr v2 uint8 array with '/' chunk keys, from a URL or a folder; a missing chunk reads as its
    fill value."""

    def __init__(self, base, level):
        self.base, self.level = str(base).rstrip("/"), int(level)
        meta = json.loads(self._get(".zarray") or b"null")
        if not meta:
            raise FreshMapError(f"no {self.base}/{self.level}/.zarray")
        if meta.get("dtype") != "|u1" or meta.get("dimension_separator", ".") != "/":
            raise FreshMapError("only uint8 zarr v2 arrays with '/' chunk keys are read")
        self.shape, self.chunks = tuple(meta["shape"]), tuple(meta["chunks"])
        self.fill = int(meta.get("fill_value") or 0)
        self.compressor = meta.get("compressor")

    def _get(self, key):
        if "://" not in self.base:
            p = Path(self.base) / str(self.level) / key
            return p.read_bytes() if p.exists() else None
        url = f"{self.base}/{self.level}/{key}"
        for i in range(RETRIES):
            try:
                with urllib.request.urlopen(url, timeout=120) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    return None
                if e.code < 500 or i == RETRIES - 1:
                    raise
            except (urllib.error.URLError, OSError, ConnectionError):
                if i == RETRIES - 1:
                    raise
            time.sleep(2 ** i)
        return None

    def grid(self):
        return tuple(-(-n // c) for n, c in zip(self.shape, self.chunks))

    def chunk(self, cz, cy, cx):
        """The chunk as a full-size array (edge chunks are stored full size in zarr v2), or None when missing."""
        np = _np()
        raw = self._get(f"{cz}/{cy}/{cx}")
        if raw is None:
            return None
        if self.compressor:
            import numcodecs
            raw = numcodecs.get_codec(self.compressor).decode(raw)
        return np.frombuffer(raw, np.uint8).reshape(self.chunks)


def voxel_um_of(scroll, scan):
    """The scan's voxel size in um from its public volume's name (PHerc0343/volumes/SCAN-7.91um-...)."""
    url = f"{OPEN}/?list-type=2&prefix={scroll}/volumes/{scan}-&delimiter=/"
    with urllib.request.urlopen(url, timeout=60) as r:
        text = r.read().decode()
    import re
    m = re.search(re.escape(scan) + r"-([0-9.]+)um", text)
    if not m:
        raise FreshMapError(f"no public volume of {scroll} scan {scan} names its voxel size; give --voxel-um")
    return float(m.group(1))


# ------------------------------------------------------------------ inputs
def m7_url(scroll, scan=None):
    """The public m7 prediction zarr (without the level) of SCROLL in frame SCAN (default M7_PUBLIC)."""
    scan = scan or M7_PUBLIC.get(scroll)
    if not scan:
        raise FreshMapError(f"no public m7 prediction listed for {scroll}: give --volume and --frame")
    return (f"{OPEN}/{scroll}/representations/predictions/surfaces/"
            f"{scan}-surface-20260413222639-surface-m7-L0-th0.2.zarr")


def load_boxes(path):
    """Regions to class BOXED: a JSON list of {"id", "z": [a, b], "y": [a, b], "x": [a, b]} in level-0 voxels of
    the prediction's frame. Returns [(z0, z1, y0, y1, x0, x1, id)]."""
    if not path:
        return []
    try:
        data = json.loads(Path(path).read_text())
        out = []
        for i, b in enumerate(data):
            z, y, x = (b[k] for k in ("z", "y", "x"))
            out.append((int(z[0]), int(z[1]), int(y[0]), int(y[1]), int(x[0]), int(x[1]), str(b.get("id", i))))
        return out
    except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
        raise FreshMapError(f"cannot read boxes {path}: {e}") from e








# ------------------------------------------------------------------ per chunk

def face_weights(b, by_axis=None):
    """Exposed faces per papyrus voxel (uint8), neighbours outside the array counted as equal (no face); by_axis, a
    list of 3, gets each axis's face count added."""
    np = _np()
    f = np.zeros(b.shape, np.uint8)
    for ax in range(3):
        n = b.shape[ax]
        lo = [slice(None)] * 3
        hi = [slice(None)] * 3
        lo[ax], hi[ax] = slice(0, n - 1), slice(1, n)
        diff = b[tuple(lo)] != b[tuple(hi)]
        f[tuple(lo)] += (diff & b[tuple(lo)])
        f[tuple(hi)] += (diff & b[tuple(hi)])
        if by_axis is not None:
            by_axis[ax] += int(diff.sum())
    return f


def near_mask(occ, origin, shape, rad):
    """bool array `shape` at `origin` (level zyx): voxels within rad (level voxels, Euclidean) of any occupied voxel
    of occ (an Occ, or None for no surfaces)."""
    np = _np()
    from scipy import ndimage
    if occ is None:
        return np.zeros(shape, bool)
    m = int(math.ceil(rad))
    o = np.asarray(origin) - m
    ext = np.asarray(shape) + 2 * m
    g = occ.box(o, o + ext)
    if not g.any():
        return np.zeros(shape, bool)
    rr = np.argwhere(g)
    # only the box of the occupied voxels grown by m can be near: the transform runs there alone
    lo = np.maximum(rr.min(0) - m, 0)
    hi = np.minimum(rr.max(0) + m + 1, ext)
    near = np.zeros(tuple(ext), bool)
    near[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] = ndimage.distance_transform_edt(
        ~g[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]) <= rad
    return near[m:m + shape[0], m:m + shape[1], m:m + shape[2]]


def box_mask(boxes, origin, shape, s):
    np = _np()
    out = np.zeros(shape, bool)
    for z0, z1, y0, y1, x0, x1, _ in boxes:
        lo, hi = [], []
        for (a, b), o, n in zip(((z0, z1), (y0, y1), (x0, x1)), origin, shape):
            # a level voxel is inside when its centre is: (i + 0.5) * s in [a, b)
            lo.append(max(0, int(math.ceil(a / s - 0.5)) - o))
            hi.append(min(n, int(math.ceil(b / s - 0.5)) - o))
        if all(h > l for l, h in zip(lo, hi)):
            out[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] = True
    return out


def classify_chunk(m7, origin, occ_read, occ_traced, boxes, level, rad, face_cm2, sum_factor):
    """Per class area (cm2) on the coarse grid of this chunk: array (4, cz, cy, cx), and the chunk's totals."""
    np = _np()
    b = m7 > 0
    shape = b.shape
    out = np.zeros((4,) + tuple(-(-n // sum_factor) for n in shape), np.float64)
    if not b.any():
        return out, [0, 0, 0]
    axes = [0, 0, 0]
    w = face_weights(b, axes).astype(np.float64) * (face_cm2 / 2.0 / PROJ)
    read = near_mask(occ_read, origin, shape, rad) & b
    traced = near_mask(occ_traced, origin, shape, rad) & b & ~read
    boxed = box_mask(boxes, origin, shape, 2 ** level) & b & ~read & ~traced
    fresh = b & ~read & ~traced & ~boxed
    for k, m in enumerate((read, traced, boxed, fresh)):
        out[k] = _coarse(np.where(m, w, 0.0), sum_factor)
    return out, axes


def _coarse(a, f):
    np = _np()
    pad = [(0, (-n) % f) for n in a.shape]
    if any(p[1] for p in pad):
        a = np.pad(a, pad)
    z, y, x = (n // f for n in a.shape)
    return a.reshape(z, f, y, f, x, f).sum((1, 3, 5))


# ------------------------------------------------------------------ build

def rasterise_all(meshes, level, jobs, say, occ):
    """Rasterise [(name, folder)] into the Occ occ; per-mesh records."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from concurrent.futures.process import BrokenProcessPool
    recs, n = [], 0
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = {ex.submit(rasterise, str(f), level, occ.dims): (nm, f) for nm, f in meshes}
        for fu in as_completed(futs):
            nm, f = futs.pop(fu)
            try:
                k, info = fu.result()
            except BrokenProcessPool:
                raise FreshMapError("a rasterising worker died (out of memory?): rerun with fewer --jobs")
            except Exception as e:  # a broken mesh is recorded, never silently dropped
                recs.append({"name": nm, "folder": str(f), "error": f"{type(e).__name__}: {e}"})
                continue
            occ.add(k)
            recs.append(dict(info, name=nm, folder=str(f)))
            n += 1
            if say and n % 200 == 0:
                say(f"rasterised {n} of {len(meshes)} meshes")
    occ.mm.flush()
    recs.sort(key=lambda r: (r["name"], r["folder"]))
    return recs


def _occ_cached(meshes, level, jobs, say, cache, dims, out, layer):
    """(Occ at OUT/occ-LAYER.bits, records): rasterised once per set of meshes (a hash of their folders, sizes and
    times names the cached copy in cache, hard-linked or copied into OUT)."""
    import shutil
    h = hashlib.sha256(f"{level}|{list(dims)}".encode())
    for n, f in sorted(meshes, key=lambda t: str(t[1])):
        st = [(Path(f) / c).stat() for c in ("x.tif", "y.tif", "z.tif")]
        h.update(f"{n}|{f}|{[(q.st_size, int(q.st_mtime)) for q in st]}".encode())
    c = Path(cache) / f"occ-L{level}-{h.hexdigest()[:16]}.bits"
    recs_p = c.with_suffix(".recs.json")
    if not recs_p.exists():
        c.parent.mkdir(parents=True, exist_ok=True)
        occ = Occ(c, dims, create=True)
        recs = rasterise_all(meshes, level, jobs, say, occ) if meshes else []
        del occ
        recs_p.write_text(json.dumps(recs))
    dst = Path(out) / f"occ-{layer}.bits"
    for src, d in ((c, dst), (c.with_suffix(".json"), dst.with_suffix(".json"))):
        if d.exists():
            d.unlink()
        try:
            os.link(src, d)
        except OSError:
            shutil.copyfile(src, d)
    return Occ(dst), json.loads(recs_p.read_text())


def _work_chunk(args):
    base, level, key, occ_rp, occ_tp, boxes, rad, face_cm2, f = args
    vol = Chunks(base, level)
    occ_r, occ_t = (Occ(q) if q else None for q in (occ_rp, occ_tp))
    a = vol.chunk(*key)
    if a is None:
        return key, None, None
    cs = vol.chunks
    origin = tuple(k * c for k, c in zip(key, cs))
    shape = tuple(min(c, n - o) for c, n, o in zip(cs, vol.shape, origin))
    a = a[:shape[0], :shape[1], :shape[2]]
    return (key,) + tuple(classify_chunk(a, origin, occ_r, occ_t, boxes, level, rad, face_cm2, f))


def build(scroll, read_srcs, traced_srcs, out, level=LEVEL, sum_level=SUM_LEVEL, fresh_vox=FRESH_VOX, zr=None,
          jobs=4, volume=None, voxel_um=None, umbilicus=None, n_targets=TARGETS, cache=None, say=print,
          boxes_path=None, frame=None):
    np = _np()
    say = say or (lambda *_: None)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(cache or out / "cache")
    t0 = time.time()
    scan = frame or M7_PUBLIC.get(scroll)
    if not scan:
        raise FreshMapError(f"no public m7 prediction listed for {scroll}: give --volume and --frame")
    base = volume or m7_url(scroll, scan)
    vol = Chunks(base, level)
    if sum_level < level:
        raise FreshMapError("--sum-level must be at least --level")
    vum = voxel_um or voxel_um_of(scroll, scan)
    read_m = find_meshes(read_srcs, cache)
    traced_m = find_meshes(traced_srcs or [], cache)
    say(f"{len(read_m)} read meshes, {len(traced_m)} traced meshes; m7 level {level} shape {vol.shape}")
    occ_r, rec_r = _occ_cached(read_m, level, jobs, say, cache, vol.shape, out, "read")
    occ_t, rec_t = _occ_cached(traced_m, level, jobs, say, cache, vol.shape, out, "traced")
    say(f"rasterised in {time.time() - t0:.0f} s")
    boxes = load_boxes(boxes_path)
    s = 2 ** level
    f = 2 ** (sum_level - level)
    rad = fresh_vox / s
    face_cm2 = (s * vum * 1e-4) ** 2
    cg = vol.grid()
    z_lo, z_hi = 0, cg[0]
    if zr:
        z_lo, z_hi = zr[0] // (s * vol.chunks[0]), -(-zr[1] // (s * vol.chunks[0]))
    keys = [(cz, cy, cx) for cz in range(z_lo, min(z_hi, cg[0])) for cy in range(cg[1]) for cx in range(cg[2])]
    gshape = tuple(-(-n // f) for n in vol.shape)
    grid = np.zeros((4,) + gshape, np.float32)
    n_r, n_t = occ_r.count(), occ_t.count()
    say(f"{len(keys)} chunks to classify, {n_r} read and {n_t} traced level voxels")
    if any(c % f for c in vol.chunks):
        raise FreshMapError("--sum-level must divide the prediction's chunks")
    from concurrent.futures import ProcessPoolExecutor
    done = missing = 0
    faces = [0, 0, 0]
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = [ex.submit(_work_chunk, (base, level, k, str(occ_r.path) if n_r else None,
                                        str(occ_t.path) if n_t else None, boxes, rad, face_cm2, f)) for k in keys]
        for fu in futs:
            k, a, ax = fu.result()
            done += 1
            if a is None:
                missing += 1
                continue
            faces = [u + v for u, v in zip(faces, ax)]
            o = tuple(kk * c // f for kk, c in zip(k, vol.chunks))
            grid[:, o[0]:o[0] + a.shape[1], o[1]:o[1] + a.shape[2], o[2]:o[2] + a.shape[3]] += a
            if say and done % 200 == 0:
                say(f"classified {done} of {len(keys)} chunks ({missing} missing)")
    np.savez_compressed(out / "grid.npz", grid=grid, classes=np.array(CLASSES), sum_level=sum_level,
                        voxel_um=vum)
    summ = summarise(grid, sum_level, vum, umbilicus)
    tg = targets(grid, sum_level, scan, n_targets, vum, umbilicus)
    rec = {"schema": "freshmap/1", "rule": dict(RULE, fresh_vox_l0=fresh_vox), "scroll": scroll, "scan": scan,
           "volume": base, "level": level, "sum_level": sum_level, "voxel_um": vum, "z_range_l0": zr,
           "chunks": {"listed": len(keys), "missing": missing},
           "faces_by_axis": {"z": faces[0], "y": faces[1], "x": faces[2],
                             "z_share": round(faces[0] / max(1, sum(faces)), 4)},
           "read_meshes": len(read_m), "traced_meshes": len(traced_m), "occupied_voxels": {"read": n_r, "traced": n_t},
           "read_errors": [r for r in rec_r if "error" in r], "traced_errors": [r for r in rec_t if "error" in r],
           "read_sources": [str(x) for x in read_srcs], "traced_sources": [str(x) for x in traced_srcs or []],
           "mesh_area_cm2": {"read": round(sum(r.get("area_vox2", 0) for r in rec_r) * (vum * 1e-4) ** 2, 1),
                             "traced": round(sum(r.get("area_vox2", 0) for r in rec_t) * (vum * 1e-4) ** 2, 1)},
           "boxes": len(boxes), "wall_s": None, **summ, "targets": tg,
           "label": "Model output (geometry): m7 papyrus away from listed surfaces; not ink, text or a reading"}
    (out / "meshes.json").write_text(json.dumps({"read": rec_r, "traced": rec_t}, indent=0) + "\n")
    write_pngs(grid, out, summ)
    rec["wall_s"] = round(time.time() - t0, 1)
    (out / "summary.json").write_text(json.dumps(rec, indent=1) + "\n")
    return rec


# ------------------------------------------------------------------ summaries

def centres(grid, umbilicus=None, sum_level=SUM_LEVEL):
    """(cy, cx) per coarse z layer, in coarse cells: from an umbilicus file ([[z, y, x], ...] or {"points": ...} in
    level-0 voxels, interpolated in z) or the papyrus area's centroid per layer, smoothed by a running median."""
    np = _np()
    tot = grid.sum(0)
    nz = tot.shape[0]
    f = 2 ** sum_level
    if umbilicus:
        pts = json.loads(Path(umbilicus).read_text())
        pts = pts.get("points", pts) if isinstance(pts, dict) else pts
        P = np.asarray(sorted(pts), float)
        zc = (np.arange(nz) + 0.5) * f
        return np.interp(zc, P[:, 0], P[:, 1]) / f - 0.5, np.interp(zc, P[:, 0], P[:, 2]) / f - 0.5
    yy, xx = np.arange(tot.shape[1]), np.arange(tot.shape[2])
    w = tot.sum((1, 2))
    cy = np.where(w > 0, (tot.sum(2) * yy).sum(1) / np.maximum(w, 1e-12), np.nan)
    cx = np.where(w > 0, (tot.sum(1) * xx).sum(1) / np.maximum(w, 1e-12), np.nan)
    out = []
    for c in (cy, cx):
        ok = np.isfinite(c)
        if not ok.any():
            out.append(np.full(nz, tot.shape[1] / 2.0))
            continue
        c = np.interp(np.arange(nz), np.flatnonzero(ok), c[ok])
        k = 15
        pad = np.pad(c, k, mode="edge")
        out.append(np.array([np.median(pad[i:i + 2 * k + 1]) for i in range(nz)]))
    return out[0], out[1]


def thick_fresh(grid, cells=None):
    """FRESH area kept only in coarse cells where FRESH holds at least half the papyrus area and that belong to a z
    run of at least THICK_L0 level-0 voxels of such cells: thin slivers (seams between band fits or read units, a
    few slices thick) drop out."""
    np = _np()
    from scipy import ndimage
    fresh = grid[3]
    m = (fresh > 0) & (fresh >= 0.5 * grid.sum(0))
    n = max(1, int(cells or 1))
    if n > 1:
        m = ndimage.binary_opening(m, structure=np.ones((n, 1, 1), bool))
    return np.where(m, fresh, 0.0)


def summarise(grid, sum_level, vum, umbilicus=None):
    np = _np()
    thick = thick_fresh(grid, THICK_L0 // 2 ** sum_level)
    f = 2 ** sum_level
    cy, cx = centres(grid, umbilicus, sum_level)
    nz, ny, nx = grid.shape[1:]
    yy, xx = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    cell_mm = f * vum * 1e-3
    tot = {c: round(float(grid[k].sum()), 1) for k, c in enumerate(CLASSES)}
    papyrus = sum(tot.values())
    tot["fresh_thick"] = round(float(thick.sum()), 1)
    band_cells = max(1, BAND_L0 // f)
    bands, sectors, rings = [], {}, {}
    for b0 in range(0, nz, band_cells):
        g = grid[:, b0:b0 + band_cells]
        row = {"z_l0": [b0 * f, min(nz, b0 + band_cells) * f]}
        row.update({c: round(float(g[k].sum()), 2) for k, c in enumerate(CLASSES)})
        p = sum(row[c] for c in CLASSES)
        row["papyrus"] = round(p, 2)
        row["fresh_share"] = round(row["fresh"] / p, 4) if p > 0 else None
        row["fresh_thick"] = round(float(thick[b0:b0 + band_cells].sum()), 2)
        if p > 0:
            bands.append(row)
    ang = np.zeros((nz, ny, nx), np.int16)
    rad = np.zeros((nz, ny, nx), np.int16)
    for z in range(nz):
        dy, dx = yy - cy[z], xx - cx[z]
        ang[z] = ((np.degrees(np.arctan2(dy, dx)) % 360) // (360 / SECTORS)).astype(np.int16)
        rad[z] = (np.hypot(dy, dx) * cell_mm // RING_MM).astype(np.int16)
    for k, c in enumerate(CLASSES):
        a = np.bincount(ang.ravel(), weights=grid[k].ravel(), minlength=SECTORS)
        r = np.bincount(rad.ravel(), weights=grid[k].ravel())
        sectors[c] = [round(float(v), 2) for v in a]
        rings[c] = [round(float(v), 2) for v in r]
    nr = max(len(v) for v in rings.values())
    for c in rings:
        rings[c] += [0.0] * (nr - len(rings[c]))
    return {"totals_cm2": dict(tot, papyrus=round(papyrus, 1)),
            "thick_l0": THICK_L0,
            "fresh_share": round(tot["fresh"] / papyrus, 4) if papyrus > 0 else None,
            "bands": bands, "sectors": {"count": SECTORS, "deg": 360 / SECTORS, "cm2": sectors},
            "rings": {"mm": RING_MM, "cm2": rings},
            "centre": {"source": "umbilicus" if umbilicus else "papyrus centroid per coarse layer, running median",
                       "y_l0_first_mid_last": [round(float(cy[i] + 0.5) * f) for i in (0, nz // 2, nz - 1)],
                       "x_l0_first_mid_last": [round(float(cx[i] + 0.5) * f) for i in (0, nz // 2, nz - 1)]}}


def bins(grid, sum_level, vum, umbilicus=None):
    """(band, sector, ring) index arrays over the coarse grid: band BAND_L0 level-0 voxels of z, SECTORS equal angles
    and RING_MM rings about the centre line."""
    np = _np()
    f = 2 ** sum_level
    cy, cx = centres(grid, umbilicus, sum_level)
    nz, ny, nx = grid.shape[1:]
    yy, xx = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    cell_mm = f * vum * 1e-3
    band = np.broadcast_to((np.arange(nz) * f // BAND_L0)[:, None, None], (nz, ny, nx))
    ang = np.empty((nz, ny, nx), np.int16)
    ring = np.empty((nz, ny, nx), np.int16)
    for z in range(nz):
        dy, dx = yy - cy[z], xx - cx[z]
        ang[z] = ((np.degrees(np.arctan2(dy, dx)) % 360) // (360 / SECTORS)).astype(np.int16)
        ring[z] = (np.hypot(dy, dx) * cell_mm // RING_MM).astype(np.int16)
    return band, ang, ring


def targets(grid, sum_level, frame, n, vum, umbilicus=None):
    """The n (band, sector, ring) bins with the most thick FRESH area (thick_fresh), each with its class areas and
    the level-0 box of its thick fresh cells. Angles count from +x toward +y in the scan's voxel frame."""
    np = _np()
    f = 2 ** sum_level
    thick = thick_fresh(grid, THICK_L0 // f)
    band, ang, ring = bins(grid, sum_level, vum, umbilicus)
    nr = int(ring.max()) + 1
    code = (band.astype(np.int64) * SECTORS + ang) * nr + ring
    flat = code.ravel()
    sums = [np.bincount(flat, weights=grid[k].ravel()) for k in range(4)]
    th = np.bincount(flat, weights=thick.ravel(), minlength=len(sums[3]))
    order = [int(c) for c in np.argsort(-th) if th[c] > 0][:n]
    out = []
    for c in order:
        cells = np.argwhere((code == c) & (thick > 0))
        lo, hi = cells.min(0) * f, (cells.max(0) + 1) * f
        b, r = divmod(c, nr)
        b, a = divmod(b, SECTORS)
        pap = sum(float(q[c]) for q in sums)
        reg = {"frame": frame, "z": [int(lo[0]), int(hi[0])], "y": [int(lo[1]), int(hi[1])],
               "x": [int(lo[2]), int(hi[2])]}
        row = {"rank": len(out) + 1, "band_z_l0": [b * BAND_L0, (b + 1) * BAND_L0],
               "angle_deg": [a * 360 / SECTORS, (a + 1) * 360 / SECTORS], "ring_mm": [r * RING_MM, (r + 1) * RING_MM]}
        row.update({k: round(float(sums[i][c]), 2) for i, k in enumerate(CLASSES)})
        row.update({"fresh_thick": round(float(th[c]), 2), "papyrus": round(pap, 2), "fresh_share": round(float(sums[3][c]) / pap, 4) if pap else None,
                    "region": reg, "region_text": f"{frame}:{reg['z'][0]}-{reg['z'][1]},{reg['y'][0]}-{reg['y'][1]},"
                                                  f"{reg['x'][0]}-{reg['x'][1]}"})
        out.append(row)
    return out




def resummarise(mapdir, n_targets=TARGETS, umbilicus=None):
    """Recompute summary.json's sums, targets and pictures from grid.npz (after a summary rule change), keeping the
    rest of the record."""
    np = _np()
    mapdir = Path(mapdir)
    rec = json.loads((mapdir / "summary.json").read_text())
    g = np.load(mapdir / "grid.npz")
    grid = g["grid"]
    summ = summarise(grid, rec["sum_level"], rec["voxel_um"], umbilicus)
    tg = targets(grid, rec["sum_level"], rec["scan"], n_targets, rec["voxel_um"], umbilicus)
    rec.update(summ)
    rec["targets"] = tg
    rec["rule"]["targets"] = RULE["targets"]
    write_pngs(grid, mapdir, summ)
    (mapdir / "summary.json").write_text(json.dumps(rec, indent=1) + "\n")
    return rec


# ------------------------------------------------------------------ pictures

COLOURS = {"read": (120, 120, 130), "traced": (70, 130, 220), "boxed": (170, 90, 200), "fresh": (240, 150, 40)}


def _png(path, rgb):
    np = _np()
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[i].astype(np.uint8).tobytes() for i in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _compose(planes):
    """RGB of class planes (4, H, W) of area: hue by the largest class, brightness by total area (log scale)."""
    np = _np()
    tot = planes.sum(0)
    rgb = np.full(tot.shape + (3,), 18.0)
    if tot.max() <= 0:
        return rgb
    lv = np.log1p(tot / np.percentile(tot[tot > 0], 50))
    lv = np.clip(lv / max(lv.max(), 1e-9), 0, 1)
    top = planes.argmax(0)
    for k, c in enumerate(CLASSES):
        m = (top == k) & (tot > 0)
        rgb[m] = 18 + (np.asarray(COLOURS[c], float) - 18) * (0.25 + 0.75 * lv[m])[:, None]
    return rgb


def write_pngs(grid, out, summ, angle_bins=360):
    np = _np()
    nz, ny, nx = grid.shape[1:]
    cy, cx = centres(grid)
    yy, xx = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    un = np.zeros((4, nz, angle_bins))
    rr = int(math.ceil(math.hypot(ny, nx)))
    side = np.zeros((4, nz, rr))
    for z in range(nz):
        a = ((np.degrees(np.arctan2(yy - cy[z], xx - cx[z])) % 360) * angle_bins / 360).astype(int).ravel()
        r = np.hypot(yy - cy[z], xx - cx[z]).astype(int).ravel()
        for k in range(4):
            w = grid[k, z].ravel()
            un[k, z] = np.bincount(a, weights=w, minlength=angle_bins)[:angle_bins]
            side[k, z] = np.bincount(r, weights=w, minlength=rr)[:rr]
    last = max(1, int(np.flatnonzero(side.sum((0, 1)) > 0).max() + 2) if side.sum() > 0 else 1)
    _png(out / "unrolled.png", _compose(un))
    _png(out / "side.png", _compose(side[:, :, :last]))


# ------------------------------------------------------------------ query

def query(mapdir, meshes, cache=None):
    """Per mesh: area, share within the map's fresh distance of read or traced voxels, share seated on m7."""
    np = _np()
    from scipy.spatial import cKDTree
    mapdir = Path(mapdir)
    summ = json.loads((mapdir / "summary.json").read_text())
    level = int(summ["level"])
    occs = {k: (Occ(mapdir / f"occ-{k}.bits") if (mapdir / f"occ-{k}.bits").exists() else None)
            for k in ("read", "traced")}
    s = 2 ** level
    rad = summ["rule"]["fresh_vox_l0"] / s
    vum = summ["voxel_um"]
    vol = Chunks(summ["volume"], level)
    rows = []
    for name, folder in find_meshes(meshes, cache or mapdir / "cache"):
        x, y, z = load_xyz(folder)
        ok = valid_of(x, y, z)
        A = mesh_cells(x, y, z)[ok] * (vum * 1e-4) ** 2
        P = np.stack([z, y, x], -1)[ok] / s - 0.5   # level voxel centre coordinates
        rec = {"name": name, "folder": str(folder), "area_cm2": round(float(A.sum()), 3)}
        near_any = np.zeros(len(P), bool)
        tile = np.floor(P / QUERY_TILE).astype(np.int64)
        tiles, inv = np.unique(tile, axis=0, return_inverse=True)
        inv = inv.ravel()
        m = int(math.ceil(rad)) + 1
        for layer in ("read", "traced"):
            near = np.zeros(len(P), bool)
            if occs[layer] is not None:
                for t, tk in enumerate(tiles):
                    lo = tk * QUERY_TILE - m
                    sel = np.argwhere(occs[layer].box(lo, lo + QUERY_TILE + 2 * m)) + lo
                    if not len(sel):
                        continue
                    idx = np.flatnonzero(inv == t)
                    d, _ = cKDTree(sel.astype(float)).query(P[idx], distance_upper_bound=rad + 1e-9)
                    near[idx] = np.isfinite(d) & (d <= rad)
            rec[f"near_{layer}_share"] = round(float(A[near].sum() / max(A.sum(), 1e-12)), 4)
            near_any |= near
        seated = _seated(vol, np.floor(P + 0.5).astype(np.int64))
        rec["seated_share"] = round(float(A[seated].sum() / max(A.sum(), 1e-12)), 4)
        fresh = seated & ~near_any
        rec["fresh_cm2"] = round(float(A[fresh].sum()), 3)
        rec["fresh_share"] = round(float(A[fresh].sum() / max(A.sum(), 1e-12)), 4)
        rows.append(rec)
    return {"map": str(mapdir), "scroll": summ["scroll"], "fresh_vox_l0": summ["rule"]["fresh_vox_l0"],
            "label": "Model output (geometry)", "meshes": rows}


def _seated(vol, V):
    """bool per level voxel row (z, y, x): m7 above 0 within one voxel (a 3-cube)."""
    np = _np()
    out = np.zeros(len(V), bool)
    cs = np.asarray(vol.chunks)
    cache = {}

    def get(k):
        if k not in cache:
            if any(c < 0 for c in k) or any(c >= g for c, g in zip(k, vol.grid())):
                cache[k] = None
            else:
                cache[k] = vol.chunk(*k)
        return cache[k]
    offs = np.array([(a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)])
    W = (V[:, None, :] + offs[None]).reshape(-1, 3)
    kk = W // cs
    hit = np.zeros(len(W), bool)
    uniq, inv = np.unique(kk, axis=0, return_inverse=True)
    for j, k in enumerate(uniq):
        a = get(tuple(int(t) for t in k))
        if a is None:
            continue
        m = inv.ravel() == j
        loc = W[m] - k * cs
        hit[m] = a[loc[:, 0], loc[:, 1], loc[:, 2]] > 0
    return hit.reshape(len(V), 27).any(1)


# ------------------------------------------------------------------ CLI

def _zrange(t):
    if not t:
        return None
    a, b = t.split(":")
    return [int(a), int(b)]


def build_parser(p=None):
    p = p or argparse.ArgumentParser(prog="python -m kit.freshmap")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("index", help="list the tifxyz meshes in folders and tars (mesh files only)")
    a.add_argument("src", nargs="+")
    a.add_argument("--cache", required=True)
    a.add_argument("--json", action="store_true")
    b = act.add_parser("build", help="map a scroll's m7 papyrus by class: read, traced, boxed, fresh")
    b.add_argument("--scroll", required=True)
    b.add_argument("--read", nargs="+", required=True, help="folders or tars of surfaces already rendered and read")
    b.add_argument("--traced", nargs="*", default=[], help="folders or tars of traced surfaces not yet read")
    b.add_argument("--out", required=True)
    b.add_argument("--level", type=int, default=LEVEL)
    b.add_argument("--sum-level", type=int, default=SUM_LEVEL)
    b.add_argument("--fresh-vox", type=float, default=FRESH_VOX)
    b.add_argument("--z", help="L0:L1 level-0 z range (whole chunks)")
    b.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 0))
    b.add_argument("--volume", help="the m7 zarr (URL or folder, without the level); default the public one")
    b.add_argument("--frame", help="scan id of the prediction's frame (needed with --volume for unlisted scrolls)")
    b.add_argument("--boxes", help="JSON list of level-0 regions to class BOXED (left alone)")
    b.add_argument("--voxel-um", type=float)
    b.add_argument("--umbilicus", help="JSON [[z, y, x], ...] in level-0 voxels")
    b.add_argument("--targets", type=int, default=TARGETS)
    b.add_argument("--cache")
    r = act.add_parser("summarise", help="recompute a built map's sums, targets and pictures from grid.npz")
    r.add_argument("dir")
    r.add_argument("--targets", type=int, default=TARGETS)
    r.add_argument("--umbilicus")
    s = act.add_parser("show", help="print a built map's totals, bands and targets")
    s.add_argument("dir")
    s.add_argument("--json", action="store_true")
    q = act.add_parser("query", help="share of each mesh on fresh papyrus of a built map")
    q.add_argument("dir")
    q.add_argument("mesh", nargs="+")
    q.add_argument("--cache")
    q.add_argument("--json", action="store_true")
    p.set_defaults(func=run)
    return p


def _say(msg):
    print(msg, file=sys.stderr, flush=True)


def run(a):
    try:
        if a.action == "index":
            ms = find_meshes(a.src, a.cache)
            rec = {"meshes": len(ms), "names": sorted({n for n, _ in ms})}
            if a.json:
                print(json.dumps(rec, indent=1))
            else:
                print(f"{rec['meshes']} meshes, {len(rec['names'])} names")
            return 0
        if a.action == "build":
            rec = build(a.scroll, a.read, a.traced, a.out, a.level, a.sum_level, a.fresh_vox, _zrange(a.z), a.jobs,
                        a.volume, a.voxel_um, a.umbilicus, a.targets, a.cache, _say, a.boxes, a.frame)
            _show(rec)
            return 0
        if a.action == "summarise":
            _show(resummarise(a.dir, a.targets, a.umbilicus))
            return 0
        if a.action == "show":
            rec = json.loads((Path(a.dir) / "summary.json").read_text())
            print(json.dumps(rec, indent=1)) if a.json else _show(rec)
            return 0
        if a.action == "query":
            rec = query(a.dir, a.mesh, a.cache)
            if a.json:
                print(json.dumps(rec, indent=1))
            else:
                for r in rec["meshes"]:
                    print(f"{r['name']}: {r['area_cm2']} cm2, fresh {r['fresh_cm2']} cm2 ({r['fresh_share']:.0%}), "
                          f"near read {r['near_read_share']:.0%}, near traced {r['near_traced_share']:.0%}, "
                          f"seated {r['seated_share']:.0%}")
            return 0
    except FreshMapError as e:
        print(f"freshmap: {e}", file=sys.stderr)
        return 2
    return 2


def _show(rec):
    t = rec["totals_cm2"]
    print(f"{rec['scroll']}: papyrus {t['papyrus']} cm2 (m7 estimate); read {t['read']}, traced {t['traced']}, "
          f"boxed {t['boxed']}, fresh {t['fresh']} ({(rec['fresh_share'] or 0):.0%}; in runs of {rec.get('thick_l0')} "
          f"slices or more {t.get('fresh_thick')}). Model output (geometry).")
    print("band z (level 0)       papyrus  read  traced  boxed  fresh  share  thick")
    for b in rec["bands"]:
        print(f"{b['z_l0'][0]:>6}-{b['z_l0'][1]:<6}  {b['papyrus']:>12.1f} {b['read']:>6.1f} {b['traced']:>6.1f} "
              f"{b['boxed']:>6.1f} {b['fresh']:>6.1f}  {(b['fresh_share'] or 0):>4.0%} {b.get('fresh_thick', 0):>6.1f}")
    for t in rec.get("targets", [])[:10]:
        print(f"target {t['rank']}: {t.get('fresh_thick')} cm2 thick fresh of {t['fresh']} ({(t['fresh_share'] or 0):.0%}) band z {t['band_z_l0']}, "
              f"{t['angle_deg'][0]:.0f}-{t['angle_deg'][1]:.0f} deg, {t['ring_mm'][0]:.0f}-{t['ring_mm'][1]:.0f} mm")
    return 0


def main(argv=None):
    p = build_parser()
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
