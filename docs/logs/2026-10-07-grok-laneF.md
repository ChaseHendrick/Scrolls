# 2026-10-07: lane F, four bold experiments on public labelled data

Research notes, not claims. Labels per [`../NOVELTY.md`](../NOVELTY.md). Public labelled data only (PHerc0139 w045, PHerc0841 w00). Ink maps are model output, not readings. No target scroll was touched.

## Readout rules (preregistered; committed before any experiment ran)

Common setup. Scoring window: the repo's w00 crop (y 2624 to 3264, x 2688 to 3328) and the lane C w045 crop (y 3840 to 4480, x 2560 to 3200), labels from the 20260918 release at level 2, inner 64 px, scored with `kit.auc.score_array`. Intervals and differences use `kit.auc.block_bootstrap` (300 draws, 107 px blocks, seed 0) with `other` set to the baseline map. "Gain" means AUC(map) minus AUC(baseline) on identical pixels. A gain counts only if it is at least +0.01 and the 95% bootstrap interval of the difference excludes 0. Everything else is null; a gain that passes on one seed or one condition only is inconclusive.

E1, test-time input adaptation of `ink_9um` across scrolls (histogram matching). The w00 crop volume (28 layers) is remapped voxelwise so its intensity CDF matches the w045 crop's CDF, written as a new Zarr, and `ink_9um` seeds 42 and 43 run forward on it with the repo's flags. Baseline: the same seed run forward on the unmatched crop (the existing quick maps). Positive only if both seeds gain. Control: matching w00 to itself must reproduce the baseline within 0.003 AUC (pipeline check); if it does not, the experiment is inconclusive. A per-layer matching variant is reported but does not decide. Note: the model uses InstanceNorm3d, so classical recompute-the-norm-statistics adaptation is already implicit; this tests the input distribution instead.

E2, two-reader disagreement as a false-positive filter on PHerc0841 w00. Readers: `ink_9um` seed 42 (whole-segment map, cropped) and v8in (crop_gpu.npy). Map: rank(s42) minus 0.5 x |rank(s42) minus rank(v8in)|. Baseline: rank(s42). Positive if it gains. It is called filter-specific only if it also beats the plain mean of the two ranks by at least 0.005; otherwise a gain is attributed to ensembling. Control: v8in rolled by a fixed (211, 307) px shift must not gain. Same procedure is reported on w045 for reference, not deciding.

E3, ink as a 3D layer: depth-profile shape transfer. Per-pixel depth profile over all layers of the 5x5 in-plane mean volume, z-scored within each pixel (shape only, brightness removed). A logistic regression is fit on w045 supervised pixels (50,000 sampled, seed 20261007) and applied unchanged to w00. Positive only if the w00 AUC is at least 0.55, above all 8 rolled-map nulls, and at least 0.02 above the same pipeline run with a fixed depth permutation (kit `depth_permutation`, seed 20261007) applied to both volumes. Depth-reversed test input is reported. An unsupervised k-means (k = 6) of w00 profiles is reported descriptively only.

E4, self-training on the unseen scroll's own pseudo-labels. Teacher: `ink_9um` s42 on w00. Pseudo-labels inside the left half of the crop (x < 320): top 10% of teacher = ink, bottom 40% = not ink. Student: logistic regression on globally standardised depth profiles of the 5x5 and 15x15 mean volumes. Evaluation only on the right half (x >= 320) with true labels. Map: 0.5 rank(student) + 0.5 rank(teacher); baseline: rank(teacher), both on the right half. Positive if it gains. Control: a student trained on pseudo-labels rolled by (0, 160) px (wrong positions) must not gain; if it does, the gain is attributed to the features, not self-training, and the result is inconclusive.

## Results

(Filled in after the runs.)
