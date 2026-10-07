# v8in-w00 (2026-10-07)

Job `v8in-w00` of [`../README.md`](../README.md), CPU container (4 cores, 15 GB). In progress.

- `run.sh`: crop zarr and layer folders, then `ink_9um` seed 42 and d9v2 (villa PR #1865, both directions), v8in forward stride 42, reverse stride 42, depth-shuffled forward stride 42, forward stride 21. Resumable.
- `score.py`: AUC and `hp_r` for every map and the ensembles; writes `results.json`.

d9v2 checkpoint sha256 `50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966` (matches the value in `docs/logs/2026-10-07-community-scan.md`).
