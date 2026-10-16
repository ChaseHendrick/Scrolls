# Data Formats {#ch-formats}

> **Chapter summary.** Volumes are distributed as chunked, multiresolution OME-Zarr; surfaces as tifxyz quad meshes (three float32 TIFFs of x, y and z plus metadata) or OBJ; surface volumes as Zarr or TIFF stacks; labels as binary images; metadata as JSON. The bucket is organized by sample, then volumes, segments and representations. Scan identifiers encode date, voxel size, propagation distance and energy.

## Formats at a glance

| Data type | Represents | Formats |
|---|---|---|
| Volumes | 3D CT reconstruction | OME-Zarr (primary), sometimes TIFF stacks |
| Segment surface volumes | data sampled along a papyrus surface at several depths | OME-Zarr and/or TIFF stacks (00.tif, 01.tif, ...) |
| Surface geometry | 3D sheet and its flattened mapping | OBJ meshes, tifxyz |
| Model outputs | predicted surfaces, ink maps | OME-Zarr (volumetric), TIFF (images) |
| Metadata | provenance, parameters, identifiers | JSON |

Source: [VC-Data].

## OME-Zarr

OME-Zarr "stores large multidimensional arrays in chunks and often at multiple resolutions, letting software read only the region it needs rather than loading an entire scroll" [VC-OpenProblems2026]. It is "the primary distribution format because it is cloud-optimized (chunked, multi-resolution) and supports streaming / partial reads" [VC-Data]. The specification is OME-NGFF [Moore2021]. Practical notes:

- Volumes are pyramids: level 0 is full resolution and each higher level is downsampled (the ink tutorial's native 3D configuration trains "at pyramid level 2 instead of full resolution") [VC-InkTutorial].
- Volumes are stored as OME-Zarr v2; a community catalogue tool includes "working openers for the bucket's OME-Zarr v2 stores under zarr-python 3" [VC-CommunityProjects], and a 2026 progress prize fixed Zarr 3 reading [VC-Winners].
- Volume names include a mask suffix when masked, for example `20250728140407-9.362um-1.2m-113keV-masked.zarr` [VC-InkTutorial].

### Volume identifiers

A catalogue long identifier has the form `YYYYMMDDHHMMSS-<voxel>um-<distance>m-<energy>keV`, for example `20250509053741-8.640um-1.2m-116keV` (PHerc. 9B) [VC-Catalog]. The leading timestamp is the scan or volume identifier used in prize rules (for example the Grand Prize volume `20250521151220` for PHerc. 1447) [VC-Prizes].

### Sizes

Uncompressed size is voxels times bytes per voxel. The catalogue's largest volume, PHerc. Paris 3 at 2.4 µm, has shape 68,417 x 42,403 x 42,403, about 1.23 x 10^14 voxels, roughly 123 TB at one byte per voxel ([Chapter 8](#ch-scans)) [VC-Catalog]. This is why tools stream chunks instead of downloading.

## tifxyz

"The unwrapping software used by our team, VC3D, uses a custom format called 'tifxyz' ... Its key benefit is that it enforces grid topology on the surface mesh, meaning, again, a single flat sheet" [VC-OpenProblems2026].

- **Structure:** "a 2D array of 3D vertex coordinates: the array's shape determines the mesh's grid structure, and the vertices define its actual shape in space" [VC-OpenProblems2026].
- **Files:** "three separate TIFF images, one each for x, y, and z coordinates (as float32)", with a meta.json [VC-OpenProblems2026] [VC-InkTutorial].
- **Missing cells:** "either by setting each coordinate to -1 or via an optional sidecar mask image" [VC-OpenProblems2026].
- **Code:** QuadSurface in C++ (QuadSurface.cpp); `vesuvius.tifxyz.Tifxyz` and `read_tifxyz()` in Python [VC-OpenProblems2026].
- **Conversion:** `vc_tifxyz2obj` and `vc_obj2tifxyz`; going from OBJ to tifxyz "requires an accompanying .griduv sidecar file specifying the intended grid structure" [VC-OpenProblems2026].

A minimal tifxyz folder [VC-InkTutorial]:

```
w00_20231016151002/
  x.tif   y.tif   z.tif   meta.json
```

The 2027 prize rules require submissions as tifxyz meshes with a low-distortion flattening included, one per column, named `column_01.tifxyz`, `column_02.tifxyz` and so on [VC-Prizes].

## Bucket layout

```
{SAMPLE_ID}/
  volumes/          # 3D reconstructed volumes (OME-Zarr, sometimes TIFF)
  segments/         # meshes, surface volumes, optional ink results
  representations/  # derived artifacts such as predictions
```

Source: [VC-Data]. A segment path from the ink tutorial: `PHerc0139/segments/20260317000000-w035_2026031718/mesh/20260317000000-on-20250728140407-9.362um.tifxyz/` [VC-InkTutorial].

## metadata.json

The catalogue is a JSON document with `samples` and `models`. Each sample lists photographs, scans with parameters (voxel size, energy, detector distance, location, beamline), volumes with shapes, segments and affine **volume_transforms** between volumes of the same sample (for example from the 2023 Diamond volume of PHerc. Paris 4 to its 2026 ESRF volumes) [VC-Catalog]. This book's data/catalog_*.csv files were extracted from it.

## Labels and masks

Ink training segments use binary label images and **supervision masks** (only masked pixels contribute to the loss), with optional **validation masks**; prefixes must match the segment folder name exactly [VC-InkTutorial]. Labels are edited as TIFF or PNG and converted with `create_label_zarrs` [VC-InkTutorial].

## Spiral-fit inputs

The *spiral-input* dataset (July 2026) is organized by scroll and contains verified and unverified patches, line annotations, point collections, same, relative and absolute winding graphs, the fitted umbilicus and outer-shell geometry. For PHerc. Paris 4 it has "~27,000 verified and ~204,000 unverified surface patches" and is "~49.6 GB total" [VC-Datasets]; the spiral tutorial labels the download "~90 GB" [VC-SpiralTutorial], so the figure depends on what is included.

## Legacy formats

- **volpkg:** Volume Cartographer's volume package directory, used on the legacy server (for example `full-scrolls/Scroll1/PHercParis4.volpkg/`) [VC-Catalog]; VC3D also streams remote volpkg folders [VC-WeAreCooking].
- **.nrrd** cubes in the 2024 volumetric instance labels dataset [VC-Datasets].
- **Fiber skeletons** in WebKnossos NML, convertible to CSV, JSON and SWC by a 2026 community tool [VC-GP2027].

## Citing data

New scans: "Vesuvius Challenge - CT Scans of Herculaneum Papyri", with the author list given on the data page. Scrolls 1 to 4 and Fragments 1 to 6 scanned at Diamond before 2025: cite EduceLab-Scrolls (Parsons et al. 2023) and state that data "were obtained from the EduceLab-Scrolls dataset" [VC-Data] [Parsons2023].
