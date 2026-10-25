# Crowd-trace merger on a real crowd: VC3D tracer runs from different seeds (25 October 2026)

Follows [the planted-crowd preregistration](2026-10-24-crowdmerge.md) and [amendment 1](2026-10-25-crowdmerge-amendment-1.md), whose report split passed. Written and committed before any trace of this test exists.

## Why

The planted bench gives each slipping trace its own slip. Real traces of one sheet are often made by the same tracer on the same surface prediction, so their slips may sit at the same contacts, where a vote cannot help. This test asks whether `kit crowdmerge` still beats the largest single trace on such a crowd.

## Data and crowd

- Scan: PHerc0139, volume 20250728140407 (9.362 µm), public and on no prize list. Truth: the published hand-traced windings w027 and w037, as `kit hopbench refs` writes them. w027 is from the bench's dev split and w037 from its report split; neither is used here to change anything, since the settings stay frozen.
- Seeds: `python scripts/crowdmerge/realcrowd.py seeds`, fixed by rule: per winding, the middle cell of its first bench contact site (the bench's site rule and seed 20261024), then 7 points on a 3 mm circle around it at equal angles, each the nearest labelled vertex of the hand trace. Output, in level-0 voxels (x, y, z):
  - w027 (contact with w026): (2105, 3900, 4017), (2264, 3947, 4281), (2561, 3945, 4259), (2727, 3926, 4106), (2700, 3963, 3834), (2508, 3943, 3671), (2218, 3864, 3693)
  - w037 (contact with w036): (1950, 3803, 6827), (2050, 3894, 7087), (2103, 4156, 7131), (2266, 4231, 6935), (2245, 4210, 6662), (2062, 4093, 6508), (1923, 3908, 6594)
- Tracer: `kit scroll2ink run --until trace` per seed, as in the released scroll2ink demo: `vc_grow_seg_from_seed` from villa `e0bbb8b` with its grid-cache and growth-time-limit patches, on the public m7 surface prediction (20260413222639, threshold 0.2) with its normal grids, 60 generations, 25 minute limit, `--snap-seed` allowed (a seed off the prediction moves to the nearest point on it; where that lands is part of the result). One run per seed on Hugging Face Jobs (CPU). A Job that fails before its trace starts is rerun once; a trace that runs and grows little is kept as it is.
- Crowd: the 7 trace surfaces of each winding, unedited.

## Method

`python scripts/crowdmerge/realcrowd.py score TRACES`, with `kit/crowdmerge.py` unchanged from `f9a30ee` (sha256 `7ae11e51952aa39c266563ace97a8e46c077559ced8b68e706764858da9ad094`) and its frozen settings. Per winding A it merges the crowd (vote, and the naive mean as a comparison) and measures against A, inside A's footprint:

- Off sheet: the share of points more than 4 voxels from A along A's normal, for the vote consensus, the mean, the largest trace (most vertices; also the merger's base) and the whole crowd.
- Coverage: labelled vertices of A within 4 voxels of a surface (densified to about 2 voxels).
- Flags: a trace vertex is slipped when more than 6 voxels from A and on when within 2; recall and precision of the merger's slip flags as in the bench.
- Neighbour control: consensus points within 4 voxels of A against those within 4 voxels of A's chain neighbours.

## Bars, pooled over both windings

- PASS needs all four: vote off sheet at most 0.5 times the largest trace's; vote coverage at least 0.9 times the largest trace's; flag recall at least 0.80; flag precision at least 0.80.
- VOID, instead of a verdict, when the crowd slipped on under 2% of its points inside A's footprint (nothing to correct), when a winding has fewer than 4 traces that grew to 1 cm², or when a winding's neighbour control ratio is under 5 (the scoring cannot tell A from its neighbours there).
- Otherwise FAIL. Reported beside the verdict, without bars: the mean's off sheet, the best single trace's off sheet (chosen with the truth, so not a method), and the share of missed slips beyond the consensus.

## Looked at before this file

One trace from the released scroll2ink demo (seed on w035, not part of this test) was scored against the hand traces while the scorer was written: 74% of its points lie within 4 voxels of w035, 13% within 4 voxels of w034 and 9% of w036. That says real tracer runs do leave the sheet here, so the test is not empty; it says nothing about how the merger does.

## After

The result is reported whatever it is. A FAIL leaves the planted-crowd PASS standing and says the merger does not yet fix real tracer crowds; any change after it needs a new preregistration on windings or seeds not used here.
