# Cloud job `laneH-finetune`: fine-tune `ink_9um` seed 42 (2026-10-07)

Preregistration and ready-to-run job spec. Committed before any training. Nothing has been trained or launched; no numbers exist yet. Labels per [`docs/NOVELTY.md`](../../../../docs/NOVELTY.md): every map is model output, not a reading. Public labelled data only (PHerc0841 w00, PHerc0139 w045). No target scroll is touched. PHerc0841 ag405 (the plan's audit segment) is not used at all.

Follows the rules of [`../README.md`](../README.md) (paths, crops, scoring), with one difference: this job needs one NVIDIA GPU, so it is a Modal job instead of a CPU container.

## Why

Lane F's E4 ([log](../../../../docs/logs/2026-10-07-grok-laneF.md)) found self-training with a linear student null. The next step is to adapt `ink_9um` itself, at low learning rate, and see whether it beats its own base on held-out labelled crops.

## Base and arms (4 trained variants in total; all counted)

Base: `scrollprize/ink_9um` `hybrid_3d2d-seed42/step-075000.pth` (SHA-256 logged at run time). Bar: base s42 forward on the w00 crop, 0.8061 (earlier CPU and Mac runs); the job reruns it on GPU and compares to the rerun.

Common recipe: AdamW, lr 1e-5 cosine to 0, weight decay 1e-4, 3 epochs of 400 steps, batch 8, the checkpoint's own crop size, depth window and normalisation, horizontal flip only, BCE with pos_weight from the supervised ink fraction (cap 10), seed 20261007. Checkpoints after each epoch, but only `last.pth` is scored (no checkpoint picking). Weights stay outside git (Modal volume `scrolls-laneH`).

| Arm | Train on | Excluded | Test (decides) | Reference only |
| --- | --- | --- | --- | --- |
| P90 (self-training) | w00 whole surface, base s42 forward map as target: >= 0.90 ink, <= 0.10 not ink, rest ignored. Human labels not used | w00 crop + 64 px gap on every side | w00 crop | w045 crop |
| P80 (self-training) | same, thresholds 0.80 / 0.20 | same | w00 crop | w045 crop |
| S1 (supervised) | w045 human labels inside its supervision mask | w045 crop + 64 px gap | w00 crop (other scroll) | w045 crop (excluded region; same segment) |
| S2 (supervised, reverse) | w00 human labels inside its supervision mask | w00 crop + 64 px gap | w045 crop (other scroll) | w00 crop (same segment) |

Leakage rule: a training window is admitted only if the whole patch lies at least 64 px outside the excluded box, and all targets inside box + 64 px are zero-weighted as well (`finetune_ink9um.py`, `allowed_mask`). ag896 is not used for testing: it is the same physical sheet as w00 (the repo's overlap finding), so any arm trained on w00 would leak into it. P on w00 is same-segment adaptation: it shows whether self-training on an unlabelled part of a surface helps on the rest, not cross-scroll transfer.

## Readout rule (fixed now)

Scored with `kit auc MAP --control MAP_reverse --labels ... --mask ... --level 2 --crop ... --surface-shape ... --inner 64 --bootstrap 300 --compare BASE_MAP --json` on the test crop. Gain = AUC(fine-tuned) minus AUC(base s42) on identical pixels.

A model counts as better than base only if all hold:

1. Gain >= +0.01 and the 95 % paired bootstrap interval of the difference excludes 0.
2. Reversed-depth control: its reverse AUC stays at least 0.10 below its forward AUC, and rises by no more than 0.02 over base's reverse AUC.
3. Depth-shuffled input (fixed permutation, seed 20261007): its shuffled AUC gain over base shuffled is less than half its forward gain (else the gain is not depth-ordered).

Arm P is positive only if P90 or P80 passes on the w00 crop; with two thresholds tried, one pass with the other far below is reported as inconclusive. S1 and S2 are judged separately; both passing is needed to say supervised cross-scroll fine-tuning helps in both directions. Everything else is a null and is reported as such, with the numbers. No setting is changed after seeing results; any rerun with changed settings is a new, separately labelled variant.

## Compute and cost (estimate, not measured)

- Provider: Modal (the repo's documented pay-per-second precedent, bnleft's A10 run in [`docs/compute.md`](../../../../docs/compute.md)). No Modal token or other GPU credential exists on the agent box; the user launches with their own account.
- GPU: 1 x NVIDIA A10G 24 GB, 8 vCPU, 32 GB RAM, about 15 GB disk on the volume. Any >= 16 GB CUDA GPU works.
- Time: setup and downloads about 0.5 to 1 h (the repo setup also runs its CPU smoke tests), whole-surface base map on w00 a few minutes, 4 trainings x 1,200 steps about 0.5 to 1 h, 42 crop inferences and scoring about 0.3 h. Estimate 2.5 h; hard timeout 4 h.
- Cost: `python -m kit cost --gpu-hours 3 --rate 1.10` gives $3.30; the 4 h cap gives $4.40 (A10G list rate assumed $1.10 per GPU hour; check current pricing).

## Launch (user action; nothing was launched)

```bash
pip install modal && modal token new
modal run scripts/experiments/2026-10-07-cloud/laneH-finetune/modal_app.py --smoke-steps 5   # pipeline test, numbers not results
modal run --detach scripts/experiments/2026-10-07-cloud/laneH-finetune/modal_app.py          # full job
modal volume get scrolls-laneH laneH/results.json scripts/experiments/2026-10-07-cloud/laneH-finetune/results.json
```

Any Linux CUDA machine works without Modal: `WORK=$HOME/scrolls-work bash scripts/experiments/2026-10-07-cloud/laneH-finetune/run_job.sh` from the repo root.

## Files

- `finetune_ink9um.py`: the fine-tune loop (villa's model, config and preprocessing; saves villa-loadable checkpoints).
- `run_job.sh`: setup, crops (stored and shuffled), pseudo-label source map, 4 trainings, inference, scoring. Resumable.
- `collect.py`: score JSONs to `results.json` rows.
- `modal_app.py`: Modal launcher.
- `results.json`: status record now; replaced by real rows after the run.
