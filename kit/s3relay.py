"""A local relay between VC3D and a remote zarr, so that VC3D never sees a false 404.

VC3D takes any 404 for a missing key: a chunk becomes an empty marker in its persistent cache (read as zeros by
every later run), and a metadata key makes the volume fail to open. From this cloud S3 answers 404 NoSuchBucket
for keys it holds (kit/s3retry.py), so the kit runs this relay on 127.0.0.1 while a VC3D tool reads a remote
volume, and gives the tool the relay's URL. A false 404 is asked again on a new connection; a 404 reaches VC3D
only when S3 says NoSuchKey (or names no code); a key that keeps answering false 404s reaches VC3D as 503, which
VC3D retries and then reports as an error, never as a hole.

The port is chosen from the upstream origin (20000 + FNV-1a % 20000, then the next few), so repeated runs give
VC3D the same URL and reuse one cache folder; a second relay for the same origin running at the same time takes
another port and a cold cache. Standard library.
"""

import http.client
import http.server
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import s3retry

PASS_HEADERS = ("Content-Type", "Content-Range", "ETag", "Last-Modified", "Accept-Ranges", "Content-Encoding")
NETWORK_TRIES = 4


class RelayError(OSError):
    pass


def _fnv1a64(text):
    h = 0xCBF29CE484222325
    for b in text.encode("utf-8"):
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def origin_of(url):
    """(origin, path) of an http(s) or s3:// URL; s3:// becomes the bucket's anonymous https origin."""
    url = str(url)
    if url.lower().startswith("s3://"):
        bucket, _, key = url[5:].partition("/")
        return f"https://{bucket}.s3.amazonaws.com", "/" + key
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise RelayError(f"not an http(s) or s3 URL: {url}")
    return f"{u.scheme}://{u.netloc}", u.path or "/"


def preferred_ports(origin, n=16):
    """The ports a relay for this origin tries first, in order."""
    pref = 20000 + _fnv1a64(origin) % 20000
    return [pref + k for k in range(n)]


def candidate_urls(url, host="127.0.0.1"):
    """Every URL a relay for url's origin may have given VC3D, so a cache folder made through a relay can be
    traced back to its volume."""
    origin, path = origin_of(url)
    return [f"http://{host}:{port}{path}" for port in preferred_ports(origin)]


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "kit-s3relay"

    def do_GET(self):   # noqa: N802 - http.server's naming
        self._relay("GET")

    def do_HEAD(self):  # noqa: N802
        self._relay("HEAD")

    def _relay(self, method):
        relay = self.server.relay
        headers = {"User-Agent": "kit-s3relay"}
        if self.headers.get("Range"):
            headers["Range"] = self.headers["Range"]
        status, hdrs, body = relay.fetch(relay.origin + self.path, method, headers)
        # Header names are case-insensitive: a proxy or an HTTP/2 hop sends "etag", not "ETag"
        hdrs = {k.lower(): v for k, v in hdrs.items()}
        try:
            self.send_response(status)
            for k in PASS_HEADERS:
                if hdrs.get(k.lower()):
                    self.send_header(k, hdrs[k.lower()])
            length = hdrs.get("content-length") if method == "HEAD" and status in (200, 206) else None
            self.send_header("Content-Length", str(length if length is not None else len(body)))
            self.end_headers()
            if method == "GET" and body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        pass


class Relay:
    """One relay for one upstream origin. Use as a context manager, or start() and stop()."""

    def __init__(self, upstream, port=None, tries=s3retry.TRIES, timeout=60, opener=None, sleep=time.sleep,
                 host="127.0.0.1"):
        self.origin, _ = origin_of(upstream)
        self.tries, self.timeout, self.sleep, self.host = max(1, tries), timeout, sleep, host
        self.opener = opener or urllib.request.urlopen
        self.port = port
        self.server = None
        self.thread = None
        self._lock = threading.Lock()
        self.stats = {"requests": 0, "false_404": 0, "missing": 0, "gave_up": 0, "network_errors": 0}

    # ---------------------------------------------------------------- lifecycle

    def start(self):
        ports = [self.port] if self.port is not None else preferred_ports(self.origin) + [0]
        last = None
        for port in ports:
            try:
                server = http.server.ThreadingHTTPServer((self.host, port), _Handler)
            except OSError as exc:
                last = exc
                continue
            server.daemon_threads = True
            server.relay = self
            self.server, self.port = server, server.server_address[1]
            self.thread = threading.Thread(target=server.serve_forever, name="kit-s3relay", daemon=True)
            self.thread.start()
            return self
        raise RelayError(f"cannot listen on {self.host}: {last}")

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    @property
    def base(self):
        return f"http://{self.host}:{self.port}"

    def url_for(self, url):
        """The relay URL that stands for an upstream URL of this origin."""
        origin, path = origin_of(url)
        if origin != self.origin:
            raise RelayError(f"{url} is not under {self.origin}")
        return self.base + path

    # ---------------------------------------------------------------- upstream

    def _count(self, key):
        with self._lock:
            self.stats[key] += 1

    def _network_failure(self, exc, failed):
        """Count one network failure: (failed + 1, the 502 to answer once NETWORK_TRIES are used up, or None after
        a pause before the next try)."""
        self._count("network_errors")
        failed += 1
        if failed >= NETWORK_TRIES:
            return failed, (502, {"Content-Type": "text/plain"}, f"kit-s3relay: {exc}\n".encode())
        self.sleep(min(8.0, 0.5 * 2 ** failed))
        return failed, None

    def fetch(self, url, method="GET", headers=None):
        """(status, headers, body) as VC3D should see them."""
        self._count("requests")
        false = failed = 0
        while True:
            req = urllib.request.Request(url, method=method, headers=headers or {})
            try:
                with self.opener(req, timeout=self.timeout) as resp:
                    body = resp.read() if method == "GET" else b""
                    return resp.status, dict(resp.headers.items()), body
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read() or b""
                except (OSError, http.client.HTTPException) as cut:
                    # An error body cut off mid-read is a network failure, retried as one. Read as empty, a cut-off
                    # false 404 would name no S3 code and reach VC3D as missing, which this relay exists to stop
                    exc.close()
                    failed, gave_up = self._network_failure(cut, failed)
                    if gave_up:
                        return gave_up
                    continue
                hdrs = dict(exc.headers.items()) if exc.headers else {}
                exc.close()
                if exc.code == 404:
                    if method == "HEAD":
                        state, _ = s3retry.key_state(url, self.opener, self.timeout, self.tries, self.sleep)
                        if state == s3retry.MISSING:
                            self._count("missing")
                            return 404, hdrs, b""
                        if state == s3retry.PRESENT and false + 1 < self.tries:
                            self._count("false_404")
                            false += 1
                            continue
                        self._count("gave_up")
                        return 503, {}, b""
                    if not s3retry.false_404(404, body):
                        self._count("missing")
                        return 404, hdrs, body
                    self._count("false_404")
                    false += 1
                    if false >= self.tries:
                        self._count("gave_up")
                        return 503, {"Content-Type": "text/plain"}, (
                            f"kit-s3relay: S3 answered 404 {s3retry.error_code(body)} {false} times for a key "
                            "it holds elsewhere; not passed on as missing\n").encode()
                    self.sleep(min(2.0, 0.1 * 2 ** false))
                    continue
                if (exc.code == 429 or exc.code >= 500) and failed + 1 < NETWORK_TRIES:
                    failed += 1
                    self.sleep(min(8.0, 0.5 * 2 ** failed))
                    continue
                return exc.code, hdrs, body
            except (urllib.error.URLError, OSError, socket.timeout, http.client.HTTPException) as exc:
                failed, gave_up = self._network_failure(exc, failed)
                if gave_up:
                    return gave_up
