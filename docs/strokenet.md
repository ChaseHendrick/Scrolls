# StrokeNet: a text-likeness score for 2D ink maps

Model card, written 14 October 2026 before the preregistered run; "Results" filled from the run's `results.json` the same day; "In short" added 18 October 2026 from the same numbers; "The two-density score", a simpler score with no network, added 22 October 2026. **StrokeNet misses its preregistered bar** on the held-out test of [`prereg/2026-10-14-strokenet.md`](prereg/2026-10-14-strokenet.md) (two of nine items); see "Results".

## In short

This describes version 1, the released model `strokenet-paris4-v1`. Every number is Model output on six held-out PHerc. Paris 4 tracings, from one ink model, with text and blank labels made by a rule (details and intervals under "Results").

- **7 of 9 bar items passed; 2 missed.** It missed T6, blank papyrus against its own 90 degree turn (0.639, where the bar asks for within 0.10 of 0.5), and FPR_blank, the share of blank windows above the threshold (0.021, bar 0.02). Both other seeds missed the same two.
- **Simple ink density matches it on its main job.** Telling text from blank papyrus (T1): density 0.996, StrokeNet 0.990. Simple scores met all 9 counted bar items.
- **Where it adds value: orientation.** It tells text windows from their own 90 degree turns far better than any simple score (T4 0.994; +0.141 over the `lines` score, 6 of 6 segments ahead), and the artifact control, which never saw text, stays near chance there (0.559). Window roughness tells text from dense ink better than StrokeNet does (T8, -0.055).
- **T2, T3 and T7 measure the tile grid, not text**: the artifact control reaches 0.999 on them.
- **Limits.** One reader's appearance: it saw only the organizers' `new_canon_autoresearch_recipe` maps, so maps from other ink models are outside what it learned (Interpretation). One handwriting: the label rule assumes Paris 4's line pitch (4.5 to 9 mm) with lines running along the rows (Sourced fact, `data.py`), so other writing sizes and turned maps got no text labels (Interpretation). Fixed input assumptions: the organizers' 0 to 255 scale, papyrus as values above 3, windows with at least 99 % core papyrus, a fixed 6.1 mm window, and maps at least 128 px at 0.048 mm on a side (Sourced fact, `kit/strokenet.py`). Float or rescaled maps, other scrolls and other ink models are not tested in this card's published evidence (Interpretation: expect it to do worse there).
- **A rework is in progress.** A version 5, for maps from any ink reader and any scroll and judged on human ink labels with a preregistered leave-one-scroll-out test, is being built in private work. Until it has a held-out result, this card's network and `kit strokenet` without `--two-density` describe version 1 only.
- **A simpler score, with no network** (22 October 2026). `kit strokenet --two-density` ranks small windows of one map by two ink densities, the window's own and its surroundings'. On its preregistered test it came out ahead of ink density inside segments on PHerc0500P2 with ink_9um (Model output), with a reader that reads that scroll weakly; numbers and limits under "The two-density score".

## What it is

StrokeNet is a small convolutional network (the released model has 589,393 weights at width 16, depth 5, the configuration the preregistered sweep chose: pairs of 3 x 3 convolutions with batch norm and ReLU, max pooling, global mean and max pooling, one linear output). It gives one logit for a 6.1 mm by 6.1 mm window of a 2D ink map (128 by 128 pixels at 0.048 mm): how much the window looks like lines of body text of PHerc. Paris 4 as the organizers' 2026 ink model draws them. It is trained against blank papyrus and against copies of text windows with their arrangement or orientation destroyed; dense ink without line structure is never a training negative and serves only to choose the configuration, in the calibration mixture and in the tests (T8, FPR_dense).

Intended uses: find where text-like ink is on a large ink map (simple ink density did as well on the held-out test, so compare with it), and tell text-like ink from ink that is merely dense. A score is model output: it is never a reading, and a high score where no text is known is not evidence that text is there.

The name is a project name. Nothing here tests whether it responds to strokes or letters as such. An unrelated model with the same name exists ("StrokeNet: A Neural Painting Environment", ICLR 2019).

## Data and labels

- Input maps: the organizers' 2.4 um ink predictions (`new_canon_autoresearch_recipe`, tile 256, stride 128) of PHerc. Paris 4's 28 tracings of 1 July 2026, at https://data.aws.ash2txt.org/samples/PHercParis4/segments/ (Sourced fact, listing read 14 October 2026). Pooled 20 by 20 to 0.048 mm, rounded half to even.
- Labels are made by a fixed rule from each map, not by people: text where the row profile repeats at a line pitch of 4.5 to 9 mm with enough ink, blank papyrus far from text without line periodicity, and dense ink without periodicity. Two measures therefore partly test the rule itself (text against blank, and text against its 90 degree turn).
- Splits by whole tracing: 14 training, 7 validation, 6 test; the innermost tracing is left out. Lists and window counts: the preregistration and [`strokenet-data-manifest.json`](strokenet-data-manifest.json).
- Windows lie on a 32 px lattice and hold at least 99 % core papyrus (usable papyrus more than 1.5 mm from any unusable pixel).

## Training

6000 steps of 128 windows: half text (half of them rebuilt from slightly jittered pieces, so that seams alone do not mark a negative; their seams are weaker than a shuffle's, so seam strength still can), half negatives (blank papyrus, IAAFT-20 copies, 4 by 4 tile shuffles and 90 degree turns of text windows), with flips, gamma and noise; the final checkpoint is the model. A sweep of six configurations picks the released one by a preregistered rule; seeds 1 and 2, four ablations at three seeds, a permuted-label control and an artifact control are trained with it. Code: [`../scripts/strokenet/`](../scripts/strokenet/).

## How it is tested

Preregistered before any test window was scored ([prereg](prereg/2026-10-14-strokenet.md)). The run used rented cloud GPUs; its runner script is not part of this repository.

- Measures on six held-out tracings: text against blank (T1, and average precision at 10 % prevalence), against IAAFT copies (T2), against shuffle and strip copies with seams on both sides (T3, T7; single seam numbers already separate these, so they cannot show arrangement), against its own 90 degree turn (T4), blank against its turn (T6), text against dense ink (T8), calibration on a fixed mixture (ECE, Brier) and false-positive rates at the validation blank threshold.
- A pass bar fixed on 7 October; eleven simple baselines fitted on the same training windows, with one rule for when StrokeNet adds over them (three primary measures, a per-segment sign-flip test); block-bootstrap intervals; seeds and ablations.
- Two controls that should fail. The permuted-label control voids any of T1, T1_AP, T2, T3, T4 and T4_paired on which it reaches the bar on validation. The artifact control never sees text; on any null measure, T4 or T8 that it separates at 0.75 or more, no claim that StrokeNet adds over simple scores is made, while the bar item still counts.
- The test split is read once: a finished read is never redone and markers refuse a read under another run, models or windows. A read cut short by a lost cloud container may be redone in the same run with the same models and windows, and nothing the cut-short attempt wrote is used. The read refuses uncommitted code and models other than the validated ones.

## Known limits, before any result

- One scroll, one hand, one ink model, one letter size. Nothing here shows it works on other scrolls, ink models or resolutions.
- Fixed input assumptions: the map on the organizers' 0 to 255 scale, usable papyrus as values above 3, only windows with at least 99 % core papyrus scored, and a fixed 6.1 mm window at 0.048 mm; a float, rescaled or turned map, or writing much smaller or larger than Paris 4's, is outside them.
- Rule-made labels: text against blank is nearly solved by ink density alone (validation T1 0.997 for the window mean).
- The tile grid: the organizers' maps carry a faint 6.4 px grid from their overlapping prediction tiles, the same in every map and at the same phase in every window. Null copies that lose or move it (IAAFT, strip, jittered and shuffled pieces) can be told from real windows by that alone, so T2, T3 and T7 may be withheld by the artifact control. Only T4 and T6 are free of it: on validation the grid alone separates text from dense windows at AUC 0.66 and from blank at 0.56, so the artifact control covers T4 and T8 too. Details: the preregistration, "The tile grid". A preregistered pilot (14 October 2026, [prereg](prereg/2026-10-14-gridpilot.md), evidence [`evidence/2026-10-14-strokenet/gridpilot-result.json`](evidence/2026-10-14-strokenet/gridpilot-result.json)) re-rendered one 9.2 mm region of `w028-037` with the organizers' checkpoint and recipe, which it reproduced exactly (r 1.000 with the published map). Moving the tiles by half a stride changes the 48 µm map by RMS 25.8 of 255 at the published stride 128, 12.3 at stride 64 and 6.3 at stride 32 (Model output). The fall is what averaging 4 and 16 times as many tiles per pixel would give, so a finer stride shrinks the tile dependence but does not remove it, and a full re-render would take about 183 GPU hours at stride 64 on one B300 (107 tiles per second). StrokeNet keeps its grid baseline and artifact control instead (Interpretation). The pilot's preregistration links a Modal runner (`scripts/strokenet/modal_gridpilot.py`) and a Modal spec (`compute/modal-specs/2026-10-14-gridpilot.md`) that were not released publicly, so those two links do not resolve here; the preregistration is frozen and stays as written. The released readout, region choice and range reads are [`scripts/strokenet/gridpilot.py`](../scripts/strokenet/gridpilot.py), tested by `tests/test_gridpilot.py`.
- T3 and T7 cannot show arrangement: on validation one seam number with no fitting separates their two sides at AUC 1.000. The bar item T3 still counts, as fixed on 7 October, but meeting it shows nothing beyond that.
- IAAFT copies keep a small excess of high-frequency power on these maps; the `nullspec` baseline measures how far that alone goes.
- Probabilities are calibrated only to the fixed evaluation mixture, not to text on a real map, so `kit strokenet` reports logits, not probabilities.

## Using it

```sh
python -m kit strokenet MAP.tif --pixel-mm 0.0024 [--weights W.npz] [--crop Y0 Y1 X0 X1] [--grid G.npy] [--json]
```

numpy only (scipy is used when present and gives the same result). The map must be on the organizers' 0 to 255 scale; an integer map at a whole fraction of 0.048 mm is pooled exactly as in training. `--pixel-mm` must lie between 0.0001 and 1 mm: at 1 mm a 6.1 mm window spans about 6 map pixels and a letter 2 to 4, so nothing coarser shows strokes, and a coarser value would only enlarge the map further; 0.0001 mm (0.1 um) is ten times finer than any scroll scan. Other values, and values that are not finite, stop with an error before anything is loaded. Only windows with 99 % core papyrus are scored, and skipped windows are counted. Every result carries two controls on a random sample of the scored windows (each window against its 90 degree turn and against an IAAFT copy of itself), read against the validation reference values stored with the weights, and an orientation hint. `--crop` moves its origin down to the 32 px training lattice and records both boxes.

```sh
python -m kit strokenet MAP.tif --pixel-mm 0.009362 --two-density [--mask PAPYRUS.tif] [--grid G.npy] [--out R.json] [--json]
```

runs the two-density score below instead of the network: no weights, no download, numpy only.

## Results

Run `20261014T141348Z` (14 October 2026): sweep at `d1f9dbfd`, then resumed at `fb65f0b3` after the cost guard stopped it, with every executed file except the runner unchanged (commits of the private working repository; `results.json` records each executed file's SHA-256, and the copies here match them); finals on L4 and A10G, validation and the single test read on A10. Evidence: [`evidence/2026-10-14-strokenet/`](evidence/2026-10-14-strokenet/README.md) (`results.json` has every value below, per-segment values for every model and baseline, and the intervals). Test split: six whole held-out segments (w053-058, w073-076, w089-091, w101-103, w113-115, w122-123), 3859 text, 1407 blank and 354 dense windows, read once. All numbers are Model output on held-out tracings of one scroll from one ink model with rule-made labels.

**Verdict line (preregistered form):** StrokeNet misses its bar on T6_dev, FPR_blank; simple scores meet 9 of 9 counted bar items; bar met by 0 of 3 seeds; adds over simple scores on T4 of the primary measures (T2, T4, T8); not interpretable as text structure: T2, T2_20, T3, T3_raw, T7, T7_raw.

Gate (validation, before the test): passed. Released T1 0.995, mean T1 to T4 0.998; permuted-label control T1 0.765 (under 0.95, so nothing is void); numpy inference matches torch to 7.6e-6 in logit. The data rebuilt from the organizers' maps matched the committed manifest in all 27 segments.

| Bar item | Bar | Released model (95 % block-bootstrap interval) | Passes | Best simple score |
| --- | --- | --- | --- | --- |
| T1 text vs blank | >= 0.95 | 0.990 (0.986 to 0.993) | yes | density 0.996 |
| T1_AP | >= 0.80 | 0.952 (0.944 to 0.969) | yes | density 0.982 |
| T2 text vs IAAFT copies | >= 0.90 | 1.000 (1.000 to 1.000) | yes | grid 0.982 |
| T3 tilejit text vs shuffle copies | >= 0.80 | 1.000 (1.000 to 1.000) | yes | seam32 1.000 |
| T4 text vs rot90 copies | >= 0.80 | 0.994 (0.992 to 0.995) | yes | texture 0.865 |
| T4_paired | >= 0.80 | 0.974 (0.968 to 0.980) | yes | texture 0.843 |
| T6 blank vs rot90 blank, distance from 0.5 | <= 0.10 | 0.139 (0.112 to 0.175); T6 = 0.639 | **no** | several at 0.5 |
| ECE | <= 0.05 | 0.042 (0.034 to 0.051) | yes | lines 0.011 |
| FPR_blank | <= 0.02 | 0.021 (0.012 to 0.034) | **no** | skew 0.001 |

Seeds 1 and 2 miss the same two items (T6 0.696 and 0.648; FPR_blank 0.025 and 0.024). Other measures of the released model: T2_20 1.000, T3_raw 1.000, T7 0.967, T7_raw 0.891, T8 text vs dense 0.643 (0.618 to 0.668), Brier 0.099, FPR_dense 0.884, TPR_text 0.918; blank against its own copies: C_iaaft 0.985, C_shuffle 0.926, C_strip 0.614.

**Against simple scores** (StrokeNet minus the baseline best on validation, mean over the six segments; it adds only when all six differences are positive and the mean is at least 0.01):

- T4: +0.141 over `lines` (0.125 to 0.159), 6 of 6 segments positive, p = 1/64. **Adds**, and the artifact control stays at 0.559 on T4, so this is the one primary measure that can be read as structure the simple scores lack.
- T8: -0.055 against `roughness` (-0.106 to -0.005), 2 of 6 positive: does not add; StrokeNet tells text from dense ink worse than window roughness does.
- T2: +0.018 over `grid`, 6 of 6 positive, but withheld: the artifact control, which never sees text, reaches 0.999 on T2 (and about 1.000 on T3 and T7), so those measures show the tile grid, not text structure. T1, T3 and T7 do not add.

**Controls.** Permuted labels: T1 0.665 and every structure measure 0.48 to 0.54 on test. Artifact control: T2 0.999, T3 1.000, T7 1.000, but T4 0.559 and T8 0.555, as the preregistration expected.

**Ablations** (effects that meet the preregistered seed-and-segment rule): with no null training at all, T2, T3, T4 and T7 fall to 0.66, 0.62, 0.59 and 0.45; without rot90 copies T4 falls to 0.64; without shuffle copies T3 and T7 fall to 0.59 and 0.40; without IAAFT copies T2 falls to 0.65. Each null type teaches the measure built on it, which is what training against them was for.

**Reading (Interpretation).** StrokeNet is a strong text-against-blank detector, but density alone does as well. Its one result beyond simple scores is orientation: it tells text windows from their 90 degree turns far better than any simple score (0.994 against 0.865). That is not pure text structure either: it also tells blank papyrus from turned blank papyrus at 0.639, which is the T6 failure, so part of what it learned is the direction of the papyrus or of the map, not of the writing. It does not tell text from dense ink better than roughness, and the null tests T2, T3 and T7 are explained by the tile grid. So the honest summary is: a held-out, controlled test of a text-likeness score that misses its bar, with one orientation result that survives the controls.

## The two-density score

Added 22 October 2026. Plain ink density is the score StrokeNet has to beat, and on its own test it did not (T1 above). The two-density score is a small step past it, with no network and no training: it adds to a window's own ink density how much ink surrounds the window. `python -m kit strokenet MAP --pixel-mm P --two-density` computes it with numpy only; the tool page has every option and output field.

**The score.** The map is stretched linearly to 0 to 255, from its lowest value to its 99.9th percentile, and pooled by the whole number of pixels nearest 48 um (5 for a 9.362 um map, so one pooled pixel is 46.8 um). Label windows of 48 pooled pixels (about 2.2 mm) are laid every 6 pooled pixels; with a papyrus mask, labels under half papyrus are skipped. For each label, d48 is its mean ink on 0 to 1 and d128 the mean ink of the 128 px window (about 6 mm) centered on it, with the map padded as empty. Then

```text
s = z(logit d48) + 0.25 z(logit d128)
```

where z is taken within the map over every scored label (population standard deviation). The first term ranks labels exactly as plain density does; the second adds the surroundings. The weights 1.0 and 0.25 were fixed before the test, on maps of other segments, not on ink_9um maps. Because z is taken within one map, s ranks windows of that map; it does not compare maps.

**The test.** One run on 22 October 2026 on public PHerc0500P2 data, preregistered before any map of a test segment existed (the preregistration is not published here). The reader was ink_9um (`scrollprize/ink_9um`, step 75,000) run with villa's inference on the segments' 9.362 um surface volumes: seed 42 is the primary reader and the verdict rests on it; seed 43 was scored the same way as a descriptive replication. ink_9um's label dataset lists no PHerc0500P2 segment (Sourced fact, S7 in the [reader exposure log](logs/2026-10-16-reader-exposure.md)). Text and blank labels were made by a fixed rule from the team's published 2.215 um ink map of each segment (`new_canon_autoresearch_recipe`), so they are model output from a finer scan, not human labels. 11 test segments had at least 10 text and 10 blank labels; together they hold 62,220 text and 6,468 blank label positions.

The measure: within each segment, the AUC of text against blank for s and for plain density (logit d48), and d, the mean over segments of AUC(s) minus AUC(density), with a 95 % interval from a block bootstrap (1 cm blocks resampled within each segment). The verdict "ahead" needed the interval's lower bound above 0, and no verdict was allowed unless two controls passed, each requiring the control's mean within-segment AUC of s to be at least 0.10 below the real one: s on the reverse-depth maps (the depth order reversed, see the glossary's "As stored / reversed"), and s against labels moved by cyclic shifts of at least 10 mm (the median over 20 shifts).

**Results** (Model output, all on the 11 segments):

| Reader | Mean d within segments (95 % interval) | Mean within-segment AUC, s / density | Segments where s beats density | Reverse-depth control | Shifted-label control | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| ink_9um seed 42 (primary) | 0.040 (0.028 to 0.050) | 0.701 / 0.662 | 11 of 11 | 0.574, pass | 0.507, pass | ahead |
| ink_9um seed 43 (descriptive only) | 0.048 | Not stated here | 11 of 11 | **fail** | Not stated here | none |

The preregistered claim, the only wording this result may be quoted in: **"ahead of ink density inside segments on PHerc0500P2 with ink_9um"**. With seed 42 the per-segment gain ran from +0.010 to +0.104, median +0.029. Seed 43's reverse-depth control failed: its s on the reverse-depth maps was less than 0.10 below its s on the real maps, so its row is not evidence for the score (Interpretation), although it too put s above density in 11 of 11 segments.

**Limits.**

- **A weak reader.** ink_9um reads this scroll weakly: plain density's mean within-segment AUC is 0.66, and on one segment it is below 0.5. A gain over a weak baseline says nothing about how s does with a strong reader.
- **One scroll, one reader, one read.** The verdict rests on one reader's maps of one scroll, read once. Other scrolls, other ink models and other resolutions are untested.
- **The interval is likely too narrow.** Three pairs of test segments share papyrus, while the bootstrap treats segments as independent.
- **The wide window also reads the footprint.** Off-papyrus pixels and the padding count as empty, so a label near a segment edge or a hole gets a lower d128 whatever its ink. Part of the gain may come from where blank labels lie on the papyrus rather than from ink. This was not tested (Untested idea).
- **The weights were set elsewhere.** 1.0 and 0.25 were chosen on maps of other segments before the test; whether they suit ink_9um, or any other reader, is untested.
- **Labels from a model.** The text and blank labels come from the team's finer-scan ink map, not from people.
- **Not StrokeNet's network.** The score uses no learned weights and says nothing about strokes, lines or letters. A score is model output, not a reading, and a high score is never by itself evidence that text is there.

Claim label: Model output, for every number in this section; the claim covers PHerc0500P2 with ink_9um only.

## License and release

Released 14 October 2026 as `strokenet-paris4-v1`, a GitHub release of this repository (`kit strokenet` downloads it once and checks its SHA-256, listed in [`../kit/data/strokenet-weights.json`](../kit/data/strokenet-weights.json)). The weights are trained on the organizers' published PHerc. Paris 4 ink maps and are licensed CC BY-NC 4.0, the license the organizers publish with their scan data (for example https://data.aws.ash2txt.org/samples/PHerc0009B/LICENSE.txt); the code is under this repository's Apache 2.0 license. The evidence folder [`evidence/2026-10-14-strokenet/`](evidence/2026-10-14-strokenet/README.md) holds the run's results, gate, calibration, choice, baselines and training histories; window positions, score grids and evaluation arrays are not published, as the preregistration says.
