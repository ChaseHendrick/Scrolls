# 2026-10-14: turn a traced render upright before ink detection

Every number below is model output of `ink_9um` on PHerc0841, scored against the published w00 ink labels. It is not a reading. Nothing here is about a target scroll, and no render, map or scroll image is committed. Claim labels follow [NOVELTY.md](../NOVELTY.md).

## What I found

My own traces come out of the tracer and the flattener turned at an arbitrary angle, and `ink_9um` reads a render turned off a right angle much worse than an upright one. On one of my traces of PHerc0841, turning the render upright before ink detection, and the ink map back afterwards, raised pixel AUC from 0.618 to 0.874 on the same labelled pixels, where the published segment's map scores 0.798.

## Why it happens

**Sourced fact (villa `main`, checked 14 October 2026; the same at `e0bbb8b`).**

- Published segments are rendered in one standard orientation: the scroll's axis (+z) runs down the rows and text is readable (`volume-cartographer/apps/src/vc_render_tifxyz.cpp` lines 1285 to 1287).
- A traced surface's grid is not tied to the axis. `vc_render_tifxyz` turns its output only by right angles, on request (`--rotate 0/90/180/270`, line 1283). The ABF++ flattening has two options that would set the turn, `alignToInputGrid` and `rotateHighZToTop` ("rotate output so highest Z values are at row 0"), both off by default (`volume-cartographer/core/include/vc/flattening/ABFFlattening.hpp` lines 39 and 42).
- villa's ink training code turns patches by right angles only, with mirrors and transposes (`vesuvius/src/vesuvius/ink_detection/data/augmentations.py`, `create_default_training_transforms`, lines 184 to 218); the released `ink_9um` readers come from it.

**Community report.** Asked whether the detection models are rotation invariant, a model author answered that they are trained with rotation augmentations, "so it should be fine" (Discord #general, 26 February 2025). For `ink_9um` that holds for right angles only, as below.

## Turning a published segment (ablation, 13 October 2026)

The published w00 surface volume, turned in plane and turned back the same way, read by `ink_9um` seed 42, scored on w00's labels inside the same 808,383 to 866,730 supervised pixels. Paired block bootstrap, 2,000 draws of 107 px blocks.

| Turn | Cost in AUC against the unturned map | 95 % interval |
| --- | ---: | --- |
| 30 degrees | 0.155 | [0.077, 0.228] |
| 90 degrees | 0.027 | [-0.020, 0.078] |
| Resampling only (no net turn) | 0.009 | [-0.004, 0.023] |

**Model output.** A 30 degree turn costs a lot; a right angle, which the training covered, and the resampling itself cost little or nothing measurable.

## The test on my own trace (preregistered, 13 October 2026)

**Setup.** AutoPipeline, my automatic pipeline from scan to ink map ([released](https://github.com/ChaseHendrick/Scrolls/tree/submission/progress-2026-10/submissions/progress-2026-10/autopipeline) on 14 October), traced a patch of PHerc0841 from a seed near w00 on 11 October. w00's human ink labels were carried onto its render where the two meshes are within 4 voxels and 30 degrees of each other: 352,860 labelled pixels. On those pixels `ink_9um` seed 42 scored 0.618 on my render and 0.798 on the published w00 map.

**The turn.** `kit canvasorient` measures the angle from the mesh alone: the direction in which z grows across the canvas, with a consistency score, and the normal's sign voted against the scroll's axis. For my trace it gave 49.3 degrees (consistency 0.983). On ten published meshes (PHerc0841 w00 and ag896, eight PHerc0139 windings) it reads between -2.3 and 1.4 degrees, and planted turns of each are recovered within 1 degree.

**The rule, fixed before any turned map existed.** GO needed all four: seed 42 upright beats native (interval above 0), it wins back at least half the gap to the published map, it beats a sham turned 45 degrees past upright, and seed 43 upright beats native. The run would be void if the inputs, a rerun, either reader's pipeline check, an A/A or any reverse control failed. The labels of PHerc0841 ag405, kept for a final test, were never opened.

| Arm | Seed 42 | Seed 43 |
| --- | ---: | ---: |
| Upright minus native | +0.256 [0.148, 0.368] | +0.181 [0.084, 0.289] |
| Upright minus sham (upright plus 45 degrees) | +0.213 [0.078, 0.360] | +0.208 [0.131, 0.298] |
| A/A: published w00 turned by its own angle (-2.3 degrees) and back | -0.018 [-0.066, 0.032] | +0.000 [-0.051, 0.049] |

**Result: GO** (Model output). Upright scored 0.874 against the published map's 0.798 on the same pixels; that difference, -0.076 [-0.164, 0.015], is not resolved. Both readers' pipeline checks matched the expected crop scores to 1e-4, the rerun matched exactly, and every forward map cleared its depth-reversed control by at least 0.137.

## Limits

- One trace, one scroll, on pixels that had been scored before. This is development data, not independent confirmation. The held-out test (labelled PHerc1447 windings, run once) has not been run.
- One reader family (`ink_9um`, two seeds). Other readers may be trained with other augmentations.
- The angle needs a sheet that contains the scroll's axis. On a sheet lying across it, the measure reports the canvas as not applicable and nothing is turned.
- Whether `rotateHighZToTop` alone gives the same gain was not tested. It would put +z up the rows, 180 degrees from the published layout, a turn the training covers (Interpretation).

## Related work

Shribyr Labs found the same kind of limit for the m7 surface model in 3D: it never saw a sheet more than 30 degrees from its training pose and misses sheets lying across the scan axis ([report](https://github.com/ShribyrLabs/vesuvius-reports/tree/main/03-m7-orientation-bias), Discord, 22 September 2026). Forrest reported that arbitrary rotations and reflections in training helped a distilled surface model (Discord, 1 September 2026). In our archive of the project's Discord I found no earlier measurement of in-plane turns for the released ink models (Community report search, 14 October 2026).

## How to use it

AutoPipeline's optional plan setting `ink.orient` (method `upright`) does the turn and the turn back for each accepted trace, and `kit canvasorient measure|apply|back|check` does it by hand on any tifxyz and its render. Both are in the [AutoPipeline release](https://github.com/ChaseHendrick/Scrolls/tree/submission/progress-2026-10/submissions/progress-2026-10/autopipeline). The ablation can be rerun on the public w00 surface volume; the trace test cannot yet, because the trace itself is not published.
