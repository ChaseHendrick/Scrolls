# Protocol: do published meshes and cross-scan renders sit where the metadata says?

Written 2026-10-07, before any content measurement below was run. The commit that adds this file timestamps it. Results go to `docs/data/mesh-hypothesis/` (derived numbers only: no CT, renders, meshes or ink maps) and a dated log. Changes after the first content run need a new dated section here, with the reason, and the original text stays.

## Why

Most published segments are traced on one scan and then rendered on others through a stored affine transform. Ink models read a fixed band of layers around the mesh, so a mesh that lands tens of micrometres off the papyrus in the second scan gives that model the wrong depth. [villa #1727](https://github.com/ScrollPrize/villa/issues/1727) (ge-al, 7 Sep 2026) found from metadata alone that 366 of 628 published surface volumes could not be reproduced from any published mesh. Nothing in the bucket says how far a carried-over mesh is from the sheet. All inputs are public: the bucket catalogue `metadata.json` (a dated copy is hashed in the results), mesh `meta.json` and TIFF headers, surface-volume `.zattrs`/`.zarray`, and surface-volume voxels.

## Hypotheses and tests

**H1, canvas (metadata).** Every published surface volume has a published mesh variant whose grid reproduces its `canvas_size`: `|canvas - (tif_dim / scale) * r| <= 1` px on both axes, for `r` in {1, 0.5, 2, 4, 0.25}. Record `r` and whether the matching variant's name contains the rendered volume's ID. Also record the catalogue's `volume_coverage.overlap_ratio` per segment and volume.

**H2, transforms (catalogue).** For each stored transform with landmarks:

- refit the least-squares affine from its landmarks and report the largest difference from the stored matrix;
- fit residual RMS in micrometres (target voxel size times target-voxel residual);
- leave-one-out RMS and maximum in micrometres when there are at least 5 landmarks (4 landmarks determine an affine exactly and cannot be tested);
- inverse consistency against the stored reverse transform: largest displacement, in micrometres, of a landmark sent forward and back;
- isotropic scale `cbrt(|det|)` against the pixel-size ratio, in percent.

Tiers, fixed now: leave-one-out RMS below 25 um is "tight", 25 to 75 um "loose", above 75 um "coarse". These are expected-error flags, not proof that any render is off the sheet.

**H3, depth (content).** For segments with a surface volume on their native volume (`original_volume_id`) and at least one other volume, the papyrus band should sit at the same normal offset in both renders.

- Tiles: 32 centres per segment, uniform random in normalized canvas coordinates (numpy seed 20261007), kept only where the native render's centre layer is nonzero in a 1.5 mm window. The same normalized centre is read from the cross render.
- Profile: mean intensity per layer over the nonzero pixels of a 1.5 mm square window, at the pyramid level whose in-plane pixel is closest to 20 um. Layer positions are converted to micrometres from the centre layer with the volume's voxel size.
- Peak: smooth with a Gaussian of sigma 8 um; take the highest local maximum within 60 um of the centre layer; refine with a parabola. No such maximum means no peak.
- Offset: delta = peak(cross) - peak(native), in um, per tile with peaks in both.
- Orientation: if the cross profile correlates better with the native profile reversed than as stored on most tiles, the layer order is reported as opposite and delta is computed after reversing.
- Report per segment and per volume pair: tiles used, median delta, median absolute deviation, fraction of |delta| above 25 um and above 75 um.

**Controls (each can fail).** C1 synthetic: profiles shifted by known amounts are recovered within 2 um. C2 identity: a render compared with itself gives delta 0. C3 location: the median profile-shape correlation of matched tiles must exceed the 95th percentile of the same correlation for each native tile against a cross tile drawn from another random centre. If C3 fails for a segment, its tile mapping is not trusted and H3 is reported as not evaluable there.

**Scope.** H1 and H2 cover the whole catalogue. H3 covers up to 5 segments per (sample, native volume, cross volume) combination, chosen with the same seed. Relating H2's leave-one-out error to H3's median |delta| across volume pairs is descriptive only (few pairs).

## What this cannot show

Brightness peaks locate papyrus, not ink, and a tracing convention (centre of sheet or recto surface) cancels only within a pair. A small delta does not prove a render is good for ink, and a large delta does not prove ink is lost. Nothing here concerns letters or readings.

## Amendment 2026-10-07, after H2 and before any content run

H2 found one stored transform that does not reproduce its own landmarks: PHerc1667 `20260323082859` (1.129 um) to `20251217075048` (2.399 um) misses its six landmarks by 42 to 212 um, while a least-squares refit of the same landmarks fits within 4 um. PHerc1667 segments are traced on `20231117161658` (7.91 um), which has no published render, so H3's native comparison cannot reach this transform.

**H3b.** For PHerc1667, compare the 1.129 um render with the 2.399 um render of the same segment, the 2.399 um render taking the native role, with H3's estimator, tiles, seed and controls unchanged; 5 segments chosen with the same seed. H3b measures the relative depth placement of two cross-scan renders, not either one's absolute accuracy. It is added because of the H2 result; nothing else in the protocol changes.
