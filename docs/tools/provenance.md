# provenance: a run record with input fingerprints and one digest

`python -m kit provenance write` records who ran a job, when, on which machine, from which code commits, and the SHA-256 of its models, inputs and outputs, sealed by one digest; `check` recomputes the digest and, with `--files`, rehashes every file.

| Field | Value |
| --- | --- |
| Id | `provenance` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Records and provenance |
| Run | `python -m kit provenance write`, `python -m kit provenance check`, `from kit import provenance` |
| Code | `kit/provenance.py`, `kit/cli.py` (`cmd_provenance`) |
| Tests | `tests/test_provenance.py` |
| Needs | Python 3.10 or newer, standard library only. `git` on the PATH for the commit, branch and operator name (without it those fields are null or fall back to the login name); on macOS, `sysctl` for the chip name |
| Runs on | Any CPU. `write` on three tiny synthetic files took 0.15 s wall (measured 2026-10-16, 4-core cloud container). Time grows with the bytes hashed, since every file of every model, input and output is read in full; large stores not measured |
| Network | None. It hashes local files only; it never lists or downloads a remote store |
| Writes | `write`: the JSON record at `path`, creating its parent folders and replacing any file there. `check` writes nothing |
| Go-ahead | Not needed to write or check a record. Publishing a record or its digest is an outward action and needs Chase's yes (the go-ahead rule, hard rule 8); a record of a target-scroll run stays in Scrolls-private (the no-findings rule, hard rule 1) |
| Released | Public `main` since 2026-10-07 (`1d45c54`) |
| Guide | [STANDARDS.md](../STANDARDS.md) (the Provenance row) |
| Checked | 2026-10-16 against commit `63ee638` |

## What it does

A number or an ink map is only worth reporting if someone can later tell exactly which code, checkpoint and input produced it, and that none of them changed since. `kit provenance write` builds one JSON record per run: the run's name, the operator (git's `user.name` in the code checkout, else the login name, never an email), the machine (system, release, architecture, Python version, and on macOS the chip and macOS version), start and finish times in UTC, the commit and branch of each code checkout with a flag for uncommitted changes, and a fingerprint of every model, input and output.

A fingerprint is the SHA-256 of a file, or for a folder such as a zarr store, the SHA-256 of a manifest listing every file's relative path, size and SHA-256 in sorted order. So a folder's fingerprint changes when any file's content, name or size changes.

The record ends with `digest`, the SHA-256 of the record itself without the digest, written as compact JSON with sorted keys. The digest can be published or committed alone as a timestamped commitment: it says nothing about the run, and anyone later shown the record can recompute it. The Mac scripts write one record for every run, null or not, so publishing a digest never hints at a result. `kit provenance check` recomputes the digest, and with `--files` refingerprints every listed path and reports what changed or went missing.

It does not judge the run. A record that checks `ok` says the record and its files are as written; it says nothing about whether the output is right or shows ink. An ink map it fingerprints is model output, not a reading.

## When to use it

- At the end of any run whose output may be reported: an inference, a scoring run, a training run. `scripts/mac-w045.sh` writes one per model and segment.
- Before publishing a result, to commit to the exact run first: publish or commit the digest, keep the record.
- When rechecking an old result: `check --files` says whether the checkpoint, inputs and outputs on disk are still the ones the record names.

Do not use it:

- To keep an experiment's plan, readout rule, status and costs: use the experiment ledger ([run-ledger](run-ledger.md)); `run record` there stores a command line with its files' hashes inside the experiment's `run.json`.
- To total machine time per run: use `python -m kit compute DIR` ([compute](compute.md)), which reads these records.
- To check that two maps agree: use [verify](verify.md). Equal fingerprints mean byte-identical files; different ones say nothing about how far apart two maps are.
- On a remote store: fetch it first ([fetch](fetch.md)); `write` hashes only local paths.

## Quick start

```bash
python -m kit provenance write OUT.json --run "NAME" --repo SCROLLS --code-repo VILLA \
    --model CHECKPOINT --input INPUT --output MAP.tif --started START
python -m kit provenance check OUT.json --files
```

- `OUT.json`: where to write the record, such as `work/RUN/provenance.json`.
- `NAME`: the run's name, such as `mac-w045 w045 v8in quick=1 smoke=0`.
- `SCROLLS`: the Scrolls checkout the run used (default `.`); `VILLA`: another code checkout, such as villa; repeat `--code-repo`.
- `CHECKPOINT`, `INPUT`, `MAP.tif`: local files or folders; repeat each option as needed.
- `START`: the run's start time in UTC, such as `2026-10-07T08:00:00Z`.

On synthetic files (an 8-byte `model.pth`, a two-file `store.zarr`, a 4-byte `map.tif`, run from the Scrolls checkout with `--note "synthetic files"`) it printed:

```
/tmp/claude-docs-public-provenance/prov.json: digest b28ed7f85688cbf65652f7bf9e6bbb6ff436a19134225f79a3b79723f00c8ed0
/tmp/claude-docs-public-provenance/prov.json: ok (digest b28ed7f85688cbf65652f7bf9e6bbb6ff436a19134225f79a3b79723f00c8ed0, files unchanged)
```

It worked when both exit codes are 0 and `check` ends `ok`. Keep the printed digest: it is the commitment.

## Checks and controls

- **A changed file is caught** (`check --files`). On the synthetic record above, rewriting `map.tif` gave `problem: outputs: /tmp/claude-docs-public-provenance/map.tif changed` and exit 1; deleting it gave `... is missing` and exit 1. `tests/test_provenance.py` checks the same, and that renaming a file inside a folder changes the folder's fingerprint.
- **An edited record is caught** (`check`). Changing the `run` field of the synthetic record gave `problem: digest does not match the record` and exit 1; the tests do the same with the operator's name.
- **What it cannot catch** (read from the code, 2026-10-16). Someone who edits the record and recomputes the digest passes `check`; only a digest published or committed before the edit shows the change. Without `--files`, `check` never looks at the files. `--files` resolves relative paths from the current directory, so a record written with relative paths reports files as missing when checked from elsewhere. `started_utc` is whatever `--started` says; only `finished_utc` comes from the clock.

Claim label: None, for the record itself: it states where a result came from and makes no claim about ink.

## Commands and options

### `python -m kit provenance write`

```
usage: python -m kit provenance write [-h] --run RUN [--repo REPO]
                                      [--code-repo CODE_REPO] [--model MODEL]
                                      [--input INPUT] [--output OUTPUT]
                                      [--started STARTED] [--note NOTE]
                                      path
```

| Option | Default | Meaning |
| --- | --- | --- |
| `path` | required | Where to write the JSON record; parent folders are created and an existing file is replaced |
| `--run RUN` | required | The run's name, stored as `run` |
| `--repo REPO` | `.` | The Scrolls checkout: the first `code` entry and the operator's name come from it. Stored as given, not resolved |
| `--code-repo CODE_REPO` | none | Another git checkout the run used, such as villa; repeatable. Each adds a `code` entry |
| `--model MODEL` | none | A checkpoint file or folder; repeatable |
| `--input INPUT` | none | An input file or store (a zarr folder is fine); repeatable |
| `--output OUTPUT` | none | An output file or folder; repeatable |
| `--started STARTED` | none | The run's UTC start time, such as `2026-10-07T08:00:00Z`, stored as given (null without it) |
| `--note NOTE` | none | A free-text note, stored as `note` when not empty |

### `python -m kit provenance check`

```
usage: python -m kit provenance check [-h] [--files] path
```

| Option | Default | Meaning |
| --- | --- | --- |
| `path` | required | A record written by `provenance write` |
| `--files` | off | Also refingerprint every model, input and output at its recorded path and report each that changed or is missing |

## Python API

```python
from kit import provenance
record = provenance.build("NAME", ".", started="2026-10-07T08:00:00Z", models=["m.pth"], outputs=["map.tif"])
provenance.write(record, "prov.json")
print(provenance.verify(record, recheck_files=True))  # [] when nothing changed
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `sha256_file(path)` | str, hex SHA-256 of the file | `OSError` for an unreadable file | Reads in 1 MiB chunks (`CHUNK`) |
| `fingerprint(path)` | A file: `{"path", "kind": "file", "bytes", "sha256"}`; a folder: `{"path", "kind": "directory", "files", "bytes", "sha256"}` | `FileNotFoundError(path)` when the path is neither a file nor a folder | SHA-256 of a file, or of a directory's sorted (relative path, size, sha256) manifest. `path` is stored as given |
| `code_state(repo)` | `{"repo", "commit", "branch", "uncommitted_changes"}`, or `{"repo", "commit": None}` when git fails | Nothing | Commit, branch, and whether tracked files differ from that commit (untracked files are ignored) |
| `operator(repo)` | `{"name", "login"}` | Only what `getpass.getuser()` raises when no login name can be found | Who ran it: git's `user.name` where the code lives, else the login name. No email |
| `machine()` | `{"system", "release", "machine", "python"}`, plus `chip` and `macos` on macOS | Nothing | From `platform`, and `sysctl -n machdep.cpu.brand_string` on macOS |
| `canonical(record)` | bytes | `TypeError` for values JSON cannot hold | The bytes the digest covers: the record without its digest, keys sorted, no spaces, UTF-8 |
| `build(name, repo, started=None, inputs=(), models=(), outputs=(), extra_code=(), note=None, notes=None)` | The record dict under Outputs, with `digest` | `FileNotFoundError` for a missing model, input or output; `OSError` | Assemble a record. inputs, models and outputs are paths; extra_code are other git repos. `notes` (any JSON value) is stored as `notes`; the command line has no option for it |
| `verify(record, recheck_files=False)` | list of problem strings; empty means the record checks | `KeyError` for a listed item without `path` or `sha256` | Problems with a record: a digest that does not match, and optionally files that changed |
| `write(record, path)` | `Path` written | `OSError` | Indented JSON, sorted keys, UTF-8, final newline; creates parent folders |

Constants: `CHUNK = 1 << 20` (1 MiB read size), `SCHEMA = 1` (the record's `schema`).

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Models, inputs, outputs | Local files or folders | Any size; every file under a folder is read in full. Paths are stored exactly as given, so absolute paths make `check --files` work from any directory |
| Code checkouts (`--repo`, `--code-repo`) | git working trees | A path that is not a git checkout gives `commit: null` and no branch |
| A record (`check`) | JSON written by `write` | Any edit, even whitespace inside a value, changes the digest; reformatting the file's indentation does not |

## Outputs

`write` prints `PATH: digest HEX`. `check` prints `problem: ...` lines, or `PATH: ok (digest HEX)`, with `, files unchanged` added under `--files`.

The record (`schema` 1), written with sorted keys:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | int | Record format, `1` |
| `run` | str | `--run` |
| `operator.name`, `operator.login` | str | git `user.name` of `--repo` (else the login name), and the login name |
| `machine.system`, `.release`, `.machine`, `.python` | str | From Python's `platform` module |
| `machine.chip`, `machine.macos` | str | macOS only |
| `started_utc` | str or null | `--started`, as given |
| `finished_utc` | str | UTC time of `write`, `YYYY-MM-DDTHH:MM:SSZ` |
| `code[]` | list of objects | One per checkout, `--repo` first: `repo` (as given), `commit` (40 hex, or null), `branch` (`HEAD` when detached), `uncommitted_changes` (bool; tracked files only) |
| `models[]`, `inputs[]`, `outputs[]` | list of fingerprints | `path` (as given), `kind` (`file` or `directory`), `bytes` (total size), `sha256`, and `files` (count) for a folder |
| `note` | str | Only with `--note` |
| `notes` | any | Only from the Python API |
| `digest` | str | SHA-256 (hex) of `canonical(record)` |

| Exit code | Meaning |
| --- | --- |
| `0` | `write`: record written. `check`: the digest matches and, with `--files`, every file is unchanged |
| `1` | `check` found problems; also an error the command does not catch, with a Python traceback, such as a record that is not a provenance object |
| `2` | A file could not be read or found, or the record is not JSON, with the message on stderr; or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as no `--run` | Check the command against Commands and options |
| `PATH` alone on stderr, exit code 2 (from `write`) | A `--model`, `--input` or `--output` path does not exist (the `FileNotFoundError` message is the path) | Fix the path; fetch remote stores first |
| `[Errno 2] No such file or directory: 'PATH'`, exit code 2 (from `check`) | The record file does not exist | Fix the path |
| `Expecting value: line 1 column 1 (char 0)` or another JSON message, exit code 2 | The record is not valid JSON | Restore the record from where it was committed or backed up |
| `problem: digest does not match the record`, exit code 1 | The record was edited after `write` | Do not trust it; compare with the published or committed digest |
| `problem: SECTION: PATH changed`, exit code 1 | A model, input or output differs from when the record was written | Find the file the run used, or rerun and write a new record |
| `problem: SECTION: PATH is missing`, exit code 1 | The file is gone, or a relative path is checked from another directory | Run `check` from the directory `write` ran in, or restore the file |
| A traceback with `KeyError` or `AttributeError`, exit code 1 | The JSON is not a provenance record (a list, or items without `path` or `sha256`) | Check that the file is a record from `provenance write` |
| `commit: null` in the record | `--repo` or `--code-repo` is not a git checkout, or git is missing | Point them at the checkouts the run used |

## How it works

1. For each `--model`, `--input` and `--output`, `fingerprint` hashes a file directly, or walks a folder in sorted order, hashes each file, and hashes the manifest of lines `RELATIVE_PATH<TAB>SIZE<TAB>SHA256` joined by newlines.
2. For `--repo` and each `--code-repo`, `code_state` runs `git rev-parse HEAD`, `git rev-parse --abbrev-ref HEAD` and `git status --porcelain --untracked-files=no` (30 s timeout each).
3. `operator` takes `git config user.name` from `--repo`, else the login name; `machine` reads `platform`.
4. `build` assembles the record, sets `finished_utc` from the clock, and adds `digest` = SHA-256 of `canonical(record)`: every field except `digest`, `json.dumps` with sorted keys, separators `,` and `:`, and `ensure_ascii=False`, encoded as UTF-8.
5. `write` saves it with two-space indentation and sorted keys. Because the digest covers the canonical form, the file's layout does not affect it.
6. `check` loads the record, recomputes the digest, and with `--files` refingerprints each recorded path and compares `sha256`.

The commitment scheme (publish a hash now, reveal the record later) is the standard hash commitment; the record holds output hashes and times, so it cannot be guessed from the digest.

## Cost and time

`write` on three tiny synthetic files took 0.15 s wall, mostly Python start-up (measured 2026-10-16, 4-core cloud container). The cost is reading every byte of every listed file once; for a multi-GB zarr store that is the store's size at disk speed, not measured here. It runs on any machine; nothing here needs Modal or a GPU.

## For agents

- **Command:** `python -m kit provenance write OUT.json --run NAME --repo SCROLLS --code-repo VILLA --model CKPT --input INPUT --output MAP.tif --started START`, then `python -m kit provenance check OUT.json --files`. The record file is the machine-readable output.
- **Parse:** `write` prints `PATH: digest HEX`; take HEX, or read `digest` from the file. `check` prints `problem: ...` lines, or a line containing `: ok (digest`. In the record: `code[].commit`, `code[].uncommitted_changes`, `models[].sha256`, `outputs[].sha256`.
- **Rerun:** `write` replaces the file at `path`, and a rerun gets a new `finished_utc` and so a new digest. `check` is read-only and safe to repeat.
- **Success:** Exit code 0; for a trustworthy record also `uncommitted_changes` false in every `code` entry and no null `commit`.
- **Not a pass:** A `check` without `--files` (the files were never looked at); `ok` on a record whose digest was never published or committed (it may have been rewritten); a record with `uncommitted_changes` true; any reading of `ok` as evidence that the output is right or shows ink.
- **Go-ahead:** Publishing a record or a digest is an outward action and needs Chase's yes. A target-scroll run's record stays in Scrolls-private; only its bare digest may ever be published, and only with that yes.
- **Never:** Put a record of a target-scroll run, or its paths and names, in public Scrolls; edit a record and recompute its digest; call a fingerprinted map a reading.

## Tests

```bash
python -m unittest tests.test_provenance -v
```

Six tests on a temporary git repository: the record names the operator without an email, a 40-character commit, no uncommitted changes and the right hashes; a folder's fingerprint changes when a file's content or name changes; an edited record fails the digest; a changed output is caught by `--files`; uncommitted changes are flagged; and the command line writes, checks and catches a changed output with exit codes 0 and 1. They do not cover a missing file, a record checked from another directory, macOS's `chip` field or non-git folders.

## History

- 2026-10-07: first version, with folder fingerprints, the digest, `check --files`, and records written by `scripts/mac-w045.sh` (`1d45c54`).

## Related

- [run-ledger](run-ledger.md): the experiment ledger; `run record` stores command lines and file hashes in an experiment's `run.json`.
- [compute](compute.md): machine time per run, read from these records' start and finish times.
- [mac-w045](mac-w045.md): the Mac script that writes one record and digest per model and segment.
- [verify](verify.md): checks two maps agree, which equal fingerprints only show for byte-identical files.
- [STANDARDS.md](../STANDARDS.md): the Provenance row of the standards.
