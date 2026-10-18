# doctor: check whether this machine can run villa's First Letters workflow

`python -m kit doctor` checks this machine for what villa's First Letters workflow needs (an NVIDIA GPU with 12 GB, 16 GB of memory, 25 GB of free disk, git, uv and docker, a villa checkout and VC3D's tools) and prints pass, warn or fail for each.

| Field | Value |
| --- | --- |
| Id | `doctor` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Planning and prizes |
| Run | `python -m kit doctor`, `from kit import doctor` |
| Code | `kit/doctor.py`, `kit/cli.py` (`cmd_doctor`) |
| Tests | `tests/test_kit.py` |
| Needs | Python 3.10 or newer, standard library only. Uses `nvidia-smi` (from the NVIDIA driver) when it is on `PATH`, and reads the environment variables `VILLA` and `VC_BIN` |
| Runs on | Any machine. 0.34 to 0.43 s per call with no `nvidia-smi` installed (5 runs, measured 2026-10-16, 4-core Xeon cloud container). With `nvidia-smi`, add its run time, at most 20 s (the timeout) |
| Network | None |
| Writes | Nothing (prints only). It runs `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits` when that program is on `PATH` |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-06 (`2daee8e`), with the Apple Silicon path since 2026-10-07 (`e8f3dda`). Also inside the AutoPipeline release copy at `faada83`, and as `scrolls-workbench doctor` in the installable package since 2026-10-14 (`2582ab7`) |
| Guide | [mac.md](../mac.md) (what runs on an Apple Silicon Mac), [compute.md](../compute.md) (hardware that has worked, and the thresholds' sources) |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

villa's First Letters workflow, the official ink detection tutorial ([scrollprize.org/tutorial5](https://scrollprize.org/tutorial5)) that [plan](plan.md) prints, needs several things on the machine: an NVIDIA GPU with CUDA for ink inference, room on disk for surface volumes, uv to run villa's Python, VC3D's command-line tools (`vc_grow_seg_from_seed` to grow a surface, `vc_render_tifxyz` to render it), and a villa checkout. `kit doctor` checks six of these and prints one line each, `pass`, `warn` or `fail`, then an overall verdict that is the worst of the six.

The thresholds come from published runs, as the module's docstring records: 12 GB of GPU memory, because Bullo27's [first-letters-survey](https://github.com/Bullo27/first-letters-survey) ran on an RTX 3060 12 GB and a July 2026 progress prize made the spiral fitter run on 12 GB cards; and 25 GB of free disk, because one tutorial segment of the ink-labels dataset is about 25 GB ([tutorial5](https://scrollprize.org/tutorial5)). The 16 GB memory threshold (`MIN_RAM_GB`) has no source in the code. "GB" in its messages means GiB (1,024^3 bytes).

On an Apple Silicon Mac (macOS on arm64) the GPU check is a warning, not a failure: there is no CUDA, but VC3D, rendering and lasagna (villa's flattening tool, `--device mps`) run locally ([mac.md](../mac.md)). There it also finds VC3D's tools inside `/Applications/VC3D.app/Contents/MacOS` when `VC_BIN` is not set.

It does not run anything on the GPU, check the CUDA driver or PyTorch, test MPS (Metal Performance Shaders, PyTorch's Apple GPU backend), check the villa checkout's commit or whether `uv sync` ran, or check access to the open-data bucket or to Modal. A pass says the parts are there, not that the pipeline runs: running the w035 control (step 1 of [plan](plan.md)) is that test. Its report makes no claim about any scroll.

In this repository GPU work goes to Modal (the Modal rule, hard rule 11), so a `fail` on `gpu` on a laptop or in a Claude cloud session is expected. It means the GPU steps go into a Modal run spec, not that the machine is broken. "Rent a GPU" in its messages means that here.

## When to use it

- At the start of a session: the [scroll-session](scroll-session.md) skill runs it after [prizes](prizes.md).
- On a new machine, or after installing villa, VC3D or uv, to see what is still missing.
- Before running the w035 control locally (step 1 of [plan](plan.md), or [mac-verify](mac-verify.md) on a Mac).
- To see whether a GPU has the 12 GB the published runs used.

Do not use it:

- To show that ink inference runs: run the control (step 1 of [plan](plan.md); on a Mac, `bash scripts/mac-verify.sh`, see [mac-verify](mac-verify.md)).
- To check that two devices give the same map (CPU against MPS): use [verify](verify.md), with its control.
- To price a job: use `kit cost` ([plan](plan.md)) or the Modal calculator ([cloudcost](cloudcost.md)); for the time and electricity of a local run, [run-local](run-local.md).
- To test whether Modal is reachable: a Claude cloud session needs `pip install 'modal[api-proxy-support]'`, Chase's sign-in and an allow rule, then `modal app list` answers (the Modal rule); without them, write a run spec in [`docs/compute/modal-specs/`](../compute/modal-specs/README.md) instead.

## Quick start

```bash
python -m kit doctor
VILLA=VILLA_DIR VC_BIN=VC_BIN_DIR python -m kit doctor --disk WORK_DIR
```

- `VILLA_DIR`: your villa checkout (the folder holding `vesuvius/` and `volume-cartographer/`).
- `VC_BIN_DIR`: the folder holding `vc_grow_seg_from_seed` and `vc_render_tifxyz`; on a Mac with VC3D.app installed, leave `VC_BIN` unset.
- `WORK_DIR`: the folder where volumes and renders will go; its file system's free space is checked.

In the cloud container where this page was written (no GPU, `VILLA` and `VC_BIN` unset, 2026-10-16) it printed, with exit code 1:

```
[fail] gpu     No NVIDIA GPU found (nvidia-smi absent or failed). Ink inference needs CUDA; see docs/compute.md for rentals.
[pass] memory  16 GB memory
[pass] disk    26 GB free at . (one tutorial segment is about 25 GB)
[pass] tools   git, uv and docker on PATH
[warn] villa   VILLA not set. Clone https://github.com/ScrollPrize/villa and export VILLA=/path/to/villa
[warn] vc_bin  VC_BIN not set. Needed for vc_grow_seg_from_seed and vc_render_tifxyz built from villa main

overall: fail
```

With a stand-in `nvidia-smi` that reported an RTX 3060 (12,288 MiB) and an A10 (23,028 MiB), a folder holding empty `vesuvius/` and `volume-cartographer/`, and a `VC_BIN` folder holding only `vc_render_tifxyz`, it printed `overall: warn` and exit code 0:

```
[pass] gpu     NVIDIA GeForce RTX 3060 12 GB; NVIDIA A10 22 GB
...
[pass] villa   villa checkout at /tmp/claude-docs-public-doctor/villa
[warn] vc_bin  /tmp/claude-docs-public-doctor/vcbin lacks vc_grow_seg_from_seed
```

It worked when the last line is `overall: pass`, `overall: warn` or `overall: fail`. Read each `warn` and `fail` line; each says what is missing.

## Checks and controls

- **Every check can fail, and the tests show it** (`DoctorTest`): no GPU gives `fail`, an 8 GB card `warn` and a 12 GB card `pass`; a folder without `vesuvius/` and `volume-cartographer/` gives `fail` and one with them `pass`; 15.6 GB of memory passes and 8 GB warns.
- **Run against stand-ins on 2026-10-16** (synthetic inputs, this container): an `nvidia-smi` reporting a GTX 1080 (8,192 MiB) gave `[warn] gpu ... Below 12 GB`, one that exited with code 9 gave `[fail] gpu`, a `VILLA` folder without the two subfolders gave `[fail] villa` and exit code 1, and a `PATH` without uv gave `[warn] tools   missing: uv`.
- **A real failure on record:** in the cloud session that built this repository on 2026-10-06 it printed `[fail] gpu No NVIDIA GPU found` ([error log](../logs/errors.md)).
- **What a pass does not show:** that CUDA, PyTorch or villa's inference work. The control run (w035, step 1 of [plan](plan.md)) shows that; it in turn shows only that the pipeline runs, since w035 is a training segment ([log](../logs/2026-10-07-w035-cpu.md)).

Claim label: None for the report, which describes this machine and makes no claim about scrolls. Its 12 GB GPU and 25 GB disk thresholds are Sourced facts (Bullo27's first-letters-survey on an RTX 3060 12 GB; scrollprize.org/tutorial5).

## Commands and options

### `python -m kit doctor`

```
usage: python -m kit doctor [-h] [--disk DISK]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--disk DISK` | `.` | Path whose file system's free space is checked: the current folder by default. Point it at where volumes, renders and VC3D's cache will go. A path that does not exist stops with a `FileNotFoundError` traceback and exit code 1 |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `VILLA` | unset, which gives `warn` | Path of a villa checkout. `pass` when it holds both `vesuvius/` and `volume-cartographer/` folders, `fail` otherwise. An empty value is read as the current folder |
| `VC_BIN` | unset, which gives `warn`; on Apple Silicon, `/Applications/VC3D.app/Contents/MacOS` when that folder exists | Folder of VC3D's command-line tools. `pass` when both `vc_grow_seg_from_seed` and `vc_render_tifxyz` are in it, `warn` otherwise. Never `fail` |
| `PATH` | the shell's | Searched for `nvidia-smi`, `git`, `uv` and `docker` (`shutil.which`) |

## Python API

```python
from kit import doctor
results = doctor.run_checks(disk_path="/data")      # [(name, status, detail), ...]
text, worst = doctor.format_report(results)
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `is_apple_silicon(system=None, machine=None)` | bool | Nothing | True only for `Darwin` on `arm64`; the defaults come from `platform.system()` and `platform.machine()` |
| `ram_gb()` | float (GiB of physical memory), or `None` | Nothing | From `os.sysconf`; `None` where that is missing, such as on Windows |
| `gpus(run=subprocess.run)` | list of `(name, memory_mb)` | Nothing | Runs `nvidia-smi` with a 20 s timeout; `[]` when it is not on `PATH`, exits non-zero or times out. `run` is replaceable for tests |
| `parse_nvidia_smi(text)` | list of `(name, memory_mb)` with int MiB | Nothing | Splits each line at its last comma; lines whose last field is not a number are skipped |
| `check_gpu(found, apple_silicon=False)` | `(status, detail)` | Nothing | `fail` with no GPU, `warn` with no GPU on Apple Silicon, `pass` when the largest card has at least `MIN_GPU_MB` (12,288 MiB), `warn` below |
| `check_disk(path)` | `(status, detail)` | `FileNotFoundError` (or another `OSError`) for a path that does not exist or cannot be read | `pass` at 25 GiB free (`MIN_DISK_GB`) or more, `warn` below; never `fail` |
| `check_ram(gb, apple_silicon=False)` | `(status, detail)` | Nothing | `pass` when `round(gb)` is at least 16 (`MIN_RAM_GB`), so a "16 GB" machine that reports 15.6 GiB passes; `warn` below or for `None` |
| `check_tools(which=shutil.which)` | `(status, detail)` | Nothing | `pass` when `git`, `uv` and `docker` (`TOOLS`) are all found, `warn` listing the missing ones |
| `check_villa(path)` | `(status, detail)` | Nothing | `warn` for `None`, `pass` for a folder with both subfolders, `fail` otherwise |
| `check_vc_bin(path, apple_silicon=False)` | `(status, detail)` | Nothing | `pass` or `warn`, never `fail`; on Apple Silicon a `None` path falls back to `MAC_VC_BIN` when that folder exists |
| `run_checks(env=None, disk_path='.')` | list of six `(name, status, detail)`: `gpu`, `memory`, `disk`, `tools`, `villa`, `vc_bin`, in that order | As `check_disk` | `env` (default `os.environ`) supplies only `VILLA` and `VC_BIN`; the GPU, memory, platform and `PATH` are always this machine's |
| `format_report(results)` | `(text, worst)`, `worst` one of `pass`, `warn`, `fail` | Nothing | The text the command prints, ending in `overall: WORST` |

Module constants: `MIN_GPU_MB = 12 * 1024`, `MIN_DISK_GB = 25`, `MIN_RAM_GB = 16`, `TOOLS = ("git", "uv", "docker")`, `MAC_VC_BIN = Path("/Applications/VC3D.app/Contents/MacOS")`, and the status words `PASS`, `WARN`, `FAIL` (`"pass"`, `"warn"`, `"fail"`).

## Inputs

| Input | Where it comes from | Notes |
| --- | --- | --- |
| GPUs | `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits` | One line per card, `NAME, MEMORY_MIB` |
| Physical memory | `os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")` | Not available on Windows |
| Free disk | `shutil.disk_usage(--disk)` | The free space of the file system that holds the path |
| Tools | `shutil.which` on `PATH` | `git`, `uv`, `docker` |
| villa and VC3D paths | `VILLA`, `VC_BIN` | See Environment variables |
| Platform | `platform.system()`, `platform.machine()` | Apple Silicon is `Darwin` on `arm64` |

## Outputs

Text on stdout, one line per check, `[STATUS] NAME    DETAIL` (status right-aligned in 4 characters, name left-aligned in 7), then a blank line and `overall: STATUS`. There is no JSON form; in Python, `run_checks()` gives the same as tuples.

| Check | `pass` when | `warn` when | `fail` when |
| --- | --- | --- | --- |
| `gpu` | The largest NVIDIA card has 12,288 MiB or more | A card below 12 GB; or no NVIDIA GPU on Apple Silicon | No NVIDIA GPU found, not on Apple Silicon |
| `memory` | 16 GB or more after rounding | Less, or unreadable | Never |
| `disk` | 25 GiB or more free at `--disk` | Less | Never |
| `tools` | `git`, `uv` and `docker` on `PATH` | Any missing | Never |
| `villa` | `VILLA` holds `vesuvius/` and `volume-cartographer/` | `VILLA` not set | `VILLA` set to anything else |
| `vc_bin` | Both VC3D tools in `VC_BIN` (or in VC3D.app on Apple Silicon) | Not set, or a tool missing | Never |

GPU sizes are printed as whole GB rounded down (23,028 MiB prints as `22 GB`), and free disk and memory are rounded to whole GB, so a disk line can read `25 GB free` and still warn when the free space is just under 25 GiB.

| Exit code | Meaning |
| --- | --- |
| `0` | No check failed: `overall: pass` or `overall: warn` |
| `1` | At least one check failed (`overall: fail`), or a Python error with a traceback and no `overall:` line, such as a `--disk` path that does not exist |
| `2` | A usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `[fail] gpu     No NVIDIA GPU found (nvidia-smi absent or failed). Ink inference needs CUDA; see docs/compute.md for rentals.` | `nvidia-smi` is not on `PATH`, exited non-zero, took over 20 s, or printed nothing it could read | Expected on a laptop or a cloud session: GPU steps go to Modal through a run spec (the Modal rule). On a GPU machine, install the NVIDIA driver and run `nvidia-smi` by hand |
| `[warn] gpu     NAME N GB. Below 12 GB: use batch size 1 or rent a GPU.` | The largest card has under 12,288 MiB | Use `--batch 1` in [plan](plan.md), or run the GPU steps on Modal |
| `[warn] gpu     Apple Silicon, no CUDA. Runs locally: VC3D app, rendering, lasagna (--device mps). Stock villa ink inference uses the CPU; open PRs #1865/#1812 add MPS. Full segments: rent a GPU. See docs/mac.md` | A Mac with Apple Silicon. The PR statuses in this text date from 2026-10-07 | Follow [mac.md](../mac.md) and `python -m kit plan SCROLL --mac`; full segments go to Modal |
| `[warn] memory  could not read installed memory` | `os.sysconf` is missing (Windows) or failed | Check memory by hand |
| `[warn] memory  N GB memory` | Under 16 GB after rounding | Small renders only; heavy CPU work goes to Modal |
| `[warn] disk    N GB free at PATH (one tutorial segment is about 25 GB)` | Under 25 GiB free on that file system | Free space, or point `--disk` and your work folder at a bigger disk |
| `FileNotFoundError: [Errno 2] No such file or directory: 'PATH'` and a traceback, exit code 1 | `--disk` names a path that does not exist | Create the folder first, or pass an existing one |
| `[warn] tools   missing: NAMES (uv runs villa; docker runs the VC3D image)` | `git`, `uv` or `docker` is not on `PATH` | Install the missing tool; docker matters only for the VC3D container, which villa issue #1588 reported stale |
| `[warn] villa   VILLA not set. Clone https://github.com/ScrollPrize/villa and export VILLA=/path/to/villa` | `VILLA` is not set | Clone villa and export `VILLA` |
| `[fail] villa   PATH does not look like a villa checkout (no vesuvius/ and volume-cartographer/)` | `VILLA` points at a folder without those two subfolders (an empty `VILLA` means the current folder) | Point `VILLA` at the top of the villa clone |
| `[warn] vc_bin  VC3D.app not in /Applications. Install the macos-arm64 .dmg from https://github.com/ScrollPrize/villa/releases` | Apple Silicon, `VC_BIN` not set and no VC3D.app | Install VC3D.app, or set `VC_BIN` |
| `[warn] vc_bin  VC_BIN not set. Needed for vc_grow_seg_from_seed and vc_render_tifxyz built from villa main` | `VC_BIN` is not set (not on Apple Silicon) | Build VC3D from villa main and export `VC_BIN` |
| `[warn] vc_bin  PATH lacks vc_grow_seg_from_seed, vc_render_tifxyz` | One or both tools are not in `VC_BIN` (or the folder does not exist) | Point `VC_BIN` at the folder that holds them |

## How it works

1. `run_checks` decides whether this is Apple Silicon (`platform.system() == "Darwin"` and `platform.machine() == "arm64"`).
2. `gpu`: `gpus()` runs `nvidia-smi` if `shutil.which` finds it (20 s timeout, `check=True`), and `parse_nvidia_smi` reads `NAME, MEMORY_MIB` lines. `check_gpu` compares the largest card with `MIN_GPU_MB = 12 * 1024`.
3. `memory`: physical pages times page size, in GiB; `round(gb) >= MIN_RAM_GB` (16) passes, because a machine sold as 16 GB reports slightly less.
4. `disk`: `shutil.disk_usage(--disk).free` in GiB against `MIN_DISK_GB` (25).
5. `tools`: `shutil.which` for each name in `TOOLS`.
6. `villa` and `vc_bin`: folder tests on `VILLA` and `VC_BIN`, with the VC3D.app fallback on Apple Silicon.
7. `format_report` writes the lines and takes the worst status (`fail` over `warn` over `pass`); `cmd_doctor` prints it and returns 1 when the worst is `fail`, 0 otherwise.

## Cost and time

Measured 2026-10-16 in a 4-core Xeon cloud container with no `nvidia-smi`: 0.34 to 0.43 s per call over 5 runs, almost all Python start-up and the import of `kit.cli`. On a machine with `nvidia-smi`, add that program's run time; the call gives up after 20 s. It rents nothing and runs anywhere.

## For agents

- **Command:** `python -m kit doctor --disk WORK_DIR`. There is no JSON form; in Python, `from kit import doctor; doctor.run_checks(disk_path="WORK_DIR")` returns `(name, status, detail)` tuples.
- **Parse:** each line `[STATUS] NAME DETAIL` (STATUS is `pass`, `warn` or `fail`; NAME is `gpu`, `memory`, `disk`, `tools`, `villa` or `vc_bin`) and the last line `overall: STATUS`.
- **Rerun:** Safe; it only reads the machine's state.
- **Success:** Exit code 0 with `overall: pass` or `overall: warn`. Exit code 1 with an `overall: fail` line is a finished report; exit code 1 without that line is a crash (see Failure modes).
- **Not a pass:** `overall: pass` does not mean CUDA, PyTorch or villa's inference work; only the control run shows that. A `gpu` pass says nothing about whether the card is free or the driver matches villa's PyTorch.
- **Go-ahead:** Nothing for the check. Renting the GPU its messages suggest needs Chase's budget decision (the go-ahead rule, hard rule 8).
- **Never:** Try to sign in to Modal from a Claude cloud session because `gpu` failed (the Modal rule, hard rule 11): write a run spec instead; run hours of GPU work on a laptop CPU because the other checks passed.

## Tests

```bash
python -m unittest tests.test_kit.DoctorTest -v
```

Six tests cover `nvidia-smi` parsing, the 12 GB threshold (fail, warn, pass), Apple Silicon reported as a warning that points to `docs/mac.md`, the memory rounding (15.6 passes, 8 warns, unreadable warns, "shared with the GPU" on a Mac), villa checkout detection, and the overall verdict. They do not cover `check_disk`, `check_tools`, `check_vc_bin`, `run_checks`, the command line or its exit codes, or a real `nvidia-smi`.

## History

- 2026-10-14: `scrolls-workbench doctor` in the installable package (`2582ab7`, [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58)).
- 2026-10-07: the Apple Silicon path: on a Mac the GPU check warns instead of failing, a memory check (16 GB) is added, and VC3D's tools are found inside VC3D.app (`e8f3dda`, [PR #1](https://github.com/ChaseHendrick/Scrolls/pull/1)).
- 2026-10-06: first version: the NVIDIA GPU (12 GB), free disk (25 GB), git, uv and docker, `VILLA` and `VC_BIN` checks (`2daee8e`).

## Related

- [mac.md](../mac.md): what runs on an Apple Silicon Mac, and the open villa PRs for MPS inference.
- [compute.md](../compute.md): hardware that has run the workflow, and costs from published runs.
- [plan](plan.md): the run plan whose steps these checks prepare for, and `kit cost`.
- [prizes](prizes.md): the other first command of a session.
- [mac-verify](mac-verify.md): runs the w035 control on a Mac in one command.
- [scroll-session](scroll-session.md): the session skill that runs this check.
- [error log](../logs/errors.md): the first recorded `fail` on the setup session's machine.
