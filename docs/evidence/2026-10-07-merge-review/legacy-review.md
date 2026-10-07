# Legacy PR revision and integration review

Observed 2026-10-07T14:16:03.079117+00:00 using read-only git and GitHub CLI/API.

Repository: ChaseHendrick/Scrolls. Base origin/main: `9af26f66c9f0314e48613550d41aa6d5c6d163ba`. Review branch: `codex/cloud-validation-and-scan-status` at `2fceb61dac68657a9b1d1fb29fb941369e861685`.

## PRs 6 through 10

All five current heads exactly match the previously repaired revisions. There is no new code delta to re-review. Each has zero reviews, zero discussion comments and zero inline review comments. GitHub reports CLEAN/MERGEABLE and successful test (3.10), test (3.13), and verify checks for each.

| PR | Verified current head | Prior repaired scope |
| --- | --- | --- |
| #6 | `814563ffc6590d073587cd4544fb2a1b89da892a` | Independent-sheet threshold calibration, boundary coverage and unknown-label handling. |
| #7 | `c4a5ead246f502e16a7b34db6629b14562bb630e` | Future matched stride42 controls; historical stride64 stays explicitly provisional without changing old metrics. |
| #8 | `a2951681ad1c590bdd4686c5340cfe1226887d60` | Reader window and Reader v2 reporting corrections. |
| #9 | `97d26e74417f42fb87abf80ad25c8a90f5629710` | Partial 2/11 coverage and matched/provisional control reporting; no inferred completion. |
| #10 | `d288c58338701c16589edccddaab22b6cea107d4` | Future matched stride42 controls; historical stride64 stays explicitly provisional. |

No approval reviews are present; this is an observation of repair identity and checks, not an invented maintainer approval. No repeated scientific evaluation or inference was needed for these unchanged heads.

## All open PRs and integration collisions

All 11 open PRs (#6 through #16) target main. At the observation time, all 11 had CLEAN/MERGEABLE status and all three checks passed. Their exact heads and changed files are saved in `integration-file-overlaps.json`; raw metadata and inline comments are saved per PR.

The only shared changed file among all 11 PRs and the current review branch is `kit/cli.py`, changed by #13, #14 and the review branch. Every other changed path is disjoint. The legacy PRs #6 through #10 add files only inside their separate experiment directories.

A read-only three-way test using `git merge-file -p` on extracted CLI files confirms exactly two conflict regions for each of the three pairs: current/#13, current/#14, and #13/#14. All three common bases are the pinned origin/main above. The conflict regions are the first-line command documentation and module imports. The command functions and parser blocks merge automatically in these pairwise tests. See `cli-three-way-audit.json` and the three `cli-*-three-way.txt` artifacts.

Resolution must preserve all of `surfacefix`, `phantom`, `view`, and `fibertensor` in the command documentation, all associated module imports, and each function/parser block. Do not choose one whole CLI side and lose the other commands. The CLI-only conflict diagnosis does not establish semantic compatibility of the new modules.

## Suggested integration order

1. Integrate repaired #6 through #10, in numerical order or any order: their experiment directories are disjoint.
2. Integrate #11, #12, #15 and #16 after the corresponding Grok review findings are handled; their paths are disjoint from the current branch and other PRs.
3. Integrate #13, then #14, resolving the two CLI regions to retain both sets of commands. These PRs have no ordering dependency, but processing them together keeps CLI resolution local.
4. Integrate the current cloud-validation-and-scan-status branch, retaining its tested surfacefix CLI, evidence, handoff and documentation. If it is integrated first, the same two CLI conflicts recur in #13 and #14.
5. Run the repository suite and verifier against the final combined tree, plus CLI parser/help checks for all four new commands. Per-PR green checks cannot prove combined-tree compatibility.

This order is a conflict-minimization suggestion, not a scientific endorsement of Grok findings. Separate Grok reviews govern their fixes and interpretation. No branch switches, repo file edits, git object writes, pushes, merges, or public comments were performed in this review.
