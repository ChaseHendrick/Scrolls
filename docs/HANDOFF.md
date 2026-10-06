# Handoff for the next repository session

Use plain sentences. Do not put U+2014 or U+2013 in new text. Inspect `git log` before quoting a SHA.

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
- The user has not yet said what hardware they have. `python -m kit doctor` on their machine is the first step.

Next steps, in order:

1. User runs `python -m kit doctor` on their machine and joins the Discord.
2. Run the PHerc0139 w035 control end to end.
3. Pick one variable to test on one eligible scroll (see `docs/state-of-play.md`); preregister; run; record.
4. Look for a small villa issue (good first issue or help wanted) to fix for an October Progress Prize. Deadline 31 Oct 2026, 11:59pm Pacific.
5. Grow `kit/` per the list in `docs/engine.md`, with tests.
