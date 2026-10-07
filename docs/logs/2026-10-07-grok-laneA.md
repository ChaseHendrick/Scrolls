# Lane A: descriptive cross-analysis of PRs #6 to #10 (2026-10-07)

Model output on public labelled PHerc0841 data, not a reading. This lane opens no map and runs no inference. It recombines committed scalar records; this is an exploratory analysis, not a new independent experiment or a novelty search.

## Correction to the historical interpretation

The checked-in `synth.json` and `synth.out` are preserved byte for byte as historical artifacts. Their numeric AUC differences and Kendall calculation reproduce from the listed records. Their `clear`, `marginal`, `within noise`, and `strong_flips` classifications are invalid for uncertainty inference. They borrowed marginal bootstrap widths from the team's whole-segment map and applied them to different readers and bare-crop differences. Disclosure as a rule of thumb does not make those intervals transferable. No actual paired crop bootstrap was performed. A small point difference does not establish a null or an equivalence bound, and a large point difference does not establish significance.

The corrected generator emits descriptive differences without these verdicts, propagates recorded control status, and pins inputs to commits:

- `tricks`: `a2951681ad1c590bdd4686c5340cfe1226887d60` (PR #8).
- `v8in1447-w00`: `c4a5ead246f502e16a7b34db6629b14562bb630e` (PR #7).
- `v8in1447-ag405`: `97d26e74417f42fb87abf80ad25c8a90f5629710` (PR #9).

From the repository root, write new outputs instead of overwriting history:

```bash
python3 scripts/experiments/2026-10-07-grok-laneA/synth.py --json /tmp/laneA-descriptive.json > /tmp/laneA-descriptive.out
```

## Observed point differences

Reader v2 minus d9v2 is +0.0275 on w00 and -0.0258 on ag896. Across 24 shared map variants, Kendall tau-a is 0.551, with 214 concordant and 62 discordant pairs. These variants include correlated readers, windows and ensembles; the 276 pairs are not independent observations. Main's overlap analysis establishes that w00 and ag896 are traces of one sheet, and their scoring crops cover different physical patches. This comparison cannot separate patch effects from tracing or depth effects and is not an independent-sheet replication.

Selecting a depth window by labels on one crop and applying it to the other gives six exploratory transfers across three readers and two directions. The fixed four-window mean has a higher point AUC than the transferred choice in all six observed cases, by +0.0074 to +0.1718. This extends the existing same-crop arithmetic comparison descriptively. It does not establish a general target-run policy, statistical certainty, or an independent calibration/test split; both traces belong to the same sheet.

Reader v2's shuffled AUC is 0.5681 on w00 and 0.6170 on ag896. Its reversed ag896 AUC is 0.5988; d9v2's reversed AUC on the separate ag405 surface is 0.6572. These are recorded control outputs, not readings or proof of a specific source of false positives. Shuffling and reversing remain different controls and both should be reported.

Soup minus seed 42 is +0.0265 on w00 and +0.0129 on ag896. d9v2 four-window mean minus default is +0.0204 and +0.0087; mirror TTA minus default is +0.0208 and -0.0099. Seed 42 four-window mean minus default is +0.0366 and +0.0627. These are differences in this dataset, with uncertainty unmeasured; they do not establish which gains replicate statistically.

On w00, the v8in-1447 + d9v2 rank ensemble exceeds d9v2 by +0.0071. Its historical reverse component uses stride 64 versus forward stride 42, so its depth-control contrast is provisional. The same limitation applies to the standalone v8in-1447 and its mean ensemble. Preserve their recorded `provisional_stride_mismatch` status. The point comparison alone cannot establish that v8in-1447 adds nothing measurable.

## Remaining checks and source limits

A meaningful inferential comparison requires the actual maps, identical scored pixels, paired spatial block resampling, matched depth-control settings and declared comparison families. An independent-sheet or scroll test is needed for transfer claims. PR #6 threshold transfer did not run; PR #10 has no results file; the inspected ag405 archive contains d9v2 only. These are missing work, not negative findings.

Sources are PRs [#7](https://github.com/ChaseHendrick/Scrolls/pull/7), [#8](https://github.com/ChaseHendrick/Scrolls/pull/8), [#9](https://github.com/ChaseHendrick/Scrolls/pull/9), and the main logs `2026-10-07-overlap-and-baseline.md` and `2026-10-07-novel-checks.md`. No broad prior-art search was performed by this synthesis, so it makes no priority claim.
