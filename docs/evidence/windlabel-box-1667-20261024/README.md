# windlabel-box on a second scroll, PHerc1667, 24 October 2026

The second-scroll check of [`kit windlabel-box`](../../tools/windlabel-box.md) and its VC3D plugin. Model output: relative windings grown on PHerc1667's open-data scan `20231117161658` (7.91 um) from an m7 surface prediction we ran with the organizers' published model, and from the published lasagna grad_mag of the 2.4 um scan `20251217075048`. They are scored against PHerc1667's published hand windings w028 to w041. It is not a reading and says nothing about ink.

- Every rule and number was fixed before any box had a prediction, in preregistrations kept in the project's private workbench. The rules were: chain rule, box, seeds, truth, readout (`readout` in [`summary.json`](summary.json)) and the m7 recipe. No setting was tuned on this scroll before the first test.
- **Split rule v1, 18 boxes: FAIL.** Split chains 0.9693 on 4,362 judged steps (lower bound 0.9508), but only 68.3 % of the uncut chains' judged steps kept, under the 70 % floor.
- **Split rule v2, 20 fresh boxes: PASS.** v2 is the same rule with the cut moved from 0.95 to 1.0. That value was picked after the v1 result, on spent boxes of both scrolls. The boxes sit higher in the scroll (z 8100 to 9850), away from the first 18.
  - Split chains 0.9786 on 5,938 judged steps (lower bound 0.9671 over 35 blocks), 75.9 % kept.
  - The uncut chains scored 0.9486.
  - Random cut control: median 0.9499, 97.5th percentile 0.9527. Skip control 0.0165, shift control 0.0772.
  - Per box 0.738 to 1.0; two boxes had no judged step.
- Limits:
  - Two runs on one scan.
  - Whether villa's tracing or lasagna models saw these windings is not known to us.

[`summary.json`](summary.json) has both tests' pooled numbers and each box's step counts and accuracies. Box positions and chain files are not included.
