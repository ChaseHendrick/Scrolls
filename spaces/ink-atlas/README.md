---
title: Ink Atlas
emoji: 📜
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: 6.28.0
python_version: "3.12"
app_file: app.py
pinned: false
license: apache-2.0
short_description: Seven ink models on First Letters surfaces, side by side
datasets:
- SharpMeow/first-letters-ink-atlas
models:
- scrollprize/ink_9um
- domenicor046/reader-v2
- domenicor046/reader-v3
- Nieuwlaar/ink9um-dense-native
- scrollprize/hecate
tags:
- vesuvius-challenge
- herculaneum
- papyrus
- ink-detection
- ct
- mcp-server
---

# Ink Atlas

Seven public ink models, run on the same traced surfaces of the First Letters scrolls, side by side. Every surface
sits on one shared 9.6 µm canvas, so maps from different models line up pixel for pixel. Browse them, put a loupe on
any spot, compare every model on one box, or connect an agent.

![Every model, then the ensemble, on one PHerc0343 reference surface](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas/resolve/main/assets/models.gif)

- **Explore**: any surface, any model, both depth orders, three depth windows, the ensemble or the CT; overlay the map
  on the CT; click anywhere for a full-resolution loupe with a slider between CT and map.
- **Compare models**: all seven models, the ensemble and the CT on the same box, with each layer's numbers and its
  correlation with the ensemble.
- **The atlas**: every surface at a glance, the models and their authors, how it was made.
- **Agents and API**: an MCP server with six tools (`atlas_summary`, `list_scrolls`, `list_surfaces`,
  `surface_info`, `get_map`, `compare_models`), `gradio_client` examples and a Connect your tool panel.

The data is the public dataset [SharpMeow/first-letters-ink-atlas](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas)
(32 surfaces: 25 from 13 First Letters scrolls and 7 PHerc0343 references), read at run time.

![CT and ensemble side by side for twelve surfaces](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas/resolve/main/assets/gallery.jpg)

## Connect an agent

```bash
claude mcp add --transport http ink-atlas https://sharpmeow-ink-atlas.hf.space/gradio_api/mcp/
```

```python
from gradio_client import Client
c = Client("SharpMeow/ink-atlas")
surfaces = c.predict("PHerc0343", api_name="/list_surfaces")
grid, numbers = c.predict(surfaces[0]["id"], -1, -1, 512, "", "c+0", api_name="/compare_models")
```

## Credits and license

Scans: [Vesuvius Challenge open data](https://scrollprize.org/data), CC BY-NC 4.0. Traced meshes and the face check:
ketchupbyheinz. Models: ink_9um and Hecate (Vesuvius Challenge), Reader v2 and Reader V3 (Domenico Russo),
dense_native (Erwin Nieuwlaar), d9v2 (TAUIL-Abd-Elilah), all MIT; ensemble recipe by Erwin Nieuwlaar through LimeGS's
ink-sdk. Atlas and page: Chase Hendrick, with Ink Lens. Page code Apache 2.0
([source](https://github.com/ChaseHendrick/Scrolls/tree/main/spaces/ink-atlas)); the data is CC BY-NC 4.0.

Every map is model output, not a reading.
