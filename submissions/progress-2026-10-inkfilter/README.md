# Inkfilter: fixed image filters for surface volumes

Inkfilter makes a two-dimensional map from a surface-volume window without a trained model or learned weights. It combines alpha compositing, the papyrus edge step and fine texture, then writes the same calculation with reversed depth as a control. A map is filter output, not a reading.

The default `face-mix` recipe scored mean AUC 0.736 on 56 separate confirmation windows from 28 publicly labelled segments across seven scrolls, against 0.704 for the selected alpha-compositing baseline and 0.708 for alpha plus high-pass. Those are the same segments and scrolls used during development, with different nonoverlapping windows. This is a comparison with the particular fixed filters tested, not with trained ink models or every available community tool. See [the evidence, controls and failures](evidence/README.md).

## Install and try synthetic data

Use Python 3.10 or newer in a fresh virtual environment; the optional Zarr 3 dependency needs Python 3.11 or newer. The exact test environment below used Python 3.12.14. From this package directory:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
python demo.py demo-output
```

The demo creates a synthetic sheet, `map.npy`, `map_reverse.npy` and `map.json`. It contains no scan data and does not test real-world ink quality. NumPy is the only required dependency. Install `python -m pip install '.[io]'` for local TIFF and Zarr input/output.

```bash
scrolls-inkfilter window.npy --output map.npy
scrolls-inkfilter surface.zarr --level 1 --crop 0 1024 0 1024 --output map.tif
python -m scrolls_inkfilter window.npy --output map.npy
```

The command prints a JSON record and exits 0 on success. It writes the map, its `_reverse` control and a `.json` record together in the output folder. Existing outputs are refused unless `--overwrite` is given. Output paths must resolve to different files and may not replace the input or lie inside an input directory, including through symlinks. Existing symbolic links and multiply linked output files are refused even with `--overwrite`, protecting hardlinked input data. Failures print a diagnostic on stderr and exit 2; a failed write can leave partial outputs. A subsequent run with the same name will refuse them until they are removed or `--overwrite` is used.

## Inputs, options and memory

Input is a local `.npy` array, a TIFF stack, a bare Zarr array, or a Zarr group with numeric level names that select arrays. A level selecting another group is rejected with a diagnostic. Its shape is `(Z,H,W)`: depth along the mesh normal, then the two flattened surface axes. Supported dtypes are uint8, uint16, or floating point in [0,1]. Zero means unrendered. The command rejects nonfinite values, unsupported types, depth outside 3 to 4096, empty windows and out-of-bounds crops. It does not accept remote URLs, meshes, raw three-dimensional CT scans or trained model checkpoints.

| Option | Default | Meaning |
| --- | --- | --- |
| `volume` | required | Local surface-volume file or Zarr directory |
| `--output` | required | Float32 `.npy`, `.tif` or `.tiff` map; also writes the control and record |
| `--level` | `0` | Numeric level in a Zarr group; bare arrays, `.npy` and TIFF use 0 |
| `--crop Y0 Y1 X0 X1` | full array | Half-open crop on the selected level's grid; all depths are retained |
| `--recipe` | `face-mix` | `face-mix` or `face-mix-sharp`; sharp has less smoothing and was not the confirmed recipe |
| `--overwrite` | false | Replace the three output paths |
| `--help` | | Print the command reference |

Use windows around 1024 x 1024 pixels. The filter holds several full floating-point copies of the cropped volume in memory, so whole large surfaces can exhaust RAM. NumPy input is memory mapped and Zarr is sliced before loading; TIFF stacks are read fully before cropping. CPU runtime and memory scale with window size, depth and smoothing. No GPU or network access is used by the command. The synthetic tests take seconds; no end-to-end runtime claim is made for other hardware or data sizes.

## Recipe and library use

The numerical implementation uses NumPy separable Gaussian filters and box sums. It smooths the volume by `(1,1.5,1.5)` voxels, finds a papyrus threshold with Otsu's method and uses the papyrus run nearest the central depth. The high-z face is the assumed ink side. The three components are:

1. Front-to-back alpha compositing of up to 41 central layers from the high-z side, with intensity window [0.45,0.60] of full scale and opacity 1.
2. The steepest papyrus-to-air step at inward depths 2, 1, 0 and -1.
3. Local texture two voxels inside that face, using a 3-pixel box.

Each component is normalized by its median and median absolute deviation, then the three are averaged. A Gaussian background with sigma 192 pixels is subtracted and a Gaussian with sigma 48 pixels smooths the result. Those constants were selected on approximately 4.8 um pixels, level 1 of approximately 2.4 um scans. The command does not infer or rescale voxel size. Use the library with an explicitly adjusted recipe for another sampling scale, and treat its quality as untested. Floating-point inputs use 1.0 as full scale; unsigned integer inputs use their dtype's full scale.

```python
import numpy as np
from scrolls_inkfilter import ink_map

volume = np.load("window.npy", allow_pickle=False)
info = {}
forward = ink_map(volume, "face-mix", info=info)
control = ink_map(volume, "face-mix", reverse=True)
```

`ink_map(volume, recipe=None, reverse=False, info=None)` returns an `(H,W)` float32 map. `recipe` can also be a dictionary with `components`, `background` and `smooth`. Copy a recipe before editing it because `RECIPES` holds shared dictionaries. The library's numerical functions retain the frozen study implementation; the CLI adds stricter dtype, range and shape validation. Library callers must supply finite, appropriately scaled input themselves. Output values are unbounded scores, not calibrated ink probabilities.

## Checks and limits

```bash
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
python evidence/summarize.py
```

The tests generate synthetic data and check the component calculations, a deliberately informative reverse-depth control, invalid input and NumPy/TIFF/Zarr command output. The summary command verifies the saved scalar score aggregates, including the paired intervals; it does not rerun maps or pixel AUC from raw data.

Always score a reversed-depth control on labelled data before making an ink-quality claim. The confirmed forward map trails alpha compositing on three of seven scrolls, and its reverse map scores higher on PHerc0814's one segment. Face orientation varies. Alpha compositing can also make the forward and reversed synthetic maps almost identical. A lower reverse score is not guaranteed by the implementation.

These data establish neither superiority over trained ink models nor performance on unseen scrolls, other resolutions or target text. Custom recipes and `face-mix-sharp` have no confirmation claim. No scan, label, mask, render, map, mesh or weight files are distributed here.

## License and attribution

Original package code is under [Apache-2.0](LICENSE). The alpha component implements front-to-back compositing with the intensity-window/opacity convention documented in [villa's `utils::composite_alpha`](https://github.com/ScrollPrize/villa/blob/b29f310957c7b29e7d332f9876e0e487819cfaa3/volume-cartographer/utils/include/utils/compositing.hpp), the reference used in the study. The package contains a NumPy formulation, not villa's C++ source or binary; villa's `volume-cartographer` subtree has its own GPL-3.0 license. The VTID baseline is credited in the evidence and its implementation is not included.

The referenced scan and label data are distributed separately by the Vesuvius Challenge under CC BY-NC 4.0, not under this code license. Follow the [data access and license conditions](https://scrollprize.org/data) when downloading or using them.
