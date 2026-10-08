# Letter reader: automatic Greek letter hypotheses from ink maps

Started 8 October 2026 at the user's request ("we should also have our model be able to read letters from the map, without needing a human", and "for the letter reading project lets make it public"). This page is the guide and the plan. Results are in [the log](logs/2026-10-08-letter-reader.md) and `docs/results.json` under `letter_reader_checks`.

Everything the reader prints is **Model output**: letter hypotheses with positions and confidences, for a person to check. It is not a reading and not a transcription; papyrologists read and transcribe ([NOVELTY.md](NOVELTY.md)).

## What exists now

| Part | File | What it does |
| --- | --- | --- |
| Line reader | [`kit/letterread.py`](../kit/letterread.py) | numpy only. Normalises an image, estimates letter size, deskews, finds text lines, runs a small convolutional network on each line and decodes letters with CTC (best path, or prefix beam search with a language model). Returns letters with boxes and confidences, plus the controls below. `python -m kit letterread IMAGE --weights W` |
| Language model | [`kit/greeklm.py`](../kit/greeklm.py) | Kneser-Ney letter 5-grams for Greek in scriptio continua (24 capitals, lunate sigma), built from TEI texts. `python -m kit greeklm build OUT TEI...` |
| Synthetic data | [`scripts/letters/letterdata.py`](../scripts/letters/letterdata.py), [`gen_dataset.py`](../scripts/letters/gen_dataset.py) | Lines of uniform random Greek capitals in two glyph sources (a broad-nib bookhand skeleton written here, and installed fonts), degraded to look like an ink-model map or a hand-drawn ink label. Whole synthetic pages for end-to-end tests. |
| Training | [`scripts/letters/train_linenet.py`](../scripts/letters/train_linenet.py) | torch, CTC loss; exports BatchNorm-folded numpy weights (format `linenet-v1`). CPU or CUDA. |
| Real-letter check | [`scripts/letters/eval_p172.py`](../scripts/letters/eval_p172.py) | Reads the hand-drawn PHerc. 172 ink labels from [Bodillium/Herculaneum-Scroll-Labels](https://github.com/Bodillium/Herculaneum-Scroll-Labels) (CC BY-NC-SA 4.0) and scores the letters against the labeller's own preliminary transcription. Nothing from that repository is copied here. |
| Full-scale training | [`scripts/letters/modal_letters.py`](../scripts/letters/modal_letters.py) | Modal app: data generation on CPU containers, training on one GPU. Not run; see the [run spec](compute/modal-specs/2026-10-08-letter-reader-training.md). |

Weights, language models, synthetic data and evaluation outputs stay out of git (rule 6). Build them with the commands below; each takes minutes on a laptop CPU except the full-scale training.

## Why it is built this way

- **Reading a line, not classifying letters one by one.** In scriptio continua there are no word gaps and letter boundaries on an ink map are unclear, so segmenting letters first is the hard part. A line recogniser trained with CTC (connectionist temporal classification) needs only the letter string of each line, not letter boxes, and learns where letters are by itself. Published Greek papyrus work classifies letters well on photographs (about 93% on single-letter crops, Swindall et al. 2021, eScience; [link](https://scholars.uky.edu/en/publications/exploring-learning-approaches-for-ancient-greek-character-recogni/)), but the best detector-classifier on whole papyrus photographs reached mAP 42% ([Turnbull and Mannix 2024](https://arxiv.org/abs/2401.12513)). Sourced facts; the comparison is Interpretation.
- **Synthetic first, because no letter-level labels on Herculaneum ink maps are public** (as of 8 October 2026; searched by this session, Interpretation). Published transcriptions are line-level Leiden text without coordinates.
- **Random letters, separate language model.** The network trains on uniform random letter strings, so it learns shapes and cannot learn Greek. Greek enters only through `kit/greeklm.py`, which is switchable, and the ink-only decode is always printed beside any language-model decode. When the two disagree, the ink-only line is what the image supports. This matters because the organisers' own statement is that their ink models use no OCR or language model so that letters in the images are trustworthy ([grand prize page](https://scrollprize.org/grandprize), Sourced fact).
- **Small receptive field.** Each output frame sees 58 px of its line at a letter height of 16 px, about three letters (dilations 1 and 2; 90 px, about five letters, with dilations 1, 2 and 4). A reader that sees a whole column can invent plausible text; this one cannot carry a word across the line.
- **numpy inference.** The kit stays light (no torch at inference), and the numpy forward pass is tested against torch with non-trivial BatchNorm statistics.

## Controls that travel with every result

Each can fail, and the result says when it does (rule 4).

1. **Nulls.** The same reader on tile-shuffled copies (letter-sized tiles, random flips: keeps local texture and grey levels, breaks letters and lines) and phase-randomised copies (keeps the power spectrum and so the line spacing, breaks shapes). The confidence floor is set from the nulls (at most 5% of a line's letter slots on nulls, never below 0.5), and the verdict compares letters kept on the image with letters kept on each null.
2. **Orientation.** Letters as stored, mirrored and turned 180 degrees. Text the right way round should keep the most letters. This is weak for Greek capitals, many of which are symmetric, so it is evidence, not a gate.
3. **Language off.** The `ink_only` string never uses the language model. A large gap between ink-only and language-model error is a warning that the language model, not the ink, is doing the work.
4. **For ink maps:** read the reverse-depth map of the same surface as well (the repository's standard AUC control). Letters that survive depth reversal are not ink.

## Commands

```bash
# 1. synthetic data (CPU; about 13 minutes for 36,000 lines on 4 cores)
python scripts/letters/gen_dataset.py work/letters/data/train --n 36000 --seed 1
python scripts/letters/gen_dataset.py work/letters/data/val --n 1200 --seed 7

# 2. train (CPU prototype: about 30 minutes on 4 cores; full scale goes to Modal)
python scripts/letters/train_linenet.py work/letters/data/train work/letters/model --val work/letters/data/val --steps 4000 --keep

# 3. language model from PerseusDL canonical-greekLit TEI files (keep Philodemus out)
python -m kit greeklm build work/letters/greek5.npz tlg0004.tlg001.perseus-grc2.xml tlg0059.tlg030.perseus-grc2.xml

# 4. read an image (ink bright by default; --polarity dark for photographs)
python -m kit letterread MAP.tif --weights work/letters/model/linenet.npz [--lm work/letters/greek5.npz] [--json]

# 5. real-letter check on PHerc. 172 drawings (needs Pillow and pdftotext): choose a checkpoint on dev, report test
git clone --depth 1 https://github.com/Bodillium/Herculaneum-Scroll-Labels work/bodillium
for w in work/letters/model/ckpt/*.npz; do python scripts/letters/eval_p172.py work/bodillium --weights $w --split dev | tail -1; done
python scripts/letters/eval_p172.py work/bodillium --weights BEST.npz --split test --lm work/letters/greek5.npz
```

## Plan: from prototype to an automatic reader people can rely on

Each stage has a gate that can fail. A stage that fails its gate is reported as a null, not tuned until it passes.

1. **Prototype (this change).** Synthetic-trained line reader, numpy inference, controls, language model, the PHerc. 172 drawing check. Gate: synthetic character error rate well under the old template reader's (about 0.43, Scrolls-private, Model output) with nulls clean; a first number on real drawn letters. Result: synthetic 0.112, real drawings 0.760 on the test half (Model output, [log](logs/2026-10-08-letter-reader.md)). Synthetic error kept falling while real-letter error rose after step 1,000, so checkpoints are chosen on the dev half of the drawings, never on synthetic validation.
2. **Scale the synthetic training (Modal, [spec](compute/modal-specs/2026-10-08-letter-reader-training.md)).** About 600,000 lines, a wider network, three dilations, more Greek fonts. Gate: lower character error on the PHerc. 172 drawings than the CPU prototype, at no more letters on nulls.
3. **Real letterforms from photographs.** AL-PUB v2 (about 205,800 single-letter crops from Oxyrhynchus papyri, Apache 2.0 on [Kaggle](https://www.kaggle.com/datasets/miswindall/al-pub-v2)) and the ICDAR 2023 Greek letters set (letter boxes on Iliad papyri, CC BY-NC 4.0, [Zenodo](https://zenodo.org/records/13825619)) give real Greek bookhand letters. Compose random lines from real crops, push them through the same map and mask degradations, and mix them with the synthetic lines. Both hosts are blocked from Claude's cloud sessions and need the owner's computer or Modal (Kaggle needs an API token). Gate: lower error on the PHerc. 172 drawings, which none of this data contains.
4. **Real ink-map letters by forced alignment, on published text only.** PHerc. 1667 has a published column-by-column Greek text of columns 1 to 22, with parts of the first three columns left untranscribed ([arXiv:2606.29085](https://arxiv.org/abs/2606.29085), Methods, Sourced fact) and six segments in the open-data bucket with official ink labels and 2.4 um ink maps on the same pixel grid (checked in the bucket listing on 8 October 2026). Read each label mask, find its lines in the published text by approximate string search, then force-align the matched text to the mask with the CTC network: every letter gets a box with no hand drawing. The same boxes cut the 2.4 um ink map, giving real map crops with letter identities. Fine-tune on some segments, test on the others, and read the reverse-depth map as the control. These six segments (w013, w018, w023, w028, w029, w031) are exactly the PHerc. 1667 segments in `ink_9um`'s training labels ([ink_9um dataset README](https://huggingface.co/buckets/scrollprize/datasets/tree/ink_9um), Sourced fact, read 8 October 2026), so ink models have likely seen their text and their maps may look cleaner than maps of unseen text (Interpretation); that is acceptable for letter training data but rules them out as the test of stage 5. The 2024 PHerc. 172 segments that Bodillium's labels belong to are not in the open-data bucket (checked 8 October 2026); they would come from dl.ash2txt.org through the owner's computer or Modal.
5. **Held-out scroll test.** Train on one scroll's aligned letters, test on another's (for example PHerc. 172 against fragments with infrared photographs, which have public pixel labels). Report precision of confident letters against a papyrologist's transcription, letters per square centimetre on nulls and on reverse-depth maps, and the ink-only against language-model gap.
6. **Self-training with guards.** Pseudo-label unlabelled public maps only where ink-only letters are confident, above the nulls and stable across two ink models; retrain; repeat only while the held-out scroll error falls. Stop at the first round that does not improve it. This is where hallucination can creep in, so every round is scored on held-out real letters and on nulls.
7. **Use.** A triage and review aid: rank regions of a segment by confident letters above the nulls (a complement to `kit rowscore`), and give reviewers letter boxes as a separate layer. Never draw letters onto a prize image, and never present a machine string as a reading.

## Limits and rules

- **Prize terms.** Prize images must be generated programmatically and must not contain manual annotations of characters ([prizes](https://scrollprize.org/prizes), Sourced fact, read 8 October 2026). Whether machine letter overlays are acceptable is not stated, so keep them out of submission images. The Grand Prize counts characters "identified on a letter-by-letter basis without papyrological interpolation" by papyrologists (same page); a machine string does not count as identification.
- **Disclosure.** Running the reader on a target scroll's map produces a possible finding. Those outputs stay in Scrolls-private or ignored local folders (rule 1). The data agreement for Scrolls 1 to 4 and Fragments 1 to 6 says "I will not make public (outside of Discord) any revelation of hidden text (or associated code) without the written approval of Vesuvius Challenge" ([villa accept_terms.py](https://raw.githubusercontent.com/ScrollPrize/villa/main/vesuvius/src/vesuvius/install/accept_terms.py), Sourced fact). This repository publishes the general tool and its numbers on synthetic data and on public community labels, not reader output on hidden text (Interpretation of how the rule applies).
- **Label masks are text too.** Reading the official ink-label masks of a scroll whose text is not published (for example PHerc0139 or PHerc0841) produces letter strings of unpublished text. Treat those outputs like reader output on a map: private, never in this repository.
- **Training data licences.** The 2027 Grand Prize requires every dataset used to train a model in the pipeline to be published under CC BY-NC 4.0 ([prizes](https://scrollprize.org/prizes), Sourced fact). The Perseus and First1KGreek texts are CC BY-SA 4.0, whose ShareAlike term does not allow that relicence (Interpretation), so a prize pipeline would build its letter model from CC BY texts such as the papyri.info DDbDP and DCLP data ([papyri/idp.data](https://github.com/papyri/idp.data), CC BY 3.0). AL-PUB v2 (Apache 2.0) and ICDAR 2023 (CC BY-NC 4.0) look compatible (Interpretation).
- **PHerc. 172 labels** are a community labeller's drawings of what they read, and the transcription is marked speculative and not peer reviewed by its author. A score against them measures agreement with one person's reading.
- **PHerc. Paris 4** data carries a publication reservation until 25 June 2027 ([data browser](https://scrollprize.org/data_browser/PHercParis4), Sourced fact); any letter dataset built from it needs that respected.
