# Handoff for the next repository session

Use plain sentences. Do not put U+2014 or U+2013 in new text. Inspect `git log` before quoting a SHA.

## Session 7 October 2026: M1 Pro path and repo transfer

The user's machine is an Apple M1 Pro. Added `doctor` Apple Silicon handling (warn, not fail; memory check; VC3D.app tool path), `plan --mac`, [`mac.md`](mac.md), and [`logs/2026-10-07-mac-and-repos.md`](logs/2026-10-07-mac-and-repos.md). 25 tests pass.

Key facts: stock villa ink inference is CUDA or CPU. MPS support is in open PRs #1865 and #1812; do not write a duplicate. Lasagna has MPS (#1639). The VC3D stable build crashes opening PHerc0826 on macOS (#1910); use the latest build.

From Chase's repositories, the GENChase Apple GPU verification method and the Research-Integrity skill transfer. Nothing else does in a meaningful way; see the log.

Next: the user runs `python -m kit doctor` and the w035 control on the Mac (CPU), then on the #1865 branch (MPS), and compares.

## Session 6 October 2026: repository set up

Work is on branch `claude/youthful-heisenberg-gdjttc`. The repository went from a one-line README to a workbench modeled on [Undeciphered-Texts](https://github.com/ChaseHendrick/Undeciphered-Texts): README, governance docs, research docs, and the `kit/` package with 22 passing tests.

What exists:

- `kit/data/prizes-2026-10-06.json`: prize snapshot from villa commit `e0bbb8b40a2d`, with all 13 Grand Prize and 22 First Letters volumes resolved to their S3 Zarr names by listing the public bucket.
- `kit plan`: official tutorial commands per scroll. Not executed here (no GPU in this container).
- `kit run`: local ledger with readout hash and a disclosure gate.
- Docs: start-here, prizes, pipeline, state-of-play, compute, engine, external, sources, workflow.

What was not done:

- No pipeline step was run. Nothing here has touched a CT volume beyond listing bucket prefixes.
- scrollprize.org and the Substack were blocked from this session. Prize facts come from the website source in villa. The Substack First Letters workflow post was not read in full.

Next steps, in order:

1. User runs `python -m kit doctor` on their machine and joins the Discord.
2. Run the PHerc0139 w035 control end to end.
3. Pick one variable to test on one eligible scroll (see `docs/state-of-play.md`); preregister; run; record.
4. Look for a small villa issue (good first issue or help wanted) to fix for an October Progress Prize. Deadline 31 Oct 2026, 11:59pm Pacific.
5. Grow `kit/` per the list in `docs/engine.md`, with tests.
