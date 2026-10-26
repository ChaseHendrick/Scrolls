---
title: Fiber Checker
emoji: 🧵
colorFrom: yellow
colorTo: green
sdk: gradio
sdk_version: 6.28.0
python_version: "3.12"
app_file: app.py
pinned: false
license: apache-2.0
short_description: Are papyrus fibers visible on a traced scroll surface?
tags:
- vesuvius-challenge
- herculaneum
- ct
- papyrus
- segmentation
- mcp-server
---

# Fiber Checker

Are papyrus fibers visible on a traced Herculaneum scroll surface? Pick any traced segment of the
[Vesuvius Challenge open data](https://scrollprize.org/data), or upload your own tifxyz mesh, and the Space renders
the CT along the surface patch by patch and gives each patch a **fiber evidence**: near 1 where long, thin, parallel
strands show, near 0.5 where the render looks no more fibrous than scrambled texture.

- **Free, no key**: the default judge is a small network that runs on this Space's CPU.
- **Claude as a second opinion**, with your own Anthropic key, used for that run only.
- **A fiber map** on the segment's own mesh grid (`fiber.tif`, the same shape as `x.tif`), a one-page `report.html`
  for prize entries, the clearest and weakest patches, and a self-check against built controls on every run.
- **Fiber or not?**: a game against the free judge, on renders of public scrolls on no prize list.
- **Compare** two traces, patch by patch.
- **API and MCP server** for scripts and agents.

The Progress Prize asks entrants to "show visually that papyrus fibers are visible on your output surface"
([scrollprize.org/prizes](https://scrollprize.org/prizes)): this is a way to measure that.

## How the free judge was tested

It was preregistered, then tested once on two public scrolls it never saw (PHerc0500P2, 120 patches; PHerc0343P, 62
patches; 2.2 um scans at level 2). It told the sheet from the gap beside it on every patch (pixel measure 0.79 and
0.76), and the sheet from a 14-pixel tile shuffle, a size never trained on, on 98% and 92% of patches (pixel measure
0.53 and 0.57). A first round failed on the tile shuffle and is kept on record. Jump hints, fiber direction and best
depth are untested ideas. A clear map says fibers show on and near the surface (each patch is rendered at the
brightest depth within 5 voxels); it does not prove the trace stayed on one sheet. Everything it shows is model output about texture: it never reads or finds text.

## Run it yourself

The command line tool is `scripts/fibercheck/fibercheck.py` in
[ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls); the weights are this Space's
`weights/fibercheck-local.pt`. See the How-to guides tab.

Scans and meshes: Vesuvius Challenge open data, CC BY-NC 4.0, read live from its bucket and never copied here. Code and
weights: Apache 2.0. Made by Chase Hendrick.
