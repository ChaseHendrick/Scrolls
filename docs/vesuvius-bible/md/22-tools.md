<a id="ch-tools"></a>

# Tools and Repositories {#ch-tools}

> **Chapter summary.** Most current code lives in the ScrollPrize/villa monorepository on GitHub: VC3D (Volume Cartographer 3D), the `vesuvius` Python package with the ink-detection pipeline, spiral fitting, Lasagna, neural tracing and dinovol. Data are in an AWS open-data bucket, curated datasets and model checkpoints on Hugging Face. A large set of community tools, cataloged in the challenge's "Awesome Scroll Tools" list, covers viewing, segmentation, ink detection and auditing. This chapter is a map, with links, of what exists in October 2026.

## Where things are

| Resource | Location | Content | Source |
|---|---|---|---|
| villa monorepo | github.com/ScrollPrize/villa | VC3D, vesuvius package, ink detection, spiral fitting, lasagna, neural tracing, dinovol, website | [VC-OpenProblems2026] |
| Open data bucket | s3://vesuvius-challenge-open-data/ (browsable at vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/index.html) | volumes, segments, representations, metadata | [VC-Data] [VC-OpenProblems2026] |
| Data Browser | scrollprize.org/data_browser | per-sample pages | [VC-OpenProblems2026] |
| Curated datasets | huggingface.co/buckets/scrollprize/datasets | ink, ink_9um, spiral-input, surface-labels | [VC-OpenProblems2026] [VC-Datasets] |
| Model checkpoints | huggingface.co/scrollprize | surface, fiber, ink, DINO checkpoints | [VC-OpenProblems2026] |
| Legacy data server | dl.ash2txt.org | older volpkg data (Scrolls 1 to 5, Fragments 1 to 6) | [VC-Catalog] |
| Discord | the challenge's server | community, announcements, support | [VC-Data] |
| Substack | scrollprize.substack.com | newsletter (68 posts to 8 October 2026 were consulted for this book) | [VC-Substack] |

## The villa monorepo

| Component | Path or name | Purpose | Chapter |
|---|---|---|---|
| VC3D | volume-cartographer/ | viewer and semi-automated unwrapping (GrowPatch, Copy Out/In, Neural Tracer panel, line annotation, rendering) | [18](18-tracing.md#ch-tracing) |
| Command-line tools | vc_render_tifxyz, vc_gen_normalgrids, vc_grow_seg_from_seed, vc_tifxyz2obj, vc_obj2tifxyz, flatboi | rendering, normals, growth, conversion, flattening | [18](18-tracing.md#ch-tracing), [20](20-flatten.md#ch-flatten) |
| vesuvius | vesuvius/ | Python data access; `vesuvius.ink_detection` training and inference; tifxyz reader | [21](21-ink.md#ch-ink), [23](23-formats.md#ch-formats) |
| Spiral fitting | spiral-fitting/ (fit_spiral.py, render_ink.py, get_ink_metrics.py) | global whole-scroll fit | [19](19-spiral.md#ch-spiral) |
| Lasagna | lasagna/ (atlas.py) | multi-sheet optimization, fiber tracing | [18](18-tracing.md#ch-tracing) |
| Neural tracing | neural_tracing/ (trace_service.py, autoreg_mesh) | learned displacement and mesh autoregression | [18](18-tracing.md#ch-tracing) |
| dinovol | dinovol/ | 3D DINO self-supervised features | [17](17-surface.md#ch-surface) |
| Ink inference | ink-detection/optimized_inference | fast inference for the 2.4 µm model | [21](21-ink.md#ch-ink) |

Sources: [VC-OpenProblems2026] [VC-SpiralTutorial] [VC-InkTutorial] [VC-VC3DTutorial]. VC3D releases for macOS, Windows and Docker (ghcr.io/scrollprize/villa/volume-cartographer:stable) are published on the villa releases page; Linux users build from source with build_from_src_debian.sh [VC-VC3DTutorial].

Accessing a volume in Python, as first published in 2024 [VC-EasierToLook]:

```python
import vesuvius
import matplotlib.pyplot as plt
scroll = vesuvius.Volume("Scroll1")
img = scroll[1000,:,:]
plt.imshow(img)
```

## Community tools

The challenge maintains an "Awesome Scroll Tools" list of "awarded open source contributions", divided into data access and visualization, segmentation, ink detection and other [VC-CommunityProjects]. A selection:

### Data access and visualization

| Tool | Author | Description |
|---|---|---|
| Segment Browser | Johannes Rudolph | web tool to browse layers and ink results of all released segments |
| vesuvius-gui | Johannes Rudolph | single-binary GUI rendering volumes and segments on the fly |
| vesuvius-phalanx | Marcel Roth | Python library and CLI for volume and fragment data |
| vesuvius-c | Forrest McDonald | C library (now deprecated in favor of `vesuvius` and VC3D) |
| scroll-data-audit | Matteo Bulloni | reconciles metadata.json against actual Zarr arrays; reported a PHerc. 172 catalog shape error |
| vesuvius-repro | TAUIL Abd Elilah | reproducibility spot checks of surface-prediction artifacts across 36 scrolls (Dice 0.9983 to 1.0000) |
| vesuvius-catalog | (listed) | scriptable catalog CLI for the bucket |
| volcomp | Forrest McDonald | chunked compressor for CT and predictions, supported in VC3D |

### Segmentation

| Tool | Author | Description |
|---|---|---|
| Volume Cartographer | EduceLab; fork by Philip Allgaier | "the OG virtual unwrapping toolkit" |
| Khartes | Chuck | manual creation and visualization of segment meshes with a rendered preview |
| ThaumatoAnakalyptor | Julian Schilliger | automatic segmentation combining classical edge detection and deep instance segmentation of point clouds |
| ScrollFiesta | Ben Kyles (HariSeldon) and collaborators | automatic meshing and unwrapping, with parameterization and GPU acceleration (CUDA, HIP/ROCm and CubeCL ports) |
| scrollreading | Will Stevens | flood-fill and patch-based surface extraction |
| windcheck | Josep Carreras | finds where a traced surface passes through itself |
| winding-ruler | Paulo Sergio Camillo | measures winding evidence; a winding-pitch atlas for 36 scrolls |
| vesuvius-automesh | spencerdavis-tx | QC-gated automated surface harvest; 279 cm2 of verified Scroll 3 surface with no manual annotation, CPU only |
| Herculaneum Scroll Tools | axiosdevs | CT-consistency audit of published surface predictions |
| Volumetric Vesuvius Labelling | James Darby | napari tools for volumetric masks |
| Mask3D and synthetic data | Lachlan Parker | instance segmentation network and synthetic pretraining |

### Ink detection

| Tool | Author | Description |
|---|---|---|
| Grand Prize ink model | Youssef Nader, Luke Farritor, Julian Schilliger | the 2023 winning model |
| 3D ink detection | Ryan Chesler | volumetric ink model on full scroll data |
| Inkalyzer | Youssef Nader | explainability package for ink models |
| ScrollMAE; DINO ink experiments | Jorge García | 3D ResNet pretraining; label-free ink detection |
| Vesuvius AutoResearch | mojomast | evidence-gated autonomous experiment search |
| Ink detection validation harness | khj1222 (Hyojun Kwon) | held-out validation masks and k-fold scoring |
| Crackle Viewer | Julian Schilliger | browse and annotate crackle |
| Vesuvius Kintsugi | Giorgio Angelotti | label floodfilled surface volumes |
| Omit | Timo Meireman | classical (non-deep-learning) ink detection |

All rows: [VC-CommunityProjects], with prize details in [VC-Winners].

## Installing a working environment

The tutorials use **uv** throughout: `uv sync --extra models` in villa/vesuvius for ink detection [VC-InkTutorial], `uv sync` in villa/spiral-fitting [VC-SpiralTutorial], and `uvx --from huggingface_hub hf buckets sync ...` to fetch datasets resumably [VC-InkTutorial]. The ink tutorial assumes Linux (Windows users are advised to use WSL2) and an NVIDIA GPU with CUDA [VC-InkTutorial].
