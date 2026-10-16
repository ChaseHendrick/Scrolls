# AutoPipeline: rules for agents

Read [`README.md`](README.md) first; section 18 is the machine-readable part. The repository's root
[`AGENTS.md`](../../AGENTS.md) applies above this file.

1. The code lives on branch `submission/progress-2026-10-fix4`, folder
   `submissions/progress-2026-10-fix4/autopipeline`. Read it before describing behaviour; never invent flags or
   settings.
2. Use `scrolls-kit autopipeline ...` in documents on `main`; `autopipeline` is not a command of `main`'s `kit`.
3. Never edit `plan.json` or `state.json`; a changed rule is a new plan in a new folder.
4. A target run needs a preregistered ledger experiment; target maps, triage lists and snapshots never leave the
   git-ignored run folder.
5. Add a row to `docs/compute/modal-ledger.csv` after any Modal job. Wrap local runs with `python -m kit run local`;
   keep the electricity rate in local config.
6. Keep the monitor on 127.0.0.1.
7. Maps and scores are model output, not readings.
8. Do not edit the README's "Released tools" section by hand (root AGENTS.md rule 15).
9. No long dashes in tracked text. Never print tokens.

Tests: `python -m unittest discover -s tests` in the package folder; `python -m unittest tests.test_repo` here.
