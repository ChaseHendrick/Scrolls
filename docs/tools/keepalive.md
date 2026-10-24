# keepalive: reuse HTTP connections for kit's remote zarr reads

`kit/keepalive.py` is a drop-in for `urllib.request.urlopen` that keeps finished HTTP and HTTPS connections in a small pool per server and reuses them, so kit's remote zarr readers stop paying a new connection and TLS handshake for every chunk.

| Field | Value |
| --- | --- |
| Id | `keepalive` |
| Status | Current |
| Kind | kit module |
| Area | Data and downloads |
| Run | `from kit import keepalive` (a library; on by default for every remote zarr store kit opens, off with `KIT_HTTP_REUSE=0`) |
| Code | `kit/keepalive.py` |
| Tests | `tests/test_keepalive.py` |
| Needs | Python 3, standard library only |
| Runs on | Any machine. On a Mac laptop over a direct connection, kept connections halved two remote box reads of public PHerc0139 volumes (4.35 s to 2.17 s and 1.89 s to 0.84 s, 15 October 2026); through the proxy of Claude's cloud sessions they save nothing, because that proxy closes every connection after one answer (measured 2026-10-16) |
| Network | Whatever host the caller asks for, such as `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`; through `HTTPS_PROXY` when one is set (an HTTP CONNECT tunnel), and never anywhere on its own |
| Writes | Nothing |
| Go-ahead | Not needed |
| Released | Public `main` from the change that adds it (24 Oct 2026). Identical to the copy inside the AutoPipeline release since 0.1.3, 2026-10-15 (branches `submission/progress-2026-10-fix3` and `-fix4`) |
| Guide | [VC3D and S3's false 404s](../vc3d-false-404.md) (the tools that read through it) |
| Checked | 2026-10-24 against commit `77aea1f` |

## What it does

kit reads remote zarr volumes (scans, surface predictions, ink labels) chunk by chunk over HTTPS, through `HttpStore` in `kit/vc3d_audit.py` ([vc3d-audit](vc3d-audit.md)). `urllib.request.urlopen` opens a new connection for every request, and for HTTPS a new TLS handshake, so a read of a few hundred chunks pays a few hundred handshakes. `KeepAlive` has `urlopen`'s call form (`opener(request, timeout=...)`) and gives the same answers: a response with `.status` and `.read()`, and `urllib.error.HTTPError` for 4xx and 5xx. The difference is that it keeps each finished connection in an idle pool of at most 32 per origin (scheme, host and port) and hands it to the next request for that origin, from any thread.

`HttpStore` uses the shared pool from `default_opener()` unless it is given another opener, so everything that opens a remote store through `kit.vc3d_audit.open_store` gets kept connections; in this repository that is the chunk store of [vc3d-audit](vc3d-audit.md) and the cache check of [vc3d-cache](vc3d-cache.md).

It does not cache bodies, retry 429 or 5xx answers, pace requests, or stream: it reads each whole body into memory before returning. Retries, pacing and S3's false 404s are `HttpStore`'s job ([vc3d-audit](vc3d-audit.md), [s3retry](s3retry.md)). The idea comes from SuperOptimizer/ufsm's pooled curl handles (`src/store.c` at commit `75e063b`, 14 October 2026); ufsm has no license for its own code, so this is kit's own implementation and nothing was copied.

## When to use it

- Any kit code that reads many small objects from one server over HTTP(S): take `keepalive.default_opener()`, or pass nothing to `HttpStore` and it will.
- Timing a remote read with and without kept connections: `KeepAlive()` against `urllib.request.urlopen`, or the same command with `KIT_HTTP_REUSE=0`.

Do not use it:

- For one large download: use `python -m kit fetch` ([fetch](fetch.md)); `KeepAlive` holds the whole body in memory.
- For POST or other requests that must not be repeated blindly: it never resends them, but it also gains little for one-off calls; use `urlopen`.
- To make reads faster inside a Claude cloud session: its proxy closes every connection after one answer, so nothing is reused there.

## Quick start

```python
import urllib.request
from kit import keepalive

ka = keepalive.KeepAlive()                       # or keepalive.default_opener(), the shared pool
for k in range(10):
    req = urllib.request.Request("URL", headers={"Range": f"bytes={k}-{k + 3}"})
    with ka(req, timeout=30) as r:
        data = r.read()
print(ka.opened, ka.reused, ka.retried, ka.passed, ka.idle())
ka.close()
```

- `URL`: any `http://` or `https://` object, such as a zarr chunk in the open-data bucket.

Run on 2026-10-16 against a local HTTP/1.1 server (`http.server` with `protocol_version = "HTTP/1.1"`, `KeepAlive(proxies={})`), ten requests printed `kept:   opened 1 reused 9 retried 0 passed 0 idle {'http://127.0.0.1:41551': 1}`; a missing file raised `HTTPError 404`; after `close()` the pool was `{}`.

To turn it off for a whole command, which is the control:

```bash
KIT_HTTP_REUSE=0 python -m kit COMMAND ...
```

- `COMMAND ...`: any kit command that reads a remote zarr, such as `python -m kit vc3dcache URL`.

It worked when `opened` is smaller than the number of requests and `reused` makes up the rest. Through a proxy that closes each connection, `opened` equals the number of requests and `reused` is 0, which is correct behavior, not a fault.

## Checks and controls

- **The control:** `KIT_HTTP_REUSE=0` (or an `opener=urllib.request.urlopen` passed to `HttpStore`) makes every store open a new connection per request, as before. The timing script used below (not in this repository) first read one shared box under every configuration and required identical arrays, so a reuse bug that changed data would fail before any timing.
- **Measured gain, direct connection** (a Mac laptop, 15 October 2026, 4 rounds, medians, public PHerc0139 data): a surface prediction box of 64 chunks took 4.35 s with new connections and 2.17 s with kept ones (3.82 s kept but paced at 20 requests a second); a lasagna box of 64 small chunks 1.89 s and 0.84 s; half a label map, single ranges, 2.28 s and 0.74 s.
- **No gain through a TLS-intercepting proxy.** The same boxes, through a Claude cloud session's proxy: 2.68 s new against 2.74 s kept; 1.73 s against 1.58 s. Checked again on 2026-10-16 in a cloud container: the proxy answers every request with `Connection: close`, so five HEAD requests of `metadata.json` in the open-data bucket opened five connections and reused none (3.68 s, against 3.11 s with `urlopen`; one trial, network noise).
- **Reuse is counted, not assumed.** The tests' local server counts the connections it accepts: ten requests, one connection.

Claim label: None for what it returns (the server's bytes, unchanged); the timings are measurements of kit's reader on public PHerc0139 volumes, not a result about any scroll.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `Response(status, body, headers, url)` | What a `KeepAlive` call returns: `.status` (int), `.headers` (`http.client.HTTPMessage`), `.url`, `.read()` (the whole body as bytes; takes no size argument), `.getcode()`, `.close()` (does nothing), and use as a context manager | Nothing | The body is already read when the call returns |
| `KeepAlive(proxies=None, context=None, max_idle=MAX_IDLE, fallback=None)` | A callable opener: `ka(req, timeout=None, **kw)` returns a `Response`, or what `fallback` returns for a request it passes on. Also `.idle()` (a dict `"scheme://host:port"` to the number of kept connections), `.close()` (closes every kept connection) and the counters `.opened` (new connections), `.reused`, `.retried` (stale connections sent again), `.passed` (requests handed to `fallback`) | `urllib.error.HTTPError` for a status of 400 or more (its body readable with `.read()`); `http.client.RemoteDisconnected`, `CannotSendRequest`, `BadStatusLine`, `ConnectionResetError`, `ConnectionAbortedError` or `BrokenPipeError` (the tuple `keepalive.STALE`) when a new connection fails, or a kept one fails on a method other than GET or HEAD; any other `OSError` (refused, timeout, TLS, `Tunnel connection failed: ...`) as is | `req` is a `urllib.request.Request` or a URL string. `proxies`: a dict as `urllib.request.getproxies()` gives, or `None` to read the environment (and honor `no_proxy`) on every request; `{}` means no proxy. `context`: the TLS context, default `ssl.create_default_context()`, which honors `SSL_CERT_FILE`. `max_idle`: kept connections per origin (32). `fallback`: default `urllib.request.urlopen`. Any extra keyword argument sends the request to `fallback` |
| `default_opener()` | The process-wide shared `KeepAlive` (made on first call, closed at exit), or `urllib.request.urlopen` when `KIT_HTTP_REUSE` is `0`, `false`, `no` or `off` | Nothing | What `HttpStore` uses when given no opener |

Constants: `MAX_IDLE = 32`, kept connections per origin; `STALE`, the exception types that mean a kept connection was closed by the server.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_HTTP_REUSE` | `1` (on) | `0`, `false`, `no` or `off` (exactly these lowercase words, spaces around them ignored) make `default_opener()` return `urllib.request.urlopen`. Read each time `default_opener()` is called, so it affects stores opened after it is set |
| `HTTPS_PROXY`, `https_proxy`, `HTTP_PROXY`, `http_proxy`, `NO_PROXY`, `no_proxy` | unset | Read through `urllib.request.getproxies()` and `proxy_bypass()` when `proxies` is `None`. An `http://` proxy for HTTPS is tunneled with CONNECT; plain HTTP through a proxy goes to `urlopen` |
| `SSL_CERT_FILE` | unset | Honored by the default TLS context; in Claude's cloud sessions it names the proxy's CA bundle |

## Inputs

A request: a `urllib.request.Request` or a URL string, with any method, headers (such as `Range`) and `data`. Only `http://` and `https://` URLs with a host are pooled; others go to `fallback`. The request's `timeout` applies to connecting and to each read on the socket; `None` means no timeout.

## Outputs

A `Response` with the status, headers and the whole body (Python API). Nothing is printed or written. Kept connections stay open in the pool until they are reused, the pool is full (then a finished connection is closed), the server says it will close (`Connection: close` or HTTP/1.0), a stale connection is found for that origin (then all of the origin's kept ones are closed), `close()` is called, or the process exits (the shared pool is closed by `atexit`).

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `urllib.error.HTTPError: HTTP Error CODE: REASON` | The server answered 400 or more; the connection is kept, since its body was read | Handle it as with `urlopen`; `HttpStore` retries 429 and 5xx and reads S3's 404 bodies |
| `http.client.RemoteDisconnected: Remote end closed connection without response` (or another `STALE` error) on a GET or HEAD | A new connection failed, or the retry after a stale kept connection failed too | Check the server and network; `HttpStore` retries network errors up to its `retries` |
| A `STALE` error on a POST, PUT or other method | A kept connection had been closed by the server, and such requests are never sent twice | Send it again yourself if that is safe, or use `urlopen` for it |
| `OSError: Tunnel connection failed: 407 Proxy Authentication Required` (or another code) | The `HTTPS_PROXY` refused the CONNECT tunnel | Put the user and password in the proxy URL, or check the proxy |
| `ssl.SSLCertVerificationError: ... certificate verify failed` | The TLS context does not trust the server's (or an intercepting proxy's) certificate | Set `SSL_CERT_FILE` to the right CA bundle, or pass a `context` |
| `TimeoutError` or `socket.timeout` | No answer within `timeout` | Raise the timeout; `HttpStore` uses 30 s |
| Reads are no faster with it on | A proxy that closes each connection (Claude's cloud sessions), or a server that answers HTTP/1.0 | Nothing to fix; measure on a direct connection |
| `TypeError: Response.read() takes 1 positional argument but 2 were given` | A caller asked for `read(N)`; the body is already whole | Call `read()` and slice |

## How it works

1. **Route.** For each request, split the URL. Not `http` or `https`, no host, or an extra keyword argument: hand it to `fallback` (`passed` counts it). Look up the proxy for the scheme (the given dict, or the environment with `no_proxy`). A proxy for `http`, or a proxy whose own scheme is not `http`: hand it to `fallback`. Otherwise the route is `(scheme, host, port, proxy)`, the port defaulting to 443 or 80.
2. **Take a connection.** Pop one from the route's idle list under a lock (`reused`), setting its timeout; or open a new `HTTPConnection` or `HTTPSConnection` (`opened`). Through a proxy, connect to the proxy and `set_tunnel(host, port)` with a `Proxy-Authorization: Basic ...` header built from the proxy URL's user and password.
3. **Send and read.** Send the method, path and query, body and headers; read the status and the whole body.
4. **Stale.** If that raises one of `STALE` on a kept connection, close it, drop every kept connection of the route, and, for GET and HEAD only, try once more on a new connection (`retried`). On a new connection, raise.
5. **Keep.** If the response says the connection will close, close it; else put it back on the route's idle list, unless the list already holds `max_idle`, in which case close it.
6. **Answer.** A 3xx status sends the request to `fallback`, which follows the redirect (`passed`). A status of 400 or more raises `urllib.error.HTTPError` with the body. Anything else returns a `Response`.

Every pool and counter change happens under one lock, so one `KeepAlive` is shared safely across threads; a connection serves one request at a time.

## Cost and time

Timings are under Checks and controls: on a direct connection kept connections halved the remote box reads measured (Mac, 15 October 2026); through Claude's cloud proxy they change nothing (15 and 16 October 2026). Memory: at most 32 idle connections per origin, and each response's whole body until the caller drops it. It rents nothing and needs no GPU.

## For agents

- **Command:** Nothing to run: `HttpStore` uses it by default. To compare, run the same kit command twice, once with `KIT_HTTP_REUSE=0`.
- **Parse:** On a `KeepAlive` object, `opened`, `reused`, `retried` and `passed`; `idle()` for the pool.
- **Rerun:** Safe; it keeps no state on disk. GET and HEAD are sent at most twice per call; other methods once.
- **Success:** A `Response` with `status` below 300; with reuse working, `reused` is greater than 0 after the first request to an origin.
- **Not a pass:** Speed numbers measured inside a Claude cloud session (its proxy closes every connection); a test against a server that answers HTTP/1.0 or `Connection: close`.
- **Go-ahead:** Nothing. Downloading is not an outward action; the data rules for what is downloaded still apply.
- **Never:** Use it for large single downloads (it holds the whole body in memory); assume a POST was retried.

## Tests

```bash
python -m unittest tests.test_keepalive -v
```

9 tests, a few seconds: ten requests share one connection, a 404 comes back as urllib's error with its body and keeps the connection, a server that drops each connection silently gets each request sent again, after an idle timeout one request succeeds and the other kept connections are dropped, a POST on a closed kept connection is not sent again, a failing new connection is not sent again, the idle limit holds under four threads, proxy routes, and `HttpStore` with the `KIT_HTTP_REUSE` switch. They run on a local server only: no real proxy, TLS or S3 is tested.

## History

- 2026-10-24: on public `main`, with the false-404 tools (`77aea1f`).
- 2026-10-15: the copy in AutoPipeline 0.1.4 (`603fe14`, branch `submission/progress-2026-10-fix4`). Made before it was public, the same day: the first version (the idea comes from SuperOptimizer/ufsm's pooled curl handles); a request on a stale kept connection is sent again on a new connection and the origin's other kept connections are dropped; review fixes for AutoPipeline 0.1.3.

## Related

- [vc3d-audit](vc3d-audit.md): `HttpStore`, which uses this as its default opener, with pacing, retries and false-404 handling.
- [s3retry](s3retry.md): S3's false 404s, which `HttpStore` retries.
- [vc3d-cache](vc3d-cache.md): the cache check, whose store reads through it.
