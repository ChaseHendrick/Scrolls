"""Time local commands and append estimated electricity cost to the local ledger.

Rates come from --rate, SCROLLS_ELECTRICITY_USD_PER_KWH, or local JSON configuration.
Device watts are illustrative assumptions, not wall-power measurements. No global cache
or privileged power measurement is used. Standard library only.
"""

import json
import math
import os
import platform
import shlex
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import resource
except ImportError:  # Keep other kit commands usable on non-POSIX platforms.
    resource = None
try:
    import fcntl
except ImportError:
    fcntl = None

from . import ledger

# Illustrative whole-machine watts while busy; users can override these assumptions.
DEVICE_WATTS = {
    "apple-silicon-cpu": 30.0,
    "apple-silicon-gpu": 40.0,
    "apple-silicon-idle": 8.0,
    "x86-cpu": 65.0,
    "cuda-gpu": 350.0,
}
ENV_RATE = "SCROLLS_ELECTRICITY_USD_PER_KWH"
ENV_CONFIG = "SCROLLS_LOCAL_CONFIG"


class CostError(Exception):
    pass


def _nonnegative(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CostError(f"{name} must be a finite nonnegative number") from exc
    if isinstance(value, bool) or not math.isfinite(number) or number < 0:
        raise CostError(f"{name} must be a finite nonnegative number")
    return number


def config_paths():
    explicit = os.environ.get(ENV_CONFIG)
    if explicit:
        return [Path(explicit)]
    return [Path.home() / ".config" / "scrolls" / "local.json", Path("scrolls.local.json")]


def load_config():
    for path in config_paths():
        if path.is_file():
            try:
                config = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise CostError(f"cannot read local configuration {path}: {exc}") from exc
            if not isinstance(config, dict):
                raise CostError(f"local configuration {path} must be a JSON object")
            return config
    if os.environ.get(ENV_CONFIG):
        raise CostError(f"local configuration does not exist: {os.environ[ENV_CONFIG]}")
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
                        "~/.config/scrolls/local.json")
    return _nonnegative(value, "electricity rate")


def default_device():
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "apple-silicon-cpu"
    return "x86-cpu"


def resolve_watts(device=None, watts=None, config=None):
    configured_device = (config or {}).get("device")
    for value in (device, configured_device):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise CostError("device must be a nonempty string")
    if watts is not None:
        return _nonnegative(watts, "watts"), device or "override"
    device = device or configured_device or default_device()
    table = dict(DEVICE_WATTS)
    overrides = (config or {}).get("device_watts", {})
    if not isinstance(overrides, dict):
        raise CostError("device_watts must be a JSON object")
    table.update(overrides)
    if not isinstance(device, str) or device not in table:
        raise CostError(f"unknown device {device!r}; use a supported device or --watts")
    return _nonnegative(table[device], "watts"), device


def estimate(wall_s, watts, rate):
    wall_s = _nonnegative(wall_s, "wall seconds")
    watts = _nonnegative(watts, "watts")
    rate = _nonnegative(rate, "electricity rate")
    kwh = _nonnegative(watts * wall_s / 3600 / 1000, "estimated energy")
    usd = _nonnegative(kwh * rate, "estimated cost")
    return round(kwh, 6), round(usd, 6)


def entry(started, ended, wall_s, cpu_s, device, watts, rate, note=None, command=None, exit_code=None):
    kwh, usd = estimate(wall_s, watts, rate)
    wall_s = _nonnegative(wall_s, "wall seconds")
    cpu_s = None if cpu_s is None else _nonnegative(cpu_s, "CPU seconds")
    out = {"kind": "local", "started_utc": started, "ended_utc": ended,
           "wall_s": round(wall_s, 3), "cpu_s": None if cpu_s is None else round(cpu_s, 3),
           "device": device, "watts": _nonnegative(watts, "watts"), "kwh": kwh,
           "rate_usd_per_kwh": _nonnegative(rate, "electricity rate"), "usd_exact": usd}
    if command is not None:
        out["command"] = command
    if exit_code is not None:
        out["exit_code"] = exit_code
    if note:
        out["note"] = note
    return out


@contextmanager
def _cost_lock(path):
    # Serialize local-cost writers on the supported Mac/Linux platforms. Other ledger
    # writers do not use this lock. Non-POSIX platforms require serial ledger writes.
    with path.with_suffix(".local-cost.lock").open("a") as lock:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _append_items(slug, items, root):
    path = ledger.path_for(slug, root)
    ledger.load(slug, root)  # Require an existing experiment; never create one here.
    with _cost_lock(path):
        record = ledger.load(slug, root)
        for item in items:
            record["costs"].append({"at": ledger._now(), "usd": item["usd_exact"],
                                    "what": item.get("note") or "local run", "local": item})
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".local-cost-", delete=False) as fh:
                temporary = Path(fh.name)
                json.dump(record, fh, indent=2, allow_nan=False)
                fh.write("\n")
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return record


def append(slug, item, root=ledger.DEFAULT_ROOT):
    return _append_items(slug, [item], root)


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(slug, command, root=ledger.DEFAULT_ROOT, device=None, watts=None, rate=None):
    """Run a child, record its cost, and return its shell-compatible exit code and entry."""
    if not command:
        raise CostError("no command given after --")
    if not isinstance(command, (list, tuple)) or not all(isinstance(x, (str, os.PathLike)) for x in command):
        raise CostError("command must be an argument list")
    command = [os.fspath(x) for x in command]
    config = load_config()
    rate = resolve_rate(rate, config)
    watts, device = resolve_watts(device, watts, config)
    ledger.load(slug, root)
    started, t0 = _utc(), time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN) if resource is not None else None
    launch_error = None
    try:
        raw_code = subprocess.call(command)
    except KeyboardInterrupt:
        raw_code = 130
    except OSError as exc:
        raw_code = 127 if isinstance(exc, FileNotFoundError) else 126
        launch_error = str(exc)
    after = resource.getrusage(resource.RUSAGE_CHILDREN) if resource is not None else None
    wall = time.monotonic() - t0
    cpu = None if before is None else ((after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime))
    code = 128 - raw_code if raw_code < 0 else raw_code
    item = entry(started, _utc(), wall, cpu, device, watts, rate,
                 note=f"local run, exit {code}", command=shlex.join(command), exit_code=code)
    item["command_argv"] = command
    if raw_code < 0:
        item["signal"] = -raw_code
        item["raw_returncode"] = raw_code
    if launch_error is not None:
        item["launch_error"] = launch_error
    append(slug, item, root)
    return code, item


def backfill(slug, items, root=ledger.DEFAULT_ROOT, rate=None):
    """Validate the whole batch before committing any estimated-from-logs entries."""
    if not isinstance(items, list):
        raise CostError("backfill must be a JSON list")
    config = load_config()
    rate = resolve_rate(rate, config)
    ledger.load(slug, root)
    prepared = []
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("what"), str) or not it["what"].strip() or "wall_s" not in it:
            raise CostError("each backfill item needs nonempty what and wall_s")
        watts, device = resolve_watts(it.get("device"), it.get("watts"), config)
        e = entry(it.get("started_utc"), None, it["wall_s"], None, device, watts, rate,
                  note=f"{it['what']} (estimated from logs)")
        e["estimated_from_logs"] = True
        prepared.append(e)
    total_s = _nonnegative(sum(e["wall_s"] for e in prepared), "total wall seconds")
    total_usd = _nonnegative(sum(e["usd_exact"] for e in prepared), "total cost")
    if prepared:
        _append_items(slug, prepared, root)
    return round(total_s / 3600, 4), round(total_usd, 6)
