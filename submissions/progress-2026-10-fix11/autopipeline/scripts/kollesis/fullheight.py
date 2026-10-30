"""Kollesis finder: CT patches tracked along the sheet at a fiber point, over the full height around it.

A kollesis (glued sheet join) is a band about 1 to 2 cm wide that runs the full height of the roll, where two
sheets overlap. A single CT row at the tag is noisy, so this samples the followed sheet on an (arc s, height dz) grid: rows at heights z0 + dz, columns along
the fiber frame (s > 0 behind the point, on the fiber body; s < 0 beyond it, extrapolated at constant curvature),
and at each (dz, s) a short profile across the sheet (in-plane normal offset n). The sheet is re-centered row by
row (from dz = 0 outward) and column by column (from s = 0 outward), so the patch follows the sheet as it drifts.

Standard library plus numpy. All coordinates are level-0 voxels in (x, y, z) order, as in VC3D annotator files,
except the zarr reader, which takes (z, y, x) at the requested level.
"""
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

# Frozen geometry (level-0 voxels). Changing any of these changes the scorer.
STEP = 16.0          # column spacing along the frame
BEHIND = 8000.0      # columns behind the point (on the fiber body)
BEYOND = 2000.0      # columns beyond the point (extrapolated)
DZ = 128.0           # row spacing in z
NROW = 12            # rows each side of dz = 0 (25 rows, +-1536)
NHALF = 96.0         # sampled half width across the sheet
NSTEP = 2.0          # sample spacing across the sheet
LEVEL = 1            # zarr level read (4.8 um for a 2.4 um scan)
SEARCH0 = 16.0       # re-centering search at the anchor column of each row (+-)
SLOPE = 4.0          # largest center change between neighboring columns
FEAT_HALF = 30.0     # feature window across the sheet (+-)
CURV_SPAN = 2000.0   # body length used for the curvature of the extrapolation


# ---------------------------------------------------------------- CT reader (public open-data zarr, uncompressed)
class Zarr:
    """Reads single voxels of an uncompressed uint8 zarr v2 with 128^3 chunks, by HTTP range requests on z rows."""

    def __init__(self, url, workers=16, tries=5):
        self.url, self.workers, self.tries = url.rstrip('/'), workers, tries
        self.requests = 0

    def _slab(self, level, cz, cy, cx, z0, z1):
        req = urllib.request.Request(f"{self.url}/{level}/{cz}/{cy}/{cx}",
                                     headers={'Range': f'bytes={z0 * 16384}-{(z1 + 1) * 16384 - 1}'})
        for attempt in range(self.tries):
            try:
                b = urllib.request.urlopen(req, timeout=60).read()
                break
            except urllib.error.HTTPError as ex:
                if ex.code in (403, 404, 416):
                    return None        # chunk absent: outside the mask, reads as 0
                time.sleep(1 + attempt)
            except Exception:
                time.sleep(1 + attempt)
        else:
            raise IOError(f'range read failed: {level}/{cz}/{cy}/{cx}')
        self.requests += 1
        if len(b) != (z1 - z0 + 1) * 16384:
            raise IOError(f'short range read: {level}/{cz}/{cy}/{cx}')
        return np.frombuffer(b, np.uint8).reshape(z1 - z0 + 1, 128, 128)

    def __call__(self, level, zyx):
        """Nearest-neighbor values at (N, 3) level-voxel coordinates (z, y, x); 0 outside the volume."""
        q = np.round(np.asarray(zyx, float)).astype(np.int64)
        out = np.zeros(len(q), np.uint8)
        if not len(q):
            return out
        key = q // 128
        uk, inv = np.unique(key, axis=0, return_inverse=True)
        inv = inv.ravel()
        order = np.argsort(inv, kind='stable')
        bounds = np.searchsorted(inv[order], np.arange(len(uk) + 1))
        jobs = []
        for i, k in enumerate(uk):
            if (k < 0).any():
                continue
            idx = order[bounds[i]:bounds[i + 1]]
            lz = q[idx, 0] - k[0] * 128
            jobs.append((i, idx, int(lz.min()), int(lz.max())))
        with ThreadPoolExecutor(self.workers) as ex:
            res = list(ex.map(lambda j: self._slab(level, *uk[j[0]], j[2], j[3]), jobs))
        for (i, idx, z0, _), c in zip(jobs, res):
            if c is None:
                continue
            r = q[idx] - uk[i] * 128
            out[idx] = c[r[:, 0] - z0, r[:, 1], r[:, 2]]
        return out


# ---------------------------------------------------------------- frame along the fiber
def resample(lp, step):
    d = np.linalg.norm(np.diff(lp, axis=0), axis=1)
    s = np.r_[0, np.cumsum(d)]
    S = np.arange(0, s[-1] + 1e-9, step)
    return np.c_[[np.interp(S, s, lp[:, i]) for i in range(lp.shape[1])]].T, S


def smooth(a, w):
    if len(a) < 3 or w < 2:
        return a.copy()
    w = min(w, len(a) - (1 - len(a) % 2))
    w = max(1, w | 1)
    k = np.ones(w) / w
    return np.c_[[np.convolve(np.pad(a[:, i], w // 2, mode='edge'), k, 'valid') for i in range(a.shape[1])]].T


def frame(body, step=STEP, behind=BEHIND, beyond=BEYOND, curv_span=CURV_SPAN):
    """Frame columns for a query point at body[-1]; body runs along the fiber and ends at the point.

    Returns dict: s (columns, + behind), xy (N, 2), z (N,), normal (N, 2) unit in-plane normals, k0 (column of s = 0),
    nbody (number of columns that lie on the body, s >= 0). Beyond the point the frame continues at the body's mean
    in-plane curvature over the last curv_span voxels (a straight ray when the body is shorter than two columns)."""
    body = np.asarray(body, float)
    P, S = resample(body[::-1], step)          # from the point back along the body
    P = P[S <= behind]
    Ps = smooth(P, 9) if len(P) > 12 else P
    if len(Ps) >= 2:
        tg = -np.gradient(Ps[:, :2], axis=0)   # outward: toward the point and beyond
    else:
        tg = np.array([[1.0, 0.0]])
    tg = tg / (np.linalg.norm(tg, axis=1)[:, None] + 1e-9)
    # heading angle along the body near the point, for curvature
    m = int(min(len(Ps), max(2, curv_span / step)))
    th = np.unwrap(np.arctan2(tg[:m, 1], tg[:m, 0]))
    if m >= 4:
        sb = np.arange(m) * step                # distance back from the point
        kappa = -np.polyfit(sb, th, 1)[0]       # dtheta/ds going outward
        th0 = np.polyval(np.polyfit(sb, th, 1), 0.0)
    else:
        kappa, th0 = 0.0, float(th[0])
    nb = int(round(beyond / step))
    ext = np.zeros((nb, 2))
    xy, ang = Ps[0, :2].copy(), th0
    for j in range(nb):                         # j = 0 is one step beyond the point
        ang = ang + kappa * step
        xy = xy + step * np.array([np.cos(ang), np.sin(ang)])
        ext[j] = xy
    ext_t = np.c_[np.cos(th0 + kappa * step * np.arange(1, nb + 1)), np.sin(th0 + kappa * step * np.arange(1, nb + 1))]
    XY = np.r_[ext[::-1], Ps[:, :2]]
    T = np.r_[ext_t[::-1], tg]
    Z = np.r_[np.full(nb, Ps[0, 2]), Ps[:, 2]]
    nrm = np.c_[-T[:, 1], T[:, 0]]
    s = (np.arange(len(XY)) - nb) * step
    return dict(s=s, xy=XY, z=Z, normal=nrm, k0=nb, nbody=len(Ps))


# ---------------------------------------------------------------- tracking
def _gsmooth1(a, sigma, axis):
    r = int(3 * sigma) + 1
    x = np.arange(-r, r + 1)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    k /= k.sum()
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    ap = np.pad(a, pad, mode='edge')
    return np.apply_along_axis(lambda v: np.convolve(v, k, 'valid'), axis, ap)


def track_row(img, k0, c_anchor, nstep=NSTEP, search0=SEARCH0, slope=SLOPE):
    """img: (ncol, nn) samples across the sheet, column offsets centered on the prior. Returns the center index per
    column (float, in samples), following the brightest ridge from column k0 outward both ways."""
    sm = _gsmooth1(_gsmooth1(img.astype(np.float32), 1.5, 1), 2.0, 0)
    ncol, nn = sm.shape
    c = np.zeros(ncol)
    r0 = int(round(search0 / nstep))
    a = int(round(c_anchor))
    lo, hi = max(0, a - r0), min(nn, a + r0 + 1)
    c[k0] = lo + int(np.argmax(sm[k0, lo:hi]))
    rs = max(1, int(round(slope / nstep)))
    for rng in (range(k0 + 1, ncol), range(k0 - 1, -1, -1)):
        prev = None
        for k in rng:
            p = int(c[k - 1] if k > k0 else c[k + 1])
            lo, hi = max(0, p - rs), min(nn, p + rs + 1)
            c[k] = lo + int(np.argmax(sm[k, lo:hi]))
    return c


def extract(fr, reader, level=LEVEL, nrow=NROW, dz=DZ, nhalf=NHALF, nstep=NSTEP):
    """Tracked patch for one frame. Returns raw (2 nrow + 1, ncol, nn) uint8 samples, centers (same rows, ncol) as
    offsets in voxels from the dz = 0 frame line, and the row heights dz."""
    off = np.arange(-nhalf, nhalf + 1e-6, nstep)
    nn, ncol = len(off), len(fr['s'])
    rows = np.arange(-nrow, nrow + 1) * dz
    raw = np.zeros((len(rows), ncol, nn), np.uint8)
    cen = np.zeros((len(rows), ncol))
    sc = 2.0 ** level
    mid = nrow

    def sample(prior, dzv):
        xy = fr['xy'][:, None] + (prior[:, None] + off[None]) [..., None] * fr['normal'][:, None]
        z = np.broadcast_to((fr['z'] + dzv)[:, None], xy.shape[:2])
        zyx = np.stack([z, xy[..., 1], xy[..., 0]], -1).reshape(-1, 3) / sc
        return reader(level, zyx).reshape(ncol, nn)

    prior = np.zeros(ncol)
    img = sample(prior, 0.0)
    ci = track_row(img, fr['k0'], (nn - 1) / 2, nstep)
    raw[mid], cen[mid] = img, prior + (ci - (nn - 1) / 2) * nstep
    for direction in (1, -1):
        prev = cen[mid].copy()
        for j in range(1, nrow + 1):
            r = mid + direction * j
            img = sample(prev, rows[r])
            ci = track_row(img, fr['k0'], (nn - 1) / 2, nstep)
            cen[r] = prev + (ci - (nn - 1) / 2) * nstep
            raw[r] = img
            prev = cen[r]
    return raw, cen, rows


# ---------------------------------------------------------------- features
def features(raw, cen, nhalf=NHALF, nstep=NSTEP, feat_half=FEAT_HALF):
    """Per (row, column) features of the profile across the tracked sheet, with thresholds from the patch itself
    (so scans with different gray levels compare). Returns dict of float32 arrays (rows, cols) and 'valid' (bool).

    The stored raw rows are centered on the prior track, and cen holds the found center; this re-indexes each
    profile around the found center before measuring."""
    R, C, N = raw.shape
    off = np.arange(-nhalf, nhalf + 1e-6, nstep)
    # prior of each row = found center of the previous row toward dz = 0 (the mid row's prior is 0)
    mid = R // 2
    prior = np.zeros((R, C))
    prior[mid + 1:] = cen[mid:-1]
    prior[:mid] = cen[1:mid + 1]
    ci = (cen - prior) / nstep + (N - 1) / 2          # center index in each stored profile
    fh = int(round(feat_half / nstep))
    a = raw.astype(np.float32)
    sm = _gsmooth1(a, 1.0, 2)
    nz = a[a > 0]
    T = float(np.percentile(nz, 50)) if len(nz) else 1.0
    H = float(np.percentile(nz, 99)) if len(nz) else 255.0
    idx = np.clip(np.round(ci).astype(int)[..., None] + np.arange(-fh, fh + 1)[None, None], 0, N - 1)
    win = np.take_along_axis(sm, idx, 2)               # (R, C, 2 fh + 1), smoothed, centered on the sheet
    wraw = np.take_along_axis(a, idx, 2)
    inside = (np.round(ci)[..., None] + np.arange(-fh, fh + 1)[None, None] >= 0) & \
             (np.round(ci)[..., None] + np.arange(-fh, fh + 1)[None, None] <= N - 1)
    valid = ((wraw > 0) & inside).mean(2) > 0.9
    c4 = int(round(4 / nstep))
    ridge = win[..., fh - c4:fh + c4 + 1].max(2)
    thick = (win > T).sum(2) * nstep
    pk = (win[..., 1:-1] > win[..., :-2]) & (win[..., 1:-1] >= win[..., 2:]) & (win[..., 1:-1] > T)
    peaks = pk.sum(2).astype(np.float32)
    b20 = int(round(20 / nstep))
    bright = (wraw[..., fh - b20:fh + b20 + 1] > H).mean(2)
    mass = np.clip(win - T, 0, None).sum(2) * nstep    # integrated density above the sheet level
    return dict(ridge=ridge.astype(np.float32), thick=thick.astype(np.float32), peaks=peaks,
                bright=bright.astype(np.float32), mass=mass.astype(np.float32),
                center=cen.astype(np.float32), valid=valid, T=np.float32(T), H=np.float32(H))
