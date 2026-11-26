# Preregistration: null calibration of the Sim Realism Standard's pass bar (26 Nov 2026)

Written and committed before the calibration runs. Synthetic tiles only: no scan, no labels, no held-out data.

## Why

The Sim Realism Standard ([SRS-1](../standards/sim-realism.md)) keeps the fixed pass rule of
[`kit.simcritic.verdict`](../tools/simcritic.md): a simulated set passes when its worst critic AUC is at most the
real-against-real control's worst AUC plus 0.05, and at most 0.60. The public reference (six PHerc0343P slices, about
105 windows) gives only three slices to each side of the control. With so few groups the AUC of a perfect simulator
may sit more than 0.05 from the control by chance, so the bar alone could fail a perfect simulator or pass a
flawed one. This calibration measures that before the standard states its sample-size rule.

## Design

- Instrument: `kit.simcritic.critic_auc` with the `feat` critic only (the CNN critics are too slow for hundreds of
  replicates on CPU), 3 grouped folds, seeds 0 and 1, the mean over seeds, exactly as `judge` does.
- Stand-in real slices: G groups, each 4 `kit.hardcases` tiles of 256 px from one seed (seeds 4611101 + g), so 16
  windows of 128 px per group. G is 6, 12 or 24.
- Perfect simulator: 480 tiles of seed 4612001 from the same generator and recipe; each replicate draws 240 of them
  without replacement (960 windows), as the standard's minimum set.
- Replicate r: the G groups are split at random (seed r) into halves A and B; the control is A against B; the set is
  B against the drawn simulated tiles; `kit.simcritic.verdict` gives PASS or FAIL. Replicates: 200 per G.
- Shifted simulators (power, reported only): the same drawn tiles blurred with a Gaussian of sigma 0.5 and of
  sigma 0.8 before windowing; 100 replicates per G and sigma.
- Seeds 4611101 to 4611124 and 4612001 are spent for this calibration once it runs.

## Readout (fixed now)

For each G: the null false-FAIL rate f(G) (share of perfect-simulator replicates that FAIL), and D99(G), the 99th
percentile of `gap_to_bar` over the null replicates.

1. A reference with G groups is **admitted** when f(G) is at most 0.10. The standard's minimum reference size is the
   smallest admitted G among 6, 12 and 24; if none is admitted, no reference size is admitted by this calibration and
   the standard says so.
2. On a reference that is not admitted, a FAIL counts only when `gap_to_bar` exceeds D99(G) of the nearest G at or
   above the reference's group count (6 when it has fewer than 6 groups, which the scorer refuses anyway); any other
   result, PASS included, is INCONCLUSIVE.
3. Power: the PASS rate of each shifted simulator per G, reported with no decision attached.

The numbers, the decision and every replicate's AUCs go to `docs/evidence/srs1-calibration-1126/`. A crash or a run
cut short is a technical break, disclosed; the calibration is then rerun on the same seeds with no change to this
rule.

Limits, stated now: the stand-in groups are tiles of one seed, not slices of a scan, so their within-group
correlation differs from real CT; the CNN critics are left out, and the worst of three critics spreads wider than
the feature critic alone. The admitted size is therefore a floor, not a guarantee.

## Prior records

The 25 Nov 2026 judgement on PHerc0343P (control 0.473, all seven sets 0.971 to 1.000, [tool page](../tools/simcritic.md#results))
used the same verdict rule; its gaps to the bar (+0.448 to +0.477) are far outside any null spread this calibration
could find, so its FAIL verdicts do not depend on this calibration. No earlier null calibration of this bar exists in
this repository (searched `docs/` for "simcritic" and "null calibration", 26 Nov 2026).
