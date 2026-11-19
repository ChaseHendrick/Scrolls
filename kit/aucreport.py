"""Detailed AUC report for an ink map: curves, ties, regions, a shifted-label null and label registration.

`python -m kit auc` gives one number per map (plus its reverse-depth control and a block-bootstrap interval). This
module scores the same pixels the same way and adds what a reader of that number usually asks next:

  curves     ROC and precision-recall curves, average precision (AP) next to the ink share it should beat, the
             true-positive rate at 1, 5 and 10 % false positives, and the best-F1 and Youden thresholds.
  ties       the share of ink and background pixel pairs that tie, and the AUC with ties counted as wins or as losses.
             A map with few gray levels (a uint8 map, a thresholded map) can move by half that share.
  tiles      the AUC of each square tile of the labeled area (default 534 px, 5 mm at 9.366 um), so one good patch
             cannot hide a region where the map fails.
  null       a spatial null: the labels (ink and supervision together) are shifted cyclically inside the labeled
             area's bounding box by at least one bootstrap block, and the map is scored against each shifted copy.
             The shift keeps the texture of both the map and the labels and breaks only their alignment. The p value
             is (1 + draws at or above the real AUC) / (1 + draws).
  offsets    optional (`--offset-scan R`): the AUC with the labels moved by every (dy, dx) within R pixels. A peak away
             from (0, 0) says the labels and the map are not registered. The best offset is chosen on these labels,
             so it is a diagnosis, not a score: fix an offset first, then score it on other labels.
  finite     every map is checked with kit.finite before scoring; a map holding NaN or Inf is refused (exit 1).
  pool       `pool` combines reports of several segments: mean, range and, from 5 segments on, a bootstrap
             interval over segments, which is the honest unit when segments differ.

Two options change which labels count, the same way for every map scored: `--exclude Y0 Y1 X0 X1` removes a box of
the surface grid (grown by `--exclude-margin`) from the supervision, for a region that was looked at before, and
`--label-offset DY DX` moves the labels by (dy, dx) surface pixels, label[y, x] = labels[y - dy, x - dx], with the
vacated edge left out of the supervision.

    python -m kit.aucreport score MAP.tif --labels L/inklabels.zarr --mask L/supervision.zarr \\
        [--control MAP_reverse.tif] [--compare OTHER.tif] [--plot roc_pr.svg] [--curves curves.csv] [--json]
    python -m kit.aucreport pool A.json B.json C.json [--json]
    python -m kit.aucreport demo [--plot demo.svg]       # synthetic data, no download: try every section

Needs numpy, plus tifffile and zarr to read files (as kit auc). Reads only; writes the files named by --plot,
--curves and --out. An AUC is a score against human labels, never a reading.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import auc, finite
from .verify import VerifyError, _numpy

VERSION = 1
LEVELS = 65536
TILE_PX = 534            # 5 mm at 9.366 um
TILE_MIN_PX = 200        # each class, per tile
NULL_DRAWS = 200
NULL_MIN_PX = 50         # each class, per shifted copy
POOL_MIN_SEGMENTS = 5
FPR_POINTS = (0.01, 0.05, 0.10)
EXIT_OK, EXIT_NONFINITE, EXIT_INPUT = 0, 1, 2
UNCONTROLLED = ("no reverse-depth control was given: no number in this report is a result until the same map, read in "
                "reverse depth order, is scored on the same labels (--control)")
COMPARE_TAG = " [no control of its own]"
COMPARE_UNCONTROLLED = ("the compared map has no reverse-depth control of its own: its AUC and AP are not a result; "
                        "score it alone with its own --control")


# ---------------------------------------------------------------------------------------------------------- labels

def _axis_index(np, start, stop, n_surface, n_labels, scale, shift=0):
    src = np.arange(start, stop) - int(shift)
    ok = (src >= 0) & (src < n_surface)
    idx = np.minimum(((np.clip(src, 0, n_surface - 1) + 0.5) * scale).astype(np.int64), n_labels - 1)
    return idx, ok


def labels_on_map(labels, mask, level, surface_shape, crop, map_shape, offset=(0, 0)):
    """Boolean ink and supervision arrays on the map's grid, as kit auc maps them (nearest neighbor), with the labels
    moved by offset (dy, dx) surface pixels; label sources off the surface leave the supervision."""
    np = _numpy()
    lab = auc._levels(labels, level)
    msk = auc._levels(mask, level)
    if lab.shape != msk.shape:
        raise VerifyError(f"labels {lab.shape} and mask {msk.shape} differ in shape at level {level}")
    sy, sx = lab.shape[0] / surface_shape[0], lab.shape[1] / surface_shape[1]
    if abs(sy - sx) > auc.MAX_AXIS_MISMATCH * max(sy, sx):
        raise VerifyError(f"labels {lab.shape} and surface {tuple(surface_shape)} differ in scale between axes "
                          f"({sy:.4f} vs {sx:.4f}); they are not the same grid")
    y0, y1, x0, x1 = crop if crop is not None else (0, surface_shape[0], 0, surface_shape[1])
    if not (0 <= y0 < y1 <= surface_shape[0] and 0 <= x0 < x1 <= surface_shape[1]):
        raise VerifyError(f"crop {[y0, y1, x0, x1]} is outside the {surface_shape[0]} x {surface_shape[1]} surface")
    if (y1 - y0, x1 - x0) != tuple(map_shape):
        raise VerifyError(f"map shape {tuple(map_shape)} does not match the window {y1 - y0} x {x1 - x0}")
    dy, dx = (int(v) for v in offset)
    if abs(dy) >= surface_shape[0] or abs(dx) >= surface_shape[1]:
        raise VerifyError(f"label offset {[dy, dx]} moves the labels off the surface")
    rows, row_ok = _axis_index(np, y0, y1, surface_shape[0], lab.shape[0], sy, dy)
    cols, col_ok = _axis_index(np, x0, x1, surface_shape[1], lab.shape[1], sx, dx)
    r0, r1, c0, c1 = int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1
    ink = np.asarray(lab[r0:r1, c0:c1])[np.ix_(rows - r0, cols - c0)] > 0
    sup = np.asarray(msk[r0:r1, c0:c1])[np.ix_(rows - r0, cols - c0)] > 0
    if not (row_ok.all() and col_ok.all()):
        sup &= row_ok[:, None] & col_ok[None, :]
    return ink, sup


def exclude_boxes(ink, sup, boxes, surface_shape, crop=None, margin=0):
    """Remove boxes (y0 y1 x0 x1 on the surface grid), each grown by margin px and clipped to the surface, from the
    supervision of a map covering `crop`. Returns the new mask and a record of what was removed."""
    if margin < 0:
        raise VerifyError("the exclusion margin cannot be negative")
    H, W = (int(v) for v in surface_shape)
    cy0, cy1, cx0, cx1 = crop if crop is not None else (0, H, 0, W)
    out = sup.copy()
    grown = []
    for box in boxes:
        y0, y1, x0, x1 = (int(v) for v in box)
        if not (y0 < y1 and x0 < x1):
            raise VerifyError(f"exclusion box {[y0, y1, x0, x1]} is empty: give y0 y1 x0 x1 with y0 < y1, x0 < x1")
        g = [max(0, y0 - margin), min(H, y1 + margin), max(0, x0 - margin), min(W, x1 + margin)]
        if g[0] >= g[1] or g[2] >= g[3]:
            raise VerifyError(f"exclusion box {[y0, y1, x0, x1]} lies outside the {H} x {W} surface")
        grown.append(g)
        r0, r1 = max(g[0], cy0) - cy0, min(g[1], cy1) - cy0
        c0, c1 = max(g[2], cx0) - cx0, min(g[3], cx1) - cx0
        if r0 < r1 and c0 < c1:
            out[r0:r1, c0:c1] = False
    removed = sup & ~out
    kept_ink, all_ink = int((out & ink).sum()), int((sup & ink).sum())
    return out, {"boxes": [[int(v) for v in b] for b in boxes], "margin": int(margin), "grown": grown,
                 "supervised_px_removed": int(removed.sum()), "ink_px_removed": int((removed & ink).sum()),
                 "ink_px_kept": kept_ink, "ink_share_kept": round(kept_ink / all_ink, 4) if all_ink else None}


# ---------------------------------------------------------------------------------------------------------- curves

def _r(x, n=4):
    return None if x is None else round(float(x), n)


def _histograms(q, ink, use):
    """Per-level counts of ink and background pixels of a quantized map (kit auc's integer scale)."""
    np = _numpy()
    a = np.bincount(q[use & ink], minlength=LEVELS).astype(np.float64)
    b = np.bincount(q[use & ~ink], minlength=LEVELS).astype(np.float64)
    return a, b


def curve_stats(a, b, points=101):
    """ROC and PR curves and their summaries from per-level counts of ink (a) and background (b).

    Thresholds run over the occupied levels from the top: a pixel is called ink when its level is at or above the
    threshold, so pixels on one level move together and a tie is never split. The ROC area by trapezoids over these
    steps equals the Mann-Whitney AUC with ties counted half. AP is the step sum of precision over recall gains
    (scikit-learn's average_precision_score).

    Bare AUCs with no control: a caller outside report_arrays must pair them with the same call on the reverse-depth
    control, or label them uncontrolled."""
    np = _numpy()
    P, N = float(a.sum()), float(b.sum())
    if P == 0 or N == 0:
        return None
    occ = np.flatnonzero((a + b) > 0)[::-1]
    tp, fp = np.cumsum(a[occ]), np.cumsum(b[occ])
    tpr, fpr = tp / P, fp / N
    prec = tp / (tp + fp)
    x, y = np.concatenate(([0.0], fpr)), np.concatenate(([0.0], tpr))
    roc_auc = float(((x[1:] - x[:-1]) * (y[1:] + y[:-1]) / 2).sum())
    ap = float(((y[1:] - y[:-1]) * prec).sum())
    ties = float((a * b).sum() / (P * N))
    f1 = np.where(prec + tpr > 0, 2 * prec * tpr / np.maximum(prec + tpr, 1e-300), 0.0)
    i = int(np.argmax(f1))
    j = int(np.argmax(tpr - fpr))
    at_fpr = {}
    for f in FPR_POINTS:
        ok = fpr <= f + 1e-12
        at_fpr[f"{f:g}"] = _r(tpr[ok].max() if ok.any() else 0.0)
    grid = np.linspace(0, 1, points)
    roc = np.interp(grid, x, y)                       # x never decreases: ROC drawn through its steps
    pmax = np.maximum.accumulate(prec[::-1])[::-1]    # interpolated precision: best at this recall or more
    k = np.minimum(np.searchsorted(tpr, grid, side="left"), len(tpr) - 1)
    pr = pmax[k]
    return {
        "auc": _r(roc_auc), "ap": _r(ap), "ink_share": _r(P / (P + N)),
        "ink_px": int(P), "background_px": int(N), "levels_used": int(len(occ)),
        "ties": {"tied_pair_share": _r(ties, 6), "auc_ties_as_losses": _r(roc_auc - ties / 2),
                 "auc_ties_as_wins": _r(roc_auc + ties / 2)},
        "tpr_at_fpr": at_fpr,
        "best_f1": {"f1": _r(f1[i]), "precision": _r(prec[i]), "recall": _r(tpr[i]),
                    "threshold_level": int(occ[i]), "called_ink_share": _r((tp[i] + fp[i]) / (P + N))},
        "youden": {"j": _r(tpr[j] - fpr[j]), "tpr": _r(tpr[j]), "fpr": _r(fpr[j]),
                   "balanced_accuracy": _r((tpr[j] + 1 - fpr[j]) / 2), "threshold_level": int(occ[j])},
        "roc": [[0.0, 0.0]] + [[_r(g), _r(v)] for g, v in zip(grid, roc)],   # best TPR at each FPR, from (0, 0)
        "pr": [[_r(g), _r(v)] for g, v in zip(grid, pr)],
    }


# ----------------------------------------------------------------------------------------------- regions and nulls

def tile_breakdown(q, ink, use, tile_px=TILE_PX, min_px=TILE_MIN_PX, origin=(0, 0)):
    """AUC per square tile of the map; a tile counts when it holds at least min_px of each class.

    Bare AUCs with no control: a caller outside report_arrays must pair them with the same call on the reverse-depth
    control, or label them uncontrolled."""
    np = _numpy()
    if tile_px < 8:
        raise VerifyError("tiles must be at least 8 px")
    H, W = use.shape
    tiles, small = [], 0
    for y0 in range(0, H, tile_px):
        for x0 in range(0, W, tile_px):
            sl = (slice(y0, min(H, y0 + tile_px)), slice(x0, min(W, x0 + tile_px)))
            u, i, v = use[sl], ink[sl], q[sl]
            ni, nb = int((u & i).sum()), int((u & ~i).sum())
            if ni < min_px or nb < min_px:
                small += bool(ni + nb)
                continue
            tiles.append({"y0": y0 + origin[0], "y1": min(H, y0 + tile_px) + origin[0],
                          "x0": x0 + origin[1], "x1": min(W, x0 + tile_px) + origin[1],
                          "auc": _r(auc.auc_scores(v[u & i], v[u & ~i])), "ink_px": ni, "background_px": nb})
    out = {"tile_px": tile_px, "min_px_each_class": min_px, "scored": len(tiles), "too_small": small,
           "tiles": tiles}
    if tiles:
        vals = np.array([t["auc"] for t in tiles])
        q25, med, q75 = np.percentile(vals, [25, 50, 75])
        worst = min(tiles, key=lambda t: t["auc"])
        out.update({"min": _r(vals.min()), "q25": _r(q25), "median": _r(med), "q75": _r(q75),
                    "max": _r(vals.max()), "at_or_below_half": int((vals <= 0.5).sum()),
                    "worst": {k: worst[k] for k in ("y0", "y1", "x0", "x1", "auc")}})
    return out


def _bbox(np, m):
    ys, xs = np.nonzero(m)
    if not len(ys):
        raise VerifyError("no supervised pixels left to score")
    return int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1


def shift_null(q, ink, sup, valid, draws=NULL_DRAWS, min_shift=auc.BLOCK_PX, seed=0, min_px=NULL_MIN_PX):
    """AUCs of the map against cyclic shifts of the labels inside their bounding box, and the p value of the real AUC.

    Ink and supervision move together, so each draw is the same labeled pattern laid elsewhere on the map. Shifts
    shorter than min_shift on both axes are refused, since nearby pixels share ink.

    Bare AUCs with no control: a caller outside report_arrays must pair them with the same call on the reverse-depth
    control, or label them uncontrolled."""
    np = _numpy()
    if draws < 20:
        raise VerifyError("use at least 20 null draws")
    y0, y1, x0, x1 = _bbox(np, sup)
    S, K, Q, V = sup[y0:y1, x0:x1], ink[y0:y1, x0:x1], q[y0:y1, x0:x1], valid[y0:y1, x0:x1]
    h, w = S.shape
    if h // 2 < min_shift and w // 2 < min_shift:
        raise VerifyError(f"the labeled area ({h} x {w} px) is too small for shifts of at least {min_shift} px; "
                          "lower --null-min-shift or switch the null off")
    u = S & V
    observed = auc.auc_scores(Q[u & K], Q[u & ~K])
    rng = np.random.default_rng(seed)
    vals, unusable, tries = [], 0, 0
    while len(vals) < draws and tries < draws * 20:
        tries += 1
        dy, dx = int(rng.integers(0, h)), int(rng.integers(0, w))
        if min(dy, h - dy) < min_shift and min(dx, w - dx) < min_shift:
            continue
        Ss, Ks = np.roll(S, (dy, dx), (0, 1)), np.roll(K, (dy, dx), (0, 1))
        us = Ss & V
        if (us & Ks).sum() < min_px or (us & ~Ks).sum() < min_px:
            unusable += 1
            continue
        vals.append(auc.auc_scores(Q[us & Ks], Q[us & ~Ks]))
    if len(vals) < 20:
        raise VerifyError(f"only {len(vals)} shifted copies kept enough labeled pixels on the map; the null needs 20")
    v = np.array(vals)
    sd = float(v.std(ddof=1))
    return {"draws": len(vals), "unusable_draws": unusable, "min_shift_px": min_shift, "seed": seed,
            "box": [y0, y1, x0, x1], "observed_auc": _r(observed), "null_mean": _r(v.mean()), "null_sd": _r(sd),
            "null_95th": _r(np.percentile(v, 95)), "null_max": _r(v.max()),
            "z": _r((observed - v.mean()) / sd, 2) if sd > 0 else None,
            "p": _r((1 + int((v >= observed).sum())) / (1 + len(v)))}


def _shift(np, arr, dy, dx):
    """out[y, x] = arr[y - dy, x - dx]; the vacated edge is False."""
    out = np.zeros_like(arr)
    H, W = arr.shape
    ys, yd = (slice(0, H - dy), slice(dy, H)) if dy >= 0 else (slice(-dy, H), slice(0, H + dy))
    xs, xd = (slice(0, W - dx), slice(dx, W)) if dx >= 0 else (slice(-dx, W), slice(0, W + dx))
    out[yd, xd] = arr[ys, xs]
    return out


def offset_scan(q, ink, sup, valid, radius, step=1, min_px=NULL_MIN_PX):
    """AUC with the labels moved by every (dy, dx) on a grid within radius px (same convention as --label-offset).

    Bare AUCs with no control: a caller outside report_arrays must pair them with the same call on the reverse-depth
    control, or label them uncontrolled."""
    np = _numpy()
    if radius < 1 or step < 1:
        raise VerifyError("the offset scan needs a radius and a step of at least 1 px")
    y0, y1, x0, x1 = _bbox(np, sup)
    H, W = sup.shape
    y0, y1, x0, x1 = max(0, y0 - radius), min(H, y1 + radius), max(0, x0 - radius), min(W, x1 + radius)
    S, K, Q, V = sup[y0:y1, x0:x1], ink[y0:y1, x0:x1], q[y0:y1, x0:x1], valid[y0:y1, x0:x1]
    grid = []
    for dy in range(-radius, radius + 1, step):
        for dx in range(-radius, radius + 1, step):
            Ss, Ks = _shift(np, S, dy, dx), _shift(np, K, dy, dx)
            us = Ss & V
            if (us & Ks).sum() < min_px or (us & ~Ks).sum() < min_px:
                continue
            grid.append({"dy": dy, "dx": dx, "auc": _r(auc.auc_scores(Q[us & Ks], Q[us & ~Ks]))})
    if not grid:
        raise VerifyError("no offset kept enough labeled pixels on the map")
    best = max(grid, key=lambda g: (g["auc"], -abs(g["dy"]) - abs(g["dx"])))
    zero = next((g["auc"] for g in grid if g["dy"] == 0 and g["dx"] == 0), None)
    edge = max(abs(best["dy"]), abs(best["dx"])) > radius - step
    return {"radius_px": radius, "step_px": step, "offsets": len(grid), "auc_at_zero": zero, "best": best,
            "gain": _r(best["auc"] - zero) if zero is not None else None, "best_at_scan_edge": bool(edge),
            "grid": grid,
            "note": "the best offset is picked on these labels: a diagnosis of registration, not a score"}


# ---------------------------------------------------------------------------------------------------------- report

def _check_finite(arr, name):
    s = finite.stats(arr)
    if not s["ok"]:
        raise finite.NonFinite(f"{name}: {s['why']}; kit auc scores no map holding NaN or Inf (replace them with 0 "
                               "for no prediction)")
    return {"ok": True, "min": s["min"], "max": s["max"], "constant": s["constant"]}


def report_arrays(pred, ink, sup, control=None, compare=None, keep_zero=False, inner=0, bootstrap=300,
                  block_px=auc.BLOCK_PX, tiles=TILE_PX, tile_min_px=TILE_MIN_PX, null=NULL_DRAWS,
                  null_min_shift=None, scan=0, scan_step=1, points=101, seed=0, origin=(0, 0)):
    """The full report for a map and boolean ink and supervision arrays on its grid."""
    np = _numpy()
    maps = {"map": pred}
    if control is not None:
        maps["control"] = control
    if compare is not None:
        maps["compare"] = compare
    for name, m in maps.items():
        if m.shape != pred.shape:
            raise VerifyError(f"{name} shape {m.shape} differs from the map's {pred.shape}")
    out = {"tool": "aucreport", "version": VERSION, "finite": {k: _check_finite(m, k) for k, m in maps.items()}}
    sup_in = auc._edge_mask(np, sup, inner)
    for name, m in maps.items():
        base = auc.score_array(m, ink, sup, keep_zero, inner)            # exactly kit auc's number
        q, _ = auc._quantize(np, m)
        use = sup_in & (np.ones_like(sup_in) if keep_zero else m != 0)
        base["curves"] = curve_stats(*_histograms(q, ink, use), points=points)
        out[name] = base
        if name == "map":
            q_map, use_map = q, use
    if out["map"]["auc"] is None:
        raise VerifyError(f"no AUC: ink {out['map']['ink_px']} px, background {out['map']['background_px']} px "
                          "in the mask")
    if compare is not None and not bootstrap:
        bootstrap = 300                      # as kit auc: a comparison always gets its interval
    if control is not None:
        out["control_gap"] = control_gap(pred, control, ink, sup_in, keep_zero)
        if bootstrap and out["control_gap"]["difference"] is not None:
            g = auc.block_bootstrap(pred, ink, sup, bootstrap, block_px, seed, control, keep_zero, inner)["compare"]
            out["control_gap"].update({"ci95": g["ci95"],
                                       "share_draws_control_not_behind": g["share_draws_map_not_ahead"]})
    out["controlled"] = (control is not None and out["control_gap"]["difference"] is not None
                         and not out["control_gap"]["control_constant"])
    if not out["controlled"]:
        out["warning"] = (UNCONTROLLED if control is None else
                          ("the control has no AUC on the pixels both maps scored: "
                           if out["control_gap"]["difference"] is None else
                           "the control is constant on the pixels both maps scored, so every pair ties and it cannot "
                           "fail: ") + UNCONTROLLED.split(": ", 1)[1])
    if compare is not None:
        out["compare"]["controlled"] = False
        out["compare"]["warning"] = COMPARE_UNCONTROLLED
    if bootstrap:
        out["bootstrap"] = auc.block_bootstrap(pred, ink, sup, bootstrap, block_px, seed, compare, keep_zero, inner)
    valid = np.ones_like(sup_in) if keep_zero else pred != 0
    if inner:
        valid = auc._edge_mask(np, valid, inner)
    if tiles:
        out["tiles"] = tile_breakdown(q_map, ink, use_map, tiles, tile_min_px, origin)
    if null:
        out["null"] = shift_null(q_map, ink, sup_in, valid, null,
                                 null_min_shift if null_min_shift is not None else block_px, seed)
    if scan:
        out["offset_scan"] = offset_scan(q_map, ink, sup_in, valid, scan, scan_step)
    return out


def control_gap(pred, control, ink, sup, keep_zero=False):
    """Map minus control on the pixels both scored (each map's exact AUC there), so a control that predicts on fewer
    pixels cannot move the gap by changing the population. sup should already have its edge removed."""
    np = _numpy()
    shared = sup if keep_zero else sup & (pred != 0) & (control != 0)
    qm, _ = auc._quantize(np, pred)
    qc, _ = auc._quantize(np, control)
    a = auc.auc_scores(qm[shared & ink], qm[shared & ~ink])
    b = auc.auc_scores(qc[shared & ink], qc[shared & ~ink])
    return {"auc_map_shared": _r(a), "auc_control_shared": _r(b),
            "difference": _r(a - b) if a is not None and b is not None else None,
            "shared_px": int(shared.sum()), "ci95": None,
            "control_constant": bool(shared.any()) and int(np.unique(qc[shared]).size) == 1}


def _load_map(path):
    np = _numpy()
    m = np.squeeze(auc._load(path))
    if m.ndim != 2:
        raise VerifyError(f"{path}: expected a 2D map, got shape {m.shape}")
    return m


def score_files(prediction, labels, mask, control=None, compare=None, level=auc.DEFAULT_LEVEL, crop=None,
                surface_shape=None, keep_zero=False, inner=0, offset=None, exclude=None, exclude_margin=0, **kw):
    pred = _load_map(prediction)
    if surface_shape is None:
        if crop is not None:
            raise VerifyError("a cropped map needs the full surface shape (surface_shape)")
        surface_shape = pred.shape
    if exclude_margin and not exclude:
        raise VerifyError("an exclusion margin needs at least one exclusion box")
    if control is not None and auc._same_file(control, prediction):
        raise VerifyError(f"control {control} is the map itself; give the reverse-depth map as the control")
    off = tuple(int(v) for v in offset) if offset is not None else (0, 0)
    ink, sup = labels_on_map(labels, mask, level, surface_shape, crop, pred.shape, off)
    excluded = None
    if exclude:
        sup, excluded = exclude_boxes(ink, sup, exclude, surface_shape, crop, exclude_margin)
    ctrl = _load_map(control) if control is not None else None
    other = _load_map(compare) if compare is not None else None
    origin = (crop[0], crop[2]) if crop is not None else (0, 0)
    out = report_arrays(pred, ink, sup, ctrl, other, keep_zero, inner, origin=origin, **kw)
    out["files"] = {"prediction": str(prediction), "labels": str(labels), "mask": str(mask),
                    "control": None if control is None else str(control),
                    "compare": None if compare is None else str(compare)}
    out.update({"level": level, "crop": crop, "label_offset": list(off) if offset is not None else None,
                "excluded": excluded})
    return out


# ------------------------------------------------------------------------------------------------------------ pool

def pool(reports, draws=2000, seed=0):
    """Combine per-segment results (aucreport or kit auc --json) into segment-level numbers."""
    np = _numpy()
    rows = []
    for name, r in reports:
        m = r.get("map") or r.get("forward")
        if not m or m.get("auc") is None:
            raise VerifyError(f"{name}: no map AUC in this file")
        c = r.get("control") or {}
        g = (r.get("control_gap") or {}).get("difference")
        if "control_gap" not in r and c.get("auc") is not None:
            g = _r(m["auc"] - c["auc"])          # a kit auc file: each map on its own pixels
        rows.append({"segment": name, "auc": m["auc"], "control_auc": c.get("auc"), "control_gap": g,
                     "controlled": g is not None, "ink_px": m["ink_px"],
                     "ap": (m.get("curves") or {}).get("ap"), "ink_share": (m.get("curves") or {}).get("ink_share")})
    v = np.array([x["auc"] for x in rows], float)
    w = np.array([x["ink_px"] for x in rows], float)
    out = {"segments": len(rows), "rows": rows, "mean_auc": _r(v.mean()), "min_auc": _r(v.min()),
           "max_auc": _r(v.max()), "ink_weighted_mean_auc": _r((v * w).sum() / w.sum())}
    gaps = [x["control_gap"] for x in rows if x["control_gap"] is not None]
    out["uncontrolled_segments"] = sum(not x["controlled"] for x in rows)
    out["controlled"] = out["uncontrolled_segments"] == 0
    if out["uncontrolled_segments"]:
        out["warning"] = (f"{out['uncontrolled_segments']} of {len(rows)} segments have no reverse-depth control: "
                          "the pooled numbers are not a result")
    if gaps:
        out["control"] = {"segments": len(gaps), "mean_gap": _r(sum(gaps) / len(gaps)),
                          "segments_map_ahead": int(sum(g > 0 for g in gaps))}
    if len(rows) >= POOL_MIN_SEGMENTS:
        rng = np.random.default_rng(seed)
        means = v[rng.integers(0, len(v), (draws, len(v)))].mean(1)
        lo, hi = np.percentile(means, [2.5, 97.5])
        out["segment_bootstrap"] = {"draws": draws, "seed": seed, "ci95": [_r(lo), _r(hi)]}
    else:
        out["segment_bootstrap"] = None
        out["note"] = f"no interval over segments below {POOL_MIN_SEGMENTS} segments"
    return out


# ------------------------------------------------------------------------------------------------- plots and files

def write_curves_csv(report, path):
    lines = ["map,curve,x,y"]
    for name in ("map", "control", "compare"):
        cs = (report.get(name) or {}).get("curves")
        if not cs:
            continue
        lines += [f"{name},roc,{x},{y}" for x, y in cs["roc"]]
        lines += [f"{name},pr,{x},{y}" for x, y in cs["pr"]]
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


COLORS = {"map": "#2f6db5", "control": "#c8742c", "compare": "#6c8f3a"}


def write_svg(report, path, title=None):
    """ROC and precision-recall panels as a standalone SVG (no plotting library needed)."""
    S, P, G = 300, 46, 40           # panel side, padding, gap
    controlled = report.get("controlled", (report.get("control_gap") or {}).get("difference") is not None)
    warn = []
    if not controlled:
        words, line = ("UNCONTROLLED: " + report.get("warning", UNCONTROLLED)).split(), ""
        for w in words:
            if line and len(line) + 1 + len(w) > 105:
                warn.append(line)
                line = w
            else:
                line = f"{line} {w}" if line else w
        warn.append(line)
    top = 16 * len(warn)
    W, H = 2 * (S + P) + G + 10, S + 2 * P + 30 + top
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           'font-family="Helvetica, Arial, sans-serif" font-size="12">',
           f'<rect width="{W}" height="{H}" fill="#ffffff"/>']
    if title:
        out.append(f'<text x="{W / 2}" y="18" text-anchor="middle" font-size="14">{_xml(title)}</text>')
    for n, text in enumerate(warn):
        out.append(f'<text x="{W / 2}" y="{36 + 16 * n}" text-anchor="middle" fill="#b00020" '
                   f'font-weight="bold">{_xml(text)}</text>')
    tag = "" if controlled else " [uncontrolled]"
    share = report["map"]["curves"]["ink_share"]
    for k, (curve, xl, yl, base) in enumerate((("roc", "false positive rate", "true positive rate", None),
                                               ("pr", "recall", "precision", share))):
        ox, oy = P + k * (S + P + G), P + 10 + top
        X = lambda v: ox + v * S
        Y = lambda v: oy + (1 - v) * S
        for t in (0, 0.25, 0.5, 0.75, 1):
            out.append(f'<line x1="{X(t):.1f}" y1="{oy}" x2="{X(t):.1f}" y2="{oy + S}" stroke="#e6e6e6"/>')
            out.append(f'<line x1="{ox}" y1="{Y(t):.1f}" x2="{ox + S}" y2="{Y(t):.1f}" stroke="#e6e6e6"/>')
            out.append(f'<text x="{X(t):.1f}" y="{oy + S + 15}" text-anchor="middle" fill="#555">{t:g}</text>')
            out.append(f'<text x="{ox - 6}" y="{Y(t) + 4:.1f}" text-anchor="end" fill="#555">{t:g}</text>')
        out.append(f'<rect x="{ox}" y="{oy}" width="{S}" height="{S}" fill="none" stroke="#999"/>')
        if base is None:
            out.append(f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(1)}" y2="{Y(1)}" stroke="#aaa" stroke-dasharray="4 4"/>')
        else:
            out.append(f'<line x1="{X(0)}" y1="{Y(base):.1f}" x2="{X(1)}" y2="{Y(base):.1f}" stroke="#aaa" '
                       'stroke-dasharray="4 4"/>')
        out.append(f'<text x="{ox + S / 2}" y="{oy + S + 32}" text-anchor="middle">{xl}</text>')
        out.append(f'<text transform="translate({ox - 34},{oy + S / 2}) rotate(-90)" text-anchor="middle">{yl}</text>')
        legend = []
        for name in ("map", "control", "compare"):
            cs = (report.get(name) or {}).get("curves")
            if not cs:
                continue
            pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in cs[curve])
            dash = ' stroke-dasharray="6 3"' if name == "control" else ""
            out.append(f'<polyline points="{pts}" fill="none" stroke="{COLORS[name]}" stroke-width="2"{dash}/>')
            legend.append((name, (f"{name} AUC {cs['auc']:.3f}" if curve == "roc" else f"{name} AP {cs['ap']:.3f}")
                           + (COMPARE_TAG if name == "compare" else "") + tag))
        if base is not None:
            legend.append((None, f"ink share {base:.3f}"))
        lx = ox + S - max(150, min(S - 4, 34 + 6.2 * max(len(t) for _, t in legend)))
        ly0 = oy + 16 + (S - 30 - 16 * len(legend) if curve == "roc" else 0)
        out.append(f'<rect x="{lx - 4:.1f}" y="{ly0 - 13}" width="{ox + S - lx:.1f}" height="{16 * len(legend) + 4}" '
                   'fill="#ffffff" fill-opacity="0.85"/>')
        for n, (name, text) in enumerate(legend):
            ly = ly0 + 16 * n
            color = COLORS.get(name, "#888")
            out.append(f'<line x1="{lx}" y1="{ly - 4}" x2="{lx + 18}" y2="{ly - 4}" stroke="{color}" stroke-width="2"/>')
            out.append(f'<text x="{lx + 24}" y="{ly}">{_xml(text)}</text>')
    out.append("</svg>")
    with open(path, "w") as fh:
        fh.write("\n".join(out) + "\n")


def _xml(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ------------------------------------------------------------------------------------------------------------ text

def format_report(r):
    rows = _report_rows(r)
    if not r.get("controlled", "control" in r):
        rows = [f"UNCONTROLLED: {r.get('warning', UNCONTROLLED)}"] + [row + " [uncontrolled]" for row in rows]
    return "\n".join(rows)


def _report_rows(r):
    rows = []
    m = r["map"]
    cs = m["curves"]
    rows.append(f"map: AUC {m['auc']:.4f} on {m['ink_px']} ink and {m['background_px']} background px "
                f"(the same number as kit auc)")
    if r.get("label_offset"):
        rows.append(f"labels moved by dy {r['label_offset'][0]:+d}, dx {r['label_offset'][1]:+d} px")
    if r.get("excluded"):
        e = r["excluded"]
        rows.append(f"excluded {len(e['boxes'])} box(es): {e['supervised_px_removed']} supervised px removed, "
                    f"{e['ink_share_kept']} of the labeled ink kept")
    b = r.get("bootstrap")
    if b:
        rows.append(f"  95 % interval {b['ci95'][0]:.4f} to {b['ci95'][1]:.4f} ({b['draws']} draws of "
                    f"{b['blocks']} blocks of {b['block_px']} px)")
    rows.append(f"  AP {cs['ap']:.4f} against an ink share of {cs['ink_share']:.4f} (a map with no skill scores "
                "about the ink share)")
    t = cs["tpr_at_fpr"]
    rows.append("  true-positive rate at " + ", ".join(f"{float(k) * 100:g} % false positives {v:.3f}"
                                                      for k, v in t.items()))
    bf, yj = cs["best_f1"], cs["youden"]
    rows.append(f"  best F1 {bf['f1']:.3f} (precision {bf['precision']:.3f}, recall {bf['recall']:.3f}, "
                f"{bf['called_ink_share'] * 100:.1f} % of pixels called ink); Youden J {yj['j']:.3f}, "
                f"balanced accuracy {yj['balanced_accuracy']:.3f}")
    ti = cs["ties"]
    rows.append(f"  ties: {ti['tied_pair_share'] * 100:.3f} % of pairs on {cs['levels_used']} levels; AUC "
                f"{ti['auc_ties_as_losses']:.4f} to {ti['auc_ties_as_wins']:.4f} if ties all lost or all won")
    if "control" in r:
        c = r["control"]
        g = r.get("control_gap") or {}
        rows.append(f"control: AUC {c['auc']:.4f}, AP {c['curves']['ap']:.4f}" if c["auc"] is not None
                    else "control: no AUC")
        if g.get("difference") is None:
            rows.append(f"  map minus control: no AUC on the {g.get('shared_px', 0)} px both maps scored")
        else:
            line = (f"  map minus control {g['difference']:+.4f} on the {g['shared_px']} px both scored (map "
                    f"{g['auc_map_shared']:.4f}, control {g['auc_control_shared']:.4f})")
            if g.get("ci95"):
                verdict = ("ahead of its control beyond sampling noise" if g["ci95"][0] > 0 else
                           "behind its control beyond sampling noise" if g["ci95"][1] < 0 else
                           "not distinguishable from its control")
                line += f", 95 % interval {g['ci95'][0]:+.4f} to {g['ci95'][1]:+.4f}: {verdict}"
            rows.append(line)
    if "compare" in r and b and b.get("compare"):
        c = b["compare"]
        verdict = ("ahead beyond sampling noise" if c["ci95"][0] > 0 else
                   "behind beyond sampling noise" if c["ci95"][1] < 0 else "not distinguishable from noise")
        rows.append(f"compared map: AUC {r['compare']['auc']:.4f}; map minus it {c['difference']:+.4f}, 95 % "
                    f"interval {c['ci95'][0]:+.4f} to {c['ci95'][1]:+.4f}: {verdict}{COMPARE_TAG}")
    t = r.get("tiles")
    if t:
        if t["scored"]:
            w = t["worst"]
            rows.append(f"tiles of {t['tile_px']} px: {t['scored']} scored ({t['too_small']} too small), AUC "
                        f"{t['min']:.3f} / {t['median']:.3f} / {t['max']:.3f} (min / median / max), "
                        f"{t['at_or_below_half']} at or below 0.5; worst y {w['y0']}:{w['y1']}, x {w['x0']}:{w['x1']}")
        else:
            rows.append(f"tiles of {t['tile_px']} px: none holds {t['min_px_each_class']} px of each class")
    n = r.get("null")
    if n:
        rows.append(f"shifted-label null: {n['draws']} shifts of at least {n['min_shift_px']} px, null AUC "
                    f"{n['null_mean']:.4f} +- {n['null_sd']:.4f} (95th {n['null_95th']:.4f}); real {n['observed_auc']:.4f}, "
                    f"p = {n['p']:.4f}" + (f", z {n['z']:.1f}" if n["z"] is not None else ""))
    s = r.get("offset_scan")
    if s:
        bst = s["best"]
        rows.append(f"offset scan within {s['radius_px']} px: AUC {s['auc_at_zero']} at (0, 0), best {bst['auc']:.4f} "
                    f"at dy {bst['dy']:+d}, dx {bst['dx']:+d}" + (" (at the scan edge: widen it)"
                                                                 if s["best_at_scan_edge"] else "")
                    + "; a diagnosis, not a score")
    return rows


def format_pool(p):
    rows = [f"{x['segment']}: AUC {x['auc']:.4f}" + (f", control {x['control_auc']:.4f}, gap {x['control_gap']:+.4f}"
                                                    if x["controlled"] else " [uncontrolled]") for x in p["rows"]]
    rows.append(f"{p['segments']} segments: mean AUC {p['mean_auc']:.4f} (min {p['min_auc']:.4f}, max "
                f"{p['max_auc']:.4f}; weighted by ink px {p['ink_weighted_mean_auc']:.4f})")
    if p.get("control"):
        c = p["control"]
        rows.append(f"map ahead of its control on {c['segments_map_ahead']} of {c['segments']} segments, mean gap "
                    f"{c['mean_gap']:+.4f}")
    sb = p.get("segment_bootstrap")
    rows.append(f"95 % interval over segments {sb['ci95'][0]:.4f} to {sb['ci95'][1]:.4f}" if sb else p["note"])
    if p.get("uncontrolled_segments"):
        n = len(p["rows"])
        rows = ([f"UNCONTROLLED: {p['warning']}"] + rows[:n]
                + [row + " [uncontrolled]" for row in rows[n:]])
    return "\n".join(rows)


# ------------------------------------------------------------------------------------------------------------ demo

def demo_arrays(seed=0, shape=(640, 640)):
    """Synthetic labels and maps: text-like ink strokes, a map that reads them with noise, and its reverse."""
    np = _numpy()
    rng = np.random.default_rng(seed)
    H, W = shape
    ink = np.zeros(shape, bool)
    for y in range(40, H - 40, 48):                 # lines of strokes
        x = 30
        while x < W - 40:
            w = int(rng.integers(8, 26))
            ink[y:y + int(rng.integers(14, 24)), x:x + w] = True
            x += w + int(rng.integers(6, 20))
    sup = np.zeros(shape, bool)
    sup[20:H - 20, 20:W - 20] = True
    smooth = lambda a: (a + np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1)) / 5
    noise = smooth(smooth(rng.normal(0, 1, shape)))
    pred = 1 / (1 + np.exp(-(1.0 * ink + 2.2 * noise - 0.7)))
    rev = 1 / (1 + np.exp(-(0.15 * ink + 2.2 * smooth(smooth(rng.normal(0, 1, shape))) - 0.7)))
    return pred.astype(np.float32), rev.astype(np.float32), ink, sup


# ------------------------------------------------------------------------------------------------------------- CLI

def _common(p):
    p.add_argument("--keep-zero", action="store_true", help="count pixels where a map is exactly 0")
    p.add_argument("--inner", type=int, default=0, metavar="PX", help="leave out this many px at every edge")
    p.add_argument("--bootstrap", type=int, default=300, metavar="N", help="block-bootstrap draws (0: none)")
    p.add_argument("--block-px", type=int, default=auc.BLOCK_PX, help="bootstrap block side (default 107: 1 mm)")
    p.add_argument("--tiles", type=int, default=TILE_PX, metavar="PX", help="tile side for the per-region AUC "
                   "(default 534: 5 mm; 0: none)")
    p.add_argument("--tile-min-px", type=int, default=TILE_MIN_PX, help="pixels of each class a tile needs")
    p.add_argument("--null", type=int, default=NULL_DRAWS, metavar="N", help="shifted-label null draws (0: none)")
    p.add_argument("--null-min-shift", type=int, metavar="PX", help="shortest shift (default: the block size)")
    p.add_argument("--offset-scan", type=int, default=0, metavar="R", help="AUC at every label offset within R px")
    p.add_argument("--offset-step", type=int, default=1, metavar="PX")
    p.add_argument("--points", type=int, default=101, help="points per curve in the output")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--plot", metavar="FILE.svg", help="write ROC and precision-recall curves as SVG")
    p.add_argument("--curves", metavar="FILE.csv", help="write the curve points as CSV")
    p.add_argument("--out", metavar="FILE.json", help="write the full report as JSON")
    p.add_argument("--json", action="store_true", help="print the report as JSON")


def _kw(a):
    return {"bootstrap": a.bootstrap, "block_px": a.block_px, "tiles": a.tiles, "tile_min_px": a.tile_min_px,
            "null": a.null, "null_min_shift": a.null_min_shift, "scan": a.offset_scan, "scan_step": a.offset_step,
            "points": a.points, "seed": a.seed}


def _parser():
    p = argparse.ArgumentParser(prog="python -m kit.aucreport", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="full report for one map of a labeled segment")
    s.add_argument("prediction", help="ink map (.tif or .npy) on the 9 um surface grid")
    s.add_argument("--labels", required=True, help="inklabels.zarr of the segment")
    s.add_argument("--mask", required=True, help="supervision.zarr of the segment")
    s.add_argument("--control", help="reverse-depth map of the same surface")
    s.add_argument("--compare", metavar="MAP", help="second map of the same surface, scored on the same pixels")
    s.add_argument("--level", default=auc.DEFAULT_LEVEL, help="label pyramid level matching the 9 um grid")
    s.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"))
    s.add_argument("--surface-shape", type=int, nargs=2, metavar=("H", "W"))
    s.add_argument("--label-offset", type=int, nargs=2, metavar=("DY", "DX"), help="move the labels by (dy, dx) px")
    s.add_argument("--exclude", type=int, nargs=4, action="append", metavar=("Y0", "Y1", "X0", "X1"),
                   help="leave a box of the surface grid out of the supervision (repeat for more)")
    s.add_argument("--exclude-margin", type=int, default=0, metavar="PX")
    _common(s)
    q = sub.add_parser("pool", help="combine reports (or kit auc --json files) of several segments")
    q.add_argument("reports", nargs="+")
    q.add_argument("--seed", type=int, default=0)
    q.add_argument("--json", action="store_true")
    d = sub.add_parser("demo", help="the full report on synthetic data (no files needed)")
    _common(d)
    return p


def _emit(a, report, text):
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(report, fh, indent=2)
    if getattr(a, "plot", None):
        write_svg(report, a.plot, title=getattr(a, "prediction", "synthetic demo"))
    if getattr(a, "curves", None):
        write_curves_csv(report, a.curves)
    print(json.dumps(report, indent=2) if a.json else text)


def main(argv=None):
    a = _parser().parse_args(argv)
    if sys.stdout.isatty() and not getattr(a, "json", False):   # the Scrolls look (AGENTS.md rule 17)
        from . import termstyle
        termstyle.script()
    try:
        if a.cmd == "score":
            r = score_files(a.prediction, a.labels, a.mask, a.control, a.compare, a.level, a.crop,
                            a.surface_shape, a.keep_zero, a.inner, a.label_offset, a.exclude, a.exclude_margin, **_kw(a))
            _emit(a, r, format_report(r))
        elif a.cmd == "demo":
            pred, rev, ink, sup = demo_arrays(a.seed)
            r = report_arrays(pred, ink, sup, rev, None, a.keep_zero, a.inner, **_kw(a))
            r["files"] = {"prediction": "synthetic demo map", "control": "synthetic reverse map"}
            _emit(a, r, format_report(r))
        else:
            reps = []
            for path in a.reports:
                with open(path) as fh:
                    reps.append((path, json.load(fh)))
            p = pool(reps, seed=a.seed)
            print(json.dumps(p, indent=2) if a.json else format_pool(p))
    except finite.NonFinite as exc:
        print(exc, file=sys.stderr)
        return EXIT_NONFINITE
    except (VerifyError, OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return EXIT_INPUT
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
