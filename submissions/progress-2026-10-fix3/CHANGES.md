# AutoPipeline 0.1.3: what changed since 0.1.2

The earlier releases stay as they were: AutoPipeline 0.1.0 is submission `progress-2026-10` (branch `submission/progress-2026-10`, commit `faada83287d39bbd4c7fd88c7ab0e75f3f1ff284`), 0.1.1 is `progress-2026-10-fix1` (commit `153413691ec2ca794acdb3bf5784c0882a43e228`) and 0.1.2 is `progress-2026-10-fix2` (commit `143c54b54804e17acbfdcf032217e6b3964f6ef4`). This package, `progress-2026-10-fix3` (15 October 2026), is the whole of AutoPipeline again with these changes. No earlier result changed.

## The default reader is Reader v2

`ink.models` now defaults to `reader-v2`, Domenico Russo's fine-tune of `ink_9um`, in place of `ink_9um` seed 42. On the 640 px windows of densest labelled ink in PHerc0841's w00 and ag896, seed 42 ranked 8th of nine released readers (Model output, 9 October 2026; one of the nine, Hecate, may have trained on PHerc0841). Before changing the default I ran the w00 benchmark again on one render with three readers: Reader v2, TAUIL-Abd-Elilah's d9v2 and seed 42 (Model output, development data, 15 October 2026; whole map, AUC forward, reversed and shuffled):

| Reader | Forward | Reversed | Shuffled |
| --- | --- | --- | --- |
| Reader v2 | 0.8752 | 0.5659 | 0.5539 |
| d9v2 | 0.8766 | 0.5404 | 0.5295 |
| `ink_9um` seed 42 | 0.7479 | 0.5012 | 0.4851 |

The rule was fixed before the run. In short, Reader v2 becomes the default if it beats seed 42 by 0.01, d9v2 instead if it leads Reader v2 by 0.01, and seed 42 stays otherwise; as written, it left two cases undecided, and neither arose. d9v2 led by 0.0014, so the default is Reader v2. Seed 42 repeated its 9 October numbers, and each reader matched its earlier score on the published surface volume's densest-ink window within 0.0004. Reader v2's reversed control is higher than d9v2's. PHerc0841 is in none of the three readers' training data, but w00's labels had been scored before and these numbers chose the default, so they are development data, not a held-out test. Reader v2 was trained on some published segments, PHerc0139's w045 among them, so its scores there are not held out. `ink_9um`, and with it d9v2, trained on w045's 2.4 µm render, so none of the three readers is held out on w045.

A plan that names its models keeps them. A plan that does not now resolves `reader-v2`, so its plan and digest differ from one made by 0.1.2; to repeat an older run, name `ink_9um-seed42`.

Files: `autopipeline/kit/autopipe.py`, `autopipeline/README.md`, tests in `autopipeline/tests/test_autopipe.py` and `test_autopipe_monitor.py`.

## Upright canvases: a fallback, and a record in the report

`ink.orient` (turn each trace's render upright before ink) stays opt in. With Reader v2 on my own trace of w00 it scored 0.911 against 0.851 as rendered, but a sham turn 45 degrees off upright scored 0.872, and upright minus sham was not clearly above zero (+0.039, 95% interval -0.005 to 0.091). The turn also raised the reversed control, from 0.476 to 0.709, so forward minus reversed fell from 0.375 to 0.202 (Model output, development pixels, one trace, 15 October 2026). With `ink_9um` seed 42 on 13 October the turn gained 0.256.

- **Fallback.** `"ink": {"orient": {"fallback": "unturned"}}` inks a trace's render as it is when its turn fails (for example, without numpy, tifffile and zarr), instead of leaving that trace uninked. Each map then carries a warning, and so does an ensemble made from them. Without `fallback`, a failed turn leaves the trace uninked, as before, so plans written for 0.1.2 behave the same.
- **Report.** `report.json` now gives the outcome for each surface a plan asked to turn: turned, with its angle and mirror; not turned, and why; or failed, and then inked as rendered or left uninked.

Files: `autopipeline/kit/autopipe.py`, tests in `autopipeline/tests/test_autopipe.py`.

## Faster remote reads

The ideas come from SuperOptimizer's [ufsm](https://github.com/SuperOptimizer/ufsm) (its pooled connections and grouped range reads, at commit [`75e063b`](https://github.com/SuperOptimizer/ufsm/tree/75e063b64495f88cb09286c6d35fed319ac622ef)). ufsm has no licence for its own code, so these are my own implementations and nothing is copied.

- **Kept connections.** The zarr readers that go through `kit/vc3d_audit.py`'s HTTP store, the voxel reader and the chunk audit among them, keep finished HTTP connections in a small pool per server and reuse them, from any thread, instead of opening a new connection, and a new TLS handshake, for every chunk. A request on a kept connection that the server closed while it sat idle is sent again on a new connection, and the other connections kept for that server are dropped. `KIT_HTTP_REUSE=0` turns it off. On a direct connection it halved the time of two 64-chunk reads of public PHerc0139 volumes (4.35 to 2.17 s and 1.89 to 0.84 s; medians of 4 rounds, 15 October 2026).
- **Box reads are not paced.** Reading a box of voxels no longer waits under the chunk audit's 20 requests per second. On the same direct connection, with kept connections, that made a 64-chunk box of PHerc0139's surface prediction 1.76 times faster (3.82 to 2.17 s).
- **Sharded zarr v3 arrays.** The voxel reader used to refuse sharded arrays. It now reads them through each shard's index (CRC32C checked) and, over HTTP, joins the inner chunks a box needs from one shard into merged range reads (gaps up to 64 KiB, reads up to 2 MiB). The whole full-resolution level of a published PHerc0139 ink label map read the same voxels as zarr-python 3.4.1, with one merged range read after the shard's index instead of one read for each of its 91 present inner chunks.

Files: `autopipeline/kit/keepalive.py` (new), `autopipeline/kit/vc3d_audit.py`, `autopipeline/kit/vc3d_region.py`, tests in the new `autopipeline/tests/test_keepalive.py`.

## The Docker build and the AppImage download work again

0.1.2's Dockerfile and README downloaded one named AppImage from villa's `latest` release. villa replaces that release on every build and deletes the previous build's file, so by 15 October the pinned name answered 404 and a default `docker build` stopped at the download.

- **`scripts/get_vc3d.py`** (new, standard library only) asks GitHub's API which `*-linux-x86_64.AppImage` the `latest` release holds now, downloads it, checks it against the sha256 GitHub publishes for it and keeps a matching file that is already there. While villa is uploading a new build the release is missing for a few minutes, so it tries again a few times over about three minutes. `python3 scripts/get_vc3d.py stable` takes the `stable` release, and `URL --sha256 HEX` takes one pinned file. Set `GITHUB_TOKEN` if GitHub's limit of 60 anonymous API requests an hour gets in the way.
- **Dockerfile.** It now gets the AppImage through `scripts/get_vc3d.py`, refuses a file with no sha256 to check, and records the file's name, address and sha256 in `/opt/vc3d/appimage.json`. A GitHub token can be passed as a BuildKit secret (`--secret id=github_token,env=GITHUB_TOKEN`), which stays out of the image. Built and run on 15 October 2026 on x86_64 with villa's AppImage `5432721`: the default command found all five VC3D tools, passed the self-test and printed DEMO PASS. That machine was behind a proxy, so a test-only layer under the image added the proxy's certificate and https apt sources, and the build read GitHub's release listing from a saved copy. On another machine the same day, the script's lookup against GitHub's API found the same file, and its sha256 matched the one GitHub publishes.
- **README and `docs/vc3d-headless.md`.** Their AppImage commands use the script too, and the README's install check runs in a subshell, so the next command still finds `scripts/`.

Files: `autopipeline/scripts/get_vc3d.py` (new), `autopipeline/Dockerfile`, `autopipeline/.dockerignore`, `autopipeline/.gitignore`, `autopipeline/README.md`, `autopipeline/docs/vc3d-headless.md`, tests in the new `autopipeline/tests/test_get_vc3d.py`.

## Smaller changes

- **TIFF predictors.** The TIFF reader now decodes the floating-point predictor, which the catalog's newer tifxyz grids use, and the horizontal predictor on float samples, which older ones use, such as two of PHerc0841's three. Files: `autopipeline/kit/vc3d_io.py`, tests in `autopipeline/tests/test_vc3d_io.py`.

## Packaging

- Version 0.1.3. File: `autopipeline/pyproject.toml`.
- The ink Space carries `kit/keepalive.py`, which the remote readers now import. File: `autopipeline/space/inkspace.py`.
