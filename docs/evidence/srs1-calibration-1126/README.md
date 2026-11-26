# SRS-1 null calibration (26 Nov 2026)

Run of the rule fixed in [`../../prereg/2026-11-26-srs1-null-calibration.md`](../../prereg/2026-11-26-srs1-null-calibration.md) (committed in `51e816f` before the run). Synthetic `kit.hardcases` tiles only. Model output.

- Command: `python -m kit run local --device x86-cpu --rate 0 srs1-calibration-1126 -- python3 -m kit.simscore calibrate --out docs/evidence/srs1-calibration-1126/calibration.json`
- Machine: 4-core cloud container, one core used; 290 s wall, 0.0052 kWh, no charge.
- Output: [`calibration.json`](calibration.json), SHA-256 `396c4a862eece1820e40e86bb8259fbdf819506d46f0384c1343d347aea182f7`, with every replicate's control AUC, set AUC, gap and verdict.
- Disclosed: a 3-replicate pipeline smoke (G 6, a 40-tile pool, 24 simulated tiles) ran on the same seeds a few minutes before the full run, after the rule was committed. It could not change the rule.

## Result

A perfect simulator (more tiles of the same generator) is scored against stand-in real slices with the fixed bar (control worst plus 0.05, at most 0.60), feature critic only:

| Groups (G) | False FAIL rate f(G) | D99 of gap to bar | Median gap | Control AUC sd | Set AUC sd | Admitted (f at most 0.10) |
| --- | --- | --- | --- | --- | --- | --- |
| 6 | 0.595 | 0.2454 | +0.024 | 0.105 | 0.106 | No |
| 12 | 0.485 | 0.2045 | -0.002 | 0.095 | 0.046 | No |
| 24 | 0.285 | 0.0788 | -0.033 | 0.056 | 0.036 | No |

Power (PASS rate of a shifted simulator, reported only): blur sigma 0.5 passes 0.09, 0.00 and 0.02 of the time at G 6, 12 and 24 (mean set AUC 0.73, 0.73, 0.69); blur sigma 0.8 never passes (mean set AUC 0.96 to 0.98).

## Decision (by the preregistered rule)

1. No reference size among 6, 12 and 24 is admitted: the bar fails a perfect simulator 29 to 60 percent of the time.
2. So under SRS-1 a PASS is never a verdict (INCONCLUSIVE), and a FAIL counts only when its gap to the bar exceeds D99 of the nearest calibrated G at or above the reference's group count: 0.2454 for R343-v1's 6 slices.
3. The 25 Nov 2026 sets on R343-v1 had gaps +0.448 to +0.477, all above 0.2454: they stay FAIL under SRS-1.

`kit.simscore.ADMIT_GROUPS` and `D99` hold these values; `tests/test_simscore.py` fails if they drift from this file.

## Reading (Interpretation)

The control's AUC spreads with sd 0.10 at 6 groups, twice the 0.05 margin, because each fold tests on a single slice per side. The margin is too narrow for any reference size tried, so a fixed margin over one control draw cannot certify realism at these sizes; it can only rule a set out when the gap is large. A bar taken from the null distribution itself (for example a permutation test of the set comparison against relabeled real groups) would be the natural rule for an SRS-2. That is an untested idea, not part of SRS-1.

Limits (stated in the preregistration): the stand-in groups are tiles of one seed, not slices of a scan; the CNN critics were left out, and the worst of three critics spreads wider. The spent seeds are 4611101 to 4611124 and 4612001.
