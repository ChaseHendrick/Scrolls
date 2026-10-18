"""Metrics for StrokeNet's evaluation, numpy only (scipy is used for t quantiles when importable).

  auc, paired_frac, average_precision, ap_at   ranking measures (AUC counts ties as one half)
  platt_fit, sigmoid                            Platt scaling: weighted, Platt's smoothed targets,
                                                damped Newton with a convergence check
  ece, brier, reliability, mixture_weights      calibration on a weighted mixture of window kinds
  blocks, block_bootstrap, per_group            intervals that resample whole clusters of windows
                                                (a segment's 512 px column band), since windows
                                                of one area are not independent
  sign_flip, t_interval                         exact paired sign-flip test and t interval over a
                                                handful of per-segment differences
"""
import math
from statistics import NormalDist

import numpy as np


def auc(pos, neg):
    """P(score of a positive > score of a negative) + 0.5 P(tie) (Mann-Whitney U / n1 n2)."""
    pos, neg = np.asarray(pos, np.float64).ravel(), np.asarray(neg, np.float64).ravel()
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    allv = np.concatenate([pos, neg])
    _, inv, counts = np.unique(allv, return_inverse=True, return_counts=True)
    start = np.cumsum(counts) - counts               # 0-based rank where each distinct value starts
    avg_rank = start + (counts + 1) / 2.0            # 1-based average rank of each distinct value
    rp = avg_rank[inv[:len(pos)]].sum()
    return float((rp - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg)))


def paired_frac(a, b):
    """Fraction of pairs (same window) where a scores strictly above b."""
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    return float(np.mean(a > b)) if len(a) else float("nan")


def average_precision(pos, neg, prevalence=None, seed=0):
    """Average precision; with prevalence, positives are subsampled (without replacement) so they
    make up that share of the pool. Ties are broken by input order, positives first."""
    pos, neg = np.asarray(pos, np.float64), np.asarray(neg, np.float64)
    if prevalence is not None:
        n_pos = int(round(prevalence / (1 - prevalence) * len(neg)))
        if n_pos < len(pos):
            pos = np.random.default_rng(seed).choice(pos, n_pos, replace=False)
    s = np.concatenate([pos, neg])
    y = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))])
    o = np.argsort(-s, kind="mergesort")
    y = y[o]
    tp = np.cumsum(y)
    prec = tp / np.arange(1, len(y) + 1)
    return float((prec * y).sum() / max(y.sum(), 1))


def ap_at(pos, neg, prevalence=0.10, repeats=20):
    return float(np.mean([average_precision(pos, neg, prevalence, seed=s) for s in range(repeats)]))


def sigmoid(z):
    z = np.asarray(z, np.float64)
    return np.where(z >= 0, 1 / (1 + np.exp(-np.abs(z))), np.exp(-np.abs(z)) / (1 + np.exp(-np.abs(z))))


def _weights(w, n):
    """Sample weights as float64 summing to 1 (equal weights when w is None)."""
    if w is None:
        return np.full(n, 1.0 / n) if n else np.zeros(0)
    w = np.asarray(w, np.float64).ravel()
    if len(w) != n:
        raise ValueError(f"{len(w)} weights for {n} samples")
    if not np.all(np.isfinite(w)) or (w < 0).any() or w.sum() <= 0:
        raise ValueError("weights must be finite, non-negative and not all zero")
    return w / w.sum()


# ------------------------------------------------------------------ Platt scaling
def platt_fit(z, y, w=None, iters=100, tol=1e-9):
    """Platt scaling p = sigmoid(a z + b), fitted by weighted maximum likelihood.

    The targets are Platt's smoothed ones, (N+ + 1) / (N+ + 2) for positives and 1 / (N- + 2)
    for negatives, where N+ and N- count the samples (not their weights), so a separable set
    still has a finite optimum. The fit runs on standardised scores (weighted mean and standard
    deviation) by damped Newton steps: each step is halved until the weighted log loss decreases
    enough (Armijo rule). It stops when the largest gradient component of the mean loss is below
    tol and raises RuntimeError if that does not happen within iters steps, or if a line search
    finds no decrease while the gradient is above 1e-6. Returns (a, b) for the raw scores z.
    Constant scores give a = 0 and b at the weighted target rate."""
    z, y = np.asarray(z, np.float64).ravel(), np.asarray(y, np.float64).ravel()
    if len(z) != len(y) or len(z) == 0:
        raise ValueError("z and y must be non-empty and of equal length")
    if not np.all(np.isfinite(z)):
        raise ValueError("scores must be finite")
    if not np.all((y == 0) | (y == 1)):
        raise ValueError("labels must be 0 or 1")
    w = _weights(w, len(z))
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    t = np.where(y == 1, (n_pos + 1.0) / (n_pos + 2.0), 1.0 / (n_neg + 2.0))
    tbar = float(w @ t)
    mu = float(w @ z)
    sd = math.sqrt(float(w @ (z - mu) ** 2))
    if sd <= 1e-12 * max(1.0, abs(mu)):
        return 0.0, math.log(tbar / (1 - tbar))
    s = (z - mu) / sd

    def loss(th):
        u = th[0] * s + th[1]
        return float(w @ (t * np.logaddexp(0, -u) + (1 - t) * np.logaddexp(0, u)))

    th = np.array([0.0, math.log(tbar / (1 - tbar))])     # slope 0, intercept at the base rate
    f = loss(th)
    for it in range(iters + 1):
        p = sigmoid(th[0] * s + th[1])
        r = w * (p - t)
        g = np.array([r @ s, r.sum()])
        if np.abs(g).max() <= tol:
            break
        if it == iters:
            raise RuntimeError(f"platt_fit did not converge in {iters} steps (gradient {np.abs(g).max():.3g})")
        h = w * p * (1 - p)
        H = np.array([[h @ (s * s), h @ s], [h @ s, h.sum()]]) + 1e-12 * np.eye(2)
        step = np.linalg.solve(H, g)
        lam = 1.0
        while lam >= 1e-10:
            new = th - lam * step
            f_new = loss(new)
            if f_new <= f - 1e-4 * lam * float(g @ step):
                break
            lam /= 2
        else:
            if np.abs(g).max() <= 1e-6:          # no decrease left at rounding level: converged
                break
            raise RuntimeError(f"platt_fit: line search failed (gradient {np.abs(g).max():.3g})")
        th, f = new, f_new
    a = th[0] / sd
    return float(a), float(th[1] - a * mu)


# ------------------------------------------------------------------ calibration
def _bin_masks(p, bins):
    edges = np.linspace(0, 1, bins + 1)
    for i in range(bins):
        yield edges[i], edges[i + 1], (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= 1))


def ece(p, y, w=None, bins=10):
    """Expected calibration error over equal-width probability bins, with optional sample weights:
    sum over bins of (bin weight share) x |weighted mean p - weighted mean y|."""
    p, y = np.asarray(p, np.float64).ravel(), np.asarray(y, np.float64).ravel()
    if len(p) == 0:
        return float("nan")
    w = _weights(w, len(p))
    e = 0.0
    for _, _, m in _bin_masks(p, bins):
        wb = w[m].sum()
        if wb > 0:
            e += abs(w[m] @ p[m] - w[m] @ y[m])        # = wb * |mean p - mean y| (weighted)
    return float(e)


def brier(p, y, w=None):
    """(Weighted) mean squared difference between probability and label."""
    p, y = np.asarray(p, np.float64).ravel(), np.asarray(y, np.float64).ravel()
    if len(p) == 0:
        return float("nan")
    return float(_weights(w, len(p)) @ (p - y) ** 2)


def reliability(p, y, w=None, bins=10):
    """One row per equal-width bin: its edges, sample count n, share of the total weight, and the
    weighted mean probability and fraction of positives (None for an empty bin)."""
    p, y = np.asarray(p, np.float64).ravel(), np.asarray(y, np.float64).ravel()
    w = _weights(w, len(p))
    rows = []
    for lo, hi, m in _bin_masks(p, bins):
        wb = float(w[m].sum())
        rows.append({"bin": [round(lo, 2), round(hi, 2)], "n": int(m.sum()), "weight": wb,
                     "mean_p": float(w[m] @ p[m] / wb) if wb > 0 else None,
                     "frac_pos": float(w[m] @ y[m] / wb) if wb > 0 else None})
    return rows


def mixture_weights(counts, shares):
    """Per-sample weight of each component so that its samples together carry its share of the
    mixture: {name: share / sum(shares) / counts[name]}. Every name in shares needs at least one
    sample when its share is positive (ValueError otherwise); a zero share gives weight 0."""
    total = float(sum(shares.values()))
    if total <= 0 or any(v < 0 for v in shares.values()):
        raise ValueError("shares must be non-negative and not all zero")
    out = {}
    for k, sh in shares.items():
        n = int(counts[k])
        if sh > 0 and n <= 0:
            raise ValueError(f"component {k} has share {sh} but no samples")
        out[k] = sh / total / n if sh > 0 else 0.0
    return out


# ------------------------------------------------------------------ resampling
BAND_BASE = 100000      # cluster id = segment index * BAND_BASE + column band


def blocks(seg_ids, pos, band_px=512):
    """Cluster id of each window: its segment and the band_px wide column band that holds its
    left edge, seg_id * 100000 + x // band_px with x = pos[:, 1] (pos rows are (y, x) in the
    pooled map). 512 px is 24.6 mm at 0.048 mm per pixel."""
    seg = np.asarray(seg_ids, np.int64).ravel()
    pos = np.asarray(pos, np.int64).reshape(-1, 2)
    if len(seg) != len(pos):
        raise ValueError("one segment id and one position per window")
    band = pos[:, 1] // int(band_px)
    if (seg < 0).any() or (pos[:, 1] < 0).any() or (band >= BAND_BASE).any():
        raise ValueError("segment ids and x positions must be non-negative and bands below 100000")
    return seg * BAND_BASE + band


def _cluster_index(ids, universe):
    """Positions of each universe id's members (ascending), as one sorted index and slices."""
    ids = np.asarray(ids, np.int64).ravel()
    order = np.argsort(ids, kind="stable")
    sid = ids[order]
    start = np.searchsorted(sid, universe, "left")
    return order, start, np.searchsorted(sid, universe, "right") - start


def _bootstrap(fn, groups, universe, n, seed, level):
    universe = np.asarray(universe, np.int64)
    k = len(universe)
    if k == 0:
        return float("nan"), float("nan"), 0
    rng = np.random.default_rng(seed)
    index = {name: _cluster_index(g, universe) for name, g in groups.items()}
    vals = []
    for _ in range(n):
        draw = rng.integers(k, size=k)
        take = {}
        for name, (order, start, cnt) in index.items():
            c = cnt[draw]
            # every member of each drawn cluster, once per draw, clusters in draw order
            take[name] = order[np.repeat(start[draw] - (np.cumsum(c) - c), c) + np.arange(c.sum())]
        v = fn(take)
        if v == v:
            vals.append(v)
    if not vals:
        return float("nan"), float("nan"), 0
    a = (1 - level) / 2
    return float(np.quantile(vals, a)), float(np.quantile(vals, 1 - a)), len(vals)


def block_bootstrap(fn, groups, n=2000, seed=0, level=0.95):
    """Percentile interval of fn(take) over resamples of whole clusters.

    groups: {name: int array of cluster ids, one per score} (for example from blocks()). Each
    resample draws, with replacement, as many clusters as there are distinct ids in the union of
    all groups, and takes every score of each drawn cluster once per draw; fn(take) gets
    {name: index array into that group's scores} and returns a float. Groups with equal id arrays
    get equal index arrays, so paired measures stay paired. Resamples where fn returns nan are
    dropped. Returns (lo, hi, n_used)."""
    ids = [np.asarray(g, np.int64).ravel() for g in groups.values()]
    universe = np.unique(np.concatenate(ids)) if ids else np.zeros(0, np.int64)
    return _bootstrap(fn, groups, universe, n, seed, level)


def segment_bootstrap(fn, groups, n_seg, n=2000, seed=0, level=0.95):
    """Percentile interval over resamples of whole segments 0..n_seg-1 (groups hold segment
    indices). Kept for callers of the 14 October code: the same draws as before, now a thin
    wrapper around the cluster bootstrap; block_bootstrap is the preregistered interval."""
    return _bootstrap(fn, groups, np.arange(n_seg), n, seed, level)


def per_group(fn, groups):
    """{id: fn(take)} for every id in the union of the groups' ids, take = {name: indices of that
    group's scores with this id} (possibly empty, so fn may return nan)."""
    ids = [np.asarray(g, np.int64).ravel() for g in groups.values()]
    if not ids:
        return {}
    out = {}
    for i in np.unique(np.concatenate(ids)):
        out[int(i)] = float(fn({name: np.nonzero(np.asarray(g).ravel() == i)[0] for name, g in groups.items()}))
    return out


def sign_flip(diffs):
    """Exact one-sided p-value for mean(diffs) > 0: the share of all 2^n sign patterns whose
    signed sum is at least the observed sum (the observed pattern counts, so p >= 2^-n). nan
    entries are dropped first; n must be at most 12. Returns nan for no values."""
    d = np.asarray(diffs, np.float64).ravel()
    d = d[~np.isnan(d)]
    n = len(d)
    if n == 0:
        return float("nan")
    if n > 12 or not np.all(np.isfinite(d)):
        raise ValueError("sign_flip takes at most 12 finite differences")
    signs = 1.0 - 2.0 * ((np.arange(2 ** n)[:, None] >> np.arange(n)) & 1)
    sums = (signs * d).sum(axis=1)
    tol = 1e-10 * max(1.0, float(np.abs(d).sum()))      # rounding: equal sums count as ties
    return float(np.mean(sums >= d.sum() - tol))


# Two-sided t quantiles t(1 - (1 - level) / 2, df) for df 1..30 (scipy.stats.t.ppf, 6 decimals),
# used when scipy is not importable.
T_TABLE = {
    0.90: (6.313752, 2.919986, 2.353363, 2.131847, 2.015048, 1.943180, 1.894579, 1.859548, 1.833113,
           1.812461, 1.795885, 1.782288, 1.770933, 1.761310, 1.753050, 1.745884, 1.739607, 1.734064,
           1.729133, 1.724718, 1.720743, 1.717144, 1.713872, 1.710882, 1.708141, 1.705618, 1.703288,
           1.701131, 1.699127, 1.697261),
    0.95: (12.706205, 4.302653, 3.182446, 2.776445, 2.570582, 2.446912, 2.364624, 2.306004, 2.262157,
           2.228139, 2.200985, 2.178813, 2.160369, 2.144787, 2.131450, 2.119905, 2.109816, 2.100922,
           2.093024, 2.085963, 2.079614, 2.073873, 2.068658, 2.063899, 2.059539, 2.055529, 2.051831,
           2.048407, 2.045230, 2.042272),
    0.99: (63.656741, 9.924843, 5.840909, 4.604095, 4.032143, 3.707428, 3.499483, 3.355387, 3.249836,
           3.169273, 3.105807, 3.054540, 3.012276, 2.976843, 2.946713, 2.920782, 2.898231, 2.878440,
           2.860935, 2.845340, 2.831360, 2.818756, 2.807336, 2.796940, 2.787436, 2.778715, 2.770683,
           2.763262, 2.756386, 2.749996),
}


def t_quantile(df, level=0.95, use_scipy=True):
    """Two-sided t quantile for a level-confidence interval with df degrees of freedom: scipy
    when importable, else the table above (df 1..30, levels 0.90, 0.95, 0.99) and, beyond df 30,
    the Cornish-Fisher expansion around the normal quantile (error below 1e-4)."""
    if use_scipy:
        try:
            from scipy import stats
            return float(stats.t.ppf(1 - (1 - level) / 2, df))
        except ImportError:
            pass
    df = int(df)
    if df < 1:
        raise ValueError("df must be at least 1")
    if df <= 30:
        for lv, row in T_TABLE.items():
            if abs(level - lv) < 1e-12:
                return row[df - 1]
        raise ValueError(f"no t table for level {level} without scipy")
    z = NormalDist().inv_cdf(1 - (1 - level) / 2)
    return (z + (z ** 3 + z) / (4 * df) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * df ** 2)
            + (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / (384 * df ** 3))


def t_interval(values, level=0.95):
    """t interval for the mean of values (nan dropped): mean +- t(df = n - 1) sd / sqrt(n).
    Returns (lo, hi), both nan for fewer than two values."""
    v = np.asarray(values, np.float64).ravel()
    v = v[~np.isnan(v)]
    n = len(v)
    if n < 2:
        return float("nan"), float("nan")
    half = t_quantile(n - 1, level) * float(v.std(ddof=1)) / math.sqrt(n)
    m = float(v.mean())
    return m - half, m + half
