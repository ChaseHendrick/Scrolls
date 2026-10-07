# PR review and merge evidence

Recorded 7 October 2026 under the user's instruction to merge every PR, including Grok contributions. The receipts record exact reviewed heads and successful checks for PRs #6 through #18. PRs #1 through #5 were already merged. Lane C was a completed branch without a PR; it became #18. The final documentation/CI follow-up is separate; its GitHub PR status is not part of these frozen merge receipts.

## What the review changed

| PR | Review outcome |
| --- | --- |
| #6-10 | Previously repaired benchmark interpretation, independent-sheet splits, unknown-label handling, boundary coverage, matched strides and partial completion records; checked original repaired heads and passing CI |
| #11, Grok A | Removed significance categories inferred from unrelated marginal bootstrap widths; synthesis is descriptive |
| #12, Grok B | Excluded geometry derivatives crossing holes, made supervision filtering explicit, censored unknown-boundary widths, handled degenerate statistics and strict JSON |
| #13, Grok E | Corrected average tied ranks and constant-map metrics, escaped inline JSON for the viewer, fixed canvas dimensions |
| #14, Grok D | Integrated experimental CLI; validated synthetic train/save/predict and Mac script dispatch; qualified contributed negative benchmark conclusions; removed 15 AppleDouble files |
| #15, Grok G | Corrected fresh-run logging, first-positive-period selection and sign-flipped null comparison; preserved historical numbers |
| #16, Grok F | Corrected tied ranks and fixed-model wrong-depth tests, stopped failed inference, removed 10 AppleDouble files |
| #17 | Integrated continuous surface correspondence, real controlled papyrus validation, UFSM assessment and earlier frozen evidence |
| #18, Grok C | Preserved ties and unclipped rank fusion, used common supervised support, made imports safe, qualified historical scores |

All merges used the current reviewed commit and successful GitHub checks. No force pushes, branch deletions or admin overrides were used. The final late #14 changes were reviewed separately: `pr14-99c71f3` checks train/test context separation and shell dispatch; `pr14-ca9c8c4` checks Grok's contributed result records. The cloud review did not rerun those Mac inferences. Raw numerical JSON remained unchanged; explicit qualifications explain invalid historical inference.

`combined-tests.log` records 185 passing repository tests at the integrated code before the subsequent shell-only/report additions. The late shell additions have their own dispatch check and CI; no application code changed afterward. `experiment-regressions.log` records another 39 passing tests across six experiment directories. The final follow-up adds these directories to the numerical CI job, which previously ran only `tests/`.

## Verify and interpret the archive

From this directory, run `sha256sum -c SHA256SUMS`. `archive-origins.json` identifies source files copied byte-for-byte from the session workspace. Reports can reference isolated review exports or source paths outside Git; those paths are historical and are not required to verify the archived bytes. Real input arrays, model weights and maps are excluded.

The source review receipts and this archive's hashes are post-run integrity records. They do not establish external timestamps, scientific validity or independently reproduced inference. Historical `synth.out` whitespace and other raw logs are preserved rather than reformatted.

The older `2026-10-07-followup.provenance.json` and `2026-10-07-ufsm.provenance.json` bind the documentation as it existed in commits `4af30e8` and `2fceb61`, respectively. The archived `historical-provenance-check.json` verifies all 18 directly fingerprinted paths at those commits and 131 archive checksum entries (112 follow-up, 14 UFSM, 5 nested geometry); current evidence bytes and old seals are unchanged. Later updates legitimately change those documents. Preserve the old records and verify them against historical exports; do not rewrite their hashes to make them describe today's documentation. New provenance alongside this archive seals the final review and research records.
