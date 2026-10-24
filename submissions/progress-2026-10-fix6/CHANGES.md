# AutoPipeline 0.1.6: one-screen monitor, console and opt-in released steps

This package follows AutoPipeline 0.1.5 at public commit `9e50d61b778a7ae4c36a12acbe32117feecfa847`. Earlier released branches and tags stay unchanged. A plan that names none of the new settings runs the same stages with the same default settings and models as before; one behavior change for plans that name `qa.repair` is listed under "Changed behavior". These are software changes. None of them is a new ink-accuracy result or a reading, and every map the pipeline makes is model output.

## The monitor on one screen, with a console

The monitor page now fits on one laptop screen with no page scroll: a header with the run's main numbers, a status row with an 11-stage rail, and five panels (Stages, Surfaces with a picker and the 3D wireframe, Ink and control, Log with Events, Tool log and Jobs tabs, and Console with Tools, Notes and Files). Below 1000 px wide or 600 px tall it stacks into one scrolling column. The look is monochrome with one signal color, in light and dark themes, with one text scale and even button spacing.

The console is new. Notes saves a Markdown note per run under the kit home, never in the run folder. Tools runs one command line at a time as a background job of the VC3D agent tools: `ap ...` for AutoPipeline, `kit ...` for any kit command, or a VC3D agent tool. The new agent tool `app_open` opens surfaces in the VC3D app, in a window (`display=true`) or offscreen. The console is on only on a loopback address, every request needs a token that only the server's own page holds, and requests from another origin are refused. `--read-only` turns it off; then the server accepts only GET and HEAD as before. Snapshots have no console; `--with-notes` adds the notes, read only. The console's tests use synthetic runs and stand-in tools; `app_open` has not been run against a real VC3D app.

## Why a trace failed qa

A rejected trace's qa record now lists every failed check with the value it measured and the threshold it was held to, and any exception that stopped the checks (`kit/qareasons.py`). The qa stage logs one line per trace and counts failures by kind and by check. `python -m kit.qareasons state STATE.json` rebuilds the same rows from a run's records.

## Opt-in steps

Each is off unless a plan names it, so existing plans keep their digests.

- **Crackle Check** (`crackle`): at report, the control-set gate of the released [Crackle Check](https://huggingface.co/spaces/SharpMeow/crackle-check) Space (rule ink-lens-gate-v1) on the mean of the planned models' forward maps against the mean of their reversed maps, on the whole surface and in 640 px tiles. Each surface gets the Space's answer (Yes, Maybe, No signal found, Too small) and a kept-ink overlay. A check that can fail, not a reading.
- **Published center lines** (`umbilicus.source` `centerlines`): the axis is the scan's line from the dataset [SharpMeow/vesuvius-center-lines](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines) at a pinned revision, its sha256 checked against `kit/data/centerlines.json`. A scan with no line is refused unless a fallback estimator is named.
- **Axis backends** (`umbilicus.estimator`, `umbilicus.shadow`, `umbilicus.polish`): villa's `vc_gen_umbilicus` as before, the scroll Center Finder (torch in the ink Python and its public script, `KIT_CENTRENET_PREDICT`), or `normals`, a numpy method on the normal grids. A list is tried in order and the record says which ran and why the others did not. Shadow backends are measured against the axis in use and never used downstream. The coverage polish moves an estimated axis toward the highest winding coverage within 8 mm; it never changes a catalog or published line.
- **Region crop** (`qa.crop`, also `kit meshqa crop`): a trace qa rejects for its crossings, seating or winding audit is cut instead of dropped whole: both quads of every located crossing, grown by `dilate` cells, and jump edges of the plan's prediction. Every piece above a minimum area is written as its own tifxyz, checked again by the same qa rule, and joins the run only if it passes. A kept piece is a place where these checks found nothing, not a verified sheet.
- **Edge extension** (`qa.extend`, agent tool `extend`): an accepted trace is grown past its edges with `vc_extend_edge`, in rounds, along the prediction's or the CT's normals, and the grown copy replaces the trace only when it passes qa again. `vc_extend_edge` comes from a VC3D fork branch and is not yet in villa's release; without it the step says so. It has no stop rule.
- **Stack check** (`stackcheck`): at report, public Scrolls' `kit stackcheck` over the accepted traces ordered by distance from the umbilicus. It needs public Scrolls' `kit/stackcheck.py` (`SCROLLS_PUBLIC_ROOT` or `../Scrolls`); otherwise the report says it did not run.
- **Trace budgets** (`trace.budget`): each trace writes its whole surface every few generations and gets a time budget from a cost model, so a trace stopped by its limit, a timeout or a cancel keeps its last complete surface as a partial result, which qa checks like any other.
- **Ink ensembles** (`ink.ensemble` method `zscore`, `python -m kit inkensemble`): each member map z-scored inside the mask, then combined by mean or trimmed mean, with optional weights.

`plan --new-defaults` adds the settings recommended for a fresh scroll where a plan names none: trace budgets, the Center Finder with villa's estimator as its fallback, and the coverage polish. It is never applied on its own.

## Swap a backend and trace an output

`python -m kit autopipeline backends` lists each swappable stage's backends and what this machine has for each, and `preflight` checks a plan's choices before a run. `why` says which stage, backend, inputs and settings made an output, `swap` makes a new run folder with one stage's backend changed, `diff` says whether two runs differ by that one swap only, and `graph` writes the run's provenance graph. `learn` reads finished runs' own records (plans, states, timings) to suggest settings, with no new compute and without reading maps or scores. The agent tool takes the same actions.

Two ink models are built in and need no download: `inkfilter` (Inkfilter's face-mix filter, fixed operations on the CPU) and `reader-v3` (Domenico Russo's Reader V3, MIT, through villa's koine inference; it needs torch, torchvision, monai, timm and einops in the ink Python). Reader v2 stays the default reader.

## Changed behavior

- A plan that names `qa.repair` without a method now uses `barrier` (`kit switchfix barrier`, which keeps the seed's part of a trace under a contact barrier) instead of `switchfix`. Name `{"method": "switchfix"}` for the earlier repair.
- A plan that gives a section's setting at the top level by its dotted name (such as `"trace.repeats"`) is refused when made; before, no stage read it and it was silently ignored.

## Package

The cut adds the modules these steps import, `kit/data/centerlines.json` and `docs/compute/modal-jobs.json`. It ships 46 test files; some added modules are covered only through the tests of the commands that call them. For the built-in Reader V3 model it ships `spaces/crackle-check/engine.py` and `spaces/crackle-check/koine_engine.py`, byte for byte the files of the public Crackle Check Space (huggingface.co/spaces/SharpMeow/crackle-check). It leaves out cloud job tools; the command line keeps only the commands AutoPipeline runs or a user runs on its output, plus `live` and `style` for the terminal look and `inkfilter` for the built-in model. Where a comment cites a file this package does not hold, it now says it is in the source repository. Three swap tests were updated to the current repair default and built-in models. Version metadata changes from 0.1.5 to 0.1.6. The Docker image was not rebuilt for this version. This package does not assert a Progress Prize form submission or award.
