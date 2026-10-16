# mac-verify: check on a Mac that villa's MPS ink inference gives the CPU's map

`scripts/mac-verify.sh` runs `ink_9um` seed 42 on PHerc0139 w035 on the CPU with stock villa and twice on the Mac GPU with villa PR #1865, then checks both pairs with `kit verify` against a reverse-depth control and prints a summary to paste.

| Field | Value |
| --- | --- |
| Id | `mac-verify` |
| Status | Current |
| Kind | script |
| Area | Scoring and controls |
| Run | `bash scripts/mac-verify.sh` |
| Code | `scripts/mac-verify.sh` |
| Tests | `tests/test_repo.py` (only that the script parses with `bash -n` and uses no bash 4 syntax) |
| Needs | An Apple Silicon Mac (macOS, arm64) with git and uv (`brew install uv`); about 3 GB free in `WORK` (script header). The script itself builds the rest: villa (`main` and PR #1865), a Python 3.14 virtual environment with villa's `models` extra minus `volume-cartographer`, `cucim`, `nnunetv2` and `batchgeneratorsv2`, plus tifffile and imagecodecs; the published w035 surface volume and the `ink_9um` seed 42 checkpoint |
| Runs on | Apple Silicon Mac only (or any machine with `EXPECT_GPU=cpu`, to test the script). On an Apple M1 Pro: CPU 1,740 s for both directions, MPS 218 s and 212 s forward ([w035 log](../logs/2026-10-07-w035-cpu.md), 2026-10-07), plus the downloads |
| Network | `github.com` (clones and fetches `ScrollPrize/villa`); `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (the w035 surface volume, through `kit fetch`); `huggingface.co` (the checkpoint `scrollprize/ink_9um`, through `uvx --from huggingface_hub hf download`); the Python package index and uv's Python downloads (the environment). Nothing is uploaded |
| Writes | Under `WORK` (default `~/scrolls-work`): `villa/` (a clone; the script checks out `origin/main` or `pr-1865` detached), `venv/`, `models-reqs.txt`, `checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth`, `data/w035_9um.zarr/`, `predictions/w035_cpu.tif`, `predictions/w035_cpu_reverse.tif`, `predictions/w035_gpu_a.tif`, `predictions/w035_gpu_b.tif`, `logs/cpu.log`, `logs/gpu_a.log`, `logs/gpu_b.log`, `results/cpu_vs_gpu.json`, `results/gpu_repeat.json`, `results/summary.txt`. uv also fills its own cache |
| Go-ahead | Not needed to run it on your own Mac. Posting its summary, for example on villa PR #1865, needs Chase's yes (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-07 |
| Guide | [mac.md, "One command"](../mac.md#one-command) and its [runbook](../mac.md#runbook-verify-mps-against-cpu-on-the-control-segment) |
| Checked | 2026-10-16 against commit `0747c06` |

## What it does

villa's ink inference (`python -m vesuvius.ink_detection.inference.infer`) runs only on CUDA or the CPU on stock `main`. [villa PR #1865](https://github.com/ScrollPrize/villa/pull/1865) lets it use the Apple GPU through PyTorch's MPS (Metal Performance Shaders) backend. Before anyone trusts a map made on MPS, the same model on the same input should give the same map on the CPU. This script answers that in one command on an Apple Silicon Mac.

It runs the released 9 um ink model `ink_9um` (seed 42, step 75,000) on the published 9.362 um surface volume of PHerc0139 segment w035: once on the CPU with stock villa `main`, in both depth directions, and twice on MPS with PR #1865, forward only. It then runs [`verify`](verify.md) twice, CPU against the first MPS run and the first MPS run against the second, each with the CPU's reverse-direction map as the control, and prints a summary of chip, versions, commits, checkpoint hash, times and verdicts.

w035 is a training segment of `ink_9um`, so its map shows the model reproducing its training labels ([w035 log](../logs/2026-10-07-w035-cpu.md)). That does not matter here: a device comparison needs only the same input on both devices. A `pass` says the Mac GPU reproduces the CPU's map; it says nothing about whether either map shows ink, and an ink map is model output, not a reading.

It does not score against labels, does not run v8in, does not reuse finished maps (every run redoes all three inference passes) and does not take the GPU lock that [mac-w045](mac-w045.md) takes.

## When to use it

- You have an Apple Silicon Mac and want to know whether villa PR #1865's MPS inference matches the CPU on your chip and torch version, with a control and a repeat.
- You are preparing evidence for a review of PR #1865 (post it only after Chase says yes).
- After a torch or macOS update, to recheck that MPS still matches.

Do not use it:

- To test whether a model finds ink it was not trained on: use [mac-w045](mac-w045.md), which scores against labels with [`auc`](auc.md).
- To compare two maps you already have: run [`verify`](verify.md) directly.
- On a Linux or CUDA machine for a real result: it refuses without `EXPECT_GPU=cpu`, and with it the "GPU" runs are CPU runs.
- While [mac-w045](mac-w045.md) or [mac-phase0](mac-phase0.md) is running on the same Mac: this script does not check their GPU lock, and two GPU jobs at once can run out of memory.

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

On a Mac it prints a header for each of its six steps (`== 1/6 villa: main and PR #1865` to `== 6/6 kit verify`) and ends with a summary in this form (from the code; capitals are filled in by the run):

```
kit mac-verify summary (paste this)
chip: CHIP | os: OS | torch: TORCH mps available: True
villa main MAIN_SHA (CPU) | PR #1865 PR_SHA (mps) | ckpt seed42 step-075000 sha256 CKPT_SHA
times: cpu both directions T_CPUs | gpu forward T_As, T_Bs
cpu_vs_gpu: verdict VERDICT (exit CODE) | max|diff| MAX | over tol SHARE% | pearson R | control over tol CONTROL%
gpu_repeat: verdict VERDICT (exit CODE) | max|diff| MAX | over tol SHARE% | pearson R | control over tol CONTROL%
```

It worked when both result lines read `verdict pass (exit 0)` and the control share is large (73.12 % on the recorded M1 Pro run). The script's own exit code 0 only means it finished: read the verdicts.

## Checks and controls

- **Reverse-depth control.** Both `kit verify` calls pass `--control WORK/predictions/w035_cpu_reverse.tif`, the CPU map with the surface volume's layers in reverse order. Agreement counts as `pass` only when that control is caught by the same test (at most 0.01 % of pixels more than 2 grey levels apart; see [`verify`](verify.md)). A control that agrees gives `control-not-caught`.
- **Repeat.** `gpu_repeat` compares two MPS runs, which catches nondeterminism, such as a torch bug that reads freed memory.
- **No silent CPU fallback.** After the two GPU runs it greps each log for `Using MPS device` and stops with exit code 1 if either lacks it. Unlike [mac-w045](mac-w045.md), it does not unset `PYTORCH_ENABLE_MPS_FALLBACK`, so unset it yourself before running.
- **Recorded pass.** Apple M1 Pro, macOS 27.0, torch 2.14.1, villa `main` `e0bbb8b40` and PR #1865 `6723ad158`: CPU against MPS `pass` with max |diff| 1 and Pearson 0.99999999; MPS repeat bit-identical; control 73.12 % of pixels over tolerance ([w035 log](../logs/2026-10-07-w035-cpu.md); `device_checks` in [`results.json`](../results.json)).
- **What a caught control looks like.** On w035 the CPU forward map against its reverse: max |diff| 167, mean 21.6692, 73.117458 % of pixels over 2, Pearson 0.511578 ([w035 log](../logs/2026-10-07-w035-cpu.md)).

Claim label: Model output, for the agreement of the CPU and MPS runs of `ink_9um` on w035; a `pass` is about the device, not about ink.

## Commands and options

### `bash scripts/mac-verify.sh`

The script takes no arguments and has no `--help`: anything after the script name is ignored and the run starts. It is configured only by the environment variables below.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `WORK` | `$HOME/scrolls-work` | Folder for villa, the environment, data, checkpoint, maps, logs and results. Shared with [mac-w045](mac-w045.md) |
| `EXPECT_GPU` | `mps` | `mps` requires `Darwin/arm64` and checks the GPU logs for `Using MPS device`. Any other value (use `cpu`) skips both checks so the script can be tested off a Mac; the "GPU" runs are then whatever device villa PR #1865 picks there |

## Python API

Not applicable: a shell script with no importable functions; see Commands and options.

## Inputs

| Input | Where it comes from | Notes |
| --- | --- | --- |
| w035 surface volume | `kit fetch w035` from the open-data bucket (alias `W035_9UM` in `kit/fetch.py`), to `WORK/data/w035_9um.zarr` | 9.362 um, 2,223 objects, 1.02 GB, shape 28 x 5,820 x 5,240 ([w035 log](../logs/2026-10-07-w035-cpu.md)). A rerun skips files already there at the listed size |
| Checkpoint | `scrollprize/ink_9um`, file `hybrid_3d2d-seed42/step-075000.pth`, to `WORK/checkpoints/ink_9um/` | Downloaded only when missing; its SHA-256 goes into the summary |
| villa | `https://github.com/ScrollPrize/villa.git`, `origin/main` and `pull/1865/head` | Both refs are fetched on every run, so the commits are the current ones; the summary records them |

The inference settings are fixed in the script: `--overlap 0.5 --blend-mode hann --batch-size 1 --no-compile`, and `--direction both` for the CPU run only.

## Outputs

The run prints step headers, `torch VERSION mps available: BOOL`, `CPU: Ns for both directions`, `GPU runs: Ns and Ns (forward only)`, then the summary (see Quick start), which is also saved to `WORK/results/summary.txt`.

| File | What it holds |
| --- | --- |
| `WORK/predictions/w035_cpu.tif`, `w035_cpu_reverse.tif` | CPU maps on villa `main`, forward and reverse (villa names the reverse map) |
| `WORK/predictions/w035_gpu_a.tif`, `w035_gpu_b.tif` | The two forward maps on PR #1865 |
| `WORK/logs/cpu.log`, `gpu_a.log`, `gpu_b.log` | villa's output for each inference run, overwritten each run |
| `WORK/results/cpu_vs_gpu.json`, `gpu_repeat.json` | `kit verify --json` output; fields in [`verify`](verify.md#outputs) |
| `WORK/results/summary.txt` | The summary to paste |

The summary's result lines read, from each JSON: `verdict`, the `kit verify` exit code, `candidate.max_abs_diff`, `candidate.fraction_over_tolerance` (as a percentage, six decimals), `candidate.pearson` and `control.fraction_over_tolerance` (two decimals).

| Exit code | Meaning |
| --- | --- |
| `0` | The script finished and printed the summary. It does not mean the maps agree: read the two verdicts |
| `1` | An inference run failed, a GPU run did not log `Using MPS device`, or a later command failed under `set -e` (such as the summary step when a `kit verify` JSON is empty) |
| `2` | Not an Apple Silicon Mac (without `EXPECT_GPU=cpu`), or git or uv is missing; also `kit fetch`'s own code 2 for a failed download |
| Other | The code of whichever command failed under `set -e`, such as git |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `This needs an Apple Silicon Mac (or EXPECT_GPU=cpu to test the script elsewhere).`, exit code 2 | `uname -s`/`uname -m` is not `Darwin/arm64` and `EXPECT_GPU` is `mps` | Run it on an Apple Silicon Mac; set `EXPECT_GPU=cpu` only to test the script |
| `git is missing (xcode-select --install)`, exit code 2 | No git on `PATH` | Install the Xcode command line tools |
| `uv is missing: brew install uv`, exit code 2 | No uv on `PATH` | `brew install uv` |
| `inference failed, see WORK/logs/LOG.log` then the log's last 20 lines, exit code 1 | villa's inference exited non-zero (a missing package, out of memory, an MPS op error) | Read the log; paste its last 20 lines when asking for help |
| `gpu_a did not run on MPS; see WORK/logs/gpu_a.log` (or `gpu_b`), exit code 1 | The PR #1865 run did not print `Using MPS device`: it ran on the CPU, or PR #1865 changed its log line | Check `torch ... mps available: True` in the output and the PR's current code |
| A Python `json.decoder.JSONDecodeError` traceback after `== 6/6 kit verify`, exit code 1 | A `kit verify` call exited 2 (an unreadable map), so its JSON file is empty and the summary step cannot read it | Run the `kit verify` command by hand with `WORK/venv/bin/python -m kit verify ...` to see its message |
| `cpu_vs_gpu: verdict fail (exit 1)` in the summary | More than 0.01 % of pixels differ by more than 2 grey levels between CPU and MPS | Use the CPU result; report the difference on PR #1865 (after Chase says yes) |
| `gpu_repeat: verdict fail (exit 1)` | Two MPS runs of the same input differ | Note torch and macOS versions; this is the kind of bug the repeat is there to catch |
| `verdict control-not-caught (exit 1)` | The reverse map also agreed, so the test cannot tell maps apart | Check that `w035_cpu_reverse.tif` is a real reverse run and not a copy |
| A git, uv or Hugging Face error during steps 1/6 to 3/6, then the prompt | No network, or a ref, package or file that moved upstream (the script fixes `PR=1865`) | Fix the network and rerun; finished downloads are kept |

## How it works

1. Refuse a machine that is not `Darwin/arm64` unless `EXPECT_GPU` is not `mps`; check for git and uv; create `WORK/{checkpoints,data,logs,results}` and `WORK/predictions`.
2. **1/6:** clone villa into `WORK/villa` if needed (`--filter=blob:none`), fetch `origin main` and `pull/1865/head` as `pr-1865`, record both short commits.
3. **2/6:** create `WORK/venv` with Python 3.14 if missing; with villa `main` checked out, read the `models` optional dependencies from `vesuvius/pyproject.toml`, drop those starting with `volume-cartographer`, `cucim`, `nnunetv2` or `batchgeneratorsv2`, and install the rest with `vesuvius` editable plus tifffile and imagecodecs.
4. **3/6:** `kit fetch w035 WORK/data/w035_9um.zarr`; download the seed 42 checkpoint if missing; hash it with SHA-256.
5. **4/6:** on villa `main`, run inference with `--direction both` into `w035_cpu.tif` (villa also writes `w035_cpu_reverse.tif`).
6. **5/6:** on `pr-1865`, run inference twice, forward, into `w035_gpu_a.tif` and `w035_gpu_b.tif`; switch villa back to `main`; with `EXPECT_GPU=mps`, require `Using MPS device` in both logs.
7. **6/6:** run `kit verify` CPU against GPU a, and GPU a against GPU b, each with `--control w035_cpu_reverse.tif --json`, keeping their exit codes; write and print the summary.

Constants in the script: `PR=1865`; the checkpoint path `hybrid_3d2d-seed42/step-075000.pth`; the tolerance and allowed share are `kit verify`'s defaults (2 grey levels, 0.01 % of pixels). The method of a repeat plus a control follows the [GENChase Apple GPU backend](https://github.com/ChaseHendrick/GENChase/blob/main/apps/validate/APPLE-GPU.md), as [mac.md](../mac.md#runbook-verify-mps-against-cpu-on-the-control-segment) describes.

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
- **Success:** Script exit code 0 and both JSON files with `verdict` equal to `pass`.
- **Not a pass:** Exit code 0 with a `fail` or `control-not-caught` verdict; any result from `EXPECT_GPU=cpu`; a `pass` read as evidence that the map shows ink (w035 is a training segment).
- **Go-ahead:** Nothing to run it on the user's Mac. Posting the summary on villa PR #1865 or anywhere public needs Chase's yes first.
- **Never:** Run it while another GPU job runs on the same Mac; report agreement without the control; call the w035 map a reading.

## Tests

```bash
python -m unittest tests.test_repo -v
```

`test_shell_scripts_parse` checks that the script exists and parses with `bash -n`; `test_mac_scripts_are_bash_32` checks that it uses no syntax macOS bash 3.2 lacks. Nothing tests a run: that needs a Mac, villa and the downloads. [`verify`](verify.md) has its own tests.

## History

- 2026-10-07: first version, with `kit fetch` for the w035 surface volume, the CPU reference, two PR #1865 runs and two `kit verify` checks (`912135c`).

## Related

- [`verify`](verify.md): the comparison and control rule this script runs.
- [mac-w045](mac-w045.md): the labelled generalization check on the same `WORK` folder.
- [mac.md](../mac.md): the Mac guide, the manual runbook and the upstream MPS PRs.
- [w035 log](../logs/2026-10-07-w035-cpu.md): the recorded M1 Pro run and why w035 is a training segment.
- `device_checks` in [`results.json`](../results.json): the recorded device checks.
- [fetch](fetch.md): the downloader for the surface volume.
