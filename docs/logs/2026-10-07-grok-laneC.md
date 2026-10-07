# 2026-10-07: lane C, gaps not yet tried, and two small model-free experiments

Research notes, not claims. Labels per [`../NOVELTY.md`](../NOVELTY.md). Public labelled data only (PHerc0139 w045, PHerc0841 w00); no target scroll was touched. Ink maps are model output, not readings.

## Readout rule (written before any experiment ran)

Experiment 1 (texture): a model-free feature counts as an ink signal at 9 um only if, on both w045 and PHerc0841 w00 crops (inner 64 px), its AUC is on the same side of 0.5, at least 0.05 from 0.5, and outside the range of 8 rolled-map nulls; for a depth-dependent feature it must also differ from its depth-shuffled version by at least 0.02 in the direction away from 0.5. Otherwise it is a null.

Experiment 2 (fusion): a feature's sign is chosen on w045 (seen scroll, held-out segment) and applied unchanged to w00 (unseen scroll). Fusion counts as a gain only if the rank fusion beats rank `ink_9um` alone on w00 by at least 0.01 AUC at a weight fixed in advance (0.25); the 0.1 and 0.5 weights are reported but do not decide. The noise floor on w00 is about +-0.008 (README finding 8), so a smaller gain is a null.

## Gap list, ranked by cost and chance of a real result

Searched 2026-10-07: scrollprize.org (prizes, winners, open problems, ink tutorial), Zenodo, Hugging Face cards, GitHub repositories found by web search. Discord was not readable from here; nothing below is a Discord report.

| Rank | Gap (Untested idea unless marked) | Why it is open | Cost | Chance |
| --- | --- | --- | --- | --- |
| 1 | Model-free volumetric texture (first-order, Laws, autocorrelation) at 9 um on PHerc0841 | Published only on PHerc. 172 by Korotetskyi and Haindl ([Zenodo 20766169](https://zenodo.org/records/20766169); 2D version [Zenodo 20671195](https://zenodo.org/records/20671195)); the repo listed it as untested | Minutes of CPU on data already on the Mac | Low to medium. **Run below: null** |
| 2 | Texture as a second signal fused with `ink_9um` | Same paper proposes it as a weak label or extra input; no fusion scored against labels found | Minutes | Low. **Run below: null** |
| 3 | DINO ink-prototype similarity at 9 um: cosine similarity of [dinovol](https://github.com/ScrollPrize/villa/tree/main/dinovol) tokens to a mean ink embedding, the guidance used for [ink_3d_dino_guided](https://huggingface.co/scrollprize/ink_3d_dino_guided) on Paris 4 at 2.4 um | No public test on a 9 um surface volume or on PHerc0841 found | Hours: checkpoint download, CPU or MPS inference on crops | Medium |
| 4 | Test-time normalisation adaptation (recompute norm statistics on the target scroll) for `ink_9um` | The [open problems page](https://scrollprize.org/2026_open_problems) names cross-scroll generalization the bottleneck; [khj1222](https://github.com/khj1222/vesuvius-challenge) lists unsupervised domain adaptation as planned, not done; v8in's `InstanceNorm3d` is a related design choice, not a test | An afternoon on the Mac | Medium |
| 5 | Disagreement between two readers as a false-positive filter, scored on PHerc0841 | [sciganec/subit-ink](https://github.com/sciganec/subit-ink) tested it only on depth offsets of Fragment 1 and says the cross-scroll test is the next step | Cheap once two maps exist (they do for w00) | Low to medium |
| 6 | Accuracy by sheet orientation (normal parallel to a volume axis) for ink, not surface | [Jinhojeong](https://github.com/Jinhojeong/vesuvius-surface-geometry-diagnostic) found surface AUC 0.90 oblique against 0.80 axis-aligned; not measured for ink | Cheap with meshes on hand | Low |

## Experiment results (model output, not readings)

Script: [`scripts/experiments/2026-10-07-grok-laneC/texture.py`](../../scripts/experiments/2026-10-07-grok-laneC/texture.py), raw numbers in [`results.json`](../../scripts/experiments/2026-10-07-grok-laneC/results.json). Run on the user's M1 Pro CPU (data already in `~/scrolls-work`), about 4 s per segment. Crops as in `mac-w045.sh`, inner 64 px (w045 46,757 ink px; w00 84,484). Sanity check: `ink_9um` seed 42 on the w00 window scores 0.8061, the repo's bar exactly. On w045 it scores 0.9199 here (inner 64 on the whole-segment map) against the repo's 0.9136 (crop without the margin).

Experiment 1, pixel AUC (depth-shuffled; range of 8 rolled nulls):

| Feature | w045 | w00 |
| --- | --- | --- |
| Local 3D std | 0.514 (0.511; 0.446 to 0.577) | 0.506 (0.519; 0.500 to 0.588) |
| Laws L5 depth x E5 plane | 0.446 (0.437; 0.457 to 0.588) | 0.608 (0.581; 0.511 to 0.567) |
| 3D gradient magnitude | 0.520 (0.491; 0.459 to 0.554) | 0.499 (0.519; 0.493 to 0.586) |
| Block lag-1 autocorrelation | 0.446 (0.436; 0.429 to 0.577) | 0.569 (0.560; 0.423 to 0.559) |
| Mean brightness (baseline) | 0.536 (0.473; 0.449 to 0.557) | 0.465 (0.477; 0.445 to 0.631) |

**Null** by the rule. No feature is on the same side of 0.5 on both segments with margin. The one strong number, Laws energy on w00 (0.608, above every rolled null), points the other way on w045 (0.446), and its depth-shuffled version keeps most of it (0.581), so it is not depth-ordered ink. Interpretation: at 9 um these texture statistics change sign between scrolls, so a training-free texture reader would need its polarity set per scroll, which is the label problem again. This is consistent with finding 6 (raw brightness carries almost no ink signal on PHerc0841) and extends it from brightness to texture.

Experiment 2, rank fusion with `ink_9um` (sign from w045; rank `ink_9um` alone: w045 0.9207, w00 0.8073):

| Feature | w00 at 0.1 | w00 at 0.25 (decides) | w00 at 0.5 |
| --- | --- | --- | --- |
| Local 3D std | 0.8065 | 0.7964 | 0.7275 |
| Laws | 0.7962 | 0.7637 | 0.6412 |
| Gradient | 0.8058 | 0.7942 | 0.7222 |
| Autocorrelation | 0.8018 | 0.7791 | 0.6719 |
| Brightness | 0.8006 | 0.7780 | 0.6847 |

**Null.** Every fusion is at or below `ink_9um` alone on both segments. Recorded: a first run of the fusion step had a ranking bug (2D argsort) and printed meaningless 0.5 and 0.8061 values; it was fixed and rerun; only the rerun is reported. Experiment 1 numbers were identical in both runs.

Novelty status: as far as these searches reach, nobody has published these texture descriptors scored against labels at 9 um or on PHerc0841, so this is a new null, not a new positive. It belongs in `docs/results.json` as a null once the user agrees.

## Prior-art check of the README findings

- **Finding 7 (ink reading survives about 50 um of surface offset): related prior work the repo missed.** [DomRusso2/sheetcheck](https://github.com/DomRusso2/sheetcheck) reports that surface placement does not predict ink contrast over 0 to 150 um offsets on PHerc1667 (r = -0.045, n = 554), with a stated caveat about its offset axis. [axiosdevs/herculaneum-scroll-tools](https://github.com/axiosdevs/herculaneum-scroll-tools) recovers planted ink at window offsets from -216 to +216 um. The [ink tutorial](https://scrollprize.org/tutorial5) says models tolerate small depth offsets thanks to window jitter and that larger ones throw them off. Our result (two real traces of one sheet, correlation falling to chance beyond about 112 um) is a different measurement and partly contradicts sheetcheck's null; the README should cite both and say so. (Community report; Sourced fact for the tutorial)
- **Finding 4 (window averaging):** the [ink tutorial](https://scrollprize.org/tutorial5) itself recommends averaging predictions over a few nearby windows when a checkpoint responds poorly, and pscamillo's August 2026 Progress Prize ["How many depth slices?"](https://scrollprize.org/winners) studied depth windows by training. Add both to the existing related-work note; the comparison with the label-chosen window remains ours.
- **Finding 6 (raw brightness):** no PHerc0841 analogue found; the open problems page states carbon ink gives little attenuation contrast, which is the expectation, not the measurement.
- Findings 1, 2, 3, 5, 8, 9: no prior art found in these searches.
