# Adaptive resolution: useful local discrimination, incomplete margin protection

A frozen 25-micrometer geometric error rule identified patches that can use one bilinear
primitive instead of four native primitives, with about 52-54% theoretical primitive
reduction on three published PHerc0841 traces. The primary separate-surface ag405 check
retained 116/120 local correspondence stress queries (96.67%), versus 106/120 for uniform
coarsening and 111/120 for count-matched random selection. The same-sheet ag896 diagnostic
retained only 112/120 (93.33%), failing the frozen 95% requirement. Keep that failure:
this is a promising geometric discriminator, not a generally validated safe export rule.

| Trace | Role | Selected 2x2 blocks | Theoretical primitive reduction | Adaptive eligible queries | Uniform2 eligible | Count-matched random eligible | Frozen >=20% and >=95% endpoints |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| w00 | Existing surface diagnostic | 6304 | 52.19% | 116/120 | 104/120 | 110/120 | Pass |
| ag896 | Same-sheet cross-trace diagnostic | 6261 | 51.63% | 112/120 | 104/120 | 108/120 | **Fail** |
| ag405 | Primary separate published surface | 6167 | 54.04% | 116/120 | 106/120 | 111/120 | Pass |

## Frozen design and direct measurements

The first rule was frozen before execution with SHA256
`ad7c395cbe658679fe84481fd5d190fe45ca622ac6817977b73dc897614e0cab`.
It records that ag405 was not initially cached and that w00/ag896 trace the same physical
sheet. Parent then authorized a bounded public ag405 geometry-only fetch. Its four XYZ/meta
files totaled 553,406 bytes; their official URLs and hashes are in
`ag405-download-receipt.json`. A separate ag405 primary rule was frozen before outcome
readout with SHA256 `e149b3f78af6620aa07041d4c2530e1ed9ffd064de2ff59dc60ef7b4baf4bd9a`.
The original rule remains preserved. Both rules use identical numerical bars and controls;
there was no outcome-driven parameter retuning.

Disjoint 2x2 native cells form each candidate block. All nine native vertices must be
valid, all four fine quads must pass the existing Jacobian certificate, and the coarse
quad must also pass it. Retain a coarse representation only when maximum discrepancy
at the nine native vertices is at most 25 micrometers, using the published 9.366-micrometer
CT voxel scale. In each fine cell, coarse bilinear interpolation minus native bilinear
interpolation is bilinear. Its vector value is a convex combination of the four corner
differences, so its norm cannot exceed their maximum. This bounds the entire digital
surface mapping, not just sampled locations. It does not bound the native mesh's physical
error relative to the actual papyrus.

Independent 17x17 interpolation audits on 64 selected and 64 unselected complete patches
per trace all satisfied the native-corner bound (384 patch audits in total). These sampled
checks supplement the mathematical argument; they are not its proof.

Each trace used 40 prospectively seeded complete blocks, with one fixed nonvertex UV
position and queries on the fine surface and at +40/-40 micrometers along its fine local
normal. These are 120 local geometry queries per trace, disjoint from the earlier study's
48 native-vertex queries. Native fine geometry accepted all 120. All modes use exactly
the same source queries, frozen closest-point implementation, physical 50-micrometer
upper-distance bar and source-coordinate roundoff tolerance. Selected patches use the
coarse quad; rejected patches retain native geometry. Uniform2 and random count-matched
selection retain native geometry where the coarse Jacobian certificate fails. The random
mode selects the same number of coarse primitives as the adaptive mode, separating the
benefit of the criterion from merely selecting fewer coarse patches.

No adaptive mode lost an on-surface query (40/40 on each trace). Losses arose in the
deliberately tight normal-offset controls:

| Trace | Adaptive +40 micrometers | Adaptive -40 micrometers |
| --- | ---: | ---: |
| w00 | 39/40 | 37/40 |
| ag896 | 38/40 | 34/40 |
| ag405 | 40/40 | 36/40 |

There were zero ambiguous or unresolved queries in these real local patches. That is not
a whole-surface ambiguity result: queries were checked against their local native/coarse
patches, not against every distant sheet or quad.

## Controls and implications

All frozen controls passed. A uniformly translated plane produced identical selection
metrics and zero interpolation error. A nonplanar exactly bilinear patch also produced
zero error. A saddle produced zero representation error and a valid local Jacobian yet
was rejected by the existing nearest-point uniqueness check. This demonstrates why the
new approximation certificate cannot replace correspondence ambiguity protection.
A bowed central vertex had 93.66-micrometer error and was excluded; a missing central
vertex prevented acceptance.

The ag896 failure explains a real limitation: a 25-micrometer representation allowance
can consume more than the 10-micrometer distance margin of a query already 40 micrometers
from the native patch. A future, separately frozen experiment could condition its error
budget on the existing query's certified distance margin using the triangle inequality.
That would still need uniqueness, global rival, topology and reader checks. No such rule
was substituted or tested after seeing these outcomes.

This provides information beyond the previous blanket-spacing stress test: a conservative
geometry criterion performs better than uniform and count-matched random coarsening on
all three traces, while retaining a concrete adverse cross-trace result. Adaptive meshing
and convex interpolation bounds are established mathematical ideas. The local empirical
result on these public PHerc0841 traces is the contribution; no worldwide methodological
novelty or decipherment is claimed.

## Cost, provenance and limits

The w00/ag896 audit took 9.27 seconds with 74.7 MB peak RSS. The ag405 audit took 4.34
seconds with 66.5 MB peak RSS. Runs were sequential on one CPU, with no training, GPU,
CT fetch, ink labels, model inference or new reader maps. These measure audit cost only,
not flattening throughput or runtime savings.

The count reduction is hypothetical patch-primitive reduction before handling hanging
edges, conformity and transition strips. No mesh was exported. No global topology,
manifold, self-intersection, material identity, ink-preservation or flatten-distortion
claim follows. A production implementation must account for transition geometry and
retain existing correspondence, distance, Jacobian, global collision and actual CT reader
controls. Do not relax the existing 50-micrometer bar on the strength of this diagnostic.

All traces come from one CT acquisition. w00 and ag896 are the same sheet. ag405 is a
separate published surface, but this experiment does not independently certify distinct
material identity or statistical independence. Query endpoints are clustered within
40 blocks per trace; no p-values, confidence intervals or broad generalization are claimed.

The geometry helper was snapshotted before runs with only its lazy NumPy loader replaced
by an equivalent local import to avoid changes during parent PR merges. Frozen rules hash
that snapshot, audit scripts and all geometry inputs. `SHA256SUMS` covers the saved audit
artifacts and downloaded geometry; `verification.json` records on-disk verification of
the manifest and original frozen input hashes. No repository files or previous evidence
artifacts were changed.
