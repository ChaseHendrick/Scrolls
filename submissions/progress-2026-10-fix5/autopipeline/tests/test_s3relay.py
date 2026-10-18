"""The local relay that keeps false 404s from VC3D (kit/s3relay.py)."""

import socket
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes as fakes  # noqa: E402

from kit import s3relay  # noqa: E402


def get(url, method="GET", headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with fakes.no_proxy_opener()(req, timeout=30) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


class TestUrls(unittest.TestCase):
    def test_origins_and_ports(self):
        self.assertEqual(s3relay.origin_of("s3://bucket/a/b.zarr"), ("https://bucket.s3.amazonaws.com", "/a/b.zarr"))
        self.assertEqual(s3relay.origin_of("https://h.example:8443/a?x=1"), ("https://h.example:8443", "/a"))
        with self.assertRaises(s3relay.RelayError):
            s3relay.origin_of("/local/path.zarr")
        ports = s3relay.preferred_ports("https://h.example")
        self.assertEqual((len(ports), ports[1] - ports[0]), (16, 1))
        self.assertTrue(all(20000 <= p < 40016 for p in ports))
        urls = s3relay.candidate_urls("https://h.example/v/x.zarr")
        self.assertEqual(urls[0], f"http://127.0.0.1:{ports[0]}/v/x.zarr")


class TestRelay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "v").mkdir()
        (self.d / "v" / "k").write_bytes(bytes(range(100)))

    def tearDown(self):
        self.tmp.cleanup()

    def relay(self, upstream, **kw):
        return s3relay.Relay(upstream, opener=fakes.no_proxy_opener(), sleep=lambda s: None, **kw)

    def test_false_404s_never_reach_the_client(self):
        with fakes.S3LikeServer(self.d, false=2, always_false={"v/bad"}) as srv, self.relay(srv.url) as relay:
            base = relay.url_for(srv.url + "/v")
            self.assertTrue(base.startswith("http://127.0.0.1:") and base.endswith("/v"))
            self.assertEqual(get(base + "/k")[::2], (200, bytes(range(100))))
            status, hdrs, body = get(base + "/k", headers={"Range": "bytes=10-19"})
            self.assertEqual((status, body, hdrs["Content-Range"]), (206, bytes(range(10, 20)), "bytes 10-19/100"))
            status, hdrs, body = get(base + "/k", method="HEAD")
            self.assertEqual((status, hdrs["Content-Length"], body), (200, "100", b""))
            status, _, body = get(base + "/gone")
            self.assertEqual((status, b"NoSuchKey" in body), (404, True))
            self.assertEqual(get(base + "/gone", method="HEAD")[0], 404)
            self.assertEqual(get(base + "/bad")[0], 503)          # VC3D retries a 503 and then fails loudly
            st = relay.stats
            self.assertEqual((st["gave_up"], st["missing"]), (1, 2))
            self.assertGreaterEqual(st["false_404"], 2)
            with self.assertRaises(s3relay.RelayError):
                relay.url_for("https://other.example/v")

    def test_upstream_down_is_a_502(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with self.relay(f"http://127.0.0.1:{port}") as relay:
            self.assertEqual(get(relay.base + "/k")[0], 502)
            self.assertEqual(relay.stats["network_errors"], s3relay.NETWORK_TRIES)

    def test_a_second_relay_for_one_origin_takes_the_next_port(self):
        with fakes.S3LikeServer(self.d) as srv, self.relay(srv.url) as a, self.relay(srv.url) as b:
            ports = s3relay.preferred_ports(a.origin)
            self.assertNotEqual(a.port, b.port)
            self.assertTrue(a.port in ports + [a.port] and b.port in ports + [b.port])
        self.assertIsNone(a.server)


if __name__ == "__main__":
    unittest.main()
