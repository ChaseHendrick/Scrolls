# ensemble: average several ink maps of one surface into one map

`python -m kit ensemble` combines two or more ink maps of the same surface on the same grid into one map, by a weighted mean of their scores or of their pixel ranks, keeping out every pixel where any input made no prediction.

| Field | Value |
| --- | --- |
| Id | `ensemble` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Ink maps and models |
| Run | `python -m kit ensemble`, `from kit import ensemble` |
| Code | `kit/ensemble.py`, `kit/cli.py` (`cmd_ensemble`), `kit/auc.py` (`_load`), `kit/verify.py` (`load_map`, `_numpy`, `VerifyError`) |
| Tests | `tests/test_ensemble.py` |
| Needs | Python 3.10 or newer, numpy; tifffile to read or write `.tif` maps (imagecodecs for LZW or zstd TIFFs). `.npy` in and out needs numpy only |
| Runs on | Any CPU. Two 600 x 800 maps take about 2 s including start-up; two 4,220 x 4,760 maps (the size of PHerc0841 w00) took 11.9 s with `mean` and 86.4 s with `rank` on a heavily loaded machine (measured 2026-10-16, 4-core 2.1 GHz Xeon cloud container, synthetic maps; see Cost and time) |
| Network | None |
| Writes | The output map `OUT` (`.npy` as float32, anything else as a uint16 TIFF), replacing any file of that name. Nothing else |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07 (`ebd4ae3`). The AutoPipeline release package carries its own larger `ensemble` (with a `zscore` method and per-model decoding), described with that release, not here |
| Guide | [tricks.md](../tricks.md) (map ensembles and z windows, with the community sources and the PHerc0841 numbers) |
| Checked | 2026-10-16 against commit `63753fa` |

## What it does

An ink map is one score per pixel of a flattened surface, made by one ink model (a "reader") from one surface volume. Maps of the same surface made by different models, by different training seeds of one model, or by one model on different depth windows of the volume (z windows) make different mistakes. Averaging them, a prediction-level or map ensemble, is the cheapest gain the community reports: on PHerc0841, d9v2 and Reader v2 averaged reached 0.840 AUC against 0.828 and 0.826 alone ([TAUIL's held-out benchmark](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search), Community report, `community` in [`results.json`](../results.json)).

`kit ensemble` does that averaging. It has two methods. `mean` scales each map to 0..1 and takes the weighted mean: right for maps of one model, such as seeds, checkpoints or z windows, whose scores are on the same scale. `rank` replaces each map by its pixel ranks (0..1 over the valid pixels) before the mean, so a model whose scores sit in a narrow band counts as much as one that uses the whole range: right for maps of different models.

A pixel is valid only where every input is non-zero, because villa's inference and v8in write 0 where they made no prediction. Elsewhere the output is 0, and every valid pixel is written above 0, so [`auc`](auc.md) leaves out exactly the pixels it would leave out for the inputs.

It averages maps, never model weights. Averaging the weights of two seeds broke `ink_9um` (AUC 0.49, Nieuwlaar's [ink9um-dense-native](https://github.com/Nieuwlaar/ink9um-dense-native), Community report, in [tricks.md](../tricks.md)); weight averaging within one training run is the separate checkpoint soup script, `scripts/soup.py`. It does not check that the inputs show the same surface: any maps of equal shape are combined. The combined map is model output, not a reading, and a higher AUC from an ensemble does not mean letters were found.

## When to use it

- Averaging the maps of several z windows of one model (`--method mean`), as in Nieuwlaar's z-window ensemble ([tricks.md](../tricks.md)).
- Averaging maps of two or more seeds or checkpoints of one model (`--method mean`).
- Combining readers of different families, such as d9v2 and Reader v2, or v8in and d9v2 (`--method rank`).
- Building the matching control: the reverse-depth maps of the same members, combined the same way.

Do not use it:

- To average model weights: use `scripts/soup.py` ([soup](soup.md)), within one training run only.
- To combine maps of different surfaces or crops, or maps on different grids: they must be the same window of the same surface, pixel for pixel. Bring each to the same grid first (villa's render or inference does this; `kit ensemble` does not resample).
- To score the result: use [`auc`](auc.md) with the ensembled reverse map as `--control`, and `--compare` against the best member.
- To combine logits or other unbounded scores with `--method mean`: apply a sigmoid first, or use `--method rank` (see Inputs).

## Quick start

```bash
# Two readers' maps of the same crop, and their reverse-depth maps
python -m kit ensemble ENS.tif MAP_A.tif MAP_B.tif --method rank
python -m kit ensemble ENS_reverse.tif MAP_A_reverse.tif MAP_B_reverse.tif --method rank

# Score it against the labels, with the ensembled reverse as control and the better member as comparison
python -m kit auc ENS.tif --control ENS_reverse.tif --labels L/inklabels.zarr --mask L/supervision.zarr \
    --compare MAP_B.tif --bootstrap 300
```

- `MAP_A.tif`, `MAP_B.tif`: ink maps of the same surface window, same shape; `MAP_A_reverse.tif`, `MAP_B_reverse.tif`: the same models on the volume with its layers in reverse order.
- `ENS.tif`, `ENS_reverse.tif`: the outputs, uint16 TIFFs.
- `L`: the segment's label folder (see [auc](auc.md) for where to get `inklabels.zarr` and `supervision.zarr`).

On synthetic 600 x 800 maps (made for this page: reader A a full-range uint8 map with 5 columns of zeros, reader B a uint16 map squeezed into 30,000 to 33,000, both noisy copies of the same blobs) it printed:

```
rank of 2 maps -> /tmp/.../ab_rank.tif (477000 valid px of 600 x 800)
rank of 2 maps -> /tmp/.../ab_rank_reverse.tif (480000 valid px of 600 x 800)
```

and `kit auc` gave, map (control): A 0.8137 (0.4999), B 0.8818 (0.4993), `--method mean` 0.8275 (0.4998), `--method rank` 0.9203 (0.4992). Plain `mean` followed reader A, because B's narrow band barely moves after scaling; `rank` gave both readers equal say. These are synthetic numbers that show the mechanics, not a measured gain.

It worked when the exit code is 0 and `valid_px` is close to the number of pixels every input predicted. Whether the ensemble is any better is decided by `kit auc`, not by this command.

## Checks and controls

- **Ensemble the control the same way.** Combine the members' reverse-depth maps with the same method and weights, and score with `kit auc ENS.tif --control ENS_reverse.tif`. The ensemble must stay well above its ensembled reverse (Gate A reads "well above" as at least 0.10, `MIN_GAP` in `kit/gate.py`). Every ensemble row in the 2026-10-07 CPU tricks job was scored this way ([tables](../../scripts/experiments/2026-10-07-cloud/tricks/tables.md)).
- **Beat the best member, beyond noise.** An ensemble helps only if it scores above its best single member: `kit auc ENS.tif --compare BEST.tif --bootstrap 300`, and a difference whose 95 % interval includes 0 is noise. On two PHerc0841 crops (w00 and ag896, 64 px edge left out, CPU, 2026-10-07), the four two-reader ensembles beat their better member once in eight cases, by 0.0008: d9v2 plus Reader v2 by mean scored 0.9277 (reverse 0.677) on w00 against Reader v2 alone at 0.9269 (0.729), and 0.8164 (0.576) on ag896 against d9v2 alone at 0.8230 (0.532). d9v2 plus `ink_9um` seed 42 fell below d9v2 alone on both crops: 0.8677 and 0.7667 by mean, 0.8750 and 0.7733 by rank, against 0.8994 and 0.8230 ([tables](../../scripts/experiments/2026-10-07-cloud/tricks/tables.md), [tricks.md](../tricks.md): ensembles help only when the members are about equally good). Uncertainty of those differences was not measured.
- **z windows.** The mean of four z windows (0:20, 3:23, 5:25, 8:27) scored above the default window in all six reader and crop cases of that job, for example d9v2 on w00 0.9198 against 0.8994, but below the best single window chosen with the labels in five of six; windows chosen on the scored crops are optimistic ([tables](../../scripts/experiments/2026-10-07-cloud/tricks/tables.md)).
- **Held-out data.** Score on segments no member trained on (`held_out` in `results.json`); PHerc0841 is in the training data of none of `ink_9um`, v8in, d9v2 and Reader v2, but possibly in Hecate's ([log](../logs/2026-10-09-pherc0841-hecate.md)).

Claim label: Model output, for the combined map and any AUC gain measured from it with `kit auc`; the command itself makes no claim. The community gains quoted above are Community reports.

## Commands and options

### `python -m kit ensemble`

```
usage: python -m kit ensemble [-h] [--method {mean,rank}]
                              [--weights WEIGHTS [WEIGHTS ...]] [--json]
                              out maps [maps ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | Output path. A name ending in `.npy` is written as a float32 array; any other name is written as a uint16 TIFF (even `.png`). Its folder must exist; an existing file is replaced |
| `maps` | required | Two or more input maps (`.tif` or `.npy`) of the same surface on the same grid, all the same shape. One map gives an error |
| `--method METHOD` | `mean` | `mean`: weighted mean of the maps scaled to 0..1, for maps of one model (seeds, checkpoints, z windows). `rank`: weighted mean of each map's pixel ranks over the valid pixels, for maps of different models (`METHODS`) |
| `--weights WEIGHTS ...` | none | One non-negative weight per map, in the order of `maps`, not all zero; they are divided by their sum. Equal weights when left out |
| `--json` | off | Print the result as JSON (fields under Outputs) instead of one line of text |

## Python API

```python
from kit import ensemble
result = ensemble.ensemble_files("ENS.tif", ["MAP_A.tif", "MAP_B.tif"], method="rank")
combined, valid = ensemble.combine([array_a, array_b], method="mean", weights=[2, 1])
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `combine(arrays, method='mean', weights=None)` | `(combined, valid)`: a float64 array of the inputs' shape, 0 outside `valid`, and the boolean mask of pixels non-zero in every input | `VerifyError` for an unknown method, fewer than two arrays, arrays of different shapes, or weights that are not one non-negative number per array with a positive sum; `VerifyError` when numpy is missing | The combining step, on arrays in memory. Values on valid pixels are in 0..1 for well-formed inputs, but are not clipped here (see Inputs) |
| `write(path, combined, valid)` | The path, as str | `VerifyError` when tifffile is missing for a TIFF; `FileNotFoundError` or another `OSError` when the folder does not exist | `.npy`: float32, `(1 + clip(v, 0, 1) * 65534) / 65535` on valid pixels and 0 elsewhere. Anything else: uint16 TIFF, `1 + round(clip(v, 0, 1) * 65534)` on valid pixels (1 to 65535) and 0 elsewhere |
| `ensemble_files(out, inputs, method='mean', weights=None)` | Dict: `out`, `inputs`, `method`, `weights`, `shape`, `valid_px` (see Outputs) | `VerifyError` from loading, `combine` or `write`; `FileNotFoundError` for a missing `.npy` input or output folder | What the command runs: loads every input (TIFFs with `load_map`, `.npy` with `numpy.load`), combines, writes |

Module constant: `METHODS = ("mean", "rank")`.

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Ink map, `.tif` | Any 2D TIFF tifffile reads | Singleton axes are squeezed; a stack or an RGB image is refused |
| Ink map, `.npy` | numpy array | Loaded as it is, with no squeeze and no 2D check; object (pickled) arrays are refused by numpy |
| All maps | Same shape | Same window of the same surface on the same grid; only the shape is checked |

How scores are scaled to 0..1 before `mean` (and before ranking, which the scaling does not change):

| Input dtype | Scaling |
| --- | --- |
| uint8 | Divided by 255 |
| uint16 | Divided by 65535 |
| Anything else (float, int32, ...) | Taken as float64. If the map's largest value is above 1: divided by 255 when it is at most 255, else by 65535. A map whose largest value is at most 1 is used as it is |

Exactly 0 means "no prediction" in every dtype; a pixel that is 0 in any input is left out of the output. Negative values count as predictions: with `mean`, logits (negative and positive scores) go through the same scaling rule and are averaged as they are, and the negative results are clipped to the bottom of the output range when written, so apply a sigmoid first or use `rank`. Values above 1 after scaling (such as an int32 map above 65535) are clipped to the top. NaN is not handled: with `mean` it makes that output pixel NaN in a `.npy` (and an undefined value in a TIFF), and with `rank` it ranks above every real score. Replace NaN with 0 before ensembling.

## Outputs

One file, `OUT`:

| Output | Type | Values |
| --- | --- | --- |
| `OUT` ending in `.npy` | float32 array, the inputs' shape | 0 where any input is 0; `(1 + v * 65534) / 65535` on valid pixels, so 1/65535 to 1 |
| Any other `OUT` | uint16 TIFF (written by tifffile whatever the extension) | 0 where any input is 0; 1 to 65535 on valid pixels |

Here `v` is the combined score clipped to 0..1: the weighted mean of the scaled maps (`mean`) or of their ranks (`rank`). Ranks run from 0 (lowest valid score) to 1 (highest), ties sharing their mean rank.

Text output, one line: `METHOD of N maps -> OUT (VALID valid px of H x W)`. With `--json`, one object:

| Field | Type | Meaning |
| --- | --- | --- |
| `out` | str | The output path as given |
| `inputs` | list of str | The input paths as given |
| `method` | str | `mean` or `rank` |
| `weights` | list of float | The weights as given, or 1.0 per map |
| `shape` | list of int | Shape of the maps, `[H, W]` |
| `valid_px` | int | Pixels non-zero in every input, which are the non-zero pixels of `OUT` |

| Exit code | Meaning |
| --- | --- |
| `0` | `OUT` was written |
| `1` | An error the command does not catch, with a Python traceback, such as a missing `.npy` input or a missing output folder (`FileNotFoundError`) |
| `2` | Bad input, with the message on stderr (see Failure modes), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as no input maps, or `--method` other than `mean` or `rank` (`argument --method: invalid choice: ...`) | Check the command against Commands and options |
| `an ensemble needs at least two maps` | Only one input map | Give two or more maps |
| `maps differ in shape: [(...), (...)]` | The inputs are not the same window or grid | Use maps of the same surface window; crop or render them to one grid first |
| `give one non-negative weight per map, not all zero` | `--weights` count differs from the number of maps, a weight is negative, or all are 0 | Give one weight per map, in order |
| `method must be one of ('mean', 'rank'), got '...'` | `combine` or `ensemble_files` called from Python with another method (the command line refuses it earlier) | Use `mean` or `rank` |
| `numpy is required. Run inside villa's environment: uv run --project "$VILLA/vesuvius" --extra models python -m kit verify ...` | numpy is not installed | `python -m pip install numpy tifffile`, or run inside villa's environment |
| `tifffile is required (it is in villa's environment)` | A `.tif` input and no tifffile | Install tifffile, or use `.npy` inputs |
| `tifffile is required to write a .tif ensemble` | An output name not ending in `.npy` and no tifffile | Install tifffile, or name the output `.npy` |
| `cannot read PATH: ...` | A `.tif` input that does not exist or cannot be decoded (for example LZW without imagecodecs) | Fix the path; install imagecodecs; or save the map as `.npy` |
| `PATH: expected a 2D map, got shape (...)` | A `.tif` input that is a stack or an RGB image | Pass one 2D map per file |
| `FileNotFoundError: ...` and a traceback, exit code 1 | A `.npy` input that does not exist, or an output folder that does not exist | Fix the path, or create the folder |

## How it works

1. Load every input: `.npy` with `numpy.load`, anything else with `load_map` (tifffile, squeezed, must be 2D).
2. Check the method, the count (at least two), equal shapes, and the weights (one per map, none negative, positive sum; equal when not given).
3. Valid mask: pixels that are non-zero in every input.
4. Scale each map to 0..1 by dtype (`_unit`; Inputs has the rule).
5. With `rank`, replace each scaled map's valid pixels by their ranks (`_ranks`): a stable sort, ties given their mean rank, divided by the number of valid pixels minus 1, so the lowest valid score gets 0 and the highest gets 1 (a little more or less when they are tied).
6. Weighted sum, divided by the sum of the weights; 0 outside the valid mask.
7. Write: clip to 0..1 and map valid pixels onto 1..65535 (`.npy` float32 divides that by 65535), so no valid pixel becomes 0.

The `rank` method makes the ensemble depend only on each member's ordering of pixels, which is also all that pixel AUC measures. The `mean` method keeps each member's scale, so a member that uses a wider range of scores weighs more, as the synthetic Quick start shows.

## Cost and time

Measured 2026-10-16 in a 4-core 2.1 GHz Xeon cloud container that other jobs were loading heavily (load average 15 to 24), so these are upper bounds:

| Maps | Method | Wall time | Peak memory |
| --- | --- | --- | --- |
| 2 x 600 x 800, uint8 and uint16 | `rank` | 2.2 s including Python start-up | Not measured |
| 2 x 4,220 x 4,760 uint8 (PHerc0841 w00's surface size), random | `mean` | 11.9 s (6.7 s combining, 1.5 s writing, in a second run) | 731 MB |
| 2 x 4,220 x 4,760 uint8, random | `rank` | 86.4 s | 1,823 MB |

Memory grows with the map size and the number of maps: every input is held in memory, plus float64 working arrays of the map's size (8 bytes per pixel each), and `rank` sorts the valid pixels of each map. The crops used here (640 x 640) take well under a second of work. It runs on any CPU; nothing here needs Modal or a GPU.

## For agents

- **Command:** `python -m kit ensemble OUT.tif MAP1.tif MAP2.tif --method rank --json` (use `--method mean` for maps of one model), then the same for the reverse maps: `python -m kit ensemble OUT_reverse.tif MAP1_reverse.tif MAP2_reverse.tif --method rank`.
- **Parse:** `valid_px` (should be close to the pixels every member predicted), `shape`, `method`, `weights` and `out`.
- **Rerun:** Safe and deterministic; it overwrites `OUT`. Writing over one of the inputs works (all inputs are read first) but loses that input.
- **Success:** Exit code 0 and `valid_px` greater than 0. Whether the ensemble is better is a separate `kit auc` result.
- **Not a pass:** An ensemble AUC without the ensembled reverse as control; an ensemble that does not beat its best member with a `--compare` interval above 0; a `valid_px` far below the members' predicted area (members cover different parts of the surface); `--method mean` across models with different score ranges; members that trained on the scored segment.
- **Go-ahead:** Nothing to run it. Publishing an ensemble of target-scroll maps, or anything learned from one, is never allowed in this public repository.
- **Never:** Average model weights across seeds with it or instead of it; combine maps of different surfaces or crops because their shapes happen to match; call the combined map a reading or say letters were found in it.

## Tests

```bash
python -m unittest tests.test_ensemble -v
```

They cover the dtype scaling of uint8 and uint16 maps and the valid mask, weights, `rank` ignoring each map's scale, tied scores sharing a rank, the refusals (one map, different shapes, wrong weight count, unknown method), and a round trip through the command line to `.tif` and `.npy` that keeps every valid pixel above 0. They skip without numpy and tifffile (the CI's map job installs them). They do not cover `--json`, `--weights` from the command line, float maps above 1, logits, NaN, or real maps.

## History

- 2026-10-09: the module text says PHerc0841 may not be held out from Hecate; no behaviour change (`3ba683f`).
- 2026-10-07: first version, with `mean` and `rank`, the valid-pixel rule and uint16 or float32 output (`ebd4ae3`).

## Related

- [`auc`](auc.md): scores the ensemble, its ensembled reverse control, and the paired difference against the best member.
- [`soup`](soup.md): `scripts/soup.py`, weight averaging within one training run, the other half of "maps across seeds, weights within a run".
- [`gate`](gate.md): Gate A, whose 0.10 control gap is the bar used above.
- [`hpscore`](hpscore.md): the letter-scale score, which the tricks job also reported for each ensemble.
- [tricks.md](../tricks.md): the community tricks, their sources and what they measured here.
- [Tricks job tables](../../scripts/experiments/2026-10-07-cloud/tricks/tables.md): every ensemble and z-window score on the PHerc0841 crops.
- [`results.json`](../results.json): `community` (the reported ensemble gains with their sources) and `held_out`.
