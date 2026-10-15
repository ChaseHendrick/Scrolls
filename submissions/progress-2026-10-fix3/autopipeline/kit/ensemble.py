"""Combine several ink maps of the same surface into one (a prediction-level ensemble).

The cheapest gain the community reports: Reader v2 and Hecate averaged reach 0.866 AUC on
PHerc0841 against 0.855 and 0.824 alone (Reader v2 model card); d9v2 and Reader v2
averaged, 0.840 against 0.828 and 0.826 (TAUIL's benchmark); two seeds' maps averaged,
0.866 against 0.840 on the PHerc0139 title (Nieuwlaar), where averaging the two seeds'
weights instead gave 0.49. Maps of different models or seeds are combined here; weights
only within one training run (`scripts/soup.py`).

Three ways to combine:

- `mean`: each map scaled to 0..1 (uint8 by 255, uint16 by 65535, floats as they are),
  then a weighted mean. Right for maps of one model (seeds, checkpoints, z windows).
- `rank`: each map replaced by its pixel ranks (0..1 over the valid pixels) before the
  mean, so a model whose scores sit in a narrow band counts as much as one that uses the
  full range. Right for maps of different models.
- `zscore`: Nieuwlaar's rule for his PHerc. 343 First Letters image (below). Each model's
  map is turned into z-scores with that model's pooled mean and population SD, taken over
  a declared set of maps (his: the reading-side maps of that model at all 31 depths,
  -15..15, in his `reproduce.sh`), and the z-scores of the models are averaged. The
  statistics can be saved and applied to other maps of the same models: his blind side
  (the forward maps, the control) is shown with the reading side's statistics and stretch,
  never its own.

A pixel counts as valid only where every input is non-zero (villa and v8in write 0 where
they made no prediction), and, with `valid_from`, where a surface volume is above 0 in
every layer (his rule; a mask image, valid where > 0, also works). `keep_zero` drops the
first condition, so `valid_from` with `keep_zero` is exactly his rule. A NaN or infinite
value of a float map is never valid, with or without `keep_zero` (kit writes NaN where a
map has no value; one NaN would otherwise make a model's mean and SD NaN). Validity is
decided on the raw values before any decoding, so decoding never invalidates a pixel.
Elsewhere the output is 0, and valid pixels are kept above 0, so `kit auc` leaves out
exactly the invalid pixels. A `.tif` output is uint16 (1..65535 on valid pixels); `.npy` is
float32, the same scale divided by 65535. For `zscore` the mean z is mapped onto that scale
by one increasing affine map, its minimum to 1 and its maximum to 65535, with no clipping,
so pixel ranks and `kit auc` are unchanged up to the rounding to 65,535 levels; the
minimum and maximum are in the result, and `raw_out` saves the unscaled values (float32,
NaN where invalid; not an input for `kit auc`, which reads floats as 0..1).

Decoding (`decode`, per map, or per model for `zscore`):

- `none`: uint8 / 255, uint16 / 65535, other types as they are, except that `mean` and
  `rank` keep their earlier rule for other types: a map whose largest value is above 1 is
  divided by 255 (largest at most 255) or 65535.
- `ls`: label smoothing. uint8 v becomes clip((v - 64) / 128, 0, 1); uint16 and float maps
  become clip((p - 0.25) / 0.5, 0, 1) of the `none` value. Community report (his code and
  docstring, 2026-10-07): this is how he decodes the villa models (dense_native, ink_9um
  seeds 42 and 43), "(p - 0.25) / 0.5 for the label-smoothed models", while Hecate is read
  as v / 255. Interpretation: a model trained with BCE label smoothing 0.5 is pulled toward
  p = 0.25 on non-ink and 0.75 on ink, so the decode maps those targets to 0 and 1 and
  everything below the no-ink floor to 0. Maps of another family are not decoded this way.

The zscore rule, ported from Erwin Nieuwlaar's `ink/scripts/ensemble_maps.py` in
https://github.com/Nieuwlaar/pherc343-first-letters at commit
e8370f1f88a211166056df62ea6fcfffe4a1063e (2026-10-07), the code of the First Letters
prize for PHerc. 343 (awarded 2026-10-08, Sourced fact:
https://scrollprize.substack.com/p/50k-first-letters-prize-awarded-for), under the MIT
License reproduced below:

  map values  float32, decoded as above.
  statistics  per model: s1 = sum of v and s2 = sum of v * v over the valid pixels of all its
              pooled maps (float64), n their number; mean = s1 / n; sd = sqrt(max(s2 / n -
              mean * mean, 0)) + 1e-6. Display stretch per model: p1 and p99.5 of those values
              from a histogram, as he computes it: exact over 129 levels for uint8 maps decoded
              with `ls` (his villa branch), else over 65,536 bins on 0..1 (his Hecate branch).
  ensemble    z = (v - mean) / sd per model (float32), summed in the given model order, then
              divided by the number of models (float32).
  stretch     p1 and p99.5 (numpy's linear percentile) of the ensemble over a fixed grid
              of valid pixels, every 8th row and column starting at row and column 4, at every
              depth where all models have maps. It is for display only and is recorded, never
              applied to the scored output.

    MIT License

    Copyright (c) 2026 Erwin Nieuwlaar

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

Deliberate deviations from the original:

- Models, maps and depths are declared (NAME=PATH, pooled maps per model) instead of found
  by his file names; the k-th pooled map of each model is taken as one depth for the
  stretch, and the stretch is left out when the models have different numbers of pooled
  maps (his code takes the depths common to all models). The order of the maps given is the
  summation order (his: dnative, hecate, ink9-42, ink9-43).
- Validity also leaves out raw zeros (kit's "no prediction") unless `keep_zero`; his is the
  surface test alone. The surface may have any number of layers (his asserts 66).
- How each map is decoded is declared (`decode`), not inferred from TIFF or PNG; the PNG
  rule matches his for 8 and 16-bit grey. Maps must share one grid: his bilinear resize of
  Hecate's 9.6 um map onto the render grid belongs to `kit hecateprep`.
- His villa rule is for uint8 TIFF only: he reads a uint16 TIFF as v / 65535 and a float
  TIFF as it is, without the (p - 0.25) / 0.5 decode, and bins every villa map on the 129
  levels. Here `ls` decodes uint16 and float maps too, and their stretch uses the 65,536
  bins. His villa maps are uint8 (trunc(255 p), his `run_ink.sh`), so they never meet the
  difference.
- NaN and infinite values are invalid pixels; his maps have none.
- Values below 0 or above 1 (an undecoded float map) are clipped into the stretch histogram
  bins; his Hecate values are always in 0..1. The z-scores use the values unclipped.
- No images are written: the output is a scored map (no 0..255 stretch, no clipping, no
  180 degree reading orientation, no CT layer). The display stretches are recorded only.
"""

import glob
import json
import math
import re
from pathlib import Path

from .verify import VerifyError, _numpy

METHODS = ("mean", "rank", "zscore")
DECODES = ("none", "ls")
SD_EPS = 1e-6                 # added to every SD (his rule)
P_LO, P_HI = 1.0, 99.5        # display stretch percentiles
GRID_START, GRID_STEP = 4, 8  # fixed grid of the ensemble stretch
FINE = 65536                  # histogram bins on 0..1 for maps that are not 129-level
LS_LEVELS = 129               # uint8 decoded with ls: k / 128, k = 0..128
VALID_ROWS = 128              # rows per block when the surface volume is read
STATS_KIND = "kit-ensemble-zscore-statistics"
STATS_VERSION = 1
SOURCE = {"repository": "https://github.com/Nieuwlaar/pherc343-first-letters",
          "commit": "e8370f1f88a211166056df62ea6fcfffe4a1063e",
          "file": "ink/scripts/ensemble_maps.py", "licence": "MIT, Copyright (c) 2026 Erwin Nieuwlaar"}
NAME_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")


def _unit(np, a):
    if a.dtype == np.uint8:
        return a.astype(np.float64) / 255.0
    if a.dtype == np.uint16:
        return a.astype(np.float64) / 65535.0
    v = a.astype(np.float64)
    finite = v[np.isfinite(v)]   # a NaN (never valid) must not decide the scale
    top = float(finite.max()) if finite.size else 1.0
    return v / (255.0 if 1.0 < top <= 255 else 65535.0) if top > 1.0 else v


def _predicted(np, a, keep_zero):
    """Where a raw map holds a prediction: non-zero (unless keep_zero) and, for floats, finite."""
    ok = np.ones(a.shape, bool) if keep_zero else a != 0
    if a.dtype.kind in "fc":
        ok &= np.isfinite(a)
    return ok


def _read(path):
    """A map file as an array; a missing or unreadable file is a VerifyError, not a traceback."""
    from .auc import _load
    try:
        return _load(path)
    except (OSError, ValueError, EOFError) as exc:
        raise VerifyError(f"cannot read {path}: {exc}") from exc


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


def decode_values(a, how="none"):
    """Map values as float32: `none` uint8 / 255, uint16 / 65535, others as they are; `ls` as in the docstring."""
    np = _numpy()
    if how not in DECODES:
        raise VerifyError(f"decode must be one of {DECODES}, got {how!r}")
    a = np.asarray(a)
    if a.dtype == np.uint8:
        if how == "ls":
            return np.clip((a.astype(np.float32) - 64.0) / 128.0, 0, 1)
        return a.astype(np.float32) / 255.0
    p = a.astype(np.float32) / 65535.0 if a.dtype == np.uint16 else a.astype(np.float32)
    return np.clip((p - 0.25) / 0.5, 0, 1) if how == "ls" else p


def _base_valid(np, shape, valid):
    if valid is None:
        return np.ones(shape, bool)
    valid = np.asarray(valid, bool)
    if valid.shape != tuple(shape):
        raise VerifyError(f"validity mask {valid.shape} differs from the maps' {tuple(shape)}")
    return valid


def _decodes(decode, n):
    if isinstance(decode, str):
        return [decode] * n
    decode = list(decode)
    if len(decode) != n:
        raise VerifyError("give one decode per map, or one for all")
    return decode


def combine(arrays, method="mean", weights=None, decode="none", valid=None, keep_zero=False):
    """(combined float map in 0..1, valid mask). zscore here uses each map's own statistics."""
    np = _numpy()
    if method not in METHODS:
        raise VerifyError(f"method must be one of {METHODS}, got {method!r}")
    if len(arrays) < 2:
        raise VerifyError("an ensemble needs at least two maps")
    shapes = {tuple(a.shape) for a in arrays}
    if len(shapes) != 1:
        raise VerifyError(f"maps differ in shape: {sorted(shapes)}")
    decodes = _decodes(decode, len(arrays))
    if method == "zscore":
        if weights is not None:
            raise VerifyError("zscore is an unweighted mean (Nieuwlaar's rule); give no weights")
        maps = [(f"map{i + 1}", a) for i, a in enumerate(arrays)]
        stats = zscore_stats(maps, {n: d for (n, _), d in zip(maps, decodes)}, valid, keep_zero)
        z, ok = apply_zscore(maps, stats, valid, keep_zero)
        return affine01(z, ok)[0], ok
    if weights is None:
        weights = [1.0] * len(arrays)
    if len(weights) != len(arrays) or any(w < 0 for w in weights) or sum(weights) <= 0:
        raise VerifyError("give one non-negative weight per map, not all zero")
    valid = _base_valid(np, arrays[0].shape, valid).copy()
    for a in arrays:
        valid &= _predicted(np, a, keep_zero)
    total = np.zeros(arrays[0].shape, np.float64)
    for a, w, how in zip(arrays, weights, decodes):
        v = _unit(np, a) if how == "none" else decode_values(a, how).astype(np.float64)
        total += w * (_ranks(np, v, valid) if method == "rank" else v)
    total /= float(sum(weights))
    total[~valid] = 0.0
    return total, valid


# ---------------------------------------------------------------- zscore (Nieuwlaar)

def _as_map(np, src):
    if isinstance(src, (str, Path)):
        a = np.squeeze(_read(src))
    else:
        a = np.asarray(src)
    if a.ndim != 2:
        raise VerifyError(f"{src if isinstance(src, (str, Path)) else 'map'}: expected a 2D map, got shape {a.shape}")
    return a


def _label(src, i):
    return str(src) if isinstance(src, (str, Path)) else f"<array {i}>"


def pct_hist(hist, values, qs):
    """np.percentile (linear) computed exactly from a histogram over discrete values (his pct_hist)."""
    np = _numpy()
    c = np.cumsum(hist)
    n = int(c[-1])
    out = []
    for q in qs:
        pos = q / 100.0 * (n - 1)
        lo = int(math.floor(pos))
        fr = pos - lo
        i_lo = int(np.searchsorted(c, lo + 1))
        i_hi = int(np.searchsorted(c, min(lo + 2, n))) if fr > 0 else i_lo
        out.append(float(values[i_lo] + fr * (values[i_hi] - values[i_lo])))
    return out


def grid_mask(shape):
    """His fixed grid: every 8th row and column, starting at 4."""
    np = _numpy()
    g = np.zeros(shape, bool)
    g[GRID_START::GRID_STEP, GRID_START::GRID_STEP] = True
    return g


def zscore_stats(pool, decode="none", valid=None, keep_zero=False, order=None):
    """Pooled statistics per model. pool: (name, map or path) pairs, several per name; decode: one
    name for all or {name: decode}; order: the model order (default: first appearance)."""
    np = _numpy()
    pool = list(pool)
    if not pool:
        raise VerifyError("no maps to pool statistics from")
    groups = {}
    for name, src in pool:
        groups.setdefault(name, []).append(src)
    order = list(order) if order is not None else list(groups)
    if sorted(order) != sorted(groups) or len(set(order)) != len(order):
        raise VerifyError(f"models in the pool {sorted(groups)} differ from the models {order}")
    decodes = {n: (decode if isinstance(decode, str) else decode.get(n, "none")) for n in order}
    for how in decodes.values():
        if how not in DECODES:
            raise VerifyError(f"decode must be one of {DECODES}, got {how!r}")
    shape = base = grid = None
    models, samples, k = {}, {}, 0
    for name in order:
        how = decodes[name]
        s1 = s2 = 0.0
        n = 0
        levels = True
        hist_ls = np.zeros(LS_LEVELS, np.int64)
        hist_fine = None
        files, valid_px, samples[name] = [], [], []
        for src in groups[name]:
            raw = _as_map(np, src)
            if shape is None:
                shape = raw.shape
                base = _base_valid(np, shape, valid)
                grid = grid_mask(shape)
            elif raw.shape != shape:
                raise VerifyError(f"{_label(src, k)}: shape {raw.shape} differs from {shape}")
            ok = base & _predicted(np, raw, keep_zero)
            m = decode_values(raw, how)
            v = m[ok]
            if levels and not (how == "ls" and raw.dtype == np.uint8):
                levels = False   # a map off the 129 levels: move what was counted into the fine bins
                hist_fine = np.zeros(FINE, np.int64)
                np.add.at(hist_fine, np.minimum(np.arange(LS_LEVELS) * (FINE // 128), FINE - 1), hist_ls)
            if levels:
                hist_ls += np.bincount(np.rint(v * 128).astype(np.int64), minlength=LS_LEVELS)[:LS_LEVELS]
            else:
                hist_fine += np.bincount(np.clip((v * FINE).astype(np.int64), 0, FINE - 1), minlength=FINE)
            s1 += float(v.sum(dtype=np.float64))
            s2 += float(np.square(v, dtype=np.float64).sum())
            n += v.size
            samples[name].append((m[grid], ok[grid]))
            files.append(_label(src, k))
            valid_px.append(int(v.size))
            k += 1
        if n == 0:
            raise VerifyError(f"model {name}: no valid pixels in its pooled maps")
        hist, values = ((hist_ls, np.arange(LS_LEVELS) / 128.0) if levels
                        else (hist_fine, np.arange(FINE) / FINE))
        lo, hi = pct_hist(hist, values, [P_LO, P_HI])
        mu = s1 / n
        sd = math.sqrt(max(s2 / n - mu * mu, 0.0)) + SD_EPS
        models[name] = {"decode": how, "maps": files, "valid_px": valid_px, "n_px": n, "mean": mu, "sd": sd,
                        "p1": lo, "p99_5": hi, "stretch_bins": f"{LS_LEVELS} levels" if levels else f"{FINE} bins"}
    counts = {len(samples[n]) for n in order}
    ens = {"models": order, "grid": {"start": GRID_START, "step": GRID_STEP}, "percentiles": [P_LO, P_HI]}
    if len(order) < 2:
        ens["note"] = "one model: no ensemble stretch"
    elif len(counts) != 1:
        ens["note"] = "the models have different numbers of pooled maps, so depths cannot be paired: no stretch"
    else:
        parts = []
        for i in range(counts.pop()):
            common = np.ones(int(grid.sum()), bool)
            for name in order:
                common &= samples[name][i][1]
            acc = None
            for name in order:
                m = models[name]
                z = (samples[name][i][0][common] - m["mean"]) / m["sd"]
                acc = z if acc is None else acc + z
            parts.append(acc / len(order))
        e = np.concatenate(parts)
        ens["pairs"] = [[models[name]["maps"][i] for name in order] for i in range(len(parts))]
        ens["n_grid"] = int(e.size)
        if e.size:
            ens["p1"], ens["p99_5"] = (float(x) for x in np.percentile(e, [P_LO, P_HI]))
    return {"kind": STATS_KIND, "version": STATS_VERSION, "source": SOURCE, "shape": list(shape),
            "keep_zero": bool(keep_zero), "model_order": order, "models": models, "ensemble": ens}


def apply_zscore(maps, stats, valid=None, keep_zero=False):
    """(mean z-score float32, valid mask) of one map per model, with the models' saved statistics."""
    np = _numpy()
    maps = list(maps)
    names = [n for n, _ in maps]
    if len(maps) < 2:
        raise VerifyError("an ensemble needs at least two maps")
    if len(set(names)) != len(names):
        raise VerifyError(f"give one map per model; repeated: {sorted({n for n in names if names.count(n) > 1})}")
    missing = [n for n in names if n not in stats["models"]]
    if missing:
        raise VerifyError(f"no statistics for {missing}; the statistics hold {sorted(stats['models'])}")
    acc = ok = shape = None
    for i, (name, src) in enumerate(maps):
        raw = _as_map(np, src)
        if shape is None:
            shape = raw.shape
            ok = _base_valid(np, shape, valid).copy()
        elif raw.shape != shape:
            raise VerifyError(f"maps differ in shape: {_label(src, i)} is {raw.shape}, not {shape}")
        ok &= _predicted(np, raw, keep_zero)
        m = stats["models"][name]
        z = (decode_values(raw, m["decode"]) - m["mean"]) / m["sd"]
        acc = z if acc is None else acc + z
    return acc / len(maps), ok


def affine01(values, valid):
    """(values mapped to 0..1 over the valid pixels by one increasing affine map, min, max); no clipping."""
    np = _numpy()
    out = np.zeros(values.shape, np.float64)
    if not valid.any():
        return out, None, None
    v = values[valid].astype(np.float64)
    lo, hi = float(v.min()), float(v.max())
    out[valid] = (v - lo) / (hi - lo) if hi > lo else 0.0
    return out, lo, hi


# ---------------------------------------------------------------- files

def _saving(path, save):
    try:
        save()
    except OSError as exc:
        raise VerifyError(f"cannot write {path}: {exc}") from exc
    return str(path)


def write(path, combined, valid):
    np = _numpy()
    path = str(path)
    if path.endswith(".npy"):
        out = np.zeros(combined.shape, np.float32)
        out[valid] = (1.0 + np.clip(combined[valid], 0.0, 1.0) * 65534.0) / 65535.0
        return _saving(path, lambda: np.save(path, out))
    try:
        import tifffile
    except ImportError as exc:
        raise VerifyError("tifffile is required to write a .tif ensemble") from exc
    out = np.zeros(combined.shape, np.uint16)
    out[valid] = 1 + np.round(np.clip(combined[valid], 0.0, 1.0) * 65534).astype(np.uint16)
    return _saving(path, lambda: tifffile.imwrite(path, out))


def _check_raw_out(path):
    if path is not None and not str(path).endswith(".npy"):
        raise VerifyError(f"the raw output is a .npy file, not {path}")


def write_raw(path, values, valid):
    """Unscaled combined values, float32, NaN where invalid."""
    np = _numpy()
    _check_raw_out(path)
    out = np.full(values.shape, np.nan, np.float32)
    out[valid] = values[valid]
    return _saving(path, lambda: np.save(str(path), out))


def valid_from(path, shape=None, level="0", rows=VALID_ROWS):
    """Pixels where a surface volume (zarr) is > 0 in every layer, read in row blocks; or a mask map > 0."""
    np = _numpy()
    from . import s3retry
    try:
        s3retry.refuse_remote(path, "kit ensemble --valid-from")
    except ValueError as exc:
        raise VerifyError(str(exc)) from None
    p = Path(path)
    if p.is_dir() or p.suffix == ".zarr":
        from .layers import open_volume
        vol = open_volume(path, level)
        _, h, w = (int(s) for s in vol.shape)
        ok = np.zeros((h, w), bool)
        for r0 in range(0, h, rows):
            blk = np.asarray(vol[:, r0:r0 + rows, :])
            ok[r0:r0 + blk.shape[1]] = (blk > 0).all(0)
    else:
        ok = _as_map(np, path) > 0
    if shape is not None and ok.shape != tuple(shape):
        raise VerifyError(f"{path}: validity {ok.shape} differs from the maps' {tuple(shape)}")
    return ok


def load_stats(path):
    try:
        stats = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise VerifyError(f"cannot read statistics {path}: {exc}") from exc
    if not isinstance(stats, dict) or stats.get("kind") != STATS_KIND or not isinstance(stats.get("models"), dict):
        raise VerifyError(f"{path}: not a kit ensemble statistics file")

    def number(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)

    for name, m in stats["models"].items():
        if not (isinstance(m, dict) and m.get("decode") in DECODES and number(m.get("mean"))
                and number(m.get("sd")) and m["sd"] > 0):
            raise VerifyError(f"{path}: model {name} needs a finite mean, an sd above 0 and a decode of {DECODES}")
    return stats


def ensemble_files(out, inputs, method="mean", weights=None, decode="none", valid_path=None,
                   keep_zero=False, raw_out=None):
    """mean or rank (or zscore on the maps' own statistics) of map files; decode is one name or one per map."""
    _numpy()   # fail early, with the message that says where numpy is
    _check_raw_out(raw_out)
    if method == "zscore":
        if weights is not None:
            raise VerifyError("zscore is an unweighted mean (Nieuwlaar's rule); give no weights")
        names = [f"map{i + 1}" for i in range(len(inputs))]
        decodes = _decodes(decode, len(inputs))
        return zscore_files(out, list(zip(names, inputs)), decode=dict(zip(names, decodes)),
                            valid_path=valid_path, keep_zero=keep_zero, raw_out=raw_out)
    arrays = [_read(p) for p in inputs]
    valid = valid_from(valid_path, arrays[0].shape) if valid_path and arrays else None
    combined, ok = combine(arrays, method, weights, decode, valid, keep_zero)
    write(out, combined, ok)
    if raw_out:
        write_raw(raw_out, combined, ok)
    return {"out": str(out), "inputs": [str(p) for p in inputs], "method": method,
            "weights": list(weights) if weights else [1.0] * len(inputs),
            "shape": list(combined.shape), "valid_px": int(ok.sum()),
            "decode": _decodes(decode, len(inputs)), "valid_from": None if valid_path is None else str(valid_path),
            "keep_zero": bool(keep_zero), "raw_out": None if raw_out is None else str(raw_out)}


def zscore_files(out, maps, stats_path=None, pool=None, stats_out=None, decode=None, valid_path=None,
                 keep_zero=False, raw_out=None):
    """Nieuwlaar's z-score ensemble of (name, path) maps.

    Statistics come from `stats_path` (saved earlier), else from `pool` ((name, path) pairs), else
    from the maps themselves; `stats_out` saves them. With no maps, only the statistics are made.
    decode: None, one name for all models, or {name: decode}."""
    _numpy()
    _check_raw_out(raw_out)
    maps, pool = list(maps or []), list(pool or [])
    if maps and out is None:
        raise VerifyError("give the output map before the input maps")
    if not maps and (out is not None or raw_out is not None):
        raise VerifyError("an ensemble needs at least two maps")
    if stats_path and (pool or stats_out):
        raise VerifyError("--stats applies saved statistics; it does not go with --pool or --stats-out")
    names = [n for n, _ in maps]
    if len(set(names)) != len(names):
        raise VerifyError(f"give one map per model; repeated: {sorted({n for n in names if names.count(n) > 1})}")
    if maps and len(maps) < 2:
        raise VerifyError("an ensemble needs at least two maps")
    valid = valid_from(valid_path) if valid_path else None   # its shape is checked against the maps'
    if stats_path:
        stats = load_stats(stats_path)
        if decode is not None:
            for name in names:
                want = decode if isinstance(decode, str) else decode.get(name)
                have = stats["models"].get(name, {}).get("decode")
                if want is not None and have is not None and want != have:
                    raise VerifyError(f"model {name}: the statistics were computed with decode {have!r}, not {want!r}")
        if maps and sorted(names) != sorted(stats["models"]):
            raise VerifyError(f"the statistics hold the models {sorted(stats['models'])}; give one map for each")
        source = str(stats_path)
    else:
        if not maps and not pool:
            raise VerifyError("give maps, --pool maps or --stats")
        if not maps and not stats_out:
            raise VerifyError("with no maps to combine, give --stats-out to save the pooled statistics")
        if pool and maps:
            extra = sorted({n for n, _ in pool} - set(names))
            if extra:
                raise VerifyError(f"the pool has models that are not in the ensemble: {extra}")
            missing = [n for n in names if n not in {p for p, _ in pool}]
            if missing:
                raise VerifyError(f"no pooled maps for {missing}")
        order = names if maps else None
        stats = zscore_stats(pool or maps, decode if decode is not None else "none", valid, keep_zero, order)
        stats["valid_from"] = None if valid_path is None else str(valid_path)
        source = "pool" if pool else "maps"
        if stats_out:
            text = json.dumps(stats, indent=1) + "\n"
            _saving(stats_out, lambda: Path(stats_out).write_text(text))
    result = {"method": "zscore", "statistics_from": source, "stats_out": None if stats_out is None else str(stats_out),
              "valid_from": None if valid_path is None else str(valid_path), "keep_zero": bool(keep_zero),
              "models": {n: {"decode": m["decode"], "mean": m["mean"], "sd": m["sd"], "n_px": m.get("n_px")}
                         for n, m in stats["models"].items()},
              "stretch": {k: v for k, v in stats.get("ensemble", {}).items() if k in ("p1", "p99_5", "n_grid")}}
    if not maps:
        result["shape"] = stats.get("shape")
        return result
    z, ok = apply_zscore(maps, stats, valid, keep_zero)
    if not ok.any():
        raise VerifyError("no pixel is valid in every map")
    scaled, lo, hi = affine01(z, ok)
    write(out, scaled, ok)
    if raw_out:
        write_raw(raw_out, z, ok)
    result.update({"out": str(out), "inputs": [{"name": n, "path": str(p)} for n, p in maps],
                   "model_order": names, "shape": list(z.shape), "valid_px": int(ok.sum()),
                   "mean_z_min": lo, "mean_z_max": hi, "raw_out": None if raw_out is None else str(raw_out),
                   "scale": "tif u = 1 + round((z - mean_z_min) / (mean_z_max - mean_z_min) * 65534); npy u / 65535"})
    if lo is not None and "p1" in result["stretch"]:
        span = (hi - lo) or 1.0
        result["stretch_out_units"] = {k: 1.0 + (result["stretch"][k] - lo) / span * 65534.0 for k in ("p1", "p99_5")}
    return result


# ---------------------------------------------------------------- command line

def _looks_named(spec):
    return "=" in spec and bool(NAME_RE.match(spec.split("=", 1)[0])) and not Path(spec).exists()


def parse_named(spec, what="map"):
    """'NAME=PATH' to (NAME, PATH); None when spec is a plain path."""
    if "=" in spec and not Path(spec).exists():
        name, path = spec.split("=", 1)
        if NAME_RE.match(name) and path:
            return name, path
        raise VerifyError(f"{what} {spec!r}: expected NAME=PATH with a name of letters, digits, _ . + -")
    return None


def expand_pool(specs):
    """--pool NAME=PATH values to (name, path) pairs; a PATH with * ? or [ that is not a file is a glob."""
    out = []
    for spec in specs or []:
        named = parse_named(spec, "--pool")
        if named is None:
            raise VerifyError(f"--pool {spec!r}: expected NAME=PATH")
        name, path = named
        if any(ch in path for ch in "*?[") and not Path(path).exists():
            hits = sorted(glob.glob(path))
            if not hits:
                raise VerifyError(f"--pool {spec!r}: no file matches")
            out.extend((name, h) for h in hits)
        else:
            out.append((name, path))
    return out


def parse_decode(specs):
    """--decode values ('ls', 'none', 'NAME=ls', ...) to (default or None, {name: decode})."""
    default, per = None, {}
    for spec in specs or []:
        name, how = spec.split("=", 1) if "=" in spec else (None, spec)
        if how not in DECODES:
            raise VerifyError(f"--decode {spec!r}: expected [NAME=]{'|'.join(DECODES)}")
        if name is None:
            if default is not None and default != how:
                raise VerifyError("give one --decode for all maps, and NAME=... for the exceptions")
            default = how
        elif not NAME_RE.match(name):
            raise VerifyError(f"--decode {spec!r}: bad model name")
        elif per.get(name, how) != how:
            raise VerifyError(f"--decode gives model {name} two decodes: {per[name]} and {how}")
        else:
            per[name] = how
    return default, per


def from_args(args):
    """Run `kit ensemble` from its parsed arguments; returns the result dict."""
    default, per = parse_decode(getattr(args, "decode", None))
    zs_only = [flag for flag, v in (("--pool", args.pool), ("--stats", args.stats), ("--stats-out", args.stats_out))
               if v]
    if args.method != "zscore":
        if zs_only:
            raise VerifyError(f"{', '.join(zs_only)} belong to --method zscore")
        if per:
            raise VerifyError("a decode per model (NAME=...) needs --method zscore; give one --decode for all maps")
        if args.out is None or len(args.maps) < 2:
            raise VerifyError("give the output map and at least two input maps")
        return ensemble_files(args.out, args.maps, args.method, args.weights, default or "none",
                              args.valid_from, args.keep_zero, args.raw_out)
    if args.weights:
        raise VerifyError("zscore is an unweighted mean (Nieuwlaar's rule); give no --weights")
    if args.out is not None and _looks_named(args.out):
        raise VerifyError(f"{args.out!r} looks like a NAME=PATH map; the output map comes first")
    maps = []
    for i, spec in enumerate(args.maps):
        named = parse_named(spec)
        if named is None:
            if args.stats or args.pool:
                raise VerifyError(f"map {spec!r}: give NAME=PATH so its model's statistics can be found")
            named = (f"map{i + 1}", spec)
        maps.append(named)
    pool = expand_pool(args.pool)
    names = [n for n, _ in maps] or list(dict.fromkeys(n for n, _ in pool))
    unknown = sorted(set(per) - set(names)) if names else []
    if unknown:
        raise VerifyError(f"--decode names models that are not given: {unknown}")
    decode = None   # None: as the statistics say (or none); a model left out of --decode is not checked
    if default is not None or per:
        decode = ({n: per.get(n, default) for n in names if n in per or default is not None} if names
                  else default)
    return zscore_files(args.out, maps, args.stats, pool, args.stats_out, decode, args.valid_from,
                        args.keep_zero, args.raw_out)


def format_result(result):
    if result["method"] != "zscore":
        return (f"{result['method']} of {len(result['inputs'])} maps -> {result['out']} "
                f"({result['valid_px']} valid px of {result['shape'][0]} x {result['shape'][1]})")
    rows = []
    if result.get("stats_out"):
        rows.append(f"statistics of {len(result['models'])} models ({result['statistics_from']}) -> {result['stats_out']}")
    for name, m in result["models"].items():
        rows.append(f"  {name}: decode {m['decode']}, mean {m['mean']:.6f}, sd {m['sd']:.6f}"
                    + (f" over {m['n_px']} px" if m.get("n_px") else ""))
    s = result.get("stretch") or {}
    if "p1" in s:
        rows.append(f"  display stretch of the mean z (p1..p99.5 on the fixed grid): {s['p1']:.4f} .. {s['p99_5']:.4f}")
    if "out" in result:
        rows.append(f"zscore of {len(result['inputs'])} maps -> {result['out']} ({result['valid_px']} valid px of "
                    f"{result['shape'][0]} x {result['shape'][1]}; mean z {result['mean_z_min']:.4f} .. "
                    f"{result['mean_z_max']:.4f} mapped to 1..65535, statistics from {result['statistics_from']})")
    return "\n".join(rows)
