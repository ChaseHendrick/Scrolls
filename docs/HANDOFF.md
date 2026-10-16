# Public repository handoff

**This file is the one handoff for this repository.** Every agent (Claude, Codex, Grok, ChatGPT or any other) reads it first and updates it before stopping: change the open-items table when you start or finish something, link longer notes from their row, and merge the handoff change into `main` at once rather than leaving it on a work branch. Private work has its own single handoff in Scrolls-private's `docs/HANDOFF.md`; nothing private goes here. Read [AGENTS.md](../AGENTS.md), [the workflow](WORKFLOW.md) and the current Git/PR state before continuing. Use plain sentences and preserve historical evidence bytes and hashes. Older dated sections are in [HANDOFF-archive.md](HANDOFF-archive.md), newest first; when this file grows long, move its oldest dated sections there, unchanged (`tests/test_repo.py` fails past 40 KB).

## Open items added 16 October 2026 (checked 02:30 ET)

Public work only, neutral voice. PR numbers and SHAs were checked on GitHub when written.

```yaml
handoff:
  written: 2026-10-16T02:30-04:00
  repo: ChaseHendrick/Scrolls
  base: main
  merged_since_last_handoff:
    - {number: 94, branch: grok/unroll-release, merge: 590636c, topic: Unroll in the README release list}
    - {number: 95, branch: grok/handoff-2026-10-16, merge: cefa929, topic: handoff 01:10 ET}
    - {number: 96, branch: grok/unroll-relicense, merge: 915f302, topic: Unroll listing Apache 2.0 and v1.0.0}
    - {number: 97, branch: grok/readings-wording, merge: e73ca73, topic: ink-layer disclaimer wording}
    - {number: 98, branch: grok/unroll-install-app, merge: 0d34f92, topic: Unroll Install app link}
  open_prs:
    - this handoff PR
  rules: [no_force_push, do_not_touch_main_claude_or_codex_branches, log_every_cloud_run, open_data_bucket_only]
```

| Item | State | Next step |
| --- | --- | --- |
| Unroll ink-layer wording | Merged, PR #97 (`e73ca73`): "Ink layers show where models detect ink; letters visible here are candidates for expert reading." | None |
| Unroll Install app | Merged, PR #98 (`0d34f92`): release entry links the Install app (offline app) and `docs/unroll-space.md` has an Install app section | None |
| Unroll viewer changes since 01:10 ET (Space repo) | New scrolls from the open data bucket (PHerc0172, PHerc1447, PHerc1667, CC BY-NC 4.0); installable offline app; texture upload queue removing a 14.6 s main-thread freeze; type and spacing pass; scan labelled 9.4 µm (9.362 µm in details); glossary links; lower resolution while dragging; X-ray window and level with auto contrast; CT volume view; lighter phone mesh (`--coarsen`); starting view fitted to each roll; first-load flash and black screen fix (shader NaN, stricter service worker matching). Space version 1.4.0 | Re-test first load on real phones and desktop GPUs; artifact sweep (spike, floating square) still open |
| Unroll audit findings (from 01:10 ET) | Not yet confirmed fixed, except the old "run by us" chip text, which no longer appears in the Space code | Escape the annotation id, reject non-finite thresholds and offsets, show share-link errors, re-test |
| Stale branches | Merged branches listed at 01:10 ET were deleted. Still present and fully merged: `grok/autopipeline-every-scan`, `grok/handoff-2026-10-16`, `grok/perf-cli-parser`, `grok/unroll-install-app`, `grok/unroll-release`, `grok/unroll-relicense` | Delete on the owner's yes |
| GPU inference speed | TensorRT dropped by owner decision. `torch.compile` max-autotune fp16 is the chosen speedup (0.003755 s/tile, about 1.9x over eager) | None |
| Quick start guide | In progress: a public QUICKSTART guide | Write it and open a PR |
| AGENTS.md size | Over the 26,000-byte test limit | Trim or move detail out, then re-run tests |
| `test_autopipe` | Import error | Fix the import and re-run tests |
| AutoPipeline paid batches | Dry runs only; no daily watch routine set | Each paid batch and any cloud launch needs the owner's approval |
| Release polish (Claude, 16 Oct 10:15 UTC) | Branch `claude/polish-releases-bgc1za`: the README's Unroll entry and `docs/unroll-space.md` now match the live Space, version 1.5.0 (they said 1.1.0 and ink_9um on `w046` to `w051` only). On `main` at `27d0e96` the full test suite passes (714 tests, 43 skipped, with numpy, tifffile, zarr and scipy installed), so the AGENTS.md size and `test_autopipe` rows above no longer fail there. The workbench package is now 0.2.0 with `CHANGELOG.md`. Fresh pictures of AutoPipeline 0.1.4's monitor on the synthetic demo (a GIF of a run and three stills) are in `docs/assets/autopipeline/`, shown in the README above the release list and in `docs/autopipeline/README.md`; the package README on the release branch stays unchanged until the next AutoPipeline fix release carries them. No GitHub release exists yet for AutoPipeline 0.1.4 or for the workbench package | Owner's yes on the list of releases to publish; GitHub releases are drafted as text, since the session cannot create them |
| Tool pages (Claude, 16 Oct 14:40 UTC; Chase: "make all current, past, and future tool docs extremely detailed and readable by both human and agent") | Draft PR [#104](https://github.com/ChaseHendrick/Scrolls/pull/104), branch `claude/tool-docs-k5afs7`: the standard `docs/TOOL-DOCS.md`, the checker `kit/tooldocs.py` with 38 tests, the template, AGENTS.md rule 16, and the model page `docs/tools/auc.md`. Every other public tool is listed in `docs/tools/pending.json` (47 pages) and is being written and independently checked page by page; the checker fails when a tool has no page and is not on that list | Finish the pages, empty `pending.json`, run the full suite, mark the PR ready for Chase |

## Open items added 16 October 2026 (checked 01:10 ET)

Public work only, neutral voice. PR numbers and SHAs were checked on GitHub when written.

```yaml
handoff:
  written: 2026-10-16T01:10-04:00
  repo: ChaseHendrick/Scrolls
  base: main
  merged_since_last_handoff:
    - {number: 91, branch: grok/glossary, merge: ad2c4f8, topic: GLOSSARY.md, an A to Z of technical terms}
    - {number: 92, branch: grok/perf-cli-parser, merge: dc6713b, topic: kit cli reuses one argparse parser per process}
    - {number: 93, branch: grok/autopipeline-every-scan, merge: 0a22f72, topic: AutoPipeline on every scan}
  open_prs:
    - none
  rules: [no_force_push, do_not_touch_main_claude_or_codex_branches, log_every_cloud_run, open_data_bucket_only]
```

| Item | State | Next step |
| --- | --- | --- |
| Unroll v1.0 (viewer Space, [unroll-space.md](unroll-space.md)) | Released. Control panel redesign (grouped Layers, Ink Bench, View, Destroy, Scrolls), Settings saved in localStorage and settable by URL, plain language glossary, agent API (`unrollView.actions/settings/state/glossary`), Ink Bench button, CPU pick fallback for Destroy on GPUs without float targets. The overlay layer is labelled `ink_9um (9 µm)`, credited to the Vesuvius Challenge. README entries updated | Fix the audit findings below |
| Unroll security and UX audit | Findings, highest first: HIGH stored HTML injection through the Ink Bench annotation id (the note field is escaped, the id is not); MED NaN or Infinity thresholds accepted and carried into share links; MED out-of-range alignment offsets accepted; MED malformed `?bench=` links fail silently or show raw errors; MED HUD collisions at 800x500 and 1100x700, and the readout has no backdrop. LOW: no minimum image size, wrong advice for non-image uploads, a double-escaped name, raw `atob` errors, "9.362 um" instead of µm, mixed UK and US spelling. Passed: bad uploads, zip bomb, path traversal, XSS in names and credits, resize and key spam | Escape the annotation id, reject non-finite thresholds and offsets, show share-link errors, then re-test |
| Glossary | Merged, PR #91 (`ad2c4f8`) | None |
| CLI speedup | Merged, PR #92 (`dc6713b`): one parser per process (about 119 ms to 13 ms per call) | None |
| AutoPipeline on every scan | Merged, PR #93 (`0a22f72`): catalog of every scan volume in the `vesuvius-challenge-open-data` bucket (75 volumes when checked), per-scan config, priced dry-run batch (`kit run all`) and watcher (`kit run watch`). Launches nothing; volumes not in the bucket are marked blocked | Paid batch runs each need the owner's approval |
| Unroll in the README release list | Merged, PR #94 (`590636c`): adds Unroll v1.0 to `docs/releases.json` and the README Released tools section | None |
| Stale branches | Fully merged into `main`, safe to delete on the owner's yes: `grok/autopipe-fixes`, `grok/autopipe-readme`, `grok/charred-ink-20261011`, `grok/glossary`, `grok/handoff-2026-10-15`, `grok/lane{A..I}-*`, `grok/local-cost-ledger`, `grok/modal-pricing`, `grok/prize-snapshot-20261011`, `grok/unroll-link`, `grok/vesuvius-bible`, `ChaseHendrick-patch-1`, `rewrite/main-without-noreply`, `release-readme/progress-2026-10-fix4`. Not merged: `release-readme/progress-2026-10-fix1` (2 commits, superseded by fix4), `submission/progress-2026-10` and `-fix4` (1 commit each, Progress Prize submission snapshots; keep) | Owner decides on deletion |
| GPU inference speed probes (C reader) | `torch.compile` gives about 1.85x over eager fp16 per tile; max-autotune about 1.9x; TensorRT fp16, int8 and fp8 builds did not complete (missing ONNX file and `onnx_graphsurgeon`) | Fix the ONNX export before any further probe; no launch without approval |

## Open items added 15 October 2026 (checked 23:20 ET)

Public work only. Every PR and SHA below was checked on GitHub when written; anything not checked says **unverified**.

```yaml
handoff:
  written: 2026-10-15T23:30-04:00
  repo: ChaseHendrick/Scrolls
  base: main
  main_head_at_writing: 303c33f
  open_prs:
    - {number: 85, branch: grok/vesuvius-bible, head: 9229ff8522, topic: Vesuvius Challenge reference book, state: open}
    - {number: 87, branch: grok/unroll-link, head: 5b963dab59, topic: link to the Unroll viewer Space, state: open}
    - {number: 88, branch: grok/autopipe-readme, head: 9983e6f3df, topic: AutoPipeline reference README and agent rules, state: open}
  in_progress_not_pushed:
    - vesuvius_bible_layout_redesign
    - autopipeline_electricity_cli_and_modal_ledger_rows
    - unroll_destroy_mode_agent_api_ink_bench
  rules: [no_force_push, do_not_touch_main_claude_or_codex_branches, log_every_cloud_run, scan_images_not_in_this_repo]
```

| Item | State | Next step | Waits on | Where |
| --- | --- | --- | --- | --- |
| Vesuvius Challenge reference book | PR #85 open and mergeable, head `9229ff8522` (80 files under `docs/vesuvius-bible`). A layout redesign (chart style, rebuilt PDF) is in progress outside git | Finish the redesign, push to `grok/vesuvius-bible` without force, then review and merge | Chase | PR #85 |
| AutoPipeline reference README | PR #88 open, head `9983e6f3df` (`docs/autopipeline/README.md`, `docs/autopipeline/AGENTS.md`, `docs/README.md`). Its commit is authored as Grok Bot, not Chase, against the identity rule below; fix by a new commit only if Chase wants it rewritten (no force-push) | Review and merge | Chase | PR #88 |
| AutoPipeline local-run and ledger tooling | In progress, not pushed: `kit run local` (wall time, CPU time and an electricity estimate, rate read from local config, never git), `kit run backfill`, and automatic one-row-per-app cloud ledger rows. `tests/test_letterlines.py` passes on `main` (13 tests); the pending letterlines change is **unverified** | Review, open a PR | agent | not yet in git |
| Unroll viewer link | PR #87 open, head `5b963dab59` (`README.md`, `docs/unroll-space.md`). The Space ([huggingface.co/spaces/SharpMeow/unroll](https://huggingface.co/spaces/SharpMeow/unroll)) serves commit `f6dcaa7`: multi-scroll registry (`scrolls/index.json` with one manifest per scroll) and Open your own (load your own meshes and ink maps in the browser). In progress, not deployed: Destroy mode (tear, crush, burn, water at any unroll amount), a `window.unroll` agent API, and an Ink Bench whose scores are agreement with the published ink layer, not ground truth | Merge the three working copies, test, deploy; then update `docs/unroll-space.md` | Chase | PR #87 |

## Open items (checked 14 October 2026, 22:45 UTC)

| Item | State | Next step | Waits on | Where |
| --- | --- | --- | --- | --- |
| Stranger account in the contributors | **Done** 14 October: public `main` was rewritten and force-pushed at 13:39 UTC with Chase's approval (cards at 13:10 and 13:19 UTC), so the two exporter commits that GitHub credited to github.com/noreply (`5462ebf`, `301e12d`, now `1544c0f`, `7404735`) are authored by Chase; files and messages unchanged, 14 commits from that day got new IDs. Grok-Bot and codex stay listed for their older commits by his choice. Release branches and the `umbilicus-v1` and `letters-v2-real` tags were not moved, so `umbilicus-v1` points at a commit no longer on `main` (its download still works) | Any agent committing here follows the AGENTS.md identity rules (standing decisions, 14 October) | None | This row |
| Segment stack check and the PHerc0139 segment note | Released 14 October 2026 in PR #80 after Chase approved its 11-file list (22:00 UTC): `kit stackcheck` (`kit/stackcheck.py`, `tests/test_stackcheck.py`, CLI) checks a stack of consecutive tifxyz segments against the umbilicus from geometry alone and writes per-vertex masks; the note gives the PHerc0139 w033 to w037 measurements, example vertices and a by-eye CT look at 12 places; `stackcheck` entry in `releases.json`, `stackcheck_checks` in `results.json` | Run it on other published stacks when a spiral fit or winding count needs them | anyone | [`logs/2026-10-14-pherc0139-segment-defects.md`](logs/2026-10-14-pherc0139-segment-defects.md) |
| Reports to villa | Issues [#2058](https://github.com/ScrollPrize/villa/issues/2058) and [#2059](https://github.com/ScrollPrize/villa/issues/2059), draft fix [#2060](https://github.com/ScrollPrize/villa/pull/2060) and seed-anchor PR [#2063](https://github.com/ScrollPrize/villa/pull/2063) are open upstream. Issue [#2104](https://github.com/ScrollPrize/villa/issues/2104) (posted by Chase on 14 October): a `vc_grow_seg_from_seed` trace with x/y/z limits stops once a cell skipped at a limit lies inside `used_area`; its fix PR is drafted, not posted | Answer maintainers' reviews; any further post needs the owner's word | villa maintainers, then the owner | [`logs/2026-10-12-upstream-reports.md`](logs/2026-10-12-upstream-reports.md) |
| AutoPipeline public release | Released 14 October with Chase's approval of the exact file list: branch [`submission/progress-2026-10`](https://github.com/ChaseHendrick/Scrolls/tree/submission/progress-2026-10), commit `faada83` | Fixes go out as new file lists, each approved by Chase first | Chase | Branch `submission/progress-2026-10`; Scrolls-private |
| Greek letter reader | **Done** 14 October. Released with Chase's approval in [PR #57](https://github.com/ChaseHendrick/Scrolls/pull/57): `kit letterread`, `kit greeklm`, training and benchmark scripts in `scripts/letters/`. [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58), merged by Chase at 21:59 UTC (merge `25914fb`), makes it installable, reads whole maps, adds controls and exports, and makes the CC BY 4.0 weights `letters-v2-ccby` the default. The letter reader thread installed the guide's pip line from `main` in a fresh venv afterwards: it installs, fetches `letters-v2-ccby` and the demo passes. The weights are not in git. `letters-v2-ccby` is the release asset on tag [`letters-v2-ccby`](https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-ccby) (sha256 `b14988852fc7...`, CC BY 4.0, published 14 October). `letters-v2-real-step030000.npz` stays on tag [`letters-v2-real`](https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-real) (sha256 `44946dad...587477`, CC BY-NC 4.0), pinned in `kit/data/letter-weights.json`. Do not re-tag or delete either, because `--weights` downloads from them | Nothing open. Any new weights get a new tag and registry entry | Nobody | [`letter-reader.md`](letter-reader.md), [`logs/2026-10-14-letter-reader.md`](logs/2026-10-14-letter-reader.md) |
| Released tools in the README | **Done** 14 October: [PR #60](https://github.com/ChaseHendrick/Scrolls/pull/60) merged (`d1a34ff`) after Chase approved it (01:51 UTC). The README's "Released tools" section is generated from `docs/releases.json` | Nothing left open. Every later release from private work adds its entry with `python -m kit releases add` (AGENTS.md rule 15); Progress Prize releases arrive as a `release-readme/<submission_id>` branch from the private exporter, for a PR into `main` | None | [`releases.json`](releases.json), [PR #60](https://github.com/ChaseHendrick/Scrolls/pull/60) |
| PHerc0841 Hecate caveat and README finding 1 like for like | **Done** 14 October: [PR #37](https://github.com/ChaseHendrick/Scrolls/pull/37) merged after Chase left the call to Claude (02:22 UTC). PHerc0841 is now called held out for every reader except possibly Hecate, and finding 1 compares v8in 0.738 with `ink_9um` 0.907 on the same bare crop. Its own 2026-10-09 prize snapshot was dropped, since the 2026-10-11 snapshot already records the PHerc. 343 award | Nothing left open | None | [`logs/2026-10-09-pherc0841-hecate.md`](logs/2026-10-09-pherc0841-hecate.md) |

## Still binding from older sections (moved 14 October 2026)

These come from sections now in [HANDOFF-archive.md](HANDOFF-archive.md) and still apply:

- README "Novel finding 1" keeps its w045 correction until v8in's PHerc0841 crop scores replace it (the owner's choice; "Correction 8 October 2026").
- Generic tools and public benchmarks stay public even when an artifact's filename includes `candidate` ("Evidence and next public work").
- When you change code, also run the separate numerical experiment regressions ([TESTING.md](TESTING.md)), and never modify a script while it runs ("Environment").

## Older sections

Dated sections from 12 October 2026 and earlier, the 7 to 9 October corrections and the October review notes are in [HANDOFF-archive.md](HANDOFF-archive.md), newest first. Search it; do not read it whole.
