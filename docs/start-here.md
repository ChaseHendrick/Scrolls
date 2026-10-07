# Start here: from "no idea" to a first submission

Checked 2026-10-06. Prize facts come from [scrollprize.org/prizes](https://scrollprize.org/prizes) (source in [villa](https://github.com/ScrollPrize/villa/blob/main/scrollprize.org/docs/34_prizes.md), commit `e0bbb8b`). Re-check the live page before you invest time.

## What the problem is, in one paragraph

About 2,000 years ago Vesuvius buried a library of papyrus scrolls at Herculaneum. They are carbonized lumps that crumble if opened. They have been X-rayed (micro-CT) into 3D volumes. To read one you must (1) find the rolled sheet inside the volume and flatten it ("unwrapping" or "segmentation"), then (2) find the carbon ink on that flattened surface ("ink detection"). The ink barely differs from the papyrus in an X-ray, so step 2 uses machine learning. The language is ancient Greek (sometimes Latin), so nobody needs to decipher anything. Papyrologists read the images. Your job is to make images they can read. Details: [`pipeline.md`](pipeline.md).

## Which prize to aim at

| If you have | Aim at | Why |
| --- | --- | --- |
| A laptop and evenings | Progress Prizes ($250 to $1,000 tiers) | Bug fixes, QA tools and docs in villa win real money every month |
| A 12 GB+ NVIDIA GPU or $50 of cloud credit | A First Letters run with a published report | Reproducible runs with honest results have won progress prizes; a positive one wins $50k |
| An ML background and months | Cross-scroll ink models, better surface tracing | These are the actual bottlenecks named by the organizers |
| A team and a year | Grand Prize | Needs whole-scroll unwrapping plus ink across most of it |

## Week by week

**Week 1: orientation, no GPU needed.**

1. Join the [Discord](https://discord.gg/V4fJhvtaQn). You must be registered there to win the Grand Prize, and the team announces new findings there first (the 24 Sep 2026 PHerc. 1447 letters were announced there).
2. Read the organizers' [2026 open problems](https://scrollprize.org/2026_open_problems) post. It is the technical map of the whole pipeline and lists six concrete ways to help.
3. Run the [data access notebook](https://colab.research.google.com/github/ScrollPrize/villa/blob/main/vesuvius/src/vesuvius/examples/notebooks/example1_data_access.ipynb) in Colab.
4. Browse scrolls in the [data browser](https://scrollprize.org/data_browser).
5. `python -m kit prizes` and `python -m kit doctor` here.

**Week 2: run the control.**

1. Get a GPU (yours, or rented; see [`compute.md`](compute.md)).
2. `python -m kit plan PHerc0826` and run steps 0 and 1: install villa, download the `ink_9um` checkpoints, render segment w035 of PHerc. 0139, run inference.
3. You should see Greek letters. They are the hand-painted training labels, reproduced by a model that was trained on them ([comparison](logs/2026-10-07-w035-cpu.md)). This proves your setup works, nothing more.

**Weeks 3 to 6: a real First Letters attempt.**

1. Pick an eligible scroll. The [First Letters Scan Atlas](https://github.com/claudepro1515/first-letters-scan-atlas) ranks how clearly sheets show in each scan; it names PHerc0826, PHerc0358, PHerc0813 and PHerc1545 as most like scrolls where ink was found. Read what others already ran on your scroll first ([`state-of-play.md`](state-of-play.md)).
2. Write your readout rule before you look: `python -m kit run init ...`.
3. Grow a surface in VC3D and **fix sheet switches by hand**. Published automatic patches mostly wander across sheets near the core.
4. Render, run both seeds and both depth directions, compare with your rule.
5. Log every dollar: `python -m kit run cost ...`.

**Then: submit something.**

- **Null result:** write it up like the published ones (commands, failures, costs, controls) and send it as a Progress Prize submission before the month's deadline. Better: also fix a villa bug you hit along the way and get the PR merged.
- **Possible letters:** stop. Tell nobody in public. Follow [`WORKFLOW.md`](WORKFLOW.md).

## Realistic expectations

- The $2.14M pool is real, but about $1.55M of it needs papyrologist-readable text from a scroll where many people have already looked.
- 28 progress awards went out in July and August 2026 ($64,500 total). The two largest ($20,000 each) went to sustained tooling work (ScrollFiesta, patch-based unwrapping). Most were $250 to $1,000.
- A first public First Letters run cost about $14 on Modal ([bnleft/first-light-pherc0211](https://github.com/bnleft/first-light-pherc0211)). Another ran on one RTX 3060 at home ([Bullo27/first-letters-survey](https://github.com/Bullo27/first-letters-survey)).
- You must open-source what wins (permissive license), and datasets used for training under CC BY-NC 4.0 for the Grand Prize.
