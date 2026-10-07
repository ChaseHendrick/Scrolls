# The pipeline: scan, unwrap, ink, papyrologist

Private operational plans, target outputs and submission material belong in [Scrolls-private](https://github.com/ChaseHendrick/Scrolls-private) (access required). This page is public background and general tooling guidance.

The Herculaneum scrolls are **not** an undeciphered script. The language is ancient Greek (mostly Epicurean prose, much of it by Philodemus). The problem is physical: the rolls are carbonized, too brittle to open, and carbon ink has almost the same X-ray density as carbonized papyrus. Background and history: Chase Hendrick's [Undeciphered Texts note on the scrolls](https://github.com/ChaseHendrick/Undeciphered-Texts/blob/main/docs/vesuvius-scrolls.md).

Main technical source: the organizers' [2026 open problems](https://scrollprize.org/2026_open_problems) post ([source](https://github.com/ScrollPrize/villa/blob/main/scrollprize.org/docs/37_2026_open_problems.md)), checked 2026-10-06.

## 1. Scanning

Micro-CT, now mostly phase-contrast synchrotron scans (ESRF BM18). The output is a 3D volume of the carbonized mass, stored as OME-Zarr in a public S3 bucket. Common working resolutions are about 9.4 µm and 8.6 µm per voxel; some scrolls also have 2.4 µm and 1.1 µm scans. Higher resolution helps but does not by itself separate sheets in compressed regions.

## 2. Unwrapping (segmentation)

Find the rolled papyrus sheet and flatten it. CT gives voxels, not sheets, so this is several steps:

| Step | What it does | Main tool |
| --- | --- | --- |
| Surface prediction | A 3D network marks voxels on the papyrus recto | nnU-Net models, e.g. [`surface_m7_nnunet`](https://huggingface.co/scrollprize/surface_m7_nnunet) |
| Meshing / tracing | Builds an explicit surface with connectivity ("this point is next to that one on the same sheet") | VC3D GrowPatch, [lasagna](https://github.com/ScrollPrize/villa/tree/main/lasagna), community [ScrollFiesta](https://github.com/Hob3rMallow/scrollfiesta_public) |
| Global prior | Fits one spiral to the whole scroll from traced patches, fibers and winding annotations | [spiral fitting](https://github.com/ScrollPrize/villa/tree/main/spiral-fitting) |
| Flattening | 2D parameterization with low distortion | VC3D, lasagna |
| Rendering | Samples a stack of layers around the surface (28 in the current tutorial) into a "surface volume" | `vc_render_tifxyz` |

The common failures are named by the organizers: **mergers** (two sheets joined), **holes**, **sheet switches** (the mesh jumps to a neighboring wrap), **compressed regions**, and **damaged regions**. A sheet switch silently ruins everything downstream: ink detection on a surface that crosses sheets sees noise.

## 3. Ink detection

A model predicts, per pixel of the flattened surface, whether there is ink. Training labels come from fragments photographed in infrared and aligned to CT, from scroll regions where ink is visible, and from pseudo-labeling (train, predict, keep confident ink, retrain).

- Released cross-scroll models: [`scrollprize/ink_9um`](https://huggingface.co/scrollprize/ink_9um), a small 3D stem feeding a 2D U-Net, trained on PHerc. 0139, 1667, Paris 4 and 0814 at about 9 µm. Two seeds, seven checkpoints each.
- The models operate on pixels, not letters. They know nothing of the Greek alphabet. That limits, but does not remove, hallucination: large receptive fields can invent plausible strokes, which is why the prizes demand false-positive mitigation and held-out validation.
- Predictions sit in a compressed range (training targets were 0.25 and 0.75 with label smoothing); rescale for display.
- The models are sensitive to depth offset. A surface rendered a little too deep or shallow can show nothing.

Organizers' recipe: [ink detection tutorial](https://scrollprize.org/tutorial5).

## 4. Papyrology

Papyrologists read the images. A heatmap is not a transcription. The prizes are judged on whether the papyrology team can read letters, letter by letter, without interpolation.

## Bottlenecks (organizers' table, condensed)

| Bottleneck | What would help |
| --- | --- |
| Compressed or highly curved regions | Scan-quality metrics, scroll-specific scan recipes |
| No built-in connectivity in CT | Better geometry priors, fiber tracing, topology-aware tools |
| Approximate surface labels | Label snapping, active learning, self-supervised methods |
| Sheet switches | Tracers that avoid them |
| Ink depth ambiguity | Direct 3D ink segmentation where possible |
| Cross-scroll generalization | Multi-scroll training, better labels, stronger diagnostics |
| Data scale | Reproducible streaming pipelines, cheaper compute and storage |

## The six places the organizers ask for help

1. Datasets with surface labels better localized on the recto, or models that preserve sheet topology.
2. Alternative, scalable meshing algorithms (geometry processing, optimization, C++).
3. Robust fiber tracing: fewer fibers followed correctly beats more followed badly.
4. Better spiral-fit evaluation and losses, fewer needed annotations, automated winding annotations.
5. Precise labels in hard regions (3D annotation, active learning, data quality).
6. Voxel-level 3D ink segmentation where ink is visible.

Each of these is eligible for Progress Prizes.
