# labelsuggest: where to paint ink labels next, from where readers' ink maps disagree

`python -m kit labelsuggest map` ranks the tiles of a segment by how much two or more readers' ink maps disagree there and writes the top tiles as a mask to label first, beside matched random and agree tiles and a shuffle control. It reads no label.

| Field | Value |
| --- | --- |
| Id | `labelsuggest` |
| Status | Experimental |
| Kind | kit command, kit module |
| Area | Training |
| Run | `python -m kit labelsuggest map`, `from kit import labelsuggest` |
| Code | `kit/labelsuggest.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_labelsuggest.py` |
| Needs | Python 3.10 or newer (run here on 3.13) and numpy; tifffile for TIFF maps. PNG and .npy maps need nothing more (PNG through kit's `vc3d_io`). No villa, no VC3D, no GPU |
| Runs on | Any CPU. The quick start (five 256 x 256 maps) takes under 1 s; three 2048 x 2048 maps took 1.2 s with `vote` and 0.6 s with `edge`; three 4096 x 4096 maps 5.5 s and 3.3 s, with 1.3 GB peak memory (in memory, 5 shuffles; measured 2026-10-29, shared 4-core cloud container, Python 3.13, numpy 2.5) |
| Network | None |
| Writes | OUT/suggest.json, OUT/label-suggestions.png, OUT/disagreement.png, OUT/random-tiles.png and OUT/agree-tiles.png; nothing else |
| Go-ahead | Not needed: local CPU only, nothing is posted or uploaded |
| Released | Public `main` from the pull request that adds this page (October 2026). The test runners and a VC3D export are not in this repository |
| Release id | `scrolls-kit` |
| Checked | 2026-10-29 against commit `5ad1fa6` |

## What it does

A person painting ink labels has limited time. The organizers name this in their open problems: "active learning, where the model identifies the most uncertain or valuable regions and asks humans to correct only those" (Sourced fact: [Every Herculaneum Scroll Is Still a Challenge](https://scrollprize.org/2026_open_problems), section "Label quality", last updated 14 October 2026, read 29 October 2026). That section is mostly about surface labels; this tool works on ink labels, which are 2D images on a segment.

Where every reader (an ink model whose map you have, such as the organizers' own predictions, `ink_9um` or Reader v2) already agrees, a new label mostly repeats what the models say. Where they disagree, at least one is wrong, so a label there corrects someone. `kit labelsuggest map` scores each pixel's disagreement among the readers, averages it over a fixed grid of square tiles, and writes the top tiles as a mask: paint there first. Beside the suggestion it writes the same number of matched random tiles and of the tiles where the readers agree most, and it runs a shuffle control that says whether the disagreement is concentrated anywhere at all.

Four measures are built in. `vote` (the default) is the committee vote disagreement 4 p (1 - p), where p is the share of readers that call a pixel ink. `margin` is plain uncertainty sampling on the readers' mean probability. `edge` is a simpler pick: it scores a tile by its share of pixels on the edge of the committee's ink call. None of the four reads a label. `rank` is the first version's spread of rank-normalized maps, kept for the record; it is drawn to the dim background and is not recommended.

Two preregistered tests (Checks and controls) found that the top 20 tiles held more of a reader committee's errors than random tiles, on two scrolls. Neither showed that the disagreement measures beat simple label-free picks: on both scrolls plain margin did as well, and on PHerc1667 so did an ink-edge pick. Whether labeling at the suggested tiles saves a person's time has not been tested.

A suggested tile is a place to label, not a claim that the spot is mislabeled or holds ink. Every input is a model's map and nothing here is a reading.

## When to use it

- Before a labeling session on a segment that two or more readers have mapped: label the suggested tiles first, and look at the agree and random tiles as a check.
- To see where readers part: disagreement.png shows the per-pixel disagreement.
- To pick tiles for a second label round when the first round's models are fixed and their maps are on one grid.

Do not use it:

- To score a reader against labels: use `kit auc` with the reverse-depth control ([auc](auc.md)).
- To combine readers into one better map: use `kit ensemble` ([ensemble](ensemble.md)).
- To view several maps and their labels side by side: use `kit view` ([view](view.md)).
- With maps on different grids: put every reader on one grid first (the command refuses).
- On one reader and its own reverse-depth map: disagreement needs independent readers, not a control map.
- With readers that trained on the segment's labels: their agreement is memory, so the suggestion says little.

## Quick start

Run from the repository root. The first block writes five synthetic readers' maps (uint8 ink probabilities); two of them call the opposite of the others inside one 64 px block. No network.

```bash
export D=/tmp/labelsuggest-demo
python3 - <<'EOF'
import os, tifffile
from pathlib import Path
from tests import test_labelsuggest as L
d = Path(os.environ["D"]); d.mkdir(parents=True, exist_ok=True)
maps, _ = L.prob_readers()
for i, m in enumerate(maps):
    tifffile.imwrite(str(d / f"reader{i + 1}.tif"), m)
EOF
python3 -m kit labelsuggest map "$D/out" "$D"/reader*.tif --tile 32 --top 4

# Real use
python3 -m kit labelsuggest map OUT MAP_A MAP_B MAP_C --names NAME_A NAME_B NAME_C --json
```

- `MAP_*`: readers' maps of one segment on one grid (ink probabilities: 0 to 1, uint8 or uint16); `NAME_*`: their names in the record.
- `OUT`: a new or existing folder; the command writes its five files there.

On the synthetic maps (2026-10-29) it printed:

```
4 tiles of 64 suggested; structure targeted (top mean spread 0.96, shuffled max 0.075956); /tmp/labelsuggest-demo/out/suggest.json
```

The four suggested tiles, at (y, x) = (64, 128), (64, 160), (96, 128) and (96, 160), are the planted block. It worked when the exit code is 0 and `structure.verdict` is `targeted`.

## Checks and controls

Controls in every run:

- **Shuffle control.** The disagreement's valid pixels are shuffled `--nulls` times (default 5), which keeps the values and destroys where they lie, and the tiles are rescored. `targeted` when the top tiles' mean beats every shuffle, else `flat`. On the synthetic maps: 0.96 against at most 0.076 (targeted). Readers that agree everywhere come out `flat` (`test_vote_is_flat_without_disagreement_where_rank_is_drawn_to_background_noise`).
- **Control arms.** random-tiles.png (matched random tiles, seeded) and agree-tiles.png (the lowest disagreement) have the same count as the suggestion. On the synthetic maps the suggestion is the planted block (4 of 4 tiles) and the agree arm has 0 of 4 there (`test_vote_finds_planted_disagreement_and_the_controls_do_not`).

Two preregistered tests on public data (Measurement, 29 October 2026). Both used the organizers' own two ink label rounds in the public Scroll Prize ink dataset (the `ink` folder of `scrollprize/datasets` on Hugging Face; [external data](../external.md)): version 1 labels (7 March 2026), version 2 (24 March 2026), and the organizers' model predictions published in the same segment folders and dated between the two rounds, as the committee of readers. An error is a pixel where the committee's call (mean probability at least 0.5) differs from the version 2 label, inside the area that version 2 newly labeled. Lift is the top 20 tiles' mean error share over the average tile's; p is the share of 10,000 random 20-tile picks that reach it. The rule, bar and controls of each were fixed and frozen before its test data was read, and each ran once. The test runners are not in this repository.

| Test | Scroll and segments | Pick tested | Lift of top 20 (bar) | p | Same tiles, other picks (reported only) | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| 1 (attempt 1, first scroll) | PHerc1667, 3 segments, 7 readers each | `vote` | 3.82, geometric mean (1.5) | 0.0001 in each segment | edge 4.17, margin 4.08, ink density 1.26 | PASS |
| 2 (attempt 2 at a second scroll) | PHerc0841 ag896, 1 segment, 3 readers, 108 tiles | `edge` | 1.84 (1.5) | 0.0005 | margin 1.96, vote 1.87, ink density 1.14 | PASS |

- **Controls of test 1, all held:** pixel shuffle geometric mean 0.935 (band 0.8 to 1.25); planted disagreement found at least 17 of 20 in every segment (bar 15); committee AUC 0.922 to 0.978 in place against 0.743 to 0.767 with the labels moved 32 px. A fourth segment was lost to a runner fault (a reader on another grid), fixed after the readout; the frozen rule allowed a verdict on three.
- **Controls of test 2, all held:** planted tiles found 20 of 20 (bar 15); the same scores moved one tile along found 0 (at most 5 allowed); scores permuted across tiles gave a mean lift of 1.00 (band 0.8 to 1.25); committee AUC 0.934 in place against 0.685 with the labels moved 32 px.

What the tests say, in the words fixed before test 2 ran: "On a second scroll (PHerc0841 ag896, one segment, three March readers), the 20 tiles a label-free ink-edge pick suggested held at least B times the average share of the committee's disagreements with the organizers' later labels (p below 0.05 against random 20-tile picks)", with B = 1.5. Test 2 was attempt 2 at a second-scroll test (the first design was never frozen, so no data was spent on it), and the edge pick was chosen on test 1's segments, already used, after a misplacement control fixed in advance failed and was made reported only once its numbers were seen.

What they do not say:

- That the disagreement measures beat simple picks. On PHerc1667 the label-free edge pick (4.17) and margin (4.08) lifted at least as much as `vote` (3.82). On PHerc0841 margin and vote lifted as much as edge or more. No comparison between picks was a preregistered claim, so none is claimed.
- That any label is wrong. An error here is a model call that the later labels disagree with.
- That labeling at these tiles saves a person's time. That needs a timed test with people, not run.
- Anything beyond these readers: the committees are the organizers' own predictions, one of the three on PHerc0841 a prediction whose file name says "reverse". The organizers may have looked at these predictions while labeling version 2, and the latest predictions may have trained on interim version 2 labels (both disclosed before the tests, untested).

Neither scroll is eligible for the open First Letters or Grand Prize ([`kit/data/prizes-2026-10-11.json`](../../kit/data/prizes-2026-10-11.json)); both label rounds are published. Numbers: `label_suggest_checks` in [`docs/results.json`](../results.json).

Claim label: Model output for the suggestions and disagreement maps (arithmetic on readers' maps); Measurement for the two tests above (two scrolls, the organizers' committees, errors judged by their later labels); Untested idea that labeling at suggested tiles saves a person's time.

## Commands and options

### `python -m kit labelsuggest map`

```
usage: python -m kit labelsuggest map [-h] [--names NAMES [NAMES ...]]
                                      [--valid VALID] [--tile TILE]
                                      [--top TOP] [--min-valid MIN_VALID]
                                      [--seed SEED] [--nulls NULLS]
                                      [--measure {vote,rank,margin,edge}]
                                      [--cut CUT] [--json]
                                      out maps [maps ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | output folder (created): suggest.json and the PNG masks |
| `maps` | required | two or more readers' maps on one grid (.tif, .png, .npy) |
| `--names NAMES ...` | none | one name per map (default: file stems) |
| `--valid VALID` | none | mask of pixels to consider (nonzero = valid) |
| `--tile TILE` | `64` | tile side in map pixels |
| `--top TOP` | `20` | tiles to suggest |
| `--min-valid MIN_VALID` | `0.5` | least share of valid pixels for a tile to count |
| `--seed SEED` | `0` | seed of the random arm and the shuffles |
| `--nulls NULLS` | `5` | pixel shuffles of the structure control |
| `--measure MEASURE` | `vote` | vote: share of readers voting ink, 4p(1-p); margin: committee mean near the cut; edge: share of committee ink edge pixels; rank: version 1's rank spread |
| `--cut CUT` | `0.5` | ink probability cut of vote, margin and edge |
| `--json` | off | print the whole record |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `SuggestError()` | exception | | A bad input or option; the message says why. A `ValueError` |
| `load_map(path)` | 2D float32 array | SuggestError | A 2D float32 array from a TIFF, PNG or .npy file (the first page or channel of anything with more). |
| `midranks(a, valid)` | float32 array, same shape | none | Each valid pixel's mid-rank among the valid pixels, scaled to 0..1 (ties share their mean rank); 0 elsewhere. |
| `spread(maps, valid)` | (spread array, stacked ranks) | none | Per-pixel population standard deviation of the readers' mid-ranks (0 outside valid), and the ranks. |
| `value_scale(top)` | 1.0, 255.0, 65535.0 or None | none | The value rule: the full scale implied by a map's largest value (1 when at most 1, else 255, else 65535), or None past 65535 |
| `full_scale(a, valid)` | 1.0, 255.0 or 65535.0 | SuggestError | The map value that means probability 1: 1 when the largest valid value is at most 1, else 255, else 65535. |
| `disagreement(maps, valid, measure='vote', cut=0.5)` | (disagreement array, full scales or None) | SuggestError | Per-pixel disagreement among the readers (0 outside valid) under `measure`, and each map's full scale (None for rank) |
| `ink_edge(call, valid)` | float32 array (0 or 1) | none | 1 where the call differs from a 4-neighbor, both pixels valid, else 0 (the `edge` measure). |
| `tile_scores(s, valid, tile, min_valid)` | list of (y, x, mean, valid share) | SuggestError | [(y, x, mean spread over its valid pixels, valid share)] for every tile with at least min_valid valid. |
| `suggest(maps, names=None, valid=None, tile=None, top=None, min_valid=None, seed=None, nulls=None, measure=None, cut=None)` | (result dict, disagreement array, valid mask) | SuggestError | Suggestions from in-memory maps (same shape). Returns (result dict, spread array, valid mask). |
| `run_map(out, paths, names=None, valid_path=None, **cfg)` | the result dict, also OUT/suggest.json | SuggestError | `kit labelsuggest map`: read the maps, suggest, write OUT's files. Returns the result dict. |
| `load_result(path)` | the suggest.json record | SuggestError | A suggest.json record, checked for its kind and version. |
| `build_parser(p)` | None | none | Add the `map` action to an argparse parser. |
| `cmd_labelsuggest(a)` | exit code | none | Run the parsed action; 0 done, 2 an input problem (the message is on stderr). |
| `main(argv=None)` | exit code | none | `python -m kit.labelsuggest`. |

## Inputs

- **Maps:** two or more 2D readers' maps of one segment on one grid: .tif or .tiff (through tifffile), 8-bit PNG, or .npy. An RGB image gives its first channel and a stack its first page. For `vote`, `margin` and `edge` each map is an ink probability: 0 to 1, or uint8 (0 to 255), or uint16 (0 to 65535), by the full-scale rule (`full_scale`); larger values are refused. For `rank` any range works, since only ranks are used.
- **`--valid`:** optional mask on the same grid (nonzero = consider). Without it a pixel counts when it is finite in every map and nonzero in at least one (a render's empty margin is zero everywhere); with it, both must hold.
- **Where to get maps:** the organizers publish predictions beside each segment's labels in the Scroll Prize ink dataset (the `ink` folder of `scrollprize/datasets` on Hugging Face; [external data](../external.md)) (`preds/`), or run released readers on a segment's render. Maps must cover the same pixels; resample or crop first.
- **Size:** memory grows with pixels and readers: about 1.3 GB peak for three 4096 x 4096 maps (Cost and time).

## Outputs

It prints one line (below), or the whole record with `--json`, and writes five files in OUT:

```
4 tiles of 64 suggested; structure targeted (top mean spread 0.96, shuffled max 0.075956); OUT/suggest.json
```

`suggest.json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `kind`, `version` | str, int | `kit-labelsuggest`, 2 (version 1 records, rank only, still load) |
| `readers`, `inputs` | list | names; each map's name, path and SHA-256 |
| `valid_mask` | object | with `--valid`: its path and SHA-256 |
| `shape` | [H, W] | the maps' grid in pixels |
| `settings`, `settings_digest` | object, str | tile, top, min_valid, seed, nulls, measure, cut; SHA-256 over them and the version |
| `full_scales` | list or null | each map's full scale (1, 255 or 65535); null for `rank` |
| `valid_pixels`, `tiles_eligible` | int | pixels considered; tiles with at least `min_valid` valid |
| `top` | list | `rank`, `y`, `x`, `h`, `w` (pixels), `spread` (the tile's mean disagreement: 0 to 1, or 0 to 0.5 for rank), `valid_share` |
| `controls.random`, `controls.agree` | list | the control arms, same fields and count as `top` |
| `structure` | object | `top_mean_spread`, `null_top_means`, `null_max`, `nulls`, `verdict` (`targeted`, `flat`, or `unchecked` with 0 nulls), `rule` |
| `files` | object | the four PNG paths |
| `note` | str | the claim label of the record |
| `seconds` | float | wall time of the run |

PNGs: label-suggestions.png, random-tiles.png and agree-tiles.png are 8-bit grey masks (255 inside a tile, 0 elsewhere). disagreement.png is the disagreement times 255 (times 510 for `rank`), clipped to 255. All are on the maps' grid, pixel for pixel.

| Exit code | Meaning |
| --- | --- |
| `0` | done: the five files were written and the line or record printed |
| `2` | an argument or input problem: the message on stderr says which |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `labelsuggest:...` | every input problem below is printed with this prefix on stderr, exit code 2 | read the rest of the line |
| `...: not a 2D map (shape...)` | the file holds an image the loader cannot reduce to 2D | pass a 2D map |
| `a map's values reach...: give probabilities (0..1, uint8 or uint16), or use --measure rank` | a map's values pass 65535, so it is not a probability map | rescale it to 0..1, or use `--measure rank` |
| `measure must be one of...` | an unknown measure through the Python API | use vote, margin, edge or rank |
| `cut must lie strictly between 0 and 1` | `--cut` at or outside 0 or 1 | pick a cut inside (0, 1) |
| `map...x...is smaller than one...px tile` | the map is smaller than one tile | lower `--tile` |
| `disagreement needs at least two readers' maps` | one map given | pass two or more readers |
| `maps differ in shape...: put every reader on one grid first` | maps of different shapes | resample or crop every map to one grid |
| `tile >= 4, top >= 1, 0 < min_valid <= 1 and nulls >= 0` | an option out of range | fix the option |
| `one distinct name per map` | `--names` count or duplicates | give one distinct name per map |
| `...: not a kit labelsuggest record of version...` | `load_result` was given another JSON file | point it at a suggest.json from `map` |
| `...: not a readable suggest.json (...)` | `load_result` found no file or no JSON | point it at OUT/suggest.json |
| `kit labelsuggest needs numpy` | numpy missing | install numpy |
| `...: read .tif, .tiff, .png or .npy maps` | another file type | convert the map |
| `reading TIFF maps needs tifffile` | tifffile missing | install tifffile, or pass PNG or .npy |

## How it works

1. Load each map as float32 (`load_map`) and the valid mask (step above).
2. Disagreement per pixel (`disagreement`). For `vote`, `margin` and `edge`, each map is divided by its full scale (`full_scale`). `vote`: each reader calls ink where its probability reaches `cut` (`DEFAULTS["cut"]`, 0.5); the disagreement is 4 p (1 - p) for the share p calling ink (0 when all agree, 1 at an even split), a vote disagreement in the manner of query by committee. `margin`: 1 - 2 |m - cut|, clipped at 0, for the mean probability m. `edge`: the committee call (m at or above `cut`) and `ink_edge`, 1 where the call differs from a valid 4-neighbor. `rank`: each map's mid-rank over the valid pixels (ties share a rank), then the population standard deviation of the readers' ranks.
3. Tiles (`tile_scores`): non-overlapping `tile` px squares from the top left (`DEFAULTS["tile"]`, 64; a partial last row or column is dropped). A tile counts when at least `min_valid` (0.5) of its pixels are valid; its score is the mean disagreement over its valid pixels.
4. Suggestion: the `top` (20) highest scores, ties to the earlier tile. Controls: `top` random eligible tiles (numpy `default_rng(seed)`) and the `top` lowest.
5. Shuffle control: `nulls` (5) permutations of the valid disagreement values (`default_rng(seed + 1)`), each rescored the same way; `targeted` when the top tiles' mean beats every permutation's.
6. Write the four PNGs (kit's own PNG writer, no Pillow) and suggest.json with each input's SHA-256.

## Cost and time

Local CPU only; nothing is rented. Time and memory grow with pixels and readers: under 1 s for the quick start; three 2048 x 2048 maps 1.2 s (`vote`) and 0.6 s (`edge`); three 4096 x 4096 maps 5.5 s and 3.3 s with 1.3 GB peak (in memory, 5 shuffles; measured 2026-10-29, shared 4-core cloud container). The shuffles and, for `rank`, the ranks take most of it. File reading adds to this and was not measured on whole segments. A whole segment of many readers can need several GB; crop to the area you will label.

## For agents

- **Command:** `python -m kit labelsuggest map OUT MAP_A MAP_B [MAP_C ...] --names A B C --json`
- **Parse:** `structure.verdict`; `top` (tiles in map pixels: `y`, `x`, `h`, `w`, `spread`); `controls.random` and `controls.agree`; `files` (the PNG paths); `settings_digest`
- **Rerun:** safe: the same inputs and settings give the same tiles; a rerun overwrites OUT's five files
- **Success:** exit 0 and `structure.verdict` `targeted`
- **Not a pass:** `flat` (no better than random spots); maps from one reader and its own reverse control (not independent readers); readers that trained on the segment's labels (their agreement is memory); any claim that the suggestion beats an ink-edge or margin pick (not shown)
- **Go-ahead:** Nothing for local runs
- **Never:** call a suggested tile a finding, a reading or evidence of ink or of a label error; run it on prize-eligible target scrolls and publish the result

## Tests

`python3 -m unittest tests.test_labelsuggest` (13 tests, under 1 s): tied ranks and scale invariance, identical readers, the planted block found with the agree and random arms not, the `flat` verdict without disagreement, the valid mask and argument errors, the files `map` writes (mask pixels, the control PNGs, the record read back and a foreign record refused), the command line's printed line and its exit code 2, the full-scale and value rules, `vote` and `margin` finding planted disagreement, `vote` flat where `rank` is drawn to background noise, `edge` scoring a square's border, and the cut and measure checks. Not covered: real readers' maps; the two tests in Checks and controls ran outside this repository's test suite.

## History

- 2026-10-30: on public `main` (on top of `5ad1fa6`): the `map` action with the `vote`, `margin`, `edge` and `rank` measures, after the two tests in Checks and controls. The test runners and a VC3D export are not in this repository.

## Related

- [auc](auc.md): score a reader against labels with the reverse-depth control.
- [ensemble](ensemble.md): combine readers' maps into one.
- [view](view.md): look at several maps, their disagreement and the labels on one page.
- [labels](labels.md): which published ink labels exist per segment and which public models trained on them.
- [`docs/results.json`](../results.json): `label_suggest_checks`, the two tests behind Checks and controls.
