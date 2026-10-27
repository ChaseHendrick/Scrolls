---
title: AFV Fibers
emoji: 🧶
colorFrom: yellow
colorTo: blue
sdk: gradio
sdk_version: 6.28.0
python_version: "3.12"
app_file: app.py
pinned: false
license: apache-2.0
short_description: Papyrus fiber curves for six whole scans, plus a catalog
models:
- Qualzz20/afv_fiber_9um_v2
datasets:
- SharpMeow/pherc0009b-afv-fibers
- SharpMeow/pherc0139-afv-fibers
- SharpMeow/pherc0332-afv-fibers
- SharpMeow/pherc0814-afv-fibers
- SharpMeow/pherc0841-afv-fibers
- SharpMeow/pherc1667-afv-fibers
tags:
- vesuvius-challenge
- herculaneum
- ct
- papyrus
- fibers
- mcp-server
---

# AFV Fibers

Papyrus fiber curves for **six whole Herculaneum scans** (PHerc0009B, PHerc0139, PHerc0332 Scroll 3, PHerc0814,
PHerc0841 and PHerc1667 Scroll 4), made with **[Qual](https://huggingface.co/Qualzz20)'s AFV V2 fiber model and his
AVF_SPLINE_GENERATOR**, the same recipe as his own published sets. Every horizontal and vertical fiber the model sees,
traced into a curve, in the `.afv` format VC3D reads.

- **Six scans**: each scan's dataset, with pictures, counts and how it was made and checked.
- **Explore a box**: pick a scan and a point; see the CT there with the fibers drawn over it, every fiber of the box in
  3D, and download the box as its own small `.afv`.
- **Catalog**: every public fiber set we know of, ours and other people's (Qual's own sets, the open data's fiber
  fields, the annotators' hand-traced fibers), linked where its makers host it.
- **API and MCP server** for scripts and agents.

## Credit

The fiber model ([Qualzz20/afv_fiber_9um_v2](https://huggingface.co/Qualzz20/afv_fiber_9um_v2)) and the spline
generator ([AVF_SPLINE_GENERATOR](https://github.com/Qualzz/AVF_SPLINE_GENERATOR)) are Qual's work, Apache 2.0, and
so is the `.afv` format. This Space and the six datasets are runs of them on more scans, with the compute, stitching
and checks described on each dataset card.

Scans: Vesuvius Challenge open data, CC BY-NC 4.0, read live from its bucket and never copied here. Fiber files:
model output derived from those scans, CC BY-NC 4.0. Code: Apache 2.0. Made by Chase Hendrick.
