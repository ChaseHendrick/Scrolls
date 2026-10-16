"""A 404 from S3 is not always a missing key.

Measured from this project's cloud on 2026-10-08 (docs/logs/2026-10-08-vc3d-landmarks.md): the open-data bucket
answered 11 to 32 percent of new connections with HTTP 404 and an S3 error body naming NoSuchBucket, for chunks
that exist, at every concurrency from 1 to 32 threads. The answers carry S3's own headers and request ids. A
connection that gets one keeps getting them, so a client that reuses connections (VC3D's libcurl) can lose a run
of chunks at once; HEAD requests never got one in 1580 tries. Whether the cloud's egress proxy has a part in it
is not known; a machine without that proxy may never see it.

A reader that takes every 404 for a missing chunk blanks real data: zarr reads a missing chunk as fill_value,
and VC3D caches a 404 chunk as empty for good. So here a 404 is a missing key only when its body names
NoSuchKey, or when it carries no S3 error code at all (a server that is not S3). Any other code is retried on a
new connection, and a key that keeps getting it is reported as unknown, never as missing.
"""

import http.client
import io
import re
import time
import urllib.error
import urllib.request

MISSING_CODE = "NoSuchKey"
TRIES = 10                  # attempts in all: 0.32 ** 10 is about 1e-5 at the worst rate measured
PRESENT, MISSING, UNKNOWN = "present", "missing", "unknown"
REMOTE = re.compile(r"^(https?|s3|gs|gcs|az|abfs)://", re.I)
_CODE = re.compile(rb"<Code>\s*([A-Za-z0-9_.-]+)\s*</Code>")


def error_code(body):
    """The <Code> of an S3 XML error body, or None (no body, or not S3's error XML)."""
    if not body:
        return None
    m = _CODE.search(body if isinstance(body, bytes) else str(body).encode("utf-8", "replace"))
    return m.group(1).decode() if m else None


def false_404(status, body):
    """True when a 404 is not a missing key: its S3 error body names another code than NoSuchKey."""
    code = error_code(body)
    return status == 404 and code is not None and code != MISSING_CODE


def _backoff(attempt):
    return min(2.0, 0.1 * 2 ** attempt)


def open_url(req, opener=None, timeout=60, tries=TRIES, sleep=time.sleep, counter=None):
    """opener(req, timeout=timeout) with a false 404 retried, up to `tries` attempts in all. Any other answer is
    returned or raised as the opener gives it; a key that answers a false 404 every time raises that HTTPError
    with a reason that says so. counter: a dict whose "false_404" entry counts the false answers."""
    opener = opener or urllib.request.urlopen
    for attempt in range(tries):
        try:
            return opener(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            body = exc.read() or b""
            exc.close()
            if not false_404(404, body):
                raise urllib.error.HTTPError(exc.url, exc.code, exc.msg, exc.hdrs, io.BytesIO(body)) from None
            if counter is not None:
                counter["false_404"] = counter.get("false_404", 0) + 1
            if attempt == tries - 1:
                raise urllib.error.HTTPError(
                    exc.url, 404, f"S3 answered 404 {error_code(body)} {tries} times; not taken as a "
                                  "missing key", exc.hdrs, io.BytesIO(body)) from None
            sleep(_backoff(attempt))


def key_state(url, opener=None, timeout=30, tries=TRIES, sleep=time.sleep, counter=None):
    """(present | missing | unknown, detail) for one object, from a one-byte ranged GET with false 404s retried:
    present on 200 or 206; missing on a 404 that names NoSuchKey or names no code; unknown otherwise (403,
    which S3 also gives for missing keys in buckets it will not list, failures, a false 404 every time)."""
    req = urllib.request.Request(url, headers={"Range": "bytes=0-0", "User-Agent": "kit-s3retry"})
    try:
        with open_url(req, opener, timeout, tries, sleep, counter) as resp:
            resp.read()
            return PRESENT, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            body = exc.read() or b""
            if not false_404(404, body):
                return MISSING, f"HTTP 404 {error_code(body) or '(no S3 code)'}"
        return UNKNOWN, f"HTTP {exc.code} {exc.reason}"
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        return UNKNOWN, str(getattr(exc, "reason", exc))


def refuse_remote(path, what="this command"):
    """Raise ValueError for a URL: zarr reads a chunk that answers 404 as fill_value, so a remote store would be
    read with holes and no error. Local paths pass."""
    if REMOTE.match(str(path)):
        raise ValueError(f"{what} reads local zarr only: over the network a chunk that answers 404 reads as "
                         f"fill_value with no error, and S3 sometimes answers 404 for chunks that exist "
                         f"(kit/s3retry.py). Fetch it first: python -m kit fetch PREFIX DEST")
    return path

