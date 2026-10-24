---
title: Segment Lens
emoji: 🧭
colorFrom: gray
colorTo: blue
sdk: gradio
sdk_version: 6.28.0
python_version: "3.12"
app_file: app.py
pinned: false
license: apache-2.0
short_description: Every published Herculaneum segment, measured, in 3D
tags:
  - vesuvius-challenge
  - herculaneum
  - tifxyz
  - segmentation
  - three.js
datasets:
  - SharpMeow/vesuvius-segment-atlas
---

# Segment Lens

The Vesuvius Challenge open data publishes hundreds of traced segments: pieces of the rolled papyrus surface,
each a grid of 3D points (a tifxyz mesh). Segment Lens shows them as surfaces you can turn, with the grid's
problems painted on: **holes** inside the sheet (blue rims), **folds** where the surface turns back on itself
(red) and **over-stretched** grid edges (orange). Beside each one are the numbers from the
[Segment Atlas](https://huggingface.co/datasets/SharpMeow/vesuvius-segment-atlas): area in cm2, filled share,
how close the grid is to isometric, and the area of each problem in mm2.

- **3D** is for scans on none of the prize lists (the public media rule of
  [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls/blob/main/docs/media/README.md)).
  Scrolls on a prize list appear in the table with their numbers only.
- **Table** lists every mesh in the atlas, sortable, with a link to its folder on the open-data bucket and the
  `kit tifxyz check` command that reproduces its numbers on your own machine.

What it shows is geometry only: no CT, no ink, and nothing here judges whether a segment stays on one sheet of
papyrus. The previews keep every k-th grid node (at most 256 per side), so a small flag can look larger than it is;
the numbers come from the full grid.

## For agents and scripts

The same atlas is an API and an MCP server at [/agents/](https://sharpmeow-segment-lens.hf.space/agents/):
`list_scrolls`, `list_segments`, `get_segment` and `segment_picture` (a picture of one mesh with its flags painted
on). MCP: add `https://sharpmeow-segment-lens.hf.space/agents/gradio_api/mcp/`. Python:

```python
from gradio_client import Client
c = Client("https://sharpmeow-segment-lens.hf.space/agents/")
top = c.predict("PHerc0139", "area_cm2", 5, True, api_name="/list_segments")
seg = c.predict(top["segments"][0]["id"], api_name="/get_segment")
picture, info = c.predict(seg["id"], "3d", 30, 20, api_name="/segment_picture")
```

Data: Vesuvius Challenge open data, CC BY-NC 4.0, via the Segment Atlas (same license). Code: Apache 2.0,
by Chase Hendrick. three.js is MIT.
