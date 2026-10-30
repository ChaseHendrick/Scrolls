---
title: Lasagna Fields
emoji: 🍝
colorFrom: red
colorTo: yellow
sdk: gradio
sdk_version: 6.28.0
python_version: "3.12"
app_file: app.py
pinned: false
license: apache-2.0
suggested_hardware: zero-a10g
startup_duration_timeout: 1h
short_description: lasagna fields for 24 scrolls, or made for any box
models:
- scrollprize/lasagna
datasets:
- SharpMeow/pherc0175a-lasagna
- SharpMeow/pherc0175b-lasagna
- SharpMeow/pherc0306b-lasagna
- SharpMeow/pherc0483a-lasagna
- SharpMeow/pherc0483b-lasagna
- SharpMeow/pherc0490a-lasagna
- SharpMeow/pherc0490b-lasagna
- SharpMeow/pherc0841-lasagna
- SharpMeow/pherc0846a-lasagna
- SharpMeow/pherc0846b-lasagna
- SharpMeow/phercmanbp-lasagna
- SharpMeow/pherc0343p-lasagna
- SharpMeow/pherc0009b-lasagnetta
- SharpMeow/pherc0172-lasagnetta
- SharpMeow/pherc0500p2-lasagnetta
- SharpMeow/phercman5-lasagnetta
- SharpMeow/phercmanb-lasagnetta
- SharpMeow/pherc0009b-20250820154339-lasagnetta
- SharpMeow/pherc0009b-20260319104112-lasagnetta
- SharpMeow/pherc0814-20250804134230-lasagnetta
- SharpMeow/pherc0814-20260521123630-lasagnetta
- SharpMeow/pherc0841-20260319124803-lasagnetta
- SharpMeow/vesuvius-center-lines
tags:
- vesuvius-challenge
- herculaneum
- ct
- 3d
- lasagna
- zerogpu
- mcp-server
---

# Lasagna Fields

The **lasagna field** for Herculaneum scroll CT, two ways:

- **Every field, by scroll**: whole-scan fields for 24 scrolls in one list, each with its volume, voxel size,
  model, size and link (`fields.json`). Seven are villa's own fields in the Vesuvius Challenge open data. Twenty-two
  are public datasets made here for scans that had none: twelve with villa's lasagna model, among them ten that
  also stream from a bucket (PHerc0175A, PHerc0175B, PHerc0306B, PHerc0483A, PHerc0483B, PHerc0490A, PHerc0490B,
  PHerc0841, PHerc0846A and PHerc0846B), and ten with [Lasagnetta](https://huggingface.co/SharpMeow/lasagnetta)
  0.1.1, a faster copy of it.
- **Make a field** for any box of any public scan: pick a scan and a point, and the Space runs villa's own lasagna
  model there on ZeroGPU, checks the result against the field the open data already publishes for that scan, and
  hands you a download in villa's own layout.

A lasagna field is what villa's lasagna surface fitting and the spiral fit read: **cos** (a signal that repeats once
per papyrus layer), its gradient size **grad_mag**, and the surface normal (**nx**, **ny**). It is model output:
geometry inputs, not a reading of any text.

## Make a field: what runs

`lasagna/preprocess_cos_omezarr.py predict3d` from [ScrollPrize/villa](https://github.com/ScrollPrize/villa) at commit
`db3dbea2` (the commit the ten whole-scan fields were made with), with the
[`scrollprize/lasagna`](https://huggingface.co/scrollprize/lasagna) checkpoint at revision `de45f011` (SHA-256 checked
at start-up), both MIT. Nothing is reimplemented. The Space:

1. reads the CT around your box from the [Vesuvius Challenge open data](https://scrollprize.org/data) into villa's
   layout (the level nearest the model's 9.4 um: level 0 of 8.6 to 9.4 um scans, level 2 of 2.4 um scans), with a
   margin of one tile so the edges match a whole-scan run;
2. calls villa's `predict3d` command line in-process on the GPU (tile 192, villa's defaults otherwise);
3. reads the field back, compares it with the published field for the scan where one exists, against a control
   read a few layers away, and draws the middle slices.

Boxes are whole 256-voxel blocks of the input level (256 or 512 a side): villa writes its field in 64-voxel chunks of
the quarter grid and widens any crop to them, and it puts tiles on one lattice over the whole scan, so a box's field
is the whole-scan field there.

## For agents

The page is also an API and an MCP server (`https://sharpmeow-lasagna-fields.hf.space/gradio_api/mcp/`):
`list_fields`, `list_scans`, `list_models`, `example_points`, `plan_field` and `make_field`. See the page's **Agents and API** tab.
A field uses the caller's ZeroGPU time.

## Credit and licenses

Made by Chase Hendrick. Code: Apache 2.0 (see `LICENSE` and `NOTICE`). Model and code it runs: villa's lasagna authors,
MIT. The fields listed from the open data are villa's own; the page only links them. Scans: Vesuvius Challenge open data, CC BY-NC 4.0; the fields, made from them, are CC BY-NC 4.0 too. Source and
docs: [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls), `spaces/lasagna-fields/` and
`docs/tools/lasagna-fields.md`.
