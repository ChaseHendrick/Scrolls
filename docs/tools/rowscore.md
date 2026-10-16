# rowscore: text-row periodicity triage score for ink maps

`python -m kit rowscore` measures how strongly an ink map repeats at a 2.5 to 8 mm period in one direction, as rows of Greek text do, for forward and reverse maps: a triage aid that says where to look first, not a verdict.

| Field | Value |
| --- | --- |
| Id | `rowscore` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Scoring and controls |
| Run | `python -m kit rowscore`, `from kit import rowscore` |
| Code | `kit/rowscore.py`, `kit/cli.py` (`cmd_rowscore`), `kit/verify.py` (`load_map`, `_numpy`, `VerifyError`), `kit/ledger.py` (`add_check`, `load`, `path_for`) |
| Tests | `tests/test_rowscore.py`, `tests/test_rowscore_fast.py` |
| Needs | Python 3.10 or newer, numpy, tifffile (imagecodecs for LZW or zstd TIFFs); scipy for the largest-piece step (skipped without it) and for `--fast-resize` |
| Runs on | Any CPU. A 305-million-pixel public map took 39.7 s, or 5.7 s with `--fast-resize` ([production scaling log](../logs/2026-10-07-production-scaling.md), one core); a 9 um segment takes seconds to under a minute |
| Network | None |
| Writes | Nothing (prints only). With `--slug SLUG`, appends one check to `experiments/SLUG/run.json` (or `ROOT/SLUG/run.json` with `--root`) |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07 |
| Guide | [rowscore.md](../rowscore.md) (the `--fast-resize` option and its numerical limits) |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

Greek text on the Herculaneum scrolls sits in rows a few millimetres apart. An ink map (one number per pixel of a flattened surface, higher where a model thinks there is ink) that shows text should therefore repeat with a period of 2.5 to 8 mm in one direction. `kit rowscore` measures that: it takes the power spectrum of the map and divides the strongest peak in the 2.5 to 8 mm band by the band's median power. A map of rows gives a strong peak and a high score; speckle or blobs give a flat band and a score near the noise level.

It scores the largest connected piece of the mapped surface, after shrinking the map four times and eroding the edges of holes. Several forward maps (such as two checkpoints of one model) are averaged before scoring, and so are the reverse maps given with `--reverse`, which are the control: the same model run with the surface volume's layers in reverse order should show no rows. Averaging raised the score on real text in Bullo27's tests (w045: 84 and 111 alone, 125 averaged; Community report).

It is a port of Bullo27's `analysis/rowscore.py` ([first-letters-survey](https://github.com/Bullo27/first-letters-survey), MIT, commit `a5f9c51`, read 2026-10-07). numpy reimplements OpenCV's area and nearest resizes, a box-sum erosion replaces `cv2.erode`, and `scipy.ndimage` finds the largest piece. It matched the original to float rounding on six synthetic maps ([community scan log](../logs/2026-10-07-community-scan.md)).

The score is a triage aid, not a verdict. A high score is a place to look, not ink; a low score on a small patch proves little, because small areas give unstable spectra. Bullo27's reference values (Community report, not checked here): PHerc0139 w045 and w033 score 73 to 148; 65 automatic patches on eligible scrolls score 2.5 to 33.5; 6 cm2 tiles of the controls score 6.8 to 77.4, which overlaps the negatives. The decision stays with a person looking at the map, and a row score is never a reading or a sign that letters were found.

## When to use it

- Ordering many maps or patches so the most row-like are looked at first. AutoPipeline's `triage` step names `method: rowscore` ([AutoPipeline README](../autopipeline/README.md)).
- A coarse forward-against-reverse structure check on a whole segment, next to [`auc`](auc.md).
- Averaging two checkpoints' maps before looking.

Do not use it:

- As evidence of text, letters or legibility, or with a pass bar: look at the map. There is no bar for this score ([STANDARDS.md](../STANDARDS.md)).
- On small patches. On PHerc0841 w00 no 0.25 cm2 window got a score, and from 0.5 to 4 cm2 the forward map did not rank above its reverse consistently ([thresholds notes](../../scripts/experiments/2026-10-07-cloud/thresholds/notes.md), Part 3).
- To score a map against human labels: use [`auc`](auc.md) and [`hpscore`](hpscore.md).
- To compare two maps of the same input on two devices: use [`verify`](verify.md).

## Quick start

```bash
python -m kit rowscore MAP_A.tif MAP_B.tif --reverse MAP_A_reverse.tif MAP_B_reverse.tif --voxel-um 9.362
```

- `MAP_A.tif`, `MAP_B.tif`: forward ink maps of one surface, such as `ink_9um` seeds 42 and 43 from villa's inference; one map is enough. They are averaged.
- `MAP_A_reverse.tif`, `MAP_B_reverse.tif`: the same models with the layers reversed (villa writes them with `--direction both`). They are averaged into the control.
- `--voxel-um 9.362`: the maps' pixel size in micrometres (9.362 for PHerc0139, 9.366 for PHerc0841).

On two synthetic 1,600 x 1,600 uint8 maps (letter-sized strokes placed only in rows 5 mm apart, under heavy noise) and a speckle map as the reverse, it printed:

```
forward: row score 320.2, period 4.99 mm at -90.0 deg, p99 1.0, 15.30% over 0.5
reverse: row score 6.8, period 4.15 mm at -146.3 deg, p99 0.669, 5.48% over 0.5
triage only: Bullo27 reports held-out controls at 73-148 and 6 cm2 control tiles as low as 6.8. Look at the map.
```

The two maps alone scored 144.8 and 115.3; their average scored higher because the noise averaged out. A synthetic map of perfect rows scores in the millions, since the score has no upper bound.

It worked when the exit code is 0 and the forward line shows a row score. It means something only next to its reverse, and only as an order in which to look (see Checks and controls).

## Checks and controls

- **Reverse maps** (`--reverse`). The forward score should be well above the reverse's. A forward score with no reverse is not a result here (the rule that every check must be able to fail, in [`AGENTS.md`](../../AGENTS.md)).
- **It can fail on real data.** `ink_9um` seed 42 on whole PHerc0841 segments, a scroll the model did not train on: w00 13.7 forward against 23.6 reversed (the reverse higher), ag896 17.5 against 8.8, ag405 46.4 (5.82 mm) against 7.5 (`results` in [`results.json`](../results.json), keys `row_score_as_stored` and `row_score_reversed`; [community scan log](../logs/2026-10-07-community-scan.md)).
- **On a training surface.** `ink_9um` on whole PHerc0139 w045: seed 42 79.8 (4.67 mm, horizontal) against 8.1 reversed, seed 43 68.3 against 10.6, both seeds averaged 95.9 against 9.5 (same sources). `ink_9um` trained on w045's 2.4 um render, so these show the pipeline runs, not that it generalizes ([log](../logs/2026-10-08-w045-not-held-out.md)).
- **Area.** On w00 with 200 random windows per size: 0.25 cm2 windows (534 px) got no score (band empty); at 0.5, 1, 2 and 4 cm2 only 4.5 %, 4.0 %, 10.0 % and 6.0 % of forward windows beat the reverse windows' 95th percentile. Among labelled windows, forward beat reverse on row score in 45.6 % (2 cm2) and 38.2 % (4 cm2) of pairs, while forward beat reverse on AUC in 97.4 % and 100 % ([thresholds notes](../../scripts/experiments/2026-10-07-cloud/thresholds/notes.md)).
- **`--fast-resize` parity.** On the two real public inputs of the speed test every historical field matched the dense default; other shapes differ by float32 rounding, and near-tied FFT peaks can change the period or angle ([rows report](../evidence/2026-10-07-production-scaling/rows/report.md)). Keep the default for exact reproduction.

Claim label: Model output, a triage order over ink maps; Bullo27's reference values quoted here are Community report.

## Commands and options

### `python -m kit rowscore`

```
usage: python -m kit rowscore [-h] [--fast-resize]
                              [--reverse REVERSE [REVERSE ...]]
                              --voxel-um VOXEL_UM [--json] [--slug SLUG]
                              [--name NAME] [--root ROOT]
                              forward [forward ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `forward` | required | One or more forward-direction maps (2D TIFFs of one shape). Several are averaged after each is scaled to 0 to 1, such as two checkpoints |
| `--reverse REVERSE ...` | none (an empty list) | One or more reverse-direction maps, averaged the same way and scored as the control. Their shape is not checked against the forward maps' |
| `--voxel-um VOXEL_UM` | required | The maps' pixel size in micrometres, such as 9.362. It sets the millimetre band and the reported period; a wrong value shifts both. It is not checked: 0 gives `band empty` |
| `--fast-resize` | off | Shrink with a sparse area resize (needs scipy) instead of the dense matrices: the same coefficients, much faster on large maps, but float32 rounding can differ and a near-tied peak can move. Adds `resize_mode` and `resize_note` to each direction and `fast_resize: true` to the result. A map with NaN keeps the dense path (`dense_nonfinite_fallback`); infinities are clipped to 0 or 1 first, so they do not |
| `--json` | off | Print the result as JSON (the fields under Outputs) instead of text |
| `--slug SLUG` | none | Attach the result as a check to the experiment SLUG in the ledger ([run-ledger](run-ledger.md)); the experiment must exist |
| `--name NAME` | `rowscore` | Name of that check in `run.json` |
| `--root ROOT` | `experiments` | Ledger folder (`ledger.DEFAULT_ROOT`) |

## Python API

```python
from kit import rowscore
result = rowscore.score_files(["MAP_A.tif", "MAP_B.tif"], 9.362, reverse=["MAP_A_reverse.tif"])
print(rowscore.format_result(result))
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `score_files(forward, voxel_um, reverse=(), *, fast_resize=False)` | The result dict under Outputs | `VerifyError` for a missing package, an unreadable or non-2D map, maps of different shapes within one direction, or `fast_resize` without scipy | What the command runs: the mean of the forward maps and, if given, the mean of the reverse maps |
| `score_array(array, voxel_um, valid=None, *, fast_resize=False)` | One direction's dict (`valid_px`, `largest_piece`, `score`, then `reason` or `period_mm`, `angle_deg`, `mean_ink`, `p99`, `frac_gt_half`; `resize_mode` and `resize_note` with `fast_resize`) | `VerifyError` without numpy, for an array that is not 2D (`expected a 2D map, got shape (...)`), or `fast_resize` without scipy | `valid` is a boolean mask of surface pixels; by default the scaled map above 0.01 |
| `mean_map(arrays)` | float32 array: the mean of the arrays after each is scaled to 0 to 1 | `VerifyError` when shapes differ (`maps to average differ in shape: [...]`) | |
| `format_result(result)` | str | Nothing | The text the command prints |

Constants: `DOWNSAMPLE = 4`, `ERODE_PX = 31`, `MIN_VALID_PX = 5000`, `MIN_BAND_BINS = 20`, `PERIOD_MM = (2.5, 8.0)`.

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Forward and reverse maps | 2D TIFF (squeezed), any dtype tifffile reads; no `.npy` | Each map is scaled to 0 to 1 as float32: divided by 255 when its maximum is above 1.5 and at most 255, by 65,535 when above 255, kept as it is otherwise. Maps within one direction must share a shape. A single NaN makes the score NaN (with a meaningless period and angle): replace NaN with 0 first |
| `--voxel-um` | Float, micrometres per pixel | Must be the maps' real pixel size |

Surface pixels are those of the averaged, scaled map above 0.01. For uint8 maps, values 0, 1 and 2 count as off the surface and 3 and up as on it; holes erode about 15 downsampled pixels (60 map pixels, about 0.56 mm at 9.362 um) around them, and the map's outer edge does not erode.

Size: the largest surface piece needs at least 5,000 downsampled pixels after erosion (about 7 mm2 at 9.362 um), and the 2.5 to 8 mm band needs at least 20 frequency bins. In practice a 200 x 200 px map was too small, a 600 x 600 px map of the test-style rows (which score in the millions at 1,600 px) scored only 8.9, and 534 px windows of PHerc0841 w00 had an empty band (this page's synthetic runs and the thresholds notes). The message for the first case says "over about 1 cm across"; read it as a rough guide.

## Outputs

Text by default (see Quick start): a `forward:` line, a `reverse:` line with `--reverse`, then notes, and always the closing `triage only: ...` line. A direction that cannot be scored prints `no score (REASON)`. Without scipy a note says the largest-piece step was skipped; with `--fast-resize` a note says rounding and near-tied peaks can differ.

With `--json`, one object:

| Field | Type | Meaning |
| --- | --- | --- |
| `voxel_um` | float | As given |
| `forward.valid_px` | int | Surface pixels of the averaged map at full resolution (above 0.01 after scaling) |
| `forward.largest_piece` | bool | True when scipy was there to keep the largest connected piece; false when that step was skipped |
| `forward.score` | float (1 decimal) or null | Strongest power in the 2.5 to 8 mm band over the band's median power; no upper bound |
| `forward.reason` | str | Only when `score` is null: `too small: the surface needs to be over about 1 cm across` or `band empty: the map is too small for a 2.5 to 8 mm period` |
| `forward.period_mm` | float (2 decimals) | Period of the strongest peak, in millimetres |
| `forward.angle_deg` | float (1 decimal) | Direction of the peak's frequency vector, `atan2(fy, fx)` in degrees: plus or minus 90 means the pattern repeats down the map (horizontal rows), 0 or plus or minus 180 across it. An angle and the angle plus or minus 180 are the same peak |
| `forward.mean_ink` | float (4 decimals) | Mean of the stretched map, `clip((a - 0.25) / 0.5, 0, 1)`, over surface pixels |
| `forward.p99` | float (3 decimals) | Its 99th percentile |
| `forward.frac_gt_half` | float (4 decimals) | Share of surface pixels whose stretched value is above 0.5 |
| `forward.resize_mode`, `forward.resize_note` | str | Only with `--fast-resize`: `sparse_area_float32` or `dense_nonfinite_fallback`, and the rounding caveat |
| `reverse` | object, the same fields | Only with `--reverse` |
| `files.forward`, `files.reverse` | list of str | The paths as given; `reverse` is empty without `--reverse` |
| `fast_resize` | bool | Only with `--fast-resize`, then true |

`period_mm`, `angle_deg`, `mean_ink`, `p99` and `frac_gt_half` are absent when `score` is null. With `--slug`, the same object is stored as the check's `result` in `run.json`, with `at` (UTC time) and `name`.

| Exit code | Meaning |
| --- | --- |
| `0` | Scored, or a direction abstained with `score` null and a `reason`: check `forward.score` |
| `1` | An error the command does not catch, with a Python traceback, such as running out of memory |
| `2` | Bad input, with the message on stderr (see Failure modes), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as no `--voxel-um` | Check the command against Commands and options |
| `numpy is required. Run inside villa's environment: uv run --project "$VILLA/vesuvius" --extra models python -m kit verify ...` | numpy is not installed (the message names `kit verify`, whose loader this command shares) | `python -m pip install numpy tifffile imagecodecs scipy` |
| `tifffile is required (it is in villa's environment)` | tifffile is missing | Install tifffile, and imagecodecs for compressed TIFFs |
| `cannot read MAP.tif: ...` | A missing file, a file that is not a TIFF (such as `.npy`), or a compressed TIFF without imagecodecs | Fix the path, install imagecodecs, or save the map as TIFF |
| `MAP.tif: expected a 2D map, got shape (...)` | A layer stack or an RGB image (from the loader; `score_array` raises `expected a 2D map, got shape (...)` for a non-2D array) | Pass one 2D map |
| `maps to average differ in shape: [(...), (...)]` | Forward maps (or reverse maps) of different shapes | Average only maps of one surface and grid |
| `--fast-resize requires scipy; omit it for the original dense resize` | `--fast-resize` without scipy | Install scipy, or drop `--fast-resize` |
| `no experiment at ROOT/SLUG/run.json` | `--slug` names an experiment that was never started | Start it with `python -m kit run init`, or fix `--slug` and `--root` |
| `bad slug: '...'` | A slug that is empty, holds `/` or starts with `.` | Use a plain name |
| `forward: no score (too small: the surface needs to be over about 1 cm across)`, exit code 0 | Fewer than 5,000 downsampled surface pixels after erosion, or no surface at all (many values at or below 0.01, or holes everywhere) | Score a larger area; check that the map is not mostly 0 to 2 grey levels |
| `forward: no score (band empty: the map is too small for a 2.5 to 8 mm period)`, exit code 0 | Fewer than 20 frequency bins in the band: the piece is small, or `--voxel-um` is too small or 0 | Score a larger area, and give the real pixel size |
| `forward: row score nan, ...`, exit code 0 | A NaN in a map spreads through the resize and the FFT; JSON then holds `NaN`, which strict JSON parsers refuse | Replace NaN with 0 (off the surface) before scoring |
| `note: scipy not found, so the largest-piece step was skipped; thin strips can fake a period` | scipy is missing; the score covers every surface pixel, and `largest_piece` is false | Install scipy for a score comparable with others |
| `note: --fast-resize changes float32 accumulation; near-tied FFT peaks can differ (see JSON resize_mode)` | `--fast-resize` was given | Expected; drop it for exact reproduction of older numbers |

## How it works

1. Load each map (`load_map`), scale it to 0 to 1 (`_normalize`) and average the maps of each direction (`mean_map`).
2. Stretch: `v = clip((a - 0.25) / 0.5, 0, 1)`, so 0.25 and below is 0 and 0.75 and above is 1. Surface pixels: `a > 0.01`.
3. Shrink `v` by `DOWNSAMPLE = 4` with an area average (OpenCV's `INTER_AREA` as two matrix products, or sparse matrices with `--fast-resize`), and map the surface mask onto the same grid by nearest neighbour.
4. Erode the mask with a square of `ERODE_PX = 31` downsampled pixels using a summed-area table; outside the image counts as surface.
5. Keep the largest 8-connected piece of the mask (`scipy.ndimage.label`) and crop both to its bounding box. Without scipy this step is skipped.
6. Stop with `too small` if fewer than `MIN_VALID_PX = 5000` mask pixels remain.
7. Fill pixels off the mask with the mean on it, subtract the mean, multiply by a 2D Hann window, and take the power spectrum of the 2D FFT.
8. The band holds the frequencies whose radius lies between `px_mm / 8` and `px_mm / 2.5` cycles per downsampled pixel, where `px_mm = 4 x voxel_um / 1000` is a downsampled pixel's size in millimetres (`PERIOD_MM = (2.5, 8.0)`). Stop with `band empty` if it has fewer than `MIN_BAND_BINS = 20` bins.
9. The score is the band's maximum power over its median power. The period is `px_mm` over the peak's radius, and the angle is the peak's direction.

Published source: Bullo27's `analysis/rowscore.py` ([first-letters-survey](https://github.com/Bullo27/first-letters-survey), MIT). The dense resize is the default and reproduces older numbers; the sparse resize computes the same overlap coefficients and only their nonzero products ([rowscore.md](../rowscore.md)).

## Cost and time

| Case | Dense default | `--fast-resize` | Memory | Source |
| --- | --- | --- | --- | --- |
| Public PHerc0841 w00 2.403 um map, 16,460 x 18,560 px, one map | 39.73 s median | 5.67 s median | 6.61 and 6.09 GiB peak (instrumented workers that keep extra arrays) | [rows report](../evidence/2026-10-07-production-scaling/rows/report.md), 2026-10-07, one core |
| Central 8,192 x 8,192 crop of that map | 5.28 s median | 1.97 s median | 1.66 GB peak, both | [production scaling log](../logs/2026-10-07-production-scaling.md) |
| Synthetic 5,980 x 8,240 uint8 map | 36.8 s wall | 21.2 s wall | 1.2 GB peak | This page, 2026-10-16, 4-core Intel Xeon cloud container (lscpu: 2.80 GHz) shared with other jobs (load average about 23), so slower than on a free machine |
| Three synthetic 1,600 x 1,600 maps (two forward, one reverse) | 5.2 s wall | 3.7 s wall | Not measured | Same machine and date |

Most of the dense time on large maps is the area resize (34.4 of 39.7 s on the full map); the FFT and the image-sized arrays are the rest. It runs on any machine in under a minute per map; nothing here needs Modal or a GPU.

## For agents

- **Command:** `python -m kit rowscore FWD.tif [FWD2.tif ...] --reverse REV.tif [REV2.tif ...] --voxel-um 9.362 --json`; add `--fast-resize` for maps of hundreds of millions of pixels.
- **Parse:** `forward.score` and `reverse.score`, `forward.period_mm` and `forward.angle_deg`; when `score` is null, `reason`.
- **Rerun:** Safe; it only reads its inputs and gives the same numbers (with or without `--fast-resize`, each mode is repeatable). With `--slug`, each run appends one more check to `run.json`.
- **Success:** Exit code 0 and a non-null, non-NaN `forward.score`.
- **Not a pass:** A forward score with no reverse; a forward score that is not well above the reverse; any score on a patch under a few cm2; a result with `largest_piece` false; a high score read as text; scores from a segment the model trained on read as generalization.
- **Go-ahead:** Nothing for scoring. Publishing any score of a target-scroll map is never allowed; score only public maps in public work.
- **Never:** Call a row score a reading, or say rows or letters were found; use it as a pass bar or as the only reason to drop a map from visual review; compare a `--fast-resize` score with a dense one to two decimals.

## Tests

```bash
python -m unittest tests.test_rowscore tests.test_rowscore_fast -v
```

Nineteen tests. `tests/test_rowscore.py` (11): rows 5 mm apart score above 50 at about 5 mm and 90 degrees, speckle scores below 20, a 1 mm period scores under a third of a 5 mm one, a 200 px map gets no score, float maps score like uint8, maps of two shapes are refused, holes on a grid erode the whole map, the area resize equals a block mean and keeps the mean on fractional factors, the erosion and its edge rule, and the command line with two averaged forward maps and a reverse. `tests/test_rowscore_fast.py` (8): sparse coefficients equal the dense ones, the default never calls the sparse path and adds no fields, the sparse resize matches within float32 tolerance while a displaced input fails that comparison, score, period and angle agree on a 1,023 px grid, a tied spectrum may pick either orientation, scipy missing is an error, NaN keeps the dense path, and the command line marks both directions only when asked. They skip without numpy and tifffile (and scipy for the fast tests). They do not cover real maps, the `band empty` reason, the run without scipy's largest-piece step, or `--slug`.

## History

- 2026-10-08: the module text no longer calls Bullo27's w045 and w033 scores held out, since `ink_9um` trained on w045's 2.4 um render (`d841e06`).
- 2026-10-07: `--fast-resize`, an opt-in sparse area resize, 7.0 times faster on a 305-million-pixel map, with `resize_mode` in the JSON; the dense default is unchanged (`047ee06`, [PR #27](https://github.com/ChaseHendrick/Scrolls/pull/27)).
- 2026-10-07: first version, a port of Bullo27's `rowscore.py` that averages forward and reverse maps (`b533efa`).

## Related

- [rowscore.md](../rowscore.md): the `--fast-resize` guide and its numerical limits.
- [`auc`](auc.md) and [`hpscore`](hpscore.md): the label-based ink-map measures that go next to this one.
- [`verify`](verify.md): agreement of two maps of the same input, with a control.
- [`mac-w045`](mac-w045.md): runs this command on its maps and prints the scores in its summary.
- [`plan`](plan.md): `kit plan` names this command as the triage step.
- [`autopipeline`](autopipeline.md): its `triage` step uses this score.
- [`run-ledger`](run-ledger.md): the experiment ledger that `--slug` writes to.
- [Community scan log](../logs/2026-10-07-community-scan.md) and `results` in [`results.json`](../results.json): row scores of `ink_9um` on w045 and PHerc0841.
- [Thresholds notes](../../scripts/experiments/2026-10-07-cloud/thresholds/notes.md): how much surface the score needs.
- [STANDARDS.md](../STANDARDS.md): the triage-order row and the note that this score has no bar.
