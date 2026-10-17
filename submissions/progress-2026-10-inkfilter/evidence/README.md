# Confirmation evidence: fixed filters, 17 October 2026

Claim label: Model output. AUC measures separation of published labelled ink and background; it is not a reading or proof of text.

This package preserves the frozen `face-mix` numerical recipe. Development used 56 windows, two from each of 28 labelled segments on seven scrolls. Confirmation used 56 additional, nonoverlapping windows from those same segments. Development comparisons used leave-one-scroll-out selection; the final recipe was selected using all seven development scrolls and frozen before confirmation. Confirmation therefore tests new windows, not seven wholly unseen scrolls.

| Method | Mean AUC over seven scrolls | Filter minus method, 95% interval | Scrolls where filter wins |
| --- | --- | --- | --- |
| Face mix | 0.7357 | | |
| Alpha compositing | 0.7042 | +0.0315 [0.0221,0.0404] | 4/7 |
| Alpha plus high-pass | 0.7077 | +0.0280 [0.0217,0.0340] | 6/7 |
| Maximum of central layers | 0.6367 | +0.0990 [0.0836,0.1127] | 7/7 |
| CLAHE of central-layer mean | 0.5271 | +0.2086 [0.1950,0.2221] | 7/7 |
| VTID baseline implementation | 0.6137 | +0.1220 [0.1072,0.1359] | 7/7 |
| Reversed-depth face mix | 0.6276 | +0.1081 [0.0905,0.1254] | 6/7 |

These results support a mean advantage over the particular frozen fixed-filter baselines. They do not establish the best available tool, superiority over trained readers, or future prize eligibility. No trained ink model was compared on these windows. Among the seven scrolls, PHerc0139, PHerc0841 and PHerc1667 score slightly higher under alpha alone. On PHerc0814, forward face mix is 0.6858 and reversed is 0.8544. The reverse result limits any general claim that the chosen high-z face is the ink side.

## Data and scoring

[`confirmation-windows.json`](confirmation-windows.json) contains only published segment identifiers, bucket-relative paths, level, crop coordinates and labelled-pixel counts. Prefix `sv` and `labels` paths with `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/`. These are public labelled training segments, not an unpublished target-scroll readout. The windows are 1024 x 1024 at level 1, approximately 4.8 um per pixel. They were chosen by balanced labelled ink/background coverage, without selecting on CT appearance. The list is a data specification; availability of every external chunk was not rechecked for this release candidate.

The saved scoring implementation excluded a 32-pixel edge on the original 1024-pixel grid, selected supervised rendered pixels, and pooled maps 2x to 512 x 512. Pooled labels use a strict majority; all four source supervision/rendered pixels must be usable. AUC is averaged over windows within a segment, segments within a scroll, then equally over seven scrolls. Paired 95% percentile intervals use 2,000 bootstrap draws, resampling segments within each scroll with seed 0. Three scrolls have one segment each and contribute no within-scroll bootstrap variation. The intervals do not measure uncertainty over new scroll populations.

[`frozen-recipe.json`](frozen-recipe.json) records the filter and baseline selections. Alpha uses 41 central layers in front-to-back order, intensity window [0.45,0.60] of uint8 full scale, opacity 1. Baseline names `s24b96` mean sigma 24 smoothing after subtracting a sigma 96 background on the pooled grid; `b0` means no subtraction. CLAHE uses scikit-image clip limit 0.01 on the mean of 21 central layers. The maximum baseline uses the same 21-layer band. The VTID baseline uses the block autocorrelation feature, surface-weighted maximum and MRF smoothing reimplemented in the original study, following [VTID, Zenodo record 20766169](https://zenodo.org/records/20766169), whose software/data license is CC BY-NC 4.0. It is a study implementation of that baseline, not an assertion of bitwise equivalence to every VTID release or setting.

## What can be reproduced from this package

[`window-scores.json`](window-scores.json) contains the 56 saved scalar score records, with runtimes removed. [`summarize.py`](summarize.py) recomputes every mean, interval and win count in [`confirmation-summary.json`](confirmation-summary.json) and fails on a mismatch. It uses NumPy only and downloads nothing:

```bash
python evidence/summarize.py
```

The numerical filter and synthetic tests are runnable independently of the source repository. A complete raw-data reproduction of the original baseline bank and window-selection study is not included in this first package. Thus the aggregate check validates arithmetic over recorded results, not the provenance of every pixel score. The window list and frozen definitions make that remaining replication scope explicit. No new confirmation data were scored while preparing this package, and no parameters changed in response to these results.
