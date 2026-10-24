# vc3d-audit: check that the chunks a render needs exist and decode, before a blank map is trusted

`kit/vc3d_audit.py` reads a zarr volume's headers and pyramid levels, decodes a few chunks, and checks every chunk a render along a tifxyz surface would read (local or anonymous HTTP and S3), so a hole that reads as zeros is found before a blank map is trusted.

| Field | Value |
| --- | --- |
| Id | `vc3d-audit` |
| Status | Current |
| Kind | kit module |
| Area | Data and downloads |
| Run | `from kit import vc3d_audit` |
| Code | `kit/vc3d_audit.py` |
| Tests | `tests/test_vc3d_audit.py`, `tests/test_s3retry.py`, `tests/test_cutoff_reads.py`, `tests/test_keepalive.py` |
| Needs | Python 3 standard library only; numcodecs for blosc, zstd or lz4 chunks (without it those chunks are reported as not decoded). A `libvolcomp.so` named by `KIT_VOLCOMP_LIB` only for volcomp chunks ([vc3d-io](vc3d-io.md)) |
| Runs on | Any CPU. Local synthetic audit of a 250,000-vertex surface on a 512 cubed volume: 4.2 s, 75 MB peak (measured 2026-10-16, 4-core Intel Xeon cloud container, synthetic data). Remote: the whole w035 footprint on the 9.362 um PHerc0139 scan took 4,793 requests in 135 s (2026-10-08) |
| Network | For a URL only: the store's own host (for the open-data bucket `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` or `vesuvius-challenge-open-data.s3.amazonaws.com`), anonymous, paced to 20 requests per second over 8 threads, at most 4,000 requests per audit by default. Through `HTTPS_PROXY` when set |
| Writes | Nothing |
| Go-ahead | Not needed: it reads public or local data |
| Released | Public `main` from the change that adds it (24 Oct 2026). An earlier copy ships inside the AutoPipeline release branches (`submission/progress-2026-10` from 2026-10-14 to `submission/progress-2026-10-fix4`); this one adds opt-in volcomp decoding |
| Guide | [VC3D and S3's false 404s](../vc3d-false-404.md) |
| Checked | 2026-10-24 against commit `77aea1f` |

## What it does

A zarr volume (the CT scan, a surface prediction, a rendered surface volume) is stored as many small files called chunks. When a chunk is missing, zarr libraries and VC3D (Volume Cartographer 3D, villa's segmentation and rendering tools) read it as the array's `fill_value`, usually 0, with no error. A render over a missing chunk is then blank there, and an ink map over that blank patch means nothing. Masked scans leave out empty chunks on purpose (the air outside the scroll), so "some chunks are missing" is normal; what matters is whether chunks under the surface you render are missing.

The audit answers that in up to three parts. **Headers and levels:** every pyramid level of an OME-Zarr group has its header (`.zarray` or `zarr.json`), the shapes agree with the multiscales scale transforms, each level holds at least one chunk, and a few chunks per level decode to the right number of bytes. **Footprint** (with a surface): every chunk that holds a surface sample, or lies within `margin` voxels of one, is checked at the levels asked; a chunk missing on the surface is a defect, one missing only in the margin is a warning. **Render** (with a rendered stack): the share of zero samples inside the stack's footprint, layer by layer. These are the failure classes that [sgsllc-jr/zarr-pyramid-audit](https://github.com/sgsllc-jr/zarr-pyramid-audit) looks for (read 7 Oct 2026), plus the per-surface presence check.

Every chunk answer is `present`, `missing` or `unknown`. Unknown means a request failed, S3 answered 403, or the request cap was reached; any unknown chunk under a surface makes the verdict `incomplete`, never `clean`. Over S3 a 404 counts as missing only when S3 names `NoSuchKey`: S3 also answers 404 `NoSuchBucket` for chunks it holds, and those are asked again ([s3retry](s3retry.md)). Sharded zarr v3 arrays are checked inner chunk by inner chunk through each shard's index.

It reads and reports only. It does not repair a volume, fetch missing data, or say anything about ink. A `clean` verdict means the chunks a render needs exist and the sampled ones decode; it is not evidence that the surface is on papyrus or in the right frame.

In this repository it is a library: [vc3d-cache](vc3d-cache.md) uses its stores and `presence` to check VC3D's empty-chunk markers. An agent tool that runs it from the command line, and AutoPipeline's use of it before each render, live in the AutoPipeline release, not on `main`.

## When to use it

- Before trusting any render, trace or ink map made from a remote or newly downloaded volume: `audit(VOLUME, surface=SURFACE)` with the surface you render.
- On a part of a larger trace, with `grid_box`.
- After a render, with `render`, to see how much of the stack is zeros inside its footprint.
- When a level, a scale transform or a codec of a new volume looks wrong: a headers-only audit (no `surface`) takes seconds.

Do not use it:

- To repair VC3D's cache after false 404s: use [vc3d-cache](vc3d-cache.md) (`python -m kit vc3dcache`), which checks and deletes the empty-chunk markers VC3D keeps.
- To download a volume: use [fetch](fetch.md).
- To check a segment's own grid (holes, folds, stretch): use [tifxyz](tifxyz.md).

## Quick start

```python
from kit import vc3d_audit
VOLUME = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr"
report = vc3d_audit.audit(VOLUME, decode_n=1)          # add surface="SURFACE" to check the chunks under a surface
print(report["verdict"], report["defects"], report["warnings"], report["requests"])
```

- `VOLUME`: an OME-Zarr group or a zarr array, as a local folder, an `https://` URL or an `s3://` URL.
- `SURFACE`: a tifxyz folder (`x.tif`, `y.tif`, `z.tif`) in that volume's level-0 voxel frame.

A headers-only run on that scan (`decode_n` 1, 2026-10-16) found six levels, level 0 `[20974, 6621, 6621]` in 128 cubed uncompressed uint8 chunks, every level populated and one chunk per level decoded to 2,097,152 bytes: verdict `clean`, 21 requests.

On a synthetic 64 cubed two-level volume (16 cubed gzip chunks) with one chunk removed under a 9 x 9 plane and one removed in the margin, with `margin=8`, the report held (excerpt, 2026-10-16):

```
 "defects": [
  "level 0: 1 of 9 chunks under the surface are missing; reads there return fill_value"
 ],
 "warnings": [
  "level 0: 1 chunks within 8 voxels of the surface (not on it) are missing: the mask, or a hole the outer layers reach"
 ],
    "chunks_on_surface": 9,
    "chunks_in_margin": 39,
    "present": 46,
    "missing_on_surface": 1,
    "unknown": 0,
 "verdict": "defects",
```

It worked when the report has a `verdict`. Only `"clean"` passes; `defects` and `incomplete` must be read.

## Checks and controls

- **The audit can fail, and the tests show it.** `tests/test_vc3d_audit.py` removes a chunk under a surface (verdict `defects`), removes one only in the margin (a warning, verdict `clean`), empties a level, contradicts a scale transform, removes a header, overwrites a chunk with bytes that do not decode, leaves an inner chunk out of a shard, and caps the requests (verdict `incomplete`). Each case gives the expected verdict.
- **Frame control.** A surface in the wrong frame or at the wrong `scale_segmentation` puts samples outside the array, which is a defect (`81 of 81 surface samples lie outside the array [64, 64, 64]` on the synthetic far plane, 2026-10-16). A clean audit with every sample inside the array is weak evidence of the frame; use `frame` and `check_surface` for the real check.
- **Unknown is not clean.** Chunks past `max_requests`, failed requests and S3 403s stay `unknown`; any unknown chunk under the surface makes the verdict `incomplete` (synthetic run with `max_requests` 5: 5 present, 43 unknown, `incomplete`).
- **False 404s.** Against a local S3-like server that answers the first request for every key with 404 `NoSuchBucket`, the audit asked again and found the same holes as the local audit: 108 requests, `false_404s` 5, and the note that none was taken as missing (synthetic, 2026-10-16).
- **A real pass, for scale.** w035 on the 9.362 um PHerc0139 scan: six levels consistent with their scale transforms, 2,577 chunks on the surface and 2,199 in the margin, all present, clean (measured 2026-10-08 in one cloud container).

Claim label: Sourced fact, for which chunks the store held and which decoded at the time of the run; a verdict says nothing about ink or about whether the surface is on papyrus.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `audit(location, surface=None, check_levels=None, scale_segmentation=1.0, margin=DEFAULT_MARGIN, max_points=DEFAULT_MAX_POINTS, max_requests=DEFAULT_MAX_REQUESTS, decode_n=2, render=None, store=None, progress=None, grid_box=None, **store_kw)` | The report dict under Outputs | `AuditError` (no metadata, bad JSON, a header read that failed, an empty `grid_box`, grids of different sizes); `vc3d_io.IOFormatError` for an unreadable TIFF | The whole audit. `location` None with `render` counts zeros only. `check_levels` holds level names (str or int). `store_kw` goes to `HttpStore` (`rate`, `workers`, `timeout`, `retries`, `opener`, `listing`, `false_404_tries`); `store` replaces the store; `progress` takes one str per step |
| `AuditError` | | | `ValueError` subclass: the store cannot be audited as given |
| `open_store(location, **kw)` | `HttpStore` for an `http://`, `https://` or `s3://` URL (with `kw`), else `LocalStore` | `AuditError` when a local path is not a directory | |
| `LocalStore(root)` | A store with `read(key, start=None, length=None)` (bytes, a range with `start` and `length`, the tail with negative `start`, or None when missing), `states(keys, budget=None, progress=None)` (`{key: "present" or "missing"}`), `chunk_keys(prefix, limit)` (up to `limit` chunk files, sorted) | Nothing of its own | `remote` is False and `requests` stays 0 |
| `HttpStore(url, rate=DEFAULT_RATE, workers=8, timeout=30.0, retries=2, opener=None, listing=None, false_404_tries=s3retry.TRIES)` | A store with the same `read`, `states` and `chunk_keys`, plus `state(key)` and the counters `requests` and `false_404s` | `read` raises `AuditError` for a status other than 200, 206 or 404, or when every attempt failed | Anonymous, paced to `rate` per second over `workers` threads. Network errors, cut-off reads, 429 and 5xx are retried `retries` times; a false 404 up to `false_404_tries` (10) times; a HEAD 404 is confirmed with a one-byte GET; 403 is `unknown`. `chunk_keys` lists through S3 ListObjectsV2 and returns None when the host is not S3. `opener` defaults to the kept-alive opener of `kit/keepalive.py` |
| `s3_https(url)` | `https://BUCKET.s3.amazonaws.com/KEY`, no trailing slash | Nothing | For `s3://BUCKET/KEY` |
| `s3_listing(url)` | `(endpoint, key prefix)` for an `amazonaws.com` URL, virtual-host or path style; `(None, None)` otherwise | Nothing | |
| `array_meta(store, path)` | Header dict (`zarr_format`, `path`, `shape`, `chunks`, `dtype`, `itemsize`, `fill_value`, `order`, `sep`, `key_prefix`, `codec`, `inner`; v2 adds `compressor`, `filters`; v3 adds `codecs`, and for sharding `inner_codecs`, `index_codecs`, `index_location`), or None when there is no array header | `AuditError` for bad JSON or a failed remote read | `path` "" is the store root |
| `header_problems(meta)` | List of str defects | Nothing | Shape and chunks of different length or not positive integers, an unknown data type, a shard shape not a multiple of the inner chunk shape |
| `chunk_key(meta, idx)` | The chunk's key, such as `0/2/1/1` or `2/c/1/0` | Nothing | Follows the separator and the v3 `c/` prefix |
| `key_index(meta, key)` | The chunk index tuple a key names, or None | Nothing | |
| `grid_counts(meta)` | Chunks per axis (ceiling of shape over chunks) | Nothing | |
| `group_attrs(store)` | `(2 or 3, attributes)`, `(2, {})` for a bare `.zgroup`, `(None, None)` without metadata | `AuditError` for bad JSON | v3 attributes under `ome` are unwrapped |
| `levels(store)` | `([{"name", "meta", "scale", "translation", "listed"}], info)`, finest first; a bare array is one level named "" | `AuditError` without metadata, or for a group with no levels | Without multiscales, levels `0` to `15` are read until one has no header |
| `level_problems(lv, info)` | `(defects, notes)`, lists of str | Nothing | Listed levels without headers, axes count, shapes that contradict the scales by more than 1 voxel (defects); data types that differ and levels that do not halve when there are no scales (notes) |
| `factors(lv, x, base)` | Voxels of level `x` per base voxel along z, y, x | Nothing | From the scale transforms, else from the shapes |
| `decode(meta, raw, inner=False)` | `(ok, detail)`: ok True, False (does not decode, or wrong length) or None (codec not decoded here) | Nothing; codec errors are caught | v2 arrays with `filters` are decompressed only, and reported as ok |
| `shard_index(meta, store, key)` | `[(offset, nbytes) or None]` per inner chunk, C order; None when the shard is missing | `AuditError` for an index shorter than expected | Reads the index from the shard's end or start |
| `surface_samples(surface, scale_segmentation=1.0, max_points=DEFAULT_MAX_POINTS, grid_box=None)` | `(samples, spacing, info)`: samples `(x, y, z, row, col)` in level-0 voxels; spacing, the 95th percentile of neighbor distances along rows; info `grid_rows_cols`, `stride`, `samples`, `spacing_voxels`, `grid_box` | `AuditError` for x, y, z grids of different sizes or an empty `grid_box`; `vc3d_io.IOFormatError` for a bad TIFF | Invalid vertices (-1, -1, -1), NaN or all zero are skipped |
| `footprint(samples, spacing, shape, chunks, factor, margin=DEFAULT_MARGIN)` | `(core, halo, outside)`: core `{chunk index: [r0, r1, c0, c1]}`, halo set, count of samples outside the array | Nothing | Core: within half the spacing plus 1 voxel of a sample; halo: within `margin` more |
| `presence(store, meta, core, halo, budget, progress=None)` | `({chunk index: state}, requests used)` | Nothing of its own (a bad shard index makes its chunks unknown) | Core first under the budget; one index read per shard for sharded arrays |
| `decode_some(store, meta, idxs, limit)` | List of `{"chunk", "key", "ok", "detail"}` | Nothing (read errors become ok None) | Up to `limit` chunks |
| `populated(store, meta, limit=3)` | `(True, False or None, sample keys)` | Nothing of its own | None when the store cannot list |
| `probe(store, meta, budget)` | `({key: state}, requests)` | Nothing of its own | Chunks at a 3 x 3 x 3 lattice near the grid's middle, for stores that cannot list |
| `render_zeros(path)` | Dict of the render fields under Outputs | `AuditError` when the path is neither a zarr nor a layer folder; `vc3d_io.IOFormatError` for a bad TIFF | Reads every layer twice |

Constants: `PRESENT`, `MISSING`, `UNKNOWN` (`"present"`, `"missing"`, `"unknown"`), `DEFAULT_MARGIN` 60, `DEFAULT_MAX_POINTS` 250,000, `DEFAULT_MAX_REQUESTS` 4,000, `DEFAULT_RATE` 20.0, `META_FILES` (`.zarray`, `.zattrs`, `.zgroup`, `.zmetadata`, `zarr.json`), `EMPTY` (2 to the 64 minus 1, a shard index entry of an absent inner chunk), `V3_SIZES` (bytes per zarr v3 data type).

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Volume | zarr v2 (`.zgroup`, `.zattrs` with OME `multiscales`, levels with `.zarray`; dot or slash keys) or v3 (`zarr.json`, attributes under `ome` or at the top; default `c/` keys or v2-style keys; `sharding_indexed`), or a bare array | Local folder, `http(s)://` or `s3://`. v2 data types like `|u1` or `<u2`; v3 types in `V3_SIZES`. Codecs: v2 none, zlib, gzip (standard library), anything else through numcodecs; v3 bytes, transpose, endian, crc32c, gzip, and zstd, blosc, lz4 through numcodecs |
| Surface | tifxyz folder: `x.tif`, `y.tif`, `z.tif` float grids of one size (row by column), `meta.json` not read | Coordinates are voxel x, y, z of the volume's level 0, after `scale_segmentation`. A vertex of (-1, -1, -1), NaN or (0, 0, 0) is invalid. `grid_box` counts grid rows and columns, half-open |
| Render | A zarr whose last three axes are layer, row, column (its first level is read), or a folder of numbered layer TIFFs | 0 means no sample; a pixel 0 in every layer is off the surface |

Find open-data volumes and surfaces with `python -m kit find SCROLL` ([find](find.md)). A level-0 mesh audited at a coarser level is mapped with that level's scale factors, so give level-0 coordinates and pick the level with `levels`.

## Outputs

`audit` returns one dict. Progress lines (`reading headers`, `level 0: looking for chunks`, ...) go to `progress` when it is given.

| Field | Type | Meaning |
| --- | --- | --- |
| `verdict` | str | `defects` when any defect, else `incomplete` when any footprint chunk is unknown, else `clean`. Warnings do not change it |
| `defects`, `warnings`, `notes` | list of str | Sentences, each naming the level (see Failure modes) |
| `volume`, `store` | str | The volume as read (an `s3://` URL shown as https) and `local` or `remote`; absent for a render-only audit |
| `kind`, `multiscales` | str, bool or null | `group` or `array`; whether the group has OME multiscales (null for an array) |
| `levels[]` | list | Per level: `level` (name), `header` (bool), and with a header `shape`, `chunks`, `dtype`, `codec`, `fill_value`, `zarr_format`, `scale`, `chunk_grid` (chunks per axis, null when the header is bad), `inner_chunks` (sharded), `translation` (when given), `populated` (true, false, or null when the store cannot list), `probe` (`N of M lattice chunks present`, when probed), `sample_keys` (up to 3), `decoded` (without a surface) |
| `footprint` | object | With `surface`: `surface`, `scale_segmentation`, `margin`, `grid_rows_cols`, `stride`, `samples`, `spacing_voxels` (level-0 voxels), `grid_box` (when given), and `levels[]` |
| `footprint.levels[]` | list | Per checked level: `level`, `chunks_on_surface`, `chunks_in_margin`, `factor_zyx`, `present`, `missing_on_surface`, `missing_in_margin`, `unknown`, `samples_outside` (when any), `missing_on_surface_chunks` (first 50: `chunk`, `voxels_zyx` as [start, end) per axis in that level's voxels, `grid_rows`, `grid_cols` of the surface that reach it), `missing_in_margin_chunks` (first 50 indices), `decoded` |
| `decoded[]` | list | `chunk` (index), `key`, `ok` (true, false or null), `detail` (`4096 bytes`, `does not decode: ...`, `decodes to N bytes, expected M`, or why it was not decoded) |
| `requests` | int | HTTP requests made in all (0 for a local store) |
| `false_404s` | int | Present only when S3 gave 404s for keys that exist; each was asked again |
| `render` | object | With `render`: `path`, `layers`, `height`, `width`, `footprint_pixels`, `zero_fraction` (per layer, share of the footprint, 4 decimals), `centre_layer`, `centre_zero_fraction`, `max_zero_fraction`, `centre_zero_box_rows_cols` (when the center layer has zeros), or `note` when every sample is 0 |

It prints nothing and writes no file.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `PATH: not a directory` | `open_store` on a local path that is not a folder | Fix the path, or give a URL |
| `LOCATION: no zarr metadata at its root (.zarray, .zgroup, .zattrs or zarr.json)` | A folder or URL with no zarr metadata (also what a wrong remote URL gives, since its keys answer 404) | Check the URL; point at the root of the `.zarr` |
| `LOCATION: a zarr group with no levels (no multiscales and no array named 0)` | A group whose levels are not listed and not numbered from 0 | Audit the array folder itself, or fix the multiscales |
| `KEY: not valid JSON (...)` | A header or attributes file that does not parse | The store is damaged; fetch the header again |
| `URL/KEY: HTTP 403` or `URL/KEY: request failed (...)` | A header read that the server refused, or that failed after every retry (network down, or a false 404 ten times: `HTTP 404 NoSuchBucket on 10 attempts (S3 lists such keys as present)`) | Check the network and the URL; run again later |
| `SURFACE: x, y and z grids differ in size` | The tifxyz grids are not one shape | Use a whole tifxyz |
| `grid_box [r0, r1, c0, c1] holds no vertex of the R x C grid` | The box lies outside the surface's grid | Fix the box (rows and columns, half-open) |
| `PATH: neither a zarr nor a folder of numbered layer TIFFs` | `render` is not a stack | Give the render's zarr or its layer folder |
| `KEY: shard index has N bytes, expected M` | A truncated shard; caught, and its chunks counted `unknown` | Fetch the shard again; the verdict is `incomplete` |
| Warning `chunk [...] not decoded (codec NAME not decoded here)` | A zarr v3 codec this module does not decode | Not a defect; decode it with zarr if it matters |
| Warning `chunk [...] not decoded (compressor 'blosc' needs numcodecs (pip install numcodecs), ...)` | numcodecs is not installed | `python -m pip install numcodecs` |
| Defect `level N: header but no chunks; every read returns fill_value V` | The level is empty (seen through a listing) | The volume is incomplete; use another level or volume |
| Defect `level N: listed in the multiscales but has no header` | A level named in the multiscales has no `.zarray` or `zarr.json` | Do not read that level |
| Defect `level N: shape [...] contradicts its scale [...] (expected about [...] from level M); coordinates would shift between levels` | The scale transform and the shapes disagree by more than 1 voxel | Do not mix levels of this volume; report it to its maker |
| Defect `level N: K of M chunks under the surface are missing; reads there return fill_value` | Holes under the surface | Do not trust a render there; look at `missing_on_surface_chunks` for where, trim the surface (`trim`) or use another volume |
| Defect `level N: K of M surface samples lie outside the array [...] (wrong frame, level or scale_segmentation?)` | The surface is in another frame or scale | Check `scale_segmentation`, `levels` and the frame |
| Defect `level N: not in this volume (levels [...])` | `levels` names a level the volume lacks | Pick from the listed levels |
| Defect `SURFACE: no valid vertex` | Every vertex in the box is invalid | Check the surface or `grid_box` |
| Defect `level N: chunk [...] does not decode: ...` or `decodes to N bytes, expected M` | A damaged chunk | Fetch it again, or report it |
| Warning `level N: K chunks within M voxels of the surface (not on it) are missing: the mask, or a hole the outer layers reach` | Missing chunks only in the margin | Usually the mask of a masked scan; check when the render's outer layers matter |
| Warning `level N: K chunks unchecked (request cap or failed requests)`, verdict `incomplete` | `max_requests` reached, or requests failed | Raise `max_requests`, audit a smaller `grid_box`, or check the network |
| Warning `level N: none of M chunks probed near the middle of the grid exists (...); give a surface to decide` | A store that cannot list, whose probes found nothing | Audit with `surface` |
| Warning `render: X% of the footprint is 0 on the center layer (rows and columns [...]): missing chunks, the mask or the volume's edge` | Zeros inside the render's footprint | Audit the volume with the surface; look at the render |

## How it works

1. **Open the store.** A URL becomes an `HttpStore` (`s3://` rewritten to the bucket's https host), a folder a `LocalStore`. S3 hosts can be listed (ListObjectsV2); other HTTP hosts cannot.
2. **Headers and levels** (`levels`, `level_problems`). Read `.zarray` or `zarr.json` at the root; else the group's attributes and every dataset of the first OME multiscales entry with its scale and translation; else numbered levels `0` to `15`. Compare each level's shape with the base level's shape divided by the scale ratio (tolerance 1 voxel).
3. **Populated** (`populated`, `probe`). List up to 3 chunk keys under each level. Where the store cannot list and there is no surface, check the chunks at a 3 x 3 x 3 lattice at a quarter, a half and three quarters of each axis. With no surface, decode up to `decode` listed chunks per unsharded level.
4. **Surface samples** (`surface_samples`). Stride the tifxyz grid evenly so at most `max_points` vertices are kept (stride = ceiling of the square root of area over `max_points`), skip invalid vertices, multiply by `scale_segmentation`, and take the 95th percentile of neighbor distances along rows (from up to 20,000 pairs) as the spacing.
5. **Footprint** (`footprint`). For each checked level, scale the samples by `factors` into that level's voxels. Core chunks lie within `spacing x max(factor) / 2 + 1` voxels of a sample (the space between samples plus the trilinear neighbor); halo chunks within `margin` voxels more. Sharded arrays use the inner chunk shape.
6. **Presence** (`presence`). Core chunks first, then halo, under the shared `max_requests` budget: a HEAD per chunk over HTTP (8 threads, paced to `rate`), `is_file` locally, or one index read per shard. A 404 HEAD is confirmed with a one-byte GET because HEAD answers carry no S3 error code.
7. **Decode** (`decode_some`, `decode`). Up to `decode` present core chunks per checked level are downloaded, decompressed and checked against chunk shape times item size.
8. **Render zeros** (`render_zeros`). OR every layer's nonzero mask into a footprint, then count each layer's zeros inside it; the center layer is index `layers // 2`.
9. **Verdict.** Defects, then unknown footprint chunks, decide `defects`, `incomplete` or `clean`.

Request retries: a network error, a cut-off read, 429 or 5xx is retried `retries` (2) times with a back-off of 0.5 s doubling up to 8 s; a false 404 is asked again up to 10 times (`s3retry.TRIES`) with 0.1 s doubling up to 2 s. Requests carry the user agent `kit-vc3d-audit` and a 30 s timeout.

## Cost and time

All measured 2026-10-16 in a 4-core Intel Xeon cloud container (lscpu: 2.80 GHz), unless marked.

| Run | Requests | Time |
| --- | --- | --- |
| Synthetic 512 cubed volume, 64 cubed chunks, 500 x 500 plane (250,000 samples, 128 chunks), local | 0 | 4.2 s, 75 MB peak RSS |
| The holey synthetic volume over a local S3-like server, a false 404 on every key's first request | 108 | 2.1 s (`rate` 0) |
| PHerc0139 9.362 um scan, headers only, `decode_n` 1 (six 2 MB chunks), through the container's proxy | 21 | 35 s wall, 55 MB peak RSS |
| w035 on that scan, whole footprint, 60 voxel margin (2026-10-08) | 4,793 | 135 s |
| w035 in the 2.399 um scan, `grid_box` [500, 560, 450, 510] (2026-10-08) | 417 | 14 s |

A remote audit is bounded by `rate`: 4,000 requests at 20 per second take at least 200 s. It is CPU and network only, never a GPU job, and rents nothing.

## For agents

- **Command:** In Python: `vc3d_audit.audit(VOLUME, surface=SURFACE)` (add `grid_box=[r0, r1, c0, c1]` for part of a trace, `check_levels=[0]` for the level you render). No command line on `main`.
- **Parse:** `verdict`; `defects`, `warnings`; per level in `footprint.levels[]`, `missing_on_surface` and `missing_on_surface_chunks`; `requests`, `false_404s`.
- **Rerun:** Safe; it only reads the volume.
- **Success:** `"verdict": "clean"`.
- **Not a pass:** `incomplete` (chunks left unknown) taken as clean; a clean verdict taken as evidence that the surface is on papyrus or in the right frame.
- **Go-ahead:** Nothing; it reads public or local data.
- **Never:** Trust a render or an ink map over chunks the audit lists as missing on the surface.

## Tests

```bash
python -m unittest tests.test_vc3d_audit -v
```

`tests/test_vc3d_audit.py` builds small OME-Zarr groups with `tests/vc3d_fakes.py` and checks each defect class with the verdict it must give: a chunk removed under a surface and in the margin, an empty level, a contradicted scale, a missing header, a chunk that does not decode, sharded arrays with an absent inner chunk, a request cap, render zeros, a far plane outside the array, and the HTTP store against a local server (the same answers as a local read, listing and probes, range reads of shards, failures, `s3://` URLs). `tests/test_s3retry.py`, `tests/test_cutoff_reads.py` and `tests/test_keepalive.py` cover its store's retries and connections. They use local data and servers only.

## History

- 2026-10-24: on public `main` as a library, for the false-404 tools, with opt-in volcomp decoding (`77aea1f`).
- 2026-10-15: the copy in AutoPipeline 0.1.4 (`603fe14`, branch `submission/progress-2026-10-fix4`), first released inside the AutoPipeline package on `submission/progress-2026-10` on 14 October. The first version, of 8 October, read headers, levels, decoding, the footprint under a surface and render zeros.

## Related

- [vc3d-cache](vc3d-cache.md): checks VC3D's empty-chunk markers with this module's stores.
- [s3retry](s3retry.md): the false-404 rule its HTTP store follows.
- [keepalive](keepalive.md): the kept connections its HTTP store reads through.
- [vc3d-io](vc3d-io.md): the TIFF and zarr readers and the volcomp decoder it uses.
- [tifxyz](tifxyz.md): checks of a segment's own grid.
- [sgsllc-jr/zarr-pyramid-audit](https://github.com/sgsllc-jr/zarr-pyramid-audit): the pyramid failure classes it also looks for.
