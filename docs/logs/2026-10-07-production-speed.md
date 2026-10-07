# Measured CPU speedups with identical outputs

Recorded 7 October 2026. The user requested an implemented production speedup. Profiling selected continuous surface correction as the main target. The complete correction process on the cached public PHerc0841 test crop improved from **5.2913 to 2.5508 seconds median**, a **2.0744x speedup** and **51.79% less wall time**. Every report field, projection array and output-file hash remained identical in the comparison.

This is a measured improvement in an implemented operation. It uses already computed reader maps; it does not measure the runtime of CT reconstruction, rendering, model inference, flattening or a complete scroll-reading pipeline. No accuracy improvement or worldwide methodological novelty is claimed.

## What changed

The original certified geometry solver separately evaluated four children at every subdivision. The initial profile attributed 6.92 of 7.90 profiled seconds to geometry, including 29,595 calls to the cell-bound calculation. The new `_child_bounds` evaluates those four boxes in one NumPy batch, then applies their results in the original order. The scalar warp-norm calculation, triangle order, seed ties, heap updates, budget exhaustion, distance bounds and all ambiguity/refusal checks remain unchanged. No acceptance threshold or numerical precision was relaxed.

The second change speeds up `kit auc` block bootstrapping. A bounded counting pass replaces repeated block sorting for dense inputs, with the old path retained for sparse huge coordinate ranges. Integer histogram counts replace scattered updates. Globally empty score columns are omitted only when original and resampled populations pass an exact-float64 arithmetic bound; larger populations retain the old reduction layout. Quantization, random draws, scored pixels, ties and output fields remain unchanged for supported finite maps. Temporary memory remains proportional to pixel count; peak RSS was not measured. Malformed nonfinite maps can raise a different underlying NumPy exception, so identical invalid-input exception classes are not part of this claim.

An unsupported historical "14 times faster" statement was removed from the layer-export docstring. Export behavior did not change.

## Repeated real-data measurements

| Operation | Baseline median | Optimized median | Ratio of medians |
| --- | ---: | ---: | ---: |
| Complete schema 2 correction in a fresh process | 5.2913 s | 2.5508 s | 2.0744x |
| Geometry within that correction | 4.5208 s | 1.8074 s | 2.5012x |
| Legacy schema 1 process, unchanged control | 0.7533 s | 0.7542 s | 0.9989x |
| Fresh AUC CLI with paired 1,000-draw bootstrap | 372.00 ms | 298.12 ms | 1.25x |
| Warm AUC file operation, including reads | 106.37 ms | 40.63 ms | 2.62x |
| Warm sequential AUC, high-pass and row scoring | 298.55 ms | 235.21 ms | 1.27x |

The correction uses a 32x32 native mesh crop and twelve existing 640x640 d9v2 maps from the [supervised real validation](2026-10-07-followup-tests.md). It still accepts zero edits and flags 16 regions. Faster abstention is the expected result on this input; the optimization does not manufacture a successful repair. The legacy schema 1 case does not invoke the optimized geometry solver, and its neutral timing is retained.

For each correction case, a warmup per version preceded five alternating before/after pairs. Every timed run used a fresh Python process on one CPU with numerical libraries restricted to one thread; competing agent compute was paused. The outer timer includes interpreter startup, imports, mesh/map reads, hashing, correction, writes, evidence serialization and shutdown. Workers call the full production correction function directly, so this table does not claim a measurement of its CLI argument parser. A separate actual CLI check verifies identical stdout and every output-file hash, including the expected abstention exit status.

The AUC comparison used six alternating pairs on the fixed supervised w00 crop, forward/reverse maps, the same labels, inner edge 64, 107-pixel blocks and seed 20261007. Its fresh-process measurement invokes the actual CLI entry point and includes JSON serialization. Warm function timings exclude startup/imports. High-pass and row-score code remained unchanged; their small timing variations are preserved in the raw record. Local input files and OS caches were warm. These are bounded single-core measurements, not cold-storage or whole-volume benchmarks. The correction's per-pair speedups ranged from 1.9266x to 2.1731x; 2.07x is a median, not a guarantee for every run.

## Checks and evidence

- Geometry parity checks matched 640 random child bounds and 640 budgeted closest-quad calls before timing. Independent review matched another 480 bounds, 224 adversarial solver cases, 138 budget abstentions, all 2,082 heap events and 28 projection cases. Thresholds, holes, folds, remote rivals and nonunique saddles were included.
- All 24 main correction runs and both displaced-reference null runs matched reports, every projection array and all output-file hashes exactly. Both tangential candidates raised the same error and produced no output folder. No report fields were excluded from the comparison.
- All six AUC timing pairs matched every returned CLI/function field. Seven new regressions compare against direct sampled-pixel calculations, including tied scores, odd block boundaries, quantization, zero/inner policies, paired and unpaired cases, sparse huge keys and the arithmetic fallback.
- The integrated repository passed 193 tests. Experiment regressions remain a separate 39-test CI step; their integrated run is archived with the final checks.

The [evidence archive](../evidence/2026-10-07-production-speed/README.md) retains fixed rules, pre-timing amendments, code/input fingerprints, raw timings, reproduction scripts and independent reviews. Geometry's original rule SHA256 is `582429ecdb0ca0492697af3440a46158c9c8117d64c155d4cec49e2de5035829`; its cold-process timing amendment is `9dcd939d50a5583ad9cc4fa0a85f1d96c816b80704958bcc0012699846ea90b1`. The scoring rule SHA256 is `4592e4582849ffd60880758ba6d7341ccd82ccd97939de18ac6f543a0cad912a`. Hashes establish byte integrity, not an externally proven preregistration time or scientific validity. Historical evidence and seals remain unchanged at their original commits.

## Other candidates examined

Exact input preloading cut a reader-input primitive from 1.021 to 0.309 seconds, but saved only 0.71 seconds across three maps. It was not implemented as an inference optimization. Existing banded layer export was independently timed at 0.091 versus 0.281 seconds for per-layer fallback with identical pixels; that behavior was already deployed. Neither number is promoted into a new whole-pipeline speedup.

The [upstream support-mask result](2026-10-07-coarse-support-mask.md) remains a separate community measurement. This environment lacks its pinned Lasagna runtime and original spacing-5 working grids/tracks. Native spacing-20 PHerc0841 meshes cannot substitute for that Paris4 reproduction. The current change accelerates exact correspondence without introducing that coarsening tradeoff. No new scan payloads, target maps, model inference, GPU work or paid compute were needed.
