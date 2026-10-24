# hopbench: does a surface prediction keep touching sheets apart?

`python -m kit hopbench` plants sheet hops at real contacts between PHerc0139's hand-traced windings and measures how often a one-sheet check reading a surface prediction (m7, recto-090 or yours) lets them through, and how large a window it still calls one sheet.

| Field | Value |
| --- | --- |
| Id | `hopbench` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit hopbench refs`, `python -m kit hopbench run`, `python -m kit.sheetgap certify` |
| Code | `kit/hopbench.py`, `kit/sheetrefs.py`, `kit/sheetgap.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_sheetgap.py` |
| Needs | Python 3.10 or newer; numpy, scipy, tifffile and numcodecs (`pip install numpy scipy tifffile numcodecs`); about 40 MB of disk for the references and 0.75 GB for the m7 chunk cache (0.56 GB for recto-090) |
| Runs on | CPU only. Building the references took 5 minutes; one `run` took 37 minutes on m7 and 40 minutes on recto-090, each with an empty chunk cache and the two partly running at once (measured 2026-10-24, 4-core Intel Xeon 2.80 GHz cloud container, peak memory 6.0 GB) |
| Network | `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` only: a bucket listing of `PHerc0139/segments/`, the 18 winding meshes, and the prediction's level-0 chunks. A local prediction (`--pred PATH`) reads no chunks from the network |
| Writes | `work/hopbench/refs/PHerc0139-20250728140407/` (meshes, `attrs/*.npz`, `manifest.json`), `work/hopbench/cache/` (chunks), `work/hopbench/runs/PRED/hopbench.json`; all under the current folder, all ignored by git |
| Go-ahead | Not needed (public data, local CPU) |
| Released | Public `main` from the PR that adds it (24 October 2026); a line of the Scrolls kit entry in the README's "Released tools", id `hopbench` |
| Checked | 2026-10-24 against commit `7e51e4f` |

## What it does

A traced surface (a tifxyz mesh following one sheet of papyrus) can switch onto the next sheet without crossing any gap where the two sheets touch. Such a switch is invisible in a coverage score and ruins whatever is rendered from the mesh. Most tools decide whether a mesh point is "on sheet" by asking whether a surface prediction (a model's voxel map of where papyrus surface is) has a voxel within a couple of voxels of it. Where two sheets touch, both sheets pass that test, so it cannot see the switch.

The one-sheet check in `kit/sheetgap.py` asks for more. At every point of the mesh, sampled every 2 voxels, it reads the binary prediction along the mesh normal from -21 to +21 voxels. The point passes when the run of predicted voxels within 2 voxels of it is no thicker than one sheet (`max_thick_vox`) and has at least 2 empty voxels on each side. Two neighboring points are linked only when their runs' centers lie within 2 voxels of each other along the normal. The largest square inside one linked component is the window the check calls one sheet. A prediction that keeps a thin empty line between touching sheets lets the check stop a switch; one that merges them into a single run of one sheet's thickness does not, and no local check can see that case.

`kit hopbench` measures this on public data. It takes PHerc0139's published hand-traced windings w023 to w040 (scan 20250728140407, 9.362 um) and finds places where two neighboring windings come within 4 voxels of each other: real contacts. Around each it builds a 6 mm patch of one winding (A) and moves part of it onto the other (B), in two ways: a band plant, which steps across only inside the contact zone, and a ramp plant, which slides across over 16 voxels. A plant counts when plain connectivity joins its A side and its B side (the no-check arm) and under 5 % of its points sample a missing chunk. The score is how many counted plants the one-sheet check still joins: fewer is better. Beside it, one 20 mm clean window per winding gives the largest one-sheet square: larger is better. The run thickness `max_thick_vox` is calibrated on the clean windows, so each prediction gets its own.

The later windings of the stack (w041 onward) are never downloaded: they are left out as held-out data. Everything here is model output about geometry (where a prediction puts surface) and published hand traces. It is never a reading and says nothing about ink.

## When to use it

- You trained or downloaded a surface prediction and want to know whether it keeps touching sheets apart better than m7, before tracing with it.
- You changed the one-sheet check (`kit/sheetgap.py`) and want to know whether it stops more hops without shrinking the windows.
- You want a one-sheet window on a trace in the PHerc0139 frame: `python -m kit.sheetgap certify SURF` prints the largest square the check certifies.

Do not use it:

- To score how much of a winding a tracer covers or where it switches against the hand traces: that needs a full surface benchmark, not planted hops.
- On another scroll or scan: the references, the frame and the default predictions are PHerc0139 at 9.362 um only.
- To check a mesh's own geometry (holes, folds, stretch): use [tifxyz](tifxyz.md).
- To check that winding counts agree with each other: use [windconsistency](windconsistency.md).

## Quick start

```bash
python -m pip install numpy scipy tifffile numcodecs
python -m kit hopbench refs                 # about 5 minutes, once
python -m kit hopbench run --pred m7        # about 37 minutes with an empty cache
python -m kit hopbench run --pred PRED.zarr --json
```

`PRED.zarr` is your prediction as a zarr v2 array in m7's frame: uint8, level-0 shape 20974 x 6621 x 6621 (z, y, x), C order, the array folder or a multiscale root holding `0/`. Voxels at or above `--threshold` (default 128) count as surface.

What the m7 run printed (2026-10-24):

```
hopbench m7: max_thick_vox 4
  planted hops joined by the one-sheet check: 11 of 64 (0.1719); per-point test: 0.4062
  clean 20 mm windows: median one-sheet square 3.505 mm, 0.0 of 18 at 12.5 mm or more
  report: work/hopbench/runs/m7/hopbench.json
```

It worked when the exit code is 0, `plants_counted` is 64 and `work/hopbench/runs/m7/hopbench.json` exists. The m7 numbers should match the baseline below; a different count of counted plants means the references or the seed changed.

## Checks and controls

The benchmark has to be able to fail in both directions, and its arms show that it can:

- **The hops are real hops.** A plant counts only when the no-check arm (plain 8-connected regions of every valid point) joins its two sides. The per-point on-sheet test (the seated arm) is today's practice and is expected to let most hops through; it does.
- **The check can stop hops.** On synthetic sheets, `test_hop_through_pressed_zone_is_not_joined` shows the check splitting a hop that slides through a pressed zone while the seated test joins it.
- **The check can be fooled.** `test_blind_spot_single_run_switch` paints a prediction that draws one thin run from A up to B through the contact and drops the other halves. The check must join that hop, and does: this is its known blind spot, and it is why the gap arm's joined share is not zero on m7.
- **The truth arm** (clean windows only) keeps points with no other hand-traced winding within 8 voxels. It needs the hand traces, so it is an upper bound for scale, not a method.

Baselines on PHerc0139 w023 to w040 (2026-10-24, this code, seed 20261016; both predictions are the organizers' public ones in `PHerc0139/representations/predictions/surfaces/`):

Of 136 plants (two modes at 68 contact sites), 64 count (10 band, 54 ramp) for both predictions; the other 72 had no split or a no-check arm that did not join. No chunk was missing.

| Prediction | `max_thick_vox` | Hops the check joins (of 64) | Wilson 95 % | Hops the per-point test joins | Median one-sheet square | Largest | Windows of 12.5 mm or more |
| --- | --- | --- | --- | --- | --- | --- | --- |
| m7 | 4 | 11 (17.2 %; band 2 of 10, ramp 9 of 54) | 9.9 to 28.2 % | 26 (40.6 %) | 3.5 mm | 5.3 mm | 0 of 18 |
| recto-090 | 8 | 13 (20.3 %; band 2 of 10, ramp 11 of 54) | 12.3 to 31.7 % | 43 (67.2 %) | 3.9 mm | 6.9 mm | 0 of 18 |
| Truth arm (needs the hand traces) | | | | | 5.9 mm | 13.8 mm | 1 of 18 |

What it shows (Interpretation): on both predictions the one-sheet check stops most hops that the per-point test lets through, but about one in six still gets through, where the prediction draws the two pressed sheets as one thin run (the blind spot). And the windows it keeps are small: in the 18 clean m7 windows, 3.5 to 39.5 % of the hand-traced points (median 14 %) have no predicted voxel within 2 voxels, so even the per-point test never reaches a 12.5 mm square. A prediction that does better on both columns at once keeps touching sheets apart better than the organizers' current ones on this test.

The bar a prediction would need for picking letters-sized windows on its own, fixed before the first run: the check joins at most 5 % of counted plants (Wilson 95 % upper bound at most 15 %) and at least 1 in 4 clean windows has a one-sheet square of at least 12.5 mm, about the area that held the 10 letters of the PHerc. 343 First Letters award. Neither m7 nor recto-090 meets it.

Claim label: Model output, for every number in the table (the predictions are model output, and the check reads them); Interpretation, for what the numbers mean for tracing.

## Commands and options

### `python -m kit hopbench refs`

```
usage: python -m kit hopbench refs [-h] [--refs REFS] [--workers WORKERS]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--refs REFS` | `work/hopbench/refs/PHerc0139-20250728140407` | where the references go (default work/hopbench/refs/PHerc0139-20250728140407) |
| `--workers WORKERS` | `2` | threads for the KD-tree queries while building the manifest |

Downloads the 18 windings (files already present are kept) and rebuilds `manifest.json` and `attrs/`. Safe to rerun.

### `python -m kit hopbench run`

```
usage: python -m kit hopbench run [-h] [--pred PRED] [--threshold THRESHOLD]
                                  [--refs REFS] [--cache CACHE] [--out OUT]
                                  [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--pred PRED` | `m7` | m7 (default), recto090, or a local zarr v2 array in m7's frame (uint8, level-0 shape 20974 x 6621 x 6621; the folder or its multiscale root) |
| `--threshold THRESHOLD` | none | on-threshold for the prediction (default 128) |
| `--refs REFS` | `work/hopbench/refs/PHerc0139-20250728140407` | the references `refs` built |
| `--cache CACHE` | `work/hopbench/cache` | chunk cache (default work/hopbench/cache) |
| `--out OUT` | none | report folder (default work/hopbench/runs/<pred>) |
| `--json` | off | print the headline as JSON |

### `python -m kit.sheetgap certify`

```
usage: python3 -m kit.sheetgap certify [-h] [--rule RULE] [--rows ROWS ROWS]
                                       [--cols COLS COLS] [--cache CACHE]
                                       [--out OUT]
                                       surface
```

| Option | Default | Meaning |
| --- | --- | --- |
| `surface` | required | a tifxyz folder in the frame of PHerc0139 scan 20250728140407 |
| `--rule RULE` | none | a JSON file of `GAP_RULE` keys to override, for example `{"max_thick_vox": 4}`, the value the benchmark calibrates on m7 |
| `--rows ROWS ROWS` | none | crop the grid to rows R0 to R1 first |
| `--cols COLS COLS` | none | crop the grid to columns C0 to C1 first |
| `--cache CACHE` | `work/hopbench/cache` | chunk cache |
| `--out OUT` | none | also write the JSON there |

The check alone on one trace, read against m7: prints the status counts and the largest one-sheet square as JSON. Exit code 0.

## Python API

```python
from kit import hopbench
rep = hopbench.run(pred="m7")          # the whole report, as hopbench.json holds it
print(rep["headline"])
```

`kit/hopbench.py`:

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `run(refs_dir=sr.DEFAULT_REFS, pred='m7', threshold=None, cache_dir=sr.DEFAULT_CACHE, rule=None, log=None)` | The report dict (see Outputs) | `sheetrefs.BenchError` for missing references, an unknown `pred`, a local array not in m7's frame, or no calibration points | `rule` overrides `GAP_RULE` keys before calibration; `log` is a function taking one string |
| `headline(rep)` | Dict of the numbers a comparison quotes | Nothing | Read from `rep["plants"]` and `rep["clean"]` |
| `calibrate(stored, rule)` | `{"points", "quantile", "value", "max_thick_vox", "hist"}` | Nothing | max_thick_vox: the THICK_QUANTILE (0.95) of run thickness at clean points with no other winding within 8 voxels whose run has both gaps, rounded up and capped at THICK_CAP (10) |
| `tally(prow)` | Per mode (`band`, `ramp`, `all`): `n` and, per arm, `joined`, `share`, `wilson95`; and `not_counted` | Nothing | Counts only rows with status `counted` |
| `wilson(k, n, z=1.96)` | `[low, high]` Wilson score interval, or `[None, None]` when n is 0 | Nothing | |
| `build_parser(p)` | Nothing | Nothing | Adds `refs` and `run` to the `hopbench` subparser |
| `cmd_hopbench(args)` | Exit code | Nothing; `BenchError` is printed | What the command runs |

`kit/sheetgap.py` (the check):

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `rule_digest(rule)` | First 12 hex of the rule's SHA-256 | Nothing | Every report carries it |
| `Field(reader, threshold, cache_chunks=48)` | A binary view of a chunked prediction | Nothing | A binary view of a chunked prediction (anything with .chunks and .read(key) -> array or None, such as sheetrefs.ChunkReader), with an LRU of decoded chunks |
| `profiles(field, P, N, half, batch=20000)` | `(B (n, 2 half + 1) bool, missing (n,))` | Nothing | P, N in zyx voxels |
| `runs(B, on_run)` | `(found, start, end, gap_lo, gap_hi)` per profile | Nothing | The run nearest the center within `on_run` samples |
| `classify(B, miss, rule)` | `(status, center offset, thickness)` per profile | Nothing | Status codes `OK`, `OFF`, `THICK`, `GAP`, `MISSING`, `INVALID` (0 to 5) |
| `Cert(status, centre, thick, xyz, normals, ok, step)` | The check on one dense grid | Nothing | `counts()` gives the status counts |
| `densify(xyz, valid, step_vox)` | `(xyz, valid, normals, ok, step)` | Nothing | Resamples a tifxyz grid to about `step_vox` |
| `check_dense(up, nrm, ok, ustep, field, rule)` | `Cert` | Nothing | On an already dense grid (xyz order) |
| `check(xyz, valid, field, rule)` | `Cert` | Nothing | `densify` then `check_dense` |
| `components(cert, rule, mask=None, linked=True)` | Component label per dense point, -1 where not counted, 0 the largest | Nothing | `linked=False` with a mask gives the seated and no-check arms |
| `largest_square(mask)` | `(side, row, col)` | Nothing | Bisection on a summed-area table |
| `best_square(lab, top=4)` | `(side, row, col, label)` | Nothing | Among the four largest components |
| `summary(cert, lab, rule)` | `points`, `status`, `ok_share`, `components`, `step_vox`, `square_cells`, `square_mm`, `square_at`, `square_label` | Nothing | |
| `plant(up, ok, refB, mode='band', contact_vox=4.0, ramp_half_vox=8.0, min_part_vox2=1600.0, step=None, workers=2)` | `(xyz, valid, w, s)` or None when the window has no split | `ValueError` for an unknown mode | w is 0 on A and 1 on B; s is the offset to B along B's normal |
| `bridges(lab, w, s, valid, far_vox=6.0, min_side_cells=1)` | `(joined, points on A, points on B)` | Nothing | Joined when one component holds at least `min_side_cells` points clearly on each side |
| `run_certify(args)`, `main(argv=None)` | Exit code 0 | Nothing | The `certify` command |

`kit/sheetrefs.py` (references and readers):

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `build_refs(dest=DEFAULT_REFS, opener=None, log=None, workers=2, rule=None, names=None)` | The manifest | `BenchError` when a winding is not on the bucket or a download fails | Downloads w023 to w040 (or `names`), then `build_manifest` |
| `load_refs(refs_dir=DEFAULT_REFS, rule=None)` | `(manifest, [Ref])` | `BenchError` for a missing, edited or out-of-date manifest or attribute file | |
| `build_manifest(dest, meshes, sources=None, skipped=None, rule=None, log=None, workers=2)` | The manifest | `BenchError` for fewer than two windings | Order, pitch, duplicates, gaps, contact zones; writes `attrs/` and `manifest.json` |
| `load_manifest(refs_dir, rule=None)` | The manifest | `BenchError` | Checks its digest and the rule digest |
| `find_meshes(opener=None, sample=SAMPLE, volume=VOLUME, voxel_tag=VOXEL_TAG)` | `(found, skipped)` | `BenchError` on a repeated listing token | Every winding folder with a tifxyz in the frame |
| `read_tifxyz(path)` | `(xyz, valid, meta)` | `BenchError` | -1, NaN and all-zero vertices are holes |
| `Ref(name, gid, xyz, valid, rule=None, label=None)` | One reference surface | Nothing | `labelled()`, `usable()`, `scoring()`, `tree()` |
| `match(P, ref, workers=2, dist=False)` | `(offset, inside, native index, normal)`, and distance with `dist` | Nothing | Signed point-to-plane offset along the reference normal |
| `self_overlap(ref, workers=2)` | Per vertex, the distance to another part of the same mesh | Nothing | A winding traced past its seam |
| `grid_geometry(xyz, valid)` | `(normals, area, ok, median edge)` | Nothing | |
| `upsample(xyz, valid, k)` | `(xyz, valid, src)` | Nothing | Bilinear, k times denser |
| `block_keys(points)`, `dilate_keys(keys)` | Integer codes of 128-voxel blocks | Nothing | Which references can be near a point |
| `ChunkReader(prefix, cache_dir=DEFAULT_CACHE, opener=None)` | Reader with `.chunks` and `.read(key)` | `BenchError` when `.zarray` cannot be fetched | Level-0 chunks of a bucket prediction, cached; a chunk S3 reports missing reads as None and is counted |
| `LocalZarr(path, offset=None, threshold=None, expect=None)` | Reader with `.chunks` and `.read(key)` | `BenchError` for no `.zarray`, F order, or a shape or dtype that is not m7's | An absent chunk file reads as the fill value and is counted in `absent`, never as missing |
| `digest(obj)`, `canonical(obj)`, `rule_digest(rule=None)` | SHA-256 hex, canonical JSON | Nothing | |
| `BenchError()` | | | A problem the caller can fix: missing references, a changed rule, an unreadable surface |

## Inputs

| Input | Format | Where it comes from |
| --- | --- | --- |
| References | 18 tifxyz folders, PHerc0139 w023 to w040, in the frame of scan 20250728140407 at 9.362 um | `refs` lists `PHerc0139/segments/` on the open-data bucket and takes each winding's `mesh/*-on-20250728140407-9.362um.tifxyz` |
| `--pred m7` | zarr v2, uint8, 0 or 255, chunks 192^3, blosc zstd | `PHerc0139/representations/predictions/surfaces/20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr/0` |
| `--pred recto090` | as m7 | `.../20250728140407-surface-20250701154204-surface-recto-090.zarr/0` |
| `--pred PATH` | local zarr v2, C order, uint8, level-0 shape `[20974, 6621, 6621]` (z, y, x), any chunk size, any numcodecs compressor | Yours. Coordinates must be m7's voxel grid: a mesh vertex (x, y, z) reads voxel `[z, y, x]` |

## Outputs

`run` prints four lines (or the headline with `--json`) and writes `OUT/hopbench.json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `headline` | object | `prediction`, `max_thick_vox`, `plants_counted`, `gap_joined`, `gap_joined_share`, `seated_joined_share`, `clean_windows`, `gap_median_square_mm`, `gap_share_ge_12.5mm` |
| `windings` | list | The 18 winding names |
| `manifest_digest` | string | Digest of the references used |
| `rule`, `rule_digest` | object, string | The check's settings after calibration, and the first 12 hex of their SHA-256 |
| `settings` | object | The benchmark constants: `seed` 20261016, `clean_mm` 20, `plant_mm` 6, `sites_per_pair` 4, `contact_vox` 4, `copy_vox` 8, `far_vox` 6, `min_side_vox2` 1600, `thick_quantile` 0.95, `thick_cap` 10 |
| `calibration` | object | `points`, `value` (the 95th percentile, voxels), `max_thick_vox`, `hist` (thickness: count) |
| `plants` | object | `tally` per mode `band`, `ramp`, `all`, arms `none`, `seated`, `gap` |
| `clean` | object | Per arm `gap`, `seated`, `truth`: `median_square_mm`, `share_ge_12.5mm`, `squares_mm` |
| `clean_rows`, `plant_rows` | lists | One row per clean window (`winding`, `window_at`, per arm the `summary`) and per plant (`A`, `B`, `at`, `mode`, `status`, `missing_share`, `side_cells`, `joined`, `status_counts`) |
| `missing_chunks`, `reader` | int, object | Chunks reported missing; chunks fetched, cached, missing, absent |
| `seconds` | int | Wall time |

`refs` prints `hopbench refs: 18 windings, manifest DIGEST in REFS` and writes the references folder.

| Exit code | Meaning |
| --- | --- |
| `0` | Done; the report or the references were written |
| `2` | A `hopbench:` error on stderr (missing references, unknown prediction, wrong frame, download failure), or an argument error |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `hopbench:...` | Any of the errors below, as the command prints them | Read the rest of the line |
| `...: no manifest.json; build it with python -m kit hopbench refs` | `run` before `refs`, or another `--refs` | Run `python -m kit hopbench refs` with the same `--refs` |
| `...: the manifest does not match its digest (edited after it was built)` | `manifest.json` was edited | Rerun `refs` |
| `...: built under rule..., not the current rule...; rebuild the references (a changed rule is a new benchmark)` | The code's reference settings changed since `refs` ran | Rerun `refs`; numbers under different references are not comparable |
| `...: changed since the manifest was built` | An `attrs/*.npz` file changed | Rerun `refs` |
| `windings not found on the bucket:...` | The bucket's segment folders changed | Report it; the benchmark is defined on those 18 windings |
| `a reference stack needs at least two windings` | `build_manifest` given one mesh | Give at least two |
| `bucket listing repeated a continuation token` | A broken bucket listing | Retry later |
| `--pred...: not one of...and not a local zarr` | A typo, or a path that does not exist | Use `m7`, `recto090` or an existing folder |
| `...: not a zarr v2 array (no .zarray)` | The folder is not a zarr v2 array or multiscale root | Point at the array folder or the folder holding `0/` |
| `...: only C-order chunks are read` | An F-order array | Rewrite it in C order |
| `...: level-0 shape ... is not m7's ...` or `dtype ... is not uint8` | The array is not in m7's frame | Resample it into m7's frame as uint8 |
| `no clean point had an isolated run: the prediction does not see these sheets` | The prediction is empty there, or `--threshold` is above its values | Check the threshold and the frame |
| `...: no x.tif (not a tifxyz folder)` | A reference or `certify` surface folder without `x.tif` | Give a tifxyz folder |
| `...: x, y and z tifs must be 2-D grids of one size` | A broken tifxyz | Fix or redownload it |
| `kit hopbench needs numpy and scipy: pip install numpy scipy tifffile numcodecs` | numpy missing | Install the needs |
| `kit hopbench needs scipy (cKDTree): pip install scipy` | scipy missing | `pip install scipy` |
| `kit hopbench needs tifffile: pip install tifffile` | tifffile missing | `pip install tifffile` |
| `compressor 'blosc' needs numcodecs ...` | numcodecs missing | `pip install numcodecs` |
| `unknown plant mode...` | A caller passed a mode other than `band` or `ramp` to `plant` | Use one of the two |
| `missing_chunks` above 0 in the report | S3 reported chunks missing (m7 has none on these windings) | Plants with 5 % or more points in missing chunks are not counted; compare `plants_counted` |

## How it works

1. **References** (`kit/sheetrefs.py`). The 18 windings are matched against each other point to plane (each grid made twice as dense, nearest 8 dense vertices, offsets blended over 4). Their normals are oriented outward, near-duplicate parts (25 % of either mesh within 2 voxels) are dropped or masked, and the windings are put in normal order by the median offsets where they overlap. Each winding's chain neighbors and contact zone (another winding within 8 voxels, `contact_vox`) go into `attrs/` and the manifest.
2. **Clean windows.** One 20 mm square (`CLEAN_MM`) per winding, at least 90 % valid, its center drawn with seed 20261016. Each is densified to about 2 voxels and profiled once.
3. **Calibration.** `max_thick_vox` is the 95th percentile of run thickness at clean points outside contact zones whose run has both gaps, rounded up, capped at 10. On m7 it comes out at 4 voxels; a prediction that draws thicker sheets gets a larger value, so it is not penalized for that alone.
4. **Plants.** For each pair of chain neighbors (skipping pairs whose median offset is under 8 voxels, copies of one sheet), up to 4 contact sites (offset up to 4 voxels, `CONTACT_VOX`) at least 6 mm apart, drawn with seed 20261017. Around each, a 6 mm window of A (`PLANT_MM`) is planted in band and ramp mode (`kit.sheetgap.plant`), checked, and its components tested with `bridges` (each side needs 1,600 voxel² of points more than 6 voxels from the other sheet).
5. **Arms and tallies.** none, seated and gap for plants; gap, seated and truth for clean windows. Wilson 95 % intervals on joined shares.

The method follows the planted-control practice of hard rule 4 (every check must be able to fail). The contact zones and chain come from the hand traces only; no CT is read.

## Cost and time

| Step | Wall time | Peak memory | Network | Source |
| --- | --- | --- | --- | --- |
| `refs` | 5 min (5.8 min CPU) | Not measured | 72 files, about 40 MB | 2026-10-24, 4-core Intel Xeon 2.80 GHz cloud container |
| `run --pred m7`, empty cache | 37 min (2,206 s) | 6.0 GB | 0.75 GB of chunks | same; recto-090's run overlapped it |
| `run --pred recto090`, empty cache | 40 min (2,389 s) | 5.3 GB | 0.56 GB of chunks | same |

About 92 s of each run goes to each of the 18 clean windows (about 1.1 million dense points each), the rest to the plants. A second run on the same prediction reads every chunk from the cache.

No paid compute. The m7 cache is reused by later runs; a second m7 run reads no chunks from the network.

## For agents

- **Command:** `python -m kit hopbench refs` once, then `python -m kit hopbench run --pred PRED --json`; the full report is `work/hopbench/runs/PRED/hopbench.json` (`--out DIR` to choose).
- **Parse:** `headline.gap_joined_share` (planted hops the check still joins; lower is better), `headline.gap_median_square_mm` and `headline["gap_share_ge_12.5mm"]` (one-sheet windows; higher is better), `headline.plants_counted` (64 for the baselines), `headline.max_thick_vox`.
- **Rerun:** Safe. `refs` keeps downloaded meshes and rebuilds the manifest; `run` overwrites `hopbench.json` in its folder and reuses the chunk cache.
- **Success:** Exit code 0 with `plants_counted` near the baseline's and `missing_chunks` 0.
- **Not a pass:** A low `gap_joined_share` with tiny squares (a prediction that is empty passes no hops and keeps no windows); a comparison where `plants_counted` differs a lot from the baseline's (the plants are not the same set); a run on references built by another version.
- **Go-ahead:** Nothing.
- **Never:** Call a certified window a reading, or a joined plant a found switch on a real trace; edit the windings list to add later windings (they are held out); compare numbers across different seeds or settings.

## Tests

`python -m unittest tests.test_sheetgap -v` (15 tests, under 2 s, no network): runs, classification and calibration on synthetic profiles; largest square against brute force; enclosed holes; on synthetic sheets, a clean trace, a hop through a pressed zone (not joined), the blind spot (joined), a missing chunk, and band and ramp plants; tallies and Wilson intervals; point-to-plane matching. They do not touch the bucket, the real windings or a real prediction; the baselines above are the end-to-end check.

## History

- 2026-10-24: first public release ([#189](https://github.com/ChaseHendrick/Scrolls/pull/189)), branched from public `main` at `7e51e4f`, with `python -m kit hopbench` in `kit/cli.py`: the planted-hop test, the one-sheet check (`kit/sheetgap.py`, the version fixed on 16 October 2026 before its first run) and the reference builder (`kit/sheetrefs.py`), restricted to windings w023 to w040.

## Related

- [tifxyz](tifxyz.md): a mesh's own geometry (holes, folds, stretch), which this benchmark does not check.
- [windconsistency](windconsistency.md): whether winding counts agree with each other; a non-local signal of the kind the check's blind spot needs.
- [planted](planted.md): planted defects on synthetic surfaces, for testing detectors on known answers.
- [stackcheck](stackcheck.md): order and spacing checks of a stack of segments against the scroll's center line.
- `hopbench_pherc0139_20261024` in [results.json](../results.json): the baseline numbers with their settings.
