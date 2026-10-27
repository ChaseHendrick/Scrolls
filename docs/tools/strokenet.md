# strokenet: score how text-like an ink map's windows look, with rotation and IAAFT controls

`python -m kit strokenet` scores 6.1 mm windows of an organizers' ink map with StrokeNet, a small CNN trained on PHerc. Paris 4, with rotation and IAAFT controls, or with `--two-density` a two-number ink density score; `scripts/strokenet/` holds the training and tests.

| Field | Value |
| --- | --- |
| Id | `strokenet` |
| Status | Experimental |
| Kind | kit command, kit module, script folder, model, data |
| Area | Scoring and controls |
| Run | `python -m kit strokenet`, `python -m kit strokenet --two-density` (the two-density score, no network), `from kit import strokenet`, `python scripts/strokenet/data.py`, `python scripts/strokenet/train.py`, `python scripts/strokenet/pipeline.py`, `python scripts/strokenet/evaluate.py` |
| Code | `kit/strokenet.py`, `kit/data/strokenet-weights.json`, `scripts/strokenet/`, `kit/cli.py` (`cmd_strokenet`, `cmd_strokenet_two_density`) |
| Tests | `tests/test_strokenet.py`, `tests/test_strokenet_pipeline.py`, `tests/test_strokenet_stats.py`, `tests/test_gridpilot.py` |
| Needs | Scoring: Python 3.10 or newer and numpy; scipy is used when present and gives the same masks; tifffile for TIFF maps (with zarr installed a TIFF is read lazily), Pillow for PNG and other images and for `--png`. From a clone, `python -m pip install -e ".[all]"` brings all of them; a plain `pip install .` brings none, and the command then names the packages to install. The scripts also need torch (`train.py`, `nulls.py`, `pipeline.py`, the `randcnn` baseline), scipy (`data.py` labels), tifffile and zarr (`data.py` pooling). The preregistered run used torch 2.14.1+cu130 (`config.torch` in the evidence's `runs/*.history.json`) |
| Runs on | Scoring runs on any CPU. A synthetic 300 x 400 px map at 0.048 mm (43 windows) with a small random test network took 4.4 s (measured 2026-10-16, 4-core cloud container); the released network on a whole segment: Not measured. `--two-density` on a synthetic 700 x 760 px map at 0.009362 mm (208 labels) took 0.26 s (measured 2026-10-22, same kind of container). Training runs on a GPU: each run of the preregistered sweep, finals and controls took 666 to 2,356 s on CUDA, the released configuration 1,506 s (`train_wall_s` in [the evidence's run histories](../evidence/2026-10-14-strokenet/README.md)) |
| Network | `kit strokenet` with a weights file, or with `--two-density`: None. With a released model name not yet in the cache: one download of the weights from github.com (the `url` in `kit/data/strokenet-weights.json`). `data.py fetch`: data.aws.ash2txt.org, one TIFF of about 1.3 GB per segment, 27 segments. `gridpilot.py`: HTTP range reads of a surface volume's chunks at a base URL its caller gives (its cloud runner is not in this repository) |
| Writes | `kit strokenet`: nothing by default (prints only); `--out` writes the result JSON, `--grid` a `.npy` logit grid, `--png` a picture of the map with each window's score painted over it (with `--two-density`, `--out` and `--grid` write that score's JSON and label grid; `--png` is refused); the first use of a released name writes the weights to `~/.cache/scrolls-kit/strokenet/` (or `$KIT_STROKENET_WEIGHTS`) through a `.part` file. Scripts: `data.py` writes `WORK/raw/`, `WORK/pooled/`, `WORK/labels/`, `WORK/crops/`; `train.py` writes `RUN/config.json`, `checkpoint.pt`, `final.pt`, `strokenet.npz`, `history.json`; `pipeline.py` writes the run folder's monitor, baselines, evaluation sets, reads, `choice.json`, `calibration.json`, `gate.json` and `WORK/read_test.started.json`; `evaluate.py` writes `calibration.json` and its `--out` file |
| Go-ahead | Not needed to score a map. Needed before renting GPUs for `train.py` or `pipeline.py` (the go-ahead rule, hard rule 8, and the Modal rule, hard rule 11), and before uploading new weights or posting any score |
| Released | Public `main` since 2026-10-14 (`8d9ad54`); the weights `strokenet-paris4-v1` are a GitHub release of this repository from the same day; in the README's "Released tools" as `strokenet`, since 2026-10-20 a line of the Scrolls kit entry; `--two-density` added 2026-10-22 |
| Guide | [StrokeNet model card](../strokenet.md) (data, training, held-out results and limits; [the two-density score](../strokenet.md#the-two-density-score)) |
| License | Code: Apache 2.0 ([LICENSE](../../LICENSE)). Weights: CC BY-NC 4.0, the license of the organizers' scan data ([model card](../strokenet.md#license-and-release)) |
| Checked | 2026-10-22 against commit `3990326` (the two-density score, `--two-density`, `--mask` and `--label-stride`) |

## What it does

StrokeNet is a small convolutional network (CNN) that gives one number, a logit, for a 6.1 mm by 6.1 mm window of a 2D ink map (128 by 128 pixels at 0.048 mm): how much the window looks like lines of body text of PHerc. Paris 4 as the organizers' 2026 ink model draws them. It was trained against blank papyrus and against copies of text windows whose arrangement or orientation was destroyed. "StrokeNet" is a project name: nothing here tests whether it responds to strokes or letters as such.

`python -m kit strokenet` resamples a map to 0.048 mm, keeps only windows with at least 99 % core papyrus (usable papyrus more than 1.5 mm from any unusable pixel, the rule the training windows met), scores every kept window, and summarizes the scores. Every result carries two controls on a seeded random sample of the kept windows: each window against itself turned by 90 degrees, and against an IAAFT copy of itself (iterative amplitude-adjusted Fourier transform: the same pixel values and nearly the same power spectrum, arrangement scrambled). It also prints an orientation hint. It runs in numpy only; the weights are downloaded once and checked by SHA-256.

`scripts/strokenet/` holds the rest: the dataset builder (`data.py`), the null copies (`nulls.py`), training (`train.py`), the preregistered run (`pipeline.py`), the measures (`metrics.py`), eleven simple baseline scores (`baselines.py`), the evaluation and release (`evaluate.py`), the run's file hashes (`prov.py`) and the tile grid pilot (`gridpilot.py`).

`--two-density` (added 22 October 2026) runs a different score with no network and no weights: the two-density score. For each 48 px label window (about 2.2 mm) of a pooled map it adds to the window's own ink density, z-scored within the map, a quarter of the z-scored ink density of the 128 px window (about 6 mm) around it. It ranks windows within one map. On its preregistered test it came out ahead of ink density inside segments on PHerc0500P2 with ink_9um (Model output), with a reader that reads that scroll weakly; see "The two-density score" below and in the [model card](../strokenet.md#the-two-density-score).

Status is Experimental because the model **missed its own preregistered bar**. What the held-out test showed, on six PHerc. Paris 4 tracings it never saw ([model card](../strokenet.md#in-short), `strokenet_checks` in [`results.json`](../results.json)):

- **7 of 9 bar items passed, 2 missed**: T6, blank papyrus against its own 90 degree turn (0.639; the bar asks for within 0.10 of 0.5), and FPR_blank, blank windows above the threshold (0.021; bar 0.02).
- **Simple ink density matches it on text against blank** (T1: density 0.996, StrokeNet 0.990), and simple scores met all 9 counted bar items.
- **Where it adds value**: telling text from its own 90 degree turn (T4 0.994, +0.141 over the best simple score, `lines`, on 6 of 6 segments), which is what the orientation hint and the rotation control use. Window roughness tells text from dense ink better (T8).

Its limits, before any further test:

- **One reader's appearance.** It saw only the organizers' `new_canon_autoresearch_recipe` maps of one scroll (Sourced fact, the run's data manifest); maps from other ink models look different (stroke width, contrast, background, tile pattern) and are outside what it learned (Interpretation).
- **Paris 4's handwriting.** Its labels assumed a 4.5 to 9 mm line pitch with lines along the rows (Sourced fact, the label rule in `data.py`); smaller or larger writing, or a turned map, did not get text labels (Interpretation).
- **Input assumptions.** The organizers' 0 to 255 scale (a float map whose values all lie in 0 to 1, as many ink models write, or a 16-bit or float map in 0 to 65535, such as kit ensemble's 16-bit TIFF, is scaled to it first and `scaled_from` in the result says which), papyrus as values above 3, windows with at least 99 % core papyrus, a fixed 6.1 mm window and maps of at least 128 px at 0.048 mm per side (Sourced fact, `kit/strokenet.py`). Float or rescaled maps, other scrolls and other ink models are not tested in this page's published evidence (Interpretation: expect it to do worse there).

A rework (version 5) for maps from any ink reader and any scroll, judged on human ink labels with a preregistered leave-one-scroll-out test, is in progress in private work. Until it has a held-out result, this page's network and the command without `--two-density` describe version 1 only.

A score is model output, not a reading. A high score where no text is known is not evidence that text is there, and nothing StrokeNet prints may be described as letters found or read.

## When to use it

- Finding where text-like ink sits on a large ink map of the organizers' 0 to 255 scale, as a pointer for a person to look. Simple ink density did as well on its held-out test (T1 0.996 against 0.990), so rank by density too and compare.
- Telling text-like ink from ink that is merely dense, with the caveat that window roughness does this better on the test set (T8 in the model card).
- Checking whether a map is on its side: the orientation hint and the rotation control.
- Ranking small windows of one map by ink with the surroundings taken into account, with no weights to download: `--two-density`. Its one test was on PHerc0500P2 with ink_9um, so compare it with plain density on your own maps.
- Rebuilding or auditing the preregistered run from public data with the scripts.

Do not use it:

- To compare maps, segments or readers with `--two-density`: its score is z-scored within each map, so values from two maps are not on one scale. Use [`auc`](auc.md) against labels instead.
- To score a map against human labels: use [`auc`](auc.md) on a labeled segment, or [`hpscore`](hpscore.md) at letter scale.
- To read letters: use [`letterread`](letterread.md), and treat its output as model output too.
- On maps from other ink models, other scrolls, rescaled or float maps without checking first: they are outside the training data, and nothing here shows it works there.
- To claim text exists on an unread area from a high score alone; target-scroll scores stay private (the no-findings rule in [`AGENTS.md`](../../AGENTS.md)).

## Quick start

```bash
python -m kit strokenet MAP.tif --pixel-mm 0.0024 --out RESULT.json --png RESULT.png
```

- `MAP.tif`: one of the organizers' ink predictions (uint8, 0 to 255, ink bright), such as a PHerc. Paris 4 tracing from https://data.aws.ash2txt.org/samples/PHercParis4/segments/. `.npy`, `.npz` and `.png` work too.
- `0.0024`: the map's pixel size in mm (2.4 um). A uint8 map at a whole fraction of 0.048 mm is pooled exactly as the training windows were.
- `RESULT.json`: where to keep the full result; add `--json` to print it instead of the text summary.
- `RESULT.png`: the map at 0.048 mm with every scored window's score painted over its center, blue low and red high, uncolored where a window was skipped (at most 2,000 px a side). It shows where the score is high; it is model output, not a reading.
- The first run downloads `strokenet-paris4-v1` (589,393 weights) into `~/.cache/scrolls-kit/strokenet/`; pass `--weights FILE.npz` to use a file.

On a synthetic 300 x 400 px uint8 map at 0.048 mm (bands every 9 px, a blank strip on the left) with a small random-weights network made as `tests/test_strokenet.py` makes one (`--weights weights.npz --sample 8 --grid grid --out res.json`), it printed:

```
StrokeNet (weights.npz), 43 windows of 6.1 mm scored at stride 32 px (0.048 mm), 27 skipped (under 99 % core papyrus)
  windows above the blank-papyrus threshold: 0.000 as given, 0.000 turned 90 degrees
  mean logit -5.74 (turned -3.36), top tenth -5.21
  8 random windows above their copies turned 90 degrees: 0.00 (mean logit drop -2.35)
  8 random windows above their IAAFT copies (200 iterations): 0.88 (mean logit drop 0.77)
  the map scores higher turned by 90 degrees: its text lines may run vertically
Model output: a text-likeness score from a small CNN trained on one scroll's ink maps, not a reading. It never shows by itself that text is present.
```

The numbers mean nothing here (random weights); the run shows the shape of the output. It worked when the exit code is 0, `learned_n` (the first number) is above 0, and the two control lines are there. The released weights also add `; validation: blank ..., text ...` to each control line, the reference values to read them against.

## Checks and controls

- **Rotation control** (`controls.rot90`). On `--sample` kept windows drawn at random with `--seed`, the share scoring above their own 90 degree turn and the mean logit drop. On the validation split the released model put 0.979 of text windows and 0.665 of blank windows above their turn (`val_ref` in [`calibration.json`](../evidence/2026-10-14-strokenet/calibration.json)); a map whose windows score near the blank value, or below it, shows no text-like orientation. A share well under 0.5 means the turned windows score higher: the map is probably on its side (the orientation hint says so).
- **IAAFT control** (`controls.iaaft`, 200 iterations). IAAFT copies keep a small excess of high-frequency power, so a score can drop on them without using arrangement. Read the share against the validation values, not against 0.5: 1.0 for text and 0.913 for blank windows (`val_ref`). A share near the blank value says nothing about text.
- **Blank threshold** (`learned_frac_above_val_blank_q99`). The share of windows above the 99th percentile of validation blank-window logits (1.704 for the released model, `models.released.q99` in `calibration.json`). By construction about 1 % of blank windows pass it; on the test split 2.1 % did (FPR_blank 0.0213, `strokenet_checks` in [`results.json`](../results.json)).
- **The preregistered test.** The released model missed its bar on T6 (blank against turned blank, 0.639, bar within 0.10 of 0.5) and FPR_blank (0.021, bar 0.02); both seeds missed the same two. It passed T1 text against blank (0.990), T4 text against its turn (0.994), and the others, but simple scores met 9 of 9 counted bar items, and the artifact control (trained never to see text) reached 0.999 on T2, so T2, T3 and T7 show the organizers' tile grid, not text structure. Its one result beyond simple scores is T4, +0.141 over the `lines` score on 6 of 6 segments ([model card](../strokenet.md#results); `strokenet_checks` in `results.json`).
- **No probability.** The Platt parameters were fitted on a fixed evaluation mixture, so `calibrate()` is not P(text) on a real map and the command never reports it.

Claim label: Model output, for every score and control the command prints; Null, for the preregistered held-out test of 14 October 2026, which missed its bar.

## The two-density score (`--two-density`)

A score with no network, no weights and no download. For each 48 px label window of the pooled map, `d48` is its mean ink on 0 to 1 and `d128` the mean ink of the 128 px window centered on it; the score is

```text
s = z(logit d48) + 0.25 z(logit d128)
```

with z taken within the map over every scored label. The first term ranks labels exactly as plain ink density does; the second adds how much ink surrounds them. The weights (`TD_WEIGHTS` = (1.0, 0.25)) were fixed before its test on maps of other segments. The model card's [section](../strokenet.md#the-two-density-score) has the full method, the test and the limits.

```bash
python -m kit strokenet MAP.tif --pixel-mm 0.009362 --two-density --mask PAPYRUS.tif --grid GRID.npy --out RESULT.json
```

- `MAP.tif`: a 2D ink map of any scale (it is stretched from its lowest value to its 99.9th percentile), ink bright, such as an ink_9um map of a segment.
- `0.009362`: the map's pixel size in mm (9.362 um); the map is pooled by the whole number nearest 48 um per pixel, here 5.
- `PAPYRUS.tif`: optional, a mask of the same shape, nonzero on papyrus; labels under half papyrus are skipped. Without it every whole label is scored, and labels off the papyrus pull the z-scale.
- `GRID.npy`: optional, the score on the label lattice, NaN where a label was skipped. `RESULT.json`: optional, the full result with every label's position and score.

On a synthetic 700 x 760 px float map at 0.009362 mm (uniform noise with values under 0.3 set to 0 and the left 250 columns masked off, the map `test_matches_the_tested_run` builds) it printed:

```
StrokeNet two-density score: 208 label windows of 2.25 mm scored at a stride of 6 pooled px of 0.0468 mm, 80 skipped (under 50% papyrus)
  s at the 10th, 50th and 90th percentiles: -1.17, -0.08, 1.26 (z units within this map)
  s ranks windows within this map only; compare positions, not maps.
Model output: an ink density score for each label window of one map, ranked within that map. Not a reading; it never shows by itself that text is present.
```

It worked when the exit code is 0 and `labels_scored` is above 0. The values are z units: their mean over the scored labels is 0 by construction, so a high value means "more ink here and around here than elsewhere on this map", never "text".

**Its test** (22 October 2026, preregistered, Model output). On 11 public PHerc0500P2 segments with ink_9um seed 42 maps, against text and blank labels made by a rule from the team's finer-scan ink map (62,220 text and 6,468 blank label positions), the mean within-segment AUC of text against blank was 0.701 for s and 0.662 for plain density: mean difference 0.040 (95 % block-bootstrap interval 0.028 to 0.050), s ahead in 11 of 11 segments (gains +0.010 to +0.104, median +0.029). Both controls passed: s on the reverse-depth maps 0.574, s against labels shifted by at least 10 mm 0.507 (each had to be at least 0.10 below 0.701). Seed 43, descriptive only, also had s ahead in 11 of 11 (mean difference 0.048), but its reverse-depth control failed. The preregistered claim, the only wording to quote: "ahead of ink density inside segments on PHerc0500P2 with ink_9um".

**Its limits.** ink_9um reads this scroll weakly (plain density's mean within-segment AUC 0.66, below 0.5 on one segment), so a gain over a weak baseline says nothing about strong readers. One scroll and one reader for the verdict, from a single read. Three pairs of test segments share papyrus, so the interval is likely too narrow. The 128 px window also reads the map's footprint (off-papyrus pixels and padding count as empty), which may explain part of the gain; untested. The weights were set on maps of other segments.

Claim label: Model output, for every score `--two-density` prints and for its one test, which covers PHerc0500P2 with ink_9um only.

## Commands and options

### `python -m kit strokenet`

```
usage: python -m kit strokenet [-h] --pixel-mm PIXEL_MM [--weights WEIGHTS]
                               [--key KEY] [--crop Y0 Y1 X0 X1]
                               [--stride STRIDE] [--sample SAMPLE]
                               [--seed SEED] [--grid GRID] [--out OUT]
                               [--png PNG] [--two-density] [--mask MASK]
                               [--label-stride LABEL_STRIDE] [--json]
                               map
```

| Option | Default | Meaning |
| --- | --- | --- |
| `map` | required | The ink map: `.npy` (memory-mapped), `.npz` (the `--key` array or the first), `.tif` or `.tiff` (read lazily through zarr when installed), or an image Pillow reads such as `.png`. On the organizers' 0 to 255 scale, ink bright; a float map whose values all lie in 0 to 1, or a 16-bit or float map in 0 to 65535, is scaled to it (the result's `scaled_from` names the range). Its dtype is kept |
| `--pixel-mm PIXEL_MM` | required | Map pixel size in mm, such as 0.0024 for a 2.4 um map or 0.048 for a map already at the working size. Must be finite and from 0.0001 to 1 (`MIN_PIXEL_MM`, `MAX_PIXEL_MM`) |
| `--weights WEIGHTS` | none (the released `strokenet-paris4-v1`, or `$KIT_STROKENET_DEFAULT`) | A StrokeNet `.npz` file, or the name of a released model in `kit/data/strokenet-weights.json`, downloaded once and checked by SHA-256 |
| `--key KEY` | none (the first array) | For an `.npz` map: the array's name |
| `--crop Y0 Y1 X0 X1` | none | Map pixels to keep: rows Y0 to Y1 and columns X0 to X1, ends excluded. For an exact-pooling map the origin moves down to the 32 px training lattice (`32 x k` source pixels) and the end is clipped to the map; the result's `crop` records both boxes. The window rule then sees the crop alone |
| `--stride STRIDE` | `32` | Window step in 0.048 mm pixels (1.5 mm, the training lattice). The last window on each axis ends at the map's edge |
| `--sample SAMPLE` | `64` | Kept windows drawn at random for the rotation and IAAFT controls (`SAMPLE`); 0 skips the controls. The hidden old name `--top` still works |
| `--seed SEED` | `0` | Seed of the control sample and of the IAAFT copies; the same seed gives the same controls |
| `--grid GRID` | none | Also save the window logit grid as `.npy` (`.npy` is added when missing), NaN where a window was skipped. Its rows and columns start at `window_y_px` and `window_x_px` of the result |
| `--out OUT` | none | Also write the result as JSON (indented) to this file |
| `--png PNG` | none | Also write a picture: the map at 0.048 mm with each scored window's score painted over its center, blue low and red high, uncolored where a window was skipped, at most 2,000 px a side (needs Pillow). The result's `png_file` names it |
| `--two-density` | off | Score 48 px label windows with the two-density score instead of the network: no weights, numpy only. `--weights`, `--crop` and `--png` are refused with it; `--stride`, `--sample` and `--seed` are ignored; `map`, `--pixel-mm`, `--key`, `--grid`, `--out` and `--json` work as usual |
| `--mask MASK` | none | With `--two-density`: a papyrus mask of the map's shape, nonzero on papyrus, read like `map`; labels under half papyrus (`TD_PAPYRUS_MIN` = 0.5) are skipped. Without it every whole label is scored. Ignored without `--two-density` |
| `--label-stride LABEL_STRIDE` | `6` | With `--two-density`: label step in pooled pixels (`TD_STRIDE`, the tested stride). Ignored without `--two-density` |
| `--json` | off | Print the result as JSON instead of the text summary |

### `python scripts/strokenet/data.py`

Builds the dataset from the organizers' public PHerc. Paris 4 ink predictions; every step is deterministic, so two machines get the same windows byte for byte.

```
usage: data.py [-h] [--work WORK] [--segments SEGMENTS] [--jobs JOBS]
               [--keep-tif] [--force] [--out OUT]
               {fetch,pool,label,crops,all,manifest,splits}
```

| Option | Default | Meaning |
| --- | --- | --- |
| `step` | required | `fetch` (download one 2.4 um TIFF per segment, resumable, with its size and SHA-256), `pool` (20 x 20 mean to 0.048 mm, rounded half to even, uint8), `label` (text, blank, dense and unusable areas by rule), `crops` (128 x 128 windows of each class), `all` (the four in order), `manifest` (the SHA-256 of every file), `splits` (print the fixed split) |
| `--work WORK` | `work/strokenet` | Work folder for `raw/`, `pooled/`, `labels/` and `crops/` |
| `--segments SEGMENTS` | none (all 27) | Comma-separated short names such as `w028-037` |
| `--jobs JOBS` | `1` | Segments processed in parallel |
| `--keep-tif` | off | Keep the 1.3 GB source TIFFs after pooling; `fetch` alone always keeps them |
| `--force` | off | Redo steps whose outputs exist |
| `--out OUT` | none (stdout) | `manifest`: write the manifest to this file |

### `python scripts/strokenet/train.py`

Trains one StrokeNet with PyTorch and exports it for numpy inference. The test segments are never read here.

```
usage: train.py [-h] --work WORK --out OUT [--width WIDTH] [--depth DEPTH]
                [--steps STEPS] [--batch BATCH] [--lr LR] [--wd WD]
                [--seed SEED] [--neg-mix NEG_MIX] [--blank-rot BLANK_ROT]
                [--jitter JITTER] [--positives {text,blank}] [--no-flip]
                [--permute-labels] [--eval-every EVAL_EVERY]
                [--max-minutes MAX_MINUTES] [--monitor MONITOR]
                [--train-segments TRAIN_SEGMENTS]
                [--val-segments VAL_SEGMENTS] [--val-limit VAL_LIMIT]
                [--resume] [--device DEVICE]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--work WORK` | required | The `data.py` work folder (`crops/`, `pooled/`) |
| `--out OUT` | required | Run folder for the checkpoint, the exported weights and the history |
| `--width WIDTH` | `16` | Channels of the first convolution pair; each later pair doubles it, up to 8 times |
| `--depth DEPTH` | `4` | Convolution pairs, each followed by 2 x 2 max pooling (the released model used 5) |
| `--steps STEPS` | `6000` | Training steps |
| `--batch BATCH` | `128` | Windows per step, half positives and half negatives |
| `--lr LR` | `2e-3` | Peak learning rate of AdamW, with a 200-step warm-up and a cosine decay to zero |
| `--wd WD` | `1e-4` | AdamW weight decay |
| `--seed SEED` | `0` | Seed of every random draw |
| `--neg-mix NEG_MIX` | `blank=0.4,iaaft=0.2,shuffle=0.2,rot90=0.2` | Shares of the negative kinds: `blank`, `iaaft` (20 iterations), `shuffle`, `rot90`, `strip` (`DEFAULT_MIX`) |
| `--blank-rot BLANK_ROT` | `0.5` | Share of blank negatives turned by 90 degrees, so fiber direction alone cannot look like text |
| `--jitter JITTER` | `0.25,0.25` | Shares of tile- and strip-jittered (seam-matched) positives and blank negatives (`DEFAULT_JITTER`) |
| `--positives {text,blank}` | `text` | `blank` is the artifact control: blank windows are the positives and nulls of blank the negatives, so it never sees text |
| `--no-flip` | off | Turn off the random horizontal and vertical flips |
| `--permute-labels` | off | Control: labels permuted at random within every batch (should learn nothing) |
| `--eval-every EVAL_EVERY` | `500` | Steps between scores of the fixed validation monitor windows, each followed by a checkpoint |
| `--max-minutes MAX_MINUTES` | `0` | Stop and export after this wall time; 0 means no cap |
| `--monitor MONITOR` | none (built here) | `.npz` of the monitor windows from `pipeline.py prep` |
| `--train-segments TRAIN_SEGMENTS` | none (the fixed training split) | Comma-separated override, for smoke tests only |
| `--val-segments VAL_SEGMENTS` | none (the fixed validation split) | Comma-separated override, for smoke tests only |
| `--val-limit VAL_LIMIT` | `0` | Use only the first N monitor windows of each kind, for smoke tests only |
| `--resume` | off | Continue from `OUT/checkpoint.pt` when it exists |
| `--device DEVICE` | none (cuda, else mps, else cpu) | Torch device |

### `python scripts/strokenet/pipeline.py`

The preregistered run, stage by stage ([prereg](../prereg/2026-10-14-strokenet.md)).

```
usage: pipeline.py [-h] --work WORK --runs RUNS [--device DEVICE]
                   {all,prep,sweep,finals,validate,test,smoke}
```

| Option | Default | Meaning |
| --- | --- | --- |
| `stage` | required | `prep` (monitor windows, fitted baselines, validation windows), `sweep` (six configurations at seed 0 and the choice), `finals` (seeds 1 and 2, ablations, controls), `validate` (random-feature baseline, validation read, calibration, gate), `test` (the single test read, only after a passed gate), `all` (every stage in order), `smoke` (a tiny run on a validation segment standing in for the test split; no test window is read) |
| `--work WORK` | required | The `data.py` work folder |
| `--runs RUNS` | required | The run folder; created when missing |
| `--device DEVICE` | none (as `train.py`) | Torch device passed to training and the reads |

### `python scripts/strokenet/evaluate.py`

Turns the reads into the preregistered results and exports the released weights.

```
usage: evaluate.py [-h] --runs RUNS [--out OUT] [--manifest MANIFEST]
                   [--test-split TEST_SPLIT]
                   {calibrate,results,release}
```

| Option | Default | Meaning |
| --- | --- | --- |
| `action` | required | `calibrate` (from the validation read only: Platt scaling, blank thresholds, baseline directions, validity checks and the gate, written once to `calibration.json`), `results` (every measure on the test split, the bar, comparisons, ablations and the verdict line), `release` (the released model's `.npz` with its Platt parameters, blank threshold and validation reference values in its metadata) |
| `--runs RUNS` | required | The run folder |
| `--out OUT` | none | Output file; required by `results` (JSON) and `release` (`.npz`), which stop with a usage error without it |
| `--manifest MANIFEST` | none | `results`: the committed data manifest to compare with the run's own rebuild |
| `--test-split TEST_SPLIT` | `test` | Split to evaluate; `smoke_test` for smoke runs only |

### Library files

`nulls.py` (the null copies: `iaaft`, `iaaft20`, `phase`, `shuffle`, `rot90`, `strip`, and the seam-matched `tilejit` and `stripjit` windows), `metrics.py` (AUC with ties as one half, average precision, Platt fitting, ECE and Brier, block bootstrap, exact sign-flip test, t interval), `baselines.py` (seven single numbers with no fitting: `density`, `skew`, `lines`, `roughness`, `seam8`, `seam32`, `grid`; four fitted by logistic regression: `spectrum`, `texture`, `nullspec`, and the random-feature CNN `randcnn`), `prov.py` (the run's files and their SHA-256 at a commit) and `gridpilot.py` (the tile grid pilot's region choice, range reads, render and readout) have no command line; `pipeline.py` and `evaluate.py` import them.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_STROKENET_DEFAULT` | `strokenet-paris4-v1` | The weights `kit strokenet` and `load()` use when none are named (`DEFAULT`, read at import) |
| `KIT_STROKENET_WEIGHTS` | `~/.cache/scrolls-kit/strokenet` | Folder that released weights are downloaded to and looked up in (`weights_cache()`) |
| `CUBLAS_WORKSPACE_CONFIG` | `:4096:8`, set by `train.py` when unset | Lets cuBLAS run deterministically; set before CUDA starts |

## Python API

```python
from kit import strokenet
net = strokenet.load()                                   # or strokenet.load("weights.npz")
with strokenet.open_map("MAP.tif") as ink:
    res = strokenet.analyze(ink, 0.0024, net)
print(strokenet.text_summary(res))

with strokenet.open_map("MAP.tif") as ink:             # the two-density score: no weights
    res, grid = strokenet.two_density_analyze(ink, 0.009362, with_grid=True)
print(strokenet.two_density_summary(res))
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `weights_cache()` | `Path` of the download folder | Nothing | `$KIT_STROKENET_WEIGHTS`, else `~/.cache/scrolls-kit/strokenet` |
| `released_weights(registry=None)` | `{name: entry}` with `file`, `sha256`, `url`, `licence`, `params`, `pixel_mm`, `window_px`, `input`, `card` | `OSError`, `ValueError` or `KeyError` for a missing or broken registry | Reads `kit/data/strokenet-weights.json` by default |
| `resolve_weights(spec=None, cache=None, registry=None, download=True)` | `Path` of a weights file | `ValueError` for an unknown name, a file missing with `download=False`, an entry with no URL, or a SHA-256 mismatch; `OSError` (such as `URLError`) when the download fails | A path that exists is returned as it is, unchecked. A released name is downloaded once to a `.part` file, checked, then renamed |
| `open_map(path, key=None)` | Context manager yielding a 2D array or a lazy 2D array-like | `ValueError` for a map that is not 2D; `ImportError` without tifffile or Pillow; `OSError` for an unreadable file; `KeyError` for a missing `.npz` key | Keeps the dtype. An RGB image whose channels are equal keeps its values; a real color image is averaged |
| `to_working(ink, pixel_mm, strip=None)` | float32 array at 0.048 mm | `ValueError` for `pixel_mm` not positive or a map that is not 2D | Exact block pooling (rounded half to even for integer maps) at a whole fraction of 0.048 mm, exact area averaging otherwise; NaN and infinite values read as 0; reads `strip` rows at a time |
| `usable_mask(a, use_scipy=None)` | bool array | `ImportError` only when `use_scipy=True` and scipy is missing | Value above 3, opened three times with a 3 x 3 cross, holes filled; the numpy fallback gives the same result |
| `core_mask(a, use_scipy=None)` | bool array | As `usable_mask` | Usable pixels more than 1.5 mm from any unusable pixel; a map with no unusable pixel is all core |
| `snap_crop(crop, pixel_mm, shape=None)` | `([y0, y1, x0, x1], moved)` | `ValueError` for an empty or negative crop | Moves the origin down to the 32 px lattice for exact-pooling maps; clips the end to `shape` |
| `window_starts(n, stride_px)` | list of int | `ValueError` for `n` under 128 or a stride under 1 | Every `stride_px`, plus one window ending at the edge |
| `layout(a, stride_px=32)` | `(ys, xs, keep)`; `keep` is a bool grid | As `window_starts` | `keep` is True where a window has at least 99 % core pixels |
| `normalise(windows)` | float32 array of the same shape | Nothing | Per window (x minus median) / (1.4826 MAD), clipped to -3..20, divided by 5; lower median and unbiased SD as in torch |
| `iaaft(windows, rng, iters=IAAFT_ITERS)` | float64 copies, same shape | Nothing of its own | Schreiber and Schmitz 1996; `rng` is a numpy `Generator` |
| `StrokeNet(path)` | Network with `path`, `meta`, `platt`, `null_q99`, `val_ref` and the methods `logits(windows, batch=16)` ((N,) float32), `score_map(ink, pixel_mm, stride_px=32)` (logit grid, NaN where skipped), `summarise(v, n_skipped=None)` and `region_score(ink, pixel_mm, stride_px=32)` (the `map` dict under Outputs), `calibrate(logit)` (Platt-scaled values) | `OSError`, `KeyError` or `ValueError` for a file that is not a StrokeNet `.npz`; `calibrate` raises `ValueError` without Platt parameters | `calibrate` is a probability only under the evaluation mixture, never P(text) on a map |
| `load(spec=None)` | `StrokeNet`, cached per path | As `resolve_weights` | Default `DEFAULT` |
| `analyze(ink, pixel_mm, net, stride_px=32, sample=SAMPLE, seed=0, iaaft_iters=IAAFT_ITERS, with_grid=False)` | The result dict under Outputs, or `(dict, grid)` with `with_grid=True` | `ValueError` from `to_working` and `layout` | What the command runs |
| `text_summary(res)` | str | Nothing | The text the command prints |
| `check_pixel_mm(pixel_mm)` | None | `ValueError` when `pixel_mm` is not finite or outside `MIN_PIXEL_MM` to `MAX_PIXEL_MM` (0.0001 to 1) | Called by the command before anything is loaded |
| `two_density_analyze(ink, pixel_mm, stride=TD_STRIDE, mask=None, with_grid=False)` | `(result dict, grid or None)`; the dict is the two-density result under Outputs, the grid float32 on the label lattice, NaN where a label was skipped | `ValueError` for a bad `pixel_mm`, a map that is not 2D, a mask of another shape or a stride under 1 | What `--two-density` runs |
| `two_density_summary(res)` | str | Nothing | The text `--two-density` prints |
| `density_stretch(ink)` | `(uint8 map, {"floor", "top"})` | `ValueError` for a map that is not 2D | Linear from the lowest finite value to the 99.9th percentile onto 0 to 255, clipped; NaN reads as 0; then times 251/255, rounded, plus 4, so the emptiest pixel is 4 (`TD_PAD_VALUE`). `floor` and `top` are None when no value is finite |
| `density_pool_k(pixel_mm)` | int | As `check_pixel_mm` | The whole number nearest 48 um (`TD_POOL_UM`) over the pixel size, at least 1 |
| `density_working(ink, pixel_mm)` | `(pooled uint8 map, info)` | As `density_stretch` and `density_pool_k` | `density_stretch`, then k x k block means rounded half to even; `info` adds `k` and the pooled `pixel_mm` |
| `density_papyrus(mask, pixel_mm)` | float32 array | As `density_pool_k` | The papyrus share of each pooled pixel; nonzero mask values are papyrus |
| `label_positions(shape, stride=TD_STRIDE, papyrus=None, min_share=TD_PAPYRUS_MIN)` | (N, 2) int64 array of top-left corners on the pooled grid | `ValueError` for a stride under 1 or papyrus shares of another shape | Every `stride` pixels from the origin, none past the last whole 48 px label; an empty array when the map is under 48 px |
| `window_densities(pooled, pos)` | `(d48, d128)` float64 arrays on 0 to 1 | Nothing of its own | `d128` reads the map padded by `TD_PAD` = 40 pixels of `TD_PAD_VALUE` |
| `logit01(d)` | float64 array | Nothing | logit after clipping to `DENSITY_CLIP` = (0.001, 0.999) |
| `zscore(v)` | float64 array | Nothing | (v minus mean) over the population SD; all zeros when the values do not vary |
| `two_density(d48, d128, weights=TD_WEIGHTS)` | float64 array, s per label | Nothing | z over all the labels given: pass one map's or segment's labels, never labeled windows only or several maps together |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Ink map | 2D `.npy`, `.npz`, `.tif`/`.tiff`, or an image Pillow reads | The organizers' ink predictions on their 0 to 255 scale, ink bright, with text lines running along the rows as in their PHerc. Paris 4 maps (turned maps trip the orientation hint). Float or rescaled maps are outside the training distribution. Values of 3 or less, NaN and infinite values count as unusable |
| Pixel size | `--pixel-mm`, mm per pixel | 0.0024 for the organizers' 2.4 um maps. An integer map whose pixel size is 0.048 mm divided by a whole number is pooled exactly as in training; any other size is area-averaged and is not exact |
| Size | At least 128 px at 0.048 mm on each side (6.1 mm) | Smaller maps, or crops, are refused. A large TIFF is read in strips of about 4 million source pixels (`STRIP_PX`) |
| Weights | `.npz` with `n_conv`, `conv{i}_w`, `conv{i}_b`, `pool_after_{i}`, `head_w`, `head_b` and `meta` (JSON: `platt`, `val_blank_logit_q99`, `val_ref` and the run's settings) | Exported by `train.py` (batch norm folded into the convolutions) and completed by `evaluate.py release`. Weights are not in git |
| Weights registry | `kit/data/strokenet-weights.json`, `{"about": ..., "models": {name: entry}}` | One entry, `strokenet-paris4-v1`: SHA-256 `e9c486be...`, 589,393 parameters, CC BY-NC 4.0 |
| Training data (scripts) | The organizers' 2.4 um ink predictions of PHerc. Paris 4's 28 tracings of 1 July 2026 | Model `new_canon_autoresearch_recipe`, tile 256, stride 128. The innermost tracing, `w010-027`, is never used; the split is fixed by position in `data.py` `ORDER` |

## Outputs

The text summary is shown under Quick start. With `--json` or `--out`, one object:

| Field | Type | Meaning |
| --- | --- | --- |
| `note` | str | The model output notice (`NOTE`) |
| `weights` | str | File name of the weights used |
| `pixel_mm`, `stride_px` | float, int | As given |
| `working_shape` | [int, int] | The map's shape at 0.048 mm |
| `grid_shape` | [int, int] | Window grid rows and columns |
| `map.learned_mean`, `map.learned_max`, `map.learned_top10` | float or null | Mean, maximum and mean of the top tenth of the kept windows' logits; null when no window was kept |
| `map.learned_n`, `map.learned_n_skipped` | int | Windows scored and windows skipped (under 99 % core papyrus) |
| `map.learned_frac_above_val_blank_q99` | float or null | Share of kept windows above the weights' validation blank threshold; null without one |
| `rotated_90` | object, the same fields | The same windows, each turned by 90 degrees |
| `controls.windows`, `controls.seed` | int | Windows in the control sample, and its seed |
| `controls.rot90.frac_above_copy`, `controls.rot90.mean_logit_drop` | float or null | Share of sampled windows above their 90 degree turn, and the mean logit minus the turned logit |
| `controls.iaaft.iterations` | int | IAAFT iterations (200) |
| `controls.iaaft.frac_above_copy`, `controls.iaaft.mean_logit_drop` | float or null | The same against IAAFT copies |
| `controls.rot90.val_ref`, `controls.iaaft.val_ref` | object | Only when the weights carry them: `text` and `blank`, each with `frac_above_copy` and `mean_logit_drop` on the validation split |
| `orientation_hint` | str | One of: `the map scores higher as given`, `the map scores higher turned by 90 degrees: its text lines may run vertically`, `no difference between the map as given and turned by 90 degrees`, `no window was scored` |
| `orientation_hint_from` | str or null | `learned_frac_above_val_blank_q99`, or `learned_mean` when the shares are equal or missing |
| `window_y_px`, `window_x_px` | list of int | Start of each grid row and column in 0.048 mm pixels |
| `top_windows` | list of `{y_px, x_px, logit}` | The ten highest kept windows, positions in 0.048 mm pixels of the (cropped) map |
| `crop` | object | Only with `--crop`: `requested`, `used` (source pixels) and `origin_moved_to_lattice` |
| `grid_file` | str | Only with `--grid`: the `.npy` path written |

The grid file is a float32 array of `grid_shape`, NaN where a window was skipped.

With `--two-density` the result is a different object:

| Field | Type | Meaning |
| --- | --- | --- |
| `score` | str | `two-density` |
| `weights` | [float, float] | `[1.0, 0.25]`, the weights of z(logit d48) and z(logit d128) |
| `pixel_mm`, `pooled_k`, `pooled_pixel_mm` | float, int, float | As given; the pooling block side; the pooled pixel size in mm (`pixel_mm` times `pooled_k`) |
| `label_px`, `window_px`, `stride_px` | int | 48, 128 and the label stride, in pooled pixels |
| `label_mm` | float | The label window's side in mm |
| `stretch.floor`, `stretch.top` | float or null | The map values mapped to 0 and 255; null when no value is finite |
| `mask` | bool | Whether `--mask` was given |
| `labels_scored`, `labels_skipped` | int | Labels scored, and labels skipped for papyrus under half |
| `density_q10_q50_q90`, `s_q10_q50_q90` | [float, float, float] or null | The 10th, 50th and 90th percentiles of `d48` and of `s`; null when no label was scored |
| `label_y_px`, `label_x_px` | list of int | Each scored label's top-left corner in source map pixels |
| `s`, `d48`, `d128` | list of float | Each scored label's score (z units within this map) and its two densities on 0 to 1, in the order of `label_y_px` |
| `note` | str | The model output notice (`NOTE_TD`) |
| `grid_file` | str | Only with `--grid`: the `.npy` path written |

Its grid file is a float32 array with one row per label row and one column per label column of the pooled map (cell (i, j) is the label at pooled pixel (i x stride, j x stride), source pixel (i x stride x `pooled_k`, j x stride x `pooled_k`)), NaN where a label was skipped. The exit codes are the same; with `--two-density` an error is exit code 2 with the message on stderr.

| Exit code | Meaning |
| --- | --- |
| `0` | Scored. `map.learned_n` can still be 0 when no window met the papyrus rule |
| `1` | An error the command does not catch, with a Python traceback. The scripts also exit 1 on their own refusals (a `SystemExit` message, see Failure modes) |
| `2` | Bad input, with the message on stderr (an `ImportError`, `OSError`, `KeyError` or `ValueError`), including an `--out` or `--grid` file that cannot be written, or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `[Errno 2] No such file or directory: 'OUT'` on stderr, exit code 2, after the map was scored | `kit strokenet --out` names a file in a folder that does not exist, or one it cannot write | Create the folder or fix the path, and rerun |
| `evaluate.py: error: results writes a file: give its path with --out.` (or `release writes a file`), exit code 2 | `evaluate.py results` or `release` without `--out` | Add `--out FILE`: JSON for `results`, `.npz` for `release`. Nothing ran |
| `SPEC: no such file, and not a released model (strokenet-paris4-v1)` | `--weights` names neither a file nor a released model | Fix the path, or use the released name |
| `SPEC: not in FOLDER` | `resolve_weights(download=False)` and the released file is not cached | Download it, or call with `download=True` |
| `SPEC: no download address yet; see docs/strokenet.md` | A registry entry with no `url` | Pass a weights file with `--weights` |
| `SPEC: download from URL does not match its SHA-256; nothing kept` | The downloaded file differs from the registry's SHA-256 | Retry; if it persists, the release or the registry changed: report it |
| `SPEC: PATH does not match its SHA-256 HASH; delete it and retry` | The cached weights file is damaged or swapped | Delete the file and rerun |
| `No module named 'tifffile'` or another import error, exit code 2 | numpy, tifffile or Pillow is missing for this input | `python -m pip install numpy tifffile` (Pillow for images) |
| `expected a 2D map, got shape (...)` | A layer stack or an image that does not squeeze to 2D | Pass one 2D map |
| `pixel_mm VALUE: give the map's pixel size in mm, from 0.0001 to 1 (0.0024 for a 2.4 um map; StrokeNet works at 0.048 mm)` | `--pixel-mm` is not a finite number from 0.0001 to 1 | Give the map's pixel size in mm |
| `--weights does not apply to --two-density` (or `--crop`, `--png`), exit code 2 | An option of the network given with `--two-density` | Drop it; the two-density score uses no weights, scores the whole map and draws no picture |
| `the mask (H, W) and the map (H, W) differ in shape` | `--mask` is not at the map's resolution | Pass a mask of the map's exact shape |
| `the label stride must be at least 1` | `--label-stride` 0 or negative | Use the default 6 |
| `papyrus shares (H, W) and the pooled map (H, W) differ` | `label_positions` called with papyrus shares of another shape | Make the shares with `density_papyrus` from a mask of the map's shape |
| A summary with `0 label windows`, exit code 0 | With `--two-density`: the pooled map is under 48 px on a side, or no label has half papyrus under `--mask` | Check `--pixel-mm` and the mask |
| `--crop needs 0 <= Y0 < Y1 and 0 <= X0 < X1 inside the map, got [...]` | An empty, negative or reversed crop | Fix the crop |
| `the map is N px at 0.048 mm along one side; StrokeNet needs at least 128 (6.1 mm)` | The map or crop is under 6.1 mm on a side | Score a larger area |
| `stride_px must be at least 1` | `--stride` 0 or negative | Use the default 32 |
| `no Platt parameters in this weights file` | `calibrate()` on weights without `platt` in their metadata | Use released weights; the command never calls it |
| A summary line `no window has 99 % of its pixels above 3 and 1.5 mm inside the papyrus`, exit code 0 | No window met the papyrus rule: a map on another scale (float 0 to 1), mostly blank, or a crop at the papyrus edge | Check the map is on the 0 to 255 scale; score the whole map |
| `is not in any split` (`SEG is not in any split`) | `data.segment_split` on a segment outside the 27 used | Use a name from `data.py splits` |
| `unknown or excluded segments: [...]` | `--segments` names a segment that is not in `ORDER` or is `w010-027` | Use names from `data.py splits` |
| `failed: SEG, ...` | A step raised for these segments; each segment's JSON line holds its `error` | Read the error, fix it, rerun the step for those segments |
| `SEG: download incomplete (HAVE of TOTAL bytes)` | The download stopped short after 6 retries | Rerun `fetch`; it resumes from the `.part` file |
| `FILE: run data.py crops first` | A split's crops file is missing | Run `data.py crops` (or `all`) for those segments |
| `unknown negative kind KIND` | `--neg-mix` names a kind outside `blank`, `iaaft`, `shuffle`, `rot90`, `strip` | Fix the kind |
| `negative mix sums to zero` | Every `--neg-mix` share is 0 | Give at least one positive share |
| `jitter shares must be non-negative and sum to at most 1` | A bad `--jitter` pair | Use two shares that sum to 1 or less |
| `a test segment was named for training or validation` | `--train-segments` or `--val-segments` names a test segment | Never train or monitor on a test segment |
| `the artifact control has no blank negatives (its positives are blank)` | `--positives blank` with a `blank` share in `--neg-mix` | Use, for example, `--neg-mix iaaft=1,shuffle=1,strip=1` |
| `finals need the chosen configuration` | `run_args` for a finals run before `choice.json` exists | Run the `sweep` stage first |
| `a test segment was named for a split that is not the test split` | Evaluation windows of another split include a test segment | Fix the segment list |
| `read_test.npz exists: the test split is read once` | The test split was already read in this run folder | Use the existing read; it is never redone |
| `MARKER exists: the test split was already read under RUNS` | A test read started under another run folder | Do not read the test split again |
| `the test read needs committed code (provenance dirty or unknown)` | The run's code files differ from the commit, or git is unavailable | Commit, or run from a clean checkout |
| `the models differ from the ones the validation read scored and calibrated` | Weights changed after the validation read | Read the test split only with the validated models |
| `MARKER exists for other models or other test windows: the test split is read once` | An interrupted test read with other models or windows | Do not redo the read under new conditions |
| `calibration.json was made from a different validation read` | The validation read changed after calibration | Never refit; start a new run folder |
| `calibration.json exists: it is written once` | `evaluate.py calibrate` run again | Use the existing file |
| `calibration.json differs from the one the gate recorded` | `calibration.json` was edited after the gate | Restore it; results never use a changed calibration |
| `validation gate failed: the test split stays unread` | The gate's checks failed (`gate.json`) | Read the checks; the test split stays closed |
| `unknown baseline models: [...]` | `baselines.py` asked for a name it does not have | Use the names in `baselines.py` |
| `X and y must be non-empty with one label per row` | Empty or mismatched inputs to the baseline logistic fit | Check the training windows |
| `sample weights must be finite, non-negative and not all zero` | Bad weights for the baseline logistic fit | Check the weights |
| `fit_logistic did not converge in N steps (gradient G)` | The baseline fit did not converge | Check for separable or constant features |
| `fit_logistic: line search failed (gradient G)` | The baseline fit's line search failed | As above |
| `key 'K' holds '/'` | A baseline model key with a slash, which `.npz` cannot store | Rename the key |
| `KEY: cannot store TYPE without pickle` | A baseline model value that is not an array, number or string | Store arrays only |
| `N weights for M samples` | `metrics` got a weight per sample count that differs | Pass one weight per sample |
| `weights must be finite, non-negative and not all zero` | Bad weights for a metric | Check the weights |
| `z and y must be non-empty and of equal length` | Empty or mismatched inputs to `platt_fit` | Check the scores and labels |
| `scores must be finite` | NaN or infinite scores to `platt_fit` | Remove them |
| `labels must be 0 or 1` | Labels outside 0 and 1 | Fix the labels |
| `platt_fit did not converge in N steps (gradient G)` | Platt scaling did not converge | Check the scores |
| `platt_fit: line search failed (gradient G)` | Platt scaling's line search failed | As above |
| `shares must be non-negative and not all zero` | A bad calibration mixture | Fix the mixture |
| `component K has share S but no samples` | A mixture component with no windows | Check the evaluation sets |
| `one segment id and one position per window` | Cluster ids and positions of different lengths | Pass one of each per window |
| `segment ids and x positions must be non-negative and bands below 100000` | Out-of-range cluster ids | Check the ids |
| `sign_flip takes at most 12 finite differences` | More than 12 per-segment differences for the exact test | Pass at most 12 |
| `df must be at least 1` | A t interval with too few values | Pass at least two values |
| `no t table for level L without scipy` | A t quantile at a level the built-in table lacks | Install scipy |
| `the map is smaller than the region` | `gridpilot.choose_region` on a label map smaller than the 192 px region and its margins | Use a larger segment |
| `the crop must lie on the 128 px chunk grid` | `gridpilot.read_crop` with corners off the chunk grid | Align the crop to 128 px |
| `chunk CY/CX: N bytes, expected M` | A chunk read returned the wrong length | Retry the read |
| `the region needs a tile of margin on each side` | The render region lacks its tile margin | Choose the region with `choose_region` |

## How it works

Scoring (`kit/strokenet.py`, what the command runs):

1. Open the map keeping its dtype (`open_map`), crop it if asked (`snap_crop`), and resample it to 0.048 mm (`PIXEL_MM`) with `to_working`: block sums rounded half to even for an integer map at a whole fraction of 0.048 mm, which reproduces `data.py` `pool_array` exactly, otherwise exact area averaging.
2. Mark usable papyrus (value above `USABLE_MIN` = 3, opened three times with a cross, holes filled) and core papyrus (more than `CORE_MM` = 1.5 mm from any unusable pixel), then lay out 128 px (`CROP`) windows every `--stride` pixels and keep those with at least `MIN_USABLE_FRAC` = 0.99 core pixels (`layout`).
3. Score each kept window: normalize it on its own (median and MAD), run three-by-three convolutions with ReLU (batch norm folded in), 2 x 2 max pooling after each pair, global mean and max pooling, and one linear output. Then score the same windows turned by 90 degrees.
4. Draw `--sample` (`SAMPLE` = 64) kept windows at random with `numpy.random.default_rng(seed)`, make an IAAFT copy of each with `IAAFT_ITERS` = 200 iterations from the same generator, and report the share above each copy and the mean drop, next to the weights' `val_ref`.
5. Orientation hint: compare the share above the blank threshold as given and turned, or the mean logit when the shares are equal or missing.

The released network has width 16 and depth 5 (configuration `F_w16_d5_lr2e-3`, chosen by the preregistered rule, `choice.json` in the evidence). The numpy forward pass matched torch to 7.6e-6 in logit on validation (`NUMPY_TOL` = 1e-3 in `evaluate.py`).

The two-density score (`--two-density`, `two_density_analyze`), the map preparation its test used:

1. Read the map as float32 and stretch it (`density_stretch`): linear from its lowest finite value to its 99.9th percentile onto 0 to 255, clipped, NaN as 0, then times 251/255, rounded, plus 4, so the emptiest value is 4.
2. Pool it by k x k block means rounded half to even, k the whole number nearest 48 um over the pixel size (`density_pool_k`; 5 at 9.362 um, so one pooled pixel is 46.8 um); rows and columns past the last whole block are dropped. A mask is pooled the same way into papyrus shares.
3. Lay 48 px labels (`TD_LABEL`) every `--label-stride` pooled pixels (`TD_STRIDE` = 6) from the origin; with a mask keep those with at least half papyrus (`TD_PAPYRUS_MIN`).
4. For each label take `d48`, its mean on 0 to 1, and `d128`, the mean of the 128 px window (`TD_WIN`) centered on it in the pooled map padded by 40 px (`TD_PAD`) of value 4, both by summed-area tables.
5. `s = 1.0 z(logit d48) + 0.25 z(logit d128)` (`TD_WEIGHTS`), logit after clipping to 0.001 to 0.999, z over every scored label of the map with the population SD.

Training and the preregistered test (`scripts/strokenet/`):

1. `data.py`: pool each 2.4 um map 20 x 20 (`POOL`) to 0.048 mm; label text where the row profile repeats at a 4.5 to 9 mm line pitch (periodicity above 0.20) with ink density above 0.06, in blocks of at least 150 mm2, blank papyrus at least 3 mm from text with periodicity below 0.12 and density below 0.15, and dense ink as blank but with density at least 0.15; cut windows at strides `STRIDE` (training text 64, blank 32; held-out text 128, blank 64). The split takes the 28 tracings in order: index mod 4 = 0 test, 2 validation, odd train, then drops `w010-027`.
2. `train.py`: AdamW, 6,000 steps of 128 windows, half text (a quarter each tile- and strip-jittered), half negatives in `DEFAULT_MIX`, with flips, a gamma of 0.8 to 1.25 and Gaussian noise with a standard deviation of 0 to 3 gray levels per window; the final checkpoint is exported.
3. `pipeline.py`: six sweep configurations at seed 0, the best final monitor score chosen with ties within `TIE` = 0.002 going to fewer parameters; seeds 1 and 2, four ablations at three seeds, a no-jitter run, the permuted-label control and the artifact control; then validation, calibration and the gate (released T1 at least 0.90 and mean T1 to T4 at least 0.85, permuted control T1 under 0.95, numpy check within 1e-3: `GATE`, `CONTROL_T1_GATE`, `NUMPY_TOL`), and the single test read with markers that refuse a second read.
4. `evaluate.py`: every measure against the bar fixed on 7 October (`BAR`), block-bootstrap intervals, the eleven baselines, and the verdict line.

The tile grid: the organizers' maps carry a faint 6.4 px grid from their overlapping prediction tiles. `gridpilot.py` measured how much a finer tile stride removes it; the grid stays, so StrokeNet keeps its `grid` baseline and artifact control ([model card](../strokenet.md#known-limits-before-any-result)).

## Cost and time

- Scoring: numpy on any CPU. 4.4 s for a synthetic 300 x 400 px map at 0.048 mm with a small random network (measured 2026-10-16, 4-core cloud container); the released network on a whole segment: Not measured. It needs no GPU and no Modal.
- `--two-density`: numpy on any CPU, no download. 0.26 s for a synthetic 700 x 760 px map at 0.009362 mm with a mask (208 labels; measured 2026-10-22, cloud container). A whole segment: Not measured; it reads the whole map into memory as float32 (4 bytes per pixel).
- Data: `data.py fetch` downloads about 1.3 GB per segment for 27 segments. Time Not measured.
- Training: one run took 666 to 2,356 s on a CUDA GPU in the preregistered run, 1,506 s for the released configuration (`train_wall_s` in the evidence's `runs/*.history.json`). Training belongs on Modal, not a laptop (the Modal rule, hard rule 11), with a run spec and the user's go-ahead. The cost of the 14 October run: Not recorded in this repository.

## For agents

- **Command:** `python -m kit strokenet MAP.tif --pixel-mm 0.0024 --json` (add `--out RESULT.json` to keep it, `--grid GRID.npy` for the per-window grid, `--weights FILE.npz` to work offline). The two-density score: `python -m kit strokenet MAP.tif --pixel-mm 0.009362 --two-density --mask PAPYRUS.tif --json` (no weights, no network).
- **Parse:** `map.learned_n` and `map.learned_n_skipped` (windows scored and skipped), `map.learned_frac_above_val_blank_q99` and `map.learned_top10`, `controls.rot90.frac_above_copy` and `controls.iaaft.frac_above_copy` with their `val_ref`, `orientation_hint`, and `top_windows` positions in 0.048 mm pixels. With `--two-density`: `labels_scored` and `labels_skipped`, and per label `label_y_px`, `label_x_px` (source map pixels) and `s` (z units within this map).
- **Rerun:** Safe; scoring only reads its inputs and gives the same result for the same seed. `--out` and `--grid` overwrite their files. The scripts skip finished steps (`data.py` without `--force`, `pipeline.py` runs with a `history.json`), and the test read refuses to run twice.
- **Success:** Exit code 0 and `map.learned_n` above 0; with `--two-density`, exit code 0 and `labels_scored` above 0.
- **Not a pass:** A high `learned_mean` without the controls; a control share near the blank `val_ref` value; scores on a float, rescaled or rotated map, or on another scroll or ink model; any `calibrate()` value read as P(text); T2, T3 or T7 read as text structure. With `--two-density`: `s` compared across maps (it is z-scored within each map); a high `s` read as text; its one test (PHerc0500P2, ink_9um, a weak reader there) read as a result on other scrolls or readers; a map scored without `--mask`, where off-papyrus labels shift the z-scale.
- **Go-ahead:** Nothing to score public maps. Renting GPUs to train, uploading new weights, and posting any score need Chase's yes.
- **Never:** Call a score a reading or say text or letters were found; quote the two-density test in any words but its preregistered claim, "ahead of ink density inside segments on PHerc0500P2 with ink_9um"; publish scores or top windows of a target-scroll map; run training on a laptop CPU instead of Modal; read the test split a second time.

## Tests

```bash
python -m unittest tests.test_strokenet tests.test_strokenet_pipeline tests.test_strokenet_stats tests.test_gridpilot -v
```

`test_strokenet` covers the numpy network against a naive convolution, the normalization, resampling against brute force and against `data.py` pooling, strip reads, the usable and core masks (numpy against scipy and by hand), the window rule, NaN handling, the IAAFT copies against `nulls.py`, the controls on a random sample, the orientation hint, `open_map` dtypes, the SHA-256 check, `snap_crop` and the command line. `test_strokenet_pipeline` covers the splits, labels, nulls, numpy export against torch, the sweep choice, the one-time test read, and the evaluation rules; `test_strokenet_stats` the metrics and baselines; `test_gridpilot` the pilot. `TwoDensityTest` in `test_strokenet` covers the two-density score: window densities against brute force, the score's weights and within-map z, the values of the tested run's own code on a synthetic map at 9.362 um, the papyrus rule, and the command line (`--grid`, `--json`, and `--png` refused). Parts skip without numpy, torch or scipy. They use synthetic maps and random weights; they do not download the released weights or run on real segments.

## History

- 2026-10-22: the two-density score, `python -m kit strokenet --two-density` with `--mask` and `--label-stride`, and its preregistered test on PHerc0500P2 with ink_9um (`044a9ef`).
- 2026-10-17: `evaluate.py results` and `release` without `--out` stop at once with a usage error; before, `results` ran the whole evaluation and then crashed with a `TypeError` in `Path(None)`, and `release` crashed in `np.savez(None)` (`c0a06fe`).
- 2026-10-17: a `kit strokenet --out` that cannot be written is reported on stderr with exit code 2; before, it ended in a `FileNotFoundError` traceback, exit code 1, after the whole map had been scored (`56b8988`).
- 2026-10-14: tests skip without numpy (`d47c2ab`).
- 2026-10-14: first public release: `kit strokenet`, the scripts, the preregistered held-out result (missed its bar), the tile grid pilot and the weights `strokenet-paris4-v1` (`8d9ad54`).

## Related

- [StrokeNet model card](../strokenet.md): data, training, every held-out number and its limits.
- [Preregistration](../prereg/2026-10-14-strokenet.md) and [grid pilot preregistration](../prereg/2026-10-14-gridpilot.md): the rules fixed before the test. The grid pilot preregistration's links to its Modal runner (`scripts/strokenet/modal_gridpilot.py`) and Modal spec do not resolve here: those two files were not released publicly, and the frozen preregistration keeps its wording. The released readout is `scripts/strokenet/gridpilot.py`.
- [Evidence folder](../evidence/2026-10-14-strokenet/README.md): results, gate, calibration (`val_ref`, `q99`) and run histories.
- [`results.json`](../results.json): `strokenet_checks`, the held-out numbers, the grid pilot and the two-density test.
- [Reader exposure log](../logs/2026-10-16-reader-exposure.md): S7, `ink_9um`'s label dataset, which lists no PHerc0500P2 segment.
- [`auc`](auc.md): score an ink map against published labels.
- [`hpscore`](hpscore.md): letter-scale score against labels.
- [`letterread`](letterread.md): Scroll Text Reader, the learned Greek reader, with its own controls.
