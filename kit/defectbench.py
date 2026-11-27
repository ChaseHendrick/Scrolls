"""A dev bench of meshes with planted defects and known answers, sized like spiral-fit columns of public PHerc0343:
`python -m kit.defectbench`.

  python -m kit.defectbench cases [--json]
        the bench's cases: family, what is planted, the column it is modelled on, the verdict a fix must reach
  python -m kit.defectbench make OUT [--track column|mini|both] [--seeds N] [--only CASE ...] [--json]
        write OUT/<track>/<case>-s<seed>/ for every case: a tifxyz (x.tif, y.tif, z.tif, meta.json), defects.json
        (the planted operations, the summary truth, the mesh statistics, sha256 of every file) and truth.npz (per
        vertex: label, true winding offset k, the true position on the base winding, the planted displacement);
        the mini track adds pred.zarr, a binary sheet prediction (OME-Zarr level 0, zlib) of the same sheets, and
        umbilicus.json; OUT/manifest.json lists every case with its digests
  python -m kit.defectbench check OUT [--json]
        recompute every case's truth from its coordinates and the sheet geometry alone and compare with truth.npz,
        defects.json and the digests; exit 3 on any disagreement
  python -m kit.defectbench baseline OUT --alarm none|all|oracle|wjump --dir DIR
  python -m kit.defectbench baseline OUT --repair identity|oracle|taubin5g --dir DIR
        write a control or reference baseline in the form score reads: DIR/<track>/<case>.npy (alarm masks) or
        DIR/<track>/<case>/ (repaired tifxyz)
  python -m kit.defectbench score OUT (--alarms DIR | --repaired DIR) [--track T] [--out FILE] [--json]
        score per-vertex switch alarms or repaired meshes against the planted truth, per case and per family

Why it exists. Fixes for rough or switched meshes (smoothing, cutting, shifting, re-gridding) and sheet-switch
alarms are hard to develop on real columns: a column a fix was tuned on cannot measure it again, and real columns
have no per-vertex truth. Two spiral-fit columns of public PHerc0343 show the two kinds of defect the bench
plants: one (column A here) carries diffuse tracer roughness (creases on 12.1 % of the area, edge spikes on
16.2 %), the other (column B) one sheet-switch band (a connected region of about 1,400 quads) on top of
roughness. Those shares are used only as calibration targets. This bench plants the same kinds of defect, at the
same grid size (91 x 405 cells, a 20 voxel grid step, a 23 voxel sheet pitch), on synthetic spiral sheets where
every vertex's true winding and true position are known.

Truth. Every surface lies on kit.planted's Archimedean spiral sheets. The label of a valid vertex is computed from
its planted winding offset k and its distance to the nearest sheet only, never from a tool's output:
  wrong (2)   |k| >= 0.5: the vertex sits on another winding (switch, lens, skip, the far side of a merger)
  gap (3)     not wrong, but farther than a quarter pitch from every sheet: in the void between windings (a switch's
              ramp, a gap bridge, a chord across a curved sheet)
  fold (4)    on its sheet but in a column the trace runs backward over (the mesh folds over itself)
  rough (1)   on its winding and within a quarter pitch, but displaced more than 1 voxel from its true position
  clean (0)   on its sheet within 1 voxel of its true position
  -1          not a valid vertex (outside the footprint or in a hole)
The true position (`ref`) of every grid site is the clean base surface there, so a repair is scored by how far it
leaves each kept vertex from its true sheet and how many correct cells it cuts.

Everything here is synthetic: no scan, label, CT, prediction or model output is read. `score` reads only the bench
folder and the folder of tool outputs it is given, never a scroll path. It runs as `python -m kit.defectbench`. The bench numbers are development numbers for tools; a mesh-fix or alarm result on the bench is not a result on any scroll.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

from . import planted

SCHEMA = "kit-defectbench/1"
EXIT_DISAGREE = 3
LABELS = {-1: "invalid", 0: "clean", 1: "rough", 2: "wrong", 3: "gap", 4: "fold"}
DEFECT = (1, 2, 3, 4)
SWITCH_LIKE = (2, 3)       # what a sheet-switch alarm must flag: off the winding or between windings
ROUGH_TOL = 1.0            # voxels from the true position before a vertex on its winding counts as rough
GAP_TOL = 0.35             # pitches from every sheet before a vertex counts as in the void between windings
ROUGH_CAP = 0.30           # pitches: the largest normal offset of a rough vertex (it stays rough, never gap)

# Geometry of the column track: a 91 x 405 grid with a 20 voxel step and a 23 voxel sheet pitch (at 8.64 um), the
# size of the PHerc0343 spiral-fit columns the roughness is calibrated on; w0 51 puts the base winding at a radius
# of 1,173 voxels, so a 405-column row wraps 1.1 turns.
TRACKS = {
    "column": {"pitch": 23.0, "step": 20.0, "zstep": 20.0, "shape": (91, 405), "w0": 51.0,
            "centre": (1600.0, 1600.0), "z0": 1000.0, "prediction": False},
    # the same ratios at half the step on a narrower spiral, small enough for a whole sheet prediction volume
    "mini": {"pitch": 11.5, "step": 10.0, "zstep": 10.0, "shape": (31, 101), "w0": 12.0,
             "centre": (200.0, 200.0), "z0": 16.0, "prediction": True},
}

# Roughness levels: a background normal jitter on every vertex plus clustered rough spots with a large normal and
# in-plane displacement. Calibrated (seeds 0 to 2, column track) so the crease and spike shares of the quads match
# the calibration targets (creases: dihedral over 60 degrees to a neighbor quad, spikes: an edge over two grid
# steps); the achieved shares are written into every case's defects.json and checked by tests.
ROUGH = {
    "none": None,
    "light": {"model": "lighter roughness (creases and spikes near 8.5 %)", "target": {"crease": 0.085, "spike": 0.085},
              "sig_s": 0.0, "corr_along": 1.0, "corr_across": 15.0,
              "bg": 0.6, "spot": 0.012, "radius": 1.0, "amp_n": 5.0, "amp_t": 16.0},
    "cB": {"model": "column B (roughness part)", "target": {"crease": 0.126, "spike": 0.125},
             "sig_s": 0.0, "corr_along": 1.0, "corr_across": 15.0,
             "bg": 0.6, "spot": 0.010, "radius": 1.0, "amp_n": 5.0, "amp_t": 21.0},
    "cA": {"model": "column A", "target": {"crease": 0.121, "spike": 0.162},
             "sig_s": 0.0, "corr_along": 1.0, "corr_across": 15.0,
             "bg": 0.6, "spot": 0.020, "radius": 1.0, "amp_n": 5.0, "amp_t": 16.0},
    # matched instead on spikes and on what 5 Taubin passes did to the real columns (vertices moved 2.0 to 3.5
    # voxels at p95, and the half-pitch guard cut 0.32 % of cells); its creases stay near 1 %, far under the
    # columns' 12 %: no model tried here matched creases, spikes and the Taubin moves at once (see the tool page)
    "cAt": {"model": "column A, Taubin-matched", "target": {"spike": 0.162, "taubin_cut": 0.0032},
              "sig_s": 0.4, "corr_along": 1.0, "corr_across": 15.0,
              "bg": 1.0, "spot": 0.03, "radius": 0.0, "amp_n": 3.0, "amp_t": 9.0},
}

# Cases: (name, roughness, operations, the column or tool case it stands for, expected verdict of the case).
# Rows and columns are fractions of the grid so both tracks use the same layout.
CASES = [
    ("clean", "none", [], "control: no defect", "CORRECT"),
    ("rough-light", "light", [], "lighter tracer roughness", "CORRECT-ROUGH"),
    ("rough-a", "cA", [], "column A: diffuse tracer roughness (creases and spikes matched)", "CORRECT-ROUGH"),
    ("rough-a-taubin", "cAt", [], "column A: roughness matched on spikes and Taubin moves instead", "CORRECT-ROUGH"),
    ("band-b", "cB", [{"op": "band", "rows": (0.11, 0.35), "cols": (0.64, 0.80), "dk": 1, "ramp": 2},
                          {"op": "band", "rows": (0.55, 0.68), "cols": (0.20, 0.25), "dk": 1, "ramp": 1},
                          {"op": "band", "rows": (0.70, 0.80), "cols": (0.45, 0.49), "dk": 1, "ramp": 0}],
     "column B: one sheet-switch band (rows 10 to 30, cols 260 to 320) and two smaller ones on roughness",
     "INCORRECT"),
    ("band-only", "none", [{"op": "band", "rows": (0.11, 0.35), "cols": (0.64, 0.80), "dk": 1, "ramp": 2}],
     "column B's band alone, no roughness: isolates the switch for alarms", "INCORRECT"),
    ("switch-edge", "light", [{"op": "switch", "rows": (0.30, 0.70), "cols": (0.75, 1.0), "dk": 1}],
     "a hard switch that stays on the next winding to the grid's end", "INCORRECT"),
    ("skip", "light", [{"op": "band", "rows": (0.40, 0.60), "cols": (0.40, 0.52), "dk": 2, "ramp": 0}],
     "a lens two windings out (skip-wrap)", "INCORRECT"),
    ("merger", "light", [{"op": "merger", "cols": (0.60, 1.0), "dk": 1, "ramp": 6}],
     "the whole height slides onto the neighbor over 6 columns and stays (sheets fused)", "INCORRECT"),
    ("fold", "light", [{"op": "fold", "rows": (0.35, 0.65), "cols": (0.30, 0.38), "gain": 2.0}],
     "the mesh folds back over itself on its own sheet (a pleat)", "INCORRECT"),
    ("bridge", "light", [{"op": "bridge", "rows": (0.40, 0.60), "cols": (0.48, 0.56)}],
     "a hole filled by the flat chord over its corners: leaves the curved sheet", "INCORRECT"),
    ("gapbridge", "light", [{"op": "gapbridge", "rows": (0.0, 1.0), "cols": (0.55, 0.57), "dk": 1}],
     "a strip across the void between windings joining two windings: a switch with a plateau mid-gap",
     "INCORRECT"),
    ("hole", "light", [{"op": "hole", "rows": (0.40, 0.60), "cols": (0.40, 0.50)}],
     "a punched hole: the rest is correct (cutting is no error here)", "CORRECT-ROUGH"),
]
CASE_NAMES = [c[0] for c in CASES]


class BenchError(ValueError):
    pass


def _np():
    import numpy
    return numpy


def _ndi():
    try:
        from scipy import ndimage
    except ImportError as exc:  # pragma: no cover
        raise BenchError("kit defectbench needs scipy (pip install scipy)") from exc
    return ndimage


def sheets_for(track):
    t = TRACKS[track]
    return planted.Sheets("spiral", pitch=t["pitch"], step=t["step"], zstep=t["zstep"], z0=t["z0"], w0=t["w0"],
                          centre=t["centre"])


def _span(frac, n):
    a, b = frac
    lo, hi = int(round(a * n)), int(round(b * n))
    return max(0, min(lo, n - 1)), max(1, min(max(hi, lo + 1), n))


def footprint(shape, rng):
    """An irregular valid footprint: wavy top and bottom edges (about 8 % of the rows off at each side, as the real
    columns keep 77 % of their 91 x 405 cells; the bench keeps 75 to 91 %) and a ragged start and end."""
    np = _np()
    h, w = shape
    valid = np.ones(shape, bool)
    for side in (0, 1):
        walk = np.cumsum(rng.normal(0, 0.6, w))
        walk = walk - np.linspace(walk[0], walk[-1], w)
        edge = np.clip(np.round(h * 0.08 + walk), 0, h // 3).astype(int)
        for c in range(w):
            if side == 0:
                valid[:edge[c], c] = False
            else:
                valid[h - edge[c]:, c] = False
    for side in (0, 1):
        cut = np.clip(np.round(np.abs(np.cumsum(rng.normal(0, 0.5, h))) + 1), 0, w // 20).astype(int)
        for r in range(h):
            if side == 0:
                valid[r, :cut[r]] = False
            else:
                valid[r, w - cut[r]:] = False
    return valid


def frames(sheets, shape):
    """Unit normal (radial), along-row and along-column directions of the base surface at every grid site."""
    np = _np()
    h, w = shape
    rr, cc = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    th = sheets.theta(cc)
    n = np.stack([np.cos(th), np.sin(th), np.zeros_like(th)], -1)
    t = np.stack([-np.sin(th), np.cos(th), np.zeros_like(th)], -1)
    z = np.zeros_like(n)
    z[..., 2] = 1.0
    return n, t, z


def _spacing_shift(shape, axis, p, rng):
    """In-plane grid irregularity along one axis, in grid units: log-normal edge spacings from a field smoothed
    little along the axis and much across it (neighboring lines stretch alike, so they do not shear), summed into
    positions and registered at the middle of every line, as a tracer's uneven step leaves them."""
    np = _np()
    ndi = _ndi()
    sig = (p["corr_across"], p["corr_along"]) if axis == 1 else (p["corr_along"], p["corr_across"])
    f = ndi.gaussian_filter(rng.normal(0, 1, shape), sig)
    f /= max(float(f.std()), 1e-9)
    s = np.exp(p["sig_s"] * f)
    s /= s.mean()
    pos = np.cumsum(s, axis=axis) - s
    n = shape[axis]
    idx = np.arange(n).reshape((1, n) if axis == 1 else (n, 1))
    d = pos - idx
    mid = d.take([n // 2], axis=axis)
    return d - mid


def roughen(valid, sheets, level, rng):
    """A roughness level as (drow, dcol, dn): in-plane grid irregularity along the sheet itself (in grid rows and
    columns: never off the sheet, and not an error, since the true position follows it) and a normal offset (a
    background jitter on every vertex plus clustered rough spots), capped so a rough vertex stays within a quarter
    pitch of its sheet. Uneven spacing makes the long edges (spikes); normal jitter on short edges the creases."""
    np = _np()
    ndi = _ndi()
    p = ROUGH[level]
    zero = np.zeros(valid.shape)
    if p is None:
        return zero, zero.copy(), zero.copy()
    scale = sheets.step / 20.0                  # amplitudes are stated for the 20 voxel column step
    dcol = _spacing_shift(valid.shape, 1, p, rng) if p["sig_s"] > 0 else zero.copy()
    drow = _spacing_shift(valid.shape, 0, p, rng) if p["sig_s"] > 0 else zero.copy()
    dn = rng.normal(0, p["bg"] * scale, valid.shape)
    seeds = rng.random(valid.shape) < p["spot"]
    spots = ndi.binary_dilation(seeds, iterations=int(p["radius"])) if p["radius"] >= 1 else seeds
    ns = int(spots.sum())
    dn[spots] += rng.normal(0, p["amp_n"] * scale, ns)
    # rough spots also move in plane (along the sheet), which folds a quad over in plane: the creases
    dcol[spots] += rng.normal(0, p["amp_t"] * scale, ns) / sheets.step
    drow[spots] += rng.normal(0, p["amp_t"] * scale, ns) / sheets.zstep
    cap = ROUGH_CAP * sheets.pitch
    dn = np.clip(dn, -cap, cap)
    for arr in (dn, drow, dcol):
        arr[~valid] = 0.0
    return drow, dcol, dn


def _band_mask(shape, rows, cols, rng):
    """A blobby region inside the ellipse of the site, its edge roughened by a smoothed random field."""
    np = _np()
    ndi = _ndi()
    h, w = shape
    r0, r1 = _span(rows, h)
    c0, c1 = _span(cols, w)
    rr, cc = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    cy, cx = (r0 + r1 - 1) / 2.0, (c0 + c1 - 1) / 2.0
    ry, rx = max((r1 - r0) / 2.0, 1.0), max((c1 - c0) / 2.0, 1.0)
    e = ((rr - cy) / ry) ** 2 + ((cc - cx) / rx) ** 2
    noise = ndi.gaussian_filter(rng.normal(0, 1, shape), 2.0)
    noise /= max(float(noise.std()), 1e-9)
    return e + 0.25 * noise < 1.0, [r0, r1, c0, c1]


def apply_ops(base_k, valid, sheets, ops, rng):
    """The planted winding offset k, the per-site angle change (folds) and the op records."""
    np = _np()
    ndi = _ndi()
    h, w = valid.shape
    k = base_k.copy()
    dcol = np.zeros(valid.shape)               # fold: shift of the column coordinate (in grid columns)
    hole = np.zeros(valid.shape, bool)
    chord = []
    recs = []
    cc = np.broadcast_to(np.arange(w)[None, :], (h, w))
    for op in ops:
        kind = op["op"]
        rec = {"op": kind}
        if kind == "band":
            m, box = _band_mask(valid.shape, op["rows"], op["cols"], rng)
            ramp = int(op.get("ramp", 0))
            if ramp > 0:
                d = ndi.distance_transform_edt(m)
                prof = np.clip(d / (ramp + 1.0), 0.0, 1.0)
                prof = prof * prof * (3 - 2 * prof)
            else:
                prof = m.astype(float)
            k = k + op["dk"] * prof
            rec.update(box=box, dk=op["dk"], ramp=ramp, cells=int((m & valid).sum()))
        elif kind == "switch":
            r0, r1 = _span(op["rows"], h)
            c0, c1 = _span(op["cols"], w)
            k[r0:r1, c0:c1] += op["dk"]
            rec.update(box=[r0, r1, c0, c1], dk=op["dk"])
        elif kind == "merger":
            c0, c1 = _span(op["cols"], w)
            ramp = int(op["ramp"])
            t = np.clip((np.arange(w) - c0 + 1) / (ramp + 1.0), 0.0, 1.0)
            t[:c0] = 0.0
            k = k + op["dk"] * (t * t * (3 - 2 * t))[None, :]
            rec.update(box=[0, h, c0, c1], dk=op["dk"], ramp=ramp)
        elif kind == "gapbridge":
            r0, r1 = _span(op["rows"], h)
            c0, c1 = _span(op["cols"], w)
            k[r0:r1, c0:c1] += 0.5 * op["dk"]           # the plateau sits in the void between the two windings
            k[r0:r1, c1:] += op["dk"]
            rec.update(box=[r0, r1, c0, c1], dk=op["dk"])
        elif kind == "fold":
            r0, r1 = _span(op["rows"], h)
            c0, c1 = _span(op["cols"], w)
            L = c1 - c0
            g = float(op["gain"])
            tt = np.clip((np.arange(w) - c0) / float(L), 0.0, 1.0)
            # u(c) = c - g L sin(2 pi t) / (2 pi): du/dc = 1 - g cos(2 pi t) runs backward where cos(2 pi t) > 1/g
            shift = -g * L * np.sin(2 * np.pi * tt) / (2 * np.pi)
            rows = np.arange(h)
            taper = np.clip(np.minimum(rows - r0 + 1, r1 - rows) / 3.0, 0.0, 1.0)
            dcol = dcol + taper[:, None] * shift[None, :]
            rec.update(box=[r0, r1, c0, c1], gain=g)
        elif kind == "hole":
            r0, r1 = _span(op["rows"], h)
            c0, c1 = _span(op["cols"], w)
            hole[r0:r1, c0:c1] = True
            rec.update(box=[r0, r1, c0, c1])
        elif kind == "bridge":
            r0, r1 = _span(op["rows"], h)
            c0, c1 = _span(op["cols"], w)
            chord.append((r0, r1, c0, c1))
            rec.update(box=[r0, r1, c0, c1])
        else:
            raise BenchError(f"unknown op {kind!r}")
        recs.append(rec)
    return k, dcol, hole, chord, recs


def build(track, case, seed):
    """One bench case: (arrays, record)."""
    np = _np()
    spec = {c[0]: c for c in CASES}
    if case not in spec:
        raise BenchError(f"unknown case {case!r}; cases: {CASE_NAMES}")
    name, level, ops, model, expected = spec[case]
    t = TRACKS[track]
    sheets = sheets_for(track)
    h, w = t["shape"]
    digest = hashlib.sha256(f"{SCHEMA}|{track}|{case}|{seed}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
    foot_rng = np.random.default_rng(int(seed) * 7919 + (0 if track == "column" else 1))  # same footprint per seed
    valid = footprint((h, w), foot_rng)
    rr, cc = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    ref = sheets.point(np.zeros((h, w)), rr, cc)
    k, dcol, hole, chord, recs = apply_ops(np.zeros((h, w)), valid, sheets, ops, rng)
    folded = np.zeros((h, w), bool)
    back = np.zeros((h, w), bool)
    if np.any(dcol):
        u = cc + dcol
        back[:, :-1] = np.diff(u, axis=1) < 0
        back[:, 1:] |= np.diff(u, axis=1) < 0
        # every vertex whose column coordinate is covered more than once in its row is in the fold
        for r in range(h):
            if not np.any(dcol[r]):
                continue
            ur = u[r]
            lo = np.minimum(ur[:-1], ur[1:])
            hi = np.maximum(ur[:-1], ur[1:])
            for c in range(w):
                folded[r, c] = int(((lo <= ur[c]) & (ur[c] <= hi)).sum()) > 2
        folded |= back
        ref = sheets.point(np.zeros((h, w)), rr, cc + dcol)  # a fold's true position is where its vertex lies
    drow_r, dcol_r, dn = roughen(valid, sheets, level, rng)
    # in-plane irregularity keeps a vertex on its sheet, so its true position follows it
    ref = sheets.point(np.zeros((h, w)), rr + drow_r, cc + dcol + dcol_r)
    # a fold's layers get a small normal offset so they never coincide
    dn = dn + np.where(back, 0.5 * t["step"] / 20.0, 0.0)
    cpar = cc + dcol + dcol_r
    xyz = sheets.point(k, rr + drow_r, cpar)
    th = sheets.theta(cpar)
    xyz = xyz + np.stack([np.cos(th), np.sin(th), np.zeros_like(th)], -1) * dn[..., None]
    for (r0, r1, c0, c1) in chord:
        if r0 == 0 or c0 == 0 or r1 >= h or c1 >= w:
            raise BenchError("a bridge needs a border on all four sides")
        A, B, C, D = xyz[r0 - 1, c0 - 1].copy(), xyz[r0 - 1, c1].copy(), xyz[r1, c0 - 1].copy(), xyz[r1, c1].copy()
        nr, nc = r1 - r0 + 1, c1 - c0 + 1
        for i in range(r0, r1):
            for j in range(c0, c1):
                uu, vv = (j - c0 + 1) / nc, (i - r0 + 1) / nr
                xyz[i, j] = (1 - uu) * (1 - vv) * A + uu * (1 - vv) * B + (1 - uu) * vv * C + uu * vv * D
    valid = valid & ~hole
    # the truth is computed from the float32 values the tifxyz and truth.npz store, so check sees the same numbers
    xyz = xyz.astype(np.float32).astype(float)
    ref = ref.astype(np.float32).astype(float)
    arrays = {"xyz": xyz, "valid": valid, "ref": ref, "folded": folded}
    lab, kk = labels(sheets, arrays)
    arrays.update(label=lab, k=kk, disp=np.where(valid[..., None], xyz - ref, 0.0))
    rec = {"schema": SCHEMA, "synthetic": True, "track": track, "case": case, "seed": int(seed), "roughness": level,
           "rough_params": ROUGH[level], "model_of": model, "expected": expected, "ops": recs,
           "sheets": sheets.params(), "shape": [h, w]}
    rec["truth"] = summary(arrays)
    rec["mesh"] = mesh_stats(xyz, valid, t["step"])
    moved = np.linalg.norm(taubin(xyz, valid) - xyz, axis=-1)[valid]
    rec["mesh"]["taubin5g"] = {"cut_share": round(float((moved > sheets.pitch / 2.0).mean()), 5),
                               "move_p50": round(float(np.percentile(moved, 50)), 3),
                               "move_p95": round(float(np.percentile(moved, 95)), 3)}
    return arrays, rec


def labels(sheets, arrays):
    """Per-vertex label and measured winding offset from coordinates, fold marks and true positions only."""
    np = _np()
    xyz, valid, ref, folded = arrays["xyz"], arrays["valid"], arrays["ref"], arrays["folded"]
    h, w = valid.shape
    cols = np.broadcast_to(np.arange(w)[None, :], (h, w))
    safe = np.where(valid[..., None], xyz, ref)
    k = sheets.measure(safe, cols)
    dist = sheets.distance(safe)
    err = np.linalg.norm(safe - ref, axis=-1)
    lab = np.zeros((h, w), np.int8)
    lab[valid & (err > ROUGH_TOL)] = 1
    lab[valid & folded] = 4
    lab[valid & (dist > GAP_TOL * sheets.pitch) & (np.abs(k) < 0.5)] = 3
    lab[valid & (np.abs(k) >= 0.5)] = 2
    lab[~valid] = -1
    return lab, np.where(valid, k, np.nan)


def summary(arrays):
    np = _np()
    ndi = _ndi()
    lab = arrays["label"]
    nv = int((lab >= 0).sum())
    out = {"vertices": nv, "invalid": int((lab < 0).sum())}
    for code, name in LABELS.items():
        if code >= 0:
            out[name] = int((lab == code).sum())
    sw = np.isin(lab, SWITCH_LIKE)
    regs, n = ndi.label(sw, structure=np.ones((3, 3)))
    out["switch_regions"] = int(n)
    out["switch_region_sizes"] = sorted((int(s) for s in np.bincount(regs.ravel())[1:]), reverse=True)[:8]
    k = arrays["k"]
    v = lab >= 0
    eh = v[:, 1:] & v[:, :-1] & (np.abs(np.nan_to_num(k[:, 1:] - k[:, :-1])) >= 0.5)
    ev = v[1:, :] & v[:-1, :] & (np.abs(np.nan_to_num(k[1:, :] - k[:-1, :])) >= 0.5)
    out["jump_edges"] = int(eh.sum() + ev.sum())
    out["defect_share"] = round(float(np.isin(lab, DEFECT).sum()) / nv, 6) if nv else None
    return out


def quad_masks(xyz, valid, step):
    """Per quad: valid, edge spike (an edge over two grid steps), crease (over 60 degrees to a neighbor quad) and
    local flip (normal against the 9 x 9 mean normal); the same definitions were used to measure the calibration
    columns, so bench and columns are measured alike."""
    np = _np()
    ndi = _ndi()
    q = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & valid[1:, 1:]
    p00, p01, p10, p11 = xyz[:-1, :-1], xyz[:-1, 1:], xyz[1:, :-1], xyz[1:, 1:]
    e = np.stack([np.linalg.norm(p01 - p00, axis=-1), np.linalg.norm(p11 - p10, axis=-1),
                  np.linalg.norm(p10 - p00, axis=-1), np.linalg.norm(p11 - p01, axis=-1)], -1)
    spike = q & (e.max(-1) > 2.0 * step)
    n = np.cross(p11 - p00, p10 - p01)
    n = n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-9)
    n[~q] = 0
    mean = np.stack([ndi.uniform_filter(n[..., i], 9) for i in range(3)], -1)
    flip = q & (np.einsum("ijk,ijk->ij", n, mean) < 0)
    crease = np.zeros_like(q)
    for sa, sb in (((slice(None), slice(None, -1)), (slice(None), slice(1, None))),
                   ((slice(None, -1), slice(None)), (slice(1, None), slice(None)))):
        ok = q[sa] & q[sb]
        bad = ok & (np.einsum("ijk,ijk->ij", n[sa], n[sb]) < math.cos(math.radians(60)))
        crease[sa] |= bad
        crease[sb] |= bad
    return q, {"spike": spike, "crease": crease, "flip": flip}


def mesh_stats(xyz, valid, step):
    """Area shares of spike, crease and flip quads (3D quad area weights, as diag.py's area_share)."""
    np = _np()
    q, m = quad_masks(xyz, valid, step)
    p00, p01, p10, p11 = xyz[:-1, :-1], xyz[:-1, 1:], xyz[1:, :-1], xyz[1:, 1:]
    area = 0.5 * (np.linalg.norm(np.cross(p01 - p00, p10 - p00), axis=-1)
                  + np.linalg.norm(np.cross(p01 - p11, p10 - p11), axis=-1))
    tot = float(area[q].sum())
    out = {"quads": int(q.sum())}
    for name, mk in m.items():
        out[name + "_area_share"] = round(float(area[mk].sum()) / tot, 4) if tot else None
    return out


# ---------------------------------------------------------------------------------------------------- files

def _write_grid(path, arr):
    import tifffile
    tifffile.imwrite(str(path), _np().asarray(arr, _np().float32), compression="zlib")   # deflate, lossless


def _read_grid(path):
    import tifffile
    return _np().asarray(tifffile.imread(str(path)), float)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def write_tifxyz(out, xyz, valid, uuid, source):
    np = _np()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate("xyz"):
        _write_grid(out / f"{c}.tif", np.where(valid, xyz[..., i], -1.0))
    pts = xyz[valid]
    meta = {"format": "tifxyz", "type": "seg", "uuid": uuid, "scale": [0.05, 0.05],
            "bbox": [pts.min(0).tolist(), pts.max(0).tolist()] if len(pts) else None, "source": source}
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return out


def read_tifxyz(path):
    np = _np()
    path = Path(path)
    xyz = np.stack([_read_grid(path / f"{c}.tif") for c in "xyz"], -1)
    valid = ~(xyz == -1).all(-1) & np.isfinite(xyz).all(-1)
    return xyz, valid


def write_case(root, arrays, rec):
    np = _np()
    out = Path(root) / rec["track"] / f"{rec['case']}-s{rec['seed']}"
    if out.exists() and any(out.iterdir()):
        raise BenchError(f"{out} exists and is not empty")
    scale = 1.0 / TRACKS[rec["track"]]["step"]
    write_tifxyz(out, arrays["xyz"], arrays["valid"], out.name, "kit defectbench (synthetic)")
    meta = json.loads((out / "meta.json").read_text())
    meta["scale"] = [scale, scale]
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    np.savez_compressed(out / "truth.npz", label=arrays["label"], k=arrays["k"].astype(np.float32),
                        ref=arrays["ref"].astype(np.float32), disp=arrays["disp"].astype(np.float32),
                        folded=arrays["folded"])
    if TRACKS[rec["track"]]["prediction"]:
        write_prediction(out / "pred.zarr", sheets_for(rec["track"]), arrays["xyz"], arrays["valid"])
        t = TRACKS[rec["track"]]
        z0, z1 = t["z0"] - 40, t["z0"] + t["zstep"] * t["shape"][0] + 40
        umb = [[t["centre"][0], t["centre"][1], z] for z in (z0, z1)]
        (out / "umbilicus.json").write_text(json.dumps({"points_xyz": umb, "note": "the spiral's center line"}) + "\n")
    files = sorted(p for p in out.iterdir() if p.is_file())
    rec["files"] = {p.name: _sha(p) for p in files}
    (out / "defects.json").write_text(json.dumps(rec, indent=1, allow_nan=False) + "\n")
    return out


def write_prediction(path, sheets, xyz, valid, chunk=64, margin=3.0, thickness=None):
    """A binary sheet prediction (uint8, 255 on a sheet; zarr v2 OME-Zarr level 0, zlib chunks) of the same
    spiral, on the windings within `margin` pitches of the surface's radial range, chunk by chunk."""
    np = _np()
    import zarr
    thickness = sheets.pitch * 0.35 if thickness is None else float(thickness)
    pts = xyz[valid]
    rad = np.hypot(pts[:, 0] - sheets.centre[0], pts[:, 1] - sheets.centre[1])
    rmin, rmax = rad.min() - margin * sheets.pitch, rad.max() + margin * sheets.pitch
    lo = np.floor(np.array([pts[:, 2].min() - 2 * sheets.pitch, sheets.centre[1] - rmax, sheets.centre[0] - rmax]))
    hi = np.ceil(np.array([pts[:, 2].max() + 2 * sheets.pitch, sheets.centre[1] + rmax, sheets.centre[0] + rmax]))
    lo = np.maximum(lo, 0).astype(int)
    shape = tuple(int(v) for v in hi + 1)
    g = zarr.open_group(str(path), mode="w", zarr_format=2)
    import numcodecs
    # zlib: kit.vc3d_region reads it with the standard library alone (vc3d_audit._decompress)
    arr = g.create_array("0", shape=shape, chunks=(chunk,) * 3, dtype="uint8", fill_value=0,
                         compressors=numcodecs.Zlib(level=1))
    for cz in range(lo[0] // chunk, -(-shape[0] // chunk)):
        for cy in range(lo[1] // chunk, -(-shape[1] // chunk)):
            for cx in range(lo[2] // chunk, -(-shape[2] // chunk)):
                o = (cz * chunk, cy * chunk, cx * chunk)
                n = tuple(min(chunk, s - a) for s, a in zip(shape, o))
                zz, yy, xx = np.meshgrid(*(np.arange(m, dtype=float) + a for m, a in zip(n, o)), indexing="ij")
                r = np.hypot(xx - sheets.centre[0], yy - sheets.centre[1])
                if r.max() < rmin or r.min() > rmax:
                    continue
                f = sheets._f(np.stack([xx, yy, zz], -1))
                on = (sheets.pitch * np.abs(f - np.round(f)) <= thickness / 2.0) & (r >= rmin) & (r <= rmax)
                if on.any():
                    arr[o[0]:o[0] + n[0], o[1]:o[1] + n[1], o[2]:o[2] + n[2]] = np.where(on, 255, 0).astype(np.uint8)
    g.attrs["multiscales"] = [{"version": "0.4", "name": "kit-defectbench-prediction",
                               "axes": [{"name": a, "type": "space"} for a in "zyx"],
                               "datasets": [{"path": "0", "coordinateTransformations": [
                                   {"type": "scale", "scale": [1.0, 1.0, 1.0]}]}]}]
    return path


def make(out, tracks=("column", "mini"), seeds=3, only=None):
    out = Path(out)
    cases = only or CASE_NAMES
    manifest = {"schema": SCHEMA, "synthetic": True, "tracks": {}, "cases": []}
    for tr in tracks:
        manifest["tracks"][tr] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in TRACKS[tr].items()}
        for s in range(int(seeds)):
            for c in cases:
                arrays, rec = build(tr, c, s)
                d = write_case(out, arrays, rec)
                manifest["cases"].append({"track": tr, "case": c, "seed": s, "dir": str(d.relative_to(out)),
                                          "expected": rec["expected"], "truth": rec["truth"], "mesh": rec["mesh"],
                                          "defects_json": _sha(d / "defects.json")})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, allow_nan=False) + "\n")
    return manifest


def load_case(d):
    np = _np()
    d = Path(d)
    rec = json.loads((d / "defects.json").read_text())
    if rec.get("schema") != SCHEMA:
        raise BenchError(f"{d}: schema {rec.get('schema')!r} is not {SCHEMA}")
    t = np.load(d / "truth.npz")
    xyz, valid = read_tifxyz(d)
    return xyz, valid, {k: t[k] for k in t.files}, rec


def check(root):
    """Disagreements between every case's files and what its coordinates say; empty means the bench agrees."""
    np = _np()
    root = Path(root)
    man = json.loads((root / "manifest.json").read_text())
    bad = []
    for ent in man["cases"]:
        d = root / ent["dir"]
        xyz, valid, t, rec = load_case(d)
        for name, sha in rec["files"].items():
            if _sha(d / name) != sha:
                bad.append(f"{ent['dir']}: {name} changed since make")
        if _sha(d / "defects.json") != ent["defects_json"]:
            bad.append(f"{ent['dir']}: defects.json differs from the manifest")
        if (valid != (t["label"] >= 0)).any():
            bad.append(f"{ent['dir']}: valid vertices differ from truth.npz")
            continue
        sheets = planted.Sheets.from_params(rec["sheets"])
        arrays = {"xyz": xyz, "valid": valid, "ref": t["ref"].astype(float), "folded": t["folded"]}
        lab, k = labels(sheets, arrays)
        if (lab != t["label"]).any():
            bad.append(f"{ent['dir']}: {int((lab != t['label']).sum())} labels differ from the coordinates")
        arrays.update(label=lab, k=k)
        now = summary(arrays)
        for key, val in now.items():
            if rec["truth"].get(key) != val:
                bad.append(f"{ent['dir']}: truth {key} is {val} from the coordinates, defects.json says "
                           f"{rec['truth'].get(key)}")
        if rec["expected"] == "CORRECT" and now["defect_share"]:
            bad.append(f"{ent['dir']}: a CORRECT case carries defects")
        if rec["expected"] == "INCORRECT" and not (now["wrong"] + now["gap"] + now["fold"]):
            bad.append(f"{ent['dir']}: an INCORRECT case has no wrong, gap or fold vertex (the plant did nothing)")
        if rec["expected"] == "CORRECT-ROUGH" and (now["wrong"] + now["gap"] + now["fold"]):
            bad.append(f"{ent['dir']}: a CORRECT-ROUGH case has wrong, gap or fold vertices")
    return bad


# ---------------------------------------------------------------------------------------------------- baselines

def taubin(P, valid, passes=5, lam=0.5, mu=-0.53):
    """Taubin smoothing of the four-neighbor umbrella on interior vertices (5 passes of lambda 0.5 and mu -0.53),
    a common first mesh-fix recipe, kept as a reference repair."""
    np = _np()
    P = np.array(P, float)
    v = valid
    inner = np.zeros_like(v)
    inner[1:-1, 1:-1] = v[1:-1, 1:-1] & v[:-2, 1:-1] & v[2:, 1:-1] & v[1:-1, :-2] & v[1:-1, 2:]
    for _ in range(passes):
        for f in (lam, mu):
            avg = np.zeros_like(P)
            avg[1:-1, 1:-1] = (P[:-2, 1:-1] + P[2:, 1:-1] + P[1:-1, :-2] + P[1:-1, 2:]) / 4.0
            P = np.where(inner[..., None], P + f * (avg - P), P)
    return P


def alarm_baseline(kind, xyz, valid, t, rec, case_dir=None):
    """A per-vertex switch alarm: none and all (controls that must score badly on recall and on false alarms),
    oracle (the truth: must score perfectly) and wjump (geometry only: a vertex whose winding coordinate about the
    known center rounds to another whole winding than a grid neighbor's: every part the largest part cannot reach
    without such an edge, plus the gap vertices next to it; a winding-jump audit, with the true center
    and pitch given, so it is a reference that knows more than any real alarm, not a fair competitor)."""
    np = _np()
    ndi = _ndi()
    if kind == "none":
        return np.zeros(valid.shape, bool)
    if kind == "all":
        return valid.copy()
    if kind == "oracle":
        return np.isin(t["label"], SWITCH_LIKE)
    if kind != "wjump":
        raise BenchError(f"unknown alarm baseline {kind!r}")
    sheets = planted.Sheets.from_params(rec["sheets"])
    h, w = valid.shape
    cols = np.broadcast_to(np.arange(w)[None, :], (h, w))
    f = np.where(valid, sheets.measure(np.where(valid[..., None], xyz, 0.0), cols), np.nan)
    g = np.round(f)                                    # whole windings: a rough vertex (under 0.3 pitch) never flips
    same_h = valid[:, 1:] & valid[:, :-1] & (np.abs(np.nan_to_num(g[:, 1:] - g[:, :-1])) < 0.5)
    same_v = valid[1:, :] & valid[:-1, :] & (np.abs(np.nan_to_num(g[1:, :] - g[:-1, :])) < 0.5)
    # 4-connected parts joined only across edges that do not jump, by union-find
    idx = np.arange(h * w).reshape(h, w)
    parent = np.arange(h * w)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for (ok, a, b) in ((same_h, idx[:, :-1], idx[:, 1:]), (same_v, idx[:-1, :], idx[1:, :])):
        for x, y in zip(a[ok], b[ok]):
            rx, ry = find(int(x)), find(int(y))
            if rx != ry:
                parent[rx] = ry
    roots = np.array([find(int(i)) for i in range(h * w)]).reshape(h, w)
    roots = np.where(valid, roots, -1)
    vals, counts = np.unique(roots[valid], return_counts=True)
    main = vals[np.argmax(counts)]
    flag = valid & (roots != main)
    off = valid & (sheets.distance(np.where(valid[..., None], xyz, 0.0)) > GAP_TOL * sheets.pitch)
    return flag | (off & ndi.binary_dilation(flag, iterations=1))


def repair_baseline(kind, xyz, valid, t, rec):
    """A repaired mesh on the same grid: identity (must keep every defect), oracle (true positions, defects
    removed: must score perfectly) and taubin5g (5 Taubin passes, vertices moved over half a pitch cut; a
    reference for a mesh-fix step)."""
    np = _np()
    sheets = planted.Sheets.from_params(rec["sheets"])
    if kind == "identity":
        return xyz.copy(), valid.copy()
    if kind == "oracle":
        keep = valid & np.isin(t["label"], (0, 1))
        return np.where(keep[..., None], t["ref"].astype(float), xyz), keep
    if kind == "taubin5g":
        P = taubin(xyz, valid)
        moved = np.linalg.norm(P - xyz, axis=-1)
        keep = valid & (moved <= sheets.pitch / 2.0)
        return P, keep
    raise BenchError(f"unknown repair baseline {kind!r}")


def _cases(root, track=None):
    root = Path(root)
    man = json.loads((root / "manifest.json").read_text())
    return [e for e in man["cases"] if track in (None, e["track"])], root


def baseline(root, out, alarm=None, repair=None, track=None):
    np = _np()
    ents, root = _cases(root, track)
    out = Path(out)
    for e in ents:
        xyz, valid, t, rec = load_case(root / e["dir"])
        name = Path(e["dir"]).name
        (out / e["track"]).mkdir(parents=True, exist_ok=True)
        if alarm:
            np.save(out / e["track"] / f"{name}.npy", alarm_baseline(alarm, xyz, valid, t, rec, root / e["dir"]))
        else:
            P, keep = repair_baseline(repair, xyz, valid, t, rec)
            write_tifxyz(out / e["track"] / name, P, keep, name, f"kit defectbench baseline {repair}")
    return out


# ---------------------------------------------------------------------------------------------------- scoring

def score_alarm(flags, t):
    """Cell recall on switch-like vertices, false alarms on clean and on rough vertices, region hits."""
    np = _np()
    ndi = _ndi()
    lab = t["label"]
    flags = np.asarray(flags, bool) & (lab >= 0)
    tgt = np.isin(lab, SWITCH_LIKE)
    clean, rough = lab == 0, lab == 1
    regs, n = ndi.label(tgt, structure=np.ones((3, 3)))
    hit = cover = 0
    for i in range(1, n + 1):
        m = regs == i
        if (flags & ndi.binary_dilation(m, iterations=1)).any():
            hit += 1
        if (flags & m).sum() >= 0.5 * m.sum():
            cover += 1
    return {"targets": int(tgt.sum()), "flagged": int(flags.sum()),
            "recall": round(float((flags & tgt).sum()) / tgt.sum(), 4) if tgt.any() else None,
            "false_alarm_clean": round(float((flags & clean).sum()) / clean.sum(), 4) if clean.any() else None,
            "false_alarm_rough": round(float((flags & rough).sum()) / rough.sum(), 4) if rough.any() else None,
            "regions": int(n), "regions_hit": hit, "regions_half_covered": cover}


def score_repair(xyz2, valid2, t, rec):
    """What a repaired mesh (same grid) kept and how far it left each kept vertex from its true sheet."""
    np = _np()
    sheets = planted.Sheets.from_params(rec["sheets"])
    lab = t["label"]
    v0 = lab >= 0
    keep = valid2 & v0
    h, w = lab.shape
    cols = np.broadcast_to(np.arange(w)[None, :], (h, w))
    k = np.where(keep, sheets.measure(np.where(keep[..., None], xyz2, 0.0), cols), np.nan)
    wrong = keep & (np.abs(np.nan_to_num(k)) >= 0.5)
    sheet_err = np.where(keep, sheets.pitch * np.abs(np.nan_to_num(k)), np.nan)
    pos_err = np.where(keep, np.linalg.norm(xyz2 - t["ref"], axis=-1), np.nan)
    good = np.isin(lab, (0, 1))
    step = TRACKS[rec["track"]]["step"]
    off = keep & ~wrong & (np.nan_to_num(sheet_err) > GAP_TOL * sheets.pitch)
    # a fold kept on the grid still runs backward: kept row edges whose angle about the center decreases
    th = np.arctan2(xyz2[..., 1] - sheets.centre[1], xyz2[..., 0] - sheets.centre[0])
    dth = np.angle(np.exp(1j * (th[:, 1:] - th[:, :-1]))) * sheets.hand
    backward = keep[:, 1:] & keep[:, :-1] & (dth < 0)
    out = {"kept_share": round(float(keep.sum()) / v0.sum(), 4),
           "good_kept_share": round(float((keep & good).sum()) / good.sum(), 4) if good.any() else None,
           "defect_cut_share": None,
           "wrong_kept": int(wrong.sum()), "off_kept": int(off.sum()), "fold_kept": int((keep & (lab == 4)).sum()),
           "backward_edges": int(backward.sum()),
           "sheet_err_p50": None, "sheet_err_p95": None, "pos_err_p95": None,
           "valid_outside_input": int((valid2 & ~v0).sum())}
    bad = np.isin(lab, (2, 3, 4))
    if bad.any():
        out["defect_cut_share"] = round(float((bad & ~keep).sum()) / bad.sum(), 4)
    if keep.any():
        se = sheet_err[keep & ~wrong]
        out["sheet_err_p50"] = round(float(np.percentile(se, 50)), 3) if se.size else None
        out["sheet_err_p95"] = round(float(np.percentile(se, 95)), 3) if se.size else None
        out["pos_err_p95"] = round(float(np.percentile(pos_err[keep & good], 95)), 3) if (keep & good).any() else None
    out["mesh"] = mesh_stats(xyz2, valid2, step)
    return out


def score(root, alarms=None, repaired=None, track=None):
    np = _np()
    ents, root = _cases(root, track)
    rows = []
    for e in ents:
        d = root / e["dir"]
        xyz, valid, t, rec = load_case(d)
        name = Path(e["dir"]).name
        row = {"track": e["track"], "case": e["case"], "seed": e["seed"], "expected": e["expected"]}
        if alarms:
            p = Path(alarms) / e["track"] / f"{name}.npy"
            if not p.is_file():
                row["missing"] = str(p)
            else:
                fl = np.load(p)
                if fl.shape != valid.shape:
                    raise BenchError(f"{p}: shape {fl.shape} is not the case's grid {valid.shape}")
                row.update(score_alarm(fl, t))
        else:
            p = Path(repaired) / e["track"] / name
            if not (p / "x.tif").is_file():
                row["missing"] = str(p)
            else:
                xyz2, valid2 = read_tifxyz(p)
                if valid2.shape != valid.shape:
                    raise BenchError(f"{p}: grid {valid2.shape} is not the case's grid {valid.shape}; a repair "
                                     "must keep the input grid (cut vertices are -1)")
                row.update(score_repair(xyz2, valid2, t, rec))
        rows.append(row)
    return {"schema": SCHEMA + "/score", "kind": "alarms" if alarms else "repair", "rows": rows,
            "families": aggregate(rows)}


def aggregate(rows):
    np = _np()
    fam = {}
    for r in rows:
        if "missing" in r:
            continue
        fam.setdefault((r["track"], r["case"]), []).append(r)
    out = {}
    for (tr, c), rs in sorted(fam.items()):
        agg = {"n": len(rs)}
        for key in ("recall", "false_alarm_clean", "false_alarm_rough", "kept_share", "good_kept_share",
                    "defect_cut_share", "wrong_kept", "off_kept", "fold_kept", "backward_edges", "sheet_err_p95", "pos_err_p95"):
            vals = [r[key] for r in rs if r.get(key) is not None]
            if vals:
                agg[key] = round(float(np.mean(vals)), 4)
        if rs and "regions" in rs[0]:
            agg["regions_hit"] = f"{sum(r['regions_hit'] for r in rs)}/{sum(r['regions'] for r in rs)}"
        out[f"{tr}/{c}"] = agg
    return out


# ---------------------------------------------------------------------------------------------------- command line

def build_parser(p):
    sub = p.add_subparsers(dest="cmd", required=True)
    js = "print JSON"
    c = sub.add_parser("cases", help="the bench's cases")
    c.add_argument("--json", action="store_true", help=js)
    m = sub.add_parser("make", help="write the bench")
    m.add_argument("out")
    m.add_argument("--track", default="both", choices=("column", "mini", "both"))
    m.add_argument("--seeds", type=int, default=3)
    m.add_argument("--only", nargs="+", choices=CASE_NAMES)
    m.add_argument("--json", action="store_true", help=js)
    k = sub.add_parser("check", help="recompute the truth of every case")
    k.add_argument("out")
    k.add_argument("--json", action="store_true", help=js)
    b = sub.add_parser("baseline", help="write a control or reference baseline")
    b.add_argument("out")
    g = b.add_mutually_exclusive_group(required=True)
    g.add_argument("--alarm", choices=("none", "all", "oracle", "wjump"))
    g.add_argument("--repair", choices=("identity", "oracle", "taubin5g"))
    b.add_argument("--dir", required=True)
    b.add_argument("--track", choices=tuple(TRACKS))
    s = sub.add_parser("score", help="score alarms or repaired meshes")
    s.add_argument("out")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--alarms")
    g.add_argument("--repaired")
    s.add_argument("--track", choices=tuple(TRACKS))
    s.add_argument("--out-file", dest="out_file")
    s.add_argument("--json", action="store_true", help=js)
    return p


def main(argv=None):
    a = build_parser(argparse.ArgumentParser(prog="python -m kit.defectbench",
                                             description=__doc__.split("\n\n")[0])).parse_args(argv)
    try:
        if a.cmd == "cases":
            rows = [{"case": n, "roughness": lv, "ops": [o["op"] for o in ops], "model_of": mo, "expected": ex}
                    for n, lv, ops, mo, ex in CASES]
            if a.json:
                print(json.dumps(rows, indent=1))
            else:
                for r in rows:
                    print(f"{r['case']:12s} {r['expected']:14s} {r['roughness']:6s} {r['model_of']}")
            return 0
        if a.cmd == "make":
            tracks = ("column", "mini") if a.track == "both" else (a.track,)
            man = make(a.out, tracks, a.seeds, a.only)
            if a.json:
                print(json.dumps(man, indent=1))
            else:
                for e in man["cases"]:
                    tr = e["truth"]
                    print(f"{e['dir']:28s} {e['expected']:14s} wrong {tr['wrong']:6d} gap {tr['gap']:5d} "
                          f"fold {tr['fold']:4d} rough {tr['rough']:5d} crease {e['mesh']['crease_area_share']} "
                          f"spike {e['mesh']['spike_area_share']}")
            return 0
        if a.cmd == "check":
            bad = check(a.out)
            print(json.dumps({"agrees": not bad, "disagreements": bad}, indent=1) if a.json else
                  ("agrees" if not bad else "\n".join(["DISAGREES"] + bad)))
            return EXIT_DISAGREE if bad else 0
        if a.cmd == "baseline":
            print(baseline(a.out, a.dir, a.alarm, a.repair, a.track))
            return 0
        res = score(a.out, a.alarms, a.repaired, a.track)
        if a.out_file:
            Path(a.out_file).write_text(json.dumps(res, indent=1, allow_nan=False) + "\n")
        if a.json:
            print(json.dumps(res, indent=1))
        else:
            for k, v in res["families"].items():
                print(k, " ".join(f"{kk} {vv}" for kk, vv in v.items()))
        return 0
    except (BenchError, planted.PlantError, OSError) as exc:
        print(f"kit defectbench: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
