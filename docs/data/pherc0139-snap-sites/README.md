# PHerc0139 two-scan recto face positions at 108 snap development sites

Chase Hendrick, 3 November 2026. License CC BY-NC 4.0, derived from Vesuvius Challenge open data (CC BY-NC 4.0); please credit Chase Hendrick.

A small table of surface geometry from CT: label vertex positions, their normals, and where the recto face of the papyrus lies along each normal according to two other scans of the same scroll. No CT voxels, renders, meshes, ink labels or ink maps; nothing here is about ink. It was prepared for A.Q. Snyder, author of [scroll-label-snap](https://github.com/aqsnyder/scroll-label-snap), and this is the public copy, byte for byte the same three data files.

Claim labels ([NOVELTY.md](../../NOVELTY.md)): the input vertices and the volume ids are Sourced facts (the open-data bucket, read in October and November 2026); the two-scan face offsets and every snap placement are Model output (measured geometry, not a reading); the hit rates below are development numbers on spent sites.

Tool pages: our snapper is [labelsnap](../../tools/labelsnap.md) (`python -m kit labelsnap`), which made the [Snapped Labels](../../tools/snapped-labels.md) dataset with [finesnap](../../tools/finesnap.md); its held-out tests are in `label_snap_checks` of [`results.json`](../../results.json).

## Files

| File | Rows | Bytes | What |
| --- | --- | --- | --- |
| `pherc0139_twoscan_vertices.csv` | 972 | 140,574 | one row per evaluated vertex (108 sites x 9) |
| `pherc0139_twoscan_vertices.json` | 972 | 589,238 | the same rows under `vertices`, plus a `sites` list (with each mesh's tif SHA-256) |
| `pherc0139_twoscan_sites.csv` | 108 | 22,686 | one row per site |

SHA-256: `14fb0a7c5a0bd3623bad9c80ab87b8b2d78e4e6a656f73940813cf92beb336a7` (vertices CSV), `e37d7d7d77613cefb7c530a61ad6a39aa03abe81615f22ff31ff3b0ba5e9ec94` (vertices JSON), `81254090194587329c7b8393ce8fe5af5f8ce10b3a79bf498df6e72df1526cb6` (sites CSV).

## Volume and input surface

- Volume: PHerc0139 `20250728140407` (9.362 um, 113 keV), level 0: `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr`. Every site uses this volume.
- Input surface: the published PHerc0139 segment label meshes (tifxyz in the 20250728140407 frame) of windings w023 to w029, w031 to w034 and w036 to w038 only. `input_surface` in the sites file is the mesh path under `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/`.
- Each site is a 13 x 13 vertex crop of that mesh around (`mesh_row`, `mesh_col`); the 9 rows per site are its central 3 x 3 block, `k` = 3 * (row offset) + (col offset), so `k = 4` is the site center. `mesh_row`, `mesh_col` index the tifxyz arrays directly.
- `z, y, x`: the vertex as stored in the tifxyz, in voxels of the volume above (level 0, zyx order).
- `nz, ny, nx`: unit normal, `cross(d/dcol, d/drow)` of the mesh grid (central differences on the crop), the same grid normal scroll-label-snap uses.
- z runs from 3736 to 5096.

## Truth: the two-scan face

The recto face is measured on two other scans of PHerc0139, each registered to the label scan per site:

- `face_1129_offset_vx`: the 1.129 um scan (volume `20260413113053`), mapped by the transform stored in the open-data catalog.
- `face_roi2_offset_vx`: the ROI2 scan (volume `20260319133554`, 2.403 um, 77 keV), mapped by Forrest McDonald's published ufsm registration field (`https://dl.ash2txt.org/community-uploads/forrest/volcomp/PHerc0139/transforms/20260319133554_to_20250728140407/`).

Along each vertex's normal, each scan's profile is registered to the label scan's profile by a shift (leave-band-out fit), and its face is the half-level crossing (sigma 1 smoothing) on the recto side of the band nearest the published label. Offsets are in 9.362 um voxels along the normal, measured from the input vertex, empty where that scan names no face.

- `covered` = 1 when both scans name a face and they agree within 1 voxel. 601 of the 972 vertices are covered, on 95 sites.
- `face_offset_vx`: the consensus, the mean of the two offsets; empty when not covered.
- `face_2399_offset_vx`: for reference only, the face on the 2.399 um scan (volume `20260102150214`), which is not part of the truth. It lies within 1 voxel of the consensus on 0.967 of covered vertices.

Where both scans name a face (698 vertices) they agree within 1 voxel on 0.861, median gap 0.31 voxels. Shifting the 1.129 um face by +1.5 or -1.5 voxels drops that agreement to 0.192 and 0.064, so the truth resolves about 1 voxel. ROI2 and the 1.129 um scan differ in energy (77 against 59 keV); ROI2 shares a modality with the 2.399 um scan.

## Sign conventions

- An offset `o` means the face is at `p + o * n` (p the input vertex, n the normal).
- `recto_sign` is +1 or -1 along the normal: the recto face lies on the `recto_sign * n` side of the sheet. Stepping from the recto face along `recto_sign * n` goes into the gap the recto faces; stepping along `-recto_sign * n` goes into papyrus. It equals scroll-label-snap's `normal_sign` (+1: papyrus to gap along the grid normal). It comes from the umbilicus: the recto faces the scroll axis. At all 972 vertices here the normal points away from the axis, so `recto_sign` is -1 everywhere.
- `recto_sign * face_offset_vx` > 0 means the published label sits inside the sheet. Its median over covered vertices is +1.66 voxels.

## Placements (optional columns)

Each `*_x` is that method's move along the normal from the input vertex, in voxels (empty if it gave no position):

- `labelsnap_x`: our single-scan snapper, [kit labelsnap](../../tools/labelsnap.md) (`label_snap` in `kit/labelsnap.py`, defaults; recto target). `labelsnap_abstain` = 1 where it chose not to vouch for the vertex (226 of 972).
- `lsnap_x`, `lsnap0_x`, `lsnap0e_x`: A.Q. Snyder's [scroll-label-snap](https://github.com/aqsnyder/scroll-label-snap) at commit `347ea5b4`, unmodified, run on each 13 x 13 crop with a CT box of the crop plus 28 voxels: default `Params()`, `convention_offset 0`, and `convention_offset 0` with `template_weight 0`. `lsnap_normal_sign_used` (sites file) is the `normal_sign` passed, the site's mean; it matches `recto_sign` at every vertex. `lsnap_default_convention_offset` is the convention the default run estimated.
- `m7_x`: a snap to the organizers' m7 surface prediction from the open data.

The published label itself is x = 0.

## Hit metric

A placement at x is a hit on a covered vertex when `|x - face_offset_vx| <= 1` and `|x| <= 16`. Uncovered vertices are never scored. Recomputed from the CSV with the snippet below (Model output, development sites):

| Placement | Hits on 601 covered vertices |
| --- | --- |
| published label (x = 0) | 179 (0.298) |
| m7 snap | 181 (0.301) |
| scroll-label-snap, defaults | 259 (0.431) |
| scroll-label-snap, `convention_offset 0` | 348 (0.579) |
| scroll-label-snap, `convention_offset 0`, `template_weight 0` | 405 (0.674) |
| kit labelsnap | 513 (0.854) |

```python
import csv
rows = [r for r in csv.DictReader(open("pherc0139_twoscan_vertices.csv")) if r["covered"] == "1"]
def hit(x, f): return x is not None and abs(x) <= 16 and abs(x - f) <= 1
for col in (None, "labelsnap_x", "lsnap_x", "lsnap0_x", "lsnap0e_x", "m7_x"):
    h = [hit(0.0 if col is None else (float(r[col]) if r[col] else None), float(r["face_offset_vx"])) for r in rows]
    print(col or "published", sum(h), len(h), round(sum(h) / len(h), 3))
```

## Caveats

- These are spent development sites: they were read and scored before, so numbers on them are development numbers, not a held-out test. The held-out tests of kit labelsnap, including a preregistered comparison with scroll-label-snap on 43 fresh PHerc0139 sites, are on its [tool page](../../tools/labelsnap.md#checks-and-controls).
- One scan of one scroll, small crops (about 240 x 240 voxels), 9 vertices per site. scroll-label-snap is built for whole meshes and label cubes and is untuned here; kit labelsnap's defaults were set on other PHerc0139 sites, and it finds the face much as the truth defines it, so it may have a home advantage on this metric (Interpretation). This table does not show that one snapper is better than the other in general.
- `site_id` is our site number; the ids are not consecutive.
