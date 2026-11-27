# atlascomm: Segment Atlas numbers for ATLAS-15k's community surface patches

Reads Qual's ATLAS-15k recto surface patches shard by shard and writes one Segment Atlas row per patch: the dataset's metadata for every patch and, for the scrolls you name, the same area, isometry, hole, fold and stretch numbers `kit atlas` gives published meshes.

| Field | Value |
| --- | --- |
| Id | `atlascomm` |
| Status | Current |
| Kind | kit command |
| Area | Surfaces and tracing |
| Run | `python -m kit atlascomm` |
| Code | `kit/atlascomm.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_atlascomm.py` |
| Needs | Python 3.10 or later, numpy, pyarrow and huggingface_hub (the last two only for `build`) |
| Runs on | Any CPU. On 27 Nov 2026 a 4-core cloud container read all 18 shards (8.6 GB) and measured 3,412 patches in 253 s; one shard on disk at a time |
| Network | `huggingface.co` (the dataset's 18 parquet shards, 8.6 GB in all, one at a time) |
| Writes | OUT/`atlas15k.csv`, OUT/`atlas15k.jsonl`, OUT/`atlas15k-scrolls.json`; each shard goes to a temporary folder (or `--workdir`) that is deleted once read |
| Go-ahead | Not needed for `build` (public data, local files). Publishing the table to the Segment Atlas dataset is an upload and needs Chase's yes on its content (AGENTS.md rule 8) |
| Released | Public `main` once merged |
| Checked | 2026-11-27 against commit `5f7edb7` |

## What it does

[ATLAS-15k](https://huggingface.co/datasets/Qualzz20/ATLAS-15k) (Qual, 27 Nov 2026, CC BY-NC 4.0) is 14,678 recto surface patches traced in the level 0 scans of 28 open-data scrolls. Each patch is a grid of x, y, z positions, nodes 2 voxels apart, -1 where empty. The Segment Atlas measures every published bucket mesh; this tool gives the community patches the same numbers so they can be compared with the published segments.

`build` downloads one shard at a time, reads its rows in batches of 64, and writes a row per patch with the dataset's own metadata (scan, voxel size, grid size, centre, bounding box, area). For each scroll named by `--measure` it turns the grid into a `kit.tifxyz` Segment (scale 0.5, so the promised step is 2 voxels) and runs `kit.atlas.measure`. Other rows carry the metadata only and `measured` false.

It copies no node grid and no CT. It does not judge whether a patch lies on one sheet.

## When to use it

- To compare community patches with published segments by area and grid quality.
- To pick clean patches for a training set (filter on `clean`, `within_10pct`).

Do not use it:
- for published bucket meshes (use [`kit atlas`](atlas.md));
- to view a patch (use the dataset card's snippet or a viewer).

## Quick start

```bash
python -m kit atlascomm build work/ac --shards 0 --limit 30 --measure PHerc0009B
```

On 27 Nov 2026 this printed `PROGRESS shard 1/18: 30 rows, 9 s` and `30 rows (30 measured)`. The first row, PHerc0009B-x03903-y03989-z04182, measured 0.131 cm2 against the dataset's 0.1309, edge p50 1.001, 92.3 % of edges within 10 % of the step, no holes.

## Checks and controls

- **Area matches the dataset's own.** On the first 30 rows of shard 0 the measured area equals the card's `area_cm2` to the third decimal (0.131 vs 0.1309 on the first row).
- **A planted flat sheet is exact.** A test builds a flat grid 2 voxels apart: edge p50 1.0, every edge within 10 %, area 19 x 29 cells of 4 voxels squared.
- **A hole is caught.** The same sheet with a 3 x 3 hole gives holes above 0 and `clean` false, so the check can fail.
- **Caveat.** The fold and stretch flags of `kit tifxyz` were set for meshes with steps of about 20 voxels. At a 2 voxel step, voxel-level noise raises them (PHerc0009B patches show about 1 to 8 % fold nodes), so compare these flags between patches, not with published meshes.

Measurement only: the numbers describe the patch grids, not whether they follow a sheet. No transfer claim across scrolls is made.

Claim label: Sourced fact, for the measurements of public patches; Interpretation, for any reading of them.

## Commands and options

### `python -m kit atlascomm build`

```
usage: python -m kit atlascomm build [-h] [--measure SCROLL] [--limit LIMIT]
                                     [--shards SHARDS [SHARDS ...]]
                                     [--revision REVISION] [--workdir WORKDIR]
                                     out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | output folder |
| `--measure SCROLL` | none | measure the patch grids of this scroll (repeatable); others get metadata only |
| `--limit LIMIT` | none | stop after N rows (a test) |
| `--shards SHARDS ...` | none | only these shard numbers (0 to 17) |
| `--revision REVISION` | `ac4b982a1dc105a861e090ecb60cbff4578b5187` | dataset revision (default: the one read on 27 Nov 2026) |
| `--workdir WORKDIR` | none | where each shard is downloaded while it is read |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `AtlasCommError()` | the error class | raised by the functions below |  |
| `volume_of(scan)` | the volume name | nothing | The volume name in a scan URL (.../volumes/NAME.zarr/0), or the URL when it has none. |
| `segment(x, y, z, voxel_um, source='')` | a `kit.tifxyz.Segment` | AtlasCommError when the grids are not 2D | A kit.tifxyz Segment from one patch's x, y, z grids (rows of lists, -1 where no node). |
| `row_of(rec, measure=False)` | one row dict | nothing (a patch that fails gets `error`) | One table row from one dataset record: its metadata, and the atlas numbers when measure is true. |
| `write(out_dir, rows)` | nothing | OSError | writes the CSV and JSONL |
| `summary(rows)` | one dict per scroll | nothing |  |
| `build(out_dir, measure=(), limit=None, shards=None, revision=REVISION, workdir=None)` | the rows | OSError, pyarrow errors | the build |
| `build_parser(p)` | the parser | nothing |  |
| `cmd_atlascomm(args)` | exit code | nothing |  |
| `main(argv=None)` | exit code | nothing |  |

## Inputs

The dataset's parquet rows: `id`, `scroll`, `scan`, `voxel_um`, `size_vx`, `centre_xyz`, `box_min_xyz`, `box_max_xyz`, `area_cm2` and `x`, `y`, `z` float32 grids in level 0 voxels, `[z, y, x]` scans.

## Outputs

Columns, in order: `id`, `scroll`, `volume`, `scan`, `voxel_um`, `size_x`, `size_y`, `centre_*`, `box_min_*`, `box_max_*` (voxels), `area_cm2` (the dataset's), `measured`, then for measured rows `grid_h`, `grid_w`, `nodes_filled`, `filled_share`, `area_cm2_measured`, `edge_p5/p50/p95`, `within_10pct`, `within_25pct`, `median_abs_log`, `angle_p5/p50/p95` (degrees), `holes_*`, `folds_*`, `stretched_*` (nodes and mm2), `clean`, `extent_*_mm`, and `error`. The meanings are those of [`kit atlas`](atlas.md). `atlas15k-scrolls.json` holds per scroll patches, area, measured and clean counts.

| Exit code | Meaning |
| --- | --- |
| `0` | the table was written |
| `1` | not used |
| `2` | an OSError (download or disk) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `...: x, y and z must be 2D grids of one shape` | A patch's grids are not 2D | The row gets `error`; report it to the dataset's author |
| `atlascomm:...` | The download or disk failed | Check the network and `--workdir` space (one shard is about 480 MB) |

## How it works

1. For each shard (`SHARDS` = 18), download it with `hf_hub_download` at `REVISION` into a temporary folder.
2. Read rows in batches of 64; build the metadata row; for `--measure` scrolls make a Segment with step `STEP_VX` = 2 voxels and run `kit.atlas.measure`.
3. Delete the shard; print `PROGRESS shard i/18`.
4. Write the CSV, JSONL and per-scroll summary.

## Cost and time

Any CPU. On 27 Nov 2026 a 4-core cloud container read all 18 shards (8.6 GB) and measured 3,412 patches in 253 s; one shard on disk at a time

## For agents

- **Command:** `python -m kit atlascomm build OUT --measure SCROLL ...`; read `OUT/atlas15k.jsonl`
- **Parse:** one JSON row per patch; `measured`, `error` and the number columns
- **Rerun:** safe; it overwrites the three output files
- **Success:** exit 0 and `N rows (M measured)` with M the patch count of the measured scrolls
- **Not a pass:** high fold or stretch counts at the 2 voxel step (see the caveat); a `measured` row is not a check that the patch is on one sheet
- **Go-ahead:** publishing the table needs Chase's yes
- **Never:** rehost the node grids; use the data commercially (CC BY-NC 4.0)

## Tests

`python -m unittest tests.test_atlascomm`: planted flat sheet, planted hole, metadata-only rows, CSV columns and summary. They do not download the dataset.

## History

- 2026-11-27: new. The ATLAS-15k patch table for the Segment Atlas.

## Related

- [atlas](atlas.md): the Segment Atlas whose numbers this reuses.
- [tifxyz](tifxyz.md): the mesh checks.
