# s3retry: tell S3's false 404s from missing keys, and retry them

`kit/s3retry.py` counts an S3 HTTP 404 as a missing key only when its error body says `NoSuchKey` (or names no S3 code), asks again after any other 404, and refuses remote zarr paths in tools that would read them with silent holes.

| Field | Value |
| --- | --- |
| Id | `s3retry` |
| Status | Current |
| Kind | kit module |
| Area | Data and downloads |
| Run | None (a library): `from kit import s3retry` |
| Code | `kit/s3retry.py` |
| Tests | `tests/test_s3retry.py`, `tests/test_cutoff_reads.py` |
| Needs | Python 3 standard library only (run here on Python 3.13) |
| Runs on | Any machine. One `key_state` check on the open-data bucket took about 0.6 s from a cloud container (59 keys in 37.9 s, measured 2026-10-16, 4-core Intel Xeon 2.80 GHz cloud container); a key that answers false 404s every time costs 10 requests and 11.1 s of backoff |
| Network | The host in each URL it is given, over HTTP or HTTPS, through the default opener's proxy settings (`HTTPS_PROXY`, `NO_PROXY`). In kit: the open-data bucket (`vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` and `vesuvius-challenge-open-data.s3.amazonaws.com`). Anonymous; it sends no credentials |
| Writes | Nothing. It returns answers and raises errors; the callers write files |
| Go-ahead | Not needed: it only reads public objects |
| Released | Public `main` from the change that adds it (24 Oct 2026). Earlier copies ship inside the AutoPipeline release branches (`submission/progress-2026-10` from 2026-10-14 to `submission/progress-2026-10-fix4`); this one adds two small fixes (an opener imported only when used, fewer than one try taken as one) |
| Guide | [VC3D and S3's false 404s](../vc3d-false-404.md) |
| Checked | 2026-10-24 against commit `77aea1f` |

## What it does

A **false 404** (the glossary term) is an HTTP 404 "not found" that Amazon S3 sends for a key the bucket does hold. From one cloud machine on 8 October 2026, the open-data bucket answered HTTP 404 with an S3 error body naming `NoSuchBucket` for chunks that exist: 102 of 316 GETs at 32 workers, 16 of 80 at 1 worker, 19 of 60 separate curl processes, 0 of 60 requests on one reused connection and 0 of 1,580 HEAD requests ([log](../logs/2026-10-12-upstream-reports.md)). A reader that takes every 404 for a missing chunk blanks real data: zarr reads a missing chunk as its `fill_value`, and VC3D caches a 404 chunk as empty for good.

This module is the rule kit's own HTTP readers use. A 404 is a missing key only when its body names `NoSuchKey`, or carries no S3 error code at all (a server that is not S3). Any other 404 is asked again, up to 10 attempts in all, and a key that answers that way every time is reported as unknown, never as missing. It has three entry points: `open_url` (fetch with false 404s retried), `key_state` (is this object present, missing or unknown) and `refuse_remote` (stop a tool that would read a remote zarr through the zarr package, which turns a 404 into fill values with no error).

It does not fix VC3D. VC3D reads volumes itself, through libcurl, and takes any 404 for a missing chunk; `python -m kit s3relay` gives it a local relay instead ([s3relay](s3relay.md), [vc3dfix](vc3dfix.md)), and `python -m kit vc3dcache` checks VC3D's cache afterward ([vc3d-cache](vc3d-cache.md)). It does not retry network errors or HTTP errors other than 404: those pass through to the caller, which has its own retries (`kit fetch` tries each object four times). It makes no claim about the data it fetches.

Callers in this repository (2026-10-24): `kit fetch` (listing and every object), the remote chunk store of [vc3d-audit](vc3d-audit.md) (`kit/vc3d_audit.py`), `kit/vc3d_cache.py` and `kit/s3relay.py`.

### The copies in the AutoPipeline release

The AutoPipeline release branches (`submission/progress-2026-10` to `submission/progress-2026-10-fix4`) carry an earlier copy of this file under `submissions/.../autopipeline/kit/`. It differs from this one only in importing `urllib.request` and `http.client` at the top and in how it treats `tries` below 1.

## When to use it

- Any new kit code that downloads from S3 with urllib: call `open_url` instead of `urllib.request.urlopen`, so a false 404 is asked again instead of raised as missing.
- Checking whether an object exists, such as a chunk VC3D cached as empty: `key_state`, which never calls a key missing on a false 404.
- A tool that reads a zarr store through the zarr package: call `refuse_remote(path, "kit TOOL")` first, so a URL is refused instead of read with holes.

Do not use it:

- To give VC3D a remote volume: VC3D does its own HTTP. Use the relay: `python -m kit s3relay URL` ([vc3dfix](vc3dfix.md)).
- To download a whole prefix: use [fetch](fetch.md) (`python -m kit fetch PREFIX DEST`), which already uses `open_url`.
- To find and repair chunks VC3D already cached as empty: `python -m kit vc3dcache URL` ([vc3d-cache](vc3d-cache.md)).
- As a retry for network failures, 5xx answers or cut-off transfers: `open_url` passes those through; retry in the caller.

## Quick start

From the repository root:

```bash
python3 - <<'EOF'
from kit import s3retry
B = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr"
counter = {}
print(s3retry.key_state(B + "/0/.zarray", counter=counter))
print(s3retry.key_state(B + "/0/no-such-chunk", counter=counter))
with s3retry.open_url(B + "/0/.zarray", counter=counter) as resp:
    print(resp.status, resp.read()[:40])
print(counter)
EOF
```

It printed, on 2026-10-16 from a cloud container (1.5 s in all):

```
('present', 'HTTP 206')
('missing', 'HTTP 404 NoSuchKey')
200 b'{\n  "shape": [\n    20974,\n    6621,\n    '
{}
```

It worked when the existing key is `present`, the made-up key is `missing` with `NoSuchKey`, and `open_url` returns the body. `counter` stays empty until a false 404 happens; then `counter["false_404"]` counts them.

## Checks and controls

- **A missing key must still come back missing.** The made-up key above answers `NoSuchKey` and `key_state` says `missing` at once, with one request: the retry rule does not hide real misses. A key that exists answers `present`. A bucket that does not exist answers `NoSuchBucket` every time, and `key_state` says `('unknown', 'HTTP 404 S3 answered 404 NoSuchBucket 10 times; not taken as a missing key')` (run 2026-10-16), never missing.
- **The retry must be seen to work and to fail.** The tests run a local server that answers like S3, false 404s included (`S3LikeServer` in `tests/vc3d_fakes.py`): a key with two false 404s is read on the third request; a key in `always_false` is `unknown`; a missing key is `missing`. On the same server, run 2026-10-16: `key_state` gave `present` (`HTTP 206`), `missing` (`HTTP 404 NoSuchKey`) and `unknown` for the three cases.
- **Later rates.** On 2026-10-12, 40 of 40 fresh ranged GETs were fine ([log](../logs/2026-10-12-upstream-reports.md)); on 2026-10-16, 59 listed chunks of PHerc0139's 9.362 um volume and 40 other keys, each a one-byte GET on a new connection from the same kind of cloud container, gave 0 false 404s. Whether a machine without that cloud's egress proxy ever sees them is not known.
- **What it cannot see.** A false 404 whose body was cut off has no readable code: `open_url` raises the network error from the read, and `key_state` says unknown. Through an opener that keeps connections open (`kit/keepalive.py`), a retry can go out on the connection that just answered the false 404 (see How it works).

Claim label: Sourced fact, for the false-404 counts measured from one cloud machine on 8 October 2026 and the 0 of 99 measured on 16 October; the module's own answers (present, missing, unknown) state one request's outcome and make no claim about the data.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `error_code(body)` | str, the text of the first `<Code>...</Code>` (such as `NoSuchKey`), or `None` | Nothing | `body` is bytes or str. `None` for an empty body or one without an S3 `<Code>` element |
| `false_404(status, body)` | bool | Nothing | True only when `status` is 404 and the body names an S3 code other than `NoSuchKey` (`MISSING_CODE`). A 404 with no S3 code is not false: it is taken as missing |
| `open_url(req, opener=None, timeout=60, tries=TRIES, sleep=time.sleep, counter=None)` | The opener's response: a context manager with `.status`, `.headers` and `.read()` | `urllib.error.HTTPError` for a real 404 (raised again with its body, so `exc.read()` still works); after `tries` false 404s, an `HTTPError` with code 404, the false body, and the reason `S3 answered 404 CODE N times; not taken as a missing key`; any other `HTTPError`, `URLError`, `OSError` or `http.client.HTTPException` from the opener, unretried | `req` is a URL string or a `urllib.request.Request`. `opener` defaults to `urllib.request.urlopen`. Between false 404s it sleeps `min(2.0, 0.1 * 2 ** attempt)` s. `counter`: a dict whose `"false_404"` entry is created and incremented per false 404. A `tries` below 1 is taken as 1 |
| `key_state(url, opener=None, timeout=30, tries=TRIES, sleep=time.sleep, counter=None)` | `(state, detail)`: state `"present"` (`PRESENT`), `"missing"` (`MISSING`) or `"unknown"` (`UNKNOWN`); detail such as `HTTP 206`, `HTTP 404 NoSuchKey`, `HTTP 404 (no S3 code)`, `HTTP 403 Forbidden`, or the network error's reason | Nothing for HTTP or network failures, which become `unknown` | One GET with `Range: bytes=0-0` and `User-Agent: kit-s3retry`, through `open_url`. Present on 200 or 206; missing on a 404 that names `NoSuchKey` or no code; unknown on anything else (403, which S3 also sends for missing keys in buckets it will not list; 5xx; network errors and cut-off reads; a false 404 every time) |
| `refuse_remote(path, what="this command")` | `path`, unchanged, when it is local | `ValueError` when `path` matches `REMOTE`: a URL starting `http://`, `https://`, `s3://`, `gs://`, `gcs://`, `az://` or `abfs://`, any case | `what` names the tool in the message, such as `"kit layers"` |

Module constants: `MISSING_CODE = "NoSuchKey"`; `TRIES = 10` (attempts in all); `PRESENT, MISSING, UNKNOWN = "present", "missing", "unknown"`; `REMOTE`, the compiled pattern `^(https?|s3|gs|gcs|az|abfs)://` (case-insensitive).

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| `req` (`open_url`) | A URL string or `urllib.request.Request` | Any method the opener supports; kit sends GETs. Headers you set (such as `Range`) go out unchanged |
| `url` (`key_state`) | An http or https URL of one object | An `s3://` URL is not translated here; give the https form, such as `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/KEY` |
| `opener` | A callable `opener(req, timeout=SECONDS)` that returns a response or raises `urllib.error.HTTPError` as `urllib.request.urlopen` does | Tests pass fakes; `kit/keepalive.py`'s pooled opener also fits |
| `body` (`error_code`, `false_404`) | bytes or str | S3's XML error document, `<Error><Code>...</Code>...</Error>` |
| `path` (`refuse_remote`) | str or path | Anything; only the start of its text is checked |

## Outputs

Return values only (see Python API); it prints nothing and writes no file. The texts callers pass on:

| Text | Where | Meaning |
| --- | --- | --- |
| `HTTP 206` or `HTTP 200` | `key_state` detail, present | The first byte came back |
| `HTTP 404 NoSuchKey`, `HTTP 404 (no S3 code)` | `key_state` detail, missing | S3 says the key does not exist, or a server that is not S3 said 404 |
| `HTTP CODE REASON` | `key_state` detail, unknown | Any other HTTP answer, including the give-up reason after `tries` false 404s |
| The network error's reason | `key_state` detail, unknown | Such as `[Errno 111] Connection refused` |
| `S3 answered 404 CODE N times; not taken as a missing key` | `open_url` give-up `HTTPError.reason` | N is `tries`; CODE is the S3 code it kept getting, such as `NoSuchBucket` |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `ValueError: WHAT reads local zarr only: over the network a chunk that answers 404 reads as fill_value with no error, and S3 sometimes answers 404 for chunks that exist (kit/s3retry.py). Fetch it first: python -m kit fetch PREFIX DEST` | Code that called `refuse_remote` before reading zarr through the zarr package was given a URL (no command in this repository calls it yet) | `python -m kit fetch PREFIX DEST` ([fetch](fetch.md)), then pass the local `DEST` |
| `urllib.error.HTTPError: HTTP Error 404: S3 answered 404 NoSuchBucket 10 times; not taken as a missing key` | The key answered a false 404 on every attempt. `exc.code` is still 404, so a caller that checks only the code takes it as missing | Wait and run again. In code, test `s3retry.false_404(404, exc.read())` before treating a 404 as missing |
| `('unknown', 'HTTP 404 S3 answered 404 NoSuchBucket 10 times; not taken as a missing key')` from `key_state` | The same, through `key_state` | Do not delete or skip the key on this answer; check again later |
| `('unknown', 'HTTP 403 Forbidden')` | S3 refused the request; it also answers 403 for missing keys in buckets it will not list | Check the URL, the bucket and whether it allows anonymous reads |
| `('unknown', '[Errno 111] Connection refused')` or another network reason | No connection, a timeout, or a transfer cut off mid-body (`IncompleteRead`) | Retry; check the network or proxy |
| `urllib.error.URLError`, `TimeoutError` or `http.client.IncompleteRead` raised by `open_url` | `open_url` retries only false 404s; network errors pass through | Retry in the caller (`kit fetch` tries each object four times) |
| `urllib.error.HTTPError` with a code other than 404, raised by `open_url` | Passed through unretried | Handle in the caller |

## How it works

1. **The code.** `error_code` finds the first `<Code>NAME</Code>` in the body with the pattern `_CODE` (`<Code>\s*([A-Za-z0-9_.-]+)\s*</Code>`). `false_404` is true when the status is 404 and that code exists and is not `MISSING_CODE` (`NoSuchKey`).
2. **`open_url`.** Up to `tries` times (default `TRIES = 10`): call the opener. On an `HTTPError` with code 404, read and close its body. A real 404 is raised again as a fresh `HTTPError` carrying the same body. A false 404 counts in `counter`, then the loop sleeps `_backoff(attempt) = min(2.0, 0.1 * 2 ** attempt)` (0.1, 0.2, 0.4, 0.8, 1.6, then 2.0 s; 11.1 s over the 9 pauses of 10 attempts) and asks again; after the last attempt it raises the give-up `HTTPError`. Anything else the opener raises passes through.
3. **Why 10.** At the worst rate measured on 8 October (32 percent of connections), ten independent attempts all failing has a chance of about `0.32 ** 10`, 1e-5 (the comment beside `TRIES`). That holds only if attempts are independent.
4. **New connections.** The default opener, `urllib.request.urlopen`, opens a new connection for every call, so each retry is on a new connection, which is what clears a false 404 (8 October: 0 of 60 requests failed on one good reused connection). An opener that keeps connections, such as `kit/keepalive.py`'s (the default of `audit`'s chunk store), takes the most recently returned connection first and does not close a connection after a 404, so a retry there can go out on the same bad connection (Interpretation from the code; not tested, since no false 404 was seen on 16 October).
5. **`key_state`.** A one-byte ranged GET through `open_url` (`Range: bytes=0-0`, timeout 30 s). The response is read and closed; 200 or 206 is present. On an `HTTPError` 404, the body (kept by `open_url`) decides: no false code, missing; a false code (the give-up case), unknown. Any other HTTP code, and `URLError`, `OSError` or `http.client.HTTPException` (which includes a cut-off read), is unknown. A HEAD answer has no body, so it would carry no S3 code to tell a false 404 from a missing key; the one-byte GET does.
6. **`refuse_remote`.** Matches the path's text against `REMOTE` and raises; it opens nothing.

## Cost and time

Measured 2026-10-16 from a cloud container (4-core Intel Xeon 2.80 GHz, through its HTTPS proxy): one `key_state` on the open-data bucket took 0.1 to 2.2 s, about 0.64 s on average over 59 keys (37.9 s); a key that answers false 404s every time costs `TRIES` = 10 requests and 11.1 s of sleep plus the requests. Memory is one response body at a time. It rents nothing and needs no GPU.

## For agents

- **Command:** In Python: `from kit import s3retry`; `s3retry.key_state(URL)` for whether an object exists, `s3retry.open_url(URL_OR_REQUEST, timeout=120)` in place of `urllib.request.urlopen`, `s3retry.refuse_remote(PATH, "kit TOOL")` before reading a zarr with the zarr package. Its command lines are `python -m kit s3relay` and `python -m kit vc3dcache` ([vc3dfix](vc3dfix.md)).
- **Parse:** `key_state` returns `(state, detail)`; `state` is exactly `"present"`, `"missing"` or `"unknown"`. From `open_url`, a raised `HTTPError` with code 404 is a missing key only if `s3retry.false_404(404, exc.read())` is False. `counter.get("false_404", 0)` counts the false answers seen.
- **Rerun:** Safe: it only reads. Each call makes new requests (up to `tries` per key).
- **Success:** `present` or `missing` from `key_state`; a response from `open_url`.
- **Not a pass:** `unknown` is not missing and not present: never delete an empty-chunk marker, skip a chunk or call data absent on it. An `HTTPError` 404 from `open_url` whose body names a code other than `NoSuchKey` is a give-up, not a missing key.
- **Go-ahead:** Nothing; it reads public objects anonymously.
- **Never:** Treat every 404 as missing in new code (use `false_404`); read a remote zarr through the zarr package (fetch it first); retry forever on `unknown` in a loop with no limit.

## Tests

```bash
python3 -m unittest tests.test_s3retry tests.test_cutoff_reads -v
```

`tests/test_s3retry.py` (8 tests) covers the code parser and `false_404` (NoSuchBucket, NoSuchKey, a body with no code, a 403), `refuse_remote` on https, s3 and upper-case GS URLs and on a local path, `open_url` retrying two false 404s, raising a real 404 at once with its body, giving up after `tries` with the reason, and passing a 500 through, and, against `S3LikeServer`, `key_state`'s three states, `audit`'s chunk store and `kit fetch` surviving false 404s. `tests/test_cutoff_reads.py` checks that a cut-off read is `unknown` in `key_state` and is reported, not a crash, in its callers. Both ran in about 5 s on 2026-10-24, all passing. They use local servers only; nothing tests against the real bucket, and no test covers a keep-alive opener.

## History

- 2026-10-24: on public `main`, with `kit fetch` now asking again after a false 404 (`77aea1f`).
- 2026-10-15: the copy in AutoPipeline 0.1.4 (`603fe14`, branch `submission/progress-2026-10-fix4`). Made before it was public: the first version of 8 October (a 404 is missing only on `NoSuchKey`, false 404s asked again up to 10 times, `key_state`, `refuse_remote`; [log](../logs/2026-10-12-upstream-reports.md)); the give-up reason `S3 answered 404 CODE N times; not taken as a missing key` (8 October); a transfer cut off mid-body is `unknown` in `key_state` instead of a crash (9 October).

## Related

- [s3relay](s3relay.md): the local relay that applies this rule for VC3D, which does its own HTTP.
- [vc3d-cache](vc3d-cache.md): finds VC3D's empty-chunk markers and checks each with `key_state`.
- [vc3d-audit](vc3d-audit.md): the integrity audit, whose remote chunk store retries false 404s the same way.
- [fetch](fetch.md): `python -m kit fetch`, which downloads through `open_url`.
- [keepalive](keepalive.md): the pooled opener whose connection reuse matters for retries.
- [false404-relay](false404-relay.md): `scripts/false404/fault_relay.py`, which replays false 404s in front of the bucket.
- [The upstream reports log](../logs/2026-10-12-upstream-reports.md): the measurements this rule rests on, and the native fix proposed to villa ([issue #2058](https://github.com/ScrollPrize/villa/issues/2058), [PR #2060](https://github.com/ScrollPrize/villa/pull/2060)).
