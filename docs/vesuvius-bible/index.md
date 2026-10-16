# The Vesuvius Challenge Bible: index

Edited reference on the Herculaneum papyri and the Vesuvius Challenge, dated 15 October 2026. 39 Markdown files, 59,959 words. Every fact is cited inline with a [Key] that resolves in Appendix G (`md/37-appendix-g-bibliography.md`, machine-readable in `data/bibliography.json`). Unverified statements are marked in italics.

Files: `bible.md` is all chapters in one file; `md/` has one file per chapter; `data/` holds the source CSV or JSON of every chart; `figures/charts/` holds the charts as SVG.

## Chapters

| File | Title | Words | Summary |
|---|---|---|---|
| [00-preface.md](md/00-preface.md) | About This Book | 503 |  |
| [01-eruption.md](md/01-eruption.md) | The Eruption of 79 CE | 1,655 | Mount Vesuvius buried the towns around the Bay of Naples in a two-phase eruption in 79 CE. Herculaneum, upwind of the first ash fall, was overwhelmed by pyroclastic surges that carbonized organic material, including a library of papyrus rolls, and sealed it under roughly 20 metres of volcanic deposi |
| [02-villa.md](md/02-villa.md) | The Villa of the Papyri and its Library | 1,991 | The Villa of the Papyri, on the coast just outside Herculaneum, held the only library from the Graeco-Roman world that survives as a physical collection. Tunnellers working for the Bourbon kings of Naples found its carbonized rolls between 1752 and 1754. The library is dominated by Epicurean philoso |
| [03-unrolling.md](md/03-unrolling.md) | Two and a Half Centuries of Unrolling | 2,029 | From 1752 to the end of the twentieth century every attempt to read a Herculaneum roll involved opening it physically, and every method destroyed part of what it revealed. Slicing, Antonio Piaggio's thread machine (1756), chemical treatments, the Oslo peeling method and multispectral photography eac |
| [04-papyrus.md](md/04-papyrus.md) | Papyrus: from Plant to Roll | 2,827 | Papyrus is made from the pith of the sedge *Cyperus papyrus*, cut into strips, laid in two layers at right angles, pressed and dried. Sheets were glued edge to edge into rolls. Carbonization at Herculaneum shrank each sheet to about 0.15 mm, and the fibre structure that survives is the main thing th |
| [05-inks.md](md/05-inks.md) | Inks and Writing | 1,693 | Herculaneum scribes wrote with a reed pen in a carbon-based ink that is chemically almost identical to carbonized papyrus, which is why the ink is so hard to see in X-ray CT. Some Herculaneum ink contains lead, at tens of micrograms per square centimetre. Published estimates of ink thickness range f |
| [06-greek.md](md/06-greek.md) | Greek and Papyrology Basics | 2,130 | The Herculaneum papyri are mostly written in Greek capitals in narrow columns, without word division. This chapter gives the minimum that a technical contributor needs to recognize what an ink model is showing: the alphabet and its letterforms on papyrus, the layout of a roll, numerals, the conventi |
| [07-xray.md](md/07-xray.md) | X-ray Tomography for Carbonized Papyrus | 1,923 | A CT scan does not deliver sheets or text; it delivers a three-dimensional grid of voxels, each holding an intensity. For carbonized papyrus with carbon ink, absorption contrast is weak, so the method depends on phase contrast, on resolution and on careful choice of three coupled parameters: voxel s |
| [08-scans.md](md/08-scans.md) | Synchrotrons and Scan Campaigns | 1,753 | The Herculaneum scrolls have been scanned at two synchrotrons: the Diamond Light Source in Oxfordshire (beamline I12, from 2019 to 2025) and the European Synchrotron (ESRF) in Grenoble (beamlines BM18 and ID11, from 2025). The public open-data catalogue lists 67 scans of 45 samples. This chapter des |
| [09-founding.md](md/09-founding.md) | Founding the Vesuvius Challenge | 1,187 | The Vesuvius Challenge was launched on 15 March 2023 by Nat Friedman, Daniel Gross and Brent Seales, with CT data from EduceLab, a Kaggle ink-detection competition and a grand prize for reading text inside a closed scroll. A week after launch the prize pool reached one million dollars. The challenge |
| [10-2023.md](md/10-2023.md) | The 2023 Season: First Letters and the Grand Prize | 1,493 | In 2023 the community built segmentation tools, won a $100,000 Kaggle ink-detection competition on fragments, discovered the "crackle" texture of ink in the scrolls, read the first word (ΠΟΡΦΥΡΑϹ, "purple") in October, and in December produced more than 15 columns of Epicurean philosophy from Scroll |
| [11-2024.md](md/11-2024.md) | 2024: From Five Percent to Autosegmentation | 1,197 | In 2024 the challenge set a goal of reading 90 percent of four scrolls, launched more than $500,000 in prizes including monthly progress prizes, released the second halves of Scrolls 1 and 2 and a new scroll (PHerc. 172), and pushed segmentation from manual tracing toward automation. The Grand Prize |
| [12-2025.md](md/12-2025.md) | 2025: Titles, Scanning at Scale and Better Scans | 1,255 | 2025 brought the first title recovered from a still-rolled Herculaneum scroll (PHerc. 172, *Philodemus, On Vices, Book 1(?)*), a production scanning session of twenty scrolls, the move to phase-contrast tomography at the ESRF, an explanation of the "compressed region" haze, a column of PHerc. 172 qu |
| [13-2026.md](md/13-2026.md) | 2026: A Scroll Read in Full | 1,806 | In 2026 the challenge unwrapped about 70 percent of PHerc. 172, ran agent-driven "autoresearch" and a 3D foundation model, closed the $200,000 Kaggle surface-detection competition, and on 25 June 2026 announced the first complete virtual unwrapping and reading of a Herculaneum scroll, PHerc. 1667, a |
| [14-ledger.md](md/14-ledger.md) | The Prize Ledger | 1,313 | The public winners list records 233 individual awards totalling **$1,958,500** in 34 rounds from April 2023 to October 2026. The 2023 Grand Prize ($850,000 including runners-up) accounts for 43 percent of the money; 202 progress and open-source awards account for $578,500. This chapter tabulates the |
| [15-inventory.md](md/15-inventory.md) | Inventory of Scrolls and Fragments | 2,532 | The open-data catalogue (retrieved 15 October 2026) lists 45 samples: 35 scrolls and 10 fragments. This chapter tabulates every sample with data, its aliases, scans, voxel sizes, energies and facilities, then gives a short profile of each sample that has a documented history or result. Counts of seg |
| [16-pipeline.md](md/16-pipeline.md) | The Pipeline at a Glance | 926 | Reading a closed scroll is a chain: scan, predict surfaces, build meshes, fit them into a consistent whole, flatten, render surface volumes, detect ink, and have papyrologists read the result. The CT scan gives "a 3D grid of voxels" and nothing else; every later stage adds structure that the data do |
| [17-surface.md](md/17-surface.md) | Surface Prediction | 882 | Surface prediction labels each voxel as papyrus recto surface or background, producing the cue that meshing follows. The standard architecture is a 3D U-Net, and since the 2025 to 2026 Kaggle competition, nnU-Net ensembles trained for very long schedules. Predictions are not final geometry: holes, m |
| [18-tracing.md](md/18-tracing.md) | Meshing and Surface Tracing | 1,421 | Meshing turns surface predictions into explicit surfaces with connectivity. The lineage runs from manual slice-by-slice tracing in Volume Cartographer (2023), through Khartes, ThaumatoAnakalyptor and patch stitching (2023 to 2024), to the 2026 toolset in VC3D: GrowPatch, Copy Out/In, the Neural Trac |
| [19-spiral.md](md/19-spiral.md) | The Spiral Fit | 1,136 | The spiral fit is the main whole-scroll method in 2026. It models the scroll as an ideal Archimedean spiral deformed by a smooth, invertible map (a diffeomorphism), and fits that map to all available evidence: verified patches, fibers, winding annotations, predicted normals and the umbilicus. Its ou |
| [20-flatten.md](md/20-flatten.md) | Flattening and Rendering | 654 | Flattening assigns each mesh point a 2D coordinate with as little distortion as possible; VC3D's production tool, flatboi, uses SLIM to minimize the symmetric Dirichlet energy. Rendering then samples the CT volume along the mesh and its normals to produce a **surface volume**, a stack of flat images |
| [21-ink.md](md/21-ink.md) | Ink Detection | 1,694 | Ink detection is "signal recovery, not reading": a model looks at a small patch of a surface volume and predicts, per pixel, the probability of ink. Labels began with fragments photographed in infrared, grew through crackle annotation and the 2023 TimeSformer models, and now come from conservative i |
| [22-tools.md](md/22-tools.md) | Tools and Repositories | 1,013 | Most current code lives in the ScrollPrize/villa monorepository on GitHub: VC3D (Volume Cartographer 3D), the `vesuvius` Python package with the ink-detection pipeline, spiral fitting, Lasagna, neural tracing and dinovol. Data are in an AWS open-data bucket, curated datasets and model checkpoints on |
| [23-formats.md](md/23-formats.md) | Data Formats | 884 | Volumes are distributed as chunked, multiresolution OME-Zarr; surfaces as tifxyz quad meshes (three float32 TIFFs of x, y and z plus metadata) or OBJ; surface volumes as Zarr or TIFF stacks; labels as binary images; metadata as JSON. The bucket is organized by sample, then volumes, segments and repr |
| [24-community.md](md/24-community.md) | Community and People | 1,321 | The Vesuvius Challenge is a hybrid of open competition and in-house work: a Discord community, open-source progress prizes, a paid segmentation (annotation) team from 2023, an in-house research team from 2025, a papyrology team, and partners at libraries and synchrotrons. The organizers credit five  |
| [25-compute.md](md/25-compute.md) | Compute, Storage and Costs | 1,272 | The economics of reading a scroll are dominated by human time for unwrapping, then by data volume. In 2023 manual segmentation cost "more than $100 per square centimeter"; in 2025 the master plan put a whole scroll at $1 to 5 million with current techniques and set a target of $5,000 or less. The pu |
| [26-open-problems.md](md/26-open-problems.md) | Open Problems | 1,399 | By October 2026 a sealed Herculaneum scroll has been unwrapped and read, but "not without a person checking its output at almost every stage" [VC-OpenProblems2026]. This chapter restates, from the challenge's own open-problems document (last updated 14 October 2026), what is unsolved at each stage,  |
| [27-howto.md](md/27-howto.md) | How-Tos | 1,283 | Step-by-step recipes adapted from the official tutorials as of October 2026: getting the code, viewing a scroll and growing a segment in VC3D, rendering a segment, training and running an ink model, searching an unread scroll for first letters with the shared 9 µm models, and fitting the spiral. Com |
| [28-ethics.md](md/28-ethics.md) | Data, Licences and Responsible Practice | 850 | Challenge data is released under CC BY-NC 4.0 unless noted, and the legacy EduceLab-Scrolls scans are copyrighted by EduceLab and the University of Kentucky. Users agree to cite the dataset and not to publish "any revelation of hidden text" without written approval. Prize rules add open-source, open |
| [29-timeline.md](md/29-timeline.md) | Timeline | 810 | A single chronology from the eruption to the 2027 prize deadline, compiled from the chapters of this book. Each row cites its source; the machine-readable version is data/timeline.csv. Dates of Substack-announced events are the dates of the announcing post unless the chapter gives another date. |
| [30-faq.md](md/30-faq.md) | Frequently Asked Questions | 850 | Short answers to common questions, each pointing to the chapter that gives the evidence. Answers repeat facts sourced elsewhere in the book; follow the chapter link for citations. |
| [31-appendix-a-glossary.md](md/31-appendix-a-glossary.md) | Appendix A. Glossary | 1,544 |  |
| [32-appendix-b-ledger.md](md/32-appendix-b-ledger.md) | Appendix B. Prize Ledger | 3,048 |  |
| [33-appendix-c-scans.md](md/33-appendix-c-scans.md) | Appendix C. Scans and Volumes | 2,690 |  |
| [34-appendix-d-models.md](md/34-appendix-d-models.md) | Appendix D. Models in the Catalogue | 280 |  |
| [35-appendix-e-substack.md](md/35-appendix-e-substack.md) | Appendix E. Newsletter Index | 901 |  |
| [36-appendix-f-images.md](md/36-appendix-f-images.md) | Appendix F. Image Credits | 1,059 |  |
| [37-appendix-g-bibliography.md](md/37-appendix-g-bibliography.md) | Appendix G. Bibliography | 2,545 |  |
| [39-index-terms.md](md/39-index-terms.md) | Index | 4,210 |  |

## Data

- [`data/award_sizes.csv`](data/award_sizes.csv)
- [`data/bibliography.json`](data/bibliography.json)
- [`data/catalog_models.csv`](data/catalog_models.csv)
- [`data/catalog_samples.csv`](data/catalog_samples.csv)
- [`data/catalog_scans.csv`](data/catalog_scans.csv)
- [`data/catalog_volumes.csv`](data/catalog_volumes.csv)
- [`data/community_indicators.csv`](data/community_indicators.csv)
- [`data/compute_costs.csv`](data/compute_costs.csv)
- [`data/feature_scales.csv`](data/feature_scales.csv)
- [`data/ink_thickness.csv`](data/ink_thickness.csv)
- [`data/prize_awards.csv`](data/prize_awards.csv)
- [`data/prize_categories.csv`](data/prize_categories.csv)
- [`data/prize_rounds.csv`](data/prize_rounds.csv)
- [`data/scroll_inventory.csv`](data/scroll_inventory.csv)
- [`data/storage_by_voxel.csv`](data/storage_by_voxel.csv)
- [`data/timeline.csv`](data/timeline.csv)
- [`data/topography_dice.csv`](data/topography_dice.csv)
- [`data/voxel_scaling.csv`](data/voxel_scaling.csv)

## Charts (SVG)

- `figures/charts/award_sizes.svg`
- `figures/charts/community_growth.svg`
- `figures/charts/compute_costs.svg`
- `figures/charts/feature_scales.svg`
- `figures/charts/ink_model_diagram.svg`
- `figures/charts/ink_thickness.svg`
- `figures/charts/inventory.svg`
- `figures/charts/phase_contrast_diagram.svg`
- `figures/charts/pipeline_flow.svg`
- `figures/charts/prize_categories.svg`
- `figures/charts/prizes_over_time.svg`
- `figures/charts/scans_energy_voxel.svg`
- `figures/charts/scans_timeline.svg`
- `figures/charts/spiral_diagram.svg`
- `figures/charts/storage_by_voxel.svg`
- `figures/charts/timeline.svg`
- `figures/charts/topography_dice.svg`
- `figures/charts/voxel_scaling.svg`
