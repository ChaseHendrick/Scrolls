# atlas: Segment Atlas, the same numbers for every published segment

`python -m kit atlas` measures every tifxyz mesh on the open-data bucket with [`kit tifxyz`](tifxyz.md)'s checks and publishes one table, the daily-refreshed dataset [SharpMeow/vesuvius-segment-atlas](https://huggingface.co/datasets/SharpMeow/vesuvius-segment-atlas).

| Field | Value |
| --- | --- |
| Id | `atlas` |
| Status | Current |
| Kind | kit command, kit module, script, data |
| Area | Surfaces and tracing |
| Run | `python -m kit atlas build`, `python -m kit atlas show`, `python -m kit.atlas`, `from kit import atlas`, `python scripts/atlas/hf_atlas.py` |
| Code | `kit/atlas.py`, `kit/cli.py` (`build_parser`), `scripts/atlas/hf_atlas.py` |
| Tests | `tests/test_atlas.py` |
| Needs | Python 3.10 or newer, numpy and tifffile (imagecodecs for the LZW-compressed meshes, about a fifth of them); scipy when installed. `huggingface_hub` only for `scripts/atlas/hf_atlas.py` |
| Runs on | Any CPU, but the whole bucket is large: 908 meshes, 69.4 GB of x, y and z files (listed 24 Oct 2026), 50.6 GB of them PHerc. Paris 4's. Per mesh on a 4-core cloud container (24 Oct 2026, download included): 1.2 to 1.5 s at 9.362 um, 7.6 to 8.4 s at 2.4 um, 23.5 s at 1.129 um. The largest mesh (about 116 million nodes) needs about 3 GB of memory, so the daily build runs as a Hugging Face Job on `cpu-upgrade` (8 vCPU, 32 GB) |
| Network | `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (metadata.json, ListObjectsV2 listings, each mesh's four files); `show` reads the published `atlas.jsonl` from `huggingface.co` unless `--atlas` names a file |
| Writes | `build`: OUT/`atlas.jsonl`, `atlas.csv`, `summary.json`, `README.md` and, with `--lens`, `lens/*.slg.gz`; each mesh is fetched into a temporary folder that is deleted after it is measured. `show`: nothing. `hf_atlas.py job`: the public dataset |
| License | Code Apache-2.0; the dataset's numbers and preview grids CC BY-NC 4.0, as the meshes they come from (Vesuvius Challenge open data, CC BY-NC 4.0) |
| Go-ahead | Not needed for `build` and `show` (public data, local files). The dataset is public, published after the leak check (AGENTS.md rule 8; Chase asked for it on 24 Oct 2026) |
| Released | Public `main` from the change that adds it (24 Oct 2026) |
| Checked | 2026-10-24 against commit `c610c7a` plus this change |

## What it does

Anyone can open one segment with `kit tifxyz`, but nobody could compare them: which published segments are large, which have holes or folds, which grids are close to isometric, and how that differs between scrolls and volumes. The atlas answers that in one table.

`build` reads `metadata.json`, lists `SCROLL/segments/` for every scroll, and finds every folder under each segment's `mesh/` (up to three levels down) that holds `x.tif`, `y.tif` and `z.tif`. Each such folder is one row: the segment mapped to one volume (`SEGMENT-on-VOLUME-N.NNNum.tifxyz`), or an intermediate mesh the publisher kept (`kind` is then the subfolder's name, such as `intermediate`). For each it fetches the four files, measures, writes the row, and deletes the copy. Rows carry the prize lists their scroll is on, from kit's dated snapshot.

The numbers are exactly those of `kit tifxyz info`, `stretch` and `check` with default settings; a test compares them. Meshes over 12 million nodes are measured in bands of 1,024 rows (each cell and edge in exactly one band, flags read with one row of each neighbor), which gives the same counts as the whole grid; their percentiles come from every k-th value, k chosen so at most 2 million values are kept.

`--previous` makes a refresh cheap: a mesh is measured again only when the ETag or size of one of its three files changed, or its row has an error, or its Lens preview is missing.

`--lens` also writes, for scrolls on no prize list, a small preview grid per mesh that the Segment Lens viewer reads. Scrolls on a prize list get numbers only, never a preview (the public media rule, [docs/media/README.md](../media/README.md)).

The numbers describe the grid, not the papyrus: a clean mesh can still jump from one sheet to the next, and nothing here looks at the CT or judges ink. None of it is an official villa or prize check.

## When to use it

- To pick segments to work on or compare: the largest, the cleanest, the most isometric, per scroll.
- To check a newly published segment against the others on its scroll.
- To cite a segment's area or defect counts with a fixed method and a dated source.

Do not use it:

- As a sheet-switch check: it does not detect a trace that jumps between wraps.
- For a segment that is not on the bucket: run `kit tifxyz` on it directly.

## Quick start

```bash
python -m kit atlas show PHerc0139 --top 5
python -m kit atlas show --sort holes_mm2 --top 10
python -m kit atlas build work/atlas --scroll PHerc0139 --limit 8      # a small local build
```

On 24 Oct 2026 a local `build --scroll PHerc0139 --limit 8 --lens` measured 6 of 8 rows in 29 s; the other 2 were intermediate meshes compressed with LZW, which need `imagecodecs` (`pip install imagecodecs`), and their rows say so in `error`. The first row, w025 mapped to the 9.362 um volume, read 35.43 cm2, 82.65 % filled, 99.67 % of edges within 10 % of the step, 18 hole nodes (0.63 mm2), 45 fold nodes (1.58 mm2) and 76 stretched nodes (2.66 mm2). On w035's 2.399 um mesh the atlas gives the same numbers as `kit tifxyz` (22.066 cm2, 43 stretched nodes, no holes or folds), measured whole or in bands of 100 rows.

## Checks and controls

- **Same numbers as kit tifxyz.** A test compares area, holes, folds and stretched nodes with `kit tifxyz` on a sheet with planted defects.
- **Bands change nothing.** A test measures one grid whole and in bands of 7 rows and requires every number and mask to match; the same test shows that bands without the overlap row would lose cells, so the comparison can fail.
- **Planted defects are counted.** A planted hole of 30 nodes reads 30; a shifted patch reads stretched; the same sheet without them reads clean.
- **Previews only where allowed.** A test builds a fake bucket with one scroll on no prize list and one on a list: only the first gets a Lens file. Another reads kit's snapshot and requires PHerc1447 and PHerc. Paris 4 to be on a list and PHerc0139 not.
- **Refresh measures only what changed.** A test rebuilds with nothing changed (nothing measured), with one ETag changed (that mesh only), and with a preview file deleted (that mesh only).

Claim label: Sourced fact, for the measurements of public meshes; Interpretation, for any reading of them.

## Commands and options

### `python -m kit atlas build`

```
usage: python -m kit atlas build [-h] [--scroll SCROLL] [--previous PREVIOUS]
                                 [--workers WORKERS] [--lens] [--limit LIMIT]
                                 [--workdir WORKDIR]
                                 out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | folder for atlas.jsonl, atlas.csv, summary.json and lens/ |
| `--scroll SCROLL` | none |  only this scroll (repeat for more) |
| `--previous PREVIOUS` | none | an earlier atlas.jsonl (path or URL): unchanged meshes are not measured again |
| `--workers WORKERS` | none | meshes measured at once; none means the CPUs, at most 4; 1 runs them in this process |
| `--lens` | off | also write Segment Lens preview grids (scrolls on no prize list) |
| `--limit LIMIT` | none | only the first N meshes (for a test) |
| `--workdir WORKDIR` | none | where each mesh is fetched while it is measured; none means the system temp folder |

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_MAX_TIFF_ELEMENTS` | `1000000000` inside `build` | largest TIFF read, in elements (kit's usual limit is 200 million) |

### `python -m kit atlas show`

```
usage: python -m kit atlas show [-h] [--atlas ATLAS]
                                [--sort {area_cm2,holes_mm2,folds_mm2,stretched_mm2,within_10pct,median_abs_log,id}]
                                [--top TOP] [--all-kinds] [--json]
                                [scroll]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `scroll` | none | a scroll id, such as PHerc0139; none means all |
| `--atlas ATLAS` | `https://huggingface.co/datasets/SharpMeow/vesuvius-segment-atlas/resolve/main/atlas.jsonl` | atlas.jsonl path or URL |
| `--sort {area_cm2,holes_mm2,folds_mm2,stretched_mm2,within_10pct,median_abs_log,id}` | `area_cm2` | column to sort by, largest first (`id` A to Z) |
| `--top TOP` | none | only the first N rows; none means all |
| `--all-kinds` | off | include intermediate meshes, not only top-level ones |
| `--json` | off | print the rows as JSON |

### `python scripts/atlas/hf_atlas.py`

`job` runs inside the Hugging Face Job: it downloads the published dataset (previews included), runs `build --previous ... --lens` with 6 workers, removes previews no row names, and uploads the folder. `run` starts that Job once on `cpu-upgrade` (`--ref` is the branch of this repository it clones, default `main`; `--timeout`, default 3 h); `schedule` creates or replaces the daily scheduled Job (`--cron`, default `17 6 * * *`, 06:17 UTC); `status` lists the scheduled Job and recent Jobs. Each needs `HF_TOKEN` with write access to the dataset and Jobs.

| Option | Default | Meaning |
| --- | --- | --- |
| `--out` | `/tmp/atlas` | `job`: the folder the dataset is downloaded into and built in |
| `--workers` | `6` | meshes measured at once inside the Job |
| `--ref` | `main` | `run`, `schedule`: branch or tag of this repository the Job runs |
| `--timeout` | `3h` | `run`, `schedule`: the Job's time limit, which caps its cost |
| `--flavor` | `cpu-upgrade` | `run`, `schedule`: the Hugging Face hardware |
| `--cron` | `17 6 * * *` | `schedule`: when the daily Job runs (UTC) |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `list_keys(prefix, get=...)` | (folders, [{"key", "size", "etag", "modified"}]) | `OSError` | One ListObjectsV2 listing, all pages |
| `prize_lists()` | {normalized scroll or volume id: [prize ids]} | `VerifyError` without a snapshot | From the newest `kit/data/prizes-*.json` |
| `norm_scroll(name)` | str | nothing | `PHerc. 139` and `pherc0139` to `PHERC0139` |
| `lists_for(scroll, volume, table)` | [prize ids] | nothing | Matches with and without a part letter or suffix |
| `survey(scrolls=None, get=..., workers=16)` | [row] sorted by id | `VerifyError` for an unknown scroll; `OSError` | Rows without numbers |
| `measure(seg, band_rows=BAND_ROWS, band_nodes=BAND_NODES)` | (dict of numbers, {"holes", "folds", "stretched": mask}) | nothing | Whole grid, or bands for large meshes |
| `masks(seg, band_rows=BAND_ROWS)` | {"holes", "folds", "stretched": (H, W) bool} | nothing | `kit tifxyz check`'s masks, band by band |
| `lens_grid(seg, flags_masks, side=LENS_SIDE)` | gzip'd bytes | nothing | The Lens file format below |
| `read_lens(blob)` | (h, w, k, lo, hi, xyz, flags) | `VerifyError` on a bad magic | Missing nodes come back NaN |
| `lens_name(row)` | file name | nothing | sha256 of the row id, 16 hex digits, `.slg.gz` |
| `load32(src, cache, voxel_um=None)` | a `kit.tifxyz` Segment with float32 positions | `VerifyError` | Half the memory of `tifxyz.load` |
| `measure_row(row, lens_dir=None, workdir=None)` | the row with its numbers, or with `error` | nothing | Fetch, measure, delete |
| `read_atlas(src, get=...)` | [row] | `OSError`, `ValueError` | Path or URL |
| `build(out_dir, scrolls=None, previous=None, workers=None, lens=False, limit=None, get=..., progress=print, measure_fn=measure_row, workdir=None)` | the summary dict | as `survey` | Prints `PROGRESS i/N` lines |
| `write(out, rows)` | the summary dict | `OSError` | The four files |
| `card(summary)` | the dataset card text | nothing | |
| `summarize(rows)` | dict | nothing | Per scroll: segments, meshes, measured, errors, clean, area |
| `show(rows, scroll=None, sort="area_cm2", top=None, kind="mesh")` | [row] | nothing | |
| `format_show(rows, total)` | the printed text | nothing | |
| `build_parser(p)`, `cmd_atlas(args)`, `main(argv=None)` | parser, exit code | nothing | |

Constants: `DATASET`, `ATLAS_URL`, `SCHEMA` (`segment-atlas/1`), `BAND_ROWS` (1,024), `BAND_NODES` (12 million), `SAMPLE_CAP` (2 million), `LENS_SIDE` (256), `LENS_MAGIC`, `TIFF_LIMIT`, `COLUMNS`, `SORTS`.

## Inputs

The open-data bucket's `metadata.json` and its `SCROLL/segments/SEGMENT/mesh/` folders. A mesh folder is any folder up to three levels under `mesh/` that holds `x.tif`, `y.tif` and `z.tif` (see [tifxyz](tifxyz.md) for the format). The voxel size comes from the folder name, else from the named volume's `pixel_size_um` in `metadata.json`, else from the scroll's only volume; `voxel_um_from` says which.

## Outputs

`atlas.jsonl` and `atlas.csv` hold one row per mesh with these columns (CSV joins `prize_lists` with `;`):

| Field | Meaning |
| --- | --- |
| `id`, `scroll`, `segment`, `mesh`, `kind`, `url` | where the mesh is; `kind` is `mesh` or the subfolder name |
| `volume`, `voxel_um`, `voxel_um_from` | the scan volume and voxel size, and where the size came from |
| `prize_lists` | prize ids from kit's snapshot (empty: on no list) |
| `grid_h`, `grid_w`, `nodes_filled`, `filled_share` | grid size and filled nodes |
| `area_cm2`, `meta_area_ratio` | area (empty without a voxel size); ours over `meta.json`'s `area_vx2` |
| `edge_p5`, `edge_p50`, `edge_p95`, `within_10pct`, `within_25pct`, `median_abs_log` | edge length over the promised step |
| `cell_area_p50`, `angle_p5`, `angle_p50`, `angle_p95` | cell area over the promised area; grid angle in degrees |
| `holes_nodes`, `holes_mm2`, `folds_nodes`, `folds_mm2`, `stretched_nodes`, `stretched_mm2`, `clean` | `kit tifxyz check`'s flags |
| `z_min`, `z_max` | height range in voxels |
| `bytes`, `banded`, `seconds`, `error`, `measured_at` | the x, y and z file sizes, whether bands were used, time, any error, when |
| `lens` | the preview file in `lens/`, or empty |
| `fingerprint`, `last_modified` | from the three files' ETags and sizes; the newest modification time |

`summary.json`: `schema`, `built`, `kit_commit`, `bucket`, `meshes`, `segments`, `errors`, and `scrolls` (per scroll: `segments`, `meshes`, `measured`, `errors`, `clean`, `area_cm2` counting each segment once from its finest-voxel top-level mesh, `prize_lists`). `README.md` is the dataset card.

### Lens files

`lens/NAME.slg.gz` is gzip over: the 4 bytes `SLG1`; uint16 `h`, `w`, `k` (little-endian); six float32 `lo` x, y, z and `hi` x, y, z; then three planes of h x w uint16 (x, y and z of every k-th node, `lo + q / 65534 * (hi - lo)`, 65535 for a missing node); then h x w uint8 flags, the OR over the k x k block each kept node stands for (1 hole, 2 fold, 4 stretched). `k` makes the longest side at most 256. A file is about 150 to 250 KB.

| Exit code | Meaning |
| --- | --- |
| `0` | Done |
| `1` | `build` found no meshes |
| `2` | Bad input, an unknown scroll, or the bucket or the atlas could not be read |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit atlas: SCROLL is not in the open-data metadata.json; close: ...` | A scroll id the bucket does not have | Use an id from `python -m kit find` |
| `kit atlas: no prize snapshot (kit/data/prizes-*.json): the atlas needs it to mark prize-eligible scrolls and to keep Segment Lens previews to the others` | The snapshot is missing | Restore `kit/data/` from the repository |
| `kit atlas could not read the bucket or the atlas: ERROR` | No network, or a bad `--atlas` path | Check the network or the path |
| A row with `error` `VerifyError: cannot read the tifxyz folder URL: <COMPRESSION.LZW: 5> requires the 'imagecodecs' package` | An LZW-compressed mesh | `pip install imagecodecs` and build again with `--previous` |
| A row with `error` `ValueError: TIFF declares N elements, over M; refused ...` | A mesh above `KIT_MAX_TIFF_ELEMENTS` | Raise it if the machine has the memory |
| A row with `error` `MemoryError: ...` or `BrokenProcessPool: ...` | Too many large meshes measured at once | Fewer `--workers`, or more memory |
| `kit atlas: not a Segment Lens grid (bad magic)` (from `read_lens`) | The bytes are not a Lens file | Read a `lens/*.slg.gz` file from the dataset |
| A row with `error` `VerifyError: URL: x.tif, y.tif and z.tif must be 2D grids of one shape` | A damaged or mixed mesh folder on the bucket | Nothing to do here; the row stays unmeasured until the folder changes |
| `previous atlas not read (ERROR); measuring everything` | `--previous` could not be read | Check the path; the build still runs |

## How it works

1. **List.** `metadata.json`, then ListObjectsV2 with a `/` delimiter for each scroll's `segments/` and each segment's `mesh/` tree, 16 listings at a time.
2. **Fingerprint.** sha256 over the three files' ETags and sizes, first 16 hex digits.
3. **Measure.** Each mesh is fetched into a temporary folder, read as float32, measured with `kit tifxyz`'s cell, edge and check functions (in bands for large ones), and deleted. Largest meshes first, in a process pool, so one big mesh does not finish last.
4. **Previews.** Every k-th node, quantized to 16 bits inside the bounding box, with flags pooled over each k x k block.
5. **Write.** JSON lines, CSV, a summary and the card.
6. **Daily.** `scripts/atlas/hf_atlas.py` clones this repository's `main` inside a `python:3.12` Job, installs numpy, tifffile, imagecodecs, scipy and huggingface_hub, downloads the dataset, builds with `--previous`, and uploads.

## Cost and time

A local build of one small scroll takes minutes. The whole bucket is a Hugging Face Job on `cpu-upgrade` at 0.03 USD an hour (price read 23 Oct 2026); the first build is the long one, and a daily refresh measures only new or changed meshes.

## For agents

- **Command:** `python -m kit atlas show SCROLL --json` (published numbers); `python -m kit atlas build OUT --scroll SCROLL --previous URL` (fresh ones).
- **Parse:** each row's `area_cm2`, `filled_share`, `within_10pct`, `holes_mm2`, `folds_mm2`, `stretched_mm2`, `clean`, `error`.
- **Rerun:** Safe; `--previous` skips unchanged meshes.
- **Success:** exit 0 and rows without `error`.
- **Not a pass:** `clean` does not mean the segment follows one sheet; a row with `error` has no numbers.
- **Go-ahead:** Nothing to run locally. A new public dataset or a changed card needs the leak check.
- **Never:** add previews for a scroll on a prize list; describe private findings in the card.

## Tests

`python -m unittest tests.test_atlas -v`: a flat isometric sheet (clean, exact area), planted holes and stretch, bands against the whole grid, the same numbers as `kit tifxyz`, Lens round trip (positions within one quantum, missing nodes, pooled flags, bad magic), prize lists with and without part letters and from the snapshot, the survey of a fake bucket (voxel sizes from the name and from the only volume, lists, bytes), refresh logic (nothing changed, one ETag changed, a preview deleted), and `show` sorting. No network.

## History

- 2026-10-24: added `build`, `show`, the Lens preview format and the daily Hugging Face Job (on top of `c610c7a`).

## Related

- [tifxyz](tifxyz.md): the same checks on one segment.
- [Segments without VC3D](../segments-without-vc3d.md): the how-to for one segment.
