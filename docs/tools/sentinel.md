# sentinel: Bucket Sentinel, standing checks on the organizers' public uploads

`python -m kit sentinel` checks new or changed uploads to the organizers' public data for label canvases out of line with their meshes, truncated pyramids, fake unit scales and meshes from another frame, and writes an offset table that training loaders can import.

| Field | Value |
| --- | --- |
| Id | `sentinel` |
| Status | Experimental |
| Kind | kit command, kit module |
| Area | Data and downloads |
| Run | `python -m kit sentinel`, `python -m kit.sentinel`, `from kit import sentinel`, `from kit import sentinel_table`, `bash scripts/sentinel/job.sh` |
| Code | `kit/sentinel.py`, `kit/sentinel_table.py`, `scripts/sentinel/`, `kit/cli.py` (`build_parser`); it reuses [tifxyz](tifxyz.md)'s chunk reader (`ZarrSource`) and [meshaudit](meshaudit.md)'s TIFF reader and catalog helpers |
| Tests | `tests/test_sentinel.py` |
| Needs | Python 3.10 or newer, numpy; numcodecs for Blosc-compressed stores (zarr installs it); tifffile for tifxyz meshes (and imagecodecs for LZW-compressed ones, such as some `ink/unused/manbp` meshes); huggingface_hub 1.33 or newer (bucket listings) for `scan` and `hf:` items. `kit/sentinel_table.py` alone needs only the standard library (numpy for array input) |
| Runs on | Any CPU with network. One S3 segment with every check and `--image`: about 45 s and 200 MB read (measured 2026-11-04, 4-core Claude cloud container); metadata checks alone take a few seconds an item. Larger runs go to a Hugging Face CPU Job (`scripts/sentinel/job.sh`) |
| Network | Hugging Face: the bucket API listing (anonymous) and the bucket's file URLs under `HF_ENDPOINT` (default `https://huggingface.co`), for `meta.json`, `x.tif`, `y.tif`, `z.tif`, zarr metadata and chunks. S3: `metadata.json` and `metadata.min.json` of `vesuvius-challenge-open-data`, and CT volume metadata and chunks. Plain HTTPS GETs; 429, 5xx and dropped connections are asked again up to 5 times |
| Writes | `scan`: the state file (`work/sentinel/state.json` by default). `check --out DIR`: one JSON file per item. `table --out FILE`: the offset table. `controls --out DIR`: one base result per pool item and `controls.json` (or `controls-KofN.json`). Nothing is ever written to a bucket; planted copies live in memory |
| Go-ahead | Not needed: it reads public open data and writes local files. A paid Hugging Face Job follows the launch rules of AGENTS.md rule 11 |
| Released | Public branch `claude/bucket-sentinel` since 2026-11-04 (pull request open, not merged) |
| Checked | 2026-11-04 against commit `d4da5ec` |

## What it does

Community members found five silent defects in published data one at a time, each after it had already cost training runs (Community report, villa issues read 4 November 2026):

- HF65 canvases in the Hugging Face bucket's `ink/` folders do not line up with the tifxyz beside them: 26 of 32 `full_3d` training folders, by up to about 254 px on PHerc. Paris 4, where the offset changes linearly with position because canvas and mesh grid differ in size ([#2370](https://github.com/ScrollPrize/villa/issues/2370), 30 October 2026).
- MAN5_outer_3's label zarrs are 59 px smaller than its canvas on both axes ([#2369](https://github.com/ScrollPrize/villa/issues/2369)).
- In 18 of 33 surface volumes, pyramid level 2 holds the first 17 of 65 depth slices while declaring z-scale 1 ([#2107](https://github.com/ScrollPrize/villa/issues/2107)).
- A store with no unit and a level-0 scale of [1, 1, 1] is read as 1.0, although its pitch is known from its name or `metadata.min.json` ([#2137](https://github.com/ScrollPrize/villa/pull/2137), [#2220](https://github.com/ScrollPrize/villa/pull/2220)).
- Nothing warns when a mesh made in one scan's frame is rendered from another scan ([#1845](https://github.com/ScrollPrize/villa/issues/1845)).

Bucket Sentinel runs these checks on every item, keeps a fingerprint of each so a later `scan` finds what is new or changed, and records the numbers. The canvas check measures, with CT only, where each canvas sits on its tifxyz: it samples the CT through the mesh on the canvas's own pixel lattice and phase-correlates that with the canvas's surface plane, window by window, coarse to fine. It fits a model per folder (aligned, constant, affine, or regions when an affine leaves more than 2 px) and writes it to an offset table, pinned by sha256 to the mesh files it was measured on, that a training loader can import with `kit/sentinel_table.py` (one file, no dependencies). An affine or per-region map is needed: on Paris 4 the offsets change linearly with position (#2370). `preflight` is the render side: before `vc_render_tifxyz`, it says whether the mesh is in the frame of the volume about to be rendered, and runs the render only when it is.

It never reads label voxels: the label check compares shapes only, and alignment uses CT and the canvas. It makes no ink map and reads nothing of any scroll's text; an offset is a data correction. A folder with no table entry is unmeasured, not aligned.

Reserved data. A local exclusion file lists item ids or glob patterns that are never opened (`--exclude FILE`, else `$KIT_SENTINEL_EXCLUDE`, else `work/sentinel/exclude.json` when it exists). Skipped items are reported only as a count, "skipped by rule", with a 16-hex sha256 of their sorted ids, so coverage is stated without naming them. This repository ships no such list. The daily `bucket-sentinel` routine (`docs/routines.json`) runs `scan` only where `work/sentinel/exclude.json` exists and is skipped elsewhere; run `scan` by hand where no folder is reserved.

## When to use it

- After the organizers upload or change data: `scan --exit-code` says what is new or changed (exit 3), and `check --queued` checks it.
- Before training on `ink/` folders with a loader that pairs labels with the tifxyz (villa's `full_3d`): look the folder up in the offset table, `verify` its pins against your copy, and map label pixels to mesh cells with `label_cells`.
- Before rendering a mesh: `preflight -- vc_render_tifxyz ...` runs the render only when the mesh is in the volume's frame.
- To test a fix: `check --plant` runs every check on an in-memory copy with one planted defect.

Do not use it:

- To audit the catalog's cross-scan affine transforms or depth offsets between renders: use [meshaudit](meshaudit.md).
- To check that a mesh follows the papyrus: a mesh in the right frame can still be on the wrong sheet; look at it, or use the fiber checks ([afv-fibers](afv-fibers.md)).
- To score an ink map: use [auc](auc.md).

## Quick start

```bash
python -m kit sentinel check s3:SAMPLE/segments/SEGMENT/surface-volumes/NAME.zarr --image --out OUT
python -m kit sentinel check hf:ink/SCROLL/FOLDER --image --out OUT
python -m kit sentinel table OUT --out offsets.json
```

- `SAMPLE/segments/SEGMENT/surface-volumes/NAME.zarr`: an S3 segment surface volume; its mesh is found in the catalog by the volume id in its name.
- `ink/SCROLL/FOLDER`: a segment folder of the Hugging Face bucket `scrollprize/datasets`.
- `OUT`: a folder for the JSON results.

Run on 2026-11-04 in a 4-core cloud container with `s3:PHerc0343P/segments/20250511003658-tifxyz/surface-volumes/2.215um-0.4m-111keV-volume-20260304131111.zarr`, the first command printed (Model output):

```
s3:PHerc0343P/segments/20250511003658-tifxyz/surface-volumes/2.215um-0.4m-111keV-volume-20260304131111.zarr: ok
  pyramid  ok
  scale    ok
  labels   skip
  frame    ok      matched
  canvas   ok      aligned  max 0.48 px, median dy dx [0.27, 0.28], resid 0.062, 20/20 windows
  blank    ok
0 skipped by rule
```

It worked: the frame check matched the volume the surface volume names, and the canvas reads aligned at about +0.3 px, the renderer's half-pixel convention that #2370 also measured on S3 renders.

## Checks and controls

Every check can fail, and `controls` shows that it does on public data before any run that counts. Each pool segment is checked as published, then as in-memory copies with one planted defect each: canvas shifts of 4 to 300 px, canvases resampled by 0.9 to 1.1, a wrong declared frame, labels on another grid, truncated levels, blank planes and a reset scale, plus negatives that must not flag (an unaltered label, a correct scale, every base canvas). The bars are recall at least 95 percent, offset error at most 2 px in at least 95 percent of caught shift and resample plants, and at most 5 percent flags on negatives and bases ([preregistration](../prereg/2026-11-04-bucket-sentinel.md), section 3).

```bash
python -m kit sentinel controls docs/sentinel/dev-pool.json --out CONTROLS
```

A pass prints a summary with `"pass": true` and exits 0; a fail exits 3, and the rows in `controls.json` say which plant was missed.

Results of 4 November 2026 (Model output; `results.json` `bucket_sentinel_checks`):

- Controls, attempt 2 (attempt 1 failed on three faults in the code, fixed before attempt 2): 252 plants on 20 segments, recall 0.988, median offset error 0.34 px with every caught plant within 2 px, no flags on 56 negatives and bases. PASS.
- Blind back-test on the 14 Hugging Face `ink/` folders our reserved-data rule leaves open, frozen before any of their canvases, meshes or CT was read: 9 of 9 canvases #2370 reports misaligned flagged, 0 of 4 it reports aligned; 5 of 5 pyramids #2107 reports truncated flagged and 0 of 9 others; MAN5_outer_3's labels flagged 59 px short (#2369). PASS on all four bars. The measured offsets agree with #2370's: (-19.20, -19.29) px against about (-19.6, -19.6) for PHerc. 0009B, and slopes 0.00427 and -0.00388 against 0.004263 and -0.003876 for Paris 4 w01_r15.
- Live sweep: every one of the 67 CT volumes the catalog lists in the bucket declares [1, 1, 1] with no unit; `metadata.min.json` gives each one's pitch, and every name agrees with it. No CT volume pyramid has missing levels or slices.

Claim label: Model output, for every offset, verdict and control number this tool prints; the defects it is tested against are a Community report.

## Commands and options

### `python -m kit sentinel scan`

```
usage: python -m kit sentinel scan [-h] [--state STATE] [--no-hf] [--no-s3]
                                   [--exclude EXCLUDE] [--exit-code] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--state STATE` | `work/sentinel/state.json` | the fingerprints of the last scan and the queue of items still to check |
| `--no-hf` | off | leave out the Hugging Face bucket's `ink/` folders |
| `--no-s3` | off | leave out the S3 catalog's CT volumes |
| `--exclude EXCLUDE` | none | local exclusion file (never committed) |
| `--exit-code` | off | exit 3 when anything is new or changed |
| `--json` | off | print the diff (new, changed, gone, queue, items, coverage) as JSON |

### `python -m kit sentinel queue`

```
usage: python -m kit sentinel queue [-h] [--state STATE] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--state STATE` | `work/sentinel/state.json` | the state file `scan` wrote |
| `--json` | off | print the queue as a JSON list |

### `python -m kit sentinel check`

```
usage: python -m kit sentinel check [-h] [--queued] [--state STATE] [--image]
                                    [--plant PLANT] [--exclude EXCLUDE]
                                    [--out OUT] [--exit-code] [--json]
                                    [items ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `items` | none | `hf:ink/SCROLL/FOLDER`, `s3:SAMPLE/segments/SEG/surface-volumes/NAME.zarr` or `s3vol:SAMPLE/volumes/NAME.zarr` |
| `--queued` | off | check what the last scan queued, then clear them |
| `--state STATE` | `work/sentinel/state.json` | the state file whose queue `--queued` reads |
| `--image` | off | also the CT checks: canvas offsets, frame, blank planes |
| `--plant PLANT` | none | a planted-defect JSON, applied to an in-memory copy |
| `--exclude EXCLUDE` | none | local exclusion file; its items are skipped before any read |
| `--out OUT` | none | folder for one JSON result per item |
| `--exit-code` | off | exit 3 when any item has a defect |
| `--json` | off | print every result and the coverage as one JSON document |

### `python -m kit sentinel table`

```
usage: python -m kit sentinel table [-h] --out OUT [--json] results
```

| Option | Default | Meaning |
| --- | --- | --- |
| `results` | required | folder of check results (kit sentinel check --out) |
| `--out OUT` | required | the table file to write |
| `--json` | off | also print the table |

### `python -m kit sentinel preflight`

```
usage: python -m kit sentinel preflight [-h] [--mesh MESH] [--volume VOLUME]
                                        [--force] [--json]
                                        ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--mesh MESH` | none | the tifxyz folder to render (else `-s` of the render command) |
| `--volume VOLUME` | none | the volume to render from, a folder or URL (else `-v` of the render command) |
| `--force` | off | run the render even when the preflight warns |
| `--json` | off | print the result as JSON |
| `render` | none | -- vc_render_tifxyz ARGS: run it when the check passes |

### `python -m kit sentinel controls`

```
usage: python -m kit sentinel controls [-h] --out OUT [--exclude EXCLUDE]
                                       [--limit LIMIT] [--shard SHARD]
                                       [--per-item PER_ITEM] [--json]
                                       pool
```

| Option | Default | Meaning |
| --- | --- | --- |
| `pool` | required | JSON list of items (hf:... or s3:...) for the controls |
| `--out OUT` | required | folder for the base results and the controls file |
| `--exclude EXCLUDE` | none | local exclusion file |
| `--limit LIMIT` | `0` | use only the first LIMIT pool items (0: all) |
| `--shard SHARD` | none | K/N: run pool items K, K+N, K+2N, ... (parallel processes) |
| `--per-item PER_ITEM` | `3` | image plants per pool item, rotating through the list |
| `--json` | off | accepted for symmetry; the summary is always printed as JSON |

### `python -m kit sentinel summarize`

```
usage: python -m kit sentinel summarize [-h] files [files ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `files` | required | the `controls*.json` files of several shards, pooled into one summary |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `SentinelError()` | an exception | | every refusal of this module |
| `sha256_bytes(b)` | hex sha256 | | |
| `Rule(patterns=(), source=None)` | an exclusion rule | | Item ids that are never opened: fnmatch globs against the item id. `Rule.load(path)`, `excluded(id)`, `coverage()` |
| `Store(url, src=None)` | a store | `VerifyError` on bad JSON | An OME-Zarr (or plain zarr v2 array) at a URL or folder: per-level metadata, declared scales and axis units |
| `Level(src, path, zarray, workers=16, cache_mb=160)` | an array reader with `read(z0, z1, y0, y1, x0, x1)` | `SentinelError` | One array of a store, read by box with an in-memory chunk cache |
| `check_pyramid(meta)` | check result | | Each level's shape against level 0 under its declared scale (#2107) |
| `true_z_factor(meta, k)` | float | | The z factor level k really has: its declared one, or 1 when it is truncated |
| `known_pitch(name, volume_id=None, minmeta=None, catalog=None)` | (um, source) | | From metadata.min.json, then metadata.json, then the store's name; else (None, None) |
| `name_pitch(name)` | um or None | | The pitch a store's name states |
| `check_scale(meta, pitch=None, pitch_source=None, kind='volume', named=None)` | check result | | [1, 1, 1] with no unit, or a declared pitch that disagrees, on a store whose pitch is known |
| `check_labels(canvas_shape, labels, grid_shape=None)` | check result | | Label zarrs against the canvas (#2369), and the canvas against the tifxyz grid (#2370) |
| `gaussian_blur(a, sigma)` | array | | separable Gaussian, reflected edges |
| `prep(a, valid=None)` | array | | High-passed, mean-filled window for registration |
| `register(ct, canvas, search, valid=None)` | (dy, dx, psr) | | canvas(y, x) shows ct(y + dy, x + dx), in window pixels, by phase correlation within +-search |
| `Mesh(xyz, scale, meta=None, pins=None)` | a mesh | | A tifxyz grid in level-0 voxels (NaN where invalid), its scale, `stretch`, `bbox()`, `points(cy, cx)` |
| `sample_ct(level, factor, pts)` | array | `SentinelError` for a window over 256 cubed voxels | Trilinear CT at level-0 points (..., x y z); NaN outside |
| `Canvas(store, meta=None, transform=None, shape=None, blank_planes=None)` | a canvas reader | `SentinelError` | The surface plane as level-F windows from the best pyramid level |
| `ct_window(mesh, ct, F, r0, c0, n, model)` | array | `SentinelError` | CT sampled through the mesh on the canvas lattice at F px, moved by the model's offset |
| `fit_model(rows)` | (coef, keep, residuals, rms) | | Least-squares affine per axis over windows, one trimming pass (3 MAD, at least 1 px) |
| `check_canvas(canvas, mesh, ct, prior=True, log=None)` | check result | | Where the canvas sits on its tifxyz; `ct` maps F to a CT level (`ct_source`) |
| `check_blank(canvas, level=None, probe=None)` | check result | | Planes that read blank between data planes, or where level 0 has data |
| `hf_url(path)` | URL | | a file URL of the Hugging Face bucket |
| `fetch_bytes(url, tries=5)` | bytes, or None for 403 and 404 | `SentinelError` after the retries | |
| `load_mesh(base_url, fetch=fetch_bytes)` | `Mesh` | `SentinelError` | A tifxyz folder with sha256 pins of its four files; the last two are kept in memory |
| `hf_listing(prefix, api=None)` | list | | [(path, type, size, xet_hash)] directly under a bucket prefix |
| `sample_of(folder)` | sample id | | Catalog sample id for an HF ink/ scroll folder name |
| `discover_hf(api=None, root='ink')` | item ids | | Segment folders under ink/, and ink/unused/ one level deeper |
| `hf_item(path, api=None)` | dict | | One HF segment folder: canvas zarr, label zarrs, tifxyz, listing digest |
| `fingerprint_hf(item)` | 16-hex | | An HF folder's listing and every zarr's metadata |
| `catalog_volumes(catalog, sample)` | list | | [(volume id, zarr URL, pixel_um)] of a catalog sample |
| `declared_volume(mesh, candidates)` | (volume id or None, how) | | An `-on-<14 digits>` name or meta.json's volume string matched to one candidate |
| `ct_source(url)` | function F -> (Level, factor) | | The CT level nearest F level-0 voxels per voxel, cached |
| `ct_level(url, want=4.0)` | ((Level, factor), Store) | | One CT level and its store |
| `frame_candidates(mesh, catalog, sample)` | list | | the sample's volumes whose level-0 shape holds the mesh's bounding box (5 percent margin) |
| `check_frame(canvas, mesh, candidates, declared, log=None)` | check result | | Which candidate's CT matches the canvas through this mesh (median PSR of three coarse windows) |
| `plant_canvas(canvas, plant)` | (planted copy, truth) | `SentinelError` for an unknown kind | In memory; the source is never written |
| `check_item(item_id, rule=None, image=False, plant=None, catalog=None, minmeta=None, log=None, api=None, image_checks=('frame', 'canvas', 'blank'))` | result | `SentinelError` | Every check on one item; an excluded item is refused before any read |
| `s3_mesh_for(path, catalog)` | (mesh URL, sample) | `SentinelError` | The segment's mesh named for the surface volume's volume |
| `table_entry(res)` | entry or None | | None when the canvas was not measured or the result is a planted copy |
| `build_table(results, source='kit sentinel')` | table document | | |
| `scan(state_path=STATE, hf=True, s3=True, rule=None, api=None, get=None)` | diff | | Fingerprints everything, compares with the last scan, writes the state file |
| `preflight(mesh_dir, volume, fetch=fetch_bytes, listing=None)` | check result | | Before vc_render_tifxyz: is this mesh in the frame of this volume? Metadata only (#1845) |
| `render_args(argv)` | (segmentation, volume) | | from a vc_render_tifxyz command line |
| `image_plants(seed=20261104)` | list | | Shifts in random directions, resampled canvases, a wrong frame |
| `plants_for(i, per_item=3, seed=20261104)` | list | | Pool item i's plants: per_item image plants, rotating, then every metadata plant |
| `control_plants(seed=20261104)` | list | | Every planted defect kind with its parameters (fixed by the preregistration) |
| `other_volume(catalog, item_id, ct_volume)` | volume id or None | | Another volume of the same sample, for the frame plant |
| `score_plant(base, planted)` | (caught, error px, what) | | Did the planted copy's checks catch its plant? |
| `build_parser(p)` | parser | | the subcommands, for `kit/cli.py` |
| `run(args)` | exit code | | |
| `run_controls(args)` | exit code | | the base, then every plant, per pool item |
| `summarize_controls(rows)` | summary with `pass` | | the preregistered bars |
| `cmd_sentinel(args)` | exit code | | `run`, with a `SentinelError` printed and exit 2 |
| `main(argv=None)` | exit code | | `python -m kit.sentinel` |
| `TableError()` | an exception | | `kit/sentinel_table.py`: a bad table or model |
| `Entry(doc)` | a table entry | `TableError` | `cell(y, x)`, `pixel(cy, cx)`, `offset(y, x)`, `verify(folder)`; scalars or numpy arrays |
| `Table(doc)` | a table | `TableError` for another schema | `lookup(path)` finds a folder's entry |
| `load(path_or_url)` | `Table` | `TableError` | from a local path or an https:// URL |
| `label_cells(entry, y0, y1, x0, x1)` | (cell_y, cell_x) arrays | `TableError` without numpy | For a label window on the canvas grid: the tifxyz full-resolution cells its pixels show |

## Inputs

- **Items.** `hf:ink/SCROLL/FOLDER` (also `hf:ink/unused/SCROLL/FOLDER`): a segment folder of `scrollprize/datasets` with the canvas `FOLDER.zarr` (planes x rows x cols, uint8; the surface is plane 32 of 65, else the middle plane), label zarrs on the canvas grid (names with `inklabels`, `supervision`, `validation` or `mask`; only their shapes are read) and a tifxyz (`x.tif`, `y.tif`, `z.tif`: float32 points in level-0 voxels of one scan, -1 or 0 where invalid; `meta.json` with `scale` [x, y] in grid nodes per voxel). `s3:...`: an S3 surface volume and the mesh the catalog names for its volume. `s3vol:...`: an S3 CT volume (metadata checks only).
- **Coordinate convention** (villa #2370's): canvas content at level-0 pixel (y, x) lies where the tifxyz puts full-resolution cell (y + dy, x + dx); a full-resolution cell is a grid index divided by `scale`. A level pixel with factor f covers level-0 pixels [i f, (i + 1) f) and is centered at i f + (f - 1) / 2.
- **CT.** The scan volume the mesh was made in: among the sample's catalog volumes whose shape holds the mesh's bounding box, the best match to the canvas (the frame check), read at the pyramid level nearest the window's pixel size times the mesh's stretch.
- **Exclusion file.** JSON `{"patterns": ["hf:ink/SCROLL/*", ...]}` or a bare list; local only.
- **Environment.** `HF_ENDPOINT` (the Hub's address, as huggingface_hub reads it), `KIT_SENTINEL_EXCLUDE` (the exclusion file), `SENTINEL_OUT` (`scripts/sentinel/job.sh`'s output folder, default `/tmp/sentinel-out`).

## Outputs

Each check result (one JSON per item with `--out`):

| Field | Type | Meaning |
| --- | --- | --- |
| `item` | string | the item id |
| `verdict` | string | `defect` when any check has verdict defect, else `ok` |
| `defects` | list | `check:kind` of every defect, such as `canvas:affine` or `pyramid:missing_slices` |
| `checks` | list | one object per check: `check` (pyramid, scale, labels, frame, canvas, blank), `verdict` (ok, defect, info, skip), `kind` and the numbers below |
| `checks[canvas].affine` | object | `dy` and `dx`, each [a, b, c]: offset = a + b y + c x, level-0 px |
| `checks[canvas].kind` | string | aligned, constant, affine, regions, or not_measured |
| `checks[canvas].max_offset`, `median_offset`, `resid_rms`, `span` | numbers | level-0 px over the accepted windows |
| `checks[canvas].windows` | list | per window: center `y`, `x`, measured `dy`, `dx`, `psr`, `accepted` |
| `checks[labels].problems` | list | `label_shape`: label, shape, canvas, `short_by` [rows, cols] |
| `checks[labels].drift_slope` | list | grid size over canvas size, minus 1, per axis |
| `checks[pyramid].problems` | list | `missing_slices` (level, axis, have, want, declared_factor, covers), `extra_slices`, `missing_level` |
| `checks[scale]` | object | `declared`, `units`, `known_pitch_um`, `pitch_source`; for a defect `kind` (scale_reset, scale_mismatch, no_scale) and `fallback_um` |
| `checks[frame]` | object | `declared`, `declared_how`, `matched`, `candidates` (volume, psr) |
| `pins` | object | sha256 of `meta.json`, `x.tif`, `y.tif`, `z.tif` |
| `ct_volume` | string | the volume id the canvas check read |

The offset table (`table`, schema `bucket-sentinel-offsets/1`) has `entries`, each with `path`, `model`, `affine`, `grid` (regions only: window centers `y`, `x` and residuals `dy`, `dx`, null where not measured), `resid_rms`, `max_offset`, `n_windows`, `ct_volume`, `pins`, `listing_digest` and `checked`.

| Exit code | Meaning |
| --- | --- |
| `0` | the run finished; with `--exit-code`, no defect was found (`check`) or nothing changed (`scan`) |
| `2` | bad arguments, or a `SentinelError` (printed as `kit sentinel: ...`) |
| `3` | with `--exit-code`: a defect (`check`) or a new or changed item (`scan`); `preflight` warned; `controls` or `summarize` failed a bar |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `unknown plant kind...` | `--plant` names a kind the module does not plant | Use one of `control_plants()`'s kinds |
| `...: no mesh named for volume...in...` | The catalog lists no `-on-VOLUME` mesh for this surface volume's segment | Check the item path |
| `a window spans...voxels at this level; use a smaller window` | The mesh is nearly edge-on to the volume, or jumps, inside one window | The window is skipped and listed in `skipped_windows`; a folder with too few windows reads not_measured |
| `.../meta.json is not there` | The folder has no meta.json | It is not a tifxyz; check the path |
| `an s3: item needs the catalog (metadata.json)` | Called from Python without a catalog | Pass `catalog=` |
| `kit sentinel check: no items (give hf:PATH, s3:PATH or s3vol:PATH, or --queued)` | Nothing to check | Give items, or run `scan` first |
| `kit sentinel preflight: give --mesh and --volume, or -- vc_render_tifxyz -s MESH -v VOLUME ...` | Neither the options nor a render command name both | Give both |
| `kit sentinel:...` | A refusal from the module | Read the message |
| `kit sentinel needs numpy (pip install numpy)` | numpy is missing | `pip install numpy` |
| `.../...: no .zarray` | A level the multiscales list names has no array | The store is incomplete; the pyramid check reports `missing_level` |
| `...: no level at factor <=...holds plane...` | No level at or finer than the window's pixel size holds the surface plane | The pyramid is truncated below the surface; the pyramid check reports it |
| `.../....tif is not there` | A tifxyz file is missing | Check the folder |
| `...: no pitch in the name for a fix_scale plant` | The plant needs a pitch | Give `"pitch"` in the plant |
| `.../...:...values, want...` | A chunk decoded to the wrong size | The chunk or its compressor setting is broken; report it |
| `...: an item is hf:PATH, s3:PATH or s3vol:PATH` | An item without a known prefix | Prefix it |
| `this store is compressed: pip install numcodecs (zarr installs it)` | A Blosc store without numcodecs | `pip install numcodecs` |
| `label_cells needs numpy` | `label_cells` without numpy | Install numpy, or call `Entry.cell` on scalars |
| `...: model...is not one of...` | A table entry with an unknown model | Rebuild the table with this version |
| `not a Bucket Sentinel offset table (schema..., want...)` | Another JSON file | Give the file `table` wrote |

## How it works

1. **Change detection.** `scan` lists the bucket's `ink/` folders through the Hub API and fingerprints each by its listing (names, sizes, Xet hashes) and every zarr's root and level metadata; it fingerprints each S3 CT volume by its metadata. New and changed items join the queue. A change only to chunk files under unchanged metadata is not seen.
2. **Pyramid.** For each level, the declared scale against level 0 gives a factor per axis; a level whose shape times its factor covers less than level 0 by more than one step is `missing_slices` (#2107's 17 of 65 at z-scale 1). Such a level's true z factor is 1 (its planes are the first ones, not pooled), and the canvas check uses that to find the surface plane.
3. **Scale.** A level-0 scale of [1, 1, 1] with no axis unit is `scale_reset` when the pitch is known: `pixel_size_um` of the volume (or its scan) in `metadata.min.json`, else `metadata.json`, else a pitch in the store's name; the fallback is reported as `fallback_um`, and a name that disagrees with the manifest as `name_disagrees`. A store not found at its catalog path is `not_read`, not a defect. A canvas grid with no known pitch is info only.
4. **Labels.** Every label zarr's level-0 rows and columns against the canvas's (`SHAPE_TOL` = 1 px), and the canvas against the tifxyz grid (rows / scale_y, cols / scale_x; `GRID_TOL` = 2 px), whose ratio minus 1 is the drift slope.
5. **Frame.** Candidates are the sample's volumes whose level-0 shape holds the mesh's bounding box (5 percent margin). For each, three canvas windows at 16 px are registered against that volume's CT sampled through the mesh; the best median peak-to-sidelobe ratio (PSR), at least `PSR_MIN` = 8, is the mesh's frame. A mesh that declares another volume (an `-on-VOLUME` name, or meta.json's volume string matched by pitch, energy and masking) that does not match is `wrong_frame`.
6. **Canvas offsets.** Coarse pass at 16 level-0 px per pixel: 3 x 3 windows of 96 px, peak within 40 px (640 level-0 px), started both from no offset and from the size-ratio prior (offset = slope times position), keeping the start with more accepted windows. Fine pass at 4 px: 5 x 5 windows of 128 px over the mesh's extent, peak within 24 px, each window's CT resampled at the coarse model's offset, then once more at the measured offset to refine near zero. Registration is phase correlation of high-passed (`SIGMA` = 4 px), mean-filled, Hann-tapered windows with a parabolic peak fit. A window counts with PSR at least 8, its peak inside the search, and at least `FILL_MIN` = 90 percent valid mesh and nonzero canvas. With at least `MIN_WINDOWS` = 6 windows an affine is fitted per axis (one trim at 3 MAD). Aligned when every window and the model at the windows' corners are within `ALIGN_TOL` = 2 px; else constant when the affine changes less than `CONST_SPAN` = 2 px over the windows; affine when its residual RMS is at most `RESID_TOL` = 2 px; else regions. The CT level follows the mesh's stretch (median voxels per full-resolution cell), so a stretched mesh reads a coarser level.
7. **Blank planes.** A 32 x 32 probe at the mesh's center, every level, all planes: a plane that reads all zero between two data planes, or where level 0 has data at its depth, is `blank_plane`.
8. **Planted copies.** A shift or resample is a coordinate transform on the canvas reader (bilinear); a truncated level or a scale plant edits a copy of the metadata; a blank plane is zeroed in the reader. The truth for a shift P is the base model moved by P; for a resample by s, offset(y) = y / s - y + base(y / s).

## Cost and time

Measured 2026-11-04 in a 4-core Claude cloud container: one S3 segment with `--image` about 45 s; a planted copy about 40 s more (the CT is read again). Metadata checks take a few seconds an item. Hugging Face CPU Jobs (`cpu-upgrade`, 8 vCPU) run `scripts/sentinel/job.sh` in parallel shards; the first development run took 179 s of Job time (preregistration, section 4).

## For agents

- **Command:** `python -m kit sentinel check ITEM --image --out OUT --json`; scheduled: `python -m kit sentinel scan --exit-code`, then `python -m kit sentinel check --queued --image --out OUT`.
- **Parse:** `results[].verdict`, `results[].defects`, and per check `verdict` and `kind`; the canvas check's `affine` and `max_offset`; `coverage.skipped_by_rule`.
- **Rerun:** safe; `check --out` overwrites that item's file; `scan` rewrites the state file and keeps the queue.
- **Success:** exit 0 and every item's verdict present; with `--exit-code`, 3 means defects or changes were found, not a crash.
- **Not a pass:** a canvas `not_measured` (too few windows, or no CT volume) is not aligned; a scale `info` is not a verified pitch; a table entry whose `verify` reports problems describes other files.
- **Go-ahead:** Nothing for local runs; a paid Job follows the launch rules.
- **Never:** never commit an exclusion file or name skipped items; never treat an offset or a canvas as a reading of a scroll; never post to villa without Chase (draft: [docs/contrib/villa-2370-offset-table.md](../contrib/villa-2370-offset-table.md)).

## Tests

`python -m unittest tests.test_sentinel -v` (about 20 s, no network): synthetic CT, mesh and canvases with known offsets (aligned, constant, affine, a size drift, planted shifts and resamples recovered within 2 px), the #2107 and #2369 shapes, scale reset and mismatch, blank planes at level 0 and 1, absent chunks, a Blosc store, the exclusion rule (an excluded item is never opened and never named), scan change detection, preflight (#1845 naming, a sibling mesh, the bounding box, the render refused on a warning), the offset table (lookup, inverse, regions, pins, label cells) and the control summary's bars. Not covered: live bucket reads, which the controls and the back-test run.

## History

- 2026-11-04: first version on branch `claude/bucket-sentinel`: scan, check, table, preflight, controls and the loader table (`09fd9b9`); fixes from the first development run (`9fcc215`); controls and back-test PASS, offset table of 13 folders; the scale check reads `metadata.min.json` first and skips stores not in the bucket.

## Related

- [meshaudit](meshaudit.md): the catalog's transforms, canvases and render depths, run by hand.
- [tifxyz](tifxyz.md): the chunk reader this reuses, and mesh geometry checks.
- [hfpull](hfpull.md): pulling a bucket folder to disk fast.
- [labels](labels.md): which published labels exist and which readers saw them.
- [Preregistration](../prereg/2026-11-04-bucket-sentinel.md): the controls, the back-test and their outcome.
