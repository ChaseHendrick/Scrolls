# Preregistration: crowd-trace merger on planted slips (PHerc0139, 24 October 2026)

Written and committed before any benchmark number of `kit crowdmerge` exists. Public data only (PHerc0139 scan 20250728140407, not prize-eligible), CPU only, synthetic crowds built from published hand-traced windings. Nothing here touches ink.

## Question

Given several traces of the same sheet, some of which slipped onto the touching neighbor sheet at different places, does a per-vertex vote along the surface normal give one surface that stays on the right sheet, and flag each trace's slipped parts?

## Bench (`python -m kit crowdmerge bench`)

- References: `kit hopbench refs` (PHerc0139 windings w023 to w040, manifest as built by `kit/sheetrefs.py`).
- Sites: for each chain-neighbor pair (A, B) that is not a copy of one sheet (median offset at least 8 voxels), up to 4 contact sites (|offset| at most 4 voxels) at least 8 mm apart, drawn with seed 20261024, as `kit hopbench` picks them. Window: an 8 mm square of A round the site, densified to about 2 voxels.
- Crowd: 7 traces of the window. Each is cropped to a random rectangle (each side 70 to 100 % of the window), resampled on a stride-2 grid with a random phase, and given a smooth normal jitter (Gaussian field, standard deviation 0.5 voxels). In the main crowd, 3 of the 7 traces slip: each moves onto B through its own random contact point of the window, along a random direction, with a ramp 16 voxels wide (the ramp plant of `kit.sheetgap.plant`, generalized to any direction); points with no match on B are dropped.
- Truth: each crowd point's offset from A (the planted weight times A's offset to B). Slipped means more than 6 voxels from A; on sheet means under 2 voxels; points between are not scored for flags. A consensus point is off sheet when its matched offset from A is more than 4 voxels.
- Arms: `merge` (the vote); `largest` (the crowd trace with the most points, the usual pick); `mean` (per canvas vertex, the mean offset of the nearest layer of every trace present, naive averaging).
- Controls: `clean` (the same crowds with no trace slipping) and `sham` (5 of 7 traces slip, all through the same contact point and direction, so the majority is wrong).

## Split

Development (parameters may change): sites with A in w023 to w031. Report (run once, after the parameters are frozen in a committed amendment naming the commit): sites with A in w032 to w040.

## Bars, on the report split

PASS needs all of:

1. `merge` off-sheet share at most 0.02 and at most a quarter of `largest`'s.
2. Slip flags over all crowd points: recall at least 0.90 and precision at least 0.90.
3. `clean` control: `merge` off-sheet share at most 0.01, and at most 0.01 of on-sheet crowd points flagged.
4. `sham` control (the check can fail): `merge` off-sheet share at least half of the slipped share of the majority traces' points. If the vote does not follow a wrong majority, something other than the crowd is steering it, and the run is void.

Coverage of the consensus (its area on A over the window's area) is reported, with no bar.

## Not tested

Real crowds of independent tracers, other scans and resolutions, crowds where most traces miss the region, slips two sheets out. Johannes's spiralfiteval scores spiral fits, not meshes, so it does not apply to this tool's output; the slip share here is the same kind of measure on a surface.
