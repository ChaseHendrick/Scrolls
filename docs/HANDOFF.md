# Public repository handoff

**This file is the one handoff for this repository.** Every agent (Claude, Codex, Grok, ChatGPT or any other) reads it first and updates it before stopping: change the open-items table when you start or finish something, link longer notes from their row, and merge the handoff change into `main` at once rather than leaving it on a work branch. Private work has its own single handoff in Scrolls-private's `docs/HANDOFF.md`; nothing private goes here. Read [AGENTS.md](../AGENTS.md), [the workflow](WORKFLOW.md) and the current Git/PR state before continuing. Use plain sentences and preserve historical evidence bytes and hashes. Older dated sections are in [HANDOFF-archive.md](HANDOFF-archive.md), newest first; when this file grows long, move its oldest dated sections there, unchanged (`tests/test_repo.py` fails past 40 KB).

## Continuation, 18 October 2026 (Claude cloud session)

Public items only; the private handoff has the detail.

| Item | State | Next step |
| --- | --- | --- |
| Modal from a Claude cloud session | Works after `pip install 'modal[api-proxy-support]'`, Chase's `modal token new` approval and an allow rule; rules, guides and tool pages corrected in [#126](https://github.com/ChaseHendrick/Scrolls/pull/126) | Budget rules unchanged: a cost estimate, the 500 USD ceiling and a ledger row for every run |
| AutoPipeline 0.1.5 | Published: package branch `submission/progress-2026-10-fix5` (`9e50d61`), README entry and tool pages in [#127](https://github.com/ChaseHendrick/Scrolls/pull/127), [GitHub release](https://github.com/ChaseHendrick/Scrolls/releases/tag/autopipeline-v0.1.5) by Chase (not Latest; workbench 0.4.1 stays Latest). Assets match `SHA256SUMS`; a clean install passes `pip check` and `scrolls-kit autopipeline defaults`. The wheel (`a45ab93b`) is reproducible with `SOURCE_DATE_EPOCH=1792293014` | Next fix release: trace-timeout robustness (in progress), and the package's `space/` copy still names `ink_9um` seed 42 while the live Space runs Reader v2 |
| Villa posts | Issue [villa #2135](https://github.com/ScrollPrize/villa/issues/2135) (`vesuvius.zarr_tasks` writes pyramid levels one voxel short on 4k + 1 axes, so VC3D refuses the output) and draft PR [villa #2136](https://github.com/ScrollPrize/villa/pull/2136) (ceiling division plus a regression test), from Chase's account | Wait for review (auto-close about 1 Nov idle or 15 Nov open); no bump comments |
| Release media (18 Oct) | Local branch `claude/release-media`, not pushed, revised after two reviews: a 1920 x 640 hero and a social card for every released tool except StrokeNet (held until its rework), shown through the optional `image` field of `docs/releases.json`; GIFs and MP4s of AutoPipeline 0.1.5's monitor (from its first stage, with a pointer), Starter's practice and a synthetic umbilicus sweep. Only concept illustrations and synthetic demos, each with a row and a sidecar ([`assets/README.md`](assets/README.md), [`scripts/media/`](tools/media.md)). The public media rule (18 Oct, set on Chase's delegation: [`media/README.md`](media/README.md), AGENTS.md row) now also allows real-data stills and short clips of public scans that are not prize-eligible, with no held-out labels, at most 1920 px and 4 MB with a sidecar, never model output; the guards and `tests/test_repo.py` enforce it, and the audit found every file conforming, none moved | **Do not merge before Scrolls-private's branch `claude/releases-image-sync`** (its `kit/releases.py` must match; merge it first or together). Then Chase reviews the pictures; push and open a PR. Queued: more motion media allowed here (a stack check sweep on PHerc0139 segment geometry, Inkfilter's synthetic demo in a terminal, a `scrolls-letterdemo` session, an untextured Unroll mesh orbit) and Chase's ZeroGPU minutes. Possible real-data additions under the rule: CT-only (ink layer off) re-renders of the private PHerc0139 Unroll and Scroll Lens clips; model output and prize-eligible scrolls stay in Scrolls-private's `docs/media/` |
| StrokeNet pages | [Tool page](tools/strokenet.md) and [model card](strokenet.md) now say plainly what version 1's held-out test showed (7 of 9 bar items passed; T6 and FPR_blank missed; ink density matches it on text against blank; its gain is T4), its limits (one reader's appearance, Paris 4's line pitch, input assumptions), and that a rework for any reader and scroll is in progress in private work; American English. A review then added: density does as well for finding text, "not tested in the published evidence" instead of "untested", and claim labels on the limits (`1d610ce`). **Merged 18 Oct in [#129](https://github.com/ChaseHendrick/Scrolls/pull/129)**, together with American English across the repo (frozen records, quotations, names, file names and public interfaces left as they were) | The public page changes again only when the rework has a preregistered held-out result Chase approves for release
| VC3D contributions in progress | VC3D builds and tests in the cloud container (villa `1db9cd9`, 197 of 197 tests). Designs for an ink-label drawing suite, region tools (3D box, ray arc, winding interval) and an optional modern theme; real VC3D screenshots and GIFs are captured headless for the PRs | Implement, test and open as draft PRs on villa with media; nothing posted yet |

## Continuation, 17 October 2026

| Item | State | Next step |
| --- | --- | --- |
| AutoPipeline 0.1.5 public package (18 Oct) | Published on branch `submission/progress-2026-10-fix5`, commit `9e50d61` (no parent commit): the 115 reviewed package files plus `release.json`, every remote file hash checked against the manifest (sha256 `261f790b...`). An ordinary software release, not a new prize entry. The pinned README entry and the [tool page](tools/autopipeline.md) now describe 0.1.5 (PR "Release AutoPipeline 0.1.5: README entry and tool pages"). The new entry no longer says the ink Space runs `ink_9um` seed 42 | Done 18 Oct: Chase published the [GitHub release](https://github.com/ChaseHendrick/Scrolls/releases/tag/autopipeline-v0.1.5) with the wheel and `SHA256SUMS`; see the 18 October section |
| README hero images (18 Oct) | Root and AutoPipeline reference now use matched charcoal/copper concept illustrations at 1920 x 640, with descriptive alt text and provenance notes. The old framed SVG is removed | Desktop/mobile and light/dark browser previews pass, as do repository checks and the generated releases check. Artwork is conceptual; no scan, model output or recovered text is depicted. [Artwork notes](assets/README.md) |
| Workbench 0.4.1 patch release | Packages the corrected viewer hover readout and updated Gate A reference. Current installation links name 0.4.1; historical 0.4.0 screenshots retain their original provenance | 123 focused tests, clean wheel installation, synthetic reader demo and browser checks passed. Wheel, portable Starter and SHA256SUMS are prepared for [workbench 0.4.1](https://github.com/ChaseHendrick/Scrolls/releases/tag/workbench-v0.4.1). Published 18 Oct 00:11 UTC; regenerate older viewer HTML files |
| Offline viewer hover and Gate A reference | Disagreement hover reads overlay alpha, so intermediate values such as 0.71 display correctly. Synthetic JavaScript regression and Chromium checks cover zero, intermediate and maximum values and opacity changes. [Gate A](tools/gate.md) now documents its existing blocked verdict, replacement records and control-edge checks | Regenerate HTML built before this fix. No model or scoring behavior changed. [Viewer reference](tools/view.md) |
| Workbench picture guide and agent interfaces | [Picture guide](workbench.md) explains the toolbox, Starter, reader and separate AutoPipeline with real screenshots and links to first tasks. Desktop/mobile previews and repository checks pass | Both-repository standing requirement: complete headless workflows and fair evidence against eligible community baselines, recorded in [the tool standard](TOOL-DOCS.md#headless-workflows-and-competitive-evidence). This does not claim every existing interface is already complete |
| Beginner onboarding and official viewer integration | Workbench 0.4.0 adds Scrolls Starter, portable offline HTML, real setup checks, a reader command builder and a rewritten [Start Here](start-here.md) path into official tools. [Volume viewer](tools/volumeview.md) checks supplied metadata and builds Neuroglancer states; it does not verify remote registration | Source and independent reviews pass. Final release checks and assets are recorded on [workbench 0.4.0](https://github.com/ChaseHendrick/Scrolls/releases/tag/workbench-v0.4.0). No hosted deployment or Discord posting |
| Scroll Text Reader name | Current docs, catalog, package description and help use Scroll Text Reader, formerly Greek Letter Reader. The default Greek model and optional local OCR route are distinguished | Commands, APIs, model names and historical release records remain compatible. [Guide](letter-reader.md); no new language-accuracy claim |
| Inkfilter 0.1.0 | [Released](https://github.com/ChaseHendrick/Scrolls/releases/tag/inkfilter-v0.1.0) as an 18-file standalone package, with a fixed filter, reverse-depth control, provenance and reproducible scalar evidence; 25 installed-wheel tests and independent review passed | Published README entry and [tool page](tools/inkfilter.md). Confirmation used new windows from the same development scrolls; no trained-reader comparison or reading is claimed |
| Reader weights, languages and runtime switching | Implemented for workbench 0.3.0: supplied lines use the `ink-lines` profile (CC BY-NC 4.0), automatic regions keep the permissive profile, and explicit overrides remain. Local Tesseract supports installed recognition languages with separate word provenance and controls. `ReaderSession.switch()` validates replacements before activating them. Independent Greek/Latin switching and seven failed-switch checks passed; 1,056 tests passed with 61 optional skips, plus 45 numerical experiment checks | [PR #119](https://github.com/ChaseHendrick/Scrolls/pull/119) merged after all nine CI checks; [workbench 0.3.0](https://github.com/ChaseHendrick/Scrolls/releases/tag/workbench-v0.3.0) is published. Printed-language checks do not establish scroll accuracy; one Latin shuffle control beat its input. [Guide](letter-reader.md), [backend contract](tools/reader-backends.md) |
| Segmentation dataset validation | [PR #118](https://github.com/ChaseHendrick/Scrolls/pull/118) merged: ambiguous inputs, malformed metadata and invalid fold counts are rejected before training plans are written | No training or model-quality result is implied. [Tool page](tools/segzoo.md) |

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
| Segmentation model zoo (`kit segzoo`, `scripts/segzoo/`; Chase, 17 Oct) | Registry of twelve families with licenses, nnU-Net v2 trainers for MedNeXt, Swin UNETR, SegResNet, SegFormer and an SS2D U-Net, SAM 2 sheet follower and frozen DINO probe, each with a control; CPU tested, nothing trained on scroll data ([page](tools/segzoo.md)) | Any GPU benchmark needs a spec and Chase's budget yes (rule 11) |
| Unroll ink-layer wording | Merged, PR #97 (`e73ca73`): "Ink layers show where models detect ink; letters visible here are candidates for expert reading." | None |
| Unroll Install app | Merged, PR #98 (`0d34f92`): release entry links the Install app (offline app) and `docs/unroll-space.md` has an Install app section | None |
| Unroll viewer changes since 01:10 ET (Space repo) | New scrolls from the open data bucket (PHerc0172, PHerc1447, PHerc1667, CC BY-NC 4.0); installable offline app; texture upload queue removing a 14.6 s main-thread freeze; type and spacing pass; scan labeled 9.4 µm (9.362 µm in details); glossary links; lower resolution while dragging; X-ray window and level with auto contrast; CT volume view; lighter phone mesh (`--coarsen`); starting view fitted to each roll; first-load flash and black screen fix (shader NaN, stricter service worker matching). Space version 1.4.0 | Re-test first load on real phones and desktop GPUs; artifact sweep (spike, floating square) still open |
| Unroll audit findings (from 01:10 ET) | Not yet confirmed fixed, except the old "run by us" chip text, which no longer appears in the Space code | Escape the annotation id, reject non-finite thresholds and offsets, show share-link errors, re-test |
| Stale branches | Merged branches listed at 01:10 ET were deleted. Still present and fully merged: `grok/autopipeline-every-scan`, `grok/handoff-2026-10-16`, `grok/perf-cli-parser`, `grok/unroll-install-app`, `grok/unroll-release`, `grok/unroll-relicense` | Delete on the owner's yes |
| GPU inference speed | TensorRT dropped by owner decision. `torch.compile` max-autotune fp16 is the chosen speedup (0.003755 s/tile, about 1.9x over eager) | None |
| Scroll Lens Space (thread "Use my 5 minutes of ZeroGPU", 16 and 17 Oct) | v1.1.0 in PR #115 (branch `claude/scroll-lens-1.1`), on top of PR #114's agent tools and MCP: the views drawn in the browser (`viewer.js`: live sliders, drag, wheel, zoom, pan, undo, hover readout), a 3D view of the cube (three.js, as in Unroll), and the fixes from a bug test of the live v1.0.0 (see [the tool page](tools/scroll-lens.md) History). Gallery: 99 cubes on the Space (batches 1 to 9, `tools/build_gallery.py --batch`). Live [SharpMeow/scroll-lens](https://huggingface.co/spaces/SharpMeow/scroll-lens) runs this branch's v1.1.0, deployed and tested live on 2026-10-17 (page flat and 3D, the seven tools and MCP, one 128³ GPU run). To free the ZeroGPU slot (free accounts get 2), Chase deleted the private `SharpMeow/scrolls-ink-zerogpu` | Done: #115 merged 17 Oct (and #117 after it); the redeploy and live recheck remain |
| Quick start guide | Completed in [Start Here](start-here.md), the existing guide, with portable practice and official-tool transitions | Keep this single shareable entry point current |
| AGENTS.md size | Resolved: AGENTS.md is under the current 20,000-byte test limit (19,717 bytes on 18 Oct) | None |
| `test_autopipe` | Resolved: the full suite passes on `main` (1,083 tests on 18 Oct) | None |
| AutoPipeline paid batches | Dry runs only; no daily watch routine set | Each paid batch and any cloud launch needs the owner's approval |
| Release polish (Claude, 16 Oct 10:15 UTC) | Branch `claude/polish-releases-bgc1za`: the README's Unroll entry and `docs/unroll-space.md` now match the live Space, version 1.5.0 (they said 1.1.0 and ink_9um on `w046` to `w051` only). On `main` at `27d0e96` the full test suite passes (714 tests, 43 skipped, with numpy, tifffile, zarr and scipy installed), so the AGENTS.md size and `test_autopipe` rows above no longer fail there. The workbench package is now 0.2.0 with `CHANGELOG.md`. Fresh pictures of AutoPipeline 0.1.4's monitor on the synthetic demo (a GIF of a run and three stills) are in `docs/assets/autopipeline/`, shown in the README above the release list and in `docs/autopipeline/README.md`; the package README on the release branch stays unchanged until the next AutoPipeline fix release carries them. GitHub release [`autopipeline-v0.1.4`](https://github.com/ChaseHendrick/Scrolls/releases/tag/autopipeline-v0.1.4) published 16 Oct 20:08 UTC with Chase's yes (tag at `603fe14`, not marked latest) | None: [`workbench-v0.2.0`](https://github.com/ChaseHendrick/Scrolls/releases/tag/workbench-v0.2.0) published 16 Oct 20:52 UTC with Chase's yes (tag at `f3ce065`, Latest), after the pentest fixes (#103) and the packaged Modal rates (#106) merged |

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
| Unroll v1.0 (viewer Space, [unroll-space.md](unroll-space.md)) | Released. Control panel redesign (grouped Layers, Ink Bench, View, Destroy, Scrolls), Settings saved in localStorage and settable by URL, plain language glossary, agent API (`unrollView.actions/settings/state/glossary`), Ink Bench button, CPU pick fallback for Destroy on GPUs without float targets. The overlay layer is labeled `ink_9um (9 µm)`, credited to the Vesuvius Challenge. README entries updated | Fix the audit findings below |
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
| Greek letter reader | **Done** 14 October. Released with Chase's approval in [PR #57](https://github.com/ChaseHendrick/Scrolls/pull/57): `kit letterread`, `kit greeklm`, training and benchmark scripts in `scripts/letters/`. [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58), merged by Chase at 21:59 UTC (merge `25914fb`), makes it installable, reads whole maps, adds controls and exports, and makes the CC BY 4.0 weights `letters-v2-ccby` the default. The letter reader thread installed the guide's pip line from `main` in a fresh venv afterward: it installs, fetches `letters-v2-ccby` and the demo passes. The weights are not in git. `letters-v2-ccby` is the release asset on tag [`letters-v2-ccby`](https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-ccby) (sha256 `b14988852fc7...`, CC BY 4.0, published 14 October). `letters-v2-real-step030000.npz` stays on tag [`letters-v2-real`](https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-real) (sha256 `44946dad...587477`, CC BY-NC 4.0), pinned in `kit/data/letter-weights.json`. Do not re-tag or delete either, because `--weights` downloads from them | Nothing open. Any new weights get a new tag and registry entry | Nobody | [`letter-reader.md`](letter-reader.md), [`logs/2026-10-14-letter-reader.md`](logs/2026-10-14-letter-reader.md) |
| Released tools in the README | **Done** 14 October: [PR #60](https://github.com/ChaseHendrick/Scrolls/pull/60) merged (`d1a34ff`) after Chase approved it (01:51 UTC). The README's "Released tools" section is generated from `docs/releases.json` | Nothing left open. Every later release from private work adds its entry with `python -m kit releases add` (AGENTS.md rule 15); Progress Prize releases arrive as a `release-readme/<submission_id>` branch from the private exporter, for a PR into `main` | None | [`releases.json`](releases.json), [PR #60](https://github.com/ChaseHendrick/Scrolls/pull/60) |
| PHerc0841 Hecate caveat and README finding 1 like for like | **Done** 14 October: [PR #37](https://github.com/ChaseHendrick/Scrolls/pull/37) merged after Chase left the call to Claude (02:22 UTC). PHerc0841 is now called held out for every reader except possibly Hecate, and finding 1 compares v8in 0.738 with `ink_9um` 0.907 on the same bare crop. Its own 2026-10-09 prize snapshot was dropped, since the 2026-10-11 snapshot already records the PHerc. 343 award | Nothing left open | None | [`logs/2026-10-09-pherc0841-hecate.md`](logs/2026-10-09-pherc0841-hecate.md) |

## Still binding from older sections (moved 14 October 2026)

These come from sections now in [HANDOFF-archive.md](HANDOFF-archive.md) and still apply:

- README "Novel finding 1" keeps its w045 correction until v8in's PHerc0841 crop scores replace it (the owner's choice; "Correction 8 October 2026").
- Generic tools and public benchmarks stay public even when an artifact's filename includes `candidate` ("Evidence and next public work").
- When you change code, also run the separate numerical experiment regressions ([TESTING.md](TESTING.md)), and never modify a script while it runs ("Environment").

## Older sections

Dated sections from 12 October 2026 and earlier, the 7 to 9 October corrections and the October review notes are in [HANDOFF-archive.md](HANDOFF-archive.md), newest first. Search it; do not read it whole.
