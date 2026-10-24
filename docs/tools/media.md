# media: make release heroes, clips and captures that say what they show

`scripts/media/` makes the pictures for released tools: 1920 x 640 heroes in the style of the README's, social cards, GIFs and MP4s, and frame-stepped browser captures, each with a sidecar JSON that records its media label, license and how it was made.

| Field | Value |
| --- | --- |
| Id | `media` |
| Status | Current |
| Kind | script folder |
| Area | Releases and repository |
| Run | `python scripts/media/hero.py`, `python scripts/media/encode.py`, `python scripts/media/capture_web.py`, `python scripts/media/sweep.py`, `python scripts/media/tifxyz_stills.py` |
| Code | `scripts/media/` |
| Tests | `tests/test_media.py`, `tests/test_repo.py` (`test_assets_are_listed_labeled_and_within_limits`) |
| Needs | Python 3.10 or newer. `hero.py` and `sweep.py`: numpy and Pillow, and the Inter font for social cards. `encode.py`: ffmpeg (libx264) and gifsicle. `capture_web.py`: the `playwright` package and a Chromium it can start (it never downloads one). `common.py` is standard library only |
| Runs on | Any CPU. A hero renders at 3840 x 1280 in 85 to 640 s on a 4-core cloud container shared with about ten other agents, with a peak of 1.7 GB of memory (measured 2026-10-18; see Cost and time). Encoding a 20 s clip takes seconds |
| Network | None, except that `capture_web.py` opens the page it is given, which may be a URL |
| Writes | `hero.py`: `NAME.webp`, `BASE-card.jpg` and `NAME.json` in `--out-dir` (with `--preview`, only `NAME-preview.png`). `encode.py`: the `--mp4` and `--gif` files and, with `--meta`, one `NAME.json` beside them. `capture_web.py`: `frame-NNNNN.png` frames and named shots in `--out-dir`. `sweep.py`: `frame-NNNNN.png` in `--out-dir`. Each overwrites files of the same name |
| Go-ahead | Not needed to make files. Publishing them anywhere (a Hugging Face Space thumbnail, release notes, a forum) needs Chase's yes first (the go-ahead rule, hard rule 8). Model output of any scroll and real-data media of prize-eligible scrolls never go into public Scrolls; other real-data media follow [the public media rule](../media/README.md) |
| Released | Not yet: local branch `claude/release-media`, not pushed (18 October 2026) |
| Guide | [Media labels, the reference style and every asset](../assets/README.md) |
| License | Apache 2.0 for the scripts and the procedural pictures; scan data and anything rendered from it is CC BY-NC 4.0 |
| Checked | 2026-10-18 against commit `4a970bd` (with the review fixes of the same day) |

## What it does

Chase asked on 18 October 2026 for a hero image on every released tool, "the quality of and the dimensions like that of the one on the scrolls public readme", and for images, GIFs and videos because "people like those". These scripts make them reproducibly, and make each one say what it is.

`hero.py` reads a JSON recipe and writes a graded 1920 x 640 WebP (quality 83, at most 300 KB), a 1200 x 630 social card with the title in Inter, and a sidecar JSON. A recipe's scene is either procedural (a builder in `scenes.py`, drawn by the small NumPy renderer in `scene.py`) or an existing picture. The procedural scenes are generated from formulas and a seed only, so they contain no scan pixel, no model output, no lettering and no ink: synthetic cross-sections wound as spirals with a copper thread bending through their centers for the umbilicus finder, a roll unrolling flat with its layers peeling up for Unroll, a cube cut by three slices for Scroll Lens, a sheet under a reading lens for Scroll Text Reader, and so on. The `panels` scene floats real screenshots of a tool's interface over the floor, and is always a Synthetic demo.

`encode.py` turns PNG frames (or a video) into a web MP4 and a two-pass palette GIF under size limits, and records the whole chain that made the frames in the sidecar. `capture_web.py` drives headless Chromium through a list of steps and takes frames, stepping sliders, scrolling and time instead of recording the screen, so a clip is smooth whatever the machine's speed; a page that runs in real time is sampled on the wall clock, and a drawn pointer with a copper click ring shows where each interaction happens. `sweep.py` makes the frames of a synthetic scroll swept from cap to base, its winding center drifting in the scanner's fixed frame.

Every output carries one of four media labels, in its caption and its sidecar: Concept illustration, Real data render, Model output or Synthetic demo. Under any `docs/assets/` folder the public media rule applies ([`docs/media/README.md`](../media/README.md), set on Chase's delegation, 18 October 2026): Concept illustrations and Synthetic demos always, a Real data render only of a public scan that is not prize-eligible and shows no held-out labels, model output never, and every file at most 1920 px wide and 4 MB with a sidecar. Model output of any scroll and real-data pictures of prize-eligible scrolls belong in Scrolls-private's `docs/media/`. A label is only a claim, so the scripts also guard where pixels come from: `hero.py` builds an illustration or a demo for `docs/assets/` only from files already under `docs/images/` or `docs/assets/`, `encode.py` refuses an unlabeled clip there, and `capture_web.py` refuses to write its raw frames there. A picture made here is an illustration or a demo, never evidence: no hero shows lettering, fabricated ink, score badges, letter boxes or a suggested reading.

## When to use it

- A tool is released or gets a new version and needs a hero, a card or a clip for its README entry (`python -m kit releases`), its tool page or its Space.
- You want a smooth clip of a web interface: a slider, a viewer's time parameter or a live monitor.
- You need to check that a picture's label, size and license are recorded (the sidecar and `docs/assets/README.md`).

Do not use it:

- To put ink maps or other model output of any scroll, or any real-data picture of a prize-eligible scroll, into public Scrolls: make those in Scrolls-private's `docs/media/` (the scripts refuse `docs/assets/`).
- To capture VC3D: use Scrolls-private's `docs/handoff/2026-10-18/vc3d/vc3d_capture.py`, which drives a real VC3D window under Xvfb.
- For charts of numbers: draw them as SVG from `docs/results.json`, as the existing charts are.

## Quick start

From the repository root, with numpy and Pillow installed:

```bash
python scripts/media/hero.py scripts/media/recipes/umbilicus.json --out-dir OUT --preview 0.25
python scripts/media/hero.py scripts/media/recipes/umbilicus.json --out-dir OUT
python scripts/media/hero.py --check scripts/media/recipes/*.json
```

`OUT` is any new folder, such as `work/media`. The first line writes `OUT/umbilicus-hero-preview.png` (480 x 160) in a few seconds; the second writes the hero, the card and the sidecar. On 2026-10-18 the second printed (on stderr, after one `surface N/13` line per surface), and its WebP was byte-identical to the committed `docs/assets/umbilicus/umbilicus-hero.webp`:

```text
hero: umbilicus-hero: rendered 3840 x 1280 in 38.6 s
hero: umbilicus-hero: wrote OUT/umbilicus-hero.webp (45400 bytes) and umbilicus-card.jpg
```

It worked when `OUT/umbilicus-hero.webp` is 1920 x 640 and under 300,000 bytes, and `OUT/umbilicus-hero.json` holds `"label": "Concept illustration"`. The last line prints `{"recipes": 8, "ok": true}`.

A clip of a web page, then its GIF and MP4:

```bash
python scripts/media/capture_web.py PAGE.html --out-dir FRAMES --actions scripts/media/captures/starter-practice.json --width 1280 --height 940
python scripts/media/encode.py FRAMES --fps 12 --gif-fps 12 --gif OUT/clip.gif --mp4 OUT/clip.mp4 --meta scripts/media/captures/starter-practice.meta.json --made-with "python scripts/media/capture_web.py PAGE.html --out-dir FRAMES --actions scripts/media/captures/starter-practice.json --width 1280 --height 940"
```

`PAGE.html` is the page, here the portable Starter from `python -m kit start --portable --out PAGE.html --no-open`; `FRAMES` is a new folder for the frames, outside `docs/assets/`. `--made-with` records the capture in the sidecar with the frames folder written as `FRAMES`, so the sidecar holds no scratch path.

## Checks and controls

The checks that can fail are about labels and limits, not about what a picture means:

- `common.check_meta` refuses a record whose label is not one of the four, whose caption does not start with its label, or whose alt text, caption or license is missing; a Real data render must name its scan, voxel size and labels drawn (`none` when there are none), be licensed CC BY-NC 4.0, and carry the credit "Vesuvius Challenge open data, CC BY-NC 4.0" in `data.credit` and its caption.
- `common.write_guard` applies the public media rule under a `docs/assets/` folder: it refuses Model output and unknown labels, and a Real data render for which `common.real_data_problems` finds a missing data field, a prize-eligible scroll (read from the newest `kit/data/prizes-*.json`; it fails closed without one) named in its data, caption, alt text or file names, or held-out labels (PHerc1447's, PHerc0841 ag405's). `common.size_guard` removes a file written there over 1920 px wide or 4 MB, and `encode.py` caps both its GIF and MP4 at 4 MB there. `common.input_guard` refuses a source picture (an image scene or a panel) from outside `docs/images/` and `docs/assets/` when the output is there; a `panels` recipe must be a Synthetic demo. `encode.py` refuses a clip under `docs/assets/` without `--meta`, and `capture_web.py` refuses an out folder there. `tests/test_media.py` shows each refusal and the allowed private path.
- `tests/test_repo.py` fails when a file under `docs/assets/` has no row in `docs/assets/README.md` or no sidecar, when a row's or sidecar's byte count or pixel size differs from the file, when a sidecar fails `common.public_problems` (schema, label, text fields, command, commit, every output's width and bytes, and for a Real data render the rule's checks and its scripts), when a picture or clip is tracked outside `docs/assets/` and `docs/images/`, when anything is over 1920 px wide, when a sidecar records a `/tmp/` path, when a `*-hero.webp` is not exactly 1920 x 640 or is over 300 KB, when anything is over 4 MB, and when a sidecar's label or byte count disagrees with its row. Its header test shows `common.media_size` reads real dimensions from PNG, GIF, JPEG, WebP and MP4 headers.
- `python -m kit releases check` fails when a release entry's `image` caption does not start with a media label or its picture is missing.

Claim label: None (the pictures are labeled illustrations and demos; they make no claim about any scroll).

## Commands and options

### `python scripts/media/hero.py`

```text
usage: python scripts/media/hero.py [-h] [--out-dir OUT_DIR] [--preview SCALE] [--check] [--font FONT] [--json]
                                    [--quiet]
                                    recipe [recipe ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `recipe` | required | One or more recipe JSON files, such as `scripts/media/recipes/*.json` |
| `--out-dir OUT_DIR` | required unless `--check` | Folder for `NAME.webp`, `BASE-card.jpg` and `NAME.json` |
| `--preview SCALE` | none | Write only `NAME-preview.png` at SCALE times 1920 x 640 (still rendered at twice that and downsampled), with no grain, card or sidecar |
| `--check` | off | Validate the recipes, print `{"recipes": N, "ok": true}` and exit; render nothing |
| `--font FONT` | none | A font file for the card instead of Inter |
| `--json` | off | Print the sidecar records as JSON on stdout |
| `--quiet` | off | No progress lines on stderr |

### `python scripts/media/encode.py`

```text
usage: python scripts/media/encode.py [-h] [--mp4 MP4] [--gif GIF] [--meta META] [--fps FPS] [--crf CRF]
                                      [--mp4-width MP4_WIDTH] [--gif-fps GIF_FPS] [--gif-width GIF_WIDTH]
                                      [--lossy LOSSY] [--dither {bayer,none,sierra2_4a}] [--made-with COMMAND]
                                      [--max-gif-mb MAX_GIF_MB] [--max-mp4-mb MAX_MP4_MB] [--json]
                                      src
```

| Option | Default | Meaning |
| --- | --- | --- |
| `src` | required | A folder of numbered PNG frames (`frame-00000.png`, ...), or a video file |
| `--mp4 MP4` | none | Write an H.264 MP4 here |
| `--gif GIF` | none | Write a GIF here (give `--mp4`, `--gif` or both) |
| `--meta META` | none | JSON with `label`, `alt`, `caption`, `license` and optional `sources` and `release_id`; writes one sidecar `NAME.json` per output name. Required for any output under `docs/assets/` |
| `--fps FPS` | `30.0` | Frame rate of the PNG frames |
| `--crf CRF` | `20` | H.264 quality; lower is better. Raised by 3 up to three times while the MP4 is over its limit |
| `--mp4-width MP4_WIDTH` | none | Scale the MP4 to this width (default: the frames' width, made even) |
| `--gif-fps GIF_FPS` | `12` | GIF frame rate |
| `--gif-width GIF_WIDTH` | `960` | GIF width in pixels |
| `--lossy LOSSY` | `40` | gifsicle `--lossy` level |
| `--dither {bayer,none,sierra2_4a}` | `sierra2_4a` | GIF dithering (`DITHERS`): error diffusion for photographic frames; `bayer` or `none` for flat fields and interfaces, where diffusion only adds noise and bytes |
| `--made-with COMMAND` | none | A command that made the frames, repeatable and in order; the sidecar records them, then this command, joined by `&&`, with the frames folder written as `FRAMES` and repository paths made relative |
| `--max-gif-mb MAX_GIF_MB` | `4.0` | GIF size limit in MB (`GIF_MAX_MB`) |
| `--max-mp4-mb MAX_MP4_MB` | `10.0` | MP4 size limit in MB (`MP4_MAX_MB`); anything under `docs/assets/` must also stay under 4 MB |
| `--json` | off | Print what was written as JSON |

### `python scripts/media/capture_web.py`

```text
usage: python scripts/media/capture_web.py [-h] --out-dir OUT_DIR [--actions ACTIONS] [--width WIDTH]
                                           [--height HEIGHT] [--scale SCALE] [--scheme {dark,light}]
                                           [--browser BROWSER] [--timeout TIMEOUT]
                                           page
```

| Option | Default | Meaning |
| --- | --- | --- |
| `page` | required | A URL, a local HTML file, or `about:blank` (then open the page with a `goto` step) |
| `--out-dir OUT_DIR` | required | Folder for `frame-NNNNN.png` frames and named shots |
| `--actions ACTIONS` | none | JSON list of steps; without it, one shot named `page.png` |
| `--width WIDTH` | `1280` | Viewport width in CSS pixels |
| `--height HEIGHT` | `800` | Viewport height in CSS pixels |
| `--scale SCALE` | `1.0` | Device pixel ratio; 2 for sharp stills |
| `--scheme {dark,light}` | `dark` | `prefers-color-scheme` |
| `--browser BROWSER` | none | Chromium executable; otherwise `CHROMIUM_PATH`, Playwright's own Chromium, then a system one |
| `--timeout TIMEOUT` | `60000` | Per-action timeout in milliseconds |

The steps, run in order (`STEP_KEYS`): `{"goto": URL}` (retries for up to 60 s while a server starts), `{"wait": MS}`, `{"wait_for": SELECTOR}` (up to 30 s), `{"click": SELECTOR}`, `{"fill": [SELECTOR, TEXT]}`, `{"press": KEY}`, `{"eval": JS}`, `{"set": [SELECTOR, VALUE]}` (sets an input's value and fires its input and change events), `{"scroll": [X, Y]}`, `{"clip": SELECTOR or null}`, `{"shot": NAME}`, `{"frame": N}`, `{"hold": N}` (repeats the last frame), `{"frames": N, "every": MS}` (real time on the wall clock: screenshots as fast as the machine allows, then each frame is the last one taken by its time, `pick_timed`), `{"tween": {"selector": S, "from": A, "to": B, "n": N}}`, `{"step": {"js": "seek({t})", "n": N}}` (frame-stepped time, `{t}` from 0 to 1), `{"cursor": "show" or "hide"}` (a pointer drawn in the palette, `CURSOR_JS`; headless Chromium draws none), `{"point": {"selector": S, "n": N}}` (move it to S, eased), `{"tap": {"selector": S, "n": N}}` (click S and draw a copper ring growing from the pointer), `{"glide": {"selector": S, "from": A, "to": B, "n": N}}` (a tween whose pointer follows the slider's thumb) and `{"scrollto": {"selector": S, "offset": PX, "n": N}}` (scroll smoothly until S's top is PX below the window's top).

### `python scripts/media/sweep.py`

```text
usage: python scripts/media/sweep.py [-h] --out-dir OUT_DIR [--frames FRAMES] [--width WIDTH] [--height HEIGHT]
                                     [--seed SEED]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--out-dir OUT_DIR` | required | Folder for `frame-NNNNN.png` |
| `--frames FRAMES` | `72` | Frames from cap to base |
| `--width WIDTH` | `960` | Frame width in pixels |
| `--height HEIGHT` | `540` | Frame height in pixels |
| `--seed SEED` | `7` | Noise seed |

### `python scripts/media/tifxyz_stills.py`

```text
usage: python scripts/media/tifxyz_stills.py [-h] --scan SCAN --segment NAME
                                             [--cache CACHE] [--size SIZE]
                                             --out-dir OUT_DIR
                                             segment
```

| Option | Default | Meaning |
| --- | --- | --- |
| `segment` | required | tifxyz folder or bucket URL, as [`kit tifxyz`](tifxyz.md) takes it; a public scan off the prize lists |
| `--scan SCAN` | required | The scroll, for the sidecar and the public media rule's check |
| `--segment NAME` | required | The segment's short name, for the sidecar |
| `--cache CACHE` | `work/tifxyz/cache` | Where a bucket segment is kept |
| `--size SIZE` | `1200` | Longest side in pixels (one pixel per node when the grid is smaller) |
| `--out-dir OUT_DIR` | required | Writes `tifxyz-before.png` (x.tif as an image viewer shows it), `tifxyz-after.png` (the shaded sheet) `tifxyz-check-demo.png` (check flags on a made-up sheet with a planted hole, fold and shifted patch) and `tifxyz-diff-demo.png` (diff colors on two versions of a made-up sheet), each with a sidecar |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `CHROMIUM_PATH` | unset | `capture_web.py`: the Chromium to start when `--browser` is not given |

## Python API

Not applicable: the scripts are run from the command line; `tests/test_media.py` imports their functions directly, but they are not a supported library.

## Inputs

- **Recipes** (`scripts/media/recipes/*.json`): `name` (lowercase letters, digits and hyphens, ending in `-hero` by convention), `release_id` (the id in `docs/releases.json`, optional), `label`, `alt`, `caption` (starts with the label), `license`, `seed`, `scene` (`{"kind": "procedural", "name": NAME, "params": {...}}` or `{"kind": "image", "path": PATH, "focus": [X, Y]}`), `grade` (`duotone`, `key`, `rim`, `vignette`, `fade_right`, `exposure`, `black`, `grain`), `card` (`title`, `subtitle`, `kicker`, `focus`, `url`, `title_size`), `sources` and `data` (required for a Real data render: `scan`, `voxel_size`, `labels`, `credit`, and `segment` and `volume` when they apply). Paths in a recipe are relative to the folder you run from, normally the repository root.
- **Scenes** (`scenes.SCENES`): `umbilicus`, `unroll`, `lens`, `reader`, `stackcheck`, `inkfilter`, `workbench` and `panels` (`{"panels": [{"image", "center", "yaw", "pitch", "height", "crop", "pad", "glow"}], "eye", "target", "fov", "focus", "spot"}`; `pad` adds a margin of the screenshot's own background color). Most builders take `eye`, `target`, `fov`, `dof` and `key_power`; StrokeNet has no scene until its rework.
- **Capture steps** (`scripts/media/captures/*.json`) and their media records (`*.meta.json`).
- **Frames** for `encode.py`: PNGs whose names end in a number, all the same size.

## Outputs

`hero.py` writes, in `--out-dir`:

| File | What it is |
| --- | --- |
| `NAME.webp` | The hero: 1920 x 640, WebP quality 83 (lowered in steps of 5 while over 300,000 bytes), 0.6 % grain |
| `BASE-card.jpg` | The social card: 1200 x 630 JPEG, quality 88; `BASE` is the name without `-hero`. Only when the recipe has `card` |
| `NAME.json` | The sidecar (below) |
| `NAME-preview.png` | With `--preview` only, instead of the three above |

The sidecar (`common.write_sidecar`, schema `scrolls-media/1`):

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | str | `scrolls-media/1` |
| `name` | str | The file name without its extension |
| `label`, `alt`, `caption`, `license` | str | The media label and the text shown with the picture |
| `release_id` | str or null | The release the picture belongs to |
| `data` | object or null | For a Real data render: `scan`, `voxel_size`, `labels` (`none` or the labels drawn), `credit` ("Vesuvius Challenge open data, CC BY-NC 4.0"), and `segment` and `volume` when they apply |
| `sources` | list of str | Source URLs |
| `outputs` | list of objects | Each file: `file`, `bytes`, `sha256`, `width`, `height`, and `kind`, `format`, `quality` or `seconds`, `frames`, `settings` |
| `inputs` | list of objects | Input pictures with `file`, `bytes`, `sha256` |
| `made` | str | Date, `YYYY-MM-DD` |
| `tool` | object | `scripts`, `scripts_sha256` (SHA-256 over the named scripts) and `base_commit` (the checkout's commit when it ran) |
| `command` | str | The command that made it |
| `recipe` | object | `hero.py` only: the whole recipe |

`capture_web.py` prints one JSON line: `url`, `frames` (number written), `shots` (paths), `out_dir`, `width`, `height`, `scale`. `sweep.py` prints `frames`, `out_dir`, `width`, `height`. `encode.py --json` prints the output records.

| Exit code | Meaning |
| --- | --- |
| `0` | Done: every requested file was written (`--check`: every recipe is valid) |
| `1` | `capture_web.py` only: a Playwright error, such as a selector that never appeared |
| `2` | A refused input: a bad recipe, label or step, a missing file, a write under `docs/assets/` or a source picture that the guards refuse, or a usage error |
| `3` | `encode.py` only: a file stayed over its size limit after every step |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `actions must be a JSON list of steps` | `--actions` holds an object or a string | Wrap the steps in a list |
| `no such page:` | The local HTML file is not there | Fix the path, or give a URL |
| `capture_web: MESSAGE` on stderr, exit code 2 | The prefix of every `capture_web.py` refusal (a `CaptureError`, `OSError` or `ValueError`); MESSAGE is one of the rows here | Read MESSAGE and find its row |
| `capture_web: ERRORTYPE: FIRST LINE` on stderr, exit code 1 | Playwright itself failed: a selector that never appears, a page that will not load, or a timeout (`--timeout`) | Check the selector and the page in a browser; raise `--timeout` for a slow page |
| `step N: unknown or empty step STEP` | A step with a key outside `STEP_KEYS`, or `{}` | Use the steps listed under Commands and options |
| `step N: every goes with frames` | `every` without `frames` | Add `"frames": N` to the step |
| `clip element 'SELECTOR' has no box` | The `clip` selector matched nothing visible | Fix the selector, or clip to `null` |
| `hold needs an earlier frame` | `hold` before any `frame` | Take a frame first |
| `the playwright package is missing: pip install playwright (with PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 where a Chromium is installed)` | No `playwright` module | Install it as the message says; never run `playwright install` where a browser exists |
| `no Chromium could start (give --browser PATH):` | Playwright's own Chromium is a different version and no system Chromium was found | Give `--browser` or set `CHROMIUM_PATH` |
| `URL did not answer within 60 s: ERROR` | A `goto` URL refused connections for 60 s | Start the server, or check its port |
| `the media record must be a JSON object` | `--meta` or a recipe is not an object | Fix the JSON |
| `label must be one of Concept illustration, Real data render, Model output, Synthetic demo, not 'LABEL'` | The label is not Concept illustration, Real data render, Model output or Synthetic demo | Use one of the four |
| `caption must start with its label,` | The caption does not begin with the label | Start it with the label |
| `LABEL may not be written under docs/assets/ (the public media rule: no model output of any scroll); write it under Scrolls-private's docs/media/ instead` | Model output or an unknown label aimed at a `docs/assets/` folder | Write model output in Scrolls-private's `docs/media/` |
| `this Real data render may not be written under docs/assets/ (the public media rule, docs/media/README.md): ` | A Real data render that breaks the public media rule; the rest of the line names each problem, such as `is prize-eligible`, `draws held-out labels` or a missing `data.` field | Keep real-data pictures of prize-eligible scrolls in Scrolls-private's `docs/media/`; otherwise fix the record ([`docs/media/README.md`](../media/README.md)) |
| `no prize snapshot (prizes-*.json) in DIR: the public media rule needs the eligible list, so nothing passes without it` | No `kit/data/prizes-*.json` to read the eligible scrolls from | Restore the snapshot, or add a new one from https://scrollprize.org/prizes |
| `NAME is W px wide and N bytes; a file under docs/assets/ is at most 1920 px wide and 4,000,000 bytes (removed it)` | A file written under `docs/assets/` broke the size limits; it was deleted | Give a smaller `--gif-width`, `--mp4-width` or a shorter clip |
| `SOURCE is not under docs/images/ or docs/assets/; a picture for docs/assets/ is built only from files already in the public tree (commit the source there, with its label, in the same reviewed change)` | A recipe for `docs/assets/` builds from a picture outside the public tree | Commit the source under `docs/images/` with its label in the same reviewed change, or write the hero elsewhere |
| `a panels scene floats screenshots, so it is a Synthetic demo (screenshots of made-up data)` | A `panels` recipe with another label | Label it Synthetic demo, and use screenshots that show only made-up data |
| `a clip under docs/assets/ needs --meta: every clip there says what it is in a sidecar` | `encode.py` writing into `docs/assets/` without a media record | Give `--meta` |
| `capture into a scratch folder, not docs/assets/: raw frames carry no label; encode.py --meta or hero.py writes the labeled result there` | `capture_web.py --out-dir` under `docs/assets/` | Capture elsewhere, then encode with `--meta` |
| `must be one non-empty line` | `alt`, `caption` or `license` is missing, empty or has a line break | Write one line |
| `a Real data render needs data: {scan, voxel_size, labels, credit}` or `a Real data render names data.` | A Real data render without its scan details | Add `data` with `scan`, `voxel_size` and `labels` (`none` when no labels are drawn) |
| `a Real data render carries the credit` | The credit is missing from `data.credit` or the caption | Add "Vesuvius Challenge open data, CC BY-NC 4.0" to both |
| `a Real data render is licensed` | Its license is not the scan data's | Set `license` to `CC BY-NC 4.0` |
| `has a long dash (house style: none)` | U+2014 or U+2013 in a text field | Use a comma, a colon or "to" |
| `no such frames folder or video:` | `src` does not exist | Fix the path |
| `OUT stays over MAX MB; shorten the clip or lower its size` | The MP4 stayed over its limit at CRF + 9 | Shorten the clip or give `--mp4-width` |
| `OUT stays over MAX MB after every step; shorten the clip` | The GIF stayed over its limit at 70 % width, 8 fps and lossy + 80 | Shorten the clip or lower `--gif-width` |
| `NAME is not on PATH; install it (macOS: brew install NAME)` | ffmpeg or gifsicle is missing | Install it |
| `no PNG frames in` | The frames folder has no PNG | Capture first |
| `frame names must end in a number, such as frame-00000.png, not` | A frame name without a trailing number | Rename the frames |
| `give --mp4, --gif or both` | Neither output was asked for | Add one |
| `unknown recipe keys` | A recipe key outside `RECIPE_KEYS` | Remove it |
| `name is lowercase letters, digits and hyphens, such as umbilicus-hero` | A bad recipe name | Rename it |
| `scene.kind is "procedural" or "image"` | Another scene kind | Use one of the two |
| `a procedural scene is a Concept illustration or a Synthetic demo` | A procedural scene labeled Real data render or Model output | Label it Concept illustration, or Synthetic demo for screenshots of made-up data |
| `no Inter font found for the card; install Inter or give --font FILE` | No Inter font in `FONT_DIRS` | Install Inter or give `--font` |
| `the recipe needs` | A recipe without `name` or `scene` | Add it |
| `--out-dir is required unless --check` | No output folder | Give `--out-dir` |
| `need at least 2 frames of at least 64 x 64 pixels` | `sweep.py` asked for too few or too small frames | Raise `--frames`, `--width` or `--height` |
| `no scene 'NAME'; scenes: ...` (as `hero: no scene ...`, exit 2) | A recipe names a scene that `scenes.py` lacks | Use a name from `scenes.SCENES` |

## How it works

1. **Recipe.** `hero.load_recipe` checks the keys, the name and the label (`common.check_meta`) and that a `panels` scene is a Synthetic demo; `common.write_guard` checks the output folder and `common.input_guard` the source pictures (`hero.input_pictures`) before anything renders.
2. **Scene.** `scenes.build` returns a `scene.Scene`: a camera, surfaces and lights. Each surface is a function of (u, v) with a material (albedo, metal, specular exponent, emission, a keep mask for holes and torn edges, a bump height). Papyrus is long fibers along the sheet in strips of uneven tone with narrow gaps between strips, a faint layer across them, char mottling and pitting, and no dark mark that could look like ink (`scene.papyrus`, `scene.ridges`); its edges fray with fiber tufts (`scene.ragged`), and its bump height has a cheap height-only path (`bump_fn`). A cross-section is one sheet wound as an Archimedean spiral, squashed and wobbling, with a visible inner start and outer end (`scenes.scroll_section`, with seamless angular noise from `scenes.ring_noise`). A roll unrolls from its bottom like a rug (`scenes.roll_profile`).
3. **Sampling.** `Surface.plan` projects a coarse grid of each surface and gives every tile enough samples that neighbors land under `density` pixels apart (0.55 to 0.8, with 15 % extra for curvature); samples are jittered so no grid pattern beats against the pixels.
4. **Splatting.** Each batch of samples is projected and kept per pixel when nearest (a z-buffer by `numpy.lexsort`), into normal, albedo, material and emission buffers. The same samples fill a 2048 x 2048 depth map seen from the key light and a top-down map of geometry near the floor.
5. **Shading.** Every pixel once: wrapped diffuse and Blinn-Phong specular from the ivory key light (upper left and in front, `key_power` 2.2 to 4.4) with percentage-closer soft shadows (17 taps), a copper rim light on silhouettes (Fresnel term to the fourth power), ambient light, emission, a key-light pool around `spot`, and a floor that is a warm sweep under the light (`FLOOR_WARM`, `#1E1A17`) cooling to charcoal away from it, with contact shadows and a faint sheen; the backdrop is a warm near-black (`SHADOW`, `#161412`) with an ivory glow at the upper left. Then cavity darkening from depth, fog, depth of field from two blur levels, and bloom.
6. **Grade** (`hero.grade`): the ACES filmic curve (Narkowicz 2015), a duotone pull toward `#171A1C`, `#3A2A22`, `#B77A54` and `#EEE7D9`, the warm key-light falloff at the upper left (the reference measures about 80 to 88 of 255 there), a copper edge glow, a right-edge fade, a vignette and a floor at the warm `SHADOW`. The 3840 x 1280 render is downsampled with Lanczos to 1920 x 640, given 0.6 % grain, and saved as WebP (`WEBP_QUALITY` 83, `HERO_MAX_BYTES` 300,000).
7. **Card** (`hero.make_card`): a 1200 x 630 card whose left half is a solid `SHADOW` band (the art there is darkened by 0.96) holding the kicker, title, subtitle, repository address and media label in Inter; the hero's subject, cropped around `card.focus`, fills the right half, joined by a feathered edge 12 % of the width.
8. **Clips.** `capture_web.py` sets sliders, scroll positions and time and waits two animation frames before each screenshot; real-time steps are sampled on the wall clock (`Recorder.timed`, `pick_timed`); the pointer and click ring are two fixed elements it adds to the page. `encode.py` runs ffmpeg's `palettegen` (`stats_mode=diff`) and `paletteuse` (`--dither`, `diff_mode=rectangle`), then `gifsicle -O3 --lossy=40`, and H.264 with `-crf 20 -preset slow -pix_fmt yuv420p -movflags +faststart`.

### Making the release media again

The released heroes were made from the repository root with:

```bash
for r in umbilicus unroll lens reader stackcheck inkfilter starter workbench; do
  python scripts/media/hero.py scripts/media/recipes/$r.json --out-dir docs/assets/FOLDER
done
```

`FOLDER` is each recipe's folder in `docs/assets/` (its sidecar records the command). The AutoPipeline monitor clip starts the capture first (`capture_web.py about:blank --out-dir FRAMES --actions scripts/media/captures/autopipeline-monitor.json --width 1280 --height 960`), then, from the 0.1.5 package folder with the package's Python, `scripts/demo_synthetic.py --out RUN` with its run held 5 s after it writes `plan.json` (so the clip opens on the first stage), then the package's own monitor (`kit autopipeline monitor RUN/run --port 8793`) once `RUN/run/plan.json` exists. The steps sample the run for 16 s on the wall clock, wait for the Finished banner, then the pointer opens the Ink stage, filters the log and prepares the status command, and the clip ends on the banner; `encode.py` runs at `--fps 12 --gif-fps 12 --dither none` (its sidecar records the chain). The Starter clip is the portable Starter with `scripts/media/captures/starter-practice.json` at 12 fps, and the umbilicus clip is `python scripts/media/sweep.py --out-dir FRAMES --frames 84`, encoded at 12 fps with `--dither none`.

## Cost and time

Measured 2026-10-18 in a 4-core Xeon cloud container shared with about ten other agents (load average 20 to 33):

| Job | Time | Source |
| --- | --- | --- |
| `hero.py` umbilicus, 3840 x 1280 | 38.6 s render, 43 s in all | The run quoted in Quick start |
| `hero.py`, each of the eight release heroes | workbench 85 s, starter 90 s, lens 100 s, umbilicus 135 s, inkfilter 159 s, unroll 183 s, stackcheck 296 s, reader 640 s | The batch that made `docs/assets/`, timed by its loop |
| `hero.py --preview 0.35` | 9 to 90 s | Previews during this work |
| `capture_web.py`, AutoPipeline monitor, 211 frames | About 90 s, of which the demo run is 17 s | The capture run |
| `encode.py`, 211 frames to MP4 and GIF | Under 60 s | The capture run |

Peak memory of a hero render was 1,687 MB (maximum resident set, the earlier lens recipe, 143.7 s, measured 2026-10-18). The Quick start rerun of the umbilicus recipe wrote a WebP byte-identical to the committed one, so a rerun reproduces a hero exactly. Nothing here needs a GPU or Modal, and nothing is rented.

## For agents

- **Command:** `python scripts/media/hero.py scripts/media/recipes/NAME.json --out-dir docs/assets/FOLDER --json`; check first with `python scripts/media/hero.py --check scripts/media/recipes/*.json`.
- **Parse:** the sidecar `NAME.json`: `label`, `caption`, `outputs[].file`, `outputs[].bytes`, `outputs[].width`, `outputs[].height`; then add a row per file to `docs/assets/README.md` with exactly those bytes and pixels.
- **Rerun:** Safe and deterministic for a procedural recipe (the same recipe, seed and scripts give the same pixels); it overwrites the hero, card and sidecar, so update their rows in `docs/assets/README.md`.
- **Success:** Exit code 0, the hero is 1920 x 640 and under 300,000 bytes, and `python -m unittest tests.test_repo tests.test_media` passes.
- **Not a pass:** a picture with no sidecar or no row in `docs/assets/README.md`; a caption that does not start with its label; a hero that is the right size but shows scan pixels, an ink map or letter boxes on real data.
- **Go-ahead:** Uploading or posting any picture (Hugging Face thumbnails, release notes, forums) needs Chase's yes; committing to a branch does not.
- **Never:** put model output of any scroll (ink maps, reader or StrokeNet output), any real-data picture of a prize-eligible scroll, or any held-out labels into public `docs/assets/`; show ink, StrokeNet or reader output on a Grand Prize or First Letters scroll anywhere, any PHerc0841 ag405 crop, or any Paris 4 ink or model output; draw lettering, fabricated ink, score badges or letter boxes in a hero; call a picture a reading.

## Tests

`python -m unittest tests.test_media tests.test_repo` runs the label, guard, sidecar and recipe checks everywhere (standard library), renders every recipe at 120 x 40 and checks the same recipe gives the same pixels (numpy and Pillow), encodes six frames into an MP4 and a GIF with one sidecar (ffmpeg and gifsicle), and captures a slider tween in Chromium (Playwright). Each part skips when its tools are missing. The tests do not judge how a picture looks; a person checks that at full size.

## History

- 2026-10-18: added `hero.py`, `scene.py`, `scenes.py`, `encode.py`, `capture_web.py`, `sweep.py` and `common.py`, with heroes and clips for every released tool and the `image` field of `kit/releases.py` (branch `claude/release-media`, `4a970bd` is the base commit).
- 2026-10-18: after review of `c33e159`, the guards check sources and clips, not only labels (`common.input_guard`, `--meta` required under `docs/assets/`, no raw frames there, panels always a Synthetic demo), and `tests/test_repo.py` allows only Concept illustration and Synthetic demo there and requires a sidecar for every file. The heroes were remade with the reference's warm key light, low cameras and diagonal subjects, fibrous papyrus, spiral cross-sections and cards with a solid text band; the Scroll Text Reader hero no longer draws letters, boxes or bars, and StrokeNet's hero is withdrawn until its rework. The AutoPipeline clip was recaptured at 12 fps from the first stage with a pointer (`cursor`, `point`, `tap`, `glide`, `scrollto`, wall-clock `frames`), the umbilicus sweep redrawn in the scanner's fixed frame, and `encode.py` gained `--dither` and `--made-with`.
- 2026-10-18: the public media rule ([`docs/media/README.md`](../media/README.md), set on Chase's delegation) replaced "only Concept illustrations and Synthetic demos": `common.write_guard` now also allows a Real data render of a public scan that is not prize-eligible and shows no held-out labels (`real_data_problems`, `prize_scrolls`, `eligible_prizes`), `common.size_guard` and `encode.py` hold every file there to 1920 px and 4 MB, `common.public_problems` checks every committed sidecar, `common.media_size` reads MP4 sizes too, the credit became "Vesuvius Challenge open data, CC BY-NC 4.0", `data.labels` is required and `data.segment` optional, and `hero.py` checks the rule before importing Pillow. The audit found every existing file conforming.

## Related

- [`docs/assets/README.md`](../assets/README.md): every asset with its size, bytes, label and license, and the reference style.
- [`docs/media/README.md`](../media/README.md): the public media rule, the prize-eligible list it uses and the audit of 18 October 2026.
- [`releases`](releases.md): the README's Released tools section, where each entry's `image` shows its hero.
- [`autopipeline`](autopipeline.md), [`unroll`](unroll.md), [`scroll-lens`](scroll-lens.md), [`letterread`](letterread.md), [`starter`](starter.md), [`umbilicus`](umbilicus.md), [`stackcheck`](stackcheck.md), [`inkfilter`](inkfilter.md), [`workbench-package`](workbench-package.md): the tools these pictures show. [`strokenet`](strokenet.md) gets its picture after its rework.
