# cropscan: pixel AUC of one ink map on every window of a grid

`kit.cropscan.scan` scores one ink map against boolean ink and supervision arrays on every full window of a regular grid (by default 640 px windows every 320 px, 64 px edge left out), to show how much a single crop's AUC depends on where the crop was put.

| Field | Value |
| --- | --- |
| Id | `cropscan` |
| Status | Current |
| Kind | kit module |
| Area | Scoring and controls |
| Run | None (library): `from kit import cropscan`, then `cropscan.scan(...)` |
| Code | `kit/cropscan.py`, `kit/auc.py` (`_quantize`, `_auc_hist`), `kit/verify.py` (`_numpy`, `VerifyError`) |
| Tests | `tests/test_cropscan.py` |
| Needs | Python 3.10 or newer, numpy. Labels must already be boolean arrays on the map's grid (for example from `kit.auc.labels_on_map`, which needs zarr) |
| Runs on | Any CPU. A 4,220 x 4,760 uint8 map (the size of PHerc0841 w00) took 4.1 s for 156 windows, peak process memory 877 MB including the inputs (measured 2026-10-16, 4-core Xeon cloud container, synthetic data). Not faster than scoring each crop directly ([lane I log](../logs/2026-10-07-grok-laneI.md)) |
| Network | None |
| Writes | Nothing (returns a list) |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07 ([PR #26](https://github.com/ChaseHendrick/Scrolls/pull/26)) |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

The repository often scores an ink map on one crop: the 640 px window of densest labeled ink per segment, with a 64 px edge left out (`--inner 64` in [`auc`](auc.md)). A single crop is one place on the segment. `cropscan` asks how much the score would change if the crop had been put somewhere else: it computes the pixel AUC (the chance that a labeled ink pixel scores above a labeled background pixel inside the supervision mask, ties counted half) of every full window on a grid, in one pass.

Instead of cutting and scoring each window separately, it quantizes the whole map once, builds ink and background score histograms for each `tile` x `tile` cell, and sums them with a 2D cumulative sum, so each window costs one histogram difference. With `bins=65536` the result is exactly what `kit.auc.score_array` gives on the same window, for uint8, uint16 or float maps already normalized to [0, 1]. With fewer bins, uint16 and float scores share bins, which adds ties and can move the AUC; uint8 keeps all 256 levels at 256 bins or more.

It reads no files and no labels itself: the caller passes the map and boolean ink and mask arrays on the map's grid. It has no control of its own; run it on the reverse-depth map as well (see Checks and controls). An AUC is a score against human labels; it is model output, not a reading, and it never means that letters were found.

It was written for the lane I crop placement study (a preregistered public-data experiment on PHerc0841 w00, 2026-10-07) to be faster than scoring each crop; it was not: 297 s against 17.7 s for the plain loop on a busy machine. It is kept as a correctness-checked helper, not as a speedup ([lane I log](../logs/2026-10-07-grok-laneI.md), section T1).

## When to use it

- Checking how much a crop AUC, or a ranking of two maps, moves with the crop's position on one segment: scan both maps and compare the per-window AUCs.
- Finding the windows of a segment that meet a supervision rule (enough supervised pixels and both classes), with their pixel counts.

Do not use it:

- For the score of one crop or a whole segment: use [`auc`](auc.md) (`kit.auc.score_array` or `python -m kit auc`), which also gives the reverse-depth control and bootstrap intervals.
- For speed: on the sizes measured, scoring each window with `score_array` was as fast or faster (see Cost and time).
- For letter-scale detail: use [`hpscore`](hpscore.md).
- To treat per-window AUCs as independent samples or confidence intervals: neighboring windows overlap by half by default.
- On float maps that are not in [0, 1] (raw logits, 0 to 255 floats): it refuses them; apply a sigmoid or convert to uint8 or uint16 first.

## Quick start

Run it from the repository root so that `import kit` finds the package, for example saved as `SNIPPET.py` and run with `python3 - < SNIPPET.py`:

```python
import numpy as np
from kit import cropscan

rng = np.random.default_rng(0)
ink = rng.random((1300, 1700)) > 0.8                      # boolean ink labels on the map's grid
mask = np.ones(ink.shape, bool)                           # boolean supervision mask
pred = np.clip(0.3 + 0.3 * ink + rng.normal(0, 0.2, ink.shape), 0, 1).astype(np.float32)

rows = cropscan.scan(pred, ink, mask)                     # 640 px windows, 320 px stride, 64 px inner edge
scored = [r["auc"] for r in rows if r["auc"] is not None]
print(len(rows), "windows,", len(scored), "scored")
print(rows[0])
print("AUC range", min(scored), "to", max(scored))
```

For a real map, `pred` is the ink map as a numpy array (uint8, uint16, or float in [0, 1]), and `ink` and `mask` are the segment's labels and supervision on the same grid, such as the arrays `kit.auc.labels_on_map` returns. On the synthetic map above it printed (2026-10-16):

```
12 windows, 12 scored
{'crop': [0, 640, 0, 640], 'ink_px': 52540, 'background_px': 195653, 'auc': 0.8474}
AUC range 0.8445 to 0.8477
```

It worked when it returns a list with one entry per full window. A window with `auc` `None` was not scored (too little supervision or one class too rare), which is not a low score.

## Checks and controls

- **Exactness against direct scoring.** At `bins=65536`, every window's `auc`, `ink_px` and `background_px` equal `kit.auc.score_array` on the same crop with the same `inner` and `keep_zero`; `tests/test_cropscan.py` checks this for float32, uint16 and uint8 maps with holes in the mask and unpredicted zeros. On the synthetic float Quick start map, the default 4,096 bins also matched `score_array` to all 4 decimals on all 12 windows, and a 4,220 x 4,760 uint8 map at the default (256 bins for uint8) matched on all 120 scored windows (2026-10-16). In lane I, the 4,096-bin scan differed from `score_array` by at most 1.0e-4 ([lane I log](../logs/2026-10-07-grok-laneI.md)). Fewer bins on other data need their own check against `score_array`.
- **Reverse-depth control.** The scan itself does not contain one. Scan the reverse-depth map of the same surface with the same arguments, and require each window's forward AUC to be well above its reverse; a forward AUC without its control is not a result (the rule that every check must be able to fail, hard rule 4).
- **Gates that keep missing data from looking like evidence.** A window is scored only when its used pixels (supervised, and nonzero unless `keep_zero`) cover at least `min_supervised` of the inner area and the rarer class is at least `min_class` of them; otherwise `auc` is `None`.
- **What the spread looked like, for scale.** In lane I, the Vesuvius Challenge team's 2.4 um ink map of PHerc0841 w00 had crop AUCs from 0.898 to 0.995 over 24 overlapping windows that passed the supervision rule, against 0.9714 for the full region (descriptive; the labels may have been drawn with that map in view, which is untested; that log's interval conclusions R1 and R2 are marked unresolved after review because of undefined bootstrap intervals, so only the point AUCs are quoted here).

Claim label: Model output, for the per-window AUCs of a model's map against the published labels; Null for the speed it was built for (lane I, T1).

## Python API

```python
from kit import cropscan
rows = cropscan.scan(prediction, ink, mask)   # defaults: window=640, stride=320, inner=64, tile=64, bins=4096
# Exact bins on a whole segment: inner=0 allows tile=320, which keeps the work estimate under the 2 GiB guard.
exact = cropscan.scan(prediction, ink, mask, bins=65536, inner=0, tile=320)
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `scan(prediction, ink, mask, window=640, stride=320, inner=64, tile=64, bins=4096, min_supervised=0.2, min_class=0.02, keep_zero=False, max_work_bytes=2 * 1024 ** 3)` | A list of dicts, one per full window, row by row: `{"crop", "ink_px", "background_px", "auc"}` (under Outputs); `[]` when the map is smaller than one window | `VerifyError` for every refusal under Failure modes, before any histogram is built | Reads only its arguments and leaves them unchanged |

Arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `prediction` | required | The ink map, a 2D numpy array: uint8, uint16, or a float dtype with every value in [0, 1]. All values must be finite |
| `ink` | required | Boolean array, same shape: True where the labels say ink |
| `mask` | required | Boolean array, same shape: True where the pixel is supervised (labeled ink or background) |
| `window` | `640` | Window side in pixels; a positive multiple of `tile` |
| `stride` | `320` | Step between window origins in pixels; a positive multiple of `tile` |
| `inner` | `64` | Pixels left out at each edge of a window, as `--inner` in `auc`; a nonnegative multiple of `tile`, less than half of `window` |
| `tile` | `64` | Cell side of the histogram grid; windows start on cell corners |
| `bins` | `4096` | Score bins, 2 to 65,536; capped at 256 for uint8. 65,536 is exact; fewer bins tie nearby scores |
| `min_supervised` | `0.2` | Least share of the inner window area that must be used pixels for a score, 0 to 1 |
| `min_class` | `0.02` | Least share of the used pixels for the rarer class, 0 to 0.5 |
| `keep_zero` | `False` | Count pixels where the map is exactly 0; by default they are left out as unpredicted, as in `auc`. Must be a bool |
| `max_work_bytes` | `2 * 1024 ** 3` | Refuse when the estimated internal array work exceeds this many bytes (a positive integer). The estimate leaves out the caller's arrays and allocator overhead; it is not a limit on process memory |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| `prediction` | 2D numpy array, uint8, uint16 or float in [0, 1] | The whole map is quantized once with `kit.auc._quantize`: uint8 and uint16 as they are, floats times 65,535, rounded. Other float ranges are refused because `score_array` picks its scale per crop from the crop's maximum, so the two would not agree. Exactly 0 means "no prediction" unless `keep_zero` |
| `ink`, `mask` | 2D numpy bool arrays, the map's shape | Not 0 and 1 integers: those are refused. On a segment, `kit.auc.labels_on_map` gives both on a map's grid from `inklabels.zarr` and `supervision.zarr` |

Coordinates are pixel rows and columns of the map. Only the top-left `(H // tile) * tile` rows and `(W // tile) * tile` columns can fall inside a window; windows never run past the edge.

## Outputs

It prints nothing and writes nothing. It returns a list, one dict per window, ordered by window row then column:

| Field | Type | Meaning |
| --- | --- | --- |
| `crop` | list of 4 int | The full window, `[Y0, Y1, X0, X1]` in map pixels, ends excluded: the same form as `auc --crop` |
| `ink_px` | int | Used ink pixels in the inner part of the window (the window minus `inner` at each edge) |
| `background_px` | int | Used background pixels in the inner part |
| `auc` | float (4 decimals) or None | Pixel AUC on those pixels; `None` when the window failed `min_supervised` or `min_class`, or has no pixel of one class |

## Failure modes

Every refusal is a `kit.verify.VerifyError` with the message below, raised before any histogram is allocated.

| What you see | Why | What to do |
| --- | --- | --- |
| `the map holds N NaN or infinite values; replace them (with 0 for no prediction) before scoring` | The map has NaN or infinite pixels, which a histogram cannot rank | Replace them, with 0 where there is no prediction, and rerun |
| `numpy is required. Run inside villa's environment: uv run --project "$VILLA/vesuvius" --extra models python -m kit verify ...` | numpy is not installed | `python -m pip install numpy` |
| `prediction, ink and mask must be 2D arrays` | An array with another number of axes | Pass one 2D map and 2D labels |
| `prediction, ink and mask must share one grid` | The shapes differ | Put the labels on the map's grid first (`kit.auc.labels_on_map`) |
| `ink and mask must be boolean arrays` | Integer or float labels | Convert with `> 0` |
| `NAME must be a positive integer` | `window`, `stride`, `tile`, `bins` or `max_work_bytes` is 0, negative, a float or a bool | Use a positive int |
| `inner must be a nonnegative integer` | `inner` is negative, a float or a bool | Use 0 or a positive int |
| `bins must be between 2 and 65536` | `bins` out of range | Use 4,096 or 65,536 |
| `NAME must be finite and between 0 and UPPER` | `min_supervised` outside 0 to 1, or `min_class` outside 0 to 0.5, or NaN | Use a share in range |
| `keep_zero must be boolean` | `keep_zero` is not a bool (a string such as `'false'` is refused) | Pass `True` or `False` |
| `NAME V is not a multiple of tile T` | `window`, `stride` or `inner` does not divide by `tile` | Pick a `tile` that divides all three (64 for the defaults) |
| `inner margin leaves nothing` | `2 * inner` is at least `window` | Use a smaller `inner` |
| `prediction must be uint8, uint16 or normalized float` | Another dtype, such as int32 or bool | Convert to uint8, uint16 or float in [0, 1] |
| `prediction must contain only finite values` | NaN or infinity in the map | Fix the map |
| `float prediction must be normalized to [0, 1] for crop-stable quantization` | A float map with a value below 0 or above 1 | Apply a sigmoid to logits, or divide 0 to 255 maps by 255 |
| `crop scan estimated work N bytes exceeds max_work_bytes M; use fewer bins or larger tiles` | The histograms for this map, `tile` and `bins` would be too large: a 4,220 x 4,760 float map at 65,536 bins and tile 64 needs an estimated 18.6 GB | Use fewer bins, a larger `tile` (with `inner` a multiple of it), or raise `max_work_bytes` if the memory is there |
| An empty list `[]` | The map is smaller than one window in a dimension | Not an error; use a smaller `window` or score the whole map with `auc` |

## How it works

1. Check every argument and the map's dtype and range (Failure modes); return `[]` when the map is smaller than `window`.
2. Estimate the work, `40 * ty * tx * bins + 16 * (ty + 1) * (tx + 1) * bins + 40 * H * W` bytes, with `ty = H // tile` and `tx = W // tile`, and refuse above `max_work_bytes`.
3. Quantize the whole map once (`kit.auc._quantize`) to 256 levels for uint8 or 65,536 otherwise, and map each score to one of `bins` bins (`q * bins // levels`; `bins` is capped at 256 for uint8).
4. Keep pixels in the mask, and not exactly 0 unless `keep_zero`. Count ink and background pixels per (cell, bin) with `numpy.bincount`, then take the cumulative sum over cell rows and columns: `cum[class, y, x, bin]`.
5. For each window origin on the `stride` grid, take the inner rectangle's histograms as `cum[y1, x1] - cum[y0, x1] - cum[y1, x0] + cum[y0, x0]`, count the pixels, apply the `min_supervised` and `min_class` gates, and compute the AUC from the two histograms (`kit.auc._auc_hist`: for each bin, ink count times the background count below it, plus half the ties, over the product of the totals), rounded to 4 decimals.

The AUC from histograms is the Mann-Whitney statistic with ties half, the same as `kit.auc.auc_scores`; at 65,536 bins no two different scores share a bin, so it is exact.

## Cost and time

Measured 2026-10-16 in a 4-core Xeon cloud container (lscpu reports 2.80 GHz) shared with other jobs, on synthetic data:

| Map | Settings | `scan` | `score_array` on each window | Notes |
| --- | --- | --- | --- | --- |
| 1,300 x 1,700 float32 | defaults (4,096 bins), 12 windows | 1.8 s | 0.5 s | Same AUCs to 4 decimals |
| 1,300 x 1,700 float32 | 65,536 bins, 12 windows | 17.7 s | 0.5 s | Estimated work 2.05 GB, just under the guard |
| 4,220 x 4,760 uint8 | defaults (256 bins), 156 windows, 120 scored | 4.1 s | 3.4 s | Peak process memory 877 MB including the inputs |

In lane I, scanning the readers on PHerc0841 w00 took 297 s against 17.7 s for the plain loop (0.06x), on a machine with a load average up to 20 ([lane I log](../logs/2026-10-07-grok-laneI.md)). Memory grows with `bins` times the number of cells, so 65,536 bins at tile 64 is refused on a full segment by the default 2 GiB guard. It runs on any machine; nothing here needs Modal or a GPU.

## For agents

- **Command:** in Python from the repository root, `from kit import cropscan` then `rows = cropscan.scan(PRED, INK, MASK)`, with PRED a uint8, uint16 or [0, 1] float map and INK and MASK boolean arrays on its grid; add `bins=65536` (and a `tile` the memory guard accepts) when the AUCs must equal `score_array` exactly. There is no command line and no JSON file; `json.dumps(rows)` serializes the result.
- **Parse:** each dict's `crop` (`[Y0, Y1, X0, X1]`), `auc` (None means not scored), `ink_px` and `background_px`.
- **Rerun:** Safe; it only reads its arguments and has no randomness, so the same inputs give the same list.
- **Success:** A list with one dict per full window and no `VerifyError`; an empty list means the map is smaller than one window.
- **Not a pass:** Per-window AUCs without the same scan of the reverse-depth map; AUCs at fewer than 65,536 bins on a uint16 or float map that were not checked against `score_array`; treating overlapping windows as independent samples; any score on a segment the model trained on; a claim that the scan is faster.
- **Go-ahead:** Nothing. Publishing any score of a target-scroll map is never allowed; scan only public labeled segments in public work.
- **Never:** Call an AUC a reading or say letters were found; read `auc: None` as a low score.

## Tests

```bash
python -m unittest tests.test_cropscan -v
```

The 7 tests cover exact agreement with `score_array` on every window (float32 and uint16 at 65,536 bins with holes and zeros; uint8 at 256, 4,096 and 65,536 bins; `inner` and `keep_zero`), the coverage and class gates returning `None` rather than a score, an empty result without allocating histograms, every refusal of shapes, dtypes, values and parameters, the memory guard firing before allocation, and the archived lane I runner refusing to run without its replay flag. They skip without numpy and took 0.4 s on 2026-10-16. They do not run on real segment data.

## History

- 2026-10-16: a map with NaN or infinite pixels is refused with a message instead of being ranked (`136b5b2`).
- 2026-10-07: the input domain is enforced (uint8, uint16 or [0, 1] floats, boolean labels, integer grid parameters), the memory guard `max_work_bytes` added, uint8 kept at all 256 levels (the first version put 16 uint8 levels in each bin at the default 4,096 bins), and exactness against `score_array` tested (`210e023`, [PR #26](https://github.com/ChaseHendrick/Scrolls/pull/26)).
- 2026-10-07: first version, for the lane I crop placement study (`f5430ee`, [lane I log](../logs/2026-10-07-grok-laneI.md)).

## Related

- [`auc`](auc.md): one map on one crop or a whole segment, with the reverse-depth control, bootstrap intervals and `labels_on_map`.
- [Lane I log](../logs/2026-10-07-grok-laneI.md): the crop placement study that used this helper, its review status and the speed null.
- [`experiment-records`](experiment-records.md): `scripts/experiments/2026-10-07-grok-laneI/`, the archived runner that calls `scan` (guarded by `SCROLLS_REPLAY_HISTORICAL_LANEI`).
- [`hpscore`](hpscore.md): the letter-scale score.
- [`gate`](gate.md): Gate A, which ranks readers by crop AUCs on PHerc0841.
