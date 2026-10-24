# tifxyz: look at a tifxyz segment without building VC3D

`python -m kit tifxyz` reads a segment's three TIFFs (local or on the open-data bucket) and reports its area in cm2, isometry, holes, folds and stretch, writes an OBJ or a picture, lists the volume chunks it touches (and fetches only those), and compares two versions.

| Field | Value |
| --- | --- |
| Id | `tifxyz` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit tifxyz info`, `python -m kit tifxyz stretch`, `python -m kit tifxyz isometry`, `python -m kit tifxyz check`, `python -m kit tifxyz obj`, `python -m kit tifxyz preview`, `python -m kit tifxyz facing`, `python -m kit tifxyz chunks`, `python -m kit tifxyz diff`, `python -m kit.tifxyz`, `from kit import tifxyz` |
| Code | `kit/tifxyz.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_tifxyz.py`, `tests/test_tifxyz_chunks_diff.py` |
| Needs | Python 3.10 or newer, numpy and tifffile; scipy when installed (finds holes faster; a numpy fallback gives the same answer). No VC3D, villa or GPU |
| Runs on | Any CPU. On PHerc0139 w035's 2.399 um mesh (1,132 x 1,020 nodes): `info` 1.36 s, `stretch` 1.30 s, `check` 1.05 s, `preview` 1.41 s, `facing` 0.90 s, `obj` 4.15 s (a 134 MB file); peak memory under 270 MB (measured 2026-10-23, 4-core Intel Xeon at 2.10 GHz cloud container, each a fresh process). `chunks` against the 2.399 um volume on the bucket: 5.8 s at level 5, 5.4 s at level 3, 45 s at level 1 (9,335 HEAD requests), 184 s at level 0 (39,590); `--fetch` of level 5's 71 MB in 7.6 s (measured 2026-10-24, same container) |
| Network | Only for a segment given as an `https://` or `s3://` URL: its four files from `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`, once, into `--cache`. `chunks` on a volume URL: its metadata files, one HEAD per touched chunk (at most `--max-requests`, 32 at a time), and with `--fetch` one GET per present chunk; 429, 5xx and dropped connections are asked again up to 5 times |
| Writes | `--cache` (default `work/tifxyz/cache`) for bucket segments; `obj` its OUT file; `preview` its OUT file; `check --png` and `diff --png` that file; `chunks --fetch` the DEST folder (metadata and the touched chunks, keeping their keys). Nothing else |
| Go-ahead | Not needed: it reads public data and writes local files |
| Released | Public `main` from the change that adds it (23 Oct 2026) |
| Checked | 2026-10-23 against commit `3376687` |

## What it does

A tifxyz segment is how villa and VC3D store a traced papyrus surface: a folder of three float32 TIFFs, `x.tif`, `y.tif` and `z.tif`, one grid of 3D points in voxels of one scan volume, and a `meta.json` whose `scale` says how many grid nodes there are per voxel (0.05 means one node every 20 voxels). Looking at one usually means building VC3D. People on the Discord report segment areas by guess ("0.81cm^2", "7cm^2", 20 to 23 Oct 2026), ask whether there is a numeric check of the "low-distortion isometric 2D parametrization" the prize rules mention (22 Oct), and post screenshots asking "is this a good or bad segmentation?" (22 Oct).

`kit tifxyz` answers those from the three TIFFs alone, on any machine with numpy:

- `info`: the surface's real 3D area (cm2, mm2 and voxels squared), grid size, filled share, bounds and voxel size, with `meta.json`'s own `area_vx2` beside ours as a check.
- `stretch`: every grid edge's 3D length over the step `meta.json` promises (1.0 is exact), cell area over the promised area, and the angle between the two grid directions, as percentiles.
- `isometry`: the block proposed for `meta.json` in villa issue [#2279](https://github.com/ScrollPrize/villa/issues/2279), version 1: edges within 10 % and 25 % of the step, the median |log(edge / step)|, triangle area over the promised area, grid angle p5, p50 and p95, nodes flagged at 1.5x, and flatboi's stretch metrics (L2 mean and median, Linf, area error) with the grid itself as the flattening, so a perfect grid gives 1, 1, 1 and 0.
- `check`: holes inside the sheet, folds (neighboring cells whose normals turn by more than 90 degrees) and over-stretched nodes (an edge 1.5 times too long or too short), each counted and in mm2, with an optional picture.
- `obj`: a Wavefront OBJ with UVs for Blender or MeshLab.
- `preview`: a shaded PNG of the sheet, holes dark.
- `facing`: given the scroll's center line, the share of grid normals that point away from it, and whether the angle about the center grows along grid columns.
- `chunks`: which chunks of a zarr volume (local, or on the bucket) the sheet touches, at any pyramid level and within a margin, with their count and stored bytes before anything is downloaded; `--fetch DEST` then copies the volume's metadata and only those chunks, keeping the zarr key layout, so a zarr reader opens DEST as the same volume with every other chunk read as the fill value (checked with zarr-python 3.4.1 on 24 Oct 2026; VC3D on such a copy was not tried). Rendering or inspecting one segment no longer needs the whole volume or a guess at a bounding box.
- `diff`: two versions of one segment on one volume (a regrown trace, a fixed one, a tool's output against its input): area change, nodes added and removed, and how far the kept nodes moved, node by node when the grids have one shape, by position when they do not, with a picture of where.

It is geometry only: no CT, no ink, no judgment of whether the surface follows the papyrus. Nothing here is an official villa or prize check. A clean `check` means the grid has no holes, folds or badly stretched cells, not that the trace is on one sheet.

## When to use it

- To report a segment's area in cm2 from its mesh, not from a screenshot.
- Before sharing or submitting a segment: holes, folds and stretch in one line each, and a picture of where.
- To open a segment in Blender or MeshLab on a Mac without building VC3D: `obj`.
- To know which way a mesh's normals face relative to the scroll center before choosing a render direction: `facing`.
- On any published segment straight from the bucket: give its `s3://` or `https://` folder.
- To download only the part of a volume a segment needs, and to know its size first: `chunks`.
- To see what changed between two versions of a trace before you replace one with the other: `diff`.

Do not use it:

- To check a stack of segments against each other and the umbilicus (order, skipped windings, missing sectors): use [`stackcheck`](stackcheck.md).
- To check a flattened sheet's UV triangles: use [`uvgate`](uvgate.md).
- To audit published meshes against their renders and transforms: use [`meshaudit`](meshaudit.md).
- To tell whether two segments trace the same papyrus: use [`overlap`](overlap.md).
- To judge ink: nothing here looks at the CT or a model's output.

## Quick start

```bash
S=s3://vesuvius-challenge-open-data/PHerc0139/segments/20260317000000-w035_2026031718/mesh/20260317000000-on-20260102150214-2.399um.tifxyz
python -m kit tifxyz info "$S"
python -m kit tifxyz check "$S" --png check.png
python -m kit tifxyz preview "$S" sheet.png
```

`S` is PHerc0139 segment w035's mesh on the 2.399 um scan (public, not prize-eligible). On 23 Oct 2026 `info` printed:

```
  grid       1132 x 1020 nodes, 83.5 % filled, step 20 x 20 voxels, 2.399 um voxels
  area       22.07 cm2 (2207 mm2), 383417151 voxels^2
  meta.json  area_vx2 383433352: ours is 1.0000 of it
  bounds     x 8572 to 18695, y 8627 to 17565, z 8506 to 28933
  volume     20260102150214
```

(the first line of each report is the segment as given) and `check` printed:

```
  ok   holes     0 nodes (0.00 %, 0.0 mm2): missing nodes inside the sheet
  ok   folds     0 nodes (0.00 %, 0.0 mm2): nodes where the sheet turns by more than 90 deg between cells
  flag stretched 43 nodes (0.00 %, 0.1 mm2): nodes with an edge over 1.5x too long or short
  not clean: see the flags above
  picture   check.png
```

exiting 1 because 43 nodes have an edge over 1.5 times the step.

The chunks of the 2.399 um volume that w035 touches, at level 5 (one voxel per 32), and a local copy of them:

```bash
V=s3://vesuvius-challenge-open-data/PHerc0139/volumes/20260102150214-2.399um-0.2m-78keV-masked.zarr
python -m kit tifxyz chunks "$S" "$V" --level 5
python -m kit tifxyz chunks "$S" "$V" --level 5 --fetch w035-level5.zarr
```

On 24 Oct 2026 the first printed (after the segment line):

```
  volume     s3://vesuvius-challenge-open-data/PHerc0139/volumes/20260102150214-2.399um-0.2m-78keV-masked.zarr, level 5 (1/32 of level 0), chunks 128 x 128 x 128 (z, y, x)
  touched    34 of 931 chunks within 0 voxels of the sheet
  stored     34 present, 71.3 MB; 0 absent (read as the fill value)
```

and the second wrote those 34 chunks (71.3 MB) with the volume's metadata into `w035-level5.zarr`, which `zarr.open` read as a (2405, 829, 829) uint8 array. The same mesh touches 576 of 51,376 chunks at level 3 (1.2 GB), 9,335 of 3,255,616 at level 1 (19.6 GB) and 39,590 of 26,044,928 at level 0 (83.0 GB, against about 54.6 TB for every chunk of level 0 at the same 2 MiB each; the volume's chunks are stored uncompressed). There is no live `diff` example: the bucket keeps one mesh per segment and volume. The picture below is the synthetic one in [Segments without VC3D](../segments-without-vc3d.md).

It worked when `info` gives an area and its ratio to `meta.json`'s is near 1, and `check` exits 0 or 1 with three lines.

## Checks and controls

- **Area against the file's own number.** `info` sums two triangles per complete grid cell and prints the ratio to `meta.json`'s `area_vx2`, which VC3D writes. On w035 the ratio is 0.9994 on the 9.362 um mesh and 1.0000 on the 2.399 um mesh, and the two meshes give 21.97 and 22.07 cm2 for one surface (23 Oct 2026). A ratio far from 1 means the grid or the file is not what it claims.
- **Every flag can fire.** `tests/test_tifxyz.py` plants a 12-node hole, a fold, and a stretched column into a flat isometric sheet; each is caught by its own check and the others stay quiet, and the clean sheet passes all three. A gap at the grid's border is not counted as a hole.
- **Facing has a mirror control.** The tests build a cylinder about a known center: its normals face one way at 100 % and its column-flipped copy the other way, summing to 1.
- **Stretch reads exact on a perfect grid.** A flat sheet at the promised step gives median 1.0 and 100 % of edges within 10 %.
- **Chunks: the right ones and no others.** `tests/test_tifxyz_chunks_diff.py` puts a flat sheet at z = 40 in a zarr with 16-voxel chunks: it touches exactly the 28 chunks of layer 2, a 10-voxel margin adds layers 1 and 3 and never a farther one, level 1 halves the coordinates, absent chunks are counted as absent, the "/", "." and v3 "c/" key layouts are followed, and `--fetch` writes the metadata and those 28 chunks only, then skips them on a second run.
- **Diff: each change in its own number.** A copy is "same"; a planted 20-node removal, a 12-node addition and a 12-node shift of 5 voxels are each counted exactly, and a tolerance above the shift makes the moved count 0. Across grids, an extension by 10 columns counts 128 to 160 added nodes and nothing removed, and a copy 360 voxels away counts every node added and removed. The position test is checked against brute-force distances: a node it calls far is more than the tolerance from every node, and one it calls near is within 2 sqrt(3) times it.

Claim label: Sourced fact for the numbers it prints about a given mesh (they are computed from the files); Interpretation for any judgment that a segment is good or bad.

## Commands and options

### `python -m kit tifxyz info`

```
usage: python -m kit tifxyz info [-h] [--voxel-um VOXEL_UM] [--cache CACHE]
                                 [--json]
                                 segment
```

| Option | Default | Meaning |
| --- | --- | --- |
| `segment` | required | tifxyz folder, or its https:// or s3:// URL on the open-data bucket |
| `--voxel-um VOXEL_UM` | none | voxel size (default: the folder name's -N.NNNum.tifxyz) |
| `--cache CACHE` | `work/tifxyz/cache` | where bucket segments are kept |
| `--json` | off | print the report as JSON (fields under Outputs) |

### `python -m kit tifxyz stretch`

```
usage: python -m kit tifxyz stretch [-h] [--voxel-um VOXEL_UM] [--cache CACHE]
                                    [--json]
                                    segment
```

| Option | Default | Meaning |
| --- | --- | --- |
| `segment` | required | tifxyz folder, or its https:// or s3:// URL on the open-data bucket |
| `--voxel-um VOXEL_UM` | none | voxel size (default: the folder name's -N.NNNum.tifxyz) |
| `--cache CACHE` | `work/tifxyz/cache` | where bucket segments are kept |
| `--json` | off | print the report as JSON |

### `python -m kit tifxyz isometry`

```
usage: python -m kit tifxyz isometry [-h] [--voxel-um VOXEL_UM]
                                     [--cache CACHE] [--json]
                                     [--max-stretch MAX_STRETCH]
                                     segment
```

| Option | Default | Meaning |
| --- | --- | --- |
| `segment` | required | tifxyz folder, or its https:// or s3:// URL on the open-data bucket |
| `--voxel-um VOXEL_UM` | none | voxel size (default: the folder name's -N.NNNum.tifxyz) |
| `--cache CACHE` | `work/tifxyz/cache` | where bucket segments are kept |
| `--json` | off | print the block as JSON |
| `--max-stretch MAX_STRETCH` | `1.5` | a stretched node has an edge this many times too long or short |

### `python -m kit tifxyz check`

```
usage: python -m kit tifxyz check [-h] [--voxel-um VOXEL_UM] [--cache CACHE]
                                  [--json] [--max-stretch MAX_STRETCH]
                                  [--fold-deg FOLD_DEG] [--png PNG]
                                  segment
```

| Option | Default | Meaning |
| --- | --- | --- |
| `segment` | required | tifxyz folder, or its https:// or s3:// URL on the open-data bucket |
| `--voxel-um VOXEL_UM` | none | voxel size (default: the folder name's -N.NNNum.tifxyz) |
| `--cache CACHE` | `work/tifxyz/cache` | where bucket segments are kept |
| `--json` | off | print the report as JSON |
| `--max-stretch MAX_STRETCH` | `1.5` | flag an edge this many times too long or short |
| `--fold-deg FOLD_DEG` | `90.0` | flag neighboring cells whose normals differ by more |
| `--png PNG` | none | write a picture of the flags here |

### `python -m kit tifxyz obj`

```
usage: python -m kit tifxyz obj [-h] [--voxel-um VOXEL_UM] [--cache CACHE]
                                [--json] [--stride STRIDE]
                                segment out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `segment` | required | tifxyz folder, or its https:// or s3:// URL on the open-data bucket |
| `--voxel-um VOXEL_UM` | none | voxel size (default: the folder name's -N.NNNum.tifxyz) |
| `--cache CACHE` | `work/tifxyz/cache` | where bucket segments are kept |
| `--json` | off | print what was written as JSON |
| `out` | required | the .obj file to write |
| `--stride STRIDE` | `1` | keep every Nth grid row and column |

### `python -m kit tifxyz preview`

```
usage: python -m kit tifxyz preview [-h] [--voxel-um VOXEL_UM] [--cache CACHE]
                                    [--json] [--size SIZE]
                                    segment out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `segment` | required | tifxyz folder, or its https:// or s3:// URL on the open-data bucket |
| `--voxel-um VOXEL_UM` | none | voxel size (default: the folder name's -N.NNNum.tifxyz) |
| `--cache CACHE` | `work/tifxyz/cache` | where bucket segments are kept |
| `--json` | off | print what was written as JSON |
| `out` | required | the .png file to write |
| `--size SIZE` | `1200` | longest side in pixels (0 keeps one pixel per node) |

### `python -m kit tifxyz facing`

```
usage: python -m kit tifxyz facing [-h] [--voxel-um VOXEL_UM] [--cache CACHE]
                                   [--json] --umbilicus UMBILICUS
                                   segment
```

| Option | Default | Meaning |
| --- | --- | --- |
| `segment` | required | tifxyz folder, or its https:// or s3:// URL on the open-data bucket |
| `--voxel-um VOXEL_UM` | none | voxel size (default: the folder name's -N.NNNum.tifxyz) |
| `--cache CACHE` | `work/tifxyz/cache` | where bucket segments are kept |
| `--json` | off | print the report as JSON |
| `--umbilicus UMBILICUS` | required | center line JSON (path or URL) in the segment's volume |

### `python -m kit tifxyz chunks`

```
usage: python -m kit tifxyz chunks [-h] [--voxel-um VOXEL_UM] [--cache CACHE]
                                   [--json] [--level LEVEL] [--margin MARGIN]
                                   [--max-requests MAX_REQUESTS]
                                   [--fetch DEST]
                                   segment volume
```

| Option | Default | Meaning |
| --- | --- | --- |
| `segment` | required | tifxyz folder, or its https:// or s3:// URL on the open-data bucket |
| `--voxel-um VOXEL_UM` | none | voxel size (default: the folder name's -N.NNNum.tifxyz) |
| `--cache CACHE` | `work/tifxyz/cache` | where bucket segments are kept |
| `--json` | off | print the report as JSON |
| `volume` | required | the volume's zarr folder or URL (the one the mesh's voxels are in) |
| `--level LEVEL` | `0` | pyramid level (0 is full resolution) |
| `--margin MARGIN` | `0.0` | also take chunks this many voxels (of level 0) from the sheet |
| `--max-requests MAX_REQUESTS` | `20000` | size at most this many chunks |
| `--fetch DEST` | none | copy the metadata and the touched chunks into this folder |

### `python -m kit tifxyz diff`

```
usage: python -m kit tifxyz diff [-h] [--voxel-um VOXEL_UM] [--cache CACHE]
                                 [--tol TOL] [--png PNG] [--json]
                                 segment other
```

| Option | Default | Meaning |
| --- | --- | --- |
| `segment` | required | version a: tifxyz folder or bucket URL |
| `other` | required | version b: tifxyz folder or bucket URL |
| `--voxel-um VOXEL_UM` | none | voxel size (default: the folder name's -N.NNNum.tifxyz) |
| `--cache CACHE` | `work/tifxyz/cache` | where bucket segments are kept |
| `--tol TOL` | `1.0` | a node moved or new beyond this (voxels on one grid, grid steps across grids) |
| `--png PNG` | none | write a picture of b with the changes colored |
| `--json` | off | print the report as JSON |

`python -m kit.tifxyz ACTION ...` takes the same actions and options.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `Segment(xyz, valid, meta=None, source='', voxel_um=None)` | a Segment with `xyz`, `valid`, `meta`, `step` (voxels per grid step along columns and rows, from `scale`), `voxel_um`, `volume` | `VerifyError` on a bad `scale` | `voxel_um` and `volume` default to what the folder name says |
| `load(src, cache=DEFAULT_CACHE, voxel_um=None)` | a Segment | `VerifyError` | A local folder or a bucket URL (fetched once into cache); holes are -1, NaN or all-zero nodes |
| `info(seg)` | dict (Outputs) | nothing | Area, grid, bounds, `meta.json` ratio |
| `stretch(seg)` | dict | nothing | Percentiles 1, 5, 50, 95, 99 of edge ratio, cell area ratio and grid angle |
| `isometry(seg, max_stretch=MAX_STRETCH)` | dict (Outputs) | `VerifyError` on a bad `max_stretch` | The block proposed for `meta.json`, `ISOMETRY_VERSION` 1 |
| `node_ratio(seg)` | (H, W) float | nothing | Each node's worst edge over the step, farthest from 1 in log terms; NaN at holes |
| `check(seg, max_stretch=MAX_STRETCH, fold_deg=FOLD_DEG)` | (dict, {"holes", "folds", "stretched": (H, W) bool}) | `VerifyError` on bad settings | Node masks on the input grid |
| `facing(seg, umb)` | dict | `VerifyError` when no normal can be compared | `umb` is a `kit.stackcheck` Umbilicus (or anything with `at(z)`, `z`, `source`, `volume`) |
| `write_obj(seg, path, stride=1)` | dict: path, vertices, triangles, stride | `VerifyError` on stride below 1 | Units: voxels; UVs from the grid position, 0 to 1 |
| `write_png(path, rgb)` | the path | `OSError` | 8-bit RGB PNG, standard library only |
| `shade(seg, masks=None, size=None)` | (H, W, 3) uint8 | nothing | Lit from a fixed direction; holes `(40, 44, 52)`, folds red, stretched orange, holes inside blue |
| `ZarrSource(root, opener=None)` | an object with `read(key)`, `size(key)` and `json(key)` (None for a missing key) | `OSError` from the network after 5 tries | A zarr folder on disk or behind an `https://` or `s3://` URL |
| `zarr_level(src, level=0)` | dict: `format`, `shape`, `chunks` (the stored unit, the shard when sharded), `prefix`, `sep`, `meta_key`, `level`, `path`, `factor` (z, y, x against level 0), `levels`, `sharded` | `VerifyError` | zarr v2 and v3, OME multiscales or a plain 3D array |
| `chunk_key(arr, idx)` | the chunk's key | nothing | `idx` in z, y, x |
| `touched_chunks(seg, arr, margin=0.0)` | ((N, 3) int array of z, y, x chunk indices, nodes outside the array) | `VerifyError` on a negative margin | Adds half a grid cell's diagonal so the sheet between nodes is covered |
| `chunks(seg, volume, level=0, margin=0.0, max_requests=MAX_REQUESTS, src=None)` | (dict, keys, sizes) | `VerifyError`, `OSError` | Sizes from one HEAD per key on a URL, `stat` on disk |
| `fetch_chunks(src, arr_levels, keys, sizes, dest, workers=CHUNK_WORKERS)` | (written, skipped, bytes) | `VerifyError` when the disk is short, `OSError` | Keeps 1 GiB free; skips files already there at the same size |
| `diff(a, b, tol=DIFF_TOL, sample=DIFF_SAMPLE, seed=0)` | (dict, {"added", "removed", "moved": (H, W) bool on b's grid}) | `VerifyError` on a tolerance of 0 or less | Node by node on one grid shape; by position otherwise (masks then hold `added` only) |
| `diff_picture(b, masks, size=1200)` | (H, W, 3) uint8 | nothing | b shaded; added green, removed red, moved orange |
| `format_info(r)`, `format_stretch(r)`, `format_isometry(r, source='')`, `format_check(r)`, `format_facing(r)`, `format_chunks(r)`, `format_diff(r)` | the text the command prints | nothing | |
| `build_parser(p)` | the parser with the nine actions | nothing | Used by `kit/cli.py` |
| `run(args)` | exit code | `VerifyError`, `OSError` | One action |
| `cmd_tifxyz(args)` | exit code | nothing | `run` with errors turned into exit 2 |
| `main(argv=None)` | exit code | nothing | `python -m kit.tifxyz` |

## Inputs

- **A tifxyz folder**: `x.tif`, `y.tif`, `z.tif`, 2D float32 grids of one shape, positions in voxels of one scan volume; -1, NaN or (0, 0, 0) marks a missing node. `meta.json` beside them with `scale` (two numbers above 0, nodes per voxel along columns then rows; read as 1, 1 when absent) and, optionally, `area_vx2`. The open-data bucket keeps each segment's meshes under `SCROLL/segments/SEGMENT/mesh/SEGMENT-on-VOLUME-N.NNNum.tifxyz/`; the voxel size and volume id are read from that name.
- **A center line** (for `facing`): the published umbilicus JSON (`control_points` with `x`, `y`, `z`), in voxels of the same volume as the segment. [`kit centerline get`](centerline.md) downloads one. A center line on another volume of the same scroll gives a warning, not a result you can trust.

## Outputs

`info` (`--json`):

| Field | Type | Meaning |
| --- | --- | --- |
| `grid` | [int, int] | rows, columns |
| `nodes_filled`, `filled_share` | int, float | nodes with a position, and their share of the grid |
| `complete_cells` | int | grid cells with all four corners |
| `step_vox` | [float, float] | voxels per grid step along columns and rows |
| `voxel_um`, `volume` | float or null, str or null | from `--voxel-um` or the folder name |
| `area_vox2`, `area_cm2`, `area_mm2` | float | 3D area of the complete cells (cm2 and mm2 need the voxel size) |
| `bbox_xyz` | [[x, y, z], [x, y, z]] | voxels |
| `meta_area_vox2`, `meta_area_ratio` | float | `meta.json`'s `area_vx2` and ours over it, when present |

`stretch`: `edge_columns`, `edge_rows`, `cell_area` (ratios, 1.0 exact) and `grid_angle_deg`, each `{p1, p5, p50, p95, p99}`; `within_10pct`, `within_25pct` (share of edges); `median_abs_log`.

`isometry`: `version`, `step_vx`, `edges`, `within_10pct`, `within_25pct`, `median_abs_log_ratio`, `area_ratio` (triangle area over complete cells times the step squared), `angle_deg` (p5, p50, p95), `stretched_nodes`, `stretched_area_vx2` (one cell per flagged node), `l2_mean`, `l2_median` (the area-weighted median of L2 squared, as flatboi returns it), `linf`, `area_error`. On PHerc0139 w035: 0.9984 within 10 %, area ratio 0.9963, 43 stretched nodes, L2 mean 0.9985, Linf 1.2094 (run 2026-10-24).

`check`: `holes`, `folds`, `stretched`, each `{nodes, share, area_mm2}` (holes' share is of the filled nodes plus the holes); `clean`; `png` when written.

`facing`: `normals_away_share`, `normals` (`away from the center` at 90 % or more, `toward the center` at 10 % or less, else `mixed`), `angle_grows_along_columns_share`, `median_radius_vox`, `outside_centerline_z_share`, `nodes_compared`, and `warning` when the volumes differ.

`chunks`: `segment`, `volume`, `level`, `level_path`, `level_factor_zyx`, `shape_zyx`, `chunk_zyx`, `sharded`, `margin_vox`, `chunks` (touched), `chunks_in_volume`, `sized`, `present`, `absent`, `bytes` (of the present ones), `nodes_outside_volume`, `note` when `--max-requests` cut the sizing short, `warning` when the volume URL does not name the mesh's volume, and `fetched` (`dest`, `written`, `skipped`, `bytes`) with `--fetch`.

`diff`: `a`, `b`, `grid_a`, `grid_b`, `area_a_vox2`, `area_b_vox2`, `area_change_vox2` (and the `_mm2` forms with a voxel size), `tol_vox`, `method`, `nodes_a`, `nodes_b`, `added`, `removed` (and `added_mm2`, `removed_mm2`), `same`; on one grid also `moved`, `unchanged` and `displacement_vox` `{p50, p90, p99, p100}`; across grids `sampled` and `nearest_node_vox` (node to node, so up to half a grid step above the distance to the surface); `warning` when the two name different volumes; `png` when written.

`obj` and `preview` print what they wrote.

| Exit code | Meaning |
| --- | --- |
| `0` | Done; for `check`, nothing flagged |
| `1` | `check` flagged holes, folds or stretched nodes |
| `2` | Bad input, a failed read or write |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit tifxyz: no tifxyz folder at PATH` | The path is not a folder | Give the `.tifxyz` folder itself, not its parent |
| `kit tifxyz: cannot read the tifxyz folder PATH: ERROR` | A TIFF is missing or unreadable | Check x.tif, y.tif and z.tif are there; refetch with a fresh `--cache` |
| `kit tifxyz: PATH: x.tif, y.tif and z.tif must be 2D grids of one shape` | The three files disagree | The folder is damaged or mixed from two segments |
| `kit tifxyz: PATH: meta.json scale must be two numbers above 0 (got VALUE)` | A broken `meta.json` | Fix `scale` (VC3D writes `[0.05, 0.05]` for one node per 20 voxels) |
| `kit tifxyz: --max-stretch must be above 1 (got VALUE)` | A ratio of 1 or less flags everything | Use a value such as 1.25 or 2 |
| `kit tifxyz: --fold-deg must be between 0 and 180 (got VALUE)` | Out of range | Use, for example, 60 or 90 |
| `kit tifxyz: --stride must be 1 or more (got VALUE)` | Bad stride | Use 1, 2, 4 ... |
| `kit tifxyz: PATH: no grid normal could be compared with the center line` | The segment is empty, or every node sits on the line | Check the segment has filled nodes and the center line is in its volume |
| `kit tifxyz: kit tifxyz needs numpy and tifffile: pip install numpy tifffile` | Missing packages | Install them |
| `kit tifxyz: ...` with another message | A bucket URL that `kit stackcheck`'s fetcher refused, or an umbilicus it could not read (their messages are on the [stackcheck page](stackcheck.md)) | Read the message |
| `kit tifxyz: PATH is one array, not a multiscale pyramid: leave out --level` | `--level` on a plain array | Leave out `--level` |
| `kit tifxyz: PATH: no .zattrs, zarr.json or multiscales found: is this a zarr volume?` | The volume path is not a zarr | Give the `.zarr` folder or URL itself |
| `kit tifxyz: PATH has levels 0 to N; --level L is not one of them` | A level the pyramid does not have | Pick one in range |
| `kit tifxyz: PATH: no array metadata at level L (WHERE)` | The level's `.zarray` or `zarr.json` is missing | Check the volume is complete |
| `kit tifxyz: PATH: level L has N axes; a scan volume has 3 (z, y, x)` | Not a 3D volume | Give a scan volume, not a 2D label array |
| `kit tifxyz: PATH/KEY is not JSON: ERROR` | A damaged metadata file | Refetch the volume's metadata |
| `kit tifxyz: --margin must be 0 or more voxels (got VALUE)` | A negative margin | Use 0 or more |
| `kit tifxyz: --fetch needs every chunk sized: N chunks, --max-requests M; raise it to N or more` | `--fetch` with sizing cut short | Raise `--max-requests` |
| `kit tifxyz: --fetch needs X GB plus 1 GB spare in DEST; Y GB free` | Not enough disk | Free space, pick another DEST or a coarser `--level` |
| `kit tifxyz: --tol must be above 0 voxels (got VALUE)` | A tolerance of 0 or less | Use 1 (voxels) or more |
| `kit tifxyz could not read or write a file: HTTP Error 502: Bad Gateway` (or another HTTP or network error) | The bucket kept failing after 5 tries | Run it again later |
| `kit tifxyz could not read or write a file: ERROR` | An output folder that cannot be written | Pick another OUT or `--png` |

## How it works

1. **Read.** The three TIFFs are stacked into an (H, W, 3) grid; a node is valid when all three values are finite, above -0.5 and not all zero (the convention of `kit stackcheck`). `scale[0]` is nodes per voxel along columns, `scale[1]` along rows, so the promised step is `1 / scale` voxels.
2. **Area.** Each grid cell whose four corners are valid is split into triangles (p00, p01, p11) and (p00, p11, p10); their areas are summed. cm2 = voxels squared times (voxel size in um times 1e-4) squared.
3. **Stretch.** Every edge between two valid neighbors, divided by the promised step; cell area over step squared; the angle between a cell's column edge and row edge.
4. **Holes.** Missing nodes not joined to the grid's border through other missing nodes (scipy's `ndimage.label`, or a numpy flood from the border when scipy is absent).
5. **Folds.** Each complete cell's normal (sum of its two triangles' normals, normalized); two neighboring cells whose normals have a dot product below cos(`FOLD_DEG` = 90) flag the nodes of both cells.
6. **Stretched.** A node is flagged when any edge it touches is over `MAX_STRETCH` = 1.5 times the step, or under 1 / 1.5.
7. **Facing.** Node normals are the cross product of the column step and the row step (central differences), exactly as in `kit stackcheck`'s `grid_geometry`. For each node the center line is interpolated at its z (constant beyond its end points); the normal's dot product with the horizontal direction away from the center gives away or toward. The turning sense is the sign of the change in atan2(y - yc, x - xc) from each node to the next along its row.
8. **Chunks.** Mesh positions (x, y, z in level-0 voxels) become z, y, x and are divided by the level's scale against level 0 (from the OME `coordinateTransformations`, or 2 to the level). Around each node a cube of half-side margin plus half a grid cell's diagonal is mapped to the chunk indices it overlaps, clipped to the array; the union is the touched set. Keys follow the array's own scheme: zarr v2 `PATH/z.y.x` or `PATH/z/y/x` (its `dimension_separator`), zarr v3 `PATH/c/z/y/x` (default encoding) or the v2 encoding. A sharded v3 array is selected by shard, its stored unit. A missing key (404 or 403) counts as absent: zarr reads it as the fill value.
9. **Diff.** With one grid shape, nodes are compared in place: added (valid in b only), removed (valid in a only), moved (valid in both, displaced by more than `--tol` voxels). With different shapes, each node of b is tested for a node of a in its own or a neighboring cube of side `--tol` times the smaller grid step (a far node is then more than that from every node of a); the same from a to b gives removed; the median and upper percentiles of node-to-node distance come from 2,000 of b's nodes against all of a's, by brute force.
10. **Pictures.** The shade is the absolute dot product of the node normal with a fixed light direction, so both sides of the sheet look the same; PNGs are written with `zlib` and `struct` only.

## Cost and time

Seconds on a laptop CPU for any published mesh (times in the At a glance table, measured 2026-10-23 on a 4-core cloud container). A bucket segment adds one download of its four files (about 14 MB for a 2.4 um w035 mesh). Nothing to rent.

## For agents

- **Command:** `python -m kit tifxyz check SEGMENT --json --png check.png` (and `info SEGMENT --json` for the area); `chunks SEGMENT VOLUME --level L --json` before `--fetch DEST`; `diff A B --json`.
- **Parse:** `chunks`: `chunks`, `bytes`, `absent`, `note`; `diff`: `same`, `added`, `removed`, `moved`, `displacement_vox`; `info`: `area_cm2`, `meta_area_ratio`; `check`: `clean`, and `holes.nodes`, `folds.nodes`, `stretched.nodes` with their `area_mm2`; `facing`: `normals` and `warning`.
- **Rerun:** Safe; it reads the same files and overwrites only the files you name. Bucket files are kept in `--cache` and not fetched again.
- **Success:** exit 0 (or 1 from `check` when something is flagged, which is a result, not a failure); exit 2 means no result.
- **Not a pass:** a clean `check` does not mean the segment follows one sheet or holds ink; an `area_cm2` from a mesh with `meta_area_ratio` far from 1; a `facing` result with a `warning` about volumes.
- **Go-ahead:** Nothing.
- **Never:** call a segment "good" or "verified" from these numbers alone; describe target-scroll segments from private work in public text.

## Tests

`python -m unittest tests.test_tifxyz tests.test_tifxyz_chunks_diff -v`: area and isometry of a flat sheet, `meta.json` ratio, each planted defect (hole, fold, stretch) caught by its own check while the others stay quiet, holes found the same without scipy, facing on a cylinder and its mirror, the volume warning, bad settings, the command line round trip (info, check with PNG, obj line counts, preview size), the PNG bytes read back, and exit codes 1 and 2. For `chunks`: the touched layer of a planted sheet and no other, the margin, level scaling, absent chunks, the three key layouts, `--fetch` copying only metadata and touched chunks (and skipping them the second time), bad levels, margins and paths, and the `--fetch` refusal when sizing was cut short. For `isometry`: an exact grid gives 1, 1, 0, 1, angles 90 and flatboi's 1, 1, 0; a grid 1.3 times too long along its columns keeps only the row edges within 10 %, flags nothing and gives Linf 1.3 and L2 mean sqrt((1.3^2 + 1) / 2); one invalid node drops its four edges; a 2-step jump and a half-step squash each flag two columns of nodes. For `diff`: a copy, each planted change counted, the tolerance, area change, an extension and a far copy across grids, and the position test against brute force. They do not download a real segment; the w035 numbers above were run by hand.

## History

- 2026-10-23: added `info`, `stretch`, `check`, `obj`, `preview` and `facing` (`3376687`).
- 2026-10-24: added `chunks` and `diff` (`ad3fddc`).
- 2026-10-24: added `isometry`, the reference for the block proposed in villa issue #2279, with its still and GIF from `scripts/media/isometry_media.py`.

## Related

- [stackcheck](stackcheck.md): many segments against each other and the umbilicus; shares the reader and normals.
- [centerline](centerline.md): get the center line `facing` needs.
- [find](find.md): list a scroll's segments and meshes.
- [uvgate](uvgate.md): checks a flattened sheet's UV triangles.
- [Segments without VC3D](../segments-without-vc3d.md): the how-to with pictures.
