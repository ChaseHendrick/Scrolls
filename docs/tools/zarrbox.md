# zarrbox: copy one box of a zarr volume, with a sha256 list

`python -m kit zarrbox` copies one box of a zarr or OME-Zarr scan volume, chunk files byte for byte, into a local folder that opens as the same volume, writes a sha256 per chunk, and later checks the copy against that list and against the source.

| Field | Value |
| --- | --- |
| Id | `zarrbox` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Data and downloads |
| Run | `python -m kit zarrbox`, `python -m kit.zarrbox`, `from kit import zarrbox` |
| Code | `kit/zarrbox.py`, `kit/cli.py` (`build_parser`); it reuses the chunk reader, key layouts and copy of [tifxyz](tifxyz.md) (`ZarrSource`, `zarr_level`, `chunk_key`, `fetch_chunks`) |
| Tests | `tests/test_zarrbox.py` |
| Needs | Python 3.10 or newer, standard library only. Reading the copy back needs a zarr reader (zarr-python 3.4.2 used on 2026-10-30), VC3D or villa's `vesuvius` package |
| Runs on | Any CPU with network. An 8-chunk box (16.8 MB) of PHerc0139's 2.399 um volume: `plan` under 2 s, `copy` 6.0 s, `verify --source` 2.2 s (measured 2026-10-30, 4-core Claude cloud container) |
| Network | For a volume given as `https://` or `s3://` (the open-data bucket `vesuvius-challenge-open-data`): its metadata files, one HEAD per chunk of the box (`plan`, `copy`), one GET per present chunk (`copy`, `verify --source`); 429, 5xx and dropped connections are asked again up to 5 times. None for a local volume or for `verify` without `--source` |
| Writes | `plan` and `verify`: nothing. `copy`: the `--to` folder, holding the volume's root and level metadata, the box's chunk files at their own keys, and `zarrbox.json` |
| Go-ahead | Not needed: it copies public open data to a local folder |
| Released | Public `main` since 2026-10-30 |
| Checked | 2026-10-30 against commit `6148ce7` |

## What it does

Training, testing and debugging often need the same small region of a scan volume again and again. Reading it from the open-data bucket each time is slow, and a crop saved as a new array (a TIFF stack, a re-encoded zarr) loses the volume's own coordinates, its pyramid metadata and any way to show that the bytes are the source's.

`zarrbox` takes a box in level-0 voxels (`Z0-Z1,Y0-Y1,X0-X1`, half-open, `*` for a whole axis), widens it to the chosen pyramid level's chunk grid, and copies the volume's metadata and only those chunk files into a folder, keeping the zarr key layout. A zarr reader opens the folder as the same volume at the same coordinates: inside the box it reads the source's voxels, outside it reads the fill value. Chunks are never decoded or re-encoded, so a compressed volume stays as stored. `zarrbox.json` beside them records the source, level, box, each chunk's size and sha256, the chunks the source does not store, and one sha256 over the whole list.

`verify` checks a copy later: every listed file is there with its sha256, no unlisted chunk file sits at that level, and the list's own sha256 still matches. With `--source` it reads every chunk again from the source, so a copy can be tied back to the bucket at any time.

It does not choose the box, resample, normalize or open the volume for you. A box copy is a copy of a public scan, not a reading of it; it holds no labels and makes no claim about the scroll.

## When to use it

- A region will be read many times (training patches, a benchmark crop, a debug case) and should be local, at its own coordinates.
- A box should be handed to someone with proof it is the source's bytes: send the folder, they run `verify --source`.
- Before a long download, to see how many chunks and bytes a box holds and how many the source leaves empty: `plan`.

Do not use it:

- For the chunks a tifxyz mesh touches rather than a box: use [tifxyz](tifxyz.md) `chunks --fetch`.
- To mirror a whole bucket prefix (a segment folder, a label store): use [fetch](fetch.md).
- To read a small region once into memory: open the volume with a zarr reader directly.
- For a mesh-shaped sparse copy at every pyramid level, re-encoded: villa's `extract_sparse_ome_zarr.py` (in the `vesuvius` package, `vesuvius/scripts/`) does that from tifxyz surfaces.

## Quick start

```bash
python -m kit zarrbox plan VOLUME --box Z0-Z1,Y0-Y1,X0-X1
python -m kit zarrbox copy VOLUME --box Z0-Z1,Y0-Y1,X0-X1 --to DEST
python -m kit zarrbox verify DEST --source
```

- `VOLUME`: the volume's zarr folder or URL, such as `s3://vesuvius-challenge-open-data/PHerc0139/volumes/20260102150214-2.399um-0.2m-78keV-masked.zarr`.
- `Z0-Z1,Y0-Y1,X0-X1`: the box in level-0 voxels, half-open; `*` for a whole axis. Add `--level L` for a coarser level.
- `DEST`: the folder to write, such as `box.zarr`.

Run on 2026-10-30 in a 4-core cloud container with that PHerc0139 volume and `--box 38400-38656,13184-13440,13184-13440`, `copy` printed:

```
s3://vesuvius-challenge-open-data/PHerc0139/volumes/20260102150214-2.399um-0.2m-78keV-masked.zarr, level 0 (full resolution), chunks 128 x 128 x 128 (z, y, x)
  box        z 38400-38656, y 13184-13440, x 13184-13440 (level voxels, widened to the chunk grid)
  chunks     8
  stored     8 present, 16.8 MB; 0 absent (read as the fill value)
  copied     8 chunks written, 0 already there, into box.zarr
  manifest   box.zarr/zarrbox.json: 8 sha256 rows, chunks_sha256 d39520c819aabad2
```

and `verify box.zarr --source` printed `OK` and `source     8 keys checked; 0 differ, 0 absent then and present now`. It worked when `copy` exits 0 and `verify` prints `OK` and exits 0.

## Checks and controls

Byte equality with the source, read by a different reader: zarr-python 3.4.2 read the box from the copy (`box.zarr/0`, shape (76953, 26511, 26511)) and from the bucket; the (256, 256, 256) uint8 arrays were equal, mean 39.24 (2026-10-30). The control can fail and did as intended: the chunk just past the box in z (z 38,656 to 38,784) read all zeros from the copy (the fill value) and mean 42.36 from the bucket, so the arrays differed. A copy that held more than the box, or read the wrong chunks, would fail one of the two.

`verify` can fail: `tests/test_zarrbox.py` changes a chunk, deletes one, plants an unlisted one, edits a manifest row, changes a chunk in the source and makes an absent source chunk appear, and requires each to be reported by its own field with `ok` false and exit code 1.

Claim label: Sourced fact, for the times, the printed output and the equality and control results above (measured 2026-10-30). None for the copies themselves: the tool makes no claim about the scroll.

## Commands and options

### `python -m kit zarrbox plan`

```
usage: python -m kit zarrbox plan [-h] --box BOX [--level LEVEL] [--max-requests MAX_REQUESTS] [--json] volume
```

| Option | Default | Meaning |
| --- | --- | --- |
| `volume` | required | the volume's zarr folder or URL (https://, or s3:// on the open-data bucket) |
| `--box BOX` | required | Z0-Z1,Y0-Y1,X0-X1 in level-0 voxels, half-open; * for a whole axis |
| `--level LEVEL` | `0` | pyramid level to copy (0 is full resolution) |
| `--max-requests MAX_REQUESTS` | `20000` | refuse a box with more chunks |
| `--json` | off | print JSON instead of lines |

### `python -m kit zarrbox copy`

```
usage: python -m kit zarrbox copy [-h] --box BOX [--level LEVEL] [--max-requests MAX_REQUESTS] [--json] --to DEST
                                  [--workers WORKERS]
                                  volume
```

| Option | Default | Meaning |
| --- | --- | --- |
| `volume` | required | the volume's zarr folder or URL (https://, or s3:// on the open-data bucket) |
| `--box BOX` | required | Z0-Z1,Y0-Y1,X0-X1 in level-0 voxels, half-open; * for a whole axis |
| `--level LEVEL` | `0` | pyramid level to copy (0 is full resolution) |
| `--max-requests MAX_REQUESTS` | `20000` | refuse a box with more chunks |
| `--json` | off | print the manifest without its per-file lists |
| `--to DEST` | required | the folder to write (created; reruns skip chunks already there at the same size) |
| `--workers WORKERS` | `32` | parallel downloads from a URL |

### `python -m kit zarrbox verify`

```
usage: python -m kit zarrbox verify [-h] [--source] [--json] dest
```

| Option | Default | Meaning |
| --- | --- | --- |
| `dest` | required | a folder kit zarrbox copy wrote |
| `--source` | off | also read every chunk again from the source and compare |
| `--json` | off | print JSON instead of lines |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `parse_box(text)` | list of three `[lo, hi]` or `None` (whole axis), level-0 voxels | `VerifyError` | Half-open; `0 <= lo < hi` |
| `box_chunks(arr, box)` | (level box aligned to the chunk grid, chunk index ranges, chunk count) | `VerifyError` when the box misses the volume | `arr` from `kit.tifxyz.zarr_level` |
| `plan(volume, box, level=0, max_requests=20000, src=None, sizes=True)` | (report dict, chunk keys, sizes with `None` for absent) | `VerifyError`, `OSError` | One HEAD per chunk on a URL; `sizes=False` skips them |
| `copy(volume, box, dest, level=0, max_requests=20000, workers=32, src=None, now=None)` | the manifest dict, also written to `dest/zarrbox.json` | `VerifyError` (bad box, too many chunks, short disk), `OSError` | Keeps 1 GiB free, as `kit fetch` does |
| `verify(dest, source=False, src=None)` | (report dict, ok) | `VerifyError` when `dest/zarrbox.json` is missing or another schema | `source=True` reads every chunk again |
| `format_plan(r)`, `format_copy(m, dest)`, `format_verify(r)` | the text the command prints | nothing | |
| `build_parser(p)` | the parser with the three actions | nothing | Used by `kit/cli.py` |
| `run(args)` | exit code | `VerifyError`, `OSError` | Runs one action and prints its result |
| `cmd_zarrbox(args)` | exit code | nothing | `run` with errors turned into exit 2 |
| `main(argv=None)` | exit code | nothing | `python -m kit.zarrbox` |

## Inputs

- **Volume:** a zarr v2 or v3 array, or an OME-Zarr multiscale group, on disk or behind `https://` or `s3://vesuvius-challenge-open-data/...` (mapped to its public HTTPS host). Three axes, z, y, x. Key layouts: v2 with `.` or `/` separators, v3 default (`c/` prefix) or v2 encoding. A sharded v3 array is copied by shard, its stored unit. The level's scale against level 0 comes from the OME `coordinateTransformations`, or 2 to the level.
- **Box:** whole voxels of level 0, half-open, `Z0-Z1,Y0-Y1,X0-X1`, `*` for a whole axis. At level L the box is divided by the level's scale (start rounded down, end up), widened to that level's chunk grid and clipped to its shape.
- **Size:** a box may hold at most `--max-requests` chunks (default 20,000; at 2 MiB per uncompressed 128-voxel chunk that is about 42 GB). `copy` refuses when the disk would keep less than 1 GiB free.

## Outputs

`plan` prints the volume, level, chunk shape, the widened box in level voxels, the chunk count, and how many chunks the source stores (with their bytes) and leaves absent. `--json` gives the report dict.

`copy` writes `DEST/` with the volume's root metadata (`.zattrs`, `.zgroup`, `.zmetadata`, `zarr.json` where present), every level's `.zarray`, `.zattrs` or `zarr.json`, the box's chunk files at their own keys, and `DEST/zarrbox.json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | string | `scrolls-zarrbox/1` |
| `made_utc` | string | when the copy was made |
| `volume` | string | the source as given |
| `level`, `level_path` | int, string | the pyramid level and its array path |
| `level_factor_zyx` | list of 3 floats | the level's scale against level 0 |
| `shape_zyx`, `chunk_zyx`, `dtype`, `sharded` | | the level array's shape, stored unit, data type and whether it is sharded |
| `box_base` | list | the box as asked, level-0 voxels (`null` for a whole axis) |
| `box_level` | list of 3 `[lo, hi]` | the box copied, level voxels, aligned to the chunk grid |
| `chunks`, `present`, `absent`, `bytes` | int | chunk count; chunks stored and copied; chunks the source does not store; their bytes |
| `written`, `skipped` | int | chunk files written by this run; already there at the same size |
| `chunks_sha256` | string | sha256 over the sorted `KEY SHA256` lines of `files` |
| `files` | list of `{key, bytes, sha256}` | one row per copied chunk |
| `absent_keys` | list of strings | chunks of the box the source does not store (they read as the fill value) |
| `meta` | list of `{key, sha256}` | the metadata files copied |

`verify` prints `OK` or `FAIL` and the counts; `--json` gives `dest`, `volume`, `level`, `files`, `missing`, `changed`, `extra`, `chunks_sha256_ok`, `ok`, and with `--source` a `source` dict with `checked`, `differ` and `now_present`.

| Exit code | Meaning |
| --- | --- |
| `0` | `plan` or `copy` done; `verify`: the copy matches its manifest (and the source, with `--source`) |
| `1` | `verify` found a missing, changed or extra file, an edited manifest, or a source chunk that differs or appeared |
| `2` | Bad input (box, level, too many chunks, no manifest) or a read or write that failed |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit zarrbox: --box needs three ranges Z0-Z1,Y0-Y1,X0-X1 (got TEXT)` | The box is not three ranges | Give all three axes; `*` for a whole one |
| `kit zarrbox: --box AXIS range TEXT is not START-END in whole voxels (or *)` | A range is not two whole numbers | Write it as `START-END`, such as `2048-2304` |
| `kit zarrbox: --box AXIS range TEXT needs 0 <= START < END` | A range is empty, reversed or negative | Swap or fix the numbers |
| `kit zarrbox: the box lies outside the volume at level L (shape [Z, Y, X])` | The box misses the level's shape | Check the shape with `plan VOLUME --box '*,*,*' --level 5 --json` |
| `kit zarrbox: the box holds N chunks at level L, over --max-requests M: raise it, take a coarser --level or a smaller --box` | A large box | Raise `--max-requests`, take a coarser `--level` or a smaller box |
| `kit zarrbox: --fetch needs X GB plus 1 GB spare in DEST; Y GB free` | Short disk (the message comes from the copy zarrbox shares with `tifxyz chunks --fetch`) | Free space or copy to another disk |
| `kit zarrbox: DEST has no zarrbox.json: is it a kit zarrbox copy?` | `verify` on a folder `copy` did not write | Give the folder `copy --to` wrote |
| `kit zarrbox: DEST/zarrbox.json is schema S, not scrolls-zarrbox/1` | The manifest is from another tool or version | Copy again with this version |
| `kit zarrbox could not read or write a file: ERROR` | A read or write failed (permissions, a network error after 5 tries) | Fix the path or network and rerun; finished chunks are kept |
| `kit zarrbox: ...` with a message about levels, multiscales or array metadata | The volume is not a 3-axis zarr or OME-Zarr, or `--level` is not one of its levels | Give the `.zarr` folder or URL itself; read its levels from `.zattrs` |
| `plan` reports every chunk absent | A masked volume stores no chunks outside the scroll, or the box is off the scroll | Move the box toward the scroll's middle; a coarse `plan` shows where chunks are |
| `FAIL` with `changed` | A chunk file was edited or damaged after the copy | Delete it and rerun `copy` with the same box; it fetches only missing files |
| `FAIL` with `source ... differ` | The source chunk changed since the copy (a re-upload) | Copy again into a new folder; keep the old manifest if results depend on it |

## How it works

1. `kit.tifxyz.zarr_level` reads the volume's root and level metadata and returns the level's shape, stored unit, key prefix and separator, and scale against level 0.
2. The level-0 box is divided by that scale (start floored, end ceiled), clipped to the level's shape, and widened to whole chunks: chunk index `floor(lo / c)` to `ceil(hi / c)`.
3. Each chunk index becomes its key in the array's own layout (`kit.tifxyz.chunk_key`). `plan` sizes each key with one HEAD (32 at a time on a URL; `CHUNK_WORKERS`); a 403 or 404 means the source does not store it.
4. `copy` calls `kit.tifxyz.fetch_chunks`: it checks the disk keeps 1 GiB free (`SPARE_BYTES`), copies the root and every level's metadata, and downloads each present chunk to `KEY.part` before renaming it, skipping a file already there at the same size.
5. Each copied chunk file is hashed (sha256) from disk; the sorted `KEY SHA256` lines are hashed again into `chunks_sha256`.
6. `verify` rehashes every listed file, lists any chunk file under the level's folder that the manifest does not name, and recomputes `chunks_sha256`. With `--source` it GETs every listed key and HEADs every absent key from the source.

## Cost and time

Free: public data, any CPU. Time is network bound: on 2026-10-30 in a 4-core Claude cloud container, `copy` of 8 chunks (16.8 MB) took 6.0 s and `verify --source` 2.2 s. Larger boxes scale with chunk count and bandwidth; run `plan` first for the byte count.

## For agents

- **Command:** `python -m kit zarrbox plan VOLUME --box BOX --json`, then `python -m kit zarrbox copy VOLUME --box BOX --to DEST --json`, then `python -m kit zarrbox verify DEST --json`.
- **Parse:** `plan`: `chunks`, `present`, `absent`, `bytes`, `box_level`. `copy`: the same plus `written`, `skipped`, `chunks_sha256`. `verify`: `ok`, and `missing`, `changed`, `extra`, `source.differ`, `source.now_present` when it is false.
- **Rerun:** safe. `copy` into the same folder fetches only files not there at the same size and rewrites `zarrbox.json`; a different box into the same folder adds chunks and the manifest then lists only the new box, so `verify` reports the earlier box's chunks as extra. Use one folder per box.
- **Success:** exit 0; `verify` prints `OK` and `ok` is true.
- **Not a pass:** `present` 0 with exit 0 means the box holds no stored data, not a good copy; a `verify` without `--source` shows only that the folder matches its own list.
- **Go-ahead:** Nothing.
- **Never:** never commit a copy or its chunks to git (hard rule 6); never call a box copy a result or a reading.

## Tests

`python -m unittest tests.test_zarrbox -v` (10 tests, standard library only, about 0.4 s). They build zarr v2 pyramids (`/` and `.` separators) and a v3 array with distinct bytes per chunk and check: box parsing and its refusals; widening to the grid and counting absent chunks; level 1 halving the box; refusals for a box outside the volume or over `--max-requests`; that `copy` writes the metadata and exactly the box's chunk files, byte for byte, with matching sha256 rows, and that a rerun skips them; an absent chunk recorded and not written; `verify` catching a changed, missing and extra chunk and an edited manifest; `verify --source` catching a changed source chunk and an absent one that appeared; and the command's exit codes. They do not download anything; the live run above is the network check.

## History

- 2026-10-30: added `plan`, `copy` and `verify` (`6148ce7`).

## Related

- [tifxyz](tifxyz.md): `chunks --fetch` copies the chunks a mesh touches, the same way; zarrbox reuses its reader.
- [fetch](fetch.md): mirrors whole bucket prefixes.
- [s3relay](s3relay.md): S3 can answer a false 404 for a chunk that exists. zarrbox, like `tifxyz chunks`, counts any 403 or 404 as absent, so a box whose `plan` shows unexpected absent chunks should be planned again; `verify --source` reports an absent chunk that has since appeared as `now_present`.
