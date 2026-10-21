"""Ink Lens: reading a region of a surface volume, and pooling it to the 9.6 um grid the ink models expect.

numpy only. Reads, layers first (layers, rows, columns):
  - a zarr array or OME-Zarr group, local or over HTTPS (the Vesuvius Challenge open-data bucket stores segment surface
    volumes as uncompressed zarr v2, which this reads with no zarr package; other codecs use the zarr package if it
    is installed);
  - a .npy, a .npz (array "volume") or a multi-page .tif (tifffile).

Pooling follows the organizers' prepare_9um_isotropic_input.py for a 2.4 um render: mean over k x k pixels in each
layer and mean over k layers (k = 4 for 2.4 um to 9.6 um). A render already near 9.6 um is used as it is (k = 1).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
TARGET_UM = 9.6
USER_AGENT = "ink-lens/0.1"


class VolumeError(ValueError):
    """An input the reader refuses; the message says why."""


# ---------------------------------------------------------------- pooling

def pool_factor(um_per_px):
    """The integer factor that brings a render of um_per_px close to 9.6 um: 1 for 7 um and above, else the nearest
    whole number of 9.6 / um_per_px (4 for 2.4 um)."""
    um = float(um_per_px)
    if not um > 0:
        raise VolumeError(f"pixel size {um_per_px} um must be positive")
    if um >= 7.0:
        return 1
    return max(1, int(round(TARGET_UM / um)))


def pool(volume, k):
    """Mean over k layers and k x k pixels, dropping a remainder at the far edge of each axis; uint8 out."""
    import numpy as np
    a = np.asarray(volume)
    if a.ndim != 3:
        raise VolumeError(f"a surface volume has 3 axes (layers, rows, columns), this one has {a.ndim}")
    k = int(k)
    if k == 1:
        return np.ascontiguousarray(a)
    L, H, W = (s // k * k for s in a.shape)
    if min(L, H, W) == 0:
        raise VolumeError(f"a {a.shape} volume is smaller than one {k} x {k} x {k} block")
    b = a[:L, :H, :W].astype(np.float32).reshape(L // k, k, H // k, k, W // k, k).mean(axis=(1, 3, 5))
    if a.dtype == np.uint8:
        return np.clip(np.rint(b), 0, 255).astype(np.uint8)
    return b


def to_uint8(volume):
    """uint8 as it is; uint16 scaled by 1/257 (the bucket's 16-bit volumes map 0..65535 to 0..255 this way)."""
    import numpy as np
    a = np.asarray(volume)
    if a.dtype == np.uint8:
        return a
    if a.dtype == np.uint16:
        return (a // 257).astype(np.uint8)
    raise VolumeError(f"type {a.dtype}: give a uint8 or uint16 surface volume")


# ---------------------------------------------------------------- zarr over HTTPS or on disk

def _get(url, timeout=60, tries=3):
    """Bytes at url, or None for a missing key (HTTP 404, S3 NoSuchKey)."""
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
    raise VolumeError(f"cannot read {url}: {last}")


def _read(base, key, fetch=_get):
    if str(base).startswith(("http://", "https://")):
        return fetch(f"{str(base).rstrip('/')}/{key}")
    p = Path(base) / key
    return p.read_bytes() if p.is_file() else None


class ZarrArray:
    """One zarr array (v2 or v3), local or remote. Uncompressed chunks are decoded here; compressed ones through
    numcodecs (v2) when it is installed."""

    def __init__(self, base, fetch=_get):
        self.base, self.fetch = str(base).rstrip("/"), fetch
        meta = _read(self.base, ".zarray", fetch)
        if meta is not None:
            m = json.loads(meta)
            self.version = 2
            self.shape, self.chunks = tuple(m["shape"]), tuple(m["chunks"])
            self.dtype = m["dtype"]
            self.fill = m.get("fill_value") or 0
            self.order = m.get("order", "C")
            self.sep = m.get("dimension_separator", ".")
            self.compressor, self.filters = m.get("compressor"), m.get("filters")
        else:
            meta = _read(self.base, "zarr.json", fetch)
            if meta is None:
                raise VolumeError(f"{self.base} is not a zarr array (no .zarray or zarr.json)")
            m = json.loads(meta)
            if m.get("node_type") != "array":
                raise VolumeError(f"{self.base} is a zarr group, not an array")
            self.version = 3
            self.shape = tuple(m["shape"])
            self.chunks = tuple(m["chunk_grid"]["configuration"]["chunk_shape"])
            self.dtype = {"uint8": "|u1", "uint16": "<u2"}.get(m["data_type"], m["data_type"])
            self.fill = m.get("fill_value") or 0
            self.order = "C"
            enc = m.get("chunk_key_encoding", {})
            self.sep = enc.get("configuration", {}).get("separator", "/")
            self.prefix = "c" + self.sep if enc.get("name", "default") == "default" else ""
            codecs = [c.get("name") for c in m.get("codecs", [])]
            self.compressor = None if set(codecs) <= {"bytes", "transpose"} else codecs
            self.filters = None
        if len(self.shape) != 3:
            raise VolumeError(f"{self.base} has {len(self.shape)} axes; a surface volume has 3 (layers, rows, columns)")
        self.chunks_read = 0

    def _key(self, idx):
        key = self.sep.join(str(i) for i in idx)
        return (self.prefix + key) if self.version == 3 else key

    def _decode(self, raw):
        import numpy as np
        if self.compressor is not None or self.filters:
            if self.version != 2:
                raise VolumeError(f"{self.base}: zarr v3 codecs {self.compressor} need the zarr package; "
                                  "read it with zarr and pass a .npy instead")
            try:
                import numcodecs
            except ImportError:
                raise VolumeError(f"{self.base} is compressed ({self.compressor.get('id')}); install numcodecs") \
                    from None
            raw = numcodecs.get_codec(self.compressor).decode(raw)
            for f in reversed(self.filters or []):
                raw = numcodecs.get_codec(f).decode(raw)
        a = np.frombuffer(raw, dtype=np.dtype(self.dtype))
        n = int(np.prod(self.chunks))
        if a.size != n:
            raise VolumeError(f"{self.base}: a chunk holds {a.size} values, not {n}")
        return a.reshape(self.chunks, order=self.order)

    def read(self, z, y, x, workers=8):
        """The box [z0, z1) x [y0, y1) x [x0, x1) as a numpy array; missing chunks are the fill value."""
        import numpy as np
        box = [z, y, x]
        for (a, b), n in zip(box, self.shape):
            if not 0 <= a < b <= n:
                raise VolumeError(f"box {box} is outside the volume's shape {self.shape}")
        out = np.full([b - a for a, b in box], self.fill, dtype=np.dtype(self.dtype))
        ranges = [range(a // c, (b - 1) // c + 1) for (a, b), c in zip(box, self.chunks)]
        keys = [(i, j, k) for i in ranges[0] for j in ranges[1] for k in ranges[2]]

        def one(idx):
            return idx, _read(self.base, self._key(idx), self.fetch)

        with ThreadPoolExecutor(max_workers=workers) as pool_:
            for idx, raw in pool_.map(one, keys):
                if raw is None:
                    continue
                self.chunks_read += 1
                chunk = self._decode(raw)
                src, dst = [], []
                for (a, b), c, i in zip(box, self.chunks, idx):
                    lo, hi = max(a, i * c), min(b, (i + 1) * c)
                    src.append(slice(lo - i * c, hi - i * c))
                    dst.append(slice(lo - a, hi - a))
                out[tuple(dst)] = chunk[tuple(src)]
        return out


def open_zarr(path, fetch=_get):
    """A zarr array, or level 0 of an OME-Zarr group (the first dataset of its multiscales)."""
    path = str(path).rstrip("/")
    try:
        return ZarrArray(path, fetch)
    except VolumeError as exc:
        if "is not a zarr array" not in str(exc) and "is a zarr group" not in str(exc):
            raise
    attrs = _read(path, ".zattrs", fetch) or b"{}"
    a = json.loads(attrs)
    if "multiscales" not in a:
        z3 = _read(path, "zarr.json", fetch)
        a = (json.loads(z3).get("attributes", {}).get("ome", {}) if z3 else {}) or a
    try:
        level = a["multiscales"][0]["datasets"][0]["path"]
    except (KeyError, IndexError, TypeError):
        level = "0"
    return ZarrArray(f"{path}/{level}", fetch)


# ---------------------------------------------------------------- whole files

MAX_FILE_BYTES = 2 << 30


def read_file(path, box=None):
    """A .npy, .npz (array "volume") or multi-page .tif as a (layers, rows, columns) array; box (y, x, h, w) crops
    rows and columns after reading (a .npy is memory-mapped, so only the box is read)."""
    import numpy as np
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".npy":
        a = np.load(p, mmap_mode="r", allow_pickle=False)
    elif suffix == ".npz":
        with np.load(p, allow_pickle=False) as z:
            if "volume" not in z:
                raise VolumeError(f"{p}: an .npz needs an array named 'volume'; it has {list(z)}")
            a = z["volume"]
    elif suffix in (".tif", ".tiff"):
        try:
            import tifffile
        except ImportError:
            raise VolumeError("reading a .tif needs tifffile (pip install tifffile)") from None
        a = tifffile.imread(str(p))
    else:
        raise VolumeError(f"{p}: give a .zarr, .npy, .npz or multi-page .tif surface volume")
    if a.ndim != 3:
        raise VolumeError(f"{p} has {a.ndim} axes; a surface volume has 3 (layers, rows, columns)")
    if box is not None:
        y, x, h, w = box
        if not (0 <= y and 0 <= x and y + h <= a.shape[1] and x + w <= a.shape[2]):
            raise VolumeError(f"box rows {y}..{y + h}, columns {x}..{x + w} is outside the {a.shape[1:]} volume")
        a = a[:, y:y + h, x:x + w]
    return np.ascontiguousarray(a)


def read_region(source, box, layers=None, fetch=_get):
    """The region box (y, x, h, w) of a surface volume, all its layers (or layers=(z0, z1)), as a numpy array.
    source: a zarr path or URL (array or OME-Zarr group), or a .npy, .npz or .tif file."""
    s = str(source)
    if s.rstrip("/").endswith(".zarr") or s.startswith(("http://", "https://")) or Path(s).is_dir():
        arr = open_zarr(s, fetch)
        z0, z1 = layers if layers else (0, arr.shape[0])
        y, x, h, w = box
        data = arr.read((z0, z1), (y, y + h), (x, x + w))
        return data, {"source": s, "shape": list(arr.shape), "chunks_read": arr.chunks_read}
    data = read_file(s, box)
    if layers:
        data = data[layers[0]:layers[1]]
    return data, {"source": s}


__all__ = ["VolumeError", "pool_factor", "pool", "to_uint8", "ZarrArray", "open_zarr", "read_file", "read_region"]
