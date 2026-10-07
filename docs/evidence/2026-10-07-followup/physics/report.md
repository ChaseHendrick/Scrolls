# Reconstruction transfer pilot on real PHerc0139 CT

7 October 2026. Prepared for Chase Hendrick. Exploratory structural measurements on public control data. No ink maps, target data, model inference or labels were inspected in this experiment.

## Measured result

The public pag0 and pag50 reconstructions are locally aligned in both tested cubes. A fixed radial Fourier response learned on the first cube predicts the disjoint held-back cube with correlation **0.99724** and RMS error **2.717 uint8 units**, or **7.587% of held-back target standard deviation**. RMS is **55.75% lower** than the affine brightness baseline fitted on the same first cube. The frozen `TRANSFER_PREDICTABLE` gate and every control passed.

This is a measurement of reconstruction redundancy and spatial response. It does not show that ink is preserved, absent, recovered or recognizable. A rare localized ink signal could be important even if it occupies only a small part of the residual. These are two patches in one acquisition, not independent scrolls or a general-purpose correction model.

## Input identity and recipe confound

The source data are the public PHerc0139 volume reconstructions:

- [pag0 metadata](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20251107132835-9.362um-1.2m-113keV-pag0-masked.zarr/metadata.json).
- [pag50 metadata](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20251107135911-9.362um-1.2m-113keV-pag50-masked.zarr/metadata.json).

Both metadata documents identify the same acquisition radix `SCROLLS_HEL_4.681um_113keV_1.2m_binmean_2_PHerc_0139_HA`, dated `2025-07-20T08:58:42.332564+02:00`, with 113 keV energy and 1.2 m sample-detector distance. Public arrays have 9.362 um voxel pitch, uint8 samples and uncompressed 128-cubed chunks. Input chunks were already cached by the prior registration pilot; this experiment made no network requests.

Crucially, the recipes differ in more than the Paganin parameter:

| Metadata field | pag0 | pag50 |
| --- | ---: | ---: |
| `phase.delta_beta` | 0.0001 | 50 |
| `phase.unsharp_coeff` | 0 | 4 |
| `phase.unsharp_sigma` | 0 | 1.2 |
| preceding `32BitsConversion` window | [-0.09, 0.4] | [-0.16, 0.75] |
| exported target float32 window | [-0.03, 0.145] | [-0.03, 0.145] |

Consequently, this is a combined reconstruction-recipe measurement. It is not an isolated test of Paganin phase retrieval, physical attenuation or denoising.

## Frozen method and leakage audit

The rule was written before loading the CT arrays for this experiment. Main rule SHA-256: `f506cac999a1189e4eff33fc014964e56800bbd49bdd9ea2a8c20a5218fb9f49`. Source code and original registration-rule hashes are included in that rule and checked before execution.

The two cube centers, in explicit ZYX voxel order, were fixed by the prior mesh-geometry pilot at `[6402,3730,4496]` and `[6615,3926,4566]`. Their 128-cubed supports do not overlap: their Z centers differ by 213 voxels. No label or model score selected either cube.

- Alignment used a 128-cubed pag0 template and a 160-cubed pag50 search region, Gaussian-sigma-1 gradient magnitudes, a unique interior NCC peak and a required zero integer shift. NCC was 0.98458 and 0.98175; competing-peak margins were 0.35283 and 0.30216. Both gates passed. This establishes only the tested local integer alignment, not globally exact subvoxel registration.
- The transfer uses 32 fixed radial frequency bins. Each coefficient is the real cross-spectrum divided by pag0 spectral power, fitted from the first cube after a separable Hann window. No positivity bound, best-bin selection or target-dependent tuning was applied.
- Affine gain and offset were fitted only on the first cube. The Fourier prediction subtracts the first cube's pag0 mean and restores the first cube's pag50 mean. The held-back cube's mean, standard deviation and values were never used to calibrate a predictor. Its standard deviation appears only in the reporting denominator; its values are needed to score a genuinely held-back prediction.
- The frozen operator was applied to the unwindowed held-back input. Scores use only the central 96-cubed region, leaving a 16-voxel margin on every face. An FFT still imposes periodic boundaries, so this margin alone does not prove absence of boundary effects. The separate padding audit below checks that concern directly.

## Falsification controls

| Held-back comparison | Correlation | Normalized RMS | Outcome |
| --- | ---: | ---: | --- |
| pag0-to-pag50 radial prediction | 0.99724 | 0.07587 | Pass |
| affine brightness baseline | 0.98551 | 0.17145 | Comparison |
| same-volume identity operator | approximately 1 | 0.000000164 | Pass |
| pag50 displaced by 8 X voxels | -0.01549 | 1.43964 | Rejected |
| pag50 depth shuffled, seed 20261007 | 0.10852 | 1.32583 | Rejected |

The displaced and shuffled controls must reduce correlation by at least 0.1, and they do. They are structural pairing controls, not an ink reverse-depth validation.

## Spatial response actually measured

The following are windowed band RMS ratios and magnitude-squared spectral coherence. These bands contain all CT structure and acquisition noise, not identified ink.

| Wavelength at 9.362 um voxels | pag50/pag0 RMS, fitting cube | pag50/pag0 RMS, held-back cube | Coherence, fitting/held-back |
| --- | ---: | ---: | ---: |
| 18.7-37.4 um | 0.9029 | 0.9068 | 0.9753 / 0.9754 |
| 37.4-74.9 um | 1.0145 | 1.0262 | 0.9979 / 0.9978 |
| 74.9-149.8 um | 0.8369 | 0.8344 | 0.9885 / 0.9905 |
| 149.8-299.6 um | 0.7133 | 0.6721 | 0.9857 / 0.9961 |

The response is not uniform brightness scaling: the 37-75 um band remains near unity while coarser bands attenuate more. The unsharp settings are a documented reason not to interpret this as simple monotonic low-pass smoothing. Attribution among phase retrieval, sharpening, contrast conversion and other reconstruction steps remains unresolved.

## Post-pilot robustness and negative transportability check

These diagnostics were frozen after the primary result, before their measurements. They are explicitly supplementary, not a second preregistered discovery. Supplement rule SHA-256: `c4bb51f47aec5a8898cb4db14a6864e9bb959345eb4962c53361c44f7f81b4a1`.

**FFT boundaries:** the unchanged coefficients and fitting means were applied after reflection-padding the held-back pag0 cube by 32 or 64 voxels. Physical frequency-bin boundaries were unchanged, and there was no refit. Central-region correlations were 0.997256 and 0.997264; normalized RMS was 0.075675 and 0.075579. Both frozen sensitivity gates passed. The largest correlation change was about 0.000022 and normalized RMS change about 0.000286. Thus the observed prediction is stable to these two boundary treatments; other boundary conditions were not exhaustively tested.

**Transport to the original reconstruction failed:** the previous CT-only pilot found original-to-phase local shifts of +1 Z voxel on cube 0 and -1 on cube 1, while rejecting a global translation. Those reported shifts were used only to compare local cached fields. Reusing the pag0-to-pag50 operator on the original held-back CT produced correlation 0.8260 and normalized RMS 0.7311. Even fitting a new original-to-pag50 radial operator on cube 0 yielded held-back correlation 0.9162 and normalized RMS 0.4151. Both fail the unchanged 0.95-correlation and 0.15-normalized-RMS prediction bars. There is no basis for transporting the successful recipe-pair operator onto the original scan as a reliable correction.

This is a useful negative control: the method does not automatically declare every reconstruction pair predictable. Its failure does not isolate whether remaining errors are from geometry, processing, anisotropy or intensity changes. The ongoing affine registration audit is needed before any official surface rendering or labelled reader comparison with the original.

## What this enables next

Use the actual reconstruction residual as a **candidate channel**, and ask whether it predicts held-back human ink labels after official rendering and independently verified registration. Compare against raw pag0, pag50 and a simple brightness residual through matched forward/reverse/shuffle reader controls. The small overall residual is not evidence that it lacks ink information. Conversely, strong CT redundancy means two recipe channels agreeing cannot count as two independent physical acquisitions or independent confirmations of ink.

The current actionable result is that a cheap, frozen operator explains most pag0/pag50 structural variation in these two real cubes, survives a boundary audit, and fails transport to the original reconstruction. This provides a defensible calibration baseline for the residual audit. It is not yet a breakthrough in ink detection.

## Prior art and novelty boundary

Paganin phase retrieval, transfer functions and Fourier filtering are established methods; this pilot claims no invention of them. [Paul-G2/VesuviusMultiSpectral](https://github.com/Paul-G2/VesuviusMultiSpectral), inspected commit `30d7d6c13ee669feac9023959462a68f07852169`, already compares Vesuvius energy/resolution reconstructions and display differences. [axiosdevs/herculaneum-scroll-tools](https://github.com/axiosdevs/herculaneum-scroll-tools), inspected commit `63a09d4fd8a46ac758ff475a8b6389a2c8152cb7`, already co-renders energy channels and calculates a mean-depth ratio. The bounded contribution here is the reproducible held-back recipe-transfer measurement, its controls and the negative transportability result. No exhaustive literature search establishes that these exact measurements are unpublished elsewhere.

## Runtime and artifacts

The main pilot took 5.56 seconds and peaked at 738,816,000 bytes RSS. The supplementary measurements took 2.09 seconds and peaked at 839,704,576 bytes RSS. Both were restricted to one CPU thread and less than 2 GiB address space. No downloads, GPU, training or reader inference occurred.

`rule.json`, `result.json`, `supplement-rule.json`, `supplement-result.json`, both code files, logs, this report and all used cached chunks have SHA-256 entries in `sha256-manifest.txt`. Verification output is recorded separately. These local hashes bind the current files; they do not establish an externally timestamped precommitment.
