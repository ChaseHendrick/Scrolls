"""The fault relay that replays S3's false 404 for the villa false-404 PR (scripts/false404/fault_relay.py)."""
import collections
import http.server
import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fault_relay", ROOT / "scripts/false404/fault_relay.py")
fr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fr)


class S3LikeServer:
    """A local HTTP server over a folder that answers like S3. A missing key gets 404 with <Code>NoSuchKey</Code>;
    the first `false` requests for each key get 404 with <Code>NoSuchBucket</Code>, the answer S3 sent for keys it
    holds (ScrollPrize/villa#2058). Range and HEAD work. .url is the base URL, .hits counts requests per key."""

    def __init__(self, root, false=1):
        self.root, self.false = Path(root), false
        self.hits = collections.Counter()
        lock = threading.Lock()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _error(self, s3code, head):
                body = b"" if head else (f"<?xml version=\"1.0\"?><Error><Code>{s3code}</Code>"
                                         f"<Message>test</Message></Error>").encode()
                self.send_response(404)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _serve(self, head):
                key = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip("/")
                with lock:
                    n = outer.hits[key]
                    outer.hits[key] += 1
                if n < outer.false:
                    return self._error("NoSuchBucket", head)
                f = outer.root / key
                if not f.is_file():
                    return self._error("NoSuchKey", head)
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

    def __enter__(self):
        # A short poll interval so shutdown() returns at once instead of after up to half a second.
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def get(url, method="GET", rng=None):
    req = urllib.request.Request(url, method=method, headers={"Range": rng} if rng else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        body = e.read()
        e.close()
        return e.code, dict(e.headers.items()), body


class TestChoice(unittest.TestCase):
    def test_chunk_keys_only(self):
        for p in ("/v.zarr/0/12/3/4", "/v.zarr/0/12.3.4", "/v.zarr/0/c/1/2/3"):
            self.assertTrue(fr.is_chunk(p), p)
        for p in ("/v.zarr/0/.zarray", "/v.zarr/.zattrs", "/v.zarr/zarr.json", "/v.zarr/meta.json", "/v.zarr/0/"):
            self.assertFalse(fr.is_chunk(p), p)
        self.assertFalse(fr.chosen("/v.zarr/0/.zarray", 1, 1.0))

    def test_choice_is_fixed_and_near_rate(self):
        keys = [f"/v.zarr/0/{z}/{y}/{x}" for z in range(10) for y in range(10) for x in range(10)]
        a = [fr.chosen(k, 7, 0.3) for k in keys]
        self.assertEqual(a, [fr.chosen(k, 7, 0.3) for k in keys])
        self.assertTrue(250 <= sum(a) <= 350, sum(a))
        self.assertNotEqual(a, [fr.chosen(k, 8, 0.3) for k in keys])
        self.assertEqual(sum(fr.chosen(k, 7, 0.0) for k in keys), 0)
        self.assertEqual(sum(fr.chosen(k, 7, 1.0) for k in keys), 1000)


class TestRelay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "bucket"
        (root / "v.zarr/0/0/0").mkdir(parents=True)
        (root / "v.zarr/0/.zarray").write_text("{}")
        for x in range(4):
            (root / f"v.zarr/0/0/0/{x}").write_bytes(bytes([x]) * 64)
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def test_chosen_key_gets_s3s_false_404_then_the_data(self):
        log = Path(self.tmp.name) / "relay.jsonl"
        with S3LikeServer(self.root, false=0) as up, fr.Relay(up.url, rate=1.0, seed=1, bad=2, log=log) as relay:
            url = relay.base + "/v.zarr/0/0/0/1"
            for n in range(2):
                status, headers, body = get(url)
                self.assertEqual(status, 404)
                self.assertEqual(headers.get("Server"), "AmazonS3")
                self.assertTrue(headers.get("x-amz-request-id"))
                self.assertEqual(fr.s3_code(body), "NoSuchBucket")
            status, _, body = get(url)
            self.assertEqual((status, body), (200, bytes([1]) * 64))
            status, _, body = get(url, rng="bytes=0-3")
            self.assertEqual((status, body), (206, bytes([1]) * 4))
            # metadata is never chosen; HEAD always goes to the bucket
            self.assertEqual(get(relay.base + "/v.zarr/0/.zarray")[0], 200)
            self.assertEqual(get(relay.base + "/v.zarr/0/0/0/2", method="HEAD")[0], 200)
            self.assertEqual(relay.stats["injected"], 2)
            self.assertEqual(relay.stats["injected_keys"], 1)
        lines = [json.loads(s) for s in log.read_text().splitlines()]
        self.assertEqual([r["injected"] for r in lines[:3]], [True, True, False])
        self.assertEqual([r["get"] for r in lines[:3]], [1, 2, 3])

    def test_a_query_string_does_not_make_a_new_key(self):
        with S3LikeServer(self.root, false=0) as up, fr.Relay(up.url, rate=1.0, seed=1, bad=1) as relay:
            url = relay.base + "/v.zarr/0/0/0/1"
            self.assertEqual(get(url + "?x-id=GetObject")[0], 404)      # the key's one false 404
            self.assertEqual(get(url + "?x-id=GetObject&n=2")[:3:2], (200, bytes([1]) * 64))
            self.assertEqual(get(url)[0], 200)
            self.assertEqual((relay.stats["injected"], relay.stats["injected_keys"]), (1, 1))

    def test_one_server_and_one_date_header(self):
        def headers(url):
            try:
                with urllib.request.urlopen(url, timeout=10) as r:
                    return r.status, r.headers
            except urllib.error.HTTPError as e:
                e.read()
                e.close()
                return e.code, e.headers
        with S3LikeServer(self.root, false=0) as up, fr.Relay(up.url, rate=1.0, seed=1, bad=1) as relay:
            for want in (404, 200):                   # the replayed false 404, then the bucket's own answer
                status, h = headers(relay.base + "/v.zarr/0/0/0/1")
                self.assertEqual(status, want)
                self.assertEqual(len(h.get_all("Server")), 1, h.get_all("Server"))
                self.assertEqual(len(h.get_all("Date")), 1, h.get_all("Date"))
                if want == 404:
                    self.assertEqual(h["Server"], "AmazonS3")

    def test_rate_zero_passes_everything_and_true_misses(self):
        with S3LikeServer(self.root, false=0) as up, fr.Relay(up.url, rate=0.0) as relay:
            for x in range(4):
                self.assertEqual(get(relay.base + f"/v.zarr/0/0/0/{x}")[2], bytes([x]) * 64)
            status, _, body = get(relay.base + "/v.zarr/0/0/0/9")
            self.assertEqual((status, fr.s3_code(body)), (404, "NoSuchKey"))
            self.assertEqual(relay.stats["injected"], 0)
            self.assertEqual(relay.stats["upstream_404"], 1)

    def test_bucket_false_404_never_reaches_the_client(self):
        with S3LikeServer(self.root, false=3) as up, fr.Relay(up.url, rate=0.0, sleep=lambda s: None) as relay:
            status, _, body = get(relay.base + "/v.zarr/0/0/0/3")
            self.assertEqual((status, body), (200, bytes([3]) * 64))
            self.assertEqual(relay.stats["upstream_false_404"], 3)

    def test_url_for_keeps_the_path(self):
        with S3LikeServer(self.root) as up, fr.Relay(up.url) as relay:
            self.assertEqual(relay.url_for(up.url + "/v.zarr/"), relay.base + "/v.zarr/")
            with self.assertRaises(ValueError):
                relay.url_for("https://elsewhere.example/v.zarr/")


if __name__ == "__main__":
    unittest.main()
