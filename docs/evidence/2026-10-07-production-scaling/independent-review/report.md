# Independent review of triangle-edge batching

Two exactness regressions were found and fixed before repeated timing. The final
reviewed candidate has no outstanding correctness blocker in the tested scope:
`290634636090c9355ddd98d89b008db0cb2de34fd5c66aa6b98abae6e3153721`.
Baseline from the `c43c41a` export:
`4590aacfcefbac089abfc31ed03e7dd3ff3ec2f704e4c7047b716df03bfc0baa`.
This review does not establish a runtime or memory improvement.

## Findings preserved

1. Candidate `0299fe7aeb38cde77d0fbeb1e7fde41be05231b5fc67b39cfb0588f3e51cb072`
   allocated barycentric storage as float64 unconditionally. The original helper
   promotes its interior and edge arrays when stacking, preserving longdouble
   interior values. A longdouble triangle with corners `(0,0,0)`, `(3,0,0)`,
   `(0,3,0)` queried at `(1,1,1)` changes returned thirds by about `1.85e-17`.
   A planar quad propagates the change to UV dtype and values. The reproduction
   is recorded in `longdouble-finding.json`.
2. The promotion repair in candidate
   `3983fa76efa53275ed4e93de1ce5f088be9c101b8577bba3a2c0482230e1d7f4`
   still changed reductions for a Fortran-contiguous float16 triangle batch with
   mixed point dtype. A 17-triangle float16/float32 example changed two distances
   by up to `0.000198841` and four barycentrics by up to `0.00048828125`. Another
   float16/longdouble example changed a barycentric weight. The complete first
   input and both outputs are in `layout-mismatch.json`; the direct sweep is in
   `initial-layout-audit.json`.

These were helper semantics regressions beyond the ordinary float64 production
mesh loader, not observed failures of the real correction workload. Preserved
source snapshots identify both rejected candidates; they were not erased after
the fixes.

The final candidate batches only native float32/float64 triangles whose point
array has the same dtype. Half, wider and mixed dtypes retain the original scalar
helper. AST comparison verifies that compatibility helper is exactly the old
function after its name change. This avoids narrowing or changing the inherited
layout-sensitive reduction path for those inputs.

## Arithmetic, ties and certificates

The fast path retains the interior, AB, BC, CA candidate order and the original
first-minimum `argmin` behavior. Edge alpha values are computed with the original
dtype and clamped to the same bounds. Interior barycentric promotion and the
original float64 edge-weight rounding are preserved. The original scalar helper
also handles point inputs without a matching NumPy dtype.

`_cell_bounds`, `_child_bounds`, `_unique_minimum`, `bilinear`, `closest_quad`,
`project`, `quad_mask` and `sample_geometry` are AST-identical to the baseline.
Distance certificates, triangle ordering inside bilinear bounds, heap child order,
serial values, tie resolution, subdivision budget, convergence tolerances,
physical thresholds, unknown-rival handling and ambiguous/unresolved flags are
therefore unchanged outside the reviewed triangle calculation.

Batching introduces O(number of triangles) temporary arrays for edge starts,
vectors and weights; it does not create a cross-call cache. Existing callers use
two triangles for one cell or eight for four batched child cells. This inspection
does not establish lower peak memory, nor bound memory for arbitrarily large
direct calls to the private helper.

## Independent validation

The final candidate passed:

- 212 exact direct triangle cases spanning float16, float32, float64 and
  longdouble; mixed point dtypes; C-contiguous, Fortran-contiguous and strided
  arrays; batch sizes 0, 1, 2, 8 and 17; signed zero, nonfinite and extreme values;
  interior/edge/vertex and degenerate/collinear cases.
- Sixteen explicit expected-weight controls for first/second edge ties,
  collapsed triangles and vertices across four dtypes.
- Four malformed-shape checks and integer input exception-class comparisons.
  The inherited extra-vertex behavior is preserved. These checks do not promise
  identical exceptions for every unsupported Python object input.
- 72 closest-quad cases with 45 budget abstentions and 606 exactly matching heap
  push/pop events, across float32, float64 and longdouble inputs.
- 21 projection cases covering one-ULP distance boundaries, shared edges, holes,
  empty valid references, masked invalid source values, remote rivals and a
  nonunique saddle. Valid, ambiguous and unresolved outcomes all occur.
- Another 1,308 cancellation, mixed-dtype and C/Fortran-layout cases, with no
  mismatches. Powers-of-two cancellation inputs and random dynamic-range inputs
  supplement the primary sweep.

Source arrays were not modified. Exact array bytes are compared for float16/32/64;
longdouble compares dtype, values and signs, excluding non-value x87 padding
bytes. Source hashes were checked again after the principal audit. That audit
took 0.43 seconds on one CPU; the supplemental cancellation sweep took 0.64
seconds. These are verification costs, not performance benchmarks.

Receipts: `result.json` and `cancellation-audit.json`. Reproduction script:
`review.py`; its earlier version is preserved as
`review-before-scalar-fallback.py`. `cancellation_audit.py` preserves the command
body of the completed supplementary sweep, saved afterward without a rerun.
The author lane owns the separately frozen
real-workload timings and production regressions. No shared checkout edits,
downloads, model inference or heavy benchmark were performed by this review.

Exactness is demonstrated for these cases in the installed numerical environment,
not proved for every future NumPy implementation or every possible floating-point
input. Preserve the fixed compatibility path and targeted regression tests during
integration. No mesh-quality, ink-accuracy or novel-discovery claim follows from
this arithmetic optimization.
