# Do villa's tracer loss weights keep a trace on its sheet? A dev sweep on PHerc0139 (25 October 2026)

Development only. PHerc0139 volume 20250728140407 (9.362 µm) is public and on no prize list. Windings w027 and w037 were already used by the crowd-trace merger's real-crowd test ([page](../tools/crowdmerge.md)), so nothing here is a held-out result.

## Why

The merger's real-crowd and mixed-crowd tests failed because villa's tracer (`vc_grow_seg_from_seed`) left the seeded sheet over about half of each trace. Its loss weights are parameters (`snap_weight`, `normal_weight`, `straight_weight` and others, `GrowPatch.cpp` `LossSettings` at villa `e0bbb8b`), and no earlier note had swept them.

## Setup

The 7 seeds per winding of [the real-crowd amendment](../prereg/2026-10-25-crowdmerge-real-crowd-amendment-1.md), traced on the m7 prediction with its normal grids by `kit scroll2ink run --until trace --snap-seed --tracer-params JSON` (60 generations, 25 minute limit; villa `e0bbb8b` with the grid-cache and time-limit patches), one run per seed and setting on Hugging Face CPU Jobs. Every trace grew the full 60 generations (13,924 vertices). Each trace vertex is matched to the hand trace along its normal: "on sheet" within 4 voxels, "neighbour" more than 10 voxels off (neighbouring windings lie about 15 to 21 voxels away here). Rings are grid steps from the seed vertex.

## Result (Model output, 14 traces per setting)

| Setting | On sheet | Neighbour | On sheet, rings 0 to 9 | Neighbour, rings 30 to 69 |
| --- | --- | --- | --- | --- |
| villa defaults (snap 0.1, normal 10, straight 0.2) | 39.5 % | 33.6 % | 56.8 % | 37.0 % |
| defaults, the real-crowd runs again | 40.3 % | 33.2 % | 57.4 % | 36.6 % |
| straight 1 | **42.3 %** | **31.0 %** | 60.8 % | 34.8 % |
| straight 3 | 41.2 % | 32.0 % | 60.0 % | 35.7 % |
| straight 10 | 35.9 % | 37.2 % | 55.4 % | 41.9 % |
| snap 1 | 34.7 % | 41.3 % | 46.2 % | 43.4 % |
| snap 0.01 | 21.6 % | 49.5 % | 29.2 % | 52.6 % |
| normal 30 | 28.7 % | 45.4 % | 42.6 % | 48.3 % |
| normal 3 | 29.0 % | 47.1 % | 45.6 % | 49.9 % |
| straight 1, snap 1 | 34.7 % | 41.5 % | 47.8 % | 43.9 % |
| straight 3, normal 3 | 32.0 % | 43.3 % | 48.4 % | 46.0 % |

## What it shows (Interpretation)

villa's default weights are close to the best of these: every change to the snap or normal weight, up or down, made traces leave more. A stiffer surface (straight 1 to 3) helps by 2 to 3 points, against a repeat-to-repeat difference of about 1 point, which does not change the picture: about a third of each trace still ends on a neighbouring winding, and even within 10 grid steps of the seed only about 60 % sits on the sheet. Loss weights do not fix the leaving; it comes from what the tracer reads (the m7 prediction and its normals at touching sheets), the problem the touching-sheets work targets. Untested ideas: villa's reference-surface clearance term (`reference_ray_weight`, which keeps a trace a set distance from a given surface, such as an already traced neighbour), and villa's neural tracer.

The sweep's Jobs cost about 0.12 USD (cheap CPU flavor).
