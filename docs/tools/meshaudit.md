# meshaudit: audit published cross-scan transforms, meshes and render depth

`python -m kit meshaudit` checks the public catalogue's geometry: it refits each cross-scan affine from its own landmarks, checks each surface volume's canvas against its meshes, picks a seeded set of segments, and measures where the papyrus sits in native and cross-scan renders.

| Field | Value |
| --- | --- |
| Id | `meshaudit` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit meshaudit transforms`, `python -m kit meshaudit canvas`, `python -m kit meshaudit plan`, `python -m kit meshaudit depth`, `from kit import meshaudit` |
| Code | `kit/meshaudit.py`, `kit/cli.py` (`cmd_meshaudit`) |
| Tests | `tests/test_meshaudit.py` |
| Needs | Python 3.10 or newer; numpy for `transforms`, `plan` and `depth`; tifffile (and imagecodecs for LZW meshes) for the mesh functions the study scripts use; zarr only for compressed surface volumes. The rest is the standard library. Checked with Python 3.13 and numpy 2.5 |
| Runs on | Any CPU. `transforms` on the live catalogue took 6 s and `plan` on a local copy 2 s; `canvas` for one scroll (PHerc0841) 17 s, almost all network reads (measured 2026-10-16, 4-core Xeon cloud container, shared). The whole 2026-10-07 study took about an hour on 4 CPUs ([data README](../data/mesh-hypothesis/README.md)) |
| Network | The open-data bucket `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` over plain HTTPS: `metadata.json` (the catalogue, 1.4 MB gzipped) unless `--catalogue` is a local file; for `canvas`, each mesh's `meta.json` and two small range reads of its `x.tif`, and each surface volume's `.zattrs`; for `depth`, the surface volumes' `.zattrs`, `.zarray` and the chunks the tiles touch, from `--base` |
| Writes | Nothing (prints only). With `--out OUT`, the JSON result to OUT |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07 (`e14b033`) |
| Guide | [The mesh hypothesis protocol](../plans/2026-10-07-mesh-hypothesis.md), [its log](../logs/2026-10-07-mesh-hypothesis.md) and [its data](../data/mesh-hypothesis/README.md) |
| Checked | 2026-10-16 against commit `63753fa` |

## What it does

Most published segments are traced on one scan of a scroll and then rendered on its other scans through a stored affine transform (a cross-scan affine: a 3x4 matrix that maps voxel coordinates of one scan to another, fitted from landmarks, points marked in both scans). An ink model reads a band of layers around the mesh, so a carried-over mesh that lands tens of micrometres off the papyrus gives the model the wrong depth. The bucket's catalogue (`metadata.json`) lists the samples, volumes, segments, renders and transforms; `kit meshaudit` checks it with four actions, written for the [mesh hypothesis protocol](../plans/2026-10-07-mesh-hypothesis.md) of 7 October 2026:

| Action | Protocol | What it does |
| --- | --- | --- |
| `transforms` | H2 | For every stored transform: refit the least-squares affine from its own landmarks, then the fit residual of the stored matrix and of the refit, the leave-one-out (LOO) error (each landmark predicted by an affine fitted to the others), the round trip through a stored reverse transform, the isotropic scale against the voxel-size ratio, anisotropy, a mirror flip and how flat the landmarks lie. A tier from the LOO error: under 25 um tight, 25 to 75 um loose, over 75 um coarse, untestable under 5 landmarks |
| `canvas` | H1 | For every surface volume (a segment's render, a zarr of layers), whether a published mesh variant reproduces its `canvas_size` within 1 px at a render ratio of 1, 0.5, 2, 4 or 0.25, and whether that variant's name names the rendered volume |
| `plan` | H3 scope | A seeded choice of up to `--per-combo` segments per (sample, native volume, cross volume), for the depth comparison |
| `depth` | H3, H3b | For one segment, where the papyrus band's brightness peak sits along the normal in its native render and in each cross-scan render, on 32 seeded tiles, with a location control |

The module also holds the functions the study's scripts use for H4 (are the cross meshes affine images of the traced mesh?) and H5 (the in-plane shift between two renders, by phase correlation); those two run from `scripts/experiments/2026-10-07-mesh-hypothesis/`, not from the command.

It reads only public catalogue entries, mesh headers and surface-volume voxels, and reports derived numbers. Brightness peaks locate papyrus, not ink: nothing here says whether a render is good for ink, and nothing concerns letters. The tiers are expected-error flags fixed in the protocol, not proof that a render is off the sheet. The `depth` location control has little power on real data (most pairs came out not evaluable, see Checks and controls).

## When to use it

- Before using a segment's render on a scan other than the one it was traced on: check that scan pair's transform (`transforms`), and that the render has a matching mesh (`canvas`).
- To see whether a stored matrix fits its own landmarks, before using it to map coordinates between scans (such as `kit stackcheck --transform catalog:...`).
- To measure whether a cross-scan render puts the papyrus at the same depth as the native render (`depth`), within its control.
- To rerun or extend the 7 October study on a newer catalogue.

Do not use it:

- To check consecutive segments of one scan against each other: use [`stackcheck`](stackcheck.md).
- To ask whether two segments trace one sheet: use [`overlap`](overlap.md).
- To judge a render by its ink: score an ink map with [`auc`](auc.md) on a labelled segment.
- To download renders or meshes: use [`fetch`](fetch.md).

## Quick start

```bash
python -m kit meshaudit transforms --out transforms.json
python -m kit meshaudit plan --out depth-plan.json
```

- `transforms.json`, `depth-plan.json`: where the JSON results go; each command reads the live catalogue from the bucket (add `--catalogue metadata.json` to use a saved copy).

On 2026-10-16 (catalogue last modified 12 October 2026), `transforms` printed 29 lines and exited 0 in 6 s; the first and the PHerc1667 lines were:

```
PHerc0009B   20250521125136 -> 20250820154339  landmarks  6  LOO RMS  188.8 um  coarse
PHerc0139    20250820105138 -> 20250728140407  landmarks  8  LOO RMS   62.4 um  loose
...
PHerc1667    20260323082859 -> 20251217075048  landmarks  6  LOO RMS    6.6 um  tight
```

The tiers came out 10 tight, 10 loose, 4 coarse and 5 untestable, as in the 7 October log. The PHerc1667 line reads "tight", yet its JSON row has `matrix_matches_landmarks: false` (`fit_max_um` 212.5 against `refit_rms_um` 2.2): the tier rates the landmarks' own refit, not the stored matrix (see For agents). `plan` printed 13 lines (63 segments) and its JSON equals the saved [`depth-plan.json`](../data/mesh-hypothesis/depth-plan.json) of 7 October.

`canvas --sample PHerc0841` printed `surface volumes 6, reproducible from a published mesh 6, by a variant naming the volume 6` in 17 s. `depth` was run only on a synthetic local bucket over `file://` URLs (a segment rendered on a 9.366 um and a 2.4 um volume, the second 10 um deeper): `python -m kit meshaudit depth --sample S --segment g1 --base file:///PATH/bucket --catalogue PATH/bucket/metadata.json` printed `g1 11111111111111 -> 22222222222222  tiles 32  median delta 10.111042498011294 um  control False`. It worked when the exit code is 0 and the lines appear; a `depth` delta counts only when its pair is `evaluable`.

## Checks and controls

- **The stored matrix against its own landmarks** (`transforms`). `matrix_matches_landmarks` is false when the stored matrix's fit residual exceeds the refit's by more than 1 um, so a matrix that does not reproduce its landmarks fails. Fail on real data: PHerc1667 `20260323082859` (1.129 um) to `20251217075048` (2.399 um) misses its six landmarks by up to 212 um while the refit fits them within 4 um ([log](../logs/2026-10-07-mesh-hypothesis.md), H2; README finding 10; rerun here on 2026-10-16 with the same result). A CT check posted to [villa #1843](https://github.com/ScrollPrize/villa/issues/1843#issuecomment-6130119937) agrees with the landmarks, not the matrix ([upstream reports log](../logs/2026-10-12-upstream-reports.md), section 3).
- **Leave-one-out** (`transforms`). With noisy landmarks the LOO error exceeds the fit error, which is what makes the tier a test (`test_noise_gives_loo_larger_than_fit`). Landmarks that lie nearly in a plane leave the affine undetermined across it: `landmark_flatness` near 0 flags them (PHerc0332's coarse transform: 0.06, LOO RMS 1,019 um).
- **Round trip** (`transforms`). Forward then the stored reverse must return each landmark; a 5-voxel error is measured as 5 voxels (`test_roundtrip_detects_inconsistent_reverse`). Today's catalogue stores no reverse pairs, so no row has `roundtrip_max_um`.
- **Canvas** (`canvas`). A canvas no ratio reproduces gives no match (`test_match_ratios`). On 7 October all 692 surface volumes matched a variant naming their volume ([log](../logs/2026-10-07-mesh-hypothesis.md), H1).
- **Depth controls** (`depth`). C1: known synthetic shifts are recovered within 2 um at 2.4, 9.366 and 1.129 um layers; C2: a render against itself gives 0 (both in the tests). C3, the location control: the median profile correlation of matched tiles must exceed the 95th percentile for tiles paired with other tiles, or the pair is not evaluable. On real data C3 failed on 37 of 68 pairs because depth profiles look alike everywhere (displaced 95th percentiles 0.86 to 0.97), and the 31 evaluable pairs put the papyrus within a few micrometres of the native render ([log](../logs/2026-10-07-mesh-hypothesis.md), H3). On this page's synthetic bucket, C3 passed with no offset but failed with a real offset of 3 or 10 um, which `depth` still measured (3.1 and 10.1 um): the control compares unshifted profile shapes, so a real offset lowers the matched correlation (Interpretation, from synthetic data).

Claim label: Sourced fact for the numbers (recomputed from the published catalogue, mesh headers and renders); what a tier or an offset means for a render or for ink is Interpretation.

## Commands and options

Every action reads the catalogue first and takes `--catalogue`, `--out` and `--json`. Without `--json` it prints text and nothing else; with `--json` it prints the JSON instead. `--out` writes the JSON either way.

### `python -m kit meshaudit transforms`

```
usage: python -m kit meshaudit transforms [-h] [--catalogue CATALOGUE]
                                          [--out OUT] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--catalogue CATALOGUE` | none | The catalogue `metadata.json`, a path or URL, gzipped or not; without it, `BUCKET/metadata.json` |
| `--out OUT` | none | Write the list of transform records as JSON to OUT (overwritten) |
| `--json` | off | Print the JSON instead of one text line per transform |

### `python -m kit meshaudit canvas`

```
usage: python -m kit meshaudit canvas [-h] [--sample SAMPLE]
                                      [--workers WORKERS]
                                      [--catalogue CATALOGUE] [--out OUT]
                                      [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--sample SAMPLE` | none | Only this sample, such as `PHerc0841`; repeat for more. Without it, every sample in the catalogue |
| `--workers WORKERS` | `16` | Threads for the network reads |
| `--catalogue CATALOGUE` | none | As for `transforms`. Meshes and surface volumes are always read from the bucket |
| `--out OUT` | none | Write `{"rows": [...], "mesh_errors": [...]}` as JSON to OUT |
| `--json` | off | Print that JSON instead of the one-line count |

### `python -m kit meshaudit plan`

```
usage: python -m kit meshaudit plan [-h] [--per-combo PER_COMBO] [--seed SEED]
                                    [--catalogue CATALOGUE] [--out OUT]
                                    [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--per-combo PER_COMBO` | `5` | Segments chosen per (sample, native volume, cross volume); fewer when fewer exist |
| `--seed SEED` | `20261007` | Seed of the choice (`SEED`, the protocol's date) |
| `--catalogue CATALOGUE` | none | As for `transforms` |
| `--out OUT` | none | Write the plan as JSON to OUT |
| `--json` | off | Print the JSON instead of one text line per combination |

### `python -m kit meshaudit depth`

```
usage: python -m kit meshaudit depth [-h] --sample SAMPLE --segment SEGMENT
                                     [--cross CROSS] [--tiles TILES]
                                     [--seed SEED] [--base BASE]
                                     [--reference REFERENCE]
                                     [--catalogue CATALOGUE] [--out OUT]
                                     [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--sample SAMPLE` | required | The catalogue sample, such as `PHerc0841` |
| `--segment SEGMENT` | required | The catalogue segment id (the key under the sample's `segments`, such as `20260220213127`) |
| `--cross CROSS` | none | Compare only with this cross volume id; repeat for more. Without it, every other volume with a render of the segment |
| `--tiles TILES` | `32` | Tile centres, uniform random over the canvas |
| `--seed SEED` | `20261007` | Seed of the tile centres (`SEED`) |
| `--base BASE` | `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` | Where the surface volumes are read from (`BUCKET`); catalogue paths are joined to it. A `file://` URL reads a local copy |
| `--reference REFERENCE` | none | A volume id whose render takes the native role, for a segment with no native render (protocol amendment H3b) |
| `--catalogue CATALOGUE` | none | As for `transforms` |
| `--out OUT` | none | Write the segment's result as JSON to OUT |
| `--json` | off | Print the JSON instead of one text line per pair |

## Python API

```python
from kit import meshaudit
cat = meshaudit.load_catalogue()                     # the bucket's metadata.json
rows = meshaudit.transforms_audit(cat)
bad = [r for r in rows if r.get("matrix_matches_landmarks") is False]
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `load_catalogue(path_or_url=None)` | dict, the catalogue | `OSError` (including `urllib.error.URLError`) or `ValueError` when it cannot be read | `BUCKET/metadata.json` when None |
| `get_json(url)` | the parsed JSON | `OSError`, `ValueError` | A path or URL, gunzipped when gzipped |
| `tif_dims(url)` | `(width, height)` | `ValueError` for a file that is not a TIFF or an IFD without width or height; `OSError` on network errors | Classic TIFF and BigTIFF, from the first IFD, with two range reads |
| `parse_ifd_dims(ifd, bo='<', big=False)` | `(width, height)` | `ValueError` | Reads tags 256 and 257 from IFD bytes |
| `fit_affine(src, dst)` | 3x4 array M with `dst` about `M[:, :3] @ src + M[:, 3]` | numpy's `LinAlgError` in rare degenerate cases | Least squares |
| `apply_affine(m, pts)` | (N, 3) array | Nothing of its own | |
| `loo_errors(src, dst)` | list of residual norms in target units, or None under 5 landmarks | Nothing of its own | Leave-one-out |
| `tier(loo_rms_um)` | `"tight"`, `"loose"`, `"coarse"` or `"untestable"` | Nothing | Cut points `TIERS_UM = (25.0, 75.0)` |
| `audit_transform(matrix, src, dst, px_from_um, px_to_um, reverse=None)` | dict, the transform record under Outputs (without `sample`, `from_volume`, `to_volume`, `has_reverse`) | numpy errors for a singular matrix | Under 4 landmarks: fit fields None, tier untestable |
| `transforms_audit(cat)` | list of transform records | `KeyError` for a catalogue without `samples` | Pairs each transform with its stored reverse when there is one |
| `canvas_match(canvas, tif_wh, scale, ratios=CANVAS_RATIOS, tol=1.0)` | the first matching ratio, or None | Nothing | `CANVAS_RATIOS = (1.0, 0.5, 2.0, 4.0, 0.25)` |
| `segment_entries(seg)` | `(surface volume paths, [(mesh type, mesh path)])` | Nothing | From a catalogue segment record |
| `canvas_audit(cat, samples=None, workers=16, base=BUCKET)` | `(rows, mesh_errors)` | Errors reading the catalogue structure; read errors are recorded, not raised | What `canvas` runs |
| `plan_depth(cat, per_combo=5, seed=SEED)` | list of plan records | Nothing of its own | One generator for all combinations in sorted order, so the picks depend on the whole catalogue |
| `tile_centres(n, seed=SEED)` | list of `(u, v)` in [0, 1) | Nothing | u along columns, v along rows |
| `depth_segment(base, sample_id, seg, cross_ids=None, n_tiles=32, seed=SEED, workers=8, reference=None)` | dict, the depth result under Outputs | Errors reading the native render; a cross render's errors go to its pair's `error` | What `depth` runs |
| `SurfaceVolume(base_url, fetch=None, fetch_range=None)` | a reader with `levels`, `dz_um`, `n_layers`, `read`, `read_layer`, `profile`, `level_near` | `OSError` or `ValueError` when `.zattrs` or `.zarray` cannot be read | Uncompressed chunks are read directly; compressed arrays through zarr. An absent chunk reads as the fill value |
| `gaussian_smooth(y, sigma)` | array | Nothing | Reflect-padded |
| `layer_positions_um(n_layers, dz_um)` | array of um from the centre layer | Nothing | |
| `sheet_peak_um(profile, dz_um, sigma_um=8.0, window_um=60.0)` | float um from the centre layer, or None | Nothing | Highest local maximum within the window, refined with a parabola |
| `shape_corr(p_native, dz_native, p_cross, dz_cross, flip=False, half_um=60.0, step_um=1.0)` | float, or NaN | Nothing | Pearson correlation on a common 1 um grid |
| `compare_profiles(native, cross, dz_native, dz_cross)` | dict, the pair fields under Outputs | Nothing | Needs 4 tiles with both profiles |
| `grid_normals(xyz)` | (H, W, 3) unit normals, NaN where undefined | Nothing | H4 |
| `affine_residuals(ref_xyz, cross_xyz, matrix, px_cross_um, search=4, max_points=20000, seed=SEED)` | dict: `points`, `matched`, normal and tangential median, 90th percentile and max in um, shares of normal residuals over 25 and 75 um | Nothing | H4: is the cross mesh the matrix's image of the reference mesh? |
| `read_tifxyz(base_path, fetch=None)` | (H, W, 3) float64, NaN for holes | `OSError`; `ImportError` without tifffile | H4 |
| `sample_matrix(cat, sample_id, a, b)` | `(matrix, derivation_path)`, or `(None, None)` | `KeyError` for an unknown sample | The catalogue's sample-level matrix from volume a to b; `kit stackcheck --transform catalog:...` uses it |
| `area_resample_1d(a, in_px, out_px, n_out, start_um, axis)` | array | Nothing | H5: area-averaged resampling |
| `phase_shift(a, b, exclude=5)` | `((rows, cols) shift in px, peak-to-sidelobe ratio)` | Nothing | H5: b(x) is about a(x - s) |
| `centre_patch(sv, u, v, size_mm=3.0, out_um=10.0)` | 2D array, or None | Nothing of its own | H5: the centre layer around (u, v) |
| `predicted_shift_um(ref_xyz, u, v, stored_ref_to_cross, true_cross_to_ref, px_ref_um)` | `(rows um, cols um, magnitude um)`, or None | Nothing | H5: the shift expected if the stored matrix is wrong and the refit right |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Catalogue | The bucket's `metadata.json` (gzipped JSON), or a saved copy | Read: `samples.SAMPLE.volumes.VOLUME.properties` (`pixel_size_um`, `transforms` with `to_volume_id`, `transformation_matrix`, `from_landmarks`, `to_landmarks`), `samples.SAMPLE.segments.SEGMENT` (`original_volume_id`, `data` entries of type `layers-zarr` and `tifxyz...` with `origins[].path`, `properties.volume_coverage`), and `samples.SAMPLE.sample.properties.volume_transforms`. The bucket changes; the 7 October study hashed its copy ([data README](../data/mesh-hypothesis/README.md)) |
| Meshes (`canvas`) | `meta.json` (`scale`) and the header of `x.tif`, on the bucket | Read over the network only |
| Surface volumes (`canvas`, `depth`) | OME-Zarr v2 groups: `.zattrs` with `multiscales` and `canvas_size`, levels with `.zarray` (ZYX, chunks spanning all layers) | The volume id is read from the folder name (`volume-` and 14 digits) |

Units: transform residuals in um of the target volume, round trips in um of the source volume, depth offsets in um along the layers from the centre layer (positive is toward the last layer), canvas sizes in pixels.

## Outputs

`transforms` prints one line per transform: `SAMPLE FROM -> TO  landmarks N  LOO RMS X um  TIER` (`-` when untestable). Its JSON is a list of records:

| Field | Type | Meaning |
| --- | --- | --- |
| `sample`, `from_volume`, `to_volume` | str | The transform |
| `n_landmarks` | int | Landmark pairs stored |
| `px_from_um`, `px_to_um` | float or null | The two volumes' voxel sizes from the catalogue |
| `iso_scale`, `expected_scale`, `scale_dev_pct` | float | Cube root of the matrix determinant, the voxel-size ratio, and their difference in % |
| `anisotropy_pct` | float | Largest over smallest singular value, minus 1, in % |
| `handedness_flip` | bool | Negative determinant (a mirror) |
| `landmark_flatness` | float | Smallest over largest spread of the landmarks; 0 when they lie in a plane |
| `refit_max_diff` | float or null | Largest difference between the stored matrix and the refit, matrix units |
| `fit_rms_um`, `fit_max_um` | float or null | The stored matrix's residual at the landmarks, um |
| `refit_rms_um` | float | The refit's residual, um |
| `matrix_matches_landmarks` | bool | The stored fit is within 1 um of the refit's |
| `loo_rms_um`, `loo_max_um` | float or null | Leave-one-out error, um; null under 5 landmarks |
| `tier` | str | From `loo_rms_um`: `tight`, `loose`, `coarse`, `untestable` |
| `roundtrip_max_um` | float | Only when a reverse is stored: the largest landmark error forward and back, um |
| `has_reverse` | bool | A reverse transform is stored |

`canvas` prints `surface volumes N, reproducible from a published mesh N, by a variant naming the volume N`. Its JSON: `rows[]` with `sample`, `segment`, `surface_volume`, `volume`, `native_volume`, `canvas` ([width, height]), `overlap_ratio` (the catalogue's coverage), `matches[]` (`mesh`, `type`, `ratio`, `names_volume`), `reproducible`, `reproducible_by_named_variant`, and `error` when the volume's `.zattrs` could not be read or has no `canvas_size`; and `mesh_errors[]` (`path`, `error`) for meshes that could not be read.

`plan` prints `SAMPLE native V cross V  N of M segments`. Its JSON is a list of `sample`, `native_volume`, `cross_volume`, `segments_available`, `segments` (the chosen ids, sorted).

`depth` prints, per pair, `SEGMENT NATIVE -> CROSS  tiles N  median delta X um  control BOOL`. Its JSON:

| Field | Type | Meaning |
| --- | --- | --- |
| `sample`, `segment`, `native_volume` | str | The segment, and the volume in the native role |
| `reference_is_native` | bool | False with a `--reference` other than the native volume |
| `native_dz_um`, `native_tiles_valid` | float, int | Layer spacing of the native render, and tiles valid in it |
| `error` | str | `no surface volume on the native volume`; then `pairs` is empty |
| `pairs[].cross_volume`, `.surface_volume`, `.cross_dz_um` | str, str, float | The cross render |
| `.tiles_with_profiles` | int | Tiles with a profile in both renders |
| `.evaluable`, `.reason` | bool, str | Whether the pair counts; `reason` when under 4 tiles |
| `.layer_order_opposite` | bool | The cross render's layers run the other way (deltas are computed after reversing) |
| `.matched_corr_median`, `.displaced_corr_p95`, `.location_control_pass` | float, float, bool | The location control C3 |
| `.tiles_with_peaks`, `.deltas_um` | int, list | Tiles with a peak in both, and each tile's offset |
| `.delta_median_um`, `.delta_mad_um` | float | Median offset (cross minus native), um, and its median absolute deviation |
| `.frac_abs_over_25um`, `.frac_abs_over_75um` | float | Share of tiles with an offset over 25 and over 75 um |
| `.error` | str | The cross render could not be read |

| Exit code | Meaning |
| --- | --- |
| `0` | Finished. Read errors inside `canvas` and `depth` are in the result, not in the exit code |
| `1` | An error with a Python traceback: the catalogue cannot be read, an unknown `--sample` or `--segment` (`KeyError`), a native render that cannot be read, or numpy missing |
| `2` | A usage error from the argument parser, such as no action |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | No action, or a missing `--sample` or `--segment` for `depth` | Check the command against Commands and options |
| `urllib.error.URLError: ...` and a traceback, exit code 1 | The bucket cannot be reached for the catalogue | Check the network, or pass a saved copy with `--catalogue` |
| `FileNotFoundError: ...` and a traceback, exit code 1 | `--catalogue` names a file that does not exist | Fix the path |
| `KeyError: 'NAME'` and a traceback, exit code 1 | `depth` with a sample or segment id the catalogue does not have | Use the key under `samples`, and the segment's key under its `segments` (the short id) |
| `ModuleNotFoundError: No module named 'numpy'` and a traceback | numpy is not installed | `python -m pip install numpy` |
| `"error": "no surface volume on the native volume"` in `depth`, and no pair lines | The segment has no render on its native volume (or on `--reference`) | Pick a `--reference` volume that has a render (amendment H3b) |
| No pair lines from `depth`, exit code 0 | `--cross` names no volume the segment has a render on | Check the volume ids with `canvas` |
| `"evaluable": false` with `"reason": "fewer than 4 tiles with both profiles"` | Under 4 tiles valid in both renders, such as a cross scan that covers little of the segment | Use more `--tiles`, or treat the pair as not measurable |
| `"evaluable": false` with `"location_control_pass": false` | The location control failed: profiles are alike everywhere, or the offset is real and large enough to lower the matched correlation | Report the pair as not evaluable; do not read its delta as a result |
| `"error": "not a TIFF (version N): URL"` in `mesh_errors` | A mesh's `x.tif` is not a TIFF | Look at the file; the row is left without that mesh |
| `"error": "TIFF IFD lacks width or height"` in `mesh_errors` | The TIFF's first directory has no size tags | As above |
| A row with `"error"` and `"reproducible": false` in `canvas` | The surface volume's `.zattrs` is missing or has no `canvas_size` | The render cannot be checked; note it |

## How it works

`transforms` (H2): for each sample, collect the stored transforms of each volume, and for each one call `audit_transform`: the determinant's cube root against the voxel-size ratio, singular values for anisotropy, the landmarks' spread (flatness), a least-squares refit from the landmarks, the stored and refit residuals scaled by the target voxel size, leave-one-out (5 or more landmarks), the tier from `TIERS_UM = (25.0, 75.0)`, and the round trip through a stored reverse.

`canvas` (H1): read every mesh's `meta.json` scale and `x.tif` size (from the first IFD, `tif_dims`) and every surface volume's `.zattrs` with 16 threads, then for each surface volume test each of the segment's meshes: `|canvas - (size / scale) * r| <= 1` on both axes for r in `CANVAS_RATIOS`.

`plan` (H3 scope): group segments by (sample, native volume, cross volume) where a render exists on both, and draw up to `--per-combo` ids per group without replacement from one numpy generator seeded with `--seed`, groups in sorted order.

`depth` (H3): draw `--tiles` centres (u, v) uniformly with `--seed`. At each, read a 1.5 mm square of the native render at the level whose pixel is nearest 20 um, keep it when at least half the centre layer is nonzero, and average each layer over the valid pixels: the depth profile. Read the same normalized centre from each cross render. Per pair (`compare_profiles`), with at least 4 tiles: decide the layer order by which way the cross profile correlates better on most tiles; the location control C3 compares the median matched correlation with the 95th percentile over all tile pairs that do not match; then smooth each profile with a Gaussian of 8 um, take the highest local maximum within 60 um of the centre layer, refine it with a parabola, and report cross minus native per tile. A pair is evaluable when C3 passes and at least 4 tiles have peaks in both.

The method is the protocol's, written before the measurements: [`plans/2026-10-07-mesh-hypothesis.md`](../plans/2026-10-07-mesh-hypothesis.md). H4 and H5 (amendments made after seeing results, marked exploratory) use the remaining functions through the study's scripts.

## Cost and time

| Run | Time | Peak memory | Source |
| --- | ---: | ---: | --- |
| `transforms`, live catalogue from the bucket | 6.1 s | 70 MB | This page, 2026-10-16, 4-core Xeon cloud container (shared) |
| `plan`, local catalogue copy | 2.0 s | 84 MB | This page |
| `canvas --sample PHerc0841` (6 surface volumes) | 16.8 s | 84 MB | This page; almost all network reads |
| `depth` on a synthetic local bucket (two renders of 200 x 200 px) | 2.2 s | 87 MB | This page |
| The whole 2026-10-07 study: H1, H2, H3 (68 pairs), H4 and H5 | about 1 hour on 4 CPUs | Not recorded | [Data README](../data/mesh-hypothesis/README.md) |

`canvas` over the whole catalogue and `depth` on real segments were not timed here. `depth` reads whole uncompressed chunks of the render levels near 20 um for every tile, so its download grows with the number of tiles and cross renders; it was not measured. Nothing here needs Modal or a GPU.

## For agents

- **Command:** `python -m kit meshaudit transforms --json --out transforms.json`; `python -m kit meshaudit canvas --sample SAMPLE --out canvas.json`; `python -m kit meshaudit plan --out plan.json`; `python -m kit meshaudit depth --sample SAMPLE --segment SEGMENT_ID --out depth.json`. Add `--catalogue metadata.json` to pin the catalogue you read.
- **Parse:** `transforms`: per record `matrix_matches_landmarks`, `fit_max_um`, `loo_rms_um`, `tier`, `landmark_flatness`, `scale_dev_pct`. `canvas`: `rows[].reproducible_by_named_variant`, `rows[].error`, `mesh_errors`. `plan`: `segments`. `depth`: `pairs[].evaluable`, then `delta_median_um` and `frac_abs_over_25um` only for evaluable pairs.
- **Rerun:** Safe; it only reads. `--out` is overwritten. The bucket changes, so a rerun on the live catalogue can give other numbers; `plan` is deterministic for one catalogue and seed.
- **Success:** Exit code 0. For `depth`, a pair with `evaluable` true.
- **Not a pass:** a `tight` tier on a record whose `matrix_matches_landmarks` is false (the tier rates the landmarks' refit, not the stored matrix); a `depth` delta from a pair that is not evaluable; a pair with `error`; a `canvas` row reproducible only by a variant that does not name the volume; numbers from two catalogue dates compared without saying so.
- **Go-ahead:** Nothing for running it. Reporting a transform upstream (a villa issue or comment) needs Chase's yes, and the text follows the public-writing rule.
- **Never:** Say a render is good or bad for ink, or anything about letters (brightness peaks locate papyrus, not ink); read a failed location control as misregistration; call a tier proof that a render is off the sheet.

## Tests

```bash
python -m unittest tests.test_meshaudit -v
```

26 tests, about 5 s, no network. They cover the transform audit (an exact refit, LOO above the fit with noise, flat landmarks, a stored matrix that misses its landmarks, 4 landmarks untestable, an inconsistent reverse, the tiers, pairing in a catalogue), canvas matching and TIFF and BigTIFF header parsing, the volume id, depth (synthetic shifts recovered within 2 um at three layer spacings, a peak outside the window, identity, a shift between resolutions, reversed layer order, a location control that fails, too few tiles), a local uncompressed zarr with an absent chunk, the H4 residuals (a pure affine, a known normal shift, holes), the H5 phase shift, area resampling and predicted shift, tile centres across pyramid levels, and the plan's grouping and determinism. They skip the numpy parts without numpy. They do not cover the command line, network reads, compressed zarr, or `canvas_audit` and `depth_segment` end to end; this page ran those on the live catalogue and a synthetic local bucket.

## History

- 2026-10-07: first version, with the protocol, its amendments, the derived data and the log (`e14b033`).

## Related

- [The mesh hypothesis protocol](../plans/2026-10-07-mesh-hypothesis.md): H1 to H5, the controls, and the dated amendments.
- [The mesh hypothesis log](../logs/2026-10-07-mesh-hypothesis.md): the 7 October results, and README findings 10 and 11 in [`README.md`](../../README.md#novel-findings).
- [The mesh hypothesis data](../data/mesh-hypothesis/README.md): the derived JSON per hypothesis and the commands that made it.
- [The upstream reports log](../logs/2026-10-12-upstream-reports.md): the CT check of the PHerc1667 matrix posted to villa #1843.
- [`stackcheck`](stackcheck.md): uses the catalogue's sample-level matrices (`sample_matrix`) for `--transform catalog:...`.
- [`overlap`](overlap.md): whether two segments of one scan trace the same sheet.
- [`experiment-records`](experiment-records.md): `scripts/experiments/2026-10-07-mesh-hypothesis/`, the H3, H4 and H5 runners.
- [`GLOSSARY.md`](../../GLOSSARY.md): affine, landmark, canvas, catalogue, surface volume.
