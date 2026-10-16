# Quick start: from nothing to a first ink layer, then to a full pipeline

This guide gets you from an empty machine to three first results in about 15 minutes, with about 10 MB of downloads: a CT slice of a real scroll, a traced papyrus surface (a segment) drawn on that slice, and an ink layer scored against a reference. It then gives the advanced path: tracing, ink models, fast GPU inference, AutoPipeline over every released scan, Ink Bench bundles, and the known traps.

Every command here was run on 16 October 2026 on Linux (Python 3.13) against this repository's code, the open-data bucket and the Unroll Space, except where a step says it needs a GPU or VC3D. Words in *italics* on first use are defined in the [glossary](../GLOSSARY.md). Other topics have one home each in the [docs index](README.md).

![Terminal recording of the beginner path: first_look.py prints the slice, segment and ink files it wrote, then inkbench scores ink_9um above the X-ray floor on winding w046](assets/quickstart-terminal.gif)

The recording shows text output only (`scripts/quickstart/terminal_gif.py` remakes it from the real commands). This repository is public, so it never holds images of scan data.

Contents: [1 What this is](#1-what-the-challenge-and-the-data-are) · [2 Install](#2-install) · [3 Data](#3-getting-data-the-open-data-bucket-only) · [4 Beginner path](#4-beginner-path-three-first-results) · [5 Unroll](#5-unroll-the-browser-viewer) · [6 The kit CLI](#6-the-kit-command-line) · [7 Advanced path](#7-advanced-path) · [8 Gotchas](#8-gotchas-that-cost-people-days) · [9 Troubleshooting](#9-troubleshooting) · [10 FAQ](#10-faq) · [11 Compared with the official guides](#11-how-this-guide-differs-from-the-official-getting-started-material)

## 1. What the challenge and the data are

**The problem.** In 79 CE Vesuvius buried a library of papyrus scrolls at Herculaneum. They survive as [*carbonized*](../GLOSSARY.md#c) lumps that break if opened. They have been scanned with X-rays ([*CT*](../GLOSSARY.md#c)) into 3D images. Reading one takes two steps:

1. **Find the sheet.** A rolled scroll is one sheet wound around itself many times. Following one turn of it through the 3D image is [*segmentation*](../GLOSSARY.md#s), also called tracing. The result is a [*segment*](../GLOSSARY.md#s): a curved surface, stored here as a [*tifxyz*](../GLOSSARY.md#t) grid of 3D points.
2. **Find the ink.** The CT is sampled in a thin slab around that surface ([*rendering*](../GLOSSARY.md#r)), giving a [*surface volume*](../GLOSSARY.md#s). A trained model then marks where it detects ink ([*ink detection*](../GLOSSARY.md#i)). The ink is carbon on carbonized papyrus, so it barely shows in an X-ray; that is why this step uses machine learning.

The text is ancient Greek or Latin, so nothing needs deciphering. Papyrologists read the images. An ink layer shows where a model detects ink; letters that appear in one are candidates for expert reading, never a reading by themselves.

**The data**, in plain words:

| Thing | What it is | Typical size |
| --- | --- | --- |
| [*Volume*](../GLOSSARY.md#v) (scan) | The 3D X-ray image of one scroll, stored as [*OME-Zarr*](../GLOSSARY.md#o) with 6 or so [*levels*](../GLOSSARY.md#l), each half the size of the one before | Hundreds of GB to several TB at level 0; tens of MB at level 5 |
| [*Voxel*](../GLOSSARY.md#v) size | The edge of one 3D pixel, in micrometres: 9.362 um, 2.4 um, 7.91 um and others | |
| Segment mesh | A tifxyz folder: `x.tif`, `y.tif`, `z.tif` (one 3D point per grid cell) and `meta.json` | Under 1 MB at 9 um |
| Surface volume | The render of a segment: about 28 layers of CT around the surface | About 1 GB at 9 um |
| Ink detection | A published model's ink map of a segment, with a small JPEG preview | 0.3 to 40 MB |
| [*Ink labels*](../GLOSSARY.md#i) | Hand-drawn ink, plus a [*supervision mask*](../GLOSSARY.md#s) saying where both ink and non-ink were marked | Under 1 MB |
| [*Umbilicus*](../GLOSSARY.md#u) | The scroll's centre line | KB |

**The licence.** The scans and everything derived from them are CC BY-NC 4.0: non-commercial use, with attribution to the Vesuvius Challenge and the scan team. Keep images of scan data out of public repositories (this one included); this repository's rule 6 is "no scroll data, maps or weights in git".

## 2. Install

You need Python 3.10 or newer and Git. The kit's core uses only the standard library; the beginner path adds numpy, Pillow and tifffile through the `reader` extra. AutoPipeline needs Python 3.11 or newer (zarr 3). Ink inference and VC3D are installed from [villa](https://github.com/ScrollPrize/villa) later, in [section 7](#7-advanced-path).

**macOS** (Apple Silicon or Intel):

```bash
xcode-select --install                # Git and compilers, once; skip if git already works
brew install python@3.12              # or the installer from python.org
git clone --depth 1 https://github.com/ChaseHendrick/Scrolls.git
cd Scrolls
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[reader]"  # numpy, pillow, tifffile, imagecodecs
python -m kit doctor
```

**Linux** (Debian or Ubuntu; other distributions have the same packages):

```bash
sudo apt install -y git python3 python3-venv
git clone --depth 1 https://github.com/ChaseHendrick/Scrolls.git
cd Scrolls
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[reader]"
python -m kit doctor
```

**Windows** (PowerShell). The kit, the beginner path, the letter reader and Ink Bench run natively; CI tests the reader on Windows. villa's ink inference and VC3D need Linux, so use WSL2 (`wsl --install`, then follow the Linux steps inside it) for [section 7](#7-advanced-path).

```powershell
winget install Git.Git
winget install Python.Python.3.12
git clone --depth 1 https://github.com/ChaseHendrick/Scrolls.git
cd Scrolls
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1           # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install -e ".[reader]"
python -m kit doctor
```

`kit doctor` prints one line per check. On a laptop with no NVIDIA GPU, `gpu` reports `fail` and `villa` and `vc_bin` report `warn`: that is expected, and nothing in the beginner path needs them.

Install check: `scrolls-letterdemo --quiet` downloads the letter reader's 6 MB of weights once, checks their SHA-256, and ends with `DEMO PASS`.

## 3. Getting data: the open-data bucket only

All data in this guide comes from one place: the public AWS S3 bucket **`vesuvius-challenge-open-data`** (region us-east-1). It needs no account and no sign-in. Use it directly, and do not point tools at other hosts or mirrors. Some villa helpers default to a different data server; pass bucket URLs to them instead.

Three ways in, from lightest to heaviest:

```bash
# 1. Plain HTTPS: any file is a URL. The catalog of samples, scans, volumes and segments:
curl -fsS https://vesuvius-challenge-open-data.s3.amazonaws.com/metadata.json -o metadata.json

# 2. The AWS CLI, anonymous (install: https://aws.amazon.com/cli/)
aws s3 ls --no-sign-request s3://vesuvius-challenge-open-data/
aws s3 ls --no-sign-request s3://vesuvius-challenge-open-data/PHerc0841/segments/20260220213127-w00/
aws s3 ls --no-sign-request --recursive --summarize --human-readable \
  s3://vesuvius-challenge-open-data/PHerc0841/segments/20260220213127-w00/surface-volumes/   # size before you sync

# 3. The kit: resumable HTTPS mirror of one prefix, no AWS CLI needed
python -m kit fetch w035 data/w035_9um.zarr          # PHerc0139 w035, 9.362 um surface volume, about 1 GB
```

Layout of the bucket: `SAMPLE/volumes/<id>.zarr` for scans, `SAMPLE/segments/<id>/{mesh,surface-volumes,ink-detection,ink-labels}/` for each segment, and `SAMPLE/representations/` for umbilicus lines, surface predictions and normal grids. `python -m kit run catalog --out work/catalog.json` writes one row per volume in the bucket (75 volumes when this was written; 11 seconds, 66 KB), with voxel size, size, licence and prize eligibility.

**Size first, always.** `--summarize --human-readable` prints the total before you download. One labelled segment's folder can hold 30 GB at 2.4 um; its 9 um render is about 1 GB. VC3D's remote cache also grows by gigabytes ([section 9](#9-troubleshooting)).

## 4. Beginner path: three first results

Run from the repository root with the virtual environment active. The commands are bash (macOS, Linux, WSL2, Git Bash); in PowerShell, run the `python` lines as they are and download files with `curl.exe -fsSLO URL`. Everything lands in `work/quickstart/`, which Git ignores.

### 4.1 First scan view (about 8 MB, a few seconds)

```bash
python scripts/quickstart/first_look.py slice
```

This reads four 2 MB chunks of PHerc. 0139's 9.362 um scan at level 5 (32 times coarser than full resolution) and writes `work/quickstart/slice-z170.png`, a 207 x 207 px cross-section. The bright curves are turns of the rolled sheet. `--z N` picks another slice (0 to 655). The script uses only HTTPS and numpy; reading the chunks is how any zarr reader works underneath.

### 4.2 First segment (under 1 MB)

```bash
python scripts/quickstart/first_look.py segment
```

This downloads the tifxyz mesh of segment w035 (one traced turn), prints its grid (262 x 291 points, 83 % valid, one point every 20 voxels) and its bounding box, and writes `slice-with-w035.png`: the slice from 4.1 with the 385 mesh points that cross it marked in red. You can now see what a segment is: one curve per slice, following one turn of the sheet.

### 4.3 First ink layer (0.5 MB), then a first score

```bash
python scripts/quickstart/first_look.py ink
```

This downloads the published ink detection preview of w035. w035 is in the training labels of the released ink models, so clear strokes there show that the data and tools work, not a new result. Use it as the control everyone starts with.

Now score an ink layer, so you have a number that can fail. [Ink Bench](#ink-bench-from-the-command-line) compares any ink map of a PHerc. 0139 winding with the published 2.4 um ink, and with the X-ray intensity as a floor that a real ink model should beat:

```bash
curl -fsSLO https://huggingface.co/spaces/SharpMeow/unroll/resolve/main/tools/inkbench.py
S=https://huggingface.co/spaces/SharpMeow/unroll/resolve/main/data/bench
curl -fsSLO $S/w046_gpu.png          # the public ink_9um layer of winding w046 (640 px reference grid)
curl -fsSLO $S/w046_ct.png           # the X-ray intensity on the same grid: the floor
python inkbench.py compare w046_gpu.png --segment w046 --model ink_9um -o ink9um.json
python inkbench.py compare w046_ct.png --segment w046 --model x-ray-floor -o floor.json
python inkbench.py rank ink9um.json floor.json --metric ap
```

Expected (16 October 2026): `ink_9um ap=0.3415 pearson=0.4220`, `x-ray-floor ap=0.1342 pearson=0.2356`. These are agreement scores with another model's output, not ground truth. The `*.png` and `*.json` files are derived from scan data: keep them out of public commits.

`python scripts/quickstart/first_look.py all` runs 4.1 to 4.3 in one go (about 6 seconds on a fast connection).

### 4.4 Where to go next

- Look at the whole scroll in 3D: [section 5](#5-unroll-the-browser-viewer).
- Plan a real run without running anything: `python -m kit plan PHerc0826` prints the official control and target commands with the real bucket paths.
- Score a reader properly on a scroll it never saw: [7.3](#73-score-on-a-held-out-scroll-pherc0841).
- Which prize suits your time and hardware: [`start-here.md`](start-here.md#which-prize-to-aim-at).

## 5. Unroll: the browser viewer

[Unroll](https://huggingface.co/spaces/SharpMeow/unroll) is an interactive 3D viewer released as a Hugging Face Space (released 16 October 2026 as version 1.1.0; the About panel and `window.unroll.version()` give the build you are running). Code Apache 2.0; data CC BY-NC 4.0. It rebuilds 37 traced windings of PHerc. 139 (`w023` to `w059`) and unrolls them, with three layers: X-ray, Published ink (2.4 um) and ink_9um (9 um). Full guide: [`unroll-space.md`](unroll-space.md).

- **Use it:** drag to orbit, scroll to zoom, scrub the timeline or press play to unroll, click a sheet (or Read) for a close-up with a swipe between the two ink layers. `?` lists the keys; `1`, `2`, `3` switch layers.
- **Install app:** open [sharpmeow-unroll.static.hf.space](https://sharpmeow-unroll.static.hf.space/) (browsers do not offer installation inside the Space's frame) and press **Install app** in the View panel or Settings, or the browser's install icon. Safari on iPhone and iPad: Share, then Add to Home Screen. The page, three.js and the default scroll then work offline.
- **Open your own:** the **+** button reads a zip, folder or manifest with OBJ or PLY meshes (with UVs) and PNG, JPG or TIFF layers in the browser; nothing is uploaded.
- **Agent API:** in the browser console or from a test runner, `window.unrollView` and `window.unroll` drive every control: `unrollView.actions.list()`, `unrollView.action('layer.gpu')`, `unrollView.action('seek', 0.5)` (0 rolled, 1 unrolled), `unrollView.settings.set({ quality: 'low' })`, `unrollView.action('install')`. Reference: the Space's [`docs/AGENT_API_UI.md`](https://huggingface.co/spaces/SharpMeow/unroll/blob/main/docs/AGENT_API_UI.md).

### Ink Bench from the command line

The Bench is the chart button in the Space (or `?bench`), and `tools/inkbench.py`, one file needing numpy and Pillow, gives the same results in Python. Its steps: load your map of one winding (PNG or TIFF; JPEG and WebP are refused because decoders differ), align it in UV space automatically, score it (Pearson r, IoU, Dice, average precision over 51 thresholds, best F1), and export a bundle.

```bash
python inkbench.py segments                                   # windings with reference layers
python inkbench.py adapt tif-stack my_pred_stack.tif -o pred.png   # also: villa-folder, nnunet, timesformer
python inkbench.py compare pred.png --segment w046 --model "my model v1" -o w046.json
python inkbench.py compare pred.png --segment w046 --min-pearson 0.35 -o w046.json   # exit 1 below a floor (CI)
python inkbench.py validate w046.json
python inkbench.py cite                                       # BibTeX
```

In a training loop: `import inkbench; refs = inkbench.Refs(); b = inkbench.compare(prob_map, segment="w046", refs=refs)`, where `prob_map` is a path, PNG or TIFF bytes, or a 2D array in [0, 1].

**Submitting to the Bench** means publishing a bundle: export the zip in the page (bundle.json, figure, citation, share link) or write `bundle.json` with `compare -o`, host it anywhere that allows CORS, and open `https://huggingface.co/spaces/SharpMeow/unroll?board=URL1,URL2` to rank it per winding on the Leaderboard tab. Always show the X-ray floor and noise baselines ("Load examples") beside your model; the Bench's own note says to rank by AP and to distrust a correlation on windings where the floor wins (`w039`, `w053`, `w054`, `w057` for ink_9um). Format: the Space's [`docs/BENCH_FORMAT.md`](https://huggingface.co/spaces/SharpMeow/unroll/blob/main/docs/BENCH_FORMAT.md).

The Bench page says `pip install "git+https://huggingface.co/spaces/SharpMeow/unroll"` also works; on 16 October 2026 that clone failed here, so this guide downloads the single file instead.

## 6. The kit command line

`python -m kit --help` lists every command; `python -m kit COMMAND --help` gives each one's flags. `scrolls-workbench` is the same program once installed. The kit plans, scores, checks and records; it never runs VC3D or ink models itself.

| Command | What it does | Needs |
| --- | --- | --- |
| `prizes` | Open prizes, deadlines, eligible scrolls (dated snapshot) | stdlib |
| `doctor` | GPU, memory, disk, tools, `VILLA` and `VC_BIN` | stdlib |
| `plan SCROLL [--mac]` | Prints the official control and target commands with real S3 paths | stdlib |
| `fetch PREFIX DEST` | Resumable anonymous mirror of a bucket prefix (`w035`, `w045` aliases) | stdlib |
| `run catalog`, `run all`, `run watch` | Every volume in the bucket; AutoPipeline priced over all of them; new-scan watcher | stdlib |
| `run init/status/cost/check` | Experiment ledger with a preregistered readout rule | stdlib |
| `run local SLUG -- CMD` | Runs a local command and logs its wall and CPU time | stdlib |
| `auc MAP --labels --mask --control` | Pixel AUC against published labels, with the reverse map as control | `maps` extra |
| `verify REF CAND --control` | Do two maps agree (CPU against MPS, say), valid only if the control is caught | `maps` extra |
| `phantom make/stress/calibrate` | Synthetic ink phantoms with known truth | numpy |
| `view OUT.html NAME=MAP ...` | One static page overlaying ink maps and labels | numpy |
| `stackcheck`, `meshaudit`, `overlap` | Segment geometry checks (order, gaps, overlaps) | numpy, tifffile |
| `ensemble`, `layers`, `shuffle` | Average maps; export layers; depth-shuffle control | `maps` extra |
| `letterread`, `letterdemo` | Greek letter reader on an image, with null and orientation controls ([`letter-reader.md`](letter-reader.md)) | `reader` extra |
| `strokenet` | Text-likeness score of a 2D ink map ([`strokenet.md`](strokenet.md)) | numpy, tifffile |
| `releases render/check/add` | Writes the README's "Released tools" section from [`releases.json`](releases.json) | stdlib |

Releases, with install lines for each: the README's [Released tools](../README.md#released-tools). The ones this guide uses: **AutoPipeline** ([7.6](#76-autopipeline-one-scan-then-every-scan)), **Unroll** with Ink Bench ([section 5](#5-unroll-the-browser-viewer)), and the **Greek letter reader** (`scrolls-letterread MAP.png --weights letters-v2-ccby --letter-px 86 --overlay MAP-letters.png`; its output is a hypothesis for a person to check). Two speedups are already built in: the CLI builds its parser once per process (about 119 ms to 13 ms per call), and AutoPipeline resumes a run folder instead of redoing finished stages.

Install extras: `".[reader]"` (numpy, Pillow, tifffile, imagecodecs), `".[maps]"` (adds zarr 3 on Python 3.11+, scipy), `".[all]"`. Give the letter reader and AutoPipeline separate virtual environments: both install a package named `kit`.

## 7. Advanced path

### 7.1 Install villa, the checkpoints and VC3D (Linux or WSL2, NVIDIA GPU)

`python -m kit plan PHerc0826` prints these lines; they are copied from the official [ink detection tutorial](https://scrollprize.org/tutorial5) with current paths.

```bash
git clone https://github.com/ScrollPrize/villa.git
cd villa/vesuvius && uv sync --extra models
uv run --extra models python -c "import torch; print(torch.__version__, '| cuda:', torch.cuda.is_available())"
uvx --from huggingface_hub hf download scrollprize/ink_9um \
  hybrid_3d2d-seed42/step-075000.pth --local-dir checkpoints/ink_9um
export VILLA=$HOME/villa
```

VC3D (tracing, rendering, flattening): villa's release AppImage on Linux x86_64, `VC3D.app` on a Mac, or a source build named by `VC_BIN`. Build `vc_render_tifxyz` from current villa main if you need `--flip-normals` (the old container lacked it, villa #1588). On Apple Silicon read [`mac.md`](mac.md): VC3D runs natively; ink inference runs on the CPU unless you use the open MPS PR, and `bash scripts/mac-verify.sh` checks CPU against MPS on the control.

### 7.2 Run the control: ink on w035

```bash
python -m kit fetch w035 ink-dataset/pherc0139/w035/w035_9um.zarr      # the published render, about 1 GB
uv run --extra models python -m vesuvius.ink_detection.inference.infer \
  ink-dataset/pherc0139/w035/w035_9um.zarr \
  checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth \
  predictions/w035_9um.tif \
  --overlap 0.5 --blend-mode hann --batch-size 4 --direction both
```

`--direction both` also writes `predictions/w035_9um_reverse.tif`, the reversed-depth map: the control for every score below. Clear strokes on w035 mean the pipeline works; they are the model's training labels reproduced, nothing more.

### 7.3 Score on a held-out scroll: PHerc0841

PHerc0841 is the labelled scroll that `ink_9um`, v8in, d9v2 and Reader v2 did not train on (possibly not held out from Hecate). Its labels are under 1 MB:

```bash
P=s3://vesuvius-challenge-open-data/PHerc0841/segments/20260220213127-w00
aws s3 sync --no-sign-request $P/ink-labels/2.403um-volume-20260319124803/20260918/ labels/0841-w00/
python -m kit fetch PHerc0841/segments/20260220213127-w00/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr \
  data/0841_w00_9um.zarr                                           # 28 x 4220 x 4760 render
# infer as in 7.2 into predictions/0841_w00.tif (and _reverse.tif), then, with the maps extra:
python -m kit auc predictions/0841_w00.tif --labels labels/0841-w00/inklabels.zarr \
  --mask labels/0841-w00/supervision.zarr --control predictions/0841_w00_reverse.tif --bootstrap 300
```

The check can fail: a random 4220 x 4760 map scores AUC 0.5014 against a random control's 0.5008 (run here). Reference numbers for each reader are in [`results.json`](results.json); `ink_9um` seed 42 scores about 0.75 to 0.81 on w00 depending on render and crop. If you crop the input, leave the edge out with `--inner 64`, or AUC moves by up to 0.03.

### 7.4 Faster inference: torch.compile and friends

villa's `infer` compiles the model with `torch.compile` by default (`--compile-mode reduce-overhead`). Measured on a GPU in this repository's speed probes: about 1.85x per tile over eager fp16, about 1.9x with `--compile-mode max-autotune`. The first batches are slow while it compiles, so judge speed after warm-up.

| Flag | Use |
| --- | --- |
| `--compile-mode max-autotune` | Longest warm-up, fastest steady state on long runs |
| `--no-compile` | Comparisons across devices (CPU against MPS), short crops, and when compile fails |
| `--amp-dtype bf16` or `fp16` | Mixed precision on CUDA; check against fp32 with `kit verify --control` once. On an M1 Pro, fp16 on MPS ran about 5x slower |
| `--batch-size N` | Raise until GPU memory is nearly full |
| `--overlap 0.25` | About half the tiles of 0.5; shows faint tile seams |
| `--layer-start/--layer-end` | Depth windows; average several with `kit ensemble` for a small AUC gain |
| `--gpus` | Choose which GPUs `infer` uses |

A GPU run longer than about an hour belongs on a rented machine; this repository writes a run spec first ([`compute.md`](compute.md)).

### 7.5 Tracing

- **By hand, in VC3D:** open the scroll from the data catalog, Create Segment (GrowPatch) on the recto surface prediction, and fix sheet switches by hand ([VC3D tutorial](https://scrollprize.org/tutorial_VC3D)). Render with `vc_render_tifxyz ... --flip-normals` exactly as `kit plan` prints it.
- **Check before you render:** [tifxyz-doctor](https://github.com/aviad12g/tifxyz-doctor) (file, metadata and topology) and [windcheck](https://github.com/joe-carr-data/windcheck) (self-intersections). For several consecutive segments, `python -m kit stackcheck` checks order, missing sectors, skipped windings and overlaps against the umbilicus, from geometry alone (example in the README's Released tools).
- **Known limits:** villa's tracer can drift off its seed sheet ([villa #2059](https://github.com/ScrollPrize/villa/issues/2059)). A new neural tracer is in [villa PR #2045](https://github.com/ScrollPrize/villa/pull/2045); compare it with published windings before trusting it.

### 7.6 AutoPipeline: one scan, then every scan

AutoPipeline runs the whole chain unattended (acquire, umbilicus, seeds, trace, bench, qa, flatten, render, ink, score, report) with every choice fixed in a plan before the run and a control beside every check. Full reference: [`autopipeline/README.md`](autopipeline/README.md).

```bash
git clone --branch submission/progress-2026-10-fix4 --depth 1 https://github.com/ChaseHendrick/Scrolls.git scrolls-autopipeline
cd scrolls-autopipeline/submissions/progress-2026-10-fix4/autopipeline
python3 -m venv .venv && . .venv/bin/activate       # Python 3.11 or newer
python -m pip install -e .
python scripts/demo_synthetic.py                    # all 11 stages on a synthetic scroll, 8 s, DEMO PASS
scrolls-kit autopipeline plan PHerc0841 --settings '{"purpose": "benchmark", "segment": "0841-w00"}'
scrolls-kit autopipeline run work/autopipe/<folder printed by plan> --monitor
scrolls-kit autopipeline status work/autopipe/<folder>
```

Without VC3D tools it stops and says how to set `VC_APPIMAGE` or `VC_BIN` (`python3 scripts/get_vc3d.py` downloads villa's AppImage and checks its SHA-256; `scrolls-kit vc3d selftest` tests it). Without an ink Python it stops at the ink stage with status `handoff` and writes `modal-job.json`; set `KIT_INK_PYTHON` (and `KIT_AUTOPIPE_DEVICE=cuda`) and run the same folder again. Its default reader is Reader v2, a community fine-tune of `ink_9um`. The ink step alone also runs in a browser: the [AutoPipeline ink Space](https://huggingface.co/spaces/SharpMeow/autopipeline-ink).

**Every scan, from this repository's `main`** (prices and plans only; nothing launches):

```bash
python -m kit run all --dry-run --state work/batch          # 30 s: catalog, per-scan config, priced plan
python -m kit run all --status --state work/batch           # one line per scan
python -m kit run all --dry-run --state work/batch --only PHerc0139
python -m kit run watch --state work/batch --exit-code      # exit 3 when the bucket gained a new or changed volume
```

On 16 October 2026 the dry run listed 75 volumes: 64 planned, 10 blocked (with a reason each, such as "coarser than any released ink reader" or "not in the open-data bucket") and 1 skipped, with an estimated total of 536 to 2,680 USD. It prints a plan digest; `python -m kit run all --approve DIGEST` records approval of exactly that plan and still launches nothing.

### 7.7 Ink models

Released readers: `ink_9um` (two seeds, [model card](https://huggingface.co/scrollprize/ink_9um)), v8in (`YoussefMoNader/ink-8um-v8in`, reads a folder of layer TIFFs: export with `python -m kit layers`), d9v2, Reader v2 and Hecate (refuses renders more than 2 % from 9.6 um; resample rather than relabel). On PHerc0841 they score within a few hundredths of AUC of each other. What helped without training, and what did not: [`tricks.md`](tricks.md). For training, start from villa's ink-detection trainer and score every checkpoint on PHerc0841 with `kit auc --control`, and on PHerc0139 windings with Ink Bench.

## 8. Gotchas that cost people days

| Trap | What happens | Fix |
| --- | --- | --- |
| **`original_volume_downscale`** ([villa PR #2112](https://github.com/ScrollPrize/villa/pull/2112), open) | In 112 open-data segments (PHercParis4 and PHerc0139 at 4, PHerc0500P2 at 2), `mesh/intermediate/tifxyz_normalized` stores coordinates at 1/s of the original volume. The factor is only in the catalog (`properties.original_volume_downscale`), not in the mesh's `meta.json`. `vesuvius.tifxyz.read_tifxyz` does not apply it and gives no warning, so points land centimetres off | Use the full-resolution tifxyz under `mesh/` (as `first_look.py` does), or multiply points by the catalog's factor; the PR adds `read_tifxyz(path, downscale=...)` |
| **m7 surface predictions: p = 0.5 at edges** ([villa PR #2082](https://github.com/ScrollPrize/villa/pull/2082), open; issues #1114, #1875) | Voxels no inference patch reached keep logits (0, 0), which `finalize_outputs` turns into softmax 0.5, foreground at the published threshold 0.2. Mixed chunks at the scroll boundary light up | Mask the scroll boundary, or treat probability 127 (255 after the threshold) next to the boundary as unknown; the PR writes those voxels as background. It does not repair predictions already published |
| Forward and reverse swapped | Without `--flip-normals` the render's layer order is reversed, so "forward" and "reverse" maps swap | Render with `--flip-normals`, and always run `--direction both` |
| Scoring the control as a result | w035 and w045 are in `ink_9um`'s training data (w045's 2.4 um render) | Claim generalization only on PHerc0841, through the identical pipeline |
| A false 404 | A transient S3 404 becomes a permanent hole in a render ([villa #2058](https://github.com/ScrollPrize/villa/issues/2058), fix in [#2060](https://github.com/ScrollPrize/villa/pull/2060)) | Re-render, or check for holes before inference |
| AUC on a crop | Edge tiles of a cropped input score low and drag AUC by up to 0.03 | `kit auc --inner 64` |
| Two packages named `kit` | The letter reader and AutoPipeline both install one | One virtual environment each |

## 9. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `python: command not found` | Use `python3`, or activate the virtual environment first |
| `missing numpy` from `first_look.py` | `python -m pip install -e ".[reader]"` inside the activated environment |
| `kit doctor` says `gpu fail` | Normal without an NVIDIA GPU. The beginner path, Ink Bench and the letter reader need none |
| `kit auc` fails on zarr | Install the `maps` extra on Python 3.11 or newer (zarr 3) |
| `AccessDenied` or a credentials prompt from `aws` | Add `--no-sign-request`; the bucket is anonymous |
| HTTP 404 on a key | Check it with `aws s3 ls --no-sign-request` on its parent; names carry timestamps. In a zarr, a missing chunk is empty space (fill value 0), not an error |
| Disk filling while VC3D runs | Its remote cache grows by gigabytes: point `VC3D_CONFIG_DIR` at a folder whose `VC3D.ini` has `[viewer]` and `remote_cache_dir=/big/disk/remote_cache` |
| First minutes of `infer` very slow | `torch.compile` warm-up; add `--no-compile` for short runs |
| `torch.cuda.is_available()` is False | Driver or CUDA build mismatch: reinstall the torch build that matches `nvidia-smi`, or rent a GPU |
| Unroll offers no Install app | You are in the Space's frame: open `sharpmeow-unroll.static.hf.space` |
| Ink Bench refuses a JPEG | On purpose; save PNG or TIFF |
| `pip install git+https://huggingface.co/spaces/...` fails | Download `tools/inkbench.py` as in 4.3 |
| AutoPipeline: `no VC3D tools found` | Set `VC_APPIMAGE` from `python3 scripts/get_vc3d.py`, or `VC_BIN` |
| AutoPipeline stops at ink with `handoff` | No ink Python: set `KIT_INK_PYTHON` to a Python with villa and torch, then rerun the same folder |
| PowerShell will not run `Activate.ps1` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

## 10. FAQ

**Do I need a GPU?** Not for sections 4 to 6, the letter reader or AutoPipeline's planning. Ink inference on a full segment wants an NVIDIA GPU with 12 GB or more, an Apple Silicon Mac (slower), or a rented one; a whole public First Letters run has cost others about 14 USD.

**How much disk?** The beginner path needs about 10 MB. A 9 um surface volume is about 1 GB; a 2.4 um segment folder can be 30 GB; full scans are terabytes, so stream them instead of downloading.

**Can I share pictures of what I made?** The data are CC BY-NC 4.0: credit the Vesuvius Challenge and the scan team, no commercial use. This repository keeps scan imagery out of git entirely; prize terms also forbid publishing a possible find before the official announcement ([`WORKFLOW.md`](WORKFLOW.md)).

**I see letters in my ink map. Now what?** An ink map is model output. Check the reverse-depth map, a depth-shuffled control and a second seed; then treat the area as a candidate for expert reading and follow [`WORKFLOW.md`](WORKFLOW.md) before telling anyone.

**Which prize should I aim at?** Progress Prizes first (tools, fixes, benchmarks, docs, monthly), then First Letters. See [`start-here.md`](start-here.md) and `python -m kit prizes`.

**Where do numbers in this guide come from?** Commands run on 16 October 2026; benchmark numbers from [`results.json`](results.json) and the Ink Bench's published examples.

## 11. How this guide differs from the official getting-started material

The official [Get Started](https://scrollprize.org/get_started) page is an excellent interactive introduction (paint ink, trace a sheet in the browser), and the [tutorials](https://scrollprize.org/tutorial5) and villa READMEs are the reference for each tool. This guide fills the gaps between them:

- **Runnable from a terminal in minutes**, with expected outputs, on Mac, Linux and Windows, instead of one notebook or one GUI.
- **Bucket only**, with sizes before downloads and a 10 MB first result.
- **A first score that can fail**: the X-ray floor in Ink Bench and the reverse-depth control in `kit auc`.
- **The traps in one table**, with their villa PRs, and a troubleshooting table for the errors people hit first.
- **The advanced path end to end**: fast inference flags, tracing checks, AutoPipeline over every scan, and Ink Bench bundles.

Found a step that no longer works? Open an issue on this repository with the command and its output.
