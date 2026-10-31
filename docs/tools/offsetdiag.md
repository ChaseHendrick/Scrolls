# offsetdiag: measure how ink AUC changes when a segment's surface moves along its normal

Renders a labeled segment box from the scan along its mesh normals at chosen offsets, snaps it to villa's lasagna sheet center against same-size controls, and scores every arm's ink map with its reverse-depth control. A development diagnostic, not a test.

| Field | Value |
| --- | --- |
| Id | `offsetdiag` |
| Status | Experimental |
| Kind | script folder |
| Area | Scoring and controls |
| Run | `python3 scripts/offsetdiag/offsetdiag.py fetch`, `validate`, `render`, `measure`, `arms`, `score`; `bash scripts/offsetdiag/infer.sh` |
| Code | `scripts/offsetdiag` |
| Tests | `tests/test_offsetdiag.py` (synthetic data only) |
| Needs | Python 3.10 or newer with numpy, scipy, tifffile, zarr (2 or 3) and numcodecs; the repository's `kit` (it imports `kit.auc` and `kit.fetch`); for the maps, villa's `vesuvius` package with its `models` extra ([ScrollPrize/villa](https://github.com/ScrollPrize/villa)), a CUDA GPU and an ink checkpoint such as Reader V3 ([`domenicor046/reader-v3`](https://huggingface.co/domenicor046/reader-v3)) |
| Runs on | fetch, validate, render, measure, arms and score on any CPU (one PHerc0841 box on a 4-core cloud container, 31 Oct 2026: fetch 7 s, validate 3 s, measure 61 s, render about 3 minutes); maps on a CUDA GPU, your own machine or a Hugging Face Job you own |
| Network | `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (the scan, meshes, published surface volumes and ink labels); `huggingface.co` (villa's lasagna cos field for the PHerc0841 scan in the public Lasagna Fields bucket, and the ink checkpoint) |
| Writes | In the work folder: `cache/`, `mesh/KEY/`, `labels/KEY/`, `render/KEY.npy`, `render/KEY_cos.npz`, `render/KEY_validate.json`, `arms/KEY/ARM.zarr`, `arms/KEY/arms.json`, `maps/` (from `infer.sh`), `scores.json` |
| Go-ahead | Not needed for the CPU steps on public data. A paid GPU (a Hugging Face Job) follows your own compute rules |
| Released | Public `main` from 2026-10-31 (code, Apache-2.0) |
| License | Code: Apache License 2.0 ([`scripts/offsetdiag/LICENSE`](../../scripts/offsetdiag/LICENSE)). The scan, meshes, surface volumes and labels are the Vesuvius Challenge open data (CC BY-NC 4.0), read live, not copied |
| Checked | 2026-10-31 against commit `0f1b080` |

## What it does

An ink model reads a stack of layers rendered around a traced surface. When the surface sits a few voxels off the papyrus, the model reads the wrong depth and its AUC drops. This tool measures that drop on a labeled segment, and tests one candidate fix: moving each pixel to the sheet center that villa's lasagna field gives (the cos maximum nearest the mesh).

It renders the segment's box itself, from the scan, along the published mesh's normals, so it can move the surface past the 28 layers of the published surface volume. Each **arm** is a 28-layer stack. **P0** is the published surface volume's box itself. **R0** is our render at the published offsets; **Rm8**, **Rm4**, **Rp4** and **Rp8** move it by -8, -4, +4 and +8 voxels ("m" for minus, toward layer 0; "p" for plus, toward layer 27). **SNAP** moves each pixel to the lasagna sheet center (smoothed and rounded); its two controls move by the same amounts in the wrong way: **ANTI** the other direction, **RAND** SNAP's field turned 180 degrees in the box (same values and smoothness, wrong places). villa's own ink inference maps every arm in both depth directions, and `score` gives each arm's AUC, its reverse-depth control and its difference to R0 with a paired block-bootstrap interval.

It does not change any mesh, and nothing it measures on development segments is a held-out result. Every map is model output, not a reading.

## When to use it

- To measure how much an ink model's AUC depends on surface depth on a labeled segment.
- To test a per-pixel surface correction (any offset field) against same-size controls before proposing it.
- To check how much a renderer alone moves a score (R0 against P0).

Do not use it:

- on a segment you mean to keep as a held-out test: the diagnostic reads its labels many times; use a frozen preregistered readout instead (`python -m kit run init`, [run-ledger](run-ledger.md));
- to score a single map: [`auc`](auc.md) does that;
- to move a mesh for tracing or rendering: it only measures; see [labelsnap](labelsnap.md) for snapping a surface label.

## Quick start

One PHerc0841 segment, the CPU steps (about 300 MB of downloads):

```bash
python3 scripts/offsetdiag/offsetdiag.py fetch 0841-w00 --work WORK
python3 scripts/offsetdiag/offsetdiag.py validate 0841-w00 1500 600 --work WORK
python3 scripts/offsetdiag/offsetdiag.py render 0841-w00 --work WORK
python3 scripts/offsetdiag/offsetdiag.py measure 0841-w00 --work WORK
python3 scripts/offsetdiag/offsetdiag.py arms 0841-w00 --work WORK
```

`WORK` is any folder. `validate` printed (31 Oct 2026, a 4-core cloud container):

```
layer  0: best offset -13.5 (expected -13.5), r 0.979
layer 13: best offset  -0.5 (expected  -0.5), r 0.990
layer 14: best offset  +0.5 (expected  +0.5), r 0.989
layer 27: best offset +13.5 (expected +13.5), r 0.962
PASS: WORK/render/0841-w00_validate.json
```

It worked when it says PASS: every published layer j matched our render at offset j - 13.5 with r at least 0.9. `measure` printed `0841-w00: 67497 points, peak found at 0.935, ...`, and `arms` writes nine zarr groups (P0 from `fetch` and the eight arms) under `WORK/arms/0841-w00/`.

Then the maps, on a machine with a CUDA GPU and villa installed (next section), and the scores:

```bash
VILLA_PYTHON=VILLA/vesuvius/.venv/bin/python bash scripts/offsetdiag/infer.sh reader-v3.pth WORK rv3
python3 scripts/offsetdiag/offsetdiag.py score --work WORK --model rv3 --keys 0841-w00
```

`VILLA` is your villa checkout. `infer.sh` writes `WORK/maps/rv3_0841-w00_ARM.tif` and `..._reverse.tif` for every arm; `score` writes `WORK/scores.json`.

### Running villa's ink inference

On any Linux machine with an NVIDIA GPU:

```bash
git clone https://github.com/ScrollPrize/villa.git
(cd villa/vesuvius && uv sync --extra models)
uvx --from huggingface_hub hf download domenicor046/reader-v3 reader-v3.pth \
  --revision aee1d64bced4eb35546348f3d276b9e2a0b99c46 --local-dir .
sha256sum reader-v3.pth      # ea405417450abd8ace1b8ff79ebce3adb646c5e48ab95da46844d77efe984d8a
VILLA_PYTHON=villa/vesuvius/.venv/bin/python bash Scrolls/scripts/offsetdiag/infer.sh reader-v3.pth WORK rv3
```

On a Hugging Face Job you own: upload the arms to a dataset repository of yours, run the same steps inside the Job, and upload the maps back. `USER/offsetdiag` is your own dataset repository:

```bash
hf upload USER/offsetdiag WORK/arms arms --repo-type dataset --private
hf jobs run --flavor a10g-large --timeout 2h --secrets HF_TOKEN python:3.12 bash -c '
  set -e
  pip install -q uv huggingface_hub
  git clone --depth 1 https://github.com/ScrollPrize/villa.git /villa
  (cd /villa/vesuvius && uv sync --extra models)
  git clone --depth 1 https://github.com/ChaseHendrick/Scrolls.git /scrolls
  hf download USER/offsetdiag --repo-type dataset --include "arms/*" --local-dir /work
  hf download domenicor046/reader-v3 reader-v3.pth --revision aee1d64bced4eb35546348f3d276b9e2a0b99c46 --local-dir /ckpt
  VILLA_PYTHON=/villa/vesuvius/.venv/bin/python bash /scrolls/scripts/offsetdiag/infer.sh /ckpt/reader-v3.pth /work rv3
  hf upload USER/offsetdiag /work/maps maps --repo-type dataset'
hf download USER/offsetdiag --repo-type dataset --include "maps/*" --local-dir WORK
```

Any CUDA flavor works; lower `--batch-size` in `INFER_ARGS` on a GPU with less memory. These two recipes were written for this release and not run in this form (Not measured); the 30 October run mapped the arms on one RTX PRO 6000 through a batching wrapper of ours around villa's inference code that normalizes tiles on the GPU, with the same arguments. Our run used villa at commit `6723ad15`; to match it, check that commit out (it is the head of villa PR #1865: `git fetch origin pull/1865/head`).

## Checks and controls

- **Convention gate:** `validate` must PASS (each published layer j matches our render at offset j - 13.5, r at least 0.9) before any arm is built. A flipped normal or another layer convention fails it; set `normal_sign` for another segment in `--segments`.
- **Reproduction gate:** before reading any shifted arm, score P0 with your model and compare it with an earlier score of the same model and setting on the same box; a mismatch means the engine or arguments differ, and no arm is read. On 30 October 2026, Reader V3 on both published boxes reproduced its earlier scores exactly.
- **Reverse-depth control:** every arm is mapped in both directions; the reverse map is scored beside it and must stay far below the forward map.
- **Same-size controls:** SNAP is read only against ANTI and RAND, which move the surface by the same amounts in the wrong direction or at the wrong places. SNAP losing to R0 but beating both controls says the field carries real geometry but the mesh already sits better.
- **Renderer control:** R0 against P0 shows how much the renderer alone moves the score; differences between arms smaller than that are not readable.

Claim label: Model output, for every AUC; Interpretation, for the readings in the result below.

## Result on PHerc0841, 30 October 2026 (development only)

Model output. Reader V3 (Domenico Russo) at villa's argument `--layer-start 6 --layer-end 23` (layers 6 to 23), hann blending, overlap 0.5, both directions, on two PHerc0841 segments of the 9.366 um scan, w00 and ag896, inside the development scoring boxes of earlier rounds (the boxes in `oddata.SEGMENTS`), with the reverse-depth control. Losses are against R0 and agree within 0.01 between the as-stored and texture label registrations ([log](../logs/2026-10-30-ink-offset.md), `results.json` key `offsetdiag_dev_20261030`).

| Move along the normal | w00 | ag896 |
| --- | --- | --- |
| 4 voxels toward layer 0 | -0.07 | -0.04 |
| 4 voxels toward layer 27 | about -0.02, not significant | about -0.02, not significant |
| 8 voxels toward layer 0 | -0.25 | -0.21 |
| 8 voxels toward layer 27 | -0.16 | -0.12 |

- Gate: before any shift, Reader V3 on the published boxes reproduced earlier scores exactly.
- Moving toward layer 0 cost 1.5 to 4.1 times as much as the same move the other way.
- SNAP, each pixel moved to villa's lasagna cos maximum (the sheet center), cost 0.03 to 0.08 AUC but beat its same-size controls ANTI and RAND: the published meshes already sit better for ink than the sheet center on these two segments.
- A second, smaller ink model of ours (not released) lost less per shift, but Reader V3 stayed above it at every shift (smallest gap 0.03).
- Our own render at offset 0 (R0) moved Reader V3 by +0.007 (w00) and -0.009 (ag896) against the published surface volume (P0), so renderer details alone are worth about 0.01.
- Release check: the released code rebuilt w00's arms on 31 October 2026 (fetch to arms, a 4-core cloud container) with the same shift statistics, lasagna coverage and R0 against P0 correlation as the run's record; the maps were not rerun.
- Limits: development only, two segments of one scroll, one main model, and both segments were already used in earlier development. It is not a test, and no level is claimed.

## Commands and options

### `offsetdiag.py`

```
usage: offsetdiag.py [-h] [--version]
                     {fetch,validate,render,measure,arms,score} ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--version` | off | Print the version (1.0.0) and exit |

### `offsetdiag.py fetch`

```
usage: offsetdiag.py fetch [-h] [--work WORK] [--segments SEGMENTS] key
```

| Option | Default | Meaning |
| --- | --- | --- |
| `key` | required | Segment key: `0841-w00`, `0841-ag896`, or one from `--segments` |
| `--work` | `$OFFDIAG_WORK` or `.` | The work folder |
| `--segments` | none | JSON file of extra segments (Inputs) |

Downloads the mesh to `mesh/KEY/`, level 2 of the ink labels and supervision mask to `labels/KEY/`, and the published surface volume's box to `arms/KEY/P0.zarr`.

### `offsetdiag.py validate`

```
usage: offsetdiag.py validate [-h] [--work WORK] [--segments SEGMENTS]
                              [--size SIZE]
                              key row col
```

| Option | Default | Meaning |
| --- | --- | --- |
| `key` | required | Segment key |
| `row`, `col` | required | The tile's top-left pixel inside the box |
| `--work`, `--segments` | as fetch | As fetch |
| `--size` | 128 | Tile size in px |

Renders the tile at offsets -18 to +18 in half voxels and prints, for every third published layer, the best-matching offset and its r; exit 0 on PASS, 1 on FAIL.

### `offsetdiag.py render`, `measure` and `arms`

```
usage: offsetdiag.py render [-h] [--work WORK] [--segments SEGMENTS] key
usage: offsetdiag.py measure [-h] [--work WORK] [--segments SEGMENTS] key
usage: offsetdiag.py arms [-h] [--work WORK] [--segments SEGMENTS] key
```

| Option | Default | Meaning |
| --- | --- | --- |
| `key` | required | Segment key |
| `--work`, `--segments` | as fetch | As fetch |

`render` writes the 44-offset render `render/KEY.npy`; `measure` the lasagna offsets `render/KEY_cos.npz`; `arms` the eight arms and `arms/KEY/arms.json`.

### `offsetdiag.py score`

```
usage: offsetdiag.py score [-h] [--work WORK] [--segments SEGMENTS]
                           --model MODEL [--keys KEYS [KEYS ...]]
                           [--draws DRAWS] [--seed SEED] [--out OUT]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--model` | required | The model name in the map file names `MODEL_KEY_ARM.tif`; repeatable |
| `--keys` | `0841-w00 0841-ag896` | Segment keys to score |
| `--draws` | 1000 | Bootstrap draws for arm minus R0 |
| `--seed` | 20261030 | Bootstrap seed |
| `--out` | `WORK/scores.json` | The scores file |
| `--work`, `--segments` | as fetch | As fetch |

### `infer.sh`

```
usage: infer.sh CHECKPOINT WORK MODEL
```

| Option | Default | Meaning |
| --- | --- | --- |
| `CHECKPOINT` | required | An ink checkpoint villa's `infer` loads, such as `reader-v3.pth` |
| `WORK` | required | The work folder holding `arms/KEY/ARM.zarr` |
| `MODEL` | required | The model name written into the map file names |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `VILLA_PYTHON` | `python` | `infer.sh`: the Python of villa's environment |
| `INFER_ARGS` | `--overlap 0.5 --blend-mode hann --batch-size 64 --no-compile --layer-start 6 --layer-end 23` | `infer.sh`: villa's arguments; `--direction both` is always added |
| `DRY_RUN` | `0` | `infer.sh`: `1` prints the commands and runs nothing |
| `OFFDIAG_WORK` | the current folder | `offsetdiag.py`: the work folder when `--work` is not given |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `oddata.segments(extra=None)`, `oddata.segment(key, extra=None)` | the segment table, or one segment's dict | `DataError` | Built-in w00 and ag896, updated from a JSON file |
| `oddata.Zarr2(url, cache=None)` | a reader with `.read_box(lo, hi)` and `.sample(zyx)` | `DataError` | One uint8 zarr v2 level, uncompressed or blosc, over HTTPS or a local path |
| `odgeom.load_mesh(folder)` | (xyz, valid, scale) | none | A tifxyz folder |
| `odgeom.render(mesh, scan, offsets, rows, cols, normal_sign=-1, shift=None)` | (len(offsets), H, W) float32 | `DataError` on an unreadable chunk | Scan at pos + (o + shift) * n_pub; 0 where the mesh is invalid |
| `odgeom.match_layers(published, rendered, offsets, mask)`, `odgeom.check_layers(best)` | [(layer, offset, r)], bool | none | The convention gate |
| `odgeom.cos_profiles(mesh, cos, rows, cols, ts, ...)`, `odgeom.nearest_peak(prof, ts)` | profiles and mask; offsets, NaN where none | none | The lasagna sheet center along n_pub |
| `odarms.take(big, r)`, `odarms.shift_field(d, ok, shape)`, `odarms.arm_shifts(field, valid)` | (28, H, W); field and summary; {arm: shifts} | `ValueError` | The arms |
| `odscore.labels_on_map(labels, mask, surface_shape, box, offset)`, `odscore.score_arm(pred, ink, sup, control, ref)` | ink and supervision; a score row | `VerifyError` | Labels moved by (dy, dx); AUC with `kit.auc` |

## Inputs

- A segment: its open-data folder, the tifxyz mesh on the 9.366 um scan (x, y, z float32 at grid scale 0.05, -1 where invalid), the published 28-layer surface volume's shape and the box (rows y0 to y1, columns x0 to x1). Built in: `0841-w00` (`PHerc0841/segments/20260220213127-w00`, shape 4220 x 4760, box 371 3492 2601 3981) and `0841-ag896` (`PHerc0841/segments/20260220214732-auto_grown_20260220144552896`, shape 4640 x 4720, box 704 3241 1513 3403).
- `--segments FILE.json`: `{KEY: {"segment", "mesh", "shape", "box"}}`, plus optional `scan` (a zarr v2 level URL), `cos` (villa's cos field level URL), `cos_scale` (base voxels per cos voxel, 2.0 for level 1), `surface_volume`, `labels` (the labels folder under the segment), `normal_sign` (default -1) and `layers` (default 28).
- The scan `PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr/0` (zarr v2, 128-cubed uint8 chunks, z y x).
- villa's lasagna cos field for that scan, level 1 (18.732 um, 64-cubed blosc chunks), run `20250821151531-lasagna-de45f011`, read from the public [Lasagna Fields](lasagna-fields.md) bucket.
- The ink labels `ink-labels/2.403um-volume-20260319124803/20260918/{inklabels,supervision}.zarr`, level 2 (the 9.366 um surface grid up to a uniform scale).
- Ink maps (for `score`): `WORK/maps/MODEL_KEY_ARM.tif` and `MODEL_KEY_ARM_reverse.tif`, each the box's shape, as villa's `infer` writes them.

Offsets are in 9.366 um voxels along n_pub, the published stack's normal: layer j of the 28 published layers sits at offset j - 13.5.

## Outputs

| Field | Type | Meaning |
| --- | --- | --- |
| `scores.json["MODEL KEY ARM"][REG].auc` | float | AUC inside supervision at level 2, zeros kept, 64 px edge left out; REG is `as_stored` or `texture` (labels moved by (-6, -7) px) |
| `...control` | float or null | The reverse-depth map's AUC |
| `...vs_R0.difference` | float | The arm's AUC minus R0's on the same pixels |
| `...vs_R0.ci95` | [float, float] | Its paired block-bootstrap 95 percent interval (107 px blocks) |
| `arms.json["arms"][ARM]` | dict | `shift_mean`, `shift_abs_mean` and `shift_pct` (5, 25, 50, 75, 95) over valid pixels, in voxels |
| `arms.json["lasagna"]` | dict | `coverage` (share of grid points with a sheet center), `median` and `pct` of the smoothed offset |
| `arms.json["r0_vs_published_corr"]` | dict | Per-layer r of R0 against P0: `min`, `median` |
| `KEY_validate.json` | dict | `layers` (`layer`, `best_offset`, `r`), `valid_px`, `pass` |
| `KEY.npy` | uint8 (44, H, W) | The render at offsets -21.5 to +21.5 |
| `KEY_cos.npz` | arrays | `cos` profiles (T, h, w), `ok`, `ts` (offsets), `d` (sheet center offset per grid point, NaN where none) |

| Exit code | Meaning |
| --- | --- |
| `0` | The step finished; for `validate`, PASS |
| `1` | `validate`: FAIL, the render does not match the published layers |
| `2` | A usage error (argparse, or `infer.sh` with the wrong arguments) |
| `3` | A data error: a missing input, an unknown segment, an unreadable array (message on stderr) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `usage: infer.sh CHECKPOINT WORK MODEL` | `infer.sh` needs three arguments | Give the checkpoint, the work folder and a model name |
| `infer.sh: error: no checkpoint at...` | The checkpoint path does not exist | Download it (Quick start) |
| `infer.sh: error: no.../arms; run offsetdiag.py fetch and arms first` | The work folder has no arms | Run the CPU steps first |
| `infer.sh: error: no arms under.../arms` | `arms/` holds no `KEY/ARM.zarr` | Run `arms` |
| `shift beyond...voxels` | A shift field exceeds the render's margin | Clip shifts to 8 voxels |
| `the wide render has...layers, expected...` | `KEY.npy` is not a 44-offset render | Run `render` again |
| `cannot read...:...` | A network read failed after eight tries | Check the network; rerun (cached chunks are kept) |
| `unknown segment...; known:...(add one with --segments)` | The key is not built in | Add it with `--segments` |
| `no zarr v2 array at...(.zarray not found)` | The URL is not a zarr v2 array level | Give one level of the array, such as `.../0` |
| `...: dtype...; only uint8 is supported` | The array is not uint8 | Use a uint8 level |
| `segment...in...lacks...` | A `--segments` entry misses a field | Add segment, mesh, shape and box |
| `...: compressor...; only none and blosc are supported` | Another codec | Not supported |
| `...chunk...has...values, expected...` | A chunk is truncated or another shape | Delete that file under `cache/` and rerun |
| `labels...and mask...differ in shape at level...` | Labels and mask are from different sets | Fetch both again |
| `labels...and surface...differ in scale between axes` | The labels do not belong to this surface | Check the segment's `labels` and `shape` |
| `...: map shape...is not the box's...` | The map is not the box's size | Map the arm zarrs, not the whole segment |
| `no mesh in...; run fetch...first` | `mesh/KEY/` is missing | Run `fetch` |
| `no published box at...; run fetch...first` | `arms/KEY/P0.zarr` is missing | Run `fetch` |
| `surface volume shape...does not match the segment's...` | The segment's `shape` is wrong | Correct it in `--segments` |
| `tile...,...of size...leaves the...x...box` | The tile does not fit in the box | Pick a smaller row or column |
| `only...valid pixels in the tile; pick a tile on the labeled surface` | The tile is mostly off the mesh | Pick another tile |
| `no maps named MODEL_KEY_ARM.tif in...` | No maps for that model | Run `infer.sh` with the same model name |
| `offsetdiag.py: error:...` | Any data error, exit 3 | Read the message |
| `no...; run...first` | `arms` needs `render` and `measure` | Run them |
| `no zarr metadata for.../.../...` | The labels folder has no zarr metadata | Check the segment's `labels` path |
| `unknown segment...` | `score --keys` names an unknown key | Add it with `--segments` |

## How it works

1. Mesh: x, y, z upsampled bilinearly from the tifxyz grid (scale from `meta.json`, default 0.05); normals are the cross product of the grid's column and row derivatives, interpolated and normalized, times `normal_sign` (-1 for these meshes) to give n_pub; a pixel is valid when all four coarse neighbors are.
2. Render: trilinear samples of the scan at pos + o * n_pub, fetched by chunk with a disk cache, in tiles of `RENDER_TILE` 256 px; offsets -21.5 to +21.5 (28 layers plus `MAX_SHIFT` 8 on each side); stored as uint8.
3. Lasagna offset: cos sampled along n_pub at -12 to +12 voxels, step 0.25, on an 8 px grid (`STRIDE`); the local maximum at or above `PEAK_MIN_VAL` 160 nearest 0 within `PEAK_MAX_ABS` 8 voxels, refined by a parabola; smoothed by a normalized Gaussian of `SIGMA` one grid point, upsampled bilinearly, rounded and clipped to 8.
4. Arms: layer j of an arm with shift s is the render at offset j - 13.5 + s (`odarms.take`).
5. Maps: villa's `infer` with `--direction both`; for Reader V3, layers 6 to 23, hann, overlap 0.5.
6. Scores: `kit.auc`'s AUC (labels mapped by nearest neighbor, keep zeros, 64 px inner edge) under two registrations, as stored and texture (labels moved by (-6, -7) px); arm minus R0 by `kit.auc.block_bootstrap` (1000 draws, seed 20261030).

## Cost and time

Measured 31 Oct 2026 on a 4-core cloud container for PHerc0841 w00: fetch 7 s (about 100 MB), validate 3 s, measure 61 s, render about 3 minutes; arms and score take seconds to a minute. The 30 October run mapped 18 arms with two models in 751 s on one RTX PRO 6000 through our wrapper; villa's own `infer` was not timed here (Not measured). GPU work goes to a GPU machine or a Hugging Face Job you own; do not run it on a laptop CPU.

## For agents

- **Command:** `python3 scripts/offsetdiag/offsetdiag.py fetch KEY --work WORK`, then `validate KEY 1500 600`, `render KEY`, `measure KEY`, `arms KEY`; `bash scripts/offsetdiag/infer.sh CKPT WORK MODEL` on a GPU; `python3 scripts/offsetdiag/offsetdiag.py score --work WORK --model MODEL`.
- **Parse:** `WORK/scores.json`: `auc`, `control` and `vs_R0` (`difference`, `ci95`) per model, segment, arm and registration; `WORK/render/KEY_validate.json` `pass`.
- **Rerun:** safe; renders, arms and scores are rewritten, caches kept; `infer.sh` skips maps that exist.
- **Success:** exit 0 at every step, `validate` PASS, and P0 reproducing an earlier score of the same model before any arm is read.
- **Not a pass:** an arm read before both gates hold; SNAP read against R0 without ANTI and RAND; a difference smaller than R0 minus P0 (about 0.01); any number called held out.
- **Go-ahead:** Nothing for the CPU steps; a paid GPU follows your own compute rules.
- **Never:** run it on a segment you keep for a held-out test; call a map a reading; pick a shift on these segments and report it as a tested gain.

## Tests

`python3 -m unittest tests.test_offsetdiag -v` covers the zarr reader (boxes across chunks, missing chunks, trilinear samples, refusals), the render's sign and offset convention on a synthetic ramp volume, per-pixel shifts and invalid mesh pixels, the convention gate passing and failing, the lasagna peak finder and a synthetic sheet above a flat mesh, the arm cutting and its controls, the shift field, the label offset and the scoring with its control and paired difference, the command line's errors and `infer.sh`'s dry run. They read no scan and run no model; the zarr round trip and the label test need zarr.

## History

- 2026-10-31: first public release, code only, Apache-2.0 (offsetdiag 1.0.0), with the 30 October development result (base `0f1b080`).

## Related

- [`../logs/2026-10-30-ink-offset.md`](../logs/2026-10-30-ink-offset.md): the dated note of the 30 October result.
- [`auc`](auc.md): the scoring this tool calls.
- [`lasagna-fields`](lasagna-fields.md): villa's lasagna field, the source of the sheet center.
- [`labelsnap`](labelsnap.md): moves a surface label onto the papyrus face, a related geometry fix.
- `results.json` key `offsetdiag_dev_20261030`: the numbers.
