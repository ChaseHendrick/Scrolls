# Review of villa's coarse support mask, 7 October 2026

The user pointed to [villa PR #1996](https://github.com/ScrollPrize/villa/pull/1996). This review uses its public code and linked evidence. The PR is open, with head `d651f04d2f5c73fc5ba46c5f859392391cc59b43` against `e0bbb8b40a2db58b1d71864f286eb85717e59e64`.

## What it changes

`grow_track_graph.py --coarse-mask-mode support` can retain output quads whose complete footprint is supported by the cleaned working grid. It avoids automatically removing a one-cell rim from every coarse output. Interior unsupported cells are checked, not merely the four output corners. The default remains `erode`.

This complements continuous surface correspondence. Support masking decides whether there is source support for a cell; correspondence checks where a physical point matches inside the retained surface. Supported cells still need geometric regularity, ambiguity and distortion checks. This flag applies while generating new meshes. It does not repair an existing mesh or accelerate ink inference directly.

## What the public benchmark supports

The [linked study](https://github.com/ibarapascal/ink-surface-support/tree/e8623546a3e147e656f3059cf5c8d78db2fe7473) reports spacing 10 with support retained 97.5-99.0% of spacing 5 reference coverage on its held-back Paris4 region. The distance tolerance is 4 voxels, or 38.4 um. At 0.5 voxel, the two reference shares are 89.5% and 97.0%.

Flattening CPU totals were 276.64 seconds for spacing 10 with support and 555.14 seconds for spacing 5. These are single-run measurements of the flattening stage, not repeated whole-pipeline benchmarks. The aggregate paired symmetric-Dirichlet loss increased 11.69% relative to unpatched spacing 10; that comparison excludes newly retained cells and does not compare distortion against spacing 5.

No measured real case required the greedy deletion branch. The demonstrated coverage gain came from skipping final erosion. The study includes three regions on one scan and registered references, without an ink-accuracy or reading result. These remain community measurements: we checked their saved evidence, not a fresh Paris4 extraction and flattening run.

## Checks run here

- The exact PR's 12 tests passed, plus 11 numerical tests from the linked helper.
- All 240 fixed-seed plane/bent-mask cases reproduced default/base behavior and support/study-helper behavior byte-for-byte. Every retained quad passed an independent fine-support check.
- The public study's six derived tables rebuilt successfully with its source and evidence hash checks.
- A separate real-mesh stress test used cached PHerc0841 w00 and ag896 grids, with fixed coarsening factors 2 and 4. Their native spacing is about 20 volume voxels, so this is substantially coarser than the Paris4 spacing-5/10 recipe and cannot reproduce that headline.

At factor 2, support retained 98.70% and 98.63% of valid fine parameter cells, compared with 95.15% and 94.99% after erosion. No retained support quad crossed an invalid fine footprint. However, more retained quads failed our local Jacobian regularity certificate: w00 18 versus 13, ag896 27 versus 19. A failed sufficient certificate does not by itself prove a fold.

Same-parameter interpolation errors had 99th percentiles 68.6 and 73.1 um at factor 2, rising to 174.7 and 184.5 um at factor 4. These include tangential displacement and must not be interpreted as nearest-surface or normal gaps.

A separately frozen continuous-correspondence audit made that distinction explicit. On 48 fixed native points per mesh, support versus erosion yielded 33 versus 32 certified matches for w00 at factor 2 and 40 versus 37 at factor 4. ag896 gave 34 versus 32 and 29 versus 27. The unchanged physical limit was 50 um. Occupancy coverage near 98% did not imply 98% certified physical correspondence.

## Use in this repository

Keep the mode optional for a future mesh-generation comparison. Pin the exact official code, save the support configuration and footprint checks, and compare erode/support on the same inputs and accepted patches. Carry geometry and distortion checks forward, then evaluate actual rendered reader outputs if claiming downstream benefit. Keep this repository's existing defaults unchanged until that pipeline comparison exists.

The complete PR review, local real-mesh measurements, rules and hashes are retained in the [evidence archive](../evidence/2026-10-07-followup/). No comment, review or PR was posted upstream. This is useful community work with a measurable coverage tradeoff; neither its headline nor our tests establishes improved ink recovery.
