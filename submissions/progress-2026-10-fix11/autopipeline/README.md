# AutoPipeline: villa's pipeline from a released scan to a scored ink map

![Concept illustration of a continuous papyrus surface traced in copper and flattened into a grid.](https://raw.githubusercontent.com/ChaseHendrick/Scrolls/b3190d92e441882c63ea8f3ed342ba1c05154efa/docs/assets/autopipeline-readme-hero.webp)

*Concept illustration, generated with OpenAI image generation; not a scan, model output or recovered text. [Artwork provenance](https://github.com/ChaseHendrick/Scrolls/blob/b3190d92e441882c63ea8f3ed342ba1c05154efa/docs/assets/README.md).*

Version **0.1.11** keeps two steps working on VC3D builds made after villa removed the tools they ran (villa `e1aa625a6`, 29 October 2026, villa #2358). The self-intersection check now has two backends: villa's `vc_tifxyz_selfcross` where the build has it, and otherwise the same census kernel from villa's source, compiled on your machine by `python -m kit selfcross build`; on 51 synthetic surfaces the two reports matched in every count and contact. Flattening uses `vc_flatten` where the build has it, and otherwise villa's own replacement, `flatboi` (SLIM), in its tifxyz mode; the same distortion limits decide whether the result is used. Before this, a run on a current build rejected every trace with its self-intersections not measured, and flattened nothing. [Changes since 0.1.10](../CHANGES.md). Version 0.1.10 added three steps that follow a run, each a swappable stage with an `off` choice: `labels` moves each accepted surface onto the papyrus face of its sheet (Snapped Labels' placement), `fibers` traces papyrus fibers in a box around it (Weft, on the public AFV V2 fiber probabilities of Qual's model), and `joins` scores glued sheet joins (kollesis) at the fiber ends along it, with a control beside each score. They are experimental: no preregistered test has scored their output on a new trace. Version 0.1.9 let a plan swap any stage by name (`plan --use STAGE=NAME`, from the stage registry `python -m kit stages`) and added 3D ink readers to the ink stage, opt in and experimental, beside or instead of the 2.5D default, which stays Reader V3. Version 0.1.8 made Domenico Russo's Reader V3 the default reader (`ink.models`), in place of his Reader v2, and the ink Space runs it too. Version 0.1.7 drew ink maps in color, on one scale from dark umber (low score) to pale papyrus (high score), in the monitor and the ink Space; the synthetic demo began to plant pen strokes on its papyrus so its maps show something to look at; and a published center line from the Center Finder came in its coverage-polished copy first. Version 0.1.6 put the monitor on one screen with a console for notes and tools, and wired in opt-in steps: Crackle Check at report, published center lines and three other axis backends, region crop, edge extension and a stack check, with each qa check's measured value kept. Every such step is off unless a plan names it.

AutoPipeline runs villa's pipeline from a released scan to a scored ink map, with checks that can fail at every step. It drives VC3D's command-line tools and villa's ink detection end to end. A rule written down before the run replaces each choice a person usually makes by eye, and every check it runs has a control. In the code and on the command line it is called `autopipeline`.

It does not replace villa or VC3D. It calls their tools (`vc_gen_umbilicus`, `vc_grow_seg_from_seed`, `vc_tifxyz_selfcross` or its census kernel, `vc_flatten` or `flatboi`, `vc_render_tifxyz`) and villa's ink inference, then checks what they return.

## Why

The [2026 open problems](https://scrollprize.org/2026_open_problems) page says: "The pipeline works, but not without a person checking its output at almost every stage." It also asks for "reproducible streaming pipelines". I wanted to see how many of those checks could be written as fixed rules that run on their own.

## What it does

| Step | Tool | Rule |
| --- | --- | --- |
| Inputs | Scan, surface prediction and normal grids from the open-data catalog | Zarr headers of every level are read and frozen in the plan |
| Umbilicus | The catalog's, or `vc_gen_umbilicus` on the normal grids every 500 slices; opt in: a published center line ([SharpMeow/vesuvius-center-lines](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines), pinned and checked by sha256), the scroll Center Finder or a numpy method on the normal grids, each with an optional coverage polish | Outliers dropped by a robust line fit; a backend that cannot run says why and the next one in the plan's list is tried |
| Seed points | Points on the surface prediction, on papyrus in the CT, 1.5 mm or more from the umbilicus, 2 mm apart | Each is checked against the prediction and the CT |
| Tracing | `vc_grow_seg_from_seed` with the published normal grids | A trace made without normal grids is refused |
| Surface checks | tifxyz validity as VC3D loads it, self-intersections (`vc_tifxyz_selfcross`, or villa's census kernel compiled by `python -m kit selfcross build`), CT contrast across the surface at 5 windows, normal direction against the umbilicus, sheet switches between wraps | A fixed accept or reject rule; every check's result is kept, and a rejection records each failed check with the value it measured and its threshold |
| Repair, crop, extend (opt in) | A sheet-switch cut back to the seed's winding; region crop (`kit meshqa crop`), which cuts out crossings and off-sheet pieces and keeps each clean piece; edge extension with `vc_extend_edge` (from a VC3D fork branch, not yet in villa's release; without it the step says so) | Each new surface is checked again by the same rule and replaces or joins the trace only when it passes |
| Flattening | `vc_flatten`, or `flatboi` (villa's SLIM flattener, tifxyz mode) on builds without it | Kept only if the 95th percentile stretch error is at most 0.25, the 95th percentile shear at most 20 degrees, and the area ratio between 0.8 and 1.25 |
| Surface volume | Missing-chunk check under the surface, then `vc_render_tifxyz` with `--flip-normals` | Refused above 5 % missing chunks (or trimmed, opt in); layer order checked against the umbilicus |
| Ink detection | Each model on the layers as rendered, reversed, and shuffled | The reversed and shuffled maps always run |
| Scoring | Pixel AUC against published ink labels | Reversed and shuffled maps scored beside the forward map |
| Report checks (opt in) | [Crackle Check](https://huggingface.co/spaces/SharpMeow/crackle-check)'s control-set gate on each accepted surface's maps against their reversed controls; `kit stackcheck` from public Scrolls over the accepted traces | Crackle gives Yes, Maybe, No signal found or Too small with a kept-ink overlay; a check that can fail, not a reading |
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

Reader v2 became the default (`ink.models`) in 0.1.3 and stayed it until 0.1.7; Reader V3 has been the default since 0.1.8 (below). Before the run I fixed the rule. In short, Reader v2 becomes the default if it beats seed 42 by 0.01, d9v2 instead if d9v2 leads Reader v2 by 0.01, and seed 42 stays otherwise; as written, it left two cases undecided, and neither arose. d9v2's lead was 0.0014. Seed 42 repeated its 9 October numbers to four decimals, and each reader matched its earlier score on the published surface volume's densest-ink window within 0.0004. PHerc0841 is in none of the three readers' training data, but w00's labels had been scored before and these numbers chose the default, so they are development data, not a held-out test.

**Reader V3 (version 0.1.8, 25 October 2026).** Reader V3, released on 19 October 2026, is Reader v2 continued on larger tiles with the same data, and it keeps the same checkpoint format. It is the default from 0.1.8 because it is the newest of that family, not because it scored better: no rule fixed in advance chose it, and I make no claim that it reads ink better than Reader v2. Its author reports fewer false ink marks on blank papyrus (Community report). Its author also benchmarked PHerc0841 while choosing its recipe, so PHerc0841 scores may favor it. villa's ink detection runs it at its own 17 x 384 x 384 patches, from its config. `"models": ["reader-v2"]` in a plan keeps the earlier default.

**The checks reject what they should** (PHerc0139 and PHerc0841, 4 CPU cores):

- One run stopped when both traces had CT contrast at 1 of 5 windows or fewer.
- Another run rejected a trace whose normals pointed toward the umbilicus.
- The missing-chunk check found 10 to 24 % of chunks missing under three traces. That result is why the 5 % rule exists.
- `vc_tifxyz_selfcross` found 175 self-intersections in the published w00 segment. For a published segment this is recorded and the run goes on, because its labels sit on its grid.

**Umbilicus estimate.** Against the catalog's umbilicus on three 9.362 µm scans, the median distance was 112, 210 and 428 voxels (about 1, 2 and 4 mm). The scan centre was 849, 166 and 795 voxels off.

## Limits

- The scored end-to-end run started from a published, hand-traced segment. Seed points and tracing are automated and tested, but my own traces have no held-out ink score yet. On w00's labelled pixels, `ink_9um` scored AUC 0.618 on my own trace's render against 0.798 for the published segment's map. Most of that gap was the render's in-plane rotation: turning it upright before ink (the `ink.orient` setting) scored 0.874 on the same pixels (seed 42, 13 October 2026). That is development data scored before, not independent confirmation. The same test with Reader v2 on 15 October: 0.851 as rendered, 0.911 upright, but 0.872 for a sham turn 45 degrees off upright, and upright minus sham was not clearly above zero (+0.039, 95% interval -0.005 to 0.091), so `ink.orient` stays opt in. The turn also raised the reversed control from 0.476 to 0.709, so forward minus reversed fell from 0.375 to 0.202; that is an observation, not part of the rule.
- Reader v2 was trained on some published segments, PHerc0139's w045 among them, so its scores there are not held out; Reader V3 continues it on the same data. `ink_9um`, and with it d9v2, trained on w045's 2.4 µm render, so none of these readers is held out there.
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

**VC3D builds after 29 October 2026.** villa main removed `vc_tifxyz_selfcross` and `vc_flatten` in `e1aa625a6` (villa #2358), so a `latest` AppImage built after that has neither (`python -m kit vc3d which` says what runs instead). Run this once:

```bash
python -m kit selfcross build              # villa's census header at 7154682e1, checked by sha256, compiled with a C++17 compiler
python -m kit selfcross status             # villa, kernel, and which one auto picks
```

It fetches one file, villa's `vc_tifxyz_selfcross_impl.hpp` at commit `7154682e1` (the last one that has it), refuses it unless its sha256 matches, and compiles it with this package's small driver into `work/selfcross/`. It needs g++ or clang++ (on a Mac, `xcode-select --install`) and no OpenCV. Without network, give a copy with `--header FILE`. villa's code is GPL-3.0: it is never copied into this package, and the binary built from it stays on your machine (an image built from the Dockerfile holds both, like the VC3D AppImage in it, so share such an image only under GPL-3.0). qa then uses it wherever the build lacks `vc_tifxyz_selfcross`, and its report is the same as that tool's. A plan can name the backend (`qa.selfcross`: `villa` or `kernel`; absent is auto), and `python -m kit stages list selfcross` lists them. Flattening needs nothing extra: it uses `flatboi` from the same AppImage, with its own settings under `flatten.flatboi` (50 SLIM iterations, symmetric Dirichlet energy by default), and a plan can name the tool (`flatten.tool`: `villa` for `vc_flatten`, or `flatboi`). `flatboi` keeps lengths where `vc_flatten`'s ABF++ keeps angles, so its grids differ; the same distortion limits decide. It has been checked on synthetic shapes only.

Keep the AppImage file, or after the first run point `VC_APPIMAGE` at the unpacked copy, `work/vc3d/appimage/<name>/squashfs-root`. Export `VC_APPIMAGE` again in every new shell.

villa rebuilds its [`latest` release](https://github.com/ScrollPrize/villa/releases/tag/latest) with every build and deletes the one before, so the file name and checksum change and an old link stops working. `scripts/get_vc3d.py` asks GitHub's API which `*-linux-x86_64.AppImage` the release holds now, checks the download against the sha256 GitHub publishes for it, and keeps a file that is already there and matches. `python3 scripts/get_vc3d.py stable` takes the `stable` release instead, which passes the self-test but has no `vc_tifxyz_selfcross` or `vc_gen_umbilicus`; `python3 scripts/get_vc3d.py URL --sha256 HEX` takes one pinned file. Set `GITHUB_TOKEN` if GitHub's limit of 60 anonymous API requests an hour gets in the way. If you unpack the AppImage yourself, set `VC_APPIMAGE` to the `squashfs-root` folder. Its `usr/bin` tools need the AppImage's own loader and crash (exit 139) when started directly.

On a Mac with Apple Silicon, the same release has a dmg. Drag `VC3D.app` to Applications and run `xattr -dr com.apple.quarantine /Applications/VC3D.app` (the app is not notarized). kit looks in `/Applications/VC3D.app/Contents/MacOS`. A villa build from source works too: set `VC_BIN` to its `build/bin`.

There is also a Dockerfile: `docker build -t autopipeline . && docker run --rm autopipeline` runs the tool check, the self-test and the demo. AutoPipeline 0.1.3's image was built and run on 15 October 2026 on x86_64 with villa's AppImage 5432721, and all three passed; the images of 0.1.4 to 0.1.7 have not been built. That machine was behind a proxy, so a test-only layer added the proxy's certificate and https apt sources under the image, and the build read GitHub's release listing from a saved copy. On another machine the same day, the script's lookup against GitHub's API found the same file, and its sha256 matched the one GitHub publishes. The self-test and the demo render local volumes only. With every VC3D build since villa ba2bf75 (12 October 2026), 4eecd08 and 5432721 among them, 0.1.3's remote renders failed; 0.1.4 passes the URL as `--volume` on those builds, as villa's tutorial now does (see the [0.1.4 changes](https://github.com/ChaseHendrick/Scrolls/blob/603fe14633201d6769776519646dc19cf203009f/submissions/progress-2026-10-fix4/CHANGES.md)); a full remote render with it has not yet been run. The build takes the AppImage villa's `latest` release holds at that moment through `scripts/get_vc3d.py` and records its name and sha256 in `/opt/vc3d/appimage.json`; `docker build --no-cache` fetches it again, and the Dockerfile's comments say how to pin one file or pass a GitHub token. villa has no arm64 AppImage, so on arm64 (Docker on Apple Silicon) the image keeps villa's older container tools, and the tool check reports `vc_tifxyz_selfcross` and `vc_gen_umbilicus` missing.

**Ink detection** needs villa's `vesuvius` package and torch (Python 3.14) in an environment of its own; set `KIT_INK_PYTHON` to its `python`. Without it, a run stops at ink and writes a job file (`modal-job.json`); on a machine with a GPU, set `KIT_INK_PYTHON` and `KIT_AUTOPIPE_DEVICE=cuda` and run the same folder again: the run then does ink, scores and the report. The default reader is Reader V3 (`reader-v3`, since 0.1.8); a plan's `ink.models` can name others, such as `reader-v2`, `d9v2` or `ink_9um-seed42`, and the `fetch_model` tool downloads the known ones with their checksums.

`KIT_AUTOPIPE_DEVICE` is the device ink is asked to use: `cpu` by default (which also hides CUDA GPUs from the ink engine), `cuda` or `cuda:N`, or `mps` with a TorchScript export of the checkpoint. Each model's ink record in `state.json` keeps the device asked for and the one the engine's output said it used, since an engine can pick another one itself.

```bash
python -m kit autopipeline defaults
python -m kit autopipeline plan PHerc0841 --settings '{"purpose": "benchmark", "segment": "0841-w00"}'
python -m kit autopipeline run work/autopipe/<folder> [--until render]
python -m kit autopipeline status work/autopipe/<folder>
```

A relative run folder is read from where runs are written (this folder, or `KIT_HOME`).

The measured runs above used my own Modal runner, which is not part of this release.

For agents, `python -m kit vc3d mcp` serves the same run as an MCP tool, next to the VC3D tools (`trace`, `render`, `flatten`, `check_surface`, `audit` and others). `flatten` takes `tool` (`auto`, `vc_flatten` or `flatboi`) and `check_surface` takes `selfcross_backend` (`auto`, `villa` or `kernel`). See [docs/vc3d-agents.md](docs/vc3d-agents.md) and [AGENTS.md](AGENTS.md).

Formats: OME-Zarr volumes and predictions, tifxyz surfaces, zarr surface volumes, TIFF ink maps, JSON records.

### Watch a run

```bash
python -m kit autopipeline run work/autopipe/<folder> --monitor          # a live page at http://127.0.0.1:8765/ while the run lasts
python -m kit autopipeline monitor work/autopipe/<folder> [--open]       # the same page for any run folder
python -m kit autopipeline monitor work/autopipe/<folder> --snapshot run.html   # one self-contained file
python -m kit autopipeline monitor work/autopipe/<folder> --text [--watch 5]    # the same run as text in a terminal
```

The page, AutoPipeline Monitor (AP Monitor on the browser tab and on a narrow screen), fits on one laptop screen with no page scroll: a header with the run's main numbers, a status row with an 11-stage rail, and five panels. Stages lists each stage with its time; Surfaces has a picker, each surface's checks and a 3D wireframe of its traced mesh that you can turn by dragging; Ink and control shows its ink maps beside their reversed controls and any scores; Log has the run's events, the newest tool log and the console's jobs; Console has Tools, Notes and Files. Below 1000 px wide or 600 px tall the panels stack in one column that scrolls. `--text` prints the same run in a terminal, with each ink map and its reversed control drawn in characters on the same scale. The page loads nothing from the internet. Every map and score on it is model output, not a reading.

- **Inspect** a stage on the rail or in Stages to see its recorded status, timing, failure type and affected surfaces; selecting a stage also filters the log. QA failures list each failed check with what it measured and its threshold, and a geometry-review next step; the monitor does not locate bad regions or repair surfaces. Use the official [VC3D tutorial](https://scrollprize.org/tutorial_VC3D) to inspect a surface against neighboring CT slices before editing it.
- The log filters count how many of the loaded tail lines match; they are not a search of the complete log history. **Clear filters** shows the whole loaded tail again.
- **Pause view** holds the page still; it does not pause the pipeline. **Refresh** loads one current summary. A refresh times out after 10 seconds, and a state older than 30 seconds cannot prepare or keep a resume command.
- **Prepare status command** and **Prepare resume command** fill a command box for review, and **Copy command** copies it. Copying runs nothing. Resume is unavailable for an active or finished run, an unreadable state, a plan-rule refusal, or a stale or paused view.
- **Files** lists the plan, state, report, score and event records under the run folder, including missing or unreadable ones. A recorded file is not a validation pass.

**The console writes and runs things.** On a loopback address (the default, 127.0.0.1) the live page's console is on. Notes saves a Markdown note per run under the kit home (`work/autopipe-notes/`), never in the run folder. Tools runs one command line at a time as a background job of the VC3D agent tools: `ap ARGS` (the same as `kit autopipeline ARGS`), `kit ARGS` for any `python -m kit` command, or a VC3D agent tool such as `app_open surfaces=[...] display=true`, which opens surfaces in the VC3D app's window (without `display` it runs offscreen). `{run}` in an argument is the run folder and `{surface}` the surface chosen on the page. Every console request must carry a token that only this server's own page holds, and a request from another origin is refused. `--read-only` turns the console off; it is also off on any address that is not loopback. With the console off, the server accepts only GET and HEAD and writes nothing; it never writes run files either way.

A snapshot (`--snapshot`) leaves out your folder's path and machine name and shows any other full path by its last name only, but it holds the run's records and log lines, so do not share one of a scroll whose ink is not published. It keeps inspection and log filters and has no console; `--with-notes` puts the run's notes in, read only.

### Swap a stage's backend, and see what made an output

```bash
python -m kit autopipeline backends                         # each swappable stage's backends, and what this machine has for each
python -m kit autopipeline preflight work/autopipe/<folder> # what a plan's backends need, checked before it runs
python -m kit autopipeline why work/autopipe/<folder> PATH  # which stage, backend, inputs and settings made an output
python -m kit autopipeline swap work/autopipe/<folder> --stage STAGE --backend BACKEND   # a new run with one backend changed
python -m kit autopipeline diff RUN_A RUN_B                 # whether two runs differ by that one swap only
python -m kit autopipeline graph work/autopipe/<folder>     # the run's provenance graph
python -m kit autopipeline learn status                     # advice from finished runs' own records, no new compute
```

A swap makes a new plan, so it has a new digest and never edits a run whose results have been seen. `plan --use STAGE=NAME` (repeatable; `KIT_STAGE_<STAGE>` in the environment counts too) picks a stage's option by name from the stage registry, `python -m kit stages list STAGE`, which lists every option with who made it, its licence and its maturity (default, validated, experimental, pending or failed); the pick becomes the plan's `backends` setting before the digest, an experimental pick warns and a pending one is refused. 3D ink readers (`python -m kit ink3d list`: the organisers' Paris 4 3D model through villa's `paris4_3d_gambiarra` inference, and published 3D predictions) predict ink in the scan's voxels; the ink stage reads that volume onto the exact pixels of the surface's 2.5D render, so both maps share labels and scorer, and writes a moved-sheet control as the r map (the read with the sheet moved two sheet pitches out and in, the larger of the two; the pitch comes from the CT or `ink.pitch_um`). None has beaten the 2.5D default on a held-out test, so every one is experimental and runs only when a plan names it: `--use ink=reader-v3,team-3d-paris4`. Two built-in ink models need no download: `inkfilter` (Inkfilter's face-mix filter, fixed operations on the CPU) and `reader-v3-koine` (Domenico Russo's Reader V3, MIT, through villa's koine inference in the ink Python; it needs torch, torchvision, monai, timm and einops, and reads the whole render into memory). It was named `reader-v3` before 0.1.8, when that name went to the same weights run by villa's ink detection, the default reader. `plan --new-defaults` adds the settings recommended for a fresh scroll where a plan names none: trace budgets with partial surfaces, the Center Finder with villa's estimator as its fallback, and the coverage polish. The Center Finder needs torch in the ink Python and its script from public Scrolls (`scripts/umbilicus/predict.py`, named by `KIT_CENTRENET_PREDICT`); without them the run uses villa's estimator and records why.

### Labels, fibers and joins after a run

```bash
python -m pip install -e '.[couple]'                        # adds huggingface_hub, which the fibers step reads the probabilities with
python -m kit apcouple from-run work/autopipe/<folder>      # a coupled run folder from a finished run's accepted traces
python -m kit apcouple chain work/autopipe/<folder>/coupled # labels, fibers and joins in order
python -m kit apcouple check work/autopipe/<folder>/coupled # the folder against each step's contract
python -m kit apcouple swap work/autopipe/<folder>/coupled labels mesh snapped   # two backends side by side, and what changed downstream
```

`python -m kit apcouple init RUN --surface S --volume URL --voxel-um UM --umbilicus U --sample SCAN` makes the same folder from any tifxyz surface, a published segment included (the labels step needs the center line `--umbilicus`, and the fibers step the scan's name `--sample`, such as PHerc0814), so the steps also run without a full AutoPipeline run; `python -m kit apcouple labels|fibers|joins RUN` runs one step. Each step reads the one before: `labels` reads each surface, the run's center line and the scan, and writes the surface moved onto the recto face, an abstain mask, an OME-Zarr surface label (1 surface, 2 ignore) and a VC3D review queue, the same code as `python -m kit labelsnap snap`; its `mesh` choice writes the surface as given, as the same label, the baseline to compare against. `fibers` reads the surface `labels` wrote (the snapped one when there is one) and traces Weft fibers in a box around it from the public AFV V2 probabilities (made with Qual's model) of the run's own scan (PHerc0009B, PHerc0139, PHerc0332, PHerc0814, PHerc0841 or PHerc1667), as `.afv` files that open in VC3D. `joins` scores each horizontal fiber end on the surface with the kollesis finder's score, the patch followed along the surface behind the end, and the same score at a point moved back about 3 cm along the surface as a control; at coarse voxel sizes it needs long unbroken surface rows behind an end and scores only the ends that have them. Each step's output equals its own tool run alone on the same input (the parity tests), `off` turns a step off, and `swap` writes both arms' digests and what the next step read from each.

Inside a plan, as plan settings, these steps come in a later version: today they follow a finished run with `from-run`. They are experimental (`python -m kit stages list labels`): a smoke run on public PHerc0814 data shows that the steps run and that each reads the one before, not that any label, fiber or join score is right. Every surface, label, fiber and score is model output, not a reading.

## Tests

`python -m unittest discover -s tests`. `tests/test_autopipe.py` runs the whole chain on a synthetic scroll with stand-in VC3D tools, also as a build after villa's removal of the two tools. `tests/test_selfcross.py` compiles the census kernel when a compiler and a copy of the header are there (it never fetches one) and checks it against the counts villa's own `vc_tifxyz_selfcross` gave its 11 fixtures; `scripts/selfcross/parity.py` compares both backends directly when you have a build that still has the tool ([docs/tools/selfcross.md](docs/tools/selfcross.md)).

The synthetic demo reports `DEMO PASS` only when its stage statuses match, both surfaces are accepted, and both fake ink runs exit successfully with nonempty forward, reversed and shuffled map files inside the run folder. A missing dependency or failed fake-model command produces `DEMO FAIL` with the relevant log location, even if orchestration recorded the ink stage as done. This checks installation and orchestration, not real VC3D geometry or ink-model accuracy.

`tests/test_autopipe_monitor_ui.py` exercises the actual generated page in a local Chromium browser, including failure filters, shell quoting, clipboard refusal, viewer refresh, snapshot privacy and phone-width layout. The optional MCP client test supports the SDK 1.x session API and retains the previously tested 2.x client API. These browser tests run when the optional `playwright` Python package and a system `chromium` or `chromium-browser` executable are installed; otherwise they report skips. They download nothing and use synthetic records only.

## Credits and license

Built on ScrollPrize's [villa](https://github.com/ScrollPrize/villa) and VC3D (their self-intersection census kernel is compiled from villa's source at build time, and `flatboi` flattens), their open data, published segments and ink labels, the released `ink_9um` model, and the community's fine-tunes of it, Domenico Russo's Reader V3 (the default reader) and Reader v2, and TAUIL-Abd-Elilah's d9v2; Qual's AFV V2 fiber model (Apache-2.0), with which we made the public fiber probabilities (CC BY-NC 4.0, like the scans) that the fibers step reads. Other community methods are cited in the code where they are used. Code: Apache License 2.0. Data and model weights keep their own licenses and are not included.
