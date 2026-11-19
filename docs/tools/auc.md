# auc: score an ink map against a segment's published labels

`python -m kit auc` gives the pixel AUC of a 2D ink map against a segment's `inklabels.zarr` inside its `supervision.zarr`, with the reverse-depth map as the control, block-bootstrap intervals, and a paired test of whether one map beats another.

| Field | Value |
| --- | --- |
| Id | `auc` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Scoring and controls |
| Run | `python -m kit auc`, `python -m kit.aucreport`, `from kit import auc, aucreport` |
| Code | `kit/auc.py`, `kit/aucreport.py`, `kit/cli.py` (`cmd_auc`), `kit/finite.py` (`stats`, `NonFinite`), `kit/verify.py` (`load_map`, `_numpy`, `VerifyError`), `kit/ledger.py` (`add_check`) |
| Tests | `tests/test_auc.py`, `tests/test_auc_bootstrap_exact.py`, `tests/test_aucreport.py`, `tests/test_scoring_guards.py` (`AucGuardsTest`) |
| Needs | Python 3.10 or newer, numpy, tifffile (imagecodecs for LZW or zstd TIFFs), zarr (3.x on Python 3.11 or newer; 2.x works for reading) |
| Runs on | Any CPU. A full-size 5,980 x 8,240 map takes about 5 s with a control and about 6 s with `--bootstrap 300` (measured 2026-10-16, 4-core 2.1 GHz Xeon cloud container, synthetic data) |
| Network | None |
| Writes | Nothing (prints only); `kit.aucreport` writes only the files named by `--plot`, `--curves` and `--out`. With `--slug SLUG`, appends one check to `experiments/SLUG/run.json` (or `ROOT/SLUG/run.json` with `--root`) |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07; also inside the AutoPipeline release |
| Guide | [STANDARDS.md](../STANDARDS.md) (how AUC is used here), [the overlap and baseline log](../logs/2026-10-07-overlap-and-baseline.md) (sampling noise) |
| Checked | 2026-11-19 against commit `b6ade72` |

## What it does

An ink model writes an ink map: one number per pixel of a flattened surface (a segment's 2D render, 9.366 um per pixel here), higher where the model thinks there is ink. For a few segments the Vesuvius Challenge publishes the ink that people marked by hand (`inklabels.zarr`) and the area where they marked both ink and non-ink (`supervision.zarr`). `kit auc` measures how well a map agrees with those labels. The AUC is the chance that a labeled ink pixel scores above a labeled non-ink pixel, counted only inside the supervision mask, with ties counted half. 1.0 is perfect and 0.5 is chance.

It also scores a control. The reverse-depth map is the same model run on the same surface volume with its layers in the opposite depth order: it sees the same brightness but not the ink in the order the model learned. A map that reads ink scores well above its reverse; a map that only follows brightness or texture scores about the same both ways. `--bootstrap` adds a 95 % interval by resampling 1 mm blocks of pixels, and `--compare` says whether one map is ahead of another beyond sampling noise on the same pixels.

On a labeled segment held out from the model, the score is a generalization number. The `held_out` key of [`results.json`](../results.json) says which segment is held out from which model: PHerc0841 is in the training data of none of `ink_9um`, v8in, d9v2 and Reader v2, but possibly in Hecate's ([log](../logs/2026-10-09-pherc0841-hecate.md)). On a segment the model trained on, the score only shows that the pipeline runs.

An AUC is a score against human labels, not a reading. It never means that letters were found.

## When to use it

- Ranking ink models, checkpoints or settings on a labeled segment held out from all of them.
- Checking that a new pipeline step did not break ink detection, with the reverse map as the control.
- Deciding whether a gap between two maps is real (`--compare`) before writing it down.

Do not use it:

- To judge letter shapes: pixel AUC rewards blur. Use [`hpscore`](hpscore.md), the letter-scale score.
- To compare two maps without labels: use [`verify`](verify.md) (agreement, with a control) or [`overlap`](overlap.md).
- On a segment with no published labels, such as a target scroll: there is nothing to score against, and target maps stay private (the no-findings rule in [`AGENTS.md`](../../AGENTS.md)).
- To claim generalization on PHerc0139 w035 (a training segment), or on w045 for `ink_9um` and its fine-tunes, which trained on its 2.4 um render ([log](../logs/2026-10-08-w045-not-held-out.md)).

## Quick start

```bash
# Labels and mask of PHerc0841 w00 from the open-data bucket. Their level 2 is the 9 um surface grid.
L=PHerc0841/segments/20260220213127-w00/ink-labels/2.403um-volume-20260319124803/20260918
python -m kit fetch "$L/inklabels.zarr" labels/inklabels.zarr --workers 8
python -m kit fetch "$L/supervision.zarr" labels/supervision.zarr --workers 8

python -m kit auc MAP.tif --control MAP_reverse.tif \
    --labels labels/inklabels.zarr --mask labels/supervision.zarr --bootstrap 300
```

- `MAP.tif`: an ink map of w00 on its 9.366 um surface grid (4,220 x 4,760 px). `scripts/mac-w045.sh` makes one with `scripts/v8in_run.py`, and the reverse map with `--reverse`; villa's inference writes one too.
- `MAP_reverse.tif`: the same model run with the surface volume's layers in reverse order.
- The bucket prefixes of the other labeled segments are in `scripts/mac-w045.sh`.

On a small synthetic map (600 x 800 px, made in the test style) it printed:

```
map    : AUC 0.8737 on 60000 ink and 238455 background px (1545 unpredicted px in the mask left out)
control: AUC 0.4992 on 59764 ink and 238997 background px (1239 unpredicted px in the mask left out)
map minus control: +0.3745 (near 0 means the model is not reading ink in this direction)
map AUC 95 % interval 0.8713 to 0.8758 (300 draws of 42 blocks of 107 px)
```

It worked when the exit code is 0 and both the map and the control show an AUC. The result means something only when the map is well above its control (see Checks and controls).

## Checks and controls

- **Reverse-depth control** (`--control`). The map must beat its reverse by a clear margin. Gate A in `kit/gate.py` reads "well below" as forward minus reverse of at least 0.10 (`MIN_GAP`) on every segment. The reverse is not always near 0.5: the 30 rows of `results` in `results.json` with a reversed score run from 0.33 to 0.73, most below 0.60, with `ink_9um` on PHerc0841 ag405 up to 0.67 and Reader v2 on w00 at 0.73. A forward AUC reported without its control is not a result here (the rule that every check must be able to fail, in `AGENTS.md`). The control file may not be the map's own file (exit code 2, since `521c648`); an identical copy under another name still scores, and its zero gap shows the control failing.
- **A real pass, for scale.** `ink_9um` seed 42 on the whole of PHerc0841 w00 scores 0.7479 as stored against 0.501 reversed (`results` in `results.json`, segment `0841-w00`, source [community scan log](../logs/2026-10-07-community-scan.md)).
- **Sampling noise** (`--bootstrap`, `--compare`). A difference whose 95 % interval includes 0 is "not distinguishable from noise", whatever its size. On PHerc0841 a strong map's interval is plus or minus 0.01 to 0.04 ([log](../logs/2026-10-07-overlap-and-baseline.md)), so a ranking by a smaller margin on one segment is noise.
- **Held-out data.** The score generalizes only on a segment outside the model's training data; check the `held_out` key of `results.json` first.

Claim label: Model output, scored against the organizers' published labels of 2026-09-18; report it with the segment, the model, the control and the interval.

## Commands and options

### `python -m kit auc`

```
usage: python -m kit auc [-h] --labels LABELS --mask MASK [--control CONTROL]
                         [--level LEVEL] [--crop Y0 Y1 X0 X1]
                         [--surface-shape H W] [--keep-zero] [--inner PX]
                         [--bootstrap N] [--block-px BLOCK_PX] [--compare MAP]
                         [--seed SEED] [--json] [--slug SLUG] [--name NAME]
                         [--root ROOT]
                         prediction
```

| Option | Default | Meaning |
| --- | --- | --- |
| `prediction` | required | The ink map: a 2D `.tif` (read with tifffile) or `.npy`, on the 9 um surface grid. Singleton axes are squeezed |
| `--labels LABELS` | required | The segment's `inklabels.zarr`: a group with pyramid levels, or a single 2D array |
| `--mask MASK` | required | The segment's `supervision.zarr`, same layout and shape as the labels at `--level` |
| `--control CONTROL` | none | The reverse-depth map of the same surface, same shape as the map |
| `--level LEVEL` | `2` | Pyramid level of the labels that matches the 9 um grid (`DEFAULT_LEVEL`) |
| `--crop Y0 Y1 X0 X1` | none | The map covers only this window of the surface: rows Y0 to Y1 and columns X0 to X1, ends excluded |
| `--surface-shape H W` | none (the map's own shape) | The full surface's shape in pixels; required with `--crop` |
| `--keep-zero` | off | Count pixels where the map is exactly 0; by default they are left out as unpredicted |
| `--inner PX` | `0` | Leave out PX pixels at every edge of the map, for maps inferred on a cropped input (the crops here use 64) |
| `--bootstrap N` | `0` | Block-bootstrap draws for a 95 % interval; 0 for none; at least 20; 300 is plenty |
| `--block-px BLOCK_PX` | `107` | Side of a bootstrap block in pixels (`BLOCK_PX`, 1 mm at 9.366 um) |
| `--compare MAP` | none | A second map of the same surface: the difference, its interval and how often the first map is not ahead. Uses 300 draws when `--bootstrap` is 0 |
| `--seed SEED` | `0` | Seed of the bootstrap draws; the same seed gives the same interval |
| `--json` | off | Print the result as JSON (the fields under Outputs) instead of text |
| `--slug SLUG` | none | Attach the result as a check to the experiment SLUG in the ledger ([run-ledger](run-ledger.md)) |
| `--name NAME` | `label-auc` | Name of that check |
| `--root ROOT` | `experiments` | Ledger folder (`ledger.DEFAULT_ROOT`) |

### `python -m kit.aucreport score`

```
usage: python -m kit.aucreport score [-h] --labels LABELS --mask MASK
                                     [--control CONTROL] [--compare MAP]
                                     [--level LEVEL] [--crop Y0 Y1 X0 X1]
                                     [--surface-shape H W]
                                     [--label-offset DY DX]
                                     [--exclude Y0 Y1 X0 X1]
                                     [--exclude-margin PX] [--keep-zero]
                                     [--inner PX] [--bootstrap N]
                                     [--block-px BLOCK_PX] [--tiles PX]
                                     [--tile-min-px TILE_MIN_PX] [--null N]
                                     [--null-min-shift PX] [--offset-scan R]
                                     [--offset-step PX] [--points POINTS]
                                     [--seed SEED] [--plot FILE.svg]
                                     [--curves FILE.csv] [--out FILE.json]
                                     [--json]
                                     prediction
```

| Option | Default | Meaning |
| --- | --- | --- |
| `prediction` | required | The ink map, as for `kit auc` |
| `--labels LABELS` | required | The segment's `inklabels.zarr` |
| `--mask MASK` | required | The segment's `supervision.zarr` |
| `--control CONTROL` | none | Reverse-depth map of the same surface; adds its curves and the paired map minus control interval |
| `--compare MAP` | none | Another map of the same surface: its curves, and the paired difference on shared pixels (300 draws when `--bootstrap` is 0, as in `kit auc`). Its numbers are tagged `[no control of its own]`: score it alone with its own `--control` |
| `--level LEVEL` | `2` | Label pyramid level matching the 9 um grid |
| `--crop Y0 Y1 X0 X1` | none | The map covers only this window of the surface |
| `--surface-shape H W` | none (the map's own shape) | Full surface shape; required with `--crop` |
| `--label-offset DY DX` | none | Move the labels: label[y, x] = labels[y - dy, x - dx]; the vacated edge leaves the supervision |
| `--exclude Y0 Y1 X0 X1` | none | Remove this box of the surface grid from the supervision; repeat for more boxes |
| `--exclude-margin PX` | `0` | Grow every exclusion box by PX on each side |
| `--keep-zero` | off | Count pixels where a map is exactly 0 |
| `--inner PX` | `0` | Leave out PX pixels at every edge |
| `--bootstrap N` | `300` | Block-bootstrap draws for the map's interval and the paired map minus control (and compared map) intervals; 0 for none |
| `--block-px BLOCK_PX` | `107` | Bootstrap block side, and the default shortest null shift |
| `--tiles PX` | `534` | Tile side for the per-region AUC (5 mm at 9.366 um); 0 for none |
| `--tile-min-px TILE_MIN_PX` | `200` | Pixels of each class a tile needs to be scored |
| `--null N` | `200` | Shifted-label null draws; 0 for none; at least 20 |
| `--null-min-shift PX` | the block size | Shortest cyclic shift on at least one axis |
| `--offset-scan R` | `0` | Score every label offset within R px; 0 for none |
| `--offset-step PX` | `1` | Step of the offset grid |
| `--points POINTS` | `101` | Points per curve in the JSON, CSV and SVG |
| `--seed SEED` | `0` | Seed of the bootstrap and null draws |
| `--plot FILE.svg` | none | Write the ROC and precision-recall panels as SVG; an uncontrolled report prints its warning on the plot and marks each legend number `[uncontrolled]` |
| `--curves FILE.csv` | none | Write the curve points as CSV (`map,curve,x,y`) |
| `--out FILE.json` | none | Write the full report as JSON |
| `--json` | off | Print the report as JSON instead of text |

### `python -m kit.aucreport pool`

```
usage: python -m kit.aucreport pool [-h] [--seed SEED] [--json]
                                    reports [reports ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `reports` | required | Report JSON files from `score --out` (or `kit auc --json` output), one per segment |
| `--seed SEED` | `0` | Seed of the bootstrap over segments |
| `--json` | off | Print the pooled result as JSON |

### `python -m kit.aucreport demo`

```
usage: python -m kit.aucreport demo [-h] [--keep-zero] [--inner PX]
                                    [--bootstrap N] [--block-px BLOCK_PX]
                                    [--tiles PX] [--tile-min-px TILE_MIN_PX]
                                    [--null N] [--null-min-shift PX]
                                    [--offset-scan R] [--offset-step PX]
                                    [--points POINTS] [--seed SEED]
                                    [--plot FILE.svg] [--curves FILE.csv]
                                    [--out FILE.json] [--json]
```

The same report on synthetic data (text-like strokes, a map that reads them through noise, and a weak reverse map): nothing to download.

| Option | Default | Meaning |
| --- | --- | --- |
| `--keep-zero` | off | Count pixels where a map is exactly 0 |
| `--inner PX` | `0` | Leave out PX pixels at every edge |
| `--bootstrap N` | `300` | Block-bootstrap draws for the map's interval and the paired map minus control (and compared map) intervals; 0 for none |
| `--block-px BLOCK_PX` | `107` | Bootstrap block side, and the default shortest null shift |
| `--tiles PX` | `534` | Tile side for the per-region AUC (5 mm at 9.366 um); 0 for none |
| `--tile-min-px TILE_MIN_PX` | `200` | Pixels of each class a tile needs to be scored |
| `--null N` | `200` | Shifted-label null draws; 0 for none; at least 20 |
| `--null-min-shift PX` | the block size | Shortest cyclic shift on at least one axis |
| `--offset-scan R` | `0` | Score every label offset within R px; 0 for none |
| `--offset-step PX` | `1` | Step of the offset grid |
| `--points POINTS` | `101` | Points per curve in the JSON, CSV and SVG |
| `--seed SEED` | `0` | Seed of the bootstrap and null draws |
| `--plot FILE.svg` | none | Write the ROC and precision-recall panels as SVG; an uncontrolled report prints its warning on the plot and marks each legend number `[uncontrolled]` |
| `--curves FILE.csv` | none | Write the curve points as CSV (`map,curve,x,y`) |
| `--out FILE.json` | none | Write the full report as JSON |
| `--json` | off | Print the report as JSON instead of text |

## Detailed report: `python -m kit.aucreport`

One AUC answers "does the map rank ink above background here?". The report answers the questions that usually follow, on exactly the pixels `kit auc` scores: its `map.auc` is the number `kit auc` prints, from the same function. Try it without any data first:

```bash
python -m kit.aucreport demo --plot demo.svg          # synthetic strokes, a map that reads them and its reverse
```

On a real segment (PHerc0841 w00 from the Quick start):

```bash
python -m kit.aucreport score w00_prediction.tif --control w00_reverse.tif \
    --labels w00/inklabels.zarr --mask w00/supervision.zarr \
    --plot w00_roc_pr.svg --curves w00_curves.csv --out w00_report.json
python -m kit.aucreport pool w00_report.json ag896_report.json ag405_report.json
```

| Section | What it says | Why it matters |
| --- | --- | --- |
| Curves | ROC and precision-recall curves (101 points each, also as CSV and SVG), average precision (AP), true-positive rate at 1, 5 and 10 % false positives, best F1 and the Youden threshold | Ink is a minority class (often 10 to 30 % of supervised pixels). AP is judged against the ink share, which is what a map with no skill scores; the TPR at low false-positive rates says how clean a binarized map would be |
| Ties | Share of ink and background pairs that tie, and the AUC with every tie lost or won | A uint8 or thresholded map has few levels; its AUC can move by half the tied share depending on a convention |
| Tiles | AUC of each square tile (`--tiles`, default 534 px, 5 mm) holding at least `--tile-min-px` of each class, with min, quartiles, max and the worst tile | One strong patch can carry a segment's AUC while another region fails |
| Shifted-label null | The labels (ink and supervision together) shifted cyclically inside their bounding box by at least one block (`--null-min-shift`, default 107 px), `--null` times (default 200); the map is scored on each copy | A baseline that keeps the texture of the map and of the labels and breaks only their alignment; it never replaces the reverse-depth control. p = (1 + copies at or above the real AUC) / (1 + copies). It can fail: a map that only follows brightness or a sheet texture shared with the labels' layout scores high on the shifted copies too |
| Offset scan | `--offset-scan R`: the AUC with the labels moved by every (dy, dx) within R px (`--offset-step`) | A peak away from (0, 0) says the labels and the map are not registered. The best offset is picked on these labels, so it is a diagnosis, never a score: fix an offset first (`--label-offset`), then score it on other labels |
| Finite check | Every map goes through [`kit.finite`](finite.md) before scoring | A map holding NaN or Inf is refused with exit code 1 and the count of bad values |
| Pool | `pool` over reports (or `kit auc --json` files): per-segment rows, mean, range, ink-weighted mean, how many segments beat their control (by the shared-pixel gap), segments with no control marked uncontrolled, and from 5 segments on a bootstrap interval over segments | Segments differ more than pixels within one; with fewer than 5 the report says so instead of giving an interval |

Two options change which labels count, for every map scored: `--exclude Y0 Y1 X0 X1` (repeatable, surface grid, grown by `--exclude-margin`) removes a region already looked at, and `--label-offset DY DX` moves the labels, label[y, x] = labels[y - dy, x - dx], with the vacated edge left out (TAUIL-Abd-Elilah's label-shift convention). The report records both.

Options are under [Commands and options](#python--m-kitaucreport-score). `--json` prints the whole report; `--out` saves it. Main fields: `map.auc`, `map.curves.ap`, `map.curves.ink_share`, `map.curves.ties`, `controlled` and `warning` (false, and a warning, when no reverse-depth control scored, or the control ties at least 99 % of ink and background pairs on the shared pixels (`control_gap.control_tied_pair_share`), so it cannot fail: the text then marks every line `[uncontrolled]`), `compare.controlled` and `bootstrap.compare.other_controlled` (always false: the compared map has no control of its own), `control_gap.difference` (map minus control, each scored exactly on the pixels both maps scored, with `control_gap.auc_map_shared`, `auc_control_shared` and `shared_px`) and `control_gap.ci95` (its paired block-bootstrap interval), `bootstrap.ci95`, `tiles.median`, `tiles.worst`, `null.p`, `null.null_95th`, `offset_scan.best`. Exit codes: 0 scored, 1 a map is not finite, 2 bad input.

Cost: on a 5,980 x 8,240 map with a 1,280 x 1,280 labeled area and a control, about 4 s for the scores and curves, plus about 2.5 s for 300 bootstrap draws and about 2 s for 200 null draws (2026-11-19, cloud container, synthetic data). The null and the scan work inside the labels' bounding box, so they grow with the labeled area, not the map.


## Python API

```python
from kit import auc
result = auc.score_files("MAP.tif", "inklabels.zarr", "supervision.zarr", control="MAP_reverse.tif")
print(auc.format_result(result))
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `score_files(prediction, labels, mask, control=None, level=DEFAULT_LEVEL, crop=None, surface_shape=None, keep_zero=False, inner=0, bootstrap=0, block_px=BLOCK_PX, compare=None, seed=0)` | The result dict under Outputs | `VerifyError` on bad input, including NaN or inf in a map and a control that is the map's own file; `FileNotFoundError` for a missing `.npy` | What the command runs. `crop` is `[Y0, Y1, X0, X1]` and `surface_shape` is `[H, W]` |
| `score_array(prediction, ink, mask, keep_zero=False, inner=0)` | `{"auc", "ink_px", "background_px", "zero_px_in_mask", "zero_px_counted", "inner"}` | `VerifyError` when `inner` leaves nothing, or for NaN or inf in the map | A map against same-shape boolean ink and mask arrays already on its grid. `auc` is rounded to 4 decimals, or `None` |
| `auc_scores(ink_scores, background_scores)` | float, or `None` when a class is empty | `VerifyError` for NaN or inf scores | Mann-Whitney AUC with ties half, exact on 65,536 integer levels. Scores that are not int64 are quantized together first |
| `block_bootstrap(prediction, ink, mask, draws=300, block_px=BLOCK_PX, seed=0, other=None, keep_zero=False, inner=0)` | The `bootstrap` dict under Outputs | `VerifyError` for fewer than 20 draws, a block under 1 px, a compared map of another shape, NaN or inf in a map, or a mask with one class | The same pixels and the same draws for both maps when `other` is given |
| `labels_on_map(labels, mask, level, surface_shape, crop, map_shape)` | `(ink, supervised)` boolean arrays of `map_shape` | `VerifyError` for unreadable stores, a missing level, or labels and mask of different shapes | Labels resampled onto the map's grid by nearest neighbor |
| `label_grid(labels_shape, surface_shape, crop, map_shape)` | `(rows, cols)` integer index arrays into the labels | `VerifyError` for a scale that differs between axes, a crop outside the surface, or a crop that does not match the map | The nearest-neighbor lookup `labels_on_map` uses |
| `format_result(result)` | str | Nothing | The text the command prints |

`kit.aucreport` (`from kit import aucreport`):

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `score_files(prediction, labels, mask, control=None, compare=None, level="2", crop=None, surface_shape=None, keep_zero=False, inner=0, offset=None, exclude=None, exclude_margin=0, **kw)` | The report dict | `VerifyError`, `finite.NonFinite` | What `score` runs; `kw` are `report_arrays`'s options |
| `report_arrays(pred, ink, sup, control=None, compare=None, keep_zero=False, inner=0, bootstrap=300, block_px=107, tiles=534, tile_min_px=200, null=200, null_min_shift=None, scan=0, scan_step=1, points=101, seed=0, origin=(0, 0))` | The report dict | `VerifyError`, `finite.NonFinite` | Arrays already on the map's grid |
| `labels_on_map(labels, mask, level, surface_shape, crop, map_shape, offset=(0, 0))` | `(ink, supervised)` | `VerifyError` | As `auc.labels_on_map`, with a label offset |
| `exclude_boxes(ink, sup, boxes, surface_shape, crop=None, margin=0)` | `(mask, record)` | `VerifyError` | Removes boxes from the supervision |
| `control_gap(pred, control, ink, sup, keep_zero=False)` | The `control_gap` dict | Nothing of its own | Map minus control on the pixels both scored; `sup` already without its edge |
| `curve_stats(a, b, points=101)` | The `curves` dict, or `None` when a class is empty | Nothing | From per-level counts of ink (`a`) and background (`b`); a bare AUC and AP: pair it with the control's, or label it uncontrolled |
| `tile_breakdown(q, ink, use, tile_px=534, min_px=200, origin=(0, 0))` | The `tiles` dict | `VerifyError` for tiles under 8 px | `q` is the quantized map; bare AUCs: pair them with the control's, or label them uncontrolled |
| `shift_null(q, ink, sup, valid, draws=200, min_shift=107, seed=0, min_px=50)` | The `null` dict | `VerifyError` | Cyclic shifts inside the labels' bounding box; a baseline, never the control: pair it with one |
| `offset_scan(q, ink, sup, valid, radius, step=1, min_px=50)` | The `offset_scan` dict | `VerifyError` | Diagnosis only; bare AUCs with no control |
| `pool(reports, draws=2000, seed=0)` | The pooled dict, with `controlled` false and a `warning` when any segment has no control | `VerifyError` for a file with no map AUC | `reports` is a list of `(name, dict)` |
| `write_svg(report, path, title=None)`, `write_curves_csv(report, path)` | None | `OSError` | The plot and the curve points |
| `format_report(report)`, `format_pool(pooled)` | str | Nothing | The text the commands print |
| `demo_arrays(seed=0, shape=(640, 640))` | `(pred, reverse, ink, sup)` | Nothing | The demo's synthetic data |
| `main(argv=None)` | Exit code | Nothing | The command line |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Ink map | 2D TIFF (any dtype tifffile reads) or `.npy` | uint8 and uint16 are scored as they are. Other dtypes are scaled once for the whole map to 0..65535 levels. A map whose values all lie in 0..65535 is read as 0..1, or as 0..255 when its maximum is above 1 and at most 255, or as 0..65535 when it is above 255. A map with a value below 0 or above 65535 (logits, signed values), or one whose scaled values fall on fewer than 256 levels (`MIN_FLOAT_LEVELS`), is stretched from its own minimum to its maximum instead, which keeps every pixel's rank; a constant map outside 0..65535 ties everywhere. NaN or infinite values anywhere in the map are refused. Exactly 0 in the raw map means "no prediction" unless `--keep-zero` |
| Labels | zarr: a group whose key `--level` is a 2D array, or one 2D array | Greater than 0 is ink |
| Mask | zarr, same layout and shape as the labels | Greater than 0 is supervised |
| Control and compared maps | Same formats, same shape as the map | |

The labels sit on the 2.4 um scan's grid; their level 2 is the 9 um surface grid up to a uniform scale (w045: 5,820 x 8,020 labels for 5,980 x 8,240 surface pixels). Each map pixel takes the label at the nearest scaled position. A scale that differs between the two axes by more than 0.5 % (`MAX_AXIS_MISMATCH = 0.005`) is refused, because then the two are not the same grid.

## Outputs

Text by default (see Quick start). With `--json`, one object:

| Field | Type | Meaning |
| --- | --- | --- |
| `forward.auc` | float (4 decimals) or null | AUC of the map; null when no ink or no background pixel is left to score |
| `forward.ink_px`, `forward.background_px` | int | Pixels scored in each class |
| `forward.zero_px_in_mask` | int | Pixels in the mask (after `--inner`) where the map is exactly 0 |
| `forward.zero_px_counted` | bool | Whether those were scored (`--keep-zero`) |
| `forward.inner` | int | Edge left out, in pixels |
| `control` | object, the same fields | Only with `--control` |
| `files` | object | `prediction`, `labels`, `mask` and `control` (null without one) as given, and `compare` with `--compare` |
| `level` | str | Label level used |
| `crop` | list of 4 int, or null | The window, as given |
| `bootstrap.draws`, `bootstrap.block_px`, `bootstrap.blocks`, `bootstrap.seed` | int | Only with `--bootstrap` or `--compare`; `blocks` is the number of blocks that hold scored pixels |
| `bootstrap.ci95` | [float, float] | 95 % interval of the map's AUC (2.5 and 97.5 percentiles of the draws) |
| `bootstrap.half_width` | float | Half the interval's width |
| `bootstrap.compare.auc_map`, `.auc_other`, `.difference` | float | Both AUCs on the shared pixels, and map minus other |
| `bootstrap.compare.ci95` | [float, float] | 95 % interval of the difference |
| `bootstrap.compare.share_draws_map_not_ahead` | float | Share of draws in which the map is not ahead |
| `bootstrap.compare.pixels` | int | Shared pixels scored (zeros of either map left out) |

With `--slug`, the same object is stored as the check's result in `run.json` ([run-ledger](run-ledger.md)).

| Exit code | Meaning |
| --- | --- |
| `0` | Scored. An AUC can still be null: check `forward.auc` |
| `1` | An error the command does not catch, with a Python traceback, such as a missing `.npy` file (`FileNotFoundError`) |
| `2` | Bad input, with the message on stderr (see Failure modes), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `numpy is required for python -m kit auc. Install the maps extra: python -m pip install "scrolls-workbench[maps]", or run inside villa's environment: uv run --project "$VILLA/vesuvius" --extra models python -m kit auc ...` | numpy is not installed | Install the maps extra, or run inside villa's environment, as the message says |
| `tifffile is required for python -m kit auc. Install the maps extra: ...` (the rest as for numpy) | tifffile is missing | The same; imagecodecs, in the maps extra, reads compressed TIFFs |
| `zarr is required for python -m kit auc. Install the maps extra (its zarr needs Python 3.11 or newer): ...` | zarr is missing | The same, on Python 3.11 or newer |
| `the map holds N NaN or infinite values; replace them (with 0 for no prediction) before scoring` | The map, control or compared map has NaN or inf anywhere, which has no rank | Replace them with 0, which is left out as unpredicted, or fix the run that wrote them |
| `control CONTROL is the map itself; give the reverse-depth map as the control` | `--control` names the map's own file (the same file, also through another path or a link) | Give the reverse-depth map |
| `cannot read MAP.tif: ...` | An unreadable TIFF, or a compressed one without imagecodecs | Install imagecodecs, or save the map as `.npy` |
| `MAP: expected a 2D map, got shape (...)` | A layer stack or an RGB image | Pass one 2D map |
| `FileNotFoundError: ...` and a traceback, exit code 1 | A `.npy` path that does not exist | Fix the path |
| `cannot open PATH as zarr: ...` | A wrong path, or not a zarr store | Point `--labels` and `--mask` at the `.zarr` folders |
| `PATH: no level '2'; levels: [...]` | The store has other level keys | Pick the level that matches the 9 um grid with `--level` |
| `labels (...) and mask (...) differ in shape at level 2` | Labels and mask from different segments or levels | Use the pair from the same segment |
| `labels (...) and surface (...) differ in scale between axes (SY vs SX); they are not the same grid` | The map is not on this segment's surface grid, or `--surface-shape` is wrong | Check the map's segment and the full surface shape |
| `a cropped map needs the full surface shape (surface_shape)` | `--crop` without `--surface-shape` | Add `--surface-shape H W` |
| `crop [...] is outside the H x W surface` | A crop larger than the surface | Fix the crop |
| `map shape (...) does not match the window h x w` | The crop does not match the map's size | Give the window the map was cut from |
| `control shape (...) differs from the map's (...)` | A control from another surface or crop | Use the reverse map of the same surface and crop |
| `compared map shape (...) differs from the map's (...)` | `--compare` map from another surface or crop | Use a map of the same surface and crop |
| `inner N leaves nothing of a (...) map` | `--inner` at least half the map's shorter side | Use a smaller `--inner` |
| `use at least 20 bootstrap draws` | `--bootstrap` from 1 to 19 | Use 300 |
| `block size must be at least 1 px` | `--block-px` 0 or less | Use the default 107 |
| `no supervised pixels to resample` | Nothing left in the mask after the crop, `--inner` and zeros | Check the crop and the mask |
| `the mask holds only one class; no AUC to resample` | No ink or no background pixels left to bootstrap | Check the crop; the crops here are the 640 px windows of densest ink |
| `no experiment at ROOT/SLUG/run.json` | `--slug` names an experiment that was never started | Start it with `python -m kit run init`, or fix `--slug` and `--root` |
| `map: no AUC (ink 0 px, background N px in the mask)`, exit code 0 | No labeled ink (or no background) inside the scored area | Check the crop and `--inner` |
| `MAP: NNN NaN, NNN Inf; kit auc scores no map holding NaN or Inf (replace them with 0 for no prediction)`, exit code 1 (`kit.aucreport`) | `kit.finite` found NaN or Inf in a map | Replace them with 0, or fix the run that wrote them |
| `not a numeric array (dtype ...): nothing to check` (`kit.aucreport`) | A map that is not numbers | Pass a numeric map |
| `no AUC: ink N px, background N px in the mask` (`kit.aucreport`) | No ink or no background left after the crop, exclusions and zeros | Check the crop and the boxes |
| `label offset [DY, DX] moves the labels off the surface` | `--label-offset` at least the surface size | Use a small offset |
| `the exclusion margin cannot be negative`, `an exclusion margin needs at least one exclusion box` | A bad `--exclude-margin` | Give a margin of 0 or more with at least one `--exclude` |
| `exclusion box [...] is empty: give y0 y1 x0 x1 with y0 < y1, x0 < x1`, `exclusion box [...] lies outside the H x W surface` | A box in the wrong order or off the surface | Give y0 y1 x0 x1 on the surface grid |
| `tiles must be at least 8 px` | `--tiles` from 1 to 7 | Use the default 534 or 0 for none |
| `no supervised pixels left to score` | The mask is empty after the crop and exclusions | Check the crop and the boxes |
| `use at least 20 null draws` | `--null` from 1 to 19 | Use 200, or 0 for none |
| `the labeled area (h x w px) is too small for shifts of at least N px; lower --null-min-shift or switch the null off` | The labels' bounding box is under twice the shortest shift on both axes | Lower `--null-min-shift` (not below the size of an ink stroke) or use `--null 0` |
| `only N shifted copies kept enough labeled pixels on the map; the null needs 20` | Most shifts land the labels on unpredicted (zero) pixels | Score the map with `--keep-zero`, or a map that covers the labeled area |
| `the offset scan needs a radius and a step of at least 1 px`, `no offset kept enough labeled pixels on the map` | A bad `--offset-scan` or `--offset-step`, or labels mostly off the map | Use a radius of a few pixels and a step of 1 or 2 |
| `FILE: no map AUC in this file` (`pool`) | A JSON without `map.auc` or `forward.auc` | Pool `score --out` files or `kit auc --json` output |

## How it works

1. Load the map and squeeze it to 2D, then open the labels and mask at `--level`.
2. Map every map pixel to a label pixel by nearest neighbor on the scaled grid (`label_grid`), inside `--crop` when given.
3. Quantize the whole map once to integers (`_quantize`), so ink and background pixels are on one scale: uint8 and uint16 as they are; a float map in 0..65535 by its known scale (0..1, 0..255 or 0..65535, from its maximum); a map outside that range, or one that would fall on fewer than `MIN_FLOAT_LEVELS` = 256 levels, stretched from its minimum to its maximum onto 0..65535. NaN or inf is refused.
4. Keep pixels inside the mask, minus exact zeros (unless `--keep-zero`) and minus `--inner` pixels at each edge.
5. Count the AUC: histogram ink and background scores on 65,536 levels and count, for each ink pixel, the background pixels below it plus half the ties (`auc_scores`). This equals the pairwise Mann-Whitney definition exactly, which `tests/test_auc_bootstrap_exact.py` checks.
6. Bootstrap (`block_bootstrap`): cut the scored pixels into square blocks of `--block-px`, draw blocks with replacement N times from a seeded numpy generator, and recompute the AUC of each draw from 1,024-bin block histograms (`BOOT_BINS`). The 2.5 and 97.5 percentiles are the interval. With `--compare`, both maps use the same pixels (zeros of either map left out) and the same draws, so the interval is of the paired difference.

The point estimates (`forward.auc`, `control.auc`) are exact. The resampled AUCs, and so the intervals and the compare AUCs, come from the 1,024 bins and can differ from the exact value in the third or fourth decimal.

Why blocks: neighboring pixels are not independent, and a segment's labels cover about 1 cm2 (PHerc0841: 0.9 to 1.4 cm2 each), so a per-pixel bootstrap would give intervals that are far too narrow.

## Cost and time

Measured 2026-10-16 in a 4-core 2.1 GHz Xeon cloud container, on a synthetic map the size of PHerc0139 w045 (5,980 x 8,240, uint8) with level-2 labels of 5,820 x 8,020: 4.8 s with `--control`, 5.8 s with `--bootstrap 300`, 5.0 s with `--compare`. Peak memory was about 1.1 GB with `--control` at that size. It runs on any machine; nothing here needs Modal or a GPU. `kit.aucreport` on the same map size with a 1,280 x 1,280 labeled area and a control: about 4 s for scores and curves, 6.5 s with 300 bootstrap draws, 5.7 s with 200 null draws, 6.6 s with an 8 px offset scan (measured 2026-11-19, cloud container, synthetic data); the defaults together take about 11 s.

## For agents

- **Command:** `python -m kit auc MAP.tif --control MAP_reverse.tif --labels L/inklabels.zarr --mask L/supervision.zarr --json`; on a crop add `--crop Y0 Y1 X0 X1 --surface-shape H W --inner 64`; for an interval add `--bootstrap 300`.
- **Parse:** `forward.auc` and `control.auc`, and with `--bootstrap` or `--compare`, `bootstrap.ci95` and `bootstrap.compare.ci95`.
- **Detail:** `python -m kit.aucreport score ... --json` for curves, AP, ties, tiles and the shifted-label null (fields under Detailed report); `pool` over the per-segment reports (pool `kit.aucreport` reports rather than `kit auc --json` files when a control may be near constant: only they carry the tie check). Report AP with `curves.ink_share` beside it, and never an offset-scan best as a score.
- **Rerun:** Safe; it only reads its inputs. With `--slug`, each run appends one more check to `run.json`.
- **Success:** Exit code 0 and a non-null `forward.auc`.
- **Not a pass:** A forward AUC without its control; a map less than 0.10 above its control; a ranking whose `--compare` interval includes 0; any score on a segment the model trained on.
- **Go-ahead:** Nothing for scoring. Publishing any score of a target-scroll map is never allowed; score only public labeled segments in public work.
- **Never:** Call an AUC a reading or say letters were found; call a score on w035, or on w045 for `ink_9um` and its fine-tunes, a generalization result.

## Tests

```bash
python -m unittest tests.test_auc tests.test_auc_bootstrap_exact tests.test_scoring_guards.AucGuardsTest tests.test_aucreport -v
```

They cover the AUC against the pairwise definition, ties, float and uint16 maps, a forward map that reads ink and a reverse that does not, crops lining up with the full map, unpredicted zeros, `--inner`, the refusals (crop outside, missing store, a scale that differs between axes, crop without shape), the command line, and the bootstrap against a per-pixel oracle with quantization, zeros and partial blocks. `AucGuardsTest` checks that maps with a tiny range, negative values or logits keep their ranks, a constant map outside the known scale ties, maps already on a known scale quantize as before, NaN and inf are refused, and the map cannot be its own control. `tests/test_aucreport.py` (34 tests) checks that the ROC area equals the Mann-Whitney AUC and AP matches a brute-force step sum with ties, the tie bounds of a constant map, that the report's AUC is `kit auc`'s on files and arrays, the NaN and Inf refusals (exit 1), tiles finding a half where the map is inverted, a null that passes a reading map and fails a noise map, a planted label offset found by the scan, exclusion boxes (also on a crop) and offsets with their vacated edge, the map refused as its own control, `--keep-zero` in the curves, the null and `--inner`, the control gap's sign, shared pixels and paired interval, an all-zero control, every uncontrolled number labeled (report, pool lines, pool JSON and plot), a constant or near-constant control counted as no control (also after pooling), the compared map tagged as having no control of its own, `--keep-zero` in the gap, the verdict against each interval, `--compare` always getting its interval, the SVG and CSV files, and pooling. They skip without numpy, tifffile and zarr. They do not run on real segment data.

## History

- 2026-11-19: `kit.aucreport pool` keeps each report's `controlled` flag and takes the mean gap from controlled segments only, and a control tying at least 99 % of pairs counts as no control ([#372](https://github.com/ChaseHendrick/Scrolls/pull/372)).
- 2026-11-19: `kit.aucreport --plot` prints the uncontrolled warning on the SVG and tags its legend, `pool --json` carries `controlled`, a constant control counts as none, `--compare` numbers are tagged `[no control of its own]`, and the verdict names a control ahead beyond noise ([#371](https://github.com/ChaseHendrick/Scrolls/pull/371)).
- 2026-11-19: `kit.aucreport` labels every number scored without a reverse-depth control `[uncontrolled]`, takes map minus control on the pixels both maps scored, survives an all-zero control and gives `--compare` its interval with `--bootstrap 0` ([#370](https://github.com/ChaseHendrick/Scrolls/pull/370)).
- 2026-11-19: `python -m kit.aucreport`: ROC and precision-recall curves, AP, tie bounds, per-tile AUCs, a shifted-label null, a label offset scan, `--exclude` and `--label-offset`, the finite check, segment pooling and SVG and CSV output; `kit auc` itself is unchanged ([#369](https://github.com/ChaseHendrick/Scrolls/pull/369)).
- 2026-10-16: a missing numpy, tifffile or zarr names the command run and the maps extra (`bb8cc06`).
- 2026-10-16: a constant float map outside 0..65535 ties everywhere (AUC 0.5) instead of crashing (`136b5b2`).
- 2026-10-16: only the map's own file is refused as its control; an identical copy scores and shows no gap (`0f3afea`).
- 2026-10-16: NaN and inf are refused, float maps outside 0..65535 or on fewer than 256 levels are stretched min to max so ranks are kept, and the map cannot be its own control (`521c648`).
- 2026-10-09: the module text gives the PHerc0841 held-out wording for Hecate (`3ba683f`).
- 2026-10-08: the module text says w045 is not held out from `ink_9um`, which trained on its 2.4 um render (`d841e06`).
- 2026-10-07: a faster exact block bootstrap with the same outputs (`fda744f`, [production speed log](../logs/2026-10-07-production-speed.md)).
- 2026-10-07: `--bootstrap`, `--compare` and `--block-px` added (`25070df`, [overlap and baseline log](../logs/2026-10-07-overlap-and-baseline.md)).
- 2026-10-07: review fixes, and QUICK mode in `scripts/mac-w045.sh` scores on the crop only (`cdc08bc`).
- 2026-10-07: first version, with the reverse-depth control, `--crop`, `--inner` and the zero rule (`1caa69e`).

## Related

- [`hpscore`](hpscore.md): the letter-scale score, which rewards blur less than pixel AUC.
- [`verify`](verify.md): agreement of two maps, such as CPU against MPS, with a control.
- [`gate`](gate.md): Gate A, which ranks readers by these AUCs on PHerc0841's crops.
- [`layers`](layers.md): writes the depth-shuffle control and the layer TIFFs models read.
- [`run-ledger`](run-ledger.md): the experiment ledger that `--slug` writes to.
- [`results.json`](../results.json): every AUC reported here, with its settings and source; `held_out` says which segment is held out from which model.
