# mac-w045: run ink_9um and v8in on a labeled segment on the Mac GPU and score them with controls

`scripts/mac-w045.sh` runs `ink_9um` (two seeds) and v8in or v8in-1447 on the Mac GPU over a labeled segment (PHerc0139 w045 or a PHerc0841 segment), checks v8in on MPS against the CPU, scores every map with reverse-depth controls, and writes a summary and a provenance record.

| Field | Value |
| --- | --- |
| Id | `mac-w045` |
| Status | Current |
| Kind | script |
| Area | Ink maps and models |
| Run | `bash scripts/mac-w045.sh` |
| Code | `scripts/mac-w045.sh` |
| Tests | `tests/test_repo.py` (only that the script parses with `bash -n` and uses no bash 4 syntax) |
| Needs | An Apple Silicon Mac (macOS, arm64) with git and uv (`brew install uv`); about 6 GB free in `WORK` (script header). The script builds the rest: villa (`main` and PR #1865), a Python 3.14 environment with villa's `models` extra (minus `volume-cartographer`, `cucim`, `nnunetv2`, `batchgeneratorsv2`) plus tifffile, imagecodecs, scipy, opencv-python-headless, safetensors and huggingface_hub; the segment's surface volume and labels; the `ink_9um` seed 42 and 43 checkpoints; v8in or v8in-1447 at a pinned revision. It also runs `scripts/v8in_run.py` ([v8in-run](v8in-run.md)) and the kit commands `fetch`, `layers`, `verify`, `auc`, `rowscore` and `provenance` |
| Runs on | Apple Silicon Mac only (any machine with `EXPECT_GPU=cpu`, to test the script). `QUICK=1` is meant to finish in under an hour once w045's device check exists (script header; the recorded steps are under Cost and time); a full run spends up to `V8IN_HOURS` (default 4) on v8in plus about 11 min per `ink_9um` seed ([mac.md](../mac.md#watching-a-run), [community scan log](../logs/2026-10-07-community-scan.md), 2026-10-07) |
| Network | `github.com` (villa); `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (surface volume and labels, through `kit fetch`); `huggingface.co` (`scrollprize/ink_9um`, and `YoussefMoNader/ink-8um-v8in` or `YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062`); the Python package index and uv's Python downloads. Nothing is uploaded |
| Writes | Under `WORK` (default `~/scrolls-work`): shared `villa/`, `venv/`, `models-reqs.txt`, `checkpoints/`, `data/`, `logs/`, and the lock folder `.gpu-job.lock/` while it runs; per run, `WORK/NAME/maps/`, `WORK/NAME/layers/`, `WORK/NAME/crop_layers/` and `WORK/NAME/results/` (see Outputs). `NAME` is the segment, with `-smoke` added under `SMOKE=1` |
| Go-ahead | Not needed to run it on your own Mac. Posting its summary or scores needs Chase's yes (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-07 |
| Guide | [mac.md, "Generalization check on w045: one command"](../mac.md#generalization-check-on-w045-one-command) and ["Watching a run"](../mac.md#watching-a-run) |
| Checked | 2026-10-16 against commit `0747c06` |

## What it does

A device check (such as [mac-verify](mac-verify.md)) shows that the Mac GPU gives the CPU's map, not that a model finds ink. This script asks the second question on segments with published ink labels: does each model's map rank labeled ink pixels above labeled background, and does the map made with the surface volume's layers in reverse order (the control) fail to do so?

It runs two released models on the Mac GPU (MPS, through PyTorch's Metal backend). `ink_9um` is the team's 9 um ink model (seeds 42 and 43, step 75,000), run through villa's `vesuvius.ink_detection` inference with [villa PR #1865](https://github.com/ScrollPrize/villa/pull/1865), in both depth directions. v8in is Youssef Nader's ResNet3D-50 ink model (`YoussefMoNader/ink-8um-v8in`); `MODEL=v8in-1447` picks its PHerc1447 fine-tune instead. v8in runs through `scripts/v8in_run.py` on layer TIFFs that `kit layers` exports. Before the long v8in pass the script runs v8in on a 640 px crop on the CPU and on MPS and stops unless [`verify`](verify.md) passes with the reverse map as the control. It then scores every map with [`auc`](auc.md) (forward against reverse) and [`rowscore`](rowscore.md), prints a summary to paste, and writes a [provenance](provenance.md) record and digest.

The segments differ in what they can show. PHerc0139 w045 is not in v8in's training set (its patch pack lists w033, w035, w041 and w044), but it is not held out from `ink_9um`, which trained on its 2.4 um render, so for `ink_9um` it is a cross-scan check on a training surface ([log](../logs/2026-10-08-w045-not-held-out.md)). PHerc0841 (`SEGMENT=0841-w00`, `0841-ag896` or `0841-ag405`) is in the training data of none of `ink_9um`, v8in, d9v2 and Reader v2, but possibly in Hecate's, so it is the fairer test. `QUICK=1` scores every model on the same 640 px crop of densest labeled ink, less a 64 px edge, which is what [mac-phase0](mac-phase0.md) queues and [gate](gate.md) ranks.

It does not decide anything: it prints AUCs and row scores. The maps and scores are model output, not a reading, and w045's maps are not a First Letters candidate (it is a training scroll with published labels). It does not run on Modal, and it does not commit or upload results.

## When to use it

- To score `ink_9um` and v8in (or v8in-1447) against labels on w045 or a PHerc0841 segment, on the Mac GPU, with controls.
- `QUICK=1`, to compare models on one 640 px crop, the cheapest real run.
- `SMOKE=1 EXPECT_GPU=cpu`, to test the script end to end on any machine on a 256 px window.

Do not use it:

- Only to check that MPS matches the CPU: use [mac-verify](mac-verify.md).
- For the whole Phase 0 queue on PHerc0841: use [mac-phase0](mac-phase0.md), which calls this script per job.
- To score a map you already have: run [`auc`](auc.md) directly.
- For long GPU work off a Mac, or on a laptop CPU: GPU jobs go to Modal with a written spec (the Modal rule, hard rule 11).
- On target scrolls: it has no such segment, and target work belongs in Scrolls-private (the no-findings rule, hard rule 1).

## Quick start

```bash
cd Scrolls
QUICK=1 bash scripts/mac-w045.sh                              # w045, crop only
SEGMENT=0841-w00 QUICK=1 bash scripts/mac-w045.sh             # the same test on PHerc0841 w00
SMOKE=1 EXPECT_GPU=cpu WORK=SCRATCH bash scripts/mac-w045.sh  # test the script anywhere on a 256 px window
```

- `SCRATCH`: an empty folder for the smoke test, so its downloads and environment stay apart from a real `WORK`.

It could not be run end to end while writing this page: it needs an Apple Silicon Mac, and even the smoke test downloads a surface volume of 0.6 to 1.7 GB, three checkpoints and villa's environment. On this page's Linux container (2026-10-16) the first checks behaved as the code says:

```
$ bash scripts/mac-w045.sh
This needs an Apple Silicon Mac (or EXPECT_GPU=cpu to test the script elsewhere).
exit 2
$ MODEL=hecate bash scripts/mac-w045.sh
MODEL must be v8in or v8in-1447
exit 2
```

A real run prints `== 1/7 ...` to `== 7/7 scores`, then the summary. On the user's Apple M1 Pro, `QUICK=1` on w045 (2026-10-07, [community scan log](../logs/2026-10-07-community-scan.md)) gave these AUCs on the crop, rows 3840 to 4480, columns 2560 to 3200:

| Map | AUC as stored | AUC reversed | Ink / background px |
| --- | --- | --- | --- |
| `ink_9um` seed 42 (MPS) | 0.9136 | 0.3704 | 78,047 / 157,531 |
| `ink_9um` seed 43 (MPS) | 0.9098 | 0.4347 | 78,047 / 157,531 |
| v8in, stride 21 (MPS) | 0.7382 | 0.3269 | 73,200 / 155,629 |

It worked when the exit code is 0, the summary's `v8in cpu vs mps (crop):` line reads `pass`, and each AUC line has a forward score above 0.5 with the reversed score well below it.

## Checks and controls

- **Reverse-depth control for every score.** Every map has a reverse-direction twin, and `kit auc --control` and `kit rowscore --reverse` score both. A model that reads ink should score well above 0.5 forward and near or below 0.5 reversed; a forward score close to the reversed one means it reads brightness, not ink. The reversed maps on w045 sat well below 0.5 (0.33 to 0.43 above), so compare each score's distance from 0.5, not only the difference ([community scan log](../logs/2026-10-07-community-scan.md)). Gate A asks for forward minus reverse of at least 0.10 on every crop ([gate](gate.md)).
- **Device check for v8in (step 5).** v8in on a crop at stride 64, CPU against MPS, with the MPS reverse map as the control, through `kit verify`. On MPS the script stops before the long pass unless the verdict is `pass`. Recorded on the M1 Pro: `pass`, max |diff| 1, Pearson 0.99999998 (`device_checks` in [`results.json`](../results.json)). Other segments and v8in-1447 reuse w045's pass (same code); `DEVICE_CHECK=1` reruns it.
- **fp16 check.** With `V8IN_FP16=1` the first run compares fp16 with fp32 on the GPU on a crop, the fp16 reverse map as the control, and stops if they differ; fp32 must first have passed against the CPU on w045. If fp16 is slower per tile than fp32, the remaining passes run fp32.
- **No silent CPU fallback.** The script unsets `PYTORCH_ENABLE_MPS_FALLBACK`, and on MPS it requires `Using MPS device` in each `ink_9um` log.
- **Cross-device consistency.** On w045 the MPS `ink_9um` crop scores equaled the CPU reference to four decimals on both seeds ([community scan log](../logs/2026-10-07-community-scan.md)).
- **Training overlap.** A high `ink_9um` score on w045 is on a surface it trained on (at 2.4 um); it cannot show that `ink_9um` beats v8in on unseen papyrus ([log](../logs/2026-10-08-w045-not-held-out.md)). Use PHerc0841 for that.

Claim label: Model output, for each AUC and row score; any comparison between models drawn from them is an Interpretation.

## Commands and options

### `bash scripts/mac-w045.sh`

The script takes no arguments and has no `--help`: anything after the script name is ignored and the run starts. It is configured only by the environment variables below.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `WORK` | `$HOME/scrolls-work` | Folder for villa, the environment, data, checkpoints, logs and outputs. Shared with [mac-verify](mac-verify.md) and [mac-phase0](mac-phase0.md) |
| `SEGMENT` | `w045` | `w045`, `0841-w00`, `0841-ag896` or `0841-ag405`; picks the surface volume, labels, crop and surface shape (see Inputs) |
| `MODEL` | `v8in` | `v8in` (`YoussefMoNader/ink-8um-v8in` at `d89166b41a3f5fad7749b3d7c0fdd1bd3695d844`) or `v8in-1447` (`YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062` at `2bf9f421862cda0ed41dcae6e8274c12e295d03a`) |
| `QUICK` | `0` | `1`: `ink_9um` reads only the 640 px crop, v8in runs on the crop at full density, and every AUC is on the crop less a 64 px edge (`--inner 64`); no row scores (the crop is too small) |
| `SMOKE` | `0` | `1`: everything on a 256 px window inside the crop, v8in at stride 64, device check always run, outputs under `WORK/SEGMENT-smoke`. A test of the script, not a result |
| `EXPECT_GPU` | `mps` | `mps` requires `Darwin/arm64` and checks MPS use. Any other value (use `cpu`) runs v8in on the CPU, skips the MPS log checks, and lets a failed device check continue |
| `FRESH` | `0` | `1`: redo every pass; otherwise finished passes are reused (see How it works) |
| `DEVICE_CHECK` | `0` | `1`: run the v8in CPU against MPS check on this segment instead of reusing w045's pass |
| `V8IN_FP16` | `0` | `1`: v8in in half precision on MPS (`--fp16`), checked once against fp32 and dropped when slower. Ignored on the CPU |
| `V8IN_BATCH` | from memory | v8in tiles per batch. Unset: 4 with at most 16 GB of RAM, 8 with at most 32 GB, 16 above |
| `V8IN_STRIDE` | none | v8in stride in pixels for the main pass. Unset: 21 under `QUICK=1`, 64 under `SMOKE=1`, otherwise the finest of 21, 32, 42, 64 whose estimate fits `V8IN_HOURS` |
| `V8IN_HOURS` | `4` | Time budget in hours for both directions of the full v8in pass, used only to pick the stride |
| `V8IN_REGION` | `labels` | `labels`: v8in reads the box around the supervision mask plus 256 px. Any other value (use `full`): the whole segment (about 1.5x the tiles, per the script header). Ignored under `QUICK` and `SMOKE` |
| `QUICK_REV_STRIDE` | `42` | Stride of the reverse control pass under `QUICK=1` (a quarter of the tiles of stride 21) |
| `STRIDE` | not read | Internal: set from `V8IN_STRIDE` before use, so a value in the environment has no effect |
| `REV_STRIDE` | not read | Internal: set from `QUICK_REV_STRIDE` under `QUICK=1`. In a full run an exported `REV_STRIDE` changes only the summary's `(reverse N)` text, not the run |
| `PYTORCH_ENABLE_MPS_FALLBACK` | unset by the script | Unset at the start so an operation MPS lacks fails instead of running on the CPU |

## Python API

Not applicable: a shell script with no importable functions; see Commands and options.

## Inputs

| `SEGMENT` | Segment in the open-data bucket | Labels | Crop (y0 y1 x0 x1) | Surface shape | Voxel (um) |
| --- | --- | --- | --- | --- | --- |
| `w045` | `PHerc0139/segments/20260126000000-w045_2026012619` (surface volume through the `kit fetch` alias `w045`) | `ink-labels/2.399um-volume-20260102150214/20260918` | 3840 4480 2560 3200 | 5980 x 8240 | 9.362 |
| `0841-w00` | `PHerc0841/segments/20260220213127-w00` | `ink-labels/2.403um-volume-20260319124803/20260918` | 2624 3264 2688 3328 | 4220 x 4760 | 9.366 |
| `0841-ag896` | `PHerc0841/segments/20260220214732-auto_grown_20260220144552896` | same | 2496 3136 1600 2240 | 4640 x 4720 | 9.366 |
| `0841-ag405` | `PHerc0841/segments/20260221022814-auto_grown_20260220174252405` | same | 1024 1664 2496 3136 | 3760 x 4900 | 9.366 |

PHerc0841 surface volumes are `SEGMENT/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr`. Labels are `inklabels.zarr` and `supervision.zarr`, scored at `--level 2`. Crops are 640 px windows fully on the surface with the densest labeled ink, in rows and columns of the surface grid; they match `segments` in [`results.json`](../results.json). Checkpoints: `scrollprize/ink_9um` files `hybrid_3d2d-seedN/step-075000.pth`; the v8in snapshot without `training/*`. Downloads are skipped when already present (`kit fetch` skips files at the listed size).

## Outputs

Step headers `== 1/7 ...` to `== 7/7 scores`, progress lines (`torch VERSION mps available: BOOL`, `memory N GB: v8in batch B`, `v8in region: rows ...`, `seed N: Ts for both directions`, `crop: cpu Ts, mps Ts`, `stride N`, `v8in: Ts and Ts`), then the summary, also saved, and `provenance: PATH: digest HEX`. The summary's lines, from the code:

```
kit mac-w045 summary for SEGMENT (paste this)
chip: CHIP | os: OS | torch: TORCH | smoke: 0 | quick: 1
villa PR #1865 PR_SHA on mps | MODEL REV on mps, stride S (reverse R), batch B, fp16 F, region REGION
sha256 seed42 HASH | seed43 HASH | v8in HASH
times (s): ink_9um s42 T, s43 T (both directions) | v8in T + T
v8in cpu vs mps (crop): VERDICT | max|diff| D | pearson P
AUC ink9um_s42: as stored A | reversed A | ink px N, background px N
AUC ink9um_s43: ...
AUC MTAG: ...
row score ink9um: as stored S | reversed S
row score MTAG: ...
```

`QUICK=1` adds two `quick:` lines saying every AUC is on the crop less a 64 px edge and that there are no row scores. A reused pass shows `earlier` or `w045` in place of its time.

Files under `WORK/NAME/`, where `INK` is `ink9um` (or `ink9um_quick` under `QUICK=1`), `MTAG` is `v8in` or `v8in1447`, `DEV` is `crop` for v8in and `v8in1447_crop` for v8in-1447, and `PTAG` is empty for v8in and `_v8in1447` for v8in-1447:

| File | What it holds |
| --- | --- |
| `maps/INK_s42.tif`, `INK_s42_reverse.tif`, `INK_s43.tif`, `INK_s43_reverse.tif` | `ink_9um` maps from villa, forward and reverse |
| `maps/MTAG.tif`, `MTAG_reverse.tif` (full run) or `MTAG_quick.tif`, `MTAG_quick_reverse.tif` (`QUICK=1`), each with its `.npy` | v8in maps: `scripts/v8in_run.py` writes float `.npy`, the script writes uint8 TIFF (`round(clip(p, 0, 1) * 255)`, zlib) |
| `maps/DEV_cpu`, `DEV_gpu`, `DEV_gpu_reverse` (`.npy`, `.tif`) | The device check's crop maps; with fp16, `DEV_gpu_fp16` and `DEV_gpu_fp16_reverse` |
| `layers/`, `crop_layers/` | Layer TIFFs from `kit layers` for v8in: the region (not under `QUICK=1`) and the crop; deleted and rewritten every run |
| `results/v8in_device.json` (or `v8in1447_device.json`; `_fp16` added with fp16) | `kit verify --json` of the device check, or a copy of w045's |
| `results/auc_ink9um_s42.json`, `auc_ink9um_s43.json`, `auc_MTAG.json` | `kit auc --json`: `forward.auc`, `control.auc`, `forward.ink_px`, `forward.background_px`, `forward.inner`, `crop` ([auc](auc.md#outputs)) |
| `results/rows_ink9um.json`, `rows_MTAG.json` | `kit rowscore --json`: `forward.score`, `reverse.score` ([rowscore](rowscore.md)) |
| `results/summaryPTAG.txt` | The summary |
| `results/provenancePTAG.json`, `provenancePTAG.digest` | `kit provenance write` record (code, models, inputs, outputs, start time) and its `PATH: digest HEX` line |

Logs: `WORK/logs/NAME_INK_s42.log`, `NAME_INK_s43.log`, and `NAME_PASS.log` for each v8in pass, whose last line reads `device=D fp16=F reverse=R stride=S tiles=N done in Ts`.

| Exit code | Meaning |
| --- | --- |
| `0` | Finished and printed the summary. It does not judge the scores: read them |
| `1` | A model run failed, an `ink_9um` seed did not log `Using MPS device`, the device or fp16 check failed, or another command failed under `set -e` |
| `2` | Bad `MODEL` or `SEGMENT`; not an Apple Silicon Mac (without `EXPECT_GPU=cpu`); git or uv missing; `V8IN_FP16=1` before fp32 has passed on w045; or a kit command (`fetch`, `layers`, `auc`, `rowscore`) that exited 2 for bad input |
| `3` | Another run holds the GPU lock `WORK/.gpu-job.lock` |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `MODEL must be v8in or v8in-1447`, exit code 2 | `MODEL` has another value | Use one of the two |
| `SEGMENT must be w045, 0841-w00, 0841-ag896 or 0841-ag405`, exit code 2 | `SEGMENT` has another value | Use one of the four |
| `This needs an Apple Silicon Mac (or EXPECT_GPU=cpu to test the script elsewhere).`, exit code 2 | Not `Darwin/arm64` and `EXPECT_GPU` is `mps` | Run on the Mac; `EXPECT_GPU=cpu` only to test the script |
| `git is missing (xcode-select --install)`, exit code 2 | No git | Install the Xcode command line tools |
| `uv is missing: brew install uv`, exit code 2 | No uv | `brew install uv` |
| `Another run is using the GPU (pid PID: COMMAND).` then `Wait for it, or stop it: kill PID`, exit code 3 | A live process holds `WORK/.gpu-job.lock` (two v8in runs at once do not fit in 16 GB and swap: 56 s per tile instead of 1.3, seen 2026-10-07) | Wait, or stop that run |
| `Taking over a stale lock left by pid PID.` | The lock's process is gone | Nothing; the run continues |
| `ink_9um seed SEED: PATH has sha256 GOT, expected WANT; move it aside and rerun`, exit code 1 | The `ink_9um` checkpoint at `WORK/checkpoints/ink_9um/hybrid_3d2d-seedSEED/step-075000.pth` is not the file of the pinned revision (a partial download, or another file at that path); the script refuses it before villa unpickles it | Move the file aside and rerun; the script downloads it again at the pinned revision |
| `ink_9um seed SEED failed, see LOG` then the log's last 20 lines, exit code 1 | villa's inference failed | Read the log |
| `seed SEED did not run on MPS; see LOG`, exit code 1 | The PR #1865 run did not log `Using MPS device` | Check `mps available: True` in the output and PR #1865's current code |
| `v8in NAME failed, see WORK/logs/SEGMENT_NAME.log` then the log's last 20 lines, exit code 1 (SEGMENT ends in `-smoke` with `SMOKE=1`) | `scripts/v8in_run.py` failed (out of memory, an MPS op, missing layers) | Read the log; lower `V8IN_BATCH`; see [v8in-run](v8in-run.md#failure-modes) |
| `v8in on MPS does not match the CPU; stopping before the full run`, exit code 1 (with ` (fp16 on: try again without V8IN_FP16)` before the semicolon when `V8IN_FP16` is set) | The device check verdict was not `pass` on MPS | Read `results/v8in_device.json`; do not trust MPS maps; rerun without fp16 |
| `Run once without V8IN_FP16 first: fp16 is checked against fp32, which must first match the CPU.`, exit code 2 | `V8IN_FP16=1` but `WORK/w045/results/v8in_device.json` has no `pass` | Run w045 once in fp32 first |
| `v8in fp16 does not match fp32 on DEVICE; run without V8IN_FP16`, exit code 1 | The fp16 check failed | Run without `V8IN_FP16` |
| `fp16 is slower than fp32 on this Mac: the remaining passes run fp32 (maps match either way)` | fp16 took longer per tile (on the M1 Pro about 5x slower, [mac.md](../mac.md#watching-a-run)) | Nothing; leave `V8IN_FP16` unset on an M1 Pro |
| `seed SEED: finished in an earlier run, reused (FRESH=1 to redo)` or `v8in NAME: finished in an earlier run, reused (FRESH=1 to redo)` | A finished pass with matching settings exists | Nothing; `FRESH=1` redoes it |
| A Python traceback after `stride` estimate lines or with no `stride N` line, exit code 1 | The stride estimate could not read `tiles=N done in Ns` from the crop's GPU log (for example a deleted `WORK/logs/w045_crop_gpu.log`) | Set `V8IN_STRIDE`, or rerun with `DEVICE_CHECK=1` |
| An AUC line with the forward score near the reversed one | The model reads brightness, not ink, on this segment | Report it as such; it is a result, not a script error |

## How it works

1. Unset `PYTORCH_ENABLE_MPS_FALLBACK`; read the settings; pick the model repository and revision (`MODEL`) and the segment paths, crop and shape (`SEGMENT`); refuse a machine that is not `Darwin/arm64` unless `EXPECT_GPU` is not `mps`; check git and uv.
2. Take the GPU lock: `mkdir WORK/.gpu-job.lock` with the process id inside; exit 3 if a live process holds it, take it over if not; remove it on exit. Start `caffeinate -i -w PID` when available.
3. **1/7:** clone or fetch villa (`main` and `pull/1865/head`), build `WORK/venv` (Python 3.14) and install villa's models stack and the extra packages; pick the v8in batch from memory.
4. **2/7:** `kit fetch` the surface volume and both label stores (`--workers 8`); download the `ink_9um` checkpoints if missing and the v8in snapshot; hash the three model files.
5. Choose the input: under `SMOKE=1` a 256 px window inside the crop (rows `y0+160` to `y0+416`, columns `x0+140` to `x0+396`), under `QUICK=1` the 640 px crop, both copied into a small zarr; otherwise the whole volume. In a full run with `V8IN_REGION=labels`, v8in's region is the supervision mask's bounding box at level 2, scaled to the surface grid, plus 256 px.
6. **3/7:** on PR #1865, run `ink_9um` seeds 42 and 43 with `--overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both`; require `Using MPS device` on MPS. A seed is reused when both maps and its log exist and (on MPS) the log shows MPS.
7. **4/7:** `kit layers` exports the region (or the smoke input) to `layers/` and the crop to `crop_layers/`.
8. **5/7:** the device check. Reuse w045's passing `v8in_device.json` for another segment or model unless `DEVICE_CHECK`, `FRESH` or `SMOKE` is set; with fp16, check fp16 against fp32 on the GPU; otherwise run v8in on the crop at stride 64 on the CPU, on the GPU and on the GPU reversed, then `kit verify CPU GPU --control GPU_REVERSE --json`, and stop on MPS unless it passes.
9. **6/7:** under `QUICK=1`, v8in on the crop at stride 21 forward and `QUICK_REV_STRIDE` (42) reversed. Otherwise pick the stride: from the crop run's seconds per tile and the tile count of each stride over the coverage mask of the central 24 of 28 layers (`ink8um.inference.coverage_mask` and `tile_positions`, 64 px tiles), the finest of 21, 32, 42, 64 whose time fits half of `V8IN_HOURS` per direction; then run forward and reversed. A v8in pass is reused when its TIFF exists and its log's last line names the same device, fp16, direction and stride.
10. **7/7:** `kit auc MAP --control REVERSE --labels LAB/inklabels.zarr --mask LAB/supervision.zarr --level 2 [--crop ... --surface-shape ...] [--inner 64] --json` for each seed and for v8in; `kit rowscore ... --voxel-um VOXEL --json` for `ink_9um` (both seeds) and v8in; write the summary; `kit provenance write` over the three models, the inputs and every output that exists.

Constants in the script: `PR=1865`; the v8in revisions under `MODEL`; the crops, shapes and voxel sizes under Inputs; the region margin `pad = 256`; strides tried `(21, 32, 42, 64)`; device check stride 64; batch thresholds 16 and 32 GB.

## Cost and time

| Step (Apple M1 Pro, fp32, batch 4) | Time | Source |
| --- | --- | --- |
| `ink_9um`, both directions, all of w045 | 649 s (seed 42) and 679 s (seed 43) | [community scan log](../logs/2026-10-07-community-scan.md), 2026-10-07; measured when `QUICK=1` still ran `ink_9um` on the whole segment (it now reads only the crop) |
| v8in device check, CPU side, 100 tiles | 2,497 s (25 s per tile) | Same |
| v8in device check, MPS side, 100 tiles each way | 396 s for the first (with warm-up), then 132 s | [mac.md](../mac.md#watching-a-run), 2026-10-07 |
| v8in on the 640 px crop, stride 21, 784 tiles | 862 s and 926 s (1.1 to 1.2 s per tile) | [community scan log](../logs/2026-10-07-community-scan.md) |
| v8in in fp16 on MPS | 5.5 to 6.2 s per tile, about 5x slower than fp32 | [mac.md](../mac.md#watching-a-run) |
| v8in on 4 CPU cores (Linux smoke test) | About 8 s per tile; fp32 batch 8 used about 10 GB of RAM | [community scan log](../logs/2026-10-07-community-scan.md) |
| Full run (not `QUICK`) | Not measured; bounded by `V8IN_HOURS` for v8in | |

It runs locally on the Mac and rents nothing. Full-segment v8in on a CPU is a GPU-sized job (hours), so off a Mac it belongs on Modal with a written spec (the Modal rule, hard rule 11). Log a local run with `python -m kit run local SLUG -- bash scripts/mac-w045.sh` (the local-compute rule, hard rule 9; see [run-local](run-local.md)).

## For agents

- **Command:** `SEGMENT=0841-w00 QUICK=1 bash scripts/mac-w045.sh` on an Apple Silicon Mac, wrapped as `python -m kit run local SLUG -- bash scripts/mac-w045.sh`. Machine-readable results: `WORK/SEGMENT/results/auc_*.json`, `rows_*.json` and the device JSON.
- **Parse:** in each `auc_*.json`, `forward.auc`, `control.auc`, `forward.ink_px`, `crop` and `forward.inner`; in the device JSON, `verdict`; in `rows_*.json`, `forward.score` and `reverse.score`; the digest line in `provenance*.digest`.
- **Rerun:** Safe and resumable: finished passes are reused unless `FRESH=1`; `layers/` and `crop_layers/` are rewritten; results, summary and provenance are overwritten. `auc_ink9um_*.json` and `rows_ink9um.json` have no model or mode tag, so the last run on a segment, `QUICK` or not, wins.
- **Success:** Exit code 0, the device JSON with `verdict` `pass`, and every AUC JSON present.
- **Not a pass:** Any `SMOKE=1` or `EXPECT_GPU=cpu` result; an AUC without its reversed score; a forward AUC close to the reversed one; an `ink_9um` score on w045 read as generalization (it trained on w045's 2.4 um render); a score on a crop other than the standard one with `inner` 64 compared with Gate A bars.
- **Go-ahead:** Nothing to run it on the user's Mac. Posting the summary or scores needs Chase's yes first.
- **Never:** Call a map or a score a reading; drop the reverse control; run two GPU jobs at once (the lock lives in `WORK`, so a second `WORK` folder bypasses it); run full-segment v8in on a laptop CPU.

## Tests

```bash
python -m unittest tests.test_repo -v
```

`test_shell_scripts_parse` checks that the script exists and parses with `bash -n`; `test_mac_scripts_are_bash_32` checks that it uses no syntax macOS bash 3.2 lacks. Nothing in the test suite runs the script; `SMOKE=1 EXPECT_GPU=cpu` is the manual end-to-end test, recorded once on 2026-10-07 on a Linux container (w045, rows 4000 to 4256, columns 2700 to 2956: AUC 0.7631, 0.6688 and 0.5857 forward, 0.3674, 0.2478 and 0.2791 reversed, a test of the script, not a result; [community scan log](../logs/2026-10-07-community-scan.md)). The tools it calls have their own tests.

## History

- 2026-10-21: Failure modes has the `ink_9um` checkpoint SHA-256 refusal, and the v8in failure shows its log path (`bbecb37`).
- 2026-10-08: comments corrected: w045 is not held out from `ink_9um`, which trained on its 2.4 um render (`d841e06`).
- 2026-10-07: Phase 0 support: `MODEL=v8in-1447`, per-model summary and provenance names (`bec6fb9`).
- 2026-10-07: fp16 is dropped when it is slower than fp32 (`ebd4ae3`).
- 2026-10-07: one GPU job at a time, with a shared lock in `WORK` (`58919cc`).
- 2026-10-07: every run writes a provenance record and digest (`858fadd`).
- 2026-10-07: faster step 6: reverse control at stride 42 under `QUICK=1`, fp16 checked against fp32 on the GPU (`35ed7cc`).
- 2026-10-07: `QUICK=1` runs `ink_9um` on the crop only (`cdc08bc`).
- 2026-10-07: other segments reuse w045's device check; the first Mac result recorded (`3d196e6`).
- 2026-10-07: reruns reuse finished passes; smoke and quick outputs get their own names (`c20b382`).
- 2026-10-07: `SEGMENT=` runs the same test on PHerc0841's three segments (`da8cc8c`).
- 2026-10-07: `QUICK=1` compares v8in and `ink_9um` on the 640 px crop (`dbaa5cb`).
- 2026-10-07: first version (`6081aab`).

## Related

- [mac-phase0](mac-phase0.md): queues this script over the PHerc0841 crops and prints Gate A.
- [mac-verify](mac-verify.md): the `ink_9um` CPU against MPS check on w035, in the same `WORK`.
- [auc](auc.md), [rowscore](rowscore.md), [verify](verify.md): the scores and the device check it runs.
- [v8in-run](v8in-run.md) and [layers](layers.md): how v8in runs on the Mac.
- [gate](gate.md): the Gate A rule that ranks the PHerc0841 crop scores.
- [mac.md](../mac.md#watching-a-run): watching a run, log names and per-step times.
- [community scan log](../logs/2026-10-07-community-scan.md) and [w045 log](../logs/2026-10-08-w045-not-held-out.md): the recorded runs and w045's training overlap.
- `device_checks`, `results` and `segments` in [`results.json`](../results.json): the recorded numbers and crops.
