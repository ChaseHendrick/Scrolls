# drivers: background jobs that cannot die unnoticed

Runs a long command as a recorded background driver with its own work folder, says when it was lost to a kill, a container restart or a reboot, and revives only the drivers started as restartable.

| Field | Value |
| --- | --- |
| Id | `drivers` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Pipeline and agents |
| Run | `python -m kit drivers start`, `python -m kit drivers status`, `python -m kit drivers revive`, `python -m kit drivers stop`, `python -m kit drivers log`, `python -m kit drivers whereami`, `python -m kit.drivers`, `from kit import drivers` |
| Code | `kit/drivers.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_drivers.py` |
| Needs | Python 3.10 or newer, standard library only. Linux or macOS (process groups, `/proc` or `ps`, a boot id from `/proc/sys/kernel/random/boot_id` or `sysctl kern.boottime`) |
| Runs on | Any machine; each action took about 0.2 s wall (measured 2026-11-20, 4-core cloud container) |
| Network | None |
| Writes | The state folder (`$KIT_DRIVERS_DIR`, else `work/drivers` in this checkout, ignored by git): per driver `driver.json`, `attempt-NN.json`, `attempt-NN.log` and the work folder `run/`. Whatever the command itself writes |
| Go-ahead | Not needed for the tool. A command it runs that rents compute or posts anything needs its own go-ahead (the go-ahead rule, hard rule 8) |
| Released | Public `main` from the PR that adds this page (2026-11-20) |
| Checked | 2026-11-20 against commit `357d2bd` |

## What it does

A long job started with `nohup ... &` leaves no record of what ran, where, or how it ended. When a cloud container restarts or a laptop reboots, the job is gone, and a killed job looks the same as a finished one until someone runs `pgrep`. Two helpers that write to one fixed path such as `/tmp/job` can also collide when they land on one machine.

`kit drivers start ID -- COMMAND` runs the command under a small supervisor (its own session and process group, stdin closed, output to the attempt's log) and records the command, the host, the machine's boot id, the pids with their process start times, and the exit code when it ends. The command gets its own work folder in `$KIT_RUN_DIR`, the same for every attempt of that driver and never shared with another driver.

`kit drivers status` names each driver running, finished, stopped, starting (its first 30 s) or lost. A driver is lost when it has no exit record and its processes are gone (a reused pid with another start time does not count as alive), or when the machine's boot id changed since it started. Status exits 3 when any driver is lost, so a session-start hook or a script can see it at once.

`kit drivers revive` restarts lost drivers that were started with `--restartable`, as the next attempt with the same command and the same work folder, up to `--max-attempts` starts in all. A driver started without `--restartable` (mode `single`) is never revived: it stands for a launch or a frozen run, which must not run twice by accident. `start --restartable` also refuses a command that names a freeze ([freeze](freeze.md)): `--frozen ID`, `--freeze ID`, `--prereg PATH`, `-e KIT_FREEZE=ID`, a leading `KIT_FREEZE=ID`, or `KIT_FREEZE` set in the environment.

It does not restart anything by itself, does not survive the loss of its state folder (a new cloud container starts with an empty one), and does not move work between machines.

## When to use it

- Any job you would start with `nohup ... &` and come back to later: a long CPU run, a download, a watcher.
- A job that can resume from its own files: start it `--restartable` and have it write under `$KIT_RUN_DIR`.
- At the start of a session, to see whether anything was lost: `python -m kit drivers status --hook`.

Do not use it:

- For paid cloud jobs: launch them on Hugging Face (the paid compute rule, hard rule 11) and follow their own progress records.
- To rerun a frozen run: a rerun needs a new freeze ([freeze](freeze.md)), started under a new id.
- For a job that must survive the machine itself: use a scheduler on a machine that stays up.

## Quick start

```bash
export KIT_DRIVERS_DIR=$(mktemp -d)
python -m kit drivers start demo --restartable -- sh -c 'echo attempt $KIT_DRIVER_ATTEMPT; sleep 30'
python -m kit drivers status
kill -9 -$(python3 -c "import json,os; print(json.load(open(os.environ['KIT_DRIVERS_DIR'] + '/demo/attempt-01.json'))['supervisor']['pid'])")
python -m kit drivers status; echo "exit $?"
python -m kit drivers revive
python -m kit drivers log demo
python -m kit drivers stop demo
```

The `kill -9` of the supervisor's process group stands in for a container restart. Printed (2026-11-20, cloud container; folder names shortened):

```
kit drivers: started demo (restartable); KIT_RUN_DIR=/tmp/tmp.X/demo/run; log /tmp/tmp.X/demo/attempt-01.log
demo                                 running   restartable attempt 1/3  pid 757 since 2026-11-20T11:11:26Z
demo                                 lost      restartable attempt 1/3  attempt 1 process is gone with no exit record
exit 3
demo: started attempt 2 of 3 (was lost: attempt 1 process is gone with no exit record)
attempt 2
kit drivers: demo attempt 2 pid 769 on vm at 2026-11-20T11:11:28Z: sh -c echo attempt $KIT_DRIVER_ATTEMPT; sleep 30
demo: stopped (stopped at 2026-11-20T11:11:29Z (exit -15))
```

It worked when status says lost with exit 3 after the kill, and revive starts attempt 2.

## Checks and controls

A lost driver must be reported lost, and a running one must not be: both directions are tested, with controls.

Outside check (20 Nov 2026): a clean install (`kit/__init__.py` and the driver module only, no third-party package), with no other checkout visible, on a Linux cloud container. Every preregistered bar was met:

| Case | Result |
| --- | --- |
| Control: drivers alive | running, exit 0 |
| Control: boot id patched to its real value | running |
| Fresh process table (status from a new pid namespace with its own `/proc`) | all three live drivers lost, exit 3 |
| SIGKILL of each supervisor's process group | lost, `process is gone with no exit record`, exit 3 |
| New boot id | lost, `boot id changed`; the hook printed the lost drivers |
| `revive` after the restart | started attempt 2 of the restartable drivers (the child alive, `KIT_DRIVER_ATTEMPT` 1 then 2 in its own work folder); refused the once-only driver, exit 1; left the driver that had finished with exit 4 at 1 attempt |
| `--max-attempts 2`, killed again | refused, `used all 2 attempts`, exit 1 |

That check ran the workbench copy, whose `--once` mode and `--restartable` start imported other workbench modules (the outside check found that the page's "standard library only" did not hold for them). This public copy drops `--once` (a driver started without `--restartable` takes its place as the never-revived kind) and replaces the launch gate with the standalone `frozen()` check, so it is standard library only. The public tests repeat the bars from the command line: SIGKILL, a boot id change, a fresh pid namespace where `unshare` is allowed (skipped where it is not), revive of the restartable driver only, a finished driver left alone, and the attempt limit.

Scope: Linux, a simulated restart (SIGKILL and a changed boot id). Not covered: a real reboot, and macOS paths (`ps` and `sysctl` instead of `/proc`).

Claim label: Sourced fact (the outside check's states and exit codes, 20 Nov 2026, and the public tests).

## Commands and options

### `python -m kit drivers` (before the action)

```
usage: python -m kit drivers [-h] [--dir DIR]
                             {start,status,revive,stop,log,whereami} ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--dir DIR` | none | The state folder (default `$KIT_DRIVERS_DIR`, else `work/drivers` in this checkout). It goes before the action |

### `python -m kit drivers start`

```
usage: kit drivers start ID [--restartable] [--max-attempts N] [--cwd DIR] [--note TEXT] -- COMMAND...
```

The options may come before or after ID; everything after `--` is the command.

| Option | Default | Meaning |
| --- | --- | --- |
| `--restartable` | off | `revive` may start it again once lost (refused for a command naming a freeze); without it the driver is never revived and its max attempts is 1 |
| `--max-attempts MAX_ATTEMPTS` | `3` | Starts allowed in all, for a restartable driver |
| `--cwd CWD` | none | The folder the command runs in (default: the current one) |
| `--note NOTE` | none | A note kept with the driver |
| `argv` | none | ID, its options, then `--` and the command |

### `python -m kit drivers status`

```
usage: python -m kit drivers status [-h] [--json] [--hook] [ids ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `ids` | none | Only these drivers (default: every driver in the state folder) |
| `--json` | off | Print one JSON list of rows |
| `--hook` | off | Print only lost drivers, briefly; always exit 0 (for a session-start hook) |

### `python -m kit drivers revive`

```
usage: python -m kit drivers revive [-h] [--dry-run] [ids ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `ids` | none | Only these drivers; a named driver that is not lost is refused (default: every lost driver) |
| `--dry-run` | off | Say what would start, start nothing |

### `python -m kit drivers stop`

```
usage: python -m kit drivers stop [-h] [--grace GRACE] id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | The driver to stop |
| `--grace GRACE` | `10.0` | Seconds between SIGTERM and SIGKILL to its process groups |

### `python -m kit drivers log`

```
usage: python -m kit drivers log [-h] [-n N] [--attempt ATTEMPT] id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | The driver |
| `-n N` | `40` | Lines from the end of the log |
| `--attempt ATTEMPT` | none | Which attempt's log (default: the latest) |

### `python -m kit drivers whereami`

```
usage: python -m kit drivers whereami [-h] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | Print one JSON object: host, boot id, platform, Python, pid, state folder and driver counts |

`python -m kit.drivers` takes the same options and actions; `python -m kit.drivers _supervise DIR N` is the supervisor itself, started by `start` and `revive`, never by hand.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_DRIVERS_DIR` | `work/drivers` in this checkout | The state folder (`STATE_ENV`) |
| `KIT_FREEZE` | unset | When set, `start --restartable` is refused: the run is frozen |
| `CLAUDE_SESSION_ID` | unset | Recorded as `who` when set |
| `USER` | the login name | Recorded as `who` when `CLAUDE_SESSION_ID` is unset |

Set for the command: `KIT_RUN_DIR` (STATE/ID/run), `TMPDIR` (STATE/ID/run/tmp), `KIT_DRIVER_ID`, `KIT_DRIVER_ATTEMPT` (1, 2, ...) and `KIT_DRIVER_STATE` (STATE/ID).

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `DriverError()` | an exception | | The action may not go ahead; the message says why |
| `state_dir(where=None)` | `Path` | | `where`, else `$KIT_DRIVERS_DIR`, else `DEFAULT_STATE` |
| `check_id(driver_id)` | the id | `DriverError` | Letters, digits, `.`, `_` and `-`, first a letter or digit, at most 121 characters |
| `boot_id()` | `str` or `None` | | An id that changes at every boot of this machine or container, or None when it cannot be read |
| `proc_start(pid)` | `str` or `None` | | The process start time of a live pid |
| `alive(entry)` | `bool` | | True when a recorded `{pid, start}` process still runs and is the same process (not a zombie, not a reused pid) |
| `whereami()` | dict | | host, boot_id, platform, python, pid |
| `attempts(d)` | list of dicts | | Every attempt record of driver folder `d`, oldest first |
| `judge(spec, rows, here=None, now=None)` | `(state, reason)` | | A driver's state from its spec and attempt records, as seen from this machine |
| `drivers(where=None, ids=None, now=None)` | list of dicts | | One row per driver: id, mode, attempts, max_attempts, state, reason, exit, command, note, log |
| `revivable(row)` | `None` or `str` | | None when a lost driver may be revived, else why not |
| `frozen(cmd, env=None)` | `str` or `None` | | The freeze or preregistration a command names (see What it does), or `KIT_FREEZE` from `env` (default `os.environ`) |
| `start(driver_id, cmd, mode='single', max_attempts=3, cwd=None, where=None, who=None, note=None)` | `(Path, Popen)` | `DriverError` | Records and starts a driver; mode `restartable` or `single` |
| `supervise(d, n)` | exit code | | The supervisor body: runs the command, records pids and its exit |
| `revive(ids=None, where=None, dry_run=False, who=None, say=print)` | `(revived, refused)` id lists | `DriverError` | Restarts lost restartable drivers (all lost ones when `ids` is empty) |
| `stop(driver_id, where=None, grace=10.0)` | the driver's row after | `DriverError` | SIGTERM to its process groups, SIGKILL after `grace` seconds |
| `hook_lines(rows)` | list of str | | The lines `status --hook` prints: empty when nothing is lost |
| `add_arguments(p)` | the parser | | Adds `--dir` and the actions to an argparse parser |
| `run(args)` | exit code | | Runs parsed arguments |
| `main(argv=None)` | exit code | | The `python -m kit.drivers` entry point |

## Inputs

- The command after `--`: any program and arguments, run with the working folder `--cwd` (default the current one) and stdin closed.
- The state folder, which must be on the machine that runs the drivers.

## Outputs

Files under STATE/ID/: `driver.json` (version, id, command, cwd, mode, max_attempts, created, who, note, run_dir), `attempt-NN.json` (attempt, requested, host, boot_id, who, then supervisor and child `{pid, start}`, started, and at the end exit, finished, and `ended` when stopped or revived after a loss), `attempt-NN.log` and `run/`.

`status --json` prints one row per driver:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | The driver id |
| `mode` | string | `restartable` or `single` |
| `attempts`, `max_attempts` | integer | Starts so far, and allowed |
| `state` | string | `running`, `finished`, `stopped`, `starting`, `lost`, or `unknown` (no readable `driver.json`) |
| `reason` | string | Why, in words (a pid, an exit code, or how it was lost) |
| `exit` | integer or null | The last attempt's exit code |
| `command` | list | The command |
| `note` | string or null | The note |
| `log` | string or null | The last attempt's log path |

| Exit code | Meaning |
| --- | --- |
| `0` | Done; for `status`, no driver is lost |
| `1` | A refusal (`kit drivers: ...` on stderr), or `revive` refused at least one driver |
| `2` | Wrong arguments, or no such log |
| `3` | `status`: at least one driver is lost |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit drivers start: give the command after --: kit drivers start ID [--restartable] -- CMD` | No `--` | Put the command after `--` |
| `kit drivers: ERROR` | One of the refusals below | Read the message |
| `ID is not a driver id (letters, digits, '.', '_' and '-', first a letter or digit)` | A bad id | Pick another id |
| `give the command after --` | An empty command | Give a command |
| `mode must be one of MODES` | A bad mode in code | Use `restartable` or `single` |
| `--max-attempts must be a positive integer` | Zero or less | Give 1 or more |
| `driver ID exists (DIR); see kit drivers status ID, revive a lost restartable one, or pick a new id` | The id was used | Revive it, or start under a new id |
| `PATH exists: another start or revive claimed attempt N at the same time` | Two revives raced | Run status; one of them started it |
| `the command names freeze or preregistration ID: a frozen run is never restarted, so start it without --restartable` | `--restartable` on a frozen run | Start it without `--restartable` |
| `no driver ID in DIR` | `stop` of an unknown id | Check `--dir` and the id |
| `ID attempt N already ended (exit CODE)` | `stop` of a finished driver | Nothing to stop |
| `kit drivers: no log PATH` | `log` of an attempt with no log | Check `--attempt` |
| `ID: not revived: it is STATE, not lost` | `revive ID` of a driver that is not lost | Nothing to do |
| `ID: not revived: it was started without --restartable ...` | A single driver | Read its log; start it again under a new id if it should run again |
| `ID: not revived: it has used all N attempts ...` | The attempt limit | Read its log before starting it under a new id |

## How it works

1. `start` checks the id and the command, claims STATE/ID/driver.json with an exclusive create (so one id starts once), writes it and the first attempt record, and starts `python -m kit.drivers _supervise STATE/ID 1` detached (`start_new_session`, stdin closed, output to the attempt log).
2. The supervisor records its own pid and start time, starts the command with the driver environment, records the child, waits, and writes the exit code and finish time. SIGTERM, SIGINT and SIGHUP are passed to the child and marked as a stop.
3. `judge` reads the last attempt: an exit record means finished or stopped; otherwise a changed boot id (or, when either side has no boot id, another host name) means lost; a live supervisor or child means running; within `STARTING_GRACE_S` (30 s) of the request with no supervisor yet it is starting; anything else is lost. A process counts as alive only when its start time (field 22 of `/proc/PID/stat`, or `ps -o lstart`) matches the one recorded and it is not a zombie.
4. `revive` refuses anything `revivable` refuses, notes on the lost attempt how it ended, claims the next attempt file with an exclusive create, and starts a new supervisor.
5. `stop` sends SIGTERM to the process groups of the live supervisor and child, waits up to `--grace` seconds, then sends SIGKILL, and writes an exit record if the supervisor could not.

## Cost and time

Each action took about 0.2 s wall (measured 2026-11-20, 4-core cloud container). The supervisor is one small Python process per running driver. It rents nothing.

## For agents

- **Command:** `python -m kit drivers start ID --restartable -- COMMAND`, then `python -m kit drivers status --json`.
- **Parse:** `state` per row; `lost` rows carry the reason; `attempts` against `max_attempts`.
- **Rerun:** `status`, `log` and `whereami` are read-only. `start` of a used id is refused. `revive` starts a new attempt each time a driver is lost.
- **Success:** exit 0 from `start`; `status` exit 0 with the driver `running` or `finished` with `exit` 0.
- **Not a pass:** `finished` says the command ended, not that it worked: read its exit code and log. An empty status in a new container does not mean nothing was lost elsewhere.
- **Go-ahead:** Nothing for the tool; the command's own outward steps need theirs.
- **Never:** never start a frozen run `--restartable`; never write a driver's output to a fixed path such as `/tmp/job` instead of `$KIT_RUN_DIR`.

## Tests

`python -m unittest tests.test_drivers` covers a finished driver's exit and work folder, separate work folders, stop, lost after SIGKILL then revive up to the attempt limit, a boot id change with a live pid, a reused pid, the starting grace, a single driver never revived and a finished one left alone, the freeze refusal in each command form, the command line after a boot id change and in a fresh pid namespace (where `unshare` is allowed), the hook lines and the argument parsing. Not covered: a real reboot and macOS.

## History

- 2026-11-20: released to public Scrolls, on top of `357d2bd`, after an outside check; `--once` and its launch gate import dropped, `frozen()` made standalone.

## Related

- [freeze](freeze.md): a frozen run's files and why it is never restarted.
- [hubcall](hubcall.md): released with it after the same outside checks.
- [routines](routines.md): the session-start routine runner, where a `status --hook` call fits.
