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
- mcp-server
---

# Scroll Lens

Look inside a carbonized Herculaneum scroll with the Vesuvius Challenge's newest 3D models, and click to search.
People use the page, flat or in 3D; scripts and AI agents use the same cubes through tools that are an API and an MCP server.

Scroll Lens reads a small cube (128³ or 256³ voxels, 0.3 or 0.6 mm a side) of a public X-ray CT scan straight from the
[Vesuvius Challenge open data](https://scrollprize.org/data) and runs three models on it, all released by the
Vesuvius Challenge team with their PHerc. Paris 4 work ([Angelotti et al. 2026](https://arxiv.org/abs/2606.29085)):

| Layer | Model | What it shows |
| --- | --- | --- |
| 3D DINO embeddings | [`scrollprize/dinovol_v2_ps8_with_paris4_352500`](https://huggingface.co/scrollprize/dinovol_v2_ps8_with_paris4_352500) | A self-supervised 3D ViT: 864 numbers for every 8 × 8 × 8 voxel patch. Alike patches get alike numbers. Shown as *DINO colors* (the three main directions as red, green, blue) and used by click search. |
| 3D ink | [`scrollprize/ink_3d_dino_guided`](https://huggingface.co/scrollprize/ink_3d_dino_guided) | Ink voxels marked directly in the scan, with no flattened surface. |
| Recto surface | [`scrollprize/surface_recto_3dunet`](https://huggingface.co/scrollprize/surface_recto_3dunet) | The written side of each papyrus sheet. |

**Click to search.** Click a patch with *More like this* and every patch whose embedding is close to it lights up;
*Not this* subtracts a patch. This is the organizers' own recipe: their ink reference (shown in amber) is the mean
embedding of 256 expert clicks on ink. Your concept follows you to other cubes and scans, and downloads as
`concept.npy` (and `concept_not.npy` for the Not this clicks), so you can click ink in one scroll and look for its like
in another.

**Everything shown is model output, not a reading.** A cube is smaller than one letter.

## Using it

1. **Gallery** (no GPU): 99 ready-made cubes. Pick one and it opens; *Previous*, *Next* and *Random* step through
   them, and you can type in the list to search it. The page opens on the first one.
2. **Your own point**: pick a scan, type a point (level-0 voxels, z y x) or press *Surprise me*, then *Run the
   models*. A 256³ cube uses about 5 seconds of your daily ZeroGPU time (a call takes 7 to 12 s), a 128³ cube under a
   second. ZeroGPU starts a call only while about 21 s (256³) or 11 s (128³) of your quota is left. When it refuses,
   or no GPU is free, the models run on the Space's CPU on the middle 128³ of the cube instead (about 10 seconds, one
   such run at a time).
3. **Look**: the three views are drawn in your browser, so everything answers at once. Drag a slider, or drag inside a
   view to move the crosshair: the other views follow as you move. The wheel or the arrow keys step one slice (Shift:
   8). Ctrl or Cmd with the wheel, or a pinch, zooms; right-drag or Shift-drag pans; double-click resets. The line
   under the views reads out what is under the pointer: place in the cube and the scan, CT value, ink and surface
   probability, and similarity.
4. **Search**: a click only moves the crosshair at first (*Move only*). Choose *More like this* and click a patch;
   *Not this* subtracts one; *Undo click* (or Ctrl or Cmd with Z) forgets the last click. *Top % shown* sets how many of the most similar patches light up. The organizers' reference (amber)
   never lights a patch below their own threshold, cosine 0.5.
5. **3D view**: turns the three views into one 3D space of the cube, as in Unroll: the three slices as planes that
   move as you drag the sliders, ink and surface as points, and the patches like your concept or the organizers'
   reference glowing. Drag to rotate, wheel to zoom, right-drag to pan, *Spin* to turn it slowly; click a slice to
   search there.
6. **More**: brightness and contrast, *Center on point*, *Reset zoom*, *Use crosshair as point* (copies the
   crosshair's scan position to Your own point), *Copy link* (a link that opens this cube at this crosshair), and
   *Save files* (model outputs as `.npz`, the receipt `.json`, your concept).

Links: `?cube=ID` opens a gallery cube; `?v=PHerc0139&z=…&y=…&x=…&size=256` fills in Your own point (press Run the
models); `&s=z,y,x` puts the crosshair at that voxel of the cube.

## The scans

Only these twelve scans, all at 2.2 to 2.4 µm, the scale the models work at. None is on the First Letters or Grand
Prize eligible lists. PHerc. Paris 4's title is an open prize, so Scroll Lens itself only ever picks the eight Paris 4
points the organizers listed for training the 3D ink model; you can type any point.

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

- Each cube shows how well the organizers' ink reference picks out the patches the 3D ink model marks as ink (AUC),
  beside controls that must fail: the same ink mask moved away from its place. Papyrus is layered, so one move can
  line the layers up again; the control is therefore taken over 16 fixed moves, and the AUC means something only
  above their range (`auc_control_p95`). Your own concept gets the same check. This is agreement between two models,
  not ground truth.
- The 3D DINO code is the organizers' own (dinovol, at a pinned commit) and reproduces their napari inspector's patch
  embeddings to a cosine of 0.9999 on a Paris 4 cube.
- Weights are downloaded at pinned revisions and refused unless their SHA-256 matches; the model code is downloaded
  at pinned commits. The receipt records all of it, plus the device, timings and the cube's place in the scan.

## For agents and scripts

Everything a person can do on the page, an agent can do too: each tool below is both an API endpoint
(`gradio_client`) and an MCP tool. Every answer carries `open_in_browser`, a link that opens the same cube on the page,
so an agent can hand its result to a person.

| Tool | What it does | GPU |
| --- | --- | --- |
| `list_scans` | the twelve scans, their sizes, what each model saw of them in training, the Paris 4 training points | no |
| `list_gallery` | the ready-made cubes, with ids | no |
| `random_point` | a point on the papyrus of a scan, fixed by a seed | no |
| `inspect_cube` | three slice views with chosen overlays (one PNG) and the cube's receipt, checks and layer fractions | gallery: no |
| `search_cube` | the patches most like example points, a `concept.npy`, or the organizers' ink reference; with the AUC against the 3D ink model and its control, an image through the best match, and the concept as `concept.npy` | gallery: no |
| `download_cube` | the model outputs as a `.npz` and the receipt | gallery: no |
| `look` | the `.npz` for any point, for batch scripts (`tools/build_gallery.py` uses it) | yes |

A cube is named by a gallery `cube_id`, or by `scan` and a point `z`, `y`, `x` (level-0 voxels) with `size` 128 or
256. Points for `search_cube` are scan coordinates inside the cube, written `"z,y,x; z,y,x"`. A point outside the
listed scans, outside the cube, or not three whole numbers is refused with a message saying why.

**MCP.** Add `https://sharpmeow-scroll-lens.hf.space/gradio_api/mcp/` to an MCP client (Claude, Cursor and others).
Calls on a new point use the caller's ZeroGPU time, so give the client a Hugging Face token
(`Authorization: Bearer hf_...`); gallery cubes need none.

**Python.**

```python
from gradio_client import Client
c = Client("SharpMeow/scroll-lens", token="hf_...")   # your token: GPU time counts against your quota
cubes = c.predict(api_name="/list_gallery")["cubes"]
image, info = c.predict(cubes[0]["id"], "", 0, 0, 0, 256, "ink,reference", api_name="/inspect_cube")
image, hits, concept = c.predict("", "PHerc1667", 15108, 10100, 5532, 256,   # cube_id, scan, z, y, x, size
                                 "15108,10100,5532", "", None, 10,           # positive, negative, concept, top_k
                                 api_name="/search_cube")
path = c.predict("PHerc1667", 15108, 10100, 5532,     # look: scan, z, y, x
                 256, "dino,ink,surface",            # cube side, models
                 False, False, False,                # mirror averaging, compact, allow the CPU fallback
                 api_name="/look")
```

Read a `.npz` with `lens.load_npz(path)` from this Space's `lens.py`: `grid` is (Z/8, Y/8, X/8, 864) float16 unit
embeddings (or `grid_reduced` and `grid_basis` when compact), `ink` and `surface` are (Z, Y, X) uint8 probabilities
times 255, and `receipt` is the JSON receipt. The scan itself is not included; read it from the bucket with
`lens.read_cube(volume, receipt["cube_origin_zyx"], receipt["cube_size"])`.

`lens.py` also runs on any computer: `python3 lens.py look PHerc0139 47316 9452 12796 --size 256` (CUDA if present).

## Credits and licenses

Code: Apache 2.0 (see `LICENSE` and `NOTICE`), by Chase Hendrick. Models and their code: MIT, by the Vesuvius
Challenge (dinovol includes parts under the DINOv2 Apache 2.0 license and the DINOv3 License Agreement). Scan data:
CC BY-NC 4.0, Giorgio Angelotti, Stephen Parsons, Sean Johnson, Elian Rafael Dal Prà, Johannes Rudolph, Paul
Tafforeau, Alessandro Mirone, Paul Henderson, Hendrik Schilling, Forrest McDonald, David Josey, Youssef Nader,
C. Seth Parker, W. Brent Seales, *Vesuvius Challenge: CT Scans of Herculaneum Papyri*. Gallery cubes are model output
derived from that data (CC BY-NC 4.0) and hold no scan voxels.

Source and tests: [github.com/ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls), `spaces/scroll-lens/`.
