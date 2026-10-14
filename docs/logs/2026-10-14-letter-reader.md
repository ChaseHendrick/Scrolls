# Greek letter reader: the measurements behind the release (8 to 14 October 2026)

This note is the record behind [`docs/letter-reader.md`](../letter-reader.md). The work was done from 8 October 2026 in this project's private workbench and is published here with Chase's approval (14 October 2026). The machine-readable numbers are in [`docs/results.json`](../results.json) under `letter_reader_checks`.

Every number is **Model output** on synthetic images or public data: the PHerc. 172 drawings of [Bodillium/Herculaneum-Scroll-Labels](https://github.com/Bodillium/Herculaneum-Scroll-Labels) (CC BY-NC-SA 4.0), and PHerc. 1667's official ink labels and 2.4 um ink-detection maps in the open-data bucket, whose Greek text is published ([arXiv 2606.29085](https://arxiv.org/abs/2606.29085)). None is a reading of anything new.

## Readers compared

| Reader | Network | Training lines | Steps, hardware | Checkpoint |
| --- | --- | --- | --- | --- |
| Prototype | 593,849 parameters; channels 32, 64, 96, 128, 192; dilations 1, 2 | 36,000 synthetic | 4,000, 4 CPU threads (26 min) | step 1000, chosen on the PHerc. 172 dev half |
| Real letterforms, CPU | same | 36,000 synthetic plus 24,000 drawn only from 12,761 Hell-Char glyphs | 4,000, 4 CPU threads (25 min) | step 3000, chosen the same way |
| letters-v1 | 1,483,241 parameters; channels 48, 96, 160, 192, 256; dilations 1, 2, 4 | 600,000 synthetic | 30,000 at batch 128, one B200 | step 12000, chosen the same way |
| **letters-v2-real** (released) | same as letters-v1 | 600,000, half the letters from 43,806 real crops (12,761 Hell-Char from 144 papyri, 31,045 ICDAR 2023 from 152 photographs) | 30,000 at batch 128, one B200 (469 s of training) | step 30000, chosen the same way |

The glyph bank splits papyri 123 to 21 into train and val by a fixed hash, so validation lines show hands the network never saw. Every reader trains on uniform random letter strings, so none has learned Greek.

## Synthetic and real-letter validation

| Reader | Synthetic val error, last step | Real-letter val error (21 unseen papyri, first 600 lines) |
| --- | --- | --- |
| Prototype | 0.112 | 0.82 to 0.91 |
| Real letterforms, CPU | 0.128 | 0.516 |
| letters-v1 | 0.074 | not measured |
| letters-v2-real | 0.084 | 0.444 (0.443 at its best, step 24000) |

Whole synthetic pages (`eval_pages.py`, 18 pages per run, no letter size or line positions given), prototype: ink-map look 0.158 and label-mask look 0.013 on random letters, 0.138 and 0.019 on Xenophon (0.108 and 0.008 with the language model); 157 of 158 lines found; on 12 blank pages 0 to 10 letters kept, and the verdict called every one of them noise.

Language model: Kneser-Ney letter 5-grams from Diogenes Laertius, *Lives*, and Plato, *Republic* (PerseusDL canonical-greekLit, CC BY-SA 4.0), 937,054 letters: 2.556 bits per letter on held-out chunks, 2.826 on Xenophon, *Anabasis*, against 4.585 for uniform guessing.

## PHerc. 172 drawings (dev half for choosing, test half for reporting)

`eval_p172.py` reads the ten hand-drawn PHerc. 172 label images that have the labeller's preliminary transcription (marked speculative by its author) and matches read lines to it in order. Segments sorted by id: first five dev, last five test. The split rule was written after all-segment numbers of the prototype were seen, and it does not depend on any result.

| Reader | Dev, columns off | Test, columns off | Dev, columns found | Test, columns found |
| --- | --- | --- | --- | --- |
| Prototype | 0.740 | 0.760 | 0.639 | 0.625 |
| Real letterforms, CPU | 0.549 | 0.867 | 0.479 | 0.525 |
| letters-v1 | 0.634 | 0.933 | 0.612 | 0.739 |
| letters-v2-real | 0.482 | 0.806 | **0.471** | **0.426** |

Without a column step, three of the five test segments (two columns side by side) were read as single lines across both columns, which is most of the dev and test disagreement. The column step (`find_columns`: a gutter at least 2 letter heights wide, nearly empty in every row) was added after that was seen, so the columns-found numbers are a diagnostic. Paired bootstrap over lines, columns found, test half: letters-v2-real minus the prototype -0.199 (95% interval -0.337 to -0.042), minus letters-v1 -0.313 (-0.558 to -0.105), minus the CPU real-letterform reader -0.098 (-0.204 to +0.009). These halves hold about 22 to 25 lines each, so they cannot rank readers that differ by less than about 0.2 to 0.3.

## PHerc. 1667 official ink labels, read as drawings (preregistered 9 October)

Six PHerc. 1667 segments in the open-data bucket (w013, w018, w023, w028, w029, w031) carry official ink labels drawn as single letters and short runs. `p1667_groups.py` cuts them into 91 groups by a model-free rule (pieces of at least 500 px at 38 um per pixel; pieces on one line within 0.6 letter heights join one group). References: three separate blind transcriptions by Claude subagents, judging the drawing only and writing `?` when unsure; a group is scored only if all three agree with no `?`: 87 groups, 122 letters. Each group is read with its line and letter height given.

| Reader | Ink only (errors of 122) | With LM | Permuted references (chance) | Letters kept; nulls |
| --- | --- | --- | --- | --- |
| Prototype | 0.402 (49) | 0.492 | 1.090 | 77; 7, 0 |
| Real letterforms, CPU | 0.033 (4) | 0.025 | 1.164 | 114; 33, 2 |
| letters-v1 | 0.320 (39) | 0.311 | 1.205 | 105; 17, 1 |
| letters-v2-real | **0.025** (3) | 0.041 | 1.172 | 119; 22, 4 |

Deviation (recorded before the corrected read): the first read was void because `p1667_groups.py` stored each line centre in the segment's rows instead of the crop's, so most groups were read outside their crop (ink-only error 0.885 to 0.967 for all four readers). The code was fixed with crops, transcriber images and references byte-identical and no rule changed; the table is the corrected read.

Paired bootstrap over groups: letters-v2-real minus the prototype -0.377 (-0.471 to -0.292), minus letters-v1 -0.295 (-0.380 to -0.213): both preregistered comparisons confirmed. letters-v2-real minus the CPU real-letterform reader -0.008 (-0.046 to +0.025): not separable. letters-v2-real's three errors: `ΓΝΚ` read `ΡΝΚ`, `ΤΩ` read `ΡΩ`, `ΕΙΚΑΙ` read `ΕΙΚΒΙ`.

Re-measured on 13 October with fresh blind transcriptions (86 groups, 119 letters agree): 0.017 (2 of 119).

## The same letters from the 2.4 um ink maps (preregistered 9 October)

Each labelled segment's 2.4 um ink-detection map has exactly its label's grid (the map is 0.62 to 0.81 under labelled ink and 0.19 to 0.28 elsewhere in the windows; shifting the labels never helps by more than one 38 um pixel). `p1667_mapcrops.py` cuts the same windows from the maps. Primary measure: free ends (letters read before and after the reference are not charged, since a window also shows unlabelled neighbours).

| Reader | Line given | Windows about 3 lines tall, line found | Same, nothing given | Whole labelled region, letter height given | Whole region, nothing given | Groups fully right (whole region, nothing given) |
| --- | --- | --- | --- | --- | --- | --- |
| Prototype | 0.680 | 0.754 | 0.746 | 0.754 | 0.803 | 8 of 87 |
| Real letterforms, CPU | **0.344** | **0.344** | 0.451 | 0.402 | 0.443 | 43 |
| letters-v1 | 0.705 | 0.746 | 0.697 | 0.680 | 0.590 | 23 |
| letters-v2-real | 0.369 | 0.402 | **0.393** | **0.328** | **0.336** | **52** |

Every reader passes both controls in every condition (more than three times as many confident letters on the maps as on the larger of the two nulls; error against the right references below the error against permuted ones). The preregistered comparisons, letters-v2-real against the prototype and against letters-v1, are confirmed in each primary read (line given; lines found and whole regions with the letter height given): for example -0.311 (-0.415 to -0.210) and -0.336 (-0.430 to -0.243) with the line given, -0.426 (-0.529 to -0.325) and -0.352 (-0.452 to -0.250) for the whole regions. The fully automatic reads were preregistered as reported beside them, not decisive, and point the same way: -0.352 (-0.448 to -0.256) and -0.303 (-0.410 to -0.194) for lines found, -0.467 (-0.562 to -0.372) and -0.254 (-0.354 to -0.154) for whole regions. Re-measured on 13 October: 0.370 with the line given, 0.328 for the whole regions.

Interpretation: on real ink maps the two real-letterform readers find about two of every three letters in order, and finding the columns, lines and letter size themselves costs letters-v2-real nothing measurable. The maps cost about 0.33 against the drawings. These six segments are in `ink_9um`'s training labels, and the training set of the 2.4 um model that made their maps is not checked, so their maps may be cleaner than maps of new text.

## Unlabelled PHerc. 1667 segments against the published text (preregistered 9 October)

The thirteen PHerc. 1667 segments with maps and no labels (w011, w012, w030, w032 to w041) were each read whole and scored against the published text of columns 5 to 22 (`p1667_text.py` on the PDF's word boxes: 177 lines, 1752 visible letters, 586 unknown). The decisive statistic counted ordered pairs: two consecutive read lines whose best published lines score at least 5 and sit 1 or 2 lines apart, in order, against 297 decoy texts of the same shape.

A dry run before the rule was fixed (9 October) gave the scorer strings in place of reads on 107 found lines. Uniform random letters (10 draws) made 0 pairs and fit the real text worse than the decoys (fit p at least 0.25 against every decoy set). Samples of the Greek letter language model (40 draws) made at most 1 pair, so the pairs rule passed in none of the 40. But their fit beat every shuffled decoy in all 40 draws (p = 0.01), every word-order decoy in 13, every corpus decoy in 2 and every shifted decoy in 3. So pairs decide and fit is only reported.

Result: **0 pairs for every reader**, so the test did not show that the reader places the published text on these maps. Post hoc (after the result, not preregistered): the same chain on the six labelled segments' whole maps makes 7 pairs for letters-v2-real against a decoy maximum of 1 (Model output), all on w013 and w018, where its letter error is lowest (0.17 and 0.23), and none on the four where it errs on about one letter in two. So the test had little power, and lowering the letter error on maps is what would give it power (Interpretation).

## What is not shown

- Accuracy on maps of text no ink model has seen.
- Accuracy finer than the sample allows: 122 letters bound an error rate only to within a few percent.
- A reading of anything: the references are machine transcriptions of drawings or one labeller's preliminary transcription.
