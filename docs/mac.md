# Working on an Apple Silicon Mac (M1 Pro)

Checked 2026-10-07. Apple Silicon has no CUDA. Much of the pipeline still runs, but full-segment ink inference is slow on stock villa.

```bash
python -m kit doctor              # on a Mac: "Apple Silicon, no CUDA" is a warning, not a failure
python -m kit plan PHerc0826 --mac
```

## What runs locally

| Step | On an M1 Pro | Source |
| --- | --- | --- |
| Browse scrolls, grow and fix surfaces (GrowPatch) | Yes: native `VC3D.app` for Apple Silicon | [VC3D README, macOS](https://github.com/ScrollPrize/villa/tree/main/volume-cartographer) |
| Render a surface volume (`vc_render_tifxyz`) | Yes: CLI tools ship in `VC3D.app/Contents/MacOS/` | same |
| Flatten with lasagna | Yes, on the GPU: `--device mps` (float32 by default; `LASAGNA_MAX_PRECISION_FLOAT=64` for float64 on CPU) | [villa #1639](https://github.com/ScrollPrize/villa/pull/1639), merged 1 Sep 2026 |
| Ink inference, stock villa | CPU only (`cuda` if available, else `cpu`, in `inference_runtime.py`) | villa `e0bbb8b` |
| Ink inference on the Mac GPU | Open, unreviewed PRs; see below | [#1865](https://github.com/ScrollPrize/villa/pull/1865), [#1812](https://github.com/ScrollPrize/villa/pull/1812) |
| CPU analyses (scan atlas, catalog, audits) | Yes | [first-letters-scan-atlas](https://github.com/claudepro1515/first-letters-scan-atlas), [vesuvius-catalog](https://github.com/Schurkai/vesuvius-catalog) |
| Training ink models | Not practical; rent a CUDA GPU | [compute.md](compute.md) |

Known VC3D issue: the stable build crashes opening some catalog samples, PHerc0826 among them. The latest build fixes it. Re-opening a sample can show a blank view until VC3D restarts ([villa #1910](https://github.com/ScrollPrize/villa/issues/1910)).

## Mac GPU ink inference: already in progress upstream

Several people have written this patch already. Do not write another one.

| PR | Author | Evidence reported | Status 2026-10-07 |
| --- | --- | --- | --- |
| [#1865](https://github.com/ScrollPrize/villa/pull/1865) | nerln | M-series: 114 s CPU vs 38 s MPS on PHerc0139 w029; maps differ by at most 1/255 on 0.002% of pixels | Open; Copilot flagged a regression test that fails on Apple Silicon; a reviewer reported a torch 2.12.1 non-blocking copy bug and a fix |
| [#1812](https://github.com/ScrollPrize/villa/pull/1812) | AndreasHad04 | M1 Max: 0.427 vs 3.261 s per tile; MPS vs CPU max diff 9.5e-7; needs torch 2.14 (fails on 2.8). Changes the separate `ink-detection/optimized_inference` pipeline, **not** the `vesuvius.ink_detection` command the tutorial uses | Open, awaiting code owner |
| [#1770](https://github.com/ScrollPrize/villa/pull/1770) | SurgeFok | M5 Pro: 2.4x end to end | Closed for inactivity |

For the tutorial's `python -m vesuvius.ink_detection.inference.infer`, the relevant PR is **#1865**. It is a four-line change in `inference_runtime.py` that calls villa's existing `get_accelerator()` (CUDA first, then MPS, then CPU), so CUDA machines behave as before. On a Mac it uses MPS automatically; stock `main` gives you the CPU reference.

Related open work: training on MPS ([#1927](https://github.com/ScrollPrize/villa/pull/1927)), `vesuvius.predict` on MPS ([#1988](https://github.com/ScrollPrize/villa/pull/1988)), spiral fitting on MPS and CPU ([#1925](https://github.com/ScrollPrize/villa/pull/1925)).

To use one now:

```bash
cd villa
git fetch origin pull/1865/head:pr-1865 && git checkout pr-1865
```

Record the PR and commit in your ledger (`--villa-commit`). Before trusting MPS output, run the PHerc0139 w035 control on the CPU and on MPS and compare the two maps. If they differ by more than a few grey levels, use the CPU result and report the difference on the PR.

## One command

```bash
git clone https://github.com/ChaseHendrick/Scrolls && cd Scrolls
brew install uv
bash scripts/mac-verify.sh
```

[`scripts/mac-verify.sh`](../scripts/mac-verify.sh) does the whole runbook below: clones villa, builds a Python 3.14 environment with villa's models stack (without its C++ `volume-cartographer` package, which inference does not need), downloads the published w035 surface volume (`kit fetch`, about 1 GB, no AWS CLI) and the seed42 checkpoint, runs the CPU reference on `main` (both directions), runs PR #1865 twice, checks the logs say `Using MPS device` (no silent CPU fallback), runs both `kit verify` comparisons, and prints a summary to paste. Everything lives in `~/scrolls-work` (override with `WORK=`); nothing is uploaded.

## Generalization check on w045: one command

```bash
cd Scrolls && git fetch origin && git checkout claude/jolly-rubin-n55p5t   # until merged
bash scripts/mac-w045.sh
```

[`scripts/mac-w045.sh`](../scripts/mac-w045.sh) answers the question w035 cannot: does a model find ink it was not trained on? PHerc0139 w045 has published ink labels and is in neither model's training set. In the same `~/scrolls-work` as `mac-verify.sh`, the script:

1. Fetches w045 (1.7 GB) and its labels, plus `ink_9um` seeds 42 and 43 and v8in at a pinned revision.
2. Runs `ink_9um` on MPS through PR #1865, both seeds, both directions, and checks the logs for `Using MPS device`.
3. Runs v8in on a 640 px crop on the CPU and on MPS, and stops unless `kit verify` passes, with the reverse map as the control.
4. Runs v8in on MPS over the box around the labelled region, both directions. It picks the stride from the speed it measured and `V8IN_HOURS` (default 4), and the batch size from your memory: fp32 batch 8 needs about 10 GB.
5. Prints a summary to paste: `kit auc` for every map against the labels (forward against reverse) and `kit rowscore`.

Knobs: `V8IN_FP16=1` (half precision on MPS; kept only if the crop check still passes), `V8IN_STRIDE`, `V8IN_BATCH`, `V8IN_REGION=full`. What to expect from the AUC: Bullo27 reports 0.74 to 0.81 for `ink_9um` on another scroll it never saw; about 0.5 means the model reads nothing. A forward AUC close to the reverse AUC means it reads brightness, not ink.

## Runbook: verify MPS against CPU on the control segment

The script above runs exactly this. The published w035 surface volume can replace the render step: `python -m kit fetch w035 ink-dataset/pherc0139/w035/w035_9um.zarr`.

Prerequisite: the PHerc0139 w035 render from `python -m kit plan PHerc0826 --mac`, step 1, at `ink-dataset/pherc0139/w035/w035_9um.zarr` under `villa/vesuvius`. Run everything from `villa/vesuvius` unless noted. `--no-compile` on every run keeps `torch.compile` out of the comparison.

```bash
export VILLA=~/villa
INFER="uv run --extra models python -m vesuvius.ink_detection.inference.infer"
CKPT=checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth
ZARR=ink-dataset/pherc0139/w035/w035_9um.zarr
COMMON="--overlap 0.5 --blend-mode hann --batch-size 1 --no-compile"

# 1. CPU reference on stock villa, both directions (the reverse map is the control)
git -C "$VILLA" checkout main
$INFER $ZARR $CKPT predictions/w035_cpu.tif $COMMON --direction both
#    writes predictions/w035_cpu.tif and predictions/w035_cpu_reverse.tif

# 2. MPS on PR #1865, twice (repeatability)
git -C "$VILLA" fetch origin pull/1865/head:pr-1865 && git -C "$VILLA" checkout pr-1865
$INFER $ZARR $CKPT predictions/w035_mps_a.tif $COMMON
$INFER $ZARR $CKPT predictions/w035_mps_b.tif $COMMON
uv run --extra models python -c "import torch, platform; print(torch.__version__, platform.mac_ver()[0])"

# 3. Compare, from the Scrolls checkout, using villa's environment (numpy, tifffile, imagecodecs)
cd ~/Scrolls
P="$VILLA/vesuvius/predictions"
uv run --project "$VILLA/vesuvius" --extra models python -m kit verify \
  "$P/w035_cpu.tif" "$P/w035_mps_a.tif" --control "$P/w035_cpu_reverse.tif"
uv run --project "$VILLA/vesuvius" --extra models python -m kit verify \
  "$P/w035_mps_a.tif" "$P/w035_mps_b.tif" --control "$P/w035_cpu_reverse.tif"
```

`kit verify` exit codes: 0 pass; 1 fail, or the control was not caught; 2 unreadable input; 3 agreement with no control given. Add `--slug NAME` to store the result in an experiment record, and `python -m kit run record NAME --command "..." --file "$CKPT"` to store the command and checkpoint hash.

Default acceptance: at most 0.01% of pixels differ by more than 2 grey levels. #1865 reported 1 level on 0.002% of pixels, so a healthy MPS run should pass with margin. The control is the reverse-depth CPU map: on w035 it should differ widely from the forward map. w035 is a training segment: its clean letters are the model reproducing its training labels ([log](logs/2026-10-07-w035-cpu.md)). That does not matter for a CPU vs MPS comparison, which only needs the same input on both, but it is not evidence that the model reads unseen ink. If it does not, the comparison cannot tell maps apart and the verdict says so.

Measured in the setup container on 2026-10-07: on the published 2.4 µm w035 ink map (22,640 × 20,400 pixels, about 462 million), `kit verify` passed a copy with 0.002% of pixels changed by one level and caught a 64-pixel-shifted control (34% of pixels beyond tolerance) in 36 s with 2.25 GB peak memory. The 9 µm w035 maps from this runbook are about 30 times smaller.

Adapted from GENChase's three checks. Its third check, exact checkpoint-resume equality, has no counterpart in villa's flat inference, so the runbook checks run-to-run repeatability instead. A torch bug that reads freed memory, like the one reported for 2.12.1 on #1865, would show up there.

## Recorded M1 Pro run (2026-10-07)

CPU vs MPS **pass** (max |diff| 1/255, Pearson 0.99999999), MPS repeat bit-identical, control caught (73.12%), MPS about 4x faster than CPU. Details: [`logs/2026-10-07-w035-cpu.md`](logs/2026-10-07-w035-cpu.md).

## A useful M1 Pro contribution

A fourth speed benchmark adds little. These would help:

1. **Reviewer-grade verification on #1865.** Run the runbook above and post both `kit verify --json` outputs on the PR with chip, macOS and torch versions. The method follows the [GENChase Apple GPU backend](https://github.com/ChaseHendrick/GENChase/blob/main/apps/validate/APPLE-GPU.md). Evidence with a control and a repeatability check is what lets a code owner merge.
2. **Reproduce the torch 2.12.1 bug report** on an M1 Pro, with and without the proposed fix, so #1865 can settle it.
3. **Fix the Apple Silicon regression test** flagged on #1865, coordinating with its author first.

Comment, then ask before pushing to someone else's branch.

## Long runs on a laptop

CPU inference on a full segment can take hours. Plug in, keep the lid open or use `caffeinate -i`, and watch temperatures. [Thermal Pilot](https://github.com/ChaseHendrick/ThermalPilot) shows live fan and SMC temperature readings in its default read-only mode. Do not use its experimental power tuning during runs you will report: its own README says above-stock clocks are unverified.
