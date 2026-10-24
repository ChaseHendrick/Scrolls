# doctor: check whether this machine can run villa's First Letters workflow

`python -m kit doctor` checks this machine for what villa's First Letters workflow needs (a 12 GB GPU, 16 GB of memory, 25 GB of disk, git, uv and docker, villa and VC3D's tools), names AMD and Intel GPUs, and prints pass, warn or fail for each.

| Field | Value |
| --- | --- |
| Id | `doctor` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Planning and prizes |
| Run | `python -m kit doctor`, `from kit import doctor` |
| Code | `kit/doctor.py`, `kit/cli.py` (`cmd_doctor`) |
| Tests | `tests/test_kit.py`, `tests/test_qol_tools.py`, `tests/test_doctor_gpus.py` |
| Needs | Python 3.10 or newer, standard library only. Uses `nvidia-smi` (from the NVIDIA driver) or `rocm-smi` (from ROCm) when it is on `PATH`, imports torch when it is installed and no NVIDIA GPU was found (not on Apple Silicon), and reads the environment variables `VILLA`, `VC_BIN`, `HOME`, `VC3D_CONFIG_DIR`, `RUNPOD_POD_ID` and `RUNPOD_VOLUME_ID` |
| Runs on | Any machine. 0.34 to 0.43 s per call with no `nvidia-smi` installed (5 runs, measured 2026-10-16, 4-core Xeon cloud container). With `nvidia-smi`, add its run time, at most 20 s (the timeout) |
| Network | None |
| Writes | A 64 MB test file under `--disk` (and with `--remote`, under the cache folder's nearest existing parent), deleted after the speed test; `--no-speed` writes nothing. It runs `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits` and `rocm-smi --showproductname --showmeminfo vram --json` when those programs are on `PATH` |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-06 (`2daee8e`), with the Apple Silicon path since 2026-10-07 (`e8f3dda`). Also inside the AutoPipeline release copy at `faada83`, and as `scrolls-workbench doctor` in the installable package since 2026-10-14 (`2582ab7`) |
| Guide | [mac.md](../mac.md) (what runs on an Apple Silicon Mac), [compute.md](../compute.md) (hardware that has worked, and the thresholds' sources) |
| Checked | 2026-10-24 against commit `cc03099` |

## What it does

villa's First Letters workflow, the official ink detection tutorial ([scrollprize.org/tutorial5](https://scrollprize.org/tutorial5)) that [plan](plan.md) prints, needs several things on the machine: an NVIDIA GPU with CUDA for ink inference, room on disk for surface volumes, uv to run villa's Python, VC3D's command-line tools (`vc_grow_seg_from_seed` to grow a surface, `vc_render_tifxyz` to render it), and a villa checkout. `kit doctor` checks six of these and prints one line each, `pass`, `warn` or `fail`, then an overall verdict that is the worst of the six.

The thresholds come from published runs, as the module's docstring records: 12 GB of GPU memory, because Bullo27's [first-letters-survey](https://github.com/Bullo27/first-letters-survey) ran on an RTX 3060 12 GB and a July 2026 progress prize made the spiral fitter run on 12 GB cards; and 25 GB of free disk, because one tutorial segment of the ink-labels dataset is about 25 GB ([tutorial5](https://scrollprize.org/tutorial5)). The 16 GB memory threshold (`MIN_RAM_GB`) has no source in the code. "GB" in its messages means GiB (1,024^3 bytes).

On an Apple Silicon Mac (macOS on arm64) the GPU check is a warning, not a failure: there is no CUDA, but VC3D, rendering and lasagna (villa's flattening tool, `--device mps`) run locally ([mac.md](../mac.md)). There it also finds VC3D's tools inside `/Applications/VC3D.app/Contents/MacOS` when `VC_BIN` is not set.

It does not run anything on the GPU, check the CUDA driver or PyTorch, test MPS (Metal Performance Shaders, PyTorch's Apple GPU backend), check the villa checkout's commit or whether `uv sync` ran, or check access to the open-data bucket or to Modal. A pass says the parts are there, not that the pipeline runs: running the w035 control (step 1 of [plan](plan.md)) is that test. Its report makes no claim about any scroll.

**GPUs other than NVIDIA.** When `nvidia-smi` finds nothing and the machine is not an Apple Silicon Mac, it asks `rocm-smi --showproductname --showmeminfo vram --json` for AMD cards (the keys `Card Series` and `VRAM Total Memory (B)` per `cardN`, as ROCm's [`rocm_smi.py`](https://github.com/ROCm/rocm_smi_lib/blob/develop/python_smi_tools/rocm_smi.py) writes them, read 24 Oct 2026), then imports torch: a ROCm build (`torch.version.hip` set) lists AMD cards through `torch.cuda`, and `torch.xpu` lists Intel GPUs. Either reports as `warn`, never `pass`, because villa's spiral fitting asks for "an NVIDIA GPU" ([tutorial_spiral](https://scrollprize.org/tutorial_spiral), read 24 Oct 2026) and other villa steps are not tested on them here. `/dev/kfd` or `/opt/rocm` with no card listed warns too, since that usually means a driver or group-permission problem rather than no card. Before this, an AMD machine got `fail` with "No NVIDIA GPU found".

**`--remote`, for a rented or cloud machine.** VC3D keeps every chunk it streams from a remote volume in a cache folder, so on a pod or job where the home folder sits on a small or slow disk the cache, not the volume, fills the disk. `--remote` adds a `cache` line: the folder VC3D will use, found in VC3D's own order (villa main [`RemoteCacheSettings.cpp`](https://github.com/ScrollPrize/villa/blob/main/volume-cartographer/core/src/RemoteCacheSettings.cpp) and [`GlobalCacheRoot.hpp`](https://github.com/ScrollPrize/villa/blob/main/volume-cartographer/core/include/vc/core/util/GlobalCacheRoot.hpp), read 24 Oct 2026: `cache.json` in `$VC3D_CONFIG_DIR` or `~/.VC3D`, then `remote_cache_dir` under `[viewer]` in `VC3D.ini` there, then `/volpkgs/remote_cache` or `/ephemeral/remote_cache` when that mount exists, then `~/.VC3D/remote_cache`), and the free space there. With the speed test on, a `cacheio` line times that disk when it differs from `--disk`. On RunPod (`RUNPOD_POD_ID` set, [RunPod's variables](https://docs.runpod.io/pods/references/environment-variables)) the line says whether the folder survives, quoting [RunPod's storage page](https://docs.runpod.io/pods/storage/types) (read 24 Oct 2026): the container disk "is cleared when the Pod stops"; the volume disk at `/workspace` "survives Pod stops and restarts, but is deleted when the Pod is terminated"; a network volume (`RUNPOD_VOLUME_ID` set) replaces it at `/workspace`. Hugging Face Jobs set no variable we could find documented, so there it reports only the folder and its space.

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
python -m kit doctor --remote          # on a RunPod pod, a Hugging Face Job or any cloud machine
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

Since 24 October the no-GPU line reads `[fail] gpu     No GPU found (nvidia-smi, rocm-smi and torch found none). Ink inference needs CUDA; see docs/compute.md for rentals.` With `--remote --no-speed` in the same kind of container (24 Oct 2026, no torch installed) it added:

```
[pass] cache   VC3D caches remote chunks in /root/.VC3D/remote_cache (VC3D's default); 28 GB free there
```

and with `RUNPOD_POD_ID` set, the same line ended `RunPod: outside /workspace, on the container disk, which "is cleared when the Pod stops"; set remote_cache_dir in VC3D.ini to a folder under /workspace to keep the cache (https://docs.runpod.io/pods/storage/types)`. With the speed test on it also printed `[pass] cacheio /root: write 469 MB/s, read 3007 MB/s`. No AMD or Intel card was available to run it on; those paths are tested with stand-ins only (Tests).

It worked when the last line is `overall: pass`, `overall: warn` or `overall: fail`. Read each `warn` and `fail` line; each says what is missing.

## Checks and controls

- **Every check can fail, and the tests show it** (`DoctorTest`): no GPU gives `fail`, an 8 GB card `warn` and a 12 GB card `pass`; a folder without `vesuvius/` and `volume-cartographer/` gives `fail` and one with them `pass`; 15.6 GB of memory passes and 8 GB warns.
- **Run against stand-ins on 2026-10-16** (synthetic inputs, this container): an `nvidia-smi` reporting a GTX 1080 (8,192 MiB) gave `[warn] gpu ... Below 12 GB`, one that exited with code 9 gave `[fail] gpu`, a `VILLA` folder without the two subfolders gave `[fail] villa` and exit code 1, and a `PATH` without uv gave `[warn] tools   missing: uv`.
- **The non-NVIDIA paths can fail and are never a pass** (`tests/test_doctor_gpus.py`): rocm-smi JSON for two cards parses to their names and MiB; an AMD card warns (and says when torch is not a ROCm build or the card is under 12 GB), an Intel card warns, ROCm with no card warns, nothing at all fails, and an NVIDIA card still passes. The cache folder follows VC3D's order in every branch; a `cache.json` VC3D would refuse (wrong version, relative root, not JSON) fails; under 25 GB warns; each RunPod storage case gives its own quoted sentence.
- **A real failure on record:** in the cloud session that built this repository on 2026-10-06 it printed `[fail] gpu No NVIDIA GPU found` ([error log](../logs/errors.md)).
- **What a pass does not show:** that CUDA, PyTorch or villa's inference work. The control run (w035, step 1 of [plan](plan.md)) shows that; it in turn shows only that the pipeline runs, since w035 is a training segment ([log](../logs/2026-10-07-w035-cpu.md)).

Claim label: None for the report, which describes this machine and makes no claim about scrolls. Its 12 GB GPU and 25 GB disk thresholds are Sourced facts (Bullo27's first-letters-survey on an RTX 3060 12 GB; scrollprize.org/tutorial5).

## Commands and options

### `python -m kit doctor`

```
usage: python -m kit doctor [-h] [--disk DISK] [--no-speed] [--remote]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--disk DISK` | `.` | Path whose file system's free space is checked: the current folder by default. Point it at where volumes, renders and VC3D's cache will go. Also where the disk speed test writes its 64 MB file. A path that does not exist stops with a `FileNotFoundError` traceback and exit code 1 |
| `--no-speed` | off | Skip the 64 MB disk speed test (the `speed` and `cacheio` lines) |
| `--remote` | off | On a rented or cloud machine: also check where VC3D will cache streamed chunks (`cache`), its speed (`cacheio`, with the speed test, when it is on another folder than `--disk`), and on RunPod whether it survives a stop |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `VILLA` | unset, which gives `warn` | Path of a villa checkout. `pass` when it holds both `vesuvius/` and `volume-cartographer/` folders, `fail` otherwise. An empty value is read as the current folder |
| `VC_BIN` | unset, which gives `warn`; on Apple Silicon, `/Applications/VC3D.app/Contents/MacOS` when that folder exists | Folder of VC3D's command-line tools. `pass` when both `vc_grow_seg_from_seed` and `vc_render_tifxyz` are in it, `warn` otherwise. Never `fail` |
| `PATH` | the shell's | Searched for `nvidia-smi`, `rocm-smi`, `git`, `uv` and `docker` (`shutil.which`) |
| `HOME`, `VC3D_CONFIG_DIR` | the user's home; unset | With `--remote`: where VC3D's `cache.json` and `VC3D.ini` are looked for (`VC3D_CONFIG_DIR`, else `HOME/.VC3D`) |
| `RUNPOD_POD_ID`, `RUNPOD_VOLUME_ID` | unset | With `--remote`: set by RunPod on a pod and when a network volume is attached; they choose the RunPod sentence on the `cache` line |

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
| `check_gpu(found, apple_silicon=False, amd=(), xpu=(), hip=None, rocm=False)` | `(status, detail)` | Nothing | With NVIDIA cards in `found`: `pass` when the largest has at least `MIN_GPU_MB` (12,288 MiB), `warn` below. Without: `warn` for AMD cards in `amd` (naming `hip`, the ROCm version of torch, or saying torch is not a ROCm build), for Intel cards in `xpu`, for `rocm` (ROCm installed, no card listed), and on Apple Silicon; `fail` otherwise |
| `parse_rocm_smi(text)` | list of `(name, memory_mb)` | Nothing | From `rocm-smi --showproductname --showmeminfo vram --json`: `cardN` entries, name from `Card Series` (else `Device Name`, `Card Model`), memory from `VRAM Total Memory (B)` (0 when absent); `[]` for text that is not JSON |
| `amd_gpus(run=subprocess.run, which=shutil.which)` | list of `(name, memory_mb)` | Nothing | Runs rocm-smi (20 s timeout) when `which` finds it; `[]` when absent or failing |
| `torch_gpus()` | `{"hip", "amd", "xpu"}` | Nothing | Imports torch; `hip` is `torch.version.hip`; `amd` lists `torch.cuda` devices only on a ROCm build; `xpu` lists `torch.xpu` devices. All empty without torch or on a driver error |
| `rocm_present(exists=os.path.exists)` | bool | Nothing | `/dev/kfd` or `/opt/rocm` exists |
| `vc3d_cache_root(env=None, exists=os.path.exists, read=...)` | `(Path, how)` | `ValueError` for a `cache.json` that is not JSON, not version 1, or has a relative root | VC3D's order, in What it does; `how` says which rule chose the folder |
| `check_cache(env=None, exists=os.path.exists, disk_usage=shutil.disk_usage, read=None)` | `(status, detail)` | Nothing | `fail` for a `cache.json` VC3D refuses, `pass` at 25 GiB free in the folder's nearest existing parent, `warn` below; adds the RunPod sentence when `RUNPOD_POD_ID` is set |
| `check_disk(path)` | `(status, detail)` | `FileNotFoundError` (or another `OSError`) for a path that does not exist or cannot be read | `pass` at 25 GiB free (`MIN_DISK_GB`) or more, `warn` below; never `fail` |
| `check_ram(gb, apple_silicon=False)` | `(status, detail)` | Nothing | `pass` when `round(gb)` is at least 16 (`MIN_RAM_GB`), so a "16 GB" machine that reports 15.6 GiB passes; `warn` below or for `None` |
| `check_tools(which=shutil.which)` | `(status, detail)` | Nothing | `pass` when `git`, `uv` and `docker` (`TOOLS`) are all found, `warn` listing the missing ones |
| `check_villa(path)` | `(status, detail)` | Nothing | `warn` for `None`, `pass` for a folder with both subfolders, `fail` otherwise |
| `check_vc_bin(path, apple_silicon=False)` | `(status, detail)` | Nothing | `pass` or `warn`, never `fail`; on Apple Silicon a `None` path falls back to `MAC_VC_BIN` when that folder exists |
| `sysctl(name, run=subprocess.run)` | str or None | Nothing | `sysctl -n NAME` on macOS (5 s timeout); None when it fails or is absent |
| `check_rosetta(system=None, machine=None, read=sysctl, torch_info=None)` | None off macOS, else `(status, detail)` | Nothing | `fail` when this Python is an Intel build under Rosetta on an Apple Silicon Mac (`sysctl.proc_translated` is 1, or `platform.machine()` is not arm64 while `hw.optional.arm64` is 1); `warn` when torch is installed but has no usable MPS; `pass` otherwise |
| `cpu_quota(root='/sys/fs/cgroup', proc='/proc/self/cgroup')` | float CPUs, or None when unlimited or unknown | Nothing | The smallest quota from this process's own cgroup up to the root: cgroup v2 `cpu.max`, or v1 `cpu.cfs_quota_us` over `cpu.cfs_period_us` |
| `check_threads(visible=None, quota=None, env=None)` | `(status, detail)` | Nothing | `warn` when the quota is under 0.9 of the CPUs Python sees and `NUMBA_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` and `OPENBLAS_NUM_THREADS` (`THREAD_VARS`) are not all set at or below it; the detail gives the export line |
| `check_disk_speed(path, nbytes=SPEED_BYTES, clock=time.perf_counter)` | `(status, detail)` | Nothing | Writes and syncs a temporary file of `SPEED_BYTES` (64 MiB), drops it from the page cache (`posix_fadvise` on Linux, `F_NOCACHE` on macOS), reads it back and deletes it; `warn` under `MIN_READ_MBS` (200 MB/s) or when the file cannot be written |
| `run_checks(env=None, disk_path='.', speed=True, remote=False)` | list of `(name, status, detail)`: `rosetta` (macOS only), `threads` (Linux only), `speed` (unless `speed=False`), `cache` and `cacheio` (with `remote=True`), then `gpu`, `memory`, `disk`, `tools`, `villa`, `vc_bin`, in that order | As `check_disk` | `env` (default `os.environ`) supplies `VILLA`, `VC_BIN` and the `--remote` variables; the GPU, memory, platform and `PATH` are always this machine's |
| `format_report(results)` | `(text, worst)`, `worst` one of `pass`, `warn`, `fail` | Nothing | The text the command prints, ending in `overall: WORST` |

Module constants: `SPEED_BYTES = 64 << 20`, `MIN_READ_MBS = 200`, `THREAD_VARS`, `MIN_GPU_MB = 12 * 1024`, `MIN_DISK_GB = 25`, `MIN_RAM_GB = 16`, `TOOLS = ("git", "uv", "docker")`, `MAC_VC_BIN = Path("/Applications/VC3D.app/Contents/MacOS")`, and the status words `PASS`, `WARN`, `FAIL` (`"pass"`, `"warn"`, `"fail"`).

## Inputs

| Input | Where it comes from | Notes |
| --- | --- | --- |
| GPUs | `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits` | One line per card, `NAME, MEMORY_MIB` |
| AMD and Intel GPUs | `rocm-smi --showproductname --showmeminfo vram --json`; torch (`torch.version.hip`, `torch.cuda`, `torch.xpu`) | Only when no NVIDIA GPU was found and not on Apple Silicon |
| VC3D's cache folder | `cache.json` and `VC3D.ini` in `$VC3D_CONFIG_DIR` or `~/.VC3D`; `/volpkgs`, `/ephemeral` | With `--remote` |
| Physical memory | `os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")` | Not available on Windows |
| Free disk | `shutil.disk_usage(--disk)` | The free space of the file system that holds the path |
| Tools | `shutil.which` on `PATH` | `git`, `uv`, `docker` |
| villa and VC3D paths | `VILLA`, `VC_BIN` | See Environment variables |
| Platform | `platform.system()`, `platform.machine()` | Apple Silicon is `Darwin` on `arm64` |

## Outputs

Text on stdout, one line per check, `[STATUS] NAME    DETAIL` (status right-aligned in 4 characters, name left-aligned in 7), then a blank line and `overall: STATUS`. There is no JSON form; in Python, `run_checks()` gives the same as tuples.

| Check | `pass` when | `warn` when | `fail` when |
| --- | --- | --- | --- |
| `rosetta` (macOS only) | Python is arm64 (and torch, when installed, sees the MPS GPU), or an Intel Mac | arm64 Python whose torch lacks MPS, or MPS not available | An Intel-build Python running under Rosetta on Apple Silicon |
| `threads` (Linux only) | No CPU quota below the CPUs Python sees, or the four thread variables already set to fit it | A smaller quota without matching thread variables | Never |
| `speed` | Read back at 200 MB/s or more | Slower, or the test file could not be written | Never |
| `cache` (`--remote`) | 25 GiB or more free where VC3D will cache chunks | Less | A `cache.json` VC3D would refuse |
| `cacheio` (`--remote`, speed test on) | As `speed`, on the cache folder's disk | As `speed` | Never |
| `gpu` | The largest NVIDIA card has 12,288 MiB or more | An NVIDIA card below 12 GB; an AMD or Intel GPU; ROCm with no card listed; or no GPU on Apple Silicon | No GPU found, not on Apple Silicon |
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
| `[fail] gpu     No GPU found (nvidia-smi, rocm-smi and torch found none). Ink inference needs CUDA; see docs/compute.md for rentals.` (before 24 Oct 2026: `No NVIDIA GPU found (nvidia-smi absent or failed)...`) | `nvidia-smi` is not on `PATH`, exited non-zero, took over 20 s, or printed nothing it could read, and neither rocm-smi nor torch listed another GPU | Expected on a laptop or a cloud session: GPU steps go to Modal through a run spec (the Modal rule). On a GPU machine, install the NVIDIA driver and run `nvidia-smi` by hand |
| `[warn] gpu     AMD GPU (ROCm): NAME N GB. ... villa's spiral fitting asks for an NVIDIA GPU (scrollprize.org/tutorial_spiral); other villa steps are not tested on it here` | An AMD card, found by rocm-smi or a ROCm build of torch | Expect to test each villa step; ScrollFiesta has a HIP backend ([tracing tools](../tracing-tools.md)). For spiral fitting, rent an NVIDIA GPU |
| `... this Python's torch is not a ROCm build: install one from https://pytorch.org` inside the AMD line | rocm-smi lists the card but this torch was built for CUDA or CPU | Install the ROCm wheel that pytorch.org lists for your ROCm version |
| `[warn] gpu     Intel GPU (torch.xpu): NAME N GB. villa's spiral fitting asks for an NVIDIA GPU ...` | torch sees an Intel GPU | As for AMD |
| `[warn] gpu     ROCm is installed (/dev/kfd or /opt/rocm) but neither rocm-smi nor torch listed an AMD GPU: check the driver with rocm-smi, and that this user is in the video and render groups` | ROCm is present but no card was listed | Run `rocm-smi` by hand; add the user to the `video` and `render` groups |
| `[fail] cache   PATH/cache.json does not read as JSON: ERROR` or `[fail] cache   PATH/cache.json needs version 1 and an absolute root; VC3D refuses it otherwise` | With `--remote`: a `cache.json` VC3D itself would refuse | Fix or remove that file |
| `[warn] cache   VC3D caches remote chunks in PATH (HOW); N GB free there. Under 25 GB: a long trace can fill it` | With `--remote`: little space where VC3D caches | Set `remote_cache_dir` under `[viewer]` in `VC3D.ini` to a bigger disk |
| `RunPod: outside /workspace, on the container disk, which "is cleared when the Pod stops"; ...` at the end of the cache line | With `--remote` on RunPod: the cache will be lost at the next stop | Set `remote_cache_dir` to a folder under `/workspace` if you want it kept |
| `[warn] gpu     NAME N GB. Below 12 GB: use batch size 1 or rent a GPU.` | The largest card has under 12,288 MiB | Use `--batch 1` in [plan](plan.md), or run the GPU steps on Modal |
| `[warn] gpu     Apple Silicon, no CUDA. Runs locally: VC3D app, rendering, lasagna (--device mps). Stock villa ink inference uses the CPU; open PRs #1865/#1812 add MPS. Full segments: rent a GPU. See docs/mac.md` | A Mac with Apple Silicon. The PR statuses in this text date from 2026-10-07 | Follow [mac.md](../mac.md) and `python -m kit plan SCROLL --mac`; full segments go to Modal |
| `[warn] memory  could not read installed memory` | `os.sysconf` is missing (Windows) or failed | Check memory by hand |
| `[warn] memory  N GB memory` | Under 16 GB after rounding | Small renders only; heavy CPU work goes to Modal |
| `[warn] disk    N GB free at PATH (one tutorial segment is about 25 GB)` | Under 25 GiB free on that file system | Free space, or point `--disk` and your work folder at a bigger disk |
| `[fail] rosetta this Python is an Intel build running under Rosetta: no MPS GPU and slow NumPy. Install an arm64 Python ...` | On an Apple Silicon Mac, this Python (often an old Anaconda or an Intel Homebrew in /usr/local) is an x86_64 build | Install an arm64 Python, make a new venv with it, reinstall packages; check `python3 -c 'import platform; print(platform.machine())'` prints arm64 |
| `[warn] rosetta arm64 Python, but this torch has no MPS support: pip install --upgrade torch` | An old or CPU-only torch wheel | Upgrade torch in the venv |
| `[warn] rosetta arm64 Python, torch has MPS but it is not available (macOS 12.3 or newer is needed)` | macOS older than 12.3, or a broken torch install | Update macOS, or reinstall torch |
| `[warn] threads N CPUs visible but the CPU quota is Q: Numba, OpenMP and torch start N threads and wait on the quota. Before running: export ...` | A container whose CPU quota is smaller than the machine's CPUs (Docker `--cpus`, RunPod, a cloud job) | Paste the export line before the run, and call `torch.set_num_threads` as printed |
| `[warn] speed   PATH: write W MB/s, read R MB/s. Under 200 MB/s: keep volume chunk caches on a local SSD ...` | `--disk` is on a network, overlay or synced file system | Point caches and work folders at a local disk, or pass `--disk` there |
| `[warn] speed   could not write a test file under PATH: ERROR` or `disk speed test under PATH failed: ERROR` | `--disk` is read-only or full | Point `--disk` at a writable folder, or pass `--no-speed` |
| `... (read may come from memory: this system cannot drop the file from its cache)` at the end of the speed line | The system has neither `posix_fadvise` nor `F_NOCACHE` (Windows), so the read speed can be the page cache's | Treat the read number as an upper bound |
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
7. `rosetta` (macOS), `threads` (Linux) and `speed` run first: `sysctl` for Rosetta, `/proc/self/cgroup` and the cgroup files for the quota, and a 64 MiB write, `fsync`, cache drop and read for the disk.
8. `format_report` writes the lines and takes the worst status (`fail` over `warn` over `pass`); `cmd_doctor` prints it and returns 1 when the worst is `fail`, 0 otherwise.

## Cost and time

With the disk speed test: 0.29 to 0.52 s per call (3 runs, `--disk /tmp`, measured 2026-10-23, 4-core Xeon cloud container, which read the test file back at 2,888 MB/s); `--no-speed` 0.14 s. The test writes 64 MiB and deletes it. Measured 2026-10-16 in a 4-core Xeon cloud container with no `nvidia-smi`: 0.34 to 0.43 s per call over 5 runs, almost all Python start-up and the import of `kit.cli`. On a machine with `nvidia-smi`, add that program's run time; the call gives up after 20 s. It rents nothing and runs anywhere.

## For agents

- **Command:** `python -m kit doctor --disk WORK_DIR`. There is no JSON form; in Python, `from kit import doctor; doctor.run_checks(disk_path="WORK_DIR")` returns `(name, status, detail)` tuples.
- **Parse:** each line `[STATUS] NAME DETAIL` (STATUS is `pass`, `warn` or `fail`; NAME is `rosetta`, `threads`, `speed`, `cache`, `cacheio`, `gpu`, `memory`, `disk`, `tools`, `villa` or `vc_bin`) and the last line `overall: STATUS`.
- **Rerun:** Safe; it only reads the machine's state.
- **Success:** Exit code 0 with `overall: pass` or `overall: warn`. Exit code 1 with an `overall: fail` line is a finished report; exit code 1 without that line is a crash (see Failure modes).
- **Not a pass:** `overall: pass` does not mean CUDA, PyTorch or villa's inference work; only the control run shows that. A `gpu` pass says nothing about whether the card is free or the driver matches villa's PyTorch.
- **Go-ahead:** Nothing for the check. Renting the GPU its messages suggest needs Chase's budget decision (the go-ahead rule, hard rule 8).
- **Never:** Try to sign in to Modal from a Claude cloud session because `gpu` failed (the Modal rule, hard rule 11): write a run spec instead; run hours of GPU work on a laptop CPU because the other checks passed.

## Tests

```bash
python -m unittest tests.test_kit.DoctorTest tests.test_qol_tools.TestDoctor tests.test_doctor_gpus -v
```

`tests/test_doctor_gpus.py` covers rocm-smi parsing and its absent or failing runs, the AMD, Intel and ROCm-without-card warnings and the no-GPU failure, VC3D's cache folder order (default, `/ephemeral`, `/volpkgs`, `VC3D.ini` with a comment and quotes, `cache.json` under `VC3D_CONFIG_DIR`), the refused `cache.json` cases, low space, the three RunPod storage cases, and that `--remote` adds the `cache` line. No real AMD or Intel card was tested.


`tests/test_qol_tools.py` (`TestDoctor`) covers the Rosetta check (off macOS, a translated Intel build, arm64 with and without MPS, an Intel Mac), the thread warning and its export line, the CPU quota read from a fake cgroup tree (a v1 quota under the process's own cgroup, an unlimited and a limited v2 `cpu.max`), and the speed check on a real temporary file (it leaves nothing behind; a fake slow clock warns). Six older tests cover `nvidia-smi` parsing, the 12 GB threshold (fail, warn, pass), Apple Silicon reported as a warning that points to `docs/mac.md`, the memory rounding (15.6 passes, 8 warns, unreadable warns, "shared with the GPU" on a Mac), villa checkout detection, and the overall verdict. They do not cover `check_disk`, `check_tools`, `check_vc_bin`, `run_checks`, the command line or its exit codes, or a real `nvidia-smi`.

## History

- 2026-10-24: AMD (rocm-smi, ROCm torch) and Intel (torch.xpu) GPUs reported as warnings instead of "No NVIDIA GPU found", a warning for ROCm with no card listed, and `--remote` with the `cache` and `cacheio` lines (`0da03d1`).
- 2026-10-23: three checks for silent slowdowns: `rosetta` (an Intel Python on an Apple Silicon Mac), `threads` (a container CPU quota smaller than the CPUs Python sees) and `speed` (a 64 MB disk read test), with `--no-speed` (`3376687`).
- 2026-10-14: `scrolls-workbench doctor` in the installable package (`2582ab7`, [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58)).
- 2026-10-07: the Apple Silicon path: on a Mac the GPU check warns instead of failing, a memory check (16 GB) is added, and VC3D's tools are found inside VC3D.app (`e8f3dda`, [PR #1](https://github.com/ChaseHendrick/Scrolls/pull/1)).
- 2026-10-06: first version: the NVIDIA GPU (12 GB), free disk (25 GB), git, uv and docker, `VILLA` and `VC_BIN` checks (`2daee8e`).

## Related

- [mac.md](../mac.md): what runs on an Apple Silicon Mac, and the open villa PRs for MPS inference.
- [compute.md](../compute.md): hardware that has run the workflow, and costs from published runs.
- [tracing tools](../tracing-tools.md): which tracing tools run on a Mac, an AMD GPU or a CPU.
- [plan](plan.md): the run plan whose steps these checks prepare for, and `kit cost`.
- [prizes](prizes.md): the other first command of a session.
- [mac-verify](mac-verify.md): runs the w035 control on a Mac in one command.
- [scroll-session](scroll-session.md): the session skill that runs this check.
- [error log](../logs/errors.md): the first recorded `fail` on the setup session's machine.
