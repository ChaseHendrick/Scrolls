# fibers: read the AFV fibers in one box of a scan without downloading the whole scan

Stream the papyrus fibers in any box of a scan from the public AFV Fibers datasets on Hugging Face, reading only the Parquet shards that box needs, with exactly the same fibers and `.afv` bytes as filtering the full download.

| Field | Value |
| --- | --- |
| Id | `fibers` |
| Status | Current |
| Kind | kit command |
| Area | Data and downloads |
| Run | `python -m kit fibers scans`, `python -m kit fibers stream`, `python -m kit fibers filter`, `python -m kit fibers parity`, `python -m kit fibers build` |
| Code | `kit/fiberstream.py`, `kit/cli.py` (`cmd_fibers`), `scripts/fiberstream/stream_job.py` (the Hugging Face Job that built and checked the published shards) |
| Tests | `tests/test_fiberstream.py` |
| Needs | Python 3.10 or newer, numpy, and pyarrow 14 or newer for `stream` and `build` (`pip install "numpy" "pyarrow"`); nothing for `scans`. VC3D and villa's `import_afv.py` to open a written `.afv` in VC3D |
| Runs on | Any machine. A small or medium box takes 0.1 to 4 s over the network, a 1024-grid-voxel box 0.5 to 16 s (measured 28 Oct 2026 from Hugging Face CPU Jobs, Cost and time) |
| Network | `huggingface.co` and the file servers it redirects to (HTTP range requests for `stream` and `parity`); none for `filter`, `build`, or `--source DIR` |
| Writes | Nothing unless asked: `--out BOX.afv`, `--json FIBERS.json`; `parity --out` also writes `BOX.afv.reference.afv`; `build` writes `stream/` under its output folder |
| Go-ahead | Not needed to read. Publishing shards to a dataset follows rule 8 |
| Released | Public `main`; stream shards for the six datasets `SharpMeow/SCAN-afv-fibers`, built and checked 28 Oct 2026 |
| Checked | 2026-10-28 against commit `bd27a0d` |

## What it does

The [AFV Fibers](afv-fibers.md) datasets hold every papyrus fiber Qual's AFV V2 model and spline generator traced in six whole scans, as `.afv` files of 1.5 to 17 GB each. Most uses need only the fibers near one place. `kit fibers stream` reads just those: each dataset now also carries `stream/`, the same fibers as Parquet files laid out on a spatial grid, with an index that says which file covers which box. The client asks for the index, then only the files and row groups whose bounds meet the box, by HTTP range requests, and picks the fibers with the same rule every `.afv` reader uses.

The answer equals filtering the full download: the same fiber ids, table rows, blocks, R-tree bounds and points, and a byte-identical `.afv` when written with `--out`. The existing downloads (`SCAN_afv_v2.afv`, the 1 mm file, `tiles/`) are unchanged.

`build` makes the shards from any `.afv`, so the same layout serves any fiber set, including a later one; `stream --repo OWNER/NAME` reads any dataset that has `stream/index.json`.

The fibers are model output nobody has checked fiber by fiber: geometry, a map of papyrus structure, never a reading of any text.

## When to use it

- To get the fibers in a region of one of the six scans, in a script or an agent, without a multi-GB download.
- To open one region's fibers in VC3D: `--out BOX.afv`, then villa's importer.
- To iterate over every fiber of a scan as rows (the `datasets` library, Quick start).
- To make stream shards for another `.afv` (`build`), and check them (`parity`).

Do not use it:

- To look at fibers over the CT in a browser: use the [AFV Fibers](afv-fibers.md) Space.
- For a whole scan in VC3D: download `SCAN_afv_v2_1mm.afv` once; it is smaller than streaming every box.
- For a scan not in `python -m kit fibers scans`: check the Space's Catalog for other fiber sets.

## Quick start

```bash
pip install numpy pyarrow
python -m kit fibers stream --scan PHerc1667 --box 5632 6656 5632 6656 5632 6656 --out box.afv
```

It printed (28 Oct 2026, from a cloud container, abridged):

```
{"fibers": 461, "H": 201, "V": 260, "points": 113725, "digest": "133999e116d1...", "box_zyx": [5632, 6656, 5632, 6656, 5632, 6656], "files": 5, "row_groups": 21, "row_groups_total": 3000, "files_total": 149, "bytes": 8423652, "requests": 54, "seconds": 11.929, ...}
```

8.4 MB read of the scan's 1.5 GB file; the digest and the written `box.afv` (sha256 `a0f40c73...`) equal those from filtering the full download.

The box is Z0 Z1 Y0 Y1 X0 X1 in level-0 voxels of the scan (lows inclusive, highs exclusive). It worked when `fibers` is above zero for a box inside the papyrus. `box.afv` copies the source file's schema, pragmas and metadata for villa's importer; nobody has opened a streamed box in VC3D yet. Add `--family H` or `V`, or `--min-len 1` for the 1 mm set.

Every fiber of a scan as rows, with the `datasets` library (streaming, no download):

```python
from datasets import load_dataset
ds = load_dataset("SharpMeow/pherc1667-afv-fibers", data_files="stream/**/*.parquet", streaming=True, split="train")
for row in ds.take(3):
    print(row["id"], row["family"], row["length_mm"], len(row["points"]) // 3)
```

Each row is one fiber: the `.afv` columns, its bounding box (`bmin_x` to `bmax_z`), its blocks and its points (flat `x, y, z` float64). A box filter on the bounding box (`filters=[("bmax_z", ">=", Z0), ...]`) is a superset of the exact box; `kit fibers stream` applies the exact rule.

## Checks and controls

Each published scan's shards were built and checked in one Hugging Face CPU Job (`scripts/fiberstream/stream_job.py`), with boxes fixed from the tile counts before any shard existed: small (32 grid voxels on a side), medium (256) and large (1024) boxes around five tile centers, a box across the corner where eight shard files meet, a control box outside the scan, and the whole scan.

- **Parity.** Every box, and the family and 1 mm filters on two medium boxes: the streamed fibers and the written `.afv` bytes equal the full file's. The whole scan: an order-free digest over every fiber equals the full file's.
- **Published 1 mm file.** `--min-len 1` over the shards gives the published `SCAN_afv_v2_1mm.afv` curves, per medium box and over the whole file.
- **Controls that can fail.** Leaving out one row group the medium box reads breaks parity (the check caught it on every scan). The published 1 mm file is an outside reference the shards must reproduce. In the tests, a duplicated fiber changes the order-free digest, and a box across shard edges neither drops nor repeats a fiber.
- **Sanity check.** The control box outside the scan returns no fiber both ways; it can hardly fail, so it is not counted as a control.
- **Hosted copy.** After upload, every box was streamed again over HTTP from the dataset and compared with the full file's digests; every hosted shard's size and sha256 match the index.

Results of the six Jobs (28 Oct 2026; Boxes counts the 15 small, medium and large boxes, the edge box and the control box). Some boxes hold no fibers: 12 of the 96 boxes and 3 of the 36 filter checks (PHerc0009B alone has 4 empty boxes and 3 empty filters), so the 84 boxes with fibers carry the parity result:

| Scan | Fibers | Shards (files, GB) | Boxes equal (local, hosted) | Filters equal | Control box | Dropped row group caught | Whole scan digest | 1 mm set equal |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PHerc0009B | 1,341,032 | 329, 0.78 | 17 of 17, 17 of 17 | 6 of 6 | 0 fibers | yes | equal | yes |
| PHerc0139 | 6,812,631 | 905, 5.13 | 17 of 17, 17 of 17 | 6 of 6 | 0 fibers | yes | equal | yes |
| PHerc0332 | 712,045 | 145, 0.62 | 17 of 17, 17 of 17 | 6 of 6 | 0 fibers | yes | equal | yes |
| PHerc0814 | 5,542,700 | 661, 4.03 | 17 of 17, 17 of 17 | 6 of 6 | 0 fibers | yes | equal | yes |
| PHerc0841 | 8,147,573 | 912, 4.99 | 17 of 17, 17 of 17 | 6 of 6 | 0 fibers | yes | equal | yes |
| PHerc1667 | 645,762 | 149, 0.45 | 17 of 17, 17 of 17 | 6 of 6 | 0 fibers | yes | equal | yes |

Claim label: Model output (the fibers); the parity results above are measurements of the files.

## Commands and options

### `python -m kit fibers scans`

```
usage: python -m kit fibers scans [-h]
```

Prints one line per scan: scan id, dataset, the CT level the model ran on.


### `python -m kit fibers stream`

```
usage: python -m kit fibers stream [-h] --box Z0 Z1 Y0 Y1 X0 X1
                                   [--family {H,V}] [--min-len MM]
                                   [--out BOX.afv] [--json FIBERS.json]
                                   [--scan SCAN] [--repo REPO]
                                   [--revision REVISION] [--source DIR]
                                   [--threads THREADS]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--box Z0 Z1 Y0 Y1 X0 X1` | required | the box in level-0 voxels, lows inclusive and highs exclusive |
| `--family FAMILY` | none | only horizontal (H) or vertical (V) fibers |
| `--min-len MM` | none | only fibers at least this long, in mm |
| `--out BOX.afv` | none | write the fibers as an .afv with the source file's schema and metadata, for villa's importer |
| `--json FIBERS.json` | none | write the fibers as JSON: id, family, length, points |
| `--scan SCAN` | none | a scan with a public dataset (python -m kit fibers scans) |
| `--repo REPO` | none | any dataset with stream shards, OWNER/NAME (instead of --scan) |
| `--revision REVISION` | `main` | the dataset's branch, tag, commit or refs/pr/N |
| `--source DIR` | none | a local folder with stream/ (instead of Hugging Face) |
| `--threads THREADS` | `8` | parallel range requests |

### `python -m kit fibers filter`

```
usage: python -m kit fibers filter [-h] --box Z0 Z1 Y0 Y1 X0 X1
                                   [--family {H,V}] [--min-len MM]
                                   [--out BOX.afv] [--json FIBERS.json]
                                   afv
```

The same box from a downloaded `.afv`: the reference a stream must equal.

| Option | Default | Meaning |
| --- | --- | --- |
| `afv` | required | a whole-scan .afv |
| `--box Z0 Z1 Y0 Y1 X0 X1` | required | the box in level-0 voxels, lows inclusive and highs exclusive |
| `--family FAMILY` | none | only horizontal (H) or vertical (V) fibers |
| `--min-len MM` | none | only fibers at least this long, in mm |
| `--out BOX.afv` | none | write the fibers as an .afv with the source file's schema and metadata, for villa's importer |
| `--json FIBERS.json` | none | write the fibers as JSON: id, family, length, points |

### `python -m kit fibers parity`

```
usage: python -m kit fibers parity [-h] --box Z0 Z1 Y0 Y1 X0 X1
                                   [--family {H,V}] [--min-len MM]
                                   [--out BOX.afv] [--json FIBERS.json]
                                   [--scan SCAN] [--repo REPO]
                                   [--revision REVISION] [--source DIR]
                                   [--threads THREADS]
                                   afv
```

Streams the box and filters the downloaded file; prints both digests and `"verdict": "PASS"` or `"FAIL"`. With `--out` it also compares the two written `.afv` files byte for byte.

| Option | Default | Meaning |
| --- | --- | --- |
| `afv` | required | the whole-scan .afv the shards were built from |
| `--box Z0 Z1 Y0 Y1 X0 X1` | required | the box in level-0 voxels, lows inclusive and highs exclusive |
| `--family FAMILY` | none | only horizontal (H) or vertical (V) fibers |
| `--min-len MM` | none | only fibers at least this long, in mm |
| `--out BOX.afv` | none | write the fibers as an .afv with the source file's schema and metadata, for villa's importer |
| `--json FIBERS.json` | none | write the fibers as JSON: id, family, length, points |
| `--scan SCAN` | none | a scan with a public dataset (python -m kit fibers scans) |
| `--repo REPO` | none | any dataset with stream shards, OWNER/NAME (instead of --scan) |
| `--revision REVISION` | `main` | the dataset's branch, tag, commit or refs/pr/N |
| `--source DIR` | none | a local folder with stream/ (instead of Hugging Face) |
| `--threads THREADS` | `8` | parallel range requests |

### `python -m kit fibers build`

```
usage: python -m kit fibers build [-h] [--level LEVEL] [--scan SCAN]
                                  [--workers WORKERS] [--no-sha256]
                                  afv out_dir
```

Writes `stream/` and `stream/index.json` under `out_dir`, then checks them (`verify_build`); prints the totals and the check as JSON.

| Option | Default | Meaning |
| --- | --- | --- |
| `afv` | required | a whole-scan .afv |
| `out_dir` | required | the folder to write stream/ in (the dataset's root) |
| `--level LEVEL` | `0` | the CT level the fibers were traced on (grid voxel = 2**level) |
| `--scan SCAN` | none | the scan id written into the index |
| `--workers WORKERS` | `0` | worker processes (0: one per CPU) |
| `--no-sha256` | off | skip the source file's sha256 in the index |

### `scripts/fiberstream/stream_job.py` (the Hugging Face Job)

```
python3 stream_job.py --code DIR --scan SCAN --out DIR [--work DIR] [--workers N] [--upload] [--smoke]
```

Builds one dataset's shards, checks them against the whole-scan file and, with `--upload`, opens a pull request on the dataset with `stream/` only, then checks the hosted copy. Writes `SCAN.json` (or `SCAN-smoke.json`) under `--out`. 
| Option | Default | Meaning |
| --- | --- | --- |
| `--code DIR` | required | a folder with `kit/__init__.py`, `kit/fiberstream.py` and `tests/test_fiberstream.py` |
| `--scan SCAN` | required | one of `python -m kit fibers scans` |
| `--out DIR` | required | where the result JSON goes |
| `--work DIR` | `/tmp/fstream` | downloads and shards |
| `--workers N` | CPU count | worker processes |
| `--upload` | off | after a local PASS, open the dataset pull request and check it over HTTP |
| `--smoke` | off | one tile stands in for the scan; no upload |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `HF_XET_CHUNK_CACHE_SIZE_BYTES` | set to `0` by `stream_job.py` | the Hugging Face download chunk cache; off in the Job so downloads do not fill its disk |

## Python API

`from kit import fiberstream as fs`. Boxes are `[z0, z1, y0, y1, x0, x1]` in level-0 voxels.

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `FiberStreamError()` | an exception | | A refusal or failure, printed as is by the CLI (exit 2). |
| `Fiber(row, block_ids, block_first, bounds, points)` | one fiber | | `row` is the `fibers` table row; `bounds` the blocks' float32 R-tree bounds; `points` (N, 3) float64 x, y, z. `.id`, `.family`, `.length_mm`, `.digest()` |
| `SCANS` | dict scan id to `{"repo", "level"}` | | the six public datasets |
| `box_touches(bounds, box)` | boolean array, one per bounds row | | the R-tree rule: max >= lo and min < hi on every axis, in float64 |
| `read_afv(path, box=None, family=None, min_len=None, check=True)` | generator of `Fiber`, by id | `FiberStreamError` | the reference: a downloaded `.afv` filtered |
| `afv_source_info(path, sha256=False)` | dict: file, bytes, metadata, schema, pragmas, counts | `FiberStreamError` | what `write_afv` needs |
| `write_afv(fibers, dest, source, box=None, family=None, min_len=None)` | dict of counts | `FiberStreamError` | the same fibers give the same bytes |
| `records_digest(fibers)` | `(sha256 hex, count)` | | over the fibers in the order given |
| `multiset_digest(fibers)` | `(hex, count)` | | order-free; catches a missing or repeated fiber |
| `Source(repo=None, revision='main', local=None, base_url=None, timeout=60, tries=4)` | a source | `FiberStreamError` | a dataset revision, a local folder or any range-capable HTTP server; counts `bytes` and `requests` |
| `RangeFile(source, path, size)` | a read-only file object | `FiberStreamError` | ranges for pyarrow |
| `open_index(source)` | the parsed `stream/index.json` | `FiberStreamError` | checks format and version |
| `stream(box, scan=None, repo=None, revision='main', local=None, family=None, min_len=None, threads=8, base_url=None)` | `(fibers by id, stats, index source block)` | `FiberStreamError` | stats: bytes, requests, files, row_groups, seconds |
| `iter_stream(box, source, index=None, family=None, min_len=None, threads=8, stats=None, skip=())` | generator of lists of `Fiber` | `FiberStreamError` | `box=None` streams every fiber; memory stays one window of files |
| `build(afv, out_dir, level=0, scan=None, workers=None, sha256=True, say=print)` | the index dict | `FiberStreamError` | writes the shards |
| `verify_build(out_dir, afv=None)` | `{"ok", "problems", "rows", "files"}` | | sizes, sha256, every id once, boxes hold their rows |
| `main(argv=None)` | exit code | | the CLI |

## Inputs

- A box in level-0 voxels of the scan's CT volume (the volume named on each dataset card; for PHerc0332 and PHerc1667 level 0 of the 2.399 um scan, though the model ran on level 2).
- For `stream`: a dataset with `stream/index.json` (the six AFV Fibers datasets, `--repo`, or a local folder with `--source`).
- For `filter`, `parity` and `build`: an `.afv` (VC3D fiber collection version 1, the SQLite format Qual's AVF_SPLINE_GENERATOR writes).

## Outputs

`stream` and `filter` print one JSON line:

| Field | Type | Meaning |
| --- | --- | --- |
| `fibers`, `H`, `V` | int | fibers in the box, and by family |
| `points` | int | points in those fibers |
| `digest` | str | sha256 over the fibers in id order (rows, blocks, bounds, points); equal digests mean equal fibers |
| `box_zyx` | list | the box |
| `bytes`, `requests` | int | (stream) bytes read and HTTP requests made |
| `files`, `row_groups` | int | (stream) shard files and row groups read |
| `files_total`, `row_groups_total` | int | (stream) in the whole dataset |
| `seconds` | float | wall time |
| `out`, `out_sha256`, `json` | str | the files written, when asked |

`--out BOX.afv` writes a valid `.afv` (the source's schema and metadata, counts updated, `box_zyx_l0`, `family` and `minimum_length_mm` added). `--json` writes a list of `{"id", "family", "length_mm", "points_xyz"}`.

Stream shards (`build`, and `stream/` in each dataset), format `afv-stream` version 1:

| Path | Meaning |
| --- | --- |
| `stream/index.json` | the scan, the source `.afv` (metadata, schema, counts, sha256), the grid, and every shard file with its box (whole voxels, rounded outward), rows, row groups, bytes, footer size and sha256 |
| `stream/L{k}/z{Z}_y{Y}_x{X}[-pN].parquet` | one row per fiber, every fiber in exactly one file; level k is the smallest whose cell (256 x 2^k grid voxels) holds the fiber's extent; Z, Y, X the file's corner in level-0 voxels |

| Exit code | Meaning |
| --- | --- |
| `0` | done; for `parity`, the stream equals the full file (PASS); for `build`, the written shards check out |
| `1` | `parity` FAIL, or `build`'s check found a problem |
| `2` | a refusal or failure (the message on stderr), or bad arguments |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `a box is six numbers: Z0 Z1 Y0 Y1 X0 X1 (level-0 voxels)` | `--box` did not get six numbers | Give Z0 Z1 Y0 Y1 X0 X1 |
| `empty box...: each low bound must be below its high bound` | A low bound at or above its high bound | Swap them |
| `no such file:...` | The `.afv` path is wrong | Check the path |
| `fiber...has no row in the fibers table` | A broken `.afv` | Download the file again |
| `fiber...has no blocks` | A broken `.afv` | Download the file again |
| `fiber...:...points in its blocks, point_count says...` | A broken `.afv` | Download the file again |
| `could not read...:...` | The network failed after 4 tries | Check the connection; run again |
| `...:...is format...version...; this reader knows...version...` | The dataset's shards are a newer format | Update kit |
| `...holds..., not...` | `--scan` and the dataset disagree | Use the matching `--scan` or `--repo` |
| `...fibers have blocks, the fibers table has...` | `build`: a broken `.afv` | Download the file again |
| `wrote...rows for...fibers` | `build` lost fibers (a bug) | Report it; do not upload |
| `numpy is needed: pip install numpy` | numpy missing | `pip install numpy` |
| `pyarrow is needed to read or write stream shards: pip install pyarrow` | pyarrow missing | `pip install pyarrow` |
| `fiber...: block...does not start on the last point of the block before it` | A broken or non-standard `.afv` | Download the file again |
| `fiber...: block...is missing from block_bounds` | A broken `.afv` | Download the file again |
| `fiber...: its first block starts at segment..., not 0` | A non-standard `.afv` | Use a file written by AVF_SPLINE_GENERATOR or VC3D |
| `fiber...: its blocks cannot be rebuilt from its points` | A non-standard `.afv`; the shards could not reproduce it byte for byte | Use a standard file |
| `fiber...: its R-tree bounds are not float32 values` | A non-standard `.afv` | Use a standard file |
| `name a dataset (--scan or --repo) or a local folder (--source)` | No source given | Add `--scan SCAN` |
| `...:...is not JSON` | `stream/index.json` is damaged or not an index | Check the revision |
| `no stream dataset known for...; scans:...(or give --repo)` | The scan has no public dataset | Use `python -m kit fibers scans`, or `--repo` |
| `fiber...is in two shards: the shards are broken` | The shards repeat a fiber | Report it; use the full download |
| `not found:...` | A local `--source` lacks the file | Check the folder |
| `not found:...(no stream shards at this revision?)` | The dataset or revision has no `stream/` | Check `--revision`, or the dataset |
| `refused (...):...` | 401 or 403 from the server: a private or gated dataset | Log in with `hf auth login`, or use a public dataset |

## How it works

1. **Placement.** Each fiber's bounds (the union of its blocks' R-tree bounds) give its largest extent; it goes to the smallest grid level k whose cell, `CELL` (256) x 2^k grid voxels, is at least that extent, up to `MAX_LEVEL` (8), and to the cell holding its center. A grid voxel is 2^level level-0 voxels (level 2 for PHerc0332 and PHerc1667).
2. **Files and row groups.** A file covers `FILE_CELLS`^3 (64) cells of its level. Inside a cell fibers go in the Morton order of their centers (on a 32-voxel grid), cut into row groups of at most `POINTS_PER_GROUP` (131,072) points or 20,000 fibers; a file holds at most `GROUPS_PER_FILE` (32) row groups, then continues in `-p1`, `-p2`. Points are float64 and bounds float32, exactly as in the `.afv`; zstd level 9 with byte stream split.
3. **Reading a box.** The index names the files whose box meets the query; each file's footer (one ranged read, its size is in the index) names the row groups whose column statistics meet it; the block bounds of those row groups are fetched first, and the rest only for row groups where some block meets the box.
4. **The rule.** A fiber is in the box when one of its blocks' R-tree bounds has max >= lo and min < hi on x, y and z, the rule of `load_example.py` and the AFV Fibers Space.
5. **Writing.** `write_afv` writes fibers, blocks and R-tree rows in id order with the source's schema, pragmas and metadata, so equal fibers give equal bytes.

## Cost and time

Free to use: reading costs nothing. Measured from Hugging Face CPU Jobs on 28 Oct 2026, against the dataset revision with the shards (`scripts/fiberstream/stream_job.py`; full records in private evidence):

| Box (level-0 voxels for level-0 scans; 4 times that for PHerc0332 and PHerc1667) | Boxes | Bytes read, median (range) | Seconds, range | The per-cell tiles the box needs, median |
| --- | --- | --- | --- | --- |
| small, 32 grid voxels | 30 | 5.1 MB (0.1 to 13.4) | 0.05 to 3.9 | 88.7 MB |
| medium, 256 | 30 | 10.3 MB (0.1 to 32.2) | 0.1 to 2.7 | 88.7 MB |
| large, 1024 | 30 | 77.4 MB (0.8 to 159) | 0.5 to 16 | 88.7 MB |
| 128 across 8 shard files | 6 | 4.4 MB (1.7 to 19.1) | 0.9 to 3.1 | 494 MB |
| control, outside the scan | 6 | the index only (0.1 to 0.3 MB) | under 0.1 | none |

| Scan | Whole-scan `.afv` | Whole scan as shards | Shard files |
| --- | --- | --- | --- |
| PHerc0009B | 2.64 GB | 0.78 GB | 329 |
| PHerc0139 | 17.44 GB | 5.13 GB | 905 |
| PHerc0332 | 2.13 GB | 0.62 GB | 145 |
| PHerc0814 | 13.76 GB | 4.03 GB | 661 |
| PHerc0841 | 17.07 GB | 4.99 GB | 912 |
| PHerc1667 | 1.53 GB | 0.45 GB | 149 |

The per-cell `tiles/` that the AFV Fibers Space reads cost a whole 1024-voxel cell file for each cell a box touches. The stream read less than those tiles for every small box and every box across shard files, and for 28 of 30 medium boxes (the other two read under 1 MB); for 9 of the 30 large boxes, each sitting exactly inside one cell, it read more than that one tile (up to 147 against 114 MB), because long fibers stored at coarser grid levels come with their row groups. The whole scan as shards is about 0.29 times the size of the whole-scan `.afv`. Each Job (build, every check, upload and the hosted checks) took 6 to 42 min on an 8-core Hugging Face CPU Job.

## For agents

- **Command:** `python -m kit fibers stream --scan SCAN --box Z0 Z1 Y0 Y1 X0 X1 [--family H|V] [--min-len MM] [--out BOX.afv]`; from Python, `fs.stream(box, scan=SCAN)`.
- **Parse:** the JSON line: `fibers`, `H`, `V`, `digest`, `bytes`, `seconds`; `--json` for the points.
- **Rerun:** Safe; it reads only, and overwrites only the files you name.
- **Success:** exit 0; `fibers` above zero for a box inside the papyrus; `parity` prints `"verdict": "PASS"`.
- **Not a pass:** zero fibers outside the papyrus is right, not a failure; a streamed box is model output, not checked fiber by fiber.
- **Go-ahead:** Nothing to read. Uploading shards to a dataset needs Chase's yes under rule 8.
- **Never:** call the fibers a reading, or rehost them without the CC BY-NC 4.0 terms and Qual's credit.

## Tests

`python -m unittest tests.test_fiberstream -v` (skipped without numpy and pyarrow): a synthetic whole-scan `.afv` in Qual's schema with long multi-block fibers crossing cells and files; shards built and checked; boxes, a box across shard edges and the whole scan equal to the full file, byte for byte when written; a control box empty; a dropped row group and a duplicated fiber caught; files split in parts; a small box reading a small part; the HTTP path through a redirect and range requests; the CLI; refusals. They use no network. The published shards were checked on Hugging Face Jobs (Checks and controls).

## History

- 2026-10-28: first version: `kit fibers` and stream shards on the six AFV Fibers datasets (Chase asked on 28 Oct for streaming beside the downloads) ([public PR](https://github.com/ChaseHendrick/Scrolls/pulls?q=head%3Aclaude%2Ffibers-stream)).

## Related

- [afv-fibers](afv-fibers.md): the datasets and the Space.
- [fibercheck](fibercheck.md): checks fiber agreement against other fiber sets.
