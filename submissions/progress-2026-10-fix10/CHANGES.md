# AutoPipeline 0.1.10: labels, fibers and joins after a run

This package follows AutoPipeline 0.1.9 at public commit `2144cdfcac4ecfc33150f7e81317e5ab33f248d6`. Earlier released branches and tags stay unchanged. Every surface, label, fiber and score the pipeline makes is model output, not a reading, and this release makes no claim that any of the three new steps is right on a new trace.

## Three steps that follow a run

`python -m kit apcouple` adds three stages to the stage registry, each with an `off` choice so its effect can be measured by turning it off:

- `labels`: `snapped` moves each surface onto the recto face of its sheet in the CT, with an abstain mask, an OME-Zarr surface label (1 surface, 2 ignore) and a VC3D review queue. It is Snapped Labels' placement code, the same function `python -m kit labelsnap snap` runs. `mesh` writes the surface as given, as the same label, with no snap: the baseline a test compares against.
- `fibers`: `weft` traces papyrus fibers with Weft, our fiber tracer, in a box around the surface `labels` wrote, from the public AFV V2 fiber probabilities of Qual's model for the run's own scan, and writes `.afv` files that open in VC3D. Weft was written for this repository; Qual's spline generator was read only for its file format and coordinate convention.
- `joins`: `kfh1` scores each horizontal fiber end on the surface for a glued sheet join (kollesis) with the kollesis finder's score, the patch followed along the surface behind the end, and writes the same score at a point moved back about 3 cm along the surface as a control. Its geometry was set in 2.399 um voxels and is scaled to the scan's voxel size; at coarse voxel sizes only ends with long unbroken surface rows behind them are scored.

`python -m kit apcouple from-run APRUN` makes a coupled run folder from a finished AutoPipeline run (its accepted traces, scan and center line); `init` makes one from any tifxyz surface. `chain` runs the three steps in order, `labels`, `fibers` or `joins` runs one, `swap RUN STAGE A B` runs two choices of one stage and the steps after it side by side and writes what changed, and `check` holds a folder to each step's contract. Records keep paths relative to the run folder, so a copied folder still checks.

Inside a plan, as plan settings, the steps come in a later version; a plan that names them is refused until then, and every plan made before keeps its digest.

## Other changes since 0.1.9

- `kit switchfix barrier2`: a second version of the contact barrier's cut, with a wider grouping of the touching zone and a seed guard that refuses rather than keep a piece on another winding. Experimental and off by default: it has not been tested on held-out data, and AutoPipeline's default repair stays the first version.
- `kit meshqa crop` (region crop) finds its pieces faster, in one pass over the grid; its piece areas are the same up to floating-point summation order, checked by its tests.
- The ink Space (`space/`): every tool is also an API endpoint and an MCP tool (`ink_sample`, `ink_upload`, `list_samples`), with Space tags and the `mcp` and `pydantic` pins Gradio's MCP server needs; the page itself works as before. American spellings in its text and in the Crackle Check engine comments.

## Checks

Parity tests require each step's output to equal its own tool run alone on the same input (`kit labelsnap snap`, Weft's `crop`, the kollesis score). Other tests require `check` to refuse a folder with no run record and to name a later record made stale by rerunning an earlier step, a copied folder to check clean, and a swap to keep each arm's own settings. Weft's tests trace synthetic probability volumes with known fibers. A smoke run of the whole chain on public PHerc0814 data (a traced mesh cut to a long strip) ran on a Hugging Face CPU Job: the steps ran in order, each read the one before, and the copied run folder checked clean. That shows the steps run; it is not a test of any label, fiber or join score.

## Package

Version metadata changes from 0.1.9 to 0.1.10. The optional extra `couple` adds `huggingface_hub`, which the fibers step reads the probability blocks with. The Docker image was not rebuilt for this version. This package does not assert a Progress Prize form submission or award.
