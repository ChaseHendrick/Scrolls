"""Score the arms' ink maps against the segment's published ink labels, with the reverse-depth map as control.

AUC as `kit.auc` computes it (level 2 labels mapped by nearest neighbor onto the surface grid, inside the supervision
mask, zeros kept, 64 px edge left out), under two label registrations: as stored, and "texture", the labels moved by
(dy, dx) = (-6, -7) surface pixels. Each arm is also compared with R0 on the same pixels by a paired block bootstrap
(kit.auc.block_bootstrap: 107 px blocks, 1 mm at 9.366 um).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kit import auc as A  # noqa: E402

REGISTRATIONS = {"as_stored": (0, 0), "texture": (-6, -7)}
LEVEL = "2"
INNER = 64
DRAWS = 1000
SEED = 20261030


def _axis(start, stop, n_surface, n_labels, scale, shift):
    """Label indices for surface pixels start..stop when the labels are moved by shift: pixel p takes the label of
    surface pixel p - shift; and whether that source lies on the surface."""
    src = np.arange(start, stop) - int(shift)
    ok = (src >= 0) & (src < n_surface)
    idx = np.minimum(((np.clip(src, 0, n_surface - 1) + 0.5) * scale).astype(np.int64), n_labels - 1)
    return idx, ok


def labels_on_map(labels, mask, surface_shape, box, offset=(0, 0), level=LEVEL):
    """Boolean ink and supervision on the box's grid, the labels moved by offset (dy, dx) surface pixels
    (label[y, x] = labels[y - dy, x - dx]); pixels whose source falls off the surface leave the supervision."""
    lab = A._levels(labels, level)
    msk = A._levels(mask, level)
    if lab.shape != msk.shape:
        raise A.VerifyError(f"labels {lab.shape} and mask {msk.shape} differ in shape at level {level}")
    H, W = surface_shape
    y0, y1, x0, x1 = box
    sy, sx = lab.shape[0] / H, lab.shape[1] / W
    if abs(sy - sx) > A.MAX_AXIS_MISMATCH * max(sy, sx):
        raise A.VerifyError(f"labels {lab.shape} and surface {tuple(surface_shape)} differ in scale between axes")
    dy, dx = (int(v) for v in offset)
    rows, rok = _axis(y0, y1, H, lab.shape[0], sy, dy)
    cols, cok = _axis(x0, x1, W, lab.shape[1], sx, dx)
    r0, r1, c0, c1 = int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1
    ink = np.asarray(lab[r0:r1, c0:c1])[np.ix_(rows - r0, cols - c0)] > 0
    sup = np.asarray(msk[r0:r1, c0:c1])[np.ix_(rows - r0, cols - c0)] > 0
    sup &= rok[:, None] & cok[None, :]
    return ink, sup


def load_map(path):
    return np.squeeze(A._load(path))


def score_arm(pred, ink, sup, control=None, ref=None, draws=DRAWS, seed=SEED, inner=INNER):
    """AUC of one map (keep_zero, inner px edge left out); with control, the reverse-depth map's AUC; with ref (the
    R0 map), the difference to ref on the same pixels and its paired block-bootstrap 95 percent interval."""
    out = {"auc": A.score_array(pred, ink, sup, True, inner)["auc"]}
    out["control"] = A.score_array(control, ink, sup, True, inner)["auc"] if control is not None else None
    if ref is not None:
        b = A.block_bootstrap(pred, ink, sup, draws, A.BLOCK_PX, seed, ref, True, inner)
        ref_auc = A.score_array(ref, ink, sup, True, inner)["auc"]
        out["vs_R0"] = {"difference": round(out["auc"] - ref_auc, 4), "ci95": b["compare"]["ci95"]}
    return out


def score_segment(maps, model, key, labels_dir, surface_shape, box, arms, draws=DRAWS, seed=SEED, log=None):
    """Score every arm map maps/MODEL_KEY_ARM.tif (and its _reverse.tif control) that exists: {ARM: {REG: row}}."""
    maps = Path(maps)
    labels_dir = Path(labels_dir)
    out = {}
    ref_path = maps / f"{model}_{key}_R0.tif"
    ref = load_map(ref_path) if ref_path.exists() else None
    for arm in arms:
        f = maps / f"{model}_{key}_{arm}.tif"
        if not f.exists():
            continue
        pred = load_map(f)
        rev = f.with_name(f.stem + "_reverse.tif")
        ctrl = load_map(rev) if rev.exists() else None
        row = {}
        for reg, off in REGISTRATIONS.items():
            ink, sup = labels_on_map(labels_dir / "inklabels.zarr", labels_dir / "supervision.zarr", surface_shape,
                                     box, off)
            if pred.shape != ink.shape:
                raise A.VerifyError(f"{f}: map shape {pred.shape} is not the box's {ink.shape}")
            cmp = ref if (ref is not None and arm not in ("R0", "P0")) else None
            row[reg] = score_arm(pred, ink, sup, ctrl, cmp, draws, seed)
        out[arm] = row
        if log:
            log(model, key, arm, row)
    return out
