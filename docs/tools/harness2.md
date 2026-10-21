# harness2: test agent provenance workflows

Use Harness2's recursion engine to compare bounded, local Scrolls provenance workflows on generated files, keeping the baseline, candidate, controls and adoption evidence.

| Field | Value |
| --- | --- |
| Id | `harness2` |
| Status | Experimental |
| Kind | script folder, workflow |
| Area | Pipeline and agents |
| Run | `python scripts/harness2/run.py` |
| Code | `scripts/harness2/` |
| Tests | `tests/test_harness2.py` |
| Needs | Linux or another POSIX system, Python 3.12 or 3.13, Git, and a separate Harness2 checkout at `1cfe254e8d25b15f37048c3730134686abe60335` |
| Runs on | Local CPU, about 20 to 30 seconds per run (measured below) |
| Network | None during a run; getting the optional checkout once contacts GitHub |
| Writes | Generated fixtures, execution records, Harness2 state and `comparison.json` beneath `--out` only |
| Go-ahead | Not needed: local synthetic checks, no service credentials, model calls or paid compute |
| Released | Source in public Scrolls; no package release, no model weights |
| Checked | 2026-10-21 against commit `249096b` (public `main`, merged into this branch), with Harness2 at the pin above |

## What it does

A provenance record can match its own digest after one of its input files has changed. A
workflow that checks only the record therefore accepts stale or missing inputs. This adapter
runs the real `python -m kit provenance check` on three generated records: one whose files are
unchanged (the positive control), one whose input was edited after the record was written, and
one whose output was deleted (the negative controls). It compares a digest-only baseline
recipe with a recipe that also rechecks the files.

[Harness2](https://github.com/google-research/harness2) (Google Research, version 0.1.0, Apache
2.0) refines the prompts, tools and other software around an agent while model weights stay
fixed. This adapter implements its `BenchmarkAdapter` protocol and calls its real
`core.schedule.run_domain`: proposals, rollouts, composition, selection, reflection, the
per-domain library and resume all run in the pinned upstream code, in both recursion modes
(parallel and sequential). The proposer is deterministic and local, in the manner of the
upstream `demo.py`. No model service is called.

The editable harness is one small JSON recipe. Candidate code, arbitrary commands and changes
to repository instructions are never executed. A passing run shows that the integration and
the fixture contract work. It does not show that a model learned a better workflow, that an
agent became more capable, or that ink detection improved.

## When to use it

- Check a proposed provenance recipe against clean, changed and missing inputs before adopting it.
- Exercise the Harness2 integration, its resume and its tamper checks without API credentials.
- See the baseline, the supplied or proposed recipe and the adopted recipe side by side.

For ordinary file checks, use [provenance](provenance.md) directly. For ink maps, use
[verify](verify.md) and a separately defined scientific comparison. This adapter accepts its
own generated fixtures only; it is not a launcher for training, target-scroll work or
unrestricted coding agents.

## Quick start

From a Scrolls checkout, get the optional source once (it lands in the ignored `work/`):

```bash
git clone --filter=blob:none --sparse https://github.com/google-research/harness2.git work/deps/harness2
git -C work/deps/harness2 sparse-checkout set harness2
git -C work/deps/harness2 checkout 1cfe254e8d25b15f37048c3730134686abe60335
python3.12 scripts/harness2/run.py demo --upstream work/deps/harness2 --out work/harness2-demo --k 1
```

No upstream setup script, rendering extras, model bridge, cloud login or executor is needed,
and the normal Scrolls package keeps its dependencies. Never run the upstream Codex or OpenCode
launchers for this: they turn off their sandbox and allow unrestricted networking.

To evaluate a candidate recipe, save it as `RECIPE.json`:

```json
{"schema": 1, "recheck_files": true}
```

```bash
python3.12 scripts/harness2/run.py compare --upstream work/deps/harness2 --out work/harness2-candidate --candidate RECIPE.json --k 1
```

`compare` evaluates exactly that recipe. It never repairs a failing candidate and then reports
that the submitted recipe passed.

## Checks and controls

The unchanged record is the positive control; the edited input and the deleted output are the
negative controls. Before any rollout the engine asks kit itself to confirm the design: every
record matches its digest, and the file recheck flags exactly the edited and the deleted file.
The digest-only baseline is kept in every run, and a run whose baseline passes every control is
reported as `controls-invalid`, because then the controls could not fail. Selection sees only
the task text and the execution observations; the expected verdicts live in
`judge/expected.json`, outside every context Harness2 builds, and are read only by the judge
after selection.

Measured on 2026-10-20 (pinned core, Python 3.12 and 3.13): the baseline gets 1 of 3 controls
right (it accepts all three); the adopted recipe gets 3 of 3 in both modes for `demo` and for
`compare` with `recheck_files: true`; `compare` with `recheck_files: false` keeps that recipe,
gets 1 of 3 and exits 1.

Claim label: None. This is a fixture-only exercise of the integration, not evidence of learned
agent improvement or of accuracy on any scroll.

## Commands and options

### `python scripts/harness2/run.py`

```bash
python3.12 scripts/harness2/run.py {demo,compare} --upstream CHECKOUT --out RUN_DIR [--k {1,2}] [--candidate RECIPE.json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `demo` | required choice | Run Harness2's recursion with the deterministic local proposer |
| `compare` | required choice | Evaluate the exact supplied candidate recipe against the baseline |
| `--upstream CHECKOUT` | required | Separate checkout at the supported Harness2 commit |
| `--out RUN_DIR` | required | New directory, or the directory of the same finished run to resume |
| `--candidate RECIPE.json` | required for `compare` | Strict recipe; no paths, commands or answer fields |
| `--k {1,2}` | `1` | Harness2 recursion budget; 2 adds a selection session per mode |
| `-h`, `--help` | false | Show help without running anything |

### Environment variables

None are read. The engine and the worker start with a clean environment (`PATH` set to the
system default and `LANG=C.UTF-8`), and the isolated interpreter ignores `PYTHON*` variables.
The tests read `SCROLLS_HARNESS2_UPSTREAM` to find a checkout; see Tests.

## Inputs

The candidate is a JSON object of at most 1024 bytes with exactly `schema: 1` and a Boolean
`recheck_files`; duplicate keys, non-finite numbers and any other field are refused. The engine
generates its own fixtures (fixture version 1). No scan, checkpoint, label, ink map or user
document is an input.

The upstream checkout must be at the pinned commit with its `harness2/` package byte for byte
as committed (blob hashes are compared), no extra files such as `__pycache__`, no `.env` (the
upstream configuration loads one automatically) and no Python modules at its root. The run
identity in `manifest.json` binds the action, `k`, the candidate, the output path, the fixture
version, the Python version, the upstream file hashes, the Scrolls commit and the hashes of
`kit/` and `scripts/harness2/`. Any change needs a new `--out`.

## Outputs

Everything goes under `--out`:

- `manifest.json`: the run identity above.
- `comparison.json`: `status`, `claim`, `recipes` (baseline, candidate, adopted per mode),
  `summary` (controls right per arm), `controls` (one row per fixture with the expected
  verdict, the baseline verdicts and the adopted verdict per mode), `harness2` (pinned commit,
  modes, per-task status and library sizes), `new_executions`, `new_proposer_calls` and
  `wall_seconds`.
- `receipt.json`: SHA-256 of every file, written only after the engine finishes; a resume
  requires it to match.
- `engine.log`, `fixtures/`, `judge/expected.json`, `base/recipe.json`, `executions/` (one
  directory per rollout with `answer.txt`, `trajectory.md`, `worker.out` and a hashed
  `run.json`), and Harness2's own `runs/` and `library/` trees.

The command prints a JSON summary: `out`, `resumed`, `status`, `comparison`, `new_executions`
and `new_proposer_calls`.

| Status | Meaning |
| --- | --- |
| `ok` | Baseline fails a negative control; every adopted recipe passes all three controls (for `compare`, the adopted recipe is the supplied one) |
| `candidate-failed` | `compare` ran the supplied recipe exactly and it got a control wrong |
| `adopted-failed` | `demo` adopted a recipe that got a control wrong |
| `controls-invalid` | The baseline passed every control, so the controls could not fail |
| `incomplete` | A Harness2 task or selection failed, a judgment is missing, or an adopted recipe is not the supplied one |
| `limit-exceeded` | More than 48 executions or 64 proposer calls in one invocation |

| Exit code | Meaning |
| --- | --- |
| 0 | Run finished with status `ok` |
| 1 | Run finished with any other status; read `comparison.json` |
| 2 | Refused input or output, or the engine failed; nothing new is trusted |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `this optional integration requires POSIX and Python >=3.12,<3.14` | Harness2 0.1.0 declares Python 3.12 or 3.13 on POSIX | Run with `python3.12` or `python3.13` on Linux or macOS |
| `--upstream must be a checkout at` the pin | Wrong revision, or not a Git checkout | Check out `1cfe254e8d25b15f37048c3730134686abe60335` |
| `upstream source differs from pin:` | A file in `harness2/` or `pyproject.toml` was edited | Restore it with `git checkout`, or use a fresh checkout |
| `upstream package has missing or extra files (including bytecode)` | Extra files, often `__pycache__` from running upstream code | Delete them or use a fresh checkout |
| `unsupported upstream file type` | The pinned tree holds a link or submodule where a file was expected | Use an unmodified checkout of the pin |
| `upstream .env is not allowed (Harness2 imports it automatically)` | Upstream configuration would load it | Remove the `.env` from the checkout |
| `upstream root import shadow is not allowed:` | A Python module sits at the checkout root | Remove it |
| `recipe must contain exactly schema: 1 and recheck_files: boolean` | Missing, extra or wrongly typed field | Write exactly the two fields |
| `recipe exceeds 1024 bytes`, `duplicate JSON key:`, `non-finite JSON value:` | Malformed candidate | Fix the JSON |
| `expected a regular file of at most` N bytes | Candidate or saved file is too big or not a regular file | Pass a small regular file |
| `parent traversal is not allowed:`, `symlink is not allowed:` | A path uses `..` or a link | Pass a plain absolute or relative path |
| `output and upstream checkout must not overlap` | `--out` inside the checkout or the reverse | Keep them apart |
| `output cannot replace the repository or an ancestor`, `outputs inside this repository must be under work/` | `--out` would mix with tracked files | Use `work/...` or a folder outside the repository |
| `output is not a directory`, `output directory is not empty and holds no run; use a fresh --out` | `--out` names a file or someone else's folder | Choose a new directory |
| `existing output provenance is incompatible; use a fresh --out` | Action, `k`, candidate, code, Python or upstream changed since that run | Use a new `--out` and keep the old evidence |
| `an earlier run in this output did not finish; use a fresh --out` | No receipt: the engine was interrupted or failed | Inspect `engine.log`; start again in a new directory |
| `existing output artifacts changed or are incomplete; use a fresh --out` | A file changed after the receipt was written | Treat the old run as tampered; start again |
| `run exceeds the file-count or total-output limit` | More than 6000 files or 32 MB under `--out` | Use a fresh `--out` |
| `local integration exceeded its` 300 `second wall limit` | The engine hung or the machine is overloaded | Retry in a new directory when the machine is idle |
| `integration failed (exit` N`); see` `engine.log` | The engine stopped; its log names the cause, such as the messages below | Read `engine.log` |
| `loaded upstream module differs from the pin:` | A module changed between the check and the import | Use a fresh checkout |
| `adapter does not satisfy the pinned BenchmarkAdapter protocol` | Adapter and upstream API disagree | Do not change the pin without reviewing the adapter |
| `generated fixtures differ from fixture version 1; use a fresh --out`, `judge expectations differ from fixture version 1; use a fresh --out`, `baseline recipe changed; use a fresh --out` | Saved inputs changed | Start again in a new directory |
| `fixture controls do not behave as designed in kit provenance (CONTROL)` | kit's provenance check no longer flags the edited or deleted file | Fix kit before trusting any workflow result |
| `the Harness2 engine writes only beneath --out, not` PATH | Code tried to write elsewhere; the run stops | Report it; nothing outside `--out` was written |
| `the Harness2 engine refuses network use and other processes (EVENT)`, `the Harness2 engine launches only the fixed provenance worker` | Code tried to open a socket or start another program | Report it; the integration never needs either |
| `the synthetic provenance worker cannot use network or launch processes`, `the synthetic provenance worker cannot write files` | The worker's own guard fired | Report it |
| `fixed worker requires RECORD and true|false`, `usage: engine.py UPSTREAM OUT (run.py starts this)` | A helper was started by hand | Use `run.py` |
| `harness must hold only recipe.json, found`, `unknown task`, `unsafe run id` | A proposal or saved state broke the adapter's fixed layout; the rollout is recorded as failed | Read `engine.log`; the status will not be `ok` |
| `worker failed with exit`, `worker output exceeded its byte limit` | kit's check crashed or printed more than 16384 bytes | Read `worker.out` in the execution directory |
| `execution limit reached`, `local proposer call limit reached` | More than 48 executions or 64 proposer calls | Status `limit-exceeded`; report it, the counts are fixed |

## How it works

`run.py` validates the arguments and the candidate, hashes the pinned upstream package and the
Scrolls code, writes or checks `manifest.json`, then starts `engine.py` in an isolated
interpreter (`-I -S -B`, clean environment, its own process group, 300 second wall limit).

`engine.py` installs an audit hook, then imports the upstream package by file location, so the
checkout never enters `sys.path`, and compares every loaded upstream module with the hashes in
the manifest. The hook refuses sockets, any process except the fixed worker command, and writes
outside `--out`. It guards this adapter's own code path and the pinned core; it is not a
security sandbox, and the fixed allowlist executor is the real boundary.

The adapter's editable surface is the single file `recipe.json`, validated with the same strict
parser as the candidate. Upstream prompt templates exist only for its OpenCode and Codex
surfaces, so this one-file surface borrows the OpenCode prompt family; the deterministic
proposer ignores that wording, and a model-backed proposer would need prompts written for this
surface. The executor reads the recipe and runs `worker.py`, which calls kit's real provenance
check in-process (with `--files` when `recheck_files` is true) under its own audit hook that
also refuses writes. Exit 0 becomes `verdict: accept` and exit 1 `verdict: reject`; each
rollout's files are hashed into its `run.json`, and Harness2's resume uses `artifacts_intact`
to refuse changed executions.

The deterministic proposer, in `demo`: an improvement proposal requests the recheck only when
the task text requires verified files and a base trajectory shows `files rechecked: no`; a
domain proposal applies a lesson already in the Harness2 library; a composition adopts a pool
candidate whose rollout shows `files rechecked: yes`. Selection (at `--k 2`) prefers a candidate
whose observation shows the recheck. Reflection writes a library lesson when the adopted recipe
differs from the baseline. In `compare` every proposal writes the supplied candidate unchanged.
After `run_domain` returns, Harness2's `core.judge` scores the adopted runs, and the baseline
runs are scored the same way, against `judge/expected.json`.

The upstream core is Apache 2.0 and is used through its API, not vendored. Its benchmark
runners, their datasets and their licenses are not used. Upstream results on professional-work
benchmarks are not Scrolls results.

## Cost and time

No paid service, model call or GPU. Measured on 2026-10-20 in a shared 4-core Linux container
under heavy load: `--k 1` makes 21 executions and 24 proposer calls in about 20 seconds; `--k 2`
makes 42 executions and 48 proposer calls in about 30 seconds; a resume makes none. The fixed
limits are 48 executions and 64 proposer calls per invocation and 300 seconds of wall time.
Harness2's call counters are not a cost bound for any model-backed use. On 2026-10-21, with
the shared disk under heavy I/O pressure, the 13 pinned-core tests took about 10 minutes of wall
time for about 15 seconds of CPU (45 to 70 seconds once the load eased), so a single run can
near the 300 second wall limit on a stalled disk; a run that hits it exits 2 and writes no receipt.

## For agents

- **Command:** `python3.12 scripts/harness2/run.py compare --upstream CHECKOUT --out RUN_DIR --candidate RECIPE.json --k 1`.
- **Parse:** the printed JSON for `status`, then `comparison.json`: `recipes`, `summary` and
  the per-fixture `controls` rows for the baseline and each mode.
- **Rerun:** the same command and `--out` resumes only a finished, intact run with the same
  identity; anything else needs a new `--out`, and the old directory stays as evidence.
- **Success:** exit 0 with `status` `ok`: the supplied recipe passed all three controls in both
  modes and the baseline failed at least one.
- **Not a pass:** exit 1 with any other status, exit 2, files that merely exist, a completed
  recursion, or a different recipe being adopted.
- **Go-ahead:** none needed; no external service is called.
- **Never:** treat a result as scientific accuracy evidence, run the upstream launchers,
  execute candidate code, or put research targets or scroll data in the fixtures.

## Tests

```bash
python -m unittest tests.test_harness2 -v
SCROLLS_HARNESS2_UPSTREAM=work/deps/harness2 python3.12 -m unittest tests.test_harness2 -v
```

Without a checkout, nine local checks run (recipe strictness, path and output refusals, the
fixture controls in kit, both audit hooks, and that normal `kit` never imports Harness2) and the
four pinned-core checks skip. With `SCROLLS_HARNESS2_UPSTREAM` (or `work/deps/harness2`) at the
pin, on Python 3.12 or 3.13, the pinned-core checks run the real upstream: the `demo` controls
in both modes, resume with no new work, refusal of a different identity, a tampered artifact and
an unfinished run, refusal of an edited, byte-compiled or `.env` upstream, the bad candidate
evaluated exactly, and a `--k 2` comparison with selection sessions. All 13 passed on Python
3.12 and 3.13 on 2026-10-20, and again on 2026-10-21 after public `main` (`249096b`) was merged in.

## History

- 2026-10-20: optional adapter on branch `claude/harness2`, finishing checkpoint `e042556` (engine, deterministic proposer, judge, tests and this page), reviewed against Harness2 at `1cfe254e8d25b15f37048c3730134686abe60335`.
- 2026-10-21: recovery bundle and manifest hashes rechecked; public `main` `249096b` merged in; all 13 tests pass again on Python 3.12 and 3.13 with a fresh clone of the pin.

## Related

- [Provenance](provenance.md): the record and file checks exercised here.
- [Tool interface standard](../TOOL-DOCS.md): headless interfaces and evidence.
- [Pinned Harness2 source](https://github.com/google-research/harness2/tree/1cfe254e8d25b15f37048c3730134686abe60335).
- [Harness2 adapter protocol](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/harness2/core/spec.py).
- [Harness2 experiments and limitations](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/docs/EXPERIMENTS.md).
