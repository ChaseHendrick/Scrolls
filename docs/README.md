# Docs index: where each topic lives

Check this page before you research or write anything. Each topic has one home. If the home already covers your question, read it and extend it there instead of writing a new note. If you do write a new dated note in `logs/`, add a line for it to the topic below and link it from the topic's home.

To search everything at once: `grep -rli "your words" docs/ README.md AGENTS.md`. Private plans, target-scroll work and submission material are not in this repository; they live in [Scrolls-private](https://github.com/ChaseHendrick/Scrolls-private) (access required), which has its own index.

Updated 14 October 2026.

## Where things stand

| Topic | Home | Also see |
| --- | --- | --- |
| Current state, open items and next steps | [`HANDOFF.md`](HANDOFF.md), the one handoff every agent reads and updates; older dated sections in [`HANDOFF-archive.md`](HANDOFF-archive.md) | [`plans/roadmap.md`](plans/roadmap.md) (pointer to the private roadmap) |
| New here, from no idea to a first submission | [`start-here.md`](start-here.md) | [`pipeline.md`](pipeline.md) |
| Every benchmark number, with settings and source | [`results.json`](results.json) | README "Novel findings" (only results not published elsewhere) |
| What has been read, tried and paid by everyone | [`state-of-play.md`](state-of-play.md) (checked 6 and 7 October; PHerc. 343 award row 9 and 14 October) | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md), [`tricks.md`](tricks.md) |
| Which scans exist and what we processed | [`scan-status.md`](scan-status.md) | |
| Prize terms, amounts, deadlines, eligible scrolls | [`prizes.md`](prizes.md), `python -m kit prizes` | |
| What has been released from private work | [`releases.json`](releases.json), shown as the README's "Released tools" section | `python -m kit releases list`; AGENTS.md rule 15 |

## Rules and standards

| Topic | Home | Also see |
| --- | --- | --- |
| Agent rules and standing decisions | [`../AGENTS.md`](../AGENTS.md) | [`AI-AGENTS.md`](AI-AGENTS.md) (full rulebook, public writing guide) |
| Repository map, one row per module and script | [`MAP.md`](MAP.md) | The top-level map in [`../AGENTS.md`](../AGENTS.md) |
| How we measure (controls, AUC, tracing, splits, cost) beside the community's practice | [`STANDARDS.md`](STANDARDS.md) | [`QUALITY.md`](QUALITY.md) (what each kind of claim needs), [`TESTING.md`](TESTING.md) |
| Claim labels (Sourced fact, Model output, ...) | [`NOVELTY.md`](NOVELTY.md) | |
| From idea to run to null or candidate | [`WORKFLOW.md`](WORKFLOW.md) | [`prereg/`](prereg/) |
| Failures we hit, append-only | [`logs/errors.md`](logs/errors.md) | [`ERROR-LOG.md`](ERROR-LOG.md) is only the pointer and format |
| CLI and output conventions | [`UI-UX.md`](UI-UX.md) | |

## Tools and how to run things

| Topic | Home | Also see |
| --- | --- | --- |
| What villa does and what `kit/` adds | [`engine.md`](engine.md) | [`MAP.md`](MAP.md), the repository map |
| The scroll pipeline in plain words | [`pipeline.md`](pipeline.md) | |
| Apple Silicon Mac: commands, timings | [`mac.md`](mac.md) | |
| Compute: hardware, costs, local electricity ledger | [`compute.md`](compute.md) | [`compute/modal-pricing.md`](compute/modal-pricing.md) (Modal rates and default GPU), [`compute/modal-specs/`](compute/modal-specs/README.md), [`compute/digitalocean-workspace.md`](compute/digitalocean-workspace.md) |
| Scroll centre (umbilicus) finder: a centre line from CT, with its held-out error on the 13 published centre lines | [`../scripts/umbilicus/README.md`](../scripts/umbilicus/README.md) | [`evidence/2026-10-14-umbilicus/`](evidence/2026-10-14-umbilicus/README.md) (end-point rule calibration; held-out scores with the end trims; weight hashes), `results.json` `umbilicus_checks` |
| StrokeNet (text-likeness of ink map windows), its held-out test on PHerc. Paris 4 and the tile grid pilot | [`strokenet.md`](strokenet.md) | [`prereg/2026-10-14-strokenet.md`](prereg/2026-10-14-strokenet.md), [`prereg/2026-10-14-gridpilot.md`](prereg/2026-10-14-gridpilot.md), [`evidence/2026-10-14-strokenet/`](evidence/2026-10-14-strokenet/README.md), data [`strokenet-data-manifest.json`](strokenet-data-manifest.json), `results.json` `strokenet_checks` |
| Greek letter reader (letter hypotheses on ink maps, labels and photographs) | [`letter-reader.md`](letter-reader.md) | [`logs/2026-10-14-letter-reader.md`](logs/2026-10-14-letter-reader.md) (measurements), `results.json` `letter_reader_checks` |
| Surface correction tool | [`surfacefix.md`](surfacefix.md) | [`logs/2026-10-07-real-surfacefix-validation.md`](logs/2026-10-07-real-surfacefix-validation.md) |
| Row score fast resize | [`rowscore.md`](rowscore.md) | |
| Phantoms and the static viewer | [`phantom-and-viewer.md`](phantom-and-viewer.md) | [`logs/2026-10-07-phantom-demo.md`](logs/2026-10-07-phantom-demo.md) |

## Research by topic

| Topic | Home | Dated notes |
| --- | --- | --- |
| Papers, datasets, Kaggle | [`logs/2026-10-07-literature.md`](logs/2026-10-07-literature.md), [`papers.json`](papers.json) | [`logs/2026-10-11-charred-ink.md`](logs/2026-10-11-charred-ink.md) (what charred ink has been shown to do) |
| URLs for organizers, tutorials, community reports | [`sources.md`](sources.md) | [`external.md`](external.md) (outside tools, data and repositories, with what each is for) |
| Community repositories and needs | [`logs/2026-10-07-community-scan.md`](logs/2026-10-07-community-scan.md) | [`logs/2026-10-07-community-needs.md`](logs/2026-10-07-community-needs.md), [`tricks.md`](tricks.md) |
| Ink model evaluation on public labels | [`plans/2026-10-07-training.md`](plans/2026-10-07-training.md) (method) | [`logs/2026-10-08-d9v2-finetune-sweep.md`](logs/2026-10-08-d9v2-finetune-sweep.md), [`logs/2026-10-08-w045-not-held-out.md`](logs/2026-10-08-w045-not-held-out.md), [`logs/2026-10-09-pherc0841-hecate.md`](logs/2026-10-09-pherc0841-hecate.md), [`logs/2026-10-07-novel-checks.md`](logs/2026-10-07-novel-checks.md), [`logs/2026-10-07-overlap-and-baseline.md`](logs/2026-10-07-overlap-and-baseline.md), [`logs/2026-10-07-w035-cpu.md`](logs/2026-10-07-w035-cpu.md), [`logs/2026-10-07-cloud-partial.md`](logs/2026-10-07-cloud-partial.md) |
| Label-free and model-free ink signals, fine-tuning and crop checks (lanes A to I) | the lane logs: [A](logs/2026-10-07-grok-laneA.md) [B](logs/2026-10-07-grok-laneB.md) [C](logs/2026-10-07-grok-laneC.md) [D](logs/2026-10-07-grok-laneD.md) [F](logs/2026-10-07-grok-laneF.md) [G](logs/2026-10-07-grok-laneG.md) [H](logs/2026-10-07-grok-laneH.md) [I](logs/2026-10-07-grok-laneI.md) | [`prereg/`](prereg/) for lanes G and I, [`logs/2026-10-07-followup-tests.md`](logs/2026-10-07-followup-tests.md) |
| Mesh placement and cross-scan transforms | [`plans/2026-10-07-mesh-hypothesis.md`](plans/2026-10-07-mesh-hypothesis.md) (protocol) | [`logs/2026-10-07-mesh-hypothesis.md`](logs/2026-10-07-mesh-hypothesis.md), [`data/mesh-hypothesis/`](data/mesh-hypothesis/README.md) |
| Surface geometry speed and resolution | [`logs/2026-10-07-adaptive-resolution.md`](logs/2026-10-07-adaptive-resolution.md) | [`logs/2026-10-07-production-speed.md`](logs/2026-10-07-production-speed.md), [`logs/2026-10-07-production-scaling.md`](logs/2026-10-07-production-scaling.md), [`logs/2026-10-07-coarse-support-mask.md`](logs/2026-10-07-coarse-support-mask.md), [`logs/2026-10-07-ufsm-review.md`](logs/2026-10-07-ufsm-review.md) |
| CT reconstruction | [`logs/2026-10-07-reconstruction-tests.md`](logs/2026-10-07-reconstruction-tests.md) | |
| Where GPUs help villa users | [`logs/2026-10-12-b300-gpu-stages.md`](logs/2026-10-12-b300-gpu-stages.md) | [`manuscripts/compute-limits/`](manuscripts/compute-limits/README.md) (shelved, not released) |
| Turning a traced render upright before ink detection | [`logs/2026-10-14-upright-before-ink.md`](logs/2026-10-14-upright-before-ink.md) | `results.json` `orientation_checks` |
| Findings reported to villa (false 404, seed drift, #1843) | [`logs/2026-10-12-upstream-reports.md`](logs/2026-10-12-upstream-reports.md) | [`evidence/2026-10-12-false-404/`](evidence/2026-10-12-false-404/README.md), [`contrib/`](contrib/) |
| Setup history (6 and 7 October) | [`logs/2026-10-06.md`](logs/2026-10-06.md) | [`logs/2026-10-07-mac-and-repos.md`](logs/2026-10-07-mac-and-repos.md), [`logs/2026-10-07-merged-review-closure.md`](logs/2026-10-07-merged-review-closure.md) |

## Raw records

`evidence/` holds byte-exact receipts (logs, inputs, review snapshots) behind the logs above. Its files repeat on purpose: each folder is a frozen record, so never merge, move or edit them; hashes in the logs depend on them.
