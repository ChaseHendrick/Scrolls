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
short_description: villa lasagna fields to download, or made for any box
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

villa's **lasagna field** for Herculaneum scroll CT, two ways:

- **Ten whole scans, ready to download or stream**: PHerc0175A, PHerc0175B, PHerc0306B, PHerc0483A, PHerc0483B,
  PHerc0490A, PHerc0490B, PHerc0841, PHerc0846A and PHerc0846B, which had no lasagna field in the open data.
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
`list_scans`, `list_models`, `example_points`, `plan_field` and `make_field`. See the page's **Agents and API** tab.
A field uses the caller's ZeroGPU time.

## Credit and licences

Made by Chase Hendrick. Code: Apache 2.0 (see `LICENSE` and `NOTICE`). Model and code it runs: villa's lasagna authors,
MIT. Scans: Vesuvius Challenge open data, CC BY-NC 4.0; the fields, made from them, are CC BY-NC 4.0 too. Source and
docs: [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls), `spaces/lasagna-fields/` and
`docs/tools/lasagna-fields.md`.
