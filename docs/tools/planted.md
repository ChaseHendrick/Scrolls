# planted: planted sheet switches, holes and mergers with known answers

One shared generator of planted defects (sheet switches, lenses, skips, mergers, holes and bridged holes) on synthetic tifxyz surfaces, each with its true winding per vertex, so stack checks, switch detectors and reference labelers test against the same known answers.

| Field | Value |
| --- | --- |
| Id | `planted` |
| Status | Current |
| Kind | kit entry point |
| Area | Surfaces and tracing |
| Run | `python -m kit.planted` |
| Code | `kit/planted.py` |
| Tests | `tests/test_planted.py` |
| Needs | Python 3.9 or newer and numpy; tifffile or kit's own TIFF writer (`kit/vc3d_io.py`) to write tifxyz. No scan data, villa or GPU. |
| Runs on | CPU anywhere; a 20 x 160 plant is made, written and checked in well under a second (measured 2026-10-21, Claude cloud container) |
| Network | None |
| Writes | `make`: the OUT tifxyz folder (`x.tif`, `y.tif`, `z.tif`, `meta.json`, `planted.json`); `families` and `check` print only |
| Go-ahead | Not needed |
| Released | Public `main` from the merge of its pull request (21 Oct 2026); the same file is in Scrolls-private |
| Checked | 2026-10-21 against commit `2601c1f` |

## What it does

Every tool that finds sheet switches, holes or mergers needs surfaces where the answer is known, and each used to build its own: `kit stackcheck`'s tests, for example, build a stack of spiral windings by hand. `kit planted` is one generator for all of them. It came from Scrolls-private, where more tools are tested against the same file.

A surface lies on a family of concentric sheets: an Archimedean spiral about a center, or parallel planes for tools that read a small prediction volume. Every vertex records the winding it truly sits on as an offset from the base winding (0 on the base, 1 on the next winding out). A plant moves vertices between windings, removes them or replaces them, and the truth (wrong vertices, off-sheet vertices, jump edges, the rim next to the wrong part, holes, components and the expected label) is computed from the moved vertices, never from any tool's output. `check` recomputes the winding of every vertex from its coordinates alone, so a plant that silently did nothing, or coordinates edited behind the record, is caught.

| Family | Id | What is planted | Expected |
| --- | --- | --- | --- |
| clean | none | nothing: the control twin of every plant | CORRECT |
| switch | N2 | rows r0..r1 jump dk windings at column c0 and stay there | INCORRECT |
| lens | N7 | switch and return: a block on the neighboring winding | INCORRECT |
| skip | N6 | a hard switch two windings out | INCORRECT |
| merger | N3 | the whole height slides onto the neighbor over 4 columns, with no single jump edge, and stays there | INCORRECT |
| hole | Q4 | a punched hole; the rest stays on its sheet | CORRECT |
| bridge | N12 | a hole filled by the bilinear plane over its four corners; it leaves a curved sheet | INCORRECT on the spiral, CORRECT on planes |

Ids starting with N are planted errors, Q a planted change that is still correct. It is synthetic data only: no scan, label or model output is read or written, and a planted surface is not a trace of any scroll.

## When to use it

Use it:

- to test a switch, hole or merger detector, a stack check or a labeler against known answers (tests/test_planted.py runs `kit stackcheck` on planted stacks);
- to build a stack of windings for a test, each one turn of the spiral, with `surface(sheets, shape, k0=k)`.

Do not use it:

- to measure a tool's accuracy on real scrolls: score it against published references;
- for ink: use `kit phantom` or the ink benchmarks.

## Quick start

```bash
python -m kit.planted make OUT --family switch
python -m kit.planted check OUT
python -m kit.planted make OUT2 --family merger --geometry planes
```

Printed on 2026-10-21 (OUT in a scratch folder):

```
OUT: switch, wrong 720, off 0, jump edges 154, holes 0, components 1, INCORRECT
agrees
OUT2: merger, wrong 420, off 60, jump edges 0, holes 0, components 1, INCORRECT
```

OUT is a folder to create; OUT2 another. `check` prints `agrees` and exits 0 when the coordinates give the recorded truth.

## Checks and controls

Each plant has a clean twin, and the tool tests run both. On a stack of six windings built by `kit planted` (pitch 50 voxels, one turn per segment), `kit stackcheck` reports the clean stack clean, a hole in w02 as its missing sector and nothing else, and a lens of w03 on w02's sheet or a merger of w02 onto w03 as the coincident pair w02/w03 and nothing else (tests/test_planted.py, 21 Oct 2026). `check` is the generator's own control: moving a block of a clean plant one winding out without updating `planted.json` gives `DISAGREES` and exit 3, and a switch whose vertices were never moved is caught too.

Claim label: Model output for stackcheck's flags on the plants; the plants themselves are synthetic data with a known answer

## Commands and options

### `python -m kit.planted families`

```
usage: python -m kit.planted families [-h] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | print the result as JSON |

### `python -m kit.planted make`

```
usage: python -m kit.planted make [-h]
                                  --family {bridge,clean,hole,lens,merger,skip,switch}
                                  [--geometry {spiral,planes}] [--shape H W]
                                  [--rows R0 R1] [--cols C0 C1] [--dk DK]
                                  [--ramp RAMP] [--overwrite] [--json]
                                  out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | output tifxyz folder (must not exist or be empty) |
| `--family FAMILY` | required | the defect to plant |
| `--geometry GEOMETRY` | `spiral` | spiral (pitch 20, 20 x 120 grid) or planes (pitch 14, 30 x 40 grid, for prediction-volume tests) |
| `--shape H W` | none | grid rows and columns |
| `--rows R0 R1` | none | rows of the site, R1 excluded |
| `--cols C0 C1` | none | columns of the site, C1 excluded |
| `--dk DK` | none | windings the plant moves by (default 1, 2 for skip) |
| `--ramp RAMP` | `4` | columns a merger takes to slide across |
| `--overwrite` | off | write into a folder that is not empty |
| `--json` | off | print the result as JSON |

### `python -m kit.planted check`

```
usage: python -m kit.planted check [-h] [--json] dir
```

| Option | Default | Meaning |
| --- | --- | --- |
| `dir` | required | a folder written by make |
| `--json` | off | print the result as JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `PlantError()` | Exception class | None | Raised for a bad site, family, geometry or file |
| `Sheets(kind='spiral', pitch=20.0, step=5.0, zstep=5.0, z0=100.0, w0=10.0, centre=(500.0, 400.0), hand=1, theta0=0.0, x0=40.0, y0=10.0)` | a sheet family with `point`, `measure`, `distance`, `params` | PlantError for a bad geometry | Concentric sheets with a continuous winding coordinate f: sheet k (an offset from the base winding) is the |
| `prediction_volume(sheets, shape, thickness=5.0, kmin=None, kmax=None, origin=(0, 0, 0))` | uint8 (z, y, x) array, 255 on a sheet | None | A binary (z, y, x) uint8 sheet prediction (255 on a sheet) for the same sheets: every voxel within |
| `Plant(sheets, xyz, valid, k, k0=0, family='clean', site=None, history=None)` | a plant: `xyz`, `valid`, `k`, `k0`, `family`, `site`, `history` | None | A grid surface on `sheets` with the true winding offset k of every vertex (NaN where invalid). |
| `surface(sheets=None, shape=(20, 120), k0=0)` | a clean Plant | PlantError for a grid under 4 x 8 | A clean surface: every vertex on winding k0 (the base, offset 0). |
| `plant(base, family, rows=None, cols=None, dk=None, ramp=4)` | a new Plant; `base` is not changed | PlantError | A copy of `base` with one defect of `family` planted at rows r0..r1-1 and columns c0..c1-1. |
| `truth(p, tol=None)` | dict of truth fields | None | The known answer of a plant, from its true winding offsets and coordinates only. |
| `masks(p, tol=None)` | (wrong, off) boolean grids | None | (wrong, off) boolean grids of a plant, the per-vertex form of truth(). |
| `neighbours(p, ks=(-2, -1, 1, 2))` | dict offset to (xyz, valid) | None | Clean grids of the windings at offsets ks next to the base: the true references a labeler matches the plant against |
| `write(p, out, overwrite=False)` | the folder path | PlantError when it is not empty | Write the plant as a tifxyz folder with planted.json beside meta.json. |
| `load(path)` | (Plant, record dict) | PlantError for a missing or foreign planted.json | (plant, record) from a folder written by write(). |
| `check(path, atol=0.001)` | list of disagreement strings; empty when it agrees | PlantError | Disagreements between a written plant's record and what its coordinates say. Empty means it agrees. |
| `build_parser(p)` | the parser | None | Adds families, make and check to `p` |
| `main(argv=None)` | exit code | None | `python -m kit.planted` |
| `cmd_planted(args)` | exit code: 0, 2 or 3 | None | The three actions |

## Inputs

- `make`: a family name, the geometry, and optionally the grid shape, the site (rows R0 R1 and columns C0 C1, end excluded), dk and the merger's ramp. Defaults: spiral of pitch 20 voxels, w0 10 (the base winding's radius over pitch), center (500, 400), column arc step 5 voxels, rows 5 voxels apart in z from z 100, grid 20 x 120; planes of pitch 14 at x 40, columns along y and rows along z 4 voxels apart from (10, 10), grid 30 x 40.
- `check`: a folder written by `make` or `write()`.

## Outputs

`make` writes OUT as a tifxyz (`x.tif`, `y.tif`, `z.tif` float32 with -1 at holes, `meta.json` with `format` tifxyz and `bbox`) and `planted.json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | string | `kit-planted/1` |
| `synthetic` | bool | always true |
| `family`, `site`, `history` | string, dict, list | what was planted where (stacked plants join names with +) |
| `sheets` | dict | the geometry's parameters |
| `k0` | int | the base winding |
| `k` | list of rows | each vertex's true winding offset, null at holes |
| `truth.wrong` | int | valid vertices at least half a winding from the base |
| `truth.off` | int | valid vertices farther than `off_tol_vox` (a quarter pitch) from every sheet |
| `truth.jump_edges` | int | grid edges whose ends differ by at least half a winding (also split rowwise and colwise) |
| `truth.rim` | int | valid vertices that are not wrong but share a grid edge with a wrong one |
| `truth.holes`, `truth.components` | int | invalid vertices; 4-connected valid parts |
| `truth.expected` | string | INCORRECT when anything is wrong or off, else CORRECT |

| Exit code | Meaning |
| --- | --- |
| `0` | success (`check`: the coordinates agree with the record) |
| `2` | a usage error (bad family, site, geometry, a folder that is not empty) |
| `3` | `check` found a disagreement (DISAGREES and the reasons) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `a surface needs at least 4 rows and 8 columns` | The grid is too small for a site | Use at least 4 x 8 |
| `unknown family 'x'; families: [...]` | The family name is not in FAMILIES | `kit planted families` |
| `site rows 0..9 cols 0..9 is outside the 8 x 8 grid or empty` | The site leaves the grid or is empty | Give rows and columns inside the shape, end excluded |
| `needs a nonzero dk` | A moving family was asked to move by 0 | Give a nonzero `--dk` |
| `exists and is not empty` | OUT already holds files | Pick a new folder or pass `--overwrite` |
| `has no planted.json` | The folder was not written by kit planted | Point `check` at a `make` output |
| `planted.json: schema 'x' is not kit-planted/1` | The record was written by another version of kit planted, or edited | Write the folder again with `make` |
| `kit planted:` | Any usage error, exit 2 | Read the rest of the line |
| `kit planted needs numpy` | numpy is not installed | Install numpy |
| `geometry must be one of ('spiral', 'planes'), not 'x'` | The geometry is not spiral or planes | Use one of the two |
| `pitch, step and zstep must be positive` | A spacing is zero or negative | Give positive values |
| `hand must be 1 or -1` | The spiral's sense is not 1 or -1 | Use 1 or -1 |
| `writing a tifxyz needs kit.vc3d_io or tifffile` | Neither tifffile nor kit's TIFF writer is importable | Install tifffile |
| `reading a tifxyz needs tifffile` | `load` and `check` read the grids with tifffile | Install tifffile |
| `merger needs ramp >= 1 and room after the ramp inside the site` | The merger's ramp does not fit in its site | Shorten the ramp or widen the site |
| `a bridge needs a border on all four sides` | A bridge needs valid corners on all four sides | Move the site off the grid's edge |

## How it works

1. `Sheets` defines the winding coordinate f: on the spiral r = pitch (w0 + f + hand (theta - theta0) / 2 pi), on the planes x = x0 + pitch f. Sheet k is the level set f = k. `measure()` inverts it from a vertex's coordinates and its column's nominal angle (which unwraps the spiral angle across the branch line); `distance()` is pitch times the distance of f to the nearest integer.
2. `surface()` puts every vertex on the base winding. `plant()` changes the true offsets of the site (switch, lens and skip add dk; the merger adds dk times a smoothstep over `ramp` columns, so no edge changes by half a winding) and moves the vertices onto the sheets those offsets name, or invalidates them (hole), or replaces them by the bilinear plane over the hole's four corners and measures where that plane sits (bridge).
3. `truth()` counts from the offsets and coordinates. The off-sheet tolerance is a quarter pitch.
4. `prediction_volume()` marks every voxel within thickness / 2 (default 5 voxels thick) of a sheet in [kmin, kmax]: on the planes, sheets 0 and 1 sit at x 38 to 42 and 52 to 56.
5. `neighbours()` gives the true windings at offsets -2 to 2 as references for a labeler.

## Cost and time

A 20 x 160 plant is made, written and checked in well under a second; the 20 tests in tests/test_planted.py take about 47 s on CPU, nearly all of it the four stackcheck runs (2026-10-21, Claude cloud container under load).

## For agents

- **Command:** `python -m kit.planted make OUT --family F --json` then `python -m kit.planted check OUT --json`
- **Parse:** `truth` in make's JSON (`wrong`, `off`, `jump_edges`, `rim`, `expected`); `agrees` and `disagreements` in check's
- **Rerun:** `make` refuses a folder that is not empty unless `--overwrite`; `check` is read-only
- **Success:** make exits 0; check exits 0 with `agrees: true`
- **Not a pass:** A tool that passes on plants has passed on synthetic sheets only; it says nothing about real scrolls until it is scored against references
- **Go-ahead:** Nothing
- **Never:** Never present a planted surface or a tool's result on it as a trace or a finding on any scroll

## Tests

`python -m unittest tests.test_planted -v` (20 tests): geometry inversion in both senses and on planes, the branch line, the prediction volume, every family's truth and counts, a base winding other than 0, stacking and refusals, write and check round trips for every family, both controls of `check`, the command line, and `kit stackcheck` on planted stacks with the clean stack as control.

## History

- 2026-10-21: first public version, the same file as Scrolls-private's (`dd4a49f`)

## Related

- [stackcheck](stackcheck.md): tested against planted stacks.
- [phantom](phantom.md): synthetic ink, not geometry.
