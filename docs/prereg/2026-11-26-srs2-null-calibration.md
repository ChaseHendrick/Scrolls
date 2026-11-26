# Preregistration: null calibration of the draft SRS-2 permutation pass rule (26 Nov 2026)

Written and committed before the frozen calibration runs. Synthetic `kit.hardcases` tiles only: no scan, no labels,
no held-out data. Freeze id `srs2-null-calibration-1126`.

## Why

SRS-1's null calibration ([evidence](../evidence/srs1-calibration-1126/README.md)) found that its fixed bar (worst
critic AUC at most one real-against-real control draw plus 0.05) fails a perfect simulator 0.595, 0.485 and 0.285
of the time at 6, 12 and 24 groups, so under SRS-1 a PASS is never a verdict. Its README named a permutation test as
the natural rule for an SRS-2 (Untested idea). [`kit.simperm`](../tools/simperm.md) implements one: whole units
(a reference slice, or a run of simulated tiles of the same window count) are dealt to 3 folds, each SRS-1 critic
scores fold k with a model trained real against simulated on fold k + 1 only (the ring design, chosen on development
seeds, section "Development runs"), units are ranked by mean held-out score within each fold, and the max over
critics of the standardized rank sum is compared with 9,999 within-fold relabelings. FAIL when p is at most 0.05.
This calibration asks whether that rule's false FAIL rate on a perfect simulator stays near its alpha, and how often
it catches blurred simulators, before any reference size is admitted for a PASS.

## Design

- Instrument: `kit.simperm._feat_test` with `kit.simperm.DESIGN = "ring"`, the `feat` critic only (as in SRS-1's calibration; the CNN critics are too
  slow for thousands of replicates on CPU), 3 folds, the rule's permutation test with 9,999 relabelings.
- Units: a pool of 400 units, unit u being 4 `kit.hardcases` tiles of 256 px from seed 4621001 + u (16 windows of
  128 px). Within a unit the tiles share their seed's recipe draw, so a unit has a group effect, as a slice does.
- Perfect simulator: replicate r for (G, K) draws G + K distinct pool units at random (`numpy` generator seeded
  `[G, K, r, 1127]`); the first G are the real units, the other K the simulated units. Under this draw the units are
  exchangeable, so the rule should fail at most about 5 percent of replicates.
- Cells: G in 6, 12 and 24; K equal to G, and K = 60 (SRS-1's 240-tile minimum set cut into 4-tile units).
  200 replicates per cell.
- SRS-1 on the same draws: `kit.simscore.verdict` on a control (the first half of the real units against the second)
  and a set (the second half against the simulated units), the feat critic, seeds 0 and 1. This reproduces SRS-1's
  known flaw on these units and is a control of the setup.
- Power (shifted simulators): the same draws with the simulated units' tiles blurred (Gaussian sigma 0.5 and 0.8)
  before windowing; 100 replicates per cell and sigma.
- One-seed simulator (report only): K units cut from 480 tiles of the single seed 4622001, SRS-1's kind of perfect
  simulator, which lacks the between-unit variation of the real units; 100 replicates per cell.
- Seeds 4621001 to 4621400 and 4622001 are spent for this calibration once it runs. Development used other seeds
  only (section "Development runs").

## Readout (fixed now)

The frozen run is `python -m kit run local --device x86-cpu --rate 0 srs2-null-calibration-1126 -- python3 -m
kit.simperm calibrate --workers 4 --freeze srs2-null-calibration-1126 --out
docs/evidence/srs2-calibration-1126/record.json`, with every other option at its default. `kit.simperm.summarize`
writes the `metrics` the rule reads.

```readout-rule
{
 "schema": "kit-readout-rule/1",
 "template": "bar-test",
 "freeze": "srs2-null-calibration-1126",
 "record": "docs/evidence/srs2-calibration-1126/record.json",
 "label": "Model output on synthetic kit.hardcases units under a frozen rule; no scan, no labels",
 "valid_if": [
  {"key": "metrics.srs1_false_fail_g6_max", "op": ">=", "value": 0.15, "control": true,
   "why": "SRS-1's bar on the same G 6 draws must reproduce its known false FAIL (0.595 on 26 Nov); if not, these units are not comparable"},
  {"key": "metrics.blur08_power_gmax", "op": ">=", "value": 0.5, "control": true,
   "why": "at G 24, K 24 the rule must catch the sigma 0.8 blur at least half the time, or the pipeline cannot fail"}
 ],
 "pass_if": [
  {"key": "metrics.false_fail_max", "op": "<=", "value": 0.08,
   "why": "alpha 0.05 plus Monte Carlo slack (binomial sd 0.015 at 200 replicates): in every cell a perfect simulator fails at most 8 percent of the time"}
 ]
}
```

Decision, fixed now:

1. PASS: the permutation rule holds its false FAIL rate in every cell. SRS-2's `ADMIT_GROUPS` becomes the smallest G
   whose cells all have false FAIL at most 0.08 and whose K = G cell catches the sigma 0.8 blur at least 80 percent
   of the time (`metrics.admit_groups`); `kit.simperm.ADMIT_GROUPS` is set to it in a reviewed change, with a test
   pinning it to the record. FAIL: SRS-2 stays a draft, no reference is admitted, and the record goes to the lessons
   list; the rule is not tuned on these seeds. VOID (a control fails): fixed and rerun as a new disclosed freeze.
2. Power and the one-seed simulator are reported with no further decision.
3. A crash or a run cut short is a technical break, disclosed; rerun on the same seeds with no change to this rule.

Publish only the summary per cell (rates, quartiles, a SHA-256 of the per-replicate p-values); the full replicate
list is regenerable with the command above.

## Limits, stated before the result

- Stand-in units are tiles of one hardcases seed, not slices of a scan; their within-unit correlation differs from
  real CT. Exchangeability holds here by construction; on a real reference it holds only to the degree a simulator
  is a draw of the same process, which is the question SRS-2 asks.
- In the ring, fold k's labels train fold k - 1's model, so the within-fold relabeling is not exact by proof; this
  calibration is the evidence that its error is small, for the feat critic only. The CNN critics and the max
  over three critics are untested here.
- The rule tests separability at alpha 0.05; a PASS is the absence of a detected difference on a reference where the
  run's own planted blur and noise were caught, never proof that a set is real.

## Development runs (before the freeze)

All on development seeds only (pool units 4629001 to 4629150, one-seed sim 4629901, replicate seeds `[G, K, r, 1127]`
and `[G, K, r, 9001]`), feat critic, 26 Nov 2026, 4-core cloud container. None of the preregistered seeds were read.
The 150-unit development pool is reused heavily across replicates (up to 84 of 150 units per draw), so these rates
are correlated and coarser than their count suggests.

1. A 20-replicate smoke at G 6 (60 units): pipeline check only.
2. Cross-fitting (each fold scored by a model trained on the other two), 200 replicates per cell, 1,999
   relabelings: false FAIL 0.075, 0.075, 0.07, 0.065, 0.065 and 0.09 (G 6 K 6, G 6 K 60, G 12 K 12, G 12 K 60,
   G 24 K 24, G 24 K 60); SRS-1 on the same draws 0.485, 0.42, 0.345, 0.24, 0.21, 0.2.
3. Four fold designs on 400 null replicates per cell (999 relabelings; G 6 K 6, G 6 K 60, G 12 K 12, G 24 K 24):
   cross 0.060, 0.085, 0.092, 0.102; ring (fold k scored by a model trained on fold k + 1 only) 0.030, 0.068, 0.062,
   0.052; holdout (only fold 1 tested, model on folds 2 and 3; exact) 0.000, 0.040, 0.025, 0.055; half (2 folds,
   one tested; exact) 0.028, 0.065, 0.050, 0.028. Blur sigma 0.5 caught (100 replicates): cross 0.52, 0.95, 0.94,
   1.00; ring 0.30, 0.95, 0.90, 1.00; holdout 0.00, 0.77, 0.58, 0.95; half 0.17, 0.84, 0.78, 0.98.
   Interpretation: cross-fitting inflates the false FAIL rate, growing with G, because every pair of folds enters
   two folds' tests; the exact designs reach 0.065 in the G 6 K 60 cell too, so about 0.065 there is this pool's
   noise. The ring keeps most of the cross design's power.
4. Chosen before the freeze: the ring design (`kit.simperm.DESIGN = "ring"`). The calibration pipeline on it, 200
   replicates per cell: false FAIL 0.015, 0.05, 0.05, 0.06, 0.025, 0.055; SRS-1 0.485, 0.42, 0.345, 0.24, 0.21, 0.2;
   blur 0.8 caught 1.0 in every cell, blur 0.5 0.35, 0.92, 0.95, 1.0, 1.0, 1.0; one-seed simulator FAIL 0.04 to
   0.08. Development `metrics`: false_fail_max 0.06, admit_groups 6. 575 s wall (other jobs shared the CPU).

Arms tried before the freeze: four fold designs (cross, ring, holdout, half); one chosen. The bar (0.08) and alpha
(0.05) were written before any development run and were not changed.

## Prior records

SRS-1's null calibration (26 Nov 2026, [evidence](../evidence/srs1-calibration-1126/README.md), seeds 4611101 to
4611124 and 4612001) measured the fixed bar this rule replaces; none of its seeds are reused. The 25 Nov 2026
PHerc0343P judgement ([tool page](../tools/simcritic.md#results)) is not rescored here. No earlier permutation rule
for the realism judge exists in this repository (searched `docs/` and `kit/` for "permutation" with "simcritic",
26 Nov 2026).
