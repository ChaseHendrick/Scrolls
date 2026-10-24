# Ink Lens: design

Status: design, 20 October 2026. Nothing here is built, deployed or measured yet. Labels follow
[`docs/NOVELTY.md`](../../docs/NOVELTY.md): Sourced fact, Community report, Measurement, Interpretation, Untested idea.

Chase asked on 20 October 2026 for something new and useful to the team and to people looking for text, built on his
daily ZeroGPU minutes and working with VC3D, and that day also asked that all his tools work with the organizers' and
the community's.

## What it is, in one paragraph

A text finder working in VC3D picks a region of a segment. Ink Lens renders (or reads) that region's surface volume,
and one ZeroGPU call runs an openly licensed 9 um ink model on it over three nearby depth windows and in both depth
orders, the community's reverse-depth control. The region's own reversed map sets the ink threshold: only ink stronger
than 99 % of what the control produces is kept, and the region gets a status that can fail ("no ink above control").
The Scroll Text Reader then reads the kept map, with the reversed map as its control map, and its letter candidates
become 3D pins on the segment. The client writes VC3D's own files into the segment folder: a single-channel PNG plus an
`ink-detections.json` record, so the map appears in VC3D's Ink Detection panel on the right place of the segment, and a
VC3D point collection for the pins. Everything shown is model output, not a reading.

## Why this and not something else

What exists (checked 20 October 2026):

| Thing | What it does | What it lacks for this job |
| --- | --- | --- |
| `SharpMeow/autopipeline-ink` (ours, ZeroGPU) | `ink_9um` on a crop of a released segment or an upload, both depth orders in one call, AUC where labels exist (Sourced fact: its `inkspace.py`, AutoPipeline fix5 package) | No VC3D output, one depth window, no threshold from the control, no letter step, uploads only up to 768 px |
| `SharpMeow/scroll-lens` (ours, ZeroGPU) | Organizers' 3D DINO, 3D ink and surface models on 128 or 256 voxel cubes | A cube is smaller than one letter; no segment, no VC3D files |
| `gmDevi/vesuvius-ink-sweeps` | A static page of scored ink sweeps | Not a tool on your own region |
| VC3D on villa main `8aa507c12` | Shows existing ink maps listed in `SEGDIR/ink-detections.json` (catalog JPEGs) | Runs no ink model; the agent bridge has `render.tifxyz` and `points.*` but no ink method (Sourced fact: `apps/VC3D/agent_bridge/rpc_description.json`, 120 methods) |
| Reader V3 (Domenico Russo, 19 Oct 2026, MIT) | A drop-in `ink_9um` checkpoint run from the command line | Not packaged for VC3D or a Space |

Searches: Hugging Face Spaces API for "vesuvius", "herculaneum", "ink-detection", "vc3d", "scroll", "papyrus" and "ink";
VC3D source on villa main; the community Discord archive in Scrolls-private (grep for ink overlays, VC3D plugins and
inference in VC3D). GitHub code search is not reachable from this container, so a private or unindexed tool could
exist. Interpretation: no public tool found runs an ink model on a VC3D user's own region and hands the result back to
VC3D as its own files, and none sets the ink threshold from the reverse-depth control per region.

Alternatives considered for the same budget:

- **3D ink as a VC3D overlay volume** (Scroll Lens's 3D ink model written as a small OME-Zarr that VC3D's
  `viewer.set_overlay` can show). Useful to check whether a segment sits on the inked sheet, but a 256 voxel cube is
  0.6 mm, smaller than a letter, so it does not help a text finder find text. Kept as a later add-on.
- **DINO click search inside VC3D.** Same cube-size limit.
- **A label-free choice of depth window** (pick the window where forward beats reverse most). Choosing on the control
  weakens it as a control. Rejected; Ink Lens averages three fixed windows instead, which the `ink_9um` card itself
  recommends ("Averaging predictions over a few nearby z windows also works as a simple ensemble", Sourced fact,
  `huggingface.co/scrollprize/ink_9um` README, read 20 Oct 2026).

Final choice: the proposed control-checked ink lens, with three refinements found in this check: the depth-window
average, a threshold set from the control's own distribution (not a pixel-by-pixel difference, which would punish ink
that also shows from the other side), and a transparent single-channel PNG so only kept ink covers the segment.

## The model

All four 9 um-era candidates are MIT (Sourced fact, model cards and LICENSE files read 20 Oct 2026):
`scrollprize/ink_9um`, `domenicor046/reader-v2`, `domenicor046/reader-v3`, TAUIL-Abd-Elilah's d9v2
(`github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search`, LICENSE: MIT). Hecate is MIT too but its PHerc0841
exposure ([`docs/results.json`](../../docs/results.json) `held_out`) and 2.4 um size make it a poor default.

Public held-out evidence, PHerc0841 crops with `--inner 64` (Measurement, public `docs/results.json`, source
`docs/logs/2026-10-07-community-scan.md` and `scripts/experiments/2026-10-07-cloud/tricks/results.json`):

| Reader | w00 as stored / reversed | ag896 | ag405 |
| --- | --- | --- | --- |
| `ink_9um` seed 42 step 75,000 | 0.806 / 0.536 | 0.659 / 0.558 | 0.784 / 0.642 |
| d9v2 | 0.899 / 0.586 | 0.823 / 0.532 | 0.832 / 0.657 |
| Reader v2 | 0.927 / 0.729 | 0.797 / 0.599 | not scored |
| Reader V3 | no public measurement of ours; author-reported held out | | |

**Default: d9v2.** It is MIT, held out on all three PHerc0841 segments (its `test.txt`), has the best forward AUC with a
low reversed AUC in our public numbers, and is a drop-in `ink_9um` checkpoint for villa's flat inference
(`vesuvius.ink_detection.inference.infer`: 17 x 128 x 128 patches, overlap 0.5, Hann blending), the same engine the
autopipeline-ink Space already runs on ZeroGPU. Reader v2's high reversed AUC on w00 (0.729) would make the
control-set threshold eat most of its ink. **Also selectable:** `ink_9um` seed 42 (the organizers' reference) and
"both" (d9v2 and `ink_9um` in one call, for agreement; doubles the cost). **Reader V3** is added only after a public
PHerc0841 check of ours (it runs through `koine_machines` on villa branch `merge-ink-pipelines` and its checkpoint is a
full pickle, so it is loaded sha-pinned with `weights_only=True` tried first).

Every checkpoint is downloaded by URL at a pinned revision and refused unless its SHA-256 matches, as in Scroll Lens.
d9v2 and `ink_9um` load with `torch.load(weights_only=True)`; a checkpoint that needs more is refused.

## One call, and its GPU seconds

The input is a uint8 surface volume at about 9.6 um, layers first, 21 layers (the `ink_9um` training window; 17 used
per pass). Three depth windows (layer starts 0, 2 and 4 of the 21) times two orders (as stored, reversed) are six
passes over the same patches, batched together.

Two changes from autopipeline-ink make one call fit in a few seconds:

1. villa's per-patch robust normalisation runs on the GPU, batched (the autopipeline-ink Space ran it on the CPU inside
   the call: about 0.03 s of its 0.06 s per patch, Sourced fact, `inkspace.py` comment of 13 Oct 2026). The port must
   match villa's CPU result within a stated tolerance on a test volume.
2. fp16, batch 64, model on the device once per process.

Patches per pass at stride 64: 225 for 1024 x 1024 px (about 9.8 mm square at 9.6 um, three or four lines of text),
529 for 1536 px, 961 for 2048 px.

| Region | Passes | Patches | Estimate at 3 to 6 ms per patch, plus 2 s | Requested duration |
| --- | --- | --- | --- | --- |
| 1024 px, 1 window | 2 | 450 | 3 to 5 s | 15 s |
| 1024 px, 3 windows (default) | 6 | 1,350 | 6 to 10 s | 20 s |
| 1536 px, 3 windows | 6 | 3,174 | 12 to 21 s | 30 s |
| 2048 px, 1 window | 2 | 1,922 | 8 to 14 s | 25 s |

Untested idea: 3 to 6 ms per patch. The measured anchor is 0.01 to 0.02 s per patch for the forward pass at batch 1 on
half an RTX Pro 6000 (Sourced fact, same `inkspace.py` comment); batching usually cuts that several fold. The
requested duration is `ceil(4 + patches x 0.012)`, capped at 40 s, and a region that would need more is refused with a
smaller size suggested. The receipt records the measured GPU time, so the first call calibrates the rest.

Chase's 300 s: one 1024 px default call on a public sample to measure (about 10 s), then about 25 default regions.
ZeroGPU admits a call only while the requested duration is left in the caller's quota, and bills what is used (as
Scroll Lens observed, its README). When the quota is gone, the Space falls back to the CPU only for 512 px, one window;
anything larger is pointed to local mode.

**Local mode** runs the same `engine.py` on the user's machine (CUDA, Apple MPS or CPU), with no Hugging Face account.
It is the route for whole segments and for anyone who does not want to send a region to a Space. The Space keeps
nothing: inputs are read into memory and never written to disk, outputs go back in the response.

## The control check

Untested idea, to be frozen in `docs/prereg/2026-10-20-ink-lens-gate.md` before any map of it exists:

- F and R are the three-window means of the as-stored and reversed maps, both in villa's 0 to 1 probability.
- T is the 99th percentile of R over the region's papyrus pixels (pixels whose middle layer is above the region's
  5th percentile of CT, so air does not lower T).
- Kept ink: F > T. Excess: the fraction of papyrus pixels with F > T, divided by 0.01 (the fraction R itself puts above
  T by construction).
- Status: `ink` when excess >= 3, `weak` when 1.5 <= excess < 3, `none` below 1.5, `too_small` under 100,000 papyrus
  pixels (about 3 mm square, autopipeline-ink's noisy-AUC floor).

Why it can fail: on a region with no text, or where the model reads the reversed volume as well as the stored one, the
excess sits near 1 and the status is `none`. Checks in the build, all on public data, CPU in the container:

1. PHerc0841 w00, ag896 and ag405 crops (held out from d9v2 and `ink_9um`): kept ink must hold a larger share of the
   labeled ink pixels than of the labeled background pixels, and the status must be `ink`. Report both shares and the
   gated-map AUC beside the raw AUC and its reversed control.
2. Swapped input (R fed as F): status must not be `ink`.
3. A region off the papyrus or in a gap between windings: status must be `none` or `too_small`.

Estimated cost of the checks: 3 crops of 640 px, 6 passes, 81 patches each, about 1,460 patches at about 0.1 s on the
container CPU, under 3 minutes (rule 11 keeps it local).

## Letter pins

The Scroll Text Reader (`kit/letterread.py`, public, numpy only, CPU, outside the GPU call) reads the kept map with
`letter_mm` (default 3.0) and `um_per_px` (the map's voxel size), the released `letters-v2-ccby` weights, and the
reversed map as its control map. Its nulls (tile-shuffled and phase-randomized copies) and its status travel with the
result. Pins are written only for letters above the reader's confidence floor when its status is `strong` or `weak`;
otherwise the result says why there are none. A 1024 px region holds three or four lines, so many regions will give
`too_few`: that is the reader working, not failing. Letter strings stay in the sidecar JSON as hypotheses for a person.

Map pixel to 3D: map pixel (r, c) at the 9.6 um grid becomes render pixel (4r, 4c) at 2.4 um (or (r, c) for a native
9.4 um render), then tifxyz grid coordinates by the segment's `scale`, then a voxel position by bilinear interpolation
of the `x`, `y`, `z` bands (holes at -1 refused). Pins sit on the surface (the middle layer).

## VC3D files it writes

All rules cited to villa main `8aa507c12` (Sourced fact unless marked).

| File | Content | VC3D source |
| --- | --- | --- |
| `SEGDIR/inklens/<run>.png` | Single-channel 8-bit PNG covering the whole segment canvas: 0 outside the region and where F <= T, else F rescaled to 1 to 255. The canvas aspect equals the tifxyz grid's (VC3D stretches the image over the whole grid and checks it) | `cv::imread(..., IMREAD_UNCHANGED)` and single-channel test, `InkDetectionOverlayController.cpp:512-536, 140-173`; single-channel pixels get alpha = value, so 0 is transparent, `:546-580`; stretch over the grid `:395-437`; aspect check `:584` |
| `SEGDIR/inklens/mosaic.png` | Running maximum of every run on this segment, so regions add up into one layer | same |
| `SEGDIR/ink-detections.json` | Existing records kept; one record per run and one for the mosaic: `local_file`, `label` ("Ink Lens d9v2 <status>"), `segment_id` (no `segment_long_id`, so a catalog JPEG of the segment does not hide the PNG), `sample_id`, `artifact_type` | `OpenDataSegmentCache.cpp:651-694` (a non-empty file replaces the catalog list, so existing records, or the `catalog-origin.json` list when the file has none, must be merged, never overwritten), `InkDetectionOverlayController.cpp:41-50, 243-253` (JPEG groups), `:502-510` (key match) |
| `SEGDIR/inklens/<run>.pins.json` | VC3D point collection `{"vc_pointcollections_json_version": "1", "collections": {...}}`, one collection "Ink Lens <run>", points `{p: [x, y, z], creation_time (ms), wind_a: null}`, point ids after every saved one | `core/src/PointCollections.cpp:36-119` (`p` required, `wind_a` may be null), `:226` (ms), `:571-662` |
| `SEGDIR/inklens/<run>.json` | Receipt: model and SHA-256, villa commit, region box in render pixels and grid cells, windows, T, excess, status, Text Reader result, GPU seconds, device | ours |

Loading a point collection file in VC3D replaces all current collections (`PointCollections.cpp:647`, `clearAll`). So
with the agent bridge the client first saves the current collections (`points.save_json`), merges the new collection
in, and loads the merged file (`points.load_json`); without the bridge it tells the user that File > Load replaces.

Untested idea: that VC3D's GUI shows the PNG on the segment as the source says. The first build step after tests is a
headless check in an offscreen VC3D with the bridge on public PHerc0139 w035.

## Inputs a VC3D user has

1. **A published segment** (open-data bucket): read the region straight from its `surface-volumes/<volume>.zarr` over
   HTTPS; a 2.4 um volume is pooled to 9.6 um exactly as the organizers' `prepare_9um_isotropic_input.py` does (XY
   pyramid level 2, 4x mean over z).
2. **A local tifxyz segment and its volume** (what VC3D tracing makes): `vc_render_tifxyz --segmentation SEG --volume VOL
   --scale 1 -n 84 --crop-x X --crop-y Y --crop-width W --crop-height H --zarr-output OUT`, then the same pooling
   (`apps/src/vc_render_tifxyz.cpp:1256-1276, 1858-1859`). The binary ships with VC3D builds.
3. **Through the agent bridge**: `render.tifxyz` with `outputFormat` `zarr` renders a whole segment (it has no crop
   field), so for a region the client calls `vc_render_tifxyz` itself and uses the bridge only to find the active
   segment (`segments.list`), the volume, and the view center (`canvas.get_cursor_volume_point`).
4. **An existing surface volume**: a `.zarr`, multi-page `.tif` or `.npy`, layers first.

The region box is given in render pixels of the segment (what `vc_render_tifxyz` writes at scale 1), or as a center
point plus a size; `--from-vc3d` takes the current cursor point.

## How VC3D triggers it

- **Command line** (works today): `python inklens.py run --segment SEGDIR --volume VOL --box X Y W H [--space | --local]
  [--reader d9v2|ink_9um|both] [--windows 3] [--bridge NAME] --json`. Exit 0 with status, 3 when the status is `none`,
  2 on a refused input. `--dry-run` prints the patch count, the GPU estimate and the files it would write.
- **Agent bridge and MCP**: an agent chains `vc3d_list_segments`, `inklens run --bridge`, `vc3d_load_points_json`,
  `vc3d_center_on_point`. The Space's own tools are an API and an MCP server, like Scroll Lens's: `lens_region`
  (an `.npz` surface volume in, maps, status and pins out), `list_samples`, `estimate`.
- **VC3D plugin system**: being built today on a villa branch, `vc3d-plugins`, which did not exist yet at the time
  of writing. The CLI's JSON contract above is what a plugin entry would call; its
  manifest is written when that system's format is known (Untested idea).
- **Missing in VC3D** (a small villa PR to draft, Chase posts): an `ink.reload` bridge method so the Ink Detection panel
  rereads `ink-detections.json` without reopening the segment.

## Public data and rules

- The Space's samples come only from autopipeline-ink's existing allow-list (PHerc0841 and PHerc0139 labeled
  segments), with the 64 px inner edge and their AUC. No prize-eligible scroll in samples, media or gallery.
- Users' regions are never stored or logged. Our own runs on target or eligible scrolls belong in Scrolls-private.
- Deployment needs Chase's yes (rule 8: a new Space). A free account may host 2 ZeroGPU Spaces (Sourced fact, Hugging
  Face ZeroGPU docs as recorded in Scrolls-private's `space-file-list.md`, read 14 Oct 2026), and SharpMeow already has
  `autopipeline-ink` and `scroll-lens`. Options for Chase: replace autopipeline-ink's app with Ink Lens (it covers its
  samples and uploads), or add Ink Lens as a tab and tools inside Scroll Lens. No Hugging Face credential exists in
  this container; nothing is deployed from here.

## Files to build

| File | What |
| --- | --- |
| `spaces/ink-lens/README.md` | Space card (Gradio 6.28.0, Python 3.12, `zero-a10g`, MIT model links), use, tools, checks, credits |
| `spaces/ink-lens/app.py` | Page, one `spaces.GPU` call per region with the computed duration, CPU fallback for small regions, API and MCP tools |
| `spaces/ink-lens/engine.py` | Pinned downloads with SHA-256, safe load, GPU-batched villa normalisation, sliding window with Hann blending, three windows, both orders; CUDA, MPS or CPU |
| `spaces/ink-lens/gate.py` | Papyrus mask, T, excess, status (numpy only) |
| `spaces/ink-lens/vc3dout.py` | Canvas PNG and mosaic, `ink-detections.json` merge, point collection, grid-to-voxel interpolation, receipt |
| `spaces/ink-lens/inklens.py` | Client CLI: inputs, `vc_render_tifxyz` call, 9.6 um pooling, Space or local run, Text Reader pins, VC3D files, bridge |
| `spaces/ink-lens/bridge.py` | Minimal JSON-RPC client for the VC3D agent bridge socket |
| `spaces/ink-lens/requirements.txt`, `LICENSE`, `NOTICE` | Pins as Scroll Lens; Apache 2.0 code; MIT models credited |
| `tests/test_inklens.py` | Gate math and its failing cases, pooling equal to the organizers' rule, GPU normalisation equal to villa's CPU result, canvas aspect, record merge keeps existing records, point collection schema, grid-to-voxel mapping, duration formula |
| `docs/prereg/2026-10-20-ink-lens-gate.md` | The control check above, frozen before any map |
| `docs/tools/ink-lens.md` | Tool page (`python -m kit.tooldocs new`), with "For agents" |
| `docs/MAP.md`, `GLOSSARY.md`, `docs/HANDOFF.md` | Map row; terms "Ink Lens" and "control-set threshold"; handoff row |
| `docs/releases.json` | Only at release, after Chase's yes, through `python -m kit releases add` |
