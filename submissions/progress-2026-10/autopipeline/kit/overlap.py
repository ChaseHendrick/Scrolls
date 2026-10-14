"""Do two segments trace the same papyrus? And do their ink maps agree where they do?

`overlap` compares two tifxyz meshes (x.tif, y.tif, z.tif in volume voxels, the grid a
fixed fraction of the surface grid, as villa and the team publish them): for every point of
one trace, the distance to the nearest point of the other. With both segments' labels, it
also reports how well their human ink labels agree where the traces run together, against
matches displaced 1 to 3 mm in the surface plane. Two traces that run within a few voxels
over much of their area are one sheet: a benchmark that scores both counts it twice, and a
split that trains on one and tests on the other trains on the test sheet. PHerc0841 w00 and
ag896 are such a pair (median gap 8.6 voxels, 98 % within 25; labels Dice 0.83 against at most
0.69 displaced; docs/logs/2026-10-07-overlap-and-baseline.md).

`collate` treats two traces of one sheet as two copies of one text, as a decipherer treats two
manuscripts: what both show is more likely real. For two ink maps (each on its own segment's
surface grid), by gap between the traces: Pearson r and how often a spot in the top fraction of
one map is also in the top fraction of the other (chance: the fraction itself), against
displaced matches. A control pair (for example high-passed raw CT, or reverse-depth maps) must
agree less, or the agreement is not about ink. `--box` restricts trace A to one window, to ask
whether a single candidate reappears. On PHerc0841 the team's maps agree 0.86 within 28 um and
fall to chance beyond about 110 um; a strong ink spot reappears 70 % of the time within 28 um
against 50 % for CT texture.

Needs numpy, tifffile, scipy (cKDTree, zoom) and, for labels, zarr: all in villa's environment.
"""

import json
from pathlib import Path

from .auc import _levels
from .verify import VerifyError, _numpy, load_map

UPSAMPLE = 4          # mesh grids are 1/20 of the surface; 4x gives about 47 um spacing at 9.4 um
DISPLACE_MM = (1.0, 3.0)


def _scipy():
    try:
        from scipy import ndimage, spatial
    except ImportError as exc:
        raise VerifyError("scipy is required for kit overlap and kit collate (it is in villa's environment)") from exc
    return ndimage, spatial


def load_mesh(path, upsample=UPSAMPLE):
    """Points (N, 3) of a tifxyz mesh, upsampled, with their (row, col) on the upsampled grid and its shape."""
    np = _numpy()
    ndimage, _ = _scipy()
    import tifffile
    path = Path(path)
    try:
        xyz = np.stack([tifffile.imread(str(path / f"{c}.tif")) for c in "xyz"], -1).astype(np.float64)
    except Exception as exc:  # missing file or unreadable TIFF
        raise VerifyError(f"cannot read the tifxyz mesh in {path}: {exc}") from exc
    if xyz.ndim != 3:
        raise VerifyError(f"{path}: x, y and z must be 2D grids of one shape")
    valid = np.isfinite(xyz).all(-1) & (xyz >= 0).all(-1) & (xyz.sum(-1) > 0)   # tifxyz marks holes with -1
    if valid.sum() < 4:
        raise VerifyError(f"{path}: fewer than 4 valid mesh points")
    if upsample > 1:
        xyz = np.stack([ndimage.zoom(xyz[..., i], upsample, order=1) for i in range(3)], -1)
        valid = ndimage.zoom(valid.astype(np.float32), upsample, order=0) > 0.5
        valid = ndimage.binary_erosion(valid, iterations=upsample)   # drop points interpolated with holes
    rows, cols = np.nonzero(valid)
    scale = 0.05                       # tifxyz grid / surface grid, from meta.json when present
    try:
        scale = float(json.loads((path / "meta.json").read_text())["scale"][0])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        pass
    return {"points": xyz[rows, cols], "rows": rows, "cols": cols, "shape": valid.shape, "path": str(path),
            "surface_px_per_point": 1.0 / scale / upsample}


def sample_grid(array, mesh):
    """Values of a 2D array spanning the whole surface at each mesh point (nearest neighbour)."""
    np = _numpy()
    gh, gw = mesh["shape"]
    r = np.minimum(((mesh["rows"] + 0.5) / gh * array.shape[0]).astype(np.int64), array.shape[0] - 1)
    c = np.minimum(((mesh["cols"] + 0.5) / gw * array.shape[1]).astype(np.int64), array.shape[1] - 1)
    return np.asarray(array)[r, c]


def match(a, b):
    """For every point of trace a: distance (voxels) to trace b and the index of b's nearest point."""
    _, spatial = _scipy()
    return spatial.cKDTree(b["points"]).query(a["points"], k=1)


def _displaced(np, rng, b, j, step_um, shape_index):
    """Indices into b of the grid points displaced 1 to 3 mm in the surface plane from b[j]."""
    r = rng.uniform(*DISPLACE_MM) * 1000 / step_um
    t = rng.uniform(0, 2 * np.pi)
    rr = b["rows"][j] + int(round(r * np.sin(t)))
    cc = b["cols"][j] + int(round(r * np.cos(t)))
    gh, gw = b["shape"]
    inside = (rr >= 0) & (rr < gh) & (cc >= 0) & (cc < gw)
    k = np.full(len(j), -1)
    k[inside] = shape_index[rr[inside], cc[inside]]
    return k


def _index(np, mesh):
    idx = np.full(mesh["shape"], -1)
    idx[mesh["rows"], mesh["cols"]] = np.arange(len(mesh["rows"]))
    return idx


def overlap(mesh_a, mesh_b, voxel_um, within=12, labels_a=None, labels_b=None, level="2",
            draws=200, seed=0, upsample=UPSAMPLE):
    np = _numpy()
    a, b = load_mesh(mesh_a, upsample), load_mesh(mesh_b, upsample)
    step = voxel_um * a["surface_px_per_point"]
    out = {"a": str(mesh_a), "b": str(mesh_b), "voxel_um": voxel_um, "grid_um": round(step, 1), "within_vox": within}
    for name, p, q in (("a_to_b", a, b), ("b_to_a", b, a)):
        d, _ = match(p, q)
        out[name] = {"area_cm2": round(len(d) * (voxel_um * p["surface_px_per_point"] * 1e-4) ** 2, 2),
                     "median_gap_vox": round(float(np.median(d)), 1),
                     "share_within": {str(t): round(float((d <= t).mean()), 4) for t in (2, 5, 12, 25, 50)}}
        if name == "a_to_b":
            out["same_sheet_share"] = round(float((d <= within).mean()), 4)
    out["verdict"] = ("overlapping traces: one sheet over this share of A; count it once in a benchmark"
                      if out["same_sheet_share"] >= 0.1 else "separate surfaces")
    if labels_a and labels_b:
        out["labels"] = _label_agreement(np, a, b, labels_a, labels_b, level, within, draws, seed, step)
    return out


def _label_agreement(np, a, b, labels_a, labels_b, level, within, draws, seed, step):
    def lab(mesh, d):
        ink = _levels(Path(d) / "inklabels.zarr", level)
        sup = _levels(Path(d) / "supervision.zarr", level)
        return sample_grid(np.asarray(ink), mesh) > 0, sample_grid(np.asarray(sup), mesh) > 0
    ia, sa = lab(a, labels_a)
    ib, sb = lab(b, labels_b)
    d, j = match(a, b)
    both = (d <= within) & sa & sb[j]
    res = {"points_both_labelled": int(both.sum()), "area_cm2": round(int(both.sum()) * (step * 1e-4) ** 2, 3)}
    if both.sum() < 50:
        res["dice"] = None
        res["note"] = "too few points labelled on both traces"
        return res
    dice = lambda x, y: 2 * float((x & y).sum()) / max(1, int(x.sum() + y.sum()))
    res["dice"] = round(dice(ia[both], ib[j][both]), 3)
    rng = np.random.default_rng(seed)
    idx = _index(np, b)
    nulls = []
    for _ in range(draws):
        k = _displaced(np, rng, b, j, step, idx)
        ok = (d <= within) & sa & (k >= 0)
        ok[ok] &= sb[k[ok]]
        if ok.sum() >= 50:
            nulls.append(dice(ia[ok], ib[k[ok]]))
    if nulls:
        res["null_dice_mean"] = round(float(np.mean(nulls)), 3)
        res["null_dice_p99"] = round(float(np.percentile(nulls, 99)), 3)
        res["null_draws"] = len(nulls)
    return res


def collate(mesh_a, mesh_b, map_a, map_b, voxel_um, gaps=(0, 3, 6, 9, 12, 18, 30), top=0.2,
            control_a=None, control_b=None, box=None, draws=50, seed=0, upsample=UPSAMPLE):
    np = _numpy()
    a, b = load_mesh(mesh_a, upsample), load_mesh(mesh_b, upsample)
    step = voxel_um * b["surface_px_per_point"]
    d, j = match(a, b)
    pairs = {"map": (map_a, map_b)}
    if control_a and control_b:
        pairs["control"] = (control_a, control_b)
    keep = np.ones(len(d), bool)
    if box is not None:
        ma = np.squeeze(_load_any(map_a))
        y0, y1, x0, x1 = box
        gh, gw = a["shape"]
        ry = (a["rows"] + 0.5) / gh * ma.shape[0]
        rx = (a["cols"] + 0.5) / gw * ma.shape[1]
        keep = (ry >= y0) & (ry < y1) & (rx >= x0) & (rx < x1)
        if not keep.any():
            raise VerifyError("the box holds no point of trace A")
    rng = np.random.default_rng(seed)
    idx = _index(np, b)
    out = {"a": str(mesh_a), "b": str(mesh_b), "grid_um": round(step, 1), "top": top, "box": box, "bins": []}
    vals = {}
    for name, (pa, pb) in pairs.items():
        va = sample_grid(np.squeeze(_load_any(pa)).astype(np.float64), a)
        vb_all = np.squeeze(_load_any(pb)).astype(np.float64)
        vb = sample_grid(vb_all, b)
        vals[name] = (va, vb)
    for lo, hi in zip(gaps[:-1], gaps[1:]):
        m = keep & (d > lo) & (d <= hi)
        row = {"gap_vox": [lo, hi], "gap_um": [round(lo * voxel_um), round(hi * voxel_um)], "points": int(m.sum())}
        for name, (va, vb) in vals.items():
            ok = m & (va != 0) & (vb[j] != 0)
            if ok.sum() < 30:
                row[name] = None
                continue
            row[name] = _agreement(np, va, vb, j, ok, top, rng, b, step, idx, draws)
        out["bins"].append(row)
    return out


def _load_any(path):
    np = _numpy()
    return np.load(path) if str(path).endswith(".npy") else load_map(path)


def _agreement(np, va, vb, j, ok, top, rng, b, step, idx, draws):
    x, y = va[ok], vb[j[ok]]
    ta = va > np.quantile(va[va != 0], 1 - top)
    tb = vb > np.quantile(vb[vb != 0], 1 - top)
    r = float(np.corrcoef(x, y)[0, 1]) if x.std() > 0 and y.std() > 0 else None
    sel = ok & ta
    reappear = float(tb[j[sel]].mean()) if sel.any() else None
    nr, nre = [], []
    for _ in range(draws):
        k = _displaced(np, rng, b, j, step, idx)
        okn = ok & (k >= 0)
        okn[okn] &= vb[k[okn]] != 0
        if okn.sum() < 30:
            continue
        xn, yn = va[okn], vb[k[okn]]
        if xn.std() > 0 and yn.std() > 0:
            nr.append(float(np.corrcoef(xn, yn)[0, 1]))
        s = okn & ta
        if s.any():
            nre.append(float(tb[k[s]].mean()))
    res = {"points": int(ok.sum()), "pearson": None if r is None else round(r, 3),
           "reappear": None if reappear is None else round(reappear, 3), "reappear_chance": top}
    if nr:
        res["null_pearson_mean"] = round(float(np.mean(nr)), 3)
        res["null_pearson_max"] = round(float(np.max(nr)), 3)
    if nre:
        res["null_reappear_mean"] = round(float(np.mean(nre)), 3)
        res["null_reappear_max"] = round(float(np.max(nre)), 3)
    return res


def format_overlap(r):
    rows = [f"A {r['a']}\nB {r['b']}  (grid {r['grid_um']} um)"]
    for k, label in (("a_to_b", "A to B"), ("b_to_a", "B to A")):
        x = r[k]
        rows.append(f"{label}: {x['area_cm2']} cm2, median gap {x['median_gap_vox']} vox, within "
                    + ", ".join(f"{t} vox {v:.0%}" for t, v in x["share_within"].items()))
    rows.append(f"within {r['within_vox']} vox: {r['same_sheet_share']:.0%} of A; {r['verdict']}")
    lab = r.get("labels")
    if lab:
        if lab.get("dice") is None:
            rows.append(f"labels: {lab.get('note')}")
        else:
            rows.append(f"labels where both traces are labelled ({lab['area_cm2']} cm2): Dice {lab['dice']}, displaced "
                        f"matches mean {lab.get('null_dice_mean')}, 99th percentile {lab.get('null_dice_p99')}")
    return "\n".join(rows)


def format_collate(r):
    rows = [f"A {r['a']}\nB {r['b']}  (grid {r['grid_um']} um; reappear = share of A's top {r['top']:.0%} "
            f"that is in B's top {r['top']:.0%}; chance {r['top']:.2f})"]
    for row in r["bins"]:
        line = f"gap {row['gap_um'][0]}-{row['gap_um'][1]} um ({row['points']} pts):"
        for name in ("map", "control"):
            x = row.get(name)
            if x is None:
                continue
            line += (f"  {name} r {x['pearson']} (displaced {x.get('null_pearson_mean')}), reappear {x['reappear']}"
                     f" (displaced {x.get('null_reappear_mean')})")
        rows.append(line)
    return "\n".join(rows)


def dumps(result):
    return json.dumps(result, indent=2)
