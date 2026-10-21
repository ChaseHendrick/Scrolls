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

## What it does

A surface volume is a stack rendered along a mesh's normal, with depth followed by the two flattened surface axes. Inkfilter combines front-to-back alpha compositing, the papyrus-to-air edge step and fine texture. It normalizes these components, averages them, subtracts a broad background and smooths the result. No label or trained weight is read at run time.

The high-z face is the assumed ink side, so every command run also processes reversed depth. A map is filter output, not a reading. The default recipe was selected on published labels at approximately 4.8 um per pixel; other resolutions and custom recipes need their own evaluation. `face-mix-sharp` reduces smoothing for inspection and is not the confirmed recipe.

On 56 confirmation windows from the same 28 segments and seven scrolls used in development, the default mean AUC was 0.7357, versus 0.7042 for the selected alpha-compositing baseline and 0.6276 for its reversed-depth control. Alpha alone wins on three scrolls; the reverse filter wins on one. This is a narrow comparison with tested fixed filters, not a trained-reader comparison or evidence of generalization to wholly unseen scrolls. The linked evidence gives all rows, intervals, controls and limitations. A second frozen test on 44 fresh windows, run on 21 October 2026, is below.

### Fresh-window check, 21 October 2026

A second one-shot test scored the same frozen `face-mix` recipe on 44 windows nobody had scored before: windows 4 and 5, taken by the same greedy pick of balanced labeled ink and background, of 22 publicly labeled segments on six scrolls. They are new windows of segments used in development, not unseen scrolls. PHerc0814, where the reversed control won on 17 October, has no windows 4 and 5, so that case was not tested again. The rules and the window list were frozen in a private commit (`3b35f149`, 20 October 2026, 20:27 UTC) before any of these windows was read; that commit is not public, so the order cannot be checked from outside. The test ran once on CPU at no cost. A neighboring process pushed the machine out of memory after 24 windows, and the other 20 were rerun with the same code, as the frozen rules allow; no window was dropped.

Model output. Each scroll is the mean of its segments and each segment the mean of its windows; intervals are segment-bootstrap 95 % intervals.

| Comparison, mean of six scrolls | A | B | A minus B | 95 % interval | Scrolls where A is higher |
| --- | --- | --- | --- | --- | --- |
| `face-mix` minus alpha compositing | 0.693 | 0.652 | +0.040 | +0.030 to +0.050 | 4 of 6 |
| `face-mix` minus its reversed-depth map | 0.693 | 0.549 | +0.144 | +0.107 to +0.175 | 5 of 6 |
| Alpha compositing minus its reversed-depth map | 0.652 | 0.575 | +0.078 | +0.068 to +0.086 | 6 of 6 |

| Scroll | Segments | `face-mix` | Alpha compositing | `face-mix` minus alpha | Reversed-depth `face-mix` |
| --- | --- | --- | --- | --- | --- |
| PHerc0009B | 1 | 0.810 | 0.749 | +0.061 | 0.473 |
| PHerc0139 | 4 | 0.634 | 0.666 | -0.032 | 0.655 |
| PHerc0500P2 | 1 | 0.625 | 0.560 | +0.066 | 0.526 |
| PHerc0841 | 2 | 0.641 | 0.590 | +0.051 | 0.370 |
| PHerc1667 | 6 | 0.663 | 0.686 | -0.024 | 0.592 |
| PHercParis4 | 8 | 0.782 | 0.663 | +0.119 | 0.678 |

What it shows (Interpretation):

- `face-mix` stayed ahead of the selected alpha compositing on the six-scroll mean, and alpha again scored higher on PHerc0139 and PHerc1667, as on 17 October.
- Most of the gain is again PHercParis4. Without it the five-scroll mean difference is +0.024; weighted by segment, the 14 segments outside PHercParis4 average -0.003, and 7 of them favor `face-mix`. These two numbers were computed after the test and are descriptive; the frozen rules do not name them.
- On PHerc0139 the reversed-depth map scored higher than the forward map (0.655 against 0.634). Two sparsely labeled windows of one segment carry that (about 3,100 and 900 labeled ink pixels, against a median of about 256,000); without them the forward map is ahead on all six scrolls, but that check is post hoc and not part of the verdict. Counting PHerc0814 on 17 October, the reversed control has beaten the forward map on two of the seven scrolls tested.
- Scores are lower than on 17 October (`face-mix` 0.693 against 0.736, alpha 0.652 against 0.704): six scrolls instead of seven, and later picks of the greedy window choice.

The same test tried a label-free rule for choosing the inked face per segment, as a possible 0.1.1 change. It picks the opposite face when that face's map has a standard deviation more than 1.15 times the default face's. It flipped one segment, PHerc0841 w00, onto the worse face: -0.018 against `face-mix` (-0.035 to 0.000), a FAIL under the frozen rules. A secondary rule that picks the face with the larger skewness per window was behind (-0.056, -0.089 to -0.021). The released recipe and its default face are unchanged; there is no 0.1.1.

There is still no comparison with a trained ink model and no test on wholly unseen scrolls. The frozen files (the preregistration, the face-rule code with its 1.15 ratio, and the window list) are private. Their SHA-256 digests are `c4fee1d497ae694410f0e2e4625390b53b4fdc1a5a5d39e5ca263c4ba0af3d5d`, `8f062b0f541b290915dd70fc678eb5a773c0288298454354271ba3884d59bf0a` and `703567225d67a07bcb456cca9b69f5f7dd19f8ec4faa1acb192236b6194e2531`. They were published here after the test ran, so they let a later release of those files be checked byte for byte; they do not show when the files were frozen.

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
- 2026-10-21: Fresh-window check of the 0.1.0 recipe (`4953f178`) on 44 windows of six scrolls: `face-mix` still ahead of alpha compositing on the mean (+0.040), mostly from PHercParis4; the label-free face rule tried for 0.1.1 failed, so the recipe is unchanged.

## Related

- [Package README](https://github.com/ChaseHendrick/Scrolls/blob/4953f17851aa9b2ffd3c26c86e85ecdabd659ca6/submissions/progress-2026-10-inkfilter/README.md): install, options, algorithm, limitations and attribution.
- [Confirmation evidence](https://github.com/ChaseHendrick/Scrolls/blob/4953f17851aa9b2ffd3c26c86e85ecdabd659ca6/submissions/progress-2026-10-inkfilter/evidence/README.md): frozen definitions, public window list, saved scores and negative results.
- [auc](auc.md): score maps against published labels with a reverse-depth control.
- [autopipeline](autopipeline.md): the pipeline that runs trained ink detection and scores its controls.
