# Glossary

A plain-language list, A to Z, of the technical terms used in this repository's code and documentation. Each definition follows how the term is used here. Where a fuller treatment exists, the entry points to it. The Vesuvius Challenge book in [`docs/vesuvius-bible/`](docs/vesuvius-bible/bible.md#app-glossary) has a longer glossary of the wider field.

Status labels used across the repository (Sourced fact, Community report, Model output, Interpretation, Untested idea) are defined in [`docs/NOVELTY.md`](docs/NOVELTY.md).

## A

**absorption contrast**: Image contrast that comes from how strongly different materials absorb X-rays.

**active learning**: Choosing which regions a person labels next so each label helps the model most, usually where the current models are least sure. The organizers list it under label quality in their open problems; `kit labelsuggest` is one such pick for ink labels.

**affine (cross-scan affine)**: A linear transform plus a shift that maps coordinates in one scan of a scroll to coordinates in another scan of the same scroll. The catalog publishes these, fitted from landmarks; `kit meshaudit transforms` refits them.

**API (application programming interface)**: A defined way for one program to request data or actions from another. A tool API lets scripts use the same operations that a person might select in an app.

**AppImage**: A single-file Linux application package. villa releases VC3D as one; `kit vc3d` can run VC3D through it.

**Apple Silicon**: Apple's own Mac processors (M1 and later). VC3D, rendering and flattening run natively on them; see [`docs/mac.md`](docs/mac.md).

**At a glance table**: The two-column table at the top of every tool page in `docs/tools/` (Id, Status, Kind, Area, Run, Code, Tests, Needs, Runs on, Network, Writes, Go-ahead, Released, Checked). An agent reads it first. See [`docs/TOOL-DOCS.md`](docs/TOOL-DOCS.md).

**AUC (pixel AUC)**: Area under the ROC curve. Here it measures how well an ink map ranks labeled ink pixels above labeled non-ink pixels, inside a segment's supervision mask (`kit auc`). 0.5 is chance and 1.0 is perfect. An AUC is reported beside the same reader's reverse-depth map as the control.

**Auto3DSeg**: NVIDIA's automatic 3D segmentation pipeline in MONAI (AutoRunner). It analyzes a dataset, trains SegResNet, DiNTS and Swin UNETR and ensembles them. `kit segzoo datalist` writes the datalist it reads from an nnU-Net dataset ([page](docs/tools/segzoo.md)).

**AutoPipeline (AP)**: The released package that drives villa's VC3D tools and ink detection from a scan through surface checks, rendering and controlled scoring. It records the choices for a run and keeps a control beside each check. See [AutoPipeline](docs/autopipeline/README.md) and the README's released tools list for the current version.

**average precision (AP score)**: A score for ranked predictions that summarizes the share of selected pixels that are positive as the selection expands to include more positives. Ink Bench uses it to compare an ink map with its reference. Here AP means average precision; in the pipeline docs, AP can also mean AutoPipeline.

## B

**B300**: An NVIDIA data-center GPU. It was the default GPU for Modal jobs in this repository until 23 Oct 2026, falling back to B200, H200 and H100 when none was free. Hugging Face Jobs, where paid work runs now, do not offer it.

**benchmark**: A fixed test with a fixed scoring rule, used to compare readers or tools. The numbers live in [`docs/results.json`](docs/results.json).

**BM18**: A beamline at the ESRF built for phase-contrast tomography of large objects; used for scroll scans from 2025.

**bootstrap**: Resampling the data many times to estimate how much a score would vary. `kit auc --bootstrap` gives AUC intervals this way.

**Branch only**: The status of a tool page whose code is not on the default branch, only on another branch or in history. The page names the branch and commit that hold it and says why it is not on the default branch ([`docs/TOOL-DOCS.md`](docs/TOOL-DOCS.md)).

**bucket (open-data bucket)**: The Vesuvius Challenge's public Amazon S3 storage, which holds the scans, segments, predictions and labels that kit reads.

## C

**canvas (render canvas)**: The 2D pixel grid onto which a traced surface is rendered. A published surface volume reproduces its canvas from its mesh.

**carbonized**: Turned to carbon-rich material by heat. The Herculaneum scrolls were carbonized in the eruption of Vesuvius in 79 CE.

**catalog**: The challenge's machine-readable list of samples, scans, volumes, segments and models.

**Center Finder**: Chase Hendrick's tool in `scripts/umbilicus/` that finds a scroll's winding center line (umbilicus) in its CT scan with two small U-Nets; page [`docs/tools/umbilicus.md`](docs/tools/umbilicus.md). Its lines are model output.

**centroid**: The average position of the points in a shape or mask. The papyrus centroid is a simple center estimate used as a comparison for the Center Finder; it need not be the center around which the sheets wind.

**chain rule (windlabel)**: The fixed test `kit windlabel-box` applies to each step of a chain of sheet crossings: the next sheet is thin, at a spacing in line with the chain's earlier steps, and the sheet's normal turns little. Version 1 has digest `0e53e0ae5016`. See [`docs/tools/windlabel-box.md`](docs/tools/windlabel-box.md).

**checkpoint**: The saved weights of a trained model.

**Connect your tool (panel)**: The section every one of Chase's Hugging Face Spaces carries (24 Oct 2026): the URLs of the data the page shows, with tested snippets for Python, villa's `vesuvius` package, VC3D, neuroglancer, curl, gradio_client and MCP. Written from each Space's `connect.json` by `python -m kit spaceconnect`; page [`docs/tools/spaceconnect.md`](docs/tools/spaceconnect.md).

**claim level (Measured, Certified, Not shown)**: How strong a statement the Snapped Labels Space's Voxel exact tab makes for one scroll. Measured: snapped vertices scored against the face seen in an independent, finer scan of the same scroll. Certified: no finer scan, so a truth-free lower bound that holds under listed assumptions. Not shown: neither holds, with the reason. Every level is model output. See [snapped-labels](docs/tools/snapped-labels.md).

**claims ledger (`docs/claims/sources.json`)**: The list, per block of the README's Novel findings, of the results units and files its numbers come from, each pinned to its sha256, and a reason (setting, count, derived, external or context) for any number no source holds. `python -m kit.claimcheck check` fails when a number has neither. See [`docs/tools/claimcheck.md`](docs/tools/claimcheck.md).

**chunk**: One stored block of a zarr array. Readers fetch only the chunks they need.

**control**: A deliberately wrong or scrambled input run through the same check, so that the check is shown able to fail. Examples here are the reverse-depth map, the depth-shuffled volume, a displaced map and a rotated or IAAFT copy.

**control-set threshold**: Ink Lens's threshold for one region: the 99th percentile of the region's own reverse-depth ink map over its papyrus. Only stored-order ink above it is kept, and the region's status compares the share above it with the control's 1 % ([`docs/prereg/2026-10-20-ink-lens-gate.md`](docs/prereg/2026-10-20-ink-lens-gate.md)).

**coordinate frame**: The origin, axis directions and units used to describe a point. Coordinates from different scans or resolution levels must be converted into the same frame before they can be compared.

**Contact barrier**: AutoPipeline's sheet-switch repair (`kit switchfix barrier`, `qa.repair` method `barrier`, in AutoPipeline 0.1.9): where a touching sheet shows on both sides of a traced surface, it draws a barrier and keeps only the part the seed reaches. It cuts, it never mends; page [`docs/tools/contact-barrier.md`](docs/tools/contact-barrier.md).

**CORS (cross-origin resource sharing)**: The web server permission that lets a browser page read data from another site. A data URL can work when opened directly yet fail inside Unroll if its server does not allow that page to read it.

**coverage polish (`kit axispolish`)**: An adjustment of an estimated center line toward nearby points with greater winding coverage on predicted sheets. It uses geometry from the normal grids, not ink. A polished line is still model output. See [axispolish](docs/tools/axispolish.md).

**CPU**: The computer's general-purpose processor. Ink inference that runs on the CPU is much slower than on a GPU.

**crop**: A rectangular window cut from a map or volume. Gate A scores fixed crops of densest labeled ink, with a 64 pixel inner edge left out (`--inner 64`).

**CT (computed tomography)**: Building a 3D image of an object from many X-ray projections taken at different angles.

**CTC**: Connectionist temporal classification, a way to train a network to output a sequence (here, letters along a line) without marking where each letter sits. Scroll Text Reader's Greek LineNet uses a CTC line network.

**CUDA**: NVIDIA's GPU programming platform. Most villa training and inference assume an NVIDIA GPU with CUDA.

## D

**d9v2**: A community fine-tune of `ink_9um`, usable as a drop-in `ink_9um` checkpoint.

**depth shuffle**: A control volume in which the layers of a surface volume are put in a random order (`kit shuffle`, `kit layers --shuffle SEED`). Real ink signal should not survive it.

**Dice score**: An overlap measure between two masks: twice the shared area divided by the sum of both areas. A Dice check is reported beside the same map displaced.

**DINOv2, DINOv3**: Self-supervised image backbones from Meta, trained without labels on very large photo collections. DINOv2 is Apache-2.0; DINOv3's weights are under the DINOv3 License and gated on Hugging Face. `scripts/segzoo/segzoo_probe.py` puts a linear head on their frozen features ([page](docs/tools/segzoo.md)).

**dinovol**: The Vesuvius Challenge model family that turns small regions of a CT volume into embeddings, or lists of learned features. Those features can be compared to find regions with similar structure; similarity alone does not identify ink.

**Discord**: The chat service where the Vesuvius Challenge community meets and where most announcements appear first.

## E

**embedding**: A list of numbers a model assigns to an input to describe learned features. Similar lists can help locate similar-looking regions, but their meaning depends on the model and its training.

**empty-chunk marker**: A `.empty` file VC3D writes in its remote chunk cache when the server answers 404 for a chunk; VC3D then reads that chunk as zeros for good. A marker for a chunk the bucket holds is a false one ([vc3d-cache](docs/tools/vc3d-cache.md)).

**ESRF**: The European Synchrotron Radiation Facility in Grenoble, where scrolls have been scanned since 2025.

**evidence archive**: A frozen folder under `docs/evidence/` with the inputs, rules, scripts, results and SHA-256 hashes of one study. These folders are not edited.

## F

**false 404**: A case where S3 answers "not found" (HTTP 404) for a chunk it actually holds, with the error code `NoSuchBucket` instead of `NoSuchKey`. VC3D then caches the chunk as empty (an empty-chunk marker) and reads it as zeros. `kit/s3retry.py` asks again; `python -m kit s3relay` keeps it away from VC3D and `python -m kit vc3dcache` deletes the false markers ([how-to](docs/vc3d-false-404.md)).

**fiber**: A strand of the papyrus plant, visible in CT. Fibers run horizontally on the recto.

**fiber evidence**: Fiber Checker's per-patch score, from 0.5 to 1: how strongly its judge prefers the CT rendered along a traced surface over a copy with the same texture but its strands scrambled. Near 1 where fibers show, near 0.5 where none do. Model output ([page](docs/tools/fibercheck.md)).

**finesnap**: `kit finesnap`, which snaps a surface label traced on a coarse scan onto the recto face seen in a finer scan of the same scroll, registered per site along the normal ([page](docs/tools/finesnap.md)).

**fine-tune**: A model made by further training an existing model on new data.

**First Letters prize**: A Vesuvius Challenge prize for the first letters found in a given scroll. Current eligible scrolls are listed by `python -m kit prizes`.

**flattening**: Mapping a traced 3D surface onto a flat plane with as little distortion as possible.

**fp16 (half precision)**: Storing and computing numbers with 16 bits instead of the usual 32 (fp32). It can make GPU inference faster at a small cost in accuracy. `V8IN_FP16=1` turns it on for v8in on MPS, where it is kept only if the crop check still passes and it is faster.

**fragment**: A detached piece of papyrus, often with visible ink, used as ground truth for ink models.

**frozen-feature probe (linear probe)**: A test of a pretrained backbone in which the backbone is not trained at all: only a linear (logistic) head on its features is fitted. Cheap enough for a CPU, and a fair first check of whether a big model helps a small task.

## G

**gap letter accuracy**: In the Greek gap restoration benchmark (`python -m kit.greekfill`, [page](docs/tools/greekfill.md)), the share of hidden letters a model puts back in the right place, counted position by position, so a reply of the wrong length loses the letters it misplaces.

**Gate A**: The repository's rule for ranking two released ink readers (`python -m kit gate`, rule in `kit/gate.py`): a lead of at least 0.02 mean AUC over three PHerc0841 crops, with forward minus reverse AUC at least 0.10 on every crop.

**generalization**: How well a model does on data it was not trained on. Claims of generalization need a held-out labeled segment.

**GPU**: A graphics processor, used here for fast model training and inference.

**grad_mag**: A sheet-density channel published with lasagna's model outputs: high where papyrus sheets are, so its integral along a short line counts roughly how many sheets the line crosses. `kit windlabel-box` uses it to find steps that cross more than one sheet.

**Grand Prize**: The largest Vesuvius Challenge prize of a challenge year.

**GrowPatch**: A VC3D tracer that grows a surface mesh outward step by step by optimization.

## H

**Harness2 (Harness squared)**: An optional framework for testing changes to the software around an agent while keeping model weights fixed. Scrolls uses a bounded local adapter to compare provenance workflows on generated files; it does not train an ink reader. See [the adapter guide](docs/tools/harness2.md).

**Headless VC3D**: The released `vc3d-agent` package, which exposes villa tools through shell commands and an MCP server so scripts and agents can trace, check, flatten and render surfaces without a graphical display. See [the tool page](docs/tools/vc3d-agent.md).

**heatmap**: An image in which each pixel holds a score. The Center Finder predicts a heatmap whose peak estimates the center of a CT slice.

**held-out**: Data a model never saw in training. A test on held-out data is the only kind that supports a claim about how well a model generalizes. For example, w045 is held out from v8in but not from `ink_9um`, which trained on its 2.4 µm render. Which released reader trained on which labeled segment is tabulated in [`docs/logs/2026-10-16-reader-exposure.md`](docs/logs/2026-10-16-reader-exposure.md).

**Hecate**: An ink model by Giorgio Angelotti, used in the PHerc. 343 First Letters result. Its base model is `scrollprize/ink_canonical_2um`, whose committed trainer lists all three PHerc0841 segments, so PHerc0841 is not held out from Hecate, although Hecate's own published split rule, applied to the published masks, would keep PHerc0841 validation-only ([log](docs/logs/2026-10-16-reader-exposure.md)).

**Herculaneum papyri (Herculaneum scrolls)**: Papyrus rolls from a Roman villa at Herculaneum, carbonized by Vesuvius in 79 CE.

**hero (hero image)**: The wide picture at the top of a README or release entry. Here every released tool has one: 1920 x 640 pixels, WebP, at most 300 KB, in the charcoal, ivory and copper style of the root README's, with its media label in the caption. Made by `scripts/media/hero.py`; listed in [`docs/assets/README.md`](docs/assets/README.md).

**hfpull**: The public bucket download helper `python -m kit.hfpull`. It downloads each distinct file once, then copies it to other paths with the same content. It downloads files; it does not upload them. See [hfpull](docs/tools/hfpull.md).

**Hugging Face**: A site that hosts models, datasets and small web apps called Spaces. Several released weights and the Unroll viewer live there.

## I

**IAAFT**: Iterative amplitude-adjusted Fourier transform. It makes a surrogate copy of an image with the same brightness values and nearly the same frequency content but no real structure. StrokeNet reports results against IAAFT copies as a control.

**inference**: Running a trained model on new data to get predictions.

**Ink Bench**: The ink map scoring in the Unroll Space. It aligns an ink map of one PHerc0139 winding with the published 2.4 um ink detection and reports Pearson r, IoU, Dice and average precision, with the X-ray intensity and uniform noise as floors; `tools/inkbench.py` in the Space gives the same numbers on the command line. It scores agreement with another model's output, not ground truth ([`docs/tools/unroll.md`](docs/tools/unroll.md)).

**ink detection**: Predicting where ink lies on a rendered surface from the CT data. The output is an ink map.

**Ink Atlas**: A Space ([SharpMeow/ink-atlas](https://huggingface.co/spaces/SharpMeow/ink-atlas)) and MCP server over the public First Letters ink atlas dataset ([SharpMeow/first-letters-ink-atlas](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas)): seven public ink models on 32 traced surfaces of the First Letters scrolls and PHerc0343, each rendered once on one shared 9.6 um canvas so the maps line up pixel for pixel. Model output ([page](docs/tools/ink-atlas.md)).

**Ink Lens**: A tool and ZeroGPU Space ([SharpMeow/ink-lens](https://huggingface.co/spaces/SharpMeow/ink-lens), live since 24 Oct 2026) that runs an openly licensed 9 um ink model on one region of a VC3D segment in both depth orders over three depth windows, keeps ink above the control-set threshold, and writes the overlay and letter-candidate pins as VC3D's own files ([`docs/tools/ink-lens.md`](docs/tools/ink-lens.md)).

**ink label (inklabels)**: A human-drawn mask of where ink is on a segment (`inklabels.zarr`), used for training and scoring.

**ink map (ink probability map)**: A model's per-pixel prediction of ink. It is model output, not a reading; only papyrologists decide what letters an image shows.

**ink_9um**: The Vesuvius Challenge's cross-scroll ink models for scans at about 9 µm.

**Inkfilter**: The released package that combines fixed image filters to make a map from a surface volume, with a reverse-depth control and no trained model. Its output is not a reading. See [Inkfilter](docs/tools/inkfilter.md).

**intercolumn**: The blank space between two columns of text.

**integrity check (`kit integrity`)**: This repository's checker for Vesuvius claims: an ink score needs its reverse-depth control and a held-out status from that reader, wording must not call model output a reading, a preregistration must precede its result, citations must match arXiv. It plants faults it must catch before it reports anything. The `vesuvius-integrity` Claude skill states the same rules as instructions ([guide](docs/integrity.md)).

**IoU (intersection over union)**: The area marked positive by both masks divided by the area marked positive by either mask. It measures overlap, so the masks must describe the same pixel grid.

**isometry (of a segment grid)**: How closely a tifxyz grid keeps the spacing its `meta.json` promises: every edge's 3D length over the promised step, each cell's area over the promised area, and the angle between the grid's two directions (1.0, 1.0 and 90 degrees when exact). `kit tifxyz stretch` reports them; a grid far from isometric distorts a flattened render ([`docs/tools/tifxyz.md`](docs/tools/tifxyz.md)).

## K

**Kaggle**: A data-science competition platform that has hosted Vesuvius Challenge competitions.

**keep-open**: The label on a ScrollPrize/villa pull request that exempts it from villa's daily time-limit workflow, which otherwise closes a PR after 14 days without activity or 28 days open; `kit prclock` shows each PR's clock ([`docs/tools/villapr.md`](docs/tools/villapr.md)).

**keV (kiloelectronvolt)**: The unit of X-ray photon energy. Scan names in the bucket give it, for example `113keV`.

**kit**: The repository's Python package (`python -m kit`). It plans and records runs of the official pipeline, scores ink maps, checks results and keeps the experiment ledger. Every subcommand is in `kit/cli.py`; the full list is in [`docs/MAP.md`](docs/MAP.md).

**Kneser-Ney (KN) letter model**: A letter n-gram language model that predicts each letter from the few before it, with modified Kneser-Ney smoothing (Chen and Goodman 1999). Here it is the baseline of the Greek gap restoration benchmark (`kit/greekkn.py`, order 8) and, separately, Scroll Text Reader's optional order-5 prior (`kit/greeklm.py`).

## L

**label set**: One dated folder of a segment's published ink labels on the open-data bucket, `SCROLL/segments/SEGMENT/ink-labels/<voxel size>um-volume-<VOLUME>/<date>/`, holding `inklabels.zarr`, `supervision.zarr` and sometimes `validation.zarr`, all drawn on one volume's render. `kit labels` lists them ([`docs/tools/labels.md`](docs/tools/labels.md)).

**labelsnap**: `kit labelsnap`, which moves each vertex of a tifxyz surface label along its normal onto the recto face of its papyrus band in the label's own CT, with a confidence and an abstain mask ([page](docs/tools/labelsnap.md)).

**labelsuggest**: `kit labelsuggest`, which ranks the tiles of a segment by how much two or more readers' ink maps disagree there, so a person paints labels first where a label corrects at least one model. A suggested tile is a place to label, not a claim about ink ([page](docs/tools/labelsuggest.md)).

**label smoothing**: Training with softened targets, so ink and background labels are not exactly 1 and 0.

**lasagna field**: The output of villa's lasagna model (`lasagna-preprocess predict3d`) over a whole scan: OME-Zarr channels cos (a signal that repeats once per papyrus layer), grad_mag and the surface normals nx and ny, with a `SCAN.lasagna.json` manifest. villa's lasagna surface fitting and the spiral fit read it. Fields for ten scans are in the [Lasagna Fields](https://huggingface.co/spaces/SharpMeow/lasagna-fields) datasets. Model output.

**landmark**: A point marked in two scans of one scroll, used to fit the cross-scan transform between them.

**lasagna**: villa's lasagna surface fitter and the model outputs it reads, such as grad_mag; outputs are published for open-data volumes, for example PHerc0139's `20260102150214-lasagna-20260419180421-L2`.

**Lasagna Fields**: The public collection of villa lasagna model outputs and its guide app. A lasagna field describes predicted sheet structure for surface fitting; it is not an ink map. See [Lasagna Fields](docs/tools/lasagna-fields.md).

**Lasagnetta**: A faster student of villa's lasagna net that writes a preview of a lasagna field, about 5 times faster than villa `predict3d`, with a self-check that points to villa where they disagree. villa's own field stays the reference. Model output. See [Lasagnetta](docs/tools/lasagnetta.md).

**layer**: One image in a surface volume, at a fixed depth from the traced surface. `kit layers` writes them as numbered TIFF files. In the scroll itself, "layer" also means one turn of papyrus (see winding).

**layer order**: The order of images through the depth of a surface volume. The surface normal determines which side comes first. Reversing the order supplies the reverse-depth control used alongside an ink model.

**ledger (experiment ledger)**: The local record of each run in `experiments/<slug>/run.json`, with its readout-rule hash, status, wall time and cost. Modal launches have their own ledger in `docs/compute/modal-ledger.csv`.

**level (resolution level)**: One copy of a volume at a given downsampling in a multi-resolution zarr. Level 0 is full resolution; higher levels are smaller, downsampled copies.

## M

**maturity (stage registry)**: How far an option of a stage has been shown to work, on one scale: default (what a workflow runs when nothing is named), validated (a held-out or published benchmark with its control), experimental (runs; no passing held-out result yet), pending (in development checks, not runnable until it passes) and failed (failed a frozen test or its controls) ([stagereg](docs/tools/stagereg.md)).

**m7**: The organizers' binary surface prediction model for the open data: a voxel map of where papyrus sheet surfaces are. Several kit tools read its published outputs; it can merge sheets that touch.

**Mamba (selective scan, SS2D)**: A sequence layer that carries a state along a sequence, with step sizes chosen from the input (the selective scan). SS2D is VMamba's 2D form: the same scan along rows and columns, both ways. U-Mamba and SS2DNet are segmentation networks built with it. `scripts/segzoo/segzoo_ss2d.py` is a pure-PyTorch version ([page](docs/tools/segzoo.md)).

**maximum intensity projection (MIP)**: A flat view of a volume that keeps the brightest voxel along each viewing ray. Unroll uses it to show CT around a selected point; several depths can contribute to the image.

**MCP (Model Context Protocol)**: A protocol through which an agent discovers tools, sends structured requests and receives results. Headless VC3D uses it to expose its commands to agents.

**memorization probe**: In the Greek gap restoration benchmark, an item that shows the start of a passage and asks for the next letters exactly; high accuracy would mean a model recalls the text rather than restores it.

**mask**: An image that marks which pixels or voxels belong to a region, such as papyrus, labeled ink or trusted labels.

**media label**: What a picture shows, written first in its caption and in its sidecar JSON: Concept illustration, Real data render, Model output or Synthetic demo ([`docs/assets/README.md`](docs/assets/README.md)). Public Scrolls holds concept illustrations, synthetic demos and real data renders allowed by the public media rule; model output pictures and real data renders of prize-eligible scrolls stay in Scrolls-private.

**MedNeXt**: A U-Net built from ConvNeXt blocks (large depthwise kernels), in sizes S, B, M and L. In the nnU-Net Revisited comparison it is the one family that scored above nnU-Net's ResEnc L on every dataset, at about twice the training time.

**MedSAM2**: SAM 2 fine-tuned on 3D medical images and video. Its weights are licensed for research and education only, so nothing trained from it is released here.

**mesh**: A connected surface made of vertices and faces. Traced segments are stored as meshes, usually in tifxyz form.

**m7**: The organizers' public surface prediction for PHerc0139 scan 20250728140407 (`...-surface-m7-L0-th0.2.zarr` under `PHerc0139/representations/predictions/surfaces/`), stored as 0 or 255. `kit hopbench` uses it as its default prediction and baseline.

**micro-CT**: CT at micrometer resolution. The scrolls are imaged this way, now mostly with phase-contrast synchrotron scans.

**micrometer (µm, um)**: One thousandth of a millimeter. Written "um" in file names and some docs.

**Modal**: A cloud computing service that runs jobs on rented GPUs and CPUs, billed by use. Until 23 Oct 2026 any job here that needed a GPU, or more than about an hour of CPU, ran on Modal; paid work now runs on Hugging Face (AGENTS.md hard rule 11). Past specs are in [`docs/compute/modal-specs/`](docs/compute/modal-specs/README.md) and prices in [`docs/compute/modal-pricing.md`](docs/compute/modal-pricing.md).

**model card**: A short document that describes a released model: its training data, intended use, results and limits.

**MPS**: Metal Performance Shaders, the backend PyTorch uses to run on Apple Silicon GPUs.

## N

**neighbor-sheet test (`kit sheetcheck`)**: A label-free check that an ink map reads the traced sheet: the same model is read one and two sheet pitches (wrap pitches) away along the mesh normals, and the map there must not correlate with the map on the sheet at 0.5 or more after slow shading is removed. A pass is necessary, not sufficient: a map with no ink signal passes too ([`docs/tools/sheetcheck.md`](docs/tools/sheetcheck.md)).

**Neuroglancer**: An external browser viewer for multidimensional image volumes. `kit volumeview` creates a local viewer link from explicitly declared public grid metadata; it does not verify the remote volume or its registration.

**nnU-Net**: A self-configuring U-Net framework: given a labeled dataset it picks the patch size, network depth, augmentation and training schedule itself. ResEnc M, L and XL are its residual-encoder presets. The community's surface model m7 is an nnU-Net ResEnc L.

**normal**: A direction perpendicular to a surface. A normal grid is a published 3D field of such directions that tracing uses.

**null result**: A run that found no signal. Several teams have published nulls from running the released 9 µm ink models on eligible scrolls.

**NumPy**: The standard Python library for numerical arrays. Several released tools need only NumPy to run.

## O

**one-sheet check (`kit.sheetgap`)**: A check that a traced surface stays on one sheet where sheets touch. At each mesh point it reads a surface prediction along the normal and passes only an isolated run no thicker than one sheet, with empty voxels on both sides; neighbors link only when their runs line up. Its blind spot is a prediction that draws two pressed sheets as one thin run ([`docs/tools/hopbench.md`](docs/tools/hopbench.md)).

**OCR (optical character recognition)**: A model proposing text from an image. Its output still needs independent checks and is not a verified reading.

**OME-Zarr**: A zarr layout for large microscopy-style images, with several resolution levels and metadata. The challenge stores its CT volumes this way.

**one-scroll fragment (`onescroll.html`)**: The style and short script every Space page carries so that only the page scrolls: it fits each same-origin frame inside the page (a guide shown with `iframe srcdoc`) to its content, so the frame never shows a scroll bar of its own. Written by `python -m kit spaceconnect render`; a frame that must scroll (a map) opts out with `data-scroll="inner"`. See [`docs/tools/spaceconnect.md`](docs/tools/spaceconnect.md).

**one-screen viewer**: A Space whose page never scrolls (Umbilici, Unroll, Segment Lens), marked `"layout": "one-screen"` in `spaces/connect/spaces.json`. It may keep one scrolling list or panel, never two at once.

**open problems**: The Vesuvius Challenge's published list of unsolved tasks ([scrollprize.org/2026_open_problems](https://scrollprize.org/2026_open_problems)).

## P

**papyrologist**: A scholar of ancient papyri. Only the Vesuvius Challenge papyrology team decides whether an image is legible.

**patch**: A small piece. In tracing, a patch is one traced piece of surface that can be merged with others. In ink detection, a patch is the small 3D block of a surface volume that a model reads at one time.

**Pearson correlation (Pearson r)**: A measure of how closely two sets of values vary together in a straight-line relationship. Ink Bench applies it to aligned image pixels. Correlation with a model-generated reference is agreement with that reference, not proof of ink.

**phase contrast**: Image contrast from the shift in phase of X-rays passing through a sample, made visible by letting the beam travel to the detector.

**PHerc.**: Short for Papyrus Herculanensis, followed by an inventory number, for example PHerc. 0139 or PHerc0139. PHerc. Paris 4 is also called Scroll 1.

**pixel AUC**: See AUC.

**planted hop (`kit hopbench`)**: A copy of a patch of one hand-traced winding moved partly onto its touching neighbor at a real contact, so that the patch switches sheets on purpose. Band plants step across only inside the contact zone; ramp plants slide across over 16 voxels. Used to measure how often a one-sheet check misses a switch ([`docs/tools/hopbench.md`](docs/tools/hopbench.md)).

**planted defect (`kit.planted`)**: A sheet switch, lens, skip, merger, hole or bridged hole put on purpose into a synthetic tifxyz surface whose every vertex records the winding it truly sits on, so a detector, stack check or labeler can be tested against a known answer. Synthetic data only ([`docs/tools/planted.md`](docs/tools/planted.md)).

**preregistration**: Writing down the readout rule, data and pass bar before any result is seen (`python -m kit run init`, or a committed file in `docs/prereg/`). It stops a rule from being tuned to fit the answer.

**prize eligible**: A scroll that one of the open prizes accepts results on. `python -m kit prizes` lists them from a dated snapshot; [scrollprize.org/prizes](https://scrollprize.org/prizes) wins where they differ. Results on a prize-eligible scroll stay private until the official announcement.

**Progress Prize**: A monthly Vesuvius Challenge prize for open-source contributions such as bug fixes, tools and benchmarks.

**provenance**: The record of who ran what, when, on which machine and from which inputs (`kit/provenance.py`).

**pseudo-label**: A provisional label created from model output and human review. Pseudo-labeling trains a model, keeps its confident predictions as new labels and trains again.

**public media rule**: What pictures and clips public Scrolls' Git may hold (18 October 2026, set by the agents on Chase's delegation): concept illustrations, synthetic demos, and real data renders of public scans that are not prize eligible and show no held-out labels, each at most 1920 px wide and 4 MB with a sidecar; never model output of any scroll ([`docs/media/README.md`](docs/media/README.md)).

**pyramid (image pyramid)**: Copies of an image or volume at several resolutions. A viewer can read a smaller copy for an overview and finer copies for detail; the level determines the coordinate scale.

## R

**Reader v2**: A community fine-tune of `ink_9um` by Domenico Russo. It is AutoPipeline's default ink reader.

**recto**: The written inner side of a roll, where the fibers run horizontally.

**recto face**: The side of a papyrus band in CT that faces the scroll's axis, where a surface label should sit; `kit labelsnap` and `kit finesnap` find it as the band's edge toward the axis along each vertex normal.

**relative windings**: Points along a line from a scroll's core, each labeled with how many windings it lies outward of the first, without saying which absolute winding that is. villa's spiral fit reads them as a `relative_windings.json` point collection; `kit windlabel-box` makes them and `kit windconsistency` checks them.

**remote chunk cache (VC3D)**: The folder where VC3D keeps every chunk it streams from a remote volume, so later runs read them from disk; `kit doctor --remote` shows where it is and how much space it has ([`docs/tools/doctor.md`](docs/tools/doctor.md)).

**render (rendering)**: Sampling the CT volume along a traced surface, and at depths around it, to make a surface volume.

**resolution (voxel size)**: The edge length of one voxel, given in micrometers, for example 9.362 µm, 2.4 µm or about 9 µm. Smaller numbers show finer detail.

**resume (scroll2ink)**: Continue an interrupted run from its saved stage records. Completed stages are reused, and changed scientific settings are refused so one run folder does not mix incompatible results.

**reverse-depth map**: An ink map made from the same surface volume with its layers in reverse order. It is the required control for an ink AUC: real ink signal should depend on the true depth order.

**ROC curve**: A plot of true positive rate against false positive rate over all thresholds. AUC is the area under it.

**ROCm**: AMD's GPU computing stack, the counterpart of NVIDIA's CUDA. PyTorch has ROCm builds that run CUDA code through `torch.cuda`; `kit doctor` reports a ROCm card as a warning, because villa's spiral fitting asks for an NVIDIA GPU.

**routine (`kit routines`)**: A recurring, read-only repository check listed in `docs/routines.json`, daily or weekly, that any agent runs at session start with `python3 -m kit routines run --due`, so it does not depend on one account's scheduler. Its results stay in the ignored `work/routines/`.

## S

**S3**: Amazon's object storage service, which hosts the open-data bucket.

**SAM 2**: Meta's Segment Anything Model 2: segments an object in an image or a video from a click, box or mask, and follows it from frame to frame. `scripts/segzoo/segzoo_sam2.py` treats a cube's slices as frames to follow papyrus sheets ([page](docs/tools/segzoo.md)).

**Scroll Lens**: A Hugging Face ZeroGPU Space that runs the organizers' 3D DINO, ink and surface models on a small cube of a public scan, with click search over the embeddings, slice views and a 3D view drawn in the browser, and agent tools (an API and MCP server) ([`docs/tools/scroll-lens.md`](docs/tools/scroll-lens.md)).

**scroll2ink**: `python -m kit scroll2ink`, one command from a public scan and a seed point to a grown, checked, flattened and rendered surface and its ink map with the reverse-depth control, each step a Headless VC3D tool ([`docs/tools/scroll2ink.md`](docs/tools/scroll2ink.md)).

**Scrolls kit**: The grouped release entry for command-line tools maintained in this repository. It links each listed tool to its command, documentation and evidence; standalone products keep their own entries. The public [release registry](docs/releases.json) identifies the group as `scrolls-kit`.

**Scroll Text Reader**: Formerly Greek Letter Reader. The `scrolls-letterread` tool proposes Greek letters with LineNet or words with explicitly installed local Tesseract language packs. Both routes record model provenance and controls; neither verifies a reading ([guide](docs/letter-reader.md)).

**Scrolls Starter**: The local browser introduction to the released tools, with a synthetic controls exercise, setup checks and a Scroll Text Reader command builder. Its portable edition opens without Python and leaves setup unchecked. See [starter](docs/tools/starter.md).

**seam (of a spiral fit)**: The angle at which a spiral fit's winding count steps by one as it goes around the roll. A fit may put it anywhere, so a sheet that crosses it is not an error; `kit.seamswitch` allows for it in seam cells of 10 degrees by 250 voxels ([`docs/tools/seamswitch.md`](docs/tools/seamswitch.md)).

**seating (of a surface)**: Whether a traced surface lies on papyrus rather than in the gap between sheets. A seating check can reject misplaced surfaces, but passing it does not by itself rule out a jump to a neighboring sheet.

**seed (seed point)**: A starting point for tracing a surface. villa's tracer does not hold an explicit seed, so a trace can start on the next winding.

**SegFormer**: A 2D segmentation network with a hierarchical transformer encoder (Mix Transformer, sizes B0 to B5) and a light MLP decoder. Its code and weights are under NVIDIA's non-commercial license.

**segment**: A traced piece of papyrus surface together with its rendered surface volume. Segments are named by id, for example w035 or w045 of PHerc0139.

**Segment Atlas**: The table of `kit tifxyz`'s numbers for every tifxyz mesh on the open-data bucket, one row per mesh, published as the Hugging Face dataset SharpMeow/vesuvius-segment-atlas and refreshed daily (`python -m kit atlas`, [`docs/tools/atlas.md`](docs/tools/atlas.md)).

**segmentation (tracing)**: Finding and tracing the rolled papyrus surface inside a CT volume.

**SHA-256**: A hash function. A file's SHA-256 is checked to prove that downloaded weights or evidence are exactly the published ones.

**single-mesh layer**: Neuroglancer's layer type `mesh` for one triangle mesh read from a file (`vtk://` ASCII VTK or `obj://`), which can carry a value per vertex that the layer's shader colors. `kit sheetview` writes one with a volume sampled onto a segment ([`docs/tools/sheetview.md`](docs/tools/sheetview.md)).

**sheet switch**: A tracing error in which a mesh jumps from one turn of papyrus to another.

**sidecar (media sidecar)**: The JSON file next to a picture or clip, `NAME.json`, recording its media label, alt text, caption, license, sizes and SHA-256, inputs, and the command and scripts that made it (schema `scrolls-media/1`; [`docs/tools/media.md`](docs/tools/media.md)).

**Space (Hugging Face Space)**: A small web app hosted on Hugging Face.

**spiral fit**: Fitting one deformed spiral to the whole rolled papyrus of a scroll.

**split rule (windlabel)**: The fixed rule `kit windlabel-box` uses to cut a chain: every step whose grad_mag integral, scaled by 0.765 so one sheet reads about 1, is above 0.95 is cut, so each piece claims only counts the grad_mag agrees with. Digest `c6d2eecbebc2`.

**stage registry (`kit stages`)**: The one list of every option for each stage of reading a scroll (tracer, surface model, lasagna field, flatten, render, 2.5D or 3D ink reader, letter reader and others), with origin, license and maturity; workflows pick from it with `--use STAGE=NAME` or `KIT_STAGE_<STAGE>` instead of hard-coding a tool ([page](docs/tools/stagereg.md)).

**stackcheck**: `kit stackcheck`, which checks a stack of consecutive tifxyz segments of one scroll against its umbilicus from geometry alone.

**StrokeNet**: A small learned score in this repository for how much a window of an ink map looks like lines of text (`kit strokenet`), with rotation and IAAFT controls ([model card](docs/strokenet.md)).

**submitcheck**: `kit submitcheck`, a preflight of a prize submission folder against the prize page's file rules (tifxyz meshes, image names, Grand Prize `column_NN` names), quoting each rule ([`docs/tools/submitcheck.md`](docs/tools/submitcheck.md)).

**supervision mask (supervision.zarr)**: The region of a segment where its ink labels are trusted. Scores are computed only inside it.

**surface prediction**: A model's voxel-by-voxel prediction of where the papyrus surface is in a CT volume, used to guide tracing.

**surface volume**: A stack of images rendered at depths above and below a traced surface. Ink models read it.

**Swin UNETR**: A U-Net whose encoder is a Swin transformer (attention inside shifted windows), from MONAI. Its input sides must divide by 32.

**synchrotron**: A particle accelerator that produces very bright X-rays, used for the scroll scans.

**synthetic data**: Data made by a program, with a known answer, used to test that a tool works before it runs on real scans.

## T

**termstyle**: The terminal look of every Scrolls command (`kit/termstyle.py`): color, wrapping and a title and closing line on a terminal, plain text everywhere else; `kit live` is its mouse viewer ([page](docs/tools/termstyle.md)).

**Tesseract**: An open-source local OCR engine with separate language packs. The reader can explicitly select an installed pack and records its hash; printed-text accuracy does not establish accuracy on scroll ink maps.

**threshold**: A cut-off value that turns a probability map into a yes or no mask.

**tifxyz**: A surface format of three float32 TIFF images giving the x, y and z position of each grid cell, with -1 for missing cells.

**tile**: One fixed-size square piece of a map or surface volume, processed on its own and then put back together. Inference wrappers log how many tiles they ran; StrokeNet's tile grid pilot scores a map tile by tile.

**tool page**: The reference page of one tool in [`docs/tools/`](docs/tools/README.md): what it does, a quick start, its checks and controls, every option with its default, inputs, outputs, failure modes, cost, rules for agents, tests and history, written to [`docs/TOOL-DOCS.md`](docs/TOOL-DOCS.md) and checked against the code by `python -m kit.tooldocs check`. Pages still to be written are listed in `docs/tools/pending.json`.

**touched chunks**: The chunks of a zarr volume that lie within a margin of a segment's surface: the only part of the volume a render or check of that segment reads. `kit tifxyz chunks` lists them with their bytes and can copy only those ([`docs/tools/tifxyz.md`](docs/tools/tifxyz.md)).

**trace (tracer)**: A traced surface, and the program that grows it. villa's tracer grows a surface from a seed.

**training labels**: The labels a model learned from. Scoring a model on its own training labels shows only that the pipeline runs, not that the model generalizes.

**two-density score**: A simple ink score with no network (`kit strokenet --two-density`): for each 48 px label window (about 2.2 mm) of a pooled ink map, z(logit of its ink density) plus 0.25 times z(logit of the ink density of the 128 px window around it), z taken within one map, so it ranks windows of one map and never compares maps. Its one test was on PHerc0500P2 with ink_9um ([model card](docs/strokenet.md#the-two-density-score)). Model output, not a reading.

## U

**U-Net**: A common neural network shape for image segmentation. The Center Finder uses two small U-Nets.

**uint8**: An 8-bit unsigned whole number (0 to 255), the data type of the catalog volumes.

**Umbilici**: The browser app that displays public scroll center lines over CT, credits their sources and provides data links. The plural of umbilicus is umbilici; a center line is geometry, not a reading. See [Umbilici](docs/tools/umbilici.md).

**umbilicus**: The central axis of a roll. In the data it is a fitted center line with one control point per height.

**umbilicus.json**: The umbilicus file name VC3D searches for first, beside its project file and its segment folders (then `estimated_umbilicus.json`), and the one a spiral-fitting dataset folder must hold. Its `metadata` may state `volume_width`, `volume_height` and `volume_slices`, the voxel grid its points are in (all three or none; VC3D refuses a partial set), which VC3D uses to place the points on the volume it has open. `scripts/umbilicus/predict.py --vc3d-name` writes one with the scan's level-0 grid when available ([page](docs/tools/umbilicus.md#use-it-in-vc3d-and-spiral-fitting)).

**Unroll**: The browser viewer that displays traced scroll windings in 3D and virtually unrolls them, with CT and ink layers, close-up views and Ink Bench. The displayed ink layers are model output, not readings. See [Unroll](docs/tools/unroll.md).

**UV (u, v)**: The two coordinates of a point on a surface's own 2D grid, as opposed to its x, y, z position in the scan. The u axis runs along the roll.

## V

**v8in**: A community ink model (`YoussefMoNader/ink-8um-v8in`, released 28 September 2026). It never saw PHerc0139 w045, which makes w045 a held-out test for it.

**VC3D (Volume Cartographer 3D)**: The main application for viewing CT volumes and tracing, rendering and flattening surfaces. It is part of villa.

**VC3D plugin**: A JSON manifest that adds one external tool to VC3D's Plugins menu: the program, its arguments with placeholders for what VC3D has open, and how VC3D loads what it writes. Proposed on villa branch `vc3d-plugins`; this repository's manifests are in [`plugins/`](plugins/README.md).

**verso**: The outer back side of a roll, where the fibers run vertically.

**Vesuvius Challenge**: The public competition, with prizes, to read the Herculaneum scrolls from X-ray scans ([scrollprize.org](https://scrollprize.org/)).

**villa**: The official ScrollPrize open-source repository ([ScrollPrize/villa](https://github.com/ScrollPrize/villa)), containing VC3D, ink detection and other tools. This repository plans runs of it and does not reimplement it.

**virtual unwrapping**: Recovering the content of a rolled surface from a 3D scan without opening it.

**volume**: A reconstructed 3D CT image of a scroll or fragment.

**voxel**: A volume element, the 3D version of a pixel. Voxel size is its edge length in micrometers.

## W

**WebGL**: The browser graphics interface used to draw interactive 3D scenes with the graphics processor. Unroll uses it to display traced surfaces and CT views.

**weights**: The learned numbers inside a trained model. Weights are never stored in git here; released weights are downloaded and checked by SHA-256.

**winding (wrap, turn, layer, sheet)**: One turn of papyrus around the roll. The terms are used interchangeably. A winding number counts turns from the center.

**winding coverage**: How many times a slice's traced sheet winds around a point: the summed angle its segments subtend there, divided by a full turn, in wraps. Deep inside the roll it is high; off center it drops. `kit windcheck` computes it from villa's normal grids, and `kit axispolish` moves a center line to where it is highest (the coverage polish) ([page](docs/tools/windcheck.md)). A measurement on model-predicted sheets, not a distance to the true axis.

**winding switch (seam-aware)**: A pair of touching vertices of one traced sheet that a spiral fit puts on different windings, once the fit's seam is allowed for. `python -m kit.seamswitch` counts them per 1000 neighbor pairs; a geometry score of a fit, not a reading ([`docs/tools/seamswitch.md`](docs/tools/seamswitch.md)).

**window and level (CT display)**: Display controls for CT brightness and contrast. Window sets the range of values shown, and level sets its midpoint. Changing them changes the view, not the stored scan values.

**wrap pitch**: The radial distance from one wrap of a scroll to the next. `kit coverage` measures it on the published meshes: along a mesh row that goes more than a full turn around the center line, the radius one turn further on less the radius here ([`docs/tools/coverage.md`](docs/tools/coverage.md)).

## X

**X-ray CT**: See CT.

## Z

**zarr**: A format that stores a large array as many compressed chunks, so a program can read only the part it needs. kit reads zarr with the zarr 3 Python library.
