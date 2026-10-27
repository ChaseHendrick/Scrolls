# crackle-check: ask whether a small patch of a segment shows ink crackle, with a reversed-layer control

A public Gradio Space that runs an open ink model on a small stack of surface layers in your order and again reversed as the control, and answers Yes, Maybe or No signal found, with the kept signal shown in amber, in the browser, from code or as an MCP tool.

| Field | Value |
| --- | --- |
| Id | `crackle-check` |
| Status | Current |
| Kind | app, agent tool |
| Area | Ink maps and models |
| Run | [huggingface.co/spaces/SharpMeow/crackle-check](https://huggingface.co/spaces/SharpMeow/crackle-check) (the page); from code with gradio_client (`Client("SharpMeow/crackle-check")`), the Gradio call API at `https://sharpmeow-crackle-check.hf.space/gradio_api/call/ENDPOINT`, or MCP at `https://sharpmeow-crackle-check.hf.space/gradio_api/mcp/sse` |
| Code | Not in this repository: the Space's own files, [huggingface.co/spaces/SharpMeow/crackle-check/tree/main](https://huggingface.co/spaces/SharpMeow/crackle-check/tree/main) (the app, the two readers' inference, the control rule and the VC3D plugin), read at Space commit 2a7d5d50. This repository holds its Connect your tool panel, `spaces/connect/crackle-check/` ([spaceconnect](spaceconnect.md)) |
| Tests | None in this repository for the Space itself. `tests/test_spaceconnect.py` checks its Connect your tool panel; `python -m kit spaceconnect run` calls its endpoints live |
| Needs | A browser, or Python with `gradio_client`, or any HTTP client, or an MCP client. A new region runs on ZeroGPU: pass your own Hugging Face token (`Client(..., token=...)`) to spend your own quota. The examples need no GPU |
| Runs on | The Space, Gradio 6.28 on ZeroGPU. The PHerc0841 w00 example answered in 0.44 s from the call API (saved maps, measured 2026-10-27, cloud container); a `/check_segment` call that read a region from the open data and ran a reader took 141 s end to end (`kit spaceconnect run`, 2026-10-24) |
| Network | The caller: `huggingface.co` and `sharpmeow-crackle-check.hf.space`. The Space: `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` for From a segment, and the readers' pinned weights |
| Writes | Nothing on the caller's machine but the files you download (the overlay PNG, the four-panel PNG, the maps `.npz`). The Space keeps no upload |
| Go-ahead | Not needed to use it. Changing or redeploying the Space follows hard rule 8 |
| Released | Space [`SharpMeow/crackle-check`](https://huggingface.co/spaces/SharpMeow/crackle-check), public since 2026-10-23, version 0.4.0 (the `tool` field of every result, read 2026-10-27); README "Released tools" entry `crackle-check` since 2026-10-27 |
| License | Code Apache 2.0 ([LICENSE](https://huggingface.co/spaces/SharpMeow/crackle-check/blob/main/LICENSE), with NOTICE); the readers MIT; the scans CC BY-NC 4.0 (Vesuvius Challenge open data) |
| Checked | 2026-10-27 against commit `45836d9` |

## What it does

Ink on some Herculaneum scrolls shows in the CT as crackle: a fine texture on the papyrus surface where the ink sits. A text finder looking at one spot of a traced segment wants a quick answer to "is there ink-like crackle here?" before rendering or reading anything.

Crackle Check takes a small region of a segment as a stack of surface layers (17 to 65 layers, about 320 to 1024 px across at about 9 µm), or reads that stack itself from the open data when you name a segment and a spot. An openly licensed ink model reads the layers in your order and again in reverse order. The reversed run is the control: it shows how much the model fires on the same pixels when the depth order makes no physical sense. The answer is Yes when the signal clearly beats the control, Maybe when it beats it a little, and No signal found otherwise, with the kept signal in amber on a before and after slider, both maps on one scale, and every number in the result.

On the public PHerc0841 w00 example the default reader answers Yes, with 18.2 times as many papyrus pixels above the control's threshold as the control itself.

What it does not do: it does not read letters and its answer is not a reading. Every map and answer is model output. No signal found is not proof that there is no ink: many scrolls show little or no crackle, and ink can be there without it. It refuses a single image or screenshot, since the readers read 17 layers at once.

## When to use it

- To check one spot of a traced segment for ink-like signal before a full render, from the page, a script or an agent.
- To get a control-checked answer from a public reader without installing anything.
- From VC3D: the Space ships a plugin manifest and a client that check a region of the active segment from VC3D's Plugins menu.

Do not use it:

- To score an ink model against labels: use [auc](auc.md) or [Ink Lens](ink-lens.md), which compare models on labeled crops.
- To map a whole segment: use [Ink Lens](ink-lens.md) or villa's own inference.
- On scans far from 8 to 10 µm per pixel without giving the pixel size.

## Quick start

```bash
URL=https://sharpmeow-crackle-check.hf.space
EVENT=$(curl -s -X POST $URL/gradio_api/call/check_example -H 'Content-Type: application/json' \
  -d '{"data": ["0841-w00", "readerv3"]}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["event_id"])')
curl -sN $URL/gradio_api/call/check_example/$EVENT
```

Printed on 2026-10-27 (excerpt):

```
event: complete
data: ["## Yes\n\nThe model finds an ink signal clearly stronger than its control: at least 3 times as many pixels pass the control's threshold as the control itself.\n\nSignal strength: 18.2 times the control (3 or more is yes, 1.5 to 3 maybe), on 387,710 papyrus pixels. ...
```

It worked when the stream ends with `event: complete` and the second item of `data` has `"answer"`. `0841-w00` is one of the public examples (`/list_readers` lists them); `readerv3` is the default reader.

## Checks and controls

Every check runs its own control: the same reader on the same layers in reverse order. T is the 99th percentile of the reversed map on papyrus, so 1 % of the control's papyrus pixels pass it by construction. The answer is Yes when at least 3 times as many papyrus pixels pass T in your order as the control's 1 %, and Maybe from 1.5 times. The rule is `ink-lens-gate-v1`, frozen before any map existed ([`docs/prereg/2026-10-20-ink-lens-gate.md`](../prereg/2026-10-20-ink-lens-gate.md)); its preregistered checks on the three public PHerc0841 crops, including the swapped-maps check that must fail, are on the [Ink Lens](ink-lens.md) page.

The examples answer from maps saved from a ZeroGPU run of the same models and crop, checked by SHA-256, and say so in their notes; your own layers and From a segment always run live.

Limits: tested on a few public PHerc0841 crops only; other scrolls are untested.

Claim label: Model output, for every answer, map and signal strength.

## Commands and options

The Space's API endpoints, each also an MCP tool (read from `https://sharpmeow-crackle-check.hf.space/gradio_api/info`, 2026-10-27):

| Endpoint | Arguments (default) | What it does |
| --- | --- | --- |
| `/check` | `path` (a ZIP of layer images `00.tif`, `01.tif`, ... or a multi-page TIFF), `um_per_px` (none), `flip` (false), `reader` (`readerv3`) | Checks your own layer stack |
| `/check_example` | `sample_id` (`0841-w00`), `reader` (`readerv3`) | Answers a public example from saved maps |
| `/check_segment` | `segment` (`SCROLL/segments/SEGMENT`), `volume` (empty: the first), `x`, `y` (the spot, in the surface volume's pixels), `size` (384), `reader` (`readerv3`) | Reads that region's layers from the open data and checks them |
| `/list_volumes` | `segment` | The segment's surface volumes |
| `/list_readers` | none | The readers, their licences, sources and SHA-256 pins, the default, the examples, the tool version and the rule |

Readers: `readerv3` (Reader V3, Domenico Russo, MIT, the default), `d9v2` (TAUIL-Abd-Elilah, MIT, a fine-tune of the Vesuvius Challenge's `ink_9um`), or both averaged.

## Python API

Not applicable: the Space is called through gradio_client, the call API or MCP; see Commands and options.

## Inputs

- **Your layers:** a ZIP of layer images (`00.tif`, `01.tif`, ...) or a multi-page TIFF of one region, 17 to 65 layers, about 320 to 1024 px across, at about 9 µm per pixel (give `um_per_px` otherwise). Layer order is your order; set `flip` if your stack runs the other way.
- **From a segment:** a released segment of the Vesuvius Challenge open data (`SCROLL/segments/SEGMENT`), a surface volume (from `/list_volumes`) and a spot in its pixels.
- **Examples:** `0841-w00`, `0841-ag896`, `0841-ag405`, public labeled PHerc0841 crops.

## Outputs

Each check returns four items: a Markdown answer, a result object, the overlay image and the maps (`.npz`, float maps in both orders and the kept map).

| Field | Type | Meaning |
| --- | --- | --- |
| `tool` | string | The Space's version, such as `Crackle Check 0.4.0` |
| `answer` | string | `Yes`, `Maybe`, `No signal found`, `Too small` or `Could not judge` |
| `gate.rule` | string | `ink-lens-gate-v1` |
| `gate.threshold` | number | T, the 99th percentile of the reversed map on papyrus |
| `gate.forward_above`, `gate.control_above` | number | Share of papyrus pixels above T in your order and in the control |
| `gate.excess` | number | `forward_above` over `control_above` (3 or more is Yes, 1.5 to 3 Maybe) |
| `gate.papyrus_px`, `gate.region_px` | int | Papyrus pixels judged, pixels in the region |
| `readers`, `windows`, `shape` | list, int, list | The readers used, the depth windows, and the stack's shape (layers, height, width) |
| `device`, `seconds`, `notes` | string, number, list | Where it ran (live or saved maps), how long, and what was read |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| A single image is refused, with the reason | The readers read 17 layers at once | Upload a layer stack, or use From a segment |
| `Too small` | The region has too few layers or pixels | Give 17 to 65 layers, at least about 320 px across |
| `Could not judge` | Too little papyrus in the region, or it could not be read | Move the spot onto papyrus |
| A ZeroGPU quota error | A new region runs on ZeroGPU | Pass your own Hugging Face token, or use an example |

## How it works

1. The layers are read (uploaded, or from the open data for From a segment) and checked for size.
2. The chosen reader runs on the stack in your order and in reverse order; d9v2 runs on Ink Lens's engine, Reader V3 on its author's inference, reproduced patch for patch.
3. T is set from the reversed map on papyrus, and the share of papyrus pixels above T in each order gives the excess and the answer (`ink-lens-gate-v1`).
4. The page draws the kept signal in amber over the middle layer, both maps on one scale, and where the two orders' scores fall.

## Cost and time

Free to call. The examples cost no GPU time; a new region uses ZeroGPU time, the caller's own when a token is passed. See Runs on for the measured times.

## For agents

- **Command:** `Client("SharpMeow/crackle-check").predict(segment="PHerc0841/segments/20260220213127-w00", volume="", x=3008, y=2944, size=384, reader="readerv3", api_name="/check_segment")`; or add the MCP server `https://sharpmeow-crackle-check.hf.space/gradio_api/mcp/sse`.
- **Parse:** the second returned item: `answer`, and `gate.excess`, `gate.forward_above`, `gate.control_above`.
- **Rerun:** safe; the Space keeps nothing. A live rerun spends ZeroGPU time again.
- **Success:** a result with `answer` and `gate.rule` `ink-lens-gate-v1`.
- **Not a pass:** an answer from saved maps (`device` names the saved run) says nothing about a new region; `No signal found` is not proof of no ink; untested off PHerc0841.
- **Go-ahead:** Nothing to call it. Changing or redeploying the Space follows hard rule 8.
- **Never:** call an answer or map a reading; upload private or target-scroll data to it.

## Tests

None in this repository for the Space's code. `python -m unittest tests.test_spaceconnect` checks its Connect your tool panel, and `python -m kit spaceconnect run` calls `/check_example`, `/check_segment` and `/list_readers` live (all passed on 2026-10-24).

## History

- 2026-10-27: release entry `crackle-check` and this page, branched from `main` at `45836d9`, describing the public Space at Space commit 2a7d5d50 (version 0.4.0).
- 2026-10-24: Connect your tool panel, `spaces/connect/crackle-check/` ([PR #170](https://github.com/ChaseHendrick/Scrolls/pull/170)).

## Related

- [Ink Lens](ink-lens.md): the same control rule, every open ink model side by side, and maps of a whole region for VC3D.
- [spaceconnect](spaceconnect.md): the Connect your tool panel this Space carries.
- [`docs/prereg/2026-10-20-ink-lens-gate.md`](../prereg/2026-10-20-ink-lens-gate.md): the frozen rule.
