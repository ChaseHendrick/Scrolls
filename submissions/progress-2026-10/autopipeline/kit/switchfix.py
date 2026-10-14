"""Detect sheet switches in a traced tifxyz and cut the trace back to its seed's winding: `kit switchfix`.

  kit switchfix detect SURF --prediction P [--seed X Y Z] [--json] [--out FILE]
        classify every vertex from the surface prediction along its normal (on a sheet and clear, off every sheet,
        or in a contact zone where another sheet lies within 8 voxels), find jump edges, and flag every vertex that
        the seed's winding cannot reach without crossing one of them
  kit switchfix repair SURF OUT --prediction P [--seed X Y Z] [--record FILE]
        the same, then write OUT: a new tifxyz with the flagged vertices removed and a JSON record; SURF is never
        modified
  kit switchfix params  print the frozen parameters and their digest

What it is. A repair that needs no reference winding and no person: it removes the parts of a trace that could be
on another winding and keeps the part its seed's winding reaches. It does not move any vertex back onto the right
sheet; what it cuts is lost, not mended. That is the best this repository can do without references today
(docs/switchfix.md, "Survey"): every open method that relabels or regrows switched parts needs references, a fitted
spiral, several traces or a person's corrections.

Why it can work (Interpretation). The tracer keeps a grid trace on the predicted sheet (docs/logs/
2026-10-09-trace-normal-grids.md: 98 % of a grid trace's vertices at offset 0 of the m7 prediction). A trace that
leaves one sheet for another must, at every place it crosses over, either leave the predicted sheets (an off-sheet
vertex), pass where the two sheets lie within a few voxels of each other (a contact zone), or jump from one to the
other across a single grid edge (a jump edge). Removing off-sheet and contact vertices and cutting jump edges
therefore separates every part on another winding from the seed, as far as the prediction resolves the sheets; the
connected part of the seed is kept. The price: a contact zone or a hole in the prediction that runs right across
the trace cuts off the far side even when the trace stayed on its sheet there.

Pieces and their sources:
  - Vertex normals: kit.surfbench.grid_geometry (central differences, one-sided at holes, as kit snap).
  - On the sheet: the prediction at nearest-voxel offsets -24..24 along the normal, foreground at >= 128, the
    threshold of VC3D's tracer (kit/vc3d_prep.py) and of scripts/unwrap/onpred.py; on the sheet when a foreground
    sample lies within 4 voxels, surfbench's scoring distance d (2 voxels cut hand-traced windows of the tune
    windings into specks: 15 to 28 % of their vertices off; docs/switchfix.md, "Design runs").
  - Contact: surfbench's contact zone is another winding within 8 voxels (2 d at its scoring distance d = 4); here
    "another winding" is another foreground run of the prediction along the normal whose centre lies within 8
    voxels of the centre of the run the vertex is on, or the vertex's own run is thicker than 1.6 times the
    surface's median run thickness (two sheets merged in the prediction).
  - Jump edges: two grid neighbours whose offset from each other's tangent plane exceeds 7 voxels, half the median
    winding step of the PHerc0139 stack (14.1 voxels, docs/surfbench.md); and sheet-jump edges, where the sheet
    points under the two vertices (vertex + offset of its run centre along the normal) break: both second
    differences of the sheet points across the edge exceed the same 7 voxels. The open winding-coordinate audit
    (kit meshqa windaudit, ScrollFiesta's wind_audit.c) was measured first and rejected for this grid: on 20-voxel
    grids of hand windings it flags 27 to 67 % of edges (docs/switchfix.md).
  - The kept part: the largest 4-connected component of clear vertices (jump edges cut) that reaches within 5 grid
    cells of the seed vertex; a component of
    removed vertices that touches only the kept part (a hole in the prediction inside the trace, a contact patch
    that leads nowhere) is given back, since no path through it reaches another winding. Known gap (found in
    review, 9 Oct 2026; frozen behaviour, not changed): the give-back ignores jump edges and does not ask whether
    the component itself lies on the seed's sheet, so a trace end that leaves every predicted sheet and stays off
    it is kept whole however far it strays (tests/test_switchfix.py, test_known_gap_an_off_sheet_end_is_kept).

Coordinates are tifxyz (x, y, z) in level-0 voxels of the volume the trace was made on; the prediction must be in
the same frame. Needs numpy and scipy. A flag is a place where the prediction cannot vouch for the trace; it is not
evidence about ink and never a reading.
"""

import concurrent.futures
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PARAMS = {
    "version": 1,
    "prediction": {"threshold": 128, "half_vox": 24, "on_tol_vox": 4},
    "contact": {"centre_vox": 8.0, "merge_factor": 1.6},
    "jump": {"normal_offset_vox": 7.0},
    "keep": {"connectivity": 4, "give_back_dead_ends": True, "seed_radius": 5},
}

CLEAR, OFF, CONTACT, NO_NORMAL, INVALID = 0, 1, 2, 3, -1
CLASS_NAMES = {CLEAR: "clear", OFF: "off_sheet", CONTACT: "contact", NO_NORMAL: "no_normal"}
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"


class SwitchFixError(ValueError):
    """A problem the caller can fix: an unreadable surface, no seed, an empty result."""


def _np():
    try:
        import numpy
    except ImportError as exc:
        raise SwitchFixError("kit switchfix needs numpy and scipy") from exc
    return numpy


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def params_digest(params=None):
    return hashlib.sha256(canonical(PARAMS if params is None else params).encode()).hexdigest()


def _r(x, n=4):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else round(x, n)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- the prediction

class ArraySampler:
    """A prediction held in memory as a (z, y, x) array; outside it reads 0."""

    def __init__(self, arr):
        self.arr = _np().asarray(arr)

    def values(self, zyx):
        np = _np()
        zyx = np.asarray(zyx, dtype=np.int64).reshape(-1, 3)
        out = np.zeros(len(zyx), self.arr.dtype)
        ins = np.all((zyx >= 0) & (zyx < np.array(self.arr.shape)), axis=1)
        q = zyx[ins]
        out[ins] = self.arr[q[:, 0], q[:, 1], q[:, 2]]
        return out


class ChunkSampler:
    """Nearest-voxel values of a chunked level-0 volume. `read(idx)` returns a chunk (or None for a chunk that is
    not stored, which reads 0); chunks are read once per call, in parallel."""

    def __init__(self, read, chunks, shape, workers=4, label=""):
        self.read, self.chunks, self.shape = read, tuple(int(c) for c in chunks), tuple(int(s) for s in shape)
        self.workers = max(1, int(workers))
        self.label = label
        self.chunks_read = 0

    def values(self, zyx):
        np = _np()
        zyx = np.asarray(zyx, dtype=np.int64).reshape(-1, 3)
        # float32 holds uint8 and uint16 values exactly; a uint8 buffer wrapped a uint16 prediction's values modulo
        # 256 (review fix, 9 Oct 2026; the m7 predictions measured are uint8, so no measured number changes)
        out = np.zeros(len(zyx), np.float32)
        ins = np.all((zyx >= 0) & (zyx < np.array(self.shape)), axis=1)
        idx = np.flatnonzero(ins)
        if not idx.size:
            return out
        ch = np.array(self.chunks)
        cid = zyx[idx] // ch
        key = (cid[:, 0] * 1_000_003 + cid[:, 1]) * 1_000_003 + cid[:, 2]
        order = np.argsort(key, kind="stable")
        key_s = key[order]
        starts = np.flatnonzero(np.r_[True, key_s[1:] != key_s[:-1]])
        ends = np.r_[starts[1:], len(order)]

        def one(k):
            sel = idx[order[starts[k]:ends[k]]]
            c = tuple(int(v) for v in zyx[sel[0]] // ch)
            arr = self.read(c)
            if arr is None:
                return sel, None
            loc = zyx[sel] - np.array(c) * ch
            loc = np.minimum(loc, np.array(arr.shape) - 1)
            return sel, arr[loc[:, 0], loc[:, 1], loc[:, 2]]

        with concurrent.futures.ThreadPoolExecutor(self.workers) as ex:
            for sel, vals in ex.map(one, range(len(starts))):
                self.chunks_read += 1
                if vals is not None:
                    out[sel] = vals
        return out


def open_prediction(location, cache_dir=None, workers=4):
    """A sampler for a published prediction: a bucket prefix or URL under the open-data bucket (level 0 chunks,
    cached on disk by kit.surfbench.ChunkReader), or any other local or remote OME-Zarr (kit.vc3d_region.Volume)."""
    from . import surfbench
    loc = str(location).rstrip("/")
    if Path(loc).exists() or (loc.startswith("http") and not loc.startswith(BUCKET + "/")):
        from . import vc3d_region
        vol = vc3d_region.Volume(loc, workers=workers)
        meta = vol.levels[0]["meta"]
        return ChunkSampler(lambda c: vol._chunk(0, c), meta["chunks"], meta["shape"], workers, loc)
    prefix = loc[len(BUCKET) + 1:] if loc.startswith(BUCKET + "/") else loc
    cr = surfbench.ChunkReader(prefix, cache_dir or surfbench.DEFAULT_CACHE)
    return ChunkSampler(_retrying(cr.read), cr.chunks, cr.meta["shape"], workers, prefix)


def _retrying(read, tries=4, wait=2.0):
    """A chunk read retried on transfer errors (a cut-off download raises http.client.IncompleteRead); a partial
    file left in the cache by a failed attempt is removed by the reader's own atomic download or read again."""
    def go(idx):
        for k in range(tries):
            try:
                return read(idx)
            except Exception:  # noqa: BLE001 - any transfer error; the last one is raised
                if k == tries - 1:
                    raise
                time.sleep(wait * (k + 1))
    return go


# ---------------------------------------------------------------- per-vertex classes

def profiles(points, normals, sampler, half=None, threshold=None):
    """Foreground (value >= threshold) of the prediction at integer offsets -half..half along each normal, nearest
    voxel: a (N, 2 half + 1) boolean array."""
    np = _np()
    P = PARAMS["prediction"]
    half = int(P["half_vox"] if half is None else half)
    threshold = P["threshold"] if threshold is None else threshold
    offs = np.arange(-half, half + 1, dtype=np.float64)
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    nrm = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    if not len(pts):
        return np.zeros((0, len(offs)), bool)
    samp = pts[:, None, :] + offs[None, :, None] * nrm[:, None, :]
    zyx = np.rint(samp[..., ::-1]).astype(np.int64).reshape(-1, 3)
    return (sampler.values(zyx) >= threshold).reshape(len(pts), len(offs))


def runs_of(row):
    """(start, end) index pairs of the True runs of a 1-D boolean array, end inclusive."""
    np = _np()
    d = np.diff(np.r_[0, row.astype(np.int8), 0])
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1))


def classify_profiles(fg, params=None):
    """Per profile: on the sheet, own run thickness and centre (offset units), and the distance from that centre to
    the nearest other run's centre on the negative and positive sides (inf when none). Returns a dict of arrays."""
    np = _np()
    p = (params or PARAMS)["prediction"]
    n, L = fg.shape
    half = (L - 1) // 2
    tol = int(p["on_tol_vox"])
    on = np.zeros(n, bool)
    thick = np.full(n, np.nan)
    centre = np.full(n, np.nan)
    dneg = np.full(n, np.inf)
    dpos = np.full(n, np.inf)
    near = fg[:, half - tol:half + tol + 1]
    has = near.any(axis=1)
    order = np.argsort(np.abs(np.arange(-tol, tol + 1)), kind="stable")
    for i in np.flatnonzero(has):
        k0 = half - tol + int(order[np.flatnonzero(near[i][order])[0]])
        rr = runs_of(fg[i])
        own = next(j for j, (a, b) in enumerate(rr) if a <= k0 <= b)
        a, b = rr[own]
        on[i] = True
        thick[i] = b - a + 1
        c = 0.5 * (a + b)
        centre[i] = c - half
        if own > 0:
            a2, b2 = rr[own - 1]
            dneg[i] = c - 0.5 * (a2 + b2)
        if own + 1 < len(rr):
            a2, b2 = rr[own + 1]
            dpos[i] = 0.5 * (a2 + b2) - c
    return {"on": on, "thickness": thick, "centre": centre, "d_neg": dneg, "d_pos": dpos}


def vertex_classes(prof, ok, params=None):
    """(H, W) class per vertex from classify_profiles output for the vertices `ok` (ravelled order): CLEAR, OFF,
    CONTACT; NO_NORMAL where valid without a normal is set by the caller. Also the median run thickness and the
    median distance to the nearest other run (a local winding step from the prediction alone)."""
    np = _np()
    c = (params or PARAMS)["contact"]
    on, t = prof["on"], prof["thickness"]
    t_med = float(np.median(t[on])) if on.any() else float("nan")
    merged = on & (t > c["merge_factor"] * t_med) if math.isfinite(t_med) else np.zeros_like(on)
    dmin = np.minimum(prof["d_neg"], prof["d_pos"])
    close = on & (dmin <= c["centre_vox"])
    cls = np.full(on.shape, OFF, np.int8)
    cls[on] = CLEAR
    cls[on & (merged | close)] = CONTACT
    both = np.concatenate([prof["d_neg"][on], prof["d_pos"][on]])
    both = both[np.isfinite(both)]
    step = float(np.median(both)) if both.size else float("nan")
    flat = np.full(ok.shape, INVALID, np.int8).ravel()
    flat[np.flatnonzero(ok.ravel())] = cls
    return flat.reshape(ok.shape), {"median_thickness_vox": _r(t_med, 2), "median_neighbour_step_vox": _r(step, 2),
                                    "merged": int(merged.sum()), "close": int(close.sum())}


def sheet_offsets(prof, ok):
    """(H, W) offset along the normal from each vertex to the centre of the prediction run it is on (NaN where it
    is on none): the sheet point under the vertex is xyz + offset * normal."""
    np = _np()
    out = np.full(ok.shape, np.nan).ravel()
    out[np.flatnonzero(ok.ravel())] = np.where(prof["on"], prof["centre"], np.nan)
    return out.reshape(ok.shape)


def jump_edges(xyz, valid, normals, ok, limit=None):
    """Horizontal (H, W-1) and vertical (H-1, W) edges between two vertices with normals whose offset from each
    other's tangent plane is over `limit` voxels."""
    np = _np()
    limit = PARAMS["jump"]["normal_offset_vox"] if limit is None else limit
    nz = np.where(ok[..., None], normals, 0.0)
    out = []
    for ax in (1, 0):
        a = (slice(None), slice(None, -1)) if ax == 1 else (slice(None, -1), slice(None))
        b = (slice(None), slice(1, None)) if ax == 1 else (slice(1, None), slice(None))
        d = xyz[b] - xyz[a]
        o = np.maximum(np.abs(np.einsum("...k,...k", d, nz[a])), np.abs(np.einsum("...k,...k", d, nz[b])))
        out.append(ok[a] & ok[b] & (o > limit))
    return out[0], out[1]


def sheet_jump_edges(C, ok, limit=None):
    """Edges across which the sheet surface C (the prediction's sheet point under each vertex) breaks: for the
    edge (a, b) along a grid line ... p, a, b, q ..., the second differences centred on a (p - 2a + b) and on b
    (a - 2b + q) both exceed `limit` voxels in length; where p or q is missing, the one that exists decides. A
    step of one sheet to the next makes both about the step; a smooth sheet keeps them near L^2 / R for grid step L
    and radius of curvature R; no normal is used, so a ramp that tilts the trace's normals does not hide it."""
    np = _np()
    limit = PARAMS["jump"]["normal_offset_vox"] if limit is None else limit
    out = []
    for ax in (1, 0):
        P = np.moveaxis(np.where(ok[..., None], C, np.nan), ax, 1)      # lines along axis 1
        n = P.shape[1]
        cut = np.zeros((P.shape[0], max(n - 1, 0)), bool)
        if n >= 2:
            a, b = P[:, :-1], P[:, 1:]
            pa = np.full_like(a, np.nan)
            qb = np.full_like(b, np.nan)
            pa[:, 1:] = P[:, :-2]
            qb[:, :-1] = P[:, 2:]
            with np.errstate(invalid="ignore"):
                ea = np.linalg.norm(pa - 2 * a + b, axis=-1)
                eb = np.linalg.norm(a - 2 * b + qb, axis=-1)
            fa, fb = np.isfinite(ea), np.isfinite(eb)
            both = np.isfinite(a).all(-1) & np.isfinite(b).all(-1)
            big_a, big_b = fa & (ea > limit), fb & (eb > limit)
            cut = both & np.where(fa & fb, big_a & big_b, big_a | big_b)
        out.append(np.moveaxis(cut, 1, ax) if ax == 0 else cut)
    return out[0], out[1]


# ---------------------------------------------------------------- components

def _components(mask, cut_h=None, cut_v=None):
    """4-connected components of `mask` (H, W), edges in cut_h / cut_v removed: (labels with -1 outside, count)."""
    np = _np()
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    H, W = mask.shape
    idx = np.arange(H * W).reshape(H, W)
    eh = mask[:, :-1] & mask[:, 1:]
    ev = mask[:-1, :] & mask[1:, :]
    if cut_h is not None:
        eh &= ~cut_h
    if cut_v is not None:
        ev &= ~cut_v
    u = np.concatenate([idx[:, :-1][eh], idx[:-1, :][ev]])
    v = np.concatenate([idx[:, 1:][eh], idx[1:, :][ev]])
    g = coo_matrix((np.ones(len(u), np.int8), (u, v)), shape=(H * W, H * W))
    n, lab = connected_components(g, directed=False)
    lab = lab.reshape(H, W).astype(np.int64)
    m = mask.ravel()
    _, inv = np.unique(lab.ravel()[m], return_inverse=True)
    out = np.full(H * W, -1, np.int64)
    out[m] = inv
    return out.reshape(H, W), int(inv.max() + 1) if m.any() else 0


def seed_vertex(xyz, valid, seed=None, among=None):
    """(row, col) of the vertex nearest the seed point (x, y, z), among `among` when given; the valid vertex nearest
    the grid centre when no seed is given."""
    np = _np()
    cand = valid if among is None else (valid & among)
    if not cand.any():
        raise SwitchFixError("no vertex to start from")
    rr, cc = np.nonzero(cand)
    if seed is None:
        H, W = valid.shape
        k = int(np.argmin((rr - (H - 1) / 2) ** 2 + (cc - (W - 1) / 2) ** 2))
    else:
        k = int(np.argmin(((xyz[rr, cc] - np.asarray(seed, dtype=np.float64)) ** 2).sum(-1)))
    return int(rr[k]), int(cc[k])


def keep_mask(cls, cut_h, cut_v, seed_rc, params=None):
    """The vertices kept: the seed's 4-connected clear component (jump edges cut), plus every component of the
    other valid vertices that touches no other clear component. Returns (keep, info)."""
    np = _np()
    k = (params or PARAMS)["keep"]
    valid = cls != INVALID
    clear = cls == CLEAR
    lab, n = _components(clear, cut_h, cut_v)
    r, c = seed_rc
    rad = int(k.get("seed_radius", 0))
    near = lab[max(0, r - rad):r + rad + 1, max(0, c - rad):c + rad + 1]
    near = near[near >= 0]
    if not near.size:
        raise SwitchFixError("no clear vertex near the seed vertex")
    # the largest clear component within seed_radius cells of the seed vertex, so a seed that sits on a speck
    # cut off by a barrier does not decide for the whole trace
    sizes = np.bincount(lab[lab >= 0], minlength=n)
    seed_lab = int(max(np.unique(near), key=lambda x: (sizes[x], -x)))
    keep = lab == seed_lab
    info = {"clear_components": n, "seed_component_vertices": int(keep.sum()), "given_back_components": 0,
            "given_back_vertices": 0, "cut_components": 0, "cut_component_vertices": 0}
    if k["give_back_dead_ends"]:
        other = valid & ~clear
        blab, bn = _components(other)
        if bn:
            # which clear components each barrier component touches (4-neighbours, jump edges ignored)
            touch_other = np.zeros(bn, bool)
            touch_seed = np.zeros(bn, bool)
            H, W = cls.shape
            for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                a = blab[max(0, -dr):H - max(0, dr), max(0, -dc):W - max(0, dc)]
                b = lab[max(0, dr):H + min(0, dr), max(0, dc):W + min(0, dc)]
                m = (a >= 0) & (b >= 0)
                touch_other[a[m][b[m] != seed_lab]] = True
                touch_seed[a[m][b[m] == seed_lab]] = True
            back = touch_seed & ~touch_other
            gb = np.isin(blab, np.flatnonzero(back)) & (blab >= 0)
            keep |= gb
            info["given_back_components"] = int(back.sum())
            info["given_back_vertices"] = int(gb.sum())
            cutc = touch_seed & touch_other
            info["cut_components"] = int(cutc.sum())
            info["cut_component_vertices"] = int((np.isin(blab, np.flatnonzero(cutc)) & (blab >= 0)).sum())
    return keep, info


# ---------------------------------------------------------------- detect and repair

def detect(xyz, valid, sampler, seed=None, params=None):
    """Classify a trace and flag what the seed's winding cannot reach. Returns (summary, arrays) where arrays holds
    cls (H, W), keep (H, W), flagged (H, W) and the jump edges. With sampler None the prediction is not read and
    only the jump test separates parts (every vertex with a normal counts as clear)."""
    np = _np()
    from . import surfbench
    params = params or PARAMS
    t0 = time.time()
    normals, _, ok, step = surfbench.grid_geometry(xyz, valid)
    if sampler is None:
        # the jump test alone: every vertex with a normal counts as clear (for the planted-seam check)
        cls = np.where(ok, CLEAR, INVALID).astype(np.int8)
        stats = {"median_thickness_vox": None, "median_neighbour_step_vox": None, "merged": 0, "close": 0,
                 "jump_test_only": True}
    else:
        fg = profiles(xyz[ok], normals[ok], sampler, params["prediction"]["half_vox"],
                      params["prediction"]["threshold"])
        prof = classify_profiles(fg, params)
        cls, stats = vertex_classes(prof, ok, params)
    cls[valid & ~ok] = NO_NORMAL
    lim = params["jump"]["normal_offset_vox"]
    cut_h, cut_v = jump_edges(xyz, valid, normals, ok, lim)
    sheet_jumps = 0
    if sampler is not None:
        # the sheet points under the vertices: a trace that slides smoothly from one sheet to another moves its
        # vertices a little per edge, but the sheet under them changes at once
        off = sheet_offsets(prof, ok)
        on_ok = ok & np.isfinite(off)
        C = xyz + np.where(on_ok, off, 0.0)[..., None] * np.where(ok[..., None], normals, 0.0)
        sh, sv = sheet_jump_edges(C, on_ok, lim)
        sheet_jumps = int((sh & ~cut_h).sum() + (sv & ~cut_v).sum())
        cut_h, cut_v = cut_h | sh, cut_v | sv
    seed_rc = seed_vertex(xyz, valid, seed)
    if cls[seed_rc] != CLEAR:
        seed_rc = seed_vertex(xyz, valid, xyz[seed_rc], among=cls == CLEAR)
    keep, info = keep_mask(cls, cut_h, cut_v, seed_rc, params)
    flagged = valid & ~keep
    nv = int(valid.sum())
    summary = {
        "vertices": nv, "grid": list(valid.shape), "grid_step_vox": _r(step, 2),
        "classes": {CLASS_NAMES[k]: int((cls == k).sum()) for k in CLASS_NAMES},
        "class_shares": {CLASS_NAMES[k]: _r((cls == k).sum() / nv) for k in CLASS_NAMES} if nv else {},
        **stats,
        "jump_edges": int(cut_h.sum() + cut_v.sum()), "sheet_jump_edges": sheet_jumps,
        "seed_vertex": list(seed_rc), "seed_point": [float(v) for v in xyz[seed_rc]],
        **info,
        "flagged": int(flagged.sum()), "flagged_share": _r(flagged.sum() / nv) if nv else None,
        "kept": int(keep.sum()), "params_digest": params_digest(params), "seconds": round(time.time() - t0, 1),
    }
    return summary, {"cls": cls, "keep": keep, "flagged": flagged, "cut_h": cut_h, "cut_v": cut_v}


def read_surface(path):
    from . import surfbench
    try:
        return surfbench.read_tifxyz(path)
    except surfbench.BenchError as exc:
        raise SwitchFixError(str(exc)) from exc


def seed_of(meta, seed=None):
    """The seed point: given, else meta.json's "seed" (vc_grow_seg_from_seed writes it), else None."""
    if seed is not None:
        return [float(v) for v in seed]
    s = (meta or {}).get("seed")
    if isinstance(s, (list, tuple)) and len(s) == 3 and all(isinstance(v, (int, float)) for v in s):
        return [float(v) for v in s]
    return None


def surface_area_vx2(xyz):
    """VC3D's computeSurfaceAreaVox2 (villa e0bbb8b, core/include/vc/core/util/SurfaceArea.hpp) of an (H, W, 3)
    grid, as kit/surfcut.py computes it: each quad split into triangles (p00, p10, p11) and (p00, p11, p01), a
    triangle counting 0 when a corner is non-finite or the (-1, -1, -1) sentinel."""
    np = _np()
    p = np.asarray(xyz, dtype=np.float64)
    if p.ndim != 3 or p.shape[0] < 2 or p.shape[1] < 2:
        return 0.0
    ok = np.isfinite(p).all(axis=-1) & ~(p == -1.0).all(axis=-1)
    p00, p10, p01, p11 = p[:-1, :-1], p[:-1, 1:], p[1:, :-1], p[1:, 1:]
    o00, o10, o01, o11 = ok[:-1, :-1], ok[:-1, 1:], ok[1:, :-1], ok[1:, 1:]

    def tri(a, b, c, keep):
        with np.errstate(invalid="ignore", over="ignore"):
            area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=-1)
        return np.where(keep, area, 0.0)

    return float((tri(p00, p10, p11, o00 & o10 & o11) + tri(p00, p11, p01, o00 & o11 & o01)).sum())


def write_kept(src, out, xyz, keep, meta, record, overwrite=False):
    """Write a copy of the grid with every vertex outside `keep` set to (-1, -1, -1), the same grid shape, meta.json
    from the source with bbox and area recomputed and a "switchfix" record; staged and renamed into place."""
    np = _np()
    from . import meshqa
    src, out = Path(src), Path(os.path.abspath(out))
    rs, ro = src.resolve(), out.resolve()
    if ro == rs or rs in ro.parents or ro in rs.parents:
        raise SwitchFixError(f"{out} must be neither {src}, inside it, nor around it")
    if out.exists() and not overwrite:
        raise SwitchFixError(f"{out} exists; pass --overwrite to replace it")
    if out.exists() and not (out.is_dir() and (meshqa.is_tifxyz_dir(out) or not any(out.iterdir()))):
        raise SwitchFixError(f"{out}: --overwrite replaces only an empty folder or a tifxyz folder")
    if not keep.any():
        raise SwitchFixError("nothing kept")
    sub = np.where(keep[..., None], xyz, -1.0).astype(np.float32)
    area = surface_area_vx2(sub)
    new = {k: v for k, v in (meta or {}).items() if k not in ("bbox", "area_vx2", "area_cm2", "uuid", "switchfix")}
    new.update({"format": new.get("format", "tifxyz"), "type": new.get("type", "seg"),
                "scale": new.get("scale", [0.05, 0.05]), "uuid": out.name,
                "bbox": [[float(v) for v in xyz[keep].min(axis=0)], [float(v) for v in xyz[keep].max(axis=0)]],
                "area_vx2": area})
    vox = (meta or {}).get("vc_gsfs_params", {}).get("voxelsize") if isinstance(meta, dict) else None
    if isinstance(vox, (int, float)) and vox > 0:
        new["area_cm2"] = area * float(vox) ** 2 / 1e8
    new["switchfix"] = record
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{out.name}.", suffix=".switchfix-partial", dir=out.parent))
    stage, old = work / "copy", work / "old"
    try:
        stage.mkdir()
        for i, name in enumerate("xyz"):
            meshqa._write_grid(stage / f"{name}.tif", sub[..., i])
        (stage / "meta.json").write_text(json.dumps(new, indent=4) + "\n", encoding="utf-8")
        if out.exists():
            os.replace(out, old)
        os.replace(stage, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out


def repair(src, out, sampler, seed=None, record_path=None, params=None, overwrite=False, prediction_label=None):
    """Detect, then write OUT with the flagged vertices removed and a JSON record (also at record_path)."""
    src = Path(src)
    xyz, valid, meta = read_surface(src)
    seed = seed_of(meta, seed)
    summary, arrays = detect(xyz, valid, sampler, seed, params)
    record = {
        "kind": "kit-switchfix-repair", "tool": "kit switchfix repair", "source": str(src),
        "source_sha256": {f: _sha256(src / f) for f in ("x.tif", "y.tif", "z.tif", "meta.json")
                          if (src / f).is_file()},
        "prediction": prediction_label or getattr(sampler, "label", ""), "seed": seed,
        "params": params or PARAMS, "params_digest": params_digest(params), "detect": summary,
        "method": "cut back: flagged vertices set to (-1, -1, -1); nothing moved; side files (generations.tif, "
                  "mask.tif) not copied",
    }
    write_kept(src, out, xyz, arrays["keep"], meta, record, overwrite)
    record["out"] = str(out)
    if record_path:
        Path(record_path).parent.mkdir(parents=True, exist_ok=True)
        Path(record_path).write_text(json.dumps(record, indent=1) + "\n")
    return record, arrays


# ---------------------------------------------------------------- planted switch and random cuts

def smoothstep(t):
    np = _np()
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def project_onto(points, ref_xyz, ref_valid, workers=2):
    """Each point's projection onto another surface along that surface's normal at its nearest (2x dense) vertex,
    with kit.surfbench's point-to-plane matching: (projected points, inside its footprint, signed offset)."""
    np = _np()
    from . import surfbench
    ref = surfbench.Ref("target", 0, ref_xyz, ref_valid)
    s, inside, _, nrm = surfbench.match(points, ref, workers)
    q = np.asarray(points, dtype=np.float64).reshape(-1, 3) - np.where(np.isfinite(s), s, 0.0)[:, None] * nrm
    return q, inside & np.isfinite(s), s


def splice(xyz, valid, target_xyz, target_ok, col0, ramp):
    """A copy of a grid whose columns from col0 on move onto the target positions (one per vertex, e.g. its
    projection onto the neighbouring winding) through a smoothstep ramp over `ramp` columns: fraction 0 before col0,
    1 from col0 + ramp. A vertex past col0 with no target becomes a hole. Returns (xyz, valid, fraction)."""
    np = _np()
    H, W = valid.shape
    cols = np.arange(W, dtype=np.float64)
    f = smoothstep((cols - col0) / float(ramp)) if ramp > 0 else (cols >= col0).astype(np.float64)
    f = np.broadcast_to(f[None, :], (H, W)).copy()
    moving = f > 0
    out = xyz.copy()
    tgt = np.where(target_ok[..., None], target_xyz, xyz)
    out = out + f[..., None] * (tgt - xyz)
    v = valid & ~(moving & ~target_ok)
    return out, v, f


def random_cut(valid, sizes, rng, protect=None):
    """A removal mask of len(sizes) 4-connected blobs of the given vertex counts, each grown breadth-first from a
    random valid vertex not yet removed (random order of neighbours); a blob that runs out of room continues from
    another random vertex until it has its count. `protect` (row, col) is never removed."""
    np = _np()
    H, W = valid.shape
    avail = valid.copy()
    if protect is not None:
        avail[protect] = False
    rem = np.zeros_like(valid)
    for size in sorted((int(s) for s in sizes), reverse=True):
        need = size
        while need > 0 and avail.any():
            cand = np.flatnonzero(avail.ravel())
            start = int(cand[rng.integers(len(cand))])
            queue = [start]
            avail.ravel()[start] = False
            head = 0
            while head < len(queue) and need > 0:
                q = queue[head]
                head += 1
                rem.ravel()[q] = True
                need -= 1
                r, c = divmod(q, W)
                nb = [(r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)]
                for k in rng.permutation(4):
                    rr, cc = nb[k]
                    if 0 <= rr < H and 0 <= cc < W and avail[rr, cc]:
                        avail[rr, cc] = False
                        queue.append(rr * W + cc)
            for q in queue[head:]:          # claimed but not used: give back
                avail.ravel()[q] = True
    return rem


def removed_blobs(before, after):
    """Vertex counts of the 4-connected components of the vertices valid before and not after."""
    np = _np()
    lab, n = _components(before & ~after)
    return [int(c) for c in np.bincount(lab[lab >= 0], minlength=n)] if n else []


# ---------------------------------------------------------------- command line

def build_parser(p):
    sub = p.add_subparsers(dest="switchfix_cmd", required=True)
    for name, hlp in (("detect", "flag the vertices the seed's winding cannot reach without crossing a barrier"),
                      ("repair", "write a copy with the flagged vertices removed, and a JSON record")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("surface")
        if name == "repair":
            s.add_argument("out")
            s.add_argument("--record", help="also write the record here")
            s.add_argument("--overwrite", action="store_true")
        s.add_argument("--prediction", required=True,
                       help="the surface prediction the trace was made on: a bucket prefix or URL (cached), or a "
                            "local or remote OME-Zarr")
        s.add_argument("--seed", nargs=3, type=float, metavar=("X", "Y", "Z"),
                       help="seed point (default: meta.json seed, else the grid centre)")
        s.add_argument("--cache", help="chunk cache folder (default work/surfbench/cache)")
        s.add_argument("--workers", type=int, default=4)
        s.add_argument("--json", action="store_true")
        if name == "detect":
            s.add_argument("--out", help="also write the summary here")
    sub.add_parser("params", help="print the frozen parameters and their digest")


def cmd_switchfix(args):
    try:
        if args.switchfix_cmd == "params":
            print(json.dumps({"params": PARAMS, "digest": params_digest()}, indent=1))
            return 0
        sampler = open_prediction(args.prediction, args.cache, args.workers)
        if args.switchfix_cmd == "detect":
            xyz, valid, meta = read_surface(args.surface)
            summary, _ = detect(xyz, valid, sampler, seed_of(meta, args.seed))
            summary = {"kind": "kit-switchfix-detect", "surface": args.surface, "prediction": sampler.label,
                       **summary}
            if args.out:
                Path(args.out).parent.mkdir(parents=True, exist_ok=True)
                Path(args.out).write_text(json.dumps(summary, indent=1) + "\n")
            print(json.dumps(summary, indent=1) if args.json else
                  f"flagged {summary['flagged']} of {summary['vertices']} ({summary['flagged_share']}); classes "
                  f"{summary['classes']}; jump edges {summary['jump_edges']}")
            return 0
        rec, _ = repair(args.surface, args.out, sampler, args.seed, args.record, overwrite=args.overwrite)
        d = rec["detect"]
        print(json.dumps(rec, indent=1) if args.json else
              f"{args.out}: kept {d['kept']} of {d['vertices']}, flagged {d['flagged']} ({d['flagged_share']})")
        return 0
    except SwitchFixError as exc:
        print(f"switchfix: {exc}", file=sys.stderr)
        return 2
