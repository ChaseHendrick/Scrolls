"""Whole-segment crop scan: pixel AUC of one map on every window of a grid, in one pass.

Instead of cropping and re-scoring each window (``kit.auc.score_array`` per crop), the map is
quantized once, ink and background histograms are built per ``tile`` x ``tile`` cell, and
summed with a 2D cumulative sum, so every window costs O(bins). Window, stride and inner
margin must be multiples of ``tile``. With ``bins=65536`` the result equals score_array on
the same pixels; fewer bins trade a small, measured error for memory.

Use it to see how much a single crop's AUC (and a ranking between maps) depends on where the
crop was put. It reads no labels itself; pass boolean ink and supervision arrays on the map's grid.
"""

from .auc import _quantize, _auc_hist
from .verify import VerifyError, _numpy


def scan(prediction, ink, mask, window=640, stride=320, inner=64, tile=64, bins=4096,
         min_supervised=0.2, min_class=0.02, keep_zero=False):
    np = _numpy()
    if not (prediction.shape == ink.shape == mask.shape):
        raise VerifyError("prediction, ink and mask must share one grid")
    for name, v in (("window", window), ("stride", stride), ("inner", inner)):
        if v % tile:
            raise VerifyError(f"{name} {v} is not a multiple of tile {tile}")
    if 2 * inner >= window:
        raise VerifyError("inner margin leaves nothing")
    q, n = _quantize(np, prediction)
    qb = (q * bins // n).astype(np.int64)
    use = mask & (np.ones_like(mask) if keep_zero else prediction != 0)
    H, W = prediction.shape
    ty, tx = H // tile, W // tile
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
