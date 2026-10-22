<a id="ch-pipeline"></a>

# The Pipeline at a Glance {#ch-pipeline}

> **Chapter summary.** Reading a closed scroll is a chain: scan, predict surfaces, build meshes, fit them into a consistent whole, flatten, render surface volumes, detect ink, and have papyrologists read the result. The CT scan gives "a 3D grid of voxels" and nothing else; every later stage adds structure that the data do not contain explicitly. This chapter maps the chain, its file formats and its failure modes, and points to the chapters that cover each stage.

## The core difficulty

The Vesuvius Challenge open-problems document puts the starting point plainly: "We do not get sheets. We do not get a mesh, a graph, or a map of which layer connects to which. We get a 3D grid of voxels." A voxel is "a tiny cube with an intensity value", and "the scan gives us billions or trillions of these cubes" [VC-OpenProblems2026]. The volume "does not tell us where one wrap ... ends and another begins" [VC-OpenProblems2026]. The words wrap, winding, sheet and layer are used "more or less interchangeably" for "one continuous turn of the papyrus as it spirals from the outside of the roll toward the center" [VC-OpenProblems2026].

The challenge summarizes the pipeline as Scanning, Unwrapping, Flattening and Ink Detection, three "complex problems": producing a volume that preserves the signal, inferring and flattening the sheets, and recovering ink on or near the surface [VC-OpenProblems2026].

![Flow diagram of the pipeline from CT scan through surface prediction, meshing and tracing, spiral fit, flattening, rendering of surface volumes, ink detection and papyrological review, with data formats on the arrows.](../figures/charts/pipeline_flow.svg)
*Figure 16.1. The virtual unwrapping pipeline as of October 2026, with the main file formats passed between stages. Diagram by the editors from [VC-OpenProblems2026], [VC-SpiralTutorial] and [VC-InkTutorial]. License: CC BY 4.0 (this book).*

## Stages

| Stage | Input | Output | Main tools (Oct 2026) | Chapter |
|---|---|---|---|---|
| 1. Scanning and reconstruction | the scroll | CT volume (OME-Zarr) | synchrotron beamlines, phase retrieval | [7](07-xray.md#ch-xray), [8](08-scans.md#ch-scans) |
| 2. Surface prediction | CT volume | voxelwise recto-surface probability; normals; winding-density fields | 3D U-Net, nnU-Net (surface_recto_3dunet, surface_m7_nnunet) | [17](17-surface.md#ch-surface) |
| 3. Meshing and tracing | surface predictions | patches as tifxyz quad meshes | VC3D GrowPatch, Copy Out/In, Neural Tracer, Lasagna, ScrollFiesta, fiber tracing | [18](18-tracing.md#ch-tracing) |
| 4. Global fit | patches, fibers, winding annotations, umbilicus | one tifxyz mesh per winding | spiral fitter (fit_spiral.py) | [19](19-spiral.md#ch-spiral) |
| 5. Flattening | 3D mesh | 2D parameterization | flatboi (SLIM) | [20](20-flatten.md#ch-flatten) |
| 6. Rendering | mesh plus volume | surface volume (layers along the normal) | vc_render_tifxyz | [20](20-flatten.md#ch-flatten) |
| 7. Ink detection | surface volume, or the raw volume in 3D modes | ink probability image | 2.5D models (TimeSformer era, hybrid 3D to 2D ink_9um, reader-v2, Hecate), native 3D models | [21](21-ink.md#ch-ink) |
| 8. Reading | ink images | transcription | papyrologists | [6](06-greek.md#ch-greek) |

Sources: [VC-OpenProblems2026] [VC-SpiralTutorial] [VC-InkTutorial] [VC-Winners].

## Failure modes

The open-problems document lists the errors that decide "whether a flattened rendering shows a coherent writing surface or a corrupted one" [VC-OpenProblems2026]:

- **mergers**, where two nearby sheets are joined by mistake;
- **holes**, where the predicted surface disappears;
- **sheet switches**, where a mesh jumps from the intended sheet to a neighboring wrap;
- **compressed regions**, where the image gives weak or ambiguous evidence;
- **damaged regions**, where the papyrus is torn, folded or missing.

The same document gives a bottleneck table [VC-OpenProblems2026]:

| Bottleneck | Current approach | What would help |
|---|---|---|
| Compressed or highly curved regions | better scan regimes, smaller voxels, shorter propagation distance, phase retrieval | scan-quality metrics, scroll-specific acquisition recipes |
| No built-in connectivity | surface prediction plus mesh tracing | geometry priors, fiber tracing, topology-aware tools |
| Approximate surface labels | train 3D surface models from approximate annotations | label snapping, active learning, self-supervised methods |
| Sheet switches | VC3D inspection and manual correction | tracing algorithms that avoid them |
| Ink depth ambiguity | surface-conditioned 3D input with 2D output | direct 3D ink segmentation |
| Cross-scroll generalization | fragment training plus scroll-specific pseudo-labeling | multi-scroll training, better labels, diagnostics |
| Data scale | OME-Zarr, chunked processing, cloud storage | reproducible streaming pipelines, cheaper compute |

## How the pipeline changed, 2023 to 2026

| Period | Surface | Ink | Human effort |
|---|---|---|---|
| 2023 | manual tracing in Volume Cartographer slice by slice; ThaumatoAnakalyptor autosegmentation at the end | Kaggle fragment models, crackle-trained models, TimeSformer | "hundreds of hours" for the Grand Prize region [VC-FASP] |
| 2024 | volumetric surface prediction; patch growing and stitching; first spiral fit | same lineage, 3D ink experiments | four hours for the FASP region (Schilling and Johnson) [VC-FASP] |
| 2025 | VC3D semi-automated tracing; Kaggle surface competition launched | generalist fragment-trained model; 2.4 µm scans | VC3D "more than 10x faster" than manual work by January 2026 [VC-PHerc172Seventy] |
| 2026 | nnU-Net surfaces; Lasagna; Neural Tracer; spiral fit as main whole-scroll method; ScrollFiesta | iterative pseudo-labeling; ink_9um cross-scroll models; reader-v2; direct 3D ink in PHerc. Paris 4 | Grand Prize rule: at most 8 documented hours [VC-Prizes] |

The August 2026 workflow post recommends a route for newcomers: "choose an eligible scroll, inspect it in VC3D, recover a papyrus surface, flatten and render a surface volume, run ink detection, inspect, iterate, and search", while noting that "it is not the only way to win" [VC-Workflow2026].
