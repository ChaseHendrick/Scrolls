# umbilici: view every public center line of the 22 prize scans over live X-ray CT

A static Hugging Face Space that draws every public center line (umbilicus) for the 22 prize-eligible Herculaneum scans in 3D, over CT that the visitor's browser streams from the open-data bucket, with villa's lasagna field for PHerc0175A.

| Field | Value |
| --- | --- |
| Id | `umbilici` |
| Status | Current |
| Kind | app, agent tool, script |
| Area | Viewers and apps |
| Run | [huggingface.co/spaces/SharpMeow/umbilici](https://huggingface.co/spaces/SharpMeow/umbilici) (the page), `python3 spaces/umbilici/tools/build_lines.py DATASET_DIR OUT.json`, `python3 spaces/umbilici/tools/build_lasagna.py DATASET_DIR OUT_DIR`, `python3 -m http.server` in `spaces/umbilici/` (the page locally, after the two builds) |
| Code | `spaces/umbilici/app.js` (the page), `spaces/umbilici/index.html`, `spaces/umbilici/style.css`, `spaces/umbilici/tools/build_lines.py`, `spaces/umbilici/tools/build_lasagna.py`, `spaces/umbilici/README.md` (the Space card), `spaces/umbilici/NOTICE`, `spaces/umbilici/LICENSE` |
| Tests | `tests/test_umbilici.py`, 11 tests, standard library (2 more need numpy, numcodecs and Pillow and skip without them) |
| Needs | In the browser: WebGL 2 (3D textures), ES modules and import maps, three.js 0.160.0 from cdn.jsdelivr.net. `build_lines.py`: Python 3.10 or newer, standard library. `build_lasagna.py`: numpy, numcodecs (Blosc), Pillow |
| Runs on | The visitor's browser. A whole-scan radiograph of PHerc0191 (119 heights, about 1,070 range reads of 16 KB) loaded in under 25 s in headless, software-rendered Chromium on a 4-core cloud container (2026-10-23); a GPU and a home connection are faster. `build_lasagna.py` read the 64 PHerc0175A parts (about 48 GB) in about 4 minutes with three downloads at once, about 12 s per part (cloud container, 2026-10-23) |
| Network | The visitor's browser: `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (CT chunks by HTTP range request; the bucket allows any origin and the Range header), `cdn.jsdelivr.net` (three.js), `fonts.googleapis.com` and `fonts.gstatic.com` (fonts), the Space itself. `build_lines.py`: the same bucket (each scan's `.zattrs` and the `.zarray` of all six levels). `build_lasagna.py`: none (reads a local copy) |
| Writes | The page: nothing on any server (the URL bar holds the view; downloads are made in the browser; two `localStorage` keys: `umbilici.seen` hides the first-visit hint, `umbilici.settings` keeps the viewer settings). `build_lines.py`: `OUT.json`. `build_lasagna.py`: `OUT_DIR/cos_Z.webp` and `ori_Z.webp` for nine heights, `needles.bin`, `meta.json` |
| Go-ahead | Needed to make the Space public: Chase's yes, given 2026-10-23 ("yes, make Umbilici public"). Later redeploys from merged `main` with public data fall under the standing yes (rule 8). Not needed to use the page or run the builds |
| Released | Space [`SharpMeow/umbilici`](https://huggingface.co/spaces/SharpMeow/umbilici) 1.6.1 (Space commit `c72b2cb0`), public since 2026-10-23 07:38 UTC (Chase switched it public); README "Released tools" entry `umbilici` |
| License | Apache 2.0 for the page and tools ([`spaces/umbilici/LICENSE`](../../spaces/umbilici/LICENSE), [`NOTICE`](../../spaces/umbilici/NOTICE)); each line keeps its own licence (MIT, CC BY 4.0, CC BY-NC 4.0), the lasagna derivative and the scans are CC BY-NC 4.0 |
| Checked | 2026-10-23 against commit `9edd7a8` |

## What it does

A Herculaneum scroll is a sheet of papyrus wound around a center. Its center line, the umbilicus, is where tracing tools such as VC3D and villa's lasagna begin. People have published center lines for 13 of the 22 scans on the prize page, and the other nine have lines from Chase Hendrick's Center Finder (model output). They are collected, with hashes and licences, in the dataset [SharpMeow/vesuvius-center-lines](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines). Umbilici shows them.

Three views. **Array**: the 22 lines side by side, heights to scale in millimetres, people's lines ice blue and the Center Finder's amber, with an optional exaggeration of side-to-side drift (default 3x, labeled on the page). **X-ray**: one scan, rendered from its level-5 CT (32x down) as a radiograph (CT summed along each ray) or a maximum intensity projection, with its lines inside and an axial slice (level 4, then level 3) on which each line's crossing is marked. **Lasagna**: PHerc0175A with a small derivative of villa's lasagna `predict3d` field from [SharpMeow/pherc0175a-lasagna](https://huggingface.co/datasets/SharpMeow/pherc0175a-lasagna): its cos channel at nine heights, an orientation picture per height, and 155,891 surface normals drawn as short needles.

The Space stores no CT. The browser reads one z plane of each 128-voxel chunk (16 KB, uncompressed uint8 in the bucket) with an HTTP range request. Every line keeps its source, licence, upstream link and note; the nine Center Finder lines show the automatic CT end check's grade for each end (PASS, FLAG, and CT recap where an end was refit to the CT) and which ends are usable.

For every level of reader: a **Guide** with five tabs (Start here for newcomers; VC3D and villa, with how each of villa's readers treats these files, cited to villa's source and tutorial, and two Python snippets that were run against the live dataset and bucket; For researchers, with every statistic defined; Data details, with frames, pyramids and encodings; Credits). A **Data** dialog holds every number as sortable tables (29 lines, 22 scans) with `lines.csv`, `scans.csv`, `points.csv` and `umbilici.json` downloads. Each scan card gives, per line, a download link and copyable URL for the raw file, the sha256, every statistic (points, z range, coverage, control-point steps, mean and offset from the grid center, stray, tilt and wiggle about a least-squares line, path length, whether the file carries VC3D's frame stamp), the pair gaps between two lines, each line's x, y, z at the current slice, the scan's OME-Zarr URL and pyramid, and a link that reopens the view.

A center line is geometry, and the lasagna field is model output. Nothing on the page is a reading of any text.

The Guide's Connect your tool tab (also the Connect button) lists the URLs of every line, scan and the lasagna field with tested snippets for Python, villa's `vesuvius` package, VC3D, neuroglancer and the command line; each scan card has an open in neuroglancer link ([spaceconnect](spaceconnect.md), 24 Oct 2026).

## When to use it

- To see where the public center lines are, how they wander, and where two people's lines disagree (the card gives the median gap).
- To check a line against CT at any height before using it as a tracing start.
- To show the PHerc0175A lasagna field to someone before they download 48 GB.
- To get a scan's lines, or a line's position at a height, from a script (`window.umbilici`).
- To load a line in VC3D or villa's spiral fit: the guide's VC3D and villa tab says how each reads the files, and the card copies the file URL, the OME-Zarr URL and the x, y, z at a slice.
- To download every line's statistics as CSV or JSON.

Do not use it:

- To score or compare center finders: use the frozen tests in the Center Finder's own records; the page has no control.
- To read CT at full resolution: the slice stops at level 3 (8x down). Use VC3D or the OME-Zarr directly.
- To view traced windings or ink: use [Unroll](unroll.md) or [Scroll Lens](scroll-lens.md).

## Quick start

```bash
cd spaces/umbilici
hf download SharpMeow/vesuvius-center-lines --repo-type dataset --local-dir /tmp/center-lines
python3 tools/build_lines.py /tmp/center-lines data/lines.json
python3 -m http.server 8765    # then open http://localhost:8765/?mode=scan&scan=PHerc0191&z=10400
```

`build_lines.py` prints one line per scan (`PHerc0191 20250821151635-9.362um-1.2m-113keV-masked.zarr [18977, 8387, 8387] 6 ['drobkov', 'tauil']`, 2026-10-23). It worked when the page's Array view shows 22 scans and the X-ray view's status reads `CT level 5 (300 µm voxels), 119 heights`. Without `data/lasagna/` the Lasagna button is disabled; build it with `tools/build_lasagna.py` from a local copy of the lasagna dataset.

## Checks and controls

- **Lines are copied, not changed.** `build_lines.py` copies each file's control points (rounded to whole voxels), the public fields of the dataset's `index.json` and the frame stamp VC3D reads (`voxelsize_um`, `volume`, `volume_width`, `volume_height`, `volume_slices`); nothing else in a file's metadata is copied (`tests/test_umbilici.py`).
- **The villa claims are cited.** The guide's statements about VC3D and spiral-fitting come from villa `main`'s `volume-cartographer/core/src/Umbilicus.cpp` and `spiral-fitting/umbilicus.py`, read 2026-10-23, and the spiral tutorial (last updated 16 Sep 2026); a test checks the citations are on the page. They can go stale when villa changes. The dataset's `SHA256SUMS` checks the files themselves.
- **Lasagna chunks have one owner.** A chunk is taken only from the part whose crop holds its origin, so overlapping parts cannot overwrite each other (`inside()`, tested). The shipped `needles.bin`, `cos_6400.webp` and `ori_6400.webp` were rebuilt byte for byte by `tools/build_lasagna.py`'s writer from the same reduction (2026-10-23).
- **No control for the picture itself.** The page shows lines and CT; it does not test whether a line is at the true center. The end-check grades come from the dataset, and their meaning is on the page.

Claim label: Sourced fact, for the lines and their sources (copied from the dataset); Model output, for the nine Center Finder lines and the lasagna layers. Interpretation, for the statistics' meaning (each is defined on the page).

## Commands and options

### build_lines.py

```text
python3 tools/build_lines.py DATASET_DIR OUT.json
```

| Option | Default | Meaning |
| --- | --- | --- |
| `DATASET_DIR` | required | A copy of SharpMeow/vesuvius-center-lines: `index.json` and `lines/` |
| `OUT.json` | required | The page's line table, normally `data/lines.json` |

### build_lasagna.py

```text
python3 tools/build_lasagna.py DATASET_DIR OUT_DIR
```

| Option | Default | Meaning |
| --- | --- | --- |
| `DATASET_DIR` | required | A copy of SharpMeow/pherc0175a-lasagna: `index.json` and `parts/*.tar` |
| `OUT_DIR` | required | Where the slices, `needles.bin` and `meta.json` go, normally `data/lasagna` |

### The page

| URL parameter | Default | Meaning |
| --- | --- | --- |
| `mode` | `array` | `array`, `scan` (the X-ray view) or `lasagna` |
| `scan` | none | A scroll id such as `PHerc0191`; needed for `scan` and `lasagna` |
| `z` | the line's middle | Slice height in level-0 voxels; in `lasagna` it snaps to the nearest of the nine heights |
| `ex` | `3` | Side-to-side exaggeration in the Array view, 1 to 20 |
| `guide` | none | Opens the guide at a tab: `basics`, `vc3d`, `research`, `data`, `credits` |
| `data` | none | Opens the Data tables: `lines` or `scans` |
| `glow` | `0.8` | Glow (bloom) strength, 0 to 3; the gear button's settings also hold glow spread, quality, film grain and spin, saved in `localStorage` under `umbilici.settings` |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `build_lines.main(src, out)` | None; writes `out` | `KeyError` when a scan has no line with a volume; `urllib.error.URLError` without network | Reads each scan's `.zattrs` and every level's `.zarray` from the bucket |
| `build_lasagna.reduce(ds)` | `(field16, slices)`: dicts of uint8 arrays | `FileNotFoundError` for a missing part | Reads tars in place |
| `build_lasagna.write(field16, slices, out)` | None; writes the files under `out` | `OSError` | |
| `build_lasagna.orientation_rgb(nx, ny, val)` | uint8 RGB array | | Hue from the doubled in-plane angle, so a normal and its opposite match |

## Inputs

- **Lines:** `index.json` (`scrolls`, `files` with `scroll`, `scan`, `source`, `kind`, `credit`, `licence`, `upstream`, `file`, `sha256`, `z`, `note`, `volume`) and one VC3D umbilicus JSON per line (`control_points` with `x`, `y`, `z` in the scan's level-0 voxels).
- **Lasagna:** the dataset's `index.json` (`parts` with `part`, `tar`, `crop_zyx`) and its tars, each holding `PHerc0175A_{cos,grad_mag,nx,ny}.ome.zarr` chunks (64³, Blosc zstd, uint8; normals stored as `v * 127 + 128`).
- **CT:** the open-data OME-Zarr volumes named in `lines.json`, levels 3 to 5 (chunks 128³, uncompressed uint8).

## Outputs

`data/lines.json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `made`, `frame` | string | Copied from the dataset |
| `sources` | object | Source id to `label` and `short` (the page's chips) |
| `scrolls[].scroll`, `scan`, `volume`, `zarr` | string | Scroll id, scan id, volume name, bucket URL of the OME-Zarr |
| `scrolls[].voxel_um` | number | Voxel size in µm, from the volume name |
| `scrolls[].shape` | [int, int, int] | Level-0 shape, z y x |
| `scrolls[].pyramid[]` | object | Per level: `path`, `shape`, `chunks`, `dtype`, `compressor` (all 132 levels of the 22 scans: `|u1`, 128³, none; 2026-10-23) |
| `scrolls[].lines[].stamp` | object | The file's `voxelsize_um`, `volume`, `volume_width`, `volume_height`, `volume_slices`, when present (22 of 29) |
| `scrolls[].lines[].points` | [int] | Flat x, y, z triples, sorted by z, level-0 voxels |
| `scrolls[].lines[].grade` | string or null | `PASS` or `FLAG` for a Center Finder line (FLAG when either end is; `VOID` only in builds from releases before v2.2) |
| `scrolls[].lines[].ends` | object | Per end (`low`, `high`): `grade`, `recapped` (the end's last 10 mm is a straight fit to the CT) and `D_mm`, from the dataset index's `ct_ends` (v2.2 and later); empty for lines made by people |
| `scrolls[].lines[].usable` | [string] or null | The ends the file's `usable_ends` marks usable |

`data/lasagna/meta.json` names the nine heights and `needles.bin`'s layout: `count` uint16 x, y, z triples (level-0 voxels), then `count` int8 nx, ny, nz triples (times 127), then `count` uint8 grad_mag.

| Exit code | Meaning |
| --- | --- |
| `0` | The output was written |
| `1` | A Python error (missing file, no network for `build_lines.py`); nothing usable was written |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| A Python traceback ending in `IndexError` or `FileNotFoundError` | Too few arguments, or a wrong folder | Pass the dataset folder and the output path |
| The slice says `CT unavailable` | The bucket did not answer, or a browser extension blocks range requests | Reload; check the browser console |
| `404` lines in the browser console | Chunks outside the scroll's mask are not stored | Nothing: they read as empty |
| The Lasagna button is grey | `data/lasagna/meta.json` is missing | Run `build_lasagna.py` |

## How it works

1. `build_lines.py` reads the dataset index, finds each scan's volume, reads its pyramid (every level's shape, chunks, dtype, compressor) from the bucket, and writes the control points, sorted by z, with each line's public fields and frame stamp.
2. The page draws each line as a tube through its control points (Catmull-Rom). World units are millimetres: voxels times the voxel size from the volume name.
3. The X-ray view picks a z stride so the level-5 volume has at most 120 heights (72 on touch screens), fetches every fourth height first and copies it into the gap, then fills the rest, three heights at a time and at most ten requests at once. A raymarching shader takes 220 samples per pixel (140 on touch screens or at low quality, half while the camera moves) and shows either `1 - exp(-gain * sum)` (radiograph) or the brightest sample.
4. The slice reads level 4, draws it, waits 220 ms, then reads level 3. Contrast is the 1st to 99.5th percentile of non-empty pixels. Each line's position at the slice height is interpolated between control points.
5. The statistics are computed in the browser from the rounded control points: a least-squares line x(z), y(z) gives the tilt (its angle from vertical) and the wiggle (RMS distance from it); the pair gap samples both lines every 64 voxels where both exist. The Data downloads are made in the browser from the same numbers.
6. `build_lasagna.py` reads level-3 chunks of cos, grad_mag, nx and ny into a 16x field (normals subsampled, the others averaged) and level-2 chunks at nine heights. Needles sit on a 96 by 96 by 192 voxel grid where cos is above 40 and grad_mag above 20.

## Cost and time

Free: a static Space, and CT comes from the public bucket at the visitor's end. See Runs on for the measured times. Building `data/lasagna/` needs a local copy of the 48 GB dataset or a fast link to it.

## For agents

- **Command:** open `https://sharpmeow-umbilici.static.hf.space/?mode=scan&scan=PHerc0191&z=10400` in a headless browser with WebGL, then call `window.umbilici.state()`.
- **Parse:** `scans()` lists scans with `sources` and `grade`; `lines(scroll)` gives control points `[x, y, z]`; `at(scroll, z)` gives each line's `xy` at a height; `stats(scroll)` gives every statistic and the pair gaps; `settings({glow: 1.5})` sets the glow; `bench(n)` times `n` frames; `table('lines')`, `table('scans')` and `csv('lines' | 'scans' | 'points')` give the Data tables; `state().ct` is `{loaded, total}` for the CT stream; `image()` and `slice()` return PNG data URLs.
- **Rerun:** safe; the page writes nothing. The builds overwrite their outputs.
- **Success:** `state().ct.loaded === state().ct.total` and the status line names the level and heights.
- **Not a pass:** a line drawn through bright CT is not a checked line; only the end-check grades and a person's look on CT say anything about a line's quality.
- **Go-ahead:** creating, pushing or making the Space public.
- **Never:** call a center line or the lasagna field a reading; rehost CT on the Space; copy a line file's own metadata into the page.

## Tests

`python3 -m unittest tests.test_umbilici -v`: the line table (volumes, sorting, rounding, grades, sources, no copied metadata), the lasagna helpers (orientation ignores the normal's sign; a chunk belongs to one part), the page (no long dashes, every `window.umbilici` call documented in the card, no hard-coded volume URL, both datasets linked, the villa claims cite their source files, Center Finder written as a name). Not covered: the WebGL rendering and the streaming, which were checked by eye in headless Chromium on 2026-10-23.

## History

- 2026-10-24: 1.7.0, Connect your tool tab and per-scan neuroglancer links, branched from `main` at `2ce4d50`.
- 2026-10-23: first version, private Space preview (Space commit `45a55be`); code added here in the PR for branch `claude/project-thread-xrkbs0`.
- 2026-10-23: 1.1.0 (Space commit `1db9a117`). Guide (five tabs), Data tables with CSV and JSON downloads, per-line statistics, VC3D and villa hooks (raw file URLs, OME-Zarr URL, x, y, z at a slice, view links), CT pyramids and frame stamps in `lines.json`; "Center Finder" written as a name (Chase, 2026-10-23). The lasagna dataset links read "(soon)" until that dataset is on the Hub; it went public at 08:09 UTC on 23 Oct and the live page links it directly.
- 2026-10-23: 1.2.0 (Space commit `a1af38e8`). Settings (gear button): glow strength and spread, quality, film grain, spin (Chase: "can there be settings and change the glow strength"). The glow no longer flickers while the camera moves: the X-ray takes fewer ray steps during a drag instead of lowering the pixel ratio, which had resized the bloom buffers (Chase: "the glow is glitchy when moving the camera").
- 2026-10-23: 1.2.1 (Space commit `b0a19cdf`). The rest of the flicker: a drag across the Array view swept the pointer over scans, and each hover dimmed every other line at once, halving and restoring the glow many times a second (measured: mean frame brightness 14.5 to 7.0 and back). Hover now waits while the camera is dragged and eases in; withdrawn lines keep their fade under hover (Chase: "its still flickering bright then back to normal").
- 2026-10-23: 1.2.3 (Space commit `0808a83d`). Contrast default 44, 20% lower (Chase: "make contrast like 20% lower by default"); panels no longer use a backdrop blur over the WebGL canvas, a likely cause of the glitch Chase saw while the first-visit spin redraws every frame; the first-visit hint sits under the buttons on phones; the guide and cards say why a VOID end check cannot judge an end.
- 2026-10-23: 1.3.0 (Space commit `47a3febe`). Faster (Chase: "its a bit laggy and slow"). Frame cost scales with pixels (headless, 2x screen: about 3.7 s per frame at pixel ratio 2, 2.2 s at 1.5, 0.6 s at 0.75, software rendering), so auto quality starts at 1.5 (1.25 on touch screens) instead of the full screen density and steps down to 1 and 0.75, at most twice, when the median frame takes over 25 ms; X-ray rays stop once a pixel is white; the film grain no longer animates; the CT texture uploads every 400 ms instead of 220 while streaming. `bench(n)` and `state().pixel_ratio` report it.
- 2026-10-23: 1.4.0 (Space commit `ecfaea91`). Frames capped at 60 a second, 30 while the array only spins, with the spin timed rather than per frame, so a 120 Hz screen no longer draws everything twice as often; the canvas drops antialias and the preserved buffer, which the composer never used; the opening view refits when the Hub resizes the Space's frame until the visitor moves the camera; the first-visit hint sits under the intro instead of over the view buttons (Chase: "screen it glitching when in first time here mode"). The glitch itself was not reproduced in headless Chromium.
- 2026-10-23: 1.5.0 (Space commit `6a5911be`). Slice panel (Chase: "a toggle to hide or show it, a toggle to match the rotation on screen ... sometimes turns black ... have the slider update it in real time"): hide and show buttons and a settings switch (`inset`); "turn with view" (`turn`) turns the slice to face the way the 3D view does, checked from above against the 3D slice plane; the height slider redraws it live from the level-5 CT already loaded (or a cached level 3 or 4 slice), then sharpens; it is composed off screen and swapped in at once, so it no longer goes black while CT streams (the lasagna path cleared it before streaming). Speed: auto quality starts at 1.25 pixels per CSS pixel, slice pixels go through a lookup table, the CT texture re-uploads every 1.2 s instead of 0.4 s while streaming, and URL updates are debounced.
- 2026-10-23: 1.6.1 (Space commit `c72b2cb0`). Grade coloring: FLAG is red (it was orange, close to the Center Finder amber), and each end's grade shows as its own colored tag on the scan card, the hover tip, the guide and the Data table, with CT recap as a dim note beside it.
- 2026-10-23: 1.6.0 (Space commit `1e158abe`). Lines rebuilt from SharpMeow/vesuvius-center-lines v2.2 (dataset commit `668455b8`, every file matching its SHA256SUMS), whose CT end check replaces the tilt check: per-end grades on each Center Finder card (14 of 18 ends PASS, 5 of them CT recap; 4 FLAG), in the Data table (`low end`, `high end`) and in the guide; no VOID. Geometry changed for PHerc0175A, PHerc0483A, PHerc0490A and PHerc0490B.

## Related

- [Unroll](unroll.md): the sibling 3D viewer for traced windings and ink; Umbilici borrows its look.
- [Scroll Lens](scroll-lens.md): model views of small cubes of non-prize scans.
- The datasets: [SharpMeow/vesuvius-center-lines](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines), [SharpMeow/pherc0175a-lasagna](https://huggingface.co/datasets/SharpMeow/pherc0175a-lasagna).
