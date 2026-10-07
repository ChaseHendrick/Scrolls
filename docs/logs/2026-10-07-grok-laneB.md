# Lane B: exploratory label-free descriptors (2026-10-07)

This branch provides scripts and synthetic checks, not measured results or a validated false-positive detector. It runs no ink inference. Public PHerc0841 model maps remain model output, not readings. No target-scroll result is included.

The scripts compare an existing team ink map with geometry, CT orientation, autocorrelation and approximate stroke widths. The analysis requires labels as scientific reference data; that does not establish that these descriptors identify ink. w00 and ag896 belong to one sheet, and must not count as separate independent validation surfaces.

## Correctness corrections before merge

- Geometry differences require finite valid mesh coordinates throughout their stencil. Nodes next to holes and canvas boundaries are excluded conservatively; a valid center alone is insufficient. Bend estimates inherit the invalid normal support.
- Label orientation and high-pass features require known supervision throughout the composed filter support. Unknown labels are not treated as background. High-pass label statistics report their supported pixel count.
- Stroke widths near unknown annotation boundaries are excluded when the distance or nearby ridge decision can depend on that boundary. This can reduce coverage; it does not invent a width for an incomplete annotation.
- Empty or constant cohorts produce unavailable statistics, encoded as strict JSON `null`. They do not produce positive or negative evidence. Correlation/null support counts remain descriptive.
- The analysis requires one explicitly selected ink TIFF and records its filename and SHA-256. A folder containing multiple versions is refused instead of silently choosing the first file.
- Correlations condition on positive-map surface support. The output reports geometric surface and zero-map counts separately. This is not full-surface accuracy or a detection threshold; a zero prediction cannot be inferred to be background.

The 16 focused tests include the original seven helper checks and nine regressions for geometry holes, unknown label boundaries, known-background widths, degenerate cohorts and strict JSON. No real-data descriptor run was performed during this repair, and there are no archived numeric results to replace.

## Limits before any experiment

Proportional nearest resampling and 4x4 map reduction are exploratory approximations, not the certified continuous mesh correspondence used by `kit surfacefix`. Record and inspect source geometry, dimensions, metadata, full input hashes and any coordinate conversion before interpreting a run. The CT structure tensor is a local orientation descriptor, not proof that a feature is a papyrus fiber or ink stroke. Cyclic rolled-map controls are dependent descriptive perturbations, not independent negatives or a calibrated error rate.

Freeze a readout rule before a new experiment. A useful accuracy or correction claim needs matched reader controls, actual known ink/background labels, fixed populations, and an independent patch or sheet. These helper scripts establish none of those claims by themselves.
