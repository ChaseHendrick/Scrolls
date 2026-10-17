# phantom: synthetic carbon-ink volumes with known truth, to test detectors and AUC noise

`python -m kit phantom` makes small synthetic papyrus surface volumes carrying carbon-ink strokes whose truth is known at every pixel, stress-tests a baseline detector against its depth-reversed control, and compares the AUC spread between phantoms with the one-segment block bootstrap.

| Field | Value |
| --- | --- |
| Id | `phantom` |
| Status | Current |
| Kind | kit command, kit module, script |
| Area | Scoring and controls |
| Run | `python -m kit phantom`, `bash scripts/phantom-demo.sh`, `from kit import phantom` |
| Code | `kit/phantom.py`, `scripts/phantom-demo.sh`, `kit/cli.py` (`cmd_phantom`, `_shape`), `kit/verify.py` (`_numpy`, `VerifyError`) |
| Tests | `tests/test_phantom.py` |
| Needs | Python 3.10 or newer and numpy (no scipy: the blur is a numpy FFT). `stress` and `calibrate` score with `kit.auc`, which needs only numpy here. The demo script needs bash and must run from the repository root, since it calls `python3 -m kit` |
| Runs on | Any CPU. `make` at the command's default size (26 x 384 x 384) took 2.1 s, `stress` with its defaults (8 phantoms) 14.2 s, `calibrate` with its defaults 8.2 s, and the whole demo 14.2 s (measured 2026-10-16, 4-core Xeon cloud container) |
| Network | None |
| Writes | `make`: the folder `OUT` (created before the phantom is checked, so it is left empty on a refusal) and `volume.npy`, `ink.npy`, `mask.npy`, `meta.json` in it, replacing earlier ones. `stress --save-maps DIR`: `DIR/surface_SEED.npy` and `DIR/surface_reversed_SEED.npy` per phantom. `calibrate`: nothing. The demo: everything under `$OUT` (default a fresh `mktemp -d` folder, `${TMPDIR:-/tmp}/phantom-demo.XXXXXX`, whose path it prints first), listed under Outputs |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07 (`eeacf6a`); `kit/phantom.py` is also in the AutoPipeline release copy at `faada83` |
| Guide | [phantom-and-viewer.md](../phantom-and-viewer.md); results of the demo in the [phantom demo log](../logs/2026-10-07-phantom-demo.md) |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

On a real segment, the ink labels are hand drawn and cover about 1 cm2, and only a few segments have them. That makes it hard to tell whether a new detector really reads ink by its depth, or whether the 95 % interval that `kit auc --bootstrap` reports on one segment is as wide as the real spread between sheets. A phantom is a test object with a known answer. Here it is a small surface volume, an array of shape (depth, height, width) like the rendered stacks ink models read, built to look to a detector like a flattened papyrus sheet: a recto fibre layer and a verso fibre layer at right angles, a smooth brightness field across the sheet, per-voxel noise, and carbon-ink strokes (random lines and arcs in rows of letter-sized cells) on the top surface. Carbon ink is close to papyrus in density, so by default the ink adds only a small density step and a small thickness bump, both below the noise. The stroke mask that made the ink is the label, so the truth of every pixel is known.

The command has three actions. `make` writes one phantom: the volume, the ink mask, the scoring mask and a metadata file. `stress` builds N phantoms and runs `surface_detector`, a transparent baseline detector (the density just above the sheet's top surface minus the sheet's interior), on each phantom as stored and with its depth reversed, and scores both maps with `kit auc`'s scorer. `calibrate` draws N stroke layouts, scores a simulated reader of one fixed quality (the blurred truth plus spatially correlated noise) on each, and compares the spread of AUC between phantoms with the mean half width of the block bootstrap (resampling square blocks of pixels, as `kit auc --bootstrap` does) on one phantom.

The strokes are random lines and arcs, not letters of any script. A score on a phantom says nothing about any scroll, and nothing here is a reading. The physics is a sketch: densities are in units of the fibre texture's standard deviation, not calibrated to CT values. `calibrate` does not build a volume at all; it uses only the stroke masks and the simulated reader. The phantoms have been run only at small sizes; whether the calibration carries over to real segments is an untested idea ([log](../logs/2026-10-07-phantom-demo.md)).

## When to use it

- Before trusting a new detector or feature: run it on phantoms it never saw and check that it beats its depth-reversed control there. Plug any detector in by scoring its map on `ink.npy` and `mask.npy` with `kit.auc.score_array`.
- Sizing AUC noise: how the one-segment bootstrap interval compares with the spread between sheets of one difficulty, for a given letter size, block size and reader quality.
- A demonstration of [`auc`](auc.md) and [`view`](view.md) with no scroll data: `bash scripts/phantom-demo.sh`.

Do not use it:

- To rank real ink models: score their maps with [`auc`](auc.md) on labelled segments held out from all of them (PHerc0841).
- To say anything about a scroll, a real model's quality, or letters: phantom strokes are not letters.
- As training data for a real reader: nothing here shows that phantoms look like real CT ink; train on the published labels.
- To look at maps side by side: use [`view`](view.md); the demo shows how.

## Quick start

```bash
python -m kit phantom make OUT/ph --shape 256 256 --depth 16 --seed 7 --letter-px 64
python -m kit phantom stress --shape 256 256 --depth 16 --seed 0 --n 4 --letter-px 64
python -m kit phantom calibrate --shape 256 256 --letter-px 64 --n 10 --quality 0.3 --draws 200 --block-px 32
```

- `OUT`: any folder of yours; `make` writes `OUT/ph/volume.npy`, `ink.npy`, `mask.npy` and `meta.json`.

Run on 2026-10-16 (synthetic data only), `make` printed its metadata, of which:

```
  "cells": 5,
  "ink_fraction": 0.1626,
  "ink_top_layer": 5.6
```

`stress` printed four rows, here as a table:

| Seed | `auc` | `auc_reversed` |
| --- | --- | --- |
| 0 | 0.7377 | 0.312 |
| 1 | 0.7097 | 0.3766 |
| 2 | 0.6984 | 0.2804 |
| 3 | 0.7016 | 0.2543 |

and `calibrate` printed:

```
AUC over 10 phantoms: mean 0.7524, between-phantom 95% half width 0.1352; mean block-bootstrap half width 0.0686 (ratio 0.508); intervals covering the mean 5/10
```

These are the same numbers as the 2026-10-07 [demo log](../logs/2026-10-07-phantom-demo.md): the runs are seeded. It worked when each exit code is 0, `make` wrote four files, every `stress` row has `auc` above `auc_reversed`, and the `calibrate` line holds no `nan`.

## Checks and controls

- **The depth-reversed control** (`stress`). The baseline detector must score clearly better on the phantom as stored than on the same phantom with its depth reversed. In the Quick start it scored 0.70 to 0.74 forward and 0.25 to 0.38 reversed on all four phantoms. A detector that ignored depth order would score about the same both ways. `tests/test_phantom.py` requires forward above 0.55 and reversed at least 0.05 below forward on a 12 x 192 x 192 phantom.
- **A known-truth positive control.** A simulated reader with quality 50 and 0.5 px blur must score above 0.95 against the phantom's own ink mask (`tests/test_phantom.py`), which shows the truth, the mask and the scorer line up.
- **The calibration ratio** (`calibrate`). A ratio of the mean bootstrap half width to the between-phantom 95 % half width near 1 says the one-segment interval is honest for that geometry; well below 1 says it is too narrow. With 95 % intervals, about 95 % of them should cover the mean AUC. The log's run (256 px phantoms, 64 px letters, quality 0.3, 32 px blocks, 10 phantoms) gave 0.508 and 5 of 10. With 10 phantoms the between-phantom spread is itself rough, so read the ratio as a size, not a precise value.
- **Blocks must fit.** On 256 px phantoms, 107 px blocks leave about 4 blocks, some draws hold one class, and the half width comes out `nan` (log, reproduced 2026-10-16). Use blocks small enough for many per phantom.

Claim label: Model output on synthetic data, for the `stress` AUCs and the `calibrate` ratio; the log's reading of the ratio (a one-segment interval understates segment-to-segment noise) is Interpretation, and using phantoms at real size is an Untested idea.

## Commands and options

### `python -m kit phantom`

```
usage: python -m kit phantom [-h] [--shape H W] [--depth DEPTH] [--seed SEED]
                             [--n N] [--letter-px LETTER_PX]
                             [--ink-contrast INK_CONTRAST]
                             [--ink-bump INK_BUMP] [--noise NOISE]
                             [--quality QUALITY] [--draws DRAWS]
                             [--block-px BLOCK_PX] [--save-maps SAVE_MAPS]
                             [--json]
                             {make,stress,calibrate} [out]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `action` | required | `make`, `stress` or `calibrate` (see What it does) |
| `out` | none | `make` only: the output folder; `make` fails with a traceback without it. The other actions ignore it |
| `--shape H W` | none (384 x 384, from `_shape` in `kit/cli.py`) | Height and width of each phantom in pixels. For `make` and `stress`, the shorter side must be at least twice `--letter-px` |
| `--depth DEPTH` | `26` | Layers of the volume, at least 8. `make` and `stress` only |
| `--seed SEED` | `0` | `make`: the phantom's seed. `stress`: the first seed; phantoms use `SEED` to `SEED+N-1`. `calibrate`: phantom `i` draws its strokes with seed `SEED*1000+i` and its reader with `SEED*1000+i+500`; the bootstrap draws use seed `i` whatever `SEED` is |
| `--n N` | `8` | `stress`, `calibrate`: number of phantoms |
| `--letter-px LETTER_PX` | `64` | Side of a letter cell in pixels (64 px is 599.4 um at `VOXEL_UM` 9.366). The stroke width is `max(2, LETTER_PX // 8)` and the scoring mask leaves out an edge of `LETTER_PX // 4`. The Python functions default to 96 |
| `--ink-contrast INK_CONTRAST` | `0.25` | Density added under ink near the top surface, in units of the fibre texture's standard deviation. `make`, `stress` |
| `--ink-bump INK_BUMP` | `0.6` | How far the sheet's top surface rises under ink, in layers (carbon ink's thickness). `make`, `stress` |
| `--noise NOISE` | `1.0` | Standard deviation of the per-voxel Gaussian noise, same units. `make`, `stress` |
| `--quality QUALITY` | `1.0` | `calibrate` only: the simulated reader's signal-to-noise ratio (blurred truth against unit-variance correlated noise) |
| `--draws DRAWS` | `200` | `calibrate` only: bootstrap draws per phantom, at least 20 |
| `--block-px BLOCK_PX` | `107` | `calibrate` only: side of a bootstrap block in pixels (1 mm at 9.366 um, `kit auc`'s `BLOCK_PX`). Too large for small phantoms: use about 32 at 256 px |
| `--save-maps SAVE_MAPS` | none | `stress` only: folder for the detector's maps (`.npy`), created when missing |
| `--json` | off | `calibrate` only: print the whole result as JSON instead of one line. `make` and `stress` always print JSON |

Which options each action reads (any other option is accepted and ignored):

| Action | Reads |
| --- | --- |
| `make` | `out`, `--shape`, `--depth`, `--seed`, `--letter-px`, `--ink-contrast`, `--ink-bump`, `--noise` |
| `stress` | `--shape`, `--depth`, `--seed`, `--n`, `--letter-px`, `--ink-contrast`, `--ink-bump`, `--noise`, `--save-maps` |
| `calibrate` | `--shape`, `--seed`, `--n`, `--letter-px`, `--quality`, `--draws`, `--block-px`, `--json` |

### `bash scripts/phantom-demo.sh`

It takes no arguments and has no `--help`. Run it from the repository root. It runs, logging each command and its output to `$OUT/commands.log`: `phantom make` (seed 7, 256 x 256, 16 layers, 64 px letters) into `$OUT/ph`; `phantom stress` (4 phantoms) with maps in `$OUT/maps`; `phantom calibrate` (10 phantoms, quality 0.3, 32 px blocks); a short Python step that saves the baseline detector's forward and reversed maps and two simulated readers (quality 1 and 3) for phantom seed 7; and `kit view`, which writes `$OUT/viewer.html` and `$OUT/viewer.png` with those four maps over the phantom's labels.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `OUT` | a fresh folder from `mktemp -d "${TMPDIR:-/tmp}/phantom-demo.XXXXXX"` | `scripts/phantom-demo.sh`: the folder for everything the demo writes; the script prints `phantom demo output: PATH` first. A fixed `/tmp` name is avoided because it could be a planted symlink. Set `OUT` to choose a folder; it is created when missing, and its `commands.log` is emptied at the start |
| `TMPDIR` | `/tmp` | `scripts/phantom-demo.sh`: where the default `OUT` folder is made |

## Python API

```python
from kit import auc, phantom
p = phantom.make_phantom((256, 256), depth=16, seed=7, letter_px=64)
fwd = phantom.surface_detector(p["volume"])
rev = phantom.surface_detector(p["volume"][::-1])
print(auc.score_array(fwd, p["ink"], p["mask"])["auc"], auc.score_array(rev, p["ink"], p["mask"])["auc"])
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `gaussian_blur(img, sigma)` | A float64 array of the same shape, blurred over its last two axes | `VerifyError` without numpy | Separable Gaussian by FFT with reflected edges; kernel radius `min(max(1, ceil(3 * sigma)), n - 1)`; `sigma <= 0` returns a copy |
| `make_phantom(shape=(512, 512), depth=26, seed=0, letter_px=96, stroke_px=None, fill=0.7, ink_contrast=0.25, ink_bump=0.6, noise=1.0, drift=0.8, row_gap=0.5)` | `{"volume", "ink", "mask", "meta"}`: float32 (depth, h, w), bool (h, w), bool (h, w), and the metadata dict under Outputs | `VerifyError` for `depth` below 8, or a shorter side under `2 * letter_px` | `stroke_px` defaults to `max(2, letter_px // 8)`; `fill` is the share of letter cells that get strokes; `drift` the brightness field's amplitude; `row_gap` the gap between rows as a share of the letter size. The defaults differ from the command's (512 x 512, 96 px letters) |
| `surface_detector(volume, band=2)` | float32 (h, w) map in [0.001, 0.999] | Nothing of its own | The baseline reader: finds the layer of the steepest rise in mean density (entering the sheet), takes the mean of that layer and the next `band` minus the mean of the 4 layers after a 1-layer gap, blurs by 2 px and rescales. Fed the reversed volume, it is its own control. Too few layers after the rise give NaN |
| `simulated_reader(ink, quality=1.0, blur_px=4.0, noise_px=6.0, seed=0)` | float32 (h, w) map in [0.001, 0.999] | Nothing of its own | `quality` times the standardized blurred truth plus standardized noise blurred by `noise_px`, rescaled. Never exactly 0, since `kit auc` drops zeros as unpredicted |
| `calibrate(n=12, shape=(512, 512), letter_px=96, quality=1.0, draws=200, block_px=107, seed=0)` | The `calibrate` dict under Outputs | `VerifyError` from `kit.auc.block_bootstrap`: fewer than 20 draws, a block under 1 px, an empty mask, or a phantom with no ink | Uses stroke masks only (fill 0.7, row gap 0.5), no volume. The defaults differ from the command's (8 phantoms, 384 x 384, 64 px letters) |

`VOXEL_UM = 9.366` is used only for `letter_um` in the metadata.

## Inputs

None from disk: every phantom is generated from its arguments and a seed. Units: sizes and widths are pixels (one pixel is `VOXEL_UM`, 9.366 um, as on the 9 um surface grid); depth is in layers; `--ink-contrast` and `--noise` are in units of the fibre texture's standard deviation, which is 1 by construction; `--ink-bump` is in layers. To test your own detector, load `volume.npy` from `make` (axis 0 is depth, with the top surface near layer `0.35 * depth`), write a 2D map of shape (h, w), and score it against `ink.npy` and `mask.npy`.

## Outputs

**`make`** writes four files to `OUT` and prints `meta.json`'s content:

| File | Content |
| --- | --- |
| `volume.npy` | float32 (depth, h, w): the phantom |
| `ink.npy` | bool (h, w): the stroke mask, the truth |
| `mask.npy` | bool (h, w): where to score, everything except an edge of `LETTER_PX // 4` |
| `meta.json` | The fields below |

| Field | Type | Meaning |
| --- | --- | --- |
| `seed` | int | The seed |
| `shape` | [int, int, int] | depth, h, w |
| `letter_px`, `stroke_px` | int | Letter cell side and stroke width, in pixels |
| `letter_um` | float | `letter_px * 9.366`, one decimal |
| `cells` | int | Letter cells that got strokes |
| `fill`, `ink_contrast`, `ink_bump`, `noise`, `drift` | float | The settings used (`fill` 0.7 and `drift` 0.8 from the command) |
| `ink_fraction` | float | Share of ink pixels inside `mask`, 4 decimals |
| `ink_top_layer` | float | `0.35 * depth`, where the sheet's top surface sits away from ink |

**`stress`** prints JSON:

| Field | Type | Meaning |
| --- | --- | --- |
| `detector` | str | Always `surface_detector` |
| `ink_contrast`, `ink_bump`, `noise` | float | The settings used |
| `rows[].seed` | int | The phantom's seed |
| `rows[].auc` | float (4 decimals) or null | AUC of the detector on the phantom as stored |
| `rows[].auc_reversed` | float (4 decimals) or null | AUC on the depth-reversed phantom, the control |

With `--save-maps DIR`, it also writes `DIR/surface_SEED.npy` and `DIR/surface_reversed_SEED.npy`, float32 (h, w).

**`calibrate`** prints `AUC over N phantoms: mean M, between-phantom 95% half width E; mean block-bootstrap half width B (ratio R); intervals covering the mean K/N`, or with `--json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `n`, `shape`, `letter_px`, `quality`, `block_px`, `draws` | as given | The settings |
| `auc_mean` | float | Mean AUC over the phantoms |
| `auc_sd_between` | float | Their standard deviation (ddof 1) |
| `empirical_half_width` | float | `1.96 * auc_sd_between`, the between-phantom 95 % half width |
| `bootstrap_half_width_mean` | float | Mean of the per-phantom bootstrap half widths |
| `ratio_bootstrap_to_empirical` | float | `bootstrap_half_width_mean / empirical_half_width`, 3 decimals |
| `intervals_covering_mean` | str | `K/N`: phantoms whose bootstrap 95 % interval contains `auc_mean` |
| `rows[].phantom`, `.auc`, `.ci95`, `.half_width` | int, float, [float, float], float | Per phantom: index, AUC, bootstrap interval, its half width |

A float can be `NaN` (blocks too large, or `--n 1`); the JSON then holds the bare word `NaN`, which strict JSON parsers reject.

**The demo** writes under `$OUT`: `commands.log`, `ph/` (the `make` files), `maps/` (8 maps), `surface.npy`, `surface_reversed.npy`, `sim_q1.npy`, `sim_q3.npy`, `viewer.html` (654 KB on 2026-10-16) and `viewer.png`.

| Exit code | Meaning |
| --- | --- |
| `0` | Done. `calibrate` can still print `nan`: check the numbers |
| `1` | An error the command does not catch, with a Python traceback: `make` without `OUT`, or numpy missing |
| `2` | Bad settings, with the message on stderr (see Failure modes), or a usage error from the argument parser |

The demo script always exits 0, even when a step fails (see Failure modes).

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as an action other than `make`, `stress` or `calibrate` | Check the command against Commands and options |
| `a phantom needs at least 8 layers`, exit code 2 | `--depth` below 8 | Use 8 or more; the demo uses 16 |
| `the phantom is too small for its letter size`, exit code 2 | `make` or `stress` with a shorter side under twice `--letter-px` | Raise `--shape` or lower `--letter-px` |
| `use at least 20 bootstrap draws`, exit code 2 | `calibrate --draws` below 20 | Use 200 |
| `block size must be at least 1 px`, exit code 2 | `calibrate --block-px` 0 or less | Use about 32 on 256 px phantoms |
| `the mask holds only one class; no AUC to resample`, exit code 2 | `calibrate` drew a phantom with no ink, usually because the shape is too small for the letter size (`calibrate` does not check that) | Raise `--shape` or lower `--letter-px` |
| `no supervised pixels to resample`, exit code 2 | `calibrate` with an empty scoring mask, such as `--letter-px` below 4 | Use a letter size of 4 px or more |
| `mean block-bootstrap half width nan (ratio nan)` and a `RuntimeWarning: invalid value encountered in divide`, exit code 0 | Blocks too large for the phantom: some draws hold one class (107 px blocks on 256 px phantoms) | Lower `--block-px` |
| `TypeError: argument should be a str or an os.PathLike object ... not 'NoneType'` and a traceback, exit code 1 | `make` without `OUT` | Give the output folder |
| `ModuleNotFoundError: No module named 'numpy'` and a traceback, exit code 1 | numpy is not installed (the command imports it first) | `python -m pip install numpy` |
| `numpy is required. Run inside villa's environment: uv run --project "$VILLA/vesuvius" --extra models python -m kit verify ...` | numpy is missing when calling `kit.phantom` from Python | Install numpy |
| `No module named kit` for each step of the demo, and exit code 0 | `scripts/phantom-demo.sh` run outside the repository root; its `run` helper pipes every step through `tee`, so a failing step does not stop it | Run it from the repository root, and check that `$OUT/viewer.html` exists rather than trusting the exit code |

## How it works

`make_phantom`:

1. **Strokes.** Letter cells of side `letter_px` are laid in rows, `int(letter_px * (1 + row_gap))` apart (1.5 letters with `row_gap` 0.5) and `int(letter_px * 0.9)` apart across, with a margin of `letter_px // 2`. Each cell gets strokes with probability `fill` (0.7), then 2 to 4 of them: 60 % straight segments between two random points of the cell, the rest arcs of radius 0.25 to 0.5 letters around the cell's centre, spanning 0.6 to 1.6 times pi. A pixel is ink within `stroke_px / 2` of a stroke. The mask is softened by a Gaussian of `stroke_px / 4`.
2. **Papyrus.** Recto fibres are noise blurred by 0.8 px along rows and 12 px along columns, verso fibres the other way round, each scaled to mean 0 and standard deviation 1. A brightness field is noise blurred by a sixth of the shorter side, scaled to `drift` (0.8).
3. **Sheet.** Along depth, the sheet fills from its top surface at `0.35 * depth` (raised by `ink_bump` times the softened ink) to its bottom at `0.65 * depth`, with logistic edges of steepness 3. Above the middle (`0.5 * depth`) it carries the recto texture, below it the verso. Density is occupancy times `2.0 + texture + field`.
4. **Ink.** `ink_contrast` times the softened ink is added in a Gaussian of 1 layer centred one layer inside the top surface.
5. **Noise.** Gaussian noise of standard deviation `noise` is added to every voxel; the scoring mask leaves out an edge of `letter_px // 4`.

`surface_detector` takes the mean density per layer, picks the layer after which it rises most steeply (entering the sheet), and returns the mean of that layer and the next `band` (2) minus the mean of the 4 layers starting `band + 2` below it, blurred by 2 px and rescaled from its 0.5 and 99.5 percentiles to [0.001, 0.999]. On the reversed volume it finds the other face, where there is no ink. `simulated_reader` adds `quality` times the standardized truth, blurred by 4 px, to standardized noise blurred by 6 px, rescaled the same way. `calibrate` scores each simulated map with `kit.auc.score_array` and resamples it with `kit.auc.block_bootstrap` ([auc](auc.md) explains both), then compares the spreads as listed under Outputs.

No published method is followed. The guide records a prior-art check: [`NOVELTY.md`](../NOVELTY.md), `tricks.md`, the [literature log](../logs/2026-10-07-literature.md) and `papers.json` held no synthetic phantom with known ground truth ([guide](../phantom-and-viewer.md)).

## Cost and time

Measured 2026-10-16 in a 4-core Intel Xeon cloud container (lscpu: 2.80 GHz, 15 GB RAM), numpy 2.5.3, with Python start-up included:

| Run | Wall time | Peak memory |
| --- | --- | --- |
| `make` at the command's defaults (26 x 384 x 384) | 2.1 s | 225 MB |
| `make --shape 256 256 --depth 16 --letter-px 64` | 1.6 s | Not measured |
| `stress` at the command's defaults (8 phantoms) | 14.2 s | 288 MB |
| `stress` in the Quick start (4 phantoms of 16 x 256 x 256) | 3.6 s | Not measured |
| `calibrate` at the command's defaults (8 phantoms, 384 px) | 8.2 s | Not measured |
| `calibrate` in the Quick start (10 phantoms, 256 px) | 8.1 s | Not measured |
| `make --shape 1024 1024 --letter-px 256` (26 layers) | 20.5 s | 1.34 GB |
| `calibrate --shape 1024 1024 --letter-px 256 --n 4` | 9.7 s | Not measured |
| `bash scripts/phantom-demo.sh` | 14.2 s | Not measured |

Memory grows with depth times height times width (several float64 copies of the volume). Everything runs on a CPU; nothing needs a GPU or Modal. On Chase's Mac, wrap a long run with `python -m kit run local SLUG -- python -m kit phantom ...` (the local compute rule in [`AGENTS.md`](../../AGENTS.md)).

## For agents

- **Command:** `python -m kit phantom stress --shape 256 256 --depth 16 --n 4 --letter-px 64` and `python -m kit phantom calibrate --shape 256 256 --letter-px 64 --n 10 --quality 0.3 --block-px 32 --json`; `python -m kit phantom make OUT --shape 256 256 --depth 16 --letter-px 64` for files to test your own detector on.
- **Parse:** `stress`: `rows[].auc` and `rows[].auc_reversed`. `calibrate --json`: `ratio_bootstrap_to_empirical`, `intervals_covering_mean`, `auc_mean`, `bootstrap_half_width_mean`. `make`: the four files and `ink_fraction` in `meta.json`.
- **Rerun:** Safe and deterministic for the same arguments and numpy version. `make` replaces its four files; `stress --save-maps` replaces the maps of the same seeds.
- **Success:** Exit code 0; `auc` above `auc_reversed` in every `stress` row; no NaN in `calibrate`'s numbers.
- **Not a pass:** A `nan` ratio; a ratio from a few phantoms read as precise; a detector that beats its reversed control on phantoms but has not been scored on real held-out labels; `calibrate` numbers expected to move with `--depth`, `--noise`, `--ink-contrast` or `--ink-bump`, which it ignores; the demo's exit code 0 without its output files.
- **Go-ahead:** Nothing.
- **Never:** Call a phantom stroke a letter or a phantom score a reading; cite a phantom AUC as evidence about a scroll or about a real model; put phantom numbers in `results.json` as segment results.

## Tests

```bash
python -m unittest tests.test_phantom -v
```

`PhantomTest` builds a 12 x 192 x 192 phantom and checks its shape and ink fraction, that the baseline detector scores above 0.55 forward and at least 0.05 lower reversed, that a near-perfect simulated reader scores above 0.95, and that the blur keeps the shape and the mean. The same file's `ViewerTest` covers [`view`](view.md), not this tool. They skip without numpy. They do not cover the command line, `calibrate`, `--save-maps`, the error messages or `scripts/phantom-demo.sh`.

## History

- 2026-10-07: the demo log and panels; the demo's `calibrate` step uses quality 0.3 and 32 px blocks, since 107 px blocks gave `nan` on 256 px phantoms (`afe8d3c`).
- 2026-10-16: the demo writes to a fresh `mktemp -d` folder by default instead of `/tmp/phantom-demo` (`da68987`).
- 2026-10-07: first version: `make`, `stress`, `calibrate`, and `scripts/phantom-demo.sh` (`eeacf6a`).

## Related

- [phantom-and-viewer.md](../phantom-and-viewer.md): the guide to this tool and `kit view`.
- [Phantom demo log](../logs/2026-10-07-phantom-demo.md): the demo's numbers and the calibration's interpretation.
- [`auc`](auc.md): the scorer and the block bootstrap that `stress` and `calibrate` call.
- [`view`](view.md): the one-file HTML viewer the demo ends with.
- [`layers`](layers.md): the depth-shuffle control, the second depth control on real volumes.
- [STANDARDS.md](../STANDARDS.md): lists this tool as the known-truth calibration.
