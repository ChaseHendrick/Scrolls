<a id="ch-open-problems"></a>

# Open Problems {#ch-open-problems}

> **Chapter summary.** By October 2026 a sealed Herculaneum scroll has been unwrapped and read, but "not without a person checking its output at almost every stage" [VC-OpenProblems2026]. This chapter restates, from the challenge's own open-problems document (last updated 14 October 2026), what is unsolved at each stage, the seven named bottlenecks, the six ways contributors are asked to help, the methods put on hold, and the questions the 2027 Grand Prize is meant to answer. It adds a list of smaller questions drawn from tutorials and prize rules.

## The state of play

The document opens: "We are no longer asking whether a sealed Herculaneum scroll can be read. It can. The next question is how to make the same process work automatically, reliably, and at scale for every scroll" [VC-OpenProblems2026]. It closes with "We can't claim final victory. What's changed is that the bottlenecks are now much clearer."

What is established, in the document's words: a sealed scroll "can be virtually unwrapped and read"; "high-resolution scanning can make previously elusive ink more visible"; "direct volumetric ink segmentation is possible in favorable cases"; "fragment-trained models can generalize far enough to bootstrap scroll-specific reading"; and "semi-automated geometry tools can drastically accelerate tracing, even though human correction remains necessary" [VC-OpenProblems2026].

## Open problems by stage

### Scanning

- **Scan quality is local.** "A scan can hold excellent regions and nearly-impossible-to-unwrap ones in the very same volume" [VC-OpenProblems2026].
- **Compressed regions.** "Densely compressed papyrus scatters the beam into haze that no downstream algorithm may fully undo" ([Chapter 8](08-scans.md#ch-scans)).
- **Three coupled parameters.** Voxel size, energy and propagation distance trade against each other. Too much propagation distance "can turn against you, blurring the volume". The current practical regime (2.4 µm, 22 cm, about 78 keV) "isn't a universal recipe" [VC-OpenProblems2026].
- **Resolution versus data.** 1.1 µm data "yields cleaner results than 2.4 µm data. But scanning at high resolution is impractical"; full scrolls "cannot yet be scanned everywhere at sub-micron resolution in a practical production workflow" [VC-OpenProblems2026].
- **What would help:** "Scan-quality metrics, and scroll-specific acquisition recipes" [VC-OpenProblems2026].

### Unwrapping

- **No connectivity in the data.** The volume "does not tell us which voxels belong to the same sheet" [VC-OpenProblems2026].
- **Topology in hard regions.** "The open question is reaching a high level of topologic accuracy in densely packed regions, regions affected by high curvature or in spots where the papyrus is damaged." Distance-transform targets are suggested as an alternative to binary masks.
- **Holes, mergers, sheet switches.** "A small local error can send a traced mesh onto the wrong wrap entirely, with no easy way to recover" ([Chapter 18](18-tracing.md#ch-tracing)).
- **Fibers.** Wanted: "a tracer that confidently follows fewer fibers correctly", more useful "than one that follows more fibers with a higher error rate."
- **Spiral fit.** "Devise better evaluation suites and loss functions to fit the spiral. Increase its expressivity and reduce the number of needed annotations"; automating relative winding-number annotation "will boost scalability by a great extent" ([Chapter 19](19-spiral.md#ch-spiral)).
- **Label quality.** "Label quality is now one of the main unwrapping bottlenecks"; "a smaller set of precise labels in hard regions may be more useful than a larger set of approximate labels in easy regions" [VC-OpenProblems2026].

### Ink recovery

- **Generalization.** "In some scrolls, predictions improve and then plateau. In others, current models show little or no convincing ink" [VC-OpenProblems2026].
- **Ambiguous failures.** Possible causes listed: weak signal in the scan, a slightly misplaced surface, labels that do not match the true ink location, an architecture that misses the right features, differences in ink morphology or chemistry, or a signal "present but below the current pipeline's ability to use it."
- **Diagnostics.** "Better diagnostics matter just as much as better models" [VC-OpenProblems2026].
- **Depth ambiguity.** Fragment photos give 2D labels; direct 3D ink segmentation is possible only "where possible" ([Chapter 21](21-ink.md#ch-ink)).
- **Telling "no ink" from "no ink recovered yet"** is one of the questions in "What's next" [VC-OpenProblems2026].

### Data scale

- Volumes are "too large for ordinary local workflows"; what would help is "reproducible streaming pipelines and cheaper compute/storage paths" ([Chapter 25](25-compute.md#ch-compute)).
- "Densely labeled 3D training data is the bottleneck. The CT volumes are enormous and trusted voxel-level labels are scarce" [VC-OpenProblems2026].

## The bottleneck table

Reproduced from the open-problems document [VC-OpenProblems2026]:

| Bottleneck | What it means | Current approach | What would help |
|---|---|---|---|
| Compressed or highly curved regions | Some regions lose effective separability between layers. | Better scan regimes, smaller voxel size, shorter propagation distance, phase retrieval. | Scan-quality metrics, and scroll-specific acquisition recipes. |
| No built-in connectivity | CT gives voxels, not sheets or graphs. | Surface prediction plus mesh tracing. | Better geometry priors, fiber tracing, and topology-aware tools. |
| Approximate surface labels | Human-created meshes are useful but not voxel-exact. | Train 3D surface models from approximate annotations. | Label snapping, active learning, self-supervised approaches. |
| Sheet switches | Meshes can jump from one wrap to another. | VC3D inspection and manual correction. | Smarter surface tracing algorithms that avoid introducing sheet switches. |
| Ink depth ambiguity | Fragment photos give 2D labels, not exact 3D ink positions. | Surface-conditioned 3D input with 2D output. | Direct 3D ink segmentation where possible. |
| Cross-scroll generalization | Ink models may work on one scroll but not another. | Fragment training plus scroll-specific pseudo-labeling. | Multi-scroll training, better labels, stronger diagnostics. |
| Data scale | Scroll volumes are too large for ordinary local workflows. | OME-Zarr, chunked processing, cloud storage. | Reproducible streaming pipelines and cheaper compute/storage paths. |

## Six ways to help

The document's six callouts, paraphrased closely [VC-OpenProblems2026]:

| Skill | Problem | Chapter |
|---|---|---|
| ML datasets and models | Labels "better localized on the papyrus' recto", or models that "better preserve the sheets' topology" | [17](17-surface.md#ch-surface) |
| Classical geometry, optimization, C++ | Meshing that avoids "holes, mergers, and sheet switches without a human checking and fixing every traced piece" | [18](18-tracing.md#ch-tracing) |
| 3D annotation, active learning, data quality | Improve surface supervision in the hardest regions | [17](17-surface.md#ch-surface) |
| Classical computer vision, curve following | "Conservative fiber tracing" over long distances | [18](18-tracing.md#ch-tracing) |
| Optimization and evaluation | "Better evaluation suites and loss functions" for the spiral fit; automated priors | [19](19-spiral.md#ch-spiral) |
| 3D deep learning | Direct 3D ink segmentation; self-supervised representations | [21](21-ink.md#ch-ink) |

## Methods on hold

Two neural tracing approaches were put "on-hold" [VC-OpenProblems2026]:

- **Neural tracer, extrapolation mode:** predicts how a surface displaces as it grows beyond its edge, without a neighboring wrap.
- **Neural mesh autoregression:** predicts a continuation of a tifxyz lattice one vertex at a time from frozen 3D DINO features; "a first MVP", not wired into GrowPatch.

Both share two "severe limitations": inference is "slow" at 2.4 µm, and multi-step rollouts "drift" because "small errors compound across steps instead of staying bounded." "Neither problem is solved yet."

## Surface morphology

Appendix B of the document notes that optical profilometry of opened fragments shows "surface shape alone carries usable information for telling inked regions from uninked ones", with detection degrading as lateral resolution is coarsened [Angelotti2026b]. "No single contrast mechanism explains every scroll" ([Chapter 5](05-inks.md#ch-inks)).

## The questions for 2027

"Can we choose scan parameters that preserve useful signals across scrolls? Can we infer surfaces from voxels without months of correction? Can we reduce the dependence on approximate labels, and reliably tell 'no ink' apart from 'no ink recovered yet'? And can we make the whole workflow reproducible enough for collection-scale reading?" The June 2027 Grand Prize is meant "to demonstrate that these questions have a positive answer" [VC-OpenProblems2026] [VC-GP2027].

## Smaller open questions

These are drawn from tutorials and rules, not from a single list:

| Question | Source |
|---|---|
| How to reduce GPU memory needs of spiral fitting with newer torch versions | [VC-SpiralTutorial] |
| How large an ink-model receptive window is safe before the model can "hallucinate" letter shapes | [VC-Prizes2024] [VC-Prizes] |
| How to choose among ink checkpoints that "behave a bit differently on different segments" | [VC-InkTutorial] |
| How to extend first-letters searches to every newly scanned scroll | [VC-Prizes] [VC-PHerc343] |
| How to scan and read "all the remaining 300 scrolls" in the planned "2-3 years" | [VC-MasterPlan] |
