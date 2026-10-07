# 2026-10-07: lane H, fine-tuning `ink_9um` (preregistered cloud job, not yet run)

Research notes, not claims. Labels per [`../NOVELTY.md`](../NOVELTY.md). No reading is claimed; there are no results yet.

## What happened

- Hardware check: the user's Mac was listed as not connected (ListMachines, 10:46 ET), and a hardware query to it did not return, so no MPS check or Mac run was done. The user then asked for a cloud job instead of Mac training.
- Prior work read: the training plan, `compute.md`, `HANDOFF.md`, `NOVELTY.md`, lane F's log (E4 linear self-training null), and `claude/gallant-pasteur-b1y2si-finetune` (v8in loop smoke test was blocked; CPU fine-tune estimated about 180 CPU hours for v8in, so GPU is needed).
- Cloud provider: no GPU credentials (Modal, RunPod, Vast) exist on the agent box. Earlier repo cloud jobs were CPU agent containers; the documented pay-per-second GPU precedent is Modal. The job is written for Modal and for any Linux CUDA machine.
- villa read at `e0bbb8b40a2db58b1d71864f286eb85717e59e64` (main) to reuse its model building, checkpoint selection and flat preprocessing in the fine-tune loop. The job itself runs villa PR #1865 as the repo's setup does.

## Preregistration

The arms, leakage rule and readout rule are in [`../../scripts/experiments/2026-10-07-cloud/laneH-finetune/README.md`](../../scripts/experiments/2026-10-07-cloud/laneH-finetune/README.md), committed before any training. Four variants: P90, P80 (self-training on w00 pseudo-labels outside the w00 crop + 64 px), S1 (w045 labels, test w00), S2 (w00 labels, test w045). Base: `ink_9um` s42 (w00 crop bar 0.8061). Controls: reverse depth and fixed depth shuffle.

## Compute estimate (not measured)

One A10G 24 GB on Modal, about 2.5 h, hard cap 4 h. `python -m kit cost --gpu-hours 3 --rate 1.10` = $3.30; cap $4.40 (assumed list rate). Not launched; needs the user's go-ahead and Modal account.

## Results

None yet. Code was syntax-checked only; the fine-tune loop has not run (no GPU, no villa environment on the agent box). The first launch should be the `--smoke-steps 5` run.

## Amendment, 11:05 ET: parallel H100 layout (hardware only)

At the user's request the job now runs P90, P80, S1 and S2 in parallel on Modal, one H100 each, after a CPU `prepare` step and one H100 `base` step, with the Volume caching env, data, checkpoint and base maps. Per-phase timing goes into `results.json`. `--smoke-steps N` runs all four in parallel briefly. The preregistered arms, recipe and readout rule are unchanged (first committed in `3a9e06c`).

Pricing from https://modal.com/pricing (fetched 2026-10-07): H100 $0.001097/s. Estimate (not measured): about 1.75 h wall on first run (1.25 to 3 h), $15.44 central (`kit cost --gpu-hours 3.25 --rate 3.9492 --cpu-hours 3.25 --cpu-rate 0.70 --storage 0.33`), $26.24 upper, smoke run $5.21. Nothing launched. Code syntax-checked only.
