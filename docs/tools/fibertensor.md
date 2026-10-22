# fibertensor: a retired CPU ink reader built on fiber-orientation features

`python -m kit fibertensor` trains a tiny numpy model on structure-tensor (fiber orientation) and brightness features of one labeled surface-volume window and writes ink maps for others; it was a measured null on public data and is kept so lane D can be rerun.

| Field | Value |
| --- | --- |
| Id | `fibertensor` |
| Status | Retired |
| Kind | kit command, kit module |
| Area | Ink maps and models |
| Run | `python -m kit fibertensor train`, `python -m kit fibertensor predict`, `from kit import fibertensor` |
| Code | `kit/fibertensor.py`, `kit/cli.py` (`cmd_fibertensor`), `kit/auc.py` (`labels_on_map`, `label_grid`, `_levels`), `kit/layers.py` (`_zarr`), `kit/verify.py` (`_numpy`, `VerifyError`) |
| Tests | `tests/test_fibertensor.py` |
| Needs | Python 3.10 or newer, numpy, scipy (`scipy.ndimage`), zarr (3.x on Python 3.11 or newer) to read the volume and labels, tifffile for `predict`. Data: a 9 um surface volume zarr of a labeled public segment and its label folder |
| Runs on | Any CPU. On a 640 px crop of 28 layers, `train` took 33 s and `predict` 11 s with one BLAS thread (measured 2026-10-16, 4-core Xeon cloud container under load, synthetic data); the lane D log gives about 8 s per pair on Chase's Mac |
| Network | None |
| Writes | `train`: the model at `-o` (numpy adds `.npz` when the name lacks it). `predict`: a float32 TIFF map at `-o`. Both overwrite and print JSON |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07 ([PR #14](https://github.com/ChaseHendrick/Scrolls/pull/14)); since 2026-10-14 also in the `scrolls-workbench` package installed from this repository |
| Replaced by | Nothing. For ink maps use a released ink model such as `ink_9um` or v8in ([v8in-run](v8in-run.md), [mac-w045](mac-w045.md)) |
| Guide | [The lane D log](../logs/2026-10-07-grok-laneD.md) (method, evaluation, result) |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

Papyrus is two layers of plant fibers laid at right angles. Lane D (one of the parallel research lanes, A to I, that agents ran on public data on 2026-10-07; [the docs index](../README.md) lists their logs) asked whether a pen stroke over those fibers, which crosses them at other angles and fills the gaps between them, leaves a texture that differs from bare papyrus where brightness does not. Raw brightness at any one depth separates ink from background at most 0.58 AUC on PHerc0841's crops ([overlap and baseline log](../logs/2026-10-07-overlap-and-baseline.md), section 2), so the idea was to add texture on top of brightness.

`kit fibertensor train` reads a window of a surface volume (the stack of images rendered at depths above and below a traced surface), averages its layers into 5 depth bands, and computes label-free features for every pixel: each band's brightness at two smoothings; for each band the 2D structure tensor (the smoothed products of the image gradients, whose eigenvalues say how strong and how one-directional the local texture is) at three scales, giving log energy, coherence and an "off-fiber" angle measured from the segment's own dominant fiber axis; and the brightness difference between neighboring bands. It trains a 16-unit numpy MLP (or logistic regression) on a balanced sample of labeled pixels from that window and saves it. `kit fibertensor predict` computes the same features on another window, re-measuring the fiber axes there, and writes the model's ink probability as a map. `--kind raw` uses the brightness features only: the ablation the fiber features had to beat. `--reverse` reads the layers in reverse depth order for the control map.

The result was a null. On three train and test splits of public labeled crops (PHerc0139 w045 to PHerc0841 w00, w00 to w045, and a second w00 window to the w00 crop), the fiber head never beat the brightness-only head, every fiber AUC interval included chance, and it was 0.30 to 0.48 AUC behind `ink_9um` on the same crops ([lane D log](../logs/2026-10-07-grok-laneD.md)). That is why its status is Retired: the code stays so the records can be read and rerun, not for new ink maps. The null covers the tested 2D features, the 16-unit learner, the training windows and the settings; it does not show that fiber texture holds no ink information. Larger training areas, stronger depth priors and a 3D tensor were not tried (Untested idea).

Its maps are model output, not readings, and on real data they did not follow the labels any better than chance.

## When to use it

- Rerunning or checking lane D's records in `scripts/experiments/2026-10-07-grok-laneD/` ([experiment-records](experiment-records.md)).
- As a small, fast, fully readable baseline when testing a new texture idea on synthetic data, such as the unit test's texture-only phantom.
- As the starting point for the untested follow-ups (a 3D tensor, larger training areas), with the same brightness ablation and reverse control.

Do not use it:

- To make ink maps of any segment for a result: use a released ink model, such as `ink_9um` through villa or v8in through [v8in-run](v8in-run.md) or [mac-w045](mac-w045.md).
- To score a map: use [`auc`](auc.md).
- On target-scroll data in public work: maps of target scrolls stay private (the no-findings rule in [`AGENTS.md`](../../AGENTS.md)).

## Quick start

```bash
python -m kit fibertensor train VOLUME.zarr LABEL_DIR --crop Y0 Y1 X0 X1 --surface-shape H W -o fibre.npz
python -m kit fibertensor predict fibre.npz TEST.zarr --crop TY0 TY1 TX0 TX1 -o fibre_fwd.tif
python -m kit fibertensor predict fibre.npz TEST.zarr --crop TY0 TY1 TX0 TX1 --reverse -o fibre_rev.tif
python -m kit auc fibre_fwd.tif --control fibre_rev.tif \
    --labels TEST_LABELS/inklabels.zarr --mask TEST_LABELS/supervision.zarr \
    --crop TY0 TY1 TX0 TX1 --surface-shape TH TW --inner 64 --bootstrap 300
```

- `VOLUME.zarr`: the training segment's 9 um surface volume, `(layers, H, W)`, a bare zarr array or a group whose level `0` is that array. `scripts/mac-w045.sh` fetches PHerc0841 w00's as `$WORK/data/0841-w00_9um.zarr`.
- `LABEL_DIR`: the folder holding that segment's `inklabels.zarr` and `supervision.zarr` (level `2` is used).
- `Y0 Y1 X0 X1`, `H W`: the training window and the full surface shape. Lane D's: w00 `2624 3264 2688 3328` on `4220 4760`, w045 `3840 4480 2560 3200` on `5980 8240`, and the second w00 window `1792 2432 2944 3584` ([`run_mac.sh`](../../scripts/experiments/2026-10-07-grok-laneD/run_mac.sh)).
- `TEST.zarr`, `TEST_LABELS`, `TY0 TY1 TX0 TX1`, `TH TW`: the same for the test window, which must not overlap the training window.

On a synthetic pair of 10 x 256 x 256 volumes made in the style of `tests/test_fibertensor.py` (fibers at 0.3 rad in the training volume and 0.9 rad in the test volume, ink as isotropic texture in the top 4 layers only), with `--crop 32 224 32 224 --surface-shape 256 256` and no `--inner`, it printed (2026-10-16):

```
{
  "kind": "fibre",
  "model": "mlp",
  ...
  "train_axes": [0.2935, 0.3027, 0.2989, 0.3000, 0.2997],
  "features": 59,
  "train_loss": 0.011467822112064152,
  "train_pixels": 6736
}
map    : AUC 0.9882 on 3004 ink and 33860 background px
control: AUC 0.6959 on 3004 ink and 33860 background px
map minus control: +0.2923 (near 0 means the model is not reading ink in this direction)
```

(Axes rounded here.) It worked when each command exits 0, `train` prints `features` (59 for `fibre`, 10 for `raw`) and a finite `train_loss`, and `predict` writes a map of the crop's shape. A working run is not a useful map: on synthetic data the depth-specific ink is easy, while on real crops the same commands gave AUCs at chance (Checks and controls).

## Checks and controls

Each check can fail, and on real data they did:

- **Reverse-depth control.** Predict with `--reverse` using the same model and pass that map to `kit auc --control`. The forward map must beat it by a clear margin; Gate A in `kit/gate.py` reads that as at least 0.10 (`MIN_GAP`).
- **Brightness-only ablation.** Train the same head with `--kind raw` on the same window, predict the same test window, and compare with `kit auc --compare RAW_MAP`, so both are scored on the same pixels with a paired interval.
- **A released reader on the same crop.** `ink_9um` seed 42's map of the same crop, compared the same way.
- **Held-out window.** Train and test windows must not overlap; the features read 32 px (`MARGIN`) beyond each crop, so keep the windows at least that far apart. Lane D's second w00 window sits 192 px above the test crop.

Lane D's results (scored with `kit auc --inner 64 --bootstrap 300 --compare`, 640 px crops, Model output; [lane D log](../logs/2026-10-07-grok-laneD.md), raw JSON in [`results/`](../../scripts/experiments/2026-10-07-grok-laneD/results/)):

| Train on, test on | fiber AUC (95 % CI) | reverse | brightness head | fiber minus brightness (95 % CI) | `ink_9um` s42 |
| --- | --- | --- | --- | --- | --- |
| w045 (PHerc0139), w00 (PHerc0841) | 0.4726 (0.405 to 0.555) | 0.4331 | 0.5663 | -0.094 (-0.153 to -0.006) | 0.8061 |
| w00, w045 | 0.4223 (0.333 to 0.537) | 0.5711 | 0.5096 | -0.072 (-0.221 to +0.089) | 0.9199 |
| w00 other window, w00 crop | 0.5018 (0.431 to 0.563) | 0.5356 | 0.4985 | +0.003 (-0.042 to +0.050) | 0.8061 |

No forward AUC is 0.10 above its reverse, no fiber head is ahead of its brightness head, and the training log loss (fiber 0.33 to 0.36, brightness 0.60 to 0.63) fell while held-out AUC stayed at chance, which is consistent with learning window-specific texture. The `ink_9um` number on w045 is not a held-out score, because `ink_9um` trained on w045's 2.4 um render ([log](../logs/2026-10-08-w045-not-held-out.md)); the w00 numbers are held out for every model in the table. `scripts/experiments/2026-10-07-grok-laneD/run.sh` covers PHerc0841 pairs (w00, ag896, ag405); no results from it are recorded in this repository.

The unit test shows that the method can detect texture where it exists: on a held-out synthetic phantom whose ink differs from the fibers only in texture, with the fibers rotated, the fiber features score above 0.8 and brightness alone stays within 0.1 of 0.5.

One more caution when scoring these maps. The probabilities crowd near the 0.001 floor, and `kit auc` rounds a float map to 65,536 levels, which ties many of them. On the synthetic Quick start maps, `kit auc` gave 0.9882 and 0.6959 for the forward and reversed maps, while the exact rank AUC is 0.9889 and 0.6465 (73 % of the reversed map's pixels were below 0.0011; measured 2026-10-16). Lane D's real-data numbers were not rechecked for this.

Claim label: Null, for the tested 2D features, the 16-unit learner, lane D's training windows and its settings on PHerc0139 w045 and PHerc0841 w00 (lane D log); every map it writes is Model output.

## Commands and options

### `python -m kit fibertensor train`

```
usage: python -m kit fibertensor train [-h] [--crop Y0 Y1 X0 X1]
                                       --surface-shape H W
                                       [--kind {fibre,raw}]
                                       [--model {mlp,logreg}]
                                       [--samples SAMPLES] [--epochs EPOCHS]
                                       [--seed SEED] [--reverse] -o OUTPUT
                                       volume labels
```

| Option | Default | Meaning |
| --- | --- | --- |
| `volume` | required | The training surface volume zarr, `(layers, H, W)` on the 9 um surface grid: a bare array, or a group whose level `0` is the array |
| `labels` | required | The label folder: `labels/inklabels.zarr` and `labels/supervision.zarr` are read at level `2` |
| `--crop Y0 Y1 X0 X1` | none (the whole volume) | The training window: rows Y0 to Y1 and columns X0 to X1 of the surface, ends excluded. Without it the whole volume is read, which for a full segment needs many GB (59 float32 features per pixel) |
| `--surface-shape H W` | required | The full surface's shape in pixels, used to put the labels on the window's grid. A wrong shape with the right aspect ratio is not caught and misaligns the labels; without `--crop` it must equal the volume's shape |
| `--kind KIND` | `fibre` | `fibre`: brightness, structure-tensor and depth-contrast features (59 with 5 bands). `raw`: brightness only (10), the ablation |
| `--model MODEL` | `mlp` | `mlp`: one hidden layer of 16 ReLU units. `logreg`: logistic regression |
| `--samples SAMPLES` | `60000` | Training pixels: half ink and half background, drawn without replacement from inside the supervision mask, fewer when a class has fewer pixels. Below 2 nothing is sampled and the model is NaN (see Failure modes) |
| `--epochs EPOCHS` | `200` | Full-batch Adam steps |
| `--seed SEED` | `0` | Seed of the sampling and of the MLP's starting weights; the same seed and inputs give the same model |
| `--reverse` | off | Read the layers in reverse depth order before computing features, so the model trains on the reversed volume |
| `--output OUTPUT` | required | `-o` or `--output`: the model file. numpy adds `.npz` when the name does not end in it; `predict` needs the full name |

### `python -m kit fibertensor predict`

```
usage: python -m kit fibertensor predict [-h] [--crop Y0 Y1 X0 X1] [--reverse]
                                         -o OUTPUT
                                         model_file volume
```

| Option | Default | Meaning |
| --- | --- | --- |
| `model_file` | required | A model `.npz` written by `train` |
| `volume` | required | The surface volume zarr to map, same layout as for `train` |
| `--crop Y0 Y1 X0 X1` | none (the whole volume) | The window to map; the map has its shape |
| `--reverse` | off | Read the layers in reverse depth order: the control map, made with the same model |
| `--output OUTPUT` | required | `-o` or `--output`: the map, written as a float32 TIFF whatever the extension |

## Python API

```python
from kit import fibertensor as ft
vol = ft.load_volume("VOLUME.zarr", crop=[Y0, Y1, X0, X1])
feats, axes = ft.features(vol, "fibre")
params = ft.fit(feats, ink, supervised, model="logreg", samples=8000, epochs=150)
prob = ft.predict(params, ft.features(ft.load_volume("TEST.zarr", crop=[TY0, TY1, TX0, TX1]), "fibre")[0])
```

`ink` and `supervised` are boolean arrays of the window's shape, such as `kit.auc.labels_on_map` returns.

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `load_volume(path, crop=None, reverse=False, margin=0)` | float32 array `(layers, h, w)` | `VerifyError` without zarr; `FileNotFoundError` for a missing store; `KeyError` for a group with no level `0` | Reads `margin` extra pixels on every side of `crop` (`[Y0, Y1, X0, X1]`), clipped at the volume's edges; `reverse` flips the layer axis |
| `fibre_axis(np, ndi, img)` | float, radians | Nothing of its own | Takes the numpy and `scipy.ndimage` modules. The dominant gradient orientation of a 2D image (across the dominant fibers), from the energy-weighted mean of the doubled angle over the whole image |
| `tensor_features(np, ndi, img, axis, rhos=RHO)` | list of `3 * len(rhos)` 2D arrays | Nothing of its own | For each integration scale: `log(energy + EPS)`, coherence (0 to 1), off-fiber angle `abs(sin(2 * (theta - axis)))` (0 on either fiber axis, 1 at 45 degrees) |
| `features(volume, kind='fibre', bands=BANDS, axis=None)` | `(float32 array (F, h, w), axes)`: F is `2 * bands` for `raw` and `12 * bands - 1` for `fibre` (59 with 5 bands); `axes` holds one fiber axis per band (empty for `raw`) | `VerifyError` for a volume that is not 3D or has fewer layers than `bands`, an unknown kind, or no scipy | Pass `axis` (one per band) to reuse fixed axes; by default each band's axis is measured on this volume |
| `fit(feats, ink, sup, model='mlp', hidden=16, samples=60000, epochs=200, lr=0.01, l2=0.0001, seed=0)` | dict of numpy arrays: `W1`, `b1` (and `W2`, `b2` for `mlp`), `mu`, `sd`, `train_loss`, `train_pixels` | `VerifyError` when `ink` holds only one class inside `sup`, or for an unknown model | `ink` and `sup` are boolean `(h, w)` on the features' grid. `hidden`, `lr` and `l2` are not on the command line |
| `predict(params, feats, chunk=1 << 18)` | float32 `(h, w)` map, `p * 0.999 + 0.001`, so from 0.001 to 1 | `KeyError` for parameters without `mu` or `sd`; `ValueError` when the feature count does not match the weights | Standardizes with the training `mu` and `sd`; runs in chunks of 262,144 pixels. No pixel is exactly 0, so `kit auc` drops none as unpredicted |
| `save_model(path, params, meta)` | None | `OSError` for an unwritable path | `np.savez` of the parameters plus `meta` as a JSON string array; numpy adds `.npz` to a name without it |
| `load_model(path)` | `(params, meta)`: the arrays and the decoded `meta` dict | `FileNotFoundError`; `KeyError` for a file with no `meta` | Loads with `allow_pickle=False` |
| `train_files(volume, label_dir, crop, surface_shape, out, kind='fibre', model='mlp', seed=0, samples=60000, epochs=200, reverse=False)` | The `meta` dict that `train` prints | `VerifyError` for bad inputs (see Failure modes); `FileNotFoundError`, `KeyError` as for `load_volume` | What `train` runs. Labels come from `label_dir` at level `"2"` |
| `predict_files(model_path, volume, crop, out, reverse=False)` | The dict that `predict` prints | `VerifyError` when the model's feature count differs; `ImportError` without tifffile; `FileNotFoundError` | What `predict` runs |

Constants: `BANDS = 5`, `RHO = (2.0, 4.0, 8.0)`, `GRAD_SIGMA = 1.0`, `EPS = 1e-6`, `MARGIN = 32`.

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Surface volume | zarr, `(layers, H, W)`, any numeric dtype (the published ones are uint8), read as float32 | A bare array or an OME-Zarr style group with level `0`. At least 5 layers (`BANDS`); lane D's had 28. 9 um surface grid; rows are Y, columns X |
| Labels | `LABEL_DIR/inklabels.zarr` and `LABEL_DIR/supervision.zarr`, level `2` (train only) | The organizers' published labels; level 2 matches the 9 um grid up to a uniform scale, and every window pixel takes the nearest label, as in `kit auc`. Greater than 0 is ink or supervised |
| Model | `.npz` from `train` (predict only) | Arrays `W1`, `b1`, `W2`, `b2` (MLP only), `mu`, `sd`, `train_loss`, `train_pixels`, and `meta` |

`--crop` windows count in surface pixels. A window may sit at the volume's edge; the 32 px margin is then clipped. A window that runs past the volume's edge gives fewer pixels than the crop and fails in `train` with the window message (Failure modes); `predict` writes the smaller map without a message.

## Outputs

`train` writes the model and prints its `meta` as JSON:

| Field | Type | Meaning |
| --- | --- | --- |
| `kind` | str | `fibre` or `raw` |
| `model` | str | `mlp` or `logreg` |
| `seed` | int | The seed used |
| `train_volume` | str | The volume path as given |
| `crop` | list of 4 int, or null | The training window as given |
| `train_axes` | list of float | Fiber axis per band in radians, measured on the training window (empty for `raw`). Stored for the record; `predict` does not use them |
| `bands` | int | Depth bands (`BANDS`, 5) |
| `rho` | list of float | Structure-tensor integration scales in pixels (`RHO`) |
| `features` | int | Features per pixel: 59 for `fibre`, 10 for `raw` |
| `train_loss` | float | Log loss of the final model on its own balanced training sample. Low values do not mean the model generalizes |
| `train_pixels` | int | Pixels in the training sample (twice the per-class count) |

`predict` writes a float32 TIFF of the window's shape, values 0.001 to 1 (higher means more ink-like to the model), and prints:

| Field | Type | Meaning |
| --- | --- | --- |
| `map` | str | The map's path as given |
| `shape` | [int, int] | The map's rows and columns |
| `axes` | list of float | Fiber axis per band measured on this window (in reversed band order with `--reverse`) |
| `kind` | str | The model's feature kind |
| `reverse` | bool | Whether the layers were reversed |

| Exit code | Meaning |
| --- | --- |
| `0` | The model or map was written. Check `train_loss` is a number: a NaN model also exits 0 |
| `1` | An error the command does not catch, with a Python traceback: a missing volume or model file, a volume group without level `0`, a missing output folder, or no tifffile for `predict` |
| `2` | Bad input, printed as `error: ...` on stderr (see Failure modes), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as `train` without `--surface-shape` | Check the command against Commands and options |
| `error: numpy is required. Run inside villa's environment: uv run --project "$VILLA/vesuvius" --extra models python -m kit verify ...` | numpy is not installed | `python -m pip install numpy scipy zarr tifffile` |
| `error: zarr is required (it is in villa's environment)` | zarr is not installed | Install zarr (3.x on Python 3.11 or newer) |
| `error: kit fibertensor needs scipy` | scipy is not installed | Install scipy |
| `FileNotFoundError: VOLUME does not exist` and a traceback, exit code 1 | The volume path is wrong | Fix the path |
| `KeyError: '0'` and a traceback, exit code 1 | The volume is a zarr group with no level `0` | Point at the full-resolution array, or a group whose level `0` is it |
| `error: need a (layers, H, W) volume with at least 5 layers, got (...)` | A 2D image, or a volume with fewer than 5 layers | Use the segment's full surface volume |
| `error: cannot open LABEL_DIR/inklabels.zarr as zarr: ...` | The label folder lacks `inklabels.zarr` or `supervision.zarr`, or they are not zarr | Fetch both into one folder and pass that folder |
| `error: PATH: no level '2'; levels: [...]` | The label stores have other level keys | The command always reads level `2`; use the published stores |
| `error: labels (...) and mask (...) differ in shape at level 2` | Labels and mask from different segments | Use the pair from one segment |
| `error: labels (...) and surface (...) differ in scale between axes (SY vs SX); they are not the same grid` | `--surface-shape` is wrong, or the labels belong to another segment | Give the segment's full surface shape |
| `error: crop [...] is outside the H x W surface` | The crop runs past `--surface-shape` | Fix the crop |
| `error: map shape (...) does not match the window h x w` | The crop runs past the volume's edge, or without `--crop` the volume's shape differs from `--surface-shape` | Keep the crop inside the volume; check the shape |
| `error: training labels hold only one class inside the mask` | The window has no labeled ink, or no background, inside the supervision mask | Choose a window with both, such as the crops above |
| `error: unknown feature kind 'KIND'` | `features` called with a kind other than `fibre` or `raw` (the command allows only those) | Use `fibre` or `raw` |
| `error: unknown model 'MODEL'` | `fit` called with a model other than `mlp` or `logreg` (the command allows only those) | Use `mlp` or `logreg` |
| `error: model expects N features, got M` | The model file's `meta` does not match the features its kind gives now, such as a file from changed code or an edited `meta` | Retrain with `train` |
| `FileNotFoundError: ...` and a traceback, exit code 1 | A missing model file, or an output folder that does not exist | Fix the path, or create the folder |
| `ModuleNotFoundError: No module named 'tifffile'` and a traceback, exit code 1 | `predict` without tifffile | Install tifffile |
| `RuntimeWarning: Mean of empty slice`, then `"train_loss": NaN` and `"train_pixels": 0`, exit code 0 | `--samples` below 2: nothing was sampled, and every map from this model is NaN | Use the default 60000 |
| A model trains and maps, but AUC against the labels is near 0.5 | Labels misaligned by a wrong `--surface-shape` with the right aspect ratio (not caught), or simply no signal, as in lane D | Check the shape against `scripts/mac-w045.sh`; compare with the raw ablation and the reverse control |

## How it works

1. **Read.** `load_volume` opens the zarr and reads all layers of the window plus `MARGIN = 32` px on each side (clipped at the volume's edges) as float32; `--reverse` flips the layers.
2. **Bands.** The layers split into `BANDS = 5` bands with edges `round(linspace(0, layers, 6))`; each band's mean image is z-scored over the window.
3. **Brightness features.** Each band mean smoothed with Gaussian sigma 1 and 4 px: 10 features. `--kind raw` stops here.
4. **Fiber axis.** Per band, `fibre_axis`: Gaussian-derivative gradients at `GRAD_SIGMA = 1.0`, summed tensor components over the whole window, and the angle `0.5 * atan2(2 Jxy, Jxx - Jyy)`. This measures the segment's own fiber direction without labels, so the features do not depend on how the segment is rotated.
5. **Structure tensor.** Per band and per scale in `RHO = (2.0, 4.0, 8.0)` px: smooth `gx * gx`, `gy * gy`, `gx * gy` at that scale; log energy `log(Jxx + Jyy + EPS)`; coherence `sqrt((Jxx - Jyy)^2 + 4 Jxy^2) / (Jxx + Jyy + EPS)`; off-fiber angle `abs(sin(2 * (theta - axis)))`, which is 0 on either fiber axis (the two fiber layers are at right angles) and 1 at 45 degrees. 45 features.
6. **Depth contrast.** Each band mean minus the one above it, smoothed at sigma 2: 4 features. 59 in all.
7. **Margin off.** The margin is cut away, leaving the features on the crop.
8. **Labels** (`train` only). `kit.auc.labels_on_map` reads level `2` of the label stores and maps each window pixel to the nearest label pixel, refusing grids that differ in scale between axes by more than 0.5 %.
9. **Fit.** A balanced sample of `min(samples // 2, ink, background)` pixels per class inside the mask, standardized by the sample's mean and standard deviation. Logistic regression starts at zero; the MLP (16 ReLU units) starts from normal weights scaled by `1 / sqrt(fan_in)`. Full-batch Adam for `--epochs` steps, learning rate 0.01, moments 0.9 and 0.999, L2 1e-4 on every parameter. The final log loss on the sample is `train_loss`.
10. **Save.** `np.savez` of the parameters, `mu`, `sd`, the loss, the pixel count and `meta`.
11. **Predict.** The same features on the new window, with the fiber axes measured there; a feature-count check; standardization with the training `mu` and `sd`; the forward pass in chunks; `p * 0.999 + 0.001`, written as a float32 TIFF.

The structure tensor is a standard image-analysis tool; the lane D log notes that the organizers' pipeline uses structure tensors for surface and fiber directions ([open problems](https://scrollprize.org/2026_open_problems), checked 2026-10-07) and found no prior use as an ink feature on PHerc0841.

## Cost and time

Measured 2026-10-16 in a 4-core Intel Xeon cloud container (cpuinfo 2.80 GHz) that other jobs were loading at the time (load average about 20), so these are upper bounds:

| Run | Wall time | Peak memory |
| --- | --- | --- |
| `train`, 640 px crop of 28 layers (lane D's crop size), `fibre`, `mlp`, 60,000 samples, one BLAS thread (`OMP_NUM_THREADS=1`) | 32.6 s | 485 MB |
| `predict`, the same window, one BLAS thread | 11.2 s | 640 MB |
| `train`, 192 px crop of 10 layers, `fibre`, one BLAS thread | 7.8 s | 126 MB |
| `train`, the same with numpy's default threads | 35 s | 126 MB |
| `predict`, 192 px crop, default threads | 4 to 6 s | 150 MB |

On a busy machine numpy's threads slow the many small matrix products of full-batch training; `OMP_NUM_THREADS=1` made `train` about 4.5 times faster here. Lane D recorded about 8 s per pair on Chase's Mac CPU ([log](../logs/2026-10-07-grok-laneD.md)). Without `--crop`, a whole segment needs about 59 x 4 bytes per pixel for the features alone (for 5,980 x 8,240, about 11.6 GB): use crops. Everything here is CPU work of seconds to a minute, well under the 10 minutes and the hour that would send a job to Modal; nothing needs a GPU. On Chase's Mac, wrap a run in `python -m kit run local SLUG -- COMMAND` so it reaches the compute ledger (the local compute rule in [`AGENTS.md`](../../AGENTS.md), [run-local](run-local.md)).

## For agents

- **Command:** `python -m kit fibertensor train VOLUME.zarr LABEL_DIR --crop Y0 Y1 X0 X1 --surface-shape H W -o MODEL.npz`, then `python -m kit fibertensor predict MODEL.npz TEST.zarr --crop TY0 TY1 TX0 TX1 -o MAP.tif`, and the same with `--reverse -o MAP_reverse.tif`; repeat `train` with `--kind raw` for the ablation. Both print JSON on stdout; score with `python -m kit auc ... --control MAP_reverse.tif --compare RAW_MAP.tif --json`.
- **Parse:** from `train`, `features` (59 or 10), `train_loss` (must be a number) and `train_pixels`; from `predict`, `shape` and `axes`. The verdict comes from `kit auc`: `forward.auc`, `control.auc` and `bootstrap.compare.ci95`.
- **Rerun:** Safe and deterministic for the same inputs and `--seed`; it overwrites the model and map files.
- **Success:** Exit code 0, a finite `train_loss`, and a map of the window's shape. That only means it ran.
- **Not a pass:** Any map from this tool as an ink result: it was a null on real data. A forward AUC without the reverse control or less than 0.10 above it; a fiber head not ahead of its `--kind raw` ablation in `--compare`; overlapping training and test windows; a low `train_loss` taken as skill.
- **Go-ahead:** Nothing; it runs locally on public data and rents nothing.
- **Never:** Use it for new ink maps or call its output a reading; run it on target-scroll data in public work; describe the lane D null as proof that fiber texture holds no ink information.

## Tests

```bash
python -m unittest tests.test_fibertensor -v
```

Three tests: on a synthetic phantom whose ink differs only in texture, the fiber features trained on one phantom score above 0.8 AUC on another with rotated fibers while brightness alone stays within 0.1 of 0.5 (and maps stay in (0, 1]); `fibre_axis` recovers a stripe angle; a model survives `save_model` and `load_model` unchanged, and `fit` and `features` refuse one-class labels and a too-thin volume. They skip without numpy or scipy. They do not run the command line, read zarr, or touch real segment data; the command line path was checked by hand on 2026-10-16 (this page's Quick start).

## History

- 2026-10-07: lane D's evaluation and log, a null against the brightness head and `ink_9um` on public crops, which is why this page lists the tool as Retired (`ca9c8c4`, merged in [PR #14](https://github.com/ChaseHendrick/Scrolls/pull/14)).
- 2026-10-07: the Mac evaluation script adds the within-segment held-out window (`99c71f3`).
- 2026-10-07: merged into public `main` with every other new command kept (`98c0eed`).
- 2026-10-07: first version, marked work in progress (`313061e`).

## Related

- [The lane D log](../logs/2026-10-07-grok-laneD.md): the method, the three splits, and the null.
- [The overlap and baseline log](../logs/2026-10-07-overlap-and-baseline.md): raw brightness alone reaches at most 0.58 AUC, the bar this tool tried to add to.
- [`auc`](auc.md): scores the maps, with `--control` for the reverse map and `--compare` for the ablation.
- [`view`](view.md): overlays the forward, reverse and raw maps with the labels on one page.
- [`gate`](gate.md): Gate A's 0.10 rule for the gap between a map and its reverse.
- [`experiment-records`](experiment-records.md): `scripts/experiments/2026-10-07-grok-laneD/`, the scripts and result JSON of the run.
- [`v8in-run`](v8in-run.md) and [`mac-w045`](mac-w045.md): released ink models on the same crops, the tools to use instead.
- [`phantom`](phantom.md): synthetic volumes with known ink, for testing detectors.
