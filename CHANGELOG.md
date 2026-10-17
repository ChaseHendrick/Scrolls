# Changelog

This file covers the `scrolls-workbench` package, the `kit` folder of this repository (`kit.__version__`, which the letter reader writes into every result's provenance). Tools released on their own keep their own notes: AutoPipeline in its release branch's `CHANGES.md`, and Unroll in its Space's `CHANGELOG.md`. The README's "Released tools" section lists every release.

To install a fixed version, name its tag:

```bash
python -m pip install "scrolls-workbench[reader] @ git+https://github.com/ChaseHendrick/Scrolls@workbench-v0.3.0"
```

## 0.3.0 (17 October 2026)

- **Letter reader:** explicit local Tesseract backend for Latin and other installed language packs, with word-level provenance, model hashes and blank/shuffle controls. Greek LineNet stays script-checked; language changes never relabel its alphabet. No runtime model downloads or remote OCR in the Tesseract route.
- **Greek weight profiles:** known line positions default to the measured ink-line checkpoint (`letters-v2-real`, CC BY-NC 4.0); automatic layout keeps `letters-v2-ccby` (CC BY 4.0). Explicit weights or profiles override this choice and the selected profile licence is recorded.
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
