# inkpreview: local model server that maps the view on screen with an ink model

`scripts/ane/inkpreview.py` is a local HTTP server that turns the layer stack under the window a viewer shows into an ink model's map of that window (model output, not a reading), on Core ML, TorchScript or inkrs, with a reversed-layer control view.

| Field | Value |
| --- | --- |
| Id | `inkpreview` |
| Status | Current |
| Kind | script folder |
| Area | Viewers and apps |
| Run | `python3 scripts/ane/inkpreview.py serve`, `python3 scripts/ane/inkpreview.py snapshot`, `python3 scripts/ane/inkpreview.py check`, `python3 scripts/ane/inkpreview_inkrs_check.py`, `python scripts/ane/export_ckpt.py`, `python scripts/ane/convert.py`, `python scripts/ane/coreml_server.py` |
| Code | `scripts/ane/` |
| Tests | `tests/test_inkpreview.py` |
| Needs | Python 3 with numpy (run here on Python 3.13.18 with numpy 2.5.3). Path mode also needs tifffile (layer TIFFs) or zarr (a zarr). One backend: `coreml` needs macOS 15 or later and a Python with coremltools (`COREML_PY`); `torchscript` needs torch; `inkrs` needs [inkrs](https://github.com/praveenperera/inkrs) (`pip install inkrs`, 0.2.0 on PyPI on 2026-11-13) and a Metal or CUDA GPU; `fake` needs nothing. `export_ckpt.py` needs torch and villa's `vesuvius` package; `convert.py` needs torch and coremltools. Model weights and scroll data are not in this repository |
| Runs on | Any machine; the server listens on `127.0.0.1` only. With the `fake` backend (no model) on a synthetic stack, a cold 1920 by 1080 view took 3.8 s and a 96 px pan 0.3 to 0.5 s (measured 2026-11-13, cloud container, 4 shared vCPU). With a real model: Not measured here |
| Network | None. It listens on `127.0.0.1` and contacts no host |
| Writes | `serve` and `check`: nothing. `snapshot`: the file `--out`. `inkpreview_inkrs_check.py`: the file `--json`, when given. `export_ckpt.py`: `OUT.pt`. `convert.py`: `OUT.mlpackage` |
| Go-ahead | Not needed to run it on your own machine. Posting a preview picture or what it shows needs Chase's yes (the go-ahead rule, hard rule 8), and a preview of a prize-eligible scroll is never published or described (the possible-findings rule, hard rule 1) |
| Released | Public `main` since November 2026, with the change that added this page |
| License | This repository's Apache 2.0 ([LICENSE](../../LICENSE)). inkrs, used by the `inkrs` backend and not included here, is by Praveen Perera under MIT or Apache 2.0 |
| Checked | 2026-11-13 against commit `aba138c` |

## What it does

Someone who wants to see an ink model's output while looking at a segment usually runs a whole-segment ink map first and loads it as an overlay. inkpreview answers for the window on screen only. A viewer asks the server for a rectangle of the segment's flat image; the server cuts that rectangle into patches on the grid a whole-segment map uses, runs the patches through the model and blends them. Patch results stay in a memory-capped cache keyed by patch position, so a pan computes only the new patches.

The server and its client speak a small HTTP protocol, called **ink preview api 1** here: `GET /health` and `POST /preview`. The rectangle is given in **canvas** pixels: the canvas is the whole flat image of the surface at one volume level, the image villa's `vc_render_tifxyz` writes for the surface with no crop, rotation or flip. The server gets its voxels in one of two ways. In **stack mode** the viewer samples the layers under the view itself and uploads them: the server answers HTTP 409 with a `need` rectangle, the bounding box of the patches it has not cached, the viewer uploads the layers of that rectangle, and the server answers with the view. A pan along one axis therefore uploads one strip. Because the viewer samples from the surface it holds, no rendered surface volume is needed. In **path mode** the server reads a surface volume from disk (a zarr, or a folder of layer TIFFs). The protocol is written out under Commands and options so that any client can speak it. No released viewer speaks it yet; the Python client there is a tested example.

The arithmetic follows the flat ink inference of [villa](https://github.com/ScrollPrize/villa) (`vesuvius.ink_detection.inference.infer`) and lives in `scripts/ane/flat_contract.py`: a center crop of the layers to the model depth, patches of the model's size (128 px for `ink_9um`) at stride 64 (the default overlap 0.5) from the canvas origin with a last row and column flush to the edge, per-patch robust normalization (clip to the 1st and 99th percentiles, subtract the median, divide by 1.4826 times the median absolute deviation), sigmoid, a Hann-weighted mean with weights floored at 0.001, all-zero patches skipped. On the same voxels a preview pixel is therefore the pixel the whole map would hold, edges included, up to the arithmetic of the backend.

Four backends run the model. Three are batch backends, which run the patches this server cuts, normalizes and blends: `coreml` (a Core ML package on the Apple Neural Engine, through `coreml_server.py`), `torchscript` (a traced model on the CPU, the Apple GPU or CUDA) and `fake` (a depth-weighted mean for tests, never a model). `export_ckpt.py` traces a villa ink checkpoint; `convert.py` turns the trace into a Core ML package. The fourth, `inkrs`, is a **window backend**: [inkrs](https://github.com/praveenperera/inkrs) by Praveen Perera (MIT or Apache 2.0) runs villa's flat ink readers with the model resident on the GPU, does its own normalization, tiling and Hann blending, and returns villa's uint8 map, `trunc(255 p)`, for a whole window. The server hands it windows on the canvas grid with a margin and keeps only the pixels where the window's map equals the whole map's (the window rule, under How it works).

A preview is model output, not a reading: never write that ink or letters were found or read in it. The server does not score anything, does not write a whole map and does not make a picture trustworthy by being fast. Variant `r` runs the same view with the layers reversed, the control view.

### Which backend

| Backend | Runs on | Models | Arithmetic |
| --- | --- | --- | --- |
| `inkrs` | Metal (Apple Silicon) or CUDA | villa's flat ink readers that inkrs runs: `ink_9um` and its fine-tunes (128 px tiles), and readers with 384 px tiles (stride 192) | inkrs's own; the reply is its uint8 map. Check it on your machine with `inkpreview_inkrs_check.py` |
| `coreml` | Apple Neural Engine (macOS) | A traced model converted by `convert.py` | float16. Not bit-equal to float32 on a CPU or GPU, so compare a map from the package with one from the checkpoint before relying on it |
| `torchscript` | CPU, Apple GPU (`mps`) or CUDA | Any trace with input (B, 1, depth, patch, patch), such as `export_ckpt.py` writes | float32 torch |
| `fake` | Anywhere | None: a test pattern | Never a map |

## When to use it

- Looking at where an ink model responds on the part of a public segment you have on screen, without waiting for a whole map.
- Comparing the forward view with its reversed-layer control on the spot (`variant=r`).
- Building or testing a viewer client for the stack-mode protocol: the `fake` backend needs no model and no GPU.
- Checking on your own machine that inkrs windows tile to the whole inkrs map (`inkpreview_inkrs_check.py`).

Do not use it:

- For results or scores. Use a whole map and [`kit auc`](auc.md) with its reverse-depth control.
- On a segment you plan a preregistered readout on. Readout rules are fixed before any map of the target exists (the preregistration rule, hard rule 3); fix them first with [`python -m kit run init`](run-ledger.md). Start the server with `--allow` naming the scrolls you mean to look at.
- To judge a model on a segment it trained on. For `ink_9um`, PHerc0139 w035 is a training segment: a preview there shows the pipeline works, nothing more.
- To claim equality with a whole map whose input was prepared differently. Parity holds when the voxels are the same; when the whole map's input was pooled or resampled from another scan, a stack sampled by a viewer gives an approximation of that map.
- With `--backend fake` for anything but tests: its output is a test pattern.
- To run a model on one region and keep files for VC3D. [Ink Lens](ink-lens.md) does that, with a control-set threshold.

## Quick start

Stack mode with the `fake` backend and a synthetic stack, which runs anywhere with numpy and curl. `stack.u8` holds 17 uint8 layers of a 300 by 200 canvas (1,020,000 bytes), written by the first command:

```bash
python3 -c "import numpy as np; np.random.default_rng(0).integers(1, 255, (17, 200, 300), dtype=np.uint8).tofile('stack.u8')"
python3 scripts/ane/inkpreview.py serve --backend fake --port 18765 &
curl -s 127.0.0.1:18765/health
Q='key=demo&cw=300&ch=200&x=100&y=50&w=120&h=100'
curl -s -X POST "127.0.0.1:18765/preview?$Q"
curl -s -X POST --data-binary @stack.u8 -D - -o view.u8 \
  "127.0.0.1:18765/preview?$Q&sx=0&sy=0&sw=300&sh=200&dtype=uint8"
```

What it printed (run on 2026-11-13 in a cloud container; the `Server` and `Date` headers are left out):

```text
inkpreview: no allow list and no extra rules: every scroll may preview (--allow SCROLLS restricts it)
inkpreview serving http://127.0.0.1:18765 backend=fake model=fake input=(16, 1, 17, 128, 128)
{"service": "ink-preview", "api": 1, "backend": "fake", "model": "fake", "patch": 128, "stride": 64, "depth": 17, "voxel_um": null, "max_view_px": 16777216, "cache": {"tiles": 0, "mb": 0.0, "cap_mb": 256, "hits": 0, "misses": 0}, "input_shape": [16, 1, 17, 128, 128], "output_shape": [16, 1, 128, 128], "allow": ["any"], "tiling": "patch", "quantized": false, "dtypes": ["uint8", "uint16"]}
{"need": {"x": 0, "y": 0, "w": 300, "h": 200}, "depth": 17, "missing": 12}
HTTP/1.1 200 OK
Content-Type: application/octet-stream
X-Shape: 100,120
X-Backend: fake
X-Tiles: 12,0
Content-Length: 12000
```

The first POST has no body, so the server answers 409 and names the rectangle to upload; the second uploads it and gets the 120 by 100 view, one byte per pixel, in `view.u8`. It worked when the second reply is 200 with `X-Shape: 100,120`. Asking again without a body then answers 200 with `X-Tiles: 0,12` (all cached). A `fake` view is a test pattern, never a map. Stop the server with `kill %1`.

With a model, one of:

```bash
python scripts/ane/export_ckpt.py CKPT TRACED.pt 16
python3 scripts/ane/inkpreview.py serve --backend torchscript --model TRACED.pt --model-name ink_9um
python scripts/ane/convert.py TRACED.pt PKG.mlpackage 16,1,17,128,128
COREML_PY=PYTHON python3 scripts/ane/inkpreview.py serve --package PKG.mlpackage --model-name ink_9um
python3 scripts/ane/inkpreview.py serve --backend inkrs --model EXPORT.safetensors --model-name ink_9um
```

- `CKPT`: a flat ink checkpoint in villa's format that you trust, such as `ink_9um`'s `step-075000.pth`. `export_ckpt.py` runs in a Python that has torch and villa's `vesuvius` package.
- `TRACED.pt`: the TorchScript trace `export_ckpt.py` writes, here at batch 16.
- `PKG.mlpackage`: the Core ML package `convert.py` writes from the trace (macOS).
- `PYTHON`: a Python that has coremltools, when the server's own Python does not.
- `EXPORT.safetensors`: an inkrs export of the checkpoint with its `.json` sidecar beside it (`python -m inkrs.export_weights`, see inkrs's documentation).

These were not run for this page. Each worked when `/health` names the backend and the model, and a POST returns 200.

## Checks and controls

- **The control view.** Request the same view with `variant=r` (layers reversed). Where the forward view is high and the reversed view is as high, the response does not depend on the order of the layers, so it says nothing about ink; a model that responds to ink should sit clearly lower in the reversed view. The reversed view does not show that a response is ink.
- **Tiling parity, in the tests that ship with the code.** With the `fake` model, path mode and stack mode equal a whole-canvas map written independently in the test from villa's rule, to 1e-6: on canvases whose size minus 128 is and is not a multiple of 64, on canvases smaller than one patch, and on views touching the right and bottom edges. Stack mode equals path mode bit for bit, and both equal, bit for bit, a reference that sums the patches in row-major order. The control that must fail does: the same pixels tiled on a grid moved by half a stride differ by more than 1e-4 on more than half the pixels (`test_displaced_grid_does_not_equal_the_full_map`). Run them with the command under Tests.
- **The window rule, in the tests.** `exact_span` and `window_span` are compared with an enumeration of the patch sets on every small case; with a stand-in inkrs module written in the test, every preview equals the stand-in's whole-canvas map exactly, and the controls that must differ do (a window without the margin, a window shifted half a stride).
- **Your own check with real inkrs.** The stand-in is not inkrs. `inkpreview_inkrs_check.py` loads your inkrs export, maps a whole canvas of a surface volume you give it, forward and reversed, and asks the server in stack mode for 16 views off the grid (inside, after pans, on every edge and corner, two reversed). It passes when every view equals the whole map's pixels (`views[].differ` all 0) and both controls differ (`controls[].differ` above 0): the view cut from a window without the margin, and from the window shifted half a stride. On public data, a surface volume of a public segment such as PHerc0139 w035 will do; that is a training segment of `ink_9um`, which is fine here because the check compares two outputs of the same engine and says nothing about the model. No result of this check is quoted on this page: run it on your machine.
- **Backend arithmetic.** The tests cover the tiling, never a model's numbers. A Core ML package runs in float16 on the Neural Engine and is not bit-equal to villa's float32 output, so never call a Core ML preview identical to a villa map without measuring it. The `torchscript` backend with a real checkpoint has not been compared with villa here.

Scope: the claim is exact tiling on the same voxels, checked by the shipped tests on synthetic stacks. No claim is made about any model's quality, about speed with a real model, or about any scroll.

Claim label: Model output (a preview is an ink model's output for one window). The tiling is checked with a fake model and a stand-in inkrs module in the tests; no real model's numbers are claimed here.

## Commands and options

### `python3 scripts/ane/inkpreview.py serve`

```text
usage: inkpreview.py serve [-h] [--allow SCROLLS] [--backend {coreml,torchscript,inkrs,fake}]
                           [--package PACKAGE] [--units UNITS] [--model MODEL]
                           [--device {auto,cpu,mps,cuda}] [--batch-size N] [--input-shape B,1,D,P,P]
                           [--model-name MODEL_NAME] [--voxel-um VOXEL_UM] [--cache-mb CACHE_MB]
                           [--overlap OVERLAP] [--activation {sigmoid,none}] [--max-view-px MAX_VIEW_PX]
                           [--port PORT]
```

Starts the server on `127.0.0.1` and serves until interrupted.

| Option | Default | Meaning |
| --- | --- | --- |
| `--allow` | `any` | Scroll ids that may preview, comma-separated; `any` is no restriction. With a list, a request must name a scroll on it: in the segment path (path mode) or in the `scroll` parameter (stack mode) |
| `--backend` | `coreml` | `coreml`, `torchscript`, `inkrs` (a window backend, Which backend above), or `fake` (a depth-weighted mean for tests, never a map) |
| `--package` | none | `coreml`: the Core ML package (required) |
| `--units` | `CPU_AND_NE` | `coreml`: compute units (`CPU_AND_NE`, `ALL`, `CPU_AND_GPU`, `CPU_ONLY`) |
| `--model` | none | `torchscript`: the traced model, `export_ckpt.py`'s output (required). `inkrs`: the safetensors export from `python -m inkrs.export_weights` with its JSON sidecar, or villa's `.pth` when inkrs can find or make its export (required). The sidecar's `crop_size` gives the depth and the patch (`[17, 128, 128]` for `ink_9um`); the server refuses to start without it |
| `--device` | `auto` | `torchscript`: `auto` picks CUDA, then the Apple GPU (`mps`), then `cpu`. `inkrs`: `auto` is inkrs's device 0, or `mps` or `cuda`; `cpu` is refused |
| `--batch-size` | none | `inkrs`: tiles per forward. Left out, it is 16 for 128 px tiles and 8 for 384 px tiles, read from the sidecar's `crop_size` beside a `.safetensors` export, and 8 for a `.pth` (no sidecar to read) |
| `--input-shape` | `16,1,17,128,128` | `torchscript` and `fake`: the model's input shape B,1,D,P,P (batch, 1, depth, patch, patch); `coreml` and `inkrs` read it from the model. A short last batch is padded with zero patches |
| `--model-name` | none | The label `/health` reports as `model`. Left out, it is the reader name an inkrs export records, else the model file's name without its extension (`fake` for the fake backend). A package called `ink9um_b16.mlpackage` gives `ink9um_b16`, so pass `--model-name ink_9um` to report the model's usual name and its voxel size |
| `--voxel-um` | none | The voxel size the model was trained at, in micrometers, reported by `/health` as `voxel_um`. Left out, it is `9.36` when the model label is `ink_9um`, else `null`. A viewer can use it to pick the volume level |
| `--cache-mb` | `256` | Memory cap of the patch cache; least recently used patches go first |
| `--overlap` | `0.5` | Patch overlap, at least 0 and under 1; 0.5 gives stride 64 for 128 px patches (192 for 384 px), villa's default grid. Another value matches only maps made at that overlap |
| `--activation` | `sigmoid` | `none` for models that already output probabilities. Not used by `inkrs`, which applies the sigmoid itself |
| `--max-view-px` | `16777216` | Largest view, in pixels (`w` times `h`) |
| `--port` | `8765` | Port on 127.0.0.1; `0` picks a free one, printed on the first line |

### `python3 scripts/ane/inkpreview.py snapshot`

```text
usage: inkpreview.py snapshot [-h] [--allow SCROLLS] [--backend {coreml,torchscript,inkrs,fake}]
                              [--package PACKAGE] [--units UNITS] [--model MODEL]
                              [--device {auto,cpu,mps,cuda}] [--batch-size N] [--input-shape B,1,D,P,P]
                              [--model-name MODEL_NAME] [--voxel-um VOXEL_UM] [--cache-mb CACHE_MB]
                              [--overlap OVERLAP] [--activation {sigmoid,none}] [--max-view-px MAX_VIEW_PX]
                              --x X --y Y --w W --h H --segment SEGMENT [--window WINDOW] [--variant {f,r}]
                              [--scale SCALE] --out OUT
```

One path-mode view written to a file, with no server.

| Option | Default | Meaning |
| --- | --- | --- |
| `--allow` | `any` | As for `serve` |
| `--backend` | `coreml` | As for `serve` |
| `--package` | none | As for `serve` |
| `--units` | `CPU_AND_NE` | As for `serve` |
| `--model` | none | As for `serve` |
| `--device` | `auto` | As for `serve` |
| `--batch-size` | none | As for `serve` |
| `--input-shape` | `16,1,17,128,128` | As for `serve` |
| `--model-name` | none | As for `serve` |
| `--voxel-um` | none | As for `serve` |
| `--cache-mb` | `256` | As for `serve` |
| `--overlap` | `0.5` | As for `serve` |
| `--activation` | `sigmoid` | As for `serve` |
| `--max-view-px` | `16777216` | As for `serve` |
| `--x` | required | View: first column, in pixels of the surface volume |
| `--y` | required | View: first row |
| `--w` | required | View: width |
| `--h` | required | View: height |
| `--segment` | required | Segment folder (with `layers/`) or surface-volume zarr |
| `--window` | none | `FIRST,END` layers the center crop comes from; left out, all layers |
| `--variant` | `f` | `r` for the control with the layers reversed |
| `--scale` | `1` | Mean-pool the result by N |
| `--out` | required | A name ending in `.png` (8-bit, `floor(255 p)`), or any other name for a float32 TIFF (needs tifffile); with `inkrs` the TIFF is its uint8 map as it is |

### `python3 scripts/ane/inkpreview.py check`

```text
usage: inkpreview.py check [-h] [--allow SCROLLS] --segment SEGMENT
```

Prints `ok: SCROLL may preview` (exit 0) or `refused: REASON` (exit 3) for a segment path. With no allow list (`--allow any`, the default) and no extra rules, every command of `inkpreview.py` first prints one line to stderr: `inkpreview: no allow list and no extra rules: every scroll may preview (--allow SCROLLS restricts it)`.

| Option | Default | Meaning |
| --- | --- | --- |
| `--allow` | `any` | As for `serve` |
| `--segment` | required | Path of a surface volume; it need not exist |

### `python3 scripts/ane/inkpreview_inkrs_check.py`

```text
usage: inkpreview_inkrs_check.py [-h] --model MODEL --segment SEGMENT [--window WINDOW]
                                 [--device {auto,mps,cuda}] [--batch-size N] [--allow SCROLLS] [--view W,H]
                                 [--json JSON]
```

Checks the `inkrs` backend against a whole inkrs map of the same layers (Checks and controls above). It loads one engine, reads the model's layers of the surface volume whole (the center crop of `--window`, as a whole map reads them), maps the whole canvas forward and reversed, then asks the server in process, in stack mode as a viewer does (ask, upload `need`, ask again). It prints one JSON report and exits 0 when it passes, 1 when not, 3 when `--allow` refuses the path.

| Option | Default | Meaning |
| --- | --- | --- |
| `--model` | required | As for `serve --backend inkrs` |
| `--segment` | required | Surface volume: zarr, folder of layer TIFFs, or `.npy` of shape (layers, rows, columns); uint8 |
| `--window` | none | `FIRST,END` layers the center crop comes from; left out, all layers |
| `--device` | `auto` | `auto`, `mps` or `cuda` |
| `--batch-size` | none | Tiles per forward; left out, as for `serve` |
| `--allow` | `any` | Scroll ids the segment path must name, comma-separated; `any` is no restriction |
| `--view` | `1200,800` | View size W,H in pixels |
| `--json` | none | Also write the report to this file |

```bash
python3 scripts/ane/inkpreview_inkrs_check.py --model EXPORT.safetensors --segment SURFACE --json check.json
```

`EXPORT.safetensors` is your inkrs export; `SURFACE` is a uint8 surface volume with at least as many layers as the model reads.

### HTTP, ink preview api 1

| Request | Reply |
| --- | --- |
| `GET /health` | 200, JSON (fields under Outputs) |
| `POST /preview?key=K&cw=CW&ch=CH&x=X&y=Y&w=W&h=H` with optional `variant`, `format`, `scroll`, and with a body `sx`, `sy`, `sw`, `sh`, `dtype` | Stack mode, below |
| `POST /preview` with a JSON body and no query | Path mode, below |

Stack mode parameters:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `key` | required | Opaque text of at most 200 characters. It names everything that decides the voxels under the canvas (the surface and its edit state, the volume, the level, the layer offsets); the client changes it whenever those change. Patches are cached under the key, the canvas size and the variant |
| `cw`, `ch` | required | Canvas size in pixels (the canvas is defined under What it does) |
| `x`, `y`, `w`, `h` | required | The view rectangle in canvas pixels, `x` the first column and `y` the first row; it must lie inside the canvas |
| `variant` | `f` | `r`: the control with the layer order reversed (the server reverses the uploaded layers) |
| `format` | `u8` | `u8`: one byte per pixel, `floor(255 p)`, villa's uint8 convention; `f32`: little-endian float32; `png`: 8-bit gray, the `u8` pixels. With `inkrs`, `u8` is inkrs's map as it is and `f32` is `u8 / 255` (`/health` says `"quantized": true`) |
| `scroll` | none | The scroll id, for a server with an allow list |
| `sx`, `sy`, `sw`, `sh` | none | The canvas rectangle the body covers; required with a body |
| `dtype` | `uint8` | `uint8` or `uint16` (little-endian); `inkrs` takes `uint8` only (`/health` `dtypes`) |
| body | none | depth times `sh` times `sw` voxels, layers first, C order. Layer `i` of the depth `D` sits at offset `i - D // 2` voxels along the surface normal (-8 to +8 for `ink_9um`, whose depth is 17), always in forward order. With `Content-Length`, or chunked |

Stack mode replies:

| Status | Body | When |
| --- | --- | --- |
| 200 | The view in `format`; headers `X-Shape: h,w`, `X-Backend`, `X-Tiles: computed,cached` (patches; cells of stride by stride pixels for `inkrs`) | Every patch that overlaps the view is cached or lies inside the uploaded rectangle (a patch on a canvas smaller than the patch is zero filled). Pixels no non-empty patch covers are 0 |
| 409 | `{"need": {"x", "y", "w", "h"}, "depth": D, "missing": N}` | Some patch is not ready. `need` is the bounding rectangle, clipped to the canvas, of every patch of the view that is not cached, those inside the current upload included, and `missing` is their number. Nothing is computed; the client samples `need` and posts again with the body. One rectangle per reply: after a diagonal pan it is the bounding box of an L-shaped band of new patches |
| 400 | `{"error": TEXT}` | A bad request |
| 403 | `{"refused": TEXT}` | The allow list or an extra rule refuses |
| 413 | `{"error": TEXT}` | `w` times `h` is over `max_view_px`, or the upload is over the server's size limit |
| 500 | `{"error": TEXT}` | Anything else; the server stays up |

Worked example (patch 128, stride 64, canvas 300 by 200, view x 100, y 50, w 120, h 100): column positions 0, 64, 128, 172 and row positions 0, 64, 72 all overlap the view, so with an empty cache the reply is 409 with `need` `{"x": 0, "y": 0, "w": 300, "h": 200}` and `missing` 12. The Quick start shows it.

Path mode takes JSON fields `segment` (path), `x`, `y`, `w`, `h` (pixels of the surface volume), and optional `window` (`[FIRST, END]`), `variant` (`f` or `r`), `scale`, `format` (`f32` by default, `u8` or `png`). It answers 200 with the same headers, or 400, 403, 413, 500 as above.

A client in Python, standard library and numpy (run against the `fake` server on 2026-11-13; `sample(x, y, w, h)` is the viewer's part: it returns the uint8 layers of that canvas rectangle, shape (depth, h, w), in forward order):

```python
import json, urllib.error, urllib.request
import numpy as np

BASE = "http://127.0.0.1:8765"


def preview(key, cw, ch, x, y, w, h, sample, variant="f"):
    url = "%s/preview?key=%s&cw=%d&ch=%d&x=%d&y=%d&w=%d&h=%d&variant=%s&format=u8" % (
        BASE, key, cw, ch, x, y, w, h, variant)
    body = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST")) as r:
                rows, cols = (int(v) for v in r.headers["X-Shape"].split(","))
                return np.frombuffer(r.read(), np.uint8).reshape(rows, cols)
        except urllib.error.HTTPError as e:
            if e.code != 409:
                raise RuntimeError("%d %s" % (e.code, e.read().decode()))
            n = json.load(e)["need"]
            body = np.ascontiguousarray(sample(n["x"], n["y"], n["w"], n["h"]), np.uint8).tobytes()
            url = url.split("&sx=")[0] + "&sx=%d&sy=%d&sw=%d&sh=%d&dtype=uint8" % (n["x"], n["y"], n["w"], n["h"])
    raise RuntimeError("the server kept asking for an upload")
```

### `python scripts/ane/export_ckpt.py`

```text
usage: export_ckpt.py [-h] CKPT OUT.pt BATCH [NORM]
```

Traces a villa ink checkpoint to TorchScript at a fixed batch size. Run it in a Python that has torch and villa's `vesuvius` package (villa's own environment); the model is built and loaded by villa's `configure_model`. It prints one JSON line with `ckpt`, `patch`, `depth`, `batch`, `norm`, `split`, `out_shape` and `swap_maxdiff`.

| Option | Default | Meaning |
| --- | --- | --- |
| `CKPT` | required | A flat ink checkpoint in villa's format, such as `ink_9um`'s `step-075000.pth`. It is loaded with pickle, which runs code from the file: trace only checkpoints you trust |
| `OUT.pt` | required | The TorchScript trace to write, at input shape (BATCH, 1, depth, patch, patch); it outputs logits |
| `BATCH` | required | Batch size of the trace, at least 1 |
| `NORM` | `in4d` | `in4d`: each InstanceNorm3d runs as the equivalent 4D instance norm (the Core ML conversion needs it); `swap_maxdiff` is the largest difference this makes on one random batch and should be near 0. `hier`: a two-level instance norm, a numeric variant to test |

### `python scripts/ane/convert.py`

```text
usage: convert.py [-h] TRACED.pt OUT.mlpackage SHAPE
```

Converts a trace to a float16 Core ML ML program for `CPU_AND_NE`, macOS 15 or later, with one input named `x`. It prints `saved OUT.mlpackage SHAPE`.

| Option | Default | Meaning |
| --- | --- | --- |
| `TRACED.pt` | required | The trace from `export_ckpt.py` |
| `OUT.mlpackage` | required | The package to write |
| `SHAPE` | required | The input shape the trace was made at, such as `16,1,17,128,128`. It is not read from the trace |

### `python scripts/ane/coreml_server.py`

```text
usage: coreml_server.py [-h] PACKAGE.mlpackage [UNITS]
```

The Core ML model server over a pipe that the `coreml` backend starts; you do not run it by hand. It writes `READY <input shape> <output shape>` and then answers each float32 batch (an 8-byte little-endian byte count, then the array) with the model's float32 output in the same framing.

| Option | Default | Meaning |
| --- | --- | --- |
| `PACKAGE.mlpackage` | required | A Core ML package with one fixed-shape input named `x` |
| `UNITS` | `CPU_AND_NE` | `CPU_AND_NE`, `ALL`, `CPU_AND_GPU` or `CPU_ONLY` |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `COREML_PY` | the Python running the server | `inkpreview.py`, `coreml` backend: the Python with coremltools that runs `coreml_server.py` |
| `HIER_BLOCK` | `1024` | `export_ckpt.py`, `NORM` `hier`: block size of the two-level norm |
| `SPLIT` | `0` | `export_ckpt.py`: `1` traces only the 2D U-Net (its input is then the output of the network's 3D stem). The preview server does not use split traces |

## Python API

The scripts load by path (`importlib`), not as a package. `flat_contract.py` needs only numpy.

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `flat_contract.normalize_robust(patch)` | float32, same shape | | Per-patch robust normalization; uint8 and uint16 take a histogram route with the same bits |
| `flat_contract.slice_order(window, depth, variant)` | layer indices | `ValueError` | Center crop to the model depth; `r` reverses |
| `flat_contract.hann2d(n)` | float32 (n, n) | | Hann blend window floored at 0.001 |
| `flat_contract.sliding_positions(length, patch, stride)` | list of positions | | villa's rule: 0, stride and so on, and a last one flush to the edge; `[0]` when the axis is not longer than the patch |
| `inkpreview.Previewer(backend, cache_mb, overlap, allow, activation, model_name, voxel_um, max_view_px)` | the server's state | `ValueError` (an empty allow list) | Thread-safe: one request at a time |
| `Previewer.preview(seg, x, y, w, h, window, variant, scale)` | float32 (h, w) | `Refused`, `TooLarge`, `ValueError` | Path mode; `preview_path` also returns the (computed, cached) patch counts |
| `Previewer.preview_stack(key, cw, ch, x, y, w, h, variant, stack, sx, sy, scroll, query)` | (float32 (h, w), or uint8 for `inkrs`, (computed, cached)) | `NeedStack` (with `need`, `depth`, `missing`), `Refused`, `TooLarge`, `ValueError` | Stack mode with the layers as an array |
| `Previewer.stack_request(q, body)`, `Previewer.path_request(q)` | (probabilities, (computed, cached), format) | as above | One HTTP request from its parameters |
| `Previewer.health()`, `Previewer.stats()` | dict | | The `/health` reply and its `cache` part |
| `inkpreview.make_handler(pv)` | a request handler class | | For `http.server.ThreadingHTTPServer` |
| `InkrsBackend(model, device, batch_size)` | the window backend | `SystemExit` when inkrs is missing, the device is `cpu`, the export cannot load, its sidecar gives no depth, or it is not a villa flat reader | `window(vol, reverse, stride)` gives villa's uint8 map of a (depth, h, w) uint8 window in forward order. Raises `BackendError` (HTTP 500) for inkrs's `UnsupportedError` and `InkrsError` |
| `inkpreview.exact_span(a, e, length, patch, stride)`, `window_span(lo, hi, length, patch, stride)`, `cells_inside(lo, hi, length, stride)` | (lo, hi), (a, e), list | | The window rule on one axis: the exact pixels of a grid window, the smallest grid window that keeps a span, the cells inside a span |
| `default_batch(model)`, `export_depth(weights, patch)` | int | `SystemExit` (`export_depth`) | The inkrs batch default; the depth from the sidecar |
| `inkpreview.EXTRA_GUARDS` | list | | Callables `guard(request_info)` run before the allow list; each may raise `Refused`. `request_info` has `mode` (`path` or `stack`), `segment`, `scroll`, `key`, `query` and `allow`. A script that wraps the server appends its own rules here |
| `inkpreview.guard(info)`, `check_allow(info)`, `path_info(seg, allow)`, `request_info(mode, allow, ...)`, `parse_allow(text)`, `scroll_id(text)`, `scroll_of(path)`, `scroll_in_path(path, allow)` | the scroll id, or the parsed value | `Refused`, `ValueError` | The allow list |
| `inkpreview.view_positions(length, patch, stride, lo, hi)` | list of positions | | The `sliding_positions` whose patch overlaps `[lo, hi)` |
| `CoreMLBackend(package, units)`, `TorchScriptBackend(model, device, input_shape)`, `FakeBackend(batch, depth, patch, out_stride)` | callable on (n, 1, D, P, P) float32 | `SystemExit` when the Core ML server or torch is missing | The model backends pad a short last batch with zero patches |
| `to_u8(prob)`, `as_prob(a)`, `png_gray(prob)`, `encode(prob, fmt)`, `upsample(y, p)`, `sigmoid(v)` | uint8 array, float32 array, PNG bytes, (body, content type), resized array, array | | `floor(255 p)`; standard library PNG; bilinear resize with half-pixel centers |
| `build_parser(default_allow)`, `main(argv, parser)`, `run(a)`, `build_backend(a)`, `model_label(a, backend)` | parser, exit code, exit code, backend, text | `SystemExit` | The command line; `build_parser().commands` maps `serve`, `snapshot` and `check` to their subparsers |

## Inputs

- **Stack mode:** the body described under HTTP. The canvas is the whole flat image of the surface at one volume level; the patch grid starts at canvas pixel (0, 0), so the client must send the true canvas size and canvas coordinates, never a crop's.
- **Path mode:** a folder with `layers/NN.tif` (one TIFF per layer, uint8 or uint16; uncompressed TIFFs are memory-mapped; names must sort in layer order) or a surface-volume zarr (an array, or a group with array `0`) of shape (layers, rows, columns). `x` is the column and `y` the row. With an allow list the path must name the scroll: the last `PHercNNNN` in the path, or, when the path has none, a folder called like a listed id. Published surface volumes of public segments are in the Vesuvius Challenge open data.
- **Model:** input shape (B, 1, depth, patch, patch); an output smaller than the patch is resized bilinearly with half-pixel centers. The batch backends apply only robust normalization, so the model must be one trained with it (`ink_9um` and its fine-tunes). Get the weights from their publisher; none are in this repository.
- **Limits:** a view of at most `max_view_px` pixels (16,777,216 by default); an upload of at most twice that plus 16 patches, in pixels.

## Outputs

`serve` prints one line, `inkpreview serving http://127.0.0.1:PORT backend=NAME model=LABEL input=SHAPE`; with no allow list and no extra rules, every command first prints the stderr notice under `check`. `snapshot` prints `wrote OUT WxH backend=NAME {cache stats}` and writes `--out`. `check` prints `ok: SCROLL may preview` or `refused: REASON`.

`GET /health`:

| Field | Type | Meaning |
| --- | --- | --- |
| `service` | string | `ink-preview` |
| `api` | int | `1` |
| `backend` | string | `coreml`, `torchscript`, `inkrs` or `fake` |
| `model` | string | The model label (`--model-name`, else the inkrs reader name, else the file name) |
| `patch`, `stride`, `depth` | int | Patch size and stride in pixels, layers the model reads |
| `voxel_um` | number or null | The model's training voxel size in micrometers, when known |
| `max_view_px` | int | Largest `w` times `h`, in pixels |
| `cache` | object | `tiles` (patches or cells held), `mb`, `cap_mb` (megabytes), `hits`, `misses` (counts) |
| `input_shape`, `output_shape` | list of int, or null | The model's batch shapes; for `inkrs` the tiles per forward, and `null` (it returns blended maps) |
| `allow` | list of string | The allowed scroll ids, or `["any"]` |
| `tiling` | string | `patch` (batch backends) or `window` (`inkrs`) |
| `quantized` | bool | `true` when `f32` is `u8 / 255` (`inkrs`) |
| `dtypes` | list of string | Upload dtypes the backend reads |
| `engine` | object | `inkrs` only: `version`, `reader`, `gpu`, `batch_size`, `weights` (file name) |

The report of `inkpreview_inkrs_check.py`:

| Field | Type | Meaning |
| --- | --- | --- |
| `inkrs` | object | The `engine` object above |
| `patch`, `stride`, `depth` | int | Pixels, pixels, layers |
| `canvas` | list of int | Rows, columns |
| `layers` | list of int | First and last layer index read from the surface volume |
| `engine_load_s`, `whole_maps_s` | number | Seconds to load the engine, and to map the whole canvas forward and reversed |
| `views` | list of object | Per view: `name`, `view` (`[x, y, w, h]`), `variant`, `pixels`, `differ` (pixels that differ from the whole map), `max_abs` (largest difference in gray levels), `need` (the uploaded rectangle or null), `cells` (computed, cached), `s` (seconds) |
| `controls` | list of object | Per control: `name`, `window` (`[x, y, w, h]`), `pixels`, `differ`, `max_abs` |
| `equal` | bool | Every view has `differ` 0 |
| `controls_differ` | bool | Every control has `differ` above 0 |
| `pass` | bool | `equal` and `controls_differ` |

| Exit code | Meaning |
| --- | --- |
| `0` | Served until interrupted, wrote the snapshot, the segment may preview, the inkrs check passed, or the trace or package was written |
| `1` | Could not start or finish (a missing package, model or Python package, a port in use, a bad snapshot view); or the inkrs check did not pass |
| `2` | Bad arguments (argparse) |
| `3` | The allow list or an extra rule refused the segment |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `the input shape must read B,1,D,P,P (such as 16,1,17,128,128)` | `--input-shape` is not five numbers with 1 second and a square patch | Give the shape `export_ckpt.py` printed |
| `the overlap must be at least 0 and under 1` | A bad `--overlap` | Use 0.5 unless the reference map used another |
| `must be a whole number of at least 1` | A bad `--batch-size` | Give 1 or more, or leave it out |
| `--allow: the allow list is empty: name at least one scroll id, or any` | `--allow` held no id | Name the scrolls, or `any` |
| `--package PATH.mlpackage is required for the coreml backend` | No package given; `coreml` is the default backend | Pass `--package`, or pick another `--backend` |
| `--model TRACED.pt is required for the torchscript backend` | No trace given | Pass `--model` |
| `--model EXPORT.safetensors (or villa's .pth) is required for the inkrs backend` | `--backend inkrs` without `--model` | Pass the export |
| `the torchscript backend needs torch in this Python (pip install torch)` | torch is not installed | Install torch, or use the Python of the environment that has it |
| `coreml_server did not start: ...` | Wrong `COREML_PY` or package, or not macOS | Point `COREML_PY` at the coremltools environment; read what `coreml_server.py` printed on stderr |
| `coreml_server.py needs numpy and coremltools in this Python (PATH): ...` | The Python in `COREML_PY` lacks them | Install them there |
| `convert.py needs torch and coremltools in this Python (PATH): ...` | Run in the wrong environment | Run it in the coremltools environment |
| `export_ckpt.py needs torch and villa's vesuvius package in this Python (PATH): ...` | Run in the wrong environment | Run it in villa's environment |
| `SHAPE must be positive integers separated by commas, such as 16,1,17,128,128` | `convert.py` got a bad shape | Give the shape the trace was made at |
| `BATCH must be at least 1` | `export_ckpt.py` got a batch under 1 | Use the batch size the server should run, such as 16 |
| `cannot listen on 127.0.0.1:PORT: ...` | The port is in use | Stop the other server or pass another `--port` |
| `refused: PHercNNNN is not on the preview allow list ...` (403 `{"refused": ...}` over HTTP) | The scroll is not on the server's allow list | Start the server with that scroll in `--allow`, if you mean to preview it |
| `no scroll id in the path; name the scroll (PHercNNNN) so the allow list can be checked` | Path mode with an allow list, and the path names no scroll | Use a path that names the scroll |
| `no scroll parameter; send scroll=ID so the allow list can be checked` | Stack mode with an allow list and no `scroll` | The client sends `scroll` |
| 409 `{"need": ...}` | Stack mode: patches of the view are neither cached nor uploaded | Not an error: upload the `need` rectangle and post again |
| `the inkrs backend needs inkrs in this Python (pip install inkrs)` | inkrs is not installed in the server's Python | Install it, or run the server with the Python that has it |
| `the inkrs backend runs on a GPU (Metal on Apple Silicon, CUDA elsewhere): use --device auto, mps or cuda, not cpu` | `--device cpu` with inkrs | Use `torchscript` on a CPU |
| `inkrs cannot run MODEL here (UnsupportedError): ...` | The GPU, the export or the checkpoint is one inkrs does not run | Read inkrs's message |
| `inkrs could not load MODEL: ...` | The file is broken or not an export | For a `.pth`, export it first with `python -m inkrs.export_weights` |
| `inkrs: cannot tell how many layers MODEL reads: no readable export sidecar FILE (...)` | No readable `.json` beside the export | Pass the `.safetensors` that `inkrs.export_weights` wrote, with its `.json` beside it |
| `inkrs: cannot tell how many layers MODEL reads: crop_size ... in FILE is not [depth, P, P]` | The sidecar's `crop_size` is not depth, patch, patch | Export the checkpoint again |
| `inkrs: MODEL is a NAME export, which inkrs maps only whole, by its own convention; the preview needs villa's flat readers (Engine.run)` | The export is not a villa flat reader | Use a villa flat reader, such as `ink_9um` |
| `the inkrs backend reads uint8 layers only; send dtype=uint8` (400) | A uint16 upload to the `inkrs` backend | Upload uint8 |
| `the inkrs backend reads uint8 layers only (an inkrs limit); send dtype=uint8` | A uint16 surface volume in path mode with `inkrs` | Use a uint8 surface volume |
| `the inkrs backend needs D layers, got N` | A window with another layer count reached the engine | Send `depth` layers, as `/health` reports |
| `the surface volume is DTYPE; inkrs reads uint8 only` | `inkpreview_inkrs_check.py` got a surface volume that is not uint8 | Give it a uint8 surface volume |
| 500 `inkrs failed on this window (InkrsError): ...` | inkrs failed on one request (out of GPU memory, for instance) | The server stays up; lower `--batch-size` or ask for a smaller view |
| 500 `inkrs does not support this window (UnsupportedError): ...` | inkrs refused the window | Read inkrs's message; the server stays up |
| 500 `inkrs returned DTYPE SHAPE, not a uint8 map of SHAPE` | The engine's reply is not a map of the window | Check the inkrs version against Needs |
| 500 `window rule: cells ... of the window y A:B x C:D are not exact` | The window rule's two functions disagree; it should not happen | Report it with the request; nothing was served |
| `key is required: text of at most 200 characters` | No `key`, or a longer one | Send a short key, such as a hash |
| `parameter NAME is required` | A missing `cw`, `ch`, `x`, `y`, `w`, `h`, `sx`, `sy`, `sw` or `sh` | Send it |
| `parameter NAME must be an integer, got ...` | A value that is not a whole number | Send integers |
| `the view must be at least 1 px wide and 1 px high` | `w` or `h` under 1 | Send the visible rectangle |
| `the canvas size cw, ch must be at least 1 by 1` | Stack mode: a bad canvas size | Send the true canvas size |
| `the view must lie inside the canvas` | Stack mode: the view leaves the canvas | Clip the view to the canvas |
| `the view has N px, over max_view_px M` (413) | The view is too large | Zoom in, or raise `--max-view-px` |
| `the view needs an upload of N px, over the limit of M px` (413) | The patches of the view span more than the upload limit; a very long, thin view can | Ask for a smaller view |
| `the upload has N px, over the limit of M px` (413) | The uploaded rectangle is over the limit | Upload the `need` rectangle, no more |
| `the body has N bytes, over the limit of M` (413) | The body is larger than the largest allowed upload | Ask for a smaller view |
| `the body has over N bytes, the limit` (413) | The same, for a chunked body | Ask for a smaller view |
| `a body needs sx, sy, sw and sh: the canvas rectangle it covers` | A body without its rectangle | Send all four |
| `the uploaded rectangle must be at least 1 px and lie inside the canvas` | A bad `sx`, `sy`, `sw`, `sh` | Send the `need` rectangle as given |
| `the body has N bytes; D layers of H x W DTYPE need M` | The body is not depth times `sh` times `sw` voxels | Send the layers the 409 asked for, `depth` of them |
| `dtype must be uint8 or uint16, got ...` | Another voxel type in `dtype` | Send uint8 or uint16 |
| `the stack must be uint8 or uint16 of shape (D, sh, sw)` | `preview_stack` got another array | Pass a (depth, rows, columns) array of uint8 or uint16 |
| `variant must be f or r, got ...` | Another variant | `f` or `r` |
| `variant must be f, r or s, got...` | `flat_contract.slice_order` got another variant | `f`, `r` or `s` |
| `format must be u8, f32 or png, got ...` | Another format | Pick one of the three |
| `the chunked body is malformed` | A broken chunked upload | Send the body with a `Content-Length` |
| `Content-Length must be a byte count` | A broken `Content-Length` header | Send the byte count of the body |
| `the JSON body must be an object` | Path mode with a JSON body that is not an object | Send the JSON fields, or the stack-mode query |
| `segment is required: the path of a surface volume` | A POST with no query is path mode, and it had no `segment` | Send the JSON fields, or the stack-mode query |
| `no surface volume at PATH` | Path mode: the segment path does not exist | Check the path |
| `window has...slices, model needs...` | Fewer layers than the model depth | Give a window of at least the model depth |
| `scale must be at least 1, got ...` | A bad `scale` | Use 1 or more |
| `snapshot: ...` and exit code 1 | One of the request errors above, from `snapshot` | As above |
| `unknown path` (404) | Not `/health` or `/preview` | Check the URL |
| 500 `{"error": "ModuleNotFoundError: No module named 'zarr'"}` (or `'tifffile'`) | Path mode needs the package to read the volume | Install it in the server's Python |
| An old picture after the surface volume on disk was rewritten | Path mode caches by path and layers, not by file time | Restart the server. Stack mode has no such problem when the client changes the key |

## How it works

`inkpreview.py` loads `flat_contract.py` from its own folder; nothing else in the repository is imported except `kit.termstyle` for the terminal look, when stdout is a terminal.

1. `guard` runs every rule in `EXTRA_GUARDS`, then the allow list, before anything is read or computed.
2. The patch positions of the view are those of `sliding_positions(canvas size, patch, stride)` on each axis whose patch overlaps the view (`view_positions`): 0, 64, 128 and so on and one position flush to the edge. `stride = round(patch * (1 - overlap))`.
3. Each position is looked up in the cache: under (path, layer order, row, column) in path mode, under (key, canvas size, variant, row, column) in stack mode. In stack mode a patch that is not cached must lie inside the uploaded rectangle; if any does not, the reply is 409 with the bounding rectangle of every patch that is not cached (those inside the upload too) and nothing runs. Because the next upload replaces this one, that upload is enough even when another viewer's requests pushed cached patches out in between.
4. New patches are cut from the volume or the upload in their own dtype (zero filled past the edge of a canvas smaller than the patch; the layers reversed for `r`). An all-zero patch is cached as empty and never reaches the model. The others are normalized with `normalize_robust`, run in model-sized batches (the last one padded with zero patches), passed through a sigmoid and resized to the patch size if the model's output is smaller.
5. The view is the Hann-weighted mean (`hann2d`, floor 0.001) of its patches, summed in row order in float32 whatever the cache held, so the same view gives the same bits after any pan history. Pixels with weight at most 1e-6 are 0.
6. `u8` output is `floor(255 p)` computed in float32, villa's uint8 convention.

The `inkrs` backend replaces steps 2 to 5, since inkrs normalizes, tiles and blends a window itself:

- The cache holds cells of stride by stride final pixels (cell `(i, j)` at row `i * stride`, column `j * stride`). A view is ready when all its cells are cached. Otherwise the cells it lacks give one window: their bounding rectangle widened by `window_span` on each axis and clipped to the canvas. In stack mode that window must lie inside the upload, else the reply is 409 with that window as `need`; nothing runs.
- The window rule (`exact_span`; derived in the code from villa's positions 0, s, 2s and so on plus a last one flush to the edge, on the window and on the canvas). inkrs tiles a window `[a, e)` from its own origin. With `a` a multiple of the stride `s`, its regular patches are patches of the whole map, and a window pixel `p` gets exactly the whole map's patches when: `a = 0` or `p >= a + P - s` (low side); and `e` is the canvas end, or `p < e - P + s` when `e - P` is on the grid (`p < e - P` when it is not, since the window's own flush patch is then no patch of the map) and `p < L - P` (high side), with `P` the patch and `L` the canvas length. Rows and columns are independent. So for `P = 2 s` (128 and 64, 384 and 192) the window needs a margin of one stride on each side that is not the canvas edge, and at least one patch on each axis; a kept pixel within `P` of the canvas end needs the window to run to the end, where inkrs's flush patch is the whole map's. `window_span` gives the smallest such grid window.
- An axis no longer than the patch is the whole axis; when it is shorter, the server zero fills it to one patch before inkrs runs and cuts the map back.
- inkrs runs window `(0, 1)` over the uploaded forward layers, or `(depth - 1, -1)` for `r`: the layers deepest first. The tests check that this equals the reversed array read forward.
- Every exact cell of the window is stored, including those outside the view, so a pan computes only the window around its new cells. The cells are inkrs's uint8 pixels; `f32` divides them by 255.

Constants: `MAX_VIEW_PX` 16,777,216; the upload limit is twice `max_view_px` plus 16 patches, in pixels; `DRAIN_BYTES` 64 MiB (an oversized body up to this size is read and dropped so the connection can go on); `flat_contract.PATCH` 128; the Hann floor 0.001; the robust scale 1.4826 times the median absolute deviation.

## Cost and time

Free: local only, nothing rented.

- Stack mode over HTTP with the `fake` backend (no model), measured 2026-11-13 in a cloud container with 4 vCPU shared with other jobs, on a synthetic uint8 stack of 17 layers and a 5240 by 5820 canvas: a cold 1920 by 1080 view took 3.82 s for 576 patches, including the 43.7 MB upload; a 96 px pan right took 0.29 s (36 new patches, a 4.0 MB upload); a 96 px pan down took 0.48 s (64 new patches, 6.9 MB); the same view again took 0.03 s. The times leave out the client's own sampling. Almost all of the server's time is normalization, not the fake model.
- With a real model, on any backend: Not measured here. Measure on your machine; `X-Tiles` tells how many patches a reply computed.
- Memory: the cache cap (`--cache-mb`, 256 MB by default), plus one upload and one view, plus the model. Not measured.
- GPU work with a real model belongs on a machine with that GPU; whole maps and long jobs follow the compute rule (hard rule 11).

## For agents

- **Command:** `python3 scripts/ane/inkpreview.py serve --backend BACKEND ...`, then `GET /health` and `POST /preview` (both JSON or raw bytes; no `--json` flag is needed). One view without a server: `python3 scripts/ane/inkpreview.py snapshot --backend BACKEND ... --segment SEG --x X --y Y --w W --h H --out view.png`. The inkrs check: `python3 scripts/ane/inkpreview_inkrs_check.py --model EXPORT.safetensors --segment SURFACE --json check.json`.
- **Parse:** the status code first: 200 carries the view (`X-Shape: h,w`, `X-Tiles: computed,cached`), 409 carries `need` (upload that rectangle and post again), 403 `refused`, 400, 413 and 500 `error`. `/health` JSON for `backend`, `model`, `patch`, `stride`, `depth`, `dtypes`. From the check's report: `pass`, then `views[].differ` and `controls[].differ`.
- **Rerun:** safe; `snapshot` overwrites `--out` and the check overwrites `--json`; the server keeps no state on disk.
- **Success:** exit 0, or HTTP 200 with a backend other than `fake`. For the check: exit 0 with `pass` true, every `views[].differ` 0 and every `controls[].differ` above 0.
- **Not a pass:** any `backend=fake` output; a preview without its reversed control; a preview used as a result or a score; a preview on a segment the model trained on taken as evidence about the model; a Core ML preview called identical to a villa map; an inkrs preview on a machine where `inkpreview_inkrs_check.py` has not passed; parity claimed against a whole map whose input was prepared differently.
- **Go-ahead:** Nothing to run it locally on public data. Posting a preview or what it shows needs Chase's yes (the go-ahead rule, hard rule 8).
- **Never:** describe a preview as ink or letters found or read; publish or describe a preview of a prize-eligible scroll (the possible-findings rule, hard rule 1); preview a segment before its readout rules are fixed when a readout is planned (the preregistration rule, hard rule 3); commit weights, Core ML packages, traces, surface volumes or previews to this repository (the no-data rule, hard rule 6); bind the server to another address than 127.0.0.1.

## Tests

```bash
python3 -m unittest tests.test_inkpreview -v
```

78 tests, about 47 s in the cloud container on 2026-11-13 (5 skipped there: no torch, tifffile or zarr).

- Covered, all with the `fake` backend or a stand-in inkrs module written in the test: the contract functions against their definitions; path mode against a whole-canvas map written from villa's rule, to 1e-6, with flush edges, small canvases, views on the right and bottom edges, and the displaced-grid control that must differ; stack mode (the 409 rectangle of the worked example, an upload equal to path mode bit for bit, a pan needing only the new strip, a diagonal pan needing the bounding box of the new patches, two viewers that push each other's patches out of the cache getting their views after one more upload, keys and canvas sizes sharing nothing, the reversed variant, `floor(255 p)`, 413, 400, 403); the row-major sum order bit for bit; the allow list and `EXTRA_GUARDS`; the stderr notice when there is no allow list; the HTTP server end to end, chunked uploads included; `snapshot`; the window rule against an enumeration of the patch sets; the `inkrs` backend on the stand-in (views on and off the grid, pans, the reverse direction, patch 384 with stride 192, small canvases, formats, engine errors as 500, the command line, and `inkpreview_inkrs_check.py` passing and failing when the margin is dropped); the TorchScript backend with a tiny traced module (skipped without torch); zarr and TIFF reading (skipped without those packages).
- Not covered: any model's numbers; real inkrs (the stand-in is not inkrs: run `inkpreview_inkrs_check.py`); Core ML, which needs macOS; `export_ckpt.py`, `convert.py` and `coreml_server.py`, which need villa, torch and coremltools and have no test here.

## History

- 2026-11-13: first public version: the server with ink preview api 1 (stack mode with the 409 `need` round trip, path mode), the `coreml`, `torchscript`, `inkrs` and `fake` backends, `flat_contract.py`, the converter scripts and `inkpreview_inkrs_check.py`, with their tests (`aba138c`).

## Related

- [inkrs](https://github.com/praveenperera/inkrs) by Praveen Perera, MIT or Apache 2.0: the engine behind the `inkrs` backend. Its Python package is `inkrs` on PyPI.
- [villa](https://github.com/ScrollPrize/villa): the official pipeline, whose flat ink inference (`vesuvius.ink_detection.inference.infer`) this server's grid, normalization and blending follow, and whose `configure_model` `export_ckpt.py` calls.
- [auc](auc.md): score a whole ink map against published labels with the reverse-depth control; the tool for results.
- [ink-lens](ink-lens.md): runs an ink model on one region of a VC3D segment in both depth orders and writes VC3D's own files.
- [mac-verify](mac-verify.md): checks on a Mac that villa's GPU ink inference gives the CPU's map; the kind of device check a new backend needs before its maps are relied on.
- [run-ledger](run-ledger.md): `python -m kit run init`, which fixes readout rules before a target map exists.
- [termstyle](termstyle.md): the terminal look the scripts use when stdout is a terminal.
