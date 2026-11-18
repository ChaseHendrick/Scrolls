# Hugging Face cpu-performance CPU diagnostics, 18 November 2026

Why CPU jobs on Hugging Face `cpu-performance` ran slower per worker than in a 4-core cloud container, measured with [`kit.cpudiag`](../../tools/cpudiag.md) and used for the table in [`kit.runlength`](../../tools/runlength.md). Synthetic work only; no scroll data.

| File | What it is |
| --- | --- |
| `container-4core.json` | `python -m kit.cpudiag run --procs 1,4 --mount DIR --scrollsim2` in a 4-core Intel Xeon cloud container (mount path replaced by `MOUNT`) |
| `container-4core-scrollsim2-32blocks.json` | The same 32 scrollsim2 pilot sheet blocks rendered by 4 workers in that container: 4.33 s median per block |
| `hf-cpu-performance-a1-kernels.txt` | The `pyloop`, `compute` and `stream` lines of the first diagnostic job at 1, 8, 16 and 32 processes (its unbounded BLAS test then ran into the job's timeout) |
| `hf-cpu-performance-a2.json` | The second job: scrollsim2 blocks at 1, 8, 16 and 32 processes, the mount I/O test and the bounded BLAS test (host name and mount path replaced) |
| `scrollsim2-pilot-timing.txt` | The last progress lines of a scrollsim2 pilot render with 32 workers on the same flavor: 2,912 blocks (2,458 sheet) in 1,512 s |

Sourced fact for the timings in these files; Interpretation for the reading on the tool pages (memory bandwidth saturates from about 8 processes, and SMT siblings share a core past 16).
