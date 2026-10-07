# Production speed evidence, 7 October 2026

This archive preserves selected frozen rules, amendments, source snapshots,
benchmark harnesses, timing results, profiles, reviews and test logs for two
exact-output CPU optimizations. It contains no raw geometry, arrays, reader maps,
CT chunks, labels, weights, corrected meshes or binary profiler dumps.

## What was measured

| Operation | Baseline median | Optimized median | Ratio of medians |
| --- | ---: | ---: | ---: |
| Schema 2 correction, fresh worker process | 5.2913 s | 2.5508 s | 2.0744x |
| Correction function including I/O, within worker | 5.1735 s | 2.4329 s | 2.1265x |
| Correction geometry stage | 4.5208 s | 1.8074 s | 2.5012x |
| Historical schema 1 correction process, unchanged control | 0.7533 s | 0.7542 s | 0.9989x |
| Fresh AUC CLI process | 0.37200 s | 0.29812 s | 1.2478x |
| AUC file operation with warm imports | 0.10637 s | 0.04063 s | 2.6177x |

Geometry used five alternating pairs per case, after a warmup per version.
Scoring used six alternating pairs. Both used one CPU and one-thread numerical
settings, public control data already cached locally, and a coordinated window
without competing heavy jobs. These are fresh Python processes with warm local
data; the operating-system page cache was not cleared. Cold process startup is
not cold disk or network I/O.

The geometry worker timer includes interpreter startup, imports, correction,
I/O, evidence serialization and exit. It calls the correction operation directly;
it does not benchmark CLI argument parsing. Inner function and geometry-only
timers have narrower scopes and must not replace the process result. Scoring's
CLI timer uses the actual CLI entrypoint in a fresh process. Its warmed function
timings exclude startup, imports and final JSON serialization, while retaining
file reads and scoring. Its worker wall time includes warmup and several
operations, so it is not CLI latency.

Returned and saved outputs matched the baseline exactly on the benchmarked
workloads. Geometry includes null/refusal controls and independent checks of
bounds, heap order, ties, budgets and ambiguity. Scoring preserves the fixed
quantization and bootstrap draws, with pixel-oracle tests and fallback paths.
The original six-test scoring freeze and later single-map test addendum are both
retained; measured production code did not change between them.
The initial six-test source was reconstructed from the append-only seven-test
file and verified against its original frozen SHA256; that restoration is noted
in `archive-origins.json` and does not represent a benchmark rerun.

These results measure correction with previously computed maps and scoring of a
cached crop. They do not measure CT acquisition/loading, rendering, inference,
flattening, a complete decipherment pipeline, ink quality or successful recovery.
The real correction case still accepted zero edits. No universal speedup or lower
peak memory claim follows. Read `geometry/report.md`,
`geometry/independent-review.md` and `scoring/scoring-review.md` for full scope.

## Contents and source provenance

- `geometry/` preserves both `_surface_geometry.py` versions, the optimized
  geometry test, profile and benchmark rules, the append-only process amendment,
  original and process harnesses, exact-parity results, timing results and reviews.
  The original in-process repeated harness is preserved but was not executed;
  its cold-process replacement was frozen before repeated timing.
- `scoring/` preserves both `auc.py` versions, optimization tests, rules,
  amendments, input/code freezes, profiles, complete comparative timing/output
  JSON, validation and the patch.
- `io-review/` preserves a diagnostic on cached input reads and existing TIFF
  export behavior. It does not represent a newly deployed reader optimization.
- `flatten-review/` preserves feasibility findings, source pins and the public
  study's source-lock/observation receipts. No flattening benchmark was run.
- `integration/` preserves the final 193-test repository run, 39 experiment
  regressions and an actual CLI parity check. That CLI check matches stdout and
  all five output files, including the same expected exit status of 1. It is a
  correctness check, not an additional timed benchmark. The prior-seal check verifies all 15 inputs bound by the previous review seal against historical commit e2fd0c0 or unchanged evidence directories.

`archive-origins.json` records original absolute paths, sizes and SHA256 values.
Copied artifacts preserve their original bytes, including space-only context lines in raw unified patches and the profiler output's final blank line. Whitespace checks on authored production changes exclude these frozen artifacts. Historical reports describe the
state at execution; later integration does not rewrite their statements.
The geometry source manifest is preserved as `geometry/source-SHA256SUMS`. It
lists 371 research artifacts and external inputs; only the selected text/source
subset is copied here. The I/O and flattening source manifests also refer to
omitted raw inputs or source-context files. Do not treat those source manifests
as lists of files fully contained in this archive.

## Integrity and reproduction

The new `SHA256SUMS` covers every file in this archive except itself. From this
directory:

```bash
sha256sum -c SHA256SUMS
```

This is a post-run archive. Local prebenchmark freezes and append-only amendments
record the workflow and allow integrity checks; they are not externally
timestamped preregistration or proof of planning time. Earlier archives and
their seals are preserved separately. Current repository documentation can be
updated without rewriting historical seal bytes; an old seal that binds an old
document snapshot is not proof that today's edited document matches that snapshot.

The scripts are historical, as-executed sources with absolute paths under
`/workspace/scrolls-env/`. Reproduction requires the pinned repository exports,
numerical dependencies and external public inputs named in their hash receipts.
The full repository exports and payloads are intentionally absent. Restore the
original layout in scratch space, or use explicitly identified script copies
with path remapping and a new provenance record. Do not edit archived rules or
scripts to conceal changes. Preserve the raw timing pairs and negative controls,
and distinguish repetition on new hardware from the measurements archived here.
