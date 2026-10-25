# lasagnetta: a fast, self-checked preview of villa's lasagna field

An experimental student of villa's lasagna net that writes a lasagna field preview about 4 times faster than villa `predict3d`, with a self-check that scores it against villa on a few spots and falls back to villa when they disagree.

| Field | Value |
| --- | --- |
| Id | `lasagnetta` |
| Status | Experimental |
| Kind | script folder, model |
| Area | Surfaces and tracing |
| Run | `python scripts/lasagnetta/preview.py --checkpoint release --ct CT --region Z0 Z1 Y0 Y1 X0 X1 --out DIR --name NAME [--self-check]`, `python scripts/lasagnetta/selfcheck.py --checkpoint release --ct CT [--exit-code]`; in Python, `preview.load`, `preview.run`, `selfcheck.check` |
| Code | `scripts/lasagnetta/preview.py` (`run`, the field writer, and `resolve`, which fetches the release), `scripts/lasagnetta/selfcheck.py` (the self-check), `scripts/lasagnetta/lasnet.py` (the student nets and the averaging recipe), `scripts/lasagnetta/teacher.py` (villa's net in process), `scripts/lasagnetta/lgcommon.py` (zarr reading and the agreement metrics). Weights: [SharpMeow/lasagnetta](https://huggingface.co/SharpMeow/lasagnetta) |
| Tests | `tests/test_lasagnetta.py` |
| Needs | Python 3.10 or newer, `torch` (2.x), `numpy`, `numcodecs` (blosc chunks), `huggingface_hub` (to fetch the weights and villa's checkpoint). The self-check also needs a [villa](https://github.com/ScrollPrize/villa) checkout's `lasagna/` folder and its Python dependencies (`LASAGNETTA_VILLA`) |
| Runs on | A CUDA GPU (bf16) or CPU. RTX Pro 6000: a 1024 x 2048 x 2048 region of PHerc0172 in 59.6 s end to end, against 235.2 s for villa `predict3d` (25 Oct 2026). 4-core cloud CPU: a 512^3 region of PHerc0139 in 988 s at batch 1, 5.4 GB peak memory (25 Oct 2026). Self-check: about 50 s per volume on the RTX Pro 6000 |
| Network | `huggingface.co` (the weights with `--checkpoint release`, villa's checkpoint `scrollprize/lasagna` for the self-check) and `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` when `--ct` is an `s3://` path |
| Writes | `DIR/NAME.lasagna.json`, `DIR/NAME_{cos,grad_mag,nx,ny}.ome.zarr`, `DIR/preview.json`; with `--self-check`, `DIR/selfcheck.json`; the weights in `~/.cache/lasagnetta`; `selfcheck.py --out FILE` writes FILE |
| Go-ahead | Not needed to use. The weights went public on Hugging Face with Chase's yes (25 Oct 2026) |
| Released | Experimental release 0.1.0 on 2026-10-25: code in public `main`, weights on Hugging Face; README "Released tools" entry `lasagnetta` |
| License | Code Apache-2.0. Weights CC BY-NC 4.0, like the scans. The teacher is villa's lasagna (MIT); credit to its authors |
| Checked | 2026-10-25 against commit `f989d89` |

## What it does

villa's lasagna net reads a CT scan of a scroll and predicts a lasagna field: a cos signal that repeats once per papyrus layer, its gradient size (grad_mag) and the sheet normals (nx, ny). villa's surface fitting reads that field. Making one with villa `predict3d` takes a GPU for hours on a whole scan.

Lasagnetta is a smaller 3D U-Net trained only to copy villa's output. It writes the same grids (cos at scaledown 2, the others at 4) in villa's own layout, so anything that opens a villa lasagna field opens a preview. The release averages three students, then blurs cos by 0.5 voxels and lowers it by 0.04, an offset fitted on training crops.

It **did not pass** its held-out test. Agreement with villa was good on most scans and under the bar on one or two scans per test (see Checks and controls). So it ships with a self-check: before a preview is trusted, villa's own net runs on 12 spots near the region and the preview is scored against it. When the median peak F1 is under 0.82, the self-check says to use villa instead.

Its output is model output, a preview of another model's output. It is not ground truth, and it is not a reading of any text.

## When to use it

- A quick look at the layer signal or normals of a region where no villa field is published, when speed matters more than exact values.
- A first pass over many regions, with `--self-check` deciding where villa must run.

Do not use it:

- Where exact villa values matter, such as a fit you will report: run villa's lasagna, or use a published field or [Lasagna Fields](lasagna-fields.md).
- Without the self-check on a scan type it has not seen: two of the ten held-out scans were under the bar.

## Quick start

```bash
pip install torch numpy numcodecs huggingface_hub
python scripts/lasagnetta/preview.py --checkpoint release \
    --ct s3://vesuvius-challenge-open-data/PHerc0139/volumes/20260102150214-2.399um-0.2m-78keV-masked.zarr/2 \
    --region 9472 9984 3072 3584 4096 4608 --input-level 2 --out out --name PHerc0139 --device cpu
```

It printed (25 Oct 2026, 4-core CPU):

```
slab 3/3: 27 tiles so far
{"config": "ens(l32n,xl,w24)", "flips": "none", "cos_blur": [0.5, 0.5, 0.5], "cos_offset": 0.04, ... "tiles": 27, ... "total_s": 987.63, "chunks_written": {"cos/3": 512, "cos/4": 64, "grad_mag/4": 64, "nx/4": 64, "ny/4": 64}}
```

It worked when `out/PHerc0139.lasagna.json` and the four `.ome.zarr` folders exist and `config` reads `ens(l32n,xl,w24)`. The region is in voxels of the CT level given to `--ct` (here level 2 of a 2.4 um scan, as villa's "-L2" fields read it). Add `--self-check` (with `LASAGNETTA_VILLA` set) to check it against villa first.

## Checks and controls

Agreement is measured against villa's net, never against truth, on 256^3 crops: Pearson r of cos (cos r) and of grad_mag (grad r), the median angle between normals, and peak F1, which matches sheet crossings (local maxima of cos at or above 0.5 along y and x lines) within one cos voxel. The bars, fixed before each test, were 0.80, 0.80, 12 degrees and 0.70, on the pooled median and on each scan. Each test's control rolls the maps by 3 cos voxels and must fail.

| Held-out test (25 Oct 2026) | Model | Pooled cos r, peak F1, normal, grad r | Peak F1 per scan | Speed | Verdict |
| --- | --- | --- | --- | --- | --- |
| Second | the `l32n` student alone, blur 0.5 | 0.864, 0.811, 4.0, 0.796 | PHerc0175A 0.863, 0175B 0.759, 0306B 0.828, 0846A 0.824, 0846B 0.809 | 6.9x | FAIL |
| Third | the release | 0.910, 0.855, 3.1, 0.877 | PHerc0009B 0.849, 0172 0.852, 0500P2 0.861, MAN5 0.774, MANB 0.870 | 3.9x | FAIL |

Each scan had 30 crops, and no student had trained on any scan of its own test. The control failed in both (third test: cos r 0.07, peak F1 0.16). The self-check was then run on 13 whole volumes, two seeds each. It sent PHerc0175B (median peak F1 0.64), PHercMAN5 (0.81, 0.82), PHerc0846B (0.81, 0.78) and PHerc0172 (0.79) to villa. It kept the preview on PHerc0800, 1545, 0814, 0175A, 0306B, 0846A, 0009B and MANB (0.82 to 0.90). Two of the three students had trained on PHerc0175A, 0306B and 0846A. On one PHerc0500P2 seed the first version of the check found only 6 spots and fell back; it now tries up to 2,000 spots.

The comparison is with villa's lasagna, the one released model for this field. No other released fast lasagna model is known (25 Oct 2026). Sources: the model card at [SharpMeow/lasagnetta](https://huggingface.co/SharpMeow/lasagnetta).

Claim label: Model output (agreement of one model's output with another's on public scans; nothing here is ground truth)

## Commands and options

### preview.py

```
usage: preview.py [-h] --checkpoint CHECKPOINT --ct CT --region Z0 Z1 Y0 Y1 X0 X1 --out OUT --name NAME [--input-level INPUT_LEVEL]
                  [--base-shape BASE_SHAPE BASE_SHAPE BASE_SHAPE] [--levels LEVELS] [--batch BATCH] [--device DEVICE] [--flips {none,x8,yx4}]
                  [--cos-blur SZ SY SX] [--cos-offset COS_OFFSET] [--self-check] [--self-check-spots SELF_CHECK_SPOTS]
                  [--self-check-threshold SELF_CHECK_THRESHOLD] [--teacher TEACHER]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--checkpoint` | required | A student `.pt`, several joined by commas (averaged), or `release` (the released average and its recipe, downloaded) |
| `--ct` | required | The zarr v2 folder of the CT level the student reads: a local folder, or `s3://vesuvius-challenge-open-data/...` |
| `--region` | required | z0 z1 y0 y1 x0 x1 in voxels of that level, rounded out to multiples of 128 |
| `--out`, `--name` | required | Output folder and the field's name |
| `--input-level` | `0` | The OME-Zarr level `--ct` is, so the field's metadata scales to level 0 |
| `--base-shape` | from `--ct` | Level-0 shape, when it is not `--ct`'s shape times 2^level |
| `--levels` | `4` | Coarser pyramid levels to write where the region is aligned |
| `--batch` | 4 on CUDA, 1 elsewhere | Tiles per forward |
| `--device` | `cuda` if available | Torch device |
| `--flips` | `none` | Flip averaging (`yx4`, `x8`); slower, not part of the release recipe |
| `--cos-blur` | `0 0 0` | Gaussian sigmas of cos (cos voxels); `release` sets `0.5 0.5 0.5` |
| `--cos-offset` | `0` | Lowers cos after the blur, clipped to 0..1; `release` sets `0.04` |
| `--self-check` | off | Run the self-check first; exit 3 with no field when it falls short |
| `--self-check-spots`, `--self-check-threshold` | `12`, `0.82` | The self-check's spots and median peak F1 cut |
| `--teacher` | `scrollprize/lasagna` at a pinned revision | villa's checkpoint for the self-check (sha256 checked when downloaded) |

### selfcheck.py

```
usage: selfcheck.py [-h] --checkpoint CHECKPOINT --ct CT [--region Z0 Z1 Y0 Y1 X0 X1] [--cos-blur SZ SY SX] [--cos-offset COS_OFFSET] [--spots SPOTS]
                    [--min-spots MIN_SPOTS] [--threshold THRESHOLD] [--seed SEED] [--teacher TEACHER] [--out OUT] [--exit-code] [--device DEVICE]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--checkpoint`, `--ct` | required | As for preview.py |
| `--region` | the whole level | Where to look; it is grown to at least 2,048 voxels a side for the spots |
| `--cos-blur`, `--cos-offset` | `0` | The recipe to check (`release` sets it) |
| `--spots`, `--min-spots`, `--threshold` | `12`, `8`, `0.82` | Spots drawn, spots needed, median peak F1 cut |
| `--seed` | `20261025` | Spot draw seed |
| `--teacher` | `scrollprize/lasagna` | villa's checkpoint |
| `--out` | none | Write the full record as JSON |
| `--exit-code` | off | Exit 3 when the decision is villa |
| `--device` | `cuda` if available | Torch device |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `LASAGNETTA_VILLA` | `/opt/villa/lasagna` | villa's `lasagna/` folder, imported for the self-check's teacher (`train_unet_3d`, `normal_encoding`) |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `preview.load(checkpoint, device)` | `(net, config)` | `FileNotFoundError`, torch load errors | Comma-joined paths give a `lasnet.Ensemble`; loads with `weights_only=True` |
| `preview.resolve(args)` | `args` | Hub download errors | `checkpoint == "release"`: download the files, set the recipe |
| `preview.run(net, meta, get, region, device, batch, log, flips, cos_blur, cos_offset)` | `(products, tiles)` | read errors | uint8 cos, grad_mag, nx, ny over the region |
| `selfcheck.check(net, teacher, meta, get, region, device, spots, threshold, min_spots, seed, cos_blur, cos_offset, log, coarse)` | `dict` | `ImportError` without villa | The self-check record (see Outputs) |
| `selfcheck.decide(rows, threshold, min_spots)` | `(decision, median, n)` | None | `"student"` or `"villa"` |
| `lasnet.predict_maps(net, x, flips, cos_blur, cos_offset)` | `dict` of tensors | None | The averaging recipe on a batch |
| `lgcommon.crop_metrics(pred, tgt, shift=0)` | `dict` | None | cos_r, peak_f1, normal_deg, gm_r and peak counts for one crop |

## Inputs

- **CT**: a zarr v2 array (uint8, the masked open-data volumes, zero outside the scroll), the level villa's lasagna reads: level 0 of the 7.9 to 9.4 um scans, level 2 of the 2.4 um scans. Local folders or `s3://vesuvius-challenge-open-data/SCAN/volumes/VOLUME.zarr/LEVEL`.
- **Region**: z0 z1 y0 y1 x0 x1 in that level's voxels. Any size; time grows with volume.
- **Weights**: `release`, or any `.pt` dict with `config` and `state_dict` from this code.

## Outputs

`NAME.lasagna.json` and `NAME_{cos,grad_mag,nx,ny}.ome.zarr` in villa's layout, written only over the region. `preview.json` (and stdout):

| Field | Type | Meaning |
| --- | --- | --- |
| `config` | string | Net config, `ens(...)` for an average |
| `cos_blur`, `cos_offset`, `flips` | list, float, string | The recipe used |
| `region` | list | The rounded region, in `--ct` voxels |
| `tiles` | int | 256^3 tiles run |
| `load_s`, `predict_s`, `write_s`, `total_s` | float | Seconds |
| `chunks_written` | dict | Chunks per product and level |
| `self_check` | dict | With `--self-check`: the record below without its rows |

The self-check record (`selfcheck.json`, `--out`):

| Field | Type | Meaning |
| --- | --- | --- |
| `decision` | string | `student` (use the preview) or `villa` (run villa) |
| `median_peak_f1`, `median_cos_r` | float | Medians over the scored spots |
| `spots_scored`, `spots_drawn` | int | Spots scored and drawn |
| `threshold`, `min_spots`, `seed`, `region` | | The rule and where it looked |
| `seconds` | float | Time taken |
| `rows` | list | Per spot: `origin` and its metrics |

| Exit code | Meaning |
| --- | --- |
| `0` | preview.py: the field was written. selfcheck.py: the check ran (read `decision`) |
| `2` | A missing or wrong argument |
| `3` | `--self-check` or `--exit-code`: the self-check said to use villa; preview.py wrote no field |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `crop origin...is not on the...grid` | A self-check spot off villa's 128 grid (only from a hand-made region in code) | Use `selfcheck.check`'s own spot drawing |
| `...is not the pinned villa lasagna checkpoint` | The downloaded villa checkpoint's sha256 differs | Delete the download folder and retry, or pass `--teacher` |
| `ModuleNotFoundError: No module named 'train_unet_3d'` | `--self-check` without villa's lasagna folder | Set `LASAGNETTA_VILLA` to a villa checkout's `lasagna/` |
| The process is killed on CPU | Out of memory | `--batch 1` (the default off CUDA) and a smaller region |
| `decision: villa` with `spots_scored` under 8 | Too little papyrus near the region | Widen `--region`, or run villa |

## How it works

1. The CT is read in 256^3 tiles that step by 192 and keep their middle 192, so tiles never blend.
2. Each student writes cos at 1/2 and grad_mag and the normal at 1/4 directly, never decoding to full resolution. The release averages the three students' cos and grad_mag, and their normals with signs aligned.
3. cos is blurred (sigma 0.5 cos voxels) and lowered by 0.04, clipped to 0..1. That is the same as raising the peak cut to 0.54, and it was fitted on 108 training crops.
4. Products are finalized as villa does (cos x 255, grad_mag, normals encoded to nx, ny with nz >= 0) and written as villa's OME-Zarr layout with coarser levels.
5. The self-check draws spots on villa's 128 grid near the region. A spot is kept when at least 98 % of its context is papyrus, with a pre-check on the level 8 times coarser. On each spot it runs villa's net on predict3d's tile lattice (tile 192, stride 128, villa's blend ramp, bf16) and pools the raw channels with villa's Gaussian pyramid to the stored scaledowns. It then scores the preview with `lgcommon.crop_metrics` and decides on the median peak F1 (`SPOTS 12`, `MIN_SPOTS 8`, `THRESHOLD 0.82`, `SPAN 2048`).

## Cost and time

Measured on 25 Oct 2026: on an RTX Pro 6000, 59.6 s for 4.3 G voxels end to end against villa's 235.2 s on the same GPU. On a 4-core cloud CPU, a 512^3 region took 988 s with 5.4 GB peak memory. The self-check takes about 50 s per volume on the GPU, mostly reading CT over the network. Nothing is rented by the tool itself. Not measured: Apple MPS for the average (one student was about 1.2 s per 256^3 tile).

## For agents

- **Command:** `python scripts/lasagnetta/preview.py --checkpoint release --ct CT --region Z0 Z1 Y0 Y1 X0 X1 --out DIR --name NAME --self-check`
- **Parse:** the last stdout line is JSON: `preview.json` on success, the self-check record (without rows) on exit 3; `DIR/selfcheck.json` has every spot.
- **Rerun:** safe; it overwrites the chunks it writes under DIR.
- **Success:** exit 0 and `DIR/NAME.lasagna.json` present; with `--self-check`, `self_check.decision` is `student`.
- **Not a pass:** a preview made without `--self-check` on a new scan type; a self-check with `spots_scored` under 8 (it falls back by design).
- **Go-ahead:** Nothing.
- **Never:** call the preview villa's field, or ground truth; report a fit from it without rerunning on villa's field.

## Tests

`python -m unittest tests.test_lasagnetta -v`. Without torch, it covers the metrics (peaks, normals, the shifted control) and zarr reading. With torch, it also covers the averaging recipe, loading comma-joined checkpoints, spot drawing, the widened region, the decision rule, and one self-check end to end with a stub teacher on CPU. CI has no torch, so only the numpy half runs there. Not covered: villa's real net (it needs a villa checkout) and the released weights.

## History

- 2026-10-25: experimental release 0.1.0: the code, the self-check and the weights on Hugging Face, after the third held-out test failed on PHercMAN5 (Chase chose to release it as a preview with a self-check).

## Related

- [lasagna-fields](lasagna-fields.md): villa's own lasagna fields for ten scans, and Make a field for any box: the reference Lasagnetta copies.
- [SharpMeow/lasagnetta](https://huggingface.co/SharpMeow/lasagnetta): the weights and model card.
