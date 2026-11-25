# greekpages: synthetic Greek book-hand pages for training letter readers

Synthetic pages of Greek majuscule text drawn as a reader's ink map would show them, with exact letter labels.

| Field | Value |
| --- | --- |
| Id | `greekpages` |
| Status | Experimental |
| Kind | kit module |
| Area | Letters and titles |
| Run | `python -m kit.greekpages gen OUT --text TEXT`, `python -m kit.greekpages preview PAGE.npz OUT.png`, `python -m kit.greekpages style`, `python -m kit.greekpages info` |
| Code | `kit/greekpages.py` |
| Tests | `tests/test_greekpages.py` |
| Needs | Python 3.10 or newer, numpy, scipy; Pillow for `preview`; a Greek text (UTF-8 .txt) of your choice |
| Runs on | CPU: about 2 s for one 512 px page on one core of a 4-core cloud container (measured 2026-11-25) |
| Network | None |
| Writes | `gen`: `OUT/page-SEED-I.npz`; `preview`: one PNG |
| Go-ahead | Not needed |
| Released | Public, with the November 2026 Progress Prize entry (pending) |
| Checked | 2026-11-25 against commit `bd011dc` |

## What it does

Letter readers for the Herculaneum scrolls have few labelled letters to learn from. `greekpages` draws as many pages as you want of Greek text in a book hand, as an ink-detection model's probability map would show them, and labels every page exactly: the clean ink mask, each letter's box and character, the text drawn and every parameter used.

A page is built in three layers. A **hand** draws the letters: plain bilinear majuscule shapes (24 letters, lunate sigma) with a broad nib whose width follows the stroke direction against the pen angle, plus letter height, width, spacing, slant, baseline and ink-load variation. A **map model** degrades the ink the way a reader's map does: patchy dropout, a smooth warp, anisotropic blur and a saturating tone curve. A **background** adds procedural papyrus: a level, noise, fibres along one axis, blotches and thin non-letter strokes such as cracks.

The hand, map model and background are one **style**, and the style is pluggable. The default, `generic-bookhand`, uses plain letter shapes and wide ranges that are ASSUMED, measured on no particular scroll. Anyone can write their own style JSON with their own measurements of a hand or a scan: `python -m kit.greekpages style > my-style.json`, edit it, and pass `--style my-style.json`. Each value is a number, or a `[low, high]` pair drawn uniformly per page.

The text is pluggable too: any Greek text you have the right to use, as one .txt file or a folder of them. It is cleaned to the 24 classical majuscules with every sigma lunate, accents and breathings dropped, and written as scriptio continua. Keep any text you will evaluate a reader on out of the training text with `--exclude`.

Everything it makes is synthetic. A page is a training and testing aid; nothing it makes is a reading of any papyrus, and how closely the default style matches real ink maps has not been measured.

## When to use it

- To make labelled training pages for a letter reader or a letter-shape prior, as many as you need.
- To test a letter reader on pages where the true letters are known exactly.
- To model your own scribe or scan: put your measurements in a style file.

Do not use it:

- as evidence about a real scroll: score real maps against real labels;
- to make 3D CT or surfaces: use [scrollsim2](scrollsim2.md) or [hardcases](hardcases.md).

## Quick start

```bash
pip install scipy pillow
python -m kit.greekpages gen PAGES --text GREEK.txt --n 3 --seed 1
python -m kit.greekpages preview PAGES/page-1-00000.npz page.png
```

PAGES is any empty folder; GREEK.txt is any UTF-8 Greek text (a folder of .txt files also works). On 25 Nov 2026 with the first lines of the Iliad as text this printed `{"text": {"files": 1, "excluded": 0, "pieces": 1, "letters": 221}}`, three `PROGRESS` lines and `DONE 3 pages in PAGES` in about 7 s. Success: exit 0, three `.npz` files, and a PNG with the map on the left (letter boxes in blue) and the clean ink on the right.

## Checks and controls

The tests hold two checks that can fail: on a page with a clean style the map is at least 0.4 higher on the ink mask than off it, and with `ink_amp` set to 0 the same page shows no difference (under 0.05). Every page's letter boxes, characters and drawn text agree, and no ink pixel lies outside a letter box.

Scope: a generator, checked for correctness only (labels, determinism, ranges). Whether a reader trained on these pages reads real scroll maps better is untested; that needs a test on real labelled maps.

Claim label: Model output (synthetic pages); the default ranges are ASSUMED.

## Commands and options

### `python -m kit.greekpages`

| Option | Default | Meaning |
| --- | --- | --- |
| `gen OUT` | required | Write pages into the folder `OUT` |
| `--text` | required | A Greek .txt file or a folder searched for *.txt |
| `--exclude` | none | File names to leave out of the text, such as evaluation texts |
| `--n` | 100 | Pages to write |
| `--seed` | 1 | Run seed; page i uses seed SEED*100000 + i |
| `--style` | none (the generic book hand) | Style JSON with `hand`, `map` and `background` sections; keys you leave out keep their defaults |
| `--size` | 512 | Page side in pixels |
| `--px-mm` | 0.0288 | Pixel size in mm |
| `preview PAGE OUT` | required | Write a PNG of one page |
| `style` | | Print the default style JSON |
| `info` | | Print the constants and the alphabet as JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `PagesError()` | exception | Nothing | A refused input: bad style, no usable text, a bad page size |
| `default_style()` | dict | Nothing | The generic book hand, map model and background |
| `load_style(path=None)` | dict | PagesError | The default with the file's sections laid over it; unknown keys and bad ranges refuse |
| `draw(section, rng)` | dict | Nothing | One value per key: numbers as is, [low, high] pairs uniformly (integer pairs stay integers) |
| `clean_text(text)` | str | Nothing | Greek text to scriptio continua over the 24 letters, sigma lunate |
| `text_bank(path, exclude=(), min_len=40)` | (pieces, stats) | PagesError | Cleaned strings from a file or a folder of .txt files |
| `sample_lines(rng, pieces, n_lines, n_letters)` | list of str | Nothing | Consecutive lines from one random place in one random piece |
| `glyph_strokes(ch, step=0.01)` | (advance, list of (N, 2) arrays) | PagesError | Letter centrelines in letter units, y down, height 1 |
| `layout(lines, hand, rng, size_mm)` | list of (char, strokes in mm, load, line) | Nothing | Places letters on the page |
| `render_ink(placed, hand, size_px, px_mm)` | (ink, boxes, drawn text) | PagesError without scipy | Broad-nib letters drawn at twice the resolution and averaged down |
| `map_model(ink, mp, rng, px_mm)` | float32 array | Nothing | Dropout, warp, blur, tone |
| `background(size_px, bg, rng, px_mm)` | float32 array, 0 to 1 | Nothing | Procedural papyrus in probability space |
| `page(seed, pieces, style=None, size_px=512, px_mm=0.0288)` | dict map, ink, mask, boxes, text, params | PagesError | One page |
| `save_page(pg, path)` | None; writes PATH atomically | OSError | Compressed .npz |
| `load_page(path)` | dict as page() | OSError, KeyError | Reads a page written by save_page |
| `generate(out_dir, pieces, n, seed, style=None, size_px=512, px_mm=0.0288, progress=print)` | list of paths | PagesError, OSError | N pages; pages already written are kept |
| `preview(pg, path)` | None; writes a PNG | PagesError without Pillow | Map with boxes beside the clean ink |
| `build_parser(ap=None)` | argparse parser | Nothing | The command line |
| `main(argv=None)` | exit code | SystemExit on bad arguments | The command line |

## Inputs

A Greek text in UTF-8 (a .txt file, or a folder searched recursively for .txt files); pieces shorter than 40 letters after cleaning are dropped. A style JSON (optional): an object with any of the sections `hand`, `map`, `background` and the keys `name` and `about`; every value a finite number or a `[low, high]` pair. Units are in the key names (`_mm`, `_deg`, `_h` for multiples of the letter height).

## Outputs

Page `.npz`: `map` float16 (ink probability, 0 to 1), `ink` float16 (clean ink, 0 to 1), `mask` bool (clean ink above 0.2), `boxes` int32 (N, 4) as y0, x0, y1, x1 in pixels, `chars` (the N characters in box order), `meta` JSON (`text`: the letters drawn, one string per line; `params`: seed, pixel size, style name and every value drawn).

| Exit code | Meaning |
| --- | --- |
| `0` | Done |
| `1` | A refused input (PagesError) |
| `2` | Bad arguments |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `no text at` | `--text` names nothing | Give a .txt file or a folder of them |
| `no Greek text of at least ... letters in` | the text has too few Greek letters | Use a longer text |
| `greekpages: cannot read style ...:` | the style file is missing or not JSON | Fix the path or the JSON |
| `style ... must be a JSON object` | the style is not an object | Write `{"hand": {...}}` |
| `style ...: unknown ... key ... (known: ...)` | a misspelt key in the style | Use the keys `python -m kit.greekpages style` prints |
| `style value ... must be a finite number or a [low, high] pair with low <= high` | a bad value in the style | Use a number or a pair with low <= high |
| `no letter shape for` | a character outside the 24 letters reached the renderer | Pass text through `clean_text` |
| `page size ... px is outside 64 to 8192` | `--size` too small or too large | Use 64 to 8192 |
| `page ...: non-finite map` | a style value produced NaN or Inf | Check the style values |
| `needs scipy (pip install scipy)` | scipy is missing | `pip install scipy` |
| `preview needs Pillow (pip install pillow)` | Pillow is missing | `pip install pillow` |

## How it works

1. Text: NFD, combining marks dropped, uppercase, every sigma lunate, only the 24 letters kept. Lines are consecutive letters from one random place in one piece.
2. Layout: each letter gets its height (letter height times 1 plus a normal draw with `height_cv`), slant (`slant_mean_deg` plus a normal draw with `slant_sd_deg`), baseline jitter, width scale and gap; a line stops at the page edge; lines sit `line_pitch_h` letter heights apart.
3. Ink: centrelines sampled every 0.01 letter heights; the nib radius runs from `nib_thick_mm / nib_contrast / 2` to `nib_thick_mm / 2` with |sin(stroke angle minus pen angle)|, in 8 steps, drawn by a distance transform at twice the output resolution (OVERSAMPLE 2) and averaged down; each letter's ink load is 1 minus a draw up to `ink_load_drop`.
4. Map model: dropout keeps ink where a smooth field (correlation `dropout_corr_mm`) is above its `dropout` quantile; a smooth warp of amplitude `warp_mm`; Gaussian blur `blur_sigma_mm` across and `blur_sigma_mm * blur_aniso` along; tone `ink_amp * (1 - exp(-tone_gain * ink))`.
5. Background: level plus noise, fibres (noise smoothed 0.05 mm across and 2 mm along, rotated by `fibre_angle_deg`), Gaussian blotches, and thin bent strokes; clipped to 0 to 1.
6. The page is `1 - (1 - background) * (1 - ink probability)` (noisy-OR).

## Cost and time

About 2 s for one 512 px page on one CPU core (25 Nov 2026, 4-core cloud container; 3 pages and the import took 6.9 s). Memory: a few tens of MB per page. Nothing is rented.

## For agents

- **Command:** `python -m kit.greekpages gen OUT --text TEXT --n N --seed S [--style STYLE.json]`
- **Parse:** the first line is JSON `{"text": {files, excluded, pieces, letters}}`; `PROGRESS i/N name` per page; `DONE N pages in OUT`; then read pages with `kit.greekpages.load_page`
- **Rerun:** safe: pages already written are kept, so a rerun with a new style needs a new folder
- **Success:** exit 0 and N pages
- **Not a pass:** a reader's score on these pages as evidence it reads real scrolls
- **Go-ahead:** Nothing
- **Never:** call a page or a reader's output on it a reading; train on text you will evaluate on

## Tests

`python -m unittest tests.test_greekpages` (about 1 s): text cleaning and sigma, every letter has a shape, text exclusion, style loading and refusals, range draws, determinism, labels agree with the drawn text and cover every ink pixel, ink shows in the map and a zero-ink control does not, save and load, generation skips written pages, the command line. Not covered: realism against real ink maps.

## History

- 2026-11-25: built with a generic book hand and pluggable styles; released on top of public `bd011dc`.

## Related

[letterread](letterread.md) (the Scroll Text Reader, a letter reader these pages can train or test), [greeklm](greeklm.md) (Greek letter language model), [sheethug](sheethug.md) (synthetic sheet stacks for surfaces).
