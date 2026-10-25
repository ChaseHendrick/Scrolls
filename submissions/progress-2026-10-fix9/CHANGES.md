# AutoPipeline 0.1.9: swap any stage by name, and 3D ink readers

This package follows AutoPipeline 0.1.8 at public commit `bf807b6fbde450bd8eb8b92654f529db06d19d3c`. Earlier released branches and tags stay unchanged. Every map the pipeline makes is model output, not a reading, and this release makes no claim that a 3D reader reads ink better than the 2.5D default.

## Swap any stage by name

`python -m kit stages` is the stage registry: every option of every stage (umbilicus, surface, trace, repair, snap, flatten, render, ink, ensemble and others) with who made it (ours, community, team or published), its licence, its maturity (default, validated, experimental, pending or failed) and why. It reads AutoPipeline's own backend tables and `kit/data/stages.json`, and lists nothing twice. `python -m kit autopipeline plan SAMPLE --use STAGE=NAME` (repeatable, and `KIT_STAGE_<STAGE>` in the environment) turns a pick into the plan's `backends` setting before the plan is frozen, so the digest covers it. An experimental pick warns, a pending one is refused, and one that contradicts `--settings` is refused. Code or weights with no stated licence are only read from their own host at run time.

## 3D ink readers in the ink stage

`python -m kit ink3d` runs a 3D ink model, or reads a published 3D prediction, and projects the volume onto a surface's 2.5D render canvas: at each pixel it takes the point and normal `vc_render_tifxyz` samples and keeps the largest value within 15 um of the sheet. A 3D map and a 2.5D map of one surface therefore share their pixels, labels and scorer. Engines: the organisers' Paris 4 3D model (`team-3d-paris4`, `scrollprize/ink_paris4_3d_4.8um_gambiarra`, MIT, through villa's `paris4_3d_gambiarra` inference named by `KIT_GAMBIARRA`), villa full_3d checkpoints, published predictions, or any command.

Reverse depth order means nothing for a 3D reader, so its r map is a moved-sheet control: the same read with the sheet moved two sheet pitches out and two in, the larger of the two at each pixel. The pitch is measured from the CT along the render normals (the nearest density peak on each side), or given as `ink.pitch_um`; with no pitch there is no control and the run refuses. The record says `dims: 3d` and `control: moved-sheet`.

A plan names a 3D reader in `ink.models` or with `--use ink=reader-v3,team-3d-paris4`. The default stays `["reader-v3"]`, and a plan without a 3D reader keeps its digest. Every 3D reader is experimental: none has beaten the 2.5D default on a held-out test. `team-3d-paris4` was trained on 2.4 um Paris 4 scans only.

## Checks

Tests build a synthetic scan with sheets every 12 voxels: ink on the traced sheet shows in the f map and not in the control, ink on the neighbour sheet fails that way, a flat CT refuses for want of a pitch, and a render on another grid refuses. An AutoPipeline run on the fake scroll makes a 3D map beside a 2.5D one on the same canvas. The registry's check plants each of its rules' faults and requires each to be named.

## Package

Version metadata changes from 0.1.8 to 0.1.9. The ink Space is unchanged. The Docker image was not rebuilt for this version. This package does not assert a Progress Prize form submission or award.
