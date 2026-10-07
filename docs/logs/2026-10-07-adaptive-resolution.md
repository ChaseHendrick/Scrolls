# Adaptive geometry and reviewed PR integration

Recorded 7 October 2026. Existing cloud CPUs only. These experiments use published PHerc0841 geometry; they produced no ink maps or readings. The [frozen evidence and independent audit](../evidence/2026-10-07-adaptive-resolution/README.md) preserve both successful and failed checks.

## A useful result with a failed primary check

**Measurement:** a fixed geometric rule selected patches with about 52-54% fewer hypothetical bilinear primitives while retaining more local correspondence queries than uniform or count-matched random coarsening. **The original primary ag896 check failed** the frozen 95% retention requirement. ag405 was fetched and tested under a separately frozen follow-up rule; its success does not replace that failure.

| Trace | Experiment role | Native regular quads | Selected 2x2 blocks | Hypothetical primitive reduction | Adaptive retained | Uniform retained | Count-matched random retained |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| w00 | Original diagnostic | 36,237 | 6,304 | 52.19% | 116/120 | 104/120 | 110/120 |
| ag896 | Original primary, failed | 36,381 | 6,261 | 51.63% | 112/120 | 104/120 | 108/120 |
| ag405 | Separately frozen follow-up | 34,236 | 6,167 | 54.04% | 116/120 | 106/120 | 111/120 |

Each disjoint 2x2 native-cell block can become one coarse bilinear patch only if all nine vertices are valid, the four fine patches and coarse patch pass the existing Jacobian certificate, and the maximum same-parameter vertex discrepancy is at most 25 um. The count calculation is `3 * selected_blocks / native_regular_quads`. Boundary strips retain their native representation.

**Mathematical interpretation:** within each fine cell, the difference between coarse and native interpolation is bilinear. Its vector is a convex combination of its four corner differences, so its norm is bounded by their maximum. This bounds discrepancy between represented digital surfaces. It does not bound error relative to physical papyrus or establish global topology.

Each trace used 40 seeded complete blocks, a nonvertex UV point and offsets of 0 and +/-40 um along the native normal, making 120 queries. Native geometry retained all queries under the unchanged 50 um distance limit. Selection and controls used identical source queries and the same frozen closest-point helper. These are local patch comparisons, not searches across every possible rival sheet. All 40 on-surface queries per trace survived; failures arose in the offset queries.

The original rule hash is `ad7c395cbe658679fe84481fd5d190fe45ca622ac6817977b73dc897614e0cab`. The ag405 follow-up rule hash is `e149b3f78af6620aa07041d4c2530e1ed9ffd064de2ff59dc60ef7b4baf4bd9a`. The rules and source were fixed before their respective runs; the archived hashes provide integrity, not an independent timestamp proving preregistration.

## Controls and independent verification

All 384 fixed 17x17 dense interpolation audits passed. Synthetic controls covered a translated plane, an exactly bilinear nonplanar patch, a bowed center that must be rejected, a missing vertex and a saddle whose zero approximation error still requires nearest-point abstention. Approximation error cannot replace ambiguity checks.

A separate agent verified all 19 source artifact hashes and 16 frozen input entries, independently rebuilt selection and primitive counts, and replayed all 360 queries exactly. It also checked 300 synthetic patches and 120 additional real patches against the interpolation bound. Query replay reused the frozen closest-point helper, so it is not an independent proof of that helper. The [audit](../evidence/2026-10-07-adaptive-resolution/independent-review/adaptive-independent-review.md) found no defect within this limited scope.

The original runs took 9.27 seconds for w00/ag896 and 4.34 seconds for ag405, each on one CPU. The independent audit took 12.97 seconds. These are audit costs, not measured processing savings. The ag405 fetch was 553,406 bytes of public XYZ/meta files; its receipt records official URLs and hashes. Raw geometry stays outside Git.

## What this suggests

**Interpretation:** geometry-aware selection can improve the local coverage tradeoff over blanket spacing. A 25 um approximation allowance can consume more than the 10 um margin of a query already 40 um from the surface. That explains why a small representation error alone does not guarantee retention under a 50 um limit. A separately frozen margin-aware follow-up can test a tighter error budget without erasing the original failure.

**Limits:** no mesh was exported. Counts omit conformity, hanging-edge transitions and stitching. No measured flattening speedup, face-count saving in a valid mesh, global self-intersection result or improved ink recovery follows. All traces come from one CT acquisition; w00/ag896 overlap, and this study does not independently establish ag405's material independence. Queries cluster within 40 blocks, so no broad statistical claim follows.

Adaptive meshing and convex interpolation bounds are established ideas. This is a new local empirical result in this repository, with worldwide novelty unestablished. Relevant precursors and implementation opportunities are the [UFSM assessment](2026-10-07-ufsm-review.md) and [villa coarse-support review](2026-10-07-coarse-support-mask.md). The next production gate is a conforming mesh and global geometry audit, followed by an official render/reader comparison on common supervised pixels.

## Separately frozen distance-margin follow-up

**Measurement, failed combined endpoint:** a new rule limited representation discrepancy to 9 um, leaving a 1 um margin for queries 40 um from native geometry under the 50 um distance limit. ag896 remained the primary trace. The new fixed query sets were disjoint from the earlier experiment, so this is a fresh test rather than a paired repair of the previous failures. No threshold was adjusted after this follow-up's results.

| Trace | Adaptive retained / native eligible | Hypothetical primitive reduction | Uniform retained | Count-matched random retained | Combined >=20% reduction and >=95% retention |
| --- | ---: | ---: | ---: | ---: | --- |
| ag896, primary | 120/120 | 15.56% | 103/120 | 117/120 | Fail: count reduction |
| w00 | 118/118 | 15.91% | 95/118 | 114/118 | Fail: count reduction |
| ag405 | 120/120 | 18.51% | 105/120 | 117/120 | Fail: count reduction |

w00 had two unresolved native queries from one block, one on-surface and one at +40 um. Adaptive geometry kept those abstentions. It therefore retained every baseline-eligible query, but did not accept every generated query. For +/-40 um offsets alone the accepted counts were 80/80, 79/80 and 80/80 for ag896, w00 and ag405, respectively. Uniform and random modes accepted the two originally unresolved w00 queries; their total acceptance and baseline retention are different quantities.

**Interpretation:** a known native point at distance 40 um has a coarse counterpart within 49 um by the triangle inequality. That supplies an in-radius feasible point; it does not establish a unique closest point. The measured result supports this distance-margin argument while exposing its cost: every trace failed the frozen 20% primitive-reduction requirement. Runtime was 14.67 seconds on one CPU, with 72.4 MB peak RSS; no inference ran. The [separate archive](../evidence/2026-10-07-adaptive-margin/README.md) preserves the new rule, controls, results, input/source hashes and independent audit. The original evidence is unchanged.

## Review fixes integrated with the experiments

The [merge review archive](../evidence/2026-10-07-merge-review/README.md) records reviewed heads, passing checks and merges for PRs #6 through #18, including all Grok branches. The review corrected tied-rank scoring, hole-crossing geometry derivatives, invalid significance labels, fixed-model depth controls, sign-flipped null interpretation, unsafe inline viewer JSON and fresh-run shell failures. Historical numerical records remain preserved with explicit qualifications; source repairs do not imply new inference runs.

The combined repository passed 185 tests. Another 39 experiment tests passed across six directories; CI now executes these directories separately with numerical dependencies installed. `kit phantom`, `kit view` and the experimental `kit fibertensor` command coexist with `kit surfacefix`. Grok subsequently supplied [Mac CPU fibre-reader results](2026-10-07-grok-laneD.md): forward AUC 0.4726, 0.4223 and 0.5018 on the three reported train/test pairs. This review checked the reported records and script dispatch; it did not rerun those inferences. The tested learner did not improve on the baselines, and the log now avoids rejecting the entire feature family from that null result.

No paid compute, GPU training, upstream posting or submission was performed. The [Progress Prize draft](../contrib/progress-prize-2026-10-draft.md) remains attributed to Chase Hendrick and unsubmitted.
