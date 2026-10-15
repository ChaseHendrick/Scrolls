"""Tests for kit.keepalive (kept HTTP connections) and the sharded, merged range reads of kit.vc3d_region.

A local HTTP/1.1 server serves a folder (GET with byte ranges, HEAD, S3-style 404) and counts the connections it
accepts, so connection reuse is counted, not assumed. It can also close each connection after answering without
saying so, which is how a server drops an idle kept connection: the next request on it must be sent again on a new
one. The sharded arrays are written here with a real CRC32C in their indexes, and every read is checked voxel for
voxel against the values written, merged and unmerged alike.
"""
import gzip
import http.server
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kit import keepalive, vc3d_audit  # noqa: E402

try:
    import numpy as np
    from kit import vc3d_region
except ImportError:                                 # pragma: no cover
    np = None

NOSUCHKEY = b"<?xml version='1.0'?><Error><Code>NoSuchKey</Code></Error>"


class Server:
    """HTTP/1.1 over a folder; counts connections and requests; drop=True closes after every answer silently, and
    idle=SECONDS closes a connection that waits that long for its next request, as servers do (nginx: 75 s)."""

    def __init__(self, root, drop=False, idle=None):
        self.root = Path(root)
        self.drop = drop
        self.connections = 0
        self.hits = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = idle

            def setup(self):
                super().setup()
                with lock:
                    server.connections += 1

            def log_message(self, *a):
                pass

            def _answer(self, body_wanted):
                path = server.root / self.path.lstrip("/").split("?")[0]
                rng = self.headers.get("Range")
                with lock:
                    server.hits.append((self.command, self.path, rng))
                if not path.is_file():
                    self.send_response(404)
                    self.send_header("Content-Length", str(len(NOSUCHKEY)))
                    self.end_headers()
                    if body_wanted:
                        self.wfile.write(NOSUCHKEY)
                else:
                    data = path.read_bytes()
                    status = 200
                    if rng:
                        spec = rng.split("=", 1)[1]
                        a, b = spec.split("-")
                        if a == "":
                            data = data[-int(b):]
                        else:
                            data = data[int(a):int(b) + 1]
                        status = 206
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    if body_wanted:
                        self.wfile.write(data)
                if server.drop:
                    self.close_connection = True       # without a Connection: close header

            def do_GET(self):
                self._answer(True)

            def do_HEAD(self):
                self._answer(False)

        lock = threading.Lock()
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "a.bin").write_bytes(bytes(range(256)) * 4)
        self.servers, self.pools = [], []

    def tearDown(self):
        for k in self.pools:
            k.close()
        for s in self.servers:
            s.close()
        self.tmp.cleanup()

    def ka(self, **kw):
        k = keepalive.KeepAlive(proxies={}, **kw)
        self.pools.append(k)
        return k

    def server(self, drop=False, idle=None):
        s = Server(self.d, drop, idle)
        self.servers.append(s)
        return s


class KeepAliveTest(Base):
    def test_requests_share_one_connection(self):
        s = self.server()
        ka = self.ka()
        for k in range(10):
            req = urllib.request.Request(f"{s.url}/a.bin", headers={"Range": f"bytes={k}-{k + 3}"})
            with ka(req, timeout=5) as r:
                self.assertEqual((r.status, r.read()), (206, bytes(range(k, k + 4))))
        self.assertEqual((s.connections, ka.opened, ka.reused), (1, 1, 9))
        self.assertEqual(ka.idle(), {f"http://127.0.0.1:{s.httpd.server_address[1]}": 1})

    def test_errors_come_back_as_urllib_errors(self):
        s = self.server()
        ka = self.ka()
        with self.assertRaises(urllib.error.HTTPError) as cm:
            ka(urllib.request.Request(f"{s.url}/nothing"), timeout=5)
        self.assertEqual(cm.exception.code, 404)
        self.assertEqual(cm.exception.read(), NOSUCHKEY)
        with ka(urllib.request.Request(f"{s.url}/a.bin", method="HEAD"), timeout=5) as r:
            self.assertEqual((r.status, r.read()), (200, b""))
        self.assertEqual(s.connections, 1)          # the 404's body was read, so its connection was kept

    def test_a_dropped_connection_is_sent_again(self):
        s = self.server(drop=True)
        ka = self.ka()
        for _ in range(3):
            with ka(f"{s.url}/a.bin", timeout=5) as r:
                self.assertEqual(len(r.read()), 1024)
        self.assertEqual((s.connections, ka.retried), (3, 2))

    def test_after_a_pause_one_request_still_succeeds(self):
        # four kept connections, all closed by the server while idle: the request fails once on one of them, is sent
        # again on a new connection, and the other three are dropped instead of being tried in turn
        s = self.server(idle=0.3)
        ka = self.ka()
        self.keep(ka, s, 4)
        time.sleep(1.0)
        with ka(f"{s.url}/a.bin", timeout=5) as r:
            self.assertEqual(len(r.read()), 1024)
        self.assertEqual((ka.retried, s.connections, sum(ka.idle().values())), (1, 5, 1))
        with ka(f"{s.url}/a.bin", timeout=5) as r:             # and the new one is kept and used
            self.assertEqual(len(r.read()), 1024)
        self.assertEqual((ka.retried, s.connections), (1, 5))

    def test_a_post_on_a_closed_kept_connection_is_not_sent_again(self):
        s = self.server(idle=0.3)
        ka = self.ka()
        self.keep(ka, s, 3)
        time.sleep(1.0)
        with self.assertRaises(keepalive.STALE):
            ka(urllib.request.Request(f"{s.url}/a.bin", data=b"x", method="POST"), timeout=5)
        self.assertEqual((ka.retried, ka.idle(), s.connections), (0, {}, 3))

    def test_a_new_connection_that_fails_is_not_sent_again(self):
        url, accepted = self.closing_server()
        ka = self.ka()
        with self.assertRaises(keepalive.STALE):
            ka(f"{url}/a.bin", timeout=5)
        self.assertEqual((ka.opened, ka.retried, accepted[0]), (1, 0, 1))

    def keep(self, ka, s, n):
        """n connections that have each answered one request, kept in ka's pool for s."""
        route = ka._route(urllib.parse.urlsplit(s.url))
        for _ in range(n):
            conn = ka._new(route, 5)
            conn.request("GET", "/a.bin")
            conn.getresponse().read()
            ka._give(route, conn)
        self.assertEqual(sum(ka.idle().values()), n)

    def closing_server(self):
        """A server that reads each request and closes the connection without answering; (url, [connections])."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        accepted = [0]

        def run():
            while True:
                try:
                    c, _ = srv.accept()
                except OSError:
                    return
                accepted[0] += 1
                with c:
                    data = b""
                    while b"\r\n\r\n" not in data:
                        chunk = c.recv(4096)
                        if not chunk:
                            break
                        data += chunk

        threading.Thread(target=run, daemon=True).start()
        self.addCleanup(srv.close)
        return f"http://127.0.0.1:{srv.getsockname()[1]}", accepted

    def test_threads_and_the_idle_limit(self):
        s = self.server()
        ka = self.ka(max_idle=2)
        barrier = threading.Barrier(4)

        def one():
            barrier.wait()
            with ka(f"{s.url}/a.bin", timeout=5) as r:
                return len(r.read())

        th = [threading.Thread(target=one) for _ in range(4)]
        for t in th:
            t.start()
        for t in th:
            t.join()
        self.assertLessEqual(sum(ka.idle().values()), 2)
        ka.close()
        self.assertEqual(ka.idle(), {})

    def test_routes(self):
        ka = keepalive.KeepAlive(proxies={"https": "http://user:pw@proxy:3128", "http": "http://proxy:3128"})
        split = urllib.parse.urlsplit
        self.assertEqual(ka._route(split("https://b.s3.amazonaws.com/k")),
                         ("https", "b.s3.amazonaws.com", 443, "http://user:pw@proxy:3128"))
        self.assertIsNone(ka._route(split("http://example.org/k")))      # plain http through a proxy: urllib
        self.assertIsNone(ka._route(split("ftp://example.org/k")))
        self.assertEqual(self.ka()._route(split("http://h:8/k")), ("http", "h", 8, None))

    def test_store_uses_it_and_the_switch(self):
        s = self.server()
        store = vc3d_audit.HttpStore(s.url, rate=0, opener=self.ka())
        self.assertEqual(store.read("a.bin", 4, 4), bytes(range(4, 8)))
        self.assertIsNone(store.read("nothing"))
        self.assertEqual(store.read("a.bin", -2), bytes([254, 255]))
        self.assertEqual(s.connections, 1)
        old = os.environ.get("KIT_HTTP_REUSE")
        try:
            os.environ["KIT_HTTP_REUSE"] = "0"
            self.assertIs(keepalive.default_opener(), urllib.request.urlopen)
            os.environ["KIT_HTTP_REUSE"] = "1"
            self.assertIsInstance(keepalive.default_opener(), keepalive.KeepAlive)
            self.assertIsInstance(vc3d_audit.HttpStore(s.url).opener, keepalive.KeepAlive)
        finally:
            if old is None:
                os.environ.pop("KIT_HTTP_REUSE", None)
            else:
                os.environ["KIT_HTTP_REUSE"] = old


def value(z, y, x):
    return (3 * z + 5 * y + 7 * x) % 251


def write_sharded(path, shape=(40, 40, 40), shard=(16, 16, 16), inner=(8, 8, 8), empty=(), bad_crc=False,
                  dtype="uint8"):
    """A sharded zarr v3 array (gzip inner chunks, index at the end with its CRC32C); `empty` inner chunks are left
    out. The grid does not divide the shape, so edge shards and edge inner chunks are partial."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    (p / "zarr.json").write_text(json.dumps({
        "zarr_format": 3, "node_type": "array", "shape": list(shape), "data_type": dtype,
        "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": list(shard)}},
        "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}}, "fill_value": 0,
        "codecs": [{"name": "sharding_indexed", "configuration": {
            "chunk_shape": list(inner), "codecs": [{"name": "bytes", "configuration": {"endian": "little"}},
                                                   {"name": "gzip", "configuration": {"level": 1}}],
            "index_codecs": [{"name": "bytes", "configuration": {"endian": "little"}}, {"name": "crc32c"}],
            "index_location": "end"}}]}))
    per = [s // i for s, i in zip(shard, inner)]
    grid = [-(-n // s) for n, s in zip(shape, shard)]
    zz, yy, xx = np.indices(inner)
    for sz in range(grid[0]):
        for sy in range(grid[1]):
            for sx in range(grid[2]):
                body, index = b"", []
                for lz in range(per[0]):
                    for ly in range(per[1]):
                        for lx in range(per[2]):
                            idx = (sz * per[0] + lz, sy * per[1] + ly, sx * per[2] + lx)
                            if idx in empty or any(i * c >= n for i, c, n in zip(idx, inner, shape)):
                                index += [vc3d_audit.EMPTY, vc3d_audit.EMPTY]
                                continue
                            v = value(zz + idx[0] * inner[0], yy + idx[1] * inner[1], xx + idx[2] * inner[2])
                            blob = gzip.compress(v.astype("<" + np.dtype(dtype).str[1:]).tobytes(), 1)
                            body += b"pad" * (lx % 2)             # gaps between inner chunks, as writers leave
                            index += [len(body), len(blob)]
                            body += blob
                idx_bytes = struct.pack(f"<{len(index)}Q", *index)
                crc = vc3d_region.crc32c(idx_bytes) ^ (1 if bad_crc else 0)
                out = p / "c" / str(sz) / str(sy) / str(sx)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(body + idx_bytes + struct.pack("<I", crc))
    return p


def truth(box, shape, empty=(), inner=(8, 8, 8)):
    (z0, z1), (y0, y1), (x0, x1) = box
    zz, yy, xx = np.meshgrid(np.arange(z0, z1), np.arange(y0, y1), np.arange(x0, x1), indexing="ij")
    v = value(zz, yy, xx).astype(np.int64)
    out = np.where((zz < shape[0]) & (yy < shape[1]) & (xx < shape[2]) & (zz >= 0) & (yy >= 0) & (xx >= 0), v, 0)
    for e in empty:
        m = ((zz // inner[0] == e[0]) & (yy // inner[1] == e[1]) & (xx // inner[2] == e[2]))
        out[m] = 0
    return out


@unittest.skipIf(np is None, "needs numpy")
class ShardedTest(Base):
    def test_crc32c_and_merge(self):
        self.assertEqual(vc3d_region.crc32c(b"123456789"), 0xE3069283)   # the CRC-32C check value
        items = [(0, 10, "a"), (12, 10, "b"), (100, 10, "c"), (2 << 20, 10, "d")]
        self.assertEqual([(s, n, [m[2] for m in ms]) for s, n, ms in vc3d_region.merge_ranges(items, gap=2)],
                         [(0, 22, ["a", "b"]), (100, 10, ["c"]), (2 << 20, 10, ["d"])])
        self.assertEqual(len(vc3d_region.merge_ranges(items, gap=200)), 2)        # the span limit splits d off
        self.assertEqual(len(vc3d_region.merge_ranges(items, gap=200, span=50)), 3)
        self.assertEqual(len(vc3d_region.merge_ranges(items, gap=-1)), 4)

    def test_local_reads_match_the_values_written(self):
        shape, empty = (40, 40, 40), {(1, 2, 0), (4, 4, 4)}
        arr = write_sharded(self.d / "s.zarr", shape=shape, empty=empty)
        vol = vc3d_region.Volume(str(arr))
        for box in ([[0, 40], [0, 40], [0, 40]], [[5, 21], [13, 30], [-3, 9]], [[33, 45], [30, 41], [38, 40]]):
            got = vol.read(0, box)
            self.assertTrue(np.array_equal(got.astype(np.int64), truth(box, shape, empty)), box)
        self.assertEqual(vol.missing, 2)
        pts = np.array([[3.5, 4.25, 6.0]])
        self.assertAlmostEqual(float(vol.sample(0, pts)[0]),
                               float(0.5 * (value(6, 4, 3) + value(6, 4, 4)) * 0.75
                                     + 0.5 * (value(6, 5, 3) + value(6, 5, 4)) * 0.25), places=6)

    def test_uint16_reads(self):
        arr = write_sharded(self.d / "u.zarr", shape=(16, 16, 16), dtype="uint16")
        got = vc3d_region.Volume(str(arr)).read(0, [[0, 16], [0, 16], [0, 16]])
        self.assertEqual(got.dtype.itemsize, 2)
        self.assertTrue(np.array_equal(got.astype(np.int64), truth([[0, 16], [0, 16], [0, 16]], (16, 16, 16))))

    def test_merged_reads_over_http_match_and_use_fewer_requests(self):
        shape, empty = (40, 40, 40), {(1, 2, 0)}
        write_sharded(self.d / "s.zarr", shape=shape, empty=empty)
        s = self.server()
        box = [[0, 32], [0, 32], [0, 32]]
        res = {}
        for coalesce in (True, False):
            s.hits.clear()
            vol = vc3d_region.Volume(f"{s.url}/s.zarr", rate=0, opener=self.ka(),
                                     coalesce=coalesce)
            got = vol.read(0, box)
            self.assertTrue(np.array_equal(got.astype(np.int64), truth(box, shape, empty)), coalesce)
            res[coalesce] = (vol.range_reads, len([h for h in s.hits if h[2] and not h[2].startswith("bytes=-")]))
            self.assertEqual(vol.missing, 1)
        self.assertEqual(res[False], (63, 63))      # 64 inner chunks in 8 shards, one absent
        self.assertEqual(res[True], (8, 8))         # one merged read per shard
        self.assertEqual(vc3d_region.Volume(f"{s.url}/s.zarr", opener=self.ka()).store.rate, 0)   # box reads: no pace
        self.assertEqual(vc3d_region.Volume(f"{s.url}/s.zarr", opener=self.ka(), rate=5).store.rate, 5)
        again = vc3d_region.Volume(f"{s.url}/s.zarr", rate=0, opener=self.ka())
        again.read(0, box)
        n = len(s.hits)
        again.read(0, box)
        self.assertEqual(len(s.hits), n)            # indexes and inner chunks come from the cache

    def test_failures(self):
        arr = write_sharded(self.d / "bad.zarr", shape=(16, 16, 16), bad_crc=True)
        with self.assertRaisesRegex(vc3d_region.RegionError, "CRC32C"):
            vc3d_region.Volume(str(arr)).read(0, [[0, 8], [0, 8], [0, 8]])
        arr = write_sharded(self.d / "cut.zarr", shape=(16, 16, 16))
        f = arr / "c" / "0" / "0" / "0"
        data = f.read_bytes()
        idx = data[-(16 * 8 + 4):]
        off, n = struct.unpack("<2Q", idx[16 * 7:16 * 8])
        f.write_bytes(data[:off + n // 2] + idx)                    # the last inner chunk cut short
        vol = vc3d_region.Volume(str(arr))
        with self.assertRaises(vc3d_region.RegionError):
            vol.read(0, [[8, 16], [8, 16], [8, 16]])
        missing = vc3d_region.Volume(str(write_sharded(self.d / "m.zarr", shape=(16, 16, 16))))
        (self.d / "m.zarr" / "c" / "0" / "0" / "0").unlink()
        self.assertEqual(int(missing.read(0, [[0, 16], [0, 16], [0, 16]]).max()), 0)
        self.assertEqual(missing.missing, 8)


if __name__ == "__main__":
    unittest.main()
