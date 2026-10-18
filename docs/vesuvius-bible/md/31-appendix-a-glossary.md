# Appendix A. Glossary {#app-glossary}

Terms are defined as used in this book. The chapter in brackets gives the fuller treatment.

| Term | Definition |
|---|---|
| 2.5D model | An ink model that takes a 3D patch of a surface volume and outputs a 2D ink image, typically by projecting along depth ([21](#ch-ink)). |
| 3D U-Net | A U-Net with 3D convolutions, used for voxelwise surface prediction [Cicek2016] ([17](#ch-surface)). |
| absorption contrast | Image contrast from differences in how strongly materials attenuate X-rays ([7](#ch-xray)). |
| Adam | A stochastic gradient optimizer [Kingma2015], used in spiral fitting ([19](#ch-spiral)). |
| agraphon | An unwritten stretch of a roll, such as the blank start or end [Romano2023] ([4](#ch-papyrus)). |
| alias | A short name for a sample, for example "Scroll 1" for PHerc. Paris 4 ([15](#ch-inventory)). |
| autoresearch | Agent-driven automated search over model architectures and training settings, used by the challenge team from 2026 ([13](#ch-2026)). |
| BM18 | ESRF beamline built for large-object phase-contrast tomography; used for scroll scans from 2025 ([8](#ch-scans)). |
| book number | The number of a book in a multi-book work, written in an end title ([6](#ch-greek)). |
| capitals (bookhand) | The upright Greek letters, without word division, in which literary papyri were written ([6](#ch-greek)). |
| carbonization | Conversion of papyrus to carbon-rich material by heat in the eruption ([1](#ch-eruption), [4](#ch-papyrus)). |
| catalog | The challenge's machine-readable listing of samples, scans, volumes and models ([8](#ch-scans), [23](#ch-formats)). |
| Ceres | An open-source C++ library for non-linear least-squares problems, used by GrowPatch [Ceres] ([18](#ch-tracing)). |
| checkpoint | Saved weights of a trained model ([21](#ch-ink)). |
| column | A block of text on a roll; Herculaneum columns are often 5 to 6 cm wide ([4](#ch-papyrus)). |
| compressed region | Part of a scroll where wraps are pressed so tightly that scans lose layer separation ([8](#ch-scans), [26](#ch-open-problems)). |
| Copy Out/In | A VC3D tracing method that predicts a neighboring wrap's surface from a traced one ([18](#ch-tracing)). |
| crackle | A fine cracked texture of ink seen in scroll CT, the first ink signal found directly in a closed scroll ([10](#ch-2023)). |
| CT | Computed tomography: reconstruction of a 3D volume from many X-ray projections ([7](#ch-xray)). |
| data agreement | The terms users accept for challenge data, including citation and no publication of hidden text without approval ([28](#ch-ethics)). |
| Diamond | Diamond Light Source, the UK synchrotron where Scrolls 1 to 5 were first scanned ([8](#ch-scans)). |
| Dice score | A segmentation overlap metric, twice the intersection over the sum of sizes ([21](#ch-ink)). |
| DINO | Self-distillation without labels, a self-supervised learning method [Caron2021]; the challenge trained a 3D version ([17](#ch-surface)). |
| EduceLab | The University of Kentucky lab led by Brent Seales that pioneered virtual unwrapping ([9](#ch-founding)). |
| EduceLab-Scrolls | The legacy dataset of scans made before 2025 at Diamond ([28](#ch-ethics)). |
| end title (subscriptio) | The title block at the end of a roll's text: author, title, book number, sometimes a line count ([6](#ch-greek)). |
| Epicureanism | The philosophy of Epicurus, which most Herculaneum texts discuss ([2](#ch-villa)). |
| ESRF | European Synchrotron Radiation Facility, Grenoble ([8](#ch-scans)). |
| fiber (fibre) | A strand of the papyrus plant visible in CT; fibers run horizontally on the recto ([4](#ch-papyrus), [18](#ch-tracing)). |
| First Letters prize | A prize for the first letters found in a given scroll ([13](#ch-2026)). |
| flattening | Mapping a traced 3D surface onto a plane with low distortion ([20](#ch-flatten)). |
| flatboi | A community flattening tool based on SLIM ([20](#ch-flatten)). |
| fragment | A detached piece of papyrus, often with visible ink, used for ground truth ([15](#ch-inventory)). |
| Grand Prize | The main prize of a challenge year: $700,000 in 2023, $1 million for 2027 ([10](#ch-2023), [13](#ch-2026)). |
| GrowPatch | A VC3D surface-growing tracer that extends a mesh by optimization ([18](#ch-tracing)). |
| haze (decohesion) | Blur in phase-contrast scans of compressed papyrus caused by beam scattering ([8](#ch-scans)). |
| Hecate | An ink model by Giorgio Angelotti, used in the PHerc. 343 First Letters result; given a single-pass speed-up in 2026 ([21](#ch-ink)). |
| hallucination | A model producing letterforms not supported by the data ([28](#ch-ethics)). |
| I12 | Diamond beamline used for the 2019 and 2023 scans ([8](#ch-scans)). |
| ID11 | ESRF beamline used for 0.55 µm scans of a fragment region ([8](#ch-scans)). |
| ink detection | Predicting where ink lies on a rendered surface from CT data ([21](#ch-ink)). |
| ink_9um | The challenge's cross-scroll ink models at about 9 µm ([21](#ch-ink)). |
| Kaggle | The data-science platform that hosted the 2023 ink and 2025 to 2026 surface competitions ([10](#ch-2023), [12](#ch-2025)). |
| keV | Kiloelectronvolt, the unit of X-ray photon energy ([7](#ch-xray)). |
| kollema (kollesis) | A sheet in a roll, and the join between sheets ([4](#ch-papyrus)). |
| label smoothing | Training with softened targets; with 0.5, ink is 0.75 and background 0.25 ([21](#ch-ink)). |
| Lasagna | An optimization tool for one or more sheets using normals and gradients ([18](#ch-tracing)). |
| layer, sheet, wrap, winding | Used interchangeably for one turn of papyrus around the roll [VC-OpenProblems2026]. |
| Leiden conventions | Signs for marking damaged or restored text in editions ([6](#ch-greek)). |
| lunate sigma | The crescent-shaped form of sigma, Ϲ ([6](#ch-greek)). |
| mesh | A connected surface of vertices and faces ([18](#ch-tracing)). |
| milestone prize | A prize for a defined result, as opposed to a monthly progress prize ([14](#ch-ledger)). |
| nnU-Net | A self-configuring U-Net framework [Isensee2021] ([17](#ch-surface)). |
| normal | A vector perpendicular to a surface; a normal grid is a 3D field of normals ([18](#ch-tracing)). |
| OME-Zarr | A chunked, multi-resolution array format for large images [Moore2021] ([23](#ch-formats)). |
| Officina dei Papiri | The workshop and archive of the Herculaneum papyri in the National Library, Naples ([2](#ch-villa)). |
| PHerc. | Abbreviation for Papyrus Herculanensis, followed by an inventory number ([15](#ch-inventory)). |
| phase contrast | Contrast from the phase shift of X-rays, revealed by propagation to the detector ([7](#ch-xray)). |
| phase retrieval | Computing the phase signal from phase-contrast images, for example by the Paganin method ([7](#ch-xray)). |
| Piaggio machine | The 18th-century unrolling device of Antonio Piaggio ([3](#ch-unrolling)). |
| progress prize | Monthly prize for open-source contributions ([14](#ch-ledger)). |
| propagation distance | Distance from sample to detector; controls phase contrast ([7](#ch-xray)). |
| pseudo-labeling | Training on labels produced by a model's own confident predictions, iteratively ([21](#ch-ink)). |
| recto | The written inner side of a roll, with horizontal fibers ([4](#ch-papyrus)). |
| rendering | Sampling the volume along a traced surface into a stack of layers ([20](#ch-flatten)). |
| ResNet3D | A 3D residual network [Hara2018], used in early ink models ([21](#ch-ink)). |
| scorza | The hard outer shell of a carbonized roll, removed in early opening ([3](#ch-unrolling)). |
| ScrollFiesta | A community meshing pipeline ([18](#ch-tracing)). |
| segment | A traced piece of surface with its rendered volume ([16](#ch-pipeline)). |
| segmentation | The process of tracing the papyrus surface in a volume ([16](#ch-pipeline)). |
| sheet switch | A tracing error in which a mesh jumps from one wrap to another ([18](#ch-tracing)). |
| SLIM | Scalable Locally Injective Mappings, a flattening algorithm [Rabinovich2017] ([20](#ch-flatten)). |
| spiral fitting | Fitting one deformed spiral to a whole scroll ([19](#ch-spiral)). |
| stichometry | Counting lines of a book ([6](#ch-greek)). |
| supervision mask | The region where training labels are trusted ([21](#ch-ink)). |
| surface prediction | Voxelwise prediction of where the recto surface is ([17](#ch-surface)). |
| surface volume | A stack of images rendered at depths around a traced surface ([20](#ch-flatten)). |
| synchrotron | A particle accelerator that produces intense, coherent X-rays ([7](#ch-xray)). |
| tifxyz | A surface format of three float32 TIFFs giving x, y, z for each grid cell, with -1 for missing cells ([23](#ch-formats)). |
| TimeSformer | A video transformer [Bertasius2021], used in the 2023 Grand Prize ink model ([21](#ch-ink)). |
| topology-aware metric | A score that penalizes holes, mergers and sheet switches ([17](#ch-surface)). |
| umbilicus | The central axis of a roll; in the data, the fitted center line ([19](#ch-spiral)). |
| uint8 | 8-bit unsigned integer; the data type of catalog volumes ([23](#ch-formats)). |
| VC3D | Volume Cartographer 3D, the main viewing and tracing application ([18](#ch-tracing), [22](#ch-tools)). |
| verso | The outer back side of a roll, with vertical fibers ([4](#ch-papyrus)). |
| villa (repository) | The ScrollPrize monorepository containing VC3D, vesuvius and other tools ([22](#ch-tools)). |
| Villa of the Papyri | The Herculaneum villa where the rolls were found ([2](#ch-villa)). |
| virtual unwrapping | Recovering a rolled surface's content from 3D imaging without opening it ([3](#ch-unrolling)). |
| volume | A reconstructed 3D CT image ([8](#ch-scans)). |
| voxel | A volume element; the voxel size is its edge length in micrometers ([7](#ch-xray)). |
| winding number | The count of turns from the center of a spiral; relative winding annotations constrain spiral fits ([19](#ch-spiral)). |
