# Mesh hypothesis data (2026-10-07)

Derived numbers from public Vesuvius Challenge data: no CT, renders, meshes, labels or ink maps. Protocol, with its dated amendments: [`../../plans/2026-10-07-mesh-hypothesis.md`](../../plans/2026-10-07-mesh-hypothesis.md). Write-up: [`../../logs/2026-10-07-mesh-hypothesis.md`](../../logs/2026-10-07-mesh-hypothesis.md). Code: `kit/meshaudit.py` (tests in `tests/test_meshaudit.py`) and `scripts/experiments/2026-10-07-mesh-hypothesis/`.

## Input snapshot

The bucket catalogue `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/metadata.json` (Last-Modified 5 Oct 2026 15:58:43 GMT) was downloaded on 7 Oct 2026. Its decompressed bytes have SHA-256 `40517076dc5f2128599868b337e25a17922ebe70a22b238b990e109b6f82af0f`. Mesh headers, `meta.json`, surface-volume metadata and voxels were read over anonymous HTTPS on the same day. The bucket can change; rerunning later may give different numbers.

## Files

| File | Hypothesis | What one record is |
| --- | --- | --- |
| `transforms.json` | H2 | One stored cross-scan affine: landmark count, refit difference, fit and leave-one-out residuals (um), whether the matrix reproduces its own landmarks, landmark flatness, scale and anisotropy |
| `canvas.json` | H1 | One published surface volume: canvas size, matching mesh variants and render ratio, catalogue coverage ratio |
| `depth-plan.json` | H3 | The seeded choice of segments per (sample, native volume, cross volume) |
| `depth.json` | H3, H3b | One segment: per cross render, papyrus peak offsets per tile (um), the location control, evaluability |
| `depth-v1.json` | H3, H3b | The first run, before a tile-centre rounding fix (see the log); kept for the record |
| `geometry.json` | H4 | One segment pair: normal and tangential distances between the affine image of the reference mesh and the published cross mesh |
| `shift.json` | H5 | One segment pair: per tile, measured in-plane shift between the two renders' centre layers, the shift predicted from the landmark refit, and the peak-to-sidelobe ratio |
| `shift-v1.json` | H5 | The first run, before the rounding fix; kept for the record |
| `shift-psr-calibration.json` | H5 | Peak-to-sidelobe ratios of matched and deliberately mismatched tiles, for one control and one PHerc1667 segment |

## Reproduce

```bash
python -m kit meshaudit transforms --catalogue metadata.json --out transforms.json
python -m kit meshaudit canvas --catalogue metadata.json --out canvas.json
python -m kit meshaudit plan --catalogue metadata.json --out depth-plan.json
python scripts/experiments/2026-10-07-mesh-hypothesis/run_depth.py metadata.json depth-plan.json depth.json
python scripts/experiments/2026-10-07-mesh-hypothesis/run_geometry.py metadata.json depth.json geometry.json
python scripts/experiments/2026-10-07-mesh-hypothesis/run_shift.py metadata.json depth.json shift.json
```

Needs numpy and tifffile (imagecodecs for LZW-compressed meshes). On 4 CPUs the whole set took about an hour, almost all of it network reads.
