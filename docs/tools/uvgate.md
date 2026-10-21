# uvgate: check that a flattened sheet's UV triangles do not overlap

`python -m kit uvgate` checks a flattened sheet's UV triangles: it fails on any positive-area overlap between two triangles, on too little summed area and, with `--mesh`, on a sheet that is not one counterclockwise piece. `scripts/bench_uvgate.py` runs and times it on an OBJ's texture coordinates.

| Field | Value |
| --- | --- |
| Id | `uvgate` |
| Status | Current |
| Kind | kit command, kit module, script |
| Area | Surfaces and tracing |
| Run | `python -m kit uvgate`, `python scripts/bench_uvgate.py`, `from kit import uvgate, meshgate` |
| Code | `kit/uvgate.py`, `kit/uvgate_cli.py`, `kit/meshgate.py`, `scripts/bench_uvgate.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_uvgate.py`, `tests/test_meshgate.py`, `tests/test_uvgate_cli.py`, `tests/test_uvgate_fast.py`, `tests/test_bench_uvgate_obj.py` |
| Needs | Python 3 (run here on 3.13.16; the Mac measurements used 3.14.8). `kit uvgate` needs only the standard library; with numpy installed (2.5.3 here) the overlap check uses a spatial grid, and without it the exact all-pairs path, whose work grows with the square of the triangle count. `scripts/bench_uvgate.py` needs numpy; it records tifffile's version when tifffile is installed and `null` otherwise. No villa, VC3D or scan data |
| Runs on | Any CPU. On Chase's Mac (M1 Pro) the grid path checked the released PHerc0139 w039 flattened OBJ (193,772 triangles) in a median 1.0 s of gate time; on a 4-CPU Linux cloud session `kit uvgate --overlap-only --mesh` on about one million synthetic triangles took 33 to 38 s, most of it reading JSON and the pure-Python mesh check (both 2026-10-13, [log](../logs/2026-10-13-uvgate-fast.md)) |
| Network | None |
| Writes | `kit uvgate`: nothing (prints one JSON object). `scripts/bench_uvgate.py --output FILE`: that JSON receipt, written as `FILE.PID.tmp` and renamed into place, with parent folders created |
| Go-ahead | Not needed: it reads local files on the CPU. Results on a target-scroll mesh stay private (the no-disclosure rule, hard rule 1) |
| Released | Public `main` since 2026-10-21; a line of the Scrolls kit entry in the README's "Released tools", id `uvgate` |
| Guide | [UV overlap gate](../uvgate.md), [speed and parity log](../logs/2026-10-13-uvgate-fast.md) |
| Checked | 2026-10-21 against commit `4e2e71e` |

## What it does

A flattening gives every triangle of a traced sheet a 2D position, its UV (parameter-domain) coordinates; a render then paints the scan along the sheet into that 2D layout. If two triangles land on the same UV area, two places on the sheet compete for the same output pixels, and a sheet that should cover its source area but does not leaves part of it unrendered. `uvgate` checks the supplied UV coordinates for both, and optionally checks that they form one clean piece:

- **Overlap** (`uv_overlap_gate`): fails when any two triangles share interior area above `abs_eps` (1e-12 in squared UV units; fixed in the command, a parameter in Python and the benchmark), and fails when no triangle has positive area. Areas are exact: each candidate pair is clipped in rational (`Fraction`) arithmetic. Triangles that only share an edge or a vertex have zero shared area and pass. Zero-area triangles are counted (`degenerate`) and left out.
- **Coverage** (`coverage_verdict`): fails when the summed triangle area divided by the source area you give (`--source-area`) is under `--min-fraction` (0.90). Overlapping area is not subtracted, so a folded sheet can pass coverage with a fraction above 1.
- **Mesh** (`mesh_verdict`, `--mesh`): fails unless every triangle is counterclockwise with positive area, the triangles join through shared edges into one piece, no edge is used by three or more triangles, and no directed edge repeats. Corners match only when both coordinates are exactly equal.

The command reads a JSON list of triangles (or a CSV with header `tri,u,v` when the name ends in `.csv`) and prints one verdict. It does not read an OBJ or a tifxyz itself, and nothing in `kit` writes its input format. `scripts/bench_uvgate.py` is the OBJ route: it takes the per-corner texture coordinates of a triangular OBJ (`--obj-uv`), such as villa's `flatten-segment` output, runs the overlap check in a fresh worker process, and prints a receipt with the verdict, timings, peak memory and hashes of the OBJ, the triangle array and the code. It runs the overlap check only, not coverage or the mesh check.

Why it exists (Community report, checked 2026-10-21): the community tracing pipeline ScrollFiesta ([Hob3rMallow/scrollfiesta_public](https://github.com/Hob3rMallow/scrollfiesta_public/tree/bce8a65f97652316efb084171a17d2f1f8d3ae1a), commit bce8a65 of 30 September 2026) has an acceptance gate, `ribbon_verdict`, that counts lattice cells covered twice by vertex position but does not measure triangle interior overlap area, and the sheet stage of its `sheet_assemble` returns 0 even when `ribbon_verdict`'s gates fail (read in `src/tools/ribbon_verdict.c` and `src/tools/sheet_assemble.c` at that commit). `uvgate` measures the overlap area itself and fails by exit code.

`uvgate` does not look at 3D positions, so it says nothing about 3D self-intersection, sheet switches or which papyrus sheet the surface follows. It does not measure distortion, tears or winding, and a pass is no evidence about ink: an ink map rendered on a sheet that passes is still model output, not a reading.

### Who calls it

Nothing else in `kit` calls it. `scripts/bench_uvgate.py` is its only caller in the repository.

## When to use it

- Before rendering on a flattening (villa's `flatten-segment` output or any OBJ with texture coordinates): run `scripts/bench_uvgate.py --obj-uv MESH.obj --triangles all --collect-pairs` to list every overlapping pair in the OBJ's own UV units.
- When you build a sheet in UV yourself (several pieces laid out side by side): write its triangles as JSON or CSV and run `python -m kit uvgate PATH --source-area AREA --mesh`, so overlaps, missing area and stray pieces all fail.
- When you change the gate or meet new UV: run the grid path against `--method reference` on 2,000 or fewer triangles with `--collect-pairs`; the verdicts must match.

Do not use it:

- To find sheet switches or crossings of a traced surface in 3D: it never reads 3D positions.
- To check relative winding counts between pieces: use [windconsistency](windconsistency.md).
- To judge ink: use [auc](auc.md) against labels with the reversed control.
- On an OBJ with texture seams together with `--mesh`: each seam-bounded island is its own piece, so the mesh check fails by design. Use the overlap and coverage checks alone there.

## Quick start

```bash
mkdir -p WORK
printf '[[[0,0],[1,0],[1,1]],[[0,0],[1,1],[0,1]]]\n' > WORK/square.json
python -m kit uvgate WORK/square.json --source-area 1 --mesh; echo "exit $?"
printf '[[[0,0],[1,0],[1,1]],[[0,0],[1,1],[0,1]],[[0.2,0.1],[0.9,0.1],[0.9,0.8]]]\n' > WORK/folded.json
python -m kit uvgate WORK/folded.json --source-area 1; echo "exit $?"
```

`WORK` is any scratch folder. The first file is a unit square split into two triangles; the second adds a third triangle inside the first one, the control that must fail. On 2026-10-21 (shortened):

```
{"pass": true, "overlap": {"pass": true, "pairs": 0, "degenerate": 0, "witness": null, ...}, "coverage": {"pass": true, "fraction": 1.0, "min_fraction": 0.9, ...}, "mesh": {"pass": true, "components": 1, "nonmanifold": 0, "same_dir": 0, "cw": 0, "ccw": 2, "degenerate": 0, ...}}
exit 0
{"pass": false, "overlap": {"pass": false, "pairs": 1, "degenerate": 0, "witness": [0, 2, 0.24500000000000002], ...}, "coverage": {"pass": true, "fraction": 1.245, "min_fraction": 0.9, ...}}
exit 1
```

It worked when the square exits 0 with `pass` true and the folded copy exits 1 with `overlap.pairs` 1 and the witness `[0, 2, 0.245]` (triangles 0 and 2 share 0.245 square units, the whole inner triangle). Coverage passes on the folded copy at 1.245 because overlaps are counted twice; only the overlap check catches the fold.

## Checks and controls

**A planted overlap must fail.** Append a copy of one face, or a face moved inside another, and the overlap check must report that pair. The benchmark's control appends source face 0 after the first 800 faces of the released PHerc0139 w039 flattened OBJ: both the grid and the reference path report exactly pair `[0, 800]` (witness area 199.30 squared UV units), while the unmodified mesh passes ([log](../logs/2026-10-13-uvgate-fast.md), 2026-10-13). Rerun on 2026-10-16 on a synthetic 20 x 20 OBJ grid (800 faces) plus one moved face: grid path `pass` false, `pairs` 1, `overlapping_pairs` `[[0, 800]]`. On a jittered 100 x 100 grid (20,000 triangles) with three faces copied 0.004 units off their originals, `kit uvgate --mesh` failed with 11 overlapping pairs and 4 components; the unmodified grid passed with 0 pairs and 1 component. `tests/test_bench_uvgate_obj.py` runs the same control end to end on a two-triangle OBJ.

**The fast path must match the exact reference.** `--method reference` compares every pair with exact clipping. On the 800-face prefix and seeded random 800-face subsets (seeds 17, 29, 41) of the released w039 mesh, and on the duplicate control, the grid and reference paths returned identical verdicts, sorted pair lists and input hashes; twelve synthetic meshes of 800 to 803 faces with 0 to 16 overlapping pairs also matched ([log](../logs/2026-10-13-uvgate-fast.md)). The 18 tests in `tests/test_uvgate_fast.py` compare the two on edge cases (shared edges, slivers, cell boundaries, exact fractions, huge integers, subnormal numbers). Rerun on 2026-10-16: 800 synthetic faces gave the same verdict (pass, 0 pairs) on both paths.

**Pieces.** Two separate squares pass the overlap check and fail `--mesh` with `components` 2. Without `--mesh`, a sheet in several pieces passes.

**What cannot fail.** Coverage cannot catch an overlap. A pass on JSON that did not come from the real flattening checks only that JSON.

Claim label: Model output, for every verdict on real UV (a geometric check of the supplied coordinates, never evidence about ink); the timings and parity results are Sourced fact from the [measurement log](../logs/2026-10-13-uvgate-fast.md) and this page's reruns (the per-run receipts are not published); the ScrollFiesta gap is a Community report, checked against its source on 2026-10-21.

## Commands and options

### `python -m kit uvgate`

```
usage: python -m kit uvgate [-h] --source-area SOURCE_AREA
                            [--min-fraction MIN_FRACTION] [--overlap-only]
                            [--mesh]
                            PATH
```

| Option | Default | Meaning |
| --- | --- | --- |
| `PATH` | required | JSON file: a list of triangles, each three `[u, v]` pairs. A name ending in `.csv` (any case) is read as CSV with header `tri,u,v` |
| `--source-area SOURCE_AREA` | required | The area the sheet should cover, in the same squared units as the UV. Required even with `--overlap-only`, where it is ignored |
| `--min-fraction MIN_FRACTION` | `0.9` | Coverage bar: summed triangle area over source area must be at least this. Not range-checked; the 0.90 default has no source in the code |
| `--overlap-only` | off | Run only the overlap check; the printed object is then the overlap verdict itself, with no `coverage` |
| `--mesh` | off | Also run the mesh check (one counterclockwise piece, no edge used three times, no repeated directed edge) and require it to pass |

The overlap threshold `abs_eps` is fixed at 1e-12 here and the method is `auto`; use the Python API or the benchmark to change them.

### `python scripts/bench_uvgate.py`

```
usage: bench_uvgate.py [-h] --obj-uv OBJ_UV [--triangles TRIANGLES]
                       [--selection {prefix,random}] [--seed SEED]
                       [--abs-eps ABS_EPS] [--timeout-seconds TIMEOUT_SECONDS]
                       [--method {auto,grid,reference}] [--collect-pairs]
                       [--output OUTPUT]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--obj-uv OBJ_UV` | required | Local triangular OBJ. Each face corner's texture index gives its UV in original units; seams, face order and zero-area faces are kept, and materials and images are never opened |
| `--triangles TRIANGLES` | `1000000` | How many triangles to take, or `all`. The default fails on any input with fewer triangles, so pass `all` for a whole mesh |
| `--selection {prefix,random}` | `prefix` | `prefix`: the first faces in file order. `random`: a seeded sample, kept in original face order |
| `--seed SEED` | `0` | Seed for `--selection random` |
| `--abs-eps ABS_EPS` | `1e-12` | Overlap area threshold in squared UV units; finite and nonnegative |
| `--timeout-seconds TIMEOUT_SECONDS` | `300` | Limit on the whole worker process; on timeout nothing is written |
| `--method {auto,grid,reference}` | `grid` | `grid` needs numpy; `auto` uses the grid when numpy imports; `reference` is the exact all-pairs check, refused above 2,000 triangles |
| `--collect-pairs` | off | Add `overlapping_pairs`, every hit as sorted `[i, j]` original face indices, to the verdict |
| `--output OUTPUT` | none | Also write the receipt here (atomically); the receipt always goes to stdout |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `UvGateError()` | An exception (a `ValueError`) | Nothing | Raised for bad triangles, points, CSV text and a nonpositive source area |
| `uv_overlap_gate(triangles, abs_eps=1e-12, *, method='auto', collect_pairs=False)` | dict: `pass`, `pairs`, `degenerate`, `witness` (`(i, j, area)` or None), `rule`, and `overlapping_pairs` when `collect_pairs` | `ValueError` for an unknown method; `ImportError` for `method='grid'` without numpy; `UvGateError` for a triangle without 3 points or a point without 2 values; `TypeError` or `ValueError` for values `Fraction` cannot take | Pass when some triangle has area and no pair overlaps above `abs_eps`. `triangles` is any iterable of three (u, v) points; ints, floats, `Fraction`s and numpy arrays work. Unusual types, nonfinite values, huge coordinates or a negative `abs_eps` drop to the exact reference. `reference` is quadratic: keep it to small inputs |
| `triangle_area(tri)` | float, the absolute area | `ValueError` or `TypeError` when `tri` is not three (x, y) points | Plain float arithmetic, unlike the overlap check |
| `coverage_fraction(triangles, source_area)` | float | `UvGateError` when `source_area` is not positive | Sum of triangle areas divided by `source_area`; overlaps counted twice |
| `coverage_verdict(triangles, source_area, min_fraction=0.9)` | dict: `pass`, `fraction`, `min_fraction`, `rule` | As `coverage_fraction` | Pass only when the fraction is at least `min_fraction` |
| `sheet_verdict(triangles, source_area, min_fraction=0.9, abs_eps=1e-12)` | dict: `pass`, `overlap`, `coverage` | As `uv_overlap_gate` and `coverage_fraction` | Pass only when both the overlap check (method `auto`) and the coverage check pass |
| `load_uv_csv(text: str)` | list of triangles, each a tuple of three `(u, v)` float pairs | `UvGateError`: `bad header`, `row must have tri, u, and v`, `non-numeric coordinate`, `triangle must have 3 points` | Rows sharing a `tri` id form one triangle, in first-seen order; blank rows skipped; empty or header-only text gives `[]` |
| `build_parser(parser=None)` | `argparse.ArgumentParser` | Nothing | In `kit/uvgate_cli.py`; `kit/cli.py` calls it to build `python -m kit uvgate` |
| `cmd_uvgate(args)` | int: 0 pass, 1 fail, 2 error | Nothing it catches: `OSError`, JSON errors, `UvGateError`, `TypeError` and `ValueError` become `uvgate: MESSAGE` on stderr and 2 | Prints one verdict JSON object |
| `MeshGateError()` | An exception (a `ValueError`) | Nothing | In `kit/meshgate.py`; raised for a triangle without 3 points or a point without 2 values |
| `mesh_verdict(triangles)` | dict: `pass`, `components`, `nonmanifold`, `same_dir`, `cw`, `ccw`, `degenerate`, `rule` | `MeshGateError`; `TypeError` or `ValueError` for values `float` cannot take | Fail unless the sheet is one counterclockwise piece with no bad edges. An empty list fails with every count 0 |
| `bench_uvgate.load_obj_uv(path, triangles=None, selection='prefix', seed=0)` | `(array, report)`: float64 array of shape (N, 3, 2) and a provenance dict | `ValueError` for every refused OBJ (message prefixed `NAME:LINE:` for a bad line); `RuntimeError` when the file changed while loading; `OSError` for a missing file | Script function; load it by path with `importlib`, as the tests do. `triangles=None` takes every face |
| `bench_uvgate.benchmark(args)` | dict, the receipt without the whole-process fields | `ValueError` or `RuntimeError` for refused inputs or changed source files | Script function; times the gate in the current process |

## Inputs

**`PATH` for `kit uvgate`.** JSON: a list of triangles, each a list of three `[u, v]` number pairs, for example `[[[0,0],[1,0],[1,1]], ...]`. Any file whose name does not end in `.csv` is parsed as JSON. CSV (name ends in `.csv`, any case): first row exactly `tri,u,v` (cells trimmed), then one row per corner; rows with the same `tri` id form one triangle, in first-seen order; blank rows are skipped and cells after `v` ignored. An empty file, an empty list or a header-only CSV fails the overlap check (no triangle with area). The whole file is read into memory: a JSON of about one million triangles was 124 MB and the run peaked at 1,899 MB ([log](../logs/2026-10-13-uvgate-fast.md)).

**Units and orientation.** UV units are whatever the flattening used; `--source-area` must be in the same units squared, and `abs_eps` (1e-12) is in those units too, so very small UV ranges deserve a thought about the threshold. The mesh check calls a triangle counterclockwise when its signed area `(b - a) x (c - a)` is positive, which is counterclockwise with `v` pointing up. Corners join only when their two values are exactly equal as floats.

**`--obj-uv` for the benchmark.** A text OBJ: `v` lines need at least three finite numbers; `vt` lines two values, or three with a third of zero; `f` lines exactly three corners, each `v/vt` or `v/vt/vn`. Negative indices count back from the records read so far; positive ones are checked against the final counts. Comments, groups, objects, normals and material lines are skipped. Every face line is checked before a subset is chosen. The UV values are used as they are, with no rescaling. The released PHerc0139 flattened OBJs (for example `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/segments/20260302000000-w039_2026030210/mesh/intermediate/20260302000000-w039_2026030210_flattened.obj`, 36.9 MB) are in this form.

## Outputs

`kit uvgate` prints one JSON object on one line. Without `--overlap-only`:

| Field | Type | Meaning |
| --- | --- | --- |
| `pass` | bool | The verdict: overlap and coverage pass, and the mesh check too with `--mesh` |
| `overlap.pass` | bool | At least one triangle has positive area and no pair overlaps above `abs_eps` |
| `overlap.pairs` | int | Number of triangle pairs whose shared interior area is above `abs_eps` |
| `overlap.degenerate` | int | Zero-area triangles, left out of the overlap check |
| `overlap.witness` | `[i, j, area]` or null | The overlapping pair with the lowest indices (input order, from 0) and its shared area in squared UV units |
| `overlap.rule` | string | The rule applied; it says "fail when no triangle has positive area" when nothing had area |
| `coverage.pass` | bool | `fraction` is at least `min_fraction` |
| `coverage.fraction` | float | Summed triangle area over `--source-area`; overlapping area counts twice |
| `coverage.min_fraction` | float | The bar used |
| `coverage.rule` | string | The rule in words |
| `mesh.pass` | bool | Only with `--mesh`: every count below is clean and `components` is 1 |
| `mesh.components` | int | Pieces joined through shared undirected edges |
| `mesh.nonmanifold` | int | Undirected edges used by three or more triangles |
| `mesh.same_dir` | int | Directed edges used twice or more (two faces on the same side of an edge, or a duplicated face) |
| `mesh.cw`, `mesh.ccw`, `mesh.degenerate` | int | Clockwise, counterclockwise and zero-area triangles |
| `mesh.rule` | string | The rule in words |

With `--overlap-only` the object is the overlap verdict itself (`pass`, `pairs`, `degenerate`, `witness`, `rule`), plus `mesh` with `--mesh`.

| Exit code | Meaning |
| --- | --- |
| `0` | The verdict passed |
| `1` | The verdict failed |
| `2` | A usage error, an unreadable or malformed file, a bad triangle or point, or a source area that is not positive (message on stderr, nothing on stdout) |

`scripts/bench_uvgate.py` prints an indented JSON receipt and writes the same to `--output`:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | int | 1 |
| `source` | object | Provenance of the triangles: `obj`, `domain`, `limitation`, `selection`, `seed`, `vertices`, `uv_vertices`, `full_triangles`, `triangles`, `uv_bounds`, `face_order`, `units`, `array_dtype`, `array_bytes`, `triangles_sha256`, `face_indices_sha256`, `files` (size and SHA-256 of the OBJ) |
| `method`, `abs_eps`, `collect_pairs` | string, float, bool | The settings used |
| `verdict` | object | The `uv_overlap_gate` result, with `overlapping_pairs` when `--collect-pairs` |
| `preparation_wall_seconds` | float | Loading and building the triangle array, in s |
| `gate_wall_seconds`, `gate_cpu_seconds` | float | The overlap check alone, wall and process CPU time, in s |
| `worker_cpu_seconds_to_receipt` | float | The worker's user plus system CPU time, in s |
| `worker_peak_rss_bytes` | int or null | The worker's whole-process peak resident memory in bytes (null on systems other than Linux and macOS) |
| `memory_scope` | string | What the memory figure includes |
| `implementation_sha256` | object | SHA-256 of `kit/uvgate.py` and `scripts/bench_uvgate.py` |
| `runtime` | object | `python`, `numpy`, `tifffile` (null when not installed), `platform`, `machine`, `logical_cpu_count` |
| `whole_process_wall_seconds` | float | Worker start to exit, in s |
| `whole_process_wall_scope` | string | What that time includes |

| Exit code | Meaning (benchmark) |
| --- | --- |
| `0` | A receipt was printed (and written), whatever the verdict: read `verdict.pass` |
| `1` | The worker hit an error it does not catch, such as a missing OBJ file; its traceback is on stderr |
| `2` | A usage error, a refused input, a source file that changed during the run, or the timeout; nothing written |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `error: the following arguments are required: --source-area` | `--source-area` is required even with `--overlap-only` | Pass any positive number with `--overlap-only`; it is ignored there |
| `error: the following arguments are required: --obj-uv` (benchmark) | The benchmark reads only OBJ texture coordinates | Pass `--obj-uv MESH.obj` |
| `uvgate: [Errno 2] No such file or directory: ...`, exit 2 | The path does not exist | Fix the path |
| `uvgate: Expecting value: line 1 column 1 (char 0)`, exit 2 | The file is not JSON; a CSV whose name does not end in `.csv` is parsed as JSON | Rename a CSV to end in `.csv`, or write JSON |
| `uvgate: bad header`, exit 2 | The CSV's first row is not `tri,u,v` | Write the header exactly `tri,u,v` |
| `row must have tri, u, and v` | A CSV row has fewer than three cells | Fix that row |
| `non-numeric coordinate` | A CSV `u` or `v` cell is not a number | Fix the cell |
| `triangle must have 3 points` | A JSON triangle with other than three corners, a CSV id with other than three rows, or JSON that is not a list of triangles (an object is read by its keys) | Give every triangle exactly three corners; triangulate polygons first |
| `point must be (x, y)` | A corner with other than two values | Write each corner as `[u, v]` |
| `source_area must be positive` | `--source-area` is 0 or negative | Pass the real source area |
| `method must be auto, grid, or reference` | `uv_overlap_gate` was called with another `method` (Python API only) | Use one of the three |
| `ModuleNotFoundError: No module named 'numpy'` from `uv_overlap_gate` | `method='grid'` without numpy | Install numpy, or use `auto` or `reference` |
| Coverage passes with `fraction` above 1 | Overlapping area is counted twice | Read `overlap.pass`; coverage never catches an overlap |
| `mesh.components` above 1 on a real flattening | The UV has seams (islands) or corners written at different precision | Expected with seams: drop `--mesh` there, or check each island alone |
| `quadratic reference is limited to 2000 triangles` | `--method reference` with more than 2,000 triangles, or `all` | Use `--triangles 2000` or fewer for reference runs, and `grid` for whole meshes |
| `triangles, but OBJ has` (as `requested 1000000 triangles, but OBJ has 193772`) | `--triangles` (default 1,000,000) is more than the OBJ's faces | Pass `--triangles all` or a smaller count |
| `triangles must be a positive integer, or all` | A bad count passed to `load_obj_uv` from Python | Pass a positive int or None |
| `expected a positive integer or all` | `--triangles` is 0 or negative | Pass a positive count or `all` |
| `expected an integer or all` | `--triangles` is not a number | Pass a positive count or `all` |
| `selection must be prefix or random` | `load_obj_uv` was called with another selection (Python only; the command limits the choices) | Use `prefix` or `random` |
| `--abs-eps must be finite and nonnegative` | A negative, infinite or NaN threshold | Pass a finite value of 0 or more |
| `--timeout-seconds must be finite and positive` | A zero, negative, infinite or NaN timeout | Pass a positive number of seconds |
| `worker exceeded N seconds; no result written` (`seconds; no result written`) | The worker ran past `--timeout-seconds` (300 by default) | Raise the timeout, use `--method grid`, or check fewer triangles; a CPU run expected to take over 10 minutes on Chase's Mac goes to Modal with a spec (hard rule 11) |
| `source changed during benchmark: FILE` | `kit/uvgate.py` or the script was edited during the run, so the timing does not match the hashed code | Rerun with the files left alone |
| `OBJ needs texture coordinates and triangular faces` | The OBJ has no `vt` lines or no faces | Use an OBJ with texture coordinates (a flattened OBJ) |
| `OBJ face index is out of range` | A face points past the last `v` or `vt` | Fix or re-export the OBJ |
| `OBJ indices cannot be zero` | A face index is 0 (OBJ counts from 1) | Re-export the OBJ |
| `relative index is out of range` | A negative index points before the first record | Re-export the OBJ |
| `vertex needs three finite coordinates` | A `v` line has fewer than three numbers or a nonfinite one | Fix that line (the message starts `NAME.obj:LINE:`) |
| `texture coordinate needs two values (optional third zero)` | A `vt` line with other than two or three values | Fix that line |
| `texture coordinates must be finite and two-dimensional` | A `vt` value is nonfinite, or a third value is not zero | Fix that line; 3D texture coordinates are not supported |
| `only triangular OBJ faces are supported` | A face with other than three corners | Triangulate the OBJ first |
| `each face corner needs vertex/texture indices` | A corner without a texture index (`f 1 2 3` or `f 1//1 ...`) | Use an OBJ whose faces carry texture indices |
| `OBJ changed while loading` | The file's size or hash changed between the start and end of loading | Rerun when nothing is writing the file |
| `FileNotFoundError` traceback, exit 1 (benchmark) | The `--obj-uv` file does not exist; the worker does not catch it | Fix the path |

## How it works

1. **Read.** `kit uvgate` reads the whole file and parses JSON, or CSV through `load_uv_csv` when the name ends in `.csv`.
2. **Choose a path.** `auto` uses the grid when numpy imports, the triangles form a finite float64 or integer array of shape (N, 3, 2) (integers within 2^53 in size, and floats from a Python list below 2^53) and `abs_eps` is not negative; anything else (fractions, strings, NaN, other float widths, huge values, a negative threshold) takes the exact reference, so the answer never depends on a lossy conversion.
3. **Orient.** Each triangle's orientation is computed in floats with an error bound (Shewchuk's first-stage `orient2d` bound, (3 + 16u)u with u = 2^-53, coded as `3.3306690738754716e-16`, plus a floor of 1e-300); signs inside the bound are recomputed exactly with `Fraction`. Zero-area triangles are counted as degenerate and dropped; clockwise ones are reversed in a private copy. Integer coordinates up to 2^25 are exact in floats and skip the bound.
4. **Grid.** The cell size is a power of two near the median triangle width (at least the largest coordinate times 2^-48, so cell indices stay exact), doubled until no triangle spans more than 4,096 cells and the cell memberships total at most 8 per triangle; exponents outside -400 to 400 fall back to the reference. Memberships are sorted by cell.
5. **Candidates.** Pairs of triangles sharing a cell are taken in batches of 65,536. A pair is handled only in its lexicographically first shared cell, so a large triangle cannot count a hit twice. Pairs whose bounding boxes do not overlap with positive width are dropped, then pairs that one edge of either triangle provably separates (only reliable signs are used to drop).
6. **Exact area.** Each remaining pair is clipped exactly (Sutherland-Hodgman against the three edges of the other triangle, in `Fraction` arithmetic) and its area compared with `abs_eps` as a `Fraction`. A hit counts toward `pairs`; the witness is the hit with the lowest index pair. The reference path does the same for every pair of positive-area triangles.
7. **Coverage.** The sum of float triangle areas divided by `--source-area`, compared with `--min-fraction`.
8. **Mesh check.** Corners become float pairs; each triangle's signed area gives cw, ccw or degenerate; edges are counted by exact corner pairs, directed and undirected; a union-find over shared undirected edges counts pieces.
9. **Benchmark.** The parent process starts `scripts/bench_uvgate.py ARGS --worker` with the timeout. The worker loads the OBJ's texture coordinates, hashes the two code files, times only the overlap check, checks that the code hashes did not change, and prints the receipt; the parent adds the whole-process time and writes `--output` through a temporary file.

Constants: `abs_eps` 1e-12, `min_fraction` 0.90, at most 4,096 cells per triangle and 8 memberships per triangle, batches of 65,536 pairs (`kit/uvgate.py`); `REFERENCE_LIMIT` 2,000, default `--triangles` 1,000,000, `--timeout-seconds` 300, `--method` `grid` (`scripts/bench_uvgate.py`).

## Cost and time

| Run | Input | Gate time | Process time | Peak RSS | Machine and source |
| --- | --- | --- | --- | --- | --- |
| Reference, 800 faces | w039 flattened OBJ prefix | 17.25 s (median of 3) | 18.44 s | 61.0 MB | Mac (M1 Pro), 2026-10-13, [log](../logs/2026-10-13-uvgate-fast.md) |
| Grid, 800 faces | same prefix | 0.0104 s | 1.12 s | 62.3 MB | same |
| Grid, 193,772 | full w039 flattened OBJ | 1.00 s | 2.20 s | 165.7 MB | same |
| `kit uvgate --overlap-only --mesh` | 999,698 synthetic jittered triangles (999,723 with 25 planted overlaps) | 12.1 s overlap, 18.4 s mesh check (10.4 s and 19.2 s) | 38.3 s (32.8 s) | 1,899 MB | 4-CPU Linux cloud session, 2026-10-13, same log (single runs) |
| `kit uvgate --mesh` | 20,000 synthetic jittered triangles | Not measured | 2.3 to 2.7 s wall, 1.0 s CPU | Not measured | 2026-10-16, 4-core Xeon cloud container shared with other jobs |
| Benchmark, grid | 801-face synthetic OBJ | 0.038 s | 1.04 s | 40.3 MB | same container |
| Benchmark, reference | 800-face synthetic OBJ | 84.4 s wall, 23.8 s CPU | 85.4 s | 38.9 MB | same container; wall time inflated by the shared machine |

On the w039 800-face prefix the grid path's median gate time is 1,666 times shorter than the exact reference's. The grid path's candidate work is near-linear for similarly sized triangles; dense overlaps or very unequal sizes can still need quadratic work, since the number of overlapping pairs can itself be quadratic. Without numpy every run takes the reference path. A one-million-triangle check of real (not synthetic) UV has not been measured. Everything runs on the CPU and rents nothing; a CPU run expected to take over 10 minutes on Chase's Mac goes to Modal with a spec (hard rule 11).

## For agents

- **Command:** `python -m kit uvgate TRIS.json --source-area AREA --mesh` for a sheet you built; `python scripts/bench_uvgate.py --obj-uv MESH.obj --triangles all --method grid --collect-pairs --output OUT.json` for a flattened OBJ. Both print JSON.
- **Parse:** `kit uvgate`: `pass`, then `overlap.pairs` and `overlap.witness`, `coverage.fraction`, and `mesh.components`, `mesh.nonmanifold`, `mesh.same_dir`, `mesh.cw`. Benchmark: `verdict.pass`, `verdict.pairs`, `verdict.overlapping_pairs`, `source.triangles`, `source.triangles_sha256`, `gate_wall_seconds`.
- **Rerun:** Safe. `kit uvgate` writes nothing; the benchmark's `--output` replaces its file.
- **Success:** `kit uvgate` exit 0 with `pass` true. Benchmark: exit 0 and `verdict.pass` true; exit 0 alone only means a receipt was written.
- **Not a pass:** a benchmark exit 0 with `verdict.pass` false; a coverage pass with overlaps (read `overlap.pass`); a sheet pass without `--mesh` when pieces matter; a pass on JSON that did not come from the real flattening; a grid result on new kinds of UV with no reference comparison on a small sample; any verdict read as evidence about ink.
- **Go-ahead:** Nothing. Verdicts on target-scroll meshes stay in Scrolls-private or ignored local folders.
- **Never:** run the reference path on whole meshes from Python (the benchmark refuses above 2,000 triangles; the API does not); call a pass a reading or evidence of letters; post or publish results on a target-scroll mesh.

## Tests

```bash
python -m unittest tests.test_uvgate tests.test_meshgate tests.test_uvgate_cli tests.test_uvgate_fast tests.test_bench_uvgate_obj -v
```

68 tests (12, 7, 7, 18 and 24), synthetic fixtures only; about 4.5 s here on 2026-10-21. They cover nested, crossing, shared-edge and degenerate triangles, coverage bars and a nonpositive source area, CSV loading and its errors; the mesh check on shared edges, disjoint pieces, three faces on one edge, clockwise and duplicate faces; the command's exit codes on JSON and CSV with and without `--mesh`; grid against reference on every fixture, seeded random meshes, cell boundaries, slivers, exact fractions, huge integers, mixed types, a negative threshold, numpy inputs and the fallback without numpy; 21 OBJ loader cases (texture indices, seams, relative and forward indices, units, sampling, hashes, degenerate and duplicate faces, a file changed during loading, and every refused form); the refusal of a large reference run; a benchmark receipt on a clean and a folded two-triangle OBJ; and one full run of the benchmark command through its fresh worker. Without numpy, `test_uvgate_fast` skips its numpy-input case and the benchmark tests skip. They do not run the timeout or real meshes.

## History

- 2026-10-21: first public release, from public `main` at `4e2e71e`: `kit uvgate`, `kit/meshgate.py`, the OBJ benchmark and the speed log (PHerc0139 w039 and synthetic runs); first written 13 to 16 October 2026.

## Related

- [UV overlap gate guide](../uvgate.md): the Python calls and the benchmark commands.
- [Speed and parity log](../logs/2026-10-13-uvgate-fast.md): every published timing, the parity runs and their limits.
- [windconsistency](windconsistency.md): relative winding counts, released with this tool.
- [auc](auc.md): the ink score against published labels, for questions this geometry check cannot answer.
