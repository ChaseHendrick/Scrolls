# Preregistration: does a finer tile stride remove the tile grid? (14 October 2026)

Private; public data only. Written and committed before any render exists. Code: [`scripts/strokenet/gridpilot.py`](../../scripts/strokenet/gridpilot.py) (the readout) and [`scripts/strokenet/modal_gridpilot.py`](../../scripts/strokenet/modal_gridpilot.py) (the run); tests in `tests/test_gridpilot.py`. Spec: [`../compute/modal-specs/2026-10-14-gridpilot.md`](../compute/modal-specs/2026-10-14-gridpilot.md). Chase chose "Run pilot" on the card in thread "StrokeNet" (14 October 2026, 15:35 UTC).

## Why

The organisers' PHerc. Paris 4 ink maps, pooled to 48 µm, carry a grid every 6.4 px that repeats every 32 px (Model output, measured 14 October; StrokeNet's preregistration, "The tile grid"). StrokeNet handles it with a grid baseline and an artifact control, and some of its tests are withheld because of it. Chase asked whether it can be fixed by re-rendering the maps. The maps were made with 256 px tiles at stride 128 on the 2.4 µm grid, blended with a Hann window (villa `ink-detection/optimized_inference` at `a4979b99`, checkpoint `scrollprize/ink_canonical_2um` `r152_3ddec_v2_l5_epoch13.ckpt`; Sourced fact for the recipe, Interpretation that the published maps used tile 256 and stride 128, which the reproduction check below tests). A finer stride gives every pixel more tiles at more offsets, which may average the tile-edge pattern away (Untested idea). This pilot measures that on one region before anyone pays for a full re-render.

## What is rendered

- **Segment** `w028-037` (a StrokeNet training segment; no validation or test segment is touched).
- **Region**: the 192 × 192 pooled px window (9.2 mm, 3840 native px) on the 32 px lattice with the most usable pixels (StrokeNet label above 0), then the most text, then the smaller y and x, leaving out the first and last lattice step of each axis (`choose_region`). On the labels built locally on 14 October it is pooled (224, 544), all text; the runner picks it from the volume's labels by the same rule and records it.
- **Input**: layers 23 to 85 of the 2.4 µm surface volume (`.../surface-volumes/2.4um-0.22m-78keV-volume-20260411134726.zarr/0`), read with 384 native px of margin, so every region pixel gets every tile that covers it.
- **Recipe**: villa's, unchanged except the stride and the tile origin: clip 0..200, divide by 200, ResNet3D-152 with 3D decoder in autocast, sigmoid, bilinear resize to 256, per-pixel valid mask (any nonzero voxel), Hann-weighted overlap-add, divide by the summed weights, clip, times 255, truncate to uint8, then the 20 × 20 mean pool StrokeNet uses (`data.pool_array`).
- **Renders, in this order**: `A128` (stride 128, tiles where the published render put them), `R128` (the same again: the numerical noise), `B128` (stride 128 with the origins moved 64 px in both axes), `A64` and `B64` (stride 64, origins 0 and 32), `A32` and `B32` (stride 32, origins 0 and 16). 43,524 tiles. A render the measured speed says would end after 2100 s from the start is skipped and reported as not run.

## Measures

All on the region's usable pooled pixels, in 0..255 units.

- **Tiling effect** at stride s: RMS of `A_s − B_s`. Both renders see the same voxels with the same network, so the difference holds no ink content; it is how much the output depends on where the tiles fall, which is what the grid is.
- **Noise**: RMS of `A128 − R128`.
- **Reproduction**: Pearson r of `A128` with the published pooled map.
- **Content kept** at stride s: Pearson r of `A_s` with `A128`.
- Reported, not part of the readout: where in the 32 px repeat each difference sits (`phase_profile`), the network's speed in tiles per second, and the cost of a full re-render of the 27 maps at each stride from that speed (17.6 million tiles at stride 128, 70.4 million at 64, 281.7 million at 32, counted from the published pooled maps).

## Readout (fixed now)

1. **VOID** if `A128`, `R128` or `B128` did not run; if the reproduction r is below 0.95 (the recipe or the tiling is not the published one, so nothing here speaks for the published maps); or if the stride-128 tiling effect is at most 2 × max(noise, 0.1) (there is nothing to remove in this region).
2. Otherwise, for each finer stride that ran: **gone** if its tiling effect is at most 2 × max(noise, 0.1); **reduced** if it is at most half the stride-128 effect; **not reduced** otherwise. **Content kept** if its r with `A128` is at least 0.95.
3. The line reads, for example, `stride 64: reduced (RMS 0.41, 0.33 of stride 128), r with stride 128 0.991`.

## What each outcome means

- **gone or reduced, content kept, at stride 64**: a stride-64 re-render would remove or shrink the grid. A full re-render is then a separate budget decision for Chase, priced from the measured speed. A StrokeNet v2 trained on re-rendered maps would still need held-out segments StrokeNet has not been scored on, because its test segments have been read once.
- **not reduced at both strides**: a finer stride is not the fix; the grid comes from something tiling at a fixed stride does not explain, and the re-render idea is dropped.
- **VOID**: reported as it is, with the reason; no second region is tried without a new preregistration.

A CPU preflight of 9 tiles, made before this file was committed and before any pilot render, matched the published pooled map in 143 of 144 pixels (the spec's "Preflight on CPU"); it checks the recipe, not the tiling effect. This is one region of one training segment: it can show that a finer stride works or fails on that region, not that it does everywhere. The run is made once.
