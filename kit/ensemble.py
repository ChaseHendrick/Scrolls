"""Average several ink maps of the same surface into one (a prediction-level ensemble).

The cheapest gain the community reports: Hecate and Reader v2 averaged reach 0.866 AUC on
PHerc0841 against 0.855 and 0.824 alone (Reader v2 model card; PHerc0841 may not be held out
from Hecate, whose base model's committed trainer lists its three labelled segments:
docs/logs/2026-10-09-pherc0841-hecate.md); d9v2 and Reader v2 averaged, 0.840 against 0.828
and 0.826 (TAUIL's benchmark); two seeds' maps averaged,
0.866 against 0.840 on the PHerc0139 title (Nieuwlaar), where averaging the two seeds'
weights instead gave 0.49. Maps of different models or seeds are combined here; weights
only within one training run (`scripts/soup.py`).

Two ways to combine:

- `mean`: each map scaled to 0..1 (uint8 by 255, uint16 by 65535, floats as they are),
  then a weighted mean. Right for maps of one model (seeds, checkpoints, z windows).
- `rank`: each map replaced by its pixel ranks (0..1 over the valid pixels) before the
  mean, so a model whose scores sit in a narrow band counts as much as one that uses the
  full range. Right for maps of different models.

A pixel counts as valid only where every input is non-zero (villa and v8in write 0 where
they made no prediction); elsewhere the output is 0, and valid pixels are kept above 0, so
`kit auc` leaves out the same pixels it would for each input. A `.tif` output is uint16
(1..65535 on valid pixels); `.npy` is float32, the same scale divided by 65535.
"""

import math

from .verify import VerifyError, _numpy

METHODS = ("mean", "rank")


def _unit(np, a):
    if a.dtype == np.uint8:
        return a.astype(np.float64) / 255.0
    if a.dtype == np.uint16:
        return a.astype(np.float64) / 65535.0
    v = a.astype(np.float64)
    top = float(v.max()) if v.size else 1.0
    return v / (255.0 if 1.0 < top <= 255 else 65535.0) if top > 1.0 else v


# The histogram path below gives the sort's bits only while every rank sum the sort path adds up stays an
# exact float64 integer; a map whose sums could pass this takes the sort path.
_EXACT_SUM = 2 ** 53


def _ranks(np, v, valid, a=None):
    """v's ranks among the valid pixels, ties sharing their mean rank, scaled to 0..1; 0 elsewhere.

    a is the map v was scaled from, when the caller has it. For a uint8 or uint16 map, whose scaled
    values keep its order and its ties, a value's mean rank is the count of valid pixels below it plus
    (its count - 1) / 2, read from a histogram instead of two full sorts: the same bits as the sort
    path, whose rank sums are exact integers, as long as every group's sum stays below _EXACT_SUM."""
    out = np.zeros_like(v)
    x = a[valid] if a is not None and a.dtype in (np.uint8, np.uint16) else None
    if x is not None and 0 < x.size < 2 ** 31:          # below 2 ** 31 the int64 group sums cannot overflow
        counts = np.bincount(x, minlength=256 if a.dtype == np.uint8 else 65536)
        below = np.cumsum(counts) - counts
        if int((counts * (2 * below + counts - 1) // 2).max()) < _EXACT_SUM:
            out[valid] = (below + (counts - 1) / 2.0)[x] / max(x.size - 1, 1)
            return out
    x = v[valid]
    if x.size:
        order = np.argsort(x, kind="stable")
        r = np.empty(x.size, np.float64)
        r[order] = np.arange(x.size, dtype=np.float64)
        # ties share their mean rank, so equal scores stay equal
        uniq, inv = np.unique(x, return_inverse=True)
        sums = np.bincount(inv, weights=r, minlength=uniq.size)
        counts = np.bincount(inv, minlength=uniq.size)
        r = (sums / counts)[inv]
        out[valid] = r / max(x.size - 1, 1)
    return out


def combine(arrays, method="mean", weights=None):
    """(combined float map in 0..1, valid mask)."""
    np = _numpy()
    if method not in METHODS:
        raise VerifyError(f"method must be one of {METHODS}, got {method!r}")
    if len(arrays) < 2:
        raise VerifyError("an ensemble needs at least two maps")
    shapes = {tuple(a.shape) for a in arrays}
    if len(shapes) != 1:
        raise VerifyError(f"maps differ in shape: {sorted(shapes)}")
    if weights is None:
        weights = [1.0] * len(arrays)
    if len(weights) != len(arrays) or any(not math.isfinite(w) or w < 0 for w in weights) \
            or sum(weights) <= 0:
        raise VerifyError("give one finite, non-negative weight per map, not all zero")
    valid = np.ones(arrays[0].shape, bool)
    for a in arrays:
        valid &= a != 0
    total = np.zeros(arrays[0].shape, np.float64)
    for a, w in zip(arrays, weights):
        v = _unit(np, a)
        total += w * (_ranks(np, v, valid, a) if method == "rank" else v)
    total /= float(sum(weights))
    total[~valid] = 0.0
    return total, valid


def write(path, combined, valid):
    np = _numpy()
    path = str(path)
    if path.endswith(".npy"):
        out = np.zeros(combined.shape, np.float32)
        out[valid] = (1.0 + np.clip(combined[valid], 0.0, 1.0) * 65534.0) / 65535.0
        np.save(path, out)
        return path
    try:
        import tifffile
    except ImportError as exc:
        raise VerifyError("tifffile is required to write a .tif ensemble") from exc
    out = np.zeros(combined.shape, np.uint16)
    out[valid] = 1 + np.round(np.clip(combined[valid], 0.0, 1.0) * 65534).astype(np.uint16)
    tifffile.imwrite(path, out)
    return path


def ensemble_files(out, inputs, method="mean", weights=None):
    from .auc import _load

    np = _numpy()
    arrays = []
    for p in inputs:
        try:
            a = np.squeeze(_load(p))
        except (OSError, ValueError) as exc:  # np.load: a missing or non-array .npy
            raise VerifyError(f"cannot read {p}: {exc}") from exc
        if a.ndim != 2:
            raise VerifyError(f"{p}: expected a 2D map, got shape {a.shape}")
        arrays.append(a)
    combined, valid = combine(arrays, method, weights)
    write(out, combined, valid)
    return {"out": str(out), "inputs": [str(p) for p in inputs], "method": method,
            "weights": list(weights) if weights else [1.0] * len(inputs),
            "shape": list(combined.shape), "valid_px": int(valid.sum())}
