# UFSM geometry methods that can help Scrolls

Reviewed public repository https://github.com/SuperOptimizer/ufsm at commit
`d86a00cff5ab198e6b7864f89e49a6101746dc9f`. Read-only review; no Scrolls implementation,
data changes, training, GPU use or published scientific claim resulted from this audit.

## Recommended order

1. **Audit the corrected surface globally, in addition to checking each local quad.**
   `tools/sheet_reconstruct.py:121-187` checks triangle self-intersections, edge incidence,
   connected vertex links and duplicate/degenerate faces. This complements Scrolls'
   certified local bilinear correspondence and Jacobian checks: individually regular
   patches can still collide with distant parts of the surface after correction.
   Implement an independent baseline-versus-corrected audit that rejects newly introduced
   collisions or nonmanifold geometry, preserves legitimate boundary edges and fails closed
   on unresolved geometry. Start with changed patches plus a conservative broad phase
   against the whole mesh. Do not treat a raw triangle approximation as the rendered
   bilinear surface: use conservative subdivision error bounds or bilinear intersection
   checks. UFSM's fixed floating tolerances and shared-vertex shrinking at lines 176-180
   also prevent calling this an exact robust-predicate certificate.

2. **Keep measured support separate from inferred geometry, and test connections themselves.**
   `tools/build_sheet_geometry.py:22-47` samples the original registered mesh grid rather
   than connecting decimated endpoints by a chord. Lines 178-213 exclude unresolved
   contacts from coordinate/path/gap supervision; a proposed gap negative also needs
   clearance from another observed surface. `tools/sheet_pipeline.py:451-465` samples
   probability along connections, and lines 585-591 require proximity to original evidence
   before reconstructed geometry contributes observed coverage. Apply the general rule to
   Scrolls' correction reports: accepted geometric correction, independently validated
   evidence, uncertainty and inferred completion are separate statuses. Do not claim an
   entire corrected region is supported because its endpoints pass or its mesh looks valid.
   Preserve holes and unresolved sheet contacts as abstentions. Our raw CT reader controls
   should validate material identity; a model probability path alone cannot establish it.
   UFSM's 8-voxel contact radius, 4-voxel evidence radius, 13 straight-line affinity samples
   and 32 mesh-path samples are dataset choices, not universal safe thresholds. Convert any
   new limits to physical units and freeze them before validation. Unreleased sheets remain
   a limitation (`SHEET_PIPELINE.md:40-47`); missing annotation is not proof of empty space.

3. **Explore a bounded ambient deformation for smoothly combining accepted corrections.**
   `tools/sheet_reconstruct.py:60-81` bounds the global Lipschitz constant L of a
   trilinearly interpolated velocity field and integrates small Euler maps. When each
   displacement has L/steps < 1, the distance inequality
   `||F(x)-F(y)|| >= (1-L/steps)||x-y||` makes that map injective; compositions remain
   injective in exact arithmetic. This is a useful architecture for a future correction
   field spanning several neighboring regions. It could prevent topology damage from
   independently blended offsets before a final mesh audit. It does not establish correct
   sheet identity, renderer accuracy, useful reconstruction quality or a globally metric
   flattening. Fitting its default 2000-iteration canonical spiral is a larger experimental
   change than adding an audit, and requires registered winding/axis evidence absent from
   many of our current surfaces. Keep this behind an experimental command until held-out
   real meshes, raw CT rerenders, explicit displacement limits and reader controls pass.

## Other useful details and unsuitable direct transfers

- `tools/sheet_geometry.py:118-156` uses the nearest registered triangle on a calibrated
  normal ray, rejecting an incompatible first hit rather than silently selecting a farther
  surface. Its abstention principle is valuable, but it requires reliable normals and
  integer winding alignment. It does not replace our certified bilinear closest-point
  and remote-competitor rejection.
- `tools/band_field.py:45-77` produces labels from Paris4 winding codes with a modulo-14
  representation, known axis, native-grid conversion and pitch assumptions. These are not
  a ready-made general sheet identity map for PHerc0841 or PHerc0139. Angular consistency
  in `sheet_geometry.py:53-100` can detect inconsistent cycles but cannot exclude every
  jump to a different winding at the same polar angle.
- `SHEET_PIPELINE.md:152-161` explicitly states that a valid manifold may still follow
  the wrong sheet. Adopt that separation of geometric validity from scientific accuracy.

## What was actually validated

The nine upstream `tests/test_sheet_geometry.py` tests passed on CPU in 0.053 seconds.
They exercise angular seams/holes, inconsistent cycles, first-hit abstention, numeric loss
gradients, reference contracts, one simple injective flow and several invalid meshes.
They are small fixtures, not full-scroll quality evidence. Exact command and output are
recorded in `test-results.txt`.

An additional independent seeded numerical smoke test (`flow_bound_audit.py`) checked
20 random velocity fields on anisotropic 4x5x6 grids with 400 point pairs per field,
including points outside the grid's physical box. All 8000 pairs satisfied the published
single-Euler-map lower distance bound in float64. This only tests consistency of the
implementation and bound on sampled pairs; it neither proves it numerically nor validates
actual papyrus reconstruction. The mathematical argument above supplies the reason for
the constraint. No fit or model update was run.

Upstream's reported 25-mesh local dataset qualification is documented at
`SHEET_PIPELINE.md:271-279`; we did not independently reproduce those data counts or audits.
Its four matched 2000-update ablations were prepared but had not started GPU training
(`:281-286`). The subsequent pilot ran only twelve 608-cube updates, after a 704-cube
out-of-memory failure (`:288-295`). Finite losses and brief throughput measurements do
not demonstrate convergence, sustained throughput, improved tracing or fewer sheet switches.

## Licensing and provenance

No top-level LICENSE was present at this commit. `README.md:399` identifies only
`third_party/volcomp.h` and `third_party/surfcomp/` as MIT; their license files do not
establish a license for the Python geometry tools. Reuse the generic mathematical and
audit ideas through an independent implementation, or clarify permission before copying
UFSM source into Scrolls. This is a code-redistribution limitation, not a reason to stop
the read-only review or local tests.

The report, audit code, measured output and test log are frozen in `SHA256SUMS`.
`source-hashes.json` records hashes of the source files that support this review; those
hashes were checked against the pinned checkout when creating the artifact manifest.

Public source links:

- https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/SHEET_PIPELINE.md
- https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/tools/sheet_reconstruct.py
- https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/tools/build_sheet_geometry.py
- https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/tools/sheet_pipeline.py
- https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/tools/sheet_geometry.py
