# Batched certified subdivision: 2.07x faster complete correction process

On the existing real PHerc0841 schema2 correction case, batching the four child-bound
evaluations reduced median cold full-process wall time from **5.2913 to 2.5508 seconds**:
**2.0744x faster**, or 51.79% less wall time. All returned and saved report fields,
projection arrays, corrected mesh values and output file hashes were exactly unchanged.
The frozen 1.5x complete-operation target passed.

| Case and timer | Before median seconds | After median seconds | Speedup |
| --- | ---: | ---: | ---: |
| Supervised schema2, cold process wall | 5.2913 | 2.5508 | 2.0744x |
| Supervised schema2, complete correct() including I/O | 5.1735 | 2.4329 | 2.1265x |
| Supervised schema2, geometry stage | 4.5208 | 1.8074 | 2.5012x |
| Earlier schema1, cold process wall control | 0.7533 | 0.7542 | 0.9989x |

Schema1 does not call continuous bilinear geometry, so its neutral performance is expected.
It was benchmarked unchanged; no manifest was upgraded to manufacture a faster case.

## Change and evidence

The initial actual full-correction cProfile measured 7.90 seconds, of which 6.92 seconds
were geometry. `_cell_bounds` accounted for 29,595 calls and 6.75 seconds cumulative;
`_triangle_closest` accounted for 4.53 seconds. These are profiled times with profiling
overhead, not the performance headline. The profile supported optimizing child subdivision
instead of the comparatively negligible AABB pruning loop.

`_child_bounds` evaluates four children in one NumPy batch. It preserves their original
order, triangle order, first-minimum seed ties and the scalar three-coordinate warp norm
arithmetic. `closest_quad` still processes each result sequentially, updating the best
upper bound, heap serial values, child pruning and budget behavior in the same order.
Physical radius, distance bounds, convergence tolerance, strict-convexity uniqueness,
remote-rival and ambiguity rules are unchanged. No precision or correctness bar was lowered.

Ready production files are listed with baseline/candidate hashes in `ready-files.json`;
`geometry-speed.patch` contains the implementation and focused regression test. The
candidate geometry helper hash is
`4590aacfcefbac089abfc31ed03e7dd3ff3ec2f704e4c7047b716df03bfc0baa`, versus baseline
`75457b1629e914480cca0be63847f9fc3b004cc5e0c3635a86dde7b42aaae393`.
No repository source was edited by this lane.

The prebenchmark exact-parity audit passed 640 random child-bound and 640 budgeted
closest-quad comparisons. Twelve geometry tests, including the new scalar/batch rounding
and seed-tie regression, and twenty existing surfacefix tests passed. Independent audit
reported exact parity for 480 child bounds, 224 adversarial closest-quad cases including
138 budget abstentions, all 2,082 heap push/pop events, and 28 projection cases covering
thresholds, edges, holes, folds, masked inputs, remote rivals and nonunique saddles.
The untouched geometry functions were AST-identical. Independent review receipts are
owned by the parent audit lane; this lane does not substitute its own tests for that review.

## Frozen benchmark and limits

Initial profile rule hash: `6a9cd66f001e3f9491a943271b7ea572e73e2bc0293d819c97992dbbfbdf3c99`.
Repeated benchmark rule hash: `582429ecdb0ca0492697af3440a46158c9c8117d64c155d4cec49e2de5035829`.
Before any repeated timing, parent requested cold process measurement in addition to
the inner operation timer. The original rule was preserved and amendment
`9dcd939d50a5583ad9cc4fa0a85f1d96c816b80704958bcc0012699846ea90b1` froze the worker and
process harness. Cases, parameters, pair order, exactness requirements and 1.5x target
were retained. The original in-process repeated harness was not executed.

Each of two cases used a warmup per version and five alternating before/after pairs.
The parent paused competing heavy jobs for the final timing window. A cold subprocess
performed every operation; its parent timer includes Python startup, all imports,
mesh/map reads, input hashing, correction, output writes, evidence serialization and
process exit. Separate inner timers measure complete `correct()` and geometry only.
These workers call the production correction operation directly; no claim is made about
CLI argument-parser timing. All workers inherited one CPU and one-thread numerical settings.

All 24 main runs and two displaced-reference schema2 null runs had exact report/projection/
output parity, with no excluded fields or numerical tolerance substitutions. Both tangential
candidate runs raised the same normal-offset error and left no output directory. Inputs
were hashed before timing and verified on execution. Full details are in `process-result.json`.

This measures the correction step with already computed reader maps, not CT loading,
rendering, model inference, flattening, or the complete decipherment pipeline. It establishes
a production software speedup on this bounded real workload, not an ink-accuracy improvement
or a universal 2x guarantee. The optimization applies whenever continuous correspondence
requires repeated child subdivision; workload-dependent speedup elsewhere remains unmeasured.
