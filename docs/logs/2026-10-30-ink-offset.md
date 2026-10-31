# How much ink AUC a surface offset costs, PHerc0841 w00 and ag896 (30 October 2026)

Development only, two segments, no frozen test. Every number is Model output; the readings are Interpretation. Tool and method: [`docs/tools/offsetdiag.md`](../tools/offsetdiag.md), code in [`scripts/offsetdiag/`](../../scripts/offsetdiag/), numbers in `results.json` under `offsetdiag_dev_20261030`.

## Setup

- Segments: PHerc0841 w00 and ag896 on the 9.366 um scan (20250821151531), inside the development scoring boxes of earlier ink rounds (the boxes in `scripts/offsetdiag/oddata.py`). Both segments had already been used in earlier development.
- Model: Reader V3 (Domenico Russo, [`domenicor046/reader-v3`](https://huggingface.co/domenicor046/reader-v3)), layers 6 to 23 of the 28-layer stack (`--layer-start 6 --layer-end 23`), hann blending, overlap 0.5, both depth directions. A second, smaller ink model of ours (not released) ran beside it.
- Arms: P0 (the published surface volume's box), R0 (our render at the published offsets), constant shifts of 4 and 8 voxels each way along the published stack's normal (minus is toward layer 0), SNAP (each pixel moved to villa's lasagna cos maximum nearest the mesh, the sheet center), and its same-size controls ANTI (the other way) and RAND (the field turned 180 degrees).
- Scoring: `kit.auc` inside the supervision mask, the reversed-depth map as control, as stored and texture label registrations, arm minus R0 with a paired block bootstrap.

## Results

- Gate: before any shift, Reader V3 on the published boxes (P0) reproduced its earlier scores exactly.
- 4 voxels toward layer 0 cost 0.07 (w00) and 0.04 (ag896) AUC; 4 voxels the other way about 0.02, not significant.
- 8 voxels toward layer 0 cost 0.25 and 0.21; 8 the other way 0.16 and 0.12.
- Moving toward layer 0 cost 1.5 to 4.1 times as much as the same move the other way.
- SNAP cost 0.03 to 0.08 AUC but beat ANTI and RAND, so the published meshes already sit better for ink than the sheet center on these two segments.
- The smaller model lost less per shift, but Reader V3 stayed above it at every shift (smallest gap 0.03).
- Our render at offset 0 moved Reader V3 by +0.007 (w00) and -0.009 (ag896) against the published surface volume: renderer details alone are worth about 0.01.

## Limits

Development only: two segments of one scroll, one main model, both segments already used in earlier development. It is not a test, and no shift chosen here is a tested gain.
