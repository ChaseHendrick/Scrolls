# Ink reader leaderboard

<!-- generated from docs/results.json by python -m kit leaderboard render; edit results.json, not this file -->

Every released ink reader on the labeled test segments, with its controls beside it. Model output, not readings.
Numbers come only from [`results.json`](results.json); this page is written from it, and
`python -m kit leaderboard check` (run by the tests) fails when the two disagree.

How to read it:

- **Forward**: pixel AUC of the map with the depth layers in their stored order, against the segment's 20260918 human
  labels inside its supervision mask (`kit auc`).
- **Reversed**: the same reader on the layers in reverse depth order, the control. It should sit near or below 0.5,
  and well below Forward. **Gap** is Forward minus Reversed; a gap under 0.10 is marked "weak control"
  (the threshold `kit gate` uses).
- **Shuffled**: a map made with the depth layers shuffled, a second control, where one was run. One shuffle is one
  random draw, so it moves between runs.
- **Held out**: whether the reader's training data left this segment out, from `held_out_by_reader` in
  results.json (reasons and sources in its `held_out`). Rows marked **NOT held out** or **possibly NOT held out** are
  not a fair test of that reader.
- **Window**: `whole` is the whole segment; `crop` is the 640 px window where the labels mark the most ink, chosen
  with the labels, so crop scores (the reversed control's included) run higher than whole-map ones. `inner 64` leaves
  a 64 px edge out. Only rows with the same window, edge and render compare directly, so each table splits by window.
- Rows are sorted by Forward within a window. A higher Forward is not a ranking by itself: check the controls and the
  held-out column first. `kit gate` applies the Phase 0 rule to the crop rows.

Written from results.json of 2026-10-16.

## Measured in this repository

### PHerc0841 w00

Segment `20260220213127-w00`, 9.366 um surface volume, crop `[2624, 3264, 2688, 3328]` (y0, y1, x0, x1).

Window: whole

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| ink_9um seed42 | held out | 0.7479 | 0.5010 | +0.2469 |  | full | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed42 | held out | 0.7479 | 0.5012 | +0.2467 | 0.4851 | AutoPipeline render, from the released scan and the published segment | cuda | [github.com/ChaseHendrick/Scrolls/blob/faada83287d39bbd4c7...](https://github.com/ChaseHendrick/Scrolls/blob/faada83287d39bbd4c7fd88c7ab0e75f3f1ff284/submissions/progress-2026-10/autopipeline/README.md) | 2026-10-09 |

Window: crop, inner 0

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| d9v2 | held out | 0.8755 | 0.5573 | +0.3182 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed42 | held out | 0.7704 | 0.4958 | +0.2746 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed42 | held out | 0.7696 | 0.5143 | +0.2553 |  | full | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |

Window: crop, inner 64

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| Reader v2 | held out | 0.9269 | 0.7294 | +0.1975 | 0.5681 | bare-crop | cpu | [`scripts/experiments/2026-10-07-cloud/tricks/results.json`](../scripts/experiments/2026-10-07-cloud/tricks/results.json) | 2026-10-07 |
| d9v2 | held out | 0.8994 | 0.5855 | +0.3139 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed42 | held out | 0.8061 | 0.5361 | +0.2700 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |

Not scored here yet: `v8in-1447`, `Hecate`, `v8in`.

### PHerc0841 auto-grown 896 (ag896)

Segment `20260220214732-auto_grown_20260220144552896`, 9.366 um surface volume, crop `[2496, 3136, 1600, 2240]` (y0, y1, x0, x1).

Window: whole

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| ink_9um seed42 | held out | 0.7195 | 0.5697 | +0.1498 |  | full | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |

Window: crop, inner 0

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| d9v2 | held out | 0.8049 | 0.5129 | +0.2920 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed42 | held out | 0.6604 | 0.5575 | +0.1029 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed42 | held out | 0.6553 | 0.5397 | +0.1156 |  | full | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |

Window: crop, inner 64

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| d9v2 | held out | 0.8230 | 0.5323 | +0.2907 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| Reader v2 | held out | 0.7972 | 0.5988 | +0.1984 | 0.6170 | bare-crop | cpu | [`scripts/experiments/2026-10-07-cloud/tricks/results.json`](../scripts/experiments/2026-10-07-cloud/tricks/results.json) | 2026-10-07 |
| ink_9um seed42 | held out | 0.6594 | 0.5579 | +0.1015 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |

Not scored here yet: `v8in-1447`, `Hecate`, `v8in`.

### PHerc0841 auto-grown 405 (ag405)

Segment `20260221022814-auto_grown_20260220174252405`, 9.366 um surface volume, crop `[1024, 1664, 2496, 3136]` (y0, y1, x0, x1).

Window: whole

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| ink_9um seed42 | held out | 0.7508 | 0.6012 | +0.1496 |  | full | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |

Window: crop, inner 0

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| d9v2 | held out | 0.8308 | 0.5883 | +0.2425 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed42 | held out | 0.8212 | 0.6711 | +0.1501 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed42 | held out | 0.7930 | 0.6527 | +0.1403 |  | full | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |

Window: crop, inner 64

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| d9v2 | held out | 0.8319 | 0.6572 | +0.1747 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed42 | held out | 0.7838 | 0.6423 | +0.1415 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |

Not scored here yet: `v8in-1447`, `Reader v2`, `Hecate`, `v8in`.

### PHerc0139 w045

Segment `20260126000000-w045_2026012619`, 9.362 um surface volume, crop `[3840, 4480, 2560, 3200]` (y0, y1, x0, x1).

Window: whole

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| ink_9um seed43 | **NOT held out** | 0.8866 | 0.5024 | +0.3842 |  | full | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed42 | **NOT held out** | 0.8722 | 0.4425 | +0.4297 |  | full | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |

Window: crop, inner 0

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| ink_9um seed42 | **NOT held out** | 0.9136 | 0.3704 | +0.5432 |  | full | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed42 | **NOT held out** | 0.9136 | 0.3704 | +0.5432 |  | full | mps (M1 Pro, villa PR #1865 6723ad158) | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed43 | **NOT held out** | 0.9098 | 0.4347 | +0.4751 |  | full | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed43 | **NOT held out** | 0.9098 | 0.4347 | +0.4751 |  | full | mps (M1 Pro, villa PR #1865 6723ad158) | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| ink_9um seed42 | **NOT held out** | 0.9074 | 0.3835 | +0.5239 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| d9v2 | **NOT held out** | 0.8600 | 0.4004 | +0.4596 |  | bare-crop | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |
| v8in d89166b | held out | 0.7382 | 0.3269 | +0.4113 |  | bare-crop | mps (M1 Pro) | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |

Window: crop, inner 64

| Reader | Held out | Forward | Reversed | Gap | Shuffled | Map from | Device | Source | Date |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| ink_9um seed42 | **NOT held out** | 0.9199 |  |  |  | bare-crop and full (identical) | cpu | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | 2026-10-07 |

Not scored here yet: `Reader v2`, `Hecate`.

## Reported by others (Community report)

Each team's own crop, labels and settings, so these do not compare directly with the tables above or with each other.

| Reader | Test | Held out | Forward | Reversed | Gap | Source | Date | Note |
| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |
| v8in d89166b | PHerc0841 ag405, labels' bounding box, human labels | held out | 0.8100 | 0.5860 | +0.2240 | [github.com/Bullo27/v8in-12gb](https://github.com/Bullo27/v8in-12gb) | 2026-10-01 |  |
| v8in d89166b | PHerc0841 ag896, labels' bounding box, human labels | held out | 0.8070 | 0.6180 | +0.1890 | [github.com/Bullo27/v8in-12gb](https://github.com/Bullo27/v8in-12gb) | 2026-10-01 |  |
| v8in d89166b | PHerc0841 w00, labels' bounding box, human labels | held out | 0.8370 | 0.5620 | +0.2750 | [github.com/Bullo27/v8in-12gb](https://github.com/Bullo27/v8in-12gb) | 2026-10-01 |  |
| Hecate + Reader v2 mean | PHerc0841 whole, human labels | **NOT held out** | 0.8660 |  |  | [huggingface.co/domenicor046/reader-v2](https://huggingface.co/domenicor046/reader-v2) | not recorded | PHerc0841 is not held out from Hecate: its base model's committed trainer lists all three segments, although Hecate's own published split rule, applied to the published masks, makes them validation-only (see held_out.PHerc0841) |
| Hecate | PHerc0841 whole, human labels | **NOT held out** | 0.8550 |  |  | [huggingface.co/domenicor046/reader-v2](https://huggingface.co/domenicor046/reader-v2) | not recorded | PHerc0841 is not held out from Hecate: its base model's committed trainer lists all three segments, although Hecate's own published split rule, applied to the published masks, makes them validation-only (see held_out.PHerc0841) |
| Reader v2 | PHerc0841 whole, human labels | held out | 0.8240 |  |  | [huggingface.co/domenicor046/reader-v2](https://huggingface.co/domenicor046/reader-v2) | not recorded |  |
| ink_9um | PHerc0841 whole, human labels | held out | 0.7330 |  |  | [huggingface.co/domenicor046/reader-v2](https://huggingface.co/domenicor046/reader-v2) | not recorded |  |
| Reader v2 + d9v2 mean | PHerc0841, TAUIL held-out benchmark | held out | 0.8400 |  |  | [github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search) | not recorded |  |
| d9v2 | PHerc0841, TAUIL held-out benchmark | held out | 0.8280 |  |  | [github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search) | not recorded |  |
| Reader v2 | PHerc0841, TAUIL held-out benchmark | held out | 0.8260 |  |  | [github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search) | not recorded |  |
| ink_9um seed42 | PHerc0841, TAUIL held-out benchmark | held out | 0.7360 |  |  | [github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search) | not recorded |  |
