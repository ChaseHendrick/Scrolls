# CPU inference layout screening: rejected

The single planned channels-last experiment completed on the fixed 192x192 center crop of the published PHerc0841 reader input. No labels, AUC or target outputs were inspected. It used the official d9v2 reader and tile engine, batch 1, two CPU threads, float32, stride 42, Hann blending and forward/reverse/shuffle controls. The only candidate change was PyTorch's built-in 2D convolution weight-layout conversion. All 63 Conv2d layers converted; logical checkpoint tensor values remained equal.

The candidate failed both frozen screening requirements. Median three-control operation time rose from 5.35897 to 6.97131 seconds. The baseline/candidate ratio was 0.76872; the candidate took about 30.1% more wall time. All three paired ratios were below one. This is a warm 192x192 operation result, not fresh CLI latency or complete-canvas performance.

Forward and reverse maps matched the baseline exactly in each pair. The shuffled-depth map differed by one uint8 pixel with maximum difference 1 in each of the three pairs. This fails the hard byte-parity gate even though the numerical difference is small. No tolerance was relaxed, no default changed and no larger experiment was started.

Total worker CPU time was 80.54 seconds, under the 175-second budget. The process peak RSS was 1,062,846,464 bytes (0.990 GiB). Both model copies coexist in the worker, so that figure cannot establish variant-specific memory use. Input preparation, model loading and warmup are outside each operation timer but inside total CPU/RSS accounting.

The complete rule, append-only harness freeze, exact source hashes, timed pairs and all comparison counts are retained. The selected input and predicted TIFFs remain outside the repository; their hashes are recorded in the findings manifest. This negative result applies to this one CPU, model, crop and conversion. It does not reject other layouts, architectures or hardware generally. Existing contiguous inference remains the correct default. The potential repository launcher can still expose official configuration and provenance, but this candidate supplies no reason to add an inference-layout optimization.
