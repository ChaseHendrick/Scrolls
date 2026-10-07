# Cloud job results so far (2026-10-07, evening; partial)

Model output on public labelled data, PHerc0841 w00 crop (640 px, 64 px edge left out), CPU, villa PR #1865. Full rows: `scripts/experiments/2026-10-07-cloud/<job>/results.json` on branches `claude/gallant-pasteur-b1y2si-tricks` and `-v8in1447-w00`. ag896 and ag405 were still running when this was written; fold them in when they land.

| Reader on w00 | AUC as stored | Reversed | Depth-shuffled | Letter-scale r |
| --- | ---: | ---: | ---: | ---: |
| `ink_9um` seed 42 | 0.806 | 0.536 | 0.500 | 0.029 |
| its soup (`soup42_last4`) | 0.833 | 0.505 | 0.481 | 0.032 |
| d9v2 | 0.899 | 0.586 | 0.491 | 0.015 |
| **Reader v2** | **0.927** | **0.729** | **0.568** | 0.048 |
| d9v2 + Reader v2, map mean | 0.928 | 0.677 | | 0.039 |
| v8in-1447 (stride 42) | 0.838 | | | 0.007 |
| v8in-1447 + d9v2, rank mean | 0.907 | | | 0.012 |

**Observation (w00 only, one crop).** Reader v2 scores highest, but its reversed map scores 0.729 and its depth-shuffled map 0.568, far above every other reader's controls (0.48 to 0.59). A large share of its AUC does not depend on reading the layers in the right order, so part of its lead over d9v2 is not ink read in depth. Its published PHerc0841 numbers (0.824 whole) carry no reverse or shuffle control. Needs ag405 (the independent surface) before it is a finding. **v8in-1447** reads w00 at 0.838, the same as base v8in in Bullo27's published run (0.837, labels' box), so on this crop the PHerc1447 fine-tune neither helps nor hurts; its reverse control is still missing.
