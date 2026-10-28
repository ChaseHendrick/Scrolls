# mac-verify: check on a Mac that villa's MPS ink inference gives the CPU's map

`scripts/mac-verify.sh` runs `ink_9um` seed 42 on PHerc0139 w035 with villa `main` at a pinned commit, once forced onto the CPU and twice on the Mac GPU, then checks both pairs with `kit verify` against a reverse-depth control and prints a summary to paste.

| Field | Value |
| --- | --- |
| Id | `mac-verify` |
| Status | Current |
| Kind | script |
| Area | Scoring and controls |
| Run | `bash scripts/mac-verify.sh` |
| Code | `scripts/mac-verify.sh` |
| Tests | `tests/test_mac_scripts.py` (runs the script off a Mac with stubs for git, uv, uname and the venv's Python: a failing verdict fails it, `PYTORCH_ENABLE_MPS_FALLBACK` is unset for every inference, the shared GPU lock, villa `main` at the pinned commit, the forced CPU arm and the device checks); `tests/test_repo.py` (it parses with `bash -n` and uses no bash 4 syntax) |
| Needs | An Apple Silicon Mac (macOS, arm64) with git and uv (`brew install uv`); about 3 GB free in `WORK` (script header). The script itself builds the rest: villa (`main` at a pinned commit), a Python 3.14 virtual environment with villa's `models` extra minus `volume-cartographer`, `cucim`, `nnunetv2` and `batchgeneratorsv2`, plus tifffile and imagecodecs; the published w035 surface volume and the `ink_9um` seed 42 checkpoint |
| Runs on | Apple Silicon Mac only (or any machine with `EXPECT_GPU=cpu`, to test the script). On an Apple M1 Pro: CPU 1,740 s for both directions, MPS 218 s and 212 s forward ([w035 log](../logs/2026-10-07-w035-cpu.md), 2026-10-07), plus the downloads |
| Network | `github.com` (clones and fetches `ScrollPrize/villa`); `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (the w035 surface volume, through `kit fetch`); `huggingface.co` (the checkpoint `scrollprize/ink_9um`, through `uvx --from huggingface_hub hf download`); the Python package index and uv's Python downloads (the environment). Nothing is uploaded |
| Writes | Under `WORK` (default under Environment variables): `villa/` (a clone; the script checks out `VILLA_REV` detached), `venv/`, `models-reqs.txt`, `checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth`, `data/w035_9um.zarr/`, `predictions/w035_cpu.tif`, `predictions/w035_cpu_reverse.tif`, `predictions/w035_gpu_a.tif`, `predictions/w035_gpu_b.tif`, `logs/cpu.log`, `logs/gpu_a.log`, `logs/gpu_b.log`, `results/cpu_vs_gpu.json`, `results/gpu_repeat.json`, `results/summary.txt`, and the lock folder `.gpu-job.lock/` while it runs. uv also fills its own cache |
| Go-ahead | Not needed to run it on your own Mac. Posting its summary, for example on villa, needs Chase's yes (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-07 |
| Guide | [mac.md, "One command"](../mac.md#one-command) and its [runbook](../mac.md#runbook-verify-mps-against-cpu-on-the-control-segment) |
| Checked | 2026-10-16 against commit `0747c06` |

## What it does

villa's ink inference (`python -m vesuvius.ink_detection.inference.infer`) uses the Apple GPU through PyTorch's MPS (Metal Performance Shaders) backend since [villa PR #1865](https://github.com/ScrollPrize/villa/pull/1865) merged into `main` on 2026-10-08 (commit `860f52cbf`; [#1812](https://github.com/ScrollPrize/villa/pull/1812), merged the same day, does the same for `ink-detection/optimized_inference`). It picks CUDA, then MPS, then the CPU by itself, through villa's `get_accelerator()`. Before anyone trusts a map made on MPS, the same model on the same input should give the same map on the CPU. This script answers that in one command on an Apple Silicon Mac.

It runs the released 9 um ink model `ink_9um` (seed 42, step 75,000) on the published 9.362 um surface volume of PHerc0139 segment w035: with villa `main` at a pinned commit (`VILLA_REV`, by default `860f52cbf`, the merge of PR #1865): once forced onto the CPU, in both depth directions, and twice on MPS, forward only. villa has no device option for this entry point (`--gpus` takes CUDA ids only), so the CPU run starts villa's own entry point with `torch.backends.mps.is_available` returning False and `CUDA_VISIBLE_DEVICES` empty; `get_accelerator()` then falls through to the CPU, and villa's code is unchanged. Each run's log must name the device the run was meant to use (`Using CPU device` or `Using MPS device`), so neither arm can quietly run on the other device. It then runs [`verify`](verify.md) twice, CPU against the first MPS run and the first MPS run against the second, each with the CPU's reverse-direction map as the control, and prints a summary of chip, versions, commits, checkpoint hash, times and verdicts.

w035 is a training segment of `ink_9um`, so its map shows the model reproducing its training labels ([w035 log](../logs/2026-10-07-w035-cpu.md)). That does not matter here: a device comparison needs only the same input on both devices. A `pass` says the Mac GPU reproduces the CPU's map; it says nothing about whether either map shows ink, and an ink map is model output, not a reading.

It does not score against labels, does not run v8in, and does not reuse finished maps (every run redoes all three inference passes). It takes the same GPU lock as [mac-w045](mac-w045.md), `WORK/.gpu-job.lock`, so it will not start while another GPU job of these scripts runs.

## When to use it

- You have an Apple Silicon Mac and want to know whether villa's MPS inference matches the CPU on your chip and torch version, with a control and a repeat.
- Before moving the villa pin: `VILLA_REV=origin/main bash scripts/mac-verify.sh` checks the newest villa `main`.
- After a torch or macOS update, to recheck that MPS still matches.

Do not use it:

- To test whether a model finds ink it was not trained on: use [mac-w045](mac-w045.md), which scores against labels with [`auc`](auc.md).
- To compare two maps you already have: run [`verify`](verify.md) directly.
- On a Linux or CUDA machine for a real result: it refuses without `EXPECT_GPU=cpu`, and with it the "GPU" runs are CPU runs.
- While [mac-w045](mac-w045.md) or [mac-phase0](mac-phase0.md) is running on the same Mac with the same `WORK`: it finds their GPU lock and stops with exit code 3. With another `WORK` the lock does not cover them, and two GPU jobs at once can run out of memory.

## Quick start

```bash
git clone https://github.com/ChaseHendrick/Scrolls && cd Scrolls
brew install uv
bash scripts/mac-verify.sh
```

It takes no arguments. Run it from anywhere; it finds the Scrolls checkout from its own path.

It could not be run end to end while writing this page: it needs an Apple Silicon Mac and about 1 GB of downloads. On this page's Linux container (x86_64, 2026-10-16) it stopped at the first check, as it should:

```
This needs an Apple Silicon Mac (or EXPECT_GPU=cpu to test the script elsewhere).
exit 2
```

On a Mac it prints a header for each of its six steps (`== 1/6 villa main at VILLA_REV` to `== 6/6 kit verify`) and ends with a summary in this form (from the code; capitals are filled in by the run):

```
kit mac-verify summary (paste this)
chip: CHIP | os: OS | torch: TORCH mps available: True
villa main VILLA_SHA | reference on cpu (forced) | runs on mps | ckpt seed42 step-075000 sha256 CKPT_SHA
times: cpu both directions T_CPUs | gpu forward T_As, T_Bs
cpu_vs_gpu: verdict VERDICT (exit CODE) | max|diff| MAX | over tol SHARE% | pearson R | control over tol CONTROL%
gpu_repeat: verdict VERDICT (exit CODE) | max|diff| MAX | over tol SHARE% | pearson R | control over tol CONTROL%
```

It worked when both result lines read `verdict pass (exit 0)` and the control share is large (73.12 % on the recorded M1 Pro run). The script exits 0 only when both `kit verify` checks pass; a `fail` or `control-not-caught` verdict ends it with exit code 1 after the summary.

## Checks and controls

- **Reverse-depth control.** Both `kit verify` calls pass `--control WORK/predictions/w035_cpu_reverse.tif`, the CPU map with the surface volume's layers in reverse order. Agreement counts as `pass` only when that control is caught by the same test (at most 0.01 % of pixels more than 2 gray levels apart; see [`verify`](verify.md)). A control that agrees gives `control-not-caught`.
- **Repeat.** `gpu_repeat` compares two MPS runs, which catches nondeterminism, such as a torch bug that reads freed memory.
- **Each run on its own device.** villa's `get_accelerator()` prints the device it picked. The CPU run's log must say `Using CPU device` and each GPU run's log `Using MPS device`; otherwise the script stops with exit code 1, so a GPU run cannot quietly fall back to the CPU and the CPU reference cannot quietly run on MPS (which villa `main` would pick by itself). Like [mac-w045](mac-w045.md), it unsets `PYTORCH_ENABLE_MPS_FALLBACK` at the start, so an op MPS lacks fails instead of running on the CPU.
- **Recorded pass.** Before the pin, when the CPU arm ran stock villa `main` (CPU only then) and the GPU arm the PR head: Apple M1 Pro, macOS 27.0, torch 2.14.1, villa `main` `e0bbb8b40` and PR #1865 `6723ad158`: CPU against MPS `pass` with max |diff| 1 and Pearson 0.99999999; MPS repeat bit-identical; control 73.12 % of pixels over tolerance ([w035 log](../logs/2026-10-07-w035-cpu.md); `device_checks` in [`results.json`](../results.json)).
- **What a caught control looks like.** On w035 the CPU forward map against its reverse: max |diff| 167, mean 21.6692, 73.117458 % of pixels over 2, Pearson 0.511578 ([w035 log](../logs/2026-10-07-w035-cpu.md)).

Claim label: Model output, for the agreement of the CPU and MPS runs of `ink_9um` on w035; a `pass` is about the device, not about ink.

## Commands and options

### `bash scripts/mac-verify.sh`

The script takes no arguments and has no `--help`: anything after the script name is ignored and the run starts. It is configured only by the environment variables below.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `WORK` | `$HOME/scrolls-work` | Folder for villa, the environment, data, checkpoint, maps, logs and results. Shared with [mac-w045](mac-w045.md) |
| `EXPECT_GPU` | `mps` | `mps` requires `Darwin/arm64`; the CPU run must log `Using CPU device` and the GPU runs `Using MPS device`. `cpu` lets the script be tested off a Mac: every run is forced onto the CPU and must log `Using CPU device`. Any other value stops with exit code 2 |
| `VILLA_REV` | `860f52cbfccb6a878032de12467d5e2f3d995560` | The villa commit to run, which must be on villa `main`. The default is the merge of PR #1865, whose ink inference code matches the PR's final head; `VILLA_REV=origin/main` runs the newest `main` |

## Python API

Not applicable: a shell script with no importable functions; see Commands and options.

## Inputs

| Input | Where it comes from | Notes |
| --- | --- | --- |
| w035 surface volume | `kit fetch w035` from the open-data bucket (alias `W035_9UM` in `kit/fetch.py`), to `WORK/data/w035_9um.zarr` | 9.362 um, 2,223 objects, 1.02 GB, shape 28 x 5,820 x 5,240 ([w035 log](../logs/2026-10-07-w035-cpu.md)). A rerun skips files already there at the listed size |
| Checkpoint | `scrollprize/ink_9um`, file `hybrid_3d2d-seed42/step-075000.pth`, to `WORK/checkpoints/ink_9um/` | Downloaded only when missing; its SHA-256 goes into the summary |
| villa | `https://github.com/ScrollPrize/villa.git`, `origin/main`, checked out at `VILLA_REV` | `main` is fetched on every run and `VILLA_REV` must be a commit on it; the summary records its short commit |

The inference settings are fixed in the script: `--overlap 0.5 --blend-mode hann --batch-size 1 --no-compile`, and `--direction both` for the CPU run only.

## Outputs

The run prints step headers, `torch VERSION mps available: BOOL`, `CPU: Ns for both directions`, `GPU runs: Ns and Ns (forward only)`, then the summary (see Quick start), which is also saved to `WORK/results/summary.txt`.

| File | What it holds |
| --- | --- |
| `WORK/predictions/w035_cpu.tif`, `w035_cpu_reverse.tif` | CPU maps, villa forced onto the CPU, forward and reverse (villa names the reverse map) |
| `WORK/predictions/w035_gpu_a.tif`, `w035_gpu_b.tif` | The two forward maps on MPS, the device villa picks by itself |
| `WORK/logs/cpu.log`, `gpu_a.log`, `gpu_b.log` | villa's output for each inference run, overwritten each run |
| `WORK/results/cpu_vs_gpu.json`, `gpu_repeat.json` | `kit verify --json` output; fields in [`verify`](verify.md#outputs) |
| `WORK/results/summary.txt` | The summary to paste |

The summary's result lines read, from each JSON: `verdict`, the `kit verify` exit code, `candidate.max_abs_diff`, `candidate.fraction_over_tolerance` (as a percentage, six decimals), `candidate.pearson` and `control.fraction_over_tolerance` (two decimals).

| Exit code | Meaning |
| --- | --- |
| `0` | The script finished, printed the summary, and both `kit verify` checks exited 0 (`verdict pass`) |
| `1` | A `kit verify` check did not pass (printed after the summary), an inference run failed, a run's log did not name the device it was meant to use, or a later command failed under `set -e` (such as the summary step when a `kit verify` JSON is empty) |
| `2` | Not an Apple Silicon Mac (without `EXPECT_GPU=cpu`), `EXPECT_GPU` not `mps` or `cpu`, `VILLA_REV` not a commit on villa `main`, or git or uv is missing; also `kit fetch`'s own code 2 for a failed download |
| `3` | Another run holds the GPU lock `WORK/.gpu-job.lock` |
| Other | The code of whichever command failed under `set -e`, such as git |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `This needs an Apple Silicon Mac (or EXPECT_GPU=cpu to test the script elsewhere).`, exit code 2 | `uname -s`/`uname -m` is not `Darwin/arm64` and `EXPECT_GPU` is `mps` | Run it on an Apple Silicon Mac; set `EXPECT_GPU=cpu` only to test the script |
| `git is missing (xcode-select --install)`, exit code 2 | No git on `PATH` | Install the Xcode command line tools |
| `uv is missing: brew install uv`, exit code 2 | No uv on `PATH` | `brew install uv` |
| `Another run is using the GPU (pid PID: COMMAND).` then `Wait for it, or stop it: kill PID`, exit code 3 | A live process holds `WORK/.gpu-job.lock`, such as a [mac-w045](mac-w045.md) run or another mac-verify run | Wait, or stop that run |
| `Taking over a stale lock left by pid PID.` | The lock's process is gone | Nothing; the run continues |
| `inference failed, see WORK/logs/LOG.log` then the log's last 20 lines, exit code 1 | villa's inference exited non-zero (a missing package, out of memory, an MPS op error) | Read the log; paste its last 20 lines when asking for help |
| `WORK/logs/LOG.log: villa ran on DEVICE, expected EXPECTED; see the log`, exit code 1 | The run's log names another device than the run needs (`cpu` for the reference, `EXPECT_GPU` for the others), or none (`an unnamed device`): a GPU run that fell back to the CPU, a CPU run that reached MPS, or a villa whose `get_accelerator()` no longer prints `Using ... device` | Check `torch ... mps available: True` in the output and `vesuvius/src/vesuvius/models/utilities/get_accelerator.py` at `VILLA_REV` |
| `EXPECT_GPU must be mps or cpu`, exit code 2 | `EXPECT_GPU` has another value | Leave it unset on a Mac; `EXPECT_GPU=cpu` only to test the script |
| `villa main has no commit VILLA_REV`, exit code 2 | `VILLA_REV` is not a commit, or not one on villa `main` | Unset it for the pinned commit, or give `origin/main` or a commit of `main` |
| A Python `json.decoder.JSONDecodeError` traceback after `== 6/6 kit verify`, exit code 1 | A `kit verify` call exited 2 (an unreadable map), so its JSON file is empty and the summary step cannot read it | Run the `kit verify` command by hand with `WORK/venv/bin/python -m kit verify ...` to see its message |
| `kit verify did not pass (cpu_vs_gpu exit V1, gpu_repeat exit V2); see the summary above and WORK/results` on stderr, exit code 1 | At least one check's verdict is not `pass`; the summary lines above it say which | See the rows below |
| `cpu_vs_gpu: verdict fail (exit 1)` in the summary | More than 0.01 % of pixels differ by more than 2 gray levels between CPU and MPS | Use the CPU result; report the difference to villa (after Chase says yes) |
| `gpu_repeat: verdict fail (exit 1)` | Two MPS runs of the same input differ | Note torch and macOS versions; this is the kind of bug the repeat is there to catch |
| `verdict control-not-caught (exit 1)` | The reverse map also agreed, so the test cannot tell maps apart | Check that `w035_cpu_reverse.tif` is a real reverse run and not a copy |
| A git, uv or Hugging Face error during steps 1/6 to 3/6, then the prompt | No network, or a ref, package or file that moved upstream (the script pins `VILLA_REV`) | Fix the network and rerun; finished downloads are kept |

## How it works

1. Unset `PYTORCH_ENABLE_MPS_FALLBACK`. Refuse an `EXPECT_GPU` other than `mps` or `cpu`, and a machine that is not `Darwin/arm64` when it is `mps`; check for git and uv; create `WORK/{checkpoints,data,logs,results}` and `WORK/predictions`. Take the GPU lock: `mkdir WORK/.gpu-job.lock` with the process id inside; exit 3 if a live process holds it, take it over if not; remove it on exit.
2. **1/6:** clone villa into `WORK/villa` if needed (`--filter=blob:none`), fetch `origin main`, check that `VILLA_REV` is a commit on it (exit 2 if not), check it out detached and record its short commit.
3. **2/6:** create `WORK/venv` with Python 3.14 if missing; with that commit checked out, read the `models` optional dependencies from `vesuvius/pyproject.toml`, drop those starting with `volume-cartographer`, `cucim`, `nnunetv2` or `batchgeneratorsv2`, and install the rest with `vesuvius` editable plus tifffile and imagecodecs.
4. **3/6:** `kit fetch w035 WORK/data/w035_9um.zarr`; download the seed 42 checkpoint if missing; hash it with SHA-256.
5. **4/6:** run inference with `--direction both` into `w035_cpu.tif` (villa also writes `w035_cpu_reverse.tif`), forced onto the CPU: `env CUDA_VISIBLE_DEVICES= python -c` with four lines that make `torch.backends.mps.is_available` return False (wrapped in `functools.lru_cache`, as torch wraps it, since `torch._dynamo` reads its `__wrapped__`) and run villa's `vesuvius.ink_detection.inference.infer` module as `__main__` (`runpy`); require `Using CPU device` in its log.
6. **5/6:** run inference twice, forward, into `w035_gpu_a.tif` and `w035_gpu_b.tif`, letting villa pick the device (with `EXPECT_GPU=cpu`, forced onto the CPU as above); require `Using MPS device` in both logs (`Using CPU device` with `EXPECT_GPU=cpu`).
7. **6/6:** run `kit verify` CPU against GPU a, and GPU a against GPU b, each with `--control w035_cpu_reverse.tif --json`, keeping their exit codes; write and print the summary; exit 1 if either code is not 0.

Constants in the script: the default `VILLA_REV`; the checkpoint path `hybrid_3d2d-seed42/step-075000.pth`; the tolerance and allowed share are `kit verify`'s defaults (2 gray levels, 0.01 % of pixels). The method of a repeat plus a control follows the [GENChase Apple GPU backend](https://github.com/ChaseHendrick/GENChase/blob/main/apps/validate/APPLE-GPU.md), as [mac.md](../mac.md#runbook-verify-mps-against-cpu-on-the-control-segment) describes.

## Cost and time

| Step | Time on an Apple M1 Pro | Source |
| --- | --- | --- |
| CPU, both directions | 1,740 s | [w035 log](../logs/2026-10-07-w035-cpu.md), 2026-10-07 |
| MPS, forward, two runs | 218 s and 212 s (about 4x faster than the CPU) | Same |
| Downloads and environment | Not measured | |
| Memory | Not measured | |

It runs locally on the Mac; it rents nothing. It is not a Modal job: the point is to test the Mac's own GPU. Log the run with `python -m kit run local SLUG -- bash scripts/mac-verify.sh` (the local-compute rule, hard rule 9; see [run-local](run-local.md)).

## For agents

- **Command:** `bash scripts/mac-verify.sh` on an Apple Silicon Mac, wrapped as `python -m kit run local SLUG -- bash scripts/mac-verify.sh`. Machine-readable results: `WORK/results/cpu_vs_gpu.json` and `WORK/results/gpu_repeat.json` (`kit verify --json`).
- **Parse:** in each JSON, `verdict`, `candidate.max_abs_diff`, `candidate.fraction_over_tolerance`, `candidate.pearson`, `control.fraction_over_tolerance` and `control.shape_match`; or the `cpu_vs_gpu:` and `gpu_repeat:` lines of `WORK/results/summary.txt`.
- **Rerun:** Safe but not cheap: it reuses villa, the environment, the data and the checkpoint, and redoes all three inference runs, overwriting the maps, logs, JSON files and summary.
- **Success:** Script exit code 0, which means both JSON files have `verdict` equal to `pass`.
- **Not a pass:** Exit code 1 after the summary (a `fail` or `control-not-caught` verdict); exit code 3 (nothing ran); any result from `EXPECT_GPU=cpu`; a `pass` read as evidence that the map shows ink (w035 is a training segment).
- **Go-ahead:** Nothing to run it on the user's Mac. Posting the summary on villa or anywhere public needs Chase's yes first.
- **Never:** Run it while another GPU job runs on the same Mac; report agreement without the control; call the w035 map a reading.

## Tests

```bash
python -m unittest tests.test_mac_scripts.MacVerifyTest tests.test_repo -v
```

`tests/test_mac_scripts.py` `MacVerifyTest` (skipped without bash or python3) runs `scripts/mac-verify.sh` off a Mac with a throwaway `WORK` holding a fake villa clone and checkpoint, stub `git`, `uv` and `uvx` on `PATH` (and a stub `uname` that answers `Darwin`/`arm64` where a test needs `EXPECT_GPU=mps`), and a stub `WORK/venv/bin/python` whose `kit verify` answers a chosen verdict and whose inference records how it was started and prints the device villa would name:

- `test_failing_verdict_fails_the_script`: with a `pass` verdict the script exits 0; with `fail` it exits non-zero and still prints the full summary line `cpu_vs_gpu: verdict fail (exit 1)`.
- `test_mps_fallback_is_off_for_every_inference`: with `PYTORCH_ENABLE_MPS_FALLBACK=1` in the caller's environment, all three inference runs see it unset.
- `test_shares_the_gpu_lock_with_mac_w045`: a lock held by a live process makes the script exit 3 before any inference; a stale lock is taken over and removed at the end.
- `test_villa_main_at_the_pin_not_a_pull_request`: no `pull/` ref is fetched, the pinned commit is checked out, and `VILLA_REV=origin/main` checks out `origin/main`.
- `test_off_a_mac_every_run_is_forced_onto_the_cpu`: with `EXPECT_GPU=cpu` all three runs go through the CPU wrapper with `CUDA_VISIBLE_DEVICES` empty.
- `test_on_a_mac_the_cpu_arm_is_forced_and_the_gpu_arms_are_villas_choice`: with `EXPECT_GPU=mps` the reference goes through the CPU wrapper and the two GPU runs through villa's module unchanged.
- `test_a_cpu_arm_that_ran_on_mps_fails` and `test_a_gpu_arm_that_fell_back_to_the_cpu_fails`: a log naming the wrong device stops the script with exit code 1 and `villa ran on ..., expected ...`.
- `test_expect_gpu_must_name_a_device`: `EXPECT_GPU=cuda` exits 2.

In `tests/test_repo.py`, `test_shell_scripts_parse` checks that the script exists and parses with `bash -n`; `test_mac_scripts_are_bash_32` checks that it uses no syntax macOS bash 3.2 lacks. Nothing tests a real run: that needs a Mac, villa and the downloads. [`verify`](verify.md) has its own tests.

## History

- 2026-10-28: villa `main` at a pinned commit (`VILLA_REV`, default `860f52cbf`, the merge of PR #1865) replaces `pull/1865/head`, now that #1812 and #1865 have merged. The CPU reference is forced onto the CPU, since villa `main` picks MPS by itself, and every run must log the device it was meant to use; `EXPECT_GPU` takes only `mps` or `cpu`.
- 2026-10-17: the script exits 1 when either `kit verify` check does not pass; before, it exited 0 whenever it finished, so a `fail` verdict was seen only in the summary (`7a0e9a9`).
- 2026-10-17: it unsets `PYTORCH_ENABLE_MPS_FALLBACK`; before, an inherited `PYTORCH_ENABLE_MPS_FALLBACK=1` let an op MPS lacks run quietly on the CPU, which the `Using MPS device` check does not see (`b213518`).
- 2026-10-17: it takes the shared GPU lock `WORK/.gpu-job.lock` and exits 3 while another run holds it; before, it did not check the lock, so it could run beside mac-w045 in the same villa clone and `WORK` (`ff604b9`).
- 2026-10-07: first version, with `kit fetch` for the w035 surface volume, the CPU reference, two PR #1865 runs and two `kit verify` checks (`912135c`).

## Related

- [`verify`](verify.md): the comparison and control rule this script runs.
- [mac-w045](mac-w045.md): the labeled generalization check on the same `WORK` folder.
- [mac.md](../mac.md): the Mac guide, the manual runbook and the upstream MPS PRs.
- [w035 log](../logs/2026-10-07-w035-cpu.md): the recorded M1 Pro run and why w035 is a training segment.
- `device_checks` in [`results.json`](../results.json): the recorded device checks.
- [fetch](fetch.md): the downloader for the surface volume.
