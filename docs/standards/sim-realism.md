# Sim Realism Standard, version 1 (SRS-1)

A fixed, public way to rate how real a set of simulated scroll CT tiles looks, so that synthetic data from any team is scored the same way. Draft, 26 November 2026. Reference scorer: [`kit.simscore`](../tools/simscore.md), built on the released judge [`kit.simcritic`](../tools/simcritic.md).

**In one line:** SRS-1 can rule a simulated set out (a FAIL beyond the calibrated noise), but at the reference sizes tested it cannot certify a set as realistic: a PASS is reported as INCONCLUSIVE. None of the seven sets scored so far is close: each fails by a wide margin.

Claim labels follow [`NOVELTY.md`](../NOVELTY.md). Every AUC on this page is **Model output**. A PASS under SRS-1 means that no SRS-1 critic told the set from that reference. It does not prove that the set is real, and it says nothing about ink or letters.

## Why a standard

Simulated CT comes with exact labels, so it is tempting training data, but a model trained on it carries over to real scans only as far as the tiles look like real CT. Realism claims are hard to compare today: each team picks its own real windows, its own classifier, its own split and its own threshold, and a random (ungrouped) split lets overlapping windows of one slice sit on both sides, which inflates or deflates the score. SRS-1 fixes all of those choices once, publishes the reference windows by digest, and makes every record checkable without rerunning anything.

The method is a classifier two-sample test (Sourced fact: Lopez-Paz and Oquab, [Revisiting Classifier Two-Sample Tests](https://arxiv.org/abs/1610.06545), ICLR 2017, read 26 Nov 2026): fit a classifier to tell real from simulated, and read its held-out AUC. SRS-1 adds grouped folds, several critics with the worst case taken, planted checks, a real-against-real control, a sample-size rule and a fixed record. A web search on 26 Nov 2026 found no published realism standard for simulated scroll CT; that is a search result, not proof that none exists.

## The protocol (normative)

A scoring follows these steps in order. A failed gate makes the record VOID; a VOID record is never reported as a PASS or a FAIL.

1. **Reference.** Real CT slices as 2D grey-value arrays, at least 6 (`MIN_GROUPS`), each with an optional cover mask. Slices are numbered in their listed order; even and odd mean that number. The default reference is R343-v1 (below). A team may use its own scan with the same protocol; its records are comparable only with records on the same reference.
2. **Fit half.** A generator may be fitted or tuned to the even slices (declared in `trained_on`). It must never be fitted or tuned to the odd slices; the scorer refuses odd slices listed as trained on.
3. **Set.** At least 240 simulated tiles (`MIN_SIM_TILES`) of at least 256 px a side, the first 240 in the order the generator wrote them, with the generator's name, version and seeds recorded. Fixing the seeds before scoring and taking the first tiles rules out picking the best-looking ones.
4. **Windows.** Non-overlapping 128 px windows on a grid (`WIN`), each scaled to its own 1st to 99th percentile; reference windows need cover of at least 0.98. Context windows: 256 px, 2x2 mean-pooled to 128.
5. **Critics.** Three critics, refitted from scratch on every call and never saved: `feat` (46 hand-made features with a logistic), `cnn` (seven-layer CNN at 128 px, 800 steps) and `cnn_half` (the same on context windows). Three folds grouped by whole slice and whole tile; seeds 0 and 1; a critic's AUC is the mean over folds and seeds. The score of a comparison is its **worst** (highest) critic AUC.
6. **Planted gate.** On the reference windows alone: two random halves of the slices (feat and cnn AUCs must stay under 0.65), one half with Gaussian noise of sd 0.08 added and one half blurred at sigma 1.0 (each must reach 0.90). A judge that cannot fail and pass known cases says nothing about a simulator.
7. **Control gate.** The same critics on even against odd slices. Its worst AUC must stay under 0.65.
8. **Set comparison.** The odd slices against the set's windows.
9. **Pass rule.** PASS when the set's worst AUC is at most the control's worst AUC plus 0.05 and at most 0.60 (both bars inclusive); otherwise FAIL. This is `kit.simcritic.verdict`, fixed in a preregistration before its first use on 25 Nov 2026. `gap_to_bar` is the worst AUC minus the bar; at most 0 passes.
10. **Sample-size rule.** From the null calibration below (preregistered and run 26 Nov 2026): no reference size tried (6, 12 or 24 slices) keeps the bar's false-FAIL rate for a perfect simulator at or under 0.10, so **no reference size is admitted**. A PASS is therefore reported as INCONCLUSIVE, never as a verdict, and a FAIL counts only when `gap_to_bar` exceeds D99, the 99th percentile of the gap for a perfect simulator at the nearest calibrated size at or above the reference's slice count (6 slices: 0.2454; 12: 0.2045; 24: 0.0788). Any other FAIL is INCONCLUSIVE. References with more than 24 slices have no calibrated D99 under SRS-1, so their results are INCONCLUSIVE.
11. **Record.** One JSON record (fields below) with the scorer's file digests and a SHA-256 over the record. `python -m kit.simscore check RECORD` recomputes the gates, the verdict and the status from the record's own numbers and fails on any mismatch.

## Fair play

- **Count every attempt.** `attempts` is the number of sets the team scored under SRS-1 on that reference before this one. A low AUC after many attempts is weaker evidence than the same AUC at the first try; readers should weigh it so.
- **No training against the scorer.** Using SRS-1 critics, their AUCs or this scorer's output as a loss or a tuning target lowers the score by construction (Goodhart). A generator may use its own discriminator; tuning to SRS-1 scores is allowed only on the fit half and counts as attempts.
- **Odd slices are the test.** Never fit, tune, select or calibrate a generator on the odd slices of the reference you report on.
- **Report FAILs too.** A record is published whatever its status, so the record of attempts stays honest.

## The R343-v1 reference

Six axial slices of PHerc0343P, a public fragment scan on no prize list, read from the Vesuvius Challenge open data:

| Field | Value |
| --- | --- |
| CT | `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0343P/volumes/20260304131111-2.215um-0.4m-111keV-masked.zarr`, level 2 (8.86 µm) |
| Labels (normalization only) | the organizers' public surface labels, `scrollprize/datasets` bucket, `surfaces/2um_032726/2.215um_0.4m_111keV_PHerc0343P_surface.zarr`, level 2: only used to pick the voxels whose 0.5 and 99.5 percentiles set the grey-value scale |
| Slices | level-2 z 1460, 1500, 1540, 1580, 1620, 1660 |
| Box | y 1006 to 1663, x 1148 to 2605 (level-2 voxels) |
| Resampling | to 9.362 µm, linear; clipped to -0.5 to 1.5; cover where the resampled value is above -0.43 |
| Windows | 211 (even 105, odd 106) |
| Digests (`kit.simcritic.digest`) | all `0c18a31a45f5daf9a8f868699d4bf3bc3cb2fa1a50de32e286198237c3134ad7`; even `6fe00a059c895a2b230964e513c1f715fb3be399f43dc1c8452ccc7ffcc203b5`; odd `e693866295f89ba69b36eb70b25adca2153b79f3543e20eb5ab97892743adf34` |

`python -m kit.simscore reference R343.npz` fetches it (14 s in a 4-core cloud container, 26 Nov 2026) and prints the digest; a different digest means different windows, so the record is not on R343-v1. The even and odd digests are byte-identical to the windows of the 25 Nov 2026 judgement below (checked 26 Nov 2026). The scan data is CC BY-NC 4.0 (Vesuvius Challenge open data terms); SRS-1 links it and never rehosts it.

R343-v1 has only 6 slices, so the sample-size rule applies to it (step 10).

## Reference results

Scored on 25 Nov 2026 with the same scorer settings, windows (digests above) and pass rule, before this page was written, so they are listed as reference results rather than SRS-1 records ([simcritic results](../tools/simcritic.md#results)). Model output.

| Set | Worst-critic AUC | Gap to bar | Under SRS-1 |
| --- | --- | --- | --- |
| Control: R343-v1 even against odd | 0.473 | bar 0.523 | gate passed |
| Hard Cases tiles, `343p` render preset, two rounds | 0.999 and 1.000 | +0.476 and +0.477 | FAIL (gap above D99 0.2454) |
| The same tiles through a learned sim-to-real texture (not released), five settings | 0.971 to 0.998 | +0.448 to +0.475 | FAIL (gap above D99 0.2454) |

None of these seven sets comes near the bar. The 46-feature critic was the worst case for 6 of the 7 sets; its finest power-spectrum band and its orientation-coherence features separate them most (Interpretation, post-hoc).

## Null calibration of the bar

Preregistered ([`prereg`](../prereg/2026-11-26-srs1-null-calibration.md), committed before the run) and run on 26 Nov 2026 ([evidence](../evidence/srs1-calibration-1126/README.md)). A perfect simulator (more tiles of the same `kit.hardcases` generator) was scored against stand-in real slices (groups of tiles of one seed) with the fixed bar, using the feature critic, 200 replicates per size. Model output on synthetic data:

| Reference slices | False FAIL rate for a perfect simulator | D99 of gap to bar | Control AUC sd |
| --- | --- | --- | --- |
| 6 | 0.595 | 0.2454 | 0.105 |
| 12 | 0.485 | 0.2045 | 0.095 |
| 24 | 0.285 | 0.0788 | 0.056 |

A slightly blurred simulator (Gaussian sigma 0.5, mean set AUC 0.69 to 0.73) still passed the bar 0 to 9 percent of the time, and a more blurred one (sigma 0.8) never did.

What this means (Interpretation): the control's own AUC moves by about 0.10 between draws when each side has only a few slices, twice the 0.05 margin, so a fixed margin over one control draw cannot certify that a set is realistic at these sizes. It can still rule a set out when the gap is large, which is all SRS-1 claims. A bar taken from the null distribution itself, such as a permutation test against relabeled real slices, is the natural rule for an SRS-2 (Untested idea). Limits: stand-in slices are synthetic tiles, not scan slices, and the CNN critics were left out; the worst of three critics spreads wider, so the real false-FAIL rate is likely higher, not lower.

## The record

`kit.simscore.score` writes these fields; `check` reads them.

| Field | Meaning |
| --- | --- |
| `standard` | `SRS-1` |
| `scorer` | SHA-256 of `kit/simcritic.py` and `kit/simscore.py` |
| `settings` | every fixed setting; `check` fails if any differs |
| `reference` | id, slice names, group count, window counts, window digest, `trained_on` |
| `set` | tile and window counts, window digest |
| `generator` | name, file, npz key, file SHA-256 |
| `attempts` | sets scored on this reference before this one |
| `planted`, `control`, `result` | the AUCs, per critic and per seed run |
| `gates`, `verdict`, `status`, `reason` | the gate results, the pass rule, and PASS, FAIL, INCONCLUSIVE, VOID or SMOKE |
| `calibration` | the admitted reference size and D99 table the status used |
| `record_sha256` | SHA-256 over the rest of the record |

## How to score a set

```bash
python -m kit.simscore reference R343.npz          # fetch R343-v1, print its digest
python -m kit.simscore score --reference R343.npz --sim my_tiles.npz --key image \
    --generator "mysim 0.3" --attempts 0 --out record.json [--device cuda]
python -m kit.simscore check record.json            # exit 0 when the record is consistent
```

The tiles npz holds a stack of 2D arrays under `--key`. A full score runs 11 CNN critic runs plus the feature critic; at the rate measured on a Hugging Face `cpu-upgrade` machine on 25 Nov 2026 (25 to 30 minutes per 3-fold CNN critic) that is about 5 hours on one CPU worker. A GPU is faster; the full scorer has not been timed on one. `--smoke --steps 2` checks the pipeline in seconds and is marked SMOKE, never a verdict.

## Limits

- One reference scan. A set that passes on R343-v1 may fail on another scan; a cross-scan realism claim needs records on several references, each under this protocol.
- A critic outside SRS-1 may still separate a set that passes. The standard measures, it does not prove.
- The calibration uses the feature critic on synthetic stand-ins (see its limits); the worst of three critics spreads wider.
- Grey values of 2D windows only: 3D structure, labels and downstream use (does a model trained on the set transfer?) are not scored. A transfer test belongs beside a realism record, not inside it.

## Changes

SRS-1 is frozen as written here once merged. Any change to a setting, gate, bar, reference or rule makes a new version (SRS-2), with its own reference digests and calibration, and is never applied to SRS-1 records after the fact. Corrections of wording that change no number keep the version.

## History

- 2026-11-26: draft SRS-1, reference scorer `kit.simscore`, null calibration preregistered ([`prereg`](../prereg/2026-11-26-srs1-null-calibration.md)) and run ([evidence](../evidence/srs1-calibration-1126/README.md)).
