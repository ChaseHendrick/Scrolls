# 2026-10-14: PHerc0139 segments: w035 is partial, and where it is missing w036 crosses w034

Chase Hendrick, 14 October 2026. The numbers below are measurements of the published PHerc0139 segments against the published umbilicus, made with `python -m kit stackcheck` ([`kit/stackcheck.py`](../../kit/stackcheck.py)). They use no CT, no model, no surface prediction and no ink map, and they can be checked from the public files with the commands at the end. A look at the CT at 12 places follows them. What any of it might mean is marked Interpretation (the claim labels of [AGENTS.md](../../AGENTS.md), hard rule 5).

## Segments, frame and runs

The segments are one per winding, inner to outer, from `PHerc0139/segments/` on the open-data bucket:

| Winding | Segment | Winding | Segment |
| --- | --- | --- | --- |
| w023 | `20260311000000-w023_202603112281` | w032 | `20260203000000-w032_2026020303` |
| w024 | `20260215000000-w024_2026021572` | w033 | `20260219000000-w033_2026021913` |
| w025 | `20250108000000-w025_2025010863` | w034 | `20260303000000-w034_2026030317` |
| w026 | `20250108000001-w026_2025010854` | w035 | `20260317000000-w035_2026031718` |
| w027 | `20250108000002-w027_2025010845` | w036 | `20260316000000-w036_2026031607` |
| w028 | `20250108000003-w028_2025010836` | w037 | `20260310000000-w037_2026031015` |
| w029 | `20250108000004-w029_2025010827` | w038 | `20260306000000-w038_2026030608` |
| w030 | `20250108000005-w030_2025010818` | w039 | `20260302000000-w039_2026030210` |
| w031 | `20260130000000-w031_2026013019` | w040 | `20250831000000-w040_2025083102` |

Frame and units. Positions are full-resolution voxels (x, y, z) of volume 20260102150214 (2.399 um), as in each segment's `on-20260102150214-2.399um.tifxyz`. Angles are degrees about the umbilicus `20260102150214-umbilicus-20260826112529.json` at the same z, atan2(y - y_u, x - x_u), 0 to 360. Distances are micrometres, along a ray from the umbilicus or along a vertex normal. Areas are summed vertex cell areas in cm².

Two runs:

- **Run A**: the 2.399 um copies of w033 to w037, every second grid row and column (`--stride 2 --upsample 1`, about 96 um between vertices), rays every degree on 102 planes from z 8,600 to 28,800 (`--plane-z 8600 28800 200`), and `--coincide-um 18.72` (2 voxels at 9.362 um). 1 min on one CPU core, 0.75 GB of memory at most.
- **Run B**: the 9.362 um copies of w023 to w040 (about 187 um between vertices). They are on volume 20250728140407, so they are mapped into 20260102150214 with the catalog's sample-level matrix (`--transform catalog:PHerc0139:20250728140407:20260102150214`); same planes and coincide distance. 2.5 min on one core, 1.7 GB.

Numbers are from run A where it covers them, with run B in square brackets. Vertex counts depend on the grid, so the text gives areas. A third run, run B with the tool's defaults (50 planes over the whole height, `--coincide-um 20`), flags the same checks on the same segments, except that w033's order conflicts fall under the 1 % share and two more missing runs (w034 to w039 and w034 to w040) reach it.

## What is wrong (measured)

- **w035 covers only part of its turn.** Along each grid line it spans a median 258 degrees, at most 297 [257, 296]. It runs from z 8,506 to 28,915, while w034 runs from 4,379 to 30,225. On each of the 102 planes there is a sector where w034 and w036 are crossed and w035 is not (the gap). The tool follows it as one sector from z 9,000 to 27,800 (95 planes): there it starts at 327 to 5 degrees and ends at 71 to 85 degrees (10th to 90th percentile over those planes, the same in run B), and it is 33 to 120 degrees wide, a median 98 [27 to 122, median 95]. These are the report's `gap_extent` for w035; its `per_plane` list gives each plane's sector.
- **In the gap, w036 lies near w034's radius instead of two windings out, by an amount that changes with height.** On the 7,427 rays [7,644] that cross w034 and w036 once each in the gap, w036 lies a median 17 um [18] outside w034 (quartiles 49 um inside to 107 um outside), and it is inside w034 on 42 % of them [41.5 %]. Where w035 is present (24,349 rays), w036 lies a median 242 um outside w034 and is inside it on 1.2 %. The median hides a swing with height (the report's `gap_by_height`, ten bands of about 2,000 voxels from z 8,600 up; run B within 10 um): -47, -7, +27, +65, +110, +80, -21, -96, -58 and +174 um (minus is inside w034). So at z 17,000 to 18,800 w036 lies about one pitch outside w034, where w035 would be, and at z 23,000 to 24,800 it lies 96 um inside w034 and only 26 um outside w033, while w033 and w034 keep 108 to 141 um apart in every band. At the heights and angles of the gap lie 9.11 cm² of w034 [9.03] and 7.46 cm² of w036 [7.22]; 41 % of that part of w034 is also on turn-overlap masks (see turn overlaps below). w033 and w037 lie a median 252 um [255] apart in the gap, against 561 um where w035 is present. The control in run B: every other pair four windings apart that lies wholly inside or wholly outside w035 (w023/w027 to w030/w034, and w036/w040) has a median spacing on the gap's rays 0.91 to 1.12 times its median where w035 is present (the report's `control_pairs`), against 0.46 for w033/w037.
- **Near the ends of w035 and w036, both are missing together.** On 716 rays [725] at the heights of w035 or w036, w034 and w037 are crossed and neither w035 nor w036 is (2.0 % of the rays crossing w034 and w037 there; the report's `missing_runs`): 399 at z 8,600 to 9,800 and 313 at z 27,800 to 28,800, over a wide range of angles, and 4 at 73 to 75 degrees between z 16,800 and 18,400, at the end of the gap. On those rays w034 and w037 lie a median 294 um [302] apart, against 402 um where all four are present. In run B, which also has w038 to w040, w035 to w037 are all missing between w034 and w038 on 433 more rays at the same heights, and w035 to w038 or w035 to w039 on 259 and 334 (under the 1 % share). These sectors are on the missing-sector masks too: 0.74 cm² of w034 and 0.71 cm² of w037 in run A.
- **Where w035 is present, it crosses w034 in small patches.** On 10.2 % of the 24,489 rays that cross both once [10.0 % of 24,361], w035 lies inside w034, by a median 32 um [31] (quartiles 13 to 67 um). On 6.8 % [6.7 %] it lies inside by more than 18.72 um, so about a third of those rays are within the distance at which two segments cannot be told apart. 79 % of the inverted rays [80 %] lie between 210 and 330 degrees, from z 8,800 to 28,400. Of the other adjacent pairs from w023 to w040, only w031/w032 is inverted on more than 0.5 % of rays (3.0 %, 1.4 % by more than 18.72 um, a median 17 um deep). Per vertex, 0.73 cm² of w035 [0.71] has w034 as the nearest segment along its normal on the outer side, a median 38 um away, in 211 separate patches [175]; 1.31 cm² of w036 [1.30] has w034 outside it the same way. Crossings of three windings occur too: w033 has w036 as its nearest inner segment on 0.36 cm² [0.29], w036 has w033 outside it on 0.58 cm² [0.49], w037 has w034 outside it on 0.47 cm² [0.41], and w034 has w037 inside it on 0.32 cm² [0.22].
- **Skipped windings.** 1.29 cm² of w034 [1.28] has w036 as the nearest segment along its outer normal, farther than 18.72 um but closer than half the local pitch (57 um, half of 113 um [114]), so no winding fits between; the median distance is 37 um. 75 % [75 %] of all w034 vertices with a skipped winding lie on its missing-sector mask. Seen from w036, 1.81 cm² [1.83] has w034 as its nearest inner segment the same way. Run B also flags skipped windings on w028, w031 to w033, w035, w037 and w038: beyond 18.72 um they cover 0.35 to 0.59 cm² each on w028, w031, w032, w035 and w038, and 1.34 and 1.51 cm² on w037 and w033. Off the turn-overlap masks that is 0.22 to 0.49 cm² each and 1.30 cm² each (the report's `beyond_coincide_off_turn_overlap`). On w028 all of it has w026 as the nearest inner segment (0.54 cm², a median 49 um away), and about half of it lies on the turn-overlap masks.
- **The ends of the stack.** In run B, w035, w036, w037 and w038 begin at z 8,570, 8,307, 8,002 and 7,778, while w034 and w039 reach down to 4,427 and 4,776. So from z 4,776 to 7,778 none of the four windings between w034 and w039 has a segment, and from 7,778 to 8,570 one to three of them have none. At the top, w035 to w039 end at z 28,869, 29,083, 29,222, 29,428 and 29,548, while w034 runs to 30,189 and w040 to 29,704. The 2.399 um copies of w034 to w037 in run A reach 36 to 68 voxels further at each end.

Example vertices to open in VC3D (run A; row and column on the segment's 2.399 um tifxyz grid):

| Defect | Segment, row, column | Voxel (x, y, z) | Angle | Nearest segments along the normal |
| --- | --- | --- | --- | --- |
| In the gap | w034, 434, 248 | 17115, 14541, 12837 | 13 | w036 1 um outside, w033 80 um inside |
| In the gap | w036, 542, 1016 | 18213, 11594, 18432 | 346 | w034 8 um inside, w037 99 um outside |
| w035 and w036 both missing | w034, 248, 1018 | 13358, 11833, 9204 | 237 | w037 311 um outside, w033 135 um inside |
| w035 inside w034 | w035, 844, 824 | 15162, 9192, 24556 | 315 | w034 50 um outside |
| w036 inside w034, in the gap | w036, 854, 1110 | 17834, 12866, 24543 | 21 | w034 80 um outside, w033 32 um inside |
| Skipped winding | w034, 472, 322 | 16038, 15479, 13682 | 51 | w036 31 um outside, w033 151 um inside |
| Skipped winding | w036, 530, 1102 | 18188, 13254, 18335 | 9 | w034 36 um inside, w037 54 um outside |

**Interpretation.** w034 and w036 cannot both be on their own sheets where they meet, and a missing w035 alone would not bring w033 and w037 closer: in the gap they are about two windings apart instead of four (252 against 561 um), while other pairs four windings apart keep their spacing on the same rays. So in this sector some of w033 to w037 leave their sheets, by about two windings in all at the median, and by three where w036 lies inside w033 or w034 outside w037. Since w036's place against w034 swings with height while w033 and w034 keep their spacing, it is not the same displacement at every height.

## A look at the CT (Interpretation, 12 places)

We looked at the 2.399 um CT of volume 20260102150214 at 12 places: six vertices of the defects above (E1 to E6), four more spread over the gap (G1 to G4) and two where w035 is present (C1 and C2). At each we used one z slice 1.5 mm across, turned so that the ray from the umbilicus runs outward, and one radial cut along that ray over z ±250 um (24 cuts), plus polar unwraps of two z slices (z 14,856 and 19,500) across the end of the gap at 55 to 95 degrees. Layers were counted by eye. To find the distance of a trace from papyrus, we measured how far it lies from material above an Otsu threshold. At the controls no trace is more than 41 um (17 voxels) from it.

| Place | Voxel (x, y, z), or z | Angle | What the CT shows |
| --- | --- | --- | --- |
| E1, in the gap | 16642, 14927, 14856 | 35 | One dense band between w033 and w037; w036 lies 19 um outside w034 in the same band |
| E2, in the gap | 18358, 12754, 17995 | 360 | Three layers between w033 and w037, separated by air; one carries only w033's doubly traced end; w034's doubly traced end and w036 lie on one layer, 24 um apart |
| E3, w035 inside w034 | 13750, 9249, 21500 | 267 | w034 lies on w035's layer, near its outer face, 58 um out; the layer just outside w037 carries no trace |
| E4, w036 inside w034 | 17611, 13846, 10437 | 355 | One dense bundle about 190 um thick holds w034 and w036; w037 lies in air, 38 um short of the next layer |
| E5, skipped winding | 17427, 13862, 13741 | 4 | w036 lies 29 um outside w034 on the same layer; two or three layer steps from w033 to w037, not four |
| E6, skipped winding | 17029, 14405, 14109 | 19 | w034 and w036 lie on one layer, 31 um apart |
| G1, gap | z 11,000 | 50 | Four traces on two layers: w034, w036 and w037 on one |
| G2, gap | z 19,500 | 15 | w034 crosses layers in the slice onto w036's layer (36 um apart); two layers between w033 and w036 carry no trace |
| G3, gap | z 23,000 | 60 | w034 and w036 cross each other, partly through air (w034 up to 72 um from papyrus); w037 crosses a layer through air (up to 76 um) |
| G4, gap | z 26,800 | 35 | w034 lies on w037's layer, 7 um apart; two layers carry only w033's doubly traced end; w036 runs up to 50 um into air |
| C1, w035 present | z 13,000 | 150 | Each of the five on the inner face of its own layer, three layers between w033 and w037 |
| C2, w035 present | z 22,000 | 180 | All five on papyrus; w036 and w037 in one compressed bundle, 36 um apart |

**Interpretation.** Where w035 is present, each segment lies on its own papyrus layer, although layers can be pressed together there too (C2). In the gap, w036 never has a layer of its own: at seven of the nine gap places (E1, E2, E4, E5, E6, G1, G2) it lies on w034's layer, or on that of w034's doubly traced end (E2), and at the other two (G3, G4) it runs partly through air. At three of the four places where the layers are separate enough to count (E2, G2 and G4), a layer between w033 and w037 carries no trace of its own, while w034 or its doubly traced end sits on the layer of w036 (E2, G2) or of w037 (G4); at G2, w034 crosses layers within the slice, and at the fourth (G3), w037 runs through air. In the two unwraps, the layer that carries w035 beside the gap runs on into the gap, where it carries only the doubly traced ends of w036 and w037. So no single segment leaves its sheet: in the middle of the gap it is most often w034 (three places), near the end of the gap the turn ends of w036 and w037, and at G3 w037. At the other five gap places (E1, E4, E5, E6, G1) the layers are pressed into dense bands, with 0 to 2 boundaries between w033 and w037 against three layers at C1, and at this resolution the CT does not show whether those layers are merged in the scan or skipped by the traces. Each place is one slice, thin strands may be split plies rather than layers, the ray is oblique to the layers at E4 and E5, the traces are drawn between vertices 48 um apart (so offsets of about 12 um are within their accuracy), and the unwraps cover one end of the gap at two heights.

## Turn overlaps: a note on using these segments (run B)

Each of w023 to w034 is traced past a full turn about the umbilicus, by a median of 28 to 48 degrees per grid line (66 for w026). The doubly traced ends lie between about 272 and 53 degrees, over nearly the whole height. Measured along the normal from each doubly traced end to the next segment: for w023 to w031, 53 to 75 % of the end lies within 18.72 um of the next segment, a median 3 to 17 um from it; for w032 and w033 less than half does (44 and 39 %), and the rest lies a median 52 and 60 um from it, about half the 114 um pitch. w034's end lies mostly in the gap, so only 23 % of it has w035 at the same height and angle. w036 to w040 also run past a full turn, by a median of 4 to 30 degrees per line, between about 48 and 94 degrees.

**Interpretation.** Where a doubly traced end lies on the next winding's sheet, as most of each end of w023 to w031 does, the surface is right and only its winding number is wrong. Much of the ends of w032 and w033 lies between sheets, and on w028 the skipped windings above may show part of w026 off its sheet rather than a missing w027. Either way, a point labelled with the segment it lies on gets the previous winding's number on a doubly traced end, one turn too low, unless that end and the next segment's vertices beside it are left out.

## What to drop before a spiral fit or a winding count

`--flags FLAGS.npz` writes one boolean mask per segment and check, on the segment's own tifxyz grid (repeated back to the full grid when run with `--stride`), under the keys `NAME/order`, `NAME/missing_sector`, `NAME/skipped_winding`, `NAME/turn_overlap`, `NAME/coincident`, `NAME/stack_end` and their union `NAME/any`, with `names` and `voxel_um`. Before using these segments for relative windings, a spiral fit or any winding count, drop:

- `missing_sector`: the segments either side of a missing sector or a missing run, where the segments between them have no vertex within 1.5 grid steps of the same height and arc, inside those segments' z extent (here w034 and w036 around the gap, and w034 with w037, or w038 in run B, near the ends of w035 and w036)
- `stack_end`: the segments either side at the heights where a winding between them has no segment at all (here w034 below z 8,570 and above 28,869 in run B, with the next segment out that has a vertex there)
- `order`: vertices whose nearest segment along the normal is a lower winding outside or a higher one inside
- `skipped_winding`: vertices with a segment two or more windings away within half the local pitch
- `turn_overlap`: each doubly traced end, plus the next segment's vertices at the same height and angle
- `coincident`: vertices with another segment within `--coincide-um` along the normal, where the two cannot be told apart

A count of windings between two points with a missing sector or a stack end between them comes out short, so the first two masks matter even where every segment is on its own sheet. In run B the union covers 11 to 56 % of each segment's vertices (56 % of w034, 31 % of w036, 20 % of w035), most of it turn overlaps and coincident vertices, and on w034 also missing sectors and stack ends.

## Usage

```bash
python -m pip install numpy tifffile scipy
python -m kit stackcheck SEG_INNER ... SEG_OUTER --umbilicus UMBILICUS.json \
    [--transform SPEC] [--stride N] [--planes N | --plane-z Z0 Z1 STEP] \
    [--out work/stackcheck/REPORT.json] [--flags work/stackcheck/FLAGS.npz] [--json] [--verbose]
python -m unittest tests.test_stackcheck      # synthetic stacks: a clean spiral passes, each planted defect is flagged
```

- Segments are given inner to outer, one per winding, as local tifxyz folders or as `https://` or `s3://` folders on the open-data bucket (fetched once into `--cache`, by default `work/stackcheck/cache`). Name one `NAME=PATH` (a name has no `/`, `\` or `:`); otherwise its name is the nearest folder above the path that is neither `mesh` nor a `.tifxyz` folder.
- The umbilicus is a local file or a URL in the published format (`control_points` with x, y and z, and `metadata.voxelsize_um`). It must be in the same volume as the segments, or `--transform` maps the segments into its volume: a JSON file with a 3x4 or 4x4 matrix, or `catalog:SAMPLE:FROM_VOLUME:TO_VOLUME` for the catalog's sample-level matrix (from `--catalog`, by default the bucket's `metadata.json`). The volume ids in the folder names (`-on-VOLUME-`), the transform and the umbilicus's `metadata.volume` must agree when they are known, and a folder name's voxel size that differs from the umbilicus's without a transform is an error.
- Settings: `--ray-step-deg` (1), `--planes` (50) or `--plane-z`, `--max-normal-um` (600, how far along a normal a neighbour is looked for), `--coincide-um` (20), `--skip-frac` (0.5 of the local pitch), `--upsample` (2, neighbours made denser for the normal search), `--min-count` (10) and `--min-share` (0.01). A check is flagged when what it finds reaches both the count and the share; the ray order check counts only rays inverted by more than `--coincide-um` for that.
- Memory: every segment's denser grid is held at once. At the defaults (`--stride 1 --upsample 2`) one full 2.399 um copy of a PHerc0139 winding needs about 2 GB, so use `--stride 2 --upsample 1` for such copies, as in run A.
- Output: a text summary (or the report with `--json`), the report JSON with `--out` (settings, frame, per segment and per check, with example vertices), and the masks with `--flags`. Keep both under `work/`, which git ignores. The exit status is 0 when every check looked and nothing is flagged, 1 when something is flagged or a check had nothing to look at (listed under `summary.not_checked`), and 2 when the run could not be made (bad input or an unexpected error).
- The `kit/stackcheck.py` docstring has the full description of each check.

## Reproducing this note

Run A (downloads about 100 MB of tifxyz):

```bash
B=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139
U=$B/representations/umbilicus/20260102150214-umbilicus-20260826112529.json
S=""
for id in 20260219000000-w033_2026021913 20260303000000-w034_2026030317 20260317000000-w035_2026031718 \
          20260316000000-w036_2026031607 20260310000000-w037_2026031015; do
  w=${id#*-}; w=${w%%_*}
  S="$S $w=$B/segments/$id/mesh/${id%%-*}-on-20260102150214-2.399um.tifxyz"
done
python -m kit stackcheck $S --umbilicus $U --stride 2 --upsample 1 \
    --plane-z 8600 28800 200 --coincide-um 18.72 \
    --out work/stackcheck/w033-w037.json --flags work/stackcheck/w033-w037-flags.npz
```

Run B (about 25 MB, with `B` and `U` as above): the 18 segments of the table, their 9.362 um copies mapped with the catalog's matrix:

```bash
S=""
for id in 20260311000000-w023_202603112281 20260215000000-w024_2026021572 20250108000000-w025_2025010863 \
          20250108000001-w026_2025010854 20250108000002-w027_2025010845 20250108000003-w028_2025010836 \
          20250108000004-w029_2025010827 20250108000005-w030_2025010818 20260130000000-w031_2026013019 \
          20260203000000-w032_2026020303 20260219000000-w033_2026021913 20260303000000-w034_2026030317 \
          20260317000000-w035_2026031718 20260316000000-w036_2026031607 20260310000000-w037_2026031015 \
          20260306000000-w038_2026030608 20260302000000-w039_2026030210 20250831000000-w040_2025083102; do
  w=${id#*-}; w=${w%%_*}
  S="$S $w=$B/segments/$id/mesh/${id%%-*}-on-20250728140407-9.362um.tifxyz"
done
python -m kit stackcheck $S --umbilicus $U --transform catalog:PHerc0139:20250728140407:20260102150214 \
    --plane-z 8600 28800 200 --coincide-um 18.72 \
    --out work/stackcheck/w023-w040.json --flags work/stackcheck/w023-w040-flags.npz
```

Both were run with these commands on 14 October 2026 and gave the same reports and masks as runs on local copies of the same files.

## Limits

- Geometry first. The checks say where segments disagree with each other and with their winding order about the umbilicus; they cannot say which segment left its sheet. The CT look above is by eye, at 12 places.
- The ray checks use only rays that cross both segments of a pair once, so rays through seams and doubly traced ends are left out. Neighbours along a normal are looked for up to `--max-normal-um`, among the other segments' vertices at about the same height and angle; on a sheet that is strongly sheared or far from round about the umbilicus the search finds fewer, and a segment with a neighbour for under half its vertices is listed under `summary.not_checked`.
- Where two segments lie within `--coincide-um` of each other they cannot be told apart, so the order check leaves those vertices out, and the skipped-winding counts above give the part beyond that distance.
- The doubly traced end is found per grid line, as the part past a full turn. It does not reach out to neighbouring lines, so its start can be a little narrower than a mask with a tolerance.
- A gap's width is the angle from its first ray to its last.
- Run A uses every second grid row and column, so its z extents are a little short of the full grid's and its vertex counts are of the strided grid; its masks are repeated back to the full grid.
- Angles depend on the umbilicus, which is a published line, not a measurement of this run.
- The tool has been run on real data only for PHerc0139 w023 to w040; its tests use synthetic spirals with planted defects.
