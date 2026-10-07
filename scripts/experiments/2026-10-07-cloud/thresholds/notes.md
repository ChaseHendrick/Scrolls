# `thresholds` job (2026-10-07, CPU cloud container)

Lead (c) of [`../README.md`](../README.md), extending section 1 of [`docs/logs/2026-10-07-novel-checks.md`](../../../../docs/logs/2026-10-07-novel-checks.md). Every map below is model output (`ink_9um` seed 42, step 75,000), not a reading. Public labelled data only.

## Scope change

At 11:12 UTC the coordinating session cut the budget to about 1.5 hours: w045 dropped (PHerc0841's three segments only), parts 1 and 3 first. So ag896 and ag405 skipped the SMOKE run of `scripts/mac-w045.sh` and only fetched their surface volume and labels with the same `kit fetch` calls (`fetch.sh`); w00 ran the full SMOKE setup. w045 rows from the earlier log are not recomputed here.

## What ran

| Step | Script | Notes |
| --- | --- | --- |
| Setup | `setup.sh` (SMOKE for w00), `fetch.sh` (ag896, ag405) | villa main plus PR #1865 (`6723ad158`), Python 3.14 venv |
| Inference | `infer.sh` | `vesuvius.ink_detection.inference.infer` on each whole surface volume, `--overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both`, CPU, one at a time |
| Analysis | `analyze.py part1|part2|part3` | reads maps and labels from `$WORK`; labels at level 2 mapped with `kit.auc.labels_on_map`; rows with `kit.rowscore.score_array` |

Timings: setup about 19 min (mostly the package install); w00 whole-segment inference 1380 s for both directions on 4 CPU cores (3,782 patches per direction); part 3 on w00 296 s; part 2 on w00 17 s.

## Community rules reimplemented (part 2)

Repositories shallow-cloned read-only into a separate folder on 2026-10-07; none of their code was run, the rules were rewritten in `analyze.py`.

| Repository | Commit | Rule source | Rule as reimplemented |
| --- | --- | --- | --- |
| [millerandmuller/first-light-pherc0826](https://github.com/millerandmuller/first-light-pherc0826) | `ee8eef11e57ce7b5bc84ae3cdf5692ca234fac7c` | `analysis/target-PHerc0826-window1-full-w010-065/analyze_target.py`; `prereg/readout.md` | map/255 >= 0.7843; 8-connected; bbox long side >= 0.5 mm / 9.362 um (53.41 px); forward, reverse, and "full mechanical pass" (pixels at or above in both directions) |
| [bnleft/first-light-pherc0211](https://github.com/bnleft/first-light-pherc0211) | `728a27234f50d239c6c83934dad6952b48b94b76` | `modal_app.py` (`READOUT_SCRIPT`, `readout`), `prereg/readout.md` (Deviation note 1: T = 199) | uint8 >= 199; 4-connected; bbox long side >= 53 px; drop components touching the map frame; drop bands (long >= 5 x short); drop components whose bbox centre lies where the surface volume's middle layer is > 50 % zero over a 129 px box; candidates per direction |
| [nerln/vesuvius-first-letters-pherc0800](https://github.com/nerln/vesuvius-first-letters-pherc0800) | `174542319b383e84a8b1dbe2092f46850592f99a` | `reproduce.py` (`candidates`), `G0.md` (22 Sep 18:48 rule change, 19:07 final rule), `PREREGISTRATION.md` | forward uint8 >= 128; reverse at the threshold that lights the same fraction of valid pixels; scipy default 4-connected; area >= 12,000 px; inside a 64 px border band; 50 % overlap with reverse candidates as a diagnostic; their 18:48 comparison: null unless forward candidates outnumber reverse |
| [TAUIL-Abd-Elilah/pherc0826-first-letters-search](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search) | `7a6b453c9f4355b97575ee6367db4a51fea9c44c` | `search/read_sheets.py` (`best2mm`, map rescale), `search/band_score.py`, `search/dense_review.py` (`slab_fraction`, one-sidedness, `rank_score`), `search/row_period.py`, README ("strong sites (>= 0.5)") | maps rescaled `clip((q - 0.25) / 0.5)`; whole map tiled into 12 x 15 mm sites (their site size), sites with < 5 % valid skipped; per site and face: best 2 mm window share of pixels > 0.5 (valid eroded 48 px), band score, slab fraction, one-sidedness, rank score; "strong" = best_2mm >= 0.5. Also `row_period` line fraction on the whole segment |

Not automated, and why:

- **bnleft:** the verdict sentence is written by a person (Bryant) after looking; the prereg's "tile seam" boundary is not in their code (only the map frame is), so only the frame is used here.
- **nerln:** the final rule (G0.md 19:07) gives no automatic verdict; the verdict is a blind visual reading of shuffled panels. The prereg's border band "from every surface hole" is not in `reproduce.py` (frame only), so only the frame is used here.
- **millerandmuller:** the stroke-shape, fibre-direction and "row-annotatable" criteria of their prereg are visual; only the mechanical pass is automated in their own code.
- **TAUIL:** the decision is "the top 15 and every strong, one-sided, non-slab site were checked by eye", then neighbouring-winding, context and line-pitch controls on the leads; "one-sided" and "non-slab" have no fixed numbers. Here "one-sided" is read as one_sided > 0 and "non-slab" as slab < 0.5 (my choice, labelled). Their readers were Reader v2 + d9v2 (ensemble) and v8in, not `ink_9um`; their sites are sheets rendered along the normal, not team segments. The neighbour and context controls need the m7 sheet prediction and new renders: not automatable on these maps. `band_score.py` hard-codes v8in's 8.64 um pixel; kept as published.

## Status: stopped early, w00 only

The user ran out of usage time at about 11:50 UTC, while ag896 was mid-inference. So only PHerc0841 w00 has whole-segment maps. **Part 1 (leave-one-out threshold) needs all three segments and was not computed.** Parts 2 and 3 have w00 only. All scripts are resumable: `bash infer.sh` (it skips w00), then `analyze.py part1`, `part2`, `part3`.

Pipeline check: the w00 rerun matches the 2026-10-07 log exactly (14.0 cm2 of map; median forward value on labelled ink 0.431; 2.3 % of ink and 0.001 % of background at or above 0.7843; 13 forward candidates, 3 mostly on labelled ink, 4 reverse). Whole-segment AUC 0.748 as stored, 0.501 reversed.

### Part 2: community rules on w00, where text is known to be present (Model output)

| Rule | Forward candidates | Of them mostly on labelled ink | Reverse candidates | What the rule says |
| --- | ---: | ---: | ---: | --- |
| millerandmuller, T = 0.7843, 8-conn, >= 0.5 mm | 13 (0.93 per cm2) | 3 | 4 | full mechanical pass (both directions) 2, neither on ink |
| bnleft, T = 199, 4-conn, >= 53 px, band and coverage exclusions | 14 (1.0 per cm2) | 4 | 1 | candidates for a person to judge |
| nerln, T = 128, area >= 12,000 px, 64 px border, reverse at matched lit fraction (115) | 35 (2.5 per cm2) | 6 | 26 (10 at an absolute 128) | forward exceeds reverse: not null by their 18:48 count rule |
| TAUIL, 12 x 15 mm sites, strong = best 2 mm window >= 0.5 | 1 of 6 sites | the strong site has labelled ink | 0 of 6 | one strong, one-sided, non-slab site: would go to visual review |

TAUIL's `row_period` line fraction on the whole w00 map, with z along rows (the axis the human labels pick: labels 0.798 there, 0.287 the other way): forward 0.295, reverse 0.406. Their calibration says text gives 0.49 to 0.74 (on Reader v2 and d9v2 maps); `ink_9um` seed 42 on w00 sits at their null (0.30 to 0.39), and the reverse map scores higher than the forward one.

Interpretation: on w00 every automatable rule flags something in the forward map, and nerln's and millerandmuller's rules also flag the reverse map (26 and 4 candidates). Only a minority of forward candidates sit mostly on labelled ink (3 of 13, 4 of 14, 6 of 35). The line-pitch tool fails on this reader and segment. One segment only; not yet a pattern.

### Part 3: how much surface the row score needs, w00 (Model output)

200 random squares per size, seed 20261007, at least 80 % on the surface, the same windows forward and reverse.

| Window | Side (px) | Windows scored | Reverse p95 row score | Forward windows above it | Median row score fwd / rev | Median window AUC fwd / rev (windows with labels) |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 0.25 cm2 | 534 | 0 (band empty) | | | | 0.794 / 0.520 (43) |
| 0.5 cm2 | 755 | 199 | 6.5 | 4.5 % | 3.2 / 2.9 | 0.726 / 0.500 (76) |
| 1 cm2 | 1068 | 200 | 9.7 | 4.0 % | 4.5 / 4.5 | 0.724 / 0.506 (100) |
| 2 cm2 | 1510 | 200 | 11.2 | 10.0 % | 6.0 / 5.9 | 0.719 / 0.489 (114) |
| 4 cm2 | 2135 | 200 | 14.6 | 6.0 % | 7.7 / 9.4 | 0.720 / 0.478 (152) |

Interpretation: on w00, `kit rowscore` cannot tell the `ink_9um` forward map from its reverse control at any window size up to 4 cm2. The share of forward windows above the reverse 95th percentile stays near the 5 % that chance gives. Pixel AUC separates the two directions on windows of every size. So on this segment and reader, a row-score null on less than 4 cm2 says nothing, and the smallest useful size, if there is one, is larger. Caveat: windows overlap (200 draws on 14 cm2), so they are not independent.

`part2_w00.json` and `part3_w00.json` hold every number, with per-site and per-window rows; `results.json` has the summary rows.

