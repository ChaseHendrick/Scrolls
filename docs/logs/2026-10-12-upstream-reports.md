# 2026-10-12: findings reported upstream to villa

On 12 October 2026 three findings from this work went public on [ScrollPrize/villa](https://github.com/ScrollPrize/villa), from ChaseHendrick's account, and a draft fix for the first one followed the same day. This note records what was posted, where, and with which numbers, and what each one does and does not show. The numbers are the ones in the posts. No ink model output is involved, nothing here is about a target scroll, and no render or scroll image is committed here.

| What | Where | State when checked, 12 October 2026 |
| --- | --- | --- |
| Issue: VC3D caches any HTTP 404 as a missing chunk, so a transient 404 becomes permanent zeros in renders and traces | [villa #2058](https://github.com/ScrollPrize/villa/issues/2058) | open; draft fix #2060 linked |
| Draft PR: Don't cache an unconfirmed S3 404 as a missing chunk ("Fixes #2058") | [villa #2060](https://github.com/ScrollPrize/villa/pull/2060), branch `ChaseHendrick:fix-unconfirmed-s3-404` | draft; a maintainer review requested; no review yet |
| Issue: `vc_grow_seg_from_seed` does not hold the explicit seed, so a trace can drift to the next winding while `meta.json` still records the seed | [villa #2059](https://github.com/ScrollPrize/villa/issues/2059) | open; no comments |
| Comment: a CT check at the PHerc1667 transform's landmarks | [villa #1843, comment](https://github.com/ScrollPrize/villa/issues/1843#issuecomment-6130119937) | posted |

Receipts for #2058 and #2060: [`docs/evidence/2026-10-12-false-404/`](../evidence/2026-10-12-false-404/README.md). The relay that replays the false 404: [`scripts/false404/fault_relay.py`](../../scripts/false404/fault_relay.py), with tests in `tests/test_false404_relay.py`.

## 1. A transient 404 becomes a permanent hole of zeros (#2058, #2060)

**What happened (measurement, 8 October 2026).** From one cloud machine, the open-data bucket answered `404` with S3's own headers (`Server: AmazonS3`, an `x-amz-request-id`) and the body `<Code>NoSuchBucket</Code>` for keys it holds: 102 of 316 GETs at 32 workers, 16 of 80 at 1 worker, 19 of 60 separate curl processes, 0 of 60 requests on one reused connection and 0 of 1,580 HEAD requests. A genuinely absent key answers `NoSuchKey`. It could not be reproduced on 12 October (40 of 40 fresh ranged GETs were fine), and the cause is unknown; the machine's egress proxy is a possibility (Interpretation).

**Why it matters.** VC3D (villa `e0bbb8b`, and unchanged on `main` at `25f3c93`) treats any 404 as "this key does not exist", writes an empty marker into its persistent remote cache and serves that chunk as zeros in later runs without asking the server again. A fresh 256 x 256 crop render of PHerc0139 w035 got 4 empty markers and 27.7 % zero samples, with exit code 0 and no warning, and rerendering did not help. Deleting the 8 false markers brought zeros down to 0.03 % and the render matched an earlier clean render bit for bit. The issue cites the code paths by file and line. Missing chunks rendering as zeros is intended behaviour in villa, which is why the cache must be sure a chunk is missing before it says so; on scroll data a hole of zeros looks like blank papyrus.

**The fix (#2060, draft).** A 404 from an S3 origin counts as missing only with a complete `NoSuchKey` error; an unconfirmed one is retried on a fresh connection and, if it never clears, reported as a fetch error instead of being cached. A real `NoSuchKey` is still cached as missing, and plain HTTP servers and SFTP keep their 404 behaviour. On villa `main` at `25f3c93`, on Linux and on macOS:

| Check | With the fix | `main` |
| --- | --- | --- |
| `test_http_s3_missing` (new) | 15 test cases pass | 65 checks fail |
| `test_s3_chunk_cache` (new) | 3 test cases pass | 5 checks fail |
| w035 crop, 6 false 404s replayed | 0 empty markers, 0.03 % zeros, same as the clean render | 12 markers, 19.18 % zeros |
| Rerender on that cache, no false 404s | same as the clean render | 12 markers, 19.18 % zeros |

**Controls and limits.** The clean render on the same machine is the reference; the unchanged build must show the holes, and it does. False 404s do not happen on demand, so the renders replay them through a local relay that answers the first GET of a fixed 30 % of chunk keys exactly as S3 answered (6 keys on this crop) and passes everything else through; the issue's own measurements were live. Markers already in users' caches stay wrong, and the fix was not tested in the VC3D GUI or against a remote SFTP server. On macOS, `test_sftp_fetch` fails the same 4 checks with and without the fix. The fix is a draft PR, not merged. Related: [#1809](https://github.com/ScrollPrize/villa/issues/1809) and [#1846](https://github.com/ScrollPrize/villa/issues/1846), fixed by [#1817](https://github.com/ScrollPrize/villa/pull/1817) and [#1847](https://github.com/ScrollPrize/villa/pull/1847), are about a failed fetch crashing the renderer or tracer, not about a failed fetch being cached as a missing chunk.

## 2. The tracer does not hold an explicit seed (#2059)

**Measurement.** villa `e0bbb8b`, `vc_grow_seg_from_seed -s 4201.0 3186.0 4602.0` on PHerc0139 scan `20250728140407` (9.362 um) with the published surface prediction `20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr`. The seed is 1.1 voxels from the nearest vertex of the published winding w031 and 24.5 from w033. After the first step (10 generations) none of the 324 vertices is on w031: 265 are on w033, 58 on no winding and 1 unscored. All four seed-quad vertices are on w033, 76 to 97 voxels from the seed, and the nearest surface vertex to the seed is 25.3 voxels away. `meta.json` still records the input seed. A 60-generation run from the same seed is also mostly on w033. The issue cites the solver lines in `GrowPatch.cpp`, unchanged on `main` at `25f3c93`.

**An opt-in anchor, described in the issue.** One vertex is held fixed at the explicit seed in every Ceres solve and checked through growth, resume and output. Same seed, 10 generations (8 threads, 0.114 cm² when anchored):

| Run | Vertices | On w031 within 4 voxels | Switch edges | Seed kept |
| --- | ---: | --- | ---: | --- |
| Unanchored (villa's behaviour) | 324 | 0 of 324 (265 on w033) | n/a | no, nearest vertex 25.3 voxels away |
| Anchored | 324 | 0.9907 | 0 | yes, a vertex exactly at the seed |
| Anchored, cropped and resumed 5 more | 169 | 0.9941 | 0 | yes |

Same seed, 60 generations, 2 threads:

| Run | Area | Dominant winding, share within 4 voxels | Area on w031 within 4 voxels |
| --- | ---: | --- | ---: |
| Unanchored (villa's behaviour) | 4.88 cm² | w033, 0.511 | 0 |
| Anchored | 4.88 cm² | w031, 0.972 | 4.74 cm² |

The anchored 60-generation trace has no transverse self-crossings and 30 switch edges out of 26,612, all where w031 touches a neighbour, and its anchor is still exactly on the seed. It took 1,635 s against 960 s unanchored; whether the anchor or the machine accounts for that is not known.

**Controls and limits.** Each vertex is assigned to the nearest published PHerc0139 winding (w023 to w040 loaded) within a distance cut-off. A seed on w027 classifies as w027, and the nearest w033 vertex to this seed classifies as w033. This compares a trace with the published windings; it does not prove sheet identity on its own. It is one seed on one scroll, and PHerc0139 is a development scroll with published windings, so it shows the tracer's behaviour, not how often drift happens elsewhere. An anchor holds one point, not the sheet: from another seed a long trace could still wander later. The anchor change is not public as code yet. Related: [#1675](https://github.com/ScrollPrize/villa/issues/1675), [#1877](https://github.com/ScrollPrize/villa/issues/1877), [#2047](https://github.com/ScrollPrize/villa/pull/2047) and [#1906](https://github.com/ScrollPrize/villa/pull/1906) check where a seed starts or whether a grown surface follows the prediction; #2059 is about the surface leaving the seed's own sheet.

## 3. The CT at PHerc1667's landmarks agrees with the landmarks, not the stored matrix (#1843 comment)

**Prior work.** kadenpool reported landmark misfits in [#1835](https://github.com/ScrollPrize/villa/issues/1835) (19 September 2026) and this transform in [#1843](https://github.com/ScrollPrize/villa/issues/1843) (20 September), with a proposed refit; neg-0 checked the refit on 6 October; [#1994](https://github.com/ScrollPrize/villa/pull/1994) proposes a landmark check when transforms are written. README finding 10 (7 October) measured the same misfit from the landmarks alone. What the comment adds is a check in the CT itself.

**Measurement.** Around each of the 6 landmarks, a 64-voxel cube of the 1.129 um scan `20260323082859` was carried through the published matrix onto the 2.399 um scan `20251217075048` and correlated with that scan at every shift up to 64 working voxels. A match had to stand 0.1 above the best correlation more than 6 voxels away. Swapping the landmark pairs is the control.

- 8 October, at 4.8 um: the CT offsets from the published matrix were 61.0, 73.7, 215.9, 43.8, 42.3 and 181.8 um, against landmark residuals of 60.2, 76.3, 212.5, 43.8, 41.9 and 181.4 um. The landmarks sit 3.3 to 5.7 um from where the CT puts their partners. Correlation at the published mapping was -0.27 to 0.52, against peaks of 0.85 to 0.95. Swapped pairs: 0 of 6 matched.
- 12 October, on the catalogue downloaded that day (`metadata.json` last modified 12 October 2026, 06:10 UTC), at 9.6 um: the matrix still misses its landmarks by up to 212.5 um while a refit fits them within 3.9 um; the landmarks sit a median 6.8 um from the CT's position; swapped pairs 0 of 6.
- The same check passes on two other stored transforms named in the comment (14 of 14 landmarks matched, median offset 13.4 um, on PHerc0139; 16 of 16, median 3.8 um), so it does not fail everywhere.

**Limits.** This supports the refit proposed in #1843; it does not say the landmarks are exact, only that the CT agrees with them within a few micrometres. The check's code is not public here. README finding 11 (renders that follow the refit) remains post hoc and needs its calibrated rerun.

## 4. Later fixes, 13 to 18 October: before and after

From 13 to 18 October three more fixes went up on villa, each as an issue first. villa's CONTRIBUTING asks a bugfix PR for a screenshot of the error (terminal or in the tool) and of the tool running without error afterward. The PR bodies give both as text; this section collects them in one place, with the commands, so a reviewer can check each one without opening five pages. The numbers and log lines are the ones in the PR bodies unless a later recheck is named. Nothing here is ink model output.

State, read 21 October 2026 at about 06:30 UTC (Sourced fact: each PR's page on villa, and `git ls-remote` and `git merge-tree` on a villa clone): villa `main` is `d1b95150e` (#2183, 20 October); the newest PR is #2185. #2060, #2063 and #2079 are open and ready for review; #2081 and #2136 are drafts; none is merged. Every head merges textually onto `d1b95150e`; a textual merge is not a rebuild.

| PR | Issue | What changes | Last run on real data | Files the PR touches, changed on `main` since its base |
| --- | --- | --- | --- | --- |
| [#2060](https://github.com/ScrollPrize/villa/pull/2060) | [#2058](https://github.com/ScrollPrize/villa/issues/2058) | An S3 404 counts as a missing chunk only with `NoSuchKey` (section 1) | Tests on the merge with `d1b95150e` (head `6e02cfa`), 21 October: all 210 pass, and with `main`'s code the PR's two new tests fail 65 and 5 checks. Relay render with `main`'s renderer on `8aa507c`, 19 October; with the fix on `25f3c93`, 12 October | none (the head merges `d1b95150e`) |
| [#2063](https://github.com/ScrollPrize/villa/pull/2063) | [#2059](https://github.com/ScrollPrize/villa/issues/2059) | Opt-in `seed_anchor_xyz` (section 2) | 60 generations on PHerc0139 (section 2) | `GrowPatch.cpp` (6 lines, #2077, 13 October) and `core/test/CMakeLists.txt` (test targets added by other PRs, 13 and 20 October) |
| [#2079](https://github.com/ScrollPrize/villa/pull/2079) | [#2078](https://github.com/ScrollPrize/villa/issues/2078) | A local `metadata.json` with no `scan` record opens | `bcdf9bf`, 13 October | none |
| [#2081](https://github.com/ScrollPrize/villa/pull/2081) | [#2080](https://github.com/ScrollPrize/villa/issues/2080) | One warning when no loss reads the volume | `bcdf9bf`, 13 October | `GrowPatch.cpp` (6 lines, #2077, 13 October) |
| [#2136](https://github.com/ScrollPrize/villa/pull/2136) | [#2135](https://github.com/ScrollPrize/villa/issues/2135) | `zarr_tasks` pyramid levels use ceiling division | Shapes and VC3D tools on `1db9cd9`, 18 October; the new test rerun on `d1b95150e`, 21 October (below) | none |

### #2136: `vesuvius.zarr_tasks` makes pyramid levels one voxel short

Data: level 4 of PHerc1451 volume `20250521151225-8.640um-1.2m-116keV-masked.zarr` (1125 x 364 x 364), copied unchanged from the open-data bucket. Command: `vesuvius.zarr_tasks IN OUT --task recompress -n 2`. `zarr_tasks` sized each level with `round()`, which rounds half to even, so 1125 / 2 = 562.5 became 562.

Before (villa `main` `1db9cd9`, 18 October; Measurement):

```
level 1: (562, 182, 182)  ceiling (563, 182, 182)  SHORT
level 2: (281, 91, 91)  ceiling (282, 91, 91)  SHORT
$ vc_create_segment_mask plane_z562 rebuilt_main.zarr mask.tif --overwrite
Error processing volume: zarr level 1 shape [z,y,x]=(562, 182, 182) does not match synthesized dimensions from first found scale (slices=1125, height=364, width=364) in rebuilt_main.zarr
exit=1
```

After (the PR; Measurement):

```
level 1: (563, 182, 182)  ceiling (563, 182, 182)  OK
level 2: (282, 91, 91)  ceiling (282, 91, 91)  OK
$ vc_create_segment_mask plane_z562 rebuilt_fixed.zarr mask.tif --overwrite
Mask generated successfully at "mask_rebuilt_fixed.tif"
  Dimensions: [60 x 60]
  Valid pixels: 3600 / 3600 (100.0%)
exit=0
```

The image in the fixed mask equals the same plane read with numpy (largest absolute difference 0). `vc_grow_seg_from_seed` refused the short pyramid with the same level shape error. The bucket's own pyramid of this volume already has 563 at level 5, so the published pyramids are fine; the bug hits volumes rebuilt with `zarr_tasks`.

Rechecked 21 October 2026, about 02:00 UTC, on villa `main` `d1b95150e` (Measurement; Python 3.13.16, zarr 3.4.1, numpy 2.5.3, numcodecs 0.17.1). The PR's new test, `vesuvius/tests/image_proc/test_build_pyramid.py`, against `main`'s code: 3 failed, 1 passed (the passing case is the 4k + 3 shape, which was already right). With the PR merged onto `main` (tree `47342fc2`): 4 passed, and all 10 tests in `vesuvius/tests/image_proc` pass. The VC3D tools were not rebuilt for this recheck.

Reproduce the recheck (no scan data needed):

```bash
git clone https://github.com/ScrollPrize/villa && cd villa
git fetch origin pull/2136/head:pr-2136
python3 -m venv venv && . venv/bin/activate
pip install numpy zarr numcodecs tqdm pytest pynrrd opencv-python-headless requests pillow fsspec edt tifffile
git checkout pr-2136 -- vesuvius/tests/image_proc/test_build_pyramid.py
PYTHONPATH=vesuvius/src python -m pytest -q vesuvius/tests/image_proc/test_build_pyramid.py   # main's code: 3 failed, 1 passed
git checkout pr-2136 -- vesuvius/src/vesuvius/image_proc/run/zarr_tasks/utils.py
PYTHONPATH=vesuvius/src python -m pytest -q vesuvius/tests/image_proc/test_build_pyramid.py   # with the fix: 4 passed
```

The block was tested in a fresh venv on Python 3.13 on 21 October; another environment may need more of the `vesuvius` package's dependencies.

### #2079: a downloaded surface prediction will not open

Data: a local copy of the PHerc0139 surface prediction `20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr` (its `metadata.json`, headers and the level-0 chunks around the seed, copied unchanged). Command: `vc_grow_seg_from_seed -v <local copy> -s 3471 4155 4603`, 15 generations, 1 thread, `VC_GROWPATCH_RNG_SEED=7`, normal grids from the prediction's published `.normal-grids/`.

Before (villa `main` `bcdf9bf`, 13 October; Measurement):

```
$ vc_grow_seg_from_seed -v <local copy> -s 3471 4155 4603 ...
Error: metadata.json missing 'scan' key
```

After (Measurement):

| Build | `-v` | Result | `x/y/z.tif` sha256 (first 16) |
| --- | --- | --- | --- |
| `main` | local copy | `Error: metadata.json missing 'scan' key` | none |
| `main` | URL | 0.257 cm² | `807140f13c275e0a` |
| the PR | local copy | 0.257 cm² | `807140f13c275e0a` |

42 of the 43 stores under `representations/predictions/surfaces/` on the open-data bucket have this `metadata.json` layout (checked 13 October). `test_volume_local` gains one test case; all 18 pass with the PR, and the new one fails with `main`'s `Volume.cpp`. Neither file the PR touches has changed on `main` since, so the result should still hold on `d1b95150e` (Interpretation; not rerun).

### #2081: a trace without normal grids ignores the volume, with no warning

Data: the same PHerc0139 surface prediction, with no `normal_grid_path`. Command: `vc_grow_seg_from_seed -s 3471 4155 4603`, 60 generations, 1 thread, `VC_GROWPATCH_RNG_SEED=7`.

Before (villa `main` `bcdf9bf`, 13 October; Measurement): the run exits 0 with a normal-looking area and no warning. Only 0.12 of its vertices are on the predicted sheet, against 0.83 with the grids, and its `x/y/z.tif` are byte for byte those grown on an all-zero copy of the prediction.

After (Measurement): the same run prints, once, before growth:

```
WARNING: no normal_grid_path given, and no other loss that reads the volume is enabled. The surface will be shaped by spacing and smoothness only and will not follow the surface prediction. Pass normal_grid_path (a published prediction's .normal-grids folder, or a folder holding normal-grids-remote.json; see docs/extending_and_modifying_segmentations.md).
```

| Run | Generations | Warning | `x/y/z.tif` sha256 (first 16), `main` | same, the PR |
| --- | ---: | --- | --- | --- |
| prediction, no grids | 60 | yes | `0693e7fbf82fbd73` | `0693e7fbf82fbd73` |
| all-zero copy, no grids | 60 | yes | `0693e7fbf82fbd73` | `0693e7fbf82fbd73` |
| prediction, published grids | 15 | no | `807140f13c275e0a` | `807140f13c275e0a` |

No test, since the change is one log line; the table checks that the output does not change.

### Limits

All of this is our own work on our own machines; no maintainer or other user has rerun it. Each fix was measured on one scroll's data (PHerc0139 or PHerc1451). The before and after blocks are text copied from the run logs with local paths shortened, not screenshots. #2060 was rebuilt and its tests rerun on `d1b95150e`, but not its relay render; #2063, #2079 and #2081 were not rebuilt on `d1b95150e`.

## Not released

Only the four items in sections 1 to 3 went public on 12 October; section 4 adds three later fixes (13 to 18 October) and a recheck of 21 October. Nothing else from the private workbench was released, and these posts do not authorize further posting, submission or compute.
