# autopipeline: run villa's pipeline from a released scan to a scored ink map, unattended

AutoPipeline (AP) 0.1.6 runs villa's VC3D tools and ink detection on one released scan, from its headers to checked surfaces, ink maps with reversed and shuffled controls, and scores; its code is on public branch `submission/progress-2026-10-fix6`, not on `main`.

| Field | Value |
| --- | --- |
| Id | `autopipeline` |
| Status | Branch only |
| Kind | package |
| Area | Pipeline and agents |
| Run | `scrolls-kit autopipeline` after `pip install -e .` in the package folder; inside that folder the branch's own `kit` module runs the same program (alias `autopipe`); `python scripts/demo_synthetic.py`; `scrolls-kit vc3d mcp` serves it as an MCP tool |
| Code | `submissions/progress-2026-10-fix6/autopipeline/` on its branch: mainly `kit/autopipe.py` (`cmd_autopipe`, `build_parser`, `DEFAULTS`), `kit/autopipe_monitor.py`, `kit/apconsole.py` (the console), `kit/qareasons.py`, `kit/apbackends.py`, `kit/vc3d_agent.py`, `kit/vc3d_cache.py`, `kit/cli.py`, `scripts/demo_synthetic.py`, `scripts/get_vc3d.py`, `scripts/vc3d/ink.py`; release record `submissions/progress-2026-10-fix6/release.json` |
| Tests | `submissions/progress-2026-10-fix6/autopipeline/tests/` on its branch: 46 `test_*.py` files, among them `test_autopipe.py` (the whole chain on a synthetic scroll with stand-in VC3D tools), `test_autopipe_monitor.py`, `test_autopipe_monitor_ui.py` (the monitor page in a local Chromium), `test_demo_synthetic.py` and `test_vc3d_agent.py`, with stand-in tools in `vc3d_fakes.py` |
| Needs | Python 3.11 or newer (zarr 3 needs it); numpy, tifffile, zarr 3 and scipy (`pyproject.toml`, tested 2026-10-12 with numpy 2.4.6, tifffile 2026.3.3, zarr 3.1.6, scipy 1.17.1). For real runs: villa's VC3D tools (`vc_gen_umbilicus`, `vc_grow_seg_from_seed`, `vc_tifxyz_selfcross`, `vc_flatten`, `vc_render_tifxyz`), from villa's Linux x86_64 AppImage or `VC3D.app` on a Mac; for ink, villa's `vesuvius` package and torch in their own environment (`KIT_INK_PYTHON`). Optional, for the browser tests only: the `playwright` Python package and a system `chromium` or `chromium-browser`; without them those tests skip and download nothing |
| Runs on | The synthetic demo: 5.5 s as it reports itself in a cloud container, Python 3.13, from the 0.1.6 package's release check (2026-10-24); the package's 1241 tests took 590 s there (27 skipped). With 0.1.5 it reported 4.7 s on a shared 4-core container (2026-10-18). A real run on PHerc0841 w00 from the released scan and published segment: 593 s, 344 s on 8 CPU cores then 249 s on one L4, on Modal (package README, 9 October 2026); the three-reader rerun took 1163 s on 8 CPU cores and one L4 (package README, 15 October 2026). GPU ink goes to Modal (the Modal rule, hard rule 11) |
| Network | The open-data bucket `vesuvius-challenge-open-data` over HTTPS (scan and prediction headers and chunks, normal grids, published segments and ink labels); `api.github.com` and `github.com` for `scripts/get_vc3d.py` (villa's AppImage, sha256 checked); model downloads by the MCP tool `fetch_model`. The monitor listens on `127.0.0.1` only and loads nothing from the internet. The synthetic demo needs no network |
| Writes | A run folder `work/autopipe/<sample>-<volume>-<digest10>/` under the kit home (the package folder, or `KIT_HOME`): `plan.json`, `state.json`, `events.jsonl`, traces, renders, ink maps, `scores.json`, `report.json` and, when ink is handed off, `modal-job.json`; `work/vc3d/` for the catalog cache and the unpacked AppImage (about 370 MB). The demo writes to a temporary folder under `/tmp` and prints its path. `monitor --snapshot FILE.html` writes one HTML file |
| Go-ahead | Needed for a paid batch or any cloud (Modal) launch, which costs money (the go-ahead rule, hard rule 8); not needed for the demo, `defaults`, `plan` or a local run |
| Released | Public branch `submission/progress-2026-10-fix6` at `8096b46` (committed 2026-10-24, a commit with no parent; README entry dated 2026-10-24 in [`releases.json`](../releases.json), pinned to the top of "Released tools"). Tagged `autopipeline-v0.1.6`, with a [GitHub release](https://github.com/ChaseHendrick/Scrolls/releases/tag/autopipeline-v0.1.6) not marked Latest (2026-10-24); 0.1.5 is on `submission/progress-2026-10-fix5` at `9e50d61`. Earlier versions stay on their own branches, the first, 0.1.0, on `submission/progress-2026-10` since 2026-10-14; 0.1.4 is tagged `autopipeline-v0.1.4` |
| License | Code: Apache License 2.0 ([LICENSE on the branch](https://github.com/ChaseHendrick/Scrolls/blob/8096b464007af732d9835ac9fae4be49ce2354d0/submissions/progress-2026-10-fix6/autopipeline/LICENSE)); data and model weights keep their own licenses and are not included |
| Guide | [`docs/autopipeline/README.md`](../autopipeline/README.md), the full reference (commands, settings, variables, stages, troubleshooting), with rules for agents in [`docs/autopipeline/AGENTS.md`](../autopipeline/AGENTS.md) |
| Branch | `submission/progress-2026-10-fix6` at `8096b46` |
| Checked | 2026-10-24 against commit `8096b46` |

## What it does

villa's pipeline turns a CT scan into ink maps in steps: find the scroll's center line (the umbilicus), trace papyrus surfaces (segments, stored as tifxyz grids of 3D points), flatten them, render a thin slab of CT around each surface (a surface volume), and run an ink model on it. Today a person checks the output at almost every step. AutoPipeline replaces each of those choices with a rule fixed before the run, and gives every check a control that can fail. It calls villa's own tools and ink inference; it does not reimplement them.

One run covers one released scan and lives in one folder. `plan.json` freezes every setting and every resolved input (the zarr headers of every level, the surface prediction, the normal grids, the axis) under a SHA-256 digest, so a changed threshold means a new folder, never an edit to a run whose results were seen. `state.json` records each of the 11 stages: `acquire`, `umbilicus`, `seeds`, `trace`, `bench`, `qa`, `flatten`, `render`, `ink`, `score`, `report`. A finished stage is not repeated, so an interrupted run resumes; each failure is labeled as the tool's own decision or an infrastructure problem. Ink detection always also runs on the layers reversed and shuffled, and scoring (pixel AUC against published ink labels) scores those control maps beside the forward map. AutoPipeline Monitor is a read-only local web page (or a text view) of one run folder. Since 0.1.5 its page has keyboard-accessible controls: inspect a stage and its recorded failure, filter the loaded log tail, pause or refresh the viewer (not the pipeline), list the run's record files, and prepare a status or resume command for review and copying. Copying never runs a command, and a stale or paused view cannot prepare or keep a resume command. Since 0.1.6 the page fits one screen and has a console, on loopback only and off with `--read-only`: per-run notes kept under the kit home, and one AutoPipeline, kit or VC3D agent command at a time run as a background job.

Its default ink model (reader) is Reader v2, Domenico Russo's community fine-tune of `ink_9um`. On PHerc0841 w00, from the released scan and the published segment, it scored AUC 0.8752 forward, 0.5659 reversed and 0.5539 shuffled, against 0.7479, 0.5012 and 0.4851 for `ink_9um` seed 42 on the same render (package README, Modal, 15 October 2026). PHerc0841 is in the training data of none of ink_9um, v8in, d9v2 and Reader v2, but possibly in Hecate's; w00's labels had been scored before and these numbers chose the default, so they are development data, not a held-out test.

What it does not do: traces grown from its own seed points are small patches with no held-out ink score yet, and whole-winding tracing is still open. Version 0.1.4 fixed remote renders for villa builds since 12 October 2026, but no full remote render has run with 0.1.4 or 0.1.5 yet. Version 0.1.5 changes usability and correctness only: the monitor controls, a synthetic demo that fails when a fake model fails or a map is missing, and cache-repair times stored at full precision, so one repair does not trigger an extra render. Its models, scientific settings and recorded measurements are those of 0.1.4, and it adds no ink-accuracy result. Version 0.1.6 adds qa failure reasons (each failed check with its value and threshold), opt-in steps that a plan must name (the Crackle Check gate at report, the published center lines as the axis, other axis backends, a region crop of rejected traces, edge extension, a stack check, trace budgets with partial results, z-scored ink ensembles), backend swap and provenance commands, and two built-in ink models (`inkfilter` and `reader-v3`); Reader v2 stays the default. A plan naming none of the new settings runs as before, except that `qa.repair` without a method now uses the barrier repair. It also adds no ink-accuracy result (`CHANGES.md`). Every map and score it makes is model output, not a reading; a triage order of maps is a reading order for a person, not a verdict. Here the release is called `autopipeline` in code; its short name is AP, while text for villa and the community spells out AutoPipeline.

## Where the code is

- Branch `submission/progress-2026-10-fix6` of public Scrolls, commit `8096b464007af732d9835ac9fae4be49ce2354d0` (no parent commit; it holds only the package), folder `submissions/progress-2026-10-fix6/`: `CHANGES.md` (what 0.1.6 changed), `SUBMISSION.md`, `release.json` (the package's 158 file hashes and its manifest digest), and `autopipeline/` (the installable package `vc-autopipeline` 0.1.6: `kit/`, `scripts/`, `docs/vc3d-agents.md`, `docs/vc3d-headless.md`, `space/` for the AutoPipeline ink Space, `spaces/crackle-check/` with the two Crackle Check engine files `reader-v3` runs, `tests/`, `Dockerfile`, `README.md`, `AGENTS.md`).
- The package's `space/` copy runs `ink_9um` seed 42. The live [AutoPipeline ink Space](https://huggingface.co/spaces/SharpMeow/autopipeline-ink) differs: since 16 October 2026 (revision `9f3ccfc5`) it runs Reader v2 and its page still links 0.1.4 (Hugging Face API, read 2026-10-18).
- Earlier releases, each on its own branch and never changed: 0.1.0 `submission/progress-2026-10` (`faada83`), 0.1.1 `submission/progress-2026-10-fix1` (`1534136`), 0.1.2 `submission/progress-2026-10-fix2` (`143c54b`), 0.1.3 `submission/progress-2026-10-fix3` (`bd7d6cf`), 0.1.4 `submission/progress-2026-10-fix4` (`603fe14`, tag `autopipeline-v0.1.4`), 0.1.5 `submission/progress-2026-10-fix5` (`9e50d61`).
- The package carries its own `kit` package, a different and larger one than `main`'s `kit/`: `autopipeline` is not a command of `main`'s `kit`.

```bash
git fetch origin submission/progress-2026-10-fix6
git show origin/submission/progress-2026-10-fix6:submissions/progress-2026-10-fix6/autopipeline/README.md
git clone --branch submission/progress-2026-10-fix6 --depth 1 https://github.com/ChaseHendrick/Scrolls.git scrolls-autopipeline
```

## How to run it

From the released entry, then the commands. On 2026-10-24 the demo printed `DEMO PASS` here with 0.1.6 (the release check's scratch copy, synthetic scroll, stand-in VC3D tools, no network), and `autopipeline defaults` ran from outside the folder after a fresh `pip install`. Since 0.1.5 it prints `DEMO PASS` only when both surfaces are accepted, both fake ink runs exit 0 and all six forward, reversed and shuffled map files are nonempty inside the run folder; otherwise `DEMO FAIL` with the log to read.

```bash
git clone --branch submission/progress-2026-10-fix6 --depth 1 https://github.com/ChaseHendrick/Scrolls.git scrolls-autopipeline
cd scrolls-autopipeline/submissions/progress-2026-10-fix6/autopipeline
python3 -m venv .venv && . .venv/bin/activate      # Python 3.11 or newer
python -m pip install -e .                          # numpy, tifffile, zarr 3, scipy
python scripts/demo_synthetic.py                    # every stage on a synthetic scroll; prints DEMO PASS
(cd /tmp && scrolls-kit autopipeline defaults)    # the install check: works from any folder
```

Demo output (synthetic inputs, this page's run):

```
render     done
ink        done
score      skipped
report     done
surface t00: accepted=True flatten=flattened render=yes ink maps={'fake-ink': ['f', 'r', 's']}
surface t01: accepted=True flatten=flattened render=yes ink maps={'fake-ink': ['f', 'r', 's']}
plan digest 553fb8d2387663d0..., run folder /tmp/autopipe-demo-x4yc4frc/run, 4.7 s
DEMO PASS
```

`f`, `r` and `s` are the forward, reversed and shuffled maps. A real run on a released scan:

```bash
APPIMAGE="$(python3 scripts/get_vc3d.py)" && export VC_APPIMAGE="$APPIMAGE"   # villa's current Linux AppImage, sha256 checked
scrolls-kit vc3d selftest                                                    # renders and traces synthetic volumes; PASS
scrolls-kit autopipeline plan SAMPLE --settings '{"purpose": "benchmark", "segment": "0841-w00"}'
scrolls-kit autopipeline run work/autopipe/FOLDER [--until STAGE] [--monitor]
scrolls-kit autopipeline status work/autopipe/FOLDER
```

- `SAMPLE`: a scroll id as the open-data catalog names it, such as `PHerc0841`.
- `FOLDER`: the run folder `plan` printed, `<sample>-<volume>-<digest10>`; a relative folder is read from the kit home.
- `STAGE`: the last stage to run, one of the 11 stages above.

Usage blocks, as `--help` prints them on the branch, shown with `scrolls-kit` (the program itself prints `python -m kit`, the branch's own module):

```
usage: scrolls-kit autopipeline [-h] {plan,run,status,defaults,monitor} ...
usage: scrolls-kit autopipeline plan [-h] [--settings SETTINGS] [--out OUT] sample
usage: scrolls-kit autopipeline run [-h]
                                    [--until {acquire,umbilicus,seeds,trace,bench,qa,flatten,render,ink,score,report}]
                                    [--monitor [PORT]]
                                    out
usage: scrolls-kit autopipeline status [-h] out
usage: scrolls-kit autopipeline monitor [-h] [--port PORT] [--host HOST]
                                        [--snapshot FILE.html] [--open]
                                        [--thumbs {auto,on,off}]
                                        [--stale-minutes STALE_MINUTES]
                                        [--text] [--width WIDTH]
                                        [--color {auto,on,off}] [--dither]
                                        [--watch SECONDS]
                                        out
```

| Action and option | Default | Meaning |
| --- | --- | --- |
| `defaults` | | Print the default settings as JSON (`DEFAULTS`) and exit 0 |
| `plan sample` | required | Freeze a plan for one scan: resolves the scan, surface prediction, normal grids and axis |
| `plan --settings SETTINGS` | none | A JSON object, or `@file`, of settings over the defaults; an unknown key is refused |
| `plan --out OUT` | `work/autopipe/<sample>-<volume>-<digest>` | Run folder |
| `run out` | required | Run or resume the planned run in this folder |
| `run --until STAGE` | none (all stages) | Stop after this stage |
| `run --monitor [PORT]` | off; port 8765 when given bare | Serve the live monitor page on 127.0.0.1 while the run lasts |
| `status out` | required | Each stage's status and each surface's result |
| `monitor out` | required | Run folder (a relative one is read from the kit home) |
| `monitor --port PORT` | `8765` | Port; `0` takes any free one |
| `monitor --host HOST` | `127.0.0.1` | Address to listen on (this machine only) |
| `monitor --snapshot FILE.html` | none | Write one self-contained page and exit, no server |
| `monitor --open` | off | Open the page in the default browser |
| `monitor --thumbs {auto,on,off}` | `auto` | Ink map thumbnails; `auto` shows them for smoke runs and published labeled segments only |
| `monitor --stale-minutes STALE_MINUTES` | `30` | With no update for this long a running stage looks stopped |
| `monitor --text` | off | Print the run as text, ink maps drawn in characters, and exit |
| `monitor --width WIDTH` | `40` | With `--text`, a map's width in characters |
| `monitor --color {auto,on,off}` | `auto` | With `--text`, gray half blocks; `auto` is on in a terminal unless `NO_COLOR` is set |
| `monitor --dither` | off | With `--text` and no color, ordered (Bayer) dithering |
| `monitor --watch SECONDS` | none | With `--text`, print again every SECONDS (at least 1) until Ctrl-C |

The settings themselves (umbilicus, seeds, trace, qa, flatten, render, ink, score, strict and others) are in [section 6 of the reference](../autopipeline/README.md#6-settings-reference); print them with `defaults`. The main environment variables:

| Variable | Meaning |
| --- | --- |
| `KIT_HOME` | Where runs, caches and experiments go; default the package folder |
| `KIT_INK_PYTHON` | A Python with villa's `vesuvius` and torch; without it a run stops at ink and writes `modal-job.json` (stage state `handoff`) |
| `KIT_AUTOPIPE_DEVICE` | `cpu` (default; hides CUDA from the ink engine), `cuda`, `cuda:N`, or `mps` with a TorchScript export |
| `KIT_AUTOPIPE_RUNNER` | `modal` marks a process as the remote runner where a handed-off stage runs |
| `KIT_SURFBENCH_REFS` | Winding reference folder for the `bench` stage |
| `KIT_ALLOW_MODAL` | `1`, set by the owner, lets kit run anything on Modal; without it nothing runs there |
| `VC_APPIMAGE`, `VC_BIN`, `VC_ROOTFS` | Where VC3D's tools are; the full list, with the relay, cache and thread variables, is in [section 7 of the reference](../autopipeline/README.md#7-environment-variables) |

## Inputs and outputs

Inputs: OME-Zarr scans and surface predictions, normal grids, published tifxyz segments, and ink label zarrs for benchmarks, all from the open-data bucket; settings as JSON. Outputs: tifxyz surfaces, zarr surface volumes, TIFF ink maps and JSON records, all in the run folder ([section 8 of the reference](../autopipeline/README.md#8-inputs-outputs-and-the-run-folder) lists every file).

| File in the run folder | What it holds |
| --- | --- |
| `plan.json` | `version`, `created`, `settings`, `resolved`, `digest`; never edited |
| `state.json` | `stages`, `surfaces`, `running`, `planned_traces`, `trace_failures`; each surface's `qa` result with `reasons` and `unmeasured` |
| `events.jsonl` | Progress and stage events, rotated at 256 KiB to `events.1.jsonl` |
| `ink/<sid>/<model>` | Forward, reversed and shuffled maps per model and surface |
| `scores.json`, `report.json` | AUCs of forward and control maps on published labels; the report with its digest |
| `triage.json` | With `triage`, a reading order of maps; on a scroll without published labels it stays in the git-ignored run folder |
| `modal-job.json` | The ink job, when ink is handed off |

`plan`, `run` and `status` print a JSON object on stdout and progress lines on stderr.

| Exit code | Meaning |
| --- | --- |
| `0` | Done, or `defaults` printed |
| `1` | The run's result holds `failed`: a stage failed (read `state.json`) |
| `2` | A tool error, printed on stderr, such as `Error: FOLDER has no plan.json; make one with action plan` (seen on 2026-10-16 with a folder that held no plan), or a usage error |

Common failures and their fixes ([section 13 of the reference](../autopipeline/README.md#13-troubleshooting) has the rest): `the plan's digest does not match its content` (plan.json was edited: make a new plan); `<out> holds a run of another plan` (use a new folder); `unknown plan setting <key>` (compare with `defaults`); ink stays `handoff` (set `KIT_INK_PYTHON`); `no surface passed the acceptance rule` (read `qa.reasons` and `qa.unmeasured`; the `stable` AppImage lacks `vc_tifxyz_selfcross` and `vc_gen_umbilicus`); a VC3D tool exits 139 (start it through the AppImage loader: set `VC_APPIMAGE`); remote renders fail on 0.1.3 (upgrade to 0.1.6, the current release; 0.1.4 fixed it); the demo prints `DEMO FAIL` (a dependency is missing or a fake ink command failed: read the log it names); the demo prints `DEMO FAIL` with `got 0` surfaces and `state.json` says a folder `is inside the repository but not ignored by git` (`--out` named a folder inside the clone that git would track: use `--out work/demo-run`, or no `--out` for a temporary folder); the monitor's Prepare resume command is unavailable (the run is active, finished, unreadable or refused by its plan's rules, or the view is paused or older than 30 seconds: press Refresh now).

## Why it is not on the default branch

It is a reviewed contribution package. 0.1.0 to 0.1.4 were released by the Progress Prize submission workflow: the owner approves an exact list of files, a manifest binds their hashes, and the release step puts them on a new public branch and checks the commit before its URL goes in the prize form (`SUBMISSION.md` on the branch). 0.1.5 and 0.1.6 are ordinary software releases, not new prize entries: the same kind of reviewed, hash-bound file list, on a branch whose one commit has no parent, with `release.json` recording each file's hash. A released branch never changes; each fix goes out as a new reviewed package under a new submission id (`progress-2026-10-fixN`), which is why 0.1.0 to 0.1.6 each have a branch. The package also carries its own `kit` package, which would clash with `main`'s `kit/`. `main` holds only its reference ([`docs/autopipeline/README.md`](../autopipeline/README.md)), its README entry, and the every-scan tools (`python -m kit run all`, `run watch`, `run catalog`), which plan and price runs and launch nothing.

## For agents

- **Revive:** Do not merge the branch into `main`: its `kit/` would overwrite `main`'s. Use it from a clone of the branch, as above. A change goes out as a new reviewed release under a new submission id, with its README entry replaced in place by `python -m kit releases add` (the releases rule, hard rule 15); never edit the released branch.
- **Check first:** That `python scripts/demo_synthetic.py` prints `DEMO PASS` (since 0.1.5 it fails when a fake model fails or a map is missing) and `scrolls-kit vc3d selftest` passes with the AppImage you have; that the villa build takes the URL form of `--volume` (`scrolls-kit vc3d call status` shows `volume_url`); `qa.unmeasured` before trusting a rejection; that a score's reversed and shuffled controls sit near 0.5 and below the forward map; whether the scored segment is held out from the reader (PHerc0139 w045 is not held out from `ink_9um`, d9v2 or Reader v2).
- **Never:** Edit `plan.json` or `state.json` (a changed rule is a new plan in a new folder); call an ink map or a triage order a reading or a finding; paste a command the monitor prepared without reading it first (it prepares commands for review and never runs them); copy a run folder, map, triage list or snapshot of a scroll without published ink into a public repository; launch a paid batch or a Modal job without the owner's yes; run GPU ink on a laptop CPU for hours.

## History

- 2026-10-24: 0.1.6 (`progress-2026-10-fix6`), an ordinary software release: the monitor on one screen with a console (notes and background commands, loopback only), qa failure reasons, opt-in steps (Crackle Check gate, published center lines, axis backends, region crop, edge extension, stack check, trace budgets, z-scored ink ensembles), backend swap and provenance commands, built-in `inkfilter` and `reader-v3` models; `qa.repair` without a method now uses the barrier repair (`8096b46`, tagged `autopipeline-v0.1.6`).
- 2026-10-18: 0.1.5 (`progress-2026-10-fix5`), an ordinary software release: keyboard-accessible monitor controls (stage inspection, log filters, viewer pause and refresh, run-record list, commands prepared for review and copying); a synthetic demo that fails when a fake model fails or a map is missing; cache-repair times at full precision; portable test fixtures for hosts with an ancestor Git checkout and for MCP SDK 1.x (`9e50d61`).
- 2026-10-15: 0.1.4 (`progress-2026-10-fix4`): remote renders pass the URL as `--volume` on villa builds since ba2bf75; monitor snapshots keep no piece of the run folder's path; real paths keep private lists out of tracked folders on macOS; four macOS-only test failures fixed (`603fe14`).
- 2026-10-15: 0.1.3 (`progress-2026-10-fix3`): Reader v2 the default reader; `ink.orient` fallback; faster remote reads; Docker build and AppImage download fixed (`bd7d6cf`).
- 2026-10-14: 0.1.2 (`143c54b`) and 0.1.1 (`1534136`), fix releases.
- 2026-10-14: 0.1.0, the first public release (`faada83`).

## Related

- [`docs/autopipeline/README.md`](../autopipeline/README.md): the full reference, sections 1 to 19, including every setting and the every-scan catalog, batch and watcher.
- [`docs/autopipeline/AGENTS.md`](../autopipeline/AGENTS.md): rules for agents that describe or run it.
- [batch](batch.md): `python -m kit run all`, `run watch` and `run catalog` on `main`, which plan AutoPipeline over every bucket volume and launch nothing.
- [auc](auc.md): the AUC score with the reversed control, as `main`'s `kit` computes it.
- [releases](releases.md): how the README's "Released tools" entry is written and replaced.
- [unroll](unroll.md): another released tool, listed under AutoPipeline in the README.
