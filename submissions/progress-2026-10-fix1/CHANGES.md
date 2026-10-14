# AutoPipeline 0.1.1: what changed since the first release

The first release, AutoPipeline 0.1.0, is submission `progress-2026-10`: branch `submission/progress-2026-10` of this repository, commit `faada83287d39bbd4c7fd88c7ab0e75f3f1ff284`. It stays as it was. This package, `progress-2026-10-fix1` (14 October 2026), is the whole of AutoPipeline again with these changes. Every other file is byte for byte the first release's, and no result changed.

## Fixes

- **Running the same folder again now finishes ink.** The README says that a run with no ink environment stops at ink, and that you then set `KIT_INK_PYTHON` on a machine with a GPU and run the same folder again. In 0.1.0 that second run counted the handed-off ink stage as finished and did nothing. Now, under the default `ink.where: auto`, it runs ink, then scores and the report, once the planned models are registered and the ink Python has torch. A plan that says `ink.where: modal` still hands off.
- **The ink device is documented and recorded.** `KIT_AUTOPIPE_DEVICE` sets the device ink is asked to use: `cpu` by default (which also hides CUDA GPUs from the ink engine), `cuda` or `cuda:N`, or `mps` with a TorchScript export. 0.1.0 read it but no document named it, so a GPU machine following the README ran ink on its CPU. Each model's ink record now keeps the device asked for and the one the engine's output said it used (`device.asked`, `device.reported`), in `state.json`, in the ink tool's result and in its `receipt.json`, since an engine can pick its own: villa's inference took MPS on a Mac when asked for `cpu`.
- **The monitor shows a passed snap check.** It read the snap check's verdict under the wrong name, so a snap check never showed as passed. It now reads `Passed` or `Failed`.

Files: `autopipeline/kit/autopipe.py`, `autopipeline/kit/vc3d_agent.py`, `autopipeline/scripts/vc3d/ink.py`, `autopipeline/kit/autopipe_monitor.py`, `autopipeline/README.md` ("Install"), `autopipeline/docs/vc3d-agents.md` ("Ink detection"), and tests in `autopipeline/tests/test_autopipe.py`, `test_vc3d_agent.py` and `test_autopipe_monitor.py`.

## Name

The run monitor's browser tab and narrow-screen title now read AP Monitor instead of APL Monitor, because Pipeline is one word. The README writes AutoPipeline in full.

Files: `autopipeline/kit/autopipe_monitor.py`, `autopipeline/tests/test_autopipe_monitor.py`, `autopipeline/README.md`.

## Run monitor

- **A 3D view of each traced mesh.** The page draws each surface's traced mesh (its tifxyz grid, at most 64 rows and columns) as a wireframe you turn by dragging, or with the arrow keys; 0 or a double click resets it. Holes stay open, nearer lines are brighter, and the scroll's axis points up. It follows the thumbnails' rule: shown by default only for smoke runs and published labelled segments, and only for a mesh inside the run folder. A snapshot carries the wireframes of up to 24 surfaces.
- **Loading.** Thumbnails and wireframes wait under a grey shimmer until they load, with no animation when the system asks for reduced motion. While the Ink stage runs, a rendered surface shows two placeholders where its maps will appear.
- **Text view.** `monitor RUN_FOLDER --text` prints the run in a terminal: the stages with their times, each surface's checks and scores, and each ink map beside its reversed control, drawn in characters on the forward map's scale, so the control is never stretched to look like ink. `--dither` adds ordered dithering; in a terminal it draws grey half blocks, two pixels to a character (`--color off` or `NO_COLOR` turns that off); `--watch S` prints it again every S seconds.

Files: `autopipeline/kit/autopipe_monitor.py`, `autopipeline/tests/test_autopipe_monitor.py`, `autopipeline/README.md` ("Watch a run").

## Hugging Face Space page

- Inline code on the page was dark text on a dark background in a dark-mode browser. It now has a light background in both modes, like the rest of the page.
- The Space's README links to AutoPipeline's released source.

Files: `autopipeline/space/app.py`, `autopipeline/space/README.md`, `autopipeline/tests/test_space.py`.

## Packaging

- Version 0.1.1. File: `autopipeline/pyproject.toml`.
