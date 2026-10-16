# layers: export a surface volume to layer TIFFs, and write the depth-shuffle control

`python -m kit layers` writes a surface-volume zarr as numbered layer TIFFs (`00.tif`, `01.tif`, ...), the input v8in reads; `--shuffle SEED`, and `python -m kit shuffle` for a zarr copy, write the depth-shuffle control: the same layers in a fixed random order.

| Field | Value |
| --- | --- |
| Id | `layers` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Data and downloads |
| Run | `python -m kit layers`, `python -m kit shuffle`, `from kit import layers` |
| Code | `kit/layers.py`, `kit/cli.py` (`cmd_layers`, `cmd_shuffle`), `kit/verify.py` (`_numpy`, `VerifyError`) |
| Tests | `tests/test_layers.py` |
| Needs | Python 3.11 or newer with numpy, tifffile and zarr 3 (checked with numpy 2.5.3, tifffile 2026.10.15, zarr 3.4.1). `kit shuffle` writes with zarr 3's `create_array`, which zarr 2.18 lacks (`pyproject.toml`); `kit layers` only reads zarr. No imagecodecs needed: the TIFFs are zlib-compressed |
| Runs on | Any CPU. A 28 x 2,048 x 2,048 synthetic volume (117 MB) took 9.7 s to export and 7.2 s to shuffle (measured 2026-10-16, 4-core Xeon cloud container); the whole PHerc0139 w045 volume (28 x 5,980 x 8,240) exported in 23 s (commit `6081aab`, machine not recorded) |
| Network | None |
| Writes | `kit layers`: the folder `OUT_DIR` (created when missing) and one TIFF per layer in it, replacing files of the same names and leaving any other files there. `kit shuffle`: a zarr group at `OUT`; anything already at `OUT` is deleted first |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07 (`1caa69e`; the shuffle control since `bd18778`); also in the AutoPipeline release copy at `faada83` |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

A surface volume is a stack of images rendered at fixed depths above and below a traced papyrus surface; ink models read it. villa's `vc_render_tifxyz --zarr-output` and the organizers' published surface volumes store it as a zarr array of shape (layers, height, width), uint8, either bare or inside an OME-Zarr group whose full-resolution level is `0`. v8in (Youssef Nader's community ink model, `YoussefMoNader/ink-8um-v8in`) reads a folder of numbered layer images instead, and uses the central 24 when there are more. `kit layers` bridges the two: it writes layers `START` to `START+COUNT-1`, optionally cut to a window, as `00.tif`, `01.tif`, ... in depth order as stored.

It keeps the stored order on purpose. The reverse-depth control (the same model run with the layers in the opposite order, the control every ink AUC here needs) is made at inference time with v8in's `--reverse`, so one export serves both directions.

The depth-shuffle control is the one exception. After [aviad12g's vesuvius-depth-order-control](https://github.com/aviad12g/vesuvius-depth-order-control), it puts the layers in a fixed random order that is never the stored and never the reversed one. A model that reads ink by its depth order loses that signal on shuffled input, while brightness and texture survive. `kit layers --shuffle SEED` writes the shuffled TIFF folder for v8in; `kit shuffle` writes a shuffled zarr for villa's ink inference. With the same seed and the same number of layers, the two give the same order, and the order is printed and stored.

It does not run a model, score anything, or change pixel values. Its outputs are model inputs, not results; a map made from them is model output, not a reading.

## When to use it

- Preparing v8in's input from a surface volume: `kit layers VOLUME.zarr OUT_DIR`, with `--crop` for the 640 px scoring windows the scripts here use.
- Making the depth-shuffle control beside the reverse one: `kit shuffle` for villa's `ink_9um` inference, `kit layers --shuffle` for v8in.
- Exporting a different depth window, such as 24 layers from `--start S` (`scripts/experiments/2026-10-07-cloud/v8inwin-ag405/run.sh` does this).

Do not use it:

- To reverse depth: do that at inference (v8in `--reverse`, villa `--direction both`), not at export.
- To get the surface volume: download it first with [`fetch`](fetch.md).
- For a volume that is not uint8 with `kit layers`: it refuses, because v8in expects uint8 layers. `kit shuffle` accepts any dtype.
- To score the shuffled run: score its map with [`auc`](auc.md) against the labels, beside the forward and reverse maps.

## Quick start

```bash
python -m kit fetch PHerc0139/segments/20260317000000-w035_2026031718/surface-volumes/9.362um-1.2m-113keV-volume-20250728140407.zarr/3 w035_l3.zarr
python -m kit layers w035_l3.zarr OUT/layers
python -m kit layers w035_l3.zarr OUT/layers_shuf --shuffle 20261007
python -m kit shuffle w035_l3.zarr OUT/shuf.zarr
```

- The first line fetches level `3` alone (33 objects, 14.7 MB) of the published PHerc0139 w035 surface volume, a bare 28 x 728 x 655 uint8 array, so the run is small. For real work, fetch the whole volume (`python -m kit fetch w035 w035_9um.zarr`, 1.0 GB) and export it the same way; level `0` of the group is used by default.
- `OUT`: any folder of yours.
- `20261007`: the seed the scripts here use; it is also `kit shuffle`'s default.

Run on 2026-10-16 on that real level, it printed:

```
28 layers of [28, 728, 655] from layer 0 -> /tmp/claude-docs-public-layers/w035_l3_layers
28 layers of [28, 728, 655] from layer 0 -> /tmp/claude-docs-public-layers/w035_l3_shuf_layers, depth order shuffled (seed 20261007): [0, 25, 2, 9, 3, 15, 16, 19, 26, 6, 7, 8, 21, 13, 24, 10, 11, 20, 17, 22, 4, 5, 18, 1, 27, 14, 12, 23]
28 layers shuffled (seed 20261007, order [0, 25, 2, 9, 3, 15, 16, 19, 26, 6, 7, 8, 21, 13, 24, 10, 11, 20, 17, 22, 4, 5, 18, 1, 27, 14, 12, 23]) -> /tmp/claude-docs-public-layers/w035_l3_shuf.zarr
```

It worked when the exit code is 0 and the folder holds `00.tif` to `27.tif`, each a 728 x 655 uint8 image. On that run the shuffled zarr's layer `i` equalled source layer `ORDER[i]` for all 28, and equalled the shuffled TIFF `i`.

## Checks and controls

- **The depth-shuffle control.** A reader that uses depth order should drop on shuffled input, toward 0.5. Real numbers (Model output, from [`results.json`](../results.json) `results`): `ink_9um` seed 42 on the whole of PHerc0841 w00 scores 0.7479 as stored, 0.5012 reversed and 0.4851 shuffled; Reader v2 on the w00 crop 0.9269, 0.7294 and 0.5681. The shuffled score is not always 0.5 and not always below the reversed one: Reader v2 on the ag896 crop scores 0.617 shuffled against 0.5988 reversed, and on ag405 `ink_9um` keeps 0.563 shuffled ([novel checks log](../logs/2026-10-07-novel-checks.md), section 3, which reads 0.06 to 0.11 above 0.5 on ag405 as a brightness share). Report forward, reverse and shuffled together ([STANDARDS.md](../STANDARDS.md), depth controls); the novel checks log reads a reader's AUC above its shuffled AUC as the part that depends on depth order (Interpretation).
- **The order is never the stored or the reversed one.** `depth_permutation` redraws until the order is neither the identity nor the reverse; `tests/test_layers.py` checks 50 seeds on 3 layers. A random order can still leave a few layers in place: seed 20261007 on 28 layers leaves layers 0, 2 and 13 where they were (numpy 2.5.3).
- **Export checks.** The tests compare the banded read with one-layer-at-a-time reads byte for byte, read the files back in v8in's numeric order, and check that the shuffled TIFFs and the shuffled zarr hold the same layers.
- **Same seed, different layer count, different order.** With `--start` or `--count`, `kit layers --shuffle` permutes only that range (a permutation of `COUNT`), so its order differs from `kit shuffle`'s order over all layers. Compare the printed orders before treating two shuffled runs as the same control.

Claim label: None for the export and the shuffle themselves, which only copy and reorder data. The AUCs quoted above are Model output against the organizers' published labels, from `results.json` and the novel checks log.

## Commands and options

### `python -m kit layers`

```
usage: python -m kit layers [-h] [--start START] [--count COUNT]
                            [--level LEVEL] [--crop Y0 Y1 X0 X1]
                            [--shuffle SEED]
                            volume out_dir
```

| Option | Default | Meaning |
| --- | --- | --- |
| `volume` | required | The surface-volume zarr: a bare (layers, height, width) array, or a group whose key `--level` is one. uint8 only |
| `out_dir` | required | Folder for the TIFFs; created with its parents when missing. Files of the same names are replaced; other files stay |
| `--start START` | `0` | First layer to export; file `00.tif` holds it |
| `--count COUNT` | none (all layers from `--start`) | Number of layers. `START + COUNT` must not pass the last layer |
| `--level LEVEL` | `0` | The group key to read when the store is a group (`0` is full resolution in OME-Zarr); ignored for a bare array |
| `--crop Y0 Y1 X0 X1` | none (the whole layer) | Export only rows Y0 to Y1 and columns X0 to X1 of the chosen level, ends excluded, in that level's pixels |
| `--shuffle SEED` | none | Write the layers in the fixed random order `depth_permutation(COUNT, SEED)`: file `i` holds layer `START + ORDER[i]`. The order is printed |

### `python -m kit shuffle`

```
usage: python -m kit shuffle [-h] [--seed SEED] [--level LEVEL]
                             [--crop Y0 Y1 X0 X1]
                             volume out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `volume` | required | The surface-volume zarr, bare or a group, any dtype |
| `out` | required | The zarr to write: a group with one array `0`. Anything already at this path is deleted first |
| `--seed SEED` | `20261007` | Seed of the order, `depth_permutation(LAYERS, SEED)` over all layers |
| `--level LEVEL` | `0` | The group key to read when the store is a group |
| `--crop Y0 Y1 X0 X1` | none (the whole layer) | Copy only this window, ends excluded; the output's shape is the window's |

## Python API

```python
from kit import layers
info = layers.export_file("w045_9um.zarr", "layers", crop=(3840, 4480, 2560, 3200))
info_shuffled = layers.export_file("w045_9um.zarr", "layers_shuf", crop=(3840, 4480, 2560, 3200), shuffle_seed=20261007)
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `open_volume(path, level='0')` | The zarr array of shape (layers, height, width), opened read-only (lazy) | `VerifyError` when zarr is missing, the store cannot be opened, a group has no key `level`, or the array is not 3D | A bare array is returned as it is; `level` is used only for a group |
| `depth_permutation(n, seed)` | A list of `n` ints, a permutation of `0 .. n-1` that is neither the identity nor the reverse | `VerifyError` for `n` below 3, or without numpy | numpy `default_rng(seed).permutation(n)`, redrawn until it is neither; the same `n`, seed and numpy version give the same list |
| `export_layers(volume, out_dir, start=0, count=None, compression='zlib', crop=None, max_bytes=DEFAULT_MAX_BYTES, order=None)` | The list of `Path`s written, in file order | `VerifyError` for a range outside the volume, a crop outside the layer, a dtype other than uint8, or an `order` that is not a permutation of `0 .. count-1` | `volume` is any array with `shape`, `dtype` and slicing (zarr or numpy). `crop` is `(y0, y1, x0, x1)`. `compression` goes to `tifffile.imwrite`. Reads every requested layer in row bands into memory when `count * h * w <= max_bytes`, else one layer at a time |
| `export_file(src, out_dir, start=0, count=None, level='0', crop=None, max_bytes=DEFAULT_MAX_BYTES, shuffle_seed=None)` | `{"source", "shape", "start", "crop", "layers", "out_dir", "order"}`: the path, the full volume shape, the first layer, the crop as given, the files written, the folder, and the order (`None` unless shuffled) | As `open_volume`, `depth_permutation` and `export_layers` | What `kit layers` runs |
| `shuffle_file(src, dst, seed, level='0', crop=None)` | `{"source", "out", "shape", "seed", "order"}`, with `shape` the written array's | `VerifyError` as `open_volume`, for a crop outside the layer, or fewer than 3 layers | What `kit shuffle` runs. Reads the whole (cropped) volume into memory, with no fallback |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Surface volume | zarr (format 2 or 3), a bare 3D array or a group (OME-Zarr) with the array at key `--level` | Axes (layers, height, width): axis 0 is depth as stored, from villa's renderer or the organizers' published volumes. The published 9 um volumes used here have 28 layers in 28 x 128 x 128 chunks: w035 is 28 x 5,820 x 5,240 and w045 28 x 5,980 x 8,240 (about 1.4 GB) at level `0` (read from their `.zarray` on 2026-10-16). `kit layers` needs uint8; `kit shuffle` keeps any dtype |
| Crop | Four ints, `Y0 Y1 X0 X1` | Pixels of the chosen level, rows then columns, ends excluded; `0 <= Y0 < Y1 <= H` and `0 <= X0 < X1 <= W`. The 640 px scoring windows per segment are in `scripts/mac-w045.sh` (w045: `3840 4480 2560 3200`) |
| Seed | int | Any int; 20261007 throughout this repository |

## Outputs

`kit layers` prints one line:

```
N layers of [L, H, W] from layer START[, rows Y0-Y1, columns X0-X1] -> OUT_DIR[, depth order shuffled (seed SEED): [ORDER]]
```

`[L, H, W]` is the shape of the whole volume, not of the export. It writes `OUT_DIR/00.tif` to `OUT_DIR/NN.tif`, `N` files named with at least two digits (three from 101 layers on). Each is a 2D uint8 TIFF of the window's size, zlib (Deflate) compressed, not tiled. File `i` holds layer `START + i`, or `START + ORDER[i]` with `--shuffle`.

`kit shuffle` prints one line:

```
L layers shuffled (seed SEED, order [ORDER]) -> OUT
```

It writes a zarr group at `OUT` in the installed zarr's default format (format 3 with zarr 3; zstd-compressed chunks on 2026-10-16) holding:

| Field | Type | Meaning |
| --- | --- | --- |
| array `0` | array (L, h, w), the source dtype | Layer `i` is source layer `ORDER[i]`, cut to the crop; chunks (L, min(128, h), min(128, w)) |
| attribute `depth_shuffle.source` | str | The source path as given |
| attribute `depth_shuffle.seed` | int | The seed |
| attribute `depth_shuffle.order` | list of int | The order: output layer `i` is source layer `order[i]` |
| attribute `depth_shuffle.crop` | list of 4 int, or null | The crop as given |

| Exit code | Meaning |
| --- | --- |
| `0` | Written |
| `1` | An error the command does not catch, with a Python traceback: tifffile missing, or a file or folder that cannot be written (`OSError`) |
| `2` | Bad input, with the message on stderr (see Failure modes), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `cannot open PATH as zarr: PATH does not exist` (or another reason after the colon), exit code 2 | A wrong path, or not a zarr store | Point at the `.zarr` folder; fetch it first with [`fetch`](fetch.md) |
| `PATH: zarr group has no level '5'; levels: ['0', '1']`, exit code 2 | The group has no key `--level` | Pick one of the listed levels; `0` is full resolution |
| `PATH: expected (layers, height, width), got shape (600, 800)`, exit code 2 | The array is not 3D, such as a single 2D map | Pass the surface volume, not a map |
| `layers 4..6 are outside the volume's 6 layers`, exit code 2 | `--start` and `--count` reach past the last layer, or `--count` is below 1 (`layers 0..-1 ...`) | Use `START + COUNT <= LAYERS` and `COUNT >= 1` |
| `crop [0, 700, 0, 10] is outside the 600 x 800 layer`, exit code 2 | A window with an end past the layer, an end before its start, or a negative start | Fix the crop for this level's size |
| `the volume is uint16; v8in expects uint8 layers`, exit code 2 | `kit layers` on a volume that is not uint8 | Convert to uint8 first, or use `kit shuffle`, which keeps the dtype |
| `a depth shuffle needs at least 3 layers, got 2`, exit code 2 | `--shuffle` or `kit shuffle` with fewer than 3 layers, where only the stored and reversed orders exist | Export more layers |
| `order must be a permutation of 0..N` | `export_layers` called from Python with a bad `order` (the command never passes one) | Pass a permutation of `range(count)` |
| `zarr is required (it is in villa's environment)`, exit code 2 | zarr is not installed (numpy missing also lands here, since zarr needs it) | `python -m pip install numpy tifffile zarr` on Python 3.11 or newer, or run inside villa's environment |
| `numpy is required. Run inside villa's environment: uv run --project "$VILLA/vesuvius" --extra models python -m kit verify ...` | numpy is missing and `depth_permutation` or `export_layers` is called from Python | Install numpy |
| `ModuleNotFoundError: No module named 'tifffile'` and a traceback, exit code 1 | `kit layers` without tifffile | Install tifffile |
| `PermissionError` or `OSError` and a traceback, exit code 1 | `OUT_DIR` or `OUT` cannot be created or written, or the disk is full | Pick a writable folder with room for the export |
| `AttributeError: ... 'create_array'` and a traceback, exit code 1 | `kit shuffle` with zarr 2.x (expected from the `pyproject.toml` note; not run here) | Use zarr 3 on Python 3.11 or newer |
| Exit code 0 but v8in reads more layers than you exported | `OUT_DIR` still held higher-numbered TIFFs from an earlier, larger export; `kit layers` does not delete them | Delete the folder first (`rm -rf OUT_DIR`), as the scripts here do |
| Exit code 0 and other files at `OUT` are gone | `kit shuffle` opens `OUT` in zarr's mode `w`, which deletes what is there | Always give `kit shuffle` a new path |

## How it works

`kit layers` (`export_file`, `export_layers`):

1. Open the store read-only (`open_volume`); for a group take key `--level`; require 3 dimensions.
2. Check the layer range, the crop and the dtype (uint8).
3. If the export fits in `DEFAULT_MAX_BYTES` (4 GiB, `count * h * w` bytes), read every requested layer of the window into one uint8 stack in bands of `BAND_ROWS` (1,024) rows. Chunks of these stores hold every depth (w035 and w045: 28 x 128 x 128, stored uncompressed, 458,752 bytes each), so reading one layer reads all depths of each touched chunk; reading bands across all layers reads each chunk once. Commit `6081aab` measured the whole w045 export at 23 s this way against about 72 s of per-layer reads. A larger export falls back to one layer at a time.
4. With `--shuffle`, compute the order with `depth_permutation(COUNT, SEED)` (before the range check).
5. Write file `i` from layer `ORDER[i]` (or `i`) with `tifffile.imwrite(..., compression="zlib")`, names zero-padded to `max(2, digits of COUNT-1)`.

`kit shuffle` (`shuffle_file`): open the volume, compute `depth_permutation(LAYERS, SEED)` over all layers, read the window of every layer in 1,024-row bands into memory already in the new order, then open `OUT` with `zarr.open_group(mode="w")`, write array `0` with chunks of all layers by 128 x 128, and store `depth_shuffle` in the group's attributes.

`depth_permutation(n, seed)`: `numpy.random.default_rng(seed).permutation(n)`, drawn again while it equals the identity or the reverse. numpy does not promise the same stream for a seed across versions, which is why both commands print the order and `kit shuffle` stores it.

v8in lists layer files by their numeric stem (`int(stem)`, which the tests mirror) and uses the central 24 when a folder holds more ([v8in-run](v8in-run.md) runs it here).

## Cost and time

| Run (2026-10-16, 4-core Intel Xeon cloud container, lscpu 2.80 GHz, 15 GB RAM) | Wall time | Peak memory |
| --- | --- | --- |
| `kit layers`, synthetic random 28 x 2,048 x 2,048 uint8 (117 MB, chunks 28 x 128 x 128) | 9.7 s | 235 MB |
| `kit shuffle`, the same volume | 7.2 s | 278 MB |
| `kit layers`, real w035 level 3 (28 x 728 x 655) | 2.7 s | Not measured |

Random data does not compress, so real volumes may write faster. For the whole w045 volume, commit `6081aab` records a 23 s export (machine not recorded). Memory is about the export's size while it fits in 4 GiB (w045: about 1.4 GB), else one layer; `kit shuffle` always holds the whole window, with no fallback. It needs no GPU and no Modal. On Chase's Mac, wrap a run with `python -m kit run local SLUG -- python -m kit layers ...` (the local compute rule in [`AGENTS.md`](../../AGENTS.md)).

## For agents

- **Command:** `python -m kit layers VOLUME.zarr OUT_DIR --crop Y0 Y1 X0 X1` for v8in's input; add `--shuffle 20261007` for its shuffled control; `python -m kit shuffle VOLUME.zarr NEW.zarr --crop Y0 Y1 X0 X1` (seed 20261007 by default) for villa's inference. There is no JSON form; read the printed line, and for `kit shuffle` the group attribute `depth_shuffle`.
- **Parse:** `kit layers`: `N layers of [L, H, W] from layer START ...`, where N is the files written and the list after `depth order shuffled (seed SEED):` is the order. `kit shuffle`: `L layers shuffled (seed SEED, order [ORDER]) -> OUT`; output layer `i` is source layer `ORDER[i]`.
- **Rerun:** `kit layers` overwrites files of the same names and keeps any others, so empty `OUT_DIR` first (`rm -rf OUT_DIR`). `kit shuffle` replaces everything at `OUT`. Both give the same order for the same seed and layer count.
- **Success:** Exit code 0, N equal to the layers wanted, and files `00.tif` to the last one present (or array `0` in the zarr).
- **Not a pass:** A forward score reported without the reverse control, with the shuffled one as a substitute; a shuffled score assumed to be 0.5 (it was 0.56 to 0.62 on some PHerc0841 crops); two shuffled runs with different layer counts treated as the same control; a TIFF folder holding leftovers from a larger export.
- **Go-ahead:** Nothing.
- **Never:** Point `kit shuffle`'s `OUT` at the source volume or any folder that holds other files (it is emptied); reverse layers at export (use the model's reverse option); commit layer TIFFs or zarrs to git (the no-data-in-git rule, hard rule 6); call a map made from these layers a reading.

## Tests

```bash
python -m unittest tests.test_layers -v
```

Twelve tests, on small synthetic zarrs: a bare array exported in stored order, a group read at level `0`, a range renumbered from `00.tif`, a crop and a crop refused, banded and one-layer reads agreeing byte for byte across more than one band, uint16 refused, a range and a missing level refused, files read back in v8in's numeric order, the command line's printed line, a permutation that is fixed for a seed and never the identity or reverse (and refused for 2 layers), and shuffled TIFFs equal to a cropped `kit shuffle` zarr. They skip without numpy, tifffile and zarr, and need zarr 3. They do not cover real data, OME metadata, the deletion at `OUT`, files left in `OUT_DIR`, or zarr 2.

## History

- 2026-10-07: the module text explains the banded read; no change in behaviour (`fda744f`).
- 2026-10-07: the depth-shuffle control: `kit shuffle` and `kit layers --shuffle`; on the PHerc0841 w00 crop, `ink_9um`, its checkpoint soup and d9v2 fell to 0.48 to 0.50 AUC shuffled against 0.50 to 0.59 reversed (`bd18778`).
- 2026-10-07: the printed line shows the crop (`b121223`).
- 2026-10-07: banded reads across all layers when they fit in 4 GiB; the whole w045 export takes 23 s instead of about 72 s of reads (`6081aab`).
- 2026-10-07: first version: zarr (bare or OME) to numbered TIFFs for v8in, with `--start`, `--count`, `--level` and `--crop` (`1caa69e`).

## Related

- [`fetch`](fetch.md): downloads the surface volumes this exports.
- [`auc`](auc.md): scores the forward, reversed and shuffled maps against the labels.
- [`v8in-run`](v8in-run.md): runs v8in on the TIFF folders this writes, with `--reverse` for the reverse control.
- [`mac-w045`](mac-w045.md): calls `kit layers` for the whole segment and for the 640 px crop.
- [`experiment-records`](experiment-records.md): the saved cloud jobs that ran `kit layers --shuffle 20261007`.
- [Novel checks log](../logs/2026-10-07-novel-checks.md), section 3: the shuffle control against the reverse one on PHerc0841.
- [STANDARDS.md](../STANDARDS.md): the depth controls every ink score here reports.
- [`results.json`](../results.json) `results`: the `auc_shuffled` scores.
