# run-local: log a local run's time and estimated electricity cost

`python -m kit run local` runs a command on this machine and appends its wall time, CPU time and an estimated electricity cost to an experiment's ledger record; `python -m kit run backfill` adds past runs from a JSON list of logged durations.

| Field | Value |
| --- | --- |
| Id | `run-local` |
| Status | Current |
| Kind | kit command, kit module, data |
| Area | Compute and cost |
| Run | `python -m kit run local`, `python -m kit run backfill`, `from kit import localcost` |
| Code | `kit/localcost.py`, `scripts/backfill/`, `kit/cli.py` (`cmd_run`) |
| Tests | `tests/test_localcost.py`, `tests/test_localcost_regressions.py` |
| Needs | Python 3.10 or newer, standard library only. An experiment made first with `python -m kit run init`, and an electricity rate (option, environment variable or local configuration file) |
| Runs on | Mac or Linux; the CPU-time counter and the writer lock need a POSIX system, and elsewhere CPU time is recorded as null and writes must be serial. The wrapper's own overhead is not measured |
| Network | None |
| Writes | Appends cost entries to `experiments/SLUG/run.json` (or `ROOT/SLUG/run.json` with `--root`), replacing the file atomically through a temporary `.local-cost-*` file in that folder, and leaves a lock file `run.local-cost.lock` beside it. The wrapped command writes whatever it writes |
| Go-ahead | Not needed for the wrapper. Long local jobs fall under the Modal rule (hard rule 11): a job that needs a GPU or more than about an hour of CPU goes to Modal instead |
| Released | Public `main` since 2026-10-07 (`7878089`) |
| Guide | [compute.md, local runs](../compute.md#local-runs-time-and-electricity) |
| License | Apache 2.0, the repository's [LICENSE](../../LICENSE), for the code and the backfill list |
| Checked | 2026-10-16 against commit `63ee638` |

## What it does

The local-compute rule (hard rule 9 in `AGENTS.md`) asks that every local run, on the Mac's CPU or its MPS GPU, be wrapped so its wall time and electricity cost reach the experiment ledger. The experiment ledger is the set of `experiments/SLUG/run.json` records that `python -m kit run init` starts ([run-ledger](run-ledger.md)); `SLUG` is the experiment's short name.

`kit run local SLUG -- COMMAND` starts `COMMAND` as a child process, waits for it, and appends one entry to the record's `costs` list: start and end times (UTC), wall seconds, CPU seconds of the child, the device class and its assumed watts, estimated kWh (watts times hours) and estimated USD (kWh times the electricity rate), the command line, and the child's exit code. It then exits with the child's exit code, so it can sit in a script in place of the bare command. The child's own output passes through unchanged; the wrapper's one summary line goes to stderr.

`kit run backfill SLUG --file FILE` adds runs that happened before the wrapper existed, from a JSON list of logged durations, each marked "estimated from logs". `scripts/backfill/2026-10-07-local-runs.json` is the one such list in the tree: seven Mac runs of 7 October 2026 (six on the CPU, one on MPS), 7,280.5 s in all.

Wall power is not measured: macOS `powermetrics` needs sudo. The energy and dollar figures are estimates from an assumed average draw per device class (`DEVICE_WATTS`), and the electricity rate is the user's own, kept out of git. Only wall time and CPU time are measurements.

## When to use it

- Every local run worth recording: an ink-map inference, a scoring pass, a smoke test of a Mac script.
- Adding past local runs from their logs once, so an experiment's cost is complete.

Do not use it:

- For Modal or other rented compute: record the spend with [modal-row](modal-row.md) and price it with [cloudcost](cloudcost.md).
- To total machine time across many runs from their provenance records: use [compute](compute.md).
- To record a cost you already know in dollars: use `python -m kit run cost` ([run-ledger](run-ledger.md)).
- To backfill a run that the wrapper already recorded: that counts it twice.

## Quick start

```bash
python -m kit run init SLUG --scroll SCROLL --question "QUESTION" --readout "READOUT"
export SCROLLS_ELECTRICITY_USD_PER_KWH=RATE
python -m kit run local SLUG -- COMMAND ARGS
python -m kit run local SLUG --device apple-silicon-gpu -- COMMAND ARGS
python -m kit run backfill SLUG --file scripts/backfill/2026-10-07-local-runs.json
```

- `SLUG`: the experiment's short name; `SCROLL`, `QUESTION` and `READOUT` are what `run init` asks for ([run-ledger](run-ledger.md)).
- `RATE`: your electricity price in USD per kWh. Set it once in `~/.config/scrolls/local.json` instead, as `{"electricity_usd_per_kwh": RATE}`.
- `COMMAND ARGS`: the run, exactly as you would type it. Everything after `--` goes to the child.
- `--device apple-silicon-gpu`: for an MPS-heavy run; the default on a Mac is `apple-silicon-cpu`.

In a scratch ledger (`--root` pointed at a temporary folder, rate 0.30, on a Linux cloud container, synthetic commands) it printed:

```
child done
demo: 1.1 s wall, 0.1 s CPU, 0.0000 kWh, $0.0000 (exit 0)
demo: 0.0 s wall, 0.0 s CPU, 0.0000 kWh, $0.0000 (exit 3)
demo: backfilled 7 entries, 2.022 h, $0.0186 (estimated from logs)
```

The first line is the child's own output; the second and third are the wrapper's summaries on stderr, and the third run returned exit code 3, the child's. It worked when the summary line appears and `run.json` gained an entry under `costs`. The printed figures round to 4 decimals; the ledger keeps 6.

## Checks and controls

- **Fails before launching.** With no rate, a rate or watts that is not a finite nonnegative number, an unknown device, a broken configuration file, or no experiment, the command stops with exit code 2 before the child starts, and nothing is written (`test_no_rate_fails_before_running`, `test_invalid_rate_and_watts_fail_before_child_launch`).
- **Measured against estimated.** `wall_s`, `cpu_s` and `exit_code` are measured. `kwh` and `usd_exact` are estimates from assumed watts; backfilled entries carry `"estimated_from_logs": true`, null times and a null `cpu_s`. Quote the two kinds separately.
- **All or nothing.** A backfill file is validated whole before any entry is written, so one bad item leaves the ledger as it was (`test_invalid_backfill_tail_never_partially_commits`); a failed atomic replace also leaves it unchanged (`test_failed_atomic_replace_preserves_original_ledger`).
- **A check of the arithmetic.** The backfill in the Quick start: 7,280.5 s is 2.022 h; 6,850.5 s at 30 W and 430 s at 40 W make 0.06187 kWh, and at 0.30 USD per kWh that is 0.0186 USD, as printed.

Claim label: None. Wall time, CPU time and exit codes are measurements of the wrapped run; kWh and USD are estimates from assumed device watts and the user's rate.

## Commands and options

`--root ROOT` belongs to `python -m kit run` and goes before the action: `python -m kit run --root ROOT local SLUG -- COMMAND`. Its default is `experiments` (`ledger.DEFAULT_ROOT`), relative to the current folder.

### `python -m kit run local`

```
usage: python -m kit run local [-h]
                               [--device {apple-silicon-cpu,apple-silicon-gpu,apple-silicon-idle,cuda-gpu,x86-cpu}]
                               [--watts WATTS] [--rate RATE]
                               slug [cmd ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `slug` | required | The experiment to charge, an existing `ROOT/SLUG/run.json` |
| `--device DEVICE` | none | Device class whose assumed watts to use: `apple-silicon-cpu` (30), `apple-silicon-gpu` (40), `apple-silicon-idle` (8), `x86-cpu` (65) or `cuda-gpu` (350). Without it: `device` from the configuration file, else `apple-silicon-cpu` on a Mac with Apple silicon and `x86-cpu` on anything else |
| `--watts WATTS` | none | Average watts to assume instead of the device class's; the entry's `device` is then the `--device` given, or `override` |
| `--rate RATE` | none | Electricity price in USD per kWh. Without it: `SCROLLS_ELECTRICITY_USD_PER_KWH`, then `electricity_usd_per_kwh` in the configuration file; with none of the three the command fails |
| `cmd` | none | The command to run, after `--`. A leading `--` is dropped and the rest is passed as an argument list (no shell). Wrapper options must come before `--` |

### `python -m kit run backfill`

```
usage: python -m kit run backfill [-h] --file FILE [--rate RATE] slug
```

| Option | Default | Meaning |
| --- | --- | --- |
| `slug` | required | The experiment to charge, an existing `ROOT/SLUG/run.json` |
| `--file FILE` | required | A JSON list of logged runs (format under Inputs), such as `scripts/backfill/2026-10-07-local-runs.json` |
| `--rate RATE` | none | Electricity price in USD per kWh, resolved as for `run local` |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `SCROLLS_LOCAL_CONFIG` | unset: the first of `~/.config/scrolls/local.json` and `./scrolls.local.json` that exists is read, and neither is required | Path of the local configuration file to read instead. When set, the file must exist and hold a JSON object |
| `SCROLLS_ELECTRICITY_USD_PER_KWH` | unset | Electricity price in USD per kWh, used when `--rate` is not given; it wins over the configuration file. An empty value counts as unset |

## Python API

```python
from kit import localcost
code, item = localcost.run("SLUG", ["python3", "-c", "print(1)"], rate=0.30)
hours, usd = localcost.backfill("SLUG", [{"what": "a past run", "wall_s": 600}], rate=0.30)
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `CostError()` | An exception | Nothing | Raised for every input, rate, device or configuration problem; the command prints its message and exits 2 |
| `config_paths()` | list of `Path`: `[SCROLLS_LOCAL_CONFIG]` when set, else `[~/.config/scrolls/local.json, scrolls.local.json]` | Nothing | The configuration files `load_config` looks at, in order |
| `load_config()` | dict: the first configuration file that exists, or `{}` | `CostError` for a file that cannot be read or parsed, JSON that is not an object, or a `SCROLLS_LOCAL_CONFIG` that does not exist | Keys it uses: `electricity_usd_per_kwh`, `device`, `device_watts` |
| `resolve_rate(rate=None, config=None)` | float, USD per kWh | `CostError` when no rate is set or it is not a finite nonnegative number | Order: `rate`, then `SCROLLS_ELECTRICITY_USD_PER_KWH`, then the configuration's `electricity_usd_per_kwh` (read with `load_config` when `config` is None) |
| `default_device()` | `"apple-silicon-cpu"` on macOS arm64, else `"x86-cpu"` | Nothing | Also `x86-cpu` on Linux arm64 |
| `resolve_watts(device=None, watts=None, config=None)` | `(watts, device)` | `CostError` for an empty or non-string device, an unknown device, `device_watts` that is not an object, or watts that are not finite and nonnegative | `watts` wins, labelled with `device` or `"override"`. Otherwise `device`, then the configuration's `device`, then `default_device()`, looked up in `DEVICE_WATTS` updated with the configuration's `device_watts` |
| `estimate(wall_s, watts, rate)` | `(kwh, usd)`, each rounded to 6 decimals | `CostError` for any value that is not finite and nonnegative | `kwh = watts * wall_s / 3600 / 1000`; `usd = kwh * rate` |
| `entry(started, ended, wall_s, cpu_s, device, watts, rate, note=None, command=None, exit_code=None)` | dict: the `local` entry under Outputs, without `command_argv`, `signal`, `raw_returncode` and `launch_error` | `CostError` as for `estimate`, and for negative `cpu_s` | `command`, `exit_code` and `note` are included only when given |
| `append(slug, item, root=ledger.DEFAULT_ROOT)` | dict: the whole updated ledger record | `LedgerError` (from `kit.ledger`) for a bad slug or no experiment; `OSError` when the write fails, with the record unchanged | Appends one cost entry under the lock and replaces `run.json` atomically |
| `run(slug, command, root=ledger.DEFAULT_ROOT, device=None, watts=None, rate=None)` | `(code, item)`: the shell-compatible exit code and the `local` entry | `CostError` for an empty or non-list command and every rate, watts and configuration problem; `LedgerError` for a bad slug or no experiment. All of these come before the child starts | Run a child, record its cost, and return its shell-compatible exit code and entry. A child that cannot be launched is recorded, not raised. When the ledger write fails after the child has run, the error is not raised: the entry comes back with `ledger_error` set to its message and the child's code is kept |
| `backfill(slug, items, root=ledger.DEFAULT_ROOT, rate=None)` | `(hours, usd)`: the batch's total hours (4 decimals) and estimated USD (6 decimals) | `CostError` when `items` is not a list, an item lacks a nonempty `what` or `wall_s`, or any value is invalid; `LedgerError` as for `run` | Validate the whole batch before committing any estimated-from-logs entries. An empty list writes nothing |

## Inputs

**Local configuration file** (JSON object, optional, never in git): `~/.config/scrolls/local.json`, or `scrolls.local.json` in the current folder (keep it gitignored), or the file `SCROLLS_LOCAL_CONFIG` names.

| Key | Type | Meaning |
| --- | --- | --- |
| `electricity_usd_per_kwh` | number | Electricity price, USD per kWh |
| `device` | str | Default device class for this machine |
| `device_watts` | object, name to number | Watts per device class; overrides `DEVICE_WATTS` and may add new class names, usable from the file's `device` or a backfill item (the command line's `--device` accepts only the five built-in names) |

**Backfill file** (`--file`): a JSON list of objects.

| Key | Needed | Meaning |
| --- | --- | --- |
| `what` | yes | Nonempty description; stored as `WHAT (estimated from logs)` |
| `wall_s` | yes | Logged duration in seconds, finite and nonnegative |
| `device` | no | Device class, resolved as for `--device` (default: the configuration's, else the platform's) |
| `watts` | no | Assumed watts, overriding the device class |
| `started_utc` | no | Start time, stored as given and not checked |

`scripts/backfill/2026-10-07-local-runs.json` holds seven such items for Mac runs of 7 October 2026, with durations taken from their logs; `tests/test_localcost.py` checks that each has a known device and a positive `wall_s`.

## Outputs

`run local` prints the child's output as it comes, then one line on stderr:

```
SLUG: WALL s wall, CPU s CPU, KWH kWh, $USD (exit CODE)
```

where `CPU` reads `unavailable` when the platform has no resource counter. `run backfill` prints `SLUG: backfilled N entries, H h, $USD (estimated from logs)` on stdout.

Each run, and each backfill item, appends one object to `costs` in `ROOT/SLUG/run.json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `at` | str | When the entry was written, UTC ISO 8601 |
| `usd` | float | Estimated cost in USD, 6 decimals; `python -m kit run list` sums these and rounds to cents |
| `what` | str | `local run, exit CODE`, or `WHAT (estimated from logs)` |
| `local.kind` | str | Always `local` |
| `local.started_utc`, `local.ended_utc` | str or null | Start and end, UTC ISO 8601 to the second; null in backfilled entries (`started_utc` holds the item's value, if any) |
| `local.wall_s` | float | Wall-clock seconds, 3 decimals (monotonic clock) |
| `local.cpu_s` | float or null | User plus system CPU seconds of the child and its waited-for descendants, 3 decimals; null without a resource counter and in backfilled entries |
| `local.device` | str | Device class, or `override` with `--watts` alone |
| `local.watts` | float | Assumed average watts |
| `local.kwh` | float | Estimated energy, kWh, 6 decimals |
| `local.rate_usd_per_kwh` | float | Rate used |
| `local.usd_exact` | float | Estimated cost, USD, 6 decimals (same as `usd`) |
| `local.command` | str | The command line, shell-quoted (`run local` only) |
| `local.command_argv` | list of str | The command as an argument list (`run local` only) |
| `local.exit_code` | int | The shell-compatible exit code (`run local` only) |
| `local.note` | str | Same as `what` |
| `local.signal`, `local.raw_returncode` | int | Only when the child was killed by a signal: the signal number and the negative return code |
| `local.launch_error` | str | Only when the child could not be started |
| `local.estimated_from_logs` | bool | `true` in backfilled entries |

| Exit code | Meaning |
| --- | --- |
| `0` | `run local`: the child exited 0 and its entry was written. `run backfill`: every item was written |
| `2` | An error before the child started, a failed `run backfill` write, or a failed `run local` ledger write after a child that exited 0, with the message on stderr (see Failure modes); also a usage error. A child that itself exits 2 looks the same: read the summary line |
| child's code | `run local` passes the child's exit code through and records it; a nonzero code is kept even when the ledger write fails |
| `128 + N` | `run local`: the child was killed by signal N (for example 143 for SIGTERM) |
| `126`, `127` | `run local`: the child could not be started (127 when the program does not exist, 126 for any other launch error); the attempt is still recorded |
| `130` | `run local`: the wrapper was interrupted with Ctrl-C while the child ran; the entry is still written |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, or an unknown `--device` | Check the command against Commands and options |
| `no electricity rate: set SCROLLS_ELECTRICITY_USD_PER_KWH or electricity_usd_per_kwh in ~/.config/scrolls/local.json` | No `--rate`, no environment variable and no rate in the configuration file | Set one of the three; the run did not start |
| `electricity rate must be a finite nonnegative number` (or `watts`, `wall seconds`, `CPU seconds`, `estimated energy`, `estimated cost`, `total wall seconds`, `total cost` in place of `electricity rate`) | A value that is negative, infinite, NaN, a boolean or not a number, from an option, the environment, the configuration file or a backfill item | Fix the value |
| `local configuration does not exist: PATH` | `SCROLLS_LOCAL_CONFIG` names a missing file | Fix or unset the variable |
| `cannot read local configuration PATH: ...` | The configuration file is unreadable or not valid JSON | Fix the file |
| `local configuration PATH must be a JSON object` | The file holds a list, a string or null | Write a JSON object |
| `device_watts must be a JSON object` | `device_watts` in the configuration file is not an object | Write it as `{"NAME": WATTS}` |
| `device must be a nonempty string` | An empty or non-string device in the configuration file or a backfill item | Fix the device name |
| `unknown device 'NAME'; use a supported device or --watts` | The device is not one of the five classes or a `device_watts` key | Use a known class, add it to `device_watts`, or give watts |
| `no command given after --` | `run local SLUG` with nothing after it | Put the command after `--` |
| `command must be an argument list` | `localcost.run` called from Python with a string or with non-string items | Pass a list of strings |
| `backfill must be a JSON list` | The backfill file holds an object or another type | Wrap the items in a list |
| `each backfill item needs nonempty what and wall_s` | An item that is not an object, or lacks `what` or `wall_s` | Fix that item; nothing was written |
| `cannot read backfill FILE: ...` | The backfill file is missing or not valid JSON | Fix the path or the JSON |
| `no experiment at ROOT/SLUG/run.json` | The experiment was never started, or `--root` points elsewhere | Run `python -m kit run init SLUG ...` first, or fix `--root` |
| `bad slug: 'SLUG'` | An empty slug, one with `/`, or one starting with `.` | Use a plain name |
| `FILE is a JSON object with key, row and optionally generic` | Comes from `run modal-row`, which shares `cmd_run`; not from these actions | See [modal-row](modal-row.md) |
| `SLUG: the command exited CODE, but its cost was not written to the ledger: MESSAGE. Record it with kit run backfill, using the wall time above.`, after the summary line; exit code CODE, or 2 when CODE is 0 | `run local`: the child has run, but its entry could not be written (such as `[Errno 13] Permission denied: ...` or a full disk); `run.json` is left as it was | Fix the folder's permissions or free space, then record the run with `python -m kit run backfill` using the wall time in the summary line, if it should count |
| An `OSError` message such as `[Errno 13] Permission denied: ...`, exit code 2 | `run backfill`: the ledger could not be written; `run.json` is left as it was | Fix the folder's permissions, then run the backfill again |

## How it works

1. **Settle the assumptions first.** Read the configuration file (`load_config`), the rate (`resolve_rate`) and the watts (`resolve_watts`), and load the experiment record, all before anything runs.
2. **Run the child.** `subprocess.call` with the argument list (no shell), timing it with `time.monotonic()` and reading `resource.getrusage(RUSAGE_CHILDREN)` before and after for user plus system CPU time. A negative return code (killed by signal N) becomes `128 + N`; Ctrl-C becomes 130; a missing program 127; another launch error 126.
3. **Estimate.** `kwh = watts * wall_s / 3600 / 1000` and `usd = kwh * rate`, each rounded to 6 decimals, so sub-cent costs survive until the ledger's cent-rounded total.
4. **Append.** Take an advisory `fcntl` lock on `run.local-cost.lock` beside `run.json` (Mac and Linux only), reload the record, append the entries, write a temporary file in the same folder and `os.replace` it over `run.json`. Other ledger commands do not take this lock.
5. **Backfill.** Build and check every entry first, then append them all in one locked write.

Assumed watts (`DEVICE_WATTS`, whole machine while busy, illustrative and not measured): `apple-silicon-cpu` 30, `apple-silicon-gpu` 40, `apple-silicon-idle` 8, `x86-cpu` 65, `cuda-gpu` 350.

## Cost and time

Not measured. The wrapper adds a configuration read, two resource-counter reads and one JSON write to the child's time. It runs where the child runs; the Modal rule (hard rule 11) decides where the child should run, and a job that needs a GPU or more than about an hour of CPU belongs on Modal, not under this wrapper.

## For agents

- **Command:** `python -m kit run local SLUG -- COMMAND ARGS` (add `--device apple-silicon-gpu` for MPS work); `python -m kit run backfill SLUG --file FILE` for past runs. There is no JSON mode: read the record.
- **Parse:** the last entry of `costs` in `experiments/SLUG/run.json`: `local.wall_s`, `local.cpu_s`, `local.exit_code`, `local.kwh`, `local.usd_exact`; or the stderr line `SLUG: ... (exit CODE)`.
- **Rerun:** Not idempotent. Each `run local` runs the child again and appends another entry; each `run backfill` appends the whole list again.
- **Success:** The exit code is the child's (0 for a clean run) and a new entry exists in `costs`. Exit code 2 with no new entry means the wrapper refused before starting, unless stderr has the `its cost was not written to the ledger` line: then the child ran and its entry was lost.
- **Not a pass:** A `kwh` or `usd` figure presented as measured; a backfilled entry (`estimated_from_logs`) mixed with measured ones; an exit code 2 read as the child's without checking `costs`.
- **Go-ahead:** Nothing for the wrapper. Moving a long or GPU job to Modal needs the user's budget decision first (the go-ahead rule, hard rule 8).
- **Never:** Commit the local configuration file or your electricity rate; backfill a run the wrapper already logged; wrap a long GPU or CPU job on a laptop instead of writing a Modal run spec.

## Tests

```bash
python -m unittest tests.test_localcost tests.test_localcost_regressions -v
```

They cover the estimate arithmetic, the order of rate sources, refusing before launch without a rate or with a NaN, infinite, negative, boolean or non-numeric rate or watts, configuration files that are a list, null or broken, a missing `SCROLLS_LOCAL_CONFIG` file and bad `device_watts`, the command line passing the child's arguments and exit code through, signals (143 for SIGTERM), a missing program (127), a missing resource counter, sub-cent sums, backfill marking and all-or-nothing validation, four concurrent writers keeping all 40 entries, a failed atomic replace leaving the ledger unchanged, a failed ledger write in `run local` keeping the child's exit code (2 for a child that exited 0) and naming the error, and that `scripts/backfill/2026-10-07-local-runs.json` is valid. The 2026-10-16 run took 0.29 s for these and the compute and modal-row tests together (25 tests). They do not measure real power.

## History

- 2026-10-17: when `run local` cannot write its ledger entry after the child has run, it keeps the child's nonzero exit code (2 when the child exited 0) and prints what was lost and how to backfill it; before, the write error replaced the child's exit code with 2 (`0a84855`).
- 2026-10-07: review fixes: values must be finite and nonnegative, the backfill is validated whole, writes are locked and atomic, signals and launch failures are recorded, and child arguments survive the Python 3.10 parser (`7492129`).
- 2026-10-07: first version, with `run local`, `run backfill` and the 7 October backfill list (`7878089`).

## Related

- [run-ledger](run-ledger.md): `python -m kit run init`, `run cost` and `run list`, the ledger these entries go into.
- [compute](compute.md): machine time per run from provenance records.
- [modal-row](modal-row.md): the Modal ledger, for rented GPU and CPU time.
- [cloudcost](cloudcost.md): cloud prices, for deciding when a job should leave the laptop.
- [compute.md, local runs](../compute.md#local-runs-time-and-electricity): the guide to wrapping local runs.
