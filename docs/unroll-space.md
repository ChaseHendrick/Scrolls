# Unroll: an interactive PHerc. 139 viewer

![Concept illustration of a papyrus roll unrolling flat along a diagonal, with a copper grid layer and a fine layer of ivory points peeling up from the flat sheet.](assets/unroll/unroll-hero.webp)

*Concept illustration: a roll unrolls flat and its layers lift apart, as Unroll stacks X-ray, surface and ink layers. No scan data. [Artwork notes](assets/README.md).*

**Link:** [huggingface.co/spaces/SharpMeow/unroll](https://huggingface.co/spaces/SharpMeow/unroll)

Unroll is a static web page, hosted as a Hugging Face Space, that rebuilds 37 traced windings of PHerc. 139 in 3D with three.js and lets a visitor unroll them in the browser. It runs on the client only; no install or account is needed.

**Version:** 1.5.0 (16 October 2026), from the Space's `version.json`; what changed in each version is in the Space's [CHANGELOG.md](https://huggingface.co/spaces/SharpMeow/unroll/blob/main/CHANGELOG.md). The page shows its version in the About panel, and `window.unroll.version()` returns it.

## What it shows

- The real winding shapes, from the public 9.362 µm surface meshes, decimated for the browser.
- An X-ray layer: CT intensity on each surface.
- A published ink layer: the Vesuvius Challenge ink detection on the 2.4 µm scan.
- A second ink layer, "ink_9um (9 µm)": ink predictions produced by Chase Hendrick, who ran the public [`scrollprize/ink_9um`](https://huggingface.co/scrollprize/ink_9um) model over these windings and processed the output for this viewer. The model itself was trained and released by the Vesuvius Challenge, not by us. It covers all 37 windings (`w023` to `w059`): `w046` to `w051` ran on Hugging Face ZeroGPU and the others on Modal, with per-run records in the Space's `data/gpu/receipts/`. It reads the 9.362 µm scan, about four times coarser than the published layer's scan, so it is shown at lower resolution on purpose, as a comparison baseline.
- Ink layers show where models detect ink; letters visible here are candidates for expert reading.
- A close-up view per winding with pan, zoom, a scale bar and a swipe comparison between Published ink (2.4 µm) and ink_9um (9 µm).

## Other scrolls

A scroll picker opens eight more scrolls from the Vesuvius Challenge open data: PHerc. 814, 9B, 343P, 841, 800, 172 (Scroll 5), 1447 and 1667 (Scroll 4). Each shows its traced segments with an X-ray layer, and the published ink detection where the open data has one. PHerc. 800 and PHerc. 1447 are shown X-ray only, with no ink layer. The ink_9um (9 µm) layer is on PHerc. 139 only.

## CT tools

Versions 1.2.0 to 1.5.0 added tools for the raw scan, documented in the Space's `docs/CT_VIEW.md`:

- X-ray window and level sliders, with auto contrast from atlas percentiles.
- A CT volume view: pick a point on the papyrus and see a cube of the raw scan around it, as a maximum intensity projection inside a slab square to the sheet.
- Labeled segments: every traced segment that passes through the cube is drawn into it and listed; click one to highlight it.
- OME-Zarr streaming of the scan from the open data bucket (`s3://vesuvius-challenge-open-data`).
- Lower resolution while the camera moves, for slower GPUs.

## Using it

- Drag to orbit, scroll or pinch to zoom.
- Scrub the timeline, or press play, to unroll from the outermost winding to the innermost.
- Click a sheet, or use the Read button, to open its close-up.
- Press `?` for keyboard shortcuts.
- A "Destroy" mode lets a visitor tear, crush, burn or soak the papyrus, rolled up or unrolled, with damage that stays as the scroll is rolled and unrolled. It is a visual toy, not a model of real damage or a real unrolling.
- A "Roll up" button (or `U`) rolls the scroll back up.

## Install app

Since version 1.1.0 Unroll is also a progressive web app. Open [sharpmeow-unroll.static.hf.space](https://sharpmeow-unroll.static.hf.space/) (the Space page shows the app in a frame, where browsers do not offer installation, so its Install app button opens this page) and press **Install app** in the View panel or in Settings, or use the browser's install icon. In Safari on iPhone and iPad: Share, then Add to Home Screen. The installed app opens in its own window; the page, three.js and the default scroll are kept on the device and work offline, and other scrolls are kept after one visit.

## Credits

- Data: Giorgio Angelotti, Stephen Parsons, Sean Johnson, Elian Rafael Dal Prà, Johannes Rudolph, Paul Tafforeau, Alessandro Mirone, Paul Henderson, Hendrik Schilling, Forrest McDonald, David Josey, Youssef Nader, C. Seth Parker, W. Brent Seales. *Vesuvius Challenge: CT Scans of Herculaneum Papyri.* Vesuvius Challenge. [Data browser for PHerc. 139](https://scrollprize.org/data_browser/PHerc0139). Licensed [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).
- PHerc. 139 is held by the Biblioteca Nazionale di Napoli and was scanned at the ESRF synchrotron.
- Ink model: [`scrollprize/ink_9um`](https://huggingface.co/scrollprize/ink_9um), trained and released by the Vesuvius Challenge; run over these windings by Chase Hendrick.
- Rendering: [three.js](https://threejs.org).
- The page code is Apache 2.0 licensed (v1.0.0); derived data in the Space is CC BY-NC 4.0. See the Space README for build scripts and per-run records.
