# vc3dfix: run VC3D through a false-404 relay, and repair its cache of empty chunks

`python -m kit s3relay` runs VC3D (or any command) through a local relay that keeps S3's false 404s out, checking VC3D's empty-chunk markers around the run; `python -m kit vc3dcache` checks and repairs those markers after a run made without it.

| Field | Value |
| --- | --- |
| Id | `vc3dfix` |
| Status | Current |
| Kind | kit command |
| Area | Data and downloads |
| Run | `python -m kit s3relay`, `python -m kit vc3dcache` |
| Code | `kit/vc3dfix.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_vc3dfix.py` |
| Needs | Python 3 standard library only. VC3D (villa's `vc_*` tools or the app) for the runs it guards; any command works in its place. numcodecs only to decode compressed chunks when a marker is checked by reading ([vc3d-cache](vc3d-cache.md)) |
| Runs on | Any CPU. The relay runs in a thread of the command; the cache check reads one object per marker, paced at 20 requests a second, at most 4,000 per check ([vc3d-cache](vc3d-cache.md)) |
| Network | `s3relay`: listens on `127.0.0.1` on a port from 20000 to 40014 (or `--port`), and connects to the volume URL's origin only, anonymously, through `HTTPS_PROXY` when set ([s3relay](s3relay.md)). Both commands ask the volume's origin about each empty-chunk marker. Nothing else |
| Writes | `vc3dcache` deletes false `.empty` markers in VC3D's cache folder for the volume (not with `--no-delete`) and writes the record `LEDGER/FOLDER.json` and its lock file (default `work/vc3d-empty/`). `s3relay` with a command does the same before and after the command; the command writes what it writes. `s3relay` alone writes nothing |
| Go-ahead | Not needed: it reads public objects anonymously and changes only the local VC3D cache |
| Released | Public `main` from the change that adds it (24 Oct 2026) |
| Guide | [VC3D and S3's false 404s](../vc3d-false-404.md) |
| Checked | 2026-10-24 against commit `HASH1` |

## What it does

S3 sometimes answers 404 with the error code `NoSuchBucket` for keys it holds: a **false 404** ([s3retry](s3retry.md)). VC3D, villa's Volume Cartographer 3D, takes any 404 for a missing chunk and writes an **empty-chunk marker** in its persistent cache, a `.empty` file that stands for good: every later read of that chunk returns zeros, with no error and exit code 0. On 8 October 2026 a fresh crop render of PHerc0139 w035 from one cloud machine got 4 false markers and 27.7 % zero samples this way ([log](../logs/2026-10-12-upstream-reports.md)).

This page is the command line for two modules. `python -m kit s3relay URL` starts the relay of [s3relay](s3relay.md), which asks S3 again after a false 404 and passes a 404 on only for `NoSuchKey`, and prints the URL to give VC3D. With a command after `--`, it runs that command with every spelling of the volume URL in its arguments (`s3://`, global and us-east-1 https) swapped for the relay's, checks VC3D's markers for the relay's cache folder before and after the run with `Guard` ([vc3d-cache](vc3d-cache.md)), and lists the false markers deleted since the run began: chunks the run may have read as zeros, so the run must be made again. It then exits with the command's exit code, or 4 when the command succeeded but such chunks were found.

`python -m kit vc3dcache URL` checks the markers of every cache folder VC3D may have made for that volume (each spelling of the URL, and the relay URLs `kit s3relay` may have given it) against the bucket, and deletes the false ones, so the next read fetches the chunk. `--all` lists every volume folder in the cache with its marker count.

It does not patch VC3D, fetch volumes, or say anything about the data it guards: a clean cache means no chunk VC3D holds as empty exists in the bucket, not that a render is right.

## When to use it

- Any VC3D run that reads a remote volume from S3, such as `vc_render_tifxyz` on an open-data scan: `python -m kit s3relay URL -- COMMAND`.
- The VC3D app on a remote volume: `python -m kit s3relay URL`, give the app the printed URL, and stop the relay (Ctrl-C) after the app has finished.
- After VC3D read a remote volume without the relay (the app, a script, another machine's session): `python -m kit vc3dcache URL`, with the URL VC3D was given.

Do not use it:

- To download a volume: use [fetch](fetch.md), which asks again after a false 404 itself.
- For a local volume: VC3D's cache and markers are only for remote ones.
- With a VC3D build that counts an S3 404 as missing only with a complete `NoSuchKey` error (the fix proposed in draft [villa PR #2060](https://github.com/ScrollPrize/villa/pull/2060)): the relay is then not needed, though `vc3dcache` still repairs markers older builds left.

## Quick start

```bash
python -m kit s3relay VOLUME_URL -- VC3D_COMMAND ...
python -m kit vc3dcache VOLUME_URL
```

- `VOLUME_URL`: the remote zarr, such as `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr` (or its `s3://vesuvius-challenge-open-data/...` form).
- `VC3D_COMMAND ...`: the command as you would run it, naming `VOLUME_URL`; the URL in it is swapped for the relay's.

A live run on 2026-10-24 (00:33 UTC, a Claude cloud container, through its HTTPS proxy), with `curl` standing in for VC3D, since VC3D is not built there:

```bash
U=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr
python -m kit s3relay $U -- curl --noproxy '*' -sS -o /dev/null -w '%{http_code} %{size_download}\n' $U/0/.zarray
```

with `$U/0/80/25/25` and `$U/0/0/0/0` added to the curl line. The relay was on `127.0.0.1:27518`; curl got `200 239` for `0/.zarray`, `200 2097152` for chunk `0/80/25/25` (one 128 cubed uint8 chunk) and `404` with S3's `NoSuchKey` body for chunk `0/0/0/0`, a corner of the masked scan the bucket does not hold, passed on unchanged. The command ended:

```
relay: 3 requests, 0 false 404s asked again, 1 missing keys passed on, 0 given up (sent as 503), 0 network errors
cache: 0 markers checked, 0 false ones deleted (.../20250728140407-9.362um-1.2m-113keV-masked.zarr-5475b6b8e15ff18f)
command exit code 0
```

and `python -m kit vc3dcache $U` then printed `no cache folder (VC3D has not read ...)` and `0 false markers found, 0 deleted, 0 unknown`, exit code 0. S3 gave no false 404 in that run, so the retry path was not exercised live; the tests below drive it with a fake server.

It worked when the exit code is 0. Exit code 4 means the command succeeded but may have read zeros: run it again (the false markers are already gone).

## Checks and controls

- **A false 404 is caught, a real one is not.** `tests/test_vc3dfix.py` serves a small zarr from a local S3-like server that answers each key's first request with `NoSuchBucket`, with one chunk really deleted. A stand-in VC3D command reads a chunk through the relay and writes two markers, one for a chunk the bucket holds and one for the deleted chunk: `s3relay` must list only the first as affected, delete it, keep the true one, and exit 4. A relay that passed false 404s on, or a check that deleted true markers, fails the test.
- **The live run above** shows the relay passing a real `NoSuchKey` 404 through as a 404, and real objects through at their full size, against the real bucket.
- The rate of false 404s is not steady: on 8 October 2026 one cloud machine got them on 102 of 316 GETs at 32 workers, and on 12 October none in 40 fresh ranged GETs ([log](../logs/2026-10-12-upstream-reports.md)). A run with no false 404 shows only that the relay passes traffic through.

Claim label: Sourced fact, for the live run of 2026-10-24 and the measurements of 8 and 12 October 2026 cited above.

## Commands and options

### `python -m kit s3relay`

```
usage: python -m kit s3relay [-h] [--port PORT] [--for SECONDS]
                             [--ledger LEDGER] [--json]
                             url [COMMAND ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `url` | required | The remote zarr VC3D should read, `s3://BUCKET/KEY` or an `https://` URL. An `s3://` URL is served from `https://BUCKET.s3.amazonaws.com` |
| `--port PORT` | none | Listen on this port. By default one is chosen from the URL's origin (the first free of 16 ports from 20000 plus the origin's FNV-1a hash modulo 20000), so repeated runs give VC3D the same URL and reuse one cache folder |
| `--for SECONDS` | none | Without a command: stop after this many seconds instead of at Ctrl-C |
| `--ledger LEDGER` | `work/vc3d-empty` | With a command: the folder of the cache check's records (which markers were found true, which were deleted and when) |
| `COMMAND` | none | A command to run through the relay, written after `--` so its own options are not read as `s3relay`'s. Every spelling of `url` in its arguments is replaced by the relay's URL; a command that does not contain it runs unchanged, with a note |
| `--json` | off | Print the report as one JSON object; progress lines go to stderr |

### `python -m kit vc3dcache`

```
usage: python -m kit vc3dcache [-h] [--all] [--no-delete] [--recheck]
                               [--no-relay] [--root ROOT] [--ledger LEDGER]
                               [--json]
                               [url]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `url` | none | The remote volume's URL as VC3D was given it (the bucket URL, not the relay's). Required unless `--all` |
| `--all` | off | List every volume folder in the cache with its marker count, and its URL when a record in `--ledger` names it; checks nothing |
| `--no-delete` | off | Report false markers without deleting them |
| `--recheck` | off | Ask again about markers already recorded as true |
| `--no-relay` | off | Skip the folders of relay URLs; check only the spellings of `url` |
| `--root ROOT` | none | VC3D's remote cache folder. By default found the way VC3D finds it: `root` in `cache.json`, else `remote_cache_dir` in `VC3D.ini` (both in `VC3D_CONFIG_DIR`, else `~/.VC3D`), else `/volpkgs/remote_cache` or `/ephemeral/remote_cache`, else `~/.VC3D/remote_cache` ([vc3d-cache](vc3d-cache.md)) |
| `--ledger LEDGER` | `work/vc3d-empty` | The folder of the check's records |
| `--json` | off | Print the report as one JSON object; progress lines go to stderr |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `VC3D_CONFIG_DIR` | `~/.VC3D` | Where `cache.json` and `VC3D.ini` are read to find the cache root, as VC3D reads them |
| `HTTPS_PROXY` | unset | Used for the relay's and the check's requests to the bucket |
| `KIT_HTTP_REUSE` | `1` | `0` makes the cache check open a new connection per request ([keepalive](keepalive.md)) |

## Python API

```python
from kit import vc3dfix
report = vc3dfix.run_through(URL, ["vc_render_tifxyz", "--volume", URL, ...])
print(report["returncode"], report["affected"])
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `forms(url)` | list of str: `url` without trailing slashes, then for an S3 bucket its `s3://`, global https and (for `vesuvius-challenge-open-data`) us-east-1 https forms, without repeats | Nothing | Any other URL comes back alone. Constants: `OPEN_DATA` (`vesuvius-challenge-open-data`), `OPEN_DATA_REGION` (`us-east-1`) |
| `swap(args, url, given)` | `(new_args, count)`: `args` with every form of `url` replaced by `given`, and how many were replaced | Nothing | Longest forms first, so a URL that extends another is replaced whole |
| `serve(url, port=None, seconds=None, opener=None, say=print)` | dict `url`, `relay_url`, `stats` (the relay's counts) | `s3relay.RelayError` for a bad URL or no free port | Runs until Ctrl-C, or for `seconds`. `say` gets the lines to print |
| `run_through(url, command, port=None, ledger=DEFAULT_LEDGER, env=None, root=None, opener=None, say=print)` | dict `url`, `relay_url`, `command` (as run), `swapped`, `returncode`, `stats`, `affected` (markers deleted since the run began), `cache` (`Guard.summary`) | `s3relay.RelayError`; `vc3d_cache.CacheError`, before anything runs, for a `cache.json` VC3D would refuse | `DEFAULT_LEDGER` is `work/vc3d-empty`. A command that cannot start gets `returncode` 127 |
| `format_run(r)` | str: the text report of `run_through` | `KeyError` for a dict of another shape | |
| `check_cache(url, delete=True, recheck=False, relay=True, root=None, ledger=DEFAULT_LEDGER, env=None, opener=None, progress=None)` | dict `cache_root`, `volumes` (one `vc3d_cache.check` report per folder, with `folder` and `given`), `false_found`, `false_deleted`, `unknown` (counts) | `vc3d_cache.CacheError` for a `cache.json` VC3D would refuse | The folder of `url` as given is always checked; other forms and relay URLs only when their folder exists |
| `list_cache(root=None, ledger=DEFAULT_LEDGER, env=None)` | dict `cache_root`, `volumes`: `folder`, `markers`, `url` (from a record, or None) | `vc3d_cache.CacheError` as above | Reads only |
| `format_check(r)` | str: the text report of `check_cache` | `KeyError` for a dict of another shape | |
| `format_list(r)` | str: the text report of `list_cache` | `KeyError` for a dict of another shape | |
| `build_parser(p, action)` | `p`, with the options of `s3relay` or (any other `action`) `vc3dcache` | Nothing | `kit/cli.py` calls it for both commands |
| `cmd_s3relay(args)` | exit code, as under Outputs | Nothing it does not print | `AFFECTED_EXIT` is 4 |
| `cmd_vc3dcache(args)` | exit code, as under Outputs | Nothing it does not print | |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Volume URL | `s3://BUCKET/KEY` or `http(s)://HOST/PATH` of a zarr store's root | Give the URL exactly as VC3D is or was given it: VC3D names its cache folder by the URL's text, so `s3://` and `https://` spellings get different folders. `vc3dcache` checks the other spellings too |
| VC3D's cache | `ROOT/NAME-HASH/` with `.empty` marker files | Found as under `--root`; layouts in [vc3d-cache](vc3d-cache.md) |
| Records | `LEDGER/NAME-HASH.json` | Written by earlier checks; a marker recorded as true is not asked again unless `--recheck` |

## Outputs

`s3relay` without a command prints `relay for ORIGIN on http://127.0.0.1:PORT`, `give VC3D this URL: RELAY_URL` and `stop with Ctrl-C` (or `stops after N s`), and when it stops `relay stopped: N requests, N false 404s asked again, N given up`. With a command it prints `running: COMMAND`, the command's own output, then the report shown in Quick start; when markers were affected it adds `N chunks the run may have read as zeros (their false markers are deleted now): run it again` and up to 20 of them. `--json` prints the `run_through` or `serve` dict.

`vc3dcache` prints `VC3D remote cache: ROOT`, one line per folder (`FOLDER: N empty-chunk markers, N known true, N checked: N false (N deleted), N true, N unknown`, or `no cache folder (VC3D has not read URL)`), and `N false markers found, N deleted, N unknown`. `--all` prints one line per folder and the hint `check one with: python -m kit vc3dcache URL (the URL VC3D was given)`. `--json` prints the `check_cache` or `list_cache` dict.

| Exit code | Meaning |
| --- | --- |
| `0` | `vc3dcache`: no false marker is left and none is unknown. `s3relay` alone: stopped. `s3relay` with a command: the command succeeded and read no chunk through a false marker |
| `1` | `vc3dcache --no-delete` found false markers and left them |
| `2` | A usage error, a URL the relay cannot serve, no free port, or a `cache.json` VC3D would refuse |
| `3` | `vc3dcache`: some markers stay unknown (S3 answered neither present nor `NoSuchKey` within the tries, or the request cap was reached) |
| `4` | `s3relay` with a command: the command exited 0, but chunks it may have read as zeros were found and repaired: run it again |
| other | `s3relay` with a command: the command's own nonzero exit code; 127 when it could not start |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit s3relay: MESSAGE`, exit code 2 | The URL is not `s3://` or `http(s)://`, no candidate port was free (or `--port` was taken), or a `cache.json` VC3D would refuse; MESSAGE says which ([s3relay](s3relay.md), [vc3d-cache](vc3d-cache.md)) | Fix the URL, free the port or pass another `--port`, or fix `cache.json` |
| `kit s3relay: cannot run NAME: ERROR`, exit code 127 | The command after `--` could not start (not on `PATH`, not executable) | Give the full path of the tool |
| `note: the command does not contain URL; it runs unchanged` | No spelling of the volume URL was in the command, so it does not read through the relay | Name the volume URL in the command exactly, or give `s3relay` the URL the command uses |
| `kit vc3dcache: give the volume's URL, or --all`, exit code 2 | Neither a URL nor `--all` | Give the URL VC3D was given |
| `kit vc3dcache: MESSAGE`, exit code 2 | A bad URL, or a `cache.json` VC3D would refuse (MESSAGE names the file) | Fix the URL or the file |
| `cache check failed: ERROR` in the `s3relay` report | The check around the run could not read the volume's headers or the cache; the run itself went on | Read ERROR; run `python -m kit vc3dcache URL` once the network works |
| Exit code 3 and `N unknown` | S3 kept answering a false 404, or the 4,000-request cap was reached | Run `vc3dcache` again later; nothing unknown is deleted |
| `no cache folder (VC3D has not read URL)` for a volume VC3D did read | VC3D was given another spelling, or uses another cache root | Give the exact URL from the VC3D command line, or `--root`; `--all` lists the folders there |

## How it works

1. **Spellings** (`forms`). A bucket URL is written three ways; VC3D's cache folder is named by the text it was given, so both commands work over every spelling.
2. **The relay** (`kit/s3relay.py`). Started on the port chosen from the origin, it serves the bucket's paths under `http://127.0.0.1:PORT/`. False 404s are asked again on new connections (10 tries in all, `s3retry.TRIES`), a 404 is passed on only with `NoSuchKey`, and a key that never answers is sent as 503, which VC3D does not cache as empty.
3. **The run** (`run_through`). The cache root is resolved first, so a bad `cache.json` stops the command before it runs. `Guard.before()` repairs the markers earlier runs left in the relay URL's folder, the command runs with its URL swapped, and `Guard.after()` repairs what it left and lists every marker deleted since `before()`, by this check or by another process ([vc3d-cache](vc3d-cache.md)).
4. **The check** (`check_cache`). For each folder that exists, `vc3d_cache.check` asks the bucket (at the bucket URL, not the relay's) about each marker not already recorded as true, with the rule of [s3retry](s3retry.md), and deletes the false ones.

## Cost and time

The live run in Quick start made 3 requests to the bucket (a small header, one 2 MB chunk and one missing key); its time was not measured. The tests (local servers) ran in about 17 s on 2026-10-24, with `tests/test_vc3d_cache.py`. A cache check takes at least a twentieth of a second per marker asked about (20 requests a second). It is CPU and network only and rents nothing.

## For agents

- **Command:** `python -m kit s3relay VOLUME_URL --json -- VC3D_COMMAND ...`; after a run made without it, `python -m kit vc3dcache VOLUME_URL --json`.
- **Parse:** `s3relay`: `returncode`, `affected` (chunks the run may have read as zeros), `stats.false_404`, `stats.gave_up`, `cache.error`. `vc3dcache`: `false_found`, `false_deleted`, `unknown`, and per folder in `volumes`.
- **Rerun:** Safe. A rerun deletes only markers that are still false, and asks again only about unknown ones.
- **Success:** Exit code 0, with `affected` empty.
- **Not a pass:** Exit code 4 (the output may have holes: run the command again); exit code 3; a run whose command did not contain the URL (`swapped` 0); a render made with VC3D given the bucket URL directly and no `vc3dcache` check afterward.
- **Go-ahead:** Nothing.
- **Never:** Delete a marker the check found true; trust a render made before a repair that listed its chunks.

## Tests

```bash
python -m unittest tests.test_vc3dfix -v
```

`tests/test_vc3dfix.py` (10 tests) checks the URL spellings and the swap; `run_through` and the command line with a stand-in VC3D command against a local S3-like server that answers false 404s (the command gets the relay URL, the false marker is listed as affected and deleted, the true one kept, exit code 4); `check_cache` finding and repairing the relay URL's folder, `--no-delete`, and `list_cache`; a `cache.json` VC3D would refuse stopping both commands with exit code 2; `serve` printing the relay URL; and bad URLs as usage errors. They use local servers only. Not covered by the tests: the real bucket (see the live run in Quick start), a real VC3D binary, and Ctrl-C.

## History

- 2026-10-24: first version, `python -m kit s3relay` and `python -m kit vc3dcache` (`HASH1`).

## Related

- [s3relay](s3relay.md): the relay itself.
- [vc3d-cache](vc3d-cache.md): finding VC3D's cache, checking its markers, `Guard`.
- [s3retry](s3retry.md): the false-404 rule.
- [VC3D and S3's false 404s](../vc3d-false-404.md): the how-to.
- [The upstream reports log](../logs/2026-10-12-upstream-reports.md): the measurements, villa issue #2058 and draft PR #2060.
