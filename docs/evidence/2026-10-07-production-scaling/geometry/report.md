# Incremental geometry speedup versus c43c41a

The real correction process is **1.1044x faster than c43c41a**, reducing median cold
full-process wall time from 2.51378 to 2.27614 seconds (9.45% less wall time). The larger
64x64 geometry case improved by 1.12377x. All outputs and refusal behavior remain exact.
These are incremental measurements against the already optimized production version;
no historical total is inferred by multiplying unrelated benchmark results.

| Case/timer | Before median seconds | After median seconds | Incremental speedup |
| --- | ---: | ---: | ---: |
| Actual 32x32 full correction, cold process wall | 2.51378 | 2.27614 | 1.10440x |
| Actual complete correct() including I/O | 2.41026 | 2.16046 | 1.11563x |
| Actual correction geometry stage | 1.77688 | 1.53682 | 1.15621x |
| Larger 64x64/full-reference project() | 7.28554 | 6.48310 | 1.12377x |
| Larger geometry, cold process wall | 7.42381 | 6.62133 | 1.12120x |

Worker median peak RSS was effectively unchanged: actual correction 84,959,232 versus
84,955,136 bytes; larger geometry 69,419,008 versus 69,431,296 bytes. These page-scale
differences do not demonstrate meaningful memory improvement or regression.

## Change, review failures and compatibility

Residual c43c41a profiling identified `_triangle_closest` as a remaining hotspot:
1.28 seconds cumulative in the 3.32-second profiled correction, and 5.21 seconds in
the 9.99-second profiled larger geometry operation. Profiled times include profiling
overhead and are not benchmark performance claims.

The optimized path batches AB, BC and CA edge projections, preserving arithmetic and
coordinate-reduction order, triangle/edge ordering, first-minimum ties and the legacy
barycentric output behavior. Certificates, heap order, budgets, radius/threshold bars,
uniqueness and remote-rival rejection are unchanged. Only matched float32/float64 arrays
use this path. The production loader supplies matched float64 data.

Independent review found two genuine compatibility defects in earlier candidates:
longdouble interior barycentrics were narrowed to float64 in candidate `0299fe7a...`;
after promotion was fixed, float16 Fortran/mixed-point layouts still changed legacy
edge rounding in candidate `3983fa76...`. Both failing sources, original rules/results
and the review repro are preserved. The final candidate uses an AST-identical copy of
the original helper for half precision, wider precision, mixed dtypes and nonarray points.
This conservative fallback preserves the broader helper contract without forcing an
unverified optimization onto those inputs. No repeated timing used a failing candidate.

Final helper hash:
`290634636090c9355ddd98d89b008db0cb2de34fd5c66aa6b98abae6e3153721`.
Baseline helper hash: `4590aacfcefbac089abfc31ed03e7dd3ff3ec2f704e4c7047b716df03bfc0baa`.
`geometry-speed-v2.patch` and `ready-files.json` identify the implementation and regression
tests. This lane did not edit the shared repository or push changes.

Final checks passed 960 triangle batches across float16/32/64/longdouble, 256 budgeted
closest-quad comparisons and every projection field on the complete 4096-point larger
case. Fifteen geometry tests passed on the final candidate; twenty-four surfacefix tests
passed before the final compatibility fallback, whose production float64 path is unchanged.
The final full-operation benchmarks also verify the final source. Independent
review additionally passed 212 dtype/layout cases, 1308 mixed/layout/cancellation cases,
72 solver cases including 45 budget abstentions and 606 identical heap events, and
21 projection cases covering every refusal state. The scalar fallback is AST-identical
to the original helper after renaming. Review receipts and synthetic repro artifacts
remain in the separate independent-review directory.

## Frozen benchmark, scope and limits

Baseline code was exported from `c43c41a`. Before profiling, a fixed larger case selected
w00 native rows 64:128 and columns 64:128 against the entire cached ag896 reference.
Its 4096 valid source points and 37,027 valid reference vertices were selected geometrically,
without performance or reader-based tuning. Baseline projection produced 898 eligible,
23 ambiguous and 6 unresolved points; these are software geometry statuses, not accuracy
or material-identity measurements. The case uses the same published PHerc0841 sheet.

Profile rule: `174ecfa63e39db6134754a50434e2eaa27bf8fef457f7fdf569f065aecb448fc`.
Final source-fix amendment: `3e7169e0486f3dca100c6083337a7607dec5280b636dc68137148343a0299272`.
Final benchmark rule: `2b2454f793477b4dc0fa729a9df49f26df60d9371872536ac9406fcc583dbbf9`.
Earlier rules/amendments remain preserved; final rules and source hashes were frozen
before repeated timing, after the independent compatibility fixes.

Each main case used one warmup per version and five alternating before/after pairs.
The parent paused competing heavy jobs during timing. Cold worker wall timers include
Python startup, imports, input loading, complete operation, outputs/evidence serialization
and exit; correction additionally hashes its inputs within that operation. Larger geometry
input hashes are verified by the parent before timing. Inner timers measure correction and
geometry. The larger project() timer includes its lazy SciPy import; its process timer
also includes full-mesh input loading. One CPU and one-thread numerical settings were used.

Every report field, all five projection arrays and all output hashes matched across
24 main runs and four displaced-reference/schema1 control runs. Projection dtypes,
shapes and raw bytes were also verified across all 28 successful workers. Both tangential
negative runs raised the identical normal-offset error and left no output directory.
The existing real correction workload accepts zero regions at its frozen settings;
positive correction behavior is covered by the unchanged surfacefix tests. No threshold
or selection change was made to create a faster result.

This measures correction with already computed reader maps and a geometry-only larger
case. It excludes CT rendering, model inference, flattening and the complete reading
pipeline. No new downloads, training, GPU, new reader maps or raw data exports were used.
Workload-dependent performance elsewhere and any ink-accuracy improvement remain unmeasured.
The compact evidence list excludes raw meshes, projection arrays and model/data payloads.
