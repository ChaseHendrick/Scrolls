# inkfilter: fixed image filters for surface volumes

Inkfilter 0.1.0 makes a map from a local surface-volume window using fixed operations and writes a reversed-depth control, with no trained model or weights.

| Field | Value |
| --- | --- |
| Id | `inkfilter` |
| Status | Branch only |
| Kind | package |
| Area | Ink maps and models |
| Run | `scrolls-inkfilter`, `python -m scrolls_inkfilter`, `from scrolls_inkfilter import ink_map`; `python demo.py demo-output` in the package directory |
| Code | `submissions/progress-2026-10-inkfilter/` on its branch: `src/scrolls_inkfilter/core.py`, `src/scrolls_inkfilter/cli.py`, `src/scrolls_inkfilter/__init__.py`, `src/scrolls_inkfilter/__main__.py`, `demo.py`, `evidence/summarize.py` |
| Tests | `submissions/progress-2026-10-inkfilter/tests/test_core.py` and `submissions/progress-2026-10-inkfilter/tests/test_cli.py` on its branch |
| Needs | Python 3.10 or newer and NumPy; Python 3.11 or newer for optional Zarr 3. Local TIFF support needs tifffile. Tested on Python 3.12.14 with NumPy 2.5.4, tifffile 2026.10.15 and zarr 3.4.1; exact pins in `requirements-test.txt` |
| Runs on | CPU. All 25 synthetic tests took 0.683 seconds in the 17 October 2026 cloud packaging check; real-data adapter runtime and peak RAM were not measured |
| Network | None for filtering, the synthetic demo or saved-score aggregation. Installing dependencies contacts the configured Python package index |
| Writes | The requested `.npy`, `.tif` or `.tiff` float32 map, `_reverse` map and `.json` record; creates the output folder and refuses existing files unless `--overwrite`. The demo creates a new directory containing wholly synthetic input and these outputs |
| Go-ahead | Not needed for local CPU use on data the user may access. Needed before publishing maps, posting or uploading (the go-ahead rule, hard rule 8) |
| Released | Public branch `submission/progress-2026-10-inkfilter`, commit `4953f17851aa9b2ffd3c26c86e85ecdabd659ca6`; code is not on public `main` |
| License | Original code: [Apache-2.0](https://github.com/ChaseHendrick/Scrolls/blob/4953f17851aa9b2ffd3c26c86e85ecdabd659ca6/submissions/progress-2026-10-inkfilter/LICENSE). Referenced data and methods keep their own licenses; data and upstream implementations are not bundled |
| Guide | [Package README](https://github.com/ChaseHendrick/Scrolls/blob/4953f17851aa9b2ffd3c26c86e85ecdabd659ca6/submissions/progress-2026-10-inkfilter/README.md), [evidence and limits](https://github.com/ChaseHendrick/Scrolls/blob/4953f17851aa9b2ffd3c26c86e85ecdabd659ca6/submissions/progress-2026-10-inkfilter/evidence/README.md) |
| Branch | `submission/progress-2026-10-inkfilter` at `4953f17851aa9b2ffd3c26c86e85ecdabd659ca6` |
| Checked | 2026-10-17 against commit `4953f17851aa9b2ffd3c26c86e85ecdabd659ca6` |

![Concept illustration of a stack of thin papyrus layers pierced by a copper sampling column, linked to an upright panel with a banded copper response and, behind it, a dimmer panel for the reversed-depth control.](../assets/inkfilter/inkfilter-hero.webp)

*Concept illustration: a surface volume's layers, a fixed filter down through them, its response and the reversed-depth control. Synthetic fields only, no ink.*

## What it does

A surface volume is a stack rendered along a mesh's normal, with depth followed by the two flattened surface axes. Inkfilter combines front-to-back alpha compositing, the papyrus-to-air edge step and fine texture. It normalizes these components, averages them, subtracts a broad background and smooths the result. No label or trained weight is read at run time.

The high-z face is the assumed ink side, so every command run also processes reversed depth. A map is filter output, not a reading. The default recipe was selected on published labels at approximately 4.8 um per pixel; other resolutions and custom recipes need their own evaluation. `face-mix-sharp` reduces smoothing for inspection and is not the confirmed recipe.

On 56 confirmation windows from the same 28 segments and seven scrolls used in development, the default mean AUC was 0.7357, versus 0.7042 for the selected alpha-compositing baseline and 0.6276 for its reversed-depth control. Alpha alone wins on three scrolls; the reverse filter wins on one. This is a narrow comparison with tested fixed filters, not a trained-reader comparison or evidence of generalization to wholly unseen scrolls. The linked evidence gives all rows, intervals, controls and limitations.

Claim label: Model output, for maps and numerical comparisons.

## Where the code is

The package is at `submissions/progress-2026-10-inkfilter/` on public branch `submission/progress-2026-10-inkfilter`, commit `4953f17851aa9b2ffd3c26c86e85ecdabd659ca6`. It installs as `scrolls_inkfilter`, separate from `kit`. Core numerical functions are in `src/scrolls_inkfilter/core.py`; the local-file adapter is in `cli.py`; synthetic tests, a demo and saved-score evidence accompany them.

```bash
git clone --branch submission/progress-2026-10-inkfilter --depth 1 https://github.com/ChaseHendrick/Scrolls.git scrolls-inkfilter
cd scrolls-inkfilter
git checkout 4953f17851aa9b2ffd3c26c86e85ecdabd659ca6
cd submissions/progress-2026-10-inkfilter
```

## How to run it

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
python demo.py demo-output
scrolls-inkfilter demo-output/synthetic.npy --output second-map.npy
```

The tested demo exits 0 and prints JSON containing `recipe_name: "face-mix"`, output/control/record paths, crop `[0,96,0,96]`, shape `[40,96,96]` and `note: "filter output, not a reading"`. The three output files must exist. Synthetic success establishes packaging and calculation behavior, not real-data accuracy.

For TIFF and Zarr use `python -m pip install '.[io]'` with Python 3.11 or newer. `scrolls-inkfilter --help` lists the local input, `--output`, `--level` (default 0), `--crop Y0 Y1 X0 X1` (half-open), `--recipe` (default `face-mix`) and `--overwrite`. The [package reference](https://github.com/ChaseHendrick/Scrolls/blob/4953f17851aa9b2ffd3c26c86e85ecdabd659ca6/submissions/progress-2026-10-inkfilter/README.md) gives exact conventions and failure behavior.

```bash
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
python evidence/summarize.py
```

The first check runs 25 synthetic tests, including refusing output paths inside the input store through direct paths or symlinks, and rejecting a Zarr subgroup where an array is required. The second recomputes saved scalar-score aggregates and prints `AGGREGATE CHECK PASS: 56 saved window scores; no map rerun`. It does not reproduce the original maps or baseline bank from raw scans.

## Inputs and outputs

Input is a local `(Z,H,W)` NumPy array, TIFF stack, bare Zarr array or Zarr group with numeric level names. Dtypes are uint8, uint16 or finite floating point in [0,1]; zero denotes unrendered data. The CLI accepts depths 3 to 4096, positive height and width and a crop contained within the selected array. Remote URLs, meshes and trained weights are not input formats. TIFF stacks load fully before cropping; NumPy and Zarr can slice first. Keep windows around 1024 pixels a side because several floating copies are held in RAM.

Output maps are float32 scores, not calibrated probabilities. The JSON record contains schema version, package version, input path, level, crop, full shape, recipe name/parameters, threshold/face summary, output paths and the filter-output note. A successful command exits 0 and prints that JSON. Invalid arguments, bad data and I/O failures exit 2 with a diagnostic. Existing outputs are refused unless `--overwrite` is passed; failed writes can leave partial outputs. All resolved output paths must lie outside a directory input, including symlinks, and no output may replace a file input. The three resolved output paths must differ; symbolic or multiply linked output files are refused even with `--overwrite`. The command never changes the input.

## Why it is not on the default branch

This release uses a self-contained package branch so it can be installed without private repository helpers. Public `main` holds this reference page and the release entry. The released numerical filter is frozen; the new local-file adapter is verified on synthetic data only. Remote volume access and the original study's full baseline bank are not included.

## For agents

- **Revive:** Use the package commit above and its own virtual environment. Install only NumPy for `.npy` input/output, or the `io` extra for TIFF/Zarr. Run the synthetic tests before processing local surface-volume windows.
- **Check first:** Verify shape, dtype, voxel scale, selected level and crop; use a fresh output name. Read both the forward and reverse results. A passing synthetic run and saved-score aggregate check do not establish quality on a new scroll or regenerate the original real-data scores.
- **Never:** Call a filter map a reading, omit an unfavorable control, present the confirmation as unseen-scroll or trained-reader superiority, or publish a possible discovery or target-scroll map.

## History

- 2026-10-17: Version 0.1.0 packages the frozen numerical filter with a local-file adapter, synthetic tests and scalar-score evidence; publication commit `4953f17851aa9b2ffd3c26c86e85ecdabd659ca6`.

## Related

- [Package README](https://github.com/ChaseHendrick/Scrolls/blob/4953f17851aa9b2ffd3c26c86e85ecdabd659ca6/submissions/progress-2026-10-inkfilter/README.md): install, options, algorithm, limitations and attribution.
- [Confirmation evidence](https://github.com/ChaseHendrick/Scrolls/blob/4953f17851aa9b2ffd3c26c86e85ecdabd659ca6/submissions/progress-2026-10-inkfilter/evidence/README.md): frozen definitions, public window list, saved scores and negative results.
- [auc](auc.md): score maps against published labels with a reverse-depth control.
- [autopipeline](autopipeline.md): the pipeline that runs trained ink detection and scores its controls.
