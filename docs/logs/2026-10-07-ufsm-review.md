# UFSM ideas worth implementing in Scrolls

Reviewed 7 October 2026 for Chase Hendrick. Source: [SuperOptimizer/ufsm](https://github.com/SuperOptimizer/ufsm/tree/d86a00cff5ab198e6b7864f89e49a6101746dc9f), pinned commit `d86a00cff5ab198e6b7864f89e49a6101746dc9f`. This is an implementation assessment, not an integration or model-quality result. No production code, training job or target-scroll run was changed.

## Best near-term transfers

| Priority | Idea | Concrete use in Scrolls | Required check |
| --- | --- | --- | --- |
| 1 | Verified resume and staged output publication | Before skipping an atlas mesh, verify both direction outputs against the exact model, source, settings and output hashes. Publish a completed receipt only after all required artifacts pass. Reuse existing `kit.provenance` rather than add another hash system. | Missing/truncated/changed maps, same-size changed inputs, checkpoint or stride changes, and interrupted publication must never look completed. A failed rerun must preserve the prior valid result. |
| 2 | Prediction windows anchored to the full surface | Extract a real-data context envelope around each requested crop so the unchanged official reader sees the same windows covering shared pixels. Trim only after inference. This directly addresses the earlier crop/full-map discrepancy. | Overlapping shifted crops, irregular final windows, true canvas edges, normalization, blending and reader validity masks must match a fixed canonical full-surface run. Retain the full canvas size and crop origin. |
| 3 | Global geometric checks before accepting a corrected mesh | Check whether distant surface pieces collide after combined edits, in addition to the existing local Jacobian, movement and hole guards. Start as a CPU rejection/audit step using the official geometry conventions. | Crossing patches, coplanar overlap, allowed shared boundaries and near-contact cases must be distinguished. Triangle intersection tests alone cannot certify our bilinear surfaces. Unresolved geometric cases must abstain. |

The first is routine reliability work with immediate value. The second improves experimental comparability rather than the trained model itself. The third addresses a correction-quality gap; passing geometry checks still cannot establish the correct papyrus sheet or readable ink.

### Specific source evidence and current gaps

UFSM [prediction signatures and bundle validation](https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/tools/production.py#L487) and [staged replacement](https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/tools/eval_holdouts.py#L24) provide the useful run-control pattern. Their completion marker compares a signature and store metadata; it is not a full rehash of every prediction chunk. Our adaptation should verify the expected output artifacts with the provenance functionality we already have.

In Scrolls at `4af30e8`, `scripts/mac-atlas-v8in.sh` skips a mesh solely when the reverse TIFF exists. The benchmark wrapper's reuse check also relies partly on log settings. Independent local synthetic checks confirmed that `kit fetch` can retain a wrong same-size file and that `kit run check` does not recheck an attached file digest after modification; `kit provenance check --files` does catch the modification. These are distinct existing contracts, not evidence that previous scientific inputs were corrupted. Tie their appropriate checks into the resume decision. This assessment does not change their behavior.

UFSM's [global grid code](https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/src/predict.c#L294) and [reported common-ROI tests](https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/README.md#L350) anchor tiles independently of output boxes. Its CPU/GPU speed claims cannot be transferred to our readers. The current official villa reader appends an irregular final tile when needed; a wrapper must preserve that full-canvas schedule, not merely round every crop to a stride multiple. Real surrounding rendered data are necessary. v8in also computes a 7-by-7 closing mask, so tile context alone is insufficient without the mask's context or a fixed global mask. The [grid review](../evidence/2026-10-07-ufsm/grid-review.md) records the exact constraints and proposed runtime comparisons. No claim of measured real-map invariance is made here.

UFSM [mesh validation](https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/tools/sheet_reconstruct.py#L121) checks edge/vertex manifold structure and triangle intersections. It is a useful design reference, not an exact-predicate guarantee to copy into our different bilinear representation. Scrolls' current local correspondence certificates and adjacent-edit guards do not replace a global intersection test.

## More ambitious research lead

The [continuous-winding pipeline](https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/SHEET_PIPELINE.md) represents which turn of the scroll a surface follows as a continuous coordinate, instead of predicting only surface probability. Its associated ideas are useful:

- Require observed support along a connection, not just high-confidence endpoints. The [track scorer](https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/tools/sheet_pipeline.py#L473) explicitly catches isolated supported points masquerading as a continuous track.
- Reject ambiguous first normal-ray hits and unresolved contacts. Do not skip a nearer ambiguous sheet to find a more convenient farther match. Winding alignment needs a suitable axis and independently justified connectivity; segment names are not winding labels.
- Separate observed material, uncertainty and inferred completion. Reconstructed area must not count as recovered evidence simply because an optimizer filled a gap.
- Fit smooth corrections through a bounded ambient deformation. Each Euler update is injective if its displacement has Lipschitz constant below one; this can preserve an initially embedded surface in the continuous model. Finite-precision evaluation and the exported mesh still require checks, and a valid deformation can follow the wrong sheet.

This could guide a future geometry-based correction proposal generator while keeping our current reader controls and unchanged acceptance gates. It is not a ready replacement: the documented real-data winding pilot completed only twelve updates, and the matched quality ablations were not established in the reviewed record. The canonical spiral and winding gauges also need information absent from an arbitrary local crop. UFSM's dense band-field helper is tied to a Paris4 winding encoding and should not be applied directly to our PHerc0841 surfaces.

## What was actually verified

Independent CPU checks passed 29 tests for coverage, production controls and evaluation splitting, plus nine focused geometry tests. These use synthetic fixtures. Source inspection and small synthetic Scrolls contract checks used no target data, downloads of scan payloads, training or model inference. The archived review receipts identify commands, code pins, local hashes and test scope. Existing Scrolls runtime code remained unchanged.

UFSM's main build uses C23 and CUDA 13 with `sm_120`/`sm_120a` kernels. It is a surface model, not a drop-in ink reader. Those kernels do not run on this CPU environment or the user's M1 Pro. The Python geometry ideas and the run-control patterns can be evaluated independently on CPU. Only vendored component licenses were found in the reviewed tree; no top-level license for UFSM's own code was found. Independently implement the general ideas or resolve permission before copying that code into Scrolls.

[Hashed review evidence](../evidence/2026-10-07-ufsm/README.md) preserves this assessment's source pin, test reports and limitations. Passing these checks establishes selected software behavior, not a speedup, accurate new surface or groundbreaking ink-recovery result.
