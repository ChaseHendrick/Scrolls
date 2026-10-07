# Cloud job results so far (2026-10-07, evening; partial)

Model output on public labelled data, PHerc0841 w00 crop (640 px, 64 px edge left out), CPU, villa PR #1865. Full rows: `scripts/experiments/2026-10-07-cloud/<job>/results.json` on branches `claude/gallant-pasteur-b1y2si-tricks` and `-v8in1447-w00`. ag896 and ag405 were still running at the original snapshot. The review below incorporates subsequently recovered scores without rescoring maps; ag405 tricks and the ag896/ag405 v8in-1447 maps have no saved scores.

| Reader on w00 | AUC as stored | Reversed | Depth-shuffled | Letter-scale r |
| --- | ---: | ---: | ---: | ---: |
| `ink_9um` seed 42 | 0.806 | 0.536 | 0.500 | 0.029 |
| its soup (`soup42_last4`) | 0.833 | 0.505 | 0.481 | 0.032 |
| d9v2 | 0.899 | 0.586 | 0.491 | 0.015 |
| **Reader v2** | **0.927** | **0.729** | **0.568** | 0.048 |
| d9v2 + Reader v2, map mean | 0.928 | 0.677 | | 0.039 |
| v8in-1447 (stride 42; reverse stride 64) | 0.838 | 0.593 | | 0.007 |
| v8in-1447 + d9v2, rank mean (v8in reverse stride 64) | 0.907 | 0.613 | | 0.012 |

**Observation (w00, one crop).** Reader v2 has the highest forward AUC among the individual readers shown, with reversed AUC 0.729 and shuffled AUC 0.568. These controls retain pixel-level label association, but do not establish its cause or what share of Reader v2's forward lead is spurious. Its high-pass label alignment falls strongly under both controls, as the recovered table below shows. Its published whole-segment PHerc0841 score (0.824) is a different evaluation setup. ag405 remains the independent-surface check.

**Recovered control readouts (two crops of one sheet).** w00 and ag896 cover different physical patches of the same sheet; these are related observations, not independent-surface replications. The rolled-key maxima describe three shifts, not a calibrated significance threshold.

| Reader | Crop | hp_r forward | hp_r reversed | hp_r shuffled | Forward rolled-key null max abs |
| --- | --- | --- | --- | --- | --- |
| Reader v2 | w00 | +0.0478 | +0.0040 | +0.0019 | 0.0153 |
| d9v2 | w00 | +0.0154 | -0.0034 | +0.0017 | 0.0132 |
| Reader v2 | ag896 | +0.0249 | +0.0032 | +0.0062 | 0.0093 |
| d9v2 | ag896 | +0.0167 | +0.0053 | -0.0015 | 0.0068 |

Reader v2 has stronger forward high-pass alignment than d9v2 on both patches. No paired uncertainty or matched-blur comparison was measured, so this is a descriptive comparison, not evidence of significance or legibility. For d9v2, averaging four depth windows raises forward AUC by 0.0204/0.0087 on w00/ag896 and reverse AUC by 0.0298/0.0185. The resulting forward-minus-reverse gaps decrease by 0.0094/0.0098; high-pass correlation changes by +0.0035/-0.0001. These AUC gaps are diagnostics, not corrected accuracy or proof that a forward signal is spurious.

**v8in-1447.** The saved w00 forward AUC is 0.8381 and reverse is 0.5932; the rank ensemble is 0.9065/0.6134. Its forward stride is 42 and reverse stride is 64, so the controls also change stride and need a matched-stride check. The nearby published base-v8in score (0.837, Bullo27's label-box evaluation) uses different crop/pipeline settings and cannot establish that fine-tuning helps or hurts. A matched base-v8in comparison is still missing.
