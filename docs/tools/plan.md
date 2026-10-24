# plan: print a First Letters run plan for one eligible scroll, and price a run

`python -m kit plan SCROLL` prints the official First Letters commands for one eligible scroll without running them, `--spiral` prints a large-surface chain from public inputs (center line, lasagna field, villa's spiral fit, render, Ink Lens), and `python -m kit cost` adds up a run's dollars.

| Field | Value |
| --- | --- |
| Id | `plan` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Planning and prizes |
| Run | `python -m kit plan`, `python -m kit cost`, `from kit import plan` |
| Code | `kit/plan.py`, `kit/cli.py` (`cmd_plan`, `cmd_cost`), `kit/data/spiral-inputs-2026-10-24.json` (the `--spiral` inputs) |
| Tests | `tests/test_kit.py` |
| Needs | Python 3.10 or newer, standard library only; it reads the prize snapshot through [prizes](prizes.md). The commands it prints need what it does not install: villa, VC3D's tools, uv, the AWS CLI (step 1), huggingface_hub (through `uvx`), and an NVIDIA GPU with CUDA, or an Apple Silicon Mac with `--mac`. `--spiral` adds git, Python 3.14 for villa's `spiral-fitting` (installed by `uv sync`), the hf CLI for scans whose lasagna field is on Hugging Face, and this checkout's `spaces/ink-lens` with its own requirements |
| Runs on | Any machine. `plan` took 0.11 to 0.49 s and `cost` 0.11 to 0.19 s per call (5 runs each, measured 2026-10-16, 4-core Xeon cloud container). The printed run is another matter: villa's inference on a full segment takes "on the order of an hour on a single GPU" ([tutorial5](https://scrollprize.org/tutorial5)) |
| Network | None. The printed commands, when you run them, reach github.com, huggingface.co and the open-data bucket `s3://vesuvius-challenge-open-data` (`--spiral`: also `SharpMeow/vesuvius-center-lines` and the scan's `SharpMeow/*-lasagna` dataset) |
| Writes | Nothing (prints only). The printed commands write under `villa/vesuvius/` (`checkpoints/`, `ink-dataset/`, `volume-cache/`, `predictions/`, `work/SCROLL_SLUG/`); `--spiral` writes under `work/SCROLL_SLUG/` in the folder you run it from; see Outputs |
| Go-ahead | Not needed to print a plan or a price. Running its GPU steps on rented compute needs Chase's budget decision (the go-ahead rule, hard rule 8); in this repository GPU work goes to Modal through a run spec (the Modal rule, hard rule 11) |
| Released | Public `main` since 2026-10-06 (`2daee8e`). Also inside the AutoPipeline release copy at `faada83`, and as `scrolls-workbench plan` and `scrolls-workbench cost` in the installable package since 2026-10-14 (`2582ab7`) |
| Guide | [WORKFLOW.md](../WORKFLOW.md) (from plan to null or candidate), [mac.md](../mac.md) (the `--mac` path), [compute.md](../compute.md) (hardware and published run costs) |
| Checked | 2026-10-24 against commit `141b9fe` |

## What it does

The organizers' ink detection tutorial ([scrollprize.org/tutorial5](https://scrollprize.org/tutorial5)) shows how to render a traced papyrus surface into a surface volume (a stack of images at depths above and below the surface) and run villa's ink model on it. `kit plan SCROLL` prints that workflow as a commented shell script, filled in for one scroll that is First Letters eligible in the prize snapshot: the scroll's volume id, its zarr path in the open-data bucket and its voxel size come from `kit/data/prizes-2026-10-11.json` ([prizes](prizes.md)). It prints and never runs anything. The commands were copied from the tutorial at villa commit `e0bbb8b`, checked 2026-10-06; paths and flags change upstream, so the tutorial wins when a printed command fails.

The plan, in order:

- **0. Setup:** clone villa, `uv sync --extra models`, check that PyTorch sees the GPU, and download the two `ink_9um` checkpoints the plan uses (the organizers' released 9 um ink model, `hybrid_3d2d` seeds 42 and 43 at step 75,000). `--mac` prints the Apple Silicon version (VC3D.app, Homebrew, an MPS check, and the open villa PR #1865 for GPU inference).
- **1. The control:** PHerc0139 segment w035, which the released models were trained on: copy its mesh, render 28 layers at 9.362 um with `--flip-normals`, run inference. If no letters show here the pipeline is broken; if they do, that proves only that the pipeline runs, since the clean letters are the training labels reproduced ([log](../logs/2026-10-07-w035-cpu.md)).
- **1b. A labeled check:** PHerc0139 w045 with `kit fetch w045`, inference in both depth directions, and [rowscore](rowscore.md) with the reverse map as the control. w045 is unseen by v8in (Youssef Nader's community ink model) but not held out from `ink_9um`, which trained on its 2.4 um render ([log](../logs/2026-10-08-w045-not-held-out.md)); PHerc0841 is the held-out test for these readers, possibly except Hecate ([log](../logs/2026-10-09-pherc0841-hecate.md)).
- **Surface checks** before rendering a target: tifxyz-doctor and windcheck (community tools that read the traced surface only).
- **2. The target:** grow a surface in VC3D, render it the same way as the control, and run inference in both depth directions; then a block for v8in, which reads 24 layer TIFFs instead of a zarr.
- **3. Rules before looking:** write the readout rule first (`kit run init`), `set -o pipefail`, compare forward and reverse depth, triage with rowscore. **4.** If letters appear: tell nobody in public, follow [WORKFLOW.md](../WORKFLOW.md), and the First Letters submission form.

`kit cost` is separate arithmetic: GPU hours times the GPU rate, plus CPU hours times the CPU rate, plus a flat storage or egress amount, rounded to cents. It holds no prices of its own.

What its output is not: a plan is a list of commands, not evidence. A map made by following it is model output, not a reading, and never means letters were found. In this public repository, only the public steps (0, 1 and 1b) are run here; a target run (steps 2 to 4 on an eligible scroll) belongs in Scrolls-private, which holds its preregistration and ledger (the [scroll-session](scroll-session.md) skill), and its GPU steps go to Modal through a run spec.

## When to use it

- Before a First Letters run, to get the command sequence with the right volume paths and voxel size for the scroll.
- To set up the w035 control on a new machine (steps 0 and 1), as [start-here.md](../start-here.md) does on day 2.
- On an Apple Silicon Mac, with `--mac`, for the VC3D.app and MPS setup.
- `kit cost`: for a quick dollar figure from hours and rates, such as a line in a run spec or the amount for `kit run cost`.

Do not use it:

- On a scroll that is not First Letters eligible: it refuses. For a Grand Prize-only scroll such as PHerc1447, or a labeled public segment such as PHerc0841, follow the tutorial directly or use [mac-w045](mac-w045.md) for the labeled benchmarks.
- As a pipeline that runs: it only prints. The [autopipeline](autopipeline.md) release runs villa end to end.
- For Modal prices, rates and budgets: use the Modal calculator, `python -m kit.cloudcost` ([cloudcost](cloudcost.md)).
- To record what a run cost: `kit run cost` writes it to the experiment ledger ([run-ledger](run-ledger.md)); `kit run local` records local time and electricity ([run-local](run-local.md)).
- To check whether a scroll is eligible, or how long is left: use [prizes](prizes.md).

## Quick start

```bash
mkdir -p work && python -m kit plan PHerc0826 > work/pherc0826-plan.sh
python -m kit plan PHerc0826 --mac
python -m kit cost --gpu-hours 6.5 --rate 1.10
```

`PHerc0826` is any scroll name in the snapshot's First Letters list; `PHerc. 826` and `pherc 826` work too. Run on 2026-10-16, the first command wrote a 91-line plan (105 lines with `--mac`) that starts:

```
# First Letters plan for PHerc0826 (prize snapshot 2026-10-11; check scrollprize.org/prizes first)

# 0. Setup (once). Linux or WSL2, NVIDIA GPU with CUDA.
git clone https://github.com/ScrollPrize/villa.git
cd villa/vesuvius && uv sync --extra models
...
# 2. Target: PHerc0826, eligible volume 20250821151701 (9.362 um voxels)
#    Browse: https://scrollprize.org/data_browser/PHerc0826
```

and the cost line printed `$7.15`. It worked when the exit code is 0 and the plan's first line names the scroll and the snapshot date. A refused scroll prints one line on stderr and exits with code 2 (Failure modes).

### The large-surface chain (`--spiral`)

A First Letters area is 4 cm2 of one sheet, larger than many grown segments; villa's spiral fit models a whole scroll as one deformed spiral, so it can give one surface over the whole scan (Interpretation). `--spiral` prints one runnable bash chain per eligible scan from public pieces only, filled in for that scan:

```bash
mkdir -p work && python -m kit plan PHerc0826 --spiral > work/pherc0826-spiral.sh
Z0=2000 Z1=4000 bash work/pherc0826-spiral.sh      # stops at step 9 until you set X and Y (the region)
```

| Step | What the printed command does | Source |
| --- | --- | --- |
| 0 | Clones villa at `e2254eb` and runs `UV_PYTHON=3.14 uv sync --frozen` in `spiral-fitting/` | villa `spiral-fitting/README.md` |
| 1 | `python -m kit centerline get SCROLL --into DS`: the best public center line as `DS/umbilicus.json`, sha256-checked | [centerline](centerline.md) |
| 2 | The lasagna field's `nx`, `ny` and `grad_mag` stores at OME-Zarr level 2 (4x down): `aws s3 sync` of the organizers' run for the 12 scans that have one, or the dataset card's own `hf download` for the 9 that only have Chase Hendrick's public `SharpMeow/<scan>-lasagna` | the bucket; each dataset's card |
| 3 | Writes `DS/spiral-scroll.json`: the catalog's `z_direction_is_top_to_bottom` and `left_handed_coordinates` with the sense villa derives from them, `normal_zarr_group` `"2"`, `lasagna_scale` 4. For the 5 volumes whose catalog entry has no z direction (PHerc0125, PHerc0490A, PHerc0490B, PHerc0846A, PHerc1203), it stops until you set `SENSE` to `CW` or `ACW`, read off the CT in VC3D | villa `fit_session.load_scroll_spec` accepted both forms (checked 2026-10-24) |
| 4 | `pack_resident_pools.py DS/lasagna_inputs --what normals,grad_mag --normal-group 2 --verify 2000` | villa README, "Lasagna inputs must be packed first" |
| 5 | `fit_spiral.py --dataset DS` with `FIT_SPIRAL_CONFIG_OVERRIDES`: the window `Z0` to `Z1` (default the whole scan), grad_mag spacing at factor 0.14, every other input off, room for 300 windings, 30,000 steps, seed 1 | the settings of a whole-scan PHerc0841 pilot started 24 Oct 2026, not yet scored |
| 6 | `flatten_spiral_checkpoint.py CKPT work/SLUG/surface.tifxyz --umbilicus ... --lasagna-dir villa/lasagna --voxel-size-um V` | villa README, "Flattening a fitted checkpoint" |
| 7 | tifxyz-doctor and windcheck on the surface | as the ink plan |
| 8 | Write the readout rule (`kit run init`) and check the reader never trained on your area | hard rule 3 |
| 9 | `vc_render_tifxyz` of a 1024 px region at `X`, `Y` (28 layers, `--flip-normals`), then `spaces/ink-lens/inklens.py run --box X Y 1024 1024 --local` on the same region | [ink-lens](ink-lens.md) |
| 10 | If letters appear: tell nobody in public, then the submission form | WORKFLOW.md |

Status: no run of the whole chain has passed yet. Each command was read from the code at the pinned commits, the printed scripts pass `bash -n`, villa's own spec parser accepts both `spiral-scroll.json` forms, the fit overrides parse as JSON after the shell fills in the window, and `aws s3 sync --dryrun` of step 2 selects only the root metadata and level 2 (103,569 files for PHerc0826's `nx`, 24 Oct 2026). The fit, the flatten, the render and the Ink Lens call were not run here. Users pay for their own compute: a spiral fit needs a CUDA GPU for villa's Triton kernels.

## Checks and controls

- **The plan carries the run's controls:** step 1 (w035) must show letters or the pipeline is broken; step 1b scores w045 against its reverse-depth map; step 2 runs both depth directions, and ink should appear in one, not both; step 3 fixes the readout rule before anyone looks. Each of these can fail.
- **The refusal can fail visibly.** On 2026-10-16 `python -m kit plan PHerc1667` (never eligible), `PHerc1447` (Grand Prize only since it left First Letters) and `"PHerc. 343"` (awarded) each exited with code 2; the last named the award date and its source.
- **The tests pin the plan's content** (`PlanTest`): the control, the resolved target path, `--direction both`, the privacy line, the 8.64 um resampling note, the Mac setup, the w045 check before the target, the surface checks, v8in, `--flip-normals` on the target render, the Hecate caveat for PHerc0841, and the refusals. CI runs `python -m kit plan PHerc0826` and `python -m kit cost --gpu-hours 6.5 --rate 1.10` on every push to `main` and every pull request ([`check.yml`](../../.github/workflows/check.yml)).
- **`kit cost` against published runs:** 6.5 GPU hours at $1.10 an hour gives $7.15, the A10 part of bnleft's PHerc0211 run (the test's comment; that run's whole cost, with 1.5 CPU hours, was $13.53 per [compute.md](../compute.md)). The Modal estimate in the [lane H log](../logs/2026-10-07-grok-laneH.md), `--gpu-hours 3.25 --rate 3.9492 --cpu-hours 3.25 --cpu-rate 0.70 --storage 0.33`, reprints as `$15.44`. It checks nothing beyond arithmetic: negative or missing costs pass.

Claim label: Sourced fact, for the printed commands (scrollprize.org/tutorial5 at villa commit `e0bbb8b`, checked 2026-10-06); the community figures in its comments (Bullo27's row scores, pscamillo's correction, nerln's resampling) are Community reports; `kit cost` is arithmetic on the numbers given.

## Commands and options

### `python -m kit plan`

```
usage: python -m kit plan [-h] [--batch BATCH] [--mac] [--spiral] scroll
```

| Option | Default | Meaning |
| --- | --- | --- |
| `scroll` | required | The scroll, in any spelling `normalize_scroll` accepts (`PHerc0826`, `PHerc. 826`, `pherc 826`). It must be in the snapshot's First Letters list, or the command refuses with exit code 2 |
| `--batch BATCH` | none (4, or 1 with `--mac`) | The `--batch-size` printed in every villa inference command. Not checked: 0 or a negative number is printed as given |
| `--mac` | off | Print the Apple Silicon setup (VC3D.app's tools on `PATH`, uv and awscli from Homebrew, an MPS check, the PR #1865 branch for GPU inference), use batch 1 unless `--batch` is given, and add `--device mps` to the v8in commands |
| `--spiral` | off | Print the large-surface chain (The large-surface chain, above) instead of the ink plan; `--batch` and `--mac` are ignored |

### `python -m kit cost`

```
usage: python -m kit cost [-h] --gpu-hours GPU_HOURS --rate RATE
                          [--cpu-hours CPU_HOURS] [--cpu-rate CPU_RATE]
                          [--storage STORAGE]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--gpu-hours GPU_HOURS` | required | GPU hours, any float |
| `--rate RATE` | required | USD per GPU hour |
| `--cpu-hours CPU_HOURS` | `0.0` | CPU hours billed apart from the GPU, such as a CPU-only render |
| `--cpu-rate CPU_RATE` | `0.0` | USD per CPU hour |
| `--storage STORAGE` | `0.0` | A flat amount in USD for storage or egress |

## Python API

```python
from kit import plan
text = plan.first_letters("PHerc0826", mac=True)      # the plan as one string
usd = plan.cost(6.5, 1.10)                           # 7.15
chain = plan.spiral_chain("PHerc0826")               # the --spiral chain as one string
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `first_letters(scroll, batch=None, snapshot=None, mac=False)` | str, the plan the command prints | `ValueError` with the refusal message for a scroll not First Letters eligible; `KeyError` when the snapshot has no `first-letters-2027` prize | `snapshot` defaults to `prizes.load()`; pass another snapshot dict to plan against it |
| `spiral_chain(scroll, snapshot=None, inputs=None)` | str, the chain `--spiral` prints | `ValueError`: the ink plan's refusal for a scroll not eligible, or `no public spiral-fit inputs recorded for volume V` when `inputs` has no row for the eligible volume | `inputs` defaults to `spiral_inputs()` |
| `spiral_inputs(path=None)` | dict, the inputs file | `OSError`, `json.JSONDecodeError` | Default `kit/data/spiral-inputs-2026-10-24.json` |
| `spiral_spec(scroll, voxel_um, row, group="2", scale=4)` | dict, the `spiral-scroll.json` content | none | `spiral_outward_sense` is `"ACW"` exactly when the two catalog properties differ (villa's rule), or `"$SENSE"` when either is unknown |
| `cost(gpu_hours, rate_per_hour, cpu_hours=0.0, cpu_rate=0.0, storage_usd=0.0)` | float, `gpu_hours * rate_per_hour + cpu_hours * cpu_rate + storage_usd` rounded with Python's `round(..., 2)` | `TypeError` for a value that is not a number | No checks: negative, NaN and infinite values pass through |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| `scroll` | A scroll name | Matched after `normalize_scroll`: upper case, spaces and dots removed, digits zero-padded to 4 |
| The prize snapshot | `kit/data/prizes-2026-10-11.json` through `prizes.load()` | Gives the eligible list, each scroll's `volume`, `zarr` and `voxel_um`, the `awarded` list, and the First Letters `submit` form URL |
| `kit/data/spiral-inputs-2026-10-24.json` | JSON | For `--spiral`: per eligible scan the volume, its slice count and the two catalog properties from the open data's `metadata.json`, and its lasagna source (`bucket` prefix or Hugging Face `dataset`), all read 24 Oct 2026; every store's level 2 is a 4x downsample by its own `.zattrs` |
| `kit cost` numbers | Floats | Hours and USD per hour; no unit conversion, no currency other than USD |

## Outputs

`plan` prints a shell script with comments to stdout. When you run its commands from `villa/vesuvius`, they make these files (SLUG is the scroll name in lower case, such as `pherc0826`):

| Step | Files the printed commands write |
| --- | --- |
| 0. Setup | `checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth` and the seed-43 file |
| 1. Control (w035) | `ink-dataset/pherc0139/w035/w035.tifxyz`, VC3D's cache `volume-cache/20250728140407.zarr`, `ink-dataset/pherc0139/w035/w035_9um.zarr`, `predictions/w035_9um.tif` |
| 1b. w045 | `ink-dataset/pherc0139/w045/w045_9um.zarr`, `predictions/w045_seed42.tif` and its reverse map; rowscore reads `predictions/w045_seed42_reverse.tif`, the name `scripts/mac-w045.sh` also expects villa's `--direction both` to write |
| 2. Target | `work/SLUG/surface.tifxyz` (you make it in VC3D), `volume-cache/VOLUME.zarr`, `work/SLUG/surface_9um.zarr`, `work/SLUG/ink_seed42.tif` and its reverse map |
| v8in block | `checkpoints/ink-8um-v8in/`, `work/SLUG/layers/` (you export it; [layers](layers.md) does this), `work/SLUG/v8in_forward.tif`, `work/SLUG/v8in_reverse.tif` |
| 3. Rules | `experiments/SLUG/run.json` through `kit run init` |

Two things the printed script leaves to you: the target step prints the seed-42 inference command only, though its comment says to run both seeds, so add the seed-43 line; and the `python -m kit fetch` and `python -m kit rowscore` lines need this repository's `kit` importable, so run them from the Scrolls checkout (adjusting the paths) or with the `scrolls-workbench` package installed.

`--spiral` prints a bash script; run from any folder, it writes `work/SLUG/villa/`, `work/SLUG/spiral-dataset/` (`umbilicus.json`, `spiral-scroll.json`, `lasagna_inputs/` with the packed sidecars), `work/SLUG/lasagna/` (Hugging Face scans), `work/SLUG/fit/` (villa's run with `checkpoint_fitted.ckpt`), `work/SLUG/surface.tifxyz`, `work/SLUG/region_X-Y.zarr` and `work/SLUG/inklens.json`, plus Ink Lens's files in the surface folder ([ink-lens](ink-lens.md#outputs)). It stops at the first failing step (`set -euo pipefail`), and Ink Lens's exit code 3 (no ink above the control) stops it too.

`cost` prints one line, `$X.XX`: two decimals, no thousands separator (`$1100000.00`), a minus sign after the dollar sign for a negative total (`$-2.00`), and `$nan` or `$inf` for those values.

| Exit code | Meaning |
| --- | --- |
| `0` | Printed: a plan, or a cost |
| `1` | A Python error with a traceback, such as a missing snapshot file |
| `2` | `plan` refused the scroll (the message is on stderr), or a usage error from the argument parser (either command) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as `cost` without `--gpu-hours`, or `argument --gpu-hours: invalid float value: 'abc'` | Check the command against Commands and options |
| `SCROLL is not First Letters eligible in the 2026-10-11 snapshot. Eligible: NAMES` on stderr, exit code 2 | The scroll is not in the snapshot's First Letters list: a typo, a scroll that was never eligible (PHerc1667), or one that is Grand Prize only (PHerc1447) | Check the name against `python -m kit prizes`; for other scrolls follow the tutorial directly |
| `SCROLL is not First Letters eligible in the 2026-10-11 snapshot. Its First Letters prize was awarded on DATE (SOURCE). Eligible: NAMES`, exit code 2 | The scroll's prize was already awarded (PHerc0343, 2026-10-08) | Pick an eligible scroll; read the live page for the current terms |
| `... awarded on an unrecorded date (no source recorded) ...` | A snapshot's `awarded` entry has no `date` or `sources` | Fill them in the snapshot |
| `KeyError: 'first-letters-2027'` and a traceback | `first_letters` was given a snapshot without the First Letters prize | Pass a full snapshot, or none |
| `$-2.00`, `$nan` or `$inf` from `cost`, exit code 0 | `cost` does not check its numbers | Give non-negative, finite hours and rates |
| `SCROLL: no public spiral-fit inputs recorded for volume V (inputs read DATE); see docs/tools/plan.md`, exit code 2 | `--spiral` on a scroll whose eligible volume is not in the inputs file (a newer snapshot) | Add its row: the volume's catalog properties, slice count and lasagna source |
| `SENSE: set SENSE to CW or ACW, read off the CT in VC3D` from the `--spiral` script | The catalog gives no z direction for this volume, so villa needs the spiral's sense from a person | Read it in VC3D (tutorial_spiral) or from an earlier fit, then `SENSE=CW bash ...` |
| `X: set X` from the `--spiral` script | Steps 0 to 8 are done; the render needs your region | Pick the region from the geometry, write the readout rule, then rerun with `X=... Y=...` (the clone in step 0 fails on a rerun: comment it out) |
| `Error: --volume (...) and --remote-url (...) name different sources` from `vc_render_tifxyz` | A plan printed before 24 Oct 2026 passed a local cache as `--volume` and the bucket as `--remote-url`; current villa refuses that | Print the plan again: it now passes the bucket URL as `--volume` |
| A printed command fails when you run it (an unknown flag, a missing path) | villa changed after commit `e0bbb8b`, or VC3D's tools are not on `PATH` | Follow the tutorial's current text, run [doctor](doctor.md), and record the villa commit you used |

## How it works

1. `first_letters` loads the snapshot (or takes the one given) and looks the scroll up with `prizes.eligible_entry` in `first-letters-2027`. When it is not there, it builds the `ValueError` message from the eligible names and, if the scroll is in the prize's `awarded` list, the award's date and first source.
2. It takes the snapshot's own spelling of the scroll, makes the slug by lower-casing it, and sets the batch to `--batch`, or 1 with `--mac`, or 4.
3. When the scroll's voxel size differs from `NATIVE_UM = 9.362` by more than 0.1 um (the 8.64 um scans), it adds `RESAMPLE_NOTE`: `ink_9um` was trained near 9.36 um, and a published run on PHerc0800 also tried resampling to 9.362 um.
4. It joins the fixed templates in order, `SETUP` or `SETUP_MAC`, `CONTROL`, `HELD_OUT`, `QA`, `TARGET`, `V8IN` and `RULES`, filling in the batch, slug, volume id, zarr name, voxel size, the data browser link (`prizes.DATA_BROWSER` plus the scroll) and the First Letters form.
5. Settings fixed in the templates: render `--scale 1 --group-idx 0 --num-slices 28 --cache-gb 16 --voxel-unit micrometer --flip-normals`; inference `--overlap 0.5 --blend-mode hann`, with `--direction both` for w045 and the target. `--flip-normals` puts the layers in the team's order; without it the forward and reverse maps swap (pscamillo's eligible-mesh maps, corrected 2026-09-15, as the template says).
6. `spiral_chain` takes the same eligible entry, looks up its row in the inputs file (refusing a volume mismatch), and joins `SPIRAL_HEAD`, the bucket or Hugging Face lasagna block, `SPIRAL_FIT` (with `spiral_spec` and `SPIRAL_OVERRIDES`), `SPIRAL_QA`, `SPIRAL_RULES`, `SPIRAL_INK` and `SPIRAL_AFTER`. villa is pinned to `VILLA_SPIRAL` (`e2254eb`, 23 Oct 2026), the commit the commands were read from.
7. `cost` returns `round(gpu_hours * rate_per_hour + cpu_hours * cpu_rate + storage_usd, 2)`, and `cmd_cost` prints it as `$` plus two decimals.

## Cost and time

Printing is cheap: measured 2026-10-16 in a 4-core Xeon cloud container, `plan` took 0.11 to 0.49 s and `cost` 0.11 to 0.19 s per call over 5 runs. The run it prints is not: inference on a full segment takes about an hour on one GPU ([tutorial5](https://scrollprize.org/tutorial5)), and bnleft's full PHerc0211 First Letters run on a Modal A10 took about 6.5 GPU hours and 1.5 CPU hours for $13.53 ([compute.md](../compute.md)). Stock villa inference on a Mac runs on the CPU, about 114 s against 38 s on MPS for one PHerc0139 segment in villa PR #1865's test (the `--mac` setup text). In this repository a GPU step goes to Modal through a run spec in [`docs/compute/modal-specs/`](../compute/modal-specs/README.md) (the Modal rule, hard rule 11), priced with [cloudcost](cloudcost.md).

## For agents

- **Command:** `python -m kit plan SCROLL > work/SLUG-plan.sh` (add `--mac` on Apple Silicon); `python -m kit cost --gpu-hours H --rate R [--cpu-hours C --cpu-rate CR --storage S]`. There is no JSON form.
- **Parse:** the plan is shell text: the line `# 2. Target: SCROLL, eligible volume VOLUME (VOXEL um voxels)` and the `--volume s3://vesuvius-challenge-open-data/SCROLL/volumes/ZARR/` line give the resolved volume. The `--spiral` chain's first line is `# First Letters large-surface chain for SCROLL: ...`. `cost` prints one line `$X.XX`.
- **Rerun:** Safe; both only print. Redirecting the plan to a file overwrites that file.
- **Success:** Exit code 0 and a plan whose first line is `# First Letters plan for SCROLL (prize snapshot DATE; ...)`; for `cost`, exit code 0 and a line starting with `$`.
- **Not a pass:** Letters on w035 (step 1): they show only that the pipeline runs, since w035 is a training segment; a w045 score for `ink_9um` or its fine-tunes as a generalization result; a target map with no reverse-depth comparison; a `kit cost` figure that leaves out CPU time, storage or idle time.
- **Go-ahead:** Nothing to print or price. Renting compute for the printed GPU steps needs Chase's budget decision; posting or submitting anything from a run needs his yes (the go-ahead rule, hard rule 8).
- **Never:** Run the target steps or keep their outputs in this public repository: target runs belong in Scrolls-private (the no-findings rule, hard rule 1); run the GPU steps for hours on a laptop CPU, or try to sign in to Modal from a Claude cloud session (the Modal rule, hard rule 11); call any resulting ink map a reading.

## Tests

```bash
python -m unittest tests.test_kit.PlanTest tests.test_kit.SpiralChainTest tests.test_kit.CliTest -v
```

`PlanTest` (10 tests) checks the control, the resolved target path, `--batch-size`, `--direction both` and the privacy line; the resampling note for an 8.64 um scan (PHerc0800); the Mac setup; the w045 check before the target, the surface checks, v8in and `--flip-normals`; the Hecate caveat; the `kit fetch` short names; the refusal of PHerc1667 and PHerc0343, with the award sentence only for the awarded scroll and a clean refusal when an award entry lacks its date and sources; and `cost(6.5, 1.10) == 7.15`; and that every render passes the bucket URL as `--volume`. `SpiralChainTest` (8 tests) checks that the inputs file covers exactly the snapshot's eligible volumes, the chain's steps in order with the villa commit, the level-2 include, the whole-scan default window and the fit overrides; the Hugging Face path; villa's sense rule and the `SENSE` stop for unknown volumes; that the fit uses no input but the lasagna field and center line; the refusals; and that all 21 chains pass `bash -n`. `CliTest` checks that `plan PHerc1667` exits with code 2. They do not run any printed command, check the commands against villa's current tutorial, or test `--batch` values or `cost`'s command line.

## History

- 2026-10-24: `--spiral`, the large-surface starter chain for every eligible scan from public pieces, with `kit/data/spiral-inputs-2026-10-24.json`; the ink plan's renders pass the bucket URL as `--volume`, since villa now refuses a local `--volume` beside a different `--remote-url`. ([PR #184](https://github.com/ChaseHendrick/Scrolls/pull/184))

- 2026-10-14: a refused scroll whose First Letters prize was awarded gets the award's date and source in the message, read from the 11 October snapshot, and survives an award entry without them; step 1b names v8in-1447 among the readers PHerc0841 is held out from (`19a1f4d`, `4053d23`, [PR #37](https://github.com/ChaseHendrick/Scrolls/pull/37)).
- 2026-10-09: step 1b says PHerc0841 is possibly not held out from Hecate (`3ba683f`, [PR #37](https://github.com/ChaseHendrick/Scrolls/pull/37), [log](../logs/2026-10-09-pherc0841-hecate.md)).
- 2026-10-08: step 1b becomes a labeled check, not a generalization check: `ink_9um` trained on w045's 2.4 um render (`d841e06`, [PR #36](https://github.com/ChaseHendrick/Scrolls/pull/36), [log](../logs/2026-10-08-w045-not-held-out.md)).
- 2026-10-07: `--flip-normals` on the target render (`2f025af`, [PR #2](https://github.com/ChaseHendrick/Scrolls/pull/2), [community scan log](../logs/2026-10-07-community-scan.md)).
- 2026-10-07: step 1b on w045 with rowscore, the surface checks and the v8in commands (`b533efa`, [PR #2](https://github.com/ChaseHendrick/Scrolls/pull/2)).
- 2026-10-07: step 1 says the w035 letters are the training labels reproduced (`3ebb108`, [PR #1](https://github.com/ChaseHendrick/Scrolls/pull/1), [log](../logs/2026-10-07-w035-cpu.md)).
- 2026-10-07: `--mac`, the Apple Silicon setup (`e8f3dda`, [PR #1](https://github.com/ChaseHendrick/Scrolls/pull/1)).
- 2026-10-06: first version: setup, the w035 control, the target and the rules, and `kit cost` (`2daee8e`).

## Related

- [prizes](prizes.md): the snapshot that decides which scrolls this plans for.
- [doctor](doctor.md): checks the machine for what the plan needs.
- [rowscore](rowscore.md): the row score step 1b and step 3 use.
- [fetch](fetch.md): `kit fetch w045` in step 1b.
- [layers](layers.md): exports the layer TIFFs v8in reads.
- [run-ledger](run-ledger.md): `kit run init` for the readout rule in step 3, and `kit run cost` to record what a run cost.
- [centerline](centerline.md) and [ink-lens](ink-lens.md): steps 1 and 9 of `--spiral`.
- [cloudcost](cloudcost.md): Modal rates and estimates, where `kit cost` has none.
- [WORKFLOW.md](../WORKFLOW.md): the path from plan to null or candidate, and what to do with a candidate.
- [state-of-play.md](../state-of-play.md): what others already ran on each scroll, so a plan does not repeat a published null.
