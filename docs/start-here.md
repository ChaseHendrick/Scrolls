# Start here: your first steps with the Vesuvius Challenge

Start with a browser, learn what each image means, then try one small task with the official tools. You do not need a GPU, a programming background or a prize plan to begin. Scrolls is a community workbench; the official [Vesuvius Challenge](https://scrollprize.org/get_started) supplies the scans, core tools and research tutorials.

**Share this guide:** <https://github.com/ChaseHendrick/Scrolls/blob/main/docs/start-here.md>

**What is Workbench?** [See the picture guide](workbench.md) for the toolbox, its screens and what to open first.

## Choose your first goal

| I want to... | Start here | What you need | First success |
| --- | --- | --- | --- |
| See what virtual unwrapping means | [Explore in a browser](#1-explore-in-a-browser) | A modern browser and Internet | Identify a rolled sheet, its flat surface and an ink layer |
| Learn by doing something small | [Scrolls Starter](#2-try-scrolls-starter-on-your-computer) | A browser; Python is optional for a setup check | Finish a synthetic exercise and compare it with a control |
| Work with actual scan data | [The official data notebook](#3-move-to-one-small-official-task) | A browser and Colab account, or local notebook setup | Display one bounded CT example and identify its axes |
| Trace papyrus surfaces | [The VC3D path](#trace-a-surface-with-vc3d) | A supported desktop and room for streamed data | Follow the same sheet through adjacent slices |
| Try ink detection | [The ink path](#make-an-ink-map-with-official-tools) | A surface volume; model-specific compute and storage | Produce one small prediction beside a control |
| Suggest text from an existing image | [Scroll Text Reader](#4-optional-suggest-text-from-an-existing-image) | A small 2D image and reader dependencies | Check synthetic known text and noise before your own image |
| Automate a pipeline I understand | [AutoPipeline](#5-optional-practice-pipeline-automation) | A separate Python environment | Run its synthetic demo before connecting real tools |

You can stop after any row. Each result teaches a skill needed by the next task; completing a demo does not establish accuracy on a real scroll.

## What the pictures mean

| Stage | Input | Output | What to check |
| --- | --- | --- | --- |
| CT scan | X-ray measurements | A 3D grid of voxels, like a stack of image slices | Which axis and resolution are you viewing? |
| Surface tracing and rendering | CT plus a traced papyrus sheet | A flattened **surface volume**, still a thin 3D stack | Does the trace stay on one sheet rather than jump to its neighbor? |
| Ink detection | A surface volume | A 2D map of predicted ink | Does it agree with known labels and beat an appropriate control? |
| Text suggestions | An ink map or photograph | Letter or word hypotheses | Does the image support them? Do noise and shuffled controls produce similar text? |
| Expert reading | The evidence and its context | An assessed reading | Papyrologists decide legibility and interpretation |

The Scroll Text Reader starts at the fourth row. It does not turn raw CT into text. An ink map is a prediction, and a plausible word is not proof. [Pipeline overview](pipeline.md) and [glossary](../GLOSSARY.md) explain the terms in more detail.

## 1. Explore in a browser

Allow about ten minutes for this tour; no installation is needed.

1. Open [Unroll](https://huggingface.co/spaces/SharpMeow/unroll). Drag to rotate, zoom, then scrub its unrolling timeline. Click a sheet or use **Read** for a close-up. Compare the X-ray and available ink layers. You are viewing published data and predictions, not running a new ink model. [Unroll controls and credits](unroll-space.md).
2. Try the official [Get Started](https://scrollprize.org/get_started) exercises: paint visible ink in **Can you find the ink?**, then follow one sheet in **Where did that surface come from?**. Deliberately stray onto a neighboring sheet and compare the flattened result. These exercises introduce labeling and surface tracing.
3. Open the official [Data Browser](https://scrollprize.org/data_browser). Pick a sample and distinguish its CT volumes from any published surfaces and ink outputs. Some samples do not have every kind of output.

**Ready to move on:** explain why a flat surface is still needed before ordinary surface-based ink inference, and why an ink-colored pixel is not a decoded letter.

Optional: [Scroll Lens](https://huggingface.co/spaces/SharpMeow/scroll-lens) compares the organizers' 3D models on small scan cubes. Start with a gallery cube and compare its scan and model layers. It uses hosted compute and may queue, be unavailable or fall back to CPU; a small cube is not a readable page. [Guide and requirements](tools/scroll-lens.md). Unroll's browser rendering and Scroll Lens's hosted model inference are different activities.

## 2. Try Scrolls Starter on your computer

**No install for practice:** download [Scrolls-Starter.html](https://github.com/ChaseHendrick/Scrolls/releases/download/workbench-v0.4.1/Scrolls-Starter.html), then open the downloaded file in a modern browser. The page contains its exercise and works offline. It links to online tools when you choose to visit them. Start at **Try a check that can fail** and follow the practice steps below.

The portable page cannot inspect your computer: its setup status is **not checked**. To get a real setup snapshot or run the optional reader, install the Python package below. Both versions have the same synthetic exercise and reader command builder. Opening Starter does not download scans or weights, run inference, rent compute or upload files. Generated reader commands are for you to inspect and run explicitly.

The following optional installation adds workbench **0.4.1**, including Starter, into a folder of your own. The base package uses Python's standard library. A virtual environment keeps this program's Python packages separate from other programs. Internet is needed for Python and package installation; the synthetic Starter exercise then works locally. Set aside roughly 1 GB for a comfortable first installation, with more if you later add reader dependencies. This is a planning allowance, not a scan-storage estimate.

### macOS

Install Python 3.13 using the [python.org macOS installer](https://www.python.org/downloads/macos/). Open **Terminal**, then paste these commands one line at a time. They do not require Homebrew or Git.

```bash
mkdir scrolls-learning
cd scrolls-learning
python3.13 -m venv .venv
.venv/bin/python -m pip install "https://github.com/ChaseHendrick/Scrolls/releases/download/workbench-v0.4.1/scrolls_workbench-0.4.1-py3-none-any.whl"
.venv/bin/python -m kit start
```

### Linux

You need **Python 3.10 or newer**; Python 3.11 or newer also supports the optional Zarr 3 tools. On a current Ubuntu or Debian release, install Python and its virtual-environment support in **Terminal**:

```bash
sudo apt update
sudo apt install python3 python3-venv
python3 --version
```

Check that the printed version is at least 3.10. If an older Linux release supplies an older Python, install a supported Python or update the distribution before continuing. On another distribution, use its package manager for Python and `venv` support. Then:

```bash
mkdir scrolls-learning
cd scrolls-learning
python3 -m venv .venv
.venv/bin/python -m pip install "https://github.com/ChaseHendrick/Scrolls/releases/download/workbench-v0.4.1/scrolls_workbench-0.4.1-py3-none-any.whl"
.venv/bin/python -m kit start
```

### Windows

Install Python 3.13 from [python.org](https://www.python.org/downloads/windows/), including its Python launcher. Open **PowerShell**, then:

```powershell
mkdir scrolls-learning
cd scrolls-learning
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install "https://github.com/ChaseHendrick/Scrolls/releases/download/workbench-v0.4.1/scrolls_workbench-0.4.1-py3-none-any.whl"
.venv\Scripts\python.exe -m kit start
```

Calling the environment's Python directly avoids PowerShell activation-policy changes. Throughout this guide, Windows users replace `.venv/bin/python` with `.venv\Scripts\python.exe`.

### Verify, practice, then choose a tool

The browser should open **Scrolls Starter**. By default its page is `index.html` in a temporary folder whose name starts with `scrolls-starter-`; the command prints its full path. If no browser opens, open that file yourself. Use `--no-open` to print the path without opening a browser, or `--out starter.html` to keep a named page; choose a new filename because Starter never overwrites an existing file. Run the setup check from the same `scrolls-learning` folder:

```bash
.venv/bin/python -m kit start --check
```

This prints a JSON setup report and does not create a page. The report describes this Python installation and optional components. The page contains a snapshot: rerun Starter after installing something to refresh it. Missing reader packages, Tesseract, VC3D or a GPU do not prevent the basic exercise. The separate `kit doctor` command checks a much larger villa workflow; its GPU and disk warnings are not requirements for starting here.

In either the portable or installed page, use the threshold practice exercise to compare its prediction with the known synthetic answer and a noise-only control. Change the threshold and see whether both the picture and score respond. Then put the same pattern in the control: the fixed practice rule should fail. Synthetic pixels are teaching material, not CT measurements or evidence of ink. The [Starter reference](tools/starter.md) lists the exact checks, output files and command-builder limits.

**Ready to move on:** locate your page, distinguish **not checked** from a real setup report, and explain why a good-looking output needs a control. Missing optional features do not prevent practice.

To resume another day, reopen the portable HTML file, or open Terminal/PowerShell and `cd` into `scrolls-learning`. For the installed app, run `.venv/bin/python -m kit start` on macOS/Linux or `.venv\Scripts\python.exe -m kit start` in PowerShell. No environment activation is required. Do not paste the Markdown fences around commands.

## 3. Move to one small official task

Our helpers are optional. You can go straight from the browser exercises to the official notebook, VC3D or ink tooling. Choose one path, finish its success check, and only then increase the amount of data.

### Inspect a small CT example with the official notebook

1. Open the [Get to Know a Dataset notebook](https://github.com/ScrollPrize/open-data/blob/main/examples/get-to-know-a-dataset.ipynb), recommended by the current official [data page](https://scrollprize.org/data). You can read it on GitHub first, then [open it in Colab](https://colab.research.google.com/github/ScrollPrize/open-data/blob/main/examples/get-to-know-a-dataset.ipynb) or use a local Jupyter setup. Colab execution needs a Google account; choose a **CPU runtime**.
2. The notebook lists `vesuvius`, `numpy`, `matplotlib` and `boto3` as dependencies. If they are missing in your notebook runtime, add a setup cell containing `%pip install vesuvius numpy matplotlib boto3`. This installs into the notebook's environment, separately from the workbench. Read the [data license](https://scrollprize.org/data) before choosing to accept it; the notebook's commented `accept_terms --yes` line is an explicit acceptance, not a prerequisite to viewing the source.
3. Run cells individually through the lazy `Volume` creation and printed **Shape** and **dtype**. This inspects metadata before fetching a crop. The example selects PHerc. 0009B at 8.640 micrometers per voxel, native level `0`; axes are `[z, y, x]`. Higher pyramid levels are downsampled, but their coordinates differ too.
4. Check the stated crop before running it: `CHUNK_SIZE = 256` and indices starting at `4000` on each axis. A 256-cubed array alone takes 16 MiB as uint8 or 64 MiB as float32; fetched chunks and temporary arrays add overhead. Run that bounded crop and its three **orthogonal slices**, then stop. Do not use **Run all** or replace the crop with the entire volume.

**Success:** the crop reports shape `(256, 256, 256)` and three grayscale slices labeled XY, XZ and YZ. Identify sheet and air, and explain which resolution you loaded. This checks data access and orientation, not ink detection. The notebook's scan reads were not rerun for this guide; if the upstream example changes, use its current dimensions and instructions. Reads use network and cache space; free Colab runtimes are subject to availability and are not a promise of free GPU capacity.

The official [vesuvius notebook collection](https://github.com/ScrollPrize/villa/tree/main/vesuvius#-introductory-notebooks) offers further examples, including downsampled slice access and ink detection. The [dataset guide](https://scrollprize.org/data_datasets) distinguishes CT, surface labels, ink labels and spiral-fitting inputs. Published labels have their own provenance; do not assume every label is an infrared photograph or independent ground truth.

### Trace a surface with VC3D

Follow the official [Virtual Unwrapping with VC3D](https://scrollprize.org/tutorial_VC3D) tutorial and [villa releases](https://github.com/ScrollPrize/villa/releases). Use the release asset matching your operating system and processor. On Apple Silicon this is the macOS ARM64 application; Windows has its own installer; check the current Linux assets before deciding to build from source. The tutorial and release packaging can change at different times.

For your first session, stop at **Viewing a scroll**: open **File > Open Data Catalog**, load the tutorial's sample, and move the same focus point through the orthogonal slice views. Its catalog streams data, so reserve cache space and watch downloads. You do not need to grow a full segment to learn navigation.

**Success:** follow one sheet through neighboring slices without jumping across an air gap to another sheet. Then attempt only the tutorial's small starter patch. Inspect the patch in the CT views and flattened view before making it larger. A message saying growth succeeded means the operation completed; it does not certify that the surface stayed on one sheet.

### Make an ink map with official tools

Use the official [Ink Detection tutorial](https://scrollprize.org/tutorial5) and [Ink Detection notebook](https://colab.research.google.com/github/ScrollPrize/villa/blob/main/vesuvius/src/vesuvius/examples/notebooks/example2_ink_detection.ipynb). First inspect one supplied segment and its published label image. The labels are a reference to compare against, not a prediction made by your setup.

Before inference or training, check the notebook's current model, environment, GPU requirements and selected crop. Write down a disk allowance, runtime limit and any spending limit. Start with one small published example and the tutorial's supported configuration. GPU model training is a later task, not an installation test. [Compute planning](compute.md) explains how this workbench records costs.

**Success:** know which file is the input surface volume, which is the predicted map, which is the known label, and which is the control. For a benchmark, hold the window, scale and score mask fixed and compare with an appropriate negative control, such as reversed depth for a surface-volume reader. Training-example success does not measure generalization to a new scroll. See [scoring and controls](STANDARDS.md).

## 4. Optional: suggest text from an existing image

**Scroll Text Reader** is this project's text-suggestion tool, formerly called Greek Letter Reader. Its command names remain `letterread`, `scrolls-letterread` and `scrolls-letterdemo`. You can use the official scan, surface and ink tools without installing it.

Add the reader dependencies to your **workbench** environment using the same wheel:

```bash
.venv/bin/python -m pip install "scrolls-workbench[reader] @ https://github.com/ChaseHendrick/Scrolls/releases/download/workbench-v0.4.1/scrolls_workbench-0.4.1-py3-none-any.whl"
.venv/bin/python -m kit letterdemo --out first-reader
```

On Windows:

```powershell
.venv\Scripts\python.exe -m pip install "scrolls-workbench[reader] @ https://github.com/ChaseHendrick/Scrolls/releases/download/workbench-v0.4.1/scrolls_workbench-0.4.1-py3-none-any.whl"
.venv\Scripts\python.exe -m kit letterdemo --out first-reader
```

The first demo downloads about 6 MB of Greek weights from the project's GitHub release and checks their hash. It then runs on CPU. Expect `DEMO PASS` only if known synthetic text and its noise control satisfy the fixed rule; `DEMO FAIL` is a real failed check, and `DEMO ERROR` means it could not run. The output folder contains `demo.json`, `demo-page.png` and `demo-overlay.png`. Inspect the images and record together. A pass verifies the installation on clean synthetic letters; it does not measure scroll accuracy.

The built-in learned model proposes **Greek capitals**. Given line positions select the `ink-lines` profile; automatic layout uses the permissive profile. The chosen weights and license are recorded. For Latin, Hebrew or another script, the optional **Tesseract** backend needs that language's local recognition pack; changing a language menu does not teach the Greek model a new alphabet. Tesseract is a separate install, not included by the `reader` extra, and its scroll accuracy is unmeasured. [Reader guide](letter-reader.md) and [backend installation and languages](tools/reader-backends.md).

Use Starter's command builder for a small image you already have. It creates a command, not a result. The installed page uses the Python that generated its setup snapshot; the portable page needs the installed environment you selected. Read the options and choose a new output name before running it: the page does not inspect your files, and the reader can overwrite existing output files. Keep real candidate images and hypotheses in private storage; do not put them in a public issue or commit. The [workflow](WORKFLOW.md) covers what to do with a possible finding.

## 5. Optional: practice pipeline automation

**AutoPipeline** connects the official tracing, rendering and ink stages and keeps their plans and controls together. Begin with its [released synthetic demo](https://github.com/ChaseHendrick/Scrolls/blob/submission/progress-2026-10-fix5/submissions/progress-2026-10-fix5/autopipeline/README.md). It uses a made-up scroll and stand-in tools. `DEMO PASS` checks orchestration, not the real VC3D binaries or an ink model; since version 0.1.5 the demo prints `DEMO FAIL` instead when a stand-in model fails or a map is missing.

**Use a separate environment and folder.** Both AutoPipeline (`vc-autopipeline`) and this workbench (`scrolls-workbench`) install a Python package named `kit`. Installing them together can overwrite files. A second virtual environment is required even though their command names differ.

For macOS or Linux with Git and Python 3.11 or newer, open a new terminal outside `scrolls-learning`. On macOS, type `python3.13` where the commands say `python3`, as in section 2.

```bash
git clone --depth 1 --branch submission/progress-2026-10-fix5 https://github.com/ChaseHendrick/Scrolls.git scrolls-autopipeline
cd scrolls-autopipeline/submissions/progress-2026-10-fix5/autopipeline
python3 -m venv .venv-ap
.venv-ap/bin/python -m pip install -e .
.venv-ap/bin/python scripts/demo_synthetic.py --out work/demo-run
.venv-ap/bin/scrolls-kit autopipeline defaults
```

The demo should end with `DEMO PASS`. The last command is the install check: it prints AutoPipeline's default settings as JSON, which shows the `scrolls-kit` command is installed in `.venv-ap`. Keep the run folder under `work/`, which the package's `.gitignore` excludes. The demo refuses to write traces into a folder git would track inside the clone: it then prints `DEMO FAIL` with `expected two synthetic surfaces, got 0`, and its `state.json` says the folder `is inside the repository but not ignored by git`. Without `--out`, the demo uses a new temporary folder and prints its path.

For Windows, this shell-tool demo uses a Linux environment such as WSL; the native Windows Starter and text-reader path above does not require WSL. Follow the release's requirements before choosing that additional setup. Keep `work/demo-run` to inspect the plan and stage outputs. The [AutoPipeline how-to guide](autopipeline/guide.md) walks through the next steps in plain language: VC3D's tools, a first real plan, your own seeds, surfaces and models, and opening results in VC3D. To connect real tools afterward, follow the [AutoPipeline reference](autopipeline/README.md#3-install-and-requirements), verify VC3D's tools, and keep villa's ink Python environment separate too. Do not start a full scan as your first integration check.

The released [Inkfilter](tools/inkfilter.md) is another optional small CPU exercise if you want to study surface-volume filters before using a trained ink model. Its synthetic demo writes a map, a reversed-depth control and a record. It uses a different standalone package and does not replace the official pipeline.

## Before a larger run

A full scroll can occupy terabytes, as the official [Get Started](https://scrollprize.org/get_started) page explains. A compressed download size is not a RAM estimate. Check the dimensions and data type of your crop, and allow room for temporary arrays, caches and outputs. A single float32 array needs four bytes per voxel; models and transformations may hold several arrays at once.

Choose the smallest public example that exercises the skill you need. Record its sample, resolution, crop, software version and model. Set a runtime and storage limit before launching; set a spending limit before using paid services. Starter never signs up for or launches paid compute. GPU tasks, full-scan work and prize attempts need their own plan and the current [official prize terms](https://scrollprize.org/prizes).

## If something goes wrong

| What you see | What to try |
| --- | --- |
| `python3.13` or `py` is not found | Finish installing Python, close and reopen the terminal, then check the version. On Linux use `python3`; on Windows `py -3.13 --version` selects the requested install |
| `No module named venv` or `ensurepip` | On Ubuntu/Debian install `python3-venv`, then create the environment again |
| `externally-managed-environment` | Use the `.venv` Python exactly as shown; do not install into the operating system's Python |
| Starter opens no browser | Open the HTML path printed by the command. On a remote computer, copy that generated page to your own computer and open it there |
| An optional dependency is missing | The base practice still works. Install the `reader` extra only for the text reader, or follow the official tool's own setup |
| `No module named kit` or the wrong command list | Check you are calling the workbench `.venv` Python, not AutoPipeline's environment. Recreate separate environments if their packages were mixed |
| `scrolls-start: command not found` | Commands in this guide call the environment directly. Run `.venv/bin/python -m kit start`, or `.venv/bin/scrolls-start`, from `scrolls-learning` |
| AutoPipeline's demo prints `DEMO FAIL` with `got 0`, and its `state.json` says a folder `is inside the repository but not ignored by git` | The run folder is inside the git clone. Rerun with `--out work/demo-run`, or leave out `--out` for a temporary folder |
| A download fails | Check the URL and Internet access. For a company proxy or certificate error follow [reader network guidance](letter-reader.md#networks-proxies-and-offline-machines); keep certificate checks enabled |
| The reader says `DEMO ERROR` | Read the named missing dependency or failed weight download. It is not a negative scientific result |
| The reader says `DEMO FAIL`, or noise looks like text | Keep the failed check. Compare inputs, weights and controls; do not select a nicer output and call it a pass |
| A large image runs out of memory | Stop, use a small crop, and read [large-map handling](letter-reader.md#big-maps) before retrying |
| An official notebook or GUI differs from this guide | Follow its current instructions and release notes; record the version and exact failing step |

For help, give your operating system, Python/tool version, the exact command, the complete error text and the small public or synthetic example you used. The [Vesuvius Discord](https://discord.gg/V4fJhvtaQn) is the official community; [this repository's issues](https://github.com/ChaseHendrick/Scrolls/issues) are for problems with these helpers. Remove tokens, personal paths and private candidate material before sharing. A reproducible setup failure is a useful contribution even if you never train a model.

## Sources and scope

Checked **17 October 2026** against the live official [Get Started](https://scrollprize.org/get_started) page and the [villa source at `1db9cd9`](https://github.com/ScrollPrize/villa/tree/1db9cd94487c2fb5e759cc4ee72018dcb7359984). The official page already offers interactive ink-labeling and surface-tracing exercises. This community guide adds the local installation, expected outputs and small-task checkpoints that connect that introduction to the official [current data notebook](https://github.com/ScrollPrize/open-data/blob/main/examples/get-to-know-a-dataset.ipynb), [VC3D tutorial](https://scrollprize.org/tutorial_VC3D) and [ink tutorial](https://scrollprize.org/tutorial5). It makes no comparative performance claim. Commands for our software are covered by its package tests; hosted services, official datasets and upstream tools have their own availability and requirements.
