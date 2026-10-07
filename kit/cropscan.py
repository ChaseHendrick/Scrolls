"""Whole-segment crop scan: pixel AUC of one map on every window of a grid, in one pass.

Instead of cropping and re-scoring each window (``kit.auc.score_array`` per crop), the map is
quantized once, ink and background histograms are built per ``tile`` x ``tile`` cell, and
summed with a 2D cumulative sum, so every window costs O(bins). Window, stride and inner
margin must be multiples of ``tile``. With ``bins=65536`` the result equals score_array on
the same pixels for uint8, uint16 or normalized [0, 1] float predictions. Other float
scales are refused because score_array chooses its quantization scale per crop. Fewer bins
introduce data-dependent ties; approximation error must be checked for each use.

Use it to see how much a single crop's AUC (and a ranking between maps) depends on where the
crop was put. It reads no labels itself; pass boolean ink and supervision arrays on the map's grid.
"""

import math
from numbers import Integral, Real

from .auc import _quantize, _auc_hist
from .verify import VerifyError, _numpy


def scan(prediction, ink, mask, window=640, stride=320, inner=64, tile=64, bins=4096,
         min_supervised=0.2, min_class=0.02, keep_zero=False, max_work_bytes=2 * 1024 ** 3):
    """Scan full windows; refuse invalid inputs and an excessive histogram working set.

    max_work_bytes bounds a conservative estimate of internal NumPy array payloads, excluding
    caller-owned inputs and allocator overhead. It is not a process-RSS guarantee.
    """
    np = _numpy()
    prediction, ink, mask = map(np.asarray, (prediction, ink, mask))
    if prediction.ndim != 2 or ink.ndim != 2 or mask.ndim != 2:
        raise VerifyError("prediction, ink and mask must be 2D arrays")
    if not (prediction.shape == ink.shape == mask.shape):
        raise VerifyError("prediction, ink and mask must share one grid")
    if ink.dtype != np.bool_ or mask.dtype != np.bool_:
        raise VerifyError("ink and mask must be boolean arrays")
    for name, value in (("window", window), ("stride", stride), ("tile", tile),
                        ("bins", bins), ("max_work_bytes", max_work_bytes)):
        if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
            raise VerifyError(f"{name} must be a positive integer")
    if isinstance(inner, bool) or not isinstance(inner, Integral) or inner < 0:
        raise VerifyError("inner must be a nonnegative integer")
    if not 2 <= bins <= 65536:
        raise VerifyError("bins must be between 2 and 65536")
    for name, value, upper in (("min_supervised", min_supervised, 1), ("min_class", min_class, .5)):
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or not 0 <= value <= upper:
            raise VerifyError(f"{name} must be finite and between 0 and {upper}")
    if not isinstance(keep_zero, (bool, np.bool_)):
        raise VerifyError("keep_zero must be boolean")
    for name, v in (("window", window), ("stride", stride), ("inner", inner)):
        if v % tile:
            raise VerifyError(f"{name} {v} is not a multiple of tile {tile}")
    if 2 * inner >= window:
        raise VerifyError("inner margin leaves nothing")
    if prediction.dtype not in (np.uint8, np.uint16) and not np.issubdtype(prediction.dtype, np.floating):
        raise VerifyError("prediction must be uint8, uint16 or normalized float")
    if not np.isfinite(prediction).all():
        raise VerifyError("prediction must contain only finite values")
    if np.issubdtype(prediction.dtype, np.floating) and prediction.size and not (prediction.min() >= 0 and prediction.max() <= 1):
        raise VerifyError("float prediction must be normalized to [0, 1] for crop-stable quantization")
    H, W = prediction.shape
    if H < window or W < window:
        return []
    ty, tx = H // tile, W // tile
    levels = 256 if prediction.dtype == np.uint8 else 65536
    bins = min(bins, levels)
    # Histogram, padded cumulative sums, cumulative temporaries, bincount output,
    # quantized maps, cell IDs and selection arrays may coexist. Refuse before allocation.
    estimate = 40 * ty * tx * bins + 16 * (ty + 1) * (tx + 1) * bins + 40 * H * W
    if estimate > max_work_bytes:
        raise VerifyError(f"crop scan estimated work {estimate} bytes exceeds max_work_bytes {max_work_bytes}; use fewer bins or larger tiles")
    q, _ = _quantize(np, prediction)
    qb = (q * bins // levels).astype(np.int64)
    use = mask & (np.ones_like(mask) if keep_zero else prediction != 0)
    cell = (np.arange(ty * tile)[:, None] // tile) * tx + np.arange(tx * tile)[None, :] // tile
    u = use[:ty * tile, :tx * tile]; k = ink[:ty * tile, :tx * tile]; b = qb[:ty * tile, :tx * tile]
    hist = np.zeros((2, ty * tx * bins), np.int32)
    for c, sel in ((0, u & k), (1, u & ~k)):
        hist[c] = np.bincount(cell[sel] * bins + b[sel], minlength=ty * tx * bins)
    hist = hist.reshape(2, ty, tx, bins)
    cum = np.zeros((2, ty + 1, tx + 1, bins), np.int64)
    cum[:, 1:, 1:] = hist.cumsum(1).cumsum(2)
    del hist
    out = []
    wt, it_, st = window // tile, inner // tile, stride // tile
    area = (window - 2 * inner) ** 2
    for y in range(0, ty - wt + 1, st):
        for x in range(0, tx - wt + 1, st):
            y0, y1, x0, x1 = y + it_, y + wt - it_, x + it_, x + wt - it_
            h = cum[:, y1, x1] - cum[:, y0, x1] - cum[:, y1, x0] + cum[:, y0, x0]
            ni, nb = int(h[0].sum()), int(h[1].sum())
            rec = {"crop": [y * tile, y * tile + window, x * tile, x * tile + window],
                   "ink_px": ni, "background_px": nb, "auc": None}
            sup = (ni + nb) / area
            if sup >= min_supervised and min(ni, nb) >= min_class * (ni + nb) and ni and nb:
                rec["auc"] = round(float(_auc_hist(np, h[0].astype(np.float64), h[1].astype(np.float64))), 4)
            out.append(rec)
    return out
