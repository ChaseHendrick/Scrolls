# hfpull: download a Hugging Face bucket folder fast, each distinct file once

`kit.hfpull.pull` copies a folder of the organizers' public `scrollprize/datasets` bucket, or any Hugging Face bucket you can read, to local disk, downloading each distinct file once and copying the duplicates, so the public ink label stores download many times faster.

| Field | Value |
| --- | --- |
| Id | `hfpull` |
| Status | Current |
| Kind | kit module |
| Area | Data and downloads |
| Run | `from kit import hfpull`, or `python -m kit.hfpull PREFIX DEST [--bucket B] [--mount M] [--exclude PAT]` under a Python that has `huggingface_hub` |
| Code | `kit/hfpull.py` |
| Tests | `tests/test_hfpull.py` |
| Needs | Python 3.10 or newer. The API route needs `huggingface_hub` with `list_bucket_tree` and `download_bucket_files` (1.33.0 or newer; 2.3.0 used here). A public bucket (`PUBLIC`: `scrollprize/datasets`) needs no token; a private bucket needs `HF_TOKEN` in the environment. The mount route needs the bucket mounted as a folder, such as a bucket volume mounted in an HF Job |
| Runs on | Any machine with network access, or inside an HF Job. The PHerc0139 w035 ink_9um label store (3,606 files, 0.3 MB) took 5.0 s against 61.7 s for a plain download of every file (25 Oct 2026, 4-core Claude cloud container behind an HTTPS proxy, anonymous) |
| Network | `huggingface.co` and its Xet storage: one bucket tree listing and the file downloads. None on the mount route |
| Writes | The pulled files under `dest`, with the bucket folder's layout; duplicates and the mount route write each file through a `.part` name and rename it |
| Go-ahead | Not needed: anonymous downloads of public data, or reads of a bucket you own |
| Released | Public `main` from the change that adds it (25 Oct 2026) |
| Checked | 2026-10-25 against commit `7e60e87` |

## What it does

The Vesuvius Challenge team publishes the ink labels its ink models train on in the Hugging Face bucket `scrollprize/datasets` (`ink_9um/labels/` and `ink/`). Each label store is a zarr v2 folder of thousands of tiny chunk files, and most of them are copies of one empty chunk. The Hub serves bucket files at about 40 to 60 a second whatever their size, so the request count, not the byte count, decides how long a download takes.

`pull(prefix, dest)` lists the bucket folder once, drops files that a pattern in `exclude` matches (a pattern matches either the path under the folder or the file's own name, and `.part` files are skipped), groups the rest by their Xet content hash and size, and downloads only the first file of each group in one `download_bucket_files` call, which fails if a listed file has gone. It then copies each downloaded file to the other paths with the same content. It returns which route ran, the file count, the bytes, how many files it actually downloaded and the seconds.

When there is no `huggingface_hub`, or no token for a private bucket, it reads a mounted copy of the bucket instead (`mount`), with 32 threads. With neither, it refuses rather than returning an empty folder.

It does not upload and it checks no hashes of its own: the bucket's content addressing is what the download trusts. It makes no claim about the data; a label store is the organizers' published labels.

## When to use it

- Downloading one or many of the public ink label stores before training or scoring an ink model.
- A Hugging Face Job script that reads more than a handful of files from a bucket before it starts work: bucket mounts read many small files slowly.

Do not use it:

- For the open-data S3 bucket (`vesuvius-challenge-open-data`): use [fetch](fetch.md). Its labels are sharded zarr v3, a few files a store, and already fast.
- For a Hugging Face dataset or model repository (not a bucket): use `hf download`.
- To write outputs: it only reads.

## Quick start

```bash
python3 -m venv .hub && .hub/bin/pip install "huggingface_hub>=1.33"
.hub/bin/python -m kit.hfpull ink_9um/labels/aligned-scrollprizeorg-21slices/pherc0139-w035 labels/w035
```

- The prefix is the organizers' ink_9um label store for PHerc0139 segment w035, a training segment of `ink_9um`.
- `labels/w035`: a local folder of your choice; it is created when missing.

Run on 2026-10-25 with `labels/w035` in a scratch folder, it printed:

```
hfpull ink_9um/labels/aligned-scrollprizeorg-21slices/pherc0139-w035: 3606 files, 0.00 GB in 5.6 s via api (175 downloaded, the rest copies of identical files)
{"route": "api", "files": 3606, "bytes": 297875, "seconds": 5.6, "downloaded": 175}
```

It worked when `route` is `api` and `files` matches what the folder should hold.

## Checks and controls

`tests/test_hfpull.py` pulls one fake bucket both ways and expects the same files from each, with an excluded `.ckpt`, a `.part` file and a sibling folder left out; checks that 53 files with 3 distinct contents are fetched as 3 downloads and copied byte for byte; and checks that a private bucket with no token and no mount is refused. The benchmark below checks the deduplicated download against a plain download of every file with `filecmp`, file by file.

Claim label: Sourced fact, for the benchmark numbers (the bench record, one run).

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `HfPullError()` | an exception | none | Raised when neither route can run |
| `excluded(rel, patterns)` | `bool` | none | True when a pattern matches the path under the pulled folder or the file's own name. |
| `has_token(env=None)` | `bool` | none | `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` is set in `env` (default `os.environ`) |
| `plan_api(api, bucket, prefix, dest, exclude=())` | `list` | Hub errors | [(bucket file, local path), ...] for every file under prefix that no pattern excludes. |
| `unique(todo)` | `tuple` | none | (first, copies): the planned downloads with one file per content hash, and (downloaded path, local path) for every other file with the same content, to copy on disk afterwards. |
| `plan_mount(src, dest, exclude=())` | `list` | `OSError` | [(mounted file, local path), ...] for the same rule, read from the mount. |
| `pull(prefix, dest, *, exclude=(), bucket=BUCKET, mount=None, api=None, env=None, workers=MOUNT_WORKERS, say=print, clock=time.monotonic)` | `dict` | `HfPullError`, Hub errors, `OSError` | Copy bucket folder `prefix` to `dest`. Returns {"route", "files", "bytes", "seconds"}. |
| `main(argv=None)` | `int` | none | One pull from the command line; its record as JSON on the last line |

## Commands and options

### `python -m kit.hfpull`

```
usage: python -m kit.hfpull [-h] [--bucket BUCKET] [--mount MOUNT]
                            [--exclude EXCLUDE]
                            prefix dest
```

| Option | Default | Meaning |
| --- | --- | --- |
| `prefix` | required | The folder (or one file) inside the bucket |
| `dest` | required | The local folder (or file) to write |
| `--bucket` | `scrollprize/datasets` | The bucket; `scrollprize/datasets` is public and needs no token |
| `--mount` | none | The mounted bucket root, read when the API route cannot run |
| `--exclude` | none | An fnmatch pattern to leave out; repeat for more |

## Inputs

A folder path inside the bucket (`prefix`), a local destination, and optional fnmatch patterns to leave out.

## Outputs

One line per pull, `hfpull PREFIX: N files, X GB in S s via ROUTE`, and the returned dict:

| Field | Type | Meaning |
| --- | --- | --- |
| `route` | str | `api` or `mount` |
| `files` | int | files written |
| `bytes` | int | bytes written |
| `seconds` | float | wall time of the pull |
| `downloaded` | int | API route only: files fetched from the Hub; the rest of `files` were copies of identical ones |

`python -m kit.hfpull` prints the line on stderr and the dict as JSON on stdout.

| Exit code | Meaning |
| --- | --- |
| `0` | Pulled |
| `2` | Neither route could run (`HfPullError`) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `no token for the API route and ... is not mounted` | A private bucket with no `HF_TOKEN`, or no `huggingface_hub`, and the folder is not under the mount | Install `huggingface_hub`, set `HF_TOKEN`, or mount the bucket and pass `--mount` |
| `HTTP Error 429` and a wait from `huggingface_hub` | The Hub's rate limit; anonymous requests have a lower limit than requests with a token | Let it retry, or set `HF_TOKEN` (any account) for the higher limit |
| An entry-not-found error from `huggingface_hub` | A listed file was deleted before the download | Rerun the pull |

## How it works

1. With `huggingface_hub` and a token, or anonymously for a bucket in `PUBLIC`: `list_bucket_tree(bucket, prefix, recursive=True)`, keep files whose path under `prefix` passes `excluded`, create their parent folders, group them by (Xet hash, size), then one `download_bucket_files(bucket, [(file, local)], raise_on_missing_files=True)` for the first file of each group, and copy it to the others through `.part` files.
2. Otherwise: walk `mount/prefix`, apply the same rule, and copy with `MOUNT_WORKERS = 32` threads through `.part` files.

## Cost and time

Measured 25 Oct 2026 in a 4-core Claude cloud container behind an HTTPS proxy, anonymous reads, one run each way, one after the other ([bench script](../../scripts/experiments/2026-10-25-label-pull/README.md)):

| Pull | Every file (`download_bucket_files`) | `hfpull` | Files downloaded | Same files |
| --- | --- | --- | --- | --- |
| PHerc0139 w035 ink_9um labels (`ink_9um/labels/aligned-scrollprizeorg-21slices/pherc0139-w035`), 3,606 files, 297,875 bytes | 61.7 s | 5.0 s (12x) | 175 | yes (`filecmp`, every file) |

The gain grows with the share of repeated chunks; a store with few repeats gains little. Times on other networks, such as inside an HF Job, will differ.

Reproduce with `python scripts/experiments/2026-10-25-label-pull/labelpull.py PREFIX OUT` under a Python that has `huggingface_hub`; it downloads the store both ways and compares the folders.

## For agents

- **Command:** `from kit import hfpull; s = hfpull.pull(PREFIX, DEST)`, or `python -m kit.hfpull PREFIX DEST` and parse the last stdout line as JSON.
- **Parse:** the returned dict; `downloaded` against `files` shows how much deduplication saved.
- **Rerun:** safe; it overwrites the same files.
- **Success:** `route` is `api` and `files` is the count you expect.
- **Not a pass:** `route` `mount` on a large folder: it works but is slow.
- **Go-ahead:** Nothing.
- **Never:** pass a token on the command line; it is read from the environment.

## Tests

`python3 -m unittest tests.test_hfpull -v`: nine tests with a fake bucket and a temporary mount; they do not reach the Hub.

## History

- 2026-10-25: released on public `main` (`c01d8f5`), with the public bucket as the default and a benchmark on the PHerc0139 w035 ink_9um label store.

## Related

- [fetch](fetch.md): the open-data S3 bucket.
- [labels](labels.md): the label stores and what they cover.
