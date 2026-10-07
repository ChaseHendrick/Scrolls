# Public PR #1996 review

Reviewed 2026-10-07, read-only. No outward posting, shared repository changes, model inference, or CT/prediction payload downloads. This report uses public sources; it does not reproduce private Discord text.

## Pinned sources

- [Public PR](https://github.com/ScrollPrize/villa/pull/1996), opened by `ibarapascal` on 2026-10-07 at 10:21:17 UTC, open at review time.
- Head `d651f04d2f5c73fc5ba46c5f859392391cc59b43`; its parent and current main/base `e0bbb8b40a2db58b1d71864f286eb85717e59e64`.
- [Actual mask implementation](https://github.com/ScrollPrize/villa/blob/d651f04d2f5c73fc5ba46c5f859392391cc59b43/spiral-fitting/grow_track_graph.py#L2266), [integration](https://github.com/ScrollPrize/villa/blob/d651f04d2f5c73fc5ba46c5f859392391cc59b43/spiral-fitting/grow_track_graph.py#L2583), [tests](https://github.com/ScrollPrize/villa/blob/d651f04d2f5c73fc5ba46c5f859392391cc59b43/spiral-fitting/tests/test_grow_track_coarse_mask.py).
- Linked public study `ibarapascal/ink-surface-support`, pinned `e8623546a3e147e656f3059cf5c8d78db2fe7473`: [results](https://github.com/ibarapascal/ink-surface-support/blob/e8623546a3e147e656f3059cf5c8d78db2fe7473/docs/RESULTS.md), [reproduction](https://github.com/ibarapascal/ink-surface-support/blob/e8623546a3e147e656f3059cf5c8d78db2fe7473/docs/REPRODUCE.md), [input receipts](https://github.com/ibarapascal/ink-surface-support/blob/e8623546a3e147e656f3059cf5c8d78db2fe7473/reproduction/data-sources.json).

## What support certifies

An output quad is permitted only when every fine validity vertex in its inclusive parameter-grid footprint is valid. Integral-image hole counts include interior fine vertices, so this is stronger than checking just the four output corners. Coordinates of retained vertices stay unchanged. If an unsupported complete quad exists, the implementation deletes the corner losing the least adjacent supported two-triangle area; ties follow row/column order. The usual largest four-connected component filter remains.

This certifies mask occupancy in the cleaned fine parameter domain. It does not establish physical sheet identity, CT alignment, bounded coarse interpolation error, a nonzero bilinear Jacobian, or absence of folding. The fine-grid cleaning and prior fold checks remain; there is no additional geometric regularity check after output coarsening.

The default still uses one-cell erosion. CLI support accepts output/resample-spacing ratios that are positive whole multiples. The actual resampling factor is output spacing divided by the measured median physical edge, so it need not be an integer; the helper correctly handles fractional footprints. The main measured configurations are working spacing 5 and output spacing 10/5, in 9.6 micrometer voxels. Do not transfer these voxel spacings directly to PHerc0841.

## Publicly verifiable benchmark

The public PR and linked tables report the same headline. At a **4-voxel / 38.4 micrometer distance tolerance**, the held-out V3 region gives:

| Reference | Unpatched spacing 10 | Support spacing 10 | Unpatched spacing 5 | Support share of spacing 5 |
|---|---:|---:|---:|---:|
| 20231210121321 | 9.997 mm2 | 11.104 mm2 | 11.390 mm2 | 97.5% |
| 20230702185753 | 13.926 mm2 | 15.428 mm2 | 15.585 mm2 | 99.0% |

Flatten CPU totals over the 18 accepted V3 patches are 274.07 / 276.64 / 555.14 seconds in that order. These are single-run user+system CPU timings of the flatten CLI, not total extraction/growth/flatten runtime and not repeated performance estimates. At the tighter 0.5-voxel / 4.8 micrometer tolerance, support shares are 89.5% and 97.0%, respectively; the headline is tolerance-dependent.

Three regions of the same PHercParis4 scan were used, with 32 fixed attempts per region/arm. V1/V2 were development regions; V3 was fixed before patched output was produced there. All arms accepted the same 65/96 attempts; failures were retained, producing 195 flattened outputs. Registered references and a held-out region of the same scan are not independent ground truth. Reference areas are scored separately, not summed. The third reference intersects no output in V3.

Shared-cell area-weighted mean symmetric-Dirichlet loss rises from 0.000178489 to 0.000199355 (+11.69%) across 65 pairs / 72,066 shared source cells. The relative increase is +13.6% in V3. Newly retained cells are excluded from this paired distortion comparison; distortion versus the spacing-5 baseline was not measured. Extra unknown/outside output area increases. These are surface proximity and flattening results, not ink accuracy or recovered text.

Crucially, [the study states](https://github.com/ibarapascal/ink-surface-support/blob/e8623546a3e147e656f3059cf5c8d78db2fe7473/docs/RESULTS.md#where-the-gain-comes-from) that **no measured case needed a greedy corner deletion**. The demonstrated gain therefore comes from skipping the final erosion; the difficult hole-handling branch has synthetic tests but no measured real-case benchmark here.

## Verification and safety edges

- Actual PR tests: **12 passed** with Python 3.12 and the existing NumPy/SciPy environment, using an isolated pytest install outside Scrolls. This does not validate the full spiral-fitting environment, whose current pyproject requires Python >=3.14.
- Linked study helper numerical tests: **11 passed**.
- Published `rebuild.py --check`: **PASS**, rebuilding all six derived result files and checking evidence, numeric-source and evaluation-source hashes, accounting and arithmetic. This is saved-report verification, not a rerun of scientific measurements. AST fingerprint checking is intentionally skipped outside the recorded Python 3.14.4; byte hashes are checked.
- Independent fixed-seed check: **240/240** plane/bent-mask cases match PR default output to its base byte-for-byte and PR support output to the older study helper byte-for-byte; all retained quads pass independent fine-support checks. `review_checks.py` and `review-checks.json` record the cases. A bow-tie with all fine vertices valid remains supported while its central bilinear Jacobian is zero, illustrating the expected limit of a validity-only mask.
- Live S3 prediction and CT `.zarray` metadata match the study's declared shapes, chunks and uint8 types. No chunk payload or reference coordinate data was downloaded for this review.

No correctness defect was confirmed in the mask invariant for valid finite lattice inputs. Remaining edges are scope and operational guarantees: greedy deletions do not optimize global area; largest-component selection can change which component survives (the public spacing-20 experiment observed this); retained coverage need not grow monotonically. Every deletion rebuilds arrays across the entire output grid, giving potentially quadratic work for adversarial holes. Unlike the public study helper, the PR helper has no 250,000-vertex cap, lattice-shape validation or emitted per-quad support certificate. The PR broadens accepted CLI spacing combinations beyond the two measured pairs. These deserve bounded tests/receipts before generalizing, rather than claiming the published benchmark validates every mode.

The public study records 47 development-region flatten wrappers as FAILED with independently qualified artifacts/unsealed timing logs; all 54 V3 flatten wrappers are SUCCEEDED. This nuance is present in evidence.json. It does not invalidate the V3 headline, but the all-region aggregate has a less uniform execution receipt.

## Fit with continuous quad matching and feasible reproduction

Support masking and continuous quad matching solve complementary problems. The mask retains more potentially usable quads near boundaries while excluding quads spanning fine invalid cells. Continuous bilinear correspondence locates matches inside those retained quads and can avoid vertex-snapping error; its certified geometric gates should still reject singular/folded quads, bound interpolant error, and retain ambiguity/physical-sheet checks. A fine-support certificate cannot replace those checks. Preserve source U/V identity and coordinate scale independently of retained-mask shape.

The cheapest real-data follow-up uses already cached PHerc0841 meshes: fixed coarsening factors 2/4, identical cleaned masks for erode/support, continuous same-U/V fine-to-coarse geometry error, quads' Jacobian/fold tests, physical retained area and fine-support audit. This requires no CT, model or labels and is being independently run by the geometry-interaction reviewer. It tests transfer of the mask invariant and geometric consequences, not Paris4's CPU/coverage headline; existing meshes have native 20-voxel grid spacing, so factors2/4 are not the study's spacing5/10 recipe.

A full public Paris4 rerun is CPU-capable but is a separate, larger acquisition/environment task. Published V3 receipts identify 512 compressed prediction chunks totaling 192,028,302 bytes; no V3 CT chunks are needed for the published geometry coverage test. The three registered-reference XYZ/meta sets total 189,376,954 bytes. Decoding a full 1536-cubed prediction crop requires 3.375 GiB before copies, exceeding our former 2-GiB process limit; extraction must stream recorded slabs or run in an explicitly larger budget. Exact packed-track/crossing hashes and the fixed 32-seed prefix must match. The source records identify historical inputs but do not bundle intermediate tracks or cleaned grids, so simply downloading reference meshes cannot reproduce production arms. Use CPU skeletonization dependencies and the pinned official Lasagna CPU float32 recipe, never fill missing chunks with zeros, then repeat timing runs on identical accepted pairs. The public flatten-only V3 workload was about 18.4 minutes of single-core CPU across all three arms; extraction/growth cost and local porting are additional and not established here.

Recommendation: keep this opt-in, carry a support receipt, and apply explicit continuous-geometry gates to the extra retained cells. It is a credible erosion-versus-coverage tradeoff with transparent limitations, not yet evidence of safer sheet tracing or improved ink recovery.

## Local artifacts and commands

`review-receipt.json` records the pinned commits, file identity and test results; `evidence-source-sha256.json` hashes the public study source/evidence; `sha256-manifest.json` hashes this report, extracted PR source/tests and local verification artifacts.

```sh
PYTHONPATH=/workspace/scrolls-env/pr1996-review/test-runtime OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /workspace/Scrolls/.venv/bin/python -m pytest -q /workspace/scrolls-env/pr1996-review/test_grow_track_coarse_mask.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /workspace/Scrolls/.venv/bin/python /workspace/scrolls-env/pr1996-review/review_checks.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /workspace/Scrolls/.venv/bin/python /tmp/scrolls-pr1996-evidence/vendor/output-spacing-10/test_support_safe_finalize.py -v
python /tmp/scrolls-pr1996-evidence/reproduction/rebuild.py --check
```
