# A tighter distance budget preserves eligibility but misses the saving target

The frozen 9-micrometer follow-up preserved every baseline-eligible local query on all
three traces, including the previously failing ag896 trace. However, hypothetical patch
primitive reduction was only 15.56-18.51%, below the frozen 20% requirement on every trace.
**The combined saving/retention hypothesis fails.** No thresholds or seeds were changed
after readout, and the prior 25-micrometer study and its failure remain preserved.

| Trace | Role | Selected blocks | Hypothetical primitive reduction | Adaptive retains baseline eligible | Uniform2 retains baseline eligible | Same-count random retains baseline eligible | All +/-40 micrometer queries accepted |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| ag896 | Primary, previously failed trace | 1887 | 15.56% | 120/120 | 103/120 | 117/120 | Yes: 80/80 |
| w00 | Secondary, same sheet as ag896 | 1922 | 15.91% | 118/118 | 95/118 | 114/118 | No: 79/80 |
| ag405 | Secondary, separate published surface | 2112 | 18.51% | 120/120 | 105/120 | 117/120 | Yes: 80/80 |

The w00 exception is an existing unresolved native correspondence at +40 micrometers;
the same block also had an unresolved on-surface query. Adaptive selection retained both
abstentions. Thus 100% retention of eligible native queries does not mean all query points
were accepted. Uniform/random coarsening accepted those two points, but that is not
evidence that their ambiguity was scientifically resolved.

## Frozen rule and the distance argument

Rule SHA256: `563513c0b47acac2698c1d128813ea30b55847c5f7e6ef2e78d7326f504a544d`.
The code, snapshotted geometry helper and all twelve XYZ/meta inputs were hashed before
results. Parent specified the 9-micrometer limit a priori after the earlier 25-micrometer
experiment. Fresh fixed query/random/dense seeds are 7348021 / 490127 / 188041. This is
a prospectively frozen follow-up on already studied surfaces, not an untouched-data
validation or a new independent CT scan.

Each disjoint 2x2 fine-cell block must have nine valid vertices, four certified regular
fine quads, one certified regular coarse quad, and maximum same-UV vertex discrepancy
of at most 9 micrometers. Within each fine cell, coarse-minus-native interpolation is
bilinear, so the norm is bounded by the largest corner discrepancy. For a query generated
40 micrometers from a native point, its distance to that point's corresponding coarse
point is at most 40+9=49 micrometers. Hence a feasible coarse surface point remains inside
the unchanged 50-micrometer limit, with one micrometer of numerical margin. This argument
bounds geometric distance, not uniqueness, sheet identity or the native mesh's physical
accuracy. The existing certified closest-point/ambiguity checks remain necessary.

Each trace used 40 seeded complete blocks and three fixed local queries per block:
on-surface and +/-40 micrometers along the native local normal, at nonvertex UV positions.
Modes share the same points and frozen 50-micrometer correspondence bar. Unselected
blocks retain native representation. The random mode uses exactly the same selected
block count as adaptive selection. Queries check local native/coarse patches only;
remote sheets and whole-surface competitors were not evaluated.

All 384 independent 17x17 interpolation audits satisfied the corner bound. All five
controls passed: translation-invariant plane, exact nonplanar bilinear patch, a zero-error
saddle that still correctly abstains on nonunique correspondence, a bowed center excluded
by its 93.66-micrometer error, and a hole excluded by missing support. The saddle and w00
unresolved cases directly demonstrate the limitation of a distance-only guarantee.

## Practical conclusion and limits

The result supports a real conservative distance-margin tradeoff: a tighter representation
budget removes the prior local eligibility loss and still outperforms count-matched random
selection. It does not meet the proposed 20% primitive-saving target. A useful future
experiment could allocate error from each query's actual certified distance margin, with
separate uniqueness and topology guards, rather than using one global worst-case offset.
That experiment has not been run or substituted into these results.

The complete run took 14.67 seconds on one CPU with 72.4 MB peak RSS. No new downloads,
training, GPU, CT reads, labels, model outputs or reader maps were used. Audit cost does
not measure flattening speed or production savings. Primitive counts ignore hanging-edge
conformity and transition strips; no mesh was exported. No global manifold, collision,
material-identity, ink-preservation or runtime claim follows. All traces share one CT
acquisition, w00/ag896 trace the same sheet, and the three queries per block are correlated;
no statistical independence, confidence interval or worldwide method novelty is claimed.

`result.json` contains every query and failed endpoint. `SHA256SUMS` covers code, rules,
results, report, frozen helper and input files through their read-only links. On-disk
verification also checked that all previous adaptive-resolution manifest entries remain
unchanged. The source snapshot is pinned to the existing helper used in that prior study;
only its equivalent local NumPy import was substituted before either experiment. No
repository files, thresholds or prior evidence were edited.
