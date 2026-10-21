# Docs index: where each topic lives

Check this page before you research or write anything. Each topic has one home. If the home already covers your question, read it and extend it there instead of writing a new note. If you do write a new dated note in `logs/`, add a line for it to the topic below and link it from the topic's home.

To search everything at once: `grep -rli "your words" docs/ README.md AGENTS.md`. Private plans, target-scroll work and submission material are not in this repository; they live in [Scrolls-private](https://github.com/ChaseHendrick/Scrolls-private) (access required), which has its own index.

Updated 18 October 2026.

## Where things stand

| Topic | Home | Also see |
| --- | --- | --- |
| Current state, open items and next steps | [`HANDOFF.md`](HANDOFF.md), the one handoff every agent reads and updates; older dated sections in [`HANDOFF-archive.md`](HANDOFF-archive.md) |
| Standing user decisions, dated, with Chase's words (including replaced ones) | [`DECISIONS.md`](DECISIONS.md); AGENTS.md lists the ones in force, one line each | [`plans/roadmap.md`](plans/roadmap.md) (pointer to the private roadmap) |
| New here: browser tour, synthetic practice, setup and first tasks with official tools | [`start-here.md`](start-here.md), the shareable beginner guide | [`pipeline.md`](pipeline.md), [`tools/starter.md`](tools/starter.md) |
| What Workbench is, what its tools look like and what to open first | [`workbench.md`](workbench.md), the picture guide | [`start-here.md`](start-here.md), [`tools/README.md`](tools/README.md) |
| What a technical term means (A to Z) | [`../GLOSSARY.md`](../GLOSSARY.md) | [`vesuvius-bible/`](vesuvius-bible/bible.md#app-glossary) Appendix A |
| A cited reference book on the scrolls and the challenge, 2023 to 2026 (history, papyrus, imaging, prizes, inventory, pipeline, tools, glossary, timeline, FAQ, bibliography) | [`vesuvius-bible/`](vesuvius-bible/) ([`index.md`](vesuvius-bible/index.md), [`llms.txt`](vesuvius-bible/llms.txt), one file: [`bible.md`](vesuvius-bible/bible.md)) | [`start-here.md`](start-here.md) |
| Every benchmark number, with settings and source | [`results.json`](results.json) | README "Novel findings" (only results not published elsewhere) |
| Ink reader leaderboard: every released reader on PHerc0841 w00, ag896, ag405 and w045, with the reversed and shuffled controls, held-out status, window, source and date | [`leaderboard.md`](leaderboard.md), generated from `results.json` by `python -m kit leaderboard render` (`check` runs in the tests) | `results.json` `held_out` and `held_out_by_reader`; `kit gate` |
| What has been read, tried and paid by everyone | [`state-of-play.md`](state-of-play.md) (checked 6 and 7 October; PHerc. 343 award row 9 and 14 October) | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md), [`tricks.md`](tricks.md) |
| Which scans exist and what we processed | [`scan-status.md`](scan-status.md) | |
| Prize terms, amounts, deadlines, eligible scrolls | [`prizes.md`](prizes.md), `python -m kit prizes` | |
| What has been released from private work | [`releases.json`](releases.json), shown as the README's "Released tools" section | `python -m kit releases list`; AGENTS.md rule 15 |
| Unroll, the released interactive 3D viewer (Hugging Face Space, v1.0.0, Apache 2.0 for all code, CC BY-NC 4.0 scan data) | [`unroll-space.md`](unroll-space.md), live at [huggingface.co/spaces/SharpMeow/unroll](https://huggingface.co/spaces/SharpMeow/unroll) | README "Released tools" |
| Ink Lens, a control-checked ink map of your own region of a VC3D segment written back as VC3D files (ZeroGPU Space and client, not yet deployed, 20 October) | [`tools/ink-lens.md`](tools/ink-lens.md), code in [`../spaces/ink-lens/`](../spaces/ink-lens/), rule in [`prereg/2026-10-20-ink-lens-gate.md`](prereg/2026-10-20-ink-lens-gate.md) | [`tools/scroll-lens.md`](tools/scroll-lens.md) |
| Scroll Lens, a ZeroGPU Space that shows the organizers' 3D DINO, ink and surface models on a cube of a public scan, with click search (v1.0.0, 17 October) | [`tools/scroll-lens.md`](tools/scroll-lens.md), live at [huggingface.co/spaces/SharpMeow/scroll-lens](https://huggingface.co/spaces/SharpMeow/scroll-lens), code in [`../spaces/scroll-lens/`](../spaces/scroll-lens/) | [`unroll-space.md`](unroll-space.md) |

## Rules and standards

| Topic | Home | Also see |
| --- | --- | --- |
| Agent rules and standing decisions | [`../AGENTS.md`](../AGENTS.md) | [`AI-AGENTS.md`](AI-AGENTS.md) (full rulebook, public writing guide) |
| Repository map, one row per module and script | [`MAP.md`](MAP.md) | The top-level map in [`../AGENTS.md`](../AGENTS.md) |
| How we measure (controls, AUC, tracing, splits, cost) beside the community's practice | [`STANDARDS.md`](STANDARDS.md) | [`QUALITY.md`](QUALITY.md) (what each kind of claim needs), [`TESTING.md`](TESTING.md) |
| Claim labels (Sourced fact, Model output, ...) | [`NOVELTY.md`](NOVELTY.md) | |
| What pictures and clips public Git may hold: the public media rule (no model output, no prize-eligible scrolls, at most 1920 px and 4 MB, a sidecar each) | [`media/README.md`](media/README.md) | [`assets/README.md`](assets/README.md); the AGENTS.md standing decision and [`DECISIONS.md`](DECISIONS.md) row of 18 October 2026 |
| From idea to run to null or candidate | [`WORKFLOW.md`](WORKFLOW.md) | [`prereg/`](prereg/) |
| Failures we hit, append-only | [`logs/errors.md`](logs/errors.md) | [`ERROR-LOG.md`](ERROR-LOG.md) is only the pointer and format |
| CLI and output conventions | [`UI-UX.md`](UI-UX.md) | |
| Recurring checks every agent runs at session start, and the daily workflow (prize page, release list, AutoPipeline watcher, handoff size and age, repository tests) | [`routines.json`](routines.json), run by `python3 -m kit routines run --due` | [`AI-AGENTS.md`](AI-AGENTS.md#session-start-repository-routines), [`../.github/workflows/routines.yml`](../.github/workflows/routines.yml) |
| How every tool is documented: the tool-page standard, its fields and sections, and what the checker checks | [`TOOL-DOCS.md`](TOOL-DOCS.md) | [`../templates/tool-doc.md`](../templates/tool-doc.md); AGENTS.md rule 16 |

## Tools and how to run things

| Topic | Home | Also see |
| --- | --- | --- |
| Every tool, one reference page each: options with defaults, inputs, outputs, failures, checks and rules for agents | [`tools/README.md`](tools/README.md) (generated index; [`tools/index.json`](tools/index.json) for agents) | `python -m kit.tooldocs list`; [`TOOL-DOCS.md`](TOOL-DOCS.md) |
| Optional Harness2 agent-workflow evaluation with synthetic provenance fixtures | [`tools/harness2.md`](tools/harness2.md) | [`tools/provenance.md`](tools/provenance.md) |
| Scrolls Starter: local setup check, synthetic practice and reader command builder | [`tools/starter.md`](tools/starter.md) | [`start-here.md`](start-here.md) |
| What villa does and what `kit/` adds | [`engine.md`](engine.md) | [`MAP.md`](MAP.md), the repository map |
| The scroll pipeline in plain words | [`pipeline.md`](pipeline.md) | |
| AutoPipeline reference: commands, settings, environment, stages, cost logging, agent rules (the released package, 0.1.5, lives on branch `submission/progress-2026-10-fix5`) | [`autopipeline/README.md`](autopipeline/README.md) | [`autopipeline/AGENTS.md`](autopipeline/AGENTS.md) |
| Release media: heroes, cards, GIFs and clips, with provenance, dimensions, labels and reuse | [`assets/README.md`](assets/README.md) | [`media/README.md`](media/README.md) (the public media rule), [`tools/media.md`](tools/media.md), root README and AutoPipeline reference |
| Apple Silicon Mac: commands, timings | [`mac.md`](mac.md) | |
| Compute: hardware, costs, local electricity ledger | [`compute.md`](compute.md) | [`compute/modal-pricing.md`](compute/modal-pricing.md) (Modal rates and default GPU), [`compute/modal-specs/`](compute/modal-specs/README.md), [`compute/digitalocean-workspace.md`](compute/digitalocean-workspace.md) |
| Scroll center (umbilicus) finder: a center line from CT, with its held-out error on the 13 published center lines | [`../scripts/umbilicus/README.md`](../scripts/umbilicus/README.md) | [`evidence/2026-10-14-umbilicus/`](evidence/2026-10-14-umbilicus/README.md) (end-point rule calibration; held-out scores with the end trims; weight hashes), `results.json` `umbilicus_checks` |
| StrokeNet (text-likeness of ink map windows), its held-out test on PHerc. Paris 4 and the tile grid pilot | [`strokenet.md`](strokenet.md) | [`prereg/2026-10-14-strokenet.md`](prereg/2026-10-14-strokenet.md), [`prereg/2026-10-14-gridpilot.md`](prereg/2026-10-14-gridpilot.md), [`evidence/2026-10-14-strokenet/`](evidence/2026-10-14-strokenet/README.md), data [`strokenet-data-manifest.json`](strokenet-data-manifest.json), `results.json` `strokenet_checks` |
| Scroll Text Reader (Greek LineNet and explicit local OCR for installed languages) | [`letter-reader.md`](letter-reader.md), [`tools/reader-backends.md`](tools/reader-backends.md) | [`logs/2026-10-14-letter-reader.md`](logs/2026-10-14-letter-reader.md) (measurements), `results.json` `letter_reader_checks` |
| UV overlap gate: a flattened sheet's UV triangles checked for overlap, coverage and one piece (`python -m kit uvgate`), and the OBJ benchmark (`scripts/bench_uvgate.py`) | [`uvgate.md`](uvgate.md), [`tools/uvgate.md`](tools/uvgate.md) | [`logs/2026-10-13-uvgate-fast.md`](logs/2026-10-13-uvgate-fast.md) (speed and parity on PHerc0139 w039 and synthetic meshes) |
| Relative winding consistency: whether winding counts between points can all hold at once (`python -m kit windconsistency`) | [`windconsistency.md`](windconsistency.md), [`tools/windconsistency.md`](tools/windconsistency.md) | [`MAP.md`](MAP.md) |
| Segment stack check: order, coincident or oddly spaced pairs, missing sectors, skipped windings, turn overlaps and stack ends of consecutive segments, from geometry against the umbilicus (`python -m kit stackcheck`) | the usage section of [`logs/2026-10-14-pherc0139-segment-defects.md`](logs/2026-10-14-pherc0139-segment-defects.md) and the `kit/stackcheck.py` docstring | [`MAP.md`](MAP.md) |
| Modern segmentation models next to nnU-Net (MedNeXt, Primus, Swin UNETR, Auto3DSeg, SegFormer, DINOv2 and v3, SAM 2, MedSAM2, Mamba and SS2D): licenses, fit, trainers, sheet follower and frozen probe (`python -m kit segzoo`) | [`tools/segzoo.md`](tools/segzoo.md) | [`MAP.md`](MAP.md), [`GLOSSARY.md`](../GLOSSARY.md) |
| Surface correction tool | [`surfacefix.md`](surfacefix.md) | [`logs/2026-10-07-real-surfacefix-validation.md`](logs/2026-10-07-real-surfacefix-validation.md) |
| Row score fast resize | [`rowscore.md`](rowscore.md) | |
| Phantoms and the static viewer | [`phantom-and-viewer.md`](phantom-and-viewer.md) | [`logs/2026-10-07-phantom-demo.md`](logs/2026-10-07-phantom-demo.md) |

## Research by topic

| Topic | Home | Dated notes |
| --- | --- | --- |
| Papers, datasets, Kaggle | [`logs/2026-10-07-literature.md`](logs/2026-10-07-literature.md), [`papers.json`](papers.json) | [`logs/2026-10-11-charred-ink.md`](logs/2026-10-11-charred-ink.md) (what charred ink has been shown to do) |
| URLs for organizers, tutorials, community reports | [`sources.md`](sources.md) | [`external.md`](external.md) (outside tools, data and repositories, with what each is for) |
| Community repositories and needs | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | [`logs/2026-10-07-community-needs.md`](logs/2026-10-07-community-needs.md), [`tricks.md`](tricks.md) |
| Ink model evaluation on public labels | [`plans/2026-10-07-training.md`](plans/2026-10-07-training.md) (method) | [`logs/2026-10-08-d9v2-finetune-sweep.md`](logs/2026-10-08-d9v2-finetune-sweep.md), [`logs/2026-10-08-w045-not-held-out.md`](logs/2026-10-08-w045-not-held-out.md), [`logs/2026-10-09-pherc0841-hecate.md`](logs/2026-10-09-pherc0841-hecate.md), [`logs/2026-10-16-reader-exposure.md`](logs/2026-10-16-reader-exposure.md) (which released reader trained on which labeled segment; Hecate's base model trained on PHerc0841, while Hecate's own published split rule would keep it validation-only), [`logs/2026-10-07-novel-checks.md`](logs/2026-10-07-novel-checks.md), [`logs/2026-10-07-overlap-and-baseline.md`](logs/2026-10-07-overlap-and-baseline.md), [`logs/2026-10-07-w035-cpu.md`](logs/2026-10-07-w035-cpu.md), [`logs/2026-10-07-cloud-partial.md`](logs/2026-10-07-cloud-partial.md) |
| Label-free and model-free ink signals, fine-tuning and crop checks (lanes A to I) | the lane logs: [A](logs/2026-10-07-grok-laneA.md) [B](logs/2026-10-07-grok-laneB.md) [C](logs/2026-10-07-grok-laneC.md) [D](logs/2026-10-07-grok-laneD.md) [F](logs/2026-10-07-grok-laneF.md) [G](logs/2026-10-07-grok-laneG.md) [H](logs/2026-10-07-grok-laneH.md) [I](logs/2026-10-07-grok-laneI.md) | [`prereg/`](prereg/) for lanes G and I, [`logs/2026-10-07-followup-tests.md`](logs/2026-10-07-followup-tests.md) |
| Mesh placement and cross-scan transforms | [`plans/2026-10-07-mesh-hypothesis.md`](plans/2026-10-07-mesh-hypothesis.md) (protocol) | [`logs/2026-10-07-mesh-hypothesis.md`](logs/2026-10-07-mesh-hypothesis.md), [`data/mesh-hypothesis/`](data/mesh-hypothesis/README.md) |
| Defects in published segments: PHerc0139 w035 partial, w034 and w036 crossing where it is missing; turn overlaps of w023 to w040 (a note on use) | [`logs/2026-10-14-pherc0139-segment-defects.md`](logs/2026-10-14-pherc0139-segment-defects.md) (measured from the segments and the umbilicus, with a CT look at 12 places) | [`plans/2026-10-07-mesh-hypothesis.md`](plans/2026-10-07-mesh-hypothesis.md) (mesh placement) |
| Surface geometry speed and resolution | [`logs/2026-10-07-adaptive-resolution.md`](logs/2026-10-07-adaptive-resolution.md) | [`logs/2026-10-07-production-speed.md`](logs/2026-10-07-production-speed.md), [`logs/2026-10-07-production-scaling.md`](logs/2026-10-07-production-scaling.md), [`logs/2026-10-07-coarse-support-mask.md`](logs/2026-10-07-coarse-support-mask.md), [`logs/2026-10-07-ufsm-review.md`](logs/2026-10-07-ufsm-review.md) |
| CT reconstruction | [`logs/2026-10-07-reconstruction-tests.md`](logs/2026-10-07-reconstruction-tests.md) | |
| Where GPUs help villa users | [`logs/2026-10-12-b300-gpu-stages.md`](logs/2026-10-12-b300-gpu-stages.md) | [`manuscripts/compute-limits/`](manuscripts/compute-limits/README.md) (shelved, not released) |
| Turning a traced render upright before ink detection | [`logs/2026-10-14-upright-before-ink.md`](logs/2026-10-14-upright-before-ink.md) | `results.json` `orientation_checks` |
| Findings reported to villa (false 404, seed drift, #1843), and the later fixes with their before and after (local metadata, missing normal grids, pyramid levels one voxel short; rechecked 21 Oct 2026) | [`logs/2026-10-12-upstream-reports.md`](logs/2026-10-12-upstream-reports.md) | [`evidence/2026-10-12-false-404/`](evidence/2026-10-12-false-404/README.md), [`contrib/`](contrib/) |
| Setup history (6 and 7 October) | [`logs/2026-10-06.md`](logs/2026-10-06.md) | [`logs/2026-10-07-mac-and-repos.md`](logs/2026-10-07-mac-and-repos.md), [`logs/2026-10-07-merged-review-closure.md`](logs/2026-10-07-merged-review-closure.md) |

## Raw records

`evidence/` holds byte-exact receipts (logs, inputs, review snapshots) behind the logs above. Its files repeat on purpose: each folder is a frozen record, so never merge, move or edit them; hashes in the logs depend on them.
