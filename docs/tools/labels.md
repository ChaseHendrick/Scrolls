# labels: which published ink labels exist, and which public models saw them

`python -m kit labels SCROLL` lists every segment of a scroll that has published ink labels on the open-data bucket, with each label set's volume, date, shape and size, and what this repository's public records say about which ink models trained on it.

| Field | Value |
| --- | --- |
| Id | `labels` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Data and downloads |
| Run | `python -m kit labels`, `python -m kit.labels`, `from kit import labels` |
| Code | `kit/labels.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_labels.py` |
| Needs | Python 3.10 or newer, standard library only. Reads `docs/results.json` and `docs/STANDARDS.md` from this repository for the exposure records |
| Runs on | Any machine. PHerc0139 (39 segments, 8 labeled, 13 label sets, sizes included): 4.4 s; PHerc0841: 2.4 s; every scroll without sizes: 19.8 s (measured 2026-10-24, 4-core cloud container) |
| Network | `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` only: `metadata.json`, bucket listings (16 at a time) and each label array's small metadata files; 429, 5xx and dropped connections are asked again up to 5 times |
| Writes | Nothing (prints only) |
| Go-ahead | Not needed: it reads public data |
| Released | Public `main` from the change that adds it (24 Oct 2026) |
| Checked | 2026-10-24 against commit `cc03099` |

## What it does

The open-data bucket keeps human ink labels beside each labeled segment, under `SCROLL/segments/SEGMENT/ink-labels/<voxel size>um-volume-<VOLUME>/<date>/`: `inklabels.zarr` (the ink), `supervision.zarr` (where the labels may be trusted) and, for some segments, `validation.zarr` (the part set aside for validation). Nothing lists them in one place: finding which segments of a scroll have labels, on which volume, means walking the bucket folder by folder. On 24 Oct 2026, 28 of the bucket's 328 segments had them, across 7 scrolls.

`kit labels` walks the bucket for one scroll (or every scroll) and prints each labeled segment's label sets: the volume and voxel size they are drawn on, the date folder, each array's shape, data type, number of pyramid levels and stored bytes.

Beside each segment it prints the training exposure that this repository's public records give it: one word per model family from `held_out_by_reader` in [`docs/results.json`](../results.json), the first sentence of the cited reason in `held_out`, and the PHerc0139 w035 row of [STANDARDS.md section 5](../STANDARDS.md#5-data-splits-and-held-out-sets). Which records apply to which segments is fixed in the code (`SCOPES`), so PHerc0139's w045 record never lands on a w045 of another scroll. A segment with no record is printed as unknown, never as held out. The records cover the released readers named there (`ink_9um`, v8in, v8in-1447, d9v2, Reader v2, Hecate); the reasons and sources are in [the exposure log](../logs/2026-10-16-reader-exposure.md).

It lists published labels only. It does not download the arrays, measure label coverage, or judge any segment, and its exposure column is a lookup of written records, not a check of any checkpoint's training list.

## When to use it

- Before scoring an ink model on a segment: which label sets exist, on which volume, and whether the records say the model saw them.
- To pick a held-out test segment for a released reader: the segments whose records say "held out" for it.
- To find the bucket path of a label set for [`kit auc`](auc.md) or [`kit fetch`](fetch.md).

Do not use it:

- To list a scroll's volumes, meshes and predictions: use [`kit find`](find.md).
- To decide held-out status for a model the records do not name: read that model's own training list.
- For anything about target scrolls from private work: this reads public records only.

## Quick start

```bash
python -m kit labels PHerc0841
python -m kit labels                  # every scroll, one line each
```

On 24 Oct 2026 the first printed, for each of PHerc0841's three segments, lines such as:

```
PHerc0841: 3 of 3 segments carry published ink labels
  20260220213127-w00
    20260918  2.403 um volume 20260319124803: inklabels 16460x18560 117.3 KB, supervision 16460x18560 104.9 KB, validation 16460x18560 252.1 KB
    exposure  ink_9um held out, v8in held out, v8in-1447 held out, d9v2 held out, Reader v2 held out, Hecate not held out
    record    in the training data of none of ink_9um (...) (docs/results.json held_out.PHerc0841 and held_out_by_reader.PHerc0841)
```

and the second:

```
7 scrolls with published ink labels
  PHerc0009B       1 labeled segment, 1 label set, 0 with an exposure record
  PHerc0139        8 labeled segments, 13 label sets, 3 with an exposure record
  PHerc0500P2      1 labeled segment, 1 label set, 0 with an exposure record
  PHerc0814        1 labeled segment, 1 label set, 0 with an exposure record
  PHerc0841        3 labeled segments, 3 label sets, 3 with an exposure record
  PHerc1667        6 labeled segments, 6 label sets, 0 with an exposure record
  PHercParis4      8 labeled segments, 8 label sets, 0 with an exposure record
```

It worked when every labeled segment has at least one dated label set and each segment shows either an exposure record or "unknown".

## Checks and controls

- **Unknown stays unknown.** In `tests/test_labels.py` a labeled segment with no record prints "unknown", and the w045 record of PHerc0139 does not reach a segment named w045 on another scroll.
- **No record is dropped.** A `held_out` key the code does not place is listed as unmatched (tested with a planted key); a test on the repository's own `docs/results.json` fails when a new record has no scope, so a new record cannot be silently ignored.
- **Sizes add up.** On a fake bucket, an array's bytes and file count equal the sum of its keys; a listing that stops at its page limit is marked "at least".
- **Live check.** On 24 Oct 2026, PHerc0841 showed `held out` for the five readers and `not held out` for Hecate, as `held_out_by_reader` says; PHerc0139 w045 showed `held out` for v8in only.

Claim label: Sourced fact for the bucket's label sets (listed as found); the exposure column repeats this repository's records, whose own labels (Sourced fact, Community report, Interpretation) are in [the exposure log](../logs/2026-10-16-reader-exposure.md).

## Commands and options

### `python -m kit labels`

```
usage: python -m kit labels [-h] [--no-sizes] [--json] [scroll]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `scroll` | none | scroll id, for example PHerc0841 (leave out for every scroll) |
| `--no-sizes` | off | skip the stored sizes (one listing per label array) |
| `--json` | off | print the inventory as JSON (fields under Outputs) |

Every scroll at once is listed without sizes. `python -m kit.labels` takes the same options.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `http_get(url, tries=5, sleep=None)` | bytes | `OSError` after the last try | `kit.find.http_get` asked again on 429, 5xx or a dropped connection |
| `list_all(prefix, get=http_get, max_pages=MAX_PAGES)` | ([(key, size)], cut) | `OSError` | Every key under a prefix, paged; `cut` is True when the page limit stopped it |
| `array_info(prefix, get=http_get, sizes=True)` | dict: `shape`, `dtype`, `format`, `levels`, `bytes`, `files`, `bytes_at_least` | `OSError` | One label zarr (v2 or v3, OME multiscales or a plain array) |
| `segment_labels(prefix, get=http_get, sizes=True)` | list of label sets | `OSError` | `folder`, `volume`, `voxel_um`, `date`, `url`, `arrays` |
| `short_id(segment)` | str or None | nothing | The w-number of a segment folder name |
| `standards_rows(path=STANDARDS)` | {label: text} | nothing | The table of STANDARDS.md section 5 |
| `records(results=RESULTS, standards=STANDARDS)` | (records, unmatched keys) | nothing | Each record: `key`, `scroll`, `segment`, `text`, `by_reader`, `source` |
| `exposure(scroll, segment, recs)` | the records for one segment | nothing | Segment records first, then scroll records |
| `inventory(scroll, get=http_get, sizes=True, recs=None, meta=None)` | dict (Outputs) | `VerifyError` for an unknown scroll, `OSError` | One scroll |
| `every_scroll(get=http_get, sizes=False)` | dict | `OSError` | Every scroll with labels |
| `format_inventory(r)`, `format_every(r)` | the printed text | nothing | |
| `build_parser(p)`, `cmd_labels(args)`, `main(argv=None)` | parser, exit code | nothing | |

Constants: `SCOPES`, `STANDARDS_ROWS`, `RESULTS`, `STANDARDS`, `EXPOSURE_LOG`, `WORKERS` (16), `MAX_PAGES` (20).

## Inputs

A scroll id as it appears in the bucket's `metadata.json` (case does not matter), or none. The exposure records are read from this checkout's `docs/results.json` and `docs/STANDARDS.md`; without them every segment is unknown.

## Outputs

`--json` for one scroll:

| Field | Type | Meaning |
| --- | --- | --- |
| `scroll` | str | the id as the bucket spells it |
| `segments`, `labeled` | int | segments on the bucket, and those with an `ink-labels` folder |
| `rows[].segment`, `rows[].short_id` | str, str or null | folder name and its w-number |
| `rows[].label_sets[]` | list | `folder`, `volume`, `voxel_um`, `date`, `url` (`s3://` of the dated folder), `arrays` (name: `shape`, `dtype`, `format`, `levels`, `bytes`, `files`, `bytes_at_least`) |
| `rows[].exposure` | list or str | each record's `key`, `by_reader` (family: "held out" or "not held out"), `summary`, `source`; or a string starting "unknown" |
| `records_unmatched` | list | `held_out` keys the code does not place |
| `exposure_log` | str | the log with the reasons |

Every scroll: `scrolls` (a list of the above), `records_unmatched`, `exposure_log`.

| Exit code | Meaning |
| --- | --- |
| `0` | Listed |
| `2` | Not a scroll id, a scroll not in `metadata.json`, or the bucket unreachable |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit labels: not a scroll id: 'X' (for example PHerc0139)` | Characters an id cannot have | Use the id as the bucket spells it |
| `kit labels: X is not in the open-data metadata.json; close: ...` | An unknown scroll | Use one of the close names, or `kit labels` for all |
| `kit labels could not read the open-data bucket: ERROR` | No network, or the bucket kept failing after 5 tries | Run it again later |
| `note: records not placed on a segment: KEY` | A new `held_out` record with no scope in `kit/labels.py` | Add its scope to `SCOPES` |

## How it works

1. Read `metadata.json` for the scroll's exact name, then list `SCROLL/segments/` and, 16 at a time, each segment's folders; a segment with `ink-labels/` is labeled.
2. Under it, each `<um>um-volume-<VOLUME>` folder gives the voxel size and volume, each date folder one label set, and each `.zarr` folder one array: its metadata gives shape and data type (zarr v3 `zarr.json` or v2 `.zarray`, at level 0 of an OME pyramid), and a listing without a delimiter gives its stored bytes (at most `MAX_PAGES` pages of 1,000 keys).
3. Exposure: the records of `docs/results.json` `held_out` are placed by `SCOPES` (w045 and w043 on PHerc0139; PHerc0841 and PHerc1447 on every segment of the scroll), with the one-word statuses of `held_out_by_reader` when present; the PHerc0139 w035 row of STANDARDS.md section 5 is placed the same way. A segment matches by its folder's w-number.

## Cost and time

Free; seconds per scroll (times in the table above). Nothing to rent.

## For agents

- **Command:** `python -m kit labels SCROLL --json`.
- **Parse:** `rows[].label_sets[].url` for the bucket path; `rows[].exposure[].by_reader` for the one-word status per model family.
- **Rerun:** Safe; read-only.
- **Success:** exit 0.
- **Not a pass:** "unknown" exposure is not held out; a family missing from `by_reader` is unknown for that family.
- **Go-ahead:** Nothing.
- **Never:** call a segment held out for a model the records do not name; add private findings to the records it reads.

## Tests

`python -m unittest tests.test_labels -v`: a fake bucket answering paged listings and reads; label sets, shapes, bytes and file counts; a segment without labels left out; exposure scoped to its scroll and "unknown" where there is no record; records read from planted files, an unmatched key reported, the repository's own records all placed; the page limit; the retry; a bad id. No network.

## History

- 2026-10-24: added (`ad3fddc`).

## Related

- [find](find.md): everything else public for a scroll.
- [auc](auc.md): score an ink map against these labels, with the reverse-depth control.
- [The exposure log](../logs/2026-10-16-reader-exposure.md): which released reader trained on which labeled segment, with sources.
- `held_out` and `held_out_by_reader` in [`docs/results.json`](../results.json).
