# false404-relay: replay S3's false 404 on chosen zarr chunks, on demand

`scripts/false404/fault_relay.py` is a local HTTP relay in front of the open-data bucket that answers the first GETs of a fixed, seeded share of zarr chunk keys with the 404 `NoSuchBucket` S3 once sent, so VC3D's caching of false 404s (villa #2058) can be shown and its fix tested.

| Field | Value |
| --- | --- |
| Id | `false404-relay` |
| Status | Current |
| Kind | script folder |
| Area | Data and downloads |
| Run | `python3 scripts/false404/fault_relay.py` |
| Code | `scripts/false404/` |
| Tests | `tests/test_false404_relay.py` |
| Needs | Python 3.10 or newer, standard library only. To show the bug: a VC3D (villa) build that streams zarr volumes over HTTP, pointed at the relay instead of the bucket |
| Runs on | Any machine; it serves on `127.0.0.1` only. On a fake local bucket it answered 11 requests in about 2.7 s, start and stop included (measured 2026-10-16, cloud container, synthetic data). Speed against the real bucket: Not measured |
| Network | The upstream it relays to, by default `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (`BUCKET`), one new connection per request; it listens on `127.0.0.1` |
| Writes | Nothing by default (prints two JSON lines). With `--log LOG`, appends one JSON line per request to LOG |
| Go-ahead | Not needed to run it. Posting what it shows, such as a comment or a new render on villa #2058 or #2060, needs Chase's yes (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-12 |
| Guide | [the upstream reports log](../logs/2026-10-12-upstream-reports.md) (section 1), [the false-404 receipts](../evidence/2026-10-12-false-404/README.md) |
| Checked | 2026-10-16 against commit `63ee638` |

## What it does

On 8 October 2026 the Vesuvius Challenge open-data bucket answered some GETs, from one cloud machine, with HTTP 404, S3's own headers (`Server: AmazonS3`, an `x-amz-request-id`) and the body `<Code>NoSuchBucket</Code>`, for keys it holds. A key that is really absent answers `NoSuchKey` instead. VC3D, villa's volume viewer and tracer, treats any 404 as "this chunk does not exist", writes an empty marker into its persistent cache, and serves the chunk as zeros in every later run. The result is a hole of zeros in renders and traces with exit code 0, which on scroll data looks like blank papyrus. Chase reported it as [villa #2058](https://github.com/ScrollPrize/villa/issues/2058) and drafted a fix, [villa #2060](https://github.com/ScrollPrize/villa/pull/2060) (numbers in [the log](../logs/2026-10-12-upstream-reports.md)).

The false 404 could not be had on demand (on 12 October, 40 of 40 fresh ranged GETs were fine), so this relay plays it back. It listens on `127.0.0.1` and forwards every request to the bucket. A zarr chunk key (a path whose last part is digits, such as `0/12/3/4` or `0/12.3.4`) is "chosen" when the SHA-256 of `SEED:PATH` falls below `--rate`; the first `--bad` GETs of a chosen key get the false 404, and later GETs get the bucket's real answer. Metadata keys (`.zarray`, `zarr.json`, `meta.json`) are never chosen, so the volume always opens, and HEAD requests always go through, because S3 never failed a HEAD for us.

It also protects the replay from the real thing: a false 404 that the bucket itself sends (a 404 whose body is not `NoSuchKey`) is asked again on a new connection, up to 10 times, and never reaches the client. So the only false 404s a client sees are the chosen ones, and each is logged.

It does not render, trace or touch VC3D's cache; it only shapes HTTP answers. The render driver that produced the published before and after renders is private and not in this repository, because it reads layers through a private helper. Nothing here involves an ink model, and the renders it helps make are CT renders, not ink maps.

## When to use it

- To show the false-404 caching bug in VC3D, or any zarr client, on real public scroll data, repeatably.
- To test a fix such as villa #2060: render once through the relay with an empty cache, then again without false 404s on that cache, and compare with a clean render.
- To check that a client retries, or reports a fetch error, when a chunk GET fails with a 404 that is not `NoSuchKey`.

Do not use it:

- To download data: use [`fetch`](fetch.md), which reads the bucket directly.
- To measure how often the real bucket sends false 404s: the relay hides those (it retries them). Count them with plain requests instead, as the [log](../logs/2026-10-12-upstream-reports.md) did.
- To simulate network faults other than this one (timeouts, resets, 5xx): it only injects the 404 `NoSuchBucket` answer.
- As a server for anyone else: it listens on `127.0.0.1` only and has no access control.

## Quick start

```bash
python3 scripts/false404/fault_relay.py --rate 0.3 --seed 1 --bad 1 --log relay.jsonl
# prints {"relay": "http://127.0.0.1:PORT", ...}; then give VC3D
#   http://127.0.0.1:PORT/BUCKET_PATH
# instead of https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/BUCKET_PATH
# stop it with Ctrl-C; it prints its counts
```

- `PORT`: the port it picked (the first JSON line); pass `--port` to fix it.
- `BUCKET_PATH`: the volume's path in the open-data bucket, such as a scan's `.zarr` folder.
- `relay.jsonl`: the request log, one JSON line per request.

The published renders used `--rate 0.3 --seed 1 --bad 1` on a 256 x 256 crop of PHerc0139 w035, which chose 6 chunk keys ([receipts](../evidence/2026-10-12-false-404/README.md)).

Run against a fake local bucket instead (synthetic data: `python3 -m http.server 8901` over a folder holding `v.zarr/0/.zarray` and four 64-byte chunks `v.zarr/0/0/0/0` to `3`), with `--upstream http://127.0.0.1:8901 --rate 0.5 --seed 1 --bad 1 --port 8902`, two curl GETs per chunk, a GET of `.zarray`, a HEAD and a GET of a missing chunk `0/0/0/9`, then Ctrl-C, it printed:

```
GET 0/0/0/0 try 1: 404
GET 0/0/0/0 try 2: 200
GET 0/0/0/1 try 1: 200
GET 0/0/0/1 try 2: 200
GET 0/0/0/2 try 1: 404
GET 0/0/0/2 try 2: 200
GET .zarray: 200
HEAD 0/0/0/1: 200
{"relay": "http://127.0.0.1:8902", "upstream": "http://127.0.0.1:8901", "rate": 0.5, "seed": "1", "bad": 1}
{"requests": 11, "injected": 4, "injected_keys": 4, "upstream_false_404": 0, "upstream_404": 0, "upstream_errors": 0}
```

A chosen GET looks like this (headers trimmed; the run above was made before `4277e97`, which dropped a second `Server: fault-relay ...` line from this answer):

```
HTTP/1.1 404 Not Found
Content-Type: application/xml
Server: AmazonS3
x-amz-request-id: 087C326AE6CA5359
...
<Error><Code>NoSuchBucket</Code><Message>The specified bucket does not exist</Message><BucketName>127</BucketName>...
```

It worked when the first line names the relay URL, chosen chunks answer 404 then 200, metadata and HEAD answer 200, and the counts at the end show `injected` greater than 0 when `--rate` is above 0.

## Checks and controls

- **Control run with no false 404s.** The relay proves nothing on its own; the check is the client's output. Render the same crop three times: `reference` (no relay or `--rate 0`, empty cache), `faulty` (through the relay, a second empty cache) and `rerun` (no false 404s, on the faulty run's cache). An unfixed client must show the holes in `faulty` and keep them in `rerun`; a fixed one must match `reference` both times. On villa `main` at `25f3c93`, the w035 crop with 6 replayed false 404s left 12 empty markers and 19.18 % zero samples, in both `faulty` and `rerun`; with the fix there were 0 markers and 0.03 % zeros, the same as the clean render, on Linux and macOS ([receipts](../evidence/2026-10-12-false-404/README.md)).
- **Fixed choice.** The chosen keys depend only on `--seed`, `--rate` and the path, so a rerun with the same settings injects into the same keys. `tests/test_false404_relay.py` checks that the choice repeats, is near the rate (250 to 350 of 1,000 keys at 0.3), changes with the seed, and is none at rate 0 and all at rate 1.
- **Count check.** The final counts and `relay.jsonl` say exactly which requests got the false 404 (`"injected": true`). If `injected` is 0, nothing was replayed, and a clean render proves nothing about the fix.
- **Real false 404s are kept out.** `upstream_false_404` counts bucket 404s that were not `NoSuchKey` and were retried. A run where it is above 0 met the real bug upstream; the client still saw only the chosen ones.

Claim label: Sourced fact for what S3 sent (measured 2026-10-08, [log](../logs/2026-10-12-upstream-reports.md)); the relay's answers are a replay of it, not the live fault.

## Commands and options

### `python3 scripts/false404/fault_relay.py`

```
usage: fault_relay.py [-h] [--upstream UPSTREAM] [--rate RATE] [--seed SEED]
                      [--bad BAD] [--port PORT] [--log LOG]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--upstream UPSTREAM` | `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (`BUCKET`) | The origin to relay to, `http` or `https`; only scheme and host are kept, and the request path is appended |
| `--rate RATE` | `0.3` | Share of chunk keys given false 404s, from 0 (none) to 1 (all) |
| `--seed SEED` | `1` | Text that fixes which keys are chosen; `1` and `"1"` choose the same keys |
| `--bad BAD` | `1` | False 404s per chosen key before the real answer; 0 injects none |
| `--port PORT` | `0` | Port on `127.0.0.1`; 0 lets the system pick a free one, printed in the first line |
| `--log LOG` | none | Append one JSON line per request to this file |

The upstream request timeout (60 s) and the retry count (`UPSTREAM_TRIES = 10`) are fixed in the code; the `Relay` class takes `timeout=`.

## Python API

The tests load the script as a module (`importlib.util.spec_from_file_location("fault_relay", "scripts/false404/fault_relay.py")`); it is not inside `kit/`.

```python
with Relay("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com", rate=0.3, seed=1, bad=1) as relay:
    url = relay.url_for("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PATH/volume.zarr/")
    # read url with any zarr client, then look at relay.stats
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `is_chunk(path)` | bool | Nothing | True when the last part of the URL path is digits, dot-separated or not (`CHUNK`); `0/c/1/2/3` counts too |
| `chosen(path, seed, rate)` | bool | Nothing | True when `rate` is above 0, `path` is a chunk, and the first 8 bytes of SHA-256 of `SEED:PATH` (query string dropped), read as a fraction of 2^64, are below `rate` |
| `s3_code(body)` | str or None | Nothing | The text of the first `<Code>...</Code>` in an S3 error body, or None |
| `false_404(path, n, bucket)` | `(headers, body)` | Nothing | The `NoSuchBucket` answer: XML body, `Content-Type: application/xml`, `Server: AmazonS3`, an `x-amz-request-id` from SHA-256 of `PATH:N`, `x-amz-id-2: fault-relay`, `Date` |
| `Relay(upstream=BUCKET, rate=0.0, seed=1, bad=1, log=None, port=0, timeout=60, opener=None, sleep=time.sleep)` | A relay; use it as a context manager, which starts and stops the server thread | `ValueError` for an upstream that is not `http` or `https` with a host | `.base` is its URL, `.stats` its counts, `.origin` the upstream origin. Note the class default `rate=0.0`, unlike the command's 0.3 |
| `Relay.url_for(url)` | str, the relay URL for an upstream URL | `ValueError` when the URL is not under the relay's origin | Keeps the path, drops the query |
| `Relay.answer(method, path, rng=None)` | `(status, headers, body)` | Nothing of its own | What one request gets; logs it |
| `main(argv=None)` | `0` after Ctrl-C | `ValueError` as above; `OSError` when the port is taken | The command line |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| HTTP requests | `GET` and `HEAD` on `http://127.0.0.1:PORT/PATH`, with an optional `Range` header | Other methods get the standard library's 501 answer. `PATH` is appended to the upstream origin as is |
| Upstream | An S3 bucket (or any HTTP server) over `http` or `https` | The bucket name in the fake answer is the first dot-separated part of the host (`vesuvius-challenge-open-data` for the default; `127` for `127.0.0.1`) |

Zarr v2 keys (`0/12/3/4`, `0/12.3.4`) and v3 keys (`0/c/1/2/3`) count as chunks; any key whose last part is not digits is metadata.

## Outputs

It prints two JSON lines on stdout: one when it starts, one when it stops with Ctrl-C.

| Field | Type | Meaning |
| --- | --- | --- |
| `relay` | str | The relay's URL, `http://127.0.0.1:PORT` |
| `upstream` | str | The upstream origin |
| `rate`, `seed`, `bad` | float, str, int | The settings in use |
| `requests` | int | Requests answered |
| `injected` | int | False 404s sent |
| `injected_keys` | int | Distinct chosen keys that were requested |
| `upstream_false_404` | int | Bucket 404s that were not `NoSuchKey`, retried and hidden from the client |
| `upstream_404` | int | Real 404s passed through (a `NoSuchKey`, or a 404 with no S3 code, or any 404 on HEAD) |
| `upstream_errors` | int | Connection errors and unreadable error bodies, retried |

With `--log LOG`, one JSON line per request, flushed as it is written:

| Field | Type | Meaning |
| --- | --- | --- |
| `t` | float | Unix time in seconds, 3 decimals |
| `method` | str | `GET` or `HEAD` |
| `path` | str | The request path as sent |
| `range` | str or null | The `Range` header |
| `status` | int | Status sent to the client |
| `injected` | bool | Whether this answer was a false 404 |
| `get` | int or null | For a chosen key, the number of this GET of it (1 for the first); null otherwise |

Answers carry the upstream's status, headers (hop-by-hop ones dropped) and body. When the upstream never answers after 10 tries, the client gets `502` with the body `fault-relay: the bucket did not answer`.

| Exit code | Meaning |
| --- | --- |
| `0` | Stopped with Ctrl-C (SIGINT) after printing the counts. Another signal, such as SIGTERM, ends it without the counts line; the log is still complete |
| `1` | A Python traceback: a bad `--upstream` (`ValueError`) or a port already in use (`OSError`) |
| `2` | A usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as `error: argument --rate: invalid float value: 'x'` | Check the command against Commands and options |
| `ValueError: not an http(s) origin: ftp://example` and a traceback, exit code 1 | `--upstream` is not an `http` or `https` URL with a host | Give an origin such as `https://HOST` |
| `ValueError: URL is not under ORIGIN` from `url_for` | The URL given to `Relay.url_for` is on another host | Pass a URL under the relay's upstream |
| `OSError: [Errno 98] Address already in use` and a traceback | `--port` is taken | Use another port, or `--port 0` |
| The client gets `502` and `fault-relay: the bucket did not answer` | 10 tries upstream all failed (network errors, or 404s that were not `NoSuchKey`) | Check the network and the upstream URL; `upstream_errors` and `upstream_false_404` in the counts say which |
| `injected` stays 0 | `--rate 0`, `--bad 0`, no chunk key requested, or the client only sent HEAD | Raise `--rate`; check the client reads chunks by GET through the relay URL |

## How it works

1. Start a threaded HTTP server on `127.0.0.1:PORT` (`http.server.ThreadingHTTPServer`, HTTP/1.1).
2. For each GET, decide whether the path is chosen (`chosen`): it must be a chunk key (`CHUNK = \d+(\.\d+)*` on the last path part) and the first 8 bytes of SHA-256 of `SEED:PATH`, as a fraction of 2^64, must be below `--rate`. Count GETs per chosen chunk key (the path without its query string) under a lock, so `KEY?x-id=GetObject` and `KEY` share one count.
3. If this is one of the first `--bad` GETs of a chosen path, answer with `false_404`: status 404, `Content-Type: application/xml`, `Server: AmazonS3`, an `x-amz-request-id` of 16 hex digits from SHA-256 of `PATH:N`, and the body `<Error><Code>NoSuchBucket</Code><Message>The specified bucket does not exist</Message>...`, as S3 sent in villa #2058.
4. Otherwise forward the request to the upstream with `urllib.request` (a new connection each time, `User-Agent: fault-relay`, the client's `Range` header kept, 60 s timeout). Return the upstream's status, headers and body; drop hop-by-hop headers (`HOP`) and set `Content-Length` to the body's length (for HEAD, the upstream's). Each answer carries one `Server` and one `Date` header: the upstream's (or the false 404's `Server: AmazonS3`) when it has them, the relay's own otherwise.
5. A GET that comes back 404 with an S3 code other than `NoSuchKey` is a real false 404: count it in `upstream_false_404`, wait `min(2.0, 0.1 * 2 ** attempt)` seconds and try again. A connection error or an unreadable error body counts in `upstream_errors` and waits `min(4.0, 0.25 * 2 ** attempt)`. After `UPSTREAM_TRIES = 10` tries, answer 502.
6. Log each answer as one JSON line when `--log` is set.

## Cost and time

Seconds of CPU; the time is the client's and the bucket's. On a fake local bucket, 11 requests with start and stop took about 2.7 s (2026-10-16, cloud container, synthetic data). The worst case for one request is 10 tries: up to about 15 s of waits for repeated false 404s and up to about 28 s for repeated connection errors, plus timeouts of 60 s each. Throughput against the real bucket: Not measured. It rents nothing and needs no GPU or Modal.

## For agents

- **Command:** `python3 scripts/false404/fault_relay.py --rate 0.3 --seed 1 --bad 1 --log relay.jsonl`, run in the background; read the relay URL from the first stdout line and stop it with SIGINT.
- **Parse:** the first stdout line's `relay`; the last line's `injected`, `injected_keys` and `upstream_false_404`; each line of `relay.jsonl`, where `"injected": true` marks a replayed false 404.
- **Rerun:** Safe. The same `--seed` and `--rate` choose the same keys. `--log` appends to the file, so use a new file per run, and give the client a fresh cache for each faulty run.
- **Success:** Exit code 0 after SIGINT, and `injected` above 0 when a false 404 was meant to be replayed.
- **Not a pass:** A clean client render with `injected` 0; a fix judged without the `reference` and `rerun` renders; a render compared with a reference made on another machine (Linux and macOS renders differ byte for byte).
- **Go-ahead:** Nothing to run it. Posting results to villa needs Chase's yes.
- **Never:** Commit renders, layers or chunk data (no scroll data in git); point it at a target scroll in public work; describe a replayed false 404 as a live measurement; expose it beyond `127.0.0.1`.

## Tests

```bash
python -m unittest tests.test_false404_relay -v
```

Eight tests, about 3 s, standard library only, against a local S3-like server over a temporary folder. They cover which keys count as chunks, a choice that is fixed by seed and near the rate, a chosen key that gets two false 404s with S3's headers and then its data (also with a `Range`), metadata and HEAD passing through, the counts and the log lines, rate 0 passing everything including a real `NoSuchKey`, a bucket false 404 retried and hidden from the client, `url_for`, one count per key whatever the query string, and one `Server` and one `Date` header on both the false 404 and the bucket's answer. They do not run VC3D, the real bucket, the 502 path, or the command line.

## History

- 2026-10-12: first version, used for the renders behind villa #2058 and its draft fix #2060 (`6be238e`).
- 2026-10-17: each answer carries one `Server` and one `Date` header; before, the standard library's handler sent its own `Server: fault-relay ...` and `Date` ahead of the relayed or replayed ones, so a client reading the first `Server` header saw the relay's (`4277e97`).
- 2026-10-17: false 404s are counted per chunk key; before, the count was per path with its query string, so `KEY?x-id=GetObject` and `KEY` each got their own `--bad` false 404s (`e2f4cc5`).

## Related

- [The upstream reports log](../logs/2026-10-12-upstream-reports.md): what S3 sent, the bug, the fix and its limits.
- [The false-404 receipts](../evidence/2026-10-12-false-404/README.md): test logs, render summaries and `relay.jsonl` from the published runs (frozen; do not edit).
- [`fetch`](fetch.md): downloads from the same bucket directly.
- [villa #2058](https://github.com/ScrollPrize/villa/issues/2058) and [villa #2060](https://github.com/ScrollPrize/villa/pull/2060): the issue and the draft fix.
