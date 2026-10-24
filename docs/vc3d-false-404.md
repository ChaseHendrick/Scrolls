# VC3D and S3's false 404s

How to keep VC3D from rendering holes of zeros when it reads a remote scan from S3, and how to repair a cache that already has them. Two commands do it, `python -m kit s3relay` and `python -m kit vc3dcache` ([their page](tools/vc3dfix.md)); both are standard library Python and run on any machine VC3D runs on.

## The problem

VC3D (villa's Volume Cartographer 3D: the app and the `vc_*` command line tools) reads a remote zarr volume chunk by chunk and keeps each chunk in a persistent cache. When the server answers 404, VC3D writes an **empty-chunk marker**, a `.empty` file in that cache, and from then on reads the chunk as zeros without asking again.

S3 sometimes answers 404 for keys it holds, with the error code `NoSuchBucket` instead of `NoSuchKey`: a **false 404**. Measured from one cloud machine on 8 October 2026 ([log](logs/2026-10-12-upstream-reports.md)):

- 102 of 316 GETs at 32 workers, 16 of 80 at 1 worker, and 19 of 60 separate curl processes got a false 404; 0 of 60 requests on one reused connection and 0 of 1,580 HEAD requests did.
- A fresh crop render of PHerc0139 w035 got 4 false empty markers and 27.7 % zero samples, and exited 0.
- Deleting the 8 false markers and rendering again gave 0.03 % zeros, bit for bit the same as a clean render.

It was not reproduced on 12 October (40 of 40 fresh ranged GETs were fine), so it comes and goes. The failure is silent: the render looks like a scan with a few dark blocks, and nothing in VC3D's output says a chunk was missing. It was reported to villa as [issue #2058](https://github.com/ScrollPrize/villa/issues/2058), with a proposed fix in draft [PR #2060](https://github.com/ScrollPrize/villa/pull/2060).

## 1. Run VC3D through the relay

Put `python -m kit s3relay URL --` in front of the VC3D command, with the volume URL as the command already names it:

```bash
U=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr
python -m kit s3relay $U -- vc_render_tifxyz ... $U ...
```

The relay listens on `127.0.0.1`, asks S3 again after a false 404 (10 tries in all), and passes a 404 on only when S3 says `NoSuchKey`. The command runs with `$U` swapped for the relay's URL. Before and after the run, the command checks VC3D's empty-chunk markers for that URL against the bucket and deletes the false ones. At the end it prints the relay's counts, the markers it repaired, and the command's exit code.

Exit code 4 means the command succeeded but read some chunks through false markers left by earlier runs or by another process: those markers are deleted now, so run the command again.

For the VC3D app, start the relay alone and give the app the URL it prints:

```bash
python -m kit s3relay $U
```

Stop it with Ctrl-C after the app has finished. The relay's port comes from the bucket's address, so the app gets the same URL and the same cache folder each time.

## 2. Repair a cache filled without the relay

If VC3D already read a remote volume without the relay, check its markers with the URL VC3D was given:

```bash
python -m kit vc3dcache $U
python -m kit vc3dcache --all
```

The first line asks the bucket about every marker in the folders VC3D may have made for that volume (its `s3://` and `https://` spellings, and the relay's URLs) and deletes the false ones; a marker found true is remembered and not asked about again. The second lists every volume folder in the cache with its marker count.

VC3D finds its cache folder in this order, and so does the kit (villa main, read 24 October 2026): `root` in `cache.json`, then `remote_cache_dir` in the `[viewer]` section of `VC3D.ini`, both in `VC3D_CONFIG_DIR` (else `~/.VC3D`); then `/volpkgs/remote_cache` or `/ephemeral/remote_cache` when that folder exists; then `~/.VC3D/remote_cache`. `python -m kit vc3dcache --all` prints the folder it found on its first line.

## What the commands do not do

They do not change VC3D or the data, and they say nothing about what a render shows: a clean cache means only that no chunk VC3D holds as empty exists in the bucket. Downloading a volume first with [`kit fetch`](tools/fetch.md), which asks again after a false 404 itself, also avoids the problem, at the cost of the disk space.

## Pages

- [vc3dfix](tools/vc3dfix.md): both commands, every option, exit codes, and a live run on 24 October 2026.
- [s3relay](tools/s3relay.md), [vc3d-cache](tools/vc3d-cache.md), [s3retry](tools/s3retry.md): the modules behind them.
- [false404-relay](tools/false404-relay.md): a relay that replays false 404s on purpose, to test a fix.
