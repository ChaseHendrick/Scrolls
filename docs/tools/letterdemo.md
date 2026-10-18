# letterdemo: check a letter reader install on synthetic Greek capitals and noise

`python -m kit letterdemo` draws four lines of Greek capitals and a noise image in numpy, reads both with the letter reader's released weights, and prints DEMO PASS or DEMO FAIL under a fixed rule: an offline check that the reader, its weights and numpy work together.

| Field | Value |
| --- | --- |
| Id | `letterdemo` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Letters and titles |
| Run | `python -m kit letterdemo`, `scrolls-letterdemo` (the installed package's console script), `from kit import letterdemo` |
| Code | `kit/letterdemo.py`, `kit/cli.py` (`cmd_letterdemo`, `letterdemo_main`) |
| Tests | `tests/test_letterdemo.py`, `tests/test_letterread.py`, `tests/test_packaging.py` |
| Needs | Python 3.10 or newer and numpy; Pillow only for the PNG files of `--out`. The reader's weights: a released model (`letters-v2-ccby` by default, 5,933,674 bytes, downloaded once) or a `linenet-v1` `.npz` file. No torch, no GPU, no system font |
| Runs on | Any CPU. 5.4 s of CPU time with one BLAS thread, 18.5 s wall while other jobs held the 4 cores at a load average of about 14 (measured 2026-10-16, 4-core 2.8 GHz Xeon cloud container, weights cached); the guide measured 6 to 12 s on a 4-core cloud container on 2026-10-14 |
| Network | On the first run only, unless the weights are already in place: the weights download from `github.com`, which redirects to GitHub's release file host (`release-assets.githubusercontent.com` or `objects.githubusercontent.com`). None after that |
| Writes | The weights file into the cache folder on the first run (`~/.cache/scrolls-kit/letters/`, or `KIT_LETTER_WEIGHTS`). With `--out DIR`: `DIR/demo.json`, and with Pillow `DIR/demo-page.png` and `DIR/demo-overlay.png`, overwritten on a rerun. Otherwise it prints only |
| Go-ahead | Not needed: it downloads public weights and posts nothing |
| Released | Public `main` since 2026-10-14 ([PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58)); part of the letter reader release and of the installable package `scrolls-workbench` |
| Guide | [Check the install: the offline demo](../letter-reader.md#check-the-install-the-offline-demo) in the letter reader guide |
| Checked | 2026-10-16 against commit `29e7e8c` |

## What it does

Scroll Text Reader's Greek backend ([letterread](letterread.md)) needs numpy, a 6 MB weights file and its own code to agree before any read means anything. This command checks that, with nothing to configure and no image of your own. It draws four lines of Greek capitals, each line the 24 letters in an order fixed by a seed, 32 px tall, with the skeleton hand of the training data (the centerline strokes of `scripts/letters/letterdata.py`, copied into `kit/letterdemo.py` and held equal to it by a test), blurs them and sets them on a noisy ground that looks like a clean ink map. It also makes an image of the same kind of ground with no letters.

It reads both images with the reader at the letter height it drew, with the reader's usual four null copies (shuffled and phase-randomized copies of the image, read the same way), and judges the two results under a fixed rule (`RULE`): the text page's control status must be `strong`, the character error of every decoded letter against the 96 drawn must be at most 0.25 (`MAX_CER`), and the noise image's status must be `none` or `too_few`. It prints DEMO PASS or DEMO FAIL with the numbers and exits 0 or 1.

A pass shows that the install reads clean letters in the hand the model was trained on, and that its controls stop noise. It says nothing about how well the reader reads a scroll: the letters are drawn by the training hand on a clean ground, with known truth. Every string the reader returns, here as anywhere, is Model output: letter hypotheses, not a reading.

## When to use it

- Right after installing the reader (`pip install "scrolls-workbench[reader] @ ..."` or `pip install -e ".[reader]"`), before reading your own images.
- On a new machine, a new Python or numpy version, or an offline machine with the weights copied in by hand (`KIT_LETTER_WEIGHTS`).
- In CI: the reader job in `.github/workflows/check.yml` runs it from outside the clone on Linux, macOS and Windows.
- To check that a weights file you trained or fine-tuned still reads clean synthetic letters (`--weights PATH`).

Do not use it:

- To judge how well the reader reads scroll maps or photographs: use the benchmark scripts in `scripts/letters/` ([letters-training](letters-training.md); the guide's [How well it reads](../letter-reader.md#how-well-it-reads)).
- To read an image of your own: use [letterread](letterread.md).
- To score a fine-tuned model on lines you transcribed: use [letterlines](letterlines.md) `score`.

## Quick start

```bash
python -m kit letterdemo
python -m kit letterdemo --json --out DEMO_DIR
```

- `DEMO_DIR`: a folder for `demo.json` and the two PNG files; it is made when missing.
- From an installed package, `scrolls-letterdemo` is the same command.

On 2026-10-16 (synthetic images, `letters-v2-ccby`, weights downloaded on the first run) the report ended:

```
  drawn   ΨΔΜΑΙΘΩΤΧΠΦΟΓϹΒΖΥΛΗΝΕΡΚΞ
  decoded ΨΔΜΑΙΘΩΤΧΠΦΟΓϹΒΖΥΛΗΝΕΡΚΞ

text page:   strong (96 letters kept; nulls 9, 0, 11, 2, ratio 8.73); character error 0.000 over 96 letters; 4 lines found of 4
noise image: none (0 letters kept; nulls 8, 0, 6, 1, ratio 0)
rule: pass when the text page's status is strong (more than 3 times the letters of every null, at least 10 letters), its character error is at most 0.25, and the noise image's status is none or too_few

DEMO PASS: the text page is strong at a character error of 0.000, and the noise image is none.
Model output: letter hypotheses from a learned line reader, not a reading. A papyrologist decides what is legible.
```

It worked when the exit code is 0 and the report says DEMO PASS (with `--json`, `"passed": true`). These are the same numbers the guide recorded on 2026-10-14.

## Checks and controls

- **The noise image is the built-in negative control.** The same kind of ground with no letters must keep no more letters than its own nulls (`none`) or too few to judge (`too_few`). A noise status of `weak` or `strong` fails the demo.
- **The rule can fail, and does on a broken model.** With the tests' small network of random weights it printed `DEMO FAIL (text_status, character_error): text page weak, character error 0.906 (at most 0.25 passes); noise image none.` and exited 1 (2026-10-16). The guide records three random-weight seeds failing with the text page `weak` or `none` and character errors of 0.91 to 3.87.
- **A pass, for scale.** `letters-v2-ccby`: 96 letters kept against nulls of 9, 0, 11 and 2 (ratio 8.73), character error 0.000, noise 0 letters (this page's run, and the guide's of 2026-10-14). The guide also records twelve other seeds of the page and the noise passing with `letters-v2-ccby` (94 to 96 letters kept, ratios 6.71 to 9.60), and `letters-v2-real` keeping 96 against 7, 0, 13 and 2 (ratio 7.38) at character error 0.000; those figures are in the `letter_reader_checks` list of [`results.json`](../results.json) (entries dated 2026-10-14).
- **What the rule does not cover.** It never reads real data, so a model that reads only the training hand passes.

Claim label: Model output on synthetic images; a pass is a check that the install works, not evidence that the reader reads any scroll.

## Commands and options

### `python -m kit letterdemo`

```
usage: python -m kit letterdemo [-h] [--weights WEIGHTS] [--out OUT] [--json]
                                [--quiet]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--weights WEIGHTS` | `letters-v2-ccby` | The model to check: a released model name from `kit/data/letter-weights.json` (`letters-v2-ccby` or `letters-v2-real`; downloaded once into the cache and checked by SHA-256), or a path to a `linenet-v1` `.npz`. A name is looked up before any file of that name; a file named like a released model's file must have its SHA-256. The default is `letterread.DEFAULT_WEIGHTS` |
| `--out OUT` | none | A folder to write `demo.json` (the numbers, the letters drawn and both full reader results) and, with Pillow, `demo-page.png` (the text page) and `demo-overlay.png` (the reader's letters drawn on it). Made when missing; refused when it is a file |
| `--json` | off | Print a JSON object (the fields under Outputs) instead of the text report |
| `--quiet` | off | No progress messages on stderr (`reading the text page ...`, `reading the noise image`, `wrote FILE`). Errors still print |

From an installed package, `scrolls-letterdemo` takes the same options and shows its own name in usage and errors.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_LETTER_WEIGHTS` | unset: `~/.cache/scrolls-kit/letters` | Read by the reader when it resolves a released name. A folder is the cache folder; a weights file with the released model's SHA-256 is used as it is (an offline machine). See [letterread](letterread.md) |

## Python API

```python
from kit import letterdemo
out = letterdemo.run("letters-v2-ccby")
print(letterdemo.report(out))
print(out["passed"], out["numbers"]["text"]["character_error"])
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `run(weights=R.DEFAULT_WEIGHTS, progress=None)` | dict: `note`, `demo`, `passed`, `numbers`, `drawing`, `truth`, `decoded`, `weights`, `text_result`, `noise_result`, and `_images` (the page and noise arrays; not JSON) | What `letterread.load_weights` raises: `ValueError` for a missing file or a SHA-256 mismatch, `WeightsError` (an `OSError`) for a failed download | `weights` is a released name, a path or a loaded `LineNet`. `progress` is an optional callable that takes a short message. Each image is read with `letterread.read(img, net, letter_px=32, orientation=False)` |
| `judge(text_res, noise_res, truth, max_cer=MAX_CER)` | `(passed, numbers)`: a bool, and the `numbers` dict under Outputs | `KeyError` for a result without `control` or `lines` | The rule: text status in `TEXT_PASS`, character error at most `max_cer`, noise status in `NOISE_PASS` |
| `character_error(res, truth)` | float | Nothing of its own | Edit distance between all decoded letters (joined in reading order) and all drawn letters, over the number drawn |
| `decoded(res)` | list of str, one per line | Nothing of its own | Every decoded letter at any confidence, lines sorted by column, then row |
| `page_lines(seed=SEED, n_lines=N_LINES)` | list of str | Nothing | Each line is a permutation of the 24 capitals drawn from `numpy.random.default_rng(seed)` |
| `render_page(lines, h=LETTER_PX, seed=SEED)` | `(image, truth)`: float32 2D array in 0..1, ink bright; and per line `{"text", "y", "x"}` (center row and each letter's left edge, page pixels) | `KeyError` for a letter with no skeleton | The same lines, `h` and seed give the same image |
| `noise_page(shape, h=LETTER_PX, seed=NOISE_SEED)` | float32 2D array in 0..1 | Nothing | The ground alone: the demo's known-bad input |
| `ground(shape, h, rng)` | float32 2D array | Nothing | Blotches, fiber streaks along the lines and grain, before clipping |
| `draw_segments(shape, segs, width)` | float32 2D array of ink coverage, 0 to 1 | Nothing | Round-pen strokes `width` px wide along `((x, y), (x, y))` segments, anti-aliased by distance |
| `blur(a, sigma)` | array | Nothing | Separable Gaussian with reflected edges; returns `a` unchanged for `sigma` at most 0.05 |
| `report(out)` | str | `KeyError` for a dict that is not `run()`'s | The printed report, ending with DEMO PASS or DEMO FAIL and the model-output note |
| `save(out, folder)` | list of the `Path`s written | `OSError` when the folder cannot be made or written | `demo.json` always; the PNG files only when Pillow imports |
| `run_cli(args)` | int exit code: 0, 1 or 2 | Nothing for the errors it reports; it catches `ImportError`, `OSError`, `KeyError` and `ValueError` | The command line on a parsed namespace with `weights`, `out`, `json` and `quiet` |

## Inputs

There is no image to give: the demo draws its own. The only input is the weights:

| Input | Format | Notes |
| --- | --- | --- |
| Weights | A released name, or a `linenet-v1` `.npz` (the export of `scripts/letters/train_linenet.py`: BatchNorm folded into the convolutions, a JSON `meta` with the alphabet, `letter_px` 16, the band and the stride) | The released files are listed in `kit/data/letter-weights.json` with their SHA-256 and address; [letterread](letterread.md) says how names, paths and the cache are resolved |

What it draws (constants in `kit/letterdemo.py`): a page of 301 x 1,006 px, four lines (`N_LINES = 4`) of letters 32 px tall (`LETTER_PX = 32`), two letter heights apart (`PITCH = 2.0`), ink bright on a dark ground, and a noise image of the same shape.

## Outputs

The text report, on stdout: the demo's settings and the weights' name, file and first 12 hex digits of SHA-256; each line drawn and decoded; the text page's and the noise image's status lines; the rule; and a last verdict line, `DEMO PASS: ...` or `DEMO FAIL (CHECKS): ...`, where CHECKS names the checks that failed (`text_status`, `character_error`, `noise_status`). A decoded line with no drawn line is listed as `(a line with no drawn line)`.

With `--json`, one object on stdout:

| Field | Type | Meaning |
| --- | --- | --- |
| `note` | str | The model-output note |
| `passed` | bool | The verdict |
| `numbers.text.status` | str | The text page's control status: `strong`, `weak`, `none`, `too_few` or `no_control` |
| `numbers.text.letters_kept`, `numbers.text.null_letters_kept`, `numbers.text.ratio` | int, list of int, float | Letters kept above the confidence floor, the same on each null copy, and kept over the largest null (a null of 0 counts as 1) |
| `numbers.text.character_error` | float (4 decimals) | Edit distance over the letters drawn |
| `numbers.text.letters_drawn`, `numbers.text.lines_found`, `numbers.text.lines_drawn` | int | 96, the lines the reader found, and 4 |
| `numbers.noise.status`, `.letters_kept`, `.null_letters_kept`, `.ratio` | as for the text page | The noise image's controls |
| `numbers.checks.text_status`, `.character_error`, `.noise_status` | bool | Each part of the rule |
| `numbers.max_cer`, `numbers.rule` | float, str | 0.25, and the rule in words |
| `truth` | list of objects | Per drawn line `text`, `y` (center row) and `x` (each letter's left edge), page pixels |
| `decoded` | list of str | Every decoded letter per line, any confidence, in reading order |
| `weights` | object | `name` (the released name, or null), `file` (file name only), `sha256`, `format` (`linenet-v1`) |
| `drawing` | object | `seed` (20261014), `noise_seed` (20261015), `letter_px` (32), `lines` (4), `pitch` (2.0), `gap` (0.3), `pen` (0.14), `shape` ([301, 1006]) and `hand` |

`--out DIR` writes `DIR/demo.json` with the same fields plus `demo` (`kit.letterdemo`), `text_result` and `noise_result` (the reader's full results, as [letterread](letterread.md) describes them; no local folder is recorded), and, with Pillow, `DIR/demo-page.png` (the text page as 8-bit gray) and `DIR/demo-overlay.png` (the reader's overlay of the text page). Progress and `wrote FILE` lines go to stderr unless `--quiet`.

| Exit code | Meaning |
| --- | --- |
| `0` | DEMO PASS |
| `1` | DEMO FAIL: the demo ran and the rule failed; the report names the failed checks |
| `2` | The demo could not run or could not write its files (`DEMO ERROR: ...` on stderr), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `DEMO ERROR: the letter reader needs numpy (No module named 'numpy'); python -m pip install "scrolls-workbench[reader]" (numpy, pillow, tifffile and imagecodecs)`, exit code 2 | The package was installed without the `reader` extra | Install the extra with the command it prints |
| `DEMO ERROR: NAME: no such file, and not a released model (letters-v2-ccby, letters-v2-real)`, exit code 2 | `--weights` is neither a released name nor an existing file | Give a released name or the path of a `.npz` |
| `DEMO ERROR: could not download the weights NAME from URL into FOLDER: ...`, exit code 2 | No network, a proxy or a firewall stopped the download | Follow the message: download the file by hand and copy it into FOLDER, or point `KIT_LETTER_WEIGHTS` at it ([letterread](letterread.md) has the details) |
| `DEMO ERROR: NAME: FILE does not match its SHA-256 ...`, exit code 2 | The cached file is damaged or another file | Delete it and run again, or download it by hand as the message says |
| `DEMO ERROR: PATH: not a linenet-v1 weight file`, exit code 2 | A `.npz` that is not the reader's export | Give a `linenet-v1` export |
| `DEMO ERROR: --out PATH: not a folder`, exit code 2 | `--out` names an existing file | Give a folder (it is made when missing) |
| `DEMO ERROR: could not write into DIR: ...`, exit code 2, after the report | The folder could not be made or written | Check the path and its permissions; the report above it is still valid |
| `DEMO FAIL (text_status, character_error): ...`, exit code 1 | The weights do not read the synthetic page: a wrong or damaged model, or a broken install | Check `--weights`; with a released name, compare the SHA-256 in the report with `kit/data/letter-weights.json` |
| `DEMO FAIL (noise_status): ...`, exit code 1 | The reader kept letters on the noise image above its nulls | The weights or the controls are not working; do not trust reads with this install |

## How it works

1. **The text.** `page_lines()` draws four permutations of the 24 capitals (`ALPHABET`, `ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ`, with the lunate sigma U+03F9 that the released weights write for every sigma) from `numpy.random.default_rng(SEED)`, `SEED = 20261014`.
2. **The page.** `render_page()` places line i with its top at (1.2 + 2i) letter heights. Each letter takes one variant of its skeleton (`SKELETONS`, centerlines in letter units) chosen by `default_rng(SEED + 1)`, a baseline wobble of normal(0, 0.02) letter heights, and an advance of its width plus `PEN + GAP` = 0.44 letter heights. Strokes are drawn as a round pen `PEN = 0.14` letter heights wide, anti-aliased by distance (`draw_segments`), blurred with sigma 0.05 letter heights, and added at 0.7 to a ground of 0.12 plus 0.05 times blotches (Gaussian noise blurred by 0.3 letter heights), 0.04 times streaks along the lines and 0.05 times grain, then clipped to 0..1 (float32).
3. **The noise.** `noise_page()` is the ground alone from `default_rng(NOISE_SEED)`, `NOISE_SEED = 20261015`, the same shape as the page.
4. **The reads.** Both images are read by `letterread.read()` at `letter_px=32` with its defaults: four nulls, seed 0, confidence floor set from the nulls, columns `auto`, deskew up to 6 degrees, and `orientation=False`.
5. **The rule.** `judge()` takes every decoded letter at any confidence (not only those above the floor), lines in reading order (column, then row), joins them and divides the edit distance to the 96 drawn letters by 96. It passes when the text page's status is in `TEXT_PASS = ("strong",)`, that error is at most `MAX_CER = 0.25`, and the noise image's status is in `NOISE_PASS = ("none", "too_few")`. `strong` means more than `STRONG_FACTOR` (3) times the largest null and at least `MIN_LETTERS` (10) letters, from `kit/letterread.py`.

## Cost and time

Measured on 2026-10-16 in a 4-core 2.8 GHz Xeon cloud container that other jobs were sharing (load average 12 to 15), with the weights cached:

| Run | Wall time | CPU time | Notes |
| --- | --- | --- | --- |
| `letterdemo`, one BLAS thread (`OMP_NUM_THREADS=1`) | 18.5 s | 5.4 s | The reading work itself |
| `letterdemo`, numpy's default threads | 104 s | 38 s | Thread oversubscription on a busy machine |
| First run, including the 6 MB download | 52 s | Not measured | |
| `--weights` with the tests' random network | 3.5 s | 1.4 s | A small network |

The guide measured 6 to 12 s on a 4-core cloud container on 2026-10-14. Memory was not measured for the demo; a read of the same page by [letterread](letterread.md) peaked at 72 MB. It runs on any laptop CPU; nothing here needs Modal or a GPU.

## For agents

- **Command:** `python -m kit letterdemo --json --quiet` (or `scrolls-letterdemo --json --quiet` from an installed package); `--weights NAME_OR_PATH` to check other weights.
- **Parse:** `passed`, then `numbers.checks` for which part failed, `numbers.text.status`, `numbers.text.character_error` and `numbers.noise.status`; `weights.sha256` says which file was read.
- **Rerun:** Safe and deterministic: the same weights give the same numbers. The first run downloads the weights once; `--out` overwrites its three files.
- **Success:** Exit code 0 and `"passed": true`.
- **Not a pass:** Exit code 2 (nothing was judged). A pass is not evidence that the reader reads any scroll, any map or any photograph.
- **Go-ahead:** Nothing.
- **Never:** Quote the demo's pass as a reading accuracy, or call any decoded string a reading; the demo's letters are synthetic and drawn in the training hand.

## Tests

```bash
python -m unittest tests.test_letterdemo -v
```

They cover the skeleton hand held equal to `scripts/letters/letterdata.py`, a skeleton for every letter, the seeded line orders, the round pen, a fixed page and a noise page without letters, the rule and its boundary at `max_cer`, the reading order across columns, random weights failing with exit code 1, exit code 2 for missing weights and for an `--out` that is a file, the `--out` files, the console script, and a missing numpy giving `DEMO ERROR` rather than a traceback. A pass is tested with a mocked reader, so the tests never download the released weights; the CI reader job runs the real demo. `tests/test_letterread.py` checks that the demo's default is `letterread.DEFAULT_WEIGHTS`, and `tests/test_packaging.py` that the console script exists and CI runs it on three systems. 34 tests of `tests.test_letterdemo`, `tests.test_letterlines` and `tests.test_letterexport` passed together in 29 s on 2026-10-16.

## History

- 2026-10-14: `letters-v2-ccby` (CC BY 4.0) becomes the default weights; `letters-v2-real` stays available with `--weights letters-v2-real` (`0366ed7`).
- 2026-10-14: a missing numpy, Pillow, tifffile or imagecodecs gives the reader extra's install line (`ca7b143`).
- 2026-10-14: first version, with the installable package, the console script `scrolls-letterdemo` and CI on Linux, macOS and Windows (`2582ab7`, [PR #58](https://github.com/ChaseHendrick/Scrolls/pull/58)).

## Related

- [letterread](letterread.md): the reader the demo checks, with every option and output.
- [letterlines](letterlines.md): training lines from your own transcriptions, and scores on lines kept apart.
- [letters-training](letters-training.md): the scripts that train the reader and benchmark it on public data.
- [workbench-package](workbench-package.md): the installable package and its console scripts.
- [The letter reader guide](../letter-reader.md): install, weights, model cards and measured accuracy.
- `letter_reader_checks` in [`results.json`](../results.json): the demo's recorded numbers with their dates.
