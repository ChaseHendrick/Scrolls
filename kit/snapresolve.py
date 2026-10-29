"""Neighbor-consensus resolver for the face snap: give an own recto face to vertices the snap left without one.

kit labelsnap (kit.snap.snap_face, per-vertex form) measures a recto face at most vertices of a label. Most of its
remaining misses are vertices it left without a face because two bands were about as near, the band ran off the
profile, or the band was farther than max_move; those take an offset filled in from neighbors, which in development
was right far less often than a measured face (Interpretation).

`resolve` revisits exactly those vertices. For each it lists every band on its CT profile (kit.snaptruth.bands, the
snap's own band finder and settings) and each band's recto face, predicts the vertex's offset from the faces its
neighbors measured (a least-squares plane over the known offsets in a window, or their median when few), and takes
the candidate face nearest that prediction when it is within `tol` voxels of it and clearly nearer than the next
candidate. Newly resolved vertices join the known set and the pass repeats, so a resolved region grows inward from
measured vertices. A vertex that no candidate fits stays as the snap left it. The idea is the surface continuity
prior of optimal surface detection (one sheet does not jump between bands from one vertex to the next), applied only
where the snap's own evidence is ambiguous.

A resolved vertex is geometry, not a reading. Resolving has not been scored on its own against an independent scan,
so it is an option, off by default in kit finesnap.
"""

import math

from . import snap as S
from . import snaptruth as T

VERSION = 1
# the snap's reasons a vertex may be resolved from (kit.snap.FACE_REASONS): ambiguous or off the profile, too far
FIXABLE = (5, 6)
RESOLVED = 10                      # reason code written for a resolved vertex (not one of kit.snap.FACE_REASONS)
DEFAULTS = {
    "window": 7,                   # neighbor window, grid cells (odd)
    "min_known": 4,                # known offsets needed in the window to predict at all
    "plane_min": 6,                # known offsets needed for the plane fit; fewer use the median
    "tol": 1.0,                    # a candidate face must lie within this of the prediction, voxels
    "margin": 0.75,                # and be nearer than the next candidate by at least this, voxels
    "reach": 8.0,                  # candidate faces farther than this from the label are ignored, voxels
    "passes": 6,                   # resolve passes (stops early when a pass resolves nothing)
    "mode": "consensus",           # consensus: the candidate nearest the neighbors' prediction; nearest: the candidate
                                   # nearest the label (the snap's own rule without the ambiguity abstention); both:
                                   # consensus first, then nearest for what is left
}
MODES = ("consensus", "nearest", "both")


def _np():
    return S._numpy()


def recto_signs(base, nvx, axis=None, recto_sign=None):
    """Per vertex +1 when the recto face lies at negative offsets along the normal, -1 at positive ones, as
    kit.snap.snap_face names it (from `recto_sign`, or the scroll axis)."""
    np = _np()
    if recto_sign is not None:
        return np.sign(np.broadcast_to(np.asarray(recto_sign, dtype=np.float64), (len(base),)).copy())
    if axis is None:
        raise S.SnapError("resolve needs the scroll axis or a recto sign to name the recto face")
    radial, _ = S._radial(base, axis)
    return np.where((nvx * radial).sum(1) >= 0, 1.0, -1.0)


def candidates(t, prof, rs, face_opts=None, reach=DEFAULTS["reach"]):
    """Every band's recto face on one profile (t units), nearest the label first; faces off the profile and
    faces farther than `reach` are left out."""
    bl, _, _ = T.bands(t, prof, face_opts)
    out = []
    for lo, hi in bl:
        f = lo if rs > 0 else hi
        if math.isfinite(f) and abs(f) <= reach:
            out.append(float(f))
    return sorted(out, key=abs)


def predict(K, r, c, o):
    """The offset at (r, c) predicted from the known offsets K (nan unknown) in the window: a least-squares plane in
    the grid coordinates with plane_min or more known values, their median with min_known or more, else nan."""
    np = _np()
    h = int(o["window"]) // 2
    H, W = K.shape
    r0, r1, c0, c1 = max(0, r - h), min(H, r + h + 1), max(0, c - h), min(W, c + h + 1)
    win = K[r0:r1, c0:c1]
    m = np.isfinite(win)
    k = int(m.sum())
    if k < int(o["min_known"]):
        return float("nan")
    if k < int(o["plane_min"]):
        return float(np.median(win[m]))
    rr, cc = np.nonzero(m)
    A = np.stack([np.ones(k), rr + r0 - r, cc + c0 - c], 1).astype(np.float64)
    coef, *_ = np.linalg.lstsq(A, win[m].astype(np.float64), rcond=None)
    if np.linalg.matrix_rank(A) < 3:
        return float(np.median(win[m]))
    return float(coef[0])


def resolve(xs, ys, zs, valid, sampler, snapped, axis=None, recto_sign=None, face_opts=None, opts=None,
            batch=S.DEFAULT_BATCH):
    """Resolve the vertices a face snap left without a face. `snapped` is the result of kit.snap.snap_face (or
    kit.labelsnap.label_snap) on this mesh; its detail grids name the measured offsets and the reasons. Returns a
    dict: xs, ys, zs (moved grids), D (offset along the normal, nan where the vertex stays), measured (own or
    resolved offsets), resolved (bool grid), reason (the snap's, with RESOLVED where resolved), report."""
    np = _np()
    o = dict(DEFAULTS)
    o.update(opts or {})
    fo = dict(T.FACE_DEFAULTS)
    fo.update(face_opts or {})
    det = snapped["detail"]
    n, ok = S.normals(xs, ys, zs, valid)
    K = np.array(det["measured"], dtype=np.float64)
    K[~ok] = np.nan
    reason = np.array(det["reason"], dtype=np.uint8)
    todo = ok & ~np.isfinite(K) & np.isin(reason, FIXABLE)
    ty, tx = np.nonzero(todo)
    cands = {}
    if len(ty):
        base = np.stack([xs[ty, tx], ys[ty, tx], zs[ty, tx]], -1).astype(np.float64)
        nvx = n[ty, tx].astype(np.float64)
        rs = recto_signs(base, nvx, axis, None if recto_sign is None
                         else np.broadcast_to(np.asarray(recto_sign, dtype=np.float64), xs.shape)[ty, tx])
        half = max(float(o["reach"]) + 4.0, float(S.FACE_SNAP_DEFAULTS["half"]))
        step = float(S.FACE_SNAP_DEFAULTS["step"])
        t = np.arange(-half, half + 0.5 * step, step)
        prof = S._profile(sampler, base, nvx, t, batch)
        for j in range(len(ty)):
            if np.isfinite(prof[j]).all() and rs[j] != 0:
                c = candidates(t, prof[j], rs[j], fo, o["reach"])
                if c:
                    cands[(int(ty[j]), int(tx[j]))] = c
    if o["mode"] not in MODES:
        raise S.SnapError(f"resolve mode must be one of {', '.join(MODES)}, not {o['mode']!r}")
    resolved = np.zeros(xs.shape, bool)
    passes = 0
    for _ in range(int(o["passes"]) if o["mode"] != "nearest" else 0):
        passes += 1
        new = {}
        for (r, c), cl in cands.items():
            if resolved[r, c]:
                continue
            p = predict(K, r, c, o)
            if not math.isfinite(p):
                continue
            d = sorted(abs(x - p) for x in cl)
            best = min(cl, key=lambda x: abs(x - p))
            if d[0] <= o["tol"] and (len(d) == 1 or d[1] - d[0] >= o["margin"]):
                new[(r, c)] = best
        if not new:
            break
        for (r, c), v in new.items():
            K[r, c] = v
            resolved[r, c] = True
    nearest = 0
    if o["mode"] in ("nearest", "both"):
        for (r, c), cl in cands.items():
            if not resolved[r, c]:
                K[r, c] = cl[0]                 # candidates come nearest the label first
                resolved[r, c] = True
                nearest += 1
    D = np.where(np.isfinite(K), K, np.asarray(snapped["D3"], dtype=np.float64))
    move = ok & np.isfinite(D) & (resolved | np.asarray(snapped["apply"], bool))
    xo, yo, zo = xs.copy(), ys.copy(), zs.copy()
    xo[move] = xs[move] + D[move] * n[move][:, 0]
    yo[move] = ys[move] + D[move] * n[move][:, 1]
    zo[move] = zs[move] + D[move] * n[move][:, 2]
    reason_out = reason.copy()
    reason_out[resolved] = RESOLVED
    report = {"fixable": int(todo.sum()), "with_candidates": len(cands), "resolved": int(resolved.sum()),
              "by_nearest": nearest, "passes": passes, "opts": o}
    return {"xs": xo, "ys": yo, "zs": zo, "valid": valid, "D": np.where(move, D, np.nan), "measured": K,
            "resolved": resolved, "reason": reason_out, "report": report}
