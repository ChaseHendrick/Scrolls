# AutoPipeline 0.1.5: interactive monitoring and trustworthy demo checks

This package is the published AutoPipeline 0.1.4 at commit `603fe14633201d6769776519646dc19cf203009f`, with the limited changes below. Earlier released branches and tags stay unchanged. The model registry, scientific settings and historical measurements are unchanged. A narrow cache-repair correction is included below; no new pipeline backend is included.

## Inspect and navigate a run

The read-only monitor now supports keyboard-accessible stage details, recorded failure reasons and geometry-review guidance, stage/event/text filters over the loaded log tail, viewer pause and manual refresh, and a run-record file list. A filtered tail is not a search of complete log history; recorded files are not validation passes. Geometry guidance does not identify bad regions or repair a surface.

Status and resume buttons prepare safely quoted bash/zsh commands for review and copying. They never execute a command. Resume is disabled for active, completed, unreadable or rule-refused runs and paused/stale viewers. Requests time out after 10 seconds; an independent freshness check clears a prepared resume command when the last successful summary is 30 seconds old, even when a request hangs. Snapshots retain inspection and filters but disable live actions because their run path is redacted. Headless CLI and summary JSON schemas are unchanged; no write endpoint was added.

## Fail a broken synthetic install demo

The demo used to print DEMO PASS when stage statuses matched even if a fake ink subprocess failed or its outputs were missing. It now requires two accepted synthetic surfaces, both fake-model exit codes equal to zero, and six nonempty map files inside the run folder. Missing dependencies and failed fake commands produce DEMO FAIL with log locations.

This demonstrates installation and orchestration with stand-in tools. It does not measure real VC3D geometry, ink-model accuracy, reading quality or community adoption. Historical benchmark scope and negative results remain in the README.

## Count each cache repair once

Empty-chunk repair timestamps were rounded to milliseconds. Rounding up could place an earlier repair after the next render's start, making the guard report it again and run an unnecessary third render. The existing reviewed correction stores these event times at full precision. Deterministic controls show the old behavior and confirm that a genuinely recreated false marker still invalidates its new render.

## Tests and presentation

Seven optional real-browser tests exercise controls, keyboard operation, phone-width layout, clipboard refusal, safe command quoting, read-only requests, snapshot privacy and recovery from a hung refresh. They use Playwright with an already installed system Chromium; otherwise they report skips and download nothing. Three demo regression tests cover missing, empty, external and failed-command outputs. The existing monitor progress fixture now emits a deterministic test callback instead of depending on subprocess timing; its assertions are retained.

The package README documents these behaviors and links the approved concept illustration at a fixed public commit. The illustration is not a scan or experimental result. No data, model weights, private research history or newly added pipeline backends are included.

The Git-less safety fixture now models its own repository boundary even when a managed host has an ancestor checkout; its refusal assertions remain. The optional MCP client test supports SDK 1.x through ClientSession and stdio_client while retaining the previously tested 2.x Client path. No server protocol or endpoint changed.

Version metadata changes from 0.1.4 to 0.1.5. This package does not assert a new Progress Prize form submission or award.
