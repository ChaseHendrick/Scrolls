# Job v8in1447-w00 (2026-10-07, CPU)

Youssef Nader's PHerc1447 fine-tune of v8in (`YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062` at
`2bf9f421862cda0ed41dcae6e8274c12e295d03a`, `model.safetensors` sha256
`4b28e153e0a631679c79b6c9b8e3e159108d75aeddc6fdea648708ffec5026b5`) and d9v2 on the PHerc0841 w00 crop
(rows 2624 to 3264, columns 2688 to 3328 of a 4220 x 4760 surface), scored with a 64 px edge left out,
labels at level 2, reverse map as the control. Everything below is model output on public labelled data,
not a reading.

## What ran

- Container: 4 CPUs, 15 GB, no GPU. Shared setup by `SMOKE=1 EXPECT_GPU=cpu SEGMENT=0841-w00 MODEL=v8in-1447 bash scripts/mac-w045.sh`,
  stopped after step 4 (data, checkpoints, venv, villa main plus PR #1865 at `6723ad158` were in place; its
  smoke v8in passes were not needed).
- `run.sh`: crop zarr and crop layers, d9v2 through villa PR #1865 (both directions), v8in-1447 forward
  stride 42 and reverse stride 64 at batch 4, then `score.py` (AUC, `hp_r`, ensembles) after each map,
  commit and push.
- d9v2: `d9v2_ft-012000.pth` from the v1.0 release of TAUIL-Abd-Elilah/pherc0826-first-letters-search,
  sha256 `50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966`.

**Scope change.** The README's job was forward s21, reverse s42 and forward s42. A message from the
coordinating session (11:12 UTC) cut it to about one hour: forward s42 as the main map, reverse s64, d9v2
and the ensemble as before. So there is no stride 21 map and no separate s42 reference.

## Timings (CPU, 4 cores)

| Map | Tiles | Seconds |
| --- | --- | --- |
| d9v2, both directions (81 patches each) | | 55 |
| v8in-1447 forward, stride 42 | 196 | 1444 (7.4 s per tile) |
| v8in-1447 reverse, stride 64 | 100 | 712 (7.1 s per tile) |

## Results (crop, inner 64, 84,484 labelled ink px)

| Map | AUC as stored | AUC reversed | hp_r | hp_r reversed | hp null max abs |
| --- | --- | --- | --- | --- | --- |
| v8in-1447 fwd s42 (control rev s64) | 0.8381 | 0.5932 | +0.0069 | -0.0137 | 0.0058 |
| d9v2 | 0.8994 | 0.5855 | +0.0154 | -0.0034 | 0.0132 |
| v8in-1447 + d9v2, mean | 0.8900 | 0.6021 | +0.0097 | -0.0141 | 0.0059 |
| v8in-1447 + d9v2, rank | 0.9065 | 0.6134 | +0.0115 | -0.0088 | 0.0070 |

Pipeline check: d9v2 forward 0.8994 matches the earlier CPU bar (0.8994) to four decimals.

## Observations (Interpretation, one crop only)

- v8in-1447 alone scores 0.838 on this unseen-scroll crop, below d9v2 (0.899) and above the `ink_9um`
  seed 42 bar on the same crop (0.806). Whether it beats its base v8in is up to the sibling job `v8in-w00`
  (same crop, base model at s21/s42); compare its stride 42 row, not stride 21.
- Its letter-scale score is weak: `hp_r` +0.0069 against a rolled-key null of 0.0058, so barely above
  the null, where d9v2 is +0.0154 against 0.0132.
- The rank ensemble raises pixel AUC above d9v2 alone (0.9065 against 0.8994) but lowers `hp_r`
  (0.0115 against 0.0154). The mean ensemble lowers both. So on this crop v8in-1447 adds pixel AUC in a
  rank ensemble without adding letter-scale signal; the gain may be blur-like agreement, which pixel AUC
  rewards.
- Reverse controls sit at 0.59 to 0.61, above 0.5 but well below forward; similar to d9v2's own control.

## Oddities

- `score.py` first passed the label level as the int 2; zarr 3 group lookups need the string key "2",
  so the first automatic scoring after d9v2 failed. Fixed and rescored; all numbers above come from the fixed script.
- The ensemble controls use the stride 64 v8in-1447 reverse map with the stride 42 forward map, so the
  forward and control maps of the ensemble differ in v8in stride as well as direction.
- No maps or weights are committed; they stay in `~/scrolls-work/job-v8in1447-w00/` in the container.
