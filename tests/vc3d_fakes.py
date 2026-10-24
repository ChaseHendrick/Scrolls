"""Small fixture writers and a local S3-like server for the zarr, false-404 and VC3D cache tests.

  write_array, write_group   uint8 zarr arrays and OME-Zarr groups (v2 or v3) holding value(z, y, x)
  write_tifxyz, plane        a tifxyz surface from a function of (row, column)
  sheet, ramp                volume contents for the tests
  write_layers               numbered u8 layer TIFFs
  env_for                    an environment whose VC3D remote cache is a folder of the test
  S3LikeServer               a local HTTP server over a folder that answers like S3, false 404s included
  no_proxy_opener            urlopen without proxy settings, for the local servers

Standard library only (blosc through numcodecs when a test asks for it).
"""

import array
import gzip
import json
import os
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kit import vc3d_io  # noqa: E402


# ---------------------------------------------------------------- fixture writers

def _compress(raw, compressor):
    if not compressor or compressor == "none":
        return raw, None
    if compressor == "gzip":
        return gzip.compress(raw, 1), {"id": "gzip", "level": 1}
    if compressor == "zlib":
        return zlib.compress(raw, 1), {"id": "zlib", "level": 1}
    import numcodecs
    codec = numcodecs.get_codec({"id": compressor} if compressor != "blosc" else {"id": "blosc", "cname": "lz4"})
    return bytes(codec.encode(raw)), codec.get_config()


def write_array(path, shape, value, chunk, compressor=None, zarr_format=2, sep="/", fill=0, skip=None):
    """A uint8 zarr array holding value(z, y, x) (any number of axes: value gets one index per axis).
    zarr_format 3 writes zarr.json with a bytes codec and gzip; skip(chunk index) leaves a chunk out."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    dims = len(shape)
    if zarr_format == 2:
        _, spec = _compress(b"", compressor)
        (p / ".zarray").write_text(json.dumps({
            "zarr_format": 2, "shape": list(shape), "chunks": list(chunk), "dtype": "|u1", "compressor": spec,
            "fill_value": fill, "filters": None, "order": "C", "dimension_separator": sep}))
        key = lambda idx: sep.join(str(i) for i in idx)  # noqa: E731
    else:
        codecs = [{"name": "bytes", "configuration": {"endian": "little"}}]
        if compressor == "gzip":
            codecs.append({"name": "gzip", "configuration": {"level": 1}})
        (p / "zarr.json").write_text(json.dumps({
            "zarr_format": 3, "node_type": "array", "shape": list(shape), "data_type": "uint8",
            "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": list(chunk)}},
            "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}},
            "codecs": codecs, "fill_value": fill}))
        key = lambda idx: "c/" + "/".join(str(i) for i in idx)  # noqa: E731
    counts = [-(-s // c) for s, c in zip(shape, chunk)]

    def indices(ranges):
        if not ranges:
            yield ()
            return
        for i in ranges[0]:
            for rest in indices(ranges[1:]):
                yield (i,) + rest

    def chunk_bytes(idx):
        lo = [i * c for i, c in zip(idx, chunk)]
        raw = bytearray()
        for head in indices([range(l, l + c) for l, c in zip(lo[:-1], chunk[:-1])]):
            inside = all(v < s for v, s in zip(head, shape))
            row = range(lo[-1], lo[-1] + chunk[-1])
            raw += bytes(value(*head, x) if inside and x < shape[-1] else fill for x in row)
        return bytes(raw)

    for idx in indices([range(n) for n in counts]):
        if skip is not None and skip(idx):
            continue
        raw = chunk_bytes(idx)
        out = p / key(idx)
        out.parent.mkdir(parents=True, exist_ok=True)
        if zarr_format == 3:
            out.write_bytes(gzip.compress(raw, 1) if compressor == "gzip" else raw)
        else:
            out.write_bytes(_compress(raw, compressor)[0])
    assert dims == len(chunk)
    return p


def write_group(path, shape, value, chunk=(32, 32, 32), compressor=None, levels=1, zarr_format=2, binned="yx"):
    """An OME-Zarr group: level 0 holds value(z, y, x); level k samples level 0 every 2^k along the
    binned axes ("yx" like a rendered surface volume, whose levels keep every layer; "zyx" like a CT scan)."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    names = []
    for k in range(levels):
        f = [2 ** k if a in binned else 1 for a in "zyx"]
        if k and any(s < g for s, g in zip(shape, f)):
            break
        sh = [max(1, s // g) for s, g in zip(shape, f)]
        ch = [min(c, s) for c, s in zip(chunk, sh)]
        write_array(p / str(k), sh, (lambda g: lambda z, y, x: value(z * g[0], y * g[1], x * g[2]))(f), ch, compressor,
                    zarr_format=zarr_format)
        names.append((str(k), f))
    ms = [{"version": "0.4", "name": "kit-test", "axes": [{"name": a, "type": "space"} for a in "zyx"],
           "datasets": [{"path": n, "coordinateTransformations": [{"type": "scale", "scale": [float(g) for g in f]}]}
                        for n, f in names]}]
    if zarr_format == 2:
        (p / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
        (p / ".zattrs").write_text(json.dumps({"multiscales": ms}))
    else:
        (p / "zarr.json").write_text(json.dumps({"zarr_format": 3, "node_type": "group",
                                                 "attributes": {"ome": {"version": "0.5", "multiscales": ms}}}))
    return p


def write_tifxyz(path, point, rows=9, cols=9, scale=0.25, meta=None):
    """A tifxyz surface: point(r, c) -> (x, y, z), or None for an invalid vertex (-1, -1, -1)."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    grids = [array.array("f") for _ in range(3)]
    for r in range(rows):
        for c in range(cols):
            v = point(r, c) or (-1.0, -1.0, -1.0)
            for k in range(3):
                grids[k].append(float(v[k]))
    for k, a in enumerate("xyz"):
        vc3d_io.write_tiff(p / f"{a}.tif", vc3d_io.Raster(rows, cols, "f32", grids[k]))
    m = {"scale": [scale, scale], "format": "tifxyz", "type": "seg", "uuid": p.name}
    m.update(meta or {})
    (p / "meta.json").write_text(json.dumps(m))
    return p


def plane(z, x0=8.0, step=4.0):
    """Vertices of a flat surface at height z, x0 + step * column by x0 + step * row; +N points to +z."""
    return lambda r, c: (x0 + step * c, x0 + step * r, z)


def sheet(z, y, x):
    """A papyrus sheet 3 voxels thick at z = 32 between neighboring windings at z = 20 and 44."""
    if abs(z - 32) <= 1:
        return 200
    if abs(z - 20) <= 1 or abs(z - 44) <= 1:
        return 150
    return 20


def ramp(z, y, x):
    """Brighter with depth: 4 + 3 z, so a layer's value tells which way the stack runs."""
    return min(255, 4 + 3 * z)


def write_layers(folder, layers, h, w):
    """Numbered u8 layer TIFFs from a list of byte strings."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for k, img in enumerate(layers):
        vc3d_io.write_tiff(folder / f"{k:02d}.tif", vc3d_io.Raster(h, w, "u8", bytes(img)))
    return folder


def env_for(home, **extra):
    """An environment whose VC3D remote cache is a folder of the test (VC3D.ini in VC3D_CONFIG_DIR), with nothing
    from a real VC3D or kit setting."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("VC_", "KIT_", "FAKE_", "VC3D_"))}
    conf = Path(home) / "vc3d-config"
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "VC3D.ini").write_text(f"[viewer]\nremote_cache_dir={Path(home) / 'remote_cache'}\n")
    env.update(PYTHONPATH=str(ROOT), VC3D_CONFIG_DIR=str(conf), HOME=str(home))
    env.update({k: str(v) for k, v in extra.items()})
    return env


class S3LikeServer:
    """A local HTTP server over a folder that answers like S3, false 404s included. A missing key gets 404 with
    <Code>NoSuchKey</Code>; the first `false` requests for each key get 404 with <Code>NoSuchBucket</Code>, and a
    key in `always_false` gets it every time (S3 sends such answers for keys it holds; kit/s3retry.py). Range
    and HEAD work. Use as a context manager; .url is the server's base URL and .hits counts requests per key."""

    def __init__(self, root, false=1, always_false=()):
        import collections
        import http.server
        import threading
        import urllib.parse
        self.root, self.false, self.always_false = Path(root), false, set(always_false)
        self.hits = collections.Counter()
        lock = threading.Lock()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _error(self, code, s3code, head):
                body = b"" if head else (f"<?xml version=\"1.0\"?><Error><Code>{s3code}</Code>"
                                         f"<Message>test</Message></Error>").encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _serve(self, head):
                key = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip("/")
                with lock:
                    n = outer.hits[key]
                    outer.hits[key] += 1
                if key in outer.always_false or n < outer.false:
                    return self._error(404, "NoSuchBucket", head)
                f = outer.root / key
                if not f.is_file():
                    return self._error(404, "NoSuchKey", head)
                data, status, extra = f.read_bytes(), 200, {}
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    a, _, b = rng[6:].partition("-")
                    a, b = int(a), min(int(b) if b else len(data) - 1, len(data) - 1)
                    extra["Content-Range"] = f"bytes {a}-{b}/{len(data)}"
                    data, status = data[a:b + 1], 206
                self.send_response(status)
                for k, v in extra.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if not head:
                    self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                self._serve(False)

            def do_HEAD(self):  # noqa: N802
                self._serve(True)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def no_proxy_opener():
    """urlopen that ignores proxy settings, for the local test servers."""
    import urllib.request
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open
