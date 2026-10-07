# Cloud jobs on labelled data, CPU (2026-10-07)

Twelve jobs, each run by its own cloud agent in its own Linux container (4 CPUs, 15 GB RAM, about 30 GB disk, no GPU). They answer the open items of [`docs/HANDOFF.md`](../../../docs/HANDOFF.md) that need no Mac, and the next leads for novel results. Every job uses public labelled data only: PHerc0139 w045 and the three PHerc0841 segments (w00, ag896, ag405). No target scroll is touched by any job.

The comparisons below were written down before any of these maps existed (2026-10-07). A job reports every number it was asked for, including the ones that come out against the idea.

## Rules for every job

1. Read [`AGENTS.md`](../../../AGENTS.md) first. Its hard rules bind you. Public labelled data only; never fetch or run anything on a First Letters or Grand Prize target scroll.
2. No maps, volumes, weights or other large files in git. Commit only scripts, small JSON and Markdown, all under `scripts/experiments/2026-10-07-cloud/<job>/`. Do not edit any other file in the repository (the coordinating session folds results into the docs).
3. Plain sentences; never U+2014 or U+2013 dashes. Model output is not a reading.
4. CPU work runs for hours. Start long work with `nohup bash <script> > <log> 2>&1 &`, make it resumable (skip outputs that already exist), and watch the log. Do not run two inference jobs at once: four cores, and v8in needs about 8 GB at batch 4.
5. When done, commit `<job>/results.json` (rows below), `<job>/notes.md` (what ran, timings, anything odd, the tables) and the scripts you ran, then push to your session's branch. End with a one-paragraph summary and the main table in your final message.
6. If something blocks you for more than about 30 minutes (a download fails, a script changed upstream), write what happened in `notes.md`, push, and stop. Do not work around a rule.

## Shared setup (about 20 to 30 minutes)

```bash
cd <repo>
W=$HOME/scrolls-work
SMOKE=1 EXPECT_GPU=cpu WORK=$W SEGMENT=0841-w00 bash scripts/mac-w045.sh            # base v8in
SMOKE=1 EXPECT_GPU=cpu WORK=$W SEGMENT=0841-w00 MODEL=v8in-1447 bash scripts/mac-w045.sh   # PHerc1447 fine-tune
```

One SMOKE run builds everything a job needs for that segment: `$W/venv` (Python 3.14, villa `main` plus PR #1865 checked out in `$W/villa`), `ink_9um` seeds 42 and 43 under `$W/checkpoints/ink_9um/`, the v8in snapshot under `$W/checkpoints/<repo name>/`, the surface volume `$W/data/<SEGMENT>_9um.zarr` and labels `$W/data/<SEGMENT>_labels/{inklabels,supervision}.zarr`. It ends with a 256 px smoke inference; its numbers are a script test, not a result. Use the segment of your job (`0841-w00`, `0841-ag896`, `0841-ag405`, `w045`).

- Python: `PY=$W/venv/bin/python`. villa inference: `(cd $W && $PY -m vesuvius.ink_detection.inference.infer IN.zarr CKPT OUT.tif --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both)` writes `OUT.tif` and `OUT_reverse.tif`. Check out PR #1865 (`git -C $W/villa checkout --detach pr-1865`) before villa inference, as the script does.
- Crops (`y0 y1 x0 x1`; surface shape `H W`): w00 `2624 3264 2688 3328` (4220 4760); ag896 `2496 3136 1600 2240` (4640 4720); ag405 `1024 1664 2496 3136` (3760 4900); w045 `3840 4480 2560 3200` (5980 8240). Voxel size 9.366 um on PHerc0841, 9.362 um on w045.
- Crop zarr for villa: the 5-line Python in `scripts/experiments/2026-10-07-tricks/crops_and_bars.sh`. Crop layers for v8in: `$PY -m kit layers $W/data/<SEG>_9um.zarr OUT_DIR --crop y0 y1 x0 x1` (add `--shuffle 20261007` for the depth-shuffle control; `--start S --count N` for a depth window).
- v8in: `$PY scripts/v8in_run.py --model-dir $W/checkpoints/ink-8um-v8in --layers DIR --output MAP.npy --device cpu --batch-size 4 --stride 21 [--reverse]`. About 8 s per tile on 4 cores; a 640 px crop is about 784 tiles at stride 21, 196 at 42, 100 at 64.
- d9v2: `d9v2_ft-012000.pth` from the v1.0 release of [TAUIL-Abd-Elilah/pherc0826-first-letters-search](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search) (an `ink_9um`-format checkpoint; record its SHA-256). Reader v2: `reader-v2-step040000.pth` from [domenicor046/reader-v2](https://huggingface.co/domenicor046/reader-v2).
- Scoring, always on the crop with a 64 px edge left out, labels at level 2:
  `$PY -m kit auc MAP --control MAP_reverse --labels L/inklabels.zarr --mask L/supervision.zarr --level 2 --crop y0 y1 x0 x1 --surface-shape H W --inner 64 --json`, and the same arguments to `kit hpscore` plus `--voxel-um`. Map ensembles: `$PY -m kit ensemble OUT MAP MAP ... [--method rank]` (ensemble the reverse maps the same way for the control).
- Bars on the same crops (CPU, earlier session), to check your pipeline: `ink_9um` seed 42 forward 0.8061 (w00), 0.6594 (ag896), 0.7838 (ag405); d9v2 0.8994, 0.8230, 0.8319. A rerun should match to about three decimals.

## Result rows

`results.json` is a JSON list of objects with these keys (leave out what does not apply):
`job`, `segment`, `window` ("crop"), `inner_px` (64), `map_from` ("bare-crop" or "full"), `reader`, `settings` (checkpoint, revision, stride, layer window, ensemble method), `device` ("cpu"), `auc_as_stored`, `auc_reversed`, `auc_shuffled`, `hp_r`, `hp_r_reversed`, `ink_px`, `seconds`, `notes`.

## The jobs

| Job | Container work | Question it answers |
| --- | --- | --- |
| `tricks` | Rebuild `scripts/experiments/2026-10-07-tricks/` (its README has the layout) and run `crops_and_bars.sh`, `tricks.sh`, `reader_v2.sh`, then score every map with `score.py`: each reader alone, soup, each z window and the 4-window mean, mirror TTA, shuffle, d9v2 + `ink_9um` and d9v2 + Reader v2 ensembles (mean and rank), on all four crops | Handoff B.1 (the tricks table on three PHerc0841 crops, not one) and lead (d): does window averaging raise the letter-scale score (`hp_r`) as well as pixel AUC? Compare the 4-window mean against the default window and against the best single window, per reader and crop. |
| `v8in-w00`, `v8in-ag896`, `v8in-ag405` | Base v8in on the crop: forward stride 21; reverse stride 42; forward stride 42 (reference); depth-shuffled layers forward stride 42. `ink_9um` seed 42 and d9v2 on the same crop (villa, both directions). Ensembles v8in + d9v2, v8in + `ink_9um`, all three (mean and rank, reverse ensembled the same way). AUC and `hp_r` for every map. | v8in against human labels on the scroll no reader trained on (pending on the Mac; CPU answers it now and the Mac run later checks the device). Lead (b): v8in's shuffle control. Does v8in add to d9v2 in an ensemble? |
| `v8in1447-w00`, `v8in1447-ag896`, `v8in1447-ag405` | The same forward s21, reverse s42 and forward s42 runs with `MODEL=v8in-1447`; d9v2 on the crop; ensemble v8in-1447 + d9v2 (mean and rank). | Does Youssef's PHerc1447 fine-tune read an unseen scroll better than its base (training idea 1 with no training)? |
| `v8inwin-w00`, `v8inwin-ag896`, `v8inwin-ag405` | v8in on the crop at stride 42 for each 24-layer window of the 28 (first check in the model's code how it picks layers from a folder, then export each window so that exactly the intended 24 layers are read), forward and reverse (reverse at stride 64 is enough). Mean of all five windows, forward and reverse. | Lead (a): how much does v8in's AUC depend on its depth window on an unseen scroll, and does the window mean reach the best window, as it did for `ink_9um` and d9v2 (0.820 against 0.819)? |
| `thresholds` | Whole-segment `ink_9um` seed 42 maps, both directions, on the three PHerc0841 segments (about 35 min each) and w045. | Lead (c), see below. |
| `finetune` | `scripts/experiments/2026-10-07-tricks/finetune_smoke.sh` (v8in's PHerc1447 loop, 2 train and 2 val batches on CPU), staging only the data it needs. | Handoff B.2: does the fine-tune loop install and run? Also: per-step CPU time and memory, the data each training idea in `docs/plans/2026-10-07-training.md` would need (sizes, bucket paths), and a GPU-hours estimate per idea. Do not rent anything. |

### `thresholds` in detail

1. **A threshold calibrated on the unseen scroll.** Leave one PHerc0841 segment out: take the median forward `ink_9um` value on labelled ink of the other two, apply it to the held-out one. Report the share of labelled ink and of labelled background at or above it, and the candidate count under millerandmuller's rule (8-connected pixels at or above the threshold, bounding-box long side at least 0.5 mm; their `analyze_target.py` in [first-light-pherc0826](https://github.com/millerandmuller/first-light-pherc0826)), forward and reverse, per cm², and the share of candidates mostly on labelled ink. Compare with the training-segment threshold 0.7843 (the 2026-10-07 log: 2.3 to 3.7 % of ink kept).
2. **What published null rules would have caught on known text.** Read the automatic readout rules of [nerln/vesuvius-first-letters-pherc0800](https://github.com/nerln/vesuvius-first-letters-pherc0800), [bnleft/first-light-pherc0211](https://github.com/bnleft/first-light-pherc0211) and [TAUIL-Abd-Elilah/pherc0826-first-letters-search](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search) (cite file and commit). Apply each rule that can be automated to the PHerc0841 and w045 whole-segment maps, forward and reverse. Report what each rule flags on surfaces where text is known to be present, and on the reversed maps.
3. **How much surface a null needs.** `kit rowscore` (and AUC where labels exist) on random square windows of 0.25, 0.5, 1, 2 and 4 cm² of each whole-segment map, forward and reverse (at least 200 windows per size where the segment allows; fixed seed; windows mostly on the surface). Report, per size, the share of forward windows whose row score is above the 95th percentile of reverse windows of the same size. This estimates the smallest surface on which the row score can tell this signal from its control: a null on less surface than that says little.
