# Preregistration: StrokeNet's held-out test on PHerc. Paris 4 ink maps

Written 14 October 2026, before any model or baseline has scored a window of the test split.
The code it names is in `scripts/strokenet/` and `kit/strokenet.py`. The frozen commit is the
commit of this branch that the runner prompt and the handoff name, made before any training run;
the run checks it out and the launcher records it in `driver.json`. Earlier commits of this file
are drafts, all made before any model or baseline scored a test window. Changes after the frozen
commit go in a dated amendment at the end; nothing above it is edited. The run records the
SHA-256 of every one of those files and of this document, and the test read refuses to start when
any of them has uncommitted changes against the checked-out commit. A code change after the frozen
commit needs a dated amendment here before the test read.

## What StrokeNet is, and what this test can show

StrokeNet is a small convolutional network (about 0.3 million parameters at the default size)
that gives one number for a 6.1 mm by 6.1 mm window of a 2D ink map (128 by 128 pixels at
0.048 mm): how much the window looks like lines of body text of PHerc. Paris 4 as the organisers'
2026 ink model draws them. It is trained against blank papyrus and against copies of text windows
with part of their structure destroyed; dense ink without line structure is never a training
negative; it is used to choose the configuration (the monitor's T8), in the calibration mixture,
and in T8 and FPR_dense. Its intended uses are to find where text-like ink is on a large map, and
to tell text-like ink from ink that is merely dense. The name is a project name: nothing here
tests whether it responds to strokes or letters as such.

On six tracings of the same scroll that no model trained on or was tuned on, the test can show:
whether the score separates text windows from blank papyrus (mostly agreement with the labelling
rule below), from dense ink without line periodicity (T8), from the same windows turned by 90
degrees (orientation, T4), from IAAFT copies that keep each window's pixel values (T2), and from
cut-and-paste copies with seams on both sides (T3, T7; single seam numbers already separate these,
so they cannot show arrangement, see "Nulls and seam-matched windows"); how much of each separation
simple scores fitted on the same training windows already give; and whether its probabilities are
calibrated on one fixed mixture of windows. It cannot show that StrokeNet reads letters, that it
works on other scrolls, hands, letter sizes or ink models, or that a high score where no text is
known means text is there. Every number it produces is model output.

## History before this document

- 7 October 2026: an earlier preregistration, kept in a private file that also holds unrelated
  plans and is not published, fixed the split rule, the test sets T1 to T6 and the pass
  thresholds used below; an addendum the same day, written before any training, set the window to
  128 px and loosened the blank-papyrus rule. Three training runs then scored the validation split
  only (Model output): a pilot on partial data (step 250: T1 0.986, T4 0.880); run A (width 16,
  depth 4, learning rate 2e-3, 2000 steps, plain phase nulls; at step 2000: T1 0.992, T2 1.000
  against plain phase copies, T3 1.000, T4 0.979); and a run at learning rate 1e-3 stopped at
  step 500 (T1 0.994, T4 0.901). No window of the test split was scored by any model or by any of
  the baselines below, then or since. Summary statistics of large text areas of every segment,
  test segments included, were computed on 7 October for other work; none is a StrokeNet score or
  one of the baselines here.
- 14 October 2026, before this document: the dataset was rebuilt from the public files by
  `scripts/strokenet/data.py`; its label areas and window counts equal the 7 October records
  (for example w095-097: 61,241 mm2 usable, 32,832 mm2 text, 9,079 mm2 blank; 666 text, 265 blank
  and 40 dense windows). The window counts of every segment are in
  `docs/strokenet-data-manifest.json`. The first version of the new code was smoke-run on 40
  validation windows and reviewed from four sides (statistics, machine learning, code, release).
  The reviewers' development checks, on training and validation windows only, shaped the design
  below; their numbers are listed in "Development checks". While the data were built and
  reviewed, logs printed the label areas and window counts of test segments w053-058 and w089-091;
  no test window was opened, viewed or scored. The tile-grid check below computed one pixel-step
  profile (mean absolute difference of neighbouring pixels by position modulo 32) per pooled map,
  test maps included, to see whether the grid is the same in every map; it uses no window, label
  or score, and the numbers quoted below come from training and validation maps only.

## Data

- Source: the organisers' 2.4 um ink predictions (model `new_canon_autoresearch_recipe`, tile 256,
  stride 128) of the 28 tracings of PHerc. Paris 4 uploaded on 1 July 2026 (folder stamps
  20260701183124 to 20260701183151), on volume 20260411134726, at
  https://data.aws.ash2txt.org/samples/PHercParis4/segments/ (Sourced fact: file listing read
  14 October 2026). Older tracings of the same wraps are not used.
- The innermost tracing, w010-027, was a test segment in the 7 October split and is kept out of
  this work entirely. The test split therefore has 6 segments, not 7.
- Each map is pooled 20 by 20 to 0.048 mm and rounded to whole values (half to even).
- The listing does not say whether the organisers' ink model was trained with labels from these
  tracings (unknown). The test below is held out for StrokeNet and its baselines, not for the ink
  model that drew the maps.
- Labels are made from each pooled map by a fixed rule (`data.label_map`): text where the row
  profile repeats at a line pitch of 4.5 to 9 mm and ink density is above 0.06, in blocks of at
  least 150 mm2; blank papyrus at least 3 mm from text, without line periodicity and with ink
  density below 0.15; dense where the same holds but density is 0.15 or more. Labels come from the
  ink map, not from people, so two tests partly measure the rule itself: text against blank (T1),
  which window density alone nearly solves, and text against its rot90 copy (T4), because the rule
  selects windows with horizontal line periodicity, which a 90 degree turn removes. Dense windows
  are rule-made negatives and may hold faint or irregular text.
- Usable papyrus: map value above 3, opened three times with a cross, holes filled; core papyrus:
  usable and more than 1.5 mm from any unusable pixel. Every label lies in core papyrus.
- Windows (`data.crops_from`): 128 by 128 px, at least 99 % core papyrus and 90 % of one class;
  blank and dense windows contain no text pixel. Window corners lie on a 32 px lattice from each
  map's origin. Strides: training text 64 px, blank 32 px, dense 64 px;
  validation and test text 128 px (no overlap), blank 64 px, dense 128 px.

## Splits (whole segments)

Over the 28 tracings in order from w010-027 outward, index i % 4 == 0 is test, i % 4 == 2 is
validation, odd i is training (7 October rule); w010-027 (index 0) is then removed.

- Training (14): w028-037, w046-052, w059-063, w069-072, w077-080, w085-088, w092-094, w098-100,
  w104-106, w110-112, w116-117, w120-121, w124-125, w128-129.
- Validation (7): w038-045, w064-068, w081-084, w095-097, w107-109, w118-119, w126-127.
- Test (6): w053-058, w073-076, w089-091, w101-103, w113-115, w122-123.

Neighbouring segments are neighbouring wraps, so faint ink of one wrap can show in its neighbour
across a split boundary; this is accepted and stated. (A reviewer found no duplicated papyrus at
the ends of adjacent training and validation tracings: normalised cross-correlation 0.15 to 0.26,
like unrelated pairs.)

## Nulls and seam-matched windows (`scripts/strokenet/nulls.py`)

Copies of a window with one kind of structure destroyed:

- `iaaft`: IAAFT surrogate (Schreiber and Schmitz 1996, Phys. Rev. Lett. 77, 635,
  https://doi.org/10.1103/PhysRevLett.77.635), 200 iterations: the same pixel values and nearly
  the same amplitude spectrum, arrangement scrambled. On these narrow-range uint8 windows the copies
  keep a measurable excess of high-frequency power (see "Development checks"), so a score may reject
  them through that residue; the `nullspec` baseline measures how far the residue alone goes.
  `iaaft20` is the same with 20 iterations (training negatives, the training monitor, T2_20).
- `phase`: plain phase randomisation (the 7 October null), rounded and clipped to whole values in
  0 to 255: the spectrum kept, the histogram made nearly Gaussian.
- `shuffle`: 4 by 4 tiles of 32 px permuted, each turned by a random multiple of 90 degrees and
  flipped at random (the 7 October addendum said 36 px; the code has always used 32 px so the tiles
  divide the window). Leaves seams on the 32 px lattice.
- `rot90`: the window turned 90 degrees.
- `strip`: 16 vertical strips of 8 px permuted: rows keep their values, letters are cut apart.
  Leaves seams on the 8 px lattice.

Seam-matched windows (`nulls.jitter`): `tilejit` and `stripjit` rebuild a window on the shuffle
or strip lattice, every piece in its own place and orientation but taken from the pooled map at an
independent random offset of up to 3 px in each direction (clipped at the map edge). They carry
seams on the same lattice as the nulls while keeping the letters nearly intact. They do not remove
the seam cue. On 800 validation text windows, single numbers with no fitting, after the direction
set on validation, separate tilejit text from shuffle copies at AUC 1.000 (`seam32`; `seam8` 0.999,
`grid` 0.996) and stripjit text from strip copies at 1.000 (`seam8`) (Model output, 14 October).
T3 and T7 therefore cannot show that StrokeNet uses arrangement. The bar item T3 still counts in
the verdict, as fixed on 7 October, but meeting it shows nothing that these seam numbers do not;
and with a reference baseline at about 1.000, the comparison rule below cannot find StrokeNet
adding over simple scores on T3 or T7. Both are reported as measured.

## Training (`scripts/strokenet/train.py`)

Every run: 6000 steps of 128 windows. Positives (64): text windows, 50 % as they are, 25 %
`tilejit`, 25 % `stripjit`. Negatives (64), drawn with shares blank 0.4, IAAFT-20 0.2, shuffle 0.2,
rot90 0.2: blank windows with the same jitter shares and half of them turned 90 degrees, and nulls
of text windows. Random horizontal and vertical flips; gamma 0.8 to 1.25 per window; Gaussian noise
with a standard deviation drawn per window from 0 to 3; per-window median and MAD normalisation
clipped to -3..20 and divided by 5; AdamW, weight decay 1e-4, cosine learning rate to zero with
200 warm-up steps. **The final checkpoint is the model.** Every 500 steps a fixed validation
monitor set (seed 12345: text, blank and dense windows, IAAFT-20, shuffle, tilejit and rot90
copies) is scored for the record; its `select` value is the mean of the monitor's T1, T2_20, T3,
T4 and T8.

Stage 1, six configurations at seed 0: A width 16, depth 4, learning rate 2e-3 (the 7 October
default); B lr 1e-3; C lr 4e-3; D width 8; E width 32; F depth 5. Among the runs whose final
`select` is within 0.002 of the best, the one with the fewest parameters is chosen; equal
parameter counts go to the higher `select`, then to the earlier letter.

Stage 2, all on the chosen configuration: seeds 1 and 2; four ablations, each at seeds 0, 1 and 2:
no nulls (blank negatives only), no IAAFT, no shuffle, no rot90 (the other shares rescaled); one
run without seam-matched windows (seed 0); the permuted-label control (seed 0, labels of each batch
permuted at random); and the artifact control (seed 0): blank windows as positives and IAAFT-20,
shuffle and strip copies of blank windows as negatives in equal shares, so it never sees text and
can learn only what the nulls themselves leave behind.

**The released model is the chosen configuration at seed 0**, fixed now, whatever the other seeds
score.

## Baselines (`scripts/strokenet/baselines.py`)

Fitted only on training windows. Seven single numbers, whose direction (higher means text, or
lower) is set for each measure on the validation split: `density` (window mean), `skew` (skewness
of the values), `lines` (row-profile against column-profile variance), `roughness` (log mean
squared Laplacian), `seam8` and `seam32` (log ratio of mean absolute neighbour differences across
the 8 px or 32 px lattice lines to those elsewhere), and `grid` (the same ratio across the lines of
the organisers' 6.4 px tile grid; see "The tile grid"). Four fitted scores, read as higher means
text: `spectrum` (logistic regression on log power in radial and angular bins of the window's
spectrum up to the corner frequency), `texture` (the same features plus the seven single numbers,
a gradient-orientation histogram and value quantiles), both trained on 8000 positives and 8000
negatives drawn like StrokeNet's training batches (the same mixture, jitter shares and blank
rotation, without flips, gamma or noise); `nullspec` (the spectrum features,
trained on 8000 training text windows against their own IAAFT-20 copies: a detector of the IAAFT
residue that knows nothing of arrangement); and `randcnn` (the chosen architecture with frozen
random weights, batch-norm statistics set on training windows, and a logistic head trained like
`spectrum`).

## The order of the run, and the gate

1. prep: the monitor windows, the three training-mixture baselines, and the validation evaluation
   windows (`nulls.eval_sets`, seed 777): text, blank, dense, and every null and seam-matched copy
   of text and blank. The SHA-256 of every array is recorded.
2. sweep, choice, finals (above).
3. validate: `randcnn` is fitted; every model and baseline scores the validation windows; numpy
   inference (`kit/strokenet.py`) is compared with torch on the CPU over the first 500 text and 500
   blank validation windows; scoring runs in full fp32 (TF32 off). `evaluate.calibrate` then writes
   `calibration.json` from validation only: each model's Platt parameters and blank threshold,
   each single-number baseline's directions, the reference baseline for each measure, and the
   validity checks below. Its SHA-256 goes into `gate.json`; results refuse a calibration file
   with another hash.
4. Gate: the released model's validation T1 is at least 0.90 and its mean of T1, T2, T3 and T4 at
   least 0.85; the permuted-label control's validation T1 is below 0.95; the numpy check's largest
   logit difference is at most 1e-3. If the gate fails, the test split stays unread and the run is
   reported as stopped; any retraining after a failed gate needs a dated amendment here first.
5. test: the test evaluation windows (seed 778) are built and scored once. Markers written before
   the first test window is scored (in the run folder and in the data folder) refuse any test read
   under another run folder, with other models or with other test windows, and a finished read
   (`read_test.npz`, written last) is never redone. A read cut short before it wrote
   `read_test.npz` (a lost cloud container) may be redone in the same run folder with the same
   models and windows; whatever the cut-short attempt wrote is deleted first and never used or
   shown, and every attempt is listed in the marker.

## Measures (all AUC unless stated; "text" means text windows)

| Measure | Definition |
| --- | --- |
| T1 | text against blank |
| T1_AP | average precision with text at 10 % prevalence (mean of 20 random subsamples of text) |
| T2 | text against its IAAFT copies (200 iterations); T2_20 against 20-iteration copies; T2_plain against plain phase copies |
| T3 | tilejit text against shuffle copies (seams on both sides); T3_raw text against shuffle copies (the 7 October definition) |
| T4 | text against its rot90 copies; T4_paired: share of text windows scoring above their own rot90 copy |
| T6 | blank against rot90 copies of blank |
| T7 | stripjit text against strip copies; T7_raw text against strip copies |
| T8 | text against dense windows |
| C_iaaft, C_shuffle, C_strip | blank against its IAAFT copies, tilejit blank against shuffle copies of blank, stripjit blank against strip copies of blank (reported only) |
| ECE, Brier | after Platt scaling, on a fixed mixture: text weight 0.5; blank, dense, IAAFT, shuffle and rot90 copies 0.1 each. The probabilities are calibrated to that mixture only, not to text on a real map |
| FPR_blank, FPR_dense, TPR_text | shares of test blank, dense and text windows whose logit is above the validation blank windows' 99th percentile |

Paired shares (T2_paired, T3_paired, T7_paired) are reported beside their AUCs.

## Pass bar (the 7 October thresholds)

On the test split, point estimates, released model: T1 >= 0.95; T1_AP >= 0.80; T2 >= 0.90;
T3 >= 0.80; T4 >= 0.80; T4_paired >= 0.80; |T6 - 0.5| <= 0.10; ECE <= 0.05; FPR_blank <= 0.02.
The thresholds are those of 7 October; T2 and T3 now use IAAFT and seam-matched positives (see
"Deviations"). The same nine items are also computed for every other model and every baseline,
each with its own validation calibration.

The verdict line is fixed now: "StrokeNet meets its preregistered bar" or "misses its bar on" the
failing items; then "simple scores meet k of n counted bar items" (n is nine less any void
measure; an item counts when any baseline meets it);
"bar met by k of 3 seeds" (seed 0, which is the released model, and seeds 1 and 2); the primary
measures on which StrokeNet adds over simple scores; and any void or not interpretable measures.
Meeting the bar is not by itself evidence that StrokeNet learned anything simple scores lack.

## Checks that can void or withhold (from validation, before the test read)

1. Permuted-label control: a bar measure on which it reaches the bar on validation (T1, T1_AP, T2,
   T3, T4 or T4_paired) is void: reported, but not counted in the verdict. Its T1 reaching 0.95
   stops the run at the gate.
2. Artifact control: on any of T2, T2_20, T3, T3_raw, T4, T7, T7_raw and T8 where it reaches AUC
   0.75 on validation, that measure is "not interpretable as text structure": the bar item is
   still reported and counted, but no claim that StrokeNet adds over simple scores is made on it.
3. numpy inference matches torch (gate).

The test-split values of both controls are reported as confirmation. That IAAFT copies keep each
window's values exactly is a unit test (`tests/`), not a check of the run.

Expected from the development checks (Interpretation, written before any model scored a window):
the artifact control will probably reach 0.75 on T2, T3 and T7, because the tile grid below lets a
model separate real windows from those copies with no text at all. Those measures would then be
reported but not interpreted as text structure. The grid is not confined to the null measures:
with no fitting, `grid` separates validation text from dense windows at AUC 0.66 (0.53 to 0.74
within single segments) and text from blank at 0.56 after its direction (0.62 to 0.73 within single
segments), because the grid shows more at some ink levels than at others (mean `grid` of text -0.48,
blank -0.45, dense -0.59; 4780 text, 2057 blank and 333 dense windows). Only T4 and T6, which
compare windows with their own turned copies, are exactly 0.50 for `grid`. Hence the artifact
control also covers T4 and T8, and `grid` is one of the baselines every comparison is made against.

## Comparisons with simple scores, and uncertainty

- Reference: for each of T1, T2, T2_20, T3, T3_raw, T4, T7, T7_raw and T8, the baseline with the
  best validation value (after its direction).
- StrokeNet adds over simple scores on a measure when the mean over the six test segments of the
  per-segment difference (StrokeNet minus reference) is at least 0.01 and the exact one-sided
  sign-flip p over the segments is at most 0.05 / 3. With six segments that needs all six
  differences positive (p = 1/64). Primary comparisons: T2, T4 and T8 (three, hence 0.05 / 3);
  the others are reported with the same rule and labelled descriptive. A segment with fewer than
  10 windows of a kind a measure needs is left out of that measure's per-segment values.
- Intervals: 95 % percentile intervals from 2000 bootstrap resamples of blocks (512 px, 24.6 mm
  column bands within each segment; text, blank and dense windows of a drawn block are taken
  together, so pairs stay paired) for every measure of the released model and every comparison.
  Per-segment values of the AUC and paired measures and of FPR_blank are listed for every model and
  baseline, and a 5-degree-of-freedom t interval
  of the per-segment differences is reported as descriptive.
- Seeds and ablations: seeds 1 and 2 and every ablation are reported on every measure. An ablation
  effect on a measure is claimed only when the ablation's mean over its three seeds lies outside
  the range of the released configuration's three seeds and the per-segment difference of the seed
  means has the same sign in at least 5 of the 6 test segments.

## Development checks that shaped this design (validation and training windows only)

All Model output, from the reviews and checks of 14 October; none touched a test window.

- Window density alone gave validation T1 0.997 and T1_AP 0.991; text against dense windows
  0.42 to 0.50 for density (dense windows are brighter), 0.69 for lines, 0.69 for a random-feature
  CNN: T8 is the comparison simple scores do not solve.
- IAAFT residue: a logistic regression on log-power spectrum features, trained on training text
  against 20-iteration IAAFT copies, separated validation text from 20-iteration copies at AUC
  0.91 and from 200-iteration copies at 0.84 (0.86 when trained on 200-iteration copies); the copy
  scored below its own window in 97 to 99 % of pairs. Dithering before IAAFT did not change this.
  A Gaussian blur of every window removed a Laplacian-energy cue (AUC 0.18 to 0.49) but not the
  log-spectrum cue (0.99), so no blur is used and `nullspec` is a baseline instead.
- Seams: one fixed-seam statistic separated text from shuffle and strip copies, and blank from
  the same copies of blank, at AUC 1.000; hence the seam-matched T3 and T7, the jittered training
  windows and the seam baselines. A later check found the seam-matched T3 and T7 solved by single
  seam numbers too (1.000; see "Nulls and seam-matched windows"), so they are reported measures
  that cannot show arrangement.
- A linear model on 84 features of an earlier draft (20 hand features and 64 spectrum features)
  reached T1 0.989, T2_20 0.975, T3_raw 1.000, T4 0.873 and T7_raw 1.000 (T7_raw without ever seeing
  a strip copy), and a random-feature CNN with a fitted head T1 0.951, T2_20 0.863, T3_raw 0.972
  and T4 0.704; the lines score reached T4 0.894. These used the earlier definitions: IAAFT copies
  of 20 iterations, and plain shuffle and strip copies. Hence `texture` and `randcnn`.
- Untrained networks reached single AUCs from 0.21 to 0.71 on validation, so the control rules are
  per measure.
- The tile grid: see the next section.
- An earlier Platt fit diverged at realistic logit scales; scoring on a GPU with TF32 would have
  differed from fp32 by up to 0.036 logit. Both are fixed in this code.

## The tile grid (development checks, training and validation maps only)

The organisers' maps are predicted in overlapping 256 px tiles at stride 128 px on the 2.4 um grid
(the `tile 256, stride 128` of the file names), blended with weights that fall towards each
tile's edge. At 0.048 mm that is a 6.4 px grid, which repeats exactly every 32 px. Model output
and Sourced fact (the file names), measured 14 October on all 21 training and validation maps:

- The mean absolute step between neighbouring pixels of usable papyrus, by position modulo 32,
  pooled over the training maps and again over the validation maps, ranges from 0.77 to 1.05 of its
  median (largest deviation 0.23 in both). In each of the 21 maps on its own the dips fall at the
  same positions (5, 12, 18, 25 and 31) along both axes, with largest deviations of 0.18 to 0.31.
  Steps across a grid line are 15 to 25 % smaller than elsewhere, depending on the ink level.
- Every window here starts on the 32 px lattice, so every window carries the grid at the same
  phase. A 90 degree turn or a flip of such a window keeps it (the grid is the same along both
  axes and symmetric). Shuffle copies keep it inside each tile, but their seams lie on grid lines
  and put large steps there. IAAFT and strip copies lose the grid, and jittered windows move it.
- The single number `grid`, with no fitting, separated validation windows from their copies with
  AUC (real windows higher) 0.97 to 0.98 against IAAFT-20 and IAAFT-200 copies, 0.98 to 1.00
  against shuffle copies, 1.00 against tilejit windows, 0.98 against stripjit windows, 0.92
  against strip copies of text and 0.87 of blank, and exactly 0.50 against rot90 copies (text and
  blank windows alike). It also separates text from dense and from blank windows somewhat (see
  "Checks that can void or withhold").
- A logistic regression on the `texture` features, fitted on training blank windows against copies
  of blank windows only (it never saw text), separated validation text from its IAAFT, shuffle,
  strip, tilejit and stripjit copies at AUC 0.996 to 1.000, and from rot90 copies at 0.50.
- Removing the grid from the maps was tried two ways, on training and validation data only. A
  level-adaptive correction fitted per grid phase flattened the pooled step profile of three
  validation maps (largest deviation 0.03); no separation was measured after it. Corrections fitted
  on pairs of grid phases, measured on training segments, left the window step profiles uneven
  (largest deviation 0.05 for text windows and 0.16 to 0.19 for blank windows, against 0.23 and 0.26
  uncorrected), and a regression fitted on blank training windows against their copies still
  separated training text from IAAFT-20 copies at 0.94 to 0.99, from strip copies at 1.00 and from
  stripjit windows at 1.00, and blank from its IAAFT-20 copies at 0.88. Neither correction was shown
  to remove the cue, so none is applied.

The grid is therefore handled by the design rather than removed: `grid` is a preregistered
baseline, the artifact control measures how far such cues go on each null measure and on T4 and
T8, and the withhold rule decides what may be read as text structure.

## Deviations from the 7 October plan

| Item | 7 October | Now | Reason, and what had been seen |
| --- | --- | --- | --- |
| Test segments | 7, including w010-027 | 6 | w010-027 is kept out of this work; no test result existed |
| T2 null | plain phase randomisation | IAAFT, 200 iterations (plain phase kept as T2_plain) | a histogram alone separates plain phase copies (skew AUC 0.998 on validation); validation T2 of 1.000 against plain phase had been seen |
| T3 | text against shuffle (36 px in the addendum) | seam-matched tilejit text against shuffle (32 px); T3_raw kept | seams alone separate the copies; validation T3 of 1.000 had been seen; the code always used 32 px. Single seam numbers separate the seam-matched version too, so T3 cannot show arrangement (see "Nulls and seam-matched windows") |
| T5 | a test outside the scope of this document | dropped | not part of this test |
| Baseline | one private score | eleven public baselines with references and a comparison rule | the earlier baseline is not public |
| New measures | none | T7, T8, T2_20, C checks, Brier, FPR_dense, paired shares | T8 tests the stated use; T7 asks about structure within lines |
| Checkpoint | best validation mean | final checkpoint | selection on near-ceiling AUCs followed T1 |
| Choosing the configuration | mean of validation T1 to T4 | final monitor mean of T1, T2_20, T3, T4 and T8, runs within 0.002 going to fewer parameters | T1 and T4 sit near the ceiling and the labelling rule nearly solves them; T8 is the stated use |
| Windows | at least 99 % usable | at least 99 % core papyrus | the same rule as 7 October, worded as the code applies it |
| Training | phase nulls, synthetic text positives, 2000 steps | IAAFT-20, shuffle and rot90 nulls, seam-matched windows, no synthetic text, 6000 steps | synthetic text belonged to other work; the scaling curve of 7 October (training fraction and width) is not run |
| Augmentation | gain, offset, noise | gamma and per-window noise | the normalisation cancels gain and offset |
| Calibration | Platt on the validation mixture | Platt on a fixed weighted mixture; Brier added | ECE on an unweighted mixture depends on window counts |

## Reproducibility checks (reported, not voiding)

- The window files' SHA-256 from the run's own data build against
  `docs/strokenet-data-manifest.json`, built before the run.
- The validation evaluation arrays' SHA-256 (`evalsets_validation.json`) against a rebuild with
  `python3 scripts/strokenet/pipeline.py prep --work WORK --runs NEW_RUNS` on a second machine,
  when one is run (CPU FFT rounding may differ between machines; differences are reported). The
  run itself does not do this.
- The code and preregistration SHA-256 recorded by the run against this commit.

## Related work

- IAAFT surrogates: Schreiber and Schmitz 1996 (above) (Sourced fact).
- The maps themselves are the output of the organisers' ink-detection model named in the file
  names (Sourced fact: file names in the public listing).
- villa's `get_ink_metrics.py` is the closest published tool (Sourced fact: tutorial "Ink
  metrics", https://scrollprize.org/tutorial_spiral, last updated 16 September 2026, read 14
  October 2026; https://github.com/ScrollPrize/villa/pull/2044, merged by 12 October 2026). From
  the ink renders of a surface and the `scrollprize/ink-coverage-32um` model, trained on PHerc.
  Paris 4, it measures the total ink area, whether columns are coherent and about the expected
  width, and whether lines are locally coherent with about the expected pitch. It is not compared
  here: it needs its own model and renders, while this test scores windows of the organisers'
  ink maps.
- An unrelated model with the same name exists ("StrokeNet: A Neural Painting Environment",
  ICLR 2019); the two share nothing but the name.

## What will be published

With Chase's approval of the exact file list: the released weights with their Platt parameters,
blank threshold and validation reference values in their metadata; every measure above for every
model and baseline, with per-segment values of the AUC and paired measures and of FPR_blank, and
intervals for every measure of the released model and every comparison; this document; the code
and tests. Window
positions, score grids and evaluation arrays are not published. A pass is described as meeting
this bar on held-out tracings of one scroll from one ink model with rule-made labels, nothing more.
