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

## Not released

Only the four items above went public on 12 October. Nothing else from the private workbench was released, and these posts do not authorize further posting, submission or compute.
