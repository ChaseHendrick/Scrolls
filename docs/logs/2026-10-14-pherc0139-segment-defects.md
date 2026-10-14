# 2026-10-14: PHerc0139 segments: w035 is partial, and where it is missing w036 crosses w034

Chase Hendrick, 14 October 2026. Every number below is a measurement of the published PHerc0139 segments against the published umbilicus, made with `python -m kit stackcheck` ([`kit/stackcheck.py`](../../kit/stackcheck.py)). No CT was opened, and no model, surface prediction or ink map was used. The measurements can be checked from the public files with the commands at the end; what they might mean is marked Interpretation ([NOVELTY.md](../NOVELTY.md)).

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

- **Run A**: the 2.399 um copies of w033 to w037, every second grid row and column (`--stride 2 --upsample 1`, about 96 um between vertices), rays every degree on 102 planes from z 8,600 to 28,800 (`--plane-z 8600 28800 200`), and `--coincide-um 18.72` (2 voxels at 9.362 um). 52 s on one CPU core.
- **Run B**: the 9.362 um copies of w023 to w040 (about 187 um between vertices). They are on volume 20250728140407, so they are mapped into 20260102150214 with the catalog's sample-level matrix (`--transform catalog:PHerc0139:20250728140407:20260102150214`); same planes and coincide distance. 2.5 min on one core.

Numbers are from run A where it covers them, with run B in square brackets. Vertex counts depend on the grid, so the text gives areas. A third run, run B with the tool's defaults (50 planes over the whole height, `--coincide-um 20`), flags the same checks on the same segments, except that w033's order conflicts fall under the 1 % share.

## What is wrong (measured)

- **w035 covers only part of its turn.** Along each grid line it spans a median 258 degrees, at most 297 [257, 296]. It runs from z 8,506 to 28,915, while w034 runs from 4,379 to 30,225. On every plane from z 9,400 to 27,600 there is a sector where w034 and w036 are crossed and w035 is not (the gap). It starts at 326 to 6 degrees and ends at 68 to 87 degrees [89], and it is 64 to 121 degrees wide [65 to 123]. Below z 9,400 and above 27,600 the sector without w035 widens toward w035's ends (at z 9,000 in run B it runs from 156 to 89 degrees, and at 28,000 from 293 to 77), but w036 is missing over most of it too, so the part where both neighbours are present narrows.
- **In the gap, w036 sits at w034's radius instead of two windings out.** On the 7,427 rays [7,644] that cross w034 and w036 once each in the gap, w036 lies a median 17 um [18] outside w034 (quartiles 49 um inside to 107 um outside), and it is inside w034 on 42 % of them [41.5 %]. Where w035 is present (24,349 rays), w036 lies a median 242 um outside w034 and is inside it on 1.2 %. At the heights and angles of the gap lie 9.16 cm² of w034 [9.09] and 7.50 cm² of w036 [7.24]; 41 % of that part of w034 is also on turn-overlap masks (see turn overlaps below). w033 and w037 lie a median 252 um [255] apart in the gap, against 561 um where w035 is present.
- **Where w035 is present, it crosses w034 in small patches.** On 10.2 % of the 24,489 rays that cross both once [10.0 % of 24,361], w035 lies inside w034, by a median 32 um [31] (quartiles 13 to 67 um). 79 % of those rays [80 %] lie between 210 and 330 degrees, from z 8,800 to 28,400. Of the other adjacent pairs from w023 to w040, only w031/w032 is inverted on more than 0.5 % of rays (3.0 %, a median 17 um deep). Per vertex, 0.73 cm² of w035 [0.71] has w034 as the nearest segment along its normal on the outer side, a median 38 um away, in 211 separate patches [175]; 1.31 cm² of w036 [1.30] has w034 outside it the same way.
- **Skipped windings.** 1.29 cm² of w034 [1.28] has w036 as the nearest segment along its outer normal, farther than 18.72 um but closer than half the local pitch (57 um, half of 113 um [114]), so no winding fits between; the median distance is 37 um. 74 % [72 %] of all w034 vertices with a skipped winding lie in the gap. Seen from w036, 1.81 cm² [1.82] has w034 as its nearest inner segment the same way. Run B also flags skipped windings on w028, w031 to w033, w035, w037 and w038: beyond 18.72 um they cover 0.34 to 0.59 cm² each on w028, w031, w032, w035 and w038, and 1.34 and 1.51 cm² on w037 and w033.
- **The ends of the stack.** In run B, w035, w036, w037 and w038 begin at z 8,570, 8,307, 8,002 and 7,778, while w034 and w039 reach down to 4,427 and 4,776. So from z 4,776 to 7,778 none of the four windings between w034 and w039 has a segment, and from 7,778 to 8,570 one to three of them have none. At the top, w035 to w039 end at z 28,869, 29,083, 29,222, 29,428 and 29,548, while w034 runs to 30,189 and w040 to 29,704. The 2.399 um copies of w034 to w037 in run A reach 36 to 68 voxels further at each end.

Example vertices to open in VC3D (run A; row and column on the segment's 2.399 um tifxyz grid):

| Defect | Segment, row, column | Voxel (x, y, z) | Angle | Nearest segments along the normal |
| --- | --- | --- | --- | --- |
| In the gap | w034, 418, 260 | 16981, 14770, 12537 | 17 | w036 101 um outside, w033 143 um inside |
| In the gap | w036, 542, 1016 | 18213, 11594, 18432 | 346 | w034 8 um inside, w037 99 um outside |
| w035 inside w034 | w035, 844, 824 | 15162, 9192, 24556 | 315 | w034 50 um outside |
| w036 inside w034, in the gap | w036, 854, 1110 | 17834, 12866, 24543 | 21 | w034 80 um outside, w033 32 um inside |
| Skipped winding | w034, 1126, 334 | 15853, 15022, 26031 | 56 | w036 30 um outside |
| Skipped winding | w036, 626, 1010 | 18232, 11332, 20052 | 347 | w034 20 um inside |

**Interpretation.** w034 and w036 cannot both be on their own sheets where they meet, and a missing w035 alone would not bring w033 and w037 closer: in the gap they are about two windings apart instead of four (252 against 561 um). So in this sector some of w033 to w037 leave their sheets, by about two windings in all. Telling which ones needs a look at the CT, which I have not done.

## Turn overlaps: a note on using these segments (measured, run B)

Each of w023 to w034 is traced past a full turn about the umbilicus, by a median of 28 to 48 degrees per grid line (66 for w026). The doubly traced ends lie between about 272 and 53 degrees, over nearly the whole height. For w023 to w033 the doubly traced end lies on the next winding's sheet: a median 3 to 32 um from the next segment along the normal, with 25 to 61 % of it more than 18.72 um away (a median 34 to 60 um). w034's end lies mostly in the gap, so only 23 % of it has w035 at the same height and angle. w036 to w040 also run past a full turn, by a median of 4 to 30 degrees per line, between about 48 and 94 degrees.

This is not an error in the segments. But a point labelled with the segment it lies on gets the previous winding's number on a doubly traced end, one turn too low, unless that end and the next segment's vertices beside it are left out.

## What to drop before a spiral fit or a winding count

`--flags FLAGS.npz` writes one boolean mask per segment and check, on the segment's own tifxyz grid (repeated back to the full grid when run with `--stride`), under the keys `NAME/order`, `NAME/missing_sector`, `NAME/skipped_winding`, `NAME/turn_overlap`, `NAME/coincident` and their union `NAME/any`, with `names` and `voxel_um`. Before using these segments for relative windings, a spiral fit or any winding count, drop:

- `missing_sector`: w034 and w036 where w035 has no vertex within 1.5 grid steps of the same height and arc
- `order`: vertices whose nearest segment along the normal is a lower winding outside or a higher one inside
- `skipped_winding`: vertices with a segment two or more windings away within half the local pitch
- `turn_overlap`: each doubly traced end, plus the next segment's vertices at the same height and angle
- `coincident`: vertices with another segment within `--coincide-um` along the normal, where the two cannot be told apart
- and pairs of points with a winding between them that has no segment at that height: the report's `stack_ends` gives the z ranges, as below z 8,570 and above 28,869 between w034 and w039.

In run B the union covers 10 to 39 % of each segment's vertices (39 % of w034, 31 % of w036, 20 % of w035), most of it turn overlaps and coincident vertices.

## Usage

```bash
python -m pip install numpy tifffile scipy
python -m kit stackcheck SEG_INNER ... SEG_OUTER --umbilicus UMBILICUS.json \
    [--transform SPEC] [--stride N] [--planes N | --plane-z Z0 Z1 STEP] \
    [--out REPORT.json] [--flags FLAGS.npz] [--json] [--verbose]
python -m unittest tests.test_stackcheck      # synthetic stacks: a clean spiral passes, each planted defect is flagged
```

- Segments are given inner to outer, one per winding, as local tifxyz folders or as `https://` or `s3://` folders on the open-data bucket (fetched once into `--cache`, by default `work/stackcheck/cache`). Name one `NAME=PATH`; otherwise its name is the nearest folder above the path that is neither `mesh` nor a `.tifxyz` folder.
- The umbilicus is a local file or a URL in the published format (`control_points` with x, y and z, and `metadata.voxelsize_um`). It must be in the same volume as the segments, or `--transform` maps the segments into its volume: a JSON file with a 3x4 or 4x4 matrix, or `catalog:SAMPLE:FROM_VOLUME:TO_VOLUME` for the catalog's sample-level matrix (from `--catalog`, by default the bucket's `metadata.json`). Without a transform, a folder name's voxel size that differs from the umbilicus's is an error.
- Settings: `--ray-step-deg` (1), `--planes` (50) or `--plane-z`, `--max-normal-um` (600, how far along a normal a neighbour is looked for), `--coincide-um` (20), `--skip-frac` (0.5 of the local pitch), `--upsample` (2, neighbours made denser for the normal search), `--min-count` (10) and `--min-share` (0.01). A check is flagged when what it finds reaches both the count and the share.
- Output: a text summary (or the report with `--json`), the report JSON with `--out` (settings, frame, per segment and per check, with example vertices), and the masks with `--flags`. The exit status is 0 when nothing is flagged, 1 when something is, and 2 for bad input.
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
    --plane-z 8600 28800 200 --coincide-um 18.72 --out w033-w037.json --flags w033-w037-flags.npz
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
    --plane-z 8600 28800 200 --coincide-um 18.72 --out w023-w040.json --flags w023-w040-flags.npz
```

Both were run from the bucket on 14 October 2026 and gave the same reports and masks as the runs on local copies of the same files.

## Limits

- Geometry only. The checks say where segments disagree with each other and with their winding order about the umbilicus; they cannot say which segment left its sheet. That needs the CT.
- The ray checks use only rays that cross both segments of a pair once, so rays through seams and doubly traced ends are left out. Neighbours along a normal are looked for up to `--max-normal-um`.
- Where two segments lie within `--coincide-um` of each other they cannot be told apart, so the order check leaves those vertices out, and the skipped-winding counts above give the part beyond that distance.
- The doubly traced end is found per grid line, as the part past a full turn. It does not reach out to neighbouring lines, so its start can be a little narrower than a mask with a tolerance.
- Run A uses every second grid row and column, so its z extents are a little short of the full grid's and its vertex counts are of the strided grid; its masks are repeated back to the full grid.
- Angles depend on the umbilicus, which is a published line, not a measurement of this run.
- The tool has been run on real data only for PHerc0139 w023 to w040; its tests use synthetic spirals with planted defects.
