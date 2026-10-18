# v8in-run: run the v8in ink model on a layer folder, with opt-in fp16 on the Mac GPU

`scripts/v8in_run.py` runs Youssef Nader's v8in ink model, or its PHerc1447 fine-tune, on a folder of numbered layer images and writes one ink probability map, with an optional fp16 autocast on Apple's MPS GPU and a final log line the Mac scripts parse.

| Field | Value |
| --- | --- |
| Id | `v8in-run` |
| Status | Current |
| Kind | script |
| Area | Ink maps and models |
| Run | `python scripts/v8in_run.py` |
| Code | `scripts/v8in_run.py` |
| Tests | None: no test in `tests/` runs it. Its end-to-end check is the CPU against MPS crop comparison in `scripts/mac-w045.sh` (step 5, `kit verify` with the reverse map as the control) |
| Needs | Python 3 with the packages of v8in's `requirements.txt`: torch 2.1 or newer, numpy, tifffile, imagecodecs, opencv-python-headless, safetensors, huggingface_hub 0.25 or newer (the runs here used torch 2.14.1). A local snapshot of the model repository, `YoussefMoNader/ink-8um-v8in` at `d89166b` (MIT, `model.safetensors` 333,532,180 bytes) or `YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062` at `2bf9f42`. `--fp16` needs an Apple Silicon Mac with MPS |
| Runs on | CPU, Apple MPS or CUDA. About 8 s per tile on 4 CPU cores of a Linux container (base v8in; [community scan log](../logs/2026-10-07-community-scan.md)) and 7.4 s per tile for the fine-tune (196 tiles in 1,444 s, `scripts/experiments/2026-10-07-cloud/v8in1447-w00/notes.md`); on Chase's M1 Pro, 1.1 to 1.2 s per tile on MPS in fp32, 5.5 to 6.2 s in fp16, and 25 s on its CPU ([mac.md](../mac.md)). All 2026-10-07. Whole segments are GPU jobs |
| Network | None. The model loads from the local `--model-dir`; downloading that snapshot from huggingface.co is a separate step |
| Writes | The map at `--output` (replaced if it exists) and any missing parent folders. Progress and the final line go to stdout |
| Go-ahead | Not needed for a local run on public data. Renting a GPU for it on Modal needs Chase's yes and a run spec (the go-ahead rule, hard rule 8, and the Modal rule, hard rule 11) |
| Released | Public `main` since 2026-10-07 (`6081aab`) |
| Guide | [mac.md](../mac.md) (the Mac runs that call it, with their times) |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

v8in (`YoussefMoNader/ink-8um-v8in`, released 2026-09-28, MIT) is Youssef Nader's community ink model: a ResNet3D-50 encoder with a 2D decoder that reads 24 layers of a surface volume in 64 px tiles and gives each pixel an ink probability. Its input is a folder of numbered layer images (`00.tif`, `01.tif`, ...), which [`layers`](layers.md) writes from a surface-volume zarr. v8in-1447 (`YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062`) is its fine-tune on PHerc1447 segments w058 and w060, with the same code. Both ship their own `predict.py`.

This script is a thin wrapper around the same inference function, `predict_surface` of the model's `ink8um` package. It adds three things. `--fp16` wraps the whole run in `torch.autocast` for MPS: the release turns on fp16 autocast only on CUDA, so on a Mac it runs fp32 otherwise. Progress lines come at most every 30 s. The last line states the device, fp16, direction, stride, tile count and time, which `scripts/mac-w045.sh` reads to reuse finished passes and to estimate seconds per tile.

It differs from the release's `predict.py` in ways that change results if you mix the two:

| | `scripts/v8in_run.py` | v8in's `predict.py` |
| --- | --- | --- |
| Model | `--model-dir`, a local snapshot only | `--model`, a local folder or a Hub id |
| Depth window | Always the central 24 layers | Central 24, or `--layer-start` |
| Depth order | As stored unless `--reverse`; the model's `reverse_layers` setting is ignored | The model's `reverse_layers` unless `--reverse` or `--no-reverse` |
| Device | `--device`, default `cpu` | Default CUDA when available, else CPU |
| Outputs | One `--output` | One or more |

The depth order matters for v8in-1447: its `config.json` sets `reverse_layers: true`, because the PHerc1447 renders it was tuned on stack the surface normal the other way (v8in's model card), so its own `predict.py` reverses by default and this script does not. On the team's 9 um renders used here (PHerc0139 w045, PHerc0841), "as stored" is the order v8in trained on ([community scan log](../logs/2026-10-07-community-scan.md), Sourced fact), so the forward map is the run without `--reverse` and the control is the run with it, for both models, as `scripts/mac-w045.sh` runs them.

The map is model output, not a reading. A bright stroke in it never means letters were found.

## When to use it

- Running v8in or v8in-1447 on a layer folder from `kit layers`: once as stored and once with `--reverse`, the control every ink AUC here needs.
- Checking that the Mac GPU gives the CPU's map, and that fp16 gives the fp32 map, on a small crop (what `scripts/mac-w045.sh` step 5 does with it).
- Reproducing the saved 2026-10-07 cloud jobs in `scripts/experiments/2026-10-07-cloud/` (`v8in-*`, `v8in1447-*`, `v8inwin-*`), which call it.

Do not use it:

- For `ink_9um`, d9v2 or Reader v2: they are villa checkpoints, run with villa's `vesuvius.ink_detection.inference.infer` (`scripts/mac-w045.sh` does both).
- To pick another depth window: export the 24 layers you want with `kit layers --start S --count 24`, or use v8in's `predict.py --layer-start`.
- To score the map: use [`auc`](auc.md) with the reverse map as `--control`; to compare two maps of one surface, such as CPU against MPS, use [`verify`](verify.md).
- For a whole segment, or a crop at stride 21, on a laptop CPU: that is hours of CPU and belongs on a GPU on Modal (the Modal rule, hard rule 11).
- With `--fp16` on CUDA or the CPU: it refuses. CUDA already runs fp16 inside the release, and the CPU stays fp32.

## Quick start

```bash
SEG=PHerc0841/segments/20260220213127-w00
python -m kit fetch "$SEG/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr" w00_9um.zarr
python -m kit layers w00_9um.zarr OUT/layers --crop 2624 3264 2688 3328
python -c 'from huggingface_hub import snapshot_download; snapshot_download("YoussefMoNader/ink-8um-v8in", revision="d89166b41a3f5fad7749b3d7c0fdd1bd3695d844", local_dir="V8IN_DIR", ignore_patterns=["training/*"])'
python -m kit run local SLUG -- python scripts/v8in_run.py --model-dir V8IN_DIR --layers OUT/layers \
    --output OUT/v8in.npy --device cpu --stride 64 --batch-size 4
python -m kit run local SLUG -- python scripts/v8in_run.py --model-dir V8IN_DIR --layers OUT/layers \
    --output OUT/v8in_reverse.npy --device cpu --stride 64 --batch-size 4 --reverse
```

- `OUT`: any folder of yours. `OUT/layers` gets every layer of the 640 px crop of densest labelled ink on PHerc0841 w00 (rows 2624 to 3264, columns 2688 to 3328, the crop `scripts/mac-w045.sh` uses).
- `V8IN_DIR`: where the model snapshot goes (its code, `config.json` and the 333.5 MB `model.safetensors`); the revision is the one `scripts/mac-w045.sh` pins.
- `SLUG`: an experiment already started in the local ledger with `python -m kit run init` ([run-ledger](run-ledger.md)); `kit run local` refuses a slug that does not exist, runs the command, passes on its exit code, and logs its wall time and electricity (the local-compute rule in [`AGENTS.md`](../../AGENTS.md)).
- Stride 64 gives about 100 tiles on a 640 px crop: at about 8 s per tile on 4 CPU cores, roughly 14 minutes per direction. On a Mac, use `--device mps` instead of `--device cpu`.

Then score both maps against the labels (fetch them as on the [`auc`](auc.md) page):

```bash
python -m kit auc OUT/v8in.npy --control OUT/v8in_reverse.npy --labels LAB/inklabels.zarr --mask LAB/supervision.zarr \
    --crop 2624 3264 2688 3328 --surface-shape 4220 4760 --inner 64
```

torch is not installed in the container these pages were written in (16 October 2026), and the model is 333.5 MB, so the script was run there with a stand-in for torch and for the model's `ink8um` package (a fixed 128 x 128 map of 0.25 and 9 tiles). That tests the wrapper's own code, not the model. It printed:

```
  1/9 tiles (0s)
  9/9 tiles (0s)
device=cpu fp16=False reverse=False stride=21 tiles=9 done in 0s; shape=(128, 128) mean=0.2500
```

and with `--fp16` and the default device it stopped with `v8in_run.py: error: --fp16 is for MPS; CUDA already runs fp16 and the CPU stays fp32` and exit code 2. Real runs end with the same line: on the M1 Pro, 784 tiles per direction at stride 21 took 862 s and 926 s ([community scan log](../logs/2026-10-07-community-scan.md)).

It worked when the exit code is 0, the last line has `tiles=` above 0 and a `mean=` above 0, and the map file exists with the layers' height and width.

## Checks and controls

- **Reverse-depth control.** Run again with `--reverse` at the same stride and score both with [`auc`](auc.md). On the PHerc0139 w045 crop, v8in on MPS at stride 21 scored 0.7382 as stored and 0.3269 reversed (`results` in [`results.json`](../results.json), reader `v8in d89166b`). Compare the distances from 0.5 as well as the difference: v8in's reversed maps can sit well below 0.5, so they are not neutral ([community scan log](../logs/2026-10-07-community-scan.md)). On PHerc0841 Bullo27 reports 0.837, 0.807 and 0.81 as stored against 0.562, 0.618 and 0.586 reversed for w00, ag896 and ag405 (`community` in `results.json`, Community report). A forward map without a reverse at the same stride is not a result: the v8in-1447 w00 crop scored 0.8381 at stride 42 against 0.5932 reversed at stride 64, still provisional for that reason (`pending` in `results.json`).
- **Device check.** The same crop on the CPU and on MPS, compared with `kit verify --control`: on the M1 Pro at stride 64 it passed with max abs difference 1 (of 255) and Pearson 0.99999998 (`device_checks` in `results.json`). afraazali42 found fp32 MPS and CPU probabilities equal to 5 decimals on an M3 Max (Community report, in the community scan log).
- **fp16 check.** `scripts/mac-w045.sh` compares an fp16 MPS crop map with an fp32 MPS one with `kit verify`, only after fp32 has passed against the CPU, and stops if they differ. On the M1 Pro fp16 matched fp32 but ran about 5 times slower, so the script falls back to fp32 there ([mac.md](../mac.md)). afraazali42 reports a largest fp16 difference of 0.0026 on an M3 Max (Community report).
- **Held-out data.** v8in trained on PHerc0139 w033, w035, w041 and w044 (its patch pack card); w045 and the three PHerc0841 segments are held out from it (`held_out` in `results.json`). v8in-1447 also trained on PHerc1447 w058 and w060.

Claim label: Model output for the v8in AUCs and device checks quoted above; Community report for Bullo27's and afraazali42's numbers.

## Commands and options

### `python scripts/v8in_run.py`

```
usage: v8in_run.py [-h] --model-dir MODEL_DIR --layers LAYERS --output OUTPUT
                   [--device DEVICE] [--fp16] [--reverse] [--stride STRIDE]
                   [--batch-size BATCH_SIZE] [--workers WORKERS]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--model-dir MODEL_DIR` | required | Local snapshot of the v8in (or v8in-1447) repository: the folder holding `ink8um/`, `config.json` and `model.safetensors`. It is put first on Python's import path, so its `ink8um` code is the code that runs |
| `--layers LAYERS` | required | Folder of numbered layer images; the central 24 are read (Inputs) |
| `--output OUTPUT` | required | Map to write; the extension picks the format: `.npy` float32 probabilities, `.tif` or `.tiff` 16-bit (probability x 65535, rounded, zlib), `.png`, `.jpg` or `.jpeg` 8-bit (probability x 255, truncated). Any other extension fails only after the whole inference has run |
| `--device DEVICE` | `cpu` | torch device: `cpu`, `mps` or `cuda` (or `cuda:N`). On `cuda` the release's own fp16 autocast is on |
| `--fp16` | off | Run under `torch.autocast(device_type="mps", dtype=torch.float16)`. Refused unless `--device` starts with `mps` |
| `--reverse` | off | Reverse the depth order of the 24 layers after reading them (never the image axes): the reverse-depth control. Off means as stored, whatever the model's `reverse_layers` says |
| `--stride STRIDE` | none (the model's `stride`, 21 for v8in and v8in-1447) | Step in pixels between 64 px tiles. 21 is the release's density; on a 640 px crop 42 gives a quarter of the tiles (196 against 784) and 64 about an eighth (100) |
| `--batch-size BATCH_SIZE` | `16` | Tiles per forward pass. fp32 batch 8 used about 10 GB of RAM ([community scan log](../logs/2026-10-07-community-scan.md)); `scripts/mac-w045.sh` uses 4 at 16 GB of memory or less, 8 up to 32 GB, 16 above |
| `--workers WORKERS` | `4` | Worker processes of torch's `DataLoader` that cut tiles; `0` cuts them in the main process |

The script reads no environment variables. `scripts/mac-w045.sh` sets its arguments from its own (`V8IN_STRIDE`, `V8IN_BATCH`, `V8IN_FP16`), documented on its page, [mac-w045](mac-w045.md).

## Python API

Not applicable: the script's only function is `main(argv=None)`, which takes the command-line arguments; the model's own Python API (`ink8um.InkDetector`, `predict_surface`, `save_prediction`) is described on its model card.

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Layer folder (`--layers`) | Images named by a number only (`00.tif`, `01.tif`, ..., or `.tiff`, `.png`, `.jpg`, `.jpeg`), sorted by that number | At least 24. With N layers it reads layers `(N - 24) // 2` to that plus 23: layers 2 to 25 of a 28-layer render. uint8, or uint16 reduced to 8 bits (`>> 8`); a colour image uses its first channel; values are clipped to 0..200. All layers must have one shape. Pixels are the surface grid (or the crop's), rows then columns |
| Model folder (`--model-dir`) | A snapshot of the model repository | `config.json` sets `in_depth` 24, `tile_size` 64, `stride` 21, `clip_max` 200, the 96 x 256 x 256 input upsampling, and `reverse_layers` (false for v8in, true for v8in-1447; ignored here). Get it with `huggingface_hub.snapshot_download` (Quick start) |

`kit layers` writes the layer folder from a surface-volume zarr, cut to a window with `--crop`. A compressed TIFF without imagecodecs is read through OpenCV instead.

## Outputs

On stdout, a progress line on the first batch, then at most every 30 s, and on the last batch:

```
  DONE/TOTAL tiles (Ns)
```

then one final line:

```
device=DEVICE fp16=BOOL reverse=BOOL stride=N tiles=N done in Ns; shape=(H, W) mean=X
```

| Field | Type | Meaning |
| --- | --- | --- |
| `device` | str | `--device` as given |
| `fp16` | `True` or `False` | Whether the MPS fp16 autocast was on |
| `reverse` | `True` or `False` | Whether the depth order was reversed |
| `stride` | int | `--stride`, or the model's default when none was given |
| `tiles` | int | Tiles predicted; 0 when no 64 px tile lies wholly inside the covered area |
| `done in` | int, seconds | From after the model is loaded to after the map is saved: layer reading, inference and writing |
| `shape` | (int, int) | Height and width of the map, equal to the layers' |
| `mean` | float, 4 decimals | Mean probability over the whole map, zeros included |

The map at `--output`: one value per layer pixel, a probability from 0 to 1 (scaled to 0..65535 in a `.tif`, 0..255 in a `.png` or `.jpg`). Pixels no tile covers are exactly 0: the area outside the coverage mask and a few pixels along the edges of a crop, since tiles must lie wholly inside ([community scan log](../logs/2026-10-07-community-scan.md)). [`auc`](auc.md) leaves exact zeros out as unpredicted. `scripts/mac-w045.sh` writes `.npy` and converts it to an 8-bit TIFF for scoring.

| Exit code | Meaning |
| --- | --- |
| `0` | The map was written. Check `tiles=` above 0 |
| `1` | An uncaught error with a Python traceback: torch or `ink8um` not importable, a bad layer folder, an unsupported output extension, a device or memory error from torch (Failure modes) |
| `2` | A usage error from the argument parser, including `--fp16` without an MPS device |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `v8in_run.py: error: --fp16 is for MPS; CUDA already runs fp16 and the CPU stays fp32`, exit code 2 | `--fp16` with a device other than `mps` | Drop `--fp16`, or use `--device mps` on an Apple Silicon Mac |
| `ModuleNotFoundError: No module named 'torch'`, exit code 1 | torch is not installed in this Python (`--help` still works) | Run in villa's environment, or install v8in's `requirements.txt` |
| `ModuleNotFoundError: No module named 'ink8um'`, exit code 1 | `--model-dir` is not a snapshot of the model repository | Point it at the folder that holds `ink8um/` and `model.safetensors` |
| A traceback from `InkDetector.from_pretrained` | `config.json` or `model.safetensors` missing or partial in `--model-dir` (exact text not recorded) | Download the snapshot again |
| `FileNotFoundError: No numbered layer images (00.tif, 01.tif, ...) in LAYERS` | Wrong folder, or file names that are not plain numbers | Write the layers with `python -m kit layers` |
| `ValueError: Need 24 layers starting at index N, found M in LAYERS` | Fewer than 24 layers | Export at least 24 layers |
| `ValueError: Layer shape mismatch: PATH (H, W) vs (H, W)` | Layers of different sizes in one folder | Export the folder again into an empty folder |
| `ValueError: PATH: unsupported layer dtype DTYPE (expected uint8 or uint16)` | Float or other layer images | Export uint8 layers with `kit layers` |
| `OSError: Could not read PATH` | An unreadable or truncated image | Export again |
| `ValueError: Unsupported output format: OUTPUT`, after the whole run | `--output` with another extension | Use `.npy`, `.tif` or `.png`; the run must be repeated |
| `OSError: Could not write OUTPUT` | OpenCV could not write the `.png` or `.jpg` | Check the folder, or write `.npy` |
| A torch `RuntimeError` naming `mps` or `cuda` (exact text not recorded) | That device is not available in this torch or on this machine | Use `--device cpu`, or a torch build with that device |
| The process is killed, or it slows to tens of seconds per tile | Out of memory: fp32 batch 8 used about 10 GB and was killed beside another job on a 15 GB machine; two v8in runs at once on a 16 GB Mac swapped to 56 s per tile ([community scan log](../logs/2026-10-07-community-scan.md), [tricks.md](../tricks.md)) | Lower `--batch-size` (4 at 16 GB) and run one v8in job at a time |
| `tiles=0` and `mean=0.0000`, exit code 0 | No 64 px tile lies wholly inside the covered area: a window under 64 px, or layers that are all zero | Check the crop and the layers; the map is all zeros |

## How it works

1. Parse the arguments, put `--model-dir` first on Python's import path, and import torch and that snapshot's `ink8um`.
2. Refuse `--fp16` unless the device starts with `mps`.
3. Load the model with `InkDetector.from_pretrained(MODEL_DIR)`, which reads `config.json` and `model.safetensors` there.
4. Under the MPS fp16 autocast when `--fp16` is on, call `predict_surface` with the layer folder, `--reverse`, `--stride`, `--batch-size`, `--workers` and `--device`. From the release's `ink8um/inference.py` at `d89166b` (read 2026-10-16):
   1. Read the central 24 layers into a height x width x 24 uint8 stack, clipped to 0..200; reverse its depth axis with `--reverse`.
   2. Coverage mask: pixels where any layer is above 0, closed with a 7 x 7 ellipse.
   3. Tile positions: every 64 x 64 tile at the stride that lies wholly inside the mask.
   4. Each tile, scaled by 1/255, goes through the network: `InstanceNorm3d`, trilinear upsampling to 96 x 256 x 256, the ResNet3D-50 encoder, a maximum over depth at each of its four levels, and the 2D decoder, giving 64 x 64 logits; then a sigmoid. The release's own fp16 autocast is on only for CUDA.
   5. Stitch: add each tile's probabilities times a 64 x 64 Gaussian weight (peak 1, plus or minus one standard deviation across the tile) and divide by the number of tiles covering each pixel; clip to 0..1.
5. Save the map by its extension (`save_prediction`) and print the final line.

Source of the method: the v8in model card and `ink8um/inference.py` of `YoussefMoNader/ink-8um-v8in` at `d89166b41a3f5fad7749b3d7c0fdd1bd3695d844`.

## Cost and time

Measured on 2026-10-07 (sources in the Runs on field):

| Where | Precision | Seconds per tile |
| --- | --- | --- |
| Linux container, 4 CPU cores, v8in | fp32 | about 8 |
| Linux container, 4 CPU cores, v8in-1447 (196 tiles in 1,444 s; 100 tiles in 712 s) | fp32 | 7.1 to 7.4 |
| Chase's M1 Pro, CPU (100 tiles in 2,497 s) | fp32 | 25 |
| M1 Pro, MPS (784 tiles in 862 s and 926 s) | fp32 | 1.1 to 1.2 |
| M1 Pro, MPS | fp16 | 5.5 to 6.2 |

Tile counts: a 640 px crop has about 100 tiles at stride 64 and 784 at stride 21; a whole segment has tens of thousands (the model card's w062 surface, 4,668 x 8,864 px, has 69,794 at stride 21 and takes about 15 to 20 minutes on one recent GPU at batch 16 with about 11 GB, Community report). Memory: fp32 batch 8 about 10 GB of RAM; from the code, the stack takes height x width x 24 bytes and the stitching two float32 maps of the layers' size, which for the whole PHerc0139 w045 surface (5,980 x 8,240) is about 1.2 GB and 0.4 GB (arithmetic, not measured).

Where it runs: a crop at stride 64 on the CPU is minutes, fine locally (log it with `kit run local`). A crop at stride 21 on 4 CPU cores is close to 2 hours, and a whole segment far more: those need a GPU, so they go to Modal (the Modal rule, hard rule 11). Write the run spec in [`docs/compute/modal-specs/`](../compute/modal-specs/README.md); A Claude cloud session can run Modal after `pip install 'modal[api-proxy-support]'`, Chase's sign-in and an allow rule. On 2026-10-07, before that rule, the stride 21 crop runs here ran on Chase's M1 Pro GPU.

## For agents

- **Command:** `python -m kit run local SLUG -- python scripts/v8in_run.py --model-dir V8IN_DIR --layers LAYERS --output OUT/v8in.npy --device cpu --stride 64 --batch-size 4`, then the same with `--reverse --output OUT/v8in_reverse.npy`. There is no JSON output; the machine-readable result is the last stdout line and the map file.
- **Parse:** the last line, with `^device=(\S+) fp16=(True|False) reverse=(True|False) stride=(\d+) tiles=(\d+) done in (\d+)s; shape=\((\d+), (\d+)\) mean=([0-9.]+)$`; seconds per tile is `done in` divided by `tiles`.
- **Rerun:** Safe; a rerun redoes the whole run and replaces `--output`. It does not resume. `scripts/mac-w045.sh` skips a pass only when the map exists and the log's last line names the same device, fp16, direction and stride.
- **Success:** Exit code 0, `tiles=` above 0, and the map file present with `shape` equal to the layers' height and width.
- **Not a pass:** A forward map without a reverse map at the same stride; `tiles=0`; an fp16 map not checked against fp32; a map of a v8in training segment (PHerc0139 w033, w035, w041, w044, or PHerc1447 w058 and w060 for v8in-1447) used as a generalization result; a v8in-1447 map whose direction was taken from its `reverse_layers` setting instead of this script's `--reverse`.
- **Go-ahead:** Nothing for a local run on public data. Renting a GPU (Modal) needs Chase's yes with a cost estimate. Target-scroll maps never go into public work.
- **Never:** Call the map a reading or say letters were found; run a whole segment, or two v8in jobs at once, on a laptop; point `--model-dir` at a folder you did not download from the model's repository (its code runs).

## Tests

None in `tests/`. What can be checked without torch, and the end-to-end check on a Mac:

```bash
python scripts/v8in_run.py --help                      # works without torch: the imports come after parsing
QUICK=1 bash scripts/mac-w045.sh                       # step 5: CPU against MPS on a crop, with the reverse control
```

On 2026-10-16 the wrapper was run with a stand-in for torch and `ink8um` (Quick start): the default stride, `--reverse`, `--stride`, `--batch-size` and `--workers` reach `predict_surface`, the `--fp16` refusal exits 2, and `--device mps --fp16` enters the MPS fp16 autocast. That stand-in is not in the repository, and it does not test the model.

## History

- 2026-10-07: the final line reports `tiles=N`, so the Mac scripts compute seconds per tile from it instead of assuming 100 tiles (`df6bb9b`).
- 2026-10-07: first version, with `--fp16` for MPS, added with `scripts/mac-w045.sh` (`6081aab`).

## Related

- [`layers`](layers.md): writes the layer folder v8in reads, and the depth-shuffle control with `--shuffle`.
- [`auc`](auc.md): scores the map and its reverse against the published labels.
- [`verify`](verify.md): compares two maps of one surface, such as CPU against MPS or fp16 against fp32, with a control.
- [`mac-w045`](mac-w045.md): the Mac script that calls this one, checks the device and fp16, and scores the maps.
- [`mac-phase0`](mac-phase0.md): runs v8in and v8in-1447 on the three PHerc0841 crops one after another.
- [`gate`](gate.md): Gate A, which ranks readers, v8in among them, by their AUCs on the PHerc0841 crops.
- [`run-local`](run-local.md): `kit run local`, which logs a local run's time and electricity.
- [`experiment-records`](experiment-records.md): the saved 2026-10-07 cloud jobs that ran v8in and v8in-1447 with this script.
- [Community scan log](../logs/2026-10-07-community-scan.md): v8in's card, depth order, CPU and Mac timings, and the first Mac result.
- [`results.json`](../results.json): `results` (v8in on the w045 crop), `device_checks`, `community` (Bullo27's PHerc0841 scores), `pending` and `held_out`.
