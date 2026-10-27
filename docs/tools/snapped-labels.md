# snapped-labels: published surface labels moved onto the papyrus, as a dataset and a CT viewer

A Hugging Face dataset of the published surface labels of PHerc0139, PHerc0814, PHerc0841 and PHerc0172 with every vertex moved along its normal onto the recto face in the CT, and a static Space that draws them over live open-data CT.

| Field | Value |
| --- | --- |
| Id | `snapped-labels` |
| Status | Current |
| Kind | data,app |
| Area | Surfaces and tracing |
| Run | [huggingface.co/spaces/SharpMeow/snapped-labels](https://huggingface.co/spaces/SharpMeow/snapped-labels) (viewer); `hf download SharpMeow/vesuvius-snapped-labels --repo-type dataset`; the dataset's `load_example.py`; in the page, `window.snappedLabels` |
| Code | `spaces/snapped-labels/index.html`, `spaces/snapped-labels/app.js`, `spaces/snapped-labels/style.css`, `spaces/snapped-labels/connect.json` |
| Tests | None for the page here: `python -m kit spaceconnect check` (run by the tests) checks its Connect panel; the page was checked in headless Chromium on the release output before upload (see Checks and controls) |
| Needs | A browser for the Space. For the data: Python 3.9+, `huggingface_hub`, `numpy`, `tifffile` and `imagecodecs` |
| Runs on | Any browser; a segment's cross sections are at most about 8 MB, and each CT view reads up to 16 uncompressed 128 voxel chunks |
| Network | `huggingface.co` (the dataset), `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (CT and the published meshes, read live) |
| Writes | Nothing; `hf download` writes the folder you name |
| Go-ahead | Not needed to use. Releasing the dataset and the Space was Chase's yes (27 Oct 2026); the Space redeploys from merged `main` under the standing yes (rule 8) |
| Released | Public on Hugging Face since 2026-10-27 (dataset and Space); 1.0.1 the same day (`abstain.tif` code 2 for filled vertices); README "Released tools" entry `snapped-labels` |
| License | Data CC BY-NC 4.0, like the open data it comes from; page code Apache 2.0 |
| Checked | 2026-10-27 against commit `ff82a63` |

## What it does

A surface label is a tifxyz mesh that follows one wrap of papyrus in a scan. Published labels sit near the sheet but rarely on it: on fresh test sites, only about a quarter of their vertices were within one voxel of the recto face. Models trained on such labels learn that offset.

The dataset holds every published label of four scrolls after a snap: each vertex moved along its normal onto the face of the bright papyrus band, on the side toward the scroll's center line. On PHerc0139, PHerc0814 and PHerc0841 the face is found in a 2.4 µm scan of the same scroll registered vertex by vertex to the label's scan (finesnap); on PHerc0172 in the label's own 7.9 µm scan (labelsnap). Where a vertex's own face is unclear, nothing is measured at that vertex: it takes a Gaussian-weighted average of its measured neighbors' offsets when one lies within two grid cells (filled, `abstain.tif` 2), and otherwise keeps its published position (`abstain.tif` 1). Of 32.9 million released vertices, 66.0 % are snapped, 33.0 % filled (median move 2.7 voxels) and 1.0 % left in place. The snapped share counts measured vertices only; keep `abstain.tif` 0 to use only vertices whose own face was found. Version 1.0.1 (27 Oct 2026) added code 2; in 1.0.0 filled vertices were marked 1. Each mesh keeps the grid and voxel frame of its source, so it lines up with it vertex for vertex.

The Space draws a segment's published and snapped lines on the CT plane you pick, and lists every segment.

The meshes are geometry. They say nothing about ink or text.

## When to use it

- Training or scoring surface and sheet models: snapped labels put the target on the face instead of beside it.
- Rendering a segment closer to the papyrus, in VC3D, villa or any tifxyz tool.
- Seeing, before you use a label, how far it was off.

Do not use it:

- To fix a label that follows the wrong wrap: a snap moves along the normal only. Check the wrap first.
- Where two sheets touch without a visible gap: the face found there can belong to the neighbor.
- For five PHerc0139 segments and PHerc0841 auto_grown_20260220174252405, which are held out for evaluation: they are not included.

## Quick start

```bash
pip install -U huggingface_hub numpy tifffile imagecodecs
hf download SharpMeow/vesuvius-snapped-labels load_example.py --repo-type dataset --local-dir snapped-labels
python snapped-labels/load_example.py
```

It reads PHerc0841 w00 from the dataset and its published mesh from the open data, and prints the grid, the counts and the median move. It worked when the last line is `matches release.json: True`.

## Checks and controls

- Accuracy (frozen tests on fresh sites, scored against the recto face in an independent 1.129 µm scan): PHerc0139, 60 sites, within 1 voxel 23.7% published, 79.4% labelsnap, 91.2% finesnap; PHerc0814, 60 sites, 24.2% published, 71.0% labelsnap. A 3D surface model trained on snapped PHerc0139 labels placed the surface 0.61 voxels closer on PHerc0814 than the same model trained on the published labels (95% interval 0.39 to 0.84; all 9 seed pairings). These tests could fail, and the published labels are their control.
- Release checks: every segment was snapped in overlapping row bands and stitched; on a test crop a banded finesnap run equals a whole run exactly. `release.json` carries the sha256 of every file and of the source mesh; the stitch refused any held-back vertex that came back valid.
- The page: opened in headless Chromium on the release folder before upload; published and snapped lines were drawn over the CT of PHerc0139, PHerc0841 and PHerc0172.

Claim label: Model output (the snapped meshes come from a band finder on CT; they are geometry, not a reading). The accuracy figures are the frozen tests' results on fresh sites.

## Commands and options

### The Space

[huggingface.co/spaces/SharpMeow/snapped-labels](https://huggingface.co/spaces/SharpMeow/snapped-labels): Viewer (scroll, segment, z plane, a 96, 192 or 384 voxel window, layers), All segments, How it works, Connect your tool. Keys: left and right step along the label, up and down step z. URL parameters: `seg=SEGMENT`, `z=Z`, `data=URL` (another copy of the dataset). The page has one scroll bar: the segment list grows with the page instead of scrolling on its own, picking a segment far down the list or the table brings the image back into view, and on a phone the list follows the viewer.

### `load_example.py` (in the dataset)

```
usage: load_example.py [-h] [--root ROOT] [--segment SEGMENT]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--root` | the Hub | A local copy of the dataset |
| `--segment` | `PHerc0841/20260220213127-w00` | A segment path from `index.json` |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `window.snappedLabels.segments()` (page) | the index rows | | In the browser console or a headless browser |
| `window.snappedLabels.open(SEGMENT, Z)` (page) | a promise | `Error` for an unknown segment | Opens a segment at the plane nearest Z |
| `window.snappedLabels.view()` (page) | the open view: planes, step, voxel size, `center` ([x, y] in voxels; spelled the British way before 27 Oct 2026) | | `null` before a segment opens |

## Inputs

None to use it. The dataset was made from the published meshes and scans of the Vesuvius Challenge open data; each `release.json` names its source mesh with sha256 and the scans used.

## Outputs

| File | Type | Meaning |
| --- | --- | --- |
| `SCROLL/SEGMENT/snapped.tifxyz/{x,y,z}.tif` | float32 grids | Moved vertices, level-0 voxels of the label scan; `-1` none or held back |
| `abstain.tif` | float32 grid of codes | 0 snapped (face measured at the vertex), 1 not measured and left at its published position, 2 not measured and moved by its measured neighbors' filled offset (since 1.0.1), 255 no vertex or held back |
| `confidence.tif` | float32 grid | 0 to 1 |
| `reason.tif` | float32 grid of codes | Why no face was measured at a vertex |
| `source.tif` | float32 grid of codes | finesnap only: 1 placed in the 2.4 µm scan, 2 in the label scan |
| `release_mask.tif` | float32 grid of codes | 0 released, 1 held back for evaluation, 255 not in the source |
| `release.json` | JSON | Source and scan URLs, sha256 of source and outputs, `release` (`1.0.1`), summary (`vertices_released`, `snapped`, `filled`, `left_in_place`, `abstained`, `move_voxels`, `placed_by`) |
| `index.json` | JSON | One row per segment with its summary |
| `viewer/SCROLL/SEGMENT.{bin,json}` | float32 rows, JSON | The viewer's line pieces per z plane: published ax ay bx by, snapped ax ay bx by |
| `SHA256SUMS` | text | Every file |

| Exit code | Meaning |
| --- | --- |
| `0` | `load_example.py` read the segment and printed its summary |
| `1` | A download or read failed (Python traceback) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| "CT read failed" in the viewer | The open-data bucket did not answer | Reload; the dataset itself is unaffected |
| No lines on a plane | The segment does not cross it, or that part is held back | Step z, or press the arrows |
| `tifffile` cannot read a published mesh | Some source meshes are LZW compressed | `pip install imagecodecs` |

## How it works

The method, its constants and its tests are recorded with the snapping code, which is not part of this release. The release used finesnap's and labelsnap's defaults as frozen for their tests, with evaluation regions held back before any read. The viewer cuts each mesh cell of four released vertices with the z plane (marching squares on the corner z), applying the same edge fractions to the published and snapped meshes so their lines correspond point for point.

## Cost and time

The snap ran on Hugging Face CPU Jobs on 27 Oct 2026, under 9 USD in caps; stitching took minutes on a CPU. Using the dataset costs nothing.

## For agents

- **Command:** `python load_example.py --segment SCROLL/SEGMENT`; or read `index.json` and each `release.json`.
- **Parse:** `index.json` rows: `vertices_released`, `snapped`, `move_voxels.median`, `vertices_held_back`; the grids above.
- **Rerun:** Safe; reads only.
- **Success:** `matches release.json: True`; `sha256sum -c SHA256SUMS` passes.
- **Not a pass:** A snapped vertex is not proof the label follows the right wrap.
- **Go-ahead:** Nothing to read it. Changing the dataset or making a new Space needs Chase's yes.
- **Never:** Call the meshes a reading, or train on held-back regions (`release_mask.tif` = 1).

## Tests

`python -m kit spaceconnect check` covers the Connect panel. The page has no unit tests here.

## History

- 2026-10-27: dataset and Space released, page added (`bd34a59`).

## Related

- [`spaces/snapped-labels/`](../../spaces/snapped-labels/): the page source.
- [segment-lens](segment-lens.md): every published mesh's geometry.
- [umbilici](umbilici.md): the center lines the snap faces toward.
