# view: one offline HTML page that overlays several ink maps and the labels

`python -m kit view` writes one self-contained HTML file (no server, no network) that shows several readers' ink maps of one crop, percentile ranked so different scales compare, with their disagreement, the label outline and the mask, plus a JSON summary.

| Field | Value |
| --- | --- |
| Id | `view` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Viewers and apps |
| Run | `python -m kit view`, `from kit import viewer` |
| Code | `kit/viewer.py`, `kit/cli.py` (`cmd_view`), `kit/verify.py` (`load_map`, `_numpy`, `VerifyError`), `kit/auc.py` (`score_array`) |
| Tests | `tests/test_phantom.py` (class `ViewerTest`) |
| Needs | Python 3.10 or newer, numpy; tifffile for `.tif` maps (imagecodecs too for LZW or zstd TIFFs). A web browser with JavaScript to open the page; nothing else |
| Runs on | Any CPU. Two 256 x 256 maps take about 1 s; three full-size 5,980 x 8,240 float32 maps with labels and mask take about 11 s and 765 MB peak memory (measured 2026-10-16, 4-core Xeon cloud container under load from other jobs, synthetic data) |
| Network | None. The page loads nothing: every image is a PNG data URI inside the file |
| Writes | `OUT.html` (overwritten if it exists); with `--png PNG`, that PNG file. Prints a JSON summary to stdout |
| Go-ahead | Not needed to build a page. Posting or sending the page to anyone is an outward action that needs Chase's yes (the go-ahead rule, hard rule 8), and a page built from a target-scroll map is never shared or committed (the no-findings rule, hard rule 1) |
| Released | Public `main` since 2026-10-07 ([PR #13](https://github.com/ChaseHendrick/Scrolls/pull/13)); since 2026-10-14 also in the `scrolls-workbench` package installed from this repository, as `scrolls-workbench view` |
| Guide | [phantom-and-viewer.md](../phantom-and-viewer.md) (the phantoms and this viewer), [the phantom and viewer demo log](../logs/2026-10-07-phantom-demo.md) |
| Checked | 2026-10-17 against commit `a6beee7` |

## What it does

Several ink readers (models that write an ink map, such as `ink_9um`, v8in or a fine-tune) can be run on the same crop of the same segment. Their maps come on different scales: probabilities, logits, 0 to 255 images. Laying them side by side by hand hides where they agree and where they do not. `kit view` puts them on one page.

Each map becomes a percentile rank: every valid pixel gets its rank among the valid pixels of that map, from 0 (lowest) to 1 (highest), with ties sharing their average rank. Ranks make readers on different scales directly comparable, and they keep the order that an AUC depends on. The page then offers one reader at a time, an overlay of the disagreement between readers (the per-pixel standard deviation of their ranks) or of one reader minus the first, the outline of the ink labels, and the supervision mask (the region where the labels are trusted). Moving the cursor reads out each reader's rank and the scaled disagreement at that pixel (see Outputs). The summary goes to stdout as JSON: rank correlations between readers, the mean disagreement, and, when labels are given, each reader's AUC on the view. `--png` writes the panels side by side for a record that needs no browser.

The file is one HTML document with every layer embedded as a PNG data URI and a few lines of inline JavaScript. It needs no server and contacts no host, so it can be opened from disk.

It does not score maps for a report. The view is subsampled to at most `--max-side` pixels per side, and its AUC has no interval; use [`auc`](auc.md) for numbers. It does not resample labels: give labels already on the maps' grid (see Inputs). What the page shows is model output, not a reading: the page header says "Model output, not a reading", and no letter is ever found or read by looking at it.

## When to use it

- Looking at where two or more readers agree and disagree on one crop of a labeled public segment, for example `ink_9um` against v8in on a PHerc0841 crop.
- Seeing a map next to its reverse-depth control: the control should look unlike the labels.
- Inspecting synthetic results, such as [`phantom`](phantom.md) detector maps, where the truth is known.
- Making one PNG of several maps with the label outline for a log.

Do not use it:

- To report a score: use [`auc`](auc.md), with the reverse-depth control and `--bootstrap`.
- To measure whether two maps agree pixel for pixel (CPU against GPU, say): use [`verify`](verify.md) or [`overlap`](overlap.md).
- To browse a whole scroll or traced surfaces in 3D: use [Unroll](unroll.md), the released 3D viewer.
- On target-scroll maps for anything that leaves the machine: such pages stay private (the no-findings rule in [`AGENTS.md`](../../AGENTS.md)).

## Quick start

Fully offline, on a synthetic phantom (a made-up papyrus volume with known ink, from [`phantom`](phantom.md)):

```bash
python -m kit phantom make ph --shape 256 256 --depth 16 --seed 0 --letter-px 64
python -m kit phantom stress --n 1 --shape 256 256 --depth 16 --seed 0 --letter-px 64 --save-maps maps
python -m kit view viewer.html surface=maps/surface_0.npy reversed=maps/surface_reversed_0.npy \
    --labels ph/ink.npy --mask ph/mask.npy --png viewer.png
```

The second command writes the baseline detector's map and its depth-reversed control; the third overlays them. It printed (2026-10-16, synthetic data):

```
{
  "shape": [256, 256],
  "step": 1,
  "valid_px": 50176,
  "disagreement_mean": 0.2402,
  "rank_correlation": {"surface vs reversed": -0.8616},
  "auc_on_view": {"surface": 0.7377, "reversed": 0.312}
}
```

(JSON lines joined here for space.) `viewer.html` was 356 KB and `viewer.png` 780 x 256 px: three panels of 256 px (surface, reversed, disagreement) with 6 px gaps. It worked when the exit code is 0, the JSON is printed, and `viewer.html` opens in a browser with the reader menu, the overlay menu and the cursor readout. Here the map scores well above its reversed control (0.7377 against 0.312, the same numbers `kit phantom stress` printed for this phantom), so the label outline sits over bright ranks in the first panel and dark ones in the second.

On real maps of a labeled segment:

```bash
python -m kit view OUT.html A=MAP_A.tif B=MAP_B.tif A_rev=MAP_A_reverse.tif \
    --labels INK.npy --mask MASK.npy --title "TITLE" --png OUT.png
```

- `A=MAP_A.tif`: a reader's name, `=`, and its map (`.tif` or `.npy`). All maps must have the same shape and cover the same pixels.
- `INK.npy`, `MASK.npy`: the segment's ink labels and supervision mask already on the maps' grid. `kit.auc.labels_on_map` makes them from the published `inklabels.zarr` and `supervision.zarr` (see Inputs).
- `TITLE`: the page title.

## Checks and controls

- **Reverse-depth control as a reader.** Add the reverse-depth map (the same model run with the surface volume's layers in reverse order) as one of the maps. A reader that reads ink scores well above its reverse in `auc_on_view` and looks unlike it; one that follows brightness or texture looks the same both ways. On the Quick start phantom: 0.7377 forward against 0.312 reversed, rank correlation -0.8616 (Model output on synthetic data, 2026-10-16). The phantom demo log has four such phantoms ([log](../logs/2026-10-07-phantom-demo.md)).
- **`auc_on_view` is the map's own AUC on the view's pixels.** Ranks keep the map's order and ties, so the value equals `kit.auc.score_array` on the same subsampled valid pixels when the map has no near-ties that `kit auc` merges; `tests/test_phantom.py` checks equality for a constant and a 2-level map (0.5 for the constant map). It can differ from `kit auc` in two ways: the view is subsampled every `step` pixels, and `kit auc` rounds float maps to 65,536 levels, so a map whose values crowd near one end loses order there. On a synthetic probability map with 73 % of its pixels just above 0.001 (a [`fibertensor`](fibertensor.md) reversed map, 2026-10-16), `kit auc` gave 0.6959, while the viewer and the exact rank AUC both gave 0.6465.
- **Ties.** Tied values share their average rank, so a constant map scores 0.5 and has no rank correlation (`null`). Before the fix of 2026-10-07 (`d7f8725`), ties got increasing ranks and a constant map could show an AUC of 1; the demo log's viewer numbers and [`../assets/phantom-viewer-demo.png`](../assets/phantom-viewer-demo.png) predate that fix and are not evidence.
- **What can fail.** A reader whose `auc_on_view` is near its reverse's, or near 0.5, is not reading ink on this crop. A rank correlation near 1 between two readers says they agree, not that either is right.

Claim label: Model output, for every layer of the page and for `auc_on_view` and `rank_correlation`; what a person concludes from looking at the page is Interpretation.

## Commands and options

### `python -m kit view`

```
usage: python -m kit view [-h] [--labels LABELS] [--mask MASK] [--title TITLE]
                          [--max-side MAX_SIDE] [--png PNG]
                          out maps [maps ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | The HTML file to write. Its folder must exist; an existing file is overwritten |
| `maps` | required | One or more `NAME=PATH`: the reader's name, `=`, and its map (`.npy`, or any file tifffile reads). The text is split at the last `=`, so a path must not contain `=`; with no `=`, the name is the file name without its extension. Give each map a different name: the page finds layers by name, so a repeated name leaves one layer stuck on screen. All maps must have the same 2D shape |
| `--labels LABELS` | none | Ink labels on the maps' grid, same shape (`.npy` or TIFF); nonzero is ink. Draws the outline layer and adds `auc_on_view` |
| `--mask MASK` | none | Supervision mask on the maps' grid, same shape; nonzero is supervised. Without it, every pixel is supervised |
| `--title TITLE` | `Ink map viewer` | The page's title and heading (HTML escaped) |
| `--max-side MAX_SIDE` | `1024` | Largest side of the view in pixels (`MAX_SIDE`): the maps are subsampled every `ceil(max(H, W) / MAX_SIDE)` rows and columns. 0 crashes (see Failure modes); a negative value means no subsampling |
| `--png PNG` | none | Also write the panels side by side as a PNG. Its panels are subsampled to at most 384 px on their largest side (`render_png`'s default), whatever `--max-side` is |

## Python API

```python
import numpy as np
from kit import viewer
maps = [("a", viewer.load_array("a.npy")), ("b", viewer.load_array("b.tif"))]
page, stats = viewer.build_html(maps, labels=np.load("ink.npy"), mask=np.load("mask.npy"), title="a and b")
open("view.html", "w").write(page)
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `load_array(path)` | A 2D numpy array, singleton axes squeezed, dtype as stored | `VerifyError` when the result is not 2D, numpy or tifffile is missing, or a TIFF cannot be read; `FileNotFoundError` for a missing `.npy`; `ValueError` for a `.npy` of Python objects (pickles are not loaded) | `.npy` by suffix through `np.load`; every other suffix through tifffile (`kit.verify.load_map`) |
| `png_bytes(img)` | `bytes` of a PNG file | `KeyError` for a channel count other than 1, 3 or 4; `ValueError` for an array that is not 2D or 3D | Encodes uint8 `[h, w]` (gray) or `[h, w, 3 \| 4]` (RGB, RGBA) with the standard library (zlib level 6, no filter). Values are cast to uint8 without scaling, so give 0 to 255 |
| `rank01(np, a, valid)` | float64 array of `a`'s shape: each valid pixel's average rank scaled to 0..1, 0 elsewhere | Nothing of its own | Takes the numpy module as its first argument. NaN counts as valid and ranks above every number |
| `build_layers(maps, labels=None, mask=None, max_side=MAX_SIDE)` | `(layers, stats)`: `layers["readers"]` is a list of `(name, uint8 rank image)`; `"disagreement"` (uint8, two or more maps), `"labels"` (RGBA outline), `"labels_bool"` and `"mask"` (RGBA) when given; `stats` is the JSON under Outputs | `VerifyError` for no maps or shapes that differ; `ZeroDivisionError` for `max_side=0` | `maps` is a list of `(name, 2D array)` on one grid |
| `build_html(maps, labels=None, mask=None, title='Ink map viewer', max_side=MAX_SIDE)` | `(page, stats)`: the HTML as a str, and the stats dict | As `build_layers` | What the command writes. Reader names and the title are HTML escaped; names inside the script are JSON with `<` escaped, so a name cannot add a script element |
| `render_png(maps, labels=None, mask=None, max_side=384)` | `(rgb, stats)`: a uint8 `[h, w, 3]` array of the panels side by side, and the stats at that scale | As `build_layers` | One gray panel per reader, then the disagreement panel; 6 px dark gray gaps; label outline green; pixels outside the valid area dimmed to a third. Encode with `png_bytes` |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Maps | 2D `.npy` or TIFF, any numeric dtype | All the same shape, the same pixels of the same surface (a whole segment or the same crop). Only the order of values matters, so probabilities, logits and 0 to 255 images mix freely. Exactly 0 means "no prediction": a pixel where any map is 0 is left out for every map. NaN ranks above everything; replace it first |
| `--labels` | 2D `.npy` or TIFF, same shape as the maps | Nonzero is ink. Not resampled: it must already be on the maps' grid |
| `--mask` | 2D `.npy` or TIFF, same shape | Nonzero is supervised |

The published labels (`inklabels.zarr`, `supervision.zarr`) sit on the 2.4 um scan's grid, not the 9 um map grid. To put them on a map's grid, use the same nearest-neighbor lookup that `kit auc` uses and save the result (run on 2026-10-16 with synthetic stores):

```python
import numpy as np
from kit import auc
ink, sup = auc.labels_on_map("L/inklabels.zarr", "L/supervision.zarr", "2",
                             (H, W), [Y0, Y1, X0, X1], (Y1 - Y0, X1 - X0))
np.save("INK.npy", ink)
np.save("MASK.npy", sup)
```

`L` is the segment's label folder, `(H, W)` the full surface shape, and `[Y0, Y1, X0, X1]` the crop the maps cover (pass `None` and `(H, W)` for whole-segment maps). [`auc`](auc.md) lists the published crops and shapes.

## Outputs

`OUT.html`: one HTML file. It holds a heading with the title, the warning "Model output, not a reading. Readers are percentile ranked inside the mask.", the controls (reader menu, overlay menu with `none`, `disagreement` and `NAME minus FIRST` for every reader after the first, an opacity slider, and check boxes for labels and mask), the stacked layers, the cursor readout, and the stats JSON. Colors: a reader is gray (white is its highest rank); the disagreement overlay is red, more opaque where readers disagree more; `NAME minus FIRST` is blue where that reader ranks a pixel higher than the first reader and red where lower; the label outline is green; the mask darkens pixels outside the valid area. The cursor readout gives `x` and `y` in map pixels (view pixel times `step`, counted from the map's top-left corner, not the surface's), each reader's rank from 0 to 1, and a disagreement value. The disagreement readout is the overlay's alpha divided by 255: the per-pixel standard deviation scaled to the largest disagreement in this view, from 0 to 1, rounded to two decimals. It is independent of the opacity slider. It is not the unscaled `disagreement_mean`, an ink probability or an accuracy score. The page size grows with the view: 356 KB for two 256 x 256 maps, 6.4 MB for three 5,980 x 8,240 maps at the default `--max-side` (measured 2026-10-16).

With `--png`, a PNG of the panels side by side: one per reader, then the disagreement (red high, blue low) when there are two or more maps.

Stdout: the stats as JSON.

| Field | Type | Meaning |
| --- | --- | --- |
| `shape` | [int, int] | The maps' full shape, rows and columns |
| `step` | int | Subsampling step: the view keeps every `step`-th row and column |
| `valid_px` | int | View pixels inside the mask (all pixels without one) where every map is nonzero |
| `disagreement_mean` | float (4 decimals) or null | Mean over valid pixels of the per-pixel standard deviation of the readers' ranks (0 to 0.5); null when no pixel is valid. Only with two or more maps |
| `rank_correlation` | object | For every pair, key `"NAME1 vs NAME2"`: the correlation of their ranks over valid pixels (Spearman's rank correlation), 4 decimals, or null when fewer than 2 pixels are valid or a map is constant. Only with two or more maps |
| `auc_on_view` | object | Per reader name: its AUC against `--labels` on the valid view pixels, 4 decimals. Only with `--labels`, and only when the labels hold both ink and non-ink on valid pixels |

| Exit code | Meaning |
| --- | --- |
| `0` | The page (and the PNG) was written and the stats printed |
| `1` | An error the command does not catch, with a Python traceback: a missing `.npy` file, a missing output folder, or `--max-side 0` |
| `2` | Bad input, with the message on stderr (see Failure modes), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as no map after `OUT.html` | Check the command against Commands and options |
| `numpy is required. Run inside villa's environment: uv run --project "$VILLA/vesuvius" --extra models python -m kit verify ...` | numpy is not installed | `python -m pip install numpy`, or run inside villa's environment |
| `tifffile is required (it is in villa's environment)` | A map, labels or mask is not `.npy` and tifffile is missing | Install tifffile, or save the arrays as `.npy` |
| `cannot read PATH: ...`, exit code 2 | A non-`.npy` file that is missing, is not a TIFF (a PNG or JPEG goes to tifffile too), or is a compressed TIFF without imagecodecs | Fix the path; save the map as `.npy` or TIFF; install imagecodecs |
| `PATH: expected a 2D map, got shape (...)` | A TIFF with a layer stack or color channels | Pass one 2D map |
| `PATH: expected a 2D array, got (...)` | A `.npy` that is not 2D after squeezing | Pass one 2D array |
| `FileNotFoundError: ...` and a traceback, exit code 1 | A `.npy` path that does not exist, or an output folder that does not exist | Fix the path, or create the folder |
| `ValueError: Object arrays cannot be loaded when allow_pickle=False` and a traceback | A `.npy` holding Python objects | Save a numeric array |
| `give at least one map` | `build_layers` called with an empty list (the command always has at least one map) | Pass at least one `(name, array)` |
| `map NAME has shape (...), expected (...)` | A map from another surface or crop, or at another scale | Give maps of the same pixels |
| `labels shape (...) differs from the maps' (...)` | Labels not on the maps' grid, such as a level of `inklabels.zarr` saved as it is | Resample them with `kit.auc.labels_on_map` (see Inputs) |
| `mask shape (...) differs from the maps' (...)` | The same, for the mask | As above |
| `ZeroDivisionError: integer division or modulo by zero` and a traceback, exit code 1 | `--max-side 0` | Use a positive value; the default is 1024 |
| `inner N leaves nothing of a (...) map` | Not reachable from the viewer: it calls `score_array` with no edge left out | Nothing |
| The page always shows one reader, whatever the menu says | Two maps with the same name | Give every map its own name |
| An older HTML page shows `disagreement 1.00` almost everywhere | Pages generated before the 17 October 2026 fix read the red channel instead of alpha | Regenerate the HTML with the fixed viewer; existing HTML files contain their original script |
| No `auc_on_view` in the JSON | No `--labels`, or the labels hold only ink or only non-ink on the valid view pixels | Check the crop and the labels |

## How it works

1. Read every map with `load_array` (`.npy` by `np.load`, anything else by tifffile) and squeeze it to 2D; read the labels and mask the same way.
2. Refuse maps of different shapes, and labels or a mask of another shape.
3. Subsample: `step = ceil(max(H, W) / max_side)` (`_step`, `MAX_SIDE = 1024`), and keep every `step`-th row and column. There is no averaging, so thin strokes can fall between kept pixels at large steps.
4. Valid pixels: inside the mask (or all) and nonzero in every map.
5. Rank each map over the valid pixels (`rank01`): sort, give tied values their average position, divide by the count minus 1. Invalid pixels get 0. The rank times 255, rounded, is the reader's gray image.
6. With two or more maps: the disagreement is the per-pixel standard deviation of the ranks across readers (population, ddof 0), shown scaled so its largest valid value is 255; `disagreement_mean` is the unscaled mean over valid pixels; `rank_correlation` is `np.corrcoef` of each pair's ranks over valid pixels.
7. With labels: the outline is every label pixel with at least one of its four neighbors not labeled (computed with `np.roll`, which wraps, so a label touching one edge is compared with the opposite edge). `auc_on_view` scores each reader's rank, scaled to 1..65535, with `kit.auc.score_array` against the labels on the valid pixels.
8. With a mask: an RGBA layer that darkens every pixel outside the valid area (black at alpha 170).
9. Encode every layer as a PNG with `png_bytes` (standard library only) and embed it as a base64 data URI; fill the HTML template `PAGE`. The inline script switches layers, sets opacity, and reads pixels back from the layer images through a canvas. Reader ranks use the red channel; disagreement uses alpha. Both have 1/255 resolution before the readout rounds to two decimals.
10. With `--png`, `render_png` builds the same layers at a largest side of at most 384 px and joins the panels; the command writes it with `png_bytes`.

## Cost and time

Measured 2026-10-16 in a 4-core Intel Xeon cloud container (cpuinfo 2.80 GHz) that other jobs were loading at the time (load average about 20), so these are upper bounds:

| Run | Wall time | Peak memory | Files |
| --- | --- | --- | --- |
| Quick start: two 256 x 256 float maps, labels, mask, `--png` | 1.1 s | Not measured | 356 KB HTML, 245 KB PNG |
| Three 5,980 x 8,240 float32 maps (the size of PHerc0139 w045), labels, mask, `--png`, default `--max-side` (step 9, view 665 x 916) | 11.3 s | 765 MB | 6.4 MB HTML, 0.68 MB PNG (1518 x 272) |

Memory grows with the full maps, which are all loaded at once before subsampling. It runs on any machine; nothing here needs Modal or a GPU. On Chase's Mac, wrap a run in `python -m kit run local SLUG -- COMMAND` so it reaches the compute ledger (the local compute rule in [`AGENTS.md`](../../AGENTS.md), [run-local](run-local.md)).

## For agents

- **Command:** `python -m kit view OUT.html A=MAP_A.tif B=MAP_B.tif --labels INK.npy --mask MASK.npy --png OUT.png`; the stats JSON goes to stdout, so redirect it (`> stats.json`) to keep it.
- **Parse:** stdout JSON: `step` and `valid_px` (what the view covers), `rank_correlation` (agreement between readers), `disagreement_mean`, and `auc_on_view` (present only with `--labels` holding both classes).
- **Rerun:** Safe; it reads its inputs only and overwrites `OUT.html` and the PNG.
- **Success:** Exit code 0 and `OUT.html` starting with `<!doctype html>`.
- **Not a pass:** `auc_on_view` as a reported score (subsampled view, no interval, and a control only if you added the reverse map as a reader); a high rank correlation taken as correctness; any number from a map of a segment the reader trained on taken as generalization.
- **Go-ahead:** Nothing to build a page locally. Posting or sending the HTML or PNG needs Chase's yes; a page made from a target-scroll map is never shared.
- **Never:** Commit or share a page or PNG made from target-scroll maps (the HTML embeds the maps); commit any map-bearing HTML to this repository (no maps in git); say a letter was found or read from what the page shows.

## Tests

```bash
python -m unittest tests.test_phantom -v
```

`ViewerTest` in that file checks the PNG encoder byte for byte, the warning in the page, `auc_on_view` for a good and a noise reader, the refusal of a map of another shape, average ranks for a constant and a 2-level map (AUC equal to `kit.auc.score_array`, 0.5 for the constant, a null rank correlation, JSON without NaN), that a hostile reader name cannot add a script element, that the stage keeps its size when the first reader is hidden, and the command line writing both files. The file's `PhantomTest` covers [`phantom`](phantom.md). The tests skip without numpy. With optional Node.js, the hover regression decodes the generated PNGs and executes the generated JavaScript with a small DOM/canvas fixture: disagreement must read 0.00, 0.71, 0.14 and 1.00 at fixed synthetic pixels, independent of overlay opacity. This regression fails with the old red-channel readout. A separate Chromium check on 17 October 2026 verified the same values in a real canvas. These checks use synthetic arrays, not real segment data.

## History

- 2026-10-17: disagreement hover values read the encoded alpha channel; intermediate values such as 0.71 no longer appear as 1.00. Regenerate older HTML files to pick up the fix (`a6beee7`).
- 2026-10-14: in the installable `scrolls-workbench` package, which runs it as `scrolls-workbench view` (`2582ab7`).
- 2026-10-07: tied values share their average rank (a constant map scored an AUC of 1 before, now 0.5), reader names in the inline script are escaped, and the stage keeps its size when the first reader is hidden; earlier viewer numbers in the demo log are marked historical (`d7f8725`).
- 2026-10-07: first version, with `kit phantom` and the demo ([PR #13](https://github.com/ChaseHendrick/Scrolls/pull/13), `eeacf6a`).

## Related

- [`phantom-and-viewer.md`](../phantom-and-viewer.md): the guide to this viewer and the phantoms.
- [`phantom`](phantom.md): synthetic volumes with known ink, the Quick start's data.
- [`auc`](auc.md): the score to report, with the reverse-depth control and intervals; also `kit.auc.labels_on_map`, which puts labels on a map's grid.
- [`verify`](verify.md) and [`overlap`](overlap.md): pixel agreement between two maps, with a control.
- [`fibertensor`](fibertensor.md): a retired CPU reader whose maps were the example of a map with crowded values.
- [`unroll`](unroll.md): the released 3D viewer, for traced surfaces rather than ink maps.
- [The phantom and viewer demo log](../logs/2026-10-07-phantom-demo.md): the first run's numbers (viewer numbers there predate the tie fix).
