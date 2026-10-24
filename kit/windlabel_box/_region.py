"""Read part of a zarr volume, local or remote, as a numpy array, and sample it anywhere.

For checks that need voxels rather than chunk presence, such as the image check of cross-scan landmarks.
Stores, headers and decoding come from kit/vc3d_audit.py, so remote reads are anonymous
(not paced unless `rate` is given: the audit's 20 requests per second made a 64-chunk box of PHerc0139's surface
prediction 1.76 times slower on a direct connection), and a 404 counts as a missing chunk only when S3 says
NoSuchKey. A missing chunk reads as the array's fill value and is counted; a chunk that could not be fetched raises,
so a failed request never passes as blank data. Pyramid levels are related by their scale transforms with voxel
centers aligned: level-0 coordinate p is (p + 0.5) * f - 0.5 at a level f times as fine (f = 0.5 for a level binned
2x). Arrays are (z, y, x); points are given as (x, y, z) where the docstring says so. Needs numpy.

Sharded zarr v3 arrays are read inner chunk by inner chunk through each shard's index (its CRC32C checked when the
index has one). Over HTTP the inner chunks a box needs from one shard are fetched in merged range reads: neighbors
in the shard's bytes are joined while the gap between them is at most MERGE_GAP and the whole read at most
MERGE_SPAN, so a box costs far fewer requests than chunks. The bounds are those SuperOptimizer/ufsm reports for its
grouped reads (64 KiB gaps, 2 MiB spans; DESIGN.md at commit 75e063b, 14 October 2026); ufsm has no license for its
own code, so this is our own implementation and nothing is copied. `coalesce=False` reads one range per inner chunk,
the control. A short or failed range read raises; an absent inner chunk reads as fill.

"""

import collections
import concurrent.futures
import itertools
import re
import struct
import threading
import numpy as np
from .. import vc3d_audit


MERGE_GAP = 64 << 10    # bytes between two inner chunks a merged range read may span


MERGE_SPAN = 2 << 20    # the longest merged range read, in bytes


class RegionError(ValueError):
    pass


def _crc32c_table():
    out = []
    for n in range(256):
        c = n
        for _ in range(8):
            c = (c >> 1) ^ 0x82F63B78 if c & 1 else c >> 1
        out.append(c)
    return out


_CRC32C = _crc32c_table()


def crc32c(data):
    """CRC-32C (Castagnoli), as zarr v3's crc32c codec writes it."""
    c = 0xFFFFFFFF
    t = _CRC32C
    for b in data:
        c = t[(c ^ b) & 0xFF] ^ (c >> 8)
    return c ^ 0xFFFFFFFF


def merge_ranges(items, gap=MERGE_GAP, span=MERGE_SPAN):
    """Group (offset, nbytes, tag) items of one shard into range reads: [(start, nbytes, [(offset, nbytes, tag)])],
    joining neighbors in offset order while the gap is at most `gap` and the read at most `span`. An item longer
    than `span` is read alone; gap < 0 joins nothing."""
    groups = []
    for off, n, tag in sorted(items, key=lambda it: it[0]):
        if groups and gap >= 0:
            start, length, members = groups[-1]
            end = start + length
            if end <= off and off - end <= gap and off + n - start <= span:
                groups[-1] = (start, off + n - start, members + [(off, n, tag)])
                continue
        groups.append((off, n, [(off, n, tag)]))
    return groups


def _dtype(meta):
    if meta["zarr_format"] == 2:
        return np.dtype(meta["dtype"])
    big = any(c.get("name") == "bytes" and (c.get("configuration") or {}).get("endian") == "big"
              for c in meta.get("codecs") or [])
    return np.dtype(meta["dtype"]).newbyteorder(">" if big else "<")


def _permutes(codecs):
    """Whether a zarr v3 codec list holds a transpose codec that changes the axis order (read in C order, its chunks
    would come back with their axes swapped)."""
    for c in codecs or []:
        if c.get("name") == "transpose":
            order = (c.get("configuration") or {}).get("order")
            if order != "C" and not (isinstance(order, list) and order == list(range(len(order)))):
                return True
    return False


def _inner_dtype(meta):
    """The data type of a sharded array's inner chunks (their own bytes codec gives the byte order)."""
    big = any(c.get("name") == "bytes" and (c.get("configuration") or {}).get("endian") == "big"
              for c in meta.get("inner_codecs") or [])
    return np.dtype(meta["dtype"]).newbyteorder(">" if big else "<")


class Volume:
    """One OME-Zarr volume (or bare array) for reading boxes and sampling points; decoded chunks are kept in a
    small cache. `voxel_um` is level 0's voxel size, when known."""

    def __init__(self, location=None, voxel_um=None, store=None, cache_chunks=192, workers=8, coalesce=True,
                 **store_kw):
        if store is None and location is None:
            raise RegionError("a volume needs a location or a store")
        if store is None and re.match(r"^(https?|s3)://", str(location), re.I):
            store_kw.setdefault("rate", 0)          # no pace for box reads (the audit's 20 per second: 1.76x slower)
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
        self.coalesce = coalesce
        self.range_reads = 0                        # sharded arrays: range reads of inner chunks (merged or not)
        self._index = {}                            # (level, shard index) -> [(offset, nbytes) or None] or None

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

    # ------------------------------------------------------------ sharded arrays

    def _shard_index(self, level, sidx):
        """[(offset, nbytes) or None] per inner chunk of one shard in C order, or None when the shard is missing;
        cached. The CRC32C is checked when the index codecs carry one."""
        key = (level, sidx)
        with self._lock:
            if key in self._index:
                return self._index[key]
        meta = self.levels[level]["meta"]
        per = [c // i for c, i in zip(meta["chunks"], meta["inner"])]
        n = int(np.prod(per))
        codecs = [c.get("name") for c in meta["index_codecs"]]
        if any(c not in ("bytes", "crc32c") for c in codecs):
            raise RegionError(f"{self.store} level {level}: shard index codecs {codecs} are not read here")
        crc = "crc32c" in codecs
        big = any(c.get("name") == "bytes" and (c.get("configuration") or {}).get("endian") == "big"
                  for c in meta["index_codecs"])
        size = 16 * n + (4 if crc else 0)
        skey = vc3d_audit.chunk_key(meta, sidx)
        try:
            raw = (self.store.read(skey, -size) if meta["index_location"] == "end"
                   else self.store.read(skey, 0, size))
        except vc3d_audit.AuditError as exc:
            raise RegionError(str(exc)) from exc
        if raw is None:
            entries = None
        else:
            if len(raw) != size:
                raise RegionError(f"{self.store} {skey}: shard index has {len(raw)} bytes, expected {size}")
            if crc and crc32c(raw[:16 * n]) != struct.unpack("<I", raw[16 * n:])[0]:
                raise RegionError(f"{self.store} {skey}: shard index CRC32C does not match")
            vals = struct.unpack((">" if big else "<") + f"{2 * n}Q", raw[:16 * n])
            entries = [None if (vals[2 * k] == vc3d_audit.EMPTY and vals[2 * k + 1] == vc3d_audit.EMPTY)
                       or not vals[2 * k + 1] else (vals[2 * k], vals[2 * k + 1]) for k in range(n)]
        with self._lock:
            self._index[key] = entries
        return entries

    def _inner(self, meta, raw, level, idx):
        try:
            data = vc3d_audit._v3_bytes_codecs(meta["inner_codecs"], raw)
        except Exception as exc:  # noqa: BLE001 - any codec failure is a read failure here
            raise RegionError(f"{self.store} level {level} inner chunk {idx}: does not decode ({exc})") from exc
        arr = np.frombuffer(data, dtype=_inner_dtype(meta))
        if arr.size != int(np.prod(meta["inner"])):
            raise RegionError(f"{self.store} level {level} inner chunk {idx}: {arr.size} values, expected "
                              f"{int(np.prod(meta['inner']))}")
        return arr.reshape(meta["inner"])

    def _sharded_chunks(self, level, idxs):
        """{inner chunk index: array or None} for inner chunk indices of a sharded level, through the cache, the
        shard indexes and (merged) range reads."""
        meta = self.levels[level]["meta"]
        if any(c.get("name") == "transpose" for c in meta["inner_codecs"]):
            raise RegionError(f"{self.store} level {level}: the transpose codec is not read here")
        per = [c // i for c, i in zip(meta["chunks"], meta["inner"])]
        got, todo = {}, []
        with self._lock:
            for idx in idxs:
                k = (level, "inner", idx)
                if k in self._cache:
                    self._cache.move_to_end(k)
                    got[idx] = self._cache[k]
                else:
                    todo.append(idx)
        if not todo:
            return got
        shards = sorted({tuple(i // p for i, p in zip(idx, per)) for idx in todo})
        with concurrent.futures.ThreadPoolExecutor(min(self.workers, len(shards))) as pool:
            index = dict(zip(shards, pool.map(lambda s: self._shard_index(level, s), shards)))
        by_shard = collections.defaultdict(list)
        for idx in todo:
            sidx = tuple(i // p for i, p in zip(idx, per))
            entries = index[sidx]
            pos = int(np.ravel_multi_index(tuple(i % p for i, p in zip(idx, per)), per))
            entry = entries[pos] if entries is not None else None
            if entry is None:
                got[idx] = None
            else:
                by_shard[sidx].append((entry[0], entry[1], idx))
        jobs = []
        for sidx, items in by_shard.items():
            groups = merge_ranges(items) if self.coalesce else [(o, n, [(o, n, i)]) for o, n, i in items]
            jobs += [(sidx, g) for g in groups]

        def fetch(job):
            sidx, (start, length, members) = job
            skey = vc3d_audit.chunk_key(meta, sidx)
            try:
                raw = self.store.read(skey, start, length)
            except vc3d_audit.AuditError as exc:
                raise RegionError(str(exc)) from exc
            if raw is None or len(raw) != length:
                raise RegionError(f"{self.store} {skey}: range {start} + {length} gave "
                                  f"{'nothing' if raw is None else f'{len(raw)} bytes'}")
            return [(idx, self._inner(meta, raw[off - start:off - start + n], level, idx)) for off, n, idx in members]

        if jobs:
            with concurrent.futures.ThreadPoolExecutor(min(self.workers, len(jobs))) as pool:
                for part in pool.map(fetch, jobs):
                    got.update(part)
        with self._lock:
            self.range_reads += len(jobs)
            for idx in todo:
                self.chunks_read += 1
                self.missing += got[idx] is None
                self._cache[(level, "inner", idx)] = got[idx]
            while len(self._cache) > self._cache_n:
                self._cache.popitem(last=False)
        return got

    # ------------------------------------------------------------ boxes and points

    def read(self, level, box):
        """The box [[z0, z1], [y0, y1], [x0, x1]] of a level (integers; parts outside the array read as fill)."""
        meta = self.levels[level]["meta"]
        if _permutes(meta.get("codecs")):
            raise RegionError(f"{self.store} level {level}: the transpose codec changes the axis order and is not "
                              "read here; rewrite the array without it, in C order")
        box = [[int(a), int(b)] for a, b in box]
        size = [max(0, b - a) for a, b in box]
        fill = meta.get("fill_value")
        dtype = _inner_dtype(meta) if meta["inner"] is not None else _dtype(meta)
        out = np.full(size, fill if isinstance(fill, (int, float)) and fill == fill else 0, dtype=dtype)
        ch, shape = meta["inner"] or meta["chunks"], meta["shape"]
        ranges = [range(max(0, a) // c, (min(b, s) - 1) // c + 1) if min(b, s) > max(0, a) else range(0)
                  for (a, b), c, s in zip(box, ch, shape)]
        idxs = list(itertools.product(*ranges))
        if not idxs:
            return out
        if meta["inner"] is not None:
            parts = self._sharded_chunks(level, idxs)
            got = [(i, parts[i]) for i in idxs]
        else:
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
        read the fill value at their neighbors."""
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
