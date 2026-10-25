# unroll: view and virtually unroll Herculaneum scrolls in 3D in the browser, and score ink maps

Unroll 1.5.0 is a static web app, a Hugging Face Space, that rebuilds traced scroll windings in 3D with X-ray and ink layers, unrolls them, shows raw CT around any point, and scores your ink map against the published one (Ink Bench).

| Field | Value |
| --- | --- |
| Id | `unroll` |
| Status | Current |
| Kind | app |
| Area | Viewers and apps |
| Run | [huggingface.co/spaces/SharpMeow/unroll](https://huggingface.co/spaces/SharpMeow/unroll) (the Space page); [sharpmeow-unroll.static.hf.space](https://sharpmeow-unroll.static.hf.space/) (the app alone, installable); Ink Bench on the command line: `python inkbench.py compare PRED.png --segment WNNN -o BUNDLE.json` |
| Code | Not in this repository: the Space's own git repository, [huggingface.co/spaces/SharpMeow/unroll/tree/main](https://huggingface.co/spaces/SharpMeow/unroll/tree/main) (page code in index.html, app.js, ui.js and the lib folder; build tools and [inkbench.py](https://huggingface.co/spaces/SharpMeow/unroll/blob/main/tools/inkbench.py) in the tools folder; one manifest per scroll in the scrolls folder), read at Space commit e31bb23 |
| Tests | None in this repository. The Space has its own in its [tests folder](https://huggingface.co/spaces/SharpMeow/unroll/tree/main/tests); not run for this page |
| Needs | A browser with WebGL; three.js 0.160, loaded from jsDelivr. The CT volume view needs float render targets for exact picking (it falls back to picking on the CPU). `inkbench.py`: Python 3 with numpy and Pillow |
| Runs on | The viewer runs in the visitor's browser, on any device; load and frame times are Not measured. Ink Bench's three Quick start commands, with the reference fetched over the network: 15.5 s wall together on a 4-core cloud container, Python 3.13 (measured 2026-10-16 for this page) |
| Network | The page and its data from `huggingface.co` and `sharpmeow-unroll.static.hf.space`; three.js from `cdn.jsdelivr.net`; the CT volume view streams OME-Zarr from the open-data bucket `s3://vesuvius-challenge-open-data`; Open your own fetches only a URL you give (the server must allow CORS). `inkbench.py` fetches `data/bench/` from the Space unless `--root` names a local checkout |
| Writes | In the browser only: settings in `localStorage` under `unroll.settings.v1`; the installed app's service-worker caches `unroll-shell-<tag>`, `unroll-data-<tag>` and `unroll-runtime-<tag>`; scrolls opened with Open your own in browser storage; downloads you ask for (a picture, an Ink Bench bundle). Nothing is uploaded. `inkbench.py` writes the bundle given by `-o` (else prints it) and, with `adapt`, a 16-bit PNG |
| Go-ahead | Not needed to view it or run Ink Bench. Changing the Space, or posting its pictures or scores, needs Chase's yes (the go-ahead rule, hard rule 8), and never with private work or target-scroll data |
| Released | Hugging Face Space `SharpMeow/unroll`, version 1.5.0 of 2026-10-16 (the Space's `version.json`); in this README's "Released tools" since 2026-10-16 (`9896827`), pinned there with AutoPipeline. The Space's changelog starts at 0.9.0 (2026-10-15); 1.0.0 is the first release |
| License | Code: Apache 2.0 ([LICENSE](https://huggingface.co/spaces/SharpMeow/unroll/blob/main/LICENSE), with `NOTICE`); the scan data and everything derived from it (`data/`, `og.jpg`): [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/); three.js keeps its MIT license |
| Guide | [`docs/unroll-space.md`](../unroll-space.md) |
| Checked | 2026-10-16 against commit `7be3185` |

![Concept illustration of a papyrus roll unrolling flat along a diagonal, with a copper grid layer and a fine layer of ivory points peeling up from the flat sheet.](../assets/unroll/unroll-hero.webp)

*Concept illustration: a roll unrolls flat and its layers lift apart, as Unroll stacks X-ray, surface and ink layers. No scan data.*

## What it does

A Herculaneum scroll cannot be opened, so it is scanned with X-rays (CT), and people trace its sheet turn by turn as segments: curved surfaces stored as tifxyz grids of 3D points. Unroll puts those traced surfaces back together in 3D in a web page and lets a visitor unroll them, outermost winding first, with a timeline. On PHerc0139 it shows 37 traced windings (`w023` to `w059`) from the public 9.362 um meshes, decimated to 579,450 vertices; a scroll picker opens eight more scrolls of the open data (PHerc. 814, 9B, 343P, 841, 800, 172, 1447 and 1667). Because each traced winding runs a little past one full turn, about a tenth of the unrolled strip repeats its neighbor's surface.

Each surface can show an X-ray layer (CT intensity on the surface), the Vesuvius Challenge's published ink detection where the open data has it, and on PHerc0139 an `ink_9um` (9 um) layer: the public `scrollprize/ink_9um` model (seed 42, step 75,000), run by Chase on the 9.362 um scan over all 37 windings, on Hugging Face ZeroGPU and Modal. A close-up view per winding has pan, zoom, a scale bar and a swipe between two layers. The CT tools (1.2.0 to 1.5.0) add window and level for the X-ray layer, a CT volume view (a maximum intensity projection of a cube of raw scan around a picked point, with the traced segments that pass through it), and streaming from the open-data bucket. Open your own (the **+** button) reads your own meshes and layers in the browser. Destroy mode tears, crushes, burns or soaks the papyrus; it is a toy, not a model of real damage.

Ink Bench scores an ink map of one PHerc0139 winding against the published 2.4 um ink detection: it aligns the map automatically, then reports Pearson r, IoU, Dice and average precision (AP), with the X-ray intensity and uniform noise as floors a real ink model should beat. It runs in the page, and `tools/inkbench.py` gives the same numbers on the command line and writes the same bundle (schema `unroll-inkbench/1`).

What it does not do: every ink layer is model output, not a reading. Letters visible in a layer are candidates for expert reading, never a reading by themselves. Ink Bench scores agreement with another model's output (the published ink detection), not ground truth, and on PHerc0139 that is not held-out ground for `ink_9um` (w045, for one, is not held out from it). Unroll does not trace, render or run ink detection itself; the layers are precomputed.

Since 1.6.0 (24 Oct 2026) the Embed sheet (the </> button, linked from About) also has Connect your tool: the open-data URLs behind every layer with tested snippets for Python, villa's `vesuvius` package, VC3D, neuroglancer and curl, and links to the page's own API ([spaceconnect](spaceconnect.md)).

## When to use it

- To see a scroll's traced windings, how they nest and how they unroll, without installing anything.
- To look at ink layers in context, or compare the published ink and `ink_9um` on one winding with the swipe.
- To glance at raw CT around a point of a traced surface, with the segments that pass through it.
- To score an ink map of a PHerc0139 winding (w023 to w059) against the published ink, with X-ray and noise floors, in the page or with `inkbench.py`.
- To show someone the problem: the page explains its terms in a glossary.
- Offline, as an installed app.

Do not use it:

- To score a map against human ink labels with the reversed-depth control: use [auc](auc.md).
- To check that two runs of one model agree: use [verify](verify.md).
- To trace, render or run ink detection: use villa, or [autopipeline](autopipeline.md) for a whole run.
- For scrolls or segments outside its manifests in Ink Bench: it knows only the PHerc0139 windings `w023` to `w059`.
- As evidence that text was found or read.

## Quick start

Open [huggingface.co/spaces/SharpMeow/unroll](https://huggingface.co/spaces/SharpMeow/unroll); drag to orbit, scrub the timeline to unroll, click a sheet for its close-up, press `?` for the keys. For an agent, a deep link sets the view: `/?scroll=PHerc0139&t=0.6&layer=overlay&focus=w047&compare=0.3`.

Ink Bench from the command line, with the Space's own example maps of winding w046:

```bash
S=https://huggingface.co/spaces/SharpMeow/unroll/resolve/main
curl -fsSLO $S/tools/inkbench.py
curl -fsSLO $S/data/bench/w046_gpu.png       # the public ink_9um layer of w046
curl -fsSLO $S/data/bench/w046_ct.png        # the X-ray intensity on the same grid: the floor
python inkbench.py compare w046_gpu.png --segment w046 --model ink_9um -o ink9um.json
python inkbench.py compare w046_ct.png --segment w046 --model x-ray-floor -o floor.json
python inkbench.py rank ink9um.json floor.json --metric ap
```

To score your own map, replace `w046_gpu.png` by your PNG or TIFF of one winding and `w046` by its id. On 2026-10-16 this printed (the Space's example maps, public data):

```
pearson 0.4220  iou 0.2377  dice 0.3841  ap 0.3415  (agreement with published ink, not ground truth)
pearson 0.2356  iou 0.1123  dice 0.2019  ap 0.1342  (agreement with published ink, not ground truth)
w046
  1. ink_9um                        ap=0.3415  pearson=0.4220 iou=0.2377 dice=0.3841
  2. x-ray-floor                    ap=0.1342  pearson=0.2356 iou=0.1123 dice=0.2019
```

It worked when every command exits 0 and your model ranks above `x-ray-floor`. The images and bundles are derived from CC BY-NC 4.0 scan data: keep them out of public commits.

## Checks and controls

- **The X-ray floor and noise.** Ink Bench scores the raw X-ray intensity and uniform noise on the same grid as controls. A model that does not beat the X-ray floor on AP has shown nothing about ink. On w046 (above), `ink_9um` scored AP 0.3415 against 0.1342 for the floor (measured 2026-10-16).
- **Over all 37 windings** (the Space's `docs/examples/bench/`, from its README): median AP 0.319 for `ink_9um`, 0.117 for X-ray intensity and 0.089 for noise, and `ink_9um` beats X-ray intensity on AP on every winding. On Pearson r the medians are 0.422, 0.266 and 0.000, but X-ray intensity outranks `ink_9um` on `w039`, `w053`, `w054` and `w057`, so rank by AP and look at windings where the floor wins.
- **A threshold that can fail.** `compare --min-pearson X` exits 1 when Pearson r is below X: on w046 with `--min-pearson 0.9` it exited 1 (seen 2026-10-16).
- **Not a control:** the reference is itself model output, and PHerc0139 is not held-out ground for `ink_9um`. The 3D viewer has no control: it shows layers, it does not test them.

Claim label: Model output, for every ink layer and every Ink Bench score, which measures agreement with the published ink detection, not ground truth.

## Commands and options

### Page URL parameters

From the Space's `llms.txt` and `docs/AGENT_API_UI.md`; query string or hash.

| Option | Default | Meaning |
| --- | --- | --- |
| `scroll` (`s`) | the default scroll | Scroll id, such as `PHerc0139` |
| `t` | Not recorded | Unroll amount, 0 (rolled) to 1 (unrolled) |
| `layer` (`l`) | Not recorded | `xray`, `ink` or `overlay`; the action form `?layer=gpu` selects the `ink_9um` layer |
| `focus` | none | A winding id, such as `w047`, to open its close-up |
| `view` | Not recorded | `main`, `overlay` or `compare` |
| `compare` | Not recorded | Swipe position, 0 to 1 |
| `panel` | none | `about`, `help`, `open`, `why`, or `settings` |
| `destroy=1`, `tool` | off | Destroy mode, and its tool: `tear`, `crush`, `burn`, `water` |
| `sandbox=1` | off | Destroy sandbox |
| `cam` | the fitted start view | Camera as `px,py,pz,tx,ty,tz` (scene units are millimeters) |
| `pos`, `play=1` | Not recorded | Position, and start playing |
| Any setting below, such as `?quality=low&speed=2&hud=0` | the setting's default | Applies for one visit, not saved |

### Settings

Set in the Settings panel, by URL, or with `unrollView.settings.set(KEY, VALUE)`; saved in `localStorage` under `unroll.settings.v1`.

| Option | Default | Meaning |
| --- | --- | --- |
| `quality` | `high` (`medium` on touch) | `low`, `medium`, `high`: pixel ratio; `low` also turns the glow off |
| `reducedMotion` | the system setting | boolean |
| `speed` | `1` | 0.25 to 4: intro, unroll and roll up |
| `bloom` | `1` | 0 to 2: glow |
| `background` | `dark` | `dark`, `black`, `slate`, `warm` |
| `hud` | `true` | Title, readout and credit |
| `labels` | `true` | Text under the View icons |
| `sensitivity` | `1` | 0.25 to 3: orbit, zoom and pan speed |
| `inkBench` | `true` | Show the Ink Bench button |
| `units` | `metric` | `metric` or `imperial` readout |

### Agent API: `window.unroll`

Every call returns a Promise of `{ ok: true, ... }` or `{ ok: false, error, code }` and never throws; codes are `invalid`, `not_found`, `unavailable`, `timeout`, `conflict`, `failed`, `load_failed`. `await unroll.schema()` lists every method with its parameters, and the Space's `api.json` is the machine-readable reference; `window.unrollView` adds the button actions, settings and glossary.

| Option | Default | Meaning |
| --- | --- | --- |
| `waitFor('ready')`, `waitFor('settled')`, `waitFor({...}, { timeout })` | | Wait for the scroll to load, for motion to stop, or for a state |
| `getState()`, `describe()`, `version()` | | The state as JSON (scroll, t, layer, winding, focus, panels, destroy, camera, description, url), in words, and `{ version, date, sha, api }` |
| `setUnroll(T)`, `play(B)`, `rollUp(B)` | | Unroll to T (0 to 1), animate, roll back up |
| `setLayer(L)` | | `xray`, `ink` or `overlay` |
| `focus(ID, { view })`, `focus(null)`, `compare(B, X)`, `closeup({...})` | | Close-up of a winding, the swipe, and zoom and pan in it |
| `camera.get()`, `camera.orbit()`, `camera.zoom()`, `camera.pan()`, `camera.set()`, `camera.reset()` | | The camera, in millimeters |
| `listScrolls()`, `openScroll(ID)`, `prizeOnly(B)` | | Other scrolls (the page reloads) |
| `bench.open('compare')`, `bench.compare({ segment, layer, thresholds })`, `bench.metrics()`, `bench.close()` | | Ink Bench in the page |
| `open.fromURL(URL)`, `open.fromFiles([...])`, `open.example()`, `open.validate(M)` | | Open your own |
| `screenshot()`, `deepLink(true)`, `run([[...], ...])`, `on('change', F)`, `off(ID)` | | A PNG of the view as `{ dataURL }`, the link for this view, a batch of calls, change events |
| `unrollView.action('install')`, `unrollView.pwa.state()` | | Install the app, and its state |

### `python inkbench.py`

The command-line Ink Bench, `tools/inkbench.py` in the Space (version 1.0.0, one file, numpy and Pillow).

```
usage: inkbench [-h] {compare,rank,validate,cite,adapt,segments} ...
usage: inkbench compare [-h] --segment SEGMENT [--target {ink,ct}]
                        [--model MODEL] [--model-url MODEL_URL]
                        [--t-ref T_REF] [--t-pred T_PRED] [--invert]
                        [--alignment ALIGNMENT] [--annotations ANNOTATIONS]
                        [--root ROOT] [--base BASE] [-o OUT]
                        [--min-pearson MIN_PEARSON]
                        pred
usage: inkbench rank [-h] [--metric {pearson,iou,dice,ap,f1}]
                     bundles [bundles ...]
usage: inkbench adapt [-h] -o OUT [--reduce {mean,max}] [--page PAGE]
                      [--channel CHANNEL]
                      {tif-stack,villa-folder,nnunet,timesformer} path
```

| Option | Default | Meaning |
| --- | --- | --- |
| `compare pred` | required | Your ink map of one winding: PNG or TIFF |
| `compare --segment SEGMENT` | required | Winding id, `w023` to `w059` (`segments` lists them with their grid sizes) |
| `compare --target {ink,ct}` | `ink` | Score against the published ink, or against the X-ray layer |
| `compare --model MODEL` | `unspecified` | Model name stored in the bundle |
| `compare --model-url MODEL_URL` | none | Model link stored in the bundle |
| `compare --t-ref T_REF`, `--t-pred T_PRED` | `0.5`, `0.5` | Thresholds, on maps scaled 0 to 1, for IoU, Dice, precision and recall; reference pixels at or above `T_REF` are the positives for AP |
| `compare --invert` | off | Invert your map first (for maps where ink is dark) |
| `compare --alignment ALIGNMENT` | none | A JSON file or bundle whose alignment to reuse instead of searching |
| `compare --annotations ANNOTATIONS` | none | A JSON file or bundle whose annotations to copy |
| `compare --root ROOT` | the folder above the script's, when it holds `data/bench/index.json` (a checkout of the Space); else none | Local checkout of the Space to read references from |
| `compare --base BASE` | `https://huggingface.co/spaces/SharpMeow/unroll/resolve/main/` | Where to fetch references when there is no root |
| `compare -o OUT` | none (print the bundle) | Write the bundle JSON here |
| `compare --min-pearson MIN_PEARSON` | none | Exit 1 when Pearson r is below this (for CI) |
| `rank bundles` | required | Bundles to rank, per segment |
| `rank --metric` | `pearson` | `pearson`, `iou`, `dice`, `ap` or `f1`; rank by `ap` |
| `validate bundles` | required | Check bundles against the format; exit 1 if any is invalid |
| `cite` | | Print a BibTeX entry |
| `segments` | | List the windings with their grid size and layers |
| `adapt kind path` | required | Convert `tif-stack`, `villa-folder`, `nnunet` or `timesformer` output to a Bench PNG |
| `adapt -o OUT` | required | The PNG to write (16 bit) |
| `adapt --reduce {mean,max}` | `mean` | How a TIFF stack is reduced to one image |
| `adapt --page PAGE` | none | One page of a TIFF stack instead |
| `adapt --channel CHANNEL` | `1` | The nnU-Net channel to take |

## Python API

`inkbench.py` is also a module (put it on `sys.path`, then `import inkbench`):

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `compare(pred, segment, target='ink', model=None, t_ref=0.5, t_pred=0.5, invert=False, alignment=None, annotations=None, refs=None, name=None)` | The bundle dict (keys `schema`, `tool`, `created`, `scroll`, `segment`, `reference`, `prediction`, `alignment`, `metrics`, `annotations`, `credits`, `disclaimer`) | `KeyError` for an unknown segment; `ValueError` for an unsupported image | `pred` is a path, bytes, or a 2D numpy array in 0 to 1 |
| `rank(bundles, metric='pearson')` | Rows per segment, ranked | Not recorded | What `rank` prints |
| `validate(b)` | A list of problems, empty when valid | Not recorded | What `validate` prints |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Ink Bench map | PNG (8 or 16 bit; 16 bit only grayscale; not interlaced) or TIFF (unsigned or float; 16 and 32 bit with one channel); color is turned to gray | Integer images are divided by their maximum value unless they hold only 0 and 1; float images are scaled min to max. On the winding's reference grid or any scale near it: alignment searches scales 0.6 to 1.6 and shifts up to a quarter of a side; maps over twice the grid are mean-pooled first |
| Winding ids | `w023` to `w059` of PHerc0139 | w046's grid is 640 x 463 px (`segments`) |
| Open your own | A zip, a folder or a manifest with OBJ or PLY meshes (with UVs) and PNG, JPG or TIFF layers, or a URL of one | Read in the browser; the Space's `docs/ADDING_A_SCROLL.md` gives the manifest format and limits |

## Outputs

The page shows the scroll; `screenshot()` returns a PNG data URL. `inkbench.py compare` writes the bundle (or prints it) and prints one summary line on stderr: `pearson P  iou I  dice D  ap A  (agreement with published ink, not ground truth)`.

| Field | Type | Meaning |
| --- | --- | --- |
| `metrics.pearson` | float | Pearson r of your map and the reference over the valid pixels |
| `metrics.pearsonMatchedBlur`, `metrics.blurSigmaPx` | float | The best r after blurring the reference, and that blur |
| `metrics.iou`, `metrics.dice`, `metrics.precision`, `metrics.recall` | float | At `thresholds.ref` and `thresholds.pred` |
| `metrics.ap` | float | Average precision over 51 thresholds of your map (`PR_STEPS` = 50) |
| `metrics.bestF1` | object | `f1` and the `threshold` that gives it |
| `metrics.nValid`, `metrics.validFraction` | int, float | Pixels scored, and their share of the grid |
| `metrics.pr` | list | Precision and recall at each threshold |
| `alignment` | object | `method` (`auto` or `reused`), `tx`, `ty` (reference px), `sx`, `sy`, `ncc`, `coarseNcc`, `evals` |
| `disclaimer` | str | That the scores are agreement with another model's output, not ground truth |

| Exit code | Meaning |
| --- | --- |
| `0` | `inkbench.py` finished |
| `1` | `compare --min-pearson` not met, `validate` found an invalid bundle, or an uncaught error such as an unknown segment (with a traceback) |
| `2` | A usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `KeyError: 'Unknown segment w999; known: w023, ...'` with a traceback, exit 1 (seen 2026-10-16) | `--segment` is not a PHerc0139 winding the Bench has | Use an id that `segments` lists |
| `Ink Bench reads PNG or TIFF (got ...)` | Another image format | Save as PNG or TIFF |
| `Interlaced PNG is not supported; save without interlacing.`, `16 bit PNG must be greyscale; save colour images as 8 bit.` | PNG options it does not read | Save as the message says |
| `Palette and WhiteIsZero TIFF are not supported.`, `16 and 32 bit TIFF must have one channel.`, `Signed integer TIFF is not supported; use unsigned or float.` | TIFF options it does not read | Save as a one-channel unsigned or float TIFF |
| `no *prediction* or *ink* image in FOLDER` | `adapt villa-folder` found no map | Point it at villa's output folder |
| A low `alignment.ncc` and scores near the floor | Your map is on another grid or crop, or turned | Check the winding id and orientation; reuse a good alignment with `--alignment` |
| An API call answers `{ ok: false, code: 'unavailable' }` | The method is not in this build or this scroll | Check `schema()` and `version()` |
| A Destroy call answers `{ ok: false, code: 'not_found' }` | The screen point is not on the papyrus | Take a point from `destroy.aim()` |
| The scroll fails to load | Data or network | `window.unroll` still offers `getState`, `version`, `openScroll` and `reload` |

## How it works

1. The data are precomputed by the Space's `tools/fetch.py` (meshes and ink previews from the open-data bucket, about 110 MB) and `tools/build.py` (packed meshes, WebP atlases of each layer, close-ups; mesh coarseness `UNROLL_STEP`, default 3; `--coarsen 2` writes a lighter copy for phones). `tools/gpu_layer.py` builds the `ink_9um` layer from ink_9um TIFFs, with per-run records in `data/gpu/receipts/`.
2. `scrolls/index.json` lists the scrolls and each has a manifest of its windings, meshes, layers, sources and credits; the page is driven by them.
3. The page draws the windings with three.js and unrolls them by laying each winding end to end, outermost first; the published ink is drawn in 3D through a local-contrast filter so letter-sized strokes stand out, while the close-up shows the preview unfiltered.
4. The CT volume view reads OME-Zarr chunks of the scan from the bucket and shows a maximum intensity projection in a slab square to the sheet.
5. Ink Bench normalizes your map, pools it if it is over twice the grid (`LONG_FIT` = 2), aligns it by a coarse search (long side `COARSE_MAX` = 80 px, `SCALES` = 25 scales from 0.6 to 1.6, shifts up to `SHIFT_FRAC` = 0.25 of a side, at least `MIN_VALID` = 0.3 of the grid covered) refined on an image pyramid by normalized cross-correlation, then computes the metrics on the valid pixels; AP sums precision over the recall steps of 51 thresholds of your map, 1 down to 0 (`PR_STEPS` = 50).

## Cost and time

| Case | Time | Source |
| --- | --- | --- |
| Ink Bench, two `compare` and one `rank` on w046, references fetched | 15.5 s wall in all | This page, 2026-10-16, 4-core cloud container, Python 3.13 |
| The viewer's load and frame times | Not measured | |
| The `ink_9um` layer's first batch | 37,141 patches in 57 s of measured GPU time | The Space's README |

The viewer rents nothing: it is a static page hosted as a Hugging Face Space and runs on the visitor's device. Rebuilding the `ink_9um` layer is GPU work and goes to Modal (the Modal rule, hard rule 11).

## For agents

- **Command:** `python inkbench.py compare PRED.png --segment WNNN --model NAME -o BUNDLE.json`, then `python inkbench.py rank BUNDLE.json FLOOR.json --metric ap`. In a browser: `await unroll.waitFor('ready')`, then `await unroll.getState()`.
- **Parse:** In the bundle, `metrics.ap`, `metrics.pearson` and `alignment.ncc`; compare `metrics.ap` with the X-ray floor's on the same winding. From the page, the `ok`, `error` and `code` of each call.
- **Rerun:** Safe; `compare` overwrites the `-o` file and gives the same numbers for the same inputs (its `created` time changes). The page keeps only settings and opened scrolls in the browser.
- **Success:** Exit code 0, and your model's `metrics.ap` above the X-ray floor's; in the page, `{ ok: true }`.
- **Not a pass:** A score without the X-ray floor beside it; a high Pearson r on a winding where the floor wins (`w039`, `w053`, `w054`, `w057` for `ink_9um`); any score read as ground truth; `ink_9um`'s scores on PHerc0139 read as a held-out test; letters seen in a layer.
- **Go-ahead:** Nothing to view it or run Ink Bench. Changing the Space, uploading to Hugging Face, or posting its pictures or scores needs Chase's yes first.
- **Never:** Call an ink layer or a Bench score a reading; commit Bench images, bundles or screenshots of scan data to a public repository (CC BY-NC 4.0 data, and no scroll data in git); put private work or target-scroll data in the Space.

## Tests

No tests in this repository, and none run for this page. The Space's `tests/` folder holds its own: `test_bench.py` and `node_bench.mjs` (Ink Bench), `e2e_bench.py` and `e2e_scrolls.py` (end to end), `api.mjs`, `embed.mjs`, `coverage.mjs` and `pack_bin.mjs`; how to run them is in the Space. This repository's `python -m kit releases check` (run by the tests) checks only the README entry.

## History

- 2026-10-24: 1.6.0 on the Space (from Space commit `e31bb23`): Connect your tool in the Embed sheet, `connect.json` and `CONNECT.md`; spec in this repository's `spaces/connect/unroll/`.
- 2026-10-16: release entry and guide updated to version 1.5.0, its other scrolls and the CT tools (`b0913b4`).
- 2026-10-16: Install app link, offline app since 1.1.0 (`cf72eb1`, PR #98).
- 2026-10-16: ink-layer wording: "candidates for expert reading" (`628f14f`, PR #97).
- 2026-10-16: Apache 2.0 for all code, version 1.0.0 (`b0aad0e`).
- 2026-10-16: listed as a released tool in the README (`9896827`). Every version is in the Space's [CHANGELOG.md](https://huggingface.co/spaces/SharpMeow/unroll/blob/main/CHANGELOG.md).

## Related

- [`docs/unroll-space.md`](../unroll-space.md): the guide: layers, scrolls, CT tools, controls, Install app and credits.
- [autopipeline](autopipeline.md): the released pipeline that makes surfaces and ink maps from a scan, for runs Unroll only shows.
- [auc](auc.md): scoring against human ink labels with the reversed control, which Ink Bench does not do.
- [quickstart-wip](quickstart-wip.md): an unreviewed guide whose first score uses Ink Bench.
- [releases](releases.md): how the README's "Released tools" entry for Unroll is kept.
