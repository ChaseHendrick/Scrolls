# s3relay: a local relay that keeps S3's false 404s away from VC3D

`kit/s3relay.py` runs a small HTTP server on 127.0.0.1 that forwards VC3D's chunk requests to S3, asks again after a false 404, and passes a 404 on only when S3 says `NoSuchKey`, so VC3D never caches a chunk that exists as empty.

| Field | Value |
| --- | --- |
| Id | `s3relay` |
| Status | Current |
| Kind | kit module |
| Area | Data and downloads |
| Run | `from kit import s3relay` (its command line, `kit s3relay`, is on the [vc3dfix](vc3dfix.md) page) |
| Code | `kit/s3relay.py` |
| Tests | `tests/test_s3relay.py`, `tests/test_cutoff_reads.py` |
| Needs | Python 3 standard library only (run here on Python 3.13). A free local TCP port. VC3D (villa) as its client |
| Runs on | Any machine, in a thread of the process that starts it. Through it, a 256 x 256 crop render of w035 at 2.399 um with an empty cache took 24 s against about 17 s direct (8 October 2026, one cloud container) |
| Network | Listens on `127.0.0.1` (the `host` argument) on one port between 20000 and 40014, or any free port. Connects to the one upstream origin it was made for, such as `https://vesuvius-challenge-open-data.s3.amazonaws.com` for an `s3://vesuvius-challenge-open-data/...` URL, through the default opener's proxy settings (`HTTPS_PROXY`, `NO_PROXY`) |
| Writes | Nothing on disk. VC3D, its client, writes its own chunk cache, in a folder named by the relay URL it was given |
| Go-ahead | Not needed: it reads public objects anonymously and serves only the local machine |
| Released | Public `main` from the change that adds it (24 Oct 2026). An earlier copy ships inside the AutoPipeline release branches (`submission/progress-2026-10` from 2026-10-14 to `submission/progress-2026-10-fix4`); this one also passes headers whose names a proxy changed in case (`etag` for `ETag`) |
| Guide | [VC3D and S3's false 404s](../vc3d-false-404.md) |
| Checked | 2026-10-24 against commit `HASH1` |

## What it does

VC3D (Volume Cartographer 3D, villa's viewer and command line tools) reads a remote zarr volume itself, over HTTP with libcurl, and keeps every chunk it reads in a persistent cache. It takes any HTTP 404 for a missing key: a chunk then gets an **empty-chunk marker** in that cache and reads as zeros in every later run, and a 404 on a metadata key makes the volume fail to open. S3 sometimes answers 404 for chunks it holds (a **false 404**: from one cloud machine on 8 October 2026, for example 102 of 316 GETs at 32 workers, with an error body naming `NoSuchBucket`). A fresh 256 x 256 crop render of PHerc0139 w035, run directly, got 4 false empty chunks and 27.7 % zero samples, with exit code 0 ([log](../logs/2026-10-12-upstream-reports.md)).

The relay sits between VC3D and the bucket. `python -m kit s3relay` starts it on `127.0.0.1` and gives VC3D `http://127.0.0.1:PORT/<the volume's path>` instead of the bucket URL. Each request goes upstream on a new connection. A 404 reaches VC3D only when S3 says `NoSuchKey` (or names no S3 code); any other 404 is asked again, up to 10 times; a key that keeps answering false 404s reaches VC3D as HTTP 503, which VC3D retries and then reports as an error, never as a hole. Network failures, cut-off transfers and 429 or 5xx answers are asked again too, and a key that keeps failing that way reaches VC3D as 502 (network) or as the upstream answer (429, 5xx).

The port comes from the upstream origin, so repeated runs give VC3D the same URL and reuse one cache folder. It does not repair a cache VC3D already filled with false markers (that is [vc3d-cache](vc3d-cache.md)), does not cache anything itself, and serves only GET and HEAD. It changes no bytes of the data: what VC3D renders through it is model input, and any ink map made from that render is model output, not a reading.

### The copies in the AutoPipeline release

The AutoPipeline release branches carry an earlier copy of this file under `submissions/.../autopipeline/kit/`. It differs from this one only in looking upstream header names up exactly as spelled, so behind a proxy that lowers their case it dropped `ETag`.

## When to use it

- Any time VC3D (a `vc_*` command line tool or the app) reads a volume from S3 while the bucket may answer false 404s: `python -m kit s3relay URL -- COMMAND` ([vc3dfix](vc3dfix.md)), or a relay of your own in Python.
- To see how often the bucket answered false 404s during a VC3D run: the relay's `stats`, which `kit s3relay` prints when it stops.

Do not use it:

- For kit's own downloads: they already use the same rule in-process ([s3retry](s3retry.md), [fetch](fetch.md)).
- To fix a cache VC3D filled without the relay: run `python -m kit vc3dcache URL` ([vc3d-cache](vc3d-cache.md)) first.
- For local volumes: there is nothing to relay. `origin_of` refuses a path that is not an http, https or s3 URL.
- As a server for other machines: it listens on loopback and has no access control.

## Quick start

From the repository root, a relay for PHerc0139's 9.362 um volume, read once the way VC3D would:

```bash
python3 - <<'EOF'
import urllib.request
from kit import s3relay
VOL = "s3://vesuvius-challenge-open-data/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr"
with s3relay.Relay(VOL) as relay:
    url = relay.url_for(VOL)              # the URL to give VC3D instead of VOL
    print(url)
    with urllib.request.urlopen(url + "/0/.zarray", timeout=60) as resp:
        print(resp.status, resp.read()[:30])
    print(relay.stats)
EOF
```

It printed, on 2026-10-16 from a cloud container (0.9 s in all):

```
http://127.0.0.1:24980/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr
200 b'{\n  "shape": [\n    20974,\n    '
{'requests': 1, 'false_404': 0, 'missing': 0, 'gave_up': 0, 'network_errors': 0}
```

It worked when the relay URL answers 200 with the bucket's bytes. The relay stops when the `with` block ends, so VC3D must run inside it. To keep a relay up for VC3D run by hand, or to wrap one VC3D command, use `python -m kit s3relay` ([vc3dfix](vc3dfix.md)).

## Checks and controls

- **The control is the direct run.** On 8 October, the same crop render with an empty cache: direct, 4 false empty chunks (8 markers) and 27.7 % zero samples; through the relay, 85 requests, 5 false 404s asked again, 19 true 404s (probes for metadata files the volume does not have), none given up, no empty markers, and the same bits as the clean render (measured 8 October 2026 in one cloud container).
- **Missing keys must still be missing.** Through the relay, a key that does not exist answers 404 with S3's `NoSuchKey` body at once (run 2026-10-16 on the bucket: `GET URL/0/no-such-chunk` gave 404 and `missing` 1 in `stats`). A relay that answered 503 for every 404 would hide holes the other way; the tests check both.
- **Against a server that sends false 404s.** On `S3LikeServer` (`tests/vc3d_fakes.py`) with two false 404s per key and one key that always answers one, run 2026-10-16: a direct GET got 404; through the relay the key read 200, HEAD 200, the missing key 404 with `NoSuchKey`, and the bad key 503 after 13.0 s with the body `kit-s3relay: S3 answered 404 NoSuchBucket 10 times for a key it holds elsewhere; not passed on as missing`; `stats` read `{'requests': 4, 'false_404': 13, 'missing': 1, 'gave_up': 1, 'network_errors': 0}`.
- **After a run.** `stats["gave_up"]` above 0 means VC3D got a 503 for some key: the run is incomplete; run it again. A VC3D run made without the relay still needs the cache check afterward ([vc3d-cache](vc3d-cache.md)), since a relay started later cannot undo markers written earlier.

Claim label: Sourced fact, for the 8 October 2026 measurements from one cloud container (direct against relay render, counts above); the relay itself relays bytes and makes no claim about them.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `RelayError` | An `OSError` subclass | Nothing | Raised by `origin_of`, `Relay.start` and `Relay.url_for`. `kit s3relay` prints it and exits 2 |
| `origin_of(url)` | `(origin, path)`: origin `scheme://host[:port]`, path the URL's path (`/` when empty; the query is dropped) | `RelayError` for anything that is not an http, https or s3 URL | `s3://BUCKET/KEY` becomes `("https://BUCKET.s3.amazonaws.com", "/KEY")`, the bucket's anonymous global endpoint |
| `preferred_ports(origin, n=16)` | list of `n` ints: `20000 + FNV-1a-64(origin) % 20000`, then the next `n - 1` ports | Nothing | The open-data bucket's `s3://` origin gives 24980 to 24995; its `https://...s3.us-east-1.amazonaws.com` origin gives 27518 to 27533 |
| `candidate_urls(url, host="127.0.0.1")` | list of 16 URLs `http://HOST:PORT/PATH`, one per preferred port | `RelayError` as `origin_of` | Every URL a relay may have given VC3D for this volume, so `kit vc3dcache` can find the cache folders made through a relay. A relay that fell back to a random port (below) is not among them |
| `Relay(upstream, port=None, tries=s3retry.TRIES, timeout=60, opener=None, sleep=time.sleep, host="127.0.0.1")` | A relay object, not yet listening | `RelayError` from `origin_of` | `upstream`: any URL of the origin (its path is ignored). `port`: None tries the preferred ports, then any free port (0); a number tries only that port. `tries`: false-404 attempts per request, at least 1 (default 10). `timeout`: seconds per upstream request. `opener`: default `urllib.request.urlopen`. `sleep`: replaced by tests. `host`: the listen address |
| `Relay.start()` | the relay (so `Relay(u).start()` chains) | `RelayError: cannot listen on HOST: ...` when no port could be bound | Serves in a daemon thread named `kit-s3relay`; sets `.port`, `.server`, `.thread` |
| `Relay.stop()` | None | Nothing | Shuts the server and closes its socket; `.server` becomes None. Also on leaving a `with` block |
| `Relay.base` (property) | str `http://HOST:PORT` | Nothing | Valid after `start()` |
| `Relay.url_for(url)` | str: `base` plus `url`'s path | `RelayError: URL is not under ORIGIN` for another origin | The URL to give VC3D |
| `Relay.fetch(url, method="GET", headers=None)` | `(status, headers, body)` as VC3D should see them | Nothing; failures become 404, 502, 503 or the upstream code | What the request handler calls for each request; usable directly in tests |
| `Relay.stats` | dict of ints: `requests`, `false_404`, `missing`, `gave_up`, `network_errors` | Nothing | Counted since the relay was made, under a lock. See Outputs |

Module constants: `PASS_HEADERS` (`Content-Type`, `Content-Range`, `ETag`, `Last-Modified`, `Accept-Ranges`, `Content-Encoding`), the upstream headers passed to VC3D; `NETWORK_TRIES = 4`, attempts per request for network failures, 429 and 5xx.

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| `upstream` | `s3://BUCKET/PATH`, or an `http://` or `https://` URL | Only the origin counts. One relay serves one origin; a second origin needs a second relay |
| Requests from VC3D | HTTP/1.1 GET or HEAD to `http://127.0.0.1:PORT/PATH[?QUERY]` | The path and query are appended to the origin. Of the request headers only `Range` is forwarded; the relay sends `User-Agent: kit-s3relay`. Other methods get the standard library's `501` |

## Outputs

What the relay answers VC3D, by what the upstream answered:

| Upstream answer | Relay answers | Counted in |
| --- | --- | --- |
| 200 or 206 | The same status, the `PASS_HEADERS` present, `Content-Length`, the body (none for HEAD) | `requests` |
| 404 naming `NoSuchKey`, or no S3 code, to a GET | 404 with the passed headers and S3's body | `missing` |
| 404 naming another code (a false 404) to a GET | Asked again after `min(2.0, 0.1 * 2 ** n)` s; after `tries` such answers, `503` with the text below | `false_404` per answer; `gave_up` once |
| 404 to a HEAD | A one-byte GET (`s3retry.key_state`) decides: missing gives 404; present asks the HEAD again (until `tries`); unknown, or out of tries, gives `503` with no body | `missing`, `false_404`, or `gave_up` |
| 429 or 5xx | Asked again after 1, 2 and 4 s; the fourth such answer is passed on as it is | Not counted |
| Any other HTTP error (such as 403) | Passed on as it is | Not counted |
| No answer, a timeout, or a body cut off mid-read (an error's body too) | Asked again after 1, 2 and 4 s; after `NETWORK_TRIES` = 4 failures, `502` with the text below | `network_errors` per failure |

The texts in the bodies (`Content-Type: text/plain`):

- `kit-s3relay: S3 answered 404 CODE N times for a key it holds elsewhere; not passed on as missing` (503)
- `kit-s3relay: ERROR` (502), such as `kit-s3relay: <urlopen error [Errno 111] Connection refused>`

| Field | Type | Meaning |
| --- | --- | --- |
| `requests` | int | Requests from the client |
| `false_404` | int | False 404s received upstream (one request can count several) |
| `missing` | int | 404s passed on as missing |
| `gave_up` | int | Requests answered 503 after false 404s |
| `network_errors` | int | Upstream network failures, including cut-off reads |

`kit s3relay` prints these counts when it stops (`stats` in its `--json`), with `relay_url`, the URL VC3D was given. Nothing is written to disk.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `RelayError: not an http(s) or s3 URL: URL` | `origin_of` got a local path or another scheme | Give the bucket URL; local volumes need no relay |
| `RelayError: cannot listen on 127.0.0.1: [Errno 98] Address already in use` | `port` was fixed and taken, or no port at all could be bound on `host` | Leave `port` as None, or free the port |
| `RelayError: URL is not under ORIGIN` | `url_for` got a URL of another origin, such as the `us-east-1` endpoint for a relay made from an `s3://` URL | Make the relay from the same form of URL you pass to `url_for` |
| VC3D reports HTTP 503 for a chunk, or `stats["gave_up"]` above 0 | A key answered false 404s `tries` times in a row | Wait and run again; check the bucket. Do not lower `tries` |
| VC3D reports HTTP 502 | The upstream could not be reached 4 times in a row (network down, proxy refused, cut-off transfers) | Check the network or proxy (`HTTPS_PROXY`), then run again |
| VC3D reports HTTP 0 or connection refused partway through a run | The relay stopped while VC3D still read through it (its process ended); on 9 Oct 2026 two traces that shared one cache folder lost 25 grid files this way (inferred from the two relays' counts) | Keep the relay's process alive until VC3D finishes; give each VC3D run its own relay |
| VC3D starts with a cold cache although the volume was read before | A second relay for the same origin was running, so this one took the next port; or all 16 preferred ports were taken and it took a random one, which also hides its cache folder from `kit vc3dcache` | Stop the other relay, or accept one cold run |

## How it works

1. **Origin and port.** `origin_of` reduces the volume URL to its origin; `s3://BUCKET/...` becomes `https://BUCKET.s3.amazonaws.com`. `preferred_ports` hashes the origin with 64-bit FNV-1a (`_fnv1a64`: offset `0xCBF29CE484222325`, prime `0x100000001B3`) to `20000 + h % 20000`, then the 15 ports after it. `start()` binds the first free one of those, then port 0 (any free port), on `host`. VC3D names its cache folder after the URL it is given (its last part and an FNV-1a hash, per the guide), so the same port means the same folder run after run.
2. **Serving.** A `ThreadingHTTPServer` with daemon threads, HTTP/1.1, `Server: kit-s3relay`, no request logging. Each GET or HEAD calls `fetch(origin + path, method, headers)`, where headers are `User-Agent: kit-s3relay` and the client's `Range`, if any.
3. **Upstream.** `fetch` sends the request with the opener (default `urllib.request.urlopen`, a new connection each time), reads the whole body into memory, and answers as in the Outputs table. False 404s are recognized by `s3retry.false_404` (the S3 `<Code>` in the body is not `NoSuchKey`). A HEAD has no body to read the code from, so a HEAD 404 is checked with `s3retry.key_state`, a one-byte GET with its own false-404 retries.
4. **Back-off.** False 404 number n waits `min(2.0, 0.1 * 2 ** n)` s (0.2, 0.4, 0.8, 1.6, then 2.0: 13.0 s in all before a 503 with `tries` = 10, as measured above). Network failures, 429 and 5xx share one count per request and wait `min(8.0, 0.5 * 2 ** n)` s (1, 2, 4 s; 7.1 s measured before a 502 on 2026-10-16).
5. **The answer.** Status, the `PASS_HEADERS` the upstream sent, and `Content-Length` (the upstream's for a HEAD that succeeded, else the body's length). A client that disconnects mid-answer is ignored.

Header names are matched without regard to case: a proxy or an HTTP/2 hop may hand S3's `ETag` on as `etag` or `Etag`, and the relay still passes it (an earlier copy dropped it; seen on 2026-10-16 behind a cloud proxy). VC3D's use of ETag was not checked.

## Cost and time

On 2026-10-16 from a cloud container (4-core Intel Xeon 2.80 GHz, through its HTTPS proxy): ten 1 KB ranged GETs of chunks averaged 0.45 s each through the relay and 0.63 s each direct, so the relay's own time is below the network's noise. On 8 October the crop render took 24 s through the relay against about 17 s direct, with 5 false 404s asked again. A key that never clears holds its request for 13 s (false 404s) or 7 s (network) before the error answer. Memory: one whole upstream body per request in flight (a chunk of the 9.362 um volume is 2,097,152 bytes). It runs wherever VC3D runs; it is not a compute job.

## For agents

- **Command:** `python -m kit s3relay VOLUME_URL --json -- VC3D_COMMAND ...` ([vc3dfix](vc3dfix.md)). In Python: `with s3relay.Relay(VOLUME_URL) as relay: url = relay.url_for(VOLUME_URL)`, then run VC3D with `url` inside the block.
- **Parse:** `relay.stats` (or `stats` in `kit s3relay --json`): `gave_up` and `network_errors` are the counts that matter; `false_404` shows the bucket misbehaved and the relay covered it.
- **Rerun:** Safe. It holds no state on disk; a new relay for the same origin takes the same port when it is free, so VC3D reuses its cache.
- **Success:** VC3D's run exits 0 and `stats["gave_up"]` is 0.
- **Not a pass:** A run made with VC3D given the bucket URL directly, when the bucket answered false 404s: its zeros may be holes. `gave_up` above 0: VC3D got a 503 for some chunk.
- **Go-ahead:** Nothing.
- **Never:** Stop the relay (end its process) while a VC3D process still reads through it; expose it beyond `127.0.0.1`; take a render with false empty chunks as data (run [vc3d-cache](vc3d-cache.md)).

## Tests

```bash
python3 -m unittest tests.test_s3relay tests.test_cutoff_reads -v
```

`tests/test_s3relay.py` (4 tests): `origin_of` for s3 and https URLs and its refusal of a local path; the 16 preferred ports and `candidate_urls`; against `S3LikeServer`, false 404s never reaching the client, ranged GETs with `Content-Range`, HEAD with `Content-Length`, a missing key as 404 for GET and HEAD, a key that always answers false 404s as 503, the counters, and `url_for` refusing another origin; an upstream that is down answered 502 after `NETWORK_TRIES`; two relays for one origin on two ports, and `stop()`. `tests/test_cutoff_reads.py` adds a cut-off body and a cut-off 404 body (retried, 502 when it never ends, never passed on as missing). `tests/test_vc3dfix.py` sends a stand-in VC3D command through the relay with `kit s3relay`. They ran in about 10 s on 2026-10-24 (with `test_s3retry`), all passing. They do not test the retries of a whole 429 or 5xx answer, the random-port fallback, or real VC3D.

## History

- 2026-10-24: on public `main`, with `python -m kit s3relay`; header names matched without regard to case (`HASH1`).
- 2026-10-15: the copy in AutoPipeline 0.1.4 (`603fe14`, branch `submission/progress-2026-10-fix4`). Made before it was public: the first version of 8 October; `preferred_ports` and `candidate_urls`, so cache folders made through a relay can be found (8 October); a transfer or an error body cut off mid-read is a network failure, asked again, then 502, instead of a crash or a missing key (9 October).

## Related

- [s3retry](s3retry.md): the false-404 rule the relay applies, and kit's in-process downloads.
- [vc3d-cache](vc3d-cache.md): checks VC3D's empty-chunk markers against the bucket and deletes false ones; uses `candidate_urls`.
- [vc3dfix](vc3dfix.md): `python -m kit s3relay` and `python -m kit vc3dcache`, the command lines for this module and the cache check.
- [false404-relay](false404-relay.md): `scripts/false404/fault_relay.py`, the opposite tool, which injects false 404s in front of the bucket to test fixes.
- [The upstream reports log](../logs/2026-10-12-upstream-reports.md): the measurements, and the native fix proposed to villa ([issue #2058](https://github.com/ScrollPrize/villa/issues/2058), [PR #2060](https://github.com/ScrollPrize/villa/pull/2060)), which would make the relay unnecessary for patched builds.
