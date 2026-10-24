# heldout: apply Hecate's published split rule to a segment's label masks

`scripts/heldout/hecate_split.py` applies the train and validation split rule of the team's published Hecate trainer to one segment's label masks and prints, as JSON, how many training patches the rule gives and what share of the supervised pixels lies under them.

| Field | Value |
| --- | --- |
| Id | `heldout` |
| Status | Current |
| Kind | script folder |
| Area | Scoring and controls |
| Run | `python scripts/heldout/hecate_split.py` |
| Code | `scripts/heldout/` |
| Tests | `tests/test_hecate_split.py` |
| Needs | Python 3.10 or newer and numpy. To read the dataset's LZW-compressed TIFF masks: tifffile with imagecodecs, or Pillow (tifffile without imagecodecs refuses LZW and the script then reads with Pillow; run 2026-10-17 with numpy 2.5.3, tifffile 2026.10.15 without imagecodecs and Pillow 12.3.0). No scipy, torch or villa. The label masks themselves, downloaded beforehand from the ink dataset the Hecate card cites (Inputs) |
| Runs on | Any CPU. 0.27 to 0.59 s per call on small synthetic masks of 2048 x 2048 to 4096 x 5120 px (measured 2026-10-17, 4-core Intel Xeon cloud container at 2.80 GHz, Python 3.13). On the full-size published masks of six segments, "a few minutes in all", CPU only ([exposure log](../logs/2026-10-16-reader-exposure.md), 2026-10-16, machine not recorded) |
| Network | None. It reads local files only; downloading the masks is a separate step |
| Writes | Nothing (prints one JSON line per segment to stdout) |
| Go-ahead | Not needed: it reads published label masks and prints. Asking Hecate's authors for their archived manifest, the one thing that would settle what the released run used, is an outward step and needs Chase's yes |
| Released | Not on public `main` yet (checked 2026-10-17): on branch `claude/project-thread-8zzi1i` since 2026-10-16 (`f15045e`), in the open [PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100) |
| Guide | [Reader exposure log](../logs/2026-10-16-reader-exposure.md): measurement M1, its numbers, sources and limits |
| Checked | 2026-10-17 against commit `1b620c6` |

## What it does

A score on a labeled segment tests an ink reader only when the reader's training data left that segment out. For Hecate, the team's released ink reader (model card [scrollprize/hecate](https://huggingface.co/scrollprize/hecate)), no training list was published: its trainer builds the split itself from the label masks of the ink dataset the card cites, `hf://buckets/scrollprize/datasets/ink`, and the manifest it wrote for the released run is not public.

This script ports that split rule, numpy only, from the trainer the team published on villa branch `distilled_3d_ink`, commit `5ff00ca0`, file `vesuvius/src/vesuvius/ink_detection/data/multiteacher.py` ([source](https://github.com/ScrollPrize/villa/blob/5ff00ca0/vesuvius/src/vesuvius/ink_detection/data/multiteacher.py)). Given one segment's supervision mask (the pixels a label set covers), its validation mask when the dataset has one, and its ink labels, it says which 256 px patches the rule would make training patches, which it would make validation patches, whether the segment is validation only (no training patch at all), and how many supervised and supervised-ink pixels lie under training patches. The folder holds this one script, `hecate_split.py`.

It answered one question on 2026-10-16: the three PHerc0841 label sets (w00, ag896, ag405) have every supervised pixel inside their validation masks, so the rule gives them zero training patches, while PHerc0139 w045 gets 86.8 % of its supervised pixels under training patches ([exposure log](../logs/2026-10-16-reader-exposure.md), measurement M1). Those findings feed the `held_out` text and the `held_out_by_reader` words in `docs/results.json`, which the [leaderboard](leaderboard.md) prints.

It does not say what the released run did: that the archived manifest used this rule's split is Interpretation, and Hecate can still have seen PHerc0841 through its starting weights (the exposure log keeps PHerc0841 not held out from Hecate for that reason). It reads label masks only, never CT, renders or ink maps, and it scores nothing. Its counts are a computation on published inputs, not model output, and nothing it prints is a reading of any text.

## When to use it

- To check how the published Hecate rule splits a labeled segment before using that segment as a test of Hecate, or of a reader started from Hecate's weights.
- To redo or extend measurement M1 of the exposure log, for example on a newly published label set, another label version (`--suffix`) or another seed (`--seed`) for a segment without a validation mask.

Do not use it:

- To decide whether another reader (`ink_9um`, v8in, v8in-1447, d9v2, Reader v2) trained on a segment: read its own published training list; the exposure log's matrix and `held_out` in `docs/results.json` hold them.
- To score a reader on a segment: use [auc](auc.md).
- To see which readers are held out on the benchmark segments, with their scores: read the board from [leaderboard](leaderboard.md).
- As proof of what the released Hecate run trained on: only the archived manifest shows that.

## Quick start

```bash
python scripts/heldout/hecate_split.py DIR PREFIX:IDENTITY
```

`DIR` is a folder holding `PREFIX_supervision_mask_v2.tif`, and, when the dataset has them, `PREFIX_validation_mask_v2.tif` and `PREFIX_inklabels_v2.tif`. `IDENTITY` is the trainer's `scroll/folder` name, such as `841/w00`.

Run on 2026-10-17 on small synthetic masks written with tifffile for this page (not dataset files): `valonly`, 2048 x 2048 px, with the validation mask over all the supervision, as on PHerc0841, and `corner`, 2048 x 4096 px, all supervised, with a 512 px validation square in one corner, as on a training segment. `python scripts/heldout/hecate_split.py SCRATCH/masks valonly:841/valonly corner:0139/corner` (`SCRATCH` is a scratch folder) printed, in 0.32 s:

```
{"segment": "valonly", "identity": "841/valonly", "suffix": "_v2", "shape": [2048, 2048], "supervised_px": 2240000, "supervised_in_validation_px": 2240000, "validation_px": 3060000, "holdout": "validation mask", "generated_blocks": 0, "train_patches": 0, "val_patches": 64, "validation_only": true, "supervised_px_in_training_patches": 0, "supervised_ink_px": 40000, "supervised_ink_px_in_training_patches": 0, "share_supervised_in_training_patches": 0.0, "share_supervised_in_validation": 1.0}
{"segment": "corner", "identity": "0139/corner", "suffix": "_v2", "shape": [2048, 4096], "supervised_px": 8388608, "supervised_in_validation_px": 262144, "validation_px": 262144, "holdout": "validation mask", "generated_blocks": 0, "train_patches": 429, "val_patches": 4, "validation_only": false, "supervised_px_in_training_patches": 7798784, "share_supervised_in_training_patches": 0.9297, "share_supervised_in_validation": 0.0312}
```

It worked when the exit code is 0 and there is one JSON line per `PREFIX`. The same masks saved with LZW compression through Pillow gave the same `valonly` line, read through the Pillow fallback. For the published PHerc0841 masks, the exposure log gives the exact commands and the mask hashes to compare with.

## Checks and controls

- **The rule can fail, and the control shows it.** On segments with a small validation block the same code gives training patches: 627 for PHerc0139 w045 (trainer identity `0139/w029_202601261946`, 86.8 % of supervised pixels under training patches) and 415 for the PHerc0814 control (`814/814_46527_2um_try2`, 62.6 %), against 0 for each of the three PHerc0841 sets ([exposure log](../logs/2026-10-16-reader-exposure.md), measurement M1, 2026-10-16). The synthetic run in Quick start shows the same split: `validation_only` true for `valonly`, 429 training patches and 0.9297 for `corner`.
- **The port is tested against hand counts and a brute-force filter.** `box_any` equals a written-out `scipy.ndimage.maximum_filter(mode="constant")`; hand-counted cases pin the 5 % threshold (12 supervised cells of 256 fail, 13 pass), the training stride of half a patch, the whole-patch validation stride and the validation rule; `stable_seed` matches the trainer's formula; and `test_small_validation_mask_keeps_training_patches_outside_the_guard` is the case that must give training patches, all at least 256 px from the validation square.
- **A seed check for generated holdouts.** Where a segment has no validation mask, the holdout depends on the seed and on `IDENTITY`. The exposure log ran seeds 0 to 39 on w043: the share of supervised pixels under training patches ran from 68.2 % to 93.7 %. On the synthetic 4096 x 5120 px mask of 2026-10-17, seeds 27 and 3 gave 0.8094 and 0.8125.
- **What it cannot check:** that the released run used this split. The trainer's guide says a new manifest "creates a new split, not a reproduction of an archived run", and the archived one is not public.

Claim label: Sourced fact, for the inputs (the published masks) and the rule (ported from villa `5ff00ca0`); the counts are our computation on them, not model output; that Hecate's released run used this split is Interpretation.

## Commands and options

### `python scripts/heldout/hecate_split.py`

```
  python3 scripts/heldout/hecate_split.py DIR PREFIX[:IDENTITY] [...] [--suffix _v2] [--seed 27]
```

That is the usage line of the script's docstring, which it prints on stderr, with exit code 2, when given fewer than two arguments, `--help` alone included. It does not use argparse: `--suffix` and `--seed` may stand anywhere, and every other argument is `DIR` (the first) or a `PREFIX` (the rest), even one that starts with `-`.

| Option | Default | Meaning |
| --- | --- | --- |
| `DIR` | required | The folder that holds the segments' mask TIFFs |
| `PREFIX[:IDENTITY]` | required, one or more | `PREFIX` is the start of the segment's file names (`w00` for `w00_supervision_mask_v2.tif`). `IDENTITY`, after a colon, is the trainer's `scroll/folder` name, such as `841/w00` or `0139/w043_2026011217`; it seeds the generated holdout and matters only when the segment has no validation mask. Without it, `PREFIX` is used in its place, and the JSON says `"identity": null` |
| `--suffix SUFFIX` | `_v2` | The label version at the end of every file name. `--suffix ""` reads unversioned files, such as w043's. It applies to every `PREFIX` in the call |
| `--seed SEED` | `27` (`SEED`, the default of the trainer's `prepare_manifest`) | Integer seed of the generated holdout; it changes nothing when the segment has a validation mask with any pixel set |

## Python API

The tests import the script as a module, as below; nothing else does.

```python
import sys; sys.path.insert(0, "scripts/heldout")
import hecate_split as H
r = H.split(sup, val, ink, identity="841/w00")      # 2D masks at full resolution; val and ink may be None
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `stable_seed(*parts)` | int, the first 8 bytes of the SHA-256 of the parts joined by `:`, big-endian | Nothing | The trainer's own formula, so block order matches it |
| `max_pool_mask(mask, factor=MASK_FACTOR)` | 2D bool array of 16 px cells, `ceil(h/16)` by `ceil(w/16)` | Nothing | A cell is set when any of its pixels is nonzero; the edge is padded with zeros |
| `cell_counts(mask, factor=MASK_FACTOR)` | 2D int64 array, nonzero pixels per cell | Nothing | Same grid as `max_pool_mask` |
| `box_any(mask, size)` | 2D bool array | Nothing | Dilation by a `size` x `size` box, zeros outside; the same mask as `scipy.ndimage.maximum_filter(mask, size, mode="constant")` for an odd `size` |
| `spatial_holdout(support, seed, identity, block_size=1024)` | (bool cell mask, list of `[block_y, block_x]`) | `ValueError` when the support touches fewer than 2 blocks | 10 % of the 1024 px blocks holding any supervised cell, at least 1, in `stable_seed(seed, identity, by, bx)` order |
| `patch_coordinates(support, heldout, shape_yx, patch=PATCH, guard=GUARD)` | (training patch corners, validation patch corners), each an `N` x 2 int32 array of `[y, x]` in pixels | Nothing | Training: every 128 px, at least 5 % of the patch's cells supported, footprint clear of the holdout dilated by the guard. Validation: every 256 px, any cell both held out and supported |
| `split(sup, val=None, ink=None, *, identity="", seed=SEED)` | dict, the JSON fields under Outputs except `segment`, `identity` and `suffix` | `ValueError` from `spatial_holdout`, or from numpy when the masks' shapes differ | One segment's split and coverage counts |
| `main(argv)` | int, the exit code (0 or 2) | Anything the file reads raise (Failure modes) | `argv` without the program name |

Module constants: `MASK_FACTOR` = 16 (px per cell), `PATCH` = 256 (px), `GUARD` = 256 (px), `SEED` = 27. `_read(path)` reads one mask TIFF (Inputs).

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| `DIR/PREFIX_supervision_mask{SUFFIX}.tif` | Single-page 2D TIFF, any integer dtype; nonzero means supervised | Required. Full resolution, as published: each segment's surface grid at 2.2 to 2.4 um per pixel (the trainer's `SPACING`), rows (`y`) down and columns (`x`) across |
| `DIR/PREFIX_validation_mask{SUFFIX}.tif` | As above; nonzero means validation | Optional. Without it, or with no pixel set, the holdout is generated (How it works) |
| `DIR/PREFIX_inklabels{SUFFIX}.tif` | As above; nonzero means ink | Optional. Without it the two `supervised_ink_*` fields are left out |

All masks of one segment must have the same shape; the script does not check, and numpy stops with a broadcast error when they differ. A 3D array is cut to its first page, or to its first channel when the last axis has 3 or 4 values. Masks are read whole into memory. w043's canvas, the one size the exposure log gives, is 23,760 x 31,680 px: about 753 MB per mask at one byte per pixel (arithmetic from that size). LZW-compressed files need imagecodecs for tifffile, or Pillow.

Where to get them: each segment's folder of the ink dataset, `https://huggingface.co/buckets/scrollprize/datasets/resolve/ink/<scroll>/<folder>/<file>`, where `<scroll>` is one of the trainer's eight scroll ids (`0009b`, `0139`, `0500p2`, `1667`, `814`, `841`, `man5`, `phercparis4`) and `IDENTITY` is `<scroll>/<folder>`. Keep them outside git (the no-data rule, hard rule 6). The trainer uses the highest label version that has both ink labels and a supervision mask: `_v2` for the segments in the exposure log, except w043, which is unversioned.

## Outputs

One JSON object per `PREFIX`, one per line on stdout, in the order given. Pixel counts are full-resolution pixels; "under training patches" means inside the 256 px footprint of at least one training patch.

| Field | Type | Meaning |
| --- | --- | --- |
| `segment` | str | `PREFIX` |
| `identity` | str or null | `IDENTITY` as given; null when none was given, although `PREFIX` then seeded the holdout |
| `suffix` | str | The `--suffix` used |
| `shape` | list of 2 int | Supervision mask height and width, px |
| `supervised_px` | int | Nonzero pixels of the supervision mask |
| `supervised_in_validation_px` | int | Pixels nonzero in both supervision and validation masks. Only when the validation mask has any pixel |
| `validation_px` | int | Nonzero pixels of the validation mask. Only when it has any |
| `holdout` | str | `validation mask`, or `generated blocks (no validation mask)` |
| `generated_blocks` | int | How many 1024 px blocks were generated as holdout; 0 with a validation mask. Their positions are not printed (`spatial_holdout` returns them) |
| `train_patches` | int | Training patches the rule gives |
| `val_patches` | int | Validation patches the rule gives |
| `validation_only` | bool | True when `train_patches` is 0, as the trainer records it |
| `supervised_px_in_training_patches` | int | Supervised pixels under training patches |
| `supervised_ink_px` | int | Ink-label pixels inside the supervision mask. Only with ink labels |
| `supervised_ink_px_in_training_patches` | int | Of those, the ones under training patches. Only with ink labels |
| `share_supervised_in_training_patches` | float, 0 to 1, 4 decimals | `supervised_px_in_training_patches` over `supervised_px` (over 1 when there is no supervised pixel) |
| `share_supervised_in_validation` | float, 0 to 1, 4 decimals | `supervised_in_validation_px` over `supervised_px`. Only with a validation mask |

| Exit code | Meaning |
| --- | --- |
| `0` | Every `PREFIX` was split and printed |
| `1` | A Python error with a traceback (Failure modes). Segments before the failing one were already printed; the rest were not |
| `2` | Fewer than two arguments, `--help` alone included: the docstring is printed on stderr |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| The script's docstring on stderr, exit code 2 | Fewer than `DIR` and one `PREFIX`, or `--help` alone | Give `DIR` and at least one `PREFIX` |
| `ValueError: Not enough spatial blocks to split IDENTITY` and a traceback, exit code 1 | No validation mask (or an empty one), and the supervision touches fewer than two 1024 px blocks, so no holdout can be generated. The trainer refuses such a segment the same way | Check `PREFIX` and `--suffix`; a segment that small cannot be split by this rule |
| `FileNotFoundError: [Errno 2] No such file or directory: 'DIR/PREFIX_supervision_mask_v2.tif'` and a traceback, exit code 1 | No supervision mask under that name: a wrong `DIR` or `PREFIX`, or unversioned file names without `--suffix ""` | Fix the path, prefix or suffix |
| `FileNotFoundError: ... '--help_supervision_mask_v2.tif'` and a traceback, exit code 1 | `--help` after `DIR`: every argument except `--suffix` and `--seed` is taken as a `PREFIX` | Run it with `--help` alone, or read Commands and options |
| `StopIteration` and a traceback, exit code 1 | `--suffix` or `--seed` as the last argument, with no value | Give the value: `--suffix ""`, `--seed 27` |
| `ValueError: invalid literal for int() with base 10: 'x'` and a traceback, exit code 1 | `--seed` not an integer | Give an integer |
| `ValueError: operands could not be broadcast together with shapes (128,128) (128,129)` and a traceback, exit code 1 | A segment's masks differ in shape | Use masks of one label version of one segment; the trainer itself refuses label sets whose geometries disagree |
| `ModuleNotFoundError: No module named 'numpy'` | numpy is not installed | `pip install numpy` |
| `ModuleNotFoundError: No module named 'PIL'` and a traceback | tifffile is missing, or cannot read LZW without imagecodecs, and Pillow is missing too | `pip install tifffile imagecodecs`, or `pip install pillow` |

## How it works

Each step follows the trainer at `5ff00ca0`; the line numbers are those the script's docstring cites in `multiteacher.py`.

1. `_read` loads each TIFF with tifffile, and on `ImportError` or `ValueError` (LZW without imagecodecs) with Pillow, its pixel limit lifted.
2. `max_pool_mask` (lines 47 to 53) turns each mask into 16 px cells (`MASK_FACTOR` = 16): a cell is set when any of its pixels is. A tiny validation mark therefore cannot vanish.
3. The holdout (`prepare_manifest`, lines 184 to 215): the pooled validation mask when it has any cell set, and then the scanned support is supervision or validation together. Otherwise `spatial_holdout` (lines 98 to 108) takes the 1024 px blocks (64 cells) that hold any supervised cell, orders them by `stable_seed(seed, identity, block_y, block_x)` and keeps the first 10 %, rounded, at least 1; fewer than 2 blocks is an error.
4. `patch_coordinates` (lines 111 to 134) dilates the holdout by the guard, `ceil(GUARD / 16)` = 16 cells each side (a 33-cell box, with `box_any` in place of scipy's `maximum_filter`). Training patches are 256 px windows (`PATCH`, 16 cells) every 128 px whose supported cells are at least 5 % of 256 (so 13 cells) and that touch no dilated holdout cell. Validation patches are windows every 256 px that hold any cell both held out and supported.
5. `validation_only` is true when there is no training patch, as the trainer records it (line 214).
6. Coverage, which the trainer does not compute: every cell under a training window is marked, and the per-cell counts of supervised pixels, and of ink pixels inside supervision, are summed over the marked cells.

Where the port differs from the trainer, checked against the trainer's file on 2026-10-17:

- It reads TIFF files only; the trainer opens the label Zarr arrays and uses the TIFF beside each when there is one, after checking that the two agree.
- It takes the canvas from the supervision mask and checks no geometry; the trainer refuses label and CT geometries that disagree.
- It does not choose the label version: give `--suffix`.
- It reports a segment with zero validation patches; the trainer refuses it (`Empty train/validation partition`).
- It prints the number of generated blocks, not their positions, which the trainer stores in its manifest.

## Cost and time

Measured 2026-10-17 in a 4-core Intel Xeon cloud container at 2.80 GHz with Python 3.13 and numpy 2.5.3, on synthetic masks: 0.27 to 0.38 s for two segments of 2048 x 2048 and 2048 x 4096 px (3 runs, peak resident memory about 79 MB) and 0.27 to 0.59 s for one of 4096 x 5120 px with a generated holdout (3 runs, about 96 MB). On the full-size published masks the exposure log reports a few minutes in all for its six segments, CPU only (2026-10-16, machine not recorded); peak memory on full-size masks is Not measured. It needs no GPU and stays far below the hour of CPU after which the Modal rule (hard rule 11) sends a job to Modal, so it runs locally. On Chase's Mac, wrap a run as `python -m kit run local SLUG -- COMMAND`, where `SLUG` names the ledger entry and `COMMAND` is the script's command line (the local-compute rule, hard rule 9). It rents nothing.

## For agents

- **Command:** `python scripts/heldout/hecate_split.py DIR PREFIX:IDENTITY [PREFIX:IDENTITY ...] [--suffix SUFFIX] [--seed SEED]`. The output is already machine-readable: one JSON object per line.
- **Parse:** per line, `segment`, `holdout`, `train_patches`, `val_patches`, `validation_only` and `share_supervised_in_training_patches`; with a validation mask, `share_supervised_in_validation`; with ink labels, `supervised_ink_px_in_training_patches` of `supervised_ink_px`.
- **Rerun:** Safe and deterministic: the same masks, suffix, seed and identity give the same output. It writes nothing.
- **Success:** Exit code 0 and one JSON line per `PREFIX`.
- **Not a pass:** `validation_only` true does not mean Hecate never saw the segment: the released run's manifest is not public, and its starting weights can carry the segment (PHerc0841's case). A generated holdout's numbers hold only for that seed and that `IDENTITY`; a run with no `IDENTITY` uses `PREFIX`, which is not the trainer's name. Numbers from masks of the wrong label version do not describe the trainer's split.
- **Go-ahead:** Nothing for running it. Asking the trainer's authors for the archived manifest needs Chase's yes (the go-ahead rule, hard rule 8).
- **Never:** Commit the masks (the no-data rule, hard rule 6); call a segment held out from Hecate on this output alone; run it on target-scroll material for a public note (the no-findings rule, hard rule 1).

## Tests

```bash
python -m unittest tests.test_hecate_split -v
```

15 tests in 0.64 s (run 2026-10-17). `HecateSplitTest` (11 tests, skipped without numpy) uses synthetic masks only: `box_any` against a brute-force filter, cell pooling of a single pixel, the PHerc0841 layout (validation over all supervision gives no training patch), a training layout that must give training patches clear of the guard, the seeded 10 % generated holdout and the fallback from an empty validation mask, hand-counted cases for the 5 % threshold, both strides and the validation rule, a hand-counted segment (33 training and 2 validation patches, shares 0.75 and 0.125), and `stable_seed` against the trainer's formula. `HeldOutEntriesTest` (4 tests) checks the `held_out` text in `docs/results.json`: every entry cites a log that exists, PHerc0841's names both Hecate channels, w043's does not call it held out from its trainers, and the Hecate caveats in `kit auc`, `kit ensemble` and `kit plan` say not held out. They do not run `main` or `_read`, so file reading, the Pillow fallback and the argument handling are untested, and they do not compare with the real trainer's output, whose archived manifest is not public.

## History

- 2026-10-17: this page ([PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100)).
- 2026-10-16: first version, `scripts/heldout/hecate_split.py` with `tests/test_hecate_split.py`, for measurement M1 of the reader exposure log (`f15045e`, [PR #100](https://github.com/ChaseHendrick/Scrolls/pull/100)).

## Related

- [Reader exposure log](../logs/2026-10-16-reader-exposure.md): the question, measurement M1, the commands and mask hashes, and the sources.
- [2026-10-09 log](../logs/2026-10-09-pherc0841-hecate.md): the earlier PHerc0841 and Hecate note, whose held-out wording the exposure log supersedes.
- [leaderboard](leaderboard.md): prints the held-out words this work set in `held_out_by_reader`.
- [auc](auc.md): the scores whose fairness depends on these splits.
- [gate](gate.md): ranks readers on the PHerc0841 crops, never Hecate.
- [batch](batch.md): picks Hecate 2.4 um for fine scans on a comparison made on w043, which the exposure log says this rule puts mostly under training patches.
- [`results.json`](../results.json): keys `held_out` (reasons and sources per segment) and `held_out_by_reader` (one word per reader family).
