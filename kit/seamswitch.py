"""Seam-aware winding switches of a spiral fit on labeled sheet grids.

A fit gives each vertex of a labeled sheet grid a whole winding j; the label gives k. With d = j - s k (s = +1 or -1,
whichever makes the most common d most common), a correct fit has d constant along a sheet except at its own seam,
which can sit at any angle. So the offset is the mode of d in each (angle bin x z bin) cell, and a switch is a pair of
grid neighbors, both matched, whose d minus their cell offset differs. Reported per 1000 neighbor pairs, with the
share of matched vertices whose d is not their cell's offset (seam wrong area) and the global-offset versions.

This follows the definition in CanadaApollo6/vesuvius-spiral-chains eval/spiral_eval.py (Apache-2.0, read
29 Oct 2026, commit 4365b98): 10 degree x 250 z cells, switches per 1000 adjacent grid pairs. It is restated here, not
copied. Standard library and numpy only.

Command line (headless):

    python -m kit.seamswitch demo [--json]                       synthetic spiral sheet, clean and with a planted error
    python -m kit.seamswitch sheet GRID.npz [GRID.npz ...] [--json]     unlabeled sheet grids: rho, theta, z, valid
    python -m kit.seamswitch labeled GRID.npz [GRID.npz ...] [--json]   labeled sheet grids: j, k, valid, angle, z

Exit 0 with the result, 2 on unusable input. The result is a geometry score of a fit, never a reading.
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np


def _mode(values: np.ndarray) -> int:
    vals, counts = np.unique(values, return_counts=True)
    return int(vals[np.argmax(counts)])


def _pairs(valid: np.ndarray):
    """Index pairs (flat) of 4-neighbors in one H x W grid with both ends valid."""
    h, w = valid.shape
    idx = np.arange(h * w).reshape(h, w)
    out = []
    for a, b in ((idx[:, :-1], idx[:, 1:]), (idx[:-1, :], idx[1:, :])):
        a, b = a.ravel(), b.ravel()
        keep = valid.ravel()[a] & valid.ravel()[b]
        out.append((a[keep], b[keep]))
    return np.concatenate([p[0] for p in out]), np.concatenate([p[1] for p in out])


def seam_switches(surfaces, bin_deg: float = 10.0, bin_z: float = 250.0) -> dict:
    """surfaces: iterable of dicts with H x W arrays j (fitted whole winding), k (label winding), valid (bool, both
    known), angle (degrees around the umbilicus) and z. Returns the sign s, counts and both offset variants."""
    js, ks, cells, pairs = [], [], [], []
    base = 0
    for s in surfaces:
        valid = np.asarray(s["valid"], bool)
        flat = valid.ravel()
        pos = np.full(flat.size, -1, np.int64)
        pos[flat] = base + np.arange(int(flat.sum()))
        a, b = _pairs(valid)
        pairs.append(np.stack([pos[a], pos[b]], 1))
        js.append(np.asarray(s["j"]).ravel()[flat].astype(np.int64))
        ks.append(np.asarray(s["k"]).ravel()[flat].astype(np.int64))
        ang = np.mod(np.asarray(s["angle"], float).ravel()[flat], 360.0)
        z = np.asarray(s["z"], float).ravel()[flat]
        cells.append(np.stack([np.floor(ang / bin_deg), np.floor(z / bin_z)], 1).astype(np.int64))
        base += int(flat.sum())
    if base == 0:
        return {"vertices": 0, "pairs": 0}
    j, k = np.concatenate(js), np.concatenate(ks)
    cell = np.concatenate(cells)
    pr = np.concatenate(pairs) if pairs else np.zeros((0, 2), np.int64)
    best = None
    for sign in (1, -1):
        d = j - sign * k
        vals, counts = np.unique(d, return_counts=True)
        share = counts.max() / len(d)
        if best is None or share > best[0]:
            best = (share, sign, d)
    _, sign, d = best
    glob = _mode(d)
    _, inv = np.unique(cell, axis=0, return_inverse=True)
    inv = inv.ravel()
    off = np.empty(len(d), np.int64)
    for c in np.unique(inv):
        m = inv == c
        off[m] = _mode(d[m])
    e_seam, e_glob = d - off, d - glob
    n = len(pr)

    def per1000(e):
        return float(1000.0 * np.count_nonzero(e[pr[:, 0]] != e[pr[:, 1]]) / n) if n else float("nan")
    return {"sign": int(sign), "vertices": int(len(d)), "pairs": int(n), "cells": int(len(np.unique(inv))),
            "switches_per_1000": per1000(e_seam), "wrong_area": float(np.mean(e_seam != 0)),
            "switches_per_1000_global": per1000(e_glob), "wrong_area_global": float(np.mean(e_glob != 0))}


def local_switches(rho, theta, valid) -> dict:
    """Label-free switches along one sheet grid: rho = r / dr and theta (radians) of each vertex in the fit's spiral
    coordinates, H x W. Two valid grid neighbors lie on the same physical sheet, so the fit's winding coordinate
    w = rho - theta / 2 pi must not change between them by a whole winding; the change is taken with theta's
    difference wrapped to (-pi, pi], so the fit's own seam is not counted. Returns the neighbor pairs, the pairs whose
    change rounds to a non-zero whole number, and that per 1000."""
    rho, theta = np.asarray(rho, float), np.asarray(theta, float)
    valid = np.asarray(valid, bool) & np.isfinite(rho) & np.isfinite(theta)
    a, b = _pairs(valid)
    r, t = rho.ravel(), theta.ravel()
    dt = np.mod(t[b] - t[a] + np.pi, 2 * np.pi) - np.pi
    step = np.rint((r[b] - r[a]) - dt / (2 * np.pi))
    n, s = int(len(a)), int(np.count_nonzero(step))
    return {"pairs": n, "switches": s, "per_1000": float(1000.0 * s / n) if n else float("nan")}


def _forest(valid: np.ndarray):
    """Spanning forest of one H x W grid: each valid vertex points to its left neighbor when valid, else the one
    above when valid, else itself (a root). Returns the parent of each flat index (-1 where invalid)."""
    h, w = valid.shape
    idx = np.arange(h * w).reshape(h, w)
    par = np.where(valid, idx, -1)
    up = np.zeros_like(valid)
    up[1:] = valid[1:] & valid[:-1]
    par[up] = idx[up] - w
    left = np.zeros_like(valid)
    left[:, 1:] = valid[:, 1:] & valid[:, :-1]
    par[left] = idx[left] - 1
    return par.ravel()


def sheet_switches(rho, theta, z, valid, bin_deg: float = 10.0, bin_z: float = 250.0, min_tree: int = 100) -> dict:
    """Switches of a fit along one unlabeled traced sheet (an H x W grid that may wind several turns): rho = r / dr
    and theta (radians, wrapped) of each vertex in the fit's spiral coordinates, z in voxels.

    theta is unwrapped along a spanning forest of the grid (left neighbor first, then above), so e = rho - theta / 2 pi
    is the fit's continuous winding along the sheet, constant for a fit that keeps the sheet on one winding. Each tree
    gets d = round(e - median of its e); vertices of trees under min_tree are left out. Then, as in seam_switches, a
    switch is a pair of grid neighbors in one tree whose d minus their cell offset (the mode of d per angle x z cell)
    differs, per 1000 such pairs; the wrong area is the share of vertices off their cell offset. The `_global`
    versions use offset 0 (the tree's own median winding). `jumps_per_1000` is local_switches on the same pairs."""
    rho, theta, z = (np.asarray(a, float) for a in (rho, theta, z))
    valid = np.asarray(valid, bool) & np.isfinite(rho) & np.isfinite(theta) & np.isfinite(z)
    par = _forest(valid)
    t = theta.ravel()
    ok = par >= 0
    c = np.zeros(par.size, np.int64)
    v = np.flatnonzero(ok & (par != np.arange(par.size)))
    p = par[v]
    dt = np.mod(t[v] - t[p] + np.pi, 2 * np.pi) - np.pi
    c[v] = np.rint((t[p] + dt - t[v]) / (2 * np.pi)).astype(np.int64)
    root = np.where(ok, par, np.arange(par.size))
    while True:                                   # pointer doubling: c becomes the turns from the root, root the root
        nxt = root[root]
        if np.array_equal(nxt, root):
            break
        c = c + c[root]
        root = nxt
    e = rho.ravel() - t / (2 * np.pi) - c
    ids, inv, size = np.unique(root[ok], return_inverse=True, return_counts=True)
    keep = np.zeros(par.size, bool)
    keep[np.flatnonzero(ok)] = size[inv] >= min_tree
    if not keep.any():
        return {"vertices": 0, "trees": 0, "pairs": 0}
    kv = np.flatnonzero(keep)
    r, ev = root[kv], e[kv]
    order = np.lexsort((ev, r))
    rs = r[order]
    start = np.flatnonzero(np.r_[True, rs[1:] != rs[:-1]])
    count = np.diff(np.r_[start, len(rs)])
    med = 0.5 * (ev[order][start + (count - 1) // 2] + ev[order][start + count // 2])
    tree_of = np.searchsorted(rs[start], r)
    d = np.zeros(par.size, np.int64)
    d[kv] = np.rint(ev - med[tree_of]).astype(np.int64)
    ang = np.mod(np.degrees(t[kv]), 360.0)
    cell = np.stack([np.floor(ang / bin_deg), np.floor(z.ravel()[kv] / bin_z)], 1).astype(np.int64)
    _, cinv = np.unique(cell, axis=0, return_inverse=True)
    cinv = cinv.ravel()
    off = np.zeros(par.size, np.int64)
    oo = np.empty(len(kv), np.int64)
    dv = d[kv]
    for cc in np.unique(cinv):
        m = cinv == cc
        oo[m] = _mode(dv[m])
    off[kv] = oo
    a, b = _pairs(keep.reshape(valid.shape))
    same = root[a] == root[b]
    a, b = a[same], b[same]
    n = int(len(a))
    es, eg = d - off, d
    jump = np.rint((rho.ravel()[b] - rho.ravel()[a]) - (np.mod(t[b] - t[a] + np.pi, 2 * np.pi) - np.pi) / (2 * np.pi))

    def per1000(x):
        return float(1000.0 * x / n) if n else float("nan")
    sw, swg, jp = (int(np.count_nonzero(x)) for x in (es[a] != es[b], eg[a] != eg[b], jump))
    wr, wrg = int(np.count_nonzero(es[kv])), int(np.count_nonzero(eg[kv]))
    return {"vertices": int(len(kv)), "trees": int(np.count_nonzero(size >= min_tree)), "pairs": n,
            "cells": int(cinv.max() + 1), "switches": sw, "switches_global": swg, "jumps": jp, "wrong": wr,
            "wrong_global": wrg, "switches_per_1000": per1000(sw), "wrong_area": wr / len(kv),
            "switches_per_1000_global": per1000(swg), "wrong_area_global": wrg / len(kv),
            "jumps_per_1000": per1000(jp)}


def pool(results) -> dict:
    """Sum sheet_switches results over several grids: counts add, rates are recomputed from the sums."""
    keys = ("vertices", "trees", "pairs", "switches", "switches_global", "jumps", "wrong", "wrong_global")
    t = {k: int(sum(r.get(k, 0) for r in results)) for k in keys}
    n, v = t["pairs"], t["vertices"]
    t.update({"switches_per_1000": 1000.0 * t["switches"] / n if n else float("nan"),
              "switches_per_1000_global": 1000.0 * t["switches_global"] / n if n else float("nan"),
              "jumps_per_1000": 1000.0 * t["jumps"] / n if n else float("nan"),
              "wrong_area": t["wrong"] / v if v else float("nan"),
              "wrong_area_global": t["wrong_global"] / v if v else float("nan")})
    return t


# ---------------------------------------------------------------- command line

SHEET_KEYS = ("rho", "theta", "z", "valid")
LABELED_KEYS = ("j", "k", "valid", "angle", "z")


class InputError(ValueError):
    pass


def _load(path, keys):
    try:
        with np.load(path) as f:
            missing = [k for k in keys if k not in f.files]
            if missing:
                raise InputError(f"{path}: no array {', '.join(missing)} (needs {', '.join(keys)})")
            arrs = {k: np.asarray(f[k]) for k in keys}
    except (OSError, ValueError) as e:
        if isinstance(e, InputError):
            raise
        raise InputError(f"{path}: not a readable .npz ({e})") from None
    shapes = {a.shape for a in arrs.values() if a.ndim}
    if len(shapes) != 1 or len(next(iter(shapes))) != 2:
        raise InputError(f"{path}: every array must be one H x W grid of the same shape")
    return arrs


def demo_sheet(h=60, w=400, turns=3.0, patch=None, dr=1.0):
    """A synthetic traced sheet that winds `turns` times around the axis at constant spacing dr, as a fit would give
    it (rho = r / dr, theta wrapped), with an optional planted error: inside patch = (r0, r1, c0, c1) the fit puts
    the sheet one winding further out. Returns the grid dict for sheet_switches and the number of neighbor pairs the
    patch boundary cuts, which is the switch count a correct score reports."""
    cols = np.linspace(0.0, turns * 2 * np.pi, w)
    theta = np.tile(np.mod(cols, 2 * np.pi), (h, 1))
    rho = np.tile(10.0 + cols / (2 * np.pi), (h, 1)) / dr
    cut = 0
    if patch is not None:
        r0, r1, c0, c1 = patch
        rho[r0:r1, c0:c1] += 1.0
        cut = (r1 - r0) * ((c0 > 0) + (c1 < w)) + (c1 - c0) * ((r0 > 0) + (r1 < h))
    z = np.tile(np.arange(h)[:, None] * 4.0, (1, w))
    return {"rho": rho, "theta": theta, "z": z, "valid": np.ones((h, w), bool)}, int(cut)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kit.seamswitch",
                                 description="Seam-aware winding switches of a spiral fit on sheet grids")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="synthetic sheet, clean and with one planted wrong-winding patch")
    d.add_argument("--json", action="store_true", help="print the full result as JSON")
    for name, help_ in (("sheet", "unlabeled sheet grids (.npz with rho, theta, z, valid)"),
                        ("labeled", "labeled sheet grids (.npz with j, k, valid, angle, z)")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("grids", nargs="+", metavar="GRID.npz", help="one .npz file per sheet grid")
        p.add_argument("--bin-deg", type=float, default=10.0, help="angle bin of the seam cells, degrees")
        p.add_argument("--bin-z", type=float, default=250.0, help="z bin of the seam cells, voxels")
        if name == "sheet":
            p.add_argument("--min-tree", type=int, default=100, help="leave out connected pieces with fewer vertices")
        p.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "demo":
            clean, _ = demo_sheet()
            planted, cut = demo_sheet(patch=(20, 40, 100, 140))
            res = {"clean": sheet_switches(**clean), "planted": sheet_switches(**planted), "planted_cut_pairs": cut}
            res["ok"] = res["clean"]["switches"] == 0 and res["planted"]["switches"] == cut
        elif a.cmd == "sheet":
            per = [sheet_switches(**_load(g, SHEET_KEYS), bin_deg=a.bin_deg, bin_z=a.bin_z, min_tree=a.min_tree)
                   for g in a.grids]
            res = {"grids": dict(zip(a.grids, per)), "pooled": pool(per), "ok": True}
        else:
            res = seam_switches([_load(g, LABELED_KEYS) for g in a.grids], bin_deg=a.bin_deg, bin_z=a.bin_z)
            res["ok"] = res.get("vertices", 0) > 0
    except InputError as e:
        print(f"seamswitch: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(res, indent=1, sort_keys=True))
    elif a.cmd == "demo":
        print(f"clean sheet: {res['clean']['switches']} switches of {res['clean']['pairs']} neighbor pairs")
        print(f"planted patch: {res['planted']['switches']} switches (patch boundary {cut} pairs), "
              f"{res['planted']['switches_per_1000']:.2f} per 1000")
        print("ok" if res["ok"] else "NOT OK")
    else:
        r = res["pooled"] if a.cmd == "sheet" else res
        print(f"{r.get('pairs', 0)} neighbor pairs, {r.get('switches_per_1000', float('nan')):.2f} switches per 1000, "
              f"wrong area {r.get('wrong_area', float('nan')):.4f}")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
