# hpscore: letter-scale score of an ink map against a segment's labels

`python -m kit hpscore` correlates an ink map with a segment's published ink labels after removing a 48 um blur from both, so strokes count and blobs do not, with a rolled-label null and an optional reverse-depth control.

| Field | Value |
| --- | --- |
| Id | `hpscore` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Scoring and controls |
| Run | `python -m kit hpscore`, `from kit import hpscore` |
| Code | `kit/hpscore.py`, `kit/cli.py` (`cmd_hpscore`), `kit/auc.py` (`_load`, `_levels`, `labels_on_map`, `label_grid`), `kit/verify.py` (`load_map`, `_numpy`, `VerifyError`), `kit/layers.py` (`_zarr`), `kit/ledger.py` (`add_check`, `load`, `path_for`) |
| Tests | `tests/test_hpscore.py`, `tests/test_hpscore_reuse.py`, `tests/test_toolreg_reports.py` |
| Needs | Python 3.10 or newer, numpy, scipy (`scipy.ndimage`), tifffile (imagecodecs for LZW or zstd TIFFs), zarr (3.x on Python 3.11 or newer). The `maps` extra of `pyproject.toml` installs all of them |
| Runs on | Any CPU. A 640 px crop with its control takes about 0.6 s as a fresh command; a 2,560 px crop about 8 s ([production scaling log](../logs/2026-10-07-production-scaling.md), one core). A full segment has not been measured |
| Network | None |
| Writes | Nothing (prints only). With `--slug SLUG`, appends one check to `experiments/SLUG/run.json` (or `ROOT/SLUG/run.json` with `--root`) |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07 |
| Guide | [STANDARDS.md](../STANDARDS.md) (where the letter-scale score sits among the measures), [tricks.md](../tricks.md) (where it came from and what it measured) |
| Checked | 2026-10-21 against commit `8721373` |

## What it does

An ink model writes an ink map: one number per pixel of a flattened surface, higher where the model thinks there is ink. Pixel AUC ([`auc`](auc.md)) asks whether labeled ink pixels score above labeled non-ink pixels. It cannot tell a map that draws letters from a map that paints a soft blob over a line of text: both put high values on the ink pixels, and blurring a map often raises its AUC. `kit hpscore` gives the letter-scale score, a number that rewards strokes and edges at the size of letters and does not reward blobs.

It works like this. Both the map and the key (the human ink labels: 1 for ink, 0 for non-ink, inside the supervision mask) are high-passed: each has its own 48 um Gaussian blur subtracted, so only detail finer than about 48 um is left. The score `hp_r` is the Pearson correlation of the two high-passed images over the pixels that are labeled, predicted, and have a fully labeled neighborhood. The same correlation without the high pass is reported as `raw_r`. The method is a port of Chris Scheirer's `hp_score.py` and `score_crop.py` (ShribyrLabs/vesuvius-reports, report 02, MIT).

Every result carries a null: the key is rolled 150, 300 and -300 px (at 9.362 um, about 1.4 and 2.8 mm) along the rows, the correlation is recomputed, and the largest absolute value is `null_max_abs`. It says how much a key that is in the wrong place still scores. With `--control`, the reverse-depth map (the same model run with the surface volume's layers in reverse order) is scored on the same label fields.

Scheirer's key is the team's 2.4 um prediction; this tool's key is the segment's human labels. So these numbers are on a different scale from his report and compare only with each other, on the same pixels and at the same blur. A blur raises this score too (his 2026-09-25 caveat), so compare maps made the same way. There is no pass bar ([STANDARDS.md](../STANDARDS.md)).

The score is a correlation against human labels, not a reading. A high `hp_r` never means letters were found; an ink map is model output.

## When to use it

- Next to `kit auc`, to see whether a gain in pixel AUC is a gain in letter-scale detail or only more blur, as with depth sharpening, which raised AUC by 0.018 to 0.062 on PHerc0841 but letter-scale r by only 0.002 to 0.004 (Bullo27's measurement, a Community report in [tricks.md](../tricks.md)).
- Ranking settings or checkpoints of one reader on a labeled crop held out from it, at the same blur.
- Checking that a map's detail sits on the labels: forward above the reverse control and above the rolled-key null.

Do not use it:

- As a legibility verdict or a pass bar: no mapping from this score to legibility is known. Look at the map, and use [`strokenet`](strokenet.md) or the letter tools only as further evidence.
- To compare with ShribyrLabs' published numbers (0.076, 0.11 to 0.14): their key is a model prediction, ours is human labels.
- To compare two maps without labels: use [`verify`](verify.md).
- On a segment with no published labels, such as a target scroll: there is nothing to correlate with, and target maps stay private (the no-findings rule in [`AGENTS.md`](../../AGENTS.md)).
- For a generalization claim on a segment the model trained on (PHerc0139 w035, or w045 for `ink_9um` and its fine-tunes; [log](../logs/2026-10-08-w045-not-held-out.md)). Check the `held_out` key of [`results.json`](../results.json) first.

## Quick start

```bash
# Labels and mask of PHerc0841 w00 from the open-data bucket. Their level 2 is the 9 um surface grid.
L=PHerc0841/segments/20260220213127-w00/ink-labels/2.403um-volume-20260319124803/20260918
python -m kit fetch "$L/inklabels.zarr" labels/inklabels.zarr --workers 8
python -m kit fetch "$L/supervision.zarr" labels/supervision.zarr --workers 8

python -m kit hpscore MAP.tif --control MAP_reverse.tif \
    --labels labels/inklabels.zarr --mask labels/supervision.zarr --voxel-um 9.366
```

- `MAP.tif`: an ink map of w00 on its 9.366 um surface grid (4,220 x 4,760 px), with values above 0 wherever it predicted. `scripts/mac-w045.sh` makes one (and its reverse) with `scripts/v8in_run.py`; villa's inference writes one too.
- `MAP_reverse.tif`: the same model run with the surface volume's layers in reverse order.
- For a map of the 640 px crop `scripts/mac-w045.sh` uses, add `--crop 2624 3264 2688 3328 --surface-shape 4220 4760 --inner 64` (the other segments' crops are in that script's `SEGMENT` block).

On synthetic data (labels of 900 short strokes on a 585 x 780 level-2 grid, a 600 x 800 map of those strokes plus noise, and a noise map as the control) it printed, in 1.2 s:

```
map    : letter-scale r +0.7792 (raw r +0.7978, rolled-key null |r| <= 0.0034) on 423600 px
control: letter-scale r -0.0002 (raw r -0.0007, rolled-key null |r| <= 0.0016) on 423600 px
```

The same strokes blurred with a 12 px Gaussian scored `letter-scale r +0.0672 (raw r +0.1933, ...)`: the blur lost most of the letter-scale score while keeping some raw correlation, which is the point of the tool.

It worked when the exit code is 0 and the map line shows a letter-scale r. The number means something only when it is above the control's and above the rolled-key null (see Checks and controls).

## Checks and controls

- **Rolled-key null** (always on). `null_max_abs` is the largest |r| of the high-passed map against the key rolled by 150, 300 and -300 px. A forward `hp_r` at or below it is not distinguishable from a misplaced key.
- **Reverse-depth control** (`--control`). The forward map's `hp_r` must sit above its reverse's. A score reported without the control is not a result here (the rule that every check must be able to fail, in [`AGENTS.md`](../../AGENTS.md)).
- **A real fail.** d9v2 on a fixed labeled crop of PHerc0139 w045 (a surface `ink_9um`, and so d9v2, trained on at 2.4 um) scored forward `hp_r` 0.0177, below its reverse 0.0214 and the null 0.0578, while its AUC was 0.9255 forward against 0.3346 reversed. The log's verdict: "The fine-detail check failed" ([follow-up log](../logs/2026-10-07-followup-tests.md); `followup_checks` in [`results.json`](../results.json), kind `labelled_reader_baseline`). So the score can fail where AUC passes.
- **Real values on PHerc0841 w00's crop** (64 px edge left out): `ink_9um` seed 42 +0.029, d9v2 +0.015, Reader v2 +0.048; depth-shuffled inputs -0.011 to +0.002 ([tricks tables](../../scripts/experiments/2026-10-07-cloud/tricks/tables.md)). These are small numbers, and on ag896 several `ink_9um` variants were below 0.
- **Scheirer's scale, for orientation only** (Community report, different key): noise 0.01, blobs 0.04, a map where a person made out four letters 0.076, the best 9 um maps 0.11 to 0.14, run-to-run noise 0.005 ([report 02](https://github.com/ShribyrLabs/vesuvius-reports/tree/main/02-9um-ink-reader-benchmark)). The report's own correction says the four-letter case sits on a scroll in the base model's training data.
- **No interval.** The command gives no bootstrap; the follow-up runs used their own harness for `hp_bootstrap` intervals. A difference between two maps on one crop is not shown to be beyond noise by this command alone.

Claim label: Model output, a correlation of an ink map with the organizers' published labels; report it with the segment, crop, model, the control's `hp_r` and `null_max_abs`. Scheirer's reference values are a Community report.

## Commands and options

### `python -m kit hpscore`

```
usage: python -m kit hpscore [-h] --labels LABELS --mask MASK
                             --voxel-um VOXEL_UM [--control CONTROL]
                             [--level LEVEL] [--crop Y0 Y1 X0 X1]
                             [--surface-shape H W] [--inner PX] [--json]
                             [--slug SLUG] [--name NAME] [--root ROOT]
                             prediction
```

| Option | Default | Meaning |
| --- | --- | --- |
| `prediction` | required | The ink map: a `.npy` file (read with numpy) or anything else read as a TIFF with tifffile, squeezed to 2D, on the segment's surface grid. Pixels at or below 0 count as unpredicted |
| `--labels LABELS` | required | The segment's `inklabels.zarr`: a group with pyramid levels, or a single 2D array. Values above 0 are ink |
| `--mask MASK` | required | The segment's `supervision.zarr`, same layout and shape as the labels at `--level`. Values above 0 are supervised |
| `--voxel-um VOXEL_UM` | required | The map's pixel size in micrometers (9.362 for PHerc0139, 9.366 for PHerc0841). It sets the blur, sigma = 48 / VOXEL_UM px, and scales the null shifts. It is not checked: 0 crashes with `ZeroDivisionError`, and a negative value gives no score |
| `--control CONTROL` | none | The reverse-depth map of the same surface, same shape as the map, scored on the same label fields |
| `--level LEVEL` | `2` | Pyramid level of the labels that matches the 9 um grid (`auc.DEFAULT_LEVEL`) |
| `--crop Y0 Y1 X0 X1` | none | The map covers only this window of the surface: rows Y0 to Y1 and columns X0 to X1, ends excluded. Needs `--surface-shape` |
| `--surface-shape H W` | none (the map's own shape) | The full surface's shape in pixels; required with `--crop` |
| `--inner PX` | `0` | Leave out PX pixels at every edge of the map, for maps inferred on a cropped input (the crops here use 64) |
| `--json` | off | Print the result as JSON (the fields under Outputs) instead of text |
| `--slug SLUG` | none | Attach the result as a check to the experiment SLUG in the ledger ([run-ledger](run-ledger.md)); the experiment must exist |
| `--name NAME` | `letter-scale` | Name of that check in `run.json` |
| `--root ROOT` | `experiments` | Ledger folder (`ledger.DEFAULT_ROOT`) |

Unlike `kit auc`, there is no `--keep-zero`: pixels at or below 0 are always left out, and there is no `--bootstrap`.

## Python API

```python
from kit import hpscore
result = hpscore.score_files("MAP.tif", "inklabels.zarr", "supervision.zarr", 9.366, control="MAP_reverse.tif")
print(hpscore.format_result(result))
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `score_files(prediction, labels, mask, voxel_um, control=None, level=DEFAULT_LEVEL, crop=None, surface_shape=None, inner=0)` | The result dict under Outputs | `VerifyError` on bad input or without scipy; `FileNotFoundError` for a missing `.npy`; `ZeroDivisionError` for `voxel_um` 0 | What the command runs. `crop` is `[Y0, Y1, X0, X1]`, `surface_shape` is `[H, W]`. The label fields are filtered once per call and shared by the map and the control; nothing is cached between calls |
| `score_array(prediction, ink, supervised, voxel_um, inner=0)` | `{"hp_r", "raw_r", "null_max_abs", "px", "sigma_px", "inner"}` | `VerifyError` without numpy or scipy, or when `inner` leaves nothing | A map against same-shape ink and supervision arrays already on its grid. Values outside `supervised` in `ink` are ignored, even NaN |
| `high_pass(np, gf, img, m, sigma)` | float array, `img` minus its Gaussian mean over the pixels where `m` is set | Nothing of its own | Normalized convolution: `img - gf(img * m, sigma) / max(gf(m, sigma), 1e-3)`. `np` is numpy and `gf` is `scipy.ndimage.gaussian_filter`. [`surfacefix`](surfacefix.md) imports it |
| `format_result(result)` | str | Nothing | The text the command prints |

`HIGH_PASS_UM = 48.0` and `NULL_SHIFTS_PX_AT_9362 = (150, 300, -300)` are the module's constants.

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Ink map | 2D TIFF (any dtype tifffile reads; imagecodecs for compressed ones) or `.npy` | Used as it is: Pearson r does not depend on scale, so uint8, uint16 and float maps score alike. Values at or below 0 are unpredicted and left out, so a map of logits loses every negative pixel: apply a sigmoid first. A single NaN spreads through the blur and makes `hp_r` and `null_max_abs` NaN: replace NaN with 0 first |
| Labels | zarr: a group whose key `--level` is a 2D array, or one 2D array | Greater than 0 is ink |
| Mask | zarr, same layout and shape as the labels | Greater than 0 is supervised |
| Control map | Same formats, same shape as the map | |

The labels sit on the 2.4 um scan's grid; their level 2 is the 9 um surface grid up to a uniform scale (PHerc0841: 0.975 of the surface grid on both axes). Each map pixel takes the label at the nearest scaled position (the same mapping as `kit auc`). A scale that differs between the two axes by more than 0.5 % (`auc.MAX_AXIS_MISMATCH = 0.005`) is refused.

The score needs labeled area around each scored pixel: only pixels whose 2 x sigma neighborhood (about 10 px at 9.366 um) is entirely supervised are scored, and the 300 px null shift wraps around inside the map, so a map much smaller than the 640 px crops scores few pixels.

## Outputs

Text by default (see Quick start): one line for the map and one for the control. A map with nothing to score prints `map    : no score (N px with a full 10 px labelled neighbourhood)`.

With `--json`, one object:

| Field | Type | Meaning |
| --- | --- | --- |
| `forward.hp_r` | float (4 decimals) or null | Pearson r of the high-passed map and key over the scored pixels; null with fewer than 3 pixels or a constant side |
| `forward.raw_r` | float (4 decimals) or null | The same correlation without the high pass |
| `forward.null_max_abs` | float (4 decimals) or null | Largest \|r\| of the high-passed map against the key rolled by each null shift; null when no shift could be scored |
| `forward.px` | int | Pixels scored: supervised with a fully supervised neighborhood, map above 0, inside `--inner` |
| `forward.sigma_px` | float (3 decimals) | The Gaussian sigma in map pixels, 48 / `voxel_um` |
| `forward.inner` | int | Edge left out, in pixels |
| `control` | object, the same fields | Only with `--control` |
| `voxel_um` | float | As given |
| `crop` | list of 4 int, or null | The window, as given |

The JSON has no `files` or `level` field, unlike `kit auc`. A NaN score is printed as `NaN`, which strict JSON parsers refuse. With `--slug`, the same object is stored as the check's `result` in `run.json`, with `at` (UTC time) and `name`.

| Exit code | Meaning |
| --- | --- |
| `0` | Scored. `hp_r` can still be null: check `forward.hp_r` |
| `1` | An error the command does not catch, with a Python traceback: a missing `.npy` file (`FileNotFoundError`) or `--voxel-um 0` (`ZeroDivisionError`) |
| `2` | Bad input, with the message on stderr (see Failure modes), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as no `--voxel-um` | Check the command against Commands and options |
| `scipy is required for kit hpscore` | scipy is not installed | `python -m pip install scipy`, or run inside villa's environment |
| `numpy is required. Run inside villa's environment: uv run --project "$VILLA/vesuvius" --extra models python -m kit verify ...` | numpy is not installed (the message names `kit verify`, whose loader this command shares) | `python -m pip install numpy tifffile zarr scipy` |
| `tifffile is required (it is in villa's environment)` | tifffile is missing | Install tifffile, and imagecodecs for compressed TIFFs |
| `zarr is required (it is in villa's environment)` | zarr is missing | Install zarr |
| `cannot read MAP.tif: ...` | A missing or unreadable TIFF, or a compressed one without imagecodecs | Fix the path, install imagecodecs, or save the map as `.npy` |
| `MAP: expected a 2D map, got shape (...)` | A layer stack or an RGB image | Pass one 2D map |
| `FileNotFoundError: ...` and a traceback, exit code 1 | A `.npy` path that does not exist | Fix the path |
| `cannot open PATH as zarr: ...` | A wrong path, or not a zarr store | Point `--labels` and `--mask` at the `.zarr` folders |
| `PATH: no level '2'; levels: [...]` | The store has other level keys | Pick the level that matches the 9 um grid with `--level` |
| `labels (...) and mask (...) differ in shape at level 2` | Labels and mask from different segments or levels | Use the pair from the same segment |
| `labels (...) and surface (...) differ in scale between axes (...); they are not the same grid` | The map is not on this segment's surface grid, or `--surface-shape` is wrong | Check the map's segment and the full surface shape |
| `a cropped map needs the full surface shape (surface_shape)` | `--crop` without `--surface-shape` | Add `--surface-shape H W` |
| `crop [...] is outside the H x W surface` | A crop larger than the surface | Fix the crop |
| `map shape (...) does not match the window h x w` | The crop does not match the map's size | Give the window the map was cut from |
| `control shape (...) differs from the map's (...)` | A control from another surface or crop | Use the reverse map of the same surface and crop |
| `inner N leaves nothing of a (...) map` | `--inner` at least half the map's shorter side | Use a smaller `--inner` |
| `no experiment at ROOT/SLUG/run.json` | `--slug` names an experiment that was never started | Start it with `python -m kit run init`, or fix `--slug` and `--root` |
| `bad slug: '...'` | A slug that is empty, holds `/` or starts with `.` | Use a plain name |
| `ZeroDivisionError: float division by zero` and a traceback, exit code 1 | `--voxel-um 0` | Give the map's real pixel size |
| `map    : no score (N px with a full 10 px labelled neighbourhood)`, exit code 0 | Fewer than 3 pixels to score, or a constant map or key there (a flat map gives this) | Check the map's values, the crop, `--inner` and that the mask holds both ink and background |
| `letter-scale r +nan (...)`, exit code 0 | A NaN in the map | Replace NaN with 0 (unpredicted) before scoring |

## How it works

1. Load the map (`.npy` with numpy, anything else with tifffile) and squeeze it to 2D; open the labels and mask at `--level`.
2. Map every map pixel to a label pixel by nearest neighbor on the scaled grid, inside `--crop` when given (`auc.labels_on_map`, as in `kit auc`).
3. Set sigma = `HIGH_PASS_UM` / `voxel_um` = 48 / `voxel_um` px (5.125 px at 9.366 um).
4. Prepare the label fields once per call (`_label_fields`): the key is the ink labels inside the mask and 0 elsewhere; its high pass `kh` uses the mask as the weight; the core is the mask pixels whose Gaussian-smoothed mask at 2 x sigma is above 0.999, that is, whose whole neighborhood is labeled.
5. For each map (the map, then the control): the covered pixels are those above 0; the scored pixels are the core and covered, minus `--inner` at each edge. The map's high pass uses the covered pixels as the weight, so unpredicted zeros do not leak into it.
6. `hp_r` is Pearson's r of the high-passed map and `kh` on the scored pixels; `raw_r` is Pearson's r of the map and the key there.
7. The null: each shift in `NULL_SHIFTS_PX_AT_9362` = (150, 300, -300) is scaled by 9.362 / `voxel_um` and rounded; the scored pixels and `kh` are rolled by it along the rows (axis 0, wrapping round), r is computed on the pixels scored in both, and `null_max_abs` is the largest |r|.

The high pass is a normalized convolution: `img - gf(img * m) / max(gf(m), 1e-3)`, where `gf` is `scipy.ndimage.gaussian_filter` (default reflect border, 4 sigma truncation). Published source: Chris Scheirer's `hp_score.py` and `score_crop.py` ([ShribyrLabs/vesuvius-reports, report 02](https://github.com/ShribyrLabs/vesuvius-reports/tree/main/02-9um-ink-reader-benchmark), MIT); our key is the human labels instead of his 2.4 um prediction.

## Cost and time

| Case | Time | Memory | Source |
| --- | --- | --- | --- |
| Real 640 px crop of PHerc0841 w00, d9v2 forward and reverse, fresh command | 0.60 s median | 88,600 KiB peak | [production scaling log](../logs/2026-10-07-production-scaling.md), 2026-10-07, one core |
| Public 2,560 px crop of the 2.403 um w00 map, two maps, fresh command | 7.95 s median | 525,868 KiB peak | same log ([HP report](../evidence/2026-10-07-production-scaling/hp/hp-review.md)) |
| Synthetic 600 x 800 map with a control | 1.2 s wall | Not measured | This page, 2026-10-16, 4-core Intel Xeon cloud container (lscpu: 2.80 GHz) shared with other jobs |
| Synthetic 2,560 x 2,560 map with a control | 31 s wall | 606 MB peak | Same machine and date, load average about 14 on 4 cores, so slower than the log's figure |

Time and memory grow with the map's pixel count: it runs seven Gaussian filters of the full map size with a control (ten before 2026-10-07's reuse change). A full 9 um segment (about 20 to 50 million pixels) has not been measured; the HP report says the 2,560 px crop "does not establish full 305-million-pixel canvas throughput or memory viability". The crops here run in seconds on any machine; nothing needs Modal or a GPU.

## Start from VC3D

Make the segment active, select its forward ink map in the Ink Detection overlay and pick Scrolls > segment > "Letter-scale score (hpscore) against the segment's labels". VC3D passes the segment, the map and the open volume; the tool registry ([toolreg](toolreg.md)) finds the reverse-depth twin (a `control:reverse` record, else `MAP_reverse` beside the map) and the labels and mask (ink detection records first, then villa's `SEG_inklabels.zarr` and `SEG_supervision_mask.zarr`). The entry's voxel size field is `auto`: the open volume's voxel size, or the one the parent VC3D's agent bridge reports; type it when the volume has none, or nothing runs. From a terminal or an agent:

```bash
python -m kit tools run hpscore --segment SEG --ink-overlay SEG/MAP.tif --volume VOL --out RUN
```

A score is a readout: in public Scrolls a prize-eligible scroll is refused.

## Open in VC3D

VC3D shows `RUN/hpscore.json` as the run's result file (Parse below), and `RUN/vc3d-result.json` carries the controls verdict (`no control: not a pass` without the twin). Nothing is drawn on the segment. hpscore checks a map against published labels; it is not an AutoPipeline (AP) stage.

## For agents

- **Command:** `python -m kit hpscore MAP.tif --control MAP_reverse.tif --labels L/inklabels.zarr --mask L/supervision.zarr --voxel-um 9.366 --json`; on a crop add `--crop Y0 Y1 X0 X1 --surface-shape H W --inner 64`.
- **Parse:** `forward.hp_r`, `forward.null_max_abs`, `control.hp_r`, and `forward.px` for how many pixels were scored. `raw_r` is for comparison only.
- **Rerun:** Safe; it only reads its inputs and gives the same numbers. With `--slug`, each run appends one more check to `run.json`.
- **Success:** Exit code 0 and a non-null, non-NaN `forward.hp_r`.
- **Not a pass:** A forward `hp_r` with no control; a forward `hp_r` at or below `control.hp_r` or `forward.null_max_abs`; a comparison of two maps made at different blur; any comparison with ShribyrLabs' numbers; a score on a segment the model trained on; a map of logits (negatives are left out).
- **Go-ahead:** Nothing for scoring. Publishing any score of a target-scroll map is never allowed; score only public labeled segments in public work.
- **Never:** Call a letter-scale score a reading or say letters were found; treat it as a legibility bar; pass a `--voxel-um` other than the map's pixel size.

## Tests

```bash
python -m unittest tests.test_hpscore tests.test_hpscore_reuse -v
```

Nine tests: a sharp map beats the same map blurred with a 12 px Gaussian by at least three times, noise scores near 0, unlabeled and unpredicted pixels and `--inner` are left out, a too-large `--inner` is refused, and an independent copy of the original per-map formula matches `score_files` and `score_array` field for field (with and without a control, with zero coverage, NaN outside the mask, an empty mask, changed labels and voxel size, a wrong-shape control), with the label filters computed once per call. They skip without numpy and scipy. They do not read real zarr stores or TIFFs (`score_files` is tested with its loaders patched), and they do not run the command line.

## History

- 2026-10-07: label-only filters computed once per call and shared by the map and the control, ten Gaussian filters down to seven, same outputs (`047ee06`, [production scaling log](../logs/2026-10-07-production-scaling.md)).
- 2026-10-07: first version, a port of Scheirer's `hp_score.py` with the rolled-key null and `--control` (`ebd4ae3`).

## Related

- [`auc`](auc.md): pixel AUC with the reverse control and bootstrap intervals; report both scores together.
- [`surfacefix`](surfacefix.md): reuses `high_pass` and the 48 um constant.
- [`strokenet`](strokenet.md): a learned score of how much a window looks like strokes.
- [`rowscore`](rowscore.md): text-row periodicity, the third ink-map measure here.
- [`run-ledger`](run-ledger.md): the experiment ledger that `--slug` writes to.
- [STANDARDS.md](../STANDARDS.md): how the letter-scale score relates to AUC and the row score, and that it has no bar.
- [tricks.md](../tricks.md) and the [tricks tables](../../scripts/experiments/2026-10-07-cloud/tricks/tables.md): letter-scale r of many readers and tricks on PHerc0841.
- [Follow-up log](../logs/2026-10-07-followup-tests.md) and `followup_checks` in [`results.json`](../results.json): the w045 case where the check failed.
