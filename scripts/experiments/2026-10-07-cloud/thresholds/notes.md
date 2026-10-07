# `thresholds` job (2026-10-07, CPU cloud container)

Lead (c) of [`../README.md`](../README.md), extending section 1 of [`docs/logs/2026-10-07-novel-checks.md`](../../../../docs/logs/2026-10-07-novel-checks.md). Every map below is model output (`ink_9um` seed 42, step 75,000), not a reading. Public labelled data only.

## Scope change

At 11:12 UTC the coordinating session cut the budget to about 1.5 hours: w045 dropped (PHerc0841's three segments only), parts 1 and 3 first. So ag896 and ag405 skipped the SMOKE run of `scripts/mac-w045.sh` and only fetched their surface volume and labels with the same `kit fetch` calls (`fetch.sh`); w00 ran the full SMOKE setup. w045 rows from the earlier log are not recomputed here.

## Review corrections and historical records

`results.json`, `part2_w00.json` and `part3_w00.json` remain the original job records, byte for byte. The tables below describe those historical runs. The corrected script has not been rerun on scroll maps, and no corrected candidate counts are claimed here. Save future reruns under a new tag, for example `python analyze.py part2 --segments 0841-w00 --tag corrected`; do not replace the archived JSON files with new results.

Part 1 had never run. Its calibration unit is now an independent sheet: w00 and ag896 trace one sheet, so both are calibrated only on ag405. ag405 is calibrated only on w00, the primary trace fixed here before any part 1 result, rather than choosing a trace by its score or pooling both traces. The `loo` output key is retained, with explicit sheet and primary-trace metadata. This is a design correction before execution; it does not retrospectively establish a preregistration or supply a new result. Report two sheets, with the second trace as a sensitivity check, rather than three independent held-out examples. The integer threshold report now uses the actual float32 uint8/255 grid, avoiding a ceiling error at exact bin boundaries.

Candidate overlap counts also need careful labels. Historical `ink_frac` and `mostly_on_ink` divide supervised ink pixels by the entire component area. Pixels outside supervision are unknown, so these quantities are not precision or false-positive rates. Future outputs retain those fields and add `sup_frac`, supervised ink/background and unknown pixel counts, and `known_label_precision` (supervised ink / all supervised pixels, or null when there are no supervised pixels). Per-candidate evidence and summary coverage accompany the counts. Sparse supervision can give high known-label precision without assessing most of a component.

The historical TAUIL tiler tested complete sites only. On w00 it considered the 3,843 x 3,204 px interior, 61.3% of the 4,220 x 4,760 px canvas, dropping the bottom and right remainder strips before the valid-area filter. The omitted fraction of the valid papyrus surface cannot be recovered from the saved summaries alone. Future runs include every nonoverlapping boundary footprint, zero-pad to the nominal 12 x 15 mm size, and mark padding invalid. The 5% valid-site floor uses the nominal padded area; erosion and scores use the same padded masks. Coverage output separately reports tested and skipped canvas pixels and valid-surface pixels. Boundary-site scores and counts may change; they have not been computed on w00 here.

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
| [TAUIL-Abd-Elilah/pherc0826-first-letters-search](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search) | `7a6b453c9f4355b97575ee6367db4a51fea9c44c` | `search/read_sheets.py` (`best2mm`, map rescale), `search/band_score.py`, `search/dense_review.py` (`slab_fraction`, one-sidedness, `rank_score`), `search/row_period.py`, README ("strong sites (>= 0.5)") | maps rescaled `clip((q - 0.25) / 0.5)`; historical run used complete 12 x 15 mm sites only, dropping remainder strips, then skipped sites with < 5 % valid; per site and face: best 2 mm window share of pixels > 0.5 (valid eroded 48 px), band score, slab fraction, one-sidedness, rank score; "strong" = best_2mm >= 0.5. Future boundary policy and coverage are described above. Also `row_period` line fraction on the whole segment |

Not automated, and why:

- **bnleft:** the verdict sentence is written by a person (Bryant) after looking; the prereg's "tile seam" boundary is not in their code (only the map frame is), so only the frame is used here.
- **nerln:** the final rule (G0.md 19:07) gives no automatic verdict; the verdict is a blind visual reading of shuffled panels. The prereg's border band "from every surface hole" is not in `reproduce.py` (frame only), so only the frame is used here.
- **millerandmuller:** the stroke-shape, fibre-direction and "row-annotatable" criteria of their prereg are visual; only the mechanical pass is automated in their own code.
- **TAUIL:** the decision is "the top 15 and every strong, one-sided, non-slab site were checked by eye", then neighbouring-winding, context and line-pitch controls on the leads; "one-sided" and "non-slab" have no fixed numbers. Here "one-sided" is read as one_sided > 0 and "non-slab" as slab < 0.5 (my choice, labelled). Their readers were Reader v2 + d9v2 (ensemble) and v8in, not `ink_9um`; their sites are sheets rendered along the normal, not team segments. The neighbour and context controls need the m7 sheet prediction and new renders: not automatable on these maps. `band_score.py` hard-codes v8in's 8.64 um pixel; kept as published.

## Status: stopped early, w00 only

The user ran out of usage time at about 11:50 UTC, while ag896 was mid-inference. So only PHerc0841 w00 has whole-segment maps. **Part 1 (leave-one-sheet-out threshold) needs the missing segments and was not computed.** Parts 2 and 3 have w00 only. All scripts are resumable: `bash infer.sh` (it skips w00), then `analyze.py part1`, `part2`, `part3`, with a new output tag for corrected reruns.

Pipeline check: the w00 rerun matches the 2026-10-07 log exactly (14.0 cm2 of map; median forward value on labelled ink 0.431; 2.3 % of ink and 0.001 % of background at or above 0.7843; 13 forward candidates, 3 mostly on labelled ink, 4 reverse). Whole-segment AUC 0.748 as stored, 0.501 reversed.

### Part 2: community rules on w00, where text is known to be present (Model output)

| Rule | Forward candidates | Of them mostly on labelled ink | Reverse candidates | What the rule says |
| --- | ---: | ---: | ---: | --- |
| millerandmuller, T = 0.7843, 8-conn, >= 0.5 mm | 13 (0.93 per cm2) | 3 | 4 | full mechanical pass (both directions) 2, neither mostly on labelled ink |
| bnleft, T = 199, 4-conn, >= 53 px, band and coverage exclusions | 14 (1.0 per cm2) | 4 | 1 | candidates for a person to judge |
| nerln, T = 128, area >= 12,000 px, 64 px border, reverse at matched lit fraction (115) | 35 (2.5 per cm2) | 6 | 26 (10 at an absolute 128) | forward exceeds reverse: not null by their 18:48 count rule |
| TAUIL, 12 x 15 mm sites, strong = best 2 mm window >= 0.5 | 1 of 6 sites | the strong site has labelled ink | 0 of 6 | one strong, one-sided, non-slab site: would go to visual review |

TAUIL's `row_period` line fraction on the whole w00 map, with z along rows (the axis the human labels pick: labels 0.798 there, 0.287 the other way): forward 0.295, reverse 0.406. Their calibration says text gives 0.49 to 0.74 (on Reader v2 and d9v2 maps); `ink_9um` seed 42 on w00 sits at their null (0.30 to 0.39), and the reverse map scores higher than the forward one.

Interpretation: on w00 every automatable rule flags something in the forward map, and nerln's and millerandmuller's rules also flag the reverse map (26 and 4 candidates). Only a minority of forward candidates sit mostly on labelled ink (3 of 13, 4 of 14, 6 of 35). This measures overlap with known labels, not the share of false positives: unlabelled regions remain unassessed. The TAUIL count applies to its historical tested interior, not the complete map. The line-pitch tool ranks this reader's reverse map above the forward map on this segment. One segment only; not yet a pattern.

### Part 3: how much surface the row score needs, w00 (Model output)

200 random squares per size, seed 20261007, at least 80 % on the surface, the same windows forward and reverse.

| Window | Side (px) | Windows scored | Reverse p95 row score | Forward windows above it | Median row score fwd / rev | Median window AUC fwd / rev (windows with labels) |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 0.25 cm2 | 534 | 0 (band empty) | | | | 0.794 / 0.520 (43) |
| 0.5 cm2 | 755 | 199 | 6.5 | 4.5 % | 3.2 / 2.9 | 0.726 / 0.500 (76) |
| 1 cm2 | 1068 | 200 | 9.7 | 4.0 % | 4.5 / 4.5 | 0.724 / 0.506 (100) |
| 2 cm2 | 1510 | 200 | 11.2 | 10.0 % | 6.0 / 5.9 | 0.719 / 0.489 (114) |
| 4 cm2 | 2135 | 200 | 14.6 | 6.0 % | 7.7 / 9.4 | 0.720 / 0.478 (152) |

Interpretation: row score does not consistently rank the forward map above its reverse control under this sampling rule. The forward share above the reverse p95 is 4% to 10%, and is not monotonic with area. These descriptive counts do not establish equivalence, a chance-level significance result, or a smallest useful surface area. The 0.25 cm2 windows yield no row score because of the implementation's size/band requirements; that is not a biological null.

A paired recalculation from the unchanged `part3_w00.json` restricts both metrics to windows where AUC exists (at least 100 supervised ink pixels and 100 supervised background pixels inside the valid mask) and both row scores exist:

| Window | Paired labelled windows | Forward AUC > reverse AUC | Forward row score > reverse row score | Median row score forward / reverse |
| --- | ---: | ---: | ---: | --- |
| 2 cm2 | 114 | 111 (97.4%) | 52 (45.6%) | 5.45 / 5.8 |
| 4 cm2 | 152 | 152 (100%) | 58 (38.2%) | 7.45 / 10.3 |

This stratification shows metric discordance even among windows containing supervised pixels. AUC uses those pixels only, while row score uses the broader valid window; the minimum label-count filter does not ensure labels fill the window. Per-window label counts and supervision fractions were not saved, so their medians cannot be reconstructed here. Windows overlap on one surface and are not independent trials; row scores were saved to one decimal. There is no significance or general minimum-area claim. The conclusion is limited to this reader, surface, sampling rule and score implementation.

`part2_w00.json` and `part3_w00.json` hold every number, with per-site and per-window rows; `results.json` has the summary rows.

Small regression checks, without downloading or inferring maps: `python -m unittest discover -s scripts/experiments/2026-10-07-cloud/thresholds -p 'test_*.py' -v` from the repository root. They exercise independent-sheet calibration, exact uint8 threshold reporting, boundary coverage and padding, unknown-label semantics through three candidate rules, and the paired counts above from the saved records.
