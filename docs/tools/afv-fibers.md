# afv-fibers: papyrus fiber curves for six whole scans, made with Qual's AFV V2 model, and a catalog of every public fiber set

Papyrus fiber curves for six whole Herculaneum scans, made with Qual's AFV V2 model and spline generator, as public `.afv` datasets that open in VC3D, and a Space to see any box over the CT, download just that box, and find every other public fiber set.

| Field | Value |
| --- | --- |
| Id | `afv-fibers` |
| Status | Current |
| Kind | data, app |
| Area | Data and downloads |
| Run | [huggingface.co/spaces/SharpMeow/afv-fibers](https://huggingface.co/spaces/SharpMeow/afv-fibers) (the page: Six scans, Explore a box, Catalog, How-to guides, Agents and API), `Client("SharpMeow/afv-fibers").predict(..., api_name="/fibers_box")` or the MCP server `https://sharpmeow-afv-fibers.hf.space/gradio_api/mcp/` (a box), `hf download SharpMeow/SCAN-afv-fibers --repo-type dataset` (a whole scan), `python3 load_example.py FILE [X Y Z [HALF]]` in a downloaded dataset |
| Code | `spaces/afv-fibers/app.py` (the page, API and MCP tools), `spaces/afv-fibers/fibers.py` (the box, tiles, reading and writing `.afv`, the CT plane and pictures), `spaces/afv-fibers/guide/index.html` (the Six scans guide), `spaces/afv-fibers/catalog.json` (the catalog). The data lives on Hugging Face: six datasets SharpMeow/SCAN-afv-fibers, each with its own load_example.py, stats.json and villa-check.jsonl |
| Tests | `tests/test_afv_fibers_space.py` (the box and its level scaling, which tiles a box needs, fibers shared by tiles read once, a box written as a valid `.afv`, every catalog entry linked); the data was checked with villa's own AFV reader before upload (villa-check.jsonl in each dataset) |
| Needs | A browser for the page. `gradio_client` to call it from Python, any MCP client for agents. `huggingface_hub[cli]` for downloads; Python's `sqlite3` and NumPy to read a file; villa's `vc_object_store/scripts/import_afv.py` (villa `main`, October 2026) and VC3D to open it there |
| Runs on | The Space: a free CPU Space; a box reads only the tiles it touches. Downloads: any machine. Making the fibers: Hugging Face GPU and CPU Jobs (Cost and time) |
| Network | `huggingface.co` and `sharpmeow-afv-fibers.hf.space` (datasets and Space); the Space reads CT slices from `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` |
| Writes | Downloads write where you point `--local-dir`; a box comes back as one `.afv` file (gradio_client saves it in its temp folder); the Space caches tiles it read in `AFV_CACHE` |
| Go-ahead | Not needed to use. Publishing the datasets and Space with a catalog was Chase's yes (27 Oct 2026); later changes to their cards or files follow rule 8 |
| Released | Public on Hugging Face since 2026-10-27 (datasets and Space); README "Released tools" entry `afv-fibers` |
| License | Fibers: CC BY-NC 4.0, the same as the scans they derive from. Model, spline generator and `.afv` format: Qual, Apache 2.0. Space code: Apache 2.0 |
| Checked | 2026-10-27 against commit `a5edca7` |

## What it does

Papyrus is made of plant fibers laid in two crossing layers: horizontal fibers run along each sheet as it wraps around the scroll, vertical fibers cross them. Following fibers is one way to follow a sheet through the scroll. Qual's [AFV V2](https://huggingface.co/Qualzz20/afv_fiber_9um_v2) model (an nnU-Net) finds fibers in the CT at about 9 um voxels, and his [AVF_SPLINE_GENERATOR](https://github.com/Qualzz/AVF_SPLINE_GENERATOR) traces them into curves stored as `.afv`, a read-only SQLite format that villa's VC3D imports. Qual published sets for several scans; these datasets add six he had not done: PHerc0009B, PHerc0139, PHerc0332 (Scroll 3), PHerc0814, PHerc0841 and PHerc1667 (Scroll 4).

Each dataset holds every traced fiber of the whole scan (`SCAN_afv_v2.afv`), the fibers 1 mm and longer (`SCAN_afv_v2_1mm.afv`), and the same fibers cut into one small file per 1024-voxel cell of the model's grid (`tiles/`), so a box can be read without the whole file. Every file is in level-0 voxels of the scan, the coordinates villa's importer takes.

The Space shows any box over the CT: pick a scan and a point, and it draws the fibers near that CT plane (horizontal cyan, vertical orange), shows every fiber of the box in 3D, and hands back that box as its own `.afv`. Its Catalog tab links every public fiber set we know of, Qual's own and the official ones included, with credit; it links them and rehosts nothing.

The fibers are model output nobody has checked fiber by fiber. They are geometry, a map of papyrus structure, not a reading of any text.

## When to use it

- To open fibers for one of the six scans in VC3D, or read them in Python, without running the model.
- To look at what the fibers do in one region before downloading a whole scan.
- To find which fiber sets exist for a scan, and who made them (Catalog).

Do not use it:

- For a scan not in the six: check the Catalog for Qual's or the official sets, or run Qual's model and generator yourself.
- As ground truth: the fibers are the model's output.

## Quick start

```bash
pip install -U "huggingface_hub[cli]" numpy
hf download SharpMeow/pherc0139-afv-fibers PHerc0139_afv_v2_1mm.afv load_example.py --repo-type dataset --local-dir pherc0139
python3 pherc0139/load_example.py pherc0139/PHerc0139_afv_v2_1mm.afv
```

It prints the file's fiber count and voxel size, then how many vertical (V) and horizontal (H) fibers touch a 256-voxel box at the middle of the scan; pass `X Y Z [HALF]` in level-0 voxels for another box. It worked when the fiber count matches the dataset card.

A box from Python, no download:

```python
from gradio_client import Client
c = Client("SharpMeow/afv-fibers")
pt = c.predict(api_name="/example_points")[0]
print(c.predict(pt["scan"], pt["z"], pt["y"], pt["x"], 64, api_name="/fibers_box")["counts"])
```

## Checks and controls

Three checks, run before release:

- **Reproduction.** On a 640-voxel test cube inside a published V2 sample of Qual's (same checkpoint step as the Hub weights), this pipeline's fibers match his to 98% within one voxel, recall and precision, with fiber lengths within 1%. The control is the check itself: a different model, setting or tracing would show as lost or extra fibers.
- **Stitching.** Each scan was traced in 1024-voxel regions with a 128-voxel halo, then joined across region faces. Against one unsplit run of the same cube, the joined fibers agree to 99.75 to 99.99% within one voxel.
- **villa's reader.** villa's own `import_afv.py` reader opened every published file and read every fiber (`villa-check.jsonl` in each dataset). It refuses files that are not in native level-0 coordinates, which is why PHerc0332 and PHerc1667, run at level 2, are published rebased to level 0 (every point times 4, exact in float64).

Settings tested for faster future runs, on a PHerc0125 cube against the stride-64 run: a compiled model differed on 0.2% of fibers (1 - F1); larger windows or strides differed on 4.1 to 7.6%, so they were not used.

Claim label: Model output (the fibers); Measurement (the agreement numbers above).

## Commands and options

### Download

`hf download SharpMeow/SCAN-afv-fibers --repo-type dataset --local-dir DIR [--include PATTERN]`, where SCAN is the scan id in lower case. `--include "tiles/*"` and the like fetch only part of it.

### Open in VC3D

```bash
PYTHONPATH=build/python python3 vc_object_store/scripts/import_afv.py SCAN_afv_v2_1mm.afv OUT.vcobj --volume-id VOLUME_ID
```

VOLUME_ID is the 14-digit open-data volume id on the dataset card (for PHerc0139, `20250728140407`). Then attach OUT.vcobj from VC3D's File → Object Store menu with that volume open; the volume's catalog id must match (the script's notes say how for a local cache).

### The page, API and MCP

| Call | Arguments | Returns |
| --- | --- | --- |
| `/list_scans` | none | the six scans: dataset, CT volume and id, the level the model ran on, voxel size, file URLs |
| `/example_points` | none | points worth a first look on each scan |
| `/fibers_box` | `scan, z, y, x, half=128` | counts by family, the tiles read, each fiber's id, family, points and length in mm |
| `/look` | `scan, z, y, x, half=128, axis="z"` | the CT plane with fibers drawn over (PNG), a 3D figure, the box as `.afv`, and its counts |

z, y, x are level-0 voxels; `half` is half the box edge in voxels of the grid the model ran on, 16 to 256; `axis` is `z` (an axial slice) or `y` (a vertical section). The same calls are MCP tools at `https://sharpmeow-afv-fibers.hf.space/gradio_api/mcp/`.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `SPACE_HOST` | unset | Set by Hugging Face on a Space; the Agents and API tab uses it for its URLs, else `http://localhost:7860` |
| `AFV_CACHE` | `afv-fibers` in the temp folder | Where the Space keeps tiles it downloaded |
| `AFV_CACHE_GB` | `20` | The cache's size limit; the oldest tiles go first |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `fibers.box_l0(scan, z, y, x, half)` | `[z0, z1, y0, y1, x0, x1]` in level-0 voxels | `FiberError` for an unknown scan | `half` clamped to 16 to 256 and scaled by 2^level |
| `fibers.tiles_for(scan, box)` | the tile entries of `tiles/index.json` the box touches | `FiberError` when the index cannot be read | |
| `fibers.fibers_in_box(scan, box)` | `({id: (family, points xyz)}, tile ids)` | `FiberError` | Whole fibers, each read once though several tiles hold it |
| `fibers.write_box_afv(scan, box, dest)` | the number of fibers written | `FiberError` | A valid `.afv` that villa's reader opens |
| `fibers.render_slice(scan, axis, at, box, fibers)` | a PIL image | `FiberError` when the CT cannot be read | |
| `fibers.plot3d(scan, box, fibers)` | a plotly figure | never | |

## Inputs

Nothing: the fibers are ready made, from each scan's masked CT volume in the open data, named on each card. The model and tracing ran on about 9 um voxels: level 0 of the 8.64 to 9.366 um scans, level 2 of the 2.399 um scans of PHerc0332 and PHerc1667.

## Outputs

| File | Meaning |
| --- | --- |
| `SCAN_afv_v2.afv` | every traced fiber of the scan |
| `SCAN_afv_v2_1mm.afv` | the fibers 1 mm and longer |
| `tiles/*.afv`, `tiles/index.json` | the same fibers, one file per 1024-voxel cell of the model's grid, each holding every fiber that touches the cell whole; the index gives each cell's box in level-0 voxels and its fiber count |
| `previews/` | the card's pictures and GIFs, and `index.json` with the views they show |
| `stats.json` | counts, lengths by family and percentiles, file sizes |
| `villa-check.jsonl` | villa's reader run over every file, one JSON line each |
| `load_example.py` | reads the fibers in a box with `sqlite3` and NumPy |

Inside an `.afv`: table `fibers` (id, family `H` or `V`, point count, length in voxels, bounds), `blocks` (XYZ float64 points, at most 257 per block, consecutive blocks sharing one point) and the R-tree `block_bounds`; `metadata` holds the frame (level 0, scale 1), voxel size and provenance.

| Exit code | Meaning |
| --- | --- |
| `0` | `load_example.py` read the file |
| `1` | It could not read the file: download it again |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| villa's importer refuses a file: frame not native level 0 | A file from elsewhere made at a coarser level | Use these datasets' files, which are all level 0 |
| A box returns no fibers | The point is outside the papyrus, or not in level-0 voxels | Use `/example_points`, and level-0 coordinates |
| "unknown scan" | Only the six scans are served | Check the Catalog for other sets |
| The first box on a scan is slow | The Space downloads the tiles it needs, then caches them | Wait; the next boxes nearby are fast |

## How it works

1. **Fiber maps.** Qual's AFV V2 checkpoint ran over every 1024-voxel block of each scan that holds papyrus, with his recipe: 128-voxel windows at stride 64 on one global lattice, Gaussian blending, bf16, per-window normalization, no mirroring. Hugging Face GPU Jobs on RTX PRO 6000 cards, 1,725 blocks in all.
2. **Curves.** AVF_SPLINE_GENERATOR at commit `3c8b7362` traced each 1024-voxel region with a 128-voxel halo and seeds only inside the region, on Hugging Face CPU Jobs.
3. **Stitching.** Each region's curves were cut at its own faces and joined across faces where ends meet within 1.5 voxels, then the CT exterior cleaning Qual uses dropped curves touching the air outside the scroll. A scan is published only when no region is missing.
4. **Publishing.** The whole-scan file, the 1 mm set, tiles, previews and stats were made in the same Job; the files of level-2 scans were rebased to level 0; villa's reader checked every file before upload.

## Cost and time

Free to use: downloads and the Space cost nothing. Making the fibers ran on Hugging Face RTX PRO 6000 GPU Jobs (fiber maps) and CPU Jobs (tracing) on 27 October 2026; what it cost stays in private records. Measured speed of the model on a 1024 block, 27 Oct 2026:

| GPU | 128-voxel windows per second |
| --- | --- |
| RTX PRO 6000, compiled | 87 |
| RTX PRO 6000, as run | 59 |
| H200, compiled | 137 |
| A100, compiled | 68 |

## For agents

- **Command:** `Client("SharpMeow/afv-fibers").predict(SCAN, Z, Y, X, HALF, api_name="/fibers_box")`, or the MCP tool `fibers_box`; for a whole scan, `hf download SharpMeow/SCAN-afv-fibers --repo-type dataset --local-dir DIR`.
- **Parse:** `counts` (`V`, `H`), `tiles`, and `fibers` (id, family, points, length_mm); a file is SQLite: read `fibers` and `blocks`.
- **Rerun:** Safe; nothing is written but downloads and the temp `.afv`.
- **Success:** counts above zero inside the papyrus, and `villa-check.jsonl` lines all `"ok": true`.
- **Not a pass:** a file that opens is not a correct fiber map; it is model output.
- **Go-ahead:** Nothing to use it. Changes to the datasets or Space follow rule 8.
- **Never:** call the fibers a reading, or rehost them without the CC BY-NC 4.0 terms and Qual's credit.

## Tests

`python -m unittest tests.test_afv_fibers_space -v`: the box and its scaling by level, which tiles a box needs, a fiber held by two tiles read once with its blocks joined, a box written as an `.afv` with a valid R-tree, and the catalog and README agreeing with the scans. They use two synthetic tiles and no network; the live data is checked by `villa-check.jsonl`.

## History

- 2026-10-28: phone fixes ([PR #254](https://github.com/ChaseHendrick/Scrolls/pull/254)), found by `python -m kit spaceconnect scroll --width 390` and the live checks after the 27 October deploy: the Catalog table scrolls sideways in its own box instead of losing its Format and Get it columns at the right, the guide's scan cards fit the guide's frame (they were 318 px in 270 px), and long names and links wrap. Deployed as Space commit `bbfa9088`.
- 2026-10-27: one page scroll bar and American English ([PR #253](https://github.com/ChaseHendrick/Scrolls/pull/253)): a fading hero with the key numbers and buttons above the fold, the guide's frame fitted to its content so only the page scrolls, the public API `/fibers_box` with output key `fibers` (was `/fibres_box`, `fibres`), and a speed chart in place of the speed and cost chart.
- 2026-10-27: six datasets and the Space 1.0.0 public, with the catalog and Connect your tool panel ([#248](https://github.com/ChaseHendrick/Scrolls/pull/248)).

## Related

- [fibercheck](fibercheck.md): checks fiber agreement against other fiber sets.
- [lasagna-fields](lasagna-fields.md): villa's lasagna field for ten whole scans, published the same way.
