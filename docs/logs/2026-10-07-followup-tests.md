# Further controlled tests, 7 October 2026

Prepared for Chase Hendrick. These are measurements on public control papyrus, software fixes and negative results. No new reading or worldwide novelty is established. Only existing cloud CPUs were used.

## A real surface-matching defect

The initial surfacefix implementation matched each native vertex to the nearest vertex of a separate trace. Native vertices are about 187 um apart at these settings. The resulting distance includes lateral grid misalignment, even when the continuous surfaces are close. A 50 um matching limit therefore rejected useful correspondence before any reader could be evaluated.

A new PHerc0841 w00 crop was selected using supervision and geometry, before reader outputs. Its canvas is rows 2720:3360, columns 2720:3360. The separate ag896 reference uses rows 3120:3760, columns 2680:3320. Inside the fixed 64 px boundary, the source has 83,199 supervised ink pixels and 178,931 supervised background pixels. Both fixed spatial halves have ample ink and background.

On this crop, the nearest native-vertex distance is at least 62.48 um and has median 103.11 um. The median tangential component, estimated using source normals, is 89.92 um. The old 50 um test admits no points. The new certified bilinear correspondence admits 479 native points under the same physical limit, with 444 also inside the reference raster and four regions meeting the geometric point-count requirement. Prediction coverage and controls can still reject these regions.

This fixes a sampling defect; it does not demonstrate successful surface repair. The earlier `kit overlap` measurements used a denser 47 um point grid, so these native-grid numbers must not be substituted into that historical study. Its distances also include sampling error and should not be interpreted as pure normal displacement.

## What changed in the correction software

New prepared manifests use schema 2. The implementation searches all potentially qualifying bilinear patches, bounds the true continuous distance, samples the original dense reference maps at fractional coordinates, and freezes correspondence before reading prediction maps. It refuses holes, folded patches, unresolved searches and ambiguous locations. A strict convexity certificate also guards against two equally close points inside a single curved patch. Failure to obtain a certificate means abstention, not proof that a surface is wrong.

The 50 um distance limit and correlation, gain and control requirements remain unchanged. Historical schema 1 manifests retain their previous behavior; replay reproduced the old real report exactly. Official rendering and reader inference remain in villa. The pinned renderer's position interpolation was checked against its source before declaring the new geometric convention.

Independent review caught three useful adversarial cases: false ambiguity near a shared patch edge, an unresolved competing patch inside the permitted radius, and two equal nearest points on one regular saddle. The final implementation passed 146 repository tests, including 35 surface geometry and correction tests. Synthetic recovery establishes software behavior; real accepted corrections require a separate combined-surface rerender and label audit.

## Supervised real correction result

The new crop completed four actual CT renders and twelve matched d9v2 maps: baseline, separate reference, minus one voxel and plus one voxel, each with forward, reverse and shuffle directions at stride 42. Independent published-CT comparisons checked the baseline and reference raster positions and depth order before inference. No candidate was chosen using human labels.

The frozen corrector accepted **zero corrections** and flagged 16 regions. Four regions were evaluable, with 444 covered native points split into 221 selection and 223 held-back points. Output coordinates, dtype, holes and metadata were preserved. Arbitrary coordinate tampering with recomputed file hashes was refused before output. All eight complete shifted-reference null searches also accepted zero corrections: 22 evaluable region cases and 16 candidate selection attempts in total. One null had no evaluable regions. These dependent, coverage-limited checks do not establish a false-positive rate.

Only after those decisions were recorded did the frozen scorer inspect the labels:

| Source geometry | Forward AUC | Interpretation |
| --- | ---: | --- |
| Baseline | 0.9211 | Reverse 0.5951, shuffle 0.6439; fixed supervised mask |
| Minus one voxel | 0.9086 | Descriptive candidate audit; not selected by labels |
| Plus one voxel | 0.9300 | Gain 0.00889, simultaneous paired interval [-0.00461, 0.02239] |

The plus-one gain is below the frozen 0.01 bar and its interval includes zero. It does not justify overriding the correction refusal. No combined rerender was required because no point changed. Baseline high-pass correlation was 0.03304, above the displaced-label null 0.00710 and both matched depth controls. That is evidence of label association on this crop, not readable text or successful geometry repair.

All 1,000 paired bootstrap draws were finite. The two spatial halves and common coverage were fixed in advance. Intervals are conditional sensitivity measures on one correlated, label-selected patch. Separate AUC and high-pass interval families do not form one joint 95% guarantee. See the [correction/null readout](../evidence/2026-10-07-followup/supervised-surfacefix/actual-validation-with-nulls.json) and [label audit](../evidence/2026-10-07-followup/supervised-surfacefix/label-audit-results.json).

## Reconstruction redundancy measured on held-back CT

A radial Fourier response learned from one 128-cubed PHerc0139 pag0/pag50 pair predicted a disjoint held-back cube with correlation 0.99724 and RMS error 2.717 uint8 units. This reduced RMS error by 55.75% relative to a brightness adjustment fitted on the same calibration cube. Identity, displacement and depth-shuffle controls passed; a subsequent fixed padding audit gave nearly identical results.

The operator did not transfer successfully to the original reconstruction. Its held-back normalized RMS was 0.7311; a separately fitted original-to-pag50 operator still had normalized RMS 0.4151. Both failed the frozen prediction bars. The recipes differ in phase processing, sharpening and conversion settings, so this does not isolate a Paganin effect.

Strong overall predictability does not establish whether the small residual contains useful ink signal. It does show why agreement between these two recipes cannot count as independent acquisition evidence. See the [complete report](../evidence/2026-10-07-followup/physics/report.md), [primary readout](../evidence/2026-10-07-followup/physics/result.json) and [supplement](../evidence/2026-10-07-followup/physics/supplement-result.json).

## Published-render and labelled reader checks

Independent comparisons against the official published CT surface stacks established the reader depth order without using ink labels. On the earlier PHerc0841 crop, the chosen order had correlation 0.99999826 and mean absolute error 0.00562 uint8 units. On w045 it had correlation 0.99999887 and mean absolute error 0.00316. Opposite depth orders failed both tests. Each comparison used 7,340,032 voxels after excluding the spatial boundary. See the [PHerc0841](../evidence/2026-10-07-followup/orientation-pherc0841/orientation-result.json) and [w045](../evidence/2026-10-07-followup/orientation-w045/orientation-result.json) readouts.

The fresh official w045 rerender produced d9v2 AUC 0.9255 forward, 0.3346 reversed and 0.5814 shuffled at matched stride 42. It used the same fixed 170,666 supervised pixels in every direction and counted zero predictions; none were present. Simultaneous paired block-bootstrap intervals for forward-minus-control AUC excluded zero: reverse [0.4331, 0.7486], shuffle [0.1863, 0.5018].

The fine-detail check failed: forward high-pass correlation was 0.0177, below reversed 0.0214 and the displaced-label null 0.0578. This supports pixel ranking in this setup, not improved detail or legibility. A separate run on the published stack gave AUC 0.9258 / 0.3356 / 0.5814; each corresponding prediction differed from the rerender result by at most one uint8 level. These are pipeline baselines, not improvements over an earlier reader. w045 is held out as a segment on a previously seen training scroll.

An independent settings audit verified both completed runs against all 18 required reader settings and output hashes. The original frozen evaluator checked agreement among folders but did not itself bind every setting to the rule. Its code and scores were preserved; the separate audit closes that verification gap for these runs. See the [audit](../evidence/2026-10-07-followup/w045-baseline/w045-baseline-reader-settings-audit.json) and [completion record](../evidence/2026-10-07-followup/w045-baseline/w045-completion-status.json).

## Fresh affine registration failed independently

The first subpixel estimator failed its algorithm controls before any fresh CT was collected. That failure and the replacement estimator are both retained. The replacement passed 34 fixed recovery and rejection checks, with maximum displacement error 0.05570 voxel and minimum continuous NCC 0.99765.

The real experiment then used eight nonplanar calibration sites and four untouched audit sites, with no point dropping or refitting after audit. It downloaded 214 new chunks, 428 MiB, and reused 28. The fitted affine matrices were well-conditioned, but four raw/gradient calibration comparisons and seven of sixteen held-back method/recipe checks exceeded the unchanged 0.5-voxel gate. Maximum audit residuals were 0.75410 voxel for pag0 and 0.77775 for pag50. No phase candidate was rendered or inferred.

Relative pag0-to-pag50 closure passed all eight checks, with maximum residual 0.06770 voxel. This cannot validate their absolute relationship to the original labelled surface. The failed original-to-phase test does not distinguish nonlinear distortion from reconstruction-dependent localization bias. [Full report](../evidence/2026-10-07-followup/affine-v3/report.md), [readout](../evidence/2026-10-07-followup/affine-v3/result.json), and [earlier estimator failure](../evidence/2026-10-07-followup/affine-v2/result.json).

The new controls also clarify the older translation pilot: an integer NCC maximum can shift by a voxel for a fractional displacement. Its reported two-voxel peak discrepancy, equivalent to 18.724 um, is a failed integer-grid test, not a precise measurement of physical distortion. All original readouts remain unchanged.

## Evidence integrity

Rules, code, source receipts and outcomes are hashed, including failed checks and their append-only amendments. The [evidence archive](../evidence/2026-10-07-followup/) contains public-control rules and readouts; raw CT, geometry, labels, weights and prediction arrays remain outside git. Local pre-run hashes bind the recorded rules. They do not by themselves establish an externally timestamped preregistration or the scientific validity of a result.
