---
title: Ink Lens
emoji: 🔬
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
short_description: Control-checked ink maps of your own region, for VC3D
models:
- scrollprize/ink_9um
tags:
- vesuvius-challenge
- herculaneum
- ink-detection
- vc3d
- zerogpu
- mcp-server
---

# Ink Lens

A control-checked ink map of **your own region** of a segment, in one ZeroGPU call, written back into VC3D.

You pick a region in VC3D (or give a box). The client renders just that region, and one call to this Space runs an
openly licensed 9 um ink model over it **three times in depth** (three nearby 17-layer windows, averaged) and **in both
depth orders**: as stored and reversed, the community's reverse-depth control. The reversed map sets the threshold.
Only ink stronger than 99 % of what the control produces is kept, and the region gets a status that can fail:

| Status | Meaning |
| --- | --- |
| `ink` | at least 3 times as many papyrus pixels pass the control's 99th percentile as the control's own 1 % |
| `weak` | 1.5 to 3 times: look before trusting it |
| `none` | under 1.5 times: no ink above the control |
| `too_small` | under 100,000 papyrus pixels (about 3 mm square) |
| `unreadable` | a map is not finite, constant, or the same as its control |

The kept map then goes to the Scroll Text Reader, with the control's own kept map as its control map; when the
reader's controls pass, its letter candidates become 3D pins on the segment. The client writes VC3D's own files into
the segment folder: a transparent overlay in the Ink Detection panel (`ink-detections.json`, existing records kept),
a running mosaic of every region, and a VC3D point collection.

**Everything shown is model output, not a reading.** The rule is preregistered in
[`docs/prereg/2026-10-20-ink-lens-gate.md`](https://github.com/ChaseHendrick/Scrolls/blob/main/docs/prereg/2026-10-20-ink-lens-gate.md).

## Readers

| Reader | License | Held out | PHerc0841 crops, raw / reversed AUC (w00, ag896, ag405) |
| --- | --- | --- | --- |
| d9v2 (default), [TAUIL-Abd-Elilah](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search) | MIT | PHerc0841 | 0.899 / 0.586, 0.823 / 0.532, 0.832 / 0.657 |
| [`ink_9um`](https://huggingface.co/scrollprize/ink_9um) seed 42, Vesuvius Challenge | MIT | PHerc0841 | 0.806 / 0.536, 0.659 / 0.558, 0.784 / 0.642 |

Scores: public `docs/results.json` of ChaseHendrick/Scrolls (640 px crops, 64 px inner edge, villa's flat inference;
windows chosen with the labels, so development numbers). `both` runs the two and averages them (twice the GPU time).
Checkpoints are downloaded by URL, refused unless their SHA-256 matches, and opened with `weights_only=True`. The
models are built by villa's own flat ink inference at a pinned commit; the per-patch normalisation runs batched on the
GPU and matches villa's CPU function exactly in the tests.

## GPU time

One call asks ZeroGPU for `ceil(4 + 0.012 x patches)` seconds, at most 40. A 1024 px region (about 1 cm, three or four
lines) with three windows is 1,350 patches: it asks for 21 s and is expected to use under 10 s. ZeroGPU admits a call
only while the requested time is left in your quota and bills what is used. When it refuses, a region of up to
512 px with one window runs on the Space's CPU; larger regions belong in local mode.

## Using it

**From VC3D** (the client, `inklens.py`, from [the source](https://github.com/ChaseHendrick/Scrolls/tree/main/spaces/ink-lens)):

```bash
pip install numpy tifffile gradio_client huggingface_hub && hf auth login     # your token: your own ZeroGPU quota
python3 inklens.py run --segment SEGDIR --volume /path/to/scan.zarr --box X Y W H        # render pixels, scale 1
python3 inklens.py run --from-vc3d --volume /path/to/scan.zarr --size 1024               # VC3D with --agent-bridge
python3 inklens.py run ... --local                                                        # no account: this machine
```

Then reopen the segment in VC3D: the map is in the Ink Detection panel as "Ink Lens d9v2 ink yY xX", and the pins are
a point collection (with `--bridge` they are merged into the open ones; File > Load replaces them all).

**On this page**: pick a public sample (PHerc0841 or PHerc0139, not prize-eligible) or upload a region as `.npz`.

## For agents and scripts

Every endpoint is an API endpoint and an MCP tool (`/gradio_api/mcp/sse`; give the client your token as
`Authorization: Bearer hf_...`).

| Tool | What it does | GPU |
| --- | --- | --- |
| `lens_region` | an `.npz` region (array `volume`, uint8, layers first, about 9.6 um, 21 to 65 layers, 128 to 2048 px) in; result, maps `.npz` (forward, reverse, kept) and a preview out | yes |
| `lens_sample` | the same on a public sample crop, with the kept ink scored against the published labels | yes |
| `list_samples` | the samples and the readers, with what each reader saw in training | no |
| `estimate` | patches and requested GPU seconds for a region | no |

```python
from gradio_client import Client, handle_file
c = Client("SharpMeow/ink-lens", token="hf_...")
result, maps, preview = c.predict(handle_file("region.npz"), "d9v2", 3, api_name="/lens_region")
```

Nothing you send is kept: an upload is read into memory and deleted, and results go back in the response.

## Credits and licenses

Code: Apache 2.0 (`LICENSE`, `NOTICE`), by Chase Hendrick. Readers: d9v2 by TAUIL-Abd-Elilah (MIT), `ink_9um` by the
Vesuvius Challenge (MIT); model code: villa's vesuvius package (MIT). Scan data: CC BY-NC 4.0, Vesuvius Challenge,
*CT Scans of Herculaneum Papyri* (https://scrollprize.org/data). Source and tests:
[github.com/ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls), `spaces/ink-lens/`.
