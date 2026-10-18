"""Is a zarr volume whole where a surface needs it? Headers, pyramid levels and chunk presence, local or remote.

A chunk that is missing reads as fill_value with no error, so a pyramid level with a header and no chunks,
or a hole under a surface, looks like blank papyrus, and a blank ink map over it would mean nothing. Masked
volumes leave empty chunks out on purpose (the air outside the scroll), which is why presence is checked
under a surface's footprint rather than over the whole grid. The failure classes are the ones
sgsllc-jr/zarr-pyramid-audit looks for (https://github.com/sgsllc-jr/zarr-pyramid-audit,
read 7 Oct 2026): a level with a valid header but no chunks, scale transforms that contradict the array shapes,
and chunk stores that cannot be decoded.

Works on a local directory, or over http(s) and s3:// (anonymous, paced, retried). Every chunk answer is
present, missing or unknown (a request that failed, or one not made under the request cap), so a check that
could not finish never passes as a clean one. A 404 is missing only when S3 says NoSuchKey: it also answers
404 NoSuchBucket for keys that exist, and those are asked again (kit/s3retry.py). Sharded zarr v3 arrays are checked chunk by chunk through
their shard indexes. Standard library; decoding blosc, zstd or lz4 chunks needs numcodecs.
"""

import concurrent.futures
import gzip
import http.client
import json
import math
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

from . import keepalive, s3retry, vc3d_io

PRESENT, MISSING, UNKNOWN = "present", "missing", "unknown"
DEFAULT_MARGIN = 60          # voxels of the checked level either side of the surface: a 2um render spans +-54
DEFAULT_MAX_POINTS = 250_000
DEFAULT_MAX_REQUESTS = 4000
DEFAULT_RATE = 20.0          # requests per second to a remote store
META_FILES = (".zarray", ".zattrs", ".zgroup", ".zmetadata", "zarr.json")
EMPTY = 2 ** 64 - 1          # shard index entry of an absent inner chunk
V3_SIZES = {"bool": 1, "int8": 1, "uint8": 1, "int16": 2, "uint16": 2, "int32": 4, "uint32": 4, "int64": 8,
            "uint64": 8, "float16": 2, "float32": 4, "float64": 8, "complex64": 8, "complex128": 16}
_NONZERO = bytes([0] + [1] * 255)


class AuditError(ValueError):
    """The store cannot be audited as given (no zarr metadata, an unreadable header, a failed request)."""


# ---------------------------------------------------------------- stores

def s3_https(url):
    """s3://bucket/key as the bucket's anonymous https URL."""
    bucket, _, key = url[5:].partition("/")
    return f"https://{bucket}.s3.amazonaws.com/{key}".rstrip("/")


def s3_listing(url):
    """(endpoint, key prefix) for listing under an S3 URL, virtual-host or path style; (None, None) otherwise."""
    u = urllib.parse.urlsplit(url)
    host = u.hostname or ""
    if not host.endswith("amazonaws.com"):
        return None, None
    path = u.path.strip("/")
    if re.match(r"^[^.]+(\.[^.]+)*\.s3([.-][a-z0-9-]+)?\.amazonaws\.com$", host) and not host.startswith("s3."):
        return f"{u.scheme}://{u.netloc}", path + "/" if path else ""
    bucket, _, rest = path.partition("/")
    return f"{u.scheme}://{u.netloc}/{bucket}", rest + "/" if rest else ""


class LocalStore:
    """A zarr store on disk; keys are paths relative to its root."""

    remote = False

    def __init__(self, root):
        self.root = Path(root)
        self.requests = 0

    def __str__(self):
        return str(self.root)

    def read(self, key, start=None, length=None):
        """Bytes of a key (a range of them with start/length; start < 0 counts from the end), or None."""
        p = self.root / key
        try:
            with open(p, "rb") as fh:
                if start is None:
                    return fh.read()
                if start < 0:
                    fh.seek(0, 2)
                    fh.seek(max(0, fh.tell() + start))
                    return fh.read()
                fh.seek(start)
                return fh.read(length)
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            return None

    def states(self, keys, budget=None, progress=None):
        return {k: PRESENT if (self.root / k).is_file() else MISSING for k in keys}

    def chunk_keys(self, prefix, limit):
        """Up to `limit` chunk keys under a prefix (files that are not zarr metadata), in sorted order."""
        base = self.root / prefix if prefix else self.root
        out = []
        if not base.is_dir():
            return out
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames.sort(key=lambda d: (not d.isdigit(), int(d) if d.isdigit() else 0, d))
            for f in sorted(filenames):
                if f in META_FILES or f.startswith("."):
                    continue
                out.append(Path(dirpath, f).relative_to(self.root).as_posix())
                if len(out) >= limit:
                    return out
        return out


class HttpStore:
    """A zarr store behind http(s), read anonymously: paced to `rate` requests per second over `workers`
    threads, retried on network errors, 429 and 5xx. A 404 is a missing key only when its body names NoSuchKey or
    no S3 code at all; S3 also answers 404 NoSuchBucket for keys that exist (kit/s3retry.py), and those are
    retried, up to false_404_tries attempts, and counted in false_404s. A HEAD 404 has no body, so it is
    confirmed with a one-byte GET. A 403 is unknown, because S3 answers 403 for missing keys in buckets it will
    not list. Connections are kept alive and reused across requests and threads (kit/keepalive.py) unless an
    opener is given or KIT_HTTP_REUSE=0."""

    remote = True

    def __init__(self, url, rate=DEFAULT_RATE, workers=8, timeout=30.0, retries=2, opener=None, listing=None,
                 false_404_tries=s3retry.TRIES):
        if url.lower().startswith("s3://"):
            url = s3_https(url)
        self.base = url.rstrip("/")
        self.rate, self.workers, self.timeout, self.retries = rate, max(1, workers), timeout, retries
        self.false_404_tries = max(1, false_404_tries)
        self.opener = opener or keepalive.default_opener()   # kept connections (KIT_HTTP_REUSE=0: urlopen)
        self.requests = 0
        self.false_404s = 0
        self._lock = threading.Lock()
        self._next = 0.0
        self.list_endpoint, self.list_prefix = listing if listing else s3_listing(self.base)

    def __str__(self):
        return self.base

    def _pace(self):
        with self._lock:
            self.requests += 1
            if not self.rate:
                return
            now = time.monotonic()
            at = max(now, self._next)
            self._next = at + 1.0 / self.rate
        if at > now:
            time.sleep(at - now)

    def _request(self, url, method="GET", headers=None):
        """(status, body) of one request; status None (and the error as body) when every attempt failed. A 404
        comes back with its error body; a false 404 (S3 naming another code than NoSuchKey) is retried."""
        last, failed, false = None, 0, 0
        while True:
            if failed or false:
                time.sleep(min(8.0, 0.5 * 2 ** failed) if failed else min(2.0, 0.1 * 2 ** false))
            self._pace()
            req = urllib.request.Request(url, method=method, headers={"User-Agent": "kit-vc3d-audit", **(headers or {})})
            try:
                with self.opener(req, timeout=self.timeout) as resp:
                    return resp.status, resp.read() if method == "GET" else b""
            except urllib.error.HTTPError as exc:
                body = exc.read() if exc.code == 404 and method == "GET" else b""
                exc.close()
                if exc.code == 404 and s3retry.false_404(404, body):
                    with self._lock:
                        self.false_404s += 1
                    false += 1
                    last = f"HTTP 404 {s3retry.error_code(body)} on {false} attempts (S3 lists such keys as present)"
                    if false >= self.false_404_tries:
                        return None, last
                    continue
                if exc.code == 429 or exc.code >= 500:
                    last = f"HTTP {exc.code}"
                    failed += 1
                    if failed > self.retries:
                        return None, last
                    continue
                return exc.code, body if exc.code == 404 else None
            except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:   # cut-off reads too
                last = str(getattr(exc, "reason", exc)) or type(exc).__name__
                failed += 1
                if failed > self.retries:
                    return None, last

    def _url(self, key):
        return self.base + "/" + urllib.parse.quote(key) if key else self.base

    def read(self, key, start=None, length=None):
        headers = None
        if start is not None:
            headers = {"Range": f"bytes={start}" if start < 0 else f"bytes={start}-{start + length - 1}"}
        status, body = self._request(self._url(key), headers=headers)
        if status in (200, 206):
            if start is not None and status == 200:  # the server ignored the range
                body = body[start:] if start < 0 else body[start:start + length]
            return body
        if status == 404:
            return None
        raise AuditError(f"{self._url(key)}: " + (f"HTTP {status}" if status else f"request failed ({body})"))

    def state(self, key):
        status, _ = self._request(self._url(key), method="HEAD")
        if status == 404:   # no body to tell NoSuchKey from a false 404: ask again with a one-byte GET
            status, _ = self._request(self._url(key), headers={"Range": "bytes=0-0"})
        return PRESENT if status in (200, 206) else MISSING if status == 404 else UNKNOWN

    def states(self, keys, budget=None, progress=None):
        keys = list(keys)
        budget = len(keys) if budget is None else min(len(keys), max(0, budget))
        out = {k: UNKNOWN for k in keys[budget:]}
        done = 0
        with concurrent.futures.ThreadPoolExecutor(self.workers) as pool:
            for key, st in zip(keys[:budget], pool.map(self.state, keys[:budget])):
                out[key] = st
                done += 1
                if progress and done % 200 == 0:
                    progress(f"checked {done} of {budget} chunk keys")
        return out

    def chunk_keys(self, prefix, limit):
        """Up to `limit` chunk keys under a prefix through an S3 listing; None when the store cannot list."""
        if self.list_endpoint is None:
            return None
        from .fetch import parse_listing
        full = self.list_prefix + prefix
        url = f"{self.list_endpoint}/?list-type=2&max-keys={limit + 5}&prefix={urllib.parse.quote(full)}"
        status, body = self._request(url)
        if status != 200:
            return None
        keys, _ = parse_listing(body.decode("utf-8", "replace"))
        out = []
        for key, _size in keys:
            rest = key[len(self.list_prefix):]
            if rest.rsplit("/", 1)[-1] in META_FILES or rest.rsplit("/", 1)[-1].startswith("."):
                continue
            out.append(rest)
        return out[:limit]


def open_store(location, **kw):
    text = str(location)
    if re.match(r"^(https?|s3)://", text, re.I):
        return HttpStore(text, **kw)
    root = Path(text)
    if not root.is_dir():
        raise AuditError(f"{root}: not a directory")
    return LocalStore(root)


# ---------------------------------------------------------------- headers and levels

def _json(store, key):
    raw = store.read(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AuditError(f"{key}: not valid JSON ({exc})") from exc


def array_meta(store, path):
    """The parsed header of the array at `path` ("" for the store root), or None when there is none."""
    pre = path.strip("/") + "/" if path else ""
    meta = _json(store, pre + ".zarray")
    if meta is not None:
        return _meta_v2(meta, pre)
    meta = _json(store, pre + "zarr.json")
    if meta is not None and meta.get("node_type") == "array":
        return _meta_v3(meta, pre)
    return None


def _meta_v2(meta, pre):
    m = re.match(r"^[<>|]([biufcmM])(\d+)$", str(meta.get("dtype")))
    out = {"zarr_format": 2, "path": pre.rstrip("/"), "shape": list(meta.get("shape") or []),
           "chunks": list(meta.get("chunks") or []), "dtype": meta.get("dtype"),
           "itemsize": int(m.group(2)) if m else None, "fill_value": meta.get("fill_value"),
           "order": meta.get("order", "C"), "sep": meta.get("dimension_separator") or ".", "key_prefix": "",
           "compressor": meta.get("compressor"), "filters": meta.get("filters") or None, "inner": None}
    out["codec"] = (out["compressor"] or {}).get("id", "none") if isinstance(out["compressor"], dict) else "none"
    return out


def _meta_v3(meta, pre):
    conf = (meta.get("chunk_grid") or {}).get("configuration") or {}
    enc = meta.get("chunk_key_encoding") or {"name": "default"}
    default = enc.get("name", "default") == "default"
    sep = (enc.get("configuration") or {}).get("separator", "/" if default else ".")
    out = {"zarr_format": 3, "path": pre.rstrip("/"), "shape": list(meta.get("shape") or []),
           "chunks": list(conf.get("chunk_shape") or []), "dtype": meta.get("data_type"),
           "itemsize": V3_SIZES.get(meta.get("data_type")), "fill_value": meta.get("fill_value"), "order": "C",
           "sep": sep, "key_prefix": "c" + sep if default else "", "codecs": meta.get("codecs") or [], "inner": None}
    names = []
    for codec in out["codecs"]:
        names.append(codec.get("name"))
        if codec.get("name") == "sharding_indexed":
            c = codec.get("configuration") or {}
            out["inner"] = list(c.get("chunk_shape") or [])
            out["inner_codecs"] = c.get("codecs") or []
            out["index_codecs"] = c.get("index_codecs") or [{"name": "bytes", "configuration": {"endian": "little"}},
                                                             {"name": "crc32c"}]
            out["index_location"] = c.get("index_location", "end")
            names += ["(" + "+".join(x.get("name", "?") for x in out["inner_codecs"]) + ")"]
    out["codec"] = "+".join(n for n in names if n) or "none"
    return out


def header_problems(meta):
    """Defects of one array header that make its chunks unreadable or its grid meaningless."""
    out = []
    shape, chunks = meta["shape"], meta["chunks"]
    if len(shape) != len(chunks):
        out.append(f"shape {shape} and chunks {chunks} differ in length")
    elif any(not isinstance(c, int) or c <= 0 for c in chunks) or any(not isinstance(s, int) or s < 0 for s in shape):
        out.append(f"shape {shape} or chunks {chunks} not positive integers")
    if meta["itemsize"] is None:
        out.append(f"data type {meta['dtype']} not understood")
    if meta["inner"] is not None and (len(meta["inner"]) != len(chunks) or
                                      any(c % i for c, i in zip(chunks, meta["inner"]) if i)):
        out.append(f"shard shape {chunks} is not a multiple of the inner chunk shape {meta['inner']}")
    return out


def chunk_key(meta, idx):
    pre = meta["path"] + "/" if meta["path"] else ""
    return pre + meta["key_prefix"] + meta["sep"].join(str(i) for i in idx)


def key_index(meta, key):
    """The chunk index a key names in this array, or None when it names something else."""
    pre = (meta["path"] + "/" if meta["path"] else "") + meta["key_prefix"]
    if not key.startswith(pre):
        return None
    parts = key[len(pre):].split(meta["sep"])
    if len(parts) != len(meta["chunks"]) or not all(v.isdigit() for v in parts):
        return None
    return tuple(int(v) for v in parts)


def grid_counts(meta):
    return [-(-s // c) for s, c in zip(meta["shape"], meta["chunks"])]


def group_attrs(store):
    """(zarr format, attributes) of the store root, (None, None) when it holds no zarr metadata."""
    attrs = _json(store, ".zattrs")
    if attrs is not None:
        return 2, attrs
    root = _json(store, "zarr.json")
    if root is not None:
        a = root.get("attributes") or {}
        return 3, a.get("ome", a) if isinstance(a.get("ome"), dict) else a
    if _json(store, ".zgroup") is not None:
        return 2, {}
    return None, None


def levels(store):
    """([{name, meta, scale, translation, listed}], info) for an OME-Zarr group, finest level first, or a
    bare array as one level named ''. A level listed in the multiscales whose header is missing has meta None."""
    root = array_meta(store, "")
    if root is not None:
        return [{"name": "", "meta": root, "scale": None, "translation": None, "listed": True}], {"kind": "array"}
    version, attrs = group_attrs(store)
    if version is None:
        raise AuditError(f"{store}: no zarr metadata at its root (.zarray, .zgroup, .zattrs or zarr.json)")
    info = {"kind": "group", "zarr_format": version}
    out = []
    ms = (attrs or {}).get("multiscales") or []
    if ms:
        info["axes"] = [a.get("name") if isinstance(a, dict) else a for a in ms[0].get("axes", [])]
        for d in ms[0].get("datasets", []):
            scale = trans = None
            for t in d.get("coordinateTransformations") or []:
                if t.get("type") == "scale":
                    scale = t.get("scale")
                elif t.get("type") == "translation":
                    trans = t.get("translation")
            name = str(d.get("path"))
            out.append({"name": name, "meta": array_meta(store, name), "scale": scale, "translation": trans,
                        "listed": True})
    else:
        for k in range(16):  # no multiscales: numbered levels until one has no header
            meta = array_meta(store, str(k))
            if meta is None:
                break
            out.append({"name": str(k), "meta": meta, "scale": None, "translation": None, "listed": False})
    info["multiscales"] = bool(ms)
    if not out:
        raise AuditError(f"{store}: a zarr group with no levels (no multiscales and no array named 0)")
    return out, info


def level_problems(lv, info):
    """Defects across the pyramid: listed levels without headers, shapes that contradict the scale
    transforms (coordinates would shift between levels), and a level that does not halve."""
    defects, notes = [], []
    base = next((x for x in lv if x["meta"] is not None), None)
    axes = info.get("axes")
    for x in lv:
        m = x["meta"]
        if m is None:
            defects.append(f"level {x['name']}: listed in the multiscales but has no header")
            continue
        for p in header_problems(m):
            defects.append(f"level {x['name']}: {p}")
        if axes and len(axes) != len(m["shape"]):
            defects.append(f"level {x['name']}: {len(m['shape'])} dimensions but {len(axes)} axes")
        if base is None or x is base:
            continue
        if m["dtype"] != base["meta"]["dtype"]:
            notes.append(f"level {x['name']}: data type {m['dtype']} differs from level {base['name']} "
                         f"({base['meta']['dtype']})")
        s0, s1 = base["meta"]["shape"], m["shape"]
        if len(s0) != len(s1):
            continue
        if x["scale"] and base["scale"] and len(x["scale"]) == len(s0) == len(base["scale"]):
            ratio = [b / a if a else 0 for a, b in zip(base["scale"], x["scale"])]
            expect = [a / r if r else 0 for a, r in zip(s0, ratio)]
            if any(abs(e - v) > 1.0 for e, v in zip(expect, s1)):
                defects.append(f"level {x['name']}: shape {s1} contradicts its scale {x['scale']} (expected about "
                               f"{[round(e, 1) for e in expect]} from level {base['name']}); coordinates would "
                               "shift between levels")
        elif not x["scale"]:
            k = lv.index(x) - lv.index(base)
            expect = [a / 2 ** k for a in s0]
            if any(abs(e - v) > 1.0 for e, v in zip(expect[-2:], s1[-2:])):
                notes.append(f"level {x['name']}: shape {s1} is not level {base['name']} halved {k} times "
                             "(no scale transforms to say otherwise)")
    return defects, notes


def factors(lv, x, base):
    """Voxels of level x per voxel of the base level, per axis (z, y, x)."""
    if x["scale"] and base["scale"] and len(x["scale"]) == len(base["scale"]):
        return [a / b if b else 1.0 for a, b in zip(base["scale"], x["scale"])]
    s0, s1 = base["meta"]["shape"], x["meta"]["shape"]
    return [b / a if a else 1.0 for a, b in zip(s0, s1)]


# ---------------------------------------------------------------- decoding

def _decompress(spec, raw):
    cid = (spec or {}).get("id") if isinstance(spec, dict) else None
    if not cid:
        return raw
    if cid == "zlib":
        return zlib.decompress(raw)
    if cid == "gzip":
        return gzip.decompress(raw)
    return bytes(vc3d_io._numcodecs(spec).decode(raw))


def _v3_bytes_codecs(codecs, raw):
    for codec in reversed(codecs):
        name, conf = codec.get("name"), codec.get("configuration") or {}
        if name in ("bytes", "transpose", "endian"):
            continue
        if name == "crc32c":
            raw = raw[:-4]
        elif name == "gzip":
            raw = gzip.decompress(raw)
        elif name in ("zstd", "blosc", "lz4"):
            spec = dict(conf, id=name)
            if name == "blosc":
                spec["shuffle"] = {"noshuffle": 0, "shuffle": 1, "bitshuffle": 2}.get(conf.get("shuffle"), 1)
                spec.pop("typesize", None)
            raw = bytes(vc3d_io._numcodecs(spec).decode(raw))
        else:
            raise vc3d_io.IOFormatError(f"codec {name} not decoded here")
    return raw


def decode(meta, raw, inner=False):
    """Decode one chunk (or one inner chunk of a shard) and check its length; returns (ok, detail)."""
    shape = meta["inner"] if inner else meta["chunks"]
    expect = math.prod(shape) * (meta["itemsize"] or 0)
    try:
        if meta["zarr_format"] == 2:
            data = _decompress(meta["compressor"], raw)
            if meta["filters"]:
                return True, f"decompressed {len(data)} bytes; filters {meta['filters']} not checked here"
        else:
            data = _v3_bytes_codecs(meta["inner_codecs"] if inner else meta["codecs"], raw)
    except vc3d_io.IOFormatError as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 - any codec failure is the finding
        return False, f"does not decode: {type(exc).__name__}: {exc}"
    if expect and len(data) != expect:
        return False, f"decodes to {len(data)} bytes, expected {expect}"
    return True, f"{len(data)} bytes"


def shard_index(meta, store, key):
    """[(offset, nbytes) or None] per inner chunk of a shard, in C order; None when the shard is missing."""
    per = [c // i for c, i in zip(meta["chunks"], meta["inner"])]
    n = math.prod(per)
    crc = any(c.get("name") == "crc32c" for c in meta["index_codecs"])
    big = any(c.get("name") == "bytes" and (c.get("configuration") or {}).get("endian") == "big"
              for c in meta["index_codecs"])
    size = 16 * n + (4 if crc else 0)
    raw = store.read(key, -size) if meta["index_location"] == "end" else store.read(key, 0, size)
    if raw is None:
        return None
    if len(raw) < 16 * n:
        raise AuditError(f"{key}: shard index has {len(raw)} bytes, expected {size}")
    vals = struct.unpack(("<" if not big else ">") + f"{2 * n}Q", raw[:16 * n])
    return [None if (vals[2 * k] == EMPTY and vals[2 * k + 1] == EMPTY) else (vals[2 * k], vals[2 * k + 1])
            for k in range(n)]


# ---------------------------------------------------------------- surface footprint

def surface_samples(surface, scale_segmentation=1.0, max_points=DEFAULT_MAX_POINTS, grid_box=None):
    """Valid vertices of a tifxyz (within grid_box [row0, row1, col0, col1) when given), subsampled to at most
    about max_points, in the volume's level-0 voxels.

    Returns (samples [(x, y, z, row, col)], spacing, info): spacing is the 95th percentile distance between
    neighbouring samples in a row, so a box of that size around each sample covers the surface between them."""
    p = Path(surface)
    gx, gy, gz = (vc3d_io.read_tiff(p / f"{a}.tif") for a in "xyz")
    if not (gx.h == gy.h == gz.h and gx.w == gy.w == gz.w):
        raise AuditError(f"{p}: x, y and z grids differ in size")
    rows, cols = gx.h, gx.w
    r0, r1, c0, c1 = grid_box or (0, rows, 0, cols)
    r0, r1, c0, c1 = max(0, r0), min(rows, r1), max(0, c0), min(cols, c1)
    if r0 >= r1 or c0 >= c1:
        raise AuditError(f"grid_box {grid_box} holds no vertex of the {rows} x {cols} grid")
    stride = max(1, math.ceil(math.sqrt((r1 - r0) * (c1 - c0) / max(1, max_points))))
    s = float(scale_segmentation)
    X, Y, Z = gx.data, gy.data, gz.data
    out, gaps = [], []
    for r in range(r0, r1, stride):
        prev = None
        for c in range(c0, c1, stride):
            i = r * cols + c
            a, b, d = X[i], Y[i], Z[i]
            if (a == -1 and b == -1 and d == -1) or a != a or b != b or d != d or not (a or b or d):
                prev = None
                continue
            pt = (a * s, b * s, d * s, r, c)
            if prev is not None and len(gaps) < 20000:
                gaps.append(math.dist(pt[:3], prev[:3]))
            out.append(pt)
            prev = pt
    gaps.sort()
    spacing = gaps[min(len(gaps) - 1, int(0.95 * len(gaps)))] if gaps else stride * s
    info = {"grid_rows_cols": [rows, cols], "stride": stride, "samples": len(out), "spacing_voxels": round(spacing, 2)}
    if grid_box:
        info["grid_box"] = [r0, r1, c0, c1]
    return out, spacing, info


def _ranges(q, pad, chunks, counts):
    return [range(max(0, int((v - pad) // ch)), min(n - 1, int((v + pad) // ch)) + 1)
            for v, ch, n in zip(q, chunks, counts)]


def footprint(samples, spacing, shape, chunks, factor, margin=DEFAULT_MARGIN):
    """Chunk indices a render along the surface reads in one array.

    factor: voxels of this array per level-0 voxel along (z, y, x). core: chunks within half the sample
    spacing plus one voxel (the trilinear neighbour) of a sample, with the grid rows and columns that reach
    each; halo: chunks only within `margin` voxels further (the layers either side of the surface).
    Returns (core {idx: [r0, r1, c0, c1]}, halo set, samples outside the array)."""
    counts = [-(-s // c) for s, c in zip(shape, chunks)]
    pad = spacing * max(factor) / 2 + 1
    core, halo, outside = {}, set(), 0
    for x, y, z, r, c in samples:
        q = (z * factor[0], y * factor[1], x * factor[2])
        if any(v < -pad or v > s + pad for v, s in zip(q, shape)):
            outside += 1
            continue
        rz, ry, rx = _ranges(q, pad, chunks, counts)
        for i in rz:
            for j in ry:
                for k in rx:
                    box = core.get((i, j, k))
                    if box is None:
                        core[(i, j, k)] = [r, r, c, c]
                    else:
                        box[0], box[1], box[2], box[3] = min(box[0], r), max(box[1], r), min(box[2], c), max(box[3], c)
        if margin:
            hz, hy, hx = _ranges(q, pad + margin, chunks, counts)
            if len(hz) * len(hy) * len(hx) > len(rz) * len(ry) * len(rx):
                for i in hz:
                    for j in hy:
                        for k in hx:
                            halo.add((i, j, k))
    halo.difference_update(core)
    return core, halo, outside


# ---------------------------------------------------------------- checks

def _box(meta, idx, inner=False):
    ch = meta["inner"] if inner else meta["chunks"]
    return [[i * c, min(s, (i + 1) * c)] for i, c, s in zip(idx, ch, meta["shape"])]


def presence(store, meta, core, halo, budget, progress=None):
    """{idx: state} for the core and halo chunks (core first under the request budget). Sharded arrays are
    checked per inner chunk through each shard's index: one request per shard. Returns (states, requests)."""
    order = sorted(core) + sorted(halo)
    if meta["inner"] is None:
        keys = {idx: chunk_key(meta, idx) for idx in order}
        st = store.states([keys[i] for i in order], budget, progress)
        return {i: st[keys[i]] for i in order}, min(len(order), budget) if store.remote else 0
    per = [c // i for c, i in zip(meta["chunks"], meta["inner"])]
    shards = {}
    for idx in order:
        shards.setdefault(tuple(i // p for i, p in zip(idx, per)), []).append(idx)
    states, used = {}, 0
    for sidx, members in shards.items():
        if store.remote and used >= budget:
            states.update({m: UNKNOWN for m in members})
            continue
        used += 1
        try:
            index = shard_index(meta, store, chunk_key(meta, sidx))
        except AuditError:
            states.update({m: UNKNOWN for m in members})
            continue
        for m in members:
            if index is None:
                states[m] = MISSING
                continue
            local = [i - s * p for i, s, p in zip(m, sidx, per)]
            flat = 0
            for v, p in zip(local, per):
                flat = flat * p + v
            states[m] = PRESENT if index[flat] is not None else MISSING
    return states, used if store.remote else 0


def decode_some(store, meta, idxs, limit):
    """Download and decode up to `limit` chunks (inner chunks for a sharded array)."""
    out = []
    for idx in idxs[:limit]:
        if meta["inner"] is None:
            key = chunk_key(meta, idx)
            try:
                raw = store.read(key)
            except AuditError as exc:
                out.append({"chunk": list(idx), "ok": None, "detail": str(exc)})
                continue
            ok, detail = (None, "missing") if raw is None else decode(meta, raw)
        else:
            per = [c // i for c, i in zip(meta["chunks"], meta["inner"])]
            sidx = tuple(i // p for i, p in zip(idx, per))
            key = chunk_key(meta, sidx)
            try:
                index = shard_index(meta, store, key)
                flat = 0
                for i, s, p in zip(idx, sidx, per):
                    flat = flat * p + (i - s * p)
                entry = index[flat] if index else None
                raw = store.read(key, entry[0], entry[1]) if entry else None
            except AuditError as exc:
                out.append({"chunk": list(idx), "ok": None, "detail": str(exc)})
                continue
            ok, detail = (None, "missing") if raw is None else decode(meta, raw, inner=True)
        out.append({"chunk": list(idx), "key": key, "ok": ok, "detail": detail})
    return out


def populated(store, meta, limit=3):
    """(True/False/None, sample chunk keys): does the array hold any chunk at all? None when the store
    cannot list (plain HTTP); the footprint or a probe has to answer then."""
    pre = meta["path"] + "/" if meta["path"] else ""
    keys = store.chunk_keys(pre + meta["key_prefix"] if meta["key_prefix"] else pre, limit)
    if keys is None:
        return None, []
    return bool(keys), keys


def probe(store, meta, budget):
    """Presence of the chunks at the centres of a 3 x 3 x 3 lattice over the middle of the grid (where a
    scroll's papyrus is), for stores that cannot list. Returns ({key: state}, requests)."""
    counts = grid_counts(meta)
    picks = []
    for n in counts:
        if n <= 3:
            picks.append(sorted(set(range(n))))
        else:
            picks.append(sorted({n // 4, n // 2, (3 * n) // 4}))
    idxs = [(a, b, c) for a in picks[0] for b in picks[1] for c in picks[2]] if len(counts) == 3 else \
        [tuple(n // 2 for n in counts)]
    keys = [chunk_key(meta, i) for i in idxs]
    st = store.states(keys, budget)
    return st, min(len(keys), budget)


def render_zeros(path):
    """Zero samples inside a rendered stack's footprint, layer by layer.

    VC3D writes 0 where the surface is invalid, so a pixel 0 in every layer is off the surface; inside the
    footprint (nonzero in some layer) a 0 is a sample of fill_value: a missing chunk, the mask of a masked
    volume, or the volume's edge. Zeros on the centre layer, which lies on the papyrus, are the ones to
    explain. A hole as deep as the whole stack looks like off-surface here; the footprint check covers it."""
    p = Path(path)
    if vc3d_io.is_zarr(p):
        arr = vc3d_io.open_zarr(p)
        n, h, w = arr.shape[-3:]

        def layer(k):
            data, _ = arr.read([(k, k + 1), (0, h), (0, w)])
            return data
    else:
        files = vc3d_io.layer_files(p)
        if not files:
            raise AuditError(f"{p}: neither a zarr nor a folder of numbered layer TIFFs")
        first = vc3d_io.read_tiff(files[0])
        n, h, w = len(files), first.h, first.w

        def layer(k):
            return vc3d_io.read_tiff(files[k]).data
    plane = h * w

    def mask(data):
        if isinstance(data, (bytes, bytearray)):
            return int.from_bytes(bytes(data).translate(_NONZERO), "big")
        return int.from_bytes(bytes(1 if v else 0 for v in data), "big")

    foot = 0
    for k in range(n):
        foot |= mask(layer(k))
    fp = foot.to_bytes(plane, "big").count(1)
    out = {"path": str(p), "layers": n, "height": h, "width": w, "footprint_pixels": fp}
    if not fp:
        out.update(zero_fraction=[], note="every sample is 0: no footprint to judge")
        return out
    mid = n // 2
    zeros, centre = [], b""
    for k in range(n):
        holes = foot ^ mask(layer(k))   # in the footprint and 0 in this layer
        hb = holes.to_bytes(plane, "big")
        zeros.append(round(hb.count(1) / fp, 4))
        if k == mid:
            centre = hb
    out["zero_fraction"] = zeros
    out["centre_layer"] = mid
    out["centre_zero_fraction"] = zeros[mid]
    out["max_zero_fraction"] = max(zeros)
    if zeros[mid]:
        rs = [r for r in range(h) if 1 in centre[r * w:(r + 1) * w]]
        cs = [centre[r * w:(r + 1) * w].find(1) for r in rs] + [centre[r * w:(r + 1) * w].rfind(1) for r in rs]
        out["centre_zero_box_rows_cols"] = [[rs[0], rs[-1]], [min(cs), max(cs)]]
    return out


def audit(location, surface=None, check_levels=None, scale_segmentation=1.0, margin=DEFAULT_MARGIN,
          max_points=DEFAULT_MAX_POINTS, max_requests=DEFAULT_MAX_REQUESTS, decode_n=2, render=None,
          store=None, progress=None, grid_box=None, **store_kw):
    """The whole audit; see the module docstring. check_levels: level names whose chunks under the surface
    are checked (default the first level). Returns a JSON-ready report whose verdict is clean, defects or
    incomplete."""
    say = progress or (lambda m: None)
    report = {"defects": [], "warnings": [], "notes": []}
    if location is not None:
        store = store or open_store(location, **store_kw)
        report["volume"] = str(store)
        report["store"] = "remote" if store.remote else "local"
        say("reading headers")
        lv, info = levels(store)
        report["kind"] = info["kind"]
        report["multiscales"] = info.get("multiscales")
        defects, notes = level_problems(lv, info)
        report["defects"] += defects
        report["notes"] += notes
        base = next((x for x in lv if x["meta"] is not None), None)
        rows = []
        budget = max_requests
        for x in lv:
            m = x["meta"]
            row = {"level": x["name"], "header": m is not None}
            if m is not None:
                row.update(shape=m["shape"], chunks=m["chunks"], dtype=m["dtype"], codec=m["codec"],
                           fill_value=m["fill_value"], zarr_format=m["zarr_format"], scale=x["scale"],
                           chunk_grid=grid_counts(m) if not header_problems(m) else None)
                if m["inner"] is not None:
                    row["inner_chunks"] = m["inner"]
                if x["translation"] is not None:
                    row["translation"] = x["translation"]
                if not header_problems(m):
                    say(f"level {x['name']}: looking for chunks")
                    has, keys = populated(store, m)
                    if has is None and not surface:
                        st, used = probe(store, m, budget)
                        budget -= used
                        found = sum(v == PRESENT for v in st.values())
                        row["probe"] = f"{found} of {len(st)} lattice chunks present"
                        has = True if found else None
                        keys = [k for k, v in st.items() if v == PRESENT][:3]
                        if not found:
                            report["warnings"].append(f"level {x['name']}: none of {len(st)} chunks probed near "
                                                      "the middle of the grid exists (an empty level, or a "
                                                      "hollow or masked middle); give a surface to decide")
                    row["populated"] = has
                    if has is False:
                        report["defects"].append(f"level {x['name']}: header but no chunks; every read returns "
                                                 f"fill_value {m['fill_value']}")
                    row["sample_keys"] = keys[:3]
                    if decode_n and keys and m["inner"] is None and not surface:
                        idxs = [i for i in (key_index(m, k) for k in keys) if i is not None]
                        row["decoded"] = decode_some(store, m, idxs, decode_n)
            rows.append(row)
        report["levels"] = rows
        if surface:
            report["footprint"] = _footprint_report(store, lv, base, surface, check_levels, scale_segmentation,
                                                    margin, max_points, budget, decode_n, report, say, grid_box)
        for row in rows:
            for d in row.get("decoded", []):
                if d["ok"] is False:
                    report["defects"].append(f"level {row['level']}: chunk {d['chunk']} {d['detail']}")
                elif d["ok"] is None:
                    report["warnings"].append(f"level {row['level']}: chunk {d['chunk']} not decoded ({d['detail']})")
        report["requests"] = store.requests
        if getattr(store, "false_404s", 0):
            report["false_404s"] = store.false_404s
            report["notes"].append(f"{store.false_404s} answers were 404s that S3 gives for keys that exist "
                                   "(NoSuchBucket); each was asked again, none was taken as missing")
    if render:
        say("counting zeros in the render")
        rz = render_zeros(render)
        report["render"] = rz
        if rz.get("centre_zero_fraction"):
            report["warnings"].append(
                f"render: {rz['centre_zero_fraction']:.2%} of the footprint is 0 on the centre layer (rows and "
                f"columns {rz['centre_zero_box_rows_cols']}): missing chunks, the mask or the volume's edge")
    unknown = any(r.get("unknown") for r in (report.get("footprint") or {}).get("levels", []))
    report["verdict"] = "defects" if report["defects"] else "incomplete" if unknown else "clean"
    return report


def _footprint_report(store, lv, base, surface, check_levels, scale_segmentation, margin, max_points, budget,
                      decode_n, report, say, grid_box=None):
    say("reading the surface")
    samples, spacing, sinfo = surface_samples(surface, scale_segmentation, max_points, grid_box)
    out = {"surface": str(surface), "scale_segmentation": scale_segmentation, "margin": margin, **sinfo, "levels": []}
    if not samples:
        report["defects"].append(f"{surface}: no valid vertex")
        return out
    names = [x["name"] for x in lv]
    wanted = [str(v) for v in check_levels] if check_levels else [base["name"]]
    for name in wanted:
        if name not in names:
            report["defects"].append(f"level {name}: not in this volume (levels {names})")
            continue
        x = lv[names.index(name)]
        m = x["meta"]
        if m is None or header_problems(m):
            continue
        f = factors(lv, x, base)
        ch = m["inner"] or m["chunks"]
        say(f"level {name}: mapping the surface onto {ch} chunks")
        core, halo, outside = footprint(samples, spacing, m["shape"], ch, f, margin)
        row = {"level": name, "chunks_on_surface": len(core), "chunks_in_margin": len(halo),
               "factor_zyx": [round(v, 6) for v in f]}
        if outside:
            row["samples_outside"] = outside
            report["defects"].append(f"level {name}: {outside} of {len(samples)} surface samples lie outside the "
                                     f"array {m['shape']} (wrong frame, level or scale_segmentation?)")
        say(f"level {name}: checking {len(core) + len(halo)} chunks")
        states, used = presence(store, m, core, halo, budget, say)
        budget -= used
        miss_core = sorted(i for i in core if states.get(i) == MISSING)
        miss_halo = sorted(i for i in halo if states.get(i) == MISSING)
        unknown = sum(1 for v in states.values() if v == UNKNOWN)
        row.update(present=sum(1 for v in states.values() if v == PRESENT), missing_on_surface=len(miss_core),
                   missing_in_margin=len(miss_halo), unknown=unknown)
        if miss_core:
            row["missing_on_surface_chunks"] = [{"chunk": list(i), "voxels_zyx": _box(m, i, m["inner"] is not None),
                                                 "grid_rows": core[i][:2], "grid_cols": core[i][2:]}
                                                for i in miss_core[:50]]
            report["defects"].append(f"level {name}: {len(miss_core)} of {len(core)} chunks under the surface are "
                                     "missing; reads there return fill_value")
        if miss_halo:
            row["missing_in_margin_chunks"] = [list(i) for i in miss_halo[:50]]
            report["warnings"].append(f"level {name}: {len(miss_halo)} chunks within {margin} voxels of the surface "
                                      "(not on it) are missing: the mask, or a hole the outer layers reach")
        if unknown:
            report["warnings"].append(f"level {name}: {unknown} chunks unchecked (request cap or failed requests)")
        if decode_n:
            have = [i for i in sorted(core) if states.get(i) == PRESENT]
            row["decoded"] = decode_some(store, m, have, decode_n)
            for d in row["decoded"]:
                if d["ok"] is False:
                    report["defects"].append(f"level {name}: chunk {d['chunk']} {d['detail']}")
                elif d["ok"] is None:
                    report["warnings"].append(f"level {name}: chunk {d['chunk']} not decoded ({d['detail']})")
        out["levels"].append(row)
    return out
