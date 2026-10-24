"""Sheet-switch repair by tracking the seed's sheet through the surface prediction (kit.switchfix2: in this release
a Python API, used by kit.surfaudit; the command lines below are not registered in its kit command line).

  kit switchfix2 detect SURF --prediction P [--seed X Y Z] [--json] [--out FILE]
        track the seed's predicted sheet across the trace and say, per vertex, whether the trace is on it (kept), on
        another predicted sheet (moved back onto the tracked one), or far from it with nothing to snap to (removed)
  kit switchfix2 repair SURF OUT --prediction P [--seed X Y Z] [--record FILE]
        the same, then write OUT: a new tifxyz with moved vertices at their new positions and removed vertices set to
        (-1, -1, -1), and a JSON record; SURF is never modified
  kit switchfix2 params  print the parameters and their digest

Version 2 of kit switchfix (kit/switchfix.py, version 1, PARAMS 38da00d570bc..., is kept unchanged). Version 1 cuts
what the seed cannot reach without crossing a barrier in the prediction. This version follows the seed's own sheet in
the prediction across the trace and moves the parts of the trace that sit on another sheet back onto it. Inputs: the
trace, its seed and the surface prediction it was made on. It never reads reference windings or anything derived from
them. It is the candidate of sheet-switch repair rule version 2 (a note of the source repository), chosen on
development data only, and not shown to meet the rule's bar.

How it works (Interpretation of why, Model output of what it does):
  1. Normals of the trace grid (kit.surfbench.grid_geometry), summed over a small square of cells so a step in the
     trace does not tilt them much.
  2. Along each normal, the prediction at nearest-voxel offsets -half..half; its foreground runs (value at least the
     tracer's threshold 128) are the predicted sheets crossing that line, each with a center offset and a thickness.
     A run thicker than thick_factor times the median thickness of the runs the trace sits on is two sheets merged.
     The run the trace vertex sits on is the one whose extent comes within on_tol_vox of offset 0.
  3. Start: the vertex nearest the seed whose line has a thin run within start tol_vox of offset 0 and no other run
     within contact_vox; the nearest such vertex within start radius_cells (so a seed in a contact or off-sheet zone
     still starts on its sheet). Its tracked sheet point is that run's center.
  4. Best-first growth over the grid (8-neighbors). For a vertex not yet assigned, every assigned neighbor u
     predicts where the tracked sheet crosses this vertex's normal line: the plane through u's sheet point with u's
     normal, met by the line (the median of these predictions is used). The vertex snaps to the thin run whose
     center is nearest the prediction when it lies within snap_vox and no other run lies within ambiguous_vox of the
     same distance; otherwise it keeps the prediction itself (supported when a run covers it, dead reckoned when
     none does). Vertices with a clear snap are grown first, ambiguous and unsupported ones last, so contact zones
     are entered from the sides where the sheets are apart.
  5. Decision per vertex, from its offset o along the normal to the tracked sheet:
       - |o| at most keep_vox (keep_support_vox where the tracked point is not a snapped run): kept, whatever run the
         trace vertex sits on (near_first), since traced and hand-made surfaces sit a few voxels off the
         prediction's run centers;
       - otherwise snapped to the run the trace vertex sits on: kept;
       - otherwise snapped to another run: the trace is on another sheet here; it moves onto the tracked run's
         center (x + o n), or is removed when remove_moves is set (a development option, off);
       - otherwise (supported or dead reckoned, and beyond keep_support_vox) and never reached: removed.
  6. A moved vertex that would land within dup_vox of a kept vertex at least dup_cells grid cells away (the trace
     already covers that place on the tracked sheet) is removed instead, so a repair does not fold the trace onto
     itself.

Why a wide keep (Model output, development windows): hand-made windings sit up to several voxels off the
prediction's run centers and the tracked sheet steps onto a neighboring run in places, so a vertex within keep_vox
(9 voxels, most of a winding step) of the tracked sheet is kept whatever run it sits on; only a vertex clearly on
another run is moved. This kept more of the clean windows than a 7-voxel keep, at the cost of more switched vertices
kept; removing instead of moving, and other tracking settings, scored lower under the selection rule fixed before
they were seen (a note of the source repository lists every configuration tried).

What it cannot do (Interpretation): where the prediction's runs jitter by half a winding step or more, or where it
merges two windings over a stretch, the tracked sheet can step onto a neighbor; a correct part of the trace is then
removed, or a switched part kept. A flag is a place where the prediction does not vouch for the trace; it is not
evidence about ink and never a reading.

Coordinates are tifxyz (x, y, z) in level-0 voxels of the volume the trace was made on; the prediction must be in the
same frame. Needs numpy and scipy.
"""


import hashlib
import heapq
import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from . import switchfix as sf1


PARAMS = {
    "version": 2,
    "name": "switchfix2-sheet-track",
    "prediction": {"threshold": 128, "half_vox": 32},
    "normals": {"smooth_cells": 2},
    "runs": {"thick_factor": 1.6, "on_tol_vox": 4.0},
    "start": {"radius_cells": 10, "tol_vox": 3.0, "contact_vox": 8.0},
    "track": {"snap_vox": 4.0, "ambiguous_vox": 2.0, "min_cos": 0.5},
    "decide": {"keep_vox": 9.0, "keep_support_vox": 9.0, "near_first": True, "remove_moves": False},
    "duplicate": {"vox": 4.0, "cells": 4},
}


KEEP, MOVE, REMOVE = 0, 1, 2
ST_NONE, ST_SNAP, ST_SUPPORT, ST_DEAD = 0, 1, 2, 3
STATE_NAMES = {ST_NONE: "unreached", ST_SNAP: "snapped", ST_SUPPORT: "supported", ST_DEAD: "dead_reckoned"}


class SwitchFix2Error(ValueError):
    """A problem the caller can fix: an unreadable surface, no seed, an empty result."""


def _np():
    try:
        import numpy
    except ImportError as exc:
        raise SwitchFix2Error("kit switchfix2 needs numpy and scipy") from exc
    return numpy


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def params_digest(params=None):
    return hashlib.sha256(canonical(PARAMS if params is None else params).encode()).hexdigest()


def merged_params(over=None):
    """PARAMS with the nested overrides `over` ({section: {key: value}}) applied: a new dict."""
    p = json.loads(json.dumps(PARAMS))
    for sec, kv in (over or {}).items():
        if isinstance(kv, dict):
            p.setdefault(sec, {}).update(kv)
        else:
            p[sec] = kv
    return p


def _r(x, n=4):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else round(x, n)


# ---------------------------------------------------------------- geometry and runs


def smooth_normals(xyz, valid, cells):
    """Unit normals of the grid (kit.surfbench.grid_geometry) summed over a (2 cells + 1) square of vertices with a
    normal and renormalized, so a step in the trace tilts them little; ok marks vertices that have one. cells 0 gives
    the plain normals. Returns (normals, ok, grid step in voxels)."""
    np = _np()
    from . import surfbench
    n, _, ok, step = surfbench.grid_geometry(xyz, valid)
    if cells <= 0:
        return n, ok, step
    H, W = ok.shape
    z = np.where(ok[..., None], n, 0.0)
    pad = np.pad(z, ((cells, cells), (cells, cells), (0, 0)))
    acc = np.zeros_like(z)
    for dr in range(-cells, cells + 1):
        for dc in range(-cells, cells + 1):
            acc += pad[cells + dr:cells + dr + H, cells + dc:cells + dc + W]
    ln = np.linalg.norm(acc, axis=-1)
    ok2 = ok & (ln > 1e-9)
    out = np.where(ok2[..., None], acc / np.where(ok2, ln, 1.0)[..., None], np.nan)
    return out, ok2, step


def run_table(fg, max_runs=None):
    """The foreground runs of each profile row: (center, thickness, start, end) arrays of shape (N, K) in offset units
    (offset 0 at the middle sample), NaN where a row has fewer than K runs; runs sorted along the line."""
    np = _np()
    N, L = fg.shape
    half = (L - 1) // 2
    d = np.diff(np.pad(fg.astype(np.int8), ((0, 0), (1, 1))), axis=1)
    sr, sc = np.nonzero(d == 1)
    er, ec = np.nonzero(d == -1)
    ec = ec - 1
    counts = np.bincount(sr, minlength=N) if len(sr) else np.zeros(N, np.int64)
    K = int(counts.max()) if len(sr) else 0
    if max_runs is not None:
        K = min(K, int(max_runs))
    shape = (N, max(K, 1))
    cen, thk, a, b = (np.full(shape, np.nan) for _ in range(4))
    if len(sr):
        first = np.r_[0, np.cumsum(counts)[:-1]]
        rank = np.arange(len(sr)) - first[sr]
        m = rank < shape[1]
        cen[sr[m], rank[m]] = 0.5 * (sc[m] + ec[m]) - half
        thk[sr[m], rank[m]] = ec[m] - sc[m] + 1
        a[sr[m], rank[m]] = sc[m] - half
        b[sr[m], rank[m]] = ec[m] - half
    return cen, thk, a, b


def own_runs(a, b, tol):
    """Index of the run each line's vertex sits on: the run whose extent comes nearest offset 0, if within tol voxels;
    -1 when none does."""
    np = _np()
    dist = np.where(np.isfinite(a), np.maximum(np.maximum(a, -b), 0.0), np.inf)
    k = np.argmin(dist, axis=1)
    best = dist[np.arange(len(k)), k]
    return np.where(best <= tol, k, -1)


# ---------------------------------------------------------------- tracking


def _neighbours8(r, c, H, W):
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr or dc:
                rr, cc = r + dr, c + dc
                if 0 <= rr < H and 0 <= cc < W:
                    yield rr, cc


def track(xyz, ok, normals, cen, thk, a, b, own, thin, start_rc, params):
    """Best-first growth of the tracked sheet from start_rc (see the module notes, step 4). cen/thk/a/b/own/thin are
    per vertex of `ok` in raveled order. Returns (offset (H, W), state (H, W), run index (H, W), order (H, W))."""
    np = _np()
    T = params["track"]
    H, W = ok.shape
    vid = np.full((H, W), -1, np.int64)
    vid[ok] = np.arange(int(ok.sum()))
    off = np.full((H, W), np.nan)
    state = np.zeros((H, W), np.int8)
    runk = np.full((H, W), -1, np.int64)
    order = np.full((H, W), -1, np.int64)
    sheet = np.full((H, W, 3), np.nan)
    snap, amb, min_cos = float(T["snap_vox"]), float(T["ambiguous_vox"]), float(T["min_cos"])
    X = np.asarray(xyz, np.float64)
    Nn = np.asarray(normals, np.float64)


    def predict(r, c):
        """Median predicted offset of the tracked sheet on vertex (r, c)'s line from its assigned neighbors: each
        assigned 8-neighbor predicts where the plane through its sheet point, with its normal, meets the line."""
        x, n = X[r, c], Nn[r, c]
        preds = []
        for rr, cc in _neighbours8(r, c, H, W):
            if state[rr, cc] == ST_NONE:
                continue
            nu = Nn[rr, cc]
            den = float(nu @ n)
            if den < min_cos:
                continue
            preds.append(float(nu @ (sheet[rr, cc] - x)) / den)
        return float(np.median(preds)) if preds else None

    def choose(i, o):
        """(state, offset, run index, cost) of a vertex with raveled index i given the predicted offset o."""
        cr = cen[i]
        fin = np.isfinite(cr)
        if not fin.any():
            return ST_DEAD, o, -1, 3.0 * snap
        dist = np.abs(cr - o)
        dist[~fin] = np.inf
        dthin = np.where(thin[i], dist, np.inf)
        k = int(np.argmin(dthin))
        d1 = float(dthin[k])
        others = np.delete(dist, k)
        d2 = float(others.min()) if others.size else np.inf
        if d1 <= snap and d2 - d1 > amb:
            return ST_SNAP, float(cr[k]), k, d1
        inside = fin & (a[i] - 1.0 <= o) & (o <= b[i] + 1.0)
        if inside.any() or d1 <= snap:
            kk = int(np.flatnonzero(inside)[0]) if inside.any() else k
            return ST_SUPPORT, o, kk, snap + min(d1, snap)
        return ST_DEAD, o, -1, 3.0 * snap

    def assign(r, c, st, o, k, step):
        state[r, c] = st
        off[r, c] = o
        runk[r, c] = k
        order[r, c] = step
        sheet[r, c] = X[r, c] + o * Nn[r, c]

    r0, c0 = start_rc
    i0 = int(vid[r0, c0])
    k0 = int(own[i0])
    if k0 >= 0:
        assign(r0, c0, ST_SNAP, float(cen[i0, k0]), k0, 0)
    else:
        assign(r0, c0, ST_DEAD, 0.0, -1, 0)
    heap, tick, step = [], 0, 1

    def push_from(r, c):
        nonlocal tick
        for rr, cc in _neighbours8(r, c, H, W):
            if not ok[rr, cc] or state[rr, cc] != ST_NONE:
                continue
            nu, n = Nn[r, c], Nn[rr, cc]
            den = float(nu @ n)
            if den < min_cos:
                continue
            o = float(nu @ (sheet[r, c] - X[rr, cc])) / den
            _, _, _, cost = choose(int(vid[rr, cc]), o)
            tick += 1
            heapq.heappush(heap, (cost, tick, rr, cc))

    push_from(r0, c0)
    while heap:
        _, _, r, c = heapq.heappop(heap)
        if state[r, c] != ST_NONE:
            continue
        o = predict(r, c)
        if o is None:
            continue
        st, o2, k, _ = choose(int(vid[r, c]), o)
        assign(r, c, st, o2, k, step)
        step += 1
        push_from(r, c)
    return off, state, runk, order


def start_vertex(ok, cen, thin, own, seed_rc, params):
    """The vertex the tracking starts from: within radius_cells of the seed vertex, a vertex whose own run is thin,
    within tol_vox of offset 0, with no other run within contact_vox of it; the nearest in grid units (ties: smallest
    row, then column). None when there is none."""
    np = _np()
    S = params["start"]
    H, W = ok.shape
    idx = np.flatnonzero(ok.ravel())
    k = own
    has = k >= 0
    ar = np.arange(len(k))
    kc = np.where(has, k, 0)
    c_own = np.where(has, cen[ar, kc], np.nan)
    thin_own = has & thin[ar, kc]
    dist = np.abs(cen - c_own[:, None])
    dist[ar, kc] = np.inf
    dist[~np.isfinite(dist)] = np.inf
    clear = thin_own & (np.abs(np.nan_to_num(c_own, nan=np.inf)) <= S["tol_vox"]) & (dist.min(axis=1) > S["contact_vox"])
    good = np.zeros(H * W, bool)
    good[idx[clear]] = True
    good = good.reshape(H, W)
    r, c = seed_rc
    rad = int(S["radius_cells"])
    rr, cc = np.nonzero(good[max(0, r - rad):r + rad + 1, max(0, c - rad):c + rad + 1])
    if not len(rr):
        return None
    rr, cc = rr + max(0, r - rad), cc + max(0, c - rad)
    j = int(np.lexsort((cc, rr, (rr - r) ** 2 + (cc - c) ** 2))[0])
    return int(rr[j]), int(cc[j])


# ---------------------------------------------------------------- detect and repair


def decide(valid, ok, off, state, runk, own_g, params):
    """Per vertex KEEP, MOVE or REMOVE from the tracking (module notes, step 5), and the signed displacement along
    the normal of each moved vertex. Returns (action, displacement)."""
    np = _np()
    D = params["decide"]
    H, W = valid.shape
    action = np.full((H, W), -1, np.int8)
    action[valid] = REMOVE                              # unreached, no normal: removed
    reached = ok & (state != ST_NONE)
    ao = np.abs(np.nan_to_num(off, nan=np.inf))
    snapped = reached & (state == ST_SNAP)
    keep_tol = np.where(snapped, float(D["keep_vox"]), float(D["keep_support_vox"]))
    near = reached & (ao <= keep_tol)
    other_run = snapped & (runk != own_g)
    if D["near_first"]:                                 # close to the tracked sheet: kept whatever run it is on
        other_run &= ~near
    action[near] = KEEP
    action[snapped & ~other_run] = KEEP
    action[other_run] = MOVE
    action[reached & ~snapped & ~near] = REMOVE         # supported or dead reckoned, far from the tracked sheet
    disp = np.where(action == MOVE, np.nan_to_num(off), 0.0)
    if D["remove_moves"]:                               # a cut: what would be moved is removed instead
        action[action == MOVE] = REMOVE
        disp = np.zeros((H, W))
    return action, disp


TRACK_SECTIONS = ("prediction", "normals", "runs", "start", "track")


def track_digest(params=None):
    """Digest of the parameters the tracking depends on (prepare); the decisions (finish) do not change it."""
    p = PARAMS if params is None else params
    return params_digest({k: p[k] for k in TRACK_SECTIONS})


def prepare(xyz, valid, sampler, seed=None, params=None):
    """Steps 1 to 4: normals, the prediction's runs along them, the start vertex and the tracked sheet. Returns a dict
    of arrays and numbers that `finish` turns into decisions; it reads the prediction, the trace and the seed only."""
    np = _np()
    params = params or PARAMS
    t0 = time.time()
    P, R = params["prediction"], params["runs"]
    xyz = np.asarray(xyz, np.float64)
    valid = np.asarray(valid, bool)
    normals, ok, step = smooth_normals(xyz, valid, int(params["normals"]["smooth_cells"]))
    if not ok.any():
        raise SwitchFix2Error("no vertex with a normal")
    fg = sf1.profiles(xyz[ok], normals[ok], sampler, int(P["half_vox"]), P["threshold"])
    cen, thk, a, b = run_table(fg)
    own = own_runs(a, b, float(R["on_tol_vox"]))
    ar = np.arange(len(own))
    has = own >= 0
    t_own = thk[ar[has], own[has]]
    t_med = float(np.median(t_own)) if t_own.size else float("nan")
    thin = np.isfinite(thk) & ((thk <= R["thick_factor"] * t_med) if math.isfinite(t_med) else True)
    seed_rc = sf1.seed_vertex(xyz, valid, seed)
    start = start_vertex(ok, cen, thin, own, seed_rc, params)
    start_fallback = start is None
    if start is None:
        start = sf1.seed_vertex(xyz, valid, xyz[seed_rc], among=ok)
    off, state, runk, order = track(xyz, ok, normals, cen, thk, a, b, own, thin, start, params)
    H, W = valid.shape
    own_g = np.full((H, W), -1, np.int64)
    own_g[ok] = own
    return {"normals": normals, "ok": ok, "step": step, "t_med": t_med, "seed_rc": tuple(seed_rc),
            "start": tuple(int(v) for v in start), "start_fallback": bool(start_fallback), "off": off,
            "state": state, "runk": runk, "order": order, "own_g": own_g, "cen": cen, "thin": thin,
            "seconds": time.time() - t0,
            "track_digest": track_digest(params)}


def finish(xyz, valid, T, params=None):
    """Steps 5 and 6 from a `prepare` result: decisions, moves and the duplicate check. Returns (summary, arrays) as
    `detect`."""
    np = _np()
    params = params or PARAMS
    t0 = time.time()
    xyz = np.asarray(xyz, np.float64)
    valid = np.asarray(valid, bool)
    normals, ok, off, state, runk, own_g = (T[k] for k in ("normals", "ok", "off", "state", "runk", "own_g"))
    start = T["start"]
    H, W = valid.shape
    action, disp_g = decide(valid, ok, off, state, runk, own_g, params)
    # a move that lands where the trace already lies on the tracked sheet is removed instead
    mv = action == MOVE
    xyz_out = xyz.copy()
    xyz_out[mv] = xyz[mv] + disp_g[mv][:, None] * normals[mv]
    dup = 0
    U = params["duplicate"]
    kept = action == KEEP
    if mv.any() and kept.any():
        from scipy.spatial import cKDTree
        kr, kc = np.nonzero(kept)
        tree = cKDTree(xyz[kept])
        mr, mc = np.nonzero(mv)
        hits = tree.query_ball_point(xyz_out[mv], r=float(U["vox"]))
        for j, h in enumerate(hits):
            if not h:
                continue
            h = np.asarray(h)
            far = np.maximum(np.abs(kr[h] - mr[j]), np.abs(kc[h] - mc[j])) >= int(U["cells"])
            if far.any():
                action[mr[j], mc[j]] = REMOVE
                dup += 1
        mv = action == MOVE
        xyz_out = xyz.copy()
        xyz_out[mv] = xyz[mv] + disp_g[mv][:, None] * normals[mv]
    valid_out = valid & (action != REMOVE)
    xyz_out = np.where(valid_out[..., None], xyz_out, xyz)
    nv = int(valid.sum())
    disp = disp_g[mv]
    summary = {
        "vertices": nv, "grid": [H, W], "grid_step_vox": _r(T["step"], 2),
        "median_run_thickness_vox": _r(T["t_med"], 2), "seed_vertex": list(T["seed_rc"]), "start_vertex": list(start),
        "start_fallback": T["start_fallback"],
        "states": {STATE_NAMES[k]: int(((state == k) & ok).sum()) for k in STATE_NAMES},
        "kept": int((action == KEEP).sum()), "moved": int(mv.sum()), "removed": int((action == REMOVE).sum()),
        "duplicates_removed": dup,
        "moved_offset_vox": {"median_abs": _r(np.median(np.abs(disp)), 2) if disp.size else None,
                             "max_abs": _r(np.max(np.abs(disp)), 2) if disp.size else None},
        "params_digest": params_digest(params), "seconds": round(T.get("seconds", 0.0) + time.time() - t0, 1),
    }
    return summary, {"action": action, "offset": off, "state": state, "normals": normals, "xyz_out": xyz_out,
                     "valid_out": valid_out, "order": T["order"], "displacement": disp_g}


def detect(xyz, valid, sampler, seed=None, params=None):
    """Track the seed's sheet and decide per vertex (prepare, then finish). Returns (summary, arrays): arrays holds
    action (H, W: KEEP, MOVE, REMOVE, -1 where not valid), offset (H, W, voxels along the normal to the tracked
    sheet), state, normals, the displacement of moved vertices and the repaired grid (xyz_out, valid_out)."""
    params = params or PARAMS
    return finish(xyz, valid, prepare(xyz, valid, sampler, seed, params), params)


def write_repaired(src, out, xyz_out, valid_out, meta, record, overwrite=False):
    """Write the repaired grid: moved vertices at their new positions, removed ones (-1, -1, -1); meta.json from the
    source with bbox and area recomputed and a "switchfix2" record; staged and renamed into place."""
    np = _np()
    from . import meshqa
    src, out = Path(src), Path(os.path.abspath(out))
    rs, ro = src.resolve(), out.resolve()
    if ro == rs or rs in ro.parents or ro in rs.parents:
        raise SwitchFix2Error(f"{out} must be neither {src}, inside it, nor around it")
    if out.exists() and not overwrite:
        raise SwitchFix2Error(f"{out} exists; pass --overwrite to replace it")
    if out.exists() and not (out.is_dir() and (meshqa.is_tifxyz_dir(out) or not any(out.iterdir()))):
        raise SwitchFix2Error(f"{out}: --overwrite replaces only an empty folder or a tifxyz folder")
    if not valid_out.any():
        raise SwitchFix2Error("nothing kept")
    sub = np.where(valid_out[..., None], xyz_out, -1.0).astype(np.float32)
    area = sf1.surface_area_vx2(sub)
    new = {k: v for k, v in (meta or {}).items() if k not in ("bbox", "area_vx2", "area_cm2", "uuid", "switchfix2")}
    new.update({"format": new.get("format", "tifxyz"), "type": new.get("type", "seg"),
                "scale": new.get("scale", [0.05, 0.05]), "uuid": out.name,
                "bbox": [[float(v) for v in sub[valid_out].min(axis=0)], [float(v) for v in sub[valid_out].max(axis=0)]],
                "area_vx2": area})
    vox = (meta or {}).get("vc_gsfs_params", {}).get("voxelsize") if isinstance(meta, dict) else None
    if isinstance(vox, (int, float)) and vox > 0:
        new["area_cm2"] = area * float(vox) ** 2 / 1e8
    new["switchfix2"] = record
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{out.name}.", suffix=".switchfix2-partial", dir=out.parent))
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
    """Detect, then write OUT with moved vertices moved and removed ones removed, and a JSON record."""
    src = Path(src)
    xyz, valid, meta = sf1.read_surface(src)
    seed = sf1.seed_of(meta, seed)
    summary, arrays = detect(xyz, valid, sampler, seed, params)
    record = {
        "kind": "kit-switchfix2-repair", "tool": "kit switchfix2 repair", "source": str(src),
        "source_sha256": {f: sf1._sha256(src / f) for f in ("x.tif", "y.tif", "z.tif", "meta.json")
                          if (src / f).is_file()},
        "prediction": prediction_label or getattr(sampler, "label", ""), "seed": seed,
        "params": params or PARAMS, "params_digest": params_digest(params), "detect": summary,
        "method": "track the seed's predicted sheet; vertices on another predicted sheet moved onto it along "
                  "their normals, far vertices that no run supports set to (-1, -1, -1); side files not copied",
    }
    write_repaired(src, out, arrays["xyz_out"], arrays["valid_out"], meta, record, overwrite)
    record["out"] = str(out)
    if record_path:
        Path(record_path).parent.mkdir(parents=True, exist_ok=True)
        Path(record_path).write_text(json.dumps(record, indent=1) + "\n")
    return record, arrays


# ---------------------------------------------------------------- command line


def build_parser(p):
    sub = p.add_subparsers(dest="switchfix2_cmd", required=True)
    for name, hlp in (("detect", "track the seed's sheet and say which vertices are kept, moved or removed"),
                      ("repair", "write a copy with switched parts moved back or removed, and a JSON record")):
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
                       help="seed point (default: meta.json seed, else the grid center)")
        s.add_argument("--cache", help="chunk cache folder (default work/surfbench/cache)")
        s.add_argument("--workers", type=int, default=4)
        s.add_argument("--json", action="store_true")
        if name == "detect":
            s.add_argument("--out", help="also write the summary here")
    sub.add_parser("params", help="print the parameters and their digest")


def cmd_switchfix2(args):
    try:
        if args.switchfix2_cmd == "params":
            print(json.dumps({"params": PARAMS, "digest": params_digest()}, indent=1))
            return 0
        sampler = sf1.open_prediction(args.prediction, args.cache, args.workers)
        if args.switchfix2_cmd == "detect":
            xyz, valid, meta = sf1.read_surface(args.surface)
            summary, _ = detect(xyz, valid, sampler, sf1.seed_of(meta, args.seed))
            summary = {"kind": "kit-switchfix2-detect", "surface": args.surface, "prediction": sampler.label,
                       **summary}
            if args.out:
                Path(args.out).parent.mkdir(parents=True, exist_ok=True)
                Path(args.out).write_text(json.dumps(summary, indent=1) + "\n")
            print(json.dumps(summary, indent=1) if args.json else
                  f"kept {summary['kept']}, moved {summary['moved']}, removed {summary['removed']} of "
                  f"{summary['vertices']}")
            return 0
        rec, _ = repair(args.surface, args.out, sampler, args.seed, args.record, overwrite=args.overwrite)
        d = rec["detect"]
        print(json.dumps(rec, indent=1) if args.json else
              f"{args.out}: kept {d['kept']}, moved {d['moved']}, removed {d['removed']} of {d['vertices']}")
        return 0
    except (SwitchFix2Error, sf1.SwitchFixError) as exc:
        print(f"switchfix2: {exc}", file=sys.stderr)
        return 2

