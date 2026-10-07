# Crop-invariant inference assessment

Source review only. No implementation was adopted, no reader inference was run, and no runtime or accuracy result is claimed.

## Pinned sources

- UFSM: `SuperOptimizer/ufsm`, commit `d86a00cff5ab198e6b7864f89e49a6101746dc9f`.
- Official villa reader: `ScrollPrize/villa`, commit `e0bbb8b40a2db58b1d71864f286eb85717e59e64`.
- Scrolls base v8in: Hugging Face `YoussefMoNader/ink-8um-v8in`, revision `d89166b41a3f5fad7749b3d7c0fdd1bd3695d844`; selected by `scripts/mac-w045.sh:43-48`.

## What UFSM actually provides

[README.md:350-359](https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/README.md#L350) describes `--grid-origin 0,0,0`: common voxels receive the same complete neural windows when the requested box or output shard changes. It also explicitly identifies repeated forwards on off-grid boxes and codec-block dependence for lossy output.

[src/predict.c:258-304](https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/src/predict.c#L258) implements this, rather than merely recording an origin. Its stride is window minus twice the halo. The modulo calculation uses the requested box origin, shard origin and fixed grid origin. It reads complete anchored windows outside the requested box and clips their output to the shard. [src/predict.c:50-53](https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/src/predict.c#L50) reads CT at those actual global coordinates. [tests/test_pipeline_cli.py:75-95](https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/tests/test_pipeline_cli.py#L75) contains the project's crop, placement and worker invariance fixtures; these were inspected, not run here.

The reusable feature is the coordinate and context contract. UFSM's serving engine itself is CUDA-dependent: [Makefile:21-23,41-59](https://github.com/SuperOptimizer/ufsm/blob/d86a00cff5ab198e6b7864f89e49a6101746dc9f/Makefile#L21) links CUDA and builds SM120/SM120a kernels. `UFSM_PRED_HOSTPATH` changes host/device transfer and assembly, not the CNN backend (`src/predict.c:270-279,364-369`). It is not a CPU inference option.

## Current Scrolls behavior

`kit/layers.py:69-109` exports a literal cropped array. The returned record includes the crop and full source shape (`114-121`), but the TIFF image coordinates themselves restart at zero. `scripts/mac-w045.sh:238-243,261-267` exports crops and runs `scripts/v8in_run.py`; that wrapper forwards stride and depth direction to the model's own `predict_surface` (`scripts/v8in_run.py:52-54`) and has no global spatial origin argument.

The pinned [v8in inference.py:93-111](https://huggingface.co/YoussefMoNader/ink-8um-v8in/blob/d89166b41a3f5fad7749b3d7c0fdd1bd3695d844/ink8um/inference.py#L93) starts tile positions at local zero, omits an irregular terminal tile, and requires every pixel in the tile to pass a 7x7 morphological closing of depth coverage. Its stitch divides Gaussian-weighted predictions by tile count, not weight sum (`148-175`). Those historical semantics must be preserved if reproducing its whole-canvas output.

The CPU adapter `/workspace/scrolls-env/infer_layers_cpu.py:17,54-56,88-103,135-144` pins villa, uses the official preprocessing/model/reader on CPU, and supplies no spatial-origin argument. Villa's [infer.py:247-280](https://github.com/ScrollPrize/villa/blob/e0bbb8b40a2db58b1d71864f286eb85717e59e64/vesuvius/src/vesuvius/ink_detection/inference/infer.py#L247) starts at local zero and appends a boundary-aligned `length - patch_size` position. Its patch normalization occurs per complete patch (`509-522`) and its stitch uses probability and importance-weight sums (`681-712`). Thus changing crop origin or extent can change both the model input and the set of overlapping predictions.

## Feasible CPU adoption

A wrapper can preserve the pinned reader and reproduce its legacy whole-canvas windows. Upstream support is not mandatory:

1. Require the original rendered canvas identity, dimensions, requested global UV rectangle, and unchanged depth/normalization/blending settings.
2. Freeze the reader's tile starts from that full canvas. Keep every complete tile intersecting the requested output, including villa's exceptional full-canvas tail.
3. Read an expanded rectangle containing those complete tiles from real rendered source data. For each axis, its first retained tile start is the expanded origin; its end is the last retained start plus patch size, clipped only at the actual full-canvas boundary.
4. Run the unchanged reader on that rectangle, then trim to the requested output. An interior villa envelope has size `P + k*S`. At a true canvas edge it may not, and its local appended tail must correspond to the original full-canvas `H-P` tail. Simply rounding every crop to a regular stride grid does not reproduce that tail.

V8in additionally needs coverage closing computed with the same surrounding data as the full canvas. Closing can depend on data up to six pixels away. Extend the real-data envelope beyond retained tile extents by sufficient grid-aligned context, or add an explicit frozen global coverage-mask API. Only the actual canvas boundary should use the original border rule. Zero-padding unavailable data outside an arbitrary crop invents context and fails this contract.

A new regular globally anchored policy is also possible, but is a new opt-in inference recipe. It must not be described as reproducing legacy whole-map tails. A streaming implementation with explicit starts and global read/output coordinates would be cleaner for large volumes; it requires a local integration or upstream scheduler API rather than a checkpoint or model-architecture change.

## Limits and proposed verification

This improves reproducibility and makes crop-versus-full comparisons interpretable. It does not establish better ink accuracy or transfer UFSM throughput to CPU. Real source context must exist; existing standalone cropped TIFFs cannot reconstruct missing surrounding pixels. Any integration should preserve historical mode, record requested and expanded origins, canvas and input hashes, exact tile policy, coverage support, and all controls. It must leave current frozen experiments unchanged.

Before claiming invariance, compare a whole-canvas run against overlapping off-grid crops, shifted origins, changed extents, shards, true boundaries, canvases smaller than a patch, holes and morphology near crop edges. Check the actual input tile bytes, support/count or weight maps, float probabilities and final encoded output, with fixed CPU settings and accumulation order. Batch-size and codec differences need separate validation. No such runtime comparisons were performed in this assessment.
