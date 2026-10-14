# Greek letter reader

A small learned reader that proposes Greek capital letters, with positions and confidences, on 2D images of scroll text: ink-detection maps, drawn ink labels and photographs of papyri. It reads whole lines with a convolutional network trained with CTC, runs in numpy (no GPU or torch needed to read), and reports controls with every result, so you can tell letters from noise.

Everything it prints is **Model output**: letter hypotheses for a person to check. It is not a reading or a transcription; papyrologists read and transcribe ([NOVELTY.md](NOVELTY.md)).

- Code: [`kit/letterread.py`](../kit/letterread.py) (reader), [`kit/greeklm.py`](../kit/greeklm.py) (optional letter language model), [`scripts/letters/`](../scripts/letters/) (training data, training, benchmarks, demo).
- Measured accuracy: [How well it reads](#how-well-it-reads) below, with the full record in [`logs/2026-10-14-letter-reader.md`](logs/2026-10-14-letter-reader.md) and the numbers in [`results.json`](results.json) under `letter_reader_checks`.
- Weights: [Model card](#model-card-letters-v2-real). Weights are not in git.

## Quick start

You need Python 3.10 or newer and numpy; Pillow reads PNG and JPEG and draws overlays; tifffile reads TIFF maps.

```bash
git clone https://github.com/ChaseHendrick/Scrolls && cd Scrolls
python -m pip install numpy pillow tifffile

# 1. Try it on a public PHerc. 1667 ink map (downloads a 3.5 MB image and the weights once)
python scripts/letters/demo_p1667.py --segment w013 --out work/letters/demo
#    -> work/letters/demo/w013.json, w013-overlay.png and a text summary on screen

# 2. Read your own image (ink bright, as in ink-detection maps; --polarity dark for photographs)
python -m kit letterread MAP.png --weights letters-v2-real --letter-px 86 --overlay MAP-letters.png
python -m kit letterread MAP.tif --weights letters-v2-real --json --out MAP-letters.json
```

`--weights letters-v2-real` names a released model in [`kit/data/letter-weights.json`](../kit/data/letter-weights.json): the reader downloads it once into `~/.cache/scrolls-kit/letters/` (or `$KIT_LETTER_WEIGHTS`) and refuses a file whose SHA-256 differs. A path to any `linenet-v1` `.npz` works too.

### Letter size matters most

The network reads letters about 16 pixels tall; the reader rescales your image to that. Give the letter height in image pixels with `--letter-px` when you know it (PHerc. 1667's letters, about 3.3 mm tall, are about 86 pixels tall on its 2.4 um maps averaged 16 by 16 to about 38 um per pixel). Without it, the reader estimates the size from the line spacing and searches six scales against its own nulls; that search is the weakest step on maps it has not seen (see the limits below). Other options:

| Option | Use |
| --- | --- |
| `--crop Y0 Y1 X0 X1` | Read part of a large image |
| `--lines Y [Y ...]` | Line centre rows, when you know them (one column) |
| `--columns auto` (default), `off` or a number | Split at empty vertical gutters, read the whole width, or ask for that many columns |
| `--lm greek5.npz` | Add a language-model decode beside the ink-only one (below) |
| `--nulls N` | Number of null copies for the control (default 4) |
| `--no-orientation` | Skip the mirrored and rotated reads (faster) |
| `--overlay OUT.png` | The image with kept letters boxed and labelled (green p >= 0.8, yellow below), lower-confidence boxes grey |

From Python:

```python
from kit import letterread as R
img = R.load_image("MAP.png")                     # .npy, .npz, .tif or .png/.jpg; 2D float array
res = R.read(img, R.resolve_weights("letters-v2-real"), letter_px=86)
print(R.text_summary(res))
for line in res["lines"]:
    print(line["column"], line["y"], line["ink_only"])   # '·' marks a letter slot under the confidence floor
    for l in line["letters"]:
        l["glyph"], l["p"], l["kept"], l["box"]           # box is [y0, y1, x0, x1] in input pixels
R.overlay(img, res, "MAP-letters.png")
```

### Optional language model

The network was trained on random letter strings, so it knows letter shapes and no Greek. A Kneser-Ney letter 5-gram model can be added as a second decode, always shown beside the ink-only string and never replacing it:

```bash
git clone --depth 1 https://github.com/PerseusDL/canonical-greekLit work/perseus     # CC BY-SA 4.0
python -m kit greeklm build work/letters/greek5.npz \
    work/perseus/data/tlg0004/tlg001/tlg0004.tlg001.perseus-grc2.xml \
    work/perseus/data/tlg0059/tlg030/tlg0059.tlg030.perseus-grc2.xml
python -m kit letterread MAP.png --weights letters-v2-real --letter-px 86 --lm work/letters/greek5.npz
```

When the two decodes disagree, the ink-only line is what the image supports. A large gap between them means the language model, not the ink, is doing the work.

## What the result means

`read()` returns, and `--json` prints, one record per found line: its column, centre row `y`, the `ink_only` string, and each letter's glyph, probability `p`, whether it cleared the confidence floor (`kept`) and its box. Three controls travel with every result, and each can fail:

1. **Nulls.** The same reader on tile-shuffled copies (letter-sized tiles with random flips: local texture and grey levels kept, letters and lines broken) and phase-randomised copies (same power spectrum, so the same line spacing, shapes broken). The confidence floor is set so the nulls keep few letters (at most 5% of a line's letter slots, never below p = 0.5), and `control.verdict` compares letters kept on the image with letters kept on each null: "well above every null" (more than three times), "above, but within a factor of three", or "NOT above the nulls: treat every letter here as noise".
2. **Orientation.** Letters kept as stored, mirrored and turned 180 degrees. Text the right way round should keep the most. This is weak for Greek capitals, many of which are symmetric, so it is evidence, not a gate.
3. **Language off.** `ink_only` never uses the language model.

For ink maps, also read the reverse-depth map of the same surface: letters that survive depth reversal are not ink.

## How well it reads

All numbers are Model output on public data, measured on CPU. Character error is edit distance over reference letters; 0.10 means about one edit per ten letters. "Free ends" does not charge letters read before or after the reference, because a map window also shows unlabelled neighbours. Each PHerc. 1667 test's rule was fixed in writing on 9 October 2026 before the readers it compares were run on it; the PHerc. 172 row is a diagnostic, because its column rule was set after that test half had been seen (conditions in the [log](logs/2026-10-14-letter-reader.md)). "Synthetic-only" is letters-v1: the same network, data size and training, with no real letters in its training lines.

| Test (letters-v2-real, step 30000) | Reference | Letters | Character error | Comparison |
| --- | --- | --- | --- | --- |
| PHerc. 1667 official ink labels (drawings), line given | 3 blind machine transcriptions, unanimous groups only | 122 | **0.025** ink only | synthetic-only reader 0.320, prototype 0.402 |
| Same 87 groups read from the 2.4 um ink maps, line given | same | 122 | **0.369** free ends | synthetic-only 0.705 |
| Maps, windows about three lines tall, reader finds the line | same | 122 | 0.402 free ends (0.393 with nothing given) | synthetic-only 0.746 |
| Maps, each segment's whole labelled region read once, nothing given | same | 122 | **0.336** free ends; 52 of 87 groups fully right | synthetic-only 0.590 |
| PHerc. 172 hand-drawn labels (Bodillium), test half, columns found | the labeller's preliminary transcription | 122 | 0.426 ink only (diagnostic) | prototype 0.625, synthetic-only 0.739 |
| Real-letter validation lines from 21 papyri it never saw (Hell-Char) | the crops' letter labels | 2,000 lines | 0.444 | CPU real-letterform reader about 0.52 |

What this supports (Interpretation): with the line found, naming clean drawn Greek capitals is close to solved for this reader (3 errors in 122 letters). On real ink maps it finds about two of every three letters in order. The gap between drawings and maps is the reader's, not the signal's: these six PHerc. 1667 segments are legible by eye on their maps.

What it does not support:

- **Maps of text no ink model has seen.** The six labelled PHerc. 1667 segments are in `ink_9um`'s training labels, so their maps may be cleaner than maps of new text. On the thirteen PHerc. 1667 segments without labels, whole-map reads gave no ordered pairs of lines matching the published text (a test with little power, since it found pairs only on the two labelled segments where the letter error is lowest).
- **A reading.** The references are machine transcriptions of drawings and one labeller's preliminary transcription, not a papyrologist's reading, and 122 letters cannot show an accuracy finer than about 1 to 3 percent.
- **Letter size found automatically on new maps.** On the unlabelled segments the scale search chose letter heights of 32 to 615 grid pixels against 74 to 103.5 measured on the labelled ones. Give `--letter-px` when you can.

## Model card: letters-v2-real

| | |
| --- | --- |
| File | `letters-v2-real-step030000.npz`, format `linenet-v1` (BatchNorm folded into the convolutions), SHA-256 `44946dadf0195ddb565f097acec0dd1d777af9b6c66d83995c1f4497aa587477` |
| Where | see [`kit/data/letter-weights.json`](../kit/data/letter-weights.json) (the `url` field) |
| Network | 2D convolutions (channels 48, 96, 160, 192, 256) over a 36-row band at a letter height of 16 px, collapsed to one row, then dilated 1D residual convolutions (dilations 1, 2, 4) and a 25-way head (24 capitals with lunate sigma, plus the CTC blank); 1,483,241 parameters; one output frame per 4 px; each frame sees about five letters, so it cannot carry a word across a line |
| Training data | 600,000 lines of uniform random letter strings (no Greek words), rendered with a broad-nib bookhand skeleton and installed fonts, with half the letters cut from a bank of 43,806 real letter crops: 12,761 from 144 dated papyri of 310 to 3 BCE (Hell-Char, [Pavlopoulos et al., arXiv 2606.24984](https://arxiv.org/abs/2606.24984), CC BY 4.0) and 31,045 from 152 photographs (ICDAR 2023 Greek letters, [Zenodo 13825619](https://zenodo.org/records/13825619), CC BY-NC 4.0); every line degraded to look like an ink-detection map or a drawn ink label |
| Training | `scripts/letters/train_linenet.py`, 30,000 steps, batch 128, AdamW one-cycle to 0.002, on one NVIDIA B200 (469 s of training), 9 October 2026 |
| Checkpoint choice | the best of 15 kept checkpoints on the dev half of the PHerc. 172 drawings (0.482; all 15 were 0.482 to 0.599); no PHerc. 1667 data was used to train or choose it |
| Intended use | Letter hypotheses on images of Greek capital text, for a person to check: triage of where letters are, review layers, research on reading ink maps |
| Not for | Claiming that a scroll says something; prize images (they must not carry character annotations); publishing reads of a prize-eligible scroll before its prize is awarded (prize disclosure terms) |
| Licence | CC BY-NC 4.0, because part of its training data is CC BY-NC 4.0 (ICDAR 2023); the code is Apache-2.0 |

## Reproduce the benchmarks

```bash
python -m pip install numpy pillow tifffile zarr imagecodecs        # pdftotext (poppler) for the published text
python scripts/letters/p1667_fetch.py work/p1667                     # 19 maps (about 1.9 GB) and 6 label sets
python scripts/letters/p1667_groups.py work/p1667/labels work/p1667/groups      # 91 letter groups, model-free
cd scripts/letters
python p1667_mapcrops.py ../../work/p1667/groups ../../work/p1667/maps          # also --wide and --region
cd ../..
# references: transcribe work/p1667/groups/png/*.png (three independent transcribers, '?' when unsure) into
# refs.json as {"agreed": {"w013-g000": "...", ...}} with only the groups all three agree on
python scripts/letters/eval_p1667.py read work/p1667/groups refs.json --weights W.npz --source label --out label.json
python scripts/letters/eval_p1667.py read work/p1667/groups refs.json --weights W.npz --source map --out map.json
python scripts/letters/eval_p1667.py read work/p1667/groups refs.json --weights W.npz --source map-region --out region.json
python scripts/letters/eval_p1667.py compare A.json B.json --metric free_ends       # paired bootstrap over groups
```

`eval_p1667.py read` needs a weights file path (resolve a released name with `python -c "from kit import letterread as R; print(R.resolve_weights('letters-v2-real'))"`). The published text (arXiv 2606.29085, columns 5 to 22) parses with `python scripts/letters/p1667_text.py PAPER.pdf text.json` (177 lines, 1752 visible letters; output SHA-256 `f936e457eb047f27014e642f50b750b6ee48c825b9eb372fda324449eec0887c` for the v1 PDF). Whole maps cut to the 38 um grid with `eval_p1667_text.py cut`, and `p1667_align.py read/align/crops` places published lines on them (decoy-tested), which `finetune_maps.py` uses to fine-tune on real map lines.

The PHerc. 172 check reads [Bodillium/Herculaneum-Scroll-Labels](https://github.com/Bodillium/Herculaneum-Scroll-Labels) (CC BY-NC-SA 4.0; nothing from it is copied here):

```bash
git clone --depth 1 https://github.com/Bodillium/Herculaneum-Scroll-Labels work/bodillium
python scripts/letters/eval_p172.py work/bodillium --weights W.npz --split test --columns auto
```

## Train your own

```bash
python -m pip install torch numpy pillow
# real letterforms: a glyph bank from Hell-Char (ICDAR 2023 can be added with --icdar)
git clone --depth 1 https://github.com/ipavlopoulos/diachronic-greek-letterforms work/hellchar
python scripts/letters/realforms.py build work/letters/bank.npz --hellchar work/hellchar/data/hellchar
python scripts/letters/realforms.py preview work/letters/bank.npz work/letters/bank-preview.png
# lines: half from the bank; val-real lines use only papyri held out of training
python scripts/letters/gen_dataset.py work/letters/data/train --n 600000 --seed 11 --bank work/letters/bank.npz --p-bank 0.5 --prefix real
python scripts/letters/gen_dataset.py work/letters/data/val --n 4000 --seed 9001
python scripts/letters/gen_dataset.py work/letters/data/val-real --n 2000 --seed 9002 --bank work/letters/bank.npz --bank-split val --p-bank 1.0 --prefix real
# the letters-v2-real recipe (one GPU; about 8 minutes of training on a B200)
python scripts/letters/train_linenet.py work/letters/data/train work/letters/model --val work/letters/data/val \
    --val-real work/letters/data/val-real --steps 30000 --batch 128 --channels 48,96,160,192,256 --dilations 1,2,4 \
    --device cuda --amp --keep
# choose a checkpoint on the PHerc. 172 dev half, never on the data you report
for w in work/letters/model/ckpt/*.npz; do python scripts/letters/eval_p172.py work/bodillium --weights $w --split dev | tail -1; done
```

A CPU-sized run (the trainer's defaults: 593,849 parameters, 4,000 steps, batch 48, on 36,000 synthetic lines plus 24,000 drawn only from the Hell-Char bank) takes about half an hour on 4 cores and reads the PHerc. 1667 drawings nearly as well (0.033) and the maps as well (0.344 free ends). `finetune_maps.py train` starts from any exported checkpoint, released weights included.

## How it works

- **Lines, not single letters.** Herculaneum texts are written without word spaces and letter edges on an ink map are unclear, so segmenting letters first is the hard part. A CTC line reader needs only each line's letter string to train, and learns where the letters are by itself.
- **Random letters, separate language model.** Training on uniform random strings means the network learns shapes and cannot learn Greek, so it cannot invent plausible words; Greek enters only through the optional language model, shown beside the ink-only decode. The organisers' own ink models use no OCR or language model for the same reason ([grand prize page](https://scrollprize.org/grandprize)).
- **Real letterforms.** Synthetic glyphs alone did not transfer to real letters (more synthetic data gave no gain on drawings); half the training letters cut from photographs of real papyri cut the error on drawn PHerc. 1667 letters from 0.320 to 0.025.
- **Page layout.** The reader normalises the image, estimates or takes the letter size, splits columns at empty gutters, deskews, finds lines from the row profile and reads each line band; boxes come back in input pixels.
- **numpy inference**, tested against torch, so reading needs no deep-learning install.

## Rules for using it on scrolls

- Its output is a hypothesis. Never write that letters were found or read on the strength of it.
- The prizes require prize images to be generated programmatically without manual character annotations ([prizes](https://scrollprize.org/prizes)); keep machine letter overlays out of prize images.
- Reading a prize-eligible scroll's maps produces a possible finding; the prize terms forbid disclosing one before the official announcement. Keep such reads private.
- Ink-label masks are text too: reading the labels of a scroll whose text is unpublished produces letters of unpublished text. Treat those reads like reads of a map.

## Files

| File | What it does |
| --- | --- |
| [`kit/letterread.py`](../kit/letterread.py) | The reader: numpy network, CTC decoding (best path and prefix beam with a language model), forced alignment, layout, nulls, orientation, overlay, released weights |
| [`kit/greeklm.py`](../kit/greeklm.py) | Kneser-Ney letter n-grams for Greek in scriptio continua, from TEI texts |
| [`kit/data/letter-weights.json`](../kit/data/letter-weights.json) | Released weights: file, SHA-256, address, licence |
| [`scripts/letters/demo_p1667.py`](../scripts/letters/demo_p1667.py) | End-to-end demo on a public PHerc. 1667 map |
| [`scripts/letters/letterdata.py`](../scripts/letters/letterdata.py), [`gen_dataset.py`](../scripts/letters/gen_dataset.py) | Synthetic lines and pages: bookhand skeleton and fonts, map and label degradations |
| [`scripts/letters/realforms.py`](../scripts/letters/realforms.py) | Glyph bank from Hell-Char and ICDAR 2023 crops, split by papyrus |
| [`scripts/letters/train_linenet.py`](../scripts/letters/train_linenet.py) | Training (torch, CPU or CUDA), export to `linenet-v1` |
| [`scripts/letters/finetune_maps.py`](../scripts/letters/finetune_maps.py) | Fine-tuning on real map lines whose text is published; a '?' in the text is a wildcard |
| [`scripts/letters/eval_p172.py`](../scripts/letters/eval_p172.py), [`compare_p172.py`](../scripts/letters/compare_p172.py), [`eval_pages.py`](../scripts/letters/eval_pages.py) | PHerc. 172 drawings, paired bootstrap, whole synthetic pages |
| [`scripts/letters/p1667_fetch.py`](../scripts/letters/p1667_fetch.py), [`p1667_groups.py`](../scripts/letters/p1667_groups.py), [`p1667_mapcrops.py`](../scripts/letters/p1667_mapcrops.py), [`eval_p1667.py`](../scripts/letters/eval_p1667.py) | PHerc. 1667 data, letter groups from the official labels, map windows, scorer |
| [`scripts/letters/p1667_text.py`](../scripts/letters/p1667_text.py), [`eval_p1667_text.py`](../scripts/letters/eval_p1667_text.py), [`p1667_align.py`](../scripts/letters/p1667_align.py) | Published text as a reference, whole-map reads against it, placing published lines on maps |
| [`tests/test_letterread.py`](../tests/test_letterread.py), [`test_letterdata.py`](../tests/test_letterdata.py), [`test_eval_p1667_text.py`](../tests/test_eval_p1667_text.py) | Tests (numpy against torch, decoding, layout, controls, weights download, overlay) |

## Related work

Published Greek papyrus work classifies single letters on photographs well (about 93% on letter crops, [Swindall et al. 2021](https://scholars.uky.edu/en/publications/exploring-learning-approaches-for-ancient-greek-character-recogni/)), and the best detector on whole papyrus photographs reached mAP 42% ([Turnbull and Mannix 2024](https://arxiv.org/abs/2401.12513)). PHerc. 1667's text and its virtual unwrapping are published in [arXiv 2606.29085](https://arxiv.org/abs/2606.29085). Community tools are listed in [`external.md`](external.md).
