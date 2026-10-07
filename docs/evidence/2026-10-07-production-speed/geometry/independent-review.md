# Independent review of batched subdivision bounds

No blocking correctness defect was found in candidate
`4590aacfcefbac089abfc31ed03e7dd3ff3ec2f704e4c7047b716df03bfc0baa`,
compared with baseline
`75457b1629e914480cca0be63847f9fc3b004cc5e0c3635a86dde7b42aaae393`.
This review addresses numerical and behavioral parity, not performance claims.

## Change and certificate review

The optimization evaluates a subdivision node's four child bounds in one NumPy
batch. Child order remains `(low u, low v)`, `(low u, high v)`, `(high u, low v)`,
`(high u, high v)`. The code then processes those results sequentially in the
original order, with the original strict upper-bound comparison, lexicographic
UV tie rule, heap serial updates, pruning and budget check.

Every child bound depends only on the point, original corners and its own box.
It does not depend on the evolving best upper bound or heap. Precomputing the
four bounds therefore does not change the branch-and-bound state transition.
The triangle closest-point and bilinear calculations retain their arithmetic
order along each vector's reduction axis. The warp error continues to use the
original single-vector `np.linalg.norm` calculation, avoiding an otherwise
possible rounding change from replacing it with a batched norm.

AST comparison confirms `_cell_bounds`, `_triangle_closest`, `_unique_minimum`,
`bilinear`, `project`, `quad_mask` and `sample_geometry` are unchanged. In
particular, the conservative lower/feasible-upper distance certificates,
uniqueness condition, unresolved-rival policy, ambiguity flags and strict
physical distance limit are unchanged. No tolerance, search radius, solver
budget or acceptance bar was relaxed.

## Independent adversarial checks

The isolated review script used one CPU and the existing numerical environment.
It did not edit the shared repository or run during the repeated timing window.

- All 480 scalar child bounds exactly matched batched lower/upper bounds and UV
  array bytes, across random boxes at scales from `1e-7` to `1e6`, including
  coordinate translations as large as `1e12`.
- All 224 closest-quad cases matched exactly, including warped and symmetric
  saddle patches, flat ties, edges, near-edge points, degenerate/collinear
  corners, translated coordinates and random warped patches. Tolerances were
  `1e-3` and `1e-8`; budgets were 1, 4, 5, 9, 17, 64 and 256.
- All 2,082 recorded heap push/pop events matched exactly, directly checking
  child ordering, serial allocation, tie behavior, pruning and budget effects.
  The set included 138 explicit budget abstentions. Solver inputs were unchanged.
- All 28 full projection cases matched UV/distance array bytes and all validity,
  ambiguous and unresolved flags. These include distances exactly at and just
  outside the physical threshold, shared edges, holes, folded and empty valid
  references, an invalid masked source, remote competitors and a nonunique
  saddle. The observed outcomes include valid matches, ambiguous refusals and
  unresolved refusals; parity was not established only on accepting cases.
- Baseline and candidate source hashes were verified again after execution.

`independent-review.json` records counts and source hashes, and
`independent_review.py` is the reproduction script. Its 1.26-second execution
is review cost, not a geometry or application speed benchmark.

## Scope

Exact parity is demonstrated for these cases in the installed environment; it
is not a proof of identical bits for every possible NumPy version, platform or
floating-point input. The unchanged numerical certificates plus matching heap
traces support integrating this batching optimization subject to the repository
tests and the separately frozen actual-workload benchmark. The benchmark must
still report exact output parity and measured application runtime. No mesh
quality, ink accuracy, corrected-region acceptance or groundbreaking discovery
claim follows from reducing interpreter overhead.
