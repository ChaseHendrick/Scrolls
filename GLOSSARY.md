# Glossary

A plain-language list, A to Z, of the technical terms used in this repository's code and documentation. Each definition follows how the term is used here. Where a fuller treatment exists, the entry points to it. The Vesuvius Challenge book in [`docs/vesuvius-bible/`](docs/vesuvius-bible/bible.md#app-glossary) has a longer glossary of the wider field.

Status labels used across the repository (Sourced fact, Community report, Model output, Interpretation, Untested idea) are defined in [`docs/NOVELTY.md`](docs/NOVELTY.md).

## A

**absorption contrast**: Image contrast that comes from how strongly different materials absorb X-rays.

**affine (cross-scan affine)**: A linear transform plus a shift that maps coordinates in one scan of a scroll to coordinates in another scan of the same scroll. The catalogue publishes these, fitted from landmarks; `kit meshaudit transforms` refits them.

**AppImage**: A single-file Linux application package. villa releases VC3D as one; `kit vc3d` can run VC3D through it.

**Apple Silicon**: Apple's own Mac processors (M1 and later). VC3D, rendering and flattening run natively on them; see [`docs/mac.md`](docs/mac.md).

**AUC (pixel AUC)**: Area under the ROC curve. Here it measures how well an ink map ranks labelled ink pixels above labelled non-ink pixels, inside a segment's supervision mask (`kit auc`). 0.5 is chance and 1.0 is perfect. An AUC is reported beside the same reader's reverse-depth map as the control.

**AutoPipeline (AP)**: The repository's automatic pipeline from a released scan to a scored ink map, released as a package on branch `submission/progress-2026-10-fix4` (see the README's "Released tools"). It drives VC3D's command-line tools and villa's ink detection end to end, with a rule written down before the run in place of each choice usually made by eye, and a control beside every check. See [`docs/autopipeline/README.md`](docs/autopipeline/README.md).

## B

**B300**: An NVIDIA data-centre GPU. It is the default GPU for Modal jobs in this repository, falling back to B200, H200 and H100 when none is free.

**benchmark**: A fixed test with a fixed scoring rule, used to compare readers or tools. The numbers live in [`docs/results.json`](docs/results.json).

**BM18**: A beamline at the ESRF built for phase-contrast tomography of large objects; used for scroll scans from 2025.

**bootstrap**: Resampling the data many times to estimate how much a score would vary. `kit auc --bootstrap` gives AUC intervals this way.

**bucket (open-data bucket)**: The Vesuvius Challenge's public Amazon S3 storage, which holds the scans, segments, predictions and labels that kit reads.

## C

**canvas (render canvas)**: The 2D pixel grid onto which a traced surface is rendered. A published surface volume reproduces its canvas from its mesh.

**carbonized**: Turned to carbon-rich material by heat. The Herculaneum scrolls were carbonized in the eruption of Vesuvius in 79 CE.

**catalogue (catalog)**: The challenge's machine-readable list of samples, scans, volumes, segments and models. `kit/vc3d_catalog.py` resolves plans through it.

**checkpoint**: The saved weights of a trained model.

**chunk**: One stored block of a zarr array. Readers fetch only the chunks they need.

**control**: A deliberately wrong or scrambled input run through the same check, so that the check is shown able to fail. Examples here are the reverse-depth map, the depth-shuffled volume, a displaced map and a rotated or IAAFT copy.

**CPU**: The computer's general-purpose processor. Ink inference that runs on the CPU is much slower than on a GPU.

**crop**: A rectangular window cut from a map or volume. Gate A scores fixed crops of densest labelled ink, with a 64 pixel inner edge left out (`--inner 64`).

**CT (computed tomography)**: Building a 3D image of an object from many X-ray projections taken at different angles.

**CTC**: Connectionist temporal classification, a way to train a network to output a sequence (here, letters along a line) without marking where each letter sits. The Greek letter reader uses a CTC line network.

**CUDA**: NVIDIA's GPU programming platform. Most villa training and inference assume an NVIDIA GPU with CUDA.

## D

**d9v2**: A community fine-tune of `ink_9um`, usable as a drop-in `ink_9um` checkpoint.

**depth shuffle**: A control volume in which the layers of a surface volume are put in a random order (`kit shuffle`, `kit layers --shuffle SEED`). Real ink signal should not survive it.

**Dice score**: An overlap measure between two masks: twice the shared area divided by the sum of both areas. A Dice check is reported beside the same map displaced.

**Discord**: The chat service where the Vesuvius Challenge community meets and where most announcements appear first.

## E

**ESRF**: The European Synchrotron Radiation Facility in Grenoble, where scrolls have been scanned since 2025.

**evidence archive**: A frozen folder under `docs/evidence/` with the inputs, rules, scripts, results and SHA-256 hashes of one study. These folders are not edited.

## F

**false 404**: A case where S3 answers "not found" (HTTP 404) for a chunk it actually holds. VC3D then caches the chunk as empty. `kit/s3retry.py` and `kit/s3relay.py` work around it.

**fibre (fiber)**: A strand of the papyrus plant, visible in CT. Fibres run horizontally on the recto.

**fine-tune**: A model made by further training an existing model on new data.

**First Letters prize**: A Vesuvius Challenge prize for the first letters found in a given scroll. Current eligible scrolls are listed by `python -m kit prizes`.

**flattening**: Mapping a traced 3D surface onto a flat plane with as little distortion as possible.

**fp16 (half precision)**: Storing and computing numbers with 16 bits instead of the usual 32 (fp32). It can make GPU inference faster at a small cost in accuracy. `V8IN_FP16=1` turns it on for v8in on MPS, where it is kept only if the crop check still passes and it is faster.

**fragment**: A detached piece of papyrus, often with visible ink, used as ground truth for ink models.

## G

**Gate A**: The repository's rule for ranking two released ink readers (`python -m kit gate`, rule in `kit/gate.py`): a lead of at least 0.02 mean AUC over three PHerc0841 crops, with forward minus reverse AUC at least 0.10 on every crop.

**generalization**: How well a model does on data it was not trained on. Claims of generalization need a held-out labelled segment.

**GPU**: A graphics processor, used here for fast model training and inference.

**Grand Prize**: The largest Vesuvius Challenge prize of a challenge year.

**GrowPatch**: A VC3D tracer that grows a surface mesh outward step by step by optimization.

## H

**held-out**: Data a model never saw in training. A test on held-out data is the only kind that supports a claim about how well a model generalizes. For example, w045 is held out from v8in but not from `ink_9um`, which trained on its 2.4 µm render. Which released reader trained on which labelled segment is tabulated in [`docs/logs/2026-10-16-reader-exposure.md`](docs/logs/2026-10-16-reader-exposure.md).

**Hecate**: An ink model by Giorgio Angelotti, used in the PHerc. 343 First Letters result. Its base model is `scrollprize/ink_canonical_2um`, whose committed trainer lists all three PHerc0841 segments, so PHerc0841 is not held out from Hecate, although Hecate's own published split rule, applied to the published masks, would keep PHerc0841 validation-only ([log](docs/logs/2026-10-16-reader-exposure.md)).

**Herculaneum papyri (Herculaneum scrolls)**: Papyrus rolls from a Roman villa at Herculaneum, carbonized by Vesuvius in 79 CE.

**Hugging Face**: A site that hosts models, datasets and small web apps called Spaces. Several released weights and the Unroll viewer live there.

## I

**IAAFT**: Iterative amplitude-adjusted Fourier transform. It makes a surrogate copy of an image with the same brightness values and nearly the same frequency content but no real structure. StrokeNet reports results against IAAFT copies as a control.

**inference**: Running a trained model on new data to get predictions.

**ink detection**: Predicting where ink lies on a rendered surface from the CT data. The output is an ink map.

**ink label (inklabels)**: A human-drawn mask of where ink is on a segment (`inklabels.zarr`), used for training and scoring.

**ink map (ink probability map)**: A model's per-pixel prediction of ink. It is model output, not a reading; only papyrologists decide what letters an image shows.

**ink_9um**: The Vesuvius Challenge's cross-scroll ink models for scans at about 9 µm.

**intercolumn**: The blank space between two columns of text.

## K

**Kaggle**: A data-science competition platform that has hosted Vesuvius Challenge competitions.

**keV (kiloelectronvolt)**: The unit of X-ray photon energy. Scan names in the bucket give it, for example `113keV`.

**kit**: The repository's Python package (`python -m kit`). It plans and records runs of the official pipeline, scores ink maps, checks results and keeps the experiment ledger. Every subcommand is in `kit/cli.py`; the full list is in [`docs/MAP.md`](docs/MAP.md).

## L

**label smoothing**: Training with softened targets, so ink and background labels are not exactly 1 and 0.

**landmark**: A point marked in two scans of one scroll, used to fit the cross-scan transform between them.

**layer**: One image in a surface volume, at a fixed depth from the traced surface. `kit layers` writes them as numbered TIFF files. In the scroll itself, "layer" also means one turn of papyrus (see winding).

**ledger (experiment ledger)**: The local record of each run in `experiments/<slug>/run.json`, with its readout-rule hash, status, wall time and cost. Modal launches have their own ledger in `docs/compute/modal-ledger.csv`.

**level (resolution level)**: One copy of a volume at a given downsampling in a multi-resolution zarr. Level 0 is full resolution; higher levels are smaller, downsampled copies.

## M

**mask**: An image that marks which pixels or voxels belong to a region, such as papyrus, labelled ink or trusted labels.

**mesh**: A connected surface made of vertices and faces. Traced segments are stored as meshes, usually in tifxyz form.

**micro-CT**: CT at micrometre resolution. The scrolls are imaged this way, now mostly with phase-contrast synchrotron scans.

**micrometre (µm, um)**: One thousandth of a millimetre. Written "um" in file names and some docs.

**Modal**: A cloud computing service that runs jobs on rented GPUs and CPUs, billed by use. In this repository any job that needs a GPU, or more than about an hour of CPU, runs on Modal. Specs are in [`docs/compute/modal-specs/`](docs/compute/modal-specs/README.md) and prices in [`docs/compute/modal-pricing.md`](docs/compute/modal-pricing.md).

**model card**: A short document that describes a released model: its training data, intended use, results and limits.

**MPS**: Metal Performance Shaders, the backend PyTorch uses to run on Apple Silicon GPUs.

## N

**normal**: A direction perpendicular to a surface. A normal grid is a published 3D field of such directions that tracing uses.

**null result**: A run that found no signal. Several teams have published nulls from running the released 9 µm ink models on eligible scrolls.

**NumPy**: The standard Python library for numerical arrays. Several released tools need only NumPy to run.

## O

**OME-Zarr**: A zarr layout for large microscopy-style images, with several resolution levels and metadata. The challenge stores its CT volumes this way.

**open problems**: The Vesuvius Challenge's published list of unsolved tasks ([scrollprize.org/2026_open_problems](https://scrollprize.org/2026_open_problems)).

## P

**papyrologist**: A scholar of ancient papyri. Only the Vesuvius Challenge papyrology team decides whether an image is legible.

**patch**: A small piece. In tracing, a patch is one traced piece of surface that can be merged with others. In ink detection, a patch is the small 3D block of a surface volume that a model reads at one time.

**phase contrast**: Image contrast from the shift in phase of X-rays passing through a sample, made visible by letting the beam travel to the detector.

**PHerc.**: Short for Papyrus Herculanensis, followed by an inventory number, for example PHerc. 0139 or PHerc0139. PHerc. Paris 4 is also called Scroll 1.

**pixel AUC**: See AUC.

**preregistration**: Writing down the readout rule, data and pass bar before any result is seen (`python -m kit run init`, or a committed file in `docs/prereg/`). It stops a rule from being tuned to fit the answer.

**prize eligible**: A scroll that one of the open prizes accepts results on. `python -m kit prizes` lists them from a dated snapshot; [scrollprize.org/prizes](https://scrollprize.org/prizes) wins where they differ. Results on a prize-eligible scroll stay private until the official announcement.

**Progress Prize**: A monthly Vesuvius Challenge prize for open-source contributions such as bug fixes, tools and benchmarks.

**provenance**: The record of who ran what, when, on which machine and from which inputs (`kit/provenance.py`).

**pseudo-label**: A provisional label created from model output and human review. Pseudo-labelling trains a model, keeps its confident predictions as new labels and trains again.

## R

**Reader v2**: A community fine-tune of `ink_9um` by Domenico Russo. It is AutoPipeline's default ink reader.

**recto**: The written inner side of a roll, where the fibres run horizontally.

**render (rendering)**: Sampling the CT volume along a traced surface, and at depths around it, to make a surface volume.

**resolution (voxel size)**: The edge length of one voxel, given in micrometres, for example 9.362 µm, 2.4 µm or about 9 µm. Smaller numbers show finer detail.

**reverse-depth map**: An ink map made from the same surface volume with its layers in reverse order. It is the required control for an ink AUC: real ink signal should depend on the true depth order.

**ROC curve**: A plot of true positive rate against false positive rate over all thresholds. AUC is the area under it.

## S

**S3**: Amazon's object storage service, which hosts the open-data bucket.

**seed (seed point)**: A starting point for tracing a surface. villa's tracer does not hold an explicit seed, so a trace can start on the next winding.

**segment**: A traced piece of papyrus surface together with its rendered surface volume. Segments are named by id, for example w035 or w045 of PHerc0139.

**segmentation (tracing)**: Finding and tracing the rolled papyrus surface inside a CT volume.

**SHA-256**: A hash function. A file's SHA-256 is checked to prove that downloaded weights or evidence are exactly the published ones.

**sheet switch**: A tracing error in which a mesh jumps from one turn of papyrus to another.

**Space (Hugging Face Space)**: A small web app hosted on Hugging Face.

**spiral fit**: Fitting one deformed spiral to the whole rolled papyrus of a scroll.

**stackcheck**: `kit stackcheck`, which checks a stack of consecutive tifxyz segments of one scroll against its umbilicus from geometry alone.

**StrokeNet**: A small learned score in this repository for how much a window of an ink map looks like lines of text (`kit strokenet`), with rotation and IAAFT controls ([model card](docs/strokenet.md)).

**supervision mask (supervision.zarr)**: The region of a segment where its ink labels are trusted. Scores are computed only inside it.

**surface prediction**: A model's voxel-by-voxel prediction of where the papyrus surface is in a CT volume, used to guide tracing.

**surface volume**: A stack of images rendered at depths above and below a traced surface. Ink models read it.

**synchrotron**: A particle accelerator that produces very bright X-rays, used for the scroll scans.

**synthetic data**: Data made by a program, with a known answer, used to test that a tool works before it runs on real scans.

## T

**threshold**: A cut-off value that turns a probability map into a yes or no mask.

**tifxyz**: A surface format of three float32 TIFF images giving the x, y and z position of each grid cell, with -1 for missing cells.

**tile**: One fixed-size square piece of a map or surface volume, processed on its own and then put back together. Inference wrappers log how many tiles they ran; StrokeNet's tile grid pilot scores a map tile by tile.

**trace (tracer)**: A traced surface, and the program that grows it. villa's tracer grows a surface from a seed.

**training labels**: The labels a model learned from. Scoring a model on its own training labels shows only that the pipeline runs, not that the model generalizes.

## U

**U-Net**: A common neural network shape for image segmentation. The scroll centre finder uses two small U-Nets.

**uint8**: An 8-bit unsigned whole number (0 to 255), the data type of the catalogue volumes.

**umbilicus**: The central axis of a roll. In the data it is a fitted centre line with one control point per height.

**Unroll**: A browser viewer on Hugging Face Spaces that rebuilds traced windings of PHerc. 139 ([`docs/unroll-space.md`](docs/unroll-space.md)).

**UV (u, v)**: The two coordinates of a point on a surface's own 2D grid, as opposed to its x, y, z position in the scan. The u axis runs along the roll.

## V

**v8in**: A community ink model (`YoussefMoNader/ink-8um-v8in`, released 28 September 2026). It never saw PHerc0139 w045, which makes w045 a held-out test for it.

**VC3D (Volume Cartographer 3D)**: The main application for viewing CT volumes and tracing, rendering and flattening surfaces. It is part of villa.

**verso**: The outer back side of a roll, where the fibres run vertically.

**Vesuvius Challenge**: The public competition, with prizes, to read the Herculaneum scrolls from X-ray scans ([scrollprize.org](https://scrollprize.org/)).

**villa**: The official ScrollPrize open-source repository ([ScrollPrize/villa](https://github.com/ScrollPrize/villa)), containing VC3D, ink detection and other tools. This repository plans runs of it and does not reimplement it.

**virtual unwrapping**: Recovering the content of a rolled surface from a 3D scan without opening it.

**volume**: A reconstructed 3D CT image of a scroll or fragment.

**voxel**: A volume element, the 3D version of a pixel. Voxel size is its edge length in micrometres.

## W

**weights**: The learned numbers inside a trained model. Weights are never stored in git here; released weights are downloaded and checked by SHA-256.

**winding (wrap, turn, layer, sheet)**: One turn of papyrus around the roll. The terms are used interchangeably. A winding number counts turns from the centre.

## X

**X-ray CT**: See CT.

## Z

**zarr**: A format that stores a large array as many compressed chunks, so a program can read only the part it needs. kit reads zarr with the zarr 3 Python library.
