# simgan: learn a real CT look for simulated sheet tiles

Trains a small generator that repaints ScrollSim Hard Cases physics tiles with the texture of real CT, while keeping every sheet where the layout put it, so the exact sheet labels still hold.

| Field | Value |
| --- | --- |
| Id | `simgan` |
| Status | Experimental |
| Kind | kit module |
| Area | Training |
| Run | `python -m kit.simgan real\|tiles\|train\|realize\|linekeep`; library: `from kit import simgan` |
| Code | `kit/simgan.py` |
| Tests | `tests/test_simgan.py` |
| Needs | Python 3.10 or newer, numpy, scipy, scikit-image, torch, safetensors; for `linekeep` also `opencv-python-headless` and Synthetic-Slices at `bf8d26f5` (`pip install --no-deps git+https://github.com/vincentl065/Synthetic-Slices@bf8d26f502ed38c188c409d7f3011a7a11c4cf89`); real CT gray values as 2D slices (the R343-v1 reference from [simscore](simscore.md) is the tested one) |
| Runs on | A GPU for training (0.064 s a step on an NVIDIA RTX PRO 6000, so about 6.5 minutes for 6,000 steps, measured 27 Nov 2026); CPU only for tiny runs (about 13 s a step in a 4-core cloud container); `tiles`, `realize` and `linekeep` run on CPU |
| Network | None (fetch the reference first with `python -m kit.simscore reference R343.npz`) |
| Writes | The npz or safetensors file named on the command line, and `G.safetensors.json` beside a trained generator |
| Go-ahead | Not needed |
| Released | Scrolls kit (27 Nov 2026) |
| Checked | 2026-11-27 against commit `de415de` plus this module (15 tests, about 4 s on CPU) |

## What it does

[Hard Cases](hardcases.md) draws exact papyrus sheet layouts and renders them with hand-made CT physics. A realism judge ([simcritic](simcritic.md), [simscore](simscore.md)) still tells those tiles from real CT almost every time: raw tiles score a worst-critic AUC near 1.0, where 0.5 would mean the judge cannot tell them apart. Changing the render knobs alone did not close that gap.

simgan learns the rest of the look from real CT. A small U-Net G takes a physics tile and a noise channel and adds a residual to the tile. It trains against a patch discriminator D that sees unlabelled real windows (least-squares GAN). A structure loss keeps the blurred (sheet-scale) image of G's output equal to the blurred input, so sheets stay in place and the tile's `lines` and `sheet_id` truth still apply after the repaint. Optional terms match the real windows' log radial spectrum (`spec_w`), grain statistics (`grain_w`) and high band (`hi_w`), and can steer the residual along the local sheet direction (`oriented`: `full`, `band:S` or `mix:A`), because real grain runs along the sheets.

It is a development tool. No simgan setting has passed the realism bar so far (see Results), so a detector trained on realized tiles is still trained on synthetic data, and scores on synthetic data say nothing about a real scroll. The real side holds gray values only, never labels.

## When to use it

- You train a sheet or line detector on ScrollSim tiles and want tiles whose texture is closer to real CT, with the same exact truth.
- You want to study what separates simulated CT from real CT, with the judge kept apart from the generator.

Do not use it:

- As a realism verdict: score the realized tiles with [simscore](simscore.md) (SRS-1), declaring the slices G trained on.
- On CT a test will score on: those windows would become part of the generator. The command line trains on even slices only, so the odd ones stay free for the judge.
- For ink: it repaints gray values of sheets; it has no ink model. See [scrollsim2](scrollsim2.md) for the ink writer.

## Quick start

```bash
python -m kit.simscore reference R343.npz                 # public PHerc0343P slices, about 14 s
python -m kit.simgan real R343.npz REAL.npz               # 3,000 training windows from the even slices
python -m kit.simgan tiles TILES.npz --n 4000             # Hard Cases tiles under the R4 preset
python -m kit.simgan train TILES.npz REAL.npz G.safetensors --steer band:4 --device cuda
python -m kit.simgan realize G.safetensors TILES.npz OUT.npz --device cuda
python -m kit.simgan linekeep OUT.npz
python -m kit.simscore score --reference R343.npz --sim OUT.npz --generator "simgan band:4" --attempts 0 \
    --trained-on z1460 z1540 z1620 --out record.json
```

`R343.npz`, `REAL.npz`, `TILES.npz`, `G.safetensors` and `OUT.npz` are file names of your choice. On a 4-core CPU with tiny sizes (`tiles --n 16`, `train --steps 3 --hold 4`) the chain printed (27 Nov 2026):

```
wrote t.npz: 15 of 16 tiles kept (air at most 5 %)
wrote real.npz: 40 windows of 256 px from slices [0, 2] of 4
wrote g.safetensors and g.safetensors.json
wrote o.npz: 15 realized tiles
{"realized": 0.6893121142585122, "physics": 0.6890563258530294}
```

It worked if `realize` writes as many tiles as asked and `linekeep` shows the realized tiles keeping about the physics tiles' line F1. A 3-step G changes almost nothing; a real run uses 6,000 steps on a GPU.

## Checks and controls

- **Realism, the control that can fail:** run [simscore](simscore.md) on the realized set and read its real-against-real control (even against odd slices, about 0.47 to 0.50 on R343-v1). A set passes only when the worst critic sits within 0.05 of the control and at most 0.60. Every simgan set so far fails.
- **Sheets kept:** `linekeep` runs a ridge filter (Sato) and Synthetic-Slices' NMS line extraction on the realized tiles and on their physics tiles, and scores each against the layout's true lines (F1 at 2 px). A G that moves or erases sheets lowers the realized number below the physics one.
- **Training split:** `real` takes the even slices of the reference; declare their names to `simscore score --trained-on`, which refuses odd slices listed as trained on.

Claim label: Model output, for every number on this page. The Results are a development judgement on one public fragment scan (PHerc0343P), not an SRS-1 record and not a test on any other scroll; no cross-scroll claim is made.

## Commands and options

### real

```
python -m kit.simgan real REFERENCE OUT [--n 3000] [--seed 1] [--win 256]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `REFERENCE` | | npz with `ct` (N, H, W) or an object array of 2D slices, such as the output of `kit.simscore reference` |
| `OUT` | | npz to write: `real` (n, win, win) float32 unit-scaled windows, `slices` (the even indices used) |
| `--n` | 3000 | windows to draw |
| `--seed` | 1 | window draw seed |
| `--win` | 256 | window size in px |

### tiles

```
python -m kit.simgan tiles OUT [--n 4000] [--seed 41] [--preset r4|none]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `OUT` | | npz to write: `image` (uint8), `lines`, `sheet_id` of the kept 256 px tiles |
| `--n` | 4000 | tiles to draw; those with more than 5 % air are left out |
| `--seed` | 41 | Hard Cases seed |
| `--preset` | `r4` | render bounds (`PRESETS`); `none` keeps the Hard Cases defaults |

### train

```
python -m kit.simgan train TILES REAL OUT [--steer MODE] [--steps 6000] [--seed 1] [--lam 10] [--sigma 1.5]
    [--spec 1] [--grain 5] [--hi 0] [--d-width 128] [--hold 240] [--device cpu]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `TILES`, `REAL` | | outputs of `tiles` and `real` |
| `OUT` | | G as safetensors; its settings and last losses go to `OUT.json` |
| `--steer` | none | `none`, `full`, `band:S` (steer only the residual's low band below S px) or `mix:A` |
| `--steps` | 6000 | training steps (batch 16) |
| `--seed` | 1 | training seed |
| `--lam`, `--sigma` | 10, 1.5 | structure loss weight and its blur in px |
| `--spec`, `--grain`, `--hi` | 1, 5, 0 | weights of the spectrum, grain and high-band terms |
| `--d-width` | 128 | discriminator channels |
| `--hold` | 240 | last tiles kept out of training |
| `--device` | cpu | `cuda` for a real run |

### realize

```
python -m kit.simgan realize G TILES OUT [--n 2000] [--seed 0] [--device cpu]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `G` | | a trained generator (`train` OUT) |
| `TILES` | | `tiles` OUT |
| `OUT` | | npz to write: `image` (realized uint8), `phys` (the input tiles), `lines`, `sheet_id` |
| `--n` | 2000 | first N tiles to realize |
| `--seed` | 0 | noise seed |
| `--device` | cpu | `cuda` on a GPU |

### linekeep

```
python -m kit.simgan linekeep NPZ [--n 64] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `NPZ` | | npz with `image`, `lines` and optional `phys` (`realize` OUT) |
| `--n` | 64 | first N tiles scored |
| `--json` | off | print `{"realized": F1, "physics": F1}` as JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `train(sim, real, steps=8000, device="cpu", seed=1, ..., oriented=False, hi_w=0, edit=None, score=None, score_ratio=0, init=None)` | G (eval mode), losses in `G.kit_log` | `GanError` on a non-finite loss | `sim` (N, H, W) any numeric type; `real` (M, H, W) already `unit()` scaled; `edit` and `score` are optional callables for an edit or a score prior inside the loop; `init` fine-tunes a saved G |
| `realize(G, images, device="cpu", batch=32, seed=0, edit=None)` | uint8 (N, H, W) | `GanError` on a non-finite tile | per-window unit view written over -0.25..1.25 |
| `save(G, path)`, `load(path, device)` | None, G | | safetensors with the steering mode in its metadata |
| `cnn_auc(real, fake, device, steps=600)` | float | | a quick fresh-CNN AUC on held-out halves; not a verdict |
| `line_keep(images, lines, n=64)` | float | `GanError` without Synthetic-Slices or on a non-finite map | mean line F1 at 2 px |
| `f1(pred, ref, mask=None, tol=2)`, `ridge(img)`, `extract(prob, mask)` | float, array, bool array | `GanError` (extract) | the parts of `line_keep` |
| `steer_mode(x)`, `steer_residual(r, x, mode)`, `steer_t(r, x)` | str, tensor, tensor | `GanError` on a bad mode | residual steering along the sheets |
| `radial_profile_t`, `grain_stats_t`, `hi_band_t`, `orientation_t`, `blur_t`, `straight_through` | tensors | | the loss terms' parts |
| `real_windows(slices, n, seed, win)`, `physics_tiles(n, seed, preset)` | arrays, dict | | what `real` and `tiles` run |
| `unit(w)`, `unit_t(x)` | array, tensor | | per-window 1st..99th percentile scaling |
| `build(width=32, d_width=64, oriented=False)` | (G, D) | `GanError` on a bad steering mode | the untrained networks |
| `main(argv=None)` | exit code | | the command line |

Constants: `PRESETS["r4"]` (render bounds), `DEFAULTS` (the measured settings), `SIGMA` 2.0 and `LAM` 10.0 (library defaults), `TOL` 2 px.

## Inputs

- Real CT: 2D gray-value slices in any linear scale (each window is rescaled to its own 1st..99th percentiles). The tested reference is R343-v1: six axial slices of PHerc0343P, a public fragment scan on no prize list, level 2 of the 2.215 um scan resampled to 9.362 um ([simscore](simscore.md)).
- Physics tiles: uint8 (N, 256, 256) from [hardcases](hardcases.md), with `lines` and `sheet_id`.

## Outputs

| File | Keys |
| --- | --- |
| `real` OUT | `real` float32 (n, win, win), `slices` int |
| `tiles` OUT | `image` uint8, `lines`, `sheet_id` |
| `train` OUT, OUT.json | G weights; JSON with `steer`, `steps`, `seed`, `lam`, `sigma`, `spec`, `grain`, `hi`, `d_width`, `hold`, `seconds`, `loss_last` |
| `realize` OUT | `image` uint8 (realized), `phys`, `lines`, `sheet_id` |
| `linekeep` | `{"realized": F1, "physics": F1}` |

Files are written under a temporary name and renamed, so a half-written file never sits at the final path.

| Exit code | Meaning |
| --- | --- |
| `0` | the command wrote its file or printed its numbers |
| `1` | an error, such as missing Synthetic-Slices for `linekeep` or a non-finite loss |
| `2` | a usage error |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `GanError: line_keep needs Synthetic-Slices and OpenCV: pip install opencv-python-headless && pip install --no-deps git+https://github.com/vincentl065/Synthetic-Slices@bf8d26f502ed38c188c409d7f3011a7a11c4cf89` | The line extraction package is missing | Install the two packages named in the message |
| `GanError: non-finite ridge map: NaN or Inf, refused before scoring` | A tile holds NaN or Inf | Check the input tiles; a non-finite map is never scored |
| `GanError: non-finite realized tile` | G produced NaN or Inf | Retrain with another seed or lower weights; never use the set |
| `GanError: steer mode ...: use full, band:SIGMA or mix:ALPHA` | An unknown steering mode | Use `none`, `full`, `band:S` or `mix:A` |
| `GanError: steer mode ...: band needs SIGMA > 0, mix needs 0 < ALPHA <= 1` | A steering value out of range | Pick S above 0, or A in (0, 1] |
| `GanError: non-finite loss at step N` | Training diverged | Lower the learning rate or the extra term weights, or change the seed |
| `--hold H leaves no training tiles of N` (exit 1) | `--hold` is at least the tile count | Draw more tiles or lower `--hold` |
| A CNN AUC that moves by 0.1 between two judgements of one set | GPU nondeterminism and critic seeds | Judge every compared set in one process, with several critic seeds |

## How it works

1. `real` draws 256 px windows from the even reference slices and scales each to its own 1st..99th percentiles.
2. `tiles` renders Hard Cases tiles under `PRESETS["r4"]`, bounds fitted on CPU to median window statistics of the R343-v1 slices (width and pitch weighted most); the fit record does not say the odd slices were left out, so treat these eight bounds as having seen them.
3. `train`: each step G repaints a batch of augmented physics tiles; D (spectral norm, 128 channels) learns real against repainted in the per-window view; G's loss is the adversarial term plus `lam` times the L1 between the Gaussian blurs (sigma 1.5 px) of its output and its input, plus the optional spectrum, grain and high-band terms against the real batch. Adam, learning rate 2e-4, betas 0.5 and 0.999. The output layer starts at zero, so G starts as the identity.
4. Steering `band:S` blurs G's residual at S px, smooths that low band along the local sheet direction (a bank of 8 oriented Gaussians blended by a von Mises weight on the structure-tensor angle) and adds back the free fine band.
5. `realize` runs G once per tile with a fresh noise channel.

## Cost and time

Measured 27 Nov 2026: 0.064 s a training step on an NVIDIA RTX PRO 6000 (about 6.5 minutes for 6,000 steps); two trainings sharing that GPU took 0.125 s a step each, so packing gives no speed. CPU: about 13 s a step in a 4-core cloud container, fine for a smoke test only. Judging eight sets at three CNN critic seeds took about 6 minutes on the same GPU.

## Results

PHerc0343P (a public fragment scan on no prize list), 27 Nov 2026, development use. Every setting starts from R4 tiles, trains 6,000 steps with structure loss 10 at 1.5 px, spectrum 1, grain 5 and a 128-channel discriminator, on windows of the even R343-v1 slices, three training seeds each. Each realized set (four 128 px windows from each of its first 50 tiles, which G trained on; the odd real slices were never seen) was judged against the odd slices with [simcritic](simcritic.md)'s feature critic and its CNN critic at three critic seeds; truth line keep is the AUC of the lightly blurred gray value on true line pixels against the rest. This is a development harness, not an SRS-1 record. Model output:

| Setting | Feature critic | CNN critic per training seed | CNN critic mean (training SD, critic SD) | Truth line keep |
| --- | --- | --- | --- | --- |
| Control: even against odd real slices | 0.497 | | 0.485 | |
| Raw R4 tiles, no simgan (earlier judgement, same harness) | 0.997 | | 0.981 | 0.637 |
| Free residual | 0.976 | 0.899, 0.796, 0.946 | 0.880 (0.077, 0.021) | 0.662 |
| `band:4` steering | 0.980 | 0.639, 0.763, 0.817 | **0.740** (0.092, 0.062) | 0.657 |
| `band:2` steering | 0.976 | 0.767, 0.782, 0.764 | 0.771 (0.010, 0.063) | 0.648 |
| High-band term (`hi_w` 2) | 0.980 | 0.820, 0.722, 0.842 | 0.795 (0.064, 0.034) | 0.652 |
| 1,500-step fine-tune of the free setting | 0.986 | 0.856, 0.948, 0.949 | 0.918 (0.054, 0.021) | 0.638 |

- No setting passes: the bar is 0.60 on both critics, and the feature critic stays at 0.976 to 0.986.
- Under a rule fixed before these runs, `band:4` and the high-band term beat the free residual on the CNN critic. A repeat check weakens both: one set judged in two GPU Jobs gave CNN 0.856 and 0.950 (nondeterministic GPU kernels), larger than the high-band margin (0.086) and close to `band:4`'s (0.141). A confirmation with fixed kernels and three more seeds was planned on 27 Nov 2026; its numbers are not in yet.
- An edit by a conditional diffusion model trained on other PHerc0343P slices (not released), applied inside the training loop (`edit`) or as a score prior (`score`), made things worse: CNN 0.927 and 0.945, and G alone learned to lean on the edit (1.000). The hooks stay in the code for others' priors.
- Interpretation: the steering lowers the CNN critic, which looks at local texture, but the 46-feature critic still separates the sets almost perfectly, so the gray-value statistics it measures (fine spectrum, grain coherence) are not yet matched.

## For agents

- **Command:** `python -m kit.simgan train TILES.npz REAL.npz G.safetensors --steer band:4 --device cuda`, then `realize`, then `python -m kit.simgan linekeep OUT.npz --json`.
- **Parse:** `linekeep --json` gives `realized` and `physics` F1; `G.safetensors.json` gives the settings and last losses.
- **Rerun:** safe; each command overwrites only its OUT file. GPU training is not bit-for-bit repeatable.
- **Success:** exit 0, realized F1 within about 0.01 of physics F1, then an SRS-1 record from `simscore score`.
- **Not a pass:** a low `cnn_auc` from this module, one seed or one critic; any number without the real-against-real control.
- **Go-ahead:** Nothing, unless you rent compute or upload weights.
- **Never:** train G on slices a test scores on; call realized tiles real CT; use the judge's critics as a training loss.

## Tests

`python3 -m unittest tests.test_simgan` (15 tests, about 4 s on CPU): training and realizing keep shapes and dtypes, the wider discriminator, oriented, band and mix steering (grain runs with the sheets, the fine band stays free), save and load with the steering mode, the spectrum and grain terms, the straight-through edit and the score weight, fine-tuning from saved weights, line F1 tolerance and mask, refusal of non-finite maps, line keep on clean and noisy tiles (needs Synthetic-Slices), the R4 bounds inside the search space, the air filter, and the command line from `real` to `realize`. Not covered: a full GPU training and the Results numbers.

## History

- 2026-11-27: released in the Scrolls kit: the generator with spectrum, grain and high-band terms, residual steering, edit and score hooks, fine-tuning, a command line from reference slices to realized tiles, and a self-contained line keep. ([#401](https://github.com/ChaseHendrick/Scrolls/pull/401))

## Related

- [hardcases](hardcases.md): the physics tiles it repaints.
- [simscore](simscore.md) and [simcritic](simcritic.md): the judge to score realized tiles with.
- [simreal](simreal.md): gray-value statistics and the render bound search.
- [scrollsim2](scrollsim2.md): the full-scale rolled scroll.
- [Synthetic-Slices v0.2](https://github.com/vincentl065/Synthetic-Slices) (vincentl065, MIT): the line extraction `linekeep` uses.
