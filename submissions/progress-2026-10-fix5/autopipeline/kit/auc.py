"""Pixel AUC of an ink map against a segment's published ink labels.

On a labelled segment no model was trained on (PHerc0841 for the released readers; PHerc0139
w045 for v8in only, since ink_9um trained on its 2.4 um render), this is the generalization
number: the chance that a labelled ink pixel scores above a
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
`compare` also gives the exact difference on the shared pixels; the interval comes from the binned draws.

Two options change which labels count, the same way for the map, its control and a compared map:

  exclude   boxes (y0 y1 x0 x1 on the surface grid, the same frame as `crop`), each grown by `exclude_margin`
            pixels on every side and clipped to the surface, are removed from the supervision mask: a region
            that was looked at before (a window chosen with labels) is left out of a later score. The pixels and
            the labelled ink removed are reported.
  offset    the labels are moved by (dy, dx) surface pixels after they are mapped onto the map's grid:
            label[y, x] = stretched[y - dy, x - dx] (TAUIL-Abd-Elilah's label-equivalent convention, as
            kit.transplant.shift2d), so (-6, -7) takes each pixel's label from 6 rows down and 7 columns right.
            Pixels whose source falls outside the surface (the vacated edge) leave the mask. The offset is applied
            on the whole surface, so a cropped map and the same window cut from a whole map get the same labels.
"""

from . import s3retry
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
    try:
        s3retry.refuse_remote(path, "kit auc")
    except ValueError as exc:
        raise VerifyError(str(exc)) from None
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


def _axis_index(start, stop, n_surface, n_labels, scale, shift=0):
    """Label indices along one axis for map pixels start..stop-1 of the surface, taking each pixel's label from
    surface pixel p - shift; and where that source lies on the surface."""
    np = _numpy()
    src = np.arange(start, stop) - int(shift)
    ok = (src >= 0) & (src < n_surface)
    idx = np.minimum(((np.clip(src, 0, n_surface - 1) + 0.5) * scale).astype(np.int64), n_labels - 1)
    return idx, ok


def label_index(labels_shape, surface_shape, crop, map_shape, offset=(0, 0)):
    """Row and column indices into the labels for every map pixel (nearest neighbour), the labels moved by
    offset (dy, dx) surface pixels, and per row and column whether the label's source is on the surface."""
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
    dy, dx = (int(v) for v in (offset or (0, 0)))
    if abs(dy) >= surface_shape[0] or abs(dx) >= surface_shape[1]:
        raise VerifyError(f"label offset {[dy, dx]} moves the labels off the {surface_shape[0]} x "
                          f"{surface_shape[1]} surface")
    rows, row_ok = _axis_index(y0, y1, surface_shape[0], labels_shape[0], sy, dy)
    cols, col_ok = _axis_index(x0, x1, surface_shape[1], labels_shape[1], sx, dx)
    return rows, cols, row_ok, col_ok


def label_grid(labels_shape, surface_shape, crop, map_shape):
    """Row and column indices into the labels for every map pixel (nearest neighbour)."""
    rows, cols, _, _ = label_index(labels_shape, surface_shape, crop, map_shape)
    return rows, cols


def labels_on_map(labels, mask, level, surface_shape, crop, map_shape, offset=(0, 0)):
    """Boolean ink and supervision arrays on the map's own grid. With an offset, the labels are moved by (dy, dx)
    surface pixels and the vacated edge is left out of the supervision."""
    np = _numpy()
    lab = _levels(labels, level)
    msk = _levels(mask, level)
    if lab.shape != msk.shape:
        raise VerifyError(f"labels {lab.shape} and mask {msk.shape} differ in shape at level {level}")
    rows, cols, row_ok, col_ok = label_index(lab.shape, surface_shape, crop, map_shape, offset)
    r0, r1, c0, c1 = int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1
    ink = np.asarray(lab[r0:r1, c0:c1])[np.ix_(rows - r0, cols - c0)] > 0
    supervised = np.asarray(msk[r0:r1, c0:c1])[np.ix_(rows - r0, cols - c0)] > 0
    if not (row_ok.all() and col_ok.all()):
        supervised &= row_ok[:, None] & col_ok[None, :]
    return ink, supervised


def exclude_boxes(ink, supervised, boxes, surface_shape, crop=None, margin=0):
    """Remove boxes (y0 y1 x0 x1 on the surface grid), each grown by `margin` px and clipped to the surface, from
    the supervision mask of a map that covers `crop` of the surface (default all of it). Returns the new mask and
    a record of what was removed."""
    np = _numpy()
    if margin < 0:
        raise VerifyError("the exclusion margin cannot be negative")
    H, W = (int(v) for v in surface_shape)
    cy0, cy1, cx0, cx1 = crop if crop is not None else (0, H, 0, W)
    out = supervised.copy()
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
    removed = supervised & ~out
    sup_ink = int((supervised & ink).sum())
    rec = {"boxes": [[int(v) for v in b] for b in boxes], "margin": int(margin), "grown": grown,
           "supervised_px_removed": int(removed.sum()), "ink_px_removed": int((removed & ink).sum()),
           "ink_px_kept": int((out & ink).sum()),
           "ink_share_kept": round(float((out & ink).sum()) / sup_ink, 4) if sup_ink else None}
    return out, rec


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
    blocks, inv = np.unique(keys, return_inverse=True)
    lab = ink[ys, xs]
    if lab.all() or not lab.any():
        raise VerifyError("the mask holds only one class; no AUC to resample")
    hists = []
    for m in maps:
        q, _ = _quantize(np, m)
        top = 255 if m.dtype == np.uint8 else 65535   # _quantize keeps uint8 as 0..255
        qb = q[ys, xs] * (BOOT_BINS - 1) // top
        hi = np.zeros((len(blocks), BOOT_BINS)); hb = np.zeros((len(blocks), BOOT_BINS))
        np.add.at(hi, (inv[lab], qb[lab]), 1)
        np.add.at(hb, (inv[~lab], qb[~lab]), 1)
        hists.append((hi, hb))
    rng = np.random.default_rng(seed)
    w = np.stack([np.bincount(rng.integers(0, len(blocks), len(blocks)), minlength=len(blocks))
                  for _ in range(draws)]).astype(np.float64)
    stats = [_auc_hist(np, w @ hi, w @ hb) for hi, hb in hists]
    lo, hi_ = np.percentile(stats[0], [2.5, 97.5])
    result = {"draws": draws, "block_px": block_px, "blocks": int(len(blocks)), "seed": seed,
              "ci95": [round(float(lo), 4), round(float(hi_), 4)], "half_width": round(float(hi_ - lo) / 2, 4)}
    if other is not None:
        full = [float(_auc_hist(np, hi.sum(0), hb.sum(0))) for hi, hb in hists]
        exact = []
        for m in maps:        # every grey level, as score_array counts them, on the shared pixels
            q, _ = _quantize(np, m)
            v = q[ys, xs]
            exact.append(auc_scores(v[lab], v[~lab]))
        diff = stats[0] - stats[1]
        dlo, dhi = np.percentile(diff, [2.5, 97.5])
        result["compare"] = {
            "auc_map": round(full[0], 4), "auc_other": round(full[1], 4), "difference": round(full[0] - full[1], 4),
            "auc_map_exact": round(exact[0], 4), "auc_other_exact": round(exact[1], 4),
            "difference_exact": round(exact[0] - exact[1], 4),
            "ci95": [round(float(dlo), 4), round(float(dhi), 4)],
            "share_draws_map_not_ahead": round(float((diff <= 0).mean()), 4),
            "pixels": int(len(ys)),
        }
    return result


def score_files(prediction, labels, mask, control=None, level=DEFAULT_LEVEL, crop=None,
                surface_shape=None, keep_zero=False, inner=0, bootstrap=0, block_px=BLOCK_PX,
                compare=None, seed=0, exclude=None, exclude_margin=0, offset=None):
    """Score a map file. exclude: boxes (y0 y1 x0 x1, surface grid) grown by exclude_margin and removed from the
    mask; offset: (dy, dx) by which the labels are moved (module docstring). Both apply to every map scored."""
    np = _numpy()
    pred = np.squeeze(_load(prediction))
    if pred.ndim != 2:
        raise VerifyError(f"{prediction}: expected a 2D map, got shape {pred.shape}")
    if surface_shape is None:
        if crop is not None:
            raise VerifyError("a cropped map needs the full surface shape (surface_shape)")
        surface_shape = pred.shape
    if exclude_margin and not exclude:
        raise VerifyError("an exclusion margin needs at least one exclusion box")
    offset = tuple(int(v) for v in offset) if offset is not None else None
    ink, supervised = labels_on_map(labels, mask, level, surface_shape, crop, pred.shape, offset or (0, 0))
    excluded = None
    if exclude:
        supervised, excluded = exclude_boxes(ink, supervised, exclude, surface_shape, crop, exclude_margin)
    result = {"forward": score_array(pred, ink, supervised, keep_zero, inner),
              "files": {"prediction": str(prediction), "labels": str(labels), "mask": str(mask),
                        "control": None if control is None else str(control)},
              "level": level, "crop": crop}
    if offset is not None:
        result["label_offset"] = list(offset)
    if excluded is not None:
        result["excluded"] = excluded
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

    rows = []
    if result.get("label_offset") is not None:
        dy, dx = result["label_offset"]
        rows.append(f"labels moved by ({dy:+d}, {dx:+d}) px: label[y, x] = stretched[y - dy, x - dx], vacated edge "
                    "left out of the mask")
    ex = result.get("excluded")
    if ex:
        kept = "" if ex["ink_share_kept"] is None else f", {ex['ink_share_kept']:.1%} of the labelled ink kept"
        rows.append(f"excluded {len(ex['grown'])} box(es) grown by {ex['margin']} px: {ex['grown']}; "
                    f"{ex['supervised_px_removed']} supervised px removed ({ex['ink_px_removed']} ink){kept}")
    rows.append(line("map    ", result["forward"]))
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
            rows.append(f"map minus compared map: {c['difference']:+.4f} ({c['difference_exact']:+.4f} at every "
                        f"grey level), 95 % interval {c['ci95'][0]:+.4f} to {c['ci95'][1]:+.4f} on {c['pixels']} "
                        f"shared px: {verdict}")
    return "\n".join(rows)
