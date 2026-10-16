# Unroll: an interactive PHerc. 139 viewer

**Link:** [huggingface.co/spaces/SharpMeow/unroll](https://huggingface.co/spaces/SharpMeow/unroll)

Unroll is a static web page, hosted as a Hugging Face Space, that rebuilds 37 traced windings of PHerc. 139 in 3D with three.js and lets a visitor unroll them in the browser. It runs on the client only; no install or account is needed.

## What it shows

- The real winding shapes, from the public 9.362 µm surface meshes, decimated for the browser.
- An X-ray layer: CT intensity on each surface.
- A published ink layer: the Vesuvius Challenge ink detection on the 2.4 µm scan.
- A second ink layer, "ink_9um, run by Chase (9 µm)": ink predictions produced by Chase Hendrick, who ran the public [`scrollprize/ink_9um`](https://huggingface.co/scrollprize/ink_9um) model over these windings and processed the output for this viewer. The model itself was trained and released by the Vesuvius Challenge, not by us. Coverage is a work in progress and grows as more windings are run; so far it covers windings `w046` to `w051`, run on Hugging Face ZeroGPU. It reads the 9.362 µm scan, about four times coarser than the published layer's scan, so it is shown at lower resolution on purpose, as a comparison baseline.
- A close-up view per winding with pan, zoom, a scale bar and a swipe comparison between Published ink (2.4 µm) and ink_9um run (9 µm).

## Using it

- Drag to orbit, scroll or pinch to zoom.
- Scrub the timeline, or press play, to unroll from the outermost winding to the innermost.
- Click a sheet, or use the Read button, to open its close-up.
- Press `?` for keyboard shortcuts.
- A "Destroy" mode lets a visitor tear, crush, burn or soak the papyrus, rolled up or unrolled, with damage that stays as the scroll is rolled and unrolled. It is a visual toy, not a model of real damage or a real unrolling.
- A "Roll up" button (or `U`) rolls the scroll back up.

## Credits

- Data: Giorgio Angelotti, Stephen Parsons, Sean Johnson, Elian Rafael Dal Prà, Johannes Rudolph, Paul Tafforeau, Alessandro Mirone, Paul Henderson, Hendrik Schilling, Forrest McDonald, David Josey, Youssef Nader, C. Seth Parker, W. Brent Seales. *Vesuvius Challenge: CT Scans of Herculaneum Papyri.* Vesuvius Challenge. [Data browser for PHerc. 139](https://scrollprize.org/data_browser/PHerc0139). Licensed [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).
- PHerc. 139 is held by the Biblioteca Nazionale di Napoli and was scanned at the ESRF synchrotron.
- Ink model: [`scrollprize/ink_9um`](https://huggingface.co/scrollprize/ink_9um), trained and released by the Vesuvius Challenge; run over these windings by Chase Hendrick.
- Rendering: [three.js](https://threejs.org).
- The page code is MIT licensed; derived data in the Space is CC BY-NC 4.0. See the Space README for build scripts and per-run records.
