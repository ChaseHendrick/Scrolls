# simcritic: judge how real simulated CT looks

Asks fresh critics, never used in training, to tell real CT windows from simulated tiles, with a real-against-real control and views that say what gives the simulation away.

| Field | Value |
| --- | --- |
| Id | `simcritic` |
| Status | Experimental |
| Kind | kit module |
| Area | Scoring and controls |
| Run | None (library): `from kit import simcritic` |
| Code | `kit/simcritic.py` |
| Tests | `tests/test_simcritic.py` |
| Needs | Python 3.10 or newer, numpy, scipy, torch (CPU or CUDA) for the CNN critics, scikit-image for the ridge view; real CT gray values and simulated tiles as 2D arrays; no labels |
| Runs on | CPU for the feature critic and small checks (planted checks, 2 critics at 400 steps: about 12 minutes in a 4-core cloud container, 25 Nov 2026); a full judge of several sets with every view is best split over many CPU workers or run on a GPU |
| Network | None |
| Writes | Nothing (it returns dicts; `dumps` gives JSON text) |
| Go-ahead | Not needed |
| Released | Scrolls kit (26 Nov 2026) |
| Checked | 2026-11-26 against commit `9cadb40` plus this module (10 tests, about 5 s) |

## What it does

Simulated CT ([scrollsim2](scrollsim2.md), [hardcases](hardcases.md)) comes with exact sheet labels, so it is tempting training data. A model trained on it carries over to real scans only as far as the tiles look like real CT. This tool is a **judge** of that: it asks fresh classifiers ("critics") to tell real CT windows from simulated ones and reports each one's ROC AUC. 0.5 means a critic cannot tell them apart; 1.0 means it always can.

The judge is kept apart from any generator. A generator that trains a discriminator, or tunes presets against its own test, lowers that test's AUC by construction (Goodhart). So the judge refits every critic from scratch on each call, saves no weights, splits by whole real slices and whole simulated tiles (overlapping windows cannot leak between training and scoring), and refuses real slices the generator trained on (`trained_on`). Its verdict uses the **worst** critic (the highest AUC), so a set passes only when no critic separates it.

**Attribution views** say what gives the simulation away. Both sets pass through the same transform before the CNN critic: `marginal` (every window ranked to a uniform gray histogram), `whiten` (also every window's Fourier amplitude set to the pooled mean, keeping phase: edges and geometry), `phaserand` (each window's own amplitude, random phase), `low` (Gaussian sigma 3), `high` (minus Gaussian sigma 1.5), `ridge` (a label-free bright-ridge map: sheet geometry). An AUC that stays high under a view means that view's content still separates the sets.

It reads gray values only, no labels. Its output is a realism measure, not a proof of realism: a critic it does not include may still separate the sets.

## When to use it

- Before simulated tiles go into training, to say how far from real they are on the scan you care about.
- To rank a generator's settings: the attribution views and the feature critic name what still differs.
- As the gate for a "passes as real" claim, with a real-against-real control on the same windows.

Do not use it:

- as a training loss or a tuning target: a judge that is optimized against stops measuring;
- to score ink or surfaces against labels: use [auc](auc.md);
- on data you may not use for development (held-out labels' scans, prize-eligible scrolls under their rules).

## Quick start

```bash
python3 - <<'PY'
import numpy as np
from kit import hardcases, simcritic as sc
# stand-in "real" slices: here simply tiles of another seed; use your own CT slices (2D float arrays)
real = [hardcases.tile(7, k, 256)["image"].astype(np.float32) for k in range(12)]
sim = list(hardcases.tiles(12, 5, 256)["image"])
R, gR = sc.grid_windows(real, 128)                          # real windows, grouped by slice
S, gS = sc.grid_windows(sim, 128)                           # simulated windows, grouped by tile
print(sc.critic_auc(R, gR, S, gS, "feat", folds=3)["auc"])  # two draws of one simulator
PY
```

It printed `0.3971354166666667` (26 Nov 2026, 7 s in a 4-core cloud container): two draws of one simulator, so near 0.5 within the noise of 48 windows a side.

On real CT, load one 2D array per slice, pass a cover mask per slice to `grid_windows` so air is left out, and run `planted` first: the judge must fail and pass known cases before its verdict on a set means anything. Then `judge(R, gR, S, gS)` on the set and on a real-against-real control (for example even against odd slices), and `verdict(result, control)`.

## Checks and controls

- **Planted** (`planted`): two random halves of the real slices, left identical (expect about 0.5), with noise sd 0.08 added to one half, and with one half blurred at sigma 1.0 (expect near 1). On PHerc0343P (25 Nov 2026, 800 steps, feature and CNN critics): identical 0.506 and 0.496, noise 1.0 and 0.993, blur 1.0 and 0.999.
- **Control** (hard rule 4): the same judge on real against real. Its worst AUC is the floor a perfect simulator would reach; `verdict` passes a set only within 0.05 of it and at most 0.60.
- **Refusal**: `judge` refuses real groups listed in `trained_on`.

Cross-scroll validation: claim-dependent. The 25 Nov 2026 judgement covers one public scan (PHerc0343P, development use). A "ScrollSim passes as real" claim would need the same fixed judge on more scans; none is published.

Claim label: Model output (critic AUCs) and Interpretation (attribution).

## Commands and options

None: it is a library. `judge` takes `critics` (any of `CRITICS`: `feat`, `cnn`, `cnn_half`), `views` (any of `VIEWS`), `folds` (3), `seeds` ((0, 1)), `steps` (800 CNN steps per fold), `device` (`cpu` or `cuda`), `trained_on` (real group ids to refuse) and `sink` (called with the partial result after every critic and view, so a run stopped by a time cap keeps what it finished).

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `CriticError` | exception | | ValueError subclass for every refusal |
| `unit(w)` | float32 window | | Scaled to its own 1st to 99th percentiles |
| `grid_windows(images, win=WIN, masks=None, min_cover=0.98, groups=None)` | (windows, groups) | `CriticError` when none fits | Non-overlapping grid |
| `half(images, groups=None, win=WIN, masks=None, min_cover=0.98)` | (windows, groups) | as above | 2*WIN windows pooled 2x2, for the context critic |
| `digest(windows)` | hex SHA-256 | | Of the float32 stack |
| `view(windows, name, ref_amp=None, seed=0)` | transformed stack | `CriticError` | One of `VIEWS` |
| `pooled_amplitude(*sets)` | 2D array | | For the whiten view |
| `ridge_map(w)` | 0/1 float32 map | | Label-free bright ridges |
| `auc(score, y)` | float | `CriticError` with one class | Ties averaged |
| `features(w)` | 46 floats | | The feature critic's input |
| `folds_of(groups, k, seed)` | fold per window | `CriticError` | Groups kept whole |
| `critic_auc(A, gA, B, gB, critic="cnn", folds=3, seed=0, steps=800, device="cpu", feats=None)` | `{"auc", "per_fold"}` | `CriticError` | A is labeled 1 |
| `judge(real, real_groups, sim, sim_groups, real_half=None, sim_half=None, critics=CRITICS, views=("full",), folds=3, seeds=(0, 1), steps=800, device="cpu", trained_on=(), progress=print, sink=None)` | dict (Outputs) | `CriticError` on trained-on groups | |
| `merge(parts)` | judge dict | `CriticError` when parts differ in windows or settings | Seeds run in parallel, merged as one call |
| `verdict(result, control, margin=0.05, ceiling=0.60)` | dict | | The fixed pass rule |
| `planted(real, real_groups, critics=("feat", "cnn"), steps=600, device="cpu", seed=0, progress=print)` | dict of AUCs | | Known cases |
| `dumps(obj)` | JSON text | | Sorted keys |

## Inputs

- Real: 2D float arrays of CT gray values (any size), with an optional cover mask per array; one group id per array.
- Simulated: 2D arrays (uint8 or float) of tiles; one group per tile.
- Windows are 128 px (`WIN`), scaled to their own 1st to 99th percentiles (`unit`). Context windows are 256 px, 2x2 mean-pooled to 128 (`half`).

## Outputs

`judge` returns a dict: `critics.{feat,cnn,cnn_half}.auc` (mean over folds and seeds) with `runs`, `views.NAME.auc`, `worst` and `worst_critic`, `n_real`, `n_sim`, `real_groups`, `digest_real` and `digest_sim` (SHA-256 of the window stacks), `folds`, `seeds`, `steps`. `verdict` returns `verdict` (PASS or FAIL), `worst`, `control_worst`, `margin`, `ceiling` and `gap_to_bar` (worst minus the bar; at most 0 passes).

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `unknown view` | A view name outside `VIEWS` | Use one of `VIEWS` |
| `no window fits` | Every image is smaller than the window or fails the cover mask | Smaller `win`, or check the mask |
| `auc needs both classes` | A fold has windows of one class only | More groups per side |
| `N groups cannot fill K folds` | Fewer groups than folds on one side | Fewer folds, or more slices or tiles |
| `real groups [...] trained the generator; the judge must not score on them` | A real group in `trained_on` was passed | Judge on slices the generator never saw |
| `nothing to merge` | `merge([])` | Pass at least one judge result |
| `parts were judged on different windows or settings` | `merge` got results of different window sets, folds or steps | Merge only seeds of one judgement |
| `whiten needs ref_amp` | `view(..., "whiten")` without `pooled_amplitude` | Pass `ref_amp=pooled_amplitude(A, B)` |

## How it works

1. Windows on a non-overlapping grid, each scaled to its 1st to 99th percentiles.
2. Grouped folds (`folds_of`): whole groups dealt to 3 folds by seed; each fold trains a fresh critic on the others.
3. Critics: `feat` (46 features: 17 gray quantiles, 12 radial log power bands, 9 gradient magnitude quantiles, structure-tensor coherence quartiles at sigma 2 and 5, ridge density and run length; class-balanced L2 logistic); `cnn` (seven 3x3 conv layers, width 24 to 96, LeakyReLU 0.2, dropout 0.3, AdamW 1e-3, 800 steps of 32, random rotations and flips, test-time mean over the 8 symmetries); `cnn_half` (the same on context windows).
4. AUC per fold, mean over folds and seeds 0 and 1; worst over critics.
5. Views run the CNN critic on transformed windows of both sets.

## Cost and time

CPU (4-core cloud container, 25 Nov 2026): features 0.19 s a window; planted checks, 2 critics at 400 steps, 12 minutes. On a Hugging Face `cpu-upgrade` machine one 3-fold CNN critic at 800 steps took about 25 to 30 minutes, so one (set, seed) pair with all views takes about 4 hours on one worker: split sets and seeds over workers and `merge` them. The PHerc0343P judgement below cost 1.74 USD in all (two GPU smoke tests and 16 CPU parts).

## Results

PHerc0343P (a public fragment scan on no prize list), 25 Nov 2026, development use. Real windows: gray values of six slices (z 1460 to 1660); the generator's training slices refused. The pass rule (above) was fixed in a preregistration before the judge ran. Model output:

| Set | Worst-critic AUC | Verdict |
| --- | --- | --- |
| Control: real against real (even against odd slices) | 0.473 | bar 0.523 |
| Hard Cases tiles with the `343p` [simreal](simreal.md) preset, two rounds | 0.999 and 1.000 | FAIL |
| The same tiles passed through a learned sim-to-real texture (not released), five settings | 0.971 to 0.998 | FAIL |

All seven sets fail; the gap to the bar is +0.448 to +0.477. The 46-feature critic is the worst case for 6 of the 7. Disclosed break: 8 of the 16 CPU parts hit their time cap, so the judgement was rebuilt from the parts' log lines; every critic finished on both seeds for every set, but the attribution views did not finish on the control, so the preregistered attribution rule is void.

What gives it away (post-hoc, Interpretation): fitting the feature critic on one feature group at a time, the finest band of the power spectrum (too much power in the simulation) and local orientation coherence (real grain runs along the sheets; simulated grain is less ordered) separate the sets most. Later rounds of the learned texture brought the spectrum group down to 0.685, but coherence stayed at 0.94 to 0.97 in every round.

## For agents

- **Command:** `python3 -c "from kit import simcritic; ..."`: `planted`, then `judge` on the set and on a real-against-real control, then `verdict`.
- **Parse:** `verdict(...)["verdict"]`, `["worst"]`, `["gap_to_bar"]`; `judge(...)["critics"]` and `["views"]`.
- **Rerun:** safe; it writes nothing. Results differ slightly by device and torch version.
- **Success:** planted identical under 0.65 and noise and blur over 0.90, control worst under 0.65, then the set's verdict.
- **Not a pass:** a low AUC from one critic, one seed, or random (ungrouped) splits; an AUC from a critic the generator trained against.
- **Go-ahead:** Nothing.
- **Never:** use it as a training loss; judge on slices the generator trained on.

## Tests

`python3 -m unittest tests.test_simcritic` (10 tests, about 5 s on CPU): AUC on known cases, grid windows and masks, grouped folds, every view's shape, the feature critic failing a different texture and passing a same one, the trained-on refusal, the verdict rule, the merge of parts, and a tiny CNN critic run. Not covered: GPU speed and a full judgement end to end.

## History

- 2026-11-26: released in the Scrolls kit: held-apart judge, planted checks, control, attribution views, partial results through `sink`. ([#382](https://github.com/ChaseHendrick/Scrolls/pull/382))

## Related

- [scrollsim2](scrollsim2.md) and [hardcases](hardcases.md): the simulators whose tiles it judges.
- [simreal](simreal.md): gray-value statistics, a linear realism test and the render fit.
