# Independent adaptive-resolution review

Reviewed the saved report, both frozen rules and scripts, geometry snapshot, both
results, public ag405 download receipt, and the 19-artifact manifest. No concrete
implementation or numerical reporting defect was found within the stated local
diagnostic scope. This review does not validate a deployable adaptive mesh or a
new ink-reading result.

## Checks performed

- Recomputed all 19 manifest entries, both frozen rule hashes and all 16 frozen
  input-hash entries. The existing manifest SHA256 is
  `56f69e0a413f4123684f08f4e9b2b7140b397d4084b142b81cf6c2e690db050b`.
- Independently implemented bilinear interpolation, fine-cell interpolation and
  the corner-normal regularity check, then reconstructed the complete-block
  enumeration, adaptive selection and primitive accounting from the TIFF inputs.
- Reproduced exactly the frozen query seeds, row/column choices, offsets, random
  count-matched masks, and all 360 saved query results. Query replay uses the
  frozen closest-point helper; it is not an independent proof of that helper.
- Ran 300 fresh synthetic patches with 150 random UV positions each, and 40
  fresh selected real patches per trace with 170 random UV positions each, using
  the independent interpolation implementation. All obeyed the corner bound.
- Replayed all five frozen synthetic controls successfully. The zero-error
  saddle's rejected correspondence is correctly retained as a separate concern.

The review script ran in 12.97 seconds with one CPU affinity. This is review cost,
not evidence of production flattening or inference savings. Existing evidence and
the shared repository checkout were not modified.

## Certificate and accounting

Restricting the coarse bilinear patch to any of the four native subcells gives a
bilinear function in that cell's local coordinates. Subtracting its native
bilinear patch therefore yields a bilinear vector function. Its value at every
point is a convex combination of its four corner values, so the triangle
inequality bounds its norm by the largest corner-discrepancy norm. Taking the
maximum over the nine native vertices bounds every subcell. This argument is
valid for the represented digital surfaces; it does not estimate papyrus truth.
The real data have finite coordinate values, and the independent numerical checks
are consistent with this exact-arithmetic argument. These are not interval-
arithmetic rounding certificates.

The selected blocks are disjoint in their native cells. Each replaces four native
regular primitives with one coarse primitive, so the claimed reduction is exactly
`3 * selected_blocks / native_regular_quads`. The independently recovered counts:

| Trace | Native regular quads | Selected blocks | Hypothetical reduction | Adaptive | Uniform | Random |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| w00 | 36237 | 6304 | 52.1898% | 116/120 | 104/120 | 110/120 |
| ag896 | 36381 | 6261 | 51.6286% | 112/120 | 104/120 | 108/120 |
| ag405 | 34236 | 6167 | 54.0396% | 116/120 | 106/120 | 111/120 |

As the source report explicitly states, this count is before hanging-edge,
continuity, transition-strip, manifold and collision requirements. No valid mesh
export or realized speedup follows from the primitive arithmetic.

## Outcome interpretation

The original rule names ag896 as its primary diagnostic. Its 112/120 retention
fails the frozen 95% endpoint, and that experiment must remain a failed test of
the general safety hypothesis. The ag405 rule is a separately frozen follow-up
with unchanged numerical thresholds; its 116/120 result passes its own endpoint.
Reporting it as a separately frozen follow-up is clearer than replacing the
original failed primary result with the successful one. Both are preserved in
the current report. Local rule hashes demonstrate integrity, not an externally
timestamped preregistration.

Only 40 query blocks per trace were tested, with three correlated offsets per
block. The random comparator uses one frozen mask seed. The saved data support
the reported ordering on those fixed queries, without a significance or general
performance claim. All queries are local to a 2x2 native-cell patch; distant
winding ambiguity, global intersections and whole-mesh behavior remain untested.

A 25-micrometer approximation error cannot guarantee preservation of a
50-micrometer distance gate for a query that already lies 40 micrometers from the
fine surface. The report's margin explanation is correct. Adapting a future rule
to that distance margin is a proposed next experiment, not a result measured here.

The empirical discriminator on these particular public PHerc0841 traces is useful
local evidence. Adaptive resolution and convex interpolation bounds are established
ideas. No worldwide novelty, ink preservation, decipherment, material independence,
reader accuracy, production topology or runtime claim is justified by this audit.

The machine-readable review receipt is `adaptive-independent-review.json`; the
read-only reproduction code is `adaptive_independent_audit.py`.
