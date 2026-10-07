# Real-control I/O profile, 2026-10-07

Input reading is a small part of the current cached-crop inference workload. No model was run and no production speedup was deployed. Prioritize the independently measured geometry CPU bottleneck over these I/O targets.

## Measurements

One configured numerical/Blosc decode thread; TIFF writer concurrency unchanged; warm page cache; three repetitions per path. Actual cached PHerc0841 surface inputs, not a phantom. Source reader: official villa `e0bbb8b40a2db58b1d71864f286eb85717e59e64`; Scrolls context HEAD `e2fd0c0afb5b3bb4e9f956f8cba648e674299949`. Context files and actual input content hashes are preserved.

| Stage | Baseline median | Alternative median | Exact-output evidence |
| --- | ---: | ---: | --- |
| 588 official reader patches: forward, reverse, shuffled; 17 x 640 x 640; patch128 stride42 | 1.020863s per-patch Zarr | 0.308509s bounded decoded preload, including preload and hash/copy | Full concatenated patch-byte SHA-256 matches all six trials |
| 28 x 640 x 640 TIFF export, including writes | 0.281406s per-layer fallback | 0.090810s existing default banded export | Full decoded TIFF pixel-byte SHA-256 matches all six trials; equal total file bytes |

The reader primitive is 3.31x faster, but saves only 0.712s across three maps. The earlier actual reader log has ~76.8s/~71.1s intervals between direction starts at two CPU threads. Those are different runs and thread settings, not a matched end-to-end benchmark; they show why a threefold I/O primitive improvement would not imply a threefold model speedup. Preload holds 13,926,400 raw bytes; whole profile peak RSS was 72.6MB. Model and normalization were not altered; model-map equivalence would still need a separate test before deployment.

The export result (3.10x) verifies an existing optimization. Default banded export is already deployed whenever selected stack size fits the 4GiB budget. It is not a new production gain. The renderer store's legacy `<u1` metadata spelling was normalized to equivalent `|u1` only in an isolated copy so Zarr3 could open it; chunk bytes and frozen source store were unchanged.

## Ranked follow-up targets, both lower priority than geometry

1. Provenance-checked reuse of existing TIFF layer exports on reruns. `mac-w045.sh` lines232-243 unconditionally deletes and exports layers even when the later predictions are reusable. The QUICK path already avoids an unused full export. A completion manifest must include source content hashes, crop/depth/order/compression, exporter identity and every output hash; existence alone is unsafe. On this actual crop, hashing source render files took median 0.009079s and the existing 28 TIFF files 0.005777s, versus 0.090810s to export. These costs use different existing TIFF compression and prove only fingerprint overhead, not a validated reuse implementation. Historical full-w045 export was 23s; this profile does not measure full-w045 reuse savings.
2. Memory-capped decoded input cache at the official FlatPatchReader boundary. It avoids repeated overlapping-chunk decode with identical input bytes and is easy to bound for these small crops. Savings here are too small to justify implementation now. Full-segment volumes need a strict memory cap/fallback and DataLoader/process behavior tests; no whole-volume preloading assumption is warranted.

The CPU adapter already builds one model and reuses it across three depth controls. These controls require distinct model computations; dropping one is not an exact-output optimization.

## Historical claim correction

`kit/layers.py` currently contains no 14x claim. The community log compares 23s for a full export against ~72s for layer-by-layer reads, which differ in measured scope and do not establish a matched end-to-end export ratio. This new crop benchmark includes TIFF writes for both paths and reports only the existing banded-export result.

## Reproduce and audit

`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 /workspace/Scrolls/.venv/bin/python /workspace/scrolls-env/production-speed/io-review/profile_io.py`

Results: `profile-result.json`, `fingerprint-result.json`; inventory: `inventory.json`; actual content receipt: `input-receipt.json`; source snapshots: `source-context/`; integrity list: `sha256-manifest.json`. The inventory includes sparse CT-cache metadata and does not imply those full CT volumes are present. No new data, reader inference, target maps, downloads or shared-repository edits occurred.
