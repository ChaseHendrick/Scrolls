# runrecord: one provenance record per run, with the causal links it ran under

Writes a run record (a kit provenance record with a token, the tool, argv, settings digest, exit code and causal link lines) for any run, so kit causal can trace results back to the run, its code, inputs, control and decision.

| Field | Value |
| --- | --- |
| Id | `runrecord` |
| Status | Experimental |
| Kind | kit command, kit module |
| Area | Records and provenance |
| Run | `python -m kit runrecord start`, `python -m kit runrecord finish`, `python -m kit runrecord wrap`, `python -m kit runrecord adopt`, `python -m kit runrecord check`, `python -m kit.runrecord`, `from kit import runrecord`; by default inside every kit run local wrapper ([run-local](run-local.md)) |
| Code | `kit/runrecord.py`, `kit/cli.py` (`build_parser`, `_local_record_start`, `_local_record_finish`) |
| Tests | `tests/test_runrecord.py`, `tests/test_causal.py`, `tests/test_causal_shared.py`, `tests/test_localcost.py` |
| Needs | Python 3.10 or newer, standard library only, plus `kit/causal.py` (the link grammar) and `kit/provenance.py` (fingerprints and the record format); git for the code commit |
| Runs on | Any CPU. Its own overhead is the input and output fingerprints: up to `HASH_BUDGET` (256 MB) hashed per record, the rest listed by reference; the 11 tests run in about 4.5 s (measured 2026-10-21, 4-core Intel Xeon at 2.80 GHz cloud container) |
| Network | None |
| Writes | `work/causal/runs/TOKEN.open.json` (start), `work/causal/runs/TOKEN.json` (finish, wrap), `docs/causal/runs/TOKEN.json` (adopt). Refuses frozen paths (kit causal rule E13) |
| Go-ahead | Not needed. Adopting a record here needs `public` true, from a public-data run |
| Released | Public `main` from the change that adds it (21 Oct 2026). `kit/runrecord.py` is shared code, byte-identical in Scrolls-private; `tests/test_causal_shared.py` pins its bytes in both |
| Checked | 2026-10-21 against commit `3bd77be` plus this tool |

## What it does

A run record says what ran, under which links, from which code, on which inputs, producing which outputs. It is a kit provenance record (schema 1: run, operator, machine, start and finish times, code with its commit and dirty flag, inputs, outputs, note) plus `kind` "run", `runrecord_schema` 1, `token` (YYYYMMDDTHHMMSSZ with an optional slug, also the file name), `tool`, `argv`, `settings_digest`, `exit_code`, `public`, `causal` (link lines in kit causal's grammar: the decision, spec, preregistration, control and inputs the run was launched under), `by_reference` (inputs too large or remote to hash), `parent` (the token of the run it ran inside) and `env` (Python, platform, torch when importable). A digest covers all of it.

`start` validates the links (a reference that does not resolve, or, with `--public`, any private or local reference is refused) and writes an open record; `finish` fingerprints the outputs and writes the finished record; `wrap` does both around a command and writes the record even when the command fails; `adopt` copies a finished record into `docs/causal/runs/`, where [causal](causal.md) reads it; `check` verifies records. `kit run local` writes a run record by default ([run-local](run-local.md)), and Python runners use `runrecord.run(...)` as a context manager.

In this repository every adopted record must be public (`public` true): `adopt` refuses any other, `kit run local` marks its records public and refuses private or local links, and `wrap` and `start` need `--public`.

A run record does not say a result is right, and it never shows that a change caused a gain: that needs a matched null arm. Its outputs are files, not readings; an ink map in its outputs is still model output.

Status is Experimental: the format is fixed (schema 1), but no record has been adopted here yet.

## When to use it

- Any run whose result will be recorded: wrap it (`wrap --public`, `kit run local`, or `runrecord.run(..., public=True)` in a runner), then adopt the record in the same commit as the result (`python -m kit causal add result --from-run TOKEN --write` adopts it for you).
- To add causal lines to an existing provenance record: `runrecord.attach(record, lines)` recomputes its digest.

Do not use it:

- to hash files without a run: use [provenance](provenance.md);
- to log cost: that is [run-local](run-local.md) and the Modal ledger ([modal-row](modal-row.md));
- to check what a result cites: use [causal](causal.md).

## Quick start

```bash
python -m kit runrecord wrap --public --tool "kit auc" --causal "prereg none:development" -- python3 -c "print('ok')"
python -m kit runrecord adopt TOKEN
python -m kit runrecord check docs/causal/runs/TOKEN.json
```

`TOKEN` is what `wrap` printed on stderr (`work/causal/runs/TOKEN.json DIGEST`). Add `--root DIR` to work in another checkout. On a synthetic repository (given with `--root`) on 2026-10-21 it printed:

```
ok
work/causal/runs/20261021T022042Z.json 20a3fcd678228a0cd3e55c7dc2d769b67a2a48623b628e51b03373eebcedd02e
.../docs/causal/runs/20261021T022042Z.json
ok   .../docs/causal/runs/20261021T022042Z.json
```

It worked when `check` exits 0.

## Checks and controls

Every record check can fail: `check` rejects a record whose digest does not match (tested by editing one field), a token that is not the file name, a wrong schema, and causal lines that do not parse. `start` refuses links that do not resolve, local paths, and with `--public` any approval, freeze, Modal app or private reference; `adopt` refuses a non-public record in a public repository. `tests/test_runrecord.py` holds each of these as a failing case.

Claim label: None (a run record makes no claim; it records what ran).

## Commands and options

### `python -m kit runrecord start`

```
usage: python -m kit runrecord start [-h] --tool TOOL [--token TOKEN]
                                     [--causal LINE] [--input PATH]
                                     [--by-reference URL[@sha256:HEX]]
                                     [--settings SETTINGS] [--public]
                                     [--note NOTE] [--root ROOT] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--tool TOOL` | required | what runs, such as 'kit auc' or 'modal_job.py' |
| `--token TOKEN` | none | the run token (default: now, YYYYMMDDTHHMMSSZ) |
| `--causal LINE` | none | a link line (repeatable) |
| `--input PATH` | none | an input to fingerprint (repeatable) |
| `--by-reference URL[@sha256:HEX]` | none | an input too large or too remote to hash (repeatable) |
| `--settings SETTINGS` | none | the run's settings as JSON; the record keeps their digest |
| `--public` | off | a public-data run: refuse private and local references |
| `--note NOTE` | none | a note kept in the record |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print the open record as JSON |

### `python -m kit runrecord finish`

```
usage: python -m kit runrecord finish [-h] [--output PATH] [--app AP]
                                      [--exit-code EXIT_CODE] [--root ROOT]
                                      [--json]
                                      token
```

| Option | Default | Meaning |
| --- | --- | --- |
| `token` | required | the token start printed |
| `--output PATH` | none | an output (repeatable) |
| `--app AP` | none | a Modal app the run started (repeatable) |
| `--exit-code EXIT_CODE` | `0` | the run's exit code (default 0) |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print the record as JSON |

### `python -m kit runrecord wrap`

```
usage: python -m kit runrecord wrap [-h] --tool TOOL [--token TOKEN]
                                    [--causal LINE] [--input PATH]
                                    [--by-reference URL[@sha256:HEX]]
                                    [--settings SETTINGS] [--public]
                                    [--note NOTE] [--output PATH]
                                    [--root ROOT] [--json]
                                    ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--tool TOOL` | required | what runs, such as 'kit auc' or 'modal_job.py' |
| `--token TOKEN` | none | the run token (default: now, YYYYMMDDTHHMMSSZ) |
| `--causal LINE` | none | a link line (repeatable) |
| `--input PATH` | none | an input to fingerprint (repeatable) |
| `--by-reference URL[@sha256:HEX]` | none | an input too large or too remote to hash (repeatable) |
| `--settings SETTINGS` | none | the run's settings as JSON; the record keeps their digest |
| `--public` | off | a public-data run: refuse private and local references |
| `--note NOTE` | none | a note kept in the record |
| `--output PATH` | none | an output (repeatable) |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print the record as JSON after the command |
| `command` | none | -- COMMAND [ARGS] |

### `python -m kit runrecord adopt`

```
usage: python -m kit runrecord adopt [-h] [--root ROOT] [--json] token
```

| Option | Default | Meaning |
| --- | --- | --- |
| `token` | required | the record's token |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print JSON |

### `python -m kit runrecord check`

```
usage: python -m kit runrecord check [-h] [--json] paths [paths ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `paths` | required | run record files |
| `--json` | off | print JSON |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_RUN_TOKEN` | unset | the token of the enclosing run; `wrap` and `kit run local` set it for their command, and `start` records it as `parent` |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `RunRecordError()` | an exception (a ValueError) | nothing | The CLI prints `kit runrecord: MESSAGE` and exits 1 |
| `token(slug=None, now=None)` | str, the run token | `RunRecordError` for a bad slug | UTC time |
| `attach(record, lines)` | dict, a new record with `causal` added and a new digest | `CausalError` for a bad line | Use on provenance records (and training records where a repository has them) |
| `start(root=ROOT, tool=None, run_token=None, causal_lines=(), inputs=(), by_reference=(), settings=None, public=False, argv=None, note=None)` | dict, the open record | `RunRecordError`, `CausalError` | Writes work/causal/runs/TOKEN.open.json |
| `finish(root=ROOT, run_token=None, outputs=(), apps=(), exit_code=0)` | dict, the finished record | `RunRecordError` | Writes work/causal/runs/TOKEN.json, removes the open file |
| `adopt(root=ROOT, run_token=None, public=None)` | Path of docs/causal/runs/TOKEN.json | `RunRecordError` | Checks the record first; in a repository without `kit/causal_ext.py` (this one) it refuses a record whose `public` is not true |
| `check_record(record, name=None)` | list of problems (empty when fine) | nothing | Digest, schema, token, lines |
| `Run(tool, argv=None, causal_lines=(), inputs=(), public=False, root=ROOT, run_token=None, settings=None, by_reference=(), note=None)` | a context manager with `.output(path)`, `.app(app_id)`, `.record` | what `start` and `finish` raise | Writes the record on exit, exit_code 1 when the block raised |
| `run(tool, argv=None, causal_lines=(), inputs=(), public=False, **kw)` | a `Run` | nothing | The usual entry for runners |
| `add_arguments(p)` | None | nothing | Adds the actions to an argparse parser |
| `cli(args)` | int exit code | nothing (prints the error, returns 1) | The CLI entry `kit/cli.py` defers to |
| `main(argv=None)` | int exit code | argparse exits 2 on usage errors | `python -m kit.runrecord` |

## Inputs

The command or block that runs, the `--causal` link lines (kit causal's grammar, see [docs/causal/README.md](../causal/README.md)), `--input` and `--output` paths (files or folders, fingerprinted with kit provenance up to `HASH_BUDGET`, 256 MB in all), `--by-reference URL[@sha256:HEX]` for inputs too large or remote to hash, `--settings` JSON (only its digest is kept), and `KIT_RUN_TOKEN` (the enclosing run).

## Outputs

`start` prints the token; `finish` and `wrap` print `work/causal/runs/TOKEN.json DIGEST` (wrap on stderr, after the command's own output); `adopt` prints the adopted path; `check` prints `ok` or `FAIL` per file. `--json` prints the record.

| Field | Type | Meaning |
| --- | --- | --- |
| `kind`, `runrecord_schema` | str, int | "run", 1 |
| `token`, `tool`, `argv` | str, str, list | what ran |
| `settings_digest` | str or null | sha256 of the canonical settings JSON |
| `exit_code` | int | the run's exit code (1 when a Python block raised) |
| `public` | bool | true only for a public-data run |
| `causal` | list of str | link lines |
| `inputs`, `outputs` | list | kit provenance fingerprints (path, kind, sha256, bytes) |
| `by_reference` | list | {url, sha256 or null, why} |
| `parent`, `env` | str or null, object | enclosing run token; Python, platform, torch |
| `code`, `started_utc`, `finished_utc`, `machine`, `operator` | mixed | kit provenance fields |
| `digest` | str | sha256 of the canonical record without `digest` |

| Exit code | Meaning |
| --- | --- |
| `0` | the record was written, adopted or checked clean |
| `1` | refused (`kit runrecord: MESSAGE`), or `check` found a problem |
| `2` | usage, or `wrap` without a command |
| other | `wrap` returns the command's own exit code |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `a run record needs --tool` | `start` without a tool | Name what runs with `--tool` |
| `is not YYYYMMDDTHHMMSSZ with an optional -slug` | `--token` has the wrong shape | Leave it out (now is used) or fix it |
| `a run record for token` | The token already has a record | Use a new token |
| `no open run record for token` | `finish` before `start`, or a wrong token | Start the run first |
| `no finished run record for token` | `adopt` before `finish` | Finish the run first |
| `refused in a public repository: the record is not public` | A non-public record in this repository | Only public-data runs, started with `--public` (or by `kit run local` here, which marks its records public), are adopted |
| `kit runrecord:` | The prefix of every refused request | Read the rest of the line |
| `must be lowercase letters, digits and hyphens` | A token slug with other characters | Use a slug such as `auc-w00` |
| `is a local path; link something tracked` | A causal line names work/, experiments/ or an absolute path | Commit the file and link it |
| `does not resolve` | A causal line names a node the repository lacks | Fix the reference |
| `is not tracked` | A causal line names an untracked path | Commit it first |
| `by-reference pin must be @sha256:<64 hex>:` | `--by-reference URL@sha256:...` with a bad pin | Give 64 hex |
| `is not JSON:` | An open record file is corrupt | Start a new run |
| `is not a Modal app id (ap-...)` | `--app` is not an app id | Copy the app id from Modal |
| `refused with --public: a Modal app id is a private reference` | Modal app ids stay private | Record public runs without `--app` |
| `--settings is not JSON:` | `--settings` does not parse | Pass a JSON object |
| `is a private or local reference` | With `--public`, a private or local link | Remove it, or record without `--public` |
| `cannot be read:` | An input or output path is unreadable | Check the path |
| `cannot be fingerprinted:` | kit provenance could not hash it | Check permissions, or list it with `--by-reference` |
| `kit runrecord wrap: cannot run` | The command could not start (exit 127) | Check the command; the record is still written |
| `run record refused:` | `kit run local` could not start its run record (a `--causal` line that does not parse or resolve, or here a private or local reference); the command did not run, exit 2 | Fix the line, or pass `--no-record` |
| `: no run record:` | `kit run local` could not start its record for a reason other than a bad link (a write failure); the command still runs, without a record | Check that `work/causal/runs/` is writable |
| `: the run record was not finished:` | `kit run local` ran the command but could not finish its record; the exit code is the command's | Finish it by hand with `python -m kit runrecord finish TOKEN` |
| `pin differs from its live freeze` | A prereg pin differs from the hash its live freeze holds (only in a repository that keeps a freeze registry) | Pin the frozen version |

## How it works

1. `start` parses each link with `causal.parse`, refuses local paths (and with `--public` private references), then (only when a line names a node or a path) loads the kit causal graph to check that each reference resolves and, where a freeze registry exists, that a prereg pin matches its live freeze. It fingerprints the inputs and writes the open record with `parent` from `KIT_RUN_TOKEN` and `env`.
2. `finish` fingerprints the outputs with the budget left, adds `run ap-...` per app, builds a kit provenance record (code commit and dirty flag, machine, operator, times), adds the run fields and writes the digest.
3. `adopt` re-checks the record and copies it into `docs/causal/runs/`, refusing a non-public record in a public repository (one without `kit/causal_ext.py`, such as this one).
4. `wrap` sets `KIT_RUN_TOKEN` for its command, so a run record written inside it records this run as its parent.

Constants: `SCHEMA = 1`, `WORK_RUNS = "work/causal/runs"`, `ADOPTED = "docs/causal/runs"`, `HASH_BUDGET = 256 MB`, `PARENT_ENV = "KIT_RUN_TOKEN"`.

## Cost and time

Local CPU, under a second plus hashing time for inputs and outputs (at most 256 MB per record). Measured 2026-10-21: the 11 tests run in about 4.5 s on a 4-core Intel Xeon at 2.80 GHz cloud container. No compute is rented.

## For agents

- **Command:** `python -m kit runrecord wrap --public --tool TOOL --causal LINE -- COMMAND`, then `python -m kit runrecord adopt TOKEN`; or in Python `with runrecord.run("TOOL", causal_lines=[...], public=True) as r: ...; r.output(path)`. `--json` prints the record.
- **Parse:** the token (stdout of `start`, or the file name), `digest`, `exit_code`, `causal`, `outputs[].sha256`.
- **Rerun:** `start` refuses a token that already has a record; a rerun gets a new token. `adopt` overwrites the adopted copy with the same bytes.
- **Success:** exit 0 (`wrap` returns the command's code); `check` prints `ok`.
- **Not a pass:** a record with `exit_code` other than 0; a record with no `causal` lines or no prereg line (kit causal flags it, rule A10); a record whose code shows uncommitted changes.
- **Go-ahead:** Nothing.
- **Never:** edit a record after it is written (its digest breaks); adopt a non-public record here; put Modal app ids, approvals or other private references in a record adopted here; edit `kit/runrecord.py` here without landing the same bytes in Scrolls-private.

## Tests

`python -m unittest tests.test_runrecord -v` (byte-identical in Scrolls-private): tokens, attach, start, finish, adopt and check, the public refusals, unresolved links, the context manager on an exception, tampering, wrap with a failing command, the parent and env fields, and `kit run local` writing (and with `--adopt`, adopting) a record by default, refusing a bad `--causal` before the command runs, and writing none with `--no-record`. Not covered: torch version capture (it needs torch installed) and the live-freeze pin refusal (Scrolls-private tests it; this repository has no freeze registry).

## History

- 2026-10-21: Added to public Scrolls: run records with `parent` and `env` fields and `KIT_RUN_TOKEN`, and `kit run local` writing a public run record by default (this change, on top of `3bd77be`)

## Related

- [causal](causal.md): reads adopted run records and checks that new results cite them.
- [docs/causal/README.md](../causal/README.md): the link grammar the `causal` lines use.
- [run-local](run-local.md): the local-run wrapper that writes a record by default.
- [provenance](provenance.md): the record format a run record extends.
