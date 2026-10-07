"""Pixel AUC of an ink map against a segment's published ink labels.

On a labelled segment no model was trained on (PHerc0139 w045 for ink_9um and v8in), this
is the generalization number: the chance that a labelled ink pixel scores above a
labelled non-ink pixel. Only pixels inside the supervision mask count, because the
labellers marked ink and non-ink there and nowhere else. Reference values (Community
reports, not checked here): `ink_9um` on PHerc0841 team surfaces, 0.74 to 0.81 (Bullo27);
on the PHerc0139 title, 0.81 to 0.95 depending on the checkpoint (Nieuwlaar).

The labels sit on the 2.4 um scan's grid. Its pyramid level 2 is the 9 um surface grid up
to a uniform scale (w045: 5,820 x 8,020 labels for 5,980 x 8,240 surface pixels), so labels
are mapped onto the map by nearest neighbour, and a scale that differs between the axes is
refused. A map that covers only a window of the surface gives that window with `crop` and
the full surface shape with `surface_shape`.

The reverse-direction map is the control: it reads the same CT, so it is shown the same
ink, but in the wrong depth order. A forward AUC well above the reverse AUC says the model
reads ink, not just brightness.

Pixels where the map is exactly 0 are left out by default: villa and v8in write 0 where
they made no prediction (outside the surface). The count is reported.

Sampling noise: a segment's labels cover about 1 cm2 (PHerc0841: 0.9 to 1.4 cm2 each), and
neighbouring pixels are not independent, so an AUC carries more noise than its pixel count
suggests. `bootstrap` resamples square blocks (default 107 px, 1 mm at 9.366 um) with
replacement and reports a 95 % interval; `compare` scores a second map on the same pixels
with the same draws and reports the difference, its interval, and the share of draws in
which the first map is not ahead. On PHerc0841 a strong map's interval is +-0.01 to +-0.04,
so a ranking by a smaller margin on one segment is noise (docs/logs/2026-10-07-overlap-and-baseline.md).
"""

from .layers import _zarr
from .verify import VerifyError, _numpy, load_map

DEFAULT_LEVEL = "2"
MAX_AXIS_MISMATCH = 0.005
BLOCK_PX = 107          # 1 mm at 9.366 um
BOOT_BINS = 1024        # score bins for the resampled AUCs (the point estimate stays exact)


def _load(path):
    np = _numpy()
    if str(path).endswith(".npy"):
        return np.load(path)
    return load_map(path)


def _levels(path, level):
    zarr = _zarr()
    try:
        node = zarr.open(str(path), mode="r")
    except Exception as exc:  # zarr raises several types for a missing or malformed store
        raise VerifyError(f"cannot open {path} as zarr: {exc}") from exc
    if not hasattr(node, "shape"):
        if level not in node:
            raise VerifyError(f"{path}: no level {level!r}; levels: {sorted(node.keys())}")
        node = node[level]
    return node


def _quantize(np, values):
    """Integer scores for exact histogram AUC: uint8 and uint16 as is, floats to 0..65535."""
    if values.dtype in (np.uint8, np.uint16):
        return values.astype(np.int64), 65536
    v = values.astype(np.float64)
    top = float(v.max()) if v.size else 1.0
    if top > 1.0:
        v = v / (255.0 if top <= 255 else 65535.0)
    return np.clip(np.round(v * 65535), 0, 65535).astype(np.int64), 65536


def auc_scores(ink_scores, background_scores):
    """Mann-Whitney AUC with ties counted half.

    The two arrays must be on one scale. score_array quantizes the whole map once before
    splitting it, so a float map is never scaled differently for ink and for background."""
    np = _numpy()
    if len(ink_scores) == 0 or len(background_scores) == 0:
        return None
    if ink_scores.dtype != np.int64 or background_scores.dtype != np.int64:
        both, _ = _quantize(np, np.concatenate([ink_scores.ravel(), background_scores.ravel()]))
        ink_scores, background_scores = both[:ink_scores.size], both[ink_scores.size:]
    a, b, n = ink_scores, background_scores, 65536
    ha = np.bincount(a, minlength=n).astype(np.float64)
    hb = np.bincount(b, minlength=n).astype(np.float64)
    below = np.concatenate(([0.0], np.cumsum(hb)[:-1]))  # background strictly below each score
    wins = float((ha * below).sum() + 0.5 * (ha * hb).sum())
    return wins / (float(ha.sum()) * float(hb.sum()))


def label_grid(labels_shape, surface_shape, crop, map_shape):
    """Row and column indices into the labels for every map pixel (nearest neighbour)."""
    np = _numpy()
    sy = labels_shape[0] / surface_shape[0]
    sx = labels_shape[1] / surface_shape[1]
    if abs(sy - sx) > MAX_AXIS_MISMATCH * max(sy, sx):
        raise VerifyError(f"labels {labels_shape} and surface {surface_shape} differ in scale between axes "
                          f"({sy:.4f} vs {sx:.4f}); they are not the same grid")
    y0, y1, x0, x1 = crop if crop is not None else (0, surface_shape[0], 0, surface_shape[1])
    if not (0 <= y0 < y1 <= surface_shape[0] and 0 <= x0 < x1 <= surface_shape[1]):
        raise VerifyError(f"crop {[y0, y1, x0, x1]} is outside the {surface_shape[0]} x {surface_shape[1]} surface")
    if (y1 - y0, x1 - x0) != tuple(map_shape):
        raise VerifyError(f"map shape {tuple(map_shape)} does not match the window {y1 - y0} x {x1 - x0}")
    rows = np.minimum(((np.arange(y0, y1) + 0.5) * sy).astype(np.int64), labels_shape[0] - 1)
    cols = np.minimum(((np.arange(x0, x1) + 0.5) * sx).astype(np.int64), labels_shape[1] - 1)
    return rows, cols


def labels_on_map(labels, mask, level, surface_shape, crop, map_shape):
    """Boolean ink and supervision arrays on the map's own grid."""
    np = _numpy()
    lab = _levels(labels, level)
    msk = _levels(mask, level)
    if lab.shape != msk.shape:
        raise VerifyError(f"labels {lab.shape} and mask {msk.shape} differ in shape at level {level}")
    rows, cols = label_grid(lab.shape, surface_shape, crop, map_shape)
    r0, r1, c0, c1 = int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1
    ink = np.asarray(lab[r0:r1, c0:c1])[np.ix_(rows - r0, cols - c0)] > 0
    supervised = np.asarray(msk[r0:r1, c0:c1])[np.ix_(rows - r0, cols - c0)] > 0
    return ink, supervised


def score_array(prediction, ink, mask, keep_zero=False, inner=0):
    """AUC of a 2D map against same-shape boolean ink and mask arrays.

    inner > 0 leaves out that many pixels along every edge of the map, where a map inferred on
    a cropped input saw less context than the same pixels of a whole-segment map."""
    np = _numpy()
    if inner:
        if 2 * inner >= min(prediction.shape):
            raise VerifyError(f"inner {inner} leaves nothing of a {prediction.shape} map")
        mask = mask.copy()
        mask[:inner] = mask[-inner:] = False
        mask[:, :inner] = mask[:, -inner:] = False
    q, _ = _quantize(np, prediction)   # one scale for the whole map
    use = mask & (np.ones_like(mask) if keep_zero else prediction != 0)
    result = {
        "auc": auc_scores(q[use & ink], q[use & ~ink]),
        "ink_px": int((use & ink).sum()),
        "background_px": int((use & ~ink).sum()),
        "zero_px_in_mask": int((mask & (prediction == 0)).sum()),
        "zero_px_counted": bool(keep_zero),
        "inner": inner,
    }
    if result["auc"] is not None:
        result["auc"] = round(result["auc"], 4)
    return result


def _edge_mask(np, mask, inner):
    if inner:
        mask = mask.copy()
        mask[:inner] = mask[-inner:] = False
        mask[:, :inner] = mask[:, -inner:] = False
    return mask


def _auc_hist(np, a, b):
    """AUC from per-bin counts of ink (a) and background (b), ties half; works on stacks."""
    below = np.cumsum(b, axis=-1) - b
    return ((a * below).sum(-1) + 0.5 * (a * b).sum(-1)) / (a.sum(-1) * b.sum(-1))


def _block_ids(np, keys):
    """Sorted occupied block IDs without sorting every pixel when the grid is dense.

    Keep the counting workspace bounded by pixel count; sparse, very large coordinate
    ranges retain the original unique/sort path rather than allocating by canvas area.
    """
    slots = int(keys.max()) + 1
    if slots > max(4096, 4 * len(keys)):
        return np.unique(keys, return_inverse=True)
    occupied = np.bincount(keys, minlength=slots) > 0
    blocks = np.flatnonzero(occupied)
    inverse = np.cumsum(occupied, dtype=np.int64)[keys] - 1
    return blocks, inverse


def _compact_histograms(np, hists, weights):
    """Remove globally empty score columns when reductions remain integer-exact.

    At <=2**26 pixels, all nonnegative count products, cumulative sums and half ties
    are exactly representable in float64. Check both the original population and every
    draw. Larger populations keep the historical reduction layout unchanged.
    """
    counts = (hists[0][0] + hists[0][1]).sum(1)
    if counts.sum() > 2 ** 26 or (weights @ counts).max() > 2 ** 26:
        return hists
    occupied = np.zeros(BOOT_BINS, dtype=bool)
    for hi, hb in hists:
        occupied |= (hi + hb).any(0)
    if occupied.all():
        return hists
    return [(hi[:, occupied], hb[:, occupied]) for hi, hb in hists]


def block_bootstrap(prediction, ink, mask, draws=300, block_px=BLOCK_PX, seed=0, other=None,
                    keep_zero=False, inner=0):
    """Block-bootstrap interval of the AUC, and of the difference to `other` (same pixels, same draws)."""
    np = _numpy()
    if draws < 20:
        raise VerifyError("use at least 20 bootstrap draws")
    if block_px < 1:
        raise VerifyError("block size must be at least 1 px")
    mask = _edge_mask(np, mask, inner)
    use = mask & (np.ones_like(mask) if keep_zero else prediction != 0)
    maps = [prediction]
    if other is not None:
        if other.shape != prediction.shape:
            raise VerifyError(f"compared map shape {other.shape} differs from the map's {prediction.shape}")
        use &= (np.ones_like(mask) if keep_zero else other != 0)
        maps.append(other)
    ys, xs = np.nonzero(use)
    if len(ys) == 0:
        raise VerifyError("no supervised pixels to resample")
    keys = (ys // block_px) * (prediction.shape[1] // block_px + 1) + xs // block_px
    blocks, inv = _block_ids(np, keys)
    lab = ink[ys, xs]
    if lab.all() or not lab.any():
        raise VerifyError("the mask holds only one class; no AUC to resample")
    hists = []
    for m in maps:
        q, _ = _quantize(np, m)
        top = 255 if m.dtype == np.uint8 else 65535   # _quantize keeps uint8 as 0..255
        qb = q[ys, xs] * (BOOT_BINS - 1) // top
        count = len(blocks) * BOOT_BINS
        indices = inv * BOOT_BINS + qb
        hi = np.bincount(indices[lab], minlength=count).reshape(len(blocks), BOOT_BINS).astype(np.float64)
        hb = np.bincount(indices[~lab], minlength=count).reshape(len(blocks), BOOT_BINS).astype(np.float64)
        hists.append((hi, hb))
    rng = np.random.default_rng(seed)
    w = np.stack([np.bincount(rng.integers(0, len(blocks), len(blocks)), minlength=len(blocks))
                  for _ in range(draws)]).astype(np.float64)
    hists = _compact_histograms(np, hists, w)
    stats = [_auc_hist(np, w @ hi, w @ hb) for hi, hb in hists]
    lo, hi_ = np.percentile(stats[0], [2.5, 97.5])
    result = {"draws": draws, "block_px": block_px, "blocks": int(len(blocks)), "seed": seed,
              "ci95": [round(float(lo), 4), round(float(hi_), 4)], "half_width": round(float(hi_ - lo) / 2, 4)}
    if other is not None:
        full = [float(_auc_hist(np, hi.sum(0), hb.sum(0))) for hi, hb in hists]
        diff = stats[0] - stats[1]
        dlo, dhi = np.percentile(diff, [2.5, 97.5])
        result["compare"] = {
            "auc_map": round(full[0], 4), "auc_other": round(full[1], 4), "difference": round(full[0] - full[1], 4),
            "ci95": [round(float(dlo), 4), round(float(dhi), 4)],
            "share_draws_map_not_ahead": round(float((diff <= 0).mean()), 4),
            "pixels": int(len(ys)),
        }
    return result


def score_files(prediction, labels, mask, control=None, level=DEFAULT_LEVEL, crop=None,
                surface_shape=None, keep_zero=False, inner=0, bootstrap=0, block_px=BLOCK_PX,
                compare=None, seed=0):
    np = _numpy()
    pred = np.squeeze(_load(prediction))
    if pred.ndim != 2:
        raise VerifyError(f"{prediction}: expected a 2D map, got shape {pred.shape}")
    if surface_shape is None:
        if crop is not None:
            raise VerifyError("a cropped map needs the full surface shape (surface_shape)")
        surface_shape = pred.shape
    ink, supervised = labels_on_map(labels, mask, level, surface_shape, crop, pred.shape)
    result = {"forward": score_array(pred, ink, supervised, keep_zero, inner),
              "files": {"prediction": str(prediction), "labels": str(labels), "mask": str(mask),
                        "control": None if control is None else str(control)},
              "level": level, "crop": crop}
    if control is not None:
        ctrl = np.squeeze(_load(control))
        if ctrl.shape != pred.shape:
            raise VerifyError(f"control shape {ctrl.shape} differs from the map's {pred.shape}")
        result["control"] = score_array(ctrl, ink, supervised, keep_zero, inner)
    if bootstrap or compare is not None:
        other = None
        if compare is not None:
            other = np.squeeze(_load(compare))
            result["files"]["compare"] = str(compare)
        result["bootstrap"] = block_bootstrap(pred, ink, supervised, bootstrap or 300, block_px, seed, other,
                                              keep_zero, inner)
    return result


def format_result(result):
    def line(label, r):
        if r["auc"] is None:
            return f"{label}: no AUC (ink {r['ink_px']} px, background {r['background_px']} px in the mask)"
        zeros = ""
        if r["zero_px_in_mask"]:
            zeros = (f" ({r['zero_px_in_mask']} zero px in the mask counted)" if r["zero_px_counted"]
                     else f" ({r['zero_px_in_mask']} unpredicted px in the mask left out)")
        edge = f", {r['inner']} px edge left out" if r.get("inner") else ""
        return (f"{label}: AUC {r['auc']:.4f} on {r['ink_px']} ink and {r['background_px']} background px"
                + edge + zeros)

    rows = [line("map    ", result["forward"])]
    if "control" in result:
        rows.append(line("control", result["control"]))
        f, c = result["forward"]["auc"], result["control"]["auc"]
        if f is not None and c is not None:
            rows.append(f"map minus control: {f - c:+.4f} (near 0 means the model is not reading ink in this direction)")
    b = result.get("bootstrap")
    if b:
        rows.append(f"map AUC 95 % interval {b['ci95'][0]:.4f} to {b['ci95'][1]:.4f} ({b['draws']} draws of "
                    f"{b['blocks']} blocks of {b['block_px']} px)")
        c = b.get("compare")
        if c:
            verdict = ("ahead beyond sampling noise" if c["ci95"][0] > 0 else
                       "behind beyond sampling noise" if c["ci95"][1] < 0 else "not distinguishable from noise")
            rows.append(f"map minus compared map: {c['difference']:+.4f}, 95 % interval {c['ci95'][0]:+.4f} to "
                        f"{c['ci95'][1]:+.4f} on {c['pixels']} shared px: {verdict}")
    return "\n".join(rows)
