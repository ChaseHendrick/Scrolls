# Evidence archive: controlled papyrus tests, 7 October 2026

Prepared for Chase Hendrick. This archive contains exact copies of rules, amendments, as-executed analysis code, source receipts, measurements and reviews from public PHerc0841/PHerc0139 controls and a public villa PR review. It contains no raw CT, surface coordinate arrays, labels, weights, prediction images or target-scroll candidates.

Start with the [research log](../../logs/2026-10-07-followup-tests.md), [coarse support review](../../logs/2026-10-07-coarse-support-mask.md) and [results ledger](../../results.json). Scientific interpretations and limitations belong there; files here preserve the evidence, including failures.

| Directory | Contents |
| --- | --- |
| `physics` | Fixed reconstruction-transfer prediction, controls, padding and failed transport audit |
| `orientation-pherc0841`, `orientation-w045` | Comparisons of official renders with published CT surface stacks |
| `w045-baseline` | Frozen scoring rule, six matched reader maps' measurements, code, external settings audit and completion receipts |
| `surfacefix-design`, `geometry-review` | Continuous correspondence diagnostics, historical replay and independent code review |
| `affine-v2`, `affine-v3` | Failed first estimator, amended replacement, algorithm controls and failed fresh CT registration |
| `supervised-surfacefix`, `supervised-review` | Frozen supervised correction experiment, official render/reader checks, zero-acceptance and label readouts, independent scoring review |
| `pr1996-review` | Public source pins, executed test receipts, saved-table checks and review; upstream sources are linked and hashed rather than vendored |
| `pr1996-geometry` | Exact upstream helper tested on cached meshes, fixed mask/geometry controls and continuous correspondence supplement |
| `support`, `verification` | Historical helper code and the final 146-test repository log |

`archive-origins.json` records the original path, byte count and SHA-256 for each copied artifact. Every copied file was compared with its original during archiving. Embedded manifests may refer to large local artifacts that are intentionally outside Git; those manifests and local verification receipts are preserved. Absolute paths describe the execution workspace, not files bundled in this repository. Archived Python scripts are historical execution records, not a standalone installer; reproduction requires the pinned upstream tools, public inputs and recorded local layout.

Frozen rules and amendments remain unchanged. In particular, `supervised-review/prereg-precedence-note.json` records why the earlier root rule's 1,000 bootstrap draws govern the supervised readout rather than the auxiliary 300-draw summary. Unsuccessful controls and zero-acceptance results are retained. The first affine estimator failed before fresh CT acquisition; the replacement passed its controls but failed real registration. No phase candidate maps were made.

From this directory, verify all bundled files with:

```bash
sha256sum -c SHA256SUMS
```

The adjacent [provenance record](../2026-10-07-followup.provenance.json) additionally binds this archive, relevant code and the final write-up. From the repository root:

```bash
python -m kit provenance check docs/evidence/2026-10-07-followup.provenance.json --files
```

The final archive digest records completed evidence integrity. Local rule hashes and timestamps alone do not prove an externally timestamped preregistration, scientific validity, independent replication or worldwide novelty. Published source claims, our measurements and unrun comparisons are distinguished in the logs. No new reading, successful real correction or general accuracy gain is established.
