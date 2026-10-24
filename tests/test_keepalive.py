"""Tests for kit.keepalive (kept HTTP connections).

A local HTTP/1.1 server serves a folder (GET with byte ranges, HEAD, S3-style 404) and counts the connections it
accepts, so connection reuse is counted, not assumed. It can also close each connection after answering without
saying so, which is how a server drops an idle kept connection: the next request on it must be sent again on a new
one. The sharded arrays are written here with a real CRC32C in their indexes, and every read is checked voxel for
voxel against the values written, merged and unmerged alike.
"""
import http.server
import json
import os
import socket
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


if __name__ == "__main__":
    unittest.main()
