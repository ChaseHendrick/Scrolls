"""Recurring repository checks that run whichever agent or account opens this clone.

Chase moves between Claude accounts, Codex and ChatGPT during a day (16 Oct 2026), so the daily and weekly checks
the docs call for live in the repository, not in one account's scheduler. Every agent runs them at session start:

  python3 -m kit routines run --due [--background]  run what is due (the Claude Code SessionStart hook in
                                                    .claude/settings.json runs it with --background)
  python3 -m kit routines status [--json]           the last result of each routine, and what is due now
  python3 -m kit routines due [--json]              what is due now
  python3 -m kit routines list                      the registry, docs/routines.json
  python3 -m kit routines run --name N [--name M]   run the named routines now, due or not
  python3 -m kit routines run --ci [--strict]       the routines marked "ci", due or not (public GitHub Actions)
  python3 -m kit routines check handoff             built-in check: AGENTS.md and docs/HANDOFF.md size headroom
                                                    against tests/test_repo.py's limits, and the handoff's age

The registry, docs/routines.json, lists each routine: a name, a cadence (daily or weekly, counted in UTC dates), a
timeout in seconds, a command (an argument list in which "{python}" is this interpreter), why (where the repository
calls for it), optional requires (repository paths that must exist, or the routine is skipped as not here yet) and
optional ci (true: the public daily workflow runs it). A routine is due when it never completed, or last completed
one UTC day (daily) or seven (weekly) ago; one attempted in the last hour waits, so a skipped one is not retried at
every session start.

A command's exit code: 0 ok, 3 attention (something for an agent to look at), 75 skipped (offline or not available),
anything else fail. A failure whose output shows no network (urlopen error, a name that does not resolve) or a
missing third-party module is recorded as skipped. A routine that runs past its timeout is stopped with its whole
process group and recorded as timeout. `run` exits 1 when a routine failed or timed out (with --strict, also on
attention) and 0 otherwise; nothing a routine does can stop a session.

Results go to the ignored folder work/routines/: state.json (each routine's last result with UTC times) and
summary.md (a table, then the output of every routine that needs a look). One run at a time: a second run while
work/routines/run.lock is held prints so and exits 0.

Routines are read-only checks. They never post, comment, open issues, upload, push or start Modal. Every command
must be `python -m kit ...`, `python -m kit.MODULE ...` or `python -m unittest ...`, with no outward action word in
it (OUTWARD, checked when the registry loads), and runs with credential variables (names with TOKEN, SECRET,
PASSWORD, API_KEY, ACCESS_KEY or CREDENTIAL, MODAL_*, SSH_AUTH_SOCK) and KIT_ALLOW_MODAL removed from its
environment. Standard library only. The same file is in Scrolls and Scrolls-private; each has its own registry.
"""

import argparse
import ast
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "docs" / "routines.json"
STATE_DIR = ROOT / "work" / "routines"

CADENCE_DAYS = {"daily": 1, "weekly": 7}
OK, ATTENTION, SKIPPED, FAIL, TIMEOUT = "ok", "attention", "skipped", "fail", "timeout"
EXIT_ATTENTION, EXIT_SKIPPED = 3, 75
COMPLETED = (OK, ATTENTION, FAIL, TIMEOUT)   # a skipped routine stays due
RETRY = timedelta(hours=1)
MAX_TIMEOUT = 3600
TAIL_LINES, TAIL_CHARS = 40, 4000
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
# Argument words that would act outward or change tracked files; no routine command may contain one.
OUTWARD = {"push", "upload", "post", "comment", "submit", "deploy", "approve", "launch", "release", "add", "render",
           "pin", "unpin", "record", "record-submitted", "modal", "hfsync", "zerogpu", "kit.hfsync", "kit.zerogpu",
           "kit.submission_release", "--approve", "--push", "--upload", "--post", "--submit"}
SECRET_ENV = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_KEY|PRIVATE_KEY|CREDENTIAL|^MODAL_|^SSH_AUTH_SOCK$"
                        r"|^KIT_ALLOW_MODAL$", re.I)
OFFLINE = re.compile(r"urlopen error|Name or service not known|Temporary failure in name resolution|nodename nor servname"
                     r"|Network is unreachable|No route to host|getaddrinfo failed|Could not resolve host")
MISSING = re.compile(r"ModuleNotFoundError: No module named '([A-Za-z0-9_.]+)'")


class RoutineError(ValueError):
    pass


def utcnow():
    return datetime.now(timezone.utc)


def _iso(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- registry

def validate(registry):
    """The registry's routines, checked: names, cadences, timeouts and read-only commands."""
    if not isinstance(registry, dict) or not isinstance(registry.get("routines"), list):
        raise RoutineError("the registry needs a list under \"routines\"")
    seen, out = set(), []
    for r in registry["routines"]:
        name = r.get("name") if isinstance(r, dict) else None
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise RoutineError(f"routine name {name!r}: lower case letters, digits and -, at most 40")
        if name in seen:
            raise RoutineError(f"routine {name} is listed twice")
        seen.add(name)
        if r.get("cadence") not in CADENCE_DAYS:
            raise RoutineError(f"routine {name}: cadence must be one of {sorted(CADENCE_DAYS)}")
        t = r.get("timeout_s")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or not 0 < t <= MAX_TIMEOUT:
            raise RoutineError(f"routine {name}: timeout_s must be a number of seconds, at most {MAX_TIMEOUT}")
        cmd = r.get("command")
        if not isinstance(cmd, list) or not cmd or not all(isinstance(a, str) and a for a in cmd):
            raise RoutineError(f"routine {name}: command must be a list of strings")
        check_command(name, cmd)
        req = r.get("requires", [])
        if not isinstance(req, list) or not all(isinstance(p, str) and p and not Path(p).is_absolute()
                                                and ".." not in Path(p).parts for p in req):
            raise RoutineError(f"routine {name}: requires must list paths inside the repository")
        if not isinstance(r.get("why", ""), str) or not r.get("why"):
            raise RoutineError(f"routine {name}: say why the repository calls for it")
        out.append(dict(r, requires=req, ci=bool(r.get("ci", False))))
    return out


def check_command(name, cmd):
    """Refuse anything but a read-only command: python -m kit, python -m kit.MODULE or python -m unittest."""
    if len(cmd) < 3 or cmd[0] != "{python}" or cmd[1] != "-m":
        raise RoutineError(f"routine {name}: the command must start with {{python}} -m")
    module = cmd[2]
    if not (module in ("kit", "unittest") or re.fullmatch(r"kit\.[a-z_][a-z0-9_]*", module)):
        raise RoutineError(f"routine {name}: only kit, kit.MODULE or unittest may run, not {module}")
    bad = [a for a in cmd[2:] if a.lower() in OUTWARD]
    if bad:
        raise RoutineError(f"routine {name}: {bad[0]!r} looks like an outward action; routines only check")


def load(path=REGISTRY):
    path = Path(path)
    if not path.is_file():
        raise RoutineError(f"no routine registry at {path}; run kit routines from a clone of the repository")
    try:
        return validate(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise RoutineError(f"{path} is not JSON: {exc}")


# ---------------------------------------------------------------- state

def load_state(state_dir):
    path = Path(state_dir) / "state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(state, dict) and isinstance(state.get("routines"), dict):
            return state
    except (OSError, ValueError):
        pass
    return {"version": 1, "routines": {}}


def save_state(state_dir, state):
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = state_dir / f".state.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, state_dir / "state.json")


def is_due(routine, entry, now):
    """Due when never completed, or last completed CADENCE_DAYS UTC dates ago; nothing attempted within RETRY."""
    entry = entry or {}
    attempt = entry.get("last_attempt")
    if attempt:
        try:
            if now - _parse_time(attempt) < RETRY:
                return False
        except ValueError:
            pass
    done = entry.get("last_completed")
    if not done:
        return True
    try:
        last = date.fromisoformat(done)
    except ValueError:
        return True
    return (now.astimezone(timezone.utc).date() - last).days >= CADENCE_DAYS[routine["cadence"]]


def due(routines, state, now):
    return [r for r in routines if is_due(r, state["routines"].get(r["name"]), now)]


# ---------------------------------------------------------------- running

def child_env(base=None):
    env = {k: v for k, v in (os.environ if base is None else base).items() if not SECRET_ENV.search(k)}
    env.update(SCROLLS_ROUTINE="1", GIT_TERMINAL_PROMPT="0", PYTHONUNBUFFERED="1")
    return env


def _tail(text):
    lines = text.rstrip().splitlines()[-TAIL_LINES:]
    out = "\n".join(lines)
    return out[-TAIL_CHARS:]


def _stop(proc):
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass


def execute(argv, cwd, timeout, env=None):
    """Run one command; return (exit code or None on timeout, output text). Never raises for the command's sake."""
    kw = {"cwd": str(cwd), "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
          "stderr": subprocess.STDOUT}
    if os.name == "posix":
        kw["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, **kw)
    except OSError as exc:
        return EXIT_SKIPPED, f"cannot start {argv[0]}: {exc}"
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        _stop(proc)
        try:
            out, _ = proc.communicate(timeout=5)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            out = b""
        text = (out or b"").decode("utf-8", "replace")
        return None, text + f"\nstopped after the {timeout:g} s timeout"


def classify(code, output):
    """(status, note) from an exit code (None: timed out) and the command's output."""
    if code is None:
        return TIMEOUT, "ran past its timeout and was stopped"
    if code == 0:
        return OK, ""
    if code == EXIT_ATTENTION:
        return ATTENTION, "needs a look (exit 3)"
    if code == EXIT_SKIPPED:
        return SKIPPED, "not available here (exit 75)"
    m = MISSING.search(output)
    if m and m.group(1).split(".")[0] not in ("kit", "tests"):
        return SKIPPED, f"missing dependency {m.group(1)} (exit {code})"
    if OFFLINE.search(output):
        return SKIPPED, f"looks offline (exit {code})"
    return FAIL, f"exit {code}"


def run_one(routine, root, now=None, executor=execute):
    started = now or utcnow()
    missing = [p for p in routine.get("requires", []) if not (Path(root) / p).exists()]
    if missing:
        return {"status": SKIPPED, "code": None, "note": f"not here yet: {', '.join(missing)}", "output": "",
                "started": _iso(started), "seconds": 0.0}
    argv = [sys.executable if a == "{python}" else a for a in routine["command"]]
    t0 = time.monotonic()
    code, output = executor(argv, root, routine["timeout_s"], child_env())
    status, note = classify(code, output)
    return {"status": status, "code": code, "note": note, "output": _tail(output), "started": _iso(started),
            "seconds": round(time.monotonic() - t0, 1)}


def record(state, routine, result):
    entry = state["routines"].setdefault(routine["name"], {})
    entry["last"] = result
    entry["last_attempt"] = result["started"]
    if result["status"] in COMPLETED:
        entry["last_completed"] = result["started"][:10]
    history = entry.setdefault("history", [])
    history.append(f"{result['started']} {result['status']}")
    del history[:-10]
    return entry


def _alive(pid):
    if os.name != "posix":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def acquire_lock(state_dir, stale_after):
    """Take work/routines/run.lock; False when another live run holds it."""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "run.lock"
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                held = json.loads(path.read_text(encoding="utf-8"))
                fresh = time.time() - float(held["t"]) < stale_after and _alive(int(held["pid"]))
            except (OSError, ValueError, KeyError, TypeError):
                fresh = False
            if fresh:
                return False
            try:
                path.unlink()
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "t": time.time()}, fh)
        return True
    return False


def release_lock(state_dir):
    try:
        (Path(state_dir) / "run.lock").unlink()
    except OSError:
        pass


def run_routines(selected, root=ROOT, state_dir=STATE_DIR, now=None, executor=execute, budget=None, log=None,
                 clock=time.monotonic, registry=None):
    """Run the selected routines in order, saving state after each; returns the results by name, or None when
    another run holds the lock. With budget (seconds), routines not started in time stay due for next time. The
    summary lists every routine in registry (default: the selected ones)."""
    log = log or (lambda line: print(line, flush=True))
    stale = sum(r["timeout_s"] for r in selected) + 120
    if not acquire_lock(state_dir, stale):
        log("kit routines: another run is in progress (work/routines/run.lock); nothing started")
        return None
    results = {}
    t0 = clock()
    try:
        for r in selected:
            if budget is not None and clock() - t0 >= budget:
                log(f"  {r['name']:<22} left for next time (the {budget:g} s budget is used)")
                continue
            state = load_state(state_dir)
            result = run_one(r, root, now=now or utcnow(), executor=executor)
            record(state, r, result)
            save_state(state_dir, state)
            results[r["name"]] = result
            log(f"  {r['name']:<22} {result['status']:<9} {result['seconds']:>6.1f} s  {result['note']}".rstrip())
        write_summary(state_dir, registry or selected, load_state(state_dir), now or utcnow())
    finally:
        release_lock(state_dir)
    return results


# ---------------------------------------------------------------- reports

def rows(routines, state, now):
    out = []
    for r in routines:
        entry = state["routines"].get(r["name"], {})
        last = entry.get("last") or {}
        out.append({"name": r["name"], "cadence": r["cadence"], "last_run": last.get("started"),
                    "status": last.get("status", "never run"), "note": last.get("note", ""),
                    "due": is_due(r, entry, now), "output": last.get("output", "")})
    return out


def summary_markdown(routines, state, now):
    table = rows(routines, state, now)
    lines = ["# Routine results", "",
             f"Written by `python3 -m kit routines` at {_iso(now)}. Read it with `python3 -m kit routines status`; "
             "the registry is `docs/routines.json` (kit/routines.py). Routines only check: act on a row by reading "
             "its output, never by posting or launching anything.", "",
             "| Routine | Cadence | Last run (UTC) | Result | Note | Due now |", "| --- | --- | --- | --- | --- | --- |"]
    for row in table:
        lines.append(f"| {row['name']} | {row['cadence']} | {row['last_run'] or 'never'} | {row['status']} | "
                     f"{row['note'].replace('|', '/')} | {'yes' if row['due'] else 'no'} |")
    look = [row for row in table if row["status"] in (ATTENTION, FAIL, TIMEOUT)]
    if look:
        lines += ["", "## Needs a look", ""]
        for row in look:
            lines += [f"### {row['name']}: {row['status']}", "", "```text", row["output"] or "(no output)", "```", ""]
    return "\n".join(lines).rstrip() + "\n"


def write_summary(state_dir, routines, state, now):
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    text = summary_markdown(routines, state, now)
    tmp = state_dir / f".summary.{os.getpid()}.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, state_dir / "summary.md")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        try:
            with open(step, "a", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            pass
    return text


def status_text(routines, state, now, brief=False):
    table = rows(routines, state, now)
    look = [r for r in table if r["status"] in (ATTENTION, FAIL, TIMEOUT)]
    if brief:
        lines = []
        for r in look:
            first = (r["output"].strip().splitlines() or [""])[-1][:160]
            lines.append(f"  {r['name']}: {r['status']} at {r['last_run']}. {first}".rstrip())
        never = [r["name"] for r in table if r["status"] == "never run"]
        head = (f"kit routines: {len(look)} of {len(table)} need a look" if look
                else f"kit routines: none of {len(table)} need a look")
        if never:
            head += f"; never run here: {', '.join(never)}"
        return "\n".join([head + ". Details: python3 -m kit routines status (work/routines/summary.md)."] + lines)
    lines = [f"{'routine':<22} {'cadence':<7} {'last run (UTC)':<21} {'result':<10} due  note"]
    for r in table:
        lines.append(f"{r['name']:<22} {r['cadence']:<7} {(r['last_run'] or 'never'):<21} {r['status']:<10} "
                     f"{'yes' if r['due'] else 'no ':<4} {r['note']}".rstrip())
    for r in look:
        lines += ["", f"--- {r['name']} ({r['status']}) ---", r["output"] or "(no output)"]
    return "\n".join(lines)


# ---------------------------------------------------------------- built-in check: handoff

LIMITS = re.compile(r"for rel, limit in (\{[^{}]*\})\.items\(\)")


def _worse(code, new):
    """The more serious of two check exit codes: 1 (fail) over 3 (attention) over 0."""
    rank = {0: 0, EXIT_ATTENTION: 1, 1: 2}
    return code if rank.get(code, 2) >= rank.get(new, 2) else new


def size_limits(root):
    """{relative path: byte limit} from tests/test_repo.py's test_agent_entry_files_stay_short, or {}."""
    try:
        m = LIMITS.search((Path(root) / "tests" / "test_repo.py").read_text(encoding="utf-8"))
        limits = ast.literal_eval(m.group(1)) if m else {}
        return {str(k): int(v) for k, v in limits.items()}
    except (OSError, ValueError, SyntaxError, TypeError):
        return {}


def _git_last_change(root, rel):
    """(UTC datetime of the last commit that touched rel, whether it has uncommitted changes); (None, False) if
    git cannot say."""
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%cI", "--", rel], capture_output=True,
                             text=True, timeout=20)
        dirty = subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", rel], capture_output=True,
                               timeout=20).returncode == 1
        stamp = out.stdout.strip()
        return (datetime.fromisoformat(stamp).astimezone(timezone.utc) if stamp else None), dirty
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None, False


def check_handoff(root=ROOT, max_age_days=3, warn_fraction=0.9, now=None, last_change=_git_last_change,
                  handoff="docs/HANDOFF.md"):
    """(exit code, lines): 1 when a file is over its tests/test_repo.py limit, 3 when one is within warn_fraction of
    it or the handoff has not changed for max_age_days, else 0. Problems come last, so a one-line view shows one."""
    now = now or utcnow()
    root = Path(root)
    code, info, problems = 0, [], []
    limits = size_limits(root)
    if not limits:
        code = _worse(code, EXIT_ATTENTION)
        problems.append("no size limits found in tests/test_repo.py (test_agent_entry_files_stay_short); "
                        "check by hand")
    for rel, limit in sorted(limits.items()):
        path = root / rel
        if not path.is_file():
            code = _worse(code, 1)
            problems.append(f"{rel}: missing")
            continue
        size = len(path.read_bytes())
        left = limit - size
        if size > limit:
            code = _worse(code, 1)
            problems.append(f"{rel}: {size} bytes, over its {limit}-byte limit; tests/test_repo.py fails")
        elif size >= warn_fraction * limit:
            code = _worse(code, EXIT_ATTENTION)
            hint = ("move its oldest dated sections, unchanged, to the top of docs/HANDOFF-archive.md"
                    if rel.endswith("HANDOFF.md") else "keep new detail in docs/ (MAP.md, AI-AGENTS.md), not here")
            problems.append(f"{rel}: {size} of {limit} bytes, only {left} left; {hint}")
        else:
            info.append(f"{rel}: {size} of {limit} bytes, {left} left")
    when, dirty = last_change(root, handoff)
    if dirty:
        info.append(f"{handoff}: has uncommitted changes (being edited now)")
    elif when is None:
        info.append(f"{handoff}: git cannot say when it last changed")
    else:
        age = (now - when).total_seconds() / 86400
        if age > max_age_days:
            code = _worse(code, EXIT_ATTENTION)
            problems.append(f"{handoff}: last committed {_iso(when)}, {age:.1f} days ago; check its open items are "
                            "current and update it on the default branch (AGENTS.md rule 14)")
        else:
            info.append(f"{handoff}: last committed {_iso(when)}, {age:.1f} days ago")
    return code, info + problems


# ---------------------------------------------------------------- command line

def add_arguments(p):
    p.add_argument("--registry", default=str(REGISTRY), help="the routine list (default docs/routines.json)")
    p.add_argument("--state", default=str(STATE_DIR), help="results folder (default work/routines, git-ignored)")
    actions = p.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="every routine: cadence, timeout, command and why")
    a = actions.add_parser("due", help="the routines due now")
    a.add_argument("--json", action="store_true")
    a = actions.add_parser("status", help="each routine's last result, and what is due now")
    a.add_argument("--json", action="store_true")
    a.add_argument("--brief", action="store_true", help="one line, plus one per routine that needs a look")
    a = actions.add_parser("run", help="run routines: all, --due, --ci or --name; results in work/routines/")
    g = a.add_mutually_exclusive_group()
    g.add_argument("--due", action="store_true", help="only the routines due now")
    g.add_argument("--ci", action="store_true", help="the routines marked ci, due or not")
    a.add_argument("--name", action="append", default=[], help="run this routine now (repeatable)")
    a.add_argument("--background", action="store_true",
                   help="start the run detached and return at once with the last results (session start)")
    a.add_argument("--budget", type=float, help="seconds: start no routine after this much time has gone")
    a.add_argument("--strict", action="store_true", help="exit 1 on attention as well as on fail and timeout")
    a = actions.add_parser("check", help="built-in checks routines call")
    a.add_argument("what", choices=["handoff"])
    a.add_argument("--max-age-days", type=float, default=3.0)
    a.add_argument("--warn-fraction", type=float, default=0.9)


def select(routines, state, now, args):
    if args.name:
        known = {r["name"]: r for r in routines}
        unknown = [n for n in args.name if n not in known]
        if unknown:
            raise RoutineError(f"no routine named {', '.join(unknown)}; see python3 -m kit routines list")
        return [known[n] for n in args.name]
    if args.ci:
        return [r for r in routines if r["ci"]]
    if args.due:
        return due(routines, state, now)
    return list(routines)


def spawn_background(args, root=ROOT, popen=subprocess.Popen):
    state_dir = Path(args.state)
    state_dir.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "kit", "routines", "--registry", str(args.registry), "--state", str(state_dir),
            "run"]
    argv += ["--due"] if args.due else ["--ci"] if args.ci else []
    for n in args.name:
        argv += ["--name", n]
    if args.budget is not None:
        argv += ["--budget", str(args.budget)]
    kw = {"cwd": str(root), "stdin": subprocess.DEVNULL, "close_fds": True}
    if os.name == "posix":
        kw["start_new_session"] = True
    else:
        kw["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with open(state_dir / "last-run.log", "ab") as fh:
        fh.write(f"\n== {_iso(utcnow())} {' '.join(argv[3:])}\n".encode())
        fh.flush()
        popen(argv, stdout=fh, stderr=subprocess.STDOUT, **kw)


def run(args):
    now = utcnow()
    try:
        if args.action == "check":
            code, lines = check_handoff(ROOT, args.max_age_days, args.warn_fraction, now)
            print("\n".join(lines))
            return code
        routines = load(args.registry)
        state = load_state(args.state)
        if args.action == "list":
            for r in routines:
                req = f"  (needs {', '.join(r['requires'])})" if r["requires"] else ""
                ci = "  [ci]" if r["ci"] else ""
                print(f"{r['name']:<22} {r['cadence']:<7} {r['timeout_s']:>5g} s  {' '.join(r['command'])}{req}{ci}")
                print(f"{'':<22} {r['why']}")
            return 0
        if args.action == "due":
            names = [r["name"] for r in due(routines, state, now)]
            print(json.dumps(names) if args.json else ("\n".join(names) if names else "nothing is due"))
            return 0
        if args.action == "status":
            if args.json:
                print(json.dumps(rows(routines, state, now), indent=2))
            else:
                print(status_text(routines, state, now, brief=args.brief))
            return 0
        selected = select(routines, state, now, args)
        if args.background:
            names = [r["name"] for r in selected]
            if names:
                spawn_background(args)
                print(f"kit routines: started in the background: {', '.join(names)}.")
            print(status_text(routines, state, now, brief=True))
            return 0
        if not selected:
            print("kit routines: nothing is due")
            return 0
        print(f"kit routines: running {len(selected)}: {', '.join(r['name'] for r in selected)}", flush=True)
        results = run_routines(selected, ROOT, args.state, budget=args.budget, registry=routines)
        if results is None:
            return 0
        bad = {FAIL, TIMEOUT} | ({ATTENTION} if args.strict else set())
        print(f"kit routines: results in {Path(args.state) / 'summary.md'}")
        return 1 if any(r["status"] in bad for r in results.values()) else 0
    except RoutineError as exc:
        print(f"routines: {exc}", file=sys.stderr)
        return 2


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit routines", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
