# Lane B: label-free checks of ink maps on PHerc0841 w00 and PHerc0139 w045 (2026-10-07)

Research notes. Labels per [`../NOVELTY.md`](../NOVELTY.md). Public labelled data only; no target scroll. Every number below comes from `scripts/experiments/2026-10-07-grok-laneB/results/*.json`, written by the commands in this log. An ink map is model output, not a reading.

## Review status: historical, preliminary observations

The tables and interpretations below are Grok's reported Mac run, retained as a historical account. This merge review checked the saved records and code; it did not independently rerun the maps. The run predates the mesh-hole and unknown-supervision corrections described below. The original frozen Python scripts and raw result files remain unchanged. Their original PR head is `c61427ede1f45fc925f95cc0d66d826a4b74b201`.

The historical "Novel", "Null" and artifact descriptions do not establish a validated label-free detector, causal identification of fibers or ink, or a calibrated target-surface gate. In particular, the displayed stroke-width comparison selects an area using the supervision mask: Otsu and the whole-surface width calculation use no labels, but the displayed in-supervision population is label-dependent. Its ordering has not been validated on an independent unlabeled surface. The corrected helper tests verify support rules, not these historical numerical findings.

`run_mac.sh` is now guarded against accidental prospective use. A deliberate historical replay requires `SCROLLS_RUN_HISTORICAL_LANEB=1`; this only acknowledges the old calculation, not its validity. Do not use the frozen scripts to produce new claimed evidence. The corrected `checks.py` map/control CLI port remains pending.

## What ran

- Maps (whole segment, 9 um grid, already on the user's Mac from earlier sessions): `ink_9um` seed 42 and 43, forward and reverse, on PHerc0841 w00 and PHerc0139 w045 (villa PR #1865, CPU). Also the team's own 2.4 um PHerc0841 w00 map (`ink-detection/...new_canon_autoresearch_recipe-tile256-stride128.tif`, 4x4 block mean), which has no reverse control.
- Data: surface volumes and 20260918 labels already in `~/scrolls-work/data`; the w00 9.366 um mesh (`mesh/20260220213127-on-20250821151531-9.366um.tifxyz`) and the team map fetched with `fetch_data.py` (bucket's global endpoint; about 25 MB for these two items).
- Scripts: `checks_run_2026-10-07.py` with `laneb_run_2026_10_07.py` (frozen copies of the scripts that produced `results/`), `run_mac.sh` (the exact runs; Apple M1 Pro, CPU, `nice -n 10`; about 5 minutes, peak memory 4.0 to 8.6 GB).
- Commands: `bash run_mac.sh` in `~/scrolls-work/laneB` (repo subset in `laneB/repo`, data links in `laneB/data`). It calls `python -m kit auc MAP --control MAP_reverse --labels L/inklabels.zarr --mask L/supervision.zarr --level 2 --bootstrap 300 --json` and `python checks.py DATA SEGMENT MAP --control MAP_reverse [--mesh MESH]`.

Every statistic is computed on the forward map and on its reverse-depth control, with the human labels as a reference only. Spatial nulls are 20 or 30 cyclic shifts of at least 2 mm in the surface plane (seed 20261007).

## 0. Pixel AUC with a block bootstrap (reproduction)

| Map | Whole-segment AUC | 95 % interval (1 mm blocks, 300 draws) | Reverse control |
| --- | ---: | --- | ---: |
| w00 `ink_9um` s42 | 0.748 | 0.697 to 0.795 | 0.501 |
| w00 `ink_9um` s43 | 0.772 | 0.728 to 0.809 | 0.599 |
| w045 `ink_9um` s42 | 0.872 | 0.833 to 0.909 | 0.443 |

(Model output; reproduction.) The s42 and s43 levels match the earlier whole-segment numbers in the community-scan log range (0.720 to 0.751 on PHerc0841, 0.872 on w045). The w00 intervals are wider (+-0.04 to +-0.05) than the team map's +-0.01 in the overlap log, section 5: weaker maps spread more, as that section predicted.

## 1. Stroke width of a label-free threshold separates forward from reverse (Novel as far as we found)

Each map is thresholded at its own Otsu value over the surface (no labels). Stroke width is twice the distance-transform value on the medial ridge of each component (`laneb.stroke_widths`, components of 20 px or more), in um. The label row is the same statistic on the human labels.

| Map | Area above Otsu | Width p25 / median / p75 inside supervision (um) | Dice with labels inside supervision |
| --- | ---: | --- | ---: |
| w00 labels (reference) | | 608 / 641 / 749 | |
| w00 team 2.4 um map | 12.9 % | 525 / 695 / 813 | 0.835 |
| w00 `ink_9um` s42, forward | 19.6 % | 19 / 27 / 136 | 0.485 |
| w00 `ink_9um` s42, reverse | 18.3 % | 19 / 19 / 56 | 0.197 |
| w045 labels (reference) | | 543 / 599 / 649 | |
| w045 `ink_9um` s42, forward | 17.1 % | 19 / 265 / 623 | 0.678 |
| w045 `ink_9um` s42, reverse | 12.3 % | 19 / 27 / 126 | 0.143 |

(Model output.) 19 um is one pixel: most ridge points of a weak map are speckle. **Interpretation.** Without any labels, the width distribution of the thresholded map orders the maps as the labels do: the team map (labelled AUC about 0.97) has label-like widths of 0.5 to 0.8 mm; `ink_9um` forward on the training scroll w045 reaches a median of 265 um; on the unseen scroll w00 only the upper quartile (136 um) rises above the reverse control (56 um). On both segments the reverse control stays at speckle widths, so the statistic can fail and does on the control. Caveats: the labels are filled letter shapes, so their "width" is a letter-body width, not a pen stroke; three maps on two segments is a small sample. As a label-free check on a target surface: a forward map whose stroke-width upper quartile does not exceed its reverse map's is behaving like the control. Not found in the community repositories read on 2026-10-07 (a parallel session covers wavelet band, CT noise, crackle, micro-relief, phase symmetry and line autocorrelation, not stroke width).

## 2. Map edges follow papyrus fibers slightly, in both depth directions (Novel; a texture leak, not ink)

The papyrus fiber direction is taken from a structure tensor (about 80 um window) of the thick-slab CT mean (layers 4 to 24), kept where its coherence is in the top half. On w00 its weighted angle histogram peaks at 0 and 90 degrees of the surface grid (18.7 % and 29.4 % of weight in the two 15-degree bins there), the two fiber layers of papyrus; w045 likewise (33.8 % and 27.6 %, with 13.3 % and 18.0 % in the neighbouring bins). For the strongest 20 % of map edges (coherence above 0.3), the share whose line direction lies within 15 degrees of the local fiber direction, against the same share after shifting the fiber field by at least 2 mm:

| Map, region | Share within 15 degrees | Shifted null mean (max) |
| --- | ---: | --- |
| w00 `ink_9um` s42 forward, whole | 0.216 | 0.184 (0.195) |
| w00 `ink_9um` s42 reverse, whole | 0.212 | 0.189 (0.202) |
| w00 team map, whole | 0.221 | 0.186 (0.202) |
| w00 labels, supervision | 0.188 | 0.172 (0.233) |
| w045 `ink_9um` s42 forward, whole | 0.230 | 0.205 (0.212) |
| w045 `ink_9um` s42 reverse, whole | 0.237 | 0.206 (0.216) |
| w045 labels, supervision | 0.130 | 0.149 (0.231) |

(Model output; measurement.) Every map's edges sit along the fibers 2 to 4 points more often than the shifted null allows, and the reverse control does so as much as the forward map; the human labels do not (inside the noise of their small area). **Interpretation.** A small share of what the readers mark as ink edges is papyrus fiber texture, and it does not depend on depth order, so it is not ink. It is small (about 3 points of edge share), so it does not explain the readers' AUC, but a candidate whose strokes run along the fiber grid deserves suspicion, and the reverse map catches this leak equally. Inside the supervision mask the forward excess is within noise.

## 3. Mesh geometry: no ink-specific link (Null, with one artifact)

Pearson r between the map and three mesh quantities on the w00 surface (normal direction against the scan axis, local stretch, and bending as change of the normal per mesh step), against 30 shifted nulls:

| Quantity | `ink_9um` forward r | Reverse r | Team map r | Null max abs (forward) |
| --- | ---: | ---: | ---: | ---: |
| Normal against scan axis | 0.020 | 0.003 | 0.047 | 0.092 |
| Stretch | 0.041 | 0.035 | 0.042 | 0.058 |
| Bending | -0.095 | -0.084 | -0.055 | 0.063 |
| Thick-slab CT brightness | 0.029 | 0.070 | -0.020 | 0.054 |

(Model output.) **Null** for normal direction and stretch. `ink_9um` reads slightly lower where the mesh bends, beyond the shifted null, but its reverse control does the same (-0.084), and the team map does not (within its null): a geometry artifact of the 9 um reader in both directions, not ink. The labels' own nulls are too wide (max abs 0.21 to 0.51 on 1.4 cm² of supervision) to say anything. Only w00 has a mesh here; w045's was not fetched.

## 4. Depth: the map's letter-scale pattern follows no single CT layer (Null)

Correlation of the 48 um high-pass of each map with the 48 um high-pass of each of the 28 raw layers, over the surface: every |r| is below 0.012 for every map, its control and the labels. The forward and reverse profiles of `ink_9um` are mirror images (peaks at layer 7 and layer 21 of 0 to 27, on both segments), which is only a check that the reverse map is the depth-flipped run. **Null:** letter-scale ink in these maps is not a copy of any one layer's letter-scale brightness, which agrees with the raw-baseline finding (overlap log, section 2) that brightness alone carries almost no ink.

### Corrections to the historical narrative

- The frozen width estimator reports twice the distance-transform radius. Its minimum reported width of about 19 um is a two-pixel diameter at 9.366 um, not the one-pixel width stated in section 1. The historical values are unchanged; these discrete ridge diameters are not direct pen-stroke measurements.
- The saved w045 label depth profile reaches `|r| = 0.0169`. The section 4 statement that every label value is below 0.012 is incorrect; all saved map/control profiles do stay below 0.012. The label profile also predates the unknown-label support correction.
- On a 28-plane stack indexed 0 to 27, index 7 reverses to 20, not 21. The recorded peaks at 7 and 21 do not demonstrate an exact mirrored profile or certify a correct depth-reversal pipeline. Filenames and weak layer correlations are not a substitute for verified layer provenance.
- Alignment with a CT structure-tensor field, agreement between forward and reverse, and a bending correlation suggest possible texture or geometry effects. They do not prove a feature is a papyrus fiber, establish that correlated signal is not ink, or isolate a causal reader artifact. Mesh-hole support and resampling limitations especially affect the geometry interpretation.
- The cyclic shifts are dependent exploratory controls with varying supported populations. The saved records contain no preregistered selection rule, independent validation split for these statistics, or calibrated false-positive rate. The proposed stroke-width ratio threshold is an untested idea, not a supported gate.
- The raw records identify map filenames and settings but do not provide complete input/checkpoint hashes or render transforms. Exact physical registration and numerical reproduction of this historical run therefore remain unverified. Retain the records; new verified runs must be reported separately rather than overwrite these tables.

## Support corrections merged after this run (prospective)

- Geometry differences require finite valid mesh coordinates throughout their stencil. Nodes next to holes and canvas boundaries are excluded conservatively; a valid center alone is insufficient. Bend estimates inherit the invalid normal support.
- Label orientation and high-pass features require known supervision throughout the composed filter support. Unknown labels are not treated as background. High-pass label statistics report their supported pixel count.
- Stroke widths near unknown annotation boundaries are excluded when the distance or nearby ridge decision can depend on that boundary. This can reduce coverage; it does not invent a width for an incomplete annotation.
- Empty or constant cohorts produce unavailable statistics, encoded as strict JSON `null`. They do not produce positive or negative evidence. Correlation/null support counts remain descriptive.
- The analysis requires one explicitly selected ink TIFF and records its filename and SHA-256. A folder containing multiple versions is refused instead of silently choosing the first file.
- Correlations condition on positive-map surface support. The output reports geometric surface and zero-map counts separately. This is not full-surface accuracy or a detection threshold; a zero prediction cannot be inferred to be background.

The 16 focused tests include the original seven helper checks and nine regressions for geometry holes, unknown label boundaries, known-background widths, degenerate cohorts and strict JSON. These corrections were written in parallel with the run above and are not in it: `results/*.json` come from the frozen `checks_run_2026-10-07.py` and `laneb_run_2026_10_07.py`. The label-reference rows (label widths, label fiber shares, label geometry r) and the in-supervision map widths are the ones most likely to move under the corrected support, so treat every number above as preliminary until `checks.py` is rerun on the same maps.

## Limits before any experiment

Proportional nearest resampling and 4x4 map reduction are exploratory approximations, not the certified continuous mesh correspondence used by `kit surfacefix`. Record and inspect source geometry, dimensions, metadata, full input hashes and any coordinate conversion before interpreting a run. The CT structure tensor is a local orientation descriptor, not proof that a feature is a papyrus fiber or ink stroke. Cyclic rolled-map controls are dependent descriptive perturbations, not independent negatives or a calibrated error rate.

Freeze a readout rule before a new experiment. A useful accuracy or correction claim needs matched reader controls, actual known ink/background labels, fixed populations, and an independent patch or sheet. These helper scripts establish none of those claims by themselves.

## Not done (next steps)

- Port the `MAP --control --mesh` arguments of the frozen script into the corrected `checks.py` (it still reads only the team map), then rerun every map above with it (and `laneb.py`, tested in `tests/test_laneb.py`) and replace the tables; the frozen run stays as the record.
- ag896 and ag405 (the box fetched their meshes and maps but could not finish; the Mac has only w00 and w045 volumes): rerun `checks.py` there to see whether the stroke-width ordering holds on the second independent PHerc0841 surface (ag405).
- d9v2 and v8in whole-segment maps: does the stroke-width upper quartile rank readers as AUC does?
- A preregistered threshold for the stroke-width check (for example: forward p75 at least twice the reverse p75) before it is used on any target map.
- w045 mesh for the geometry check.
- Spatial autocorrelation and letter-scale periodicity were dropped from this lane: a parallel session covers line autocorrelation.
