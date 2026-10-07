# Lane I: crop placement and a downsampled proxy (2026-10-07)

Rule preregistered in commit 2f8d7e7 (`docs/prereg/2026-10-07-grok-laneI.md`), pushed before any number was computed. Labels: Null and Model output only. No reading is claimed. Public PHerc0841 w00 only.

## Commands (box CPU; the Mac was offline so no lane B, H or cost-ledger job was touched; the local cost logger had not landed on main, so runs are not wrapped)

```
LANEI_CACHE=CACHE_DIR python scripts/experiments/2026-10-07-grok-laneI/run.py DATA_DIR results.json
```

DATA_DIR holds the w00 20260918 labels (level 2), the 28 layer 9 um surface volume and the team's 2.4 um `new_canon_autoresearch_recipe` w00 ink map. Output: `scripts/experiments/2026-10-07-grok-laneI/results.json` (per crop AUCs included), `run.log`. 156 windows of 640 px on a 320 px stride; 24 pass the supervision rule.

## R1: one crop's bootstrap interval does not describe the segment (problem declared by the rule)

| Reader | full region AUC [CI] | repo crop AUC [CI] | crop AUC range | between crop SD | share of crops in repo CI | mean coverage |
| --- | --- | --- | --- | --- | --- | --- |
| TEAM | 0.9714 [0.961, 0.978] | 0.9695 [0.949, 0.985] | 0.898 to 0.995 | 0.022 | 0.625 | **0.543** |
| BAVG | 0.5242 [0.484, 0.567] | 0.4928 [0.416, 0.562] | 0.417 to 0.626 | 0.053 | 0.708 | **0.797** |
| B1 | 0.5073 | 0.5544 | 0.379 to 0.759 | 0.088 | 0.583 | 0.614 |
| B2 | 0.4914 | 0.4517 | 0.357 to 0.613 | 0.065 | 0.625 | 0.592 |
| B3 | 0.5191 | 0.4932 | 0.469 to 0.593 | 0.033 | 0.792 | 0.819 |
| B4 | 0.5327 | 0.4647 | 0.423 to 0.603 | 0.046 | 0.500 | 0.716 |

Mean coverage below 0.80 for TEAM (0.543) and BAVG (0.797), so the preregistered rule declares a problem: a 95 % block-bootstrap interval from one 640 px crop contains on average only 54 % (TEAM) of the AUCs of other crops of the same tracing. The bootstrap resamples pixels inside the crop; it does not model where the crop was put. A single crop AUC with its interval should not be read as a segment level number. Limits: one segment, 24 overlapping crops (not independent), and the brightness readers sit near chance. The `median_boot_sd` field in `results.json` is NaN because of a script bug; the ratio was not used by any rule.

## R2: significant crop orderings did transfer (null for the problem)

32 crop level orderings had intervals excluding 0 for the 2 pairs whose full region difference was significant (B2 vs BAVG, TEAM vs BAVG); 0 disagreed with the full region sign. Rule threshold 0.20: not met, null. Descriptive, not a rule: the best of the four depth windows on a crop matched the full region best (B4) on only 7 of 24 crops (0.292; B1 10, B2 4, B3 3, B4 7), and among pairs that were not significant overall, 18 of 59 crop level "significant" orderings had the opposite sign. So a best window chosen on one crop is often not the best within the same tracing, which is consistent with today's between-tracing flips being crop variation; it does not prove that. BAVG beat all four windows on 0 of 24 crops for these brightness readers (unlike today's ink_9um result; different readers).

## R3: descriptive

TEAM full region AUC 0.9714 [0.961, 0.978]. That is far above the ink_9um reports cited in `kit/auc.py`. These labels may have been made with the team's predictions in view; if so, this AUC would be inflated. That is untested, and no leakage claim is made.

## P1: downsampled proxy (pass)

| Pool | max Spearman shortfall | max abs AUC error | ordering agreement (pairs with full diff >= 0.01) | scoring time, 6 readers x 24 crops |
| --- | --- | --- | --- | --- |
| full res | | | | 17.67 s |
| 2 x 2 | Spearman >= 0.992 | 0.0044 | 1.000 | 3.91 s (4.5x) |
| 4 x 4 | Spearman >= 0.988 | 0.0189 | 1.000 | 0.99 s (17.8x) |

Both pass the fixed rule (Spearman >= 0.95, error <= 0.02, ordering >= 95 %). 4 x 4 is near the error limit for brightness (B2 0.0189). The times cover AUC scoring only, not inference; a proxy for inference needs a model run at lower resolution, which is untested.

## T1: whole segment crop scan tool (null on speed)

`kit/cropscan.py` matches `score_array` (max diff 1.0e-4, at the tolerance) but took 297 s against 17.7 s for the loop (0.06x) on a box with load average up to 20 from other jobs. The tile histogram design is slower at this crop count; it is kept as a correctness-checked helper, not claimed as a speedup.

Caching: building the readers from raw data took 592 s inside the run; reloading the saved `maps.npz` took 110 s wall (mostly system time under memory pressure). Box I/O was noisy, so no speedup figure is claimed for the cache.
