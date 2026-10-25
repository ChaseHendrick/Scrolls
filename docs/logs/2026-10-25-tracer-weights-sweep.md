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

## Follow-up: keep clear of known neighbours (Model output, same 14 seeds)

villa's `reference_surface` term (occlusion and clearance residuals against a given tifxyz) was tried as a best case, with the hand traces of the neighbouring windings as references (`penalty_weight` 10, `min_clearance` 8, `clearance_weight` 1). villa takes one reference surface, and its nearest-point search finds only one sheet of a mesh that packs two, so a small local patch let the term take several surfaces (`reference_surface.extra_paths`), each with its own residuals. The share columns say which hand-traced winding each trace vertex lies on (within 4 voxels along that trace's normal); the rest lies between sheets.

| Setting | On sheet | Neighbour | w027 run on w026 / w027 / w028 / w029 | w037 run on w036 / w037 / w038 / w039 |
| --- | --- | --- | --- | --- |
| defaults | 39.5 % | 33.6 % | 24 / 28 / 32 / 0 % | 29 / 30 / 14 / 1 % |
| one neighbour (w026, w036), weight 1 | 42.1 % | | | |
| one neighbour, weight 10 | 42.7 % | 33.3 % | 9 / 36 / 37 / 0 % | 0 / 27 / 42 / 8 % |
| both neighbours in one mesh | 42.6 % | 30.7 % | 25 / 28 / 32 / 0 % | 20 / 36 / 19 / 1 % |
| both neighbours, patched | 25.3 % | 61.2 % | 3 / 7 / 12 / 34 % | 1 / 37 / 1 / 7 % |

Interpretation: the term does what it says, since the referenced windings empty out, but the trace does not return to its own sheet. With one neighbour barred it moves to the other; with both barred it crosses to the winding beyond (w027 onto w029) or floats between sheets (38 % of the w037 runs' area against 20 % with defaults). So exclusion moves the error instead of removing it, which again points at what the tracer reads at touching sheets, not at its losses. These runs and the patched build cost about 0.12 USD on cheap CPU Jobs.
