# Meshing and Surface Tracing {#ch-tracing}

> **Chapter summary.** Meshing turns surface predictions into explicit surfaces with connectivity. The lineage runs from manual slice-by-slice tracing in Volume Cartographer (2023), through Khartes, ThaumatoAnakalyptor and patch stitching (2023 to 2024), to the 2026 toolset in VC3D: GrowPatch, Copy Out/In, the Neural Tracer, the Lasagna optimizer and fiber tracing, plus community pipelines such as ScrollFiesta and William Stevens's patch-based unwrapping. All are still described as semi-automated.

## Why meshes

"The purpose of the meshing step is to determine the geometrical connectivity of the scroll. It supplies the necessary information we cannot recover from the voxel grid alone: the ability to say 'this point is next to that point, on the same surface'" [VC-OpenProblems2026]. The analogy given is a faint trail: "The mesh is then a map of the path you've chosen to take, whether right or wrong. If the map is wrong in one place, you'll end up off-course" [VC-OpenProblems2026].

## History

| Period | Approach | Representative tools | Source |
|---|---|---|---|
| 2013 to 2023 | Volume Cartographer, created by Seth Parker at EduceLab for the 2009 scans; first success En-Gedi (2016) | Volume Cartographer | [VC-NewScans2023] |
| 2023 | manual tracing by the segmentation team; faster tracers and viewers | optical-flow segmentation (Julian Schilliger), Khartes (Chuck), VA Sheet Tracer, Volume Viewer, Segment Viewer | [VC-Winners] |
| late 2023 | autosegmentation from point clouds | ThaumatoAnakalyptor (Julian Schilliger) | [VC-GrandPrize] |
| 2024 | volumetric labels; fiber following; patch generation and stitching; first global spiral fit | Khartes3D, napari tools, fiber following (Sean Johnson), patch generation (Hendrik Schilling) | [VC-Winners] [VC-FASP] |
| 2025 | VC3D becomes the team's main tool (Hendrik Schilling's packages, 16-bit Zarr support and new tools in early 2025); ball-and-spring surface growing | VC3D, Will Stevens's ball-and-spring method | [VC-FebProgress2025] [VC-AprilProgress2025] [VC-MayProgress2025] |
| 2026 | normal grids, GrowPatch, Copy Out/In, Neural Tracer, Lasagna; community meshers | VC3D, ScrollFiesta, patch-based unwrapping | [VC-OpenProblems2026] [VC-Winners] |

## VC3D

VC3D, Volume Cartographer 3D [VC-OpenProblems2026], is "our specialized software for virtual unwrapping" [VC-VC3DTutorial]. It visualizes "the CT scans, meshes, and annotations all in one tool", streaming volumes that "can reach dozens of terabytes" from the open-data bucket [VC-OpenProblems2026]. Installation options are a macOS disk image, a Windows installer, a Linux build script and Docker images [VC-VC3DTutorial]. Remote streaming was added by Forrest McDonald [VC-WeAreCooking]. Philip Allgaier's 2025 work restored prebuilt Docker packages and improved stability [VC-MayProgress2025].

A first segment in VC3D takes a few steps [VC-VC3DTutorial]:

1. **File > Open Data Catalog**, select a sample (the tutorial uses PHerc. 1447), **Open Sample**.
2. Navigate: wheel to zoom, right-drag to pan, Ctrl-click or R to move the focus point, Shift plus wheel to move through slices.
3. Ctrl plus right-click, **Create Segment (GrowPatch)**, choose the volume containing "surface", set growth iterations (35 in the tutorial).
4. Inspect the segment under **Volume Package**: "A high quality segment should follow the sheets in the cross-section views, and also have the horizontal and vertical fibers clearly visible in the flattened view".
5. Extend it under **Segmentation > Enable Editing** with keys 1 to 5 (left, up, down, right, all directions), each step "roughly 20 voxels".

## GrowPatch and normal grids

"A GrowPatch-style routine starts from a seed point or an existing patch and extends a local mesh along the predicted surface." It optimizes several objectives at once: "follow the predicted papyrus surface, keep the local geometry smooth, hold mesh spacing to something reasonable, follow whatever local orientation evidence is available, and resist the pull of a nearby sheet it could easily jump onto instead" [VC-OpenProblems2026]. It uses the Ceres nonlinear least-squares solver [Ceres] "inside an iterative growth loop that adds quads progressively and repeatedly re-optimizes an outer fringe". It "works well when the prediction is clean and the layers are separable" but fails "when the prediction topology does not match the real papyrus topology", so "the current system is therefore best described as semi-automated" [VC-OpenProblems2026].

## Copy Out/In and the Neural Tracer

"Once one wrap has been traced well, nearby wraps further in or out may have similar local curvature." Copy Out/In uses an existing mesh as a reference to trace a neighboring wrap; it is "useful as an acceleration tool, not as an unchecked replacement for validation" because errors propagate [VC-OpenProblems2026]. A learned version predicts the displacement to the next wrap; its checkpoint *copy_displacement_latest* was "trained on 2.4 µm data downscaled once" to 4.8 µm and runs in VC3D's Neural Tracer panel [VC-OpenProblems2026]. In March 2026 the Neural Tracer "still does not perform on par with the state of the art", but its training "scales well with the size of the dataset" [VC-WeAreCooking]. In June it was reported to drift and to be slow [VC-HardParts]. Two other neural approaches, an extrapolation mode and neural mesh autoregression on frozen DINO features, are "on hold" because of slow inference and "rollout drift" [VC-OpenProblems2026].

## Lasagna

The Lasagna is "a more flexible optimization framework" that "can better fit complex, curved regions of the scroll, at the expense of being somewhat more computationally intensive" [VC-OpenProblems2026]. It can optimize several stacked sheets jointly ("like the layers of a lasagna. When an annotator corrects one, he corrects all of them"), and make local corrections that move a draft surface toward the true surface while holding user "correction points" fixed [VC-WeAreCooking] [VC-OpenProblems2026]. Surfaces are "a stack of non-intersecting quad-meshes" adjusted in PyTorch to agree with the predicted normal and gradient-magnitude volumes ([Chapter 17](#ch-surface)). The tool was expected to make annotation "at least 3x faster" when complete [VC-WeAreCooking]. By June 2026 it had semi-automated fiber tracing ("2 cm / minute") and inpainting to bridge noisy gaps [VC-HardParts]. Code: villa/lasagna [VC-OpenProblems2026].

## Fibers

"Within each sheet are vascular bundles oriented vertically or horizontally and each one, if perfectly segmented, could be used directly as an individual row or column" of the flattened parameterization [VC-OpenProblems2026]. Fibers are both "a blessing and a curse": they carry geometry, but beam decohesion on fibers also blurs the volume ([Chapter 7](#ch-xray)).

Tools and data:

- the VC3D **line annotation** tool, which adds control points to a fiber with interpolation from Lasagna normals [VC-VC3DTutorial];
- *atlas.py*, which pairs fibers or skeleton annotations and optimizes a patch through them [VC-OpenProblems2026];
- hand-traced skeletons in WebKnossos on the 7.91 µm scans, the *fiber_hz_vt* model trained on them, and **cross-frame training** that maps old annotations to new ESRF scans with an affine transform stored in a *transform.json* sidecar [VC-OpenProblems2026];
- **automated fiber extraction** (Samir Lerognon, September 2026 best submission), which "fine-tunes existing fiber models on data from more scrolls, fits splines to the predicted fibers, and integrates the results with VC3D and the spiral fitter" [VC-Winners];
- a fiber neural tracing model added to VC3D in October 2026 [Recent-2026-10-15].

The open-problems document compares the task to **connectomics**, which traces axons through teravoxel electron-microscopy volumes, and advises that "a tracer that confidently follows fewer fibers correctly is more useful than one that follows more fibers with a higher error rate" [VC-OpenProblems2026].

## Community meshing pipelines in 2026

| Pipeline | Author | Idea | Recognition |
|---|---|---|---|
| ScrollFiesta | Ben Kyles and collaborators | automatic mesher: per-cube meshing, welding, surface parameterization, snapping to raw CT intensity; reads zarr volumes and writes tifxyz patches; integrated with VC3D | $10,000 (May), $20,000 (July), $2,500 (August), $5,000 (September 2026) [VC-Winners] [VC-July2026] |
| Patch-based unwrapping | William Stevens | "detects when the 2D alignments of overlapping patches imply incompatible 3D locations, drops the offending patches, and joins the rest into flattened components", about 365 cm2 on PHerc. 1667 | $20,000 (August 2026) [VC-Winners] |
| PLatS | Houjing Huang | "trains a model to learn an instance embedding of papyrus sheets" | $1,000 (September 2026) [VC-Winners] |
| Assigning patches to windings | Thomas Kelly | assigning surface patches to global windings | $1,000 (September 2026) [VC-Winners] |

Will Stevens's earlier ball-and-spring method grows a mesh by inserting candidate vertices and relaxing it as a mass-spring system; "the resulting per-vertex stress map acts as an intrinsic quality check, clearly exposing layer 'sheet switches'" [VC-AprilProgress2025]. The open-problems document points to ScrollFiesta as an example of the "alternative, scalable meshing algorithms" it wants [VC-OpenProblems2026].

## Speed

The January 2026 report put the VC3D pipeline at "more than 10x faster than a fully manual workflow in the original Volume Cartographer", with sheet-switch fixing as the main remaining manual work [VC-PHerc172Seventy]. Unwrapping PHerc. 172's lower 70 percent produced about 7 m by 14 cm of surface [VC-PHerc172Seventy].
