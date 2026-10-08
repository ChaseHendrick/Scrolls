# d9v2 fine-tune sweep on public human labels (2026-10-08)

A public-data benchmark: can a short fine-tune of the community d9v2 reader on human ink labels beat the released readers on PHerc0841, a scroll none of them trained on? Four variants were trained and every checkpoint was scored. None beats Reader v2, the better of the two released readers scored on these crops; the best edges d9v2 by 0.0004, within noise. Labels follow [`../NOVELTY.md`](../NOVELTY.md): numbers are **Model output**; readings of the trend are **Interpretation**.

## Setup

- **Start point:** d9v2 (`d9v2_ft-012000.pth`, TAUIL v1.0, sha256 `50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966`), itself a fine-tune of `ink_9um`.
- **Training data:** the 20260918 human ink labels and supervision masks of nine public 9.362 um, 113 keV surface volumes: PHerc0139 w030, w035, w039, w040, w041, w043 and w044, PHerc0814 (segment 46527) and PHerc0500P2. PHerc0841 and w045 were excluded; the training scripts refuse PHerc0841.
- **Training:** villa flat preprocessing, 1500 steps, batch 16, bf16, depth jitter 5, checkpoints every 250 steps, one seed. Four arms:

| Arm | Anchor to frozen d9v2 | Learning rate |
| --- | --- | --- |
| A | 1.0 | 2e-5 |
| B | 0.3 | 2e-5 |
| C | 1.0 | 5e-6 |
| D | 0 | 5e-6 |

- **Scoring:** pixel AUC (`kit auc`) on the 640 px selection crops of PHerc0841 w00 and ag896, 64 px edge left out, against their 20260918 labels inside the supervision mask, with the reverse-depth map as control; villa inference at PR #1865 (6723ad158), overlap 0.5, hann. ag405 was not scored. It already has exploratory use in this repository ([`../results.json`](../results.json) holds d9v2 0.8319 there), so a later ag405 score could only be compared with that number, not serve as an untouched audit.
- **Comparison:** on these crops d9v2 scores w00 0.8994 and ag896 0.8230 (mean 0.8612; [`../results.json`](../results.json)), and Reader v2 (`reader-v2-step040000`) w00 0.9269 and ag896 0.7972, mean 0.8620 (CPU, villa PR #1865, measured in the same development work; not yet in results.json). The selection rule was fixed in the run specification before training: a variant needs a mean of at least 0.8820 (the better of d9v2 and Reader v2 plus 0.02), with reverse well below forward.

## Results

All 24 checkpoints (forward AUC, reverse in brackets):

| Checkpoint | w00 | ag896 | Mean |
| --- | --- | --- | --- |
| A-250 | 0.8842 (0.5404) | 0.8251 (0.5428) | 0.8546 |
| A-500 | 0.8845 (0.5238) | 0.8303 (0.5334) | 0.8574 |
| A-750 | 0.8829 (0.5207) | 0.8381 (0.5329) | 0.8605 |
| A-1000 | 0.8816 (0.5299) | 0.8392 (0.5312) | 0.8604 |
| A-1250 | 0.8835 (0.5429) | 0.8392 (0.5270) | 0.8613 |
| A-1500 | 0.8838 (0.5458) | 0.8394 (0.5236) | 0.8616 |
| B-250 | 0.8719 (0.5224) | 0.8229 (0.5490) | 0.8474 |
| B-500 | 0.8640 (0.5046) | 0.8245 (0.5465) | 0.8442 |
| B-750 | 0.8605 (0.5029) | 0.8310 (0.5443) | 0.8458 |
| B-1000 | 0.8597 (0.5129) | 0.8308 (0.5404) | 0.8453 |
| B-1250 | 0.8612 (0.5270) | 0.8306 (0.5336) | 0.8459 |
| B-1500 | 0.8627 (0.5294) | 0.8307 (0.5288) | 0.8467 |
| C-250 | 0.8786 (0.5572) | 0.8240 (0.5381) | 0.8513 |
| C-500 | 0.8711 (0.5312) | 0.8227 (0.5445) | 0.8469 |
| C-750 | 0.8699 (0.5208) | 0.8238 (0.5411) | 0.8468 |
| C-1000 | 0.8678 (0.5168) | 0.8250 (0.5368) | 0.8464 |
| C-1250 | 0.8681 (0.5212) | 0.8256 (0.5374) | 0.8468 |
| C-1500 | 0.8684 (0.5215) | 0.8260 (0.5367) | 0.8472 |
| D-250 | 0.8703 (0.5462) | 0.8239 (0.5401) | 0.8471 |
| D-500 | 0.8538 (0.5103) | 0.8182 (0.5505) | 0.8360 |
| D-750 | 0.8437 (0.4980) | 0.8150 (0.5512) | 0.8294 |
| D-1000 | 0.8345 (0.4939) | 0.8126 (0.5489) | 0.8236 |
| D-1250 | 0.8321 (0.4986) | 0.8120 (0.5501) | 0.8220 |
| D-1500 | 0.8320 (0.4987) | 0.8117 (0.5495) | 0.8218 |

Best per arm: A 0.8616 (step 1500), B 0.8474 (step 250), C 0.8513 (step 250), D 0.8471 (step 250). Forward is above reverse on every line; reverse stays between 0.49 and 0.56. Two earlier CPU runs of the same recipe were also scored and count as tried variants: lr 2e-5, batch 8, jitter 2, no anchor (step 250 mean 0.8431, step 500 0.8314) and lr 2e-5, batch 8, jitter 5, anchor 1.0 (step 250 0.8552, step 500 0.8521). That makes 28 checkpoints in all.

## Depth windows of the best checkpoint

A-1500 was then scored at five depth windows (`--layer-start/--layer-end`) on the same two crops, on an L4. The default reproduced the B200 score:

| Window | w00 | ag896 | Mean |
| --- | --- | --- | --- |
| default | 0.8838 (0.5458) | 0.8394 (0.5235) | 0.8616 |
| z0-20 | 0.7753 (0.6184) | 0.8184 (0.4581) | 0.7969 |
| z3-23 | 0.8764 (0.5706) | 0.8411 (0.5225) | 0.8587 |
| z5-25 | 0.8863 (0.5647) | 0.8461 (0.5682) | 0.8662 |
| z8-27 | 0.9046 (0.5909) | 0.8286 (0.5972) | 0.8666 |

Deeper windows help, as they do for the released readers, but the best (z8-27, 0.8666) stays below 0.8820 and below d9v2 at the same window (w00 0.9280, ag896 0.8243, mean 0.8761, measured in the same development work). Windows chosen on these crops are optimistic. With these five, 33 variants were scored in all (24 sweep checkpoints, 4 CPU checkpoints, 5 windows).

## Reading

- No checkpoint or window reaches 0.8820, and no checkpoint passes Reader v2's 0.8620 at the default depth window. The best, A-1500 at 0.8616, sits between d9v2 (0.8612) and Reader v2; nothing was promoted.
- **Interpretation:** only arm A (anchor 1.0, lr 2e-5) held its mean, gaining on ag896 (0.8230 to 0.8394) and losing on w00 (0.8994 to 0.8838); single-segment changes of this size are within the sampling noise of about 0.02 or more estimated in section 5 of [the overlap log](2026-10-07-overlap-and-baseline.md), and no paired interval was computed. Arms B (anchor 0.3) and C (anchor 1.0 at the lower learning rate) lost about 0.01 to 0.015, and unanchored D fell steadily to 0.8218. At each learning rate the stronger anchor scored higher (A over B, C over D), but full anchoring alone did not keep C near d9v2. Fine-tuning on these human labels tends to move the model away from what works on PHerc0841, mostly on w00.
- **Limits:** one seed; two crops that trace the same sheet, so their mean is not two independent selection surfaces ([plan](../plans/2026-10-07-training.md)); 640 px windows only.

## Compute

Modal: setup and the pipeline check on one L4 (the d9v2 numbers above reproduced to four decimals), the sweep on B200s. On a B200 an arm took about 300 s (about 0.2 s per step, with the GPU about a quarter busy, so data bound) and scoring one checkpoint on both crops, forward and reverse, about 85 s. The training and scoring scripts are kept in Scrolls-private; no weights or maps are in either repository.
