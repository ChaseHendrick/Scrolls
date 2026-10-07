# Independent review of the 9-micrometer margin follow-up

The saved numerical results and distance argument are correct within the stated
local diagnostic scope. No concrete implementation defect was found. The primary
combined hypothesis fails: ag896 preserves 120/120 baseline-eligible queries but
achieves only 15.56% hypothetical primitive reduction, below the frozen 20% bar.
The secondary traces also fail that reduction endpoint.

## Independent checks

- Verified all 19 original manifest entries and all 14 frozen input-hash entries.
  The source manifest SHA256 is
  `13c951a0adb65235894baf35eac42df257ed9bb02b0fe3018d21e8f3d8e819b6`.
- Verified the frozen rule digest and its binding in the saved result.
- Independently rebuilt interpolation, corner-normal regularity, all complete
  2x2 blocks, the selected counts, random masks and primitive accounting from the
  TIFF inputs. The geometry snapshot is identical to the preceding experiment.
- Exactly reproduced all 360 saved query results with the frozen closest-point
  helper. This replay is not an independent proof of that helper.
- Verified every mode's baseline-eligible denominator, retained count and total
  eligible count. Confirmed all saved combined-hypothesis flags are false.
- Passed 300 synthetic random-patch bounds and 120 additional selected real-patch
  random-UV checks with independently implemented interpolation. Replayed all
  five frozen controls successfully.

The independent review ran in 13.91 seconds on one CPU. Neither the original
evidence nor the preceding experiment's archive was changed.

| Trace | Regular native quads | Selected blocks | Hypothetical reduction | Adaptive retains baseline eligible | Uniform retains baseline eligible | Random retains baseline eligible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ag896 | 36381 | 1887 | 15.5603% | 120/120 | 103/120 | 117/120 |
| w00 | 36237 | 1922 | 15.9119% | 118/118 | 95/118 | 114/118 |
| ag405 | 34236 | 2112 | 18.5068% | 120/120 | 105/120 | 117/120 |

The w00 native on-surface and +40-micrometer queries in block 884, native row 32,
column 158, are unresolved. Adaptive representation retains those abstentions.
Uniform and random coarsening accept those two points, producing total-eligible
counts of 97 and 116 respectively, while retained-baseline counts are 95 and 114.
The distinction is correctly represented in the saved data and source report.
Neither coarsening mode establishes that the original uncertainty was resolved.

## Distance guarantee and remaining limits

On each fine cell, coarse-minus-fine interpolation is bilinear. Its vector values
are convex combinations of the four corner differences, so the largest corner
norm bounds the entire cell. A selected block therefore places corresponding
fine and coarse points at most 9 micrometers apart in the represented digital
geometry. For a source query 40 micrometers from a fine point, the triangle
inequality gives a feasible coarse point at most 49 micrometers away. This is
inside the unchanged 50-micrometer distance bar.

This proves existence of a nearby coarse point. It does not prove a unique
closest point, a match on the correct sheet, global topology, collision freedom,
or physical accuracy relative to papyrus. A sufficient uniqueness check may
still abstain. The saved saddle control and w00 native abstentions correctly
illustrate that limitation. The one-micrometer mathematical margin is not an
independent interval-arithmetic certification of every floating-point operation.

Primitive reduction remains `3 * selected_blocks / native_regular_quads`, before
conformity, hanging-edge and transition-strip costs. No mesh was exported and no
production runtime or ink-reader gain was measured.

## Reporting qualification

This is a prospectively frozen follow-up motivated by the failed 25-micrometer
study, using the same previously studied surfaces and different query seeds.
The new query blocks do not overlap the preceding study's query blocks. Thus the
source report's phrase that a tighter budget "removes the prior local eligibility
loss" should be understood as full eligible-query retention on the new fixed
queries. The experiment is not a paired causal demonstration that every earlier
failed query was repaired. Do not replace the original failure with this result.

All three queries within each of 40 blocks are correlated, and the comparator
uses one random mask seed. Only local patches are checked. These results support
the reported ordering on the fixed query set, without statistical independence,
whole-mesh safety, physical independence, general superiority or worldwide
methodological novelty. Local rule hashes establish integrity, not externally
timestamped preregistration.

The receipt is `margin-independent-review.json`; its read-only reproduction
script is `margin_independent_audit.py`.
