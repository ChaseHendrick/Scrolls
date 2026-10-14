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


def _ranks(np, v, valid):
    out = np.zeros_like(v)
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
    if len(weights) != len(arrays) or any(w < 0 for w in weights) or sum(weights) <= 0:
        raise VerifyError("give one non-negative weight per map, not all zero")
    valid = np.ones(arrays[0].shape, bool)
    for a in arrays:
        valid &= a != 0
    total = np.zeros(arrays[0].shape, np.float64)
    for a, w in zip(arrays, weights):
        v = _unit(np, a)
        total += w * (_ranks(np, v, valid) if method == "rank" else v)
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

    arrays = [_load(p) for p in inputs]
    combined, valid = combine(arrays, method, weights)
    write(out, combined, valid)
    return {"out": str(out), "inputs": [str(p) for p in inputs], "method": method,
            "weights": list(weights) if weights else [1.0] * len(inputs),
            "shape": list(combined.shape), "valid_px": int(valid.sum())}
