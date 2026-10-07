# PHerc0841's segments overlap; raw CT brightness alone; community update (2026-10-07, afternoon)

Research notes. Labels per [`../NOVELTY.md`](../NOVELTY.md). Public labelled data only (PHerc0841, PHerc0139 w045); no target scroll. Scripts and outputs: [`scripts/experiments/2026-10-07-cloud/baseline/`](../../scripts/experiments/2026-10-07-cloud/baseline/). CPU, this session's container.

## 1. w00 and ag896 are the same papyrus, traced twice (Sourced fact: the published meshes and labels; numbers below)

The three labelled PHerc0841 segments come with their meshes (`mesh/<id>-on-20250821151531-9.366um.tifxyz`, a 1/20 grid of the surface in volume voxels). Upsampled to a 47 um grid, each mesh point's distance to the nearest point of another trace (`segment_overlap.py`, output in `segment_overlap.txt`):

| From, to | Area | Median gap | Within 5 vox | Within 12 vox | Within 25 vox |
| --- | ---: | ---: | ---: | ---: | ---: |
| w00 to ag896 | 12.7 cm² | 8.6 vox (81 um) | 17 % | 75 % | 98 % |
| ag896 to w00 | 12.8 cm² | 8.6 vox | 17 % | 75 % | 98 % |
| w00 to ag405 | 12.7 cm² | 38.7 vox | 1 % | 5 % | 21 % |
| ag896 to ag405 | 12.8 cm² | 47.6 vox | 0.5 % | 2 % | 11 % |

Where w00 and ag896 run within 12 voxels and both are labelled (5,096 points, 0.11 cm²), their human ink labels agree with Dice 0.83. Matching w00's points to ag896 points displaced 1 to 3 mm in the surface plane instead gives Dice 0.25 on average (200 draws, 99th percentile 0.69, maximum 0.69). The scoring crops of `scripts/mac-w045.sh` sit on different patches of that shared sheet: 99 % of w00's crop lies within 12 voxels of ag896, but none of it falls inside ag896's crop.

**Interpretation.** w00 and ag896 are two traces of one sheet (or of layers close enough that their labels show the same text), about 80 um apart; ag405 is a different surface. PHerc0841 therefore gives two independent labelled surfaces, not three. A mean over the three segments weights the w00/ag896 sheet twice, and a leave-one-segment-out split between w00 and ag896 trains on the test sheet. This settles a disagreement in the community: Bullo27's [v8in-12gb](https://github.com/Bullo27/v8in-12gb) describes them as different windings about 12 voxels apart; SirColton's [pherc0841-9um-letter-test](https://github.com/SirColton/pherc0841-9um-letter-test) says ag896 "carries w00's text" (Community reports, found by the 2026-10-07 scan below). Nobody had measured it. A side result: on the same sheet, `ink_9um` scores 0.806 on w00's crop and 0.659 on ag896's crop, so the crop (and perhaps the trace depth) moves AUC by 0.15 within one sheet.

## 2. Raw CT brightness alone carries almost no ink signal on PHerc0841 (Model-free measurement)

Pixel AUC of each of the 28 surface-volume layers as is, against the human labels inside the supervision mask (`raw_baseline.py`, outputs `raw_0841-*.json`); crop with a 64 px edge left out, and whole segment:

| Segment | Layer AUC range, crop | Layer AUC range, whole | After a 48 um high-pass, whole | Depth max, whole | Depth std, whole |
| --- | --- | --- | --- | ---: | ---: |
| w00 | 0.449 to 0.549 | 0.489 to 0.525 | 0.496 to 0.501 | 0.514 | 0.494 |
| ag896 | 0.432 to 0.583 | 0.472 to 0.539 | 0.495 to 0.503 | 0.548 | 0.511 |
| ag405 | 0.464 to 0.530 | 0.495 to 0.543 | 0.496 to 0.503 | 0.565 | 0.557 |

The layer that separates best is chosen with the labels, so these ranges are an upper bound for any single layer. **Interpretation.** Brightness at any one depth, or its plain depth statistics, reaches at most 0.58 on a crop and 0.57 on a whole segment, and nothing at letter scale; the readers' 0.66 to 0.93 on the same crops comes from learned 3D texture. It also bounds the brightness share in the depth-shuffle control (novel-checks log, section 3): `ink_9um` on shuffled ag405 reads 0.563, its soup 0.607, both above the best raw statistic on that crop (0.537 for depth std), so the readers find some depth-order-free texture beyond brightness there. Analogues on other data: per-depth AUC at most 0.55 on Paris 4 w00 ([khj1222](https://github.com/khj1222/vesuvius-challenge)) and at most 0.56 on single fragment layers ([kartoun](https://github.com/kartoun/vesuvius-fragment-ink-depth), 2026-10-05) (Community reports). Not found for PHerc0841. w045's run ran out of memory here and was not redone.

## 4. An ink reading survives a trace offset of about 50 um, not 100 um (Model output: the team's maps; no labels involved)

The team publishes its own 2.4 um ink map for each PHerc0841 segment (`ink-detection/...new_canon_autoresearch_recipe-tile256-stride128.tif`). Because w00 and ag896 trace one sheet at gaps that vary from 0 to about 30 voxels, they are a natural experiment: the same papyrus, read by the same model, from two surfaces a known distance apart. Pearson correlation of the two maps at matched 3D points (47 um grid), by gap, against matches displaced 1 to 3 mm in the surface plane (`trace_and_noise.py`, output `trace_and_noise.txt`):

| Gap between the traces | Area | Correlation | Displaced null, mean (max of 50) |
| --- | ---: | ---: | --- |
| 0 to 28 um | 0.68 cm² | **0.86** | 0.04 (0.29) |
| 28 to 56 um | 2.49 cm² | **0.75** | 0.06 (0.19) |
| 56 to 84 um | 3.56 cm² | 0.45 | 0.05 (0.16) |
| 84 to 112 um | 2.70 cm² | 0.26 | 0.04 (0.14) |
| 112 to 169 um | 2.25 cm² | 0.07 | 0.04 (0.17) |
| 169 to 281 um | 0.68 cm² | 0.10 | 0.06 (0.22) |

Both maps keep the same contrast at every gap (standard deviation 53 to 69 of 255) and w00's labelled ink share there is 20 to 31 % for every gap above 28 um, so the drop is not a lack of text. **Interpretation.** Two readings of one sheet agree well only while the surfaces are within about 50 um (five 9.4 um voxels) of each other; at about 110 um they are unrelated. A traced surface that sits a tenth of a millimetre off the ink layer reads something else. This puts a number on how precise a hand-fixed surface has to be, and on how much an automatic surface may wander before a null from it means nothing. Nearest published work: [Ahggggg/page-that-isnt-flat](https://github.com/Ahggggg/page-that-isnt-flat) (offset tolerance of the 2.4 um model by shifting one surface) and villa #1867 (window shifts); a comparison of two independent traces of the same sheet was not found.

## 5. The PHerc0841 benchmark is 3.4 cm² of labelled papyrus, and its AUCs carry about +-0.01 to +-0.04 of sampling noise

| Segment | Surface | Supervised (labelled) | Labelled ink | Share labelled |
| --- | ---: | ---: | ---: | ---: |
| w00 | 12.7 cm² | 1.41 cm² | 0.31 cm² | 11 % |
| ag896 (same sheet as w00) | 12.8 cm² | 0.86 cm² | 0.28 cm² | 7 % |
| ag405 | 12.0 cm² | 1.12 cm² | 0.25 cm² | 9 % |

Every unseen-scroll AUC quoted for PHerc0841 rests on 3.4 cm² of labelled papyrus (0.84 cm² of it ink), less than the single 4 cm² area a First Letters claim needs, and on two independent surfaces (section 1). A block bootstrap over 1 mm blocks (300 draws) of the team's map against the labels gives AUC 0.971 (95 % interval 0.962 to 0.979) on w00, 0.921 (0.896 to 0.941) on ag896 and 0.869 (0.829 to 0.905) on ag405 (the labels may have been drawn with this map's help, so the levels are not a fair score; the interval widths are the point). **Interpretation.** On one segment, AUC differences below about 0.02 (w00) to 0.04 (ag405) are within sampling noise for a strong map, and weaker maps spread more. Many published rankings on PHerc0841 differ by less than that, and our own Gate A rule (0.02) sits at the noise floor. Not found reported for PHerc0841 by anyone.

## 6. Collation: two traces as two copies of one text (from decipherment practice)

In decipherment, a passage that survives in two independent copies is checked by collation: what both copies share is real, what one alone shows is noise or a copying error. Two traces of one sheet are two copies. `collation.py` (output `collation.txt`) compares, at matched points of w00 and ag896, the team's ink maps against raw CT averaged over a thin slab (5 layers, about 47 um) and a thick slab (21 layers, about 200 um, closer to an ink model's input), plain and with a 48 um high-pass (letter scale). "Reappears" is the share of points in the top 20 % of one trace's map that are also in the top 20 % of the other's (chance 0.20):

| Gap | Ink maps r | Thick CT r | Thick CT, letter scale r | Ink spot reappears | CT-texture spot reappears |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0 to 28 um | 0.86 | 0.83 | 0.51 | 0.70 | 0.50 |
| 28 to 56 um | 0.75 | 0.75 | 0.39 | 0.65 | 0.41 |
| 56 to 84 um | 0.45 | 0.64 | 0.30 | 0.47 | 0.36 |
| 84 to 112 um | 0.26 | 0.53 | 0.23 | 0.38 | 0.32 |
| 112 to 169 um | 0.08 | 0.42 | 0.14 | 0.31 | 0.28 |

**Interpretation.** (a) At gaps beyond about 80 um the thick-slab CT of the two traces still correlates 0.4 to 0.5, so they see the same papyrus; the ink reading is what is lost, faster than the papyrus structure. This sharpens section 4: depth precision matters for ink, not for finding the sheet. (b) Within about 60 um, the ink maps agree well beyond the letter-scale CT texture (0.86 against 0.51; a strong ink spot reappears 70 % of the time against 50 % for a strong texture spot). So collation carries ink-specific information, but reappearance alone is weak evidence, since texture reappears half the time. **As a test:** on overlapping automatic meshes of a target scroll, a candidate that does not reappear on a second trace lying within about 50 um is probably noise; one that does is still to be judged by eye. Labels are not needed, so it works where no labels exist. A cross-trace comparison of ink maps was not found in the community work read on 2026-10-07 (Untested idea as a target-scroll test; measured only on PHerc0841).

## 3. What the community published that changes our claims (scan of 2026-10-07; Community reports)

- **v8in on PHerc0841 is published.** Bullo27, [v8in-12gb](https://github.com/Bullo27/v8in-12gb) (commits 2026-10-01 and 02): v8in, no fine-tune, labels' bounding box, AUC (reverse) w00 0.837 (0.562), ag896 0.807 (0.618), ag405 0.810 (0.586); `ink_9um` mean of 14 checkpoints 0.813, 0.756, 0.761. v8in leads `ink_9um` there, the opposite of our w045 result (README finding 1, still unpublished elsewhere). Not there: a shuffle control, w045, and the PHerc1447 fine-tune on PHerc0841 ("was not scored on PHerc0841"). Our Mac and cloud v8in runs on PHerc0841 are therefore reproductions; the fine-tune runs are not.
- **Depth windows (README finding 4) have prior work.** [villa #1867](https://github.com/ScrollPrize/villa/issues/1867) (2026-09-22): on PHerc0841, shifting `ink_9um`'s window by up to 4 pooled planes moves AUC by at most 0.023, far less than the 0.085 on our crops (whole segment against crop: not yet reconciled). [#1907](https://github.com/ScrollPrize/villa/issues/1907): the best shift differs by segment. [PR #1946](https://github.com/ScrollPrize/villa/pull/1946) (2026-10-02): window averages, seed averages and mirror TTA did not beat the better single centred run on three validation segments. [ArcheyChen](https://github.com/ArcheyChen/vesuvius-eligible-scouting) (2026-09-25): averaging Hecate over windows -1 to +1 raises AUC 0.887 to 0.902, PHerc0841 included, and survives a matched blur. [TAUIL cross-scan-ink-transfer](https://github.com/TAUIL-Abd-Elilah/cross-scan-ink-transfer): a label-free most-confident-of-5 depth pick comes within 0.007 of the label-chosen best at 2.4 um. What stays ours: the oracle comparison for `ink_9um`, its soup and d9v2 at 9 um on PHerc0841 crops.
- **Thresholds and null rules (README finding 3):** no leave-one-out calibration and no cross-application of null rules to known text was found; every published null calibrated on w035. SirColton ran a preregistered blind letter reading on PHerc0841 ag405 with phase-scrambled and depth-shuffled nulls (TAUIL's ft6k named 3 of 8 letters, `ink_9um` seed 43 none, the team's 2.4 um map 6 of 8). [lightsgoblack/ink-placebo-check](https://github.com/lightsgoblack/ink-placebo-check): 0 of 16 maps trip its text rule on blank PHerc1667 papyrus.
- **Row score by area:** [abundantjoe/orgsec-ink](https://github.com/abundantjoe/orgsec-ink) (2026-10-03): at 2 cm tiles only 1.8 % of PHerc0139 text tiles beat the 99th percentile of PHerc0268 non-text tiles. No forward-against-reverse sweep over area found.
- **Targets:** TAUIL's [pherc0826 repository](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search) (update 2026-10-04) read PHerc0358 (99 sites) and PHerc0813 (124 sites) with d9v2, no leads. Two of our three preregistered target scrolls; it bears on how our atlas run is read, not on the rule.
- **Other new items:** [nestorvfx datasets](https://huggingface.co/datasets/nestorvfx/vesuvius-ink256-pretrain-sheets) (unlabelled 21-layer sheets from 41 scans, 2026-10-05; and [vesuvius-ink-training](https://huggingface.co/datasets/nestorvfx/vesuvius-ink-training), 130.5 cm² labelled, object-level splits), useful for training idea 3; villa PRs [#1961](https://github.com/ScrollPrize/villa/pull/1961), [#1967](https://github.com/ScrollPrize/villa/pull/1967), [#1989](https://github.com/ScrollPrize/villa/pull/1989) (`--overlap` is the overlap, not the stride), [#1988](https://github.com/ScrollPrize/villa/pull/1988) (`vesuvius.predict` on Apple Silicon), [#1987](https://github.com/ScrollPrize/villa/pull/1987), [#1993](https://github.com/ScrollPrize/villa/pull/1993), [#1942](https://github.com/ScrollPrize/villa/pull/1942), [#1952](https://github.com/ScrollPrize/villa/pull/1952), [#1971](https://github.com/ScrollPrize/villa/pull/1971); issues [#1964](https://github.com/ScrollPrize/villa/issues/1964) (a PHerc1447 debug mesh among real segments), [#1963](https://github.com/ScrollPrize/villa/issues/1963) (an all-zero PHerc0814 surface volume); [Jashann TRACE](https://github.com/Jashann/vesuvius-scrolling) (`ink_9um` fine-tunes 0.837 to 0.868 on PHerc0841, but PHerc0841 chose the checkpoints). Prize deadlines unchanged ([prizes page](https://scrollprize.org/prizes)): Progress Prize 31 Oct 2026, 11:59pm Pacific.

## Dropped

A row score of the human labels alone was tried as a ceiling for `kit rowscore` on PHerc0841. The labelled areas are 0.5 to 1.4 cm², about the score's minimum size, so the number says more about the mask shape than about the text. Not reported.
