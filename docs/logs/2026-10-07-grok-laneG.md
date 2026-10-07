# Lane G: new model-free ink signals (2026-10-07)

Rule preregistered in commit 8578f69 (`docs/prereg/2026-10-07-grok-laneG.md`) before any run; script in c7f05c4. Labels: Null and Model output only. No reading is claimed.

## Commands (user's Mac, CPU, ~/scrolls-work/laneG, about 50 s, no running job disturbed)

```
tar xzf ../laneG.tgz && cp scripts/experiments/2026-10-07-laneG/*.{py,sh} .
bash run.sh      # signals.py, then python -m kit auc MAP --control MAP_shuf --crop ... --inner 64 --bootstrap 300 --seed 20261007 --json per signal and segment
```

Results: `scripts/experiments/2026-10-07-laneG/results.json` (features plus every `kit auc` output), log `signals.log`.

## Pixel signals (direction fixed on w045, applied to PHerc0841 w00; AUC, bootstrap 95 % CI, depth-shuffled, max of 8 rolled nulls)

| Signal | w045 AUC [CI] | shuf | roll max | w00 AUC [CI] | shuf | roll max | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| brightness (baseline) | 0.536 [0.438, 0.639] | 0.473 | 0.557 | 0.465 [0.406, 0.530] | 0.477 | 0.631 | baseline |
| dog_band (stroke-scale band energy, lower=ink) | 0.543 [0.467, 0.646] | 0.535 | 0.498 | 0.416 [0.347, 0.487] | 0.472 | 0.533 | null |
| noise_resid (depth residual noise) | 0.515 [0.412, 0.629] | 0.551 | 0.616 | 0.493 [0.415, 0.555] | 0.508 | 0.617 | null |
| crackle (fiber crack density, lower=ink) | 0.567 [0.419, 0.708] | 0.575 | 0.603 | 0.385 [0.323, 0.437] | 0.406 | 0.524 | null |
| relief (surface micro-relief, lower=ink) | 0.532 [0.486, 0.577] | 0.500 | 0.545 | 0.501 [0.444, 0.548] | 0.507 | 0.574 | null |
| phase_sym (phase symmetry 12 to 48 px) | 0.501 [0.500, 0.503] | 0.501 | 0.501 | 0.498 [0.493, 0.501] | 0.500 | 0.503 | null |

No signal clears 0.55 lower bound on either segment; every point AUC is within 0.03 of, or below, a control. Post hoc observation, not a result: crackle and dog_band flip direction between the scrolls. Flipping a signal also flips every null: the maximum becomes one minus the original minimum. On w00, crackle would have AUC 0.6149 against a flipped rolled maximum of 0.6114 (only +0.0035); dog_band would have AUC 0.5842 against 0.5198. Selecting the sign using w00 labels makes these exploratory calibration observations, not held-out results. A transfer claim requires a fresh rule and a separate evaluation surface; ag405 is a separate surface of the same scroll, not a third scroll.

## Text-level cue: line period (row autocorrelation of dog_band row means)

| Segment | label period px (peak) | signal period px (peak) | shuffled (peak) |
| --- | --- | --- | --- |
| w045 | 187 (-0.26, no positive peak) | 45 (0.21) | 62 (0.18) |
| 0841-w00 | 115 (0.26) | 117 (0.43) | 78 (0.22) |

Verdict: exploratory and inconclusive. The historical implementation selected the strongest local autocorrelation peak, including negative peaks, although the preregistration specified the first peak. Thus the saved w00 match within 2 % and peak advantage 0.21 do not establish a pass of that fixed rule. w045 has no positive supported label peak in this readout. The saved results and log remain unchanged. Future code selects the first positive local peak and requires at least three observed periods; its output records that method. No corrected data run has been performed. Next: use whole-segment windows and an orientation-agnostic 2D autocorrelation under a fresh rule.

## Merge review qualification

w045 labels choose each pixel signal's sign, so its AUC and bootstrap intervals are calibration descriptions. Only the unchanged sign on w00 is a transfer test; the two crops are not two independent validation samples. These nulls concern the implemented features and fixed crops, not the absence of model-free ink information in CT generally. The fresh-run wrapper now creates its output directory before opening the tee log.
