# letterread: Greek letter hypotheses or explicit local multilingual OCR

`python -m kit letterread` proposes Greek letters with a controlled line network, or explicitly selects a local Tesseract language model for word hypotheses. Both routes record the model and controls; neither produces a verified reading.

| Field | Value |
| --- | --- |
| Id | `letterread` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Letters and titles |
| Run | `python -m kit letterread`, `scrolls-letterread` (the installed package's console script), `from kit import letterread`, `from kit import letterexport` |
| Code | `kit/letterread.py`, `kit/letterexport.py`, `kit/letterweights.py`, `kit/data/letter-weights.json`, `kit/cli.py` (`cmd_letterread`, `letterread_main`, `import_advice`) |
| Tests | `tests/test_letterweights.py`, `tests/test_reader_backends.py`, `tests/test_letterread.py`, `tests/test_letterexport.py`, `tests/test_letterlines.py`, `tests/test_letter_scripts.py`, `tests/test_letterdemo.py`, `tests/test_packaging.py` |
| Needs | Python 3.10 or newer and numpy. Pillow for PNG and JPEG input and for `--overlay`; tifffile (and imagecodecs for compressed TIFFs) for TIFF input; zarr for zarr input and for reading a compressed tiled TIFF band by band. The `reader` extra of the `scrolls-workbench` package brings numpy, Pillow, tifffile and imagecodecs; zarr comes with `pip install zarr`. The weights: a released model (`letters-v2-ccby`, 5,933,674 bytes, or `letters-v2-real`), downloaded once, or a `linenet-v1` `.npz` file. No torch, no GPU |
| Runs on | Any CPU. A 301 x 1,006 px synthetic page with a control map, the four orientation reads, the three exports and an overlay took 4.0 s wall and 13.4 s of CPU (measured 2026-10-16, 4-core 2.8 GHz Xeon cloud container, weights cached). The guide measured a whole 2.4 um PHerc. 1667 w013 map (a 269 MB tiled TIFF) block-averaged by 43 at 35 to 36 s and about 250 MB peak with zarr installed (14 October 2026, 4-core cloud container; [Big maps](../letter-reader.md#big-maps)) |
| Network | Only when a released weights name is not yet in the cache: the download from `github.com`, which redirects to GitHub's release file host (`release-assets.githubusercontent.com` or `objects.githubusercontent.com`). It follows `HTTPS_PROXY` and `NO_PROXY`. Reading an image and the exports make no connection |
| Writes | The weights file into the cache folder on a released name's first use (`~/.cache/scrolls-kit/letters/`, or the folder `KIT_LETTER_WEIGHTS` names). With `--out`, `--csv`, `--page-xml` and `--overlay`, those files, overwritten on a rerun. Otherwise it prints only |
| Go-ahead | Not needed to read public data. Publishing a read, an overlay or an export of a prize-eligible or unpublished scroll is never allowed before the prize is announced (the no-findings rule, hard rule 1); posting any read needs Chase's yes (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-14 ([PR #57](https://github.com/ChaseHendrick/Scrolls/pull/57)); in the installable package `scrolls-workbench` since [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58) the same day; listed in the README's "Released tools" as `letter-reader` |
| Release id | `letter-reader` |
| License | Code: Apache-2.0 ([LICENSE](../../LICENSE)). Weights: `letters-v2-ccby` CC BY 4.0, `letters-v2-real` CC BY-NC 4.0 ([which weights](../letter-reader.md#which-weights)) |
| Guide | [letter-reader.md](../letter-reader.md) (install, first reads, model cards, benchmarks, the result field by field) |
| Checked | 2026-10-17 against commit `869d621` and the reader routing change |

## What it does

The default backend is the Greek LineNet described below. The separate [reader-backends page](reader-backends.md) documents `--backend tesseract`: Latin and other installed language packs, capability discovery, word output and its limitations. Greek weights cannot be relabelled as another language. The command checks a local LineNet checkpoint's actual alphabet before calling it Greek.

Greek weights are selected before reading the image. Explicit `--weights` is preserved; otherwise `--weight-profile` selects a documented profile, defaulting to `ink-lines` when `--lines` is supplied and `permissive` for automatic layout. The profile and licence are printed and recorded in JSON. This follows the released given-line evidence, not a claim of one universally better checkpoint. The Python `letterread.read()` API still requires explicit weights.

Ink detection turns a scroll's CT scan into a 2D ink map, and people then look for letters in it. `letterread` proposes those letters. It is a convolutional line reader trained with CTC (connectionist temporal classification: the network learns from each line's letter string alone, without letter boxes) on synthetic lines of random Greek capitals and real letter crops, exported to a `.npz` file in the format `linenet-v1` and run in plain numpy. For each text line it finds, it returns the letters it decodes, each with a confidence `p`, a box in the image's pixels and whether it cleared the read's confidence floor (`kept`).

Every read carries its controls. The nulls are the same reader run on copies of the image that keep its grey levels but break its letters (tile-shuffled and phase-randomised), and the confidence floor `p_min` is set so the nulls keep few letters. An optional control map, such as the reverse-depth ink map of the same surface, is read on the same lines at the same floor. From those counts the read, each column and each line get a status: `strong`, `weak`, `none`, `too_few` or `no_control`. Turned and mirrored reads add weak evidence about orientation. An optional letter language model (built by [greeklm](greeklm.md)) gives a second decode beside the ink-only one and never replaces it.

Around the network it does the page work: it loads big maps block-averaged in bands (never a float copy of the whole map), normalises the image once (inverting dark ink on a light ground so the network always sees bright ink), estimates the letter height from the line spacing when it is not given, splits columns at empty gutters, deskews each column, finds line rows and reads each line band. `kit/letterexport.py` writes the result as a CSV table of letters and as PAGE XML for tools such as eScriptorium.

It does not read a scroll. Every string, box and overlay it returns is Model output: letter hypotheses for a person to check, never a reading or a transcription. Never write that letters were found or read on the strength of it. A papyrologist decides what is legible.

## When to use it

- Proposing letters, with positions and confidences, on a public ink map, a drawn ink label or a photograph of Greek capitals, for a person to check against the overlay.
- Deciding whether a map region shows letter-like structure beyond chance: the status against the nulls and, for an ink map, the reverse-depth control map.
- Exporting letter hypotheses to CSV or PAGE XML for a review tool.
- From Python, as a step of a pipeline that acts on the status code.

Do not use it:

- To check that the install works: run [letterdemo](letterdemo.md), the offline synthetic check.
- To score how well it reads your own transcribed lines, or to cut training lines from them: use [letterlines](letterlines.md).
- To train or fine-tune the weights, or rerun the benchmarks: use the scripts in [letters-training](letters-training.md).
- To score an ink map against published ink labels: use [auc](auc.md) (pixel AUC with the reverse-depth control) or [hpscore](hpscore.md).
- On a prize-eligible or unpublished scroll in public work: its letters are a possible finding and stay private (the no-findings rule in [`AGENTS.md`](../../AGENTS.md)). Reading the ink labels of an unpublished text counts too.

## Quick start

```bash
python -m kit letterread IMAGE --weights letters-v2-ccby --letter-px PX \
    --control CONTROL --out RESULT.json --overlay OVERLAY.png
```

- `IMAGE`: the image to read: `.npy`, `.npz`, `.tif`, `.png`, `.jpg` or a zarr store, ink bright (give `--polarity dark` or `auto` for a photograph).
- `PX`: the letter height in image pixels (or `--letter-mm MM --um-per-px UM`). Leave it out to estimate it from the line spacing; the read stops when the image shows none.
- `CONTROL`: a map of the same surface on the same grid that should show no letters, such as the reverse-depth ink map; optional.
- `RESULT.json`, `OVERLAY.png`: the full result and a picture of the letters on the image, for a person to check.

The first use of `letters-v2-ccby` downloads it once. On a synthetic page of four lines of 24 drawn capitals, 32 px tall (made with `kit.letterdemo.render_page`, 301 x 1,006 px), with a noise image of the same ground as the control map, it printed:

```
Model output: letter hypotheses from a learned line reader, not a reading. A papyrologist decides what is legible.
weights letters-v2-ccby (letters-v2-ccby-step026000.npz), sha256 b14988852fc7; reader 0.2.0, seed 0, result schema 1
letter height 32.0 px (given), deskew 0.0 deg, confidence floor 0.952
line  0 y=   54.0 [ 24 kept, chance  1.38, control map   0]: ΦΟΜΥΕΡΘΞΒΧΛΔΚΤΨΩΗΠΓΑΖϹΝΙ
...
control: 96 letters kept vs nulls [9, 0, 11, 2]: confident letters well above every null
control map noise.npy: 0 letters kept on the same lines at the same confidence floor
status: strong (96 letters kept; nulls 9, 0, 11, 2, ratio 8.73 to the largest; control map 0, ratio 96). Confident letters more than three times every control: worth a person's check, still model output and not a reading.
orientation: {'as_is': 96, 'mirrored': 75, 'rot180': 56, 'rot90': 23, 'rot270': 20} (best as_is)
```

It worked when the exit code is 0 and the summary ends with a `status:` line. Only `strong` is worth a person's check; see Checks and controls. Progress messages (`reading at letter height ...`, `wrote FILE`) go to stderr; `--quiet` hides them.

## Checks and controls

- **Nulls** (`--nulls`, default 4). Alternating tile-shuffled copies (letter-sized tiles moved and flipped at random: grey levels and local texture kept, letters and lines broken) and phase-randomised copies (the same power spectrum, so the same line spacing, shapes broken), each read like the image. The floor `p_min` lets the nulls keep at most 5 % of the line's letter slots (`null_rate` 0.05), never below 0.5.
- **Control map** (`--control`). For an ink map, the reverse-depth map of the same surface: it shows the same fibres and cracks with the ink signal at the wrong depth. It is read on the image's columns, deskew and lines at the image's letter size and floor. A control map that keeps as many letters as the image makes the read `none`. A control map with no finite values, or a constant one, is refused (`check_control`): it normalises to zeros and keeps no letters, so its count of 0 could never stop a pass; before 16 October 2026 such a control let a read end `strong`.
- **Status** (`control.status`, in this order, `control_status`): no nulls run is `no_control`; letters kept not above the largest null, or not above the control map, is `none`; fewer than `--min-letters` (10, `MIN_LETTERS`) is `too_few`; more than 3 times (`STRONG_FACTOR`) every control, a count of 0 counting as 1, is `strong`; the rest is `weak`. Each column gets its own status, and each line its `chance` count (the column's mean null count over its lines). The rule and what to do for each code: [The status, and what to do](../letter-reader.md#the-status-and-what-to-do).
- **A pass and a fail, synthetic** (2026-10-16, this page's run). The synthetic page above is `strong`: 96 letters against nulls of 9, 0, 11 and 2 and a control map of 0. The noise image alone, nothing given, is `too_few`: 4 letters against nulls of 0, 0, 3 and 2, with a deskew warning, exit code 0.
- **On a public map** (Model output, 14 October 2026, [guide](../letter-reader.md#where-the-letters-are)). PHerc. 1667 w013's public map averaged to about 38 um, `--letter-px 86`, `letters-v2-ccby`: 120 letters against nulls of 31, 20, 33 and 47, status `weak`, ratio 2.55. With the map itself as its control map the status is `none`, as it must be.
- **The controls can fail on text-free input** (Model output, 14 October 2026, `letters-v2-real`, `letter_reader_checks` in [`results.json`](../results.json)). On 24 synthetic pages with no letters read twice each, 47 of 48 reads were `none` and one was `weak` (ratio 1.06), so `weak` is not a pass. On 60 windows of tile-shuffled copies of the w013 map, the old verdict passed 17, each on 1 to 5 letters; the 10-letter floor makes all 17 `too_few`.
- **Accuracy** (Model output, 14 October 2026, [benchmarks](../letter-reader.md#benchmarks-letters-v2-ccby-against-letters-v2-real)). `letters-v2-ccby` names drawn PHerc. 1667 letters from the official ink labels at a character error of 0.043 with the line and letter height given (117 letters), and the same places on the 2.4 um ink maps at a free-ends error of 0.308 to 0.479. Those segments are in `ink_9um`'s training labels, so their maps may be cleaner than maps of new text.
- **Orientation** (`orientation.letters_kept`). Text the right way round should keep the most letters `as_is`. This is weak for Greek capitals, many of which are symmetric, so it does not enter the status.

Claim label: Model output, for every letter, box, count and status the reader returns; each read is a hypothesis for a person to check, reported with its weights, letter size, nulls, control map and status.

## Commands and options

### `python -m kit letterread`

The console script `scrolls-letterread` takes the same arguments, with `scrolls-letterread` in place of `python -m kit letterread` in its usage line.

```
usage: python -m kit letterread [-h] [--backend {linenet,tesseract}]
                                [--language LANGUAGE]
                                [--weights WEIGHTS | --weight-profile {ink-lines,permissive}]
                                [--tessdata TESSDATA]
                                [--ocr-psm {3,6,7,11,13}]
                                [--ocr-timeout OCR_TIMEOUT]
                                [--ocr-min-confidence OCR_MIN_CONFIDENCE]
                                [--key KEY] [--crop Y0 Y1 X0 X1]
                                [--letter-px LETTER_PX]
                                [--letter-mm LETTER_MM]
                                [--um-per-px UM_PER_PX] [--max-mpx MAX_MPX]
                                [--polarity {bright,dark,auto}]
                                [--rotate {0,90,180,270}] [--mirror]
                                [--deskew MAX_DEG] [--lines LINES [LINES ...]]
                                [--columns COLUMNS] [--nulls NULLS]
                                [--control MAP_REVERSE]
                                [--min-letters MIN_LETTERS] [--seed SEED]
                                [--p-min P_MIN] [--lm LM]
                                [--lm-weight LM_WEIGHT] [--beam BEAM]
                                [--no-orientation] [--out OUT] [--csv OUT.csv]
                                [--page-xml OUT.xml] [--overlay OVERLAY]
                                [--overlay-max-side OVERLAY_MAX_SIDE]
                                [--quiet] [--json]
                                image
```

| Option | Default | Meaning |
| --- | --- | --- |
| `image` | required | The image: `.npy`, `.npz`, `.tif`/`.tiff`, `.png`, `.jpg` (any format Pillow opens) or a zarr store. Ink bright by default. A PNG or JPEG is turned by its EXIF orientation as it loads |
| `--weights WEIGHTS` | none | A released model name (`letters-v2-ccby` or `letters-v2-real`, downloaded once and SHA-256 checked; a name is looked up before any file of that name), or a path to a `linenet-v1` `.npz` file |
| `--backend BACKEND` | `linenet` | `linenet` for the Greek network, `tesseract` for explicitly installed local OCR packs; no fallback |
| `--language LANGUAGE` | `grc` | Explicit language; LineNet supports Greek only. Tesseract accepts installed codes such as `lat`, `grc`, `heb`, or an ordered combination such as `grc+lat` |
| `--weight-profile WEIGHT_PROFILE` | none | LineNet: `ink-lines` chooses `letters-v2-real` (CC BY-NC 4.0), `permissive` chooses `letters-v2-ccby` (CC BY 4.0). With neither weights nor profile, supplied `--lines` selects ink-lines and automatic line finding selects permissive. Mutually exclusive with `--weights` |
| `--tessdata TESSDATA` | none | Tesseract local language-pack directory; otherwise the engine's configured system directory. No downloads |
| `--ocr-psm OCR_PSM` | `3` | Tesseract segmentation: 3 automatic, 6 block, 7 line, 11 sparse text, 13 raw line |
| `--ocr-timeout OCR_TIMEOUT` | `60` | Tesseract timeout in seconds per call, including each control, positive and at most 600 |
| `--ocr-min-confidence OCR_MIN_CONFIDENCE` | `50` | Tesseract word confidence floor from 0 to 100, not a calibrated probability |
| `--key KEY` | none | `.npz`: the array name (default the first). zarr: the array path or OME-Zarr level (default level 0, full resolution); pixel values are then in that level's pixels. Also applied to `--control` |
| `--crop Y0 Y1 X0 X1` | none | Read only rows Y0 to Y1 and columns X0 to X1 (numpy slicing, ends excluded); every row, box and `--lines` value is then relative to Y0, X0. The CSV and PAGE exports add the offset back |
| `--letter-px LETTER_PX` | none | Letter height in image pixels, at least 4 (`MIN_LETTER_PX`, a quarter of the network's 16 px letters). Without it (and without `--letter-mm`) it is estimated from the line pitch with a scale search, and the read stops when the image shows no line pitch |
| `--letter-mm LETTER_MM` | none | Letter height in millimetres; needs `--um-per-px`. Not with `--letter-px`. The height it gives in pixels must be at least 4 |
| `--um-per-px UM_PER_PX` | none | Pixel size in micrometres, with `--letter-mm`; letter px = mm x 1000 / um |
| `--max-mpx MAX_MPX` | `64` | Pixel budget in millions of pixels (`MAX_PIXELS` / 1e6): a bigger image is block-averaged by an integer factor while it loads |
| `--polarity POLARITY` | `bright` | `bright`: ink brighter than the ground, as in ink maps. `dark`: dark ink on a light ground, as in photographs. `auto`: a quick read both ways, keeping the polarity whose letters stand further above its nulls (bright on a tie) |
| `--rotate ROTATE` | `0` | Turn the image 0, 90, 180 or 270 degrees clockwise before reading (after `--mirror`); letter boxes stay in input pixels |
| `--mirror` | off | Flip the image left to right before reading |
| `--deskew MAX_DEG` | `6.0` | Largest line tilt searched, degrees either way, in steps of 0.5 (`DESKEW_DEG`, `DESKEW_STEP`); 0 turns deskew off; under 45 |
| `--lines LINES ...` | none | Centre rows of the lines in image pixels (in the turned image with `--rotate` or `--mirror`), each its row at the image's horizontal middle, which the deskew turns about (give `--deskew 0` for level bands). Given lines mean one column. Default: found from the row profile |
| `--columns COLUMNS` | `auto` | `auto`: split at empty vertical gutters at least 2 letter heights wide; `off`: the whole width as one column; a number: that many columns, split at the widest gutters |
| `--nulls NULLS` | `4` | Null copies to read, 0 to 64 (`MAX_NULLS`), alternating tile shuffle and phase randomisation; 0 runs no control (status `no_control`) |
| `--control MAP_REVERSE` | none | A second map of the same surface on the same grid, such as its reverse-depth ink map, read on the image's lines at the same letter size and floor. Same shape after `--crop` and `--key`; normalised in the image's polarity. A map with no finite values, or whose finite values are all the same, is refused, since it could never fail |
| `--min-letters MIN_LETTERS` | `10` | Fewest kept letters a read or a column needs before its controls can pass (`MIN_LETTERS`); fewer is `too_few` |
| `--seed SEED` | `0` | Seed of the null copies (column `i` uses seed + `i`; the polarity trial uses seed + 1). The same seed, image, weights and options give the same result |
| `--p-min P_MIN` | none | Letter confidence floor from 0 to 1. Default: set from the nulls so they keep at most 5 % of letter slots, at least 0.5 |
| `--lm LM` | none | A letter language model `.npz` (`python -m kit greeklm build`); its beam decode is reported per line as `with_lm`, beside the ink-only string |
| `--lm-weight LM_WEIGHT` | `0.5` | Weight of the language model in its decode (`LM_WEIGHT`); 0 or more |
| `--beam BEAM` | `32` | Beam width of the language-model decode (CTC prefix beam search); at least 1. Unused without `--lm` |
| `--no-orientation` | off | Skip the mirrored and turned reads (`orientation` is then absent) |
| `--out OUT` | none | Also write the full result as JSON (UTF-8) |
| `--csv OUT.csv` | none | Also write one row per letter: column, line, index, letter, p, kept and its box, in the image file's pixels (the crop's Y0 and X0 added) |
| `--page-xml OUT.xml` | none | Also write PAGE XML (2019-07-15 schema): a TextRegion per column, a TextLine per line, a Glyph per letter with its confidence, in the image file's pixels; marked as model output |
| `--overlay OVERLAY` | none | Also write an image (PNG or any extension Pillow writes) of the image with the letters drawn on it, under a banner with the model-output note and the status; needs Pillow |
| `--overlay-max-side OVERLAY_MAX_SIDE` | `4000` | Longest side of the overlay in pixels (`OVERLAY_MAX_SIDE`); at least 16. The JSON records the scale under `overlay` |
| `--quiet` | off | No progress messages on stderr |
| `--json` | off | Print the full result as JSON on stdout instead of the text summary |

The command checks every option, the output folders and the input paths before it loads the weights, and loads the weights before the image, so a bad option or a failed download costs no load.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_LETTER_WEIGHTS` | unset: the cache folder is `~/.cache/scrolls-kit/letters` | A folder (`~` expanded) to download and keep released weights in, or a weights file (an existing file, or a path ending in `.npz`) to use for a released name when its SHA-256 matches; its folder is then the cache |

## Python API

The standard-library helper `kit.letterweights` selects weights without loading models or reading images:

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `profile_info(profile=None, *, lines_given=False, registry=None)` | Profile name, weights, licence, scope and evidence | `ValueError` for unknown profiles or unregistered weights; file/JSON errors for an invalid registry | Given lines default to ink-lines; automatic layout to permissive |
| `select_weights(weights=None, profile=None, *, lines_given=False, registry=None)` | Released weight name or unchanged explicit path | `ValueError` for both weights and profile | Selection never downloads; the existing loader still checks the release's hash |

For explicit reusable backend selection use `reader_backends.read()` as described on its [page](reader-backends.md).

```python
from kit import letterread as R
from kit import letterexport as E
img, k, shape = R.load_reduced("MAP.tif", letter_px=86)
res = R.read(img, "letters-v2-ccby", letter_px=86, input_scale=k)
print(R.text_summary(res)); E.write_csv(res, "letters.csv")
```

`read()` is the entry point; it takes an array, never a file name. Every result starts with `note`, `schema`, `reader`, `weights` and `seed` and ends with `options`.

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `WeightsError()` | An `OSError` subclass | Nothing | Raised by `resolve_weights` when a download fails; the message names the model, the URL and the cache folder |
| `weights_cache()` | `Path` | Nothing | Folder for downloaded weights: $KIT_LETTER_WEIGHTS (~ expanded), else ~/.cache/scrolls-kit/letters; the file's folder when the variable names a file |
| `released_weights(registry=None)` | dict `{name: entry}` with `file`, `sha256`, `url`, `licence`, `params`, `letter_px`, `card` | `OSError`, `ValueError` or `KeyError` for a missing or malformed registry | Reads `kit/data/letter-weights.json` by default |
| `released_name(sha256, registry=None)` | str, or `None` | Nothing | The released model name whose SHA-256 is sha256; `None` also when the registry cannot be read |
| `resolve_weights(spec, cache=None, registry=None, download=True)` | `Path` of a checked weights file | `TypeError` for a spec that is not a string or path; `ValueError` for a missing file, a folder, a SHA-256 mismatch, a model without a URL, or a missing cached file with `download=False`; `WeightsError` for a failed download | Names come first. A download goes to a temporary file, is kept (mode 0644) only when its SHA-256 matches, and times out after 120 s without data (`DOWNLOAD_TIMEOUT`) |
| `weights_info(net)` | dict `name`, `file`, `sha256`, `format` | Nothing | File name only, never a folder |
| `load_weights(weights)` | `LineNet` | As `resolve_weights`; `ValueError` for a file that is not `linenet-v1` | A `LineNet` is returned as it is |
| `utf8_console(*streams)` | list of the streams changed | Nothing | Default `sys.stdout` and `sys.stderr`; a pipe, a file or a console that cannot encode Greek becomes UTF-8 with `errors="backslashreplace"` |
| `LineNet(path)` | Object with `alphabet`, `letter_px`, `band`, `stride`, `meta`, `file`, `sha256`, `name`, `band_rows`, `logits(band)` and `log_probs(band)` ((T, K) arrays, T = ceil(W / stride)) | `ValueError` for a file that is not `linenet-v1`, or `unknown layer op` | numpy inference of the exported CTC line reader |
| `ctc_greedy(lp, alphabet, blank=0)` | list of `(letter, p, t0, t1)` | Nothing | Best-path decode; p is the highest frame probability of the letter |
| `ctc_beam(lp, alphabet, lm=None, lm_weight=0.0, beam=32, blank=0, insert_bonus=0.0, top_k=8)` | `(best string, log score)` | Nothing of its own | Prefix beam search with optional shallow fusion; `lm` needs `logp_next(prefix)` |
| `force_align(lp, text, alphabet, blank=0)` | list of `(letter, t0, t1, mean p)`, or `None` when the line has too few frames | `ValueError` for a letter not in the alphabet | Viterbi alignment of a known text |
| `locate(query, text, top=3)` | list of `(start, end, edit distance)`, end exclusive, best first | Nothing | Semi-global alignment of a short string in a long text |
| `edit_distance(a, b)` | int | Nothing | Levenshtein distance (insertions, deletions and substitutions cost 1) |
| `exif_orientation(path)` | int 1 to 8 | Pillow's errors for an unreadable PNG or JPEG | 1 for other formats and for a damaged EXIF block |
| `image_shape(path, key=None)` | `(H, W)` | As `load_image` | Without decoding pixels where the format allows; EXIF orientation applied |
| `display_image(path, crop=None, k=1)` | RGB uint8 array, or `None` for a grey image or a format other than PNG and JPEG | `ValueError` for an empty image or crop | The overlay's colour base, cropped and reduced by k |
| `load_image(path, key=None, crop=None)` | 2D float32 array | `FileNotFoundError` for a missing zarr; `ValueError` for a shape that is not 2D or colour, an empty crop, or a zarr key problem; `KeyError` for a missing `.npz` array; `ImportError` without the format's package | Colour becomes grey: Pillow's luma for PNG and JPEG, the mean of three channels otherwise |
| `reduce_factor(shape, letter_px=None, net_letter_px=16, max_pixels=MAX_PIXELS)` | int, 1 or more | Nothing | 1 within the budget; with a letter height, the largest factor that keeps letters at least twice `net_letter_px` tall |
| `load_reduced(path, key=None, crop=None, letter_px=None, net_letter_px=16, max_pixels=MAX_PIXELS, progress=None)` | `(float32 image, k, (H, W) of the input window)` | As `load_image` | Block-averages in row bands that follow the file's tiles; pass k to `read` as `input_scale` |
| `normalize(a, polarity='bright', dtype=np.float64)` | float32 array in 0 to 1, ink bright | `ValueError` for an image with no finite values or a bad polarity | Robust scaling between the 0.5th and 99.8th percentiles; `dark` inverts |
| `resolve_polarity(lo, med, hi, polarity='auto')` | `"bright"` or `"dark"` | `ValueError` for a polarity other than bright, dark or auto | The grey-level guess `POLARITY_RULE`, used only without a reader |
| `normalize_info(a, polarity='bright', dtype=np.float64)` | `(image, info)`; info has `asked`, `used`, `background` and, for auto, `rule` | As `normalize` | |
| `normalize_for_reading(a, polarity='bright', max_pixels=MAX_PIXELS, with_info=False)` | image, or `(image, info)` | As `normalize` | float64 arithmetic within the budget, float32 above |
| `polarity_trial(a, weights, polarity='bright', *, letter_px=None, input_scale=1, seed=0, columns='auto', deskew_deg=DESKEW_DEG, lines=None, rotate=0, mirror=False, letter_px_fallback=True, min_letters=MIN_LETTERS)` | dict `rule`, `letter_px`, `bright`, `dark`, `choice` | `ValueError` for a polarity other than bright or dark, or no letter size with `letter_px_fallback=False` | Quick reads both ways: up to 8 lines, 2 nulls; per polarity `letters_kept`, `null_letters_kept`, `margin`, `status` |
| `normalize_auto(img, weights, max_pixels=MAX_PIXELS, **trial_kw)` | `(image, info)`, info with `trial` | As `polarity_trial` and `normalize` | Polarity auto for a whole read |
| `polarity_hint(trial, used)` | str, or `None` | Nothing | A hint when the other polarity reads `strong` and better |
| `letter_px_from_units(letter_mm, um_per_px)` | float, letter height in pixels | `ValueError` when either is missing or not positive | mm x 1000 / um |
| `resize(a, shape)` | float32 array of `shape`, each side at least 1 px | Nothing | Area average by an integer factor, then bilinear |
| `line_pitch(a, lo=8)` | int pixels, or `None` | Nothing | First autocorrelation peak above 0.15 of the row profile |
| `shear(a, deg, fill=0.0)` | array of a's shape | Nothing | Vertical shear about the middle column |
| `deskew_angles(max_deg=DESKEW_DEG, step=DESKEW_STEP)` | numpy array of angles in degrees | Nothing | Symmetric about 0, both limits included |
| `deskew_at_limit(angle, max_deg=DESKEW_DEG, step=DESKEW_STEP)` | bool | Nothing | True when the chosen angle is an end of the search |
| `deskew(a, h, max_deg=DESKEW_DEG, step=DESKEW_STEP, fill=0.0)` | `(angle, sheared image)` | Nothing | The angle whose smoothed row profile has the largest variance |
| `orient(a, rotate=0, mirror=False)` | array (a itself when neither is asked) | `ValueError` for a rotate other than 0, 90, 180, 270 | Mirror first, then turn clockwise |
| `view_box_to_input(box, rotate, mirror, shape)` | `[y0, y1, x0, x1]` rounded to 0.1 | Nothing | A box in the turned image mapped back to the input |
| `compose_view(rotate, mirror, name)` | `(rotate, mirror)` | `KeyError` for a name not in `ORIENTATIONS` | The turn that reads the input as an orientation read did |
| `find_lines(a, h, pitch)` | sorted list of rows | Nothing | Row-profile peaks at least 0.7 pitch apart |
| `find_columns(a, h, min_gap=2.0, n=None, level=0.05, min_width=3.0)` | list of `(x0, x1)` | Nothing | Gutters near empty in every row; no span narrower than 3 letter heights |
| `null_images(a, h, n=4, seed=0)` | list of `(kind, image)`, kind `tile_shuffle` or `phase` | Nothing | Both keep the image's grey levels |
| `read_bands(net, a, ys, h)` | list of (T, K) log-probability arrays | Nothing | One band per line centre |
| `as_image(img, name='image')` | 2D array | `TypeError` for a file name; `ValueError` for non-numbers, a wrong shape or an empty image | Size-1 axes dropped; (H, W, 3 or 4) averaged to grey |
| `check_control(c, name='the control image')` | `None` | `ValueError` when `c` has no finite values or they are all the same | Checks in row bands of about 4 million pixels, without copying a big map; `read` and `analyze` call it on `control`, the command line on `--control` |
| `check_options(*, letter_px=None, polarity='bright', columns='auto', nulls=4, seed=0, min_letters=MIN_LETTERS, deskew_deg=DESKEW_DEG, rotate=0, input_scale=1, p_min=None, null_rate=0.05, lm_weight=None, beam=32, lines=None, shear_fill=None, **_)` | `None` | `ValueError` naming the option and what to give | What `read` and `analyze` check first; `letter_px / input_scale` must be at least `MIN_LETTER_PX` (4) and `nulls` at most `MAX_NULLS` (64) |
| `lm_info(lm)` | dict `file`, `sha256`, `order`, or `None` | Nothing | |
| `read_options(kw, **extra)` | dict of every name in `OPTION_NAMES` with its value used | Nothing | The result's `options` |
| `provenance(net, seed=0)` | dict `schema`, `reader`, `weights`, `seed` | Nothing | |
| `estimate_letter_px(a)` | `(px, how)`, how `"line pitch"` or `"image height / 4"` | Nothing | Line pitch over `PITCH_PER_H` (6.6 / 3.5) |
| `analyze(img, weights, *, letter_px=None, polarity='bright', nulls=4, seed=0, deskew_deg=DESKEW_DEG, lines=None, p_min=None, null_rate=0.05, lm=None, lm_weight=None, beam=32, scale_search=True, columns='auto', normalized=False, input_scale=1, letter_px_fallback=True, progress=None, control=None, min_letters=MIN_LETTERS, shear_fill=None)` | The result dict without orientation | `ValueError` for a bad option, no letter size (with `letter_px_fallback=False`) or a control of another shape, with no finite values or constant; `TypeError` for a file name; as `load_weights` | One read with nulls, columns, deskew, scale search and control map |
| `deskew_warning(res)` | str, or `None` | Nothing | |
| `verdict(n, null_n)` | str, one of four fixed sentences | Nothing | The old wording kept in `control.verdict`; more than 3 times is "well above" |
| `control_status(n, null_n, control_n=None, min_letters=MIN_LETTERS)` | `"strong"`, `"weak"`, `"none"`, `"too_few"` or `"no_control"` | Nothing | The rule under Checks and controls |
| `control_report(n, null_n, control_n=None, min_letters=MIN_LETTERS)` | dict `letters_kept`, `null_letters_kept`, `min_letters`, `ratio`, `status`, `status_text`, and `control_map` with a control | Nothing | |
| `status_line(c, sentence=True)` | str | Nothing | The `status:` line of the summary |
| `letter_px_check(a0, letter_px, input_scale=1)` | dict `line_pitch_estimate`, `ratio` and, beyond 2 times either way, `warning`; or `None` without a pitch | Nothing | |
| `read(img, weights, *, orientation=True, normalized=False, progress=None, control=None, rotate=0, mirror=False, polarity_info=None, **kw)` | The full result dict (the fields under Outputs) | `TypeError` for an unknown option or a file name; as `analyze` | `analyze` plus the turned reads, the polarity check after a failed read and boxes mapped back to input pixels |
| `trial_text(trial)` | str | Nothing | |
| `text_summary(res)` | str | Nothing | What the command prints without `--json` |
| `provenance_line(res)` | str | Nothing | |
| `view_options(rotate, mirror)` | str, such as `"--rotate 90 --mirror"`, or `""` | Nothing | |
| `banner_text(res)` | str | Nothing | `NOTE`, then `Controls: ` and the status line |
| `banner_layout(width, text=NOTE)` | `(font, lines, line height, top offset, canvas width)` | `ImportError` without Pillow | |
| `overlay_geometry(shape, res, max_side=OVERLAY_MAX_SIDE)` | dict `scale`, `banner_rows`, `size`, `max_side` | `ImportError` without Pillow | A box edge at input row y lands at overlay row banner_rows + y x scale |
| `overlay(img, res, path, polarity='bright', max_side=OVERLAY_MAX_SIDE, normalized=False, base=None)` | path | `ValueError` for a base of another size; `ImportError` without Pillow; `OSError` on write | Kept letters green at p 0.8 or more, yellow below; letters under the floor grey boxes without glyphs |
| `image_frame(res, image_shape=None)` | `(oy, ox, H, W)` | `ValueError` for a crop read without the whole image's size | In `kit/letterexport.py`, as are the rows below |
| `letter_rows(res, image_shape=None)` | list of dicts with `CSV_FIELDS` | As `image_frame` | Boxes in the image file's pixels |
| `letters_csv(res, image_shape=None)` | str | As `image_frame` | |
| `write_csv(res, path, image_shape=None)` | path | As `image_frame`; `OSError` | UTF-8, no byte-order mark |
| `view_points(res, line)` | `(band corners, baseline)` as (y, x) points | Nothing | One letter height around the line, following the column's deskew |
| `to_image_points(res, pts, frame, turned=True)` | list of integer `(x, y)` clipped to the image | Nothing | |
| `page_xml(res, image_filename=None, image_shape=None, created=None)` | str | As `image_frame` | PAGE XML 2019-07-15; `created` defaults to now, UTC |
| `write_page_xml(res, path, image_filename=None, image_shape=None, created=None)` | path | As `page_xml`; `OSError` | UTF-8 |

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Image | 2D array in `.npy`, `.npz`, TIFF, PNG, JPEG or zarr (an array, a group with one array, or an OME-Zarr group, level 0 by default) | Any numeric dtype. Colour becomes grey. Exactly one non-singleton 2D plane, or a colour plane with 3 or 4 channels last. A `.npy` and an uncompressed TIFF are memory-mapped; a zarr, or a compressed tiled TIFF with zarr installed, is read by chunk; a `.npz`, PNG or JPEG is decoded whole |
| Ink polarity | `--polarity` | Ink maps and labels are bright ink (the default); photographs of papyrus are dark ink (`dark` or `auto`) |
| Letter height | `--letter-px`, or `--letter-mm` with `--um-per-px` | In input pixels. The guide's [Letter size matters most](../letter-reader.md#letter-size-matters-most) gives sizes for public maps, such as 86 px on PHerc. 1667's map averaged to about 38 um |
| Control map | Same formats, same shape after `--crop` and `--key` | Such as the reverse-depth map villa writes with `--direction both` |
| Weights | A released name, or a `linenet-v1` `.npz` | Released: `letters-v2-ccby` and `letters-v2-real`, both 1,483,241 parameters at a working letter height of 16 px ([`letter-weights.json`](../../kit/data/letter-weights.json)) |
| Language model | `.npz` from `python -m kit greeklm build` | Optional |

Coordinates: rows down, columns right, in input pixels (the image file's pixels after EXIF orientation, relative to the crop's Y0 and X0). Boxes are `[y0, y1, x0, x1]`. Size: an image over `--max-mpx` (64 million pixels by default) is block-averaged while it loads, and everything is reported back in input pixels.

## Outputs

These fields describe the default LineNet backend. It adds `backend` with id/language/script and, when a task profile selects the weights, `weight_profile` with the profile's licence and evidence. Tesseract instead emits `schema: "scrolls-ocr-v1"`, word confidences and separate controls; see [its output contract](reader-backends.md#outputs). Its result must not be parsed as Greek letter confidences or treated as `control.status: strong`.

Without `--json` it prints the text summary (see Quick start): the model-output note, a provenance line, the letter height and floor, the scale-search table when the size was estimated, any warnings, one line per text line (`line N y=ROW [K kept, chance C]: LETTERS`, `·` for a letter under the floor), per-column statuses when there are several columns, then the `control:`, `control map`, `status:` and `orientation:` lines. With `--json` it prints the full result instead. `--out` writes the same JSON. Main fields (every field: [The result, field by field](../letter-reader.md#the-result-field-by-field)):

| Field | Type | Meaning |
| --- | --- | --- |
| `note` | str | `NOTE`: model output, not a reading |
| `schema` | int | Result schema, 1 (`SCHEMA`) |
| `reader.module`, `reader.version` | str | `kit.letterread` and the package version |
| `weights.name`, `.file`, `.sha256`, `.format` | str or null | The released name (null for other weights), file name, SHA-256 and `linenet-v1` |
| `seed` | int | Seed of the nulls |
| `engine` | str | `linenet` |
| `letter_px` | float | Letter height read at, input pixels |
| `letter_px_from`, `letter_px_estimated` | str, bool | `given`, or `line pitch, then scale search` (or `image height / 4, ...` from Python) |
| `letter_px_first_guess`, `scale_search` | float, list | When estimated: the first guess and per scale `letter_px`, `letters_kept`, `null_letters_kept`, `margin` |
| `letter_px_check` | object | With a given size: `line_pitch_estimate`, `ratio`, and `warning` beyond 2 times |
| `working_scale` | float | Network pixels per input pixel |
| `p_min` | float | Confidence floor used |
| `lines[]` | list | Per line: `line`, `column`, `y` (row at the column's middle), `ink_only`, `n_kept`, `chance`, `control_map_kept` (with a control map), `with_lm` (with `--lm`), and `letters[]` |
| `lines[].letters[]` | list | Per letter: `glyph`, `p` (0 to 1), `kept` (p at or above `p_min`), `box` `[y0, y1, x0, x1]` in input pixels, and `view_box` after a turned read |
| `columns[]` | list | Per column: `x0`, `x1`, `deskew_deg`, `deskew_at_limit`, `lines`, and its own `control` block with `chance` |
| `control` | object | `letters_kept`, `null_letters_kept`, `nulls` (`kind`, `letters_kept`), `verdict`, `min_letters`, `ratio` (to the largest null, null when no nulls), `status`, `status_text`, and `control_map` (`letters_kept`, `ratio`, `file`) with `--control` |
| `orientation` | object | `letters_kept` for `as_is`, `mirrored`, `rot180`, `rot90`, `rot270`; `best`; `best_view` (`rotate`, `mirror`) |
| `polarity` | object | `asked`, `used`, `background`, and `trial` (with `hint`) when auto decided or the controls did not pass |
| `deskew_deg`, `deskew_max_deg`, `deskew_warning`, `shear_fill` | float, str | First column's angle, the search limit, a warning at the limit, the grey of sheared-in rows |
| `input_shape`, `image_shape`, `input_scale`, `reduced_shape` | list, int | The input window, the whole image, the block size k, and what was read when k is above 1 |
| `source` | object | `file` (name only, never a folder) and `key` |
| `crop`, `letter_mm`, `um_per_px`, `exif_orientation`, `view` | various | Present when used |
| `overlay` | object | With `--overlay`: `file`, `scale` (overlay pixels per input pixel), `banner_rows`, `size` [width, height], `max_side` |
| `options` | object | Every option used, with `max_mpx`, `rotate`, `mirror`, `orientation`, `control_map` and `lm` |

`--csv` writes the header `column,line,index,letter,p,kept,y0,y1,x0,x1` and one row per decoded letter (`kept` is `true` or `false`), in the image file's pixels. `--page-xml` writes a PAGE 2019-07-15 file whose Metadata comments carry the model-output note and the status; a glyph under the floor has `·` as its text and its best letter in its comments. `--overlay` writes the picture.

| Exit code | Meaning |
| --- | --- |
| `0` | The read finished and every file asked for was written. Any status, including `none` and `too_few`, exits 0: check `control.status` |
| `1` | An error the command does not catch, with a Python traceback |
| `2` | A bad option or input, a missing package, a failed weights download, or out of memory, with the message on stderr and no read; or a usage error from the argument parser. Also when the read finished but an output file could not be written: the result is still printed, and the error follows on stderr |

## Failure modes

Routing and weight selection can also fail before reading:

| Message | Cause and action |
| --- | --- |
| `--tessdata and --ocr-* options require --backend tesseract` | Select Tesseract explicitly or remove its options |
| `unknown weight profile` | Choose ink-lines or permissive |
| `weight profile ... names unregistered weights` | The registry is invalid; do not substitute a different model |
| `choose --weights or --weight-profile, not both` | Make one explicit selection |

Tesseract's capability, language, input and timeout failures are on the [backend page](reader-backends.md#failure-modes). Nondefault LineNet options unsupported by Tesseract fail; word output cannot use the glyph exporters.

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument, such as no `--weights` | Check the command against Commands and options |
| `give the letter height once: --letter-px, or --letter-mm with --um-per-px` | Both size forms given | Give one |
| `give the letter height in millimetres and the pixel size in micrometres together (--letter-mm MM --um-per-px UM)` | `--letter-mm` without `--um-per-px`, or the reverse | Give both |
| `letter height (MM mm) and pixel size (UM um) must both be positive` | A zero or negative unit | Fix the values |
| `--letter-px PX: give the letter height in image pixels, at least 4 (the network reads letters 16 px tall, so smaller letters have no shape left to read)` | `--letter-px` under 4 (`MIN_LETTER_PX`), refused before any work | Give the height of a letter in image pixels; a block-averaged map's letters are still given in input pixels |
| `--letter-mm MM at --um-per-px UM is a letter PX px tall, under the 4 px the reader can read; check the units (the letter height in millimetres, the pixel size in micrometres)` | The two values give a letter under 4 px, usually a unit mix-up (such as 0.1 mm at 38.4 um, 2.6 px, seen 2026-10-16) | Give the letter height in millimetres and the pixel size in micrometres |
| `--max-mpx must be positive and --overlay-max-side at least 16` | A bad budget or overlay size | Use the defaults, 64 and 4000 |
| `--min-letters N: give at least 1` | `--min-letters` 0 or less | Keep 10; do not lower it to get a pass |
| `--deskew DEG: give an angle from 0 (off) to under 45 degrees` | Out of range | Use 0 to 44 |
| `--nulls must be 0 to 64, --beam at least 1 and --lm-weight 0 or more` | A negative count or weight, or more than 64 nulls (`MAX_NULLS`) | Fix the value; 4 nulls is the default |
| `--p-min P: give a confidence from 0 to 1` | Out of range | Leave it out to set it from the nulls |
| `--columns C: give auto, off or a number of columns, at least 1` | Not `auto`, `off` or a whole number | Fix it |
| `--overlay needs Pillow: ...` | Pillow is not installed | `python -m pip install pillow`, or the `reader` extra |
| `--overlay FILE: give an image file name such as letters.png` | An extension Pillow does not write | Use `.png` |
| `no such folder for FILE` | An output's folder does not exist (checked before the read) | Make the folder or fix the path |
| `IMAGE: no such file or folder` | The image, the control map or a zarr path does not exist | Fix the path |
| `SPEC: no such file, and not a released model (letters-v2-ccby, letters-v2-real)` | `--weights` is neither a released name nor a file | Use a released name, or the path of a `linenet-v1` file |
| `SPEC: a folder, not a linenet-v1 weights file` | `--weights` names a folder | Give the file |
| `SPEC: has the file name of the released model NAME but not its SHA-256 SHA, so it is damaged or another file; download it again (python -m kit letterread IMAGE --weights NAME does), or rename it if it is weights of your own` | A local file named like a release with other contents | Pass the release's name instead, or rename your own file |
| `PATH: not a linenet-v1 weight file` | An `.npz` that is not exported reader weights | Give weights from `scripts/letters/train_linenet.py --export` |
| `NAME: no download address yet; download FILE by hand ...` | A registry entry without a URL | Copy the file into the cache folder the message names |
| `could not download the weights NAME from URL into FOLDER: ERROR. Check the connection and retry, or download FILE by hand ...` | No network, a proxy or a certificate problem (a `WeightsError`) | Retry, set `HTTPS_PROXY` or `SSL_CERT_FILE`, or download by hand and set `KIT_LETTER_WEIGHTS` ([guide](../letter-reader.md#networks-proxies-and-offline-machines)) |
| `NAME: download from URL does not match its SHA-256; nothing kept. Retry, or download FILE by hand ...` | A damaged or swapped download | Retry; nothing was kept |
| `NAME: PATH does not match its SHA-256 SHA; delete it and retry, or download FILE by hand ...` | The cached file or the `KIT_LETTER_WEIGHTS` folder's file is damaged | Delete it and run again |
| `NAME: not in FOLDER` | Python only: `resolve_weights(..., download=False)` with nothing cached | Allow the download or copy the file in |
| `weights SPEC: give a released model name (letters-v2-ccby, letters-v2-real), a path to a linenet-v1 .npz file, or a LineNet` | Python only: weights of another type | Pass a name, a path or a `LineNet` |
| `unknown layer op 'OP'` | A weights file from a newer exporter | Update the package |
| `no letter size: the image shows no regular line spacing to estimate it from. Give the letter height with --letter-px H (image pixels), or with --letter-mm MM and --um-per-px UM (for example --letter-mm 3.3 --um-per-px 38.4), or read a window that holds several lines with --crop Y0 Y1 X0 X1` | No line pitch and no size given (the command line never falls back to a quarter of the height) | Give the size, or crop to several lines |
| `--control FILE: H x W px, but the image is H x W; give a map of the same surface on the same grid (such as its reverse-depth map)` | The control map has another shape (seen on synthetic inputs, 2026-10-16) | Use the map of the same surface and grid |
| `the control image is H x W px but the image is H x W; give a map of the same surface on the same grid (such as its reverse-depth map), cropped the same way` | Python only: a control of another shape | Same as above |
| `--control FILE is constant (every finite value is V): a constant map keeps no letters, so as a control it could never fail. Give a map of the same surface with its own content, such as its reverse-depth map, or read without a control map` (from Python, `the control image is constant ...`) | Every finite value of the control map is the same | Give the real reverse-depth map of the surface, or read without `--control` |
| `--control FILE has no finite values: it can keep no letters, so as a control it could never fail` (from Python, `the control image has no finite values ...`) | The control map is all NaN or infinite | Same as above |
| `IMAGE: expected a 2D image, got shape (...)` | A file with more than one 2D plane, such as a layer stack | Pass one 2D map |
| `image: expected a 2D image (H, W), or a colour image (H, W, 3 or 4) with its channels last; got shape (...)` | Python only: an array of another shape | Pass a 2D array |
| `image: expected an array of numbers, got one of DTYPE` | Python only: strings or objects | Pass numbers |
| `image 'PATH': read() and analyze() take an image array; read a file with load_image(path) or, for a big map, load_reduced(path) (its block size goes in as input_scale)` | Python only: a file name passed to `read` | Load it first |
| `read(): unknown option NAME; the options are ..., orientation, normalized, progress, control, rotate, mirror and polarity_info` | Python only: a misspelt keyword | Use a listed option |
| `OPTION VALUE: WHAT TO GIVE` (such as `nulls -1: give a whole number of null copies from 0 to 64 (4 is the default; 0 runs no control)`, or `letter_px 3: letters under 4 px tall in the image read are too small to read (the network reads letters 16 px tall); give the height of a letter in image pixels`, with `, here at least N input pixels with input_scale K` for a block-averaged image) | Python only: `check_options` refuses a value for `letter_px`, `polarity`, `columns`, `nulls`, `seed`, `min_letters`, `deskew_deg`, `rotate`, `input_scale`, `p_min`, `null_rate`, `lm_weight`, `beam`, `lines` or `shear_fill` | Give what the message asks |
| `IMAGE: the image is empty (0 x W px)` | An empty image or array | Check the file |
| `IMAGE: crop [...] is empty for an image of shape (H, W)` | `--crop` outside the image | Fix the crop |
| `rotate R: give 0, 90, 180 or 270 (degrees clockwise)` | Python only: another angle | Use a quarter turn |
| `polarity 'P': give bright, dark or auto` | Python only: another polarity name | Use one of the three |
| `polarity 'P': the image's own polarity, bright or dark` | Python only: `polarity_trial` given auto | Give bright or dark |
| `image has no finite values` | An all-NaN or all-infinite image | Check the map |
| `IMAGE: reading zarr needs the zarr package (python -m pip install zarr)` | zarr is not installed | Install zarr |
| `IMAGE: a single zarr array, so --key KEY does not apply` | `--key` on a zarr array | Drop `--key` |
| `IMAGE: a zarr group with arrays [...]; pick one with --key (an array path, or an OME-Zarr level such as 0)` | A group with several arrays and no OME metadata | Give `--key` |
| `IMAGE: no array 'KEY' in this zarr (arrays: ...)` | A wrong `--key` | Use one of the listed arrays |
| `IMAGE: 'KEY' is a zarr group, not an array; give its level, such as KEY/0` | `--key` names a group | Add the level |
| `'KEY is not a file in the archive'` | `--key` names no array of the `.npz` | Use an array name of the file |
| `No module named 'numpy'; python -m pip install numpy pillow tifffile imagecodecs (the reader extra's packages)` | numpy, Pillow, tifffile or imagecodecs is missing (`import_advice` adds the install line) | Install them, or the `reader` extra from a clone (`python -m pip install -e ".[reader]"`) |
| `...; python -m pip install zarr (Python 3.11 or newer)` | zarr is missing for a zarr input | Install zarr |
| `out of memory reading IMAGE. Give the letter size (--letter-px, or --letter-mm with --um-per-px) so a big image is block-averaged while it loads, lower the budget with --max-mpx, or read a window with --crop Y0 Y1 X0 X1.` | A big image without a letter size | Do what it says |
| `out of memory reading IMAGE. Its letters (PX px tall) are too small to block-average (that needs letters at least 64 px tall), so the image is loaded whole: read a window with --crop Y0 Y1 X0 X1, or check the letter size.` | Letters under twice the network's height cannot be averaged | Crop a window, or check the size |
| `this result was read from a --crop window and does not record the whole image's size (image_shape); give image_shape=(H, W) of the image file` | Python only: exporting a crop read without its image size | Pass `image_shape` |
| `overlay base is H x W px but the image is H x W` | Python only: an overlay base of another size | Pass a base of the read image's size |
| Status `none` or `too_few`, exit code 0, maybe with `hint: this image reads better as ...` | Wrong letter size or polarity, too small an area, or no text the model can see | Follow the [status table](../letter-reader.md#the-status-and-what-to-do): check the size, the polarity, read a larger area |
| `warning: the deskew angle ... is the limit of its search ...` | The lines may be tilted more than `--deskew` | Read again with a larger `--deskew`, or `--rotate` |

## How it works

1. **Check** every option, the output folders and the input paths; load the weights (a released name resolves to the cache file, downloaded once and SHA-256 checked).
2. **Load** the image (`load_reduced`). Over the budget (`MAX_PIXELS` = 64,000,000) it is block-averaged by an integer k in row bands of `BAND_PIXELS` (64,000,000 input pixels) that follow the file's tiles; with a letter size, k keeps letters at least 32 px tall (twice the network's 16 px).
3. **Normalise** once (`normalize_for_reading`): clip between the 0.5th and 99.8th percentiles to 0..1, inverted for dark ink. With `auto`, `polarity_trial` reads both ways once (up to 8 lines, 2 nulls) and keeps the larger margin over its nulls (`AUTO_RULE`).
4. **Letter size.** Given (at least `MIN_LETTER_PX`, 4 px, in the image read), or estimated from the first autocorrelation peak of the row profile divided by `PITCH_PER_H` (6.6 / 3.5, about 1.89 letter heights per line) and raised to 4 px when smaller, then a scale search at `SCALE_STEPS` (0.5, 0.63, 0.8, 1.0, 1.25, 1.6) times the guess, each size raised to 4 px and each distinct size read once, with 2 nulls on up to 8 lines, keeping the largest margin of letters over the largest null. The polarity trial also never reads under 4 px.
5. **Layout.** Resize to the network's 16 px letters, split columns at gutters (`find_columns`), deskew each column by the shear in steps of 0.5 degrees up to `--deskew` that makes its row profile most peaked, and find line rows as row-profile peaks at least 0.7 pitch apart.
6. **Read.** Each line band (a fixed number of letter heights around the row, `band_rows`) goes through the numpy network: 2D convolutions with BatchNorm folded in, a collapse to one row, dilated 1D residual convolutions and a 25-way CTC head (24 capitals with lunate sigma, plus the blank). Best-path decoding gives letters, confidences and frame spans; boxes widen each span by 0.3 letter heights and undo the shear.
7. **Controls.** Read the nulls (`null_images`) on the same lines, set the floor, count kept letters per line, column and read, read the control map on the same lines and floor, and set each status (`control_status`). Then, in `read`, the four turned reads at the same floor with no nulls, and, after a `none` or `too_few` read in a fixed polarity, the quick read both ways with a hint.
8. **Report** every row, box and size in input pixels (through k and any turn), with the provenance first and the options last.

The method and its reasons: [How it works](../letter-reader.md#how-it-works) and [Why these rules](../letter-reader.md#why-these-rules) in the guide. The PAGE export follows PRImA's 2019-07-15 schema (`PAGE_NS` in `kit/letterexport.py`).

## Cost and time

- Synthetic page of 301 x 1,006 px with `--letter-px 32`, a control map, the orientation reads, three exports and an overlay: 4.0 s wall, 13.4 s CPU (measured 2026-10-16, 4-core 2.8 GHz Xeon cloud container, weights cached).
- Whole 2.4 um PHerc. 1667 w013 map, 41,600 x 79,600 px, block-averaged by 43 with `--letter-px 1376` and an overlay: 35 to 36 s and about 250 MB peak with zarr; about 3.7 GB peak without zarr. The same map averaged 16 by 16, 2,600 x 4,975 px: 20 to 23 s and 420 MB (14 October 2026, 4-core cloud container, 2 threads; [Big maps](../letter-reader.md#big-maps)).
- The weights download is 5,933,674 bytes, once.

It runs on a laptop CPU and needs no GPU and no Modal. Peak memory for a large image without a letter size: Not measured beyond the cases above.

## For agents

The guidance below concerns LineNet. For Tesseract use its [agent contract](reader-backends.md#for-agents); `above_controls` never means a verified reading. Always preserve explicit caller weight choices, and include the selected profile's licence when reporting an automatic choice.

- **Command:** `python -m kit letterread IMAGE --weights letters-v2-ccby --letter-px PX --control MAP_REVERSE --json --quiet`; add `--out RESULT.json --csv LETTERS.csv --page-xml LETTERS.xml --overlay LETTERS.png` for files. Set `KIT_LETTER_WEIGHTS` to a folder or file when the cache must live elsewhere.
- **Parse:** `control.status` (`strong`, `weak`, `none`, `too_few`, `no_control`), `control.letters_kept`, `control.null_letters_kept`, `control.control_map.letters_kept`, per column `columns[].control.status`, per line `lines[].ink_only`, `n_kept` and `chance`, per letter `glyph`, `p`, `kept`, `box`; `weights.sha256` and `options` for provenance.
- **Rerun:** Safe and deterministic for the same image, weights, options and seed. It overwrites `--out`, `--csv`, `--page-xml` and `--overlay`; the weights download happens once.
- **Success:** Exit code 0 and `control.status` of `strong`. Exit code 0 alone only means the read finished.
- **Not a pass:** `weak` (a text-free page can be `weak`), `none`, `too_few`, `no_control`; any read with `--nulls 0`; an ink map read without its reverse-depth `--control`; a `strong` read on a segment whose labels or maps trained the ink model, which may be cleaner than new text; lines chosen afterwards because they beat `chance`; any read at an estimated letter size that the scale-search table does not support.
- **Go-ahead:** Nothing to read public data. Posting a read needs Chase's yes, and a read of a prize-eligible or unpublished scroll never goes public before the prize is announced.
- **Never:** Call its output a reading or say letters were found or read; put an overlay in a prize image (they carry machine letter annotations); commit weights, maps or reads of target scrolls to this repository; lower `--min-letters` or `--p-min` to get a pass.

## Tests

```bash
python -m unittest tests.test_letterread tests.test_letterexport -v
```

`tests/test_letterread.py` covers the numpy network against a torch export (skipped without torch), CTC decoding with and without a language model, forced alignment, nulls, line and column finding, deskew, normalisation and polarity (auto, the trial, the hint), big images block-averaged in every format including zarr and OME-Zarr levels, the letter size in units and its check, the status codes and the control map, turned, mirrored and EXIF-turned reads, the overlay, the released weights (download once, SHA-256 refusal, nothing kept on a bad or interrupted download, names before paths, `KIT_LETTER_WEIGHTS`), the Python API's checks and provenance, the command line's errors and file order, and UTF-8 output. They use small random weights, not the released ones. `tests/test_letterexport.py` (6 tests, 2.0 s on 2026-10-16) checks the CSV and PAGE XML in input pixels, turned and two-column reads, crops and block-averaged reads. `tests/test_letter_scripts.py`, `tests/test_letterlines.py`, `tests/test_letterdemo.py` and `tests/test_packaging.py` use the reader from the scripts, `letterlines`, the demo and the console scripts. They skip without numpy. They do not measure accuracy on real maps; the benchmark scripts do (see [letters-training](letters-training.md)). The run time of `tests/test_letterread.py` was Not measured here.

## History

- 2026-10-17: working change against `869d621`, explicit local multilingual backend routing with word provenance and controls; task-aware Greek weight profiles while preserving explicit weights and released model hashes.

- 2026-10-16: speed-ups with bit-identical output: LineNet's max pooling by strided slices (one 36 x 1200 band 148.2 ms to 77.8 ms, per the commit), `shear` by runs of columns (deskew of a 630 x 1200 image 384 ms to 40 ms, per the commit), and `normalize_info` skipping the median fill when every pixel is finite (`b48258d`, `4a31ee5`, `45269ca`, `9e2a16e`).
- 2026-10-16: the missing-package hint names numpy, pillow, tifffile and imagecodecs instead of `scrolls-workbench[reader]`, which is not on PyPI (`00c25f5`).
- 2026-10-16: refuses a constant control map or one with no finite values (`check_control`), which could never fail and let a read end `strong`; letter heights under 4 px (`MIN_LETTER_PX`) and more than 64 nulls (`MAX_NULLS`); the scale search and polarity trial never read under 4 px; `resize` keeps each side at least 1 px, so a strip a few pixels tall no longer stops with a division by zero (`c58cdab`).
- 2026-10-14: `letters-v2-ccby` (CC BY 4.0) becomes the default weights of the demo and guide; `letters-v2-real` stays released (`0366ed7`).
- 2026-10-14: fixes from the usability review (`ca7b143`).
- 2026-10-14: CSV and PAGE XML exports (`kit/letterexport.py`, `--csv`, `--page-xml`) (`33a0ad3`).
- 2026-10-14: a Python API with checked options, provenance on every result, sturdier weights downloads and UTF-8 output (`203018a`).
- 2026-10-14: turned, mirrored and tilted text, and photographs (`--rotate`, `--mirror`, `--deskew`, `--polarity auto`, EXIF orientation) (`c502445`).
- 2026-10-14: a status code per read and column, the control map (`--control`) and per-line chance counts (`05c59cc`).
- 2026-10-14: whole native maps block-averaged while loading, letter size in millimetres, a clearer overlay (`beb0ad8`).
- 2026-10-14: first public release with guide, model card, benchmarks and demo (`19d2f95`, [PR #57](https://github.com/ChaseHendrick/Scrolls/pull/57)).

## Related

- [letter-reader.md](../letter-reader.md): the guide, with install, first reads, model cards, benchmarks and every result field.
- [letterdemo](letterdemo.md): the offline install check on synthetic letters.
- [letterlines](letterlines.md): training lines from your own transcriptions, and scores on lines kept apart.
- [greeklm](greeklm.md): builds the optional letter language model for `--lm`.
- [letters-training](letters-training.md): the training, fine-tuning and benchmark scripts behind the weights and the numbers.
- [workbench-package](workbench-package.md): the installable package and its `scrolls-letterread` console script.
- [The letter reader log](../logs/2026-10-14-letter-reader.md) and `letter_reader_checks` in [`results.json`](../results.json): the measured numbers and their conditions.
