# surfacefix: suggest bounded normal shifts of a surface from two traces' ink maps

`python -m kit surfacefix` writes copies of a traced surface shifted along its normal, then, from one ink model's maps of those copies and of a second trace of the same sheet, flags regions where the traces disagree and copies only control-passing shifts into a new surface.

| Field | Value |
| --- | --- |
| Id | `surfacefix` |
| Status | Experimental |
| Kind | kit command, kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit surfacefix prepare`, `python -m kit surfacefix apply`, `from kit import surfacefix` |
| Code | `kit/surfacefix.py`, `kit/_surface_geometry.py`, `kit/cli.py` (`cmd_surfacefix`), `kit/verify.py` (`load_map`, `_numpy`, `VerifyError`), `kit/hpscore.py` (`high_pass`, `_r`) |
| Tests | `tests/test_surface_geometry.py`, `tests/test_surfacefix.py` |
| Needs | Python 3.10 or newer, numpy, scipy (`cKDTree`, `map_coordinates`, `gaussian_filter`), tifffile (imagecodecs for compressed TIFF maps). The ink maps come from outside: villa's `vc_render_tifxyz` to render each mesh and an ink model run three ways on each render |
| Runs on | Any CPU. `prepare` on a 32 x 32 vertex mesh took 0.6 s; `apply` on that mesh with 320 x 320 maps took 2.3 s of CPU (3.5 to 6.8 s wall on a busy machine), and on a 64 x 64 mesh with 640 x 640 maps 6.9 s of CPU (measured 2026-10-16, 4-core Xeon cloud container, synthetic data). The real 32 x 32 PHerc0841 crop took a median 2.28 s on one core ([production scaling log](../logs/2026-10-07-production-scaling.md)) |
| Network | None |
| Writes | `prepare`: a new folder OUT with `manifest.json` and one `offset-NNN.tifxyz/` per offset. `apply`: a new folder OUT with `corrected.tifxyz/` and `report.json`. Both refuse an OUT that exists or overlaps an input; inputs are never changed |
| Go-ahead | Not needed to run it. The renders and model runs it needs happen outside it; GPU inference goes to Modal (the Modal rule, hard rule 11) |
| Released | Public `main` since 2026-10-07 ([PR #17](https://github.com/ChaseHendrick/Scrolls/pull/17)) |
| Guide | [surfacefix.md](../surfacefix.md) (workflow, acceptance checks, validation scope) |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

A traced surface (a mesh, stored in villa's tifxyz form: three TIFF grids giving the x, y and z position of each native vertex) can sit a little above or below the papyrus sheet it follows. An ink model's map of that surface then sees the wrong layers. `surfacefix` tries small, bounded shifts along the surface normal and keeps one only where a second, independent trace of the same sheet (the **reference trace**) says the shifted surface agrees with it better, and every control says that agreement is not an artifact.

It works in two steps. `prepare` writes shifted copies of the source mesh, one per offset in voxels, each checked to be a pure normal shift within `--max-shift-um` that keeps holes, topology and scale and does not fold the grid, plus a `manifest.json` to fill in. Between the two steps you render every mesh with villa and run one ink model on each render three ways: forward (the depth order as stored), reverse (layers in reverse order) and shuffle (layers in a random order). `apply` then matches each source vertex to a point on the reference trace by geometry alone, before it reads any map, and compares high-pass-filtered map values region by region. A region gets a shift only when the best candidate, chosen on the even native rows, also passes on the held-back odd rows, beats the baseline by a margin on both, and beats every control: the reverse and shuffle maps in all pairings, and the reference map displaced 1 to 3 mm. Everything else is left unchanged and flagged.

It does no rendering and no inference, and it never changes the source mesh. A shift it accepts is a geometry suggestion for one region, chosen from model output; it is not evidence of ink, not proof that the surface now follows the ink layer, and not a reading. Accepted shifts change the input context of neighbouring patches, so the merged copy must be rendered again and the reader run again before anyone claims an improvement (the tool says so in every report's `notice`). On real papyrus it has so far accepted no correction (see Checks and controls).

Status is Experimental: its thresholds are defaults, not calibrated operating points, and no real correction has passed its own checks yet ([guide](../surfacefix.md#validation-scope)). villa already has surface snapping and optimization in Lasagna; this is a small selection and checking layer over existing pipeline outputs, not a replacement ([community needs log](../logs/2026-10-07-community-needs.md)).

### Terms

- **Native vertex, native grid**: a point of the tifxyz grid, before rendering. Public meshes space them about 187 um apart ([follow-up log](../logs/2026-10-07-followup-tests.md)).
- **Schema 2** (`certified_bilinear_reference_v1`): the current matching. Each source vertex is matched to the nearest point of the reference's bilinear surface, with a certified distance bracket. **Schema 1**: the original nearest-native-vertex matching, kept only to replay old reports.
- **Region**: a square of `--region-points` x `--region-points` native vertices, scored on its own.

## When to use it

- Testing, on public labelled data, whether bounded normal shifts chosen by agreement between two traces of one sheet would move a surface toward a better render.
- Flagging regions of a trace where two traces' ink maps disagree beyond their controls, as a list of places to look at.
- A preregistered experiment with frozen thresholds (the preregistration rule, hard rule 3), where "no correction" is an acceptable and meaningful result.

Do not use it:

- To fix a surface for real use: use villa's snapping and optimization (Lasagna) or VC3D. This tool's merged copy is a suggestion that needs a rerender and a recheck.
- To measure ink detection against labels: use [`auc`](auc.md) and [`hpscore`](hpscore.md) on the rerendered surface.
- To measure how far apart two traces are: use [`overlap`](overlap.md); to check a mesh's own geometry and canvas, use [`meshaudit`](meshaudit.md).
- With maps of only part of a surface, maps of a cropped canvas, or maps from different models or strides: it refuses them.
- On a target scroll with thresholds chosen after seeing its maps: that breaks the preregistration, and any target result stays private (the no-findings rule, hard rule 1).

## Quick start

```bash
# 1. Shifted copies of the source mesh, 1 voxel each way along the normal.
python -m kit surfacefix prepare SOURCE.tifxyz work/surfacefix-candidates --voxel-um 9.366 --offsets -1 1

# 2. Outside this tool: render SOURCE, REFERENCE and every offset-NNN.tifxyz with villa (scale 1, group 0,
#    linear position interpolation, no rotation or affine, full native canvas), run one ink model on each
#    render forward, reversed and depth-shuffled at one stride, and fill work/surfacefix-candidates/manifest.json.

# 3. Select, check and apply shifts into a new copy.
python -m kit surfacefix apply work/surfacefix-candidates/manifest.json work/surfacefix-output
```

- `SOURCE.tifxyz`: the trace to correct, a tifxyz folder with `x.tif`, `y.tif`, `z.tif` and `meta.json`.
- `REFERENCE`: a separate trace of the same sheet, in the same CT coordinates.
- `9.366`: the CT voxel size in micrometres, which is also the map pixel size at render scale 1.

Filling the manifest means setting `model` and `stride`, a `path` with the same `model` and `stride` for every map, and a `reference` record. Paths are relative to the manifest's folder (absolute paths also work):

```json
"model": "d9v2@sha256:...", "stride": 42,
"reference": {"mesh": "../REFERENCE.tifxyz",
              "maps": {"forward": {"path": "maps/reference-forward.tif", "model": "d9v2@sha256:...", "stride": 42},
                       "reverse": {"path": "maps/reference-reverse.tif", "model": "d9v2@sha256:...", "stride": 42},
                       "shuffle": {"path": "maps/reference-shuffle.tif", "model": "d9v2@sha256:...", "stride": 42}}}
```

On a synthetic 32 x 32 vertex plane with one hole, a reference trace 1 voxel below it, and 320 x 320 synthetic maps in which the +1 candidate and the reference share one random pattern (the fixture of `tests/test_surfacefix.py`, with `--voxel-um 10`), it printed:

```
candidate surfaces prepared in /tmp/claude-docs-public-surfacefix/work/candidates; render and score them with the existing reader, then fill manifest.json before applying corrections
corrections_require_rerender: corrected surface copy and region report in /tmp/claude-docs-public-surfacefix/work/out; rerender and recheck this copy before using its predictions
```

`report.json` had `accepted_regions` 15, `flagged_regions` 16 (accepted regions count as flagged too) and `correspondence.all_maps_covered_points` 960; the corrected `z.tif` held 912 vertices at z 49 (moved), 111 at z 50 and the hole at -1. With every map of a mesh made identical (a shared artifact), the same run printed `no_corrections: ...` and exited 1, with the reasons of the 15 scored regions ending in `held_back: controls agree or are inadequate` (the winner's r was 1.0 and so was its largest control r).

It worked when `prepare` exits 0 with the folders above, and `apply` exits 0 or 1 with `report.json` written. Exit 1 with a `no_corrections` line is a normal abstention, not a crash.

## Checks and controls

The checks are built in; none can be switched off. A region's shift is accepted only when all of these hold on both the selection rows and the held-back rows:

- **Agreement**: Pearson r of the source's forward high-pass values with the reference's at least `--min-corr` (0.5).
- **Gain**: r at least `--min-gain` (0.1) above the baseline mesh's r on the same points.
- **Depth-order controls**: r at least `--control-margin` (0.1) above the largest absolute r among the six control pairings: source reverse with reference reverse, source reverse with reference forward, source forward with reference reverse, and the same three for shuffle. A shared artifact, such as a crack seen the same way in every depth order, makes these agree and refuses the shift.
- **Spatial controls**: the reference forward map displaced 1, 2 and 3 mm along each native axis, both ways, kept only where the displaced point is really 1 to 3 mm away and covered. At least 2 must be usable, and they count in the same maximum.
- **Held-back rows**: the winner is chosen on even native rows only, then checked once on odd rows; no runner-up is tried when it fails.
- **Geometry**: every candidate must be the declared normal offset (tangential motion at most the rounding tolerance), keep holes and scale, stay within `max_shift_um`, and not fold the grid; the merged mesh is checked again and reverted whole if it folds; neighbouring vertices may differ by at most `--max-step-vox`.

What a pass and a fail look like, with real numbers:

- **Real PHerc0841, no labels in the crop** (schema 1 matching, before schema 2 existed; w00 and ag896 traces, `d9v2` reader, stride 42, 12 maps): 0 regions accepted, 16 flagged, 4 evaluable; 432 of 962 native points covered. All eight full searches with deliberately misregistered reference maps (shifted 150 and 300 px each way on each axis) also accepted 0 ([log](../logs/2026-10-07-real-surfacefix-validation.md), `surfacefix_checks` in [`results.json`](../results.json)).
- **Real PHerc0841, supervised crop** (schema 2; a new w00 crop chosen from supervision and geometry before any map): 0 accepted, 16 flagged, 4 evaluable, 444 covered points; a sideways 0.5 voxel edit with recomputed hashes was refused; eight displaced-reference nulls accepted 0. Labels were read only afterwards: the baseline's forward AUC was 0.9211 (reverse 0.5951, shuffle 0.6439), and the +1 voxel candidate's 0.9300, a gain of 0.00889 with interval [-0.00461, 0.02239] that includes zero, so the refusal stood ([follow-up log](../logs/2026-10-07-followup-tests.md), `followup_checks` kinds `supervised_surfacefix_rejection` and `supervised_surfacefix_label_audit` in `results.json`).
- **Synthetic**: `tests/test_surfacefix.py` recovers a known 1 voxel shift, and refuses when the controls share the signal, when a control has no variation, when the held-back rows disagree, and when neighbouring offsets jump.

These real runs are dependent checks on one patch of one sheet; zero acceptances does not give a false-positive rate. Before any claim, rerender the merged copy and score it with [`auc`](auc.md) (with the reverse-depth control) and [`hpscore`](hpscore.md) where labels exist.

Claim label: Null for real-papyrus correction (no shift has been accepted, and no improvement is established); the correlations themselves are Model output, agreement between one model's maps of two traces.

## Commands and options

### `python -m kit surfacefix prepare`

```
usage: python -m kit surfacefix prepare [-h] --voxel-um VOXEL_UM
                                        [--offsets OFFSETS [OFFSETS ...]]
                                        [--max-shift-um MAX_SHIFT_UM] [--json]
                                        mesh out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `mesh` | required | The source tifxyz folder. It is read and hashed, never changed |
| `out` | required | A new output folder, such as `work/surfacefix-candidates`. It must not exist, must not be the source or inside it, and must not contain it |
| `--voxel-um VOXEL_UM` | required | CT voxel size in micrometres (9.366 for the PHerc0841 scan used in the real runs). Must be positive and finite. Converts offsets to micrometres for the bound |
| `--offsets OFFSETS ...` | `-1 1` | Candidate shifts in voxels along the unit normal, one `offset-NNN.tifxyz` each, numbered in the order given. Each must be finite, nonzero, unique, and at most `--max-shift-um` once multiplied by `--voxel-um`. Positive is along cross(row tangent, column tangent) of the native grid; check which side that is for your mesh |
| `--max-shift-um MAX_SHIFT_UM` | `50.0` | Physical bound in micrometres on any vertex's shift, and on the reference matching distance in `apply`. Must be positive and finite |
| `--json` | off | Print the manifest it wrote as JSON instead of the one-line message |

### `python -m kit surfacefix apply`

```
usage: python -m kit surfacefix apply [-h] [--region-points REGION_POINTS]
                                      [--min-points MIN_POINTS]
                                      [--min-corr MIN_CORR]
                                      [--min-gain MIN_GAIN]
                                      [--control-margin CONTROL_MARGIN]
                                      [--max-step-vox MAX_STEP_VOX] [--json]
                                      manifest out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `manifest` | required | The `manifest.json` from `prepare`, filled with a model, a stride, a reference record and every map (see Inputs) |
| `out` | required | A new output folder, such as `work/surfacefix-output`. It must not exist or overlap the manifest, any mesh folder or any map |
| `--region-points REGION_POINTS` | `8` | Side of a scoring region in native vertices. An integer of at least 2 |
| `--min-points MIN_POINTS` | `24` | Fewest covered points in each of the selection and held-back subsets for a region to be scored, and in each correlation. An integer of at least 3 |
| `--min-corr MIN_CORR` | `0.5` | Lowest acceptable Pearson r between source and reference forward maps. From 0 to 1 |
| `--min-gain MIN_GAIN` | `0.1` | How far the winner's r must exceed the baseline's r on each subset. From 0 to 2 |
| `--control-margin CONTROL_MARGIN` | `0.1` | How far r must exceed the largest absolute control r. From 0 to 2 |
| `--max-step-vox MAX_STEP_VOX` | `1.0` | Largest allowed difference in chosen offset between adjacent native vertices; both regions of a larger jump are reverted. Positive |
| `--json` | off | Print the report as JSON instead of the one-line status |

These thresholds are experimental defaults. Freeze them on held-out labelled data before a target run; changing them after seeing target maps invalidates that run's preregistration ([guide](../surfacefix.md#inputs-and-workflow)).

## Python API

```python
from kit import surfacefix
manifest = surfacefix.prepare("SOURCE.tifxyz", "work/surfacefix-candidates", 9.366, [-1, 1])
# ... render, infer, fill the manifest ...
report = surfacefix.correct("work/surfacefix-candidates/manifest.json", "work/surfacefix-output")
print(report["status"], report["accepted_regions"])
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `prepare(mesh, out_dir, voxel_um, offsets, max_shift_um=50)` | The manifest dict, also written to `OUT/manifest.json` | `VerifyError` for every refusal under Failure modes; `ImportError` without tifffile; `OSError` if writing fails | What `prepare` runs. `offsets` is a list of numbers in voxels |
| `correct(manifest_path, out_dir, region_points=8, min_points=24, min_corr=0.5, min_gain=0.1, control_margin=0.1, max_step_vox=1)` | The report dict under Outputs, also written to `OUT/report.json` | `VerifyError` for every refusal; `ImportError` without scipy or tifffile; `OSError` if writing fails | What `apply` runs. Writes nothing when it refuses |
| `quad_mask(mesh)` | Boolean array of shape (rows - 1, cols - 1) | Nothing of its own | `kit._surface_geometry`. True for a quad whose four corners are valid and whose four corner normals point the same way (dot product with their mean above 1e-12): no holes, folds or degenerate quads. `mesh` is a dict with `xyz` (rows, cols, 3) and `valid` (rows, cols) |
| `bilinear(corners, uv)` | Array of positions, shape (..., 3) | Nothing of its own | `kit._surface_geometry`. Corners in the order (r, c), (r + 1, c), (r, c + 1), (r + 1, c + 1); `uv` is (u along rows, v along columns) in 0..1 |
| `sample_geometry(mesh, uv)` | `(positions, valid)`: positions (..., 3) and a boolean array | Nothing of its own | `kit._surface_geometry`. `uv` holds fractional native (row, column) positions; `valid` is False outside the grid, for non-finite input, and on quads that `quad_mask` rejects |
| `closest_quad(point, corners, tolerance, budget=4096)` | `{"lower", "upper", "uv", "converged"}` | Nothing of its own | `kit._surface_geometry`. Branch and bound over subdivided boxes: `lower` and `upper` bracket the distance from `point` to the bilinear quad, `uv` is the best point found. `converged` is False when `budget` boxes ran out before `upper - lower <= tolerance`; that is never treated as a match |
| `project(source, reference, max_distance, tolerance)` | Dict of arrays shaped like `source["valid"]`: `uv` (fractional reference row, column), `distance` (upper bound, voxels, inf where none), `valid`, `ambiguous`, `unresolved` | `ImportError` without scipy | `kit._surface_geometry`. The schema 2 correspondence; `max_distance` and `tolerance` in voxels. `valid` means one certified match within `max_distance` with no competitor |

## Inputs

**Source and candidate meshes** (tifxyz folders):

| File | Format | Notes |
| --- | --- | --- |
| `x.tif`, `y.tif`, `z.tif` | 2D floating-point TIFFs of one shape, at least 2 x 2 | CT coordinates in voxels, one value per native vertex. A hole is (-1, -1, -1) or (0, 0, 0); any other negative value is refused. At least 4 valid vertices. The stored dtype (float32 in villa) is kept when copies are written |
| `meta.json` | JSON with `"scale": [SX, SY]` | Native vertices per rendered pixel along x (columns) and y (rows), both positive. Other keys and any other files in the folder are copied unchanged into every copy |

The expected map shape is `round(rows / SY)` x `round(cols / SX)`: the full native canvas of `vc_render_tifxyz` at scale 1 and group 0. Coordinates must be fine enough for subvoxel checks: the rounding tolerance, `max(0.001, 2 * sqrt(3) * ulp)` voxels at the largest coordinate, must be at most 0.1 voxel (for float32 that fails from coordinates of 262,144 voxels up).

**Manifest** (`manifest.json`, written by `prepare`; `null` fields are yours to fill):

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | int | `2` (written by `prepare`) or `1` (historical replay only) |
| `matching_mode` | str | Must be `certified_bilinear_reference_v1` for schema 2 |
| `render_geometry` | object | Must equal `{"position_interpolation": "linear", "scale": 1, "group": 0, "rotation_degrees": 0, "affine": false, "full_native_canvas": true}` for schema 2. It is a declaration: it must match the renderer command you actually ran |
| `voxel_um`, `max_shift_um` | number | From `prepare`; positive and finite |
| `model` | str | Fill in: one model identifier (such as a checkpoint name and its SHA-256), the same for every map |
| `stride` | int | Fill in: the inference stride, a positive JSON integer (not `42.0`), the same for every map; reverse and shuffle must use the forward stride |
| `baseline` | object | `mesh` (path), `hashes` (file name to SHA-256, required and checked) and `maps` |
| `reference` | object | Fill in: `mesh` (a separate trace, not a copy of the baseline) and `maps`; `hashes` optional, checked when given |
| `candidates` | list | One object per offset: `offset_vox`, `mesh`, `hashes` (required and checked) and `maps` |
| `.maps.forward`, `.maps.reverse`, `.maps.shuffle` | object | Each `{"path": ..., "model": ..., "stride": ...}`; `path` relative to the manifest's folder or absolute |
| `notice` | str | The rerender warning |

**Ink maps**: one 2D map per mesh and depth order, `.npy` (read with `allow_pickle=False`) or a TIFF (read with tifffile, singleton axes squeezed). Any numeric dtype; it is cast to float. It must have exactly the mesh's map shape, be finite and nonnegative, and cover the full surface, not a crop. 0 means "no prediction": a vertex counts as covered only when every map pixel it is interpolated from is above 0, so a valid score of exactly 0 is treated as uncovered. Rows and columns follow the native grid: vertex (r, c) sits at map position (r / SY - 0.5, c / SX - 0.5).

## Outputs

**`prepare`** prints `candidate surfaces prepared in OUT; render and score them with the existing reader, then fill manifest.json before applying corrections`, or with `--json` the manifest. It writes `OUT/manifest.json` and `OUT/offset-000.tifxyz/`, `OUT/offset-001.tifxyz/` and so on: copies of the source folder (every file), with `x.tif`, `y.tif` and `z.tif` rewritten in their original dtype.

**`apply`** prints `STATUS: corrected surface copy and region report in OUT; rerender and recheck this copy before using its predictions`, or with `--json` the report. It writes `OUT/corrected.tifxyz/` (a copy of the baseline folder with accepted shifts applied; equal to the baseline when none are) and `OUT/report.json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | int | The manifest's schema (2, or 1 for a replay) |
| `experimental` | bool | Always true |
| `notice` | str | The rerender warning |
| `model`, `stride`, `voxel_um` | str, int, float | From the manifest |
| `thresholds` | object | `region_points`, `min_points`, `min_corr`, `min_gain`, `control_margin`, `max_step_vox`, `max_shift_um` (um), `high_pass_um` (48.0), `spatial_displacement_um` ([1000, 3000]), `map_sampling` (str), `normal_tolerance_vox` (voxels) |
| `input_hashes` | object | Per mesh folder path: `mesh` (file name to SHA-256) and `maps` (kind to `path` and `sha256`) |
| `manifest_sha256` | str | SHA-256 of the manifest as read |
| `regions` | list | One object per region with valid vertices (below) |
| `matching_mode`, `render_geometry` | str, object | Schema 2 only, as declared |
| `correspondence` | object | Schema 2 only: `geometry_frozen_before_maps` (true), `method`, `uniqueness`, `reference_sampling` (str), `distance_tolerance_vox` (voxels), `geometrically_matched_points`, `ambiguous_points`, `unresolved_points`, `all_maps_covered_points` (counts of native vertices) |
| `accepted_regions` | int | Regions whose shift was applied |
| `flagged_regions` | int | Regions flagged as uncertain; accepted regions are counted here too |
| `status` | str | `corrections_require_rerender` (some accepted), `no_corrections` (some flagged, none accepted) or `unchanged` (nothing flagged) |
| `output_mesh` | str | `corrected.tifxyz` |

Each region:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | int | Region number, row-major over the native grid |
| `box` | list of 4 int | Native rows r0 to r1 and columns c0 to c1, ends excluded |
| `points`, `selection_points`, `held_back_points` | int | Valid vertices, and covered vertices on even and on odd native rows |
| `accepted`, `offset_vox` | bool, number | Whether a shift was applied, and which (0 when none) |
| `flagged` | bool | Uncertain: anything but a baseline that passes |
| `reasons` | list of str | Why, in order (below) |
| `baseline.selection`, `baseline.held_back` | object | The baseline's score on each subset, when the region had enough points |
| `winner.offset_vox`, `winner.selection`, `winner.held_back` | number, object | The best candidate on the selection rows and its scores, when one was tried |

A score is `{"r", "control_max_abs", "spatial_controls", "reason"}`: Pearson r (or null with fewer than `min_points` points or no variation), the largest absolute control r (null when controls were inadequate), the number of usable spatial controls, and null or `inadequate control points or variation` or `inadequate spatially displaced controls`.

| Reason | Meaning |
| --- | --- |
| `baseline passes both subsets and controls; no correction needed` | Not flagged; nothing to do |
| `inadequate points or map/reference coverage` | Fewer than `min_points` covered vertices in a subset |
| `inadequate baseline negative controls` | A baseline control could not be computed |
| `weak baseline agreement` | Baseline r below `min_corr` (or null) on a subset; candidates are tried |
| `baseline fails negative-control margin` | Baseline r high enough but too close to a control; candidates are tried |
| `no candidate with usable selection variation` | No candidate gave an r on the selection rows |
| `selection: insufficient correlation or gain`, `held_back: insufficient correlation or gain` | The winner missed `min_corr` or `min_gain` on that subset |
| `selection: controls agree or are inadequate`, `held_back: controls agree or are inadequate` | The winner missed `control_margin`, or had no usable controls |
| `neighboring offset discontinuity exceeds max_step_vox` | Accepted, then reverted by the jump check |
| `merged geometry folds or degenerates the native grid` | Accepted, then reverted because the merged mesh folded |

| Exit code | Meaning |
| --- | --- |
| `0` | `prepare` wrote its candidates; or `apply` finished with `corrections_require_rerender` or `unchanged` |
| `1` | `apply` finished with `no_corrections`: regions were flagged and none accepted, and both output files were written. Also any error the command does not catch, with a Python traceback (such as scipy missing); tell them apart by the `no_corrections:` line or `report.json` |
| `2` | A refusal, `surfacefix: MESSAGE` on stderr (see Failure modes), with no output folder created; or a usage error from the argument parser |

## Failure modes

Every refusal below is printed as `surfacefix: MESSAGE` with exit code 2, and leaves no output folder.

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as `prepare` without `--voxel-um` | Check the command against Commands and options |
| `numpy is required. Run inside villa's environment: uv run --project "$VILLA/vesuvius" --extra models python -m kit verify ...` | numpy is not installed | `python -m pip install numpy scipy tifffile`, or run inside villa's environment |
| `ModuleNotFoundError: No module named 'scipy'` (or `'tifffile'`) and a traceback, exit code 1 | scipy or tifffile is missing | Install it |
| `tifffile is required (it is in villa's environment)` | tifffile is missing when a TIFF map is read | Install tifffile |
| `cannot read MAP: ...` | An unreadable TIFF map, or a compressed one without imagecodecs | Install imagecodecs, or save the map as `.npy` |
| `MAP: expected a 2D map, got shape (...)` | A TIFF map with more than one non-singleton axis | Pass one 2D map per depth order |
| `NAME must be finite` | `voxel_um`, `max_shift_um` or a threshold is NaN, infinite or not a number | Give a finite number |
| `NAME must be positive` or `NAME must be nonnegative` | A size or bound is 0 or negative, or `--min-corr`, `--min-gain` or `--control-margin` is negative | Use the ranges under Commands and options |
| `correlation thresholds are outside their possible range` | `--min-corr` above 1, or `--min-gain` or `--control-margin` above 2 | Use a value in range |
| `NAME must be an integer of at least N` | `--region-points` below 2 or `--min-points` below 3 (or a non-integer in Python) | Use the defaults 8 and 24, or larger |
| `at least one nonzero candidate offset is required` | An empty offset list (Python API) | Give at least one offset |
| `offsets must be finite numbers` | An offset is NaN, infinite or not a number | Fix `--offsets` |
| `candidate offsets must be nonzero and within max_shift_um` | An offset of 0, or one whose size times `--voxel-um` exceeds `--max-shift-um` (6 voxels at 10 um is 60 um, refused under 50) | Use smaller offsets, or a bound you preregistered |
| `duplicate candidate offsets` | The same offset twice | Remove the duplicate |
| `output already exists: OUT` | OUT is already there | Pick a new folder; the tool never overwrites |
| `input-output overlap: INPUT and OUT` | OUT is an input, inside one, or contains one | Put OUT outside every input |
| `missing native tifxyz directory: PATH` | The mesh path is not a folder | Point at the `.tifxyz` folder |
| `invalid tifxyz mesh or required meta.json scale in PATH: ...` | `x.tif`, `y.tif`, `z.tif` or `meta.json` is missing or unreadable, or `meta.json` has no `scale` | Check the folder holds a complete tifxyz mesh |
| `PATH: finite x/y/z 2D grids, at least 2 x 2, are required` | Coordinates are not floating point, not finite, not 2D, or smaller than 2 x 2 | Use a float32 tifxyz mesh |
| `PATH: meta.json scale must have two positive finite values` | `scale` is not two positive numbers | Fix `meta.json` |
| `PATH: malformed holes or fewer than four valid points` | A vertex with some but not all coordinates at -1, or fewer than 4 valid vertices | Fix the mesh's holes |
| `symlink inputs are not supported: PATH` | A file inside a mesh folder is a symbolic link | Copy the real file in |
| `mesh has too few points with usable local normals` | Fewer than 4 vertices have neighbours on both axes and a nonzero normal | Use a larger, connected mesh |
| `coordinate precision is inadequate for subvoxel normal-offset checks` | The rounding tolerance at the largest coordinate exceeds 0.1 voxel | Store coordinates in a wider float type |
| `source mesh has degenerate native-grid triangles` | The source grid already has a zero-area or folded triangle | Repair the source trace first |
| `offset would create negative coordinates or a hole` | A shift would push a vertex below 0 | Use a smaller offset |
| `offset exceeds native coordinate precision` | A shifted coordinate does not fit the stored dtype | Use a smaller offset or a wider dtype |
| `candidate must preserve native topology, holes and scale` | A candidate mesh has another shape, other holes or another `scale` | Use the meshes `prepare` wrote |
| `candidate is not the declared bounded normal offset, or changes holes` | A candidate moved sideways, by another amount than `offset_vox`, past the bound, or moved a hole; checked even when its hashes were recomputed | Use the meshes `prepare` wrote, unedited |
| `candidate folds or degenerates the native grid` | The shift flips or degenerates normals or triangles | Use a smaller offset |
| `cannot read manifest: ...` | The manifest file is missing or not JSON | Check the path |
| `surfacefix manifest schema must be 1 or 2` | `schema` is missing or another value | Use the manifest from `prepare` |
| `schema 2 requires explicit certified bilinear matching_mode` | `matching_mode` was changed or removed | Restore `certified_bilinear_reference_v1` |
| `schema 2 requires declared linear, untransformed full-native-canvas render_geometry` | `render_geometry` differs from the required declaration, such as bicubic interpolation | Render with linear interpolation, scale 1, group 0, no rotation or affine, full canvas, and keep the declaration |
| `manifest needs a model identifier and positive integer inference stride` | `model` or `stride` not filled (the state `prepare` leaves them in) | Fill both |
| `baseline and reference must be mesh records` | `baseline` or `reference` is not an object (`reference` is `null` until you fill it) | Fill the reference record |
| `baseline, separate reference and candidates must be mesh records` | A record is not an object | Fix the manifest |
| `manifest needs filled mesh and map paths` | A `mesh` or map `path` is empty or not a string | Fill every path |
| `missing or changed mesh file hashes: PATH` | A mesh changed after `prepare`, or the baseline or a candidate has no `hashes` | Use unchanged meshes, or prepare again |
| `KIND: maps must share the manifest model and stride` | A map spec is missing, or its `model` or `stride` differs from the manifest's (a stride of `42.0` also fails) | Run every map with one model and one stride, and record them exactly |
| `missing KIND map: PATH` | The map file does not exist | Fix the path |
| `cannot load KIND map: ...` | The `.npy` or TIFF could not be read | Check the file |
| `KIND: expected finite nonnegative full-surface map (H, W)` | Wrong shape (a crop, or another render scale), or NaN, infinite or negative values | Render the full native canvas at scale 1; apply a sigmoid to logits |
| `baseline or reference geometry changed after correspondence was frozen` | A mesh changed while `apply` was running | Do not edit inputs during a run |
| `reference must be a separate trace, not a copy of the baseline mesh` | The reference is the baseline's folder, has its hashes, or has identical coordinates | Use a different trace of the same sheet |
| `manifest needs bounded offset candidates` | `candidates` is missing or empty | Use the manifest from `prepare` |
| `candidate offset_vox must be finite` | An `offset_vox` is missing, NaN or not a number | Use the manifest from `prepare` |
| `candidate offsets must be unique, nonzero and within max_shift_um` | Candidate offsets were edited out of bounds or duplicated | Use the manifest from `prepare` |

## How it works

`prepare`:

1. Read the mesh (`_mesh`): valid vertices are those with all coordinates at least 0 and a positive sum; holes are all -1 or all 0.
2. Normals (`_normals`): central differences along rows and columns, one-sided beside holes and edges; the unit normal is cross(row tangent, column tangent). A vertex without a neighbour on both axes, or with a zero cross product, is unsupported and never moves.
3. For each offset, move supported vertices by offset x normal, cast to the stored dtype, and check the result (`_geometry`): same shape, holes and scale; every shift at most `max_shift_um` plus the rounding tolerance; tangential motion and error along the normal at most the tolerance (`_roundoff`, at least 0.001 voxel); normals still supported and not flipped; no triangle of the native grid flipped or degenerate (`_unfolded`).
4. Only after every offset passes, create OUT, copy the source folder per offset, and write the manifest with SHA-256 hashes of every file.

`apply` (`correct`):

1. Check thresholds, the manifest's schema, matching mode, render declaration, voxel size, bound, model and stride.
2. Schema 2: read only the baseline and reference geometry and run `project` (in `kit/_surface_geometry.py`) before any map is read. For each valid source vertex, find every valid reference quad (`quad_mask`) whose centre lies within `max_shift_um / voxel_um` plus the largest quad radius plus the tolerance (a scipy `cKDTree` ball query), prune by bounding box, and bracket the true distance to each bilinear quad by subdivision (`closest_quad`: triangle distances give a lower bound corrected for the quad's warp, points on the quad an upper bound; budget 4,096 boxes). A quad that does not converge, or whose unique nearest point is not certified by `_unique_minimum` (a sufficient strict-convexity test), makes the vertex unresolved if it could be within the bound. A second quad within numerical reach of the winner at another position, or any quad more than 2 native steps away within the bound (a remote winding), makes it ambiguous. Only a unique certified match at distance at most the bound is valid; the tolerance never enlarges the bound. Schema 1 instead takes the nearest valid reference vertex and accepts it within the bound.
3. Read every map (`_record`): check model, stride, shape, finiteness and sign; high-pass filter it (`high_pass` from `kit/hpscore.py`: the map minus its Gaussian mean over covered pixels, sigma `HIGH_PASS_UM / voxel_um` pixels, with `HIGH_PASS_UM = 48.0`); sample it at every native vertex with bilinear interpolation at (r / SY - 0.5, c / SX - 0.5) (`_sample_native`). For schema 2 the reference is sampled on its dense high-pass canvas at the matched fractional positions (`_sample_projected`), not from its vertex samples.
4. Confirm the geometry did not change since step 2, the reference is a separate trace, and each candidate is the declared normal offset; check OUT.
5. Covered vertices: valid, with a supported normal, matched, and covered in every map of the baseline, every candidate and the reference.
6. Spatial controls: from the median spacing of adjacent reference vertices, shift the matched positions by 1, 2 and 3 mm along each axis, both ways (up to 12), without wrapping, keeping points really 1,000 to 3,000 um away.
7. Per region (`--region-points` square), selection = covered vertices on even native rows, held back = odd rows. Score the baseline on both (`_scores`: Pearson r via `_r`, and the maximum absolute r over the six depth-order pairings and the spatial controls). A passing baseline is left alone; otherwise every candidate is scored on the selection rows, the best r wins, and the winner is scored once on the held-back rows. Accept only if both subsets pass `min_corr`, `min_gain` and `control_margin`; set the offset on the region's covered vertices.
8. Revert both regions of any neighbouring jump above `max_step_vox` (plus 1e-8), repeating until nothing changes.
9. Merge the accepted candidates' coordinates; if the merged grid folds or loses a normal, revert everything.
10. Create OUT, write `corrected.tifxyz` (baseline folder copy, coordinates in their original dtype) and `report.json`.

Constants: `KINDS = ("forward", "reverse", "shuffle")`, `CONTINUOUS_MODE = "certified_bilinear_reference_v1"`, `CONTINUOUS_RENDER` (the render declaration above), `HIGH_PASS_UM = 48.0`, the 1,000 to 3,000 um spatial controls, the 0.1 voxel precision limit, and the 4,096-box budget of `closest_quad`. The map registration (vertex at pixel r / SY - 0.5) follows villa's `vc_render_tifxyz` canvas centring, as checked against its source ([real validation log](../logs/2026-10-07-real-surfacefix-validation.md)).

## Cost and time

Measured 2026-10-16 in a 4-core Xeon cloud container (lscpu reports 2.80 GHz) shared with other jobs, on synthetic data: `prepare` with two offsets on a 32 x 32 mesh, 0.6 s wall; `apply` on that mesh with two candidates and 320 x 320 maps, 2.3 s of CPU and 3.5 to 6.8 s wall over four runs, peak memory about 81 MB; `apply` on a 64 x 64 mesh with 640 x 640 maps, 6.9 s of CPU (26.7 s wall under load).

On real data, the complete schema 2 correction of the 32 x 32 PHerc0841 crop with twelve 640 x 640 `d9v2` maps took a median 2.55 s on one core after the batched child bounds ([production speed log](../logs/2026-10-07-production-speed.md)), then 2.28 s after the batched triangle edges, with median peak memory 85 MB ([production scaling log](../logs/2026-10-07-production-scaling.md)). Time grows with the number of source vertices, since step 2 loops over them in Python; a whole segment has not been measured.

The tool itself needs no GPU and rents nothing. Its inputs do: rendering each mesh and running the ink model three times per mesh is GPU work, which goes to Modal (the Modal rule, hard rule 11), outside this tool.

## For agents

- **Command:** `python -m kit surfacefix prepare SOURCE.tifxyz OUT_CANDIDATES --voxel-um 9.366 --offsets -1 1 --json`, then, after the maps exist and the manifest is filled, `python -m kit surfacefix apply OUT_CANDIDATES/manifest.json OUT_FIX --json`; the report is also in `OUT_FIX/report.json`.
- **Parse:** `status`, `accepted_regions` and `flagged_regions`; per region `accepted`, `offset_vox`, `flagged` and `reasons`; `correspondence.all_maps_covered_points` for how much was evaluable.
- **Rerun:** Each run needs a new OUT and refuses an existing one; inputs are never changed. The same inputs and thresholds give the same report.
- **Success:** `prepare` exit 0. `apply` exit 0 with `corrections_require_rerender` or `unchanged`, or exit 1 with `no_corrections` and `report.json` present (an abstention). Exit 2 is a refusal; exit 1 without `report.json` is a crash.
- **Not a pass:** `corrections_require_rerender` itself: the merged copy is untested until it is rendered again and scored with `auc` (with the reverse control) and `hpscore`; separate candidate renders do not validate the merged one. A run whose thresholds were changed after seeing target maps. Synthetic test recoveries, which test software only.
- **Go-ahead:** Nothing for this tool. Renting GPUs for the renders and maps needs the user's budget decision; publishing anything about a target scroll is never allowed.
- **Never:** Call an accepted shift a better surface, an improvement in reading, or evidence of ink; mix models or strides across maps; edit candidate meshes by hand; overwrite or replace the source mesh with `corrected.tifxyz` without a rerender and recheck; commit meshes, maps or reports of scroll data to git.

## Tests

```bash
python -m unittest tests.test_surface_geometry tests.test_surfacefix -v
```

`tests/test_surface_geometry.py` (15 tests) covers the correspondence: batched and scalar triangle distances across dtypes, child bounds, a half-grid plane match, the physical bound never widened by tolerance, holes and folded quads, a saddle's distance bracket against a dense search, budget exhaustion, shared edges, remote ties, unresolved rivals, a saddle with two nearest points, and a large far-centred quad. `tests/test_surfacefix.py` (24 tests) covers recovery of a known shift with holes, metadata and inputs preserved; shared-artifact and flat controls; a healthy baseline left unchanged; held-back rejection without a runner-up; missing coverage; mixed strides and missing controls; bad maps, offsets, overlap, hashes, tangential edits, jumps, folds, precision, anisotropic scale and map registration; schema 2 against schema 1; geometry frozen before maps; the render declaration; and the command line. They need numpy, scipy and tifffile and skip without them. They use synthetic meshes only, never real papyrus. On 2026-10-16 the 39 tests took 29 s of CPU (116 s wall on the busy shared 4-core container).

## History

- 2026-10-07: triangle edges batched for float32 and float64, 1.10x faster complete correction on the real crop with identical outputs (`047ee06`, [PR #27](https://github.com/ChaseHendrick/Scrolls/pull/27), [production scaling log](../logs/2026-10-07-production-scaling.md)).
- 2026-10-07: four child boxes bounded in one batch, 2.07x faster complete correction with identical reports and outputs (`fda744f`, [PR #24](https://github.com/ChaseHendrick/Scrolls/pull/24), [production speed log](../logs/2026-10-07-production-speed.md)).
- 2026-10-07: schema 2, certified bilinear matching against the reference (`kit/_surface_geometry.py`), dense reference sampling, geometry frozen before maps, and the render declaration; schema 1 kept for replay (`93c42bf`, [follow-up log](../logs/2026-10-07-followup-tests.md)).
- 2026-10-07: the guide records the bounded real PHerc0841 run, which accepted no correction (`f62ad8c`).
- 2026-10-07: first version: `prepare` and `apply`, nearest-native-vertex matching, depth-order and spatial controls, held-back rows, jump and fold checks (`cc880c6`, [PR #17](https://github.com/ChaseHendrick/Scrolls/pull/17)).

## Related

- [surfacefix.md](../surfacefix.md): the guide, with the workflow, the acceptance checks and the validation scope.
- [Real validation log](../logs/2026-10-07-real-surfacefix-validation.md) and [follow-up log](../logs/2026-10-07-followup-tests.md): the real PHerc0841 runs and nulls; `surfacefix_checks` and `followup_checks` in [`results.json`](../results.json).
- [`auc`](auc.md) and [`hpscore`](hpscore.md): score the rerendered merged copy against labels, with controls.
- [`overlap`](overlap.md): agreement and distance between two traces' maps, the study that motivated this tool.
- [`meshaudit`](meshaudit.md): checks of a mesh's transforms, canvas and depth before rendering.
- [`layers`](layers.md): writes the depth-shuffled layers for the shuffle maps.
- [Community needs log](../logs/2026-10-07-community-needs.md): villa's Lasagna snapping, which any real comparison must include.
