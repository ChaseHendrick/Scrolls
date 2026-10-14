"""Read and write the images and volumes the headless VC3D tools touch, with the standard library.

The agent tools (`kit/vc3d_agent.py`) have to run in any Python, so nothing here needs numpy:

  read_tiff    TIFF and BigTIFF, first page: 8, 16 or 32-bit integer or 32/64-bit float samples, one
               per pixel; strips or tiles; no compression, LZW, deflate or PackBits; the horizontal
               predictor. That covers vc_render_tifxyz layers, tifxyz x/y/z grids and villa's ink maps.
  read_npy     2-D or 3-D .npy (torchscript_infer.py and v8in write their maps this way)
  open_zarr    v2 and unsharded v3 arrays and OME-Zarr groups, uncompressed, zlib or gzip; blosc,
               zstd and lz4 through numcodecs when it is installed
  png_bytes    8-bit grey or RGB PNG, for previews

Pure-Python decoding is slow (LZW runs at a few MB/s), so the agent's `preview` reads the least it
can: a coarse pyramid level, a window, one layer. When numpy and tifffile are importable it uses them.
"""

import array
import ast
import gzip
import json
import math
import struct
import sys
import zlib
from pathlib import Path

KINDS = {  # kind: (array typecode, bytes per sample)
    "u8": ("B", 1), "i8": ("b", 1), "u16": ("H", 2), "i16": ("h", 2),
    "u32": ("I", 4), "i32": ("i", 4), "f32": ("f", 4), "f64": ("d", 8),
}
LITTLE = sys.byteorder == "little"


class IOFormatError(ValueError):
    pass


class Raster:
    """An h x w image in row-major order; `data` is an array.array (or bytes for u8)."""

    __slots__ = ("h", "w", "kind", "data")

    def __init__(self, h, w, kind, data):
        if len(data) != h * w:
            raise IOFormatError(f"raster {h}x{w} given {len(data)} samples")
        self.h, self.w, self.kind, self.data = h, w, kind, data

    def at(self, r, c):
        return self.data[r * self.w + c]

    def row(self, r):
        return self.data[r * self.w:(r + 1) * self.w]

    def floats(self):
        return as_floats(self.data)


def as_floats(data):
    """Samples as a float32 array.array. Bytes are 8-bit samples (0 to 255), never raw float bytes,
    which is what array.array("f", some_bytes) would read them as."""
    if isinstance(data, array.array):
        return data if data.typecode == "f" else array.array("f", data.tolist())
    return array.array("f", list(data))


def _typed(raw, kind, little):
    code, size = KINDS[kind]
    if size == 1:
        return raw if kind == "u8" else array.array(code, raw)
    out = array.array(code)
    if out.itemsize != size:
        raise IOFormatError(f"this Python's array type {code!r} is not {size} bytes")
    out.frombytes(raw[:len(raw) - len(raw) % size])
    if little != LITTLE:
        out.byteswap()
    return out


# ---------------------------------------------------------------- codecs

def lzw_decode(data):
    """TIFF LZW (MSB first, early change), as written by libtiff and tifffile."""
    out, table, width, prev = bytearray(), [bytes([i]) for i in range(256)] + [b"", b""], 9, None
    acc = nbits = pos = 0
    n = len(data)
    while True:
        while nbits < width:
            if pos >= n:
                return bytes(out)
            acc, nbits, pos = (acc << 8) | data[pos], nbits + 8, pos + 1
        nbits -= width
        code, acc = acc >> nbits, acc & ((1 << nbits) - 1)
        if code == 256:
            table, width, prev = table[:258], 9, None
            continue
        if code == 257:
            return bytes(out)
        if prev is None:
            entry = table[code]
        else:
            entry = table[code] if code < len(table) else prev + prev[:1]
            table.append(prev + entry[:1])
            if len(table) + 1 >= 1 << width and width < 12:
                width += 1
        out += entry
        prev = entry


def packbits_decode(data):
    out, i = bytearray(), 0
    while i < len(data):
        n = data[i] - 256 if data[i] > 127 else data[i]
        if n >= 0:
            out += data[i + 1:i + 2 + n]
            i += 2 + n
        else:
            if n != -128:
                out += data[i + 1:i + 2] * (1 - n)
            i += 2
    return bytes(out)


def _numcodecs(spec):
    try:
        import numcodecs
    except ImportError as exc:
        raise IOFormatError(f"compressor {spec.get('id')!r} needs numcodecs (pip install numcodecs), "
                            "or render with --zarr-compressor none|gzip, or use --tif-output") from exc
    return numcodecs.get_codec(spec)


# ---------------------------------------------------------------- TIFF

TIFF_TYPES = {1: "B", 3: "H", 4: "I", 16: "Q", 6: "b", 8: "h", 9: "i", 17: "q"}
TIFF_COMPRESSION = {1: "none", 5: "lzw", 8: "deflate", 32946: "deflate", 32773: "packbits",
                    7: "jpeg", 50000: "zstd", 34925: "lzma", 50001: "webp"}


def tiff_tags(raw, page=0):
    """(byte order, tags) of one page; tags maps number -> tuple of ints."""
    order = {b"II": "<", b"MM": ">"}.get(raw[:2])
    if order is None:
        raise IOFormatError("not a TIFF")
    magic = struct.unpack(order + "H", raw[2:4])[0]
    if magic == 42:
        big, at = False, struct.unpack(order + "I", raw[4:8])[0]
    elif magic == 43:
        big, at = True, struct.unpack(order + "Q", raw[8:16])[0]
    else:
        raise IOFormatError(f"TIFF magic {magic} is neither 42 nor 43")
    for _ in range(page):
        count = struct.unpack(order + ("Q" if big else "H"), raw[at:at + (8 if big else 2)])[0]
        at = struct.unpack(order + ("Q" if big else "I"),
                           raw[at + (8 if big else 2) + count * (20 if big else 12):][:8 if big else 4])[0]
        if not at:
            raise IOFormatError(f"TIFF has no page {page}")
    head, entry, inline_size = (8, 20, 8) if big else (2, 12, 4)
    count = struct.unpack(order + ("Q" if big else "H"), raw[at:at + head])[0]
    tags = {}
    for i in range(count):
        e = raw[at + head + entry * i:at + head + entry * (i + 1)]
        if big:
            tag, typ, n = struct.unpack(order + "HHQ", e[:12])
            inline = e[12:20]
        else:
            tag, typ, n = struct.unpack(order + "HHI", e[:8])
            inline = e[8:12]
        if typ not in TIFF_TYPES:
            continue
        fmt = order + TIFF_TYPES[typ] * n
        size = struct.calcsize(fmt)
        if size <= inline_size:
            src = inline
        else:
            off = struct.unpack(order + ("Q" if big else "I"), inline)[0]
            src = raw[off:off + size]
        tags[tag] = struct.unpack(fmt, src[:size])
    return order, tags


def tiff_info(path):
    """Shape and storage of a TIFF's first page without decoding it."""
    raw = Path(path).read_bytes()
    order, tags = tiff_tags(raw)
    bits, fmt = tags.get(258, (1,))[0], tags.get(339, (1,))[0]
    return {"height": tags[257][0], "width": tags[256][0], "kind": _tiff_kind(bits, fmt),
            "samples_per_pixel": tags.get(277, (1,))[0],
            "compression": TIFF_COMPRESSION.get(tags.get(259, (1,))[0], tags.get(259, (1,))[0]),
            "tiled": 322 in tags, "bigtiff": raw[2:4] in (b"\x2b\x00", b"\x00\x2b"), "bytes": len(raw)}


def _tiff_kind(bits, fmt):
    kind = {(8, 1): "u8", (16, 1): "u16", (32, 1): "u32", (8, 2): "i8", (16, 2): "i16", (32, 2): "i32",
            (32, 3): "f32", (64, 3): "f64"}.get((bits, fmt))
    if kind is None:
        raise IOFormatError(f"{bits}-bit samples of format {fmt} are not supported")
    return kind


def read_tiff(path, page=0):
    """The first (or given) page of a single-sample TIFF as a Raster."""
    raw = Path(path).read_bytes()
    try:
        order, tags = tiff_tags(raw, page)
    except (struct.error, IndexError) as exc:
        raise IOFormatError(f"{path}: truncated TIFF ({exc})") from exc
    w, h = tags[256][0], tags[257][0]
    if tags.get(277, (1,))[0] != 1:
        raise IOFormatError(f"{path}: expected one sample per pixel, found {tags[277][0]}")
    kind = _tiff_kind(tags.get(258, (1,))[0], tags.get(339, (1,))[0])
    size = KINDS[kind][1]
    comp, predictor = tags.get(259, (1,))[0], tags.get(317, (1,))[0]
    decode = {1: bytes, 5: lzw_decode, 8: zlib.decompress, 32946: zlib.decompress,
              32773: packbits_decode}.get(comp)
    if decode is None:
        raise IOFormatError(f"{path}: compression {TIFF_COMPRESSION.get(comp, comp)} not supported")
    if predictor not in (1, 2) or (predictor == 2 and kind.startswith("f")):
        raise IOFormatError(f"{path}: predictor {predictor} not supported for {kind}")
    if 322 in tags:
        bw, bh, offsets, counts = tags[322][0], tags[323][0], tags[324], tags[325]
    else:
        bw, bh, offsets, counts = w, tags.get(278, (h,))[0], tags[273], tags[279]
    bh = min(bh, h) if 322 not in tags else bh
    across = -(-w // bw)
    img = bytearray(w * h * size)
    rowbytes = bw * size
    for n, (off, cnt) in enumerate(zip(offsets, counts)):
        block = bytearray(decode(raw[off:off + cnt]))
        rows = bh if 322 in tags else min(bh, h - n * bh)
        if len(block) < rowbytes * rows:
            block += bytes(rowbytes * rows - len(block))
        if predictor == 2:
            _undo_predictor(block, bw, rows, kind, order)
        y0, x0 = ((n // across) * bh, (n % across) * bw) if 322 in tags else (n * bh, 0)
        span = min(bw, w - x0) * size
        for r in range(min(rows, h - y0)):
            dst = ((y0 + r) * w + x0) * size
            img[dst:dst + span] = block[r * rowbytes:r * rowbytes + span]
    return Raster(h, w, kind, _typed(bytes(img), kind, order == "<"))


def _undo_predictor(block, bw, rows, kind, order):
    size = KINDS[kind][1]
    if size == 1:
        for r in range(rows):
            base = r * bw
            for c in range(base + 1, base + bw):
                block[c] = (block[c] + block[c - 1]) & 255
        return
    code = {2: "H", 4: "I"}[size]
    fmt = order + code * bw
    mask = (1 << (8 * size)) - 1
    for r in range(rows):
        vals = list(struct.unpack_from(fmt, block, r * bw * size))
        for c in range(1, bw):
            vals[c] = (vals[c] + vals[c - 1]) & mask
        struct.pack_into(fmt, block, r * bw * size, *vals)


def write_tiff(path, raster):
    """Single-strip uncompressed little-endian TIFF of a Raster (u8, u16 or f32)."""
    bits, fmt = {"u8": (8, 1), "u16": (16, 1), "f32": (32, 3)}[raster.kind]
    data = raster.data if isinstance(raster.data, (bytes, bytearray)) else raster.data.tobytes()
    if raster.kind != "u8" and not LITTLE:
        swapped = array.array(KINDS[raster.kind][0], data)
        swapped.byteswap()
        data = swapped.tobytes()
    tags = [(256, 4, raster.w), (257, 4, raster.h), (258, 3, bits), (259, 3, 1), (262, 3, 1), (273, 4, None),
            (277, 3, 1), (278, 4, raster.h), (279, 4, len(data)), (339, 3, fmt)]
    data_at = 8 + 2 + 12 * len(tags) + 4
    ifd = struct.pack("<H", len(tags))
    for tag, typ, value in tags:
        value = data_at if value is None else value
        ifd += struct.pack("<HHI", tag, typ, 1) + (struct.pack("<HH", value, 0) if typ == 3 else struct.pack("<I", value))
    Path(path).write_bytes(b"II*\x00" + struct.pack("<I", 8) + ifd + struct.pack("<I", 0) + bytes(data))


# ---------------------------------------------------------------- NPY

NPY_KINDS = {"u1": "u8", "i1": "i8", "u2": "u16", "i2": "i16", "u4": "u32", "i4": "i32", "f4": "f32", "f8": "f64",
             "b1": "u8"}


def npy_header(raw):
    if raw[:6] != b"\x93NUMPY":
        raise IOFormatError("not an .npy file")
    major = raw[6]
    if major == 1:
        hlen, start = struct.unpack("<H", raw[8:10])[0], 10
    else:
        hlen, start = struct.unpack("<I", raw[8:12])[0], 12
    header = ast.literal_eval(raw[start:start + hlen].decode("latin1"))
    descr = header["descr"]
    if not isinstance(descr, str) or descr[1:] not in NPY_KINDS:
        raise IOFormatError(f"npy dtype {descr!r} not supported")
    if header.get("fortran_order"):
        raise IOFormatError("Fortran-ordered .npy not supported")
    return {"shape": tuple(header["shape"]), "kind": NPY_KINDS[descr[1:]], "little": descr[0] != ">",
            "offset": start + hlen}


def read_npy(path, index=None):
    """A 2-D .npy as a Raster; for 3-D, layer `index` (default: the middle one)."""
    raw = Path(path).read_bytes()
    head = npy_header(raw)
    shape, kind, size = head["shape"], head["kind"], KINDS[head["kind"]][1]
    if len(shape) == 2:
        h, w = shape
        start = head["offset"]
    elif len(shape) == 3:
        k = shape[0] // 2 if index is None else index
        if not 0 <= k < shape[0]:
            raise IOFormatError(f"{path}: layer {k} outside {shape[0]}")
        h, w = shape[1:]
        start = head["offset"] + k * h * w * size
    else:
        raise IOFormatError(f"{path}: expected 2-D or 3-D, got shape {shape}")
    return Raster(h, w, kind, _typed(raw[start:start + h * w * size], kind, head["little"]))


# ---------------------------------------------------------------- zarr

class ZArray:
    """A local zarr v2 or (unsharded) v3 array; `read` returns the samples of a box."""

    def __init__(self, path):
        self.path = Path(path)
        if (self.path / ".zarray").is_file():
            meta = json.loads((self.path / ".zarray").read_text())
            self.version = 2
            self.shape, self.chunks = list(meta["shape"]), list(meta["chunks"])
            dtype = meta["dtype"]
            self.little = dtype[0] != ">"
            if dtype[1:] not in NPY_KINDS:
                raise IOFormatError(f"{path}: dtype {dtype} not supported")
            self.kind = NPY_KINDS[dtype[1:]]
            if meta.get("order", "C") != "C" or meta.get("filters"):
                raise IOFormatError(f"{path}: only C order without filters is supported")
            self.sep = meta.get("dimension_separator", ".")
            self.prefix = ""
            self.compressor = meta.get("compressor")
            self.fill = meta.get("fill_value") or 0
        elif (self.path / "zarr.json").is_file():
            meta = json.loads((self.path / "zarr.json").read_text())
            if meta.get("node_type") != "array":
                raise IOFormatError(f"{path}: zarr.json is not an array")
            self.version = 3
            self.shape = list(meta["shape"])
            self.chunks = list(meta["chunk_grid"]["configuration"]["chunk_shape"])
            self.kind = {"uint8": "u8", "int8": "i8", "uint16": "u16", "int16": "i16", "uint32": "u32",
                         "int32": "i32", "float32": "f32", "float64": "f64"}.get(meta["data_type"])
            if self.kind is None:
                raise IOFormatError(f"{path}: data type {meta['data_type']} not supported")
            enc = meta.get("chunk_key_encoding", {"name": "default"})
            self.sep = enc.get("configuration", {}).get("separator", "/" if enc["name"] == "default" else ".")
            self.prefix = "c" + self.sep if enc["name"] == "default" else ""
            self.little, self.compressor = True, None
            for codec in meta.get("codecs", []):
                name, conf = codec["name"], codec.get("configuration", {})
                if name == "bytes":
                    self.little = conf.get("endian", "little") == "little"
                elif name == "sharding_indexed":
                    raise IOFormatError(f"{path}: sharded zarr v3 is not supported without the zarr package")
                elif name == "gzip":
                    self.compressor = {"id": "gzip"}
                elif name in ("zstd", "blosc", "lz4"):
                    spec = dict(conf, id=name)
                    if name == "blosc":
                        spec["shuffle"] = {"noshuffle": 0, "shuffle": 1, "bitshuffle": 2}.get(conf.get("shuffle"), 1)
                        spec.pop("typesize", None)
                    self.compressor = spec
                elif name not in ("transpose",):
                    raise IOFormatError(f"{path}: codec {name} not supported")
            self.fill = meta.get("fill_value") or 0
        else:
            raise IOFormatError(f"{path}: no .zarray or zarr.json")
        self.size = KINDS[self.kind][1]
        self._codec = None

    def _decode(self, raw):
        spec = self.compressor
        if not spec:
            return raw
        cid = spec.get("id")
        if cid == "zlib":
            return zlib.decompress(raw)
        if cid == "gzip":
            return gzip.decompress(raw)
        if self._codec is None:
            self._codec = _numcodecs(spec)
        return bytes(self._codec.decode(raw))

    def _chunk(self, idx):
        key = self.prefix + self.sep.join(str(i) for i in idx)
        f = self.path / key
        n = 1
        for c in self.chunks:
            n *= c
        if not f.is_file():
            fill = _typed(struct.pack("<" + KINDS[self.kind][0], self.fill), self.kind, True)
            return bytes(fill if isinstance(fill, (bytes, bytearray)) else fill.tobytes()) * n
        data = self._decode(f.read_bytes())
        if len(data) != n * self.size:
            raise IOFormatError(f"{f}: chunk holds {len(data)} bytes, expected {n * self.size}")
        return data

    def read(self, box):
        """box: [(start, stop)] per axis. Returns an array.array (bytes for u8) in C order."""
        dims = len(self.shape)
        box = [(max(0, a), min(s, b)) for (a, b), s in zip(box, self.shape)]
        out_shape = [b - a for a, b in box]
        if any(n <= 0 for n in out_shape):
            raise IOFormatError(f"empty box {box} for shape {self.shape}")
        size = self.size
        out = bytearray(math.prod(out_shape) * size)
        ranges = [range(a // c, (b - 1) // c + 1) for (a, b), c in zip(box, self.chunks)]
        for idx in _product(ranges):
            data = self._chunk(idx)
            lo = [max(a, i * c) for (a, _), i, c in zip(box, idx, self.chunks)]
            hi = [min(b, (i + 1) * c) for (_, b), i, c in zip(box, idx, self.chunks)]
            # copy rows along the last axis
            for pre in _product([range(l, h) for l, h in zip(lo[:-1], hi[:-1])]):
                src = 0
                dst = 0
                for d in range(dims - 1):
                    src = src * self.chunks[d] + (pre[d] - idx[d] * self.chunks[d])
                    dst = dst * out_shape[d] + (pre[d] - box[d][0])
                src = (src * self.chunks[-1] + lo[-1] - idx[-1] * self.chunks[-1]) * size
                dst = (dst * out_shape[-1] + lo[-1] - box[-1][0]) * size
                n = (hi[-1] - lo[-1]) * size
                out[dst:dst + n] = data[src:src + n]
        return _typed(bytes(out), self.kind, self.little), out_shape


def _product(ranges):
    if not ranges:
        yield ()
        return
    for head in ranges[0]:
        for tail in _product(ranges[1:]):
            yield (head,) + tail


def zarr_levels(path):
    """[(name, shape)] of an OME-Zarr group's levels, finest first; a bare array is one level ''."""
    root = Path(path)
    if (root / ".zarray").is_file() or (root / "zarr.json").is_file() and \
            json.loads((root / "zarr.json").read_text()).get("node_type") == "array":
        return [("", ZArray(root).shape)]
    names = []
    attrs = {}
    if (root / ".zattrs").is_file():
        attrs = json.loads((root / ".zattrs").read_text())
    elif (root / "zarr.json").is_file():
        attrs = json.loads((root / "zarr.json").read_text()).get("attributes", {})
        attrs = attrs.get("ome", attrs)
    for ms in attrs.get("multiscales", [])[:1]:
        names = [d["path"] for d in ms.get("datasets", [])]
    if not names:
        names = sorted((p.name for p in root.iterdir() if p.is_dir() and p.name.isdigit()), key=int)
    out = []
    for name in names:
        try:
            out.append((name, ZArray(root / name).shape))
        except IOFormatError:
            continue
    if not out:
        raise IOFormatError(f"{path}: not a zarr array or OME-Zarr group")
    return out


def open_zarr(path, level=None):
    levels = zarr_levels(path)
    if level is None:
        name = levels[0][0]
    else:
        name = str(level)
        if name not in [n for n, _ in levels]:
            raise IOFormatError(f"{path}: no level {name!r}; levels {[n for n, _ in levels]}")
    return ZArray(Path(path) / name if name else Path(path))


def is_zarr(path):
    p = Path(path)
    return p.is_dir() and any((p / f).is_file() for f in (".zarray", ".zgroup", "zarr.json"))


# Forrest McDonald's volcomp copies of the open-data scans (Community report: Discord #general, 2026-09-04, about
# 6 TB for the bucket's ~300 TB, https://dl.ash2txt.org/community-uploads/forrest/volcomp/, codec
# https://github.com/SuperOptimizer/volume-compressor, VC3D support in villa PR #1704). The copies keep the scans'
# zarr names, so a copy is known by this prefix or by its codec. Lossy: at q = 8, the setting published at level 0,
# 2.5D ink at 9 um lost about a quarter of its ink/papyrus separation on two PHerc0139 segments and q = 4 about 7 %
# (Community report, pscamillo, Discord #show-and-tell, 2026-09-10, https://github.com/pscamillo/volcomp-ink-curve);
# PR #1704 itself says not to run the released models on them.
VOLCOMP_PREFIX = "community-uploads/forrest/volcomp/"
VOLCOMP_COST = ("volcomp is lossy: at q 8 (the published level 0) released 2.5D ink models lost about a quarter of "
                "their separation on PHerc0139 (pscamillo, 2026-09-10), and villa PR #1704 says not to run the released "
                "models on these volumes; render ink inputs from the open-data bucket instead")


def _codecs(codecs):
    """(name, configuration) of every codec in a zarr v3 codec list, inside sharding too."""
    for c in codecs or []:
        if isinstance(c, dict):
            conf = c.get("configuration") or {}
            yield c.get("name"), conf
            yield from _codecs(conf.get("codecs"))


def volcomp_source(path):
    """Why a volume is a lossy volcomp copy, or None. A URL or path under the community copies' prefix is one; a
    local zarr (group or array) is one when its level-0 array uses the volcomp codec (v3 codecs, or a v2
    compressor of that id). Remote volumes elsewhere are not opened here."""
    text = str(path).replace("\\", "/")
    if VOLCOMP_PREFIX in text:
        return f"{path} is a community volcomp copy ({VOLCOMP_PREFIX}). {VOLCOMP_COST}"
    if "://" in text:
        return None
    root = Path(path)
    for meta in (root / "zarr.json", root / "0" / "zarr.json", root / ".zarray", root / "0" / ".zarray"):
        try:
            info = json.loads(meta.read_text()) if meta.is_file() else None
        except (OSError, ValueError):
            info = None
        if not isinstance(info, dict):
            continue
        if meta.name == ".zarray":
            comp = info.get("compressor") or {}
            found = [(comp.get("id"), comp)] if isinstance(comp, dict) else []
        elif info.get("node_type") == "array":
            found = list(_codecs(info.get("codecs")))
        else:
            continue
        for name, conf in found:
            if name == "volcomp":
                q = conf.get("q")
                q = f" (q {q:g})" if isinstance(q, (int, float)) else ""
                return f"{path} is volcomp-compressed{q}. {VOLCOMP_COST}"
        return None
    return None


def layer_files(path):
    """Numbered layer images of a directory (00.tif, 01.tif, ...), in numeric order."""
    files = [f for f in Path(path).iterdir() if f.suffix.lower() in (".tif", ".tiff") and f.stem.isdigit()]
    return sorted(files, key=lambda f: int(f.stem))


def is_tifxyz(path):
    p = Path(path)
    return p.is_dir() and all((p / f"{a}.tif").is_file() for a in "xyz")


# ---------------------------------------------------------------- PNG

def png_bytes(h, w, data, channels=1):
    """8-bit grey (channels=1) or RGB (3) PNG of row-major samples."""
    stride = w * channels
    if len(data) != h * stride:
        raise IOFormatError(f"PNG {w}x{h}x{channels} given {len(data)} bytes")
    raw = b"".join(b"\x00" + bytes(data[r * stride:(r + 1) * stride]) for r in range(h))

    def chunk(tag, payload):
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0 if channels == 1 else 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def read_png_gray(blob):
    """Decode an 8-bit grey or RGB, non-interlaced PNG (enough to test png_bytes and read previews)."""
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise IOFormatError("not a PNG")
    pos, idat, w, h, channels = 8, b"", 0, 0, 1
    while pos < len(blob):
        n = struct.unpack(">I", blob[pos:pos + 4])[0]
        tag, payload = blob[pos + 4:pos + 8], blob[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h, depth, color = struct.unpack(">IIBB", payload[:10])
            if depth != 8 or color not in (0, 2) or payload[12]:
                raise IOFormatError("only 8-bit grey or RGB, non-interlaced")
            channels = 1 if color == 0 else 3
        elif tag == b"IDAT":
            idat += payload
        pos += 12 + n
    raw = zlib.decompress(idat)
    stride = w * channels
    out = bytearray()
    prev = bytearray(stride)
    for r in range(h):
        f = raw[r * (stride + 1)]
        line = bytearray(raw[r * (stride + 1) + 1:(r + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b, c = prev[i], prev[i - channels] if i >= channels else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += line
        prev = line
    return h, w, channels, bytes(out)


# ---------------------------------------------------------------- statistics and previews

def percentile(sorted_vals, pct):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * pct / 100.0
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def sample_values(values, limit=200000):
    step = max(1, len(values) // limit)
    return values[::step]


def stats(raster, threshold=None, skip_zero=False):
    """Summary of a Raster: min, max, mean, nonzero fraction, percentiles, fraction above threshold."""
    vals = raster.data
    n = len(vals)
    sample = sorted(v for v in sample_values(vals) if not (skip_zero and v == 0) and v == v)
    nonzero = sum(1 for v in sample_values(vals) if v) / max(1, len(sample_values(vals)))
    out = {"shape": [raster.h, raster.w], "kind": raster.kind, "pixels": n,
           "min": sample[0] if sample else None, "max": sample[-1] if sample else None,
           "mean": round(sum(sample) / len(sample), 4) if sample else None,
           "p1": percentile(sample, 1), "p50": percentile(sample, 50), "p99": percentile(sample, 99),
           "nonzero_fraction": round(nonzero, 4), "sampled": len(sample) < n}
    if threshold is not None:
        sv = sample_values(vals)
        out["threshold"] = threshold
        out["above_threshold_fraction"] = round(sum(1 for v in sv if v > threshold) / max(1, len(sv)), 5)
    return out


def prob_threshold(kind):
    """Sample value meaning probability 0.5 for an ink map of this kind (uint8 0-255, uint16, float 0-1)."""
    return {"u8": 127.5, "u16": 32767.5}.get(kind, 0.5)


def downsample(raster, factor, how="mean"):
    """Block reduce by an integer factor (mean, max or nearest), returning float32 samples."""
    if factor <= 1:
        return Raster(raster.h, raster.w, "f32", as_floats(raster.data))
    h, w = raster.h // factor, raster.w // factor
    h, w = max(1, h), max(1, w)
    data, W = raster.data, raster.w
    out = array.array("f", bytes(4 * h * w))
    if how == "nearest":
        c0 = factor // 2
        for r in range(h):
            base = (r * factor + factor // 2) * W
            out[r * w:(r + 1) * w] = as_floats(data[base + c0:base + c0 + w * factor:factor][:w])
        return Raster(h, w, "f32", out)
    reduce_max = how == "max"
    for r in range(h):
        acc = [0.0] * w if not reduce_max else [-math.inf] * w
        for rr in range(r * factor, min(raster.h, (r + 1) * factor)):
            row = data[rr * W:rr * W + w * factor]
            for c in range(w):
                block = row[c * factor:(c + 1) * factor]
                if reduce_max:
                    m = max(block)
                    if m > acc[c]:
                        acc[c] = m
                else:
                    acc[c] += sum(block)
        if not reduce_max:
            area = factor * min(factor, raster.h - r * factor)
            acc = [a / area for a in acc]
        out[r * w:(r + 1) * w] = array.array("f", acc)
    return Raster(h, w, "f32", out)


def to_u8(raster, lo_pct=1.0, hi_pct=99.0, skip_zero=True, invert=False, lo=None, hi=None):
    """Contrast-stretch a Raster to bytes; zeros stay black when skip_zero (VC3D marks off-surface as 0)."""
    vals = raster.data
    if lo is None or hi is None:
        sample = sorted(v for v in sample_values(vals) if v == v and not (skip_zero and v == 0))
        if not sample:
            return bytes(len(vals)), (0, 0)
        lo = percentile(sample, lo_pct) if lo is None else lo
        hi = percentile(sample, hi_pct) if hi is None else hi
    span = hi - lo
    out = bytearray(len(vals))
    for i, v in enumerate(vals):
        if v != v or (skip_zero and v == 0):
            continue
        t = (v - lo) / span if span else 0.5  # a uniform image shows mid grey, not black
        g = 0 if t <= 0 else 255 if t >= 1 else int(t * 255 + 0.5)
        out[i] = 255 - g if invert else g
    return bytes(out), (lo, hi)


def numpy_or_none():
    try:
        import numpy
        return numpy
    except ImportError:
        return None


def raster_from_numpy(arr):
    np = numpy_or_none()
    a = np.ascontiguousarray(arr, dtype=np.float32)
    return Raster(a.shape[0], a.shape[1], "f32", array.array("f", a.tobytes()))
