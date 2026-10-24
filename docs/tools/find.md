# find: everything public for one scroll, and how to credit it

`python -m kit find SCROLL` lists a scroll's volumes, segments, predictions, center lines and Hugging Face matches in one screen; `python -m kit cite SCROLL` prints the credit and licence lines to paste under a figure.

| Field | Value |
| --- | --- |
| Id | `find` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Data and downloads |
| Run | `python -m kit find`, `python -m kit cite`, `python -m kit.find`, `from kit import find` |
| Code | `kit/find.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_qol_tools.py` |
| Needs | Python 3.10 or newer, standard library only |
| Runs on | Any machine with HTTPS. `find PHerc0139` took 2.0 s and `cite PHerc0139 --centerline` 0.7 s (measured 2026-10-23, cloud container) |
| Network | Reads, anonymously over HTTPS: the open-data bucket's `metadata.json` and listings (`vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`), the Hugging Face Hub search API (`huggingface.co/api/datasets`, `models`, `spaces`), and the center lines dataset's `index.json`. Posts nothing |
| Writes | Nothing |
| Go-ahead | Not needed |
| Released | Public `main` from the change that adds it (23 Oct 2026) |
| Checked | 2026-10-23 against commit `3376687` |

## What it does

What exists for a scroll is spread over the open-data bucket (volumes, segments, `representations/predictions/`), the data browser, Hugging Face (community datasets and Spaces) and our center lines dataset. People on the Discord ask where a scroll's surface predictions or umbilicus are, and which volume a segment was traced on. `find` puts it on one screen:

- every volume of the scroll: id, voxel size, shape (z y x), licence, whether it has been superseded, and which open prizes name it (from kit's dated prize snapshot, [prizes](prizes.md));
- how many segments it has, per original volume;
- every folder under `SCROLL/representations/` in the bucket: surface, lasagna and fiber predictions, umbilicus files;
- the center lines in `SharpMeow/vesuvius-center-lines` for that scroll;
- public Hugging Face datasets, models and Spaces whose names or cards match the scroll's id.

`cite` prints one credit line per volume, as `metadata.json` states its licence, and with `--centerline` one per center line, as the dataset's index states it.

A Hub match is a name match, not a check that the data is what it says; read its card. Prize eligibility comes from the snapshot's date, not the live page; `python -m kit prizes` shows that date.

## When to use it

- Before starting on a scroll: what volumes, segments and predictions already exist, and on which volume.
- To find a scroll's published umbilicus, surface prediction or lasagna run without browsing the bucket.
- To write the credit line for a figure, a README or a Space from the bucket's own licence field.

Do not use it:

- To download anything: use [fetch](fetch.md) for a bucket folder, [centerline](centerline.md) for a center line.
- For every volume of every scroll at once: `python -m kit run catalog` ([batch](batch.md)).
- As a check of current prize rules: read https://scrollprize.org/prizes.

## Quick start

```bash
python -m kit find PHerc0175A
python -m kit cite PHerc0175A --centerline
```

On 23 Oct 2026 `find PHerc0175A` printed:

```
PHerc0175A
  volumes (1)
    20250521115057-8.640um-1.2m-116keV-masked.zarr  8.64 um  12748x9363x9363 (z y x)  CC BY-NC 4.0  prize: First Letters
  segments: 0 (none)
  bucket representations
    predictions/surfaces: 2
      20250521115057-surface-20260413222639-surface-m7-L0-th0.2.normal-grids
      20250521115057-surface-20260413222639-surface-m7-L0-th0.2.zarr
  center lines in SharpMeow/vesuvius-center-lines
    finder (model, 146 points)  lines/PHerc0175A/PHerc0175A_20250521115057_finder_umbilicus.json
  Hugging Face matches (1; a name match, read each card first)
    dataset https://huggingface.co/datasets/SharpMeow/pherc0175a-lasagna
  bucket: https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0175A/   browser: https://scrollprize.org/data_browser/
```

`find PHerc0139` listed 10 volumes (one marked `superseded by 20260930100252`), 39 segments all on `20260102150214`, two fiber runs, one lasagna run, four surface predictions and one umbilicus file. `cite PHerc0139` printed lines such as:

```
PHerc0139 volume 20250728140407-9.362um-1.2m-113keV-masked.zarr: Vesuvius Challenge open data, CC BY-NC 4.0 (https://creativecommons.org/licenses/by-nc/4.0/)
  source: https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr/
```

It worked when the exit code is 0 and the volumes list is not empty.

## Checks and controls

- **The listing is the bucket's own.** Volumes, shapes and licences are read from `metadata.json`; folders from the bucket's ListObjectsV2 listing, all pages. Nothing is inferred from names except the volume id prefix of a representation folder.
- **An unknown scroll fails loudly.** A scroll not in `metadata.json` exits 2 with the close names (`PHerc139` suggests `PHerc0139`), tested with a fake `metadata.json`.
- **Private Hub repos are skipped.** Only rows the search API marks public are listed.

Claim label: Sourced fact (each line is read from the bucket, the Hub or the dataset index on the day it runs).

## Commands and options

### `python -m kit find`

```
usage: python -m kit find [-h] [--no-hub] [--json] scroll
```

| Option | Default | Meaning |
| --- | --- | --- |
| `scroll` | required | scroll id as in the bucket, for example PHerc0139 or PHerc0175A (matched without regard to case) |
| `--no-hub` | off | skip the Hugging Face search |
| `--json` | off | print the result as JSON (fields under Outputs) |

### `python -m kit cite`

```
usage: python -m kit cite [-h] [--volume VOLUME] [--centerline] [--json]
                          scroll
```

| Option | Default | Meaning |
| --- | --- | --- |
| `scroll` | required | scroll id as in the bucket, for example PHerc0139 or PHerc0175A |
| `--volume VOLUME` | none | only this volume (short or long id) |
| `--centerline` | off | also credit the scroll's center lines |
| `--json` | off | print the lines as JSON |

`python -m kit.find SCROLL` runs `find`.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `http_get(url, timeout=60)` | bytes | `OSError` | Anonymous GET; un-gzips a gzip body (`metadata.json` is served gzipped) |
| `get_json(url, get=http_get)` | parsed JSON | `OSError`, `ValueError` | |
| `check_id(scroll)` | the id | `VerifyError` | Letters, digits, `_` and `-`, 2 to 41 characters |
| `sample(meta, scroll)` | (id as in the bucket, sample dict) | `VerifyError` with close names | Case-insensitive |
| `list_prefix(prefix, get=http_get)` | (sub-folders, [(key, size)]) | `OSError` | One level, all pages |
| `representations(scroll, get=http_get)` | {kind: [names]} | `OSError` | `predictions/KIND` for each prediction kind, plus each other folder under `representations/` |
| `hub_search(scroll, get=http_get)` | [{"type", "id", "url"}] | Nothing | A failed search is skipped |
| `centerlines(scroll, get=http_get)` | rows of the center lines index for the scroll | Nothing | [] when the Hub is down |
| `eligible_volumes()` | {volume id: [prize names]} | Nothing | From kit's prize snapshot |
| `find(scroll, get=http_get, hub=True)` | dict (Outputs) | `VerifyError`, `OSError`, `ValueError` | |
| `cite(scroll, get=http_get, with_centerlines=False, volume=None)` | {"scroll", "lines": [{"what", "credit", "licence_url", "source"}]} | `VerifyError`, `OSError`, `ValueError` | |
| `format_find(r)`, `format_cite(r)` | the printed text | Nothing | |
| `build_parser(p, action)` | the parser | Nothing | `action` is `find` or `cite` |
| `cmd_find(args)`, `cmd_cite(args)` | exit code | Nothing | |
| `main(argv=None)` | exit code | Nothing | `python -m kit.find` |

Constants: `BUCKET`, `METADATA`, `HUB`, `CENTERLINES` (`SharpMeow/vesuvius-center-lines`), `CENTERLINES_INDEX`, `DATA_CREDIT` (`Vesuvius Challenge open data`).

## Inputs

A scroll id as the bucket spells it (`PHerc0139`, `PHerc0175A`, `PHerc0343P`). Everything else is read from the network.

## Outputs

`find --json`: `scroll`; `volumes` (each `id`, `long_id`, `voxel_um`, `shape_zyx`, `licence`, `superseded_by`, `prizes`, `url`); `segments` (`count`, `by_volume`, `url`); `representations` ({kind: [names]}); `centerlines` (index rows); `hub` (list, or null with `--no-hub`); `browse`.

`cite --json`: `scroll` and `lines`, each `what`, `credit`, `licence_url`, `source`.

| Exit code | Meaning |
| --- | --- |
| `0` | Listed |
| `2` | Unknown scroll or volume, a bad id, or the bucket could not be read |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit find: not a scroll id: 'X' (for example PHerc0139)` | Spaces, slashes or other characters in the id | Use the id as the bucket spells it |
| `kit find: X is not in the open-data metadata.json; close: A, B` | A typo, a missing leading zero, or a scroll not yet released | Use a close name, or check the data browser |
| `kit cite: SCROLL has no volume V` | `--volume` names no volume of that scroll | Run `find SCROLL` for the volume ids |
| `kit cite: ...` with another message | As for `find` | As above |
| `kit find could not read the bucket's metadata or listing: ERROR` | No network, a proxy refusal or a timeout | Check the network, then rerun |
| `kit cite could not read the bucket's metadata: ERROR` | As above | As above |
| `Hugging Face matches (0; ...)` when you expected some | The Hub search matches names and cards; a repo that does not mention the id is not found, and a Hub outage gives 0 silently | Search the Hub by hand |
| `licence not stated in metadata.json` in a `cite` line | The volume has no `license` entry in `metadata.json` | Check the data's terms on scrollprize.org before using it |

## How it works

1. `metadata.json` is fetched (gzip) and the scroll's sample found without regard to case.
2. Volumes and their properties come from the sample; segments are counted by `original_volume_id`.
3. `SCROLL/representations/` is listed with the bucket's ListObjectsV2 API (`delimiter=/`, following continuation tokens), then each prediction kind's folder.
4. The center lines index and the Hub search API (`?search=SCROLL&limit=50` for datasets, models and Spaces) are read; failures there are skipped, so the bucket part still prints.
5. Prize names come from scanning kit's prize snapshot for 14-digit volume ids.

## Cost and time

Seconds and a few hundred kilobytes of listings. Nothing to rent.

## For agents

- **Command:** `python -m kit find SCROLL --json` and `python -m kit cite SCROLL --json`.
- **Parse:** `volumes[].long_id`, `volumes[].prizes`, `representations`, `centerlines[].file`; `lines[].credit`.
- **Rerun:** Safe; read-only.
- **Success:** exit 0.
- **Not a pass:** an empty `hub` list does not mean nothing exists on the Hub; `prizes` reflects the snapshot date, not today's rules.
- **Go-ahead:** Nothing.
- **Never:** treat a Hub match as verified data.

## Tests

`python -m unittest tests.test_qol_tools.TestFind -v`: with a fake bucket and Hub, `find` lists volumes, segments by volume, representations, center lines and public Hub repos (a private one is skipped); unknown and malformed ids raise with close names; `cite` prints one line per volume, filters by `--volume`, refuses an unknown volume, and adds center lines. They do not touch the network; the outputs above were run by hand.

## History

- 2026-10-23: added `find` and `cite` (`3376687`).

## Related

- [centerline](centerline.md): download a center line `find` lists.
- [fetch](fetch.md): download a bucket folder.
- [tifxyz](tifxyz.md): look at a segment's mesh.
- [prizes](prizes.md): the dated prize snapshot behind the `prize:` labels.
