# UV overlap gate performance, 2026-10-13

Speed and parity measurements of the UV overlap gate (`python -m kit uvgate`, `kit/uvgate.py`) and its OBJ benchmark (`scripts/bench_uvgate.py`), measured on 13 October 2026 and published on 21 October 2026. Tool page: [uvgate](../tools/uvgate.md). This is a geometry check of supplied UV coordinates: it says nothing about 3D sheet identity, ink or a reading. The per-run receipts are kept privately; this log is the public source of the numbers below.

## Implementation

- Uniform grid over UV triangle bounding boxes, with power-of-two scaling checked for exact round trips. Typical occupancy gives near-linear candidate work; dense overlaps or widely varying triangle sizes can still produce quadratic work.
- NumPy computes cell memberships, bounding-box culling and conservative orientation predicates in batches. A pair is processed in only its first shared cell. Uncertain pairs use the exact `Fraction` clipping and threshold comparison of the all-pairs reference.
- Default verdict fields, original face indices, overlap counts and the lexicographically first witness are the same on both paths. `collect_pairs=True` provides the complete sorted pair list for parity checks. `method="reference"` keeps the exact all-pairs algorithm; `auto` uses NumPy when installed.
- Unsafe numeric conversions, unusual exact types and negative thresholds use the reference. NumPy integer coordinates are normalized to Python integers before `Fraction` construction to prevent fixed-width overflow.
- The original exact all-pairs gate on a synthetic 20 by 20 quad grid (800 triangles) made 319,600 clipping calls; exact clipping and `Fraction` arithmetic dominate its profile.

## Released flattened UV: PHerc0139 w039

Data: the released PHerc0139 w039 flattened OBJ from the open-data bucket, `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/segments/20260302000000-w039_2026030210/mesh/intermediate/20260302000000-w039_2026030210_flattened.obj` (36,875,399 bytes, SHA-256 `1f85e13fc1433eb53c7bb601824567f8cee80c7b7f444ecefb2d11d4b7c9506b`, downloaded 13 October 2026). The official catalog lists it as `flatten-segment` output of villa `ee7ee2944ea063b5da752598abf3c82469000121`, 50 iterations, created 19 June 2026 and copied to the public bucket on 25 June 2026. It has 97,549 vertices, 581,316 texture coordinates and 193,772 triangular faces. Only this geometry file was downloaded; no texture, CT or ink image was opened.

`--obj-uv` follows each face corner's texture index into `vt`; `v` remains nonplanar 3D geometry and is not used as UV. Original UV units, face order, texture seams and degenerate faces are kept. No rescaling, triangulation, material, texture or ink-image loading occurs. The mesh is not padded or tiled to reach one million faces.

Three fresh processes per table row, run one after another on Chase's Mac (Apple M1 Pro, macOS 27.0, Python 3.14.8, NumPy 2.5.3). Gate time excludes OBJ parsing, imports and hashing; whole-process time includes them. Peak RSS is the maximum whole-worker high-water mark of the three runs, including all worker preparation, in decimal MB. `abs_eps=1e-12` in squared original UV units, with all overlapping pairs collected.

| Input and path | Triangles | Median gate seconds | Gate range, seconds | Median process seconds | Max peak RSS, MB |
| --- | ---: | ---: | ---: | ---: | ---: |
| w039 800-face prefix, reference | 800 | 17.254121 | 17.205316 to 17.433480 | 18.435294 | 61.030 |
| w039 same prefix, grid | 800 | 0.010357 | 0.009402 to 0.012741 | 1.120596 | 62.308 |
| w039 full released mesh, grid | 193,772 | 1.003584 | 0.978087 to 1.430846 | 2.203803 | 165.659 |

The matched 800-face median speedup is **1,666.01 times**. The full mesh returned pass=true, pairs=0, degenerate=0 in all three repeats. No full quadratic reference run was attempted. A million-triangle result on real UV remains unmeasured.

Parity: 17 benchmark workers ran on w039. Full verdict dictionaries, sorted overlapping pairs, triangle hashes and original-face index hashes agree between the grid and reference paths for every prefix repeat and for 800-face random samples at seeds 17, 29 and 41. The positive control appends source face 0 to the 800-face prefix: both methods detect exactly pair `[0,800]`, with the same witness area, 199.30 squared UV units. The control is modified geometry and is not counted as a defect of the released mesh. All five selection and control comparisons on w039 agree.

To repeat a row on any machine (any scratch folder `WORK`; the reference path is refused above 2,000 faces):

```bash
mkdir -p WORK
curl -o WORK/w039_flattened.obj https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/segments/20260302000000-w039_2026030210/mesh/intermediate/20260302000000-w039_2026030210_flattened.obj
python scripts/bench_uvgate.py --obj-uv WORK/w039_flattened.obj --triangles all --method grid --collect-pairs --output WORK/w039-full.json
python scripts/bench_uvgate.py --obj-uv WORK/w039_flattened.obj --triangles 800 --selection random --seed 17 --method reference --collect-pairs --output WORK/w039-random-reference.json
```

Repeat the second command with `--method grid`, then compare complete verdicts and input hashes. Repeat timing cases in three fresh processes.

This checks supplied UV interior overlap. It does not establish 3D sheet identity, complete coverage, downstream ink accuracy or a reading.

### Upstream change noted the same day

[villa `bcdf9bf`](https://github.com/ScrollPrize/villa/commit/bcdf9bf53165e49c28807dcd6178478fb7d2d6f2), merged 13 October 2026 at 07:23:44 UTC via [PR #1978](https://github.com/ScrollPrize/villa/pull/1978), changes the legacy OBJ-to-tifxyz scale default from an area-weighted mean to the median, with explicit legacy and manual options. It changes the converter and its tests, not the published OBJ coordinates above or the overlap algorithm. A future conversion with the new default can change raster dimensions, so pin conversion settings for such a run.

## One million fractional UV triangles, synthetic

A synthetic mesh in a Linux cloud session (4 CPUs, Python 3.13.16, NumPy 2.5.3). Mesh: a 707 by 707 quad grid (999,698 triangles), every vertex jittered by up to 0.15 cell, rotated 0.37 rad and scaled to 0.0123 UV units per cell, so all coordinates are fractional and no edge is axis-aligned. The folded copy adds 25 faces, each a copy of a random face shifted 0.004 in u and v. Generator seed 1.

| Input | Command | Verdict | Wall seconds | Peak RSS, MB |
| --- | --- | --- | ---: | ---: |
| Clean, 999,698 triangles | `kit uvgate PATH --source-area 1e9 --overlap-only --mesh` | pass, 0 pairs, 1 component | 38.3 | 1,899 |
| Folded, 999,723 triangles | same | fail, 123 pairs, 26 components | 32.8 | 1,899 |

Wall time is the whole process: reading a 124 MB JSON file, the overlap check and the mesh check. Measured in process on the same meshes, the overlap check took 12.1 s (clean) and 10.4 s (folded), and the mesh check 18.4 s and 19.2 s. The mesh check, still pure Python, is the larger cost. Single runs, not three repeats.

Parity: twelve 800 to 803 face meshes from the same generator (jitter 0.3 cell, seeds 0 to 11, 0 to 3 folded faces) gave identical complete verdicts and sorted overlap pairs on the grid and reference paths, with 0 to 16 pairs each. Single runs. Synthetic geometry only; no scroll data was opened.

## Verification

- 18 fast/reference tests compare complete verdicts and sorted overlapping pairs on the UV, mesh and command fixtures, seeded random meshes, shared boundaries, degenerate and clockwise faces, epsilon boundaries, exact rational inputs, very large integers, subnormal coordinates and optional NumPy behavior.
- 20 winding-consistency tests ([windconsistency](../tools/windconsistency.md)) include an inconsistent three-step cycle, a consistent triangle, cross-chain cycles, disconnected components and a 2,001-step loop.
- 21 OBJ loader tests cover separate texture indices, seams, relative and forward indexing, source units, sampling, unsupported inputs, preserved duplicate and degenerate faces and a file changed during loading.
- On 21 October 2026 the released files passed 88 focused tests together in this repository: `python -m unittest tests.test_uvgate tests.test_meshgate tests.test_uvgate_cli tests.test_uvgate_fast tests.test_bench_uvgate_obj tests.test_windconsistency`.
