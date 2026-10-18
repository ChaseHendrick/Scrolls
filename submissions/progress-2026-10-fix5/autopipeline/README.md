# AutoPipeline: villa's pipeline from a released scan to a scored ink map

![Concept illustration of a continuous papyrus surface traced in copper and flattened into a grid.](https://raw.githubusercontent.com/ChaseHendrick/Scrolls/b3190d92e441882c63ea8f3ed342ba1c05154efa/docs/assets/autopipeline-readme-hero.webp)

*Concept illustration, generated with OpenAI image generation; not a scan, model output or recovered text. [Artwork provenance](https://github.com/ChaseHendrick/Scrolls/blob/b3190d92e441882c63ea8f3ed342ba1c05154efa/docs/assets/README.md).*

Version **0.1.5** adds interactive monitor controls, stricter synthetic-demo checks and a cache-repair timestamp correction. [Changes since 0.1.4](../CHANGES.md).

AutoPipeline runs villa's pipeline from a released scan to a scored ink map, with checks that can fail at every step. It drives VC3D's command-line tools and villa's ink detection end to end. A rule written down before the run replaces each choice a person usually makes by eye, and every check it runs has a control. In the code and on the command line it is called `autopipeline`.

It does not replace villa or VC3D. It calls their tools (`vc_gen_umbilicus`, `vc_grow_seg_from_seed`, `vc_tifxyz_selfcross`, `vc_flatten`, `vc_render_tifxyz`) and villa's ink inference, then checks what they return.

## Why

The [2026 open problems](https://scrollprize.org/2026_open_problems) page says: "The pipeline works, but not without a person checking its output at almost every stage." It also asks for "reproducible streaming pipelines". I wanted to see how many of those checks could be written as fixed rules that run on their own.

## What it does

| Step | Tool | Rule |
| --- | --- | --- |
| Inputs | Scan, surface prediction and normal grids from the open-data catalog | Zarr headers of every level are read and frozen in the plan |
| Umbilicus | The catalog's, or `vc_gen_umbilicus` on the normal grids every 500 slices | Outliers dropped by a robust line fit |
| Seed points | Points on the surface prediction, on papyrus in the CT, 1.5 mm or more from the umbilicus, 2 mm apart | Each is checked against the prediction and the CT |
| Tracing | `vc_grow_seg_from_seed` with the published normal grids | A trace made without normal grids is refused |
| Surface checks | tifxyz validity as VC3D loads it, `vc_tifxyz_selfcross`, CT contrast across the surface at 5 windows, normal direction against the umbilicus, sheet switches between wraps | A fixed accept or reject rule; every check's result is kept |
| Flattening | `vc_flatten` | Kept only if the 95th percentile stretch error is at most 0.25, the 95th percentile shear at most 20 degrees, and the area ratio between 0.8 and 1.25 |
| Surface volume | Missing-chunk check under the surface, then `vc_render_tifxyz` with `--flip-normals` | Refused above 5 % missing chunks (or trimmed, opt in); layer order checked against the umbilicus |
| Ink detection | Each model on the layers as rendered, reversed, and shuffled | The reversed and shuffled maps always run |
| Scoring | Pixel AUC against published ink labels | Reversed and shuffled maps scored beside the forward map |
| Triage (optional) | Bullo27's text-row periodicity score ([first-letters-survey](https://github.com/Bullo27/first-letters-survey), ported in `kit/rowscore.py`) on each model's maps and their mean | Reversed and shuffled maps scored beside; the surfaces ranked as a reading order, not a verdict |

Each run lives in one folder. `plan.json` holds every setting and every resolved input under a SHA-256 digest, so a changed threshold means a new folder, never an edit to a run whose results have been seen. `state.json` records each step. A finished step is not repeated, so an interrupted run resumes where it stopped. Each failure is labelled as either the tool's own decision or an infrastructure problem (a fetch, a 404, a lost machine).

S3 sometimes answers 404 for chunks it holds ([villa #2058](https://github.com/ScrollPrize/villa/issues/2058)). The downloads here treat a chunk as missing only on S3's `NoSuchKey`, and the missing-chunk check asks again.

## Results

All numbers are model output on public data. None of this is a reading.

**PHerc0841 w00, from the released scan and the published segment to scores (9 October 2026, Modal).** The run took 593 s from start to scores: 344 s on 8 CPU cores, then 249 s on one L4.

- The rendered surface volume matched the published one inside the densest-ink window, with correlation 0.9999984. The two controls (layers reversed, window moved 64 px) gave 0.087 and 0.045.
- `ink_9um` seed 42, whole map: AUC 0.7479 forward, 0.5012 reversed, 0.4851 shuffled. The same model on the published surface volume gave 0.7479 and 0.501.

**The default reader (15 October 2026, Modal).** The same run again with three readers on one render, 1163 s on 8 CPU cores and one L4. Whole map, AUC forward, reversed and shuffled:

| Reader | Forward | Reversed | Shuffled |
| --- | --- | --- | --- |
| Reader v2 | 0.8752 | 0.5659 | 0.5539 |
| d9v2 | 0.8766 | 0.5404 | 0.5295 |
| `ink_9um` seed 42 | 0.7479 | 0.5012 | 0.4851 |

Reader v2 is now the default (`ink.models`). Before the run I fixed the rule. In short, Reader v2 becomes the default if it beats seed 42 by 0.01, d9v2 instead if d9v2 leads Reader v2 by 0.01, and seed 42 stays otherwise; as written, it left two cases undecided, and neither arose. d9v2's lead was 0.0014. Seed 42 repeated its 9 October numbers to four decimals, and each reader matched its earlier score on the published surface volume's densest-ink window within 0.0004. PHerc0841 is in none of the three readers' training data, but w00's labels had been scored before and these numbers chose the default, so they are development data, not a held-out test.

**The checks reject what they should** (PHerc0139 and PHerc0841, 4 CPU cores):

- One run stopped when both traces had CT contrast at 1 of 5 windows or fewer.
- Another run rejected a trace whose normals pointed toward the umbilicus.
- The missing-chunk check found 10 to 24 % of chunks missing under three traces. That result is why the 5 % rule exists.
- `vc_tifxyz_selfcross` found 175 self-intersections in the published w00 segment. For a published segment this is recorded and the run goes on, because its labels sit on its grid.

**Umbilicus estimate.** Against the catalog's umbilicus on three 9.362 µm scans, the median distance was 112, 210 and 428 voxels (about 1, 2 and 4 mm). The scan centre was 849, 166 and 795 voxels off.

## Limits

- The scored end-to-end run started from a published, hand-traced segment. Seed points and tracing are automated and tested, but my own traces have no held-out ink score yet. On w00's labelled pixels, `ink_9um` scored AUC 0.618 on my own trace's render against 0.798 for the published segment's map. Most of that gap was the render's in-plane rotation: turning it upright before ink (the `ink.orient` setting) scored 0.874 on the same pixels (seed 42, 13 October 2026). That is development data scored before, not independent confirmation. The same test with Reader v2 on 15 October: 0.851 as rendered, 0.911 upright, but 0.872 for a sham turn 45 degrees off upright, and upright minus sham was not clearly above zero (+0.039, 95% interval -0.005 to 0.091), so `ink.orient` stays opt in. The turn also raised the reversed control from 0.476 to 0.709, so forward minus reversed fell from 0.375 to 0.202; that is an observation, not part of the rule.
- Reader v2 was trained on some published segments, PHerc0139's w045 among them, so its scores there are not held out. `ink_9um`, and with it d9v2, trained on w045's 2.4 µm render, so none of the three readers is held out there.
- Traces grown from seed points are small patches. Whole-winding tracing is still the open problem.
- The flattening limits are my choice. The prize rules give no number.
- The measured runs were launched from a Mac and ran on Modal. A native one-click Mac run has not been shown.
- Code comments and a few help texts cite notes and Modal runners in my development repository (paths under `docs/` and `scripts/vc3d/modal_*.py`). Those are not part of this release. This README, `AGENTS.md` and the two guides in `docs/` are its documentation.

## Install and use

You need Python 3.11 or newer (zarr 3 needs it). I tested these steps on Ubuntu 24.04 (x86_64) on 12 October 2026, from a fresh shell. I have not tested the Mac steps yet.

```bash
cd autopipeline                            # this folder
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e .                 # numpy, tifffile, zarr 3, scipy
python scripts/demo_synthetic.py           # every step on a synthetic scroll with stand-in VC3D tools; prints DEMO PASS
(cd /tmp && python -m kit autopipeline defaults)   # the install check: works from any folder
```

The demo runs from this folder whether or not the install worked; the last line is what shows the install did. The demo and the self-test below write to temporary folders under `/tmp` and print their paths.

Keep the `-e`: the ink runner and the guides live in `scripts/` and `docs/` beside the code. Runs and caches go to `work/` in this folder, including the unpacked AppImage (about 370 MB); set `KIT_HOME` to keep them somewhere else (each new `KIT_HOME` unpacks the AppImage again). The folder's `.gitignore` keeps `work/`, `.venv/`, build folders and the AppImage out of git.

**VC3D's tools.** On Linux (x86_64), villa's release AppImage has all five. kit unpacks it on first use (no FUSE needed) and starts each tool through its `AppRun`:

```bash
APPIMAGE="$(python3 scripts/get_vc3d.py)" && export VC_APPIMAGE="$APPIMAGE"   # villa's current AppImage, checked
python -m kit vc3d which                   # the five tools, and the step that runs each
python -m kit vc3d selftest                # renders and traces synthetic volumes with no display: PASS in about 2 s
```

Keep the AppImage file, or after the first run point `VC_APPIMAGE` at the unpacked copy, `work/vc3d/appimage/<name>/squashfs-root`. Export `VC_APPIMAGE` again in every new shell.

villa rebuilds its [`latest` release](https://github.com/ScrollPrize/villa/releases/tag/latest) with every build and deletes the one before, so the file name and checksum change and an old link stops working. `scripts/get_vc3d.py` asks GitHub's API which `*-linux-x86_64.AppImage` the release holds now, checks the download against the sha256 GitHub publishes for it, and keeps a file that is already there and matches. `python3 scripts/get_vc3d.py stable` takes the `stable` release instead, which passes the self-test but has no `vc_tifxyz_selfcross` or `vc_gen_umbilicus`; `python3 scripts/get_vc3d.py URL --sha256 HEX` takes one pinned file. Set `GITHUB_TOKEN` if GitHub's limit of 60 anonymous API requests an hour gets in the way. If you unpack the AppImage yourself, set `VC_APPIMAGE` to the `squashfs-root` folder. Its `usr/bin` tools need the AppImage's own loader and crash (exit 139) when started directly.

On a Mac with Apple Silicon, the same release has a dmg. Drag `VC3D.app` to Applications and run `xattr -dr com.apple.quarantine /Applications/VC3D.app` (the app is not notarized). kit looks in `/Applications/VC3D.app/Contents/MacOS`. A villa build from source works too: set `VC_BIN` to its `build/bin`.

There is also a Dockerfile: `docker build -t autopipeline . && docker run --rm autopipeline` runs the tool check, the self-test and the demo. AutoPipeline 0.1.3's image was built and run on 15 October 2026 on x86_64 with villa's AppImage 5432721, and all three passed; 0.1.4's and 0.1.5's images have not been built. That machine was behind a proxy, so a test-only layer added the proxy's certificate and https apt sources under the image, and the build read GitHub's release listing from a saved copy. On another machine the same day, the script's lookup against GitHub's API found the same file, and its sha256 matched the one GitHub publishes. The self-test and the demo render local volumes only. With every VC3D build since villa ba2bf75 (12 October 2026), 4eecd08 and 5432721 among them, 0.1.3's remote renders failed; 0.1.4 passes the URL as `--volume` on those builds, as villa's tutorial now does (see the [0.1.4 changes](https://github.com/ChaseHendrick/Scrolls/blob/603fe14633201d6769776519646dc19cf203009f/submissions/progress-2026-10-fix4/CHANGES.md)); a full remote render with it has not yet been run. The build takes the AppImage villa's `latest` release holds at that moment through `scripts/get_vc3d.py` and records its name and sha256 in `/opt/vc3d/appimage.json`; `docker build --no-cache` fetches it again, and the Dockerfile's comments say how to pin one file or pass a GitHub token. villa has no arm64 AppImage, so on arm64 (Docker on Apple Silicon) the image keeps villa's older container tools, and the tool check reports `vc_tifxyz_selfcross` and `vc_gen_umbilicus` missing.

**Ink detection** needs villa's `vesuvius` package and torch (Python 3.14) in an environment of its own; set `KIT_INK_PYTHON` to its `python`. Without it, a run stops at ink and writes a job file (`modal-job.json`); on a machine with a GPU, set `KIT_INK_PYTHON` and `KIT_AUTOPIPE_DEVICE=cuda` and run the same folder again: the run then does ink, scores and the report. The default reader is Reader v2 (`reader-v2`); a plan's `ink.models` can name others, such as `d9v2` or `ink_9um-seed42`, and the `fetch_model` tool downloads the known ones with their checksums.

`KIT_AUTOPIPE_DEVICE` is the device ink is asked to use: `cpu` by default (which also hides CUDA GPUs from the ink engine), `cuda` or `cuda:N`, or `mps` with a TorchScript export of the checkpoint. Each model's ink record in `state.json` keeps the device asked for and the one the engine's output said it used, since an engine can pick another one itself.

```bash
python -m kit autopipeline defaults
python -m kit autopipeline plan PHerc0841 --settings '{"purpose": "benchmark", "segment": "0841-w00"}'
python -m kit autopipeline run work/autopipe/<folder> [--until render]
python -m kit autopipeline status work/autopipe/<folder>
```

A relative run folder is read from where runs are written (this folder, or `KIT_HOME`).

The measured runs above used my own Modal runner, which is not part of this release.

For agents, `python -m kit vc3d mcp` serves the same run as an MCP tool, next to the VC3D tools (`trace`, `render`, `flatten`, `check_surface`, `audit` and others). See [docs/vc3d-agents.md](docs/vc3d-agents.md) and [AGENTS.md](AGENTS.md).

Formats: OME-Zarr volumes and predictions, tifxyz surfaces, zarr surface volumes, TIFF ink maps, JSON records.

### Watch a run

```bash
python -m kit autopipeline run work/autopipe/<folder> --monitor          # a live page at http://127.0.0.1:8765/ while the run lasts
python -m kit autopipeline monitor work/autopipe/<folder> [--open]       # the same page for any run folder
python -m kit autopipeline monitor work/autopipe/<folder> --snapshot run.html   # one self-contained file
python -m kit autopipeline monitor work/autopipe/<folder> --text [--watch 5]    # the same run as text in a terminal
```

The page, AutoPipeline Monitor (AP Monitor on the browser tab and on a narrow screen), says what the run is doing now, shows the 11 stages with their times, each surface's checks, a 3D wireframe of its traced mesh that you can turn by dragging, its ink maps beside their reversed controls and any scores, and the tail of the run's log. `--text` prints the same run in a terminal, with each ink map and its reversed control drawn in characters on the same scale. It stays on your machine: the server listens on 127.0.0.1, it only reads the run folder, and the page loads nothing from the internet. A snapshot leaves out your folder's path and machine name, and shows any other full path by its last name only, but it holds the run's records and log lines, so do not share one of a scroll whose ink is not published. Every map and score on it is model output, not a reading.

The monitor's controls work with a keyboard or on a narrow screen:

- Choose a stage name, or **Inspect current / stopped stage**, to see its recorded status, timing, failure type and affected surfaces. Selecting a stage also filters the log. QA failures include a geometry-review next step; the monitor does not locate bad regions or repair surfaces. Use the official [VC3D tutorial](https://scrollprize.org/tutorial_VC3D) to inspect a surface against neighboring CT slices and check that it follows the same sheet before editing it.
- **Search log** jumps to the stage, event-type and text filters. The count says how many of the loaded tail lines match; it is not a search of the complete log history. **Clear filters** shows the whole loaded tail again and leaves every failure record intact. The newest tool log is shown separately, unfiltered, and may belong to another stage.
- **Pause viewer updates** holds the view still while you inspect it. It does not pause the pipeline. **Refresh now** loads one current summary, even while viewer updates are paused; **Resume viewer updates** restores polling. Filters stay selected through refreshes. A refresh times out after 10 seconds; a state older than 30 seconds cannot prepare or retain a resume command. Refresh successfully before preparing another one.
- **Find run files** lists the plan, state, report, score and event records under the displayed run folder, including missing or unreadable records. A recorded file is not a validation pass. Open these files locally; the monitor does not expose a raw-file download endpoint.
- **Prepare status command** and **Prepare resume command** fill a command box for review. **Copy command** copies it, or selects the text for manual copying if clipboard access is unavailable. Paste into a bash/zsh terminal with this package installed. Copying runs nothing. Resume is unavailable for an active or finished run, an unreadable state, a plan-rule refusal, or a stale/paused viewer. Fix an infrastructure failure before resuming; a handed-off ink stage still needs its configured model and GPU environment. Completed stages remain recorded.

Snapshots keep stage inspection and log filters, but disable live refresh and command preparation because the original run path is omitted. All controls preserve the existing headless CLI and summary JSON schema. The server still accepts only GET/HEAD requests and never writes run files.

## Tests

`python -m unittest discover -s tests`. `tests/test_autopipe.py` runs the whole chain on a synthetic scroll with stand-in VC3D tools.

The synthetic demo reports `DEMO PASS` only when its stage statuses match, both surfaces are accepted, and both fake ink runs exit successfully with nonempty forward, reversed and shuffled map files inside the run folder. A missing dependency or failed fake-model command produces `DEMO FAIL` with the relevant log location, even if orchestration recorded the ink stage as done. This checks installation and orchestration, not real VC3D geometry or ink-model accuracy.

`tests/test_autopipe_monitor_ui.py` exercises the actual generated page in a local Chromium browser, including failure filters, shell quoting, clipboard refusal, viewer refresh, snapshot privacy and phone-width layout. The optional MCP client test supports the SDK 1.x session API and retains the previously tested 2.x client API; 1.29.0 was exercised for this release. These browser tests run when the optional `playwright` Python package and a system `chromium` or `chromium-browser` executable are installed; otherwise they report skips. They download nothing and use synthetic records only.

## Credits and license

Built on ScrollPrize's [villa](https://github.com/ScrollPrize/villa) and VC3D, their open data, published segments and ink labels, the released `ink_9um` model, and the community's fine-tunes of it, Domenico Russo's Reader v2 (the default reader) and TAUIL-Abd-Elilah's d9v2. Other community methods are cited in the code where they are used. Code: Apache License 2.0. Data and model weights keep their own licenses and are not included.
