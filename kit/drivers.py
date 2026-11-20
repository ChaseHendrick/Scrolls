"""Background drivers that cannot die unnoticed: start, status, revive, stop, log, whereami.

  python3 -m kit drivers start ID [--restartable] [--max-attempts 3] [--cwd DIR] [--note TEXT] -- COMMAND...
  python3 -m kit drivers status [ID...] [--json] [--hook]
  python3 -m kit drivers revive [ID...] [--dry-run]
  python3 -m kit drivers stop ID [--grace 10]
  python3 -m kit drivers log ID [-n 40] [--attempt N]
  python3 -m kit drivers whereami [--json]
  every action takes --dir DIR (default $KIT_DRIVERS_DIR, else work/drivers in this checkout)

Why: a long job started with `nohup ... &` leaves no record of what ran, where or how it ended, so when a cloud
container restarts or a laptop reboots, a killed job looks the same as a finished one until someone runs pgrep. Two
helpers that write to one fixed path such as /tmp/job can also collide when they land on one machine.

`start` runs COMMAND under a small supervisor (`python3 -m kit.drivers _supervise`, its own session and process
group, stdin closed, output to the attempt's log) and records, under STATE/ID/:

  driver.json        the command, its working folder, its mode (restartable or single), max attempts, who and when
  attempt-NN.json    one per start: host, boot id, the supervisor's and the command's pid and process start time,
                     then the exit code and finish time, written by the supervisor when the command ends
  attempt-NN.log     the command's output (stdout and stderr)
  run/               the driver's own work folder, the same for every attempt so a restartable driver can resume
                     from its own files; never shared with another driver

The command runs with KIT_RUN_DIR (STATE/ID/run), TMPDIR (STATE/ID/run/tmp), KIT_DRIVER_ID, KIT_DRIVER_ATTEMPT and
KIT_DRIVER_STATE set. A driver script should write under $KIT_RUN_DIR, never under a fixed path such as /tmp/job,
so two drivers on one host cannot collide.

`status` reads every driver: running (the supervisor or the command is alive, checked by pid and process start time
so a reused pid does not count), finished (with the exit code), stopped (by `kit drivers stop`), starting (in its
first 30 s) or lost: no exit record and the process is gone, or the machine's boot id changed since the start (a
container restart or a reboot). It exits 3 when any driver is lost. With --hook it prints only the lost ones, in two
or three lines, and always exits 0, so a session-start hook can run it and every new session sees a lost driver at
once.

`revive` restarts lost drivers that were started --restartable, as the next attempt (same command, same run/
folder, a new log), up to --max-attempts starts in all; it notes on the lost attempt how it ended. A driver started
without --restartable (mode single) is never revived: it is a launch or a frozen run, which must not run twice by
accident; start it again under a new id once you have looked at its log. `start --restartable` refuses a command
that names a freeze (--frozen ID, --freeze ID, --prereg PATH, -e KIT_FREEZE=ID or a leading KIT_FREEZE=ID; see
frozen()), and also when KIT_FREEZE is set: a frozen run is never restarted (kit/freeze.py).

The state folder must be on the machine that runs the drivers (the default, work/drivers, is ignored by git). A new
cloud session gets a fresh container and an empty state folder. Standard library only; tested in
tests/test_drivers.py. Tool page: docs/tools/drivers.md.
"""
import argparse
import calendar
import json
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_ENV = "KIT_DRIVERS_DIR"
DEFAULT_STATE = ROOT / "work" / "drivers"
SPEC = "driver.json"
VERSION = 1
MODES = ("restartable", "single")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
FREEZE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FREEZE_FLAGS = ("--frozen", "--freeze", "--prereg")
STARTING_GRACE_S = 30
EXIT_OK, EXIT_PROBLEM, EXIT_ARGS, EXIT_LOST = 0, 1, 2, 3
RUNNING, FINISHED, STOPPED, STARTING, LOST = "running", "finished", "stopped", "starting", "lost"
STOPPED_NOTE = "stopped by kit drivers stop"


class DriverError(RuntimeError):
    """The action may not go ahead; the message says why."""


def _write_json(path, doc):
    """Write doc as JSON to path atomically (a temporary file in the same folder, then os.replace)."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")   # pids repeat across containers
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _epoch(stamp):
    try:
        return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def state_dir(where=None):
    return Path(where or os.environ.get(STATE_ENV) or DEFAULT_STATE).expanduser()


def check_id(driver_id):
    if not isinstance(driver_id, str) or not ID_RE.match(driver_id):
        raise DriverError(f"{driver_id!r} is not a driver id (letters, digits, '.', '_' and '-', first a letter or "
                          "digit)")
    return driver_id


# ---------------------------------------------------------------- this machine

def boot_id():
    """An id that changes at every boot of this machine or container, or None when it cannot be read."""
    try:
        return "linux-" + Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        pass
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r"sec\s*=\s*(\d+)", out)
            if m:
                return "darwin-" + m.group(1)
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def _proc(pid):
    """(start time, state letter) of a live process, (None, None) when it is alive but unreadable, or None when gone.
    The start time tells a reused pid from the process that was recorded."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass                                   # alive, owned by someone else
    except OSError:
        return None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        rest = stat[stat.rindex(")") + 2:].split()
        return rest[19], rest[0]               # field 22 (starttime) and field 3 (state)
    except FileNotFoundError:
        if Path("/proc/self/stat").exists():
            return None                        # Linux, and the process went away between the two reads
    except (OSError, ValueError, IndexError):
        pass
    try:
        out = subprocess.run(["ps", "-o", "lstart=,stat=", "-p", str(pid)], capture_output=True, text=True,
                             timeout=5).stdout.strip()
        if not out:
            return None
        return out[:-len(out.split()[-1])].strip() or None, out.split()[-1][:1]
    except (OSError, subprocess.SubprocessError):
        return None, None


def proc_start(pid):
    p = _proc(pid)
    return p[0] if p else None


def alive(entry):
    """True when a recorded {pid, start} process still runs and is the same process (not a zombie, not a reused
    pid)."""
    if not entry:
        return False
    p = _proc(entry.get("pid"))
    if p is None or p[1] == "Z":
        return False
    return not (entry.get("start") and p[0] and p[0] != entry["start"])


def whereami():
    return {"host": socket.gethostname(), "boot_id": boot_id(), "platform": platform.platform(),
            "python": sys.executable, "pid": os.getpid()}


# ---------------------------------------------------------------- records

def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _attempt_path(d, n):
    return Path(d) / f"attempt-{n:02d}.json"


def attempts(d):
    """Every attempt record of driver folder d, oldest first."""
    rows = []
    for p in sorted(Path(d).glob("attempt-[0-9][0-9].json")):
        rec = _read(p)
        rows.append(rec if isinstance(rec, dict) else {"attempt": int(p.stem[-2:]), "unreadable": True})
    return rows


def _new_attempt(d, n, who):
    """Claim attempt n of driver folder d (refuses when another start claimed it) and write its first record."""
    p = _attempt_path(d, n)
    try:
        os.close(os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
    except FileExistsError:
        raise DriverError(f"{p} exists: another start or revive claimed attempt {n} at the same time")
    me = whereami()
    rec = {"attempt": n, "requested": _now(), "host": me["host"], "boot_id": me["boot_id"], "who": who}
    _write_json(p, rec)
    return rec


def judge(spec, rows, here=None, now=None):
    """(state, reason) of a driver from its spec and attempt records, as seen from this machine."""
    here = here or whereami()
    if not rows:
        return LOST, "no attempt was recorded (the start stopped half way)"
    rec = rows[-1]
    if rec.get("unreadable"):
        return LOST, f"attempt {rec.get('attempt')} record cannot be read"
    if "exit" in rec:
        if rec.get("ended") == STOPPED_NOTE:
            return STOPPED, f"stopped at {rec.get('finished', '?')} (exit {rec['exit']})"
        return FINISHED, f"exit {rec['exit']} at {rec.get('finished', '?')}"
    if rec.get("boot_id") and here.get("boot_id") and rec["boot_id"] != here["boot_id"]:
        return LOST, (f"the machine restarted since attempt {rec.get('attempt')} started (boot id changed; started "
                      f"on {rec.get('host')})")
    if not (rec.get("boot_id") and here.get("boot_id")) and rec.get("host") != here.get("host"):
        return LOST, f"attempt {rec.get('attempt')} started on {rec.get('host')}, this is {here.get('host')}"
    if alive(rec.get("supervisor")) or alive(rec.get("child")):
        pid = (rec.get("child") or rec.get("supervisor") or {}).get("pid")
        return RUNNING, f"pid {pid} since {rec.get('started', rec.get('requested'))}"
    t0 = _epoch(rec.get("requested"))
    if not rec.get("supervisor") and t0 is not None and (now or time.time()) - t0 < STARTING_GRACE_S:
        return STARTING, f"requested {rec.get('requested')}"
    return LOST, f"attempt {rec.get('attempt')} process is gone with no exit record"


def drivers(where=None, ids=None, now=None):
    """One row per driver: id, mode, attempts, max_attempts, state, reason, command, note."""
    root = state_dir(where)
    here = whereami()
    out = []
    names = ids or (sorted(p.name for p in root.iterdir() if (p / SPEC).is_file()) if root.is_dir() else [])
    for name in names:
        d = root / name
        spec = _read(d / SPEC)
        if not isinstance(spec, dict):
            out.append({"id": name, "state": "unknown", "reason": f"no readable {SPEC} in {d}"})
            continue
        rows = attempts(d)
        state, reason = judge(spec, rows, here, now)
        last = rows[-1] if rows else {}
        out.append({"id": name, "mode": spec.get("mode"), "attempts": len(rows),
                    "max_attempts": spec.get("max_attempts"), "state": state, "reason": reason,
                    "exit": last.get("exit"), "command": spec.get("command"), "note": spec.get("note"),
                    "log": str(d / f"attempt-{len(rows):02d}.log") if rows else None})
    return out


def revivable(row):
    """None when a lost driver may be revived, else why not."""
    if row.get("state") != LOST:
        return f"it is {row.get('state')}, not lost"
    if row.get("mode") != "restartable":
        return ("it was started without --restartable (a launch or a frozen run): never restarted; look at its log, "
                "then start it again under a new id (a rerun of a frozen run needs a new freeze)")
    if row.get("attempts", 0) >= (row.get("max_attempts") or 0):
        return f"it has used all {row.get('max_attempts')} attempts; look at its log before starting it under a new id"
    return None


# ---------------------------------------------------------------- start, supervise, revive, stop

def _spawn(d, n):
    """Start the supervisor of attempt n of driver folder d, detached; returns the Popen."""
    log = open(Path(d) / f"attempt-{n:02d}.log", "ab")
    try:
        return subprocess.Popen([sys.executable, "-m", "kit.drivers", "_supervise", str(d), str(n)], cwd=str(ROOT),
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True, close_fds=True)
    finally:
        log.close()


def frozen(cmd, env=None):
    """The freeze or preregistration a command names, or None: the value after --frozen, --freeze or --prereg (as
    `--flag VALUE` or `--flag=VALUE`; for --frozen and --freeze only a value that looks like a freeze id, not a file
    path), `-e KIT_FREEZE=ID` or `--env KIT_FREEZE=ID`, a leading `KIT_FREEZE=ID` before the program, or
    KIT_FREEZE set in env (default os.environ)."""
    cmd = [str(c) for c in cmd]
    for i, tok in enumerate(cmd):
        name, eq, val = tok.partition("=")
        if name in FREEZE_FLAGS and (eq or i + 1 < len(cmd)):
            v = val if eq else cmd[i + 1]
            if name == "--prereg" and v:
                return v
            if FREEZE_ID.match(v) and not v.endswith((".md", ".json", ".py")):
                return v
        pair = None
        if tok in ("-e", "--env") and i + 1 < len(cmd):
            pair = cmd[i + 1]
        elif tok.startswith("KIT_FREEZE=") and all("=" in t for t in cmd[:i]):
            pair = tok
        if pair and pair.startswith("KIT_FREEZE="):
            v = pair.partition("=")[2]
            if FREEZE_ID.match(v):
                return v
    return (os.environ if env is None else env).get("KIT_FREEZE") or None


def start(driver_id, cmd, mode="single", max_attempts=3, cwd=None, where=None, who=None, note=None):
    """Record and start driver driver_id; returns (driver folder, Popen of its supervisor). mode is restartable
    (revive may start it again once lost) or single (never revived; max_attempts is then 1)."""
    check_id(driver_id)
    if not cmd:
        raise DriverError("give the command after --")
    if mode not in MODES:
        raise DriverError(f"mode must be one of {MODES}")
    if not isinstance(max_attempts, int) or max_attempts < 1:
        raise DriverError("--max-attempts must be a positive integer")
    if mode == "single":
        max_attempts = 1
    else:
        f = frozen(cmd)
        if f:
            raise DriverError(f"the command names freeze or preregistration {f}: a frozen run is never restarted, "
                              "so start it without --restartable")
    d = state_dir(where) / driver_id
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.close(os.open(d / SPEC, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
    except FileExistsError:
        raise DriverError(f"driver {driver_id} exists ({d}); see kit drivers status {driver_id}, revive a lost "
                          "restartable one, or pick a new id")
    workdir = Path(cwd or os.getcwd()).resolve()
    _write_json(d / SPEC, {"version": VERSION, "id": driver_id, "command": list(cmd), "cwd": str(workdir),
                           "mode": mode, "max_attempts": max_attempts, "created": _now(), "who": who, "note": note,
                           "run_dir": str(d / "run")})
    (d / "run" / "tmp").mkdir(parents=True, exist_ok=True)
    _new_attempt(d, 1, who)
    return d, _spawn(d, 1)


def supervise(d, n):
    """The supervisor body (python -m kit.drivers _supervise DIR N): run the command, record pids and its exit."""
    d = Path(d)
    spec = _read(d / SPEC)
    p = _attempt_path(d, n)
    rec = _read(p) or {"attempt": n}
    me = os.getpid()
    rec.update(supervisor={"pid": me, "start": proc_start(me)}, started=_now())
    _write_json(p, rec)
    run_dir = d / "run"
    (run_dir / "tmp").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, KIT_RUN_DIR=str(run_dir), TMPDIR=str(run_dir / "tmp"), KIT_DRIVER_ID=spec["id"],
               KIT_DRIVER_ATTEMPT=str(n), KIT_DRIVER_STATE=str(d))
    stopping = []
    child = []

    def on_signal(signum, _frame):
        stopping.append(signum)
        for c in child:
            try:
                c.send_signal(signal.SIGTERM)
            except OSError:
                pass

    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, on_signal)

    def runner(cmd):
        c = subprocess.Popen(cmd, cwd=spec["cwd"], env=env, stdin=subprocess.DEVNULL)
        child.append(c)
        rec["child"] = {"pid": c.pid, "start": proc_start(c.pid)}
        _write_json(p, rec)
        print(f"kit drivers: {spec['id']} attempt {n} pid {c.pid} on {socket.gethostname()} at {_now()}: "
              f"{' '.join(map(str, cmd))}", flush=True)
        while True:
            try:
                return c.wait()
            except InterruptedError:
                continue

    try:
        code = runner(list(spec["command"]))
    except OSError as exc:
        print(f"kit drivers: cannot start {spec['command'][0]}: {exc}", flush=True)
        code = 127
    rec.update(exit=code, finished=_now())
    if stopping:
        rec["ended"] = STOPPED_NOTE
    _write_json(p, rec)
    print(f"kit drivers: {spec['id']} attempt {n} exit {code} at {rec['finished']}", flush=True)
    return code


def revive(ids=None, where=None, dry_run=False, who=None, say=print):
    """Restart lost restartable drivers (all lost ones when ids is empty); returns (revived, refused) id lists."""
    revived, refused = [], []
    rows = drivers(where, ids)
    for row in rows:
        if not ids and row.get("state") != LOST:
            continue
        why = revivable(row)
        if why:
            refused.append(row["id"])
            say(f"{row['id']}: not revived: {why}")
            continue
        n = row["attempts"] + 1
        if dry_run:
            say(f"{row['id']}: would start attempt {n} of {row['max_attempts']} ({row['reason']})")
            revived.append(row["id"])
            continue
        d = state_dir(where) / row["id"]
        last = _attempt_path(d, n - 1)
        rec = _read(last) or {"attempt": n - 1}
        rec.setdefault("ended", f"lost: {row['reason']}; revived as attempt {n} at {_now()}")
        _write_json(last, rec)
        _new_attempt(d, n, who)
        _spawn(d, n)
        revived.append(row["id"])
        say(f"{row['id']}: started attempt {n} of {row['max_attempts']} (was lost: {row['reason']})")
    return revived, refused


def stop(driver_id, where=None, grace=10.0):
    """Stop a running driver: SIGTERM to its process group, SIGKILL after grace seconds. Returns its row after."""
    check_id(driver_id)
    d = state_dir(where) / driver_id
    rows = attempts(d)
    if not rows:
        raise DriverError(f"no driver {driver_id} in {state_dir(where)}")
    rec = rows[-1]
    if "exit" in rec:
        raise DriverError(f"{driver_id} attempt {rec['attempt']} already ended (exit {rec['exit']})")
    procs = [e for e in (rec.get("supervisor"), rec.get("child")) if alive(e)]
    for e in procs:
        try:
            os.killpg(os.getpgid(e["pid"]), signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + grace
    while time.time() < deadline and any(alive(e) for e in procs):
        time.sleep(0.2)
    for e in procs:
        if alive(e):
            try:
                os.killpg(os.getpgid(e["pid"]), signal.SIGKILL)
            except OSError:
                pass
    time.sleep(0.2)
    rec = _read(_attempt_path(d, rec["attempt"])) or rec
    if "exit" not in rec:                    # the supervisor was gone or killed before it wrote its exit
        rec.update(exit=-int(signal.SIGTERM), finished=_now(), ended=STOPPED_NOTE)
        _write_json(_attempt_path(d, rec["attempt"]), rec)
    return drivers(where, [driver_id])[0]


# ---------------------------------------------------------------- command line

def hook_lines(rows):
    lost = [r for r in rows if r.get("state") == LOST]
    if not lost:
        return []
    out = [f"kit drivers: {len(lost)} background driver(s) in this checkout were lost (no exit record):"]
    for r in lost:
        out.append(f"  {r['id']} ({r.get('mode')}, attempt {r.get('attempts')} of {r.get('max_attempts')}): "
                   f"{r['reason']}")
    out.append("Revive the restartable ones with `python3 -m kit drivers revive`; the others (launches, frozen "
               "runs) are never restarted. Details: python3 -m kit drivers status")
    return out


def add_arguments(p):
    p.add_argument("--dir", help=f"the state folder (default ${STATE_ENV}, else work/drivers in this checkout)")
    sub = p.add_subparsers(dest="what", required=True)
    s = sub.add_parser("start", usage="kit drivers start ID [--restartable] [--max-attempts N] [--cwd DIR] "
                       "[--note TEXT] -- COMMAND...",
                       help="run COMMAND as a recorded background driver with its own work folder")
    _start_options(s)
    s.add_argument("argv", nargs=argparse.REMAINDER, help="ID, its options, then -- and the command")
    st = sub.add_parser("status", help="running, finished, stopped and lost drivers; exit 3 when one is lost")
    st.add_argument("ids", nargs="*")
    st.add_argument("--json", action="store_true")
    st.add_argument("--hook", action="store_true", help="print only lost drivers, briefly; always exit 0")
    r = sub.add_parser("revive", help="restart lost --restartable drivers (all lost ones, or the ids given)")
    r.add_argument("ids", nargs="*")
    r.add_argument("--dry-run", action="store_true")
    k = sub.add_parser("stop", help="stop a running driver (SIGTERM, then SIGKILL after --grace seconds)")
    k.add_argument("id")
    k.add_argument("--grace", type=float, default=10.0)
    lg = sub.add_parser("log", help="the tail of a driver's log")
    lg.add_argument("id")
    lg.add_argument("-n", type=int, default=40)
    lg.add_argument("--attempt", type=int)
    w = sub.add_parser("whereami", help="this machine's host name and boot id, and the drivers recorded here")
    w.add_argument("--json", action="store_true")
    return p


def _start_options(p, defaults=True):
    """The start options. They may come before or after ID (argparse hands everything after the first positional to
    the command remainder, so run() parses that part again with _start_parser)."""
    keep = (lambda v: v) if defaults else (lambda v: argparse.SUPPRESS)
    p.add_argument("--restartable", action="store_true", default=keep(False),
                   help="revive may restart it once lost (refused for a command naming a freeze); without it the "
                        "driver is never revived")
    p.add_argument("--max-attempts", type=int, default=keep(3), help="starts allowed in all (restartable)")
    p.add_argument("--cwd", default=keep(None), help="the folder the command runs in (default: the current one)")
    p.add_argument("--note", default=keep(None), help="a note kept with the driver")
    return p


def _start_parser():
    p = argparse.ArgumentParser(prog="kit drivers start", add_help=False)
    p.add_argument("id", metavar="ID")
    return _start_options(p, defaults=False)


def run(args):
    where = args.dir
    try:
        if args.what == "start":
            argv = list(args.argv)
            if "--" not in argv:
                print("kit drivers start: give the command after --: kit drivers start ID [--restartable] -- CMD",
                      file=sys.stderr)
                return EXIT_ARGS
            i = argv.index("--")
            a = argparse.Namespace(**{k: v for k, v in vars(args).items() if k not in ("argv", "what", "dir")})
            a = _start_parser().parse_args(argv[:i], namespace=a)
            mode = "restartable" if a.restartable else "single"
            d, _proc_ = start(a.id, argv[i + 1:], mode, a.max_attempts, a.cwd, where,
                              who=os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("USER"), note=a.note)
            print(f"kit drivers: started {a.id} ({mode}); KIT_RUN_DIR={d / 'run'}; log {d / 'attempt-01.log'}")
            return EXIT_OK
        if args.what == "status":
            rows = drivers(where, args.ids or None)
            if args.hook:
                for line in hook_lines(rows):
                    print(line)
                return EXIT_OK
            if args.json:
                print(json.dumps(rows, indent=1))
            elif not rows:
                print(f"kit drivers: no drivers recorded in {state_dir(where)}")
            for r in ([] if args.json else rows):
                print(f"{r['id']:36} {r['state']:9} {r.get('mode') or '?':11} attempt {r.get('attempts', '?')}/"
                      f"{r.get('max_attempts', '?')}  {r['reason']}")
            return EXIT_LOST if any(r["state"] == LOST for r in rows) else EXIT_OK
        if args.what == "revive":
            _, refused = revive(args.ids or None, where, args.dry_run,
                                who=os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("USER"))
            return EXIT_PROBLEM if refused else EXIT_OK
        if args.what == "stop":
            r = stop(args.id, where, args.grace)
            print(f"{r['id']}: {r['state']} ({r['reason']})")
            return EXIT_OK
        if args.what == "log":
            d = state_dir(where) / check_id(args.id)
            n = args.attempt or len(attempts(d))
            p = d / f"attempt-{n:02d}.log"
            if not p.is_file():
                print(f"kit drivers: no log {p}", file=sys.stderr)
                return EXIT_ARGS
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[-args.n:]:
                print(line)
            return EXIT_OK
        if args.what == "whereami":
            me = whereami()
            rows = drivers(where)
            me.update(state_dir=str(state_dir(where)),
                      drivers={s: sum(r["state"] == s for r in rows) for s in (RUNNING, LOST, FINISHED, STOPPED)})
            if args.json:
                print(json.dumps(me, indent=1))
            else:
                for k in ("host", "boot_id", "platform", "state_dir"):
                    print(f"{k:10} {me[k]}")
                print("drivers    " + ", ".join(f"{v} {k}" for k, v in me["drivers"].items()))
            return EXIT_OK
    except DriverError as exc:
        print(f"kit drivers: {exc}", file=sys.stderr)
        return EXIT_PROBLEM
    return EXIT_ARGS


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_supervise"]:
        return supervise(argv[1], int(argv[2]))
    return run(add_arguments(argparse.ArgumentParser(prog="python -m kit drivers")).parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
