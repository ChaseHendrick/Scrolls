# Start here: from "no idea" to a first submission

Private operational plans, target outputs and submission material belong in [Scrolls-private](https://github.com/ChaseHendrick/Scrolls-private) (access required). This page is public background and general tooling guidance. Every other doc is listed by topic in the [docs index](README.md).

Checked 2026-10-13. Prize facts come from [scrollprize.org/prizes](https://scrollprize.org/prizes) as snapshotted on 2026-10-11 (`python -m kit prizes`). Re-check the live page before you invest time.

## What the problem is, in one paragraph

About 2,000 years ago Vesuvius buried a library of papyrus scrolls at Herculaneum. They are carbonized lumps that crumble if opened. They have been X-rayed (micro-CT) into 3D volumes. To read one you must (1) find the rolled sheet inside the volume and flatten it ("segmentation" or "tracing"), then (2) find the carbon ink on that flattened surface ("ink detection"). The ink barely differs from the papyrus in an X-ray, so step 2 uses machine learning. The language is ancient Greek (sometimes Latin), so nobody needs to decipher anything. Papyrologists read the images. Your job is to make images they can read. Details: [`pipeline.md`](pipeline.md).

## Where things stand (October 2026)

- **First Letters has been won once.** PHerc. 0343 was read on 8 October 2026 (Erwin Nieuwlaar). The prize now pays $50,000 for each of up to 9 more eligible scrolls, 21 of which are listed; the Grand Prize ($1,000,000 across four places) and the PHerc. Paris 4 title prize ($50,000) close on 25 June 2027.
- **Progress Prizes close on 31 October 2026** for this round ($590,000 a year). The last round gave 28 awards for merged bug fixes, QA tools, benchmarks and honest null runs.
- **The released ink models are hard to beat.** On PHerc. 0841, the one labelled scroll none of them trained on, `ink_9um`, d9v2, Reader v2 and v8in score within a few hundredths of AUC of each other, and our short fine-tunes of d9v2 did not improve on Reader v2 ([log](logs/2026-10-08-d9v2-finetune-sweep.md), [numbers](results.json)). Averaging depth windows or two readers helps a little; training a new network has not.
- **Keeping a surface on one sheet is the bottleneck.** villa's tracer does not hold its seed ([villa #2059](https://github.com/ScrollPrize/villa/issues/2059)) and a transient S3 404 becomes a permanent hole in renders ([villa #2058](https://github.com/ScrollPrize/villa/issues/2058), fix in [#2060](https://github.com/ScrollPrize/villa/pull/2060)). villa also has a new neural sheet tracer ([villa PR #2045](https://github.com/ScrollPrize/villa/pull/2045)); try it, but check it against the published windings before trusting it.
- **Our own automation** is AutoPipeline (AP): one run from a released scan to checked surfaces, renders, ink maps with their controls and labelled scores, with the plan frozen before any map is made. Its first public copy went out on 14 October 2026 on the branch `submission/progress-2026-10` (see [Released tools](../README.md#released-tools)); `main` holds the pieces (`kit`) and the benchmarks.

## Which prize to aim at

| If you have | Aim at | Why |
| --- | --- | --- |
| A laptop and evenings | Progress Prizes ($250 to $1,000 tiers, up to $20,000 for sustained tooling) | Bug fixes, QA tools and docs in villa win real money every month |
| A 12 GB+ NVIDIA GPU, an Apple Silicon Mac, or $50 of cloud credit | A First Letters run with a published report | Reproducible runs with honest results have won progress prizes; a positive one wins $50,000 |
| An ML background and months | Cross-scroll ink models, better surface tracing | These are the actual bottlenecks named by the organizers |
| A team and a year | Grand Prize | Needs whole-scroll unwrapping plus ink across most of it |

## Day by day

Each step below is a day or less. Nothing here needs weeks; the long part is waiting for a trace or a render to finish, and that can run while you do the next day's reading.

**Day 1: orientation, no GPU needed.**

1. Join the [Discord](https://discord.gg/V4fJhvtaQn). You must be registered there to win the Grand Prize, and the team announces new findings there first.
2. Read the organizers' [2026 open problems](https://scrollprize.org/2026_open_problems) post. It is the technical map of the whole pipeline and lists six concrete ways to help.
3. Run the [data access notebook](https://colab.research.google.com/github/ScrollPrize/villa/blob/main/vesuvius/src/vesuvius/examples/notebooks/example1_data_access.ipynb) in Colab, and browse scrolls in the [data browser](https://scrollprize.org/data_browser).
4. `python -m kit prizes` and `python -m kit doctor` here.

**Day 2: run the control.**

1. Pick your compute: your own GPU, an Apple Silicon Mac ([`mac.md`](mac.md)), or a rented one ([`compute.md`](compute.md)). A full First Letters run on Modal has cost other people about $14.
2. `python -m kit plan PHerc0826` and run steps 0 and 1: install villa, download the `ink_9um` checkpoints, render segment w035 of PHerc. 0139, run inference. On a Mac, `bash scripts/mac-verify.sh` does the whole control in one command.
3. You should see Greek letters. They are the hand-painted training labels, reproduced by a model that was trained on them ([comparison](logs/2026-10-07-w035-cpu.md)). This proves your setup works, nothing more.

**Day 3: score a reader on a scroll it never saw.**

1. `python -m kit fetch` a labelled PHerc. 0841 segment (w00, ag896 or ag405) and run the same reader on it, forward and with depth reversed.
2. `python -m kit auc` against the published labels, with the reversed map as the control. Leave a 64 px edge out of any crop (`--inner 64`), or the number is wrong by up to 0.03 ([README finding 2](../README.md#novel-findings)).
3. Compare with [`results.json`](results.json). You now have a benchmark that can fail, which most published nulls lack.

**Day 4: pick a scroll and write the rule before you look.**

1. Pick an eligible scroll. The [First Letters Scan Atlas](https://github.com/claudepro1515/first-letters-scan-atlas) ranks how clearly sheets show in each scan; it names PHerc0826, PHerc0358, PHerc0813 and PHerc1545 as most like scrolls where ink was found. Read what others already ran on your scroll first ([`state-of-play.md`](state-of-play.md), [`scan-status.md`](scan-status.md)).
2. Write your readout rule before any target map exists: `python -m kit run init ...`. The ledger hashes the rule, so a rule edited after you looked is caught by `kit run check`.

**Day 5: trace a surface.**

1. Grow a surface in VC3D from a seed on the outer wraps, where sheets are furthest apart. Use 200 generations for anything you will compare; 60 is only a quick check.
2. Check it against the published windings where the scroll has them, and **fix sheet switches by hand**. Published automatic patches mostly wander across sheets near the core.
3. Audit the render's chunks before you trust it: a missing chunk reads as zeros, not as an error (villa #2058).

**Day 6: render, infer, compare.**

1. Render, then run both seeds and both depth directions. Average a few depth windows rather than picking one by eye ([README finding 4](../README.md#novel-findings)).
2. Score your maps by the rule you wrote on day 4, with the reversed map as the control, and nothing else.
3. Log every dollar: `python -m kit run cost ...`.

**Day 7: submit something.**

- **Null result:** write it up like the published ones (commands, failures, costs, controls) and send it as a Progress Prize submission before the month's deadline. Better: also fix a villa bug you hit along the way and get the PR merged. Public posts follow [`AI-AGENTS.md`](AI-AGENTS.md#public-writing-for-villa-and-the-community): a specific title, the community's terms, your own voice.
- **Possible letters:** stop. Tell nobody in public. Follow [`WORKFLOW.md`](WORKFLOW.md).

## Realistic expectations

- The pool is real, but most of it needs papyrologist-readable text from a scroll where many people have already looked. In August and September 2026 at least five independent teams ran the released ink models on eligible scrolls and published nulls.
- 28 progress awards went out in July and August 2026 ($64,500 total). The two largest ($20,000 each) went to sustained tooling work (ScrollFiesta, patch-based unwrapping). Most were $250 to $1,000.
- A first public First Letters run cost about $14 on Modal ([bnleft/first-light-pherc0211](https://github.com/bnleft/first-light-pherc0211)). Another ran on one RTX 3060 at home ([Bullo27/first-letters-survey](https://github.com/Bullo27/first-letters-survey)). The PHerc. 0343 result came from careful mesh work and the released readers, not a new model.
- You must open-source what wins (permissive license), and datasets used for training under CC BY-NC 4.0 for the Grand Prize.
