# Letter reader prototype (8 October 2026)

The owner asked for a model that reads letters from ink maps without a person ("we should also have our model be able to read letters from the map, without needing a human"), wanted it "amazing and automated", and asked for the letter-reading work to be public. This note records the first CPU prototype and its numbers. The guide and the seven-stage plan are in [`docs/letter-reader.md`](../letter-reader.md); the machine-readable numbers are in [`docs/results.json`](../results.json) under `letter_reader_checks`.

Every number below is **Model output** on synthetic images or on public community drawings. None is reader output on hidden text, and none is a reading.

## What was built

- `kit/letterread.py`: numpy line reader. Normalise, estimate letter size from line pitch and then search six scales against the nulls, deskew, find lines, run a small convolutional network per line, decode with CTC (best path, or prefix beam search with a letter language model). Every result carries the nulls, the orientation check and the ink-only string. It also has CTC forced alignment and approximate line search for plan stage 4.
- `kit/greeklm.py`: Kneser-Ney letter 5-gram model for Greek capitals in scriptio continua.
- `scripts/letters/`: synthetic line and page generator, trainer (torch, CPU or CUDA), PHerc. 172 drawing check, whole-page check, and the Modal app for full-scale training (not run).

## Training run (CPU, this session)

| Setting | Value |
| --- | --- |
| Training data | 36,000 synthetic lines (seed 1, 36 shards, 758 s to generate on 4 vCPUs) |
| Validation data | 1,200 synthetic lines (seed 7) |
| Network | 593,849 parameters; channels 32, 64, 96, 128, 192; dilations 1, 2 |
| Optimiser | AdamW, one-cycle learning rate peaking at 0.002, batch 48, 4,000 steps |
| Wall time | 1,578 s (26 minutes) on 4 CPU threads |

The run used an earlier copy of `scripts/letters/train_linenet.py` with the same defaults. The committed version adds the GPU options and seeds each batch from (seed, epoch, bucket), so a rerun of the committed command gives a similar but not bit-identical model.

| Step | Synthetic validation character error rate | Letters per blank line (best path, no floor) |
| --- | --- | --- |
| 500 | 0.206 | 0.69 |
| 1000 | 0.207 | 0.50 |
| 1500 | 0.150 | 0.60 |
| 2000 | 0.140 | 0.79 |
| 2500 | 0.120 | 0.94 |
| 3000 | 0.119 | 0.62 |
| 3500 | 0.111 | 0.88 |
| 4000 | 0.112 | 0.90 |

"Letters per blank line" counts best-path letters on blank synthetic lines before any confidence floor. The reader does not use the raw best path: it keeps only letters above a floor set from the nulls, and on the twelve synthetic blank pages below it kept 0 to 10 letters, and the verdict called every one of them noise.

## Language model

Kneser-Ney 5-gram letter model (discount 0.75) built from two PerseusDL canonical-greekLit texts (CC BY-SA 4.0): Diogenes Laertius, *Lives* (tlg0004.tlg001) and Plato, *Republic* (tlg0059.tlg030). 937,054 training letters. Cross-entropy 2.556 bits per letter on 48,000 held-out letters of the same texts and 2.826 bits per letter on Xenophon, *Anabasis* (tlg0032.tlg006, 290,095 letters, not in the corpus); uniform guessing over 24 letters is 4.585. The model file is not committed. A prize pipeline would need CC BY texts instead (see the guide's licence note).

## Whole synthetic pages

`scripts/letters/eval_pages.py`, 18 pages per run, pages generated fresh (seeded), with no letter size or line positions given to the reader. Two thirds of pages look like ink-model maps and one third like hand-drawn label masks. Six blank pages per run (texture only, or texture with non-letter strokes) test false letters.

Weights: the final step 4000 model.

| Run | Ink-map look, character error | Label-mask look, character error | With language model (map, mask) | Lines found | Letter size used / true (median) | Letters kept on 6 blank pages |
| --- | --- | --- | --- | --- | --- | --- |
| Random letters (seed 11) | 0.158 on 672 letters | 0.013 on 306 | not used | 81 of 81 | 1.036 | 0, 0, 0, 0, 1, 1 |
| Real Greek text, Xenophon (seed 12) | 0.138 on 659 | 0.019 on 260 | 0.108, 0.008 | 76 of 77 | 0.981 | 0, 0, 10, 0, 0, 1 |

On every blank page the verdict said the letters were not above the nulls. The one blank page that kept 10 letters had 88 letters kept on its tile-shuffled null, so the verdict flagged it as noise; the raw count alone would not have. On Xenophon (a text the language model never saw) the language model cut the ink-map error from 0.138 to 0.108.

## Real letters: PHerc. 172 drawings

`scripts/letters/eval_p172.py` reads the hand-drawn PHerc. 172 ink labels of [Bodillium/Herculaneum-Scroll-Labels](https://github.com/Bodillium/Herculaneum-Scroll-Labels) (commit `2266661c`, CC BY-NC-SA 4.0) and compares the reader's lines with the labeller's own preliminary transcription, matching lines in order. These drawings are bold round-pen strokes, unlike anything in the synthetic training set, so this is an out-of-domain test. The reference is one person's reading, marked speculative by its author. Only aggregates are recorded here.

The segments are split by a fixed rule (sorted by id: first five dev, last five test), and the checkpoint is chosen on dev only. The rule was written after the all-segment numbers below were seen, so it is not preregistered; it was chosen because it does not depend on any result.

| Weights | Dev, ink only | Test, ink only | Test, with language model | All 10 segments, ink only | Letters kept / on tile-shuffle null / on phase null (all) |
| --- | --- | --- | --- | --- | --- |
| Step 500 (letter size from pitch only, before the scale search) | 0.745 on 161 | 1.113 on 80 | not run | 0.867 on 241 | 175 / 65 / 5 |
| Step 1000 | **0.740 on 169** | **0.760 on 100** | 0.670 on 94 | 0.747 on 269 | 216 / 33 / 5 |
| Step 4000 (final) | 0.886 on 167 | 1.102 on 98 | 0.947 on 94 | 0.966 on 265 | 293 / 81 / 32 |

Dev picks step 1000; its test error is 0.760 ink only and 0.670 with the language model. An error above 1 means the reader put in more letters than the reference has on the matched lines. Every segment's verdict had more confident letters than either null for steps 1000 and 4000, but the final model also keeps far more letters on the nulls.

## What this shows and does not show

- Interpretation: the network learns letter shapes from synthetic lines (validation error fell from 0.206 to 0.112), and on synthetic pages the whole chain works with no hints: median letter size within 4 percent of the truth, 157 of 158 lines found, near-zero letters on blank pages, and a verdict that catches the one noisy blank page.
- On real drawn letters it is far from usable, and longer synthetic training made it worse: from step 1000 to step 4000 the synthetic error fell from 0.207 to 0.112 while the drawing error rose from 0.747 to 0.966 and letters kept on nulls more than doubled. The model grows more confident on shapes it has never seen. So synthetic validation is not a safe guide for choosing a model; the trainer now keeps every checkpoint (`--keep`) and `eval_p172.py --split dev` chooses among them. The gap between synthetic and real letterforms, not the decoder, is the bottleneck, which is why the plan puts real letterforms (stage 3) and forced alignment on published text (stage 4) at the centre, and why the Modal run must choose its checkpoint on the dev half.
- Not shown: anything about reading an ink map of real scroll text. No public letter-level ground truth on ink maps exists yet; stage 4 builds it from PHerc. 1667's published text.
- Character error rate counts only lines matched to a reference line; letters in unmatched lines are reported separately in the JSON outputs.

## Found along the way (not acted on here)

The `ink_9um` label dataset README ([link](https://huggingface.co/buckets/scrollprize/datasets/tree/ink_9um), updated 14 August 2026, read 8 October 2026) lists annotation segment `pherc0139-w029` with source volume `20260126000000-w045_2026012619` at 2.399 um, pooled to about 9.6 um for training (Sourced fact). This repository calls w045 "held out from ink_9um". Its native 9.362 um render is not in the native training list, but the same surface and labels were trained on through the 2.4 um render (Interpretation). The owner has been told; the wording elsewhere is unchanged by this note.

## Next

1. Full-scale synthetic training on Modal ([spec](../compute/modal-specs/2026-10-08-letter-reader-training.md)); needs the owner's go-ahead and budget. Given the result above it is a cheap test of whether more fonts, a wider network and more data close the gap, with the checkpoint chosen on the dev half; it is not expected to close it alone.
2. Real letterforms (AL-PUB v2 on Kaggle, ICDAR 2023 on Zenodo), which Claude's cloud sessions cannot download. This is the larger lever (Interpretation).
3. Forced alignment on PHerc. 1667's published text and official labels.
