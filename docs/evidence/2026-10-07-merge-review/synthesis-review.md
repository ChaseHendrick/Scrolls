# Grok synthesis merge review

Reviewed PR #11 at `84a9ef20f0e0a02f87b7b4c76bc8372a36181e45` (`origin/grok/laneA-pr-synthesis`) and PR #12 at `487540845054573a650e3cb1d1c7b7c6c28da8b5` (`origin/grok/laneB-label-free`) against `origin/main` at `9af26f66c9f0314e48613550d41aa6d5c6d163ba`. The original heads need the corrections below before merge. Prepared replacements are confined to isolated `git archive` exports; no shared checkout, branch, commit or push was changed.

## PR #11 findings and repair

1. Original `synth.py:16-19,49,109-111` uses whole-segment marginal bootstrap intervals for a different team map to classify bare-crop AUC differences. Original notes `17,23,37-50` turn this into clear, marginal, within-noise, replication and null conclusions. Those conclusions are unsupported even though the heuristic is disclosed. The corrected generator emits descriptive differences without an uncertainty verdict; notes invalidate the historical heuristic and retain the observed point values. Actual paired crop-map resampling is still missing.
2. Original notes `23-27,33-42` risk attributing crop differences to trace or reader effects and recommending a target-run policy from six label-chosen transfers on one sheet. These are two traces of the same sheet, with different physical scoring patches, and the 24 variants and 276 pairs are dependent. Corrected notes state those limits and make no broad novelty or generalization claim.
3. Original `synth.py:11-14,85,111` reads mutable branch tips and drops corrected control-status metadata. Replacement inputs are exact commits. Historical stride-42-forward/stride-64-reverse controls remain provisional in both descriptive comparison and control rows. No inference rerun was performed.

The original arithmetic reproduces, including Kendall tau-a 0.5507246377, 214 concordant and 62 discordant pairs. Original `synth.json` and `synth.out` remain byte-identical; their old inferential labels are invalidated by the corrected note, not silently rewritten. The old output has pre-existing trailing spaces, retained to preserve its bytes.

Replacement tree: `/workspace/scrolls-env/pr-merge-review/laneA-fixed`.

Changed relative files only:

- `docs/logs/2026-10-07-grok-laneA.md`
- `scripts/experiments/2026-10-07-grok-laneA/synth.py`
- `tests/test_grok_synthesis.py` (new)

Five focused tests pass: small differences cannot become null/equivalence claims, large differences cannot become significance claims, mismatched control status propagates, historical output aliases are refused, and source reads bind immutable commits. Corrected synthesis ran on committed scalar records only, yielding six transfer cases, 14 descriptive comparisons and three provisional control records.

## PR #12 findings and repair

1. Original `laneb.py:9-24` differentiates through invalid mesh coordinates and rejects only the center node. A flat-plane synthetic example with one `-1` hole gives finite false normals and areas 7.16 to 9.01 at valid neighbors whose true area is 1. Replacement geometry functions reject every incomplete differential stencil and canvas edge conservatively, including valid zero-valued coordinate components. Bend features inherit unsupported normal cells.
2. Original `checks.py:47-49,76-81,127-138` treats unknown label values or clipped supervision boundaries as image/background for orientation, high-pass and stroke widths. A uniform known-ink patch surrounded by unknown cells creates strong artificial boundary gradients/coherence. Replacement filters require fully known composed support; high-pass label statistics report their actual supported cohort. Stroke widths are censored when unknown edges could determine the distance or ridge. This is conservative loss of coverage, not inferred negative labels.
3. Original `checks.py:33` silently selects an arbitrary glob entry, and empty/constant cohorts in `laneb.py:59-67,118-125` and several readouts crash or emit nonstandard JSON NaN. Replacement analysis refuses multiple ink TIFFs, records the selected map path/hash, reports conditional positive-map versus geometric surface coverage, and encodes unavailable results as JSON null. Empty descriptor cohorts and nulls are unavailable, not evidence against or for ink.

Replacement tree: `/workspace/scrolls-env/pr-merge-review/laneB-fixed`.

Changed relative files only:

- `scripts/experiments/2026-10-07-grok-laneB/checks.py`
- `scripts/experiments/2026-10-07-grok-laneB/laneb.py`
- `tests/test_laneb.py`
- `docs/logs/2026-10-07-grok-laneB.md` (new)

Sixteen focused tests pass: seven original helper tests and nine regressions for hole stencils, unknown-boundary orientation, unknown-value high-pass invariance, censored versus known-background widths, degenerate autocorrelation/correlation strict JSON and Python 3.10 compatible streamed file digests. The original flat-plane test now checks its supported interior and requires boundary abstention. Both scripts compile. No real-data descriptor run or new download was performed, and PR #12 contains no archived metric artifact to alter.

## Remaining limits

These repairs make the additions suitable to merge as descriptive research and exploratory helpers. They do not establish a useful ink detector, a validated correction filter or groundbreaking novelty. Proportional mesh/map resampling is approximate, descriptor populations are conditional on map-positive coverage, and cyclic spatial perturbations are dependent null checks. Future claims need fixed recipes, actual supported labels, matched controls and independent patches or sheets. The lane C notes were inspected only for related context and are not included in this PR repair.

Validation and exact changed-file hashes: `/workspace/scrolls-env/pr-merge-review/synthesis-fix-validation.json`. Parent must copy only the listed files into the appropriate PR branch and run the integrated repository checks before merging.
