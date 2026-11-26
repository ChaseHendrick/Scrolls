#!/usr/bin/env python3
"""simreal: measure how real CT looks, from its grey values only, and fit kit.hardcases' render to it.

Real sheets in some scans look cleaner and wider than default ScrollSim tiles draw them (25 Nov 2026). simreal
turns that into numbers and a fit, never reading a label:

- `window_stats(w)`: for one 2D window, kit.ctmatch's bright fraction, noise and grain, plus three ridge statistics
  from the window's own bright ridges (skimage Sato, kept where it is a local maximum across the ridge and above its
  own 80th percentile): `width`, the median best Hessian scale at ridge pixels (sheet width in voxels); `pitch`,
  twice the median distance from ridge-free midlines to the nearest ridge (sheet spacing); `contrast`, the ridge
  pixels' mean minus the mid-gap pixels' mean, in the window's 1st to 99th percentile units.
- `measure(slices, masks)` and `measure_tiles(images)`: those statistics over many windows, summarised by quartiles.
- `fit(real, tiles_fn, grid)`: each candidate set of render bounds (kit.hardcases.realism) renders tiles; the one
  whose window statistics sit nearest the real quartiles, in units of the real spread, wins.
- `features`, `realism_auc`, `search`: a 35-feature linear realism test (real against real sits near 0.5) and a
  random or local search of render bounds that lowers it.

The real side holds grey-value statistics only. It is a training-data setting, not a reading.

    python -m kit.simreal measure SLICES.npz OUT.json        # npz with 'ct' (and optional 'mask') object arrays
    python -m kit.simreal fit OUT.json scanA=REAL_A.json scanB=REAL_B.json [--n 96] [--workers 4]
"""
import argparse
import json
import sys

STATS = ("bright", "noise", "grain", "width", "pitch", "contrast")
SCALES = (0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0)
WIN = 256
# The fit weighs the statistics the detectors are most sensitive to: noise and width first (observed 25 Nov 2026).
WEIGHTS = {"bright": 1.0, "noise": 2.0, "grain": 0.5, "width": 2.0, "pitch": 1.0, "contrast": 1.0}
# Candidate render bounds (kit.hardcases.REAL_KEYS), crossed with sheet fill (kit.hardcases.dense FILL).
GRID = {
    "sd": [(0.04, 0.16), (0.02, 0.10), (0.01, 0.06), (0.005, 0.03)],
    "psf": [(0.5, 1.4), (1.0, 1.8), (1.4, 2.2)],
    "ply_w": [(0.12, 0.25), (0.22, 0.42), (0.4, 0.7)],
    "fill": [None, (0.5, 0.8), (0.75, 0.95)],
}


class RealError(ValueError):
    pass


def _np():
    import numpy as np
    return np


def _nd():
    from scipy import ndimage as nd
    return nd


def ridge_lines(s):
    """Label-free bright ridge pixels of a window S (already scaled to its 1..99 percentiles): Sato response that is a
    local maximum along either image axis and above the response's own 80th percentile."""
    np = _np()
    nd = _nd()
    from skimage.filters import sato
    r = sato(s, sigmas=(1.0, 1.5, 2.0, 2.5, 3.0), black_ridges=False)
    keep = _thin_max(np, nd, r)
    return keep & (r > np.percentile(r, 80)), r


def _thin_max(np, nd, r):
    """Pixels that are the maximum of R along either image axis within +-1 (ridges running along the other axis)."""
    a = (r >= np.roll(r, 1, 0)) & (r >= np.roll(r, -1, 0))
    b = (r >= np.roll(r, 1, 1)) & (r >= np.roll(r, -1, 1))
    return a | b


def window_stats(w):
    """Grey-value statistics of one 2D window W (any scale): STATS as a dict of floats, or None when W is flat."""
    np = _np()
    nd = _nd()
    from kit import ctmatch
    w = np.asarray(w, np.float64)
    if not np.isfinite(w).all():
        raise RealError("non-finite window")
    lo, hi = np.percentile(w, [1, 99])
    if hi - lo <= 1e-9:
        return None
    base = ctmatch.window_stats(w)
    s = (w - lo) / (hi - lo)
    ln, _ = ridge_lines(s)
    if ln.sum() < 50:
        return None
    best = []
    for sg in SCALES:
        hxx = nd.gaussian_filter(s, sg, order=(0, 2))
        hyy = nd.gaussian_filter(s, sg, order=(2, 0))
        hxy = nd.gaussian_filter(s, sg, order=(1, 1))
        lmin = (hxx + hyy) / 2 - np.sqrt(((hxx - hyy) / 2) ** 2 + hxy ** 2)
        best.append(-lmin[ln] * sg * sg)
    width = float(np.median(np.array(SCALES)[np.argmax(np.array(best), 0)]))
    dt = nd.distance_transform_edt(~ln)
    mid = (dt >= nd.maximum_filter(dt, 3)) & (dt >= 2) & (dt < 40)
    pitch = float(2 * np.median(dt[mid])) if mid.any() else float("nan")
    gap = dt >= 0.4 * pitch if np.isfinite(pitch) else dt >= 3
    contrast = float(s[ln].mean() - s[gap].mean()) if gap.any() else float("nan")
    return {"bright": float(base["bright"]), "noise": float(base["noise"]), "grain": float(base["grain"]),
            "width": width, "pitch": pitch, "contrast": contrast}


def summarise(rows):
    """Quartiles (25, 50, 75) of every statistic over ROWS (list of window_stats dicts, None skipped)."""
    np = _np()
    rows = [r for r in rows if r]
    if not rows:
        raise RealError("no usable window")
    out = {"windows": len(rows)}
    for k in STATS:
        v = np.array([r[k] for r in rows], float)
        v = v[np.isfinite(v)]
        out[k] = [float(x) for x in np.percentile(v, [25, 50, 75])] if len(v) else [float("nan")] * 3
    return out


def measure(slices, masks=None, n=160, seed=0, win=WIN, min_cover=0.98):
    """Statistics of N random full windows of real SLICES (list of 2D arrays), inside MASKS when given."""
    np = _np()
    rng = np.random.default_rng(int(seed))
    cand = [i for i, s in enumerate(slices) if s.shape[0] >= win and s.shape[1] >= win]
    if not cand:
        raise RealError("no slice holds a full window")
    rows, tries = [], 0
    while len(rows) < n and tries < 30 * n:
        tries += 1
        i = cand[int(rng.integers(len(cand)))]
        H, W = slices[i].shape
        y, x = int(rng.integers(0, H - win + 1)), int(rng.integers(0, W - win + 1))
        if masks is not None and masks[i][y:y + win, x:x + win].mean() < min_cover:
            continue
        st = window_stats(slices[i][y:y + win, x:x + win])
        if st:
            rows.append(st)
    return summarise(rows)


def measure_tiles(images, air=None):
    """Statistics of synthetic tiles IMAGES (N, H, W); tiles with more than 5 % air (AIR mask) are skipped, so the
    comparison is papyrus against papyrus as the real windows are."""
    rows = []
    for i, im in enumerate(images):
        if air is not None and air[i].mean() > 0.05:
            continue
        rows.append(window_stats(im))
    return summarise(rows)


def distance(real, sim, weights=None):
    """Weighted distance between two summaries: per statistic, |median difference| plus half the |IQR difference|,
    in units of the real IQR (floored at 5 % of the real median's size)."""
    weights = weights or WEIGHTS
    d = 0.0
    for k, wt in weights.items():
        r, s = real[k], sim[k]
        iqr = max(r[2] - r[0], 0.05 * abs(r[1]), 1e-6)
        d += wt * (abs(s[1] - r[1]) + 0.5 * abs((s[2] - s[0]) - (r[2] - r[0]))) / iqr
    return d


def grid_points(grid=None):
    import itertools
    grid = grid or GRID
    keys = list(grid)
    for vals in itertools.product(*(grid[k] for k in keys)):
        yield dict(zip(keys, vals))


def render_tiles(point, n=96, seed=5):
    """N kit.hardcases tiles (seed SEED) rendered under POINT's bounds; returns images and air masks."""
    np = _np()
    from kit import hardcases
    pt = dict(point)
    fill = pt.pop("fill", None)
    core = pt.pop("core", None)
    ims, airs = [], []
    with hardcases.realism(**pt), hardcases.dense(fill=fill, core=core):
        for k in range(n):
            t = hardcases.tile(seed, k)
            ims.append(t["image"])
            airs.append(t["air"])
    return np.stack(ims), np.stack(airs)


def _point_summary(args):
    pt, n, seed = args
    ims, air = render_tiles(pt, n, seed)
    return measure_tiles(ims, air)


def fit(real, n=96, seed=5, grid=None, progress=print, workers=1, reals=None):
    """Grid search of render bounds whose tiles' statistics sit nearest REAL (a summary). REALS, a dict of name to
    summary, ranks the same rendered points against several real scans at once (one render per point). Returns the
    ranked list of {point, summary, distance} (with REALS: a dict of such lists)."""
    pts = list(grid_points(grid))
    jobs = [(pt, n, seed) for pt in pts]
    if workers > 1:
        from multiprocessing import Pool
        with Pool(workers) as pool:
            sums = pool.map(_point_summary, jobs)
    else:
        sums = [_point_summary(j) for j in jobs]
    targets = reals if reals is not None else {"real": real}
    out = {}
    for name, r in targets.items():
        rows = [{"point": pt, "summary": sm, "distance": distance(r, sm)} for pt, sm in zip(pts, sums)]
        out[name] = sorted(rows, key=lambda x: x["distance"])
        if progress:
            progress(f"fit {name}: best {out[name][0]['point']} distance {out[name][0]['distance']:.2f}")
    return out if reals is not None else out["real"]


def features(w):
    """A fixed feature vector of one 2D window for the realism test: 17 quantiles of the window scaled to its 1..99
    percentiles, the radially averaged log power spectrum in 12 bands (mean removed), and the six STATS."""
    np = _np()
    w = np.asarray(w, np.float64)
    lo, hi = np.percentile(w, [1, 99])
    s = (w - lo) / max(hi - lo, 1e-9)
    q = np.quantile(s, np.linspace(0.02, 0.98, 17))
    f = np.abs(np.fft.fftshift(np.fft.fft2(s - s.mean()))) ** 2
    H, W = s.shape
    yy, xx = np.indices((H, W))
    k = np.rint(np.hypot(yy - H // 2, xx - W // 2)).astype(int)
    kmax = min(H, W) // 2
    prof = np.bincount(k.ravel(), f.ravel(), kmax + 1)[1:kmax] / np.maximum(np.bincount(k.ravel(), None, kmax + 1)[1:kmax], 1)
    # the log power at 12 frequencies spread evenly in log between the lowest and the Nyquist, as a fraction of it
    at = np.geomspace(1, kmax - 1, 12)
    ps = np.interp(np.log(at), np.log(np.arange(1, kmax)), np.log(prof + 1e-12))
    ps = ps - ps.mean()
    st = window_stats(w) or {k: float("nan") for k in STATS}
    return np.concatenate([q, ps, [st[k] for k in STATS]])


def _auc(score, y):
    np = _np()
    order = np.argsort(score)
    ranks = np.empty(len(score))
    ranks[order] = np.arange(1, len(score) + 1)
    n1 = int(y.sum())
    n0 = len(y) - n1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / max(1, n0 * n1))


def realism_auc(real_feats, sim_feats, folds=5, seed=0, l2=1.0, iters=400):
    """Can a linear classifier tell real windows from simulated ones? L2 logistic regression on standardised
    features, FOLDS-fold cross-validated ROC AUC (0.5: indistinguishable to it; 1.0: always told apart). A realism
    measure, not a proof: a stronger classifier may still separate them."""
    np = _np()
    X = np.vstack([real_feats, sim_feats]).astype(np.float64)
    y = np.r_[np.ones(len(real_feats)), np.zeros(len(sim_feats))]
    X = np.where(np.isfinite(X), X, np.nan)
    med = np.array([np.nanmedian(c) if np.isfinite(c).any() else 0.0 for c in X.T])
    X = np.where(np.isfinite(X), X, med)
    rng = np.random.default_rng(int(seed))
    fold = rng.permutation(len(y)) % folds
    score = np.zeros(len(y))
    for k in range(folds):
        tr, te = fold != k, fold == k
        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
        A, B = (X[tr] - mu) / sd, (X[te] - mu) / sd
        w = np.zeros(A.shape[1])
        b = 0.0
        for _ in range(iters):
            p = 1 / (1 + np.exp(-(A @ w + b)))
            g = A.T @ (p - y[tr]) / len(A) + l2 * w / len(A)
            w -= 0.5 * g
            b -= 0.5 * float((p - y[tr]).mean())
        score[te] = B @ w + b
    return _auc(score, y)


def windows(slices, masks=None, n=160, seed=0, win=WIN, min_cover=0.98):
    """N random full windows of SLICES (inside MASKS when given), as a list of arrays."""
    np = _np()
    rng = np.random.default_rng(int(seed))
    cand = [i for i, s in enumerate(slices) if s.shape[0] >= win and s.shape[1] >= win]
    out, tries = [], 0
    while len(out) < n and tries < 30 * n:
        tries += 1
        i = cand[int(rng.integers(len(cand)))]
        H, W = slices[i].shape
        y, x = int(rng.integers(0, H - win + 1)), int(rng.integers(0, W - win + 1))
        if masks is not None and masks[i][y:y + win, x:x + win].mean() < min_cover:
            continue
        out.append(np.asarray(slices[i][y:y + win, x:x + win], np.float64))
    return out


# Presets (25 Nov 2026), from a random then local search over SPACE on 64 tiles a point, scored by realism_auc
# against 120 windows of the scan's CT (grey values only). "343p": PHerc0343P, a public fragment scan that is on no
# prize list. In the search, selected on those same windows, it lowers the linear test's AUC from 0.999 to 0.986; on
# other windows of the scan the preset tiles still score 1.000 (0.995 with kit.ctmatch's histogram match). The render
# knobs alone do not make tiles indistinguishable from real CT.
PRESETS = {
    "343p": {"sd": (0.0189, 0.1015), "psf": (0.9598, 1.6667), "ply_w": (0.4638, 0.6789), "rim": (0.0141, 0.6042),
             "gap": (0.0, 0.1055), "pitch": (0.9454, 1.0234), "fill": (0.35, 0.5762), "core": (0.7671, 1.1573)},
}

SPACE = {"sd": (0.003, 0.2), "psf": (0.4, 2.6), "ply_w": (0.1, 0.8), "rim": (0.0, 1.2), "gap": (0.0, 0.5),
         "pitch": (0.6, 1.3), "fill": (0.35, 0.97), "core": (0.1, 1.2)}


def random_point(rng, around=None, spread=0.25):
    """A random point of SPACE: each setting a (lo, hi) bound pair; AROUND (a point) narrows the draw to SPREAD of
    each range about its centre, for a local search."""
    pt = {}
    for k, (a, b) in SPACE.items():
        if around and k in around and around[k] is not None:
            c = sum(around[k]) / 2
            h = (around[k][1] - around[k][0]) / 2
            c = float(rng.uniform(max(a, c - spread * (b - a)), min(b, c + spread * (b - a))))
            h = float(max(0.0, h * rng.uniform(0.6, 1.5)))
        else:
            c = float(rng.uniform(a, b))
            h = float(rng.uniform(0.05, 0.25) * (b - a))
        lo, hi = max(a, c - h), min(b, c + h)
        if k == "fill":
            hi = min(hi, 0.97)
        pt[k] = (round(lo, 4), round(max(lo, hi), 4))
    return pt


def _point_auc(args):
    pt, n, seed, real_feats = args
    np = _np()
    ims, air = render_tiles(pt, n, seed)
    keep = [i for i in range(len(ims)) if air[i].mean() <= 0.05]
    feats = np.array([features(ims[i]) for i in keep])
    return realism_auc(np.asarray(real_feats), feats)


def search(real_feats, points, n=64, seed=5, workers=1):
    """Realism AUC of every point in POINTS against REAL_FEATS (rows of features()), lowest first."""
    jobs = [(pt, n, seed, real_feats) for pt in points]
    if workers > 1:
        from multiprocessing import Pool
        with Pool(workers) as pool:
            aucs = pool.map(_point_auc, jobs)
    else:
        aucs = [_point_auc(j) for j in jobs]
    return sorted(({"point": p, "auc": a} for p, a in zip(points, aucs)), key=lambda r: r["auc"])


def _load_slices(path):
    np = _np()
    z = np.load(path, allow_pickle=True)
    ct = list(z["ct"])
    mask = list(z["mask"]) if "mask" in z.files else None
    return ct, mask


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kit.simreal", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure", help="grey-value statistics of real slices (npz with ct, optional mask)")
    m.add_argument("slices")
    m.add_argument("out")
    m.add_argument("--n", type=int, default=160)
    m.add_argument("--no-mask", action="store_true", help="ignore the npz mask (use when it is derived from labels)")
    f = sub.add_parser("fit", help="grid-fit kit.hardcases render bounds to measured summaries")
    f.add_argument("out")
    f.add_argument("real", nargs="+", help="NAME=SUMMARY.json, one or more")
    f.add_argument("--n", type=int, default=96)
    f.add_argument("--seed", type=int, default=5)
    f.add_argument("--workers", type=int, default=1)
    a = ap.parse_args(argv)
    if a.cmd == "measure":
        ct, mask = _load_slices(a.slices)
        if a.no_mask:
            mask = None
        res = measure(ct, mask, a.n)
        json.dump(res, open(a.out, "w"), indent=1)
        print(json.dumps(res))
        return 0
    reals = {}
    for spec in a.real:
        name, _, path = spec.partition("=")
        if not path:
            raise SystemExit(f"fit: expected NAME=SUMMARY.json, got {spec!r}")
        reals[name] = json.load(open(path))
    ranked = fit(None, a.n, a.seed, workers=a.workers, reals=reals)
    json.dump({"real": reals, "ranked": ranked}, open(a.out, "w"), indent=1)
    for name, rows in ranked.items():
        print(f"{name}: best {rows[0]['point']} distance {rows[0]['distance']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
