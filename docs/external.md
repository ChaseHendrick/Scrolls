# External tools, data and repositories

Pointers only; nothing here is vendored. Checked 2026-10-06.

## ScrollPrize organization ([github.com/ScrollPrize](https://github.com/ScrollPrize))

| Repository | What it is | Status |
| --- | --- | --- |
| [villa](https://github.com/ScrollPrize/villa) | The monorepo: `vesuvius` library, VC3D, lasagna, spiral fitting, ink detection, website | Active, the one to use |
| [dinovol](https://github.com/ScrollPrize/dinovol) | 3D DINOv2-style pretraining for larger-than-memory OME-Zarr | Active |
| [vc-delta3d](https://github.com/ScrollPrize/vc-delta3d) | C++ (no description) | Active |
| [vc3d-deps](https://github.com/ScrollPrize/vc3d-deps) | Prebuilt containers with VC3D dependencies | Active |
| [vesuvius-gui](https://github.com/ScrollPrize/vesuvius-gui) | Rust GUI for browsing project data | Active |
| [open-data](https://github.com/ScrollPrize/open-data), [open-data-registry](https://github.com/ScrollPrize/open-data-registry) | AWS Open Data documentation and registry entry | Reference |
| [scroll2zarr](https://github.com/ScrollPrize/scroll2zarr) | TIFF to Zarr conversion | Older |
| [volume-cartographer](https://github.com/ScrollPrize/volume-cartographer) | Original toolkit; VC3D now lives in villa | Older |
| scrollrenderer, vesuvius, vesuvius-c, awesome-scroll-tools, scrollprize-website | Archived, moved into villa | Archived |

## Data and models

| Resource | URL |
| --- | --- |
| Data browser | https://scrollprize.org/data_browser |
| S3 bucket (anonymous) | https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/index.html |
| Curated ink and spiral datasets | https://huggingface.co/buckets/scrollprize/datasets |
| Model checkpoints | https://huggingface.co/scrollprize |
| Data docs | https://scrollprize.org/data, https://scrollprize.org/data_datasets |

## Tutorials (current)

- [VC3D](https://scrollprize.org/tutorial_VC3D): install, load data, navigate, annotate, grow segments.
- [Spiral fitting](https://scrollprize.org/tutorial_spiral) and [winding annotations](https://scrollprize.org/open_problems/winding_annotations).
- [Ink detection](https://scrollprize.org/tutorial5): training, inference, 9 µm cross-scroll models, iterative labeling.
- Colab notebooks: [data access](https://colab.research.google.com/github/ScrollPrize/villa/blob/main/vesuvius/src/vesuvius/examples/notebooks/example1_data_access.ipynb), [ink detection](https://colab.research.google.com/github/ScrollPrize/villa/blob/main/vesuvius/src/vesuvius/examples/notebooks/example2_ink_detection.ipynb), [instance cubes](https://colab.research.google.com/github/ScrollPrize/villa/blob/main/vesuvius/src/vesuvius/examples/notebooks/example3_cubes_bootstrap.ipynb).

## Community tools worth knowing

Full list: [Awesome Scroll Tools](https://scrollprize.org/community_projects) ([source](https://github.com/ScrollPrize/villa/blob/main/scrollprize.org/docs/20_community_projects.md)).

| Tool | Use |
| --- | --- |
| [vesuvius-catalog](https://github.com/Schurkai/vesuvius-catalog) (`vcat`) | Which scrolls have segments, ink outputs, surface predictions; data URLs; opening OME-Zarr v2 with zarr 3 |
| [scroll-data-audit](https://github.com/Bullo27/scroll-data-audit) | Catalog vs actual Zarr integrity checks |
| [first-letters-survey](https://github.com/Bullo27/first-letters-survey) (`fls.py`) | One command from eligible scroll to 9 µm ink maps on a grown patch |
| [first-light-pherc0211](https://github.com/bnleft/first-light-pherc0211) | Modal pipeline, preregistration, costs, slab-centering diagnostic |
| [vesuvius-first-letters-pherc0800](https://github.com/nerln/vesuvius-first-letters-pherc0800) | Forward vs reverse depth, blinded reading protocol |
| [vesuvius-reports](https://github.com/ShribyrLabs/vesuvius-reports) | Letter-scale benchmark for 9 µm readers; report format that matches villa PRs |
| [first-letters-scan-atlas](https://github.com/claudepro1515/first-letters-scan-atlas) | CPU-only sheet visibility per scan |
| [first-letters-fit-audit](https://github.com/claudepro1515/first-letters-fit-audit) | Model-free check of whether spiral fits sit on sheets |
| [ScrollFiesta](https://github.com/Hob3rMallow/scrollfiesta_public) | Automatic surface mesher (July 2026 $20k progress prize) |
| [vesuvius-browser](https://github.com/jrudolph/vesuvius-browser), [vesuvius-gui](https://github.com/jrudolph/vesuvius-gui) | Browse segments and render volumes |
| [vesuvius-repro](https://github.com/TAUIL-Abd-Elilah/vesuvius-repro) | Reproducibility spot-checks of m7 surface predictions |

Community code is untrusted until you read it. Clone into its own directory and read before running.

## Background reading

- [2026 open problems](https://scrollprize.org/2026_open_problems): the technical map.
- [Complete virtual unwrapping and reading of a rolled Herculaneum papyrus, arXiv:2606.29085](https://arxiv.org/abs/2606.29085).
- [EduceLab-Scrolls, arXiv:2304.02084](https://arxiv.org/abs/2304.02084) and [Parker et al., PLOS One 2019](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0215775): why carbon ink is detectable at all.
- [Youssef Nader's ink detection notes](https://youssefnader.com/2024/02/06/the-ink-detection-journey-of-the-vesuvius-challenge/): what failed in 2023.
- [Undeciphered Texts: Vesuvius scrolls note](https://github.com/ChaseHendrick/Undeciphered-Texts/blob/main/docs/vesuvius-scrolls.md): history and what AI did and did not do.
