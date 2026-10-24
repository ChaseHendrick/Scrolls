# Preregistration: our letter reader against Hell-Char ConvNeXt-V2 on fresh papyrus photographs (ICDAR 2023 test answers)

> [!NOTE]
> **Public copy** (24 October 2026) of a preregistration kept in the owner's workbench, frozen before the test read (sha256 of the full file there, outcome included: `4561ae045972c755b1a670a7e141305b1349c14bb3f7938733c03061f0094f2f`). This copy differs in five places, none in a rule: the sentence on who asked for the work; the fill commit's title and the freeze command's id, left out; the freeze command and the label check, named as the workbench's because neither is part of this repository's kit; and the path of `eval_set_a.py`, a script not published here. The code hashes below are of the files as frozen there. In this repository `icdar_train.py`, `greek_lm.py` and `icdar_h2h.py` are byte-identical to them. `icdar_read.py` differs in one import: since the read it takes two CTC helpers, unchanged, from `scripts/letters/ctc_letter.py` instead of `eval_set_a.py` (a study script not published here). This repository's `kit/letterread.py` and `realforms.py` are other versions than the frozen ones; they are used only by the O2 arm.

**Status: Draft** (written 24 October 2026, about 07:15 UTC, before any reader has read any box or line of the test part). It is frozen at the commit that fills the preregistration, which may change only the `<<...>>` placeholders below, line for line; the freeze is registered with the workbench's `kit freeze add --prereg docs/prereg/2026-10-24-letter-reader-icdar-h2h.md --commit FILL_COMMIT --from-prereg`. The owner asked for this work on 24 October 2026.

## Why this set

Every scroll-map letter set we had is spent (the 342-letter pool of 22 October, PHerc. 1667's S1 and S2, family D waits on placement nobody can do), and the workbench's check for new public label sets finds none (run 24 October, 06:20 UTC). The ICDAR 2023 Competition on Detection and Recognition of Greek Letters on Papyri published its test answers on Zenodo ([record 13825619](https://zenodo.org/records/13825619), 22 September 2024, CC BY-NC 4.0; Sourced fact): expert letter boxes on 37 photographs of Iliad papyri. None of our readers or Hell-Char's has ever been scored on them in this repository. These are photographs, Hell-Char's home ground, not scroll ink maps; a result here says which reader names papyrus letters better on unseen hands and collections, not which reads a Herculaneum scroll.

## Disclosure (what is already seen)

- **Test part (T).** Built model-free by `scripts/letters/icdar_h2h.py build` (boxes, labels and pixels only; no reader). Its counts are known: 30 photographs pass the ink gate, 8,479 letters in 28 texts, 516 scored lines with 7,462 letters. No reader has read any T crop. The agent who wrote this file has not opened any T image.
- **Mapping repair.** 2c.Answers numbers its annotations' `image_id` in another scheme than its `images` list. The build pairs the 37 annotation image ids, ascending, with the 37 `images` entries in list order: every group's box extents then fit its photograph (36 inside, one 9 px over). The ink gate (boxes darker than the same boxes moved half a line up and down, paired t at least 5) passes 30 of the 32 photographs in the zip, and passes 0 of 64 deliberately wrong pairings (largest t 4.13), so it can fail. 5 answer photographs are not in the zip. Found and fixed on 24 October before any read.
- **Overlap.** No T text shares a Trismegistos number with Hell-Char's 144 papyri, and no T text folder is in the ICDAR training part (`build.json`, `overlap`).
- **Dev part (D).** The ICDAR training part, built the same way (32,798 letters in 92 texts, 2,291 scored lines). It is used for every choice below, for both sides. No arm trains on it. letters-v2-real (not an arm) trained on these photographs.
- **R1 on D (Model output).** R1's input recipe was chosen on D: its own evaluate.py recipe ("plain": gray, `cv2.INTER_AREA` to 64 x 64, [0, 1], Normalize(0.5, 0.5)) errs 0.357; aspect-kept padding 0.394; the demo's inverted input 0.612. With the Greek letter prior added, plain errs 0.376, so R1 is read without it as H1's rival.
- **Language model.** A Kneser-Ney model of order 5 on 7,068,213 letters of 22 Perseus prose texts (`scripts/letters/greek_lm.py`, Perseus commit `0189b9c8`), with Homer, every poet, and every verse line, quotation, citation and note inside the prose left out. It scores the Iliad at 3.649 bits per letter, the Odyssey (never quoted into it either) at 3.627, and unseen prose (Aeschines 1) at 2.524 (Model output, 24 October): it has not learned the Iliad's text.

## Question and hypotheses

On the 8,479 T letters, given the expert box, does our reader name the letter better than Hell-Char ConvNeXt-V2? On T's 516 lines, does our reader read the line better?

- **H1 (primary).** Letter error over every T box: O5 against R1 as released (plain input, no prior).
- **H1b (secondary).** O5 against R1 read with the same prior and the same rule as O5 (R1p), so the classifier is compared and not only the prior.
- **H2 (primary for lines).** Character error rate over T's scored lines, boxes given: L5 (O5's posteriors decoded with the language model) against R1 box by box (L-R1, each box's top letter, concatenated).
- **H2b (secondary).** L5 against R1's posteriors decoded with the same language model at the weight that suits R1 best on D (L-R1lm), so the language model helps both sides as well as it can.
- **Reported, not decisive:** O2 (letters-v2-ccby, one-letter CTC) on boxes; O2 reading each line strip free, with no boxes (L-O2free, greedy CTC); every arm per text.

## Arms

| Arm | What | Pin |
| --- | --- | --- |
| O5 | Our classifier, `scripts/letters/icdar_train.py`: ConvNeXt from timm's ImageNet weights, trained on Hell-Char only (13,014 crops of 144 papyri, aeef8466), never on ICDAR or scroll data. Runs, ensemble, test-time scaling and prior weight as filled | three run folders, log-probabilities averaged (`work/letters/icdar-h2h/o5final/`): `cb128` (convnext_base, 128 px, seed 0), `cs128s0` and `cs128s1` (convnext_small, 128 px, seeds 0 and 1), each 40 epochs, sha256 in Code. D letter error 0.3010 against R1 plain 0.3571 (d -0.0561, 95% -0.0725 to -0.0364). Chosen on D among 11 runs of 24 October (alone 0.3161 to 0.3322): the runs of the two larger architectures; all 11 together gave 0.3027, and a greedy pick of 5 runs gave 0.2991 but was not taken, to avoid tuning to D; prior weight 0 (no prior: on D a weight of 0.25 erred 0.3065 and 0.5 erred 0.3057, both worse; so R1p equals R1 and H1b equals H1) on log P(letter) from the language model's unigram, minus log of the runs' training class shares; no test-time scaling (`tta` 0; scaling changed single runs by under 0.003 on D, in both directions) |
| R1 | Hell-Char ConvNeXt-V2 Tiny LF+DSCL, `pplatanou/greek-letter-convnextv2-jocch` at `355f1b1c`, plain input | sha256 `b30dfd2f22df66683e50ab660bba6673f20c6a1b503fd05dc30d87b818d4bec5`, config `d81d285b37b1f27b54abd1d2f5b08491c1a5631dc4c4bcf6840361ab41c43b60` |
| R1p | R1 plus the prior as O5 uses it (R1's training shares from Hell-Char's class counts) | as R1 |
| O2 | letters-v2-ccby step 26,000 | sha256 `b14988852fc721cce71e80a66db0a8ea99a1de914ef2b724ecc6e711baa9ed8c` |
| L5, L-R1lm | `greek_lm.decode_boxes` (beam 16), L5 with weight 0.5 (D character error 0.2449; 0.375 gave 0.2508, 0.625 0.2472, 0.75 0.2537), L-R1lm with weight 0.875 (D 0.2698; 0.5 gave 0.2799, 0.75 0.2708, 1.0 0.2712, 1.25 0.2788) (each its best on D) | language model sha256 `a8fa01f3b023ff5ba3fbe56dcabb0f15b6bee91321efa5576539ec6f9ff72c74` |

No arm is an ensemble with a released Hell-Char model. Choices for O5 and L5 are made on D only, and the fill commit lists each with its D score.

## Sets

- **T:** `work/letters/icdar-h2h/build/test/` from the zip with sha256 `f86b7aaf0697e82042a0d042d8626cfbd4d13ea9644cede5bc57edf2b7af3e97`: `letters.json` sha256 `871795707ac6ee757327d24f00ed41889b85ee41ed29a925416ff3c0bd334c51`, `lines.json` `3e8cb8419b02c4520c545702f160f2ea5742168789280040ed6dd5794774ca37`, crop manifest `9befff14e2c369f8d642d0165191a37ce2c61e19fa169e98a30caaa6e03f1f34`.
- **Line rule (fixed before any read):** boxes link when their vertical extents overlap by half the smaller height, centres sit within half the image's median box height, and the gap is at most one median height; a line is a component read left to right; a component with two horizontally stacked boxes is not scored; lines under 5 letters are not scored; a line is scored only if its reference lies within 20% edits of some stretch of the Perseus Iliad (5-letter anchors). The strip is the boxes' union padded 0.25 h left and right and 0.15 h above and below.
- **Units:** the text folder (28 in T). Every interval resamples units.

## Metric, intervals and decision rule

- **Letter error:** wrong boxes over boxes; the reference is the expert label mapped to the 24 capitals (lunate sigma as Σ).
- **Character error rate:** edit distance of the read string to the reference, summed over a unit's lines, over the reference letters.
- **Intervals:** 20,000 bootstrap resamples of units, seed 0 (`icdar_read.paired`); d = ours minus rival.
- **Decision:** ahead if the 95% upper bound is below 0; behind if the lower bound is above 0; level if the whole interval lies within -0.05 to +0.05; otherwise not resolved.
- **What may be written:** "ahead of Hell-Char ConvNeXt-V2 on fresh papyrus photographs (ICDAR 2023 test answers, N letters)" only if H1 is ahead and O5 and R1 pass every control below. "Reads papyrus lines better than Hell-Char ConvNeXt-V2 letter by letter" only if H2 is ahead and its controls pass. Each sentence names the set, N, that the boxes were given, and that these are photographs, not scroll ink maps. Every other outcome is reported as it comes.

## Controls (each can fail)

1. **C1, chance:** each arm's accuracy above a permutation null (2,000 permutations of the references within units, seed 0, one-sided p < 0.05).
2. **C2, decoys:** each box crop cut into a 4 x 4 grid and its tiles shuffled (`numpy.random.default_rng(index in letters.json)`); real minus decoy accuracy, paired 95% lower bound above 0, for O5 and R1.
3. **C6, prior alone:** the prior's own answer (its commonest letter for every box) is scored; O5 must beat it by a paired lower bound above 0.
4. **C7, language model alone (lines):** each line read from the language model with no image (the best string of the line's length under beam 16); L5 must beat it by a paired lower bound above 0.

If O5 fails a control, H1 is invalid. If R1 fails one, H1 is reported with the failure named and the "ahead" sentence may not be written. The same holds for L5 and H2.

## VOID and INCOMPLETE

VOID: an input hash differs at read time; a T crop, label or line changes after any read; any arm reads T before the fill commit; a read comes from code that is not the fill commit or a descendant that leaves the listed code unchanged; any choice is made on T.

INCOMPLETE: R1's plain input errs more than 0.50 on D at read time (it did 0.357), or a code path cannot run as written (then stop before any T read, and amend).

## Code (hashed at the fill commit)

Code, then inputs (weights, the language model, the fill JSON for `icdar_read.py score --fill`, and the test part). `test_guard` checks every line before a test read.

- `scripts/letters/icdar_read.py` sha256 `35b703f709c884ced331880893d09bc43a043fc2081ad6c8b7889b557b81c48f`
- `scripts/letters/icdar_train.py` sha256 `3cc4efaec71498acb95a2172b1f62f53ae3dabba40045a59190f496488b2f8db`
- `scripts/letters/greek_lm.py` sha256 `445213393af6327cf0cc52c9da651c25524bdd44560c53e4648d50e19d55f353`
- `scripts/letters/icdar_h2h.py` sha256 `b5ae5650081425dbc448d8012a551b2f49e50f6113e103a51523fed34639ab46`
- `eval_set_a.py` (a study script of the workbench, not published here; its two CTC helpers are `scripts/letters/ctc_letter.py`) sha256 `c759af5503681bd53da45595820521142d5d3d1acf6f7dee5b571d35f2bc2efb`
- `scripts/letters/realforms.py` sha256 `972c161ac07091a48c1fa2a237595fb7ac0f4baea992132a56695abce327bafb`
- `kit/letterread.py` sha256 `ef4ae4a92f1223cdcc41fff62cc43ae44a821eff514bc8413316128fc429ad67`
- `work/letters/icdar-h2h/o5final/cb128/model.pt` sha256 `6f30048298e21dd86306e7d2f59c73870e87f7fc215229dcc5cc68d5f5e62150`
- `work/letters/icdar-h2h/o5final/cb128/config.json` sha256 `6d01e2dae944a957a2d60c1f7e0d493d9b41e37f45eb390bdb4ab5d29e8d3ace`
- `work/letters/icdar-h2h/o5final/cs128s0/model.pt` sha256 `0b81ce1ed27205de5e869f44a945f2bc7ffbdc4279110beb6b11bc35c2ff134a`
- `work/letters/icdar-h2h/o5final/cs128s0/config.json` sha256 `4b53a47acca43cabbbcc93ff0439a39cd5d7ca08c55c75a2452d1bfc41731254`
- `work/letters/icdar-h2h/o5final/cs128s1/model.pt` sha256 `804670af8355bf4c9991c1a7976fb22aa02cb2c7ea0a2405e08d25d6f04f4647`
- `work/letters/icdar-h2h/o5final/cs128s1/config.json` sha256 `fca2e364ff36e49c7964f3cb7f6a27e111023b46f8b8a394eca26c8143d5372b`
- `work/letters/icdar-h2h/lm5.json.gz` sha256 `a8fa01f3b023ff5ba3fbe56dcabb0f15b6bee91321efa5576539ec6f9ff72c74`
- `work/letters/icdar-h2h/fill.json` sha256 `7e56ae1ec7848e4c7bfd0983f587a548ff8ef420faa4bdd71abb76390240ff68`
- `work/letters/icdar-h2h/rivals/best_convnextv2_tiny_lf_dscl.pth` sha256 `b30dfd2f22df66683e50ab660bba6673f20c6a1b503fd05dc30d87b818d4bec5`
- `work/letters/icdar-h2h/rivals/demo_config.json` sha256 `d81d285b37b1f27b54abd1d2f5b08491c1a5631dc4c4bcf6840361ab41c43b60`
- `work/letters/icdar-h2h/rivals/letters-v2-ccby-step026000.npz` sha256 `b14988852fc721cce71e80a66db0a8ea99a1de914ef2b724ecc6e711baa9ed8c`
- `work/letters/icdar-h2h/build/test/letters.json` sha256 `871795707ac6ee757327d24f00ed41889b85ee41ed29a925416ff3c0bd334c51`
- `work/letters/icdar-h2h/build/test/lines.json` sha256 `3e8cb8419b02c4520c545702f160f2ea5742168789280040ed6dd5794774ca37`
- `work/letters/icdar-h2h/build/test/crops.sha256` sha256 `9befff14e2c369f8d642d0165191a37ce2c61e19fa169e98a30caaa6e03f1f34`

## Order of the run

1. This commit (draft); D development; the fill commit; the freeze.
2. `icdar_read.py post --part test` for O5, R1, O2 (guarded: clean tree, filled file, matching code hashes), then `icdar_read.py score`, once.
3. The outcome is appended below, under "Outcome", with the score file's hash.

## Outcome (appended 24 October 2026, about 09:20 UTC; nothing above changed)

Read once, 08:41 to 09:17 UTC, on a cloud CPU from commit `f1108c7f` (the fill commit `e3925301` plus the freeze registration; every listed hash matched, `test_guard` passed at each step). Score file [`score.json`](../evidence/2026-10-24-letter-icdar-h2h/score.json), sha256 `713ee5e4f55cd61696dbc9ed917f55ec519f99178532ee846493ea9e1e53c3f1`; log [`run.log`](../evidence/2026-10-24-letter-icdar-h2h/run.log). Model output on public papyrus photographs; references are the ICDAR experts' boxes and labels. 8,479 boxes and 516 lines in 28 texts.

| Arm | Letter error (95%) | Line character error (95%) |
| --- | --- | --- |
| O5 / L5 (ours) | 0.291 (0.260 to 0.328) | 0.241 (0.212 to 0.277) |
| R1 / L-R1 (Hell-Char ConvNeXt-V2, as released) | 0.340 (0.314 to 0.370) | 0.320 (0.295 to 0.349) |
| L-R1lm (R1 with our language model at its own best weight) | | 0.252 (0.229 to 0.281) |
| O2 (letters-v2-ccby, one letter) / L-O2free (no boxes) | 0.449 (0.412 to 0.489) | 0.547 (0.505 to 0.588) |
| C7 language model alone | | 0.869 |

- **H1: ahead.** O5 minus R1 -0.049 (95% -0.061 to -0.035). O5 has the lower error on 24 of the 28 texts, R1 on 3.
- **H1b: ahead,** identical to H1 because the fill set the prior to 0.
- **H2: ahead.** L5 minus L-R1 -0.079 (-0.096 to -0.061).
- **H2b: level.** L5 minus L-R1lm -0.011 (-0.025 to +0.003), inside -0.05 to +0.05: with the same language model, R1's reads are about as good on lines.
- **Controls: all pass.** C1 (p 0.0005 for every arm), C2 decoys (real minus decoy accuracy: O5 +0.571, lower bound 0.534; R1 +0.526, 0.497), C6 prior alone (+0.606, 0.567), C7 language model alone (+0.628, 0.594).

The sentences allowed by the rule: **"ahead of Hell-Char ConvNeXt-V2 on fresh papyrus photographs (ICDAR 2023 test answers, 8,479 letters, boxes given; photographs, not scroll ink maps)"** and **"reads papyrus lines better than Hell-Char ConvNeXt-V2 letter by letter (516 lines, boxes given)"**. Not allowed: that our line reading beats Hell-Char with the same language model (H2b is level), or anything about Herculaneum ink maps. The ICDAR 2023 test answers are now spent.
