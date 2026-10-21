# stackcheck: check consecutive segments of one scroll against its umbilicus, from geometry alone

`python -m kit stackcheck` checks a stack of consecutive tifxyz segments, inner to outer, against the scroll's umbilicus: winding order, coincident or oddly spaced pairs, missing sectors and runs, skipped windings, turn overlaps and stack ends, with masks of the flagged vertices.

| Field | Value |
| --- | --- |
| Id | `stackcheck` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit stackcheck`, `from kit import stackcheck` |
| Code | `kit/stackcheck.py`, `kit/cli.py` (`cmd_stackcheck`), `kit/meshaudit.py` (`_get`, `get_json`, `load_catalogue`, `sample_matrix`), `kit/verify.py` (`VerifyError`) |
| Tests | `tests/test_stackcheck.py`, `tests/test_toolreg_reports.py` |
| Needs | Python 3.10 or newer, numpy, scipy (`cKDTree`, `ndimage.label`), tifffile. Inputs: the segments' tifxyz folders and the scroll's published umbilicus JSON. Checked with Python 3.13, numpy 2.5, scipy 1.18 |
| Runs on | One CPU core. PHerc0139 run A (5 segments) took 49.8 s and 0.75 GB, run B (18 segments) 144.8 s and 1.7 GB (`stackcheck_checks` in `results.json`, 2026-10-14); a synthetic six-winding stack takes 13 to 16 s and 166 MB (measured 2026-10-16, 4-core Xeon cloud container, shared) |
| Network | None for local folders. For `https://` or `s3://` segments, the umbilicus or the catalog: the open-data bucket `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (or the host the URL names), for each segment's `x.tif`, `y.tif`, `z.tif` and `meta.json`, the umbilicus JSON, and `metadata.json` for `--transform catalog:...` without a local `--catalog` |
| Writes | Fetched segments under `--cache` (default `work/stackcheck/cache/HOST/PATH/`, kept for reuse); the JSON report with `--out`; the masks `.npz` with `--flags`. Otherwise it prints only |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-14 (`47cd607`); listed in the README's "Released tools" as the release `stackcheck` (Segment stack check), since 2026-10-20 a line of the Scrolls kit entry under the same id |
| Guide | [The PHerc0139 segment note](../logs/2026-10-14-pherc0139-segment-defects.md): usage, the PHerc0139 numbers, example vertices for VC3D, a look at the CT and the limits |
| Checked | 2026-10-21 against commit `8721373` |

## What it does

A scroll is a spiral of papyrus. One turn of it is a winding, and the umbilicus is the scroll's center line, published as control points with an x and y per height z. Tracers deliver one segment per winding: a tifxyz folder (`x.tif`, `y.tif`, `z.tif`, the position in voxels of each grid vertex, -1 for holes). When segments are used together, for a spiral fit or to count windings between two points, a segment that leaves its sheet, is missing in places, or runs past a full turn gives a wrong count.

`kit stackcheck` takes consecutive segments, inner to outer, and checks them against each other and the umbilicus using only their vertex positions: no CT, no surface prediction, no ink. It casts rays from the umbilicus every degree on planes of constant z and walks along each vertex normal to the nearest other segment, then runs these checks:

| Check | What it flags |
| --- | --- |
| Order | An adjacent pair where the inner segment lies outside the outer one by more than `--coincide-um` on a ray; per vertex, a lower winding outside or a higher one inside along the normal |
| Coincident pair | An adjacent pair within `--coincide-um` of each other on a ray: one sheet traced twice, or sheets pressed closer than the traces can be told apart |
| Pair spacing | An adjacent pair whose median spacing on the rays is under 0.5 or over 1.75 times the median of the pairs up to two places away: a winding counted twice, or one missing all the way |
| Missing sector | Heights and angles where a segment has no vertex while both neighbors do, within its own z extent |
| Missing run | The same where two or more adjacent windings are missing between present ones |
| Skipped winding | Vertices whose nearest other segment along the normal is two or more windings away and closer than half the local pitch, so nothing fits between |
| Turn overlap | A segment traced past a full turn: the angle past 360 degrees per grid line, and the doubly traced end (the piece of the turn traced a second time, on the next or previous winding's sheet) |
| Stack end | Heights where a winding between two traced ones has no segment |

It writes a JSON report (counts, areas, heights, angles and spacings per check, with example vertices to open in VC3D) and, with `--flags`, one boolean mask per segment and check on the segment's own grid, so flagged vertices can be dropped before a spiral fit or a relative winding count. The exit code is 0 only when every check looked and none flagged.

Geometry alone cannot say which segment left its sheet, or whether papyrus layers are pressed together or skipped by the traces: that takes a look at the CT, as in the [PHerc0139 note](../logs/2026-10-14-pherc0139-segment-defects.md). A flag is a disagreement between segments and the umbilicus, not a statement about the papyrus, and nothing here concerns ink or text.

## When to use it

- Before a spiral fit, a relative winding count or a winding number assigned per point: find and drop the vertices on missing sectors, stack ends, doubly traced ends and order conflicts (`--flags`).
- To review a set of published or newly traced segments for one scroll: where windings are missing, crossed, doubled or run past a full turn, with example vertices to look at in VC3D.
- To compare two versions of the same segments (two resolutions, or before and after a retrace) on the same rays.

Do not use it:

- To ask whether two given segments trace the same sheet: use [`overlap`](overlap.md).
- To check cross-scan meshes and transforms against the catalog: use [`meshaudit`](meshaudit.md).
- To find or fit the umbilicus itself: use the scroll center finder, [`umbilicus`](umbilicus.md).
- To judge whether a segment lies on papyrus: it reads no CT. Look at the CT in VC3D at the example vertices.
- For one or two segments: a stack needs at least three, and the innermost and outermost get no missing-sector check.

## Quick start

```bash
python -m pip install numpy tifffile scipy
B=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139; S=""
for id in 20260219000000-w033_2026021913 20260303000000-w034_2026030317 20260317000000-w035_2026031718 \
          20260316000000-w036_2026031607 20260310000000-w037_2026031015; do
  w=${id#*-}; S="$S ${w%%_*}=$B/segments/$id/mesh/${id%%-*}-on-20260102150214-2.399um.tifxyz"
done
python -m kit stackcheck $S --umbilicus $B/representations/umbilicus/20260102150214-umbilicus-20260826112529.json \
    --stride 2 --upsample 1 --plane-z 8600 28800 200 --coincide-um 18.72 \
    --out work/stackcheck/w033-w037.json --flags work/stackcheck/w033-w037-flags.npz
```

This is run A of the [PHerc0139 note](../logs/2026-10-14-pherc0139-segment-defects.md): PHerc0139 w033 to w037 on their own 2.399 um volume, every second grid row and column. The first run downloads about 100 MB into `work/stackcheck/cache`; the note ran it on 14 October 2026 (49.8 s) and its findings are in the note. This page did not rerun it.

To try it without downloads, this page wrote the test module's synthetic spiral (six windings one pitch, 100 um, apart; voxel 2 um) as tifxyz folders `w00` to `w05`, with w02 missing from 100 to 160 degrees between z 100 and 300, and ran `python -m kit stackcheck DIR/w00 DIR/w01 DIR/w02 DIR/w03 DIR/w04 DIR/w05 --umbilicus DIR/umbilicus.json --planes 40` (`DIR` is the folder it wrote). It printed, among the other lines:

```
kit stackcheck: 6 segments, voxel 2.0 um; 40 planes z 5.0 to 395.0, 360 rays each
  w00: 11029 vertices, 0.04 cm2, z 0.0 to 400.0, radius 850.0 um, local pitch 99.9 um
...
b. missing sectors (neighbors crossed, segment not)
  w02: 1342 gap rays (9.3 %) in its height, 0 beyond it; w01 to w03 median 200.0 um in the gap vs 200.0 um elsewhere; gap z 95.0 to 305.0, starts 100.0 to 100.0 and ends 160.0 to 160.0 deg (10th to 90th percentile)  FLAG
...
not covered by any check: missing sectors of w00 and w05: the innermost and outermost segments have a neighbor on one side only
not covered by any check: missing runs that include w00 or w05
flagged: {"missing_sectors": ["w02"]}
```

and exited 1. The same stack without the gap ended `clean: every check looked and none flagged (see 'not covered' above)` and exited 0. It worked when the exit code is 0 or 1 and the report names every segment; 2 means it could not run.

## Checks and controls

- **Every check can fail, and does on planted defects.** The tests build a clean six-winding Archimedean spiral that passes every check, then plant one defect at a time (a missing sector, two adjacent missing sectors, an inversion, a skipped winding, a turn overlap at either end of the turn, a missing stack end, a winding traced twice, one missing all the way, a segment on its neighbor's sheet) and require that defect's own check, and no other, to flag it (`tests/test_stackcheck.py`).
- **A check that saw nothing is not a pass.** An adjacent pair no ray crosses once each, a segment with a neighbor along the normal for under half its vertices, or an order check left with under half its vertices is listed under `summary.not_checked`, and the stack is then not clean (exit 1). `summary.not_covered` names, in every report, what no check can see: missing sectors of the innermost and outermost segments, and missing runs that include them.
- **Control pairs for a missing sector.** For a missing sector the report gives `control_pairs`: other pairs as many windings apart as the outer pair (four), lying wholly inside or wholly outside the segment, with their spacing on the gap's rays against the rays where the segment is present. On PHerc0139 (run B) those pairs keep 0.91 to 1.12 times their spacing, against 0.46 for w033/w037 across the w035 gap (`stackcheck_checks.control_pairs_four_windings_apart_B` in [`results.json`](../results.json)).
- **Real data.** On PHerc0139 w023 to w040 it flagged a gap in w035 (a median 258 degrees of its turn traced) and w023 to w034 traced a median 28 to 48 degrees per grid line past a full turn (66 for w026); the CT look at 12 places in the note is Interpretation ([note](../logs/2026-10-14-pherc0139-segment-defects.md)). It has been run on real data only for PHerc0139 w023 to w040.

Claim label: Sourced fact for the report's numbers (measurements of published segment vertices against a published umbilicus; no CT, no model); which segment left its sheet, and why, is Interpretation.

## Commands and options

### `python -m kit stackcheck`

```
usage: python -m kit stackcheck [-h] --umbilicus UMBILICUS
                                [--transform TRANSFORM] [--catalog CATALOG]
                                [--voxel-um VOXEL_UM] [--stride STRIDE]
                                [--planes PLANES] [--plane-z START STOP STEP]
                                [--ray-step-deg RAY_STEP_DEG]
                                [--max-normal-um MAX_NORMAL_UM]
                                [--coincide-um COINCIDE_UM]
                                [--skip-frac SKIP_FRAC]
                                [--min-count MIN_COUNT]
                                [--min-share MIN_SHARE] [--upsample UPSAMPLE]
                                [--cache CACHE] [--out OUT] [--flags FLAGS]
                                [--json] [--verbose] [--exit-zero]
                                segments [segments ...]
```

The settings that show `none` take their value from `DEFAULTS` in `kit/stackcheck.py`, given in brackets.

| Option | Default | Meaning |
| --- | --- | --- |
| `segments` | required | Three or more tifxyz folders, inner to outer, one per winding: local paths, `https://` URLs, or `s3://` URLs (`s3://vesuvius-challenge-open-data/...` is read over HTTPS). `NAME=PATH` names one; NAME has no `/`, `\` or `:`, and an argument that is an existing path is a path even with `=`. Unnamed, a segment is named after the nearest folder above the path that is neither `mesh` nor a `.tifxyz` folder. Names must differ |
| `--umbilicus UMBILICUS` | required | The scroll's umbilicus JSON, a path or URL: `control_points` with `x`, `y`, `z`, and `metadata.voxelsize_um` and `metadata.volume` when known. Must be in the volume the segments are mapped into |
| `--transform TRANSFORM` | none | Maps the segments into the umbilicus's volume: a JSON file holding a 3x4 or 4x4 matrix (a list, or an object with `matrix`, and optionally `from_volume_id`, `to_volume_id`), or `catalog:SAMPLE:FROM_VOLUME:TO_VOLUME` for the catalog's sample-level matrix |
| `--catalog CATALOG` | none | The catalog `metadata.json` (path or URL) for `catalog:...`; without it, the bucket's `metadata.json` |
| `--voxel-um VOXEL_UM` | none | Voxel size in um of the umbilicus's volume. Without it: the umbilicus's `metadata.voxelsize_um`, else (without `--transform`) the folder names' `-N.NNNum.tifxyz`. Must agree with each known one to 1 % |
| `--stride STRIDE` | `1` | Use every Nth grid row and column of each segment; masks are repeated back to the full grid |
| `--planes PLANES` | none (50) | Planes of constant z for the rays, spread evenly over the stack's height |
| `--plane-z START STOP STEP` | none | Explicit plane heights in voxels, STOP included, instead of `--planes`; at least one must lie within the stack |
| `--ray-step-deg RAY_STEP_DEG` | none (1) | Degrees between rays, above 0 and at most 10 |
| `--max-normal-um MAX_NORMAL_UM` | none (600) | Farthest a neighbor is looked for along a vertex normal, um |
| `--coincide-um COINCIDE_UM` | none (20) | Two segments this close cannot be told apart: sets the coincident-pair check and mask, and which inversions count for the order flag (the note used 18.72, 2 voxels at 9.362 um) |
| `--skip-frac SKIP_FRAC` | none (0.5) | A skipped winding is closer than this share of the local pitch; above 0 and at most 1 |
| `--min-count MIN_COUNT` | none (10) | Rays or vertices a check must find to flag, at least 1 |
| `--min-share MIN_SHARE` | none (0.01) | Share of the rays or vertices it looked at that a check must find to flag, 0 to 1 |
| `--upsample UPSAMPLE` | none (2) | Neighbor grids are made this much denser (bilinear) for the normal search; 1 keeps them as they are |
| `--cache CACHE` | `work/stackcheck/cache` | Where bucket segments are kept; a file already there and not empty is not fetched again |
| `--out OUT` | none | Write the JSON report here (parent folders are made); `work/` is git-ignored |
| `--flags FLAGS` | none | Write the masks here as `.npz` (the suffix is added when missing); the report's `flags_file` names the file written |
| `--json` | off | Print the whole report as JSON instead of the text summary |
| `--verbose` | off | Progress lines on stderr: fetched URLs, rays cast, and each segment's normal search with elapsed seconds |
| `--exit-zero` | off | Exit 0 when the report is written even if something was flagged (`summary.clean` says so); errors still exit 2. VC3D's entry uses it so flags come back as a result |

Two settings are fixed in the code and have no option: `tol_cells` 1.5 (same height and angle means within 1.5 grid steps of z and of arc; settable only through `settings` in the Python API) and `PAIR_SPACING` (0.5, 1.75).

### Environment variables

Both are read by [`meshaudit`](meshaudit.md)'s readers, which this command uses.

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_MAX_TIFF_ELEMENTS` | `200000000` (`meshaudit.MAX_TIFF_ELEMENTS`) | Largest grid TIFF read, in array elements, checked before decoding |
| `KIT_MAX_GUNZIP_BYTES` | `1073741824` (`meshaudit.MAX_GUNZIP_BYTES`, 1 GiB) | Largest size a gzipped download (a fetched file or the umbilicus JSON) may inflate to; a larger one fails as `cannot fetch ...` or `cannot read the umbilicus ...` |

## Python API

```python
from kit import stackcheck
rep, segs, masks = stackcheck.run(["w0=a", "w1=b", "w2=c"], "umbilicus.json", settings={"planes": 40})
print(rep["summary"]["clean"], rep["summary"]["flagged"])
stackcheck.write_flags("flags.npz", segs, masks, rep["frame"]["voxel_um"])
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `run(specs, umbilicus, transform=None, catalog=None, voxel_um=None, stride=1, cache='work/stackcheck/cache', settings=None, log=None)` | `(report, segments, masks)` | `VerifyError` for bad input; `OSError` for a file it cannot write | What the command runs. `settings` takes the `DEFAULTS` keys; `log` is a function given progress lines |
| `check_stack(segs, umb, voxel_um, settings=None, log=None)` | `(report, {name: {mask: bool grid}})` | `VerifyError` for fewer than three segments, no plane within the stack, a bad setting, or a segment with no usable normal | The checks on prepared `Segment` objects; `run` adds `transform`, `settings.stride`, `frame.voxel_um_from` and `frame.volumes` |
| `check_settings(settings=None)` | dict: `DEFAULTS` updated with the given values (None keeps a default) | `VerifyError` on a bad value, or both `planes` and `plane_z` | Sets `planes` to None when `plane_z` is given |
| `write_flags(path, segs, masks, voxel_um)` | str, the path written (`.npz` added when missing) | `OSError` | Masks on each segment's input grid; a strided vertex covers its stride x stride block |
| `format_report(rep)` | str | `KeyError` for a dict that is not a report | The text the command prints |
| `load_segments(specs, transform=None, stride=1, cache='work/stackcheck/cache', log=None)` | list of `Segment` | `VerifyError` for unreadable or unfetchable folders, or names that are not unique | Strided, then mapped by the 3x4 transform |
| `Segment(name, xyz, valid, path=None, stride=1, input_shape=None, input_xyz=None)` | a segment; `prepare(umb)` adds normals (pointing away from the umbilicus), cell areas, radius, angle, unwrapped turn, z extent and median radius | `VerifyError` from `prepare` when no vertex has a usable normal | `xyz` is (H, W, 3) in the umbilicus's frame |
| `split_spec(spec)` | `(name or None, path)` | Nothing | Reads `NAME=PATH` |
| `segment_name(path)` | str | Nothing | The nearest folder above the path that is neither `mesh` nor a `.tifxyz` folder |
| `fetch_tifxyz(url, cache)` | `Path` of the local copy, `CACHE/HOST/PATH` | `VerifyError` for a URL without an http(s) scheme and a host name, for `.`, `..` or a backslash in the URL path, for a local folder that would fall outside `cache`, or a failed download of `x.tif`, `y.tif` or `z.tif` | `meta.json` is skipped when missing; each file is written as `.part` and renamed |
| `read_tifxyz(folder)` | `(xyz (H, W, 3) float64, valid (H, W) bool, meta dict)` | `VerifyError` for a missing or unreadable file, a TIFF past `KIT_MAX_TIFF_ELEMENTS`, grids that are not 2D of one shape, or no tifffile | Holes: non-finite, any coordinate below -0.5, or all zero |
| `Umbilicus(z, x, y, voxel_um=None, source=None, volume=None)` | an umbilicus; `at(z)` gives `(x, y)` | `VerifyError` with no control points | Linear between control points, constant beyond them |
| `parse_umbilicus(data, source=None)` | `Umbilicus` | `VerifyError` for missing keys, values that are not finite numbers, or a voxel size that is not above 0 | Reads `control_points` (or `points`, or a bare list) and `metadata` |
| `load_umbilicus(src)` | `Umbilicus` | `VerifyError` when the file or URL cannot be read | A local path or a URL |
| `load_transform(spec, catalog=None)` | 3x4 float array, or None for None | `VerifyError` for a bad spec, file, catalog, or matrix | A 4x4 matrix must end in `[0, 0, 0, 1]` |
| `transform_volumes(spec)` | `(from_volume, to_volume)`, each str or None | Nothing | From `catalog:...`, or a matrix file's `from_volume_id` and `to_volume_id` |
| `check_frame(paths, umb, transform)` | None | `VerifyError` when folder names, transform and umbilicus disagree about volumes or voxel sizes | Checks only what is known |
| `folder_voxel_um(path)` | float or None | Nothing | N from a folder name ending `-N.NNNum.tifxyz` |
| `folder_volume(path)` | str or None | Nothing | VOLUME from `ID-on-VOLUME-N.NNNum.tifxyz` |
| `umbilicus_volume(umb)` | str or None | Nothing | From `metadata.volume`, else the file name `VOLUME-umbilicus-...json` |
| `grid_geometry(xyz, valid)` | `(normals (H, W, 3), cell area per vertex in voxels squared, ok mask, median edge length)` | Nothing | Central differences where both neighbors are valid, else one-sided |
| `upsample(xyz, valid, k)` | `(xyz, valid)` on a grid of `((H - 1) k + 1, (W - 1) k + 1)` | Nothing | Bilinear; a new vertex is valid when every corner it uses is |
| `turn_angles(xyz, valid, cx, cy)` | `(angles in degrees, along)`: unwrapped along the turn; `along` is 1 when columns run along the turn | Nothing | Two vertices one turn apart differ by 360 |
| `plane_cut(tri, z0)` | (M, 2, 2) array of x, y pieces | Nothing | Where triangles cross z = z0 |
| `ray_radii(pieces, centre, nrays, keep=4)` | `(counts (nrays,), radii (nrays, keep))` | Nothing | Distinct crossings per ray and the first `keep` distances, sorted |
| `cast_rays(segs, umb, planes, step_deg, log=None)` | `(counts (P, S, R), first radii (P, S, R, 4), ray angles (R,))`, voxels | Nothing | One ray per `step_deg` from the umbilicus on each plane |
| `circ_range(deg)` | `[start, end, width]` or None | Nothing | The smallest arc holding every angle |
| `circ_quantiles(deg, ps=(10, 50, 90))` | list of angles or None | Nothing | Percentiles about the circular mean |
| `circular_runs(mask)` | list of `(start, end)` | Nothing | Runs of True in a circular array, inclusive |
| `Dense(seg, k, umb)` | a neighbor index: dense points, normals, and a KD-tree on (height, arc length) | `VerifyError` without scipy | Arc length at the segment's median radius, repeated one turn either side |
| `normal_hits(P, N, D, maxd, foot, chunk=50000)` | `(outward, inward)` signed distances along each normal, voxels, NaN where none | Nothing | Candidates at the point's height and angle, then refined around the crossing |
| `neighbour_table(segs, umb, upsample_k, maxd, tol_cells, log=None)` | list per segment: `out_d`, `out_j`, `in_d`, `in_j` grids and `adj` (distance to each adjacent segment) | `VerifyError` without scipy | The normal search behind the vertex checks |
| `sector_mask(mark, absent, present, tol_cells)` | bool grid of `mark` | Nothing | Vertices where no `absent` segment has a vertex at the same height and angle while `present` does |
| `turn_overlap(seg)` | `(spans, past, outer piece mask, inner piece mask, "start" or "end")` | Nothing | Per grid line along the turn |
| `main_sector(runs)` | list of the per-plane gap records followed up the stack | Nothing | The longest series of consecutive planes whose widest gaps overlap |
| `plane_heights(segs, planes=None, plane_z=None)` | array of plane heights | `VerifyError` for a STEP of 0 or less, or STOP below START | Evenly over the stack, at the centers of `planes` bands |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Segments | tifxyz folders: `x.tif`, `y.tif`, `z.tif` (2D grids of one shape, voxels of one volume) and `meta.json` | Inner to outer, one per winding. Folder names like `ID-on-VOLUME-N.NNNum.tifxyz` let the tool check volumes and voxel sizes. On the bucket: `PHERC/segments/SEGMENT/mesh/ID-on-VOLUME-N.NNNum.tifxyz` |
| Umbilicus | JSON: `{"control_points": [{"x", "y", "z"}, ...], "metadata": {"voxelsize_um", "volume"}}` | On the bucket: `PHERC/representations/umbilicus/VOLUME-umbilicus-DATE.json`. Its volume and voxel size set the report's frame |
| Transform | JSON matrix file or `catalog:SAMPLE:FROM:TO` | Needed when the segments are in another volume than the umbilicus, such as the 9.362 um copies of PHerc0139 against the 2.399 um umbilicus |

Frame: positions are tifxyz values in voxels of the umbilicus's volume. Angles are degrees about the umbilicus at the same z, `atan2(y - y_u, x - x_u)`, 0 to 360. Distances are um, radial along a ray or along a vertex normal. Areas are summed vertex cell areas in cm2.

Memory: every segment's neighbor grid, made `--upsample` times denser, is held at once. At the defaults (`--stride 1 --upsample 2`) a full 2.399 um copy of one PHerc0139 winding needs about 2 GB, so use `--stride 2 --upsample 1` for such copies (the module docstring).

## Outputs

The text summary has one block per check (`a. order`, `a2. pair spacing`, `b. missing sectors`, `b2. missing runs`, `c. skipped windings`, `d. turn overlaps`, `e. stack ends`), with `FLAG` on each flagged line, then `not checked:` and `not covered by any check:` lines, and a last line `clean: ...`, `flagged: {...}` or `not clean: nothing flagged, but some checks had nothing to look at`. With `--json`, or in the `--out` file, the report:

| Field | Type | Meaning |
| --- | --- | --- |
| `tool`, `version`, `created` | str, int, str | `kit stackcheck`, 1, and the UTC time |
| `frame` | object | Units in words, `voxel_um`, `voxel_um_from` (`--voxel-um`, `umbilicus metadata` or `segment folder name`), `volumes.segments` and `volumes.umbilicus` (ids or null) |
| `umbilicus` | str | The umbilicus as given |
| `settings` | object | Every setting used, `pair_spacing_ratio` and `stride`; `planes` is null with `--plane-z` |
| `rays` | object | `planes` (count), `z` (first and last height), `rays_per_plane`, `ray_step_deg` |
| `transform` | 3x4 list or null | The matrix applied |
| `segments[]` | list | Per segment: `name`, `path`, `input_grid`, `stride`, `vertices`, `area_cm2`, `z` (extent), `median_radius_um`, `grid_step_um`, `local_pitch_um` |
| `summary.clean` | bool | True when nothing is flagged and nothing is under `not_checked` |
| `summary.flagged` | object | Lists of flagged names under `order` and `coincident_pairs` and `pair_spacing` (pairs `INNER/OUTER`), `order_vertices`, `missing_sectors`, `skipped_windings`, `turn_overlaps`, `stack_ends` (segments) and `missing_runs` (`INNER/OUTER` either side of the run) |
| `summary.not_checked` | list of str | Checks that had nothing to look at |
| `summary.not_covered` | list of str | What no check can see in this stack |
| `order.pairs[]` | list | Per adjacent pair: `rays` crossing both once, `inverted_rays` and `_share`, `inverted_beyond_coincide_rays` and `_share`, `within_coincide_rays` and `_share`, `spacing_um_q10_25_50_75_90`, `inverted` (z, `angle_deg`, `rays_by_30_deg`, `depth_um_q25_50_75`), `normal_spacing_um_q25_50_75`, `spacing_against_nearby_pairs`, and `flagged`, `coincident_flagged`, `spacing_flagged` |
| `order.vertices[]` | list | Per segment: out-of-order vertices (`vertices`, `share`, `area_cm2`, `z`, `angle_deg` as start, end and width, `parts`), `groups` by side and neighbor with `distance_um_q25_50_75`, `examples`, `flagged` |
| `missing_sectors[]` | list | Per segment except the end ones: `gap_rays`, `gap_share`, `rays_with_both_neighbours`, `gap_rays_outside_own_height`, `neighbour_spacing` (gap and present), `outer_pair_spacing`, `gap_by_height`, `control_pairs`, `gap_extent` (z, start and end angles with 10th, 50th and 90th percentiles, widths), `neighbour_vertices` with `examples`, `flagged`, and `per_plane` when flagged |
| `missing_runs[]` | list | Per pair of segments with two or more missing between them: `between`, `missing`, `rays`, `rays_with_both`, `share`, `rays_beyond_their_heights`, `z`, `angle_deg`, `planes`, `spacing` (hole and all present), `per_plane`, `bounding_vertices`, `flagged` |
| `skipped_windings[]` | list | Per segment: `local_pitch_um`, `limit_um`, the vertex counts and areas, `distance_um_q25_50_75`, `beyond_coincide`, `beyond_coincide_off_turn_overlap`, `on_own_doubly_traced_end_left_out`, `groups`, `in_missing_sector_share`, `in_turn_overlap_share`, `examples`, `flagged` |
| `turn_overlaps[]` | list | Per segment: `lines`, `turn_deg_per_line_q10_50_90` and `_max`, `lines_past_full_turn`, `past_full_turn_deg_q10_25_50_75_90` and `_max`, `doubly_traced_end` (`end_of_turn`, `piece` `outer` or `inner`, area and extent), `neighbour` (the segment whose sheet it lies on, `matched_share`, `distance_um_q5_25_50_75_95`, `within_coincide_share`, `beyond_coincide_share`, `beyond_coincide_median_um`, `vertices_at_same_height_and_angle`), `flagged` |
| `stack_ends[]` | list | Per segment except the end ones: `z`, `missing_below` and `missing_above` (`z`, `between`, `windings_without_segment`) when a winding has no segment there, `flagged` |
| `examples[]` (in several checks) | list | Up to three vertices of the largest flagged part: `segment`, `row` and `col` on the input grid, `xyz` and `xyz_input` (before the transform), `angle_deg`, `nearest_outer` and `nearest_inner` (segment and `distance_um`) |
| `seconds` | float | Time of the checks, without loading |
| `flags_file` | str | The masks file written, only with `--flags` |

The `--flags` file holds `names`, `voxel_um`, and for each segment NAME the boolean masks `NAME/order`, `NAME/missing_sector`, `NAME/skipped_winding`, `NAME/turn_overlap`, `NAME/coincident`, `NAME/stack_end` and their union `NAME/any`, each of the segment's input grid shape. Read it with `numpy.load`.

| Exit code | Meaning |
| --- | --- |
| `0` | Clean: every check looked and none flagged (what `summary.not_covered` names is still unseen) |
| `1` | Something is flagged, or a check had nothing to look at (`summary.not_checked`) |
| `2` | The run could not be made: bad input, an output that cannot be written, an unexpected error (with its traceback), or a usage error from the argument parser |

## Failure modes

Every message below goes to stderr with exit code 2.

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` | A missing or wrong argument, such as no `--umbilicus` | Check the command against Commands and options |
| `a stack needs at least three consecutive segments` | Fewer than three segments | Give at least three consecutive windings |
| `segment names must differ (name them NAME=PATH): [...]` | Two segments got the same name | Name them with `NAME=PATH` |
| `cannot read the tifxyz folder FOLDER: ...` | No `x.tif`, `y.tif` or `z.tif` there, or an unreadable TIFF | Point at the `.tifxyz` folder itself |
| `FOLDER: x.tif, y.tif and z.tif must be 2D grids of one shape` | Grids of different shapes, or multi-page TIFFs | Use a tifxyz folder as villa writes it |
| `NAME: no vertex with a usable normal` | Every vertex is a hole, or the grid is degenerate | Check the segment; it may be a placeholder |
| `refusing a URL without an http(s) scheme and a host name: URL` | A URL with no host (such as `https:///PATH`), a host of only dots, or a `/` or `\` in the host part | Give the full bucket URL |
| `refusing a URL with '.' or '..' in its path: URL` | A URL with `.` or `..` parts, or a backslash in a part, which could write outside `--cache` | Give the plain URL |
| `refusing a URL whose cache folder DEST is outside --cache ROOT` | The URL's host and path would put the fetched files outside `--cache` (checked on the path as written, so a `--cache` that is a link to another disk works) | Give the plain URL |
| `cannot read the tifxyz folder FOLDER: TIFF declares N elements, over M; refused (raise KIT_MAX_TIFF_ELEMENTS to allow it)` | A grid TIFF declares more elements than `KIT_MAX_TIFF_ELEMENTS` (200,000,000 by default, about a 14,000 px square), checked before any pixel is decoded, against decompression bombs | Check the file; for a genuinely larger segment you trust, raise `KIT_MAX_TIFF_ELEMENTS` (see Environment variables) |
| `cannot fetch URL/x.tif: ...` | A network or HTTP error, or no such segment on the bucket | Check the URL in a browser and the network; rerun, since fetched files are kept |
| `cannot read the umbilicus UMBILICUS: ...` | A missing file, unreachable URL, or not JSON | Fix the path or URL |
| `UMBILICUS: expected control points with x, y and z keys` | Not the published umbilicus format | Use the scroll's `representations/umbilicus/...json` |
| `UMBILICUS: control points must be numbers` | A control point value that is not a number | Fix the file |
| `UMBILICUS: control points must be finite` | NaN or infinite values | Fix the file |
| `UMBILICUS: metadata.voxelsize_um must be a number above 0 (got ...)` | A bad voxel size in the umbilicus | Fix the file, or remove the key and give `--voxel-um` |
| `the umbilicus has no control points` | An `Umbilicus` built in Python with empty lists | Give at least one control point |
| `give --voxel-um: the umbilicus has no metadata.voxelsize_um` | No voxel size from the umbilicus, and none from the folder names | Give `--voxel-um` |
| `--voxel-um must be above 0` | `--voxel-um` 0, negative or not finite | Give the umbilicus volume's voxel size |
| `--voxel-um V differs from the umbilicus's metadata.voxelsize_um M` | They differ by more than 1 % | Leave out `--voxel-um`, or fix it |
| `--voxel-um V differs from the segments' folder names ([N] um): map the segments with --transform` | Without a transform, the folder names give another voxel size | Map the segments with `--transform`, or fix `--voxel-um` |
| `the segments are in a [N] um volume and the umbilicus in a M um one: map the segments with --transform` | Segments and umbilicus are in volumes of different voxel sizes | Add `--transform` |
| `the segments are on volume VOLUME and the umbilicus on VOLUME: map the segments with --transform` | The folder names' volume differs from the umbilicus's | Add `--transform`, or use copies on the umbilicus's volume |
| `the segments are already on the umbilicus's volume VOLUME: leave out --transform` | A transform given for segments already in the right volume | Leave out `--transform` |
| `the segments are on different volumes [...]; give copies on one volume` | Folder names name more than one volume | Use copies of every segment on one volume |
| `the segments' folder names give different voxel sizes [...] um` | Folder names name more than one voxel size | Use copies at one voxel size |
| `the transform starts on volume FROM but the segments are on VOLUME` | `catalog:SAMPLE:FROM:TO` (or the matrix file) starts on another volume | Give the segments' volume as FROM |
| `the transform ends on volume TO but the umbilicus is on VOLUME` | The transform ends on another volume than the umbilicus's | Give the umbilicus's volume as TO |
| `--transform catalog:SAMPLE:FROM_VOLUME:TO_VOLUME` | A `catalog:` spec without four parts | Write all four parts |
| `cannot read the catalog: ...` | The catalog file or URL could not be read | Fix `--catalog`, or check the network |
| `the catalog has no SAMPLE matrix from FROM to TO` | No such sample, or no sample-level matrix between those volumes | Check the sample and volume ids in the catalog |
| `cannot read the transform SPEC: ...` | A missing file or not JSON | Fix the path |
| `a transform is a 3x4 or 4x4 matrix` | The matrix has another shape or non-finite values | Give a 3x4 or 4x4 matrix |
| `a 4x4 transform must have [0, 0, 0, 1] as its last row` | A projective last row | Give an affine matrix |
| `give --planes or --plane-z, not both` | Both given | Give one |
| `--plane-z START STOP STEP needs STEP > 0 and STOP >= START` | A bad range | Fix the range |
| `--plane-z takes START STOP STEP` | A `plane_z` setting without three finite numbers (Python API) | Give three numbers |
| `no ray plane lies within the stack's heights, z LO to HI` | `--plane-z` outside the segments' z extent | Choose heights inside it |
| `--stride must be 1 or more` | `--stride` 0 or negative | Use 1 or more |
| `--KEY must be ...`, such as `--min-count must be a whole number at least 1 (got 0)` or `--ray-step-deg must be above 0 and at most 10 (got 0.0)` | A setting outside its range | Use a value in the range the message gives |
| `kit stackcheck needs numpy, tifffile and scipy` | numpy is not installed | `python -m pip install numpy tifffile scipy` |
| `kit stackcheck needs tifffile` | tifffile is not installed | Install tifffile |
| `kit stackcheck needs scipy (cKDTree)` | scipy is not installed | Install scipy |
| `kit stackcheck could not read or write a file: ...` | `--out` or `--flags` cannot be written (a folder, or a path under a file), or the output was piped into a program that closed early, such as `head` (`[Errno 32] Broken pipe`) | Fix the path; write the report with `--out` and read the file instead of piping |
| A traceback, then `kit stackcheck stopped on an unexpected error (above)` | An error the tool does not expect | Read the traceback; exit code 2 keeps it apart from a flagged stack |

## How it works

1. Load each segment (fetching bucket URLs once into `--cache`), keep every `--stride`th row and column, and map it with the transform. Check that folder names, transform and umbilicus agree on volumes and voxel sizes.
2. Per segment: normals by central differences, turned to point away from the umbilicus; cell areas; radius and angle of every vertex about the umbilicus at its own height (linear between control points); the angle unwrapped along the turn.
3. Rays: cut each segment's triangles (two per grid cell with four valid corners) with planes of constant z (`--planes` evenly over the stack, or `--plane-z`), and cast `360 / --ray-step-deg` rays from the umbilicus on each plane. For every segment and ray, count the distinct crossings and keep the first four distances.
4. Order and pair checks use only rays that cross both segments of an adjacent pair once: the spacing is the outer segment's first crossing minus the inner one's. The order flag counts rays inverted by more than `--coincide-um`; the coincident flag counts rays within `--coincide-um` either way; the pair-spacing flag compares the pair's median spacing with the median over the pairs up to two places away, itself included, outside `PAIR_SPACING = (0.5, 1.75)`.
5. Neighbors along the normal: each other segment's grid is made `--upsample` times denser and indexed by height and arc length about the umbilicus. For every vertex, the nearest crossing of each other segment along the normal, within `--max-normal-um`, outward and inward, is found among that segment's vertices at the same height and angle and refined around the crossing. Vertices with another segment within `--coincide-um` go on the coincident mask.
6. Turn overlaps first, so later checks can leave them out: per grid line along the turn, the angle traced past 360 degrees. The doubly traced end is the piece farther from the umbilicus, unless the nearer piece lies on the previous winding's sheet (its median distance to that segment under half of the rest's) where the previous segment's end is not marked already. The vertices of the segment whose sheet it lies on, at the same height and angle, are marked too.
7. Local pitch: the median spacing along the normals between adjacent segments, outside the turn-overlap masks, over the pairs either side of a segment.
8. Order per vertex: outside the coincident and turn-overlap masks, a lower winding nearest outside, or a higher one nearest inside.
9. Missing sectors: for each segment but the end ones, rays at its heights where both neighbors are crossed and it is not; the gap is followed up the stack as the longest series of planes whose widest gaps (at least 3 rays) overlap. Missing runs: the same for two or more adjacent windings. The neighbors' vertices at those heights and angles go on the missing-sector masks.
10. Skipped windings: vertices whose nearest segment along the normal is two or more windings away and closer than `--skip-frac` times the local pitch, leaving out the segment's own doubly traced end.
11. Stack ends: from each segment's z extent, heights where an inner and an outer segment both reach but this one does not.
12. A check flags when what it finds reaches both `--min-count` and `--min-share` of what it looked at; the pair-spacing and stack-end flags use their own limits instead (the ratio range, and a band taller than 1.5 grid steps).

The method is this repository's own; it follows no published method. Each check is described in the `kit/stackcheck.py` docstring.

## Cost and time

| Run | Time | Memory | Source |
| --- | ---: | ---: | --- |
| PHerc0139 run A: w033 to w037, 2.399 um, `--stride 2 --upsample 1`, 102 planes | 49.8 s | 0.75 GB | `stackcheck_checks.runs.A` in `results.json`; memory from the note (one CPU core, 2026-10-14) |
| PHerc0139 run B: w023 to w040, 9.362 um mapped with the catalog matrix, 102 planes | 144.8 s | 1.7 GB | `stackcheck_checks.runs.B`; the note |
| Run B at the defaults (50 planes, `--coincide-um 20`) | 161.6 s | Not recorded | `stackcheck_checks.runs.B_defaults` |
| Synthetic six-winding stack, 40 planes | 13 to 16 s | 166 MB | This page, 2026-10-16, 4-core Xeon cloud container (shared) |

Run A downloads about 100 MB once and run B about 25 MB (the note). It uses one core; nothing here needs Modal or a GPU. A full-resolution 2.399 um copy at the defaults needs about 2 GB per segment (the module docstring), so a large stack at full resolution may not fit a laptop's memory.

## Start from VC3D

Attach the scroll's umbilicus in VC3D and pick Scrolls > segments > "stackcheck". VC3D asks for the segments by their ids, inner to outer, separated by commas; the launcher turns the ids into folders through the agent bridge of the VC3D that started it (read-only calls, never another window's bridge), so start VC3D with its agent bridge on, or type folders instead. The registry runs `kit stackcheck ... --exit-zero`, so a stack with flags comes back as a result; `summary.clean` says whether anything was flagged. From a terminal or an agent ([toolreg](toolreg.md)):

```bash
python -m kit tools run stackcheck --input segments=W00,W01,W02 --umbilicus UMB.json --out RUN
```

## Open in VC3D

VC3D shows `RUN/stackcheck.json` as the run's result file, with example vertices per flag to look at; `RUN/flags.npz` holds the masks. Loading the flagged vertices as a point collection is planned, not built. stackcheck checks finished segments against each other; it is not an AutoPipeline (AP) stage.

## For agents

- **Command:** `python -m kit stackcheck SEG_INNER ... SEG_OUTER --umbilicus UMBILICUS.json [--transform SPEC] --out work/stackcheck/REPORT.json --flags work/stackcheck/FLAGS.npz`; add `--stride 2 --upsample 1` for full-resolution 2.399 um copies. Read the `--out` file rather than piping stdout.
- **Parse:** `summary.clean`, `summary.flagged` (which checks flagged which segments or pairs), `summary.not_checked`, `summary.not_covered`; per check, the record of a flagged name (such as `missing_sectors[].gap_extent`, `turn_overlaps[].past_full_turn_deg_q10_25_50_75_90`, `skipped_windings[].beyond_coincide`); the masks under `NAME/any` in the `.npz`.
- **Rerun:** Safe. It overwrites `--out` and `--flags`, and reuses segments already in `--cache`.
- **Success:** Exit code 0 means clean; 1 is a completed run that flagged something or could not check something; only 2 means it failed.
- **Not a pass:** exit 1 with an empty `summary.flagged` (something was not checked); a clean report whose `not_covered` names the segment you care about (the innermost and outermost); a clean run with `--max-normal-um` or `--coincide-um` changed until nothing flags; any report on a stack given out of order or with a winding left out.
- **Go-ahead:** Nothing for running it. A report on a target scroll's segments used to choose where to look for text is a triage list and stays in Scrolls-private.
- **Never:** Say a flag shows which segment left its sheet, or anything about ink or text; run it on segments of different volumes without `--transform`; treat exit 1 as a crash.

## Tests

```bash
python -m unittest tests.test_stackcheck -v
```

34 tests on synthetic Archimedean spirals built in the test file, with no downloads. They cover a clean stack passing every check; each planted defect flagged by its own check (missing sector, two adjacent missing sectors, inversion, an inversion within `--coincide-um` flagged only as coincident, skipped winding, turn overlap at the end and at the start of the turn and across a hole wider than half a turn, missing stack end, a winding traced twice, one missing all the way, a segment on its neighbor's sheet, control pairs keeping their spacing); checks with nothing to look at keeping the stack from being clean; the command line on files with a transform, the report and the masks; stride; names, URLs and `NAME=PATH`; catalog transforms and volume checks; settings, the umbilicus format, and exit codes 1 and 2; and that a fetch stays inside the cache, a cache host folder may be a link to another disk, and a grid TIFF declaring a size past the ceiling is refused. They do not fetch from the bucket and do not run on real segments. On 2026-10-16 they took about 5 minutes of wall clock in the shared container (82 s of CPU time).

## History

- 2026-10-16: a cache folder linked to another disk works again: the URL check runs on the path as written (`136b5b2`).
- 2026-10-16: fetched segments must stay inside `--cache` (a URL needs an http(s) scheme and a host name), and grid TIFFs over `KIT_MAX_TIFF_ELEMENTS` are refused (`145b0fc`).
- 2026-10-14: flags coincident and oddly spaced pairs, finds a turn overlap at the start of the turn, names what no check covers, exits 2 on an unwritable output, and checks settings and the umbilicus's voxel size (`1243518`).
- 2026-10-14: review fixes: missing runs, turn angles unwrapped across holes, missing sectors limited to the segment's heights, a stack-end mask, inversions counted beyond `--coincide-um`, gap by height and control pairs, `summary.not_checked`, volume checks, and paths with `=` (`2bf31fd`).
- 2026-10-14: first version, with the PHerc0139 note and the release entry (`47cd607`).

## Related

- [The PHerc0139 segment note](../logs/2026-10-14-pherc0139-segment-defects.md): the real runs, the CT look, what to drop before a spiral fit, and the limits.
- [`results.json`](../results.json), key `stackcheck_checks`: the PHerc0139 numbers with their settings and times.
- [`overlap`](overlap.md): whether two given segments trace one sheet.
- [`meshaudit`](meshaudit.md): the catalog's cross-scan matrices, which `--transform catalog:...` uses.
- [`umbilicus`](umbilicus.md): the scroll center finder.
- [`fetch`](fetch.md): downloads bucket folders, if you want local copies first.
- [`GLOSSARY.md`](../../GLOSSARY.md): umbilicus, winding, tifxyz.
