# voltransform: move points between scan volumes with the revision 2 transforms

Reads the open-data catalog after its 16 Nov 2026 change: revisioned volume transforms with their thin-plate splines, superseded t1 segment data, and the lossless vc-delta3d volume copies.

| Field | Value |
| --- | --- |
| Id | `voltransform` |
| Status | Current |
| Kind | kit module |
| Area | Data and downloads |
| Run | `python -m kit.voltransform` (actions `table`, `map`, `superseded`); library: `from kit import voltransform` |
| Code | `kit/voltransform.py` |
| Tests | `tests/test_voltransform.py` |
| Needs | Python 3.10+; numpy only to move points; `vc-delta3d[zarr]>=0.3.2` and zarr >= 3.1.1 only for `open_volume` on a vcd3d copy |
| Runs on | CPU; `table` and `superseded` under 1 s on a cached catalog, `map` about 1 s per transform file fetched (measured 2026-11-18, 4-core cloud container) |
| Network | vesuvius-challenge-open-data.s3.amazonaws.com: `metadata.json` (cached a day) and `<sample>/transforms/<from>-to-<to>-r<N>/fit/transform.json` |
| Writes | `$KIT_VC3D_HOME/cache/open-data-metadata.json` and `$KIT_VC3D_HOME/cache/transforms/` (cached transform files); nothing else |
| Go-ahead | Not needed |
| Released | Public `main` since its PR (2026-11-18); the same file in Scrolls-private |
| Checked | 2026-11-18 against commit `c371a7f` |

## What it does

On 16 Nov 2026 the organizers re-registered 14 volume pairs on 10 scrolls (revision 2, "r2"): an affine plus, for 13
of them, a smooth thin-plate-spline correction. Each registration is a folder
`<sample>/transforms/<from>-to-<to>-r<N>/` whose `fit/transform.json` holds the matrix, the landmarks and the spline.
The cross-volume segment meshes of 233 segments were re-derived through r2 (`-t2` in the path); the old "t1" sets stay
for now with `properties.superseded_by` (retained until 2027-02-14). `volume.properties.transforms` is deprecated and
removed after 2026-12-31. Every masked OME-Zarr volume also got a lossless vc-delta3d copy (`ome-zarr-vcd3d` entries).

This module is the one place kit code reads those parts of the catalog. `volume_affines` replaces the deprecated
per-volume list with rows built from `sample.properties.volume_transforms`. `load_chain` moves points from one volume
to another exactly as the organizers' pipeline does: matrix plus spline per step, the fitted inverse spline for
inverted steps (it matches villa `volreg.cores.deformable.Correction` to the last digit on all 13 bent r2 files).
`current` and `pick_current` drop superseded entries, so a t1 and a t2 mesh for the same volume never collide.
`vcd3d_url` and `open_volume` find and open the vc-delta3d copy.

It does not re-register anything, does not judge whether a transform is right (that is `kit vc3d_landmarks`), and its
output is a coordinate, not evidence about ink.

## When to use it

- Any code that moves points, meshes or labels between two volumes of a sample.
- Any code that picks a segment's mesh, surface volume or ink map in another volume's frame.
- Reading a masked volume where bytes matter (a home link, staging a region to disk).

Do not use it:

- To check a transform against its landmarks: `kit vc3d_landmarks` (or `kit meshaudit transforms`).
- To fetch segment files: `kit fetch` or the VC3D agent's `fetch_segment`, which now skip superseded sets.

## Quick start

```bash
python -m kit.voltransform table PHerc0841
echo "1000 1000 1000" | python -m kit.voltransform map PHerc0841 20260319124803 20250821151531
echo "1000 1000 1000" | python -m kit.voltransform map PHerc0841 20260319124803 20250821151531 --revision 1
python -m kit.voltransform superseded PHerc0841
```

Printed on 18 Nov 2026 (catalog Last-Modified 18 Nov 2026 13:26 UTC):

```
20250821151531 -> 20260319124803  r2  bent  20260319124803-to-20250821151531-r2^-1
20260319124803 -> 20250821151531  r2  bent  20260319124803-to-20250821151531-r2
178.745 192.678 13039.180
175.031 193.440 13045.228
20260220213127  tifxyz-transformed  PHerc0841/.../20260220213127-on-20260319124803-2.403um.tifxyz/  ->  ...-2.403um-t2.tifxyz/
```

The same point lands about 7 voxels apart (9.366 um voxels) under r1 and r2. `--json` gives the same as JSON.

## Checks and controls

The spline code is checked against villa's own reader: on the 13 bent r2 files, forward on the moving landmarks and
inverse on the fixed landmarks, the largest difference from `volreg.cores.deformable.correction_from_json` was 0
(2026-11-18). The unit tests fit a spline with zero smoothing and require it to reproduce its points within 1e-6
voxels and its fitted inverse to round-trip; a bent transform with no inverse must refuse to invert.

Claim label: Sourced fact for the catalog structure (`metadata.json`, Last-Modified 18 Nov 2026 13:26 UTC);
Model output for nothing; the r1 against r2 distances in the log are measurements on public data.

## Commands and options

| Option | Default | Meaning |
| --- | --- | --- |
| `table SAMPLE` | | Every transform of the sample: from, to, revision, bent or affine, steps |
| `map SAMPLE SRC DST` | | Move `x y z` points read from stdin from volume SRC to volume DST |
| `superseded SAMPLE` | | Superseded segment data entries and their replacements |
| `sample` | | Sample id, such as `PHerc0841` |
| `src`, `dst` | | Volume ids (14 digits) |
| `--revision N` | the table's | Force every step to revision N (1 rebuilds the old map) |
| `--json` | off | JSON instead of lines |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `volume_affines(sample_entry, vid)` | list of `{to_volume_id, transformation_matrix, revision, from_landmarks, to_landmarks}` | Nothing | Replacement for `volume.properties.transforms`; affine part only |
| `table(sample_entry)` | list of `{from, to, revision, steps, matrix, derivation_path, created}` | Nothing | The sample's `volume_transforms` |
| `chain_spec(cat, sample, src, dst)` | one table row with its steps | `TransformError` | |
| `load_chain(cat, sample, src, dst, fetch=None, revision=None)` | `Chain` with `.apply(points)` | `TransformError`, URL errors | `revision=1` rebuilds the old map |
| `compare_revisions(cat, sample, src, dst, points)` | `{n, median, p90, max}` in dst voxels | as `load_chain` | r1 against current |
| `Transform.from_json(record)` | `Transform` (`.apply`, `.inverted()`, `.bent`) | `TransformError` | One `transform.json` |
| `current(entries)`, `pick_current(entries, key)` | list, dict | Nothing | Skip superseded; highest `transform_revision` wins |
| `is_superseded(entry)`, `replacement(entry)` | bool, dict or None | Nothing | |
| `path_revision(path)` | int | Nothing | 2 for `-t2` paths, else 1 |
| `latest_revision(sample_entry, src, dst)` | int or None | Nothing | From `volume-transform` entries |
| `vcd3d_url(volume_entry)`, `vcd3d_sibling(url)` | URL or None | Nothing | |
| `open_volume(url, level=0, prefer_vcd3d=True)` | `(zarr array, url used)` | zarr errors | Falls back to the URL given |
| `have_vcd3d()` | bool | Nothing | vc-delta3d >= 0.3.2 and zarr >= 3.1.1 importable |
| `volume_transform_entries(sample_entry)` | list of `{from, to, revision, bent, path, fit}` | Nothing | The `volume-transform` data entries |
| `Spline(record)` | callable: points to displacements | `TransformError` | One stored spline |
| `invert_matrix(m)` | 3x4 array | `LinAlgError` | Inverse of an affine |
| `fetch_json(url, cache_dir=None)` | parsed JSON | URL errors | gzip-aware, cached by path |
| `transform_url(sample, src, dst, revision)` | URL | Nothing | |
| `load_step(sample, src, dst, revision, fetch=None)` | `Transform` | as `fetch_json` | One registration as stored |
| `vcd3d_entry(volume_entry)` | data entry or None | Nothing | Newest codec version first |
| `load_catalog(cache_dir)` | parsed `metadata.json` | URL errors | Cached a day |
| `main(argv=None)` | exit code | Nothing | The command line |

## Inputs

The open-data `metadata.json` (or a parsed catalog dict), sample and volume ids, points as `x y z` level-0 voxels.

## Outputs

`table`: one line per transform (from, to, revision, bent or affine, steps). `map`: one `x y z` line per input point in
the target volume's voxels. `superseded`: segment, data type, superseded path and its replacement.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `TransformError: no sample 'X' in the catalog` | The sample id is wrong | Use an id from `metadata.json` (case is ignored) |
| `TransformError: S: no transform from A to B; from A the table reaches [...]` | The sample's table has no such pair | Pick a pair it lists, or chain through one |
| `TransformError: ... is bent but carries no fitted inverse` | A spline with no inverse was asked to run backwards | Use the forward direction, or wait for the organizers to publish the inverse |
| `TransformError: unknown deformation model ...` or `unknown deformation kernel ...` | A transform file with a newer schema | Update this module against villa's `deformable.py` |
| `TransformError: deformation arrays have the wrong shapes` or `matrix must be 3x4, got ...` | A damaged or unexpected transform file | Refetch it (delete the cached copy) and report it if it repeats |
| `DeprecationWarning: volume.properties.transforms is deprecated ...` | An old catalog snapshot with no `volume_transforms` table | Refresh the catalog |

## How it works

Per step, `x -> M x + U(x)`, where `U` is a thin-plate spline with kernel `-r` on points normalised by the stored
centre and scale (villa `foundation/volume-registration/pipeline/volreg/cores/deformable.py`, MIT). Inverted steps use
the inverse of `M` plus the separately fitted inverse spline. Steps compose in the order the table gives.

## Cost and time

Free: CPU only, one small JSON per transform (about 200 KB for a bent one). Moving a million points through a spline
with 435 control points takes a few seconds and about 200 MB in batches of 50,000.

## For agents

- **Command:** `python -m kit.voltransform map SAMPLE SRC DST --json < points.txt`
- **Parse:** a JSON list of `[x, y, z]` in DST voxels, in input order.
- **Rerun:** safe; it only reads and caches.
- **Success:** exit 0 and one output point per input point.
- **Not a pass:** a matrix read from the catalog alone for a bent pair (it misses the spline, 3 to 20 um p90).
- **Go-ahead:** Nothing.
- **Never:** pair labels drawn on a t1 render with the t2 render of the same segment; they no longer line up.

## Tests

`python -m unittest tests.test_voltransform`: superseded filtering, path revisions, the deprecated-list fallback,
chains with inverted steps and forced revisions, spline interpolation and inverse round trip. Not covered: network
fetches (the tests inject a fetch function) and `open_volume` on a real vcd3d copy (checked by hand, below).

## History

- 2026-11-18: first version (`8e1c645`), with the landmark, mesh audit, sentinel and sheet reference readers moved to it.

## Related

- `kit/vc3d_landmarks.py`: checks the catalog matrices against landmarks.
- [meshaudit](meshaudit.md): mesh and transform audits that now read the table.
- villa volreg reader: https://github.com/ScrollPrize/villa/tree/main/foundation/volume-registration
- vc-delta3d codec: https://github.com/ScrollPrize/vc-delta3d
