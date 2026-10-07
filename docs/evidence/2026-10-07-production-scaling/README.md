# CPU scaling evidence, 7 October 2026

The [measurement log](../../logs/2026-10-07-production-scaling.md) describes scope, results and limitations. The comparison baseline is merged PR #24, `c43c41a59ac3793b9a653fa236165f6f6b9d47a4`.

- `geometry/`: fixed profiling and timing rules, candidate fixes, raw timings, output hashes, regression results and independent review of triangle-edge batching.
- `hp/`: exact high-pass label-filter reuse, two fixed input sizes, five alternating pairs per case, raw outputs, process memory and independent differential review.
- `rows/`: public input receipts, optional sparse area resizing, numerical differences, fixed crop/full-map measurements and bounded execution rules.
- `inference-layout/`: rejected channels-last CPU inference experiment, original plan, frozen harness and all paired aggregate results.
- `integration/`: combined repository checks and fresh CLI output comparisons.

Only small source, text and JSON artifacts are archived. Public CT arrays, meshes, prediction maps, label stores and weights remain outside Git. Input URLs and SHA-256 receipts identify those external files. The inference experiment uses the official villa engine; no model or inference engine is vendored.

Individual lane manifests preserve their original external workspace paths and source hashes. Benchmark scripts document the original cached-input layout and dependency versions; those paths are historical, not portable download locations. Recreate public inputs from their receipts before rerunning. Original rules, amendments and rejected candidates are retained rather than silently rewritten. Raw patch/profiler whitespace is preserved.

`SHA256SUMS` covers every other file in this directory. The adjacent `2026-10-07-production-scaling.provenance.json` binds this archive, integrated code, tests and final documentation. Prior archives and seals remain unchanged; their source/documentation hashes refer to their historical commits. Hashes establish integrity, not correctness, novelty or improved papyrus readability.
