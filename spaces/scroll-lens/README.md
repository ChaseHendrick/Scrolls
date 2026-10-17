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
People use the page; scripts and AI agents use the same things through an API and an MCP server.

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
4. **Search**: with *More like this* chosen, click a patch; *Not this* subtracts one; *Move only* just moves the
   crosshair; *Undo click* (or Ctrl or Cmd with Z) forgets the last click. *Top % shown* sets how many of the most similar patches light up. The organizers' reference (amber)
   never lights a patch below their own threshold, cosine 0.5.
5. **More**: brightness and contrast, *Center on point*, *Reset zoom*, *Use crosshair as point* (copies the
   crosshair's scan position to Your own point), *Copy link* (a link that opens this cube at this crosshair), *Draw in
   3D* (ink and surface shells and similar patches), and *Save files* (model outputs as `.npz`, the receipt `.json`,
   your concept).

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

## For scripts and agents

Everything on the page is also an endpoint. Each is a `gradio_client` call, a plain HTTP call, and an MCP tool.
Only `look` uses the GPU.

| Endpoint | Arguments | Returns | GPU |
| --- | --- | --- | --- |
| `volumes` | none | the twelve scans: id, shape, voxel size, notes, what each model saw | no |
| `gallery` | `volume` (optional) | the gallery cubes: id, scan, point, size, `npz_url`, `page_url` | no |
| `gallery_cube` | `cube_id` | the cube's receipt, with the agreement check, and its `.npz` | no |
| `random_point` | `volume`, `seed` (optional) | a point on the papyrus (Surprise me) | no |
| `look` | `vid`, `z`, `y`, `x`, `size=256`, `layers="dino,ink,surface"`, `tta`, `compact`, `allow_cpu` | the receipt, `cube_ref` and the `.npz` | yes |
| `search` | `cube` (a gallery id or a `cube_ref`), `positive_zyx`, `negative_zyx`, `positive_vector`, `negative_vector`, `reference`, `top_k=20`, `top_pct=8`, `return_concept` | the best patches with scores, and the ink-model check | no |
| `view` | `cube`, `axis` (all, z, y or x), `index` (-1 for the cube's point), `layers` (ink, surface, reference, concept, pca), the concept arguments, `top_pct`, `opacity` | a PNG drawn like the page: the three views side by side (1552 × 512), or one (512 × 512) | no |
| `reference` | none | the organizers' ink reference: 864 numbers, threshold 0.5, source | no |

**MCP.** Connect any MCP client to `https://sharpmeow-scroll-lens.hf.space/gradio_api/mcp/` (streamable HTTP; the
older SSE transport is at `/gradio_api/mcp/sse`). On this Space the tools are named `scroll_lens_volumes`,
`scroll_lens_gallery` and so on. In Claude Code:

```bash
claude mcp add --transport http scroll-lens https://sharpmeow-scroll-lens.hf.space/gradio_api/mcp/ --header "Authorization: Bearer hf_YOUR_TOKEN"
```

The token is optional. With it, `look` spends your own ZeroGPU quota (300 s a day on a free account, 40 minutes on
PRO); without it, ZeroGPU gives an anonymous caller only a few runs a day. The other tools need no quota.

**Python:**

```python
from gradio_client import Client
c = Client("SharpMeow/scroll-lens")            # token="hf_..." to spend your own ZeroGPU quota in look
cubes = c.predict(api_name="/gallery")["cubes"]
hits = c.predict(cube="paris4-train-1", reference=True, top_k=5, api_name="/search")
print(hits["agreement_with_ink_model"], hits["top_patches"][0]["center_zyx"])
png = c.predict(cube="paris4-train-1", axis="y", layers=["ink", "reference"], api_name="/view")
out = c.predict("PHerc1667", 15108, 10100, 5532, 128, "dino,ink,surface", False, True, True, api_name="/look")
same = c.predict(cube=out["cube_ref"], positive_zyx=[[15108, 10100, 5532]], api_name="/search")
```

Notes for agents:

- Coordinates are level-0 scan voxels, z y x. `look` puts the cube on the 128-voxel chunk grid around your point;
  `cube_origin_zyx` and `cube_size` in the receipt say where it landed. After `allow_cpu`, check `cube_size` and
  `note_run`: the CPU ran only the middle 128³.
- One `look` at a time per caller; a second one is refused until the first ends.
- `cube_ref` works while the Space keeps that cube in memory (its last 12). If it is gone, run `look` again or search
  the `.npz` yourself with this Space's `lens.py`.
- Returned files (the `.npz`, the PNG) are served for about an hour; save them if you need them later.
- Over MCP, a dict result arrives as Python literal text (single quotes, `True`, `None`), not JSON; `gradio_client`
  gives real JSON.
- Errors come back with their reason, for example `'X' is not one of the scans this Space may read; choose from …`.

Reading a `.npz`: `meta, arrays = lens.load_npz(path)` with this Space's
[`lens.py`](https://huggingface.co/spaces/SharpMeow/scroll-lens/blob/main/lens.py), or plain numpy:
`z = numpy.load(path); receipt = json.loads(bytes(z["receipt"]))`. `grid` is (Z/8, Y/8, X/8, 864) float16 unit
embeddings (or `grid_reduced` and `grid_basis` when compact; `lens.grid_of` rebuilds them), `ink` and `surface` are
(Z, Y, X) uint8 probabilities times 255. The scan itself is not included: `lens.read_cube(volume,
receipt["cube_origin_zyx"], receipt["cube_size"])` reads it from the bucket.

`lens.py` also runs on any computer: `python3 lens.py look PHerc0139 47316 9452 12796 --size 256` (CUDA if present).

## Credits and licenses

Code: Apache 2.0 (see `LICENSE` and `NOTICE`), by Chase Hendrick. Models and their code: MIT, by the Vesuvius
Challenge (dinovol includes parts under the DINOv2 Apache 2.0 license and the DINOv3 License Agreement). Scan data:
CC BY-NC 4.0, Giorgio Angelotti, Stephen Parsons, Sean Johnson, Elian Rafael Dal Prà, Johannes Rudolph, Paul
Tafforeau, Alessandro Mirone, Paul Henderson, Hendrik Schilling, Forrest McDonald, David Josey, Youssef Nader,
C. Seth Parker, W. Brent Seales, *Vesuvius Challenge: CT Scans of Herculaneum Papyri*. Gallery cubes are model output
derived from that data (CC BY-NC 4.0) and hold no scan voxels.

Source and tests: [github.com/ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls), `spaces/scroll-lens/`.
