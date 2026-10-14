# Greek letter reader

A small learned reader that proposes Greek capital letters, with positions and confidences, on 2D images of scroll text: ink-detection maps, drawn ink labels and photographs of papyri. It reads whole lines with a convolutional network trained with CTC, runs in numpy (no GPU or torch needed to read), and reports controls with every result, so you can tell letters from noise.

Everything it prints is **Model output**: letter hypotheses for a person to check. It is not a reading or a transcription; papyrologists read and transcribe ([NOVELTY.md](NOVELTY.md)).

- Code: [`kit/letterread.py`](../kit/letterread.py) (reader), [`kit/greeklm.py`](../kit/greeklm.py) (optional letter language model), [`scripts/letters/`](../scripts/letters/) (training data, training, benchmarks, demo).
- Measured accuracy: [How well it reads](#how-well-it-reads) below, with the full record in [`logs/2026-10-14-letter-reader.md`](logs/2026-10-14-letter-reader.md) and the numbers in [`results.json`](results.json) under `letter_reader_checks`.
- Weights: [Model card](#model-card-letters-v2-real). Weights are not in git.

## Quick start

You need Python 3.10 or newer and numpy; Pillow reads PNG and JPEG and draws overlays; tifffile reads TIFF maps; zarr (optional) reads zarr and OME-Zarr maps and lets a compressed tiled TIFF be read band by band.

```bash
git clone https://github.com/ChaseHendrick/Scrolls && cd Scrolls
python -m pip install numpy pillow tifffile

# 1. Try it on a public PHerc. 1667 ink map (downloads a 3.5 MB image and the weights once)
python scripts/letters/demo_p1667.py --segment w013 --out work/letters/demo
#    -> work/letters/demo/w013.json, w013-overlay.png and a text summary on screen

# 2. Read your own image (ink bright, as in ink-detection maps; --polarity dark for photographs)
python -m kit letterread MAP.png --weights letters-v2-real --letter-px 86 --overlay MAP-letters.png
python -m kit letterread MAP.tif --weights letters-v2-real --letter-mm 3.3 --um-per-px 38.4 --json --out MAP-letters.json
#    with the reverse-depth map of the same surface as a control (see "The status, and what to do")
python -m kit letterread MAP.tif --weights letters-v2-real --letter-px 86 --control MAP_reverse.tif

# 3. A whole native 2.4 um villa map as downloaded, here with PHerc. 1667's letter height
#    (block-averaged while it loads; see "Big maps" below)
python -m kit letterread MAP-2.4um.tif --weights letters-v2-real --letter-mm 3.3 --um-per-px 2.399 --overlay MAP-letters.png
```

`--weights letters-v2-real` names a released model in [`kit/data/letter-weights.json`](../kit/data/letter-weights.json): the reader downloads it once into `~/.cache/scrolls-kit/letters/` (or `$KIT_LETTER_WEIGHTS`) and refuses a file whose SHA-256 differs. A path to any `linenet-v1` `.npz` works too.

### Letter size matters most

The network reads letters about 16 pixels tall; the reader rescales your image to that. Give the letter height when you know it, either in image pixels with `--letter-px`, or in millimetres with `--letter-mm` together with the pixel size in micrometres, `--um-per-px` (letter_px = letter_mm * 1000 / um_per_px; the reader prints the value it used). PHerc. 1667's letters are about 3.3 mm tall: `--letter-mm 3.3 --um-per-px 2.399` on its native 2.4 um maps (1375.6 px), or `--letter-px 86` on those maps averaged 16 by 16 to about 38 um per pixel. A given size is checked against the line spacing: when the two differ by more than a factor of two, the result carries `letter_px_check.warning` and the summary prints it (the spacing estimate itself can be a factor of two off, when it takes two lines for one).

Without a size, the reader estimates one from the line spacing and searches six scales against its own nulls; the summary prints that search as a table, with the kept scale marked `*`. The search is the weakest step on maps it has not seen (see the limits below). When the image shows no regular line spacing at all, the command stops and asks for `--letter-px` or `--letter-mm` with `--um-per-px` (or a `--crop` that holds several lines); it no longer guesses a quarter of the image height. Python's `analyze()` and `read()` keep that guess for the benchmark scripts, which call them directly, unless given `letter_px_fallback=False`.

| Option | Use |
| --- | --- |
| `--letter-px H`, or `--letter-mm MM --um-per-px UM` | Letter height, in image pixels or in physical units (give one form, not both) |
| `--crop Y0 Y1 X0 X1` | Read part of a large image (a `.npy`, an uncompressed TIFF and a zarr are read by window, and so is a compressed tiled TIFF when zarr is installed); rows, boxes and `--lines` are then relative to Y0, X0, and the result records the crop as `crop`, so full-image rows are Y0 plus the result's rows |
| `--key K` | `.npz`: the array name; zarr: the array path, or the OME-Zarr level (default level 0, full resolution). Every pixel value, `--letter-px` and `--um-per-px` included, is then in that array's pixels |
| `--max-mpx M` | Pixel budget in millions of pixels (default 64); see "Big maps" |
| `--lines Y [Y ...]` | Line centre rows, when you know them (one column) |
| `--columns auto` (default), `off` or a number | Split at empty vertical gutters, read the whole width, or ask for that many columns |
| `--lm greek5.npz` | Add a language-model decode beside the ink-only one (below) |
| `--nulls N` | Number of null copies for the control (default 4) |
| `--control MAP_REVERSE` | A second map of the same surface on the same grid, such as its reverse-depth ink map, read on the image's lines at the same letter size and confidence floor; `strong` then also needs more than three times its letters (see [The control map](#the-control-map)) |
| `--min-letters N` | Fewest confident letters a read or a column needs before its controls can pass (default 10; fewer is `too_few`) |
| `--no-orientation` | Skip the mirrored and rotated reads (faster) |
| `--overlay OUT.png` | The image with kept letters boxed and labelled (green p >= 0.8, yellow below), lower-confidence boxes grey; every outline at least 2 px; a banner above it always carries the whole "Model output ... not a reading" note, wrapped to the width, and under it the status line of the controls with its counts |
| `--overlay-max-side N` | Longest side of the overlay in pixels (default 4000); the JSON records the overlay's scale |
| `--quiet` | No progress messages; without it, long steps (loading, scale search, reading, orientation) report on stderr, so `--json` output on stdout stays clean |

### Big maps

A whole native ink map is large: PHerc. 1667 w013 at 2.4 um is 41,600 by 79,600 pixels (3.3 billion), 13 GB as float32. The reader never makes a float copy of such an image. When an image (or its `--crop`) has more pixels than the budget, 64 million by default (`--max-mpx`; 256 MB as float32, and normalising it takes a few such copies), and the letter size is given, it block-averages the image by an integer factor k while it loads: the largest k that keeps letters at least 32 pixels tall, twice the network's working letter height, so the reader's own resize still averages several pixels into each of its pixels. It reads in row bands that follow the file's tiles: a `.npy` or uncompressed TIFF through a memory map, a zarr or OME-Zarr level by chunk, a compressed tiled TIFF through tifffile's zarr view (with zarr installed; without it the TIFF is decoded whole in its stored integer type, 1 or 2 bytes a pixel, and averaged band by band), a PNG or JPEG decoded in its stored type. Rows and columns left over from the last whole block (fewer than k) are not read.

Everything in the result stays in input pixels: rows, columns, boxes, `letter_px` and the scale-search table are mapped back through k, and the JSON records `input_scale` (k), `input_shape` (the input window) and `reduced_shape` (what was read). Below the budget nothing changes: the image is loaded and read exactly as before. Without a letter size, an image over the budget is reduced only as far as the budget needs, and the reader says so; if its letters are small that can leave them too small to read, so give the size. With letters too small to reduce (under 64 px), the image is loaded whole and the reader says it is over the budget. The image is normalised once (in float32 above the budget, float64 within it, as before) and that one image serves the main read, its nulls, the orientation reads and the overlay. Out of memory, the command stops with this advice: give the letter size, lower `--max-mpx`, or `--crop` a window.

Measured on 14 October 2026 on a 4-core cloud container, 2 threads, under a 10 GB address-space limit (`ulimit -v 10000000`), reading w013's whole 2.4 um map (a 269 MB deflate-compressed tiled TIFF) with `--letter-px 1376` and an overlay: block-averaged by 43 to 967 by 1,851 pixels, 35 to 36 s wall time and about 250 MB peak resident memory (two runs), with 120 letters kept against nulls of 29, 22, 28 and 31 (Model output). The same command before this change stopped with a MemoryError after 23 s, asking for a 12.3 GiB float32 array. The same map averaged 16 by 16 (`--letter-px 86`, 2,600 by 4,975 pixels, under the budget) reads exactly as before, with the same letters, boxes, confidences and control counts: 20 to 23 s and 420 MB, against 23 s and 443 MB before.

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
print(res["control"]["status"], res["control"]["ratio"])  # strong, weak, none, too_few or no_control
print([c["control"]["status"] for c in res["columns"]])   # one status per column
res2 = R.read(img, R.resolve_weights("letters-v2-real"), letter_px=86,
              control=R.load_image("MAP_reverse.png"))    # with a control map of the same shape
print(res2["control"]["control_map"])                     # its kept letters and the ratio to them
R.overlay(img, res, "MAP-letters.png")

# a whole map: block-averaged while it loads when over the budget; boxes come back in input pixels
img, k, shape = R.load_reduced("MAP-2.4um.tif", letter_px=R.letter_px_from_units(3.3, 2.399))
a = R.normalize_for_reading(img)                  # normalise once
res = R.read(a, R.resolve_weights("letters-v2-real"), normalized=True, input_scale=k,
             letter_px=R.letter_px_from_units(3.3, 2.399), letter_px_fallback=False)
R.overlay(a, res, "MAP-letters.png", normalized=True)    # draws the reduced image; boxes are mapped
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

`read()` returns, and `--json` prints, one record per found line: its column, centre row `y`, the `ink_only` string, each letter's glyph, probability `p`, whether it cleared the confidence floor (`kept`) and its box `[y0, y1, x0, x1]`, all in input pixels, and the line's `n_kept` beside `chance`, the count the nulls make expected there (below). Beside them: `letter_px` and where it came from (`letter_px_from`; `letter_px_first_guess` and the `scale_search` table when it was estimated; `letter_mm` and `um_per_px` when given in units), `letter_px_check` (a given size against the line spacing), `input_scale`, `input_shape` and `reduced_shape` (see "Big maps"), `working_scale` (network pixels per input pixel), `columns` (each with its own `control` block), `crop`, and, with `--overlay`, `overlay`: its file, `scale` (overlay pixels per input pixel), `banner_rows` and `size`, so a box edge at input row y and column x lands at overlay row banner_rows + y * scale and column x * scale. These controls travel with the result, and each can fail:

1. **Nulls.** The same reader on tile-shuffled copies (letter-sized tiles with random flips: local texture and grey levels kept, letters and lines broken) and phase-randomised copies (same power spectrum, so the same line spacing, shapes broken). The confidence floor is set so the nulls keep few letters (at most 5% of a line's letter slots, never below p = 0.5). `control.verdict` keeps its old wording, which compares letters kept on the image with each null only: "confident letters well above every null" (more than three times), "more confident letters than every null, but within a factor of three", or "confident letters NOT above the nulls: treat every letter here as noise". The benchmark scripts record it unchanged.
2. **Control map** (`--control MAP_REVERSE`, or `read(..., control=...)`). A second map of the same surface on the same grid, above all its reverse-depth ink map, read on the image's lines at the same letter size and confidence floor (details below).
3. **Status** (`control.status`). One code that a person or a pipeline acts on, from the nulls, the control map when there is one, and a minimum count; per column too.
4. **Orientation.** Letters kept as stored, mirrored and turned 180 degrees. Text the right way round should keep the most. This is weak for Greek capitals, many of which are symmetric, so it is evidence, not a gate; it does not enter the status.
5. **Language off.** `ink_only` never uses the language model.

### The status, and what to do

`control` holds `letters_kept`, `null_letters_kept`, `nulls`, `verdict`, then `min_letters` (10 by default, `--min-letters`), `ratio` (letters kept over the largest null, a null of 0 counting as 1; `null` in the JSON when no nulls were run), `status`, `status_text` and, with a control map, `control_map` (`letters_kept`, `ratio` and, from the command line, `file`). Each column's `control` block has the same fields for that column, plus `chance`. The rule, in order (`control_status()` in `kit/letterread.py`):

1. no nulls run: `no_control`;
2. letters kept not above the largest null, or not above the control map: `none`;
3. fewer than `min_letters` letters kept: `too_few`;
4. more than three times the largest null (and more than three times the control map, when there is one): `strong`;
5. otherwise `weak`.

Without a control map and with at least 10 letters, `strong`, `weak` and `none` are exactly the three old verdicts. The summary prints the old line, then the status line; the overlay banner carries the same status line under the model-output note, starting "Controls:". The status line names the code, the counts behind it and a fixed sentence, for example (the PHerc. 1667 w013 map below):

```
control: 122 letters kept vs nulls [43, 33, 27, 28]: more confident letters than every null, but within a factor of three
status: weak (122 letters kept; nulls 43, 33, 27, 28, ratio 2.84 to the largest). Confident letters above every control, but not three times above all of them: weak evidence.
```

With a control map, the summary adds `control map FILE: N letters kept on the same lines at the same confidence floor` and the counts gain `; control map N, ratio R`. The five sentences, exactly as printed, and what to do:

| `status` | Printed sentence | What to do |
| --- | --- | --- |
| `strong` | `Confident letters more than three times every control: worth a person's check, still model output and not a reading.` | Open the overlay and check the letters by eye, line by line; a person decides what is legible. On an ink map read without `--control`, read again with the reverse-depth map: the nulls alone do not rule out letters the ink model makes from papyrus structure. A pipeline may pass only `strong` reads (or `strong` columns) on to a person. |
| `weak` | `Confident letters above every control, but not three times above all of them: weak evidence.` | Do not use single letters. Check the letter size first (the scale-search table, any `letter_px_check` warning; give `--letter-px` or `--letter-mm`). Look at the per-column statuses and the per-line counts: when the letters sit in one column or a block of lines, read that area again as its own crop, chosen on what the map shows (below). Add `--control` if you have the reverse-depth map. |
| `none` | `Confident letters NOT above the controls: treat every letter here as noise.` | Treat every letter as noise. Common causes: a wrong letter size, the wrong polarity (`--polarity dark` for photographs), or no text the model can see. When `control_map.ratio` is 1 or below, the control map kept as many letters or more, so these letters are not particular to this map. |
| `too_few` | `Too few confident letters to judge (fewer than 10).` | Nothing can be judged either way. Read a larger area (more lines, or a whole column) and check the letter size. Do not lower `--min-letters` to get a pass. |
| `no_control` | `No control run (nulls=0): nothing here can be trusted.` | Read again with nulls (the default `--nulls 4`). |

### Where the letters are

Empty papyrus dilutes a whole-segment count: on a map where text fills a corner, the letters there sit among many lines with none. So the result also says where the letters are kept.

- **Per column.** Each column's nulls are scrambles of that column alone, read on its own lines, so each column has real null counts and gets its own `control` block and status by the same rule (with the control map's count in that column, when one is read). With several columns the summary prints one line per column, in the form `column I (x X0 to X1): STATUS (N letters kept; nulls A, B, C, D, ratio R to the largest), chance C`, where `chance` is the column's mean null count.
- **Per line.** The nulls scramble positions across the whole column (the tile shuffle moves letter-sized tiles anywhere in it, and phase randomisation spreads every shape over all of it), so a null's letters say nothing about which line they came from. The honest chance count for a line is therefore the column's mean null count spread evenly over its lines, `chance` = mean of the column's null counts / its number of lines; every line band spans the column's full width, so each line has the same letter slots. The summary prints it before each line's letters, as in `line  0 y=  209.6 [ 15 kept, chance  2.52]: ··ΝΦΟϹΥ·Ρ·ΗΟΥ····ϹΦ·········ΥΗΙ··Π·` (with `, control map N` added when a control map is read).

Per-line counts are small, so they show where to look; they are not a test. Choosing lines because they beat chance and then calling them text is circular. To test an area, choose it on something other than this read's letter counts (what the map shows, a label, a published column) and read it as its own `--crop`, which gets its own nulls and floor.

Example (Model output, 14 October 2026; PHerc. 1667 w013, a published scroll, its public map averaged to about 38 um, `--letter-px 86`): the whole map is one column of 13 lines, 122 letters kept against nulls of 43, 33, 27 and 28, status `weak`, ratio 2.84. The chance count is 2.52 per line (mean null 32.75 over 13 lines); lines 0 to 9 keep 7 to 16 letters each (110 of the 122) and lines 10 to 12 keep 3 to 6, so the kept letters sit on the upper ten lines.

### The control map

Read the reverse-depth map of the same surface with `--control`: villa's ink inference writes it beside the forward map with `--direction both` (as `NAME_reverse.tif`; see [mac.md](mac.md)). An ink model run on the layers in reverse order sees the same fibres, cracks and sheet edges at the same places, with the ink signal at the wrong depth, so letters that survive depth reversal are not ink.

```bash
python -m kit letterread MAP.tif --weights letters-v2-real --letter-px 86 --control MAP_reverse.tif --overlay MAP-letters.png
```

The control map must have the same shape as the image (the same `--crop` and `--key` are applied to it, and the same block size when the image is over the budget); a different shape stops the command before the read. It is normalised on its own, as any image the reader reads, and read on the image's columns, deskew angles and line rows at the image's letter size and confidence floor, with no nulls of its own. Both rules are deliberate: a map without text has no line structure, so read with its own layout it would get fewer lines and fewer chances to keep letters, and scaled by the image's grey levels a fainter control map would keep fewer letters; either would flatter the image. The control changes nothing else: the image's letters, boxes, floor, nulls and orientation counts are the same with and without it. It does not enter the scale search: without a given size, the size is chosen on the nulls alone and the control map is read at that size.

Check that it can fail (Model output, 14 October 2026, the same w013 map): with the map itself as its control, the control map keeps the same 122 letters and the status is `none`, as it must be; with a tile-shuffled copy of the map as a stand-in control (no public reverse-depth map of w013 was at hand), the control keeps 40 letters, ratio 3.05, and the status stays `weak` because of the nulls.

### Why these rules

**More than three times every control for `strong`** (Interpretation). One factor for every control keeps `strong` meaning one thing, and it is the factor the old verdict already used for the nulls. Read as a rate, a control's count estimates how many of the image's confident letters the reader would make without the image's text; more than three times means that estimate is under a third of what the image keeps. The control map is the stricter control for an ink map, since it keeps the surface's real structure in place, so it gets the same factor, not a lower one; it is paired with the image letter slot for letter slot, so its count needs no allowance for a different layout. A control map that keeps as many letters as the image, or more, makes the read `none`, whatever the nulls say.

**At least 10 letters** (a judgement, checked on public data). The factor of three counts a null of 0 as 1, so with quiet nulls any four letters were "well above every null", and a count of n carries about sqrt(n) of counting noise, a third of the count or more below 10. Measured on 14 October 2026 (Model output): the w013 map above cut into 20 windows of 520 by 1000 px (one to three found lines of about ten letter slots), and three tile-shuffled copies of it cut the same way (60 windows whose letter-sized tiles are scrambled, so lines and letters are broken, as in the tile-shuffle null), each read at 86 px with four nulls. On the shuffled windows, where a pass is a false one, the old verdict passed 17 of 60 (15 "more confident letters than every null", 2 "well above every null"), each on 1 to 5 letters; no shuffled window kept more than 5 letters, and the floor, twice that, makes all 17 `too_few`. It has a cost: on the map as stored, the old verdict passed 12 of 20 windows; 4 (10 to 16 letters) are `strong` now and 8 with 1 to 7 letters are `too_few`, 2 of them "well above every null" on 7 letters. Small windows near the floor are better read as part of a larger area. `--min-letters` changes the floor; raise it for a read that must be sure.

**`weak` is not a pass** (Model output, 14 October 2026). On 24 synthetic pages with no letters (`eval_pages.py`'s blank pages, 12 papyrus-like texture and 12 clutter, seeds 21 and 22), each read twice with four nulls, once with the size searched and once with the true 24 px given, 47 of the 48 reads are `none`; one texture page read at a searched size kept 134 letters against a largest null of 126 (ratio 1.06), which is `weak`. A page with no text at all can be `weak`, which is why the advice for `weak` starts with the letter size.

The numbers are in [`results.json`](results.json) under `letter_reader_checks` (14 October 2026), and both checks rerun with `python scripts/letters/eval_controls.py windows MAP.tif --weights W.npz` (on the w013 map averaged 16 by 16; defaults: 86 px, 520 by 1000 px windows, three shuffled copies) and `python scripts/letters/eval_controls.py blanks --weights W.npz`.

## How well it reads

All numbers are Model output on public data, measured on CPU with the numpy reader, except the real-letter validation row, which is the trainer's own check on the B200. Character error is edit distance over reference letters; 0.10 means about one edit per ten letters. "Free ends" does not charge letters read before or after the reference, because a map window also shows unlabelled neighbours. Each PHerc. 1667 test's rule was fixed in writing on 9 October 2026 before the readers it compares were run on it; the PHerc. 172 row is a diagnostic, because its column rule was set after that test half had been seen (conditions in the [log](logs/2026-10-14-letter-reader.md)). "Synthetic-only" is letters-v1: the same network, data size and training, with no real letters in its training lines.

| Test (letters-v2-real, step 30000) | Reference | Letters | Character error | Comparison |
| --- | --- | --- | --- | --- |
| PHerc. 1667 official ink labels (drawings), line given | 3 blind machine transcriptions, unanimous groups only | 122 | **0.025** ink only | synthetic-only reader 0.320, prototype 0.402 |
| Same 87 groups read from the 2.4 um ink maps, line given | same | 122 | **0.369** free ends | synthetic-only 0.705 |
| Maps, windows about three lines tall, reader finds the line | same | 122 | 0.402 free ends (0.393 with nothing given) | synthetic-only 0.746 |
| Maps, each segment's whole labelled region read once, nothing given | same | 122 | **0.336** free ends; 52 of 87 groups fully right | synthetic-only 0.590 |
| PHerc. 172 hand-drawn labels (Bodillium), test half, columns found | the labeller's preliminary transcription | 122 | 0.426 ink only (diagnostic) | prototype 0.625, synthetic-only 0.739 |
| Real-letter validation lines from 21 papyri it never saw (Hell-Char) | the crops' letter labels | first 600 of 2,000 lines | 0.444 | CPU real-letterform reader about 0.52 |

What this supports (Interpretation): with the line and letter height given, naming clean drawn Greek capitals is close to solved for this reader (3 errors in 122 letters). On real ink maps it finds about two of every three letters in order. Maps cost it about 0.33 of error against the drawings; which letters the maps lose, and how much of that gap is the reader rather than the map, has not been measured.

What it does not support:

- **Maps of text no ink model has seen.** The six labelled PHerc. 1667 segments are in `ink_9um`'s training labels, and the training set of the 2.4 um model that made their maps is not checked, so their maps may be cleaner than maps of new text. On the thirteen PHerc. 1667 segments without labels, whole-map reads gave no ordered pairs of lines matching the published text (a test with little power, since it found pairs only on the two labelled segments where the letter error is lowest).
- **A reading.** The references are machine transcriptions of drawings and one labeller's preliminary transcription, not a papyrologist's reading, and 122 letters cannot show an accuracy finer than about 1 to 3 percent.
- **Letter size found automatically on new maps.** On the unlabelled segments the scale search chose letter heights of 32 to 615 grid pixels against 74 to 103.5 measured on the labelled ones. Give `--letter-px`, or `--letter-mm` with `--um-per-px`, when you can.

## Model card: letters-v2-real

| | |
| --- | --- |
| File | `letters-v2-real-step030000.npz`, format `linenet-v1` (BatchNorm folded into the convolutions), SHA-256 `44946dadf0195ddb565f097acec0dd1d777af9b6c66d83995c1f4497aa587477` |
| Where | the [`letters-v2-real` release](https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-real) of this repository; the address is in [`kit/data/letter-weights.json`](../kit/data/letter-weights.json) |
| Network | 2D convolutions (channels 48, 96, 160, 192, 256) over a 36-row band at a letter height of 16 px, collapsed to one row, then dilated 1D residual convolutions (dilations 1, 2, 4) and a 25-way head (24 capitals with lunate sigma, plus the CTC blank); 1,483,241 parameters; one output frame per 4 px; each frame sees about five letters, so it cannot carry a word across a line |
| Training data | 600,000 lines of uniform random letter strings (no Greek words), rendered with a broad-nib bookhand skeleton and installed fonts, with half the letters cut from a bank of 43,806 real letter crops: 12,761 from 144 dated papyri of 310 to 3 BCE (Hell-Char, [Pavlopoulos et al., arXiv 2606.24984](https://arxiv.org/abs/2606.24984), CC BY 4.0) and 31,045 from 152 photographs (ICDAR 2023 Greek letters, [Zenodo 13825619](https://zenodo.org/records/13825619), CC BY-NC 4.0); every line degraded to look like an ink-detection map or a drawn ink label |
| Training | `scripts/letters/train_linenet.py`, 30,000 steps, batch 128, AdamW one-cycle to 0.002, on one NVIDIA B200 (469 s of training), 9 October 2026 |
| Checkpoint choice | the best of 15 kept checkpoints on the dev half of the PHerc. 172 drawings (0.482; all 15 were 0.482 to 0.599); no PHerc. 1667 data was used to train or choose it |
| Intended use | Letter hypotheses on images of Greek capital text, for a person to check: triage of where letters are, review layers, research on reading ink maps |
| Not for | Claiming that a scroll says something; prize images (they must be generated programmatically without manual character annotations; whether machine letter overlays are allowed is not stated, so keep them out); publishing reads of a prize-eligible scroll before its prize is awarded (prize disclosure terms) |
| Licence | CC BY-NC 4.0, because part of its training data is CC BY-NC 4.0 (ICDAR 2023); the code is Apache-2.0 |

## Reproduce the benchmarks

```bash
python -m pip install numpy scipy pillow tifffile zarr imagecodecs  # pdftotext (poppler) for the published text
python scripts/letters/p1667_fetch.py work/p1667                     # 19 maps (about 1.9 GB) and 6 label sets
python scripts/letters/p1667_groups.py work/p1667/labels work/p1667/groups      # 91 letter groups, model-free
cd scripts/letters
python p1667_mapcrops.py ../../work/p1667/groups ../../work/p1667/maps            # windows for --source map
python p1667_mapcrops.py ../../work/p1667/groups ../../work/p1667/maps --wide     # taller windows, --source map-wide
python p1667_mapcrops.py ../../work/p1667/groups ../../work/p1667/maps --region   # whole regions, --source map-region
cd ../..
# references: transcribe work/p1667/groups/png/*.png (three independent transcribers, '?' when unsure) into
# refs.json as {"agreed": {"w013-g000": "...", ...}} with only the groups all three agree on
python scripts/letters/eval_p1667.py read work/p1667/groups refs.json --weights W.npz --source label --out label.json
python scripts/letters/eval_p1667.py read work/p1667/groups refs.json --weights W.npz --source map --out map.json
python scripts/letters/eval_p1667.py read work/p1667/groups refs.json --weights W.npz --source map-wide --out wide.json
python scripts/letters/eval_p1667.py read work/p1667/groups refs.json --weights W.npz --source map-region --out region.json
python scripts/letters/eval_p1667.py compare A.json B.json --metric free_ends       # paired bootstrap over groups
```

`eval_p1667.py read` needs a weights file path (resolve a released name with `python -c "from kit import letterread as R; print(R.resolve_weights('letters-v2-real'))"`). The published text (arXiv 2606.29085, columns 5 to 22) parses with `python scripts/letters/p1667_text.py PAPER.pdf text.json` (177 lines, 1752 visible letters; output SHA-256 `f936e457eb047f27014e642f50b750b6ee48c825b9eb372fda324449eec0887c` for the v1 PDF). Whole maps cut to the 38 um grid with `eval_p1667_text.py cut`, and `p1667_align.py read/align/crops` places published lines on them (decoy-tested), which `finetune_maps.py` uses to fine-tune on real map lines.

The PHerc. 172 check reads [Bodillium/Herculaneum-Scroll-Labels](https://github.com/Bodillium/Herculaneum-Scroll-Labels) (CC BY-NC-SA 4.0; nothing from it is copied here):

```bash
git clone --depth 1 https://github.com/Bodillium/Herculaneum-Scroll-Labels work/bodillium
python scripts/letters/eval_p172.py work/bodillium --weights W.npz --split test --columns auto   # needs pdftotext (poppler)
```

## Train your own

```bash
python -m pip install torch numpy pillow
# real letterforms: a glyph bank from Hell-Char and ICDAR 2023, as in letters-v2-real (about 43,806 glyphs);
# leave out --icdar for a Hell-Char-only bank (CC BY 4.0 data), which is not the released model's data
git clone https://github.com/ipavlopoulos/diachronic-greek-letterforms work/hellchar
git -C work/hellchar checkout aeef8466be674403e2dd9b0fc708b95fe7475a00
curl -sSfL -o work/icdar.zip "https://zenodo.org/records/13825619/files/ICDAR2023_Competition_on_Detection_and_Recognition_of_Greek_Letters_on_Papyri_Dataset.zip?download=1"   # CC BY-NC 4.0, MD5 115645f6864bb922d60309687fcfaa56
python -c "import zipfile; zipfile.ZipFile('work/icdar.zip').extractall('work/icdar')"
# --icdar-optional skips the two truncated ICDAR photographs, as the release bank did
python scripts/letters/realforms.py build work/letters/bank.npz --hellchar work/hellchar/data/hellchar --icdar work/icdar --icdar-optional
python scripts/letters/realforms.py preview work/letters/bank.npz work/letters/bank-preview.png
# lines: half from the bank; val-real lines use only papyri held out of training
python scripts/letters/gen_dataset.py work/letters/data/train --n 600000 --seed 11 --bank work/letters/bank.npz --p-bank 0.5 --prefix real
python scripts/letters/gen_dataset.py work/letters/data/val --n 4000 --seed 9001
python scripts/letters/gen_dataset.py work/letters/data/val-real --n 2000 --seed 9002 --bank work/letters/bank.npz --bank-split val --p-bank 1.0 --prefix real
# the letters-v2-real recipe (one GPU; about 8 minutes of training on a B200)
python scripts/letters/train_linenet.py work/letters/data/train work/letters/model --val work/letters/data/val \
    --val-real work/letters/data/val-real --steps 30000 --batch 128 --channels 48,96,160,192,256 --dilations 1,2,4 \
    --device cuda --amp --workers 6 --threads 2 --eval-every 2000 --keep    # keeps 15 checkpoints, steps 2,000 to 30,000
# choose a checkpoint on the PHerc. 172 dev half, never on the data you report
# (needs the Bodillium clone from the PHerc. 172 check above and pdftotext)
for w in work/letters/model/ckpt/*.npz; do echo "$w $(python scripts/letters/eval_p172.py work/bodillium --weights $w --split dev | tail -1)"; done
```

A CPU-sized run (the trainer's defaults: 593,849 parameters, 4,000 steps, batch 48, on 36,000 synthetic lines plus 24,000 drawn only from the Hell-Char bank) takes about half an hour on 4 cores and reads the PHerc. 1667 drawings nearly as well (0.033) and the maps as well (0.344 free ends). `finetune_maps.py train` starts from any exported checkpoint, released weights included.

## How it works

- **Lines, not single letters.** Herculaneum texts are written without word spaces and letter edges on an ink map are unclear, so segmenting letters first is the hard part. A CTC line reader needs only each line's letter string to train, and learns where the letters are by itself.
- **Random letters, separate language model.** Training on uniform random strings means the network learns shapes and cannot learn Greek, so it cannot invent plausible words; Greek enters only through the optional language model, shown beside the ink-only decode. The organisers' own ink models use no OCR or language model for the same reason ([grand prize page](https://scrollprize.org/grandprize), Sourced fact).
- **Real letterforms.** Synthetic glyphs alone did not transfer to real letters (more synthetic data gave no gain on drawings); half the training letters cut from photographs of real papyri cut the error on drawn PHerc. 1667 letters from 0.320 to 0.025.
- **Page layout.** The reader block-averages an image over the pixel budget while loading it, normalises it once, estimates or takes the letter size, splits columns at empty gutters, deskews, finds lines from the row profile and reads each line band; boxes come back in input pixels.
- **numpy inference**, tested against torch, so reading needs no deep-learning install.

## Rules for using it on scrolls

- Its output is a hypothesis. Never write that letters were found or read on the strength of it.
- The prizes require prize images to be generated programmatically without manual character annotations ([prizes](https://scrollprize.org/prizes), Sourced fact); keep machine letter overlays out of prize images.
- Reading a prize-eligible scroll's maps produces a possible finding; the prize terms forbid disclosing one before the official announcement. Keep such reads private.
- Ink-label masks are text too: reading the labels of a scroll whose text is unpublished produces letters of unpublished text. Treat those reads like reads of a map.

## Files

| File | What it does |
| --- | --- |
| [`kit/letterread.py`](../kit/letterread.py) | The reader: image loading (block-averaged while loading when over the budget; zarr and OME-Zarr), numpy network, CTC decoding (best path and prefix beam with a language model), forced alignment, layout, nulls, control map, status codes per read, column and line, orientation, overlay, released weights |
| [`kit/greeklm.py`](../kit/greeklm.py) | Kneser-Ney letter n-grams for Greek in scriptio continua, from TEI texts |
| [`kit/data/letter-weights.json`](../kit/data/letter-weights.json) | Released weights: file, SHA-256, address, licence |
| [`scripts/letters/demo_p1667.py`](../scripts/letters/demo_p1667.py) | End-to-end demo on a public PHerc. 1667 map |
| [`scripts/letters/letterdata.py`](../scripts/letters/letterdata.py), [`gen_dataset.py`](../scripts/letters/gen_dataset.py) | Synthetic lines and pages: bookhand skeleton and fonts, map and label degradations |
| [`scripts/letters/realforms.py`](../scripts/letters/realforms.py) | Glyph bank from Hell-Char and ICDAR 2023 crops, split by papyrus |
| [`scripts/letters/train_linenet.py`](../scripts/letters/train_linenet.py) | Training (torch, CPU or CUDA), export to `linenet-v1` |
| [`scripts/letters/finetune_maps.py`](../scripts/letters/finetune_maps.py) | Fine-tuning on real map lines whose text is published; a '?' in the text is a wildcard |
| [`scripts/letters/eval_p172.py`](../scripts/letters/eval_p172.py), [`compare_p172.py`](../scripts/letters/compare_p172.py), [`eval_pages.py`](../scripts/letters/eval_pages.py) | PHerc. 172 drawings, paired bootstrap, whole synthetic pages |
| [`scripts/letters/eval_controls.py`](../scripts/letters/eval_controls.py) | The control status checked on map windows (as stored and tile-shuffled) and on synthetic pages with no letters |
| [`scripts/letters/p1667_fetch.py`](../scripts/letters/p1667_fetch.py), [`p1667_groups.py`](../scripts/letters/p1667_groups.py), [`p1667_mapcrops.py`](../scripts/letters/p1667_mapcrops.py), [`eval_p1667.py`](../scripts/letters/eval_p1667.py) | PHerc. 1667 data, letter groups from the official labels, map windows, scorer |
| [`scripts/letters/p1667_text.py`](../scripts/letters/p1667_text.py), [`eval_p1667_text.py`](../scripts/letters/eval_p1667_text.py), [`p1667_align.py`](../scripts/letters/p1667_align.py) | Published text as a reference, whole-map reads against it, placing published lines on maps |
| [`tests/test_letterread.py`](../tests/test_letterread.py), [`test_greeklm.py`](../tests/test_greeklm.py), [`test_letterdata.py`](../tests/test_letterdata.py), [`test_eval_p1667_text.py`](../tests/test_eval_p1667_text.py) | Tests (numpy against torch, decoding, layout, controls and status codes, control map, weights download, big images and their formats, letter size in units, overlay, letter language model) |

## Related work

Published Greek papyrus work classifies single letters on photographs well (about 93% on letter crops, [Swindall et al. 2021](https://scholars.uky.edu/en/publications/exploring-learning-approaches-for-ancient-greek-character-recogni/)), and the best detector on whole papyrus photographs reached mAP 42% ([Turnbull and Mannix 2024](https://arxiv.org/abs/2401.12513)); both are Sourced facts, the authors' own numbers. PHerc. 1667's text and its virtual unwrapping are published in [arXiv 2606.29085](https://arxiv.org/abs/2606.29085). Community tools are listed in [`external.md`](external.md).
