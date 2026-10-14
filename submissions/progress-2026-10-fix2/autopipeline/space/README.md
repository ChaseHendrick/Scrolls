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
  - scrollprize/ink_9um
short_description: ink_9um maps with a reversed-layer control
pinned: false
---

# AutoPipeline ink step

Pick a crop of a released segment, or upload a small surface volume. The Space runs the released `ink_9um` ink model on it twice: once with the layers in their stored order, and once with the layers reversed. The reversed map is the control. A model that reads ink in depth order should do worse on it. Where the crop has published ink labels, both maps get a pixel AUC.

AutoPipeline runs villa's pipeline from a released scan to a scored ink map, with checks that can fail at every step. This Space is its last step only.

An ink map is model output, not a reading.

## What runs

- Model: [`scrollprize/ink_9um`](https://huggingface.co/scrollprize/ink_9um), seed 42, step 75,000 (MIT). The Space downloads it when it starts and refuses it unless its SHA-256 is `e635558ae6a1a807a7e5ec1e83adfd45bc3c0ac53883ea43f1d4e085d62a9cab`.
- Inference: villa's flat ink inference (`vesuvius.ink_detection.inference.infer`) at commit `e0bbb8b40a2db58b1d71864f286eb85717e59e64`, called in the Space's own process on an array in memory. Its settings are villa's defaults: 128 px patches, overlap 0.5, Hann blending, the middle 17 layers. On a CPU, the maps are byte for byte what villa's command line writes for a zarr of the same crop (`--direction both`). On the GPU, villa runs this checkpoint in fp16, so the maps differ a little from a CPU run.
- Data: read anonymously from the [open-data bucket](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com) when you press Run analysis. Nothing is bundled.
- Checks: a map that is constant, has non-finite pixels, or equals its control is refused, not shown. The forward map is never shown without its control.
- Score: pixel AUC, the chance that a labelled ink pixel scores above a labelled background pixel, inside the labelled area. A 64 px edge is left out, where a crop sees less context than the whole segment.

## The samples

Each is a 640 px crop where the labels mark a lot of ink. I picked these windows with the labels, so none of them is a blind test.

| Sample | What it is to ink_9um |
| --- | --- |
| PHerc0841 w00 | Development segment. ink_9um was not trained on PHerc0841. |
| PHerc0841 auto-grown 896 | Development segment, as above. |
| PHerc0139 w035 | Training data. A high AUC here only shows the pipeline runs. |
| PHerc0139 w045 | Not held out: ink_9um was trained on the 2.4 µm render of this same surface. A check on training data. |

## Uploads

A surface volume as `.npy` or a multi-page `.tif`, layers first (layers x height x width), uint8 or uint16, 128 to 768 px a side, 17 to 65 layers, at most 64 MB. Its shape and type are checked from the file's header before its data are read. When you press Analyze upload it is read into memory and its upload file is deleted; a file you upload but do not run is deleted within 11 minutes. The images of it (its middle layer and the two maps) are sent inside the page and never written to the Space's disk. Uploads get maps but no AUC, since there are no labels for them.

## GPU time

Each run is one GPU call with both directions in it. The call asks for 10 s plus 0.06 s per 128 px patch, at least 20 s: 20 s for a 640 px sample, 25 s for a 768 px upload. A crop that would need more than 60 s is refused. On Hugging Face the time counts against the daily GPU quota of whoever presses Run.

## Code

`app.py` is the page and the call into villa. `inkspace.py` holds the rest: the sample list and the segments the Space may read, crop sizing, the bucket reads, the checks and the scoring. They use AutoPipeline's `kit/` (the anonymous bucket reader and `kit/auc.py`) and `scripts/vc3d/ink.py` (the map checks). Code: Apache License 2.0. The model and the data keep their own licenses.

AutoPipeline's full source, with these files, its tests and its guide: [ChaseHendrick/Scrolls, branch submission/progress-2026-10](https://github.com/ChaseHendrick/Scrolls/tree/submission/progress-2026-10/submissions/progress-2026-10/autopipeline).
