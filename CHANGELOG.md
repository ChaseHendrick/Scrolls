# Changelog

This file covers the `scrolls-workbench` package, the `kit` folder of this repository (`kit.__version__`, which the letter reader writes into every result's provenance). Tools released on their own keep their own notes: AutoPipeline in its release branch's `CHANGES.md`, and Unroll in its Space's `CHANGELOG.md`. The README's "Released tools" section lists every release.

To install a fixed version, name its tag:

```bash
python -m pip install "scrolls-workbench[reader] @ git+https://github.com/ChaseHendrick/Scrolls@workbench-v0.4.1"
```

## Unreleased

- **Segments without VC3D:** `python -m kit tifxyz info|stretch|check|obj|preview|facing` reads one tifxyz segment (local or on the open-data bucket) and gives its area in cm2, how isometric its grid is, holes, folds and stretched cells with a picture, an OBJ for Blender, a shaded preview and which way it faces. How-to with pictures: [docs/segments-without-vc3d.md](docs/segments-without-vc3d.md).
- **Segment Atlas:** `python -m kit atlas show SCROLL` prints the same numbers for every published segment (area, isometry, holes, folds, stretch), from the public dataset SharpMeow/vesuvius-segment-atlas, which a daily Hugging Face Job refreshes with `python -m kit atlas build`.
- **Segment Lens:** a Hugging Face Space (`spaces/segment-lens/`) that shows published segments of scans on no prize list in 3D, with holes, folds and stretched edges painted on, beside their atlas numbers.
- **Winding coverage:** `python -m kit coverage SCROLL` places a volume's published meshes around its center line and reports the heights and angles traced, the turns each mesh spans, the wrap pitch measured on the meshes, and about how many wraps lie untraced between neighboring meshes (or none, for copies).
- **Chunks and diff:** `python -m kit tifxyz chunks SEGMENT VOLUME` lists the zarr chunks a segment touches with their bytes, and `--fetch DEST` copies only those; `python -m kit tifxyz diff A B` compares two versions of a segment (added, removed and moved nodes, area change, a picture).
- **Ink labels:** `python -m kit labels [SCROLL]` lists every published ink label set per segment on the open-data bucket, with the training exposure this repository's records give each segment (unknown when there is none).
- **Find, center line, cite:** `python -m kit find SCROLL` lists a scroll's volumes, segments, bucket predictions, center lines and Hugging Face matches; `python -m kit centerline get SCROLL --into FOLDER` writes its center line as `umbilicus.json` for VC3D (sha256 checked); `python -m kit cite SCROLL` prints credit lines.
- **villa helpers:** `python -m kit prclock USER` shows days before villa's time-limit workflow closes each open PR; `python -m kit prtext BODY.md` checks a PR or issue body against villa's templates.
- **Help:** `python -m kit --help` groups commands by task, `python -m kit help COMMAND` shows a worked example, and a mistyped command suggests the closest names.
- **doctor and fetch:** `doctor` checks for an Intel Python under Rosetta on Apple Silicon, a container CPU quota smaller than the thread counts, and slow disks; `fetch` checks free space first and has `--dry-run`.
- **doctor for AMD, Intel and rented machines:** `doctor` names AMD (ROCm) and Intel GPUs instead of failing with "No NVIDIA GPU found", and `doctor --remote` shows where VC3D will cache streamed chunks, the space and speed there, and on RunPod whether that folder survives a stop.
- **Submission preflight:** `python -m kit submitcheck FOLDER --prize first-letters|grand|title` checks a prize folder against the prize page's file rules and quotes each one.
- **Docs:** [docs/tracing-tools.md](docs/tracing-tools.md), which tool to trace, check or view a segment with; [docs/prizes.md](docs/prizes.md) answers common prize questions with quotes from the prize page only.

## 0.4.1 (18 October 2026)

- **Offline ink-map viewer:** hovering now reports the scaled disagreement encoded in the overlay, including intermediate values such as 0.71. It previously read the red color channel and displayed 1.00 wherever disagreement was nonzero. Regenerate existing HTML pages to use the fix.
- **Gate A reference:** documents the existing blocked verdict on a Mac/CPU mismatch, replacement records and reverse-control edge checks. Scoring behavior is unchanged.

## 0.4.0 (17 October 2026)

- **Volume viewer:** `python -m kit volumeview` builds a Neuroglancer link, state or receipt from an explicit local manifest. It checks axes, voxel spacing, physical extents and declared frames before combining a public CT volume and prediction. This validates supplied metadata, not remote registration; no array is downloaded.

- **Scrolls Starter:** an offline browser introduction, synthetic practice with a known answer and a noise-only control, a local setup snapshot, and a command builder for the optional reader. A portable HTML download works without Python; the installed checker reports the current environment. The Start Here guide connects these exercises and existing community tools to the official data notebook, VC3D and ink workflow.

- **Scroll Text Reader:** the current name for the former Greek Letter Reader, covering Greek LineNet and optional local Tesseract OCR for installed languages. Commands, Python APIs, model names and output schemas are unchanged. Existing benchmark limits still apply.

## 0.3.0 (17 October 2026)

- **Letter reader:** explicit local Tesseract backend for Latin and other installed language packs, with word-level provenance, model hashes and blank/shuffle controls. Greek LineNet stays script-checked; language changes never relabel its alphabet. No runtime model downloads or remote OCR in the Tesseract route.
- **Greek weight profiles:** known line positions default to the measured ink-line checkpoint (`letters-v2-real`, CC BY-NC 4.0); automatic layout keeps `letters-v2-ccby` (CC BY 4.0). Explicit weights or profiles override this choice and the selected profile license is recorded.
- **Reader sessions:** `ReaderSession.switch()` changes weights, profiles, languages or backends on one Python object. It loads and validates the replacement before activation, retains the previous working selection on failure and records the active selection in each result. Tesseract remains a local subprocess per read. A language pack that fails initialization is rejected even if the engine could continue with only part of the requested language set.
- **Segmentation model zoo** (`python -m kit segzoo datalist`): refuse duplicate case/channel files, mismatched label endings, malformed dataset metadata, empty datasets and fewer than two folds before writing an Auto3DSeg training plan. Previously duplicates could silently replace an input and zero folds caused a traceback. Valid datasets keep the same fold assignments.

## 0.2.0 (16 October 2026)

The first tagged version. It holds everything released from this repository from 14 to 16 October 2026.

- **Greek letter reader** (`scrolls-letterread`, `scrolls-letterlines`, `scrolls-letterdemo`): `letters-v2-ccby` (CC BY 4.0) is the default weights; reads whole native maps with the letter size in mm; turned, mirrored and tilted text, and photographs; a status code per read and per column, a control map, and where the letters are; a Python API with provenance; CSV and PAGE XML exports; fine-tuning on your own lines. Guide: [`docs/letter-reader.md`](docs/letter-reader.md).
- **StrokeNet text-likeness score** (`python -m kit strokenet`), with rotation and IAAFT controls and its full held-out result. Card: [`docs/strokenet.md`](docs/strokenet.md).
- **Segment stack check** (`python -m kit stackcheck`): order, spacing, gaps and overlaps of a stack of tifxyz segments against the scroll's umbilicus, from geometry alone.
- **AutoPipeline on every scan, planning only** (`python -m kit run all --dry-run`, `python -m kit run watch`): a catalog of every scan volume in the open-data bucket, per-scan settings, a priced plan and a watcher for new or changed volumes. It launches nothing.
- **Release list** (`python -m kit releases`): the README's "Released tools" section is written from `docs/releases.json`, and `kit releases check` fails when they disagree.
- The command line builds its parser once per process, so repeated calls are much faster.
- The Modal rates (`kit/data/modal-rates.json`) ship with the package, so `kit run all` and `python -m kit.cloudcost` work after a pip install.
- **Checks that can fail, and inputs checked**, from an adversarial test of the tools: `kit verify` and `kit auc` refuse controls and maps that made a check pass by construction; the batch planner keeps every file inside its state folder, plans a failed row again and approves only the plan it computes; the release list refuses inline HTML and script links; the letter reader, StrokeNet, the umbilicus finder, `provenance check` and the TIFF reader refuse inputs that crashed, hung or used unbounded memory. Scores for valid inputs are unchanged.
- `python -m kit run modal-row` appends one row to a Modal ledger; the public ledger takes a row only with `--public-generic` and a run marked generic.

## 0.1.0 (14 October 2026)

The version number the package carried from the letter reader's first release until 0.2.0. It was never tagged, so results stamped 0.1.0 may come from any commit between 14 and 16 October 2026; their provenance records name the weights they read with (by SHA-256).
