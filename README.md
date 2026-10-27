# Scrolls: Vesuvius Challenge workbench

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab.svg)](#quick-start)
[![Vesuvius Challenge](https://img.shields.io/badge/Vesuvius_Challenge-scrollprize.org-b4965a.svg)](https://scrollprize.org/)

![Concept illustration of layered carbonized papyrus unfolding into a copper surface mesh.](docs/assets/scrolls-readme-hero.webp)

*Concept illustration. [Artwork notes](docs/assets/README.md).*

Open tools, public-data benchmarks and research notes for the [Vesuvius Challenge](https://scrollprize.org/): reading the carbonized Herculaneum papyri from X-ray CT scans. The tools plan, check, score and record runs of the official open-source pipeline, [ScrollPrize/villa](https://github.com/ScrollPrize/villa); they do not replace it.

> [!IMPORTANT]
> **This repository does not claim that any letters have been found in any scroll.** An ink map is model output, not a reading.

## Start here

- **New to the challenge?** [Start Here](docs/start-here.md) goes from a browser tour to one small task with the official tools, for macOS, Linux and Windows. You can begin without a GPU or programming experience.
- **Look first:** [Unroll](https://huggingface.co/spaces/SharpMeow/unroll) shows scroll scans in 3D in your browser, and the [picture guide](docs/workbench.md) shows the toolbox with real screenshots.
- **Practice offline:** [Scrolls Starter](docs/start-here.md#2-try-scrolls-starter-on-your-computer) has a synthetic exercise and a setup check.
- **Look up a word:** the [glossary](GLOSSARY.md).

## Released tools

<!-- releases:start (generated from docs/releases.json by python -m kit releases render; edit that list, not this section) -->
Every released tool, one line each; each name opens its guide. Generated from [`docs/releases.json`](docs/releases.json).

### Apps, packages and datasets

| Tool | What it does |
| --- | --- |
| [AutoPipeline](docs/tools/autopipeline.md) | Runs villa's VC3D tools and ink detection on a released scan, from surface checks to ink maps scored with controls (package, 0.1.9). |
| [Unroll (interactive 3D scroll viewer)](docs/tools/unroll.md) | Virtually unrolls scroll scans in 3D in your browser, with ink layers, CT tools and an Ink Bench for comparing ink models (Space). |
| [Crackle Check (is there ink crackle in this patch?)](docs/tools/crackle-check.md) | Asks one ink model whether a small patch of a segment shows ink crackle, with the reversed layer order as its control (Space, API and MCP). |
| [Snapped Labels (published surface labels moved onto the papyrus)](docs/tools/snapped-labels.md) | Every published surface label of PHerc0139, PHerc0814, PHerc0841 and PHerc0172, moved onto the papyrus recto face, as tifxyz meshes with a viewer on live CT. |
| [AFV Fibers (papyrus fibre curves for six whole scans)](docs/tools/afv-fibers.md) | Papyrus fibre curves from Qual's AFV V2 for six whole scans, as .afv files VC3D opens, with a Space to explore any box and a fibre-set catalog. |
| [Ink Atlas (seven ink models on the First Letters surfaces)](docs/tools/ink-atlas.md) | Seven public ink models on the same First Letters surfaces, one 9.6 um canvas: a dataset, a Space with a loupe and compare, and an MCP server. |
| [Lasagnetta (fast preview of villa's lasagna field)](docs/tools/lasagnetta.md) | A fast preview of villa's lasagna field, about 5 times faster than villa predict3d (6.6 times with larger tiles), with a built-in self-check against villa. |
| [Umbilici (center lines of 35 Herculaneum scans)](docs/tools/umbilici.md) | Every public center line (umbilicus) we know of for 35 scans, 57 lines from six sources, in 3D over the CT (Space). |
| [Fiber Checker (are papyrus fibers visible on a traced surface?)](docs/tools/fibercheck.md) | A free per-patch fiber map of any traced segment or your own tifxyz, with a self-check on every run, as a Space and a command line tool. |
| [Lasagna Fields (villa lasagna fields for ten scans)](docs/tools/lasagna-fields.md) | villa's lasagna fields for ten whole scans that had none in the open data, one dataset each, with a Space to view and make them. |
| [Segment Lens (published segment geometry viewer)](docs/tools/segment-lens.md) | Shows published segment meshes with geometry warnings and the Segment Atlas table, with an API and MCP server for agents (Space). |
| [dinovol embeddings of PHerc0841](docs/tools/dinovol-embeddings.md) | Precomputed dinovol embeddings of the whole PHerc0841 scan, to search, cluster or segment by feature similarity without a GPU. |
| [Headless VC3D for agents](docs/tools/vc3d-agent.md) | An MCP server and shell command that let an AI agent run villa's VC3D tools with no display, checks built in (package, 1.1.1). |
| [Ink Lens (control-checked ink on your own VC3D region)](docs/tools/ink-lens.md) | Checks one region of your own VC3D segment for ink in seconds, keeping only ink above its own reversed-depth control (Space). |
| [Scrolls Starter: a beginner path into the tools](docs/tools/starter.md) | A beginner path in your browser: a synthetic practice exercise with a control, a setup checker and a Scroll Text Reader command builder. |
| [Inkfilter: fixed surface-volume filters](docs/tools/inkfilter.md) | Makes model-free maps from a surface-volume window, each with a reversed-depth control; not a trained reader (package). |
| [Scroll Lens (3D DINO, ink and surface models on scan cubes)](docs/tools/scroll-lens.md) | Shows what the organizers' 3D models (dinovol, 3D ink, recto surface) see inside a cube of a public scan (Space). |

### Scrolls kit

Command-line tools, benchmarks and script folders that run from a clone of this repository. [Guide](docs/tools/cli.md). Open an area to see its tools.

<details>
<summary><b>Pipeline and agents</b> (3)</summary>

| Tool | What it does |
| --- | --- |
| [Scan catalog and batch plans](docs/tools/batch.md) | Lists released scan volumes, makes resumable batch plans and watches for new or changed inputs. |
| [Scroll to ink in one command (experimental)](docs/tools/scroll2ink.md) | Experimental: one command from a public scan and a seed point to an ink map with its reverse-depth control, stopping at a failed check. |
| [Swap any stage by name](docs/tools/stagereg.md) | Lists every option for each stage of reading a scroll, with its maker, license and maturity, so a workflow can swap any stage by name. |

</details>

<details>
<summary><b>Viewers and apps</b> (5)</summary>

| Tool | What it does |
| --- | --- |
| [Offline ink map comparison viewer](docs/tools/view.md) | Builds one offline HTML page to compare ink maps, their differences, labels and the mask. |
| [Terminal look and mouse viewer](docs/tools/termstyle.md) | Gives every kit command and script one styled terminal look, plain for pipes and --json, with a full-screen mouse viewer. |
| [Tool connection instructions](docs/tools/spaceconnect.md) | Writes and checks connection instructions and code examples for the public tools' hosted pages. |
| [Volume on a sheet in Neuroglancer](docs/tools/sheetview.md) | Samples a CT or prediction volume on a tifxyz surface and writes a mesh and Neuroglancer view. |
| [Volume overlay links](docs/tools/volumeview.md) | Creates Neuroglancer overlay links from supplied volume metadata. |

</details>

<details>
<summary><b>Surfaces and tracing</b> (13)</summary>

| Tool | What it does |
| --- | --- |
| [Bounded surface correction (experimental)](docs/tools/surfacefix.md) | Suggests bounded surface shifts using agreement between maps from two traces and keeps only shifts that pass its controls. |
| [Mesh and cross-scan audit](docs/tools/meshaudit.md) | Checks cross-scan transforms, mesh canvases and rendering depth against public catalog geometry. |
| [Planted defect generator](docs/tools/planted.md) | Plants sheet switches, holes and other defects into synthetic tifxyz surfaces with a known answer, to test checkers against. |
| [Published segment coverage](docs/tools/coverage.md) | Shows the heights and winding angles covered by published meshes and the gaps between them. |
| [Relative winding consistency check](docs/tools/windconsistency.md) | Passes relative winding counts only when every one is an integer and all of them can hold at once. |
| [Relative windings in a box](docs/tools/windlabel-box.md) | Grows chains of sheet crossings around a point and writes villa's relative_windings.json for a spiral fit, with a VC3D plugin. |
| [Scroll center (umbilicus) finder and coverage polish](docs/tools/umbilicus.md) | Finds a scroll's winding center line (umbilicus) in its CT scan with two small U-Nets and writes umbilicus.json for VC3D. |
| [Segment Atlas](docs/tools/atlas.md) | Measures published segment meshes with the same geometry checks and builds a searchable table. |
| [Segment stack check](docs/tools/stackcheck.md) | Checks a stack of consecutive tifxyz segments against the umbilicus from geometry alone: winding order, spacing, gaps and overlaps. |
| [Segments without VC3D](docs/tools/tifxyz.md) | Reads a tifxyz segment, local or from the open-data bucket, and reports its true area, grid, holes and folds, with numpy and tifffile only. |
| [Surface overlap and map comparison](docs/tools/overlap.md) | Checks whether traced surfaces cover the same sheet and compares their labels or ink maps with controls. |
| [Touching-sheets benchmark](docs/tools/hopbench.md) | Plants sheet hops at real contacts between PHerc0139's hand-traced windings and measures how often a one-sheet check misses them. |
| [UV overlap gate](docs/tools/uvgate.md) | Checks a flattened sheet's UV triangles for any overlap, with exact arithmetic, plus coverage. |

</details>

<details>
<summary><b>Ink maps and models</b> (4)</summary>

| Tool | What it does |
| --- | --- |
| [Checkpoint averaging](docs/tools/soup.md) | Averages compatible model checkpoints from one training run and refuses a mixture of different seeds. |
| [Ink map ensemble](docs/tools/ensemble.md) | Combines ink maps of the same surface by weighted score or pixel rank, keeping only pixels predicted by every input. |
| [Mac ink inference and verification scripts](docs/tools/mac-w045.md) | Runs public ink-model checks on a Mac with reverse-depth controls. |
| [v8in ink model runner](docs/tools/v8in-run.md) | Runs the released v8in ink model on layer images, including an optional reduced-precision Mac GPU mode. |

</details>

<details>
<summary><b>Scoring and controls</b> (9)</summary>

| Tool | What it does |
| --- | --- |
| [Controlled benchmark gate](docs/tools/gate.md) | Checks recorded benchmark scores against the declared pass rules and required controls. |
| [Controlled ink AUC scoring](docs/tools/auc.md) | Scores an ink map against labeled ink and background inside a supervision mask, alongside a reverse-depth control. |
| [Ink map agreement check](docs/tools/verify.md) | Checks whether two ink maps of the same input agree while requiring a deliberately different control to fail. |
| [Ink map self-check (neighbor-sheet test)](docs/tools/sheetcheck.md) | Checks without labels whether an ink map reads the traced sheet, comparing it with the same model one and two sheets away. |
| [Letter-scale ink score](docs/tools/hpscore.md) | Compares an ink map with published labels after removing broad brightness changes, with displaced-label and reverse-depth controls. |
| [Research integrity checks for Vesuvius claims](docs/tools/integrity.md) | Checks a claim before it goes out: controls on the same pixels, held-out status, number sources, preregistration and wording. |
| [StrokeNet text-likeness score](docs/tools/strokenet.md) | Scores how much a window of an ink map looks like lines of text, with rotation and IAAFT controls, using only NumPy. |
| [Synthetic map controls](docs/tools/phantom.md) | Creates known-answer synthetic inputs for checking ink-map scoring and controls. |
| [Text-row pattern score](docs/tools/rowscore.md) | Measures repeating bands in forward and reverse ink maps as a triage aid, without interpreting text. |

</details>

<details>
<summary><b>Letters and titles</b> (4)</summary>

| Tool | What it does |
| --- | --- |
| [Greek character language model](docs/tools/greeklm.md) | Builds and scores a character language model from public Greek text for the letter reader. |
| [Greek gap restoration benchmark](docs/tools/greekfill.md) | Hides letters in public Greek text and scores hosted text models against a Kneser-Ney letter model under a frozen rule. |
| [Greek letter classifier and line reader for agents](docs/tools/letterclass.md) | Names Greek capital letters in given boxes on papyrus photographs and reads lines of boxes, as a JSON command and an MCP server. |
| [Scroll Text Reader](docs/tools/letterread.md) | Proposes Greek capital letters with boxes and confidences on ink maps, drawn labels and photographs, on a CPU, with null and orientation controls. |

</details>

<details>
<summary><b>Data and downloads</b> (7)</summary>

| Tool | What it does |
| --- | --- |
| [False-404 test relay](docs/tools/false404-relay.md) | Replays selected false missing-file responses through a local relay so cache handling can be tested. |
| [Fast public label downloads](docs/tools/hfpull.md) | Downloads a folder of the organizers' public Hugging Face datasets bucket fast, fetching each distinct file once. |
| [Find, center line, cite and villa helpers](docs/tools/find.md) | Lists everything public for one scroll, fetches its best center line, prints credit lines, and checks villa PR timing and text. |
| [Layer extraction and shuffle control](docs/tools/layers.md) | Exports surface-volume layers as images and creates a shuffled-depth control. |
| [Public bucket downloader](docs/tools/fetch.md) | Copies files under a public data bucket prefix to a local folder and skips complete files when resuming. |
| [Published ink labels and model exposure](docs/tools/labels.md) | Lists published ink label sets and the recorded training exposure of public ink models. |
| [VC3D false-404 relay and cache repair](docs/tools/vc3dfix.md) | Runs VC3D through a relay that retries false missing-file responses and checks its empty-chunk cache. |

</details>

<details>
<summary><b>Training</b> (1)</summary>

| Tool | What it does |
| --- | --- |
| [Segmentation model comparison tools (experimental)](docs/tools/segzoo.md) | Lists segmentation model families and provides training and controlled scoring scripts. |

</details>

<details>
<summary><b>Planning and prizes</b> (4)</summary>

| Tool | What it does |
| --- | --- |
| [Local setup checker](docs/tools/doctor.md) | Checks the machine and installed tools before a pipeline run. |
| [Pipeline planning and cost estimates](docs/tools/plan.md) | Prints the official pipeline commands for a scroll without running them. |
| [Public prize snapshot](docs/tools/prizes.md) | Lists public prize requirements from a dated local snapshot. |
| [Submission folder check](docs/tools/submitcheck.md) | Checks a submission folder against published file requirements and lists the remaining checks for a person. |

</details>

<details>
<summary><b>Compute and cost</b> (4)</summary>

| Tool | What it does |
| --- | --- |
| [Hugging Face Jobs ledger importer](docs/tools/hf-rows.md) | Adds finished Hugging Face Jobs to a cost ledger with the cost from Hugging Face's own bill, once per Job, and restricts public ledgers to generic work. |
| [Local run time and cost log](docs/tools/run-local.md) | Runs a local command and records its elapsed time and estimated electricity cost, or adds records of past runs. |
| [Modal ledger row importer](docs/tools/modal-row.md) | Adds a recorded job to a cost ledger once and restricts public ledgers to rows marked generic. |
| [Run time and energy summary](docs/tools/compute.md) | Summarizes machine time from run provenance records, with an optional energy estimate. |

</details>

<details>
<summary><b>Records and provenance</b> (2)</summary>

| Tool | What it does |
| --- | --- |
| [Experiment ledger](docs/tools/run-ledger.md) | Keeps a run record with a fixed readout rule, status, costs, file fingerprints and checks. |
| [Run provenance records](docs/tools/provenance.md) | Records run settings and file fingerprints, then checks the record and its files for changes. |

</details>

<details>
<summary><b>Releases and repository</b> (3)</summary>

| Tool | What it does |
| --- | --- |
| [Recurring repository checks](docs/tools/routines.md) | Lists and runs the registered recurring repository checks and records their status locally. |
| [Release list and README generator](docs/tools/releases.md) | Keeps the public release list, compact tool inventory and generated README section in step. |
| [Stale repository reference check](docs/tools/stale.md) | Checks live documentation and registries for outdated references and pending work. |

</details>
<!-- releases:end -->

## Quick start

Python 3.10 or newer. Most `kit` commands need only the standard library; the map tools add numpy and tifffile, and the heavy pipeline (VC3D, PyTorch, ink models) comes from villa. `python -m kit doctor` says what is missing.

```bash
git clone --depth 1 https://github.com/ChaseHendrick/Scrolls.git
cd Scrolls
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[all]"
# open prizes, deadlines and eligible scrolls, from a dated snapshot
python -m kit prizes
# what this machine has and lacks for a run
python -m kit doctor
# the official commands for one eligible scroll, printed and never run
python -m kit plan PHerc0826
# score an ink map against its labels, with the reverse-depth map as control
python -m kit auc MAP.tif --control MAP_reverse.tif --labels L/inklabels.zarr --mask L/supervision.zarr
# Scroll Text Reader on synthetic letters
scrolls-letterdemo
python -m unittest discover -s tests
```

Every command is in [`docs/tools/cli.md`](docs/tools/cli.md), and every tool has a page in [`docs/tools/`](docs/tools/README.md). Install AutoPipeline in its own environment, since both install `kit`.

## Open prizes (snapshot 2026-10-11)

| Prize | Money | Deadline | What wins |
| --- | --- | --- | --- |
| [2027 Grand Prize](https://scrollprize.org/prizes#2027-grand-prize) | $800k / $100k / $50k / $50k | 25 Jun 2027 | Fully unroll one of 13 sealed scrolls; at least 70% of each counted column's preserved characters legible |
| [First Letters](https://scrollprize.org/prizes#first-letters-prizes) | $50k per scroll, 9 more ($450k remaining; one already used) | 25 Jun 2027 | First team to show 10 legible letters in a single 4 cm² area of one of 21 eligible scrolls |
| [PHerc. Paris 4 title](https://scrollprize.org/prizes#first-title-prize) | $50k | 25 Jun 2027 | A papyrologist-readable image of Scroll 1's title |
| [Progress Prizes](https://scrollprize.org/prizes#progress-prizes) | $20k best of month, plus $250 to $20k awards | monthly, several entries a month allowed (next: 31 Oct 2026) | Open-source tools, models, datasets, fixes, reports that help read the scrolls |

> [!IMPORTANT]
> All prizes require open-sourcing your method (permissive license) to accept the money. Details, submission contents and the eligible-scroll lists: [`docs/prizes.md`](docs/prizes.md).

## Novel findings

> [!NOTE]
> **Reviewed 23 October 2026.** One line per finding, newest group first. Each keeps its number, so "finding N" elsewhere still points at the right one. The full text of each, with its controls, limits, corrections and links, is in [`docs/FINDINGS.md`](docs/FINDINGS.md); every number with its settings and source is in [`docs/results.json`](docs/results.json). Public labeled data only; an ink map is model output, not a reading.

**Tool results** ([details](docs/FINDINGS.md#tool-results))

15. **Center Finder:** 0.73 mm median from the 13 published lines with each scroll held out, and level with villa's `vc_gen_umbilicus` on two sealed lines (0.56 against 0.81 mm; closer on PHerc0139 only) (13 and 22 October 2026, model output).
16. **StrokeNet tells text from the same text turned 90 degrees far better than any simple score** (AUC 0.994 against 0.865, six held-out PHerc. Paris 4 tracings, 14 October 2026, model output); it passed 7 of the 9 bars of that first test, plain ink density matched it at text against blank papyrus, and part of its sense of orientation may come from the direction of the papyrus rather than the writing.
17. **Inkfilter's face mix** scored mean AUC 0.736 against 0.704 for alpha compositing on 56 confirmation windows, from the segments it was developed on; not a trained-reader comparison (17 October 2026).
18. **StrokeNet's two-density score, with no network, came out ahead of ink density inside segments on PHerc0500P2 with ink_9um** (mean within-segment AUC 0.701 against 0.662, ahead in all 11 segments, both controls passed; 22 October 2026, model output; ink_9um reads this scroll weakly).
19. **Three hosted text models restored hidden Greek letters in Philodemus, De Musica, less often than a Kneser-Ney letter model** (gap letter accuracy 0.181, 0.181 and 0.118 against 0.331, single letters 0.447 at best against 0.895, no recall detected (probe about 0.08); public text, 22 October 2026, model output).
20. **Our letter classifier, trained on Hell-Char only, named Greek letters on fresh papyrus photographs better than Hell-Char ConvNeXt-V2** (error 0.291 against 0.340 on the 8,479 ICDAR 2023 test boxes, boxes given, every control passed; as lines with a no-Homer Greek letter model it was level with Hell-Char given the same model; 24 October 2026, model output; photographs, not ink maps).

**Pipeline and reader checks** ([details](docs/FINDINGS.md#pipeline-and-reader-checks))

12. **A transient S3 404 becomes a permanent hole of zeros in VC3D's renders and traces** ([villa #2058](https://github.com/ScrollPrize/villa/issues/2058), draft fix [villa #2060](https://github.com/ScrollPrize/villa/pull/2060); 8 to 12 October 2026).
13. **villa's tracer does not hold an explicit seed, so a trace can start on the next winding** ([villa #2059](https://github.com/ScrollPrize/villa/issues/2059); one seed on PHerc0139, 11 and 12 October 2026).
14. **A traced surface's render comes out turned, and `ink_9um` reads it much worse until it is turned upright** (one trace, development data, 13 October 2026); Reader v2 did not replicate it cleanly, so `ink.orient` stays opt in.

**Earlier measurements and corrections** ([details](docs/FINDINGS.md#earlier-measurements-and-corrections))

1. **On w045, v8in scores below `ink_9um`, but `ink_9um` trained on that surface,** so the test cannot say which reads an unseen surface better (corrected 8 and 9 October 2026).
2. **Scoring a crop needs an edge margin:** a 64 px edge makes bare-crop and whole-map scores agree.
3. **A threshold taken from a training segment misses about 96 % of real ink on an unseen scroll.**
4. **Averaging depth windows matches the best window chosen with labels on PHerc0841** (related prior work is cited).
5. **Two of PHerc0841's three labeled segments, w00 and ag896, are the same papyrus.**
6. **Raw CT brightness alone carries almost no ink signal on PHerc0841.**
7. **Ink-map agreement between two traces falls with their distance** (model output; the maps are probably in-sample).
8. **PHerc0841 has 3.4 cm² of supervision, so its AUCs need intervals.**
9. **Cross-trace agreement suggests a label-free triage experiment** (untested idea).
10. **Every published surface volume matches a published mesh, but the stored PHerc1667 matrix contradicts its own landmarks** (reported earlier by kadenpool in [villa #1843](https://github.com/ScrollPrize/villa/issues/1843); our CT check agrees with the landmarks).
11. **PHerc1667's 1.129 um renders appear misplaced** (post hoc; the preregistered version failed its control, so it needs a calibrated rerun).

Follow-up tests, partial results, the adaptive-geometry experiment and the CPU speed checks are listed after finding 11 in [`docs/FINDINGS.md`](docs/FINDINGS.md#earlier-measurements-and-corrections).

## Documentation

- [`docs/README.md`](docs/README.md): the docs index, one home per topic.
- [`docs/MAP.md`](docs/MAP.md): the repository map, one row per module and script.
- [`docs/engine.md`](docs/engine.md): what villa does, what `kit/` adds, and what this repository does not do.
- [`docs/prizes.md`](docs/prizes.md), [`docs/state-of-play.md`](docs/state-of-play.md), [`docs/pipeline.md`](docs/pipeline.md): the prizes, what has been tried, and how a scan becomes text.
- [`AGENTS.md`](AGENTS.md) and [`docs/AI-AGENTS.md`](docs/AI-AGENTS.md): rules for AI agents and for people; [`docs/QUALITY.md`](docs/QUALITY.md), [`docs/NOVELTY.md`](docs/NOVELTY.md) and [`docs/TESTING.md`](docs/TESTING.md): the bar for claims and tests.
- [`CONTRIBUTING.md`](CONTRIBUTING.md), [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md), [`SECURITY.md`](SECURITY.md) and [`SUPPORT.md`](SUPPORT.md).

Private plans, candidate outputs and submission material live in [Scrolls-private](https://github.com/ChaseHendrick/Scrolls-private) (access required).

## License

Code and documentation: [Apache-2.0](LICENSE), copyright 2026 Chase Hendrick and Scrolls contributors; see [NOTICE](NOTICE). Cite with [`CITATION.cff`](CITATION.cff).

Third-party software, data, labels, renders and model weights keep their own licenses, which the code license does not cover. Scroll Text Reader's Greek weights are CC BY 4.0 (`letters-v2-ccby`) and CC BY-NC 4.0 (`letters-v2-real`, trained with ICDAR 2023 Greek letters); the Center Finder's weights (`umbilicus-v1`) are CC BY-NC 4.0, because the CT they learned from is. Local OCR language packs keep their source licenses. Check each source's terms, including the [Vesuvius data browser](https://scrollprize.org/data_browser), before use or redistribution.

> [!WARNING]
> Do not commit scroll data, renders or ink maps to this public repository.
