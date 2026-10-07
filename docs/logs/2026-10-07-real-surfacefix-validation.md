# Real papyrus surfacefix validation, 7 October 2026

**Model-output consistency test, not an accuracy improvement or reading.** The frozen PHerc0841 patch has zero supervised label pixels. Twelve real prediction maps completed. The default correction rule accepted no changes and flagged all 16 regions. Four regions had adequate coverage for candidate evaluation; the other 12 did not.

## Inputs and frozen recipe

The public source was [PHerc0841's 9.366 um CT](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr/.zattrs). Only 120 uncompressed 128-cubed chunks were fetched, 240 MiB, with S3 single-part ETag and SHA-256 checks. This was public known-sheet data, with no target-scroll run or training.

Source meshes: [w00](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/mesh/20260220213127-on-20250821151531-9.366um.tifxyz/meta.json) and [ag896](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220214732-auto_grown_20260220144552896/mesh/20260220214732-on-20250821151531-9.366um.tifxyz/meta.json). The geometry-selected native crops were w00 rows 128:160, columns 0:32, and ag896 rows 148:180, columns 0:32. Each renders to 640 x 640 pixels. Their original canvas crops are respectively `[2560,3200,0,640]` and `[2960,3600,0,640]`. They trace one sheet, not independent papyri.

The official `vc_render_tifxyz` binary came from the digest-pinned container `sha256:b2509de2c107852799a5077fd2038a917549a1d1e3665d5a1919c955858d698a`, source revision `1e3f4c021f4e53bea3867772ed05f51a7e586a9c`. Complete compressed layer digests were verified before selectively extracting the binary and runtime libraries. Its binary SHA-256 was `fd1d5118e8f7e38c2c482d9cd5473eb5631f82546b896f088ef85ee4fe615a6a`. The full image pull had exceeded disk capacity; selective extraction avoided its transient build tree.

All four actual meshes, including offsets -1 and +1 volume voxel, were rendered from CT. Recipe: group 0, one pixel per voxel, 28 slices, slice step 1, no accumulation, affine, rotation or flattening, explicit 9.366 um metadata. The official column-cross-row depth stack was reversed into the row-cross-column convention used by surfacefix. Existing published surface volumes were not shifted to impersonate new renders. Native point sampling uses the checked `row/scale_y-.5, col/scale_x-.5` canvas relation.

The reader was released [d9v2 v1.0](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search/releases/tag/v1.0), checkpoint SHA-256 `50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966`, loaded with `weights_only=True` and a strict state match. Inference used official villa `e0bbb8b40a2db58b1d71864f286eb85717e59e64`, torch 2.8.0+cpu, stride 42, Hann blending, batch 1, no compilation or mixed precision. Forward, reverse and seeded shuffle all used exactly the same selected central 17 source layers. Four surfaces times three depth orders produced twelve maps; each had 196 scheduled patches. Two jobs used two threads each under the four-CPU quota. Output hashes, shapes, layer sets and settings were verified.

Geometry/crop thresholds were fixed before maps. The original rule SHA-256 was `179041e32532a23fcbf375fcd628471cc3ab92aac5d744ca0ec5714937d24e9c`. A separate reader amendment recorded the switch from a blocked Hugging Face seed42 download to the verified official d9v2 GitHub release before reader outputs. Default region size 8, minimum 24 points in each subset, correlation 0.5, gain 0.1, control margin 0.1, maximum neighboring step 1 voxel and displacement bound 50 um were retained.

## Readout

432 of 962 valid native points met geometric and all-map coverage checks: 215 selection points and 217 held-back points. All four evaluated winners failed the fixed checks.

| Region | Selected offset (voxels) | Baseline r, selection / held-back | Candidate r, selection / held-back | Accepted |
| --- | ---: | --- | --- | --- |
| 5 | +1 | 0.4387 / 0.5063 | 0.4282 / 0.5561 | No |
| 6 | -1 | 0.5214 / 0.3903 | 0.6025 / 0.3995 | No |
| 9 | -1 | 0.3367 / 0.4418 | 0.4403 / 0.3756 | No |
| 10 | -1 | 0.1741 / 0.4074 | 0.1568 / 0.3059 | No |

Region 9 illustrates why selection gain alone is insufficient: its selection correlation increased by about 0.104, but held-back correlation decreased. It also failed the minimum correlation bar. This is one descriptive case, not a calibrated generalization estimate.

The new output's coordinates were exactly unchanged. All 62 native holes, metadata bytes and float32 coordinate dtypes were preserved. Source hashes remained unchanged. No combined-surface rerender or additional inference was needed because no geometry changed.

## Concrete failure tests

- A real candidate edited sideways by 0.5 voxel was refused even after its mesh hashes were recomputed, so rejection exercised the normal-offset constraint rather than stale-hash detection. No output was created.
- A 6-voxel offset, 56.196 um, was refused under the 50 um bound before output creation.
- Eight full correction searches used deliberately misregistered reference maps. All three reference depth orders were jointly translated without wrapping, by -300, -150, +150 and +300 pixels along each axis. This rule was fixed before the normal readout and null searches, SHA-256 `4e3ef716ca39a1dabbaf78cfc7089c59cdf8e3669d46d3e6827532601d209fb8`.

Every null accepted zero corrections. Each had two to four evaluable regions, with one to four candidate-selection attempts and 170 to 422 covered native points. In total there were 24 evaluable region checks and 18 selection attempts across the eight searches. These are dependent tests on one patch; zero acceptances does not establish a false-positive rate or statistical significance.

## Limits and next gate

The official supervision and ink-label shards contained zero supervised pixels in this frozen crop. No AUC, paired label improvement or correctly placed ink-layer claim is supported. The frozen crop was not changed after this result. A zero-valued prediction is currently treated as uncovered; that conservative convention can also exclude valid quantized background, especially in controls. The thresholds have not been calibrated on independent sheets.

This run validates real-input geometry constraints, actual rendering/inference, provenance and rejection behavior. It does not demonstrate successful real-papyrus recovery, superiority to Lasagna, or a groundbreaking result. Next, choose an independently supervised, frame-verified benchmark before inference, compare official snapping and bounded candidates, and audit the final combined rerender whenever a correction is accepted.

Local evidence and maps remain outside git in `/workspace/scrolls-env/geometry-validation/`. Key receipts are `actual-validation-with-nulls.json`, `reader-all-maps-integrity.json`, `w00-label-coverage.json` and `actual-geometry-output-checks.json`. Aggregate results are recorded in [results.json](../results.json); no maps, weights or CT chunks are committed.
