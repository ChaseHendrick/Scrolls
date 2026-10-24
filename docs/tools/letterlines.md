# letterlines: training lines for the letter reader from your own transcriptions, and their scores

`python -m kit letterlines build` checks records of lines you transcribed and cuts each line as the letter reader sees it into a `LINES.npz` for fine-tuning; `letterlines score` gives one or more models' character error on lines kept apart, with a paired interval.

| Field | Value |
| --- | --- |
| Id | `letterlines` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Letters and titles |
| Run | `python -m kit letterlines build`, `python -m kit letterlines score`, `scrolls-letterlines` (the installed package's console script), `from kit import letterlines` |
| Code | `kit/letterlines.py`, `kit/cli.py` (`cmd_letterlines`, `letterlines_main`) |
| Tests | `tests/test_letterlines.py`, `tests/test_letter_scripts.py` |
| Needs | Python 3.10 or newer and numpy; the image libraries the reader loads your images with (tifffile and imagecodecs for TIFF, Pillow for PNG and JPEG, zarr for zarr), which the `reader` extra brings except zarr; Pillow for `--preview`. `score` needs the reader's weights: a released name (downloaded once) or a `linenet-v1` `.npz`. No torch: training on the lines is `scripts/letters/finetune_maps.py`, which needs torch |
| Runs on | Any CPU, in seconds. On 2026-10-16 (4-core 2.8 GHz Xeon cloud container shared with other jobs, one BLAS thread): a dry run of 4 records in 1.1 s, `build` of 2 lines with a preview in 1.4 s, `score` of 2 lines with two cached models in 1.8 s. The guide measured `build` cutting 54 lines from 9 images in 2.4 s and `score` reading 18 lines with two models in 3.5 s (2026-10-14) |
| Network | `build`: none. `score`: the first use of a released weights name downloads it from `github.com`, which redirects to GitHub's release file host (`release-assets.githubusercontent.com` or `objects.githubusercontent.com`) |
| Writes | `build`: the `--out` file (`LINES.npz`) and the `--preview` PNG, making their folders once the records pass; `--dry-run` writes nothing. `score`: the `--out` JSON when given, and the weights file in the cache folder on a released name's first use |
| Go-ahead | Not needed to run. Lines cut from a text that is not published carry that text: keep their `LINES.npz`, previews and any model trained on them private, and never upload them without Chase's yes (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-14 ([PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58)); part of the letter reader release and of the installable package `scrolls-workbench` |
| Guide | [Fine-tune on your own lines](../letter-reader.md#fine-tune-on-your-own-lines) in the letter reader guide |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

Scroll Text Reader's Greek LineNet ([letterread](letterread.md)) was trained on synthetic lines and letter crops of papyri. On a hand or a kind of image it has not seen it can do poorly, and when you know the text of some lines (your own transcription, or a published edition of a papyrus whose images you may use) you can fine-tune it on them. That needs two things done exactly right: the training lines must be cut the way the reader cuts a line when it reads, and the fine-tuned model must be judged on lines it never trained on.

`build` does the first. You write one **record** per line: the image, the line's letters, its center row and its letter height, optionally where it starts and ends, a crop, a polarity and a split label such as `train` or `test`. It checks every record before it decodes any image and lists every problem at once. Then it loads each image as the reader loads it, normalizes it once, scales it so letters are the network's working height of 16 px, and cuts the reader's **band** around each line: 36 rows, from 1.1 letter heights above the center to 1.15 below, from the line's first to its last column. The bands, their texts and where each came from go into `LINES.npz`, the format `scripts/letters/p1667_align.py` writes and `scripts/letters/finetune_maps.py` trains on.

`score` does the second. It reads every band of a `LINES.npz` with one or more models and reports each model's **character error**: the edit distance from the model's letters to your text, summed over lines, over the number of letters in your text. A `?` in your text (the **wildcard**, for a letter you cannot see or restore) matches any one letter or none at no cost. With two models or more it gives each later model's error minus the first's, with a 95 % interval from a bootstrap over lines.

It does not train (that is `finetune_maps.py`, with torch), it does not find lines or transcribe them, and it does not make a fine-tuned model's letters any more than hypotheses. A model fine-tuned on these lines is a new model: its output is still Model output for a person to check, never a reading.

## When to use it

- Before fine-tuning the reader on lines you transcribed: `build --dry-run` to check the records, then `build --split train` and `build --split test`.
- After fine-tuning: `score` the lines you set apart, with the model you started from first and the fine-tuned one second.
- To compare two released or trained models on the same transcribed lines (`score` with `--weights` twice).
- `check_references()` from Python, as the benchmark scripts use it, to refuse reference texts with characters the reader never writes.

Do not use it:

- To read an image: use [letterread](letterread.md).
- To check an install: use [letterdemo](letterdemo.md).
- To benchmark on the public PHerc. 1667 and PHerc. 172 labels: use the benchmark scripts in `scripts/letters/` ([letters-training](letters-training.md)), whose rules were fixed before the reads.
- To judge a fine-tuned model on the lines it trained on: that score says nothing; keep a `test` split apart before training.

## Quick start

```bash
python -m kit letterlines build RECORDS.json --dry-run
python -m kit letterlines build RECORDS.json --split train --out OUT/train.npz --preview OUT/train.png
python -m kit letterlines build RECORDS.json --split test --out OUT/test.npz
python -m kit letterlines score OUT/test.npz --weights letters-v2-ccby --weights letters-v2-real
```

- `RECORDS.json`: your records (Inputs gives the fields). Relative image paths are relative to its folder.
- `OUT`: a folder for the lines and the preview; `build` makes it once the records pass.
- The last line compares two released models; after fine-tuning, give the model you started from first and your `linenet.npz` second.

On 2026-10-16 the records were the four lines of [letterdemo](letterdemo.md)'s synthetic page (`demo-page.png`, letters 32 px tall), two with `split` `train` and two `test`. The dry run printed one line per band, then:

```
records.json record 4 [test]: demo-page.png, y 246.4, x 40 to 990, letters 32 px; band rows 211.2 to 283.2 -> 475 x 36 px at the network's scale, 19.8 px a letter: ΨΔΜΑΙΘΩΤΧΠΦΟΓϹΒΖΥΛΗΝΕΡΚΞ
4 lines from 1 image(s), 96 letters and 0 '?'
dry run: nothing was cut or written
```

`build` printed `out/train.npz: 2 lines, 48 letters and 0 '?', from 1 image(s)`, and `score` ended:

```
model 0: letters-v2-ccby: character error 0.0000 (0 edits over 48 letters)
model 1: letters-v2-real: character error 0.0000 (0 edits over 48 letters)
model 1 minus model 0: +0.0000 character error (95% interval +0.0000 to +0.0000, bootstrap over lines)
```

It worked when every command exits 0, the dry run lists every line you wrote with no `error:` line, the preview shows each band holding its line, and `score` lists every test line with each model's read.

## Checks and controls

- **Every record is checked before anything is cut.** A missing field, a number that is not one, an image that does not exist, a row outside the image, a character the reader does not write, or a band too narrow for its letters stops `build` with every problem listed (exit 2). Lines that can be cut but look wrong (letters much narrower or wider than the network's, a band beyond the image, two records on the same line) are warnings.
- **The preview is the check by eye.** `--preview` draws the first 100 bands, each above its text; a band that does not hold its line means a wrong `y`, `letter_px`, `x0` or `x1`.
- **Score only lines kept apart.** The fair test of a fine-tuned model is on lines set apart before training (a `test` split), against the model it started from on the same lines. A difference whose 95 % interval includes 0 is not distinguishable from noise. Lines from one image share its hand and damage, so with test lines from few images the interval is narrower than it should be; with one test line there is no interval, and the result says so.
- **The comparison can fail.** On 2026-10-16, `letters-v2-ccby` against the tests' network of random weights on the two test lines above gave `model 1 minus model 0: +0.9167 character error`.
- **Recorded numbers.** The guide's chain check (2026-10-14, synthetic pages that the released model already reads well, started from `letters-v2-real`): character error on the set-apart lines 0.191 before and 0.186 after 50 steps of fine-tuning, a difference of -0.005 with a 95 % interval of -0.028 to +0.019. It shows that the chain works, nothing about how much fine-tuning helps on real lines; it is in the `letter_reader_checks` list of [`results.json`](../results.json) (entry dated 2026-10-14).

Claim label: Model output: the character error of named weights on the lines given, against your own transcription. It is not a reading, and it measures nothing beyond those lines.

## Commands and options

### `python -m kit letterlines build`

```
usage: python -m kit letterlines build [-h] [--out LINES.npz] [--dry-run]
                                       [--split SPLIT] [--preview PNG]
                                       [--max-mpx MAX_MPX] [--quiet]
                                       records
```

| Option | Default | Meaning |
| --- | --- | --- |
| `records` | required | A `.json` or `.csv` records file (any other suffix is read as JSON). Relative image paths in it are relative to its folder |
| `--out LINES.npz` | none | The training lines to write. Required unless `--dry-run`; refused when it names a folder. Its folder is made once the records pass |
| `--dry-run` | off | Check every record and print the plan, one line per band; decode no image and write nothing |
| `--split SPLIT` | none | Keep only records whose `split` equals this label (compared as text). With no record of that label, an error |
| `--preview PNG` | none | Also write a PNG of the first 100 bands, each above its text, scaled 2 times (at most 3,000 px wide). Needs Pillow; refused when it names a folder |
| `--max-mpx MAX_MPX` | `64` | Pixel budget in millions of pixels, as in `letterread` (`letterread.MAX_PIXELS / 1e6`): a bigger image (or crop) is block-averaged while it loads. Must be positive |
| `--quiet` | off | No progress messages and no warnings on stderr (the dry run still prints its warnings on stdout) |

### `python -m kit letterlines score`

```
usage: python -m kit letterlines score [-h] --weights WEIGHTS [--out OUT]
                                       [--json]
                                       lines
```

| Option | Default | Meaning |
| --- | --- | --- |
| `lines` | required | A `LINES.npz` from `build` (or from `scripts/letters/p1667_align.py`) |
| `--weights WEIGHTS` | required | A released model name (`letters-v2-ccby`, `letters-v2-real`; downloaded once and SHA-256 checked) or a `linenet-v1` `.npz`. Repeat it to compare models: the first is the reference, and each later one is reported minus it |
| `--out OUT` | none | Also write the result as JSON (UTF-8). Its folder must exist; that is checked before any read |
| `--json` | off | Print the result as JSON (the fields under Outputs) instead of the text summary |

From an installed package, `scrolls-letterlines build ...` and `scrolls-letterlines score ...` are the same commands.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_LETTER_WEIGHTS` | unset: `~/.cache/scrolls-kit/letters` | Where `score` finds or downloads a released model: a cache folder, or a weights file with the model's SHA-256. Read by `kit/letterread.py` ([letterread](letterread.md)) |

## Python API

```python
from kit import letterlines as LL
plans, warnings, meta = LL.build("my-lines.json", "work/letters/mine-test.npz", split="test")
res = LL.score_lines("work/letters/mine-test.npz", ["letters-v2-ccby", "work/letters/mine/linenet.npz"])
print(LL.score_text(res))
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `build(records_path, out=None, split=None, dry_run=False, max_pixels=R.MAX_PIXELS, progress=None)` | `(plans, warnings, meta)` | `RecordsError` listing every problem in the records; `ValueError("give the output file (LINES.npz), or a dry run")` without `out` and `dry_run`; the loaders' errors while cutting | What the command runs. `meta` is the dict stored in `LINES.npz` (Outputs). `progress` is an optional callable taking a short message |
| `RecordsError(errors)` | An exception (a `ValueError`) whose `.errors` lists every problem; its message is those lines joined | Nothing | Raised by `load_records`, `build` |
| `load_records(path)` | list of `(where, record)`, `where` being `FILE record N` (JSON) or `FILE line N` (CSV), with the JSON object's defaults applied | `RecordsError` for an unreadable or unparseable file, an unknown field or column, or a default it does not take | A CSV row's empty cells are left out |
| `check_records(records, base_dir='.', split=None, net_letter_px=NET_LETTER_PX, band=BAND, stride=STRIDE)` | `(plans, errors, warnings)`; each plan holds `where`, `image`, `key`, `crop`, `window`, `y`, `x0`, `x1`, `letter_px`, `polarity`, `split`, `id`, `text`, `visible`, `wildcards`, `band_rows`, `width`, `frames`, `frames_needed`, `pitch` | Nothing: problems are returned as `errors` | Opens each image only to read its shape (no pixels decoded where the format allows) |
| `plan_text(plans, warnings=(), errors=())` | str | Nothing | The dry run's text |
| `cut_lines(plans, net_letter_px=NET_LETTER_PX, band=BAND, max_pixels=R.MAX_PIXELS, progress=None)` | `(imgs, texts, where)`: float32 bands in 0..1 (36 rows each), texts, and per band its origin | The reader's loading errors (`OSError`, `ValueError`, `ImportError`) | Each image, crop, polarity and letter size is loaded and normalized once |
| `save_lines(path, imgs, texts, where, meta)` | `path` | `OSError` | Writes the `LINES.npz` format (Outputs); bands as uint8, column-major |
| `load_lines(path)` | `(imgs, texts, where, meta)`, bands as uint8 arrays | `OSError` for a missing file, `ValueError` for a file that is not a `.npz`, `zipfile.BadZipFile` for a damaged one, `KeyError` for a `.npz` without the fields | Reads this module's files and `p1667_align.py`'s |
| `preview(path, imgs, texts, max_lines=100, scale=2)` | `path` | `ImportError` without Pillow; `OSError` | The first `max_lines` bands, each above its text |
| `score_lines(path, weights, boot=2000, seed=0)` | The `score` result dict under Outputs | What `load_lines` and `letterread.load_weights` raise | `weights` is a list of names, paths or `LineNet`s |
| `score_text(res)` | str | Nothing | The text `score` prints |
| `clean_text(text)` | `(cleaned, problems)`: the text in the reader's alphabet with `?` kept, and each other character as `'X' (UNICODE NAME)` | Nothing | Drops accents, breathings, dots under letters and spaces; capitalizes; every sigma becomes the lunate `Ϲ` |
| `check_references(refs, alphabet=ALPHABET, wildcard=WILDCARD, source='references', limit=20)` | `refs` unchanged | `ValueError` naming each faulty reference (up to `limit`), every character at fault, what to write instead, and the alphabet | For reference texts compared letter for letter, so nothing is cleaned. `refs` is `{id: text}` or `(id, text)` pairs; `wildcard=None` allows no `?` |
| `reference_problems(text, alphabet=ALPHABET, wildcard=WILDCARD)` | list of str, each faulty character once, as `'X' (NAME; what to write instead)` | Nothing | |
| `letter_problem(c, alphabet=ALPHABET, wildcard=WILDCARD)` | `None` when the reader writes `c` (or it is the allowed wildcard), else the character's name and the fix | Nothing | Knows Latin and Cyrillic look-alikes (`LOOKALIKES`), sigmas, accents, `·`, spaces |
| `alphabet_text(alphabet=ALPHABET, wildcard=WILDCARD)` | str | Nothing | The sentence naming the 24 capitals and the wildcard |
| `ctc_frames_needed(text)` | int | Nothing | One frame per letter plus one between doubled letters; `?` needs none |
| `wild_edit_distance(hyp, ref)` | int | Nothing | Levenshtein distance in which each `?` of `ref` matches any one letter or none at no cost |

## Inputs

**Records**, for `build`: a JSON list of objects; or a JSON object whose `lines` is that list and whose other keys (`image`, `letter_px`, `crop`, `key`, `polarity`, `split`) are defaults for every line; or a CSV with a header row of the field names (a crop as four numbers separated by spaces). Keys `note` and `comment` are ignored. The file is read as UTF-8 (a byte-order mark is allowed).

| Field | Required | Meaning |
| --- | --- | --- |
| `image` | yes | The image file, in any format the reader loads (`.npy`, `.npz`, `.tif`, `.png`, `.jpg`, zarr); a relative path is relative to the records file's folder |
| `text` | yes | The line's letters in Greek capitals. Accents, breathings and dots under letters are dropped, letters are capitalized, every sigma becomes the lunate `Ϲ` and spaces are dropped; `?` stands for a letter you cannot see or restore. Any other character is an error |
| `y` | yes | The line's center row, halfway between the letters' tops and feet, in image pixels (relative to Y0 with `crop`) |
| `letter_px` | yes | The letters' height in image pixels, over 0 |
| `x0`, `x1` | no | The columns where the line starts and ends (default 0 and the image's width); `0 <= x0 < x1 <= width` |
| `crop` | no | `[Y0, Y1, X0, X1]`, four whole numbers, as the reader's `--crop`; the image is normalized over the crop, as a read of it is |
| `key` | no | The array of a `.npz` or zarr, as the reader's `--key` |
| `polarity` | no | `bright` (ink brighter than the ground, ink maps; the default) or `dark` (dark ink on a light ground, photographs) |
| `split` | no | Any label, such as `train` or `test`; `--split` keeps one |
| `id` | no | Your own name for the line, kept in `LINES.npz` |

The cut band is level, so for a tilted line give `x0` and `x1` close to its letters, or a crop around it.

**`LINES.npz`**, for `score`: the file `build` writes (Outputs), or one from `scripts/letters/p1667_align.py`.

## Outputs

**`build`** prints, on stdout, `OUT: N lines, L letters and W '?', from I image(s)`, and with `--preview` a line naming the PNG; progress and warnings go to stderr. **`build --dry-run`** prints one line per band (`WHERE [SPLIT]: IMAGE, crop ..., y Y, x X0 to X1, letters H px; band rows A to B -> W x 36 px at the network's scale, P px a letter: TEXT`), a total line, `warning: ...` lines, then `dry run: nothing was cut or written`.

`LINES.npz` (written with `numpy.savez`):

| Array | Type | Meaning |
| --- | --- | --- |
| `flat` | uint8, 1D | Every band's pixels, 0 to 255, each band column by column, bands one after another |
| `widths` | int32, 1D | Each band's width in pixels at the network's scale |
| `height` | int | Band height, 36 rows |
| `texts` | JSON string | List of the cleaned texts |
| `where` | JSON string | Per band: `where`, `image` (file name only), `y`, `x0`, `x1`, `letter_px`, `crop`, `split`, `id` |
| `meta` | JSON string | `note`, `made_by` (`kit.letterlines`), `version` (the kit version), `records` (`file` name and `sha256`), `split`, `net_letter_px` (16), `band` ([1.1, 1.15]), `lines`, `letters` (visible letters), `wildcards`, `images` (file names) |

No local folder is recorded: images and the records file are named by file name only.

**`score`** prints the model-output note, the file and its counts, each model's character error, each line with each model's read and edit count, and each difference with its interval. With `--json` (and in `--out`):

| Field | Type | Meaning |
| --- | --- | --- |
| `note` | str | The model-output note |
| `lines_file.file`, `lines_file.meta` | str, object | The `LINES.npz` file name and its `meta` |
| `models[].weights` | object | `name` (released name or null), `file`, `sha256`, `format` |
| `models[].errors`, `models[].letters` | int | Edits summed over lines, and visible letters of the texts |
| `models[].cer` | float (4 decimals) | `errors / letters` |
| `lines[].line`, `.text`, `.where` | int, str, object | The band's index, its text and origin |
| `lines[].reads`, `lines[].errors` | list of str, list of int | Each model's best-path letters and its edit count |
| `decode` | str | How lines were decoded: best path, every letter, no confidence floor |
| `diff[].model`, `diff[].minus_model`, `diff[].cer_diff` | int, int, float | Model j minus model 0, in character error |
| `diff[].ci95` | [float, float] or null | 95 % interval from the bootstrap over lines; null with one line |
| `diff[].boot`, `diff[].seed`, `diff[].note` | int, int, str | Draws (2000) and seed (0); or, with one line, the note `one test line: no interval; give two lines or more` |

`diff` is there only with two models or more.

| Exit code | Meaning |
| --- | --- |
| `0` | `build` cut and wrote the lines (warnings allowed), the dry run passed, or `score` finished |
| `1` | An error the command does not catch, with a Python traceback, such as a damaged `LINES.npz` (`zipfile.BadZipFile`) |
| `2` | Problems in the records (nothing was cut), a bad option, a missing file or weights, or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument (an action is required) | Check the command against Commands and options |
| `give --out LINES.npz, or --dry-run to check the records and see what would be cut` | `build` with neither `--out` nor `--dry-run` | Add one of them |
| `give the output file (LINES.npz), or a dry run` | Python's `build()` with neither `out` nor `dry_run` | Pass `out` or `dry_run=True` |
| `PATH is a folder; give a file name` | `--out` or `--preview` names a folder | Give a file name |
| `--max-mpx must be positive` | `--max-mpx` 0 or less | Use the default 64 |
| `--preview needs Pillow: ...` | Pillow is not installed | `python -m pip install pillow`, or leave out `--preview` |
| `N problems in the records; nothing was cut:` then one `error: ...` line per problem, exit code 2 | `build` found problems in the records; the lines below name each | Fix every listed record and run the dry run again |
| `error: FILE: [Errno 2] No such file or directory: ...` | The records file does not exist or cannot be read | Fix the path |
| `error: NAME: empty, or no header row (give a first row of field names: image, text, y, letter_px, x0, x1, crop, key, polarity, split, id)` | An empty CSV | Add the header row |
| `error: NAME: unknown column color; the fields are ...` (or `unknown columns`) | A CSV header with a field it does not know | Rename or drop the column |
| `error: NAME: not JSON (...); give a JSON list of records, an object with "lines", or a .csv file` | A JSON syntax error | Fix the JSON |
| `error: NAME: a JSON object needs "lines", a list of records` | A JSON object without a `lines` list | Put the records under `lines` |
| `error: NAME: x0 cannot be a default; the defaults are image, letter_px, crop, key, polarity, split` | A top-level key that cannot be a default | Move it into each record |
| `error: NAME: give a JSON list of records, an object with "lines", or a .csv file` | JSON that is neither a list nor an object | Use one of the three forms |
| `error: NAME record N: a record is an object such as {"image": ..., "text": ..., "y": ..., "letter_px": ...}` | A list item that is not an object | Make it an object |
| `error: NAME record N: unknown field color; the fields are ...` (or `unknown fields`) | A record field it does not know | Rename or drop it (`note` and `comment` are allowed) |
| `error: WHERE: missing text` (or `image`, `y`, `letter_px`) | A required field is missing or empty | Add it |
| `error: WHERE: y, letter_px, x0 and x1 must be numbers` | A value that is not a number | Give numbers |
| `error: WHERE: letter_px H: give the letter height in image pixels, over 0` | `letter_px` 0, negative or not finite (or `y` not finite) | Give the letter height |
| `error: WHERE: crop ...: give four whole numbers, Y0 Y1 X0 X1` | A crop that is not four whole numbers | Fix the crop |
| `error: WHERE: polarity 'grey': give bright (ink brighter than the ground, as in ink maps) or dark (dark ink on a light ground, as in photographs)` | Another polarity | Give `bright` or `dark` |
| `error: WHERE: text has characters the reader does not write: 'K' (LATIN CAPITAL LETTER K; a Latin letter: type the Greek one), '.' (FULL STOP). Write Greek capitals (ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ), and '?' for a letter you cannot see or restore` | Punctuation, brackets, a Latin look-alike, the reader's own `·`, or another non-Greek character | Write the Greek letter, or `?` |
| `error: WHERE: text has no letters (only '?' or nothing): nothing to learn from` | A text of only `?` | Leave the line out, or write its letters |
| `error: WHERE: PATH: no such file or folder (a relative path is relative to the records file's folder, DIR)` | The image does not exist | Fix the path, relative to the records file's folder |
| `error: WHERE: ...` with the reader's own message | The image cannot be opened or its crop is empty (the reader's loading errors, such as `crop [...] is empty for an image of shape (...)` or a zarr `--key` problem; [letterread](letterread.md) lists them) | Fix the image, its key or the crop |
| `error: WHERE: y 500 is outside the image (rows 0 to 300)` (or `the crop`) | `y` beyond the image or crop | Check `y`, and that it is relative to Y0 with a crop |
| `error: WHERE: x0 X0 and x1 X1: give 0 <= x0 < x1 <= W, the image's width` | `x0` and `x1` out of order or outside the image | Fix them |
| `error: WHERE: the band from x0 40 to x1 80 is 20 px wide at the network's scale (5 frames), too narrow for 12 letters (CTC needs at least 12); check x0, x1, letter_px and the text` | The network gives one output frame per 4 px, and the line needs one per letter plus one between doubled letters | Check `x0`, `x1`, `letter_px` and the text |
| `error: no record has split 'dev'` | `--split` names a label no record has | Fix the label |
| `error: NAME: no records` | The records list is empty | Add records |
| `warning: WHERE: 3 letters on a band 503 px wide at the network's scale, 167.7 px a letter, where letters are usually 8 to 32: check letter_px, the text, and x0 and x1 ...` | Letters much narrower or wider than the network's; still cut | Usually a wrong `letter_px`, or no `x0` and `x1` on a short line |
| `warning: WHERE: band rows A to B reach beyond the image (rows 0 to H); those rows are cut as 0, as the reader reads them` | A line near the edge; still cut | Fine when the line is really there; otherwise check `y` |
| `warning: WHERE and WHERE: rows 54 and 60 are under half a letter apart on overlapping columns: the same line twice?` | Two records on one line; still cut | Remove the duplicate |
| `[Errno 2] No such file or directory: 'PATH'`, exit code 2 | `score` was given a `LINES.npz` that does not exist | Fix the path |
| `This file contains pickled (object) data. ...`, exit code 2 | `score` was given a file that is not a `.npz` | Give a `LINES.npz` |
| `zipfile.BadZipFile: File is not a zip file` and a traceback, exit code 1 | A damaged or cut-off `LINES.npz` | Build it again |
| `no such folder for OUT` | `score --out` in a folder that does not exist | Make the folder |
| `NAME: no such file, and not a released model (letters-v2-ccby, letters-v2-real)` | `score --weights` is neither a released name nor a file | Fix the name or path |
| `could not download the weights NAME from URL into FOLDER: ...` | The weights download failed | Follow the message, or see [letterread](letterread.md) |
| `No module named 'numpy'; python -m pip install "scrolls-workbench[reader]" (numpy, pillow, tifffile and imagecodecs)` | The `reader` extra is not installed | Install it |

## How it works

1. **Load and validate** (`load_records`, `check_records`). Records are parsed, defaults applied, and each record checked in order; image shapes are read once per image and key without decoding pixels where the format allows (`letterread.image_shape`). The text is cleaned (`clean_text`). The working scale is `f = NET_LETTER_PX / letter_px` with `NET_LETTER_PX = 16`; the band's width is `round((x1 - x0) * f)` and its frames that width over `STRIDE = 4`, which must be at least `ctc_frames_needed(text)`. A pitch outside `PITCH_RANGE = (0.5, 2.0)` working letter heights (8 to 32 px a letter) is a warning.
2. **Cut** (`cut_lines`). Records are grouped by image, key, crop, polarity and letter size. Each group's image is loaded with `letterread.load_reduced` (block-averaged by k while loading when over `--max-mpx`), normalized once with `letterread.normalize_for_reading` in its polarity, and resized by `letterread.resize` to `f / k`, as `analyze()` resizes it. A band is rows `round(y / k * f - 1.1 * 16)` onward for 36 rows (`BAND = (1.1, 1.15)`), columns `x0` to `x1` at that scale; rows beyond the image are 0. A test checks that this is exactly the band the reader reads on a line given as `--lines Y` with `--deskew 0`.
3. **Save** (`save_lines`): bands as uint8 (0..1 times 255, rounded), with texts, origins and `meta`, including the records file's SHA-256.
4. **Score** (`score_lines`). Each band is divided by 255, run through the network (`LineNet.log_probs`) and decoded by best path (`letterread.ctc_greedy`) with every letter, no confidence floor. Each line's error is `wild_edit_distance(read, text)`; a model's character error is the sum over lines over the text's visible letters. With several models, `numpy.random.default_rng(seed)` draws `boot` resamples of the lines with replacement, computes each later model's error minus the first's on each, and takes the 2.5 and 97.5 percentiles.

## Cost and time

Measured on 2026-10-16 in a 4-core 2.8 GHz Xeon cloud container that other jobs were sharing (load average 18 to 21), one BLAS thread, on the four synthetic lines of the Quick start:

| Run | Wall time | CPU time |
| --- | --- | --- |
| `build --dry-run`, 4 records | 1.1 s | 0.2 s |
| `build --split train --preview`, 2 lines | 1.4 s | 0.3 s |
| `score`, 2 lines, two cached models | 1.8 s | 0.6 s |
| `score`, the same, downloading `letters-v2-real` (5.9 MB) on its first use | 4.2 s | 0.7 s |

The guide (2026-10-14, a 4-core cloud container): `build` cut 54 lines from 9 images in 2.4 s and `score` read 18 lines with two models in 3.5 s. Memory was not measured. Building and scoring run on any laptop CPU. The fine-tuning between them (`finetune_maps.py`) took about 3.1 s a step on 4 CPU threads in the guide's run, about 80 minutes for the default 1,500 steps, so long runs belong on Modal by the Modal rule (hard rule 11), with a written run spec and the user's go-ahead for any spending.

## For agents

- **Command:** `python -m kit letterlines build RECORDS.json --dry-run`, then `python -m kit letterlines build RECORDS.json --split train --out OUT/train.npz --quiet`; to score, `python -m kit letterlines score OUT/test.npz --weights START --weights TUNED --json`.
- **Parse:** `build`: exit code, and the dry run's `error:` and `warning:` lines. `score --json`: `models[].cer`, and `diff[].cer_diff` with `diff[].ci95` (null with one line).
- **Rerun:** Safe. `build` overwrites `--out` and `--preview`; `score` overwrites `--out`. The dry run writes nothing. The bootstrap is seeded, so a rerun gives the same interval.
- **Success:** Exit code 0; for `build`, a final line `OUT: N lines, ...` with the count you expect.
- **Not a pass:** A score on lines the model trained on; a difference whose `ci95` includes 0; an interval from test lines of one or two images (too narrow); a `build` whose warnings you did not read.
- **Go-ahead:** Nothing to build or score. Uploading lines, previews or models made from an unpublished text needs Chase's yes, and target-scroll text never goes public.
- **Never:** Choose a fine-tuning step count or checkpoint by its score on the test lines; call a fine-tuned model's letters a reading; put a `LINES.npz` of unpublished text in a public commit.

## Tests

```bash
python -m unittest tests.test_letterlines -v
```

They cover text cleaning and its refusals, the reference checks with each fault named and the alphabet printed, the wildcard edit distance, the three ways to write records, every problem reported at once, the warnings, bands that equal the reader's own bands, crops and block-averaged loads, dark ink inverted as the reader inverts it, a `LINES.npz` in the format `finetune_maps.py` reads, the command line (dry run, splits, preview and score), and `build` making its folders. They use synthetic images and small random weights; they never download the released weights and never train. `tests/test_letter_scripts.py` checks that the benchmark scripts refuse references outside the alphabet through `check_references`. On 2026-10-16, `tests.test_letterlines`, `tests.test_letterdemo` and `tests.test_letterexport` (34 tests) passed in 29 s.

## History

- 2026-10-15: the command-line test no longer lets the preview build overwrite the test split's file (`9461876`).
- 2026-10-14: `build` makes the folders of `--out` and `--preview` once the records pass; `score` with one test line says that one line allows no interval; a missing numpy gives the reader extra's install line (`ca7b143`).
- 2026-10-14: `check_references` for the benchmark scripts' reference texts (`e30ff76`).
- 2026-10-14: first version, `build` and `score`, with the CSV and PAGE XML exports of the reader (`33a0ad3`, [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58)).

## Related

- [letterread](letterread.md): the reader whose bands these are, and how released weights are resolved.
- [letters-training](letters-training.md): `finetune_maps.py`, which trains on `LINES.npz`, and the public benchmarks.
- [letterdemo](letterdemo.md): the offline check of an install.
- [greeklm](greeklm.md): the optional letter language model, which cleans text the same way.
- [Fine-tune on your own lines](../letter-reader.md#fine-tune-on-your-own-lines): the whole chain, with its limits and licenses.
- `letter_reader_checks` in [`results.json`](../results.json): the chain check's numbers (2026-10-14).
