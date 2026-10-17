# overlap: do two segments trace the same papyrus, and do their ink maps agree there

`python -m kit overlap` measures how close two tifxyz meshes run (one sheet traced twice, or two surfaces) and how well their human labels agree there against displaced matches; `python -m kit collate` compares two traces' ink maps by gap, against a control.

| Field | Value |
| --- | --- |
| Id | `overlap` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit overlap`, `python -m kit collate`, `from kit import overlap` |
| Code | `kit/overlap.py`, `kit/cli.py` (`cmd_overlap`, `cmd_collate`), `kit/auc.py` (`_levels`), `kit/layers.py` (`_zarr`), `kit/verify.py` (`load_map`, `_numpy`, `VerifyError`) |
| Tests | `tests/test_overlap.py` |
| Needs | Python 3.10 or newer, numpy, scipy (`cKDTree`, `ndimage.zoom`), tifffile; zarr for `--labels-a` and `--labels-b`; imagecodecs for LZW or zstd TIFF maps. Checked with Python 3.13, numpy 2.5, scipy 1.18, zarr 3.4 |
| Runs on | Any CPU. PHerc0841 w00 against ag896 with labels takes 38 s and 254 MB; a full-size synthetic pair takes 9 s without labels, and `collate` with a control 37 s and 509 MB (measured 2026-10-16, 4-core Xeon cloud container, shared) |
| Network | None |
| Writes | Nothing (prints only) |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07 (`25070df`) |
| Guide | [The overlap and baseline log](../logs/2026-10-07-overlap-and-baseline.md), sections 1, 4 and 6 |
| Checked | 2026-10-16 against commit `63753fa` |

## What it does

A segment's mesh is a tifxyz folder: three 2D float images, `x.tif`, `y.tif` and `z.tif`, that give each grid point's position in voxels of one CT volume. Villa and the team publish the grid at a fixed fraction of the segment's flattened surface (the `scale` in `meta.json`, usually 0.05, so one mesh point per 20 surface pixels), with holes marked -1. Here a "trace" is one segment's mesh, and the "gap" is the 3D distance from a point of one trace to the nearest point of the other, in voxels.

`kit overlap` answers: do two segments trace the same papyrus? It makes both grids 4 times denser (`UPSAMPLE = 4`, about 47 um between points at 9.366 um), finds for every point of A the nearest point of B and the reverse, and reports the median gap and the share of A within 2, 5, 12, 25 and 50 voxels. Over `--within` voxels (default 12) the two are counted as one sheet. Given both segments' label folders, it also reports the Dice score (twice the shared ink, over the sum of both inks) of their human ink labels where both are labelled and the traces run within `--within`, against the same matches displaced 1 to 3 mm in the surface plane. Two traces of one sheet count twice in a benchmark, and a train and test split between them trains on the test sheet: PHerc0841 w00 and ag896 are such a pair ([log](../logs/2026-10-07-overlap-and-baseline.md), section 1).

`kit collate` treats two traces of one sheet as two copies of one text, as a decipherer collates two manuscripts: what both copies show is more likely real. For two ink maps, each on its own segment's surface grid, it reports by gap bin the Pearson correlation of the maps at matched points and the "reappear" share: of A's points in the top fraction of A's map (`--top`, default 0.2), the share whose matched B point is in the top fraction of B's map (chance is the fraction itself). Each number comes with displaced matches as a null, and the same numbers for a control pair (`--control-a`, `--control-b`), such as high-passed raw CT or the reverse-depth maps, which must agree less, or the agreement is not about ink.

Neither command says which trace is right, and neither registers or corrects a surface. The gap is the distance to the nearest sampled point, so on the 47 um grid it includes lateral sampling error and is not a pure normal offset ([follow-up log](../logs/2026-10-07-followup-tests.md)). An ink map is model output, not a reading: two maps that agree are still model output, and agreement is not evidence of letters.

## When to use it

- Before averaging scores over labelled segments, or splitting them into training and test: check that no two of them are one sheet traced twice.
- To check that two labellings of one sheet agree beyond chance (labels Dice against the displaced null).
- To ask whether two ink maps of overlapping traces agree where the traces run together, and whether that agreement beats a control such as raw CT texture.
- With `--box`, to ask whether one candidate area of map A reappears on trace B.

Do not use it:

- To score a map against labels: use [`auc`](auc.md).
- To compare two maps of the same surface on the same grid, such as a CPU and an MPS run: use [`verify`](verify.md).
- To check a stack of consecutive windings against the umbilicus: use [`stackcheck`](stackcheck.md).
- To measure or correct a surface's offset along its normal: use [`surfacefix`](surfacefix.md), whose correspondence is exact on the native grid.
- To check published cross-scan meshes against their transforms: use [`meshaudit`](meshaudit.md).
- On a target scroll in public work. Collating overlapping target meshes as a candidate filter is an untested idea (README finding 9); its outputs belong in Scrolls-private, and its readout rule must be preregistered first (the preregistration rule in [`AGENTS.md`](../../AGENTS.md)).

## Quick start

```bash
# PHerc0841 w00 and ag896: their 9.366 um meshes (0.6 and 0.7 MB) and labels (0.1 MB per store).
S=PHerc0841/segments; L=ink-labels/2.403um-volume-20260319124803/20260918
python -m kit fetch $S/20260220213127-w00/mesh/20260220213127-on-20250821151531-9.366um.tifxyz w00 --workers 8
python -m kit fetch $S/20260220214732-auto_grown_20260220144552896/mesh/20260220214732-on-20250821151531-9.366um.tifxyz ag896 --workers 8
for z in inklabels supervision; do
  python -m kit fetch $S/20260220213127-w00/$L/$z.zarr labels-w00/$z.zarr --workers 8
  python -m kit fetch $S/20260220214732-auto_grown_20260220144552896/$L/$z.zarr labels-ag896/$z.zarr --workers 8
done

python -m kit overlap w00 ag896 --voxel-um 9.366 --labels-a labels-w00 --labels-b labels-ag896
```

- `w00`, `ag896`: the tifxyz folders the fetches write; `labels-w00`, `labels-ag896`: each segment's `inklabels.zarr` and `supervision.zarr`.
- For `collate`, add two ink maps of the same segments: `python -m kit collate w00 ag896 MAP_A MAP_B --voxel-um 9.366 --control-a CONTROL_A --control-b CONTROL_B`. `MAP_A` is an ink map on w00's surface grid (`.tif` or `.npy`, any resolution), `MAP_B` one on ag896's, and `CONTROL_A`, `CONTROL_B` the control maps of the same two surfaces, such as their reverse-depth maps.

It printed, on 2026-10-16:

```
A w00
B ag896  (grid 46.8 um)
A to B: 12.71 cm2, median gap 8.6 vox, within 2 vox 2%, 5 vox 17%, 12 vox 75%, 25 vox 98%, 50 vox 100%
B to A: 12.77 cm2, median gap 8.6 vox, within 2 vox 2%, 5 vox 17%, 12 vox 75%, 25 vox 98%, 50 vox 99%
within 12 vox: 75% of A; overlapping traces: one sheet over this share of A; count it once in a benchmark
labels where both traces are labelled (0.112 cm2): Dice 0.828, displaced matches mean 0.27, 99th percentile 0.668
```

These match the log's numbers (median 8.6 voxels; 17, 75 and 98 % within 5, 12 and 25; Dice 0.83). On synthetic data, `collate` of two traces 3 voxels apart with one map copied to both and a smooth-noise control printed:

```
gap 0-47 um (17024 pts):  map r 1.0 (displaced 0.01), reappear 1.0 (displaced 0.212)  control r -0.055 (displaced -0.017), reappear 0.174 (displaced 0.186)
gap 47-112 um (0 pts):
```

It worked when the exit code is 0 and the lines above appear. A label Dice means something only well above the displaced 99th percentile, and a map agreement only well above both its displaced null and its control.

## Checks and controls

- **Displaced matches** (both commands, `--draws`). Each draw moves every matched point of B by one random 1 to 3 mm step in the surface plane (`DISPLACE_MM = (1.0, 3.0)`) and recomputes the number. Labels that agree only because ink is common give a Dice near the displaced mean. Pass on real data: w00 and ag896 agree with Dice 0.828 against a displaced mean of 0.27 and 99th percentile 0.668 (this page's run, 2026-10-16, seed 0); the log's own script gave 0.83 against 0.25 and 0.69 (section 1).
- **A separate surface** for the gap. The same measurement on two different surfaces must come out far apart: w00 against ag405 has median gap 38.7 voxels and 5 % within 12 ([log](../logs/2026-10-07-overlap-and-baseline.md), section 1), and two synthetic planes 200 voxels apart give 0 % and `separate surfaces` (this page's run).
- **A control pair** for `collate` (`--control-a` and `--control-b`, both needed). On PHerc0841 the team's ink maps correlate 0.86 within 28 um against 0.51 for letter-scale raw CT, and a strong ink spot reappears 0.70 of the time against 0.50 for CT texture, with chance 0.20 ([log](../logs/2026-10-07-overlap-and-baseline.md), section 6). Those maps are probably in-sample on PHerc0841 ([Hecate log](../logs/2026-10-09-pherc0841-hecate.md)), so the levels are not a held-out result. The 7 October handoff says `kit overlap` and `kit collate` reproduce the log's numbers on the real data (commit `25070df`); this page reran only `overlap`.
- **Sampling error.** On the 47 um grid the gap includes lateral error, so neither the gap bins nor a tolerance taken from them are pure normal distances ([follow-up log](../logs/2026-10-07-followup-tests.md)).

Claim label: Sourced fact for `overlap` (distances between published meshes and the agreement of published labels, measured here); Model output for `collate` (agreement of two ink maps); what either means for a sheet or for ink is Interpretation.

## Commands and options

### `python -m kit overlap`

```
usage: python -m kit overlap [-h] --voxel-um VOXEL_UM [--within WITHIN]
                             [--labels-a LABELS_A] [--labels-b LABELS_B]
                             [--level LEVEL] [--draws DRAWS] [--seed SEED]
                             [--json]
                             mesh_a mesh_b
```

| Option | Default | Meaning |
| --- | --- | --- |
| `mesh_a` | required | Segment A's tifxyz folder (`x.tif`, `y.tif`, `z.tif`, and `meta.json` when there) |
| `mesh_b` | required | Segment B's tifxyz folder, in the same volume as A |
| `--voxel-um VOXEL_UM` | required | Voxel size of the mesh coordinates in um, such as 9.366; turns grid steps into um and cm2 |
| `--within WITHIN` | `12` | Gap in voxels (an integer) that counts as one sheet: sets `same_sheet_share` and which points the label Dice uses |
| `--labels-a LABELS_A` | none | Folder holding A's `inklabels.zarr` and `supervision.zarr`. Give it together with `--labels-b`, or neither |
| `--labels-b LABELS_B` | none | The same for B. Giving only one of the two is refused |
| `--level LEVEL` | `2` | Pyramid level of the label stores to read (`auc.DEFAULT_LEVEL`); any level that spans the whole surface works |
| `--draws DRAWS` | `200` | Displaced matches for the label null; a draw with fewer than 50 points is dropped |
| `--seed SEED` | `0` | Seed of the displaced matches; the same seed gives the same null |
| `--json` | off | Print the result as JSON (the fields under Outputs) instead of text |

### `python -m kit collate`

```
usage: python -m kit collate [-h] --voxel-um VOXEL_UM [--gaps GAPS [GAPS ...]]
                             [--top TOP] [--control-a CONTROL_A]
                             [--control-b CONTROL_B] [--box Y0 Y1 X0 X1]
                             [--draws DRAWS] [--seed SEED] [--json]
                             mesh_a mesh_b map_a map_b
```

| Option | Default | Meaning |
| --- | --- | --- |
| `mesh_a` | required | Trace A's tifxyz folder, as for `overlap` |
| `mesh_b` | required | Trace B's tifxyz folder, in the same volume |
| `map_a` | required | Ink map of A on A's whole surface grid, `.tif` or `.npy`, any resolution; 0 means no prediction |
| `map_b` | required | Ink map of B on B's whole surface grid |
| `--voxel-um VOXEL_UM` | required | Voxel size of the mesh coordinates in um; turns gaps and grid steps into um |
| `--gaps GAPS ...` | `0 3 6 9 12 18 30` | Gap bin edges in voxels; each bin holds gaps above its lower edge and up to its upper edge |
| `--top TOP` | `0.2` | A strong spot is in this top fraction of its map's nonzero values over the whole trace; also the chance level of `reappear` |
| `--control-a CONTROL_A` | none | Control map of A, such as high-passed raw CT or the reverse-depth map. Give it together with `--control-b`, or neither |
| `--control-b CONTROL_B` | none | Control map of B. Giving only one of the two is refused |
| `--box Y0 Y1 X0 X1` | none | Keep only A's points inside rows Y0 to Y1 and columns X0 to X1 of map A (pixels of map A, ends excluded): one candidate area |
| `--draws DRAWS` | `50` | Displaced matches for the null; a draw with fewer than 30 points is dropped |
| `--seed SEED` | `0` | Seed of the displaced matches, shared over the bins and the map and control |
| `--json` | off | Print the result as JSON (the fields under Outputs) instead of text |

## Python API

```python
from kit import overlap
r = overlap.overlap("w00", "ag896", 9.366, labels_a="labels-w00", labels_b="labels-ag896")
print(r["same_sheet_share"], r["labels"]["dice"], r["labels"]["null_dice_p99"])
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `load_mesh(path, upsample=UPSAMPLE)` | dict: `points` (N, 3) float64 voxels, `rows` and `cols` on the upsampled grid, `shape`, `path`, `surface_px_per_point` (1 / scale / upsample) | `VerifyError` for an unreadable folder, grids that are not 2D of one shape, fewer than 4 valid points, or missing numpy or scipy; `ImportError` without tifffile | Holes: non-finite, any coordinate below 0, or all zero. The scale is `meta.json`'s `scale[0]`, 0.05 when missing |
| `sample_grid(array, mesh)` | 1D array, one value per mesh point | Nothing of its own | Nearest neighbour of a 2D array that spans the whole surface, by proportional grid position |
| `match(a, b)` | `(distances, indices)`: gaps in voxels from each point of `a`, and the index of `b`'s nearest point | `VerifyError` without scipy | A `cKDTree` query in 3D |
| `overlap(mesh_a, mesh_b, voxel_um, within=12, labels_a=None, labels_b=None, level='2', draws=200, seed=0, upsample=UPSAMPLE)` | The `overlap` dict under Outputs | `VerifyError` for bad meshes or label stores, or only one of `labels_a`, `labels_b` | What `kit overlap` runs; labels only when both folders are given |
| `collate(mesh_a, mesh_b, map_a, map_b, voxel_um, gaps=(0, 3, 6, 9, 12, 18, 30), top=0.2, control_a=None, control_b=None, box=None, draws=50, seed=0, upsample=UPSAMPLE)` | The `collate` dict under Outputs | `VerifyError` for bad meshes or maps, a box with no point of A, or only one of `control_a`, `control_b`; `FileNotFoundError` for a missing `.npy` | What `kit collate` runs; the control only when both control maps are given |
| `format_overlap(r)` | str | `KeyError` for a dict that is not an `overlap()` result | The text `kit overlap` prints |
| `format_collate(r)` | str | `KeyError` for a dict that is not a `collate()` result | The text `kit collate` prints |
| `dumps(result)` | str | Nothing of its own | JSON with an indent of 2, as `--json` prints |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Mesh (`mesh_a`, `mesh_b`) | A tifxyz folder: `x.tif`, `y.tif`, `z.tif`, 2D grids of one shape, positions in voxels of one volume; `meta.json` with `scale` | Both meshes must be in the same volume, at the voxel size given by `--voxel-um`. On the open-data bucket: `PHERC/segments/SEGMENT/mesh/ID-on-VOLUME-N.NNNum.tifxyz`. A grid of 211 x 238 points (PHerc0841 w00) becomes about 800,000 points after upsampling |
| Labels (`--labels-a`, `--labels-b`) | A folder with `inklabels.zarr` and `supervision.zarr`: zarr groups with level keys, or single 2D arrays | Above 0 is ink, and above 0 is supervised. The array at `--level` must span the trace's whole surface, since it is sampled by proportional grid position. The level is read whole into memory. On the bucket: `SEGMENT/ink-labels/VOLUME/DATE/` |
| Ink maps (`map_a`, `map_b`) and control maps | 2D TIFF (read with tifffile and squeezed) or `.npy` (squeezed) on the trace's own surface grid, any resolution and dtype | Compared as float64. Exactly 0 means no prediction: a point where either map is 0 is left out |
| `--box` | Four integers in pixels of map A | Rows Y0 to Y1, columns X0 to X1, ends excluded |

## Outputs

Text by default (see Quick start). With `--json`, `overlap` prints one object:

| Field | Type | Meaning |
| --- | --- | --- |
| `a`, `b` | str | The mesh folders as given |
| `voxel_um` | float | `--voxel-um` |
| `grid_um` | float | Spacing of A's upsampled points in um (1 decimal) |
| `within_vox` | int | `--within` |
| `a_to_b.area_cm2`, `b_to_a.area_cm2` | float | Area of the valid upsampled points of A (or B), cm2 |
| `a_to_b.median_gap_vox` | float | Median gap from A's points to B, voxels (1 decimal) |
| `a_to_b.share_within` | object | Keys `"2"`, `"5"`, `"12"`, `"25"`, `"50"` (voxels): share of A's points within that gap |
| `b_to_a` | object | The same from B to A |
| `same_sheet_share` | float | Share of A within `--within` voxels of B |
| `verdict` | str | `overlapping traces: one sheet over this share of A; count it once in a benchmark` when `same_sheet_share` is at least 0.1, else `separate surfaces` |
| `labels.points_both_labelled`, `labels.area_cm2` | int, float | Points of A within `--within`, supervised on both traces, and their area |
| `labels.dice` | float (3 decimals) or null | Dice of the two ink labels on those points; null under 50 points |
| `labels.note` | str | `too few points labelled on both traces`, only when `dice` is null |
| `labels.null_dice_mean`, `labels.null_dice_p99` | float | Mean and 99th percentile of Dice over the displaced draws |
| `labels.null_draws` | int | Draws with at least 50 points |

`collate` prints one object:

| Field | Type | Meaning |
| --- | --- | --- |
| `a`, `b` | str | The mesh folders as given |
| `grid_um` | float | Spacing of B's upsampled points in um |
| `top` | float | `--top` |
| `box` | list of 4 int, or null | `--box` |
| `bins[].gap_vox`, `bins[].gap_um` | [float, float], [int, int] | The bin's edges in voxels and in um (rounded) |
| `bins[].points` | int | A's points in the bin (inside the box when given) |
| `bins[].map`, `bins[].control` | object or null | Null when fewer than 30 points have both maps nonzero; `control` only with both control maps |
| `.points` | int | Points with both maps nonzero |
| `.pearson` | float or null | Correlation of the two maps at matched points; null when either is constant |
| `.reappear`, `.reappear_chance` | float, float | Share of A's top-fraction points whose match is in B's top fraction, and the chance level (`--top`) |
| `.null_pearson_mean`, `.null_pearson_max` | float | Mean and largest correlation over the displaced draws |
| `.null_reappear_mean`, `.null_reappear_max` | float | The same for `reappear` |

| Exit code | Meaning |
| --- | --- |
| `0` | Measured. A null `labels.dice` or a null bin is still exit 0 |
| `1` | An error the command does not catch, with a Python traceback, such as a missing `.npy` file (`FileNotFoundError`) or tifffile not installed |
| `2` | Bad input, with the message on stderr (see Failure modes), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as no `--voxel-um` | Check the command against Commands and options |
| `cannot read the tifxyz mesh in PATH: ...` | No `x.tif`, `y.tif` or `z.tif` there, an unreadable TIFF, or grids of different shapes (`all input arrays must have the same shape`) | Point at the `.tifxyz` folder itself |
| `PATH: x, y and z must be 2D grids of one shape` | The TIFFs hold more than one page | Use a tifxyz folder whose three TIFFs are single 2D images |
| `PATH: fewer than 4 valid mesh points` | Every point is a hole (-1, NaN, or all zero) | Check the folder; it may be a placeholder mesh |
| `scipy is required for kit overlap and kit collate (it is in villa's environment)` | scipy is not installed | `python -m pip install scipy` |
| `numpy is required. Run inside villa's environment: uv run --project "$VILLA/vesuvius" --extra models python -m kit verify ...` | numpy is not installed | `python -m pip install numpy tifffile scipy` |
| `tifffile is required (it is in villa's environment)` | tifffile is missing when a `.tif` map is read | Install tifffile, and imagecodecs for compressed TIFFs |
| `ModuleNotFoundError: No module named 'tifffile'` and a traceback, exit code 1 | tifffile is missing when a mesh is read | Install tifffile |
| `zarr is required (it is in villa's environment)` | zarr is missing and labels were given | Install zarr |
| `cannot open DIR/inklabels.zarr as zarr: ...` | The labels folder has no `inklabels.zarr` or `supervision.zarr`, or they are not zarr stores | Point `--labels-a` and `--labels-b` at the folders that hold both stores |
| `DIR/inklabels.zarr: no level '2'; levels: [...]` | The store has other level keys | Pick a level from the list with `--level` |
| `cannot read MAP.tif: ...` | An unreadable TIFF map, or a compressed one without imagecodecs | Install imagecodecs, or save the map as `.npy` |
| `MAP.tif: expected a 2D map, got shape (...)` | A layer stack or an RGB image | Pass one 2D map per trace |
| `FileNotFoundError: ...` and a traceback, exit code 1 | A `.npy` map path that does not exist | Fix the path |
| `the box holds no point of trace A` | `--box` lies outside the part of map A that trace A covers | Give the window in map A's pixels, rows first |
| Every `collate` bin shows `(0 pts)`, exit code 0 | The two traces are the same mesh: every gap is exactly 0, and the first bin starts above 0 | Compare two different traces |
| A bin with no `map r` in the text, or `"map": null` | Under 30 points in that bin with both maps nonzero | Read the bins that have points, or widen `--gaps` |
| `labels: too few points labelled on both traces` | Under 50 points supervised on both traces within `--within` | The traces' labelled areas do not overlap; there is no label check to make |
| `label agreement needs labels for both segments: give --labels-a and --labels-b, or neither`, exit code 2 | `kit overlap` with only one of `--labels-a`, `--labels-b` | Give both, or neither |
| `the control needs a map for both segments: give --control-a and --control-b, or neither`, exit code 2 | `kit collate` with only one of `--control-a`, `--control-b` | Give both, or neither |

## How it works

1. Read `x.tif`, `y.tif` and `z.tif` into an (H, W, 3) grid. A point is valid when it is finite, no coordinate is below 0, and not all are 0.
2. Make the grid 4 times denser (`UPSAMPLE = 4`) by linear interpolation of each coordinate (`scipy.ndimage.zoom`, order 1), and erode the valid mask by 4 steps to drop points interpolated with holes. One point then stands for `1 / scale / 4` surface pixels, 5 at the usual scale 0.05, so about 47 um at 9.366 um.
3. For every point of A, find the nearest point of B in 3D with a KD-tree (`match`), and the reverse. The gap is that distance in voxels.
4. `overlap`: the median gap, the shares within 2, 5, 12, 25 and 50 voxels, and the share within `--within` (`same_sheet_share`); the verdict is fixed at a share of 0.1. Areas are point counts times the squared point spacing, taking a surface pixel as one voxel.
5. Labels: sample ink and supervision at each point by proportional grid position (`sample_grid`). Keep A's points within `--within` that are supervised on both traces; with at least 50, Dice of A's ink against the ink at B's matched points. Null: per draw, one step of 1 to 3 mm in a random direction (`DISPLACE_MM`) moves every matched B point in B's grid; points that leave the grid or land on a hole or outside B's supervision drop out; draws with at least 50 points count.
6. `collate`: sample both maps at each trace's points, drop points where either map is 0, and bin A's points by gap. Per bin with at least 30 points: Pearson correlation, and `reappear` with each map's top fraction taken over all its nonzero points on the trace. The same displaced steps give the nulls; the control pair goes through the same steps with the same random stream.

The displaced-match null follows the log's scripts (`scripts/experiments/2026-10-07-cloud/baseline/`), and collation follows decipherment practice ([log](../logs/2026-10-07-overlap-and-baseline.md), section 6); no published method is reimplemented.

## Cost and time

Measured 2026-10-16 in a 4-core Xeon cloud container (2.8 GHz, shared with other jobs), from the wall clock and the peak resident memory of the process:

| Run | Time | Peak memory |
| --- | ---: | ---: |
| `overlap` PHerc0841 w00 against ag896 (211 x 238 and 232 x 236 point grids), with labels, 200 draws | 38 s | 254 MB |
| `overlap` synthetic 211 x 238 point grids, no labels | 9 s | 182 MB |
| `overlap` the same, with 4,220 x 4,760 labels, 200 draws | 32 s | 284 MB |
| `collate` the same, 4,220 x 4,760 uint8 maps and a control, 50 draws | 37 s | 509 MB |
| Either command on 30 x 40 point grids | about 2 s | |

Most of the time goes to the displaced draws. It runs on any machine; nothing here needs Modal or a GPU. The PHerc0841 inputs of the Quick start are about 2 MB to download.

## For agents

- **Command:** `python -m kit overlap MESH_A MESH_B --voxel-um 9.366 --labels-a LABELS_A --labels-b LABELS_B --json`, and `python -m kit collate MESH_A MESH_B MAP_A MAP_B --voxel-um 9.366 --control-a CONTROL_A --control-b CONTROL_B --json`.
- **Parse:** for `overlap`, `same_sheet_share`, `a_to_b.median_gap_vox` and `a_to_b.share_within`, and `labels.dice` against `labels.null_dice_p99`. For `collate`, per entry of `bins`: `map.pearson` against `map.null_pearson_max` and `control.pearson`, and `map.reappear` against `map.reappear_chance`, `map.null_reappear_max` and `control.reappear`.
- **Rerun:** Safe; it only reads its inputs and prints. The same `--seed` gives the same nulls.
- **Success:** Exit code 0, and for labels a non-null `labels.dice`.
- **Not a pass:** a label Dice or a map agreement without its displaced null; `collate` without both control maps; a bin whose `map` is null; reading `same_sheet_share` under 0.1 as proof of two sheets (0.1 is a fixed cut, not a test); taking a gap bin as a normal offset; agreement of maps the model trained on (the team's PHerc0841 maps are probably in-sample).
- **Go-ahead:** Nothing for running it. Collating target-scroll meshes needs a preregistered rule first, and its outputs stay private.
- **Never:** Call two agreeing ink maps a reading or say letters were found; use either command's result to say which trace is right; publish collate results on target-scroll meshes.

## Tests

```bash
python -m unittest tests.test_overlap -v
```

Four tests, about 3 s: `overlap` finds two flat synthetic traces 3 voxels apart to be one sheet and two 200 voxels apart to be separate; `collate` finds high correlation and reappearance for one map copied to both traces and low correlation for a smooth-noise control. Another refuses only one of the two label folders or control maps. The last test in the file checks `kit auc`'s block bootstrap. They skip without numpy, scipy and tifffile. They do not cover the labels path (Dice and its null), `--box`, the command line, the other error messages, holes, or real data; this page's real PHerc0841 run covers the labels path once.

## History

- 2026-10-17: only one of `--labels-a`, `--labels-b` (or of `--control-a`, `--control-b`) is refused with a message; before, the label check or the control was skipped without a word (`9c2fdb7`).
- 2026-10-09: the module text says the team's PHerc0841 maps used for collation are probably in-sample there (`3ba683f`, [Hecate log](../logs/2026-10-09-pherc0841-hecate.md)).
- 2026-10-07: first version of `kit overlap` and `kit collate`, with tests, after the log's scripts (`25070df`, [overlap and baseline log](../logs/2026-10-07-overlap-and-baseline.md)).

## Related

- [The overlap and baseline log](../logs/2026-10-07-overlap-and-baseline.md): the PHerc0841 measurements these commands came from (sections 1, 4 and 6), and README findings 5, 7 and 9 in [`README.md`](../../README.md#novel-findings).
- [The follow-up tests log](../logs/2026-10-07-followup-tests.md): why nearest-point gaps on a sampled grid are not normal offsets.
- [The Hecate log](../logs/2026-10-09-pherc0841-hecate.md): why the team's PHerc0841 maps are probably in-sample.
- [`auc`](auc.md): scoring a map against labels, with its own reverse-depth control.
- [`verify`](verify.md): two maps of the same surface on the same grid.
- [`surfacefix`](surfacefix.md): continuous surface correspondence and bounded corrections.
- [`stackcheck`](stackcheck.md): consecutive windings against the umbilicus.
- [`fetch`](fetch.md): downloads the meshes and labels of the Quick start.
- [`experiment-records`](experiment-records.md): the saved scripts in `scripts/experiments/`, including the log's `segment_overlap.py` and `collation.py`.
- [`GLOSSARY.md`](../../GLOSSARY.md): Dice score.
