# defectbench: a dev bench of meshes with planted defects and known answers

Builds synthetic tifxyz meshes with planted sheet switches, rough tracing, folds and bridges, sized like spiral-fit columns of public PHerc0343, with per-vertex truth, and scores switch alarms and mesh repairs on them.

| Field | Value |
| --- | --- |
| Id | `defectbench` |
| Status | Experimental |
| Kind | kit module |
| Area | Surfaces and tracing |
| Run | `python3 -m kit.defectbench cases`, `make`, `check`, `baseline`, `score`; `from kit import defectbench` |
| Code | `kit/defectbench.py`, `kit/stagereg_ext_defectbench.py` |
| Tests | `tests/test_defectbench.py` |
| Needs | Python 3.9 or newer, numpy, scipy, tifffile; zarr 3 and numcodecs for the mini track's prediction. No scan data, villa, VC3D or GPU. |
| Runs on | CPU anywhere. `make --seeds 3` (78 cases, both tracks) took 1 min 43 s and 168 MB; `check` 1 s; one baseline plus its score about 1 min (measured 2026-11-27, 4-core cloud container) |
| Network | None |
| Writes | `make`: OUT/manifest.json and OUT/TRACK/CASE-sSEED/ (x.tif, y.tif, z.tif, meta.json, truth.npz, defects.json; mini adds pred.zarr and umbilicus.json); `baseline`: DIR/TRACK/CASE-sSEED.npy or DIR/TRACK/CASE-sSEED/ tifxyz; `score --out-file`: one JSON file |
| Go-ahead | Not needed |
| Released | Not yet |
| Checked | 2026-11-27 |

## What it does

Fixes for rough or switched meshes (smoothing, cutting, shifting, re-gridding) and sheet-switch alarms are hard to
develop on real columns: a column a fix was tuned on cannot measure it again, and real columns have no per-vertex
truth. Two spiral-fit columns of public PHerc0343 show the two kinds of defect this bench plants: column A carries
diffuse tracer roughness (creases on 12.1 % of the area, edge spikes on 16.2 %), and column B carries one
sheet-switch band (a connected region of about 1,400 quads near grid columns 260 to 320, rows 10 to 30, and smaller
ones) on top of roughness. Their shares are used only as calibration targets. `kit defectbench` plants the same
kinds of defect, at the same grid size (91 x 405 cells, a 20 voxel step, a 23 voxel pitch), on
[kit planted](planted.md)'s spiral sheets, so every vertex has a known true winding and a known true position.

Thirteen cases, three seeds each, on two tracks: **column** (the calibration columns' size) and **mini** (the same
ratios at half the step on a 31 x 101 grid, small enough to ship a whole binary sheet prediction, `pred.zarr`, and
an `umbilicus.json`, for alarms that read a prediction). The cases: a clean control; three roughness levels
(`rough-light`, `rough-a` matched on column A's crease and spike shares, `rough-a-taubin` matched on column A's
spikes and on what Taubin smoothing did to the real columns); `band-b` (column B's band and two smaller ones on its
roughness); `band-only` (the band on a smooth mesh); `switch-edge`, `skip` (two windings), `merger` (a slide over 6
columns that stays), `fold` (the mesh runs backward over itself on its own sheet), `bridge` (a hole filled by the
flat chord, leaving the curved sheet), `gapbridge` (a strip in the void between two windings) and `hole` (a punched
hole: the rest is correct).

Each valid vertex gets one label from its coordinates and its true position only: wrong (on another winding),
gap (more than 0.35 pitch from every sheet), fold, rough (on its sheet within 0.35 pitch but more than 1 voxel from
its true position) or clean. `score` measures per-vertex switch alarms (recall on wrong and gap vertices, false
alarms on clean and on rough vertices, regions hit) and repaired meshes on the same grid (kept share, good cells
kept, wrong, off and fold cells kept, backward row edges, sheet error percentiles, and the crease, spike and flip
shares after the repair).

It is synthetic: nothing here reads a scan, CT, label, prediction or model output, and a bench number is a
development number for a tool, never a result on a scroll.

## When to use it

Use it:

- to develop and compare mesh-fix recipes (smoothing, cutting, shifting, re-gridding) before a frozen test on fresh
  columns;
- to develop sheet-switch alarms that read the mesh alone or a sheet prediction (the mini track);
- as a cheap regression check: a recipe that loses good area on `rough-a-taubin` or keeps the switch in `band-only`
  is wrong before any real column is spent.

Do not use it:

- to claim a fix works on a scroll: use a frozen preregistered test on fresh columns;
- for winding identity across whole windings or stacks: use [kit planted](planted.md);
- for alarms that read CT or ink: this bench has no CT; render [ScrollSim v2](scrollsim2.md) volumes instead;
- for planted ink.

## Quick start

```bash
python3 -m kit.defectbench cases
python3 -m kit.defectbench make work/defectbench/bench --seeds 3
python3 -m kit.defectbench check work/defectbench/bench
python3 -m kit.defectbench baseline work/defectbench/bench --repair taubin5g --dir work/defectbench/rep-taubin5g
python3 -m kit.defectbench score work/defectbench/bench --repaired work/defectbench/rep-taubin5g --out-file work/defectbench/score.json
```

`make` prints one line per case, such as
`column/band-b-s0  INCORRECT  wrong ... gap ... fold 0 rough ... crease ... spike ...`; `check` prints
`agrees` and exits 0. `score` prints one line per track and case with the means over seeds. To score your own tool,
write one file per case in the layout `baseline` writes: `DIR/column/band-b-s0.npy` (a boolean H x W mask of flagged
vertices) for an alarm, or `DIR/column/band-b-s0/` (a tifxyz on the same grid, cut vertices -1) for a repair.

## Checks and controls

`check` recomputes every case's labels and summary truth from the stored coordinates and the sheet geometry, and
compares them, and every file's sha256, with `defects.json` and `manifest.json`; it fails (exit 3) when a vertex
was moved, a file changed, an INCORRECT case carries no defect or a CORRECT case carries one. The tests move one
vertex by a pitch and require `check` to fail.

Every score has controls that must fail: the `none` and `all` alarms (recall 0, or every clean vertex flagged) and
the `identity` repair (every switch and fold kept); the `oracle` alarm and repair must score perfectly. In the build
below all four controls behaved as required. Calibration against the two PHerc0343 columns (means over 3 seeds,
column track): `rough-a` creases 0.138 and spikes 0.159 (column A: 0.121 and 0.162); `band-b` 0.116 and 0.120
(column B: 0.126 and 0.125); `rough-a-taubin` matches what 5 Taubin passes did to the real columns (p95 move 2.95
voxels, cut 0.49 %; real: 2.0 to 3.5 voxels and 0.32 %) but has creases near 1 %. No roughness model tried matched
all three at once, so a fix should be judged on both variants.

Cross-scroll validation: not applicable to the bench itself (a synthetic generator with contract tests); any
mesh-fix or alarm claim measured on it is development only and needs the usual frozen multi-scroll test.

Claim label: Model output for the baseline scores (synthetic meshes); Interpretation for the reading that the two
roughness variants bracket the real columns.

## Result so far (Model output, synthetic data only)

The first public build: `make --seeds 3` on both tracks (78 cases), `check` agrees, manifest sha256
`aa67bcebfda0b307a71626554d323794a52b45c78ecdc03451f163c77843d405`; it rebuilds byte for byte, since the seeds come
from the track and case names. Column track, means over 3 seeds.

| Alarm | band-b recall | band-only recall | merger recall | skip recall | false alarms on clean (max over cases) |
| --- | --- | --- | --- | --- | --- |
| none (control) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| all (control) | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| oracle (control) | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 |
| wjump (knows the true center and pitch) | 0.9992 | 1.0 | 0.9996 | 1.0 | 0.0002 |

| Repair | rough-a kept | rough-a-taubin kept | band-b kept | band-b wrong kept | fold cells kept | rough-a sheet error p95 (voxels) |
| --- | --- | --- | --- | --- | --- | --- |
| identity (control) | 1.0 | 1.0 | 1.0 | 1152.7 | 626 | 3.31 |
| oracle (control) | 1.0 | 1.0 | 0.958 | 0 | 0 | 0.0 |
| taubin5g | 0.943 | 0.995 | 0.964 | 1143.3 | 610 | 1.26 |

Interpretation: Taubin smoothing more than halves the sheet error but leaves almost every switch and fold in place
(it is a smoother, not a switch repair), and on the crease-matched roughness its half-pitch guard cuts 5.7 % of good
cells, against 0.32 % on the real columns; the Taubin-matched variant reproduces the real cut. wjump is a reference
that knows the true center and pitch, so it knows more than any real alarm and is not a fair competitor.

## Commands and options

### `python3 -m kit.defectbench cases`

```text
usage: python -m kit.defectbench cases [-h] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | print the cases as JSON |

### `python3 -m kit.defectbench make`

```text
usage: python -m kit.defectbench make [-h] [--track {column,mini,both}]
                                      [--seeds SEEDS]
                                      [--only CASE [CASE ...]]
                                      [--json]
                                      out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `OUT` | required | the bench folder; every case folder in it must be new or empty |
| `--track` | `both` | `column`, `mini` or `both` |
| `--seeds` | `3` | seeds 0 to N-1 of every case |
| `--only` | all | only these cases |
| `--json` | off | print the manifest as JSON |

### `python3 -m kit.defectbench check`

```text
usage: python -m kit.defectbench check [-h] [--json] out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `OUT` | required | a bench folder written by make |
| `--json` | off | print the disagreements as JSON |

### `python3 -m kit.defectbench baseline`

```text
usage: python -m kit.defectbench baseline [-h]
                                          (--alarm {none,all,oracle,wjump} |
                                          --repair {identity,oracle,taubin5g})
                                          --dir DIR [--track {column,mini}]
                                          out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `OUT` | required | the bench folder |
| `--alarm` | none | `none`, `all`, `oracle` or `wjump`: write per-case alarm masks |
| `--repair` | none | `identity`, `oracle` or `taubin5g`: write per-case repaired tifxyz |
| `--dir` | required | where to write them |
| `--track` | both | only this track |

### `python3 -m kit.defectbench score`

```text
usage: python -m kit.defectbench score [-h] (--alarms ALARMS |
                                       --repaired REPAIRED)
                                       [--track {column,mini}]
                                       [--out-file OUT_FILE] [--json]
                                       out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `OUT` | required | the bench folder |
| `--alarms` | none | a folder of alarm masks in the baseline layout |
| `--repaired` | none | a folder of repaired tifxyz in the baseline layout |
| `--track` | both | only this track |
| `--out-file` | none | also write the score JSON there |
| `--json` | off | print the score JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `BenchError()` | exception | None | ValueError subclass for every bench error |
| `sheets_for(track)` | kit.planted.Sheets | KeyError | the spiral of track column or mini |
| `footprint(shape, rng)` | bool (H, W) | None | An irregular valid footprint (wavy top and bottom, ragged ends) |
| `frames(sheets, shape)` | three (H, W, 3) arrays | None | Unit normal (radial), along-row and along-column directions |
| `roughen(valid, sheets, level, rng)` | (drow, dcol, dn) arrays | KeyError | A roughness level: in-plane grid moves along the sheet and a capped normal offset |
| `apply_ops(base_k, valid, sheets, ops, rng)` | (k, dcol, hole, chord, records) | BenchError | The planted winding offsets, fold column shifts, holes and chords |
| `build(track, case, seed)` | (arrays, record) | BenchError | One case in memory; deterministic in (track, case, seed) |
| `labels(sheets, arrays)` | (label int8, k float) | None | Per-vertex label and measured winding offset from coordinates only |
| `summary(arrays)` | dict | None | The summary truth written to defects.json |
| `quad_masks(xyz, valid, step)` | (valid quads, {spike, crease, flip}) | None | spike: an edge over two grid steps; crease: over 60 degrees to a neighbor quad; flip: against the 9 x 9 mean normal |
| `mesh_stats(xyz, valid, step)` | dict | None | Area shares of spike, crease and flip quads |
| `write_tifxyz(out, xyz, valid, uuid, source)` | Path | OSError | A tifxyz folder, invalid vertices -1 |
| `read_tifxyz(path)` | (xyz, valid) | OSError | valid is not all -1 and finite |
| `write_case(root, arrays, rec)` | Path | BenchError if the folder is not empty | Writes the case and its digests |
| `write_prediction(path, sheets, xyz, valid, chunk=64, margin=3.0, thickness=None)` | path | None | A binary sheet prediction, zlib zarr v2 OME-Zarr level 0 |
| `make(out, tracks=('column', 'mini'), seeds=3, only=None)` | manifest dict | BenchError | Writes the bench and manifest.json |
| `load_case(d)` | (xyz, valid, truth dict, record) | BenchError on a wrong schema | Reads one case |
| `check(root)` | list of disagreements | OSError | Empty means the bench agrees |
| `taubin(P, valid, passes=5, lam=0.5, mu=-0.53)` | (H, W, 3) array | None | Taubin smoothing of the four-neighbor umbrella |
| `alarm_baseline(kind, xyz, valid, t, rec, case_dir=None)` | bool (H, W) | BenchError on an unknown kind | none, all, oracle, wjump |
| `repair_baseline(kind, xyz, valid, t, rec)` | (xyz, keep) | BenchError on an unknown kind | identity, oracle, taubin5g |
| `baseline(root, out, alarm=None, repair=None, track=None)` | Path | BenchError | Writes a baseline for every case |
| `score_alarm(flags, t)` | dict | None | Recall, false alarms, regions hit |
| `score_repair(xyz2, valid2, t, rec)` | dict | None | Kept shares, residual defects, sheet error, mesh stats |
| `score(root, alarms=None, repaired=None, track=None)` | dict with rows and families | BenchError on a grid mismatch | Missing files are listed as missing, never scored |
| `aggregate(rows)` | dict | None | Means over seeds per track and case |
| `build_parser(p)` | argparse parser | None | The command line |
| `main(argv=None)` | exit code | None | 0, 2 or 3 |

## Inputs

- `make`: none (all synthetic). Options: `--track column|mini|both` (default both), `--seeds N` (default 3), `--only CASE ...`.
- `score --alarms DIR`: DIR/TRACK/CASE-sSEED.npy, a boolean (H, W) numpy array per case (True = flagged), on the
  case's own grid (column 91 x 405, mini 31 x 101).
- `score --repaired DIR`: DIR/TRACK/CASE-sSEED/, a tifxyz (x.tif, y.tif, z.tif float32, -1 where cut) on the case's
  own grid; coordinates in the case's voxel frame (x, y, z order, as tifxyz stores them).
- A mini case's `pred.zarr` is uint8 (z, y, x), 255 on a sheet, readable with zarr; its
  `umbilicus.json` holds two points of the spiral's center line as `points_xyz`.

## Outputs

`defects.json` per case:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | string | `kit-defectbench/1` |
| `track`, `case`, `seed` | string, string, int | which case |
| `roughness`, `rough_params` | string, object | the roughness level and its parameters |
| `model_of` | string | the column or tool case it stands for |
| `expected` | string | CORRECT (no defect), CORRECT-ROUGH (roughness only) or INCORRECT |
| `ops` | list | each planted operation with its grid box (rows r0..r1, columns c0..c1, end excluded) |
| `sheets` | object | the spiral (pitch, step, zstep, z0, w0, `centre` (the center), hand, theta0), as kit planted's Sheets |
| `truth` | object | vertices, invalid, clean, rough, wrong, gap, fold counts; switch_regions and their sizes; jump_edges; defect_share |
| `mesh` | object | crease, spike and flip area shares; taubin5g cut_share, move_p50 and move_p95 in voxels |
| `files` | object | sha256 of every other file of the case |

`truth.npz` per case: `label` (int8 H x W: -1 invalid, 0 clean, 1 rough, 2 wrong, 3 gap, 4 fold), `k` (float32,
measured winding offset), `ref` (float32 H x W x 3, the true position), `disp` (float32, position minus true
position), `folded` (bool).

`score` JSON: `kind` (alarms or repair), `rows` (one per case, with `missing` when the file is absent) and
`families` (means over seeds per `TRACK/CASE`). Alarm fields: `targets`, `flagged`, `recall`, `false_alarm_clean`,
`false_alarm_rough`, `regions`, `regions_hit` (a flag within one cell of the region), `regions_half_covered`.
Repair fields: `kept_share`, `good_kept_share` (clean and rough cells kept), `defect_cut_share` (wrong, gap and fold
cells cut), `wrong_kept`, `off_kept` (kept, not wrong, over 0.35 pitch off), `fold_kept`, `backward_edges` (kept row
edges running backward about the center), `sheet_err_p50` and `sheet_err_p95` (voxels to the base sheet),
`pos_err_p95` (voxels to the true position, good cells), `valid_outside_input`, `mesh`.

| Exit code | Meaning |
| --- | --- |
| `0` | success; for `check`, the bench agrees with its coordinates |
| `2` | a usage or input error (`kit defectbench: ...` on stderr) |
| `3` | `check` found a disagreement (listed) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `unknown repair baseline` | the --repair kind is not identity, oracle or taubin5g | use one of those |
| `unknown case 'NAME'; cases: [...]` | the case name is not in CASES | run `cases` for the list |
| `exists and is not empty` | make never writes into a used case folder | choose a new OUT or remove the old one |
| `unknown alarm baseline` | the --alarm kind is not none, all, oracle or wjump | use one of those |
| `kit defectbench:` | any BenchError, PlantError or OSError | read the rest of the line |
| `kit defectbench needs scipy (pip install scipy)` | scipy is missing | install scipy |
| `a bridge needs a border on all four sides` | a bridge op touches the grid edge | move its box inside |
| `FILE: shape (H, W) is not the case's grid (H, W)` | an alarm mask has another shape than the case | write one H x W mask per case |
| `DIR: grid (H, W) is not the case's grid (H, W); a repair must keep the input grid (cut vertices are -1)` | a repaired tifxyz was re-gridded | score on the input grid; mark cut vertices -1 |
| `DIR: schema 'X' is not kit-defectbench/1` | the case folder was written by another version or tool | rebuild the bench with `make` |
| `unknown op 'X'` | a case lists an operation the builder does not know (only when CASES is edited) | use band, switch, merger, fold, bridge, gapbridge or hole |

## How it works

1. Sheets: kit planted's Archimedean spiral. column: pitch 23, step 20, zstep 20, w0 51 (radius 1,173, so a 405-column
   row wraps 1.1 turns), center (1600, 1600), z0 1000. mini: pitch 11.5, step 10, w0 12, center (200, 200).
2. Footprint: wavy top and bottom edges and ragged ends, the same for every case of one seed.
3. Planted operations change the winding offset k (band: a blobby ellipse with a smooth ramp of `ramp` cells;
   switch; merger; gapbridge: a plateau at k = 0.5), shift columns backward (fold: u = c - g L sin(2 pi t) / 2 pi,
   gain 2, tapered over 3 rows), punch holes, or replace a block by the bilinear chord over its corners (bridge).
4. Roughness (`ROUGH`): a background normal jitter, clustered rough spots that move along the sheet and along the
   normal, and (rough-a-taubin) log-normal grid spacing; the normal offset is capped at `ROUGH_CAP` 0.30 pitch so a rough
   vertex is never labeled gap.
5. Coordinates are rounded to float32 before labelling, so `check` sees the same numbers as the files.
6. Labels (`labels`): wrong when |k| >= 0.5; gap when farther than `GAP_TOL` 0.35 pitch from every sheet; fold;
   rough when over `ROUGH_TOL` 1 voxel from the true position.
7. Mesh statistics (spike: an edge over two grid steps; crease: over 60 degrees
   to a neighbor quad; flip: against the 9 x 9 mean normal) and record taubin5g's moves and half-pitch cut.

## Cost and time

CPU only, 0 USD. `make --seeds 3` on both tracks: 1 min 43 s and 168 MB (most of it the mini predictions); `check`
1 s; a baseline and its score about 1 min each (measured 2026-11-27, 4-core cloud container). Memory under 1 GB.

## For agents

- **Command:** `python3 -m kit.defectbench make OUT --seeds 3 && python3 -m kit.defectbench check OUT`, then write
  your tool's output in the baseline layout and run `python3 -m kit.defectbench score OUT --repaired DIR --json`
  (or `--alarms DIR`).
- **Parse:** `families["column/CASE"]` in the score JSON; for a repair read `good_kept_share`, `wrong_kept`,
  `fold_kept` and `sheet_err_p95`; for an alarm `recall`, `false_alarm_clean` and `false_alarm_rough`.
- **Rerun:** safe; `make` refuses a used folder, `baseline` and `score --out-file` overwrite.
- **Success:** exit 0; `check` prints `agrees`.
- **Not a pass:** any bench score as evidence about a scroll; a score without the `identity` or `none` control
  beside it; a recipe judged on one roughness variant only.
- **Go-ahead:** Nothing.
- **Never:** tune a recipe on the bench and call it validated; put bench meshes where real segments are expected.

## Tests

`python3 -m unittest tests.test_defectbench` (about 10 s): `check` agrees and catches a moved vertex; every case's
expected class; the crease and spike calibration within 25 %; the Taubin-matched variant; band-b's shape; alarm
and repair controls fail and the oracles pass; a wrong grid is refused; determinism; the mini prediction sits under
clean vertices and not under gap vertices. Not covered: any real mesh, flattening, CT-reading alarms.

## History

- 2026-11-27: first public version, 13 cases on two tracks, with the none, all, oracle, wjump, identity, oracle and
  taubin5g baselines.

## Related

- [kit planted](planted.md): the shared spiral and the first planted families this extends.
- [ScrollSim v2](scrollsim2.md): synthetic CT, for alarms that read CT.
