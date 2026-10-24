# Open prizes

**Snapshot checked 2026-10-11** from the [scrollprize.org/prizes](https://scrollprize.org/prizes) page body (not the homepage banner) and its source [`34_prizes.md`](https://github.com/ScrollPrize/villa/blob/34d4b260dd2a281d635227a71ab8bfb5eb45c4cd/scrollprize.org/docs/34_prizes.md) and [`prizeEligibility.json`](https://github.com/ScrollPrize/villa/blob/34d4b260dd2a281d635227a71ab8bfb5eb45c4cd/scrollprize.org/src/data/prizeEligibility.json) at villa commit `34d4b260dd2a` ([#2037](https://github.com/ScrollPrize/villa/pull/2037)). Machine-readable copy: [`../kit/data/prizes-2026-10-11.json`](../kit/data/prizes-2026-10-11.json). The 6 October 2026 snapshot is kept at [`../kit/data/prizes-2026-10-06.json`](../kit/data/prizes-2026-10-06.json): a maximum of 10 First Letters scrolls ($500,000) and 22 eligible volumes, including PHerc0343. The live page wins on any disagreement. Eligible lists change: PHerc. 1447 left First Letters on 24 Sep 2026 when the team found text in it ([villa #1887](https://github.com/ScrollPrize/villa/pull/1887)). PHerc0343 left after its First Letters prize was awarded on 8 Oct 2026.

Label: **Sourced fact** (see [`NOVELTY.md`](NOVELTY.md)).

## Summary

| Prize | Money | Deadline (11:59pm Pacific) | Submit |
| --- | --- | --- | --- |
| 2027 Grand Prize | $1,000,000: 1st $800k, 2nd $100k, 3rd $50k, 4th $50k | 25 Jun 2027 | grandprize@scrollprize.org |
| First Letters | $50,000 per scroll, maximum of 9 more scrolls ($450,000 remaining; one prize already used) | 25 Jun 2027 | [form](https://forms.gle/TM5ao8GwC2mDrdLk9) |
| PHerc. Paris 4 title | $50,000 | 25 Jun 2027 | [form](https://forms.gle/4zeVPPBtNdSCAQa88) |
| Progress Prizes | $20,000 best of month guaranteed; others $20k, $10k, $5k, $2,500, $1,000, $500, $250; about $590k per year | monthly, several entries a month allowed; next 31 Oct 2026 | [form](https://docs.google.com/forms/d/e/1FAIpQLSc4flEfgK2nyjoczz2_U_XrIGMlgrnSknWatLqrFPnbtKfZwg/viewform) |

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

10 legible letters within one 4 cm² area of an eligible scroll. 21 eligible volumes remain. The page says prizes will be awarded for a maximum of 9 more scrolls, up to $450,000. One prize was already used.

On 8 October 2026 the $50,000 First Letters prize for PHerc 343 was awarded to Erwin Nieuwlaar ([official post](https://scrollprize.substack.com/p/50k-first-letters-prize-awarded-for), [@scrollprize](https://x.com/scrollprize/status/2108285044133663084)). That is why PHerc0343 is no longer eligible. The 6 October snapshot listed 22 volumes and a maximum of 10 scrolls ($500,000), and it included PHerc0343 (volume 20250521140437, 8.64 µm).

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

Voxel sizes come from the volume names in `s3://vesuvius-challenge-open-data/<scroll>/volumes/`, listed on 2026-10-06 and carried forward for volume ids the 11 Oct page still lists.

A submission contains: the tifxyz mesh(es) with flattening; one programmatically generated image with no manual annotation of characters, a 1 cm scale bar and letter sizes in pixels and mm; rows annotated without covering the letters (a baseline or box), ideally over a fiber-visible render; methodology and a way to reproduce it; false-positive mitigation (large model windows can invent letterforms; show it is not hallucinated, for example on a held-out region); held-out validation on public ground truth. No public disclosure before the announcement.

Organizers' notes: existing ink models may or may not work on these scrolls; sometimes ink is visible directly in the render with no model; a little visible ink is a foothold for fine-tuning and iterative labeling. Their step-by-step guide: ["From CT Scan to Ancient Text: A First Letters Prize Workflow"](https://scrollprize.substack.com/p/from-ct-scan-to-ancient-text-a-first).

## PHerc. Paris 4 title

$50,000 for an image of the title of Scroll 1 that the papyrologists can read, from any of its scans including the 2.4 µm volumes. Substantial Epicurean prose has been read from this scroll, but its author and title are unknown. The expected title region has shown no ink so far; the top rows are physically missing, and the ink may differ. Submissions stay open until won.

## Progress Prizes

Open-ended monthly awards for open-source contributions. The organizers favor work that is released early, actually used, measured on real data (their public [ink](https://scrollprize.org/data_datasets#ink-labels-2026-07) and [surface](https://scrollprize.org/data_datasets#surface-labels-2026-07) label sets), fixes bugs in tools people use, and is well documented. Anything that eases an [open problem](https://scrollprize.org/2026_open_problems) qualifies. Idea lists: [help wanted](https://github.com/ScrollPrize/villa/issues?q=is%3Aissue%20state%3Aopen%20label%3A%22help%20wanted%22), [VC3D](https://github.com/ScrollPrize/villa/issues?q=is%3Aissue%20state%3Aopen%20label%3AVC3D), [good first issue](https://github.com/ScrollPrize/villa/issues?q=is%3Aissue%20state%3Aopen%20label%3A%22good%20first%20issue%22).

**Several entries a month are allowed.** The prize page says: "Submissions are evaluated monthly, and multiple submissions/awards per month are permitted" ([prizes](https://scrollprize.org/prizes#progress-prizes), read 2026-10-13; Sourced fact). Separate contributions can each be entered in the same month, and one entrant can win more than one award.

Formal requirements: address a specific challenge on scroll data with a demonstration; documentation and usage examples; standard formats (OME-Zarr or Zarr, tifxyz, triangular meshes).

## Terms that apply to everything

Awards are at the sole discretion of Scroll Prize, Inc. You must open-source a winning method under a permissive license to accept the prize (not at submission time). Winners provide payment information within 30 days. Teams: the leader submits and splits the money.

## Questions people ask, answered in the page's words

Read **24 October 2026** from [scrollprize.org/prizes](https://scrollprize.org/prizes). Each answer is a short quote from that page, with the section it is under. Where the page does not answer, the row says "Not stated; ask the organizers" (on the [Discord](https://discord.gg/V4fJhvtaQn) or by email). Label: **Sourced fact** for the quotes; the few notes marked *Note* are **Interpretation**. This section does not change the summary snapshot above, which the daily prize routine checks.

| Question | The page says | Section |
| --- | --- | --- |
| How is legibility judged? | "Verify that at least 70% of each counted column's preserved characters are legible. Legible characters only count as legible when identified on a letter-by-letter basis without papyrological interpolation." and "Each submitted column is distributed to one or more papyrologists, who independently attribute a legibility score to it; a column counts toward the legibility thresholds above only once it is scored as legible." | 2027 Grand Prize |
| What counts toward the human hours? | "The unrolling pipeline should be fully automated; up to 8 documented hours of human annotation / input are tolerated." and "Unlimited time, compute, and manual effort may be spent creating generic ML datasets to train ML models." Which tasks count as annotation or input beyond that: Not stated; ask the organizers. | 2027 Grand Prize |
| Does a mesh need a flattening, and how flat? | "Each tifxyz must already include a low-distortion isometric 2D parametrization (flattening)." (Grand Prize); "already including a low-distortion isometric 2D parametrization (flattening)" (First Letters, Title). A numeric distortion limit: Not stated; ask the organizers. *Note:* `kit tifxyz stretch` reports distortion percentiles, which are a way to show it, not an official test. | All three milestone prizes |
| How many meshes, and how named? | "At most one mesh per full column of text (plus its margins) will be accepted; smaller meshes are not considered valid unless they localize regions where the papyrus is broken, or detached patches. Name each mesh with a sequential column number (e.g. column_01.tifxyz, column_02.tifxyz, ...) following the order of the windings" | 2027 Grand Prize |
| How are images named? | "Name each image after the tifxyz mesh (from the same package) used to generate it" | All three milestone prizes |
| Can the image carry annotations? | "Images must be generated programmatically from the reconstructed CT scan volume and the mesh(es) submitted in the same package, and should not contain manual annotations of characters or text. This includes annotations that were then used as training data and memorized by a machine learning ink model." Rows may be marked: "drawing a horizontal baseline through each row or a rectangle around it, rather than overwriting the letters themselves." | First Letters |
| What sizes must be shown? | "Include a scale bar showing the size of 1 cm on the submission image, and the pixel and millimeter dimensions of a few representative letters." The shape of the 4 cm² area (square or any outline): Not stated; ask the organizers. | First Letters, Title |
| Does text without clear rows fail? | "Misaligned text or text without clear rows does not immediately disqualify a submission, but it does make it less likely that you found valid text." | First Letters |
| Can I train where I predict? | "No overlap between training and prediction regions." (Grand Prize); "Do not include overlap between training and prediction regions" (First Letters, Title) | All three milestone prizes |
| Can I use other people's segments, models or data? | "You may use any information or resource that is publicly available (published scholarship, other scrolls' data, segments, or models, third-party pretrained models, etc.), provided that use is permitted by that resource's own license or terms. Data derived from higher resolution scans of the submitted scroll volume cannot be used." The First Letters and Title sections do not repeat this: Not stated for them; ask the organizers. | 2027 Grand Prize |
| Under what license must datasets go out? | "Any dataset created or used to train ML models must be published publicly, under a CC-BY-NC 4.0 license." | 2027 Grand Prize |
| Must my code be open when I submit? | "It does not have to be open source at the time of submission, but you have to make it open source under a permissive license to accept the prize." | Terms and Conditions |
| Can I post my result before it is judged? | "Do not make your discovery public until winning the prize is officially announced." and, for First Letters, "As with the Grand Prize, you must not make your discovery public until the prize is officially announced." | Grand Prize, First Letters, Title |
| Must I be on the Discord? | "To qualify, you must have registered on the Vesuvius Challenge Discord at the time of the submission." The First Letters and Title sections do not repeat it: Not stated for them; ask the organizers. | 2027 Grand Prize |
| Two teams qualify: who wins? | "In case there are multiple teams that submit qualifying results, the team that submitted first will win (independent of how long our assessment takes)." | 2027 Grand Prize |
| How long until I hear back? | "We will acknowledge having received your submission within a week." | 2027 Grand Prize |
| One Progress Prize form or many? | "If you make multiple small contributions in a month, for example several bugfix PRs on our villa monorepo, please bundle them into a single submission. More substantial contributions (new methods, models or datasets) should each be submitted separately, unless they are closely coupled." | Progress Prizes |
| When is the next Progress Prize deadline? | "The next deadline is 11:59pm Pacific, October 31st, 2026!" | Progress Prizes |
| What gets favored for a Progress Prize? | "Are released or open-sourced early." "Actually get used." "Improve results quantitatively and/or qualitatively on real data." "Are well documented." (four of the page's six points) | Progress Prizes |

`python -m kit submitcheck FOLDER` ([page](tools/submitcheck.md)) checks a folder against the file-level lines above (mesh format and naming, flattening present, image names, the 1 cm scale bar note) and quotes each line it applies.
