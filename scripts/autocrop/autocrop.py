"""Autocrop: keep the regions of a villa spiral fit whose winding order is most likely right.

villa's spiral fit (lasagna `fit_spiral`) puts one surface per winding through a whole band of a scroll. Some regions
of it sit on the right winding and some do not. Autocrop splits each winding of the fit's tifxyz export into cells of
4 by 8 grid vertices, scores every cell by four signals that need no truth, and keeps the better half:

- seed: the share of the cell's vertices that a second fit (another seed, the sibling) puts on the same winding,
  after the two fits' global winding offset;
- normal: how well the fit's normal agrees with the lasagna field's normal (nx, ny);
- spacing: how far the distance to the inner and outer winding, scaled by the field's grad_mag density, is from one
  sheet spacing;
- regularity: how far the cell's grid edges are from the fit's median grid step.

Each signal becomes a percentile rank, the four ranks are averaged, the average is smoothed over each cell's 3 by 3
neighbors on its own winding, and the top half is kept (rule main). Kept cells that touch form components; each
component of at least 4 cells is written as one villa point collection of relative windings (one point per cell,
all on the same winding), with a control file holding the same components shifted along their winding.

    python autocrop.py crops --fit RUN --sibling RUN2 --lasagna LASAGNA --windings W0 W1 --out-dir OUT
    python autocrop.py score --crops OUT/crops-NAME.json --pairs PAIRS.json --out SCORE.json
    python autocrop.py readout SCORE.json ... --out READOUT.json
    python autocrop.py demo --out-dir DEMO

`crops` needs no truth. `score` and `readout` check the rule against winding truth you bring as a pair table, with
equal-count random crops and a shuffled-signals control, the way the rule was tested. `demo` makes a synthetic fit
pair with a planted wrong-winding patch and checks that the rule drops it. Every fit, crop and score is model
output, never a reading; nothing here reads ink.

Needs numpy, scipy, tifffile and zarr, and spiralfiteval (github.com/jo-tud/spiralfiteval, MIT, commit 217947a) for
the sibling projection and the grid refinement, as in the tests of the rule.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

VERSION = "1.0.0"
CELL = (4, 8)               # rows, columns of a winding's export grid in one cell
TOL_N = 10.0                # sibling projection: largest distance along the normal, in fit voxels
LAS_SCALE = 4.0             # fit voxels per stored lasagna voxel
DENSITY = 0.14 / 1000.0 * 4.0   # villa's fitter density per fit voxel per raw grad_mag unit
SHARE = 0.5                 # rule main keeps this share of the cells
MIN_CELLS = 4               # smallest component written as a point collection
DRAWS = 1000                # random crops per fit in `score`
SHUFFLES = 50               # shuffled-signals control draws per fit in `score`
SIGNALS = ("seed", "normal", "spacing", "regularity")
HIGHER_BETTER = {"seed": True, "normal": True, "spacing": False, "regularity": False}
# readout bars, as frozen for the tests of rule main
BAR_G = 0.05                # BEATS_CONTROL: mean G_rand at least this
BAR_ABOVE = 0.8             # and at least this share of scored fits above their random draws' 97.5th percentile
CONTROL_MAX = 0.02          # VOID when the mean (shuffled E minus random E) reaches this
NO_GAIN_G = 0.02            # NO_GAIN: mean G_rand under this, or
NO_GAIN_FITS = 2            # at least this many fits under their random draws' mean
MIN_PAIRS = 200             # a fit with fewer kept pairs than this is void
MIN_KEPT_SHARE = 0.10       # or with a smaller share of its pairs kept


class CropError(ValueError):
    pass


def sha256(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- the fit

def export_dir(d) -> Path:
    """The tifxyz folder of a fit: the folder itself, or its spiral-checkpoint.tifxyz child."""
    d = Path(d)
    if (d / "spiral-checkpoint.tifxyz").is_dir():
        d = d / "spiral-checkpoint.tifxyz"
    if not (d / "meta.json").is_file():
        raise CropError(f"no meta.json in {d}: give the fit's run folder or its spiral-checkpoint.tifxyz folder")
    return d


def export_grids(d) -> dict:
    """{winding: (P (H, W, 3) xyz, valid)} of villa's spiral-fit export: one tifxyz surface with the windings side by
    side, each winding's columns given by meta.json's winding_column_ranges, -1 where the fit has no point."""
    import tifffile
    d = export_dir(d)
    x, y, z = (tifffile.imread(d / f"{c}.tif").astype(np.float32) for c in "xyz")
    meta = json.loads((d / "meta.json").read_text())
    if "winding_column_ranges" not in meta:
        raise CropError(f"{d / 'meta.json'} has no winding_column_ranges: not a spiral-fit export")
    valid = (z > 0) & np.isfinite(x) & np.isfinite(y) & np.isfinite(z) & (x != -1)
    first = int(meta.get("first_winding", 10))
    P = np.stack([x, y, z], -1)
    out = {}
    for i, (a, b) in enumerate(meta["winding_column_ranges"]):
        v = valid[:, a:b]
        if v.any():
            out[first + i] = (P[:, a:b], v)
    return out


class Axis:
    """The umbilicus as x(z), y(z) by linear interpolation of its control points (x, y, z)."""

    def __init__(self, xyz):
        a = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
        a = a[np.argsort(a[:, 2], kind="stable")]
        if len(a) < 2:
            raise CropError("an umbilicus needs at least two points")
        self.pts = a

    @classmethod
    def from_json(cls, path):
        """villa's umbilicus JSON: {"control_points": [{x, y, z}, ...]} or a list of [x, y, z]."""
        d = json.loads(Path(path).read_text())
        if isinstance(d, dict):
            d = d.get("control_points") or d.get("points") or list(d.values())
        return cls([[p["x"], p["y"], p["z"]] if isinstance(p, dict) else list(p)[:3] for p in d])

    def at(self, z):
        z = np.asarray(z, dtype=np.float64)
        return np.interp(z, self.pts[:, 2], self.pts[:, 0]), np.interp(z, self.pts[:, 2], self.pts[:, 1])


def build_fit_cells(grids, name, bbox, column_sense, cell=CELL, max_step=5.0):
    """spiralfiteval.fit.build_fit (commit 217947a) line for line, plus the (winding, row block, column block) of
    every vertex it keeps. A winding whose valid vertices all lie outside the box is skipped before the refine."""
    from spiralfiteval import fit as sf
    xyz, f, wn, nrm, steps, cells = [], [], [], [], [], []
    lo = hi = None
    if bbox is not None:
        lo, hi = np.asarray(bbox[0]), np.asarray(bbox[1])
    for w, (P, valid) in grids.items():
        step = np.nan
        both = valid[:, :-1] & valid[:, 1:]
        if both.any():
            step = float(np.median(np.linalg.norm(P[:, 1:][both] - P[:, :-1][both], axis=-1)))
        factor = int(np.ceil(step / max_step)) if np.isfinite(step) and step > max_step else 1
        if np.isfinite(step):
            steps.append(step / factor)
        if bbox is not None:
            V = P[valid]
            if not len(V) or np.any(V.max(0) < lo) or np.any(V.min(0) >= hi):
                continue
        H0, W0 = valid.shape
        P2, v2 = sf.refine_grid(P, valid, factor)
        H, W = v2.shape
        t = np.broadcast_to(np.arange(W, dtype=np.float64) / (factor * W0), (H, W))
        if column_sense < 0:
            t = 1.0 - 1.0 / W0 - t
        N = sf.grid_normals(P2, v2)
        sel = v2 & np.isfinite(N).all(-1)
        if bbox is not None:
            sel = sel & np.all((P2 >= lo) & (P2 < hi), axis=-1)
        if not sel.any():
            continue
        xyz.append(P2[sel])
        f.append(w + t[sel])
        wn.append(np.full(int(sel.sum()), w, np.int32))
        nrm.append(N[sel])
        r, c = np.nonzero(sel)
        cells.append(np.stack([np.full(len(r), w), (r // factor) // cell[0], (c // factor) // cell[1]], 1))
    if not xyz:
        raise CropError(f"no fit vertices inside {bbox}")
    fit = sf.Fit(name, np.concatenate(xyz), np.concatenate(f), np.concatenate(wn), np.concatenate(nrm),
                 list(grids), float(np.median(steps)) if steps else float("nan"))
    return fit, np.concatenate(cells).astype(np.int64)


class CellFit:
    """spiralfiteval's Fit plus the export cell of every fit vertex, and a projection that returns the vertex."""

    def __init__(self, grids, name, bbox=None, cell=CELL):
        from spiralfiteval import fit as sf
        self.grids = grids
        self.sense = sf.check_seams(grids)["sense"]
        self.fit, self.cell_of_vertex = build_fit_cells(grids, name, bbox, self.sense, cell)

    def project(self, pts, tol=TOL_N, k=16, chunk=200_000):
        """(f, dn, vertex index or -1): spiralfiteval Fit.project's choice, with the index of the vertex it took."""
        f = self.fit
        pts = np.asarray(pts, np.float64)
        tol_n = np.broadcast_to(np.asarray(tol, np.float64), (len(pts),))
        r = float(np.hypot(f.step, tol_n.max())) + 1e-6
        F, DN, I = (np.full(len(pts), np.nan), np.full(len(pts), np.nan), np.full(len(pts), -1, np.int64))
        for s in range(0, len(pts), chunk):
            p, tn = pts[s:s + chunk], tol_n[s:s + chunk]
            d, i = f.tree.query(p, k=k, distance_upper_bound=r)
            if d.ndim == 1:
                d, i = d[:, None], i[:, None]
            ok = np.isfinite(d)
            i = np.where(ok, i, 0)
            v = p[:, None, :] - f.xyz[i]
            n = f.normal[i]
            dn = np.abs(np.einsum("pkc,pkc->pk", v, n))
            dt = np.sqrt(np.maximum(np.einsum("pkc,pkc->pk", v, v) - dn ** 2, 0))
            cand = ok & (dt <= f.step) & (dn <= tn[:, None])
            dn = np.where(cand, dn, np.inf)
            best = np.argmin(dn, axis=1)
            rows = np.arange(len(p))
            hit = np.isfinite(dn[rows, best])
            vi = i[rows, best]
            F[s:s + chunk] = np.where(hit, f.f[vi], np.nan)
            DN[s:s + chunk] = np.where(hit, dn[rows, best], np.nan)
            I[s:s + chunk] = np.where(hit, vi, -1)
        return F, DN, I


def own_spiral_time(grids, sense, w, cols):
    """Spiral time f = w + t of original-grid columns, as spiralfiteval numbers them (t in units of W0 columns)."""
    W0 = grids[w][1].shape[1]
    t = np.asarray(cols, np.float64) / W0
    if sense < 0:
        t = 1.0 - 1.0 / W0 - t
    return w + t


def band_cells(grids, w0, w1) -> list:
    """Every (winding, row block, column block) cell with at least one valid vertex, windings w0 to w1."""
    cells = []
    for w, (P, valid) in sorted(grids.items()):
        if not w0 <= w <= w1:
            continue
        H, W = valid.shape
        for rb in range(int(math.ceil(H / CELL[0]))):
            for cb in range(int(math.ceil(W / CELL[1]))):
                if valid[rb * CELL[0]:(rb + 1) * CELL[0], cb * CELL[1]:(cb + 1) * CELL[1]].any():
                    cells.append((w, rb, cb))
    return cells


# ---------------------------------------------------------------- signals

def cell_vertices(grids, cells):
    """{cell: (rows, cols)} of the original export grid vertices of each cell (valid ones only)."""
    out = {}
    for (w, rb, cb) in cells:
        P, valid = grids[w]
        r0, c0 = rb * CELL[0], cb * CELL[1]
        sub = valid[r0:r0 + CELL[0], c0:c0 + CELL[1]]
        r, c = np.nonzero(sub)
        out[(w, rb, cb)] = (r + r0, c + c0)
    return out


def grid_normal_xy(P, valid, r, c):
    """Unit xy part of the grid normal at original-grid vertices (row, column), and the full normals."""
    from spiralfiteval import fit as sf
    N = sf.grid_normals(P, valid)[r, c].astype(np.float64)
    xy = N[:, :2]
    nn = np.linalg.norm(xy, axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return xy / nn, N


def regularity(P, valid, r, c):
    """max(|ln(|du| / s)|, |ln(|dv| / s)|) at vertices, s the winding's median column step."""
    H, W = valid.shape
    both_c = valid[:, :-1] & valid[:, 1:]
    s = float(np.median(np.linalg.norm(P[:, 1:][both_c] - P[:, :-1][both_c], axis=-1))) if both_c.any() else np.nan
    out = np.full(len(r), np.nan)
    for k, (i, j) in enumerate(zip(r, c)):
        vals = []
        for di, dj in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            ii, jj = i + di, j + dj
            if 0 <= ii < H and 0 <= jj < W and valid[ii, jj]:
                d = float(np.linalg.norm(P[ii, jj] - P[i, j]))
                if d > 0 and s > 0:
                    vals.append(abs(math.log(d / s)))
        if vals:
            out[k] = max(vals)
    return out


class Lasagna:
    """Nearest-sample reader of a lasagna field's nx, ny and grad_mag arrays, in fit coordinates."""

    def __init__(self, root):
        import zarr
        self.root = Path(root)
        self.arr = {}
        for name in ("nx", "ny", "grad_mag"):
            hits = sorted(self.root.rglob(f"*{name}*.zarr"))
            if not hits:
                raise CropError(f"no {name} zarr under {root}")
            g = zarr.open(str(hits[0]), mode="r")
            self.arr[name] = g if hasattr(g, "shape") else g[sorted(g.array_keys())[0]]
        self.cache = {}

    def sample(self, name, xyz):
        """Nearest stored sample at fit xyz (index = round-to-even of xyz / LAS_SCALE, zyx order)."""
        a = self.arr[name]
        idx = np.rint(np.asarray(xyz, float)[:, ::-1] / LAS_SCALE).astype(np.int64)
        out = np.full(len(idx), np.nan)
        ok = np.all((idx >= 0) & (idx < np.asarray(a.shape)[None, :]), axis=1)
        if ok.any():
            lo = idx[ok].min(0)
            hi = idx[ok].max(0) + 1
            key = (name, tuple(lo), tuple(hi))
            block = self.cache.get(key)
            if block is None:
                block = np.asarray(a[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]])
                self.cache = {key: block}
            j = idx[ok] - lo
            out[ok] = block[j[:, 0], j[:, 1], j[:, 2]].astype(float)
        return out

    def normal_xy(self, xyz):
        nx, ny = self.sample("nx", xyz), self.sample("ny", xyz)
        missing = (nx == 0) & (ny == 0)
        v = np.stack([(nx - 128.0) / 127.0, (ny - 128.0) / 127.0], 1)
        v[missing | ~np.isfinite(nx) | ~np.isfinite(ny)] = np.nan
        n = np.linalg.norm(v, axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            return v / n

    def density(self, xyz):
        g = self.sample("grad_mag", xyz)
        return np.where(np.isfinite(g) & (g > 0), g * DENSITY, np.nan)


def radial_profile(P, valid, center_xy):
    """Per row: (angle sorted, radius) of a winding's valid vertices about the axis point of that row."""
    out = []
    for i in range(P.shape[0]):
        v = valid[i]
        if v.sum() < 4:
            out.append(None)
            continue
        q = P[i, v, :2] - center_xy[i][None, :]
        th = np.arctan2(q[:, 1], q[:, 0])
        rr = np.hypot(q[:, 0], q[:, 1])
        o = np.argsort(th)
        out.append((th[o], rr[o]))
    return out


def radius_at(profile, row, th):
    pr = profile[row] if 0 <= row < len(profile) else None
    if pr is None:
        return np.nan
    t, rr = pr
    return float(np.interp(th, t, rr, period=2 * np.pi))


def axis_xy(axis, zs):
    x, y = axis.at(np.asarray(zs, float))
    return np.stack([np.asarray(x, float), np.asarray(y, float)], 1)


def compute_signals(grids, sense, sib: CellFit, las: Lasagna, cells, axis: Axis):
    """({cell: {signal: value}}, info) over the given cells of the fit."""
    verts = cell_vertices(grids, cells)
    allp, f1 = [], []
    for cell, (r, c) in verts.items():
        P, _ = grids[cell[0]]
        allp.append(P[r, c].astype(np.float64))
        f1.append(own_spiral_time(grids, sense, cell[0], c))
    allp = np.concatenate(allp) if allp else np.zeros((0, 3))
    f1 = np.concatenate(f1) if f1 else np.zeros(0)
    f2, _, _ = sib.project(allp)
    d = f2 - f1
    hit = np.isfinite(d)
    O = float(np.median(d[hit])) if hit.any() else 0.0
    agree = hit & (np.rint(d - O) == 0)
    sig = {cell: {} for cell in verts}
    start = 0
    for cell, (r, c) in verts.items():
        n = len(r)
        sig[cell]["seed"] = float(agree[start:start + n].mean()) if n else np.nan
        start += n
    profiles, zrows = {}, {}
    for w, (P, valid) in grids.items():
        zrows[w] = np.array([np.median(P[i, valid[i], 2]) if valid[i].any() else np.nan for i in range(P.shape[0])])
    for cell, (r, c) in verts.items():
        w = cell[0]
        P, valid = grids[w]
        if not len(r):
            for s in ("normal", "spacing", "regularity"):
                sig[cell][s] = np.nan
            continue
        xyz = P[r, c].astype(np.float64)
        nxy, N = grid_normal_xy(P, valid, r, c)
        lxy = las.normal_xy(xyz)
        cosang = np.abs(np.sum(nxy * lxy, 1))
        sig[cell]["normal"] = float(np.nanmedian(cosang)) if np.isfinite(cosang).any() else np.nan
        sig[cell]["regularity"] = float(np.nanmedian(regularity(P, valid, r, c)))
        cen = axis_xy(axis, xyz[:, 2])
        q = xyz[:, :2] - cen
        th = np.arctan2(q[:, 1], q[:, 0])
        rad = np.hypot(q[:, 0], q[:, 1])
        with np.errstate(invalid="ignore", divide="ignore"):
            rhat = q / rad[:, None]
        cosr = np.abs(np.sum(rhat * nxy, 1))
        rho = las.density(xyz)
        vals = []
        for k in range(len(r)):
            sides = []
            for nb in (w - 1, w + 1):
                if nb not in grids:
                    continue
                if nb not in profiles:
                    Pn, vn = grids[nb]
                    zr = zrows[nb]
                    cz = axis_xy(axis, np.where(np.isfinite(zr), zr, np.nanmedian(zr)))
                    profiles[nb] = radial_profile(Pn, vn, cz)
                rn = radius_at(profiles[nb], int(r[k]), th[k])
                if np.isfinite(rn):
                    sides.append(abs(rn - rad[k]) * cosr[k] * rho[k])
            sides = [s for s in sides if np.isfinite(s) and s > 0]
            if sides:
                vals.append(float(np.mean([abs(math.log(s)) for s in sides])))
        sig[cell]["spacing"] = float(np.median(vals)) if vals else np.nan
    return sig, {"seed_offset": O, "seed_hit_share": float(hit.mean()) if len(hit) else None,
                 "vertices": int(len(allp))}


# ---------------------------------------------------------------- the rule

def average_ranks(v) -> np.ndarray:
    """Ranks 1 to n of v, ties sharing their mean rank (scipy.stats.rankdata's 'average' method)."""
    v = np.asarray(v, float)
    order = np.argsort(v, kind="mergesort")
    sv = v[order]
    rk = np.empty(len(v))
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and sv[j + 1] == sv[i]:
            j += 1
        rk[order[i:j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return rk


def ranks(values: dict, higher_better: bool) -> dict:
    """Percentile rank of each cell's value among the cells that have one (1 best, 0 worst); ties share the mean."""
    keys = [k for k, v in values.items() if v is not None and np.isfinite(v)]
    if not keys:
        return {}
    v = np.array([values[k] for k in keys], float)
    if not higher_better:
        v = -v
    rk = (average_ranks(v) - 1) / max(len(v) - 1, 1)
    return dict(zip(keys, rk.tolist()))


def scores(sig: dict) -> dict:
    """{name: {cell: score}}: each signal's ranks, their mean ("combined") and the mean smoothed over each cell's
    3 by 3 neighbors on its winding ("smooth", rule main's score). Higher is better."""
    cells = list(sig)
    out, rk = {}, {}
    for s in SIGNALS:
        rk[s] = ranks({c: sig[c].get(s) for c in cells}, HIGHER_BETTER[s])
        out[s] = rk[s]
    comb = {}
    for c in cells:
        vals = [rk[s][c] for s in SIGNALS if c in rk[s]]
        if vals:
            comb[c] = float(np.mean(vals))
    out["combined"] = comb
    smooth = {}
    for c in comb:
        w, a, b = c
        nb = [comb[(w, a + i, b + j)] for i in (-1, 0, 1) for j in (-1, 0, 1) if (w, a + i, b + j) in comb]
        smooth[c] = float(np.mean(nb))
    out["smooth"] = smooth
    return out


def keep_top(score: dict, zone: list, share: float) -> set:
    """The top `share` of zone cells by score (cells without a score rank last; ties by zone order)."""
    n = int(round(share * len(zone)))
    order = sorted(range(len(zone)), key=lambda i: (-(score.get(zone[i], -1.0)), i))
    return {zone[i] for i in order[:n]}


def components(kept, min_cells=MIN_CELLS):
    """4-connected components of kept cells within each winding grid, each of at least min_cells cells."""
    left = set(kept)
    out = []
    for c in sorted(kept):
        if c not in left:
            continue
        comp, todo = [], [c]
        left.discard(c)
        while todo:
            w, a, b = todo.pop()
            comp.append((w, a, b))
            for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (w, a + d[0], b + d[1])
                if n in left:
                    left.discard(n)
                    todo.append(n)
        if len(comp) >= min_cells:
            out.append(sorted(comp))
    return sorted(out)


def cell_point(grids, cell):
    """The valid original-grid vertex nearest the cell's center, as fit xyz, or None."""
    w, rb, cb = cell
    P, valid = grids[w]
    r0, c0 = rb * CELL[0], cb * CELL[1]
    sub = valid[r0:r0 + CELL[0], c0:c0 + CELL[1]]
    if not sub.any():
        return None
    r, c = np.nonzero(sub)
    k = int(np.argmin((r - (CELL[0] - 1) / 2.0) ** 2 + (c - (CELL[1] - 1) / 2.0) ** 2))
    return [round(float(v), 3) for v in P[r0 + r[k], c0 + c[k]]]


def shifted(comps, grids, seed=0):
    """The control: each component moved along its own winding by a random whole number of column blocks
    (1 to n - 1 of that winding's n blocks, modulo n), shape and size kept."""
    rng = np.random.default_rng(seed)
    out = []
    for comp in comps:
        w = comp[0][0]
        n = int(math.ceil(grids[w][1].shape[1] / CELL[1]))
        k = int(rng.integers(1, n)) if n > 1 else 0
        out.append(sorted((w, a, (b + k) % n) for (_, a, b) in comp))
    return out


def crop_collections(comps, grids, tag):
    """villa point collections (relative windings): one per component, one point per cell, all at wind_a 0, so each
    component is same-winding evidence, as a surface patch is. Components left with under 4 points are dropped."""
    cols, n_pts = {}, 0
    for i, comp in enumerate(comps):
        pts = [p for p in (cell_point(grids, c) for c in comp) if p is not None]
        if len(pts) < 4:
            continue
        cols[str(len(cols) + 1)] = {"name": f"{tag}_{i}", "metadata": {"winding_is_absolute": False,
                                    "generator": f"autocrop {tag}: one same-winding strip per kept component"},
                                    "points": {str(j + 1): {"p": p, "wind_a": 0.0} for j, p in enumerate(pts)}}
        n_pts += len(pts)
    return {"vc_pointcollections_json_version": "1", "collections": cols}, n_pts


def cell_key(c) -> str:
    return ",".join(str(int(v)) for v in c)


def parse_key(k) -> tuple:
    return tuple(int(v) for v in k.split(","))


# ---------------------------------------------------------------- scoring against truth

def outcome(exact, cell_a, cell_b, kept: set):
    """(inside mask, kept pairs, exact share among them): a pair is kept when both its cells are kept."""
    inside = np.array([(ca in kept) and (cb in kept) for ca, cb in zip(cell_a, cell_b)], bool)
    n = int(inside.sum())
    return inside, n, (float(exact[inside].mean()) if n else None)


def random_crops(exact, cell_a, cell_b, zone, n_keep, dw, draws=DRAWS, seed=0):
    """Equal-count random crops of the zone: the mean, 2.5th and 97.5th percentile of the exact share among kept
    pairs over the draws, and the dw mix of all kept pairs (for the dw-standardized comparison)."""
    rng = np.random.default_rng(seed)
    zi = {c: i for i, c in enumerate(zone)}
    ia = np.array([zi[c] for c in cell_a])
    ib = np.array([zi[c] for c in cell_b])
    shares, counts = [], []
    mix = np.zeros(7)
    for _ in range(draws):
        m = np.zeros(len(zone), bool)
        m[rng.choice(len(zone), n_keep, replace=False)] = True
        inside = m[ia] & m[ib]
        k = int(inside.sum())
        counts.append(k)
        if k:
            shares.append(float(exact[inside].mean()))
            mix += np.bincount(dw[inside].astype(int), minlength=7)[:7]
    s = np.array(shares)
    return {"mean": float(s.mean()) if len(s) else None, "p975": float(np.percentile(s, 97.5)) if len(s) else None,
            "p025": float(np.percentile(s, 2.5)) if len(s) else None, "draws_with_pairs": int(len(s)),
            "mean_pairs": float(np.mean(counts)), "dw_mix": (mix / mix.sum()).tolist() if mix.sum() else None}


def dw_standardized(exact, inside, dw, mix):
    """The kept pairs' exact share reweighted per dw (1 to 6) to the random draws' dw mix."""
    if mix is None:
        return None
    num = den = 0.0
    for d in range(1, 7):
        m = inside & (dw == d)
        if m.any() and mix[d] > 0:
            num += mix[d] * float(exact[m].mean())
            den += mix[d]
    return num / den if den else None


def shuffled_signals(sig: dict, seed: int) -> dict:
    """The signal records permuted across the cells (which cells exist unchanged)."""
    cells = list(sig)
    perm = np.random.default_rng(seed).permutation(len(cells))
    return {c: sig[cells[perm[i]]] for i, c in enumerate(cells)}


def zone_plus(zone, have) -> list:
    """The zone and every cell of `have` in its 3 by 3 ring on the same winding."""
    return sorted({(w, x + i, y + j) for (w, x, y) in zone for i in (-1, 0, 1) for j in (-1, 0, 1)
                   if (w, x + i, y + j) in have})


def score_fit(crops: dict, pairs: dict, draws=DRAWS, shuffles=SHUFFLES, seed=0) -> dict:
    """Rule main against a pair table, as tested: signals ranked over the cells holding truth pairs and their
    3 by 3 ring, top half of the truth cells kept, against equal-count random crops and shuffled signals."""
    sig = {parse_key(k): v for k, v in crops["signals"].items()}
    ca = [tuple(int(v) for v in c) for c in pairs["cell_a"]]
    cb = [tuple(int(v) for v in c) for c in pairs["cell_b"]]
    ex = np.asarray(pairs["exact"], bool)
    dw = np.asarray(pairs["dw"], int)
    if not (len(ca) == len(cb) == len(ex) == len(dw)):
        raise CropError("the pair table's cell_a, cell_b, exact and dw differ in length")
    if not len(ex):
        raise CropError("the pair table holds no pairs")
    missing = sorted({c for c in ca + cb if c not in sig})
    if missing:
        raise CropError(f"{len(missing)} pair cells have no signals in the crops file (first {list(missing[0])}): "
                        "run crops over the windings the truth crosses")
    zone = sorted(set(ca) | set(cb))
    zp = zone_plus(zone, set(sig))
    zsig = {c: sig[c] for c in zp}
    E_all = float(ex.mean())
    out = {"fit": crops.get("fit"), "pairs": int(len(ex)), "zone_cells": len(zone), "zone_plus_cells": len(zp),
           "E_all": E_all, "rules": {}}
    kept_all = {tuple(c) for c in crops["kept"]}
    for rule, kept in (("main", keep_top(scores(zsig)["smooth"], zone, SHARE)), ("crops", kept_all & set(zone))):
        inside, n, E = outcome(ex, ca, cb, kept)
        rnd = random_crops(ex, ca, cb, zone, len(kept), dw, draws=draws, seed=seed)
        std = dw_standardized(ex, inside, dw, np.array(rnd["dw_mix"]) if rnd["dw_mix"] else None)
        out["rules"][rule] = {
            "kept_cells": len(kept), "kept_pairs": n, "kept_pair_share": n / len(ex), "E_rule": E,
            "E_rand": rnd["mean"], "rand_p975": rnd["p975"], "rand_p025": rnd["p025"],
            "G_rand": (E - rnd["mean"]) if E is not None and rnd["mean"] is not None else None,
            "G_all": (E - E_all) if E is not None else None,
            "above_p975": bool(E is not None and rnd["p975"] is not None and E > rnd["p975"]),
            "G_rand_dw_std": (std - rnd["mean"]) if std is not None and rnd["mean"] is not None else None}
    m = out["rules"]["main"]
    es = []
    for s in range(shuffles):
        kept = keep_top(scores(shuffled_signals(zsig, seed * 1000 + s))["smooth"], zone, SHARE)
        es.append(outcome(ex, ca, cb, kept)[2])
    sh = float(np.mean(es)) if es and all(e is not None for e in es) else None
    out["shuffled"] = {"shuffles": shuffles, "E_shuffled": sh,
                       "shuffled_minus_rand": (sh - m["E_rand"]) if sh is not None and m["E_rand"] is not None
                       else None}
    return out


def readout(recs: dict) -> dict:
    """The tests' verdict for rule main over several fits ({fit: score record})."""
    out = {"rule": "main", "fits": {}, "void_fits": [], "verdict": None, "why": []}
    for name, r in sorted(recs.items()):
        m = r["rules"]["main"]
        void = m["kept_pairs"] < MIN_PAIRS or m["kept_pair_share"] < MIN_KEPT_SHARE or m["G_rand"] is None
        out["fits"][name] = {k: m[k] for k in ("E_rule", "E_rand", "rand_p975", "G_rand", "G_all", "above_p975",
                                                "G_rand_dw_std", "kept_pairs")}
        out["fits"][name]["shuffled_minus_rand"] = r["shuffled"]["shuffled_minus_rand"]
        out["fits"][name]["void"] = void
        if void:
            out["void_fits"].append(name)
    ok = [n for n in out["fits"] if not out["fits"][n]["void"]]
    if not ok:
        out["verdict"] = "VOID"
        out["why"].append("no fit has enough kept pairs")
        return out
    sm = [out["fits"][n]["shuffled_minus_rand"] for n in ok]
    if any(v is None for v in sm):
        out["verdict"] = "VOID"
        out["why"].append("shuffled control missing on a scored fit")
        return out
    ctrl = float(np.mean(sm))
    g = float(np.mean([out["fits"][n]["G_rand"] for n in ok]))
    gs = [out["fits"][n]["G_rand_dw_std"] for n in ok]
    gstd = float(np.mean(gs)) if all(v is not None for v in gs) else None
    above = sum(1 for n in ok if out["fits"][n]["above_p975"])
    under = sum(1 for n in ok if out["fits"][n]["E_rule"] < out["fits"][n]["E_rand"])
    need = math.ceil(BAR_ABOVE * len(ok))
    out.update(mean_shuffled_minus_rand=ctrl, mean_G_rand=g, mean_G_rand_dw_std=gstd, fits_above_p975=above,
               fits_needed_above=need, fits_scored=len(ok), fits_under_rand_mean=under,
               mean_G_all=float(np.mean([out["fits"][n]["G_all"] for n in ok])))
    if ctrl >= CONTROL_MAX:
        out["verdict"] = "VOID"
        out["why"].append(f"the shuffled control beat random crops by {ctrl:.4f} (bar under {CONTROL_MAX})")
    elif g >= BAR_G and above >= need and gstd is not None and gstd > 0:
        out["verdict"] = "BEATS_CONTROL"
    elif g < NO_GAIN_G or under >= NO_GAIN_FITS:
        out["verdict"] = "NO_GAIN"
    else:
        out["verdict"] = "WEAK"
    return out


# ---------------------------------------------------------------- commands

def find_umbilicus(fit, given):
    if given:
        return Path(given)
    d = Path(fit)
    for p in (d / "dataset" / "umbilicus.json", d.parent / "dataset" / "umbilicus.json", d / "umbilicus.json"):
        if p.is_file():
            return p
    raise CropError(f"no dataset/umbilicus.json beside {fit}: pass --umbilicus")


def run_crops(fit, sibling, lasagna, windings, out_dir, umbilicus=None, seed=0, name=None, sname=None, log=print):
    """Rule main over every cell of windings W0 to W1 (no truth), its components as point collections, and the
    shifted control. Returns the record it writes."""
    import time
    from spiralfiteval import fit as sf
    t0 = time.time()
    w0, w1 = windings
    if w1 < w0:
        raise CropError(f"--windings {w0} {w1}: the first winding must not be above the second")
    name = name or Path(fit).name
    sname = sname or Path(sibling).name
    grids = export_grids(fit)
    if not any(w0 <= w <= w1 for w in grids):
        raise CropError(f"the fit has no winding in {w0} to {w1} (it has {min(grids)} to {max(grids)})")
    sense = sf.check_seams(grids)["sense"]
    sgr = export_grids(sibling)
    sib = CellFit({w: g for w, g in sgr.items() if w0 - 3 <= w <= w1 + 3}, sname, None)
    axis = Axis.from_json(find_umbilicus(fit, umbilicus))
    cells = band_cells(grids, w0, w1)
    log(f"fits read in {time.time() - t0:.0f} s, {len(cells)} cells")
    sig, sinfo = compute_signals(grids, sense, sib, Lasagna(lasagna), cells, axis)
    sc = scores(sig)
    kept = keep_top(sc["smooth"], cells, SHARE)
    comps = components(kept)
    ctrl = shifted(comps, grids, seed=seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rec = {"tool": "autocrop", "version": VERSION, "fit": name, "sibling": sname, "windings": [w0, w1],
           "cells": len(cells), "kept_cells": len(kept), "components": len(comps),
           "cells_in_components": sum(len(c) for c in comps), "signal_info": sinfo, "seed": seed, "files": {},
           "seconds": None}
    for tag, cs in (("crop", comps), ("shift", ctrl)):
        doc, n_pts = crop_collections(cs, grids, tag)
        f = out / f"relative_windings_{tag}_{name}.json"
        f.write_text(json.dumps(doc) + "\n")
        rec["files"][tag] = {"file": f.name, "sha256": sha256(f), "collections": len(doc["collections"]),
                             "points": n_pts}
    clean = {cell_key(c): {k: (None if v is None or not np.isfinite(v) else v) for k, v in s.items()}
             for c, s in sig.items()}
    (out / f"crops-{name}.json").write_text(json.dumps({
        "fit": name, "windings": [w0, w1], "signals": clean,
        "smooth": {cell_key(c): v for c, v in sc["smooth"].items()},
        "kept": [list(c) for c in sorted(kept)], "components": [[list(c) for c in comp] for comp in comps],
        "shifted": [[list(c) for c in comp] for comp in ctrl]}) + "\n")
    rec["seconds"] = round(time.time() - t0, 1)
    (out / f"crops-record-{name}.json").write_text(json.dumps(rec, indent=1) + "\n")
    return rec


def cmd_crops(a):
    rec = run_crops(a.fit, a.sibling, a.lasagna, a.windings, a.out_dir, a.umbilicus, a.seed, a.name,
                    a.sibling_name, log=lambda s: print(s, file=sys.stderr, flush=True))
    print(json.dumps(rec))
    return 0


def cmd_score(a):
    crops = json.loads(Path(a.crops).read_text())
    pairs = json.loads(Path(a.pairs).read_text())
    rec = score_fit(crops, pairs, draws=a.draws, shuffles=a.shuffles, seed=a.seed)
    Path(a.out).write_text(json.dumps(rec, indent=1) + "\n")
    m = rec["rules"]["main"]
    print(json.dumps({"fit": rec["fit"], "pairs": rec["pairs"], "kept_pairs": m["kept_pairs"], "E_rule": m["E_rule"],
                      "E_rand": m["E_rand"], "G_rand": m["G_rand"], "above_p975": m["above_p975"],
                      "shuffled_minus_rand": rec["shuffled"]["shuffled_minus_rand"]}))
    return 0


def cmd_readout(a):
    recs = {}
    for p in a.files:
        r = json.loads(Path(p).read_text())
        name = r.get("fit") or Path(p).stem
        if name in recs:
            raise CropError(f"two score files for fit {name}")
        recs[name] = r
    out = readout(recs)
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: out.get(k) for k in ("verdict", "mean_G_rand", "fits_above_p975", "fits_scored",
                                              "mean_shuffled_minus_rand", "why")}))
    return {"BEATS_CONTROL": 0, "WEAK": 0, "NO_GAIN": 0}.get(out["verdict"], 3)


# ---------------------------------------------------------------- synthetic demo

DEMO_CENTER = (300.0, 300.0)
DEMO_PITCH = 20.0
DEMO_W = (10, 15)
DEMO_COLS = 64
DEMO_ROWS = 24
DEMO_BAD = (12, (4, 16), (16, 48))      # winding, rows, columns of the planted patch on the fit


def demo_grid(rng, noise, bad=False):
    """A spiral fit export (one tifxyz surface, windings side by side) about DEMO_CENTER: r = 40 + pitch (w - 10 + t).
    With bad, the DEMO_BAD patch sits one winding out, as a fit that jumped to the next sheet does."""
    ws = list(range(DEMO_W[0], DEMO_W[1] + 1))
    X = np.zeros((DEMO_ROWS, DEMO_COLS * len(ws)), np.float32)
    Y, Z = X.copy(), X.copy()
    t = np.arange(DEMO_COLS) / DEMO_COLS
    for k, w in enumerate(ws):
        for i in range(DEMO_ROWS):
            r = 40.0 + DEMO_PITCH * (w - DEMO_W[0] + t) + rng.normal(0, noise, DEMO_COLS)
            if bad and w == DEMO_BAD[0] and DEMO_BAD[1][0] <= i < DEMO_BAD[1][1]:
                c0, c1 = DEMO_BAD[2]
                r[c0:c1] += DEMO_PITCH
            th = 2 * np.pi * t
            sl = slice(k * DEMO_COLS, (k + 1) * DEMO_COLS)
            X[i, sl] = DEMO_CENTER[0] + r * np.cos(th)
            Y[i, sl] = DEMO_CENTER[1] + r * np.sin(th)
            Z[i, sl] = 20.0 + 8.0 * i
    return ws, X, Y, Z


def write_demo_fit(root, rng, noise, bad):
    import tifffile
    ws, X, Y, Z = demo_grid(rng, noise, bad)
    d = Path(root) / "spiral-checkpoint.tifxyz"
    d.mkdir(parents=True, exist_ok=True)
    for c, a in zip("xyz", (X, Y, Z)):
        tifffile.imwrite(d / f"{c}.tif", a)
    (d / "meta.json").write_text(json.dumps({"first_winding": ws[0], "scale": 0.05, "winding_column_ranges":
                                             [[k * DEMO_COLS, (k + 1) * DEMO_COLS] for k in range(len(ws))]}) + "\n")
    (Path(root) / "dataset").mkdir(exist_ok=True)
    (Path(root) / "dataset" / "umbilicus.json").write_text(json.dumps(
        [[DEMO_CENTER[0], DEMO_CENTER[1], 0.0], [DEMO_CENTER[0], DEMO_CENTER[1], 400.0]]) + "\n")


def write_demo_lasagna(root):
    """nx, ny (uint8, 128 + 127 cos) pointing away from the axis, and grad_mag so one sheet spacing is one unit."""
    import zarr
    n = int(600 / LAS_SCALE)
    nz = int(240 / LAS_SCALE)
    yy, xx = np.meshgrid(np.arange(n) * LAS_SCALE - DEMO_CENTER[1], np.arange(n) * LAS_SCALE - DEMO_CENTER[0],
                         indexing="ij")
    rr = np.hypot(xx, yy) + 1e-9
    nx = np.broadcast_to(np.rint(128 + 127 * xx / rr).astype(np.uint8), (nz, n, n))
    ny = np.broadcast_to(np.rint(128 + 127 * yy / rr).astype(np.uint8), (nz, n, n))
    gm = np.full((nz, n, n), 1.0 / (DEMO_PITCH * DENSITY), np.float32)
    for name, arr in (("nx", nx), ("ny", ny), ("grad_mag", gm)):
        z = zarr.open(str(Path(root) / f"demo_{name}.zarr"), mode="w", shape=arr.shape, chunks=(16, 64, 64),
                      dtype=arr.dtype)
        z[:] = arr


def cmd_demo(a):
    out = Path(a.out_dir)
    if out.exists() and any(out.iterdir()):
        raise CropError(f"{out} exists and is not empty")
    rng = np.random.default_rng(a.seed)
    write_demo_fit(out / "fitA", rng, 0.3, bad=True)
    write_demo_fit(out / "fitB", rng, 0.3, bad=False)
    write_demo_lasagna(out / "lasagna")
    rec = run_crops(out / "fitA", out / "fitB", out / "lasagna", (DEMO_W[0] + 1, DEMO_W[1] - 1), out / "crops",
                    seed=a.seed, log=lambda s: print(s, file=sys.stderr, flush=True))
    crops = json.loads((out / "crops" / "crops-fitA.json").read_text())
    kept = {tuple(c) for c in crops["kept"]}
    w, (r0, r1), (c0, c1) = DEMO_BAD
    allc = [parse_key(k) for k in crops["smooth"]]
    planted = [c for c in allc if c[0] == w and r0 // CELL[0] <= c[1] < -(-r1 // CELL[0])
               and c0 // CELL[1] <= c[2] < -(-c1 // CELL[1])]
    rest = [c for c in allc if c not in set(planted)]
    kp = sum(c in kept for c in planted) / len(planted)
    kr = sum(c in kept for c in rest) / len(rest)
    ok = kp <= 0.5 * kr
    res = {"check": "PASS" if ok else "FAIL", "planted_cells": len(planted), "planted_kept_share": round(kp, 3),
           "other_cells": len(rest), "other_kept_share": round(kr, 3), "components": rec["components"],
           "crop_points": rec["files"]["crop"]["points"], "shift_points": rec["files"]["shift"]["points"],
           "bar": "planted kept share at most half the other cells' kept share"}
    (out / "demo-result.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res))
    return 0 if ok else 1


def main(argv=None):
    if argv is None and sys.stdout.isatty():          # the Scrolls look (AGENTS.md, terminal look rule)
        sys.path.insert(0, str(ROOT))
        from kit import termstyle
        termstyle.script()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"autocrop {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("crops", help="rule main over a band of windings, no truth: point collections and a control")
    p.add_argument("--fit", required=True, help="the fit's run folder or its spiral-checkpoint.tifxyz folder")
    p.add_argument("--sibling", required=True, help="a second fit of the same window (another seed), same form")
    p.add_argument("--lasagna", required=True, help="folder holding the nx, ny and grad_mag zarrs the fit read")
    p.add_argument("--windings", type=int, nargs=2, required=True, metavar=("W0", "W1"))
    p.add_argument("--out-dir", required=True)
    p.add_argument("--umbilicus", help="villa umbilicus JSON in fit coordinates (default: the fit's "
                   "dataset/umbilicus.json)")
    p.add_argument("--seed", type=int, default=0, help="numpy seed of the shifted control")
    p.add_argument("--name", help="the fit's name in file names (default: the folder name)")
    p.add_argument("--sibling-name", help="the sibling's name in the record (default: the folder name)")
    p = sub.add_parser("score", help="rule main against a winding-truth pair table, with its controls")
    p.add_argument("--crops", required=True, help="crops-NAME.json written by crops")
    p.add_argument("--pairs", required=True, help="pair table JSON: cell_a, cell_b, exact, dw")
    p.add_argument("--out", required=True)
    p.add_argument("--draws", type=int, default=DRAWS)
    p.add_argument("--shuffles", type=int, default=SHUFFLES)
    p.add_argument("--seed", type=int, default=0)
    p = sub.add_parser("readout", help="the tests' verdict over the score files of several fits")
    p.add_argument("files", nargs="+", metavar="SCORE")
    p.add_argument("--out", required=True)
    p = sub.add_parser("demo", help="synthetic fit pair with a planted wrong-winding patch; checks the rule drops it")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    try:
        return {"crops": cmd_crops, "score": cmd_score, "readout": cmd_readout, "demo": cmd_demo}[a.cmd](a)
    except CropError as exc:
        print(f"autocrop: {exc}", file=sys.stderr)
        return 2
    except ImportError as exc:
        print(f"autocrop: {exc}; install numpy, scipy, tifffile, zarr and spiralfiteval", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
