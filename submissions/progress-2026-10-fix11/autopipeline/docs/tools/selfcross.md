# selfcross: count where a tifxyz surface passes through itself

Runs villa's self-intersection census on a tifxyz surface, through villa's vc_tifxyz_selfcross or, on builds after villa removed it, through its census kernel compiled here; AutoPipeline's qa stage rejects a trace that crosses itself.

| Field | Value |
| --- | --- |
| Id | `selfcross` |
| Status | Experimental |
| Kind | kit command,kit module,script folder |
| Area | Surfaces and tracing |
| Run | `python -m kit selfcross` |
| Code | `kit/selfcross.py`, `scripts/selfcross` |
| Tests | `tests/test_selfcross.py` |
| Needs | Python 3.11+, numpy. Backend `villa`: a VC3D build with `vc_tifxyz_selfcross` (villa before `e1aa625a6`, 29 Oct 2026). Backend `kernel`: a C++17 compiler (g++ 9 or newer, or clang++ 10 or newer; checked with g++ 13.3) and villa's `vc_tifxyz_selfcross_impl.hpp` at `7154682e1` (fetched by `build`, sha256 checked); no OpenCV |
| Runs on | CPU. The build takes about 10 s; `tests/test_selfcross.py` (17 tests) runs in about 3 s, and the parity run on 51 surfaces of up to 90 x 90 cells in about 2 minutes, mostly starting the AppImage (measured 2026-10-30, cloud container, g++ 13.3) |
| Network | `build` only: `raw.githubusercontent.com` for villa's census header at `7154682e1`, unless `--header` or `KIT_SELFCROSS_HEADER` gives a copy. `run` and `status`: none |
| Writes | `build`: `work/selfcross/` in the kit home (the cached header, `kernel-<key>/selfcross_kernel` and its `build.json`). `run`: the report at `-o` |
| Go-ahead | Not needed |
| Released | AutoPipeline 0.1.11 (`progress-2026-10-fix11`) |
| Checked | 2026-10-30 against commit `2f89ac67` |

## What it does

A traced surface (a tifxyz grid of 3D points) can fold back and pass through itself. A real sheet of papyrus never
does that, however tightly the wraps are packed, so a transverse self-intersection is a tracing defect. villa's
`vc_tifxyz_selfcross` counted them: every pair of non-adjacent triangles, under both ways of splitting each grid quad,
classified as transverse (the interiors pass through each other), coplanar (two sheets pressed flat) or grazing (a
touch within the tolerance). AutoPipeline's qa stage rejects a trace with any transverse contact (`qa.max_selfcross`
0), and region crop, the geometry score and the winding benchmark read the same report.

villa main removed the tool, its census kernel and their tests in `e1aa625a6` (29 Oct 2026, villa #2358), and nothing
on main checks a surface for self-intersections now. So on a build made after that, every trace went to qa with its
self-intersections "not measured" and was rejected. This tool brings the check back as two swappable backends:
`villa` runs `vc_tifxyz_selfcross` when the build has it; `kernel` runs the same census kernel, villa's
`vc_tifxyz_selfcross_impl.hpp` at `7154682e1`, compiled on this machine by `kit selfcross build` with our small
driver. `auto` (the default) takes `villa` when it is there, else `kernel`.

The kernel backend's report is villa's report: the same keys, census rows and contact fields, with its own `tool`,
`backend: "kernel"` and a `kernel` block naming the villa commit and the sha256 of the header and our files. It has no
`--collection` (VC3D point collection) output. It is a count of a geometric defect, not a judgment of whether the trace
followed the right sheet.

License: villa's code is GPL-3.0. The header is fetched at build time and never copied into this repository or any
release; the binary built from it is a GPL-3.0 work and stays on the machine that built it. A Docker image built from the package's Dockerfile holds both, like the VC3D AppImage it already holds, so share such an image only under GPL-3.0. Our driver
(`scripts/selfcross/selfcross_kernel.cpp`) and the stand-in for OpenCV's two types (`scripts/selfcross/shim/`) are
Apache-2.0, like the rest of the package.

## When to use it

- Before AutoPipeline runs on a VC3D build from after `e1aa625a6`: run `python -m kit selfcross build` once, or qa
  rejects every trace as unmeasured.
- To check one tifxyz yourself: `kit selfcross run`.
- To compare the backends: `python -m kit autopipeline swap RUN --stage selfcross --backend kernel`, or `scripts/selfcross/parity.py` on the
  synthetic fixtures.

Do not use it:

- to find where a trace switched to the touching sheet without crossing itself: that is the winding audit
  (`kit meshqa`) and seating (`check_surface`);
- as a reading of ink: it reads only the mesh.

## Quick start

```bash
python -m kit selfcross build
python -m kit selfcross status
python -m kit selfcross run --surface SURFACE.tifxyz -o selfcross.json
```

`SURFACE.tifxyz` is a tifxyz folder (`x.tif`, `y.tif`, `z.tif`, `meta.json`, optional `mask.tif`). Printed on
2026-10-30 in a cloud container (status, then a run on the `driven_through` fixture):

```
villa   missing  vc_tifxyz_selfcross
kernel  found  .../work/selfcross/kernel-8fe74dcc1da8cab0/selfcross_kernel
auto    kernel
diagonal 0: 216 triangles, ... 33 transverse, 0 coplanar, 0 grazing
diagonal 1: 216 triangles, ... 35 transverse, 0 coplanar, 0 grazing
Report written to selfcross.json
Surface has non-adjacent transverse self-intersections: 33 contacts on diagonal 0, 35 on diagonal 1.
```

It worked when the exit code is 0 and the report's `census` has two rows.

## Checks and controls

Parity with villa's own tool. `scripts/selfcross/parity.py` makes 51 synthetic tifxyz surfaces (the 11 named fixtures
of `tests/selfcross_fixtures.py`, one per rule of the census or of VC3D's loader, and 40 seeded crumpled sheets with
folds, holes, z <= 0 rows and masks; 29 of the 51 cross), runs both backends through kit's own resolver, and compares
clean, grid size, parameters, triangles, dropped quads, pairs tested, the three counts on both diagonals, the contact
lists in order, and every contact's penetration, angle and site (to 1e-9). Run on 2026-10-30 against villa's
`vc_tifxyz_selfcross` in the archived Linux AppImage of villa `7154682e1` (VC3D-7154682 2026-10-28, sha256
`93f52efb...`): **0 of 51 surfaces differ**.

Two controls show the comparison can fail. The kernel fed the grid with mask.tif ignored differs on 15 of 51; fed it
with x = -1 cells also invalidated (a rule kit's mesh checks use and VC3D's loader does not) differs on 1 of 51. The
script exits 1 unless every surface matches and both controls differ somewhere.

`tests/test_selfcross.py` compiles the kernel and checks the 11 named fixtures against the counts villa's tool gave
them (`tests/selfcross_fixtures.py`, `VILLA`), and that ignoring the mask changes a count.

Claim label: Model output (of tools) for the parity counts; nothing here is about ink or text. Parity is on synthetic
surfaces only: no real trace was compared.

## Commands and options

### `python -m kit selfcross build`

```
usage: python -m kit selfcross build [-h] [--header HEADER] [--cxx CXX]
                                     [--force] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--header HEADER` | none | a local copy of volume-cartographer/apps/src/vc_tifxyz_selfcross_impl.hpp (else KIT_SELFCROSS_HEADER, the cache, or fetched) |
| `--cxx CXX` | none | the C++17 compiler (default $CXX, c++, g++ or clang++) |
| `--force` | off | rebuild even when a build exists |
| `--json` | off | print the build record as JSON |

### `python -m kit selfcross status`

```
usage: python -m kit selfcross status [-h] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | print the status as JSON |

### `python -m kit selfcross run`

```
usage: python -m kit selfcross run [-h] --surface SURFACE -o OUTPUT
                                   [--backend {auto,villa,kernel}]
                                   [--threads THREADS] [--exclude EXCLUDE]
                                   [--maxedge MAXEDGE] [--cell CELL]
                                   [--fail-on-crossing]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--surface SURFACE` | required | tifxyz folder |
| `--output OUTPUT` | required | report file (.json) |
| `--backend BACKEND` | `auto` | `villa` (vc_tifxyz_selfcross), `kernel`, or `auto` (villa when the build has it, else kernel) |
| `--threads THREADS` | `0` | worker threads; 0 = all cores |
| `--exclude EXCLUDE` | `1` | grid-index adjacency left out (default 1: quads that share a vertex) |
| `--maxedge MAXEDGE` | `60.0` | drop quads with an edge longer than this many voxels (default 60; 0 disables) |
| `--cell CELL` | `40.0` | broad-phase cell in voxels (default 40; changes speed, never the counts) |
| `--fail-on-crossing` | off | exit 3 when a transverse contact is found |

### `scripts/selfcross/parity.py`

```
usage: parity.py [-h] [--random RANDOM] out
```

Needs `VC_APPIMAGE` (or `VC_BIN`) naming a VC3D build that still has `vc_tifxyz_selfcross`, and a built kernel.

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | folder for both backends' reports and `parity.json` |
| `--random RANDOM` | `40` | random crumpled sheets beside the 11 named fixtures |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `SelfcrossError()` | exception | | every refusal of this module |
| `build_root(env=None)` | Path | | `work/selfcross` in the kit home |
| `source_bytes()` | (bytes, bytes) | SelfcrossError (no source folder) | (driver bytes, shim bytes): the two files of ours the kernel binary is built from. |
| `build_key(driver, shim)` | str | | What a kernel binary is built from, as one digest: the header's sha256 and our two files. |
| `build_dir(env=None)` | Path | SelfcrossError | `work/selfcross/kernel-<key>` |
| `header(given=None, env=None, fetch=True, timeout=60)` | (bytes, where) | SelfcrossError (unreadable, unfetchable, wrong sha256) | The census header's bytes, checked against HEADER_SHA256: from `given` or KIT_SELFCROSS_HEADER, else the |
| `find_compiler(cxx=None, env=None)` | path or None | | `$CXX`, `c++`, `g++`, `clang++` |
| `build(cxx=None, given_header=None, force=False, env=None, timeout=600)` | dict | SelfcrossError | Compile the kernel backend into the kit home (work/selfcross/kernel-<key>/). Returns its build record. |
| `kernel_binary(env=None)` | (Path, dict) or (None, str) | | (path, build record) of the kernel backend this machine has, or (None, why not). |
| `villa_has(tools)` | bool | | the build has vc_tifxyz_selfcross |
| `resolve(backend='auto', tools=None, env=None)` | (str, None) or (None, str) | SelfcrossError (unknown backend) | (backend name, None) for the backend that runs, or (None, why none can). |
| `argv(backend, surface, report, tools=None, threads=None, params=None)` | list | SelfcrossError | The command that writes `report` for `surface` with this backend (resolve() picked it). |
| `unavailable_text(why)` | str | | the qa reason's text |
| `load_grid(surface)` | float32 array (rows, cols, 3) | SelfcrossError | The (rows, cols, 3) float32 grid VC3D's load_quad_from_tifxyz gives for a tifxyz folder: z <= 0 cells and the |
| `run_kernel(surface, report, threads=None, binary=None, env=None, timeout=None, echo=False, **params)` | dict (the report) | SelfcrossError | The kernel backend on one tifxyz: writes `report` as vc_tifxyz_selfcross would. Returns the report. echo: pass |
| `transverse(report)` | int | | Transverse contacts over both diagonals of a report (either backend's). |
| `census(surface, report, backend='auto', tools=None, threads=None, timeout=3600, env=None, log=None, **params)` | dict | SelfcrossError (unknown backend) | Run the chosen backend on one surface, in a child process, and read its report. Returns {"backend", "exit", |
| `report_json(surface, tools=None, threads=2, timeout=3600, env=None, backend='auto')` | (str, dict, exit) | SelfcrossError | (backend, report dict, exit code) for one surface in a scratch folder: the callers that read the report and |
| `status(tools=None, env=None)` | dict | | What this machine has for each backend, and which `auto` picks. |
| `build_parser(p=None)` | ArgumentParser | | |
| `main(argv_=None, args=None)` | exit code | | |

## Inputs

A tifxyz folder: `x.tif`, `y.tif` and `z.tif` (one 2-D page each, the same shape; level-0 voxel coordinates),
`meta.json`, and optionally `mask.tif`. The kernel backend loads it as VC3D's `load_quad_from_tifxyz` does: a cell with
z <= 0 is invalid; mask.tif channel 0 under 255 invalidates its cell; a mask an integer multiple of the grid
invalidates a cell when any pixel of its block does; a mask of another size is ignored. Nothing else invalidates: a
cell with x = -1 and z > 0 stays (unlike `kit meshqa`'s validity). NaN cells stay NaN; the census skips any quad with
a non-finite or (-1, -1, -1) corner. The grid goes to the kernel as raw float32, 12 bytes a cell.

## Outputs

The report (JSON), as vc_tifxyz_selfcross writes it:

| Field | Type | Meaning |
| --- | --- | --- |
| `tool` | string | `vc_tifxyz_selfcross`, or `kit selfcross (villa's vc_tifxyz_selfcross census kernel)` |
| `backend` | string | kernel backend only: `kernel` |
| `kernel` | object | kernel backend only: `villa_commit`, `header`, `header_sha256`, `driver_sha256`, `shim_sha256`, `compiler_version` |
| `report_only` | bool | always true: nothing is changed |
| `surface` | string | the tifxyz folder |
| `clean_of_transverse_self_intersection` | bool | no transverse contact on either diagonal |
| `note` | string | what clean means |
| `parameters` | object | `exclude` (cells), `maxedge` (voxels), `cell` (voxels), `touch_tolerance` (voxels, 0.001), `diagonals` |
| `grid_rows`, `grid_cols` | int | the grid's shape |
| `census` | list | one row per diagonal (0, 1): `triangles`, `quads_dropped_for_edge_length`, `pairs_tested`, `transverse`, `coplanar`, `grazing`, `transverse_contacts` |
| `census[].transverse_contacts[]` | object | `quad1`, `quad2` ([row, col]), `tri1`, `tri2` (0 or 1), `penetration_vx`, `angle_deg`, `site` ([x, y, z] on the intersection segment) |

`build` writes `work/selfcross/kernel-<key>/build.json`: the binary, villa commit, header path, sha256 of the header,
driver and shim, the compiler and its version, when, and the license note. `status --json` prints `villa`, `kernel`
and `auto`.

| Exit code | Meaning |
| --- | --- |
| `0` | `run`: the census ran, whatever it found; `build`, `status`: done. These codes are the kernel backend's; `run --backend villa` returns villa's tool's own exit code |
| `1` | an error: bad parameters, an unreadable surface, a failed build or kernel |
| `2` | `run`: no backend on this machine (or an argument error) |
| `3` | `run --fail-on-crossing` found a transverse contact |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `the census header from ... has sha256 ... refused` | The header is not villa's at `7154682e1` | Fetch it again, or give the right copy |
| ``no C++17 compiler found (set CXX, or install g++ or clang++; on a Mac, `xcode-select --install`)`` | No compiler on PATH | Install one, or set CXX |
| `selfcross backend` | An unknown backend name | Use auto, villa or kernel |
| `: x, y and z grids differ in shape (` | A broken tifxyz | Rewrite the surface |
| `--cell must be a finite positive number of voxels (got` | As villa's CLI refuses | Give a cell over 0 |
| `--exclude must be a whole number, 0 or more (got` | As villa's CLI refuses | Give 0 or more |
| `--maxedge must be a finite number, 0 or more; 0 disables it (got` | NaN or a negative edge | Give 0 or more |
| `self-intersection backend failed on` | The backend wrote no readable report | Read its log (`selfcross.log` beside the check) |
| `the kernel backend needs numpy to read the tifxyz grid` | No numpy | `pip install numpy` |
| `the kernel build failed (exit` | The compiler refused the code (shown below the line) | Use a C++17 compiler (g++ 9+, clang 10+) |
| `the kernel exited` | The kernel refused a parameter or could not read the grid | Read its message |
| `selfcross build:` | The build stopped (the reason follows) | As the reason says |
| `cannot read the census header` | `--header` or KIT_SELFCROSS_HEADER names no readable file | Fix the path |
| ``the census header is not cached in ...; run `python -m kit selfcross build` (it fetches`` | No cached header and fetching is off | Run build |
| `the kernel build did not finish:` | The compiler timed out or could not start | Check the compiler |
| `the kernel did not finish:` | Timeout or the binary could not start | Rebuild with `--force` |
| `could not fetch the census header` | No network to raw.githubusercontent.com | Give a copy with `--header` |
| `: set VC_APPIMAGE to a 7154682e1 or older build` | parity.py needs villa's own tool | Point VC_APPIMAGE at a pre-cutover build |
| `no kernel backend:` | parity.py needs a built kernel | `python -m kit selfcross build` |

## How it works

1. `build` reads our driver and shim, finds the header (`--header`, `KIT_SELFCROSS_HEADER`, the cache, or
   `HEADER_URL`: `https://raw.githubusercontent.com/ScrollPrize/villa/7154682e174205bcaafe06a4962668becd85bb56/volume-cartographer/apps/src/vc_tifxyz_selfcross_impl.hpp`),
   refuses it unless its sha256 is `HEADER_SHA256` (`307e3d33...ae64b`), and compiles
   `c++ -O2 -std=c++17 -I shim -I header-dir selfcross_kernel.cpp -pthread` into `work/selfcross/kernel-<key>/`, where
   key is a digest of the header's sha256 and our two files, so a change to either builds anew.
2. `run --backend kernel` loads the grid under VC3D's loader rule (Inputs), writes it as raw float32, and runs the
   binary, which calls villa's `vc_selfcross::census` once per diagonal with `exclude` 1, `maxedge` 60 and `cell` 40
   (villa's defaults) and the thread count (0 is all cores; the kernel's answer does not depend on it), and writes the
   census rows. kit writes the report around them.
3. `resolve` picks the backend: `villa` when `vc_tifxyz_selfcross` is in the VC3D build kit finds (VC_BIN,
   VC_APPIMAGE), else `kernel` when it is built (or `KIT_SELFCROSS_BIN` names one).

Callers: `check_surface` (the agent tool AutoPipeline's qa runs, argument `selfcross_backend`), `kit regioncrop`
and the winding benchmark's per-winding score (`kit surfbench gscore`). AutoPipeline's plan picks
the backend with `qa.selfcross` (absent is auto, so older plans keep their digest) or `backends: {"selfcross":
"kernel"}`; `kit stages list selfcross` lists the choices.

## Cost and time

CPU only, nothing rented. Build about 10 s (g++ 13.3, cloud container, 2026-10-30). The parity run of 51 surfaces
with both backends and two controls took about 2 minutes, most of it starting the AppImage. On real traces: not
measured here; villa's tool took minutes on full segments, and the kernel is the same code.

## For agents

- **Command:** `python -m kit selfcross status --json`, then `python -m kit selfcross run --surface S -o R.json`.
- **Parse:** `clean_of_transverse_self_intersection`, and the sum of `census[].transverse`; `backend` says which ran.
- **Rerun:** safe; `run` overwrites its report, `build` reuses a build unless `--force`.
- **Success:** exit 0 and a report with two census rows.
- **Not a pass:** a qa record that says "not measured": no backend ran, so the surface was not checked.
- **Go-ahead:** Nothing.
- **Never:** commit villa's header or a built binary to a repository or a release package (GPL-3.0); call a clean report a correct trace.

## Tests

`python -m unittest tests.test_selfcross` covers the loader rule, the backend choice, the commands, the report's
shape, refusals, the command line through a fake kernel, and (with a compiler and a copy of the header, never
fetched by the tests) the compiled kernel on the 11 named fixtures against villa's counts, thread independence and a
control. AutoPipeline's use is in `tests/test_autopipe.py` (`cutover` tests) and `tests/test_vc3d_agent.py`.
Not covered by tests: villa's binary itself (`scripts/selfcross/parity.py` needs it), and real traces.

## History

- 2026-10-30: new, for AutoPipeline 0.1.11, after villa removed vc_tifxyz_selfcross in `e1aa625a6` (villa #2358).

## Related

- AutoPipeline's page (`a note of the source repository` in the Scrolls repository): the qa stage that rejects crossing traces, and the flatten stage's flatboi backend.
- The stage registry's page (`a note of the source repository` in the Scrolls repository): `kit stages list selfcross`.
- `kit/regioncrop.py`, `kit/gscore.py`: read the same report.
