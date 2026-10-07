# 2026-10-07: do published meshes and cross-scan renders sit where the metadata says?

Research notes on public data, not claims about ink or text. Protocol and its dated amendments: [`../plans/2026-10-07-mesh-hypothesis.md`](../plans/2026-10-07-mesh-hypothesis.md), committed before each measurement (f374791, 99aa3c5, 66de681, 20c301b). Data: [`../data/mesh-hypothesis/`](../data/mesh-hypothesis/README.md). Code: `kit meshaudit` and `scripts/experiments/2026-10-07-mesh-hypothesis/`. Existing cloud CPUs only, about one hour, almost all network reads.

Labels follow [`../NOVELTY.md`](../NOVELTY.md). "Measured here" means computed in this work from the public bucket on 7 Oct 2026 (catalogue SHA-256 in the data README). The bucket can change.

## Why

Segments are traced on one scan and rendered on others through stored affine transforms. Ink models read a band of layers around the mesh, so a carried-over mesh that lands off the papyrus gives them the wrong depth or place. [villa #1727](https://github.com/ScrollPrize/villa/issues/1727) (ge-al, 7 Sep 2026; Community report) found 366 of 628 published surface volumes not reproducible from any published mesh.

## H1: every published surface volume now has its mesh (Measured here)

All **692 of 692** surface volumes in the catalogue reproduce their `canvas_size` exactly from a published mesh variant that names the rendered volume: 581 at render scale 1 and 111 at 0.5, and all 111 half-scale renders carry `-L1` in their names. The gap reported in #1727 is closed in today's bucket. The first pass undercounted (685) because 301 large meshes are BigTIFF; the reader now handles both.

Coverage from the catalogue: region-of-interest scans hold only part of each mesh. Median `overlap_ratio` is 0.37 for PHerc0139's 1.129 um volume, 0.44 for PHercParis4's, 0.67 for PHerc1667's and 0.95 for PHerc0814's; the rest of those renders is empty. Four PHerc1447 segments sit only 81 to 90% inside their own native volume.

## H2: the stored transforms, refit from their own landmarks (Measured here)

29 stored transforms; 24 have at least 5 landmarks, so a leave-one-out (LOO) error can be computed. Tiers fixed in advance: 10 tight (LOO RMS under 25 um), 10 loose (25 to 75 um), 4 coarse (over 75 um), 5 untestable (0 or 4 landmarks).

- **One stored matrix does not fit its own landmarks.** PHerc1667 `20260323082859` (1.129 um) to `20251217075048` (2.399 um) misses its six landmarks by 42 to 212 um. A least-squares refit of the same landmarks fits them within 4 um, with LOO errors of at most 11 um. The stored matrix is also anisotropic (diagonal 0.472, 0.475, 0.466), while the refit is isotropic at 0.471, matching the voxel-size ratio 0.4706. Every other stored matrix equals the least-squares fit of its landmarks to about 1e-11.
- **Coarse transforms.** PHerc0332 `20251211183505` to `20231117143551`: fit RMS 103 um, LOO up to 2.3 mm. PHerc0009B `20250521125136` to `20250820154339`: LOO RMS 189 um. PHerc1667 2023 and 2025 scans to the 2023 7.91 um scan: 89 and 77 um. All three have nearly flat landmark sets (flatness 0.03 to 0.11), so the fit is poorly constrained across them.
- **Paris 4:** 2.4 um 78 keV to the 2023 7.91 um scan, 24 landmarks, LOO RMS 23.6 um; 1.129 um to 2.4 um, 16 landmarks, 4.1 um.
- **Scale (Interpretation).** Every transform whose fitted isotropic scale departs from the nominal voxel-size ratio by more than 0.5% maps into a 2023 Diamond Light Source scan: Paris 4 (+1.11%, +1.18%, +1.23% from three ESRF scans), PHerc0332 (+1.17%, +0.72%) and PHerc1667 (+1.48%, +0.70%). Transforms among 2025 and 2026 scans stay within about 0.4%. The simplest reading is that those 2023 volumes' true voxel size is about 1% smaller than the nominal 7.91 um, so millimetre measurements taken in them read about 1% large. Physical change between scan dates is the alternative; these data do not separate the two.

## H3: papyrus depth in native and cross renders (Measured here)

For 63 seeded segment pairs (13 scan combinations) plus 5 PHerc1667 pairs (H3b), the brightness peak of the papyrus band was located in 32 tiles per segment, in both renders.

- **31 of 68 pairs were evaluable**, and in all of them the cross render puts the papyrus within a few micrometres of the native render. Segment medians run from -5.4 to +5.8 um, with one at -11.6 um (PHerc0814 to its 1.129 um scan). That holds even where the transform's landmark LOO error is 30 to 60 um (PHerc0139, PHerc0841).
- **37 pairs were not evaluable.** The location control (C3) failed: depth profiles look alike everywhere (one sheet near the centre layer), so a profile from another random tile correlates nearly as well as the matched one (displaced 95th percentiles 0.86 to 0.97). That is a weakness of the control's design, not evidence of misregistration. It includes all of Paris 4's 45.5 um renders (too few layers) and all of H3b.
- **Limit.** The peak is searched within plus or minus 60 um of the centre layer, so an offset much larger than that cannot be measured this way.

## H4: cross meshes are affine images of the reference mesh (Measured here, exploratory)

Applying the catalogue's matrix to the reference mesh reproduces the published cross mesh along the normal: median normal residual 0.01 to 1.9 um per scan combination, 90th percentiles up to 16 um, i.e. grid resampling error. Two cases are coarser: PHerc0814 meshes on its 9.362 um scan for segments traced on 2.399 um (median 11 um, p90 up to 50 um) and Paris 4's 45.5 um meshes (14 um). Both are within about 1.2 cross voxels and consistent with resampling onto a much coarser grid; H4 cannot separate that from a small transform difference. An attempt to fit a direct affine for PHerc0814 failed because the grids are not proportional, so no different matrix is claimed. Tangential residuals of about 8 cross voxels everywhere are the expected nearest-vertex distance for non-aligned grids, not error. Paris 4, PHerc0139 and some PHerc0814 and PHerc1667 meshes over 40 MB were skipped.

So published cross meshes are pure affine images, not refinements in the second scan. H3's small offsets therefore reflect transforms that are accurate along the normal where the papyrus is, better than their landmark LOO suggests. PHerc1667's 1.129 um meshes are the exact image (0.02 um) under the matrix that misses its landmarks.

## H5: is PHerc1667's matrix or its landmarks wrong? (Measured here, exploratory)

Measured the in-plane shift between the 2.399 um and 1.129 um renders' centre layers by phase correlation on 3 mm tiles (24 per segment). The prediction under "landmarks right, matrix wrong", fixed before measuring, is computed per tile from the reference mesh.

**Pre-registered outcome: not trusted, neither hypothesis supported.** All nine control segments (PHerc0139, PHerc0814 and Paris 4 pairs whose matrices fit their landmarks with LOO about 4 um) measured 15.6 to 18.2 um, above the 10 um bar. None of the five PHerc1667 segments met either criterion with the pre-set peak-to-sidelobe (PSR) cut-off of 6.

**Two design errors, found afterwards.** First, unrelated tile pairs reach PSR 5.3 to 8.3 ([calibration](../data/mesh-hypothesis/shift-psr-calibration.json)), so a cut-off of 6 admits noise. Second, the control shift is not noise: it is a constant (-11.9, -11.0) um (rows, columns) on every control tile across three scrolls, spread 1.7 um, median PSR 146. A render compared with itself at two pyramid levels gives 0.0 um, so the offset is in the published renders, not in this code: the 1.129 um renders sit about 16 um from the 2.4 um renders of the same segments. Its size matches half a grid cell of the 1.129 um meshes (11.3 um per axis), which suggests a canvas convention; that is untested.

**Post hoc (Interpretation).** Keeping PHerc1667 tiles above the noise ceiling (PSR at least 9: 42 of 111) and removing the constant offset, the measured shifts follow the landmark-refit prediction: median miss 7.7 um against a median predicted shift of 37 um, least-squares slope 0.93, correlation 0.82 (rows) and 0.55 (columns), 71% within 20 um. Examples: predicted (210, 188) um, measured (209, 198); predicted (-242, -138), measured (-257, -136). Matching also falls as the predicted 3D displacement grows: 22 of 22 tiles match below 50 um, 14 of 32 between 50 and 150 um, and 6 of 57 above 150 um, which is what a wrong matrix predicts (large displacements leave the sheet or the tile). Over all 111 tiles, the predicted displacement of the published 1.129 um renders has median 158 um, 90th percentile 389 um and maximum 475 um.

So, on the five PHerc1667 segments measured, the stored landmarks are right and the stored matrix is wrong, and the published 1.129 um meshes and renders built from it are misplaced by tens to hundreds of micrometres. This rests on a post hoc threshold and offset, so it should be confirmed with a new, calibrated protocol before anyone relies on it.

The first H5 run ([`shift-v1.json`](../data/mesh-hypothesis/shift-v1.json)) used tile centres taken from each pyramid level's rounded-up size, which drifts by up to one level pixel when sizes do not divide evenly. The fix takes centres from the full-resolution canvas; a regression test fails on the old code (6.4 um drift) and passes on the new. Conclusions did not change. H3 was rerun with the fix too (31 of 68 evaluable, against 32 before; segment medians moved by at most 0.8 um).

## What this does and does not show

Brightness peaks and texture locate papyrus, not ink. Nothing here concerns letters or readings. A transform that places papyrus well is not shown to be good for ink, and the PHerc1667 displacement is shown only on the five segments measured. Fibre directions could give an independent alignment check: they are visible texture with no ink involved. That is an untested idea.

## Next

- Report the PHerc1667 matrix to the organisers with these numbers, if the user agrees (nothing is posted without a go-ahead).
- Rerun H5 on all PHerc1667 segments with 1.129 um renders, and add a calibrated noise threshold to the protocol before using PSR again.
- Explain the constant 16 um offset between 1.129 um and 2.4 um renders with the renderer's source, then check whether ink labels drawn on one and used on the other inherit it (16 um is about 14 pixels at 1.129 um).
