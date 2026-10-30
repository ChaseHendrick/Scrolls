# seamswitch: count seam-aware winding switches of a spiral fit

Counts how often a spiral fit puts neighboring vertices of one sheet on different windings, after allowing for the fit's own seam: switches per 1000 neighbor pairs and the seam wrong area, on labeled or unlabeled sheet grids.

| Field | Value |
| --- | --- |
| Id | `seamswitch` |
| Status | Experimental |
| Kind | kit module, kit entry point |
| Area | Scoring and controls |
| Run | `python -m kit.seamswitch`, `from kit.seamswitch import seam_switches, sheet_switches, pool` |
| Code | `kit/seamswitch.py` |
| Tests | `tests/test_seamswitch.py` |
| Needs | Python 3.10 or newer, numpy; the caller supplies the fit's coordinates or windings on each sheet grid |
| Runs on | Any CPU. A 60 by 20,000 grid (1.2 million vertices) takes about 3.3 s in `sheet_switches` (measured 2026-10-29, 4-core cloud container, synthetic grid) |
| Network | None |
| Writes | Nothing (prints a summary line, or JSON with `--json`) |
| Go-ahead | Not needed |
| Released | Public `main` from this release; a line of the Scrolls kit entry in the README's "Released tools", id `seamswitch` |
| Checked | 2026-10-29 against commit `afcc05a` |

## What it does

A spiral fit gives every point of a scroll a winding coordinate: how many turns out from the core it sits. A traced sheet (a grid of vertices that follow one layer of papyrus) should stay on one winding all along, except where it crosses the fit's own seam, the angle where the winding count steps by one, which a fit may put anywhere. A switch is a pair of touching grid vertices that the fit puts on different windings once the seam is allowed for. Switches are the local errors that pair-accuracy scores of relative windings can miss: a fit can get most point pairs right and still tear a sheet across two windings in places.

`sheet_switches` scores one unlabeled traced sheet. It takes the fit's spiral coordinates of each vertex, rho = r / dr (radius over winding spacing) and theta, unwraps theta along a spanning forest of the grid so e = rho - theta / 2 pi is the fit's continuous winding along the sheet, rounds e minus each connected piece's median to a whole winding offset d, and takes the most common d in each 10 degree by 250 voxel cell as that cell's seam offset. A switch is a neighbor pair whose d minus its cell offset differs; the wrong area is the share of vertices off their cell's offset. `seam_switches` does the same for labeled grids, where each vertex has the fit's whole winding j and a label winding k, with d = j - s k for the label direction s that fits best. `local_switches` counts only whole-winding jumps between neighbors; a smooth fit drifts instead, so `sheet_switches` is the one to use on fits. `pool` sums several grids.

The definition restates the one in [CanadaApollo6/vesuvius-spiral-chains](https://github.com/CanadaApollo6/vesuvius-spiral-chains) `eval/spiral_eval.py` (Apache-2.0, read 2026-10-29 at commit `4365b98`): 10 degree by 250 z cells, switches per 1000 adjacent grid pairs. It is written anew, not copied, so a number from either can be set beside the other on the same grids.

It does not fit anything, does not look at the CT and does not say which winding is right; on unlabeled grids it measures only whether the fit keeps each sheet together. A number it computes on a fit is a geometry score of model output. It is not a reading and says nothing about ink.

## When to use it

- Beside a pair-accuracy readout of relative windings, when a fit change (a constraint weight, a margin, an anneal) might add local islands that pair scores miss.
- On traced sheet meshes with no winding labels, as a label-free check that a fit keeps each sheet on one winding (`sheet`).
- On dense labeled sheet grids, to count switches against the labels (`labeled`).

Do not use it:

- For pair accuracy of relative windings against held-out pairs: use the step readout of [windlabel-box](windlabel-box.md).
- To check that relative winding counts agree with each other: use [windconsistency](windconsistency.md).
- On a fit's own constraint points, which the fit was pulled onto; score held-out sheets.
- On sparse labels such as rays with one point per winding: there are no same-sheet neighbors to count.

## Quick start

```bash
python -m kit.seamswitch demo
echo "exit $?"
```

It printed (synthetic sheet, 2026-10-29):

```
clean sheet: 0 switches of 47540 neighbor pairs
planted patch: 120 switches (patch boundary 120 pairs), 2.52 per 1000
ok
exit 0
```

The demo builds a 60 by 400 sheet that winds three turns at constant spacing, scores it clean, then moves a 20 by 40 patch one winding out and scores it again. It worked when the clean sheet has 0 switches, the planted one has exactly as many as the patch boundary cuts, and the exit code is 0. On your own grids, `python -m kit.seamswitch sheet GRID.npz` scores one sheet:

- `GRID.npz`: a numpy `.npz` file with H x W arrays `rho`, `theta`, `z` and `valid` (see Inputs).

## Checks and controls

- **It can fail on a planted error.** The demo and the tests move a patch one winding out and require the count to equal the number of neighbor pairs its border cuts, exactly; a clean sheet must give 0. A scorer that ignored switches, or counted the seam, would fail these.
- **The seam is not a switch.** A sheet crossing the seam several times (a two-turn and a four-turn spiral in the tests) gives 0 switches; a seam that sits at a cell boundary gives 0 seam-aware switches but is seen by the global count, which is the control that the cell offsets do something.
- **Drift is counted where jumps are not.** A slow drift of 1.6 windings along a sheet is counted by `sheet_switches` and missed by `local_switches`, which the tests check both ways.
- **The label direction is found.** Reversed labels give the same counts with `sign` -1; invalid and non-finite vertices are left out; pieces under `min_tree` vertices are left out.
- **What a result needs.** Any use on fits needs a control arm scored the same way (the same grids under a baseline fit), and the difference between arms is the result. It has been run here on synthetic grids only; no fit on real data is scored on this page.

Claim label: None. The tool's checks are on synthetic grids; a number it computes on a real fit is Model output.

## Commands and options

### `python -m kit.seamswitch`

```
usage: python -m kit.seamswitch [-h] {demo,sheet,labeled} ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `demo` | | Synthetic sheet, clean and with one planted wrong-winding patch |
| `sheet` | | Unlabeled sheet grids (`.npz` with `rho`, `theta`, `z`, `valid`) |
| `labeled` | | Labeled sheet grids (`.npz` with `j`, `k`, `valid`, `angle`, `z`) |

### `python -m kit.seamswitch demo`

```
usage: python -m kit.seamswitch demo [-h] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | Print the full result as JSON |

### `python -m kit.seamswitch sheet`

```
usage: python -m kit.seamswitch sheet [-h] [--bin-deg BIN_DEG] [--bin-z BIN_Z] [--min-tree MIN_TREE] [--json]
                                      GRID.npz [GRID.npz ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `GRID.npz` | required | One `.npz` file per sheet grid, one or more |
| `--bin-deg` | 10.0 | Angle bin of the seam cells, degrees |
| `--bin-z` | 250.0 | z bin of the seam cells, voxels |
| `--min-tree` | 100 | Leave out connected pieces with fewer vertices |
| `--json` | off | Print the full result as JSON |

### `python -m kit.seamswitch labeled`

```
usage: python -m kit.seamswitch labeled [-h] [--bin-deg BIN_DEG] [--bin-z BIN_Z] [--json] GRID.npz [GRID.npz ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `GRID.npz` | required | One `.npz` file per sheet grid, one or more |
| `--bin-deg` | 10.0 | Angle bin of the seam cells, degrees |
| `--bin-z` | 250.0 | z bin of the seam cells, voxels |
| `--json` | off | Print the full result as JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `sheet_switches(rho, theta, z, valid, bin_deg=10.0, bin_z=250.0, min_tree=100)` | dict: counts `vertices`, `trees`, `pairs`, `cells`, `switches`, `switches_global`, `jumps`, `wrong`, `wrong_global` and rates `switches_per_1000`, `wrong_area`, `switches_per_1000_global`, `wrong_area_global`, `jumps_per_1000` (only `vertices`, `trees`, `pairs` when nothing is kept) | Nothing for matching shapes | One unlabeled traced sheet; theta unwrapped along a spanning forest of the grid |
| `seam_switches(surfaces, bin_deg=10.0, bin_z=250.0)` | dict: `sign`, `vertices`, `pairs`, `cells`, `switches_per_1000`, `wrong_area`, `switches_per_1000_global`, `wrong_area_global` (only `vertices` and `pairs` when nothing is valid) | `KeyError` when a surface lacks a key | surfaces: iterable of dicts of H x W arrays `j`, `k`, `valid`, `angle`, `z` |
| `local_switches(rho, theta, valid)` | dict: `pairs`, `switches`, `per_1000` (NaN when no pair is valid) | Nothing for matching shapes | Whole-winding jumps between neighbors only; non-finite rho or theta counts as invalid |
| `pool(results)` | The summed counts and recomputed rates | Nothing | Sums `sheet_switches` results over grids |
| `demo_sheet(h=60, w=400, turns=3.0, patch=None, dr=1.0)` | `(grid, cut)`: a dict for `sheet_switches` and the number of neighbor pairs the planted patch border cuts | Nothing | patch = `(r0, r1, c0, c1)` is moved one winding out |
| `main(argv=None)` | Exit code | Nothing; input errors print and return 2 | What `python -m kit.seamswitch` runs |
| `InputError` | | | `ValueError` raised by the file loader for unusable `.npz` input; `main` catches it |

## Inputs

Each `GRID.npz` holds one sheet grid as H x W arrays of one shape, read with `numpy.load`:

| Command | Arrays | Meaning |
| --- | --- | --- |
| `sheet` | `rho`, `theta`, `z`, `valid` | rho = r / dr, the fit's radius over its winding spacing; theta in radians, wrapped or not; z in voxels, in the frame of `--bin-z`; valid as bool (non-finite values count as invalid) |
| `labeled` | `j`, `k`, `valid`, `angle`, `z` | j the fit's whole winding, k the label winding, valid where both are known, angle in degrees around the scroll's axis, z in voxels |

The grid's rows and columns must follow the sheet: neighbors in the grid are neighbors on the papyrus. Size is limited only by memory; 1.2 million vertices took about 3.3 s.

## Outputs

Without `--json`, one summary line: the demo's three lines; for `sheet`, the pooled pairs, switches per 1000 and wrong area; for `labeled`, the same from `seam_switches`. With `--json`, the full result with sorted keys:

| Field | Type | Meaning |
| --- | --- | --- |
| `ok` | bool | demo: the clean sheet has 0 switches and the planted one the patch border count; sheet: true when every file was read; labeled: at least one valid vertex |
| `grids` | object | sheet: each file path to its `sheet_switches` result |
| `pooled` | object | sheet: `pool` over all files |
| `clean`, `planted`, `planted_cut_pairs` | object, object, int | demo: the two results and the expected count |
| `switches_per_1000` | float | Neighbor pairs whose offset minus cell offset differs, per 1000 pairs |
| `wrong_area` | float | Share of vertices whose offset is not their cell's |
| `switches_per_1000_global`, `wrong_area_global` | float | The same with one offset for all vertices |
| `jumps_per_1000` | float | sheet: whole-winding jumps between neighbors, per 1000 pairs |
| `sign` | int | labeled: +1 or -1, the label direction used |

| Exit code | Meaning |
| --- | --- |
| `0` | Scored, and `ok` is true |
| `1` | Scored, and `ok` is false (the demo did not count as planned, or a labeled grid had no valid vertex) |
| `2` | An input file was unusable (message on stderr), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `seamswitch: PATH: no array NAMES (needs KEYS)`, exit 2 | The `.npz` lacks an array the command needs | Save every array the command lists under Inputs |
| `seamswitch: PATH: not a readable .npz (ERROR)`, exit 2 | The path does not exist or is not a numpy `.npz` | Fix the path, or save the grid with `numpy.savez` |
| `seamswitch: PATH: every array must be one H x W grid of the same shape`, exit 2 | The arrays differ in shape or are not 2D | Save all arrays of one grid with one H x W shape |
| `KeyError` from `seam_switches` | A surface dict lacks `j`, `k`, `valid`, `angle` or `z` | Pass all five arrays |
| Only `vertices`, `trees` and `pairs` in a result | No valid vertex, or every piece is under `min_tree` | Check the fit covers the grid, or lower `--min-tree` |

## How it works

1. `sheet_switches`: valid vertices form a spanning forest of the grid, each vertex's parent its left neighbor if valid, else the one above (`_forest`). Theta differences to the parent, wrapped to (-pi, pi], give each vertex its whole turns from its tree's root by pointer doubling, so e = rho - theta / 2 pi - turns is continuous along the sheet.
2. Trees under `min_tree` vertices (default 100) are left out. In each kept tree, d = round(e - median e).
3. Cells are `floor(angle / bin_deg)` by `floor(z / bin_z)`, defaults 10 degrees and 250 voxels; each cell's offset is the mode of d in it (`_mode`).
4. A switch is a 4-neighbor pair in one tree whose d minus cell offset differs (`_pairs`); the global versions use offset 0. A jump is a pair whose rho difference, less the wrapped theta difference over 2 pi, rounds to a nonzero whole winding.
5. `seam_switches` takes d = j - s k, with s = +1 or -1 whichever makes the most common d more common, then steps 3 and 4.

The cell sizes and the per 1000 pairs rate follow CanadaApollo6/vesuvius-spiral-chains `eval/spiral_eval.py` (Apache-2.0, commit `4365b98`).

## Cost and time

Measured 2026-10-29 on a 4-core cloud container: the 19 tests take about 0.4 s; `sheet_switches` on a synthetic 60 by 20,000 grid (1.2 million vertices) about 3.3 s. Memory grows linearly with the vertex count. It runs on any CPU; nothing here needs a GPU or rented compute.

## For agents

- **Command:** `python -m kit.seamswitch sheet GRID.npz [GRID.npz ...] --json`; `python -m kit.seamswitch demo` as a self-test.
- **Parse:** `pooled.switches_per_1000` and `pooled.wrong_area` (sheet), `switches_per_1000` and `wrong_area` (labeled); compare arms, not single values.
- **Rerun:** Safe and idempotent; it only reads the files.
- **Success:** Exit code 0, `ok` true and `pairs` above zero.
- **Not a pass:** A single arm's value with no control arm; values on the fit's own constraint points; exit 0 with `pairs` 0.
- **Go-ahead:** Nothing.
- **Never:** Call its output a reading or evidence of text; score fresh held-out truth with it outside a frozen preregistration.

## Tests

```bash
python -m unittest tests.test_seamswitch -v
```

19 tests, all synthetic, about 0.4 s: constant offsets, a seam at a cell boundary, islands counted exactly, reversed labels, invalid vertices, multi-turn sheets crossing the seam, a slow drift, small trees, pooling, and the command line (demo, sheet and labeled files, exit codes 0, 1 and 2 and their messages). They skip without numpy. Real fits are not tested.

## History

- 2026-10-29: first public release, on top of `afcc05a`, with the `python -m kit.seamswitch` command line and its demo; the library was first written the same day for a switch check on spiral fits

## Related

- [windlabel-box](windlabel-box.md): the relative winding tool whose fits this scores beside its step accuracy.
- [windconsistency](windconsistency.md): checks that relative winding counts agree with each other.
- [windcheck](windcheck.md): measures how far a slice's sheet traces wrap around a candidate axis point, a check on the center a fit uses.
