# simreal: measure how real CT looks and fit the Hard Cases render to it

Gray-value statistics of real CT windows (brightness, noise, grain, sheet width, pitch, contrast), a linear realism test that can fail, and a fit of [hardcases](hardcases.md) render bounds to a scan; with ctmatch, a training augmentation that matches a tile's histogram and noise to real CT.

| Field | Value |
| --- | --- |
| Id | `simreal` |
| Status | Experimental |
| Kind | kit module |
| Area | Training |
| Run | `python -m kit.simreal measure SLICES.npz OUT.json`, `python -m kit.simreal fit OUT.json NAME=SUMMARY.json ...`; library `from kit import simreal, ctmatch` |
| Code | `kit/simreal.py`, `kit/ctmatch.py` |
| Tests | `tests/test_simreal.py`, `tests/test_ctmatch.py` |
| Needs | Python 3.10 or newer, numpy, scipy, scikit-image (Sato ridge filter); torch for `ctmatch.apply` |
| Runs on | CPU. `measure` of 40 windows about 7 s in a 4-core cloud container (26 Nov 2026); a `fit` over the default grid of 108 points at 96 tiles each takes about 30 s a point on one core (measured at 16 tiles, scaled), so about an hour on one core: use `--workers` |
| Network | None |
| Writes | `measure`: one JSON summary; `fit`: one JSON of the ranked points; the library writes nothing (`ctmatch.save` writes a reference `.npz` when asked) |
| Go-ahead | Not needed |
| Released | Scrolls kit (26 Nov 2026) |
| Checked | 2026-11-26 against commit `9cadb40` plus this module (13 tests, about 10 s; the quick start's output below) |

## What it does

Simulated tiles can look unlike real CT in ways a detector notices: noisier, thinner sheets, a different gray histogram. simreal turns "looks like" into numbers, from the real CT's gray values only, never a label:

- `window_stats(w)`: for one 2D window, the bright fraction (share above its Otsu threshold), noise level and noise grain (from ctmatch), and three ridge statistics from the window's own bright ridges (scikit-image Sato, kept where it is a local maximum across the ridge and above its own 80th percentile): `width`, the median best Hessian scale at ridge pixels; `pitch`, twice the median distance from ridge-free midlines to the nearest ridge; `contrast`, ridge pixels' mean minus mid-gap pixels' mean.
- `measure` and `measure_tiles`: those statistics over many windows of real slices or of tiles, summarized by quartiles; `distance` compares two summaries in units of the real spread.
- `fit`: renders Hard Cases tiles under each point of a grid of render bounds (`hardcases.realism` and `hardcases.dense`) and ranks the points by distance to the real summary.
- `features` and `realism_auc`: 35 features per window (17 gray quantiles, 12 log power bands, the six statistics) and a 5-fold L2 logistic regression whose cross-validated ROC AUC says whether a linear classifier can tell real windows from tiles. Two draws of one source score near 0.5, so the test can fail (tested). `random_point` and `search` run a random or local search of render bounds that lowers it.

ctmatch is the training-side partner: `reference(slices)` stores, for many real 256 px windows, 257 gray quantiles, bright fraction, noise and grain; `apply(x, ref)` gives each synthetic tile, with probability P, a blur and added noise that bring its grain and noise to a reference window's, then a rank-preserving quantile map onto that window's histogram. Lines never move; only gray values change.

These are training-data settings and realism measures. They say nothing about what a scan contains.

## When to use it

- To measure a scan's look before making training tiles for it, and to fit render bounds to it.
- To check, with `realism_auc`, whether a linear classifier still separates your tiles from the scan.
- To augment training tiles toward a scan's histogram and noise with `ctmatch.apply`.

Do not use it:

- as proof that tiles pass as real: a linear test is weak; use [simcritic](simcritic.md), the held-apart judge;
- with masks derived from labels you may not use (`measure --no-mask` ignores the npz mask).

## Quick start

```bash
python -m kit.simreal measure SLICES.npz real.json --n 40
```

SLICES.npz holds `ct`, an object array of 2D slices (and optional `mask`). On 4 stand-in slices made from Hard Cases tiles (26 Nov 2026) it printed one JSON line beginning `{"windows": 40, "bright": [0.225, 0.284, 0.366], "noise": [0.084, 0.111, 0.121], ...` (quartiles, rounded here). Then `python -m kit.simreal fit fit.json scan=real.json --workers 4` ranks the render bounds for that scan.

## Checks and controls

- The realism test can fail and pass: two draws of one source score within 0.2 of 0.5, a different source above 0.95 (`tests.test_simreal`).
- `window_stats` follows the image: pitch and width track drawn sheets, noise tracks added noise; flat windows return None and non-finite windows are refused.
- Render bounds leave the default tiles bit for bit unchanged and take effect when set.
- ctmatch keeps every line where it was, moves the histogram toward the reference, and never paints a crowded window's histogram onto a mostly empty tile.

Cross-scroll validation: claim-dependent. The one fitted preset (`PRESETS["343p"]`) covers one public scan, PHerc0343P; a claim that fitted tiles help a detector on real CT needs its own fixed test on real labels.

Claim label: Model output (statistics, AUCs) on the data given.

## Commands and options

`python -m kit.simreal measure SLICES OUT [--n 160] [--no-mask]`: statistics of N random 256 px windows of the slices.

| Argument | Default | Meaning |
| --- | --- | --- |
| `slices` | required | npz with `ct`, an object array of 2D slices, and optional `mask` |
| `out` | required | the summary JSON to write |
| `--n` | 160 | windows to measure |
| `--no-mask` | off | ignore the npz's `mask` (use when it was made from labels) |

`python -m kit.simreal fit OUT NAME=SUMMARY.json [NAME=SUMMARY.json ...] [--n 96] [--seed 5] [--workers 1]`: renders N tiles per grid point once and ranks the points against every named summary.

| Argument | Default | Meaning |
| --- | --- | --- |
| `out` | required | the ranked points JSON to write |
| `real` | required | one or more `NAME=SUMMARY.json`, summaries from `measure` |
| `--n` | 96 | tiles rendered per grid point |
| `--seed` | 5 | tile seed |
| `--workers` | 1 | processes rendering grid points |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `RealError` | exception | | ValueError subclass |
| `window_stats(w)` | dict of `STATS` or None | `RealError` (non-finite) | None for a flat window or too few ridge pixels |
| `summarise(rows)` | dict of quartiles | `RealError` (no usable window) | |
| `measure(slices, masks=None, n=160, seed=0, win=256, min_cover=0.98)` | summary | `RealError` | random full windows |
| `measure_tiles(images, air=None)` | summary | `RealError` | tiles over 5 % air skipped |
| `distance(real, sim, weights=None)` | float | | weighted, in real IQR units |
| `grid_points(grid=None)` | iterator of points | | over `GRID` |
| `render_tiles(point, n=96, seed=5)` | (images, air) | `hardcases.SimError` | tiles under a point's bounds |
| `fit(real, n=96, seed=5, grid=None, progress=print, workers=1, reals=None)` | ranked list (dict with REALS) | | |
| `features(w)` | 35 floats | | |
| `realism_auc(real_feats, sim_feats, folds=5, seed=0, l2=1.0, iters=400)` | float | | random folds: windows of one slice can sit on both sides, so use simcritic for a verdict |
| `windows(slices, masks=None, n=160, seed=0, win=256, min_cover=0.98)` | list of arrays | | |
| `random_point(rng, around=None, spread=0.25)` | point | | in `SPACE` |
| `search(real_feats, points, n=64, seed=5, workers=1)` | list, lowest AUC first | | |
| `PRESETS` | dict | | `343p`: fitted to PHerc0343P (Results) |
| `ridge_lines(s)` | (ridge mask, Sato response) | | of a window already scaled to 0..1 |
| `main(argv=None)` | exit code | | the command line |
| `reference(slices, masks=None, n=512, seed=0, win=256, min_cover=0.98)` | reference dict | `ValueError` | kit.ctmatch: per-window quantiles, bright fraction, noise, grain |
| `apply(x, ref, gen=None, p=0.8, k=16, noise=True, tol=0.15)` | torch tensor, 0 to 255 | | kit.ctmatch: (B, H, W) tiles matched to reference windows |
| `window_stats(w)` | dict | | kit.ctmatch: bright fraction, noise, grain of one window |
| `otsu(v, bins=64)` | float | | kit.ctmatch: Otsu threshold |
| `save(ref, path)`, `load(path)` | None, reference | | kit.ctmatch: a reference as `.npz` |
| `summary(ref)` | dict | | kit.ctmatch: medians of a reference |
| `tile_stats(tiles, n=None)` | dict | | kit.ctmatch: the same statistics for tiles |
| `distance(a, b)` | float | | kit.ctmatch: between two `summary` dicts |
| `blur_sigma(c)`, `grain_sigma(c)` | float | | kit.ctmatch: blur that gives grain C, from the lookup tables |

## Inputs

Real slices as 2D float arrays (any scale), optional cover masks; tiles as uint8 arrays from [hardcases](hardcases.md).

## Outputs

A summary is `{"windows": N, STAT: [q25, q50, q75], ...}` for `bright`, `noise`, `grain`, `width`, `pitch`, `contrast`. `fit` writes `{"real": {...}, "ranked": {NAME: [{"point", "summary", "distance"}, ...]}}`.

| Exit code | Meaning |
| --- | --- |
| `0` | written |
| `1` | an exception (for example `no slice holds a full window`) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `no slice holds a full window` | every slice is smaller than 256 px | larger slices, or call `measure` with a smaller `win` |
| `no usable window` | every window was flat, masked out or had too few ridges | check the mask and the scale |
| `non-finite window` | NaN or Inf in a slice | clean the input |
| `fit: expected NAME=SUMMARY.json, got ...` | a summary argument without a name | write `scan=real.json` |
| `realism: unknown setting` | a bound outside `hardcases.REAL_KEYS` | use `sd`, `psf`, `ply_w`, `rim`, `gap`, `pitch` |
| `ctmatch: no slice holds a full window` | every slice is smaller than the reference window | larger slices or a smaller `win` |
| `ctmatch: only N usable windows` | too few windows passed the cover mask | more slices or a looser mask |

## How it works

Every window is scaled to its own 1st to 99th percentiles. Ridge pixels come from the Sato response at sigmas 1 to 3, thinned to local maxima across the ridge and kept above the response's 80th percentile. The best Hessian scale at each ridge pixel (seven scales, 0.75 to 4) gives the width; the distance transform from ridges gives pitch and the mid-gap pixels for contrast. Noise is the standard deviation of the residual after a Gaussian blur of sigma 1.5, grain its lag-1 correlation.

## Cost and time

`measure` 40 windows: about 7 s (4-core cloud container, 26 Nov 2026). The PHerc0343P preset came from a random then local search on 64 tiles a point.

## Results

PHerc0343P (a public fragment scan on no prize list), 25 Nov 2026, gray values only, development use. Default Hard Cases tiles against real windows: linear realism AUC 0.999. The `343p` preset was picked by a search scored on 120 windows of the scan; on those same windows it scores 0.986, which is selection-biased, and on other windows of the scan its tiles still score 1.000 (0.995 after ctmatch's histogram match). The render knobs alone do not make tiles indistinguishable from real CT; [simcritic](simcritic.md) has the stronger judge's results. Model output.

## For agents

- **Command:** `python -m kit.simreal measure SLICES.npz OUT.json`, then `python -m kit.simreal fit FIT.json scan=OUT.json --workers 4`
- **Parse:** the JSON files; `ranked.scan[0].point` is the best point, usable as `hardcases.tiles(..., dense_look=point)`
- **Rerun:** safe; seeded, files overwritten
- **Success:** exit 0 and a summary with `windows` near N
- **Not a pass:** a low `realism_auc` alone; random folds and one linear critic are weak
- **Go-ahead:** Nothing
- **Never:** fit to a mask made from labels you may not use

## Tests

`python -m unittest tests.test_simreal tests.test_ctmatch` (13 tests, about 10 s): window statistics follow the image, flat and non-finite windows, summary distance, the realism test failing and passing, render bounds (default tiles unchanged, bounds take effect, pitch factor), ctmatch references, line positions kept, histogram moved, the empty-tile guard. Not covered: a full `fit` (minutes of rendering).

## History

- 2026-11-26: released in the Scrolls kit with the `343p` preset. ([#382](https://github.com/ChaseHendrick/Scrolls/pull/382))

## Related

- [hardcases](hardcases.md): the render whose bounds it fits.
- [simcritic](simcritic.md): the held-apart realism judge.
- [scrollsim2](scrollsim2.md): the full-scale synthetic scroll, with its own realism statistics.
