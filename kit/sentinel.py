"""Bucket Sentinel: standing checks on every new or changed upload to the organizers' public data, with an offset
table loaders can import.

    python -m kit sentinel scan [--state FILE] [--hf] [--s3] [--exit-code] [--json]
    python -m kit sentinel check ITEM [ITEM ...] [--image] [--plant JSON] [--out DIR] [--json]
    python -m kit sentinel queue [--state FILE] [--json]            what scan found new or changed, not yet checked
    python -m kit sentinel table DIR --out offsets.json             the loader table from check results
    python -m kit sentinel preflight --mesh DIR --volume URL [-- vc_render_tifxyz ARGS ...]
    python -m kit sentinel controls POOL.json --out DIR [--json]    the planted-defect controls (must be caught)

An ITEM is a Hugging Face segment folder of the organizers' bucket scrollprize/datasets (`hf:ink/841/w00`) or an S3
segment surface volume of the open-data bucket (`s3:SAMPLE/segments/SEG/surface-volumes/NAME.zarr`, its mesh found
from the catalog), or an S3 CT volume (`s3vol:SAMPLE/volumes/NAME.zarr`).

Why. Community members found these silent defects one at a time, each after it had already cost training runs:
HF65 canvases off their tifxyz by up to 286 px in 26 of 32 `full_3d` training folders, with offsets on Paris 4 that
vary linearly with position (ScrollPrize/villa#2370, 30 Oct 2026); MAN5_outer_3 label zarrs 59 px smaller than
their canvas (#2369); pyramid level 2 holding 17 of 65 slices while declaring z-scale 1 in 18 of 33 volumes
(#2107); a missing physical scale silently read as 1.0 (#2137, #2220); and no warning when a mesh from another
scan's frame is rendered (#1845). Each check below has a planted control that must catch it (`controls`).

Checks (each gives ok, defect, info or skip, with numbers):
  pyramid   every OME-Zarr level's shape against level 0 under its declared scale: a level that covers less of an
            axis than it declares is missing slices (#2107); with --image, planes read as blank at a level where
            level 0 has data
  scale     a level-0 scale of [1, 1, 1] with no axis unit on a store whose pitch is known elsewhere: the store's
            name, then metadata.min.json (pixel_size_um of its scan), then metadata.json; reports the fallback
  labels    every label zarr's level-0 (y, x) shape against its canvas, and the canvas against the tifxyz grid
            (rows / scale): a label on another grid loads silently (#2369), a canvas on another grid drifts (#2370)
  canvas    --image: phase correlation, CT only, of the canvas surface plane against the CT sampled through the
            tifxyz on the canvas lattice, coarse to fine; an offset model per folder (aligned, constant, affine or
            regions) for the table; labels are never read
  frame     --image: which scan volume the mesh really samples (the candidate whose CT matches the canvas), against
            the volume it declares; a mesh from another frame is a defect (#1845)

Reserved data. A local exclusion file (--exclude FILE, else $KIT_SENTINEL_EXCLUDE, else work/sentinel/exclude.json
when it exists) lists item ids or glob patterns that are never opened. They are reported only as a count, "skipped
by rule", with a sha256 of the sorted skipped ids, so coverage is stated without naming them. The repository ships
no such list.

Reads only public data over anonymous HTTPS: the Hugging Face bucket through its resolve URLs and API listing, and
the open-data S3 bucket. Writes only where --out, --state or the table path say. Needs numpy (and numcodecs for
Blosc-compressed stores, as zarr installs it); tifffile for the tifxyz meshes.
"""

import argparse
import concurrent.futures as cf
import fnmatch
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path

from . import meshaudit
from . import tifxyz as tx

HF_BUCKET = "scrollprize/datasets"
HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")   # as huggingface_hub reads it
HF_RESOLVE = f"{HF_ENDPOINT}/buckets/{HF_BUCKET}/resolve"   # the bucket's file URLs, as HfApi builds them
S3 = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
METADATA_MIN = S3 + "/metadata.min.json"
METADATA = S3 + "/metadata.json"
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "work" / "sentinel" / "state.json"
EXCLUDE_DEFAULT = ROOT / "work" / "sentinel" / "exclude.json"
VERSION = "sentinel-1"

# ---- decision constants, frozen with the back-test preregistration (docs/prereg/2026-11-04-bucket-sentinel.md)
ALIGN_TOL = 2.0          # level-0 px: a canvas is aligned when every measured window and the model are within this
RESID_TOL = 2.0          # level-0 px: an affine whose window residual RMS exceeds this becomes a regions model
CONST_SPAN = 2.0         # level-0 px: an affine that changes less than this over the measured windows is constant
PSR_MIN = 8.0            # peak-to-sidelobe ratio a window registration needs to count
MIN_WINDOWS = 6          # accepted fine windows a canvas verdict needs (else "not measured")
FINE_WIN, FINE_SEARCH, FINE_GRID = 128, 24, 5     # level-2 px; fine windows on a FINE_GRID x FINE_GRID grid
COARSE_WIN, COARSE_SEARCH, COARSE_GRID = 96, 40, 3
SIGMA = 4.0              # level-2 px: high-pass (minus a Gaussian blur) before registration
FILL_MIN = 0.9           # share of a window that must be valid mesh and nonzero canvas
SHAPE_TOL = 1            # px: label and canvas shapes may differ by this (rounding)
GRID_TOL = 2.0           # px: canvas and tifxyz grid sizes may differ by this before it is reported
FRAME_MARGIN = 0.05      # a candidate volume must contain the mesh bbox within this share of its size
SURFACE_PLANE = 32       # level-0 index of the surface plane in a 65-plane canvas; other depths use D // 2


class SentinelError(RuntimeError):
    pass


def _np():
    try:
        import numpy
    except ImportError:
        raise SentinelError("kit sentinel needs numpy (pip install numpy)") from None
    return numpy


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


# ================================================================ exclusion rule

class Rule:
    """Item ids that are never opened. Patterns are fnmatch globs against the item id (hf:ink/..., s3:...)."""

    def __init__(self, patterns=(), source=None):
        self.patterns = [str(p) for p in patterns]
        self.source = source
        self.skipped = []

    @classmethod
    def load(cls, path=None, env=None):
        env = os.environ if env is None else env
        p = path or env.get("KIT_SENTINEL_EXCLUDE") or (EXCLUDE_DEFAULT if EXCLUDE_DEFAULT.exists() else None)
        if not p:
            return cls()
        doc = json.loads(Path(p).read_text())
        pats = doc.get("patterns", doc) if isinstance(doc, dict) else doc
        return cls(pats, source="file")

    def excluded(self, item_id):
        hit = any(fnmatch.fnmatch(item_id, p) or fnmatch.fnmatch(item_id.split(":", 1)[-1], p)
                  for p in self.patterns)
        if hit and item_id not in self.skipped:
            self.skipped.append(item_id)
        return hit

    def coverage(self):
        """What may be published about the skipped items: a count and a digest, never the ids."""
        ids = sorted(set(self.skipped))
        return {"skipped_by_rule": len(ids),
                "skipped_digest": sha256_bytes("\n".join(ids).encode())[:16] if ids else None,
                "rule": "local exclusion file" if self.source else "none"}


# ================================================================ reading zarr stores

class Store:
    """An OME-Zarr (or plain zarr v2 array) at a URL or folder: per-level metadata, declared scales and axis units."""

    def __init__(self, url, src=None):
        self.url = str(url).rstrip("/")
        self.src = src or tx.ZarrSource(self.url)
        self.attrs = self.src.json(".zattrs") or {}
        self.name = self.url.split("/")[-1]
        ms = (self.attrs.get("multiscales") or [None])[0]
        self.levels = []
        if ms:
            self.axes = ms.get("axes") or []
            for d in ms.get("datasets") or []:
                scale, trans = None, None
                for t in d.get("coordinateTransformations") or []:
                    if t.get("type") == "scale":
                        scale = [float(v) for v in t.get("scale")]
                    if t.get("type") == "translation":
                        trans = [float(v) for v in t.get("translation")]
                self.levels.append({"path": d["path"], "scale": scale, "translation": trans})
        else:
            self.axes = []
            self.levels.append({"path": "", "scale": None, "translation": None})
        for lv in self.levels:
            pre = (lv["path"] + "/") if lv["path"] else ""
            za = self.src.json(pre + ".zarray")
            lv["zarray"] = za
            lv["shape"] = list(za["shape"]) if za else None

    def meta(self):
        """The metadata the checks read, as a plain dict (planted copies edit this)."""
        return {"name": self.name, "axes": self.axes,
                "levels": [{k: lv[k] for k in ("path", "scale", "translation", "shape")} for lv in self.levels],
                "attrs_keys": sorted(self.attrs)}

    def level(self, k):
        return Level(self.src, self.levels[k]["path"], self.levels[k]["zarray"])


class Level:
    """One array of a store, read by box with an in-memory chunk cache."""

    def __init__(self, src, path, zarray, workers=16, cache_mb=160):
        np = _np()
        if zarray is None:
            raise SentinelError(f"{src.root}/{path}: no .zarray")
        self.src, self.path, self.za = src, path, zarray
        self.shape = tuple(zarray["shape"])
        self.chunks = tuple(zarray["chunks"])
        self.dtype = np.dtype(zarray["dtype"])
        self.fill = zarray.get("fill_value") or 0
        self.sep = zarray.get("dimension_separator") or "."
        self.codec = None
        if zarray.get("compressor"):
            try:
                import numcodecs
            except ImportError:
                raise SentinelError("this store is compressed: pip install numcodecs (zarr installs it)") from None
            self.codec = numcodecs.get_codec(zarray["compressor"])
        self.filters = zarray.get("filters")
        self.workers = workers
        self.cache, self.cache_bytes, self.cache_cap = {}, 0, cache_mb << 20

    def key(self, idx):
        pre = (self.path + "/") if self.path else ""
        return pre + self.sep.join(str(int(i)) for i in idx)

    def chunk(self, idx):
        np = _np()
        idx = tuple(int(i) for i in idx)
        if idx in self.cache:
            return self.cache[idx]
        raw = self.src.read(self.key(idx))
        if raw is None:
            arr = None
        else:
            if self.codec is not None:
                raw = self.codec.decode(raw)
            arr = np.frombuffer(raw, dtype=self.dtype)
            n = int(np.prod(self.chunks))
            if arr.size != n:
                raise SentinelError(f"{self.src.root}/{self.key(idx)}: {arr.size} values, want {n}")
            arr = arr.reshape(self.chunks)
        if self.cache_bytes > self.cache_cap:
            self.cache.clear()
            self.cache_bytes = 0
        self.cache[idx] = arr
        self.cache_bytes += 0 if arr is None else arr.nbytes
        return arr

    def read(self, z0, z1, y0, y1, x0, x1):
        """Box [z0, z1) x [y0, y1) x [x0, x1) as an array; outside the array or in absent chunks reads the fill."""
        np = _np()
        box = [(int(z0), int(z1)), (int(y0), int(y1)), (int(x0), int(x1))]
        out = np.full([b - a for a, b in box], self.fill, dtype=self.dtype)
        rng = []
        for (a, b), n, c in zip(box, self.shape, self.chunks):
            lo, hi = max(a, 0), min(b, n)
            if hi <= lo:
                return out
            rng.append(range(lo // c, (hi - 1) // c + 1))
        idxs = [(i, j, k) for i in rng[0] for j in rng[1] for k in rng[2]]
        todo = [i for i in idxs if i not in self.cache]
        if len(todo) > 1:
            with cf.ThreadPoolExecutor(min(self.workers, len(todo))) as ex:
                list(ex.map(self.chunk, todo))
        for idx in idxs:
            arr = self.chunk(idx)
            if arr is None:
                continue
            sl_out, sl_in = [], []
            for ax, ((a, b), i, c, n) in enumerate(zip(box, idx, self.chunks, self.shape)):
                lo, hi = max(a, i * c), min(b, (i + 1) * c, n)
                sl_out.append(slice(lo - a, hi - a))
                sl_in.append(slice(lo - i * c, hi - i * c))
            out[tuple(sl_out)] = arr[tuple(sl_in)]
        return out


# ================================================================ metadata checks

def _factors(levels):
    s0 = levels[0].get("scale")
    out = []
    for k, lv in enumerate(levels):
        s = lv.get("scale")
        if s and s0 and len(s) >= 3 and len(s0) >= 3:
            out.append([b / a if a else float("nan") for a, b in zip(s0[-3:], s[-3:])])
        else:
            out.append([1.0, 2.0 ** k, 2.0 ** k])      # undeclared: XY halving, as villa's renders do
    return out


def check_pyramid(meta):
    """Each level's shape against level 0 under its declared scale (#2107). Returns the check result."""
    levels = meta["levels"]
    if not levels or not levels[0].get("shape"):
        return {"check": "pyramid", "verdict": "skip", "why": "no level-0 array"}
    n0 = levels[0]["shape"][-3:]
    fac = _factors(levels)
    rows, problems = [], []
    for k, lv in enumerate(levels):
        shp = lv.get("shape")
        if shp is None:
            problems.append({"level": k, "kind": "missing_level", "detail": "declared in multiscales, no .zarray"})
            continue
        shp = shp[-3:]
        row = {"level": k, "shape": shp, "declared_factor": fac[k]}
        for ax, name in enumerate("zyx"):
            f = fac[k][ax]
            if not (f and f > 0) or math.isnan(f):
                continue
            covers = shp[ax] * f
            if covers < n0[ax] - f - 1e-6:
                problems.append({"level": k, "axis": name, "kind": "missing_slices", "have": shp[ax],
                                 "want": math.ceil(n0[ax] / f), "declared_factor": f,
                                 "covers": round(covers / n0[ax], 4),
                                 "true_factor_if_truncated": 1.0 if shp[ax] < n0[ax] else None})
            elif shp[ax] > math.ceil(n0[ax] / f) + 1:
                problems.append({"level": k, "axis": name, "kind": "extra_slices", "have": shp[ax],
                                 "want": math.ceil(n0[ax] / f), "declared_factor": f})
        rows.append(row)
    return {"check": "pyramid", "verdict": "defect" if problems else "ok", "levels": rows, "problems": problems}


def true_z_factor(meta, k):
    """The z factor level k really has: its declared one, or 1 when check_pyramid finds it truncated."""
    levels = meta["levels"]
    f = _factors(levels)[k][0]
    n0, nk = levels[0]["shape"][-3], levels[k]["shape"][-3]
    if nk * f < n0 - f - 1e-6:
        return 1.0
    return f


PITCH_IN_NAME = re.compile(r"(\d+\.\d+)\s*um", re.I)
UNITS = {"micrometer": 1.0, "micrometre": 1.0, "um": 1.0, "µm": 1.0, "nanometer": 1e-3, "millimeter": 1e3}


def known_pitch(name, volume_id=None, minmeta=None, catalog=None):
    """(pitch in um, source) for a store, from its name, then metadata.min.json, then metadata.json; else (None, None)."""
    m = PITCH_IN_NAME.search(name or "")
    if m:
        return float(m.group(1)), "name"
    for doc, label in ((minmeta, "metadata.min.json"), (catalog, "metadata.json")):
        if not doc or not volume_id:
            continue
        for s in (doc.get("samples") or {}).values():
            vols = s.get("volumes") or {}
            v = vols.get(volume_id) if isinstance(vols, dict) else None
            if isinstance(v, dict):
                p = (v.get("properties") or {}).get("pixel_size_um")
                if p:
                    return float(p), label
                scan = v.get("scan_id")
                sc = (s.get("scans") or {}).get(scan) if scan else None
                if sc:
                    p = (sc.get("properties") or {}).get("pixel_size_um")
                    if p:
                        return float(p), label
            scans = s.get("scans") or {}
            if volume_id in scans:
                p = (scans[volume_id].get("properties") or {}).get("pixel_size_um")
                if p:
                    return float(p), label
    return None, None


def check_scale(meta, pitch=None, pitch_source=None, kind="volume"):
    """A level-0 scale of [1, 1, 1] with no axis unit, or a declared pitch that disagrees, on a store whose pitch is
    known (#2137, #2220). A canvas grid with no known pitch is info, not a defect."""
    lv0 = meta["levels"][0]
    s = lv0.get("scale")
    units = [a.get("unit") if isinstance(a, dict) else None for a in meta.get("axes") or []][-3:]
    has_unit = any(u for u in units)
    out = {"check": "scale", "declared": s, "units": units, "known_pitch_um": pitch, "pitch_source": pitch_source}
    if s is None:
        out.update(verdict="defect" if pitch else "info", kind="no_scale",
                   fallback_um=pitch, detail="no scale transform at level 0")
        return out
    ones = all(abs(v - 1.0) < 1e-9 for v in s[-3:])
    if ones and not has_unit:
        if pitch:
            out.update(verdict="defect", kind="scale_reset", fallback_um=pitch,
                       detail=f"level-0 scale [1, 1, 1] with no unit; the pitch is {pitch} um ({pitch_source})")
        else:
            out.update(verdict="info", kind="pixel_grid", detail="[1, 1, 1] with no unit and no known pitch"
                       + (" (a canvas grid)" if kind == "canvas" else ""))
        return out
    if has_unit and pitch:
        u = next(u for u in units if u)
        mult = UNITS.get(str(u).lower())
        if mult is not None:
            declared = s[-1] * mult
            if abs(declared - pitch) > 0.01 * pitch:
                out.update(verdict="defect", kind="scale_mismatch", fallback_um=pitch,
                           detail=f"declares {declared} um, known pitch {pitch} um ({pitch_source})")
                return out
    out.update(verdict="ok")
    return out


def check_labels(canvas_shape, labels, grid_shape=None):
    """Label zarrs against the canvas (#2369), and the canvas against the tifxyz grid (#2370). canvas_shape and each
    label shape are level-0 (y, x); grid_shape is (rows / scale_y, cols / scale_x) of the tifxyz."""
    problems, rows = [], []
    for name, shp in sorted(labels.items()):
        if shp is None:
            continue
        dy, dx = canvas_shape[0] - shp[0], canvas_shape[1] - shp[1]
        rows.append({"label": name, "shape": list(shp), "short_by": [dy, dx]})
        if abs(dy) > SHAPE_TOL or abs(dx) > SHAPE_TOL:
            problems.append({"kind": "label_shape", "label": name, "shape": list(shp),
                             "canvas": list(canvas_shape), "short_by": [dy, dx]})
    out = {"check": "labels", "canvas": list(canvas_shape), "labels": rows}
    if grid_shape is not None:
        gy, gx = grid_shape
        out["grid"] = [round(gy, 2), round(gx, 2)]
        out["drift_slope"] = [gy / canvas_shape[0] - 1.0, gx / canvas_shape[1] - 1.0]
        if abs(gy - canvas_shape[0]) > GRID_TOL or abs(gx - canvas_shape[1]) > GRID_TOL:
            out["grid_note"] = (f"canvas {canvas_shape[0]} x {canvas_shape[1]} on a tifxyz grid of "
                                f"{gy:.1f} x {gx:.1f}: expect offsets that change linearly with position")
    out["problems"] = problems
    out["verdict"] = "defect" if problems else ("ok" if rows else "skip")
    return out


# ================================================================ image registration (CT only)

def gaussian_blur(a, sigma):
    np = _np()
    if sigma <= 0:
        return a
    r = int(math.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    p = np.pad(a, r, mode="reflect")
    p = np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), 0, p)
    return np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), 1, p)


def prep(a, valid=None):
    """High-passed, mean-filled window for registration."""
    np = _np()
    a = np.asarray(a, float)
    if valid is None:
        valid = np.isfinite(a)
    m = a[valid].mean() if valid.any() else 0.0
    a = np.where(valid, a, m)
    return a - gaussian_blur(a, SIGMA)


def register(ct, canvas, search, valid=None):
    """(dy, dx, psr): canvas(y, x) shows ct(y + dy, x + dx), in window pixels, from phase correlation with the peak
    searched within +-search. meshaudit.phase_shift gives s with b(x) ~ a(x - s); here a = ct, b = canvas, so d = -s."""
    np = _np()
    a, b = prep(ct, valid), prep(canvas, valid)
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa = np.fft.fft2(a * win)
    fb = np.fft.fft2(b * win)
    r = fb * np.conj(fa)
    r /= np.maximum(np.abs(r), 1e-12)
    c = np.real(np.fft.ifft2(r))
    h, w = c.shape
    sy = np.fft.fftfreq(h) * h
    sx = np.fft.fftfreq(w) * w
    inside = (np.abs(sy)[:, None] <= search) & (np.abs(sx)[None, :] <= search)
    cm = np.where(inside, c, -np.inf)
    i, j = np.unravel_index(int(np.argmax(cm)), c.shape)

    def sub(m1, m0, p1):
        den = m1 - 2 * m0 + p1
        return 0.5 * (m1 - p1) / den if den != 0 else 0.0
    di = sub(c[(i - 1) % h, j], c[i, j], c[(i + 1) % h, j])
    dj = sub(c[i, (j - 1) % w], c[i, j], c[i, (j + 1) % w])
    si, sj = sy[i] + di, sx[j] + dj
    side = (np.abs(sy)[:, None] <= max(search, h // 4)) & (np.abs(sx)[None, :] <= max(search, w // 4))
    for y in range(i - 5, i + 6):
        for x in range(j - 5, j + 6):
            side[y % h, x % w] = False
    psr = float((c[i, j] - c[side].mean()) / (c[side].std() + 1e-12))
    return -float(si), -float(sj), psr


# ================================================================ geometry: canvas pixels to CT through the mesh

class Mesh:
    """A tifxyz grid (rows x cols of x, y, z points in level-0 voxels, NaN where invalid) and its scale."""

    def __init__(self, xyz, scale, meta=None, pins=None):
        np = _np()
        self.xyz = np.asarray(xyz, np.float32)
        self.scale = (float(scale[1]), float(scale[0]))      # meta.json scale is [x, y]; kept here as (y, x)
        self.meta = meta or {}
        self.pins = pins or {}
        self.valid = np.isfinite(self.xyz).all(-1)

    @property
    def stretch(self):
        """Median level-0 voxels per full-resolution cell along the grid (1.0 for an isometric tifxyz)."""
        if getattr(self, "_stretch", None) is None:
            np = _np()
            k = max(1, int(math.sqrt(self.valid.size / 4e5)))
            g = self.xyz[::k, ::k]
            ey = np.linalg.norm(g[1:] - g[:-1], axis=-1) * self.scale[0] / k
            ex = np.linalg.norm(g[:, 1:] - g[:, :-1], axis=-1) * self.scale[1] / k
            e = np.concatenate([ey[np.isfinite(ey)], ex[np.isfinite(ex)]])
            self._stretch = float(np.median(e)) if len(e) else 1.0
        return self._stretch

    def valid_cells(self, most=200000):
        """Grid indices (rows, cols) of valid nodes, subsampled on a regular stride to at most about `most`."""
        np = _np()
        n = int(self.valid.sum())
        k = max(1, int(math.sqrt(n / most))) if n > most else 1
        r, c = np.nonzero(self.valid[::k, ::k])
        return r * k, c * k

    @property
    def grid_shape(self):
        """Full-resolution grid size (rows / scale_y, cols / scale_x)."""
        return self.xyz.shape[0] / self.scale[0], self.xyz.shape[1] / self.scale[1]

    def bbox(self):
        np = _np()
        k = max(1, int(math.sqrt(self.valid.size / 1e6)))
        sub = self.xyz[::k, ::k][self.valid[::k, ::k]]
        return sub.min(0), sub.max(0)

    def points(self, cy, cx):
        """3D points (N, 3, x y z) at full-resolution cells (cy, cx) by bilinear interpolation; NaN off the mesh."""
        np = _np()
        gy, gx = np.asarray(cy, float) * self.scale[0], np.asarray(cx, float) * self.scale[1]
        H, W = self.valid.shape
        i0, j0 = np.floor(gy).astype(int), np.floor(gx).astype(int)
        ok = (i0 >= 0) & (j0 >= 0) & (i0 < H - 1) & (j0 < W - 1)
        i0c, j0c = np.clip(i0, 0, H - 2), np.clip(j0, 0, W - 2)
        ty, tx_ = (gy - i0c)[..., None], (gx - j0c)[..., None]
        p = ((1 - ty) * (1 - tx_) * self.xyz[i0c, j0c] + (1 - ty) * tx_ * self.xyz[i0c, j0c + 1]
             + ty * (1 - tx_) * self.xyz[i0c + 1, j0c] + ty * tx_ * self.xyz[i0c + 1, j0c + 1])
        p[~ok] = np.nan
        return p


def sample_ct(level, factor, pts):
    """Trilinear CT values of `level` (level-0 voxels per level voxel: factor, z y x) at level-0 points (..., x y z);
    NaN where a point is invalid or outside the volume."""
    np = _np()
    shp = pts.shape[:-1]
    p = pts.reshape(-1, 3)
    ok = np.isfinite(p).all(1)
    q = np.full((p.shape[0], 3), np.nan)
    f = np.asarray(factor, float)
    q[ok] = (p[ok][:, ::-1] - (f - 1) / 2.0) / f          # level coordinates, z y x, voxel centers
    out = np.full(p.shape[0], np.nan)
    if not ok.any():
        return out.reshape(shp)
    lo = np.floor(np.nanmin(q[ok], 0)).astype(int)
    hi = np.floor(np.nanmax(q[ok], 0)).astype(int) + 2
    if np.prod(hi - lo) > 256 ** 3:
        raise SentinelError(f"a window spans {tuple(hi - lo)} voxels at this level; use a smaller window")
    box = level.read(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]).astype(np.float32)
    r = q[ok] - lo
    i0 = np.floor(r).astype(int)
    t = r - i0
    acc = np.zeros(len(r))
    for dz in (0, 1):
        for dy in (0, 1):
            for dx in (0, 1):
                w = ((t[:, 0] if dz else 1 - t[:, 0]) * (t[:, 1] if dy else 1 - t[:, 1])
                     * (t[:, 2] if dx else 1 - t[:, 2]))
                zz = np.clip(i0[:, 0] + dz, 0, box.shape[0] - 1)
                yy = np.clip(i0[:, 1] + dy, 0, box.shape[1] - 1)
                xx = np.clip(i0[:, 2] + dx, 0, box.shape[2] - 1)
                acc += w * box[zz, yy, xx]
    inside = (q[ok] >= -0.5).all(1) & (q[ok] <= np.asarray(level.shape) - 0.5).all(1)
    acc[~inside] = np.nan
    out[ok] = acc
    return out.reshape(shp)


class Canvas:
    """The canvas surface plane, read as level-F windows (F level-0 px per window px) from the best pyramid level.

    A planted copy wraps this: `transform(y, x) -> (y', x')` maps a level-0 pixel of the planted canvas to the
    level-0 pixel of the source it shows, and shape overrides the level-0 (y, x) size."""

    def __init__(self, store, meta=None, transform=None, shape=None, blank_planes=None):
        self.store = store
        self.meta = meta or store.meta()
        self.transform = transform
        lv0 = self.meta["levels"][0]["shape"]
        self.depth0 = lv0[-3]
        self.shape0 = tuple(shape) if shape else (lv0[-2], lv0[-1])
        self.plane0 = SURFACE_PLANE if self.depth0 == 65 else self.depth0 // 2
        self._levels = {}
        self.blank_planes = blank_planes or {}

    def plan(self, want):
        """(level index, its XY factor, plane index at that level) for the coarsest level <= want that still holds
        the surface plane at its true z factor."""
        fac = _factors(self.meta["levels"])
        best = None
        for k in range(len(self.meta["levels"])):
            if self.meta["levels"][k].get("shape") is None:
                continue
            fy = fac[k][1]
            if fy > want + 1e-9:
                continue
            fz = true_z_factor(self.meta, k)
            plane = int(self.plane0 // fz)
            if plane < self.meta["levels"][k]["shape"][-3]:
                if best is None or fy > best[1]:
                    best = (k, fy, plane)
        if best is None:
            raise SentinelError(f"{self.store.name}: no level at factor <= {want} holds plane {self.plane0}")
        return best

    def _level(self, k):
        if k not in self._levels:
            lv = self.store.levels[k]
            self._levels[k] = Level(self.store.src, lv["path"], lv["zarray"])
        return self._levels[k]

    def window(self, F, r0, c0, n):
        """n x n window of the surface plane at F level-0 px per pixel, top-left at level-0 pixel (r0, c0)."""
        np = _np()
        k, fy, plane = self.plan(F)
        sub = int(round(F / fy))
        lv = self._level(k)
        if self.transform is None:
            R0, C0 = int(round(r0 / fy)), int(round(c0 / fy))
            a = lv.read(plane, plane + 1, R0, R0 + n * sub, C0, C0 + n * sub)[0].astype(np.float32)
        else:
            yy = r0 + (np.arange(n * sub) + 0.5) * fy - 0.5
            xx = c0 + (np.arange(n * sub) + 0.5) * fy - 0.5
            Y, X = np.meshgrid(yy, xx, indexing="ij")
            sy, sx = self.transform(Y, X)
            qy, qx = (sy + 0.5) / fy - 0.5, (sx + 0.5) / fy - 0.5
            R0, C0 = int(np.floor(qy.min())) - 1, int(np.floor(qx.min())) - 1
            R1, C1 = int(np.ceil(qy.max())) + 2, int(np.ceil(qx.max())) + 2
            src = lv.read(plane, plane + 1, R0, R1, C0, C1)[0].astype(np.float32)
            a = _bilinear(src, qy - R0, qx - C0)
        if plane in self.blank_planes.get(k, ()):
            a = np.zeros_like(a)
        if sub > 1:
            a = a.reshape(n, sub, n, sub).mean((1, 3))
        return a


def _bilinear(img, y, x):
    np = _np()
    H, W = img.shape
    y = np.clip(y, 0, H - 1.000001)
    x = np.clip(x, 0, W - 1.000001)
    i, j = np.floor(y).astype(int), np.floor(x).astype(int)
    ty, tx_ = y - i, x - j
    return ((1 - ty) * (1 - tx_) * img[i, j] + (1 - ty) * tx_ * img[i, j + 1]
            + ty * (1 - tx_) * img[i + 1, j] + ty * tx_ * img[i + 1, j + 1])


# ================================================================ the canvas check

def _lattice(F, r0, c0, n):
    np = _np()
    yy = r0 + (np.arange(n) + 0.5) * F - 0.5
    xx = c0 + (np.arange(n) + 0.5) * F - 0.5
    return np.meshgrid(yy, xx, indexing="ij")


def ct_window(mesh, ct, F, r0, c0, n, model):
    """CT sampled through the mesh on the canvas lattice at F px, each pixel moved by the model's offset."""
    np = _np()
    Y, X = _lattice(F, r0, c0, n)
    dy, dx = model(Y, X)
    pts = mesh.points(Y + dy, X + dx)
    lv, fac = ct(F * max(1.0, mesh.stretch)) if callable(ct) else ct   # a stretched mesh covers more voxels a pixel
    return sample_ct(lv, fac, pts)


def fit_model(rows):
    """Least-squares affine per axis over window rows (y, x, dy, dx), one trimming pass (3 MAD, at least 1 px)."""
    np = _np()
    A = np.array([[1.0, r["y"], r["x"]] for r in rows])
    D = np.array([[r["dy"], r["dx"]] for r in rows])
    keep = np.ones(len(rows), bool)
    coef = None
    for _ in range(2):
        if keep.sum() < 3:
            break
        rank = np.linalg.matrix_rank(A[keep])
        if rank < 3:
            c0 = np.median(D[keep], 0)
            coef = np.array([[c0[0], 0.0, 0.0], [c0[1], 0.0, 0.0]])
        else:
            coef = np.linalg.lstsq(A[keep], D[keep], rcond=None)[0].T
        res = np.linalg.norm(D - A @ coef.T, axis=1)
        mad = np.median(np.abs(res[keep] - np.median(res[keep]))) * 1.4826
        keep = res <= max(3 * mad, 1.0) + np.median(res[keep])
    if coef is None:
        c0 = np.median(D, 0)
        coef = np.array([[c0[0], 0.0, 0.0], [c0[1], 0.0, 0.0]])
    res = D - A @ coef.T
    rms = float(np.sqrt((res[keep] ** 2).sum(1).mean())) if keep.any() else float("nan")
    return coef, keep, res, rms


def check_canvas(canvas, mesh, ct, prior=True, log=None):
    """Measure where the canvas sits on its tifxyz. `ct` gives, for F level-0 px per window pixel, the CT level
    (Level, factor zyx) to sample (ct_source). Returns the check result with an offset model."""
    np = _np()
    H, W = canvas.shape0
    gy, gx = mesh.grid_shape
    sy = gy / H - 1.0 if prior else 0.0
    sx = gx / W - 1.0 if prior else 0.0
    model = lambda Y, X: (sy * Y, sx * X)          # noqa: E731  the size-ratio prior (#2370's slopes)
    out = {"check": "canvas", "prior_slope": [sy, sx], "mesh_stretch": round(mesh.stretch, 4), "windows": []}
    # where the mesh is valid, in canvas level-0 px (through the prior)
    vy, vx = mesh.valid_cells()
    cy = vy / mesh.scale[0] / (1 + sy)
    cx = vx / mesh.scale[1] / (1 + sx)
    ylo, yhi, xlo, xhi = np.percentile(cy, 2), np.percentile(cy, 98), np.percentile(cx, 2), np.percentile(cx, 98)

    def windows(F, n, grid):
        size = F * n
        res = []
        for gi in range(grid):
            for gj in range(grid):
                yc = ylo + (gi + 0.5) * (yhi - ylo) / grid
                xc = xlo + (gj + 0.5) * (xhi - xlo) / grid
                if size > H or size > W:
                    continue
                r0 = min(max(0, yc - size / 2), H - size)
                c0 = min(max(0, xc - size / 2), W - size)
                r0, c0 = int(r0 // F) * int(F), int(c0 // F) * int(F)
                if (r0, c0) not in res:
                    res.append((r0, c0))
        return res

    def measure(F, n, search, r0, c0, mdl, refine=False):
        try:
            cv = canvas.window(F, r0, c0, n)
            ctw = ct_window(mesh, ct, F, r0, c0, n, mdl)
        except SentinelError as e:          # a window the mesh crosses too steeply is skipped, and recorded
            out.setdefault("skipped_windows", []).append(str(e)[:120])
            return None
        valid = np.isfinite(ctw) & (cv > 0)
        if valid.mean() < FILL_MIN:
            return None
        dy, dx, psr = register(ctw, cv, search, valid)
        ok = psr >= PSR_MIN and max(abs(dy), abs(dx)) < search - 1
        if ok and refine:
            # one refinement: resample the CT at the measured shift and register the remainder near zero, where
            # the parabolic peak fit has no pixel-locking bias
            shifted = lambda Y, X: tuple(a + b for a, b in zip(mdl(Y, X), (dy * F, dx * F)))  # noqa: E731
            try:
                ct2 = ct_window(mesh, ct, F, r0, c0, n, shifted)
            except SentinelError:
                ct2 = np.full_like(ctw, np.nan)
            v2 = np.isfinite(ct2) & (cv > 0)
            if v2.mean() >= FILL_MIN:
                ry, rx, psr2 = register(ct2, cv, 3, v2)
                if psr2 >= PSR_MIN:
                    dy, dx, psr = dy + ry, dx + rx, psr2
        Yc, Xc = r0 + F * n / 2 - 0.5, c0 + F * n / 2 - 0.5
        my, mx = mdl(np.array(Yc), np.array(Xc))
        return {"y": float(Yc), "x": float(Xc), "dy": float(my + dy * F), "dx": float(mx + dx * F),
                "psr": round(psr, 2), "F": F, "accepted": bool(ok)}

    # coarse pass
    F_c = 16.0
    try:
        canvas.plan(F_c)
    except SentinelError:
        F_c = 4.0
    zero = lambda Y, X: (0 * Y, 0 * X)            # noqa: E731
    tries = []
    for name, mdl in (("prior", model), ("none", zero)) if (sy or sx) else (("none", zero),):
        coarse = []
        for r0, c0 in windows(F_c, COARSE_WIN, COARSE_GRID):
            m = measure(F_c, COARSE_WIN, COARSE_SEARCH, r0, c0, mdl)
            if m:
                coarse.append(m)
        acc = [m for m in coarse if m["accepted"]]
        tries.append((len(acc), sum(m["psr"] for m in acc), name, coarse, mdl))
    tries.sort(key=lambda t: (t[0], t[1]), reverse=True)
    _, _, start, coarse, model = tries[0]
    out["coarse"], out["coarse_start"] = coarse, start
    acc = [m for m in coarse if m["accepted"]]
    if acc:
        if len(acc) >= 3:
            coef, keep, res, rms = fit_model(acc)
        else:
            med = np.median([[m["dy"], m["dx"]] for m in acc], 0)
            m0 = model(np.array(0.0), np.array(0.0))
            coef = np.array([[med[0], 0.0, 0.0], [med[1], 0.0, 0.0]]) if start == "none" else \
                np.array([[med[0] - float(m0[0]), sy, 0.0], [med[1] - float(m0[1]), 0.0, sx]])
        model = lambda Y, X, c=coef: (c[0, 0] + c[0, 1] * Y + c[0, 2] * X,   # noqa: E731
                                      c[1, 0] + c[1, 1] * Y + c[1, 2] * X)
    if log:
        log(f"coarse: {len(acc)}/{len(coarse)} windows accepted")
    # fine pass at 4 px
    fine = []
    for r0, c0 in windows(4.0, FINE_WIN, FINE_GRID):
        m = measure(4.0, FINE_WIN, FINE_SEARCH, r0, c0, model, refine=True)
        if m:
            fine.append(m)
    out["windows"] = fine
    acc = [m for m in fine if m["accepted"]]
    out["n_windows"], out["n_accepted"] = len(fine), len(acc)
    if len(acc) < MIN_WINDOWS:
        out.update(verdict="info", kind="not_measured",
                   detail=f"{len(acc)} accepted windows, fewer than {MIN_WINDOWS}")
        return out
    coef, keep, res, rms = fit_model(acc)
    ys, xs = np.array([m["y"] for m in acc]), np.array([m["x"] for m in acc])
    D = np.array([[m["dy"], m["dx"]] for m in acc])
    corners = np.array([[1, ys.min(), xs.min()], [1, ys.min(), xs.max()], [1, ys.max(), xs.min()],
                        [1, ys.max(), xs.max()]])
    pred = corners @ coef.T
    span = float(np.abs(pred - pred.mean(0)).max() * 2)
    max_meas = float(np.abs(D[keep]).max()) if keep.any() else float(np.abs(D).max())
    max_model = float(np.abs(pred).max())
    if max(max_meas, max_model) <= ALIGN_TOL:
        kind = "aligned"
    elif span <= CONST_SPAN:
        kind = "constant"
    elif rms <= RESID_TOL:
        kind = "affine"
    else:
        kind = "regions"
    out.update(verdict="ok" if kind == "aligned" else "defect", kind=kind,
               affine={"dy": [float(v) for v in coef[0]], "dx": [float(v) for v in coef[1]]},
               resid_rms=round(rms, 3), span=round(span, 2), max_offset=round(max(max_meas, max_model), 2),
               median_offset=[round(float(np.median(D[keep, 0])), 2), round(float(np.median(D[keep, 1])), 2)],
               trimmed=int((~keep).sum()))
    if kind == "constant":
        med = np.median(D[keep], 0)
        out["affine"] = {"dy": [float(med[0]), 0.0, 0.0], "dx": [float(med[1]), 0.0, 0.0]}
    if kind == "regions":
        out["grid"] = _region_grid(acc, coef)
    return out


def _region_grid(acc, coef):
    ys = sorted({round(m["y"], 1) for m in acc})
    xs = sorted({round(m["x"], 1) for m in acc})
    gdy = [[None] * len(xs) for _ in ys]
    gdx = [[None] * len(xs) for _ in ys]
    for m in acc:
        i, j = ys.index(round(m["y"], 1)), xs.index(round(m["x"], 1))
        py = coef[0, 0] + coef[0, 1] * m["y"] + coef[0, 2] * m["x"]
        px = coef[1, 0] + coef[1, 1] * m["y"] + coef[1, 2] * m["x"]
        gdy[i][j], gdx[i][j] = round(m["dy"] - py, 3), round(m["dx"] - px, 3)
    return {"y": ys, "x": xs, "dy": gdy, "dx": gdx}


def check_blank(canvas, level=None, probe=None):
    """Planes that read blank at a level although level 0 has data at the same depth (dropped slices)."""
    np = _np()
    meta = canvas.meta
    H, W = canvas.shape0
    probs = []
    ref = None
    for k in range(len(meta["levels"])):
        if level is not None and k != level:
            continue
        shp = meta["levels"][k].get("shape")
        if not shp:
            continue
        fac = _factors(meta["levels"])[k]
        fz = true_z_factor(meta, k)
        lv = canvas._level(k)
        n = 32
        py, px = probe if probe else (H / 2, W / 2)
        Y0, X0 = int(py / fac[1] - n / 2), int(px / fac[2] - n / 2)
        a = lv.read(0, shp[-3], Y0, Y0 + n, X0, X0 + n).astype(np.float32)
        for (kk, pl) in [(kk, p) for kk, ps in canvas.blank_planes.items() for p in ps]:
            if kk == k and pl < a.shape[0]:
                a[pl] = 0
        nz = (a > 0).mean((1, 2))
        if ref is None and k == 0:
            ref = nz
        if ref is None:
            continue
        for p in range(a.shape[0]):
            z0 = int(p * fz)
            interior = 0 < p < a.shape[0] - 1 and nz[p - 1] > 0.5 and nz[p + 1] > 0.5
            if nz[p] == 0 and (interior or (k > 0 and z0 < len(ref) and ref[z0] > 0.5)):
                probs.append({"level": k, "plane": p, "kind": "blank_plane"})
    return {"check": "blank", "verdict": "defect" if probs else "ok", "problems": probs}


# ================================================================ items: discovery and loading

def hf_url(path):
    return f"{HF_RESOLVE}/{path.strip('/')}"


def fetch_bytes(url, tries=5):
    import urllib.error
    import urllib.request
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kit-sentinel"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            err = e
        except Exception as e:  # noqa: BLE001  a dropped connection is retried
            err = e
        time.sleep(min(8, 0.5 * 2 ** i))
    raise SentinelError(f"{url}: {err}")


_MESHES = {}


def load_mesh(base_url, fetch=fetch_bytes):
    """Mesh from a tifxyz folder URL, with sha256 pins of its four files (the last two are kept in memory)."""
    if base_url in _MESHES:
        return _MESHES[base_url]
    m = _load_mesh(base_url, fetch)
    if len(_MESHES) >= 2:
        _MESHES.pop(next(iter(_MESHES)))
    _MESHES[base_url] = m
    return m


def _load_mesh(base_url, fetch=fetch_bytes):
    np = _np()
    import io
    pins = {}
    b = fetch(f"{base_url}/meta.json")
    if b is None:
        raise SentinelError(f"{base_url}/meta.json is not there")
    pins["meta.json"] = sha256_bytes(b)
    meta = json.loads(b)
    meta["name"] = base_url.rstrip("/").split("/")[-1]
    xyz = None
    for i, a in enumerate("xyz"):          # one file in memory at a time (Paris 4 meshes are 67 MB a file)
        b = fetch(f"{base_url}/{a}.tif")
        if b is None:
            raise SentinelError(f"{base_url}/{a}.tif is not there")
        pins[f"{a}.tif"] = sha256_bytes(b)
        arr = meshaudit.imread_capped(io.BytesIO(b))
        del b
        if xyz is None:
            xyz = np.empty(arr.shape + (3,), np.float32)
        xyz[..., i] = arr
        del arr
    bad = (xyz == -1).any(-1) | ~np.isfinite(xyz).all(-1) | (xyz == 0).all(-1)
    xyz[bad] = np.nan
    del bad
    return Mesh(xyz, meta.get("scale") or [1.0, 1.0], meta, pins)


def hf_listing(prefix, api=None):
    """[(path, type, size, xet_hash)] directly under a bucket prefix (anonymous Hub API)."""
    if api is None:
        from huggingface_hub import HfApi
        api = HfApi(token=False)
    out = []
    for it in api.list_bucket_tree(HF_BUCKET, prefix=prefix.strip("/"), recursive=False):
        out.append((it.path, getattr(it, "type", "file"), getattr(it, "size", None), getattr(it, "xet_hash", None)))
    return sorted(out)


SAMPLE_ALIASES = {"man5": "PHercMAN5", "phercparis4": "PHercParis4", "manb": "PHercMANB", "manbp": "PHercMANBp",
                  "p343p": "PHerc0343P", "500p2a": "PHerc0500P2"}


def sample_of(folder):
    """Catalog sample id for an HF ink/ scroll folder name (0009b, 841, man5, phercparis4, ...)."""
    f = folder.lower()
    if f in SAMPLE_ALIASES:
        return SAMPLE_ALIASES[f]
    m = re.match(r"(\d+)([a-z0-9]*)$", f)
    if m:
        return "PHerc" + m.group(1).zfill(4) + m.group(2).upper()
    return folder


def discover_hf(api=None, root="ink"):
    """Segment folders under the HF bucket's ink/: scroll folders, then segment folders; ink/unused/ one level
    deeper (ink/unused/<scroll>/<segment>)."""
    items = []
    for p, t, _, _ in hf_listing(root, api):
        if t != "directory":
            continue
        scrolls = [p]
        if p.endswith("/unused"):
            scrolls = [q for q, t2, _, _ in hf_listing(p, api) if t2 == "directory"]
        for sc in scrolls:
            for q, t2, _, _ in hf_listing(sc, api):
                if t2 == "directory" and not q.endswith((".zarr", "/preds", "/layers")):
                    items.append("hf:" + q)
    return items


def hf_item(path, api=None):
    """The files of one HF segment folder: canvas zarr, label zarrs, tifxyz, with listing hashes."""
    files = hf_listing(path, api)
    name = path.rstrip("/").split("/")[-1]
    zarrs = [p for p, t, _, _ in files if t == "directory" and p.endswith(".zarr")]
    canvas = next((z for z in zarrs if z.split("/")[-1] == name + ".zarr"), None)
    labels = [z for z in zarrs if z != canvas and re.search(r"(inklabels|supervision|validation|mask)", z)]
    has_mesh = all(any(p.endswith("/" + n) for p, t, _, _ in files) for n in ("x.tif", "y.tif", "z.tif"))
    listing = [[p.split("/")[-1], t, s, h] for p, t, s, h in files]
    return {"id": "hf:" + path, "path": path, "canvas": canvas, "labels": labels, "mesh": path if has_mesh else None,
            "sample": sample_of(path.split("/")[2] if path.startswith("ink/unused/") else path.split("/")[1])
            if path.startswith("ink/") else None,
            "listing_digest": sha256_bytes(json.dumps(listing).encode())[:16], "listing": listing}


def fingerprint_hf(item):
    """Change fingerprint of an HF folder: its listing (names, sizes, Xet hashes) and every zarr's root metadata."""
    h = hashlib.sha256(item["listing_digest"].encode())
    for z in [item["canvas"]] + item["labels"]:
        if not z:
            continue
        st = Store(hf_url(z))
        h.update(json.dumps(st.meta(), sort_keys=True).encode())
    return h.hexdigest()[:16]


# ================================================================ volume candidates and frames

def catalog_volumes(catalog, sample):
    """[(volume id, zarr URL, pixel_um)] of a catalog sample."""
    s = (catalog.get("samples") or {}).get(sample) or {}
    out = []
    for vid, v in sorted((s.get("volumes") or {}).items()):
        if not isinstance(v, dict):
            continue
        for d in v.get("data") or []:
            for o in d.get("origins") or []:
                p = (o.get("path") or "").rstrip("/")
                if p.endswith(".zarr") and not p.startswith("s3://"):
                    out.append((vid, f"{S3}/{p}", (v.get("properties") or {}).get("pixel_size_um")))
                    break
    seen, uniq = set(), []
    for r in out:
        if r[0] not in seen:
            seen.add(r[0])
            uniq.append(r)
    return uniq


def declared_volume(mesh, candidates):
    """The volume a mesh says it is in: an "-on-<14 digits>" name or meta.json's volume string matched to one
    candidate by pitch, energy and masking. (volume id or None, how)."""
    txt = " ".join(str(mesh.meta.get(k, "")) for k in ("volume", "uuid", "name"))
    m = re.search(r"-on-(\d{14})", txt) or re.search(r"(\d{14})", str(mesh.meta.get("volume", "")))
    if m and any(c[0] == m.group(1) for c in candidates):
        return m.group(1), "id"
    vol = str(mesh.meta.get("volume", ""))
    pm, em = re.search(r"(\d+\.\d+)um", vol), re.search(r"(\d+)keV", vol)
    if not pm:
        return None, "undeclared" if not vol else "unmatched"
    hits = []
    for vid, url, um in candidates:
        name = url.split("/")[-1]
        if um and abs(float(um) - float(pm.group(1))) > 0.002:
            continue
        if em and f"{em.group(1)}keV" not in name:
            continue
        if ("masked" in vol) != ("masked" in name):
            continue
        hits.append(vid)
    return (hits[0], "name") if len(hits) == 1 else (None, "ambiguous" if hits else "unmatched")


def ct_source(url):
    """F -> (Level, factor) of a CT volume, the level nearest F level-0 voxels per voxel, cached."""
    st = Store(url)
    fac = _factors(st.levels)
    memo = {}

    def get(F):
        k = min(range(len(st.levels)), key=lambda i: abs(math.log(fac[i][1] / F)) if st.levels[i]["shape"] else 1e9)
        if k not in memo:
            memo[k] = (st.level(k), fac[k])
        return memo[k]
    return get


def ct_level(url, want=4.0):
    """(Level, factor zyx) of a CT volume at the level nearest `want` level-0 voxels per voxel, with its store."""
    st = Store(url)
    fac = _factors(st.levels)
    k = min(range(len(st.levels)), key=lambda i: abs(fac[i][1] - want) if st.levels[i]["shape"] else 1e9)
    return (st.level(k), fac[k]), st


def frame_candidates(mesh, catalog, sample):
    lo, hi = mesh.bbox()
    out = []
    for vid, url, um in catalog_volumes(catalog, sample):
        try:
            st = Store(url)
        except Exception:  # noqa: BLE001  an unreadable volume is not a candidate
            continue
        shp = st.levels[0]["shape"]
        if not shp:
            continue
        z, y, x = shp[-3:]
        m = FRAME_MARGIN
        if (lo[0] >= -m * x and lo[1] >= -m * y and lo[2] >= -m * z
                and hi[0] <= x * (1 + m) and hi[1] <= y * (1 + m) and hi[2] <= z * (1 + m)):
            out.append((vid, url, um))
    return out


def check_frame(canvas, mesh, candidates, declared, log=None):
    """Which candidate volume's CT matches the canvas through this mesh (median PSR of three coarse windows)."""
    np = _np()
    H, W = canvas.shape0
    scores = []
    for vid, url, um in candidates:
        try:
            ct = ct_source(url)
        except Exception as e:  # noqa: BLE001
            scores.append({"volume": vid, "error": str(e)[:120]})
            continue
        psrs = []
        F = 16.0
        try:
            canvas.plan(F)
        except SentinelError:
            F = 4.0
        n = 64 if F == 16.0 else 128
        vy, vx = mesh.valid_cells()
        if not len(vy):
            break
        for q in (0.3, 0.5, 0.7):
            k = int(q * (len(vy) - 1))
            yc, xc = vy[k] / mesh.scale[0], vx[k] / mesh.scale[1]
            r0 = int(max(0, min(H - F * n, yc - F * n / 2)) // F * F)
            c0 = int(max(0, min(W - F * n, xc - F * n / 2)) // F * F)
            try:
                cv = canvas.window(F, r0, c0, n)
                ctw = ct_window(mesh, ct, F, r0, c0, n, lambda Y, X: (0 * Y, 0 * X))
            except SentinelError:
                continue
            valid = np.isfinite(ctw) & (cv > 0)
            if valid.mean() < 0.5:
                continue
            psrs.append(register(ctw, cv, n // 3, valid)[2])
        scores.append({"volume": vid, "psr": round(float(np.median(psrs)), 2) if psrs else None, "n": len(psrs)})
    good = [s for s in scores if s.get("psr") is not None]
    best = max(good, key=lambda s: s["psr"]) if good else None
    out = {"check": "frame", "declared": declared[0], "declared_how": declared[1], "candidates": scores}
    if not best or best["psr"] < PSR_MIN:
        out.update(verdict="info", kind="unresolved", detail="no candidate volume's CT matches the canvas")
        return out
    out["matched"] = best["volume"]
    if declared[0] and declared[0] != best["volume"]:
        dec = next((s for s in good if s["volume"] == declared[0]), None)
        if dec is None or dec["psr"] < PSR_MIN:
            out.update(verdict="defect", kind="wrong_frame",
                       detail=f"declares {declared[0]}, its CT matches {best['volume']}")
            return out
    out.update(verdict="ok" if declared[0] else "info", kind="matched" if declared[0] else "undeclared_matched")
    return out


# ================================================================ planted copies

def plant_canvas(canvas, plant):
    """A planted copy of a canvas (in memory, the source is never written) and its truth."""
    kind = plant["kind"]
    if kind == "shift":
        P = (float(plant["dy"]), float(plant["dx"]))
        c = Canvas(canvas.store, canvas.meta, transform=lambda Y, X: (Y + P[0], X + P[1]), shape=canvas.shape0)
        return c, {"shift": P}
    if kind == "scale":
        s = float(plant["s"])
        H, W = canvas.shape0
        c = Canvas(canvas.store, canvas.meta, transform=lambda Y, X: (Y / s, X / s),
                   shape=(int(round(H * s)), int(round(W * s))))
        return c, {"scale": s}
    if kind == "drop_meta":
        meta = json.loads(json.dumps(canvas.meta))
        lv = meta["levels"][plant["level"]]
        lv["shape"] = [plant.get("keep", max(1, lv["shape"][-3] // 4))] + lv["shape"][-2:]
        return Canvas(canvas.store, meta, shape=canvas.shape0), {"drop_meta": plant["level"]}
    if kind == "drop_planes":
        return Canvas(canvas.store, canvas.meta, shape=canvas.shape0,
                      blank_planes={plant["level"]: tuple(plant["planes"])}), {"drop_planes": plant["level"]}
    if kind in ("reset_scale", "fix_scale"):
        meta = json.loads(json.dumps(canvas.meta))
        n = len(meta["levels"][0].get("scale") or [1, 1, 1])
        if kind == "reset_scale":
            base = meta["levels"][0].get("scale") or [1.0] * n
            for lv in meta["levels"]:
                s = lv.get("scale") or [1.0] * n
                lv["scale"] = [a / b for a, b in zip(s, base)]
            meta["axes"] = [{"name": a.get("name"), "type": a.get("type")} for a in meta.get("axes") or []]
        else:
            p = float(plant["pitch"])
            base = meta["levels"][0].get("scale") or [1.0] * n
            for lv in meta["levels"]:
                s = lv.get("scale") or [1.0] * n
                lv["scale"] = [v / b * p for v, b in zip(s, base)]
            meta["axes"] = [{"name": a, "type": "space", "unit": "micrometer"} for a in "zyx"]
        return Canvas(canvas.store, meta, shape=canvas.shape0), {kind: True}
    raise SentinelError(f"unknown plant kind {kind!r}")


# ================================================================ one item, every check

def check_item(item_id, rule=None, image=False, plant=None, catalog=None, minmeta=None, log=None, api=None,
               image_checks=("frame", "canvas", "blank")):
    """Every check on one item. Refuses (verdict skip, reason rule) an excluded item before any read."""
    log = log or (lambda m: None)
    rule = rule or Rule()
    if rule.excluded(item_id):
        return {"item": "(skipped by rule)", "skipped": True}
    t0 = time.time()
    res = {"item": item_id, "version": VERSION, "checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "plant": plant, "checks": []}
    kind, _, path = item_id.partition(":")
    if kind == "hf":
        it = hf_item(path, api)
        res["listing_digest"] = it["listing_digest"]
        canvas_url = hf_url(it["canvas"]) if it["canvas"] else None
        mesh_url = hf_url(it["mesh"]) if it["mesh"] else None
        label_urls = {z.split("/")[-1]: hf_url(z) for z in it["labels"]}
        sample = it["sample"]
    elif kind == "s3":
        canvas_url = f"{S3}/{path}"
        mesh_url, sample = s3_mesh_for(path, catalog)
        label_urls = {}
    elif kind == "s3vol":
        st = Store(f"{S3}/{path}")
        meta = st.meta()
        if plant and plant["kind"] in ("reset_scale", "fix_scale", "drop_meta"):
            meta = plant_canvas(_MetaOnly(st, meta), plant)[0].meta
        vid = (re.match(r"(\d{14})", path.split("/")[-1]) or [None, None])[1]
        pitch, src = known_pitch(st.name, vid, minmeta, catalog)
        res["checks"] = [check_pyramid(meta), check_scale(meta, pitch, src, "volume")]
        return _finish(res, t0)
    else:
        raise SentinelError(f"{item_id}: an item is hf:PATH, s3:PATH or s3vol:PATH")
    if not canvas_url:
        res["checks"].append({"check": "canvas", "verdict": "skip", "why": "no canvas zarr named after the folder"})
        return _finish(res, t0)
    store = Store(canvas_url)
    canvas = Canvas(store)
    truth = None
    if plant and plant.get("pitch") == "name":
        plant = dict(plant, pitch=known_pitch(store.name)[0])
        if plant["pitch"] is None:
            raise SentinelError(f"{store.name}: no pitch in the name for a fix_scale plant")
    if plant and plant["kind"] not in ("label_scale", "label_same", "frame"):
        canvas, truth = plant_canvas(canvas, plant)
    res["truth"] = truth
    res["checks"].append(check_pyramid(canvas.meta))
    cpitch, csrc = known_pitch(store.name)
    res["checks"].append(check_scale(canvas.meta, cpitch, csrc, kind="canvas"))
    mesh = None
    if mesh_url:
        try:
            mesh = load_mesh(mesh_url)
            res["pins"] = {f"{n}": h for n, h in mesh.pins.items()}
        except SentinelError as e:
            res["checks"].append({"check": "mesh", "verdict": "info", "detail": str(e)})
    labels = {}
    for n, u in label_urls.items():
        try:
            s = Store(u)
            labels[n] = tuple(s.levels[0]["shape"][-2:]) if s.levels[0]["shape"] else None
        except Exception as e:  # noqa: BLE001
            labels[n] = None
            log(f"{n}: {e}")
    if plant and plant["kind"] == "label_scale":
        s = float(plant["s"])
        H, W = canvas.shape0
        labels = {"planted_inklabels.zarr": (int(round(H * s)), int(round(W * s)))}
        res["truth"] = {"label_scale": s}
    elif plant and plant["kind"] == "label_same":
        labels = {"planted_inklabels.zarr": tuple(canvas.shape0)}
    res["checks"].append(check_labels(canvas.shape0, labels, mesh.grid_shape if mesh is not None else None))
    if image and mesh is not None:
        cands = frame_candidates(mesh, catalog or {}, sample) if catalog else []
        declared = declared_volume(mesh, cands)
        if plant and plant["kind"] == "frame":
            if plant["declare"] == "other":
                plant = dict(plant, declare=other_volume(catalog, item_id, declared[0]))
                res["plant"] = plant
            declared = (plant["declare"], "planted")
            res["truth"] = {"frame": plant["declare"]}
        if "frame" in image_checks or "canvas" in image_checks:
            fr = check_frame(canvas, mesh, cands, declared, log)
            res["checks"].append(fr)
            vol = fr.get("matched") or declared[0]
            url = next((c[1] for c in cands if c[0] == vol), None)
        if "canvas" in image_checks:
            if url:
                ct = ct_source(url)
                res["ct_volume"] = vol
                res["checks"].append(check_canvas(canvas, mesh, ct, log=log))
            else:
                res["checks"].append({"check": "canvas", "verdict": "info", "kind": "not_measured",
                                      "detail": "no CT volume for this mesh"})
        if "blank" in image_checks:
            vy, vx = mesh.valid_cells()
            probe = (float(_np().median(vy)) / mesh.scale[0], float(_np().median(vx)) / mesh.scale[1])
            res["checks"].append(check_blank(canvas, probe=probe))
    return _finish(res, t0)


class _MetaOnly:
    def __init__(self, store, meta):
        self.store, self.meta = store, meta
        lv0 = meta["levels"][0]["shape"] or [1, 1, 1]
        self.shape0 = (lv0[-2], lv0[-1])


def _finish(res, t0):
    v = [c.get("verdict") for c in res["checks"]]
    res["verdict"] = "defect" if "defect" in v else "ok"
    res["defects"] = sorted({c["check"] + ":" + str(c.get("kind") or (c.get("problems") or [{}])[0].get("kind"))
                             for c in res["checks"] if c.get("verdict") == "defect"})
    res["seconds"] = round(time.time() - t0, 1)
    return res


def s3_mesh_for(path, catalog):
    """(mesh URL, sample) for an S3 surface volume path: the segment's mesh named for the surface volume's volume."""
    if not catalog:
        raise SentinelError("an s3: item needs the catalog (metadata.json)")
    sample = path.split("/")[0]
    seg_folder = "/".join(path.split("/")[:3])
    vid = meshaudit._volume_id_in(path.split("/")[-1])
    s = catalog["samples"].get(sample) or {}
    for gid, g in (s.get("segments") or {}).items():
        sv, meshes = meshaudit.segment_entries(g)
        if any(p.rstrip("/") == path.rstrip("/") for p in sv):
            named = [m for t, m in meshes if vid and f"-on-{vid}" in m]
            if named:
                return f"{S3}/{named[0]}", sample
    raise SentinelError(f"{path}: no mesh named for volume {vid} in {seg_folder}")


# ================================================================ table

def table_entry(res):
    """The loader table entry for one check result (None when the canvas was not measured)."""
    c = next((c for c in res["checks"] if c["check"] == "canvas" and c.get("kind") in
              ("aligned", "constant", "affine", "regions")), None)
    if c is None or res.get("plant"):
        return None
    path = res["item"].split(":", 1)[1]
    e = {"path": path, "model": c["kind"], "affine": c["affine"], "resid_rms": c["resid_rms"],
         "max_offset": c["max_offset"], "n_windows": c["n_accepted"], "ct_volume": res.get("ct_volume"),
         "pins": res.get("pins") or {}, "listing_digest": res.get("listing_digest"), "checked": res["checked"]}
    if c["kind"] == "regions":
        e["grid"] = c["grid"]
    if c["kind"] == "aligned":
        e["affine"] = {"dy": [0.0, 0.0, 0.0], "dx": [0.0, 0.0, 0.0]}
    return e


def build_table(results, source="kit sentinel"):
    from . import sentinel_table as st
    entries = [e for e in (table_entry(r) for r in results) if e]
    return {"schema": st.SCHEMA, "made_by": source, "version": VERSION,
            "convention": "canvas level-0 pixel (y, x) shows tifxyz full-resolution cell (y + dy, x + dx); "
                          "dy = a + b*y + c*x (affine lists a, b, c); villa issue #2370",
            "align_tol_px": ALIGN_TOL, "entries": sorted(entries, key=lambda e: e["path"])}


# ================================================================ scan (change detection)

def scan(state_path=STATE, hf=True, s3=True, rule=None, api=None, get=None):
    """Fingerprint every item and compare with the last scan. Returns {"new": [...], "changed": [...], "gone": [...],
    "coverage": ...}; the state file keeps the fingerprints and the queue."""
    rule = rule or Rule()
    state_path = Path(state_path)
    old = json.loads(state_path.read_text()) if state_path.exists() else {"items": {}, "queue": []}
    now = {}
    if hf:
        for iid in discover_hf(api):
            if rule.excluded(iid):
                continue
            try:
                now[iid] = fingerprint_hf(hf_item(iid.split(":", 1)[1], api))
            except Exception as e:  # noqa: BLE001  record and go on
                now[iid] = "error:" + str(e)[:80]
    if s3:
        from . import scancatalog
        cat = json.loads(fetch_bytes(scancatalog.METADATA_URL) if get is None else get(scancatalog.METADATA_URL))
        for sid, s in sorted((cat.get("samples") or {}).items()):
            for vid, url, um in catalog_volumes(cat, sid):
                iid = "s3vol:" + url[len(S3) + 1:]
                if rule.excluded(iid):
                    continue
                try:
                    now[iid] = sha256_bytes(json.dumps(Store(url).meta(), sort_keys=True).encode())[:16]
                except Exception as e:  # noqa: BLE001
                    now[iid] = "error:" + str(e)[:80]
    o = old.get("items", {})
    diff = {"new": sorted(k for k in now if k not in o), "changed": sorted(k for k in now if k in o and o[k] != now[k]),
            "gone": sorted(k for k in o if k not in now and not rule.excluded(k))}
    queue = sorted(set(old.get("queue", [])) | set(diff["new"]) | set(diff["changed"]))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"items": now, "queue": queue,
                                      "scanned": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=1))
    diff["queue"] = queue
    diff["items"] = len(now)
    diff["coverage"] = rule.coverage()
    return diff


# ================================================================ render preflight

def preflight(mesh_dir, volume, fetch=fetch_bytes, listing=None):
    """Before vc_render_tifxyz: is this mesh in the frame of this volume? Metadata only (#1845)."""
    warn, info = [], []
    mesh_dir = str(mesh_dir).rstrip("/")
    vol_id = (re.search(r"(\d{14})", str(volume).split("/")[-1]) or [None, None])[1]
    mesh_name = mesh_dir.split("/")[-1]
    on = re.search(r"-on-(\d{14})", mesh_name)
    meta_b = fetch(mesh_dir + "/meta.json") if "://" in mesh_dir else \
        (Path(mesh_dir, "meta.json").read_bytes() if Path(mesh_dir, "meta.json").exists() else None)
    meta = json.loads(meta_b) if meta_b else {}
    if on and vol_id and on.group(1) != vol_id:
        warn.append(f"the mesh is named for volume {on.group(1)}, the render reads {vol_id}")
    siblings = listing if listing is not None else []
    match = [s for s in siblings if vol_id and f"-on-{vol_id}" in s]
    if vol_id and match and mesh_name not in [m.rstrip("/").split("/")[-1] for m in match]:
        warn.append(f"this segment has a mesh made in volume {vol_id}'s frame: {match[0].rstrip('/').split('/')[-1]}")
    bb = meta.get("bbox")
    try:
        st = Store(volume)
        shp = st.levels[0]["shape"]
    except Exception as e:  # noqa: BLE001
        shp = None
        info.append(f"volume not read: {str(e)[:80]}")
    if bb and shp:
        z, y, x = shp[-3:]
        lo, hi = bb[0], bb[1]
        m = FRAME_MARGIN
        if not (lo[0] >= -m * x and lo[1] >= -m * y and lo[2] >= -m * z and hi[0] <= x * (1 + m)
                and hi[1] <= y * (1 + m) and hi[2] <= z * (1 + m)):
            warn.append(f"the mesh bbox {[round(v) for v in lo]} to {[round(v) for v in hi]} (x y z) does not fit "
                        f"the volume's {x} x {y} x {z} voxels")
    if not on and not meta.get("volume"):
        info.append("the mesh does not say which volume it was made in")
    return {"check": "preflight", "mesh": mesh_dir, "volume": volume, "verdict": "defect" if warn else "ok",
            "warnings": warn, "info": info}


def render_args(argv):
    """(segmentation, volume) from a vc_render_tifxyz command line."""
    seg = vol = None
    i = 0
    while i < len(argv):
        a = argv[i]
        for flag, short in (("--segmentation", "-s"), ("--volume", "-v")):
            if a in (flag, short) and i + 1 < len(argv):
                if flag == "--segmentation":
                    seg = argv[i + 1]
                else:
                    vol = argv[i + 1]
            elif a.startswith(flag + "="):
                if flag == "--segmentation":
                    seg = a.split("=", 1)[1]
                else:
                    vol = a.split("=", 1)[1]
        i += 1
    return seg, vol


# ================================================================ planted-defect controls

SHIFTS = (4, 6, 10, 16, 25, 40, 64, 100, 150, 200, 250, 300)     # level-0 px
SCALES = (0.9, 0.95, 0.98, 1.02, 1.05, 1.1)


def image_plants(seed=20261104):
    """The planted canvas defects that need CT (shifts in random directions, resampled canvases, a wrong frame)."""
    import random
    rnd = random.Random(seed)
    out = []
    for m in SHIFTS:
        ang = rnd.uniform(0, 2 * math.pi)
        out.append({"kind": "shift", "dy": round(m * math.sin(ang), 2), "dx": round(m * math.cos(ang), 2)})
    for s in SCALES:
        out.append({"kind": "scale", "s": s})
    out.append({"kind": "frame", "declare": "other"})
    return out


def plants_for(i, per_item=3, seed=20261104):
    """Pool item i's plants: per_item image plants, rotating through image_plants(), then every metadata plant."""
    imgs = image_plants(seed)
    mine = [imgs[(i * per_item + j) % len(imgs)] for j in range(per_item)]
    return mine + [p for p in control_plants(seed) if p["kind"] not in ("shift", "scale", "frame")]


def control_plants(seed=20261104):
    """Every planted defect kind with its parameters (fixed by the preregistration)."""
    out = image_plants(seed)
    for s in SCALES:
        out.append({"kind": "label_scale", "s": s})
    out.append({"kind": "label_same"})
    out.append({"kind": "drop_meta", "level": 2})
    out.append({"kind": "drop_meta", "level": 1, "keep": 20})
    out.append({"kind": "drop_planes", "level": 1, "planes": [10, 11]})
    out.append({"kind": "drop_planes", "level": 0, "planes": [40]})
    out.append({"kind": "reset_scale"})
    out.append({"kind": "fix_scale", "pitch": "name"})
    return out


PLANT_IMAGE = {"shift": ("frame", "canvas"), "scale": ("frame", "canvas"), "drop_planes": ("blank",),
               "frame": ("frame",)}


def other_volume(catalog, item_id, ct_volume):
    """A volume of the same sample other than the one the item's canvas was rendered from (for the frame plant)."""
    path = item_id.split(":", 1)[1]
    sample = path.split("/")[0] if not path.startswith("ink/") else sample_of(path.split("/")[1])
    vols = [v for v, _, _ in catalog_volumes(catalog, sample) if v != ct_volume]
    return vols[0] if vols else None


def score_plant(base, planted):
    """Did the planted copy's checks catch its plant? (caught, error in px or None, what)."""
    np = _np()
    p = planted["plant"]
    kind = p["kind"]
    get = lambda r, name: next((c for c in r["checks"] if c["check"] == name), {})  # noqa: E731
    if kind in ("shift", "scale"):
        cb, cp = get(base, "canvas"), get(planted, "canvas")
        if cp.get("verdict") != "defect":
            return False, None, cp.get("kind")
        if not cb.get("affine") or not cp.get("affine"):
            return True, None, "no base model"
        A = lambda c, y, x: (c["dy"][0] + c["dy"][1] * y + c["dy"][2] * x,   # noqa: E731
                             c["dx"][0] + c["dx"][1] * y + c["dx"][2] * x)
        errs = []
        for w in [w for w in cp["windows"] if w["accepted"]]:
            y, x = w["y"], w["x"]
            if kind == "shift":
                by, bx = A(cb["affine"], y + p["dy"], x + p["dx"])
                ty, tx_ = p["dy"] + by, p["dx"] + bx
            else:
                s = p["s"]
                by, bx = A(cb["affine"], y / s, x / s)
                ty, tx_ = y / s - y + by, x / s - x + bx
            my, mx = A(cp["affine"], y, x) if cp["kind"] != "regions" else (w["dy"], w["dx"])
            errs.append(math.hypot(my - ty, mx - tx_))
        return True, (round(float(np.median(errs)), 3) if errs else None), cp.get("kind")
    if kind in ("label_scale",):
        lb = get(planted, "labels")
        return lb.get("verdict") == "defect", None, "labels"
    if kind == "label_same":
        lb = get(planted, "labels")
        return lb.get("verdict") != "defect", None, "unaltered label must pass"
    if kind in ("drop_meta",):
        return get(planted, "pyramid").get("verdict") == "defect", None, "pyramid"
    if kind == "drop_planes":
        return get(planted, "blank").get("verdict") == "defect", None, "blank"
    if kind == "reset_scale":
        return get(planted, "scale").get("verdict") == "defect", None, "scale"
    if kind == "fix_scale":
        return get(planted, "scale").get("verdict") == "ok", None, "a correct scale must pass"
    if kind == "frame":
        return get(planted, "frame").get("kind") == "wrong_frame", None, "frame"
    return False, None, "unknown"


# ================================================================ command line

def _print_result(res, out=sys.stdout):
    if res.get("skipped"):
        print("skipped by rule", file=out)
        return
    print(f"{res['item']}: {res['verdict']}" + (f" ({', '.join(res['defects'])})" if res["defects"] else ""), file=out)
    for c in res["checks"]:
        line = f"  {c['check']:<8} {c.get('verdict', '?'):<7} {c.get('kind') or ''}"
        if c["check"] == "canvas" and c.get("affine"):
            line += (f"  max {c['max_offset']} px, median dy dx {c['median_offset']}, resid {c['resid_rms']}, "
                     f"{c['n_accepted']}/{c['n_windows']} windows")
        elif c.get("problems"):
            line += "  " + "; ".join(json.dumps(p) for p in c["problems"][:3])
        elif c.get("detail"):
            line += "  " + c["detail"]
        print(line, file=out)


def build_parser(p):
    sub = p.add_subparsers(dest="action", required=True)
    a = sub.add_parser("scan", help="fingerprint every HF ink/ folder and S3 CT volume; queue the new and changed")
    a.add_argument("--state", default=str(STATE))
    a.add_argument("--no-hf", action="store_true")
    a.add_argument("--no-s3", action="store_true")
    a.add_argument("--exclude", default=None, help="local exclusion file (never committed)")
    a.add_argument("--exit-code", action="store_true", help="exit 3 when anything is new or changed")
    a.add_argument("--json", action="store_true")
    a = sub.add_parser("queue", help="what the last scan queued")
    a.add_argument("--state", default=str(STATE))
    a.add_argument("--json", action="store_true")
    a = sub.add_parser("check", help="every check on items (hf:PATH, s3:PATH, s3vol:PATH)")
    a.add_argument("items", nargs="*")
    a.add_argument("--queued", action="store_true", help="check what the last scan queued, then clear them")
    a.add_argument("--state", default=str(STATE))
    a.add_argument("--image", action="store_true", help="also the CT checks: canvas offsets, frame, blank planes")
    a.add_argument("--plant", default=None, help="a planted-defect JSON, applied to an in-memory copy")
    a.add_argument("--exclude", default=None)
    a.add_argument("--out", default=None, help="folder for one JSON result per item")
    a.add_argument("--exit-code", action="store_true", help="exit 3 when any item has a defect")
    a.add_argument("--json", action="store_true")
    a = sub.add_parser("table", help="the loader offset table from a folder of check results")
    a.add_argument("results", help="folder of check results (kit sentinel check --out)")
    a.add_argument("--out", required=True)
    a.add_argument("--json", action="store_true")
    a = sub.add_parser("preflight", help="before vc_render_tifxyz: is the mesh in the volume's frame? (metadata)")
    a.add_argument("--mesh", default=None)
    a.add_argument("--volume", default=None)
    a.add_argument("--force", action="store_true", help="run the render even when the preflight warns")
    a.add_argument("--json", action="store_true")
    a.add_argument("render", nargs=argparse.REMAINDER, help="-- vc_render_tifxyz ARGS: run it when the check passes")
    a = sub.add_parser("controls", help="the planted-defect controls on a pool of public segments")
    a.add_argument("pool", help="JSON list of items (hf:... or s3:...) for the controls")
    a.add_argument("--out", required=True)
    a.add_argument("--exclude", default=None)
    a.add_argument("--limit", type=int, default=0)
    a.add_argument("--shard", default=None, help="K/N: run pool items K, K+N, K+2N, ... (parallel processes)")
    a.add_argument("--per-item", type=int, default=3, help="image plants per pool item, rotating through the list")
    a.add_argument("--json", action="store_true")
    a = sub.add_parser("summarize", help="pool the controls files of several shards into one summary")
    a.add_argument("files", nargs="+")
    return p


def _catalogs():
    cat = json.loads(_maybe_gunzip(fetch_bytes(METADATA)))
    mm = fetch_bytes(METADATA_MIN)
    minmeta = json.loads(_maybe_gunzip(mm)) if mm else None
    return cat, minmeta


def _maybe_gunzip(b):
    import gzip
    return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b


def run(args):
    if args.action == "scan":
        diff = scan(args.state, hf=not args.no_hf, s3=not args.no_s3, rule=Rule.load(args.exclude))
        if args.json:
            print(json.dumps(diff, indent=1))
        else:
            print(f"bucket sentinel scan: {diff['items']} items, {len(diff['new'])} new, {len(diff['changed'])} "
                  f"changed, {len(diff['gone'])} gone, {len(diff['queue'])} queued; "
                  f"{diff['coverage']['skipped_by_rule']} skipped by rule")
            for k in ("new", "changed", "gone"):
                for i in diff[k][:40]:
                    print(f"  {k:<8} {i}")
        return 3 if args.exit_code and (diff["new"] or diff["changed"]) else 0
    if args.action == "queue":
        st = json.loads(Path(args.state).read_text()) if Path(args.state).exists() else {"queue": []}
        print(json.dumps(st.get("queue", []), indent=1) if args.json else "\n".join(st.get("queue", [])) or "empty")
        return 0
    if args.action == "check":
        rule = Rule.load(args.exclude)
        items = list(args.items)
        if args.queued:
            st = json.loads(Path(args.state).read_text()) if Path(args.state).exists() else {"queue": []}
            items += st.get("queue", [])
        if not items:
            print("kit sentinel check: no items (give hf:PATH, s3:PATH or s3vol:PATH, or --queued)", file=sys.stderr)
            return 2
        cat = minmeta = None
        if args.image or any(i.startswith(("s3:", "s3vol:")) for i in items):
            cat, minmeta = _catalogs()
        plant = json.loads(args.plant) if args.plant else None
        results, defect = [], False
        for iid in items:
            try:
                r = check_item(iid, rule, image=args.image, plant=plant, catalog=cat, minmeta=minmeta,
                               log=lambda m: print(m, file=sys.stderr))
            except Exception as e:  # noqa: BLE001  one bad item does not stop the run
                r = {"item": iid, "verdict": "error", "error": str(e)[:300], "checks": [], "defects": []}
            results.append(r)
            defect |= r.get("verdict") == "defect"
            if args.out and not r.get("skipped"):
                Path(args.out).mkdir(parents=True, exist_ok=True)
                safe = re.sub(r"[^A-Za-z0-9._-]+", "_", iid)
                Path(args.out, safe + ".json").write_text(json.dumps(r, indent=1))
            if not args.json:
                _print_result(r)
        if args.queued and not plant:
            done = {r["item"] for r in results if r.get("verdict") in ("ok", "defect")}
            st = json.loads(Path(args.state).read_text())
            st["queue"] = [q for q in st.get("queue", []) if q not in done]
            Path(args.state).write_text(json.dumps(st, indent=1))
        cov = rule.coverage()
        if args.json:
            print(json.dumps({"results": [r for r in results if not r.get("skipped")], "coverage": cov}, indent=1))
        else:
            print(f"{cov['skipped_by_rule']} skipped by rule")
        return 3 if args.exit_code and defect else 0
    if args.action == "table":
        res = [json.loads(p.read_text()) for p in sorted(Path(args.results).glob("*.json"))]
        doc = build_table(res)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(doc, indent=1) + "\n")
        print(json.dumps(doc, indent=1) if args.json else f"{len(doc['entries'])} entries written to {args.out}")
        return 0
    if args.action == "preflight":
        render = [a for a in (args.render or []) if a != "--"]
        seg, vol = render_args(render[1:]) if render else (None, None)
        mesh, volume = args.mesh or seg, args.volume or vol
        if not mesh or not volume:
            print("kit sentinel preflight: give --mesh and --volume, or -- vc_render_tifxyz -s MESH -v VOLUME ...",
                  file=sys.stderr)
            return 2
        listing = None
        if not str(mesh).startswith(("http", "s3:")) and Path(mesh).parent.is_dir():
            listing = [p.name for p in Path(mesh).parent.iterdir()]
        r = preflight(mesh, volume, listing=listing)
        if args.json:
            print(json.dumps(r, indent=1))
        else:
            print(f"preflight {r['verdict']}: {mesh} on {volume}")
            for w in r["warnings"]:
                print(f"  warning: {w}")
            for i in r["info"]:
                print(f"  note: {i}")
        if r["verdict"] == "defect" and not args.force:
            if render:
                print("not rendering (pass --force to render anyway)", file=sys.stderr)
            return 3
        if render:
            import subprocess
            return subprocess.call(render)
        return 0
    if args.action == "controls":
        return run_controls(args)
    if args.action == "summarize":
        rows = [r for f in args.files for r in json.loads(Path(f).read_text())["rows"]]
        s = summarize_controls(rows)
        print(json.dumps(s, indent=1))
        return 0 if s["pass"] else 3
    return 2


def run_controls(args):
    """Planted-defect controls on each pool item: the base, then every plant; recall, error, false flags."""
    rule = Rule.load(args.exclude)
    pool = json.loads(Path(args.pool).read_text())
    if args.limit:
        pool = pool[:args.limit]
    index = {iid: i for i, iid in enumerate(pool)}
    if args.shard:
        k, n = (int(v) for v in args.shard.split("/"))
        pool = [iid for i, iid in enumerate(pool) if i % n == k]
    cat, minmeta = _catalogs()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for iid in pool:
        try:
            base = check_item(iid, rule, image=True, catalog=cat, minmeta=minmeta)
        except Exception as e:  # noqa: BLE001  an item that cannot be read is recorded, not fatal
            rows.append({"item": iid, "plant": None, "base_kind": "error: " + str(e)[:120], "flag": False})
            continue
        if base.get("skipped"):
            continue
        (out / (re.sub(r"[^A-Za-z0-9._-]+", "_", iid) + ".base.json")).write_text(json.dumps(base, indent=1))
        cb = next((c for c in base["checks"] if c["check"] == "canvas"), {})
        rows.append({"item": iid, "plant": None, "base_kind": cb.get("kind"), "flag": cb.get("verdict") == "defect"})
        print(f"{iid}: base {cb.get('kind')} {cb.get('median_offset')}", file=sys.stderr)
        if cb.get("kind") not in ("aligned", "constant", "affine", "regions"):
            continue
        for p in plants_for(index[iid], args.per_item):
            try:
                r = check_item(iid, rule, image=p["kind"] in PLANT_IMAGE, plant=p, catalog=cat, minmeta=minmeta,
                               image_checks=PLANT_IMAGE.get(p["kind"], ()))
                caught, err, what = score_plant(base, r)
            except Exception as e:  # noqa: BLE001
                caught, err, what = False, None, "error: " + str(e)[:120]
            rows.append({"item": iid, "plant": p, "caught": caught, "error_px": err, "what": what})
            print(f"  {json.dumps(p)}: caught={caught} err={err} {what}", file=sys.stderr)
    summary = summarize_controls(rows)
    name = "controls.json" if not args.shard else f"controls-{args.shard.replace('/', 'of')}.json"
    (out / name).write_text(json.dumps({"rows": rows, "summary": summary}, indent=1))
    print("CONTROLS " + json.dumps({"rows": rows, "summary": summary}))
    print(json.dumps(summary, indent=1))
    return 0 if summary["pass"] else 3


def summarize_controls(rows):
    np = _np()
    plants = [r for r in rows if r["plant"]]
    must = [r for r in plants if r["plant"]["kind"] not in ("label_same", "fix_scale")]
    neg = [r for r in plants if r["plant"]["kind"] in ("label_same", "fix_scale")]
    shifts = [r for r in must if r["plant"]["kind"] in ("shift", "scale") and r["error_px"] is not None]
    bases = [r for r in rows if r["plant"] is None]
    recall = sum(r["caught"] for r in must) / len(must) if must else float("nan")
    errs = [r["error_px"] for r in shifts]
    within = sum(e <= 2.0 for e in errs) / len(errs) if errs else float("nan")
    base_flags = sum(bool(r.get("flag")) for r in bases)
    n_neg = len(neg) + len(bases)
    false_flags = (sum(not r["caught"] for r in neg) + base_flags) / n_neg if n_neg else 0.0
    by_kind = {}
    for r in must:
        k = r["plant"]["kind"]
        by_kind.setdefault(k, [0, 0])
        by_kind[k][0] += r["caught"]
        by_kind[k][1] += 1
    s = {"items": len(bases), "base_flags": base_flags, "plants": len(must),
         "recall": round(recall, 4), "by_kind": by_kind, "shift_error_median_px": round(float(np.median(errs)), 3)
         if errs else None, "shift_within_2px": round(within, 4) if errs else None,
         "negatives": n_neg, "false_flag_rate": round(false_flags, 4)}
    s["pass"] = bool(recall >= 0.95 and errs and within >= 0.95 and false_flags <= 0.05)
    return s


def cmd_sentinel(args):
    try:
        return run(args)
    except SentinelError as e:
        print(f"kit sentinel: {e}", file=sys.stderr)
        return 2


def main(argv=None):
    if sys.stdout.isatty():              # the Scrolls look (AGENTS.md rule 17)
        from . import termstyle
        termstyle.script()
    p = argparse.ArgumentParser(prog="python -m kit.sentinel", description=__doc__.split("\n")[0])
    build_parser(p)
    return cmd_sentinel(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
