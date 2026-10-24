# Tracing tools: which one for what

One page for the question "how do I trace, edit or check a segment, and which tool should I install?" It lists the public ways to make or edit a tifxyz surface, what each takes in and writes out, how hard it is to install, whether it runs on a Mac, and where this repository's kit commands fit. The history of these tools is in [the reference book's tracing chapter](vesuvius-bible/md/18-tracing.md) and its [tools chapter](vesuvius-bible/md/22-tools.md); a longer list of community repositories is in [external.md](external.md).

Every row was read on **24 October 2026** from the linked page (the project's tutorial, the [Awesome Scroll Tools](https://scrollprize.org/community_projects) list, or the tool's own README, read from its default branch). Tools change quickly; the linked page wins on any disagreement. Labels follow [NOVELTY.md](NOVELTY.md): rows are **Sourced fact** unless marked; the "Pick it when" column is **Interpretation**.

## Make or edit a surface

| Tool | What it does | In | Out | Install | Mac | Pick it when |
| --- | --- | --- | --- | --- | --- | --- |
| [VC3D](https://scrollprize.org/tutorial_VC3D) (villa) | The team's viewer and semi-automated unwrapping tool: opens scans from the built-in open-data catalog, grows a segment with Create Segment (GrowPatch), extends it by hand, line annotations along fibers (needs lasagna normals) | OME-Zarr volumes (streamed or local), surface predictions | tifxyz segments | A macOS `.dmg`, a Windows installer `.zip`, a Linux `.AppImage` with the `vc_*` command-line tools, a source build script, or the Docker image `ghcr.io/scrollprize/villa/volume-cartographer:edge` ([tutorial](https://scrollprize.org/tutorial_VC3D#installing-vc3d)) | Yes, Apple Silicon `.dmg` | You want the tool the team and annotators use, and the format every prize asks for |
| VC3D command-line tools (`vc_*`) | The same engine without the window: growing segments, rendering, conversion; the Linux AppImage lists them with `list` ([tutorial](https://scrollprize.org/tutorial_VC3D#installing-vc3d)) | As VC3D | tifxyz, renders | In the AppImage or the source build; inside a container without FUSE, prefix with `APPIMAGE_EXTRACT_AND_RUN=1` | Through the app bundle (`/Applications/VC3D.app/Contents/MacOS`, which [`kit doctor`](tools/doctor.md) looks for) | Batch or headless runs on a rented machine |
| [Spiral fitting](https://scrollprize.org/tutorial_spiral) (villa `spiral-fitting/`) | Fits one tifxyz mesh per winding of the whole scroll to patches, winding annotations, normals and tracks; writes `wNNN` and `wNNN_spliced` per winding | Verified patches (tifxyz), annotations, lasagna normals, the scroll's `umbilicus.json` | One tifxyz per winding | `uv sync` in `villa/spiral-fitting`; "Python ≥ 3.14 and an NVIDIA GPU"; cmake and a C++ toolchain for the `vc_spiral` extension ([tutorial](https://scrollprize.org/tutorial_spiral)) | No local fit (NVIDIA GPU required); VC3D's Spiral workspace can drive a fit on a GPU machine over SSH | Whole-scroll unrolling, the Grand Prize route the organizers suggest |
| [Khartes](https://github.com/KhartesViewer/khartes) | "a tool to manually create and visualize segment meshes, while also visualizing a preview of the rendered segment" ([list](https://scrollprize.org/community_projects)) | Volumes in its own project format | Meshes | `conda env create -f environment.yml`, then `python khartes.py` ([README](https://github.com/KhartesViewer/khartes#installation)) | Not stated in the README; it is Python with conda | Careful hand tracing of a small area, with a live render beside it |
| [ScrollFiesta](https://github.com/Hob3rMallow/scrollfiesta_public) | "a C/C++ research pipeline for turning segmented CT surface predictions into registered scroll meshes, textured unrolls, and review artifacts"; `vmesh_tifxyz` exports VC3D tifxyz segments | "a completed surface-probability volume" (it "does not produce or repair one") | Meshes, tifxyz, unroll images | CMake build, Linux and Windows instructions in the README; default path on CPU, optional CubeCL CUDA/HIP backend | Not stated in the README | Automatic meshing of a large region from a surface prediction |
| [vesuvius-automesh](https://github.com/spencerdavis-tx/vesuvius-automesh) | "Automated, QC-gated surface harvest": seed-sweeps the villa tracer and accepts output per 25 mm window under a quality gate | Public surface predictions, CT streamed from S3 | Accepted tifxyz windows and per-window QC records | `uv pip install -e .`, Python 3.10 or newer, plus a VC3D build | Yes: its README's runs were "on a single Apple-silicon Mac", CPU only | Unattended harvesting with every window's pass or fail recorded |
| [scrollreading](https://github.com/WillStevens/scrollreading) | Flood-fill based autosegmentation experiments, one 512 cubed volume at a time, with stitching | Volumes | Surface patches, renders | Python scripts; see the README and reports | Not stated | Research on alternative autosegmentation |
| [ThaumatoAnakalyptor](https://github.com/schillij95/ThaumatoAnakalyptor) | Automatic segmentation from point clouds (part of the 2023 Grand Prize submission) | Volumes | Meshes and renders | Docker with `nvidia-docker2` and `--gpus all` ([README](https://github.com/schillij95/ThaumatoAnakalyptor)) | No (its Docker route needs an NVIDIA GPU) | Reproducing the 2023 pipeline; VC3D is the current tool |

## Check or repair a surface

| Tool | What it checks | Install | Mac |
| --- | --- | --- | --- |
| [`kit tifxyz`](tools/tifxyz.md) (this repository) | Area in cm2, isometry (edge, cell area and angle percentiles), holes, folds and stretched nodes, OBJ export, a shaded picture, which way normals face; a segment on the bucket is fetched once | numpy and tifffile ([how-to](segments-without-vc3d.md)) | Yes |
| [`kit stackcheck`](tools/stackcheck.md) (this repository) | A stack of consecutive segments against the umbilicus: winding order, skipped windings, overlaps, missing sectors | numpy, scipy and tifffile | Yes |
| [`kit uvgate`](tools/uvgate.md) and [`kit overlap`](tools/overlap.md) (this repository) | Overlaps in a flattening's UV triangles; how close two traces of one sheet run | `uvgate`: standard library; `overlap`: numpy, scipy and tifffile | Yes |
| [windcheck](https://github.com/joe-carr-data/windcheck) | Where "a surface trace can pass through itself", from mesh geometry alone | `uv`, Python ([README](https://github.com/joe-carr-data/windcheck#install)) | Not stated |
| [tifxyz-repair](https://github.com/Nieuwlaar/tifxyz-repair) | Validates and repairs tifxyz `meta.json` bounding boxes against VC3D's loader ([villa#1272](https://github.com/ScrollPrize/villa/issues/1272)) | `pip install "tifxyz-repair[deep] @ git+https://github.com/Nieuwlaar/tifxyz-repair"` | Not stated |

## Look at a surface without tracing

| Tool | What it shows | Install |
| --- | --- | --- |
| [vesuvius-gui](https://github.com/jrudolph/vesuvius-gui) | "a single binary GUI to render volumes and segments on-the-fly"; its README says macOS and Windows binaries "should work out of the box" | A release binary |
| [Segment Browser](https://github.com/jrudolph/vesuvius-browser) | "a web-based tool to browse layers and open source ink detection results of all released segments" ([list](https://scrollprize.org/community_projects)) | None (web) |
| [Unroll](https://huggingface.co/spaces/SharpMeow/unroll) (this repository's Space) | Traced windings of public scrolls in 3D, unrolled, with raw CT around any point ([page](tools/unroll.md)) | None (web) |

## Where to start (Interpretation)

- **A first segment:** VC3D from the release page, then the [VC3D tutorial](https://scrollprize.org/tutorial_VC3D), which opens PHerc1447 from the catalog. On a Mac this needs nothing else.
- **No VC3D, just numbers or a picture of a published segment:** [`kit tifxyz`](tools/tifxyz.md) and the [how-to](segments-without-vc3d.md).
- **A whole scroll:** spiral fitting on an NVIDIA machine, with VC3D's Spiral workspace on your laptop driving it over SSH.
- **Before you share a trace:** `kit tifxyz check`, then windcheck for self-intersection; a clean grid still has to be looked at on the CT for sheet switches.

Not covered here: ink detection tools (see [external.md](external.md) and the [reference book](vesuvius-bible/md/21-ink.md)).
