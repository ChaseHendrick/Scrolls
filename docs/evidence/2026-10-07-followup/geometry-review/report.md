# Independent continuous-correspondence code review

7 October 2026. Geometry and software checks only, prepared for Chase Hendrick. No new CT downloads, reader inference, target maps or labelled ink claims.

**Final review passes for the inspected source.** The production full test suite must also pass before inference, and the implementation must remain unchanged after its hashes are frozen.

Reviewed source SHA-256 values:

- `kit/_surface_geometry.py`: `75457b1629e914480cca0be63847f9fc3b004cc5e0c3635a86dde7b42aaae393`.
- `kit/surfacefix.py`: `c44e8fb21be1381a0788ab7add7dfc23f3db52c2a90852d147b7d8d8fe989117`.

Exact source snapshots are retained beside this report.

## Why the bounds are sound

A bilinear quad is a convex combination of its four corners. Its corner AABB and centroid ball therefore contain every on-quad point. A centroid-tree radius of the physical limit plus the maximum corner radius includes every quad that could qualify. AABB pruning cannot discard a point within the physical limit. The search uses all qualifying quads, rather than a fixed count of nearby centroids.

For either triangle diagonal, the corresponding triangle interpolation differs from the bilinear surface by at most `||p11-p10-p01+p00||/4` at the same UV. Subtracting this deviation from the triangle's closest distance gives a conservative bilinear distance lower bound. Evaluating an actual bilinear point gives a feasible upper bound. Four-way parameter subdivision tightens these brackets; budget exhaustion remains unresolved, and the upper distance must satisfy the unchanged physical threshold.

The quad validity test is also sound: its Jacobian normal is affine in UV. If all four corner normals have a positive dot product with their common mean normal, that dot product remains positive throughout the unit box. This excludes a zero Jacobian or orientation reversal within the quad. Four valid corners are required, so the method does not interpolate across a missing corner.

No-fold geometry alone does not establish a unique closest point. The new `_unique_minimum` addresses that issue. For `F = 0.5 ||a+bu+cv+duv-q||^2`, the Hessian has:

`H11=||b+dv||^2`, `H22=||c+du||^2`,

`H12=b.c+(a-q).d+2(b.d)u+2(c.d)v+2||d||^2 uv`.

The diagonal minima are exact bounded line minima. The off-diagonal is bilinear, so its absolute maximum is bounded by the four corners. Strictly positive diagonal minima and a positive lower determinant bound, including the floating-point guard, suffice for positive definiteness everywhere. Thus the squared-distance objective is globally strictly convex and has one constrained closest UV. This is a sufficient certificate; failure causes abstention rather than a claim that every failed quad is actually ambiguous.

## Independent checks and corrected findings

1. **Randomized distance brackets:** sixteen fixed-seed regular nonplanar quads were compared with an 81-by-81 dense UV grid and nine-start bounded L-BFGS-B optimization. Every certified distance bracket contained the optimized result and remained below the sampled-grid minimum. Every case converged; the largest bracket width was 0.000963 voxels for a 0.001-voxel tolerance. Numerical comparisons supplement the algebraic bounds; they are not themselves a formal proof.
2. **Adjacent edge coverage:** a flat two-by-three reference grid with 20-voxel native spacing initially rejected unique points at UV `(0.3,0.999)` and `(0.3,0.9999)` as ambiguous. Adding the optimization tolerance to the competitor comparison manufactured those ties. The implementation now uses only a floating arithmetic epsilon for that comparison. All five exact-edge/near-edge plane fixtures pass on the reviewed source.
3. **Unresolved remote competitor:** an exhausted competitor with distance bracket `[3,3.1]` inside radius 5 was initially ignored when another quad had distance 1. Fault injection reproduced the unsafe acceptance. The fixed method rejects any unresolved quad which could lie within the physical radius, including a farther remote winding. The independent fault-path recheck passes.
4. **Two nearest points within one valid quad:** the smooth saddle `z=2xy`, for `x,y` in `[-1,1]`, has two exact closest points to `(0,0,1)`, at UV `(0.25,0.25)` and `(0.75,0.75)`, each at distance `sqrt(0.75)`. The no-fold test accepts this regular quad. The original inter-quad-only ambiguity test therefore missed the ambiguity. The new global convexity certificate fails closed on this example; the independent recheck passes.
5. **Convexity bound audit:** a separate algebraic lower bound using Jacobian normal projection and residual-dot extrema was checked against 1,600 sampled Hessians. Every sampled eigenvalue exceeded that lower bound. This provides an independent numerical check of the strict-convexity reasoning, while the production implementation uses its own diagonal/determinant bound.

## Integration review

Schema 2 declares linear position interpolation, unit render scale, group 0, zero rotation, no affine transform and the full native canvas. Those assumptions are required; arbitrary bicubic or transformed renders cannot inherit this bilinear correspondence certificate.

Reference UV is computed from baseline and reference geometry before any reader map is loaded. Candidates do not retune it. Frozen mesh hashes are compared with the reread record hashes before scoring. Dense reference high-pass maps are sampled directly at fractional `UV/scale - 0.5`; the code does not interpolate an already decimated native high-pass array. Coverage requires the contributing dense map pixels to be covered. Boundary samples outside the canvas, holes and unresolved geometry remain excluded.

Forward, reverse and shuffle controls retain the same fixed matches and evaluation subset. Fractional spatial controls shift the same UV without wrapping and check actual 3D separation within the existing 1-3 mm bounds. The source selection/audit split, one-winner audit and minimum point/correlation/gain/control bars remain in force. Schema 1 retains the earlier matching path.

## Limits

This review establishes conservative correspondence behavior for the inspected code and tested cases. It does not prove that two physically nearby traces belong to the same historical sheet, that correlated reader output identifies ink, or that a corrected combined surface is globally free of self-intersections. The existing rerender requirement remains necessary. Global maximum-radius enumeration is memory bounded per source point but can be slow for malformed or unusually large quads. The new sufficient convexity certificate can reduce coverage in difficult geometry; it must not be bypassed to obtain a positive correction.

Independent scripts and results are `audit.py`, `result.json`, `adversarial.py` and `adversarial-result.json`. They use one CPU thread; the original randomized distance/edge audit took about 0.51 seconds excluding imports. No source files were edited by this reviewer.
