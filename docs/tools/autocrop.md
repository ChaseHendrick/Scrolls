# autocrop: keep the regions of a villa spiral fit whose windings are most likely right

Ranks every cell of a villa spiral fit by four checks that need no truth, keeps the better half, and writes the kept regions as villa relative-winding point collections, with a shifted control and a scorer for when winding truth exists.

| Field | Value |
| --- | --- |
| Id | `autocrop` |
| Status | Experimental |
| Kind | script |
| Area | Surfaces and tracing |
| Run | `python3 scripts/autocrop/autocrop.py crops`, `score`, `readout`, `demo` |
| Code | `scripts/autocrop/autocrop.py` |
| Tests | `tests/test_autocrop.py` |
| Needs | Python 3.10 or later, numpy, scipy, tifffile, zarr (2.x), and [spiralfiteval](https://github.com/jo-tud/spiralfiteval) (MIT) at commit `217947a`, installed with `pip install "git+https://github.com/jo-tud/spiralfiteval@217947aff35db6dd8fb912a82423c7c37ea1281d#subdirectory=tools/spiralfiteval"`; for real use, two villa spiral-fit exports of the same window and the lasagna field they read |
| Runs on | Any CPU; the synthetic demo (192 cells) in about 2 s (measured 2026-11-05, cloud container); 13,465 cells of a 1,024-slice PHerc0139 fit band in about 4 minutes (measured 2026-10-28, cloud container) |
| Network | None |
| Writes | `crops`: four files in `--out-dir` (two point-collection files, the cell file and the record); `score` and `readout`: the `--out` file; `demo`: synthetic fits, a lasagna folder, the crops files and `demo-result.json` under `--out-dir` |
| Go-ahead | Not needed: it reads local files and rents nothing |
| Released | Public `main` since 2026-11-05 (code, Apache-2.0) |
| Checked | 2026-11-05 against commit `cc5f793` |
| License | [Apache-2.0](../../LICENSE) |

## What it does

villa's spiral fit (the lasagna `fit_spiral` stage) puts one deformed spiral through a whole band of a scroll and exports it as one tifxyz surface with the windings side by side. Some regions of that surface follow the right papyrus winding and some jump to a neighbor. The organizers' [winding annotations page](https://scrollprize.org/winding_annotations) names automatically cropping the good regions of a spiral fit as an open avenue. autocrop is one answer: it picks the regions most likely to be right, using only the fit, a second fit of the same window and the lasagna field.

It splits each winding of the export into **cells** of 4 rows by 8 columns of grid vertices (about 80 by 160 fit voxels on a 20-voxel grid) and scores every cell by four signals. **seed**: the share of the cell's vertices that the **sibling** (a second fit of the same window with another seed) puts on the same winding, after the two fits' overall winding offset. **normal**: how well the fit's surface normal agrees with the lasagna field's normal. **spacing**: how far the distance to the inner and outer winding, scaled by the field's `grad_mag` density, is from one sheet spacing. **regularity**: how far the cell's grid edges are from the winding's median grid step. Each signal becomes a percentile rank, the four ranks are averaged and smoothed over each cell's 3 by 3 neighbors on its winding, and the top half is kept. This is **rule main**.

`crops` writes the kept cells that touch each other (components of at least 4 cells) as villa point collections of relative windings: one point per cell, all on the same winding of their component, as a surface patch would be. It also writes a **shifted control**: the same components moved along their winding by a random number of cell columns. `score` checks rule main against winding truth you bring, with equal-count random crops and a shuffled-signals control, and `readout` applies the bars the rule was tested with. `demo` builds a synthetic fit pair with a planted wrong-winding patch and checks that the rule drops it.

autocrop does not fit, trace or mesh anything, and it does not read CT or ink. A kept cell is model output that the fit is more likely right there, never a reading. Its point collections are not hand annotations and must not be presented as winding truth.

## When to use it

- You have a villa spiral fit and want the regions of it most likely on the right winding, for example to inspect, to mesh or to pass to a later step.
- You have hand windings or other winding truth in a window and want to check a crop rule against equal-count random crops, with controls that can fail (`score`, `readout`).
- You want villa relative-winding point collections from a fit's own good regions, with a shifted control to compare them against.

Do not use it:

- To improve a spiral fit by feeding its own crops back in: on the development window that gave no gain (see Checks and controls). Use winding labels that add information the fit lacks, such as [Ringleader](ringleader.md)'s ladders or [`windlabel-box`](windlabel-box.md).
- To count a fit's winding errors over a whole scroll: use [`seamswitch`](seamswitch.md).
- With one fit only: the seed signal needs a sibling fit of the same window.

## Quick start

```bash
python3 -m pip install numpy scipy tifffile "zarr<3" \
  "git+https://github.com/jo-tud/spiralfiteval@217947aff35db6dd8fb912a82423c7c37ea1281d#subdirectory=tools/spiralfiteval"
python3 scripts/autocrop/autocrop.py demo --out-dir work/autocrop-demo
python3 scripts/autocrop/autocrop.py crops --fit work/autocrop-demo/fitA --sibling work/autocrop-demo/fitB \
  --lasagna work/autocrop-demo/lasagna --windings 11 14 --out-dir work/autocrop-demo/again
```

The demo writes two synthetic spiral fits (windings 10 to 15; `fitA` has a 12-cell patch of winding 12 pushed one winding out) and a lasagna folder, runs `crops` on windings 11 to 14 and checks the kept share of the planted cells. It printed (2026-11-05, cloud container, about 2 s):

```
fits read in 0 s, 192 cells
{"check": "PASS", "planted_cells": 12, "planted_kept_share": 0.0, "other_cells": 180, "other_kept_share": 0.533, "components": 4, "crop_points": 91, "shift_points": 91, "bar": "planted kept share at most half the other cells' kept share"}
```

It worked when the demo exits 0 with `"check": "PASS"`. The second command reruns `crops` on the demo's fits the way you would on real ones, and prints the record (`"cells": 192, "kept_cells": 96, "components": 4`). On real data, `--fit` and `--sibling` are two villa spiral-fit run folders (or their `spiral-checkpoint.tifxyz` folders) of the same window, `--lasagna` the folder of the field they read, and `--windings` the band of windings to crop.

## Checks and controls

The rule was developed on PHerc0139 and then tested twice with its rule, bars and controls fixed before any fit of the test band existed. In each test, villa's spiral fit (default settings, 30,000 steps) was run with several seeds; each fit's cells holding scored truth pairs were ranked, and the kept half was scored by the share of hand-winding pairs, both ends in kept cells, whose winding difference the fit gets exactly right. **G_rand** is that share minus the mean over 1,000 equal-count random crops of the same cells, in percentage points. The bars: mean G_rand at least 5 points, at least 80 % of fits above their random crops' 97.5th percentile, and a positive gain after reweighting to the random crops' mix of winding distances; the readout is void if the rule run on shuffled signals beats random crops by 2 points or more.

| Window | What it is | Fits | G_rand (mean) | Fits above the 97.5th percentile | Gain over the whole fit | Shuffled-signals control | Shifted-crops control |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PHerc0139, 14 development windings, 1,394 pairs (28 Oct 2026) | Development, not held out | 10 | +9.7 points | 9 of 10 | +6.1 points | not run | not run |
| PHerc0172, one 1,024-slice band, 10,790 pairs (29 Oct 2026) | Held-out test | 5 | +7.3 points | 5 of 5 (and 3 of 3 extra fits) | +5.9 points | -0.01 points | kept cells ahead by +7.2 points |
| PHerc1667, one band of 13 consecutive windings, 7,679 pairs (31 Oct 2026) | Exception test on reused windings (weaknesses below) | 5 | +8.1 points | 5 of 5 | +7.2 points | -0.1 points | kept cells ahead by +6.6 points |

Both tests read BEATS_CONTROL, the rule's pass. The truth in both was the organizers' published hand-winding meshes (Vesuvius Challenge open data), clipped to the test band; a margin around regions set aside for other tests was left out.

**The PHerc1667 test was an exception test, not a fresh held-out test.** No unused winding truth was left on a scroll that met the test's floors, so it reused the least-used truth under a disclosed exception rule. Its weaknesses, stated with every report of its result:

- W1: villa's lasagna model, whose field the fits, the spacing, normal and regularity signals read, was trained on tifxyz meshes from this scan over a z range that includes the band, and these windings were most likely among them. A pass says the rule works on a fit whose field has seen this scroll; it does not show transfer to an unseen field.
- W2: these windings had been scored once before by a spiral-fit test, in another band of the same scroll.
- W3: two earlier tests of other methods (automatic winding labels and a tracing test) scored truth in this band.
- W4: part of the band overlaps a region set aside for another test; this test read only the public lasagna field and winding order there, with no CT and no surface positions.
- W5: the host differed from PHerc0172's: the fit grid was level 2 of the 2.4 um scan (9.6 um voxels), the field was the open-data lasagna product, the fit loop stopped at 45 minutes, the truth density differed, and the band was chosen after four geometry-only counts.
- W6: thirteen consecutive windings in one band, against PHerc0172's larger set.

**Against villa's own per-region losses.** villa's spiral fit can export diagnostic loss maps. Ranking cells by them instead of rule main, on the same fits and truth (development comparisons, not frozen tests): on four PHerc0139 development fits the two tied (villa's map +8.8 points, rule main +7.8; difference about -1 point, 95 % interval -4.3 to +2.0); on the five PHerc1667 test fits rule main was ahead of villa's raw map by 3.4 points (95 % interval 1.0 to 5.8), but villa's map with rule main's neighbor smoothing reached +7.95 against +8.06. Most of rule main's edge over villa's maps comes from the smoothing.

**Limits.**

- Feeding the crops back as relative windings did not help: on the PHerc0139 development window, two refits with the crops scored on average 4.7 points below the plain fits (the bar for a gain was +5), and only 1.6 points above refits with the shifted control. The fitter meets the strips within about 1,000 steps, since they come from a surface it can already make. A later frozen test that would have fed crops into a fit on another band stopped at its control check before any such fit ran. Using the crops as fit inputs is untested beyond that.
- The rule removes oversplits more than merges: inside kept cells, pairs one winding apart were put on one winding more often than in the whole fit (15.6 % against 11.8 % on development).
- The tests ranked only the cells holding scored truth pairs and their ring of neighbors; `crops` ranks every cell of the chosen windings, so its kept set can differ slightly from the scored one. `score` reproduces the tests' ranking and also reports the `crops` ranking's own result (rule `crops`).
- Two scrolls, one band each, with the second test on reused truth. A test on fresh winding truth of a scroll the lasagna model did not train on has not been run.
- A machine-searched alternative rule was scored on both tests as a reported secondary and did not pass (WEAK on both); it is not part of the tool.

To check the rule yourself, run `crops` on your fit pair, build a pair table from your truth (Inputs), run `score` per fit and `readout` over the fits. A pass needs the bars above; `readout` returns VOID when the shuffled control beats random crops, and the synthetic `demo` returns FAIL (exit 1) when the planted patch is not dropped.

Claim label: Model output, for every crop, score and test result above (fits and crops against the organizers' published hand windings); Interpretation, for what the comparison with villa's loss maps means.

## Commands and options

### `autocrop.py`

```
usage: autocrop.py [-h] [--version] {crops,score,readout,demo} ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--version` | off | Print `autocrop 1.0.0` and exit |

### `crops`

```
usage: autocrop.py crops [-h] --fit FIT --sibling SIBLING --lasagna LASAGNA
                         --windings W0 W1 --out-dir OUT_DIR
                         [--umbilicus UMBILICUS] [--seed SEED] [--name NAME]
                         [--sibling-name SIBLING_NAME]
```

Rule main over every cell of windings W0 to W1, with no truth: the kept components as point collections, and the shifted control.

| Option | Default | Meaning |
| --- | --- | --- |
| `--fit` | required | The fit's run folder, or its `spiral-checkpoint.tifxyz` folder |
| `--sibling` | required | A second fit of the same window (another seed), in the same form; only windings W0 - 3 to W1 + 3 are read |
| `--lasagna` | required | Folder holding the `nx`, `ny` and `grad_mag` zarrs the fit read (any file name containing those words and ending `.zarr`) |
| `--windings` | required | W0 W1: the first and last winding to crop, as the export numbers them |
| `--out-dir` | required | Output folder (created; files of the same fit name are overwritten) |
| `--umbilicus` | none | villa umbilicus JSON in fit coordinates; default the fit's `dataset/umbilicus.json` (looked for in the fit folder, its parent, or as `umbilicus.json` in the fit folder) |
| `--seed` | 0 | numpy seed of the shifted control |
| `--name` | none | The fit's name in file names; default the folder name |
| `--sibling-name` | none | The sibling's name in the record; default the folder name |

### `score`

```
usage: autocrop.py score [-h] --crops CROPS --pairs PAIRS --out OUT
                         [--draws DRAWS] [--shuffles SHUFFLES] [--seed SEED]
```

Rule main against a pair table of winding truth, ranked as in the tests, with random crops and the shuffled-signals control; also the `crops` ranking as rule `crops`.

| Option | Default | Meaning |
| --- | --- | --- |
| `--crops` | required | `crops-NAME.json` written by `crops` |
| `--pairs` | required | Pair table JSON: `cell_a`, `cell_b`, `exact`, `dw` (Inputs) |
| `--out` | required | Score file to write (overwritten) |
| `--draws` | 1000 | Random crops (`DRAWS`) |
| `--shuffles` | 50 | Shuffled-signals draws (`SHUFFLES`); seeds 1000 x `--seed` + s |
| `--seed` | 0 | numpy seed of the random crops and base of the shuffle seeds |

### `readout`

```
usage: autocrop.py readout [-h] --out OUT SCORE [SCORE ...]
```

The tests' verdict for rule main over the score files of several fits.

| Option | Default | Meaning |
| --- | --- | --- |
| `SCORE` | required | Score files written by `score`, one per fit (fit names must differ) |
| `--out` | required | Readout file to write (overwritten) |

### `demo`

```
usage: autocrop.py demo [-h] --out-dir OUT_DIR [--seed SEED]
```

A synthetic fit pair with a planted wrong-winding patch, `crops` on it, and a check that the patch is dropped.

| Option | Default | Meaning |
| --- | --- | --- |
| `--out-dir` | required | New or empty folder for the demo files |
| `--seed` | 0 | numpy seed of the synthetic noise and the shifted control |

## Python API

Not applicable: the script is the interface; its functions (such as `compute_signals`, `scores`, `keep_top` and `score_fit`) can be imported from `scripts/autocrop/autocrop.py` but are not a supported library.

## Inputs

- **Spiral-fit export** (`--fit`, `--sibling`): villa's export of a spiral fit, a tifxyz folder with `x.tif`, `y.tif` and `z.tif` (one grid, rows along z, the windings side by side in columns) and `meta.json` with `winding_column_ranges` (each winding's column range) and `first_winding` (default 10). Vertices with x equal to -1, or z not above 0, are empty. Coordinates are fit voxels (x, y, z). The run folder may hold it as `spiral-checkpoint.tifxyz/`. The sibling must be a fit of the same window and grid with another seed.
- **Lasagna field** (`--lasagna`): the `nx`, `ny` (uint8, 128 + 127 times the normal component; 0 and 0 mean no value) and `grad_mag` arrays the fit read, zyx order, one stored voxel per `LAS_SCALE` = 4 fit voxels. A zarr group is read through its first array. villa's lasagna fields for many scans are listed in [Lasagna Fields](https://huggingface.co/spaces/SharpMeow/lasagna-fields).
- **Umbilicus** (`--umbilicus`): villa's umbilicus JSON in fit coordinates, `{"control_points": [{"x", "y", "z"}, ...]}` or a list of `[x, y, z]`, at least two points.
- **Pair table** (`score --pairs`): JSON with four lists of equal length, one entry per truth pair: `cell_a` and `cell_b`, the `[winding, row block, column block]` cells of the fit vertices the pair's two truth points project to (the cells of `crops-NAME.json`); `exact`, 1 when the fit's winding difference between them equals the truth's, else 0; and `dw`, the truth winding difference (1 to 6). Making it needs truth that crosses the fit and a projection of each truth point onto the fit's nearest sheet; autocrop does not build it.

## Outputs

`crops` prints its record as one JSON line on stdout (progress goes to stderr) and writes, in `--out-dir`:

| File | What it holds |
| --- | --- |
| `relative_windings_crop_NAME.json` | villa point collections (`vc_pointcollections_json_version` "1"): one collection per kept component of at least 4 cells with at least 4 points, one point per cell (the valid vertex nearest the cell's center), `wind_a` 0, `winding_is_absolute` false |
| `relative_windings_shift_NAME.json` | The shifted control in the same form |
| `crops-NAME.json` | `signals` and `smooth` per cell (key `"winding,row block,column block"`), `kept`, `components`, `shifted` |
| `crops-record-NAME.json` | The record below |

| Field | Type | Meaning |
| --- | --- | --- |
| `tool`, `version` | string | `autocrop` and its version |
| `fit`, `sibling` | string | The two fits' names |
| `windings` | list | W0 and W1 |
| `cells`, `kept_cells` | int | Cells of the band with a valid vertex, and the kept half |
| `components`, `cells_in_components` | int | Kept components of at least 4 cells, and their cells |
| `signal_info` | object | `seed_offset` (the two fits' median winding offset), `seed_hit_share` (share of vertices the sibling projection found), `vertices` |
| `seed` | int | The shifted control's seed |
| `files` | object | Per tag (`crop`, `shift`): `file`, `sha256`, `collections`, `points` |
| `seconds` | float | Wall time |

`score` writes the score file and prints a one-line summary (`fit`, `pairs`, `kept_pairs`, `E_rule`, `E_rand`, `G_rand`, `above_p975`, `shuffled_minus_rand`):

| Field | Type | Meaning |
| --- | --- | --- |
| `pairs`, `zone_cells`, `zone_plus_cells` | int | Truth pairs, cells holding them, and those cells with their ring |
| `E_all` | float | Share of all pairs the fit gets exact |
| `rules.main`, `rules.crops` | object | Per rule: `kept_cells`, `kept_pairs`, `kept_pair_share`, `E_rule` (exact share of kept pairs), `E_rand`, `rand_p975`, `rand_p025` (random crops), `G_rand` (E_rule minus E_rand), `G_all` (E_rule minus E_all), `above_p975`, `G_rand_dw_std` (the dw-reweighted gain) |
| `shuffled` | object | `shuffles`, `E_shuffled`, `shuffled_minus_rand` |

`readout` writes the readout and prints `verdict`, `mean_G_rand`, `fits_above_p975`, `fits_scored`, `mean_shuffled_minus_rand` and `why`. The file also holds `fits` (per fit, with `void`), `void_fits`, `fits_needed_above`, `fits_under_rand_mean`, `mean_G_all` and `mean_G_rand_dw_std`. Verdicts: BEATS_CONTROL, WEAK, NO_GAIN, VOID.

`demo` writes `fitA/`, `fitB/`, `lasagna/`, `crops/` and `demo-result.json` (`check`, `planted_cells`, `planted_kept_share`, `other_cells`, `other_kept_share`, `components`, `crop_points`, `shift_points`, `bar`), and prints the result.

| Exit code | Meaning |
| --- | --- |
| `0` | Done; for `readout`, a verdict of BEATS_CONTROL, WEAK or NO_GAIN; for `demo`, PASS |
| `1` | `demo` only: FAIL, the planted patch was kept at more than half the other cells' rate |
| `2` | Bad arguments, an input it cannot read, or a missing package |
| `3` | `readout` only: VOID |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `autocrop: no dataset/umbilicus.json beside FIT: pass --umbilicus` | The fit folder holds no center line | Pass `--umbilicus` with the center line the fit used |
| `autocrop: no meta.json in DIR: give the fit's run folder or its spiral-checkpoint.tifxyz folder` | The folder is not a spiral-fit export | Point `--fit` or `--sibling` at the run folder or the tifxyz folder |
| `autocrop: FILE has no winding_column_ranges: not a spiral-fit export` | A tifxyz surface that is not a spiral-fit export | Use villa's spiral-fit export |
| `autocrop: no fit vertices inside BOX` | The sibling has no valid vertex in the windings read | Check the sibling is a fit of the same window |
| `autocrop: the pair table's cell_a, cell_b, exact and dw differ in length` | A malformed pair table | Rebuild it with one entry per pair in each list |
| `autocrop: the pair table holds no pairs` | An empty pair table | Check the truth crosses the fit |
| `autocrop: N pair cells have no signals in the crops file (first CELL): run crops over the windings the truth crosses` | The pair table uses cells outside the cropped band | Rerun `crops` with `--windings` covering the truth |
| `autocrop: --windings W0 W1: the first winding must not be above the second` | W0 is above W1 | Swap them |
| `autocrop: the fit has no winding in W0 to W1 (it has A to B)` | The band misses the fit | Pick windings the export holds |
| `autocrop: DIR exists and is not empty` | `demo` will not write over a folder | Give a new folder |
| `autocrop: MESSAGE` | Any other input error above | Read the message |
| `autocrop: ERROR; install numpy, scipy, tifffile, zarr and spiralfiteval` | A package is missing | Install the packages under Needs |
| `autocrop: an umbilicus needs at least two points` | The center line file has fewer than two points | Use the full center line |
| `autocrop: two score files for fit NAME` | `readout` got two score files of one fit | Pass each fit once |
| `autocrop: no NAME zarr under DIR` | The lasagna folder lacks `nx`, `ny` or `grad_mag` | Point `--lasagna` at the folder the fit read |

## How it works

1. **Read.** `export_grids` splits the export into windings by `winding_column_ranges`. The sibling is built as spiralfiteval's `Fit` (grid refined to at most 5 voxels a step, `build_fit_cells`), over windings W0 - 3 to W1 + 3. spiralfiteval's `check_seams` gives the column sense.
2. **Cells.** Every block of `CELL` = 4 rows by 8 columns of a winding with at least one valid vertex, windings W0 to W1.
3. **Signals** (`compute_signals`). seed: each vertex's spiral time on the fit (winding plus column fraction) against the sibling's at its projection (nearest sheet within `TOL_N` = 10 voxels along the normal); after the median offset, the share whose rounded difference is 0. normal: median of the absolute cosine between the fit's grid normal (xy part) and the field's (nx, ny). spacing: per vertex, the radial distance to the inner and outer winding at the same row and angle about the umbilicus, times the cosine between the radial direction and the normal, times the field density `grad_mag` x `DENSITY` (0.14 / 1000 x 4, villa's fitter density per fit voxel); the median of the mean absolute log over both sides. regularity: median over vertices of the largest absolute log ratio of an edge to the winding's median column step.
4. **Rule main** (`scores`, `keep_top`). Percentile ranks (ties averaged; seed and normal higher is better, spacing and regularity lower), their mean, the mean over each cell's 3 by 3 neighbors on its winding, and the top `SHARE` = 0.5 (ties by cell order).
5. **Crops.** 4-connected components of kept cells on each winding, of at least `MIN_CELLS` = 4 cells; each becomes one point collection with one point per cell at `wind_a` 0. The control moves each component along its winding by a random 1 to n - 1 of the winding's n column blocks.
6. **Score** (`score_fit`). The cells holding truth pairs (the zone) and their ring are ranked as in step 4, the top half of the zone kept; a pair counts when both its cells are kept. Random crops draw the same number of zone cells `DRAWS` = 1,000 times; the shuffled control permutes the signals across cells `SHUFFLES` = 50 times.
7. **Readout** (`readout`). A fit is void with under `MIN_PAIRS` = 200 kept pairs or a kept share under `MIN_KEPT_SHARE` = 0.10. VOID when the mean shuffled minus random reaches `CONTROL_MAX` = 0.02; BEATS_CONTROL when the mean G_rand is at least `BAR_G` = 0.05, at least `BAR_ABOVE` = 80 % of fits are above their 97.5th percentile and the mean dw-reweighted gain is positive; NO_GAIN when the mean G_rand is under `NO_GAIN_G` = 0.02 or at least `NO_GAIN_FITS` = 2 fits are under their random mean; otherwise WEAK.

## Cost and time

`demo` with 192 cells: about 2 s (measured 2026-11-05, cloud container). On a PHerc0139 band of 1,024 slices and 34 windings (about 13,400 cells), `crops` took about 4 minutes on a CPU (measured 2026-10-28, cloud container). Memory scales with the sibling's vertices in the band; spiralfiteval needs about 6 GB for a whole 1,000-slice band, and `crops` reads only W0 - 3 to W1 + 3 of the sibling. It needs two spiral fits, which villa runs on a GPU; autocrop itself runs on any CPU and rents nothing.

## For agents

- **Command:** `python3 scripts/autocrop/autocrop.py crops --fit RUN --sibling RUN2 --lasagna LASAGNA --windings W0 W1 --out-dir OUT`; the record is the JSON line on stdout and `OUT/crops-record-NAME.json`.
- **Parse:** `kept_cells`, `components` and `files.crop.points` from the record; the point collections are `OUT/relative_windings_crop_NAME.json`; per-cell values are in `OUT/crops-NAME.json`. For `readout`, `verdict` and `why`.
- **Rerun:** Safe: `crops` gives the same output for the same inputs and seed and overwrites the files of that fit name; `score` and `readout` overwrite `--out`; `demo` refuses a non-empty folder.
- **Success:** Exit 0 and `kept_cells` about half of `cells`; for `demo`, `"check": "PASS"`; for `readout`, verdict BEATS_CONTROL.
- **Not a pass:** A `score` without the random-crop and shuffled controls; a `readout` on fewer than 5 fits or on truth the rule was developed on; kept cells read as correct windings; the crops used as fit inputs and called an improvement without a refit scored against the shifted control.
- **Go-ahead:** Nothing.
- **Never:** Call kept cells or their point collections winding truth or hand annotations; call any output a reading; score on a band and then present that band as a fresh test.

## Tests

`python3 -m unittest tests.test_autocrop` (about 4 s, synthetic data only). With numpy alone: ranks and tie handling (equal to scipy's `rankdata` when scipy is there), smoothing, the top-half rule, random crops, the scorer with good and noise signals, the shuffled control and every readout path, the refusal of a pair table with unknown cells, components, cell points, the shifted control and the point-collection format, and the umbilicus reader. With scipy, tifffile, zarr and spiralfiteval as well: the cell fit equals spiralfiteval's `build_fit`, the demo drops its planted patch and refuses a used folder, and `crops` refuses windings the fit lacks. They do not run a real spiral fit or real truth. On the demo fits, the public `crops` gave the same signals, kept cells and components as the code the tests above used (checked 2026-11-05).

## History

- 2026-11-05: first public release, version 1.0.0 (on top of `cc5f793`), code only, Apache-2.0: rule main, the shifted control, the scorer and readout of the tests, and the synthetic demo; results of the PHerc0139 development, the PHerc0172 test and the PHerc1667 exception test.

## Related

- [`seamswitch`](seamswitch.md): counts a fit's winding switches along traced sheets.
- [Ringleader](ringleader.md): winding labels for a z-slice, and relative-winding ladders for the spiral fit.
- [`windlabel-box`](windlabel-box.md): relative windings from a surface prediction, for the spiral fit.
- [Lasagna Fields](lasagna-fields.md): lasagna fields for many scans, the field autocrop reads.
- [Winding annotations](https://scrollprize.org/winding_annotations): the organizers' page that names auto-cropping as an open avenue.
- [spiralfiteval](https://github.com/jo-tud/spiralfiteval): the fit loader and projection autocrop builds on.
