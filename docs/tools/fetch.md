# fetch: mirror one folder of the public bucket over HTTPS, resumably

`python -m kit fetch` copies every file under one prefix of the Vesuvius Challenge open-data bucket to a local folder over anonymous HTTPS, with no AWS CLI, and skips files already there at the listed size, so an interrupted fetch resumes.

| Field | Value |
| --- | --- |
| Id | `fetch` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Data and downloads |
| Run | `python -m kit fetch`, `from kit import fetch` |
| Code | `kit/fetch.py`, `kit/cli.py` (`cmd_fetch`) |
| Tests | `tests/test_kit.py` |
| Needs | Python 3.10 or newer, standard library only (urllib, concurrent.futures); outbound HTTPS to the bucket. Reading what it fetched needs zarr (the map tools) |
| Runs on | Any machine with network access. 33 objects (14.7 MB) took 3.9 s and 13 objects (0.12 MB) 6.8 s; a rerun with nothing to download 3.5 s (measured 2026-10-16, 4-core Xeon cloud container behind an HTTPS proxy). A whole surface volume (1.0 to 1.7 GB): Not measured |
| Network | `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` only (`BUCKET_URL`): S3 ListObjectsV2 listing pages and anonymous GETs of each object. urllib's default opener honors `HTTPS_PROXY` |
| Writes | The folder `DEST` and every subfolder it needs; one file per bucket object at `DEST/` plus the key minus the prefix, each written first as `NAME.part` and then renamed. Files already there at the listed size are left alone, files of another size are replaced, nothing is deleted |
| Go-ahead | Not needed: anonymous downloads of public data; nothing is posted or rented |
| Released | Public `main` since 2026-10-07 (`912135c`); also in the AutoPipeline release copy at `faada83`, and as `scrolls-workbench fetch` in the installed package |
| Guide | [mac.md](../mac.md) (the w035 download in the Mac runbook) |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

The Vesuvius Challenge publishes its scans, segments, surface volumes and ink labels in a public Amazon S3 bucket, `s3://vesuvius-challenge-open-data` (the open-data bucket). A surface volume (a stack of images rendered at depths above and below a traced papyrus surface, which ink models read) or a label store is a zarr folder of hundreds to thousands of small objects. `kit fetch` mirrors one such folder: it lists every key under the prefix you give, then downloads each object in parallel to the same relative path under a local folder.

It needs no AWS account and no AWS CLI, only Python's standard library. It checks every download against the size the listing reports, retries each object up to four times, writes each file under a temporary `.part` name and renames it when complete, and refuses keys that would land outside the destination. A file already present at the listed size is skipped, so a second run after an interruption only fetches what is missing.

Two short names cover the surface volumes most used here: `w035` and `w045`, the native 9.362 um renders of PHerc0139 segments w035 and w045. w035 is a training segment of `ink_9um` (the organizers' released 9 um ink model), and w045 is unseen by v8in (Youssef Nader's community ink model) but not held out from `ink_9um`, which trained on its 2.4 um render ([log](../logs/2026-10-08-w045-not-held-out.md)).

It does not check contents beyond the byte count: a file of the right size but wrong bytes is kept (see Checks and controls). It does not delete local files that are no longer in the bucket, and it fetches folders only, not single files. It makes no claim about the data: what it downloads is the organizers' published data, and any ink map made from it is model output, not a reading.

## When to use it

- Downloading a segment's surface volume and its `inklabels.zarr` and `supervision.zarr` before running an ink model and scoring it with [`auc`](auc.md).
- Getting the PHerc0139 w035 or w045 surface volume by its short name (`w035`, `w045`), as `kit plan` step 1b and the Mac runbook do.
- Resuming a large download that stopped: run the same command again.
- On a machine without the AWS CLI, or where only Python is allowed.

Do not use it:

- To fetch a single file: the prefix is always treated as a folder (`PREFIX/`), so a file's own key lists nothing. Download that one URL with any HTTPS client instead.
- To find what the bucket holds: use `python -m kit run catalog` ([batch](batch.md)), which lists every volume, or the prefixes in `scripts/mac-w045.sh` ([mac-w045](mac-w045.md)) for the labeled segments.
- To read only a window of a remote volume: `kit.meshaudit.SurfaceVolume` ([meshaudit](meshaudit.md)) reads windows of a published surface volume straight from the bucket, without mirroring the whole store.
- To prove the files are intact: it compares sizes only. Hash the files with [provenance](provenance.md) after the fetch, or delete them and fetch again.
- To keep a full mirror in step with the bucket: it never deletes local files that the bucket no longer has.

## Quick start

```bash
L=PHerc0841/segments/20260220213127-w00/ink-labels/2.403um-volume-20260319124803/20260918
python -m kit fetch "$L/inklabels.zarr" DEST/inklabels.zarr --workers 8
python -m kit fetch "$L/inklabels.zarr" DEST/inklabels.zarr --workers 8   # again: resumes, downloads nothing
```

- `DEST`: a local folder of your choice; it is created when missing.
- `L`: the bucket prefix of PHerc0841 w00's published ink labels (date 20260918), the same path `scripts/mac-w045.sh` uses. The labels of ag896 and ag405 sit under the same `ink-labels/2.403um-volume-20260319124803/20260918` path of their own segments, which are listed in that script.

Run on 2026-10-16 against the real bucket, with `DEST=/tmp/claude-docs-public-fetch/labels`, it printed:

```
13 objects, 0.1 MB total, 0.1 MB downloaded -> /tmp/claude-docs-public-fetch/labels/inklabels.zarr
13 objects, 0.1 MB total, 0.0 MB downloaded -> /tmp/claude-docs-public-fetch/labels/inklabels.zarr
```

It worked when the exit code is 0 and the object count is above 0; the rerun reporting `0.0 MB downloaded` shows the resume. The store then opens with zarr: this one has levels `0` to `5`, and level `2`, which matches w00's 9.366 um surface grid (4,220 x 4,760) up to a uniform scale, is a 4,115 x 4,640 uint8 array.

The surface volumes most used here go by their short names:

```bash
python -m kit fetch w045 data/w045_9um.zarr      # 3,700 objects, 1,693.7 MB (listed 2026-10-16)
python -m kit fetch w035 data/w035_9um.zarr      # 2,223 objects, 1,016.1 MB (listed 2026-10-16)
```

## Checks and controls

- **Byte count, able to fail.** Every download must be exactly the size the listing gives, or it is retried, and after four tries the run stops with `KEY: KEY: got N bytes, expected M` and exit code 2. `tests/test_kit.py` (`test_short_read_is_an_error`) feeds a short body and expects the failure; a fake bucket on 2026-10-16 printed `p/a.zarr/0: p/a.zarr/0: got 1 bytes, expected 3`.
- **Resume is by size only.** A local file of the listed size is trusted without being read, and no checksum or ETag is compared. A synthetic check recorded in the [UFSM review log](../logs/2026-10-07-ufsm-review.md) confirmed that `kit fetch` keeps a wrong file of the same size. When contents matter, record digests with [provenance](provenance.md) after the first fetch and check them later, or delete the folder and fetch again.
- **Exit code 0 as the completeness check.** A run that exits 0 leaves every listed object on disk at its listed size, and a rerun that prints `0.0 MB downloaded` found almost nothing missing. The figure is rounded to 0.1 MB, so `0.0` means under 50 KB came down, not exactly nothing. Then open the store with the tool that will read it (zarr): a store that does not open was fetched from a wrong prefix or is incomplete.
- **Listing guards.** A continuation token seen twice stops the listing (`bucket listing repeated a continuation token`) instead of looping, and a key that would land outside `DEST` is refused (`refusing unsafe key`).
- **Held-out status of the short names.** A score on w035 or w045 is not a generalization result for `ink_9um` and its fine-tunes; w045 is held out from v8in only. Check the `held_out` key of [`results.json`](../results.json) before scoring.

Claim label: None: it copies the organizers' public files and makes no claim. The held-out notes on `w035` and `w045` are Sourced fact, from the [w045 log](../logs/2026-10-08-w045-not-held-out.md).

## Commands and options

### `python -m kit fetch`

```
usage: python -m kit fetch [-h] [--workers WORKERS] prefix dest
```

| Option | Default | Meaning |
| --- | --- | --- |
| `prefix` | required | A bucket prefix that is a folder, written without `s3://` or the bucket name, such as `PHerc0841/segments/20260220213127-w00/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr`. Leading and trailing slashes are dropped and one `/` is added, so only keys under `PREFIX/` are fetched. Or a short name: `w035` (`W035_9UM`, an `ink_9um` training segment) or `w045` (`W045_9UM`, unseen by v8in, but `ink_9um` trained on its 2.4 um render) |
| `dest` | required | The local folder. Created with its parents when missing; each object lands at `DEST/` plus its key minus `PREFIX/`, so a zarr store's root metadata sits directly in `DEST` |
| `--workers WORKERS` | `16` | Download threads. Each thread holds one whole object in memory while it downloads. 0 or less fails after the listing with a traceback (`ValueError`). The scripts here pass 8 for label stores |

## Python API

```python
from kit import fetch
objects, fetched, total = fetch.fetch_prefix(fetch.ALIASES["w045"], "data/w045_9um.zarr", workers=8)
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `FetchError` | An exception class (subclass of `Exception`) | Nothing | Raised for every failure the module detects itself; the command catches it and exits 2 |
| `parse_listing(xml)` | `([(key, size), ...], token)`: the keys and byte sizes of one ListObjectsV2 XML page, and its `NextContinuationToken` or `None` | Nothing of its own | Reads `<Key>` and `<Size>` inside each `<Contents>` with a regular expression. XML escapes such as `&amp;` in a key are not decoded |
| `list_prefix(prefix, opener=urllib.request.urlopen, base=BUCKET_URL)` | `(prefix, entries)`: the prefix with one trailing `/`, and every `(key, size)` under it, over all pages | `FetchError` for a repeated continuation token; whatever `opener` raises, such as `urllib.error.URLError`, `HTTPError` or `TimeoutError` (all `OSError`) | 1,000 keys per page, 60 s timeout per page. `opener(url, timeout=...)` must return an object with `.read()`; tests pass a fake |
| `local_path(dest, prefix, key)` | `Path(dest) / rest`, where `rest` is `key` minus `prefix` | `FetchError` (`refusing unsafe key ...`) when `rest` is empty, starts with `/`, or has a `..` part | `prefix` must end with `/`, as `list_prefix` returns it |
| `fetch_prefix(prefix, dest, workers=16, opener=urllib.request.urlopen, base=BUCKET_URL)` | `(objects, fetched, total)`: the number of objects listed, the bytes downloaded in this call, and the bytes of all listed objects | `FetchError` for an empty listing, an unsafe key, a repeated token, or an object that failed four tries; `OSError` from the listing or from creating folders; `ValueError` for `workers` below 1 | What the command runs, after mapping a short name through `ALIASES` (the command does that, not this function) |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Prefix | A key prefix in the bucket, case sensitive | Layout used here: `SCROLL/segments/SEGMENT/surface-volumes/VOLUME.zarr` for a surface volume, and `SCROLL/segments/SEGMENT/ink-labels/VOLUME/DATE/inklabels.zarr` and `supervision.zarr` for labels. The labeled segments' prefixes are in `scripts/mac-w045.sh`; `python -m kit run catalog` lists every volume |
| Objects | Any bytes | Each object is read whole into memory, then written. Memory is about `--workers` times the largest object: the largest object of w035 and w045 is 458,752 bytes (listed 2026-10-16), so this is small for zarr stores, but a single multi-GB object would need that much RAM |
| Short names | `ALIASES` in `kit/fetch.py` | `w035`: `PHerc0139/segments/20260317000000-w035_2026031718/surface-volumes/9.362um-1.2m-113keV-volume-20250728140407.zarr`. `w045`: `PHerc0139/segments/20260126000000-w045_2026012619/surface-volumes/9.362um-1.2m-113keV-volume-20250728140407.zarr` |

What came down in the Quick start: `inklabels.zarr` of PHerc0841 w00, a zarr 3 group with levels `0` to `5`; level `0` is 16,460 x 18,560 and level `2` is 4,115 x 4,640, both uint8 (read with zarr 3.4.1 on 2026-10-16). The w035 surface volume is an OME-Zarr (zarr 2 layout) group with levels `0` to `5`; its level `3` alone is 28 x 728 x 655 uint8 in 28 x 128 x 128 chunks (33 objects, 14.7 MB). The bucket's data carry the license its `metadata.json` names; `kit/scancatalog.py` records CC BY-NC 4.0 (`LICENSE`).

## Outputs

On success it prints one line to stdout:

```
N objects, T MB total, F MB downloaded -> DEST
```

| Part | Meaning |
| --- | --- |
| `N objects` | Objects listed under the prefix |
| `T MB total` | Their total size, in units of 10^6 bytes, one decimal |
| `F MB downloaded` | Bytes downloaded in this run, same units; `0.0` when every file was already present at its size, or when under 50 KB came down (rounding) |
| `-> DEST` | The destination as given |

Files: one per object under `DEST`, at the key's path relative to the prefix. A `NAME.part` file is left behind only if writing a file failed part way; the next run replaces it.

| Exit code | Meaning |
| --- | --- |
| `0` | Every listed object is present at its listed size |
| `1` | An error the command does not catch, with a Python traceback, such as `--workers 0` (`ValueError`), or a transfer error during the listing that is not an `OSError` (such as `http.client.IncompleteRead`) |
| `2` | A `FetchError` or `OSError`, with the message on stderr (see Failure modes), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `nothing under s3://vesuvius-challenge-open-data/PREFIX/`, exit code 2 | The listing is empty: a typo or wrong case in the prefix, a prefix that names a single file, or a path that moved | Check the prefix against `python -m kit run catalog` or `scripts/mac-w045.sh`; fetch the folder that holds the file |
| `refusing unsafe key 'KEY'`, exit code 2 | A listed key whose rest after the prefix is empty, starts with `/`, or has a `..` part, so it would land on `DEST` itself or outside it | Do not work around it; fetch a narrower prefix and report the key |
| `bucket listing repeated a continuation token`, exit code 2 | The listing returned a page token it had already returned, so it would loop forever | Run again later; if it repeats, check the HTTPS proxy, which may be serving a cached page |
| `KEY: KEY: got N bytes, expected M`, exit code 2 | The object came back shorter (or longer) than listed on all four tries; truncated reads happen (villa issue #1666, named in the code) | Run the same command again: it resumes |
| `KEY: HTTP Error 403: Forbidden`, `KEY: timed out` or another `KEY: ...`, exit code 2 | Downloading that object failed four times (an HTTP error, a 120 s timeout, a write error) | Check the network and the proxy, then rerun |
| `<urlopen error [Errno -2] Name or service not known>`, `HTTP Error 403: Forbidden` or `timed out` without a key, exit code 2 | The listing request failed: no network, DNS, a proxy refusal, or a 60 s timeout | Check the network and `HTTPS_PROXY`, then rerun |
| `[Errno 13] Permission denied: 'DEST/...'`, exit code 2 | `DEST` or a folder under it cannot be created | Pick a writable `DEST` |
| `ValueError: max_workers must be greater than 0` and a traceback, exit code 1 | `--workers` 0 or less (the listing has already run) | Use `--workers 1` or more |

## How it works

1. **Short names.** The command replaces `w035` or `w045` with `W035_9UM` or `W045_9UM` from `ALIASES`; any other text is used as the prefix.
2. **List.** `list_prefix` strips slashes, adds one `/`, and requests `BUCKET_URL/?list-type=2&max-keys=1000&prefix=PREFIX/` (S3 ListObjectsV2, 1,000 keys per page, 60 s timeout). It follows `NextContinuationToken`, URL-encoded completely (`safe=""`), because a token holding `/` otherwise re-requests page 1 forever (commit `912135c`). A token seen twice raises `FetchError`. An empty result raises `FetchError`.
3. **Download.** A `ThreadPoolExecutor` of `--workers` threads maps over the listing in order. For each object: refuse an unsafe key; skip it if the local file exists at the listed size (0 bytes counted); create its folder; then up to 4 tries of GET `BUCKET_URL/KEY` (key URL-quoted, slashes kept, 120 s timeout), read the whole body, check its length, write `NAME.part`, and `os.replace` it onto `NAME`, which is atomic on one filesystem. Tries follow each other at once, with no wait. After the fourth failure it raises `FetchError("KEY: LAST_ERROR")`.
4. **Stop on failure.** The first failure stops the run when the in-order collection reaches it: objects not started yet are canceled, and downloads already running finish. A rerun resumes from what is on disk.
5. **Count.** It returns the number of objects, the bytes downloaded and the total bytes, and the command prints them.

Constants: `BUCKET_URL = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"`, 1,000 keys per listing page, 60 s listing timeout, 120 s download timeout, 4 tries per object, 16 workers by default. The module docstring describes the result as the same files `aws s3 sync --no-sign-request` would fetch. To decide what to skip, `kit fetch` compares sizes only, and it never deletes a local file.

## Cost and time

Measured 2026-10-16 in a 4-core Intel Xeon cloud container (lscpu: 2.80 GHz, 15 GB RAM) whose HTTPS goes through a proxy:

| Run | Objects | Size | Wall time |
| --- | --- | --- | --- |
| PHerc0841 w00 `inklabels.zarr`, `--workers 8` | 13 | 0.12 MB | 6.8 s |
| The same again (nothing to download) | 13 | 0.12 MB | 3.5 s |
| Level `3` of the w035 surface volume, 16 workers | 33 | 14.7 MB | 3.9 s |
| Listing only, `w035` | 2,223 | 1,016.1 MB | 7.3 s |
| Listing only, `w045` | 3,700 | 1,693.7 MB | 6.5 s |

A whole surface volume (about 1.0 to 1.7 GB): Not measured; the time depends on the link. The 2026-10-07 [w035 run](../logs/2026-10-07-w035-cpu.md) records the w035 fetch as 2,223 objects, 1.02 GB, without a time. It uses no GPU and rents nothing. Make sure `DEST` has room for the total size first. On Chase's Mac, wrap a long fetch with `python -m kit run local SLUG -- python -m kit fetch ...` (the local compute rule in [`AGENTS.md`](../../AGENTS.md)).

## For agents

- **Command:** `python -m kit fetch PREFIX DEST --workers 8`, or `python -m kit fetch w045 DEST.zarr` for a short name. There is no JSON form; the machine-readable result is the exit code and the one stdout line.
- **Parse:** the line `N objects, T MB total, F MB downloaded -> DEST`: N is the object count (above 0 on success), T the total size, F what this run downloaded (`0.0` on a complete rerun; rounded to 0.1 MB). On failure, stderr holds one message from Failure modes.
- **Rerun:** Safe and resumable. It skips files present at the listed size, replaces files of another size, and never deletes. It does not detect a wrong file of the right size.
- **Success:** Exit code 0 and the stdout line; for a strong check, a rerun printing `0.0 MB downloaded` and the store opening in zarr.
- **Not a pass:** Exit code 0 does not prove the bytes are right, only the sizes; a store from the wrong prefix (another segment or label date) fetches without error; a later score on w035, or on w045 for `ink_9um` and its fine-tunes, is not a held-out result.
- **Go-ahead:** Nothing: it downloads public data anonymously. Check free disk space before a surface volume (up to 1.7 GB).
- **Never:** Commit fetched scroll data to git or attach it to public artifacts (the no-data-in-git rule, hard rule 6); treat a size match as a checksum; describe an ink map made from fetched data as a reading.

## Tests

```bash
python -m unittest tests.test_kit.FetchTest tests.test_kit.PlanTest.test_fetch_aliases_point_at_9um_surface_volumes -v
```

They use a fake bucket (an `opener` that returns canned XML and bodies) and cover: a listing over two pages whose token holds `/`, the download, a rerun that downloads nothing, a short read that fails, an unsafe key refused, and the `w035` and `w045` short names pointing at the 9 um surface volumes. They do not touch the network, and do not cover HTTP errors, timeouts, the four tries, an empty prefix, a repeated token, or what happens to other downloads when one fails. `FetchTest` sits below the `unittest.main()` line of `tests/test_kit.py`, so it runs under `python -m unittest` but not with `python tests/test_kit.py`.

## History

- 2026-10-08: the `w045` comment says w045 is not held out from `ink_9um`, which trained on its 2.4 um render (`d841e06`, [log](../logs/2026-10-08-w045-not-held-out.md)).
- 2026-10-07: the `w045` short name (`b533efa`).
- 2026-10-07: first version: paged listing with fully encoded tokens, resume by size, short reads rejected, unsafe keys refused, the `w035` short name; checked against the real w035 surface volume, 2,223 objects over three listing pages (`912135c`).

## Related

- [`auc`](auc.md): scores ink maps against the `inklabels.zarr` and `supervision.zarr` this fetches.
- [`layers`](layers.md): turns a fetched surface volume into v8in's layer TIFFs, and writes the depth-shuffle control.
- [`mac-w045`](mac-w045.md): fetches a segment's surface volume and labels with this command; it holds the prefixes of the labeled segments.
- [`plan`](plan.md): its step 1b starts with `kit fetch w045`.
- [`batch`](batch.md): `kit run catalog` lists every volume in the bucket.
- [`provenance`](provenance.md): file digests, the content check this tool does not make.
- [`meshaudit`](meshaudit.md): its `SurfaceVolume` reads windows of bucket surface volumes without mirroring them.
- [UFSM review log](../logs/2026-10-07-ufsm-review.md): the same-size file that resume keeps.
- [`results.json`](../results.json) `held_out`: which segment is held out from which model.
