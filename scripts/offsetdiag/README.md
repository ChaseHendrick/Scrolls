# Ink offset diagnostic

How much does an ink model's AUC change when a segment's surface moves a few voxels along its normal, and does moving each pixel to villa's lasagna sheet center help? This folder renders a labeled segment box from the scan along its mesh normals, cuts 28-layer stacks ("arms") at constant shifts and at the lasagna sheet center with two same-size controls, maps every arm with villa's own ink inference in both depth directions, and scores each map against the published labels with its reverse-depth map as control. Every map is model output, not a reading.

Full page: [`docs/tools/offsetdiag.md`](../../docs/tools/offsetdiag.md).

## Steps

```bash
python3 scripts/offsetdiag/offsetdiag.py fetch 0841-w00 --work WORK      # mesh, labels, published box (P0)
python3 scripts/offsetdiag/offsetdiag.py validate 0841-w00 1500 600 --work WORK
python3 scripts/offsetdiag/offsetdiag.py render 0841-w00 --work WORK     # 44 offsets along the normal
python3 scripts/offsetdiag/offsetdiag.py measure 0841-w00 --work WORK    # lasagna sheet center, 8 px grid
python3 scripts/offsetdiag/offsetdiag.py arms 0841-w00 --work WORK       # R0, Rm8, Rm4, Rp4, Rp8, SNAP, ANTI, RAND
VILLA_PYTHON=VILLA/vesuvius/.venv/bin/python bash scripts/offsetdiag/infer.sh reader-v3.pth WORK rv3   # CUDA GPU
python3 scripts/offsetdiag/offsetdiag.py score --work WORK --model rv3
```

The first five steps run on any CPU from public data. `infer.sh` needs villa's `vesuvius` package and a CUDA GPU: your own machine, or a Hugging Face Job you own (the page gives both recipes).

## Files

| File | What it holds |
| --- | --- |
| `offsetdiag.py` | The command line |
| `oddata.py` | The segment table, public URLs and a chunked zarr v2 reader with a disk cache |
| `odgeom.py` | Mesh normals, the render along the normal, the convention check and the lasagna sheet center |
| `odarms.py` | The arms and their controls |
| `odscore.py` | AUC with the reverse-depth control and the paired difference to R0, through `kit.auc` |
| `infer.sh` | villa's `infer` over every arm, both directions |

## What it has shown

On two PHerc0841 development segments (w00 and ag896, 30 October 2026, Reader V3, Model output), moving the surface 4 voxels toward layer 0 cost 0.07 and 0.04 AUC, and 8 voxels cost 0.25 and 0.21; the same moves toward layer 27 cost less (about 0.02, not significant, at 4; 0.16 and 0.12 at 8). Snapping to the lasagna sheet center cost 0.03 to 0.08 but beat its same-size controls. Development only, two segments of one scroll, not a test: see the page.

Code: Apache License 2.0 (`LICENSE`). Data: the Vesuvius Challenge open data (CC BY-NC 4.0) and villa's lasagna field for the same scan, read live, not copied.
