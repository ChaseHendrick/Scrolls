# Preregistration: Bucket Sentinel, planted-defect controls and blind rediscovery of the published bucket defects

**Status: Frozen** (4 November 2026, at the commit that fills section 4; written before any check of Bucket Sentinel had read a canvas, mesh or CT window of the Hugging Face `ink/` folders it is tested on). The back-test job starts after this commit and runs the code of this commit. Nothing in sections 2, 3, 5 and 6 may change after that commit except to record what happened, below the "Outcome" heading.

Tool: `python -m kit sentinel` ([page](../tools/sentinel.md), code `kit/sentinel.py`). Owner's decision to build it: 4 November 2026.

## 1. Question

Can one automatic checker, run on every new or changed upload of the organizers' public data, find again the silent defects that community members found by hand, without reading their answers?

- **Canvas offsets** (ScrollPrize/villa#2370, stantheman0128, 30 October 2026; Community report): HF65 canvases in `ink/` do not line up with the tifxyz in the same folder; offsets up to about 254 px on PHerc. Paris 4, varying linearly with position there; a constant offset of about one stored mesh cell elsewhere.
- **Truncated pyramids** (#2107, EhimenNathan, 15 October 2026; Community report): pyramid level 2 holds the first 17 of 65 depth slices while declaring z-scale 1, in 18 of 33 volumes.
- **Label grid** (#2369, stantheman0128, 30 October 2026; Community report): MAN5_outer_3's label zarrs are 59 px smaller than the canvas on both axes.
- **Silent unit scale** (#2137 and #2220, gaogao94; Community report) and **meshes from another frame** (#1845; Community report) are covered by planted controls only (section 3), since their published cases are either every store (the scale) or on data this test does not open.

## 2. Disclosure (what was seen before this file)

- The issue texts of #2370 (body and four comments, including the audit comment's grouping of 32 folders into misaligned, aligned and not measured, with offset ranges), #2369, #2107 and #1845, read on 4 November 2026 through a summarizing fetch. The reporters' shift tables, scripts and result files (`correct/`, `audit/`, `pyramid-repair/`) were not opened. So this is a rediscovery without the reporters' measurements as input, not a test by someone who has never seen the answer: the checker's method and every constant below were fixed on other data (section 3), and the bars here are taken from the idea's design notes, not from the reported values.
- From the back-test folders, only metadata was read during development: the bucket listings, every folder's `meta.json` (its bounding box, read to check the folder against the reserved-site registry), and the `.zattrs` and `.zarray` of three stores (one PHerc. Paris 4 canvas, the PHerc. 0841 w00 canvas, the MAN5_outer_3 ink label, whose shape is the #2369 defect). No chunk, mesh coordinate or CT window of any back-test folder was read.
- Development data: 20 open-data S3 segments of PHerc. 0343P, PHerc. 0814 and PHerc. 0009B, each a surface volume rendered from its own mesh (`docs/sentinel/dev-pool.json`), plus synthetic stores in `tests/test_sentinel.py`. None of them is in the back-test set.

## 3. Pass-first: the planted-defect controls (development data)

Each dev segment is checked as published (its base), then as in-memory copies with one planted defect each. Nothing is written to any bucket.

| Plant | Parameters | Must |
| --- | --- | --- |
| canvas shift | 4, 6, 10, 16, 25, 40, 64, 100, 150, 200, 250 and 300 px in seeded random directions (seed 20261104) | flag `canvas`, recover the shift |
| resampled canvas | scale 0.9, 0.95, 0.98, 1.02, 1.05, 1.1 (canvas size changes with it) | flag `canvas`, recover the drift |
| wrong frame | the mesh declared in another volume of the same scroll | flag `frame` as `wrong_frame` |
| label on another grid | label shape scaled 0.9 to 1.1 | flag `labels` |
| truncated level | level 2 to a quarter of its depth; level 1 to 20 planes | flag `pyramid` |
| blank planes | planes 10 and 11 of level 1; plane 40 of level 0 | flag `blank` |
| reset scale | the level-0 scale set to [1, 1, 1] with no unit on a store whose name states its pitch | flag `scale` |
| negatives | an unaltered label of the canvas's size; the scale set correctly in micrometers; every base canvas (a render from its own mesh) | must not flag |

Each segment gets 3 of the 19 image plants (rotating through the list) and every metadata plant. Bars, all on the dev pool together:

- recall over every must-flag plant at least 95 percent;
- for shift and resample plants, the median error of the offset model at the accepted windows (against truth = the base model moved by the plant) at most 2 px in at least 95 percent of caught plants;
- flags on negatives and bases together at most 5 percent.

A failed bar means the back-test does not run: report it and redesign. The bars do not move.

## 4. Dev runs (filled at the freeze)

- **Attempt 1** (4 November 2026, commit `09fd9b9`, Hugging Face CPU Job, 179 s): FAIL, as a smoke should when the code is wrong. Shifts and resamples were caught with errors of 0.05 to 0.73 px and the wrong-frame plant was caught, but three faults showed: a blank plane at level 0 was never caught (level 0 was its own reference), the correct-scale negative flagged on every segment (the plant multiplied an already correct scale by the pitch again), and four of six shards stopped on meshes whose cells span several voxels (a window spanned more CT than the reader allows). Fixed in commit `9fcc215` (interior blank planes count at every level; the plant sets the scale relative to level 0; the CT level follows the mesh's stretch, and a window that still spans too much is skipped and recorded). No bar or constant changed.
- **Attempt 2** (4 November 2026, commit `9fcc215`, Hugging Face CPU Job, 173 s; Model output): PASS. 20 pool segments, 252 must-flag plants, recall 0.988 (249 caught): every shift (36), wrong frame (3), label grid (108), truncated level (36), blank plane (36) and reset scale (18) plant was caught; 12 of 15 resampled canvases were caught and 3 (scale 1.05 and 1.1 on two of the smaller canvases) read not measured. Shift and resample errors: median 0.34 px, 100 percent of caught plants within 2 px. Negatives and bases: 0 flags of 56. 18 of 20 base canvases read aligned (median offsets about +0.4 px on both axes, the renderer's half pixel) and 2 read not measured (too few windows on two stretched PHerc. 0814 meshes); not measured counts as no flag. The pass-first rule is met, so the back-test of section 5 runs once.

## 5. Back-test (live data, run once after the freeze)

- **Set.** Every segment folder under `ink/` in the Hugging Face bucket `scrollprize/datasets` as of the run, minus the folders our reserved-data rule keeps closed (checked with the workbench's test-site registry; they are never opened and are reported only as a count). The set has 14 folders; the sorted list of item ids has sha256 `a17410c2e8500e2e105a4fff15c01a308aee7494b7c3d59626ea034354b54d45`. The reference labels, transcribed from the issue texts of section 1 for these 14 folders before any check ran on them, have sha256 `9f5992ad64ec0dd776624a32a480696d96f4c0ea64562a1022e440c7a172ef61`. Both files are kept in the workbench and published with the outcome.
- **Run.** `kit sentinel check ITEM ... --image` with the constants of `kit/sentinel.py` at the freeze commit, on a Hugging Face CPU Job (`scripts/sentinel/job.sh check`).
- **Counted.** A folder is flagged for a defect class when its check of that class has verdict `defect`: `canvas` (any model other than aligned), `pyramid` (`missing_slices` on z), `labels` (`label_shape`). A folder whose canvas is "not measured" counts as not flagged.

Bars (each from the idea's design: at least 80 percent of the non-excluded known cases, at most 10 percent flags on the folders the reporters found correct):

| Bar | Reference rows in the set | Pass |
| --- | --- | --- |
| B1 canvas offsets (#2370) | 9 misaligned | at least 8 flagged |
| B2 canvas false flags (#2370) | 4 aligned | none flagged |
| B3 truncated pyramids (#2107) | 5 affected, 9 not affected | at least 4 of the 5 flagged, none of the 9 |
| B4 label grid (#2369) | MAN5_outer_3 | flagged, short by 59 and 59 px |

PASS needs all four. One folder of the 14 (its CT is not public, per #2370) is in no canvas bar. Reported, not decisive: each flagged folder's offset model against the values the issue text gives (a constant of about -19.6 px on both axes for the one-cell group; Paris 4 slopes near the canvas-to-grid size ratio).

## 6. What a result means

A PASS says the checker finds these defect classes on this bucket version without the reporters' tables; it says nothing about defects of other kinds, or about the folders it did not open. A FAIL is recorded as such, with the misses. The offset table it writes is a data correction for training loaders, not a reading of any scroll; no ink map is made or scored here.

## Outcome

### Back-test, 4 November 2026 (run once; Hugging Face CPU Job, code at commit `a7ecd62`; Model output)

**PASS: all four bars.** Numbers are copied from the per-folder results (`checks[].verdict`, `kind`, `median_offset`, `affine`, `problems`), archived with the job's log in the workbench.

| Bar | Result | Pass |
| --- | --- | --- |
| B1 canvas offsets | 9 of 9 misaligned folders flagged (8 Paris 4 `affine`, the PHerc. 0009B folder `constant`) | yes (at least 8) |
| B2 canvas false flags | 0 of 4 aligned folders flagged (the three PHerc. 0841 folders at about +0.45 px on both axes, MAN5_outer_3 at about -1.0 px, all within 2 px) | yes |
| B3 truncated pyramids | 5 of 5 affected flagged `missing_slices` on z; 0 of 9 others | yes |
| B4 label grid | MAN5_outer_3's three label zarrs flagged, each short by 59 and 59 px | yes |

The folder whose CT is not public read "not measured" (no candidate volume matched), as expected; its pyramid was flagged as #2107 reports.

Reported, not decisive (the issue texts' values are a Community report):

- PHerc. 0009B: constant offset (-19.20, -19.29) px, against about (-19.6, -19.6) in #2370.
- PHerc. Paris 4 w01_r15: slopes 0.00427 (rows) and -0.00388 (columns), against 0.004263 and -0.003876 in #2370; largest offset over the measured windows 231 px.
- The other seven Paris 4 folders: intercepts near (-21, +12) px where the mesh scale is 0.1 and near (-43, +23) px for the two at 0.05 (w05_4424, w07_1619), with slopes 0.0007 to 0.0011 and -0.0004 to -0.0007; #2370's audit comment gives about (-21, +12) and (-42, +23) for the same two groups. Affine residuals 0.08 to 0.19 px RMS, so no folder needed a per-region map.
- The offset table of the 13 measured folders is `docs/sentinel/offsets.json`.

Not claimed: anything about the folders the reserved-data rule kept closed, other defect kinds, or later bucket versions. The match to #2370 is agreement between two measurements of the same published files, not a check of the CT itself.

<<SWEEP>>
