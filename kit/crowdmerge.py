"""Crowd-trace merger: fuse several traces of one sheet into one consensus surface and flag each trace's slips.
`kit crowdmerge`.

Where two sheets of a scroll touch, a tracer (a person in VC3D or an automatic grower) can slide onto the
neighboring sheet and carry on there. Different traces of the same sheet tend to slide at different places, so
where one trace has left the sheet, most of the others still follow it. This tool takes several tifxyz traces that
cover the same patch of one sheet, puts them on the grid of one of them (the base: by default the trace with the
most points), and at every grid vertex looks along the base normal from -40 to +40 voxels for each trace. Each
trace votes for the offsets where it passes (within 2 voxels of the ray). The offset with the most traces wins
(ties go to the most votes in a box of neighbors, then to the smaller move), the vertex moves to the median offset
of the traces that pass there, and it is kept only where at least two traces, and more than half of those present,
agree. The result then grows past the base ring by ring, and a second vote along its own normals cleans it up.
Every trace is then checked against it: a vertex more than 4 voxels off the consensus along its normal is a slip;
a vertex beyond the consensus is judged by the majority of traces on its own normal.

  merge  TRACE TRACE [...] --out DIR: write DIR/consensus (tifxyz), DIR/flags/NAME.tif (uint8 per vertex of each
         trace: 0 no verdict, 1 agrees, 2 slip), DIR/support.tif and DIR/crowdmerge.json
  bench  planted slips on PHerc0139's hand-traced windings (preregistration docs/prereg/2026-10-24-crowdmerge.md):
         crowds of 7 copies of a winding window, 3 of which slide onto the touching neighbor at their own place,
         scored against the hand traces, with a clean and a wrong-majority control

It is a vote, not a check against the scan: a wrong majority wins (the bench's sham control shows it does), and a
patch that only one trace covers is left out. Geometry only; it never reads ink and is never a reading.
"""

import json
import math
import sys
import time
from pathlib import Path

from . import sheetrefs as sr

SETTINGS = {
    "canvas_step_vox": 5.0,   # consensus grid spacing (the base grid, upsampled)
    "dense_step_vox": 2.0,    # trace points are densified to about this spacing before they vote
    "reach_vox": 40,          # the ray along the base normal runs from -reach to +reach in 1 voxel steps
    "tol_vox": 2.0,           # a trace passes a ray sample when one of its points is this close
    "spread_bins": 1,         # a trace's pass also counts in this many offset bins either side
    "box_cells": 9,           # canvas cells: box smoothing of the votes
    "slip_vox": 4.0,          # a trace vertex further than this from the consensus, along its normal, is a slip
    "in_plane_vox": 8.0,      # and only when it lies over the consensus (lateral distance within this)
    "flag_reach_vox": 64.0,   # trace vertices further than this from every consensus point are not over it
    "grow_cells": 100,        # the consensus may grow this many canvas rings past the base's grid
    "rings_per_vote": 3,      # rings continued in a straight line before each vote while growing
    "passes": 2,              # a second vote on the first result, with the box count deciding
    "reliability_weights": True,  # the second pass weighs each trace by how much of it agrees with the first
    "beyond_share": 0.6,      # with weights, the share of weight that settles a vertex beyond the consensus
    "min_support": 2,         # a consensus vertex needs this many traces agreeing, and more than half of those
}                             # present (with one trace given, the trace is kept as it is)
SEED = 20261024
WINDOW_MM = 8.0
SITES_PER_PAIR = 4
SITE_SPACING_MM = 8.0
CONTACT_VOX = 4.0
COPY_VOX = 8.0
RAMP_HALF_VOX = 8.0
JITTER_VOX = 0.5
CROWD = 7
SLIPPING = 3
SHAM_SLIPPING = 5
SPLITS = {"dev": [f"w{n:03d}" for n in range(23, 32)], "report": [f"w{n:03d}" for n in range(32, 41)]}
BARS = {"off_sheet_max": 0.02, "off_vs_largest_max": 0.25, "flag_recall_min": 0.90, "flag_precision_min": 0.90,
        "clean_off_max": 0.01, "clean_false_flag_max": 0.01, "sham_follow_min": 0.5}
DEFAULT_OUT = sr.DEFAULT_ROOT.parent / "crowdmerge"


class MergeError(Exception):
    pass


def _np():
    return sr._np()


def _say(log, msg):
    if log:
        log(msg)


def _densify(xyz, valid, step_vox):
    """The grid upsampled to about step_vox: (xyz, valid, normals, ok, step)."""
    _, _, ok, step = sr.grid_geometry(xyz, valid)
    k = max(1, int(math.ceil(step / step_vox))) if math.isfinite(step) else 1
    up, uv, _ = sr.upsample(xyz, valid, k)
    n, _, uok, ustep = sr.grid_geometry(up, uv)
    return up, uv, n, uok, ustep, k


def _tree(points):
    return sr._kdtree()(points)


def ray_hits(P, N, tree, reach, tol, workers=2, batch=400000):
    """(V, 2 reach + 1) bool: a point of the tree lies within tol of P + o N, o = -reach..reach (pure; tested)."""
    np = _np()
    offs = np.arange(-reach, reach + 1, dtype=np.float64)
    V, O = len(P), len(offs)
    hit = np.zeros((V, O), bool)
    per = max(1, batch // O)
    for i in range(0, V, per):
        Q = P[i:i + per, None, :] + offs[None, :, None] * N[i:i + per, None, :]
        d, _ = tree.query(Q.reshape(-1, 3), distance_upper_bound=tol, workers=workers)
        hit[i:i + per] = np.isfinite(d).reshape(-1, O)
    return hit


def _refine(P, N, off, tree, pts, nrm, tol, workers=2):
    """Each vertex's offset along N to where the ray meets the tangent plane of the tree's point nearest
    P + off N (the plain projection where the plane is steeper than 70 degrees to the ray); NaN when no point is
    within tol + 1."""
    np = _np()
    d, j = tree.query(P + off[:, None] * N, distance_upper_bound=tol + 1.0, workers=workers)
    ok = np.isfinite(d)
    out = np.full(len(P), np.nan)
    v = pts[j[ok]] - P[ok]
    proj = np.einsum("ij,ij->i", v, N[ok])
    q = nrm[j[ok]]
    c = np.einsum("ij,ij->i", q, N[ok])
    with np.errstate(all="ignore"):
        hit = np.einsum("ij,ij->i", v, q) / c
    out[ok] = np.where(np.abs(c) > 0.34, hit, proj)
    return out


def _box(a, mask, box):
    """Box mean of a over mask (H, W[, K]), zero outside it."""
    np = _np()
    from scipy import ndimage
    m = mask.astype(np.float32)
    w = ndimage.uniform_filter(m, box, mode="constant")
    size = (box, box) + ((1,) if a.ndim == 3 else ())
    s = ndimage.uniform_filter(a.astype(np.float32) * (m[..., None] if a.ndim == 3 else m), size, mode="constant")
    return s / np.maximum(w, 1e-6)[(...,) + ((None,) if a.ndim == 3 else ())] * (m[..., None] if a.ndim == 3 else m)


def choose(votes, mask, offs, box, smooth_first=False):
    """Per canvas vertex the winning offset index: the most traces passing at that vertex; ties go to the offset
    with the most votes in the box round it, then to the smaller |offset| (pure; tested). votes: (H, W, O) number
    of traces passing per offset. The box only breaks ties: where the base itself bends (a slip of its own), the
    right offset changes from vertex to vertex and a smoothed count would smear it. With smooth_first (the second
    pass, on a canvas that already follows the consensus) the box count decides and the vertex's own breaks ties."""
    np = _np()
    sm = _box(votes, mask, box)
    top = max(float(sm.max()), 1.0)
    vt = max(float(votes.max()), 1.0)
    key = (sm + 0.9 * votes / vt) if smooth_first else (votes + 0.9 * sm / top)
    key = key - 1e-3 * np.abs(offs)[None, None, :] / max(float(np.abs(offs).max()), 1.0)
    return key.argmax(-1)


def _vote(P, N, dense, S, method, shape, mask, workers, smooth_first=False, weights=None):
    """Offsets, support and presence for the canvas vertices P (normals N) that sit at mask in a grid of shape,
    and the weighted support and presence (each trace's vote counts its weight; all 1 when weights is None)."""
    np = _np()
    wts = np.ones(len(dense)) if weights is None else np.asarray(weights, dtype=np.float64)
    reach, tol = int(S["reach_vox"]), float(S["tol_vox"])
    offs = np.arange(-reach, reach + 1, dtype=np.float64)
    V, O = len(P), len(offs)
    votes = np.zeros((V, O), np.float32)
    present = np.zeros(V, np.int16)
    wpres = np.zeros(V)
    hits = []
    for (pts, _, tree), wt in zip(dense, wts):
        if tree is None or not V:
            hits.append(np.zeros((V, O), bool))
            continue
        h = ray_hits(P, N, tree, reach, tol, workers)
        sp = int(S["spread_bins"])
        if sp:
            g = h.copy()
            for d in range(1, sp + 1):
                g[:, d:] |= h[:, :-d]
                g[:, :-d] |= h[:, d:]
            h = g
        hits.append(h)
        votes += wt * h
        present += h.any(1)
        wpres += wt * h.any(1)
    win = None
    if method == "vote":
        grid = np.zeros(shape + (O,), np.float32)
        grid[mask] = votes
        win = choose(grid, mask, offs, int(S["box_cells"]), smooth_first)[mask]
    per = np.full((len(dense), V), np.nan)
    for t, ((pts, pn, tree), h) in enumerate(zip(dense, hits)):
        if tree is None or not V:
            continue
        if method == "vote":
            at = win
            use = h[np.arange(V), at]
        else:
            near = np.where(h, np.abs(offs)[None, :], np.inf)
            at = near.argmin(1)
            use = np.isfinite(near[np.arange(V), at])
        r = _refine(P, N, offs[at], tree, pts, pn, tol, workers)
        per[t] = np.where(use, r, np.nan)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        off = np.nanmedian(per, 0) if method == "vote" else np.nanmean(per, 0)
    support = np.isfinite(per).sum(0)
    wsup = (np.isfinite(per) * wts[:, None]).sum(0)
    if method == "vote":
        off = np.where(np.isfinite(off), off, offs[win] if V else off)
    else:
        off = np.where(np.isfinite(off), off, 0.0)
    return off, support, present, wsup, wpres


def extrapolate(X, valid, blocked):
    """One ring of new canvas vertices: each invalid, unblocked cell with two valid cells in a row beside it gets
    the mean of their straight-line continuations 2 X[n1] - X[n2] over the four directions (pure; tested)."""
    np = _np()
    H, W = valid.shape
    acc = np.zeros((H, W, 3))
    cnt = np.zeros((H, W))
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        def sh(a, k, fill):
            out = np.full_like(a, fill)
            r, c = dr * k, dc * k
            src = a[max(r, 0):H + min(r, 0), max(c, 0):W + min(c, 0)]
            out[max(-r, 0):H + min(-r, 0), max(-c, 0):W + min(-c, 0)] = src
            return out
        v1, v2 = sh(valid, 1, False), sh(valid, 2, False)
        x1, x2 = sh(X, 1, 0.0), sh(X, 2, 0.0)
        m = ~valid & ~blocked & v1 & v2
        acc[m] += 2 * x1[m] - x2[m]
        cnt[m] += 1
    new = cnt > 0
    Y = X.copy()
    Y[new] = acc[new] / cnt[new][:, None]
    return Y, new


def merge(traces, base=None, settings=None, method="vote", workers=2, log=None):
    """Fuse traces [(name, xyz (H, W, 3), valid (H, W))]; returns a dict with the consensus grid (xyz, valid), the
    per-vertex offset, support and presence, each trace's flag grid, and a summary. The consensus starts on the
    base's grid and then grows ring by ring past it (straight-line continuation, then the same vote). A vertex is
    kept only where at least min_support traces, and more than half of those present, agree. method "vote" is the
    tool; "mean" (the mean offset of each trace's nearest layer) is the naive comparison the bench scores."""
    np = _np()
    S = dict(SETTINGS, **(settings or {}))
    if method not in ("vote", "mean"):
        raise MergeError(f"unknown method {method}")
    if not traces:
        raise MergeError("no traces")
    names = [t[0] for t in traces]
    if len(set(names)) != len(names):
        raise MergeError("trace names must be distinct")
    counts = [int(np.asarray(t[2]).sum()) for t in traces]
    if base is not None and base not in names:
        raise MergeError(f"base {base} is not one of the traces")
    b = names.index(base) if base is not None else int(np.argmax(counts))
    C, Cv, CN, Cok, cstep, ck = _densify(traces[b][1], traces[b][2], S["canvas_step_vox"])
    if not Cok.any():
        raise MergeError(f"base {names[b]} has no vertex with a normal")
    dense = []
    for name, xyz, valid in traces:
        up, uv, un, uok, _, _ = _densify(xyz, valid, S["dense_step_vox"])
        pts, pn = up[uok], un[uok]
        dense.append((pts, pn, _tree(pts) if len(pts) else None))
    G = int(S["grow_cells"]) if len(traces) > 1 else 0
    H, W = Cok.shape[0] + 2 * G, Cok.shape[1] + 2 * G
    inner = (slice(G, G + Cok.shape[0]), slice(G, G + Cok.shape[1]))
    X = np.zeros((H, W, 3))
    X[inner] = np.nan_to_num(C)
    valid = np.zeros((H, W), bool)
    valid[inner] = Cok
    Nn = np.zeros((H, W, 3))
    Nn[inner] = np.nan_to_num(CN)
    og = np.zeros((H, W))
    sup = np.zeros((H, W), np.int16)
    pres = np.zeros((H, W), np.int16)
    grown = np.zeros((H, W), bool)
    off, support, present, _, _ = _vote(X[valid], Nn[valid], dense, S, method, (H, W), valid, workers)
    og[valid], sup[valid], pres[valid] = off, support, present
    out = np.zeros((H, W, 3))
    out[valid] = X[valid] + off[:, None] * Nn[valid]
    blocked = np.zeros((H, W), bool)
    ms = int(S["min_support"])
    if len(traces) > 1:
        weak = valid & ((sup < ms) | (2 * sup <= pres))
        valid &= ~weak
        blocked |= weak
        if not valid.any():
            raise MergeError("no vertex of the base is agreed by enough traces")
    rings = 0
    while rings < G:
        Y, new = out, np.zeros((H, W), bool)
        for _ in range(min(int(S["rings_per_vote"]), G - rings)):
            Y, n1 = extrapolate(Y, valid | new, blocked)
            if not n1.any():
                break
            new |= n1
            rings += 1
        if not new.any():
            break
        both = valid | new
        nrm, _, nok, _ = sr.grid_geometry(np.where(both[..., None], Y, np.nan), both)
        cand = new & nok
        blocked |= new & ~nok
        if not cand.any():
            continue
        off, support, present, _, _ = _vote(Y[cand], nrm[cand], dense, S, method, (H, W), cand, workers)
        keep = (support >= ms) & (2 * support > present)
        idx = np.argwhere(cand)
        ka, kr = idx[keep], idx[~keep]
        blocked[kr[:, 0], kr[:, 1]] = True
        if not len(ka):
            break
        kk = (ka[:, 0], ka[:, 1])
        out[kk] = Y[kk] + off[keep][:, None] * nrm[kk]
        og[kk], sup[kk], pres[kk] = off[keep], support[keep], present[keep]
        valid[kk] = True
        grown[kk] = True
    rows, cols = np.nonzero(valid)
    crop = (slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1))
    out, valid, og, sup, pres, grown = (a[crop] for a in (out, valid, og, sup, pres, grown))
    out = np.where(valid[..., None], out, np.nan)
    weights = None
    if len(traces) > 1 and int(S["passes"]) > 1 and method == "vote":
        # second pass: vote again along the first result's own normals, where offsets are near zero everywhere,
        # so the box count can decide without smearing a bend
        # so the box count can decide without smearing a bend. With reliability weights on, each trace's vote
        # counts the share of its vertices over the first result that agree with it (a trace that slipped over
        # half its area counts about half)
        if S["reliability_weights"]:
            cp, cn, _ = _flag_surface(out, valid, S)
            ct = _tree(cp) if len(cp) else None
            weights = []
            for name, xyz, v in traces:
                f = flag(xyz, v, cp, cn, ct, S, workers)
                n_on = int((f > 0).sum())
                weights.append(max(float((f == 1).sum()) / n_on, 0.05) if n_on else 0.05)
        n2, _, ok2, _ = sr.grid_geometry(out, valid)
        valid &= ok2
        off, support, present, ws, wp = _vote(out[valid], n2[valid], dense, S, method, valid.shape, valid, workers,
                                              True, weights)
        P2 = out[valid] + off[:, None] * n2[valid]
        og[valid] += off
        sup[valid], pres[valid] = support, present
        wmaj = np.ones(valid.shape, bool)
        wmaj[valid] = 2 * ws > wp
        out[valid] = P2
        weak = valid & ((sup < ms) | ~wmaj)
        valid &= ~weak
        out = np.where(valid[..., None], out, np.nan)
    flags, fstats = {}, {}
    cpts, cnrm, _ = _flag_surface(out, valid, S)
    ctree = _tree(cpts) if len(cpts) else None
    fl = [flag(xyz, v, cpts, cnrm, ctree, S, workers) for name, xyz, v in traces]
    final_w = None
    if weights is not None:
        final_w = [max(float((f == 1).sum()) / max(int((f > 0).sum()), 1), 0.05) for f in fl]
    for t, (name, xyz, v) in enumerate(traces):
        f = fl[t]
        n_on = int((f > 0).sum())
        n_off = 0
        if len(traces) > 1:
            n_off = beyond(f, xyz, v, t, dense, S, workers, final_w)
        flags[name] = f
        fstats[name] = {"vertices": int(v.sum()), "over_consensus": n_on, "judged_beyond": n_off,
                        "slip_share": sr._r(float((f == 2).sum()) / (n_on + n_off)) if n_on + n_off else None}
    cell = cstep * cstep
    based = valid & ~grown
    summary = {"traces": len(traces), "base": names[b], "method": method, "canvas": list(valid.shape),
               "canvas_step_vox": sr._r(cstep), "vertices": int(valid.sum()), "grown_vertices": int(grown.sum()),
               "grow_rings": rings,
               "moved_share": sr._r(float((np.abs(og[based]) > S["slip_vox"]).mean())) if based.any() else None,
               "contested_share": sr._r(float((2 * sup[valid] <= pres[valid]).mean())),
               "single_trace_share": sr._r(float((pres[valid] <= 1).mean())),
               "area_vox2": sr._r(float(valid.sum()) * cell, 1), "flags": fstats,
               "weights": dict(zip(names, (sr._r(w) for w in weights))) if weights else None, "settings": S}
    return {"xyz": out, "valid": valid, "offset": og, "support": sup, "present": pres, "grown": grown,
            "flags": flags, "scale_factor": ck, "summary": summary}


def beyond(f, xyz, valid, t, dense, S, workers=2, weights=None):
    """Judge, in place, a trace's vertices that are not over the consensus (f == 0) by the traces present on its
    own normal: 1 where a strict majority of them, itself included and at least min_support, pass within slip_vox,
    2 where such a majority passes elsewhere; others stay 0. With weights (each trace's reliability), a side wins
    with more than beyond_share of the weight and at least one other trace present. Returns how many were judged
    (pure; tested)."""
    np = _np()
    nrm, _, ok, _ = sr.grid_geometry(xyz, valid)
    sel = (f == 0) & ok
    if not sel.any():
        return 0
    P, N = xyz[sel], nrm[sel]
    reach, tol, slip = int(S["reach_vox"]), float(S["tol_vox"]), float(S["slip_vox"])
    offs = np.arange(-reach, reach + 1, dtype=np.float64)
    near = np.abs(offs) <= slip
    w = np.ones(len(dense)) if weights is None else np.asarray(weights, dtype=np.float64)
    agree = np.ones(len(P), np.int16)
    away = np.zeros(len(P), np.int16)
    wa = np.full(len(P), w[t])
    wy = np.zeros(len(P))
    for u, (pts, _, tree) in enumerate(dense):
        if u == t or tree is None:
            continue
        h = ray_hits(P, N, tree, reach, tol, workers)
        a = h[:, near].any(1)
        y = h.any(1) & ~a
        agree += a
        away += y
        wa += w[u] * a
        wy += w[u] * y
    tot = agree + away
    ms = int(S["min_support"])
    out = np.zeros(len(P), np.uint8)
    if weights is None:
        out[(agree >= ms) & (2 * agree > tot)] = 1
        out[(away >= ms) & (2 * away > tot)] = 2
    else:
        q = float(S["beyond_share"])
        out[(tot >= 2) & (wa > q * (wa + wy))] = 1
        out[(away >= 1) & (wy > q * (wa + wy))] = 2
    f[sel] = out
    return int((out > 0).sum())


def _flag_surface(xyz, valid, S):
    np = _np()
    up, uv, n, uok, _, _ = _densify(xyz, valid, S["dense_step_vox"])
    return up[uok], n[uok], uok


def flag(xyz, valid, cpts, cnrm, ctree, settings=None, workers=2):
    """(H, W) uint8 for one trace against the consensus points: 0 not over the consensus, 1 agrees, 2 slip (pure;
    tested)."""
    np = _np()
    S = dict(SETTINGS, **(settings or {}))
    f = np.zeros(valid.shape, np.uint8)
    if ctree is None or not valid.any():
        return f
    q = xyz[valid]
    d, j = ctree.query(q, distance_upper_bound=float(S["flag_reach_vox"]), workers=workers)
    ok = np.isfinite(d)
    jj = np.where(ok, j, 0)
    v = q - cpts[jj]
    dn = np.einsum("ij,ij->i", v, cnrm[jj])
    dp = np.sqrt(np.maximum((v * v).sum(-1) - dn * dn, 0.0))
    over = ok & (dp <= S["in_plane_vox"])
    out = np.where(over, np.where(np.abs(dn) > S["slip_vox"], 2, 1), 0).astype(np.uint8)
    f[valid] = out
    return f


def write(out_dir, res, base_meta=None):
    """DIR/consensus (tifxyz), DIR/support.tif, DIR/offset.tif, DIR/flags/NAME.tif, DIR/crowdmerge.json."""
    np = _np()
    import tifffile
    d = Path(out_dir)
    (d / "consensus").mkdir(parents=True, exist_ok=True)
    (d / "flags").mkdir(exist_ok=True)
    xyz, valid = res["xyz"], res["valid"]
    for i, a in enumerate("xyz"):
        tifffile.imwrite(str(d / "consensus" / f"{a}.tif"), np.where(valid, xyz[..., i], -1.0).astype(np.float32))
    meta = dict(base_meta or {})
    if isinstance(meta.get("scale"), list):
        meta["scale"] = [float(s) * res["scale_factor"] for s in meta["scale"]]
    elif isinstance(meta.get("scale"), (int, float)):
        meta["scale"] = float(meta["scale"]) * res["scale_factor"]
    meta.setdefault("type", "seg")
    meta.setdefault("format", "tifxyz")
    meta["crowdmerge"] = {k: res["summary"][k] for k in ("traces", "base", "method", "canvas_step_vox")}
    (d / "consensus" / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    tifffile.imwrite(str(d / "support.tif"), res["support"].astype(np.uint16))
    tifffile.imwrite(str(d / "offset.tif"), np.where(valid, res["offset"], 0).astype(np.float32))
    for name, f in res["flags"].items():
        tifffile.imwrite(str(d / "flags" / f"{name}.tif"), f)
    (d / "crowdmerge.json").write_text(json.dumps(res["summary"], indent=1) + "\n")
    return d


# ---------------------------------------------------------------- bench


def _window(ref, centre_rc, mm):
    np = _np()
    side = int(math.ceil(mm * 1000.0 / sr.VOXEL_UM / ref.step))
    H, W = ref.valid.shape
    r0 = int(np.clip(centre_rc[0] - side // 2, 0, max(H - side, 0)))
    c0 = int(np.clip(centre_rc[1] - side // 2, 0, max(W - side, 0)))
    return slice(r0, r0 + side), slice(c0, c0 + side)


def sites(refs, man, names, rng, log=None):
    """(A, B, window) contact sites between chain neighbors, picked the way kit hopbench picks them."""
    np = _np()
    out, seen = [], set()
    for A in refs:
        if A.name not in names:
            continue
        for B in sr._neighbours_of(A, refs, man):
            if (B.name, A.name) in seen:
                continue
            seen.add((A.name, B.name))
            sel = np.argwhere(A.labelled())
            s, ins, _, _ = sr.match(A.xyz[A.labelled()], B)
            ok = ins & np.isfinite(s)
            if ok.sum() < 500 or float(np.median(np.abs(s[ok]))) < COPY_VOX:
                continue
            cand = sel[ok & (np.abs(s) <= CONTACT_VOX)]
            rng.shuffle(cand)
            min_cells = SITE_SPACING_MM * 1000.0 / sr.VOXEL_UM / A.step
            picked = []
            for rc in cand:
                if len(picked) >= SITES_PER_PAIR:
                    break
                if all(np.hypot(*(rc - p)) >= min_cells for p in picked):
                    picked.append(rc)
            out += [(A, B, _window(A, rc, WINDOW_MM)) for rc in picked]
    _say(log, f"{len(out)} sites on {len(names)} windings")
    return out


def crowd(up, ok, nA, s, ins, nB, step, rng, n=CROWD, slipping=SLIPPING, same=False):
    """n synthetic traces of a dense window of A: [(name, xyz, valid, truth offset from A)]; the first `slipping`
    slide onto B along a ramp through a contact point (shared when same), the rest stay on A (pure; tested)."""
    np = _np()
    from scipy import ndimage
    H, W = ok.shape
    K = np.argwhere(ok & ins & (np.abs(np.nan_to_num(s, nan=99)) <= CONTACT_VOX))
    if not len(K):
        return None
    shared = (K[rng.integers(len(K))], rng.uniform(0, 2 * math.pi))
    h = max(RAMP_HALF_VOX / step, 1.0)
    rr, cc = np.mgrid[0:H, 0:W]
    out = []
    for i in range(n):
        w = np.zeros((H, W))
        if i < slipping:
            (r0, c0), th = shared if same else (K[rng.integers(len(K))], rng.uniform(0, 2 * math.pi))
            w = np.clip(((rr - r0) * math.cos(th) + (cc - c0) * math.sin(th)) / (2 * h) + 0.5, 0, 1)
        sv = np.nan_to_num(s)
        P = up - (w * sv)[..., None] * np.nan_to_num(nB)
        valid = ok & ((w <= 0) | ins)
        g = ndimage.gaussian_filter(rng.normal(size=(H, W)), 5)
        g *= JITTER_VOX / max(float(g.std()), 1e-9)
        P = P + g[..., None] * np.nan_to_num(nA)
        truth = np.abs(w * sv)
        fr, fc = rng.uniform(0.7, 1.0, 2)
        hr, wc = max(2, int(H * fr)), max(2, int(W * fc))
        r0, c0 = rng.integers(0, H - hr + 1), rng.integers(0, W - wc + 1)
        pr, pc = rng.integers(0, 2, 2)
        sl = (slice(r0 + pr, r0 + hr, 2), slice(c0 + pc, c0 + wc, 2))
        out.append((f"t{i}", P[sl], valid[sl], truth[sl]))
    return out


def _off_share(P, A, off_vox=4.0):
    """(off-sheet count, matched count) of points against reference A."""
    np = _np()
    if not len(P):
        return 0, 0
    s, ins, _, _ = sr.match(P, A)
    m = ins & np.isfinite(s)
    return int((np.abs(s[m]) > off_vox).sum()), int(m.sum())


def _score_site(A, B, win, rng, settings, workers, log):
    np = _np()
    xyz, valid = A.xyz[win], A.valid[win] & (A.label[win] == A.gid)
    up, uv, nA, ok, step, _ = _densify(xyz, valid, 2.0)
    if ok.sum() < 1000:
        return None
    s = np.full(ok.shape, np.nan)
    ins = np.zeros(ok.shape, bool)
    nB = np.zeros(ok.shape + (3,))
    ss, ii, _, nn = sr.match(up[ok], B)
    s[ok], ins[ok], nB[ok] = ss, ii & np.isfinite(ss), nn
    row = {"A": A.name, "B": B.name, "at": [win[0].start, win[1].start], "window_points": int(ok.sum())}
    for arm, k, same in (("main", SLIPPING, False), ("clean", 0, False), ("sham", SHAM_SLIPPING, True)):
        cr = crowd(up, ok, nA, s, ins, nB, step, rng, slipping=k, same=same)
        if cr is None:
            return None
        traces = [(nm, P, v) for nm, P, v, _ in cr]
        res = {}
        for method in ("vote", "mean"):
            r = merge(traces, settings=settings, method=method, workers=workers)
            off, m = _off_share(r["xyz"][r["valid"]], A)
            d, _ = _tree(r["xyz"][r["valid"]]).query(up[ok], distance_upper_bound=4.0, workers=workers)
            res[method] = {"off": off, "matched": m, "covered": int(np.isfinite(d).sum())}
            if method == "vote":
                fl = {"tp": 0, "fp": 0, "fn": 0, "fn_outside": 0, "on": 0, "on_flagged": 0, "slipped": 0}
                for (nm, P, v, t) in cr:
                    f = r["flags"][nm][v]
                    tv = t[v]
                    sl, on = tv > 6.0, tv < 2.0
                    fl["tp"] += int((sl & (f == 2)).sum())
                    fl["fn"] += int((sl & (f != 2)).sum())
                    fl["fn_outside"] += int((sl & (f == 0)).sum())
                    fl["fp"] += int((on & (f == 2)).sum())
                    fl["on"] += int((on & (f > 0)).sum())
                    fl["on_flagged"] += int((on & (f == 2)).sum())
                    fl["slipped"] += int(sl.sum())
                res["flags"] = fl
        big = max(cr, key=lambda c: int(c[2].sum()))
        res["largest"] = dict(zip(("off", "matched"), _off_share(big[1][big[2]], A)))
        maj = [c for c in cr[:k]]
        res["majority_slipped"] = [int(sum(int((c[3][c[2]] > 4.0).sum()) for c in maj)),
                                   int(sum(int(c[2].sum()) for c in maj))]
        row[arm] = res
    v = row["main"]["vote"]
    _say(log, f"site {A.name}/{B.name} at {row['at']}: vote off {v['off']}/{v['matched']}, largest off "
              f"{row['main']['largest']['off']}/{row['main']['largest']['matched']}, flags tp {row['main']['flags']['tp']}"
              f" fp {row['main']['flags']['fp']} fn {row['main']['flags']['fn']}")
    return row


def _share(a, b):
    return sr._r(a / b) if b else None


def tally(rows):
    """Pooled shares over sites and the bar verdicts (pure; tested)."""
    def tot(arm, part, key):
        return sum(r[arm][part][key] for r in rows)
    t = {"sites": len(rows)}
    for arm in ("main", "clean", "sham"):
        a = {m: _share(tot(arm, m, "off"), tot(arm, m, "matched")) for m in ("vote", "mean", "largest")}
        a["coverage"] = _share(tot(arm, "vote", "covered"), sum(r["window_points"] for r in rows))
        f = {k: sum(r[arm]["flags"].get(k, 0) for r in rows)
             for k in ("tp", "fp", "fn", "fn_outside", "on", "on_flagged", "slipped")}
        a["flag_recall"] = _share(f["tp"], f["tp"] + f["fn"])
        a["flag_precision"] = _share(f["tp"], f["tp"] + f["fp"])
        a["false_flag_share"] = _share(f["on_flagged"], f["on"])
        a["missed_outside_share"] = _share(f["fn_outside"], f["fn"])
        ms = [sum(r[arm]["majority_slipped"][i] for r in rows) for i in (0, 1)]
        a["majority_slipped_share"] = _share(*ms)
        t[arm] = a
    m, c, s = t["main"], t["clean"], t["sham"]
    B = BARS
    ok = lambda x, y, ge=False: x is not None and y is not None and (x >= y if ge else x <= y)  # noqa: E731
    checks = {
        "off_sheet": ok(m["vote"], B["off_sheet_max"]) and ok(m["vote"], (m["largest"] or 0) * B["off_vs_largest_max"]),
        "flags": ok(m["flag_recall"], B["flag_recall_min"], True) and ok(m["flag_precision"], B["flag_precision_min"], True),
        "clean": ok(c["vote"], B["clean_off_max"]) and ok(c["false_flag_share"], B["clean_false_flag_max"]),
        "sham": ok(s["vote"], (s["majority_slipped_share"] or 0) * B["sham_follow_min"], True),
    }
    t["checks"] = checks
    t["verdict"] = "VOID" if not checks["sham"] else ("PASS" if all(checks.values()) else "FAIL")
    return t


def bench(refs_dir=sr.DEFAULT_REFS, split="dev", settings=None, workers=2, log=None, limit=None):
    """The planted-slip bench on one split; returns the report."""
    np = _np()
    if split not in SPLITS and split != "all":
        raise MergeError(f"split must be dev, report or all, not {split}")
    t0 = time.time()
    man, refs = sr.load_refs(refs_dir)
    names = set(SPLITS["dev"] + SPLITS["report"]) if split == "all" else set(SPLITS[split])
    site_list = sites(refs, man, names, np.random.default_rng(SEED), log)
    if limit:
        site_list = site_list[:limit]
    rng = np.random.default_rng(SEED + 1)
    rows = []
    for A, B, win in site_list:
        r = _score_site(A, B, win, rng, settings, workers, log)
        if r is not None:
            rows.append(r)
    if not rows:
        raise MergeError("no usable site")
    rep = {"kind": "kit-crowdmerge-bench", "version": 1, "split": split, "windings": sorted(names),
           "manifest_digest": man["digest"], "settings": dict(SETTINGS, **(settings or {})),
           "bench": {"seed": SEED, "window_mm": WINDOW_MM, "crowd": CROWD, "slipping": SLIPPING,
                     "sham_slipping": SHAM_SLIPPING, "jitter_vox": JITTER_VOX, "ramp_half_vox": RAMP_HALF_VOX},
           "bars": BARS, "tally": tally(rows), "rows": rows, "seconds": round(time.time() - t0)}
    return rep


# ---------------------------------------------------------------- command line


def build_parser(p):
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("merge", help="fuse traces of one sheet into one consensus surface and flag slips")
    a.add_argument("traces", nargs="+", help="tifxyz folders (x.tif, y.tif, z.tif, meta.json), at least two")
    a.add_argument("--out", required=True, help="output folder")
    a.add_argument("--base", help="the trace whose grid carries the consensus (folder name; default: most points)")
    a.add_argument("--method", choices=("vote", "mean"), default="vote")
    a.add_argument("--workers", type=int, default=2)
    a.add_argument("--json", action="store_true", help="print the summary as JSON")
    a = actions.add_parser("bench", help="planted slips on PHerc0139's hand-traced windings")
    a.add_argument("--refs", default=str(sr.DEFAULT_REFS), help="kit hopbench refs output (default %(default)s)")
    a.add_argument("--split", choices=("dev", "report", "all"), default="dev")
    a.add_argument("--limit", type=int, help="score only the first N sites (a smoke test)")
    a.add_argument("--out", help="report folder (default work/crowdmerge/bench-SPLIT)")
    a.add_argument("--workers", type=int, default=2)
    a.add_argument("--json", action="store_true", help="print the tally as JSON")


def _log(msg):
    print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


def cmd_crowdmerge(args):
    try:
        if args.action == "merge":
            if len(args.traces) < 2:
                raise MergeError("give at least two traces")
            traces, metas = [], {}
            for t in args.traces:
                xyz, valid, meta = sr.read_tifxyz(t)
                name = Path(t).resolve().name
                traces.append((name, xyz, valid))
                metas[name] = meta
            res = merge(traces, base=args.base, method=args.method, workers=args.workers)
            out = write(args.out, res, metas[res["summary"]["base"]])
            s = res["summary"]
            if args.json:
                print(json.dumps(s, indent=1))
                return 0
            print(f"crowdmerge: {s['traces']} traces on {s['base']}'s grid, {s['vertices']} vertices")
            print(f"  moved {s['moved_share']}, contested {s['contested_share']}, one trace only {s['single_trace_share']}")
            for name, f in s["flags"].items():
                print(f"  {name}: slip share {f['slip_share']} of {f['over_consensus']} vertices over the consensus")
            print(f"  written: {out}")
            return 0
        rep = bench(args.refs, args.split, workers=args.workers, log=_log, limit=args.limit)
    except (MergeError, sr.BenchError) as exc:
        print(f"crowdmerge: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else DEFAULT_OUT / f"bench-{args.split}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "crowdmerge-bench.json").write_text(json.dumps(rep, indent=1, default=lambda o: o.item()
                                                          if hasattr(o, "item") else str(o)) + "\n")
    t = rep["tally"]
    if args.json:
        print(json.dumps(t, indent=1))
        return 0
    m = t["main"]
    print(f"crowdmerge bench {args.split}: {t['sites']} sites, verdict {t['verdict']}")
    print(f"  off sheet: vote {m['vote']}, mean {m['mean']}, largest trace {m['largest']}; coverage {m['coverage']}")
    print(f"  slip flags: recall {m['flag_recall']}, precision {m['flag_precision']}")
    print(f"  clean control: vote off {t['clean']['vote']}, false flags {t['clean']['false_flag_share']}")
    print(f"  sham control: vote off {t['sham']['vote']} against majority slipped {t['sham']['majority_slipped_share']}")
    print(f"  report: {out / 'crowdmerge-bench.json'}")
    return 0
