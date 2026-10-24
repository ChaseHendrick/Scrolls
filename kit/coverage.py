"""Winding coverage map: which turns and heights of a scroll the published segments trace, and where the gaps are.

Every top-level tifxyz mesh on one scan volume is put in cylindrical coordinates around that volume's center line
(umbilicus): angle theta = atan2(y - yc(z), x - xc(z)), radius r, height z, all in level-0 voxels of the volume. The
meshes are subsampled to at most --side nodes along each side first, so a scroll's whole set fits in memory.

What it reports:
- per mesh: its height range, radius range, and how many turns it spans (theta unwrapped along the grid's
  horizontal axis, the one along which z changes least, median over rows);
- for the scroll: which heights have any trace, the angular share traced at each height and its largest untraced
  arc, and the heights with no trace;
- untraced wraps: on fine (z, theta) cells, the radial step between neighboring meshes divided by the wrap pitch
  gives the wraps nobody traced between them, for each pair of meshes, with the pairs on one wrap (overlaps, copies)
  listed apart. The pitch comes from the meshes that pass a cell twice, one wrap apart (or --pitch);
- with --png, a picture: theta (across) against z (down) colored by radius, beside radius (across) against z.

Wraps are estimated from radius, not counted in the CT: where the scroll is squashed or the pitch changes, the
estimate is off, and "turns" is angle traveled, not a layer count. Pictures are made only for scans on no prize
list (docs/media/README.md); the numbers are made for any scan.
"""

import argparse
import concurrent.futures
import json
import math
import os
import sys
import tempfile
from pathlib import Path

from . import find as _find
from .verify import VerifyError

SIDE = 256
Z_BINS = 128
THETA_BINS = 72
R_STEP = 50.0  # voxels per radius band when the wrap pitch is not known
MIN_ROW = 8    # nodes a row needs before its turns count
CELL_Z = 40.0         # voxels: height of the fine cells the wraps are compared on
CELL_DEG = 0.5        # degrees: their width (44 voxels of arc at a radius of 5,000 voxels)
CELL_STRIDE = 1000    # theta cells per z cell in a cell id (360 / CELL_DEG is 720)
DENSE_MAX = 8         # the most points per grid quad side when filling the quads
OWN_FLOOR = 10.0      # voxels: a mesh's own wrap step must be over twice this to set where its passes split
SPLIT_DEFAULT = 30.0  # voxels: where a mesh's passes through a cell split when its own wrap step is not known
MIN_CELLS = 500       # cells two meshes must be neighbors in to be listed


def _np():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise VerifyError("kit coverage needs numpy: python -m pip install numpy tifffile") from exc
    return np


def subsample(seg, side=SIDE):
    """(xyz, valid) of a Segment keeping 1 in k nodes along each side, k chosen so the longer side is at most side."""
    h, w = seg.valid.shape
    k = max(1, math.ceil(max(h, w) / side))
    return seg.xyz[::k, ::k].astype("float64"), seg.valid[::k, ::k].copy(), k


def polar(xyz, valid, umb):
    """theta in degrees [0, 360), radius and z for every node (NaN where not valid)."""
    np = _np()
    z = np.where(valid, xyz[..., 2], np.nan)
    xc, yc = umb.at(np.nan_to_num(z))
    dx, dy = xyz[..., 0] - xc, xyz[..., 1] - yc
    theta = np.where(valid, np.degrees(np.arctan2(dy, dx)) % 360.0, np.nan)
    r = np.where(valid, np.hypot(dx, dy), np.nan)
    return theta, r, z


def turns(theta, z, valid, r=None):
    """Turns the mesh spans, that axis, and its own wrap steps. Theta is unwrapped along the grid axis on which z
    changes least, within each run of nodes a hole does not break; the turns are the median span over rows with at
    least MIN_ROW nodes. Where a run spans more than a turn, the radius one turn further on, less the radius here, is
    one wrap step of this mesh's own (given r): returned as a list (axis 1 means along rows)."""
    np = _np()
    dz = [np.nanmean(np.abs(np.diff(z, axis=a))) if z.shape[a] > 1 else np.inf for a in (0, 1)]
    axis = 1 if not (dz[1] > dz[0]) else 0
    t, v = (theta, valid) if axis == 1 else (theta.T, valid.T)
    rr = None if r is None else (r if axis == 1 else r.T)
    spans, own = [], []
    for i, (row, ok) in enumerate(zip(t, v)):
        if ok.sum() < MIN_ROW:
            continue
        best = 0.0
        for a, b in _runs(ok):
            if b - a < 2:
                continue
            u = np.degrees(np.unwrap(np.radians(row[a:b])))
            best = max(best, float(u.max() - u.min()))
            if rr is not None and abs(u[-1] - u[0]) > 360:
                if u[-1] < u[0]:
                    u = -u
                if np.all(np.diff(u) > 0):
                    rad = rr[i, a:b]
                    hit = u + 360 <= u[-1]
                    step = np.abs(np.interp(u[hit] + 360, u, rad) - rad[hit])
                    own.extend(zip((rad[hit] + step / 2).tolist(), step.tolist()))
        spans.append(best)
    return (float(np.median(spans)) / 360.0 if spans else 0.0), axis, own


def _dense(xyz, valid, cell):
    """Points filling every grid quad whose four corners are valid, bilinear between the corners, dense enough that
    neighboring points are at most half a cell (`cell` voxels) apart, up to DENSE_MAX points per quad side: so every
    mesh that crosses a fine cell has points in it."""
    np = _np()
    q = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & valid[1:, 1:]
    if not q.any():
        return np.zeros((0, 3))
    p00, p01, p10, p11 = xyz[:-1, :-1][q], xyz[:-1, 1:][q], xyz[1:, :-1][q], xyz[1:, 1:][q]
    edge = max(float(np.median(np.linalg.norm(p01 - p00, axis=-1))),
               float(np.median(np.linalg.norm(p10 - p00, axis=-1))))
    f = int(min(DENSE_MAX, max(1, math.ceil(2 * edge / cell))))
    out = []
    for a in range(f):
        for b in range(f):
            u, w = a / f, b / f
            out.append(((1 - u) * (1 - w) * p00 + (1 - u) * w * p01 + u * (1 - w) * p10 + u * w * p11)
                       .astype(np.float32))
    return np.concatenate(out)


def passes(points, umb, split, cell_z=CELL_Z, cell_deg=CELL_DEG):
    """(cells, radii) of one mesh on the fine cells: one entry per pass the mesh makes through a cell, its points'
    mean radius. A mesh that spans more than a turn passes some cells twice; its radii there are split where they
    jump by `split` voxels or more."""
    np = _np()
    if not len(points):
        return np.zeros(0, np.int64), np.zeros(0, np.float32)
    ok = np.ones((1, len(points)), bool)
    theta, r, z = (a[0] for a in polar(points[None], ok, umb))
    cell = np.floor(z / cell_z).astype(np.int64) * CELL_STRIDE + np.floor(theta / cell_deg).astype(np.int64)
    o = np.lexsort((r, cell))
    c, rr = cell[o], r[o]
    new = np.ones(len(rr), bool)
    new[1:] = (c[1:] != c[:-1]) | (np.diff(rr) >= split)
    gid = np.cumsum(new) - 1
    n = int(gid[-1]) + 1
    return c[new], (np.bincount(gid, rr, n) / np.bincount(gid, None, n)).astype(np.float32)


def mesh_record(row_id, seg, umb, side=SIDE):
    """One mesh's summary numbers and its samples: node polar coordinates (theta, r, z), its own wrap steps, and its
    passes through the fine cells."""
    np = _np()
    xyz, valid, k = subsample(seg, side)
    theta, r, z = polar(xyz, valid, umb)
    n = int(valid.sum())
    if n == 0:
        return {"id": row_id, "nodes": 0, "error": "no valid nodes"}, None
    tn, axis, own = turns(theta, z, valid, r)
    own = np.asarray(own, np.float32).reshape(-1, 2)  # (radius midway, step) pairs
    own_p50 = float(np.median(own[:, 1])) if len(own) >= MIN_ROW else None
    split = own_p50 / 2 if own_p50 and own_p50 > 2 * OWN_FLOOR else SPLIT_DEFAULT
    # the fine cells are CELL_Z high and CELL_DEG wide, which is narrower than CELL_Z voxels inside a radius of
    # about 4,600 voxels; fill to the narrower of the two at this mesh's inner radii
    cell = min(CELL_Z, max(float(np.nanpercentile(r, 10)), 1.0) * math.radians(CELL_DEG))
    cells, radii = passes(_dense(xyz, valid, cell), umb, split)
    rec = {"id": row_id, "nodes": n, "step": k, "z_min": float(np.nanmin(z)), "z_max": float(np.nanmax(z)),
           "r_min": float(np.nanmin(r)), "r_p50": float(np.nanmedian(r)), "r_max": float(np.nanmax(r)),
           "turns": round(tn, 3), "turn_axis": "rows" if axis == 1 else "columns",
           "own_step_p50": round(own_p50, 1) if own_p50 else None, "own_steps": len(own), "error": None}
    return rec, {"theta": theta[valid], "r": r[valid], "z": z[valid], "own": own,
                 "cells": cells, "radii": radii}


def accumulate(samples, z_lo, z_hi, z_bins=Z_BINS, theta_bins=THETA_BINS, r_step=R_STEP):
    """Grids over (z, theta) and (z, radius band): meshes touching each cell, and the mean radius per (z, theta).
    The radius bands reach the largest 99.5th percentile of any mesh's radii."""
    np = _np()
    r_max = max((float(np.percentile(s["r"], 99.5)) for s in samples if s is not None and len(s["r"])), default=0.0)
    r_bins = max(1, int(math.ceil(r_max / r_step)) + 1)
    zt = np.zeros((z_bins, theta_bins), np.int32)
    zr = np.zeros((z_bins, r_bins), np.int32)
    rsum = np.zeros((z_bins, theta_bins))
    rcnt = np.zeros((z_bins, theta_bins))
    span = max(z_hi - z_lo, 1e-9)
    for smp in samples:
        if smp is None:
            continue
        theta, r, z = smp["theta"], smp["r"], smp["z"]
        keep = (z >= z_lo) & (z <= z_hi)
        theta, r, z = theta[keep], r[keep], z[keep]
        zi = np.clip(((z - z_lo) / span * z_bins).astype(int), 0, z_bins - 1)
        ti = np.clip((theta / 360.0 * theta_bins).astype(int), 0, theta_bins - 1)
        ri = (r / r_step).astype(int)
        inside = ri < r_bins  # the outermost half percent of a mesh's nodes may fall past the panel
        hitr = np.zeros_like(zr, bool)
        hitr[zi[inside], ri[inside]] = True
        zr += hitr
        s1, c1 = np.zeros((z_bins, theta_bins)), np.zeros((z_bins, theta_bins))
        np.add.at(s1, (zi, ti), r)
        np.add.at(c1, (zi, ti), 1)
        zt += c1 > 0
        rsum += s1
        rcnt += c1
    with np.errstate(invalid="ignore", divide="ignore"):
        rmean = np.where(rcnt > 0, rsum / rcnt, np.nan)
    return {"zt": zt, "zr": zr, "r_mean": rmean, "r_step": r_step, "r_bins": r_bins, "z_lo": z_lo, "z_hi": z_hi}


def wraps(samples, ids, pitch=None, min_cells=MIN_CELLS):
    """Untraced wraps between traced meshes, estimated from radius on fine (z, theta) cells.

    The wrap pitch, unless given, comes from the meshes themselves: along a grid row that spans more than a turn,
    the radius one turn on less the radius here is one wrap, so the median of those steps over every mesh is the
    pitch (the median step between neighboring meshes is the fallback when no mesh spans a turn). One pitch serves
    the whole scroll, so where the wraps are packed tighter or looser than the median the count is off. In every
    cell the meshes' passes are sorted by radius; for each pair of neighbors the median step over the cells where they are
    neighbors, divided by the pitch and rounded, less one, is the wraps nobody traced between them, and a median step
    under half a pitch puts both on one wrap (an overlap or a copy). Pairs that are neighbors in fewer than min_cells
    cells count in the totals but are not listed."""
    np = _np()
    own = [smp["own"] for smp in samples if smp is not None and len(smp["own"])]
    own = np.concatenate(own) if own else np.zeros((0, 2))
    parts = [(smp["cells"], smp["radii"], np.full(len(smp["cells"]), m)) for m, smp in enumerate(samples)
             if smp is not None and len(smp["cells"])]
    if parts:
        c = np.concatenate([a for a, _, _ in parts])
        r = np.concatenate([b for _, b, _ in parts]).astype(float)
        m = np.concatenate([x for _, _, x in parts])
        o = np.lexsort((r, c))
        c, r, m = c[o], r[o], m[o]
        nb = np.nonzero((c[1:] == c[:-1]) & (m[1:] != m[:-1]))[0]
        steps, ma, mb, mid = r[nb + 1] - r[nb], m[nb], m[nb + 1], (r[nb + 1] + r[nb]) / 2
    else:
        steps = ma = mb = mid = np.zeros(0)
    pairs = {}
    if len(steps):
        key = np.minimum(ma, mb) * 100000 + np.maximum(ma, mb)
        o = np.argsort(key, kind="stable")
        key, steps_s, inner_s, mid_s = key[o], steps[o], ma[o], mid[o]
        bounds = np.nonzero(np.diff(key))[0] + 1
        for grp_k, grp_d, grp_i, grp_r in zip(np.split(key, bounds), np.split(steps_s, bounds),
                                              np.split(inner_s, bounds), np.split(mid_s, bounds)):
            a, b = int(grp_k[0] // 100000), int(grp_k[0] % 100000)
            inner = a if (grp_i == a).sum() * 2 >= len(grp_i) else b
            pairs[(a, b)] = (inner, len(grp_d), float(np.median(grp_d)), float(np.median(grp_r)))
    pitch_from = "given"
    if pitch is None:
        if len(own) >= 30:
            pitch, pitch_from = float(np.median(own[:, 1])), "median step one turn along a mesh's own rows"
        else:
            far = [d for _, n, d, _ in pairs.values() if n >= min_cells]
            pitch = float(np.median(far)) if far else None
            pitch_from = "median step between neighboring meshes (no mesh spans a full turn)"
    out = {"pitch_vox": round(pitch, 1) if pitch else None, "pitch_from": pitch_from, "own_steps": int(len(own)),
           "own_step_p10_p90": [round(float(np.percentile(own[:, 1], q)), 1) for q in (10, 90)] if len(own) else None,
           "cell_z": CELL_Z, "cell_deg": CELL_DEG, "min_cells": min_cells}
    if not pitch:
        return {**out, "adjacent_share": None, "gaps": [], "neighbors": [], "overlaps": []}
    listed, overlaps, total, adjacent = [], [], 0, 0
    for (a, b), (inner, n, med, rmid) in pairs.items():
        rec = {"inner": ids[inner], "outer": ids[b if inner == a else a], "cells": n, "step_vox": round(med, 1),
               "r_vox": round(rmid)}
        if med < pitch / 2:
            if n >= min_cells:
                overlaps.append(rec)
            continue
        rec["wraps_missing"] = max(0, int(round(med / pitch)) - 1)
        total += n
        adjacent += n if rec["wraps_missing"] == 0 else 0
        if n >= min_cells:
            listed.append(rec)
    listed.sort(key=lambda r: (-r["wraps_missing"], -r["cells"]))
    overlaps.sort(key=lambda r: -r["cells"])
    return {**out, "adjacent_share": round(adjacent / total, 3) if total else None,
            "gaps": [r for r in listed if r["wraps_missing"] > 0],
            "neighbors": [r for r in listed if r["wraps_missing"] == 0], "overlaps": overlaps}


def _runs(mask):
    """[(start, stop)] of the runs of True in a 1D boolean sequence, stop exclusive."""
    out, start = [], None
    for i, m in enumerate(list(mask) + [False]):
        if m and start is None:
            start = i
        elif not m and start is not None:
            out.append((start, i))
            start = None
    return out


def _largest_arc(row):
    """Largest run of untraced theta bins at one height, wrapping around 360 degrees."""
    n = len(row)
    empty = [not v for v in row]
    if all(empty):
        return n
    if not any(empty):
        return 0
    k = empty.index(False)  # rotate so the sequence starts on a traced bin; then no run wraps
    rot = empty[k:] + empty[:k]
    return max((b - a for a, b in _runs(rot)), default=0)


def gaps(grid, voxel_um=None):
    """Heights with no trace, and the angular coverage and largest untraced arc at each height."""
    np = _np()
    zt, zr = grid["zt"], grid["zr"]
    z_bins, theta_bins = zt.shape
    dz = (grid["z_hi"] - grid["z_lo"]) / z_bins
    z_of = lambda i: grid["z_lo"] + i * dz
    traced = zt.sum(1) > 0
    height_gaps = [{"z0": round(z_of(a), 1), "z1": round(z_of(b), 1),
                    "mm": round((b - a) * dz * voxel_um / 1000, 2) if voxel_um else None}
                   for a, b in _runs(~traced)]
    share = (zt > 0).sum(1) / theta_bins
    arcs = [_largest_arc(list(row > 0)) * 360.0 / theta_bins for row in zt]
    r_any = zr.sum(0) > 0
    last = int(np.nonzero(r_any)[0].max()) + 1 if r_any.any() else 0
    first = int(np.nonzero(r_any)[0].min()) if r_any.any() else 0
    rows = [{"z0": round(z_of(i), 1), "z1": round(z_of(i + 1), 1), "theta_share": round(float(share[i]), 3),
             "largest_arc_deg": round(arcs[i], 1), "meshes_max": int(zt[i].max()),
             "r_bands": int((zr[i] > 0).sum())} for i in range(z_bins)]
    t = [r for r in rows if r["theta_share"] > 0]
    return {"heights_traced": round(float(traced.mean()), 3),
            "full_turn_heights": round(float((share >= 1).mean()), 3),
            "full_turn_traced_heights": round(float((share[traced] >= 1).mean()), 3) if traced.any() else 0.0,
            "theta_share_median": round(float(np.median(share[traced])), 3) if traced.any() else 0.0,
            "largest_arc_median_deg": round(float(np.median([r["largest_arc_deg"] for r in t])), 1) if t else None,
            "r_traced": [first * grid["r_step"], last * grid["r_step"]],
            "height_gaps": height_gaps, "rows": rows}


_RAMP = [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)]


def _ramp(v):
    """Viridis-like colors for v in [0, 1] (NaN gives the background)."""
    np = _np()
    v = np.clip(np.nan_to_num(v, nan=0.0), 0, 1) * (len(_RAMP) - 1)
    i = np.minimum(v.astype(int), len(_RAMP) - 2)
    f = (v - i)[..., None]
    a, b = np.asarray(_RAMP, float)[i], np.asarray(_RAMP, float)[i + 1]
    return (a + (b - a) * f).astype(np.uint8)


def picture(grid, height=512, left_px=360, right_px=480):
    """An RGB array of two panels, z down both. Left: angle across (0 to 360 degrees, a mark every 90), colored by
    how many meshes trace each cell (dark: none). Right: radius from the center line across (0 at the left, a mark
    every 10 radius bands), brightness by meshes tracing each band."""
    np = _np()
    zt, zr = grid["zt"], grid["zr"]
    bg = np.array([8, 12, 16], np.uint8)
    left = _ramp((zt - 1) / max(int(zt.max()) - 1, 1))
    left[zt == 0] = bg
    cnt = zr.astype(float)
    level = 0.25 + 0.75 * np.clip(cnt / max(cnt.max(), 1), 0, 1)  # one mesh still shows
    right = (level[..., None] * np.array([225, 235, 239]) + 0.5).astype(np.uint8)
    right[zr == 0] = bg
    fz = max(1, height // zt.shape[0])

    def up(a, px, every):
        f = max(1, px // a.shape[1])
        img = np.repeat(np.repeat(a, fz, 0), f, 1)
        for c in range(0, a.shape[1] + 1, every):  # short marks at the top and bottom edges
            x = min(c * f, img.shape[1] - 1)
            img[:6, x] = img[-6:, x] = 150
        return img

    L = up(left, left_px, max(1, zt.shape[1] // 4))
    R = up(right, right_px, 10)
    gap = 16
    out = np.zeros((L.shape[0], L.shape[1] + gap + R.shape[1], 3), np.uint8)
    out[:] = bg
    out[:, :L.shape[1]] = L
    out[:, L.shape[1] + gap:] = R
    return out


def _volume_info(scroll, volume, get):
    try:
        md = _find.get_json(_find.METADATA, get)
        _, s = _find.sample(md, scroll)
    except (OSError, ValueError, VerifyError):
        return {}
    v = (s.get("volumes") or {}).get(volume) or {}
    p = v.get("properties") or {}
    return {"voxel_um": p.get("pixel_size_um"), "slices": (p.get("shape") or [None])[0] if p.get("shape") else None}


def line_for(scroll, volume=None, source=None, get=_find.http_get):
    """The center line to use: a given file or URL, else the first public line on the volume asked for (or on any
    volume, when none is asked for)."""
    from . import centerline, stackcheck
    if source and (Path(source).is_file() or stackcheck._is_url(source)):
        umb = stackcheck.load_umbilicus(source)
        return umb, {"url": source, "volume": volume or umb.volume, "source": "given"}
    found = [l for l in centerline.lines(scroll, get) if l.get("volume")]
    if volume:
        found = [l for l in found if l["volume"] == volume]
    if source:
        found = [l for l in found if l["source"] == source]
    if not found:
        raise VerifyError(f"no public center line for {scroll}" + (f" on volume {volume}" if volume else "")
                          + "; pass one with --line FILE_OR_URL (python -m kit centerline list " + scroll + ")")
    line = found[0]
    return stackcheck.load_umbilicus(line["url"]), line


def run(scroll, volume=None, line=None, meshes=None, side=SIDE, z_bins=Z_BINS, theta_bins=THETA_BINS,
        r_step=None, workers=8, limit=None, pitch=None, get=_find.http_get, progress=None):
    """The coverage report for one scroll and volume: {"scroll", "volume", "line", "meshes", "summary", "grid"}."""
    from . import atlas
    np = _np()
    umb, info = line_for(scroll, volume, line, get)
    volume = volume or info.get("volume")
    if meshes:
        rows = [{"id": m, "url": m} for m in meshes]
    else:
        if not volume:
            raise VerifyError("the center line does not name its volume; pass --volume")
        rows = [r for r in atlas.survey([scroll], get) if r["kind"] == "mesh" and r["volume"] == volume]
        if not rows:
            raise VerifyError(f"no top-level meshes of {scroll} on volume {volume}")
    rows = sorted(rows, key=lambda r: r["id"])[:limit] if limit else sorted(rows, key=lambda r: r["id"])
    os.environ.setdefault("KIT_MAX_TIFF_ELEMENTS", atlas.TIFF_LIMIT)
    vinfo = _volume_info(scroll, volume, get) if volume else {}

    def one(row):
        with tempfile.TemporaryDirectory(prefix="kit-coverage-") as tmp:
            try:
                seg = atlas.load32(row["url"], tmp)
                return mesh_record(row["id"], seg, umb, side)
            except (VerifyError, OSError, ValueError) as exc:
                return {"id": row["id"], "nodes": 0, "error": str(exc)[:300]}, None

    recs, samples = [], []
    with concurrent.futures.ThreadPoolExecutor(max(1, workers)) as ex:
        for i, (rec, s) in enumerate(ex.map(one, rows), 1):
            recs.append(rec)
            samples.append(s)
            if progress:
                progress(f"PROGRESS {i}/{len(rows)} {rec['id']}")
    ok = [r for r in recs if not r.get("error")]
    if not ok:
        raise VerifyError("no mesh could be read: " + "; ".join(str(r["error"]) for r in recs[:3]))
    z_lo = min(r["z_min"] for r in ok)
    z_hi = max(r["z_max"] for r in ok)
    if vinfo.get("slices"):
        z_lo, z_hi = 0.0, float(vinfo["slices"])
    ids = [r["id"] for r in recs]
    w = wraps(samples, ids, pitch)
    if r_step is None:
        r_step = w["pitch_vox"] / 2 if w["pitch_vox"] else R_STEP
    grid = accumulate(samples, z_lo, z_hi, z_bins, theta_bins, r_step)
    g = gaps(grid, vinfo.get("voxel_um"))
    allr = np.concatenate([smp["r"] for smp in samples if smp is not None])
    g["r_traced"] = [round(float(np.percentile(allr, 1)), 0), round(float(np.percentile(allr, 99)), 0)]
    if w["pitch_vox"] and vinfo.get("voxel_um"):
        w["pitch_um"] = round(w["pitch_vox"] * float(vinfo["voxel_um"]), 1)
    summary = {"meshes": len(recs), "read": len(ok), "turns_total": round(sum(r["turns"] for r in ok), 2),
               "z_range": [z_lo, z_hi], "z_range_from": "volume slices" if vinfo.get("slices") else "meshes",
               **{k: v for k, v in g.items() if k != "rows"}, "wraps": w}
    return {"scroll": scroll, "volume": volume, "voxel_um": vinfo.get("voxel_um"),
            "line": {k: info.get(k) for k in ("source", "kind", "volume", "url")},
            "meshes": sorted(recs, key=lambda r: (r.get("z_min") or 0)), "summary": summary, "heights": g["rows"],
            "grid": grid}


def may_draw(scroll, volume):
    """Prize lists the scroll is on; a picture is drawn only when this is empty (the public media rule)."""
    from . import atlas
    return atlas.lists_for(scroll, volume, atlas.prize_lists())


def format_report(rep):
    s = rep["summary"]
    out = [f"{rep['scroll']} on volume {rep['volume']}: {s['read']} of {s['meshes']} meshes read, "
           f"center line from {rep['line'].get('source')} ({rep['line'].get('kind') or 'given'})"]
    out.append(f"heights traced: {s['heights_traced'] * 100:.0f} % of z {s['z_range'][0]:.0f} to {s['z_range'][1]:.0f} "
               f"({s['z_range_from']}); a full turn traced at {s['full_turn_heights'] * 100:.0f} % of heights")
    arc = s["largest_arc_median_deg"]
    out.append(f"angle traced per traced height: median {s['theta_share_median'] * 100:.0f} %"
               + (f", median largest untraced arc {arc:.0f} degrees" if arc is not None else ""))
    out.append(f"radius traced (1st to 99th percentile of nodes): {s['r_traced'][0]:.0f} to {s['r_traced'][1]:.0f} "
               f"voxels from the center line; "
               f"turns spanned by all meshes together: {s['turns_total']}")
    for gp in s["height_gaps"][:8]:
        out.append(f"  no trace at z {gp['z0']:.0f} to {gp['z1']:.0f}" + (f" ({gp['mm']} mm)" if gp["mm"] else ""))
    w = s["wraps"]
    if w["pitch_vox"]:
        um = f" ({w['pitch_um']} um)" if w.get("pitch_um") else ""
        share = f"{w['adjacent_share'] * 100:.0f} %" if w["adjacent_share"] is not None else "none"
        out.append(f"wrap pitch {w['pitch_vox']} voxels{um}, the {w['pitch_from']} ({w['own_steps']} such steps); "
                   f"neighboring meshes one wrap apart in {share} of the cells they share")
        for gp in w["gaps"][:10]:
            out.append(f"  about {gp['wraps_missing']} untraced wrap(s) between {_short(gp['inner'])} and "
                       f"{_short(gp['outer'])} ({gp['step_vox']:.0f} voxels apart over {gp['cells']} cells)")
        for gp in w["overlaps"][:5]:
            out.append(f"  on one wrap: {_short(gp['inner'])} and {_short(gp['outer'])} "
                       f"({gp['step_vox']:.0f} voxels apart over {gp['cells']} cells)")
    else:
        out.append("wrap pitch: no two meshes share a cell, so untraced wraps cannot be estimated")
    out.append("meshes (low z first): id, z, radius median, turns")
    for r in rep["meshes"]:
        if r.get("error"):
            out.append(f"  {r['id']}: {r['error']}")
        else:
            out.append(f"  {r['id']}: z {r['z_min']:.0f} to {r['z_max']:.0f}, r {r['r_p50']:.0f}, {r['turns']} turns")
    out.append("Wraps are estimated from radius and the pitch, not counted in the CT.")
    return "\n".join(out)


def _short(mesh_id):
    """scroll/segment, without the mesh folder name."""
    parts = str(mesh_id).split("/")
    return "/".join(parts[:2]) if len(parts) > 2 else str(mesh_id)


def build_parser(p):
    p.add_argument("scroll", help="scroll id, such as PHerc0139")
    p.add_argument("--volume", help="scan volume id (default: the center line's volume)")
    p.add_argument("--line", help="center line JSON file or URL, or a source name from kit centerline list")
    p.add_argument("--mesh", action="append", help="a tifxyz folder or URL to use instead of the bucket's "
                   "top-level meshes on the volume (repeat)")
    p.add_argument("--side", type=int, default=SIDE, help=f"nodes kept along a mesh's longer side (default {SIDE})")
    p.add_argument("--z-bins", type=int, default=Z_BINS, help=f"height bins (default {Z_BINS})")
    p.add_argument("--theta-bins", type=int, default=THETA_BINS, help=f"angle bins (default {THETA_BINS}, 5 degrees)")
    p.add_argument("--r-step", type=float, help=f"radius band width in voxels for the picture and the per-height "
                   f"band counts (default: half the wrap pitch, or {R_STEP:g} when it is not known)")
    p.add_argument("--pitch", type=float, help="wrap pitch in voxels (default: none, estimated from the meshes)")
    p.add_argument("--workers", type=int, default=8, help="meshes fetched at once (default 8)")
    p.add_argument("--limit", type=int, help="only the first N meshes by id (default: none, every mesh)")
    p.add_argument("--png", help="write the coverage picture here (refused for a scroll on a prize list)")
    p.add_argument("--out", help="write the full report as JSON here")
    p.add_argument("--json", action="store_true", help="print the report as JSON")


def _public(rep):
    return {k: v for k, v in rep.items() if k != "grid"}


def cmd_coverage(args):
    if args.png:
        lists = may_draw(args.scroll, args.volume)
        if lists:
            raise VerifyError(f"{args.scroll} is on a prize list ({', '.join(lists)}): kit coverage gives its numbers "
                              "but draws no picture of it (docs/media/README.md); drop --png")
    say = (lambda m: print(m, file=sys.stderr, flush=True)) if not args.json else None
    rep = run(args.scroll, args.volume, args.line, args.mesh, args.side, args.z_bins, args.theta_bins, args.r_step,
              args.workers, args.limit, args.pitch, progress=say)
    if args.png:
        if may_draw(args.scroll, rep["volume"]):
            raise VerifyError(f"volume {rep['volume']} is on a prize list: no picture drawn")
        from . import tifxyz
        tifxyz.write_png(args.png, picture(rep["grid"]))
        rep["png"] = args.png
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(_public(rep), indent=1) + "\n")
    print(json.dumps(_public(rep), indent=1) if args.json else format_report(rep))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit coverage", description=__doc__.split("\n\n")[0])
    build_parser(p)
    args = p.parse_args(argv)
    try:
        return cmd_coverage(args)
    except VerifyError as exc:
        print(f"kit coverage: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
