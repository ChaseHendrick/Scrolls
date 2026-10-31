"""Shared helpers for Ringleader: the umbilicus axis, the catalog transform, an optional z exclusion list, and the
reference geometry the scorer needs (turn angles, seam masks, point matching).

Geometry only. Reads public open-data files; nothing here is a reading.
"""

import gzip
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"

# PHerc0139: the m7 surface prediction lives in the frame of volume 20250728140407 (9.362 um); the published
# umbilicus is in the frame of volume 20260102150214. The open-data catalog's volume transform maps one to the other.
P0139 = {
    "sample": "PHerc0139",
    "m7": f"{BUCKET}/PHerc0139/representations/predictions/surfaces/"
          "20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr/0",
    "umbilicus": f"{BUCKET}/PHerc0139/representations/umbilicus/20260102150214-umbilicus-20260826112529.json",
    "from": "20250728140407", "to": "20260102150214",
}
CATALOG = HERE.parent / "catalog-0139.json"     # reduced copy of the bucket's metadata.json (one transform)
CATALOG_URL = f"{BUCKET}/metadata.json"


# ---------------------------------------------------------------- affines and the axis

def apply(affine, P):
    """3 x 4 affine applied to points (N, 3)."""
    A = np.asarray(affine, float)
    P = np.asarray(P, float)
    return P @ A[:, :3].T + A[:, 3]


def invert(affine):
    A = np.asarray(affine, float)
    Li = np.linalg.inv(A[:, :3])
    return np.concatenate([Li, (-Li @ A[:, 3])[:, None]], axis=1)


class Axis:
    """The umbilicus as x(z), y(z) by linear interpolation of control points given as (x, y, z)."""

    def __init__(self, xyz):
        a = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
        a = a[np.argsort(a[:, 2], kind="stable")]
        if len(a) < 2:
            raise ValueError("an axis needs at least two points")
        self.pts = a

    @classmethod
    def from_json(cls, path, affine=None):
        """villa's umbilicus JSON ({"control_points": [{x, y, z}]}, or a list of [x, y, z]); the affine maps its
        frame to the frame the slices are in."""
        d = json.loads(Path(path).read_text())
        if isinstance(d, dict):
            d = d.get("control_points") or d.get("points") or list(d.values())
        pts = [[p["x"], p["y"], p["z"]] if isinstance(p, dict) else list(p)[:3] for p in d]
        P = np.asarray(pts, dtype=np.float64)
        if affine is not None:
            P = apply(affine, P)
        return cls(P)

    def at(self, z):
        z = np.asarray(z, dtype=np.float64)
        return np.interp(z, self.pts[:, 2], self.pts[:, 0]), np.interp(z, self.pts[:, 2], self.pts[:, 1])


def _get(url, tries=4, timeout=60):
    err = None
    for t in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise
            err = e
        except Exception as e:  # network
            err = e
        time.sleep(2 ** t)
    raise RuntimeError(f"{url}: {err}")


def fetch(url, cache_dir):
    """A file from a URL, cached by its name in cache_dir; a local path is returned as it is."""
    if not str(url).startswith(("http://", "https://")):
        return Path(url)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / str(url).rsplit("/", 1)[-1]
    if not p.is_file():
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(_get(url))
        tmp.rename(p)
    return p


def catalog_matrix(sample, src, dst, catalog=None):
    """The 3 x 4 matrix from volume src to volume dst in the open-data catalog (a path or URL; default the reduced
    copy beside this file, which holds only PHerc0139's 20250728140407 to 20260102150214 transform)."""
    catalog = catalog or CATALOG
    raw = _get(catalog) if str(catalog).startswith(("http://", "https://")) else Path(catalog).read_bytes()
    if raw[:2] == b"\x1f\x8b":                  # the bucket serves metadata.json gzip-compressed
        raw = gzip.decompress(raw)
    d = json.loads(raw)
    for g in d["samples"][sample]["sample"]["properties"]["volume_transforms"]:
        if g["from_volume_id"] == src:
            for t in g["transforms"]:
                if t["to_volume_id"] == dst:
                    return np.asarray(t["matrix"], dtype=float)
    raise KeyError(f"{sample}: no transform {src} to {dst} in {catalog}")


def axis_0139(cache, catalog=None):
    """PHerc0139's published umbilicus in the m7 frame (volume 20250728140407), through the catalog transform."""
    M = catalog_matrix(P0139["sample"], P0139["from"], P0139["to"], catalog)
    return Axis.from_json(fetch(P0139["umbilicus"], Path(cache) / "json"), affine=invert(M))


def load_axis(cache, umbilicus=None, catalog=None):
    """The axis in the slices' frame: a given umbilicus JSON (already in that frame), else PHerc0139's."""
    return Axis.from_json(fetch(umbilicus, Path(cache) / "json")) if umbilicus else axis_0139(cache, catalog)


# ---------------------------------------------------------------- an optional z exclusion list

def parse_ranges(text):
    """'lo:hi,lo:hi' (inclusive; a single z is 'z') to [(lo, hi)]; a file path holding that text works too."""
    if not text:
        return []
    p = Path(text)
    if p.is_file():
        text = p.read_text()
    out = []
    for w in text.replace("\n", ",").split(","):
        w = w.strip()
        if not w or w.startswith("#"):
            continue
        lo, _, hi = w.partition(":")
        lo, hi = int(lo), int(hi or lo)
        if lo > hi:
            raise SystemExit(f"bad z range {w}")
        out.append((lo, hi))
    return out


def check_z(zs, exclude=()):
    """Stop when any slice lies in a user-given exclusion range (such as data you keep held out)."""
    for z in zs:
        for lo, hi in exclude:
            if lo <= int(z) <= hi:
                raise SystemExit(f"z {z} lies in the excluded range {lo} to {hi}")


# ---------------------------------------------------------------- reference geometry (for the scorer)

SEAM_TOL_CELLS = 1.5        # same height and angle: within this many native grid steps (as arc length)


def axis_at(axis_zyx, z):
    """(N, 2) axis (x, y) at heights z; axis_zyx rows are (z, y, x)."""
    z = np.asarray(z, dtype=np.float64)
    return np.stack([np.interp(z, axis_zyx[:, 0], axis_zyx[:, 2]), np.interp(z, axis_zyx[:, 0], axis_zyx[:, 1])], -1)


def turn_angles(xyz, valid, axis_zyx):
    """Angle in degrees of each vertex about the axis at its own height, unwrapped along the grid direction in
    which the angle turns (the columns of a tifxyz winding) and aligned row to row, so that two vertices of one
    mesh one turn apart differ by 360. NaN where not valid."""
    X = np.asarray(xyz, dtype=np.float64)
    ok = np.asarray(valid, bool) & np.isfinite(X).all(-1)
    th = np.full(ok.shape, np.nan)
    if ok.any():
        c = axis_at(axis_zyx, X[ok][:, 2])
        th[ok] = np.arctan2(X[ok][:, 1] - c[:, 1], X[ok][:, 0] - c[:, 0])

    def turning(a, ax):
        dd = np.diff(a, axis=ax)
        dd = (dd + np.pi) % (2 * np.pi) - np.pi
        return float(np.nanmedian(np.abs(dd))) if np.isfinite(dd).any() else 0.0

    along = 1 if turning(th, 1) >= turning(th, 0) else 0
    T, okT = (th, ok) if along == 1 else (th.T, ok.T)
    out = np.full(T.shape, np.nan)
    ref = np.full(T.shape[1], np.nan)          # last unwrapped angle seen in each column
    for i in range(T.shape[0]):
        cols = np.flatnonzero(okT[i])
        if len(cols) == 0:
            continue
        t = np.unwrap(T[i, cols])
        have = np.flatnonzero(np.isfinite(ref))
        if len(have):
            prev = np.interp(cols, have, ref[have])
            t = t - 2 * np.pi * np.round(np.median(t - prev) / (2 * np.pi))
        out[i, cols] = t
        ref[cols] = t
    out = np.degrees(out)
    return out if along == 1 else out.T


def _turn_geometry(r, axis_zyx):
    """(flat indices of usable vertices, z, unwrapped angle in degrees, radius, median radius) of one reference."""
    th = turn_angles(r.xyz, r.valid, axis_zyx)
    ok = r.valid & np.isfinite(th)
    flat = np.flatnonzero(ok.ravel())
    X = r.xyz.reshape(-1, 3)[flat]
    c = axis_at(axis_zyx, X[:, 2])
    rad = np.hypot(X[:, 0] - c[:, 0], X[:, 1] - c[:, 1])
    return flat, X[:, 2], th.ravel()[flat], rad, (float(np.median(rad)) if len(rad) else 1.0)


def _sector_tree(z, ang_deg, rmed, tol, wrap=True):
    """KD-tree over (height, arc length at radius rmed) in units of tol; with wrap, angles are taken mod 360 and
    the points are repeated one turn either side so a query near 0 or 360 degrees finds both."""
    from scipy.spatial import cKDTree
    a = np.radians(np.mod(ang_deg, 360.0) if wrap else ang_deg)
    q = np.stack([z / tol, a * rmed / tol], -1)
    if not len(q):
        return None
    if wrap:
        turn = 2 * np.pi * rmed / tol
        q = np.concatenate([q, q + [0.0, turn], q - [0.0, turn]])
    return cKDTree(q)


def _within(tree, z, ang_deg, rmed, tol, wrap=True):
    """Per query point: whether the tree holds a point within one tolerance (Chebyshev) in height and arc."""
    if len(z) == 0 or tree is None:
        return np.zeros(len(z), bool)
    a = np.radians(np.mod(ang_deg, 360.0) if wrap else ang_deg)
    q = np.stack([z / tol, a * rmed / tol], -1)
    dist, _ = tree.query(q, k=1, p=np.inf, distance_upper_bound=1.0 + 1e-9)
    return np.isfinite(dist)


def seam_masks(refs, axis_zyx, tol_cells=SEAM_TOL_CELLS):
    """Seam-overlap vertices of a reference stack, as ({gid: bool mask over that reference's grid}, {name: info}).

    A published winding traced past a full turn covers the angles just past its seam twice: once on its own sheet
    and once, one turn out, on the sheet where the next winding starts. For each mesh, vertices one turn apart (same
    height and angle within tol_cells grid steps of arc, unwrapped angles 360 degrees apart) form its doubly covered
    sector. Of the two copies, the one farther from the axis is the traced end on the next turn's sheet. Masked:
    that outer copy, and every vertex of the next winding by rank whose height and angle (mod 360) lie within
    tol_cells of it. info[name]["outer"] says which copy was outer ("later" or "earlier" in the traced angle)."""
    by_rank = {r.attrs.get("rank"): r for r in refs if isinstance(r.attrs.get("rank"), int)}
    masks = {r.gid: np.zeros(r.valid.shape, bool) for r in refs}
    geo = {r.gid: _turn_geometry(r, axis_zyx) for r in refs}
    info = {}
    for r in refs:
        flat, z, th, rad, rmed = geo[r.gid]
        tol = tol_cells * (r.step if math.isfinite(r.step) else 1.0)
        rec = {"overlap_vertices": 0, "outer": None}
        info[r.name] = rec
        if len(flat) < 2:
            continue
        tree = _sector_tree(z, th, rmed, tol, wrap=False)
        q = np.stack([z / tol, np.radians(th) * rmed / tol], -1)
        turn = 2 * np.pi * rmed / tol
        d_e, j_e = tree.query(q - [0.0, turn], k=1, p=np.inf, distance_upper_bound=1.0 + 1e-9)
        later = np.isfinite(d_e)                   # has a copy one turn earlier
        if not later.any():
            continue
        d_l, _ = tree.query(q + [0.0, turn], k=1, p=np.inf, distance_upper_bound=1.0 + 1e-9)
        earlier = np.isfinite(d_l)                 # has a copy one turn later
        dr = float(np.median(rad[later] - rad[j_e[later]]))
        outer = later if dr > 0 else earlier
        rec.update(overlap_vertices=int(later.sum()), outer="later" if dr > 0 else "earlier")
        masks[r.gid].ravel()[flat[outer]] = True
        nxt = by_rank.get(r.attrs.get("rank", -9) + 1) if isinstance(r.attrs.get("rank"), int) else None
        if nxt is None:
            continue
        nflat, nz, nth, _, _ = geo[nxt.gid]
        st = _sector_tree(z[outer], th[outer], rmed, tol)
        hit = _within(st, nz, nth, rmed, tol)
        masks[nxt.gid].ravel()[nflat[hit]] = True
    return masks, info


def matches(P, refs, workers=2):
    """(S, IN, J) of kit.sheetrefs.match for every reference, as (references, points) arrays: the signed offset
    along the reference normal, whether the point projects inside its footprint, and the native vertex index."""
    from kit import sheetrefs as sr
    R, N = len(refs), len(P)
    S = np.full((R, N), np.nan)
    IN = np.zeros((R, N), bool)
    J = np.zeros((R, N), np.int64)
    for i, r in enumerate(refs):
        m = sr.match(P, r, workers)
        S[i], IN[i], J[i] = m[0], m[1], m[2]
    return S, IN, J


def nearest_on(S, IN, J, refs, d):
    """Per point: the winding id it lies on (the reference label at its nearest footprint match, when that match is
    within d voxels) or -1, and the row of that nearest reference (-1 when none)."""
    N = S.shape[1]
    if not len(refs):
        return np.full(N, -1, np.int64), np.full(N, -1, np.int64)
    ar = np.arange(N)
    absd = np.where(IN, np.abs(S), np.inf)
    best = np.argmin(absd, axis=0)
    bestd = absd[best, ar]
    has = np.isfinite(bestd)
    jb = J[best, ar]
    lab = np.full(N, -1, np.int64)
    for i, r in enumerate(refs):
        sel = has & (best == i)
        lab[sel] = r.label.ravel()[jb[sel]]
    on = has & (bestd <= d)
    return np.where(on, lab, -1), np.where(has, best, -1)
