# vc3d-cache: find VC3D's remote chunk cache and delete its false empty-chunk markers

`kit/vc3d_cache.py` and `python -m kit vc3dcache` find the folder where VC3D caches a remote volume, check every chunk VC3D marked as empty against the bucket, and delete the markers for chunks that exist, so a later render or trace fetches them instead of reading zeros.

| Field | Value |
| --- | --- |
| Id | `vc3d-cache` |
| Status | Current |
| Kind | kit module |
| Area | Data and downloads |
| Run | `from kit import vc3d_cache` (its command line, `kit vc3dcache`, is on the [vc3dfix](vc3dfix.md) page) |
| Code | `kit/vc3d_cache.py` |
| Tests | `tests/test_vc3d_cache.py`, `tests/test_vc3dfix.py` |
| Needs | Python 3.10 or newer; standard library only (it uses the stores of `kit/vc3d_audit.py` and the states of `kit/s3retry.py`). `fcntl` for the ledger lock where the system has it (Linux, macOS); without it the ledger is written unlocked. VC3D itself is not needed to check a cache |
| Runs on | Any CPU. A synthetic cache of 6 markers against a local S3-like server: 16 requests in 1.1 s (measured 2026-10-16, 4-core Intel Xeon cloud container). Real caches: Not measured for time; on 2026-10-08 a crop render's 8 false markers were found and deleted ([log](../logs/2026-10-12-upstream-reports.md)) |
| Network | The remote volume's own host only (for the open-data bucket `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` or `vesuvius-challenge-open-data.s3.amazonaws.com`): the volume's headers, then a HEAD per marked chunk (a 404 confirmed with a one-byte GET) or one shard-index read per shard, anonymous, at most 4,000 per check, paced at 20 per second. Nothing when no marker needs checking |
| Writes | Deletes false `.empty` marker files in VC3D's cache folder for the volume (not with `delete` false). Writes the ledger `LEDGER_DIR/FOLDER.json` and its lock file `LEDGER_DIR/FOLDER.lock` (`kit vc3dcache` and `kit s3relay` use `work/vc3d-empty/`) |
| Go-ahead | Not needed: it reads a public bucket and changes only VC3D's cache on this machine |
| Released | Public `main` from the change that adds it (24 Oct 2026). An earlier copy ships inside the AutoPipeline release branches (`submission/progress-2026-10` from 2026-10-14, `submission/progress-2026-10-fix4`), without the 17 October deletion-timestamp correction below |
| Guide | [VC3D and S3's false 404s](../vc3d-false-404.md) |
| Checked | 2026-10-24 against commit `77aea1f` |

## What it does

VC3D (Volume Cartographer 3D, villa's segmentation and rendering tools) streams a remote zarr volume chunk by chunk and keeps what it fetched in a persistent cache on disk. A chunk the server answered with HTTP 404 becomes an empty marker file in that cache, and the marker stands for good: every later render and trace reads that chunk as zeros and never asks again. S3 sometimes answers 404 for chunks it holds (a "false 404": 404 with the S3 error code `NoSuchBucket` instead of `NoSuchKey`; [s3retry](s3retry.md)). Measured on 2026-10-08 from one cloud machine: a 256 x 256 crop render of the 2.4 um PHerc0139 scan with an empty cache left markers for 4 chunks the bucket holds, so 27.7 % of its samples were zeros, and VC3D exited 0 with no warning ([log](../logs/2026-10-12-upstream-reports.md)).

This module finds the cache folder exactly as VC3D does (the root as in villa main [`GlobalCacheRoot.hpp`](https://github.com/ScrollPrize/villa/blob/main/volume-cartographer/core/include/vc/core/util/GlobalCacheRoot.hpp) and [`RemoteCacheSettings.cpp`](https://github.com/ScrollPrize/villa/blob/main/volume-cartographer/core/src/RemoteCacheSettings.cpp), read 24 Oct 2026; the folder name and markers as in villa `e0bbb8b`: `core/src/Volume.cpp`, `core/src/render/ChunkCache.cpp`), lists every empty-chunk marker in it, and asks the bucket about each one with the same rule as [vc3d-audit](vc3d-audit.md): present, missing only on `NoSuchKey`, unknown otherwise. A marker whose chunk is present is false and is deleted, so the next read fetches the chunk. A marker whose chunk is missing is true and is remembered in a ledger, so it is asked only once.

`python -m kit s3relay URL -- COMMAND` runs it around one VC3D command through `Guard`: before the run it repairs what earlier runs left; after the run it repairs what this run left and lists the false markers deleted since the run started, which are chunks the run may have read as zeros, so the run can be made again. `python -m kit vc3dcache URL` does the check on demand, for runs made without the relay (the VC3D app, a script).

It does not change the bucket, VC3D, or a volume on disk, and it does not decide whether any render is good. It only removes markers whose chunks exist; a render made before the repair still has its holes and must be made again.

## When to use it

- After VC3D read a remote volume without the relay (the app, a script, another session): `python -m kit vc3dcache` with the URL VC3D was given, or `--all`.
- When a render or trace from a URL has blank patches.
- In your own Python wrapper around a VC3D run on a URL: `Guard(url, ...)`, `before()`, run, `after()`.

Do not use it:

- For a local volume: it has no remote cache. Use [vc3d-audit](vc3d-audit.md) to check its chunks.
- To check whether the bucket itself holds every chunk under a surface: that is [vc3d-audit](vc3d-audit.md) with `surface`.
- To stop VC3D from caching false 404s in the first place: the local relay ([s3relay](s3relay.md), `python -m kit s3relay`) does that; this check is the second line.

## Quick start

```bash
python -m kit vc3dcache VOLUME_URL
python -m kit vc3dcache --all
```

- `VOLUME_URL`: the volume URL as VC3D was given it, such as `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr`. The command also checks the folders of the other spellings of a bucket URL (`s3://`, global and us-east-1 https) and of the relay URLs `kit s3relay` may have given VC3D for it ([vc3dfix](vc3dfix.md)).

On a synthetic cache (a 64 cubed volume of 2 x 2 x 2 chunks served by a local S3-like server that answers each key's first request with a false 404, one chunk really missing, and markers in every layout) the Python API `check` printed (excerpt, 2026-10-16):

```
 "markers": 6,
 "known_true": 0,
 "checked": 6,
 "false": [
  ".vc_cache_empty/0/1/0/0.empty",
  "0/0/0/1.empty",
  "level_0/0/0/0.empty"
 ],
 "true": 2,
 "unknown": [
  "level_9/0/0/0.empty"
 ],
 "deleted": 3,
 "false_404s": 4,
 "requests": 16
```

A second check asked only about the unknown marker (`known_true` 2, `checked` 1). On a cloud container with no VC3D cache, `python -m kit vc3dcache --all` printed `VC3D remote cache: /root/.VC3D/remote_cache` and `no volume folders` (2026-10-24).

It worked when the exit code is 0. Read the false markers deleted and the unknown count; a run that read a deleted marker's chunk must be run again.

## Checks and controls

- **The check can fail both ways, and the tests show it.** `tests/test_vc3d_cache.py` serves a volume with one chunk really missing and markers for chunks that exist: the false ones are deleted, the true ones stay and go in the ledger, and a marker of a level the volume lacks stays `unknown`. With `delete` false the false marker stays on disk.
- **A repair is counted in its own run.** Deletion timestamps retain full precision, matching `Guard`'s window boundaries. Rounding a repair up to the next millisecond could make it appear in two consecutive windows, so a run that repeats itself after a repair could repeat once too often (found 17 October 2026; the tests of that repeat logic belong to a tool not in this repository).
- **The folder name is VC3D's.** The FNV-1a folder names were checked against two folders VC3D (villa `e0bbb8b`) made in one cloud container on 2026-10-08 (`20250728140407-9.362um-1.2m-113keV-masked.zarr-740e7d4163dba61a` and `20260102150214-2.399um-0.2m-78keV-masked.zarr-f9800af75caa5598`, in `tests/test_vc3d_cache.py`). A wrong folder name would find no markers and pass silently, so this test is the control for "no markers".
- **A real repair, for scale.** On 2026-10-08 the 2.399 um crop render with 27.7 % zero samples was rendered again after the check deleted its 8 false markers: 0.03 % zeros, bit for bit the same as an earlier clean render ([log](../logs/2026-10-12-upstream-reports.md)). The 16 markers already in that container's 9.362 um cache were all true.
- **Unknown is not true.** A marker the bucket could not answer for (403, failures, the request budget, a level missing from the pyramid) stays on disk and is listed under `unknown`; it is asked again next time.

Claim label: Sourced fact, for which marked chunks the bucket held when it was asked; a deleted marker says nothing about a render made before the repair.

## Commands and options

The command line is `python -m kit vc3dcache` (and `python -m kit s3relay`, which runs `Guard` around one command); both are on the [vc3dfix](vc3dfix.md) page with every option.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `VC3D_CONFIG_DIR` | `~/.VC3D` | Folder of `cache.json` (its `root` sets the cache root when the file exists) and `VC3D.ini` (its `[viewer]` key `remote_cache_dir` sets it otherwise), as VC3D reads them |
| `HOME` | the user's home | Base of `~/.VC3D` and `~/.VC3D/remote_cache` |
| `KIT_HTTP_REUSE` | `1` | `0` makes the store open a new connection per request ([keepalive](keepalive.md)) |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `check(url, env=None, ledger_dir=None, store=None, delete=True, recheck=False, budget=DEFAULT_BUDGET, progress=None, root=None, cache_url=None, **store_kw)` | The report dict under Outputs | Nothing for a store that cannot be read (that becomes `error`, with every marker `unknown`); `OSError` from the file system can escape | `url` is where chunks are checked; `cache_url` (default `url`) is the URL VC3D was given, which names the folder. `env` replaces `os.environ` for finding the root, `root` replaces the root. `store_kw` goes to `vc3d_audit.HttpStore` (`rate`, `opener`, ...). Without `ledger_dir` nothing is remembered |
| `Guard(url, env=None, ledger_dir=None, store_factory=None, budget=DEFAULT_BUDGET, progress=None, root=None, cache_url=None)` | An object with `before()` and `after()` (each returns a `check` report; `after()` adds `affected`), `summary()` (dict `cache`, `checked`, `false_deleted`, `unknown`, and `error` when a check failed) and `reports` (every report) | Never; a failed check becomes a report with `error` | `affected`: the false markers deleted since `before()`, by this guard or by another process (read from the ledger), sorted. `store_factory()` may return a store, or None for the default `HttpStore` |
| `cache_root(env=None, is_dir=os.path.isdir)` | `Path` of VC3D's remote cache root | `CacheError` for a `cache.json` that is not JSON, not version 1, or has a relative root (VC3D refuses those too) | `root` in `VC3D_CONFIG_DIR/cache.json` (else `HOME/.VC3D/cache.json`) when that file exists, normalized; else `remote_cache_dir` in `[viewer]` of `VC3D.ini` in the same folder, `~` expanded; else `/volpkgs/remote_cache` or `/ephemeral/remote_cache` when that folder exists; else `HOME/.VC3D/remote_cache` |
| `volume_dir(url, env=None, root=None)` | `Path` `ROOT/NAME-HASH` | Nothing | NAME is the URL's last part after trailing slashes are dropped; HASH is `fnv1a64` of that URL as 16 hex digits |
| `fnv1a64(text)` | int, the 64-bit FNV-1a hash of the UTF-8 bytes | Nothing | Offset basis `0xCBF29CE484222325`, prime `0x100000001B3` |
| `ini_value(path, section, key)` | str or None | Nothing (an unreadable file gives None) | Qt-style INI: `;` and `#` comments, a double-quoted value unescaped |
| `markers(vdir)` | Sorted list of every `*.empty` path under the folder, relative, with `/` | Nothing | Empty when the folder does not exist |
| `parse_marker(rel)` | `("chunk", L, (iz, iy, ix))` for `level_L/iz/iy/ix.empty`; `("key", None, KEY)` for `KEY.empty` or `.vc_cache_empty/KEY.empty` | Nothing | |
| `classify(store, rels, budget=DEFAULT_BUDGET, progress=None)` | `{rel: (state, zarr key or note)}`, state `present`, `missing` or `unknown` | `vc3d_audit.AuditError` when the volume's headers cannot be read | Markers of one chunk are asked once; a legacy marker's L is the level's position in the pyramid, finest first; sharded levels are checked through shard indexes |
| `Ledger(path)` | An object with `read()` (dict `url`, `cache_url`, `genuine` {marker: time}, `deleted` [{`marker`, `at`}]) and `locked()` (a context manager that yields that dict and writes it back atomically) | `OSError` when the folder cannot be made | Keeps the last `LEDGER_KEEP` deletions. An unreadable ledger reads as empty |
| `CacheError` | | | `ValueError` subclass, raised by `cache_root` for a `cache.json` VC3D would refuse |

Constants: `LEDGER_KEEP` 2,000 (deletions kept per volume), `DEFAULT_BUDGET` 4,000 (requests per check).

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Volume URL | `http(s)://` or `s3://`, as VC3D was given it | Trailing slashes do not change the folder; `s3://` and `https://` forms, and relay URLs, name different folders |
| VC3D's cache | A folder per volume under the cache root, holding markers `level_L/iz/iy/ix.empty` (chunk indices of pyramid level L, VC3D's legacy layout), `KEY.empty` (the mirror layout) and `.vc_cache_empty/KEY.empty` (the delta3d layout), KEY being the zarr chunk key | Only files ending in `.empty` are touched |
| The volume's zarr headers | Read from `url` through [vc3d-audit](vc3d-audit.md)'s `levels` | A legacy marker needs the pyramid to turn chunk indices into keys |
| Ledger | JSON written by this module | `work/vc3d-empty/FOLDER.json` for `kit vc3dcache` and `kit s3relay` |

## Outputs

`check` returns, and `kit vc3dcache --json` prints per volume (inside `volumes[]`, with `folder` and `given`):

| Field | Type | Meaning |
| --- | --- | --- |
| `volume` | str | The URL the chunks were checked at |
| `cache` | str | The cache folder |
| `markers` | int | Markers in the folder before the check |
| `known_true` | int | Markers the ledger already holds as true, not asked again |
| `checked` | int | Markers asked about |
| `false` | list of str | Markers whose chunk exists (deleted unless `delete` false) |
| `true` | int | Markers whose chunk is missing (`NoSuchKey`); kept and remembered |
| `unknown` | list of str | Markers with no answer (403, failures, budget, a level the pyramid lacks, or every marker when `error` is set) |
| `deleted` | int | Marker files deleted |
| `keys` | object | The first 20 false markers with the zarr key (or `level L inner chunk [...]`) each stands for |
| `false_404s` | int | 404s S3 gave for keys that exist, each asked again (only when any) |
| `requests` | int | HTTP requests made (only when any) |
| `error` | str | Why the volume could not be read (only then) |
| `affected` | list of str | `Guard.after()` only: false markers deleted since `before()` |

`kit vc3dcache --json` adds `cache_root`, and totals over the folders: `false_deleted`, `false_found`, `unknown` (a count). A check with no marker to ask returns at once with only `volume`, `cache`, `markers`, `known_true`, `checked`, `false`, `true`, `unknown` and `deleted`. Its exit codes are on the [vc3dfix](vc3dfix.md) page.

## Failure modes

The messages of the command line are on the [vc3dfix](vc3dfix.md) page. In a report from `check`:

| What you see | Why | What to do |
| --- | --- | --- |
| `"markers": 0` for a volume you know VC3D read | The folder is named by another form of the URL (`s3://` against `https://`, a relay port, a trailing difference VC3D keeps) or the cache root differs (`VC3D_CONFIG_DIR`, `/volpkgs`, `/ephemeral`) | Give the exact URL from the VC3D command line; check the cache root against `root` in `cache.json` and `remote_cache_dir` in `VC3D.ini` |
| `CONF/cache.json does not read as JSON: DETAIL` (`CacheError`, from `cache_root`) | `cache.json` in `VC3D_CONFIG_DIR` or `~/.VC3D` exists but is not JSON; VC3D refuses it too | Fix or remove the file; `kit vc3dcache` and `kit s3relay` exit 2 before touching anything |
| `CONF/cache.json needs version 1 and an absolute root; VC3D refuses it otherwise` (`CacheError`) | The file is JSON but not an object with `"version": 1` and a `root` starting with `/` | Write `{"version": 1, "root": "/ABSOLUTE/PATH"}`, or remove the file |
| `"error": "URL: no zarr metadata at its root (.zarray, .zgroup, .zattrs or zarr.json)"` and every marker under `unknown` | The URL is wrong, or its headers could not be read | Fix the URL or the network; nothing was deleted |
| `"error": "URL/KEY: request failed (...)"` or `HTTP 403` | A header read failed after retries | Check the network; run again |
| A `level_L/...` marker stays under `unknown` on every check (`classify` notes `level L: not in this volume's pyramid`) | A legacy marker of a pyramid level the volume does not have | Check that the URL is the volume VC3D read; such a marker is left alone |
| `unknown` lists markers after `requests` reached about 4,000 | The per-check budget (`DEFAULT_BUDGET`) | Run the check again; markers found true are not asked again |
| `Guard.summary()` has `error` | A check around a run failed; the run went on unguarded | Run `python -m kit vc3dcache URL` afterward |

## How it works

1. **Find the folder** (`cache_root`, `volume_dir`). The root is `root` from `cache.json` when that file exists (villa main since October 2026; the same file as [doctor](doctor.md)'s `--remote` reads), else `remote_cache_dir` from VC3D.ini, else `/volpkgs/remote_cache` or `/ephemeral/remote_cache` when that folder exists, else `~/.VC3D/remote_cache`. The folder is `NAME-HASH`: the URL's last part, and the 64-bit FNV-1a of the URL without trailing slashes, as VC3D names it.
2. **List markers** (`markers`) and drop those the ledger holds as true (unless `recheck`).
3. **Map markers to chunks** (`classify`). Legacy markers become chunk keys of their pyramid level through the volume's headers; key markers are their key. Markers of the same chunk are grouped.
4. **Ask the bucket.** Through `vc3d_audit.HttpStore`: a HEAD per key, a 404 confirmed with a one-byte GET, a false 404 asked again up to 10 times, 403 and failures `unknown`, 8 threads at 20 requests per second, at most `budget` requests. Sharded levels read one shard index per shard.
5. **Repair.** Delete each false marker (present chunk). In the ledger, under a file lock, record true markers with the time, append the deletions with the time (keeping the last 2,000), and drop a marker from the true list when it is false now.
6. **Guard a run** (`Guard`). `before()` checks and records the time; `after()` checks again and reports as `affected` every false marker deleted since then, from this guard's check and from the ledger (another process may have deleted one). `kit s3relay` lists them and exits 4 when the command succeeded, so the run can be made again.

## Cost and time

| Run | Requests | Time | Source |
| --- | --- | --- | --- |
| Synthetic cache, 6 markers in three layouts, local S3-like server with false 404s, Python API (`rate` 0) | 16 | 1.1 s | Run 2026-10-16, 4-core Intel Xeon cloud container |
| A real cache | Not measured | Not measured | |

The cost grows with the number of markers to ask: about one request per marked chunk (two when the answer is a 404), at 20 per second, after the volume's headers. It is CPU and network only, runs wherever VC3D's cache is, and rents nothing.

## For agents

- **Command:** `python -m kit vc3dcache VOLUME_URL --json`; to look without changing anything, add `--no-delete`; for every folder in the cache, `python -m kit vc3dcache --all --json`. In Python: `vc3d_cache.check(URL, ledger_dir="work/vc3d-empty")`, or `Guard` around your own VC3D run.
- **Parse:** `false_deleted`, `false_found`, `unknown` (count), and per volume `false`, `true`, `unknown`, `keys`, `error`. From `Guard.after()`, `affected`.
- **Rerun:** Safe and cheap: markers found true are remembered and not asked again; false ones are already gone. It appends deletions to the ledger.
- **Success:** Exit 0, no `error` in any volume, and `unknown` 0.
- **Not a pass:** `"markers": 0` for a URL in a form VC3D was not given; a repaired cache taken to mean an earlier render is whole (render it again); `unknown` markers taken as true.
- **Go-ahead:** Nothing; it only reads the public bucket and edits VC3D's cache on this machine.
- **Never:** Delete a cache folder or markers by hand to "fix" holes without checking them (true markers are real holes in a masked scan); take any 404 from S3 as a missing chunk.

## Tests

```bash
python -m unittest tests.test_vc3d_cache tests.test_vc3dfix -v
```

`tests/test_vc3d_cache.py` covers folder names against two real VC3D folders, the cache root from `cache.json` (winning over VC3D.ini, and refused when VC3D would refuse it), from VC3D.ini, `/ephemeral` and `HOME`, the three marker layouts, false markers deleted and true ones remembered against a local S3-like server with false 404s, report-only mode, the folder named by `cache_url`, `Guard` listing what a run may have read (including a deletion by another process), and a guard that never raises. `tests/test_vc3dfix.py` runs `Guard` around a stand-in VC3D command through the relay and checks a relay folder from the command line. They do not touch a real VC3D cache or the bucket.

## History

- 2026-10-24: on public `main`, with `python -m kit vc3dcache` and `kit s3relay`'s guard; deletion times keep full precision, so one repair is never counted in two runs' windows (a correction of 17 October, not in the AutoPipeline release copies); the cache root follows villa main's `cache.json` before `VC3D.ini` (`77aea1f`).
- 2026-10-15: the copy in AutoPipeline 0.1.4 (`603fe14`, branch `submission/progress-2026-10-fix4`), first released inside the AutoPipeline package on `submission/progress-2026-10` on 14 October. Made before it was public: the first version of 8 October; the folder is named by the URL VC3D was given (`cache_url`, the relay's URL), while chunks are checked at the bucket URL (8 October).

## Related

- [vc3dfix](vc3dfix.md): `python -m kit vc3dcache` and `python -m kit s3relay`.
- [vc3d-audit](vc3d-audit.md): the stores, the headers and `presence` this module uses; checks the bucket under a surface.
- [s3retry](s3retry.md): the rule that a 404 is missing only on `NoSuchKey`.
- [s3relay](s3relay.md): the local relay that keeps VC3D from caching false 404s in the first place.
- [VC3D and S3's false 404s](../vc3d-false-404.md): the how-to.
- [The upstream reports log](../logs/2026-10-12-upstream-reports.md): the false-404 measurements and the repair.
