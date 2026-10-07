# 7 October 2026: merged public review validation

This closes public PRs [#25](https://github.com/ChaseHendrick/Scrolls/pull/25), [#26](https://github.com/ChaseHendrick/Scrolls/pull/26) and [#27](https://github.com/ChaseHendrick/Scrolls/pull/27) at combined main commit `25dd450dda3a3da69b02374198fe28055c3b66cc`. This follow-up changes documentation and validation records only. No training, inference, data downloads, paid compute or new performance measurements were performed for this closure.

PR #25's fine-tuning scaffold remains unrun. Its reviewed implementation protects unknown labels during pooling, loads the pinned checkpoint strictly, handles quantization and zero coverage conservatively, requires explicit execution gates, isolates worker code checkouts and rechecks source/recipe/output bindings before using crops, teacher maps or comparator maps. A precise family-level research decision rule remains required before a separately authorized launch. GPU execution and remote storage remain unvalidated.

PR #26's crop-scan helper now rejects invalid input domains and excessive estimated temporary work. Its historical experiment is gated against accidental reuse. The archived nonfinite bootstrap intervals invalidate R1/R2 decisions; a separately preregistered rerun is needed because the missing interval details cannot be recovered. The point-AUC proxy observations are limited to their measured cohort and do not establish a general production speedup. Historical results were qualified in prose while their raw bytes were preserved.

PR #27's measured performance results and public/private routing are described in the [scaling log](2026-10-07-production-scaling.md). The later merge reviews do not multiply or extend those operation-specific speed ratios. Earlier public material remains in Git history even when its current location is private.

Validation on the combined main commit:

- Local numerical suite: 253 tests, 252 passed and one CPU-Torch dependency skip.
- Existing CPU Torch runtime: all 17 focused fine-tuning guard tests passed, covering that skipped tensor case.
- [Combined-main CI run 37657023237](https://github.com/ChaseHendrick/Scrolls/actions/runs/37657023237): Python 3.10, Python 3.13 and numerical jobs passed. Its six experiment suites passed 11 + 1 + 7 + 6 + 6 + 8 = 39 tests. This already completed CI evidence was retained rather than rerunning unchanged experiments.
- The scaling provenance seal was verified against historical commit `047ee0688d5a00ac7d62bf91686bd61dd48e44ad`, including all recorded file fingerprints. Its record digest is `5cbdada673f3c970803a0555db36b1a2fcf60cc85bd8c23094f1bb952cd288cb`. Existing evidence files are byte-identical between that commit and combined main. Current documentation is not substituted for historical sealed inputs.

The [validation archive](../evidence/2026-10-07-merged-review-closure/) contains test output, public CI receipts and a SHA-256 manifest. Hashes establish file integrity, not research validity or an externally established preregistration time. All target-specific research stays in Scrolls-private.
