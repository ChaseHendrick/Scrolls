# compute: tabulate machine time per run from provenance records

`python -m kit compute` finds the `provenance*.json` records that runs leave behind and prints one row per run with its operator, machine, start time, wall-clock hours and digest, plus an optional energy estimate from an assumed power draw.

| Field | Value |
| --- | --- |
| Id | `compute` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Compute and cost |
| Run | `python -m kit compute`, `from kit import compute` |
| Code | `kit/compute.py`, `kit/cli.py` (`cmd_compute`) |
| Tests | `tests/test_compute.py` |
| Needs | Python 3.10 or newer (`requires-python` in `pyproject.toml`), standard library only. Input: provenance records written by `python -m kit provenance write` |
| Runs on | Any CPU. Time not measured; two synthetic records returned at once in a cloud container on 2026-10-16 |
| Network | None |
| Writes | Nothing (prints only) |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07 (`da58d07`) |
| Guide | [compute.md](../compute.md) (what compute the work needs and what it costs) |
| Checked | 2026-10-16 against commit `63ee638` |

## What it does

Every result here should show what machine time it cost. Runs made with the Mac scripts leave a provenance record: a JSON file, written by `python -m kit provenance write`, that holds the run's name, the operator (from git), the machine, the UTC start and finish times, and a SHA-256 digest over the record (the provenance digest). `scripts/mac-w045.sh`, for example, writes `results/provenance*.json` in its output folder.

`kit compute` collects those records from files or folders, works out each run's wall-clock hours from its start and finish times, and prints them as a Markdown table sorted by start time, with a total. Given `--watts`, it multiplies hours by that power draw for a watt-hour column. The idea comes from the compute ledger of Chase's GENChase repository ([COMPUTE.md](https://github.com/ChaseHendrick/GENChase/blob/main/COMPUTE.md)), which is generated from job records so that each result's cost is visible.

It measures nothing itself. The hours are copied from the records, and the energy figure is an estimate, because laptops do not report their power draw; the table says so in its last line. It does not price anything in dollars and does not write a ledger: for a logged electricity cost per run use [run-local](run-local.md), and for Modal spend use [modal-row](modal-row.md).

## When to use it

- Summing the machine time behind a set of results, such as every Mac run in a work folder, for a log or a compute note.
- Checking which machine and operator produced a run before quoting its numbers.

Do not use it:

- To log the time and electricity cost of a run as it happens: wrap the run with `python -m kit run local` ([run-local](run-local.md)).
- To record Modal or other rented compute: use `python -m kit run modal-row` ([modal-row](modal-row.md)) and the price tables in [`cloudcost`](cloudcost.md).
- To check that a record was not edited: use `python -m kit provenance check` ([provenance](provenance.md)).

## Quick start

```bash
python -m kit compute WORK --watts 30
python -m kit compute WORK --json
```

- `WORK`: a folder searched recursively for `provenance*.json`, or one or more record files. Several paths may be given.
- `30`: an assumed average power draw in watts; leave `--watts` out for hours only.

On two synthetic records (a 30 minute and a 12 minute run, one of them without a `chip` field) it printed:

```
| Run | Operator | Machine | Started (UTC) | Hours | Digest | Wh at 30 W |
| --- | --- | --- | --- | ---: | --- | ---: |
| w045-cpu | Chase Hendrick | Apple M1 Pro | 2026-10-07T08:00:00Z | 0.500 | `3f1a9c0d7e5b2a4c` | 15.0 |
| w045-mps | Chase Hendrick | arm64 | 2026-10-07T09:00:00Z | 0.200 | `9b8a7c6d5e4f3021` | 6.0 |

2 runs, 0.70 hours wall clock, about 21 Wh at 30 W (an estimate, not a measurement).
```

It worked when the exit code is 0 and the count in the last line matches the runs you expected. A third file in the folder, `provenance_bad.json` without `run` and `digest`, was skipped without a message.

## Checks and controls

- **The records themselves.** The table is only as good as the records. Run `python -m kit provenance check FILE` on any record you quote: it recomputes the digest and prints `FILE: ok (digest ...)` with exit code 0, or one `problem: ...` line per mismatch with exit code 1. The 16-character digest prefix in the table ties each row to its record.
- **Skipped files.** A path that does not exist, a file that is not JSON, or JSON without both `run` and `digest` is skipped silently. Compare the run count in the last line with the runs you expected; the command fails (exit code 2) only when nothing at all is found.
- **Energy.** The Wh column is hours times the `--watts` you gave, labelled "an estimate, not a measurement". Do not report it as measured energy.

Claim label: None. The hours are copied from provenance records, and the Wh figure is an estimate from an assumed power draw.

## Commands and options

### `python -m kit compute`

```
usage: python -m kit compute [-h] [--watts WATTS] [--json] paths [paths ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `paths` | required | One or more provenance JSON files, or folders searched recursively for `provenance*.json`. A file named directly is read whatever its name |
| `--watts WATTS` | none | Assumed average power draw in watts. Adds a `Wh at WATTS W` column (and `wh_estimate` in JSON) and an energy total |
| `--json` | off | Print the rows as a JSON list (fields under Outputs) instead of the Markdown table |

## Python API

```python
from kit import compute
rows = compute.rows(compute.collect(["WORK"]), watts=30)
print(compute.table(rows, watts=30))
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `collect(paths)` | list of record dicts, each with an added `_file` key (the path it was read from) | Nothing of its own; unreadable files and non-records are skipped | Provenance records from files or directories (searched for provenance*.json). A record is a JSON object with both `run` and `digest`. Folders are searched in sorted path order |
| `rows(records, watts=None)` | list of row dicts (fields under Outputs), sorted by `started_utc` (missing start first) | `ValueError` when `started_utc` or `finished_utc` is not in the form `YYYY-MM-DDTHH:MM:SSZ`; `KeyError` when a record lacks `run` or `digest` | `hours` is rounded to 3 decimals, or `None` without both times. `wh_estimate` is added only when `watts` is given and hours are known |
| `table(rows_, watts=None)` | str: the Markdown table and its total line | Nothing of its own | The text the command prints. Rows without hours count 0 toward the total |

## Inputs

A provenance record is a JSON object. `kit compute` reads these fields; others are ignored:

| Field | Needed | Meaning |
| --- | --- | --- |
| `run` | yes | Run name |
| `digest` | yes | SHA-256 of the record (a hex string); the first 16 characters are shown |
| `operator.name` | no | Who ran it |
| `machine.chip`, else `machine.machine` | no | The chip name (macOS) or the platform's machine type |
| `started_utc`, `finished_utc` | no | UTC times in exactly the form `2026-10-07T08:00:00Z`; without both, hours are blank |

`python -m kit provenance write` produces this form. There is no size limit beyond reading each file into memory.

## Outputs

By default a Markdown table with the columns Run, Operator, Machine, Started (UTC), Hours (3 decimals) and Digest (16 characters, in code), plus `Wh at WATTS W` (1 decimal) with `--watts`, then a line `N runs, H hours wall clock.` that, with a nonzero `--watts`, adds `about E Wh at WATTS W (an estimate, not a measurement)`.

With `--json`, a list of objects:

| Field | Type | Meaning |
| --- | --- | --- |
| `run` | str | Run name from the record |
| `operator` | str or null | `operator.name` |
| `machine` | str or null | `machine.chip`, else `machine.machine` |
| `started_utc` | str or null | Start time as stored |
| `hours` | float or null | Finish minus start in hours, 3 decimals |
| `digest` | str | First 16 characters of the record's digest |
| `wh_estimate` | float | Only with `--watts` and known hours: hours times watts, 1 decimal, in watt-hours |

| Exit code | Meaning |
| --- | --- |
| `0` | At least one record found and printed |
| `1` | An uncaught error with a traceback, such as a timestamp in another format (`ValueError`) |
| `2` | No records found under the paths, or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `no provenance records found` on stderr, exit code 2 | No path held a readable JSON object with both `run` and `digest`; a mistyped path or folder also ends here | Check the paths; folders are searched only for files named `provenance*.json` |
| `ValueError: time data '...' does not match format '%Y-%m-%dT%H:%M:%SZ'` and a traceback, exit code 1 | A record's `started_utc` or `finished_utc` has another form, such as `+00:00` or fractional seconds. One bad record stops the whole table | Fix the record's times to `YYYY-MM-DDTHH:MM:SSZ`, or leave that file out of the paths |
| Fewer rows than expected, exit code 0 | Files that are missing, not JSON, or lack `run` or `digest` are skipped without a message | Check each expected file; run `python -m kit provenance check FILE` on it |
| A blank Hours cell | The record has no `finished_utc` (or no `started_utc`) | The run did not finish writing its record; it counts 0 toward the total |

## How it works

1. `collect` walks each path: a folder with `rglob("provenance*.json")` in sorted order, anything else as one file. Each file is parsed as JSON; files that fail to read or parse, and JSON that is not an object with `run` and `digest`, are dropped.
2. `rows` parses `started_utc` and `finished_utc` with `datetime.strptime(..., "%Y-%m-%dT%H:%M:%SZ")`, takes the difference in hours, and rounds it to 3 decimals. With `watts`, `wh_estimate` is hours times watts, rounded to 1 decimal. Rows are sorted by the start string.
3. `table` writes the Markdown table and sums the hours, treating blank hours as 0. The energy total in the last line is the summed hours times watts, rounded to a whole Wh, and is printed only when `watts` is nonzero.

There are no constants; the power draw is whatever the caller gives. Finish times before start times are not checked and would give negative hours.

## Cost and time

Not measured. It reads small JSON files and does arithmetic; it runs anywhere, with no GPU and no Modal.

## For agents

- **Command:** `python -m kit compute WORK --json`; add `--watts W` for an energy estimate.
- **Parse:** the JSON list: `run`, `hours` (wall clock), `machine`, `operator`, `digest` (16-character prefix) and, with `--watts`, `wh_estimate` (watt-hours, an estimate).
- **Rerun:** Safe; it only reads.
- **Success:** Exit code 0 and as many rows as the runs you expected.
- **Not a pass:** A missing run in the list (files are skipped silently); a `wh_estimate` reported as measured energy; hours from a record that `python -m kit provenance check` rejects.
- **Go-ahead:** Nothing.
- **Never:** Present the Wh column as a measurement, or copy rows from records of private target-scroll runs into public files.

## Tests

```bash
python -m unittest tests.test_compute -v
```

They cover collecting records from nested folders (skipping a JSON file without `run` and `digest`), hours and the Wh estimate, the table's total line and its "an estimate, not a measurement" wording, matching header and rule widths, and the command line's exit codes 0 and 2. They do not cover malformed timestamps or records without times.

## History

- 2026-10-07: first version, modelled on GENChase's compute ledger (`da58d07`).

## Related

- [provenance](provenance.md): writes and checks the records this command reads.
- [run-local](run-local.md): logs each local run's wall time, CPU time and electricity cost in the experiment ledger.
- [modal-row](modal-row.md): records Modal spend in the Modal ledger.
- [cloudcost](cloudcost.md): Modal and other cloud prices for estimates.
- [compute.md](../compute.md): the guide to what the work needs and what it costs.
