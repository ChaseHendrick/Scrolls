"""Kept-alive HTTP connections for the remote zarr readers (`HttpStore`'s default opener).

urllib.request.urlopen opens a new connection for every request, and for https a new TLS handshake, so a reader
that fetches thousands of chunks pays the handshake thousands of times. `KeepAlive` has the same call form as
urlopen(request, timeout=...) and the same answers (a response with .status and .read(), urllib.error.HTTPError for
4xx and 5xx), but keeps finished connections in a bounded idle pool per origin, so the next request, from any
thread, reuses one. A connection serves one request at a time. A request on a kept connection that the server has
meanwhile closed is sent once more on a new connection (GET and HEAD only), and the origin's other kept connections,
idle at least as long and so most likely closed too, are dropped. Redirects, https proxies and plain http
through a proxy go through urllib unchanged. An http proxy for https (HTTPS_PROXY, as in Claude's cloud sessions)
is used through CONNECT, with its user and password if the URL has them; no_proxy is honoured.

`KIT_HTTP_REUSE=0` turns it off (every store then opens a connection per request, as before), which is the control
for timing it. The idea comes from SuperOptimizer/ufsm's pooled curl handles (src/store.c at commit 75e063b,
14 October 2026). ufsm has no licence for its own code, so this is our own implementation and nothing is copied.
Standard library only.
"""
import atexit
import base64
import http.client
import io
import os
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request

MAX_IDLE = 32           # kept connections per origin
STALE = (http.client.RemoteDisconnected, http.client.CannotSendRequest, http.client.BadStatusLine,
         ConnectionResetError, ConnectionAbortedError, BrokenPipeError)


class Response:
    """What urlopen's response gives the stores: status, headers, the whole body, and a context manager."""

    def __init__(self, status, body, headers, url):
        self.status, self.headers, self.url = status, headers, url
        self._body = body

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class KeepAlive:
    """urlopen with kept connections. proxies: a dict as urllib.request.getproxies() gives (None reads the
    environment on each new connection); context: the TLS context (None: the default, which honours
    SSL_CERT_FILE). Counters: opened (new connections), reused, retried (stale connections sent again),
    passed (requests handed to urllib)."""

    def __init__(self, proxies=None, context=None, max_idle=MAX_IDLE, fallback=None):
        self.proxies = proxies
        self.context = context
        self.max_idle = max(0, int(max_idle))
        self.fallback = fallback or urllib.request.urlopen
        self.opened = self.reused = self.retried = self.passed = 0
        self._idle = {}
        self._lock = threading.Lock()

    def _ctx(self):
        if self.context is None:
            self.context = ssl.create_default_context()
        return self.context

    def _route(self, parts):
        """(scheme, host, port, proxy) of a URL, or None when urllib should send it."""
        scheme, host = parts.scheme.lower(), parts.hostname
        if scheme not in ("http", "https") or not host:
            return None
        port = parts.port or (443 if scheme == "https" else 80)
        proxies = urllib.request.getproxies() if self.proxies is None else self.proxies
        proxy = proxies.get(scheme)
        if proxy and self.proxies is None and urllib.request.proxy_bypass(host):
            proxy = None
        if proxy:
            if scheme != "https" or urllib.parse.urlsplit(proxy).scheme.lower() != "http":
                return None
        return scheme, host, port, proxy or None

    def _new(self, route, timeout):
        scheme, host, port, proxy = route
        if proxy:
            p = urllib.parse.urlsplit(proxy)
            conn = http.client.HTTPSConnection(p.hostname, p.port or 80, timeout=timeout, context=self._ctx())
            headers = {}
            if p.username is not None:
                cred = f"{urllib.parse.unquote(p.username)}:{urllib.parse.unquote(p.password or '')}"
                headers["Proxy-Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
            conn.set_tunnel(host, port, headers=headers)
        elif scheme == "https":
            conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=self._ctx())
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        with self._lock:
            self.opened += 1
        return conn

    def _take(self, route, timeout):
        """(connection, fresh): a kept one when there is one, else a new one."""
        with self._lock:
            idle = self._idle.get(route)
            conn = idle.pop() if idle else None
            if conn is not None:
                self.reused += 1
        if conn is None:
            return self._new(route, timeout), True
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
        return conn, False

    def _give(self, route, conn):
        with self._lock:
            idle = self._idle.setdefault(route, [])
            if len(idle) < self.max_idle:
                idle.append(conn)
                return
        conn.close()

    def _drop(self, route):
        """Close every connection kept for route."""
        with self._lock:
            conns = self._idle.pop(route, [])
        for c in conns:
            c.close()

    def idle(self):
        """Kept connections per origin, for checks."""
        with self._lock:
            return {f"{r[0]}://{r[1]}:{r[2]}": len(v) for r, v in self._idle.items() if v}

    def close(self):
        with self._lock:
            conns = [c for v in self._idle.values() for c in v]
            self._idle.clear()
        for c in conns:
            c.close()

    def __call__(self, req, timeout=None, **kw):
        if isinstance(req, str):
            req = urllib.request.Request(req)
        url = req.full_url
        parts = urllib.parse.urlsplit(url)
        route = self._route(parts)
        if route is None or kw:
            with self._lock:
                self.passed += 1
            return self.fallback(req, timeout=timeout, **kw)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        method = req.get_method()
        headers = dict(req.header_items())
        resp = body = None
        for attempt in (0, 1):
            # the second try is always on a new connection: after a pause every kept one may be closed
            conn, fresh = (self._new(route, timeout), True) if attempt else self._take(route, timeout)
            try:
                conn.request(method, path, body=req.data, headers=headers)
                resp = conn.getresponse()
                body = resp.read()
            except STALE:
                conn.close()
                if fresh:
                    raise
                self._drop(route)
                if method not in ("GET", "HEAD"):
                    raise
                with self._lock:
                    self.retried += 1
                continue
            except BaseException:
                conn.close()
                raise
            if resp.will_close:
                conn.close()
            else:
                self._give(route, conn)
            break
        if 300 <= resp.status < 400:
            with self._lock:
                self.passed += 1
            return self.fallback(req, timeout=timeout)
        if resp.status >= 400:
            raise urllib.error.HTTPError(url, resp.status, resp.reason, resp.headers, io.BytesIO(body))
        return Response(resp.status, body, resp.headers, url)


_POOL = None
_POOL_LOCK = threading.Lock()


def default_opener():
    """The shared kept-alive opener, or urllib's urlopen when KIT_HTTP_REUSE=0."""
    global _POOL
    if os.environ.get("KIT_HTTP_REUSE", "1").strip() in ("0", "false", "no", "off"):
        return urllib.request.urlopen
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = KeepAlive()
            atexit.register(_POOL.close)
        return _POOL
