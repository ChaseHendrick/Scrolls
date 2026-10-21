<a id="ch-spiral"></a>

# The Spiral Fit {#ch-spiral}

> **Chapter summary.** The spiral fit is the main whole-scroll method in 2026. It models the scroll as an ideal Archimedean spiral deformed by a smooth, invertible map (a diffeomorphism), and fits that map to all available evidence: verified patches, fibers, winding annotations, predicted normals and the umbilicus. Its output is one tifxyz mesh per winding; its inverse map is the virtual unrolling. It was introduced by Paul Henderson in 2024, published at WACV 2026, and used in the October 2026 PHerc. 343 first-letters result.

## The idea

"We know the scroll was originally one long rectangular sheet, rolled up into a neat spiral. The eruption of Vesuvius deformed that spiral into the crushed shape we see in the CT scan. Instead of reconstructing the surface piece by piece, we search for the combination of ideal scroll shape and smooth deformation that best explains everything we observe. Once we have those, virtual unrolling comes almost for free" [VC-SpiralTutorial]. A fit of PHerc. Paris 4 produced 130 windings [VC-SpiralTutorial].

The method first appeared in Paul Henderson's FASP submission ([Chapter 11](11-2024.md#ch-2024)) [VC-FASP], and is described in "Virtually Unrolling the Herculaneum Papyri by Diffeomorphic Spiral Fitting" (WACV 2026, arXiv 2512.04927) [Henderson2026]. In 2026 Paul Henderson and Sean Johnson extended it to conform to patches, skeletons and points [VC-HardParts].

## The mathematics

**Ideal scroll.** In cross-section the ideal scroll is an Archimedean spiral with a single free parameter, the winding tightness ω. A point is addressed by the angle θ along the spiral and the height z, and lies at radius [VC-SpiralTutorial]

r(θ) = (ω / 2π) θ,

so each turn moves outward by one sheet spacing ω.

**Deformation.** The damage is modeled as a diffeomorphism, "a smooth, differentiable, invertible map of 3D space". This guarantees that the sheet cannot tear, pass through itself or collapse, and that "any point in the scan maps back to a point on the ideal (i.e. flattened) scroll. That inverse map is the virtual unrolling" [VC-SpiralTutorial]. It is composed of [VC-SpiralTutorial]:

1. a coarse global scale and shear;
2. the integral of a **stationary velocity field** u, the most important part: points follow dφt(x)/dt = u(φt(x)) with φ0(x) = x, and the transform is φ1 (integrated with a few Runge-Kutta steps);
3. a local scaling of the gap between windings.

The same machinery is used in diffeomorphic medical image registration [VC-SpiralTutorial].

**Fitting.** Every input becomes a differentiable loss [VC-SpiralTutorial]:

- points on a same-sheet strip must land on one winding surface;
- two points annotated k windings apart must land exactly k windings apart;
- a verified patch must coincide with a single winding;
- tracks, normals and gradient magnitude nudge orientation and winding density;
- the innermost winding must wrap the umbilicus and the outermost must follow the outer shell;
- regularizers keep the parameterization from distorting.

All parameters are optimized jointly with Adam [Kingma2015] on the weighted sum of losses. Each winding is then sampled on a regular (θ, z) grid and written as a tifxyz mesh [VC-SpiralTutorial].

![Diagram showing an ideal Archimedean spiral on the left, a smoothly deformed spiral on the right, and arrows for the forward map (ideal to scan) and inverse map (scan to flat sheet).](../figures/charts/spiral_diagram.svg)
*Figure 19.1. The spiral prior: an ideal Archimedean spiral r = ωθ/2π and a smooth invertible deformation of it. Diagram by the editors, drawn from the description in [VC-SpiralTutorial]; not derived from scan data. License: CC BY 4.0 (this book).*

## Inputs

| Input | Kind of constraint | How it is made |
|---|---|---|
| Surface patches (tifxyz), preferably verified | same winding | GrowPatch, Lasagna, neural Copy Out/In, other tools |
| Strips and lines of points; fibers | same winding | VC3D point collections and fiber tracing |
| Relative winding annotations | "these two points are exactly one wrap apart" | VC3D point collections |
| Absolute winding annotations | "this patch is on winding 20" | VC3D point collections |
| Normals, gradient magnitude, skeletonized surface tracks | soft volumetric guidance | Lasagna predictions; extract_surface_tracks.py |
| Umbilicus (required); outer-surface mesh (optional) | scroll-level structure | annotation |

Source: [VC-SpiralTutorial]. "Annotations placed where the scroll is most damaged contribute the most" [VC-SpiralTutorial], and "relative winding number annotations seem to have a great impact on the spiral fit" [VC-OpenProblems2026].

## Outputs

- One tifxyz mesh per winding in two variants: *wNNN*, the pure fitted surface, and *wNNN_spliced*, with verified patch geometry spliced in where fit and patch agree [VC-SpiralTutorial].
- A checkpoint, **satisfaction metrics** per input type, and optional overlay images [VC-SpiralTutorial].
- *render_ink.py* groups spliced windings into chunks, SLIM-flattens them, renders them through an ink-prediction volume with *vc_render_tifxyz*, and writes one JPEG strip per chunk (for example *w010-027.jpg*) [VC-SpiralTutorial].
- *get_ink_metrics.py* measures detected ink area and the coherence of columns and lines using the *ink-coverage-32um* model, which "was only trained on PHerc. Paris 4" [VC-SpiralTutorial].

## Running it

The code is in villa/spiral-fitting; the entry point is *fit_spiral.py*. It needs Python 3.14 or later and an NVIDIA GPU; `uv sync` installs dependencies, including PyTorch from the CUDA 12.8 index on Linux and *triton-windows* on Windows, and builds a small C++ extension, *vc_spiral* [VC-SpiralTutorial]. The tutorial warns that torch 2.13 and later "will require significantly more vram" [VC-SpiralTutorial]. Community contributions in 2026 made it run on consumer GPUs, on Windows, and on Apple MPS or CPU [VC-Winners] [Recent-2026-10-15].

## Where to annotate

The tutorial's advice [VC-SpiralTutorial]:

- Think of the scroll "as a set of local shapes glued together", a C here, a J there, "or god forbid a Z". The **complexity of the local shape**, not the number of windings or curvature alone, is "the primary multiplier of annotation density".
- Once a constraint describes a neighborhood, adding more has little benefit.
- **Shears**, where the papyrus has broken and shifted, are hard for a smooth field; annotate heavily on both sides.
- Regular spacing and smooth curvature, long runs of wide gaps, and areas of low curvature "even highly compressed ones" are easier.

## Limits

"Where annotations are sparse or the volume is highly ambiguous, spiral fitting is still under-constrained, and won't necessarily follow the true sheet surfaces" [VC-OpenProblems2026]. In June 2026 it "still does not conform well where annotations" are wrong or missing [VC-HardParts]. The open-problems document asks for "better evaluation suites and loss functions", greater expressivity, fewer needed annotations, and automation of relative-winding annotation [VC-OpenProblems2026].

## A worked example: PHerc. 343

Erwin Nieuwlaar's prize-winning surface came from the open-source spiral fitter "adapted to run on the 8.64 µm scan of PHerc. 343, with his own estimate of the scroll axis (umbilicus)", plus a new method "to snap the segments more accurately to the papyrus surface". The letters lay on windings w047 and w048, joined across θ = 0 [VC-PHerc343].
