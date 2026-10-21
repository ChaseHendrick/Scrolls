# Ink Lens control check: preregistration

Frozen 20 October 2026, before any Ink Lens map of any region existed. Tool: `spaces/ink-lens/` (design in
`spaces/ink-lens/DESIGN.md`, page in [`docs/tools/ink-lens.md`](../tools/ink-lens.md)). The rule is coded in
`spaces/ink-lens/gate.py` (`RULE_ID = "ink-lens-gate-v1"`); this file and that code must agree, and a change to either
is a new rule with a new id and a new preregistration.

## The rule

- F and R are the mean ink probabilities (0 to 1) of one region with its layers as stored and reversed. Each is the
  mean of the same three 17-layer depth windows (starts 0, 2 and 4 of the 21 layers around the middle), and of the
  same readers when more than one is chosen.
- Papyrus: pixels whose middle CT layer is above the region's own 5th percentile of CT and above 0.
- T: the 99th percentile of R over the papyrus pixels.
- Kept ink: papyrus pixels with F > T. Excess: the share of papyrus pixels with F > T, divided by 0.01.
- Status: `ink` when excess >= 3; `weak` when 1.5 <= excess < 3; `none` below 1.5; `too_small` under 100,000 papyrus
  pixels; `unreadable` when F or R is not finite, constant on the papyrus, or identical to the other.

## The checks, all on public data, before release

Reader: d9v2 (`d9v2_ft-012000.pth`, SHA-256 `50d2ad0e...a9f966`), three windows, villa
`8aa507c1215f1fa8758f13d0538f7af9710e02d7` flat inference with the robust normalisation of `engine.robust_torch`, on
CPU in a Claude cloud container (rule 11: under 10 minutes). Regions: the three PHerc0841 640 px crops in
`spaces/ink-lens/samples.json` (w00, ag896, ag405), which are in the training data of neither d9v2 nor `ink_9um`
(public `docs/results.json`, `held_out`).

1. **Labeled crops.** For each crop: the status must be `ink`, and kept ink must hold a larger share of the labeled
   ink pixels than of the labeled background pixels (inside the supervision mask, 64 px inner edge left out,
   `gate.label_shares`). Reported beside them: the raw AUC of F and of R with `kit.auc.score_array` (inner 64).
   Pass: all three crops meet both conditions.
2. **Swapped input.** The same three crops with R given as F and F as R: no crop may get the status `ink`.
3. **No papyrus.** A 640 px region of w00 off the segment (all zero, refused by the engine) and the 640 px window at
   rows 0 to 640, columns 0 to 640 of w00: the status must be `none`, `too_small` or `unreadable`, or the engine must
   refuse the region.

A FAIL on any check is reported as it is, in this file's results section and in the tool page, and the Space is not
offered for release until the rule is changed under a new preregistration. These numbers are development numbers on
windows chosen with the labels, not a blind test, and the status is model output, not a reading.

## Results

Filled in after the checks run; nothing above this line changes.

Run 20 October 2026 with `spaces/ink-lens/tools/check_gate.py` (CPU, 4 cores, fp32); every number is in
[`scripts/experiments/2026-10-20-ink-lens-gate/results.json`](../../scripts/experiments/2026-10-20-ink-lens-gate/results.json)
and `ink_lens_checks` in [`docs/results.json`](../results.json). Model output on development windows.

| Crop | Status | Excess | Labeled ink kept | Labeled background kept | Swapped status |
| --- | --- | --- | --- | --- | --- |
| w00 | ink | 15.4 | 53.9 % | 3.1 % | none (excess 0.0) |
| ag896 | ink | 21.2 | 52.3 % | 7.1 % | none (excess 0.0) |
| ag405 | ink | 17.6 | 49.7 % | 7.1 % | none (excess 0.0) |

Check 1: PASS. Check 2: PASS. Check 3: PASS by refusal (the corner window of w00 is all zero, so the engine refused
it before the gate ran; the gate was not exercised off the papyrus).
