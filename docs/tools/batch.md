# batch: plan, price and queue AutoPipeline over every scan in the open-data bucket

`python -m kit run catalog`, `run all` and `run watch` list every volume of the Vesuvius Challenge open-data bucket, give each one an AutoPipeline config and a Modal price, and queue them in a resumable, approvable dry-run plan; they never launch anything.

| Field | Value |
| --- | --- |
| Id | `batch` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Pipeline and agents |
| Run | `python -m kit run all`, `python -m kit run watch`, `python -m kit run catalog`, `from kit import autobatch, scancatalog` |
| Code | `kit/autobatch.py`, `kit/scancatalog.py`, `kit/cli.py` (`cmd_batch`) |
| Tests | `tests/test_autobatch.py` |
| Needs | Python 3.10 or newer, standard library only. Reads `kit/data/modal-rates.json` (through [cloudcost](cloudcost.md)) and the prizes snapshot `kit/data/prizes-2026-10-11.json`. Launching an approved scan needs the released AutoPipeline package (`scrolls-kit`), which this tool does not call |
| Runs on | Any CPU. A dry run of a 5-volume synthetic catalog took 0.19 s (measured 2026-10-16, cloud container). A catalog of the real bucket: Not measured; it is a few hundred small HTTPS requests |
| Network | `run catalog`, `run watch`, and `run all` with `--refresh` or with no saved catalog: anonymous HTTPS GETs of `https://vesuvius-challenge-open-data.s3.amazonaws.com/metadata.json`, the bucket's S3 listing (root and each `SAMPLE/volumes/`) and `https://scrollprize.org/prizes` (skipped by `run catalog --no-live-prizes`). `run all` and `run watch` also GET each in-bucket volume's `.zattrs`, and `0/.zarray` when the shape is missing, once (cached). `dl.ash2txt.org` is refused. Nothing is posted |
| Writes | `run catalog`: `--out` only (default `work/autobatch/catalog.json`). `run all` and `run watch`: under `--state` (default `work/autobatch/`, git-ignored): `catalog.json`, `plan.json`, `plan.md`, `batch-ledger.csv`, `approval.json`, `scans/SAMPLE/VOLUME/status.json` and `settings.json`, `zattrs/` caches. `run all --status` writes nothing |
| Go-ahead | Not needed for `catalog`, `watch`, `--dry-run` or `--status`: they launch, post and spend nothing. Needed for `--approve`: run it only with the digest Chase approved, and each approved scan's Modal launch needs his yes and budget (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-16 ([PR #93](https://github.com/ChaseHendrick/Scrolls/pull/93)) |
| Guide | [AutoPipeline reference, section 19](../autopipeline/README.md#19-every-scan-catalog-batch-and-watcher) |
| Checked | 2026-10-16 against commit `14f5ce0` |

## What it does

AutoPipeline (AP), the released tool that runs villa's pipeline from a scan to a scored ink map, plans one scan at a time. The open-data bucket holds dozens of scan volumes at different voxel sizes, some superseded, some not yet in the bucket's `metadata.json`, and new ones appear. This tool takes the whole bucket at once and turns it into one priced plan that Chase can approve, without launching anything.

It has three parts. `kit/scancatalog.py` builds the catalog: one row per volume, from `metadata.json`, the bucket listing and the prizes page, with voxel size, shape, size, access, era (current, superseded or listing-only), surface predictions, normal grids, published segments and ink, license and prize eligibility. A sample, volume or zarr folder name that is not a safe name (one path component and one shell word) is left out and listed under `rejected`. `kit/autobatch.py` gives each row a config (the zarr level to trace and read at, the ink readers for its voxel size, the AP settings), prices it at Modal list rates, and keeps a status file per scan (`planned`, `approved`, `running`, `done`, `failed`, `skipped`, `blocked`), a plan with a digest, and a dry-run ledger. The watcher (`run watch`) rebuilds the catalog, finds new or changed volumes, and queues them the same way, for a scheduled routine.

It never starts Modal or any process: a test checks that neither module imports `modal` or `subprocess`. `--approve` records Chase's approval of one exact priced plan; the launch of each approved scan is AP's own per-run path, with its own budget guards and ledger row. Prices are estimates at list rates times assumed stage hours, not quotes. Batch configs carry only the generic AP settings for `benchmark` or `smoke` runs on public scans; a config that names title work is refused, since that work is private.

Nothing it writes is an ink map or a reading. A plan says what would run and what it would cost.

## When to use it

- Seeing what the bucket holds: `python -m kit run catalog`.
- Pricing AP over every scan, or one sample, before asking for a budget: `python -m kit run all --dry-run --refresh`.
- Recording Chase's yes to an exact plan: `python -m kit run all --approve DIGEST`.
- A scheduled check for new scans: `python -m kit run watch --exit-code`.

Do not use it:

- To run AP on one scan: use the released [AutoPipeline](autopipeline.md) (`scrolls-kit autopipeline plan`), which is also what an approved scan's `command` runs.
- To price one Modal job of another shape: use [cloudcost](cloudcost.md).
- To download scan data: use [fetch](fetch.md); this tool reads only metadata and zarr headers.
- To list the open prizes: use [prizes](prizes.md).
- For a target-scroll investigation: batch runs are generic benchmark and smoke runs; target work stays private.

## Quick start

```bash
python -m kit run all --dry-run --refresh            # catalog the bucket, config, price and queue every scan
python -m kit run all --status                       # per-scan status and the typical total still to run
python -m kit run all --approve DIGEST               # only after Chase approves that exact plan; launches nothing
python -m kit run watch --exit-code                  # for a schedule: exit 3 when new or changed volumes were queued
```

- `DIGEST`: the 16-hex-digit plan digest the dry run prints on its last line, the one Chase approved.

The first line contacts the bucket. To try it offline, this page was written from a synthetic run: the test catalog of `tests/test_autobatch.py` (5 volumes of one sample `S1`) written to `STATE/catalog.json`, with the `.zattrs` caches filled, then `python -m kit run all --dry-run --state STATE`. It printed, in 0.19 s:

```
| scan | um | readers | level | surf pred | low | typical | high | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S1/20230101000004 | 3.24 | hecate-2.4um | None | published | 0.0 | 0.0 | 0.0 | blocked: not in the open-data bucket (catalog points to another host; the bucket is the only source) |
| S1/20250101000001 | 2.4 | hecate-2.4um | 2 | published | 6.36 | 12.71 | 31.78 | planned |
| S1/20250101000002 | 9.362 | ink_9um-seed42 hecate-9.6um | 0 | needed | 2.2 | 4.39 | 10.99 | planned |
| S1/20250101000003 | 7.91 | ink_9um-seed42 hecate-9.6um | 0 | published | 0.0 | 0.0 | 0.0 | skip: superseded by 20250101000002 |
...
Total: low 8.56 USD, typical 17.1 USD, high 42.77 USD.

counts {'blocked': 2, 'planned': 2, 'skipped': 1}; plan digest 693d7eda73f1de80 (approve with: python -m kit run all --approve 693d7eda73f1de80); nothing launched
```

Then `--approve 693d7eda73f1de80` printed `approved 2 scans of plan 693d7eda73f1de80; nothing launched`, and `--status` listed the two scans as `approved`. With the network replaced by the same catalog, `run watch --exit-code` printed one `new` line per volume and `5 queued (dry run, nothing launched), 0 gone, 5 volumes in the catalog (first run: all are new)` with exit code 3, and a second run `0 queued ...` with exit code 0.

It worked when the exit code is 0 (or 3 for `watch --exit-code`) and the last line ends `nothing launched`.

## Checks and controls

- **Approval is bound to one priced plan.** The plan digest covers every scan's config and price, so `--approve` with any other digest fails (`BatchError: plan digest is A, not B: approve the plan you priced`, exit code 2), and a changed config or price sends a scan back to `planned`. `--approve` also rehashes `plan.json` and refuses one edited after pricing, and checks every scan's status file, config, cost and `settings.json` against the plan before it writes any approval. `tests/test_autobatch.py` checks all of these.
- **One bad row never stops the batch.** A catalog row with an unsafe id, a repeated key or the wrong types is listed under `rejected` and planned no further; `run watch --exit-code` exits 3 when a row failed, and retries it on the next run.
- **The ink control stays in every config.** Each scan's AP settings ask for the `f`, `r` and `s` ink variants, so the forward map comes with its reverse-depth control (`r`), as the rule that every check must be able to fail asks (hard rule 4).
- **Prices are calibrated once.** The module text says `COST_MODEL` was calibrated on the billed PHerc0841 w00 AP run (0.27 USD: 249 L4 seconds, 4,892 CPU seconds). Low and high are fixed multiples of typical (0.5 and 2.5), not measured spreads; check a plan's price against the Modal bill of its first few scans.
- **The reader choice is model output from one segment.** The code's comment (Chase, 16 October 2026) cites Hecate 2.4 um AUC 0.940, the organizers' canonical 2um model 0.887 and Hecate 9.6 um 0.922 on PHerc0139 w043, which it calls held out. That comparison is not in [`results.json`](../results.json), and w043 is in the training data of `ink_9um` ([log](../logs/2026-10-08-w045-not-held-out.md)); treat the rule as a planning default, not a ranking.
- **A recorded catalog, for scale.** On 16 October 2026 the catalog held 75 volumes in 39 samples: 73 current, 1 superseded, 1 listing-only; 68 in the bucket, 7 outside it; 22 prize eligible ([guide](../autopipeline/README.md#the-catalog)). Licenses vary by row (67 CC BY-NC 4.0, 7 EduceLab Data License, 1 none given), so read `license` per row.

Claim label: Interpretation, for the plan's configs and prices (estimates at Modal list rates, Sourced fact for the rates); Sourced fact, for the catalog rows read from the bucket's `metadata.json` and listing on the date in `checked`.

## Commands and options

### `python -m kit run all`

```
usage: python -m kit run all [-h] [--state STATE] [--dry-run | --status |
                             --approve DIGEST] [--refresh] [--only ONLY]
                             [--include-superseded] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--state STATE` | `work/autobatch` | Batch folder for the catalog, plan, ledger and status files (`autobatch.STATE`, git-ignored) |
| `--dry-run` | off | Plan, price and queue every scan. This is also what runs when none of `--dry-run`, `--status`, `--approve` is given |
| `--status` | off | Print each scan's status, typical USD and reason, and the typical total of `planned` and `approved` scans; writes nothing |
| `--approve DIGEST` | none | Move every `planned` scan of the plan in `STATE/plan.json` to `approved`, if DIGEST is that plan's digest, `plan.json` still hashes to it, and every scan's status, config, cost and `settings.json` still match what was priced (all are checked before any is written); write `approval.json`. Launches nothing |
| `--refresh` | off | Rebuild the catalog from the network before planning. Without it, `STATE/catalog.json` is reused (and fetched when missing). Ignored with `--status` and `--approve` |
| `--only ONLY` | none | Plan only `SAMPLE` or `SAMPLE/VOLUME`. Status files and ledger rows are written; `plan.json` and `plan.md` are not, so the printed digest is that of a partial plan, which `--approve` refuses |
| `--include-superseded` | off | Plan superseded volumes too, instead of skipping them |
| `--json` | off | Print the plan as JSON (the `plan.json` fields) instead of Markdown. Ignored with `--status` and `--approve` |

### `python -m kit run watch`

```
usage: python -m kit run watch [-h] [--state STATE] [--json] [--exit-code]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--state STATE` | `work/autobatch` | Batch folder; `STATE/catalog.json` is the last catalog seen, and is replaced by the new one |
| `--json` | off | Print the result as JSON (`first_run`, `queued`, `gone`, `catalog_volumes`, `rejected`, `failed`) instead of text lines |
| `--exit-code` | off | Exit 3 when anything was queued (new or changed rows, including skipped and blocked ones) or a row failed to plan, 0 when neither happened |

### `python -m kit run catalog`

```
usage: python -m kit run catalog [-h] [--out OUT] [--no-live-prizes]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--out OUT` | `work/autobatch/catalog.json` | Where to write the catalog JSON. Writing it to `STATE/catalog.json` makes it the catalog `run all` uses and the baseline `run watch` diffs against |
| `--no-live-prizes` | off | Do not fetch `https://scrollprize.org/prizes`; prize eligibility then comes from the dated snapshot only |

## Python API

```python
from kit import autobatch, scancatalog
doc = scancatalog.build(metadata, bucket_listing, snapshot, live_html=None)   # no network
plan = autobatch.plan_all("STATE", catalog=doc, levels_get=lambda url: b"{}")  # writes under STATE
```

`autobatch`:

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `BatchError` | Exception class | | Raised for a refused approval, an unsafe id, a path outside the batch folder, and by `refuse_title`; the command prints it as `BatchError: MESSAGE` and exits 2 |
| `digest(obj)` | First 16 hex digits of the SHA-256 of `obj` as compact JSON with sorted keys | `TypeError` for an object JSON cannot encode | Config and plan digests |
| `readers_for(voxel_um)` | `(reader names, reason)`; `([], reason)` when none fits | Nothing | The `READERS` rule by voxel size; `([], "no voxel size")` for a missing or non-positive size |
| `zarr_levels(zattrs)` | `[{"path", "scale"}]` from the first multiscale of an OME-Zarr `.zattrs` | Nothing for an empty document | `[(level path, scale zyx)]` |
| `fetch_levels(row, cache_dir, get=scancatalog.http_get)` | The level list, or `None` with no `zarr_url` or when the read fails | `BatchError` for a sample or volume id that is not a safe name, or a cache path outside `cache_dir`; nothing for network or JSON errors (they give `None`) | Read once from the volume's `.zattrs` and cached as `cache_dir/zattrs/SAMPLE_VOLUME.json`; a failure is not cached |
| `fetch_shape(row, cache_dir, get=scancatalog.http_get)` | Level-0 shape `[z, y, x]`, or `None` | `BatchError` as `fetch_levels`; nothing for network, JSON or key errors | From the zarr's `0/.zarray` when `metadata.json` gives none; cached as `SAMPLE_VOLUME.shape.json` |
| `with_shape(row, state, get)` | The row, with `shape_zyx` and `shape_source` added when fetched | Nothing | Fetches only for in-bucket rows in `metadata.json` without a shape |
| `pick_level(levels, voxel_um, want_um)` | Level index | Nothing | The coarsest level whose voxel (`voxel_um x 2^i`) is at most `want_um`; 0 when none is coarser |
| `scan_config(row, levels=None, model=None)` | The config dict (fields under Outputs), with `digest`, `skip` and `block` | `KeyError` or `TypeError` for a malformed row | The automatic per-scan config. A shape that is not three positive integers blocks the scan; a config naming title work is blocked with `refused: ...` (ids, `zarr_url` and the settings' `volume` are not checked, since bucket names may contain `title`) |
| `refuse_title(obj, path='config')` | None | `BatchError` for any key, or string value, containing `title` | Batch configs carry only the generic AP settings |
| `price(cfg, rates=None, model=None)` | `{"hours": {stage: h}, "stages_usd": {stage: USD}, "usd": {"low", "typical", "high"}}`; all zero for a skipped or blocked scan | `KeyError` for an unknown reader | Rates default to `cloudcost.load_rates()` |
| `read_status(state, cfg)` | The scan's `status.json` as a dict, or `None` | `json.JSONDecodeError` for a damaged file | |
| `queue_scan(state, cfg, cost)` | `(status, changed)` | `OSError` on a write failure; `BatchError` for an unsafe id | Creates or refreshes a scan's status; never moves a `done` or `running` scan with the same config back; keeps `approved` or `failed` only when both the config digest and the cost are unchanged; writes `settings.json` |
| `ledger_row(state, cfg, status, cost, plan_digest, note='')` | `True` when a row was added, `False` when its key was already there | `OSError` | One dry-run row per scan, config digest and plan digest |
| `launch_command(cfg)` | str: `scrolls-kit autopipeline plan SAMPLE --settings @work/autobatch/scans/SAMPLE/VOLUME/settings.json --out work/autobatch/runs/SAMPLE-VOLUME` | Nothing | The AP command an approved scan runs, each argument shell-quoted (`shlex.quote`); the paths assume the default state folder |
| `load_catalog(state, refresh=False, fetch=None)` | The catalog document | As `scancatalog.fetch` | Reuses `STATE/catalog.json` unless `refresh` or missing; otherwise fetches and saves it |
| `plan_all(state=STATE, catalog=None, only=None, include_superseded=False, levels_get=None, rates=None)` | The plan dict (fields under Outputs) | `OSError`, `ValueError`; as `load_catalog` when `catalog` is not given | Plan, price and queue every volume; write `plan.json`, `plan.md` (not with `only`) and the dry-run ledger rows. A row that raises one of `ROW_ERRORS` (`BatchError`, `TypeError`, `ValueError`, `KeyError`, `AttributeError`, `IndexError`, `ZeroDivisionError`, `OverflowError`), repeats a key, or lacks `prize_eligible` or `era` goes in `rejected` and is planned no further |
| `plan_markdown(plan)` | Markdown text | Nothing | What `run all --dry-run` prints and saves as `plan.md` |
| `approve(state, plan_digest)` | Number of scans moved from `planned` to `approved` | `BatchError` for another digest, a malformed or edited `plan.json`, or a scan whose status, config, cost or `settings.json` changed after pricing; `OSError` when `plan.json` is missing | Checks every scan before it writes any; writes `approval.json` |
| `status_table(state)` | `[{"key", "status", "reason", "typical_usd"}]`, sorted by path | `json.JSONDecodeError` for a damaged status file | What `--status` prints |
| `watch(state=STATE, fetch=None, levels_get=None, rates=None)` | `{"first_run", "queued", "gone", "catalog_volumes", "rejected", "failed"}` | As `scancatalog.fetch` and `queue_scan` | Diff a fresh catalog against the last one seen, queue new or changed volumes (dry run), save the catalog. `rejected` lists rows that failed to plan (`key`, `reason`, `change`) and names the catalog left out; `failed` counts the first kind, which are saved as last seen (or left out) so the next run retries them |

`scancatalog`:

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `ScanCatalogError` | Exception class | | Raised for a refused host |
| `safe_id(value)` | `True` for a string matching `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` that is not `.` or `..` | Nothing | Sample, volume and zarr folder names must pass: they become folder names and shell words |
| `valid_shape(shape)` | `True` for a list or tuple of three positive integers (not booleans) | Nothing | A level-0 shape check |
| `check_url(url)` | The URL | `ScanCatalogError` for `dl.ash2txt.org` or its subdomains | Every request goes through it |
| `http_get(url, opener=None, timeout=120)` | Response bytes, gunzipped when they start with the gzip magic | `ScanCatalogError`; `OSError` (`urllib.error.URLError`, `HTTPError`) for network errors | Anonymous GET with `User-Agent: kit-scancatalog` |
| `list_prefixes(prefix, get=http_get)` | List of folder prefixes | As `get`; `xml.etree.ElementTree.ParseError` for a bad listing | S3 ListObjectsV2 with `delimiter=/`, following continuation tokens |
| `listing(get=http_get)` | `{sample: [zarr folder names under SAMPLE/volumes/]}` | As `list_prefixes` | Skips top-level prefixes starting with `_` |
| `live_prize_ids(html)` | Sorted list of 14-digit volume ids starting `20` | Nothing | Volume ids the live prizes page names |
| `snapshot_prizes(snapshot)` | `{volume id: [prize ids]}` | Nothing | From a dated prizes snapshot |
| `parse_long_id(name)` | `{"volume", "voxel_um", "energy_keV"}`, each only when found | Nothing | From a zarr folder name such as `20250821110041-0.500um-masked.zarr` |
| `build(cat, bucket_listing, snapshot=None, live_html=None, checked=None)` | The catalog document (fields under Outputs) | `KeyError` or `TypeError` for a malformed `metadata.json` | No network. `live_html=None` means the live page was not read. Rows with an unsafe sample, volume or zarr folder name, or no unique volume id left, go in `rejected`. A second listing-only zarr of a known volume id takes the folder name without `.zarr`, else the whole folder name, so every key is unique |
| `key(row)` | `"SAMPLE/VOLUME"` | `KeyError` | |
| `fingerprint(row)` | 16 hex digits | Nothing | What a change to a row is measured by (see How it works) |
| `diff(old, new)` | `{"new": [rows], "changed": [rows], "gone": [keys]}` | Nothing | `old` may be `None` (first run) |
| `fetch(snapshot=None, get=http_get, live=True)` | The catalog document | `OSError`, `ValueError`, `ScanCatalogError`, `ParseError` | Reads `metadata.json`, the listing and (with `live`) the prizes page; a failed prizes page read falls back to the snapshot |
| `summary(doc)` | `{"volumes", "samples", "era", "access", "prize_eligible", "license", "scans_without_volume", "rejected"}` | Nothing | What `run catalog` prints; `rejected` is a count |
| `write(doc, path)` | The path | `OSError` | Indented JSON with sorted keys; makes parent folders |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| `metadata.json` | JSON from the bucket | `samples.SAMPLE.volumes.ID` with `long_id`, `scan_id`, `data` (an `ome-zarr` entry with `origins[0].path` and `access_roots`; `surface-prediction-zarr`, `normal-grids`, `umbilicus`, `lasagna`, `ink-detection-3d-zarr`) and `properties` (`pixel_size_um`, `energy_keV`, `shape` z y x, `superseded_by`, `license.name`); `segments` with `original_volume_id` and data types; `scans` |
| Bucket listing | S3 ListObjectsV2 XML | Zarr folder names under each `SAMPLE/volumes/` |
| Prizes | The live page's HTML, and `kit/data/prizes-2026-10-11.json` | A 14-digit volume id on the live page makes a row prize eligible; the snapshot says which prize names it |
| Zarr headers | `.zattrs` (OME-Zarr multiscales) and `0/.zarray` | Level paths; level-0 shape when `metadata.json` has none. Levels are assumed to halve resolution each step |
| Rates | `kit/data/modal-rates.json` | Through `cloudcost.load_rates()` |
| Saved state | `STATE/catalog.json`, `STATE/scans/*/*/status.json`, `STATE/plan.json` | From earlier runs; a status file's `status` may be edited by hand to `running`, `done` or `failed` as scans run |

## Outputs

`run all --dry-run` prints `plan.md` (a table of scan, voxel um, readers, trace level, surface prediction `needed` or `published`, low, typical and high USD, status), then one `rejected KEY: TYPE: MESSAGE` line per rejected row, then `counts {...}; plan digest DIGEST (approve with: python -m kit run all --approve DIGEST); nothing launched`. `--status` prints one line per scan (key, status, typical USD, reason) and `N scans, typical total X USD to run`. `--approve` prints `approved N scans of plan DIGEST; nothing launched`. `run watch` prints one line per queued scan (`new` or `changed`, key, status, voxel, readers, typical USD, reason) and `N queued (dry run, nothing launched), M gone, K volumes in the catalog`, with `(first run: all are new)` on a first run, then one `rejected KEY: REASON` line per row that failed to plan or that the catalog left out. `run catalog` prints the summary JSON and `wrote PATH`.

`plan.json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | int | 1 |
| `catalog_checked` | str | UTC time the catalog was built |
| `cost_model` | object | `COST_MODEL` as used |
| `scans[].key`, `.digest` | str | `SAMPLE/VOLUME` and its config digest |
| `scans[].voxel_um` | float or null | Level-0 voxel size, um |
| `scans[].readers` | list of str | Ink readers by voxel size |
| `scans[].trace_level`, `.ink_level` | int or null | Zarr levels to trace (at or under 9.6 um) and read ink at; null without levels |
| `scans[].levels` | list of str or null | The zarr's level paths |
| `scans[].needs_surface_prediction` | bool | No published surface prediction: a GPU surface-prediction stage is priced |
| `scans[].skip`, `.block` | str or null | Why the scan is skipped or blocked |
| `scans[].usd.low`, `.typical`, `.high` | float | USD estimate |
| `scans[].hours` | object | Hours per stage: `plan`, `grid`, `trace_render`, `ink`, and `surfacepred` when needed |
| `scans[].prize_eligible`, `.era` | bool, str | From the catalog |
| `scans[].command` | str or null | The AP launch command; null when skipped or blocked |
| `total_usd.low`, `.typical`, `.high` | float | Sum over scans, USD |
| `counts` | object | Scans per status |
| `rejected` | list | `{"key", "reason"}` per catalog row planned no further; not covered by the digest |
| `digest` | str | The plan digest to approve |

`scans/SAMPLE/VOLUME/status.json` has `key`, `digest`, `status`, `reason`, `config` (the scan config: `sample`, `volume`, `long_id`, `zarr_url`, `voxel_um`, `shape_zyx`, `levels`, `trace_level`, `ink_level`, `readers`, `reader_rule`, `readers_spec` (Hugging Face repo, file, revision, cost factor), `needs_surface_prediction`, `autopipe_settings`, `readers_outside_autopipe`, `surfaces`, `digest`, `skip`, `block`), `cost` (the `price` result) and `history` (`at`, `status`, and `digest` or `plan`). `settings.json` next to it is `autopipe_settings`: `purpose` (`benchmark` when the volume has ink labels, else `smoke`), `volume`, `ink` (`where` `modal`, `variants` `f r s`, `models`), `trace.normal_grids` (`auto` or `off`). `approval.json` has `plan`, `at`, `approved_scans`, `total_usd`. Times in these files are written as `YYYY-MM-DD HH:MM ET` from the machine's local clock.

`batch-ledger.csv` columns: `date_time_et, key, sample, volume, voxel_um, status, ink_readers, est_low_usd, est_typical_usd, est_high_usd, plan_digest, note`. `key` is `SAMPLE/VOLUME@CONFIGDIGEST#PLANDIGEST` (`#watch` for the watcher), `status` is `dry-run STATUS`, `note` is the skip or block reason, or `new` or `changed` from the watcher.

Catalog (`catalog.json`): `schema`, `checked`, `sources` (`metadata`, `listing`, `prizes`), `license_expected` (`CC BY-NC 4.0`), `scans_without_volume` (`sample`, `scan_id`, `long_id`, `voxel_um`, `energy_keV`, `date`), `rejected` (`sample`, `volume`, `name`, `reason` per name left out) and `volumes`, one row each:

| Field | Type | Meaning |
| --- | --- | --- |
| `sample`, `volume`, `long_id`, `scan_id` | str | Ids; `scan_id` null for listing-only rows |
| `voxel_um`, `energy_keV` | float or null | Voxel size in um, beam energy in keV |
| `shape_zyx`, `size_gb` | list of 3 int, float | Level-0 shape and uint8 size in GB (1e9 bytes) |
| `zarr_url` | str or null | Bucket URL of the zarr; null outside the bucket |
| `in_bucket`, `access`, `in_metadata` | bool, str, bool | `access` is `bucket` or `outside-bucket` |
| `era` | str | `current`, `superseded` or `listing-only` |
| `superseded_by` | str, object or null | The newer volume |
| `surface_predictions` | list | `model`, `level` per published surface prediction |
| `normal_grids`, `lasagna`, `volume_ink_3d` | int | Counts of those data entries |
| `umbilicus` | bool | An umbilicus is published |
| `segments`, `segment_ink_maps`, `ink_labels`, `ink_3d` | int | Published segments of the volume, and how many have ink maps, ink labels, 3D ink predictions |
| `license` | str or null | Per row; not all are CC BY-NC 4.0 |
| `prizes_snapshot`, `prize_live`, `prize_eligible` | list, bool or null, bool | Prizes naming it in the snapshot; named on the live page (null when not read); eligibility (live page when read, else snapshot) |

| Exit code | Meaning |
| --- | --- |
| `0` | Done; for `watch --exit-code`, nothing was queued and no row failed |
| `1` | An error the command does not catch, with a traceback, such as an unreadable bucket listing (`ParseError`) |
| `2` | A refused approval, an unsafe id, a refused host, a network or file error, bad JSON, or a malformed catalog (`TypeError`, `KeyError`), with `TYPE: MESSAGE` on stderr; or a usage error from the argument parser |
| `3` | `watch --exit-code` queued at least one volume or a row failed to plan |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, or two of `--dry-run`, `--status`, `--approve` | Check the command against Commands and options |
| `BatchError: plan digest is A, not B: approve the plan you priced`, exit code 2 | The digest given is not the one in `STATE/plan.json`: a typo, a plan rebuilt since it was priced, or a digest printed by an `--only` run | Rerun `--dry-run` without `--only`, show Chase the new plan and digest, and approve only what he approved |
| `BatchError: plan.json was edited after it was priced (contents hash to H): run --dry-run again`, exit code 2 | `STATE/plan.json` no longer hashes to its own `digest`: its scans or totals were changed by hand | Rerun `--dry-run` and have Chase approve the new digest |
| `BatchError: plan.json is malformed (...): run --dry-run again`, exit code 2 | `plan.json` lacks `scans` or `total_usd`, or they have the wrong types | Rerun `--dry-run` |
| `BatchError: S/V: status, config, cost or settings.json changed after pricing: run --dry-run again`, exit code 2 | A planned scan's `status.json` config no longer hashes to its digest, its cost differs from the plan's, or its `settings.json` is missing or edited. Nothing is approved | Rerun `--dry-run` and approve the new digest; do not edit `settings.json` by hand |
| `FileNotFoundError: [Errno 2] No such file or directory: '.../plan.json'`, exit code 2 | `--approve` before any full dry run in this `--state` | Run `python -m kit run all --dry-run` first |
| `rejected S/V: BatchError: sample id '...' is not a safe name` (or `volume id`) | A catalog row's id is not one safe path component and shell word (`scancatalog.safe_id`); the row is planned no further. From `--approve`, the same message with exit code 2 | Check the row; the rest of the batch is planned |
| `rejected S/V: BatchError: duplicate key S/V` | Two catalog rows share a key; the second is planned no further | Rebuild the catalog with `--refresh`, which gives each row a unique key |
| `rejected S/V: BatchError: row has no prize_eligible or era: rebuild the catalog with --refresh` | A catalog saved by an older version, or edited, lacks those fields | Run `python -m kit run all --dry-run --refresh` |
| `rejected S/V: TYPE: MESSAGE` with another type (`TypeError`, `KeyError`, ...) | A malformed catalog row | Rebuild the catalog with `--refresh`; report the row |
| `BatchError: PATH is outside the batch folder STATE`, as a `rejected` line or with exit code 2 | A status or cache path resolved outside `--state` (a second guard after the safe-id check, such as a symbolic link under `STATE`) | Check `STATE` for links; use a plain folder |
| `rejected S/NAME: sample id is not a safe name`, `volume id or zarr folder name is not a safe name`, `zarr folder name in the listing is not a safe name` or `duplicate volume id` (`run watch`) | `scancatalog.build` left the name out of the catalog | Nothing in the batch; it is listed every run until the bucket's name changes |
| A scan `blocked` with `refused: config.KEY: title settings are not allowed in a batch config` or `refused: config.PATH: title work is not allowed in a batch config` | A config key or string, other than the ids, `zarr_url` and the settings' `volume`, contains `title` | Batch configs are generic; title work is private and never runs here |
| `ScanCatalogError: refused: HOST is never used; the open-data bucket is the only source`, exit code 2 | A URL on `dl.ash2txt.org` | The bucket is the only source; the row stays `outside-bucket` |
| `URLError: <urlopen error ...>` or `HTTPError: HTTP Error 403: Forbidden`, exit code 2 | No network, a proxy refusal, or the bucket refusing a request | Check the network; `run all` without `--refresh` reuses a saved catalog |
| `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` or another JSON message, exit code 2 | `metadata.json`, a saved catalog or a status file is not valid JSON | Rerun with `--refresh`, or delete the damaged file under `STATE` |
| `KeyError: ...` or `TypeError: ...`, exit code 2 | A catalog document in an unexpected shape (such as no `volumes`) | Rebuild with `run catalog` or `--refresh` |
| `ParseError: ...` and a traceback, exit code 1 | A bucket listing that is not XML | Retry; report it if it persists |
| A scan `blocked` with `shape S is not three positive integers` | The row's `shape_zyx` is not three positive integers | Nothing to plan; check the row in `metadata.json` |
| A scan `blocked` with `not in the open-data bucket (catalog points to another host; the bucket is the only source)` | The volume is served only from another host (the 2023 scans) | Nothing in the batch; it is planned when the bucket holds it |
| A scan `blocked` with `in the bucket listing but not in metadata.json: no headers yet (watch picks it up when it appears)` | A listing-only volume | Wait; the watcher queues it as changed when `metadata.json` lists it |
| A scan `blocked` with `no shape in metadata.json`, `no voxel size`, or `N um is coarser than any released ink reader (20 um limit)` | Missing headers, or a voxel above 20 um | Nothing to plan; check the row |
| A scan `skipped` with `superseded by ID` | An earlier version of a scan | Leave it, or plan it with `--include-superseded` |
| `levels` and `trace_level` null for an in-bucket scan that is `planned` | Its `.zattrs` could not be read (network); the price then assumes level 0 | Rerun when the network is back: failures are not cached, and the scan's digest changes when levels are known |

## How it works

1. **Catalog** (`scancatalog.build`). For every sample in `metadata.json` or the listing, each volume gets a row from its `ome-zarr` entry, properties and data types. It is `in_bucket` when its zarr folder is in the listing or an access root is `s3://vesuvius-challenge-open-data`; otherwise it is `outside-bucket` and gets no URL. Folders in the listing that `metadata.json` does not name become `listing-only` rows, with voxel size and energy parsed from the folder name. Segments are counted per volume by `original_volume_id`. Eligibility comes from the live prizes page (any `20` followed by 12 digits) when read, else from the snapshot. Scans with no volume are listed apart. A sample, volume or zarr folder name that fails `safe_id` is left out and listed under `rejected`; a second listing-only zarr of a known volume id takes the folder name without `.zarr` (else the whole name) as its volume id, so keys are unique. The bucket keeps no object versions (checked 16 October 2026, per the module), so the past is what it still holds.
2. **Per-scan config** (`scan_config`). Readers by voxel size (`READERS`): up to 3.5 um `hecate-2.4um`; up to 6.5 um `hecate-2.4um` and `hecate-9.6um`; up to 20 um `ink_9um-seed42` and `hecate-9.6um`; coarser is blocked. `READER_SPEC` pins the Hecate weights to `scrollprize/hecate` revision `9cb86e500e944b11a06a7020403cde5dffb5bcb2` and `ink_9um` to `scrollprize/ink_9um` `hybrid_3d2d-seed42/step-075000.pth`; Hecate 9.6 um needs a resampling step (`kit hecateprep`) that is not in public `kit/`. `trace_level` is the coarsest level at or under 9.6 um; `ink_level` at or under 2.4 um when the first reader is Hecate 2.4 um, else 9.6 um. AP's own ink models are the readers it registers (`AUTOPIPE_MODELS`: `ink_9um-seed42`, `ink_9um-seed43`, `reader-v2`, `d9v2`, `v8in`), or `ink_9um-seed42` when none is; the rest go in `readers_outside_autopipe`. Skips and blocks are decided in order: outside the bucket, superseded, not in `metadata.json`, no shape, a shape that is not three positive integers, no reader; then a config that names title work (outside the ids, `zarr_url` and the settings' `volume`) is blocked with `refused: ...`. The config digest is taken before `skip` and `block` are set.
3. **Price** (`price`, `COST_MODEL`). With T the level-0 voxels in units of 1e12 and 4 surfaces per scan (`surfaces_per_scan`): plan 0.1 h on 8 cores and 32 GiB; normal-grid cache 0.6 h per T, clamped to 0.25 to 3 h, on 4 cores; trace and render 0.4 h per surface on 8 cores; ink per surface per reader (AP models and the scan's readers together), `min(1.0, 0.07 x (9 / um)^2 x cost_factor)` h on one L4 with 8 cores, where um is the ink level's voxel size and `cost_factor` is 2.0 for Hecate 2.4 um, else 1.0; surface prediction, when none is published, 2.0 h per T clamped to 0.5 to 8 h on one H100 with 8 cores and 64 GiB. Each stage is priced with `cloudcost.container_cost` at list rates, plus 0.016 USD per hour of all stages for the driver (`driver_usd_per_h`). Low and high are 0.5 and 2.5 times typical (`spread`).
4. **Queue** (`queue_scan`). A `done` or `running` scan with the same config digest is left alone. Otherwise the status is `blocked` or `skipped` with the reason, or kept `approved` or `failed` when the digest and the cost are unchanged (an approval holds only for the price Chase saw), or `planned`. History grows only when the status or digest changes. Files are written only when their text changes, through a temporary file and a rename.
5. **Plan and digest** (`plan_all`). Each row is checked (safe ids, a unique key, `prize_eligible` and `era` present) and prepared inside a guard: a row that raises one of `ROW_ERRORS` goes in `rejected` and the rest go on. The plan digest is taken over every scan's entry and the totals, not over `rejected`. Ledger rows are keyed by scan, config digest and plan digest, so a rerun with nothing changed adds none.
6. **Approve** (`approve`). `plan.json` is rehashed; it must match both its own `digest` and the one given. Then every scan is checked before any is written: each `planned` scan whose config digest matches must still have a config that hashes to that digest, the plan's cost, and a `settings.json` equal to its settings, or nothing is approved. Each such scan moves to `approved`, with a history entry naming the plan.
7. **Watch** (`watch`). The new catalog is diffed against `STATE/catalog.json` by key and by `fingerprint`, a hash of `long_id`, `voxel_um`, `shape_zyx`, `in_bucket`, `superseded_by`, `surface_predictions`, `normal_grids`, `umbilicus`, `segments` and `license`. New and changed rows are configured, priced and queued with a ledger row (`plan_digest` `watch`); gone keys are only reported. A row that fails to plan is reported and saved as it was last seen (or left out when new), so the next run tries it again. Then the new catalog is saved.

## Cost and time

The tool itself is free and quick: 0.19 s for a synthetic 5-volume dry run (2026-10-16, cloud container). A real catalog build and first dry run make a few hundred small HTTPS requests (Not measured). What it prices is not small: the guide says the batch total over the whole bucket is far above 100 USD, so Chase approves it in parts, and the AP Modal runner has its own guards (`ASK_USD` 100, `CAP_USD` 200; [guide](../autopipeline/README.md#the-batch-python--m-kit-run-all)). Every launch runs on Modal under the Modal rule (hard rule 11), within the Starter plan's limits of 10 GPUs and 100 containers at once ([plan limits](../compute/modal-pricing.md#2-plans-credits-limits-and-budgets)).

## For agents

- **Command:** `python -m kit run all --dry-run --refresh --json` (plan as JSON); `python -m kit run all --status`; `python -m kit run watch --json --exit-code` on a schedule; `python -m kit run catalog --out FILE`.
- **Parse:** from the plan, `digest`, `total_usd.typical`, `counts`, and per scan `key`, `usd`, `skip`, `block`, `command`; `rejected[].key`, `.reason`; from watch, `queued[].key`, `.change`, `.status`, `.usd.typical`, `.reason`, `gone`, `rejected[]` and `failed`; per scan, `status` in `STATE/scans/SAMPLE/VOLUME/status.json`.
- **Rerun:** Safe and idempotent: unchanged scans rewrite nothing and add no ledger row (`plan.md` is rewritten with the same text); `done` and `running` scans with an unchanged config are never moved back; a changed config returns a scan to `planned`. `watch` replaces `STATE/catalog.json`, so its second run reports only what changed since the first.
- **Success:** Exit code 0 and a last line ending `nothing launched`; for `watch --exit-code`, 3 means something was queued and 0 means nothing new.
- **Not a pass:** A printed digest from an `--only` run (it cannot be approved); `watch` exit 3 when every queued row is `skipped` or `blocked`, or when only `failed` is above 0; a plan with `rejected` rows read as covering the whole bucket; a `planned` scan with null `levels`; a typical USD read as a quote; the Hecate reader rule read as a held-out ranking.
- **Go-ahead:** `--approve` only with the exact digest Chase approved, and each Modal launch after it only with his yes and budget; nothing for dry runs, status, watch or catalog.
- **Never:** Launch Modal from a Claude cloud session; add title or target-scroll settings to a batch config; fetch from `dl.ash2txt.org`; commit anything under `work/autobatch/`; call a planned scan's future map a reading.

## Tests

```bash
python -m unittest tests.test_autobatch -v
```

They run on a synthetic catalog with no network and no Modal: catalog rows for current, superseded, listing-only and outside-bucket volumes, the refused host, listing parsing, the diff, readers by voxel size, prices and statuses (skips, blocks, levels, surface prediction, settings with `f` and `r`), idempotent and resumable reruns (no new ledger rows, `done` kept), approval with the exact digest only (and kept on replan), approval refused after `plan.json`, `settings.json` or a cost was changed, title refusal (and a volume named with `title` not stopping the batch), unsafe ids rejected with nothing written outside the state folder, shell-quoted launch commands, unique keys for repeated volume ids, bad rows blocked or rejected without stopping the batch, the watcher queueing only new volumes, surviving a malformed row, retrying a failed row and flagging it in the exit code, and printing names the catalog left out, and that neither module imports `modal` or `subprocess`. They do not touch the real bucket, check prices against a bill, or run the command line.

## History

- 2026-10-16: first version: open-data bucket catalog, per-scan config, priced dry-run batch (`run all`) and watcher (`run watch`); launches nothing (`765b428`, [PR #93](https://github.com/ChaseHendrick/Scrolls/pull/93)).
- 2026-10-16: safe ids (unsafe names left out of the catalog, shell-quoted launch commands, paths kept inside the batch folder), per-row errors under `rejected` instead of a failed batch, title refusal no longer tripped by bucket ids, and approval bound to the priced plan: `plan.json`, each scan's config, cost and `settings.json` are checked before any approval is written; errors print as `TYPE: MESSAGE` and `TypeError` and `KeyError` exit 2 (`794a48a`).
- 2026-10-16: `run watch` saves a row that failed to plan as last seen so the next run retries it, exits 3 for it with `--exit-code`, and prints names the catalog left out (`c1d38a2`).
- 2026-10-16: the Modal rates moved to `kit/data/modal-rates.json`, shipped with the package, so `run all` works after a pip install (`b1a96d2`).

## Related

- [AutoPipeline reference, section 19](../autopipeline/README.md#19-every-scan-catalog-batch-and-watcher): the guide to the catalog, batch and watcher; section 11 covers the per-run Modal launch.
- [autopipeline](autopipeline.md): the released tool each approved scan runs.
- [cloudcost](cloudcost.md): the Modal rates and `container_cost` behind every price.
- [modal-pricing.md](../compute/modal-pricing.md): rates, Starter plan limits and the default machine.
- [fetch](fetch.md): downloads from the same bucket.
- [prizes](prizes.md): the prizes snapshot that sets eligibility when the live page is not read.
- [the w045 log](../logs/2026-10-08-w045-not-held-out.md): which PHerc0139 segments `ink_9um` trained on, including w043.
