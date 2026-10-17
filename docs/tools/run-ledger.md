# run-ledger: the local experiment ledger, one run.json per experiment

`python -m kit run init`, `status`, `cost`, `record`, `check` and `list` keep one `run.json` per experiment under `experiments/`: the question, a readout rule hashed before any output is seen, a status that cannot jump to published, costs, file hashes and checks.

| Field | Value |
| --- | --- |
| Id | `run-ledger` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Records and provenance |
| Run | `python -m kit run init`, `python -m kit run status`, `python -m kit run cost`, `python -m kit run record`, `python -m kit run check`, `python -m kit run list`, `from kit import ledger` |
| Code | `kit/ledger.py`, `templates/experiment.json`, `experiments/README.md`, `kit/cli.py` (`cmd_run`) |
| Tests | `tests/test_kit.py`, `tests/test_verify.py` |
| Needs | Python 3.10 or newer, standard library only. `run init` reads the dated prize snapshot `kit/data/prizes-2026-10-11.json` through `kit/prizes.py` |
| Runs on | Any CPU. Each action took about 0.13 s wall on a one-record ledger, almost all of it Python start-up (measured 2026-10-16, 4-core cloud container, synthetic record). `run record` hashes every `--file` in full, so it grows with file size; not measured on large files |
| Network | None |
| Writes | `experiments/SLUG/run.json` (or `ROOT/SLUG/run.json` with `--root`): `init` creates it and its folder; `status`, `cost` and `record` rewrite it in place. `check` and `list` write nothing |
| Go-ahead | Not needed to keep the ledger. Moving a record into git, or making a `candidate` or `submitted` one public, is never allowed before the official announcement (the no-findings rule, hard rule 1) |
| Released | Public `main` since 2026-10-06 (`2daee8e`) |
| Guide | [WORKFLOW.md](../WORKFLOW.md) (plan, run, null or candidate, with these commands) |
| Checked | 2026-10-16 against commit `63ee638` |

## What it does

A First Letters run is only worth something if its readout rule, what will count as ink, was fixed before anyone looked at the target's ink map (the preregistration rule, hard rule 3), and if a possible finding stays private until the Vesuvius Challenge announces it (the no-findings rule, hard rule 1). The ledger is where both rules are kept for each experiment. An experiment is one question asked of one scroll, named by a slug such as `p0826-a`.

`run init` writes `experiments/SLUG/run.json` with the scroll, the question, the readout rule and its SHA-256, the villa commit, the First Letters volume eligible for that scroll in the prize snapshot, and the status `planned`. `run status` moves the experiment along a fixed set of steps (planned, running, null, candidate, submitted, published) and refuses any other step. A `candidate` (a run whose map may show letters) cannot go straight to `published`, and a `submitted` one goes to `published` only with `--announced`. `run cost` adds a dollar amount, `run record` adds a command line with the SHA-256 of the files it used or wrote, and `run check` reports a readout rule edited after `init` or a history that skips the rules. `run list` prints one line per experiment.

Other tools write into the same `run.json`: `verify`, `auc`, `rowscore` and `hpscore` append a check with `--slug`, and `run local` and `run backfill` ([run-local](run-local.md)) append local compute costs.

Everything under `experiments/` except its README is gitignored ([`experiments/README.md`](../../experiments/README.md)), so the ledger lives on one machine. It is a record of what was planned and done, not evidence of a result: a `candidate` status is the operator's label, not a reading, and never means that letters were found. Target-scroll experiments belong in Scrolls-private's checkout, whose ledger works the same way.

## When to use it

- Before any run on a target scroll, or any run whose readout should be fixed in advance: `run init` with the readout rule.
- While the run goes: `run status SLUG running`, `run cost`, `run record` for checkpoints and outputs, and `--slug SLUG` on `verify`, `auc`, `rowscore` or `hpscore` to attach their checks.
- After it: `run status SLUG null` or `candidate`, then `run check` before writing anything up.

Do not use it:

- For local machine time and electricity: use `python -m kit run local SLUG -- COMMAND` ([run-local](run-local.md)), which adds to the same record.
- For Modal jobs: their rows go in `docs/compute/modal-ledger.csv` with `python -m kit run modal-row` ([modal-row](modal-row.md)).
- For a portable, publishable record of one run with input fingerprints and one digest: use [provenance](provenance.md).
- As the preregistration others can see: commit the rule to `docs/prereg/` (public data) or Scrolls-private, since `run.json` itself is never committed.

## Quick start

```bash
python -m kit run init SLUG --scroll SCROLL \
    --question "QUESTION" --readout "READOUT" --villa-commit "$(git -C "$VILLA" rev-parse HEAD)"
python -m kit run status SLUG running
python -m kit run cost SLUG --usd USD --what "WHAT"
python -m kit run record SLUG --command "COMMAND" --file CHECKPOINT
python -m kit run check SLUG
python -m kit run list
```

- `SLUG`: a short name for the experiment, such as `p0826-a`; no `/`, not starting with `.`.
- `SCROLL`: the scroll id, such as `PHerc0826`.
- `QUESTION`: what exactly the run tests.
- `READOUT`: what will count as ink, written now, before any target map exists.
- `VILLA`: your villa checkout.
- `USD` and `WHAT`: a cost in US dollars and what it paid for.
- `COMMAND` and `CHECKPOINT`: a command line the run used, and a file it read or wrote; repeat `--file`.

On a scratch ledger (`python -m kit run --root /tmp/.../exp ...`, a synthetic experiment on PHerc0826 with no villa commit) it printed:

```
created /tmp/claude-docs-public-run-ledger/exp/demo-a/run.json (status planned, readout rule hashed)
demo-a: running
demo-a: total $0.50
demo-a: recorded command and 1 file hash(es)
demo-a: ok
demo-a                       PHerc0826    running    $0.50
```

It worked when every exit code is 0 and `run check` prints `SLUG: ok`. The record's `first_letters_volume` was `20250821151701` for PHerc0826, read from the prize snapshot.

## Checks and controls

- **The readout hash** (`run check`). `init` stores `readout_rule_sha256`, the SHA-256 of the rule's UTF-8 text. On the scratch record above, changing `readout_rule` by hand made `run check` print `problem: readout rule was edited after the run was created` and exit 1. `tests/test_kit.py` checks the same.
- **The status rules** (`run status`). On the scratch record, `running` to `published` was refused (`cannot go from running to published`, exit 2), and `submitted` to `published` without `--announced` was refused with the announcement message (exit 2).
- **What `run check` cannot catch** (read from the code, 2026-10-16). The hash sits in the same file as the rule, so an edit that also replaces the hash passes; a commitment others can check needs the rule or its hash committed elsewhere, such as `docs/prereg/` or a [provenance](provenance.md) digest. `check` cannot tell whether `--announced` was given, so a hand-written `submitted` to `published` step passes.

Claim label: None, for the ledger itself: it records plans, statuses and costs, and makes no claim about ink. A status of `candidate` is the operator's label (Candidate (private)), never a reading.

## Commands and options

### The shared `--root` option

```
usage: python -m kit run [-h] [--root ROOT]
                         {init,status,cost,record,check,list,local,backfill,modal-row,all,watch,catalog} ...
```

`--root` belongs to `run` itself, so it goes before the action: `python -m kit run --root ROOT init SLUG ...`.

| Option | Default | Meaning |
| --- | --- | --- |
| `--root ROOT` | `experiments` | Ledger folder (`ledger.DEFAULT_ROOT`), relative to the current directory. Every action reads and writes `ROOT/SLUG/run.json` |

The other actions of `run` have their own pages: `local` and `backfill` ([run-local](run-local.md)), `modal-row` ([modal-row](modal-row.md)), and `all`, `watch` and `catalog` ([batch](batch.md)).

### `python -m kit run init`

```
usage: python -m kit run init [-h] --scroll SCROLL --question QUESTION
                              --readout READOUT [--villa-commit VILLA_COMMIT]
                              slug
```

| Option | Default | Meaning |
| --- | --- | --- |
| `slug` | required | The experiment's name and folder: not empty, no `/`, not starting with `.` |
| `--scroll SCROLL` | required | The scroll, such as `PHerc0826`. Any spelling the prize snapshot can match (`PHerc. 826`, `pherc0826`) finds its eligible volume; an unknown scroll stores `null` |
| `--question QUESTION` | required | What the run tests, stored as given |
| `--readout READOUT` | required | What will count as ink, written before looking. Must not be blank; stored with its SHA-256 |
| `--villa-commit VILLA_COMMIT` | none | The villa commit the run uses, stored as given (`null` without it) |

### `python -m kit run status`

```
usage: python -m kit run status [-h] [--note NOTE] [--announced]
                                slug
                                {planned,running,null,candidate,submitted,published}
```

| Option | Default | Meaning |
| --- | --- | --- |
| `slug` | required | An experiment made by `run init` |
| `status` | required | The new status, one of `STATUSES`: `planned`, `running`, `null`, `candidate`, `submitted`, `published`. Only the steps under How it works are allowed |
| `--note NOTE` | none | A note stored with the step in `history` (an empty string when left out) |
| `--announced` | off | The prize result was officially announced. Needed for `submitted` to `published`; pass it only after the Vesuvius Challenge announces it |

### `python -m kit run cost`

```
usage: python -m kit run cost [-h] --usd USD --what WHAT slug
```

| Option | Default | Meaning |
| --- | --- | --- |
| `slug` | required | An experiment made by `run init` |
| `--usd USD` | required | The cost in US dollars, rounded to cents when stored; negative values are refused |
| `--what WHAT` | required | What it paid for, such as `Modal A10, 6.5 h` |

### `python -m kit run record`

```
usage: python -m kit run record [-h] --command COMMAND [--file FILE] slug
```

| Option | Default | Meaning |
| --- | --- | --- |
| `slug` | required | An experiment made by `run init` |
| `--command COMMAND` | required | The command line to store, as one quoted string |
| `--file FILE` | none | A checkpoint or output to hash with SHA-256; repeatable. Each must be an existing file (not a folder); the key is the path as given |

### `python -m kit run check`

```
usage: python -m kit run check [-h] slug
```

| Option | Default | Meaning |
| --- | --- | --- |
| `slug` | required | The experiment to check |

### `python -m kit run list`

```
usage: python -m kit run list [-h]
```

No options of its own; it lists every `ROOT/*/run.json`, sorted by path.

| Option | Default | Meaning |
| --- | --- | --- |

## Python API

```python
from kit import ledger
path, record = ledger.init("demo-a", "PHerc0826", "QUESTION", "READOUT", root="experiments")
ledger.set_status("demo-a", "running", note="started")
print(ledger.check("demo-a"))  # [] when consistent
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `LedgerError()` | Exception class | | Raised for every refusal here; the commands print its message and exit with code 2 |
| `path_for(slug, root=DEFAULT_ROOT)` | `Path` of `root/slug/run.json` | `LedgerError` (`bad slug: ...`) for an empty slug, one with `/`, or one starting with `.` | Does not touch the disk |
| `load(slug, root=DEFAULT_ROOT)` | The record dict | `LedgerError` (`no experiment at ...`) when the file is missing; `LedgerError` (`cannot read ...` or `... is not a run record`) for a file that is not JSON or not a JSON object | |
| `save(record, root=DEFAULT_ROOT)` | `Path` written | `LedgerError` for a bad `record["slug"]`; `OSError` | Creates the folder; writes indented JSON with a final newline, replacing the file |
| `init(slug, scroll, question, readout, root=DEFAULT_ROOT, villa_commit=None, snapshot=None)` | `(path, record)` | `LedgerError` when the experiment exists or the readout is blank | `snapshot` is a prize snapshot dict; by default `prizes.load()` reads `kit/data/prizes-2026-10-11.json` |
| `set_status(slug, status, note='', announced=False, root=DEFAULT_ROOT)` | The updated record | `LedgerError` for an unknown status (new, or stored in the file), a step not in `TRANSITIONS`, or `submitted` to `published` without `announced` | Appends to `history` and saves |
| `add_cost(slug, usd, what, root=DEFAULT_ROOT)` | The updated record | `LedgerError` for a `usd` that is not finite (NaN or infinity) or is negative | Stores `round(usd, 2)` |
| `add_provenance(slug, command, files=(), root=DEFAULT_ROOT)` | The updated record | `LedgerError` (`not a file: ...`) for a path that is not a file | Record a command line and the SHA-256 of files it used or wrote (checkpoints, maps), in 1 MiB chunks |
| `add_check(slug, name, result, root=DEFAULT_ROOT)` | The updated record | `LedgerError` when the experiment is missing | Attach a verification result (such as from `kit verify`) to an experiment; what `--slug` on `verify`, `auc`, `rowscore` and `hpscore` calls |
| `total_cost(record)` | float, the sum of `costs[].usd` rounded to cents | `KeyError` for a record without `costs` | |
| `check(slug, root=DEFAULT_ROOT)` | list of problem strings; empty means consistent | `LedgerError` when the experiment is missing | Return a list of problems; empty means the record is consistent |
| `list_runs(root=DEFAULT_ROOT)` | list of record dicts sorted by path; `[]` when `root` is not a folder | `LedgerError` for a `run.json` that is not JSON or not a JSON object | |

Constants: `DEFAULT_ROOT = Path("experiments")`, `STATUSES` and `TRANSITIONS` (see How it works).

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Options | Text on the command line | The question, readout rule, notes and command lines are stored as given, in UTF-8 |
| Prize snapshot | `kit/data/prizes-2026-10-11.json`, read by `run init` | Gives `first_letters_volume` (the First Letters 2027 volume for the scroll) and `prize_snapshot` (the snapshot's `checked` date). Offline; `python -m kit prizes` shows it |
| Files for `run record` | Any regular files | Read in full to hash; folders are refused (use [provenance](provenance.md), which fingerprints folders) |
| An existing `run.json` | JSON, as under Outputs | Every action but `init` and `list` needs it |

[`templates/experiment.json`](../../templates/experiment.json) shows the format with an example PHerc0826 experiment. No code reads it; `run init` writes the same fields.

## Outputs

Each action prints one line (see Quick start); `check` prints one `problem: ...` line per problem; `list` prints one line per experiment: slug (28 wide), scroll (12 wide), status (10 wide) and the total cost as `$0.00`.

`ROOT/SLUG/run.json`, indented JSON:

| Field | Type | Meaning |
| --- | --- | --- |
| `slug` | str | The experiment's name |
| `created` | str | UTC time of `init`, ISO 8601 to the second (`2026-10-16T19:32:12+00:00`) |
| `scroll` | str | As given |
| `first_letters_volume` | str or null | The scroll's eligible First Letters 2027 volume in the snapshot; null when not eligible or unknown |
| `prize_snapshot` | str | Date the prize snapshot was checked |
| `question` | str | As given |
| `readout_rule` | str | As given |
| `readout_rule_sha256` | str | SHA-256 (hex) of `readout_rule` in UTF-8 |
| `villa_commit` | str or null | As given |
| `status` | str | Current status |
| `history[]` | list of `{at, status, note}` | Every status step, oldest first; the first is `planned` with note `created` |
| `costs[]` | list of `{at, usd, what}` | From `run cost`; `run local` and `run backfill` add entries with a `local` object too |
| `provenance[]` | list of `{at, command, sha256}` | From `run record`; `sha256` maps each path as given to its hash. Absent until the first `record` |
| `checks[]` | list of `{at, name, result}` | From `--slug` on `verify`, `auc`, `rowscore` and `hpscore`; `result` is that command's JSON. Absent until the first check |

| Exit code | Meaning |
| --- | --- |
| `0` | Done; for `check`, the record is consistent |
| `1` | `check` found problems; also an error the command does not catch, with a Python traceback |
| `2` | Refused, with the message on stderr (see Failure modes), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as `argument status: invalid choice: 'foo'` or `argument --usd: invalid float value: 'abc'` | Check the command against Commands and options; `--root` goes before the action |
| `bad slug: '...'` | An empty slug, one with `/`, or one starting with `.` | Use a plain name such as `p0826-a` |
| `no experiment at ROOT/SLUG/run.json` | The slug was never started, or `--root` points elsewhere | Run `run init` first, or fix the slug and `--root` |
| `SLUG already exists` | `run init` on a slug that has a `run.json` | Pick a new slug; never overwrite a record |
| `a readout rule is required before the run starts` | `--readout` is blank | Write the readout rule now, before looking at any target output |
| `unknown status '...'; use one of planned, running, null, candidate, submitted, published` | `set_status` called from Python with another word (the command line refuses it earlier) | Use one of the listed statuses |
| `cannot go from CURRENT to NEW` | A step not in `TRANSITIONS`, such as `running` to `published` or anything after `published` | Follow the steps under How it works; a `candidate` goes through `submitted` |
| `a submitted result stays private until the prize is officially announced; pass --announced only after Vesuvius Challenge announces it` | `submitted` to `published` without `--announced` | Wait for the official announcement |
| `SLUG has the unknown status '...' in its run.json; it must be one of planned, running, null, candidate, submitted, published` | `run status` on a record whose stored `status` was edited to another word (or is missing) | Restore `status` from `history`, then rerun |
| `cost must be a finite number of US dollars, not nan` (or `inf`) | `--usd nan`, `inf` or `-inf` | Give the amount as a plain number |
| `cost cannot be negative` | `--usd` below 0 | Record refunds in `--what` of a corrected entry instead |
| `not a file: PATH` | A `--file` that is missing or a folder | Fix the path; hash folders with [provenance](provenance.md) |
| `problem: readout rule was edited after the run was created`, exit code 1 | `readout_rule` no longer matches its hash | The run's preregistration is broken: say so in any write-up, and start a new experiment with the rule fixed before looking |
| `problem: unknown status '...'`, exit code 1 | The file's `status` was edited to another word | Restore it from `history` |
| `problem: history does not start at planned`, exit code 1 | `history` is empty, or its first step is not `planned`: steps were removed or the file was written by hand | Find out who edited the file; do not trust the record |
| `problem: history has an illegal step A -> B`, exit code 1 | `history` holds a step `run status` would refuse | Find out who edited the file; do not trust the record |
| `problem: status does not match the last history entry`, exit code 1 | `status` was edited by hand | Restore it from `history` |
| `cannot read ROOT/SLUG/run.json: ...; fix the file or restore it from a backup`, exit code 2 | A `run.json` that is not valid JSON; any action that reads it, `run list` included, stops here | Repair the JSON by hand, or restore it from a backup |
| `ROOT/SLUG/run.json is not a run record (a JSON object); fix the file or restore it from a backup`, exit code 2 | A `run.json` that holds JSON other than an object, such as a list | Restore the record from a backup |
| `cannot read backfill FILE: ...` | `run backfill` only: its JSON file is missing or not JSON ([run-local](run-local.md)) | Fix the file |
| `FILE is a JSON object with key, row and optionally generic` | `run modal-row` only: its spec has the wrong shape ([modal-row](modal-row.md)) | Fix the spec |

## How it works

1. `init` checks the slug (`path_for`), refuses an existing record and a blank readout rule, reads the prize snapshot, hashes the readout rule with SHA-256, and saves the record with status `planned`.
2. `status` loads the record, refuses a stored status that is not one of `STATUSES`, checks the new status against `TRANSITIONS`, refuses `submitted` to `published` without `--announced`, appends `{at, status, note}` to `history`, and saves.
3. `cost`, `record` and the `--slug` of other commands load the record, append one entry with the UTC time, and save the whole file again.
4. `check` recomputes the readout hash, checks that the status is known, that `history` starts at `planned`, that each pair of steps in `history` is allowed, and that `status` equals the last step.

The allowed steps (`TRANSITIONS` in `kit/ledger.py`):

| From | To |
| --- | --- |
| `planned` | `running`, `null` |
| `running` | `null`, `candidate`, `running` |
| `null` | `published`, `running` |
| `candidate` | `submitted`, `null` |
| `submitted` | `published` (with `--announced`), `null` |
| `published` | nothing |

A null can be shared at any time; a candidate reaches `published` only through `submitted` and the announcement. The two rules come from the prize terms, which forbid making a discovery public before the official announcement ([prizes](https://scrollprize.org/prizes)), and from published First Letters runs that preregistered their readout ([WORKFLOW.md](../WORKFLOW.md)).

Writes are plain rewrites of the file with no lock, so two commands writing the same experiment at once can lose an entry.

## Cost and time

About 0.13 s wall per action on a one-record ledger (measured 2026-10-16, 4-core cloud container, synthetic record), mostly Python start-up. `run record` reads every file it hashes in full; hashing large checkpoints was not measured. It runs on any machine and rents nothing; nothing here needs Modal or a GPU.

## For agents

- **Command:** `python -m kit run init SLUG --scroll SCROLL --question "Q" --readout "RULE" --villa-commit HASH`, then `python -m kit run status SLUG running`, and `python -m kit run check SLUG`. There is no `--json`; read `ROOT/SLUG/run.json` directly for machine use.
- **Parse:** In `run.json`: `status`, `history[-1]`, `readout_rule_sha256`, `first_letters_volume`, `costs[].usd`, `checks[].result`. From `run check`: lines starting `problem: `, or `SLUG: ok`.
- **Rerun:** `init` refuses a slug that exists. `status`, `cost`, `record` and `--slug` checks append each time they run, so a repeated `run cost` counts the cost twice. `check` and `list` are read-only.
- **Success:** Exit code 0; `run check` prints `SLUG: ok`.
- **Not a pass:** `SLUG: ok` when the readout rule was written after looking (the hash only proves it did not change after `init`); a record whose hash and rule were both edited; a `published` reached from `submitted` in a hand-edited history; a `candidate` status read as a result.
- **Go-ahead:** Nothing to keep the ledger. Never move a `candidate` or `submitted` record, or anything it describes, into git, a PR or a post before the official announcement.
- **Never:** Pass `--announced` before the Vesuvius Challenge announces the result; edit `readout_rule` after `init`; commit `experiments/` contents to public Scrolls; call a `candidate` a reading or say letters were found.

## Tests

```bash
python -m unittest tests.test_kit.LedgerTest tests.test_kit.CliTest.test_run_roundtrip -v
python -m unittest tests.test_verify -v
```

`LedgerTest` in `tests/test_kit.py` covers the eligible volume and hash written by `init`, a readout edit caught by `check`, a `candidate` refused straight to `published` and `submitted` refused without `announced`, a `null` published, costs and the negative-cost refusal, and the blank-readout and `../escape` refusals. `CliTest.test_run_roundtrip` runs `init`, `check` and `list` on the command line with `--root`. `tests/test_verify.py` covers `add_provenance` and its refusal of a missing file, and a `verify` check stored with `--slug`. `LedgerTest` also covers a history that does not start at `planned`, a cost that is not finite, and a corrupt record or unknown stored status raised as `LedgerError`; `CliTest` checks that `run` reports a corrupt record without a traceback. They do not cover `check`'s other history and status problems.

## History

- 2026-10-17: `run check` reports a history that does not start at `planned`; before, such a history passed (`b4edc21`).
- 2026-10-17: `run cost` refuses a cost that is not a finite number; before, `--usd nan` was stored and the total printed `$nan` (`bc75474`).
- 2026-10-17: a `run.json` that is not JSON or not an object, or that holds an unknown status, is reported as a message with exit code 2; before, it ended in a `JSONDecodeError` or `KeyError` traceback with exit code 1 (`4941862`).
- 2026-10-07: `run record` (`add_provenance`) and `add_check`, so `verify` and later `auc` attach checks with `--slug` (`99dba9e`).
- 2026-10-06: first version, with the hashed readout rule, the status steps and the announcement guard (`2daee8e`).

## Related

- [provenance](provenance.md): a portable record of one run with input fingerprints and one digest that can be published alone.
- [run-local](run-local.md): `run local` and `run backfill`, which add local compute costs to the same `run.json`.
- [modal-row](modal-row.md): the Modal ledger CSV, kept apart from `run.json`.
- [verify](verify.md), [auc](auc.md), [rowscore](rowscore.md) and [hpscore](hpscore.md): attach their results as checks with `--slug`.
- [WORKFLOW.md](../WORKFLOW.md): the plan, run, null and candidate steps that use these commands.
- [`experiments/README.md`](../../experiments/README.md): why the folder is gitignored and how to share a null.
