# crowdmerge: fuse several traces of one sheet into one surface and flag each trace's slips

`python -m kit crowdmerge merge` fuses several tifxyz traces of the same papyrus sheet into one consensus surface by a vote along the surface normal, and flags where each trace slid onto a neighboring sheet; `bench` scores it on planted slips in PHerc0139's hand-traced windings.

| Field | Value |
| --- | --- |
| Id | `crowdmerge` |
| Status | Experimental |
| Kind | kit command, kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit crowdmerge merge`, `python -m kit crowdmerge bench`, `from kit import crowdmerge`; the real-crowd test: `python scripts/crowdmerge/realcrowd.py seeds\|score` |
| Code | `kit/crowdmerge.py`, `kit/cli.py` (`build_parser`), `scripts/crowdmerge/realcrowd.py` |
| Tests | `tests/test_crowdmerge.py` |
| Needs | Python 3.10 or newer (checked with 3.11), numpy, scipy (`cKDTree`, `ndimage`) and tifffile (`pip install numpy scipy tifffile`); `kit/sheetrefs.py` (tifxyz reader, grid geometry, upsampling, references, matching). `bench` also needs the references of [hopbench](hopbench.md) (`python -m kit hopbench refs`, about 40 MB, 5 minutes, and numcodecs for that step) |
| Runs on | CPU only. `merge` of 7 traces of an 8 mm window (about 15,000 vertices each at 4 voxels): 30 to 60 s. `bench --split dev` (36 sites, 3 crowds and 2 methods per site): 1,882 s; `--split report`: 2,580 s (measured 2026-10-25, 4-core Intel Xeon 2.80 GHz cloud container, peak memory under 2 GB) |
| Network | None. `bench` reads only the local references |
| Writes | `merge`: `OUT/consensus/` (x.tif, y.tif, z.tif, meta.json), `OUT/flags/NAME.tif` per trace, `OUT/support.tif`, `OUT/offset.tif`, `OUT/crowdmerge.json`. `bench`: `work/crowdmerge/bench-SPLIT/crowdmerge-bench.json` (or `--out`) |
| Go-ahead | Not needed: local CPU, your own traces or public data |
| Released | Public `main` from the PR that adds it (October 2026); a line of the Scrolls kit entry in the README's "Released tools", id `crowdmerge` |
| Guide | [Preregistration](../prereg/2026-10-24-crowdmerge.md); [real-crowd test](../prereg/2026-10-25-crowdmerge-real-crowd.md) |
| Checked | 2026-10-25 against commit `f9a30ee` |

## What it does

When several people (or several automatic runs) trace the same region of a scroll, each trace is a tifxyz mesh: three 2D float images giving every grid vertex's position in voxels of one CT volume. Where two sheets of papyrus touch, a trace can slide onto the neighboring sheet without crossing any gap, and carry on there. Different traces tend to slide at different places, so where one has left the sheet, most of the others still follow it.

`crowdmerge` uses that. It picks one trace as the base (by default the one with the most vertices) and puts its grid at about 5 voxel spacing. At every vertex it looks along the base's normal from -40 to +40 voxels in 1 voxel steps and asks, for every trace, whether one of its points lies within 2 voxels of that ray sample. Each trace that passes there votes for that offset. The offset with the most traces wins (ties go to the offset with more votes in the 9 x 9 box of vertices round it, then to the smaller move), and the vertex moves to the median offset of the traces that pass there. A vertex is kept only where at least 2 traces, and more than half of the traces present, agree. The surface then grows past the base's edges, a few rings at a time (each new ring is the straight-line continuation of the last two, then the same vote snaps it onto the crowd), so the result covers what the crowd covers, not only what the base covers. A second vote along the result's own normals, with the box count deciding, cleans up single vertices that picked the wrong sheet.

![Two stacked line charts along one row of an 8 mm window of PHerc0139 winding w023. Top: seven planted traces, four on w023 and three that leave it for w024. Bottom: the crowdmerge consensus stays on w023, the largest single trace leaves it, the naive mean sits between the windings.](../assets/crowdmerge/crowdmerge-pherc0139.png)

*Real data render: one planted crowd of PHerc0139 winding w023 next to w024 (published hand traces, scan 20250728140407; a development-split site), along one row of an 8 mm window. Up is the offset from w023 along its normal in voxels. Mesh geometry only, no CT, no ink. Vesuvius Challenge open data, CC BY-NC 4.0. Made by `python scripts/media/crowdmerge_still.py --site w023 w024 25 0 --seed 2 --row-frac 0.7 --out-dir docs/assets/crowdmerge`.*

Every trace is then checked against the result. A trace vertex that lies over the consensus (within 8 voxels of it sideways) and more than 4 voxels from it along the consensus normal is flagged as a slip. The flags are a uint8 image per trace on that trace's own grid, so they open as a mask in VC3D next to the segment.

It is a vote, not a check against the scan. A majority that is wrong wins: the bench's sham control shows it does. A place only one trace covers is left out of the consensus, and a trace's vertices there are neither confirmed nor flagged. It does not read the CT or any surface prediction, and it says nothing about ink: the output is geometry, never a reading.

## When to use it

- Several traces of the same sheet exist (yours, other people's, several tracer runs from different seeds) and you want one surface for rendering that follows the sheet most of them agree on.
- You want to know where each trace left the sheet the others follow, as a mask per trace, before rendering or before sending a trace on.
- You changed the merger and want to know whether it got better: run `bench --split dev`.

Do not use it:

- With two traces only: a vote of two cannot settle where they disagree, and those vertices are dropped. Use [overlap](overlap.md) to see where two traces of one sheet run apart.
- To find a sheet switch inside a single trace: use [planted](planted.md) plants with a switch detector, or [stackcheck](stackcheck.md) on a stack of windings.
- To say whether a surface prediction keeps touching sheets apart: use [hopbench](hopbench.md).
- On traces of different scans or resolutions without first moving them into one volume's voxel frame: positions are compared directly.

## Quick start

```bash
python -m pip install numpy scipy tifffile
python -m kit crowdmerge merge TRACE_A TRACE_B TRACE_C --out OUT
python -m kit crowdmerge merge TRACE_A TRACE_B TRACE_C --out OUT --json
```

`TRACE_A`, `TRACE_B`, `TRACE_C` are tifxyz folders (`x.tif`, `y.tif`, `z.tif`, `meta.json`) in the same volume's voxel frame; `OUT` is a new folder. What a run on three synthetic traces printed (two on one sheet, one that slides 12 voxels onto the next sheet halfway, as in `tests/test_crowdmerge.py`):

```
crowdmerge: 3 traces on t0's grid, 2450 vertices
  moved 0.4694, contested 0.0, one trace only 0.0
  t0: slip share 0.46 of 2500 vertices over the consensus
  t1: slip share 0.0 of 2500 vertices over the consensus
  t2: slip share 0.0 of 2500 vertices over the consensus
  written: OUT
```

It worked when the exit code is 0 and `OUT/consensus/x.tif` and `OUT/crowdmerge.json` exist. Open `OUT/consensus` as a segment in VC3D and `OUT/flags/NAME.tif` as a mask over that trace: value 2 marks the slipped vertices.

The bench, after `python -m kit hopbench refs`:

```bash
python -m kit crowdmerge bench --split dev
python -m kit crowdmerge bench --split dev --limit 2    # a smoke test, about a minute
```

## Checks and controls

The bench plants slips into copies of PHerc0139's published hand-traced windings (scan 20250728140407, 9.362 um, public and not prize-eligible), at places where two neighboring windings really touch, and scores the result against the hand traces. Its design and bars were fixed before the first run in the [preregistration](../prereg/2026-10-24-crowdmerge.md). In short: at each contact site (up to 4 per pair of neighboring windings, 8 mm apart), an 8 mm window of winding A becomes a crowd of 7 traces, each cropped to 70 to 100 % of each side, resampled at 4 voxels with a random phase and given a smooth 0.5 voxel normal jitter. In the main crowd, 3 of the 7 slide onto the touching winding B, each through its own contact point and direction, with a 16 voxel ramp (the ramp plant of hopbench, in any direction).

- **Arms.** `vote` is the tool. `largest` is the crowd's largest single trace, what one would usually pick. `mean` averages, per vertex, every trace's nearest layer: naive averaging, which lands between the sheets where traces disagree.
- **Clean control.** The same crowds with no trace slipping: the vote must not move off the sheet or flag good vertices.
- **Sham control (the check can fail).** 5 of 7 traces slide through the same contact and direction, so the majority is wrong. The vote must follow it; if it did not, something other than the crowd would be steering it, and the run would be void.
- **Splits.** Parameters may change on the development split (sites on windings w023 to w031); the report split (w032 to w040) runs once, with frozen parameters.

Development rounds (dev split, 36 sites; the bars apply to the report split):

| Round | Change | Off sheet: vote / largest / mean | Flag recall | Flag precision | Verdict |
| --- | --- | --- | --- | --- | --- |
| 1 | first version | 5.95 % / 26.29 % / 21.89 % | 74.5 % | 89.5 % | FAIL |
| 2 | per-vertex count decides; ray 40 voxels | 4.77 % / 26.29 % / 25.67 % | 85.2 % | 93.8 % | FAIL |
| 3 | growth past the base | 4.79 % / 26.29 % / 25.64 % | 85.7 % | 93.8 % | FAIL |
| 4 | 2 traces and a strict majority per vertex | 2.82 % / 26.29 % / 26.04 % | 83.8 % | 95.9 % | FAIL |
| 5 | second pass | 2.66 % / 26.29 % / 26.04 % | 84.3 % | 96.0 % | FAIL |
| 6 | vertices beyond the consensus judged | 2.66 % / 26.29 % / 26.04 % | 85.5 % | 95.8 % | FAIL |
| 7 | reliability weights in the second pass | 1.32 % / 26.29 % / 26.04 % | 88.4 % | 98.0 % | FAIL (recall) |
| 8 | the same weights beyond the consensus | 1.32 % / 26.29 % / 26.04 % | 93.9 % | 98.9 % | PASS |

In every round the clean control stayed at 0 off sheet and at most 0.01 % of good vertices flagged, and the sham control followed the wrong majority (about 43 % off sheet against 47 % of the majority's points slipped). The full record is in [amendment 1](../prereg/2026-10-25-crowdmerge-amendment-1.md), which froze round 8 (`f9a30ee`) before the report split ran.

Report split (run once, frozen settings):

| Arm or control | Bar | Result (36 sites, w032 to w040, 25 Oct 2026) |
| --- | --- | --- |
| Main crowd: consensus off sheet | at most 2 % and a quarter of the largest trace's | **0.96 %**; largest single trace 13.8 %; naive mean 18.2 % |
| Main crowd: slip flags | recall and precision at least 90 % | **recall 93.8 %, precision 99.3 %**; 0.13 % of good vertices flagged |
| Main crowd: coverage | none | 84.8 % of the window |
| Clean control | at most 1 % off sheet and 1 % false flags | **0 % and 0 %** |
| Sham control (wrong majority) | follows it: at least half of the majority's slipped share | **44.2 %** off sheet against 46.9 % slipped: it follows, as a vote must |
| Verdict | | **PASS** (2,580 s on 4 cores) |

What it shows (Interpretation): on planted crowds where 3 of 7 traces slide onto a touching sheet at their own places, the merged surface is off the sheet about one fourteenth as often as the largest single trace (0.96 % against 13.8 %), and the per-trace flags find about 94 % of the slipped area with under 1 % false alarms. What it does not show: real crowds were not tested (people's slips cluster where the scan is hard, so they are less independent than these), nor crowds where most traces slip, nor other scans. Missed slips are mostly where too few traces overlap to vote (38 % of the misses lie beyond the consensus).

Claim label: Model output, for every number above (geometry computed by the tool on planted crowds; the hand traces are the reference); Interpretation, for what they mean for real crowds, which were not tested.

## Commands and options

### `python -m kit crowdmerge merge`

```
usage: python -m kit crowdmerge merge [-h] --out OUT [--base BASE]
                                      [--method {vote,mean}]
                                      [--workers WORKERS] [--json]
                                      traces [traces ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `traces` | required | tifxyz folders (x.tif, y.tif, z.tif, meta.json), at least two |
| `--out OUT` | required | output folder |
| `--base BASE` | none | the trace whose grid carries the consensus (folder name; default: most points) |
| `--method METHOD` | `vote` | `vote` is the tool; `mean` is the naive per-vertex average, kept for comparison |
| `--workers WORKERS` | `2` | threads for the KD-tree queries |
| `--json` | off | print the summary as JSON |

Trace names are the folder names, so they must differ. Rerunning with the same `--out` overwrites its files.

### `python -m kit crowdmerge bench`

```
usage: python -m kit crowdmerge bench [-h] [--refs REFS]
                                      [--split {dev,report,all}]
                                      [--limit LIMIT] [--out OUT]
                                      [--workers WORKERS] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--refs REFS` | `work/hopbench/refs/PHerc0139-20250728140407` | kit hopbench refs output (default work/hopbench/refs/PHerc0139-20250728140407) |
| `--split SPLIT` | `dev` | `dev` (sites on w023 to w031), `report` (w032 to w040, the preregistered held-back split), `all` |
| `--limit LIMIT` | none | score only the first N sites (a smoke test) |
| `--out OUT` | none | report folder (default work/crowdmerge/bench-SPLIT) |
| `--workers WORKERS` | `2` | threads for the KD-tree queries |
| `--json` | off | print the tally as JSON |

### `python scripts/crowdmerge/realcrowd.py`

The real-crowd test of the [real-crowd preregistration](../prereg/2026-10-25-crowdmerge-real-crowd.md): `seeds` prints its fixed seed points (7 per winding on a 3 mm circle around the winding's first bench contact site); `score TRACES` merges each winding's crowd (`TRACES/<winding>/<trace>/` tifxyz folders, for example VC3D tracer runs from those seeds) and scores it against the hand trace, writing `TRACES/realcrowd.json`.

| Option | Default | Meaning |
| --- | --- | --- |
| `--windings W ...` | `w027 w037` | `seeds`: the hand-traced windings to seed |
| `--agent DIR` | none | `seeds`: a Headless VC3D folder; each seed moves along the hand trace's normal (up to 6 voxels) to where the tracer's `seed_check` passes, drawing on 14 candidates until 7 pass ([amendment 1](../prereg/2026-10-25-crowdmerge-real-crowd-amendment-1.md)) |
| `--refs REFS` | `work/hopbench/refs/PHerc0139-20250728140407` | kit hopbench refs output |
| `--json` | off | `seeds`: print as JSON |
| `--out FILE` | `TRACES/realcrowd.json` | `score`: report path |
| `--workers N` | `2` | `score`: threads for the KD-tree queries |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `merge(traces, base=None, settings=None, method='vote', workers=2, log=None)` | dict: `xyz` (H, W, 3, NaN outside), `valid`, `offset` (total move per vertex, voxels), `support` and `present` (traces agreeing and present), `grown`, `flags` {name: uint8 grid}, `scale_factor`, `summary` | `MergeError` | `traces` is a list of (name, xyz (H, W, 3) float, valid (H, W) bool). `settings` overrides keys of `SETTINGS` |
| `flag(xyz, valid, cpts, cnrm, ctree, settings=None, workers=2)` | (H, W) uint8: 0 not over the consensus, 1 agrees, 2 slip | nothing | one trace against dense consensus points, their normals and a KD-tree of them |
| `write(out_dir, res, base_meta=None)` | the output folder | `OSError` | writes what `merge` returned; `meta.json` scale is multiplied by the canvas upsampling |
| `ray_hits(P, N, tree, reach, tol, workers=2, batch=400000)` | (V, 2 reach + 1) bool | nothing | whether a tree point lies within `tol` of P + o N, o = -reach..reach |
| `choose(votes, mask, offs, box, smooth_first=False)` | (H, W) index into `offs` | nothing | the vote's tie-breaking rule |
| `beyond(f, xyz, valid, t, dense, S, workers=2, weights=None)` | how many vertices it judged | nothing | judges, in place, a trace's vertices beyond the consensus by the traces on its own normal (weighted when weights are given) |
| `extrapolate(X, valid, blocked)` | (X with one new ring, new mask) | nothing | straight-line continuation used for growth |
| `sites(refs, man, names, rng, log=None)` | [(A, B, window)] | nothing | the bench's contact sites |
| `crowd(up, ok, nA, s, ins, nB, step, rng, n=7, slipping=3, same=False)` | [(name, xyz, valid, truth offset)] or None | nothing | one synthetic crowd |
| `tally(rows)` | dict of pooled shares, `checks`, `verdict` | nothing | the preregistered bars |
| `bench(refs_dir, split='dev', settings=None, workers=2, log=None, limit=None)` | the report dict | `MergeError`, `BenchError` | what `bench` writes |
| `MergeError` | | | raised for bad input; the command prints it and exits 2 |
| `build_parser(p)`, `cmd_crowdmerge(args)` | | | the command line |

## Inputs

- **Traces** (`merge`): tifxyz folders in one CT volume's voxel frame. Vertices at -1, NaN or (0, 0, 0) are holes. Any grid spacing; each trace is densified to about 2 voxels before it votes. Each trace must cover the same sheet for at least part of its area; traces of other regions just do not vote there.
- **References** (`bench`): the output of `python -m kit hopbench refs`: PHerc0139 windings w023 to w040 with their manifest.

## Outputs

`merge` prints the summary (or, with `--json`, the same as `OUT/crowdmerge.json`) and writes:

| File | What it is |
| --- | --- |
| `OUT/consensus/x.tif`, `y.tif`, `z.tif` | float32 grids at about 5 voxel spacing, -1 outside the consensus |
| `OUT/consensus/meta.json` | the base's meta.json with `scale` multiplied by the upsampling, and a `crowdmerge` record (traces, base, method, spacing) |
| `OUT/flags/NAME.tif` | uint8 on that trace's own grid: 0 not over the consensus, 1 agrees, 2 slip |
| `OUT/support.tif` | uint16 per consensus vertex: traces that agree there |
| `OUT/offset.tif` | float32 per consensus vertex: how far it moved from the base (or the straight-line continuation), voxels |
| `OUT/crowdmerge.json` | the summary below |

| Field | Type | Meaning |
| --- | --- | --- |
| `traces`, `base`, `method` | int, str, str | inputs |
| `canvas`, `canvas_step_vox`, `vertices`, `grown_vertices`, `grow_rings` | | the consensus grid; vertices grown past the base and how many rings |
| `moved_share` | float | share of base vertices moved more than `slip_vox` |
| `contested_share`, `single_trace_share` | float | share of kept vertices with no strict majority, or one trace present (0 after the support rule unless one trace was given) |
| `area_vox2` | float | consensus area, voxels squared |
| `flags.NAME` | dict | `vertices`, `over_consensus`, `slip_share` per trace |
| `settings` | dict | every setting used |

`bench` writes `crowdmerge-bench.json` with `tally` (per arm `main`, `clean`, `sham`: `vote`, `mean`, `largest` off-sheet shares, `coverage`, `flag_recall`, `flag_precision`, `false_flag_share`, `missed_outside_share`, `majority_slipped_share`; then `checks` and `verdict` PASS, FAIL or VOID), `rows` (per site counts), `settings`, `bench`, `bars` and `seconds`.

| Exit code | Meaning |
| --- | --- |
| `0` | done (for `bench`, whatever the verdict: read `tally.verdict`) |
| `2` | bad input or no references (the message says which) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `crowdmerge: no traces` | `merge([])` from Python | pass at least one trace |
| `crowdmerge: give at least two traces` | one folder given | give two or more; with two, expect their disagreements dropped |
| `crowdmerge: trace names must be distinct` | two folders with one name | copy or link one under another name |
| `crowdmerge: base NAME is not one of the traces` | `--base` names no input folder | use a folder name exactly as given |
| `crowdmerge: base NAME has no vertex with a normal` | the base is empty or one row wide | pick another base |
| `crowdmerge: no vertex of the base is agreed by enough traces` | the traces do not overlap the base, or are in different frames | check they trace the same region in the same volume |
| `crowdmerge: split must be dev, report or all, not ...`, `unknown method ...` | API misuse | use one of the listed values |
| `WINDING has no contact site` | `realcrowd.py seeds` on a winding that touches no chain neighbor | pick another winding |
| `seed_check failed: ...` | `realcrowd.py seeds --agent DIR` could not run Headless VC3D's `seed_check` in DIR, or it printed no JSON | point `--agent` at a Headless VC3D folder (v1.1.1); it needs network access to the open-data bucket |
| `crowdmerge: no usable site` | the references are missing or empty | run `python -m kit hopbench refs` |
| `crowdmerge: ...: no x.tif (not a tifxyz folder)` | a path is not a tifxyz folder | point at the folder holding x.tif |
| A consensus that follows the wrong sheet | most traces present there are on that sheet | it is a vote; check with the slip flags of the traces you trust, or add independent traces |

## How it works

1. Base: the trace with the most valid vertices (or `--base`), upsampled bilinearly to about `canvas_step_vox` = 5 voxels; normals by central differences (`sheetrefs.grid_geometry`).
2. Every trace is densified to about `dense_step_vox` = 2 voxels and put in a KD-tree.
3. Ray votes: for each base vertex, samples at offsets -`reach_vox`..+`reach_vox` (40) along the normal; a trace passes a sample when a point lies within `tol_vox` = 2. A pass also counts in `spread_bins` = 1 bin either side.
4. Choice: the offset with the most passing traces; ties to the most votes in a `box_cells` = 9 box, then to the smaller |offset|. The move is the median, over the traces passing at the winning offset, of where the ray meets each trace's tangent plane.
5. Support rule: drop vertices where fewer than `min_support` = 2 traces agree, or no more than half of those present do.
6. Growth: up to `grow_cells` = 100 rings past the base, `rings_per_vote` = 3 rings continued in a straight line at a time, then voted; new vertices that fail the support rule are blocked.
7. Second pass (`passes` = 2): the same vote along the result's own normals, with the box count deciding and the vertex's own count breaking ties; the support rule again.
8. Flags: each trace vertex against the consensus densified to 2 voxels: over it when the nearest consensus point is within `flag_reach_vox` = 64 and within `in_plane_vox` = 8 sideways; a slip when it is more than `slip_vox` = 4 along the normal.

## Cost and time

CPU only; no rented compute. See Runs on for measured times. Time grows with the number of traces times the consensus area times the ray length (81 samples): halve `reach_vox` for traces known to stay within 20 voxels of each other.

## For agents

- **Command:** `python -m kit crowdmerge merge T1 T2 T3 ... --out OUT --json`.
- **Parse:** the JSON summary; per trace `flags.NAME.slip_share`; `OUT/flags/NAME.tif` value 2 for slipped vertices.
- **Rerun:** safe; the same inputs give the same output, and a rerun overwrites `OUT`.
- **Success:** exit 0 and `vertices` greater than 0.
- **Not a pass:** a consensus from traces that copied each other (one trace grown from another shares its slips: votes are not independent); a low slip share on a trace that barely overlaps the others (`over_consensus` small).
- **Go-ahead:** Nothing for local runs. Publishing a consensus or flags from a prize-eligible scroll is a possible-finding question: keep those private.
- **Never:** call the consensus a reading or say it contains letters; run the report split again after it has been spent.

## Tests

`python -m unittest tests.test_crowdmerge -v` (about 10 s): on two synthetic parallel sheets 12 voxels apart, a minority slip is pulled back onto the sheet and flagged even when the base is the slipped trace; a wrong majority wins (the sham); a lone trace is kept unchanged; the consensus grows past a half-width base and a lone trace beyond the base is not enough to grow; the naive mean lands between the sheets; the ray, tie-break and straight-line continuation rules; the crowd generator's truth; the tally's PASS and VOID verdicts; the command line writes and reads tifxyz. They do not cover real scans or real crowds.

## History

- 2026-10-25: first version (`f9a30ee`): vote, growth, a second reliability-weighted pass, per-trace flags, and the planted-slip bench with clean and sham controls.

## Related

- [hopbench](hopbench.md): the same references and contact sites; whether a surface prediction keeps touching sheets apart.
- [planted](planted.md): synthetic switches and mergers with known answers.
- [overlap](overlap.md): how close two traces of one sheet run.
- [Preregistration](../prereg/2026-10-24-crowdmerge.md): bench design and bars.
