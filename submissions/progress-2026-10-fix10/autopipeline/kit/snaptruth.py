"""Score a surface-label snap against an independent scan: registration along the normal, sheet faces, gains.

Pure numpy, no I/O: the callers sample the volumes and pass profiles.

A profile is a row of intensities along one line, sampled at offsets t (voxels of the label frame, uniform step)
measured from a label vertex along its unit normal. Three steps:

1. `register_shift`: the shift s along the normal that best aligns profiles of the truth scan (resampled to the
   label scan's resolution) with profiles of the label scan, scored by the mean per-line normalised cross
   correlation over the samples a mask keeps. Leaving out the band around the label (|t| < E) means the shift is
   fitted on the neighbouring sheets only, so the sheet the snap moves toward is not used to place the truth.
   Fitting the inner side (t <= -E) and the outer side (t >= E) separately gives two independent estimates whose
   difference measures how well the shift is known at the label.
2. `sheet_faces`: on the truth profile (sampled at t + s), the papyrus bands (runs above a level half way between
   the profile's 10th and 90th percentiles, after a light Gaussian smoothing; dips shorter than `fill` are closed
   and runs shorter than `min_band` dropped), the band nearest the label (by distance from t = 0 to the band), its
   two faces (sub-sample crossings of the level), midline and thickness, and flags that say when the answer is
   ambiguous.
3. `gains`: per vertex, |error before| - |error after| for each arm, positive when the arm moved the label closer to
   the truth surface; `site_bootstrap` gives the mean over sites (each site the mean of its vertices) with a
   percentile interval from resampling sites.

Recto side. Rolled papyrus is written on the inside, so the recto face is the face toward the scroll axis
(Interpretation, the usual convention; villa #1640 reports surface labels marking the recto face). `recto_sign`
is the sign of the normal's component along the outward radial direction: +1 means t grows outward, so the recto
face is the band's lower face.
"""

import math

import numpy as np


# ---------------------------------------------------------------- smoothing and resampling

def smooth(p, sigma):
    """Gaussian smoothing along the last axis, sigma in samples, edges reflected (numpy only)."""
    p = np.asarray(p, dtype=np.float64)
    if sigma <= 0:
        return p.copy()
    r = max(1, int(4.0 * sigma + 0.5))
    x = np.arange(-r, r + 1)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    k /= k.sum()
    pad = [(0, 0)] * (p.ndim - 1) + [(r, r)]
    q = np.pad(p, pad, mode="reflect")
    out = np.zeros_like(p)
    n = p.shape[-1]
    for j, w in enumerate(k):
        out += w * q[..., j:j + n]
    return out


def shifted(t_ext, prof_ext, t, s):
    """Profiles sampled on t_ext (uniform), read at t + s by linear interpolation (nan outside t_ext)."""
    prof_ext = np.atleast_2d(np.asarray(prof_ext, dtype=np.float64))
    q = np.asarray(t, dtype=np.float64) + float(s)
    out = np.empty((prof_ext.shape[0], len(q)))
    for i in range(prof_ext.shape[0]):
        out[i] = np.interp(q, t_ext, prof_ext[i], left=np.nan, right=np.nan)
    return out


# ---------------------------------------------------------------- 1. registration along the normal

def _ncc_rows(a, b, m):
    """Per-row normalised cross correlation of a and b over the samples where m (and both finite); nan for a row
    with fewer than 8 such samples or no variance."""
    ok = m[None, :] & np.isfinite(a) & np.isfinite(b)
    out = np.full(a.shape[0], np.nan)
    for i in range(a.shape[0]):
        k = ok[i]
        if k.sum() < 8:
            continue
        x = a[i, k] - a[i, k].mean()
        y = b[i, k] - b[i, k].mean()
        den = math.sqrt(float((x * x).sum() * (y * y).sum()))
        if den > 1e-12:
            out[i] = float((x * y).sum()) / den
    return out


def register_shift(t, ref, t_ext, mov_ext, mask, s_max=4.0, step=0.05):
    """The shift s (in t units) maximising the mean per-line NCC between ref (lines x len(t)) and the moving
    profiles read at t + s, over the samples where mask (len(t), bool). Returns a dict: shift (refined below a step
    by a parabola), peak (mean NCC there), curve (s values and scores), edge (the peak is at the end of the search
    range, so the shift is not trusted), lines (lines with a score)."""
    t = np.asarray(t, dtype=np.float64)
    ref = np.atleast_2d(np.asarray(ref, dtype=np.float64))
    mask = np.asarray(mask, dtype=bool)
    ss = np.arange(-s_max, s_max + 0.5 * step, step)
    sc = np.full(len(ss), np.nan)
    nlines = 0
    for j, s in enumerate(ss):
        r = _ncc_rows(ref, shifted(t_ext, mov_ext, t, s), mask)
        if np.isfinite(r).any():
            sc[j] = float(np.nanmean(r))
            nlines = max(nlines, int(np.isfinite(r).sum()))
    if not np.isfinite(sc).any():
        return {"shift": float("nan"), "peak": float("nan"), "edge": True, "lines": 0, "curve": [ss, sc]}
    k = int(np.nanargmax(sc))
    best = float(ss[k])
    edge = k == 0 or k == len(ss) - 1
    if not edge and np.isfinite(sc[k - 1]) and np.isfinite(sc[k + 1]):
        a, b, c = sc[k - 1], sc[k], sc[k + 1]
        den = a - 2 * b + c
        if den < 0:
            best += float(np.clip(0.5 * (a - c) / den, -0.5, 0.5)) * step
    return {"shift": best, "peak": float(sc[k]), "edge": bool(edge), "lines": nlines, "curve": [ss, sc]}


# ---------------------------------------------------------------- 2. sheet faces on the truth profile

FACE_DEFAULTS = {
    "sigma": 0.5,        # smoothing, in t units (voxels of the label frame)
    "lo_pct": 10.0,      # percentile taken as the gap level
    "hi_pct": 90.0,      # percentile taken as the papyrus level
    "level": 0.5,        # face level between them
    "fill": 1.0,         # close dips shorter than this (t units): partial dips between fibre layers
    "min_band": 1.0,     # drop runs shorter than this (t units): specks
    "ambiguous": 2.0,    # second nearest band within this much farther than the nearest: ambiguous
    "split_sigma": 0.25, # finer smoothing for the split check
    "split_len": 1.0,    # a dip below the level at least this long inside the band (fine profile) splits it
}


def _runs(b):
    """(start, end) index pairs of the True runs of a 1-D boolean array, end exclusive."""
    d = np.diff(np.concatenate([[0], b.astype(np.int8), [0]]))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def _crossing(t, p, i0, i1, level):
    """Sub-sample t where p crosses level between samples i0 and i1 (linear)."""
    a, b = p[i0], p[i1]
    if b == a:
        return 0.5 * (t[i0] + t[i1])
    f = (level - a) / (b - a)
    return float(t[i0] + min(max(f, 0.0), 1.0) * (t[i1] - t[i0]))


def bands(t, p, opts=None):
    """Papyrus bands of one profile: (list of (lower face, upper face)), level, contrast. A run touching either end
    of the profile has no face there, which is recorded as nan."""
    o = dict(FACE_DEFAULTS)
    o.update(opts or {})
    t = np.asarray(t, dtype=np.float64)
    dt = float(t[1] - t[0])
    ps = smooth(np.asarray(p, dtype=np.float64), o["sigma"] / dt)
    lo, hi = np.percentile(ps, [o["lo_pct"], o["hi_pct"]])
    level = lo + o["level"] * (hi - lo)
    above = ps >= level
    n = len(ps)
    # close short dips inside papyrus
    for s, e in _runs(~above):
        if s > 0 and e < n and (e - s) * dt < o["fill"]:
            above[s:e] = True
    out = []
    for s, e in _runs(above):
        if (e - s) * dt < o["min_band"]:
            continue
        lower = _crossing(t, ps, s - 1, s, level) if s > 0 else float("nan")
        upper = _crossing(t, ps, e - 1, e, level) if e < n else float("nan")
        out.append((lower, upper))
    return out, float(level), float(hi - lo)


def sheet_faces(t, p, recto_sign, at=0.0, opts=None):
    """The band nearest `at` on one truth profile and its faces. Returns a dict with recto, verso, mid, thick
    (t units, nan when a face is missing), dist (from `at` to the band, 0 inside), second (distance to the next
    nearest band), gap_recto and gap_verso (clear gap between that face and the next band on its side, nan when the
    profile ends first), split (the finer profile dips below the level for at least split_len inside the band, so
    at full resolution the band is two or more layers), contrast, and ok (a face pair exists and the choice is
    not ambiguous)."""
    o = dict(FACE_DEFAULTS)
    o.update(opts or {})
    bl, level, contrast = bands(t, p, o)
    res = {"recto": float("nan"), "verso": float("nan"), "mid": float("nan"), "thick": float("nan"),
           "dist": float("nan"), "second": float("nan"), "gap_recto": float("nan"), "gap_verso": float("nan"),
           "split": False, "contrast": contrast, "n_bands": len(bl), "ok": False, "why": ""}
    if not bl:
        res["why"] = "no band"
        return res
    t0, t1 = float(t[0]), float(t[-1])

    def dist(b):
        lo = b[0] if math.isfinite(b[0]) else t0
        hi = b[1] if math.isfinite(b[1]) else t1
        return 0.0 if lo <= at <= hi else min(abs(at - lo), abs(at - hi))

    d = np.array([dist(b) for b in bl])
    order = np.argsort(d, kind="stable")
    k = int(order[0])
    lower, upper = bl[k]
    res["dist"] = float(d[k])
    res["second"] = float(d[order[1]]) if len(bl) > 1 else float("inf")
    below = [b[1] for b in bl[:k]]                   # upper faces of the bands below
    above = [b[0] for b in bl[k + 1:]]               # lower faces of the bands above
    gap_lo = float(lower - below[-1]) if below and math.isfinite(below[-1]) else float("nan")
    gap_hi = float(above[0] - upper) if above and math.isfinite(above[0]) else float("nan")
    if recto_sign > 0:
        recto, verso = lower, upper
        res["gap_recto"], res["gap_verso"] = gap_lo, gap_hi
    else:
        recto, verso = upper, lower
        res["gap_recto"], res["gap_verso"] = gap_hi, gap_lo
    res["recto"], res["verso"] = float(recto), float(verso)
    if math.isfinite(lower) and math.isfinite(upper):
        res["mid"] = 0.5 * (lower + upper)
        res["thick"] = upper - lower
        dt = float(t[1] - t[0])
        fine = smooth(np.asarray(p, dtype=np.float64), o["split_sigma"] / dt)
        inside = (t > lower) & (t < upper)
        low = inside & (fine < level)
        res["split"] = any((e - s) * dt >= o["split_len"] for s, e in _runs(low))
    if not (math.isfinite(lower) and math.isfinite(upper)):
        res["why"] = "band runs off the profile"
    elif res["second"] - res["dist"] < o["ambiguous"]:
        res["why"] = "two bands about as near"
    else:
        res["ok"] = True
    return res


# ---------------------------------------------------------------- 2b. a second face definition: the steepest edge

GRAD_DEFAULTS = {
    "grad_sigma": 1.0,   # smoothing before the derivative, in t units
}


def _parabola_peak(t, g, k):
    """Sub-sample position of the extremum of g at index k (a parabola through k - 1, k, k + 1)."""
    a, b, c = g[k - 1], g[k], g[k + 1]
    den = a - 2 * b + c
    dt = float(t[1] - t[0])
    if den == 0:
        return float(t[k])
    return float(t[k] + float(np.clip(0.5 * (a - c) / den, -0.5, 0.5)) * dt)


def gradient_faces(t, p, recto_sign, at=0.0, opts=None):
    """The band nearest `at` (chosen as in sheet_faces) with its faces placed by a second, independent rule: each
    face is the steepest edge of the profile on its side of the band (the largest rise for the lower face, the
    largest fall for the upper face), searched from half way across the gap to the next band (or the profile's end)
    to the band's half-level midline, after Gaussian smoothing at grad_sigma, refined by a parabola. It shares only
    the band's identity with sheet_faces, never its level: the faces do not depend on the profile's percentiles, so a
    snap built on the half-level crossing is not scored only by its own rule. Returns the keys of sheet_faces
    (recto, verso, mid, thick from these faces; dist, second, gaps, split and contrast from sheet_faces) plus
    recto_half and verso_half (the half-level faces), and ok False with a reason when the steepest edge sits at the
    end of its search window (no interior edge)."""
    o = dict(FACE_DEFAULTS)
    o.update(GRAD_DEFAULTS)
    o.update(opts or {})
    res = sheet_faces(t, p, recto_sign, at, o)
    res["recto_half"], res["verso_half"] = res["recto"], res["verso"]
    if not res["ok"]:
        return res
    t = np.asarray(t, dtype=np.float64)
    dt = float(t[1] - t[0])
    ps = smooth(np.asarray(p, dtype=np.float64), o["grad_sigma"] / dt)
    g = np.gradient(ps, dt)
    if recto_sign > 0:
        lower, upper, gap_lo, gap_hi = res["recto"], res["verso"], res["gap_recto"], res["gap_verso"]
    else:
        lower, upper, gap_lo, gap_hi = res["verso"], res["recto"], res["gap_verso"], res["gap_recto"]
    mid = 0.5 * (lower + upper)
    a_lo = lower - 0.5 * gap_lo if math.isfinite(gap_lo) else float(t[0])
    b_hi = upper + 0.5 * gap_hi if math.isfinite(gap_hi) else float(t[-1])
    faces = []
    for a, b, sign in ((a_lo, mid, 1.0), (mid, b_hi, -1.0)):
        idx = np.nonzero((t >= a) & (t <= b))[0]
        if len(idx) < 3:
            faces.append(None)
            continue
        k = int(idx[np.argmax(sign * g[idx])])
        if k <= idx[0] or k >= idx[-1] or sign * g[k] <= 0:
            faces.append(None)
            continue
        faces.append(_parabola_peak(t, g, k))
    if faces[0] is None or faces[1] is None:
        res.update({"recto": float("nan"), "verso": float("nan"), "mid": float("nan"), "thick": float("nan"),
                    "ok": False, "why": "no interior steepest edge"})
        return res
    lo_g, hi_g = faces
    recto, verso = (lo_g, hi_g) if recto_sign > 0 else (hi_g, lo_g)
    res.update({"recto": float(recto), "verso": float(verso), "mid": 0.5 * (lo_g + hi_g), "thick": hi_g - lo_g})
    return res


# ---------------------------------------------------------------- 3. gains and the site bootstrap

def depth(x, recto, verso):
    """Normalised depth of positions x in the sheet: 0 at the recto face, 1 at the verso face."""
    x, recto, verso = (np.asarray(a, dtype=np.float64) for a in (x, recto, verso))
    with np.errstate(invalid="ignore", divide="ignore"):
        return (x - recto) / (verso - recto)


def offsheet(x, recto, verso):
    """Distance of positions x from the sheet [min(recto, verso), max(recto, verso)], 0 inside."""
    x, recto, verso = (np.asarray(a, dtype=np.float64) for a in (x, recto, verso))
    lo, hi = np.minimum(recto, verso), np.maximum(recto, verso)
    return np.maximum(0.0, np.maximum(lo - x, x - hi))


def gains(x_arm, x_id, truth):
    """|x_id - truth| - |x_arm - truth| per vertex (positions along the normal, same units)."""
    x_arm, x_id, truth = (np.asarray(a, dtype=np.float64) for a in (x_arm, x_id, truth))
    return np.abs(x_id - truth) - np.abs(x_arm - truth)


def site_means(values, sites):
    """Mean of values per site id (ignoring nan); returns (site ids, means, counts)."""
    values = np.asarray(values, dtype=np.float64)
    sites = np.asarray(sites)
    ids = []
    means = []
    counts = []
    for s in sorted(set(sites.tolist())):
        v = values[(sites == s) & np.isfinite(values)]
        if len(v):
            ids.append(s)
            means.append(float(v.mean()))
            counts.append(int(len(v)))
    return ids, np.array(means), np.array(counts)


def site_bootstrap(site_values, n_boot=10000, seed=0, level=0.95):
    """Mean of per-site values with a percentile bootstrap interval over sites."""
    v = np.asarray(site_values, dtype=np.float64)
    v = v[np.isfinite(v)]
    if not len(v):
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"), "n_sites": 0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(v), size=(n_boot, len(v)))
    bm = v[idx].mean(axis=1)
    a = (1 - level) / 2
    return {"mean": float(v.mean()), "lo": float(np.quantile(bm, a)), "hi": float(np.quantile(bm, 1 - a)),
            "n_sites": int(len(v))}


def classify(ci, margin):
    """GAIN, HARM, NULL (interval inside +-margin) or INCONCLUSIVE from a bootstrap interval dict."""
    if not math.isfinite(ci["mean"]):
        return "NO DATA"
    if ci["lo"] > 0 and ci["mean"] >= margin:
        return "GAIN"
    if ci["hi"] < 0 and ci["mean"] <= -margin:
        return "HARM"
    if ci["lo"] > -margin and ci["hi"] < margin:
        return "NULL"
    return "INCONCLUSIVE"
