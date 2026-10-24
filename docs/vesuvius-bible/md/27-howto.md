<a id="ch-howto"></a>

# How-Tos {#ch-howto}

> **Chapter summary.** Step-by-step recipes adapted from the official tutorials as of October 2026: getting the code, viewing a scroll and growing a segment in VC3D, rendering a segment, training and running an ink model, searching an unread scroll for first letters with the shared 9 µm models, and fitting the spiral. Commands are quoted from the tutorials; check the live pages before running them, because the tools change quickly. Nothing here requires private data.

All recipes assume Linux with an NVIDIA GPU and CUDA, as the ink tutorial does ("Windows users are advised to use WSL2") [VC-InkTutorial].

## Recipe 1. Get the code

```
git clone https://github.com/ScrollPrize/villa.git
cd villa/vesuvius
uv sync --extra models
uv run --extra models python -c "import torch; print(torch.__version__, '| cuda:', torch.cuda.is_available())"
```

`uv sync --extra models` "creates a virtual environment and installs the exact locked dependencies" [VC-InkTutorial]. The `vesuvius` package also provides the data-access API shown in [Chapter 22](22-tools.md#ch-tools).

## Recipe 2. Install VC3D

| Platform | Method | Source |
|---|---|---|
| Windows | installer .zip from the villa releases page | [VC-VC3DTutorial] |
| Linux | build from source with `villa/volume-cartographer/build_from_src_debian.sh` | [VC-VC3DTutorial] |
| Any with Docker | `docker pull ghcr.io/scrollprize/villa/volume-cartographer:stable` | [VC-VC3DTutorial] |
| Mac | application in the Applications folder | [VC-VC3DTutorial] |

On Linux, launch with `cd build/bin && ./VC3D` [VC-VC3DTutorial].

## Recipe 3. View a scroll and grow a first segment

Following the VC3D tutorial, which uses PHerc. 1447 [VC-VC3DTutorial]:

1. **File, Open Data Catalog...**, select PHerc1447, **Open Sample**.
2. Navigate: right click pans; `ctrl+click` or `R` moves the focus point, and the other planes align with it.
3. The recto surface predictions for PHerc. 1447 appear in the overlay selector; overlay them to see the sheets.
4. `ctrl+right click` on a point, then **Create Segment (GrowPatch)**. Wait for "Successful".
5. Open **Volume Package** and select the new segment.
6. **Segmentation, Enable Editing**; grow with keys `1` (left), `2` (up), `3` (down), `4` (right), `5` (all directions).
7. For hard regions, use **Line Annotation** from the `ctrl+right click` menu; the first time, VC3D asks to load the Lasagna normals.

Inspect for sheet switches as you grow ([Chapter 18](18-tracing.md#ch-tracing)).

## Recipe 4. Render a segment to a surface volume

The ink tutorial renders segment w035 of PHerc. 0139 at the native 9.362 µm [VC-InkTutorial]:

```
aws s3 sync --no-sign-request \
  s3://vesuvius-challenge-open-data/PHerc0139/segments/20260317000000-w035_2026031718/mesh/20260317000000-on-20250728140407-9.362um.tifxyz/ \
  ink-dataset/pherc0139/w035/w035.tifxyz

vc_render_tifxyz \
  --volume s3://vesuvius-challenge-open-data/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr/ \
  --segmentation ink-dataset/pherc0139/w035/w035.tifxyz \
  --zarr-output ink-dataset/pherc0139/w035/w035_9um.zarr \
  --scale 1 --group-idx 0 --num-slices 28 \
  --cache-gb 16 \
  --voxel-size 9.362 --voxel-unit micrometer \
  --flip-normals
```

"For w035 this takes about five minutes and writes a ~900 MB Zarr." The rendered volume is "28 slices of 5820x5240 at 9.362 µm", and "No ink is visible to the eye; that's the model's job." Inside VC3D, right-clicking a segment and choosing **Render** runs the same renderer [VC-InkTutorial]. Chunks are cached in `~/.VC3D/remote_cache`.

## Recipe 5. Train an ink model on one segment

1. Download one labeled segment (about 25 GB):

```
uvx --from huggingface_hub hf buckets sync \
  hf://buckets/scrollprize/datasets/ink/phercparis4/w00_20231016151002 \
  ./ink-dataset/phercparis4/w00_20231016151002
```

2. Create `configs/ink_tutorial.json`. Key settings from the tutorial: `"mode": "flat"`, `"model_type": "vesuvius_unet"`, `"z_projection_mode": "max"`, `"patch_size": [64, 256, 256]`, `"patch_overlap": 0.5`, `"patch_min_labeled_coverage": 0.05`, `"batch_size": 2`, `"num_iterations": 20000`, `"learning_rate": 0.01`, `"mixed_precision": "fp16"`, `"val_every": 500`, `"save_every": 1000`, and a `datasets` entry pointing `segments_path` at the folder of segments [VC-InkTutorial].
3. Train:

```
uv run --extra models python -m vesuvius.ink_detection.training.train configs/ink_tutorial.json
```

The run "takes about an hour and a half on a single H100". Checkpoints `ckpt_001000.pth` and onward, plus `train_previews/`, appear in `out_dir` [VC-InkTutorial].

4. If out of memory: "reduce `batch_size` to 1, or reduce the `patch_size` to `[64, 128, 128]`". For multiple GPUs use `accelerate launch --num_processes 2` [VC-InkTutorial].

## Recipe 6. Run inference

```
uv run --extra models python -m vesuvius.ink_detection.inference.infer \
  /path/to/ink-dataset/phercparis4/w00_20231016151002/w00_20231016151002.zarr \
  runs/ink_tutorial/ckpt_020000.pth \
  predictions/w00_20231016151002.tif \
  --overlap 0.5 --blend-mode hann \
  --batch-size 4
```

Expect "on the order of an hour on a single GPU for a full segment". For many segments, use folder mode: `--folder /path/to/ink-dataset/phercparis4 --checkpoint-path ...`, which writes each prediction into a `preds/` directory inside the segment [VC-InkTutorial].

## Recipe 7. A first-letters search with the shared 9 µm models

This is "the first-letters workflow: take a segment of an unread scroll, render it, run the shared models, and look" [VC-InkTutorial].

1. Download a checkpoint:

```
uvx --from huggingface_hub hf download scrollprize/ink_9um \
  hybrid_3d2d-seed42/step-075000.pth --local-dir checkpoints/ink_9um
```

2. Render your segment at the scroll's native ~9 µm (Recipe 4), using the `.tifxyz` produced in VC3D.
3. Run flat inference with the 9 µm checkpoint, for example `--batch-size 32` on a large GPU, dropping "to 4 or 1 if you run out of memory".
4. Interpret carefully:
   - "The models are sensitive to depth offsets"; shift the window with `--layer-start` / `--layer-end`, or average nearby windows.
   - "The background doesn't sit at zero": with label smoothing 0.5, targets are 0.25 and 0.75, so rescale for display, for example `(p - 0.25) / 0.5` clipped to [0, 1].
   - Run both seeds, several steps, and `--direction both` when the surface orientation is unknown [VC-InkTutorial].
5. Before submitting, follow the prize rules on false-positive mitigation: "The larger your model's window size, the easier it is for it to invent plausible letterforms instead of recovering real ink", and do not publish findings before the prize is announced [VC-Prizes].

The PHerc. 343 award in October 2026 shows how a winning first-letters submission documented its method ([Chapter 13](13-2026.md#ch-2026)) [VC-PHerc343].

## Recipe 8. Fit the spiral

```
git clone https://github.com/ScrollPrize/villa.git
cd villa/spiral-fitting
uv sync
rclone copy :http: ./spiral_datasets/phercparis4 \
  --http-url https://dl.ash2txt.org/datasets/spiral_datasets/PHercParis4/ \
  --transfers 32 -P
FIT_SPIRAL_CONFIG_OVERRIDES='{"z_begin": 10500, "z_end": 11500, "optimizer_num_training_steps": 10000}' \
  python fit_spiral.py --dataset ./spiral_datasets/phercparis4
```

Notes from the tutorial [VC-SpiralTutorial]:

- Keep torch below 2.13; later versions "will require _significantly_ more vram".
- The default z range (4,000 to 17,000) "span[s] the whole written region of Scroll 1"; "Consider starting with a small range", and about 1,000 slices "is a good first run".
- A default fit runs "30,000 optimization steps", printing losses "every 200 steps". Multi-GPU: `torchrun --nproc-per-node=N fit_spiral.py --dataset ...`.
- Outputs go to `out/<run>/`: `checkpoint_fitted.ckpt`, `satisfied_fitted.json`, `satisfaction_metrics_fitted.json`, overlay PNGs and `meshes/mesh/`.
- `runners/run_single.py` runs fit, ink render and scoring in one command; `render_ink.py` renders ink through a fitted mesh.
- Environment variables: `FIT_SPIRAL_OUT_DIR`, `FIT_SPIRAL_RUN_DIR`, `FIT_SPIRAL_RUN_TAG`, `FIT_SPIRAL_RESUME_PATH`, `FIT_SPIRAL_RESUME_STEP`, `WANDB_MODE`. The preprocessing cache defaults to `~/.cache/vc3d/spiral`.

## Recipe 9. Submit a progress prize

From the prize rules [VC-Prizes]:

1. Open-source the work under a permissive license, with documentation.
2. Prefer community formats (OME-Zarr, tifxyz, meshes).
3. Bundle a month's small fixes into one submission.
4. Submissions "are evaluated monthly" through the submission form on the prizes page; the deadline current at the time of writing was "11:59pm Pacific, October 31st, 2026".
5. Keep discoveries of hidden text private until the official announcement; the data agreement forbids publishing hidden text without approval [VC-FAQ].

## Troubleshooting

| Symptom | Likely cause | Fix from the tutorials |
|---|---|---|
| CUDA out of memory in training | patch or batch too large | smaller `batch_size` or `patch_size` [VC-InkTutorial] |
| Prediction looks washed out | label-smoothing range | rescale `(p - 0.25) / 0.5` [VC-InkTutorial] |
| No response from a 9 µm checkpoint | depth offset or orientation | `--layer-start`/`--layer-end`, `--direction both`, other seeds and steps [VC-InkTutorial] |
| Hugging Face rate limits | anonymous downloads | free account and `HF_TOKEN` or `hf auth login` [VC-InkTutorial] |
| Spiral fit runs out of GPU memory | torch 2.13 or later, or z range too large | pin torch below 2.13; fit about 1,000 slices first [VC-SpiralTutorial] |
| Validation accuracy stalls while loss drops | overfitting to labels | more segments, held-out validation regions [VC-InkTutorial] |
