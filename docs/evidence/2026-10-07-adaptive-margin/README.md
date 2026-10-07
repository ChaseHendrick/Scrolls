# Adaptive margin follow-up evidence, 7 October 2026

This archive preserves a separately frozen follow-up to the failed 25-micrometer
adaptive-resolution study. It tests a tighter 9-micrometer representation budget
on public PHerc0841 geometry. It contains rules, scripts, results, logs and an
independent review, with no raw geometry, CT data, images, labels, reader outputs
or weights.

**The combined hypothesis fails.** Primary ag896 retains 120/120 baseline-eligible
local queries but saves only 15.56% of hypothetical primitives, below the fixed
20% target. Secondary w00 retains 118/118 eligible queries with two native
abstentions preserved, and saves 15.91%. Secondary ag405 retains 120/120 and saves
18.51%. The preceding experiment's failed primary result remains preserved in
the neighboring [adaptive-resolution archive](../2026-10-07-adaptive-resolution/README.md).

The 9-micrometer interpolation bound plus the 40-micrometer query offset ensures
existence of a coarse point within 49 micrometers in the digital geometry. It
does not certify correspondence uniqueness, sheet identity, global topology or
physical papyrus accuracy. Primitive counts precede transition and conformity
costs. No mesh was exported, and no production speedup or ink improvement was
measured. Read `report.md` and the independent review for full limitations.

The independent review clarifies one source-report phrase: the new query seeds
give a different, disjoint query set. Full retention here is not a paired causal
demonstration that every earlier failed query was repaired. Preserve both studies
and both failed combined hypotheses.

## Integrity and reproduction

All copied research and review files preserve their original bytes.
`archive-origins.json` records their source paths, byte counts and hashes. The
original source manifest is preserved as `source-SHA256SUMS`; it also covers
raw geometry reached through local read-only symlinks, which are deliberately
excluded from this archive. The independent review verified all 19 source
manifest entries and all 14 frozen input-hash entries before archival.

The new `SHA256SUMS` covers every archived file except itself. Verify it from
this directory with:

```bash
sha256sum -c SHA256SUMS
```

This archive and its manifest were assembled after the experiment. Original
local rules were frozen before their respective outcome readouts as recorded by
the workflow. Hashes establish artifact integrity, not externally timestamped
preregistration or independent proof of planning time.

Scripts are preserved as executed. They depend on the original numerical
environment and filesystem paths under `/workspace/scrolls-env/`. The experiment
script expects `ag896.tifxyz`, `w00.tifxyz` and `ag405.tifxyz` beside it; those
original symlinks pointed to public geometry cached outside Git. The input
hashes are in `rule.json`. Official ag405 download URLs are preserved in the
neighboring adaptive-resolution archive's `ag405-download-receipt.json`.

For reproduction elsewhere, use a separate scratch directory, obtain and
hash-check the external inputs, and remap paths or create separately identified
script copies. Record modified scripts, dependency versions and results in a
new provenance record. Do not edit these archived artifacts to conceal changes.
The frozen geometry snapshot prevents later repository edits from changing the
historical closest-point implementation silently.

`independent-review/` contains the read-only reproduction script, review receipt,
report and hash manifest. It reconstructs selection/counts independently, replays
all 360 local queries and adds interpolation checks. No concrete implementation
defect was found within the limited diagnostic scope.
