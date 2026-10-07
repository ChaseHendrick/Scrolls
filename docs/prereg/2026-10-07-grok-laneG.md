# Preregistration: lane G, new model-free ink signals (2026-10-07)

Written and committed before any lane G script was run on data. Label: Untested idea until results exist.

Data: the two labelled 640 x 640 px crops already used in this repo (PHerc0139 w045 crop 3840 4480 2560 3200; PHerc0841 w00 crop 2624 3264 2688 3328), 28 layers, 9.366 um, labels 20260918 at level 2, inner 64 px left out. Lane C covered local 3D std, Laws energy, 3D gradient and lag-1 autocorrelation; lanes D and F covered structure tensor, stroke priors, depth-profile clustering and others. Lane G tests signals none of those compute.

## Signals (each projected to 2D; layers used: central half, 7 to 20, unless stated)

1. **dog_band**: wavelet-like band energy at stroke-width scale. Difference of in-plane Gaussians sigma 3 px minus sigma 6 px (about 30 to 60 um, stroke edges and thin strokes) on the depth-mean image, squared, then smoothed by Gaussian sigma 6.
2. **noise_resid**: CT noise texture, not mean: the high-frequency residual along depth only (second difference along z of each voxel profile), its local median absolute value (11 x 11 px window), averaged over central layers. Differs from lane C std3d, which mixes in-plane structure.
3. **crackle**: fiber disruption density. Black top-hat of each central layer with a 7 px disk (dark thin cracks), thresholded at the layer's 90th percentile, fraction of crack pixels in a 31 x 31 px window, averaged over central layers.
4. **relief**: surface micro-relief from ink layers. For each pixel, the depth (sub-layer, intensity-weighted centroid over all 28 layers after subtracting each profile's minimum), then the magnitude of its in-plane Laplacian of Gaussian at sigma 8 px (local bumps or steps of the surface).
5. **phase_sym**: phase symmetry (monogenic, log-Gabor bands at wavelengths 12, 24, 48 px) on the depth-mean image, symmetric dark-or-bright line response; Kovesi style, simplified noise threshold T = 2 x median amplitude.
6. **line_period** (text-level, not a pixel AUC): row autocorrelation of the dog_band map row means; the period of its first peak at lags 15 to 200 px compared with the same statistic from the label map.

## Readout rule (fixed now)

- Sign: each pixel signal's direction (higher means ink, or lower) is fixed on w045 by its AUC and applied unchanged to PHerc0841 w00. Reported AUC is in that direction.
- Controls on each segment: (a) depth-shuffled volume (kit depth_permutation, seed 20261007) through the same feature; (b) 8 rolled maps (shifts 120 to 520 px, seed 20261007), max taken; (c) raw brightness (depth mean) as the baseline.
- `kit auc --bootstrap 300 --inner 64` on each written map (95 % interval, blocks 107 px).
- A pixel signal is **positive** only if on BOTH segments: bootstrap lower bound above 0.55, and point AUC at least 0.03 above the max rolled null, and (for depth-dependent signals 2 and 4) at least 0.03 above the depth-shuffled control. **Null** if it fails on either segment with point AUC within 0.03 of a control or below 0.55. **Inconclusive** otherwise (for example passes one segment only, or the direction flips).
- Extra report, not part of the rule: the brightness baseline and Spearman correlation with brightness, so a signal that only repeats brightness is visible.
- line_period: **positive** if, on both segments, the signal period is within 15 % of the label period and the autocorrelation peak exceeds that of the depth-shuffled control's map by 0.05; null otherwise; inconclusive if a label period cannot be found (crop under 3 periods).

No target-scroll data is used. No reading is claimed from any map.
