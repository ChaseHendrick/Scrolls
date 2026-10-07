# Lane C merge-readiness review

Baseline: `d3074de09b36e8717108d2ac073de7943657af9d` (`origin/grok/laneC-gaps` when reviewed). There is no open PR for this branch. It adds a research log, texture experiment script and recorded JSON; these paths do not collide with the other open PRs or current review branch.

Confirmed issues: stable ordinal ranks split equal reader scores by flattened pixel position; percentile clipping in fusion adds ties; raw and rank baselines can use different exact-zero cohorts. The quoted whole-map bootstrap width does not measure uncertainty of this crop-specific fusion difference. Retained shuffled association cannot establish the absence or cause of depth-ordered ink.

Isolated export `laneC-fixed` fixes future fusion using average ties, no percentile clipping in the fusion scoring path, and the same supervised reference-valid cohort for both baseline and fusion. An import-safe main entry point allows direct synthetic testing without loading data. No feature calculation or original recorded numeric value was replaced. `results.json` adds review flags deprecating historical fusion inference and causal depth-order claims. The log marks the fusion table historical, withdraws the unrelated noise floor, and narrows the texture interpretation to failure of this two-crop rule.

Eight CPU synthetic tests passed, zero failures/skips. They cover average ties, constant-map AUC 0.5, independence of flattened pixel ordering, matching support, uint8 baseline AUC preservation, no percentile rank clipping, and invalid input rejection. `git apply --check` passes against an isolated original branch export. Original results equality was checked after removing only the new review metadata. No data/model download or scientific rerun occurred.

Changed paths:

- `docs/logs/2026-10-07-grok-laneC.md`
- `scripts/experiments/2026-10-07-grok-laneC/results.json`
- `scripts/experiments/2026-10-07-grok-laneC/texture.py`
- `scripts/experiments/2026-10-07-grok-laneC/test_texture.py`

Apply `laneC-fixes.patch` on the pinned branch, then include the reviewed branch through a PR. The final experiment remains exploratory: no corrected run, paired interval, reverse-depth reader control or broad generalization proof was produced by this repair. Treat its gap list as research ideas, and its numerical tables as preserved historical outputs.
