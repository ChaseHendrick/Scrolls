# AutoPipeline 0.1.2: what changed since 0.1.1

The first release, AutoPipeline 0.1.0, is submission `progress-2026-10` (branch `submission/progress-2026-10`, commit `faada83287d39bbd4c7fd88c7ab0e75f3f1ff284`), and the first fix, 0.1.1, is `progress-2026-10-fix1` (branch `submission/progress-2026-10-fix1`, commit `153413691ec2ca794acdb3bf5784c0882a43e228`). Both stay as they were. This package, `progress-2026-10-fix2` (14 October 2026), is the whole of AutoPipeline again with these changes. No result of 0.1.0 or 0.1.1 changed.

## Fixes

- **Reserved segments are never planned.** A plan could name PHerc0841's `0841-ag405` as its published segment and score it, although that segment is the report surface of an ink comparison, scored once by a fixed recipe; only `score.transfer` refused it. Now a plan that names a reserved segment, by its key or its segment id, is refused when it is made, and a plan made by an earlier version that names one is refused when it runs. A checkout can reserve more segments, such as a held-out set kept for one final score, by listing them in `kit/data/autopipe-reserved.json` as a JSON list of `sample`, `segment` and `why`; this release ships without that file, and a malformed one stops planning rather than reserving nothing.
- **A repair needs a measured sheet switch.** With `qa.repair` set, a trace rejected for a reason the rule decided, such as its seating, was cut back to its seed's winding when its self-crossing count could not be measured, because that unmeasured check was read as a switch. Now a switch check that could not run is never a switch, and such a trace keeps its rejection uncut.
- **Model names are checked when a plan is made.** A misspelt name in `ink.models` was frozen into the plan and failed only at ink. The `autopipeline` tool's `plan`, and `python -m kit autopipeline plan`, now refuse a name that is neither one kit can fetch nor one registered on that machine.
- **Parallel downloads of one file no longer collide.** Workers that fetched the same object at once wrote through one temporary name, so one could rename it away from the other or leave the other a partial file. Each now writes its own temporary file, and a failed write leaves none behind.
- **The guides no longer give commands for files the release does not ship.** `docs/vc3d-headless.md` gave Modal commands for `scripts/vc3d/modal_vc3d.py`, and `AGENTS.md` said `scripts/vc3d/modal_autopipe.py` runs a handed-off ink job; neither file is part of the release. The guides now say so, and `AGENTS.md` says how to finish ink: run the same folder again where `KIT_INK_PYTHON` names a Python with torch and the planned models are registered.

Files: `autopipeline/kit/autopipe.py`, `autopipeline/AGENTS.md`, `autopipeline/docs/vc3d-headless.md`, `autopipeline/docs/vc3d-agents.md`, and tests in `autopipeline/tests/test_autopipe.py` and the new `autopipeline/tests/test_autopipe_download.py`.

## New since 0.1.1

- **Lossy volume copies are refused for ink.** The `render` tool refuses a community volcomp copy of a scan (under `dl.ash2txt.org/community-uploads/forrest/volcomp/`, or a local zarr whose level 0 uses the volcomp codec) unless `allow_lossy` is set, for geometry checks or previews; the receipt records it, and the `ink` tool warns on such a render or input. Released 2.5D ink models lost about a quarter of their ink and papyrus separation at the published setting of those copies (Community report: pscamillo, Discord, 10 September 2026), and villa PR #1704 says not to run the released models on them.
- **Ink records a direction readout.** With the forward and reversed maps, `ink.json` holds `direction`, the readout of `python -m kit dirtrend` (after freek_cool's rule, Community report, Discord, 31 August 2026): the forward over reversed area ratio at rising thresholds and whether it grows, counted where the input has CT in every layer. It never fails a run. Over 146 forward and reversed map pairs from 21 readers on labelled PHerc0841 crops it did not track the labels (Model output, 12 October 2026), so it is a record, not ink evidence.

Files: `autopipeline/kit/vc3d_agent.py`, `autopipeline/kit/vc3d_io.py`, `autopipeline/kit/dirtrend.py` (new), `autopipeline/kit/cli.py`, `autopipeline/scripts/vc3d/ink.py`, `autopipeline/docs/vc3d-agents.md`, and tests in `autopipeline/tests/test_vc3d_agent.py`, `test_vc3d_io.py` and the new `test_dirtrend.py`.

## Smaller changes

- `kit snap`'s help says that `--outer-iters` 0 or less also means 4 iterations, as in `recto_refine.c`. File: `autopipeline/kit/snap.py`.
- `scripts/firstletters/readers.tsv` also lists the public intermediate checkpoints of `ink_9um` (steps 10,000 to 60,000 of seeds 42 and 43), each with its URL and sha256. Nothing in AutoPipeline downloads them. File: `autopipeline/scripts/firstletters/readers.tsv`.

## Packaging

- Version 0.1.2. File: `autopipeline/pyproject.toml`.
