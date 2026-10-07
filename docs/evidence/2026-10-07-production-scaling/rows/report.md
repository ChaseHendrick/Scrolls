# Large public-map row scoring, 2026-10-07

The opt-in sparse area resize substantially reduced row-scoring time on one real full-size public ink map. It does not speed up inference or rendering, and it is not a new ink detector. Default row-score behavior is unchanged; the optional method can change floating-point rounding and FFT peak selection on other inputs.

## Primary repeated result

The input is the official public PHerc0841 w00 `2.403um` autoresearch ink map, native shape 16460 x 18560 (305,497,600 pixels), SHA-256 `c980b60dc457037d0cfe8c654619c23f3fd673e2847d64aed09cbdb3e26f7bde`. Its exact public URL is preserved in `public-input-receipt.json`. This is not the 9.366um surface-volume grid. Downloaded 27 public map/label files totaled 23,782,639 bytes; no CT, weights or models were downloaded for this task. Matching labels have the same native canvas but were not used to score rows.

Both modes ran from the same exported candidate build in `rows-fixed`, based on Scrolls `c43c41a59ac3793b9a653fa236165f6f6b9d47a4` (PR24). The dense resize coefficients/function and default algorithm are unchanged. This is a same-build dense-versus-sparse comparison, not a comparison between separate historical and modified exports. Seven underlying default helpers were checked for AST equality; the 8 new regression tests and 11 existing row tests all passed.

Three fresh paired trials followed a separate screening pair. Order was dense/fast, fast/dense, dense/fast. Workers used one CPU affinity core with BLAS thread counts 1. Each child had a 120-second wall cap, 10GiB RSS stop and 16GiB virtual-memory cap. All completed. Sources, rules, input receipts and the repeat-budget amendment were frozen before the corresponding measurements.

| Measurement, median of 3 fresh trials per mode | Dense default | Optional sparse |
| --- | ---: | ---: |
| Fresh-worker cli.main operation | 39.7320s | 5.6701s |
| Area-resize portion | 34.4033s | 0.3863s |
| Parent-observed process wall | 39.9602s | 5.9249s |
| Maximum instrumented-worker RSS | 6.610GiB | 6.087GiB |

The primary operation ratio is 7.01x; the parent-observed ratio is 6.74x. **The primary timer is an in-process fresh-worker `cli.main` operation: it includes kit imports, file reads, scoring and JSON construction. It excludes interpreter startup/shutdown, output hashing and evidence writes.** Parent wall also includes those extras and 0.1-second polling. Neither is a pure resize-kernel timing. RSS includes the instrumented worker and a retained resize-array reference; it is not an uninstrumented production memory guarantee.

| Mode/trial | Worker operation seconds | Resize seconds | Peak RSS GiB |
| --- | ---: | ---: | ---: |
| baseline, run 1 | 39.5550 | 33.4233 | 6.610 |
| baseline, run 2 | 39.7320 | 34.4033 | 6.610 |
| baseline, run 3 | 53.0718 | 41.2014 | 6.610 |
| fast, run 1 | 5.6701 | 0.3962 | 6.087 |
| fast, run 2 | 5.6670 | 0.3817 | 6.087 |
| fast, run 3 | 5.6812 | 0.3863 | 6.087 |

Individual parent wall times were dense 39.7425,39.9602,53.3305s and fast 5.9230,5.9249,5.9257s. The third dense trial was slower; all trials remain in the summary. The separate screening pair was 55.8427s/7.9078s for the primary operation (parent wall 56.0443s/8.1378s), and is excluded from these medians. These are small local timing samples on one map, not a confidence interval or a promise across all machines/maps.

## Compatibility and useful limits

All six fresh full-map resized-float arrays had the same SHA-256: `56ba4f35429e2ed899cd45dd02d280dd47645984a43dd33adff07685ab7d6361`. Every historical output field matched: score 36.1, period 5.78mm, angle -66.6 degrees, valid-pixel count 216,957,844, mean ink 0.1286, p99 1.0 and fraction above half 0.1254. These are row-triage statistics from existing model output, not a reading. Opt-in JSON adds only resize provenance fields. All 16 archived worker resize hashes, including screening and crop runs, were verified against the actual saved float arrays.

The separate fixed central 8192 crop (rows 4134:12326, columns5184:13376) had its own screening pair followed by 3 new paired trials. Worker medians were 5.2791s/1.9682s (2.68x); parent wall 5.4201s/2.1102s. Pixel hashes and old fields also matched. Maximum RSS was 1.547GiB/1.542GiB, a negligible memory difference. The first fixed origin 4096 crop abstained because its valid component left too few FFT-band bins; it remains preserved and was not presented as a successful row result.

Universal bitwise parity fails. Positive fractional-grid controls showed resized-pixel differences up to1.79e-07 and up to3 output ULP in this assessment. Signed high-dynamic-range cancellation controls had much larger relative/ULP differences, so no generic few-ULP bound is claimed. The row-score path clips its resized inputs to nonnegative values in[0,1]. All12 assessed full scoring records matched, including nondivisible dimensions, quantized ties, clipping thresholds and near-tied spectra, but this does not prove universal rounded-score, angle or period stability. Mirrored/tied FFT peaks can switch under rounding.

Sparse weights store exactly the same nonzero float32 cell-overlap coefficients as the dense calculation; their accumulation order differs. The default remains dense. `--fast-resize` and the keyword-only `fast_resize=True` API are explicit opt-ins; JSON/human output labels them. Nonfinite clipped arrays use the original dense fallback to preserve propagation/error behavior. Missing SciPy raises a clear opt-in error. See `docs/rowscore.md` and the focused regression tests.

## Inventory and scope

The earlier local inventory found only small cached crop maps (mostly 640 x 640), not full public inference canvases. Public S3 supplied this full native w00 map and matching labels. The official w045 map listing also exposes a 2.399um map 69,661,736 bytes and a 1.129um map 50,049,737 bytes; they were not downloaded or benchmarked. Their availability does not establish local full-volume availability or a scoring speedup.

`kit/rowscore.py` originally builds dense n_out by n_in overlap matrices and performs dense products although only about 4 inputs per output cell contribute. At this native canvas, final dense float32 weight matrices occupy about 271MB and 344MB, with substantially larger float64 construction temporaries. The sparse representation avoids those zero-weight products. The original upstream Bullo27 implementation uses OpenCV area resize; this fixes a bottleneck in Scrolls' NumPy port rather than establishing a new general image-resizing method.

No new readers, training, target scans, GPU work or quality-changing inference settings were involved. This agent changed only the isolated export; the parent integrated the four reviewed source/test/doc files separately.

## Reproduction and integrity

The map URL/content receipt, frozen rules, code receipts, runtime/library versions, all individual worker JSON records, parent run-status files, tests and scripts are in the evidence archive. `stage_public.py` reproduces the bounded public acquisition from the saved S3 listing. `run_rows_pair.py` drives capped isolated workers. The central crop is selected by fixed geometric coordinates, not by its score. Rules/code hash receipts preserve integrity; they are not an independent timestamp service.

The archive excludes all ink maps, label chunks, crops and resized arrays. Their URL/content or raw-array digests remain in the receipts/results. An initial central fixture used .npy, which the existing TIFF-only loader refused before any scoring; its failure log and the identical-pixel TIFF conversion receipt are preserved. No numerical recipe was altered to obtain a successful run.
