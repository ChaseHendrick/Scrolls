# freshmap: where a scroll's papyrus is still unread

Maps where a scroll's public m7 papyrus prediction lies away from every surface already read or traced, by band, angle and radius, ranks targets and measures new meshes against it, so tracing and unrolls aim at new papyrus.

| Field | Value |
| --- | --- |
| Id | `freshmap` |
| Status | Experimental |
| Kind | kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit.freshmap build`, `python -m kit.freshmap query`, `python -m kit.freshmap show`, `python -m kit.freshmap summarise`, `python -m kit.freshmap index` |
| Code | `kit/freshmap.py` |
| Tests | `tests/test_freshmap.py` |
| Needs | Python 3.10 or newer with numpy, scipy, tifffile and numcodecs; the scroll's m7 surface prediction (public for many scrolls) and your meshes as tifxyz folders or tars |
| Runs on | CPU. Public PHerc0343, z 9,500 to 11,000 (432 chunks, one mesh): 50 s with 8 jobs on a 4-core cloud container (measured 2026-11-25). A whole scroll with about 4,000 meshes: about 25 minutes with 4 jobs, peak about 3 GB |
| Network | The Vesuvius Challenge open data bucket on S3 (m7 chunks, and the volume listing for the voxel size; anonymous), unless `--volume` is a local folder and `--voxel-um` is given |
| Writes | `build`: `OUT/` (summary.json, grid.npz, occ-read.bits, occ-traced.bits, meshes.json, unrolled.png, side.png) and the mesh cache (default `OUT/cache`) |
| Go-ahead | Not needed (free CPU, geometry and a public prediction only) |
| Released | Public, with the November 2026 Progress Prize entry (pending) |
| Checked | 2026-11-25 against commit `859fc14` |

## What it does

Before a new trace or unroll, the question is where papyrus remains that nobody has read or traced. Without a map, each candidate trace is checked one at a time, after it is made, and often turns out to repeat a surface already read. This tool answers the question once per scroll, before any tracing.

It reads the scroll's m7 surface prediction (the community's papyrus surface model, published in the open data bucket) at level 2, four level-0 voxels a side, so neighbouring sheets stay apart, and gives every papyrus voxel one class:

- READ: within 20 level-0 voxels (about one sheet pitch) of a surface you list as already rendered and read;
- TRACED: near a traced surface you list that has not been read;
- BOXED: inside one of the `--boxes` regions, areas you want left alone for any reason;
- FRESH: everything else.

Each voxel stands for an area estimated from its exposed faces. The tool sums the classes per band of z, angle sector and radius ring, and ranks the bins with the most FRESH area as targets, each with a level-0 box you can hand to a tracer.

`query` measures new meshes against a built map: how much of each lies on fresh papyrus, how much repeats read or traced surface, and how much sits on m7 at all. A tracing run can check its traces before anyone renders or reads them.

It reads geometry and the prediction only: no CT, no ink map, no labels. A FRESH area is where m7 predicts papyrus that no listed surface comes near. That is model output about geometry, not evidence of ink, text, or a sheet a tracer can follow. The map is only as complete as the read set you give it.

## When to use it

- Before planning a new trace, seed flood or unroll on a scroll: aim seeds at the top targets.
- On new traces (volunteer tracks, refits, automatic meshes) before rendering: `query` gives the fresh share and area per mesh.
- To see how much of a scroll your team or the community has already covered, per band.

Do not use it:

- As an area figure for prize accounting: the face count is a coarse estimate, best read as relative.
- On a scroll with no m7 prediction: the tool has nothing to classify.
- As a sign of ink or text: FRESH says only that no listed surface is near.

## Quick start

On public PHerc0343, with its one public segment as the read set (the segment's mesh is in the same scan frame, 20250521140437, as the scroll's m7 prediction):

```bash
O=https://vesuvius-challenge-open-data.s3.amazonaws.com
M=PHerc0343/segments/20261007213123-concat_w047-w048_R5B2_z9500-11000/mesh/20261007213123-on-20250521140437-8.64um.tifxyz
mkdir -p work/fm/read/w047-w048
for f in meta.json x.tif y.tif z.tif; do curl -sf -o work/fm/read/w047-w048/$f "$O/$M/$f"; done
python -m kit.freshmap build --scroll PHerc0343 --read work/fm/read --out work/fm/PHerc0343 --z 9500:11000 --jobs 8
python -m kit.freshmap query work/fm/PHerc0343 work/fm/read
```

Output (25 Nov 2026; Model output (geometry)):

```
PHerc0343: papyrus 2154.1 cm2 (m7 estimate); read 19.4, traced 0.0, boxed 0.0, fresh 2134.7 (99%; in runs of 96 slices or more 2124.6). Model output (geometry).
band z (level 0)       papyrus  read  traced  boxed  fresh  share  thick
  9216-10240          997.5    8.7    0.0    0.0  988.8   99%  984.8
 10240-11264          928.5   10.6    0.0    0.0  917.9   99%  913.0
 11264-12288          228.1    0.0    0.0    0.0  228.1  100%  226.8
target 1: 12.03 cm2 thick fresh of 12.03 (100%) band z [10240, 11264], 315-338 deg, 20-22 mm
...
w047-w048: 7.804 cm2, fresh 0.0 cm2 (0%), near read 100%, near traced 0%, seated 90%
```

The z range snaps to whole 192-voxel chunks, so the classified slab runs from z 9,216 to 11,520. The read papyrus (19.4 cm2) is larger than the mesh (7.8 cm2) because every papyrus face within 20 voxels of the mesh counts as read, which includes parts of the neighbouring sheets. The segment's own `query` row is the check that the map and the mesh agree: none of it is fresh, all of it is near read, and 90% of it sits on m7.

For another copy of the prediction or another scroll: `--volume URL_OR_DIR --frame SCAN`. For regions to leave alone: `--boxes boxes.json`, a list of `{"id": "name", "z": [a, b], "y": [a, b], "x": [a, b]}` in level-0 voxels of the prediction's frame. Rebuild only the summary (new target count or umbilicus) without classifying again: `python -m kit.freshmap summarise work/fm/PHerc0343 --targets 40`.

## Checks and controls

The control is a check that can fail on known geometry: in `tests/test_freshmap.py` a synthetic prediction holds two flat sheets 24 level-0 voxels apart. A read mesh on one sheet must class that sheet READ and the other FRESH at the default 20 voxels, and both READ at 25 (the distance is exact, not a cube). A traced mesh and a box must give TRACED and BOXED. `query` must give a mesh on the fresh sheet a fresh share of 1, a mesh on the read sheet 0, and a mesh between the sheets a seated share of 0. Tar members other than mesh files must never be unpacked, and displaced control copies (folders named `sham` or `sham_trim`) never count as surfaces.

On real data the public PHerc0343 run above is the check: its read segment, queried against the map built from it, must come out 0% fresh and 100% near read, and did; its faces' z share was 0.24, so the horizontal-normal area factor holds roughly.

Earlier real-scroll runs caught two faults now fixed: rows near a chunk edge missed their own chunk (READ came out 0), and an out-of-memory worker death was recorded as per-mesh errors, so read meshes silently dropped out; a dead worker now stops the build.

The face estimate runs high where m7 marks sheets more than one voxel thick. Treat the areas as relative. In the unrolled picture FRESH can show as thin horizontal slivers at the seams between stacked read meshes; `fresh_thick` counts FRESH only in z runs of at least `THICK_L0` (96 level-0 voxels) of coarse cells where FRESH is the largest class, and targets rank by it.

Cross-scroll validation: claim-dependent. The tool makes no broad scientific claim; its per-scroll numbers are geometry estimates for planning.

Claim label: Model output (geometry): every class area, share and target; Interpretation: the area estimate's factor.

## Commands and options

### `python -m kit.freshmap index`

```
usage: python -m kit.freshmap index [-h] --cache CACHE [--json] src [src ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `src` | required | tifxyz folders, folders holding them at any depth, or .tar files of them |
| `--cache CACHE` | required | where tar mesh files are unpacked (once per tar) |
| `--json` | off | print the mesh count and names as JSON |

### `python -m kit.freshmap build`

```
usage: python -m kit.freshmap build [-h] --scroll SCROLL
                                    --read READ [READ ...]
                                    [--traced [TRACED ...]] --out OUT
                                    [--level LEVEL] [--sum-level SUM_LEVEL]
                                    [--fresh-vox FRESH_VOX] [--z Z]
                                    [--jobs JOBS] [--volume VOLUME]
                                    [--frame FRAME] [--boxes BOXES]
                                    [--voxel-um VOXEL_UM]
                                    [--umbilicus UMBILICUS]
                                    [--targets TARGETS] [--cache CACHE]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--scroll SCROLL` | required | the scroll; picks the public m7 prediction and its scan id (the frame) when listed |
| `--read READ ...` | required | folders or tars of surfaces already rendered and read |
| `--traced TRACED ...` | none | folders or tars of traced surfaces not yet read |
| `--out OUT` | required | output folder |
| `--level LEVEL` | `2` | m7 pyramid level read (2: four level-0 voxels a side) |
| `--sum-level SUM_LEVEL` | `5` | level of the coarse summary grid (5: 32 level-0 voxels a side); must divide the 192 voxel chunks |
| `--fresh-vox FRESH_VOX` | `20.0` | level-0 voxels within which a surface makes papyrus READ or TRACED |
| `--z Z` | none | L0:L1 level-0 z range (whole chunks) |
| `--jobs JOBS` | `4` | worker processes (4 fits a 15 GB machine for a whole scroll) |
| `--volume VOLUME` | none | the m7 zarr (URL or folder, without the level); default the public one |
| `--frame FRAME` | none | scan id of the prediction's frame (needed with `--volume` for unlisted scrolls) |
| `--boxes BOXES` | none | JSON list of level-0 regions to class BOXED (left alone) |
| `--voxel-um VOXEL_UM` | none | voxel size in um; default read from the scan's public volume name |
| `--umbilicus UMBILICUS` | none | JSON `[[z, y, x], ...]` in level-0 voxels |
| `--targets TARGETS` | `25` | how many (band, sector, ring) bins to list |
| `--cache CACHE` | none | mesh cache (default OUT/cache); rasterised meshes are kept here by hash |

### `python -m kit.freshmap show`

```
usage: python -m kit.freshmap show [-h] [--json] dir
```

| Option | Default | Meaning |
| --- | --- | --- |
| `dir` | required | a built map's folder |
| `--json` | off | print summary.json |

### `python -m kit.freshmap summarise`

```
usage: python -m kit.freshmap summarise [-h] [--targets TARGETS]
                                        [--umbilicus UMBILICUS]
                                        dir
```

| Option | Default | Meaning |
| --- | --- | --- |
| `dir` | required | a built map's folder |
| `--targets TARGETS` | `25` | how many bins to list |
| `--umbilicus UMBILICUS` | none | umbilicus file for the centre |

### `python -m kit.freshmap query`

```
usage: python -m kit.freshmap query [-h] [--cache CACHE] [--json]
                                    dir mesh [mesh ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `dir` | required | a built map's folder |
| `mesh` | required | tifxyz folders, folders holding them, or tars, as for build |
| `--cache CACHE` | none | where tar mesh files are unpacked (default DIR/cache) |
| `--json` | off | print one JSON object |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `FreshMapError()` | the error class | nothing | bad inputs; the CLI prints it and exits 2 |
| `mesh_name(folder)` | str or None | nothing | a mesh's name: its folder's, or the nearest ancestor's when the folder has a generic name (`seat/NAME/snap` is NAME); None for control copies |
| `find_meshes(srcs, cache)` | list of (name, Path) | FreshMapError for a source that is neither a folder nor a tar | every tifxyz folder under srcs (tars unpacked into cache, mesh files only) |
| `unpack(tar, cache, dest=None)` | Path of the unpacked folder | tarfile errors | mesh files (x.tif, y.tif, z.tif, meta.json) of a tar, unpacked once |
| `load_xyz(folder)` | (x, y, z) float64 grids | FreshMapError when the grids differ in shape | level-0 voxels; invalid vertices are -1 |
| `valid_of(x, y, z)` | bool grid | nothing | valid when all of x, y, z are above -0.5 and finite |
| `dense_voxels(x, y, z, spacing, s)` | int64 rows (N, 3) | nothing | unique level voxels of a mesh's valid vertices and of bilinear points between them |
| `mesh_cells(x, y, z)` | float grid | nothing | area per valid vertex: the product of half-step neighbour distances |
| `rasterise(folder, level, dims=None)` | (rows, record), or (sorted keys, record) with dims | FreshMapError, tifffile errors | unique level-voxel rows of a mesh's densified surface, and the mesh's summary |
| `Chunks(base, level)` | a reader with shape, chunks, grid() and chunk() | FreshMapError for a missing or unsupported array | one level of a zarr v2 uint8 array with `/` chunk keys, from a URL or a folder; a missing chunk reads as fill |
| `voxel_um_of(scroll, scan)` | float um | FreshMapError when no volume names its size | the scan's voxel size from its public volume's name |
| `m7_url(scroll, scan=None)` | str | FreshMapError for an unlisted scroll with no scan | the public m7 prediction zarr, without the level |
| `load_boxes(path)` | list of (z0, z1, y0, y1, x0, x1, id) | FreshMapError for an unreadable file | the `--boxes` regions; an empty list for no path |
| `face_weights(b, by_axis=None)` | uint8 array | nothing | exposed faces per papyrus voxel |
| `near_mask(occ, origin, shape, rad)` | bool array | nothing | exact Euclidean distance (scipy distance transform) to the Occ's voxels |
| `box_mask(boxes, origin, shape, s)` | bool array | nothing | a voxel is inside when its centre is inside the half-open level-0 box |
| `classify_chunk(m7, origin, occ_read, occ_traced, boxes, level, rad, face_cm2, sum_factor)` | (areas (4, cz, cy, cx), faces per axis) | nothing | per class area (cm2) on the coarse grid of one chunk |
| `Occ(path, dims=None, create=False)` | a bit-packed level-voxel occupancy on disk with key(), add(), box() and count() | OSError for a missing file | one bit a voxel, x padded to a multiple of 8 |
| `keys_to_rows(k, dims)` | int64 rows (N, 3) | nothing | decodes `(z * Y + y) * X + x` keys |
| `rasterise_all(meshes, level, jobs, say, occ)` | per-mesh records | FreshMapError when a worker dies | writes every mesh into the Occ |
| `build(scroll, read_srcs, traced_srcs, out, level=LEVEL, sum_level=SUM_LEVEL, fresh_vox=FRESH_VOX, zr=None, jobs=4, volume=None, voxel_um=None, umbilicus=None, n_targets=TARGETS, cache=None, say=print, boxes_path=None, frame=None)` | the summary dict (also summary.json) | FreshMapError | steps 1 to 3 of How it works |
| `centres(grid, umbilicus=None, sum_level=SUM_LEVEL)` | (cy, cx) arrays per coarse z layer | nothing | from an umbilicus file, else the papyrus centroid smoothed over 31 layers |
| `summarise(grid, sum_level, vum, umbilicus=None)` | dict of totals, bands, sectors, rings, centre | nothing | bands of 1,024 level-0 voxels, 16 sectors, 2 mm rings |
| `thick_fresh(grid, cells=None)` | float array (z, y, x) | nothing | FRESH area of coarse cells in z runs of at least `cells` where FRESH is the largest class |
| `resummarise(mapdir, n_targets=TARGETS, umbilicus=None)` | the summary dict | FreshMapError | rebuild summary.json, targets and pictures from grid.npz |
| `bins(grid, sum_level, vum, umbilicus=None)` | (band, sector, ring) int arrays | nothing | bin indices over the coarse grid |
| `targets(grid, sum_level, frame, n, vum, umbilicus=None)` | list of target dicts | nothing | the n bins with the most thick FRESH area, each with its class areas and the level-0 box of its fresh cells |
| `write_pngs(grid, out, summ, angle_bins=360)` | None | nothing | unrolled.png (z down, angle across) and side.png (z down, radius across), coloured by the largest class |
| `query(mapdir, meshes, cache=None)` | dict with one row per mesh | FreshMapError | per mesh: area, fresh area and share, near-read, near-traced and seated shares |
| `build_parser(p=None)` | the argparse parser | nothing | subcommands index, build, summarise, show, query |
| `run(a)` | exit code | nothing (FreshMapError becomes exit 2) | the CLI entry for every subcommand |
| `main(argv=None)` | exit code | nothing | parses argv and calls run |

## Inputs

- The scroll's m7 surface prediction: OME-Zarr v2, uint8, 192 voxel chunks, blosc, `/` keys, in the scan's level-0 voxel frame. The public one is at `{scroll}/representations/predictions/surfaces/{scan}-surface-20260413222639-surface-m7-L0-th0.2.zarr` in the open data bucket; `M7_PUBLIC` lists the scrolls this tool was tried on, and any other takes `--volume` and `--frame`.
- Meshes: tifxyz folders (x.tif, y.tif, z.tif float grids in the same level-0 frame, invalid vertices -1), folders of them, or tars. Meshes must be in the prediction's scan frame; a mesh from another scan of the same scroll lands in the wrong place.
- `--boxes`: optional JSON list of level-0 boxes in the prediction's frame.
- `--umbilicus`: optional JSON `[[z, y, x], ...]` in level-0 voxels; without it the centre per coarse layer is the papyrus area's centroid, smoothed by a running median of 31 layers.

## Outputs

`build` prints the totals, the per-band table and the first ten targets, and writes:

| File | Content |
| --- | --- |
| `summary.json` | everything below |
| `grid.npz` | `grid` float32 (4, Z, Y, X): READ, TRACED, BOXED, FRESH area in cm2 per coarse cell (`sum_level`) |
| `occ-read.bits`, `occ-traced.bits` (+ `.json`) | the rasterised level voxels, one bit each, mostly zero; read by `query` |
| `meshes.json` | per mesh: name, folder, valid vertices, voxels, area, or its error |
| `unrolled.png`, `side.png` | class maps: z down, angle (1 degree columns) or radius (coarse cells) across; orange FRESH, blue TRACED, purple BOXED, grey READ; brighter for more area |

| Field | Type | Meaning |
| --- | --- | --- |
| `totals_cm2` | dict | area per class and `papyrus` (all classes), cm2, face-count estimate |
| `fresh_share` | float | FRESH over papyrus |
| `bands` | list | per 1,024 level-0 voxels of z: class areas, papyrus, fresh_share, fresh_thick |
| `sectors`, `rings` | dict | class areas per 22.5 degree sector and per 2 mm ring |
| `targets` | list | rank, band_z_l0, angle_deg, ring_mm, class areas, papyrus, fresh_share, region (level-0 box of the bin's fresh cells) |
| `boxes` | int | how many `--boxes` regions were used |
| `faces_by_axis` | dict | exposed faces per axis; a `z_share` far above 0 means sheets are steep and the area factor reads high |
| `mesh_area_cm2` | dict | summed mesh area per layer (overlaps counted again) |
| `chunks` | dict | chunks listed and missing (missing reads as empty) |

`query` prints, per mesh, its area, `fresh_cm2` and `fresh_share` (seated within one level voxel of m7 and farther than the map's distance from every read and traced voxel), `near_read_share`, `near_traced_share` and `seated_share`.

| Exit code | Meaning |
| --- | --- |
| `0` | done |
| `2` | bad arguments or inputs (FreshMapError) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `: x, y, z grids differ in shape or are not 2D` | a broken tifxyz | build records it in meshes.json and goes on; fetch the mesh again |
| `freshmap: no public volume of ... scan ... names its voxel size; give --voxel-um` | no public volume of the scan names its size | pass `--voxel-um` |
| `freshmap: no public m7 prediction listed for ...: give --volume and --frame` | the scroll is not in `M7_PUBLIC` | pass `--volume` and `--frame` |
| `freshmap: cannot read boxes ...:` | the boxes file is not a list of z, y, x pairs | fix the JSON |
| `--sum-level must be at least --level` | the summary grid is finer than the read level | raise `--sum-level` |
| `--sum-level must divide the prediction's chunks` | 192 is not a multiple of the summary factor | use a factor of 2 to 64 |
| `only uint8 zarr v2 arrays with '/' chunk keys are read` | another array format | point `--volume` at the m7 zarr |
| `freshmap: no .../.../.zarray` | the volume has no array at that level | check `--volume` and `--level` |
| `: not a folder or a tar` | a missing source path | check the path |
| `a rasterising worker died (out of memory?): rerun with fewer --jobs` | a worker process was killed, usually for memory | rerun with fewer `--jobs`; nothing partial is kept as the map |

## How it works

1. Each mesh's valid cells are filled with bilinear points at most half a level voxel apart and floored to level voxels (`dense_voxels`), batch by batch; the union per layer (read, traced) is a bit-packed occupancy volume on disk (`Occ`), cached by a hash of the mesh files' sizes and times. Cells with an edge over 4 times the mesh's median (`LONG_CELL`, seams and wraps) are left out.
2. For each 192-voxel chunk of the prediction: papyrus is m7 above 0; area per voxel is its exposed faces times the face area over 2 and over 4/pi (`PROJ`: the mean of |nx| + |ny| for normals spread evenly in the horizontal plane, as a rolled scroll's point about radially); READ and TRACED use an exact Euclidean distance transform over the box of the nearby rasterised voxels (`FRESH_VOX` 20 level-0 voxels); BOXED uses the `--boxes` regions; FRESH is the rest. Areas are summed to the coarse grid.
3. Bands (1,024 level-0 voxels), 16 sectors and 2 mm rings about the centre. `thick_fresh` keeps FRESH only where a coarse cell's largest class is FRESH in a z run at least `THICK_L0` level-0 voxels long; targets are the bins with the most thick FRESH area.

## Cost and time

Free CPU. Public PHerc0343, z 9,500 to 11,000: 432 chunks (246 empty or missing) classified in 50 s with `--jobs 8` on a 4-core cloud container, `query` of one mesh 12 s, output 40 MB. A whole scroll with about 4,000 meshes: rasterise about 11 minutes and classify about 2,800 chunks in about 12.5 minutes with `--jobs 4`, peak memory about 3 GB, two occupancy files of about 2.3 GB each. A rerun with no changed mesh reuses the occupancy; `summarise` takes seconds.

## For agents

- **Command:** `python -m kit.freshmap build --scroll S --read READ_DIR --traced TRACED_DIR --out OUT --jobs 4`, then `python -m kit.freshmap show OUT --json` or `python -m kit.freshmap query OUT MESHES --json`.
- **Parse:** `totals_cm2.fresh`, `fresh_share`, `bands[].fresh`, `targets[]` (region, fresh, fresh_thick); `query` rows' `fresh_cm2` and `seated_share`.
- **Rerun:** safe; it overwrites OUT's files and reuses the cached rasterisation when no mesh changed.
- **Success:** exit 0, and a read mesh queried against its own map comes out 0% fresh.
- **Not a pass:** FRESH area is not readable papyrus, ink or text; a map missing some read surfaces overstates FRESH near them; the area is a face-count estimate, not an unroll's area.
- **Go-ahead:** Nothing (free CPU).
- **Never:** call FRESH papyrus text; mix meshes from another scan frame into a map.

## Tests

`python -m unittest tests.test_freshmap -v`: the synthetic two-sheet prediction (classes, exact distance at 20 and 25 voxels, area, faces by axis, boxes, targets), bad boxes and an unlisted scroll, `query` (fresh, read and off-sheet meshes), the distance ball, the bit occupancy round trip, mesh naming and the tar filter. Not covered: reading the public bucket (the PHerc0343 quick start is the manual check).

## History

- 2026-11-25: First public version: build, summarise, show, query, index; `--boxes` and `--frame`; public PHerc0343 check run (`859fc14`).

## Related

- [sheethug](sheethug.md): a score for whether a model separates fused sheets, another surface-side tool.
- The m7 surface predictions: the open data bucket's `representations/predictions/surfaces/` folder for each scroll.
