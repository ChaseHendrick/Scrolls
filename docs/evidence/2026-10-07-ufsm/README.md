# UFSM review evidence, 7 October 2026

[Assessment and recommendations](../../logs/2026-10-07-ufsm-review.md) for Chase Hendrick, pinned to SuperOptimizer/ufsm `d86a00cff5ab198e6b7864f89e49a6101746dc9f`.

- `controls/production-io-review.json` records 29 passing CPU tests with synthetic or mocked production inputs, exact commands, source hashes and reuse recommendations.
- `controls/scrolls-gap-receipt.json` preserves two synthetic current-Scrolls contract checks. Existing provenance detects changed files when explicitly asked to recheck them; the fetch and ledger checks have different contracts. No actual scientific input corruption is alleged.
- `geometry-audit/report.md` records nine passing upstream geometry tests and the limited independent numerical deformation check. It distinguishes triangle validation from Scrolls' bilinear surface convention and implementation tests from quality evidence.
- `grid-review.md` is a source assessment with proposed runtime comparisons. It does not claim actual reader crop invariance or performance measurements.

These are exact copies of authored review records, logs and local check scripts. No upstream project source, weights or papyrus arrays are bundled. `archive-origins.json` binds each copy to its original path and hash; absolute paths in reports describe the review workspace. External inputs must be restored from their pinned sources to reproduce the checks. The lack of a top-level UFSM license was recorded; vendored-component licenses do not establish permission to copy the project as a whole.

Verify this directory with `sha256sum -c SHA256SUMS`. From the Scrolls root, verify the archive and assessment with `python -m kit provenance check docs/evidence/2026-10-07-ufsm.provenance.json --files`. These post-review hashes establish integrity, not an external pre-run timestamp or scientific validity. No Scrolls production implementation was changed.
