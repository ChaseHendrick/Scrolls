"""The flat ink inference contract in numpy: the steps villa's flat ink inference applies around the model.

Four small functions, numpy only, shared by the ink preview server (inkpreview.py) and anything else that has to tile
a surface volume the way a whole-segment ink map is tiled:

  normalize_robust(patch)                    per-patch robust normalization
  slice_order(window, depth, variant)        the layers the model reads, in order
  hann2d(n)                                  the floored Hann blend window
  sliding_positions(length, patch, stride)   patch positions along one axis, the last one flush to the edge

They follow villa's `vesuvius.ink_detection.inference.infer` (https://github.com/ScrollPrize/villa) for a model
trained with robust normalization, such as ink_9um: clip each patch to its 1st and 99th percentiles, subtract the
median, divide by 1.4826 times the median absolute deviation; center crop the layer window to the model depth and
reverse it for the control view; weight each patch by a Hann window floored at 0.001; place patches at 0, stride,
2 stride and so on, with one more patch flush to the far edge when the regular positions do not end there.

The arithmetic here is numpy float32. villa's own normalization runs in compiled code, so a value can differ from
villa's in the last float32 digit; the rule is the same.
"""
from __future__ import annotations

import numpy as np

PATCH = 128


def normalize_robust(patch: np.ndarray) -> np.ndarray:
    """Robust normalization of one patch as a whole (zero fill included): float32, same shape.

    Non-negative integer patches up to 16 bits take the histogram route, which gives the same float32 result as the
    direct route to the bit and is faster; anything else takes the direct route."""
    p = np.asarray(patch)
    if p.size and p.dtype.kind in "ui" and int(p.min()) >= 0 and int(p.max()) <= 65535:
        return _normalize_robust_hist(p)
    return _normalize_robust_direct(p)


def _normalize_robust_hist(p: np.ndarray) -> np.ndarray:
    """normalize_robust from the value histogram. np.percentile and np.median depend only on the multiset of values,
    so each runs on a sorted array with the same multiset, and the float32 steps run once per distinct value, then
    map back through a lookup table."""
    cnt = np.bincount(p.ravel())
    present = np.flatnonzero(cnt)
    k = cnt[present]
    vals = present.astype(np.float32)
    lo, hi = np.percentile(np.repeat(vals, k), [1.0, 99.0], overwrite_input=True)
    c = vals.copy()
    np.clip(c, lo, hi, out=c)                       # monotone, so c stays sorted
    med = float(np.median(np.repeat(c, k), overwrite_input=True))
    dev = np.abs(c - med)
    o = np.argsort(dev, kind="stable")
    smad = 1.4826 * float(np.median(np.repeat(dev[o], k[o]), overwrite_input=True))
    if not np.isfinite(smad) or smad < 1e-6:
        std_pre = float(np.asarray(p, dtype=np.float32).std())
        cands = [x for x in (abs(std_pre), abs(hi - lo) / 2.0) if np.isfinite(x) and x >= 1e-6]
        smad = cands[0] if cands else 1.0
    c -= med
    c /= smad
    np.nan_to_num(c, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    lut = np.zeros(cnt.size, np.float32)
    lut[present] = c
    return lut[p]


def _normalize_robust_direct(patch: np.ndarray) -> np.ndarray:
    arr = np.asarray(patch, dtype=np.float32).copy()
    if arr.size == 0:
        return arr
    std_pre = float(arr.std())
    lo, hi = np.percentile(arr, [1.0, 99.0])
    np.clip(arr, lo, hi, out=arr)
    med = float(np.median(arr))
    smad = 1.4826 * float(np.median(np.abs(arr - med)))
    if not np.isfinite(smad) or smad < 1e-6:        # a flat patch: fall back to the spread before clipping
        cands = [c for c in (abs(std_pre), abs(hi - lo) / 2.0) if np.isfinite(c) and c >= 1e-6]
        smad = cands[0] if cands else 1.0
    arr -= med
    arr /= smad
    np.nan_to_num(arr, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    return arr


def slice_order(window: tuple[int, int], depth: int, variant: str, seed: int = 20261007) -> np.ndarray:
    """Indices of the layers fed to the model, in order, out of the layers window[0] to window[1] - 1.

    More layers than the model depth are center cropped (start = n // 2 - depth // 2). Variant f keeps the order,
    r reverses it (the control view), s shuffles the window with numpy default_rng(seed) before the crop."""
    idx = np.arange(window[0], window[1])
    if variant == "s":
        idx = idx[np.random.default_rng(seed).permutation(idx.size)]
    if idx.size > depth:
        start = idx.size // 2 - depth // 2
        idx = idx[start:start + depth]
    elif idx.size < depth:
        raise ValueError(f"window has {idx.size} slices, model needs {depth}")
    if variant == "r":
        idx = idx[::-1]
    elif variant not in ("f", "s"):
        raise ValueError(f"variant must be f, r or s, got {variant!r}")
    return idx


def hann2d(n: int = PATCH) -> np.ndarray:
    """The n by n blend window: outer product of two symmetric Hann windows, scaled to a maximum of 1, floored at
    0.001 so a pixel that only one patch covers at its rim still has a weight."""
    w = np.hanning(n).astype(np.float32)  # symmetric, same as torch.hann_window(periodic=False)
    m = np.outer(w, w)
    m /= max(float(m.max()), 1e-12)
    return np.maximum(m, 0.001).astype(np.float32)


def sliding_positions(length: int, patch: int = PATCH, stride: int = PATCH // 2) -> list[int]:
    """Top-left patch positions along an axis of the given length: 0, stride, 2 stride and so on, plus a last
    position flush to the edge (length - patch) when the regular ones do not end there. An axis no longer than the
    patch has the one position 0; the patch is then zero filled past the edge."""
    length, patch, stride = int(length), int(patch), max(1, int(stride))
    if length <= patch:
        return [0]
    out = list(range(0, length - patch + 1, stride))
    last = length - patch
    if out[-1] != last:
        out.append(last)
    return out
