# prizes: list the open Vesuvius Challenge prizes from a dated snapshot

`python -m kit prizes` prints each open Vesuvius Challenge prize with its money, deadline, days left and eligible scrolls, from a dated copy of scrollprize.org/prizes kept in `kit/data/`; `--json` prints the copy itself. The live page wins where they differ.

| Field | Value |
| --- | --- |
| Id | `prizes` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Planning and prizes |
| Run | `python -m kit prizes`, `from kit import prizes` |
| Code | `kit/prizes.py`, `kit/data/prizes-2026-10-11.json`, `kit/data/prizes-2026-10-06.json`, `kit/cli.py` (`cmd_prizes`) |
| Tests | `tests/test_kit.py`, `tests/test_packaging.py`, `tests/test_cli_parser_cache.py` |
| Needs | Python 3.10 or newer, standard library only (json, datetime, pathlib) |
| Runs on | Any machine. 0.31 to 0.56 s per call for the table and 0.45 to 0.60 s for `--json`, almost all of it Python start-up and importing `kit.cli` (5 runs each, measured 2026-10-16, 4-core Xeon cloud container) |
| Network | None. It never contacts scrollprize.org: the snapshot is a file in the repository |
| Writes | Nothing (prints only) |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-06 (`2daee8e`); the 11 October snapshot since 2026-10-11 ([PR #40](https://github.com/ChaseHendrick/Scrolls/pull/40)). Also inside the AutoPipeline release copy at `faada83`, and as `scrolls-workbench prizes` in the installable package since 2026-10-14 (`2582ab7`) |
| Guide | [prizes.md](../prizes.md) (the prize terms in prose, from the same snapshot) |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

The Vesuvius Challenge publishes its open prizes, their money, deadlines and eligible scrolls on [scrollprize.org/prizes](https://scrollprize.org/prizes), built from villa's `prizeEligibility.json`. They change: PHerc1447 left First Letters on 24 September 2026 when the team found text in it ([villa #1887](https://github.com/ScrollPrize/villa/pull/1887)), and PHerc0343 left after its First Letters prize was awarded on 8 October 2026 ([official post](https://scrollprize.substack.com/p/50k-first-letters-prize-awarded-for)). This repository keeps a dated copy of that page as JSON, the prize snapshot: `kit/data/prizes-2026-10-11.json`, checked on 11 October 2026 against villa commit `34d4b260`.

`kit prizes` reads the snapshot and prints one block per prize: title, amount, deadline date, days left from today, the goal in one sentence and, for the Grand Prize and First Letters, the eligible scrolls. It ends with the snapshot's own note. `--json` prints the whole snapshot file instead, which also holds each eligible scroll's volume id, its zarr name in the open-data bucket and its voxel size, and the First Letters awards.

Other tools read the same file through this module. `kit plan` refuses a scroll that is not First Letters eligible in it and takes the volume, zarr name and voxel size from it ([plan](plan.md)). `kit run init` stores the scroll's First Letters volume and the snapshot date in the experiment record ([run-ledger](run-ledger.md)). The every-scan catalog behind `kit run catalog`, `run all` and `run watch` names which prize each bucket volume belongs to from it, and lets the live page win ([batch](batch.md)).

It does not fetch the live page, so it knows nothing that changed after the snapshot's `checked` date. "Days left" counts calendar days from this machine's local date to the deadline's date and ignores the time of day (the deadlines are 23:59 Pacific). Eligibility is a dated fact about the prize rules, not a judgment about whether a scroll holds text, and the snapshot is not the full terms: what a submission must contain is in [prizes.md](../prizes.md) and on the live page.

Two snapshots are kept. The current one is `prizes.SNAPSHOT`, 11 October 2026: 13 Grand Prize volumes, 21 First Letters volumes, First Letters at $50,000 a scroll for a maximum of 9 more scrolls ($450,000). The previous one, 6 October 2026, had 22 First Letters volumes including PHerc0343 and a maximum of 10 ($500,000); the command never prints it, but `prizes.load(path)` reads it.

## When to use it

- At the start of a session, before choosing a target: the [scroll-session](scroll-session.md) skill runs it first.
- To check whether a scroll is still First Letters or Grand Prize eligible, which decides whether results on it must stay private (the no-findings rule in [`AGENTS.md`](../../AGENTS.md)).
- In code, to get a scroll's eligible volume id, zarr name and voxel size (`eligible_entry`), or to normalize a scroll name (`normalize_scroll`).
- To see how many days are left to the next Progress Prize deadline.

Do not use it:

- As the last word before submitting, spending money or telling Chase a scroll is eligible: read the live page at https://scrollprize.org/prizes. The snapshot can be out of date.
- For the full prize terms (what a submission must contain, disclosure rules): read [prizes.md](../prizes.md) and the live page.
- To list every volume in the open-data bucket with its prize status from the live page: use `kit run catalog` ([batch](batch.md)).
- To print the commands of a run: use [plan](plan.md).

## Quick start

```bash
python -m kit prizes
python -m kit prizes --json > prizes.json
```

Run on 2026-10-16 with `--today 2026-10-16` (the same as no option on that day), it printed, shortened here:

```
Open prizes, snapshot checked 2026-10-11 (https://scrollprize.org/prizes)

2027 Grand Prize             $1,000,000  2027-06-25  252 days left
    Fully unroll one eligible sealed scroll and make it readable: 100% of the recto surface meshed, at least 70% of each counted column's preserved characters legible.
    Eligible (13): PHerc0125, PHerc0191, PHerc0211, PHerc0257, PHerc0268, PHerc0358, PHerc0800, PHerc0813, PHerc0826, PHerc1203, PHerc1218, PHerc1447, PHerc1545

First Letters                  $450,000  2027-06-25  252 days left
    First team to show 10 legible letters within a single 4 cm2 area of an eligible scroll.
    Eligible (21): PHerc0125, PHerc0175A, PHerc0175B, ... PHerc1218, PHerc1545

PHerc. Paris 4 title            $50,000  2027-06-25  252 days left
    ...
Progress Prizes             $590,000/yr  2026-10-31  15 days left
    ...
Snapshot of the prizes page body on 2026-10-11, not the homepage banner. The live page wins if it disagrees. ...
```

It worked when the exit code is 0 and the first line names the snapshot date. If that date is more than about a month old, or any line says `deadline passed`, re-check the live page and add a new snapshot (How it works).

## Checks and controls

- **The live page is the control.** The snapshot is right only while it matches https://scrollprize.org/prizes. On 2026-10-16 this page's author fetched the live page: it still said First Letters prizes "will be awarded for a maximum of 9 more scrolls", up to $450,000, with the deadline June 25th, 2027 (11:59pm Pacific), and the 14-digit volume ids it named were the same 22 as the snapshot's Grand Prize and First Letters lists together. The split of those ids between the two prizes was not checked that day.
- **The tests pin the snapshot's arithmetic and counts** (`PrizeSnapshotTest`): the Grand Prize tiers add up to $1,000,000, First Letters per-scroll money times the maximum equals its total, there are 13 Grand Prize and 21 First Letters volumes, PHerc0343 is out of First Letters and PHerc1447 is only in the Grand Prize, every eligible zarr name starts with its volume id, and every voxel size is 8.64 or 9.362 um. A snapshot edited without updating the tests fails them.
- **A stale deadline shows itself.** After a deadline, its line reads `deadline passed N days ago; re-check` instead of a count (for example `python -m kit prizes --today 2026-11-02` for the Progress Prizes line).

Claim label: Sourced fact, for the amounts, deadlines and eligible volumes, copied from scrollprize.org/prizes and villa's `prizeEligibility.json` at commit `34d4b260` on 2026-10-11; days left is arithmetic on the machine's date.

## Commands and options

### `python -m kit prizes`

```
usage: python -m kit prizes [-h] [--json] [--today TODAY]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | Print the whole snapshot file as JSON (indented 2 spaces) instead of the table. `--today` is ignored with it |
| `--today TODAY` | none (this machine's local date, `date.today()`) | Count days left from this date instead of today, written `YYYY-MM-DD` (read with `date.fromisoformat`). A malformed date stops with a `ValueError` traceback and exit code 1 |

## Python API

```python
from kit import prizes
snap = prizes.load()
entry = prizes.eligible_entry(snap, "PHerc. 826")   # {'scroll': 'PHerc0826', 'volume': '20250821151701', ...}
print(prizes.format_table(snap))
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `load(path=SNAPSHOT)` | dict, the parsed snapshot (fields under Outputs) | `FileNotFoundError` for a missing file, `json.JSONDecodeError` for a broken one | `SNAPSHOT` is `kit/data/prizes-2026-10-11.json`; pass `prizes.DATA_DIR / "prizes-2026-10-06.json"` for the previous one |
| `deadline_date(prize)` | `datetime.date` | `KeyError` without `deadline`, `ValueError` for a malformed one | The date part of the ISO deadline, in the deadline's own time zone (Pacific) |
| `days_left(prize, today=None)` | int, negative after the deadline | As `deadline_date` | `today` defaults to `date.today()`, the machine's local date. The deadline day itself gives 0 |
| `find(snapshot, prize_id)` | dict, the prize | `KeyError(prize_id)` for an unknown id | Ids in the current snapshot: `grand-prize-2027`, `first-letters-2027`, `first-title`, `progress-prizes` |
| `eligible_entry(snapshot, scroll, prize_id='first-letters-2027')` | dict `{"scroll", "volume", "zarr", "voxel_um"}`, or `None` when the scroll is not eligible | `KeyError` for an unknown `prize_id` | Compares names through `normalize_scroll`. The `first-title` entry has only `scroll` and `volume` (`"any"`) |
| `eligible_volume(snapshot, scroll, prize_id='first-letters-2027')` | str, the 14-digit volume id, or `None` | `KeyError` for an unknown `prize_id` | What `kit run init` stores as `first_letters_volume` |
| `normalize_scroll(name)` | str | Nothing | Upper case, spaces and dots removed, the digits after `PHERC` zero-padded to 4: `PHerc. 826`, `pherc0826` and `PHERC 826` all give `PHERC0826`; `PHerc. 175A` gives `PHERC0175A` |
| `amount(prize)` | str such as `$1,000,000` or `$590,000/yr`; `?` when neither `total_usd` nor `total_usd_per_year` is there | Nothing | `/yr` marks `total_usd_per_year` |
| `format_table(snapshot, today=None)` | str, the table the command prints | As `days_left` | Lists eligible scrolls only when the list is not empty and its first volume is not `any` |

Module constants: `DATA_DIR` (`kit/data`), `SNAPSHOT` (the current snapshot file) and `DATA_BROWSER` (`https://scrollprize.org/data_browser/`, which [plan](plan.md) prints with the scroll name).

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| The snapshot | JSON at `kit/data/prizes-2026-10-11.json` (`prizes.SNAPSHOT`), about 10 KB | Fixed: no option chooses another file. Its fields are listed under Outputs. Installed packages carry it as package data (`kit = ["data/*.json"]` in `pyproject.toml`) |
| `--today` | `YYYY-MM-DD` | Optional; the machine's local date otherwise |

## Outputs

The table goes to stdout: a header line naming the snapshot date and source, then per prize a line of title (24 characters), amount (right-aligned in 14), deadline date and `N days left` or `deadline passed N days ago; re-check`, an indented goal line, an indented `Eligible (N): ...` line for the two scroll prizes, and a blank line; last, the snapshot's `note`.

With `--json`, the snapshot file as it is:

| Field | Type | Meaning |
| --- | --- | --- |
| `checked` | str (date) | The day the snapshot was copied from the live page |
| `source` | str (URL) | `https://scrollprize.org/prizes` |
| `source_repo_file`, `source_prizes_md` | str (URL) | villa's `prizeEligibility.json` and `34_prizes.md` at the commit read (`source_prizes_md` only in the 11 October snapshot) |
| `source_commit` | str | villa commit read (`34d4b260...` for 11 October, `e0bbb8b4...` for 6 October) |
| `note` | str | What the snapshot follows and what changed since the previous one |
| `prizes[].id`, `.title`, `.goal`, `.submit` | str | Prize id (see `find`), title, one-sentence goal, submission address or form URL |
| `prizes[].deadline` | str (ISO 8601 with offset) | Such as `2027-06-25T23:59:00-07:00` |
| `prizes[].deadline_note` | str | Progress Prizes only: the deadline is monthly and this is the next one |
| `prizes[].total_usd` | int (USD) | Total money; for First Letters the money still on offer |
| `prizes[].tiers_usd` | object (USD) | Grand Prize places `1st` to `4th` |
| `prizes[].per_scroll_usd`, `.max_scrolls` | int | First Letters money per scroll, and how many more scrolls can win |
| `prizes[].awarded_count`, `.awarded[]` | int, list | First Letters awards already made: `scroll`, `volume`, `usd`, `date`, `winner`, `sources` (11 October snapshot only) |
| `prizes[].total_usd_per_year`, `.monthly_best_usd`, `.typical_tiers_usd` | int, int, list of int (USD) | Progress Prizes money |
| `prizes[].eligible[]` | list | `scroll`, `volume` (14-digit id, or `any`), `zarr` (the volume's folder name under `SCROLL/volumes/` in the bucket) and `voxel_um` (8.64 or 9.362) |
| `bucket`, `bucket_checked` | str | `s3://vesuvius-challenge-open-data`, and the day its listing resolved the zarr names (2026-10-06) |

| Exit code | Meaning |
| --- | --- |
| `0` | Printed. A line may still say `deadline passed`: check the text |
| `1` | A Python error with a traceback: a malformed `--today`, or a missing or broken snapshot file |
| `2` | A usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `ValueError: Invalid isoformat string: '16-10-2026'` and a traceback, exit code 1 | `--today` not written `YYYY-MM-DD` | Write the date as `2026-10-16` |
| `ValueError: month must be in 1..12` (or `day is out of range for month`) and a traceback, exit code 1 | `--today` is not a real date | Give a real date |
| `deadline passed N days ago; re-check` in a prize's line, exit code 0 | The snapshot is older than that deadline: for the Progress Prizes it names only the next monthly deadline | Read the live page and add a new snapshot (How it works) |
| `FileNotFoundError: ... prizes-2026-10-11.json` and a traceback, exit code 1 | A copy of `kit/` without its `data/` folder | Run from a clone, or reinstall the package, which ships `kit/data/*.json` |
| `KeyError: 'PRIZE_ID'` from `find`, `eligible_entry` or `eligible_volume` | An id not in the snapshot | Use one of the ids under Python API |
| `BrokenPipeError` after `python -m kit prizes --json \| head` | The reader closed the pipe before the JSON ended | Harmless; write to a file instead |

## How it works

1. `cmd_prizes` loads `SNAPSHOT` with `json.load`.
2. With `--json` it prints the loaded object with `json.dumps(indent=2)`, so the output equals the file's content (the packaging test checks `scrolls-workbench prizes --json` against `prizes.load()`).
3. Otherwise `format_table` prints each prize in file order. `amount` writes `total_usd`, or `total_usd_per_year` with `/yr`. `days_left` subtracts dates: the deadline's date in its own time zone minus the given or local date.
4. `eligible_entry` compares scroll names through `normalize_scroll`, so `PHerc. 826`, `pherc 826` and `PHerc0826` match the same entry.

To add a snapshot when the live page changes (the steps in [TESTING.md](../TESTING.md)): copy the page body (not the homepage banner) and villa's `prizeEligibility.json` into a new `kit/data/prizes-YYYY-MM-DD.json` with the same fields, set `checked`, `source_commit` and `note`, point `SNAPSHOT` at it, update the counts in `tests/test_kit.py`, [prizes.md](../prizes.md) and the README in the same commit, and keep the old file. Volume ids that the page adds need their zarr names and voxel sizes from a bucket listing.

## Cost and time

Measured 2026-10-16 in a 4-core Xeon cloud container: 0.31 to 0.56 s for the table and 0.45 to 0.60 s for `--json` (5 runs each), with a peak resident memory of about 24 MB. Nearly all of it is Python start-up and the import of `kit.cli`; the snapshot itself is about 10 KB. It rents nothing and runs anywhere.

## For agents

- **Command:** `python -m kit prizes --json` (machine-readable: the snapshot); `python -m kit prizes` for the table.
- **Parse:** from the JSON, `checked` (snapshot date), and per `prizes[]` entry `id`, `deadline`, `total_usd` or `total_usd_per_year`, and `eligible[].scroll`, `.volume`, `.zarr`, `.voxel_um`. Days left is not in the JSON: compute it from `deadline`, or read the table's `N days left`.
- **Rerun:** Safe; it only reads the snapshot and prints.
- **Success:** Exit code 0 and output that starts with `{` (JSON) or `Open prizes, snapshot checked` (table).
- **Not a pass:** A snapshot whose `checked` date is old, or any `deadline passed` line: confirm on https://scrollprize.org/prizes before telling the user a scroll is eligible or an amount is current. Eligibility does not mean a scroll holds text.
- **Go-ahead:** Nothing for reading. Adding a new snapshot is an ordinary repository change; submitting to any prize needs Chase's yes (the go-ahead rule, hard rule 8).
- **Never:** Publish or describe a possible finding on an eligible scroll (the no-findings rule, hard rule 1); treat the snapshot as newer than its `checked` date.

## Tests

```bash
python -m unittest tests.test_kit.PrizeSnapshotTest tests.test_kit.CliTest -v
python -m unittest tests.test_packaging.ConsoleScriptTest tests.test_cli_parser_cache -v
```

`PrizeSnapshotTest` (7 tests) pins the totals, tiers, deadlines and counts of the 11 October snapshot, the 6 October file's 22 First Letters volumes and maximum of 10, PHerc1447 on the Grand Prize only, a zarr name for every eligible volume, name normalization and the deadline arithmetic. `CliTest` runs `prizes --today 2026-10-06` and expects `262 days left`. The packaging tests check that `scrolls-workbench prizes --json` prints exactly the snapshot and that the snapshots live in `kit/data/`; the parser cache test runs `prizes --json` 20 times in under 5 s. They do not compare the snapshot with the live page, and they do not cover a malformed `--today`.

## History

- 2026-10-14: `scrolls-workbench prizes` in the installable package, which ships the snapshots as package data (`2582ab7`, [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58)).
- 2026-10-11: the 11 October snapshot becomes current: First Letters at $50,000 a scroll for a maximum of 9 more scrolls ($450,000), 21 eligible volumes after the PHerc0343 award, and an `awarded` list; the 6 October file is kept (`f4092cd`, [PR #40](https://github.com/ChaseHendrick/Scrolls/pull/40)).
- 2026-10-06: first version, with the 6 October snapshot: 13 Grand Prize and 22 First Letters volumes, each resolved to its zarr name in the bucket (`2daee8e`).

## Related

- [prizes.md](../prizes.md): the prize terms in prose, written from the same snapshot.
- [plan](plan.md): prints a First Letters run plan for a scroll this snapshot calls eligible.
- [run-ledger](run-ledger.md): `kit run init` records the scroll's First Letters volume and the snapshot date.
- [batch](batch.md): the every-scan catalog, which reads the live page and this snapshot for each bucket volume's prize.
- [scroll-session](scroll-session.md): the session skill that starts with this command.
- [scan-status.md](../scan-status.md): the bucket volumes behind the 6 October snapshot's lists.
