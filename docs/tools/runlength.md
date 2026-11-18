# runlength: how long a CPU job takes on a cloud CPU flavor

`python -m kit.runlength cpu` turns one task timed in a 4-core cloud container into the wall time and a timeout for a job on a measured cloud CPU flavor, from slowdown tables that [cpudiag](cpudiag.md) measured, instead of dividing core-seconds by vCPUs.

| Field | Value |
| --- | --- |
| Id | `runlength` |
| Status | Current |
| Kind | kit entry point, kit module |
| Area | Compute and cost |
| Run | `python -m kit.runlength cpu`, `from kit import runlength` |
| Code | `kit/runlength.py` |
| Tests | `tests/test_runlength.py` |
| Needs | Python 3.10 or newer; standard library only |
| Runs on | Any machine; instant |
| Network | None |
| Writes | Nothing (prints only) |
| Go-ahead | Not needed |
| Released | Public `main` from the PR that adds this page (2026-11-18), the CPU estimate only, with [cpudiag](cpudiag.md) |
| Checked | 2026-11-18 against commit `c2cb575` |

## What it does

A task timed in a small container does not scale to a big CPU machine by dividing its core-seconds by the machine's vCPUs. On Hugging Face `cpu-performance` (32 vCPU, which are 16 cores with 2 threads each on 2 NUMA nodes) one process runs as fast as in a 4-core container, but memory bandwidth saturates near 68 GB/s from about 8 processes, and two processes share each core past 16. So every worker slows down as more run at once, and by how much depends on the work.

`CPU_FLAVORS` holds, per flavor, the measured seconds per task per worker over the same task in the container, at 1, 8, 16 and 32 workers, for three kinds of work: `stream` (memory-bandwidth bound, the worst case for array-streaming numpy), `scrollsim2` (that simulator's render) and `compute` (cache-resident numpy math). `cpu_slowdown` interpolates between the measured worker counts and time-shares past the vCPUs; the default kind `max` takes the largest of the three, so a timeout sized from it covers unknown work. `cpu_wall_s` gives the wall time, `cpu_best_workers` the worker count with the most tasks per second, and `cap_minutes` a timeout of about 1.5 times the estimate plus 5 minutes.

What it does not do: it knows only the flavors in its table (today `cpu-performance`); it does not time anything itself (time the task with the script's own probe, and a new flavor with `python -m kit.cpudiag run`); and it estimates GPU jobs not at all.

## When to use it

- Before a CPU job on a measured flavor: to set its worker count and its timeout from a container timing of one task.
- To see whether fewer workers would finish sooner (memory-bound work often does).

Do not use it:

- For a flavor not in the table: measure it with [cpudiag](cpudiag.md) and add a row.
- For GPU jobs.

## Quick start

```bash
python -m kit.runlength cpu --task-s 4.33 --tasks 2458 --kind scrollsim2
python -m kit.runlength cpu --task-s 4.33 --tasks 2458 --kind scrollsim2 --workers 32
```

- `--task-s`: seconds per task timed in a 4-core cloud container; `--tasks`: how many tasks the job runs.

It printed (2026-11-18):

```
2458 tasks of 4.33 s on cpu-performance with 8 workers (scrollsim2): about 22.2 min (slowdown 1.0 x per task; best workers 8); cap --timeout-min 39
2458 tasks of 4.33 s on cpu-performance with 32 workers (scrollsim2): about 26.7 min (slowdown 4.8 x per task; best workers 8); cap --timeout-min 46
```

A real 32-worker pilot of that render took 25.2 min for its level-0 blocks (1,512 s). It worked when the exit code is 0 and the line names a worker count and a cap.

## Checks and controls

- The `stream` and `compute` rows are recomputed in the tests from the committed evidence (the first diagnostic job's seconds per process over the container's P=1 seconds), to within 0.06.
- The `scrollsim2` row predicts the measured 32-worker pilot within 15 percent (26.7 min predicted, 25.2 measured), and the old core-seconds-over-vCPU guess is more than three times too short; the test fails if the row drifts to either.
- A bandwidth-bound job of the triad, sized with the default `max` kind, fits its cap at 8, 16 and 32 workers; sized with the `scrollsim2` row it would not (the test checks both).

Claim label: Sourced fact for the measured timings in `docs/evidence/2026-11-18-hf-cpu-diag`; Interpretation for the slowdown table built from two diagnostic jobs and for any estimate it gives.

## Commands and options

### `python -m kit.runlength cpu`

```
usage: python -m kit.runlength cpu [-h] [--flavor FLAVOR] --task-s TASK_S
                                   --tasks TASKS [--workers WORKERS]
                                   [--kind {max,stream,scrollsim2,compute}]
                                   [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--flavor FLAVOR` | `cpu-performance` | the cloud CPU flavor; it must be in `CPU_FLAVORS` |
| `--task-s TASK_S` | required | seconds per task, timed in a 4-core cloud container |
| `--tasks TASKS` | required | tasks in the job |
| `--workers WORKERS` | the measured best for `--kind` | parallel worker processes |
| `--kind {max,stream,scrollsim2,compute}` | `max` | `max` (the largest slowdown of the measured kinds: safe for unknown work), `stream` (memory bandwidth bound), `scrollsim2` (its render) or `compute` (cache-resident math) |
| `--json` | off | print the result as JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `cpu_slowdown(flavor, workers, kind='max')` | float or None | Nothing | Seconds per task per worker over the container's, interpolated between measured worker counts, flat below them, time-shared above; None for an unmeasured flavor or kind |
| `cpu_wall_s(task_s, tasks, flavor, workers, kind='max')` | float or None | Nothing | ceil(tasks / workers) x task_s x the slowdown |
| `cpu_best_workers(flavor, kind='max')` | int or None | Nothing | The measured worker count with the most tasks per second (the fewest when tied within 5 percent) |
| `cap_minutes(estimate_min)` | int | `ValueError` for a non-number | About 1.5 times the estimate plus 5, whole minutes, at least 10 |
| `add_arguments(p)` | None | Nothing | Adds the `cpu` subcommand to a parser |
| `run(a)` | exit code | Nothing | The `cpu` command on parsed arguments |
| `main(argv=None)` | exit code | `SystemExit` 2 on bad arguments | The command line |

Constants: `CPU_FLAVORS`, `CPU_KINDS`, `TIMEOUT_MARGIN = 1.5`, `TIMEOUT_SETUP_MIN = 5`.

## Inputs

Only the options.

## Outputs

One line, or with `--json`: `flavor`, `kind`, `workers`, `best_workers`, `slowdown`, `wall_s`, `cap_min`.

| Exit code | Meaning |
| --- | --- |
| `0` | Estimated |
| `2` | No table for the flavor, or bad arguments |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `kit runlength cpu: no kit.cpudiag table for FLAVOR; measure it first (python -m kit.cpudiag run)` | The flavor is not in `CPU_FLAVORS` | Measure it with cpudiag and add a row |
| `usage: ...` then `error: ...`, exit code 2 | A missing `--task-s` or `--tasks`, or an unknown `--kind` | Check the options |

## How it works

`cpu_slowdown` looks up the kind's row (`max` takes the largest over the kinds at that worker count), returns the first entry below the smallest measured count, interpolates linearly between measured counts, and past the largest scales it by workers over that count (processes time-share the vCPUs). `cpu_wall_s` multiplies the number of rounds, ceil(tasks / workers), by the task time and the slowdown. `cpu_best_workers` compares workers over slowdown at each measured count.

## Cost and time

Instant; the tests run in 0.002 s. It rents nothing.

## For agents

- **Command:** `python -m kit.runlength cpu --task-s S --tasks N [--workers W] [--kind K] --json`.
- **Parse:** `wall_s`, `cap_min`, `workers`, `best_workers`.
- **Rerun:** safe; it is a pure function of its options.
- **Success:** exit 0.
- **Not a pass:** an estimate for a flavor measured on other work without the `max` kind; a container timing of a different task size.
- **Go-ahead:** Nothing.
- **Never:** size a CPU job as core-seconds over vCPUs.

## Tests

```bash
python -m unittest tests.test_runlength -v
```

8 tests: interpolation and time-sharing, `max` covering every kind, the table against the committed evidence, the stream cap, the measured pilot, the best worker counts, `cap_minutes` and the command line.

## History

- 2026-11-18: released to public Scrolls with [cpudiag](cpudiag.md) and the evidence folder (`f1e9aa8`), the CPU estimate only.

## Related

- [cpudiag](cpudiag.md): measures a flavor's table.
- Evidence: [`docs/evidence/2026-11-18-hf-cpu-diag/`](../evidence/2026-11-18-hf-cpu-diag/README.md).
