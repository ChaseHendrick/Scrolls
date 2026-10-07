# Adaptive-resolution evidence, 7 October 2026

This archive preserves the completed, CPU-only geometry diagnostic on published
PHerc0841 traces. It contains frozen rules, scripts, results, logs, source receipts
and an independent review. It contains no geometry arrays, images, CT data, ink
maps, labels or weights. The official public geometry URLs and hashes are in
`ag405-download-receipt.json` and the frozen input records.

The original frozen primary diagnostic on ag896 **failed**: it retained 112/120
local correspondence queries, below the fixed 95% requirement. A separately
frozen ag405 follow-up retained 116/120 and passed its own endpoint. The w00
diagnostic also retained 116/120. All three traces showed approximately 52-54%
hypothetical primitive reduction before conformity and transition requirements.
These results do not establish production mesh safety, realized runtime savings,
ink preservation, decipherment or worldwide methodological novelty. Read the
preserved `report.md` and `independent-review/adaptive-independent-review.md` for
the controls, failed hypothesis and limitations.

## Archive integrity

Every copied file is byte-identical to its research source. `archive-origins.json`
lists source paths, byte counts and SHA256 values. The original research manifest
is preserved as `source-SHA256SUMS`; its original name was `SHA256SUMS`, and it
also lists raw geometry files that are deliberately absent from this archive.
The archived source verification report describes verification in the original
research workspace, where those raw files were present.

The new `SHA256SUMS` verifies all files in this archive except itself. From this
directory, run:

```bash
sha256sum -c SHA256SUMS
```

The original rules and scripts were frozen before their respective outcome
readouts, as recorded by the local research workflow. This archive and its new
manifest were assembled after execution. Local hashes establish artifact
integrity; they are not externally timestamped preregistration or independent
proof of when an experiment was planned. The original failed primary result is
preserved alongside the later follow-up.

## Reproduction paths and inputs

These are historical scripts as executed, not portable installation scripts.
They use absolute paths under `/workspace/scrolls-env/` and the frozen numerical
environment. The original audit expects w00 and ag896 geometry under
`/workspace/scrolls-env/geometry-validation/`. The ag405 follow-up expects an
`ag405.tifxyz` directory beside its script; that original directory was a symlink
to the downloaded geometry outside Git. Neither the symlink nor raw geometry is
included here. The independent review also references the original research
paths and writes its receipt outside the repository.

For reproduction elsewhere, work in a separate scratch directory, obtain the
public geometry inputs and verify them against the original hashes, then remap
the filesystem layout or use separately identified script copies. Do not rewrite
these archived rules, scripts or receipts to hide path changes. Record any
modified reproduction scripts, dependency versions, input hashes and results in
a new provenance record. The frozen `geometry_snapshot.py` provides the exact
closest-point helper used in these experiments, so later repository changes do
not silently alter the original audit.

`independent-review/` contains the read-only review script, its receipt, report
and three-file hash manifest. It independently reconstructed selection and
primitive counts, replayed all 360 local queries, checked 19 original artifacts
and 16 frozen input-hash entries, and tested additional interpolation samples.
It found no concrete defect within the explicitly limited diagnostic scope.
