# 2026-10-07: lane F, four bold experiments on public labelled data

Research notes, not claims. Labels per [`../NOVELTY.md`](../NOVELTY.md). Public labelled data only (PHerc0139 w045, PHerc0841 w00). Ink maps are model output, not readings. No target scroll was touched.

## Readout rules (preregistered; committed before any experiment ran)

Common setup. Scoring window: the repo's w00 crop (y 2624 to 3264, x 2688 to 3328) and the lane C w045 crop (y 3840 to 4480, x 2560 to 3200), labels from the 20260918 release at level 2, inner 64 px, scored with `kit.auc.score_array`. Intervals and differences use `kit.auc.block_bootstrap` (300 draws, 107 px blocks, seed 0) with `other` set to the baseline map. "Gain" means AUC(map) minus AUC(baseline) on identical pixels. A gain counts only if it is at least +0.01 and the 95% bootstrap interval of the difference excludes 0. Everything else is null; a gain that passes on one seed or one condition only is inconclusive.

E1, test-time input adaptation of `ink_9um` across scrolls (histogram matching). The w00 crop volume (28 layers) is remapped voxelwise so its intensity CDF matches the w045 crop's CDF, written as a new Zarr, and `ink_9um` seeds 42 and 43 run forward on it with the repo's flags. Baseline: the same seed run forward on the unmatched crop (the existing quick maps). Positive only if both seeds gain. Control: matching w00 to itself must reproduce the baseline within 0.003 AUC (pipeline check); if it does not, the experiment is inconclusive. A per-layer matching variant is reported but does not decide. Note: the model uses InstanceNorm3d, so classical recompute-the-norm-statistics adaptation is already implicit; this tests the input distribution instead.

E2, two-reader disagreement as a false-positive filter on PHerc0841 w00. Readers: `ink_9um` seed 42 (whole-segment map, cropped) and v8in (crop_gpu.npy). Map: rank(s42) minus 0.5 x |rank(s42) minus rank(v8in)|. Baseline: rank(s42). Positive if it gains. It is called filter-specific only if it also beats the plain mean of the two ranks by at least 0.005; otherwise a gain is attributed to ensembling. Control: v8in rolled by a fixed (211, 307) px shift must not gain. Same procedure is reported on w045 for reference, not deciding.

E3, ink as a 3D layer: depth-profile shape transfer. Per-pixel depth profile over all layers of the 5x5 in-plane mean volume, z-scored within each pixel (shape only, brightness removed). A logistic regression is fit on w045 supervised pixels (50,000 sampled, seed 20261007) and applied unchanged to w00. Positive only if the w00 AUC is at least 0.55, above all 8 rolled-map nulls, and at least 0.02 above the same pipeline run with a fixed depth permutation (kit `depth_permutation`, seed 20261007) applied to both volumes. Depth-reversed test input is reported. An unsupervised k-means (k = 6) of w00 profiles is reported descriptively only.

E4, self-training on the unseen scroll's own pseudo-labels. Teacher: `ink_9um` s42 on w00. Pseudo-labels inside the left half of the crop (x < 320): top 10% of teacher = ink, bottom 40% = not ink. Student: logistic regression on globally standardised depth profiles of the 5x5 and 15x15 mean volumes. Evaluation only on the right half (x >= 320) with true labels. Map: 0.5 rank(student) + 0.5 rank(teacher); baseline: rank(teacher), both on the right half. Positive if it gains. Control: a student trained on pseudo-labels rolled by (0, 160) px (wrong positions) must not gain; if it does, the gain is attributed to the features, not self-training, and the result is inconclusive.

## Results

Run on the user's M1 Pro (data in `~/scrolls-work`, work dir `~/scrolls-work/laneF`; no other GPU job was running). Scripts and raw numbers: [`scripts/experiments/2026-10-07-grok-laneF/`](../../scripts/experiments/2026-10-07-grok-laneF/) (`results.json`, logs under `logs/`). Commands, from `~/scrolls-work/laneF`:

```
../venv/bin/python scripts/experiments/2026-10-07-grok-laneF/e1_histmatch.py . ../data zarr   # e1_prep.log
(cd .. && laneF/e1_infer.sh)  # copy in this folder; 6 ink_9um forward runs, 37 to 39 s each, logs e1_*_s4?.log
../venv/bin/python scripts/experiments/2026-10-07-grok-laneF/e234.py . .. results.json        # e234.log, 9.5 s
```

Sanity: `ink_9um` s42 forward on the w00 crop scores 0.8061 (the repo's bar); s43 0.8354; s42 whole-segment map cropped 0.8073 rank AUC.

| Exp | Result | Evidence (AUC, gain with 95% block-bootstrap interval) |
| --- | --- | --- |
| E1 histogram matching w00 to w045 | **Null (harmful)** | s42 0.8061 to 0.6841, gain -0.122 [-0.213, -0.034]; s43 0.8354 to 0.6462, gain -0.189 [-0.318, -0.083]. Per-layer variant: -0.132 and -0.101. Self-match control: identical map (gain 0.000), so the pipeline is sound |
| E2 disagreement filter on w00 | **Null** | filter 0.8082 vs rank s42 0.8073, gain +0.0008 [-0.014, +0.017]; plain mean of ranks 0.8210, gain +0.014 [-0.020, +0.051] (not significant); filter below the mean by 0.013. Rolled-v8in control -0.033. On w045 (reference) filter +0.007 [-0.009, +0.023] |
| E3 depth-profile shape transfer w045 to w00 | **Null** | w00 0.4924 (CI 0.442 to 0.562), inside rolled nulls 0.451 to 0.537; depth-shuffled 0.4928; reversed input 0.468. Fit on w045 itself only 0.634. K-means clusters of w00 shapes have ink rates 0.25 to 0.41 against a base of 0.32 |
| E4 self-training on w00 pseudo-labels | **Null (harmful)** | right-half teacher 0.8832; student alone 0.507; fusion 0.7876, gain -0.096 [-0.168, -0.005]; rolled pseudo-label control student 0.523, fusion -0.085 |

Interpretation (model output, not readings):

- E1: pushing PHerc0841 intensities onto PHerc0139's distribution costs `ink_9um` 0.10 to 0.19 AUC on both seeds. Whatever the model reads on w00 is tied to the scroll's own intensity scale; a monotone remap that changes about 97% of voxels by a mean shift of 18 grey levels destroys it, even though the model normalises each patch. This argues against simple input-level domain adaptation for this checkpoint, and suggests the model uses absolute intensity cues that per-patch robust normalisation does not remove. Untested idea: the reverse direction (matching to the training scrolls' distribution, which we do not have here).
- E2: v8in and `ink_9um` correlate only 0.44 on w00, but their disagreement does not mark false positives. Plain averaging is the better use of a second reader and even that is inside noise on one 640 px window (36 bootstrap blocks).
- E3: brightness-free depth-profile shape carries no transferable ink signal at 9 um, extending lane C's texture null to the depth axis. Ink is not detectable here as a characteristic layer shape by a linear reader; even on the training scroll it reaches only 0.63.
- E4: a linear student on depth profiles cannot learn from the teacher's pseudo-labels (0.51, same as wrong-position labels), so self-training with cheap features is a dead end; a self-training test would need a deep student (fine-tuning `ink_9um` on its own w00 pseudo-labels), which is the obvious next step and costs GPU hours.

Not run: dinovol ink-prototype similarity (needs the dinovol checkpoint from Hugging Face, unreachable from the box and not on the Mac); cross-segment overlap consistency (no overlapping segment pair on hand). Both stay Untested ideas.

Novelty status: no published test of these four at 9 um on PHerc0841 was found in lane C's searches; these are new nulls, not positives.
