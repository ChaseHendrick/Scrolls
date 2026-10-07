# 2026-10-07: lane C, gaps not yet tried, and two small model-free experiments

Research notes, not claims. Labels per [`../NOVELTY.md`](../NOVELTY.md). Public labelled data only (PHerc0139 w045, PHerc0841 w00); no target scroll was touched. Ink maps are model output, not readings.

## Readout rule (written before any experiment ran)

Experiment 1 (texture): a model-free feature counts as an ink signal at 9 um only if, on both w045 and PHerc0841 w00 crops (inner 64 px), its AUC is on the same side of 0.5, at least 0.05 from 0.5, and outside the range of 8 rolled-map nulls; for a depth-dependent feature it must also differ from its depth-shuffled version by at least 0.02 in the direction away from 0.5. Otherwise it is a null.

Experiment 2 (fusion): a feature's sign is chosen on w045 (seen scroll, held-out segment) and applied unchanged to w00 (unseen scroll). Fusion counts as a gain only if the rank fusion beats rank `ink_9um` alone on w00 by at least 0.01 AUC at a weight fixed in advance (0.25); the 0.1 and 0.5 weights are reported but do not decide. The noise floor on w00 is about +-0.008 (README finding 8), so a smaller gain is a null.
