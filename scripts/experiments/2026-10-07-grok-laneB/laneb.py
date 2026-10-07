"""Label-free statistics for ink maps (lane B, 2026-10-07). numpy and scipy only.

Each function takes plain 2D arrays on one surface grid; tests in tests/test_laneb.py.
"""
import hashlib
import numpy as np
from scipy import ndimage as ndi


def file_sha256(path, chunk_bytes=1024 * 1024):
    """Stream an input digest using APIs available on Python 3.10."""
    if chunk_bytes < 1:
        raise ValueError("chunk_bytes must be positive")
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_bytes), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normals_from_xyz(xyz, valid):
    """Unit surface normals of a tifxyz grid (H, W, 3) by central differences; NaN off-surface."""
    valid = geometry_valid(xyz, valid)
    clean = np.where(valid[..., None], xyz, np.nan)
    du = np.gradient(clean, axis=1)
    dv = np.gradient(clean, axis=0)
    n = np.cross(du, dv)
    norm = np.linalg.norm(n, axis=-1, keepdims=True)
    n = n / np.where(norm > 0, norm, np.nan)
    n[~known_feature_support(valid, extra=1)] = np.nan
    return n


def stretch_from_xyz(xyz, valid=None):
    """Local area of one grid cell in volume voxels squared (mesh stretch)."""
    valid = geometry_valid(xyz, valid)
    clean = np.where(valid[..., None], xyz, np.nan)
    du = np.gradient(clean, axis=1)
    dv = np.gradient(clean, axis=0)
    area = np.linalg.norm(np.cross(du, dv), axis=-1)
    area[~known_feature_support(valid, extra=1)] = np.nan
    return area


def geometry_valid(xyz, valid=None):
    intrinsic = np.isfinite(xyz).all(-1) & (xyz >= 0).all(-1) & (xyz.sum(-1) > 0)
    return intrinsic if valid is None else intrinsic & np.asarray(valid, bool)


def known_feature_support(mask, *sigmas, extra=0):
    """Conservative square support for composed Gaussian filters and stencils."""
    radius = int(extra) + sum(int(np.ceil(4 * float(s))) for s in sigmas)
    return ndi.minimum_filter(np.asarray(mask, bool), size=2 * radius + 1,
                              mode="constant", cval=0).astype(bool)


def known_high_pass(img, known, sigma):
    """High-pass and valid core; unknown labels are never image background."""
    known = np.asarray(known, bool)
    clean = np.where(known, img, 0.0).astype(np.float64)
    weight = ndi.gaussian_filter(known.astype(float), sigma)
    trend = ndi.gaussian_filter(clean, sigma) / np.maximum(weight, 1e-12)
    return clean - trend, known_feature_support(known, sigma)


def orientation(img, sigma_grad=1.0, sigma_win=4.0, known=None):
    """Structure-tensor orientation of the dominant line direction (radians in [0, pi)) and coherence.

    Lines along x (horizontal stripes varying in y) give angle 0.
    """
    f = img.astype(np.float64) if known is None else np.where(known, img, 0.0).astype(np.float64)
    gy = ndi.gaussian_filter(f, sigma_grad, order=(1, 0))
    gx = ndi.gaussian_filter(f, sigma_grad, order=(0, 1))
    jxx = ndi.gaussian_filter(gx * gx, sigma_win)
    jyy = ndi.gaussian_filter(gy * gy, sigma_win)
    jxy = ndi.gaussian_filter(gx * gy, sigma_win)
    grad_angle = 0.5 * np.arctan2(2 * jxy, jxx - jyy)      # direction of strongest gradient
    line_angle = np.mod(grad_angle + np.pi / 2, np.pi)      # lines run perpendicular to it
    tr = jxx + jyy
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / np.where(tr > 0, tr, np.inf)
    if known is not None:
        core = known_feature_support(known, sigma_grad, sigma_win)
        line_angle[~core] = np.nan
        coh[~core] = np.nan
    return line_angle, coh


def axial_diff(a, b):
    """Smallest difference of two axial angles (period pi), in [0, pi/2]."""
    d = np.abs(np.mod(a - b, np.pi))
    return np.minimum(d, np.pi - d)


def angle_hist(angle, weight, bins=12):
    """Weighted histogram of axial angles over [0, pi), normalised to sum 1."""
    h, _ = np.histogram(np.mod(angle, np.pi), bins=bins, range=(0, np.pi), weights=weight)
    return h / max(h.sum(), 1e-12)


def autocorr_profile(img, mask, max_lag):
    """Normalised autocorrelation along y and along x of a masked image, lags 0..max_lag."""
    if not np.asarray(mask).any() or not np.isfinite(img[mask]).all() or np.std(img[mask]) == 0:
        return np.full(max_lag + 1, np.nan), np.full(max_lag + 1, np.nan)
    f = np.where(mask, img - img[mask].mean(), 0.0).astype(np.float64)
    m = mask.astype(np.float64)
    shape = [s + max_lag for s in f.shape]
    F = np.fft.rfft2(f, shape)
    M = np.fft.rfft2(m, shape)
    num = np.fft.irfft2(F * np.conj(F), shape)
    cnt = np.fft.irfft2(M * np.conj(M), shape)
    ac = num / np.maximum(cnt, 1.0)
    ac = ac / ac[0, 0]
    return ac[: max_lag + 1, 0], ac[0, : max_lag + 1]


def first_crossing(profile, level):
    """First lag where a decreasing profile drops below level (linear interpolation); NaN if never."""
    for i in range(1, len(profile)):
        if profile[i] < level:
            p0, p1 = profile[i - 1], profile[i]
            return (i - 1) + (p0 - level) / (p0 - p1)
    return float("nan")


def first_peak(profile, start):
    """First local maximum of a profile at or after lag start, and its value; (NaN, NaN) if none."""
    for i in range(max(start, 1), len(profile) - 1):
        if profile[i] >= profile[i - 1] and profile[i] > profile[i + 1]:
            return i, float(profile[i])
    return float("nan"), float("nan")


def stroke_widths(mask, min_px=20, known=None):
    """Stroke width per skeleton pixel: twice the distance to background (in pixels).

    Medial-axis approximation: local maxima of the distance transform in a 3x3 window,
    inside components of at least min_px pixels.
    """
    if known is not None:
        mask = np.asarray(mask, bool) & np.asarray(known, bool)
    lab, n = ndi.label(mask)
    if n == 0:
        return np.array([])
    sizes = ndi.sum(mask, lab, index=np.arange(1, n + 1))
    keep = np.isin(lab, np.nonzero(sizes >= min_px)[0] + 1)
    dt = ndi.distance_transform_edt(keep)
    ridge = keep & (dt >= ndi.maximum_filter(dt, size=3)) & (dt > 0)
    if known is not None:
        # Exclude widths and nearby ridge decisions determined by an unknown edge.
        unknown_distance = ndi.distance_transform_edt(np.pad(np.asarray(known, bool), 1))[1:-1, 1:-1]
        ridge &= known_feature_support(known, extra=1) & (unknown_distance > dt + 2)
    return 2.0 * dt[ridge]


def otsu(values, bins=256):
    """Otsu threshold of a 1D sample."""
    h, e = np.histogram(values, bins=bins)
    c = (e[:-1] + e[1:]) / 2
    w0 = np.cumsum(h)
    w1 = w0[-1] - w0
    s0 = np.cumsum(h * c)
    m0 = s0 / np.maximum(w0, 1)
    m1 = (s0[-1] - s0) / np.maximum(w1, 1)
    return float(c[np.argmax(w0 * w1 * (m0 - m1) ** 2)])


def block_shift_null(x, y, mask, shifts):
    """Pearson r of x and y inside mask, and r after cyclic 2D shifts of y (spatial null)."""
    def r(a, b, m):
        if int(m.sum()) < 3 or np.std(a[m]) == 0 or np.std(b[m]) == 0:
            return float("nan")
        return float(np.corrcoef(a[m], b[m])[0, 1])
    real = r(x, y, mask)
    null = []
    for dy, dx in shifts:
        ys = np.roll(y, (dy, dx), axis=(0, 1))
        ms = mask & np.roll(mask, (dy, dx), axis=(0, 1))
        null.append(r(x, ys, ms))
    return real, np.array(null)


def finite_json(value):
    """Encode unavailable statistics as JSON null, never NaN or infinity."""
    if isinstance(value, dict):
        return {k: finite_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_json(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    return value
