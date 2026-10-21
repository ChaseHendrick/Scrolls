# umbilicus: find a scroll's winding center line in X-ray CT

`scripts/umbilicus/` finds a scroll's winding center in its 1.2 m scan with two U-Nets, writes the published JSON format with scan dimensions when available, and supports the `umbilicus.json` name used by VC3D and spiral-fitting; it also trains and scores the finder.

| Field | Value |
| --- | --- |
| Id | `umbilicus` |
| Status | Current |
| Kind | script folder |
| Area | Surfaces and tracing |
| Run | `python scripts/umbilicus/predict.py`, `python scripts/umbilicus/slices.py`, `python scripts/umbilicus/pipeline.py`, `python scripts/umbilicus/refine.py`, `python scripts/umbilicus/endcheck.py`, `python scripts/umbilicus/ctcheck.py`, `python -m kit.umbfind` (the finder on the scan VC3D has open, as the tool registry runs it) |
| Code | `scripts/umbilicus/`, `kit/umbfind.py` (VC3D and tool registry adapter), `kit/data/registry/umbilicus.json` (its tool registry manifest) |
| Tests | `tests/test_umbilicus.py`, `tests/test_umbfind.py`, `tests/test_toolreg_rowumb.py` |
| Needs | Python 3.10 or newer, numpy, scipy, requests; torch for `predict.py`, `centrenet.py`, `refine.py` and training; numcodecs only for `slices.extract` (the whole-chunk reader); matplotlib and Pillow for `ctcheck.py`. The released weights `umbilicus-first-all.pt` and `umbilicus-zoom-all.pt` (release `umbilicus-v1`) for `predict.py` |
| Runs on | `predict.py` runs on a CPU or an NVIDIA GPU (`--device cuda`; `mps` is untested). On 4 CPU cores the smallest published scan, PHerc1203, took about 13 minutes, 7 of them reading its slices ([guide](../../scripts/umbilicus/README.md#quick-start)). Training needs a GPU: about 162 to 253 s per first-stage job on a B300 and 46 to 76 s per zoom job on an L40S ([guide](../../scripts/umbilicus/README.md#reproduce-the-held-out-results)). `pipeline.py trim` on a synthetic 60-slice scroll took 0.6 s (measured 2026-10-16, 4-core cloud container) |
| Network | vesuvius-challenge-open-data.s3.amazonaws.com: HTTP range reads of level-3 planes (about 0.8 to 2.4 MB per slice, 0.25 to 0.65 GB per scroll), the scan's level-0 `.zarray` (a few hundred bytes, for the volume dimensions; not read again when the slice file holds `shape_l0`), level-5 planes and level-3 windows for `endcheck.py`, level-2 planes and level-1 and level-0 windows for `ctcheck.py`, bucket listings, and the three published umbilicus files. raw.githubusercontent.com: Alexey Drobkov's ten published lines at commit `DROBKOV_REV`, read for the 13 published scrolls (also when `predict.py` picks the scan of one of them). github.com: the weights, downloaded by hand with `curl`, or by `python -m kit.umbfind --download` into its run folder when they are not found |
| Writes | `predict.py`: `DATA/SCROLL.npz` (slices, when missing), `OUT/SCROLL_umbilicus.json` (or `OUT/SCROLL/umbilicus.json` with `--vc3d-name`) and `OUT/SCROLL_predict.json`. `slices.py extract`: `OUT/SCROLL.npz`. `pipeline.py`: `OUT/JOB.pt` and `OUT/JOB.json` (job), `OUT/result.json` and `OUT/umbilicus/` (collect), `DST/SCROLL_umbilicus.json` or `DST/SCROLL/umbilicus.json` (trim). `refine.py`: `refine_NAME.pt` and `.json` (chain), `refine_cv_fold<k>.pt` and `refine_cv.json` (cv), `result.json` and `umbilicus/` (chain-collect). `endcheck.py`: its cache (default `work/umbilicus/endcheck-cache`), the `--out` JSON, `DST/SCROLL_umbilicus.json` or `DST/SCROLL/umbilicus.json` (files). `ctcheck.py`: `OUT/SCROLL_ct_check.png`, `OUT/SCROLL/SCROLL_zZ.png`, `OUT/summary.json` and `OUT/.cache/`. `python -m kit.umbfind`: only inside `--out RUN`: `umbilicus.json`, `predict.json`, `predict.log`, `predict/`, `slices/` and, with `--download`, `weights/` |
| Go-ahead | Not needed to run `predict.py` on public scans. Needed before renting GPUs to train (the go-ahead rule, hard rule 8, and the Modal rule, hard rule 11), and before posting a line or uploading weights |
| Released | Public `main` since 2026-10-14 (`76e4591`); the 14 weight files are the GitHub release `umbilicus-v1` of this repository; in the README's "Released tools" as `umbilicus-finder`, since 2026-10-20 a line of the Scrolls kit entry (run from a clone like the kit commands, with its weights as a release of this repository) |
| Release id | `umbilicus-finder` |
| Guide | [Scroll center finder guide](../../scripts/umbilicus/README.md) (weights and their SHA-256, held-out results, end-point rule, reproduction, licenses) |
| License | Code: Apache 2.0 ([LICENSE](../../LICENSE)). Weights: CC BY-NC 4.0 ([guide](../../scripts/umbilicus/README.md#licenses-credits-and-citation)) |
| Checked | 2026-10-20 against commit `518556f` |

## What it does

Tools that trace and orient the papyrus sheets of a scroll use its umbilicus: the line of its winding center, one point per height. Many scrolls have none published, and people placing the same center by hand often disagree by a few millimeters. This folder finds the line automatically and measures its error against the 13 published lines.

`predict.py` reads every 8th plane of pyramid level 3 (8 times downsampled) of a scroll's 1.2 m (about 9 um) scan from the open-data bucket, one slice every 64 level-0 voxels. A first U-Net (3.3 million parameters, `centrenet.py`) looks at three neighboring slices squeezed into a 256 pixel frame and puts a heatmap peak on the center, averaged over the 8 flips and rotations. A second U-Net of the same shape (the zoom stage, `refine.py`) looks at a 176 pixel level-3 window round that answer (12 to 13 mm across) and moves it onto the center, twice. The line is smoothed along the height, then two end trims drop heights where a center has nothing to sit on. The file it writes has control points `x`, `y`, `z` in level-0 voxels, as the published umbilicus files do, and, when the source grid is available, the scan's level-0 `volume_width`, `volume_height` and `volume_slices`, which VC3D uses to place the points on the volume it has open. With `--vc3d-name` the file is `OUT/SCROLL/umbilicus.json`, the name VC3D searches for and spiral-fitting reads (see "Use it in VC3D and spiral-fitting" under Outputs).

The other scripts make and check it: `slices.py` reads the slices and the published lines, `pipeline.py` trains and scores the first stage by fold and holds the trims and the file format, `refine.py` trains and chains the zoom stage, `endcheck.py` calibrates and applies the end-point rule, and `ctcheck.py` draws lines on CT slices for a person to check.

The line is model output, not a measurement: check it on CT slices before relying on it. On the 13 published scrolls the released `-all` models trained on every scroll, so a line for one of them is not a test; the held-out numbers come from models that never saw the scroll they scored. It does not trace sheets, and it takes only 8 to 10 um scans.

## When to use it

- A scroll with a 1.2 m scan in the open-data bucket and no published umbilicus, before tracing or orienting its sheets.
- A line for VC3D or a spiral fit: `--vc3d-name` writes `SCROLL/umbilicus.json`, stamped with the scan's grid when available.
- A second opinion on a published or hand-made line: draw both on CT with `ctcheck.py`.
- Trimming the mount and cap ends from umbilicus files already written (`pipeline.py trim`, `endcheck.py files`).
- Reproducing the held-out scores from public data (`slices.py`, `pipeline.py`, `refine.py`, `endcheck.py score`).

Do not use it:

- On scans finer or coarser than 8 to 10 um: `predict.py` refuses them; villa's `vc_gen_umbilicus` is another finder (the two have not been compared on the same slices).
- To check segment stacking against a line: use [`stackcheck`](stackcheck.md), which takes an umbilicus file.
- Inside AutoPipeline runs: [`autopipeline`](autopipeline.md) takes the catalog's file or villa's estimate, and accepts a file in the published format such as this one.
- As ground truth: a line from this finder is model output and its spread between models is not accuracy.

## Quick start

```bash
python -m pip install numpy scipy requests torch
U=https://github.com/ChaseHendrick/Scrolls/releases/download/umbilicus-v1
mkdir -p work/umbilicus/weights
for f in umbilicus-first-all.pt umbilicus-zoom-all.pt; do curl -fL -o work/umbilicus/weights/$f $U/$f; done
(cd work/umbilicus/weights && shasum -a 256 -c) <<'EOF'
c9b50aae2876e00f50b7ade5cf9a6facc84fb0f8ad9667dddf5565e5f06ae854  umbilicus-first-all.pt
0a06fe2e108fbb5f252455f93862336ec4013a535eb922676ae8f846406fb4bb  umbilicus-zoom-all.pt
EOF
python scripts/umbilicus/predict.py SCROLL \
    --first work/umbilicus/weights/umbilicus-first-all.pt --zoom work/umbilicus/weights/umbilicus-zoom-all.pt \
    --data work/umbilicus/slices --out work/umbilicus/out
```

- `SCROLL`: a scroll id as the bucket names it, such as `PHerc0125`. It needs a 1.2 m scan in the bucket stored as raw 128^3 uint8 chunks; give `--volume PATH` to pick one scan when there are several.
- The two weight files are about 13 MB each; the SHA-256 check must print `OK` for both.
- `work/` is ignored by git, so the weights and slices stay out of it.
- Add `--vc3d-name` to write `work/umbilicus/out/SCROLL/umbilicus.json` instead, the name VC3D and spiral-fitting look for.

It prints one line per scroll, `SCROLL {"points": ..., "keep_band": ..., "spread_mm_median": ..., "file": ...}`, and writes `work/umbilicus/out/SCROLL_umbilicus.json` (or `SCROLL/umbilicus.json`) and `SCROLL_predict.json`. It worked when the exit code is 0 and `points` is above 0. The compatibility checks use synthetic slices and fixed center predictions; they verify file naming and coordinate metadata, not model accuracy. No real-scan inference or live VC3D window was run for this update.

The end trims run offline. On the synthetic 60-slice scroll of `tests/test_umbilicus.py` (slices in `slices/S.npz` with its level-0 grid as `shape_l0`, its untrimmed line in `src/S_umbilicus.json`), `python scripts/umbilicus/pipeline.py trim src --data slices --out trimmed --vc3d-name` printed (19 October 2026):

```
{
 "S": {
  "points": 36,
  "z": [
   800,
   3040
  ],
  "file": "trimmed/S/umbilicus.json"
 }
}
```

Without `--vc3d-name` the file is `trimmed/S_umbilicus.json`, as before. Either way its metadata gains `volume_width` 2080, `volume_height` 1600 and `volume_slices` 3840, and `metadata.trimmed` reads `mount and cap slices dropped: kept the longest run with at least 0.3 of the median papyrus area, at least 3 mm inside the first and last slices with papyrus; end-point rule: dropped from each end until 2 mm of slices where at least 0.75 of 32 rays from the center meet papyrus within 4 mm`.

## Checks and controls

- **Held-out scoring with a control.** The 13 published lines were split into four groups by scroll on 13 October 2026 (`FOLDS` in `pipeline.py`); each group was scored by models trained on the other scrolls only. The control is the papyrus centroid of each slice, smoothed the same way. Over 3,414 held-out slices the median distance to the published line was 3.98 mm for the centroid, 1.20 mm for the first stage and 0.73 mm for both stages (90th percentile 9.97, 4.00 and 3.37 mm); the first stage beat the centroid on 13 of 13 scrolls (`umbilicus_checks` in [`results.json`](../results.json), [guide](../../scripts/umbilicus/README.md#held-out-results)).
- **Rules fixed before each run** (13 October 2026): the first stage works if its pooled held-out median is at most 2.0 mm and it beats the centroid on at least 10 of 13 scrolls; the zoom stage is adopted if its pooled median is at least 0.1 mm lower and it is not worse on at least 9 of 13. Both passed. The plan that holds the rules is not published, so the timing cannot be checked from here.
- **With the end trims.** Both trims keep 3,243 of the 3,414 scored slices, median 0.69 mm for both stages; the dropped slices were mostly worse than the rest (9 of 10 scrolls) ([`heldout-endrule.json`](../evidence/2026-10-14-umbilicus/heldout-endrule.json)). `endcheck.py score RUN_DIR` reproduces this from a run; its `pooled.all` must first equal the run's own `result.json`.
- **Limits.** The reference is one person's line per scroll (ten of 13 by one annotator), people disagree by more than this error, two scrolls have more than one winding center, and the settings were chosen while looking at some of the same scrolls, so it is not an untouched test set ([guide](../../scripts/umbilicus/README.md#read-these-numbers-with-care)). `spread_mm_median` measures agreement between models, not accuracy.
- **A person's check.** `ctcheck.py` draws a line (red) beside another (cyan) on whole and zoomed CT slices; nothing replaces looking at them.
- **VC3D reads the file.** The tests read every written file back through rule-for-rule copies of VC3D's reader (`Umbilicus::LoadJsonFile`), its file-name search and its rescale rule at villa main `8aa507c12`; the copies refuse a partial triplet, a float or zero dimension, an empty `volume` and a file without points, and agree with villa's own tests of the rescale. They are copies: no VC3D binary was built or opened for this page.

Claim label: Model output, for every line `predict.py` writes and for the held-out distances of 13 October 2026, scored against one person's published line per scroll.

## Commands and options

### `python scripts/umbilicus/predict.py`

The center line of any scroll from trained weights: no training, no labels.

```
usage: predict.py [-h] --first FIRST [FIRST ...] [--zoom [ZOOM ...]]
                  --data DATA --out OUT [--volume VOLUME] [--device DEVICE]
                  [--no-end-rule] [--vc3d-name]
                  scrolls [scrolls ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `scrolls` | required | One or more scroll ids, such as `PHerc0125` |
| `--first FIRST [FIRST ...]` | required | First-stage weights (`centrenet.Net` state dicts); the median of several models is taken |
| `--zoom [ZOOM ...]` | none | Zoom-stage weights; each moves the first-stage guess, and the median is taken. Without it only the first stage runs |
| `--data DATA` | required | Folder of slice files `SCROLL.npz`, made here when missing |
| `--out OUT` | required | Folder for `SCROLL_umbilicus.json` (or `SCROLL/umbilicus.json`) and `SCROLL_predict.json` |
| `--volume VOLUME` | none (`slices.volume()`: the published line's scan, else the scroll's 1.2 m scan) | Bucket path of the scan to use, one scroll only; its name must give a voxel size from 8 to 10 um (`UM_RANGE`) |
| `--device DEVICE` | `cpu` | Torch device; `cuda` for an NVIDIA GPU (bfloat16 autocast off the CPU) |
| `--no-end-rule` | off | Trim mount and caps only, without the end-point rule |
| `--vc3d-name` | off | Write `OUT/SCROLL/umbilicus.json`, the name VC3D and spiral-fitting look for, instead of `OUT/SCROLL_umbilicus.json` |

### `python scripts/umbilicus/slices.py`

```
usage: slices.py [-h] --out OUT {extract} [scrolls ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `cmd` | required | `extract`: write the slice file of each scroll by range reads (`extract_ranged`), with the scan's level-0 shape as `shape_l0`; an existing file is skipped |
| `scrolls` | none (the 13 published scrolls) | Scroll ids |
| `--out OUT` | required | Folder for `SCROLL.npz` |

### `python scripts/umbilicus/pipeline.py`

First-stage training by fold, its held-out score, and trimming written files.

```
usage: pipeline.py [-h] --data DATA --out OUT [--size SIZE] [--width WIDTH]
                   [--epochs EPOCHS] [--time-s TIME_S] [--batch BATCH]
                   [--device DEVICE] [--no-end-rule] [--vc3d-name]
                   {job,collect,trim} [job]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `cmd` | required | `job` (train one model and predict its held-out scrolls), `collect` (average seeds per fold, score against the published lines and the centroid control, write `result.json`), `trim` (drop end points from files already written and stamp the scan's volume dimensions). Any other word is refused with a usage error, exit code 2 |
| `job` | none | For `job`: `fold<k>s<seed>` (k from 0 to 3) or `alls<seed>`. For `trim`: the source folder of `SCROLL_umbilicus.json` or `SCROLL/umbilicus.json` files; each keeps its own name unless `--vc3d-name` is given |
| `--data DATA` | required | Folder of slice files |
| `--out OUT` | required | Run folder (job, collect), or the destination folder (trim) |
| `--size SIZE` | `256` | First-stage frame side in pixels |
| `--width WIDTH` | `32` | Channels of the U-Net's first block |
| `--epochs EPOCHS` | `40` | Training epochs (the release used 60) |
| `--time-s TIME_S` | `900` | Training time cap in seconds (the release used 300) |
| `--batch BATCH` | `32` | Batch size |
| `--device DEVICE` | `cpu` | Torch device |
| `--no-end-rule` | off | `trim`: mount and caps only, without the end-point rule |
| `--vc3d-name` | off | `collect`, `trim`: write `SCROLL/umbilicus.json`, the name VC3D and spiral-fitting look for, instead of `SCROLL_umbilicus.json` |

### `python scripts/umbilicus/refine.py`

The zoom stage: a check from offset published centers (`cv`), training on top of first-stage answers (`chain`), and its held-out score (`chain-collect`).

```
usage: refine.py [-h] [--base BASE] --data DATA --out OUT
                 [--folds FOLDS [FOLDS ...]] [--epochs EPOCHS] [--width WIDTH]
                 [--rounds ROUNDS] [--time-s TIME_S] [--device DEVICE]
                 [--every EVERY] [--side SIDE] [--reach REACH]
                 [--offsets OFFSETS [OFFSETS ...]] [--vc3d-name]
                 {cv,chain,chain-collect} [name]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `cmd` | required | `cv`, `chain` or `chain-collect` |
| `name` | none | For `chain`: `fold<k>` (trains without fold k's scrolls) or `all` |
| `--base BASE` | none | `chain`: the first-stage run folder whose answers are refined |
| `--data DATA` | required | Folder of slice files |
| `--out OUT` | required | Run folder |
| `--folds FOLDS [FOLDS ...]` | `0 1 2 3` | `cv`: folds to train and score |
| `--epochs EPOCHS` | `12` | Training epochs (the release used 30 with `chain`) |
| `--width WIDTH` | `16` | Channels of the U-Net's first block (the release used 32) |
| `--rounds ROUNDS` | `2` | Times each guess is re-cropped and moved |
| `--time-s TIME_S` | none (no cap) | Training time cap in seconds (the release used 300) |
| `--device DEVICE` | `cpu` | Torch device |
| `--every EVERY` | `1` | `cv`: score every Nth annotated slice |
| `--side SIDE` | `176` | Crop side in level-3 pixels (`S`) |
| `--reach REACH` | `64` | Largest training offset in level-3 pixels (`R`) |
| `--offsets OFFSETS [OFFSETS ...]` | `0.0 1.2 2.5` | `cv`: median sizes in mm of the smooth random offsets added to the published centers |
| `--vc3d-name` | off | `chain-collect`: write `umbilicus/SCROLL/umbilicus.json`, the name VC3D and spiral-fitting look for, instead of `umbilicus/SCROLL_umbilicus.json` |

### `python scripts/umbilicus/endcheck.py`

```
usage: endcheck.py [-h] [--cache CACHE] [--data DATA] [--out OUT]
                   [--radius RADIUS] [--vc3d-name]
                   {calibrate,score,files} [args ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `cmd` | required | `calibrate` (the rule at the 13 published centers), `score` (the rule on a run's held-out answers, one stage per folder), `files` (apply the rule to written `SCROLL_umbilicus.json` or `SCROLL/umbilicus.json` files, each kept under its own name, and stamp the scan's volume dimensions) |
| `args` | none | `score`: `RUN_DIR`; `files`: `SRC DST` |
| `--cache CACHE` | `work/umbilicus/endcheck-cache` | Cache of bucket reads |
| `--data DATA` | none (bucket reads) | The pipeline's slice files instead of bucket reads |
| `--out OUT` | none | Write the result JSON here |
| `--radius RADIUS` | none (`END_RADIUS_MM`, 4 mm) | `calibrate`: try this radius in mm instead |
| `--vc3d-name` | off | `files`: write `DST/SCROLL/umbilicus.json`, the name VC3D and spiral-fitting look for |

### `python scripts/umbilicus/ctcheck.py`

```
usage: ctcheck.py [-h] --a A --b B --out OUT [--scrolls [SCROLLS ...]] [--n N]
                  [--cache CACHE] [--a-label A_LABEL] [--b-label B_LABEL]
                  [--zoom-mm ZOOM_MM] [--close-mm CLOSE_MM]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--a A` | required | Folder of the lines to check (`SCROLL_umbilicus.json` or `SCROLL/umbilicus.json`), drawn as red circles |
| `--b B` | required | Folder of the lines to compare with (either name), drawn as cyan crosses |
| `--out OUT` | required | Folder for the pictures and `summary.json` |
| `--scrolls [SCROLLS ...]` | none (every file in `--a`) | Scroll ids to draw |
| `--n N` | `6` | Slices spread along the line, plus the height where A and B differ most and where A moves fastest sideways |
| `--cache CACHE` | none (`OUT/.cache`) | Cache of plane reads |
| `--a-label A_LABEL` | `centers A` | Legend label of A |
| `--b-label B_LABEL` | `centers B` | Legend label of B |
| `--zoom-mm ZOOM_MM` | `6.0` | Half width in mm of the level-1 zoom panel |
| `--close-mm CLOSE_MM` | `2.0` | Half width in mm of the level-0 close-up panel |

`centrenet.py` has no command line; the other scripts import it.

### `python -m kit.umbfind`

```
usage: python -m kit.umbfind [-h] --out OUT [--first FIRST] [--zoom ZOOM]
                             [--weights WEIGHTS] [--download] [--no-end-rule]
                             [--json]
                             volume
```

| Option | Default | Meaning |
| --- | --- | --- |
| `volume` | required | the scan: its open-data bucket URL, bucket key, or a local copy under the bucket's layout (`SCROLL/volumes/SCAN.zarr`); another location is refused |
| `--out OUT` | required | the run folder: `umbilicus.json`, `predict.json`, `predict/`, `slices/` |
| `--first FIRST` | none | first-stage weights to use instead of the released file (recorded, not pinned) |
| `--zoom ZOOM` | none | zoom-stage weights to use instead of the released file (recorded, not pinned) |
| `--weights WEIGHTS` | none | a folder holding the released `umbilicus-first-all.pt` and `umbilicus-zoom-all.pt` |
| `--download` | off | fetch a missing released weight file into `OUT/weights` (checked against the release's SHA-256) |
| `--no-end-rule` | off | trim mount and caps only, without the end-point rule |
| `--json` | off | accepted; the summary is always JSON |

It prints one JSON summary (`scroll`, `key`, `voxel_um`, `weights` with each file's SHA-256 and `pinned`, `points`, `umbilicus`, `claim`). Exit code 0 when the line has points; 1 when the finder failed or kept no point (no `umbilicus.json` is written then, because VC3D refuses an umbilicus without points); 2 for a refused volume (not in the bucket, or outside 8 to 10 um), missing weights or a bad argument. `KIT_CENTRENET_PREDICT` names another `predict.py` (the variable AP's `centrenet` backend reads).

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `DROBKOV_REV` | `de7642ac9b38266e95192489e22fb13b7e2d13b6` | Commit of Alexey Drobkov's herculaneum-umbilici whose ten lines `slices.truth()` reads; the held-out scores used this one |

## Python API

The scripts import one another by file name (each puts its folder first on `sys.path`). The functions other code uses:

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `predict.predict(s, first, zoom, data, out, device="cpu", end_rule=True, vol=None, vc3d_name=False)` | `{"points", "keep_band", "spread_mm_median", "file"}` | `SystemExit` for a scan outside 8 to 10 um or a slice file of another scan; `RuntimeError` from bucket reads | Writes both output files; `file` is the umbilicus file's path, or None when `vc3d_name` and no point was kept |
| `slices.extract_ranged(s, out, level=3, every=8, vol=None, threads=16)` | `out` | `RuntimeError` for failed reads or no 1.2 m scan; `ValueError` for chunks that are not raw 128^3 uint8 or a malformed level-0 `.zarray` | The slice file: `ct`, `z_l0`, `vol`, `um`, `level`, `missing`, `chunks`, and `shape_l0` when the bucket has a level-0 `.zarray` |
| `slices.level0_shape(vol)` | `[z, y, x]` or None | `ValueError` when the shape is not three positive integers; `RuntimeError` from the read | One small read of the scan's level-0 `.zarray`; None when the bucket has none |
| `slices.PlaneReader(vol, level)` | Reader with `plane(z, y0=0, y1=None, x0=0, x1=None, threads=16)` and `missing` | As above | One 16 KiB range request per chunk; absent chunks read as 0 and are counted |
| `slices.truth(s)` | `(volume path, rows z, y, x in level-0 voxels)` | `RuntimeError` | A published line, cached per process |
| `slices.smooth_z(p, win=9)` | Smoothed `(n, 2)` array | Nothing of its own | Running median, then a quadratic Savitzky-Golay over 11 slices; NaNs filled first |
| `pipeline.keep_band(area, z, um, cap_mm=None, frac=None)` | bool array | Nothing | The mount and cap trim |
| `pipeline.end_trimmed_keep(ct, yx, z, um, keep, level=3)` | `(keep, support, papyrus_level)` | Nothing | The end-point rule |
| `pipeline.umbilicus_json(s, z, yx, keep, um, vol, spread, note, dims=None)` | dict in the published format | `ValueError` when `dims` is not all three of `volume_width`, `volume_height`, `volume_slices` as positive integers | See Outputs |
| `pipeline.volume_dims(vol, held=None, planes=None, level=3)` | `{volume_width, volume_height, volume_slices}` or `{}` | Nothing (an unreadable shape gives `{}` and a line on stderr) | The scan's level-0 grid from `held` (a slice file's `shape_l0`) or the bucket; `{}` when it does not downsample to `planes`; export paths verify the cache source matches the line before using its grid |
| `pipeline.write_umbilicus(j, out, s, vc3d=False)` | the path written, or None | `ValueError` for NaN or infinity | `OUT/s_umbilicus.json`, or with `vc3d` `OUT/s/umbilicus.json`; strict JSON, written atomically; a line with no points is not written under the VC3D name |
| `pipeline.umbilicus_files(src)` | `[(scroll, path, vc3d)]` | `SystemExit` for a scroll in both layouts | The umbilicus files in a folder, both names |
| `pipeline.stamp_dims(meta, dims, name)` | `meta` | `SystemExit` for a triplet of another grid, or a partial one with no scan shape | Puts the triplet into a file's metadata |
| `pipeline.trim(src, data, dst, end_rule=True, vc3d_name=False)` | `{scroll: {"points", "z", "file"}}` | `SystemExit` for points off the slice heights | What `pipeline.py trim` runs |
| `endcheck.files(src_dir, dst, cache, data=None, vc3d_name=False)` | `{scroll: {"points_in", "points_out", "papyrus_level", "file"}}` | `SystemExit` for points off the slice heights (with `data`) | Applies the end-point rule to any file in the published format |
| `bucket_key(volume)` (`kit/umbfind.py`) | `(scroll, key, voxel_um)` | `UmbfindError` for a location outside the bucket, a name without a voxel size, or a scan outside 8 to 10 um | A bucket URL (`https://` or `s3://`), a bucket key, or a local copy under `SCROLL/volumes/SCAN.zarr` |
| `find_weights(out, first=None, zoom=None, folder=None, download=False, env=None, opener=None)` | `{stage: {"path", "sha256", "pinned"}}` | `UmbfindError` for missing weights or a download whose SHA-256 differs | Explicit files as they are (not pinned), else the released files with the release's SHA-256 (`WEIGHTS`), else fetched into `OUT/weights` |
| `find(volume, out, first=None, zoom=None, weights=None, download=False, env=None, python=None, opener=None, end_rule=True)` | `(summary, exit code)` | `UmbfindError` as above | Runs `predict.py` (`KIT_CENTRENET_PREDICT`, else this checkout's) on the CPU into `OUT` and copies the line to `OUT/umbilicus.json` |
| `main(argv=None)` (`kit/umbfind.py`) | exit code | nothing | `python -m kit.umbfind` |
| `UmbfindError` (`kit/umbfind.py`) | exception | | A refused volume, missing weights or a bad argument (exit 2) |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Scan | A zarr v2 volume in the open-data bucket with raw (uncompressed) 128^3 uint8 chunks, levels 0 to 5 | 8 to 10 um voxels (the 1.2 m scans); the models trained on 8.64 and 9.362 um scans only. Absent chunks read as 0 (air) |
| Slice file | `SCROLL.npz` with `ct` (n, H, W) uint8 level-3 planes, `z_l0` (level-0 heights, 32 + 64 k), `vol`, `um`, `level`, and since 19 October 2026 `shape_l0` (the scan's level-0 [z, y, x]) | Made by `predict.py` or `slices.py extract`; 0.24 to 0.62 GB of reads on the 13 published scrolls. An older file without `shape_l0` still works: the level-0 `.zarray` is read instead |
| Weights | PyTorch state dicts of `centrenet.Net` (float32) | 14 files in release `umbilicus-v1`, SHA-256 in the [guide](../../scripts/umbilicus/README.md#weights); `predict.py` needs the two `-all` files |
| Umbilicus file | JSON with `control_points` (`x`, `y`, `z` in level-0 voxels) and `metadata` (`source_volume`, `voxelsize_um`), named `SCROLL_umbilicus.json` or `SCROLL/umbilicus.json` | Input to `trim`, `endcheck.py files` and `ctcheck.py` |
| Published lines | The three bucket files (PHerc0125, PHerc0211, PHerc0826) and Drobkov's ten | Read by `slices.truth()` for training and scoring only |

## Outputs

`predict.py` prints one line per scroll: the scroll id and `{"points": N, "keep_band": N, "spread_mm_median": X, "file": PATH}`.

`OUT/SCROLL_umbilicus.json`, or `OUT/SCROLL/umbilicus.json` with `--vc3d-name`:

| Field | Type | Meaning |
| --- | --- | --- |
| `control_points` | list of `{x, y, z, score}` | One point per kept slice, level-0 voxels, rounded to integers; `score` is always 100 |
| `metadata.source_volume`, `metadata.volume` | str | The scan's bucket path and its last part |
| `metadata.voxelsize_um` | float | Voxel size in um |
| `metadata.volume_width`, `metadata.volume_height`, `metadata.volume_slices` | int | The scan's level-0 x, y and z sizes in voxels, the grid the points are in; all three or none (none, with a line on stderr, when the level-0 shape cannot be read or does not match the slice file) |
| `metadata.total_points` | int | Number of control points |
| `metadata.created` | str | UTC time, `YYYY-MM-DDTHH:MM:SSZ` |
| `metadata.method` | str | The models used and the trims applied |
| `metadata.spread_mm_median` | float or null | Median over kept slices of the distance in mm between each model's answer and the models' median; null when the last stage has one model, as in Quick start |

`OUT/SCROLL_predict.json` (this name in both modes) holds per slice: `z`, `yx` (smoothed center, level-0 voxels, null where no papyrus), `present`, `keep_band`, `kept`, `support` (share of 32 rays meeting papyrus), `spread_mm`; and `scroll`, `volume`, `voxelsize_um`, `volume_dims` (the stamped triplet or null), `umbilicus` (the umbilicus file's path), `papyrus_level`, `first`, `zoom` (weight file names) and `rule` (the trim constants). `pipeline.py trim` adds `metadata.trimmed`, `endcheck.py files` adds `metadata.end_trimmed`; both stamp the triplet when the file lacks it.

### Use it in VC3D and spiral-fitting

What the file needs, from villa main `8aa507c12` (Sourced fact, read 19 October 2026):

- **The name.** VC3D searches each of its folders for `umbilicus.json`, then `estimated_umbilicus.json`, and nothing else (`volume-cartographer/core/src/ScrollUmbilicus.cpp:74-75`, `135-165`). The folders are the one holding the project file (`*.volpkg.json`) and those beside its segment folders (`82-109`). Two hits refuse to pick one (`238-244`). A project's `umbilicus` field names a file and skips the search (`118-132`, `186-217`; `core/src/VolumePkg.cpp:1525-1529`, `2288-2290`). spiral-fitting's dataset folder must hold `umbilicus.json` (`spiral-fitting/fit_session.py:362-365`), and it reads `control_points` (`spiral-fitting/umbilicus.py:25-33`).
- **The grid.** With `volume_width`, `volume_height` and `volume_slices` VC3D finds the one integer factor between that grid and the volume it has open, so the points land on the right voxels at any pyramid level (`ScrollUmbilicus.cpp:262-341`). Without them it uses the ratio of voxel sizes (`348-358`). A partial set, or a value that is not a positive integer, refuses the file (`core/src/Umbilicus.cpp:368-421`). villa's own finder `vc_gen_umbilicus` stamps the same three keys, all three or none (`apps/src/vc_gen_umbilicus.cpp:224-226`, `510-520`).

So: run with `--vc3d-name`, then put the project file in `OUT/SCROLL/` (or copy `umbilicus.json` beside it, or set the project's `umbilicus` field to the file), and open the scan's volume in that project; for spiral-fitting, copy `OUT/SCROLL/umbilicus.json` into the dataset folder. The points are in level-0 voxels of the scan named in `metadata.source_volume`. A line with no points is not written under this name, because VC3D refuses such a file (`Umbilicus.cpp:327-329`) and would stop there. Opening the file in a live VC3D window is not covered here (Untested idea that the window shows what the source says).

| Exit code | Meaning |
| --- | --- |
| `0` | Done. A line can still have 0 points when no run of slices meets the end-point rule |
| `1` | A refusal with its message (a `SystemExit`, see Failure modes), or an error with a Python traceback, such as a failed bucket read (`RuntimeError`) or a missing torch |
| `2` | A usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `NPZ holds no CT (every chunk read was absent or zero): remove the file and check the scan path` (`predict.py`) | A cached slice file holds only zeros, or every chunk it read was missing, usually from a wrong scan path or a false 404 | Remove the file, check `--volume`, and run again |
| `VOL/LEVEL: all N chunk reads were absent (NoSuchKey); no slice file written` (`slices.py`) | Every chunk read for the sampled slices was missing, so the scan path or level is wrong | Check the volume URL and level, then rerun; nothing was cached |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `umbfind: VOLUME: the center finder reads its slices from the open-data bucket (vesuvius-challenge-open-data); open the scan by its bucket URL`, `...: not a bucket URL, bucket key or local folder`, `...: the center finder reads its slices from the open-data bucket by key; give the scan's bucket URL, its key (PHercNNNN/volumes/SCAN.zarr) or a local copy kept under that layout` (`kit.umbfind`, exit 2) | The volume is another host or a local folder that does not keep the bucket's layout | Open the scan by its bucket URL in VC3D, or keep the local copy at `.../PHercNNNN/volumes/SCAN.zarr` |
| `umbfind: VOLUME: KEY is not a scan in the bucket (SCROLL/volumes/SCAN.zarr)` | The key does not name a scan folder | Use a key listed under `SCROLL/volumes/` |
| `umbfind: VOLUME: 2.4 um voxels; the center finder takes 8 to 10 um scans (the 1.2 m scans)` | The open scan is outside `UM_RANGE` | Open the scroll's 1.2 m scan |
| `umbfind: umbilicus-first-all.pt not found with the release's sha256 in ...: download it from ...` | No released weight file with the right SHA-256, and no `--download` | Download them as in Quick start into `work/umbilicus/weights` (or `KIT_UMBILICUS_WEIGHTS`), or pass `--download` (the registry's `--yes-download`) |
| `umbfind: NAME: downloaded sha256 ..., the release pins ...` | The downloaded file is not the released one (a cut download or a proxy page) | Run again; nothing was kept |
| `umbfind: give both --first and --zoom, or neither (the released all-scroll files)`, `umbfind: --first FILE does not exist` | Only one explicit weight file, or a missing one | Give both files, or neither |
| `umbfind: PATH is missing: the finder ships in Scrolls under scripts/umbilicus/` | `KIT_CENTRENET_PREDICT` or `scripts/umbilicus/predict.py` is missing | Use a full Scrolls checkout, or correct the variable |
| `umbfind: the finder exited N: ...`, `umbfind: the finder kept no point ...` (exit 1) | `predict.py` failed (see `RUN/predict.log`), or no run of slices met the end rules, so no `umbilicus.json` was written | Read `RUN/predict.log`; a missing torch or a failed bucket read shows there |
| `--volume needs exactly one scroll` | `predict.py` with `--volume` and several scrolls | Run one scroll per `--volume` |
| `VOLUME: no voxel size in the scan name (<timestamp>-<size>um-...)` | The `--volume` path does not name its voxel size | Give the bucket path of the scan, as listed under `SCROLL/volumes/` |
| `WHAT: 2.4 um voxels; this finder takes 8 to 10 um scans (the models trained on 8.64 and 9.362 um scans only)` | The scan or slice file is outside `UM_RANGE` | Use the scroll's 1.2 m scan |
| `NPZ holds slices of VOL, not --volume VOLUME: use another --data folder or remove the file` | A slice file in `--data` from another scan | Use another `--data` folder, or delete the file |
| `SCROLL: no 1.2 m scan in the open-data bucket; name a scan with predict.py --volume` | The scroll has no `um-1.2m` scan | Name an 8 to 10 um scan with `--volume`, if one exists |
| `VOL/LEVEL: needs raw 128^3 uint8 chunks, got ...` | The scan is stored compressed or with other chunks | Not supported by the range reader |
| `SCROLL: no volume matching ID` | The published bucket file names a scan the listing does not show | Check the bucket; report it |
| `URL: STATUS` (a `RuntimeError` with a traceback) | A bucket or GitHub read failed 6 times | Check the network and retry; finished slice files are kept |
| `listing PREFIX: ...` | A bucket listing did not return XML | Retry; check the prefix |
| `bad job 'JOB': use fold<k>s<seed> or alls<seed>` | `pipeline.py job` with a malformed job name | Use, for example, `fold0s0` or `alls0` |
| `pipeline.py: error: argument cmd: invalid choice: 'WORD' (choose from 'job', 'collect', 'trim')`, exit code 2 | `pipeline.py` with a mistyped command | Use `job`, `collect` or `trim`. Nothing ran |
| `SCROLL: N control points are not at the slice file's heights (first z Z); use endcheck.py files without --data, or trim --no-end-rule` | `pipeline.py trim` on a file not written by this pipeline | Use `endcheck.py files` without `--data`, or `--no-end-rule` |
| `SCROLL: control point heights are not the slice file's heights` | `endcheck.py files --data` on a file whose points are at other heights | Run it without `--data` |
| `SRC: SCROLL has both SCROLL_umbilicus.json and SCROLL/umbilicus.json; keep one` (`trim`, `endcheck.py files`, `ctcheck.py`) | One scroll's line under both names in a folder, so either could be meant | Remove or move one of the two files |
| `SCROLL: no umbilicus file in FOLDER` (`ctcheck.py`) | A scroll asked for, or found in `--a`, has no file under either name in the other folder | Write or copy its line there, or leave the scroll out of `--scrolls` |
| `FILE: its volume dimensions [W, H, Z] are not the scan's [W, H, Z]; the file is in another frame` (`trim`, `endcheck.py files`) | The file already states a grid that is not the scan's level-0 grid, for example a line annotated on a downsampled volume | Convert the points to the scan's level-0 voxels first, or keep the file as it is for the grid it names |
| `FILE: metadata has volume_width without the rest of volume_width, volume_height, volume_slices, which VC3D refuses, and the scan's level-0 shape could not be read` | A partial triplet in an input file and no shape to complete it | Give `--data` slice files with `shape_l0`, restore bucket access, or remove the partial keys |
| `VOL/0/.zarray: shape [...] is not three positive integers` (`ValueError`) | The scan's level-0 `.zarray` is malformed | Report it; the scan cannot be stamped |
| `FILE: slice file holds VOL, not EXPECTED: use another --data folder` or `FILE: slice file has no source volume; rebuild it with slices.py extract` | `trim`, `collect` or `chain-collect` cannot establish that the cached slices belong to the line's scan | Use the matching cache or rebuild it with `slices.py extract`; no line is written for that scroll |
| `VOL: no shape_l0 stored: level-0 metadata could not be read (REASON); CT slices are kept` | The optional level-0 metadata request failed or returned an invalid shape after extraction | The downloaded slices remain usable; restore bucket access to add dimensions on the next prediction |
| `dims must hold all of ('volume_width', 'volume_height', 'volume_slices') as positive integers, got ...` (`ValueError`) | `pipeline.umbilicus_json` called with part of the triplet | Pass `volume_dims`'s answer, all three or none |
| `VOL: no volume_width, volume_height or volume_slices stamped: REASON` (stderr, exit code 0) | The level-0 shape could not be read (no bucket access with an old slice file, no level-0 `.zarray`) or does not downsample to the slice file's planes (another scan) | The file is still valid; VC3D then uses the voxel size. Rerun with bucket access, or remake the slice file with `slices.py extract` to store `shape_l0` |
| `SCROLL: no control points kept, so no OUT/SCROLL/umbilicus.json written (VC3D refuses an umbilicus file without points)` (stderr, exit code 0) | `--vc3d-name` and a line with 0 points; a file there from an earlier run is removed | Check the scan on CT; compare with `--no-end-rule` |
| `ValueError: Out of range float values are not JSON compliant` | A NaN or infinity in an umbilicus file being written (an input file from elsewhere) | Fix the input; nothing was written |
| `RUN: no refine_*.json or fold*.json` | `endcheck.py score` on a folder without job records | Point it at a first-stage or zoom-stage run folder |
| `RUN: holds both first-stage (fold*.json) and zoom-stage (refine_*.json) records; score one stage per folder` | Both stages' records in one folder | Score each stage's folder separately |
| `score RUN_DIR` | `endcheck.py score` without exactly one folder | Give one run folder |
| `files SRC DST` | `endcheck.py files` without a source and a destination | Give both folders |
| `ModuleNotFoundError: No module named 'torch'` | torch is missing for `predict.py`, `refine.py` or training | `python -m pip install torch` |
| A line with `"points": 0` | No 2 mm run of slices has papyrus within 4 mm of the center in three quarters of the directions, or no slice holds papyrus | Check the scan on CT; compare with `--no-end-rule` |

## How it works

1. **Slices** (`slices.extract_ranged`): planes `z = 4 + 8 k` of level 3, so level-0 heights `32 + 64 k`, about 0.55 to 0.60 mm apart; each plane read with one range request per 128 px chunk (`PlaneReader`).
2. **First stage** (`centrenet.frame`, `centrenet.predict`): the slices resampled into a 256 px square (`FRAME`) round the scroll's papyrus, plus 5 %; three slices (64 voxels apart) in, a heatmap at half resolution out; the 8 dihedral transforms are averaged, the peak is refined by a weighted mean over a 9 x 9 window, and mapped back to level-0 voxels. The median over `--first` models is taken.
3. **Zoom stage** (`refine.refine`): a 176 px (`S`) level-3 window round each guess, the same network shape, two rounds (`--rounds`), median over `--zoom` models.
4. **Smoothing** (`slices.smooth_z`): running median over 9 slices, then a quadratic Savitzky-Golay filter over 11.
5. **Mount and cap trim** (`pipeline.keep_band`): keep the longest unbroken run of slices with at least `AREA_FRAC` = 0.3 of the scroll's median papyrus area and at least `CAP_MM` = 3.0 mm inside the first and last slices with papyrus.
6. **End-point rule** (`pipeline.end_trimmed_keep`): from each slice's center cast `END_RAYS` = 32 rays in the 3 x 3 smoothed level-3 slice and count the share that meet papyrus (at or above Otsu's level over the kept windows) within `END_RADIUS_MM` = 4.0 mm; drop points from each end until `END_RUN_MM` = 2.0 mm of consecutive slices reach `END_SUPPORT` = 0.75. Nothing between the first and last such run is dropped. The radius was the smallest of 2, 3, 4 and 5 mm at which at most 0.5 % of published centers in the middle 80 % of each line fall under the bar ([`calibrate.json`](../evidence/2026-10-14-umbilicus/calibrate.json)).
7. **File** (`pipeline.umbilicus_json`, `pipeline.write_umbilicus`): one control point per kept slice, and the scan's level-0 grid (`pipeline.volume_dims`: the slice file's `shape_l0`, else the level-0 `.zarray`, kept only when each level-3 plane dimension is floor or ceil of the corresponding level-0 dimension divided by 8, the test VC3D's `uniformRescaleFactor` applies), written as strict JSON under `SCROLL_umbilicus.json` or, with `--vc3d-name`, `SCROLL/umbilicus.json`.

Training (`pipeline.run_job`, `refine.chain_job`): four folds by scroll (`FOLDS`), two first-stage seeds per fold plus one model on all 13 (`JOBS`), one zoom model per fold plus one on all (`CHAIN_JOBS`); the zoom stage trains from published centers plus random offsets up to `R` = 64 level-3 pixels and is chained onto the first stage's real answers.

## Cost and time

- `predict.py`: about 13 minutes on 4 CPU cores for PHerc1203, the smallest published scan, 7 of them reading 0.25 to 0.65 GB of slices ([guide](../../scripts/umbilicus/README.md#quick-start)). That fits a laptop; no Modal needed.
- Training: 162 to 253 s per first-stage job on a B300 and 46 to 76 s per zoom job on an L40S ([guide](../../scripts/umbilicus/README.md#reproduce-the-held-out-results)), plus `slices.py extract` of the 13 scrolls (at most 5.0 GB of range reads). It needs a GPU, so it runs on Modal with a run spec and Chase's go-ahead (the Modal rule, hard rule 11). Cost: Not recorded in this repository.
- `endcheck.py calibrate`: about 0.6 to 0.7 GB of range reads; time Not measured.
- `pipeline.py trim` on a synthetic 60-slice scroll: 0.6 s (measured 2026-10-16, 4-core cloud container).
- Stamping the grid: none extra when the slice file holds `shape_l0`; otherwise one read of a few hundred bytes per scroll.

## Start from VC3D

Open a 1.2 m scan (8 to 10 um) in VC3D by its open-data bucket URL, or a local copy kept under the bucket's layout (`.../PHercNNNN/volumes/SCAN.zarr`), and pick Scrolls > viewer > "Plan: Find the scroll's center line in the open volume (umbilicus finder)". It is a plan only, never a run: the finder reads 0.25 to 0.65 GB of slices, may fetch the two weight files (about 26 MB) and takes about 13 minutes on 4 CPU cores, over the 10 minute rule for Chase's Mac. VC3D shows `plan.json`, with the bound volume, the command, the time and download estimate and each gate's verdict. Run it from a terminal (or have an agent run it) where torch is installed, through the tool registry ([toolreg](toolreg.md)):

```bash
python -m kit tools run umbilicus --volume VOLUME_URL --yes-download --out RUN
```

`kit/umbfind.py` maps the volume to its bucket key, uses the released weights from `KIT_UMBILICUS_WEIGHTS` or `work/umbilicus/weights` when their SHA-256 matches the release (else fetches them into `RUN/weights`), runs `predict.py` on the CPU and copies the line to `RUN/umbilicus.json`. `--input first=FILE --input zoom=FILE` uses other weights, such as a fold's, and records their SHA-256 as not pinned. AutoPipeline (AP) runs the same finder as its umbilicus backend `centrenet`; where AP is installed, the registry's manifest digest travels with that backend into AP's records and `graph.json`.

## Open in VC3D

The plan's run writes `RUN/umbilicus.json`, which passes the registry's umbilicus check (VC3D's reader rules) before anything opens. Load it into VC3D with Scrolls > Open run output > "Open run output as umbilicus" (run folder `RUN`), or from a terminal `python -m kit tools take umbilicus --run RUN --out DIR`. The points are level-0 voxels of the scan named in `metadata.source_volume`, with its grid stamped when the bucket gives it, so VC3D places them on any pyramid level of that scan (see "Use it in VC3D and spiral-fitting" under Outputs). The line is model output, not a measured line; on the 13 scrolls with a published line it is not held out.

## For agents

- **Command:** `python scripts/umbilicus/predict.py SCROLL --first W/umbilicus-first-all.pt --zoom W/umbilicus-zoom-all.pt --data work/umbilicus/slices --out work/umbilicus/out --vc3d-name` (weights checked by SHA-256 first, as in Quick start); the machine-readable output is `OUT/SCROLL/umbilicus.json` (without `--vc3d-name`, `OUT/SCROLL_umbilicus.json`) and `OUT/SCROLL_predict.json`.
- **Parse:** `control_points` (level-0 `x`, `y`, `z`), `metadata.total_points`, `metadata.spread_mm_median`, `metadata.volume_width`, `volume_height`, `volume_slices`; per slice `kept` and `support` in `_predict.json`. The printed line holds `points`, `keep_band`, `spread_mm_median` and `file`.
- **Rerun:** Safe. Slice files in `--data` are reused (delete one to read it again); the two output files are overwritten. Training jobs overwrite their `.pt` and `.json`.
- **Success:** Exit code 0, `points` above 0, and for VC3D the three `volume_*` keys present (no "no volume_width" line on stderr).
- **Not a pass:** A line on one of the 13 published scrolls from the `-all` weights (they trained on it); a small `spread_mm_median` read as accuracy; a line not looked at on CT; held-out scores that do not first reproduce `result.json` in `endcheck.py score`; a file that passes the tests' copy of VC3D's reader taken as proof that a live VC3D window shows it right.
- **Go-ahead:** Nothing to run `predict.py` on public scans. Renting GPUs to train, posting a line, or uploading weights needs Chase's yes.
- **Never:** Call a line a measurement or ground truth; run it on a scan outside 8 to 10 um by editing `UM_RANGE`; commit slice files, CT pictures or weights to git (scan data is CC BY-NC 4.0 and stays out of the repository); hand-edit `volume_width`, `volume_height` or `volume_slices` to another grid without converting the points.

## Tests

```bash
python -m unittest tests.test_umbilicus -v
```

They cover the first stage's coordinate frame and augmentation, the zoom crops and offsets, `keep_band`, the papyrus level, the end-point support and trims (from the ends only, at 2 mm and 4 mm for each voxel size), trimming written files, `collect` and `chain-collect`, `predict.py` writing a trimmed file from weights, its refusal of other scans, `endcheck.py` windows and missing-chunk counts, the range reader against a synthetic volume, `pipeline.py` refusing a mistyped command, and the files VC3D reads: rule-for-rule copies of VC3D's reader, name search and rescale rule (checked against villa's own test values) read back what `predict.py`, `trim`, `endcheck.py files`, `collect` and `chain-collect` write, with and without `--vc3d-name`, from a slice file's `shape_l0` or the level-0 `.zarray`, and with no triplet at all when the shape is missing or of another scan. All data is synthetic and read on the CPU; the module keeps `slices.get` off the network. On 2026-10-20 in a Linux cloud container, all 58 tests passed with numpy, scipy, CPU torch, requests and numcodecs, with no skips. The regressions include mismatched or missing slice-cache identity and an optional metadata failure after extraction. They do not read the bucket or the released weights.

`python -m unittest tests.test_umbfind tests.test_toolreg_rowumb -v` covers the adapter and its manifest with a stand-in `predict.py` (`KIT_CENTRENET_PREDICT`): volume to bucket key (URL, key, local copy, refusals), the release's SHA-256 pins and explicit weights, a line with no points refused, VC3D's Plan: entry only, the run with `--yes-download` through the registry, the umbilicus check and taking the line back into VC3D.

## History

- 2026-10-21: `python -m kit.umbfind` and the tool registry manifest: VC3D plans the finder on the open scan, and the run's line comes back as an umbilicus ([branch claude/integration-1020](https://github.com/ChaseHendrick/Scrolls/tree/claude/integration-1020)).
- 2026-10-20: `--vc3d-name` writes `SCROLL/umbilicus.json`, the name VC3D and spiral-fitting look for; when available, written files carry the scan's level-0 `volume_width`, `volume_height` and `volume_slices`; slice files keep `shape_l0`; `ctcheck.py` reads both names; tests check the files with a copy of VC3D's reader at villa `8aa507c12`.
- 2026-10-17: `pipeline.py` refuses a command other than `job`, `collect` or `trim` with a usage error; before, a mistyped command did nothing and exited 0 (`c03e227`).
- 2026-10-16: slice caches are keyed by scan, and a slice file with no CT is refused (`91bc14e`).
- 2026-10-14: the tests set aside StrokeNet's same-named `pipeline` module (`8bf841b`).
- 2026-10-14: first public release: `predict.py`, training and scoring scripts, the end-point rule, `ctcheck.py`, and held-out evidence; weights in release `umbilicus-v1` (`76e4591`).

## Related

- [Scroll center finder guide](../../scripts/umbilicus/README.md): weights, held-out tables, the end-point rule, reproduction and credits.
- [Evidence folder](../evidence/2026-10-14-umbilicus/README.md): `heldout-endrule.json` and `calibrate.json`.
- [`results.json`](../results.json): `umbilicus_checks`, the held-out scores and the centroid control.
- [`stackcheck`](stackcheck.md): checks a stack of segments against an umbilicus file.
- [`autopipeline`](autopipeline.md): its umbilicus stage accepts a file in the published format, and runs this finder as its backend `centrenet`.
- [`toolreg`](toolreg.md): the tool registry that starts it from VC3D and the command line.
