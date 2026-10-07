# Lane D: a fibre-orientation feature reader on CPU (2026-10-07)

Research notes. Labels per [`../NOVELTY.md`](../NOVELTY.md). Public labelled data only (PHerc0139 w045, PHerc0841 w00); no target scroll. All maps are Model output, not readings.

## What was built

`kit fibertensor` ([`kit/fibertensor.py`](../../kit/fibertensor.py), tests in [`tests/test_fibertensor.py`](../../tests/test_fibertensor.py)): a CPU ink reader with hand-made, label-free features and a tiny learned head.

- The 28 layers are averaged into 5 depth bands, each z-scored.
- Per band: brightness smoothed at 1 and 4 px; a 2D structure tensor (gradient sigma 1 px, integration 2, 4 and 8 px) giving log energy, coherence, and an "off-fibre" angle, the distance of the local orientation from the nearer of the two fibre axes, where the axis is measured per segment from the volume alone; band to band depth contrast. 59 features.
- Head: a 16-unit MLP in numpy (or logistic regression), full-batch Adam, balanced sample of 60,000 supervised pixels.
- Ablation baseline: the same head on the 10 brightness features only (`--kind raw`).
- `--reverse` reads the depth order backwards for the control map.

Idea under test (Untested idea before this run): ink laid across papyrus fibres breaks their two-axis texture, so coherence and off-fibre angle should separate ink where brightness does not (raw brightness: at most 0.58 AUC per layer, [overlap-and-baseline log](2026-10-07-overlap-and-baseline.md)). Prior art check: structure tensors are used in the pipeline for surface and fibre directions (organizers' [open problems](https://scrollprize.org/2026_open_problems), checked 2026-10-07), not found as an ink feature on PHerc0841. The unit test builds a phantom whose ink is texture only (same mean and spread as the fibres): the fibre features find it (AUC above 0.8 on a held-out phantom with rotated fibres) and brightness does not (within 0.1 of 0.5), so the tool can tell the two cases apart.

## Evaluation

Run on the user's Mac (CPU, about 8 s per pair) with [`scripts/experiments/2026-10-07-grok-laneD/run_mac.sh`](../../scripts/experiments/2026-10-07-grok-laneD/run_mac.sh); outputs (scores and model metadata, no maps) in [`results/`](../../scripts/experiments/2026-10-07-grok-laneD/results/). Commands:

```bash
cd ~/scrolls-work/laneD/Scrolls
PAIRS="w045:w00" bash scripts/experiments/2026-10-07-grok-laneD/run_mac.sh ~/scrolls-work/laneD/out
PAIRS="w00:w045" bash scripts/experiments/2026-10-07-grok-laneD/run_mac.sh ~/scrolls-work/laneD/out
PAIRS="w00train:w00" bash scripts/experiments/2026-10-07-grok-laneD/run_mac.sh ~/scrolls-work/laneD/out
```

Each scores with `python -m kit auc MAP --control MAP_reverse --labels ... --mask ... --crop ... --surface-shape ... --inner 64 --bootstrap 300 --compare OTHER --json`: the repo's 640 px crops, 64 px edge left out, 300 block-bootstrap draws over 1 mm blocks. `ink_9um` is seed 42 on the same crop (w00 0.8061, the bar in `tricks.md`). `w00train` is the densest-labelled 640 px window of w00 (rows 1792 to 2432, columns 2944 to 3584) at least 64 px from the test crop: a held-out area of the same segment.

| Train on, test on | fibertensor AUC (95 % CI) | reverse | brightness-only head | fibre minus brightness (95 % CI), share not ahead | `ink_9um` s42 | fibre minus `ink_9um` (95 % CI) |
| --- | --- | --- | --- | --- | --- | --- |
| w045 (PHerc0139), w00 (PHerc0841) | 0.4726 (0.405 to 0.555) | 0.4331 | 0.5663 (0.496 to 0.640) | -0.094 (-0.153 to -0.006), 0.98 | 0.8061 | -0.333 (-0.413 to -0.228) |
| w00, w045 | 0.4223 (0.333 to 0.537) | 0.5711 | 0.5096 (0.369 to 0.631) | -0.072 (-0.221 to +0.089), 0.82 | 0.9199 | -0.482 (-0.588 to -0.381) |
| w00 other window, w00 crop | 0.5018 (0.431 to 0.563) | 0.5356 | 0.4985 (0.405 to 0.575) | +0.003 (-0.042 to +0.050), 0.49 | 0.8061 | -0.304 (-0.399 to -0.206) |

Training loss (log loss, balanced sample): fibre head 0.33 to 0.36, brightness head 0.60 to 0.63.

## Result (Null)

This implementation did not improve on the brightness-only ablation on any of the three tested splits. Each fibre-head AUC interval includes chance, and the w045-to-w00 fibre-versus-brightness interval indicates a decrease. It is 0.30 to 0.48 AUC behind the reported `ink_9um` comparisons. Lower training loss alongside weak held-out performance is consistent with learning window-specific texture. **Interpretation.** These runs are a null for the tested 2D features, 16-unit learner, training windows, and settings; they do not establish that fibre texture contains no ink information or identify which features `ink_9um` uses. Larger training areas, stronger depth priors, and a 3D tensor were not tested and remain unresolved.

## Use

```bash
python -m kit fibertensor train VOLUME.zarr LABEL_DIR --crop Y0 Y1 X0 X1 --surface-shape H W [--kind fibre|raw] [--model mlp|logreg] -o model.npz
python -m kit fibertensor predict model.npz VOLUME.zarr --crop Y0 Y1 X0 X1 [--reverse] -o map.tif
```

Tests: `python -m unittest discover -s tests` (185 tests, all pass on the Mac venv).
