# CPU scaling checks after PR #24

Recorded 7 October 2026. Geometry and HP experiments compare against merged PR #24, commit `c43c41a59ac3793b9a653fa236165f6f6b9d47a4`. Row scoring compares dense and sparse modes in the same updated build; the dense algorithm remains unchanged from PR #24. These tests use existing cloud CPUs and public PHerc0841 controls. Earlier speedup ratios are not multiplied into these measurements. Raw inputs, model maps and weights stay outside Git.

## Full-map row scoring: optional sparse resizing

The largest measured gain is **7.0073x faster complete row-scoring operation** on a public 305,497,600-pixel map: 39.7320 to 5.6701 seconds median. Dense area resizing builds enormous overlap matrices and multiplies their mostly zero entries. The optional sparse path stores the same float32 overlap coefficients and computes only their nonzero contributions. It is available through `kit rowscore --fast-resize`; [usage and numerical compatibility](../rowscore.md).

| Fixed public input | Dense operation median | Sparse operation median | Ratio |
| --- | --- | --- | --- |
| Central 8192 by 8192 crop | 5.279072 s | 1.968208 s | 2.6822x |
| Full native 16460 by 18560 map | 39.731961 s | 5.670122 s | 7.0073x |

Each final comparison uses three alternating pairs of isolated fresh workers, one CPU affinity core and one numerical thread. The operation timer begins before importing `kit`, invokes the real `cli.main` path, and includes TIFF loading, normalization, resizing, scoring and JSON construction. It excludes interpreter startup/shutdown, result hashing and evidence writes. This is complete file scoring, not a literal external `python -m kit` process-wall timer and not model inference. Parent-observed process wall is retained separately in the raw records. Those full-map dense processes took 39.74, 39.96 and 53.33 seconds; the sparse ones took about 5.92 seconds each. Variability is retained rather than hidden.

The full native input is the official published PHerc0841 w00 2.403 um autoresearch map, with exact URL, bytes and SHA-256 in the input receipt. The central crop was selected geometrically before its results were examined. Its initial screening pair and the full-map screening pair are separate from the final repeated medians. The latter took 55.84 versus 7.91 seconds for the operation; an append-only amendment authorized the three fresh pairs before they ran. Each child had a 120-second wall cap and 10 GiB RSS cap; none hit a cap.

Resized float-array hashes and every historical score field matched on both real inputs in all final pairs. This is **not a universal exactness guarantee**. Other finite synthetic shapes differ by float32 rounding, and near-tied FFT peaks can select another angle or period. Signed cancellation cases also disprove a universal small-ULP claim. The default dense path and its records are unchanged. The option is explicit, requires SciPy and records its backend/numerical caveat in JSON and text. Nonfinite clipped arrays retain the dense path. Eight focused tests cover coefficients, rounding, negative controls, default preservation, ties, dependency errors and CLI provenance.

Median worker peak RSS through scoring was 1.661 versus 1.656 GB for the crop and 7.098 versus 6.536 GB for the full map, about 7.9% lower on the full map. The instrumented workers retain the resized array for later parity checks, so these are not uninstrumented CLI memory measurements. The resize step itself improved from 34.403 to 0.386 seconds on the full map, but the 7.0073x whole-operation ratio is the useful throughput result. The FFT and other image-sized arrays remain substantial costs.

## Surface geometry: exact triangle-edge batching

The remaining geometry profile identified repeated triangle-edge projection work. Matched float32/float64 inputs now evaluate the three edges together, preserving coordinate reductions, interior/edge ordering and tie handling. Half, wider and mixed dtypes use the original helper. Independent review caught longdouble truncation and a float16 layout difference in earlier candidates; both rejected versions and reproductions are retained. The solver, physical limits, bounds, certificates, ambiguity handling and refusal rules remain unchanged.

| Measurement | PR #24 median | Updated median | Ratio |
| --- | --- | --- | --- |
| Complete correction process, existing real crop | 2.513779 s | 2.276141 s | 1.1044x |
| Geometry within that correction | 1.776881 s | 1.536820 s | 1.1562x |
| Larger 4096-point projection against full reference | 7.285543 s | 6.483104 s | 1.1238x |

Each case used five alternating fresh-process pairs plus one warmup per version, one CPU core and one numerical thread. The complete correction worker includes imports, input reads, correction, output writes, hash checks and exit; it calls the production API directly, so its timer is not a CLI parser benchmark. The larger test is a fixed 64 by 64 native w00 crop against the full cached ag896 reference. It measures correspondence alone, without new rendering, reader maps or a complete correction run on the larger mesh.

All 24 main runs and four schema-1/displaced-control runs matched their baseline report fields, projection arrays and output-file hashes; tangential refusal also matched. The real correction still accepts zero edits and flags 16 regions. Larger projection eligibility and refusal diagnostics also remain identical. Independent checks cover dtypes, memory layouts, degeneracies, ties, heap order and budget exhaustion. Fifteen geometry tests passed.

Median process peak RSS stayed essentially unchanged: 84.959 versus 84.955 MB for complete correction, and 69.419 versus 69.431 MB for the larger projection. This is an additional 9.45% reduction in complete-correction wall time relative to PR #24 on this crop. It is not a new total speedup relative to the older pre-PR #24 implementation. See the [geometry evidence](../evidence/2026-10-07-production-scaling/geometry/benchmark-result.json).

## High-pass scoring: exact reuse

Paired high-pass scoring repeated three Gaussian filters of the same labels and supervision mask. The implementation prepares those fields once per file-scoring call, reducing ten filters to seven. Each prediction retains its own coverage, inner border, normalized filter, correlations and rolled-label nulls. There is no persistent cache.

Five alternating pairs per case ran with one CPU affinity core and one numerical thread, after fixed input/source/harness hashes and one warmup per version. Every reported field matched in all 20 measured variant rows. The real 640-pixel crop uses actual forward/reverse d9v2 maps. The public 2560-pixel crop uses the official 2.403 um map and matching labels; its second map is a synthetic roll used only to test computation and parity, not a depth control or accuracy result.

| Measurement | PR #24 median | Updated median | Ratio |
| --- | --- | --- | --- |
| Real 640 crop, warm paired HP file operation | 0.180190 s | 0.137200 s | 1.3133x |
| Real 640 crop, fresh HP CLI | 0.650112 s | 0.602402 s | 1.0792x |
| Real 640 crop, warm sequential HP/AUC/row scoring | 0.254305 s | 0.196488 s | 1.2943x |
| Public 2560 crop, paired HP operation inside fresh CLI | 10.755387 s | 7.485103 s | 1.4369x |
| Public 2560 crop, fresh HP CLI | 11.276091 s | 7.950575 s | 1.4183x |

File operations include map and label reads, grid mapping, all scoring and result construction. CLI time also includes startup, imports, JSON stdout and exit. The combined scoring measurement does not include rendering or inference. AUC and row implementations were unchanged in this comparison; their small timing differences are retained as variance in the raw results.

Median fresh-process peak RSS was 88,916 versus 88,600 KiB for the small case and 532,248 versus 525,868 KiB for the larger case. These are Linux process high-water marks, not isolated buffer sizes. This establishes a speed gain on these cases, with little measured memory change. It does not establish full-canvas HP feasibility.

Independent review passed 368 array comparisons, 374 file comparisons, 11 matching exception cases and 373 formatting comparisons against the actual baseline. Nine HP tests passed. See the [HP report and raw evidence](../evidence/2026-10-07-production-scaling/hp/hp-review.md).

## Rejected CPU inference layout

A fixed 192 by 192 public CT crop tested PyTorch's channels-last layout for the official d9v2 model's 2D convolutions. Checkpoint values, fp32 precision, the official villa engine, preprocessing, stride, batch size and controls stayed fixed. Three alternating pairs each ran forward, reversed and shuffled depth through the same engine.

The candidate failed both declared gates. Median time for the three maps increased from 5.35897 to 6.97131 seconds, about 30% slower. Every shuffled result differed from its paired baseline by one uint8 pixel of magnitude one. Forward and reverse maps matched. No inference setting was changed or larger run launched. The [negative result](../evidence/2026-10-07-production-scaling/inference-layout/screening-report.md) and its fixed plan are preserved alongside successful experiments.

## Interpretation

The integrated repository passed 229 tests and 39 experiment regressions. Fresh real surfacefix and HP CLI invocations preserve all stdout, stderr, output files and exit statuses; surfacefix still returns its expected abstention exit code 1. Actual row CLI checks preserve default stdout exactly and correctly label both directions when sparse resizing is requested. PR #24's provenance seal verifies against its historical source export, and all prior tracked evidence remains unchanged.

These are engineering measurements on public model output. They do not establish recovered text, improved correction accuracy, a new reader, GPU performance or total scroll-processing throughput. Named operations, dimensions, controls and numerical compatibility matter when reusing the results. All timings used cached local inputs. SHA-256 records establish artifact integrity, not scientific validity.
