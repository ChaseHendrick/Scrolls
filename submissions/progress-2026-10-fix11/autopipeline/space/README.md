---
title: AutoPipeline ink step
colorFrom: gray
colorTo: yellow
sdk: gradio
sdk_version: 6.28.0
python_version: "3.12"
app_file: app.py
suggested_hardware: zero-a10g
license: apache-2.0
models:
  - domenicor046/reader-v3
short_description: Reader V3 ink maps with a reversed-layer control
tags:
  - vesuvius-challenge
  - ink-detection
  - zerogpu
  - mcp-server
pinned: false
---

# AutoPipeline ink step

Pick a crop of a released segment, or upload a small surface volume. The Space runs Reader V3, Domenico Russo's community ink model, on it twice: once with the layers in their stored order, and once with the layers reversed. The reversed map is the control. A model that reads ink in depth order should do worse on it. Where the crop has published ink labels, both maps get a pixel AUC.

AutoPipeline runs villa's pipeline from a released scan to a scored ink map, with checks that can fail at every step. This Space is its last step only.

An ink map is model output, not a reading.

## What runs

- Model: [Reader V3](https://huggingface.co/domenicor046/reader-v3), file `reader-v3.pth` (MIT), by Domenico Russo. It continues Reader v2, itself a fine-tune of the released `ink_9um`, on 384 px tiles; it keeps `ink_9um`'s checkpoint format, so villa's ink detection loads it unchanged. It is AutoPipeline's default reader since version 0.1.8. Its author reports fewer false ink marks on blank papyrus than Reader v2 (Community report). This Space makes no claim that it reads ink better than Reader v2. The Space downloads it when it starts and refuses it unless its SHA-256 is `ea405417450abd8ace1b8ff79ebce3adb646c5e48ab95da46844d77efe984d8a`.
- Inference: villa's flat ink inference (`vesuvius.ink_detection.inference.infer`) at commit `e0bbb8b40a2db58b1d71864f286eb85717e59e64`, called in the Space's own process on an array in memory. Its settings are the checkpoint's own and villa's defaults: 384 px patches (from Reader V3's config), overlap 0.5, Hann blending, the middle 17 layers. These are the calls villa's command line makes for a zarr of the same crop (`--direction both`). On the GPU, villa runs this checkpoint in fp16, so the maps differ a little from a CPU run.
- Data: read anonymously from the [open-data bucket](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com) when you press Run analysis. Nothing is bundled.
- Checks: a map that is constant, has non-finite pixels, or equals its control is refused, not shown. The forward map is never shown without its control.
- Score: pixel AUC, the chance that a labeled ink pixel scores above a labeled background pixel, inside the labeled area. A 64 px edge is left out, where a crop sees less context than the whole segment. With 384 px patches a crop's map still differs from the whole segment's map further in, so a crop's AUC is a crop number, not the segment's.

## The samples

Each is a 640 px crop where the labels mark a lot of ink. I picked these windows with the labels, so none of them is a blind test.

| Sample | What it is to Reader V3 |
| --- | --- |
| PHerc0841 w00 | Development segment. Reader V3 was not trained on PHerc0841, and neither were Reader v2 and `ink_9um`, the models it continues. Reader V3's author benchmarked PHerc0841 while choosing its recipe, so it may have been selected on these segments. |
| PHerc0841 auto-grown 896 | Development segment, as above. |
| PHerc0139 w035 | Training data: `ink_9um` was trained on it, and Reader v2 and Reader V3 continue from `ink_9um`. A high AUC here only shows the pipeline runs. |
| PHerc0139 w045 | Not held out: Reader V3 was trained on this segment and on its 2.4 µm render, as Reader v2 was before it. A check on training data. |

## Uploads

A surface volume as `.npy` or a multi-page `.tif`, layers first (layers x height x width), uint8 or uint16, 384 to 768 px a side, 17 to 65 layers, at most 64 MB. Its shape and type are checked from the file's header before its data are read. When you press Analyze upload it is read into memory and its upload file is deleted; a file you upload but do not run is deleted within 11 minutes. The images of it (its middle layer and the two maps) are sent inside the page and never written to the Space's disk. Uploads get maps but no AUC, since there are no labels for them.

## For agents and scripts

Every tool is an API endpoint and an MCP tool. MCP clients (Claude, Cursor and others) add the server at
`/gradio_api/mcp/sse` on this Space's own host (the page's Connect your tool panel gives the full address) with the
header `Authorization: Bearer hf_...`, your own Hugging Face token, so each call spends your ZeroGPU quota; without it
calls share the small logged-out quota. MCP clients see the tool names below with the Space's name as a prefix, such as
`autopipeline_ink_ink_sample`.

| Tool | What it does | GPU |
| --- | --- | --- |
| `ink_sample` | a sample id (`0841-w00`, `0841-ag896`, `0139-w035`, `0139-w045`) and a size (384 to 640 px) in; a JSON record with both AUCs and the forward-versus-control check, and a PNG preview (CT, stored order, reversed control) out | yes |
| `ink_upload` | the URL of your own surface volume (the limits under Uploads) in; a JSON record out, with no image written to the Space's disk and no AUC | yes |
| `list_samples` | the samples, what each is to the model, the checkpoint and the limits | no |

```python
from gradio_client import Client
c = Client("OWNER/autopipeline-ink", token=YOUR_TOKEN)   # gradio_client 2; your token: your own ZeroGPU quota
record, preview = c.predict("0841-w00", 640, api_name="/ink_sample")
record["receipt"]["auc"]    # stored order and reversed control, on the same labeled pixels
```

The page's own buttons stay callable as `/on_sample` and `/on_upload`; they return the page's HTML and are not MCP tools.

## GPU time

Each run is one GPU call with both directions in it. The call asks for 10 s plus 1 s per 384 px patch, at least 20 s: any crop the Space takes is at most 3 x 3 patches, so 28 s for a 640 px sample and for a 768 px upload. A crop that would need more than 60 s is refused. On Hugging Face the time counts against the daily GPU quota of whoever presses Run.

## Code

`app.py` is the page and the call into villa. `inkspace.py` holds the rest: the sample list and the segments the Space may read, crop sizing, the bucket reads, the checks and the scoring. They use AutoPipeline's `kit/` (the anonymous bucket reader and `kit/auc.py`) and `scripts/vc3d/ink.py` (the map checks). The Connect your tool panel (`connect.json`, `connect.html`, `CONNECT.md`) lists the data's URLs and ready snippets for other tools. Code: Apache License 2.0. The model and the data keep their own licenses.

AutoPipeline's full source, with these files, its tests and its guide: [ChaseHendrick/Scrolls, branch submission/progress-2026-10-fix8](https://github.com/ChaseHendrick/Scrolls/tree/submission/progress-2026-10-fix8/submissions/progress-2026-10-fix8/autopipeline).
