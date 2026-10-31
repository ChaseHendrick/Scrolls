"""Paired acquisition-recipe fidelity: in the same 128-voxel regions, does a finer acquisition binned to the coarse
grid keep more of the sheet pattern an independent finer reference shows than the native coarse acquisition does?
(`kit/sqrecipe.py`; command line: scripts/sqrecipe/sqrecipe.py.)

The outcome is kit.sqfid's fidelity: band-passed NCC of an arm's cube against the reference cube at the best integer
shift, under RULE below. This module adds what the paired design needs:

  Store, ZArray      a zarr v2 array, local folder or HTTPS prefix, read chunk by chunk into memory only
  ParallelZArray     a ZArray whose chunks under a block are fetched in parallel, with a small LRU cache
  lattice_range      the source-level box kit.sqfid.fine_on_coarse reads for a region (same arithmetic)
  round_trip         the processing control: the native cube sent through a finer arm's resampling chain
  hf_noise, degrade_to   the degradation control: blur and noise matched to the native arm's noise level
  paired             share of d > 0 and median d with cluster-bootstrap intervals, and the primary bar
  signflip           cluster sign-flip permutation of d: the share of draws that pass the primary bar
  border_share, rho_ci   the border-shift check and a Spearman rho with its cluster-bootstrap interval

Every number is a Measurement of the CT, never a reading.
"""

import collections
import concurrent.futures
import copy
import json
import math
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import sqfid

# The outcome rule of the PHerc0332 test: kit.sqfid's measure with a wider shift search (+-10), a higher sheet band
# (sigmas 0.7 and 2.0 grid voxels) and the reference read at its level 1 (set in the script).
RULE = copy.deepcopy(sqfid.RULE)
RULE.update({"max_shift": 10, "inner": 10, "band_sigmas": [0.7, 2.0]})
BOOT = {"bootstrap": {"resamples": 2000, "seed": 0, "level": 0.95}}
DEGRADE_SIGMA = 1.0                        # grid voxels
HF_SIGMA = 1.0                             # the noise statistic: sd of x - Gaussian(x, HF_SIGMA) inside the mask
WHITE_SEED = 5
SIGNFLIP = {"draws": 200, "seed": 1, "resamples": 1000, "max_pass_share": 0.10}
BORDER_MAX = 0.10


def _np():
    return sqfid._np()


def _nd():
    return sqfid._nd()


class RecipeError(RuntimeError):
    pass


# ---------------------------------------------------------------- reading

class Store:
    """A zarr store, local folder or HTTPS prefix, read in memory only. Counts requests and bytes; `opener(url)` may
    be replaced (tests use a dict). A key that is not there (404 or 403, or no file) reads as None."""

    def __init__(self, root, opener=None, tries=4):
        self.root = str(root).rstrip("/")
        self.remote = self.root.startswith("http://") or self.root.startswith("https://")
        self.opener = opener
        self.tries = tries
        self.requests = self.bytes = self.missing = 0
        self._lock = threading.Lock()

    def _count(self, nbytes=0, missing=False, request=False):
        with self._lock:
            self.requests += int(request)
            self.bytes += nbytes
            self.missing += int(missing)

    def get(self, key):
        self._count(request=True)
        if not self.remote:
            p = Path(self.root) / key
            if not p.is_file():
                self._count(missing=True)
                return None
            b = p.read_bytes()
            self._count(nbytes=len(b))
            return b
        url = f"{self.root}/{key}"
        for k in range(self.tries):
            try:
                if self.opener is not None:
                    b = self.opener(url)
                else:
                    with urllib.request.urlopen(url, timeout=120) as r:
                        b = r.read()
                if b is None:
                    self._count(missing=True)
                    return None
                self._count(nbytes=len(b))
                return b
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 404):
                    self._count(missing=True)
                    return None
                if k == self.tries - 1:
                    raise
            except (urllib.error.URLError, OSError, ConnectionError):
                if k == self.tries - 1:
                    raise
            time.sleep(2 * (k + 1))
        return None


def _decode(meta, raw):
    np = _np()
    comp = meta.get("compressor")
    if comp:
        from . import vc3d_audit
        raw = vc3d_audit._decompress(comp, raw)
    a = np.frombuffer(raw, dtype=np.dtype(meta["dtype"]))
    return a.reshape(meta["chunks"], order=meta.get("order", "C"))


class ZArray:
    """One zarr v2 array (a level of an OME-Zarr) read chunk by chunk from a Store."""

    def __init__(self, store, path=""):
        self.store, self.path = store, path.strip("/")
        raw = store.get(self._key(".zarray"))
        if raw is None:
            raise RecipeError(f"no .zarray at {store.root}/{self.path}")
        self.meta = json.loads(raw)
        self.shape = tuple(int(v) for v in self.meta["shape"])
        self.chunks = tuple(int(v) for v in self.meta["chunks"])
        self.sep = self.meta.get("dimension_separator", ".")
        self.fill = self.meta.get("fill_value") or 0

    def _key(self, name):
        return f"{self.path}/{name}" if self.path else name

    def chunk(self, idx):
        raw = self.store.get(self._key(self.sep.join(str(int(i)) for i in idx)))
        return None if raw is None else _decode(self.meta, raw)

    def _chunks_under(self, o, s):
        np = _np()
        C = np.array(self.chunks, dtype=np.int64)
        lo, hi = np.maximum(o, 0) // C, (np.minimum(o + s, self.shape) - 1) // C
        return C, [(cz, cy, cx) for cz in range(int(lo[0]), int(hi[0]) + 1)
                   for cy in range(int(lo[1]), int(hi[1]) + 1) for cx in range(int(lo[2]), int(hi[2]) + 1)]

    def _fetch(self, idxs):
        return [self.chunk(i) for i in idxs]

    def block(self, origin, size):
        """The cube [origin, origin + size) (fill outside the array and in missing chunks) and the number of
        missing chunks under it."""
        np = _np()
        o = np.asarray(origin, dtype=np.int64)
        s = np.asarray(size if hasattr(size, "__len__") else (size,) * 3, dtype=np.int64)
        out = np.full(tuple(s), self.fill, dtype=np.dtype(self.meta["dtype"]))
        C, idxs = self._chunks_under(o, s)
        missing = 0
        for (cz, cy, cx), arr in zip(idxs, self._fetch(idxs)):
            if arr is None:
                missing += 1
                continue
            c0 = np.array([cz, cy, cx], dtype=np.int64) * C
            a, b = np.maximum(o, c0), np.minimum(np.minimum(o + s, c0 + C), self.shape)
            if (b <= a).any():
                continue
            out[a[0] - o[0]:b[0] - o[0], a[1] - o[1]:b[1] - o[1], a[2] - o[2]:b[2] - o[2]] = \
                arr[a[0] - c0[0]:b[0] - c0[0], a[1] - c0[1]:b[1] - c0[1], a[2] - c0[2]:b[2] - c0[2]]
        return out, missing


class ParallelZArray(ZArray):
    """ZArray whose block() fetches the chunks under it with `threads` parallel requests and keeps the last `cache`
    chunks (LRU). Same output as ZArray.block."""

    def __init__(self, store, path="", threads=8, cache=96):
        super().__init__(store, path)
        self.threads = int(threads)
        self.cache = int(cache)
        self._lru = collections.OrderedDict()
        self._lock = threading.Lock()

    def _get(self, idx):
        with self._lock:
            if idx in self._lru:
                self._lru.move_to_end(idx)
                return self._lru[idx]
        arr = self.chunk(idx)
        with self._lock:
            self._lru[idx] = arr
            while len(self._lru) > self.cache:
                self._lru.popitem(last=False)
        return arr

    def _fetch(self, idxs):
        if self.threads > 1 and len(idxs) > 1:
            with concurrent.futures.ThreadPoolExecutor(min(self.threads, len(idxs))) as ex:
                return list(ex.map(self._get, idxs))
        return [self._get(i) for i in idxs]


# ---------------------------------------------------------------- geometry

def compose(*Ms):
    """3 x 4 matrices applied right to left: compose(B, A) maps p to B(A(p))."""
    np = _np()
    T = np.eye(4)
    for M in Ms:
        T = T @ np.vstack([np.asarray(M, float), [0.0, 0.0, 0.0, 1.0]])
    return T[:3]


def invert(M):
    """The inverse of a 3 x 4 affine matrix, as 3 x 4."""
    np = _np()
    return np.linalg.inv(np.vstack([np.asarray(M, float), [0.0, 0.0, 0.0, 1.0]]))[:3]


def _grid_xyz(origin, R):
    np = _np()
    o = np.asarray(origin, dtype=np.int64)
    zz, yy, xx = np.meshgrid(*[np.arange(R) + o[i] for i in range(3)], indexing="ij")
    return np.stack([xx.ravel(), yy.ravel(), zz.ravel()], 1).astype(float)


def _level_zyx(vxyz, level):
    f = 2.0 ** level
    return (vxyz[:, 2] + 0.5) / f - 0.5, (vxyz[:, 1] + 0.5) / f - 0.5, (vxyz[:, 0] + 0.5) / f - 0.5


def lattice_range(M, level, origin, R=128):
    """(lo, hi) zyx of the source-level block kit.sqfid.fine_on_coarse reads for the region (same arithmetic)."""
    np = _np()
    v = _grid_xyz(origin, R) @ np.asarray(M)[:, :3].T + np.asarray(M)[:, 3]
    vz, vy, vx = _level_zyx(v, level)
    lo = np.floor([vz.min(), vy.min(), vx.min()]).astype(np.int64) - 1
    hi = np.ceil([vz.max(), vy.max(), vx.max()]).astype(np.int64) + 2
    return lo, hi


def mapped_corners(M, origin, R):
    """The region's eight corners mapped by M, as level-0 zyx of the target volume (8 x 3)."""
    np = _np()
    o = np.asarray(origin, float)
    pts = np.array([(o[2] + dx, o[1] + dy, o[0] + dz) for dz in (0, R) for dy in (0, R) for dx in (0, R)], float)
    v = pts @ np.asarray(M)[:, :3].T + np.asarray(M)[:, 3]
    return v[:, ::-1]


def corners_inside(M, origin, R, shape0_zyx, margin=2):
    """Every corner of the region maps inside the level-0 extent (zyx) of the volume M points into."""
    np = _np()
    zyx = mapped_corners(M, origin, R)
    return bool((zyx >= margin).all() and (zyx <= np.array(shape0_zyx, float) - 1 - margin).all())


def touches(M, origin, R, box):
    """Whether the bounding box of the region's mapped corners overlaps `box` ({'z': [lo, hi], 'y': ..., 'x': ...},
    level-0 voxels of the volume M points into, hi exclusive; an axis left out spans everything)."""
    zyx = mapped_corners(M, origin, R)
    for ax, k in enumerate("zyx"):
        if k not in box:
            continue
        lo, hi = float(box[k][0]), float(box[k][1])
        if zyx[:, ax].max() < lo or zyx[:, ax].min() >= hi:
            return False
    return True


class _Held:
    """An in-memory block standing in for a zarr level: block(lo, size) must ask for exactly the held box."""

    def __init__(self, data, lo):
        self.data, self.lo = data, tuple(int(i) for i in lo)

    def block(self, lo, size):
        if tuple(int(i) for i in lo) != self.lo or tuple(int(i) for i in size) != self.data.shape:
            raise RecipeError("round_trip: fine_on_coarse asked for another box than the lattice held")
        return self.data, 0


def sample_coarse(arr, pts_zyx, pad=3):
    """Trilinear samples of a coarse level-0 array at zyx points (float), 0 where the nearest voxel is outside the
    mask (0), else rounded and clipped to 1..255, like fine_on_coarse."""
    np = _np()
    nd = _nd()
    lo = np.floor(pts_zyx.min(1)).astype(np.int64) - pad
    hi = np.ceil(pts_zyx.max(1)).astype(np.int64) + pad + 1
    block, _ = arr.block(lo, hi - lo)
    q = pts_zyx - lo[:, None]
    vals = nd.map_coordinates(block.astype(np.float32), q, order=1, mode="constant", cval=0.0)
    near = nd.map_coordinates(block, q, order=0, mode="constant", cval=0)
    return np.where(near > 0, np.clip(np.rint(vals), 1, 255), 0).astype(np.uint8)


def round_trip(native, M, level, origin, R=128):
    """The processing control N': the native coarse volume resampled onto the finer arm's source lattice (level
    `level` of the volume M maps coarse xyz into), then onto the coarse grid by kit.sqfid.fine_on_coarse exactly as
    that arm is. `native` has block(origin, size) in coarse level-0 voxels."""
    np = _np()
    lo, hi = lattice_range(M, level, origin, R)
    shp = tuple(int(i) for i in (hi - lo))
    gz, gy, gx = np.meshgrid(*[np.arange(shp[i]) + lo[i] for i in range(3)], indexing="ij")
    f = 2.0 ** level
    fxyz = np.stack([(gx.ravel() + 0.5) * f - 0.5, (gy.ravel() + 0.5) * f - 0.5, (gz.ravel() + 0.5) * f - 0.5], 1)
    Minv = invert(M)
    cxyz = fxyz @ Minv[:, :3].T + Minv[:, 3]
    lat = sample_coarse(native, np.stack([cxyz[:, 2], cxyz[:, 1], cxyz[:, 0]])).reshape(shp)
    return sqfid.fine_on_coarse(_Held(lat, lo), level, M, origin, R)


# ---------------------------------------------------------------- degradation

def hf_noise(x, sigma=HF_SIGMA):
    """Standard deviation, inside the mask (x > 0), of x - Gaussian(x, sigma) (outside voxels take the inside mean
    first)."""
    np = _np()
    nd = _nd()
    a = np.asarray(x, dtype=np.float32)
    on = a > 0
    if not on.any():
        return float("nan")
    a = np.where(on, a, a[on].mean()).astype(np.float32)
    r = a - nd.gaussian_filter(a, sigma)
    return float(r[on].std())


_WHITE = {}


def white_c(sigma=HF_SIGMA, n=64, seed=WHITE_SEED):
    """hf_noise of unit white noise (computed once per sigma)."""
    np = _np()
    nd = _nd()
    if sigma not in _WHITE:
        w = np.random.default_rng(seed).standard_normal((n, n, n)).astype(np.float32)
        r = w - nd.gaussian_filter(w, sigma, mode="wrap")
        _WHITE[sigma] = float(r.std())
    return _WHITE[sigma]


def degrade_to(x, hf_target, seed, sigma=DEGRADE_SIGMA):
    """x blurred by sigma, then seeded Gaussian noise so its hf_noise is about hf_target (none when the blurred cube
    is already noisier); 0 outside the mask, uint8 1..255 inside. Returns (cube, added noise SD)."""
    np = _np()
    nd = _nd()
    a = np.asarray(x, dtype=np.float32)
    on = a > 0
    a = np.where(on, a, a[on].mean() if on.any() else 0).astype(np.float32)
    b = nd.gaussian_filter(a, sigma)
    hb = hf_noise(np.where(on, np.clip(b, 1, None), 0))
    add = math.sqrt(max(float(hf_target) ** 2 - hb ** 2, 0.0)) / white_c()
    if add > 0:
        b = b + np.random.default_rng(seed).standard_normal(b.shape).astype(np.float32) * add
    out = np.where(on, np.clip(np.rint(b), 1, 255), 0).astype(np.uint8)
    return out, add


# ---------------------------------------------------------------- readouts

def paired(d, clusters, boot=None, seed=None):
    """Share of d > 0 and median d, each with its cluster-bootstrap interval; the primary bar: share's lower bound
    above 0.5 and median's lower bound above 0."""
    np = _np()
    boot = boot or BOOT
    d = np.asarray(d, float)
    win = (d > 0).astype(float)
    b = sqfid.bootstrap({"share": lambda i: float(win[i].mean()), "median": lambda i: float(np.median(d[i]))},
                        len(d), clusters, boot, seed=seed)
    sci, mci = sqfid.interval(b["share"], boot), sqfid.interval(b["median"], boot)
    return {"n": int(len(d)), "clusters": int(len(set(clusters))), "share": float(win.mean()), "share_ci": sci,
            "median": float(np.median(d)), "median_ci": mci, "passes": bool(sci[0] > 0.5 and mci[0] > 0)}


def signflip(d, clusters, cfg=None):
    """Cluster sign-flip permutation: each draw flips d's sign in a seeded half of the clusters (each cluster
    independently, probability 1/2) and reads the primary bar with cfg['resamples'] bootstrap resamples. Returns the
    pass share and whether it is at most max_pass_share."""
    np = _np()
    cfg = cfg or SIGNFLIP
    d = np.asarray(d, float)
    labels, inv = np.unique(np.asarray(clusters), return_inverse=True)
    rng = np.random.default_rng(cfg["seed"])
    boot = {"bootstrap": {"resamples": int(cfg["resamples"]), "seed": 0, "level": 0.95}}
    passes = 0
    for k in range(int(cfg["draws"])):
        flip = rng.integers(0, 2, len(labels)) * 2 - 1
        passes += int(paired(d * flip[inv], clusters, boot, seed=k)["passes"])
    share = passes / int(cfg["draws"])
    return {"draws": int(cfg["draws"]), "passes": passes, "share": share,
            "holds": bool(share <= cfg["max_pass_share"])}


def border_share(flags):
    """Share of best shifts on the search border; holds when at most BORDER_MAX."""
    np = _np()
    f = np.asarray(flags, bool)
    share = float(f.mean()) if f.size else float("nan")
    return {"n": int(f.size), "at_border": int(f.sum()), "share": share, "holds": bool(share <= BORDER_MAX)}


def rho_ci(x, y, clusters, boot=None):
    """Spearman rho of the finite pairs with its cluster-bootstrap interval."""
    np = _np()
    boot = boot or BOOT
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    cl = [c for c, k in zip(clusters, ok) if k]
    b = sqfid.bootstrap({"rho": lambda i: sqfid.spearman(x[i], y[i])}, len(x), cl, boot)
    return {"n": int(len(x)), "rho": sqfid.spearman(x, y), "rho_ci": sqfid.interval(b["rho"], boot)}


def processing_holds(fb, fnp, clusters):
    """Processing control: B beats N' with share(F(B) > F(N')) lower bound above 0.5."""
    np = _np()
    r = paired(np.asarray(fb, float) - np.asarray(fnp, float), clusters)
    r["holds"] = bool(r["share_ci"][0] > 0.5)
    return r


def degradation_holds(fdeg, fn, d_median):
    """Degradation control: median(F(Bdeg) - F(N)) at most half of median(d); moot (holds None) when median(d) is
    not above 0."""
    np = _np()
    m = float(np.median(np.asarray(fdeg, float) - np.asarray(fn, float)))
    if not d_median > 0:
        return {"median_lead": m, "half_primary": None, "holds": None}
    return {"median_lead": m, "half_primary": 0.5 * d_median, "holds": bool(m <= 0.5 * d_median)}
