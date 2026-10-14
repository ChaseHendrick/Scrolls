"""Read part of a zarr volume, local or remote, as a numpy array, and sample it anywhere.

For checks that need voxels rather than chunk presence, such as the image check of cross-scan landmarks
(kit/vc3d_landmarks.py). Stores, headers and decoding come from kit/vc3d_audit.py, so remote reads are
anonymous and paced, and a 404 counts as a missing chunk only when S3 says NoSuchKey. A missing chunk reads
as the array's fill value and is counted; a chunk that could not be fetched raises, so a failed request never
passes as blank data. Pyramid levels are related by their scale transforms with voxel centres aligned: level-0
coordinate p is (p + 0.5) * f - 0.5 at a level f times as fine (f = 0.5 for a level binned 2x). Arrays are
(z, y, x); points are given as (x, y, z) where the docstring says so. Needs numpy.
"""

import collections
import concurrent.futures
import itertools
import threading

import numpy as np

from . import vc3d_audit


class RegionError(ValueError):
    pass


def _dtype(meta):
    if meta["zarr_format"] == 2:
        return np.dtype(meta["dtype"])
    big = any(c.get("name") == "bytes" and (c.get("configuration") or {}).get("endian") == "big"
              for c in meta.get("codecs") or [])
    return np.dtype(meta["dtype"]).newbyteorder(">" if big else "<")


class Volume:
    """One OME-Zarr volume (or bare array) for reading boxes and sampling points; decoded chunks are kept in a
    small cache. `voxel_um` is level 0's voxel size, when known."""

    def __init__(self, location=None, voxel_um=None, store=None, cache_chunks=192, workers=8, **store_kw):
        if store is None and location is None:
            raise RegionError("a volume needs a location or a store")
        self.store = store or vc3d_audit.open_store(str(location), **store_kw)
        self.levels, _ = vc3d_audit.levels(self.store)
        if any(lv["meta"] is None for lv in self.levels):
            raise RegionError(f"{self.store}: a pyramid level has no header")
        base = self.levels[0]
        self.factors = [vc3d_audit.factors(self.levels, lv, base) for lv in self.levels]
        self.voxel_um = voxel_um
        self.workers = max(1, workers)
        self.missing = 0
        self.chunks_read = 0
        self._cache = collections.OrderedDict()
        self._cache_n = cache_chunks
        self._lock = threading.Lock()

    def __str__(self):
        return str(self.store)

    def shape(self, level=0):
        return list(self.levels[level]["meta"]["shape"])

    def level_um(self, level):
        """Voxel size of a level along x, when level 0's is known."""
        return self.voxel_um / self.factors[level][-1] if self.voxel_um else None

    def coarsest_within(self, um):
        """The coarsest level whose voxels are at most `um` (level 0 when none is)."""
        best = 0
        for k in range(len(self.levels)):
            if self.level_um(k) is not None and self.level_um(k) <= um * (1 + 1e-9):
                best = k
        return best

    def finest_reaching(self, um):
        """The finest level whose voxels are at least `um` (the coarsest level when none is)."""
        for k in range(len(self.levels)):
            if self.level_um(k) is not None and self.level_um(k) >= um * (1 - 1e-9):
                return k
        return len(self.levels) - 1

    def to_level(self, level, xyz):
        """Level-0 (x, y, z) coordinates, an array (N, 3), in a level's voxels (x, y, z)."""
        f = np.array(self.factors[level][::-1], dtype=float)
        return (np.asarray(xyz, dtype=float) + 0.5) * f - 0.5

    def from_level(self, level, xyz):
        f = np.array(self.factors[level][::-1], dtype=float)
        return (np.asarray(xyz, dtype=float) + 0.5) / f - 0.5

    def _chunk(self, level, idx):
        key = (level, idx)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        meta = self.levels[level]["meta"]
        if meta["inner"] is not None:
            raise RegionError(f"{self.store} level {level}: sharded arrays are not read here")
        if meta.get("filters"):
            raise RegionError(f"{self.store} level {level}: zarr filters {meta['filters']} are not decoded here")
        try:
            raw = self.store.read(vc3d_audit.chunk_key(meta, idx))
        except vc3d_audit.AuditError as exc:
            raise RegionError(str(exc)) from exc
        if raw is None:
            arr = None
        else:
            try:
                data = (vc3d_audit._decompress(meta["compressor"], raw) if meta["zarr_format"] == 2
                        else vc3d_audit._v3_bytes_codecs(meta["codecs"], raw))
            except Exception as exc:  # noqa: BLE001 - any codec failure is a read failure here
                raise RegionError(f"{self.store} level {level} chunk {idx}: does not decode ({exc})") from exc
            arr = np.frombuffer(data, dtype=_dtype(meta))
            if arr.size != int(np.prod(meta["chunks"])):
                raise RegionError(f"{self.store} level {level} chunk {idx}: {arr.size} values, expected "
                                  f"{int(np.prod(meta['chunks']))}")
            arr = arr.reshape(meta["chunks"], order=meta.get("order") or "C")
        with self._lock:
            self.chunks_read += 1
            self.missing += arr is None
            self._cache[key] = arr
            while len(self._cache) > self._cache_n:
                self._cache.popitem(last=False)
        return arr

    def read(self, level, box):
        """The box [[z0, z1], [y0, y1], [x0, x1]] of a level (integers; parts outside the array read as fill)."""
        meta = self.levels[level]["meta"]
        box = [[int(a), int(b)] for a, b in box]
        size = [max(0, b - a) for a, b in box]
        fill = meta.get("fill_value")
        out = np.full(size, fill if isinstance(fill, (int, float)) and fill == fill else 0, dtype=_dtype(meta))
        ch, shape = meta["chunks"], meta["shape"]
        ranges = [range(max(0, a) // c, (min(b, s) - 1) // c + 1) if min(b, s) > max(0, a) else range(0)
                  for (a, b), c, s in zip(box, ch, shape)]
        idxs = list(itertools.product(*ranges))
        if not idxs:
            return out
        with concurrent.futures.ThreadPoolExecutor(min(self.workers, len(idxs))) as pool:
            got = list(pool.map(lambda i: (i, self._chunk(level, i)), idxs))
        for idx, arr in got:
            if arr is None:
                continue
            src, dst = [], []
            for i, c, (a, b) in zip(idx, ch, box):
                lo, hi = max(a, i * c), min(b, (i + 1) * c)
                src.append(slice(lo - i * c, hi - i * c))
                dst.append(slice(lo - a, hi - a))
            out[tuple(dst)] = arr[tuple(src)]
        return out

    def sample(self, level, xyz, pad=1):
        """Trilinear values at points (N, 3) given as (x, y, z) in a level's voxels; points outside the array
        read the fill value at their neighbours."""
        pts = np.asarray(xyz, dtype=float).reshape(-1, 3)
        zyx = pts[:, ::-1]
        lo = np.floor(zyx.min(axis=0)).astype(int) - pad
        hi = np.floor(zyx.max(axis=0)).astype(int) + 1 + pad
        block = self.read(level, list(zip(lo, hi + 1))).astype(np.float64)
        local = zyx - lo
        i0 = np.floor(local).astype(int)
        f = local - i0
        out = np.zeros(len(pts))
        for dz, dy, dx in itertools.product((0, 1), repeat=3):
            w = ((f[:, 0] if dz else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1]) *
                 (f[:, 2] if dx else 1 - f[:, 2]))
            iz = np.clip(i0[:, 0] + dz, 0, block.shape[0] - 1)
            iy = np.clip(i0[:, 1] + dy, 0, block.shape[1] - 1)
            ix = np.clip(i0[:, 2] + dx, 0, block.shape[2] - 1)
            out += w * block[iz, iy, ix]
        return out


# ---------------------------------------------------------------- matching

def _window_sums(a, p):
    """Sums of `a` over every p x p x p window that fits inside it, by an integral volume."""
    c = np.zeros(tuple(s + 1 for s in a.shape))
    c[1:, 1:, 1:] = a.cumsum(0).cumsum(1).cumsum(2)
    n0, n1, n2 = (s - p + 1 for s in a.shape)
    return (c[p:p + n0, p:p + n1, p:p + n2] - c[:n0, p:p + n1, p:p + n2] - c[p:p + n0, :n1, p:p + n2]
            - c[p:p + n0, p:p + n1, :n2] + c[:n0, :n1, p:p + n2] + c[:n0, p:p + n1, :n2]
            + c[p:p + n0, :n1, :n2] - c[:n0, :n1, :n2])


def ncc_map(template, image):
    """Normalized cross-correlation of a cube template with every same-sized window of a larger cube image, by
    FFT: an array of (image side - template side + 1) per axis, index d for the window starting at d. Windows
    with no variance score 0. None when the template has no variance."""
    t = np.asarray(template, dtype=np.float64)
    im = np.asarray(image, dtype=np.float64)
    p = t.shape[0]
    if t.shape != (p, p, p) or any(s < p for s in im.shape):
        raise RegionError(f"template {t.shape} must be a cube no larger than the image {im.shape}")
    t0 = t - t.mean()
    tn = float(np.sqrt((t0 * t0).sum()))
    if tn <= 1e-9 * max(1.0, float(np.abs(t).max())):
        return None
    n = im.shape
    corr = np.fft.irfftn(np.fft.rfftn(im, n) * np.conj(np.fft.rfftn(t0, n)), n)
    corr = corr[:n[0] - p + 1, :n[1] - p + 1, :n[2] - p + 1]
    s1, s2 = _window_sums(im, p), _window_sums(im * im, p)
    var = np.maximum(s2 - s1 * s1 / p ** 3, 0.0)
    scale = float(var.max()) if var.size else 0.0
    out = np.zeros_like(corr)
    ok = var > 1e-9 * max(scale, 1e-12)
    out[ok] = corr[ok] / (tn * np.sqrt(var[ok]))
    return out


def peak(ncc, exclude=4.0):
    """(peak value, peak position, best value farther than `exclude` voxels from the peak) of an NCC map. The
    position is refined below a voxel by a parabola through the peak and its neighbours on each axis."""
    k = np.unravel_index(int(np.argmax(ncc)), ncc.shape)
    grid = np.indices(ncc.shape).reshape(3, -1).T
    far = np.sqrt(((grid - np.array(k)) ** 2).sum(axis=1)) > exclude
    side = float(ncc.reshape(-1)[far].max()) if far.any() else float("-inf")
    pos = []
    for axis, i in enumerate(k):
        if 0 < i < ncc.shape[axis] - 1:
            lo, hi = list(k), list(k)
            lo[axis], hi[axis] = i - 1, i + 1
            a, b, c = float(ncc[tuple(lo)]), float(ncc[k]), float(ncc[tuple(hi)])
            den = a - 2 * b + c
            pos.append(i + (max(-0.5, min(0.5, 0.5 * (a - c) / den)) if den < 0 else 0.0))
        else:
            pos.append(float(i))
    return float(ncc[k]), tuple(pos), side
