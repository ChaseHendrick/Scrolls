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

No signal clears 0.55 lower bound on either segment; every point AUC is within 0.03 of, or below, a control. Post hoc observation, not a result: crackle and dog_band flip direction between the scrolls (w00 reversed would be 0.615 and 0.584, above its rolled max of 0.52 to 0.53). That fits a scroll-specific texture difference, not a general ink cue; testing it needs a fresh preregistration and a third segment (for example ag405).

## Text-level cue: line period (row autocorrelation of dog_band row means)

| Segment | label period px (peak) | signal period px (peak) | shuffled (peak) |
| --- | --- | --- | --- |
| w045 | 187 (-0.26, no positive peak) | 45 (0.21) | 62 (0.18) |
| 0841-w00 | 115 (0.26) | 117 (0.43) | 78 (0.22) |

Verdict: inconclusive. On w00 the period matches labels within 2 % and beats the shuffled control by 0.21, but w045's 640 px crop has no label periodicity (fewer than 3 lines along rows), so the both-segments rule cannot be met. Next: rerun on whole-segment windows (several line periods) with an orientation-agnostic 2D autocorrelation; preregister first.
