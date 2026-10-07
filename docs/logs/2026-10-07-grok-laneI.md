# Lane I: crop placement and a downsampled proxy (2026-10-07)

Rule preregistered in commit 2f8d7e7 (`docs/prereg/2026-10-07-grok-laneI.md`), pushed before any number was computed. Labels: Null and Model output only. No reading is claimed. Public PHerc0841 w00 only.

## Review status: R1/R2 unresolved; P1 descriptive on the measured cohort

The following tables are the original reported run and remain unchanged, together with its raw `results.json`, `run.log` and preregistration. This merge review inspected the code and records; it did not independently rerun the public maps. The original source head is `d0bc8d1af33d9b54e90d603b86f40e5c0d0b4786`.

The recorded `median_boot_sd` is NaN for every reader because at least one of its per-crop intervals was nonfinite. The same interval list was used in R1: comparisons against NaN evaluate false, so undefined intervals were counted as zero coverage. R2's `not (lo <= 0 <= hi)` also classifies a nonfinite interval as significant. Consequently the original R1 problem declaration and R2 null are not validated; the "median field only" caveat below understates the impact. The per-crop intervals and valid-draw counts were not saved, so the corrected decisions cannot be recovered from this archive. A separate, preregistered rerun must address undefined resamples and report eligible intervals and draws. Missing intervals must never count as either evidence of miscoverage or significant orderings.

Containment of other crops' AUCs is a spatial heterogeneity diagnostic, not nominal confidence-interval coverage: a within-crop interval targets that crop's population, while different crops have different populations. Overlapping crops and multiple pairwise comparisons add dependence. The displayed containment figures cannot calibrate a segment-level uncertainty or error rate.

P1's saved point-AUC comparisons and fixed threshold checks are separate descriptive observations on 24 overlapping crops from one segment, one team map and five brightness summaries. They do not validate a proxy for new readers, lower-resolution inference, held-out sheets or targets. Majority pooling changes the label population and excludes partially supervised pooled pixels. The reported timing ratios come from one noisy run, with different work paths and memory pressure; they are observed ratios, not a general speed guarantee or a controlled performance benchmark. No reverse-depth reader controls were included, so this is not evidence of ink detection accuracy. R3 does not establish label leakage, and no independent prior-art novelty search is documented here.

The historical `run.py` is guarded against accidental prospective use. A deliberate unvalidated replay requires `SCROLLS_REPLAY_HISTORICAL_LANEI=1`; it still contains the old analysis and is not a corrected experiment. The original source remains available at the head named above. New crop-scan calls use the tested helper's explicit input domain and memory bound described below.

That runner also accepts a cache without validating its source hashes and selects the first globbed team TIFF when several exist. A stale cache or a different file can therefore change the experiment silently. The 4x4 team-map reduction and subsequent label-grid indexing are exploratory coordinate assumptions without a full registration/provenance receipt. A prospective runner must require an explicit map, verify grid metadata and freeze hashes of labels, masks, maps, cache and reader settings before computing. The archival gate does not repair these historical limitations.

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

32 crop level orderings had intervals excluding 0 for the 2 pairs whose full region difference was significant (B2 vs BAVG, TEAM vs BAVG); 0 disagreed with the full region sign. Rule threshold 0.20: not met, null. Descriptive, not a rule: the best of the four depth windows on a crop matched the full region best (B4) on only 7 of 24 crops (0.292; B1 10, B2 4, B3 3, B4 7), and among pairs that were not significant overall, 17 of 59 crop level "significant" orderings had the opposite sign. So a best window chosen on one crop is often not the best within the same tracing, which is consistent with today's between-tracing flips being crop variation; it does not prove that. BAVG beat all four windows on 0 of 24 crops for these brightness readers (unlike today's ink_9um result; different readers).

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

Prospective helper contract after review: `scan` requires 2D uint8/uint16 predictions or normalized finite floats in [0, 1], boolean labels/masks, valid integer grid parameters and bounded finite coverage fractions. At 65536 bins it matches `score_array` on that domain; uint8 retains all 256 levels with at least 256 bins. Coarser bins create data-dependent ties and need separate error validation. Arbitrary unnormalized float maps are refused because per-crop quantization can change with the crop maximum. Excessive estimated temporary-array work is refused before histogram allocation (default 2 GiB, configurable with `max_work_bytes`; caller inputs and allocator overhead are outside that estimate). This does not make the original 4096-bin historical timing a production speed result.

Caching: building the readers from raw data took 592 s inside the run; reloading the saved `maps.npz` took 110 s wall (mostly system time under memory pressure). Box I/O was noisy, so no speedup figure is claimed for the cache.
