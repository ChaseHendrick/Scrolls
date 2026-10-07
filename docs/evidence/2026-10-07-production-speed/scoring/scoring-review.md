# Exact scoring speedup

The fresh AUC CLI is 1.25x faster on the frozen cached public PHerc0841 w00 crop: median wall time 372.00 ms to 298.12 ms. The warmed full AUC file operation is 2.62x faster: 106.37 ms to 40.63 ms. Every output field matches the baseline exactly across all six alternating pairs. The benchmark includes actual TIFF reads, Zarr labels/supervision reads and coordinate mapping, both point scores, and the paired 1,000-draw block bootstrap. This is a bounded single-core CPU result, not a full-volume or GPU throughput claim.

## Change

Only `kit/auc.py` changes in production. Block IDs use a linear counting pass when the key range is bounded by supervised pixel count. Sparse or huge coordinate ranges retain the original sorted-unique path, avoiding a allocation proportional to an arbitrary canvas extent. Histograms use flattened integer bincounts instead of repeated scattered `np.add.at` updates.

Globally empty histogram columns are removed before matrix multiplication and cumulative sums, using the same ordered column subset for both compared maps. The 1,024-bin score quantization, RNG draw sequence, shared scored pixels, ties and output schema remain unchanged. Compaction applies only when both the original and every resampled population are at most 2^26 pixels. All count products and half-tie sums are then exactly representable in float64; larger populations retain the historical reduction layout. There is no global cache or stale cross-run state.

The linear counting path adds O(supervised pixels) temporary arrays with a bounded key range. This is not a fixed-byte memory cap or a measured memory improvement. Peak RSS was not captured. Histogram compaction reduces inner arrays on this input, but that does not establish lower overall peak memory for every canvas.

HP and row-score code remain unchanged. The initial profile exposed duplicate HP label filtering as another possible optimization, but it was not implemented in this change. The dense row resize was a small component on this crop; full canvases need a separate benchmark and floating-output review.

## Frozen inputs and method

Baseline commit: `e2fd0c0afb5b3bb4e9f956f8cba648e674299949`, exported to `scoring-baseline`. Candidate export: `scoring`. Source and full input fingerprints are in `scoring-input-freeze.json`; the production candidate and benchmark helper were frozen in `scoring-candidate-freeze.json` before comparative timing. The rule hash is `4592e4582849ffd60880758ba6d7341ccd82ccd97939de18ac6f543a0cad912a`. An append-only amendment adds fresh CLI process timing, frozen before the first comparison.

Inputs are the completed public d9v2 w00 baseline forward/reverse TIFFs and downloaded published w00 inklabels/supervision stores. Requested canvas crop is [2720,3360,2720,3360], full surface [4220,4760], inner edge 64. Scores count zeros and use 1,000 paired draws, 107-pixel blocks and seed 20261007. No model inference, target data, download, GPU or paid compute was used.

Six pairs alternate AB, BA, AB, BA, AB, BA. Each variant uses a fresh subprocess, pinned to one CPU, with BLAS/OpenMP threads, Zarr concurrency and TIFF read workers set to one. Function measurements warm the full pipeline once and exclude interpreter startup/imports and JSON serialization; they include input reads and scoring. The separate CLI measurement uses the actual `kit.cli` entrypoint in a fresh process without warmup and includes interpreter startup, imports, scoring, JSON output and shutdown. Worker process wall time also remains archived but includes warmup and several operations, so it is not described as CLI latency.

## Full-operation results

| Operation | Baseline median | Candidate median | Ratio of medians |
| --- | ---: | ---: | ---: |
| Fresh AUC CLI process | 372.00 ms | 298.12 ms | 1.25x |
| AUC file operation, warm imports | 106.37 ms | 40.63 ms | 2.62x |
| Sequential AUC + HP + rows | 298.55 ms | 235.21 ms | 1.27x |
| HP file operation, unchanged | 175.12 ms | 177.85 ms | 0.98x |
| Rows file operation, unchanged | 21.22 ms | 20.78 ms | 1.02x |

The paired AUC speedups range from 2.34x to 2.87x; CLI speedups range from 1.06x to 1.40x. HP's median is 1.6% slower despite unchanged code, and individual HP/rows pairs vary more. These negative/control timings are retained rather than discarded. No confidence interval or universal speed guarantee is inferred from six pairs. The frozen primary acceptance rule is met; unchanged secondary median regressions remain below its 10% threshold.

## Correctness and remaining scope

Fifteen existing AUC tests and three overlap/bootstrap tests pass. Six original focused optimization regressions pass, including 20 paired pixel-oracle combinations of uint8, uint16 and three float ranges with zeros/inner edges, partial blocks, tied identity, shared occupied columns, sparse 10^12 keys, unsafe population fallback and existing explicit validation guards. An append-only test addendum adds requested single-map `other=None` cases after performance timing without changing measured production code; its final result is recorded in the validation receipt.

The baseline files are retained as a frozen old oracle. All measured operation/CLI dictionaries match its real-data output exactly, and the mathematical regressions use direct sampled pixels and pairwise Mann-Whitney ties rather than reproducing the optimized histogram logic. The performance contract covers supported finite maps. Malformed nonfinite floating maps may now raise a different underlying NumPy exception through bincount versus scattered updates; this change does not claim identical exception classes for every invalid input. A separate clean validation change can address that outside this performance patch.

Patch: `scoring-exact-speedup.patch`. Copy only `kit/auc.py` and `tests/test_auc_bootstrap_exact.py` from the candidate export. Raw timings and outputs: `scoring-benchmark-raw.json`; summaries: `scoring-benchmark-summary.json`; initial profile: `scoring-initial-profile.json`. No shared checkout was edited and no branch, commit, push or PR was created by this agent.
