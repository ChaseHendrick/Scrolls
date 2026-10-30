"""Synthetic tifxyz surfaces for the self-intersection backends (kit/selfcross.py): tests/test_selfcross.py and the
parity check against villa's vc_tifxyz_selfcross (scripts/selfcross/parity.py) use the same ones.

Each fixture is (grid, mask): a float32 (rows, cols, 3) grid of x, y, z (-1 marks an invalid cell, as VC3D writes
them) and a uint8 mask.tif or None. NAMED are fixed shapes, each for one rule of the census or of VC3D's loader;
random(n) adds crumpled sheets with folds, holes and masks from a seeded generator.

VILLA counts the named ones as villa's vc_tifxyz_selfcross at 7154682e1 (the archived Linux AppImage, VC3D-7154682
2026-10-28, sha256 93f52efb...) counted them: transverse, coplanar and grazing contacts on diagonals 0 and 1.
"""

import json
import math

import numpy as np

GAP = 4     # grid rows between the two sheets of a two-sheet fixture: further apart than the adjacency exclusion

# name -> ((transverse d0, d1), (coplanar d0, d1), (grazing d0, d1)) from villa's tool
VILLA = {
    "flat": ((0, 0), (0, 0), (0, 0)),
    "driven_through": ((33, 35), (0, 0), (0, 0)),
    "pressed_coplanar": ((0, 0), (765, 765), (0, 0)),
    "edge_on": ((0, 0), (0, 0), (52, 52)),
    "fold_through_self": ((78, 78), (0, 0), (0, 0)),
    "z_nonpositive": ((18, 19), (0, 0), (0, 0)),
    "nan_cells": ((25, 27), (0, 0), (0, 0)),
    "x_minus_one": ((52, 53), (0, 0), (0, 0)),
    "mask_same_size": ((15, 15), (0, 0), (0, 0)),
    "mask_decimated_2x": ((13, 15), (0, 0), (0, 0)),
    "discontinuity": ((0, 0), (0, 0), (42, 29)),
}


def blank(h, w):
    return np.full((h, w, 3), -1.0, np.float32)


def plane(P, r0, rows, cols, z, dx=0.0):
    for v in range(rows):
        for u in range(cols):
            P[r0 + v, u] = (4 * u + dx, 4 * v, z)


def named():
    out = {}
    P = blank(12, 16)
    plane(P, 0, 12, 16, 5.0)
    out["flat"] = (P, None)
    # a second sheet in the same grid, tilted and driven through the first
    P = blank(10 + GAP + 10, 12)
    plane(P, 0, 10, 12, 20.0)
    for v in range(10):
        for u in range(12):
            P[10 + GAP + v, u] = (4 * u + 1.7 + 0.3 * v, 4 * v + 0.9, 20.0 - 9.0 + 2.0 * u)
    out["driven_through"] = (P, None)
    # two sheets pressed flat on each other: coplanar contacts, no crossing
    P = blank(8 + GAP + 8, 10)
    plane(P, 0, 8, 10, 5.0)
    plane(P, 8 + GAP, 8, 10, 5.0, dx=1.3)
    out["pressed_coplanar"] = (P, None)
    # a sheet standing on the other's surface edge-on: grazing contacts
    P = blank(8 + GAP + 8, 10)
    plane(P, 0, 8, 10, 5.0)
    for v in range(8):
        for u in range(10):
            P[8 + GAP + v, u] = (4 * u, 4 * v, 5.0 + 4.0 * u)
    out["edge_on"] = (P, None)
    # one connected sheet folded back through itself
    H, W = 40, 14
    P = np.zeros((H, W, 3), np.float32)
    for v in range(H):
        t = v / (H - 1) * math.pi * 1.15
        for u in range(W):
            P[v, u] = (60 * math.sin(t) + 0.4 * u, 4.0 * u,
                       30 + 60 * (1 - math.cos(t)) * 0.5 + 0.9 * u - 1.6 * v * (v > 20))
    out["fold_through_self"] = (P, None)
    # the crossing with part of it at z <= 0 (VC3D invalidates those cells), and with NaN cells
    base = out["driven_through"][0]
    P = base.copy()
    P[10 + GAP:10 + GAP + 4, :, 2] -= 40.0
    out["z_nonpositive"] = (P, None)
    P = base.copy()
    P[10 + GAP + 2, 3:6, 0] = np.nan
    P[10 + GAP + 5, 7, 2] = np.nan
    out["nan_cells"] = (P, None)
    # x = -1 with z > 0: VC3D's loader keeps the cell (only z <= 0 and the mask invalidate)
    P = base.copy()
    P[10 + GAP + 3, 4:9, 0] = -1.0
    out["x_minus_one"] = (P, None)
    # masks: the grid's size, and twice it (a cell survives only when its whole 2 x 2 block passes)
    m = np.full(base.shape[:2], 255, np.uint8)
    m[10 + GAP:10 + GAP + 5, 2:8] = 0
    out["mask_same_size"] = (base, m)
    m2 = np.full((base.shape[0] * 2, base.shape[1] * 2), 255, np.uint8)
    m2[2 * (10 + GAP) + 3, 9] = 254
    m2[2 * (10 + GAP + 6):2 * (10 + GAP + 8), 0:24] = 0
    out["mask_decimated_2x"] = (base, m2)
    # a quad across a grid discontinuity: maxedge drops it
    P = blank(6 + GAP + 6, 8)
    plane(P, 0, 6, 8, 10.0)
    for v in range(6):
        for u in range(8):
            P[6 + GAP + v, u] = (4 * u + 0.5, 4 * v + 0.5, 4.0 + 3.0 * u)
    P[6 + GAP + 2, 3] = (500.0, 500.0, 500.0)
    out["discontinuity"] = (P, None)
    return out


def random(n, seed=20261030):
    """n crumpled sheets: smooth random height fields, most with a flap folded back through the rest, with holes,
    some with a row at z <= 0 and some with a mask."""
    rng = np.random.default_rng(seed)
    out = {}
    for i in range(n):
        H, W = int(rng.integers(20, 90)), int(rng.integers(20, 90))
        vv, uu = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
        P = np.zeros((H, W, 3), np.float32)
        a = rng.uniform(5, 40, 3)
        f = rng.uniform(0.03, 0.25, 6)
        ph = rng.uniform(0, 6.3, 6)
        P[..., 0] = 3.0 * uu + a[0] * np.sin(f[0] * vv + ph[0]) * np.cos(f[1] * uu + ph[1])
        P[..., 1] = 3.0 * vv + a[1] * np.sin(f[2] * uu + ph[2])
        P[..., 2] = (50 + a[2] * np.sin(f[3] * uu + ph[3]) * np.sin(f[4] * vv + ph[4])
                     + 25 * np.sin(f[5] * (uu + vv) + ph[5]))
        if rng.random() < 0.6:
            r = int(rng.integers(H // 3, 2 * H // 3))
            k = rng.uniform(0.5, 1.5)
            P[r:, :, 0] = P[r, :, 0][None] - k * (P[r:, :, 0] - P[r, :, 0][None]) * rng.uniform(0.3, 1.0)
            P[r:, :, 2] -= k * 2.5 * (vv[r:] - r)
        P += rng.normal(0, 0.3, P.shape).astype(np.float32)
        P[rng.random((H, W)) < rng.uniform(0, 0.08)] = -1.0
        if rng.random() < 0.3:
            P[int(rng.integers(0, H)), :, 2] = -3.0
        mask = None
        if rng.random() < 0.3:
            mask = np.where(rng.random((H, W)) < 0.05, 0, 255).astype(np.uint8)
        out[f"random_{i:02d}"] = (P.astype(np.float32), mask)
    return out


def write(folder, grid, mask=None):
    """A tifxyz folder (x.tif, y.tif, z.tif, meta.json and mask.tif when given) holding the grid."""
    from kit import vc3d_io
    folder.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate("xyz"):
        vc3d_io.write_tiff(folder / f"{c}.tif", vc3d_io.raster_from_numpy(np.ascontiguousarray(grid[..., i])))
    (folder / "meta.json").write_text(json.dumps({"format": "tifxyz", "type": "seg", "scale": [0.25, 0.25],
                                                  "uuid": folder.name}))
    if mask is not None:
        m = np.ascontiguousarray(mask, dtype=np.uint8)
        vc3d_io.write_tiff(folder / "mask.tif", vc3d_io.Raster(m.shape[0], m.shape[1], "u8", m.tobytes()))
    return folder


def counts(report):
    """((transverse d0, d1), (coplanar d0, d1), (grazing d0, d1)) of a report."""
    c = report["census"]
    return tuple(tuple(int(c[d][k]) for d in (0, 1)) for k in ("transverse", "coplanar", "grazing"))
