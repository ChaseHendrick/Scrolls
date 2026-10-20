# ink-lens: control-checked ink maps of your own region, written back into VC3D

Runs an openly licensed 9 um ink model on one region of a VC3D segment in both depth orders over three depth windows, keeps only ink above the region's own reverse-depth control, and writes the overlay and letter-candidate pins as VC3D's own files.

| Field | Value |
| --- | --- |
| Id | `ink-lens` |
| Status | Experimental |
| Kind | app, agent tool, script |
| Area | Ink maps and models |
| Run | `python3 spaces/ink-lens/inklens.py run` (a region of a segment), `python3 spaces/ink-lens/inklens.py demo SAMPLE` (a public sample end to end), `python3 spaces/ink-lens/inklens.py estimate H W`, `python3 spaces/ink-lens/inklens.py samples`, `python3 spaces/ink-lens/app.py` (the Space page, API and MCP), `python3 spaces/ink-lens/engine.py estimate H W`, `python3 spaces/ink-lens/tools/check_gate.py OUT.json` (the preregistered check), `python3 spaces/ink-lens/tools/deploy.py OWNER/NAME` |
| Code | `spaces/ink-lens/inklens.py` (the client), `spaces/ink-lens/engine.py` (model, windows, both orders), `spaces/ink-lens/gate.py` (the control-set threshold), `spaces/ink-lens/vc3dout.py` (VC3D's files), `spaces/ink-lens/volio.py` (reading regions), `spaces/ink-lens/bridge.py` (VC3D agent bridge), `spaces/ink-lens/app.py` (the Space), `spaces/ink-lens/tools/deploy.py`, `spaces/ink-lens/tools/check_gate.py`, `spaces/ink-lens/samples.json`, `spaces/ink-lens/vc3d-plugin.json` (draft plugin manifest), `spaces/ink-lens/README.md` (the Space card) |
| Tests | `tests/test_inklens.py`, 43 tests (5 need torch, tifffile or `VILLA_SRC` and skip without them) |
| Needs | Python 3.10 or newer, numpy. Space mode: gradio_client and huggingface_hub, and the user's own Hugging Face token. Local mode and the Space: torch 2.13.0 and the pins in `spaces/ink-lens/requirements.txt`; villa's `vesuvius/src` at `8aa507c12` and the checkpoint are downloaded once (or `VILLA_SRC`, `INKLENS_D9V2`, `INKLENS_INK_9UM`). Pins: tifffile, and this repository's `kit/` (the Scroll Text Reader). Rendering a region: `vc_render_tifxyz` from a VC3D build. Label scoring: zarr |
| Runs on | ZeroGPU (Space mode, estimate only until deployed: 6 to 10 s for a 1024 px region, 1,350 patches). CPU, 4 cores of a Claude cloud container: 0.14 to 0.30 s per patch, a 640 px crop with three windows (486 patches) in 112 to 148 s (measured 2026-10-20). CUDA or Apple MPS in local mode: not measured |
| Network | `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (samples, labels and tifxyz meshes), `github.com` and `codeload.github.com` (villa at a pinned commit; d9v2 and the letter weights from release assets), `huggingface.co` (`ink_9um`; the Space in Space mode). Space mode sends the region (an `.npz`) to the Space; local mode sends nothing |
| Writes | Into the segment folder: `inklens/RUN.png`, `inklens/mosaic.png`, `inklens/RUN.pins.json`, `inklens/RUN.json`, `inklens/RUN.letters.json`, and `ink-detections.json` (merged, existing records kept). Downloads under `$INKLENS_CACHE` (default `TMPDIR/ink-lens`, about 0.6 GB for both readers and villa). The Space writes result `.npz` files under `TMPDIR/ink-lens-out` and keeps no upload. `demo --vc3d-out DIR` writes a copy of the sample's tifxyz mesh into DIR |
| Go-ahead | Needed to deploy the Space (`tools/deploy.py`, a new Space under rule 8) and to spend Chase's ZeroGPU quota. Not needed for local mode or the tests |
| Released | Not released: code on branch `claude/ink-lens` since 2026-10-20; the Space is not deployed |
| License | Apache 2.0 for the code ([`spaces/ink-lens/LICENSE`](../../spaces/ink-lens/LICENSE), [`NOTICE`](../../spaces/ink-lens/NOTICE)); d9v2 and `ink_9um` MIT; the scans CC BY-NC 4.0 |
| Checked | 2026-10-20 against commit `3c2445e` |

## What it does

A text finder working in VC3D wants to know whether a part of a segment holds ink, without exporting the whole
segment, installing villa and running a model for an hour. Ink Lens takes one region (about 1 cm square), renders only
that region with `vc_render_tifxyz` (or reads it from an existing surface volume), pools it to the 9.6 um grid the
models were trained on, and runs a 9 um ink model on it six times: three nearby 17-layer depth windows, each with the
layers as stored and reversed. Reversed depth is the community's control: a model that reads ink in depth order
should do worse on it.

The reversed map sets the threshold. T is the 99th percentile of the reversed map over the region's papyrus, so the
control itself puts 1 % of its pixels above T. The region's status is the share of papyrus the stored-order map puts
above T, divided by that 1 %: `ink` at 3 or more, `weak` from 1.5, `none` below 1.5, `too_small` under 100,000 papyrus
pixels, `unreadable` when a map is broken. A region without text, or one where the model sees as much in the reversed
volume, gets `none`: the check can fail, and a failing region writes an empty overlay.

The kept map then goes to the Scroll Text Reader ([letterread](letterread.md)), with the control's own kept map as its
control map. When the reader's controls pass (`strong` or `weak`), each kept letter's center becomes a 3D point on the
segment surface. The client writes VC3D's own files into the segment folder: a transparent single-channel PNG over
the whole segment canvas (VC3D draws a gray image with alpha equal to the pixel value), a running mosaic of all
regions, records for both in `ink-detections.json`, and a VC3D point collection for the pins.

The model runs either on a Hugging Face ZeroGPU Space with the user's own token (their quota pays; Chase's budget is
not touched by other users), or on the user's machine (`--local`, CUDA, MPS or CPU, no account). The Space is the same
engine with a page, an API and MCP tools, following [Scroll Lens](scroll-lens.md).

Everything Ink Lens shows is model output, not a reading. The letter strings stay in a sidecar file as hypotheses for a
person.

## When to use it

- To check a region of your own segment for ink, with a control, from VC3D or a script, in seconds of GPU time.
- To mark letter-candidate places on a segment as VC3D points for a person to look at.
- To compare d9v2 and `ink_9um` on the same region (`--reader both`).

Do not use it:

- On a whole segment: run villa's flat inference ([AutoPipeline](autopipeline.md)), or Ink Lens `--local` region by
  region.
- To score a map against labels with confidence intervals: use [auc](auc.md).
- To publish anything about a target or prize-eligible scroll: that belongs in Scrolls-private (hard rule 1).
- As a reading: the status says ink stands above the control, not what it says.

## Quick start

```bash
cd spaces/ink-lens
python3 inklens.py estimate 1024 1024 --json
python3 inklens.py demo 0841-w00 --local --score --vc3d-out /tmp/inklens-demo --json
```

The demo reads the public PHerc0841 w00 crop from the open-data bucket, runs d9v2 on this machine, scores the kept
ink against the published labels and writes VC3D's files into a downloaded copy of the segment's tifxyz mesh under
`/tmp/inklens-demo`. It worked when the exit code is 0 and `gate.status` is `ink`; open that folder as a segment in
VC3D to see the overlay. Excerpt of the run on 2026-10-20 (CPU, 4 cores, 188 s):

```text
"gate": {"rule": "ink-lens-gate-v1", "papyrus_px": 387710, "threshold": 0.527333, "excess": 15.4345, "status": "ink"}
"labels": {"shares": {"ink_kept_share": 0.53927, "background_kept_share": 0.03108}, "auc_forward": 0.9147, "auc_reverse": 0.5955}
"letters": {"status": "too_few", "letters_kept": 1, "null_letters_kept": [0, 0, 0, 0]}
```

It wrote a 4760 x 4220 overlay (the segment's whole canvas), the mosaic, two records in `ink-detections.json` and the
receipt; the letter read ended `too_few`, so no pins. Scrolls-private's VC3D format checker (`kit.villafmt`
`check_inkmaps` and `check_tifxyz`) accepts that folder: records found, key matched, aspect within 2 %.

## Checks and controls

The rule was frozen before any map existed: [`docs/prereg/2026-10-20-ink-lens-gate.md`](../prereg/2026-10-20-ink-lens-gate.md)
(`ink-lens-gate-v1`). Three checks on public data, run with `tools/check_gate.py` (d9v2, three windows, CPU):

1. The three PHerc0841 640 px crops, held out from d9v2 and `ink_9um`: status `ink`, and kept ink covers a larger share
   of labeled ink than of labeled background.
2. The same crops with the two maps swapped: no crop may be `ink`.
3. The corner of w00 (rows and columns 0 to 640), off the papyrus: `none`, `too_small`, `unreadable`, or refused.

Results, 20 October 2026 (d9v2, three windows, CPU; [`scripts/experiments/2026-10-20-ink-lens-gate/results.json`](../../scripts/experiments/2026-10-20-ink-lens-gate/results.json)):

| Crop | Status | Excess | T | Labeled ink kept | Labeled background kept | Raw AUC / reversed (3 windows) | Swapped |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PHerc0841 w00 | ink | 15.4 | 0.527 | 53.9 % | 3.1 % | 0.915 / 0.596 | none (excess 0.0) |
| PHerc0841 ag896 | ink | 21.2 | 0.490 | 52.3 % | 7.1 % | 0.830 / 0.561 | none (excess 0.0) |
| PHerc0841 ag405 | ink | 17.6 | 0.552 | 49.7 % | 7.1 % | 0.839 / 0.684 | none (excess 0.0) |

All three checks passed. Check 3 passed by refusal: the corner of w00 is all zero, so the engine refused it and the
gate itself was not exercised off the papyrus; the swapped check is the one that shows the gate failing (excess 0.0).
The three-window raw AUCs sit slightly above the public single-window d9v2 numbers (0.899, 0.823, 0.832); that is a
development comparison on the same label-chosen windows, not a held-out gain.

Other controls in every run: the Space's status is recomputed by the client from the maps it returns and the run is
refused when they differ; the letter pins need the Scroll Text Reader's own nulls and control map to pass. The engine's
maps equal villa's own flat inference on a real 256 px crop of w00 to 2.4e-7 (both depth orders, CPU, 2026-10-20), and
its batched normalisation equals villa's `normalize_robust` exactly in the tests.

Claim label: Model output for every map, status and check number (the check numbers come from development windows
chosen with the labels, not a blind test); Untested idea for the GPU timings until the Space runs.

## Commands and options

### `inklens.py run`

```text
inklens.py run --segment SEGDIR (--surface-volume PATH | --volume OME_ZARR) --box X Y W H [--um-per-px UM]
               [--local | --space OWNER/NAME] [--reader d9v2|ink_9um|both] [--windows 3|1] [--no-pins]
               [--letter-mm MM] [--bridge [NAME]] [--dry-run] [--json]
inklens.py run --from-vc3d [--bridge NAME] --volume OME_ZARR [--size 1024] ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--segment` | none | The tifxyz segment folder (meta.json, x.tif, y.tif, z.tif) |
| `--surface-volume` | none | A surface volume covering the whole segment canvas, layers first (zarr, `.npy`, `.npz`, `.tif`) |
| `--volume` | none | The scan's OME-Zarr; only the region is rendered with `vc_render_tifxyz` |
| `--render-binary` | `vc_render_tifxyz` on PATH | Path to `vc_render_tifxyz` |
| `--um-per-px` | from the OME-Zarr | Pixel size of the render in micrometers; sets the pooling (4 for 2.4 um, 1 at 7 um and above) |
| `--box` | none | Region `X Y W H` in render pixels of the segment at scale 1 |
| `--from-vc3d` | off | Center the region on VC3D's cursor (needs a running VC3D with `--agent-bridge`) |
| `--size` | 1024 | With `--from-vc3d`: the region side at 9.6 um |
| `--bridge` | off | Merge the pins into VC3D's point collections and center the view; a name or socket path, or empty for the newest bridge |
| `--local` | off | Run the model on this machine |
| `--space` | `SharpMeow/ink-lens` | The Space to call with your token |
| `--token` | `HF_TOKEN` or the stored login | Your Hugging Face token |
| `--device` | best available | Local mode: `cuda`, `mps` or `cpu` |
| `--reader` | `d9v2` | `d9v2`, `ink_9um` or `both` |
| `--windows` | 3 | Depth windows averaged: 3 or 1 |
| `--no-pins` | off | Skip the Scroll Text Reader and the pins |
| `--letter-mm` | 3.0 | Letter height for the reader, in millimeters |
| `--dry-run` | off | Print the plan, the patch count and the GPU estimate; run nothing |
| `--json` | off | Print one JSON object |

### `inklens.py demo`

| Option | Default | Meaning |
| --- | --- | --- |
| `SAMPLE` | required | A sample id from `samples` (`0841-w00`, `0841-ag896`, `0841-ag405`, `0139-w035`) |
| `--size` | the 640 px crop | A smaller square at the crop's center |
| `--at` | none | `ROW COL`: the square's top-left corner on the segment instead |
| `--vc3d-out` | none | Download the sample's tifxyz mesh here and write VC3D's files into it |
| `--score` | off | Score the maps and the kept ink against the published labels |
| `--save-maps` | none | Also save forward, reverse, kept and the CT layer as `.npz` |
| Common options | | `--local`, `--space`, `--token`, `--device`, `--reader`, `--windows`, `--no-pins`, `--letter-mm`, `--dry-run`, `--json` as for `run` |

### `inklens.py estimate`, `inklens.py samples`, `engine.py`

| Option | Default | Meaning |
| --- | --- | --- |
| `estimate H W` | | Patches and requested GPU seconds for an H x W region at 9.6 um; `--windows`, `--reader`, `--json` |
| `samples` | | The public samples as JSON |
| `engine.py estimate H W` | | The same estimate from the engine; `--windows`, `--reader` |
| `engine.py fetch READER` | | Download and check one checkpoint into the cache |

### `tools/check_gate.py`, `tools/deploy.py`

| Option | Default | Meaning |
| --- | --- | --- |
| `check_gate.py OUT` | | Run the preregistered check and write every number to OUT |
| `--maps` | none | Also save each crop's maps as `.npz` (keep them out of git) |
| `--device` | best available | `cuda`, `mps` or `cpu` |
| `deploy.py files` | | The Space's files with SHA-256 |
| `deploy.py stage DEST` | | Copy them into DEST |
| `deploy.py OWNER/NAME` | | Check the login, list differences, ask y/N, upload, ask for `zero-a10g` |
| `--private` | off | Create the Space private |

### Deploying the Space (Chase only, after a yes)

A new Space needs Chase's yes (rule 8). A free account hosts two ZeroGPU Spaces and SharpMeow has `autopipeline-ink`
and `scroll-lens`, so either upgrade, or replace one Space's app (deploy.py lists the old files it leaves behind).

```bash
git fetch origin && git checkout claude/ink-lens          # or main, once merged
python3 -m pip install huggingface_hub gradio_client numpy
hf auth login                                              # once; or export HF_TOKEN=hf_... (write scope)
python3 spaces/ink-lens/tools/deploy.py files              # what will be sent, with SHA-256
python3 spaces/ink-lens/tools/deploy.py SharpMeow/ink-lens # new Space; or SharpMeow/autopipeline-ink to replace it
# after the Space shows "Running": one calibration call on a public sample (requests 21 s of ZeroGPU)
python3 spaces/ink-lens/inklens.py demo 0841-w00 --space SharpMeow/ink-lens --score --json
```

In a cloud session with `HF_TOKEN` set, the same commands work; `deploy.py` still asks y/N on the terminal.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `INKLENS_SPACE` | `SharpMeow/ink-lens` | The Space the client calls |
| `HF_TOKEN` | the stored `hf auth login` token | Your Hugging Face token, so your ZeroGPU quota pays |
| `INKLENS_CACHE` | `TMPDIR/ink-lens` | Where villa and the checkpoints are downloaded |
| `VILLA_SRC` | unset | A local villa `vesuvius/src` instead of the pinned download |
| `INKLENS_D9V2`, `INKLENS_INK_9UM` | unset | A local copy of a checkpoint (its SHA-256 is still checked); read as `INKLENS_` plus the reader name in capitals |
| `SPACES_ZERO_GPU` | set by Hugging Face | The Space attaches the GPU through `spaces.GPU` when it is true |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `engine.Engine(readers, models=None).run(volume, reader, windows, device)` | dict: `forward`, `reverse` (float32, 0 to 1), `per_reader`, `patches`, `seconds`, `window_layers` | `EngineError` | One region; `models` takes stand-ins |
| `engine.run_reference(volume, predict, windows)` | `{"forward", "reverse"}` | | The same algorithm in numpy with any predict function |
| `engine.estimate(h, w, windows, reader)` | dict with `patches`, `gpu_seconds_requested` | `EngineError` | |
| `gate.decide(F, R, ct_middle)` | the decision dict | `GateError` | The preregistered rule |
| `gate.kept(F, decision, ct_middle)`, `gate.to_u8(kept)` | arrays | | |
| `inklens.analyze(F, R, volume)` | `(decision, kept, kept_control)` | | |
| `inklens.run_space(volume, space, reader, windows, token)` | run dict | `Refused` | Your token, your quota |
| `inklens.write_vc3d(segdir, run_id, box, pool, kept_u8, decision, receipt, pins)` | `(files, voxels)` | `VC3DError` | |
| `vc3dout.merge_records`, `vc3dout.points_doc`, `vc3dout.merge_points`, `vc3dout.check_points_doc` | | `VC3DError` | VC3D's file rules |

## Inputs

- A tifxyz segment folder (VC3D's format): `meta.json` with `format: tifxyz` and `scale [sx, sy]`, and float32
  `x.tif`, `y.tif`, `z.tif` (voxel positions; -1 marks a hole). The render canvas is the grid size over the scale.
- The region: `--box X Y W H` in render pixels at scale 1, or the VC3D cursor. After pooling it must be 128 to 2048 px
  a side; Space mode refuses a region whose call would need more than 40 GPU seconds.
- The voxels: an OME-Zarr scan (rendered with `vc_render_tifxyz --scale 1 --num-slices 21 x pool`, uncompressed), or a
  surface volume of the whole segment, uint8 or uint16, layers first, at least 21 layers centered on the surface (17
  for one window).
- To the Space: an `.npz` with one array `volume` (uint8, layers first, about 9.6 um), at most 64 MB.

## Outputs

`run --json` prints `run`, `segment`, `gate` (below), `letters` (`status`, `letters_kept`, `null_letters_kept`,
`control_map_letters`), `files`, `pins`, `where` and `note`.

| Field | Type | Meaning |
| --- | --- | --- |
| `gate.status` | string | `ink`, `weak`, `none`, `too_small` or `unreadable` |
| `gate.excess` | number | Share of papyrus above T, divided by 0.01 |
| `gate.threshold` | number | T, the 99th percentile of the reversed map on papyrus (0 to 1) |
| `gate.forward_above`, `gate.control_above` | number | Shares of papyrus above T in each map (the control's is 0.01 by construction) |
| `gate.papyrus_px` | integer | Papyrus pixels in the region |
| `files.png` | path | The run's overlay, the whole canvas at the map's resolution |
| `files.mosaic` | path | The running maximum of every run on this segment |
| `files.records` | path | `ink-detections.json` |
| `files.pins` | path | The point collection (only when letters passed) |
| `files.receipt` | path | Everything above plus readers and their SHA-256, villa commit, windows, box, pooling, device and seconds |

| Exit code | Meaning |
| --- | --- |
| `0` | Status `ink` or `weak`: the overlay and any pins were written |
| `2` | Refused: nothing was written; the reason is on stderr |
| `3` | Status `none` or `too_small`: an empty overlay and the receipt were written |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `; the samples are` | The sample id is not in `samples.json` | Run `inklens.py samples` |
| `samples must come from` | `samples.json` names another bucket | Restore the file; samples come only from the open-data bucket |
| `must be a plain path inside the segment` | A sample path is absolute, a URL or climbs out | Restore `samples.json` |
| `is listed twice` | Two samples share an id | Restore `samples.json` |
| `is outside the` | A crop, box or read lies outside the surface or volume | Give a box inside the segment |
| `px region at rows` | `--at` puts the square outside the surface | Pick a corner further in |
| `label scoring needs this repository's kit/ (and zarr)` | `--score` outside this repository | Run from the repository with zarr installed |
| `MB. Use a smaller region or --local` | The packed region is over 64 MB | Use a smaller region or local mode |
| `Space mode runs on your own ZeroGPU quota, so it needs your Hugging Face token: run 'hf auth login' or set HF_TOKEN (a read token is enough). Or use --local to run on this machine` | No token was found | Log in, set `HF_TOKEN`, or use `--local` |
| `Space mode needs gradio_client (pip install gradio_client), or use --local` | gradio_client is missing | Install it or use `--local` |
| `the Space refused the region:` | The Space returned an error (size, quota, loading) | Read the reason; retry later or use `--local` |
| `here; nothing is written` | The Space's status differs from the one recomputed from its maps | Nothing to trust; report it, rerun locally |
| `vc_render_tifxyz is not on PATH (it ships with VC3D builds); give --render-binary, or render the segment's surface volume yourself and pass --surface-volume` | No renderer found | Give `--render-binary` or `--surface-volume` |
| `vc_render_tifxyz failed (` | The renderer exited with an error | Read its stderr tail in the message |
| `give --segment SEGDIR (a tifxyz folder), or --from-vc3d with a running VC3D` | No segment | Give one |
| `give --um-per-px (the render's pixel size in micrometers)` | The pixel size is unknown | Give `--um-per-px` |
| `is outside the segment canvas` | The box does not fit the canvas | Fix the box (render pixels at scale 1) |
| `give --box X Y W H (render pixels of the segment at scale 1) or --from-vc3d` | No region | Give one |
| `give --surface-volume PATH or --volume OME_ZARR` | No voxels | Give one |
| `has no tifxyz mesh listed; pick one that does for --vc3d-out` | The sample has no mesh in `samples.json` | Use `0841-w00` |
| `of its tifxyz mesh is missing from the bucket` | The bucket no longer has the mesh file | Report it; use another sample |
| `voxels from the active segment; put it on the segment` | The VC3D cursor is off the active segment | Put the cursor on the segment |
| `: choose one of` | Unknown reader | `d9v2`, `ink_9um` or `both` |
| `: use 1 or 3` | Unknown window count | 1 or 3 |
| `s one call may ask for; use a smaller region, one depth window, or local mode` | Over 40 GPU seconds | Smaller region, `--windows 1`, or `--local` |
| `a surface volume has 3 axes (layers, rows, columns), this one has` | Wrong array shape | Give layers x rows x columns |
| `: the engine takes uint8 (volio.to_uint8 converts uint16)` | Wrong type reached the engine | Convert with `volio.to_uint8` |
| `layers, layers first` | Too few or too many layers | 21 to 65 layers (17 for one window) |
| `px a side at 9.6 um` | Region side outside 128 to 2048 px | Resize the region |
| `the region is all zero (off the segment, or a hole in it)` | No voxels in the region | Pick a region on the segment |
| `; refusing it` | A checkpoint's SHA-256 does not match | Delete the cached file; check the source |
| `does not exist` | `INKLENS_<READER>` names a missing file | Fix the variable |
| `held no vesuvius/src files` | The villa tarball was empty | Retry, or set `VILLA_SRC` |
| `holds no villa vesuvius package` | `VILLA_SRC` or the download is not villa | Point `VILLA_SRC` at `vesuvius/src` |
| `; Ink Lens is built for` | The checkpoint's patch or depth is not 128 and 17 | Use a 9 um flat checkpoint |
| `, which Ink Lens does not run` | Unknown preprocessing in the checkpoint | Use a 9 um flat checkpoint |
| `is not loaded here` | The reader was not loaded in this engine | Load it, or pick a loaded reader |
| `the CT layer is 2-D, not` | Wrong CT input to the gate | Pass the middle layer |
| `must be 2-D and the same shape` | Maps of different shapes | Pass both maps of the same region |
| `differ in shape` | CT and maps of different regions | Pass matching arrays |
| `a PNG here is a non-empty 2-D uint8 array, not` | Wrong array for the PNG writer | Pass uint8 |
| `a PNG with no IHDR` | A broken mosaic file | Delete `inklens/mosaic.png` |
| `only 8-bit grayscale non-interlaced PNGs are read here (depth` | The mosaic was replaced by another PNG | Delete it; Ink Lens writes a new one |
| `PNG filter type` | A broken PNG | Delete it |
| `is not a TIFF` | A band is not a TIFF | Check the segment |
| `is not a TIFF (magic` | A band is not a TIFF | Check the segment |
| `: no image width or height tag` | A band lacks size tags | Check the segment |
| `has no meta.json; give a tifxyz segment folder` | Not a segment folder | Give the tifxyz folder |
| `, VC3D needs tifxyz` | meta.json is not tifxyz | Give a tifxyz segment |
| `is not two positive numbers` | meta.json's scale is broken | Fix the segment |
| `; the segment is too small for this map resolution` | The canvas would lose the grid's aspect | Use a larger segment or a finer render |
| `lies outside the segment's canvas` | The region is off the canvas | Fix the box |
| `: x, y and z bands differ in size` | Broken segment | Fix the segment |
| `the segment has no valid vertex` | Every vertex is a hole | Fix the segment |
| `is not a JSON array; refusing to overwrite it` | `ink-detections.json` is not a list; VC3D would ignore it | Fix or move the file, then rerun |
| `); refusing to overwrite it` | `ink-detections.json` is not readable JSON | Fix or move the file |
| `mapping pins onto the segment needs tifffile (pip install tifffile)` | No tifffile | Install it, or `--no-pins` |
| `: give a uint8 or uint16 surface volume` | Other voxel type | Convert the volume |
| `um must be positive` | Bad `--um-per-px` | Give the pixel size |
| `volume is smaller than one` | The region is smaller than one pooling block | Give a larger region |
| `axes; a surface volume has 3 (layers, rows, columns)` | A zarr or file with other axes | Give a 3-axis surface volume |
| `: a chunk holds` | A zarr chunk has the wrong size | Check the zarr |
| `is not a zarr array (no .zarray or zarr.json)` | Not a zarr | Check the path |
| `is a zarr group, not an array` | A group without multiscales | Give the array path |
| `need the zarr package; read it with zarr and pass a .npy instead` | Compressed zarr v3 | Convert to `.npy` |
| `); install numcodecs` | Compressed zarr v2 | Install numcodecs |
| `is outside the volume's shape` | The box is outside the zarr | Fix the box |
| `: give a .zarr, .npy, .npz or multi-page .tif surface volume` | Unknown file type | Convert it |
| `: an .npz needs an array named 'volume'; it has` | Wrong array name | Save it as `volume` |
| `reading a .tif needs tifffile (pip install tifffile)` | No tifffile | Install it |
| `VC3D has no active segment; open one first` | `--from-vc3d` with no segment open | Open a segment in VC3D |
| `VC3D's active segment` | The active segment has no folder on disk | Save it, or give `--segment` |
| `canvas.get_cursor_volume_point returned no volumePoint:` | The cursor is not on a viewer | Hover over the segment view |
| `cannot connect to the VC3D bridge at` | The bridge socket is gone | Start VC3D with `--agent-bridge` |
| `the bridge closed the connection during` | VC3D closed the socket | Restart the bridge |
| `the readers are still loading (about a minute after the Space wakes up); try again shortly` | The Space is starting | Wait a minute |
| `the readers failed to load:` | The Space could not load a reader | Read the reason in the Space logs |
| `px with one window; run larger regions in local mode (python3 inklens.py run --local ...), or try again later` | ZeroGPU refused and the region is too big for the CPU fallback | Try later or use local mode |
| `, and the Space's CPU is busy with another fallback run; try again in a minute` | One CPU fallback at a time | Wait a minute |
| `upload an .npz first` | No file | Upload one |
| `MB; the limit is` | Upload over 64 MB | Use a smaller region |
| `upload an .npz with one array named 'volume' (uint8, layers x rows x columns)` | Not an `.npz` | Save the region as `.npz` |
| `not a readable .npz:` | A broken file | Save it again |
| `; it needs volume` | No `volume` array | Save it as `volume` |
| `the volume is larger than a region may be (2048 x 2048 px, 65 layers)` | Too large uncompressed | Use a smaller region |
| `missing Space files:` | A staged file is missing | Restore it |
| `is not empty` | `stage` into a non-empty folder | Give an empty folder |
| `give the Space as OWNER/NAME` | Bad Space name | `OWNER/NAME` |
| `not logged in to Hugging Face (` | No login on this computer | `hf auth login` |

## How it works

1. **Region.** `vc_render_tifxyz --scale 1 --num-slices 21 x pool --crop-x X --crop-y Y --crop-width W
   --crop-height H --zarr-compressor none` renders only the region (or it is read from a surface volume), and
   `volio.pool` takes a 2.4 um render to 9.6 um by a 4 x 4 x 4 mean (`pool_factor`: 1 at 7 um and above).
2. **Engine** (`engine.py`). villa's `configure_model` builds the reader at villa `8aa507c12` from a checkpoint checked
   by SHA-256 and opened with `weights_only=True`. The middle 21 layers (`STACK`) hold three 17-layer windows
   (`WINDOW_OFFSETS` 0, 2, 4; 2 is villa's own center window). Each window runs as stored and reversed: 128 px patches
   at stride 64 (`PATCH`, `STRIDE`), villa's robust normalisation batched on the device (`robust_torch`, batch 64,
   fp16 autocast on CUDA as the checkpoint asks), villa's floored Hann blend. All-zero patches are skipped as villa
   does. F and R are the means of the three windows (and of the readers with `both`).
3. **Gate** (`gate.py`, `ink-lens-gate-v1`). Papyrus: middle CT layer above its 5th percentile and above 0. T: 99th
   percentile of R on papyrus. Excess: share of papyrus with F > T over 0.01. Status from `INK_EXCESS` 3,
   `WEAK_EXCESS` 1.5 and `MIN_PAPYRUS` 100,000.
4. **Letters.** `kit.letterread.read` on the kept map with `letters-v2-ccby`, letter height `--letter-mm` over the
   map's pixel size, and the control's kept map (R where R > T) as control. Pins only for a `strong` or `weak` read.
5. **VC3D files** (`vc3dout.py`). The kept map, as 0 or 1 to 255, is placed on a canvas the size of the segment grid
   over its scale (divided by the pooling, and by a whole number more when over 16,384 px), so its aspect equals the
   grid's within 2 % (the rule `kit.villafmt` checks in Scrolls-private). Records carry the segment's key in
   `segment_id` and `segment_long_id`. Pins map render pixel to grid by the scale and to voxels by bilinear
   interpolation of the x, y and z bands; a pin on or next to a hole is dropped.
6. **Space** (`app.py`). One `spaces.GPU` call per region with duration `ceil(4 + 0.012 x patches)` seconds, at most
   40; a region of at most 512 px with one window falls back to the CPU when ZeroGPU refuses.

Sources: villa main `8aa507c12` (`vesuvius/src/vesuvius/ink_detection/inference/infer.py`,
`image_proc/intensity/normalization.py`, VC3D's `OpenDataSegmentCache.cpp:651-694`,
`InkDetectionOverlayController.cpp:395-580`, `PointCollections.cpp:36-119, 571-662`, `vc_render_tifxyz.cpp:1254-1337`,
`agent_bridge/SPEC.md`). The window average follows the `ink_9um` model card ("Averaging predictions over a few nearby
z windows also works as a simple ensemble", read 2026-10-20).

## Cost and time

- CPU (4 cores of a Claude cloud container, 2026-10-20): 0.14 s per patch with d9v2 in fp32 at batch 8 alone on the CPU; the preregistered check (four regions, three of them run) in 434 s wall, 112 to 148 s per 640 px crop
  (0.23 to 0.30 s per patch at batch 64 while other work shared the CPU).
- ZeroGPU: not measured. Estimate 3 to 6 ms per patch with batching and fp16, so 6 to 10 s for a 1024 px region with
  three windows (requested 21 s). Chase's 300 s covers one calibration call and then about 25 such regions.
- Local CUDA and Apple MPS: not measured.

## For agents

- **Command:** `python3 spaces/ink-lens/inklens.py run --segment SEGDIR --volume SCAN.zarr --box X Y W H --local --json`
  (or `--space OWNER/NAME` with `HF_TOKEN` set); `--dry-run` first for the plan and the GPU estimate.
- **Parse:** `gate.status`, `gate.excess`, `files.*`, `pins`, `letters.status` from the JSON on stdout.
- **Rerun:** Safe. Each run writes new files under a new run id; the mosaic grows by maximum; `ink-detections.json`
  keeps every record not written by this run.
- **Success:** Exit 0 with `gate.status` `ink` or `weak`; exit 3 is a valid answer (`none`), not an error.
- **Not a pass:** A map with no status, a Space result whose status the client did not recompute, letters with
  `letters.status` other than `strong` or `weak`, and any number from the samples presented as a blind test.
- **Go-ahead:** Deploying the Space, and calling it with Chase's token.
- **Never:** Call a kept map or a pin a reading; publish a map, status or pin of a target or prize-eligible scroll in
  this repository; overwrite `ink-detections.json` by hand while VC3D has the segment open.

## Tests

`python3 -m unittest tests.test_inklens -v` (numpy only; with torch the engine checks run too, and with
`VILLA_SRC=PATH/vesuvius/src` the normalisation is compared with villa's own function). They cover the gate and its
failing cases, the prereg's constants, patch counts and the duration formula, window and layer choice, villa's
normalisation and Hann map, the numpy reference against the torch engine with a stand-in model, the PNG, canvas
aspect, record merge, point collections and grid mapping, the zarr reader, the client's full local run on a synthetic
segment, its refusals (no token, too big, outside the canvas, bad records file, Space status mismatch), the Space's
upload checks, card, files and the plugin manifest. Not covered: a real VC3D opening the files, `vc_render_tifxyz`,
the live Space, and the agent bridge against a running VC3D.

## History

- 2026-10-20: design, preregistration and the gate (`3c2445e`); the engine, client, Space, tests and this page on
  branch `claude/ink-lens`.

## Related

- [Scroll Lens](scroll-lens.md): the ZeroGPU Space pattern this follows.
- [letterread](letterread.md): the Scroll Text Reader that makes the pins.
- [auc](auc.md): pixel AUC with its reversed control.
- [AutoPipeline](autopipeline.md): whole-segment ink maps through villa.
- `docs/results.json` `ink_lens_checks`: the preregistered check's numbers.
- [`spaces/ink-lens/DESIGN.md`](../../spaces/ink-lens/DESIGN.md): why this design, and what was checked.
