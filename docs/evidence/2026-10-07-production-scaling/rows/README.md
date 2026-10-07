# Optional sparse row-score resize evidence

The native public PHerc0841 w00 map comparison measured a 7.01x median fresh-worker scoring-operation improvement (6.74x parent-observed process wall) in 3 paired trials. Both modes use the same candidate build; the dense default is unchanged. Read report.md for individual timing variance, memory, numeric compatibility and limits. This is postprocessing, not an inference or ink-recovery claim.

Public input URL/content receipts, fixed crop/rules, source/code receipts, runtime, tests and every individual result are preserved. No maps, label chunks, crops or resized arrays are included. Their digests remain in the receipts/results.

Reproduction scripts are Linux-specific bounded worker harnesses and refer to the documented /workspace experiment layout. stage_public.py requires the saved w00-prefix.xml and fetches less than 100MB public control data. The candidate source snapshots are under candidate/. The controller sets one CPU affinity core and 1 BLAS thread; it caps each process at 120 seconds and 10GiB RSS (with 16GiB virtual-memory limit).

The primary operation timer includes kit imports, read, scoring and JSON construction. It excludes interpreter startup/shutdown, hashing and evidence writes; parent process wall is separate. RSS is from an instrumented worker retaining a resize-array reference. Screening pairs are excluded from the 3-pair medians. Sparse arithmetic is opt-in and is not universally bit-identical; all measured real-map resized arrays and old output fields matched.

sha256-manifest.json lists every archive file and its SHA-256. All archive hashes and 27 public input-file receipts were verified; 16 worker resize-array digests were independently checked against the actual saved arrays outside this archive. Hash receipts provide integrity, not an independent timestamp service.
