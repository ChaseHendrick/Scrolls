"""Steps the VC3D tutorial leaves to a person, done headless: checking that a seed sits on the surface
prediction and on papyrus (not air) before a trace, and trimming the parts of a surface that lie over empty CT.

Points are (x, y, z) in level-0 voxels; volume arrays are (z, y, x). Volumes are vc3d_region.Volume objects (or
anything with the same read and sample methods). Needs numpy.
"""

import itertools
import json
import shutil
from pathlib import Path

import numpy as np

from . import vc3d_io

# vc_grow_seg_from_seed's own test for a point on the surface prediction (villa e0bbb8b,
# apps/src/vc_grow_seg_from_seed.cpp: random seeds and expansion seeds both need a value >= 128).
SURFACE_THRESHOLD = 128
# Papyrus minus air under this many grey levels: the CT box has no contrast to judge by.
MIN_CONTRAST = 15
# frame: a candidate whose surface points are mostly over CT zero is not scored (the rest would be a biased few).
MIN_ON_CT = 0.5
# seed_check horizon: the shell triage of villa PR #2047 (AleksaGavric, "Add vc_diagnose_seed: pre-growth seed
# triage for vc_grow_seg_from_seed", open on 12 Oct 2026; Community report), written here from its description
# (villa's volume-cartographer is GPL-3.0; nothing is copied). Foreground is any nonzero prediction, as there.
# Shells [0, 8), [8, 16), [16, 24) and [24, 65) voxels inside the 65-voxel cube around the seed (the cube spans the
# growth horizon of 32 voxels, 8 generations of step 4; the last shell reaches its corners, about 55 voxels, as the
# PR's does); the outer three are averaged. The PR set the two minima by 5-fold cross-validation on 165 seeds of a 576^3
# PHerc1203 level-2 crop (precision 0.953, recall 0.950) and confirmed them on 200 fresh grown seeds against
# support under 40 %; one scroll, one level, one prediction: starting points, not calibrated here.
HORIZON = 32
HORIZON_SHELLS = ((0, 8), (8, 16), (16, 24), (24, 2 * HORIZON + 1))   # last: every cube voxel at r >= 24
HORIZON_EDGE = 24
HORIZON_INNER_MIN = 0.15
HORIZON_OUTER_MIN = 0.40
HORIZON_VOID = 0.02


class PrepError(ValueError):
    pass


def _box(centre_zyx, radius):
    return [[int(c) - radius, int(c) + radius + 1] for c in centre_zyx]


def seed_horizon(pred, xyz):
    """Report-only triage of a seed's growth horizon (villa PR #2047's classes): nonzero-prediction density in
    shells around the seed (level 0), the distance to the nearest volume face, and one of SEED_VOID (nothing near
    the seed), SPARSE_REGION (too little prediction near it), TRAPPED (dense at the seed, not beyond: an isolated
    blob) or HEALTHY. `edge` flags a seed within HORIZON_EDGE voxels of a face. Never changes seed_check's `ok`."""
    x, y, z = (float(v) for v in xyz)
    centre = np.round([z, y, x]).astype(int)
    shape = pred.shape(0)
    block = np.asarray(pred.read(0, _box(centre, HORIZON)), dtype=np.float64) > 0
    g = np.arange(-HORIZON, HORIZON + 1)
    d2 = g[:, None, None] ** 2 + g[None, :, None] ** 2 + g[None, None, :] ** 2
    inside = np.ones_like(block)
    for axis, (c, s) in enumerate(zip(centre, shape)):
        ok = (g + c >= 0) & (g + c < s)
        inside &= ok.reshape([-1 if k == axis else 1 for k in range(3)])
    raw = []
    for r0, r1 in HORIZON_SHELLS:
        m = (d2 >= r0 * r0) & (d2 < r1 * r1) & inside
        raw.append(float(block[m].mean()) if m.any() else 0.0)
    inner, outer = raw[0], sum(raw[1:]) / (len(raw) - 1)       # classified unrounded, as the PR does
    dist = int(min(min(c, s - 1 - c) for c, s in zip(centre, shape)))
    at_seed = bool(block[HORIZON, HORIZON, HORIZON])
    if not at_seed and inner < HORIZON_VOID and outer < HORIZON_VOID:
        cls = "SEED_VOID"
    elif inner < HORIZON_INNER_MIN and outer < HORIZON_OUTER_MIN:
        cls = "SPARSE_REGION"
    elif outer < HORIZON_OUTER_MIN:
        cls = "TRAPPED"
    else:
        cls = "HEALTHY"
    return {"class": cls, "edge": dist < HORIZON_EDGE, "distance_to_face": dist, "nonzero_at_seed": at_seed,
            "inner": round(inner, 4), "outer": round(outer, 4), "shells": [round(v, 4) for v in raw],
            "radius": HORIZON,
            "thresholds": {"inner_min": HORIZON_INNER_MIN, "outer_min": HORIZON_OUTER_MIN,
                           "source": "villa PR #2047, PHerc1203 level 2, not calibrated here"}}


def seed_check(pred, xyz, threshold=SURFACE_THRESHOLD, radius=8, ct=None, ct_radius=12, horizon=False):
    """Is the seed on the surface prediction (trilinear value >= threshold), and if not, where is the nearest
    voxel that is (within radius)? With ct, is the seed on papyrus: its CT value at or above the midpoint of the
    10th and 90th percentiles of a box around it, when that box has contrast. Returns a dict; `ok` is true only
    when the seed is on the prediction and the CT (if given) does not say air. With horizon, also seed_horizon's
    report-only triage under "horizon" (it reads a 65-voxel box; `ok` is unchanged)."""
    x, y, z = (float(v) for v in xyz)
    centre = np.round([z, y, x]).astype(int)
    shape = pred.shape(0)
    if not all(0 <= c < s for c, s in zip(centre, shape)):
        raise PrepError(f"seed {[x, y, z]} is outside the prediction volume (shape z, y, x {shape})")
    block = np.asarray(pred.read(0, _box(centre, radius)), dtype=np.float64)
    value = float(pred.sample(0, [[x, y, z]])[0])
    res = {"seed": [x, y, z], "value": round(value, 2), "threshold": threshold, "radius": radius,
           "on_prediction": value >= threshold, "box_max": float(block.max()),
           "box_fraction_on": round(float((block >= threshold).mean()), 4)}
    hits = np.argwhere(block >= threshold)
    if hits.size:
        d = np.linalg.norm(hits - radius, axis=1)
        k = int(np.argmin(d))
        zz, yy, xx = (hits[k] + centre - radius).tolist()
        res["nearest_on"] = [int(xx), int(yy), int(zz)]
        res["nearest_distance"] = round(float(d[k]), 2)
    else:
        res["nearest_on"] = None
    res["ok"] = res["on_prediction"]
    if horizon:
        res["horizon"] = seed_horizon(pred, (x, y, z))
    if ct is not None:
        res["ct"] = ct_check(ct, (x, y, z), ct_radius)
        if res["ct"]["verdict"] == "air":
            res["ok"] = False
    return res


def ct_check(ct, xyz, radius=12):
    """papyrus, air or unclear for one point of a CT volume (level 0)."""
    x, y, z = (float(v) for v in xyz)
    box = np.asarray(ct.read(0, _box(np.round([z, y, x]).astype(int), radius)), dtype=np.float64)
    value = float(ct.sample(0, [[x, y, z]])[0])
    lo, hi = (float(v) for v in np.percentile(box, [10, 90]))
    mid = (lo + hi) / 2
    out = {"value": round(value, 2), "p10": round(lo, 2), "p90": round(hi, 2), "radius": radius,
           "zero_fraction": round(float((box == 0).mean()), 4)}
    if value == 0:
        out["verdict"] = "air"
        out["why"] = "the CT reads 0 at the seed (outside the scan or its mask)"
    elif hi - lo < MIN_CONTRAST:
        out["verdict"] = "unclear"
        out["why"] = f"the box around the seed has under {MIN_CONTRAST} grey levels of contrast"
    else:
        out["verdict"] = "papyrus" if value >= mid else "air"
    return out


def _read_xyz(surface):
    p = Path(surface)
    rasters = [vc3d_io.read_tiff(p / f"{a}.tif") for a in "xyz"]
    h, w = rasters[0].h, rasters[0].w
    if any((r.h, r.w) != (h, w) for r in rasters):
        raise PrepError(f"{p}: x, y and z tifs differ in size")
    return [np.asarray(r.floats(), dtype=np.float32).reshape(h, w) for r in rasters]


def trim_over_zero(surface, ct, out, level=0, scale_segmentation=1.0, dilate=0, tile=256):
    """Copy a tifxyz to out with every vertex over CT value 0 (outside the scan or its mask) made invalid
    (x = y = z = -1, the tifxyz convention), plus `dilate` grid cells around each. The CT is read at `level`
    by nearest voxel. Other files are copied; meta.json gets the new bbox. Returns counts."""
    src, out = Path(surface), Path(out)
    if out.resolve() == src.resolve():
        raise PrepError("trim writes a copy: give an out folder other than the surface")
    X, Y, Z = _read_xyz(src)
    valid = (X != -1) & (Y != -1) & (Z != -1) & (X > 0)
    zero = np.zeros_like(valid)
    h, w = X.shape
    shape = ct.shape(level)
    for r0 in range(0, h, tile):
        for c0 in range(0, w, tile):
            sl = (slice(r0, r0 + tile), slice(c0, c0 + tile))
            m = valid[sl]
            if not m.any():
                continue
            pts = np.stack([X[sl][m], Y[sl][m], Z[sl][m]], axis=1).astype(np.float64) * scale_segmentation
            lv = np.round(ct.to_level(level, pts)).astype(int)[:, ::-1]    # z, y, x at the level
            inside = np.all((lv >= 0) & (lv < np.array(shape)), axis=1)
            vals = np.zeros(len(lv))
            if inside.any():
                lo, hi = lv[inside].min(axis=0), lv[inside].max(axis=0) + 1
                block = np.asarray(ct.read(level, list(zip(lo.tolist(), hi.tolist()))))
                q = lv[inside] - lo
                vals[inside] = block[q[:, 0], q[:, 1], q[:, 2]]
            z = np.zeros(m.shape, bool)
            z[m] = vals == 0
            zero[sl] = z
    if dilate > 0 and zero.any():
        padded = np.pad(zero, dilate)     # no wrap-around: a cell at one edge never trims the other edge
        grown = np.zeros_like(zero)
        for dr in range(2 * dilate + 1):
            for dc in range(2 * dilate + 1):
                grown |= padded[dr:dr + h, dc:dc + w]
        zero = grown & valid
    keep = valid & ~zero
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out)
    for name, arr in zip("xyz", (X, Y, Z)):
        vc3d_io.write_tiff(out / f"{name}.tif", vc3d_io.raster_from_numpy(np.where(keep, arr, -1.0)))
    meta_path = out / "meta.json"
    if meta_path.is_file() and keep.any():
        meta = json.loads(meta_path.read_text())
        pts = np.stack([X[keep], Y[keep], Z[keep]], axis=1)
        meta["bbox"] = [pts.min(axis=0).tolist(), pts.max(axis=0).tolist()]
        meta_path.write_text(json.dumps(meta, indent=1))
    n_valid, n_zero = int(valid.sum()), int((valid & zero).sum())
    return {"surface": str(src), "out": str(out), "level": level, "dilate": dilate, "valid_vertices": n_valid,
            "trimmed_vertices": n_zero, "kept_vertices": int(keep.sum()),
            "trimmed_fraction": round(n_zero / n_valid, 4) if n_valid else 0.0}


def _ct_level_for(pred, ct, level):
    """The CT level on the same voxel grid as the prediction's level (same shape), or PrepError."""
    want = pred.shape(level)
    for k in range(len(ct.levels)):
        if ct.shape(k) == want:
            return k
    raise PrepError(f"no CT level has the prediction's level {level} shape {want} (CT levels: "
                    f"{[ct.shape(k) for k in range(len(ct.levels))]}); the two volumes are not on one voxel grid")


def _cell_counts(block, origin, cell, ncell, weights=None):
    """Per-cell sums of a boolean block whose first voxel sits at origin (level voxels, z y x); flat array over the
    whole cell grid ncell."""
    idx = [(o + np.arange(n)) // c for o, n, c in zip(origin, block.shape, cell)]
    flat = (idx[0][:, None, None] * ncell[1] + idx[1][None, :, None]) * ncell[2] + idx[2][None, None, :]
    return np.bincount(flat.ravel(), weights=block.ravel().astype(np.float64), minlength=int(np.prod(ncell)))


def phantom_scan(pred, ct, level=0, box=None, threshold=SURFACE_THRESHOLD, max_chunks=4096, list_limit=200):
    """Phantom surface prediction: voxels at or above threshold where the CT reads 0 (outside the scan or its
    mask), so there is no papyrus under them. Scans the prediction at `level` (inside box, z, y, x at that level,
    when given) in cells the size of one level-0 prediction chunk (the patch an inference run blends over), and
    sorts every cell holding phantoms by where its CT is:
    - edge: the cell itself holds CT, so the phantoms sit at the rim of the mask;
    - halo: no CT in the cell but some in a neighbouring cell (the one-chunk blend halo of patchwise inference);
    - beyond: no CT within one cell, which a blend halo cannot explain (a frame mismatch, or a model firing on air).
    A tracer seeded or grown there follows nothing. Returns counts and cell boxes; never writes."""
    ct_level = _ct_level_for(pred, ct, level)
    meta = pred.levels[level]["meta"]
    shape, ch = [int(s) for s in meta["shape"][-3:]], [int(c) for c in meta["chunks"][-3:]]
    ch0 = [int(c) for c in pred.levels[0]["meta"]["chunks"][-3:]]
    cell = [max(1, int(round(c * f))) for c, f in zip(ch0, pred.factors[level][-3:])]
    if box is None:
        box = [[0, s] for s in shape]
    box = [[max(0, int(a)), min(s, int(b))] for (a, b), s in zip(box, shape)]
    if any(b <= a for a, b in box):
        raise PrepError(f"box {box} holds no voxels of level {level} (shape {shape})")
    ext = [[max(0, (a // c - 1) * c), min(s, ((b - 1) // c + 2) * c)] for (a, b), c, s in zip(box, cell, shape)]
    grid = [range(a // c, (b - 1) // c + 1) for (a, b), c in zip(ext, ch)]
    n = len(grid[0]) * len(grid[1]) * len(grid[2])
    if n > max_chunks:
        raise PrepError(f"{n} chunks at level {level}: over max_chunks {max_chunks}; use a coarser level or a box")
    ncell = [-(-s // c) for s, c in zip(shape, cell)]
    ct_n, pos_n, ph_n = (np.zeros(int(np.prod(ncell))) for _ in range(3))
    for idx in itertools.product(*grid):
        eb = [[max(a, i * c), min(b, (i + 1) * c)] for i, c, (a, b) in zip(idx, ch, ext)]
        c = np.asarray(ct.read(ct_level, eb))
        ct_n += _cell_counts(c != 0, [a for a, _ in eb], cell, ncell)
        ib = [[max(a, lo), min(b, hi)] for (a, b), (lo, hi) in zip(box, eb)]
        if any(b <= a for a, b in ib):
            continue
        on = np.asarray(pred.read(level, ib)) >= threshold
        if not on.any():
            continue
        sub = c[tuple(slice(a - lo, b - lo) for (a, b), (lo, _) in zip(ib, eb))]
        origin = [a for a, _ in ib]
        pos_n += _cell_counts(on, origin, cell, ncell)
        ph_n += _cell_counts(on & (sub == 0), origin, cell, ncell)
    has_ct = (ct_n > 0).reshape(ncell)
    near = np.zeros_like(has_ct)
    padded = np.pad(has_ct, 1)
    for dz, dy, dx in itertools.product(range(3), repeat=3):
        near |= padded[dz:dz + ncell[0], dy:dy + ncell[1], dx:dx + ncell[2]]
    ph_grid = ph_n.reshape(ncell)
    phantom = ph_grid > 0
    kinds = {"edge": phantom & has_ct, "halo": phantom & ~has_ct & near, "beyond": phantom & ~near}
    pos, ph = int(pos_n.sum()), int(ph_n.sum())
    n_pred = int((pos_n > 0).sum())
    res = {"level": level, "ct_level": ct_level, "box_zyx": box, "cell_zyx": cell, "cell_level0_zyx": ch0,
           "threshold": threshold, "chunks_read": n, "cells_with_prediction": n_pred, "prediction_voxels": pos,
           "phantom_voxels": ph, "phantom_fraction": round(ph / pos, 4) if pos else 0.0,
           "phantom_cells": {k: int(v.sum()) for k, v in kinds.items()},
           "phantom_voxels_by_kind": {k: int(ph_grid[v].sum()) for k, v in kinds.items()},
           "halo_share_of_prediction_cells": round(int(kinds["halo"].sum()) / n_pred, 4) if n_pred else 0.0}
    for k, v in kinds.items():
        cells = np.argwhere(v)[:list_limit]
        if len(cells):
            res[f"{k}_cells"] = [[[int(i * c), int(min(s, (i + 1) * c))] for i, c, s in zip(ci, cell, shape)]
                                 for ci in cells]
    if kinds["beyond"].any():
        res["warning"] = (f"{int(kinds['beyond'].sum())} cells hold prediction more than one level-0 chunk from any "
                          "CT: a blend halo cannot explain that; check that the prediction and the CT share a frame")
    return res


def _grid_normals(X, Y, Z):
    """Unit normals of a tifxyz grid (cross product of the row and column derivatives; one-sided at the edges)."""
    P = np.stack([X, Y, Z], axis=-1).astype(np.float64)
    du = np.gradient(P, axis=1)
    dv = np.gradient(P, axis=0)
    n = np.cross(du, dv)
    norm = np.linalg.norm(n, axis=-1, keepdims=True)
    return n / np.where(norm > 0, norm, 1)


def surface_points(surface, window=48, points=3000, seed=0):
    """Valid vertices and normals from a window of window x window grid cells round the grid's valid centre
    (vertices whose 3 x 3 neighbourhood is valid, so normals are sound), at most `points` of them."""
    X, Y, Z = _read_xyz(surface)
    valid = (X != -1) & (Y != -1) & (Z != -1)
    core = valid.copy()
    core[1:-1, 1:-1] &= valid[:-2, 1:-1] & valid[2:, 1:-1] & valid[1:-1, :-2] & valid[1:-1, 2:]
    core[[0, -1], :] = False
    core[:, [0, -1]] = False
    if not core.any():
        raise PrepError(f"{surface}: no valid vertex with valid neighbours")
    rows, cols = np.nonzero(core)
    r0, c0 = int(np.median(rows)), int(np.median(cols))
    k = int(np.argmin((rows - r0) ** 2 + (cols - c0) ** 2))
    r0, c0 = int(rows[k]), int(cols[k])
    h = window // 2
    sel = np.zeros_like(core)
    sel[max(0, r0 - h):r0 + h, max(0, c0 - h):c0 + h] = True
    sel &= core
    rr, cc = np.nonzero(sel)
    if len(rr) > points:
        pick = np.random.default_rng(seed).choice(len(rr), points, replace=False)
        rr, cc = rr[pick], cc[pick]
    n = _grid_normals(X, Y, Z)[rr, cc]
    p = np.stack([X[rr, cc], Y[rr, cc], Z[rr, cc]], axis=1).astype(np.float64)
    return p, n, [r0, c0]


def _as_u8(a):
    a = np.asarray(a)
    if a.dtype == np.uint8:
        return a
    if a.dtype == np.uint16:
        return (a >> 8).astype(np.uint8)
    return np.clip(a, 0, 255).astype(np.uint8)


def sample_nearest(vol, level, xyz):
    """Nearest-voxel values at points (N, 3) given as (x, y, z) in a level's voxels, read chunk by chunk (so
    points spread over a large surface do not pull in their whole bounding box). Outside the array reads 0."""
    meta = vol.levels[level]["meta"]
    shape, ch = np.array(meta["shape"][-3:]), np.array(meta["chunks"][-3:])
    zyx = np.rint(np.asarray(xyz, dtype=np.float64).reshape(-1, 3)[:, ::-1]).astype(np.int64)
    from .vc3d_region import _dtype
    out = np.zeros(len(zyx), dtype=_dtype(meta))
    inside = np.all((zyx >= 0) & (zyx < shape), axis=1)
    if not inside.any():
        return out
    ids = np.nonzero(inside)[0]
    cidx = zyx[ids] // ch
    keys, inverse = np.unique(cidx, axis=0, return_inverse=True)
    inverse = inverse.reshape(-1)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max(1, min(getattr(vol, "workers", 8), len(keys)))) as pool:
        chunks = list(pool.map(lambda key: vol._chunk(level, tuple(int(v) for v in key)), keys))
    for k, key in enumerate(keys):
        arr = chunks[k]
        if arr is None:
            continue
        sel = ids[inverse == k]
        local = zyx[sel] - key * ch
        out[sel] = arr[local[:, 0], local[:, 1], local[:, 2]]
    return out


def frame_score(ct, level, pts, normals, scale=1.0, affine=None, half=30, gap=None):
    """Seating of sampled surface points in one candidate frame: points (level-0 xyz of the surface's own
    frame) times scale, then through affine (3 x 4 or 4 x 4, xyz, column convention) when given; normals by the
    inverse transpose. The CT is sampled along each normal at -half..half voxels of `level` and the stack is
    scored as check_surface scores a render (vc3d_seat.seating). Also: the share of points inside the volume
    and on nonzero CT."""
    from . import vc3d_seat
    p = np.asarray(pts, dtype=np.float64) * scale
    n = np.asarray(normals, dtype=np.float64)
    if affine is not None:
        A = np.asarray(affine, dtype=np.float64)[:3]
        p = p @ A[:, :3].T + A[:, 3]
        n = n @ np.linalg.inv(A[:, :3])        # rows times inv(M) == (inv(M).T @ n.T).T
        n /= np.where(np.linalg.norm(n, axis=1, keepdims=True) > 0, np.linalg.norm(n, axis=1, keepdims=True), 1)
    lp = ct.to_level(level, p)
    shape = np.array(ct.shape(level)[::-1], dtype=np.float64)       # x, y, z
    inside = np.all((lp >= 0) & (lp <= shape - 1), axis=1)
    res = {"scale_segmentation": scale, "affine": None if affine is None else np.asarray(affine).tolist(),
           "points": len(p), "inside_fraction": round(float(inside.mean()), 4)}
    if not inside.any():
        res.update(score=-1.0, verdict="outside the volume", ct_nonzero_fraction=0.0)
        return res
    lp, ln = lp[inside], n[inside]
    offsets = np.arange(-half, half + 1, dtype=np.float64)
    layers = []
    for t in offsets:
        layers.append(_as_u8(sample_nearest(ct, level, lp + t * ln)))
    stack = np.stack(layers)                                          # layers x points
    res["ct_nonzero_fraction"] = round(float((stack[half] > 0).mean()), 4)
    seat = vc3d_seat.seating((len(offsets), 1, stack.shape[1]), stack.tobytes(), gap=gap)
    seat.pop("profile", None)
    res.update({k: seat.get(k) for k in ("score", "contrast", "coverage", "gap", "sheet_contrast", "surface_mean")})
    res["verdict"] = vc3d_seat.verdict(seat)
    # Scans differ in brightness and contrast, so the raw score ranks frames within one volume only. Across
    # volumes the contrast is divided by the spread (90th minus 10th percentile) of the values sampled.
    full = stack[:, np.all(stack > 0, axis=0)]
    spread = float(np.percentile(full, 90) - np.percentile(full, 10)) if full.size else 0.0
    res["spread"] = round(spread, 2)
    on_ct = res["ct_nonzero_fraction"] >= MIN_ON_CT
    if not on_ct:
        res["verdict"] = "mostly off the CT"
        res["raw_score"], res["score"] = res["score"], -1.0
    res["relative_score"] = (round(seat["contrast"] / spread * seat["coverage"], 4)
                             if on_ct and spread > 0 and seat.get("contrast") is not None and seat["score"] >= 0
                             else -1.0)
    return res


def rank_frames(rows, margin=1.5, key="relative_score"):
    """Order frame rows by key and say whether the best is clear: positive and at least `margin` times the
    runner-up's (or the runner-up not positive)."""
    def val(r):
        v = r.get(key)
        return -1.0 if v is None else v
    order = sorted(range(len(rows)), key=lambda i: -val(rows[i]))
    bs = val(rows[order[0]])
    ss = val(rows[order[1]]) if len(order) > 1 else -1.0
    clear = bs > 0 and (ss <= 0 or bs >= margin * ss)
    return order, {"best": order[0], "clear": bool(clear),
                   "why": ("no candidate seats on a sheet" if bs <= 0 else
                           f"best {bs:g} against runner-up {ss:g}" + ("" if clear else
                                                                      f": under {margin}x, so unclear"))}
