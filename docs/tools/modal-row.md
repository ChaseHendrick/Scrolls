# modal-row: add one Modal job's row to a Modal cost ledger, once

`python -m kit run modal-row` appends one row, from a small JSON file, to a Modal cost ledger CSV such as `docs/compute/modal-ledger.csv`, never twice for the same key, and lets the public ledger take only rows marked generic.

| Field | Value |
| --- | --- |
| Id | `modal-row` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Compute and cost |
| Run | `python -m kit run modal-row`, `from kit import modalledger` |
| Code | `kit/modalledger.py`, `kit/cli.py` (`cmd_run`) |
| Tests | `tests/test_modalledger.py` |
| Needs | Python 3.10 or newer, standard library only. A ledger CSV that already has its header row |
| Runs on | Any machine; the advisory lock needs `fcntl` (Mac and Linux), and elsewhere only one process may write at a time. Time not measured |
| Network | None. It never contacts Modal; the numbers come from the caller |
| Writes | The ledger CSV named by `--ledger` (default `docs/compute/modal-ledger.csv`), replaced atomically through a temporary `.modal-ledger-*` file in the same folder; a lock file `modalledger-HASH.lock` in the system temporary folder, left in place |
| Go-ahead | Not needed to write the row, since it only edits a local file. The Modal run it records needed its own go-ahead (renting compute, the go-ahead rule, hard rule 8), and the row becomes public only when the change is merged into public Scrolls |
| Released | Public `main` since 2026-10-16 ([pull request 90](https://github.com/ChaseHendrick/Scrolls/pull/90)) |
| Guide | [compute.md, Modal ledger rows](../compute.md#modal-ledger-rows) |
| Checked | 2026-10-16 against commit `63ee638` |

## What it does

GPU work here runs on Modal, a cloud GPU service, under the Modal rule (hard rule 11), and every launch should leave a row in a Modal cost ledger: a CSV of when it ran, what it was for, the GPU type and count, GPU and CPU seconds, the estimated and actual cost, and notes. Rows written by hand, or by a runner that is restarted, tend to be doubled or lost. `kit run modal-row` writes exactly one row per launch.

The caller gives a JSON file with a key, the row, and a `generic` mark. The key is a stable name for the launch (for example a launch token); it is stored at the end of the row's notes as `autoledger KEY`, and the tool writes nothing when the ledger already holds that key. In a ledger that has an `app_id` column, a row whose app id is already there is also skipped, so a hand-written row of the same Modal app is never doubled. The columns come from the ledger's own header, so one writer serves ledgers with different columns.

The public ledger, `docs/compute/modal-ledger.csv`, is recognized by having no `lane_branch` column. Because it is public, it takes a row only behind two gates: the explicit `--public-generic` flag, and `"generic": true` in the file. A row whose purpose or notes name title, target, preregistered, held-out, experiment or candidate work is refused, and the private-only columns `lane_branch` and `app_id` are dropped. A ledger with a `lane_branch` column is treated as private; that ledger lives in the private repository and is not described here.

It records numbers; it does not compute them. It does not ask Modal for prices or usage, does not fill `cumulative_usd`, and does not check that a cost is right. Estimates come from [cloudcost](cloudcost.md); `actual_cost_usd_if_known` comes from Modal's per-app usage report when that is available.

## When to use it

- After each Modal launch of a generic job on public data, to record it in the public ledger.
- From a runner or a script that may run more than once for the same launch: the key makes the second write a no-op.

Do not use it:

- For local runs on the Mac: use `python -m kit run local` ([run-local](run-local.md)).
- To price a job before it runs: use [cloudcost](cloudcost.md).
- For work on a target scroll, a preregistered run or anything else private: that row belongs in the private repository's own ledger, never in the public one (the no-findings rule, hard rule 1).
- To total machine time from provenance records: use [compute](compute.md).

## Quick start

```bash
cat > ROW.json <<'EOF'
{"key": "KEY", "generic": true,
 "row": {"date_time_et": "2026-10-16 08:00 ET", "purpose": "generic smoke run on public data",
         "gpu_type": "B300", "gpu_count": 1, "gpu_seconds": 120, "cpu_seconds": 400,
         "est_cost_usd": 0.25, "notes": "synthetic example"}}
EOF
python -m kit run modal-row ROW.json --ledger docs/compute/modal-ledger.csv --public-generic
```

- `ROW.json`: the row file; format under Inputs. Run from the repository root, since `--ledger` is relative.
- `KEY`: a stable name for this launch, unique per launch, with no `;` or line break.

On a scratch copy of the public ledger (header only, as on 2026-10-16), with a synthetic row that also carried `"app_id": "ap-demo123"` and the key `smoke:2026-10-16a`, it printed, on two runs:

```
/tmp/claude-docs-public-modal-row/ledger.csv: row added (autoledger smoke:2026-10-16a)
/tmp/claude-docs-public-modal-row/ledger.csv: already holds this row; nothing written (autoledger smoke:2026-10-16a)
```

and the ledger gained one line, with `app_id` dropped and blank cells for the columns not given:

```
2026-10-16 08:00 ET,generic smoke run on public data,B300,1,120,400,0.25,,,synthetic example; autoledger smoke:2026-10-16a
```

It worked when the exit code is 0 and the message says `row added`, or `already holds this row` on a rerun.

## Checks and controls

- **The public gates can refuse.** On the same scratch ledger, leaving out `--public-generic` gave `... is the public ledger: pass the explicit public flag (--public-generic) for a generic run, or write the private ledger` with exit code 2, and a purpose reading `target scroll pass` gave `...: the row names target work, which the public ledger never carries` with exit code 2. The tests check every refusal (title, target, held out, prereg, experiment, and a row not marked generic).
- **One row per key.** A second write with the same key prints `already holds this row; nothing written`. The key must match a notes part exactly: `job:1` does not block `job:10` (tested).
- **What it cannot catch.** The word check matches substrings of the purpose and notes only, in lower case. It refuses harmless words that contain a blocked one (such as `experiments` or `subtitle`) and cannot recognize private work described in other words, or private detail in other columns. Read the row before committing it to public Scrolls.

Claim label: None. The tool copies the caller's numbers; the estimated cost is an estimate and the actual cost comes from Modal's report.

## Commands and options

`--root` of `python -m kit run` has no effect on this action.

### `python -m kit run modal-row`

```
usage: python -m kit run modal-row [-h] [--ledger LEDGER] [--public-generic]
                                   file
```

| Option | Default | Meaning |
| --- | --- | --- |
| `file` | required | JSON object: key (unique per launch), row (column: value), generic (true or false). Format under Inputs |
| `--ledger LEDGER` | `docs/compute/modal-ledger.csv` | The ledger CSV to append to, relative to the current folder; it must exist with a header row |
| `--public-generic` | off | Allow writing a public ledger (one without a `lane_branch` column). The row is still refused unless the file says `"generic": true` and its purpose and notes name no title, target, preregistered, held-out, experiment or candidate work. Ignored for a ledger with `lane_branch` |

## Python API

```python
from kit import modalledger
wrote = modalledger.append("docs/compute/modal-ledger.csv", {"purpose": "generic smoke run"}, "KEY",
                           public=True, generic=True)
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `LedgerRowError()` | An exception | Nothing | Raised for every refusal; the command prints its message and exits 2 |
| `read(path)` | `(header, rows)`: the list of column names and a list of dicts, one per row, keyed by column | `LedgerRowError` for a file with no header row; `OSError` for a missing or unreadable file | (header, rows) of a ledger CSV; rows are dicts by the header's columns |
| `is_public(header)` | bool: `True` when the header has no `lane_branch` column | Nothing | How the public ledger is told apart |
| `holds(rows, key, app_id=None)` | bool | Nothing | True when a row carries this key, or this app id (when one is given). The key must equal one `;`-separated part of the notes, `autoledger KEY`, after stripping spaces |
| `public_refusal(row, generic)` | str (the reason), or `None` when the row may go in | Nothing | Why this row may not go into the public ledger, or None. Checks `generic`, then the words of `PUBLIC_BLOCK` in the purpose and notes |
| `append(path, row, key, public=False, generic=False)` | `True` when the row was written, `False` when the ledger already held the key (or, in a ledger with `app_id`, the row's app id) | `LedgerRowError` for a bad key, a header-less file, a public ledger without `public=True`, a row `public_refusal` turns down, or a column the header lacks; `OSError` when the file cannot be read or replaced, with the ledger left as it was | Write row (column: value) to the ledger at path under key, unless it is there already. Takes the lock, rereads the file, appends and replaces it atomically, keeping its permissions |

Constants: `KEY_MARK = "autoledger "`, `PRIVATE_ONLY = ("lane_branch", "app_id")`, `PUBLIC_BLOCK = ("title", "target", "prereg", "held out", "held-out", "heldout", "experiment", "candidate")`.

## Inputs

**The row file** (`file`), a JSON object:

| Key | Type | Meaning |
| --- | --- | --- |
| `key` | string (other JSON values are turned into strings) | Stable, unique name of the launch; non-empty, without `;` or a line break. Stored as `autoledger KEY` |
| `row` | object | Column name to value. Every name must be a column of the ledger's header, except `lane_branch` and `app_id`, which a public row drops |
| `generic` | bool | Must be exactly `true` for the public ledger; anything else, or leaving it out, counts as not generic |

**The public ledger's columns** (header of `docs/compute/modal-ledger.csv`, which on 2026-10-16 holds only the header):

| Column | What to put |
| --- | --- |
| `date_time_et` | Launch time, US Eastern, such as `2026-10-16 08:00 ET` |
| `purpose` | What the job did, in plain words, generic and public |
| `gpu_type`, `gpu_count` | The card the job ran on, such as `B300`, and how many |
| `gpu_seconds`, `cpu_seconds` | Billed seconds |
| `est_cost_usd` | The estimate made before or at launch |
| `actual_cost_usd_if_known` | From Modal's per-app usage report, when available |
| `cumulative_usd` | The running total, if you keep one; the tool does not compute it |
| `notes` | Anything else; the tool appends `autoledger KEY` |

Values are written as text: `null` becomes an empty cell, a float is written with up to 8 decimals and trailing zeros removed (`0.0` as `0`), and anything else with `str()`.

## Outputs

One line on stdout:

```
LEDGER: row added (autoledger KEY)
LEDGER: already holds this row; nothing written (autoledger KEY)
```

The ledger gains one CSV line in the header's column order, with the key at the end of `notes` (after `; ` when there were notes). Existing lines are kept as they were, except that Windows line endings become `\n` (the file is read in text mode); a missing final newline is added first.

| Exit code | Meaning |
| --- | --- |
| `0` | The row was added, or the ledger already held it |
| `2` | Refused or failed, with the message on stderr (see Failure modes), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `cannot read FILE: ...` | The row file is missing or not valid JSON | Fix the path or the JSON |
| `FILE is a JSON object with key, row and optionally generic` | The file is not an object, `row` is not an object, or `key` is missing or empty | Write `{"key": ..., "row": {...}, "generic": true}` |
| `a ledger key is a non-empty string without ';' or a line break` | The key holds `;`, `\n` or `\r` (or is empty when called from Python) | Pick another key |
| `[Errno 2] No such file or directory: 'LEDGER'` | `--ledger` names a missing file, or the command ran outside the repository root | Run from the root, or fix `--ledger`; the tool never creates a ledger |
| `LEDGER has no header row` | The ledger file is empty | Restore its header line |
| `LEDGER is the public ledger: pass the explicit public flag (--public-generic) for a generic run, or write the private ledger` | A public ledger without `--public-generic` | Add the flag for a generic public-data run; anything else belongs in the private ledger |
| `LEDGER: only a run marked generic goes into the public ledger` | `--public-generic` given but the file lacks `"generic": true` | Mark it generic only if it is: public data, nothing private |
| `LEDGER: the row names WORDS work, which the public ledger never carries` | The purpose or notes contain one of title, target, prereg, held out, held-out, heldout, experiment, candidate | If the run is private, write it to the private ledger. If the word is incidental, reword the purpose or notes |
| `LEDGER has no column NAMES` | The row has columns the ledger's header lacks (after a public row drops `lane_branch` and `app_id`) | Remove or rename those keys |
| `cannot read backfill FILE: ...` | Comes from `run backfill`, which shares `cmd_run`; not from this action | See [run-local](run-local.md) |

## How it works

1. The command reads the JSON file and checks its shape, then calls `append(LEDGER, row, str(key), public=--public-generic, generic=(generic is true))`.
2. `append` refuses a key that is empty or holds `;`, `\n` or `\r`, then takes an exclusive `fcntl` lock on `modalledger-HASH.lock` in the system temporary folder, where HASH is the first 16 hex characters of the SHA-256 of the ledger's resolved path, so every writer of one ledger shares one lock.
3. Under the lock it reads the header and rows. For a public header it requires `public`, asks `public_refusal`, and drops `lane_branch` and `app_id` from the row. Any column left that the header lacks is refused.
4. `holds` looks for a notes part equal to `autoledger KEY`, and, in a private ledger, for a row with the same non-empty `app_id`. A hit returns `False` with nothing written.
5. Otherwise it formats each cell, appends the key to the notes, writes the whole old text plus the new line to a temporary file in the ledger's folder, copies the ledger's permissions to it, and `os.replace`s it over the ledger.

## Cost and time

Not measured. It reads and rewrites one small CSV. It contacts no service and rents nothing; the Modal job it records is priced in [cloudcost](cloudcost.md) and the Modal price guide ([modal-pricing.md](../compute/modal-pricing.md)).

## For agents

- **Command:** `python -m kit run modal-row ROW.json --ledger docs/compute/modal-ledger.csv --public-generic`, run from the repository root, with `ROW.json` holding `{"key": ..., "row": {...}, "generic": true}`. There is no JSON output mode.
- **Parse:** stdout ends `row added (autoledger KEY)` or `already holds this row; nothing written (autoledger KEY)`; the new CSV line ends its notes with `autoledger KEY`.
- **Rerun:** Safe with the same key: the second run writes nothing. A new key for the same launch would add a second row in the public ledger, which has no `app_id` column to catch it.
- **Success:** Exit code 0 with either message.
- **Not a pass:** A row whose `est_cost_usd` was never checked against Modal's report; a `cumulative_usd` you did not recompute; a public row that passed the word check but still describes private work in other words.
- **Go-ahead:** Nothing to write the row. Launching the Modal job it records needs the user's budget decision first, and a Claude cloud session runs Modal only with `modal[api-proxy-support]`, Chase's sign-in and an allow rule.
- **Never:** Put a target-scroll, title, preregistered, held-out or other private run in the public ledger; use `--public-generic` to push through a row that is not generic; invent a key per rerun to force a second row.

## Tests

```bash
python -m unittest tests.test_modalledger -v
```

They cover one row per key and per app id in a private-style ledger (and that `job:1` does not block `job:10`), earlier rows kept as they were, number formatting, refusal of unknown columns and of bad keys, the public ledger needing the flag and a generic row and refusing title, target, held out, prereg and experiment rows, `lane_branch` and `app_id` dropped from a public row, and the command line's exit codes 0 and 2 and its messages. They do not test concurrent writers or a failed replace.

## History

- 2026-10-16: merged into public `main` ([pull request 90](https://github.com/ChaseHendrick/Scrolls/pull/90)).
- 2026-10-15: first version: one row per key, columns from the ledger's header, the public ledger only behind `--public-generic` and a generic row (`9461876`).

## Related

- [run-local](run-local.md): the same kind of record for local Mac runs, in the experiment ledger.
- [cloudcost](cloudcost.md): Modal prices and estimates for `est_cost_usd`.
- [compute](compute.md): machine time per run from provenance records.
- [compute.md, Modal ledger rows](../compute.md#modal-ledger-rows): the guide's short version of this page.
- [modal-pricing.md](../compute/modal-pricing.md): Modal rates, plan limits and the default machines.
- [modal-ledger.csv](../compute/modal-ledger.csv): the public ledger itself.
