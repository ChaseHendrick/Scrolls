# Amendment 1 to the real-crowd test: seeds the tracer accepts (25 October 2026)

Amends [the real-crowd preregistration](2026-10-25-crowdmerge-real-crowd.md). Written and committed before any trace of the test exists. Everything else is unchanged.

## What happened

The first tracer Job (seed (2105, 3900, 4017) on w027) stopped before tracing: the tracer's own seed check (Headless VC3D `seed_check`, as `trace` runs it) moved the seed 1 voxel onto the m7 prediction and then read the CT there as air (24 against a 30 to 148 box range), so the trace never started. Run locally on all 14 seeds, the same check passed 5 of 7 on w027 and 4 of 7 on w037 after the shift below: the hand traces often sit a few voxels off the bright papyrus that the check wants.

## New seed rule

`python scripts/crowdmerge/realcrowd.py seeds --agent DIR` (DIR: Headless VC3D v1.1.1, the version the Jobs run):

1. Candidates: 14 points on the same 3 mm circle around the same centre, at equal angles, the original 7 first and then the 7 between them; each is the nearest labelled vertex of the hand trace.
2. Each candidate moves along the hand trace's normal to the nearest whole-voxel offset, up to 6 voxels (the + side first on a tie), where `seed_check` passes against the m7 prediction and the CT. A candidate with no such offset is dropped.
3. The first 7 candidates that pass are the seeds.

Result (candidate index, shift in voxels, seed in level-0 voxels x, y, z):

- w027: 0 (+3) (2105, 3903, 4017); 1 (+5) (2263, 3952, 4280); 2 (+3) (2561, 3948, 4258); 4 (+3) (2699, 3966, 3835); 5 (+2) (2507, 3945, 3672); 7 (-6) (2176, 3920, 4170); 8 (+1) (2364, 3960, 4292)
- w037: 1 (-2) (2052, 3894, 7087); 3 (+4) (2265, 4235, 6934); 4 (-2) (2246, 4208, 6662); 5 (0) (2062, 4093, 6508); 7 (+6) (2010, 3815, 6974); 8 (-1) (2048, 4014, 7140); 10 (+1) (2298, 4224, 6795)

A shift of up to 6 voxels keeps a seed nearer A than its neighbours (about 15 to 21 voxels away here). Each Job runs `kit scroll2ink run --until trace` from its seed as before; the tracer may still move a seed onto the prediction (`--snap-seed`), and that is part of the result.
