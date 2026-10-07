# HP label-filter reuse, 7 October 2026

Implemented exact reuse of label-only high-pass filters within one `score_files` call. Baseline is merged PR24 main `c43c41a59ac3793b9a653fa236165f6f6b9d47a4`, not the earlier unoptimized bootstrap baseline. Only `kit/hpscore.py` and new `tests/test_hpscore_reuse.py` change. Candidate source SHA256 is `283753892087eb4f9a005fb1b9f5a6997497f0cf846016843e9d1c2182441abf`.

The original paired call applies ten Gaussian filters. Three repeat the same supervision, label key and conservative labelled-neighbourhood calculation for the control. Preparing these label fields once reduces paired filters to seven. Prediction coverage, normalized prediction filter, inner border, correlation support and rolled-key null support remain separate for each map. Nothing persists across calls. There is no model inference, global cache, threshold change or scoring-schema change.

The warm initial profile found HP dominated the real 640-pixel crop pipeline: HP205 ms, AUC86 ms and rows22 ms. On the public 2560-pixel crop crop, ten Gaussian filters accounted for 10.618 of the 11.785 profiled seconds. These are diagnostic profiles, not the comparative timing results below.

## Frozen benchmark

Rules, baseline/input fingerprints, production source, tests and harnesses were fixed before comparative timings. Original freezes remain intact. A before-timing append-only amendment removed redundant large-case worker timings: the larger case uses a fresh actual HP CLI process, whose wrapper also times the complete `score_files` call. One unmeasured CLI invocation per variant primes its input cache. The real 640-pixel crop case retains a warmed operation worker and combined HP/AUC/rows pipeline, plus a separate fresh HP CLI.

Both cases used five alternating pairs, AB/BA/AB/BA/AB, one Linux affinity core, numerical threads set to one, and TIFF/Zarr workers set to one. The median ratios summarize this fixed small repeated workload; they are not significance tests. Every measured report field for forward, control and nulls matched the frozen baseline exactly. On real 640-pixel crop every AUC/bootstrap and row-score field also matched. All 20 measured variant rows and negative or neutral component results are retained. Frozen inputs were checked before and after the benchmark.

The real 640-pixel crop workload is the existing actual CT-derived public PHerc0841 w00 d9v2 forward/reverse pair at 9.366 um, crop `(2720,3360,2720,3360)` in full surface `(4220,4760)`, level 2 labels, inner 64. The larger workload uses a 2560 by 2560 crop `(10240,12800,10240,12800)` of the official published 2.403 um map, full raster `(16460,18560)`, with its matching published labels mapped from level 2 and inner 64. Its control is a synthetic 523-row roll, solely a workload/parity fixture; it is not a reverse-depth control or ink evidence. Exact public URLs, source hashes and crop derivation are recorded in `large-hp-fixture.json` and the public-input receipt.

## Complete-operation results

| Case and measurement | Baseline median | Reuse median | Ratio of medians |
| --- | --- | --- | --- |
| Real 640 crop warm HP file call |0.180190 s|0.137200 s|1.3133x|
| Real 640 crop fresh HP CLI process |0.650112 s|0.602402 s|1.0792x|
| Real 640 crop warm HP/AUC/rows pipeline |0.254305 s|0.196488 s|1.2943x|
| Public 2560 crop complete HP file call inside fresh CLI |10.755387 s|7.485103 s|1.4369x|
| Public 2560 crop fresh HP CLI process |11.276091 s|7.950575 s|1.4183x|

A file call includes both prediction/control TIFF loads, label reads and grid mapping, all filters, masks, correlations, rolled nulls and report return. Fresh CLI wall time includes interpreter startup, imports, I/O, scoring, JSON stdout and shutdown. The warm pipeline includes repeated file reads for each tool, the existing 1,000-draw paired AUC/bootstrap computation and reverse controls. It does not include interpreter startup. The old PR24 speedup is not compounded with these ratios.

The unchanged AUC and row operations had median ratios 1.0612x and 1.0524x here; source hashes are unchanged, so these small timing changes do not establish new component optimizations. The raw timings and all five paired ratios are in `hp-benchmark-summary.json` and `hp-benchmark-raw.json`.

## Memory and validation

Peak RSS is Linux process high-water `ru_maxrss`, in KiB, including imports and all operation buffers. It is not incremental function memory. Real 640 crop fresh-CLI medians were 88,916 KiB baseline and 88,600 KiB reuse. Public 2560 crop medians were 532,248 KiB baseline and 525,868 KiB reuse. The real 640-pixel crop warmed worker, including warmup and repeated combined operations, was 89,684 KiB versus 89,436 KiB. These differences are small; this is a speed optimization, not a demonstrated general memory reduction.

Nine original and focused HP tests passed. Independent differential review imported the actual PR24 source: 368 array comparisons, 374 file comparisons, 11 matching exception outcomes and 373 formatting comparisons passed. It additionally checked actual cropped TIFF/NPY/Zarr mapping, input immutability, label-buffer release after return and the ten-to-seven filter count. See `scoring-independent-review/`.

The implementation still uses dense arrays and Gaussian filtering. The 2560 crop does not establish full 305-million-pixel canvas throughput or memory viability. No rendering, inference, GPU, Mac or scientific ink-recovery improvement is claimed. Existing unsupported-input semantics were not redesigned.

`hp-reuse.patch` is Git-applicable against c43 main. The shared checkout was not edited by this task. Static checks and the benchmark sources/inputs are retained outside the checkout; raw TIFFs and label arrays are excluded from the source/evidence archive.
