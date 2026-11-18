# mergedriver: git merge drivers for tables, registries and indexes that many branches append to

`python -m kit.mergedriver` installs git merge drivers that merge CSV tables by row, JSON registries by entry and Markdown indexes and JSON-lines logs by line, so two branches that each add a row no longer conflict, while a real conflict still stops the merge.

| Field | Value |
| --- | --- |
| Id | `mergedriver` |
| Status | Current |
| Kind | kit entry point, kit module |
| Area | Releases and repository |
| Run | `python -m kit.mergedriver install`, `python -m kit.mergedriver status`, `python -m kit.mergedriver attributes`, `from kit import mergedriver` |
| Code | `kit/mergedriver.py` |
| Tests | `tests/test_mergedriver.py` |
| Needs | Python 3.10 or newer (standard library only) and git 2.x on `PATH`; kit importable as `python3 -m kit.mergedriver` from the clone's top folder (a clone of this repository, or kit on `PYTHONPATH`) |
| Runs on | Any machine; a merge of a file takes milliseconds |
| Network | None |
| Writes | `install`: `merge.kit-csv.*`, `merge.kit-json.*` and `merge.kit-lines.*` in the clone's `.git/config`. A driver run (git calls it): the merged file into git's OURS temporary file |
| Go-ahead | Not needed |
| Released | Public `main` from the PR that adds this page (2026-11-18) |
| Checked | 2026-11-18 against commit `f16c9e3` |

## What it does

In a repository where many branches each add a row to a run log, an entry to a JSON registry or a line to an index, git's line merge calls two different additions at the same place a conflict, though nothing conflicts. In one busy repository, replaying a week of merges found that in more than half of the merges with textual conflicts every conflicting file was such a table, registry or index. git's built-in `merge=union` does not help a table whose rows are also edited in place: it keeps both versions of an edited row.

This tool gives git three merge drivers that merge by identity, not by line:

- **csv** (`kit-csv`): rows keyed by the key columns (`--csv-key` at install, default the column named `id`, else the first column), with an occurrence number for repeated keys. A row added on one side is kept; a row changed on one side takes that change; a row changed on both sides merges field by field. Rows keep their original bytes unless merged field by field, and the result has LF line ends.
- **json** (`kit-json`): objects merged key by key, lists of objects that all carry a unique `"id"` merged by id, other lists merged only when one side left them alone. The file is written back only in the exact format it had (indent and `ensure_ascii` are detected), so a merge never reformats it.
- **lines** (`kit-lines`): `git merge-file` first; in each hunk it calls a conflict, lines or table rows that both sides added at the same place are all kept, ours first (a nonblank line both added is kept once), and an edit on one side next to an addition on the other is taken. A path ending `.jsonl` is an append-only log: the merge base, then theirs' new lines, then ours' new lines, so a branch that merges the main branch in keeps the main branch's records first (`KIT_LINES_FIRST=ours` or `theirs` overrides).

Whenever a driver meets a real conflict (the same field or line changed two ways, a row changed on one side and removed on the other, a format it does not understand, or any error), it falls back to `git merge-file`, which leaves the usual conflict markers, so git stops the merge as it would without the driver. If Python itself fails, the configured command runs `git merge-file` on the untouched files. A clone without the drivers configured merges these files as before.

## When to use it

- A repository whose branches often add rows to the same CSV log, entries to the same JSON registry, or lines to the same Markdown index or JSON-lines log.

Do not use it:

- For source code or prose that people edit in the middle: line merges and real conflicts are what you want there.
- For a CSV table without a stable key column: rows edited in place could not be paired.

## Quick start

```bash
python -m kit.mergedriver install --csv-key date,job_id      # once per clone
python -m kit.mergedriver attributes                           # example .gitattributes lines to adapt and commit
python -m kit.mergedriver status
```

- `date,job_id`: the columns that identify a row of your CSV tables; leave `--csv-key` out to key by an `id` column, else the first column.

`install` printed `set 3 driver(s) in .git/config`, then `status` printed `OK: drivers set` (2026-11-18). Then list your files in `.gitattributes`, as `attributes` shows:

```
logs/runs.csv          merge=kit-csv
registry/*.json        merge=kit-json
docs/INDEX.md          merge=kit-lines
logs/*.jsonl           merge=kit-lines
```

It worked when two branches that each append a row to a listed table merge with exit code 0 and both rows in the result.

## Checks and controls

The control is a real conflict: the tests make two branches change the same field of the same row two ways, and the merge must stop with conflict markers, as git's own merge does. Each driver also has unit cases that must conflict (the same field, line or id changed two ways; a row changed on one side and removed on the other; different headers; a JSON format that does not round-trip). A further test removes kit from the path, so the driver command itself fails, and checks that both sides still reach the file through `git merge-file`.

Claim label: Interpretation, for the share of conflicts these drivers remove (one repository's replay); the drivers' behavior is tested.

## Commands and options

### `python -m kit.mergedriver`

```
usage: python -m kit.mergedriver [-h] [--root ROOT]
                                 {install,status,attributes,csv,json,lines} ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--root ROOT` | `.` | the clone (git runs drivers from its top folder) |
| `install` | | set the three drivers in the clone's `.git/config` (idempotent; without `--csv-key` an installed key is kept) |
| `--check` | off | `install`: only report, exit 1 when any driver is missing |
| `--quiet` | off | `install`: print nothing when all is well |
| `--csv-key CSV_KEY` | the column `id`, else the first | `install`: key columns for the csv driver, comma-separated |
| `status` | | say whether the drivers are set; exit 1 when one is missing |
| `attributes` | | print example `.gitattributes` lines |
| `csv BASE OURS THEIRS [PATH]` | | git's csv driver: merge into OURS |
| `--key KEY` | the column `id`, else the first | `csv`: key columns, comma-separated |
| `json BASE OURS THEIRS [PATH]`, `lines BASE OURS THEIRS [PATH]` | | git's json and lines drivers; PATH is git's `%P` (a `.jsonl` path is an append-only log) |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_LINES_FIRST` | `theirs` | for an append-only `.jsonl` log, whose new lines come first: `ours` or `theirs` |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `merge_csv(base, ours, theirs, key=None)` | the merged text | `Conflict` | key: a list of column names |
| `merge_json(base, ours, theirs)` | the merged text | `Conflict` | |
| `merge_lines(base, ours, theirs, first='ours')` | the merged text | `Conflict` | |
| `merge_append(base, ours, theirs, first='theirs')` | the merged text | `Conflict` | an append-only log |
| `union_hunk(b, o, t, first='ours')` | list of lines | `Conflict` | one conflict hunk merged by line union |
| `append_only(path)` | bool | Nothing | a path ending `.jsonl` |
| `lines_first(path)` | `'ours'` or `'theirs'` | Nothing | from `KIT_LINES_FIRST` for a log |
| `drive(kind, base_path, ours_path, theirs_path, path=None, key=None)` | exit code | Nothing | what git calls; falls back to `git merge-file` on any error |
| `driver_command(kind, csv_key=None)` | str | Nothing | the command written to `.git/config` |
| `install(root='.', check_only=False, csv_key=None)` | list of (name, command) missing or changed | `OSError` from git | writes them unless `check_only`; without `csv_key` an installed csv driver keeps its key |
| `installed_key(command)` | list of column names or None | Nothing | the `--key` of an installed csv driver command |
| `add_arguments(p)` | the parser | Nothing | the subcommands |
| `run(args)` | exit code | Nothing | the command on parsed arguments |
| `main(argv=None)` | exit code | `SystemExit` 2 on bad arguments | |

Constants: `DRIVERS`, `DRIVER`, `ATTRIBUTES`, `MERGERS`, `MARK` (31, the conflict marker length it reads).

## Inputs

Git's three temporary files (BASE, OURS, THEIRS) and the path, read as UTF-8 with line ends kept.

## Outputs

The merged file in OURS. `install` and `status` print one line per missing driver and a summary.

| Exit code | Meaning |
| --- | --- |
| `0` | merged cleanly (driver); drivers set (`install`, `status`) |
| `1` | `status` or `install --check`: a driver is missing |
| `2` | bad arguments, or git failed during `install` |
| `3` | conflict markers left in OURS: git stops the merge |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `kit.mergedriver KIND: REASON; merging by line` on stderr | a real conflict or an unreadable file; the driver fell back to `git merge-file` | resolve the markers as usual |
| `csv: the headers differ or a side is empty` | the table's header changed on a side | merge the header change first |
| `csv: no column(s) NAMES to key rows by` | `--key` names a column the table lacks | install with the right `--csv-key` |
| `csv: a row we changed was removed by them`, `csv: a row they changed was removed by us` | one side edited a row the other deleted | decide by hand |
| `the same field changed two ways`, `a row added or changed differently on both sides` | both sides set one field differently | decide by hand |
| `csv: a repeated row key changed count on both sides, so its rows cannot be paired` | a key that is not unique changed on both sides | give the table a unique key |
| `csv: ...`, `json: ...` with a parser message | the file does not parse | fix the file |
| `json: the same key or id added two ways`, `json: a value changed two ways` | a real JSON conflict | decide by hand |
| `json: 'KEY' removed by us, changed by them`, `json: 'KEY' changed by us, removed by them`, `json: entry 'ID' changed by them, removed by us`, `json: entry 'ID' changed by us, removed by them` | one side removed what the other changed | decide by hand |
| `json: the file's format does not round-trip, so it is merged by line` | the file is not formatted the way `json.dumps` writes it | format it with one indent and keep it so |
| `lines: the same existing line edited on both sides`, `lines: lines added inside a run the other side replaced` | a real line conflict | decide by hand |
| `lines: a conflict hunk it cannot read`, `lines: an unfinished conflict hunk` | a file already holding conflict markers | clean the file first |
| `kit.mergedriver: git config ...` | git failed during `install` | run inside a clone |
| `git merge-file failed: ...` | git itself crashed during a fallback | check git on `PATH` |
| `error: argument --key: --key takes column names separated by commas` | an empty `--key` or `--csv-key` | name the columns |

## How it works

git calls the configured command with `%O %A %B %P` (base, ours, theirs, path). The command runs the driver; an exit of 0 or 3 is final, and any other exit (Python missing, an import error) runs `git merge-file` on the untouched files. The csv driver parses every side with Python's `csv` module, keeps each record's bytes, pairs rows by key and occurrence, and takes a group of repeated keys whole from the side that changed it. The json driver merges recursively and writes the result with the detected indent. The lines driver asks `git merge-file --diff3` for hunks with 31-character markers and merges each by `difflib` edits.

## Cost and time

Milliseconds per file; the tests run in about 1 s (2026-11-18, a 4 logical CPU cloud container). It rents nothing.

## For agents

- **Command:** `python -m kit.mergedriver install --csv-key COLS --quiet` at the start of a session in each clone; commit `.gitattributes` lines for the files.
- **Parse:** exit codes; `status` lines starting `missing`.
- **Rerun:** safe; `install` is idempotent.
- **Success:** `status` prints `OK: drivers set`, and a merge of two added rows exits 0.
- **Not a pass:** a merge that exits 0 on a file not listed in `.gitattributes` (git's own merge did it).
- **Go-ahead:** Nothing.
- **Never:** resolve a fallback's conflict markers by keeping one side without reading both.

## Tests

```bash
python -m unittest tests.test_mergedriver -v
```

24 tests: each driver's merges and its real conflicts, CRLF input, the default key, JSON format detection, line unions and append-only order, and real git merges in a scratch repository (two branches without a conflict, a real conflict that stops the merge, and a broken kit that still leaves both sides).

## History

- 2026-11-18: released to public Scrolls (`RELEASE_COMMIT`): the csv, json and lines drivers with configurable CSV key columns. Developed outside this repository from 31 Oct 2026.

## Related

- [releases](releases.md): `docs/releases.json`, one JSON registry such a driver can merge.
