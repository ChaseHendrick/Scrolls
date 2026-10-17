---
title: Scroll Lens
emoji: 🔎
colorFrom: yellow
colorTo: gray
sdk: gradio
sdk_version: 6.28.0
python_version: "3.12"
app_file: app.py
pinned: false
license: apache-2.0
suggested_hardware: zero-a10g
startup_duration_timeout: 1h
short_description: See scroll CT through 3D DINO, ink and surface models
models:
- scrollprize/dinovol_v2_ps8_with_paris4_352500
- scrollprize/ink_3d_dino_guided
- scrollprize/surface_recto_3dunet
tags:
- vesuvius-challenge
- herculaneum
- ct
- 3d
- dino
- self-supervised
- zerogpu
---

# Scroll Lens

Look inside a carbonized Herculaneum scroll with the Vesuvius Challenge's newest 3D models, and click to search.

Scroll Lens reads a small cube (128³ or 256³ voxels, 0.3 or 0.6 mm a side) of a public X-ray CT scan straight from the
[Vesuvius Challenge open data](https://scrollprize.org/data) and runs three models on it, all released by the
Vesuvius Challenge team with their PHerc. Paris 4 work ([Angelotti et al. 2026](https://arxiv.org/abs/2606.29085)):

| Layer | Model | What it shows |
| --- | --- | --- |
| 3D DINO embeddings | [`scrollprize/dinovol_v2_ps8_with_paris4_352500`](https://huggingface.co/scrollprize/dinovol_v2_ps8_with_paris4_352500) | A self-supervised 3D ViT: 864 numbers for every 8 × 8 × 8 voxel patch. Alike patches get alike numbers. Shown as *DINO colours* (the three main directions as red, green, blue) and used by click search. |
| 3D ink | [`scrollprize/ink_3d_dino_guided`](https://huggingface.co/scrollprize/ink_3d_dino_guided) | Ink voxels marked directly in the scan, with no flattened surface. |
| Recto surface | [`scrollprize/surface_recto_3dunet`](https://huggingface.co/scrollprize/surface_recto_3dunet) | The written side of each papyrus sheet. |

**Click to search.** Click a patch with *More like this* and every patch whose embedding is close to it lights up;
*Not this* subtracts a patch. This is the organisers' own recipe: their ink reference (shown in amber) is the mean
embedding of 256 expert clicks on ink. Your concept follows you to other cubes and scans, and downloads as
`concept.npy`, so you can click ink in one scroll and look for its like in another.

**Everything shown is model output, not a reading.** A cube is smaller than one letter.

## Using it

1. **Gallery** (no GPU): pick a ready-made cube. The page opens on the first one.
2. **Your own point**: pick a scan, type a point (level-0 voxels, z y x) or press *Surprise me*, then *Run the
   models*. A 256³ cube asks ZeroGPU for about half a minute. When your daily ZeroGPU time is used up, or no GPU is
   free, the models run on the Space's CPU on the middle 128³ of the cube instead (slower, about a minute).
3. **Look**: move the z, y and x sliders; tick the layers. White dotted lines show where the other views cut.
4. **Search**: choose a click mode and click a view. *Top % shown* sets how many of the most similar patches light up.
5. **3D view**: ink and surface as shells, similar patches as points, rotatable.
6. **Save files**: the model outputs (`.npz`), a receipt (`.json`) and, after clicks, `concept.npy` and `clicks.json`.

Links: `?v=PHerc0139&z=…&y=…&x=…&size=256` opens the page on a point (it runs only when you press the button);
`?cube=ID` opens a gallery cube.

## The scans

Only these twelve scans, all at 2.2 to 2.4 µm, the scale the models were made for. None is on the First Letters or
Grand Prize eligible lists. PHerc. Paris 4's title is an open prize, so Scroll Lens itself only ever picks the eight
Paris 4 points the organisers listed for training the 3D ink model; you can type any point.

| Id | Scroll | 3D DINO | 3D ink | Recto surface |
| --- | --- | --- | --- | --- |
| PHercParis4 | PHerc. Paris 4 | trained on this scan | made for this scroll | not trained on it |
| PHerc0139 | PHerc. 139 | trained on this scan | its teacher was | trained on it |
| PHerc1667 | PHerc. 1667 (Scroll 4) | **never saw it** | its teacher was | trained on it |
| PHerc0500P2 | PHerc. 500P2 | trained on this scan | its teacher was | trained on it |
| PHerc0343P | PHerc. 343P | trained on this scan | not trained on it | trained on it |
| PHerc0814 | PHerc. 814 | trained on this scan | its teacher was | not trained on it |
| PHerc0009B | PHerc. 9B | trained on this scan | its teacher was | not trained on it |
| PHercMAN5 | PHerc. MAN 5 | trained on this scan | its teacher was | not trained on it |
| PHerc1299 | PHerc. 1299 | trained on this scan | not trained on it | not trained on it |
| PHerc0332 | PHerc. 332 | trained on this scan | not trained on it | not trained on it |
| PHerc1451 | PHerc. 1451 | trained on this scan | not trained on it | not trained on it |
| PHercMANB | PHerc. MAN B | trained on this scan | not trained on it | trained on it (MAN Bp) |

"Its teacher was": the 3D ink model was distilled from a stage-1 teacher trained on that scroll's ink labels. From
the model cards and the checkpoints' own training configs, read 16 October 2026. The page shows this per cube.

## Checks

- Each cube shows how well the organisers' ink reference picks out the patches the 3D ink model marks as ink (AUC),
  beside a control that must fail: the same ink mask moved by half the cube, which should sit near 0.5. Your own
  concept gets the same pair. This is agreement between two models, not ground truth.
- The 3D DINO code is the organisers' own (dinovol, at a pinned commit) and reproduces their napari inspector's patch
  embeddings to a cosine of 0.9999 on a Paris 4 cube.
- Weights are downloaded at pinned revisions and refused unless their SHA-256 matches; the model code is downloaded
  at pinned commits. The receipt records all of it, plus the device, timings and the cube's place in the scan.

## For scripts and agents

The `look` endpoint returns the same `.npz` for any listed point:

```python
from gradio_client import Client
c = Client("SharpMeow/scroll-lens", token="hf_...")   # your token: GPU time counts against your quota
path = c.predict("PHerc1667", 15108, 10100, 5532,     # scan, z, y, x
                 256, "dino,ink,surface",            # cube side, models
                 False, False, False,                # mirror averaging, compact, allow the CPU fallback
                 api_name="/look")
```

Read it with `lens.load_npz(path)` from this Space's `lens.py`: `grid` is (Z/8, Y/8, X/8, 864) float16 unit
embeddings (or `grid_reduced` and `grid_basis` when compact), `ink` and `surface` are (Z, Y, X) uint8 probabilities
times 255, and `receipt` is the JSON receipt. The scan itself is not included; read it from the bucket with
`lens.read_cube(volume, receipt["cube_origin_zyx"], receipt["cube_size"])`.

`lens.py` also runs on any computer: `python3 lens.py look PHerc0139 47316 9452 12796 --size 256` (CUDA if present).

## Credits and licences

Code: Apache 2.0 (see `LICENSE` and `NOTICE`), by Chase Hendrick. Models and their code: MIT, by the Vesuvius
Challenge (dinovol includes parts under the DINOv2 Apache 2.0 licence and the DINOv3 License Agreement). Scan data:
CC BY-NC 4.0, Giorgio Angelotti, Stephen Parsons, Sean Johnson, Elian Rafael Dal Prà, Johannes Rudolph, Paul
Tafforeau, Alessandro Mirone, Paul Henderson, Hendrik Schilling, Forrest McDonald, David Josey, Youssef Nader,
C. Seth Parker, W. Brent Seales, *Vesuvius Challenge: CT Scans of Herculaneum Papyri*. Gallery cubes are model output
derived from that data (CC BY-NC 4.0) and hold no scan voxels.

Source and tests: [github.com/ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls), `spaces/scroll-lens/`.
