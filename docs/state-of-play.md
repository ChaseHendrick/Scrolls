# State of play (checked 2026-10-06)

What has been read, what has been tried, and who has been paid. Read this before choosing a target so you do not repeat a published run. Each line carries a source. Community repositories are cited for what they report; they are not organizer statements.

## Read so far (organizer statements)

| When | What | Source |
| --- | --- | --- |
| Oct 2023 | First word from inside a sealed scroll: ΠΟΡΦΥΡΑϹ ("purple"), Luke Farritor | [scrollprize.org/firstletters](https://scrollprize.org/firstletters) |
| Dec 2023 | Grand Prize: 15 partial columns of PHerc. Paris 4 (Nader, Farritor, Schilliger) | [scrollprize.org/grandprize](https://scrollprize.org/grandprize) |
| Dec 2024 | 2024 "90% of four scrolls" prize not won; $60k for first automated segmentation | [winners](https://scrollprize.org/winners) |
| May 2025 | First title: PHerc. 172, Philodemus, *On Vices* | [Substack](https://scrollprize.substack.com/p/60000-first-title-prize-awarded) |
| Mar 2026 | $200k Kaggle surface detection competition closed; top teams used nnU-Net ensembles | [winners](https://scrollprize.org/winners#surface-detection-kaggle-winners) |
| Jun 2026 | PHerc. 1667 (Scroll 4) read end to end: lower parts of about 22 columns of the surviving core. PHerc. 139 title evidence: Philodemus, *On Gods* book 8 | [first scroll](https://scrollprize.org/firstscroll), [arXiv:2606.29085](https://arxiv.org/abs/2606.29085) |
| Jun 2026 | New $1M 2027 Grand Prize and $50k-per-scroll First Letters launched | [Substack](https://scrollprize.substack.com/p/a-new-1m-grand-prize-for-2027), [prizes](https://scrollprize.org/prizes) |
| 24 Sep 2026 | PHerc. 1447 removed from First Letters "where letters have now been found"; a new 9 µm ink recipe was announced on Discord, model not released at the time | [villa #1887](https://github.com/ScrollPrize/villa/pull/1887); reported in [nerln](https://github.com/nerln/vesuvius-first-letters-pherc0800) and [Bullo27](https://github.com/Bullo27/first-letters-survey) READMEs |

An organizer note on AI: an autonomous agent swarm adapted from karpathy/autoresearch "nearly doubled the validation Dice score (computed on pseudo-labels) on PHerc. 1667 while training only on PHerc. 139 data" ([open problems, section 5](https://scrollprize.org/2026_open_problems)).

## Published First Letters attempts on eligible scrolls (all nulls)

| Who | Scroll(s) | Result | Notes |
| --- | --- | --- | --- |
| Lutfiya Miller, Chris Müller | PHerc0826 | No ink | Aug 2026 progress prize ($1,000); runbook at millerandmuller/first-light-pherc0826 |
| [bnleft](https://github.com/bnleft/first-light-pherc0211) | PHerc0211 | "I didn't see any ink in the window." | Preregistered readout; $13.53 on Modal; spiral fit, lasagna, `ink_9um`; Claude Code assisted |
| [Bullo27 (Matteo Bulloni)](https://github.com/Bullo27/first-letters-survey) | 21 eligible scrolls, 65 patches, 971 cm² | No letter-like ink | One RTX 3060; one-command `fls.py`; Claude assisted. Automatic patches mostly cross sheets near the core |
| [nerln](https://github.com/nerln/vesuvius-first-letters-pherc0800) | PHerc0800 (+ MANBp) | Null for public `ink_9um` | Forward vs reverse depth comparison; blinded AI readers on shuffled panels |
| [ShribyrLabs (Chris Scheirer)](https://github.com/ShribyrLabs/vesuvius-reports) | PHerc0826 | Null | Letter-scale benchmark for 9 µm readers; m7 orientation bias; Claude agent on one RTX 5090 |

Related diagnostics: [first-letters-scan-atlas](https://github.com/claudepro1515/first-letters-scan-atlas) (CPU-only sheet visibility per scroll; ranks PHerc0826, 0358, 0813, 1545 most like ink-found scans) and [first-letters-fit-audit](https://github.com/claudepro1515/first-letters-fit-audit) (published spiral fits of eligible scrolls do not detectably sit on sheets).

What these nulls say: the public 9 µm model, on automatically traced or spiral-fitted surfaces, did not show letters. What they do not say: that these scrolls have no ink. On PHerc0841, the same public pipeline found ink only as blobs where the team's 2.4 µm predictions show text (Bullo27 calibration). Surface quality and model generalization are the open variables.

## Apple Silicon support (open PRs, 2026-10-07)

Ink inference on MPS: [#1865](https://github.com/ScrollPrize/villa/pull/1865) (the tutorial's `vesuvius.ink_detection` path) and [#1812](https://github.com/ScrollPrize/villa/pull/1812) (the separate `ink-detection/optimized_inference` path) open, [#1770](https://github.com/ScrollPrize/villa/pull/1770) closed for inactivity. Training, `vesuvius.predict` and spiral fitting on MPS: [#1927](https://github.com/ScrollPrize/villa/pull/1927), [#1988](https://github.com/ScrollPrize/villa/pull/1988), [#1925](https://github.com/ScrollPrize/villa/pull/1925). Lasagna on MPS merged ([#1639](https://github.com/ScrollPrize/villa/pull/1639)). Details: [`mac.md`](mac.md).

## Recent Progress Prize winners (what gets paid)

August 2026, $31,000 total: $20,000 patch-based unwrapping (William Stevens); $2,500 9 µm surface model and ScrollFiesta fixes; $1,000 each for ink checkpoint benchmarking, seeded sheet growing, a depth-slice study, Lasagna and VC3D fixes, the PHerc. 0826 First Letters run, nnInteractive label refinement; $500 each for dense pseudo-labels and checkpoint repair, assorted villa fixes, sustained PR work; $250 each for a shared disk cache, spiral fitting on Windows, VC3D agent bridge fixes, checkpoint averaging.

July 2026, $33,500 total: $20,000 ScrollFiesta (Ben Kyles); $2,500 patch connectivity; $1,000 each for portable GPU kernels, Zarr 3 read fixes, an ink validation harness, `windcheck`, TIFXYZ Doctor, faster augmentation, reproducibility fixes, spiral fitting on 12 GB GPUs, tifxyz repair, `scroll-data-audit`, `fit_spiral` fixes.

Source: [winners](https://scrollprize.org/winners) ([source file](https://github.com/ScrollPrize/villa/blob/main/scrollprize.org/docs/15_winners.md)).

Pattern: small, merged, verifiable fixes to tools people use are paid reliably. Honest null runs with full commands and costs are paid. Large awards go to sustained work that the team adopts.
