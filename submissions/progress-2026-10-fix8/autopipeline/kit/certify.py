"""Certify a traced surface: the cells no check faults, the largest certified square, and a fiber score.

  kit meshqa certify SURF --pitch P [--voxel-um V] [--compare S ...] [--rival S ...] [--prediction LOC] [--ct LOC]

A cell (grid vertex) of the tifxyz SURF fails when
  - it is a hole (VC3D's loader validity, kit/meshqa.py);
  - fold: the same surface lies about one pitch away along the cell's normal (0.5 to 1.5 pitch along it, lateral
    within one grid step, normals within 20 degrees, more than 3 pitches apart on the surface), and such cells add
    up to at least 16,384 square voxels over the surface (a sheet folded onto the next winding). By default
    (--fold-rule hairpin) only pairs whose normals point opposite ways count: the trace turned back over itself.
    Pairs whose normals point the same way are a winding that runs past one full turn; they are reported and fail
    only under --fold-rule any, the source's rule;
  - crossing: a --compare surface passes through the sheet near the cell (its vertices lie on both sides of the
    cell's tangent plane within 1.5 of its grid steps, at more than 20 degrees to the sheet). A parallel surface one
    pitch away is the next winding and is not a crossing; a coincident trace of the same sheet is not either;
  - rival crossing: the same test against a --rival surface (another trace whose claim competes with SURF's), but
    the cell fails only when SURF agrees less than the rival with the --compare surfaces around the crossing, and
    for both when they agree equally. Agreement is the share of a surface's vertices within 3 pitches of the
    crossing that lie within 4 voxels of a --compare surface along its normal;
  - steep (needs --prediction): the sheet runs more than 25 degrees against the surface prediction (normal from the
    structure tensor of the prediction in a 9-voxel box), in a 4-connected cluster of more than 101 such points,
    widened by 2 cells (taxicab). A steep point outside such a cluster does not fail its cell.
A square is certified when none of its cells fails. The fiber score (needs --ct and --voxel-um) is the median, over
up to 64 random windows of 128 x 128 points resampled every 0.03745 mm (--fibre-step-mm) inside the certified (or valid) cells,
of the share of the raw scan's non-DC spectral power at periods of 0.15 to 0.6 mm along the two grid axes (half
width 2 bins, Hann window, mean removed); white noise scores about the band's share of the bins, printed beside it.

Source. Giovanni Pellerano, "An Automatic Patch Based Unwrapping Pipeline Applied to PHerc. 0826"
(https://github.com/evilaliv3/vesuvius-challenge-pipeline, results/f49f6c7d-pherc0826-chain, read 12 Oct 2026;
code MIT): the certification rule (body.tex, sections 1 and 3), the pitch conflict test (src/tools/studies/
area-0826-90/lamina.py, conflicts()), the a2 settings T* 25 degrees and S 101 (src/prereg/chain-0826.md) and the
fiber score (src/tools/studies/certified-piece-0826/fibre.py, bands() and wscore(), same constants and draw seed).
Their numbers on PHerc. 0826 (Community report): pitch 15.125 voxels; white noise 0.0293, their reference sheet
0.0906, their bar 0.0680 (75 % of the reference); 61 of 92 certified pieces passed and the 4 largest failed.

Deliberate deviations (Interpretation, not from the source):
  - Their sheets are Stevens' flattened grids; ours are tifxyz grids whose step is the median vertex spacing, so a
    cell is a grid vertex and the square's side is cells times the smaller median step.
  - The fold area threshold is applied to the surface's total self-conflict area, as their combine() does for
    "wrapping"; below it no cell fails for a fold.
  - The default fold rule counts only hairpins. On four published PHerc0139 windings, self-conflict pairs with
    the same orientation outnumbered opposite ones by 44,215 to 1, 33,909 to 58, 2,826 to 0 and 2,990 to 6, all
    where a winding runs past one turn; a synthetic hairpin gave 0 to 13,464 (Model output, 12 Oct 2026,
    a note of the source repository). Each cell of a full-turn winding still lies on one lamina, so the
    overlap is not a fault there. --fold-rule any keeps the source's rule.
  - The crossing test is ours: their crossing map (v2) is not in the published source.
  - Rival adjudication is per crossing region, not per cell, and agreement is measured on the --compare surfaces.
  - The a2 measurement (a2_after.py) is not in the published source; the prediction normal here is the structure
    tensor's leading eigenvector, and S 101 counts points at --a2-stride, not recalibrated for tifxyz grids.
  - The fiber windows are resampled from the tifxyz grid (bilinear in x, y, z), since a tifxyz step of about 20
    voxels is too coarse for 0.15 mm periods; the CT is read at the nearest voxel. The default step, 0.03745 mm,
    is the one at which white noise scores their 0.0293 (four 9.362 um voxels); at one voxel the band sits next
    to DC and every smooth image scores high (Model output, 12 Oct 2026, a note of the source repository).
  - Their bar came from one of their own sheets on PHerc. 0826; no bar is assumed here (--fibre-bar sets one).
A certificate means these checks passed and nothing more: it is not a reading, and the article itself shows the
checks can certify surface that runs through air.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

FOLD_ALONG = (0.5, 1.5)          # pitches along the normal
FOLD_COS = math.cos(math.radians(20.0))
FOLD_GEO_PITCHES = 3.0
FOLD_MIN_AREA = 16384.0          # square voxels
FOLD_RULES = ("hairpin", "any")
CROSS_COS = math.cos(math.radians(20.0))
CROSS_REACH = 1.5                # grid steps
CROSS_TAU = 0.1                  # voxels: a vertex this close to the plane is on neither side
ADJ_RADIUS_PITCHES = 3.0
ADJ_NEAR = 4.0                   # voxels
A2_T = 25.0                      # degrees
A2_S = 101                       # points
A2_DILATE = 2
A2_HALF = 4                      # box half width, voxels
FIBRE_N, FIBRE_NW, FIBRE_HW = 128, 64, 2
FIBRE_PERIODS_MM = (0.15, 0.6)
FIBRE_SEED = 20260929
FIBRE_STEP_MM = 0.03745         # white noise then scores 0.0293, the source's figure
FIBRE_MAXDRAW = 20000
SQUARE_MM = 20.0                 # a 4 cm2 First Letters window

FAIL_HOLE, FAIL_FOLD, FAIL_CROSS, FAIL_RIVAL, FAIL_STEEP = 1, 2, 4, 8, 16
FAIL_NAMES = {FAIL_HOLE: "hole", FAIL_FOLD: "fold", FAIL_CROSS: "crossing", FAIL_RIVAL: "rival", FAIL_STEEP: "steep"}


class CertifyError(ValueError):
    pass


def _np():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - the core kit is standard library only
        raise CertifyError("kit meshqa certify needs numpy") from exc
    return np


# ---------------------------------------------------------------- surfaces

class Sheet:
    """A tifxyz grid as points P (H, W, 3) in voxels (x, y, z), validity, unit normals and median grid steps."""

    def __init__(self, P, valid, name="surface"):
        np = _np()
        self.P = np.asarray(P, dtype=np.float64)
        self.valid = np.asarray(valid, dtype=bool) & np.isfinite(self.P).all(axis=-1)
        self.name = name
        self.N, self.nvalid = normals(self.P, self.valid)
        self.step_i, self.step_j = grid_steps(self.P, self.valid)

    @property
    def shape(self):
        return self.valid.shape

    @property
    def step(self):
        return min(self.step_i, self.step_j)

    def cells(self, mask=None):
        np = _np()
        m = self.nvalid if mask is None else (mask & self.nvalid)
        ii, jj = np.nonzero(m)
        return ii, jj, self.P[ii, jj], self.N[ii, jj]


def load_sheet(path):
    from . import meshqa
    patch = meshqa.load_patch(path)
    if patch.read_errors:
        raise CertifyError(f"{path}: {patch.read_errors}")
    if not patch.shapes_agree() or patch.x.size == 0:
        raise CertifyError(f"{path}: x, y and z grids are empty or differ in shape")
    return Sheet(patch.points(), patch.valid, name=Path(path).name)


def grid_steps(P, valid):
    np = _np()
    out = []
    for ax in (0, 1):
        a = [slice(None)] * 2
        b = [slice(None)] * 2
        a[ax], b[ax] = slice(0, -1), slice(1, None)
        ok = valid[tuple(a)] & valid[tuple(b)]
        d = np.linalg.norm(P[tuple(b)] - P[tuple(a)], axis=-1)[ok]
        out.append(float(np.median(d)) if d.size else float("nan"))
    if not all(math.isfinite(s) and s > 0 for s in out):
        raise CertifyError("the grid has no two valid neighbors along a row or a column")
    return out[0], out[1]


def normals(P, valid):
    """Unit normals from central differences (one-sided at an edge or a hole); (N, normal valid)."""
    np = _np()

    def diff(ax):
        Pm = np.moveaxis(P, ax, 0)
        vm = np.moveaxis(valid, ax, 0)
        d = np.full(Pm.shape, np.nan)
        ok = np.zeros(vm.shape, bool)
        if vm.shape[0] < 2:
            return np.moveaxis(d, 0, ax), np.moveaxis(ok, 0, ax)
        if vm.shape[0] >= 3:
            c = vm[:-2] & vm[2:]
            d[1:-1][c] = ((Pm[2:] - Pm[:-2]) / 2.0)[c]
            ok[1:-1] = c
        fwd = vm[:-1] & vm[1:]
        step = Pm[1:] - Pm[:-1]
        need = ~ok[:-1] & fwd          # forward difference where the central one is missing
        d[:-1][need] = step[need]
        ok[:-1] |= need
        need = ~ok[1:] & fwd           # backward difference
        d[1:][need] = step[need]
        ok[1:] |= need
        return np.moveaxis(d, 0, ax), np.moveaxis(ok, 0, ax)

    di, oki = diff(0)
    dj, okj = diff(1)
    n = np.cross(dj, di)
    ln = np.linalg.norm(n, axis=-1)
    good = valid & oki & okj & np.isfinite(ln) & (ln > 1e-12)
    N = np.zeros(P.shape)
    N[good] = n[good] / ln[good][:, None]
    return N, good


# ---------------------------------------------------------------- neighbor pairs (no scipy)

def pairs_within(A, B, r, chunk=200000):
    """(ia, ib): every pair with |A[ia] - B[ib]| <= r, by a spatial hash of cell r."""
    np = _np()
    A = np.asarray(A, dtype=np.float64).reshape(-1, 3)
    B = np.asarray(B, dtype=np.float64).reshape(-1, 3)
    if len(A) == 0 or len(B) == 0:
        e = np.zeros(0, np.int64)
        return e, e
    lo = np.minimum(A.min(0), B.min(0)) - r
    cb = np.floor((B - lo) / r).astype(np.int64)
    ca = np.floor((A - lo) / r).astype(np.int64)
    span = max(int(cb.max()), int(ca.max())) + 3
    if span ** 3 >= 2 ** 62:
        raise CertifyError("surface extent too large for the neighbor hash")

    def key(c):
        return (c[:, 0] * span + c[:, 1]) * span + c[:, 2]

    kb = key(cb)
    order = np.argsort(kb, kind="stable")
    ks = kb[order]
    uk, start, count = np.unique(ks, return_index=True, return_counts=True)
    out_a, out_b = [], []
    r2 = r * r
    for c0 in range(0, len(A), chunk):
        ca_c = ca[c0:c0 + chunk]
        Ac = A[c0:c0 + chunk]
        for off in ((dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)):
            q = key(ca_c + np.array(off, dtype=np.int64))
            pos = np.searchsorted(uk, q)
            pos = np.clip(pos, 0, len(uk) - 1)
            hit = uk[pos] == q
            if not hit.any():
                continue
            ai = np.flatnonzero(hit)
            cnt = count[pos[ai]]
            st = start[pos[ai]]
            rep_a = np.repeat(ai, cnt)
            first = np.repeat(np.cumsum(cnt) - cnt, cnt)
            bi = order[np.repeat(st, cnt) + (np.arange(len(rep_a)) - first)]
            d2 = ((Ac[rep_a] - B[bi]) ** 2).sum(1)
            k = d2 <= r2
            out_a.append(rep_a[k] + c0)
            out_b.append(bi[k])
    if not out_a:
        e = np.zeros(0, np.int64)
        return e, e
    return np.concatenate(out_a), np.concatenate(out_b)


# ---------------------------------------------------------------- grid helpers

def label4(mask):
    """4-connected component id of every True cell (-1 elsewhere) and the component sizes."""
    np = _np()
    from .meshqa import union_min
    H, W = mask.shape
    idx = np.flatnonzero(mask.ravel())
    lab = np.full(H * W, -1, np.int64)
    if idx.size == 0:
        return lab.reshape(H, W), np.zeros(0, np.int64)
    cmap = np.full(H * W, -1, np.int64)
    cmap[idx] = np.arange(idx.size)
    eu, ev = [], []
    h = np.zeros((H, W), bool)
    h[:, :-1] = mask[:, :-1] & mask[:, 1:]
    u = np.flatnonzero(h.ravel())
    eu.append(cmap[u]); ev.append(cmap[u + 1])
    v = np.zeros((H, W), bool)
    v[:-1] = mask[:-1] & mask[1:]
    u = np.flatnonzero(v.ravel())
    eu.append(cmap[u]); ev.append(cmap[u + W])
    root = union_min(np, idx.size, np.concatenate(eu), np.concatenate(ev))
    _, comp = np.unique(root, return_inverse=True)
    lab[idx] = comp
    return lab.reshape(H, W), np.bincount(comp)


def dilate4(mask, k):
    """Taxicab dilation by k cells."""
    np = _np()
    m = mask.copy()
    for _ in range(int(k)):
        n = m.copy()
        n[1:] |= m[:-1]
        n[:-1] |= m[1:]
        n[:, 1:] |= m[:, :-1]
        n[:, :-1] |= m[:, 1:]
        m = n
    return m


def largest_square(ok):
    """(side in cells, top-left row, top-left col) of the largest all-True square.

    Among equal squares the first bottom-right corner in row-major order wins. The square ending at (i, j) has side
    min(side at (i-1, j-1) + 1, the True run up from (i, j), the True run left of it), so each row is one array
    step."""
    np = _np()
    ok = np.asarray(ok, bool)
    H, W = ok.shape
    best, at = 0, (None, None)
    if H == 0 or W == 0:
        return best, at[0], at[1]
    idx = np.arange(W)
    up = np.zeros(W, np.int64)
    prev = np.zeros(W + 1, np.int64)   # the row above, shifted one right: prev[j] is column j - 1
    for i in range(H):
        row = ok[i]
        up = np.where(row, up + 1, 0)
        left = idx - np.maximum.accumulate(np.where(row, -1, idx))
        cur = np.minimum(np.minimum(prev[:-1] + 1, up), left)
        v = int(cur.max())
        if v > best:
            j = int(np.argmax(cur))
            best, at = v, (i - v + 1, j - v + 1)
        prev[1:] = cur
    return best, at[0], at[1]


# ---------------------------------------------------------------- checks

def fold_cells(sheet, pitch):
    """Cells in pitch conflict with the same surface (lamina.py conflicts(..., same=True)), split by orientation.

    Returns (hairpin, wrap): hairpin cells pair with a part of the surface whose normal points the other way (the
    trace turned back over itself onto the neighboring sheet); wrap cells pair with a part whose normal points the
    same way (a winding that runs past one full turn and lies over its own start one pitch out). A cell can be both.
    """
    np = _np()
    ii, jj, Pa, Na = sheet.cells()
    hairpin = np.zeros(sheet.shape, bool)
    wrap = np.zeros(sheet.shape, bool)
    a, b = pairs_within(Pa, Pa, FOLD_ALONG[1] * pitch)
    if a.size == 0:
        return hairpin, wrap
    v = Pa[b] - Pa[a]
    na = Na[a]
    along = (v * na).sum(1)
    lat = np.linalg.norm(v - along[:, None] * na, axis=1)
    geo = np.hypot((ii[a] - ii[b]) * sheet.step_i, (jj[a] - jj[b]) * sheet.step_j)
    dot = (na * Na[b]).sum(1)
    ok = ((np.abs(along) >= FOLD_ALONG[0] * pitch) & (np.abs(along) <= FOLD_ALONG[1] * pitch)
          & (lat <= max(sheet.step_i, sheet.step_j)) & (np.abs(dot) >= FOLD_COS)
          & (geo > FOLD_GEO_PITCHES * pitch))
    back = ok & (dot < 0)
    same = ok & (dot > 0)
    hairpin[ii[a[back]], jj[a[back]]] = True
    wrap[ii[a[same]], jj[a[same]]] = True
    return hairpin, wrap


def crossing_cells(sheet, other):
    """Cells of `sheet` that `other` passes through at more than 20 degrees."""
    np = _np()
    ii, jj, Pa, Na = sheet.cells()
    _, _, Pb, Nb = other.cells()
    out = np.zeros(sheet.shape, bool)
    lat_max = CROSS_REACH * max(sheet.step, other.step)
    d_max = CROSS_REACH * other.step
    a, b = pairs_within(Pa, Pb, math.hypot(lat_max, d_max))
    if a.size == 0:
        return out
    v = Pb[b] - Pa[a]
    na = Na[a]
    d = (v * na).sum(1)
    lat = np.linalg.norm(v - d[:, None] * na, axis=1)
    keep = (lat <= lat_max) & (np.abs(d) <= d_max) & (np.abs((na * Nb[b]).sum(1)) < CROSS_COS)
    a, d = a[keep], d[keep]
    pos = np.zeros(len(Pa), bool)
    neg = np.zeros(len(Pa), bool)
    pos[a[d > CROSS_TAU]] = True
    neg[a[d < -CROSS_TAU]] = True
    hit = pos & neg
    out[ii[hit], jj[hit]] = True
    return out


def on_reference(sheet, refs, mask):
    """Of the cells in `mask`, which lie within ADJ_NEAR voxels of some reference surface along its normal."""
    np = _np()
    ii, jj, Pa, _ = sheet.cells(mask)
    hit = np.zeros(len(Pa), bool)
    for ref in refs:
        _, _, Pb, Nb = ref.cells()
        lat_max = max(ref.step_i, ref.step_j)
        a, b = pairs_within(Pa, Pb, math.hypot(lat_max, ADJ_NEAR))
        if a.size == 0:
            continue
        v = Pa[a] - Pb[b]
        d = (v * Nb[b]).sum(1)
        lat = np.linalg.norm(v - d[:, None] * Nb[b], axis=1)
        hit[a[(np.abs(d) <= ADJ_NEAR) & (lat <= lat_max)]] = True
    return ii, jj, hit


def agreement(sheet, region, refs):
    np = _np()
    _, _, hit = on_reference(sheet, refs, region)
    return float(hit.mean()) if hit.size else 0.0


def rival_cells(sheet, rival, refs, pitch):
    """(cells of `sheet` lost to `rival`, record). Without references every crossing cell is lost."""
    np = _np()
    mine = crossing_cells(sheet, rival)
    rec = {"rival": rival.name, "crossing_cells": int(mine.sum())}
    if not mine.any():
        rec["lost"] = False
        return mine, rec
    theirs = crossing_cells(rival, sheet)
    k_me = max(1, int(math.ceil(ADJ_RADIUS_PITCHES * pitch / sheet.step)))
    k_them = max(1, int(math.ceil(ADJ_RADIUS_PITCHES * pitch / rival.step)))
    reg_me = dilate4(mine, k_me) & sheet.nvalid
    reg_them = dilate4(theirs, k_them) & rival.nvalid if theirs.any() else theirs
    if not refs:
        rec.update(agree_self=None, agree_rival=None, lost=True, why="no --compare surfaces to adjudicate")
        return mine, rec
    ag_me = agreement(sheet, reg_me, refs)
    ag_them = agreement(rival, reg_them, refs) if theirs.any() else 0.0
    lost = ag_me <= ag_them
    rec.update(agree_self=round(ag_me, 6), agree_rival=round(ag_them, 6), lost=bool(lost),
               why="equal agreement: both lose" if ag_me == ag_them else
               ("the rival agrees more with the compared surfaces" if lost else "this surface agrees more"))
    return (mine if lost else np.zeros_like(mine)), rec


class ArrayVolume:
    """A (z, y, x) numpy array with Volume's read(level, box) for level 0."""

    def __init__(self, arr):
        self.arr = arr

    def read(self, level, box):
        np = _np()
        if level != 0:
            raise CertifyError("an array volume has level 0 only")
        (z0, z1), (y0, y1), (x0, x1) = [[int(a), int(b)] for a, b in box]
        out = np.zeros((max(0, z1 - z0), max(0, y1 - y0), max(0, x1 - x0)), dtype=self.arr.dtype)
        Z, Y, X = self.arr.shape
        sz = slice(max(0, z0), min(Z, z1)); sy = slice(max(0, y0), min(Y, y1)); sx = slice(max(0, x0), min(X, x1))
        if sz.start < sz.stop and sy.start < sy.stop and sx.start < sx.stop:
            out[sz.start - z0:sz.stop - z0, sy.start - y0:sy.stop - y0, sx.start - x0:sx.stop - x0] = \
                self.arr[sz, sy, sx]
        return out


def open_volume(location, voxel_um=None):
    np = _np()
    loc = str(location)
    if loc.endswith(".npy"):
        return ArrayVolume(np.load(loc, mmap_mode="r"))
    from .vc3d_region import Volume
    return Volume(loc, voxel_um=voxel_um)


def prediction_normal(box):
    """Leading eigenvector (x, y, z) of the gradient structure tensor of a (z, y, x) box, or None if flat."""
    np = _np()
    b = np.asarray(box, dtype=np.float64)
    if b.max() <= b.min():
        return None
    gz, gy, gx = np.gradient(b)
    G = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], 1)
    T = G.T @ G
    if np.trace(T) <= 1e-12:
        return None
    w, V = np.linalg.eigh(T)
    return V[:, -1]


def steep_cells(sheet, vol, stride=1, half=A2_HALF, t_deg=A2_T, s_min=A2_S, dilate=A2_DILATE):
    """(failing cells, record): points steeper than t_deg against the prediction, clusters of more than s_min."""
    np = _np()
    H, W = sheet.shape
    gi = np.arange(0, H, stride)
    gj = np.arange(0, W, stride)
    flag = np.zeros((len(gi), len(gj)), bool)
    meas = 0
    cos_t = math.cos(math.radians(t_deg))
    for a, i in enumerate(gi):
        for b, j in enumerate(gj):
            if not sheet.nvalid[i, j]:
                continue
            x, y, z = np.rint(sheet.P[i, j]).astype(int)
            box = vol.read(0, [[z - half, z + half + 1], [y - half, y + half + 1], [x - half, x + half + 1]])
            m = prediction_normal(box)
            if m is None:
                continue
            meas += 1
            if abs(float(np.dot(m, sheet.N[i, j]))) < cos_t:
                flag[a, b] = True
    lab, sizes = label4(flag)
    big = np.flatnonzero(sizes > s_min)
    cut = np.isin(lab, big) if big.size else np.zeros_like(flag)
    cut = dilate4(cut, dilate) if cut.any() else cut
    out = np.zeros((H, W), bool)
    if cut.any():
        full = np.repeat(np.repeat(cut, stride, 0), stride, 1)[:H, :W]
        out = full & sheet.valid
    rec = {"stride": stride, "t_deg": t_deg, "s_min": s_min, "measurable": int(meas), "flagged": int(flag.sum()),
           "flagged_share": round(flag.sum() / meas, 6) if meas else None,
           "largest_cluster": int(sizes.max()) if sizes.size else 0, "clusters_cut": int(big.size)}
    return out, rec


# ---------------------------------------------------------------- fiber score

def fibre_bands(step_mm, n=FIBRE_N, hw=FIBRE_HW, periods=FIBRE_PERIODS_MM):
    """(band mask, non-DC mask, white-noise share) for an n x n window at step_mm on both axes."""
    np = _np()
    pmin, pmax = periods
    k = np.rint(np.fft.fftfreq(n) * n).astype(int)
    KI, KJ = np.meshgrid(k, k, indexing="ij")
    lo, hi = n * step_mm / pmax, n * step_mm / pmin
    bi = (np.abs(KI) >= lo) & (np.abs(KI) <= hi) & (np.abs(KJ) <= hw)
    bj = (np.abs(KJ) >= lo) & (np.abs(KJ) <= hi) & (np.abs(KI) <= hw)
    band = bi | bj
    nondc = ~((KI == 0) & (KJ == 0))
    return band, nondc, float(band.sum() / nondc.sum())


def window_score(win, band, nondc):
    np = _np()
    n = win.shape[0]
    hann = np.outer(np.hanning(n), np.hanning(n))
    v = (win - win.mean()) * hann
    P = np.abs(np.fft.fft2(v)) ** 2
    tot = P[nondc].sum()
    return float(P[band].sum() / tot) if tot > 0 else float("nan")


def _bilinear(P, u, v):
    np = _np()
    i0 = np.clip(np.floor(u).astype(int), 0, P.shape[0] - 2)
    j0 = np.clip(np.floor(v).astype(int), 0, P.shape[1] - 2)
    fu = (u - i0)[..., None]
    fv = (v - j0)[..., None]
    return ((1 - fu) * (1 - fv) * P[i0, j0] + (1 - fu) * fv * P[i0, j0 + 1]
            + fu * (1 - fv) * P[i0 + 1, j0] + fu * fv * P[i0 + 1, j0 + 1])


def sample_nearest(vol, idx):
    """Level-0 values at integer points idx (..., 3) as (x, y, z). A kit.vc3d_region.Volume is read chunk by chunk,
    only the chunks the points fall in (a tilted window's bounding box can hold several times as many); anything
    else needs read(level, box). Points outside the array read 0, which the fiber score treats as masked."""
    np = _np()
    flat = np.asarray(idx, dtype=np.int64).reshape(-1, 3)
    out = np.zeros(len(flat))
    if not (hasattr(vol, "levels") and hasattr(vol, "_chunk")):
        lo = flat.min(0)
        hi = flat.max(0) + 1
        block = vol.read(0, [[lo[2], hi[2]], [lo[1], hi[1]], [lo[0], hi[0]]])
        loc = flat - lo
        out[:] = block[loc[:, 2], loc[:, 1], loc[:, 0]]
        return out.reshape(np.shape(idx)[:-1])
    import concurrent.futures
    meta = vol.levels[0]["meta"]
    ch = np.array(meta["chunks"], dtype=np.int64)
    shape = np.array(meta["shape"], dtype=np.int64)
    zyx = flat[:, ::-1]
    inside = np.flatnonzero((zyx >= 0).all(1) & (zyx < shape).all(1))
    if inside.size:
        from .vc3d_region import chunk_groups
        ci = zyx[inside] // ch
        keys, order, bounds = chunk_groups(ci)
        with concurrent.futures.ThreadPoolExecutor(max(1, min(getattr(vol, "workers", 8), len(keys)))) as pool:
            arrs = list(pool.map(lambda k: vol._chunk(0, tuple(int(v) for v in k)), keys))
        fill = meta.get("fill_value")
        fill = fill if isinstance(fill, (int, float)) and fill == fill else 0
        for n, arr in enumerate(arrs):
            sel = inside[order[bounds[n]:bounds[n + 1]]]
            if arr is None:
                out[sel] = fill
                continue
            loc = zyx[sel] - keys[n] * ch
            out[sel] = arr[loc[:, 0], loc[:, 1], loc[:, 2]]
    return out.reshape(np.shape(idx)[:-1])


def fibre_score(sheet, vol, voxel_um, piece=None, fine_step=None, n=FIBRE_N, nw=FIBRE_NW, seed=FIBRE_SEED,
                maxdraw=FIBRE_MAXDRAW):
    """Median window score inside `piece` (default: valid cells), with the windows drawn and the white-noise share."""
    np = _np()
    piece = sheet.valid if piece is None else (piece & sheet.valid)
    if fine_step is None:
        fine_step = FIBRE_STEP_MM * 1000.0 / voxel_um
    step_mm = fine_step * voxel_um / 1000.0
    band, nondc, white = fibre_bands(step_mm, n=n)
    wi = int(math.ceil((n - 1) * fine_step / sheet.step_i)) + 2
    wj = int(math.ceil((n - 1) * fine_step / sheet.step_j)) + 2
    H, W = sheet.shape
    rec = {"fine_step_vox": round(fine_step, 4), "window_points": n, "step_mm": round(step_mm, 6),
           "periods_mm": list(FIBRE_PERIODS_MM), "white_noise_share": round(white, 6)}
    if H < wi or W < wj:
        rec.update(windows=0, score=None, why="the piece is smaller than one window")
        return rec
    S = np.zeros((H + 1, W + 1), np.int64)
    S[1:, 1:] = piece.astype(np.int64).cumsum(0).cumsum(1)
    rng = np.random.default_rng(seed)
    I = rng.integers(0, H - wi + 1, maxdraw)
    J = rng.integers(0, W - wj + 1, maxdraw)
    full = (S[I + wi, J + wj] - S[I, J + wj] - S[I + wi, J] + S[I, J]) == wi * wj
    a = np.arange(n) * fine_step
    scores, tried = [], 0
    for i0, j0 in zip(I[full], J[full]):
        tried += 1
        U, V = np.meshgrid(i0 + a / sheet.step_i, j0 + a / sheet.step_j, indexing="ij")
        Q = _bilinear(sheet.P, U, V)
        win = sample_nearest(vol, np.rint(Q).astype(np.int64))
        if (win == 0).any() or not np.isfinite(win).all():
            continue                     # masked scan or outside it (the source skips zeros and NaN)
        s = window_score(win, band, nondc)
        if math.isfinite(s):
            scores.append(s)
        if len(scores) >= nw:
            break
    rec.update(windows=len(scores), windows_tried=tried,
               score=round(float(np.median(scores)), 6) if scores else None,
               why=None if scores else "no window fits inside the piece on scan data")
    return rec


# ---------------------------------------------------------------- the whole certificate

def certify(sheet, pitch, compare=(), rivals=(), prediction=None, ct=None, voxel_um=None, a2_stride=1,
            fibre_step=None, fibre_on="certified", fibre_bar=None, square_mm=SQUARE_MM, fold_rule="hairpin"):
    np = _np()
    if not pitch or pitch <= 0:
        raise CertifyError("--pitch must be a positive number of voxels")
    fail = np.zeros(sheet.shape, np.uint8)
    fail[~sheet.valid] |= FAIL_HOLE
    rep = {"surface": sheet.name, "grid": list(sheet.shape), "step_i_vox": round(sheet.step_i, 4),
           "step_j_vox": round(sheet.step_j, 4), "pitch_vox": pitch, "valid_cells": int(sheet.valid.sum())}
    cell_area = sheet.step_i * sheet.step_j
    if fold_rule not in FOLD_RULES:
        raise CertifyError(f"--fold-rule must be one of {', '.join(FOLD_RULES)}")
    hairpin, wrap = fold_cells(sheet, pitch)
    counted = hairpin if fold_rule == "hairpin" else (hairpin | wrap)
    fold_area = float(counted.sum() * cell_area)
    folds = fold_area >= FOLD_MIN_AREA
    if folds:
        fail[counted] |= FAIL_FOLD
    rep["fold"] = {"rule": fold_rule, "cells": int(counted.sum()), "area_vox2": round(fold_area, 1),
                   "min_area_vox2": FOLD_MIN_AREA, "folds": bool(folds),
                   "hairpin_cells": int(hairpin.sum()), "hairpin_area_vox2": round(float(hairpin.sum() * cell_area), 1),
                   "wrap_cells": int(wrap.sum()), "wrap_area_vox2": round(float(wrap.sum() * cell_area), 1)}
    rep["crossings"] = []
    for other in compare:
        c = crossing_cells(sheet, other)
        fail[c] |= FAIL_CROSS
        rep["crossings"].append({"compare": other.name, "cells": int(c.sum())})
    rep["rivals"] = []
    for rv in rivals:
        lost, rec = rival_cells(sheet, rv, list(compare), pitch)
        fail[lost] |= FAIL_RIVAL
        rep["rivals"].append(rec)
    if prediction is not None:
        st, rec = steep_cells(sheet, prediction, stride=a2_stride)
        fail[st] |= FAIL_STEEP
        rec["cells_cut"] = int(st.sum())
        rep["steep"] = rec
    else:
        rep["steep"] = None
    ok = fail == 0
    unit_mm = sheet.step * voxel_um / 1000.0 if voxel_um else None
    hf, hi, hj = largest_square(sheet.valid)
    cs, ci, cj = largest_square(ok)
    rep["counts"] = {name: int(((fail & bit) != 0).sum()) for bit, name in FAIL_NAMES.items()}
    rep["certified_cells"] = int(ok.sum())
    rep["hole_free_square"] = {"cells": hf, "row": hi, "col": hj,
                               "mm": round(hf * unit_mm, 4) if unit_mm else None}
    rep["certified_square"] = {"cells": cs, "row": ci, "col": cj,
                               "mm": round(cs * unit_mm, 4) if unit_mm else None}
    if unit_mm:
        rep["certified_square"]["reaches_mm"] = square_mm
        rep["certified_square"]["reaches"] = bool(cs * unit_mm >= square_mm)
    if ct is not None:
        if not voxel_um:
            raise CertifyError("the fiber score needs --voxel-um")
        piece = ok if fibre_on == "certified" else sheet.valid
        fr = fibre_score(sheet, ct, voxel_um, piece=piece, fine_step=fibre_step)
        fr["on"] = fibre_on
        if fibre_bar is not None:
            fr["bar"] = fibre_bar
            fr["passes"] = None if fr["score"] is None else bool(fr["score"] >= fibre_bar)
        rep["fibre"] = fr
    else:
        rep["fibre"] = None
    return rep, fail


def format_report(rep):
    lines = [f"certify {rep['surface']}: grid {rep['grid'][0]} x {rep['grid'][1]}, step "
             f"{rep['step_i_vox']} x {rep['step_j_vox']} voxels, pitch {rep['pitch_vox']}"]
    k = rep["counts"]
    lines.append("  failing cells: " + ", ".join(f"{n} {k[n]}" for n in FAIL_NAMES.values()))
    f = rep["fold"]
    lines.append(f"  fold ({f['rule']}): {f['cells']} cells, {f['area_vox2']} square voxels "
                 f"({'folds onto the next winding' if f['folds'] else 'under the area threshold'}); "
                 f"hairpin {f['hairpin_cells']} cells, wrap past one turn {f['wrap_cells']} cells"
                 + (" (reported, not failed)" if f['rule'] == "hairpin" and f['wrap_cells'] else ""))
    for c in rep["crossings"]:
        lines.append(f"  crossing with {c['compare']}: {c['cells']} cells")
    for r in rep["rivals"]:
        lines.append(f"  rival {r['rival']}: {r['crossing_cells']} crossing cells, "
                     f"{'lost' if r['lost'] else 'kept'}" + (f" ({r['why']})" if r.get("why") else ""))
    if rep["steep"]:
        s = rep["steep"]
        lines.append(f"  steep: {s['flagged']} of {s['measurable']} points over {s['t_deg']} degrees, largest "
                     f"cluster {s['largest_cluster']}, {s['cells_cut']} cells cut")
    for key, label in (("hole_free_square", "hole-free square"), ("certified_square", "certified square")):
        q = rep[key]
        mm = f", {q['mm']} mm" if q.get("mm") is not None else ""
        lines.append(f"  {label}: {q['cells']} cells{mm}")
    if rep["fibre"]:
        fr = rep["fibre"]
        bar = ""
        if "bar" in fr:
            bar = f", bar {fr['bar']}: {'pass' if fr['passes'] else 'fail' if fr['passes'] is False else 'n/a'}"
        lines.append(f"  fiber score: {fr['score']} over {fr['windows']} windows (white noise about "
                     f"{fr['white_noise_share']}){bar}")
    lines.append("  A certificate means these checks passed, nothing more; it is not a reading.")
    return "\n".join(lines)


def add_parser(act):
    c = act.add_parser("certify", help="certified cells and largest certified square of a tifxyz (holes, folds onto "
                                       "the next winding, crossings, steep clusters) and a fiber score of the raw scan")
    c.add_argument("surface", help="tifxyz folder")
    c.add_argument("--pitch", type=float, required=True, help="voxels between windings (PHerc0826: 15.125)")
    c.add_argument("--voxel-um", type=float, help="level-0 voxel size, for mm and the fiber score")
    c.add_argument("--compare", nargs="+", default=[], metavar="TIFXYZ",
                   help="surfaces any crossing with which fails a cell (and that adjudicate rival crossings)")
    c.add_argument("--rival", nargs="+", default=[], metavar="TIFXYZ",
                   help="competing traces: a crossing fails the one that agrees less with --compare")
    c.add_argument("--prediction", metavar="LOC", help="surface prediction zarr (local or URL) or .npy (z, y, x)")
    c.add_argument("--a2-stride", type=int, default=1, help="grid stride of the steep test (default 1)")
    c.add_argument("--ct", metavar="LOC", help="raw scan zarr (local or URL) or .npy (z, y, x), for the fiber score")
    c.add_argument("--fibre-step-mm", type=float, default=FIBRE_STEP_MM,
                   help="resampling step of the fiber windows in mm (default 0.03745, the source's grid)")
    c.add_argument("--fibre-on", choices=("certified", "valid"), default="certified")
    c.add_argument("--fibre-bar", type=float, help="report pass or fail against this fiber score")
    c.add_argument("--fold-rule", choices=FOLD_RULES, default="hairpin",
                   help="hairpin (default): only a surface turned back over itself fails for a fold, and a winding "
                        "past one full turn is reported; any: both fail, as in the source")
    c.add_argument("--square-mm", type=float, default=SQUARE_MM, help="report whether the certified square reaches "
                                                                      "this side (default 20 mm, a 4 cm2 window)")
    c.add_argument("--fail-map", metavar="OUT.tif", help="uint8 grid of failure bits: 1 hole, 2 fold, 4 crossing, "
                                                         "8 rival, 16 steep")
    c.add_argument("--json", action="store_true", help="print JSON")
    return c


def run_certify(args):
    sheet = load_sheet(args.surface)
    compare = [load_sheet(p) for p in args.compare]
    rivals = [load_sheet(p) for p in args.rival]
    pred = open_volume(args.prediction, args.voxel_um) if args.prediction else None
    ct = open_volume(args.ct, args.voxel_um) if args.ct else None
    rep, fail = certify(sheet, args.pitch, compare, rivals, prediction=pred, ct=ct, voxel_um=args.voxel_um,
                        a2_stride=args.a2_stride,
                        fibre_step=(args.fibre_step_mm * 1000.0 / args.voxel_um) if args.voxel_um else None,
                        fibre_on=args.fibre_on,
                        fibre_bar=args.fibre_bar, square_mm=args.square_mm,
                        fold_rule=args.fold_rule)
    if args.fail_map:
        from . import vc3d_io
        vc3d_io.write_tiff(args.fail_map, vc3d_io.raster_from_numpy(fail))
        rep["fail_map"] = str(args.fail_map)
    print(json.dumps(rep, indent=2) if args.json else format_report(rep))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit("use: python -m kit meshqa certify ...")
