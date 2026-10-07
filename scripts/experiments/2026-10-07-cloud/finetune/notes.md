# Cloud job `finetune` (2026-10-07)

Container: 4 CPUs, 15 GB RAM, about 31 GB free disk, no GPU, Python 3.13 system, `uv` present.

## 1. Smoke test: NOT RUN (blocked)

Status: **not run.** The fine-tune loop did not execute in this container, so there is no log tail, no measured per-step CPU time and no measured peak memory. Nothing below is a measurement of the loop.

What happened:

1. Cloned [YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062](https://huggingface.co/YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062) at commit `2bf9f421862cda0ed41dcae6e8274c12e295d03a` (2026-09-28 19:26 UTC) into its own folder, LFS files not fetched.
2. Read `training/finetune_loo_w062.py` in full and searched `training/lib/` (10,508 lines) for subprocess, `os.system`, `eval`/`exec`, pickle, network and Hub calls. Findings: the entry script only downloads from the Hub (`snapshot_download` of the surfaces dataset, `hf_hub_download` of v8in) and then `os.execv`s `lib/train_resnet3d.py`; the library makes no network calls of its own; the init checkpoint is read with `safetensors` (`checkpointing.py`), `torch.load` is used only for non-safetensors checkpoints; W&B is off unless `--wandb`. The smoke script's patch target (`"--devices", "1", "--accelerator", "gpu", "--precision", "16-mixed",`) is present unchanged, so `finetune_smoke.sh` would apply cleanly.
3. Started `run_smoke.sh` (this folder: runs `scripts/experiments/2026-10-07-tricks/finetune_smoke.sh` unchanged and samples summed RSS of the venv's processes every 2 s). The session's permission layer **denied the launch** ("Code from External": running code downloaded from the Hub). Per the job rules I did not work around the denial. The coordinating session or the user can run it where that permission is granted:

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone https://huggingface.co/YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062 ~/ft-src/loo-w062
FT=$HOME/scrolls-cpu/ft TRAIN_SRC=$HOME/ft-src/loo-w062 \
  nohup bash scripts/experiments/2026-10-07-cloud/finetune/run_smoke.sh > ~/scrolls-cpu/smoke_wrapper.log 2>&1 &
```

What the smoke run would download (from the Hub listing, dataset commit `7e4d918712a8d8642a6fdeee45b80217c1e98317`): w058 and w060 layers (24 TIFFs each, 0.537 and 0.549 GB) and labels (`inklabels.png`, `mask.png`, about 1.2 MB in all), plus v8in `model.safetensors`, plus the venv (torch 2.8.0 CPU and the pinned requirements, about 2 to 3 GB). About 4 GB of disk. It does **not** use w062: the loop trains and validates on w058 + w060 by default.

### Expected CPU cost (Interpretation, extrapolated, not measured)

Basis: v8in inference costs about 8 s per 64 px tile on 4 CPU cores in fp32, because each tile is upsampled to 96 x 256 x 256 ([`docs/logs/2026-10-07-community-scan.md`](../../../../docs/logs/2026-10-07-community-scan.md), line 70). A training step is usually about three forward passes of compute (forward plus backward).

| Quantity | Estimate |
| --- | --- |
| One training micro-batch (4 tiles), CPU fp32 | about 1.5 min (4 x 8 s x 3) |
| One optimizer step (8 micro-batches) | about 13 min |
| Smoke run (2 train micro-batches, 2 val batches of 16 tiles) | about 3 min train + about 4 min val + setup and data load; roughly 15 to 25 min |
| Full recipe on this CPU (850 optimizer steps) | about 180 CPU-hours: not feasible here |
| Peak memory | unknown. Inference at batch 4 used about 8 GB; training keeps activations for the backward pass, so batch 4 may exceed 15 GB. If it is killed, retry with a smaller micro-batch (edit `train_batch_size` in a scratch copy of the config) and record that it was changed. |

## 2. Data each training idea needs

Sizes from the Hub tree API and anonymous S3 listings on 2026-10-07. No target scroll was listed below the scroll level, and nothing was downloaded.

### Idea 1: train on PHerc1447

| Item | Path | Size |
| --- | --- | --- |
| w058 layers + labels | `hf://datasets/YoussefMoNader/ink-8um-pherc1447-surfaces/w058/{layers,labels}` | 0.537 GB + 0.55 MB |
| w060 layers + labels | `.../w060/{layers,labels}` | 0.549 GB + 0.60 MB |
| w062 layers | `.../w062/layers` | 0.586 GB |
| v8in init | `hf://YoussefMoNader/ink-8um-v8in/model.safetensors` (rev `d89166b4`, as pinned in `finetune_smoke.sh`) | |
| Released fine-tune (step one, no training) | `hf://YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062/model.safetensors` | |

**Sourced fact that changes the plan:** the dataset releases labels for w058 and w060 only. w062 has layers and predictions but no `labels/` folder (dataset README: "w058 and w060 also include the refined ink labels"; its table lists w062's labels as empty (a dash)). So "train on all three windings" in the training plan cannot be done with public data: the labelled set is w058 + w060, 45.1 cm² of surface (22.2 + 22.9 cm²), 2,718 admitted 64 px tiles. The training script also refuses windings without labels.

The bucket has 16 PHerc1447 segments, none with a 1.129 um `mrg` map, so PHerc1447 adds nothing to idea 2.

### Idea 2: a 1 um teacher

Inventory script: `inventory_mrg.py` (lists segments of non-target scrolls with a `ink-detection/*1.129um*mrg*` map) then `inventory_shapes.py` (reads each 9 um zarr's `0/.zarray`). Output: `idea2_inventory.json` (74 rows, one per segment). Skipped without listing: every scroll in `kit/data/prizes-2026-10-06.json` except PHerc1447, and PHerc0841 (the test scroll).

| Scroll | Segments with 1 um mrg | With 9 um surface volume | Used | Excluded | Surface bbox (cm²) | 9 um level 0, uncompressed upper bound | mrg maps |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PHerc0139 | 37 | 37 (`9.362um-1.2m-113keV-volume-20250728140407.zarr`) | 36 | w045 (held-out test) | 1,755.7 | 56.1 GB | 1.78 GB |
| PHerc0814 | 18 | 18 (`9.362um-1.2m-113keV-volume-20250804134230.zarr`) | 17 | 46527 (nestorvfx evaluation segment) | 1,292.7 | 41.3 GB | 1.64 GB |
| PHerc1667 | 19 | 0 (only 1.129 um and 2.399 um volumes) | 0 | all 19 | | | 1.99 GB |
| **Total usable** | | | **53** | | **3,048** | **97 GB** | **3.4 GB** |

Notes:
- Bucket paths: `s3://vesuvius-challenge-open-data/<scroll>/segments/<segment>/ink-detection/<...>-1.129um-...-mrg20736-1um-s1z2-tile256-stride128.tif` and `.../surface-volumes/9.362um-...zarr/` (zarr v2, `(28, H, W)` uint8, chunks 28 x 128 x 128, no compressor). The "uncompressed upper bound" is 28 x H x W at level 0; empty chunks may be absent, so the real download is smaller. A staging script should fetch only chunks inside the mrg map's non-zero area.
- The bbox area includes empty canvas; papyrus is a fraction of it (Interpretation: about half).
- 7 of the 53 also have human `ink-labels/`.
- w035 (the pipeline-check segment) is in the 36 and was a training segment of `ink_9um`; keep it or drop it by choice, it does not touch the test set.
- PHerc1667 could be added by reading its 2.399 um volume at pyramid level 2 (about 9.6 um), as nestorvfx did, but that is a different scan protocol from the 9 um survey scans; not counted.
- The 1.1 um canvas has to be mapped onto the 9 um canvas (scale about 8.29); TAUIL's `align9.py` does the 2.4 um case. Not attempted here.

### Idea 3: self-supervised pre-training

[`nestorvfx/vesuvius-ink256-pretrain-sheets`](https://huggingface.co/datasets/nestorvfx/vesuvius-ink256-pretrain-sheets) (commit `b02c04db02675d0a4fb2aad5a8c812c6b1da0388`, 2026-10-05; CC BY-NC 4.0): 41 tar files, `volumes/<volume>.tar`, 384.7 GB in all. Each unpacks to zarr v2 sheets, `image` uint8 (21, H, W), 21 layers one voxel apart, with `origins` of 256 x 256 crops.

| Subset | Tars | Size |
| --- | --- | --- |
| First Letters / Grand Prize target scrolls (per the prize snapshot) | 25 | 295.2 GB |
| PHerc0841 (our test scroll: should be excluded to keep the PHerc0841 test fair) | 2 | 15.3 GB |
| Other scrolls (0009B, 0139, 0332, 0343P, 0500P2 x2, 0814 x2, 1299, 1447, 1451, MAN5, MANB, MANBp) | 14 | 74.3 GB |

The idea's point is pre-training on the eligible scans, which means downloading target-scroll data (as unlabelled pretraining input, not maps). That is a decision for the user; this job did not fetch any of it. A first test could pretrain on the 74.3 GB non-target subset only. Its sheets use 21 layers, v8in reads 24 (`in_chans: 24`), so the encoder input needs adapting (pad or re-render). nestorvfx's held-out evaluation segments: PHerc0139 w016, PHerc0814 46527, PHerc1667 w029, PHerc Paris 4 w02.

## 3. GPU-hours estimates (Interpretation)

Throughput basis: the loo-w062 model card says one epoch of the recipe takes about 3 min plus about 30 s of validation on an RTX PRO 6000 (Blackwell) in fp16, with 2,718 tiles per epoch, so about 15 training tiles per second; 32 GB of GPU memory is enough. A 24 GB RTX 3090 or 4090 is assumed 2 to 3 times slower and may need micro-batch 2 with accumulation 16 (same effective batch 32).

| Idea | Work | RTX PRO 6000 | RTX 3090 / 4090 class |
| --- | --- | --- | --- |
| 1 | Score the released fine-tune on PHerc0841 (no training; three 640 px crops) | minutes | minutes; also runs on the Mac |
| 1 | Re-run the released recipe (w058 + w060, 10 epochs) | about 0.6 h | about 1.2 to 1.8 h |
| 1 | Small sweep, e.g. 4 variants (lr, epochs, depth order) | about 2.5 h | about 5 to 7 h |
| 2 | 53 segments, 64 px tiles at stride 48 (0.00202 cm² per tile at 9.36 um): 1.5 M tiles in the bbox, about 0.75 M on papyrus | about 14 h per full epoch | about 28 to 42 h per epoch |
| 2 | Practical: about 100 k sampled tiles per epoch, 5 epochs | about 9 h | about 18 to 28 h |
| 3 | Masked reconstruction, one pass over the non-target 74 GB (about 110 k distinct 256 px crops, assuming 2:1 zstd) | about 2 h | about 4 to 6 h |
| 3 | One pass over all 385 GB (about 560 k crops), needs target data | about 10 h | about 20 to 30 h |
| 3 | Typical pretraining (10 to 20 passes) on all of it | 100 to 200 h | 200 to 600 h |

How the idea 3 numbers were made: 385 GB of zstd uint8 assumed to be about 770 GB raw; divided by 21 layers x 256 x 256 bytes gives about 560 k non-overlapping crops; one 256 x 256 crop at 21 to 24 layers, upsampled in depth to 96, is the same tensor v8in sees for one upsampled 64 px tile, so the same 15 crops per second. The crop count is the weakest number here: the per-volume `index.jsonl` gives the exact count but sits inside the tars.

For scale: d9v2 (an `ink_9um`-size model) took 1.3 to 2 h on one RTX 3090 (training plan). v8in is larger and upsamples every tile 4x in each axis and 4x in depth, which is why its per-tile cost dominates every estimate above.

## Files

| File | What it is |
| --- | --- |
| `run_smoke.sh` | Wrapper that runs `finetune_smoke.sh` unchanged and records wall time and peak summed RSS. Written, launch denied, never ran. |
| `inventory_mrg.py` | Lists non-target segments with a 1.129 um mrg map. Its first run used a 9 um regex that also matched `2.399um`; fixed in the file, and `inventory_shapes.py` recomputes the 9 um list from the stored volume names. |
| `inventory_shapes.py` | Adds 9 um shapes, bbox areas and exclusions; prints totals per scroll. |
| `idea2_inventory.json` | The 74-segment inventory (object names and sizes only). |
| `results.json` | One status row; this job has no AUC numbers. |
