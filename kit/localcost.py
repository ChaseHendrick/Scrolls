"""Wall time and electricity cost of local runs, written into the experiment ledger.

``python -m kit run local SLUG -- CMD ...`` runs CMD, times it, and appends one cost entry
to ``experiments/SLUG/run.json``. Energy is an estimate: laptops do not report wall power
without root (macOS ``powermetrics`` needs sudo), so it is average watts for a device class
(or ``--watts``) times wall hours. The rate is the local electricity rate, set outside git:

1. ``--rate`` on the command line, else
2. env var ``SCROLLS_ELECTRICITY_USD_PER_KWH``, else
3. ``electricity_usd_per_kwh`` in the local config file: ``$SCROLLS_LOCAL_CONFIG``, else
   ``~/.config/scrolls/local.json``, else ``scrolls.local.json`` in the working directory
   (gitignored).

Only the rate number and the USD are stored. Standard library only.
"""

import json
import os
import platform
import resource
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import ledger

# Average whole-machine draw while busy, in watts. Rough, documented, overridable.
DEVICE_WATTS = {
    "apple-silicon-cpu": 30.0,   # M1 Pro class laptop, all performance cores busy
    "apple-silicon-gpu": 40.0,   # same laptop with MPS busy
    "apple-silicon-idle": 8.0,
    "x86-cpu": 65.0,
    "cuda-gpu": 350.0,
}
ENV_RATE = "SCROLLS_ELECTRICITY_USD_PER_KWH"
ENV_CONFIG = "SCROLLS_LOCAL_CONFIG"


class CostError(Exception):
    pass


def config_paths():
    paths = []
    if os.environ.get(ENV_CONFIG):
        paths.append(Path(os.environ[ENV_CONFIG]))
    paths.append(Path.home() / ".config" / "scrolls" / "local.json")
    paths.append(Path("scrolls.local.json"))
    return paths


def load_config():
    for path in config_paths():
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise CostError(f"bad JSON in {path}: {exc}") from exc
    return {}


def resolve_rate(rate=None, config=None):
    if rate is not None:
        value = rate
    elif os.environ.get(ENV_RATE):
        value = os.environ[ENV_RATE]
    else:
        value = (load_config() if config is None else config).get("electricity_usd_per_kwh")
    if value is None:
        raise CostError(f"no electricity rate: set {ENV_RATE} or electricity_usd_per_kwh in "
                        "~/.config/scrolls/local.json (local electricity rate, set in your local config)")
    value = float(value)
    if value < 0:
        raise CostError("rate cannot be negative")
    return value


def default_device():
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "apple-silicon-cpu"
    return "x86-cpu"


def resolve_watts(device=None, watts=None, config=None):
    if watts is not None:
        return float(watts), device or "override"
    device = device or (config or {}).get("device") or default_device()
    table = dict(DEVICE_WATTS)
    table.update((config or {}).get("device_watts", {}))
    if device not in table:
        raise CostError(f"unknown device {device!r}; use one of {', '.join(sorted(table))} or --watts")
    return float(table[device]), device


def estimate(wall_s, watts, rate):
    kwh = watts * wall_s / 3600 / 1000
    return round(kwh, 6), round(kwh * rate, 6)


def entry(started, ended, wall_s, cpu_s, device, watts, rate, note=None, command=None, exit_code=None):
    kwh, usd = estimate(wall_s, watts, rate)
    out = {"kind": "local", "started_utc": started, "ended_utc": ended,
           "wall_s": round(wall_s, 3), "cpu_s": None if cpu_s is None else round(cpu_s, 3),
           "device": device, "watts": watts, "kwh": kwh,
           "rate_usd_per_kwh": rate, "usd_exact": usd}
    if command is not None:
        out["command"] = command
    if exit_code is not None:
        out["exit_code"] = exit_code
    if note:
        out["note"] = note
    return out


def append(slug, item, root=ledger.DEFAULT_ROOT):
    record = ledger.load(slug, root)
    what = item.get("note") or "local run"
    cost = {"at": ledger._now(), "usd": round(item["usd_exact"], 2), "what": what, "local": item}
    record["costs"].append(cost)
    ledger.save(record, root)
    return record


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(slug, command, root=ledger.DEFAULT_ROOT, device=None, watts=None, rate=None):
    """Run command, record its cost, return (exit_code, entry). Fails before running if unconfigured."""
    if not command:
        raise CostError("no command given after --")
    config = load_config()
    rate = resolve_rate(rate, config)
    watts, device = resolve_watts(device, watts, config)
    ledger.load(slug, root)  # the experiment must exist before the run starts
    started, t0 = _utc(), time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        code = subprocess.call(command)
    except KeyboardInterrupt:
        code = 130
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall = time.monotonic() - t0
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    item = entry(started, _utc(), wall, cpu, device, watts, rate,
                 note=f"local run, exit {code}", command=" ".join(command), exit_code=code)
    append(slug, item, root)
    return code, item


def backfill(slug, items, root=ledger.DEFAULT_ROOT, rate=None):
    """items: dicts with what, wall_s, device (or watts), optional started_utc. Marked estimated."""
    config = load_config()
    rate = resolve_rate(rate, config)
    total_s = total_usd = 0.0
    for it in items:
        watts, device = resolve_watts(it.get("device"), it.get("watts"), config)
        e = entry(it.get("started_utc"), None, float(it["wall_s"]), None, device, watts, rate,
                  note=f"{it['what']} (estimated from logs)")
        e["estimated_from_logs"] = True
        append(slug, e, root)
        total_s += e["wall_s"]
        total_usd += e["usd_exact"]
    return round(total_s / 3600, 4), round(total_usd, 6)
