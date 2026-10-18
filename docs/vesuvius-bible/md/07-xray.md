# X-ray Tomography for Carbonized Papyrus {#ch-xray}

> **Chapter summary.** A CT scan does not deliver sheets or text; it delivers a three-dimensional grid of voxels, each holding an intensity. For carbonized papyrus with carbon ink, absorption contrast is weak, so the method depends on phase contrast, on resolution and on careful choice of three coupled parameters: voxel size, X-ray energy and the distance from sample to detector. This chapter explains the physics at the level needed to understand scan metadata and the trade-offs in the data.

## From projections to voxels

X-ray computed tomography (CT) records hundreds to thousands of X-ray projection images of an object from different angles, usually by rotating the object through 360 degrees between a fixed source and a fixed detector, and then combines them with a reconstruction algorithm into a three-dimensional volume [VC-Tutorial] [WP-MicroCT]. The volume is a grid of **voxels** (volume pixels). The voxel size is the physical edge length of each cube; the value stored is the local intensity of the reconstruction (often loosely called "radiodensity") [VC-Tutorial].

> **Photograph (not stored in git; see the caption for source and license):** Schematic of tomography: an object containing several shapes is projected from different directions onto detector planes, and the projections are combined to reconstruct the object.
*Figure 7.1. The basic principle of tomography: projections of an object from different directions (S1, S2) are combined to reconstruct its interior. Illustration: Dtrx, via Wikimedia Commons. License: CC BY-SA 3.0 DE. <https://commons.wikimedia.org/wiki/File:TomographyPrinciple_Illustration.png>*

When the voxel size is in the micrometer range the technique is called **micro-CT**. The first X-ray microtomography system was built by James C. Elliott in the early 1980s; its first published images had pixels of about 50 µm [WP-MicroCT]. Scroll scans in this book range from 45.5 µm (overview scans) to 0.55 µm (a small region of interest) ([Chapter 8](#ch-scans)).

A scan is often delivered as a **TIFF stack**: one image per horizontal slice, typically from the bottom of the scroll upward. At 10 µm voxel size, 100 slices cover 1 mm of the object [VC-Tutorial]. Modern distributions use chunked, multiresolution **OME-Zarr** instead ([Chapter 23](#ch-formats)).

The Vesuvius Challenge's 2026 overview emphasizes what the scan does *not* contain: "We do not get sheets. We do not get a mesh, a graph, or a map of which layer connects to which. We get a 3D grid of voxels" [VC-OpenProblems2026]. Everything downstream, from surface prediction to ink detection, is an attempt to infer structure that the scan only implies.

## Attenuation contrast

As X-rays pass through matter they are absorbed and scattered. Materials that absorb more appear brighter in a reconstructed CT slice. This **attenuation contrast** separates papyrus from air very well. It separates carbon ink from carbonized papyrus very poorly, because both are mostly carbon of similar density [VC-OpenProblems2026] [VC-Tutorial5]. Exceptions are inks that contain heavier elements such as lead ([Chapter 5](#ch-inks)): heavier elements absorb much more strongly, which is why some scrolls show ink "by eye" [VC-Scroll5News].

Absorption depends on energy. Lower energies increase absorption contrast but penetrate less; higher energies penetrate thick objects but flatten contrast. Absorption also jumps at element-specific edges: lead's K edge at 88.0045 keV is where its mass attenuation coefficient rises from 1.910 to 7.683 cm2/g [NIST-Pb].

## Phase contrast

X-rays are waves. Passing through matter also shifts their phase, by an amount that depends on the refractive index of the material. As the wavefront travels from the sample to the detector it interferes with itself, producing fringes at interfaces between materials. These fringes act as natural edge enhancement: **propagation-based phase contrast** [VC-OpenProblems2026].

Phase contrast is especially valuable for objects with weak attenuation contrast, like carbonized scrolls. A computational step called **phase retrieval** converts the fringes into a higher-contrast reconstruction; the Paganin algorithm is a common choice. Phase retrieval trades a little effective resolution for more contrast, which seems to help segmentation; its effect on ink detection was still being studied in 2025 [VC-OpenProblems2026] [VC-CompressedRegions]. The 2.4 µm Scroll 1 data were reconstructed with Paganin phase retrieval with a delta-to-beta ratio of 1000 [Angelotti2026a].

![Diagram of propagation-based phase-contrast imaging: a synchrotron beam passes through the scroll, propagates a distance, and forms fringes on the detector; three control knobs are voxel size, energy and distance.](../figures/charts/phase_contrast_diagram.svg)
*Figure 7.2. Schematic of propagation-based phase-contrast CT and the three coupled scan parameters. Diagram by the editors after the description in [VC-OpenProblems2026]. License: CC BY 4.0 (this book).*

## Three coupled parameters

The 2026 open-problems overview identifies three parameters that matter most [VC-OpenProblems2026]:

| Parameter | Meaning | Why it matters |
|---|---|---|
| Voxel size | physical size represented by each voxel | smaller voxels preserve finer structure but increase scan time, reconstruction difficulty and data size |
| X-ray energy | energy of the incident photons | affects penetration, contrast and phase behavior |
| Sample to detector distance | propagation distance after the sample | controls how phase fringes develop before detection |

More phase contrast is not always better. Pushing the propagation distance too far blurs the volume. The balance, in the words of the overview, is "enough phase contribution to reveal useful structure; not so much that the scan becomes dominated by haze ...; enough X-ray energy to penetrate the object and separate layers; not so much that useful absorption contrast disappears; and voxels small enough to resolve the structures that matter, without shrinking so far that scanning a full scroll stops being practical" [VC-OpenProblems2026].

### Working regimes

| Regime | Voxel | Distance | Energy | Status | Source |
|---|---|---|---|---|---|
| Recent full-scroll scans (ESRF BM18) | about 2.4 µm | 22 cm | about 78 keV | current practical recipe | [VC-OpenProblems2026] |
| Earlier "optimal" low-resolution regime | about 9 µm | 1.2 m | about 110 keV | widely used in 2025 | [VC-OpenProblems2026] |
| Best small-pixel result for a fragment ROI (ESRF ID11) | 0.55 µm | 7 cm | 65 keV | region of interest only | [VC-CompressedRegions] |
| Best 2.4 µm fragment result | 2.4 µm | 22 cm | 77 keV | | [VC-CompressedRegions] |
| Original Diamond scans of Scrolls 1 and 2 | 7.91 µm | not recorded in catalog | 53 to 54 keV | 2023 Grand Prize data | [Parsons2023] [VC-Catalog] |

Angelotti and colleagues give rough guides: about 0.5 m at 4.6 µm and 2 m at 8 µm are acceptable distances, with a "sweet spot" near 8 µm at 100 to 120 keV and about 3 m [Angelotti2026a]. The August 2025 recipe was: pixel size as small as feasible; distance short enough to enhance phase contrast without letting scattering dominate (generally under 1 m and less than half the near-field limit); energy as low as possible to boost absorption, within the constraints of the other two [VC-CompressedRegions].

**On energy, sources differ.** Parsons and colleagues report anecdotal evidence that lower energy works better for carbon ink [Parsons2023]; Angelotti and colleagues favor higher energy and shorter distance to fight decoherence [Angelotti2026a]. These need not conflict: the first concerns absorption contrast, the second phase decoherence.

## Compressed regions and haze

For years, some regions of scroll scans looked worse than their nominal resolution: blurred, "foggy" or "mushy", with adjacent sheets hard to separate. Scans of a fragment region at 0.55 µm on ESRF beamline ID11 in July 2025 gave an explanation [VC-CompressedRegions] [VC-OpenProblems2026]:

- Carbonized papyrus fibers contain small internal cavities: each fiber is surrounded by a thick wall of cells with hollow lumens.
- Carbonized fibers are probably close to graphite, a strong decoherer that scrambles the X-ray wavefront.
- Where many fibers are densely packed, as in closely spaced sheets, these periodic micro-structures scatter the beam slightly, and the longer the beam travels through them before reaching the detector, the stronger the effect.
- The result is a local haze that degrades exactly the most compressed parts of a scroll.

The practical remedies are smaller voxels (ideally below the periodicity, under 1 µm, which is impractical for whole scrolls), shorter propagation distances, and an energy balanced between penetration and absorption [VC-CompressedRegions]. Scan quality is therefore **local**: "A scan can hold excellent regions and nearly-impossible-to-unwrap ones in the very same volume" [VC-OpenProblems2026].

## The curse of dimensionality

Halving the voxel size multiplies the number of voxels for the same physical volume by eight. Going from 8 µm to 2 µm multiplies it by 64; from 8 µm to 0.55 µm by about 4,096 [VC-OpenProblems2026] [VC-CompressedRegions]. Small regions can be scanned at very high resolution; "full scrolls cannot yet be scanned everywhere at sub-micron resolution in a practical production workflow" [VC-OpenProblems2026].

![Line chart on log-log axes showing how the number of voxels per cubic centimeter grows as voxel size decreases from 45 micrometers to 0.55 micrometers, with the scan sizes used for Herculaneum scrolls marked.](../figures/charts/voxel_scaling.svg)
*Figure 7.3. Voxels per cubic centimeter (and bytes at 8 bits per voxel) as a function of voxel size, with the voxel sizes of Herculaneum scans marked. Chart by the editors; the scaling law is from [VC-OpenProblems2026]. Data: data/voxel_scaling.csv. License: CC BY 4.0 (this book).*

| Voxel size (µm) | Voxels per cm3 | Relative to 7.91 µm | Bytes per cm3 at 8 bits |
|---|---|---|---|
| 45.532 | 10.6 million | 0.005x | 10.6 MB |
| 9.362 | 1.22 billion | 0.60x | 1.2 GB |
| 7.91 | 2.02 billion | 1x | 2.0 GB |
| 3.24 | 29.4 billion | 14.6x | 29 GB |
| 2.4 | 72.3 billion | 35.8x | 72 GB |
| 1.129 | 695 billion | 344x | 695 GB |
| 0.55 | 6.01 trillion | 2,975x | 6.0 TB |

This is arithmetic (voxels per cm3 = (10,000 / voxel size in µm) cubed). The November 2023 announcement of the 3.24 µm data noted that it has "about 15 times more pixels per cm3 than 7.91 µm", consistent with the 14.6x in the table [VC-NewScans2023].

## What resolution buys

Smaller voxels help in several ways: they preserve finer papyrus structure; they are less affected by haze; they reduce ambiguity between adjacent layers; they may preserve more of the ink morphology; and they give cleaner absorption and phase contrast [VC-OpenProblems2026]. Early analyses by contestants in 2023 showed a large effect of 3.24 versus 7.91 µm on fragment-trained ink detection [VC-NewScans2023]. Scans of Scroll 1 at 1.129 µm showed cleaner ink than at 2.4 µm [VC-OpenProblems2026].

Resolution is not the whole story. The open-problems overview stresses that a failure to recover ink "doesn't necessarily mean the signal isn't there. It may be absent, or it may be present but not yet exploitable by the current surface placement, labels, model architecture, or training data" [VC-OpenProblems2026].

## Other non-destructive methods

| Method | What it gives | Limitation | Source |
|---|---|---|---|
| Laboratory micro-CT | internal structure | ink invisible for carbon ink; 23.94 µm for Scroll 1 in 2009 | [WP-HercPapyri] [Parsons2023] |
| Infrared photography (about 950 nm) | ink on exposed surfaces | surface only | [WP-HercPapyri] |
| Shortwave-infrared hyperspectral imaging (1,000 to 2,500 nm) | better ink contrast on opened papyri | surface only | [WP-HercPapyri] |
| X-ray fluorescence (XRF), macro XRF | element maps (lead in ink, lead ruling lines) | surface or near surface | [Brun2016] [Tack2016] [Romano2023] |
| Pulsed thermography | sheet joins (kolleseis) and overlaps in opened fragments | fragments | [Ceccarelli2025] |
| Confocal profilometry | surface topography | fragments; resolution dependent | [Angelotti2026b] |
| Structured-light 3D scanning (Artec Space Spider) | surface shape of PHerc. 118, 2018 | surface | [WP-HercPapyri] |
