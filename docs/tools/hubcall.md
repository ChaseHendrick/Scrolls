# hubcall: Hugging Face Hub calls that back off together on a 429

Wraps Hugging Face Hub calls so a 429 (rate limited) or a passing 5xx waits and retries on one fixed schedule, every process on the machine shares one cool-down, and a local log names the busiest caller.

| Field | Value |
| --- | --- |
| Id | `hubcall` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Compute and cost |
| Run | `python -m kit hubcall report`, `python -m kit.hubcall report`, `from kit import hubcall` |
| Code | `kit/hubcall.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_hubcall.py` |
| Needs | Python 3.10 or newer, standard library only; `huggingface_hub` only for `hf_api()`, which builds an `HfApi` |
| Runs on | Any machine. `report` over a short log took 0.17 s wall (measured 2026-11-20, 4-core cloud container) |
| Network | None of its own: it runs the Hub calls you give it, and contacts whatever host they contact |
| Writes | `hubcalls.jsonl` (the call log) and `hub-cooldown.json` (the shared cool-down) in the kit cache folder: `$KIT_HUBCALL_DIR`, else `$XDG_CACHE_HOME/kit`, else `~/.cache/kit`. `report` writes nothing |
| Go-ahead | Not needed: it only retries calls your own code makes |
| Released | Public `main` from the PR that adds this page (2026-11-20) |
| Checked | 2026-11-20 against commit `357d2bd` |

## What it does

The Hugging Face Hub answers HTTP 429 when an account makes too many API calls in a short time. A script that fails at once on a 429 loses its work; a script that retries on its own fixed timer, run in twenty copies on one machine, keeps the account over the limit. A 5xx answer or a dropped connection can also come and go within seconds.

`hubcall.call(fn, ...)` runs one call and, on a 429, waits (the server's `Retry-After`, else 5, 10, 20, 40, 80 and 120 s, plus up to 2 s of jitter) and calls again. On a 5xx or a dropped connection it waits 2 s, then 4 s, but only for reads: a write may have been applied before its answer was lost, so a write is never repeated after a 5xx. It gives up and raises the last error once the total wait would pass 600 s (120 s inside a Hugging Face Job, where `JOB_ID` is set). Other errors, such as a 404, are raised at once.

Every process on one machine backs off together: a 429 writes a cool-down time to `hub-cooldown.json`, and every `call()` on that machine waits it out before calling. Each call also adds one line to `hubcalls.jsonl` (time, caller, method, outcome, seconds waited, pid), and `python -m kit hubcall report` counts them per caller, busiest first, so the next time the limit is hit the caller to slow down is named from data.

`hubcall.wrap(api, who)` returns a stand-in for an `HfApi` whose every public method goes through `call()`; a listing that returns a generator is read whole inside the retry, so a 429 halfway through a listing is retried too. It does not lower your call rate by itself and does not know the Hub's actual limits.

Note: `huggingface_hub` itself already retries 429 and 5xx answers on its paginated listings (`list_models` and other listings built on its pagination helper; checked in version 2.4.0, 20 Nov 2026), but not on single calls such as `model_info`. Inside a wrapped listing those library retries are invisible to the hubcall log and do not set the shared cool-down, and hubcall's own waits come on top of them.

## When to use it

- Any script or tool that makes many Hub calls, or runs in several copies on one machine: build its client with `hubcall.wrap(HfApi(), "my-tool")` or `hubcall.hf_api("my-tool")`.
- A single Hub call you want retried on the same rule: `hubcall.call(api.upload_file, ..., who="my-tool", retry_net=False)` for a write.
- After a run of 429s: `python -m kit hubcall report` to see which caller made the most calls.

Do not use it:

- To retry calls to hosts other than the Hub with their own rate rules; it treats every 429 the same way.
- As a reason to poll: a loop that reads the Hub every few seconds still uses up the limit. Read less often instead.
- For downloads of large files where the library's own resumable download is the better retry.

## Quick start

```bash
export KIT_HUBCALL_DIR=$(mktemp -d)
python3 -c '
from kit import hubcall
import urllib.error
n = [0]
def f():
    n[0] += 1
    if n[0] == 1:
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {"Retry-After": "1"}, None)
    return "ok"
print(hubcall.call(f, who="demo", method="model_info", say=print))
'
python -m kit hubcall report
```

The function `f` stands in for a Hub call that is refused once with a 429 and `Retry-After: 1`. Printed (2026-11-20, cloud container):

```
kit hubcall: demo model_info: 429; waiting 1 s
ok
2 Hub call(s) in the last 24 h on this machine
       2  demo model_info  1 rate-limited  1 s waited
```

It worked when the call returns after one wait and the report counts two calls, one rate limited.

## Checks and controls

The retry rule can fail: the tests run it against a local HTTP server that answers with real 429s, `Retry-After` headers, 5xx answers and dropped connections, and check the number of requests and the waits exactly. A mutant whose 429 detection is turned off must fail the same bar, and does.

Outside check (20 Nov 2026): a clean install with only `kit/__init__.py` and `kit/hubcall.py`, run against a local mock server with the network limited to loopback, so no request could reach the Hub. Every preregistered bar was met:

| Case | Result |
| --- | --- |
| 429 three times, no `Retry-After` | waits 5, 10, 20 s, then success (4 requests) |
| `Retry-After: 3`, then `Retry-After: 500` | waits 3 and 300 s (clipped to `MAX_RETRY_AFTER_S`) |
| 503, then a dropped connection, on a read | waits 2 and 4 s, then success |
| 503 three times | 3 requests, then raised |
| 502 on a write | 1 request, raised at once |
| 404 | 1 request |
| 429 for ever | 8 waits summing 515 s, raised at 9 requests (limit 600 s); with `JOB_ID` set, 4 waits and 5 requests |
| Two processes, one shared cool-down | the second process's first request came 5.80 s after the first one's 429 (a 4 s cool-down plus jitter); control with separate state folders: 0.53 s |
| Never-429 server (control) | 0 retries |
| Log | every line names caller, method, outcome and pid; `report --json` counts match |
| Wrapped `HfApi` (huggingface_hub 2.4.0) | `model_info` retried once and returned; `create_repo` on a 502 not repeated |

The public tests repeat these cases (`MockServer` in `tests/test_hubcall.py`), with a 2 s `Retry-After` for the two-process case.

Scope: retry counts, waits and the shared cool-down on one machine. Not checked: the real Hub's limits, several machines sharing one account (each machine has its own cool-down), and calls the library retries by itself.

Claim label: Sourced fact (the outside check's retry counts and waits on a local mock server, 20 Nov 2026).

## Commands and options

### `python -m kit hubcall report`

```
usage: python -m kit hubcall report [-h] [--hours HOURS] [--log LOG] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--hours HOURS` | `24.0` | How far back to read, in hours |
| `--log LOG` | none | The log to read (default: `hubcalls.jsonl` in the kit cache folder) |
| `--json` | off | Print one JSON object instead of the text lines |

`python -m kit.hubcall report` takes the same options.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_HUBCALL_DIR` | unset | The folder that holds the log and the cool-down file (`DIR_ENV`) |
| `XDG_CACHE_HOME` | `~/.cache` | Used when `KIT_HUBCALL_DIR` is unset: the folder is `$XDG_CACHE_HOME/kit` |
| `KIT_HUBCALL_LOG` | `1` | `0` stops the log (`LOG_ENV`) |
| `KIT_HUBCALL_MAX_WAIT` | unset | The total wait in seconds before a call gives up (`WAIT_ENV`) |
| `JOB_ID` | unset | Set inside a Hugging Face Job; the total wait is then `JOB_MAX_WAIT_S` (120 s) |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `HubCallError()` | an exception | | A log that cannot be read |
| `state_dir()` | `Path` | | The kit cache folder (see Environment variables) |
| `log_path()` | `Path` | | `state_dir() / "hubcalls.jsonl"` |
| `cooldown_path()` | `Path` | | `state_dir() / "hub-cooldown.json"` |
| `status_of(exc)` | `int` or `None` | | The HTTP status an exception carries (huggingface_hub, requests, httpx or urllib errors), else None |
| `default_max_wait()` | `float` seconds | | `KIT_HUBCALL_MAX_WAIT` when set, else `JOB_MAX_WAIT_S` inside a Hugging Face Job, else `MAX_WAIT_S` |
| `is_read(method)` | `bool` | | True for an HfApi method that only reads (`READ_PREFIXES`), so repeating it after a dropped answer is safe |
| `is_rate_limited(exc)` | `bool` | | The error is a 429 |
| `is_transient(exc)` | `bool` | | A 5xx, or a connection dropped or timed out before an answer |
| `retry_after(exc)` | `float` or `None` | | Seconds from the error's `Retry-After` header, clipped to `MAX_RETRY_AFTER_S`, or None |
| `read_cooldown(clock=time.time)` | `float` seconds | | Seconds left of this machine's shared cool-down, 0 when none |
| `set_cooldown(seconds, who='', clock=time.time)` | `None` | | Start (or lengthen) the shared cool-down; never shortens one already set |
| `record(who, method, outcome, waited_s=0.0, clock=time.time)` | `None` | | One line in the local log; never raises |
| `call(fn, *args, who='', method=None, sleep=None, clock=None, max_wait_s=None, jitter=None, say=None, retry_net=True, **kw)` | what `fn` returns | the last error once the waits run out, and any other error at once | `fn(*args, **kw)` retried on a 429 and, when `retry_net`, on a 5xx or a dropped connection; `sleep`, `clock` and `jitter` can be replaced in tests; `say` gets one line per wait |
| `Wrapped(api, who)` | an HfApi stand-in | | Public methods run through `call()` (5xx and dropped-connection retries for reads only); attributes that are not methods pass through |
| `wrap(api, who)` | `Wrapped` | | `api` wrapped; an already wrapped api is returned as it is |
| `hf_api(who, **kw)` | `Wrapped` | `ImportError` without huggingface_hub | A new `huggingface_hub.HfApi(**kw)`, wrapped |
| `read_log(path=None, since=None)` | list of dicts | `HubCallError` | The log's lines (newer than `since`, epoch seconds); unparsable lines are skipped |
| `report(rows)` | list of dicts | | Per caller (who and method): calls, 429s, other failures and seconds waited, busiest first |
| `add_arguments(p)` | `None` | | Adds the `report` action to an argparse parser |
| `run(a, say=print)` | exit code | `HubCallError` | Runs parsed arguments |
| `main(argv=None)` | exit code | | The `python -m kit.hubcall` entry point |

## Inputs

- `call()` takes any callable; `wrap()` takes any object, normally a `huggingface_hub.HfApi`.
- `report` reads `hubcalls.jsonl`: one JSON object per line with `t` (epoch seconds), `who`, `method`, `outcome`, `waited_s` and `pid`.

## Outputs

`report` prints a header line and one line per caller: calls, who, method, and when nonzero the rate-limited count, the failed count and the seconds waited. With `--json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `hours` | number | The `--hours` window |
| `calls` | integer | Log lines in the window |
| `cooldown_s` | number | Seconds left of the shared cool-down |
| `callers[].who`, `callers[].method` | string | The caller and the HfApi method |
| `callers[].calls` | integer | Lines for this caller |
| `callers[].rate_limited` | integer | Lines whose outcome was a 429 |
| `callers[].failed` | integer | Other lines that were not ok |
| `callers[].waited_s` | number | Seconds waited, summed |

A log line's `outcome` is `ok`, `429`, `retry STATUS` (or `retry ERRORNAME`), `gave up after OUTCOME`, or `error STATUS`.

| Exit code | Meaning |
| --- | --- |
| `0` | The report was printed |
| `2` | The log could not be read, or the arguments were wrong |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit hubcall: PATH: ERROR` | The log exists but cannot be read | Check the file's permissions, or pass another `--log` |
| Your own Hub error, raised from `call()` | The waits ran out (`gave up after ...` in the log), the error is not one it retries, or a write met a 5xx | Read the log line; slow the caller down or raise `KIT_HUBCALL_MAX_WAIT` |

## How it works

1. Before each attempt, `call()` reads the cool-down file and sleeps out what is left of it, within the total wait.
2. It runs the call. On a 429 it takes `Retry-After` (clipped to `MAX_RETRY_AFTER_S`, 300 s), else the next of `RATE_WAITS_S` (5, 10, 20, 40, 80, 120 s, the last repeated), adds jitter of 0 to 2 s, and writes the cool-down for that long (never shortening a longer one).
3. On a 5xx or a dropped connection (and `retry_net`), it takes the next of `NET_WAITS_S` (2, 4 s); after two such waits, or for any other error, it raises.
4. When the next wait would pass the total (`MAX_WAIT_S`, 600 s, or `JOB_MAX_WAIT_S`, 120 s, with `JOB_ID` set), it logs `gave up after ...` and raises the last error.
5. Every attempt adds one log line; the log is cut to its newer half past `LOG_MAX_BYTES` (8 MiB). The cool-down and the log are written atomically or appended, and a write error is ignored so logging never breaks a call.

## Cost and time

It adds no time to a call that succeeds beyond reading one small file. A retried call waits as above, at most 600 s (120 s in a Job). `report` took 0.17 s wall on a short log (measured 2026-11-20, 4-core cloud container). It rents nothing.

## For agents

- **Command:** `python -m kit hubcall report --json` (in code: `hubcall.wrap(HfApi(), "TOOL")`).
- **Parse:** `callers` sorted busiest first; `rate_limited` and `waited_s` per caller; `cooldown_s` above 0 means the machine is still cooling down.
- **Rerun:** `report` is read-only and safe to rerun. `call()` appends to the log.
- **Success:** exit 0 from `report`; in code, `call()` returns the call's result.
- **Not a pass:** a run with no 429s in the log does not show the limit is far away; a wrapped listing's own library retries are not logged.
- **Go-ahead:** Nothing.
- **Never:** never repeat a write by hand after a 5xx without checking whether it was applied; never poll the Hub in a tight loop because hubcall will retry.

## Tests

`python -m unittest tests.test_hubcall` covers error detection for every error shape, the 429 and 5xx schedules, giving up, the shared cool-down (in one process with a fake clock, and across two real processes against a local HTTP server, with a separate-folder control), the Job limit, the log switch, the wrapper (listings read inside the retry, writes not repeated after a 502) and the report. It does not call the real Hub.

## History

- 2026-11-20: released to public Scrolls, on top of `357d2bd`, after an outside check against a local mock server.

## Related

- [drivers](drivers.md): restart-safe background drivers, often the callers that make many Hub calls.
- [freeze](freeze.md): the other tools released with it after the same outside checks.
- [compute](../compute.md): where paid jobs run.
