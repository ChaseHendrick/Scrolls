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

TIMINGS

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

RESULTS
