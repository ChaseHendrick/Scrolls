# axispolish: polish a center line to the deepest point of the traced sheet

`python -m kit axispolish` moves a scroll's center line (umbilicus), slice by slice, to the point of highest winding coverage nearby on the scan's published normal grids, and writes it back in the published format for VC3D and the spiral fit.

| Field | Value |
| --- | --- |
| Id | `axispolish` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit axispolish`, `from kit import axispolish` |
| Code | `kit/axispolish.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_axispolish.py` |
| Needs | Python 3.10 or newer and numpy; numba optional (the same sums compiled, about 8 times faster); the scan's level-0 normal grids, found on the open-data bucket or given with `--grids` |
| Runs on | CPU. About 1.4 s per slice with numba on 4 cloud cores (PHerc0175A, 91 slices in 127 s with grids cached, 24 Oct 2026); about 6 s per slice with numpy alone (the frozen test's development runs, 22 Oct 2026); a whole line is about 100 slices, see Cost and time |
| Network | `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`: one bucket listing to find the grids, then one `xy/NNNNNN.grid` file per polished slice. None with a local `--grids` folder |
| Writes | The polished line at `--out` (parent folders created); with `--cache DIR`, the downloaded grid files under `DIR/xy/` |
| Go-ahead | Not needed: local arithmetic on public grids |
| Released | Public `main` since 2026-10-24; a line of the Scrolls kit entry in the README's "Released tools" |
| Checked | 2026-10-24 against commit `81e5ead` |

## What it does

A center line says where the scroll's winding center sits on each slice. VC3D and villa's spiral fit read it as `umbilicus.json`. A line can sit beside the true center: the Center Finder learned where people put their lines, and people place by eye.

`axispolish` keeps the line as a guess and, on one slice every 100 (`--every`), searches a disc of 8 mm round the guess for the point of highest winding coverage ([windcheck](windcheck.md)): how many wraps of the slice's traced sheet sweep a full turn round the point. Coverage is highest inside the innermost wrap, so the best point is the deepest place in the rolled sheet. The traced sheet is the scan's published normal grid, the predicted papyrus surface that villa's `vc_gen_umbilicus` also reads. The polished points pass a robust check along z that drops a point far from its neighbors, and become the new line.

It does not find the true axis: coverage is measured on a model's predicted sheets, and a slice with a hollow core (no trace near the center) has flat coverage, so the polish can stop anywhere inside it. The polished line is Model output. Do not polish a person's line: their placement is theirs, and the test below only measured the Center Finder's lines.

## When to use it

- On a Center Finder line from the [center lines dataset](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines) ([centerline](centerline.md) gets it), before a spiral fit or a VC3D project, when the scan has level-0 normal grids on the bucket.
- On your own estimated line (from villa's `vc_gen_umbilicus` or another estimator) as an untested experiment: score it yourself.

Do not use it:

- On a line a person made: use it as it is.
- On a scan with no published level-0 normal grids: it refuses; get a line with [centerline](centerline.md) instead.
- To score lines against each other: coverage is a measurement on one set of predicted sheets; use the same slices and grids for every line, as [windcheck](windcheck.md) describes.

## Quick start

```bash
python -m kit centerline get PHerc0175A --source finder --out work/PHerc0175A_finder.json --no-stamp
python -m kit axispolish work/PHerc0175A_finder.json --out work/PHerc0175A_polished.json --cache work/grids-0175A
```

Run on PHerc0175A's Center Finder line (2026-10-24, 4-core cloud container, numba, grids cached from an earlier run), it printed:

```text
wrote work/PHerc0175A_polished.json: 88 points from 91 of 91 slices
median move: 0.806 mm
median coverage gain: 0.4838 wraps
time: 127.2 s
Model output, not the true axis: On ten fresh scans the Center Finder's lines, polished so, beat villa's vc_gen_umbilicus by winding coverage at slices the polish never read: +0.084 wraps, 8 of 10 scans, 95% interval +0.028 to +0.169 (docs/evidence/2026-10-22-umbilicus-windpolish/)
```

The first run, which also fetched the 91 slices' grids, took 134.7 s.

It worked when the exit code is 0 and the summary names more polished slices than skipped ones. Open the result in VC3D as `umbilicus.json` (copy it into the volume folder) or give it to the spiral fit.

## Checks and controls

The frozen test of 22 October 2026 (evidence: [`docs/evidence/2026-10-22-umbilicus-windpolish/`](../evidence/2026-10-22-umbilicus-windpolish/README.md)) polished the Center Finder's lines on ten fresh 1.2 m scans, then scored every line by winding coverage at 24 slices per scan that the polish never read, against villa's `vc_gen_umbilicus` run on those slices. Polished: **BETTER**, pooled median +0.084 wraps (95% interval +0.028 to +0.169), deeper on 8 of 10 scans. Unpolished: WORSE, -0.330 wraps, 10 of 10 lost. Controls: the scan center scored -5.57 wraps and a 3 mm ring round villa's point -2.40 (interval -2.94 to -1.82), so the check sees a 3 mm miss. The verdict could have read WORSE, as the unpolished line did.

Each run records how far the polish moved the line and the coverage it gained (`median_moved_mm`, `median_gain_wraps`), so a polish that moved nothing shows a move of 0.

Claim label: Model output, measured against villa's predicted sheets; not the true axis.

## Commands and options

### `python -m kit axispolish`

```text
usage: python -m kit axispolish [-h] --out OUT [--grids GRIDS]
                                [--scroll SCROLL] [--every EVERY]
                                [--voxel-um VOXEL_UM] [--cache CACHE]
                                [--verbose] [--json]
                                LINE.json
```

| Option | Default | Meaning |
| --- | --- | --- |
| `LINE.json` | required | A center line in the published format: `control_points` of `x`, `y`, `z` in level-0 voxels, and `metadata` with `voxelsize_um` and `volume` |
| `--out` | required | Where to write the polished line |
| `--grids` | none (found on the bucket) | The scan's level-0 normal-grid folder or URL, holding `xy/NNNNNN.grid` |
| `--scroll` | none (from `metadata.source_volume`) | The scroll id, used to find the grids |
| `--every` | `100` | Polish one slice every this many; the test read its lines at most 100 slices from a polished slice |
| `--voxel-um` | none (from the metadata) | Voxel size in micrometres, when the line names none |
| `--cache` | none | Keep downloaded grid files here, so a rerun fetches nothing |
| `--verbose` | off | Print each slice's move on stderr |
| `--json` | off | Print the summary as JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `polish_file(line, out, grids=None, scroll=None, every=100, voxel_um=None, cache=None, segs_at=None, log=None)` | Summary dict | `PolishError` | The command's work; `segs_at` replaces the grids (tests) |
| `polish_line(guess, heights, segs_at, voxel_um, rule=RULE, log=None)` | `(line or None, records)` | `PolishError` without numpy | `guess` is `[(z, y, x)]` sorted by z; `segs_at(z)` gives segments or None |
| `polish_point(segs, guess, voxel_um, rule=RULE)` | `((x, y), coverage, guess_coverage)` | `PolishError` without numpy | One slice |
| `coverage_many(segs, pts, use_numba=True)` | Float array of wraps | `PolishError` without numpy | `windcheck.coverage` at each point |
| `disc(centre, radius, step)` | `(N, 2)` array | `PolishError` without numpy | Square grid clipped to a disc, the center included |
| `heights(guess, every, z_range=None)` | List of slices | None | Multiples of `every` inside the line's z span and `z_range` |
| `grid_source(grids, cache=None)` | `segs_at(z)` | None | A missing or unreadable grid gives None |
| `find_grids(scroll, volume)` | URL or None | `OSError` on a network error | The level-0 `.normal-grids` folder of the line's scan |
| `read_grid(source)`, `write_grid(path, lines, bounds)` | `(header, polylines)`, None | `PolishError` | villa's GridStore format, version 3 |
| `load_line(path)` | `(points, metadata)` | `PolishError` | Points sorted by z |
| `centre_at(points, z)` | `(x, y)` | None | Linear between points, constant past the ends |
| `robust_axis(points, window=5, floor=1.0)` | `(kept, dropped)` | None | Repeated-median outlier check along z |
| `build_parser()`, `cmd_axispolish(args)`, `main(argv=None)` | Parser, exit code, exit code | None (refusals print and return 2) | The command line; `kit cli` calls `cmd_axispolish` |

## Inputs

`LINE.json` as above. The kit reads `metadata.voxelsize_um`, `metadata.volume` (its first 14 characters name the scan), `metadata.source_volume` (`SCROLL/volumes/...`) and, when present, `metadata.z_valid` (only slices inside it are polished). Every Center Finder line in the center lines dataset has these. The grids are villa's GridStore files, one per slice, in the same level-0 voxel frame as the line.

## Outputs

The polished line, in the same format: `control_points` (`x`, `y` rounded to 0.01 voxel, `z`), and `metadata` copied from the input with `total_points` updated and `polish` added:

| Field | Type | Meaning |
| --- | --- | --- |
| `rule` | Object | The rule's numbers (version 1) |
| `frozen_rule_sha256` | String | sha256 of the frozen test's whole rule, `71d431b3...` |
| `every`, `grids`, `guess` | Integer, string, string | Slices between polished slices, the grids used, the input file's name |
| `slices`, `polished`, `kept` | Integers | Slices asked for, polished, and kept by the outlier check |
| `median_moved_mm` | Float | Median distance the polish moved the line |
| `median_gain_wraps` | Float | Median coverage gained over the input line's point |
| `label`, `evidence`, `made` | Strings | Claim label, the test it rests on, UTC time |

The summary (printed, or JSON with `--json`) has `out`, `points`, `seconds`, `slices`, `polished`, `median_moved_mm`, `median_gain_wraps` and `grids`.

| Exit code | Meaning |
| --- | --- |
| `0` | The polished line was written |
| `2` | A refusal: bad line, no grids, fewer than 2 polishable slices, bad `--every`; nothing written |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `axispolish: give --grids, or --scroll with a line whose metadata names its volume` | The line names no scan | Pass `--grids`, or `--scroll` with a line whose metadata has `volume` |
| `axispolish: the open-data bucket has no level-0 normal grids for SCROLL VOLUME` | No `-L0-....normal-grids` folder for that scan | Use the line unpolished |
| `axispolish: fewer than 2 of N slices could be polished (no grid, or under 500 traced segments)` | Grids missing or too thin at nearly every slice | Check the grids folder; use the line unpolished |
| `axispolish: give --voxel-um: the line's metadata names no voxelsize_um` | No voxel size | Pass `--voxel-um` |
| `axispolish: PATH: not a center line in the published format (control_points of x, y, z): ...` | Not `control_points` of `x`, `y`, `z` | Give the published format |
| `axispolish: the coverage polish needs numpy: python -m pip install numpy` | numpy missing | Install it |
| `axispolish: PATH: a line needs at least 2 finite control points` | Fewer than two usable points | Give a whole line |
| `axispolish: --every is a whole number of slices, at least 1` | `--every 0` or less | Use the default 100 |
| `grid file shorter than its header`, `not a GridStore file (magic ...)` | A truncated or wrong file in the grids folder | Delete it from `--cache` and run again; a slice whose grid cannot be read is skipped |
| `GridStore version N is newer than 3` | villa changed the grid format | Update Scrolls, or report it |
| `a polyline step does not fit in int8` | `write_grid` was given a polyline with a jump over 127 voxels (tests only) | Split the polyline |

## How it works

Coverage sums the absolute angle each traced segment subtends at a point and divides by a full turn ([windcheck](windcheck.md)); a segment within 0.5 voxels of the point is left out. On each polished slice: a grid of 0.4 mm over the 8 mm disc round the guess finds the basin, a grid of 0.05 mm within 0.5 mm of the coarse best finds its top, and the highest coverage is kept (`RULE` in `kit/axispolish.py`). A slice with fewer than 500 traced segments is skipped. The polished points go through `robust_axis` (window 5): each is compared with a repeated-median line through its 5 nearest neighbors in z and dropped when farther than the median distance plus 4 robust deviations. The numbers are rule version 1 of the frozen test; `tests/test_axispolish.py` pins the frozen code's outputs.

## Cost and time

About 1,575 coverage evaluations per slice. A 14,000-slice scan polished every 100 slices is 140 slices: about 3 to 4 minutes with numba or about 14 minutes with numpy alone on 4 cores, plus fetching about 0.3 MB of grid per slice (Interpretation from the timings above; PHerc0175A's 91 slices took 127 s with numba, 135 s including the grid fetch, 24 Oct 2026). It rents nothing.

## For agents

- **Command:** `python -m kit axispolish LINE.json --out OUT.json --cache DIR --json`
- **Parse:** `polished` against `slices`, `median_moved_mm`, `median_gain_wraps`; the file's `metadata.polish` holds the same.
- **Rerun:** Deterministic for the same line and grids; it overwrites `--out`.
- **Success:** Exit 0 and `polished` close to `slices`.
- **Not a pass:** A line polished on grids of another scan or level, a polished person's line, or citing the BETTER verdict for any line other than the Center Finder's.
- **Go-ahead:** Nothing.
- **Never:** Call the polished line the true axis, or tune the rule on the ten test scans (they are spent for coverage).

## Tests

```bash
python -m unittest tests.test_axispolish -q
```

They pin the rule and the frozen code's outputs on synthetic spirals, check coverage equal to windcheck with and without numba, the grid reader and writer, refusals, finding the level-0 grids in a bucket listing, and the command moving an offset line back into a planted spiral. All synthetic; no network.

## History

- 2026-10-24: ported to public Scrolls as `kit axispolish` on top of `81e5ead`, the polish of the private test of 22 October 2026 with the same rule.

## Related

- [windcheck](windcheck.md): the coverage arithmetic.
- [centerline](centerline.md): gets a scroll's center line into a VC3D project.
- [umbilicus](umbilicus.md): the Center Finder.
- [Polish test evidence](../evidence/2026-10-22-umbilicus-windpolish/README.md).
