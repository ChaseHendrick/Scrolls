# Open prizes

**Snapshot checked 2026-10-06** from [scrollprize.org/prizes](https://scrollprize.org/prizes) and its source [`34_prizes.md`](https://github.com/ScrollPrize/villa/blob/main/scrollprize.org/docs/34_prizes.md) and [`prizeEligibility.json`](https://github.com/ScrollPrize/villa/blob/main/scrollprize.org/src/data/prizeEligibility.json) at villa commit `e0bbb8b40a2d`. Machine-readable copy: [`../kit/data/prizes-2026-10-06.json`](../kit/data/prizes-2026-10-06.json). The live page wins on any disagreement. Eligible lists change: PHerc. 1447 left First Letters on 24 Sep 2026 when the team found text in it ([villa #1887](https://github.com/ScrollPrize/villa/pull/1887)).

**Update, 2026-10-09.** Sourced fact: the organisers announced on 8 Oct 2026 that the $50,000 First Letters prize for PHerc. 343 has been awarded (["$50K First Letters Prize awarded for PHerc. 343"](https://scrollprize.substack.com/p/50k-first-letters-prize-awarded-for), Vesuvius Challenge Substack). On 2026-10-09 villa's `34_prizes.md` and `prizeEligibility.json` on main were byte-identical to `e0bbb8b40a2d`, and the live page still listed PHerc0343. The new snapshot [`../kit/data/prizes-2026-10-09.json`](../kit/data/prizes-2026-10-09.json) keeps the eligible lists as villa has them and marks the award, which `python -m kit prizes` prints. Interpretation: PHerc0343 is no longer open for First Letters, since the prize goes to the first team per scroll.

Label: **Sourced fact** (see [`NOVELTY.md`](NOVELTY.md)).

## Summary

| Prize | Money | Deadline (11:59pm Pacific) | Submit |
| --- | --- | --- | --- |
| 2027 Grand Prize | $1,000,000: 1st $800k, 2nd $100k, 3rd $50k, 4th $50k | 25 Jun 2027 | grandprize@scrollprize.org |
| First Letters | $50,000 per scroll, max 10 scrolls ($500k) | 25 Jun 2027 | [form](https://forms.gle/TM5ao8GwC2mDrdLk9) |
| PHerc. Paris 4 title | $50,000 | 25 Jun 2027 | [form](https://forms.gle/4zeVPPBtNdSCAQa88) |
| Progress Prizes | $20,000 best of month guaranteed; others $20k, $10k, $5k, $2,500, $1,000, $500, $250; about $590k per year | monthly; next 31 Oct 2026 | [form](https://docs.google.com/forms/d/e/1FAIpQLSc4flEfgK2nyjoczz2_U_XrIGMlgrnSknWatLqrFPnbtKfZwg/viewform) |

## 2027 Grand Prize

Fully unroll and make readable one of 13 scans: PHerc0125, 0191, 0211, 0257, 0268, 0358, 0800, 0813, 0826, 1203, 1218, 1447, 1545.

Key conditions (paraphrased; read the original):

- 100% of the recto surface unrolled (disconnected outer patches under 10% may be skipped), as tifxyz meshes with a low-distortion flattening, at most one mesh per column.
- At least 70% of each counted column's preserved characters legible letter by letter, without papyrological interpolation.
- No overlap between training and prediction regions.
- Pipeline integrated in [VC3D](https://github.com/ScrollPrize/villa/tree/main/volume-cartographer), fully automated with at most 8 documented hours of human input.
- Training datasets published under CC BY-NC 4.0, including every pseudo-labeling stage; seeds fixed and reported; experiment tracking (for example Weights & Biases) public.
- Docker image to reproduce; false-positive mitigation; held-out validation on public ground truth.
- Registered on the Discord at submission. No public disclosure before the official announcement.

The organizers suggest a team: one person on whole-scroll segmentation (start with the [spiral fitting tutorial](https://scrollprize.org/tutorial_spiral)), one on ink detection.

## First Letters

10 legible letters within one 4 cm² area of an eligible scroll. 22 eligible volumes:

| Scroll | Volume | Voxel (µm) |
| --- | --- | --- |
| PHerc0125 | 20250821151825 | 9.362 |
| PHerc0175A | 20250521115057 | 8.64 |
| PHerc0175B | 20250521125822 | 8.64 |
| PHerc0191 | 20250821151635 | 9.362 |
| PHerc0211 | 20250821151803 | 9.362 |
| PHerc0257 | 20250821151750 | 9.362 |
| PHerc0268 | 20251110183117 | 8.64 |
| PHerc0306B | 20250521133212 | 8.64 |
| PHerc0343 (awarded 2026-10-08, see the update above) | 20250521140437 | 8.64 |
| PHerc0358 | 20250821151737 | 9.362 |
| PHerc0483A | 20250521140913 | 8.64 |
| PHerc0483B | 20251124083638 | 8.64 |
| PHerc0490A | 20250521151210 | 8.64 |
| PHerc0490B | 20250521151215 | 8.64 |
| PHerc0800 | 20250521135224 | 8.64 |
| PHerc0813 | 20250821151723 | 9.362 |
| PHerc0826 | 20250821151701 | 9.362 |
| PHerc0846A | 20250728152254 | 9.362 |
| PHerc0846B | 20250804142305 | 9.362 |
| PHerc1203 | 20250820131727 | 9.362 |
| PHerc1218 | 20250521120456 | 8.64 |
| PHerc1545 | 20250821151648 | 9.362 |

Voxel sizes come from the volume names in `s3://vesuvius-challenge-open-data/<scroll>/volumes/`, listed on 2026-10-06.

A submission contains: the tifxyz mesh(es) with flattening; one programmatically generated image with no manual annotation of characters, a 1 cm scale bar and letter sizes in pixels and mm; rows annotated without covering the letters (a baseline or box), ideally over a fiber-visible render; methodology and a way to reproduce it; false-positive mitigation (large model windows can invent letterforms; show it is not hallucinated, for example on a held-out region); held-out validation on public ground truth. No public disclosure before the announcement.

Organizers' notes: existing ink models may or may not work on these scrolls; sometimes ink is visible directly in the render with no model; a little visible ink is a foothold for fine-tuning and iterative labeling. Their step-by-step guide: ["From CT Scan to Ancient Text: A First Letters Prize Workflow"](https://scrollprize.substack.com/p/from-ct-scan-to-ancient-text-a-first).

## PHerc. Paris 4 title

$50,000 for an image of the title of Scroll 1 that the papyrologists can read, from any of its scans including the 2.4 µm volumes. Substantial Epicurean prose has been read from this scroll, but its author and title are unknown. The expected title region has shown no ink so far; the top rows are physically missing, and the ink may differ. Submissions stay open until won.

## Progress Prizes

Open-ended monthly awards for open-source contributions. The organizers favor work that is released early, actually used, measured on real data (their public [ink](https://scrollprize.org/data_datasets#ink-labels-2026-07) and [surface](https://scrollprize.org/data_datasets#surface-labels-2026-07) label sets), fixes bugs in tools people use, and is well documented. Anything that eases an [open problem](https://scrollprize.org/2026_open_problems) qualifies. Idea lists: [help wanted](https://github.com/ScrollPrize/villa/issues?q=is%3Aissue%20state%3Aopen%20label%3A%22help%20wanted%22), [VC3D](https://github.com/ScrollPrize/villa/issues?q=is%3Aissue%20state%3Aopen%20label%3AVC3D), [good first issue](https://github.com/ScrollPrize/villa/issues?q=is%3Aissue%20state%3Aopen%20label%3A%22good%20first%20issue%22).

Formal requirements: address a specific challenge on scroll data with a demonstration; documentation and usage examples; standard formats (OME-Zarr or Zarr, tifxyz, triangular meshes).

## Terms that apply to everything

Awards are at the sole discretion of Scroll Prize, Inc. You must open-source a winning method under a permissive license to accept the prize (not at submission time). Winners provide payment information within 30 days. Teams: the leader submits and splits the money.
