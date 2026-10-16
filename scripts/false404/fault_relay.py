"""A local relay in front of an S3 bucket that gives chosen chunk GETs the false 404 S3 once sent us, so the
false-404 bug in villa (ScrollPrize/villa#2058) can be shown on real scroll data on demand.

What S3 sent (ScrollPrize/villa#2058; docs/logs/2026-10-12-upstream-reports.md): HTTP 404 with S3's own
headers (`Server: AmazonS3`, an `x-amz-request-id`) and the body `<Error><Code>NoSuchBucket</Code>...` for keys
the bucket holds, on some new connections. It cannot be had on demand, so this relay plays it back: a chunk key is chosen when the SHA-256 of
`seed:path` falls below `rate`, and its first `bad` GETs get that answer. Everything else, HEAD included (S3 never
failed a HEAD for us), goes to the bucket and comes back with the bucket's status, headers and body. A false 404
the bucket itself sends is asked again on a new connection (up to 10 times) and never reaches the client, so the
only false 404s a client sees are the chosen ones, logged one per line.

  python3 scripts/false404/fault_relay.py --rate 0.3 --seed 1 --bad 1 --log relay.jsonl
  # then give VC3D http://127.0.0.1:PORT/<bucket path> instead of the bucket URL

Chunk keys are paths whose last part is digits (`0/12/3/4`, `0/12.3.4`); metadata keys are never chosen, so the
volume always opens. Standard library.
"""
import argparse
import hashlib
import http.client
import http.server
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "proxy-connection", "te", "trailer",
       "upgrade"}
UPSTREAM_TRIES = 10
CHUNK = re.compile(r"\d+(\.\d+)*")


def is_chunk(path):
    """True for a zarr chunk key (last path part digits, dot-separated or not), False for metadata."""
    last = urllib.parse.urlsplit(path).path.rsplit("/", 1)[-1]
    return bool(CHUNK.fullmatch(last))


def chosen(path, seed, rate):
    """Is this chunk key one whose first GETs get the false 404? Fixed by seed and path alone."""
    if rate <= 0 or not is_chunk(path):
        return False
    h = hashlib.sha256(f"{seed}:{urllib.parse.urlsplit(path).path}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64 < rate


def s3_code(body):
    m = re.search(rb"<Code>([^<]*)</Code>", body or b"")
    return m.group(1).decode("ascii", "replace") if m else None


def false_404(path, n, bucket):
    """(headers, body) of the answer S3 gave us: 404 NoSuchBucket with S3's headers. n numbers the answer."""
    rid = hashlib.sha256(f"{path}:{n}".encode()).hexdigest()[:16].upper()
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<Error><Code>NoSuchBucket</Code>'
            f"<Message>The specified bucket does not exist</Message><BucketName>{bucket}</BucketName>"
            f"<RequestId>{rid}</RequestId><HostId>fault-relay</HostId></Error>").encode()
    headers = {"Content-Type": "application/xml", "Server": "AmazonS3", "x-amz-request-id": rid,
               "x-amz-id-2": "fault-relay", "Date": time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())}
    return headers, body


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "fault-relay"

    def do_GET(self):   # noqa: N802 - http.server's naming
        self._answer("GET")

    def do_HEAD(self):  # noqa: N802
        self._answer("HEAD")

    def _answer(self, method):
        status, headers, body = self.server.relay.answer(method, self.path, self.headers.get("Range"))
        try:
            # send_response would add the relay's own Server and Date beside the bucket's (or the false 404's)
            self.send_response_only(status)
            names = {k.lower() for k in headers}
            if "server" not in names:
                self.send_header("Server", self.version_string())
            if "date" not in names:
                self.send_header("Date", self.date_time_string())
            for k, v in headers.items():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            if method == "HEAD" and "Content-Length" in headers:
                self.send_header("Content-Length", headers["Content-Length"])
            else:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if method == "GET" and body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        pass


class Relay:
    """One relay on 127.0.0.1. Use as a context manager; .base is its URL, .stats its counts."""

    def __init__(self, upstream=BUCKET, rate=0.0, seed=1, bad=1, log=None, port=0, timeout=60, opener=None,
                 sleep=time.sleep):
        u = urllib.parse.urlsplit(upstream)
        if u.scheme not in ("http", "https") or not u.netloc:
            raise ValueError(f"not an http(s) origin: {upstream}")
        self.origin = f"{u.scheme}://{u.netloc}"
        self.bucket = u.netloc.split(".")[0]
        self.rate, self.seed, self.bad, self.port, self.timeout = float(rate), seed, int(bad), port, timeout
        self.opener, self.sleep = opener or urllib.request.urlopen, sleep
        self.log = open(log, "a") if log else None
        self.gets = {}
        self.lock = threading.Lock()
        self.stats = {"requests": 0, "injected": 0, "injected_keys": 0, "upstream_false_404": 0,
                      "upstream_404": 0, "upstream_errors": 0}
        self.server = self.thread = None

    def __enter__(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        self.server.daemon_threads = True
        self.server.relay = self
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, name="fault-relay", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        if self.log:
            self.log.close()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    def url_for(self, url):
        """The relay URL standing for an upstream URL."""
        u = urllib.parse.urlsplit(url)
        if f"{u.scheme}://{u.netloc}" != self.origin:
            raise ValueError(f"{url} is not under {self.origin}")
        return self.base + (u.path or "/")

    def _note(self, rec):
        with self.lock:
            if self.log:
                self.log.write(json.dumps(rec) + "\n")
                self.log.flush()

    def answer(self, method, path, rng=None):
        """(status, headers, body) for one request."""
        with self.lock:
            self.stats["requests"] += 1
            n = None
            if method == "GET" and chosen(path, self.seed, self.rate):
                key = urllib.parse.urlsplit(path).path         # one count per chunk key, whatever the query string
                n = self.gets.get(key, 0)
                self.gets[key] = n + 1
                if n == 0:
                    self.stats["injected_keys"] += 1
                if n < self.bad:
                    self.stats["injected"] += 1
        rec = {"t": round(time.time(), 3), "method": method, "path": path, "range": rng}
        if n is not None and n < self.bad:
            headers, body = false_404(path, n, self.bucket)
            self._note({**rec, "status": 404, "injected": True, "get": n + 1})
            return 404, headers, body
        status, headers, body = self._upstream(method, path, rng)
        self._note({**rec, "status": status, "injected": False, "get": None if n is None else n + 1})
        return status, headers, body

    def _count(self, key):
        with self.lock:
            self.stats[key] += 1

    def _upstream(self, method, path, rng):
        headers = {"User-Agent": "fault-relay"}
        if rng:
            headers["Range"] = rng
        for attempt in range(UPSTREAM_TRIES):
            req = urllib.request.Request(self.origin + path, method=method, headers=headers)
            try:
                with self.opener(req, timeout=self.timeout) as resp:
                    body = resp.read() if method == "GET" else b""
                    return resp.status, dict(resp.headers.items()), body
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read() or b""
                except (OSError, http.client.HTTPException):
                    body = None
                hdrs = dict(exc.headers.items()) if exc.headers else {}
                exc.close()
                if body is None or (exc.code == 404 and method == "GET" and s3_code(body) not in ("NoSuchKey", None)):
                    self._count("upstream_false_404" if body is not None else "upstream_errors")
                    self.sleep(min(2.0, 0.1 * 2 ** attempt))
                    continue
                if exc.code == 404:
                    self._count("upstream_404")
                return exc.code, hdrs, body
            except (urllib.error.URLError, OSError, http.client.HTTPException):
                self._count("upstream_errors")
                self.sleep(min(4.0, 0.25 * 2 ** attempt))
        return 502, {"Content-Type": "text/plain"}, b"fault-relay: the bucket did not answer\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upstream", default=BUCKET)
    ap.add_argument("--rate", type=float, default=0.3, help="share of chunk keys given false 404s")
    ap.add_argument("--seed", default="1")
    ap.add_argument("--bad", type=int, default=1, help="false 404s per chosen key before the real answer")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--log", help="one JSON line per request")
    args = ap.parse_args(argv)
    with Relay(args.upstream, args.rate, args.seed, args.bad, args.log, args.port) as relay:
        print(json.dumps({"relay": relay.base, "upstream": relay.origin, "rate": relay.rate, "seed": relay.seed,
                          "bad": relay.bad}), flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        print(json.dumps(relay.stats), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
