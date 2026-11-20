"""Hugging Face Hub calls that back off on the rate limit, with one shared cool-down per machine and a log of who
made them (python -m kit hubcall).

The Hub answers HTTP 429 when an account makes too many API calls. A script that fails at once on a 429, or retries
on its own fixed timer, loses work or makes the limit worse when many processes on one machine retry into it together.
This module gives every Hub call one rule:

  wrap(api, who)       an HfApi stand-in whose every method goes through call()
  call(fn, *a, who=)   run one Hub call; on a 429 wait (Retry-After, else 5, 10, 20, 40, 80, 120 s), and on a 5xx
                       or a dropped connection wait 2, 4 s (reads only), then call again, up to MAX_WAIT_S (600) in
                       all, or JOB_MAX_WAIT_S (120) inside a Hugging Face Job
  python -m kit hubcall report [--hours H] [--log PATH] [--json]
                       calls and 429s per caller in the local log, busiest first

One machine's processes back off together: a 429 writes a cool-down time to the cool-down file (in the kit cache
folder), and every call() on that machine waits it out before calling, so twenty processes do not each retry into the
same limit. Each call adds one line (time, caller, method, outcome, seconds waited, pid) to the log, which `report`
reads, so the next time the limit is hit the busiest caller is named from data. KIT_HUBCALL_DIR moves both files;
KIT_HUBCALL_LOG=0 stops the log; KIT_HUBCALL_MAX_WAIT sets the total wait. A 429 means the call was refused, so every
call is retried on it; a 5xx or a dropped connection may come after a write was applied, so only reads
(READ_PREFIXES) retry on those. Standard library only; huggingface_hub is imported only by hf_api(), which builds an
HfApi.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import types
from collections import Counter, defaultdict
from pathlib import Path

RATE_WAITS_S = (5, 10, 20, 40, 80, 120)      # waits after successive 429s with no Retry-After
NET_WAITS_S = (2, 4)                         # waits after a 5xx or a dropped connection
MAX_WAIT_S = 600                             # no call waits longer than this in all; then the last error is raised
JOB_MAX_WAIT_S = 120                         # inside a Hugging Face Job (JOB_ID set), so a wait cannot eat its export room
MAX_RETRY_AFTER_S = 300                      # a Retry-After past this is clipped to it
LOG_MAX_BYTES = 8 << 20                      # the log is cut to its newer half past this size
DIR_ENV, LOG_ENV, WAIT_ENV = "KIT_HUBCALL_DIR", "KIT_HUBCALL_LOG", "KIT_HUBCALL_MAX_WAIT"
READ_PREFIXES = ("list_", "get_", "file_exists", "repo_exists", "revision_exists", "repo_info", "model_info",
                 "dataset_info", "space_info", "bucket_info", "paths_info", "hf_hub_download", "snapshot_download",
                 "download", "whoami", "auth_check", "fetch_", "inspect_", "read_")


class HubCallError(Exception):
    """A log that cannot be read."""


def state_dir():
    d = os.environ.get(DIR_ENV)
    if d:
        return Path(d)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "kit"


def log_path():
    return state_dir() / "hubcalls.jsonl"


def cooldown_path():
    return state_dir() / "hub-cooldown.json"


def status_of(exc):
    """The HTTP status an exception carries (huggingface_hub, requests, httpx or urllib errors), else None."""
    for obj in (getattr(exc, "response", None), exc):
        for name in ("status_code", "code", "status"):
            v = getattr(obj, name, None)
            if isinstance(v, int) and 100 <= v <= 599:
                return v
    text = str(exc)
    if "429" in text and ("Too Many Requests" in text or "rate limit" in text.lower() or "429 Client Error" in text):
        return 429
    return None


def default_max_wait():
    """KIT_HUBCALL_MAX_WAIT seconds when set, else JOB_MAX_WAIT_S inside a Hugging Face Job, else MAX_WAIT_S."""
    try:
        return max(0.0, float(os.environ[WAIT_ENV]))
    except (KeyError, ValueError):
        return JOB_MAX_WAIT_S if os.environ.get("JOB_ID") else MAX_WAIT_S


def is_read(method):
    """True for an HfApi method that only reads, so repeating it after a dropped answer is safe."""
    return str(method).startswith(READ_PREFIXES)


def is_rate_limited(exc):
    return status_of(exc) == 429


def is_transient(exc):
    """A 5xx, or a connection dropped or timed out before an answer."""
    s = status_of(exc)
    if s is not None:
        return 500 <= s <= 599
    name = type(exc).__name__
    return isinstance(exc, (ConnectionError, TimeoutError)) or name in (
        "ConnectionError", "ReadTimeout", "ConnectTimeout", "Timeout", "RemoteDisconnected", "ReadError",
        "ConnectError", "RemoteProtocolError")


def retry_after(exc):
    """Seconds from the error's Retry-After header, clipped to MAX_RETRY_AFTER_S, or None."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or getattr(exc, "headers", None)
    if not headers:
        return None
    try:
        v = headers.get("Retry-After") or headers.get("retry-after")
    except AttributeError:
        return None
    try:
        return max(0.0, min(float(v), MAX_RETRY_AFTER_S))
    except (TypeError, ValueError):
        return None


def read_cooldown(clock=time.time):
    """Seconds left of this machine's shared cool-down, 0 when none."""
    try:
        until = float(json.loads(cooldown_path().read_text()).get("until", 0))
    except (OSError, ValueError, AttributeError, TypeError):
        return 0.0
    return max(0.0, until - clock())


def set_cooldown(seconds, who="", clock=time.time):
    """Start (or lengthen) the shared cool-down; never shortens one already set."""
    p = cooldown_path()
    until = clock() + seconds
    if read_cooldown(clock) >= seconds:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"until": until, "who": who, "set": clock()}))
        os.replace(tmp, p)
    except OSError:
        pass


def record(who, method, outcome, waited_s=0.0, clock=time.time):
    """One line in the local log; never raises."""
    if os.environ.get(LOG_ENV, "1") == "0":
        return
    p = log_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > LOG_MAX_BYTES:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            p.write_text("\n".join(lines[len(lines) // 2:]) + "\n")
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(clock(), 3), "who": who, "method": method, "outcome": outcome,
                                "waited_s": round(waited_s, 1), "pid": os.getpid()}) + "\n")
    except OSError:
        pass


def call(fn, *args, who="", method=None, sleep=None, clock=None, max_wait_s=None, jitter=None, say=None,
         retry_net=True, **kw):
    """fn(*args, **kw), retried on a 429 (Retry-After, else RATE_WAITS_S, waited by every process on this machine)
    and, when retry_net, on a 5xx or a dropped connection (NET_WAITS_S), while the total wait stays within max_wait_s
    (default_max_wait()). Other errors, and the last one when the waits run out, are raised unchanged."""
    sleep, clock, jitter = sleep or time.sleep, clock or time.time, jitter or random.random
    max_wait_s = default_max_wait() if max_wait_s is None else max_wait_s
    method = method or getattr(fn, "__name__", "call")
    waited, rate_n, net_n = 0.0, 0, 0
    while True:
        cool = read_cooldown(clock)
        if cool > 0:
            pause = min(cool, max(0.0, max_wait_s - waited))
            if pause > 0:
                sleep(pause)
                waited += pause
        try:
            out = fn(*args, **kw)
        except Exception as exc:                          # noqa: BLE001 (sorted below; others re-raised)
            if is_rate_limited(exc):
                base = retry_after(exc)
                pause = base if base is not None else RATE_WAITS_S[min(rate_n, len(RATE_WAITS_S) - 1)]
                pause += jitter() * 2
                rate_n += 1
                outcome = "429"
            elif retry_net and is_transient(exc) and net_n < len(NET_WAITS_S):
                pause = NET_WAITS_S[net_n]
                net_n += 1
                outcome = f"retry {status_of(exc) or type(exc).__name__}"
            else:
                record(who, method, f"error {status_of(exc) or type(exc).__name__}", waited, clock)
                raise
            if waited + pause > max_wait_s:
                record(who, method, f"gave up after {outcome}", waited, clock)
                raise
            if outcome == "429":
                set_cooldown(pause, who, clock)
            if say:
                say(f"kit hubcall: {who or 'hub'} {method}: {outcome}; waiting {pause:.0f} s")
            record(who, method, outcome, waited, clock)
            sleep(pause)
            waited += pause
            continue
        record(who, method, "ok", waited, clock)
        return out


class Wrapped:
    """An HfApi whose public methods run through call() (5xx and dropped-connection retries for reads only);
    attributes that are not methods pass through."""

    def __init__(self, api, who):
        self._api, self._who = api, who

    def __getattr__(self, name):
        attr = getattr(self._api, name)
        if name.startswith("_") or not callable(attr):
            return attr

        def whole(*a, **kw):             # a lazy listing is read inside the retry, so a 429 mid-way is retried
            out = attr(*a, **kw)
            return list(out) if isinstance(out, types.GeneratorType) else out

        def method(*a, **kw):
            return call(whole, *a, who=self._who, method=name, retry_net=is_read(name), **kw)
        method.__name__ = name
        return method


def wrap(api, who):
    """api wrapped so every call backs off on the rate limit and is logged under WHO (a module name)."""
    return api if isinstance(api, Wrapped) else Wrapped(api, who)


def hf_api(who, **kw):
    """A new huggingface_hub.HfApi(**kw), wrapped."""
    from huggingface_hub import HfApi
    return wrap(HfApi(**kw), who)


def read_log(path=None, since=None):
    p = Path(path) if path else log_path()
    out = []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return out
    except OSError as exc:
        raise HubCallError(f"{p}: {exc}") from exc
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and (since is None or r.get("t", 0) >= since):
            out.append(r)
    return out


def report(rows):
    """Per caller (who and method): calls, 429s, other failures and seconds waited, busiest first."""
    agg = defaultdict(Counter)
    for r in rows:
        k = (r.get("who") or "?", r.get("method") or "?")
        agg[k]["calls"] += 1
        o = str(r.get("outcome", ""))
        if o == "429" or o.endswith("429"):
            agg[k]["429"] += 1
        elif o != "ok":
            agg[k]["failed"] += 1
        agg[k]["waited_s"] += float(r.get("waited_s") or 0)
    out = [{"who": w, "method": m, "calls": c["calls"], "rate_limited": c["429"], "failed": c["failed"],
            "waited_s": round(c["waited_s"], 1)} for (w, m), c in agg.items()]
    return sorted(out, key=lambda x: (-x["calls"], x["who"], x["method"]))


def add_arguments(p):
    sub = p.add_subparsers(dest="hubcall_cmd", required=True)
    r = sub.add_parser("report", help="Hub calls and 429s per caller in this machine's log, busiest first")
    r.add_argument("--hours", type=float, default=24.0, help="how far back to read (default 24)")
    r.add_argument("--log", help="the log to read (default: the kit cache folder's hubcalls.jsonl)")
    r.add_argument("--json", action="store_true")


def run(a, say=print):
    rows = read_log(a.log, time.time() - a.hours * 3600)
    rep = report(rows)
    cool = read_cooldown()
    if a.json:
        say(json.dumps({"hours": a.hours, "calls": len(rows), "cooldown_s": round(cool, 1), "callers": rep},
                       indent=1))
        return 0
    say(f"{len(rows)} Hub call(s) in the last {a.hours:g} h on this machine"
        + (f"; cooling down for {cool:.0f} s after a 429" if cool else ""))
    for x in rep:
        say(f"  {x['calls']:6d}  {x['who']} {x['method']}"
            + (f"  {x['rate_limited']} rate-limited" if x["rate_limited"] else "")
            + (f"  {x['failed']} failed" if x["failed"] else "")
            + (f"  {x['waited_s']:.0f} s waited" if x["waited_s"] else ""))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit hubcall", description=__doc__.splitlines()[0])
    add_arguments(p)
    a = p.parse_args(argv)
    try:
        return run(a)
    except HubCallError as exc:
        print(f"kit hubcall: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
