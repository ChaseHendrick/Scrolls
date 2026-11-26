---
license: cc-by-nc-4.0
pretty_name: First Letters ink atlas
language:
- en
task_categories:
- image-segmentation
tags:
- vesuvius-challenge
- herculaneum
- papyrus
- ink-detection
- x-ray-ct
- model-outputs
- benchmark
annotations_creators:
- machine-generated
size_categories:
- 1K<n<10K
configs:
- config_name: default
  default: true
  data_files:
  - split: train
    path:
    - "metadata.jsonl"
    - "surfaces/**/*.png"
    - "surfaces/**/*.jpg"
- config_name: surfaces
  data_files:
  - split: train
    path:
    - "surfaces/metadata.jsonl"
    - "surfaces/*/*/preview.jpg"
---

# First Letters ink atlas

Seven public ink detection models, run on the same public traced surfaces of the Herculaneum scrolls in the Vesuvius
Challenge First Letters prize list, with every map kept: both depth orders, three depth windows, and a z-score
ensemble. Each surface was rendered once from the public CT onto one shared 9.6 µm canvas, so the maps of different
models line up pixel for pixel and can be compared, stacked or ensembled directly, with no registration step.

Every map is model output, not a reading.

![Seven ink models and their ensemble on one PHerc0343 reference surface, in the same box](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas/resolve/main/assets/hero.jpg)

**At a glance:** 32 surfaces (25 from 13 First Letters scrolls, 7 references on PHerc0343) · 116.2 cm² of
papyrus surface · 1,216 model maps, 128 ensemble maps, 32 CT layers and 32 previews · 7 models, all with MIT
weights · CC BY-NC 4.0.

**Browse it without downloading:** the [Ink Atlas Space](https://huggingface.co/spaces/SharpMeow/ink-atlas) shows any
map with a loupe, compares every model on one box, and serves the atlas to agents as an MCP server.

## Quick start

The Dataset Viewer above and `load_dataset` give one row per picture, with its surface, model, window, depth order
and liveness numbers beside it:

```python
from datasets import load_dataset

maps = load_dataset("SharpMeow/first-letters-ink-atlas", split="train")          # 1,408 pictures with columns
reader = maps.filter(lambda r: r["model"] == "reader-v3" and r["window"] == "c+0")
surfaces = load_dataset("SharpMeow/first-letters-ink-atlas", "surfaces", split="train")  # 32 rows with previews
```

Files for one scroll, or one map, with `huggingface_hub` (paths are stable; nothing has moved since the first
release):

```python
from huggingface_hub import hf_hub_download, snapshot_download

root = snapshot_download("SharpMeow/first-letters-ink-atlas", repo_type="dataset",
                         allow_patterns=["atlas.json", "surfaces/PHerc0268/*"])
png = hf_hub_download("SharpMeow/first-letters-ink-atlas", repo_type="dataset",
                      filename="surfaces/PHerc0268/kbh-PHerc0268_2704_5907_7421/maps/reader-v3/c+0_s1_forward.png")
```

The tables alone, with pandas (no pictures downloaded):

```python
import pandas as pd

base = "https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas/resolve/main/"
surfaces = pd.read_csv(base + "index/surfaces.csv")
maps = pd.read_csv(base + "index/maps.csv")
```

Check a full download against `SHA256SUMS` (every file but this card):

```bash
hf download SharpMeow/first-letters-ink-atlas --repo-type dataset --local-dir first-letters-ink-atlas
cd first-letters-ink-atlas && sha256sum -c SHA256SUMS
```

From an agent: the Space's MCP server is `https://sharpmeow-ink-atlas.hf.space/gradio_api/mcp/` (six tools:
`atlas_summary`, `list_scrolls`, `list_surfaces`, `surface_info`, `get_map` for a whole map or a crop, and
`compare_models`); from Python,
`gradio_client.Client("SharpMeow/ink-atlas")`.

## What is in it

![One surface: the 65-layer canvas, the three depth windows, the two depth orders and the files](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas/resolve/main/assets/anatomy.png)

| Path | What it is |
| --- | --- |
| `surfaces/SCROLL/SURFACE_ID/maps/MODEL/WINDOW_s1_ORDER.png` | one model's map, 8-bit grayscale; windows `c-4`, `c+0`, `c+4`; orders `forward`, `reverse`. Hecate 9.6 has `c+0` only |
| `surfaces/SCROLL/SURFACE_ID/ensemble/ORDER.png` | z-score ensemble of the alive models, z-scored with the statistics of the forward maps |
| `surfaces/SCROLL/SURFACE_ID/ensemble-rev/ORDER.png` | the same ensemble, z-scored with the statistics of the reverse maps |
| `surfaces/SCROLL/SURFACE_ID/ct_mid.png` | the middle CT layer of the render (the layer on the mesh) |
| `surfaces/SCROLL/SURFACE_ID/preview.jpg` | CT and ensemble side by side, long side 1600 px |
| `surfaces/SCROLL/SURFACE_ID/meta.json` | the surface's full record: mesh and CT links, render record with its SHA-256, every model's liveness at every window and order, training exposure, the face check of every model pair |
| `atlas.json` | every surface with its path, and the release counts per scroll |
| `metadata.jsonl` | one row per picture under `surfaces/` (the default config) |
| `surfaces/metadata.jsonl` | one row per surface, joined to its preview (the `surfaces` config) |
| `index/maps.csv`, `index/surfaces.csv` | the same two tables as spreadsheets |
| `assets/` | the pictures on this card |
| `provenance.json` | sources, code commit, caveats and the spent list, machine-readable ([standard](https://github.com/ChaseHendrick/Scrolls/blob/main/docs/standards/dataset-card.md)) |
| `SHA256SUMS` | the SHA-256 of every file but this card |

`MODEL` is one of `ink_9um-s42`, `ink_9um-s43`, `reader-v2`, `reader-v3`, `dense-native`, `d9v2`, `hecate-9.6`.
`SURFACE_ID` is `kbh-` plus the mesh's name in the source survey (`SCROLL_X_Y_Z`, its seed point in scan voxels).

## Columns

The default config (`metadata.jsonl`, `index/maps.csv`), one row per picture:

| Column | Type | Meaning |
| --- | --- | --- |
| `image` | image | the picture (default config only) |
| `file_name` | string | its path in the repository (CSV and JSONL only) |
| `surface_id`, `scroll` | string | which surface and scroll |
| `role` | string | `eligible` (a First Letters scroll) or `reference` (PHerc0343) |
| `kind` | string | `map`, `ensemble`, `ensemble-rev`, `ct` or `preview` |
| `model` | string | model id; `ensemble` for both ensemble kinds; empty for `ct` and `preview` |
| `window` | string | `c-4`, `c+0` or `c+4` (maps only) |
| `window_offset_layers` | int | the window's center in 9.6 µm layers from the mesh: -4, 0 or 4 |
| `order` | string | `forward` (depth order as stored) or `reverse` |
| `stats_from` | string | for ensembles: which order's statistics set the z-scores |
| `value_min`, `value_max` | float | what pixel values 0 and 255 stand for (0 and 1 for maps, -2 and 4 for ensembles) |
| `alive` | bool | the liveness verdict of this map (maps only) |
| `p50`, `p99`, `std` | float | median, 99th percentile and standard deviation of the map's values on the surface |
| `spread_p99_p50` | float | `p99` minus `p50`, the spread the liveness check reads |
| `fraction_near_half` | float | share of the map's pixels with values near 0.5 |
| `url` | string | direct download link |

The `surfaces` config (`surfaces/metadata.jsonl`, `index/surfaces.csv`), one row per surface: `surface_id`, `scroll`,
`role`, `source` (who traced the mesh), `scan` (the CT's id in the open data), `voxel_um` (the scan's voxel size),
`canvas_um` (9.6), `height_px` and `width_px` of the canvas, `layers` (65), `rendered_px` (canvas pixels the mesh
covers), `area_cm2` (`rendered_px` times one 9.6 µm pixel), `models_alive` and `alive_models`, `path`, `meta_url`,
`preview_url`, `mesh_url`, `ct_url` and `render_sha256`; in the viewer the preview is the `image` column.

## How to read the values

```python
import numpy as np
from PIL import Image

v = np.asarray(Image.open(png), np.float32) / 255
prob = v                       # a model map: the model's 0 to 1 output
z = -2 + 6 * v                 # an ensemble map: mean z-score, from -2 to 4
```

- **Depth order.** A surface has two faces. `forward` feeds a model the 65 layers as stored and `reverse` feeds the
  same layers flipped, so the model reads the other face as the writing side. Which face carries ink is not known in
  advance; keep both and use the reverse map as the control for the forward one, or the other way round.
- **Depth window.** Where the model's 3D input is centered: on the mesh (`c+0`) or 4 layers (38.4 µm) to either side.
  A mesh a little off the sheet can read better off center.
- **Liveness.** A map is alive when its values have real spread on the surface (the metrics are in each row and in
  `meta.json`). Dead maps are kept, so absence of signal is part of the record; the ensemble uses alive models only.
- **Canvas.** Pixels outside the mesh are 0 in `ct_mid.png` but not in the maps, which hold model output there too;
  use `ct_mid.png > 0` as the surface mask before any statistic.

## How it was made

1. **Surfaces.** Traced meshes from ketchupbyheinz's
   [vesuvius-scroll-survey](https://github.com/ketchupbyheinz/vesuvius-scroll-survey) (commit `1f12c1ce`), on the
   public scans in the [Vesuvius Challenge open data](https://scrollprize.org/data).
2. **Render.** Each mesh is rendered from level 0 of the public CT, streamed chunk by chunk, onto a 9.6 µm canvas
   with 65 layers 9.6 µm apart along each pixel's mesh normal (trilinear sampling, the canvas rule villa's
   `vc_render_tifxyz` uses with `--scale`). One canvas for every scan, whether 8.64 or 9.362 µm, so each 9 µm model
   reads at its own scale. Each render's SHA-256 is in `meta.json`.
3. **Models.** All seven run with pinned weights and SHA-256 checks, through villa's own flat inference and
   ink-sdk's Hecate adapter, at three windows and both orders.
4. **Ensemble.** [ink-sdk](https://github.com/LimeGS/ink-sdk)'s ensemble, Erwin Nieuwlaar's PHerc0343 recipe: the
   mean of per-model z-scores over the alive models. 25 surfaces have all seven models alive and 7 have six.
5. **Face check.** For every pair of alive models, ketchupbyheinz's face check from
   [villa PR #2318](https://github.com/ScrollPrize/villa/pull/2318) scores whether their strongest marks agree better
   on one face than on the other. The scores are in each `meta.json`.
6. **Release rule.** A rule fixed before any map existed decided which surfaces are in this release. It had to flag
   the PHerc0343 mesh behind the
   [First Letters prize awarded on 8 October 2026](https://scrollprize.substack.com/p/50k-first-letters-prize-awarded-for),
   and it did; it flagged all seven PHerc0343 references. `atlas.json` counts the surfaces of each scroll that are not
   in this release.

![Surfaces in this release by scroll](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas/resolve/main/assets/surfaces-per-scroll.png)

## Models

| Model id | Model | By | Weights | License |
| --- | --- | --- | --- | --- |
| `ink_9um-s42`, `ink_9um-s43` | ink_9um seeds 42 and 43, step 75,000 | Vesuvius Challenge | [scrollprize/ink_9um](https://huggingface.co/scrollprize/ink_9um) | MIT |
| `reader-v2` | Reader v2 | Domenico Russo | [domenicor046/reader-v2](https://huggingface.co/domenicor046/reader-v2) | MIT |
| `reader-v3` | Reader V3 | Domenico Russo | [domenicor046/reader-v3](https://huggingface.co/domenicor046/reader-v3) | MIT |
| `dense-native` | dense_native, step 16,000 | Erwin Nieuwlaar | [Nieuwlaar/ink9um-dense-native](https://huggingface.co/Nieuwlaar/ink9um-dense-native) | MIT |
| `d9v2` | d9v2 | TAUIL-Abd-Elilah | [pherc0826-first-letters-search](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search) | MIT |
| `hecate-9.6` | Hecate 9.6 µm | Vesuvius Challenge | [scrollprize/hecate](https://huggingface.co/scrollprize/hecate) | MIT |

![Every model on one PHerc0343 reference surface](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas/resolve/main/assets/models.gif)

![One model across the three depth windows on the same surface](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas/resolve/main/assets/depth.gif)

**Training exposure.** None of these models' published training lists names any scroll in this release, PHerc0343
included (d9v2, Reader v2 and Reader V3 list PHerc0343P, a separate object). Hecate's audited training manifest is not
published, so its list rests on its committed trainer, and one fragment id of its base model is unidentified. Each
`meta.json` records every model's exposure as the published sources state it.

## Uses and limits

Good uses: comparing ink models on identical pixels; studying how depth order and window change a model's output;
building and testing ensembles; checking a new model against seven others on the same surfaces; teaching and
visualization.

Limits:

- **No ground truth.** There are no ink labels here, so nothing in this dataset scores a model. A brighter or more
  confident map is not a more correct one. For scores against published labels, use labeled segments with a
  reverse-depth control.
- **Not a reading.** Ink maps are model output. Nothing here says that letters were found or read.
- **A screened subset.** The 25 First Letters surfaces are those a fixed rule let out, so they are not a random sample
  of each scroll.
- **Exposure unknown for most pairs.** Most models do not publish their full training lists; treat agreement between
  models with that in mind.
- **One render per surface.** Each map depends on the mesh's placement on the sheet; a different trace of the same
  sheet can change every map.

## Spent seeds and truth

What this release has used up, so that a later test on it is not called blind or held out:

- **Released model output.** Every map of the seven models on these 32 surfaces is public. A later read of these
  surfaces with these models is not blind, and a new model compared here meets surfaces whose maps from other models
  are already public.
- **Testing, PHerc0343.** The release rule was checked on the seven PHerc0343 reference surfaces: it had to flag the
  mesh behind the First Letters prize awarded on 8 October 2026, and it did.
- **Held back.** Surfaces of each scroll that the release rule did not let out are not in this release;
  `atlas.json` counts them per scroll.

No ink labels were used and no random seed defines the data. `provenance.json` holds the same list, in the format of
the [scroll dataset card standard](https://github.com/ChaseHendrick/Scrolls/blob/main/docs/standards/dataset-card.md).

## License and credit

- CT scans: [Vesuvius Challenge open data](https://scrollprize.org/data), CC BY-NC 4.0.
- Traced meshes and the face check: ketchupbyheinz (vesuvius-scroll-survey, code MIT, meshes CC BY-NC 4.0; villa
  PR #2318, MIT).
- Models: as in the table above. Ensemble recipe: Erwin Nieuwlaar, through LimeGS's ink-sdk.
- Atlas: Chase Hendrick ([ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls); the index and card
  pictures are built by `spaces/ink-atlas/dataset/` there).

The maps derive from CC BY-NC 4.0 scans and meshes, so this dataset is CC BY-NC 4.0: attribution required,
noncommercial use only.

## Citation

```bibtex
@misc{sharpmeow2026firstlettersinkatlas,
  author       = {SharpMeow},
  title        = {First Letters ink atlas},
  year         = {2026},
  howpublished = {\url{https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas}},
  note         = {Hugging Face dataset. Seven public ink models on 32 traced surfaces of the Herculaneum scrolls,
                  one 9.6 um canvas}
}
```

Please also credit the Vesuvius Challenge open data, ketchupbyheinz's meshes and the authors of each model used.

## Related

- [SharpMeow/ink-atlas](https://huggingface.co/spaces/SharpMeow/ink-atlas): the Space over this dataset.
- [SharpMeow/vesuvius-segment-atlas](https://huggingface.co/datasets/SharpMeow/vesuvius-segment-atlas): geometry
  numbers for every traced segment in the open data.
- [SharpMeow/vesuvius-snapped-labels](https://huggingface.co/datasets/SharpMeow/vesuvius-snapped-labels): published
  surface labels moved onto the papyrus face.

## Changelog

- **2026-11-26** (later): the card follows the [scroll dataset card standard 0.1](https://github.com/ChaseHendrick/Scrolls/blob/main/docs/standards/dataset-card.md): new
  `SHA256SUMS` (every file but this card) and `provenance.json`, a Spent seeds and truth section and a download check
  in Quick start. No other file was added, moved or changed.
- **2026-11-26.** Dataset Viewer tables: `metadata.jsonl` (one row per picture) and a `surfaces` config with
  previews, plus `index/*.csv`. New card with schema, decoding and loading guides, and two new pictures. No file was
  moved, renamed or changed. `load_dataset` now returns the 1,408 pictures under `surfaces/` with metadata columns
  beside the `image` column; the card pictures under `assets/` are no longer rows.
- **2026-10-27.** First release: 32 surfaces, 7 models.
