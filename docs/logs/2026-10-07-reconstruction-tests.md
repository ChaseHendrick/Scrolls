# CT reconstruction research and concrete tests, 7 October 2026

**Measured result:** two same-acquisition PHerc0139 reconstructions failed a frozen local-registration test. **Research hypothesis:** properly registered reconstruction recipes may change which sheet and ink features a reader preserves. No recipe-specific ink inference, accuracy improvement, new reading or groundbreaking result is established.

## A real test before ink inference

The official [Data Browser index](https://github.com/ScrollPrize/villa/blob/e0bbb8b40a2db58b1d71864f286eb85717e59e64/scrollprize.org/static/data_browser/index.json) groups original, pag0 and pag50 PHerc0139 reconstructions under scan ID `20250720065842`. Live acquisition metadata agrees on scan date, scan radix, 113 keV energy and 1.2 m propagation distance. All three use 9.362 um voxels. Their recipes differ:

| Public metadata | Shape Z,Y,X | Paganin delta_beta | Unsharp coefficient / sigma | Detector distortion correction |
| --- | --- | ---: | --- | --- |
| [Original](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr/metadata.json) | 20974,6621,6621 | 1000 | 4 / 1.2 | True |
| [pag0](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20251107132835-9.362um-1.2m-113keV-pag0-masked.zarr/metadata.json) | 20961,6621,6621 | 0.0001 | 0 / 0 | False |
| [pag50](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20251107135911-9.362um-1.2m-113keV-pag50-masked.zarr/metadata.json) | 20961,6621,6621 | 50 | 4 / 1.2 | False |

Rotation-axis, masking and shape metadata also differ. No original-to-new transform was found at these volume roots or among the w045 mesh variants inspected. This permits a reconstruction-recipe study after registration; it does not isolate the Paganin parameter. The 13-slice shape difference alone does not define a voxel transform.

A raw-CT-only pilot was fixed before fetching chunks or examining ink predictions. Two structural cube centers, ZYX `[6402,3730,4496]` and `[6615,3926,4566]`, came from the one-third and two-thirds positions of the public w045 crop's physical geometry bounding box. Original templates were 128 cubed; each phase search region was 192 cubed, allowing shifts up to 32 voxels. Primary matching used gradient-magnitude normalized cross-correlation after sigma-1 smoothing. Raw intensity matching was a diagnostic. Fit on the first cube; require the held-back second cube to agree within 0.5 voxel. The rule SHA-256 was `37ed675e2edf44d9010cefbb434ecbffc504e8e9692c6dca358ee46934839dbd`.

82 actual public CT chunks were downloaded, 164 MiB. Peak resident memory was about 929 MiB, below the 2 GiB cap. No GPU or paid compute was used.

| Comparison | Fit shift Z,Y,X | Held-back peak | Residual | Gradient NCC, fit / held-back | Gate |
| --- | --- | --- | --- | --- | --- |
| Original to pag0 | +1,0,0 | -1,0,0 | 2 voxels, 18.724 um | 0.8479 / 0.8832 | Failed |
| Original to pag50 | +1,0,0 | -1,0,0 | 2 voxels, 18.724 um | 0.7984 / 0.8236 | Failed |

All four algorithm controls passed: self comparisons recovered zero shift, and deliberately displaced comparisons recovered `[3,-4,5]`, with NCC about 0.995. Raw intensity independently selected the same real-data shifts. Real peaks were interior, with margins of 0.156 to 0.188 over competitors outside three voxels. Original patches had over 99.9% nonzero coverage. The mismatch is therefore not inferred merely from filenames, missing data, a boundary maximum or failure to recover a known displacement.

**Interpretation:** a common scan ID and voxel size did not justify copying a local translation between these two sites. This test does not prove global nonlinear distortion, chemical ink identity, or that no affine registration can work. Two displacements cannot identify a 3D affine transform. No phase-recipe ink comparison was run after the failed gate. A fresh registration experiment needs additional structural correspondences and untouched held-back sites before a fixed-mesh reader comparison.

Local rule, source hashes, script and receipts are retained in `/workspace/scrolls-env/phase-reconstruction/`. Aggregate readouts are in [results.json](../results.json). CT chunks and geometry stay outside git.

## Research directions checked against existing software

1. **Whole-search false-correction audits.** Run the complete candidate-selection process against deliberately displaced reference maps, with coverage accounting. The [real surfacefix test](2026-10-07-real-surfacefix-validation.md) completed eight such searches: zero accepted corrections, with evaluable regions in every case. This is a useful bounded rejection check, not a false-positive-rate guarantee. Lasagna already optimizes geometry; the contribution to test is reliable acceptance, not invention of snapping.
2. **Fixed-reader reconstruction comparisons.** After independent registration succeeds, compare original, pag0 and pag50 on one frozen human-labelled w045 patch with matched forward/reverse/shuffle maps, common coverage and paired region uncertainty. A stronger structural match need not imply better ink discrimination. w045 is a held-out segment on a seen training scroll, so cross-scroll claims need another surface. The current registration pilot failed; ink discrimination remains untested.
3. **Cross-energy contrast that rejects alignment and blur artifacts.** A small CPU experiment could remove local gain, displacement-gradient and blur terms before testing the residual against independently labelled ink/background. Freeze an artifact envelope and compare with simple ratios. Public Paris4 78/137 keV arrays exist, but uint8 reconstruction values without quantitative attenuation calibration cannot identify an element. Label availability and common footprint must pass before this experiment runs.

The third proposal is an untested approximation and may remove real signal along with artifacts. It cannot manufacture trustworthy negative labels or turn a sheet-gradient peak into ink identity.

## Prior art and search limits

Generic snapping, transform fitting and dual-energy rendering already exist:

- Official [Lasagna](https://github.com/ScrollPrize/villa/tree/e0bbb8b40a2db58b1d71864f286eb85717e59e64/lasagna) has snapping and geometric regularizers. [Open villa PR #1994](https://github.com/ScrollPrize/villa/pull/1994), inspected 7 October, reports landmark/transform repairs and improved CT correspondence; those reported results were not reproduced here.
- [axiosdevs/herculaneum-scroll-tools](https://github.com/axiosdevs/herculaneum-scroll-tools/tree/63a09d4fd8a46ac758ff475a8b6389a2c8152cb7) implements registered 53/70 keV ratio co-rendering, cross-scan transfer and CT support trimming. Its reported metal-bearing inclusions do not establish ink identity.
- [Paul-G2/VesuviusMultiSpectral](https://github.com/Paul-G2/VesuviusMultiSpectral/tree/30d7d6c13ee669feac9023959462a68f07852169) already compares energy/resolution images.
- [Independent depth validation](https://github.com/stantheman0128/vesuvius-ink3d-depth-validation/tree/50655db01d92698c50f90eaeb40eac5c504ea01b) supplies high-resolution/dual-energy registration and geometric checks. Its stated limit is geometry rather than ink identity. Reuse its checks rather than replacing them with an unverified new aligner.

Public GitHub source/pages and S3 metadata were inspected. The phase pilot actually used raw CT; the cross-energy proposal used metadata and code inspection only. Scholarly requests during the physics audit were denied, so this was not an exhaustive literature review. No worldwide novelty is established. The useful completed findings are the concrete rejection tests and the failed fixed-translation assumption.
