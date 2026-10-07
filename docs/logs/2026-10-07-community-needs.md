# 2026-10-07: community needs and correction software

Sourced facts and community reports are distinguished from untested ideas below. This was a targeted inspection of public issue bodies, preloaded comments and source code, not an exhaustive community survey. Initial requests to the GitHub API and Hugging Face were blocked; public GitHub pages and Git reads worked. Later approved requests fetched public S3 meshes and surface-volume metadata and the base-v8in README/config pinned to `d89166b` from Hugging Face. This verifies those specific endpoints, not unrestricted access. No target data, training, posting or upstream submission was performed.

## Maintainer priorities

**Sourced fact.** The maintainers want better sheets, not another standalone switch detector. In [villa #1937](https://github.com/ScrollPrize/villa/pull/1937), merged 30 September 2026, pmh47 wrote: "Aim to avoid LLMs fixating on sheet-switch detection" so they instead "create better sheets ... much more valuable."

The official [open-problems document](https://github.com/ScrollPrize/villa/blob/e0bbb8b40a2db58b1d71864f286eb85717e59e64/scrollprize.org/docs/37_2026_open_problems.md) requests topology-preserving predictions, geometry optimization, conservative fiber tracing, improved spiral-fit evaluation and label snapping. Its contribution guidance requires real-scroll evidence; synthetic-only results do not satisfy an upstream contribution. Its human-written motivation requirement also means generated research prose should not be submitted as the contributor's personal commentary.

| Explicit need | Evidence inspected on 2026-10-07 | Existing work and remaining gap |
| --- | --- | --- |
| Better compressed/curved surfaces and connected fibers | [Open #191](https://github.com/ScrollPrize/villa/issues/191), bruniss, 18 Apr 2025; [giorgioangel's evaluation requirement](https://github.com/ScrollPrize/villa/issues/191#issuecomment-4603217532), 2 Jun 2026 | Kaggle Surface Detection test-set evidence is required. Improved ink AUC alone can coexist with worse topology. |
| Better image/label pairs than mesh voxelization | [Open #193](https://github.com/ScrollPrize/villa/issues/193), bruniss, 18 Apr 2025 | [TAUIL's correction](https://github.com/ScrollPrize/villa/issues/193#issuecomment-5224267398), 8 Aug 2026, withdraws an unverified multi-model/CT recipe and explicitly requests trustworthy absent-sheet negatives. Unknown labels are not negatives. |
| Ready-to-run true 3D ink labels | [Open #192](https://github.com/ScrollPrize/villa/issues/192), bruniss, 18 Apr 2025 | [pmh47's warning](https://github.com/ScrollPrize/villa/issues/192#issuecomment-5282281283), 13 Aug 2026: a gradient peak does not establish ink identity. Existing depth validators do not resolve that identity problem. |
| Reproducible mesh, transform and render scale metadata | [Open #1727](https://github.com/ScrollPrize/villa/issues/1727), ge-al, 7 Sep 2026 | Existing metadata audits identify the gap. A local source-frame validator and provenance sidecar are feasible without training a new model. |
| Held-out reader evaluation and depth-direction checks | [Open #1867](https://github.com/ScrollPrize/villa/issues/1867), AndreasHad04, 22 Sep 2026 | Several analyses already exist. Independent-sheet splits, common label coordinates and render provenance remain important for comparisons. |

## Reuse before inventing another solver

**Sourced fact from code inspection.** villa already implements surface snapping and optimization in [Lasagna](https://github.com/ScrollPrize/villa/tree/e0bbb8b40a2db58b1d71864f286eb85717e59e64/lasagna), including `opt_loss_snap_surf.py`, `opt_loss_corr.py` and atlas snapping configs. Normal, distance, bend, Jacobian, metric and area losses already exist. `vc_atlas_pred_snap_rebuild.cpp` uses a normal sampler and preserves manually attached records. A new integration must compare with these methods, not claim to invent snapping.

**Community report.** [Jinhojeong's surface geometry diagnostic](https://github.com/Jinhojeong/vesuvius-surface-geometry-diagnostic), inspected commit `34011216020f5bdb3070f5693f0e2721616e1c28`, already has a ray flag, continuity splitter, synthetic twin tests and topology-aware repair comparisons. Its reported performance was not independently reproduced here. The relevant lesson is to measure topology along with reader output.

## Useful parts of the user's other repositories

**Sourced fact from code inspection.** [GENChase's differential geometry harness](https://github.com/ChaseHendrick/GENChase/blob/f8ae2ff35b4fc3ff7ba758b203853174ff6ec461/tools/surfaces-science.js#L17) computes normals, area Jacobian and curvature, with analytic surfaces, refinement assertions and deliberately broken controls. Its bounded science and statistics checks passed here. These are useful validation patterns for masked tifxyz grids, not a papyrus solver. The existing Metal kernel solves a different problem and was not run here.

**Sourced fact from code inspection.** [Undeciphered-Texts' router](https://github.com/ChaseHendrick/Undeciphered-Texts/blob/80262d358e9bee2e9ad6af7b03e309e83a1be982/engine/neural_router_v2.py) separates selection, calibration and a frozen audit, and supports abstention. Its scheduler bounds work. These patterns transfer; cipher weights, constants and symbol alignment do not.

**Access and evidence scope.** Later approved requests read the base-v8in README/config pinned to `d89166b` and public S3 meshes/surface metadata. The broader model and dataset inventory was not revalidated by that check. The existing Scrolls training inventory remains the evidence that only PHerc1447 w058/w060 have public labels in its inventoried release. Network additions were saved to the environment draft; saving the draft does not change the running instance. Weight downloads and validation are reported separately when completed.

## Implemented locally and research directions

The small `kit surfacefix` implementation compares pre-rendered candidate offsets through the existing reader. It writes a new surface copy, retains uncertain regions and records controls and inputs. It is a consistency-selection layer, not a replacement for Lasagna or proof of a better sheet. See [the workflow and limits](../surfacefix.md).

**Untested idea, highest priority for the automatic correction goal.** Compare official snapping outputs and bounded normal-offset candidates on the same physical patch and one shared label set. Require topology non-regression, matched-stride controls and a frozen independent-surface audit. Validate the combined rerender, not only separate candidate maps.

**Untested idea, low compute and direct demand.** Extend provenance with authoritative source frame, mesh revision, transform and render scale checks before inference. This could prevent comparing misregistered renders as if their model scores were comparable.

**Untested idea, substantial research value.** Build a human-reviewed hard-region benchmark with explicit positive, confirmed negative and unknown masks. Use calibrated abstention to choose which regions need annotation. Repeated agreement between models cannot supply the missing independent truth.

**Untested idea, training extension.** Distill a teacher only on regions with independently verified geometry and label identity, while holding an independent sheet out. This differs from trusting a dense teacher everywhere, but remains untested and requires a GPU budget decision.

No groundbreaking result or worldwide novelty is established. The implementation is a testable starting point; real-scroll validation is the next evidence gate.
