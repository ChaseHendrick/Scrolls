# Independent HP scoring reuse review

Status: approved for exact-output benchmark on the reviewed source. No blocking correctness issue found.

Baseline: `c43c41a59ac3793b9a653fa236165f6f6b9d47a4`. Candidate: `/workspace/scrolls-env/production-speed-v2/scoring/kit/hpscore.py`, SHA256 `283753892087eb4f9a005fb1b9f5a6997497f0cf846016843e9d1c2182441abf`.

The refactor prepares label key, high-pass key, and conservative labelled-neighbourhood core once within each `score_files` call. These fields depend only on labels, supervision, and voxel spacing. Each prediction still computes its own positive-value coverage, high-pass prediction, inner-edge mask, rolled-null support, and correlations. The combined mask is newly allocated and never mutates the shared core. No global cache or reuse across calls exists.

Independent differential checks imported the exact baseline source as a separate module, rather than restating its formula. Tiny fixtures covered uint8/float32/float64 and constant/zero predictions; full, holed, half, sparse and empty supervision; separate forward/control holes; non-contiguous arrays; multiple voxel sizes and inner borders; singleton squeezing; invalid dimensions, control shapes, crop metadata, label level, voxel spacing, and nonfinite values. Existing error outcomes, including nonfinite legacy behavior, were preserved rather than silently changed.

Results: 368 exact score_array comparisons, 374 exact score_files comparisons, 11 equal exception type/message outcomes, and 373 matching formatting outcomes. Actual temporary NPY/TIFF plus Zarr label/mask loading and cropped-grid mapping also matched. All nine original/new HP unit tests passed.

A direct lifecycle check confirms label-only arrays are released after the paired call; input arrays remain unchanged. Source inspection finds no retained global state. Gaussian filter calls for a paired call fall from 10 to 7: only the three repeated label-only filters are eliminated. Label buffers remain live while the control file loads and is scored; they were previously recreated during control scoring, so this is a per-call lifetime change rather than an unbounded cache. No production-memory or timing claim was evaluated here.

Evidence: `evidence.json`, `checks.log`, `check_compatibility.py`, and `unit-tests.log`. All checks used one thread and only small synthetic fixtures; shared checkout source was not edited.
