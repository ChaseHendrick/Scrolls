"""Segments, URLs and a small chunked zarr v2 reader for the ink offset diagnostic.

Everything here reads public data over HTTPS: the scan, the published meshes, surface volumes and ink labels from the
Vesuvius Challenge open data (CC BY-NC 4.0), and villa's lasagna cos field for the same scan from the public Lasagna
Fields bucket on Hugging Face (the field is not in the open data for this scan). Chunks are cached on disk.
"""
import concurrent.futures
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

OPEN_DATA = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
LASAGNA_FIELDS = "https://huggingface.co/buckets/SharpMeow/lasagna-fields/resolve"
P0841_SCAN = "PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr/0"
P0841_COS = ("PHerc0841/representations/predictions/lasagna/20250821151531-lasagna-de45f011/"
             "PHerc0841_cos.ome.zarr/1")
P0841_SV = "surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr/0"
P0841_LABELS = "ink-labels/2.403um-volume-20260319124803/20260918"

# The two development boxes the diagnostic was run on (PHerc0841, 9.366 um scan): the box is rows y0..y1 and columns
# x0..x1 of the published 28-layer surface volume, whose full shape is `shape`.
SEGMENTS = {
    "0841-w00": {
        "segment": "PHerc0841/segments/20260220213127-w00",
        "mesh": "mesh/20260220213127-on-20250821151531-9.366um.tifxyz",
        "shape": [4220, 4760], "box": [371, 3492, 2601, 3981]},
    "0841-ag896": {
        "segment": "PHerc0841/segments/20260220214732-auto_grown_20260220144552896",
        "mesh": "mesh/20260220214732-on-20250821151531-9.366um.tifxyz",
        "shape": [4640, 4720], "box": [704, 3241, 1513, 3403]},
}
DEFAULTS = {
    "scan": f"{OPEN_DATA}/{P0841_SCAN}",
    "cos": f"{LASAGNA_FIELDS}/{P0841_COS}",
    "cos_scale": 2.0,            # cos level 1 voxels per base voxel: 1 / 2
    "surface_volume": P0841_SV,
    "labels": P0841_LABELS,
    "normal_sign": -1,           # n_pub = normal_sign * cross(d/dcol, d/drow) of the mesh
    "layers": 28,
}
KEYS = ("segment", "mesh", "shape", "box")


class DataError(Exception):
    pass


def segments(extra=None):
    """The built-in segment table, updated from a JSON file of the same form ({KEY: {segment, mesh, shape, box,
    and optionally scan, cos, cos_scale, surface_volume, labels, normal_sign}})."""
    table = {k: dict(DEFAULTS, **v) for k, v in SEGMENTS.items()}
    if extra:
        for k, v in json.loads(Path(extra).read_text()).items():
            missing = [f for f in KEYS if f not in v]
            if missing:
                raise DataError(f"segment {k} in {extra} lacks {', '.join(missing)}")
            table[k] = dict(DEFAULTS, **v)
    return table


def segment(key, extra=None):
    table = segments(extra)
    if key not in table:
        raise DataError(f"unknown segment {key!r}; known: {', '.join(sorted(table))} (add one with --segments)")
    return table[key]


def http_get(url, tries=8, timeout=60):
    """The bytes at url, or None when it does not exist (a missing zarr chunk). A local path or file:// URL is read
    from disk. Other errors are retried with backoff."""
    if not url.startswith(("http://", "https://")):
        p = Path(url[7:] if url.startswith("file://") else url)
        return p.read_bytes() if p.is_file() else None
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:  # retried: dropped connections and truncated reads
            last = e
        time.sleep(min(2 ** i, 20))
    raise DataError(f"cannot read {url}: {last}")


class Zarr2:
    """One level of a zarr v2 array (uint8, uncompressed or blosc), read chunk by chunk over HTTPS with a disk cache.
    Missing chunks read as the fill value."""

    def __init__(self, url, cache=None, workers=32):
        self.url = url.rstrip("/")
        raw = http_get(self.url + "/.zarray")
        if raw is None:
            raise DataError(f"no zarr v2 array at {self.url} (.zarray not found)")
        meta = json.loads(raw)
        if meta.get("dtype") not in ("|u1", "uint8"):
            raise DataError(f"{self.url}: dtype {meta.get('dtype')}; only uint8 is supported")
        self.shape = tuple(meta["shape"])
        self.chunks = tuple(meta["chunks"])
        self.sep = meta.get("dimension_separator", ".")
        self.fill = meta.get("fill_value") or 0
        comp = meta.get("compressor")
        self.codec = None
        if comp is not None:
            if comp.get("id") != "blosc":
                raise DataError(f"{self.url}: compressor {comp.get('id')}; only none and blosc are supported")
            import numcodecs
            self.codec = numcodecs.get_codec(comp)
        self.cache = None
        if cache is not None:
            self.cache = Path(cache) / hashlib.sha1(self.url.encode()).hexdigest()[:16]
        self.workers = workers
        self._mem = {}
        self._lock = threading.Lock()

    def _path(self, idx):
        return self.cache / "_".join(map(str, idx)) if self.cache is not None else None

    def _raw(self, idx):
        p = self._path(idx)
        if p is not None and p.exists():
            return p.read_bytes()
        b = http_get(self.url + "/" + self.sep.join(map(str, idx)))
        b = b"" if b is None else b
        if p is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.part")
            tmp.write_bytes(b)
            os.replace(tmp, p)
        return b

    def chunk(self, idx):
        """The whole chunk at chunk index idx (zarr v2 stores edge chunks whole)."""
        idx = tuple(int(i) for i in idx)
        with self._lock:
            if idx in self._mem:
                return self._mem[idx]
        b = self._raw(idx)
        if not b:
            a = np.full(self.chunks, self.fill, np.uint8)
        else:
            if self.codec is not None:
                b = self.codec.decode(b)
            a = np.frombuffer(b, np.uint8)
            if a.size != int(np.prod(self.chunks)):
                raise DataError(f"{self.url} chunk {idx} has {a.size} values, expected {int(np.prod(self.chunks))}")
            a = a.reshape(self.chunks)
        with self._lock:
            if len(self._mem) > 512:
                self._mem.clear()
            self._mem[idx] = a
        return a

    def prefetch(self, ids):
        ids = [tuple(i) for i in ids]
        with concurrent.futures.ThreadPoolExecutor(self.workers) as ex:
            list(ex.map(self._raw_cached, ids))

    def _raw_cached(self, idx):
        p = self._path(idx)
        if p is None or not p.exists():
            self._raw(idx)

    def read_box(self, lo, hi):
        """The array's values in [lo, hi) per axis (clipped reads outside the array give the fill value)."""
        lo = np.asarray(lo, np.int64)
        hi = np.asarray(hi, np.int64)
        ch = np.asarray(self.chunks)
        out = np.full(tuple(hi - lo), self.fill, np.uint8)
        c0 = np.maximum(lo, 0) // ch
        c1 = (np.minimum(hi, self.shape) - 1) // ch
        ids = [tuple(c) for c in np.stack(np.meshgrid(*[np.arange(a, b + 1) for a, b in zip(c0, c1)],
                                                      indexing="ij"), -1).reshape(-1, len(ch))]
        self.prefetch(ids)
        for c in ids:
            start = np.asarray(c) * ch
            a = self.chunk(c)
            s0 = np.maximum(start, lo)
            s1 = np.minimum(np.minimum(start + ch, self.shape), hi)
            if (s1 <= s0).any():
                continue
            src = tuple(slice(int(a0 - b0), int(a1 - b0)) for a0, a1, b0 in zip(s0, s1, start))
            dst = tuple(slice(int(a0 - l0), int(a1 - l0)) for a0, a1, l0 in zip(s0, s1, lo))
            out[dst] = a[src]
        return out

    def sample(self, zyx):
        """Trilinear samples at points zyx (3, N) in this array's voxels (z, y, x), rounded to whole values (scipy keeps
        the uint8 input type, as in the 30 October 2026 run); 0 outside the array."""
        from scipy import ndimage
        zyx = np.asarray(zyx, np.float64)
        out = np.zeros(zyx.shape[1], np.float32)
        f = np.floor(zyx).astype(np.int64)
        good = (f >= 0).all(0) & np.all(f < (np.asarray(self.shape)[:, None] - 1), axis=0)
        if not good.any():
            return out
        lo = f[:, good].min(1)
        hi = f[:, good].max(1) + 2
        sub = self.read_box(lo, hi)
        out[good] = ndimage.map_coordinates(sub, zyx[:, good] - lo[:, None], order=1, mode="constant", cval=0,
                                            prefilter=False)
        return out
