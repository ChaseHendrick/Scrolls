# Lane I preregistration (2026-10-07)

Written and committed before any lane I number was computed. Labels per `../NOVELTY.md`. Public labelled data only: PHerc0841 w00, 20260918 labels at level 2, scored on the 9 um surface grid with `kit.auc.label_grid` (nearest neighbour). No target scroll. Model maps are model output, not readings.

Readers (fixed, no tuning):

- TEAM: the published 2.4 um `new_canon_autoresearch_recipe` ink map for w00, mean pooled 4 x 4 onto the label grid, then indexed like the labels.
- B1..B4: mean surface brightness of layers 0..6, 7..13, 14..20, 21..27 of the 28 layer 9 um surface volume (higher = ink, as in lane G).
- BAVG: mean of the average ranks of B1..B4 (the untuned 4 window average).

Crops: every 640 x 640 window on a 320 px stride; inner 64 px dropped; a crop is valid if at least 20 % of its inner pixels are supervised and ink and background are each at least 2 % of them. "Repo crop" = y 2624..3264, x 2688..3328. Full region = all supervised pixels. Bootstrap: `kit.auc.block_bootstrap`, 300 draws, 107 px blocks, seed 0.

## R1, does one crop's bootstrap interval describe the segment?

For each reader: share of valid crops whose AUC lies inside the repo crop's 95 % interval, and the mean over crops k of the share of other crops inside crop k's interval. Also between crop SD vs median (half width / 1.96). Rule: an evaluation problem is declared if the mean coverage is below 0.80 for TEAM or for BAVG. Otherwise null.

## R2, do significant crop level orderings transfer within one tracing?

Pairs: the 10 pairs among B1..B4 and BAVG, plus TEAM vs BAVG. Per crop: AUC difference with bootstrap interval. Among crop level differences whose interval excludes 0, the share whose sign disagrees with the full region sign (only pairs whose full region interval excludes 0). Rule: problem declared if that share is at least 0.20. Also reported: share of crops whose best of B1..B4 equals the full region best.

## R3, descriptive only

TEAM full region AUC with interval. No leakage claim is made from it.

## P1, downsampled proxy (tool track)

Maps averaged and labels pooled 2 x 2 and 4 x 4 (a pooled pixel is supervised only if all its children are; ink if at least half are). Per crop and reader, proxy AUC vs full resolution AUC. Pass if, for every reader with at least 10 crops, Spearman is at least 0.95 and the maximum absolute error is at most 0.02, and pairwise ordering signs agree on at least 95 % of crop pairs where the full resolution difference is at least 0.01. Wall time of proxy vs full is reported as the speedup.

## T1, whole segment crop scan tool

A vectorized scan (one quantization, per crop histogram AUC) vs looping `kit.auc.score_array` per crop. Pass if every crop AUC agrees within 1e-4. Speedup = loop time / scan time on the same machine.
