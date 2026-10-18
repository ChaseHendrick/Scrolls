# Synchrotrons and Scan Campaigns {#ch-scans}

> **Chapter summary.** The Herculaneum scrolls have been scanned at two synchrotrons: the Diamond Light Source in Oxfordshire (beamline I12, from 2019 to 2025) and the European Synchrotron (ESRF) in Grenoble (beamlines BM18 and ID11, from 2025). The public open-data catalog lists 67 scans of 45 samples. This chapter describes the facilities, the logistics of a scan session, and every campaign represented in the public data, with voxel sizes, energies and distances.

## What a synchrotron is

A synchrotron is a particle accelerator that keeps electrons circulating at nearly the speed of light in a storage ring. When magnets bend their path, the electrons emit **synchrotron radiation**: intense, highly collimated light from the infrared to hard X-rays [WP-SynchrotronRadiation]. Experimental stations called **beamlines** branch off the ring. For tomography of scrolls the key properties are high flux (short scans at fine resolution), a choice of monochromatic energies, and, at fourth-generation sources, high spatial coherence, which strengthens propagation-based phase contrast ([Chapter 7](#ch-xray)) [VC-SummerHaze].

## Diamond Light Source

Diamond is the United Kingdom's national synchrotron, at the Harwell Science and Innovation Campus in Oxfordshire. It is a 3 GeV medium-energy machine with 32 beamlines; it produced its first user beam in January 2007 and was formally opened in October 2007. Construction cost £260 million, covering the synchrotron building, accelerators, the first seven beamlines and the adjacent office block, Diamond House [WP-Diamond]. Herculaneum scans there were made on beamline **I12**, whose optical modules 2 and 3 give pixel sizes of 7.91 µm and 3.24 µm [VC-NewScans2023].

> **Photograph (not stored in git; see the caption for source and license):** A panoramic view inside the Diamond synchrotron building, showing the curved experimental hall and beamline hutches.
*Figure 8.1. Inside the Diamond Light Source synchrotron building (2018). Photo: Prosthetic Head, via Wikimedia Commons. License: CC BY-SA 4.0. <https://commons.wikimedia.org/wiki/File:Diamond_Inside_Panorama.jpg>*

> **Photograph (not stored in git; see the caption for source and license):** Diamond House, a modern office building with glass and gray panels at the Diamond Light Source site.
*Figure 8.2. Diamond House, the office building of the Diamond Light Source synchrotron. Photo: Sintakso, via Wikimedia Commons. License: CC BY-SA 4.0. <https://commons.wikimedia.org/wiki/File:Diamond-House.jpg>*

## The European Synchrotron (ESRF)

The ESRF in Grenoble, France, is a joint facility supported by 19 countries. Inaugurated in 1994 as the world's first third-generation synchrotron, it has an 844 m storage ring operating at 6 GeV and 46 beamlines. Its Extremely Brilliant Source (EBS) upgrade, built from 2018 to 2020, made it the first fourth-generation high-energy synchrotron, with X-ray intensity improved by a factor of 100; it reopened to users on 25 August 2020 [WP-ESRF]. **BM18** is a beamline "specifically designed to harness the coherence of a 4th generation synchrotron for phase-contrast X-ray tomography" of large objects [VC-SummerHaze]. **ID11** was used for the 0.55 µm region-of-interest scan of a fragment in July 2025 [VC-CompressedRegions].

> **Photograph (not stored in git; see the caption for source and license):** The Grenoble valley seen from the Moucherotte, with the ESRF ring at the confluence of the rivers in the center and the Chartreuse massif behind.
*Figure 8.3. The Grenoble valley with the European Synchrotron in the center and the Massif de la Chartreuse in the background (December 2020). Photo: Marco Cammarata, via Wikimedia Commons. License: CC BY-SA 4.0. <https://commons.wikimedia.org/wiki/File:Esrf_chartreuse_01.jpg>*

## Preparing a scroll for the beam

Scanning a Herculaneum scroll is a logistics project. The steps described by the Vesuvius Challenge and EduceLab [VC-NewScans2023] [VC-ScanningAtScale]:

1. **Selection and photogrammetry.** In Naples, conservators and scientists select scrolls and photograph each one on a rotating platform with a known scale, producing an accurate 3D model of its exterior.
2. **Case design.** From the model, a form-fitting case is designed and 3D printed (in 2023, Nylon 12 by HP Multi Jet Fusion). The scroll is wrapped in PTFE (Teflon) relic wrap inside it and stays in the case for transport and scanning.
3. **Transport.** Cases travel in foam-lined hard cases. In September 2023 storms grounded commercial flights from Naples; Nat Friedman chartered a private plane so the scrolls reached Diamond in time for the scan slot [VC-NewScans2023].
4. **Mounting and settling.** At the facility the case is mounted vertically and allowed to settle before imaging, because shifting during a multi-hour scan would blur the data.
5. **Grid scanning.** Large scrolls exceed the field of view, so they are scanned in overlapping grids ("double-double" scans): centered, rotated 180 degrees, offset, lowered and rotated again, with the parts stitched into full projections. Scrolls taller than the stage travel are scanned in parts using a manual lab jack [VC-ScanningAtScale]. Scrolls 1 and 2 were each scanned in two overlapping halves for this reason [VC-NewData2024].
6. **Reconstruction.** Projections are reconstructed into slices by filtered back-projection. In 2023 a reproducible reconstruction pipeline, run right after each scan, replaced the 2019 workflow in which the team waited days or weeks to see the first slices [VC-NewScans2023].

## Campaigns

The table summarizes the campaigns visible in the public record. Facility and beamline for scans in the open-data catalog are taken from the catalog metadata; counts are numbers of catalog scans, not physical scrolls.

| Period | Facility, beamline | Samples | Voxel sizes | Energies | Notes | Source |
|---|---|---|---|---|---|---|
| 2009 | laboratory micro-CT (Paris) | PHerc. Paris 4 and another roll | 23.94 µm (Paris 4) | 70 kV | no ink visible | [Parsons2023] [WP-HercPapyri] |
| 2019 | Diamond, I12 | Scrolls 1 and 2 (PHerc. Paris 4, Paris 3), fragments | 7.91 µm (scrolls); 3.24 µm (fragments) | 54 keV (and 88 keV for fragments) | data of the 2023 challenge; catalog timestamps for these volumes are dated February 2023 | [Parsons2023] [VC-NewScans2023] [VC-Catalog] |
| Sept to Oct 2023 | Diamond, I12 | PHerc. 332, PHerc. 1667, two fragments, carbon phantom | 7.91 and 3.24 µm | 53, 70, 88, 105 keV | eight volumes per main sample | [VC-NewScans2023] |
| Oct 2024 | Diamond | PHerc. 172 (Scroll 5, Bodleian) | 7.91 µm | 53 keV | visible ink; First Title | [VC-Catalog] |
| Apr 2025 | Diamond | 20 scrolls in one session | not stated in post | | test of "productionized" scanning | [VC-ScanningAtScale] |
| May 2025 | ESRF, BM18 | 18 catalog scans (scrolls and fragments PHerc. 9B, 343P, 500P2) | 8.64 µm; 2.215 µm; 4.317 µm | 111 to 116 keV | first BM18 batch | [VC-SummerHaze] [VC-Catalog] |
| Jul 2025 | ESRF, BM18 | 21 catalog scans | 9.362 µm; 2.403 µm | 113 keV; 77 keV | 9 µm survey and 2.4 µm scans | [VC-Catalog] |
| Jul 2025 | ESRF, ID11 | PHerc. 500P2 region | 0.55 µm | 65 keV | explains compressed-region haze | [VC-CompressedRegions] [VC-Catalog] |
| Dec 2025 | ESRF, BM18 | 13 catalog scans | 2.399 µm; 1.129 µm | 78 keV; 59 keV | includes PHerc. 1667, 139, 814 | [VC-Catalog] |
| Mar 2026 | ESRF, BM18 | PHerc. Paris 3 and Paris 4 | 2.4 µm; 1.129 µm; 45.532 µm overview | 78, 137 keV; 74, 110 keV | the Scroll 1 rescan | [VC-Catalog] [Angelotti2026a] |

**Unverified.** The April 2025 Diamond session is reported in the Vesuvius Challenge newsletter but its scans do not appear, under that date, in the open-data catalog consulted on 15 October 2026. Whether they were released under different dates or are still being processed is not known to the editors.

![Scatter plot of public scans: voxel size on a log axis against scan date, colored by facility, with marker size showing X-ray energy.](../figures/charts/scans_timeline.svg)
*Figure 8.4. Every scan in the public open-data catalog by date and voxel size, colored by facility. Chart by the editors. Data: data/catalog_scans.csv (from the Vesuvius Challenge open-data catalog, metadata.json, retrieved 15 October 2026). License: CC BY 4.0 (this book).*

![Scatter plot of X-ray energy against voxel size for all public scans, showing clusters at 7.91 micrometers and 53 keV (Diamond), 8.6 to 9.4 micrometers at 111 to 116 keV, and 2.4 micrometers at 77 to 78 keV (ESRF).](../figures/charts/scans_energy_voxel.svg)
*Figure 8.5. Energy versus voxel size for every public scan. The clusters correspond to the regimes in Chapter 7. Chart by the editors. Data: data/catalog_scans.csv. License: CC BY 4.0 (this book).*

## Throughput

The 2025 plan reported that by "pioneering cutting-edge X-ray scanning techniques, such as tetra-, hexa-, and octa-helical acquisitions on the BM18 beamline at ESRF, we can now scan a large scroll at 9.2 µm pixel size in under two hours. This more than halves the scan time compared to our previous sessions, while also improving effective resolution. More than thirty scrolls have been scanned under varied setups" [VC-MasterPlan]. The stated long-term aim is to scan the roughly 300 extant scrolls, mostly in Naples, and the plan estimates that scanning and reading the remainder could take two to three years once unwrapping and ink detection generalize [VC-MasterPlan].

## Sizes of the largest volumes

The open-data catalog records the array shape of each volume. The largest public volumes are the 2026 BM18 scans at 2.4 µm. Their bounding arrays, at one byte per voxel, are on the order of 10 to 120 TB before compression and masking:

| Sample | Volume | Voxel | Array shape (z, y, x) | Uncompressed size at 8 bits |
|---|---|---|---|---|
| PHerc. Paris 3 | 2026 BM18 | 2.400 µm | 68,417 x 42,403 x 42,403 | about 123 TB |
| PHerc. Paris 4 | 2026 BM18 | 2.400 µm | 75,784 x 32,693 x 32,693 | about 81 TB |
| PHerc. Paris 4 | 2026 BM18 | 1.129 µm | 59,969 x 36,006 x 32,354 | about 70 TB |
| PHerc. 139 | 2025 BM18 | 2.399 µm | 76,953 x 26,511 x 26,511 | about 54 TB |
| PHerc. MAN B | 2025 BM18 | 2.399 µm | 72,681 x 26,723 x 26,723 | about 52 TB |
| PHerc. 814 | 2025 BM18 | 2.399 µm | 74,568 x 23,891 x 23,891 | about 43 TB |

Source: [VC-Catalog] (shape field); sizes are the product of the shape, not the stored size. Volumes are distributed as masked, compressed OME-Zarr, so the stored size is much smaller; the bounding box also includes empty space around the scroll. See [Chapter 25](#ch-compute) for storage and compute.

## Licenses of the scan data

Scan volumes in the open-data catalog carry one of two licenses: **CC BY-NC 4.0** (67 volumes, including all ESRF data) or the **EduceLab Data License** (7 volumes, the older Diamond data) [VC-Catalog]. Publication of hidden text derived from the data is additionally governed by the Vesuvius Challenge data agreement ([Chapter 28](#ch-ethics)). This book reproduces no images derived from the scan data.
