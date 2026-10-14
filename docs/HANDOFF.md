# Public repository handoff

**This file is the one handoff for this repository.** Every agent (Claude, Codex, Grok, ChatGPT or any other) reads it first and updates it before stopping: change the open-items table when you start or finish something, link longer notes from their row, and merge the handoff change into `main` at once rather than leaving it on a work branch. Private work has its own single handoff in Scrolls-private's `docs/HANDOFF.md`; nothing private goes here. Read [AGENTS.md](../AGENTS.md), [the workflow](WORKFLOW.md) and the current Git/PR state before continuing. Use plain sentences and preserve historical evidence bytes and hashes. Older dated sections are in [HANDOFF-archive.md](HANDOFF-archive.md), newest first; when this file grows long, move its oldest dated sections there, unchanged (`tests/test_repo.py` fails past 40 KB).

## Open items (checked 14 October 2026)

| Item | State | Next step | Waits on | Where |
| --- | --- | --- | --- | --- |
| Reports to villa | Issues [#2058](https://github.com/ScrollPrize/villa/issues/2058) and [#2059](https://github.com/ScrollPrize/villa/issues/2059), draft fix [#2060](https://github.com/ScrollPrize/villa/pull/2060) and seed-anchor PR [#2063](https://github.com/ScrollPrize/villa/pull/2063) are open upstream | Answer maintainers' reviews; any further post needs the owner's word | villa maintainers, then the owner | [`logs/2026-10-12-upstream-reports.md`](logs/2026-10-12-upstream-reports.md) |
| AutoPipeline public release | Released 14 October with Chase's approval of the exact file list: branch [`submission/progress-2026-10`](https://github.com/ChaseHendrick/Scrolls/tree/submission/progress-2026-10), commit `faada83` | Fixes go out as new file lists, each approved by Chase first | Chase | Branch `submission/progress-2026-10`; Scrolls-private |
| Greek letter reader | Released 14 October with Chase's approval in [PR #57](https://github.com/ChaseHendrick/Scrolls/pull/57): `kit letterread`, `kit greeklm`, training and benchmark scripts in `scripts/letters/`; review fixes in [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58). The weights are not in git: they are the release asset `letters-v2-real-step030000.npz` on tag [`letters-v2-real`](https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-real) (sha256 `44946dad...587477`, CC BY-NC 4.0), pinned in `kit/data/letter-weights.json`. Do not re-tag or delete it, because `--weights letters-v2-real` downloads from it | Merge #58; any new weights get a new tag and registry entry | Chase | [`letter-reader.md`](letter-reader.md), [`logs/2026-10-14-letter-reader.md`](logs/2026-10-14-letter-reader.md) |
| Released tools in the README | **Done** 14 October: [PR #60](https://github.com/ChaseHendrick/Scrolls/pull/60) merged (`d1a34ff`) after Chase approved it (01:51 UTC). The README's "Released tools" section is generated from `docs/releases.json` | Nothing left open. Every later release from private work adds its entry with `python -m kit releases add` (AGENTS.md rule 15); Progress Prize releases arrive as a `release-readme/<submission_id>` branch from the private exporter, for a PR into `main` | None | [`releases.json`](releases.json), [PR #60](https://github.com/ChaseHendrick/Scrolls/pull/60) |
| PHerc0841 Hecate caveat and README finding 1 like for like | **Done** 14 October: [PR #37](https://github.com/ChaseHendrick/Scrolls/pull/37) merged after Chase left the call to Claude (02:22 UTC). PHerc0841 is now called held out for every reader except possibly Hecate, and finding 1 compares v8in 0.738 with `ink_9um` 0.907 on the same bare crop. Its own 2026-10-09 prize snapshot was dropped, since the 2026-10-11 snapshot already records the PHerc. 343 award | Nothing left open | None | [`logs/2026-10-09-pherc0841-hecate.md`](logs/2026-10-09-pherc0841-hecate.md) |

## Still binding from older sections (moved 14 October 2026)

These come from sections now in [HANDOFF-archive.md](HANDOFF-archive.md) and still apply:

- README "Novel finding 1" keeps its w045 correction until v8in's PHerc0841 crop scores replace it (the owner's choice; "Correction 8 October 2026").
- Generic tools and public benchmarks stay public even when an artifact's filename includes `candidate` ("Evidence and next public work").
- When you change code, also run the separate numerical experiment regressions ([TESTING.md](TESTING.md)), and never modify a script while it runs ("Environment").

## Older sections

Dated sections from 12 October 2026 and earlier, the 7 to 9 October corrections and the October review notes are in [HANDOFF-archive.md](HANDOFF-archive.md), newest first. Search it; do not read it whole.
