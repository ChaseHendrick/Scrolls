# Greek letter reader

A small learned reader that proposes Greek capital letters, with positions and confidences, on 2D images of scroll text: ink-detection maps, drawn ink labels and photographs of papyri. It reads whole lines with a convolutional network trained with CTC, runs in numpy (no GPU or torch needed to read), and reports controls with every result, so you can tell letters from noise.

Everything it prints is **Model output**: letter hypotheses for a person to check. It is not a reading or a transcription; papyrologists read and transcribe ([NOVELTY.md](NOVELTY.md)).

- Code: [`kit/letterread.py`](../kit/letterread.py) (reader), [`kit/greeklm.py`](../kit/greeklm.py) (optional letter language model), [`scripts/letters/`](../scripts/letters/) (training data, training, benchmarks, demo).
- Measured accuracy: [How well it reads](#how-well-it-reads) below, with the full record in [`logs/2026-10-14-letter-reader.md`](logs/2026-10-14-letter-reader.md) and the numbers in [`results.json`](results.json) under `letter_reader_checks`.
- Weights: the command selects `letters-v2-real` (CC BY-NC 4.0) when you supply line positions, and `letters-v2-ccby` (CC BY 4.0) for automatic page reads. You can choose either explicitly; the demos use the permissive weights. [Which weights](#which-weights) explains the evidence and licenses. Weights are not in git.
- Other scripts: the optional local Tesseract backend can propose Latin, Hebrew and other text when the corresponding language packs are installed. It reports word hypotheses, pack hashes and blank/shuffled controls; it has no measured scroll accuracy. [Reader backends](tools/reader-backends.md) covers installation, explicit language selection and switching backends or weights in a long-lived `ReaderSession`.

## Quick start

You need Python 3.10 or newer. Make a virtual environment for the reader, install it there, and check it with the offline demo. The install takes a few minutes (git fetches the repository, and pip fetches numpy, Pillow, tifffile and imagecodecs); the demo then downloads the 6 MB of weights once and runs in about ten seconds.

**macOS and Linux.** Use `python3`: many systems have no `python` command until a virtual environment is active. Debian, Ubuntu, Homebrew's Python and others refuse `pip install` outside a virtual environment (an `externally-managed-environment` error, [PEP 668](https://peps.python.org/pep-0668/)), which is one more reason to make one; on Debian and Ubuntu, `python3 -m venv` may first need `sudo apt install python3-venv`. Once the environment is active, `python` and `pip` are its own.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install "scrolls-workbench[reader] @ git+https://github.com/ChaseHendrick/Scrolls"
scrolls-letterdemo
```

**Windows** (PowerShell or Command Prompt). `py` is the Python launcher that the python.org installer sets up. Calling the environment's own `python.exe` needs no activation (PowerShell's default execution policy often blocks `Activate.ps1`), and the commands are installed beside it in `.venv\Scripts`:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install "scrolls-workbench[reader] @ git+https://github.com/ChaseHendrick/Scrolls"
.venv\Scripts\scrolls-letterdemo.exe
```

**From a clone**, which you need for the scripts in `scripts/letters/` (the public-map demo, the benchmarks, training) and for the commands that read the repository's `docs/` (`releases`, `gate`). A virtual environment in the clone, then an editable install of it, so the commands follow the clone's files:

```bash
git clone https://github.com/ChaseHendrick/Scrolls
cd Scrolls
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[reader]"
python -m kit letterdemo
```

On Windows: `git clone https://github.com/ChaseHendrick/Scrolls`, `cd Scrolls`, `py -m venv .venv`, `.venv\Scripts\python.exe -m pip install -e ".[reader]"` and `.venv\Scripts\python.exe -m kit letterdemo`. Every `python ...` command below assumes the environment is active (on Windows, read `python` as `.venv\Scripts\python.exe`) and, for `scripts/...`, that it runs from the clone's root.

Then read an image of your own. Here it is an ink map whose letters are 86 px tall, as PHerc. 1667's are on the 38 um grid of the public-map demo ([`scripts/letters/demo_p1667.py`](#first-reads), not the offline demo above; [Letter size matters most](#letter-size-matters-most) gives the size for other images):

```bash
scrolls-letterread MAP.png --weights letters-v2-ccby --letter-px 86 --overlay MAP-letters.png
```

The code blocks in this guide hold one command per line, and any comment sits on a line of its own, so a block can be pasted into any shell as it is: stock zsh (macOS) has interactive comments off, so it runs a pasted comment line as a command named `#`, which prints `zsh: command not found: #` and does nothing else (`setopt interactivecomments` silences it). A comment after a command on the same line would be passed to the command as arguments. The comment lines hold plain words only, no quotes, brackets or `>`, which zsh would otherwise act on.

### Install

- **The `git+https` form needs git** (Git for Windows on Windows, the Xcode command line tools on macOS). Without git, install from the archive GitHub serves of the same branch: `python -m pip install "scrolls-workbench[reader] @ https://github.com/ChaseHendrick/Scrolls/archive/refs/heads/main.zip"`.
- **Commands.** `scrolls-letterread` is `python -m kit letterread`, `scrolls-letterlines` is `python -m kit letterlines` and `scrolls-letterdemo` is `python -m kit letterdemo`; `scrolls-workbench` runs every `python -m kit` command. Every `python -m kit ...` in this guide works either way, from any folder, except `gate` and `releases`: they read the repository's `docs/` and `README.md`, which an installed package does not have, so they need a clone and say so when run without one.
- **Extras.** `reader` installs numpy, Pillow, tifffile and imagecodecs. `all` adds zarr (zarr and OME-Zarr maps, and big tiled TIFFs read band by band, which keeps a whole native map's read near 250 MB of memory; see [Big maps](#big-maps)) and scipy (the map tools); `maps` is the map tools alone. zarr 3 needs Python 3.11, and zarr 2 lacks what `kit shuffle` and the zarr outputs use, so on Python 3.10 these two extras install without zarr. With no extra, only the standard-library core installs (`prizes`, `plan`, the run ledger), and the reader stops with a message that names the missing module and gives the install line, `python -m pip install numpy pillow tifffile imagecodecs`: the reader itself is not standard library only. The line names the packages, not the extra, because `scrolls-workbench` is not on PyPI: a bare `pip install "scrolls-workbench[reader]"` outside an install from GitHub would fetch whatever another person published under that name.
- **Its own environment, apart from AutoPipeline's.** AutoPipeline's released package (`vc-autopipeline`, with its `scrolls-kit` command; the README's AutoPipeline entry names its current release branch) also installs a top-level package named `kit`, its own cut of this one. In one environment the second install overwrites the first one's `kit`, and uninstalling either removes files the other needs. This package is named `scrolls-workbench` and none of its commands is `scrolls-kit`, so the names do not clash; the `kit` package does, so give each its own environment.

### Check the install: the offline demo

`scrolls-letterdemo` (from a clone, `python -m kit letterdemo`) checks that the package, its weights and numpy work together, with nothing to download but the weights and nothing to configure; it took 6 to 12 seconds on a 4-core cloud container. It draws four lines of Greek capitals, each line the 24 letters in an order fixed by a seed, 32 px tall, with the bookhand skeleton of the training data ([`scripts/letters/letterdata.py`](../scripts/letters/letterdata.py), drawn in numpy with no font), blurred and set on a noisy ground like a clean ink map, and an image of the same ground with no letters. It reads both at that letter height with the usual nulls and prints the letters drawn and decoded, line by line, both statuses and its verdict:

```
text page:   strong (96 letters kept; nulls 9, 0, 11, 2, ratio 8.73); character error 0.000 over 96 letters; 4 lines found of 4
noise image: none (0 letters kept; nulls 8, 0, 6, 1, ratio 0)
DEMO PASS: the text page is strong at a character error of 0.000, and the noise image is none.
```

The rule is fixed in [`kit/letterdemo.py`](../kit/letterdemo.py) (`RULE`): DEMO PASS when the text page's status is `strong` (more than three times the letters of every null, and at least ten letters), the character error of every letter decoded, line by line from the top, against the 96 drawn is at most 0.25, and the noise image's status is `none` or `too_few`. Otherwise DEMO FAIL, with the checks that failed and the numbers. The exit code is 0 on a pass, 1 on a fail and 2 when the demo cannot run (`DEMO ERROR`: no numpy, or no weights).

- `--weights NAME` reads with another released model, such as `--weights letters-v2-real`; `--weights PATH` reads with a weights file you already have, such as one downloaded by hand; a file named like the released one is checked by its SHA-256, and `KIT_LETTER_WEIGHTS` works as for the reader (below).
- `--out DIR` writes `demo.json` (the numbers, the letters drawn and both full results) and, with Pillow, `demo-page.png` and `demo-overlay.png`; `--json` prints the numbers as JSON.
- A pass shows that the install reads clean letters in the hand it was trained on and that its controls stop noise. It says nothing about how well it reads a scroll (Interpretation); for that see [How well it reads](#how-well-it-reads) and the public-map demo below.

Measured on 14 October 2026 (Model output, synthetic images): with `letters-v2-ccby`, the numbers above (Python 3.13, numpy 2.5.3), and twelve other seeds of the page and the noise all passed: character error 0.000 each time, 94 to 96 letters kept, ratios 6.71 to 9.60 to the largest null, and 0 or 1 letter kept on the noise (status `none`). With `letters-v2-real`, the default before it, the text page kept 96 letters against nulls of 7, 0, 13 and 2 (ratio 7.38) at a character error of 0.000 and the noise 0 letters, identical on Python 3.10 with numpy 2.2.6 and on Python 3.13 with numpy 2.5.3; its twelve other seeds passed too (95 or 96 letters kept, ratios 6.86 to 10.67). With random weights (the tests' small random network, three seeds) the demo fails, as it must: text page weak or none, character error 0.91 to 3.87.

CI ([`.github/workflows/check.yml`](../.github/workflows/check.yml)) builds and installs the package with the `reader` extra on Linux, macOS and Windows, with Python 3.10 and 3.13, runs the reader's tests, and runs the demo from outside the clone with the weights downloaded from the GitHub release; the standard-library job installs it with no extra and checks that the demo stops with exit code 2.

### Networks, proxies and offline machines

What goes over the network, and to where (checked 14 October 2026):

- **Installing.** `pip install ... @ git+https://github.com/...` runs git against `github.com`; the archive form downloads from `github.com`, which redirects to `codeload.github.com`. pip fetches numpy, Pillow, tifffile and imagecodecs, and setuptools to build the package, from `pypi.org` and `files.pythonhosted.org`.
- **The weights, once.** The address in [`kit/data/letter-weights.json`](../kit/data/letter-weights.json) is on `github.com`, which redirects the download to GitHub's host for release files, `release-assets.githubusercontent.com` when this was checked; GitHub has also served release files from `objects.githubusercontent.com`, so allow both beside `github.com`.
- **The public-map demo and the benchmark data.** `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`, the open-data bucket, read anonymously over HTTPS.
- Nothing else. Reading an image, the exports and the offline demo (with the weights in place) make no connection.

**Proxies.** The reader's downloads use Python's `urllib`, which follows the `HTTPS_PROXY` (or `https_proxy`) and `NO_PROXY` environment variables, or when they are not set the system's proxy settings on macOS and Windows; pip and git follow the same variables.

**Certificates.** A network that inspects HTTPS (many company proxies) signs every site with its own certificate authority. Give its PEM file to Python with `SSL_CERT_FILE=/path/to/ca.pem` (the weights download and the bucket), to pip with `--cert /path/to/ca.pem` or `PIP_CERT`, and to git with `GIT_SSL_CAINFO`. On macOS with Python from python.org, a `CERTIFICATE_VERIFY_FAILED` error usually means its certificates were never installed: run `Install Certificates.command` in its folder under Applications. Do not turn certificate checks off.

**Offline machines.** On a machine with network, in the clone with its environment active, build wheels of the package and its dependencies and fetch the weights; then copy the `wheels` folder and the weights file to the offline machine, which must have the same system and Python version (numpy's wheels are built for each):

```bash
python -m pip wheel ".[reader]" -w wheels
curl -L -o letters-v2-ccby-step026000.npz https://github.com/ChaseHendrick/Scrolls/releases/download/letters-v2-ccby/letters-v2-ccby-step026000.npz
```

On the offline machine:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --no-index --find-links wheels "scrolls-workbench[reader]"
export KIT_LETTER_WEIGHTS="$PWD/letters-v2-ccby-step026000.npz"
scrolls-letterdemo
```

The weights file and the `wheels` folder sit in the clone, and its `.gitignore` keeps both out of git (weights never go in git). On Windows, `$env:KIT_LETTER_WEIGHTS = "C:\path\to\letters-v2-ccby-step026000.npz"` in PowerShell, or `set KIT_LETTER_WEIGHTS=C:\path\to\letters-v2-ccby-step026000.npz` in Command Prompt. The file's SHA-256 is checked before it is read, as for a download. Measured on 14 October 2026: these steps on Python 3.13, with the offline machine's proxy pointed at a closed port so no connection could succeed, installed the package and printed DEMO PASS (with the `letters-v2-real` file, the default then; the steps are the same for any released file). For `letters-v2-real`, download its file and set `KIT_LETTER_WEIGHTS` the same way; the demo then needs `--weights letters-v2-real`, and its address is in its [model card](#model-card-letters-v2-real).

### What it reads, and what it does not

- **Images of ink, not CT.** It reads 2D images on which ink shows as letter shapes: an ink-detection map (the output of villa's ink detection, or of any ink model), a drawn ink label, or a photograph or scan of a papyrus (with `--polarity dark` or `auto`, see [Reading a photograph](#reading-a-photograph)). It was never trained or tested on raw CT: a CT layer or a slice of a surface volume shows ink far too faintly for it, so run ink detection first ([pipeline.md](pipeline.md)).
- **Greek capitals only.** It proposes the 24 Greek capitals, every sigma as the lunate Ϲ, and nothing else: no small letters, accents, punctuation or numerals. Latin text comes out as Greek look-alikes (A as Α, C as Ϲ, P as Ρ) and other letters as their nearest Greek shapes, so its strings there mean nothing.
- **Prize scrolls.** Before you read a scroll's maps, check whether it is prize-eligible: `python -m kit prizes` (or `scrolls-workbench prizes`) lists the open prizes and their eligible scrolls from a dated snapshot, and [scrollprize.org/prizes](https://scrollprize.org/prizes) wins where they differ. A read of a prize-eligible scroll is a possible finding, and the prize terms forbid disclosing one before the official announcement: keep it private ([Rules for using it on scrolls](#rules-for-using-it-on-scrolls)).

### First reads

From a clone, in its environment ([Install](#install)). First the public-map demo, which downloads a 3.5 MB image of a PHerc. 1667 ink map and the weights once, keeps the image as `work/letters/demo/w013-ds8.jpg` with its bucket address in `w013-ds8.json`, and writes `w013.json` and `w013-overlay.png` beside a text summary on screen:

```bash
python scripts/letters/demo_p1667.py --segment w013 --out work/letters/demo
```

The demo reads the map's small JPEG from the bucket averaged 2 by 2 to the 38 um grid, with `letters-v2-ccby` unless `--weights` names other weights. Measured on 14 October 2026 (Model output): on w013 it keeps 121 letters against nulls of 30, 20, 34 and 47, status `weak`; the full map averaged 16 by 16 under [Where the letters are](#where-the-letters-are) keeps 120 against 31, 20, 33 and 47, also `weak`. With `--weights letters-v2-real` both keep 122 letters against 43, 33, 27 and 28.

Then your own images. The first command is an ink map, ink brighter than its ground; the second a photograph, dark ink on a light ground ([Reading a photograph](#reading-a-photograph)); the third gives the letter size in millimetres and writes the whole result as JSON to a file (`--json` would print it in place of the summary); the fourth reads the reverse-depth map of the same surface as a control ([The control map](#the-control-map)); the fifth writes the letters as a table and as PAGE XML for eScriptorium ([Exports](#exports-csv-and-page-xml)):

```bash
python -m kit letterread MAP.png --weights letters-v2-ccby --letter-px 86 --overlay MAP-letters.png
python -m kit letterread PHOTO.jpg --weights letters-v2-ccby --letter-px 28 --polarity auto --overlay PHOTO-letters.png
python -m kit letterread MAP.tif --weights letters-v2-ccby --letter-mm 3.3 --um-per-px 38.4 --out MAP-letters.json
python -m kit letterread MAP.tif --weights letters-v2-ccby --letter-px 86 --control MAP_reverse.tif
python -m kit letterread MAP.png --weights letters-v2-ccby --letter-px 86 --csv MAP-letters.csv --page-xml MAP-letters.xml
```

And a whole native 2.4 um villa map as downloaded, with PHerc. 1667's letter height; it is block-averaged while it loads, and with zarr installed (`python -m pip install zarr`) it stays near 250 MB of memory, against about 3.7 GB without ([Big maps](#big-maps), which also gives what it keeps on w013):

```bash
python -m kit letterread MAP-2.4um.tif --weights letters-v2-ccby --letter-mm 3.3 --um-per-px 2.399 --overlay MAP-letters.png
```

`--weights letters-v2-ccby` names a released model in [`kit/data/letter-weights.json`](../kit/data/letter-weights.json) (so does `--weights letters-v2-real`; [Which weights](#which-weights)): the reader downloads it once into `~/.cache/scrolls-kit/letters/` (or `$KIT_LETTER_WEIGHTS`) and refuses a file whose SHA-256 differs. A path to any `linenet-v1` `.npz` works too. In detail:

- **Names first.** An argument that is a released model's name is that model, even when a file of that name sits in the current folder; anything else is a path (`~` is expanded).
- **Checked files.** The cached file is checked against the registry's SHA-256 on every read, and so is any file you give by path whose file name is a released model's (`letters-v2-ccby-step026000.npz`, `letters-v2-real-step030000.npz`), so a damaged or swapped copy is refused, not read.
- **`KIT_LETTER_WEIGHTS`** (with `~` expanded) is either the cache folder or a weights file: a file with the model's SHA-256 is used as it is, otherwise its folder is the cache.
- **The weights come before the image.** The command (and the demo) resolves the weights, downloading them if needed, before it loads any image, so a failed download costs no load.
- **When the download fails** (no network, a proxy, a firewall), the message names the model, its address and the cache folder. Download the file by hand, in a browser or with `curl -L -o letters-v2-ccby-step026000.npz URL`, and copy it into that folder (or point `KIT_LETTER_WEIGHTS` at it); its SHA-256 is checked there as for a download. Downloaded files are written readable by everyone (mode 0644), so a shared cache works.

**Windows consoles and pipes.** The command line, the demo and the letter scripts switch standard output and standard error to UTF-8 (with backslash escapes for anything UTF-8 cannot encode) when they are not a terminal (a pipe, or `> out.txt`) or their encoding cannot hold Greek letters, so printing never stops a read on a letter; a console set to another code page may show the letters garbled, and `--out` still holds them correctly. `--out` and `--overlay` (and `--csv` and `--page-xml`) are written before the summary is printed, each named on stderr as it is written (`wrote MAP-letters.png`; `--quiet` leaves that out), and their folders are checked before the read, so a console error never loses a finished read; when one of the two files cannot be written, the other and the summary still come out and the command exits with 2. The JSON is always UTF-8.

### Letter size matters most

The network reads letters about 16 pixels tall; the reader rescales your image to that. Give the letter height when you know it, either in image pixels with `--letter-px`, or in millimetres with `--letter-mm` together with the pixel size in micrometres, `--um-per-px`; the reader works out

letter_px = letter_mm * 1000 / um_per_px

and prints the value it used. PHerc. 1667's letters are about 3.3 mm tall (86 px, the median over its six labelled segments, on a grid of 16 * 2.399 = 38.384 um per pixel). The same 3.3 mm letter on the images you are likely to meet:

| Image | um per pixel | Letter px | Give |
| --- | --- | --- | --- |
| A native 2.4 um ink map, as villa writes it for PHerc. 1667 | 2.399 | 1375.6 | `--letter-mm 3.3 --um-per-px 2.399` (block-averaged while it loads; see [Big maps](#big-maps)) |
| A map at 7.91 um, the voxel size of PHerc. 172's public scan ([scan status](scan-status.md)) | 7.91 | 417 | `--letter-mm 3.3 --um-per-px 7.91` |
| The bucket's small JPEG of a 2.4 um map (`...-ds8.jpg`, 8 times smaller each way) | 19.192 | 172 | `--letter-px 172` |
| The public-map demo's 38 um grid (`scripts/letters/demo_p1667.py`): a 2.4 um map averaged 16 by 16, or that JPEG averaged 2 by 2 | 38.384 | 86 | `--letter-px 86` |

The smallest letter height the reader takes is 4 px (`MIN_LETTER_PX`), a quarter of the network's 16 px: a smaller letter is enlarged more than four times each way (over 16 times the pixels, and the time of the read with them), and its pen stroke (0.14 of the letter's height in the demo's hand) is under a pixel wide, so no letter shape is left to read. `--letter-px` under 4, or `--letter-mm` and `--um-per-px` that give under 4 px, stop with an error before anything is loaded, and the scale search below never tries a height under 4 px.

The table is arithmetic for a 3.3 mm letter; other hands differ, so on another scroll measure a letter on your own image (on screen, or from a drawn label) and give that. Checked on 14 October 2026 (Model output, `letters-v2-ccby`) on PHerc. 1667 w013: the bucket's JPEG at `--letter-px 172` keeps 121 letters against nulls of 30, 20, 34 and 47, and the map averaged 16 by 16 at `--letter-px 86` keeps 120 against 31, 20, 33 and 47. The whole 2.4 um map read with the table's `--letter-mm 3.3 --um-per-px 2.399` (1375.57 px) is block-averaged by 42 and keeps 120 letters against 30, 25, 41 and 35; read with `--letter-px 1376` it is block-averaged by 43 and keeps 128 against 27, 24, 35 and 45. With `letters-v2-real` the four reads kept 122, 122, 118 and 120 letters. The two forms differ by under half a pixel, but the block size is the whole number of times 32 px fits into the letter height (1375.57 / 32 is 42.99, 1376 / 32 is 43.0), so they average differently and their counts differ ([Big maps](#big-maps)). No PHerc. 172 map was read for the 7.91 um row.

A given size is checked against the line spacing: when the two differ by more than a factor of two, the result carries `letter_px_check.warning` and the summary prints it (the spacing estimate itself can be a factor of two off, when it takes two lines for one).

Without a size, the reader estimates one from the line spacing and searches six scales against its own nulls; the summary prints that search as a table, with the kept scale marked `*`. Scales under 4 px are read once, at 4 px, so a guess under 4 px (a strip of an image a few pixels tall, say) gives a search of one row. The search is the weakest step on maps it has not seen (see the limits below). When the image shows no regular line spacing at all, the command stops and asks for `--letter-px` or `--letter-mm` with `--um-per-px` (or a `--crop` that holds several lines); it no longer guesses a quarter of the image height. Python's `analyze()` and `read()` keep that guess for the benchmark scripts, which call them directly, unless given `letter_px_fallback=False`.

| Option | Use |
| --- | --- |
| `--letter-px H`, or `--letter-mm MM --um-per-px UM` | Letter height, in image pixels or in physical units (give one form, not both); at least 4 px |
| `--crop Y0 Y1 X0 X1` | Read part of a large image (a `.npy`, an uncompressed TIFF and a zarr are read by window, and so is a compressed tiled TIFF when zarr is installed); rows, boxes and `--lines` are then relative to Y0, X0, and the result records the crop as `crop`, so full-image rows are Y0 plus the result's rows |
| `--key K` | `.npz`: the array name; zarr: the array path, or the OME-Zarr level (default level 0, full resolution). Every pixel value, `--letter-px` and `--um-per-px` included, is then in that array's pixels |
| `--max-mpx M` | Pixel budget in millions of pixels (default 64); see "Big maps" |
| `--lines Y [Y ...]` | Line centre rows, when you know them (one column). Each is the line's row at the horizontal middle of the image; the deskew still turns the lines about that middle (see [Tilted, turned and mirrored text](#tilted-turned-and-mirrored-text)), so give `--deskew 0` for level bands. With `--rotate` or `--mirror` the rows are in the turned image |
| `--deskew MAX_DEG` | Largest line tilt searched, in degrees either way (default 6, in steps of 0.5; 0 turns the deskew off). A warning says when the angle found is the limit |
| `--polarity bright`, `dark` or `auto` | `bright` (default): ink brighter than the ground, as in ink maps; `dark`: dark ink on a light ground, as in photographs; `auto`: read quickly both ways and keep the polarity whose letters stand further above its nulls (see [Reading a photograph](#reading-a-photograph)) |
| `--rotate 0/90/180/270`, `--mirror` | Read the image flipped left to right (`--mirror`) and then turned that many degrees clockwise, as when its lines run up and down; boxes stay in input pixels |
| `--columns auto` (default), `off` or a number | Split at empty vertical gutters, read the whole width, or ask for that many columns |
| `--lm greek5.npz` | Add a language-model decode beside the ink-only one (below) |
| `--nulls N` | Number of null copies for the control (default 4, at most 64: each is one more read of the whole image, and the status compares with the largest of them, so more nulls cost time and make the test stricter) |
| `--control MAP_REVERSE` | A second map of the same surface on the same grid, such as its reverse-depth ink map, read on the image's lines at the same letter size and confidence floor; `strong` then also needs more than three times its letters (see [The control map](#the-control-map)) |
| `--min-letters N` | Fewest confident letters a read or a column needs before its controls can pass (default 10; fewer is `too_few`) |
| `--no-orientation` | Skip the four orientation reads, mirrored and turned 90, 180 and 270 degrees (faster) |
| `--overlay OUT.png` | The image with kept letters boxed and labelled (green p >= 0.8, yellow below), lower-confidence boxes grey; every outline at least 2 px; a banner above it always carries the whole "Model output ... not a reading" note, wrapped to the width, and under it the status line of the controls with its counts |
| `--overlay-max-side N` | Longest side of the overlay in pixels (default 4000); the JSON records the overlay's scale |
| `--csv OUT.csv` | One row per letter: column, line, index, letter, p, kept and its box, in the image file's pixels (see [Exports](#exports-csv-and-page-xml)) |
| `--page-xml OUT.xml` | PAGE XML (2019 schema): a region per column, a line per line, a glyph per letter with its confidence, in the image file's pixels, marked as model output (see [Exports](#exports-csv-and-page-xml)) |
| `--quiet` | No progress messages; without it, long steps (loading, scale search, reading, orientation) report on stderr, so `--json` output on stdout stays clean |

### Big maps

A whole native ink map is large: PHerc. 1667 w013 at 2.4 um is 41,600 rows by 79,600 columns (3.3 billion pixels), 13 GB as float32. The reader never makes a float copy of such an image. When an image (or its `--crop`) has more pixels than the budget, 64 million by default (`--max-mpx`; 256 MB as float32, and normalising it takes a few such copies), and the letter size is given, it block-averages the image by an integer factor k while it loads: the largest k that keeps letters at least 32 pixels tall, twice the network's working letter height, so the reader's own resize still averages several pixels into each of its pixels. It reads in row bands that follow the file's tiles: a `.npy` or uncompressed TIFF through a memory map, a zarr or OME-Zarr level by chunk, a compressed tiled TIFF through tifffile's zarr view (with zarr installed; without it the TIFF is decoded whole in its stored integer type, 1 or 2 bytes a pixel, and averaged band by band), a PNG or JPEG decoded in its stored type. Rows and columns left over from the last whole block (fewer than k) are not read.

Everything in the result stays in input pixels: rows, columns, boxes, `letter_px` and the scale-search table are mapped back through k, and the JSON records `input_scale` (k), `input_shape` (the input window) and `reduced_shape` (what was read). Below the budget nothing changes: the image is loaded and read exactly as before. Without a letter size, an image over the budget is reduced only as far as the budget needs, and the reader says so; if its letters are small that can leave them too small to read, so give the size. With letters too small to reduce (under 64 px), the image is loaded whole and the reader says it is over the budget. The image is normalised once (in float32 above the budget, float64 within it, as before) and that one image serves the main read, its nulls, the orientation reads and the overlay. Out of memory, the command stops with this advice: give the letter size, lower `--max-mpx`, or `--crop` a window; when the letter size was given and its letters are too small to block-average, only a `--crop` window (or a check of the letter size) can help, and the advice says just that.

Measured on 14 October 2026 on a 4-core cloud container, 2 threads, under a 10 GB address-space limit (`ulimit -v 10000000`), reading w013's whole 2.4 um map (a 269 MB deflate-compressed tiled TIFF) with `--letter-px 1376` and an overlay, with zarr installed (the `all` extra, or `python -m pip install zarr`): block-averaged by 43 to 967 rows by 1,851 columns, 35 to 36 s wall time and about 250 MB peak resident memory (two runs), with 120 letters kept against nulls of 29, 22, 28 and 31 (Model output, `letters-v2-real`; with `letters-v2-ccby` the same read keeps 128 against 27, 24, 35 and 45 and peaked at about 250 MB). With the `reader` extra alone, no zarr, the TIFF is decoded whole as uint8 before it is averaged: the same read peaked at about 3.7 GB (39 s, the same counts), so on a machine with 4 to 8 GB install zarr first. The table's `--letter-mm 3.3 --um-per-px 2.399` form of the same command, with zarr, averaged by 42 to 990 rows by 1,895 columns and kept 118 against 35, 32, 32 and 32 in 32 s and about 240 MB (`letters-v2-real`; `letters-v2-ccby` keeps 120 against 30, 25, 41 and 35) ([Letter size matters most](#letter-size-matters-most) says why the two forms differ). The same command before this change stopped with a MemoryError after 23 s, asking for a 12.3 GiB float32 array. The same map averaged 16 by 16 (`--letter-px 86`, 2,600 by 4,975 pixels, under the budget) reads exactly as before, with the same letters, boxes, confidences and control counts: 20 to 23 s and 420 MB, against 23 s and 443 MB before.

### From Python

`read(image, weights, **options)` is the entry point, with a fixed contract:

- **image**: a 2D array of numbers. Size-1 axes are dropped, and a colour array with its channels last, `(H, W, 3)` or `(H, W, 4)`, is made grey as `load_image` makes a colour TIFF: the mean of its first three channels (alpha left out). Anything else (channels first, 1D, empty, text, a file name) stops with an error that says what to give. Files are read with `load_image(path)`, or `load_reduced(path)` for big maps.
- **weights**: a released model name (`"letters-v2-ccby"`, which `R.DEFAULT_WEIGHTS` names, or `"letters-v2-real"`, downloaded once and checked as on the command line), a path to a `linenet-v1` `.npz`, or a `LineNet` already loaded (`load_weights(name or path)`), which is fastest for many reads.
- **options**: `analyze()`'s keyword options, the command line's options under their Python names (`letter_px`, `polarity`, `columns`, `nulls`, `seed`, `deskew_deg`, `lines`, `p_min`, `min_letters`, `lm`, `lm_weight`, `beam`, ...), plus `control`, `rotate`, `mirror` and `orientation`. They are checked before any work: a letter height that is not a number of at least 4 pixels, a number of nulls outside 0 to 64, a polarity other than `bright`, `dark` or `auto`, a `columns` other than `auto`, `off` or a whole number of at least 1, an unknown option name, and the like stop with an error naming the option and what to give (`check_options()`). With a language model (`lm=`) and no `lm_weight`, the weight is 0.5, as on the command line (`LM_WEIGHT`).
- **result**: a dict that `json.dumps` writes as it is, starting with the model-output note and its provenance (schema number, reader version, the weights' released name, file name and SHA-256, the seed) and ending with the options used; [The result, field by field](#the-result-field-by-field) lists every field. `text_summary(res)` prints it as the command line does, with a provenance line under the note.

```python
from kit import letterread as R
net = R.load_weights("letters-v2-ccby")           # once; a name, a path, or pass the name to read() each time
img = R.load_image("MAP.png")                     # .npy, .npz, .tif or .png/.jpg; 2D float array
res = R.read(img, net, letter_px=86)
print(R.text_summary(res))
print(res["weights"]["name"], res["weights"]["sha256"], res["schema"])   # what read it, for the record
for line in res["lines"]:
    print(line["column"], line["y"], line["ink_only"])   # '·' marks a letter slot under the confidence floor
    for l in line["letters"]:
        l["glyph"], l["p"], l["kept"], l["box"]           # box is [y0, y1, x0, x1] in input pixels
print(res["control"]["status"], res["control"]["ratio"])  # strong, weak, none, too_few or no_control
print([c["control"]["status"] for c in res["columns"]])   # one status per column
res2 = R.read(img, net, letter_px=86, control=R.load_image("MAP_reverse.png"))   # a control map of the same shape
print(res2["control"]["control_map"])                     # its kept letters and the ratio to them
R.overlay(img, res, "MAP-letters.png")

# a whole map: block-averaged while it loads when over the budget; boxes come back in input pixels
img, k, shape = R.load_reduced("MAP-2.4um.tif", letter_px=R.letter_px_from_units(3.3, 2.399))
a = R.normalize_for_reading(img)                  # normalise once
res = R.read(a, net, normalized=True, input_scale=k,
             letter_px=R.letter_px_from_units(3.3, 2.399), letter_px_fallback=False)
R.overlay(a, res, "MAP-letters.png", normalized=True)    # draws the reduced image; boxes are mapped

# a photograph (EXIF orientation applied as it loads), read the way its polarity reads best, turned a quarter
img = R.load_image("PHOTO.jpg")
res = R.read(img, net, letter_px=28, polarity="auto", rotate=90)
print(res["polarity"]["used"], res["polarity"]["trial"]["dark"])  # dark or bright, and the quick read's counts
R.overlay(img, res, "PHOTO-letters.png")                  # drawn as given; boxes in input pixels
```

A read can be repeated from its own record: on the same image, `R.read(img, net, **{k: v for k, v in res["options"].items() if k in R.ANALYZE_OPTIONS and k != "lm"}, rotate=res["options"]["rotate"], mirror=res["options"]["mirror"])` gives the same letters (a test checks it). Give `normalized=True` again if you normalised the image yourself, and pass the language model and the control map again; the record holds their names, not the objects.

### Tilted, turned and mirrored text

**Tilt.** Each column is sheared by the angle, within `--deskew` degrees either way (default 6, in steps of 0.5, symmetric about 0), that makes its row profile most peaked, so its lines run level. The shear turns about the column's horizontal middle: a line's `y`, found or given, is its row at that middle, and at column x the line lies at row y + (x - (x0 + x1) / 2) * tan(deskew_deg), with x0 and x1 the column's edges (the whole image width when `--lines` is given). Letter boxes are mapped back through the shear, so they sit on the tilted line. When the angle found is the limit of the search, the column has `deskew_at_limit: true`, the result a `deskew_warning`, and the summary and stderr say so: the lines may be tilted more, so read again with a larger `--deskew`, or with `--rotate` when the lines run up and down. `--deskew 0` reads level bands.

**Given lines.** `--lines Y ...` are rows at the image's horizontal middle and follow the deskew like found lines (Python's `analyze()` has always done this, and the PHerc. 1667 benchmarks were run that way). On a tilted image, give the row where each line crosses the middle of the image, or give `--deskew 0` and the bands stay level, so a tilted line drifts out of its band away from the middle. A test shears a page by 3 degrees and checks both: with the deskew, the letters on the given rows are those of the level page; with `--deskew 0` they are not.

**Turned and mirrored images.** `--rotate 90` (or 180, 270) turns the image that many degrees clockwise before reading, and `--mirror` flips it left to right first; use them when the lines run up and down, or when an image was stored mirrored. Letter boxes come back in input pixels, the pixels of the file as given (after its EXIF orientation, below); each letter's `view_box` is its box in the turned image, and lines' `y`, columns' `x0` and `x1` and any `--lines` are in the turned image, which the result's `view` block describes. The overlay draws the image as given, with the boxes on it. The orientation reads are made on the turned image, and `orientation.best_view` names the `--rotate` and `--mirror` that would read the input as their best.

**EXIF orientation.** A JPEG or PNG with an EXIF orientation tag (cameras and phones set one) is turned by it as it loads, so its pixels, `--crop` and the boxes are those of the image as a viewer shows it; the result records `exif_orientation`, and the reader says so on stderr. TIFF, `.npy` and zarr images are read as stored.

### Reading a photograph

A photograph of a papyrus shows dark ink on a light ground, the opposite of an ink map, and the network only ever sees bright ink: `--polarity dark` inverts the image before reading, and the default, `--polarity bright`, does not. A photograph read with the default keeps no more letters than its nulls.

**`--polarity auto`** first reads the image quickly both ways, as one step of the scale search: at the letter size, up to 8 lines, two nulls each, as it is and inverted. It keeps the polarity whose letters kept exceed its own largest null by more (bright on a tie) and then reads the image exactly as that `--polarity` would; the result records both quick reads as `polarity.trial`, and the summary prints them. On the two photographs below it added 17 to 28 s to reads of about a minute. The polarity is chosen on the image as given (after `--rotate` and `--mirror`), and so is the letter size when none is given, so for an image whose lines run up and down give `--rotate` as well.

Why not grey levels (Interpretation, from the measurements below). The earlier guess, which Python's `normalize(a, "auto")` still makes, calls an image dark ink when its median grey sits nearer the light end. That fails for a fragment of brown papyrus on a white background, the usual museum photograph: the median falls on the papyrus, nearer its dark ink than the white, and the guess called both photographs below bright ink. A quick read asks only which way letters appear.

**A failed read checks the other polarity.** When a read with a given polarity ends `none` or `too_few`, the reader makes the same quick read both ways and records it as `polarity.trial`. When the other polarity's quick read is `strong` and beats the one used, the result carries `polarity.hint`, printed on stderr and in the summary, as here for P.Oxy. 1183 read with the default polarity and `letters-v2-real`:

```
hint: this image reads better as dark ink on a light ground (a photograph or a page scan): a quick read as dark ink keeps 81 letters against nulls of 18, 8, as bright ink 1 against 10, 8; read it again with --polarity dark (or auto)
```

The orientation counts of such a read are in the polarity the hint advises against, and the summary says so beside them.

**Overlay, EXIF and letter size.** The overlay draws the image as given, a colour photograph in colour with its ink dark, turned by its EXIF orientation as it loads (see [EXIF orientation](#tilted-turned-and-mirrored-text)). A whole photograph of a fragment on a plain ground has no regular line spacing for the size estimate (neither photograph below has one, in either polarity), so the command stops and asks for the size: measure a letter on screen and give `--letter-px`, or `--crop` the written area (on P.Oxy. 551, a crop of its written rows gave an estimate of 23.3 px against about 22 px measured by eye). A dark-ink read fills the rows the deskew shears in with the image's median grey, its ground; filled with 0, as before, the sheared-in corners are darker than the ground and pull the deskew to its limit (below).

**Synthetic pages** (Model output, 14 October 2026; `python scripts/letters/eval_photos.py --weights letters-v2-real`, 9 minutes on 2 CPU threads). Twelve photograph-like pages from `letterdata.py` (dark ink on a light papyrus ground, 8-bit grey, 4 to 7 lines of letters 18 to 30 px tall, each page turned 2 to 5 degrees), read at the true letter height with four nulls:

| Read | Status | Character error | Deskew within 1 degree | Deskew at its limit |
| --- | --- | --- | --- | --- |
| `--polarity bright` (default) | `none` 11, `too_few` 1; hint on all 12 | 0.895 | 1 of 12 | 11 of 12 |
| `--polarity dark` | `strong` 11, `weak` 1 | 0.055 (732 letters) | 8 of 12 | 0 of 12 |
| `--polarity auto` | chose dark on all 12; the same reads as dark | 0.055 | 8 of 12 | 0 of 12 |
| dark, sheared-in rows filled with 0 (as before) | `strong` 12 | 0.076 | 2 of 12 | 10 of 12 |

Turned a quarter turn, so the lines run up and down, and read with auto: the orientation reads named `rot90` the best on 10 of 12 pages. Auto's quick read on these turned pages chose bright ink on 3 of 12, and on 2 of those the orientation reads named another view; with `--rotate 90` the quick read chose dark on all 12. On a white mount (grey 250 of 255, 60% of the frame) auto and the grey-level guess both chose dark on all 12. On a dark mount (grey 20, 60% of the frame) neither works: the dark-ink quick read kept no letters on any page, the bright one 2 to 17 against largest nulls of 5 to 16, so auto's choice (dark on 8 of 12) rests on counts no better than chance, and the grey-level guess chose bright on all 12. Crop a photograph on a dark mount to the papyrus. On 24 pages with no letters (12 photograph-like, 12 ink-map-like from `eval_pages.py`), every read was `none`, with auto and with the fixed polarity (dark for photographs, bright for maps); 24 pages show only that choosing the polarity by letter counts does not make false passes common.

**Two real photographs** (Model output, 14 October 2026, read with `letters-v2-real`). Both are on Wikimedia Commons, marked public domain, from Princeton University Library (Sourced fact): P.Oxy. 551, AM 4405, Homer, Iliad XIV ([image](https://upload.wikimedia.org/wikipedia/commons/b/bf/Papyrus_Oxyrhynchus_551_-_Princeton_University_Library%2C_AM_4405_-_Homer%2C_Iliad_XIV%2C227%E2%80%93253%2C256%E2%80%93263.jpg), 2148 px wide by 1939 tall, SHA-256 `feac2ca61462d85f36d094e78593493bfd85f7fefc1d22ff2218475dbdc826b5`), and P.Oxy. 1183, AM 4097, Isocrates, Trapeziticus ([image](https://upload.wikimedia.org/wikipedia/commons/6/6c/Papyrus_Oxyrhynchus_1183_-_Princeton_University_Library%2C_AM_4097_-_Isocrates%2C_Trapeziticus_44%E2%80%9348.jpg), 1750 px wide by 2571 tall, SHA-256 `d35d4a1a430caf596b53954728fd40f9193bf9237295544b20a1bbcdb47de27d`). The images are not in this repository. Each is brown papyrus on white with no EXIF orientation, read whole with the letter height measured by eye and four nulls:

| Photograph | `--polarity bright` (default) | `--polarity dark` | `--polarity auto` |
| --- | --- | --- | --- |
| P.Oxy. 551, `--letter-px 22` | `none`: 4 letters kept, nulls 45, 10, 38, 24; hint (quick read as dark ink 155 against 41, 18; as bright 1 against 11, 8) | `strong`: 394 kept, nulls 105, 19, 122, 33, ratio 3.23; 20 lines in one column | chose dark; letters, boxes and controls the same as dark |
| P.Oxy. 1183, `--letter-px 28` | `none`: 3 kept, nulls 21, 17, 29, 15; hint (dark 81 against 18, 8; bright 1 against 10, 8) | `weak`: 188 kept, nulls 76, 49, 84, 38, ratio 2.24; 26 lines in one column | chose dark; the same as dark |

The orientation reads in dark ink kept the most as the photographs are stored: 394, against 294 mirrored, 307 turned 180 degrees and 113 and 122 turned 90 and 270 (P.Oxy. 551); 188, against 160, 181, 98 and 127 (P.Oxy. 1183). By eye (Interpretation): on P.Oxy. 551 the boxes sit on written lines, but its two columns were read as one, since the space between them is not empty from top to bottom, and the written lines between rows 590 and 968 got no line at all; on P.Oxy. 1183 boxes sit on parts of many written lines and many others got none.

**Untested.** No character error was measured on a real photograph: no reference transcription aligned with these lines was at hand, so how well the reader names letters on whole photographs is untested. The statuses above say only that confident letters stand above the nulls; the measured character errors are for synthetic pages. Fragments with ragged edges and columns also defeat the line and column finding; `--crop` one column at a time, or give `--columns N`. The numbers are in [`results.json`](results.json) under `letter_reader_checks` (14 October 2026).

### Optional language model

The network was trained on random letter strings, so it knows letter shapes and no Greek. A Kneser-Ney letter 5-gram model can be added as a second decode, always shown beside the ink-only string and never replacing it. The commands build it from Diogenes Laertius and Plato's Republic in the Perseus Digital Library's Greek texts (CC BY-SA 4.0), as in the log, and read with it:

```bash
git clone --depth 1 https://github.com/PerseusDL/canonical-greekLit work/perseus
python -m kit greeklm build work/letters/greek5.npz \
    work/perseus/data/tlg0004/tlg001/tlg0004.tlg001.perseus-grc2.xml \
    work/perseus/data/tlg0059/tlg030/tlg0059.tlg030.perseus-grc2.xml
python -m kit letterread MAP.png --weights letters-v2-ccby --letter-px 86 --lm work/letters/greek5.npz
```

When the two decodes disagree, the ink-only line is what the image supports. A large gap between them means the language model, not the ink, is doing the work.

## What the result means

`read()` returns, and `--json` prints, a JSON record whose every field is listed in [The result, field by field](#the-result-field-by-field), below; in short, one record per found line: its column, centre row `y`, the `ink_only` string, each letter's glyph, probability `p`, whether it cleared the confidence floor (`kept`) and its box `[y0, y1, x0, x1]`, all in input pixels, and the line's `n_kept` beside `chance`, the count the nulls make expected there (below). Beside them: `letter_px` and where it came from (`letter_px_from`; `letter_px_first_guess` and the `scale_search` table when it was estimated; `letter_mm` and `um_per_px` when given in units), `letter_px_check` (a given size against the line spacing), `input_scale`, `input_shape` and `reduced_shape` (see "Big maps"), `working_scale` (network pixels per input pixel), `columns` (each with its own `control` block, `deskew_deg` and `deskew_at_limit`), `deskew_deg` (the first column's), `deskew_max_deg`, `deskew_warning` when a column's angle is the limit of the search, `shear_fill`, `polarity` (`asked`, `used`, and the quick read both ways as `trial` when auto decided or the controls did not pass, with `hint` when the other polarity reads clearly better), `view` and each letter's `view_box` after a turned read, `exif_orientation` for a turned JPEG or PNG, `crop`, and, with `--overlay`, `overlay`: its file, `scale` (overlay pixels per input pixel), `banner_rows` and `size`, so a box edge at input row y and column x lands at overlay row banner_rows + y * scale and column x * scale. These controls travel with the result, and each can fail:

1. **Nulls.** The same reader on tile-shuffled copies (letter-sized tiles with random flips: local texture and grey levels kept, letters and lines broken) and phase-randomised copies (same power spectrum, so the same line spacing, shapes broken). The confidence floor is set so the nulls keep few letters (at most 5% of a line's letter slots, never below p = 0.5). `control.verdict` keeps its old wording, which compares letters kept on the image with each null only: "confident letters well above every null" (more than three times), "more confident letters than every null, but within a factor of three", or "confident letters NOT above the nulls: treat every letter here as noise". The benchmark scripts record it unchanged.
2. **Control map** (`--control MAP_REVERSE`, or `read(..., control=...)`). A second map of the same surface on the same grid, above all its reverse-depth ink map, read on the image's lines at the same letter size and confidence floor (details below).
3. **Status** (`control.status`). One code that a person or a pipeline acts on, from the nulls, the control map when there is one, and a minimum count; per column too.
4. **Orientation.** Letters kept as read, mirrored left to right, and turned 90, 180 and 270 degrees clockwise (`orientation.letters_kept`, keys `as_is`, `mirrored`, `rot180`, `rot90`, `rot270`), each at the main read's letter size and confidence floor with no nulls. Text the right way round should keep the most. This is weak for Greek capitals, many of which are symmetric, so it is evidence, not a gate; it does not enter the status. `orientation.best_view` gives the `--rotate` and `--mirror` that would read the input as the best of them, and the summary prints them when the best is not `as_is`; check by eye before reading again that way. On the w013 map below, with `letters-v2-ccby`: 120 as read, 96 mirrored, 96 turned 180 degrees, 29 and 27 turned 90 and 270 (Model output; `letters-v2-real` kept 122, 95, 104, 37 and 30).
5. **Language off.** `ink_only` never uses the language model.

### The status, and what to do

`control` holds `letters_kept`, `null_letters_kept`, `nulls`, `verdict`, then `min_letters` (10 by default, `--min-letters`), `ratio` (letters kept over the largest null, a null of 0 counting as 1; `null` in the JSON when no nulls were run), `status`, `status_text` and, with a control map, `control_map` (`letters_kept`, `ratio` and, from the command line, `file`). Each column's `control` block has the same fields for that column, plus `chance`. The rule, in order (`control_status()` in `kit/letterread.py`):

1. no nulls run: `no_control`;
2. letters kept not above the largest null, or not above the control map: `none`;
3. fewer than `min_letters` letters kept: `too_few`;
4. more than three times the largest null (and more than three times the control map, when there is one): `strong`;
5. otherwise `weak`.

Without a control map and with at least 10 letters, `strong`, `weak` and `none` are exactly the three old verdicts. The summary prints the old line, then the status line; the overlay banner carries the same status line under the model-output note, starting "Controls:". The status line names the code, the counts behind it and a fixed sentence, for example (the PHerc. 1667 w013 map below, read with `letters-v2-ccby`):

```
control: 120 letters kept vs nulls [31, 20, 33, 47]: more confident letters than every null, but within a factor of three
status: weak (120 letters kept; nulls 31, 20, 33, 47, ratio 2.55 to the largest). Confident letters above every control, but not three times above all of them: weak evidence.
```

With a control map, the summary adds `control map FILE: N letters kept on the same lines at the same confidence floor` and the counts gain `; control map N, ratio R`. The five sentences, exactly as printed, and what to do:

| `status` | Printed sentence | What to do |
| --- | --- | --- |
| `strong` | `Confident letters more than three times every control: worth a person's check, still model output and not a reading.` | Open the overlay and check the letters by eye, line by line; a person decides what is legible. On an ink map read without `--control`, read again with the reverse-depth map: the nulls alone do not rule out letters the ink model makes from papyrus structure. A pipeline may pass only `strong` reads (or `strong` columns) on to a person. |
| `weak` | `Confident letters above every control, but not three times above all of them: weak evidence.` | Do not use single letters. Check the letter size first (the scale-search table, any `letter_px_check` warning; give `--letter-px` or `--letter-mm`). Look at the per-column statuses and the per-line counts: when the letters sit in one column or a block of lines, read that area again as its own crop, chosen on what the map shows (below). Add `--control` if you have the reverse-depth map. |
| `none` | `Confident letters NOT above the controls: treat every letter here as noise.` | Treat every letter as noise. Common causes: a wrong letter size, the wrong polarity (`--polarity dark` or `auto` for photographs; the reader then checks the other polarity itself and prints a hint when it reads clearly better, see [Reading a photograph](#reading-a-photograph)), or no text the model can see. When `control_map.ratio` is 1 or below, the control map kept as many letters or more, so these letters are not particular to this map. |
| `too_few` | `Too few confident letters to judge (fewer than 10).` | Nothing can be judged either way. Read a larger area (more lines, or a whole column) and check the letter size. Do not lower `--min-letters` to get a pass. |
| `no_control` | `No control run (nulls=0): nothing here can be trusted.` | Read again with nulls (the default `--nulls 4`). |

### Where the letters are

Empty papyrus dilutes a whole-segment count: on a map where text fills a corner, the letters there sit among many lines with none. So the result also says where the letters are kept.

- **Per column.** Each column's nulls are scrambles of that column alone, read on its own lines, so each column has real null counts and gets its own `control` block and status by the same rule (with the control map's count in that column, when one is read). With several columns the summary prints one line per column, in the form `column I (x X0 to X1): STATUS (N letters kept; nulls A, B, C, D, ratio R to the largest), chance C`, where `chance` is the column's mean null count.
- **Per line.** The nulls scramble positions across the whole column (the tile shuffle moves letter-sized tiles anywhere in it, and phase randomisation spreads every shape over all of it), so a null's letters say nothing about which line they came from. The honest chance count for a line is therefore the column's mean null count spread evenly over its lines, `chance` = mean of the column's null counts / its number of lines; every line band spans the column's full width, so each line has the same letter slots. The summary prints it before each line's letters, as in `line  0 y=  209.6 [ 14 kept, chance  2.52]: ··Ν·ΡΟΕΥ····ΝΟΥ···Θ···ΦϹ····Ϲ·Η····Π··` (with `, control map N` added when a control map is read).

Per-line counts are small, so they show where to look; they are not a test. Choosing lines because they beat chance and then calling them text is circular. To test an area, choose it on something other than this read's letter counts (what the map shows, a label, a published column) and read it as its own `--crop`, which gets its own nulls and floor.

Example (Model output, 14 October 2026; PHerc. 1667 w013, a published scroll, its public map averaged to about 38 um, `--letter-px 86`, `letters-v2-ccby`): the whole map is one column of 13 lines, 120 letters kept against nulls of 31, 20, 33 and 47, status `weak`, ratio 2.55. The chance count is 2.52 per line (mean null 32.75 over 13 lines); lines 0 to 9 keep 8 to 16 letters each (108 of the 120) and lines 10 to 12 keep 2 to 6, so the kept letters sit on the upper ten lines. With `letters-v2-real`: 122 letters against 43, 33, 27 and 28 (ratio 2.84), 110 of them on lines 0 to 9.

### The control map

Read the reverse-depth map of the same surface with `--control`: villa's ink inference writes it beside the forward map with `--direction both` (as `NAME_reverse.tif`; see [mac.md](mac.md)). An ink model run on the layers in reverse order sees the same fibres, cracks and sheet edges at the same places, with the ink signal at the wrong depth, so letters that survive depth reversal are not ink.

```bash
python -m kit letterread MAP.tif --weights letters-v2-ccby --letter-px 86 --control MAP_reverse.tif --overlay MAP-letters.png
```

The control map must have the same shape as the image (the same `--crop` and `--key` are applied to it, and the same block size when the image is over the budget); a different shape stops the command before the read. So does a control map whose finite values are all the same, such as a failed render of all zeros: normalised, it is blank, keeps no letters, and so could never fail (`check_control()`; `read()` and `analyze()` refuse it too). It is normalised on its own, as any image the reader reads, and read on the image's columns, deskew angles and line rows at the image's letter size and confidence floor, with no nulls of its own. Both rules are deliberate: a map without text has no line structure, so read with its own layout it would get fewer lines and fewer chances to keep letters, and scaled by the image's grey levels a fainter control map would keep fewer letters; either would flatter the image. The control changes nothing else: the image's letters, boxes, floor, nulls and orientation counts are the same with and without it. It does not enter the scale search: without a given size, the size is chosen on the nulls alone and the control map is read at that size.

Check that it can fail (Model output, 14 October 2026, the same w013 map, `letters-v2-ccby`): with the map itself as its control, the control map keeps the same 120 letters and the status is `none`, as it must be; with a tile-shuffled copy of the map as a stand-in control (no public reverse-depth map of w013 was at hand; `null_images(img, 86, n=1, seed=100)`), the control keeps 42 letters, ratio 2.86, and the status stays `weak`. `letters-v2-real` kept 122 and `none` with the map itself, and 37 letters (ratio 3.30) on that shuffled copy, 40 (ratio 3.05) on the copy used when this section was first written; its status stayed `weak` because of the nulls.

### Why these rules

**More than three times every control for `strong`** (Interpretation). One factor for every control keeps `strong` meaning one thing, and it is the factor the old verdict already used for the nulls. Read as a rate, a control's count estimates how many of the image's confident letters the reader would make without the image's text; more than three times means that estimate is under a third of what the image keeps. The control map is the stricter control for an ink map, since it keeps the surface's real structure in place, so it gets the same factor, not a lower one; it is paired with the image letter slot for letter slot, so its count needs no allowance for a different layout. A control map that keeps as many letters as the image, or more, makes the read `none`, whatever the nulls say.

**At least 10 letters** (a judgement, checked on public data). The factor of three counts a null of 0 as 1, so with quiet nulls any four letters were "well above every null", and a count of n carries about sqrt(n) of counting noise, a third of the count or more below 10. Measured on 14 October 2026 with `letters-v2-real` (Model output): the w013 map above cut into 20 windows of 520 by 1000 px (one to three found lines of about ten letter slots), and three tile-shuffled copies of it cut the same way (60 windows whose letter-sized tiles are scrambled, so lines and letters are broken, as in the tile-shuffle null), each read at 86 px with four nulls. On the shuffled windows, where a pass is a false one, the old verdict passed 17 of 60 (15 "more confident letters than every null", 2 "well above every null"), each on 1 to 5 letters; no shuffled window kept more than 5 letters, and the floor, twice that, makes all 17 `too_few`. It has a cost: on the map as stored, the old verdict passed 12 of 20 windows; 4 (10 to 16 letters) are `strong` now and 8 with 1 to 7 letters are `too_few`, 2 of them "well above every null" on 7 letters. Small windows near the floor are better read as part of a larger area. `--min-letters` changes the floor; raise it for a read that must be sure.

**`strong` means letter-like marks in rows, not letters** (Model output, 16 October 2026, `letters-v2-ccby`, adversarial test). The nulls break the arrangement of the image into lines but keep letter-sized stroke texture, so marks that are not letters pass when they sit in rows. Pages of random straight pen strokes, two or three per letter slot in the demo's hand and ground, read `strong` on all 8 tried (36 to 156 letters kept, 4.0 to 5.5 times the largest null), and one dash per slot still read `strong` (69 letters against nulls of 20 or fewer). Nulls that turn each letter-sized tile 180 degrees in place stopped every stroke page from reaching `strong`, but they also dropped the PHerc. 1667 drawings w018 and w023 from `strong` to `weak`, because the reader names real letters with less confidence than drawn ones and many capitals look alike turned; that change is not made. So a `strong` read still needs a person to look at the letters, and the orientation counts are a warning sign when the image read as it is keeps about as many letters as its mirrored and turned copies (random strokes kept 36, 35 and 35). Text that is turned or mirrored also reads `strong`, with wrong letters: orientation is evidence, not part of the status.

**`weak` is not a pass** (Model output, 14 October 2026, `letters-v2-real`). On 24 synthetic pages with no letters (`eval_pages.py`'s blank pages, 12 papyrus-like texture and 12 clutter, seeds 21 and 22), each read twice with four nulls, once with the size searched and once with the true 24 px given, 47 of the 48 reads are `none`; one texture page read at a searched size kept 134 letters against a largest null of 126 (ratio 1.06), which is `weak`. A page with no text at all can be `weak`, which is why the advice for `weak` starts with the letter size.

The numbers are in [`results.json`](results.json) under `letter_reader_checks` (14 October 2026), and both checks rerun with `python scripts/letters/eval_controls.py windows MAP.tif --weights letters-v2-real` (on the w013 map averaged 16 by 16; defaults: 86 px, 520 by 1000 px windows, three shuffled copies) and `python scripts/letters/eval_controls.py blanks --weights letters-v2-real`.

### The result, field by field

Schema 1 (14 October 2026). `schema` is raised when a field is renamed or removed or changes its meaning; new fields keep the number, so read fields by name and ignore ones you do not know. The tables cover `read()`, which the command line calls; `analyze()` (no orientation reads) returns the same fields except `orientation`, `letter_px_check` and `view`, has `polarity` only when it decided `auto`, and its `options` lack `rotate`, `mirror` and `orientation`. Units are input pixels: the pixels of the image as given, after its `--crop` (rows and columns relative to Y0, X0) and its EXIF orientation, before any block-averaging. No field holds a local folder: files are named by their file name only.

**Every box's height is the line band.** A letter's `box` is `[y0, y1, x0, x1]`. Its rows are the line's band, one letter height (`letter_px`) centred on the line's row, moved by the column's deskew at the box's horizontal centre: every letter on a line has the same height, set by the line, not measured on the letter, so a box says which line a letter is on, not how tall its ink is. Its columns come from the letter's own output frames, widened by 0.3 letter heights on each side, so boxes of neighbouring letters overlap. After a read turned by 90 or 270 degrees the lines run up and down in input pixels, so there the band is the box's width; `view_box` keeps the box in the turned image.

Top level:

| Field | Meaning |
| --- | --- |
| `note` | "Model output: letter hypotheses from a learned line reader, not a reading. A papyrologist decides what is legible." |
| `schema` | The result's schema number, 1 |
| `reader` | `module` (`kit.letterread`) and `version`, the kit package's version (`kit.__version__`) |
| `weights` | `name` (the released model whose SHA-256 the file has, or `null`), `file` (file name only), `sha256` and `format` (`linenet-v1`) |
| `seed` | Seed of the null copies (the quick polarity reads use seed + 1) |
| `engine` | `linenet` |
| `letter_px` | Letter height the read used |
| `working_scale` | Network pixels per input pixel |
| `deskew_deg` | The first column's deskew angle in degrees (each column has its own in `columns`) |
| `p_min` | Confidence floor: letters at or above it are kept |
| `lines` | One record per line, column by column, left to right (below) |
| `columns` | One record per column (below) |
| `control` | The controls of the whole read (below) |
| `input_shape` | `[H, W]` of the input window |
| `input_scale` | Block size k the image was averaged by while loading (1 when it fit the budget) |
| `reduced_shape` | `[H, W]` of the image read, only when `input_scale` is over 1 |
| `letter_px_from` | `given`, `line pitch` or `image height / 4`, with `, then scale search` when the size was searched |
| `letter_px_estimated` | `true` unless the size was given |
| `letter_px_first_guess` | The estimate the scale search started from (only when estimated) |
| `scale_search` | Only when estimated: per scale `letter_px`, `letters_kept`, `null_letters_kept` (two nulls) and `margin` (kept minus the largest null); the largest margin was kept |
| `deskew_max_deg` | The deskew search's limit, degrees either way (0: off) |
| `shear_fill` | Grey of rows the deskew shears in (0 for bright ink, the image's median for dark ink) |
| `deskew_warning` | Only when a column's angle is the limit of the search: what to do |
| `letter_px_check` | Only when the size was given and the image shows a line pitch: `line_pitch_estimate`, `ratio` (given over estimate) and, beyond 2x either way, `warning` |
| `orientation` | `letters_kept` as read and turned (`as_is`, `mirrored`, `rot180`, `rot90`, `rot270`), `best`, `best_view` (`rotate`, `mirror` that read the input as the best), `note` and `turns` (fixed sentences) |
| `view` | Only after `--rotate` or `--mirror`: `rotate`, `mirror`, `shape` (of the turned image, in input pixels) and `note` |
| `polarity` | `asked` (`bright`, `dark` or `auto`) and `used` (`bright` or `dark`); `background` when the reader normalised the image itself (where its median grey lies between the 0.5th and 99.8th percentiles, 0 to 1; a description, not a rule); `rule` (how auto decides) when auto was asked; `trial` (the quick reads both ways, `polarity_trial()`: `rule`, `letter_px`, `choice`, and for `bright` and `dark` each its `letters_kept`, `null_letters_kept`, `margin` and `status`) when auto decided or the controls did not pass; `hint` when the other polarity reads clearly better |
| `options` | Every option of the read with the value used (below) |

Added by the command line: `source` (`file`, the image's file name, and `key`), `exif_orientation` (only for a turned JPEG or PNG, 2 to 8), `letter_mm` and `um_per_px` (only when the size was given in units), `crop` (`[Y0, Y1, X0, X1]`, only with `--crop`), `image_shape` (`[H, W]` of the whole image file, the array at `--key` for a zarr or `.npz`, a JPEG or PNG the way round a viewer shows it; it places a crop in the file for the exports), `overlay` (only with `--overlay`: `file`, `scale` in overlay pixels per input pixel, `banner_rows`, `size` as `[height, width]` and `max_side`; a box edge at input row y and column x lands at overlay row `banner_rows + y * scale` and column `x * scale`), `control.control_map.file` and `options.max_mpx`. The demo adds `source` with `file`, `map` (the public address of the map it read, `null` when a cached map has no note of it), `grid`, `crop` and `weights` (file name).

A line (`lines[i]`):

| Field | Meaning |
| --- | --- |
| `line` | Index over the whole read |
| `column` | Index of its column |
| `y` | Centre row of its band at its column's horizontal middle (in the turned image after a turned read) |
| `ink_only` | The letters decoded from the ink alone, `·` for a letter slot under the floor |
| `letters` | One record per decoded letter (below) |
| `n_kept` | Letters kept on the line |
| `chance` | The column's mean null count over its lines: the count the nulls make expected on one line (`null` with no nulls) |
| `control_map_kept` | Only with a control map: its letters kept on the same line |
| `with_lm` | Only with a language model and a weight over 0: the beam decode with it, beside `ink_only`, never replacing it |

A letter (`lines[i].letters[j]`): `glyph` (one of the 24 capitals, lunate sigma for sigma), `p` (its confidence, 0 to 1), `kept` (`p` at or above `p_min`), `box` (above), and `view_box` after a turned read.

A column (`columns[i]`): `x0` and `x1` (its edges, in the turned image after a turned read), `deskew_deg`, `deskew_at_limit`, `lines` (how many) and `control`, a block like the read's without `nulls` and `verdict`, with `chance` (its mean null count).

The controls (`control`):

| Field | Meaning |
| --- | --- |
| `letters_kept` | Letters kept on the image |
| `null_letters_kept` | Letters kept on each null copy, at the same floor |
| `nulls` | Per null its `kind` (`tile_shuffle` or `phase`) and `letters_kept` |
| `verdict` | The old wording, kept unchanged for the benchmark scripts |
| `min_letters` | The floor of letters a read needs before it can pass (10 by default) |
| `ratio` | `letters_kept` over the largest null (a null of 0 counting as 1); `null` without nulls |
| `status`, `status_text` | `strong`, `weak`, `none`, `too_few` or `no_control`, and its fixed sentence ([The status, and what to do](#the-status-and-what-to-do)) |
| `control_map` | Only with a control map: `letters_kept`, `ratio` and, from the command line, `file` |

The options (`options`), each with the value the read used, given or default: `letter_px` (given, or `null` when estimated), `polarity` (as asked), `nulls`, `seed`, `deskew_deg` (the search's limit), `lines` (given rows, or `null`), `p_min` (given, or `null` when set from the nulls), `null_rate`, `lm_weight` (`null` without a language model), `beam`, `scale_search`, `columns`, `input_scale`, `letter_px_fallback`, `min_letters`, `shear_fill` (as given, `null` for the default), `lm` (`null`, or the model's `file`, `sha256` and `order`), and for `read()` `rotate`, `mirror`, `orientation` and `control_map` (whether a control map was read); the command line adds `max_mpx`, its pixel budget in millions of pixels.

### Exports: CSV and PAGE XML

`--csv OUT.csv` and `--page-xml OUT.xml` write the letters of a read in two standard forms, beside `--out` (or from Python, `from kit import letterexport as E`, then `E.write_csv(res, "OUT.csv")` and `E.write_page_xml(res, "OUT.xml", image_filename="MAP.png")`). Both hold Model output only: letter hypotheses, not a reading. Their folders are checked before the read, and both are written before the summary is printed.

**Coordinates.** Both write every box in the pixels of the whole image file: the result's boxes (input pixels, already mapped back through block-averaging and through `--rotate` and `--mirror`) plus the crop's Y0 and X0 when `--crop` was given. For a JPEG or PNG with an EXIF orientation tag, those are the pixels of the image as a viewer shows it. The command line records the whole image's size as `image_shape`, which places the crop; in Python, a result read from a window needs `image_shape=(H, W)`.

**CSV.** A header row, then one row per decoded letter, line by line: `column`, `line`, `index` (the letter's place on its line, from 0), `letter`, `p` (its confidence), `kept` (`true` at or above the confidence floor, `false` below it, where the line's `ink_only` writes `·`) and its box `y0`, `y1`, `x0`, `x1` to 0.1 pixel. UTF-8 without a byte-order mark: a spreadsheet may need to be told so (in Excel, Data, From Text/CSV, UTF-8) to show the Greek letters.

**PAGE XML.** The PAGE 2019-07-15 schema of PRImA ([schema](http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15/pagecontent.xsd)), with `imageFilename` the image's file name and `imageWidth` and `imageHeight` its size:

- `Metadata`: the creator (`kit.letterread` and its version), the time, `Comments` holding the model-output note, the status line of the controls and the provenance line (weights, SHA-256, reader version, seed), and a `MetadataItem` of type `processingStep` whose labels repeat them one by one (`output` is "Model output, not a reading").
- A `TextRegion` per reader column, left to right as read (also listed in `ReadingOrder`), its `Coords` the bounding box of its lines.
- A `TextLine` per line: `Coords` its band (one letter height along the column, following the column's deskew), `Baseline` the band's lower edge from the line's start to its end as read (so after a turned read it runs the way the text does), `comments` its kept letters beside its chance count, and the language-model decode when one was run (never as its text).
- One `Word` per line, since Herculaneum texts are written without word division, holding a `Glyph` per letter with its box as `Coords` and a `TextEquiv`: a kept letter with `conf` its p; a letter under the confidence floor as `·`, with no `conf`, and its best letter and p in its `comments`. So the text of every glyph, word and line is the line's `ink_only` string, and an editor shows a `·` where the reader saw a letter it was not confident of.
- Coordinates are whole pixels clipped to the image; `TextRegion` and `TextLine` also carry Transkribus's `readingOrder {index:N;}` in their `custom` attribute.

The tests check that the file is well-formed XML with every element in the schema's order and every glyph at its box in the image file's pixels, after a crop, block-averaging, two columns and a quarter turn. On 14 October 2026 the PAGE files of those cases and of the w013 read under "Where the letters are" were also checked against PRImA's 2019 schema with lxml, and all were valid (the test suite does not do this, as it would need the schema file). So was the PAGE file of a read of a crop of w013's whole 2.4 um map (`--crop 2000 30000 1000 60000`, block-averaged by 42 while loading): its page is the whole map's 79,600 pixels wide by 41,600 tall, and all 195 glyphs sit at their boxes plus the crop's corner, as do the CSV's rows.

**Where they open** (14 October 2026; neither tool was run with these files):

- **eScriptorium** (Sourced fact, from its source code, [`app/apps/imports/parsers.py`](https://gitlab.com/scripta/escriptorium/-/blob/develop/app/apps/imports/parsers.py) on its `develop` branch): its PAGE import accepts the 2013, 2016, 2017, 2018 and 2019 schemas, named by `xsi:schemaLocation`, and validates a file against it; it matches a page to an uploaded image by `imageFilename` ([import guide](https://escriptorium-tutorial.readthedocs.io/en/latest/import/)); it warns that a line without a `Baseline` is very likely not usable; when a line has `Word` elements it takes the line's text from them; and it reads `Word/Glyph` elements as one polygon, letter and confidence per character. This export was shaped to fit that code: a baseline on every line, one word per line, a glyph per letter.
- **Transkribus** (Sourced fact): its help page on exports ([help.transkribus.org/downloading](https://help.transkribus.org/downloading)) links its PAGE format definition, [`pagecontent_extension.xsd`](https://gitlab.com/readcoop/transkribus/TranskribusCore/-/blob/master/src/main/resources/xsd/pagecontent_extension.xsd), which is the 2013-07-15 schema with Transkribus additions and has `Word` and `Glyph`; its upload interface takes a PAGE file beside each image ([REST upload](https://www.transkribus.org/blog/transkribus/docu/rest-api/upload)). I found no public page saying Transkribus imports the 2019 schema, so a 2019 file may need converting to 2013 before Transkribus reads it (Interpretation, untested).

The exports carry machine letter annotations, like the overlay: keep them out of prize images. Uploading one to a shared eScriptorium or Transkribus server publishes the read, so for a scroll whose text is unpublished keep the files private ([Rules for using it on scrolls](#rules-for-using-it-on-scrolls)).

## How well it reads

All numbers are Model output on public data, measured on CPU with the numpy reader, except the real-letter validation row (row 6), which is the trainer's own check on the B200. [Reproduce the benchmarks](#reproduce-the-benchmarks) gives the command for each row, and each benchmark script prints the row its settings reproduce before its numbers. Character error is edit distance over reference letters; 0.10 means about one edit per ten letters. "Free ends" does not charge letters read before or after the reference, because a map window also shows unlabelled neighbours. Each PHerc. 1667 test's rule was fixed in writing on 9 October 2026 before the readers it compares were run on it; the PHerc. 172 row is a diagnostic, because its column rule was set after that test half had been seen (conditions in the [log](logs/2026-10-14-letter-reader.md)). "Synthetic-only" is letters-v1: the same network, data size and training, with no real letters in its training lines.

The table is `letters-v2-real`'s card as first published, scored on the PHerc. 1667 references of 9 October 2026. The permissive weights, `letters-v2-ccby`, were compared with `letters-v2-real` on 14 October on the same benchmarks, with PHerc. 1667 references rebuilt because the 9 October ones were lost, so `letters-v2-real`'s PHerc. 1667 numbers there differ from this table: see [Benchmarks: letters-v2-ccby against letters-v2-real](#benchmarks-letters-v2-ccby-against-letters-v2-real). In short (Interpretation), `letters-v2-ccby` errs more than `letters-v2-real` on one PHerc. 1667 map row, the other PHerc. 1667 and PHerc. 172 test comparisons are not resolved, and it errs less on Hell-Char validation lines.

| Row | Test (letters-v2-real, step 30000) | Reference | Letters | Character error | Comparison |
| --- | --- | --- | --- | --- | --- |
| 1 | PHerc. 1667 official ink labels (drawings), line given | 3 blind machine transcriptions, unanimous groups only | 122 | **0.025** ink only | synthetic-only reader 0.320, prototype 0.402 |
| 2 | Same 87 groups read from the 2.4 um ink maps, line given | same | 122 | **0.369** free ends (0.370 when re-measured on 13 October; [log](logs/2026-10-14-letter-reader.md)) | synthetic-only 0.705 |
| 3 | Maps, windows about three lines tall, reader finds the line | same | 122 | 0.402 free ends (0.393 with nothing given) | synthetic-only 0.746 |
| 4 | Maps, each segment's whole labelled region read once, nothing given | same | 122 | **0.336** free ends; 52 of 87 groups fully right | synthetic-only 0.590 |
| 5 | PHerc. 172 hand-drawn labels (Bodillium), test half, columns found | the labeller's preliminary transcription | 122 | 0.426 ink only (diagnostic) | prototype 0.625, synthetic-only 0.739 |
| 6 | Real-letter validation lines from 21 papyri it never saw (Hell-Char) | the crops' letter labels | first 600 of 2,000 lines | 0.444 | CPU real-letterform reader about 0.52 |

What this supports (Interpretation): with the line and letter height given, naming clean drawn Greek capitals is close to solved for `letters-v2-real` (3 errors in 122 letters). On real ink maps it finds about two of every three letters in order. Maps cost it about 0.33 of error against the drawings; which letters the maps lose, and how much of that gap is the reader rather than the map, has not been measured.

What it does not support:

- **Maps of text no ink model has seen.** The six labelled PHerc. 1667 segments are in `ink_9um`'s training labels, and the training set of the 2.4 um model that made their maps is not checked, so their maps may be cleaner than maps of new text. On the thirteen PHerc. 1667 segments without labels, whole-map reads gave no ordered pairs of lines matching the published text (a test with little power, since it found pairs only on the two labelled segments where the letter error is lowest).
- **A reading.** The references are machine transcriptions of drawings and one labeller's preliminary transcription, not a papyrologist's reading, and 122 letters cannot show an accuracy finer than about 1 to 3 percent.
- **Letter size found automatically on new maps.** On the unlabelled segments the scale search chose letter heights of 32 to 615 grid pixels against 74 to 103.5 measured on the labelled ones. Give `--letter-px`, or `--letter-mm` with `--um-per-px`, when you can.

## Which weights

Two models are released, with the same network and the same reader code; [`kit/data/letter-weights.json`](../kit/data/letter-weights.json) lists both, their fixed hashes and the selection profiles. `--weights` takes either name or your own weights file and always preserves that explicit choice.

| | `letters-v2-ccby` | `letters-v2-real` |
| --- | --- | --- |
| Licence | CC BY 4.0 | CC BY-NC 4.0 |
| Real letters in its training lines | Hell-Char only (10,857 crops of 123 papyri) | Hell-Char and ICDAR 2023 (43,806 crops) |
| Checkpoint chosen on | Hell-Char validation lines from 21 papyri held out of training | the PHerc. 172 dev half |
| Card | [letters-v2-ccby](#model-card-letters-v2-ccby) | [letters-v2-real](#model-card-letters-v2-real) |

The default now follows the task, using the public comparison below (17 October 2026). With `--lines`, the command selects the `ink-lines` profile and `letters-v2-real`. Without given line positions it selects `permissive` and `letters-v2-ccby`. This chooses before reading any pixels or scoring any output; it does not try both and select whichever produces more letters. Use `--weight-profile` to override the task choice, or `--weights` for a particular checkpoint or file; the two options cannot be combined. The command reports the profile and license, and its result records the selected weights and hash.

| Profile | Weights | When to use it |
| --- | --- | --- |
| `ink-lines` | `letters-v2-real`, CC BY-NC 4.0 | Noncommercial research on ink-map lines. In the published PHerc. 1667 test with line positions and letter height given, free-ends error was 0.376 against 0.462 for `letters-v2-ccby`; the paired difference was +0.085, 95% interval +0.017 to +0.155 |
| `permissive` | `letters-v2-ccby`, CC BY 4.0 | Automatic page reads, photographs, commercial use or sharing a permissively licensed fine-tune. The whole-region ink-map comparison was unresolved: 0.308 against 0.342 for `letters-v2-real`, difference -0.034, interval -0.118 to +0.048. Photo accuracy remains untested; this profile does not claim an accuracy win on photographs |

For example, a noncommercial ink-map read with a known line at row 120 selects the ink-line checkpoint. A permissive read can keep that checkpoint choice explicit even when its line position is supplied:

```bash
scrolls-letterread MAP.png --lines 120 --letter-px 86
scrolls-letterread MAP.png --lines 120 --letter-px 86 --weight-profile permissive
scrolls-letterread MAP.png --weight-profile ink-lines --letter-px 86
```

**Scope matters.** Neither checkpoint is established as best for every input. The PHerc. 172 development half helped choose `letters-v2-real`, so its advantage there is not independent evidence. `letters-v2-ccby` errs less on the Hell-Char validation lines. The map benchmarks use a small, previously studied set; they do not establish accuracy on new scrolls. All figures are Model output, and the model card below gives the controls and limitations.

The earlier all-purpose demo choice of `letters-v2-ccby` was for its permissive license (14 October 2026). The offline demo, public-map demo and CI still use it explicitly; `R.DEFAULT_WEIGHTS` remains that demo default. The Python `read()` API still takes explicit weights; `kit.letterweights.select_weights(lines_given=True)` returns the ink-line choice when an application wants the same policy as the command. No weights, release tags or hashes change. Fine-tunes inherit their starting checkpoint's terms: CC BY 4.0 from `letters-v2-ccby`, CC BY-NC 4.0 from `letters-v2-real`.

## Model card: letters-v2-ccby

| | |
| --- | --- |
| File | `letters-v2-ccby-step026000.npz` (5,933,674 bytes), format `linenet-v1` (BatchNorm folded into the convolutions), SHA-256 `b14988852fc721cce71e80a66db0a8ea99a1de914ef2b724ecc6e711baa9ed8c` |
| Where | the [`letters-v2-ccby` release](https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-ccby) of this repository (14 October 2026); the address is in [`kit/data/letter-weights.json`](../kit/data/letter-weights.json) |
| Network | the same as `letters-v2-real`: 2D convolutions (channels 48, 96, 160, 192, 256) over a 36-row band at a letter height of 16 px, collapsed to one row, then dilated 1D residual convolutions (dilations 1, 2, 4) and a 25-way CTC head (24 capitals with lunate sigma, plus the blank); 1,483,241 parameters as trained |
| Training data | 600,000 lines of uniform random Greek capitals, about 7% of them left blank (no Greek words or text). Glyphs come from a hand-coded broad-nib bookhand, from fonts installed from Debian packages (fonts-dejavu-core, fonts-freefont-ttf, fonts-gfs-artemisia, fonts-gfs-baskerville, fonts-gfs-bodoni-classic, fonts-gfs-complutum, fonts-gfs-didot, fonts-gfs-neohellenic, fonts-gfs-olga, fonts-gfs-porson, fonts-gfs-solomos, fonts-gfs-theokritos, fonts-liberation2 and fonts-noto-core; no font file is included), and, in about half the lines, from 10,857 letter crops of 123 papyri in Hell-Char. Every line is degraded to look like an ink-detection map or a drawn ink label. No ICDAR 2023 data and no scroll data were used to train or choose it |
| Training | from scratch for 30,000 steps (batch 128, AdamW one-cycle to 0.002) on one NVIDIA B200; the recipe (network size, steps, learning rate) is `letters-v2-real`'s, settled earlier while that model was checked on the PHerc. 172 drawings |
| Checkpoint choice | of the 15 checkpoints kept every 2,000 steps, the one with the lowest character error on 600 validation lines (the first 600 of 2,000, 549 of them with letters) built only from Hell-Char crops of 21 papyri held out of training: step 26,000, 0.416 (the lowest of 15, so optimistic). The PHerc. 1667 and PHerc. 172 labels took no part in training or choosing it |
| Intended use | Letter hypotheses on images of Greek capital text, for a person to check: triage of where letters are, review layers, research on reading ink maps |
| Not for | Claiming that a scroll says something; prize images (they must be generated programmatically without manual character annotations; whether machine letter overlays are allowed is not stated, so keep them out); publishing reads of a prize-eligible scroll before its prize is awarded (prize disclosure terms) |
| Licence | Weights: Creative Commons Attribution 4.0 International ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)), Copyright (c) 2026 Chase Hendrick. Code: Apache-2.0. Credit it as: letters-v2-ccby by Chase Hendrick, https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-ccby, CC BY 4.0. If you share the weights, please keep this credit and the Hell-Char credit below with them |

### Benchmarks: letters-v2-ccby against letters-v2-real

CPU, Model output, read with the public reader code at commit `7dc92e8` on 14 October 2026; paired differences are `letters-v2-ccby` minus `letters-v2-real`, computed before rounding, with 95% bootstrap intervals (20,000 resamples). An interval wholly below zero says `letters-v2-ccby` errs less, wholly above zero that it errs more; otherwise the comparison is not resolved.

| Test | letters-v2-ccby | letters-v2-real | Difference (95% interval) |
| --- | --- | --- | --- |
| PHerc. 1667 official ink labels, line and letter height given, character error ink only (84 groups, 117 letters) | 0.043 | 0.017 | +0.026 (-0.018 to +0.079) |
| Same groups read from the 2.4 um ink maps, line and letter height given, free-ends error | 0.462 | 0.376 | +0.085 (+0.017 to +0.155) |
| Maps, windows about three lines tall, the reader finds the line (letter height given), free-ends error | 0.479 | 0.410 | +0.068 (0.000 to +0.142) |
| Maps, each segment's whole labelled region read once, nothing given, free-ends error | 0.308 | 0.342 | -0.034 (-0.118 to +0.048) |
| PHerc. 172 hand-drawn labels, test half, columns found, character error ink only (diagnostic: the column rule was set after this half was seen) | 0.541 | 0.426 | +0.115 (-0.023 to +0.265) |
| The same PHerc. 172 test half with the letter language model, character error (diagnostic) | 0.500 | 0.451 | +0.049 (-0.048 to +0.155) |
| PHerc. 172 hand-drawn labels, dev half, columns found, character error ink only (letters-v2-real was chosen on this half, so biased in its favour) | 0.580 | 0.471 | +0.109 (+0.006 to +0.204) |
| Whole synthetic pages (24 pages, seed 11), character error | 0.071 (ink-map look 0.098, drawn-label look 0.012) | 0.064 (ink-map look 0.087, drawn-label look 0.012) | |
| Hell-Char validation lines from 21 unseen papyri, lines 601 to 2,000 (1,288 with letters), used to choose neither checkpoint | 0.404 | 0.430 | -0.026 (-0.034 to -0.018) |
| The same papyri, the first 600 lines (549 with letters), which letters-v2-ccby was chosen on (biased in its favour) | 0.416 | 0.444 | -0.028 (-0.039 to -0.017) |

What the numbers say (Interpretation). On these tests `letters-v2-ccby` errs more than `letters-v2-real` on the map windows with the line given, and on the PHerc. 172 dev half that chose `letters-v2-real`; the other scroll comparisons are not resolved (the three-line windows only just: the interval's lower end is exactly zero). It errs less on the Hell-Char validation lines, whose papyri come from the dataset that gave `letters-v2-ccby` all of its real letters but `letters-v2-real` only about a quarter of them; that may favour it there, but this is untested. The Hell-Char and dev-half comparisons were not fixed in advance; the six scroll comparisons that were (the four PHerc. 1667 rows and the two PHerc. 172 test-half rows) carry no correction for multiplicity. It remains the automatic-page and demo choice because its weights carry a permissive license; supplied-line research now selects `letters-v2-real` unless overridden.

Controls. Every PHerc. 1667, PHerc. 172 and synthetic-page read passed both controls on its totals: the error against references shuffled across groups or lines is above the real error, and the confident letters kept are more than three times those kept on scrambled copies of the same images. On the PHerc. 172 and page reads the shuffled-reference check was added after the test plan was fixed. A few segments fall under the letters-kept bar on their own: two of `letters-v2-ccby`'s six PHerc. 1667 segments in the whole-region read, and one small PHerc. 172 dev-half segment for each reader. The Hell-Char lines have no letters-kept control; their error against shuffled references, checked after the plan was fixed, is above the real error. On six blank synthetic pages `letters-v2-ccby` kept 1 confident letter and `letters-v2-real` 39; `letters-v2-real`'s 39 all fell on one texture page, where its own scrambled-copy control marked them as noise.

References. The PHerc. 1667 references were rebuilt on 14 October 2026: the 9 October transcriptions were lost, so both readers were scored on new blind machine transcriptions of the same 91 label groups, made under the same rule (three transcriptions per group, only the 84 unanimous groups scored, 117 letters). `letters-v2-real`'s numbers here therefore differ from those first published for it ([How well it reads](#how-well-it-reads)). The references are machine transcriptions of the drawings, not a papyrologist's reading.

Benchmark data, used for evaluation only: the PHerc. 172 labels of [Bodillium/Herculaneum-Scroll-Labels](https://github.com/Bodillium/Herculaneum-Scroll-Labels) (CC BY-NC-SA 4.0) and the Vesuvius Challenge PHerc. 1667 ink labels and maps ([scrollprize.org/data](https://scrollprize.org/data), CC BY-NC 4.0). The optional letter language model is built from PerseusDL canonical-greekLit texts (CC BY-SA 4.0) and is not part of the release. [Reproduce the benchmarks](#reproduce-the-benchmarks) gives the commands; the numbers are in [`results.json`](results.json) under `letter_reader_checks`.

### Training data and credits

Part of the training lines' glyphs are letter crops from Hell-Char, released with "Learning Diachronic Representations of Ancient Greek Letterforms" by John Pavlopoulos, Spyros Barbakos, Lavinia Ferretti, Dionysis Voulgarakis, Asimina Paparrigopoulou, Maria Konstantinidou, Giuseppe De Gregorio, Isabelle Marthot-Santaniello, Paraskevi Platanou and Holger Essler (ICDAR 2026; [arXiv:2606.24984](https://arxiv.org/abs/2606.24984)).
Copyright (c) 2026 The authors of "Learning Diachronic Representations of Ancient Greek Letterforms" and contributors.
Source: https://github.com/ipavlopoulos/diachronic-greek-letterforms, commit `aeef8466be674403e2dd9b0fc708b95fe7475a00`, folder `data/hellchar`.
Licence: Creative Commons Attribution 4.0 International ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)). The material is provided "as is", without warranty of any kind (see the repository's LICENSE and Section 5 of the licence).

As the Hell-Char licence asks, we also credit its origins. Hell-Char is a curated subset of Hell-Date, the EGRAPSA Hellenistic Dated Papyri Dataset by Lavinia Ferretti, Olga Serbaeva Saraogi, Giuseppe De Gregorio and Isabelle Marthot-Santaniello (https://doi.org/10.5281/zenodo.15830980), described in G. De Gregorio, L. Ferretti, R. C. G. Pena, I. Marthot-Santaniello, M. Konstantinidou and J. Pavlopoulos, "A New Framework for Error Analysis in Computational Paleographic Dating of Greek Papyri", ICDAR 2024 Workshops, LNCS 14936, Springer, 2024 (https://doi.org/10.1007/978-3-031-70642-4_7). The crops come from photographs of papyri held by the collections listed in Hell-Date's data.csv, the largest shares from the Staatliche Museen zu Berlin, the British Library, the Egyptian Museum Cairo, the Institut de Papyrologie de la Sorbonne and the Universitaet zu Koeln, and others including the UC Berkeley Library, the Musée du Louvre, the Biblioteca Medicea Laurenziana and Heidelberg University, under each holder's own terms. The Hell-Char authors license the crops they distribute under CC BY 4.0. The release contains no crop and no photograph.

Changes made: we do not redistribute the crops. Each usable crop was converted to an ink mask (pixels darker than its papyrus), scaled to a common letter height, and assigned by papyrus to training or validation; crops with no letter label, of unusual size, with too little contrast or with papyrus texture over most of the crop were left out (12,761 of 13,046 kept). In about half of the training lines every letter is a training crop; the other lines use the synthetic glyphs. All lines were degraded to look like ink-detection maps or drawn ink labels and used to train the network from scratch. The checkpoint was chosen on lines built from the held-out papyri. Neither the Hell-Char and Hell-Date authors nor the holding collections endorse this model.

## Model card: letters-v2-real

The reader's default weights until 14 October 2026 and the `ink-lines` profile since 17 October; `--weights letters-v2-real` also selects them explicitly ([Which weights](#which-weights)).

| | |
| --- | --- |
| File | `letters-v2-real-step030000.npz`, format `linenet-v1` (BatchNorm folded into the convolutions), SHA-256 `44946dadf0195ddb565f097acec0dd1d777af9b6c66d83995c1f4497aa587477` |
| Where | the [`letters-v2-real` release](https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-real) of this repository; the address is in [`kit/data/letter-weights.json`](../kit/data/letter-weights.json) |
| Network | 2D convolutions (channels 48, 96, 160, 192, 256) over a 36-row band at a letter height of 16 px, collapsed to one row, then dilated 1D residual convolutions (dilations 1, 2, 4) and a 25-way head (24 capitals with lunate sigma, plus the CTC blank); 1,483,241 parameters; one output frame per 4 px; each frame sees about five letters, so it cannot carry a word across a line |
| Training data | 600,000 lines of uniform random letter strings (no Greek words), rendered with a broad-nib bookhand skeleton and installed fonts, with half the letters cut from a bank of 43,806 real letter crops: 12,761 from 144 dated papyri of 310 to 3 BCE (Hell-Char: the paper, [Pavlopoulos et al., arXiv 2606.24984](https://arxiv.org/abs/2606.24984), and the dataset, CC BY 4.0 by the LICENSE of [its repository](https://github.com/ipavlopoulos/diachronic-greek-letterforms) at commit `aeef8466be674403e2dd9b0fc708b95fe7475a00`) and 31,045 from 152 photographs (ICDAR 2023 Greek letters, [Zenodo 13825619](https://zenodo.org/records/13825619), CC BY-NC 4.0); every line degraded to look like an ink-detection map or a drawn ink label |
| Training | `scripts/letters/train_linenet.py`, 30,000 steps, batch 128, AdamW one-cycle to 0.002, on one NVIDIA B200 (469 s of training), 9 October 2026 |
| Checkpoint choice | the best of 15 kept checkpoints on the dev half of the PHerc. 172 drawings (0.482; all 15 were 0.482 to 0.599); no PHerc. 1667 data was used to train or choose it |
| Intended use | Letter hypotheses on images of Greek capital text, for a person to check: triage of where letters are, review layers, research on reading ink maps |
| Not for | Claiming that a scroll says something; prize images (they must be generated programmatically without manual character annotations; whether machine letter overlays are allowed is not stated, so keep them out); publishing reads of a prize-eligible scroll before its prize is awarded (prize disclosure terms) |
| Licence | CC BY-NC 4.0, because part of its training data is CC BY-NC 4.0 (ICDAR 2023); the code is Apache-2.0 |

## Reproduce the benchmarks

From a clone, in its environment ([Install](#install)). The `all` extra adds what the data steps need (zarr and scipy); the PHerc. 172 check and the published text also need `pdftotext`, from poppler (`brew install poppler` on macOS, `sudo apt install poppler-utils` on Debian and Ubuntu).

```bash
python -m pip install -e ".[all]"
python scripts/letters/p1667_fetch.py work/p1667
python scripts/letters/p1667_groups.py work/p1667/labels work/p1667/groups
python scripts/letters/p1667_mapcrops.py work/p1667/groups work/p1667/maps
python scripts/letters/p1667_mapcrops.py work/p1667/groups work/p1667/maps --wide
python scripts/letters/p1667_mapcrops.py work/p1667/groups work/p1667/maps --region
```

- `p1667_fetch.py` downloads the 19 PHerc. 1667 maps at 2.4 um (about 1.9 GB) and the six labelled segments' official ink labels from the open-data bucket; it resumes and keeps no cut-off file. With `--labels-only` it fetches the label sets alone (under 1 MB), which is all row 1 needs: skip the three `p1667_mapcrops.py` lines then.
- `p1667_groups.py` cuts the labels into 91 letter groups by a rule that never looks at a reader, and writes a PNG of each group for transcription (`work/p1667/groups/png/`).
- `p1667_mapcrops.py` cuts the same places from the maps: windows for `--source map`, with `--wide` taller windows for `--source map-wide`, and with `--region` each segment's whole labelled region for `--source map-region`.

**References.** The tests score against transcriptions of the group images, which are not in this repository. Write your own: have three people (or three separate passes) transcribe every PNG in `work/p1667/groups/png/` without seeing any read, writing `?` for a letter they are unsure of, and keep the groups all three agree on in `work/p1667/refs.json` as `{"agreed": {"w013-g000": "ΚΑΙ", ...}}`. Write the reader's alphabet only: the 24 Greek capitals `ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ`, with the lunate `Ϲ` for every sigma. `eval_p1667.py` refuses a scored group that holds anything else, such as a Latin `A`, `C` or `P` typed for the Greek letter it looks like, a `Σ` or a final `ς`, and prints the character's name, what to write instead and the alphabet. Groups with a `?` are not scored. The log's references were three blind machine transcriptions (87 groups, 122 letters), so your numbers will differ somewhat from the table.

The reads, one per row of [How well it reads](#how-well-it-reads):

```bash
# Row 1, drawings, line given
python scripts/letters/eval_p1667.py read work/p1667/groups work/p1667/refs.json --weights letters-v2-real --source label --out work/letters/row1-label.json
# Row 2, the same groups from the maps, line given
python scripts/letters/eval_p1667.py read work/p1667/groups work/p1667/refs.json --weights letters-v2-real --source map --out work/letters/row2-map.json
# Row 3, map windows about three lines tall, the reader finds the line
python scripts/letters/eval_p1667.py read work/p1667/groups work/p1667/refs.json --weights letters-v2-real --source map-wide --out work/letters/row3-wide.json
# Row 3, its second value, the same windows with nothing given
python scripts/letters/eval_p1667.py read work/p1667/groups work/p1667/refs.json --weights letters-v2-real --source map-wide --letter-px auto --out work/letters/row3-wide-auto.json
# Row 4, each segment whole labelled region read once, nothing given
python scripts/letters/eval_p1667.py read work/p1667/groups work/p1667/refs.json --weights letters-v2-real --source map-region --letter-px auto --out work/letters/row4-region.json
```

Each read first prints the row its settings reproduce, then the table's measure (the plain character error for the drawings, the free-ends error for the maps) with the other measure, the error against references permuted across groups (the chance floor) and the letters kept against the nulls, and last the summary JSON on one line. `--letter-px auto` is the scale search; without it the segment's measured letter height is given (`--source label` and `map` always give it). `--source map-region` without `--letter-px auto` reads the whole regions with the letter height given, a condition reported in the [log](logs/2026-10-14-letter-reader.md) (0.328), not in the table. `--lm work/letters/greek5.npz` adds the language-model decode as `with_lm` ([Optional language model](#optional-language-model)), except for `map-region`.

To compare two readers on the same groups, read with each and give both results to `compare`, which resamples groups (paired bootstrap) and prints the difference of the second minus the first with a 95% interval; `--metric free_ends` is the maps' measure, `plain` (the default) the drawings':

```bash
python scripts/letters/eval_p1667.py compare work/letters/row2-map.json work/letters/row2-map-mine.json --metric free_ends
```

**Row 5**, the PHerc. 172 drawings, reads [Bodillium/Herculaneum-Scroll-Labels](https://github.com/Bodillium/Herculaneum-Scroll-Labels) (CC BY-NC-SA 4.0; nothing from it is copied here) and needs `pdftotext` for its transcription. It prints the row and the character error over the lines matched to the transcription first, one line per segment, and the summary JSON last; `--split dev` is the half for choosing checkpoints, never for reporting, and `compare_p172.py A.json B.json` compares two `--out` results line by line:

```bash
git clone --depth 1 https://github.com/Bodillium/Herculaneum-Scroll-Labels work/bodillium
python scripts/letters/eval_p172.py work/bodillium --weights letters-v2-real --split test --columns auto --out work/letters/row5-p172.json
```

**Row 6** is the trainer's own check, `real_val_cer` in `train.json` and `EVAL ... real-letter val CER` on screen, from the letters-v2-real recipe under [Train your own](#train-your-own).

**letters-v2-ccby against letters-v2-real.** The rows of [that comparison](#benchmarks-letters-v2-ccby-against-letters-v2-real) read both models with the commands above, once with `--weights letters-v2-ccby` and once with `--weights letters-v2-real`: `eval_p1667.py read` with `--source label`, `--source map`, `--source map-wide` (letter height given) and `--source map-region --letter-px auto`; `eval_p172.py` with `--split test --columns auto`, again with `--lm work/letters/greek5.npz`, and with `--split dev --columns auto`; and `eval_pages.py --weights W` with its defaults (24 pages, seed 11). Both comparison tools print the second result minus the first, so give the `letters-v2-real` result first; `--metric plain` is the label row's measure, `free_ends` the maps', and `--key with_lm` compares the language-model decodes:

```bash
python scripts/letters/eval_p1667.py compare work/letters/row2-map.json work/letters/row2-map-ccby.json --n 20000 --level group --metric free_ends
python scripts/letters/compare_p172.py work/letters/row5-p172.json work/letters/row5-p172-ccby.json --n 20000 --level line --key ink_only
```

The Hell-Char rows score both checkpoints on the 2,000 validation lines that `gen_dataset.py` writes with `--n 2000 --seed 9002 --bank-split val --p-bank 1.0` from a Hell-Char-only bank (as under [Train your own](#train-your-own)), in the trainer's order, with a scoring script that is not in this repository.

**Weights.** Every benchmark script takes a released name, `--weights letters-v2-real` or `--weights letters-v2-ccby` (downloaded once and checked, as for the reader), or a path to a `linenet-v1` `.npz`. `eval_p1667.py`, `eval_p1667_text.py read` and `p1667_align.py read` record `--weights` as given, because their formats are those of the tests fixed on 9 October 2026 (and `p1667_align.py`'s digest covers the field): give a released name, or a path inside the repository such as `work/letters/W.npz`, so no folder of your own ends up in the record. `eval_controls.py`, `eval_pages.py`, `eval_photos.py` and `eval_p172.py` record the weights' file name and SHA-256 (`weights`, `weights_sha256`).

**The published text and whole maps.** The published text (arXiv 2606.29085, columns 5 to 22) parses with `python scripts/letters/p1667_text.py PAPER.pdf work/p1667/text.json` (177 lines, 1752 visible letters; output SHA-256 `f936e457eb047f27014e642f50b750b6ee48c825b9eb372fda324449eec0887c` for the v1 PDF). Whole maps cut to the 38 um grid with `eval_p1667_text.py cut`, and `p1667_align.py read/align/crops` places published lines on them (decoy-tested), which `finetune_maps.py` uses to fine-tune on real map lines. `eval_p1667_text.py decoys` and `p1667_align.py align` refuse a reference line that holds a character outside the reader's alphabet (`?` aside), as `finetune_maps.py train` refuses such a line in its training lines.

## Train your own

Training needs a clone ([Install](#install)) and torch; reading never does. Each training line is drawn by [`letterdata.py`](../scripts/letters/letterdata.py) as uniform random Greek capitals, so the network learns letter shapes and no Greek; letters come from a broad-nib bookhand skeleton drawn in numpy, from installed fonts, and, with a glyph bank, from crops of real papyrus letters. Install torch first:

- **Linux, no GPU:** `python -m pip install torch --index-url https://download.pytorch.org/whl/cpu`, the CPU build (the default build from PyPI also carries CUDA libraries of several GB).
- **Linux with an NVIDIA GPU, macOS and Windows:** `python -m pip install torch`. On macOS and Windows, train on the CPU (`--device cpu`, the default): the trainer was run with `cpu` and with `cuda` on Linux only, and Apple's GPU was not tried.

**A CPU run.** This is the size of the "Real letterforms, CPU" reader in the [log](logs/2026-10-14-letter-reader.md): the trainer's defaults (593,849 parameters, 4,000 steps at batch 48), on 36,000 synthetic lines and 24,000 lines whose letters all come from a bank of the 12,761 Hell-Char letter crops (CC BY 4.0), with checkpoints chosen on the PHerc. 172 dev half. That reader took 25 minutes of training on 4 CPU threads and reads the PHerc. 1667 drawings nearly as well as `letters-v2-real` (0.033) and the maps as well (0.344 free ends). Its seeds were not recorded, so these commands make a reader of that size and recipe, not that reader:

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e ".[reader]"
git clone https://github.com/ipavlopoulos/diachronic-greek-letterforms work/hellchar
git -C work/hellchar checkout aeef8466be674403e2dd9b0fc708b95fe7475a00
python scripts/letters/realforms.py build work/letters/bank-hc.npz --hellchar work/hellchar/data/hellchar
python scripts/letters/gen_dataset.py work/letters/data/cpu --n 36000 --seed 11 --procs 4
python scripts/letters/gen_dataset.py work/letters/data/cpu --n 24000 --seed 12 --bank work/letters/bank-hc.npz --p-bank 1.0 --prefix real --procs 4
python scripts/letters/gen_dataset.py work/letters/data/val --n 4000 --seed 9001 --procs 4
python scripts/letters/gen_dataset.py work/letters/data/val-real-hc --n 2000 --seed 9002 --bank work/letters/bank-hc.npz --bank-split val --p-bank 1.0 --prefix real --procs 4
python scripts/letters/train_linenet.py work/letters/data/cpu work/letters/model-cpu --val work/letters/data/val --val-real work/letters/data/val-real-hc --threads 4 --workers 0 --keep
```

`train_linenet.py` reads every `.npz` in its data folder, so the two kinds of lines share `work/letters/data/cpu` under their own file name prefixes. The validation lines with `--bank-split val` use only the 21 papyri the bank holds out of training. `--keep` keeps a checkpoint at every evaluation (every 500 steps here) in `work/letters/model-cpu/ckpt/`; choose among them as below, and `work/letters/model-cpu/linenet.npz` is the last step. Read with any of them as `--weights work/letters/model-cpu/ckpt/linenet-step003000.npz`.

**Data generation, time and disk** (measured 14 October 2026 on a 4-core cloud container with 2 processes, on a sample of 2,000 lines of each kind, and extrapolated): a process writes 1,000 synthetic lines in about 137 s, and 1,000 lines drawn from the Hell-Char bank in about 70 s; 1,000 lines take about 10 MB on disk (9 MB for bank lines). So 100,000 lines take about 3.8 process-hours and 1.0 GB when synthetic, about 1.9 process-hours and 0.9 GB from the bank: divide the time by `--procs` (the default is every core) when that many cores are free. The CPU run above is about 30 minutes of data with 4 processes and 0.65 GB, the bank 9.5 MB built in 23 s. The letters-v2-real recipe's 600,000 lines, half of them from the bank, extrapolate to about 17 process-hours and 5.7 GB; that run's bank also holds the ICDAR crops, which were not timed here.

**macOS and Windows.** Keep `--workers 0`, the default, which assembles batches in the training process. With workers, PyTorch on macOS and Windows starts each worker as a new process and sends it a copy of every training line, once per pass over the data. The recipe's `--workers 6` was run on Linux only, and so was all of this section. `gen_dataset.py --procs` uses a process pool and should work on any system, but was likewise run on Linux only.

**Fonts.** About a third of the lines not drawn from a bank use a font that has the Greek capitals, when one is installed; without one every such line uses the skeleton hand. `letterdata.py` looks in the folders listed in `LETTER_FONT_DIRS` (separated by `:` on Linux and macOS, `;` on Windows), then in the system and user font folders of Linux (`/usr/share/fonts`, `/usr/local/share/fonts`, `~/.fonts`, `~/.local/share/fonts`), macOS (`/System/Library/Fonts`, `/Library/Fonts`, `~/Library/Fonts`) and Windows (`%WINDIR%\Fonts`, `%LOCALAPPDATA%\Microsoft\Windows\Fonts`), and keeps fonts that draw the Greek capitals, leaving out monospaced ones. `python -c "import sys; sys.path.insert(0, 'scripts/letters'); import letterdata; print(len(letterdata.font_files()))"` counts the fonts found (64 on the container above). Machines with different fonts draw different lines from the same seed, so a run is repeatable on one machine, not across machines.

**The letters-v2-real recipe** (one GPU). The glyph bank adds the ICDAR 2023 crops (CC BY-NC 4.0; the zip's MD5 is `115645f6864bb922d60309687fcfaa56`) to Hell-Char, about 43,806 letters; `--icdar-optional` skips the two truncated ICDAR photographs, as the release bank did. Leave out `--icdar` and `--icdar-optional` for a Hell-Char-only bank, which is not `letters-v2-real`'s data and leaves out the ICDAR crops' non-commercial licence; `letters-v2-ccby` was trained on lines from such a bank and synthetic glyphs (its [card](#model-card-letters-v2-ccby) gives its data and how its checkpoint was chosen). Training took about 8 minutes on one B200, and `--keep` keeps 15 checkpoints, steps 2,000 to 30,000:

```bash
python -m pip install torch
python -m pip install -e ".[reader]"
git clone https://github.com/ipavlopoulos/diachronic-greek-letterforms work/hellchar
git -C work/hellchar checkout aeef8466be674403e2dd9b0fc708b95fe7475a00
curl -sSfL -o work/icdar.zip "https://zenodo.org/records/13825619/files/ICDAR2023_Competition_on_Detection_and_Recognition_of_Greek_Letters_on_Papyri_Dataset.zip?download=1"
python -c "import zipfile; zipfile.ZipFile('work/icdar.zip').extractall('work/icdar')"
python scripts/letters/realforms.py build work/letters/bank.npz --hellchar work/hellchar/data/hellchar --icdar work/icdar --icdar-optional
python scripts/letters/realforms.py preview work/letters/bank.npz work/letters/bank-preview.png
python scripts/letters/gen_dataset.py work/letters/data/train --n 600000 --seed 11 --bank work/letters/bank.npz --p-bank 0.5 --prefix real
python scripts/letters/gen_dataset.py work/letters/data/val --n 4000 --seed 9001
python scripts/letters/gen_dataset.py work/letters/data/val-real --n 2000 --seed 9002 --bank work/letters/bank.npz --bank-split val --p-bank 1.0 --prefix real
python scripts/letters/train_linenet.py work/letters/data/train work/letters/model --val work/letters/data/val \
    --val-real work/letters/data/val-real --steps 30000 --batch 128 --channels 48,96,160,192,256 --dilations 1,2,4 \
    --device cuda --amp --workers 6 --threads 2 --eval-every 2000 --keep
```

**Choosing a checkpoint.** Choose on the PHerc. 172 dev half, never on the data you report. This needs the Bodillium clone and `pdftotext` from [Reproduce the benchmarks](#reproduce-the-benchmarks) (row 5), and prints each checkpoint's summary JSON, whose `ink_only` `cer_matched_lines` is the dev error (columns off, as the release's choice was made). For the CPU run, read `work/letters/model-cpu/ckpt` in place of `work/letters/model/ckpt`:

```bash
for w in work/letters/model/ckpt/*.npz; do echo "$w $(python scripts/letters/eval_p172.py work/bodillium --weights $w --split dev | tail -1)"; done
```

Then report the chosen checkpoint once on the test half (row 5) and on the PHerc. 1667 rows. `finetune_maps.py train` starts from any exported checkpoint, released weights included; [Fine-tune on your own lines](#fine-tune-on-your-own-lines) gives the whole chain for lines you transcribe yourself. Weights trained on the ICDAR crops inherit their CC BY-NC 4.0 licence.

## Fine-tune on your own lines

When the reader does poorly on a hand or a kind of image it has not seen, and you have lines whose text you know (your own transcription, or a published edition of a papyrus whose images you may use), you can fine-tune it on them. The result is a new model. Its output is still Model output, a hypothesis for a person to check, and the only fair test of it is on lines it did not train on, which you set aside before you train.

**1. Write records.** One record per line, in JSON or CSV. Open the image in any viewer that shows pixel positions (GIMP, Fiji, or the reader's own `--csv` and `--out`: a line's `y` and its first and last letter boxes):

```json
{
 "image": "PHOTO.jpg",
 "letter_px": 28,
 "polarity": "dark",
 "lines": [
  {"text": "ΚΑΙΤΟΥΤΟΝΤΟΝΤΡΟΠΟΝ", "y": 412, "x0": 120, "x1": 905, "split": "train"},
  {"text": "ΕΠΙ??ΝΤΗϹΑΝΤΩΝ", "y": 466, "x0": 118, "x1": 760, "split": "train"},
  {"text": "ΟΥΔΕΝΟϹΑΛΛΟΥ", "y": 520, "x0": 121, "x1": 690, "split": "test"}
 ]
}
```

| Field | What to give |
| --- | --- |
| `image` | The image file, any format the reader loads; a relative path is relative to the records file's folder |
| `text` | The line's letters in Greek capitals. Accents, breathings and dots under letters are dropped, every sigma becomes lunate and spaces are dropped, as the reader writes scriptio continua; `?` stands for a letter you cannot see or restore, and training lets it be any one letter or none. Anything else (punctuation, brackets, a Latin letter that looks Greek, the reader's own `·`) stops the build with the character's name |
| `y` | The line's centre row, halfway between the letters' tops and feet, in image pixels |
| `letter_px` | The letters' height in image pixels, as for `--letter-px` |
| `x0`, `x1` | Optional: the columns where the line starts and ends (default the whole width, which may hold other text) |
| `crop` | Optional: `[Y0, Y1, X0, X1]` as for `--crop`; `y`, `x0` and `x1` are then relative to Y0 and X0, and the image is normalised over the crop, as a read of it is |
| `key`, `polarity` | Optional: as `--key`, and `bright` (the default, ink maps) or `dark` (dark ink on a light ground, photographs) |
| `split`, `id` | Optional: a label such as `train` or `test` (`--split` keeps one), and your own name for the line |

A JSON object's keys other than `lines` (`image`, `letter_px`, `crop`, `key`, `polarity`, `split`) are defaults for every line. The same lines as CSV, with a header row (a crop as four numbers separated by spaces):

```
image,text,y,letter_px,x0,x1,polarity,split
PHOTO.jpg,ΚΑΙΤΟΥΤΟΝΤΟΝΤΡΟΠΟΝ,412,28,120,905,dark,train
```

Each line is cut as the reader sees it: the image loaded as the reader loads it (block-averaged while loading when over the pixel budget), normalised once, scaled so the letters are the network's 16 px, and the 36-row band the reader reads on a line given as `--lines Y` with `--deskew 0` (from 1.1 letter heights above the centre to 1.15 below), from `x0` to `x1`. A test checks that the band is exactly the reader's. The band is level, so for a tilted line give `x0` and `x1` close to its letters, or a crop around it.

**2. The chain**, from a clone with the reader installed ([Install](#install)) and the default released model, `letters-v2-ccby`, as the start (about 80 minutes on 4 CPU cores, below). Install torch first, as under [Train your own](#train-your-own): on Linux without a GPU, `python -m pip install torch --index-url https://download.pytorch.org/whl/cpu` (the default build from PyPI also carries several GB of CUDA libraries); on Linux with an NVIDIA GPU, macOS and Windows, `python -m pip install torch`. `build` makes the folders of `--out` and `--preview` (here `work/letters/`) once the records pass, so the chain runs in a fresh clone:

```bash
# check every record and list every problem at once, decoding no image and writing nothing
python -m kit letterlines build my-lines.json --dry-run
# cut the lines to train on, with a picture of them to check by eye
python -m kit letterlines build my-lines.json --split train --out work/letters/mine-train.npz --preview work/letters/mine-train.png
# cut the lines set apart to test on
python -m kit letterlines build my-lines.json --split test --out work/letters/mine-test.npz
# synthetic lines for half of every batch, so the model keeps what it knew, 12 files of 1,000 lines
python scripts/letters/gen_dataset.py work/letters/data/mix --n 12000 --seed 11
# fine-tune for 1,500 steps at batch 24 on a fixed schedule, keeping the last step
python scripts/letters/finetune_maps.py train work/letters/mine-train.npz work/letters/data/mix \
    --weights letters-v2-ccby --out work/letters/mine --steps 1500 --threads 4
# judge it on the lines set apart, against the model it started from
python -m kit letterlines score work/letters/mine-test.npz --weights letters-v2-ccby --weights work/letters/mine/linenet.npz
# read with it as with any weights file
python -m kit letterread PHOTO.jpg --weights work/letters/mine/linenet.npz --letter-px 28 --polarity dark
```

`finetune_maps.py train` refuses a line whose text holds a character outside the reader's alphabet (`?` aside) before it loads torch; `letterlines build` has already cleaned and checked your texts, so this stops only lines made some other way.

`build` stops before cutting anything when a record has a problem, and lists them all: a missing field, a number that is not one, an image that does not exist, a row outside the image, a character the reader does not write, a band too narrow for its letters (the network gives one output per 4 px, and a line needs one per letter plus one between doubled letters). It warns, and still cuts, when the letters would be much narrower or wider than the network's (usually a wrong `letter_px`, or no `x0` and `x1` on a short line), when the band reaches beyond the image (those rows are cut as 0, as the reader reads them) and when two records sit under half a letter apart on one image. `LINES.npz` holds the bands as 8-bit images with their texts, where each came from and the records file's name and SHA-256, in the format `p1667_align.py` writes and `finetune_maps.py` trains on. `finetune_maps.py` writes `linenet.npz` and `finetune.json` (file names and SHA-256 of the start and the result, the lines' record and the settings; no local folder).

`score` decodes every line by best path with every letter (no confidence floor: the reader's `ink_only` before letters under the floor become `·`) and reports each model's character error over the visible letters of your text, where a `?` matches any one letter or none at no cost; with two models or more it gives each later model's error minus the first's, with a 95% interval from a bootstrap over lines (with a single test line it gives the difference and says that one line allows no interval; set apart two lines or more). Lines of one image share its hand and its damage, so with test lines from few images that interval is narrower than it should be.

**Time** (measured 14 October 2026 on a 4-core cloud container): the 12,000 synthetic lines took 6 min 43 s with 4 processes; fine-tuning took 3.1 s a step with 4 threads (50 steps in 157 s) on lines 472 to 680 px wide at the network's scale (18 to 26 letters), so the default 1,500 steps take about 80 minutes, longer with longer lines (a step's time follows the widest line in its batch); `build` cut 54 lines from 9 images in 2.4 s, and `score` read 18 lines with two models in 3.5 s. On a CUDA GPU (`--device cuda`) it should take minutes; that was not measured here. That run, started from `letters-v2-real`, was a check that the chain works, on synthetic pages the released model already reads well (character error on the set-apart lines 0.191 before and 0.186 after 50 steps, a difference of -0.005 with a 95% interval of -0.028 to +0.019; Model output); it says nothing about how much fine-tuning helps on real lines. The numbers, with the export checks, are in [`results.json`](results.json) under `letter_reader_checks` (14 October 2026).

**Limits.**

- The fine-tuned model is a new model. Its letters are hypotheses like the released model's, and the controls (nulls, control map, status) are as necessary with it as without it.
- Judge it only on lines it did not train on, set apart before training. The schedule is fixed and the last step is kept, so nothing is chosen on the test lines; keep it that way (do not try several step counts and keep the best on them). Test lines from another part of the papyrus, or another papyrus, say more than neighbours of the training lines, which share their hand and damage.
- With few lines (tens, not hundreds) the gain on set-apart lines can be nothing or a loss: the synthetic half of each batch (`--p-map 0.5`) keeps the model from forgetting, but cannot stop it learning those lines by heart. `score` shows which happened.
- It learns your transcription, errors included: a wrong letter in a record teaches a wrong letter. Write `?` where you are unsure.
- The weights inherit the licence of the model they start from, whatever you train them on: CC BY 4.0 from `letters-v2-ccby` (keep its credit and the Hell-Char credit with them), CC BY-NC 4.0 from `letters-v2-real` (part of its training data is non-commercial). Your own lines may carry terms of their own.
- A model trained on lines of an unpublished text carries that text, and so does `LINES.npz`. For a scroll whose text is unpublished, keep both private, as its reads ([Rules for using it on scrolls](#rules-for-using-it-on-scrolls)).

## How it works

- **Lines, not single letters.** Herculaneum texts are written without word spaces and letter edges on an ink map are unclear, so segmenting letters first is the hard part. A CTC line reader needs only each line's letter string to train, and learns where the letters are by itself.
- **Random letters, separate language model.** Training on uniform random strings means the network learns shapes and cannot learn Greek, so it cannot invent plausible words; Greek enters only through the optional language model, shown beside the ink-only decode. The organisers' own ink models use no OCR or language model for the same reason ([grand prize page](https://scrollprize.org/grandprize), Sourced fact).
- **Real letterforms.** Synthetic glyphs alone did not transfer to real letters (more synthetic data gave no gain on drawings); half the training letters cut from photographs of real papyri cut the error on drawn PHerc. 1667 letters from 0.320 to 0.025.
- **Page layout.** The reader block-averages an image over the pixel budget while loading it, normalises it once (inverting dark ink on a light ground, so the network always sees bright ink), turns it when asked, estimates or takes the letter size, splits columns at empty gutters, deskews, finds lines from the row profile and reads each line band; boxes come back in input pixels.
- **numpy inference**, tested against torch, so reading needs no deep-learning install.

## Rules for using it on scrolls

- Its output is a hypothesis. Never write that letters were found or read on the strength of it.
- The prizes require prize images to be generated programmatically without manual character annotations ([prizes](https://scrollprize.org/prizes), Sourced fact); keep machine letter overlays out of prize images.
- Reading a prize-eligible scroll's maps produces a possible finding; the prize terms forbid disclosing one before the official announcement. Keep such reads private.
- Ink-label masks are text too: reading the labels of a scroll whose text is unpublished produces letters of unpublished text. Treat those reads like reads of a map.

## Files

| File | What it does |
| --- | --- |
| [`kit/letterread.py`](../kit/letterread.py) | The reader: the Python entry point `read()` with its input and option checks, image loading (block-averaged while loading when over the budget; zarr and OME-Zarr; EXIF orientation for JPEG and PNG), numpy network, CTC decoding (best path and prefix beam with a language model), forced alignment, layout and deskew, turned and mirrored reads, polarity (auto and the check after a failed read), nulls, control map, status codes per read, column and line, orientation, overlay, released weights (names first, SHA-256 checks, the download's advice), provenance on every result, UTF-8 output for pipes and Windows consoles |
| [`kit/greeklm.py`](../kit/greeklm.py) | Kneser-Ney letter n-grams for Greek in scriptio continua, from TEI texts |
| [`kit/letterexport.py`](../kit/letterexport.py) | A read as a CSV of letters and as PAGE XML 2019, in the image file's pixels ([Exports](#exports-csv-and-page-xml)) |
| [`kit/letterlines.py`](../kit/letterlines.py) | Training lines from your own records (`python -m kit letterlines build`), checked before any image is decoded, and character error on lines kept apart (`letterlines score`) ([Fine-tune on your own lines](#fine-tune-on-your-own-lines)) |
| [`kit/data/letter-weights.json`](../kit/data/letter-weights.json) | Released weights: file, SHA-256, address, licence |
| [`kit/letterdemo.py`](../kit/letterdemo.py) | The offline demo (`python -m kit letterdemo`, `scrolls-letterdemo`): synthetic Greek capitals in the training data's skeleton hand, drawn in numpy, and a noise image, read and judged under a fixed rule ([Check the install](#check-the-install-the-offline-demo)) |
| [`CITATION.cff`](../CITATION.cff) | How to cite the repository, with the weights as a separate reference under their own licence ([Citing](#citing)) |
| [`pyproject.toml`](../pyproject.toml) | The installable package `scrolls-workbench`: the `kit` package with its data files, extras `reader`, `maps` and `all`, and the commands `scrolls-letterread`, `scrolls-letterlines`, `scrolls-letterdemo` and `scrolls-workbench` ([Install](#install)) |
| [`scripts/letters/demo_p1667.py`](../scripts/letters/demo_p1667.py) | End-to-end demo on a public PHerc. 1667 map |
| [`scripts/letters/letterdata.py`](../scripts/letters/letterdata.py), [`gen_dataset.py`](../scripts/letters/gen_dataset.py) | Synthetic lines and pages: bookhand skeleton and fonts, map and label degradations, and a photograph look for whole pages (dark ink on a light papyrus ground; tests only, not training) |
| [`scripts/letters/realforms.py`](../scripts/letters/realforms.py) | Glyph bank from Hell-Char and ICDAR 2023 crops, split by papyrus |
| [`scripts/letters/train_linenet.py`](../scripts/letters/train_linenet.py) | Training (torch, CPU or CUDA), export to `linenet-v1` |
| [`scripts/letters/finetune_maps.py`](../scripts/letters/finetune_maps.py) | Fine-tuning on real lines whose text is known (published map lines, or your own from `letterlines build`); a '?' in the text is a wildcard |
| [`scripts/letters/eval_p172.py`](../scripts/letters/eval_p172.py), [`compare_p172.py`](../scripts/letters/compare_p172.py), [`eval_pages.py`](../scripts/letters/eval_pages.py) | PHerc. 172 drawings, paired bootstrap, whole synthetic pages |
| [`scripts/letters/eval_controls.py`](../scripts/letters/eval_controls.py) | The control status checked on map windows (as stored and tile-shuffled) and on synthetic pages with no letters |
| [`scripts/letters/eval_photos.py`](../scripts/letters/eval_photos.py) | Photograph-like pages (dark ink on a light ground, tilted, turned a quarter, on dark and white mounts): polarity bright, dark and auto, the deskew, the orientation reads, and pages with no letters |
| [`scripts/letters/p1667_fetch.py`](../scripts/letters/p1667_fetch.py), [`p1667_groups.py`](../scripts/letters/p1667_groups.py), [`p1667_mapcrops.py`](../scripts/letters/p1667_mapcrops.py), [`eval_p1667.py`](../scripts/letters/eval_p1667.py) | PHerc. 1667 data, letter groups from the official labels, map windows, scorer |
| [`scripts/letters/p1667_text.py`](../scripts/letters/p1667_text.py), [`eval_p1667_text.py`](../scripts/letters/eval_p1667_text.py), [`p1667_align.py`](../scripts/letters/p1667_align.py) | Published text as a reference, whole-map reads against it, placing published lines on maps |
| [`tests/test_letterread.py`](../tests/test_letterread.py), [`test_greeklm.py`](../tests/test_greeklm.py), [`test_letterdata.py`](../tests/test_letterdata.py), [`test_eval_p1667_text.py`](../tests/test_eval_p1667_text.py), [`test_letterexport.py`](../tests/test_letterexport.py), [`test_letterlines.py`](../tests/test_letterlines.py), [`test_letterdemo.py`](../tests/test_letterdemo.py), [`test_packaging.py`](../tests/test_packaging.py), [`test_letter_scripts.py`](../tests/test_letter_scripts.py) | Tests (this guide's commands: no comment after a command and only plain words in comment lines, every script and option it names, the letter-size table; the benchmark scripts' alphabet checks, released weight names and printed rows; numpy against torch, decoding, layout, controls and status codes, control map, weights download and lookup, the Python API's input and option checks, provenance and file names in results, UTF-8 output and files written before the summary, big images and their formats, letter size in units, deskew limit and given lines, turned and mirrored reads, polarity auto and the polarity check, EXIF orientation, overlay, letter language model, the CSV and PAGE XML exports, training lines from records and their scores, the offline demo's drawing and rule, the package's metadata, data files and commands) |

## Citing

[`CITATION.cff`](../CITATION.cff) says how to cite this repository (GitHub shows it as "Cite this repository"); the code is Apache-2.0. Cite the weights you read with as well; each released model is a separate reference there, with its release, its SHA-256 and its own licence: `letters-v2-ccby` ([release](https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-ccby), CC BY 4.0, [Model card](#model-card-letters-v2-ccby), whose credit line and Hell-Char credit go with the weights when you share them) and `letters-v2-real` ([release](https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-real), CC BY-NC 4.0, [Model card](#model-card-letters-v2-real)). A read is Model output; quote it as letter hypotheses with the weights' name and SHA-256 from the result's `weights` block, never as a reading.

## Related work

Published Greek papyrus work classifies single letters on photographs well (about 93% on letter crops, [Swindall et al. 2021](https://scholars.uky.edu/en/publications/exploring-learning-approaches-for-ancient-greek-character-recogni/)), and the best detector on whole papyrus photographs reached mAP 42% ([Turnbull and Mannix 2024](https://arxiv.org/abs/2401.12513)); both are Sourced facts, the authors' own numbers. PHerc. 1667's text and its virtual unwrapping are published in [arXiv 2606.29085](https://arxiv.org/abs/2606.29085). Community tools are listed in [`external.md`](external.md).
