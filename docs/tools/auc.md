# kit auc: pixel AUC of an ink map against a segment's published labels

Scores a 2D ink map against a segment's `inklabels.zarr` inside its `supervision.zarr`, with the reverse-depth map as the control, block-bootstrap intervals and a paired comparison of two maps.

| Field | Value |
| --- | --- |
| Id | `auc` |
| Status | Current |
| Kind | kit command, kit module |
| Run | `python -m kit auc`, `from kit import auc` |
| Code | `kit/auc.py`, `kit/cli.py` (`cmd_auc`), `kit/verify.py` (`load_map`, `VerifyError`), `kit/layers.py` (`_zarr`) |
| Tests | `tests/test_auc.py`, `tests/test_auc_bootstrap_exact.py` |
| Needs | Python 3.10 or newer, numpy, tifffile (imagecodecs for compressed TIFFs), zarr 3 (Python 3.11 or newer) |
| Runs on | CPU. A full-size 5,980 x 8,240 map: about 5 s with a control, about 6 s with `--bootstrap 300` (measured 2026-10-16 on a 4-core 2.1 GHz Xeon cloud container, synthetic data) |
| Network | None |
| Writes | Nothing (prints only). With `--slug SLUG`, appends a check to `experiments/SLUG/run.json` (or under `--root`) |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07; also in the AutoPipeline release |
| Guide | [STANDARDS.md](../STANDARDS.md) (how AUC is used here), [the overlap and baseline log](../logs/2026-10-07-overlap-and-baseline.md) (sampling noise) |
| Checked | 2026-10-16 against commit `27d0e96` |

## What it does

An ink model writes an ink map: one number per pixel of a flattened surface, higher where it thinks there is ink. The Vesuvius Challenge publishes, for a few segments, the ink that people marked by hand (`inklabels.zarr`) and the area where they marked both ink and non-ink (`supervision.zarr`). `kit auc` measures how well a map agrees with those labels: the AUC is the chance that a labelled ink pixel scores above a labelled non-ink pixel, counted only inside the supervision mask, with ties counted half. 1.0 is perfect, 0.5 is chance.

It also scores a control map. The reverse-depth map reads the same CT layers in the opposite depth order, so it sees the same brightness but not the same ink. A map that reads ink scores well above its reverse; a map that only follows brightness scores about the same both ways. `--bootstrap` adds a 95 % interval by resampling 1 mm blocks, and `--compare` says whether one map is ahead of another beyond sampling noise on the same pixels.

On a segment no model was trained on, this is a generalization number. On a segment the model trained on it only shows that the pipeline runs. It is a score against human labels, not a reading: an AUC never means letters were found.

## When to use it

- Ranking ink models, checkpoints or settings on a labelled segment held out from all of them (PHerc0841 for `ink_9um`, v8in, d9v2 and Reader v2, though possibly not for Hecate; see the [Hecate log](../logs/2026-10-09-pherc0841-hecate.md)).
- Checking that a new pipeline step did not break ink detection, with the reverse map as the control.
- Deciding whether a gap between two maps is real (`--compare`) before writing it down.

Do not use it:

- To judge letter shapes: pixel AUC rewards blur. Use [`hpscore`](hpscore.md), the letter-scale score.
- To compare a map with another map without labels: use [`verify`](verify.md) (agreement, with a control) or [`collate`](overlap.md).
- On a segment with no published labels, such as a target scroll: there is nothing to score against, and target maps stay private (AGENTS.md hard rule 1).
- To claim generalization on PHerc0139 w035 (a training segment) or w045 for `ink_9um` and its fine-tunes (which trained on its 2.4 um render; [log](../logs/2026-10-08-w045-not-held-out.md)).

## Quick start

```bash
# Labels and mask of PHerc0841 w00 from the open-data bucket (their level 2 is the 9 um surface grid).
L=PHerc0841/segments/20260220213127-w00/ink-labels/2.403um-volume-20260319124803/20260918
python -m kit fetch "$L/inklabels.zarr" labels/inklabels.zarr --workers 8
python -m kit fetch "$L/supervision.zarr" labels/supervision.zarr --workers 8

python -m kit auc MAP.tif --control MAP_reverse.tif \
    --labels labels/inklabels.zarr --mask labels/supervision.zarr
```

- `MAP.tif`: an ink map of that segment on its 9.366 um surface grid (4,220 x 4,760 px for w00). `MAP_reverse.tif`: the same model run with the surface volume's layers in reverse order. The prefixes of the other labelled segments are in `scripts/mac-w045.sh`.

It prints, for example (synthetic data):

```
map    : AUC 0.9949 on 2112319 ink and 5224067 background px (53394 unpredicted px in the mask left out)
control: AUC 0.4999 on 2102018 ink and 5250758 background px (37004 unpredicted px in the mask left out)
map minus control: +0.4950 (near 0 means the model is not reading ink in this direction)
```

It worked when the exit code is 0 and both lines show an AUC. The result means something only when the map is well above the control.

## Commands and options

### `python -m kit auc`

```
usage: python -m kit auc [-h] --labels LABELS --mask MASK [--control CONTROL] [--level LEVEL]
                         [--crop Y0 Y1 X0 X1] [--surface-shape H W] [--keep-zero] [--inner PX]
                         [--bootstrap N] [--block-px BLOCK_PX] [--compare MAP] [--seed SEED]
                         [--json] [--slug SLUG] [--name NAME] [--root ROOT]
                         prediction
```

| Option | Default | Meaning |
| --- | --- | --- |
| `prediction` | required | The ink map: a 2D `.tif` (read with tifffile) or `.npy`, on the 9 um surface grid. Singleton axes are squeezed |
| `--labels PATH` | required | The segment's `inklabels.zarr` (a group with pyramid levels, or a single array) |
| `--mask PATH` | required | The segment's `supervision.zarr`, same shape as the labels at the chosen level |
| `--control PATH` | none | The reverse-depth map of the same surface, same shape as the map |
| `--level LEVEL` | `2` (`DEFAULT_LEVEL`) | Pyramid level of the labels that matches the 9 um grid |
| `--crop Y0 Y1 X0 X1` | none | The map covers only this window of the surface (rows Y0 to Y1, columns X0 to X1, ends excluded) |
| `--surface-shape H W` | the map's shape | The full surface's shape; required with `--crop` |
| `--keep-zero` | off | Count pixels where the map is exactly 0 (by default they are left out as unpredicted) |
| `--inner PX` | `0` | Leave out PX pixels at every edge of the map, for maps inferred on a cropped input (the crops here use 64) |
| `--bootstrap N` | `0` (none) | Block-bootstrap draws for a 95 % interval; 300 is plenty; at least 20 |
| `--block-px BLOCK_PX` | `107` (`BLOCK_PX`, 1 mm at 9.366 um) | Side of a bootstrap block, in pixels |
| `--compare MAP` | none | A second map of the same surface: the difference, its interval and how often the first map is not ahead. Implies 300 draws when `--bootstrap` is 0 |
| `--seed SEED` | `0` | Seed of the bootstrap draws |
| `--json` | off | Print the result as JSON instead of text |
| `--slug SLUG` | none | Attach the result as a check to the experiment SLUG in the ledger ([run-ledger](run-ledger.md)) |
| `--name NAME` | `label-auc` | Name of that check |
| `--root ROOT` | `experiments` (`ledger.DEFAULT_ROOT`) | Ledger folder |

## Python API

```python
from kit import auc
result = auc.score_files("MAP.tif", "inklabels.zarr", "supervision.zarr", control="MAP_reverse.tif")
```

| Function | Returns | Notes |
| --- | --- | --- |
| `score_files(prediction, labels, mask, control=None, level="2", crop=None, surface_shape=None, keep_zero=False, inner=0, bootstrap=0, block_px=107, compare=None, seed=0)` | The result dict below | What the command runs; raises `VerifyError` on bad input |
| `score_array(prediction, ink, mask, keep_zero=False, inner=0)` | `{"auc", "ink_px", "background_px", "zero_px_in_mask", "zero_px_counted", "inner"}` | A map against same-shape boolean ink and mask arrays already on its grid |
| `auc_scores(ink_scores, background_scores)` | float, or `None` when a class is empty | Mann-Whitney AUC with ties half, exact on 65,536 integer levels |
| `block_bootstrap(prediction, ink, mask, draws=300, block_px=107, seed=0, other=None, keep_zero=False, inner=0)` | The `bootstrap` dict below | Same draws for both maps when `other` is given |
| `labels_on_map(labels, mask, level, surface_shape, crop, map_shape)` | `(ink, supervised)` boolean arrays | Labels resampled onto the map's grid by nearest neighbour |
| `format_result(result)` | str | The text the command prints |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Ink map | 2D TIFF (any dtype tifffile reads) or `.npy` | uint8 and uint16 are scored as they are; floats are scaled once for the whole map to 0..65535 (divided by 255 or 65535 first when the maximum is above 1). Exactly 0 means "no prediction" unless `--keep-zero` |
| Labels | zarr: a group whose key `--level` is a 2D array, or a 2D array | Greater than 0 is ink |
| Mask | zarr, same layout and shape as the labels | Greater than 0 is supervised |
| Control and compared maps | Same formats, same shape as the map | |

The labels sit on the 2.4 um scan's grid; their level 2 is the 9 um surface grid up to a uniform scale (w045: 5,820 x 8,020 labels for 5,980 x 8,240 surface pixels). Each map pixel takes the label at the nearest scaled position. A scale that differs between the two axes by more than 0.5 % (`MAX_AXIS_MISMATCH`) is refused, since then the grids are not the same.

## Outputs

Text by default (see Quick start); with `--json`, one object:

| Field | Type | Meaning |
| --- | --- | --- |
| `forward.auc` | float (4 decimals) or null | AUC of the map; null when the mask holds no ink or no background pixel |
| `forward.ink_px`, `forward.background_px` | int | Pixels scored in each class |
| `forward.zero_px_in_mask` | int | Pixels in the mask where the map is exactly 0 |
| `forward.zero_px_counted` | bool | Whether those were counted (`--keep-zero`) |
| `forward.inner` | int | Edge left out, in pixels |
| `control` | object, same fields | Only with `--control` |
| `files` | object | `prediction`, `labels`, `mask`, `control` paths as given, and `compare` with `--compare` |
| `level` | str | Label level used |
| `crop` | list or null | The window, as given |
| `bootstrap.draws`, `bootstrap.block_px`, `bootstrap.blocks`, `bootstrap.seed` | int | Only with `--bootstrap` or `--compare` |
| `bootstrap.ci95` | [float, float] | 95 % interval of the map's AUC |
| `bootstrap.half_width` | float | Half the interval's width |
| `bootstrap.compare.auc_map`, `.auc_other`, `.difference` | float | Both AUCs on the shared pixels, and map minus other |
| `bootstrap.compare.ci95` | [float, float] | 95 % interval of the difference |
| `bootstrap.compare.share_draws_map_not_ahead` | float | Share of draws in which the map is not ahead |
| `bootstrap.compare.pixels` | int | Shared pixels scored |

| Exit code | Meaning |
| --- | --- |
| 0 | Scored (an AUC can still be null; check `forward.auc`) |
| 2 | Bad input: the message on stderr says which (see Failure modes) |

## How it works

1. Load the map (squeeze to 2D) and open the labels and mask at `--level`.
2. Map every map pixel to a label pixel by nearest neighbour on the scaled grid (`label_grid`), inside `--crop` when given.
3. Quantize the whole map once to integers (`_quantize`), so ink and background are on one scale.
4. Keep pixels inside the mask, minus exact zeros (unless `--keep-zero`) and minus `--inner` pixels at each edge.
5. AUC by counting: histogram ink and background scores on 65,536 levels, and count for each ink pixel the background pixels below it plus half the ties (`auc_scores`). This equals the pairwise Mann-Whitney definition exactly.
6. Bootstrap (`block_bootstrap`): cut the scored pixels into square blocks of `--block-px`, draw blocks with replacement `N` times with the seeded generator, and recompute the AUC from 1,024-bin block histograms (`BOOT_BINS`); the 2.5 and 97.5 percentiles are the interval. With `--compare`, both maps use the same pixels (zeros of either map left out) and the same draws, so the interval is of the paired difference. The point estimates stay exact; only the resampled AUCs use the 1,024 bins.

Neighbouring pixels are not independent and a segment's labels cover about 1 cm2 (PHerc0841: 0.9 to 1.4 cm2 each), so the block bootstrap gives the honest interval. On PHerc0841 a strong map's interval is plus or minus 0.01 to 0.04, so a ranking by a smaller margin on one segment is noise ([log](../logs/2026-10-07-overlap-and-baseline.md)).

## Checks and controls

- **Reverse-depth control** (`--control`): it should sit near or below 0.5. Map minus control near 0 means the model is not reading ink in this direction. A forward AUC reported without its control is not a result here (AGENTS.md hard rule 4).
- **Sampling noise** (`--bootstrap`, `--compare`): a difference whose interval includes 0 is "not distinguishable from noise", whatever its size.
- **Held-out data**: the score generalizes only on a segment outside the model's training data; the `held_out` key of [`../results.json`](../results.json) says which segment is held out from which model.
- **Claim label**: the AUC is Model output scored against Community labels; write it with the segment, the model, the control and the interval.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `numpy is required. Run inside villa's environment: ...` | numpy is not installed | `python -m pip install numpy tifffile zarr`, or run inside villa's environment |
| `tifffile is required (it is in villa's environment)` | tifffile missing | Install tifffile (and imagecodecs for LZW or zstd TIFFs) |
| `cannot read MAP.tif: ...` | Unreadable or compressed TIFF without imagecodecs | Install imagecodecs, or save the map as `.npy` |
| `MAP: expected a 2D map, got shape (...)` | A layer stack or an RGB image | Pass one 2D map |
| `cannot open PATH as zarr: ...` | Wrong path, or not a zarr store | Point `--labels` and `--mask` at the `.zarr` folders |
| `PATH: no level '2'; levels: [...]` | The store has other level keys | Pick the level that matches the 9 um grid with `--level` |
| `labels (...) and mask (...) differ in shape at level 2` | Labels and mask from different segments or levels | Use the pair from the same segment |
| `labels (...) and surface (...) differ in scale between axes (...); they are not the same grid` | The map is not on this segment's surface grid, or `--surface-shape` is wrong | Check the map's segment and the full surface shape |
| `a cropped map needs the full surface shape (surface_shape)` | `--crop` without `--surface-shape` | Add `--surface-shape H W` |
| `crop [...] is outside the H x W surface` | Crop larger than the surface | Fix the crop |
| `map shape (...) does not match the window h x w` | The crop does not match the map's size | Give the window the map was cut from |
| `control shape (...) differs from the map's (...)` | Control from another surface or crop | Use the reverse map of the same surface and crop |
| `inner N leaves nothing of a (...) map` | `--inner` at least half the map's side | Use a smaller `--inner` |
| `use at least 20 bootstrap draws` | `--bootstrap` between 1 and 19 | Use 300 |
| `the mask holds only one class; no AUC to resample` | No ink or no background pixels left to bootstrap | Check the crop and the mask |
| `map: no AUC (ink 0 px, background N px in the mask)` | No labelled ink inside the scored area (exit code 0) | Check the crop; the crops here are the 640 px windows of densest ink |

## Cost and time

Measured 2026-10-16 in a 4-core 2.1 GHz Xeon cloud container, on a synthetic map the size of PHerc0139 w045 (5,980 x 8,240, uint8) with level-2 labels of 5,820 x 8,020: 4.8 s with `--control`, 5.8 s with `--bootstrap 300`, 5.0 s with `--compare`. Memory: not measured (it holds the map, its quantized copy and the boolean arrays, a few hundred MB at this size). It runs locally on any machine; nothing here needs Modal or a GPU.

## For agents

- Common case: `python -m kit auc MAP.tif --control MAP_reverse.tif --labels L/inklabels.zarr --mask L/supervision.zarr --json`. Read `forward.auc` and `control.auc`; on crops add `--crop Y0 Y1 X0 X1 --surface-shape H W --inner 64`.
- It reads the three or four files and prints. It writes nothing unless `--slug` is given, and then only appends a check to that experiment's `run.json`. Safe to rerun; with `--slug`, each run appends one more check.
- No network and no go-ahead needed. Publishing a score of a target-scroll map is never allowed (hard rule 1); score only public labelled segments in public work.
- Success: exit 0 and a non-null `forward.auc`. A pass needs the control well below the map, and for a ranking, a `--compare` interval that excludes 0.
- Never call an AUC a reading, never report a forward AUC without its control, and never call a score on w035, or on w045 for `ink_9um` and its fine-tunes, a generalization result.

## Tests

```bash
python -m unittest tests.test_auc tests.test_auc_bootstrap_exact -v
```

They cover the AUC against the pairwise definition, ties, float and uint16 maps, a forward map that reads ink and a reverse that does not, crops lining up with the full map, unpredicted zeros, `--inner`, the refusals (crop outside, missing store, anisotropic grid, crop without shape), the CLI, and the bootstrap against a per-pixel oracle with quantization, zeros and partial blocks. They skip without numpy, tifffile and zarr. They do not run on real segment data.

## History

- 2026-10-07: faster block bootstrap, unchanged outputs ([production speed log](../logs/2026-10-07-production-speed.md)).
- 2026-10-07: `--bootstrap`, `--compare` and `--block-px` added ([overlap and baseline log](../logs/2026-10-07-overlap-and-baseline.md)).
- 2026-10-07: first version, with the reverse-depth control, `--crop`, `--inner` and the zero rule.

## Related

- [`hpscore`](hpscore.md): the letter-scale score, which rewards blur less than pixel AUC.
- [`verify`](verify.md): agreement of two maps (CPU against MPS), with a control.
- [`gate`](gate.md): Gate A, which ranks readers by these AUCs on PHerc0841's crops.
- [`layers`](layers.md): writes the depth-shuffle control and the layer TIFFs models read.
- [`../results.json`](../results.json): every AUC reported here, with its settings and source.
