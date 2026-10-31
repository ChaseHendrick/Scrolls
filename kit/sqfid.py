"""Cross-scan sheet fidelity: how much of the sheet pattern a finer, independent scan shows in a region does a coarse
scan (or another acquisition put on the coarse grid) keep there? (`kit/sqfid.py`; used by kit/sqrecipe.py.)

The measure needs no labels and no model. In a 128-voxel region on the coarse scan's own grid, the finer scan is
resampled onto that grid through a published affine transform (fine_on_coarse). Both cubes are band-passed to the
sheet band (a difference of Gaussians), and the fidelity is the normalized cross-correlation (NCC) of the two at the
best integer shift within +-max_shift voxels (published transforms hold only to a few voxels). High: the coarse cube
reproduces the sheets the finer scan sees there. Low: it loses them (compressed sheets, noise, blur).

Its control (outcome_control) pairs each coarse cube with another region's fine cube under the same shift search; the
true pair must win in most regions, or the measure cannot tell regions apart. Statistics are cluster bootstraps over
blocks of 4 x 4 x 4 regions.

Every number is a Measurement of the CT, never a reading.
"""

import hashlib
import json
import math

RULE = {
    "region_vox": 128,
    "fine_level": 2,
    "min_mask_share": 0.98,               # both cubes: CT above 0 in at least this share, else the region is skipped
    "band_sigmas": [1.0, 3.0],            # difference of Gaussians, coarse voxels: passes periods of about 6 to 20
    "max_shift": 6,                       # integer shift search, each axis
    "inner": 8,                           # the coarse cube's border left out of the NCC (room for the shift)
    "cluster_regions": 4,                 # bootstrap cluster: a block of 4 x 4 x 4 regions
    "bootstrap": {"resamples": 2000, "seed": 0, "level": 0.95},
    "outcome_control": {"min_share_lb": 0.75, "seed": 7},
}


class FidError(RuntimeError):
    pass


def _np():
    try:
        import numpy
    except ImportError as exc:
        raise FidError("kit sqfid needs numpy") from exc
    return numpy


def _nd():
    try:
        from scipy import ndimage
    except ImportError as exc:
        raise FidError("kit sqfid needs scipy") from exc
    return ndimage


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def digest(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


# ---------------------------------------------------------------- region codes

def region_code(zyx):
    """One integer per region from its (z, y, x) chunk indices (each below 1024)."""
    z, y, x = (int(i) for i in zyx)
    if not all(0 <= i < 1024 for i in (z, y, x)):
        raise FidError(f"region index {zyx} outside 0 to 1023")
    return (z << 20) | (y << 10) | x


def region_index(code):
    """(z, y, x) chunk indices of a region code."""
    code = int(code)
    return (code >> 20, (code >> 10) & 1023, code & 1023)


def cluster_of(code, rule=None):
    """Bootstrap cluster: the block of cluster_regions^3 regions holding the region, as 'z_y_x'."""
    rule = rule or RULE
    c = int(rule["cluster_regions"])
    return "_".join(str(int(i) // c) for i in region_index(code))


# ---------------------------------------------------------------- statistics

def spearman(x, y):
    """Spearman's rank correlation with average ranks for ties; nan when either side is constant or under 3."""
    np = _np()
    from scipy.stats import rankdata
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return float("nan")
    rx, ry = rankdata(x), rankdata(y)
    rx, ry = rx - rx.mean(), ry - ry.mean()
    den = math.sqrt(float((rx * rx).sum() * (ry * ry).sum()))
    return float((rx * ry).sum() / den) if den > 0 else float("nan")


def bootstrap(stat_fns, n_items, clusters, rule=None, seed=None):
    """Cluster bootstrap: resample clusters with replacement and evaluate every stat_fn(index) on the pooled
    members. Returns {name: array of resampled values}."""
    np = _np()
    rule = rule or RULE
    B = rule["bootstrap"]
    labels, inv = np.unique(np.asarray(clusters), return_inverse=True)
    members = [np.flatnonzero(inv == i) for i in range(len(labels))]
    rng = np.random.default_rng(B["seed"] if seed is None else seed)
    out = {k: np.empty(B["resamples"]) for k in stat_fns}
    m = len(members)
    for i in range(B["resamples"]):
        pick = rng.integers(0, m, m)
        idx = np.concatenate([members[j] for j in pick])
        for k, f in stat_fns.items():
            out[k][i] = f(idx)
    return out


def interval(vals, rule=None):
    """The central interval at rule['bootstrap']['level'] of the finite values."""
    np = _np()
    rule = rule or RULE
    a = (1 - rule["bootstrap"]["level"]) / 2
    v = np.asarray(vals, float)
    v = v[np.isfinite(v)]
    if not v.size:
        return [float("nan"), float("nan")]
    return [float(np.quantile(v, a)), float(np.quantile(v, 1 - a))]


# ---------------------------------------------------------------- geometry: the fine scan on the coarse grid

def coarse_to_fine(affine, direction):
    """3 x 4 matrix (xyz) from coarse level-0 voxels to fine level-0 voxels. `affine` is a published transform
    (3 x 4 or 4 x 4); direction 'fine_to_coarse' when it maps the fine volume into the coarse frame,
    'coarse_to_fine' when it maps the coarse volume into the fine frame."""
    np = _np()
    A = np.asarray(affine, float)
    if direction == "coarse_to_fine":
        return A[:3, :4].copy()
    if direction != "fine_to_coarse":
        raise FidError(f"unknown direction {direction}")
    Minv = np.linalg.inv(A[:3, :3])
    return np.concatenate([Minv, (-Minv @ A[:3, 3])[:, None]], 1)


def fine_on_coarse(arr, level, M, origin, R=128):
    """The fine array (level `level`) resampled trilinearly on the coarse cube [origin, origin + R) (zyx). M maps
    coarse xyz to fine level-0 xyz; level-0 voxel v sits at (v + 0.5) / 2**level - 0.5 of the level. `arr` has
    block(lo, size) returning (array, missing chunks). Voxels whose nearest fine voxel is 0 (outside the fine mask)
    stay 0."""
    np = _np()
    nd = _nd()
    M = np.asarray(M, float)
    o = np.asarray(origin, dtype=np.int64)
    zz, yy, xx = np.meshgrid(*[np.arange(R) + o[i] for i in range(3)], indexing="ij")
    rxyz = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], 1).astype(float)
    vxyz = rxyz @ M[:, :3].T + M[:, 3]
    f = 2.0 ** level
    vz, vy, vx = ((vxyz[:, 2] + 0.5) / f - 0.5, (vxyz[:, 1] + 0.5) / f - 0.5, (vxyz[:, 0] + 0.5) / f - 0.5)
    lo = np.floor([vz.min(), vy.min(), vx.min()]).astype(np.int64) - 1
    hi = np.ceil([vz.max(), vy.max(), vx.max()]).astype(np.int64) + 2
    block, _ = arr.block(lo, hi - lo)
    q = np.stack([vz - lo[0], vy - lo[1], vx - lo[2]])
    vals = nd.map_coordinates(block.astype(np.float32), q, order=1, mode="constant", cval=0.0)
    near = nd.map_coordinates(block, q, order=0, mode="constant", cval=0)
    vals = np.where(near > 0, np.clip(np.rint(vals), 1, 255), 0)
    return vals.reshape(R, R, R).astype(np.uint8)


# ---------------------------------------------------------------- the fidelity

def bandpass(x, rule=None):
    """Difference of Gaussians at band_sigmas of a cube (float32); outside voxels (0) take the inside mean first."""
    np = _np()
    nd = _nd()
    rule = rule or RULE
    a = np.asarray(x, dtype=np.float32)
    on = a > 0
    if on.any():
        a = np.where(on, a, a[on].mean()).astype(np.float32)
    s1, s2 = rule["band_sigmas"]
    return nd.gaussian_filter(a, s1) - nd.gaussian_filter(a, s2)


def best_ncc(c, f, rule=None):
    """NCC of the band-passed coarse cube's inner part (border `inner`) against the band-passed fine cube shifted by
    every integer offset within +-max_shift: (best NCC, its shift zyx). Inputs are band-passed cubes. Direct loop;
    best_ncc_fast gives the same result."""
    np = _np()
    rule = rule or RULE
    m, e = int(rule["max_shift"]), int(rule["inner"])
    if m > e:
        raise FidError("max_shift cannot exceed inner")
    n = c.shape[0]
    a = c[e:n - e, e:n - e, e:n - e].astype(np.float64)
    a = a - a.mean()
    na = math.sqrt(float((a * a).sum()))
    best, arg = -2.0, (0, 0, 0)
    if na <= 0:
        return float("nan"), [0, 0, 0]
    F = f.astype(np.float64)
    for dz in range(-m, m + 1):
        for dy in range(-m, m + 1):
            for dx in range(-m, m + 1):
                b = F[e + dz:n - e + dz, e + dy:n - e + dy, e + dx:n - e + dx]
                bm = b - b.mean()
                nb = math.sqrt(float((bm * bm).sum()))
                if nb <= 0:
                    continue
                v = float((a * bm).sum()) / (na * nb)
                if v > best:
                    best, arg = v, (dz, dy, dx)
    return best, list(arg)


def best_ncc_fast(c, f, rule=None):
    """best_ncc by FFT: the cross-correlation of the inner coarse part with the fine cube over all shifts within
    +-max_shift, normalized by the fine window's local energy (the NCC of best_ncc, up to rounding)."""
    np = _np()
    rule = rule or RULE
    m, e = int(rule["max_shift"]), int(rule["inner"])
    if m > e:
        raise FidError("max_shift cannot exceed inner")
    n = c.shape[0]
    L = n - 2 * e
    a = c[e:n - e, e:n - e, e:n - e].astype(np.float64)
    a = a - a.mean()
    na = math.sqrt(float((a * a).sum()))
    if na <= 0:
        return float("nan"), [0, 0, 0]
    W = f[e - m:n - e + m, e - m:n - e + m, e - m:n - e + m].astype(np.float64)   # L + 2m per axis
    K = W.shape[0]        # L + 2m: zero-padding a to K, circular correlation is exact for shifts 0 to 2m
    a = a.astype(np.float32)
    W = W.astype(np.float32)
    FA = np.fft.rfftn(a, (K, K, K), axes=(0, 1, 2))
    FW = np.fft.rfftn(W, (K, K, K), axes=(0, 1, 2))
    corr = np.fft.irfftn(FW * np.conj(FA), (K, K, K), axes=(0, 1, 2))[:2 * m + 1, :2 * m + 1, :2 * m + 1]
    ones = np.ones_like(a)
    FO = np.conj(np.fft.rfftn(ones, (K, K, K), axes=(0, 1, 2)))
    s1 = np.fft.irfftn(FW * FO, (K, K, K), axes=(0, 1, 2))[:2 * m + 1, :2 * m + 1, :2 * m + 1]
    s2 = np.fft.irfftn(np.fft.rfftn(W * W, (K, K, K), axes=(0, 1, 2)) * FO, (K, K, K),
                       axes=(0, 1, 2))[:2 * m + 1, :2 * m + 1, :2 * m + 1]
    N = float(L ** 3)
    var = np.maximum(s2 - s1 * s1 / N, 1e-12)
    ncc = corr / (na * np.sqrt(var))          # a has mean 0, so corr with W equals corr with W - mean(W)
    idx = np.unravel_index(int(np.argmax(ncc)), ncc.shape)
    return float(ncc[idx]), [int(i) - m for i in idx]


def outcome(coarse, fine, rule=None):
    """The region's fidelity: best NCC of the band-passed cubes, its shift, and whether the shift is at the search
    border (the transform is then off by more than the search may hold)."""
    rule = rule or RULE
    v, s = best_ncc_fast(bandpass(coarse, rule), bandpass(fine, rule), rule)
    return {"fidelity": round(v, 6), "shift": s, "at_border": bool(max(abs(i) for i in s) >= int(rule["max_shift"]))}


# ---------------------------------------------------------------- the control

def derangement(n, seed):
    """A seeded permutation with no fixed point (n >= 2): region i's coarse cube meets region perm[i]'s fine cube."""
    np = _np()
    rng = np.random.default_rng(seed)
    while True:
        p = rng.permutation(n)
        if n < 2 or not (p == np.arange(n)).any():
            return [int(i) for i in p]


def outcome_control(true_vals, mis_vals, clusters, rule=None):
    """Share of regions where the true pair's fidelity beats the mismatched pair's, with its cluster-bootstrap
    interval; holds when the lower bound is above min_share_lb."""
    np = _np()
    rule = rule or RULE
    t, m = np.asarray(true_vals, float), np.asarray(mis_vals, float)
    win = (t > m).astype(float)
    boot = bootstrap({"share": lambda i: float(win[i].mean()),
                      "med_gap": lambda i: float(np.median((t - m)[i]))}, len(t), clusters, rule)
    ci = interval(boot["share"], rule)
    return {"n": int(len(t)), "share": float(win.mean()), "share_ci": ci,
            "median_true": float(np.median(t)), "median_mismatched": float(np.median(m)),
            "median_gap_ci": interval(boot["med_gap"], rule),
            "holds": bool(ci[0] > rule["outcome_control"]["min_share_lb"])}
