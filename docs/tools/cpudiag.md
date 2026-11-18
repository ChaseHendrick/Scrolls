# cpudiag: time a CPU flavor against a container, core by core

`kit.cpudiag` runs fixed CPU, memory-bandwidth, BLAS-thread, small-file I/O and scrollsim2 render benchmarks at several process counts, so a cloud CPU flavor can be compared with a known machine and CPU job estimates corrected.

| Field | Value |
| --- | --- |
| Id | `cpudiag` |
| Status | Current |
| Kind | kit entry point, kit module |
| Area | Compute and cost |
| Run | `python -m kit.cpudiag run [--procs 1,8,32] [--kernels pyloop,compute,stream,blas] [--mount DIR] [--scrollsim2] [--out FILE]`; `python -m kit.cpudiag compare HERE.json THERE.json` |
| Code | `kit/cpudiag.py` |
| Tests | `tests/test_cpudiag.py` |
| Needs | Python 3.10 or newer and numpy (measured with 3.12 and 3.13, numpy 2.3.4); scipy and `kit/scrollsim2.py` for `--scrollsim2` only. Linux for the cgroup and lscpu facts (elsewhere they are null) |
| Runs on | CPU anywhere. All kernels at 1 and 4 processes: about 40 s in a 4-core cloud container; `--scrollsim2` adds the pilot geometry (34 s there, 21 s on Hugging Face `cpu-performance`) and one block per process (5 to 21 s) (2026-11-18) |
| Network | None |
| Writes | `--out FILE` (saved after each phase); `--mount DIR`: a temporary folder of 32 files of 2 MB inside DIR, removed at the end |
| Go-ahead | Not needed to run it; a run on rented machines follows hard rule 11 |
| Released | Public `main` from the PR that adds this page (2026-11-18), with [runlength](runlength.md) |
| Checked | 2026-11-18 against commit `c2cb575` |

## What it does

On 18 Nov 2026 the scrollsim2 render ran about 6.5 times slower per worker on Hugging Face `cpu-performance` (32 vCPU) than in a 4-core cloud container, and the cause was not known. This tool measures the pieces separately so the cause can be read from numbers: interpreter speed (`pyloop`), cache-resident numpy math (`compute`), memory bandwidth (`stream`, a STREAM-like triad on 128 MB arrays), BLAS thread oversubscription (`blas`, with the thread variables as inherited and with 1 thread per process), small-file writes with a rename on local disk and on a bucket mount (`--mount`), and the real scrollsim2 pilot sheet blocks (`--scrollsim2`). Each kernel runs at every process count P in `--procs`, the P processes forked at once behind one barrier, each doing the same fixed work.

It also prints the machine: lscpu's model, cores, threads per core and NUMA nodes, `nproc`, `os.cpu_count()`, the cgroup CPU quota, the affinity mask, the thread variables in force and numpy's SIMD build.

The numbers are timings of synthetic work only. No scroll data is read.

## When to use it

- A CPU job runs much slower than its estimate from a container or laptop timing.
- Before sizing a large CPU run on a new cloud CPU flavor: measure it once, then add its row to [runlength](runlength.md)'s `CPU_FLAVORS`.
- Choosing the worker count of a forked pool on a big CPU flavor.

Do not use it:

- To time one script end to end: run the script's own probe (for scrollsim2, `python -m kit.scrollsim2 estimate`) and scale it with `python -m kit.runlength cpu`.

## Quick start

```bash
python -m kit.cpudiag run --procs 1,4 --mount /tmp/cpudiag-mnt --out /tmp/cpudiag-here.json
python -m kit.cpudiag compare /tmp/cpudiag-here.json docs/evidence/2026-11-18-hf-cpu-diag/hf-cpu-performance-a2.json
```

- `/tmp/cpudiag-mnt`: any writable folder (a bucket mount to test one); `/tmp/cpudiag-here.json`: where the result goes.

Excerpt from a 4-core cloud container (2026-11-18, `docs/evidence/2026-11-18-hf-cpu-diag/container-4core.json`):

```
PROGRESS compute P=1: {"median_s": 2.0211, "max_s": 2.0211, "n": 1}
PROGRESS stream P=4: {"median_s": 2.1409, "max_s": 2.1971, "n": 4, "gb_s_per_proc": 15.67, "gb_s_total": 61.1}
reading: blas at P=4: inherited threads 8.63 x the time of 1 thread per process
```

It worked when every phase printed a `PROGRESS` line and the JSON has `scaling`, `blas` and (with the options) `io` and `scrollsim2`. `compare` against the evidence file matches only the phases both runs have (the evidence job ran scrollsim2, I/O and BLAS).

## Checks and controls

The control is P=1 on the same machine: a slowdown that appears only as P grows is contention (shared cores, memory bandwidth, threads); one already present at P=1 against another machine is per-core speed. `blas` carries its own control (1 thread per process beside the inherited threads). `--mount` carries local disk as its control and counts the files that landed. A claim that a flavor is "slower per core" must cite both P=1 and the largest P.

Claim label: Sourced fact for the measured timings in `docs/evidence/2026-11-18-hf-cpu-diag`; Interpretation for the `reading` lines and the cause.

## Commands and options

| Option | Default | Meaning |
| --- | --- | --- |
| `run --procs` | `1,8,32` | comma-separated process counts P; every kernel runs at each |
| `run --scale` | `1.0` | work per kernel (1 is about 1 to 4 s a kernel on a 2026 Xeon core) |
| `run --kernels` | `pyloop,compute,stream,blas` | which kernels to time; an empty or unknown list skips them (scrollsim2 and I/O only) |
| `run --mount` | none | a directory (bucket mount) to time small-file writes in, beside local disk |
| `run --scrollsim2` | off | also time scrollsim2 pilot sheet blocks at each P (needs `kit/scrollsim2.py`, released in [#362](https://github.com/ChaseHendrick/Scrolls/pull/362)) |
| `run --out` | none | write the JSON here, saved after each phase |
| `compare HERE THERE` | | two `run` JSON files; prints THERE's seconds over HERE's at matching P |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `cgroup_cpus(root='/sys/fs/cgroup')` | float or None | Nothing | CPUs the cgroup quota allows (cpu.max, or cgroup v1 cfs quota over period), or None when unlimited. |
| `lscpu_fields(text)` | dict | Nothing | The lscpu lines that decide per-core speed: model, cores, threads per core, sockets, caches, NUMA, MHz. |
| `machine()` | dict | Nothing | Host facts printed and saved with every run. |
| `k_pyloop(scale=1.0)` | seconds | Nothing | 40 million pure Python steps at scale 1. |
| `k_compute(scale=1.0)` | seconds | Nothing | 40,000 rounds of four numpy ufuncs on 16,384 doubles (cache-resident). |
| `k_stream(scale=1.0)` | seconds | Nothing | Triad a = b + s*c over STREAM_N doubles, as two numpy passes; returns seconds for the timed passes. |
| `stream_bytes(scale=1.0)` | int | Nothing | Bytes the timed triad passes move (read c, write a; read a and b, write a), per process. |
| `k_blas(scale=1.0)` | seconds | Nothing | 500 matmuls of 512 x 512 at scale 1. |
| `scale_run(name, procs, scale=1.0)` | list of seconds | Nothing | Seconds per process for kernel NAME with PROCS processes started at once (forked, one barrier). |
| `summarize(times)` | dict | Nothing | `median_s`, `max_s`, `n`. |
| `blas_subprocess(procs, threads, scale=1.0, timeout=600)` | list of seconds | `RuntimeError`, `subprocess.TimeoutExpired` | The blas kernel in a fresh interpreter, so the thread variables take effect at numpy's import; on a timeout the whole process group is killed. |
| `io_run(base, writers=8, files=4, size=2 << 20)` | dict | `OSError` | Write (temp file plus rename, as zarr does) and read back WRITERS x FILES files of SIZE bytes under BASE. |
| `scrollsim2_run(procs_list, preset='pilot', per_proc=1)` | dict | `ImportError` without scipy or scrollsim2 | Build the scrollsim2 geometry once, then time sheet blocks near the center with each P in PROCS_LIST (the same blocks on every machine). |
| `reading(res)` | list of str | Nothing | Plain-language reading of one run's slowdowns (Interpretation, not a measurement). |
| `run(procs=(1, 8, 32), scale=1.0, mount=None, scrollsim2=False, progress=print, kernels=KERNELS, out=None)` | dict | as above | Every phase in order of value (scrollsim2, I/O, the plain kernels, BLAS last, as it can run away); with OUT the result so far is saved after each phase. |
| `compare(here, there)` | dict | Nothing | Per-core factors THERE over HERE: seconds per process at matching P, kernel by kernel (above 1 = slower). |
| `main(argv=None)` | exit code | Nothing | The CLI. |

## Inputs

None but the options. `--mount DIR` must be writable. `--scrollsim2` needs `kit/scrollsim2.py` importable and about 6 GB of memory for the pilot geometry.

## Outputs

Prints one `PROGRESS` line per phase, then the JSON and its `reading:` lines. JSON fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `machine` | object | lscpu fields, `nproc`, `os_cpu_count`, `affinity`, `cgroup_cpus`, `threads_env`, `numpy_simd` |
| `scaling.KERNEL.P` | object | `median_s`, `max_s`, `n` seconds per process; `stream` adds `gb_s_per_proc` and `gb_s_total` (GB/s) |
| `blas` | object | `procs`, `scale`, `one_thread`, `single_proc_inherited`, `inherited` (or `{"timeout_s": 120}`) |
| `io.local`, `io.mount` | object | `mb`, `wall_s`, `write_mb_s`, `read_mb_s`, `files_landed`, `files_expected` |
| `scrollsim2` | object | `seconds_init`; `by_procs.P` seconds per block per process |
| `reading` | list | Interpretation lines |

| Exit code | Meaning |
| --- | --- |
| `0` | Every requested phase ran |
| `2` | Bad arguments |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `blas subprocess failed:` | numpy failed to import or the kernel crashed in the child | Read the stderr tail it prints; check numpy installs in the image |
| `"inherited": {"timeout_s": 120}` | P processes each started as many BLAS threads as CPUs (32 x 32 on `cpu-performance`) | That is the finding: give each pool worker 1 BLAS thread (see For agents) |
| `scrollsim2 ... error: only N sheet blocks near the center` | Fewer sheet blocks near the center than P | Lower the largest `--procs` |

## How it works

Each kernel is a fixed amount of work (constants in `k_*`; `STREAM_N` = 2^24 doubles, 128 MB an array). `scale_run` forks P workers with `multiprocessing`'s fork context, makes them wait on one barrier, runs the kernel in each and returns each worker's seconds. `blas_subprocess` starts a fresh interpreter (in its own session, killed as a group on timeout) so `OMP_NUM_THREADS` and the other thread variables take effect when numpy loads OpenBLAS. `scrollsim2_run` builds the pilot `Scroll2` once, sorts blocks by distance to the volume's center, keeps sheet blocks, and forks P workers that each render one, so P=1 on two machines times the same block.

## Cost and time

Measured 2026-11-18 (`docs/evidence/2026-11-18-hf-cpu-diag`):

- 4-core cloud container (Intel Xeon, AVX-512, 1 thread per core): all kernels at P=1 and 4 plus scrollsim2, about 2 minutes.
- Hugging Face `cpu-performance`, first job: kernels at 1, 8, 16 and 32, then an earlier unbounded BLAS test ran the job to its 9 minute timeout (the test is now bounded and kills its process group).
- Hugging Face `cpu-performance`, second job: scrollsim2 at 1, 8, 16, 32, I/O, bounded BLAS: 151 s.

### The 18 Nov 2026 finding (Hugging Face `cpu-performance`)

`cpu-performance` is an AMD EPYC 7R13 (Zen 3, AVX2, no AVX-512), 32 vCPU as 16 cores with 2 threads each, 2 NUMA nodes, cgroup quota 32.

| Measure | Container (4 cores) | HF P=1 | HF P=8 | HF P=16 | HF P=32 |
| --- | --- | --- | --- | --- | --- |
| scrollsim2 pilot block, s per worker | 6.83 (P=1); 4.33 median of the same 32 blocks at 4 workers | 6.69 | 3.84 | 8.18 | 20.89 |
| scrollsim2 blocks per second | 0.92 at 4 workers | 0.15 | 2.08 | 1.96 | 1.53 |
| STREAM triad GB/s in all | 61 (P=4) | 31.8 | 67.8 | 67.6 | 69.6 |
| compute kernel, s per process | 2.02 | 3.87 | 3.83 | 4.01 | 7.22 |
| pyloop, s per process | 2.11 | 2.86 | 2.87 | 2.91 | 5.36 |
| blas, 32 procs: inherited 32 threads over 1 thread | 8.6 x (4 procs) | | | | 116 x |
| bucket mount, 32 x 2 MB files with rename | | all 32 landed, 4.8 GB/s write (local disk 17 GB/s) | | | |

Interpretation: one scrollsim2 worker is as fast on HF as in the container (0.98 times). The slowdown at 32 workers is contention: memory bandwidth is saturated by 8 processes (68 GB/s in all), and 32 workers put two on every core. scrollsim2's render moves large arrays, so 32 workers render fewer blocks per second than 8 or 16. Not the cause: thread variables (scrollsim2's render makes no BLAS calls; changing them moved its block time by under 5 percent in the container), the bucket mount (all files landed, writes faster than the render needs) and the CPU quota (32). Per-core math is slower on Zen 3 for numpy ufuncs (compute 1.9 times) because numpy's AVX-512 loops are not available there.

## For agents

- **Command:** `python -m kit.cpudiag run --procs 1,8,16,32 --mount DIR --out FILE.json`; on a rented flavor, a job of `--kernels blas --scrollsim2` or all kernels, with a timeout of about 10 minutes.
- **Parse:** `scaling.KERNEL.P.median_s`, `stream ... gb_s_total`, `blas.inherited` against `blas.one_thread`, `scrollsim2.by_procs.P.median_s`, `reading`.
- **Rerun:** safe; `--out` is overwritten.
- **Success:** exit 0 and every requested phase in the JSON.
- **Not a pass:** a P=1 comparison alone (contention shows only at the job's real worker count); a `compare` across different block sets.
- **Estimates:** scale a container task time to a measured flavor with `python -m kit.runlength cpu --task-s S --tasks N [--workers W] [--kind max|stream|scrollsim2|compute]` (default `max`, safe for unknown work), never as core-seconds over vCPUs. On `cpu-performance` run memory-heavy pools (renders, filters, zarr writes) with 8 to 16 workers, not 32.
- **Pools that call BLAS:** a job wrapper that sets `OMP_NUM_THREADS` and the others to the job's CPU count makes a forked pool of W workers run W times that many BLAS threads (116 times slower at 32 x 32). Export `OMP_NUM_THREADS=1` (and `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS`) before Python starts, or set them with `os.environ.setdefault` before numpy is imported.
- **Go-ahead:** a run on rented machines follows hard rule 11.
- **Never:** run its BLAS test unbounded at full width; read scroll data with it.

## Tests

```bash
python -m unittest tests.test_cpudiag -v
```

The cgroup quota parser (v1, v2, unlimited, missing), lscpu parsing, `compare` and `reading`, a tiny run's shape at 1 and 2 processes with a mount, `--kernels` skipping, and the BLAS timeout killing its process group. They do not check timings.

## History

- 2026-11-18: released to public Scrolls with [runlength](runlength.md)'s CPU estimate and the evidence folder (`f1e9aa8`). Written the same day, outside this repository, to find why the scrollsim2 render ran slower on Hugging Face `cpu-performance`.

## Related

- [runlength](runlength.md): `python -m kit.runlength cpu`, the CPU flavor table this tool measured.
- scrollsim2 (`kit/scrollsim2.py`, [#362](https://github.com/ChaseHendrick/Scrolls/pull/362)): the render whose slowdown this explained.
- Evidence: [`docs/evidence/2026-11-18-hf-cpu-diag/`](../evidence/2026-11-18-hf-cpu-diag/README.md).
