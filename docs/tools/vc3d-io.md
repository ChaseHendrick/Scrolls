# vc3d-io: standard-library readers for TIFF, zarr, npy and PNG

`kit/vc3d_io.py` reads and writes the images and volumes VC3D's tools write or read (TIFF and BigTIFF layers and tifxyz grids, local zarr arrays and OME-Zarr groups, `.npy` maps, PNG previews) with the Python standard library alone, plus pixel statistics and contrast stretching.

| Field | Value |
| --- | --- |
| Id | `vc3d-io` |
| Status | Current |
| Kind | kit module |
| Area | Data and downloads |
| Run | `from kit import vc3d_io` |
| Code | `kit/vc3d_io.py` |
| Tests | `tests/test_vc3d_io.py`, `tests/test_vc3d_volcomp.py` (volcomp decoding) |
| Needs | Python 3 standard library only. numcodecs only for zarr chunks compressed with blosc, zstd or lz4; numpy only for `raster_from_numpy`; a `libvolcomp.so` named by `KIT_VOLCOMP_LIB` only for `volcomp_lib` and `volcomp_decode` (built from villa's `volume-cartographer/libs/volcomp`, see What it does) |
| Runs on | Any CPU, one thread. Pure-Python decoding is slow: a 2,000 x 2,000 8-bit LZW TIFF took 8.1 s and a float32 LZW TIFF with the floating-point predictor 30.6 s, against 0.03 s uncompressed; an 8 MB zarr box read 0.25 to 0.38 s (measured 2026-10-16, 4-core Intel Xeon 2.80 GHz cloud container, synthetic data) |
| Network | None. It reads local files only; `volcomp_source` recognizes a URL by its text and never opens it, and `volcomp_decode` decodes bytes it is handed |
| Writes | Only `write_tiff(path, raster)` writes, to the path it is given (replacing any file there). Every other function reads files or bytes and returns values |
| Go-ahead | Not needed |
| Released | Public `main` from the change that adds it (24 Oct 2026). Older copies ship inside the AutoPipeline release branches (`submission/progress-2026-10` to `-fix4`); see below |
| Guide | [VC3D and S3's false 404s](../vc3d-false-404.md) (the tools that read through it) |
| Checked | 2026-10-24 against commit `77aea1f` |

## What it does

kit's VC3D cache and chunk tools ([vc3d-audit](vc3d-audit.md), [vc3d-cache](vc3d-cache.md)) have to run in any Python, including one without numpy, tifffile or zarr. They still need to look at what VC3D writes and reads: the layer TIFFs of a render, the x, y and z grids of a **tifxyz** surface (three float32 TIFFs giving each grid cell's position, -1 where there is none), a render's OME-Zarr output, and the ink maps villa writes as TIFF or `.npy`. This module reads those formats with `struct`, `zlib` and `array` only, and writes small TIFFs and PNG previews.

What it reads: the first (or a given) page of a single-sample TIFF or BigTIFF, 8, 16 or 32-bit integer or 32 or 64-bit float, in strips or tiles, uncompressed or LZW, deflate or PackBits, with the horizontal predictor (on float samples too) or the floating-point predictor; 2-D and 3-D `.npy` files; local zarr v2 arrays and unsharded zarr v3 arrays, uncompressed, zlib or gzip natively and blosc, zstd or lz4 through numcodecs; OME-Zarr groups (a **pyramid** of levels, finest first); 8-bit gray or RGB PNG. It holds an image as a **Raster**: height, width, a **kind** (`u8`, `i8`, `u16`, `i16`, `u32`, `i32`, `f32` or `f64`) and the samples in row order in an `array.array` (or `bytes` for `u8`). On top it gives pixel statistics, block reduction and contrast stretch, and `volcomp_source`, which names a lossy volcomp copy of a scan.

A **volcomp copy** is one of Forrest McDonald's compressed copies of the open-data scans under `https://dl.ash2txt.org/community-uploads/forrest/volcomp/`, made with the `volcomp` codec (`SuperOptimizer/volume-compressor`). They are lossy: at q 8, the setting published at level 0, released 2.5D ink models lost about a quarter of their ink and papyrus separation on two PHerc0139 segments (Community report, pscamillo, 2026-09-10, `https://github.com/pscamillo/volcomp-ink-curve`), and villa PR #1704, which added VC3D support for them, says not to run the released models on them. `volcomp_source` names such a volume, so a caller can refuse it as an ink input.

**Decoding volcomp chunks (opt in).** kit has no volcomp decoder of its own. When the environment variable `KIT_VOLCOMP_LIB` names a shared library built from villa's vendored copy of the codec (`volume-cartographer/libs/volcomp`, which exports `volcomp_lib_decode`), for example with `cc -O2 -std=c11 -fPIC -shared -o libvolcomp.so volcomp_lib.c -lm`, `volcomp_decode(raw)` turns one volcomp chunk into its 128 x 128 x 128 uint8 voxels (2,097,152 bytes, z-major). `volcomp_lib()` loads that library once per path through `ctypes`. Only the zarr v3 codec chain of [vc3d-audit](vc3d-audit.md) (`_v3_bytes_codecs`) calls it; this module's own `ZArray` still refuses a volcomp array (`codec volcomp not supported`). What comes back is the lossy copy, never the scan.

It does not read remote stores, sharded zarr v3 (use the zarr package), JPEG, zstd, LZMA or WebP TIFFs, multi-sample (RGB) TIFFs, or Fortran-ordered `.npy`. It does not check what it reads against anything: a missing zarr chunk reads as the array's fill value and a short TIFF strip reads as zeros, both without an error. An ink map it reads is model output, not a reading, and its statistics describe pixel values, not ink.

### The copies in the AutoPipeline release

The AutoPipeline release branches carry older copies under `submissions/<id>/autopipeline/kit/vc3d_io.py`. Against this file, `submission/progress-2026-10-fix4` and `-fix3` ignore a zarr v3 `transpose` codec in any order, keep a `"NaN"` or `"Infinity"` fill value as text (so a box over a missing chunk fails with `struct.error`), mix in other rows in `downsample` with a factor wider than the image, and have no `volcomp_lib`, `volcomp_decode` or `KIT_VOLCOMP_LIB`. `-fix2` also lacks the floating-point predictor and predictor 2 on float samples; `submission/progress-2026-10` and `-fix1` also lack `volcomp_source`, `VOLCOMP_PREFIX` and `VOLCOMP_COST`.

## When to use it

- Kit code that must run without numpy, such as the VC3D cache and chunk tools.
- Reading a VC3D render's layer TIFFs (`layer_files`), a tifxyz grid (`is_tifxyz`, `read_tiff`), a local OME-Zarr render (`zarr_levels`, `open_zarr`, `ZArray.read`), or an ink map in `.npy`.
- Making a small PNG preview of a Raster (`downsample`, `to_u8`, `png_bytes`), or summary numbers for one (`stats`).
- Before rendering ink inputs from a volume: `volcomp_source(volume)` says whether it is a lossy volcomp copy.
- Decoding the chunks of a volcomp copy for geometry or an audit: `volcomp_decode(raw)` with `KIT_VOLCOMP_LIB` set (normally through [vc3d-audit](vc3d-audit.md)).

Do not use it:

- When numpy and tifffile or zarr are there and the image is large: use them (`tifffile.imread`, `zarr.open`), which decode in C.
- For remote volumes: use the chunk store of [vc3d-audit](vc3d-audit.md), which retries S3's false 404s ([s3retry](s3retry.md)), or fetch the zarr first with [fetch](fetch.md).
- For sharded zarr v3: use the zarr package; this module refuses them ([vc3d-audit](vc3d-audit.md) checks their chunks).
- To check that a local zarr has every chunk: missing chunks read as fill here. Use [vc3d-audit](vc3d-audit.md).
- To score an ink map: use [auc](auc.md) and its reverse-depth control.

## Quick start

From the repository root (writes two files under `/tmp/vc3d-io-qs`; any folder works):

```bash
mkdir -p /tmp/vc3d-io-qs
python3 - <<'EOF'
import array
from kit import vc3d_io
OUT = "/tmp/vc3d-io-qs"
# a 3 x 4 float map in 0..1, written and read back with the standard library only
m = vc3d_io.Raster(3, 4, "f32", array.array("f", [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1, 0]))
vc3d_io.write_tiff(f"{OUT}/map.tif", m)
print(vc3d_io.tiff_info(f"{OUT}/map.tif"))
r = vc3d_io.read_tiff(f"{OUT}/map.tif")
s = vc3d_io.stats(r, threshold=vc3d_io.prob_threshold(r.kind))
print(s["shape"], s["kind"], s["min"], s["max"], s["mean"], s["above_threshold_fraction"])
grey, (lo, hi) = vc3d_io.to_u8(r)
open(f"{OUT}/map.png", "wb").write(vc3d_io.png_bytes(r.h, r.w, grey))
print(vc3d_io.read_png_gray(open(f"{OUT}/map.png", "rb").read())[:3])
EOF
```

It printed, on 2026-10-16 (0.12 s):

```
{'height': 3, 'width': 4, 'kind': 'f32', 'samples_per_pixel': 1, 'compression': 'none', 'tiled': False, 'bigtiff': False, 'bytes': 182}
[3, 4] f32 0.0 1.0 0.4583 0.41667
(3, 4, 1)
```

It worked when the TIFF reads back with the shape and kind it was written with, and the PNG decodes to the same height and width. For a real map, replace the Raster with `vc3d_io.read_tiff("MAP.tif")` or `vc3d_io.read_npy("MAP.npy")`, where `MAP` is an ink map file.

## Checks and controls

- **Each decoder can fail its tests.** The tests decode data whose values are known (a decoder that drops a row, swaps bytes or misreads a type fails), a real VC3D layer TIFF (tiled, LZW, predictor 2), and files written by tifffile and by Pillow with libtiff as a second opinion (tiles, predictors, deflate, PackBits, big-endian, BigTIFF, predictor 3).
- **A second opinion on your own file.** Where numpy and tifffile are installed, compare: `list(vc3d_io.read_tiff(P).data) == tifffile.imread(P).ravel().tolist()`. On 2026-10-16 this held, every pixel equal, for 2,000 x 2,000 synthetic files written by tifffile 2026.10.15: uncompressed u8 and f32, deflate with predictor (u8, u16), LZW with and without predictor (u8), and LZW with predictor 3 (f32). A zarr 3.4.1 group (gzip, two levels), a zstd v3 array and a zstd v2 array read back equal to what zarr wrote.
- **What it cannot catch.** A missing zarr chunk reads as fill, a TIFF strip cut short reads as zeros for the missing bytes, and a damaged LZW strip can decode to wrong or zero pixels (all seen on 2026-10-16 with synthetic files, no error raised). A zarr v3 `transpose` codec used to be accepted but not applied (a 2 x 3 array with order (1, 0) read back as `[0, 3, 1, 4, 2, 5]` where zarr gives `[0, 1, 2, 3, 4, 5]`); since 16 October 2026 any order other than C is refused instead. Use [vc3d-audit](vc3d-audit.md) for completeness, and the comparison above when a value matters.
- **volcomp decoding cannot pass silently.** A nonzero status from the library raises `IOFormatError` instead of returning zeros (`tests/test_vc3d_volcomp.py`, with a stand-in library). The lossless round trip through a real `libvolcomp.so` runs only when `KIT_VOLCOMP_LIB` is set; it is skipped without one (none was built for this page), so the real decoder is not checked here.

Claim label: None. It reads and writes files; its statistics describe pixel values. An ink map read through it is model output, not a reading; the volcomp loss figures it quotes are a Community report (pscamillo, 2026-09-10).

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `IOFormatError` | A `ValueError` subclass | Nothing | Every refusal of this module |
| `Raster(h, w, kind, data)` | A Raster with `.h`, `.w`, `.kind`, `.data`; methods `.at(r, c)` (one sample), `.row(r)` (one row) and `.floats()` (all samples as float32) | `IOFormatError` when `len(data)` is not `h * w` | `data`: an `array.array` of the kind's type code (`KINDS`), or `bytes` for `u8` |
| `as_floats(data)` | `array.array("f")` | Nothing | Bytes are 8-bit samples (0 to 255), never raw float bytes. An `array.array("f")` is returned as it is, not copied |
| `lzw_decode(data)` | bytes | Nothing; damaged input gives short or wrong output | TIFF LZW, most significant bit first, early change, as libtiff and tifffile write it |
| `packbits_decode(data)` | bytes | Nothing | TIFF PackBits |
| `tiff_tags(raw, page=0)` | `(order, tags)`: `"<"` or `">"`, and a dict tag number to tuple of ints | `IOFormatError` for a file that is not a TIFF, a magic other than 42 or 43, or a missing page; `struct.error` or `IndexError` for a cut-off file | Classic TIFF and BigTIFF. Tags of other types (text, rationals, floats) are skipped |
| `tiff_info(path)` | dict: `height`, `width`, `kind`, `samples_per_pixel`, `compression` (a name such as `none`, `lzw`, `deflate`, `packbits`, `jpeg`, `zstd`, `lzma`, `webp`, or the number), `tiled`, `bigtiff`, `bytes` | `IOFormatError` as `tiff_tags`, and for a sample type `_tiff_kind` does not know | First page only; reads the whole file into memory but decodes no pixels |
| `read_tiff(path, page=0)` | Raster of the page | `IOFormatError` (see Failure modes); `zlib.error` for a damaged deflate strip | Single-sample pages only. Whole file read into memory |
| `write_tiff(path, raster)` | None | `KeyError` for a kind other than `u8`, `u16`, `f32` | One strip, uncompressed, little-endian |
| `npy_header(raw)` | dict: `shape` (tuple), `kind`, `little` (bool), `offset` (byte where the data starts) | `IOFormatError` for a file that is not `.npy`, an unsupported dtype, or Fortran order | Format versions 1 and 2 or later |
| `read_npy(path, index=None)` | Raster | `IOFormatError` for a layer outside the array or a shape that is not 2-D or 3-D | For 3-D, layer `index` along the first axis, default the middle one (`shape[0] // 2`). dtypes `u1`, `i1`, `u2`, `i2`, `u4`, `i4`, `f4`, `f8`, and `b1` read as `u8` |
| `ZArray(path)` | An array object with `.version` (2 or 3), `.shape`, `.chunks`, `.kind`, `.little`, `.compressor` (a numcodecs-style dict or None), `.fill` (a number: the strings `"NaN"`, `"Infinity"` and `"-Infinity"` that zarr writes become floats, null becomes 0), `.sep`, `.prefix`, `.size` (bytes per sample), and `.read(box)` | `IOFormatError` (see Failure modes) | `read(box)` takes `[(start, stop)]` per axis, clamps it to the shape, and returns `(samples, shape)`: an `array.array` (bytes for `u8`) in C order and the list of lengths. Missing chunk files read as the fill value |
| `zarr_levels(path)` | list of `(name, shape)`, finest first; `[("", shape)]` for a bare array | `IOFormatError` when nothing readable is found | Level names from the first `multiscales` entry (`.zattrs`, or `zarr.json` attributes, under `ome` when present), else the folders named by digits. Levels that fail to open are skipped |
| `open_zarr(path, level=None)` | `ZArray` of the level (default the finest) | `IOFormatError` for a level that is not there | `level` may be an int or a str |
| `is_zarr(path)` | bool | Nothing | A folder holding `.zarray`, `.zgroup` or `zarr.json` |
| `volcomp_source(path)` | str (why it is a lossy volcomp copy, with the q setting when the metadata gives one) or None | Nothing | True for any text containing `VOLCOMP_PREFIX`, or a local zarr whose root or `0/` metadata uses the `volcomp` codec (inside sharding too, or as a v2 compressor id). Other URLs return None unopened |
| `volcomp_lib()` | The `ctypes.CDLL` handle of the library `KIT_VOLCOMP_LIB` names, with `volcomp_lib_decode`'s argument and return types set | `IOFormatError` when `KIT_VOLCOMP_LIB` is unset or empty, or when the library does not load; `AttributeError` when it loads but has no `volcomp_lib_decode` symbol | Loaded once per path and cached in `_VOLCOMP_LIBS` for the life of the process; changing the variable loads the new path |
| `volcomp_decode(raw, lib=None)` | bytes: one chunk's 2,097,152 uint8 voxels (128 cubed, z-major) | `IOFormatError` when the library returns a nonzero status; `volcomp_lib`'s errors when `lib` is not given | `lib` defaults to `volcomp_lib()`; tests pass a stand-in. The output size is fixed: it assumes villa's 128 cubed uint8 chunk and does not read the array's chunk shape. Lossy data, never the scan |
| `layer_files(path)` | list of paths, numeric order | `FileNotFoundError` for a missing folder | Files named by digits with `.tif` or `.tiff` (any case): `00.tif`, `01.tif`, ... |
| `is_tifxyz(path)` | bool | Nothing | A folder with `x.tif`, `y.tif` and `z.tif` |
| `png_bytes(h, w, data, channels=1)` | bytes of a PNG | `IOFormatError` when `len(data)` is not `h * w * channels` | 8-bit gray (`channels=1`) or RGB (`3`), filter 0, zlib level 6 |
| `read_png_gray(blob)` | `(h, w, channels, bytes)` | `IOFormatError` for a blob that is not a PNG, or a PNG that is not 8-bit gray or RGB and non-interlaced | Despite the name, RGB too. All five row filters. CRCs are not checked |
| `percentile(sorted_vals, pct)` | float, or None for an empty list | Nothing | Linear interpolation; the list must be sorted |
| `sample_values(values, limit=200000)` | Every `step`-th value, `step = max(1, len(values) // limit)` | Nothing | So statistics read at most about 2 x `limit` values |
| `stats(raster, threshold=None, skip_zero=False)` | dict (fields under Outputs) | Nothing | Over `sample_values`, NaN left out of min, max, mean and percentiles |
| `prob_threshold(kind)` | `127.5` for `u8`, `32767.5` for `u16`, else `0.5` | Nothing | The sample value that means probability 0.5 in an ink map of that kind |
| `downsample(raster, factor, how="mean")` | Raster of kind `f32`, `h // factor` by `w // factor` (at least 1 x 1) | Nothing | `how`: `mean`, `max` or `nearest` (the block center). Remainder rows and columns are dropped. `factor` 1 or less returns a float copy. A factor wider or taller than the image makes one block across it, of the pixels there are (before 16 October 2026, `mean` and `max` mixed in pixels of the next rows there and `nearest` could fail) |
| `to_u8(raster, lo_pct=1.0, hi_pct=99.0, skip_zero=True, invert=False, lo=None, hi=None)` | `(bytes, (lo, hi))` | Nothing | Linear stretch from `lo` to `hi` (default the 1st and 99th percentiles of the sampled values, zeros and NaN left out) to 0 to 255. Zeros (with `skip_zero`) and NaN stay 0; a uniform image is mid gray (128); `invert` flips the gray |
| `numpy_or_none()` | the numpy module, or None | Nothing | |
| `raster_from_numpy(arr)` | Raster of kind `f32` | `AttributeError` when numpy is missing; numpy's errors for an array that is not 2-D | |

Module constants: `KINDS` (kind to `array` type code and bytes per sample), `LITTLE` (this machine is little-endian), `TIFF_TYPES` (tag types read), `TIFF_COMPRESSION` (compression numbers to names: 1 `none`, 5 `lzw`, 8 and 32946 `deflate`, 32773 `packbits`, 7 `jpeg`, 50000 `zstd`, 34925 `lzma`, 50001 `webp`), `NPY_KINDS` (numpy and zarr v2 dtype codes to kinds), `VOLCOMP_PREFIX = "community-uploads/forrest/volcomp/"`, `VOLCOMP_COST` (the text that says why volcomp copies are not ink inputs), `VOLCOMP_LIB_ENV = "KIT_VOLCOMP_LIB"`, `VOLCOMP_CHUNK_BYTES = 128 ** 3`, `FILL_NAMES` (zarr's fill value strings `NaN`, `Infinity`, `-Infinity` to floats).

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| TIFF | Classic (magic 42) or BigTIFF (43), either byte order; one sample per pixel; bits and sample format 8, 16, 32 unsigned or signed, 32 or 64 float; strips or tiles; compression 1, 5, 8, 32946 or 32773; predictor 1, 2 or 3 (3 on floats only) | VC3D layer TIFFs (`vc_render_tifxyz`), tifxyz `x.tif`, `y.tif`, `z.tif` (float32, including the catalog's BigTIFF grids with LZW and predictor 3), villa's ink maps. The whole file is read into memory |
| `.npy` | Format version 1 or later, C order, 2-D or 3-D | What `numpy.save` writes for a 2-D or 3-D array |
| zarr v2 array | A folder with `.zarray`: C order, no filters, `dimension_separator` `.` (default) or `/`, compressor none, `zlib`, `gzip`, or any numcodecs id | Local folders only |
| zarr v3 array | A folder with `zarr.json`, `node_type` `array`: data types `uint8` to `float64`, chunk key encoding `default` (`c/` and `/`) or `v2`, codecs `bytes`, `gzip`, `zstd`, `blosc`, `lz4`, and `transpose` in C order; fill value a number, null, or `"NaN"`, `"Infinity"`, `"-Infinity"` | `sharding_indexed`, `volcomp` and other codecs are refused; `transpose` is accepted only in C order (`"C"` or 0, 1, 2), any other order is refused |
| OME-Zarr group | A folder with `.zattrs` or `zarr.json` naming `multiscales` datasets, or digit-named level folders | Levels are listed finest first as the metadata gives them |
| PNG | 8-bit gray or RGB, not interlaced | Palette, 16-bit, alpha and interlaced PNGs are refused |
| volcomp chunk (`volcomp_decode`) | The encoded bytes of one chunk, as stored in a volcomp zarr v3 array | Needs `KIT_VOLCOMP_LIB`; decodes to 128 cubed uint8 |
| Raster for writing | kind `u8`, `u16` or `f32` | `write_tiff` only |

## Outputs

Return values (see Python API) and, for `write_tiff`, one TIFF file. `volcomp_decode` returns 2,097,152 bytes, the voxels of one 128 cubed chunk with z slowest. `stats` returns:

| Field | Type | Meaning |
| --- | --- | --- |
| `shape` | [int, int] | Height and width |
| `kind` | str | The Raster's kind |
| `pixels` | int | All pixels |
| `min`, `max` | number or null | Over the sampled values (NaN, and zeros with `skip_zero`, left out) |
| `mean` | float (4 decimals) or null | The same values |
| `p1`, `p50`, `p99` | float or null | 1st, 50th and 99th percentiles of the same values |
| `nonzero_fraction` | float (4 decimals) | Share of sampled values that are not 0 (NaN counts as nonzero) |
| `sampled` | bool | True when fewer values than pixels went into the numbers: subsampling (images of 400,000 pixels or more), or any NaN or skipped zero |
| `threshold` | number | Only when `threshold` is given |
| `above_threshold_fraction` | float (5 decimals) | Only with `threshold`: share of sampled values above it |

`tiff_info` returns `height`, `width` (int), `kind` (str), `samples_per_pixel` (int), `compression` (str, or the number when unnamed), `tiled`, `bigtiff` (bool) and `bytes` (file size, int). `write_tiff` writes a little-endian, single-strip, uncompressed TIFF with tags 256, 257, 258, 259, 262, 273, 277, 278, 279 and 339; `png_bytes` returns a PNG's bytes, which the caller writes.

## Failure modes

Every refusal is an `IOFormatError` (a `ValueError`) unless the row says otherwise.

| What you see | Why | What to do |
| --- | --- | --- |
| `PATH: the transpose codec (order ORDER) is not supported; rewrite the array without it, in C order` (`IOFormatError`) | The zarr v3 array lists a `transpose` codec whose order is not C (not 0, 1, 2), so its chunks are not stored in z, y, x order | Rewrite the array without the codec, in C order, then read it again |
| `not a TIFF` | The file does not start with `II` or `MM` | Check the file; it may be a PNG, a JPEG or an HTML error page |
| `TIFF magic N is neither 42 nor 43` | A damaged header | Check the file |
| `TIFF has no page N` | `page` past the last page | Use a page the file has (0 is the first), or `tifffile` |
| `PATH: truncated TIFF (unpack requires a buffer of 8 bytes)` | The file ends inside its header or tag table | Download or copy it again |
| `PATH: expected one sample per pixel, found N` | An RGB TIFF, or an array tifffile stored as samples | Save one channel per file, or read it with tifffile |
| `N-bit samples of format F are not supported` | Such as 64-bit integers (`format 1`) or complex numbers (`format 6`) | Convert to 8, 16 or 32-bit integers or 32 or 64-bit floats |
| `PATH: compression NAME not supported` | JPEG, zstd, LZMA, WebP or another codec | Read it with tifffile and imagecodecs, or rewrite it uncompressed, LZW or deflate |
| `PATH: predictor N not supported for KIND` | Predictor 3 on integer samples, or a predictor other than 1, 2, 3 | Rewrite it with predictor 1 or 2 |
| `zlib.error: Error -5 while decompressing data: incomplete or truncated stream` (not an `IOFormatError`) | A damaged or cut-off deflate strip | Download or copy the file again |
| `KeyError: 'i16'` from `write_tiff` (not an `IOFormatError`) | `write_tiff` writes only `u8`, `u16` and `f32` | Convert the Raster first (`downsample(r, 1)` gives `f32`) |
| `this Python's array type 'I' is not 4 bytes` | This Python's `array` module uses another size for that type code | Use a standard 64-bit CPython build |
| `raster HxW given N samples` | `Raster` got the wrong number of samples | Pass `h * w` samples |
| `not an .npy file` | The file does not start with numpy's magic | Check the path |
| `npy dtype '<c8' not supported` | A dtype outside `NPY_KINDS`, such as complex | Save as an integer, float or bool array |
| `Fortran-ordered .npy not supported` | Saved from a Fortran-ordered array | Save `numpy.ascontiguousarray(a)` |
| `PATH: expected 2-D or 3-D, got shape (N,)` | A 1-D or 4-D array | Save a 2-D map or a 3-D stack |
| `PATH: layer K outside N` | `index` past the stack | Use 0 to N-1 |
| `PATH: no .zarray or zarr.json` | The folder is not a zarr array (perhaps a group) | Use `open_zarr`, which finds the levels of a group |
| `PATH: not a zarr array or OME-Zarr group` | No array and no readable level in the folder | Check the path |
| `PATH: no level '3'; levels ['0', '1']` | `open_zarr` asked for a level the group does not have | Use a listed level |
| `PATH: zarr.json is not an array` | A v3 group opened as an array | Use `open_zarr` |
| `PATH: dtype <c8 not supported` (v2) or `PATH: data type complex64 not supported` (v3) | An unsupported data type | Use zarr or numpy |
| `PATH: only C order without filters is supported` | A v2 array with Fortran order or filters | Read it with the zarr package |
| `PATH: sharded zarr v3 is not supported without the zarr package` | A sharded v3 array | Read it with the zarr package |
| `PATH: codec crc32c not supported` | A v3 codec outside `bytes`, `gzip`, `zstd`, `blosc`, `lz4`, `transpose` | Read it with the zarr package |
| `compressor 'zstd' needs numcodecs (pip install numcodecs), or render with --zarr-compressor none\|gzip, or use --tif-output` | A blosc, zstd or lz4 chunk and no numcodecs | `pip install numcodecs`, or have the render write gzip or TIFF |
| `PATH/0.0: chunk holds 3 bytes, expected 4` | A chunk file of the wrong size after decoding (damaged, or a different dtype) | Fetch the chunk again; [vc3d-audit](vc3d-audit.md) checks a store |
| `empty box [(3, 3), (0, 2)] for shape [4, 4]` | A box with no samples after clamping | Give each axis `start < stop` inside the shape |
| `struct.error: required argument is not a float` (not an `IOFormatError`) | Before 16 October 2026 (and in the released copies): a float zarr whose `fill_value` is `"NaN"` (as zarr writes NaN) and a box that touches a missing chunk. Fixed here; a fill value string other than `NaN`, `Infinity` or `-Infinity` still fails this way | Use this checkout's module, or read it with the zarr package |
| `PATH: codec volcomp not supported` | `ZArray` opened a volcomp-compressed v3 array; only [vc3d-audit](vc3d-audit.md)'s codec chain decodes volcomp | Read it through vc3d-audit with `KIT_VOLCOMP_LIB` set, or use the original scan, which is not lossy |
| `codec volcomp not decoded here: set KIT_VOLCOMP_LIB to a libvolcomp.so built from villa's volume-cartographer/libs/volcomp (cc -O2 -std=c11 -fPIC -shared -o libvolcomp.so volcomp_lib.c -lm)` | `volcomp_decode` without `lib` and with `KIT_VOLCOMP_LIB` unset or empty | Build the library from villa's `volume-cartographer/libs/volcomp` with that command and set `KIT_VOLCOMP_LIB` to its absolute path |
| `KIT_VOLCOMP_LIB=PATH does not load: PATH: cannot open shared object file: No such file or directory` | The path is wrong, or the library was built for another platform or architecture (the text after `does not load:` is the loader's) | Fix the path, or rebuild the library on this machine |
| `AttributeError: PATH: undefined symbol: volcomp_lib_decode` (not an `IOFormatError`) | `KIT_VOLCOMP_LIB` names a library that loads but is not libvolcomp (seen 2026-10-17 with `libm.so.6`) | Point it at the library built from `volcomp_lib.c` |
| `volcomp chunk of N bytes does not decode (status S)` | The library rejected the chunk: damaged or cut-off bytes, or not a volcomp chunk | Fetch the chunk again. In [vc3d-audit](vc3d-audit.md) this error makes the chunk's `ok` None (not checked), the same as a missing library, not False |
| `PNG WxHxC given N bytes` | `png_bytes` got the wrong number of bytes | Pass `h * w * channels` bytes |
| `not a PNG` | The blob does not start with the PNG signature | Check the file |
| `only 8-bit grey or RGB, non-interlaced` | A 16-bit, palette, alpha or interlaced PNG | Save it as 8-bit gray or RGB |
| `FileNotFoundError` (not an `IOFormatError`) | A path that does not exist | Fix the path |

## How it works

1. **TIFF.** `tiff_tags` reads the byte order (`II` or `MM`) and the magic (42 classic, 43 BigTIFF), walks the page chain to `page`, and unpacks each tag of the integer types in `TIFF_TYPES`, inline or from its offset. `read_tiff` takes width (256), height (257), bits (258), compression (259), predictor (317), samples per pixel (277), sample format (339) and either strips (273, 278, 279) or tiles (322 to 325). Each strip or tile is decoded (`bytes`, `lzw_decode`, `zlib.decompress`, `packbits_decode`), padded with zeros if short, un-predicted, and copied into place; edge tiles are cropped. The samples become an `array.array` in this machine's byte order.
2. **Predictors.** Predictor 2 adds each sample to the one on its left, modulo the sample's bits, on the raw bits of float samples too (as libtiff and tifffile do). Predictor 3 (libtiff's floating-point predictor, `fpAcc`) undoes byte-wise differencing along each row, then gathers the byte planes, most significant first, back into samples in the file's byte order (`_undo_float_predictor`).
3. **`.npy`.** `npy_header` parses the version 1 (2-byte length) or later (4-byte length) header with `ast.literal_eval`; `read_npy` slices the bytes of the 2-D array, or of one layer of a 3-D one.
4. **zarr.** `ZArray` reads `.zarray` (v2) or `zarr.json` (v3) and works out the chunk key form (`.` or `/`, with `c/` before v3 default keys), byte order and compressor. `read` lists the chunks the box touches, decodes each (zlib and gzip with the standard library, others through `numcodecs.get_codec`), checks its decoded size, and copies rows along the last axis into the output. A chunk file that is absent reads as the fill value (`fill_value`, or 0 when it is null).
5. **Levels and volcomp.** `zarr_levels` lists a group's levels from the first `multiscales` entry, or from its digit-named folders, and skips levels it cannot open. `volcomp_source` checks the text for `VOLCOMP_PREFIX`, then, locally, the codec lists of `zarr.json`, `0/zarr.json`, `.zarray` and `0/.zarray` (the first array it finds decides) for a codec named `volcomp`.
6. **PNG.** `png_bytes` writes IHDR, one zlib-compressed IDAT with filter 0 on every row (level 6), and IEND. `read_png_gray` checks the signature, then joins the IDAT chunks and undoes the five row filters.
7. **Statistics and previews.** `sample_values` keeps every `step`-th value, `step = max(1, n // limit)` with `limit` 200,000, so an image under 400,000 pixels is used whole and a larger one gives 200,000 to 400,000 values to `stats`, `to_u8`'s percentiles and the threshold share. `to_u8` maps `lo` to 0 and `hi` to 255 linearly. `downsample` averages, takes the maximum of, or picks the center of `factor` x `factor` blocks.

## Cost and time

Measured 2026-10-16 in a 4-core Intel Xeon 2.80 GHz cloud container, Python 3.13, on synthetic 2,000 x 2,000 images written by tifffile:

| File | On disk | `read_tiff` |
| --- | --- | --- |
| u8, uncompressed | 4.00 MB | 0.03 s |
| f32, uncompressed | 16.00 MB | 0.20 s |
| u16, deflate, predictor 2 | Not recorded | 2.46 s |
| u8, deflate, predictor 2, 256 px tiles | 2.86 MB | 3.02 s |
| u8, LZW, no predictor, 256 px tiles | Not recorded | 8.45 s |
| u8, LZW, predictor 2, 256 px tiles | 3.61 MB | 8.05 s |
| f32, LZW, predictor 3 | 11.28 MB | 30.60 s |

LZW decoded at about 0.5 MB/s here, below the "few MB/s" the module's docstring gives. zlib itself is C, so most of the 3.02 s of the deflate file is the pure-Python predictor (Interpretation). On the same 4-megapixel u8 Raster: `stats` 0.13 s, `downsample` by 8 (mean) 0.58 s, `to_u8` 4.46 s, `png_bytes` 0.57 s. zarr boxes decode in C: 8 MB (four 128-cubed u8 chunks) in 0.25 s uncompressed, 0.31 s blosc and 0.38 s gzip; one 256 x 256 slice through them 0.01 to 0.04 s. Memory: a TIFF or `.npy` is read whole, so about the file's size plus the decoded image. `volcomp_decode` runs in the C library; its speed was not measured. It needs no GPU; a pure-Python decode of large LZW files is the slow case, and tifffile is the faster tool there.

## For agents

- **Command:** In Python: `from kit import vc3d_io`; `r = vc3d_io.read_tiff("MAP.tif")` (or `read_npy`), `vc3d_io.stats(r, threshold=vc3d_io.prob_threshold(r.kind))`; for a zarr, `z = vc3d_io.open_zarr("VOL.zarr", LEVEL)` and `samples, shape = z.read([(Z0, Z1), (Y0, Y1), (X0, X1)])`; `vc3d_io.volcomp_source(VOLUME)` before an ink render; `KIT_VOLCOMP_LIB=/abs/libvolcomp.so` then `vc3d_io.volcomp_decode(CHUNK_BYTES)` for one volcomp chunk. There is no command line.
- **Parse:** A `Raster` (`h`, `w`, `kind`, `data`); `stats` returns a dict (`shape`, `kind`, `min`, `max`, `mean`, percentiles, `above_threshold_fraction`, `sampled`).
- **Rerun:** Safe; only `write_tiff` writes, to the path it is given.
- **Success:** A Raster or array of the expected shape and kind.
- **Not a pass:** Zeros or fill values in a read: they may be missing chunks or a short strip, which this module does not report; check with [vc3d-audit](vc3d-audit.md). Voxels from `volcomp_decode` taken as the scan (they are the lossy copy). Statistics with `sampled` true taken as exact.
- **Go-ahead:** Nothing.
- **Never:** Use a volcomp copy as an ink input; call an ink map read with it a reading, or say letters were found.

## Tests

```bash
python -m unittest tests.test_vc3d_io tests.test_vc3d_volcomp -v
```

`tests/test_vc3d_io.py` (25 tests) covers TIFF round trips for `u8`, `u16` and `f32`; a real VC3D layer (tiled, LZW, predictor 2, villa `e0bbb8b`); deflate; refusals (JPEG, a GIF, a cut-off file); predictors 1, 2 and 3 on float32 in both byte orders, and predictor 3 refused on integers; predictor 3 against libtiff through Pillow; tiles, strips, big-endian, BigTIFF and PackBits against tifffile; LZW against Pillow; `as_floats`; `.npy` 2-D, 3-D layers, big-endian and refusals; zarr v2 with three compressors and both separators, partial edge chunks and boxes across chunks; missing chunks as fill; v3 OME groups and levels; sharded and unknown codecs refused; blosc with and without numcodecs; PNG round trips and all row filters; `downsample`, `to_u8`, `stats` and `prob_threshold`; `layer_files` and `is_tifxyz`; `volcomp_source` by prefix and by codec; a `transpose` codec refused unless it keeps the order; NaN and infinite fill values; `downsample` with a factor wider than the image. The tests that compare with tifffile or Pillow skip without them. `tests/test_vc3d_volcomp.py` (5 tests) checks with a stand-in library that `volcomp_lib` names `KIT_VOLCOMP_LIB` when it is unset, that vc3d-audit's v3 chain and `decode` pass volcomp chunks through `volcomp_decode`, and that a nonzero status raises; its round trip through a real library is skipped without `KIT_VOLCOMP_LIB`. Not covered: a cut-off strip, a library without the `volcomp_lib_decode` symbol, and (without `KIT_VOLCOMP_LIB`) the real volcomp decoder.

## History

- 2026-10-24: on public `main`, for the false-404 tools; adds, since the release copies, the `transpose` refusal, NaN and infinite fill values, `downsample` with a factor wider than the image (16 October) and opt-in volcomp decoding through `KIT_VOLCOMP_LIB` (17 October) (`77aea1f`).
- 2026-10-15: the copy in AutoPipeline 0.1.4 (`603fe14`, branch `submission/progress-2026-10-fix4`); the first version was of 8 October.

## Related

- [vc3d-audit](vc3d-audit.md): checks a store's chunks, local or remote, with this module's decoders.
- [vc3d-cache](vc3d-cache.md): VC3D's empty-chunk markers.
- [tifxyz](tifxyz.md): segment geometry with numpy and tifffile.
- [auc](auc.md): scoring an ink map with its reverse-depth control.
