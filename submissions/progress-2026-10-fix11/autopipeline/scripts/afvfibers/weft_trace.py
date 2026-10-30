"""Weft: our own papyrus fiber tracer. V and H fiber probabilities in, fibers with a confidence each out, as AFV.

  python3 weft_trace.py crop --volume volume.json --blocks DIR --crop-l0 X0 X1 Y0 Y1 Z0 Z1 --out WEFT.afv
        [--halo 64] [--exterior EXT.npz] [--frame-from V2.afv] [--params JSON]
  python3 weft_trace.py v2crop --afv PHerc0332_afv_v2.afv --crop-l0 X0 X1 Y0 Y1 Z0 Z1 --out V2CROP.afv
  python3 weft_trace.py exterior --volume volume.json --out EXT.npz        (CT exterior, coarse cells, public CT)
  python3 weft_trace.py stats --afv A.afv [B.afv ...] --volume volume.json [--blocks DIR] --crop-l0 ...
        [--png OUT.png --slab 24]                                         (sanity numbers, not a scorer)

Written from scratch for this repository (27 Oct 2026). It reads the probability blocks afv_tile.py writes (the
published PHerc0332 set of Qual's AFV V2 model, Qualzz20/afv_fiber_9um_v2, Apache-2.0, in the public bucket
SharpMeow/afv-fiber-probabilities) and writes the AFV v1 SQLite layout that AVF_SPLINE_GENERATOR writes and villa's
import_afv.py reads. Qual's generator was read only to learn that file format and its coordinate convention (pooled
voxel i sits at native 2 i + 0.5); none of its tracing code is used. The algorithm, per family (V, then H):

1. Smooth the family's own pooled probability (the "tracing grid", 2x pooled from the probability level) with a small
   Gaussian, so the saturated plateaus the model writes get a single peak on the fiber's center line.
2. Direction field from the Hessian of a further 2x pooled copy (8 times fewer voxels than the tracing grid): the
   eigenvector of the eigenvalue nearest zero runs along a bright tube.
3. Seeds: tracing-grid voxels above a threshold that are maxima in the plane across the local direction (ridge
   centers), taken strongest first; a seed inside an already traced fiber's tube is skipped.
4. Tracing: unit steps along a blend of the field direction and the previous step, re-centered each step by a 3x3
   hill climb and a quadratic peak fit in the cross plane; it coasts straight through up to `gap_steps` weak steps and
   stops at a sharp turn, at the volume edge, after more than `contact_steps` steps inside another fiber's tube (so a
   touch or a crossing passes, running along an existing fiber does not), on returning onto its own path, or when
   it wanders (short chord over `wander_steps`). The other family is ignored here, so an H/V crossing does not stop
   a fiber unless its own probability really drops there.
5. Global linking: every pair of fragment ends of one family within `link_radius` is scored by collinearity, gap
   length, probability along the bridging curve (the other family's probability counts at `cross_weight`, because a
   crossing fiber hides this one), and context (whether the nearest same-family fibers run parallel to the join).
   Hard rules refuse joins that turn sharply, step sideways (a parallel neighbor), or cross another fiber. Joins are
   taken best first, one per end, without cycles; the bridge is a cubic Hermite curve.
6. Confidence per fiber in [0, 1] from its mean own probability, the share of its length with support, the bridged
   share, the weakest link and its length (a heuristic, not calibrated).
7. Optional: points in or near the scroll's outside (CT exterior cells) are cut out and the inner pieces kept.

Output: each fiber's annotation keeps villa's fields and adds "weft" (confidence, its parts, "bridges": inclusive
point index ranges on join bridges, "exterior_trimmed"); the extra table weft_fibers(id, confidence, parts) holds the
same and is ignored by villa's reader. Design, dev numbers and limits: a note of the source repository.

Coordinates: arrays are (z, y, x); output points are XYZ native level-0 voxels like the stitched V2 files
(L0 = 2^level x level coordinate; level coordinate = 2 t + 0.5 + origin for tracing-grid index t).
"""
import argparse
import json
import math
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import numpy as np

try:
    from numba import njit, prange
except ImportError:  # pragma: no cover
    def njit(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f
    prange = range

HERE = Path(__file__).resolve().parent

DEFAULTS = {
    "sigma": 1.2,            # smoothing of the tracing grid (tracing voxels)
    "dir_sigma": 1.0,        # Hessian scale on the direction grid (its voxels)
    "dir_pool": 2,           # direction grid: tracing grid pooled this many times per axis
    "seed": 150.0,           # smoothed own probability (0..255) a seed needs
    "low": 70.0,             # below this a step counts as a gap step
    "gap_steps": 3,          # weak steps coasted through before stopping
    "contact_steps": 4,      # steps allowed inside another fiber's tube (a touch or crossing) before stopping
    "turn_deg": 40.0,        # stop when one step turns more than this
    "wander_steps": 16,      # window for the straightness check (tracing voxels)
    "wander_ratio": 0.6,     # stop when the chord over that window is shorter than this share of it
    "alpha": 0.5,            # weight of the field direction against the last step
    "cover_r": 1.6,          # tube radius marked around a traced fiber (tracing voxels)
    "max_steps": 6000,       # per half fiber
    "link_radius": 16.0,     # longest join considered (tracing voxels)
    "guard_r": 1.2,          # a bridge passing within this of a third fragment's point is refused
    "link_cos": 0.82,        # each end's tangent within about 35 deg of the join
    "link_lat": 1.5,         # lateral offset allowed: link_lat + 0.2 x gap
    "link_score": 0.6,       # joins below this score are refused
    "link_short": 3.0,       # ends closer than this only need antiparallel tangents (overlapping ends)
    "cross_weight": 0.7,     # other family's probability counted along a join
    "ctx_radius": 8.0,       # neighbors looked at for context (tracing voxels)
    "min_len": 10.0,         # shortest fiber kept (tracing voxels)
    "smooth_passes": 2,      # [1 2 1]/4 passes over interior points
}


# ---------------------------------------------------------------------------------------------- numba kernels

@njit(cache=True)
def _tri(S, z, y, x):
    """Trilinear sample of S at (z, y, x), clamped to the array."""
    Z, Y, X = S.shape
    z = min(max(z, 0.0), Z - 1.0)
    y = min(max(y, 0.0), Y - 1.0)
    x = min(max(x, 0.0), X - 1.0)
    z0 = min(int(z), Z - 2) if Z > 1 else 0
    y0 = min(int(y), Y - 2) if Y > 1 else 0
    x0 = min(int(x), X - 2) if X > 1 else 0
    fz, fy, fx = z - z0, y - y0, x - x0
    z1, y1, x1 = min(z0 + 1, Z - 1), min(y0 + 1, Y - 1), min(x0 + 1, X - 1)
    c00 = S[z0, y0, x0] * (1 - fx) + S[z0, y0, x1] * fx
    c01 = S[z0, y1, x0] * (1 - fx) + S[z0, y1, x1] * fx
    c10 = S[z1, y0, x0] * (1 - fx) + S[z1, y0, x1] * fx
    c11 = S[z1, y1, x0] * (1 - fx) + S[z1, y1, x1] * fx
    return (c00 * (1 - fy) + c01 * fy) * (1 - fz) + (c10 * (1 - fy) + c11 * fy) * fz


@njit(cache=True)
def _dir(D, k, z, y, x, rz, ry, rx):
    """Field direction at tracing-grid point (z, y, x): trilinear over the 8 neighbors of the field grid (k tracing
    voxels per field voxel, field voxel j centered at k j + (k - 1) / 2), each flipped to agree with the reference
    direction (rz, ry, rx). Returns a unit vector (or the reference when the field is 0 there)."""
    Z, Y, X = D.shape[0], D.shape[1], D.shape[2]
    h = (k - 1) / 2.0
    cz = min(max((z - h) / k, 0.0), Z - 1.0)
    cy = min(max((y - h) / k, 0.0), Y - 1.0)
    cx = min(max((x - h) / k, 0.0), X - 1.0)
    z0 = min(int(cz), max(Z - 2, 0))
    y0 = min(int(cy), max(Y - 2, 0))
    x0 = min(int(cx), max(X - 2, 0))
    fz, fy, fx = cz - z0, cy - y0, cx - x0
    oz = 0.0
    oy = 0.0
    ox = 0.0
    for dz in range(2):
        wz = fz if dz else 1 - fz
        iz = min(z0 + dz, Z - 1)
        for dy in range(2):
            wy = fy if dy else 1 - fy
            iy = min(y0 + dy, Y - 1)
            for dx in range(2):
                wx = fx if dx else 1 - fx
                ix = min(x0 + dx, X - 1)
                w = wz * wy * wx
                vz, vy, vx = D[iz, iy, ix, 0], D[iz, iy, ix, 1], D[iz, iy, ix, 2]
                if vz * rz + vy * ry + vx * rx < 0:
                    w = -w
                oz += w * vz
                oy += w * vy
                ox += w * vx
    n = math.sqrt(oz * oz + oy * oy + ox * ox)
    if n < 1e-6:
        return rz, ry, rx
    return oz / n, oy / n, ox / n


@njit(cache=True)
def _perp(dz, dy, dx):
    """Two unit vectors perpendicular to (dz, dy, dx) and to each other."""
    if abs(dz) < 0.9:
        az, ay, ax = 1.0, 0.0, 0.0
    else:
        az, ay, ax = 0.0, 0.0, 1.0
    # u = a x d
    uz = ay * dx - ax * dy
    uy = ax * dz - az * dx
    ux = az * dy - ay * dz
    n = math.sqrt(uz * uz + uy * uy + ux * ux)
    uz, uy, ux = uz / n, uy / n, ux / n
    vz = dy * ux - dx * uy
    vy = dx * uz - dz * ux
    vx = dz * uy - dy * uz
    return uz, uy, ux, vz, vy, vx


@njit(cache=True)
def _recenter(S, z, y, x, dz, dy, dx):
    """Move (z, y, x) to the ridge peak in the plane across (dz, dy, dx): one 3x3 hill-climb step, then a quadratic
    peak fit along each in-plane axis (offset clipped to half a voxel). Returns the point and S there."""
    uz, uy, ux, vz, vy, vx = _perp(dz, dy, dx)
    for _ in range(2):
        best = _tri(S, z, y, x)
        bi, bj = 0, 0
        for i in range(-1, 2):
            for j in range(-1, 2):
                if i == 0 and j == 0:
                    continue
                s = _tri(S, z + i * uz + j * vz, y + i * uy + j * vy, x + i * ux + j * vx)
                if s > best:
                    best, bi, bj = s, i, j
        if bi == 0 and bj == 0:
            break
        z += bi * uz + bj * vz
        y += bi * uy + bj * vy
        x += bi * ux + bj * vx
    s0 = _tri(S, z, y, x)
    sp = _tri(S, z + uz, y + uy, x + ux)
    sm = _tri(S, z - uz, y - uy, x - ux)
    den = sp - 2 * s0 + sm
    a = 0.0
    if den < -1e-6:
        a = min(max(0.5 * (sm - sp) / den, -0.5), 0.5)
    sp = _tri(S, z + vz, y + vy, x + vx)
    sm = _tri(S, z - vz, y - vy, x - vx)
    den = sp - 2 * s0 + sm
    b = 0.0
    if den < -1e-6:
        b = min(max(0.5 * (sm - sp) / den, -0.5), 0.5)
    z += a * uz + b * vz
    y += a * uy + b * vy
    x += a * ux + b * vx
    return z, y, x, _tri(S, z, y, x)


@njit(cache=True)
def _ridge_seeds(S, D, k, thr):
    """Voxels with S >= thr that are maxima of S in the plane across the field direction (8 samples at one voxel)."""
    Z, Y, X = S.shape
    cz, cy, cx = D.shape[0], D.shape[1], D.shape[2]
    out = np.empty((1024, 3), np.int32)
    n = 0
    r = 0.70710678
    for z in range(Z):
        for y in range(Y):
            for x in range(X):
                s = S[z, y, x]
                if s < thr:
                    continue
                iz, iy, ix = min(z // k, cz - 1), min(y // k, cy - 1), min(x // k, cx - 1)
                dz, dy, dx = D[iz, iy, ix, 0], D[iz, iy, ix, 1], D[iz, iy, ix, 2]
                if dz == 0 and dy == 0 and dx == 0:
                    continue
                uz, uy, ux, vz, vy, vx = _perp(dz, dy, dx)
                ok = True
                for m in range(8):
                    if m < 4:
                        a = 1.0 if m % 2 == 0 else -1.0
                        if m < 2:
                            pz, py, px = a * uz, a * uy, a * ux
                        else:
                            pz, py, px = a * vz, a * vy, a * vx
                    else:
                        a = 1.0 if m % 2 == 0 else -1.0
                        b = 1.0 if m < 6 else -1.0
                        pz, py, px = (a * uz + b * vz) * r, (a * uy + b * vy) * r, (a * ux + b * vx) * r
                    if _tri(S, z + pz, y + py, x + px) > s:
                        ok = False
                        break
                if ok:
                    if n == out.shape[0]:
                        bigger = np.empty((out.shape[0] * 2, 3), np.int32)
                        bigger[:n] = out[:n]
                        out = bigger
                    out[n, 0], out[n, 1], out[n, 2] = z, y, x
                    n += 1
    return out[:n]


@njit(cache=True)
def _half(S, D, k, cover, visit, start, g, z, y, x, dz, dy, dx, prm, buf):
    """Trace from (z, y, x) along (dz, dy, dx); points go to buf. visit holds a running step stamp per voxel; a
    voxel stamped by this fiber (stamp >= start) more than 8 steps ago means the trace came back on itself.
    Returns the count kept (trailing gap and contact steps dropped), a stop code (0 weak, 1 edge, 2 turn, 3 reached
    another fiber, 4 step limit, 5 loop, 6 wander: the chord over the last `wander_steps` steps is shorter than
    `wander_ratio` of them, as on a sheet-like plateau, and the last half window is dropped) and the next stamp."""
    Z, Y, X = S.shape
    low, gap_max, cos_turn, alpha, max_steps, touch_max = prm[1], int(prm[2]), prm[3], prm[4], int(prm[5]), int(prm[6])
    wwin, wrat = int(prm[7]), prm[8]
    n = 0
    good = 0
    gap = 0
    touch = 0
    code = 4
    for _ in range(max_steps):
        qz, qy, qx = z + dz, y + dy, x + dx
        if qz < 0 or qy < 0 or qx < 0 or qz > Z - 1 or qy > Y - 1 or qx > X - 1:
            code = 1
            break
        rz, ry, rx, s = _recenter(S, qz, qy, qx, dz, dy, dx)
        if s < low:
            gap += 1
            if gap > gap_max:
                code = 0
                break
        else:
            qz, qy, qx = rz, ry, rx
            gap = 0
        iz, iy, ix = int(qz + 0.5), int(qy + 0.5), int(qx + 0.5)
        if iz < Z and iy < Y and ix < X:
            st = visit[iz, iy, ix]
            if st >= start and st < g - 8:
                code = 5
                break
            visit[iz, iy, ix] = g
        g += 1
        if iz < Z and iy < Y and ix < X and cover[iz, iy, ix] > 0:
            touch += 1
            if touch > touch_max:
                code = 3
                break
        else:
            touch = 0
        fz, fy, fx = _dir(D, k, qz, qy, qx, dz, dy, dx)
        sz, sy, sx = qz - z, qy - y, qx - x
        sn = math.sqrt(sz * sz + sy * sy + sx * sx)
        if sn > 1e-6:
            sz, sy, sx = sz / sn, sy / sn, sx / sn
        else:
            sz, sy, sx = dz, dy, dx
        nz = alpha * fz + (1 - alpha) * sz
        ny = alpha * fy + (1 - alpha) * sy
        nx = alpha * fx + (1 - alpha) * sx
        nn = math.sqrt(nz * nz + ny * ny + nx * nx)
        nz, ny, nx = nz / nn, ny / nn, nx / nn
        if nz * dz + ny * dy + nx * dx < cos_turn:
            code = 2
            break
        buf[n, 0], buf[n, 1], buf[n, 2] = qz, qy, qx
        n += 1
        if wwin > 0 and n > wwin:
            cz, cy, cx = qz - buf[n - 1 - wwin, 0], qy - buf[n - 1 - wwin, 1], qx - buf[n - 1 - wwin, 2]
            if math.sqrt(cz * cz + cy * cy + cx * cx) < wrat * wwin:
                code = 6
                good = min(good, n - wwin // 2)
                break
        if gap == 0 and touch == 0:
            good = n
        z, y, x, dz, dy, dx = qz, qy, qx, nz, ny, nx
    return good, code, g


@njit(cache=True)
def _mark(cover, pts, fid, r):
    Z, Y, X = cover.shape
    k = int(math.ceil(r))
    r2 = r * r
    for i in range(pts.shape[0]):
        cz, cy, cx = int(pts[i, 0] + 0.5), int(pts[i, 1] + 0.5), int(pts[i, 2] + 0.5)
        for a in range(-k, k + 1):
            for b in range(-k, k + 1):
                for c in range(-k, k + 1):
                    z, y, x = cz + a, cy + b, cx + c
                    if 0 <= z < Z and 0 <= y < Y and 0 <= x < X:
                        dd = (z - pts[i, 0]) ** 2 + (y - pts[i, 1]) ** 2 + (x - pts[i, 2]) ** 2
                        if dd <= r2 and cover[z, y, x] == 0:
                            cover[z, y, x] = fid


@njit(cache=True)
def _trace_all(S, D, k, seeds, cover, prm, cover_r, min_pts):
    """Trace every uncovered seed, strongest first. Returns all points (N, 3), offsets (F + 1) and per-fiber stop
    codes (F, 2) for the start and the end."""
    cap = 1 << 16
    pts = np.empty((cap, 3), np.float64)
    offs = np.zeros(1024, np.int64)
    codes = np.zeros((1024, 2), np.int64)
    maxs = int(prm[5])
    fwd = np.empty((maxs + 1, 3), np.float64)
    bwd = np.empty((maxs + 1, 3), np.float64)
    nf = 0
    npt = 0
    visit = np.full(S.shape, -1, np.int32)
    g = 0
    for si in range(seeds.shape[0]):
        z, y, x = seeds[si, 0], seeds[si, 1], seeds[si, 2]
        if cover[z, y, x] != 0:
            continue
        iz, iy, ix = min(z // k, D.shape[0] - 1), min(y // k, D.shape[1] - 1), min(x // k, D.shape[2] - 1)
        dz, dy, dx = D[iz, iy, ix, 0], D[iz, iy, ix, 1], D[iz, iy, ix, 2]
        if dz == 0 and dy == 0 and dx == 0:
            continue
        sz, sy, sx, s = _recenter(S, float(z), float(y), float(x), dz, dy, dx)
        start = g
        visit[z, y, x] = g
        g += 1
        nfw, cf, g = _half(S, D, k, cover, visit, start, g, sz, sy, sx, dz, dy, dx, prm, fwd)
        nbw, cb, g = _half(S, D, k, cover, visit, start, g, sz, sy, sx, -dz, -dy, -dx, prm, bwd)
        m = nfw + nbw + 1
        if m < 2:
            cover[z, y, x] = -1       # a lone point: never seed here again; only cover > 0 stops a trace
            continue
        if npt + m > pts.shape[0]:
            bigger = np.empty((max(pts.shape[0] * 2, npt + m), 3), np.float64)
            bigger[:npt] = pts[:npt]
            pts = bigger
        if nf + 2 > offs.shape[0]:
            o2 = np.zeros(offs.shape[0] * 2, np.int64)
            o2[:nf + 1] = offs[:nf + 1]
            offs = o2
            c2 = np.zeros((codes.shape[0] * 2, 2), np.int64)
            c2[:nf] = codes[:nf]
            codes = c2
        j = npt
        for i in range(nbw - 1, -1, -1):
            pts[j] = bwd[i]
            j += 1
        pts[j, 0], pts[j, 1], pts[j, 2] = sz, sy, sx
        j += 1
        for i in range(nfw):
            pts[j] = fwd[i]
            j += 1
        fid = nf + 1
        _mark(cover, pts[npt:j], fid if m >= min_pts else -1, cover_r)
        codes[nf, 0], codes[nf, 1] = cb, cf
        npt = j
        nf += 1
        offs[nf] = npt
    return pts[:npt], offs[:nf + 1], codes[:nf]


@njit(cache=True)
def _sample(S, pts):
    out = np.empty(pts.shape[0], np.float64)
    for i in range(pts.shape[0]):
        out[i] = _tri(S, pts[i, 0], pts[i, 1], pts[i, 2])
    return out


@njit(cache=True)
def _eig_min_abs(hzz, hyy, hxx, hzy, hzx, hyx, mask):
    """Unit eigenvector of the eigenvalue nearest zero of each masked voxel's symmetric 3x3 Hessian (Jacobi
    rotations), and a tubularity value: the smaller magnitude of the two remaining eigenvalues if both are negative."""
    Z, Y, X = hzz.shape
    D = np.zeros((Z, Y, X, 3), np.float32)
    T = np.zeros((Z, Y, X), np.float32)
    for z in prange(Z):
        A = np.empty((3, 3))
        V = np.empty((3, 3))
        for y in range(Y):
            for x in range(X):
                if not mask[z, y, x]:
                    continue
                A[0, 0], A[1, 1], A[2, 2] = hzz[z, y, x], hyy[z, y, x], hxx[z, y, x]
                A[0, 1] = A[1, 0] = hzy[z, y, x]
                A[0, 2] = A[2, 0] = hzx[z, y, x]
                A[1, 2] = A[2, 1] = hyx[z, y, x]
                for i in range(3):
                    for j in range(3):
                        V[i, j] = 1.0 if i == j else 0.0
                for _ in range(12):
                    off = A[0, 1] ** 2 + A[0, 2] ** 2 + A[1, 2] ** 2
                    if off < 1e-18:
                        break
                    for p, q in ((0, 1), (0, 2), (1, 2)):
                        if abs(A[p, q]) < 1e-12:
                            continue
                        th = (A[q, q] - A[p, p]) / (2 * A[p, q])
                        t = (1.0 if th >= 0 else -1.0) / (abs(th) + math.sqrt(th * th + 1))
                        c = 1 / math.sqrt(t * t + 1)
                        s = t * c
                        for k in range(3):
                            akp, akq = A[k, p], A[k, q]
                            A[k, p] = c * akp - s * akq
                            A[k, q] = s * akp + c * akq
                        for k in range(3):
                            apk, aqk = A[p, k], A[q, k]
                            A[p, k] = c * apk - s * aqk
                            A[q, k] = s * apk + c * aqk
                        for k in range(3):
                            vkp, vkq = V[k, p], V[k, q]
                            V[k, p] = c * vkp - s * vkq
                            V[k, q] = s * vkp + c * vkq
                ev0, ev1, ev2 = A[0, 0], A[1, 1], A[2, 2]
                i0 = 0
                if abs(ev1) < abs(ev0):
                    i0 = 1
                if abs(ev2) < abs((ev0, ev1, ev2)[i0]):
                    i0 = 2
                D[z, y, x, 0], D[z, y, x, 1], D[z, y, x, 2] = V[0, i0], V[1, i0], V[2, i0]
                o1, o2 = (ev1, ev2) if i0 == 0 else ((ev0, ev2) if i0 == 1 else (ev0, ev1))
                if o1 < 0 and o2 < 0:
                    T[z, y, x] = min(-o1, -o2)
    return D, T


# ---------------------------------------------------------------------------------------------- fields

def _gauss(a, sigma, order=0):
    from scipy import ndimage
    return ndimage.gaussian_filter(a, sigma, order=order, mode="nearest", truncate=3.0)


def smooth(channel, sigma):
    return _gauss(channel.astype(np.float32), sigma)


def direction_field(S, dir_sigma=1.0, floor=20.0, pool=2):
    """Direction field (Cz, Cy, Cx, 3) of the smoothed tracing grid S: `pool` x mean pooling (2 by default; 1 is
    the full tracing grid, kept for comparison), then the Hessian at `dir_sigma` field voxels; the along-tube
    eigenvector where the pooled value is at least `floor`."""
    k = int(pool)
    Z, Y, X = (n // k for n in S.shape)
    C = S[:k * Z, :k * Y, :k * X].reshape(Z, k, Y, k, X, k).mean((1, 3, 5)).astype(np.float32)
    o = {"zz": (2, 0, 0), "yy": (0, 2, 0), "xx": (0, 0, 2), "zy": (1, 1, 0), "zx": (1, 0, 1), "yx": (0, 1, 1)}
    H = {k: _gauss(C, dir_sigma, v) for k, v in o.items()}
    D, T = _eig_min_abs(H["zz"], H["yy"], H["xx"], H["zy"], H["zx"], H["yx"], C >= floor)
    return D, T


# ---------------------------------------------------------------------------------------------- linking

def _tangent(p, at_end, k=5):
    q = p[-1] - p[max(0, len(p) - 1 - k)] if at_end else p[0] - p[min(len(p) - 1, k)]
    n = np.linalg.norm(q)
    return q / n if n > 0 else q


def hermite(a, ta, b, tb_in, step=1.0):
    """Points strictly between a and b on the cubic Hermite curve leaving a along ta and arriving at b along tb_in."""
    L = float(np.linalg.norm(b - a))
    n = max(1, int(math.ceil(L / step)))
    t = (np.arange(1, n) / n)[:, None]
    h00, h10, h01, h11 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t, -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
    return h00 * a + h10 * (L * ta) + h01 * b + h11 * (L * tb_in)


def link(frags, S, So, prm):
    """Score and accept joins between fragment ends. frags: list of (N, 3) arrays (tracing grid). Returns the list of
    accepted joins (i, end_i, j, end_j, score, bridge points, support, at_crossing) and the number of candidates
    that passed the score."""
    from scipy.spatial import cKDTree
    if len(frags) < 2:
        return [], 0
    ends, tans, owner = [], [], []
    for i, p in enumerate(frags):
        for e in (0, 1):
            ends.append(p[-1] if e else p[0])
            tans.append(_tangent(p, e))
            owner.append((i, e))
    ends, tans = np.array(ends), np.array(tans)
    # every fragment point (thinned) with its tangent, for context and for the crossing guard
    allp, allt, allf = [], [], []
    for i, p in enumerate(frags):
        sel = np.arange(0, len(p), 2)
        g = np.gradient(p, axis=0) if len(p) > 1 else np.zeros_like(p)
        g /= np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)
        allp.append(p[sel])
        allt.append(g[sel])
        allf.append(np.full(len(sel), i))
    allp, allt, allf = np.concatenate(allp), np.concatenate(allt), np.concatenate(allf)
    ptree = cKDTree(allp)
    # the crossing guard uses every point: with the thinned set a third fragment passing the bridge slightly out of
    # its plane could sit just over the guard radius from every sampled point and be missed
    gp = np.concatenate(frags)
    gf = np.concatenate([np.full(len(p), i) for i, p in enumerate(frags)])
    gtree = cKDTree(gp)
    pairs = cKDTree(ends).query_pairs(prm["link_radius"], output_type="ndarray")
    if not len(pairs):
        return [], 0
    a, b = pairs[:, 0], pairs[:, 1]
    keep = np.array([owner[i][0] != owner[j][0] for i, j in pairs])
    a, b = a[keep], b[keep]
    g = ends[b] - ends[a]
    L = np.linalg.norm(g, axis=1)
    gh = g / np.maximum(L, 1e-9)[:, None]
    ta, tb = tans[a], tans[b]
    c1 = (ta * gh).sum(1)
    c2 = -(tb * gh).sum(1)
    c3 = -(ta * tb).sum(1)
    lat_a = np.linalg.norm(g - (g * ta).sum(1)[:, None] * ta, axis=1)
    lat_b = np.linalg.norm(g - (g * tb).sum(1)[:, None] * tb, axis=1)
    lat = np.maximum(lat_a, lat_b)
    short = L < prm["link_short"]
    ok = (short & (c3 > prm["link_cos"])) | ((c1 > prm["link_cos"]) & (c2 > prm["link_cos"]) & (c3 > prm["link_cos"])
                                            & (lat <= prm["link_lat"] + 0.2 * L))
    cands = []
    for k in np.flatnonzero(ok):
        i, j = int(a[k]), int(b[k])
        pa, pb = ends[i], ends[j]
        br = hermite(pa, tans[i], pb, -tans[j])
        fi, fj = owner[i][0], owner[j][0]
        if len(br):
            # crossing guard: the bridge must not pass through another fragment of this family
            near_b = gtree.query_ball_point(br, prm["guard_r"])
            if any(int(gf[q]) not in (fi, fj) for qs in near_b for q in qs):
                continue
            own_b, oth_b = _sample(S, br), _sample(So, br)
            sup = np.maximum(own_b, prm["cross_weight"] * oth_b) / 255.0
            support = float(sup.mean())
            crossing = bool(prm["cross_weight"] * oth_b.mean() > own_b.mean())
        else:
            support = 1.0
            crossing = False
        mid = 0.5 * (pa + pb)
        near = ptree.query_ball_point(mid, prm["ctx_radius"])
        ctx, wsum = 0.0, 0.0
        best = {}
        for q in near:
            f = allf[q]
            if f in (fi, fj):
                continue
            dq = float(np.linalg.norm(allp[q] - mid))
            if f not in best or dq < best[f][0]:
                best[f] = (dq, q)
        for f, (dq, q) in best.items():
            w = 1.0 / (1.0 + dq)
            ctx += w * abs(float(allt[q] @ gh[k]))
            wsum += w
        ctx = ctx / wsum if wsum else 0.75
        geom = 0.5 * (max(c1[k], 0) + max(c2[k], 0)) if not short[k] else float(c3[k])
        score = 0.4 * geom + 0.25 * math.exp(-L[k] / 10.0) + 0.2 * support + 0.15 * ctx
        if score >= prm["link_score"]:
            cands.append((score, i, j, br, support, crossing))
    cands.sort(key=lambda c: -c[0])
    used = set()
    parent = list(range(len(frags)))

    def root(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u
    joins = []
    for score, i, j, br, support, crossing in cands:
        if i in used or j in used:
            continue
        fi, fj = owner[i][0], owner[j][0]
        ri, rj = root(fi), root(fj)
        if ri == rj:
            continue
        parent[ri] = rj
        used.update((i, j))
        joins.append((fi, owner[i][1], fj, owner[j][1], float(score), br, float(support), crossing))
    return joins, len(cands)


def assemble(frags, joins):
    """Chains of fragments joined end to end. Returns [(points, bridged mask, link scores, fragment count)]."""
    adj = {}
    for fi, ei, fj, ej, score, br, _, _ in joins:
        adj[(fi, ei)] = (fj, ej, score, br)
        adj[(fj, ej)] = (fi, ei, score, br[::-1])
    seen = set()
    out = []
    order = [i for i in range(len(frags)) if (i, 0) not in adj or (i, 1) not in adj] + list(range(len(frags)))
    for start in order:
        if start in seen:
            continue
        # orient so the free end (if any) is the head
        cur, head = start, (0 if (start, 0) not in adj else 1)
        pts, mask, scores, nfr = [], [], [], 0
        while True:
            seen.add(cur)
            p = frags[cur] if head == 0 else frags[cur][::-1]
            pts.append(p)
            mask.append(np.zeros(len(p), bool))
            nfr += 1
            tail = 1 - head
            nxt = adj.get((cur, tail))
            if nxt is None or nxt[0] in seen:
                break
            fj, ej, score, br = nxt
            if len(br):
                pts.append(br)
                mask.append(np.ones(len(br), bool))
            scores.append(score)
            cur, head = fj, ej
        out.append((np.concatenate(pts), np.concatenate(mask), scores, nfr))
    return out


def smooth_line(p, passes):
    p = p.copy()
    for _ in range(passes):
        if len(p) < 3:
            break
        p[1:-1] = 0.25 * p[:-2] + 0.5 * p[1:-1] + 0.25 * p[2:]
    return p


def length(p):
    return float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum()) if len(p) > 1 else 0.0


def confidence(S, p, bridged, scores, prm):
    """Heuristic confidence in [0, 1] and its parts."""
    s = _sample(S, p) / 255.0
    own = s[~bridged] if (~bridged).any() else s
    mean_p = float(own.mean())
    support = float((s * 255.0 >= prm["low"]).mean())
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    L = float(seg.sum())
    bfrac = float(seg[bridged[1:] | bridged[:-1]].sum() / L) if L > 0 else 0.0
    link_min = float(min(scores)) if scores else 1.0
    lf = 1.0 - math.exp(-L / 20.0)
    conf = mean_p * support * (0.5 + 0.5 * lf) * (1.0 - 0.5 * bfrac) * (0.75 + 0.25 * min(1.0, link_min))
    return float(min(max(conf, 0.0), 1.0)), {"mean_p": round(mean_p, 4), "support": round(support, 4),
                                             "bridged_fraction": round(bfrac, 4), "links": len(scores),
                                             "min_link_score": round(link_min, 4)}


# ---------------------------------------------------------------------------------------------- one volume

def trace_family(own, other, prm=None, say=None, smoothed=False):
    """Weft on one family: own and other are tracing-grid probability arrays (Z, Y, X), uint8 0..255 or float
    (already smoothed with prm["sigma"] when `smoothed`). Returns ([{"points": (N, 3) zyx tracing grid,
    "confidence": c, "parts": {...}}], timing and counts)."""
    prm = {**DEFAULTS, **(prm or {})}
    t = {}
    t0 = time.time()
    S = own if smoothed else smooth(own, prm["sigma"])
    So = other if smoothed else smooth(other, prm["sigma"])
    t["smooth_s"] = time.time() - t0
    t0 = time.time()
    k = int(prm["dir_pool"])
    D, _ = direction_field(S, prm["dir_sigma"], pool=k)
    t["direction_s"] = time.time() - t0
    t0 = time.time()
    seeds = _ridge_seeds(S, D, k, prm["seed"])
    if len(seeds):
        order = np.argsort(-S[seeds[:, 0], seeds[:, 1], seeds[:, 2]], kind="stable")
        seeds = np.ascontiguousarray(seeds[order])
    t["seeds_s"] = time.time() - t0
    t0 = time.time()
    cover = np.zeros(S.shape, np.int32)
    kprm = np.array([prm["seed"], prm["low"], prm["gap_steps"], math.cos(math.radians(prm["turn_deg"])),
                     prm["alpha"], prm["max_steps"], prm["contact_steps"], prm["wander_steps"], prm["wander_ratio"]],
                    np.float64)
    pts, offs, codes = _trace_all(S, D, k, seeds.reshape(-1, 3).astype(np.int32), cover, kprm, prm["cover_r"], 3)
    long_ = [i for i in range(len(offs) - 1) if offs[i + 1] - offs[i] >= 3]
    frags = [pts[offs[i]:offs[i + 1]] for i in long_]
    stops = np.bincount(codes[long_].ravel(), minlength=7) if long_ else np.zeros(7, int)
    t["trace_s"] = time.time() - t0
    t0 = time.time()
    joins, ncand = link(frags, S, So, prm)
    chains = assemble(frags, joins)
    t["link_s"] = time.time() - t0
    t0 = time.time()
    fibers = []
    for p, bridged, scores, nfr in chains:
        p = smooth_line(p, prm["smooth_passes"])
        if length(p) < prm["min_len"]:
            continue
        c, parts = confidence(S, p, bridged, scores, prm)
        parts["fragments"] = nfr
        fibers.append({"points": p, "confidence": c, "parts": parts, "bridged": bridged})
    t["finish_s"] = time.time() - t0
    info = {"seeds": int(len(seeds)), "fragments": len(frags),
            "fragment_ends": dict(zip(("weak", "edge", "turn", "fiber", "limit", "loop", "wander"),
                                      (int(v) for v in stops))),
            "join_candidates": ncand, "joins": len(joins), "joins_at_crossings": sum(j[7] for j in joins),
            "fibers": len(fibers), **{k: round(v, 2) for k, v in t.items()}}
    if say:
        say(json.dumps(info))
    return fibers, info


def trace_volume(pooled, prm=None, say=None):
    """Both families of a (2, Z, Y, X) tracing-grid array (channel 0 V, channel 1 H). Returns [(family, fiber)]."""
    p = {**DEFAULTS, **(prm or {})}
    t0 = time.time()
    sm = [smooth(pooled[0], p["sigma"]), smooth(pooled[1], p["sigma"])]   # each channel once, shared by both families
    t_s = round(time.time() - t0, 2)
    out, infos = [], {}
    for fam, c in (("V", 0), ("H", 1)):
        fibers, info = trace_family(sm[c], sm[1 - c], prm, say, smoothed=True)
        info["smooth_s"] = t_s / 2
        out += [(fam, f) for f in fibers]
        infos[fam] = info
    return out, infos


# ---------------------------------------------------------------------------------------------- data and frames

def load_pooled(blocks, lo2, hi2, shape2, block=512):
    """(2, Z, Y, X) uint8 tracing grid over level coordinates [lo2, hi2) (zyx, even), from pooled block files
    blocks/pooled/Z_Y_X.blosc (absent blocks are zero)."""
    import numcodecs
    codec = numcodecs.Blosc()
    lo2, hi2, shape2 = np.asarray(lo2), np.asarray(hi2), np.asarray(shape2)
    assert (lo2 % 2 == 0).all()
    lo, hi = lo2 // 2, (hi2 + 1) // 2
    out = np.zeros((2,) + tuple(int(v) for v in hi - lo), np.uint8)
    rng = [range((int(a) // block) * block, int(b), block) for a, b in zip(lo2, hi2)]
    for z in rng[0]:
        for y in rng[1]:
            for x in rng[2]:
                k = np.array([z, y, x])
                f = Path(blocks) / "pooled" / f"{z}_{y}_{x}.blosc"
                if not f.exists():
                    continue
                pshape = np.minimum(block, shape2 - k) // 2
                arr = np.frombuffer(codec.decode(f.read_bytes()), np.uint8).reshape((2,) + tuple(int(v) for v in pshape))
                k2 = k // 2
                s0, s1 = np.maximum(k2, lo), np.minimum(k2 + pshape, hi)
                if (s1 > s0).all():
                    out[(slice(None),) + tuple(slice(a - b, c - b) for a, b, c in zip(s0, lo, s1))] = \
                        arr[(slice(None),) + tuple(slice(a - b, c - b) for a, b, c in zip(s0, k2, s1))]
    return out


def load_native(blocks, lo2, hi2, shape2, block=512):
    """(2, Z, Y, X) uint8 native probabilities over [lo2, hi2) from blocks/native/ (absent blocks zero)."""
    import numcodecs
    codec = numcodecs.Blosc()
    lo2, hi2, shape2 = np.asarray(lo2), np.asarray(hi2), np.asarray(shape2)
    out = np.zeros((2,) + tuple(int(v) for v in hi2 - lo2), np.uint8)
    rng = [range((int(a) // block) * block, int(b), block) for a, b in zip(lo2, hi2)]
    for z in rng[0]:
        for y in rng[1]:
            for x in rng[2]:
                k = np.array([z, y, x])
                f = Path(blocks) / "native" / f"{z}_{y}_{x}.blosc"
                if not f.exists():
                    continue
                bshape = np.minimum(block, shape2 - k)
                arr = np.frombuffer(codec.decode(f.read_bytes()), np.uint8).reshape((2,) + tuple(int(v) for v in bshape))
                s0, s1 = np.maximum(k, lo2), np.minimum(k + bshape, hi2)
                out[(slice(None),) + tuple(slice(a - b, c - b) for a, b, c in zip(s0, lo2, s1))] = \
                    arr[(slice(None),) + tuple(slice(a - b, c - b) for a, b, c in zip(s0, k, s1))]
                del arr
    return out


def tgrid_to_l0(p_zyx, origin2_zyx, level):
    """Tracing-grid (z, y, x) points to XYZ level-0 voxels: level coordinate 2 t + 0.5 + origin, times 2^level."""
    q = (2.0 * np.asarray(p_zyx, np.float64) + 0.5 + np.asarray(origin2_zyx, np.float64)) * (2 ** int(level))
    return q[:, ::-1].copy()


def crop_args(c):
    """--crop-l0 X0 X1 Y0 Y1 Z0 Z1 -> lo, hi (xyz)."""
    c = [float(v) for v in c]
    return np.array(c[0::2]), np.array(c[1::2])


def bridge_spans(run, points, bridged):
    """[[i0, i1], ...] inclusive index ranges of `run` (a clipped or trimmed piece of the polyline `points`) whose
    points lie on a join's bridge (`bridged`, one flag per row of `points`). A point that clipping added (a face
    crossing, not a row of `points`) takes its inner neighbor's flag."""
    if not bridged.any():
        return []
    key = lambda r: np.ascontiguousarray(r, np.float64).tobytes()
    flags = {key(r): bool(b) for r, b in zip(points, bridged)}
    raw = [flags.get(key(r)) for r in run]
    for i in (0, len(run) - 1):
        if raw[i] is None:
            j = 1 if i == 0 else len(run) - 2
            raw[i] = bool(raw[j]) if 0 <= j < len(run) and raw[j] is not None else False
    spans, start = [], None
    for i, f in enumerate(raw):
        if f and start is None:
            start = i
        if not f and start is not None:
            spans.append([start, i - 1])
            start = None
    if start is not None:
        spans.append([start, len(run) - 1])
    return spans


def clip_runs(p, lo, hi):
    sys.path.insert(0, str(HERE))
    from afv_stitch import clip
    return [r for inside, r in clip(p, lo, hi) if inside]


# ---------------------------------------------------------------------------------------------- AFV writer

SCHEMA = """
PRAGMA application_id=0x56434643;
PRAGMA user_version=1;
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE fibers(id INTEGER PRIMARY KEY,name TEXT NOT NULL,family TEXT NOT NULL,
 point_count INTEGER NOT NULL CHECK(point_count>=2),length REAL NOT NULL,
 min_x REAL NOT NULL,max_x REAL NOT NULL,min_y REAL NOT NULL,max_y REAL NOT NULL,
 min_z REAL NOT NULL,max_z REAL NOT NULL,annotation TEXT NOT NULL);
CREATE TABLE blocks(id INTEGER PRIMARY KEY,fiber_id INTEGER NOT NULL REFERENCES fibers(id),
 first_segment INTEGER NOT NULL,points BLOB NOT NULL,UNIQUE(fiber_id,first_segment));
CREATE VIRTUAL TABLE block_bounds USING rtree(id,min_x,max_x,min_y,max_y,min_z,max_z);
CREATE TABLE weft_fibers(id INTEGER PRIMARY KEY REFERENCES fibers(id),confidence REAL NOT NULL,parts TEXT NOT NULL);
"""
# The first five statements are the AFV v1 layout (VC3D fiber collection) that villa's import_afv.py reads; the
# weft_fibers table is ours (per-fiber confidence and its parts), and the reader never looks at it. The same values
# are in each fiber's annotation under "weft", which villa's reader keeps as the fiber's annotation.


def _dumps(v):
    return json.dumps(v, separators=(",", ":"), allow_nan=False)


def _bounds(q):
    return tuple(float(v) for pair in zip(q.min(0), q.max(0)) for v in pair)


def write_afv(fibers, out, frame, source, provenance, voxel_um_l0, weft_table=True):
    """fibers: [(family 'V'/'H', (N, 3) XYZ L0 float64, extra annotation dict or None)].

    A separate writer from afv_stitch.write_afv on purpose: afv_stitch's imports the schema from Qual's
    avf_spline_generator package (Weft must run without it) and takes a stitch plan. This one adds the weft_fibers table and the
    per-fiber "weft" annotation, and copies a given frame (--frame-from) so crop files match the stitched V2 file."""
    out = Path(out)
    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(out))
    schema = SCHEMA if weft_table else SCHEMA.split("CREATE TABLE weft_fibers")[0]
    db.executescript(schema)
    root = {"type": "vc3d_fiber_collection", "version": 1, "scale": 1, **frame, "coordinate_order": "XYZ",
            "coordinate_units": "voxel", "voxel_size_mm": voxel_um_l0 / 1000}
    count = npts = nblk = 0
    for fam, q, extra in fibers:
        q = np.asarray(q, "<f8")
        L = length(q)
        if len(q) < 2 or L <= 0 or not np.isfinite(q).all():
            continue
        count += 1
        ann = {"type": "vc3d_fiber", "version": 1, "sequence": count, "filename": f"fiber_{count}.json",
               "hv_classification": {"manual_tag": fam},
               "classification_source": "model_prediction_family_locked_tracing",
               "control_points": [q[0].tolist(), q[-1].tolist()], "length_voxels": L,
               "length_mm": L * voxel_um_l0 / 1000}
        if extra:
            ann.update(extra)
        db.execute("INSERT INTO fibers VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (count, ann["filename"], fam, len(q), L, *_bounds(q), _dumps(ann)))
        if weft_table and extra and "weft" in extra:
            w = extra["weft"]
            db.execute("INSERT INTO weft_fibers VALUES(?,?,?)", (count, w["confidence"], _dumps(w)))
        for first in range(0, len(q) - 1, 256):
            blk = np.ascontiguousarray(q[first:first + 257])
            nblk += 1
            db.execute("INSERT INTO blocks VALUES(?,?,?,?)", (nblk, count, first, blk.tobytes()))
            db.execute("INSERT INTO block_bounds VALUES(?,?,?,?,?,?,?)", (nblk, *_bounds(blk)))
        npts += len(q)
    meta = {"complete": True, "uuid": str(uuid.uuid4()), "root": root, "frame": frame,
            "geometry": "XYZ binary64 little-endian native L0", "block_segments": 256, "source": source,
            "provenance": provenance, "fiber_count": count, "point_count": npts, "block_count": nblk,
            "minimum_length_mm": 0.0}
    db.executemany("INSERT INTO metadata VALUES(?,?)", [(k, _dumps(v)) for k, v in meta.items()])
    db.execute("CREATE INDEX fibers_length ON fibers(length DESC,id)")
    db.commit()
    assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert db.execute("SELECT rtreecheck('block_bounds')").fetchone()[0] == "ok"
    db.close()
    return {"fibers": count, "points": npts, "blocks": nblk}


def read_afv(path, lo=None, hi=None):
    """[(id, family, (N, 3) xyz, annotation)] of the fibers of an AFV file, only those with a block meeting the box
    [lo, hi) (xyz) when given (through the rtree)."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    if lo is None:
        ids = [r[0] for r in db.execute("SELECT id FROM fibers")]
    else:
        ids = [r[0] for r in db.execute(
            "SELECT DISTINCT b.fiber_id FROM block_bounds r JOIN blocks b ON b.id = r.id WHERE r.max_x >= ? AND "
            "r.min_x < ? AND r.max_y >= ? AND r.min_y < ? AND r.max_z >= ? AND r.min_z < ?",
            tuple(float(v) for v in (lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])))]
    out = []
    for fid in sorted(ids):
        fam, ann = db.execute("SELECT family, annotation FROM fibers WHERE id = ?", (fid,)).fetchone()
        parts = [np.frombuffer(b, "<f8").reshape(-1, 3) for (b,) in
                 db.execute("SELECT points FROM blocks WHERE fiber_id = ? ORDER BY first_segment", (fid,))]
        p = np.concatenate([parts[0]] + [q[1:] for q in parts[1:]]) if parts else np.zeros((0, 3))
        out.append((fid, fam, p, json.loads(ann)))
    db.close()
    return out


def frame_of(afv):
    db = sqlite3.connect(f"file:{afv}?mode=ro", uri=True)
    meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM metadata")}
    db.close()
    return meta["frame"], meta


# ---------------------------------------------------------------------------------------------- exterior

def exterior_trim(p_xyz, mask, cell_l0, min_pts=2):
    """Pieces of a polyline (XYZ L0) outside the exterior mask (zyx cells of `cell_l0` L0 voxels); points in an
    exterior cell are removed and the runs between them kept."""
    idx = np.floor(p_xyz[:, ::-1] / cell_l0).astype(int)
    idx = np.clip(idx, 0, np.array(mask.shape) - 1)
    bad = mask[idx[:, 0], idx[:, 1], idx[:, 2]]
    if not bad.any():
        return [p_xyz]
    runs, cur = [], []
    for i, b in enumerate(bad):
        if b:
            if len(cur) >= min_pts:
                runs.append(p_xyz[cur])
            cur = []
        else:
            cur.append(i)
    if len(cur) >= min_pts:
        runs.append(p_xyz[cur])
    return runs


def exterior(volume, out, reach=16):
    """CT exterior of the scan (afv_stitch.exterior_mask on the public CT), saved with its cell size in L0 voxels."""
    sys.path.insert(0, str(HERE))
    from afv_stitch import exterior_mask
    plan = {"ct": volume["ct"], "level": volume["level"]}
    mask, cell = exterior_mask(plan, reach=reach)
    np.savez_compressed(out, mask=mask, cell_l0=cell * 2 ** int(volume["level"]))
    return int(mask.sum()), mask.shape, cell


# ---------------------------------------------------------------------------------------------- commands

def run_crop(a):
    vol = json.loads(Path(a.volume).read_text())
    level, shape2 = int(vol["level"]), np.array(vol["shape_zyx"])
    f = 2 ** level
    lo_xyz, hi_xyz = crop_args(a.crop_l0)
    lo2 = (lo_xyz[::-1] / f).astype(int)
    hi2 = (hi_xyz[::-1] / f).astype(int)
    rlo = np.maximum(lo2 - a.halo, 0) // 2 * 2
    rhi = np.minimum(hi2 + a.halo, shape2)
    t0 = time.time()
    pooled = load_pooled(a.blocks, rlo, rhi, shape2, block=int(vol.get("block", 512)))
    t_load = time.time() - t0
    prm = json.loads(a.params) if a.params else {}
    t0 = time.time()
    traced, infos = trace_volume(pooled, prm, say=print)
    t_trace = time.time() - t0
    mask = cell = None
    if a.exterior:
        z = np.load(a.exterior)
        mask, cell = z["mask"], float(z["cell_l0"])
    fibers, trimmed = [], 0
    for fam, fb in traced:
        q = tgrid_to_l0(fb["points"], rlo, level)
        pieces, cut = [q], False
        if mask is not None:
            pieces = exterior_trim(q, mask, cell)
            cut = len(pieces) != 1 or len(pieces[0]) != len(q)
            trimmed += cut
            if cut:     # inner pieces are kept when long enough (min_len in tracing voxels, 2^(level+1) L0 each)
                pieces = [r for r in pieces if length(r) >= (prm.get("min_len", DEFAULTS["min_len"]) * 2 * f)]
        for piece in pieces:
            for r in clip_runs(piece, lo_xyz, hi_xyz):
                if len(r) >= 2:
                    w = {"confidence": round(fb["confidence"], 4), **fb["parts"], "exterior_trimmed": bool(cut),
                         "bridges": bridge_spans(r, q, fb["bridged"])}
                    fibers.append((fam, r, {"classification_source": "weft_family_locked_tracing", "weft": w}))
    if a.frame_from:
        frame, _ = frame_of(a.frame_from)
    else:
        frame = {"coordinate_base_shape_zyx": [int(v) * f for v in shape2], "vc_open_data_source_coordinate_level": 0,
                 "vc_open_data_source_coordinate_scale_factor": 1,
                 "vc_open_data_source_original_resolution": vol["voxel_um"] / f,
                 "vc_open_data_coordinate_space": vol["coordinate_space"],
                 "vc_open_data_source_path": vol["ct"].rsplit("/", 1)[0]}
    prov = {"tracer": "weft_trace.py (Scrolls, AutoPipeline 0.1.10)", "params": {**DEFAULTS, **prm},
            "probabilities": f"SharpMeow/afv-fiber-probabilities {vol['scan']} pooled (Qualzz20/afv_fiber_9um_v2)",
            "crop_l0_xyz": [float(v) for v in a.crop_l0], "read_level_lo_zyx": rlo.tolist(),
            "read_level_hi_zyx": rhi.tolist(), "families": infos, "exterior_trimmed_fibers": trimmed}
    summ = write_afv(fibers, a.out, frame, "Weft (Scrolls) on AFV V2 probabilities", prov,
                     float(frame["vc_open_data_source_original_resolution"]))
    info = {"out": a.out, "load_s": round(t_load, 1), "trace_s": round(t_trace, 1), **summ, "families": infos,
            "exterior_trimmed_fibers": trimmed, "tracing_grid_zyx": list(pooled.shape[1:])}
    Path(str(a.out) + ".json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info))
    return 0


def run_v2crop(a):
    lo, hi = crop_args(a.crop_l0)
    frame, meta = frame_of(a.afv)
    fibers = []
    src = read_afv(a.afv, lo, hi)
    for fid, fam, p, ann in src:
        for r in clip_runs(p, lo, hi):
            if len(r) >= 2:
                fibers.append((fam, r, {"v2_fiber_id": fid}))
    prov = {"of": Path(a.afv).name, "crop_l0_xyz": [float(v) for v in a.crop_l0],
            "note": "V2 fibers (Qual's AFV V2 model and AVF_SPLINE_GENERATOR, Apache-2.0) clipped to the crop",
            "source_fibers_touching": len(src)}
    summ = write_afv(fibers, a.out, frame, meta.get("source", "AFV V2"), prov,
                     float(frame["vc_open_data_source_original_resolution"]), weft_table=False)
    print(json.dumps({"out": a.out, **summ, "source_fibers_touching": len(src)}))
    return 0


def run_exterior(a):
    vol = json.loads(Path(a.volume).read_text())
    n, shape, cell = exterior(vol, a.out)
    print(json.dumps({"out": a.out, "exterior_cells": n, "shape_zyx": list(shape), "cell_level_voxels": cell}))
    return 0


def native_index(p_xyz, f, lo2_zyx, shape_zyx):
    """(N, 3) zyx indices, relative to `lo2_zyx`, of the native level voxel nearest each XYZ L0 point. An integer
    level coordinate (L0 / f) is a voxel center (the stitched V2 files' convention, L0 = f x level coordinate), so the
    nearest voxel is the rounded coordinate, not the floor."""
    v = np.rint(np.asarray(p_xyz, np.float64)[:, ::-1] / f - np.asarray(lo2_zyx)).astype(int)
    return np.clip(v, 0, np.array(shape_zyx) - 1)


def run_stats(a):
    """Sanity numbers per AFV inside the crop: fibers, length quantiles (um), share of points whose own-family native
    probability is at least 0.5 (nearest native voxel), and an optional PNG of maximum-intensity projections with the
    fibers drawn. With --min-len-um, fibers shorter than that inside the crop are left out of every number, for every
    file alike (Weft drops fragments under min_len before clipping; the V2 crop files keep every clipped piece)."""
    vol = json.loads(Path(a.volume).read_text())
    level, shape2 = int(vol["level"]), np.array(vol["shape_zyx"])
    f = 2 ** level
    lo, hi = crop_args(a.crop_l0)
    lo2, hi2 = (lo[::-1] / f).astype(int), (hi[::-1] / f).astype(int)
    nat = load_native(a.blocks, lo2, hi2, shape2, block=int(vol.get("block", 512))) if a.blocks else None
    res = {"min_len_um": a.min_len_um or 0.0}
    draw = []
    for path in a.afv:
        fib = read_afv(path, lo, hi)
        um = float(vol["voxel_um"]) / f
        if a.min_len_um:    # the same minimum length for every file, so fiber counts and lengths compare like for like
            fib = [t for t in fib if length(t[2]) * um >= a.min_len_um]
        L = np.array([length(p) * um for _, _, p, _ in fib]) if fib else np.zeros(0)
        r = {"fibers": len(fib), "V": sum(fm == "V" for _, fm, _, _ in fib), "H": sum(fm == "H" for _, fm, _, _ in fib),
             "points": int(sum(len(p) for _, _, p, _ in fib)), "total_mm": round(float(L.sum()) / 1000, 2)}
        if len(L):
            r["length_um_q"] = {q: round(float(np.percentile(L, q)), 1) for q in (10, 25, 50, 75, 90, 99)}
            r["length_um_max"] = round(float(L.max()), 1)
            r["n_ge_1mm"] = int((L >= 1000).sum())
        if nat is not None and fib:
            hits = tot = 0
            for _, fm, p, _ in fib:
                v = native_index(p, f, lo2, nat.shape[1:])
                pr = nat[0 if fm == "V" else 1][v[:, 0], v[:, 1], v[:, 2]]
                hits += int((pr >= 128).sum())
                tot += len(pr)
            r["share_points_own_p_ge_0.5"] = round(hits / tot, 4)
        conf = [ann.get("weft", {}).get("confidence") for _, _, _, ann in fib if "weft" in ann]
        if conf:
            c = np.array(conf)
            r["confidence_q"] = {q: round(float(np.percentile(c, q)), 3) for q in (10, 50, 90)}
        res[path] = r
        draw.append((path, fib))
    if a.png and nat is not None:
        render(a.png, nat, lo2, f, draw, slab=a.slab)
        res["png"] = a.png
    print(json.dumps(res, indent=1))
    return 0


def render(png, nat, lo2, f, draw, slab=24):
    """Side-by-side maximum projections along y over a slab of `slab` level voxels at the crop's middle (V and H
    probabilities in two colors) with each AFV's fiber segments inside the slab drawn over them, one panel per file
    (V fibers orange, H fibers cyan)."""
    from PIL import Image, ImageDraw
    y0 = nat.shape[2] // 2 - slab // 2
    v = nat[0][:, y0:y0 + slab].max(axis=1).astype(np.float32)
    h = nat[1][:, y0:y0 + slab].max(axis=1).astype(np.float32)
    base = np.stack([h * 0.55, v * 0.45 + h * 0.2, v * 0.55], -1).clip(0, 255).astype(np.uint8)  # z by x
    panels = []
    colors = {"V": (255, 170, 60), "H": (90, 230, 255)}
    for path, fib in draw:
        im = Image.fromarray(base).convert("RGB")
        d = ImageDraw.Draw(im)
        for _, fam, p, _ in fib:
            q = p[:, ::-1] / f - lo2
            inside = (q[:, 1] >= y0) & (q[:, 1] < y0 + slab)
            for i in range(len(q) - 1):
                if inside[i] and inside[i + 1]:
                    d.line([(float(q[i, 2]), float(q[i, 0])), (float(q[i + 1, 2]), float(q[i + 1, 0]))],
                           fill=colors.get(fam, (255, 255, 255)), width=1)
        d.text((4, 4), Path(path).name, fill=(255, 255, 255))
        panels.append(im)
    W = sum(p.width for p in panels) + 8 * (len(panels) - 1)
    out = Image.new("RGB", (W, panels[0].height), (20, 20, 20))
    x = 0
    for p in panels:
        out.paste(p, (x, 0))
        x += p.width + 8
    out.save(png)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crop")
    c.add_argument("--volume", required=True)
    c.add_argument("--blocks", required=True)
    c.add_argument("--crop-l0", nargs=6, required=True, metavar=("X0", "X1", "Y0", "Y1", "Z0", "Z1"))
    c.add_argument("--out", required=True)
    c.add_argument("--halo", type=int, default=64, help="level voxels read around the crop")
    c.add_argument("--exterior")
    c.add_argument("--frame-from", help="AFV whose frame metadata to copy (the stitched V2 file)")
    c.add_argument("--params", help="JSON overrides of DEFAULTS")
    v = sub.add_parser("v2crop")
    v.add_argument("--afv", required=True)
    v.add_argument("--crop-l0", nargs=6, required=True)
    v.add_argument("--out", required=True)
    e = sub.add_parser("exterior")
    e.add_argument("--volume", required=True)
    e.add_argument("--out", required=True)
    s = sub.add_parser("stats")
    s.add_argument("--afv", nargs="+", required=True)
    s.add_argument("--volume", required=True)
    s.add_argument("--blocks")
    s.add_argument("--crop-l0", nargs=6, required=True)
    s.add_argument("--png")
    s.add_argument("--slab", type=int, default=24, help="level voxels of y projected in the PNG")
    s.add_argument("--min-len-um", type=float, default=0.0, help="leave out fibers shorter than this inside the crop")
    a = p.parse_args(argv)
    return {"crop": run_crop, "v2crop": run_v2crop, "exterior": run_exterior, "stats": run_stats}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
