# Center line coverage polish against villa, 22 October 2026

The one run of the coverage polish test, rule version 1 (frozen rule sha256 `71d431b3459f69c3989899a3f4d09647132714119ce6cb0537109ebb9d2fb5c8`), the rule that `python -m kit axispolish` runs ([tool page](../../tools/axispolish.md)). The rule was fixed before the run; the polish never read a scored slice.

`summary.json` holds every number of the verdict. Labels follow [`../../NOVELTY.md`](../../NOVELTY.md).

## What was measured

Ten scans that none of the methods had been tuned on, 24 slices each (240 slices). At each slice, winding coverage (the summed angle of villa's traced sheet around a point, in wraps; [`kit windcheck`](../../tools/windcheck.md)) was taken at five points:

| Name | Point |
| --- | --- |
| P | Center Finder line after the coverage polish |
| L | Center Finder line before the polish |
| V | villa `vc_gen_umbilicus`, median of 20 runs per slice |
| C | scan center (control) |
| ring | points on a 3 mm ring round V (control) |

Gain is coverage minus V's coverage, in wraps.

## Result (Measurement against villa's model-predicted sheet traces)

Verdict **BETTER**: P sat deeper in villa's traced sheet than V, pooled median gain **+0.084 wraps**, 95% interval **+0.028 to +0.169**, deeper on **8 of 10** scans. Before the polish, L was WORSE: -0.330 wraps, interval -0.651 to -0.142, 10 of 10 lost.

| Scan | P, polished | L, before | C, scan center | 3 mm ring |
| --- | --- | --- | --- | --- |
| PHerc0175A | +0.124 | -0.079 | -9.48 | -3.44 |
| PHerc0175B | +0.003 | -0.363 | -8.69 | -2.07 |
| PHerc0306B | +0.118 | -0.109 | -5.00 | -3.01 |
| PHerc0483A | +0.125 | -1.043 | -7.48 | -2.74 |
| PHerc0483B | +0.039 | -0.567 | -7.53 | -2.53 |
| PHerc0490A | +0.075 | -1.073 | -8.01 | -1.74 |
| PHerc0490B | -0.043 | -1.627 | -2.36 | -1.70 |
| PHerc0814 | -0.086 | -0.257 | -2.76 | -2.64 |
| PHerc0841 | +0.063 | -0.058 | -11.51 | -3.88 |
| PHerc0846B | +0.648 | -0.035 | -0.58 | -1.14 |

Controls: the scan center pooled -5.57 wraps and the 3 mm ring -2.40 (interval -2.94 to -1.82), so the check sees a 3 mm miss. The self-check passed (coverage equal to `kit.windcheck` in numpy and numba). Nothing was excluded. Median distances: P moved 1.55 mm from L; P sat 1.13 mm from V; L sat 1.55 mm from V.

## What it does not say (Interpretation)

- Coverage reads villa's own surface model, which `vc_gen_umbilicus` reads too. It is not a distance to the true axis or to any person's center line.
- The gain is small, about a twelfth of a wrap at the median. PHerc0846B's +0.65 is the largest; the pooled median and the 8 of 10 count do not rest on it alone, but that was not tested separately.
- The polish moves the line toward villa's (1.13 mm apart after, 1.55 before). People's hand-made lines are never polished.

## Run

Claude cloud container, 4 cores, CPU only, 0 USD, 22 Oct 2026 about 21:23 to 22:30 UTC, 1,200 normal grids from the open-data bucket. villa built from `ScrollPrize/villa` `e2254eb` with g++ 14, binary sha256 `44c8bc1fefabbd409a7a70a4e5b8cc1afa30be16a59c4be04ac8189da2e6c579`. The per-slice `result.json` (sha256 in `summary.json`) is kept with the run outside git.
