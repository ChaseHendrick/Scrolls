# scroll-lens: look inside a scan cube with the organizers' 3D DINO, ink and surface models

A Hugging Face ZeroGPU Space that reads a 128³ or 256³ cube of a public 2.2 to 2.4 µm scroll scan and shows what three Vesuvius Challenge 3D models see in it: click search, slice views and a 3D view drawn in the browser, and agent tools (API and MCP).

| Field | Value |
| --- | --- |
| Id | `scroll-lens` |
| Status | Current |
| Kind | app, agent tool, script |
| Area | Viewers and apps |
| Run | [huggingface.co/spaces/SharpMeow/scroll-lens](https://huggingface.co/spaces/SharpMeow/scroll-lens) (the page; MCP at `https://sharpmeow-scroll-lens.hf.space/gradio_api/mcp/`), `python3 spaces/scroll-lens/app.py` (the page locally), `python3 spaces/scroll-lens/lens.py look VOLUME Z Y X` (one cube, no page), `python3 spaces/scroll-lens/tools/deploy.py OWNER/NAME`, `python3 spaces/scroll-lens/tools/build_gallery.py OWNER/NAME` |
| Code | `spaces/scroll-lens/app.py` (the page and the agent tools), `spaces/scroll-lens/viewer.js` (the slice viewer and 3D view, run in the browser), `spaces/scroll-lens/lens.py` (everything else), `spaces/scroll-lens/tools/deploy.py`, `spaces/scroll-lens/tools/build_gallery.py`, `spaces/scroll-lens/requirements.txt`, `spaces/scroll-lens/README.md` (the Space card) |
| Tests | `tests/test_scroll_lens.py`, 50 tests, numpy only (2 more need gradio or node and skip without them) |
| Needs | Python 3.12 (3.10 or newer works), the pins in `spaces/scroll-lens/requirements.txt` (torch 2.13.0, timm 1.0.30, numpy 2.5.2, zarr 3.4.1, mcp 1.30.0, huggingface_hub 1.33.0; gradio 6.28.0 for the page, from the card); downloads dinovol at commit `a72fda2` and villa's `vesuvius/src` at `b29f310` itself. In the browser: `DecompressionStream` (Chrome 80, Safari 16.4, Firefox 113 or newer) for the viewer, WebGL and three.js 0.160.0 (from cdn.jsdelivr.net, loaded on first use) for the 3D view. `tools/deploy.py` needs huggingface_hub; `tools/build_gallery.py` needs numpy, gradio_client and huggingface_hub |
| Runs on | ZeroGPU (an NVIDIA RTX PRO 6000 Blackwell MIG 2g.48gb slice): a 256³ cube with all three models in 3.2 to 8.0 s of model time (median 3.5 s over 61 gallery cubes), 7 to 12 s per call, about 4.5 s of quota; a 128³ cube in about 0.3 s of model time and 0.5 s of quota (38 cubes; 2026-10-17). The Space's CPU fallback: a 128³ cube in about 9 s (live, 2026-10-17). A gallery cube opens in 1.2 s the first time (0.1 s for 128³) and then from memory (M1 Pro, 2026-10-17) |
| Network | The page's server: `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (scan chunks and listings), `huggingface.co` (weights at pinned revisions; `tools/` also the Space itself), `github.com` or `codeload.github.com` (model code at pinned commits). The visitor's browser: the same bucket (scan chunks; it allows any origin), the Space, and `cdn.jsdelivr.net` (three.js, for the 3D view) |
| Writes | Model weights and code under `$LENS_CACHE` (default `TMPDIR/scroll-lens`, about 3.7 GB); the viewer's layer files under `TMPDIR/scroll-lens-view` (one per cube shown, a few MB each, cleared at start-up); saved files, `look` and `download_cube` outputs and `search_cube` concepts under `TMPDIR/scroll-lens-out` (pruned after 15 minutes by the page's saves; Gradio serves its own copies); `lens.py look` writes `VOLUME-Z-Y-X-SIZE.npz` and `.json` to `--out`; `tools/build_gallery.py` writes `--out` (default `spaces/scroll-lens/gallery/`, gitignored) |
| Go-ahead | Needed for `tools/deploy.py` (creates or pushes the Space) and `tools/build_gallery.py` (spends Chase's ZeroGPU minutes and uploads `gallery/`), and for calling the live Space's model runs with Chase's token; both scripts ask y/N. Not needed to use the page or the gallery tools, or to run locally |
| Released | Space [`SharpMeow/scroll-lens`](https://huggingface.co/spaces/SharpMeow/scroll-lens) since 2026-10-17 (v1.0.0; v1.1.0 adds the agent tools and MCP, the browser viewer and the 3D view); 99 gallery cubes since 2026-10-17; code on public `main` since 2026-10-16 ([PR #110](https://github.com/ChaseHendrick/Scrolls/pull/110)) |
| License | Apache 2.0 for the Space's code ([`spaces/scroll-lens/LICENSE`](../../spaces/scroll-lens/LICENSE), [`NOTICE`](../../spaces/scroll-lens/NOTICE)); the models (MIT) and the scans and gallery cubes (CC BY-NC 4.0) keep their own licenses |
| Checked | 2026-10-17 against commit `e14e165` |

## What it does

The Vesuvius Challenge released three 3D models with its PHerc. Paris 4 work (Angelotti et al. 2026, [arXiv:2606.29085](https://arxiv.org/abs/2606.29085)): `scrollprize/dinovol_v2_ps8_with_paris4_352500`, a self-supervised 3D ViT that gives each 8 × 8 × 8 voxel patch 864 numbers (an embedding); `scrollprize/ink_3d_dino_guided`, which marks ink voxels directly in the scan; and `scrollprize/surface_recto_3dunet`, which marks the written (recto) side of each sheet. Scroll Lens reads one cube of a scan from the open-data bucket, runs any of the three on it, and shows the results as layers on three slice views, or in one 3D view of the cube.

Click search: a click in "More like this" mode takes the embedding of the clicked patch and lights up the cube's most similar patches; "Not this" subtracts a patch. The concept is the unit-length mean of the clicked embeddings, the same recipe the organizers used for their reference ink embedding (`avg_ref_embedding.npy`, 256 expert clicks), which the page also shows, in amber, never below their threshold (cosine 0.5). The concept follows the visitor to other cubes and scans and downloads as `concept.npy` (plus `concept_not.npy` for the Not this clicks).

The views are drawn in the visitor's browser by `viewer.js`: it reads the scan chunks itself from the bucket and one compressed file of model layers from the Space, so sliders, dragging the crosshair, the wheel, zoom, pan, layer toggles, opacity, Top %, brightness and contrast all answer at once. *3D view* turns the three views into one three.js scene (as in [Unroll](unroll.md)): the three slices as planes through the cube, moving as the sliders move, ink and surface as points, and the patches like the concept or the reference glowing; it rotates, zooms and pans with the mouse. Only clicks (search), saving and running the models go to the server.

For AI agents and scripts, seven tools are API endpoints and MCP tools (added in [PR #114](https://github.com/ChaseHendrick/Scrolls/pull/114)): list the scans and the gallery, pick a papyrus point, inspect a cube (three views as one image, with its numbers), search it by example points, a concept file or the organizers' reference, download its outputs, and `look` for batch scripts. A cube is a gallery id (no GPU) or a scan and a point (runs the models on the caller's ZeroGPU time). Every answer carries a link that opens the same cube on the page.

Everything shown is model output, not a reading. A cube is at most 0.6 mm across, smaller than one letter. Scroll Lens reads only twelve listed scans (below), none on the First Letters or Grand Prize eligible lists. On PHerc. Paris 4, whose title is an open prize, Scroll Lens itself picks only the eight points listed in the ink checkpoint's training config (`lens.PARIS4_TRAINING_POINTS`).

A Connect your tool accordion gives the scans' open-data URLs and snippets for Python, villa's `vesuvius` package, VC3D, neuroglancer, gradio_client, curl and MCP ([spaceconnect](spaceconnect.md), 24 Oct 2026).

## When to use it

- To see what the organizers' 3D models mark in a piece of a scan, flat or in 3D, without installing villa or dinovol.
- To try few-click labeling with 3D DINO embeddings, then carry the concept to another scan or a script.
- To get the models' outputs for a cube as arrays (`download_cube`, `look`, or `lens.py look`), or to let an agent explore cubes through MCP.

Do not use it:

- To read text or judge a candidate: use flattened surface renders and the ink tools; Scroll Lens is a 0.6 mm window.
- On a target or prize-eligible scroll: it refuses them, and such work belongs in Scrolls-private.
- To score an ink map against labels: use `python -m kit auc` ([auc](auc.md)).
- To view traced windings in 3D: use [Unroll](unroll.md).

## Quick start

```bash
pip install gradio_client
python3 - <<'EOF'
from gradio_client import Client
c = Client("SharpMeow/scroll-lens")
cubes = c.predict(api_name="/list_gallery")["cubes"]
image, hits, concept = c.predict(cubes[0]["id"], "", 0, 0, 0, 256, "", "", None, 3, api_name="/search_cube")
print(hits["concept"], hits["matches"][0], hits["agreement_with_ink_model"])
EOF
```

No token and no GPU are needed for a gallery cube. On 2026-10-17 (the local copy of the page, the same code and gallery) it printed, rounded:

```
the organizers' ink reference {'center_zyx': [37732, 8772, 22124], 'score': 0.7357} {'auc': 0.766, 'auc_control_shifted': 0.468, 'ink_patch_fraction': 0.094, 'auc_control_mean': 0.492, 'auc_control_p05': 0.413, 'auc_control_p95': 0.558}
```

It worked if `auc` is above `auc_control_p95`. To run the models on a cube of your own, without the Space: `cd spaces/scroll-lens && python3 lens.py look PHercParis4 37628 8793 22167 --size 128 --out OUT` (`OUT` is any folder; the first run downloads about 3.7 GB of weights and code). For the page locally: `python3 spaces/scroll-lens/app.py`, then open the printed address.

## Checks and controls

- Agreement with controls that must fail: `lens.agreement` gives the AUC with which a similarity map (the organizers' reference, or the visitor's concept) picks out the patches the 3D ink model marks as ink (mean probability over 0.5). The controls roll the same ink mask away from its place: `auc_control_shifted` by half the cube on every axis, and `auc_control_mean`, `auc_control_p05` and `auc_control_p95` over `CONTROL_SHIFTS` = 16 fixed rolls between a quarter and three quarters of the cube. Papyrus is layered, so a single roll can line the layers up again: over the 99 gallery cubes the half-cube control ranged from 0.26 to 0.72 and sat more than 0.1 from 0.5 in 28 (bug test, 2026-10-17). The AUC means something only above `auc_control_p95`. Paris 4 training point 1 (256³): AUC 0.77 against a control range of 0.41 to 0.56 (Model output, 2026-10-17). `test_agreement_control_range` and `test_agreement_has_a_control_that_fails` check that the controls can fail.
- Port check: on a 128³ Paris 4 block, `Engine._dino_grid` matched dinovol's napari inspector (`compute_patch_embedding_grid`) to a cosine of at least 0.99990 per patch.
- Compact cubes: the gallery keeps 128 of the 864 embedding directions. Search scores the projection without rescaling it, which estimates the full cosine; rescaling to unit length had inflated it (the kept share of an embedding is 0.98 at the median, at least 0.68). `test_reduced_search_matches_the_rebuilt_embeddings` checks the page's search and `lens.grid_of` agree.
- Pinned inputs: weights are refused unless their SHA-256 matches `lens.MODELS`; code is fetched at `lens.CODE` commits.
- The agreement is with another model, not with ground truth; a high AUC says the DINO concept and the ink model mark the same patches, nothing more.

Claim label: Model output, for every number and layer the tool shows.

## Commands and options

### `python3 spaces/scroll-lens/lens.py volumes`

```
usage: lens.py [-h] {volumes,look,files,stage} ...
```

Prints one line per allowed scan: id, scroll, voxel size and scan name. No options.

### `python3 spaces/scroll-lens/lens.py look`

```
usage: lens.py look [-h] [--size {128,256}] [--layers LAYERS] [--tta]
                    [--device DEVICE] [--out OUT]
                    volume zyx zyx zyx
```

| Option | Default | Meaning |
| --- | --- | --- |
| `volume` | required | A scan id from `lens.py volumes` (`lens.VOLUMES`; case does not matter) |
| `zyx` | required | Three integers: a point in level-0 voxels, z y x |
| `--size` | `128` | Cube side in voxels, one of `lens.SIZES` = (128, 256); 256 is the models' training patch, 128 fits a CPU |
| `--layers` | `dino,ink,surface` | Comma-separated models to run, from `lens.LAYERS`; no spaces |
| `--tta` | off | Average the eight mirrorings for ink and surface, 8 times their time |
| `--device` | none | `cpu` or `cuda`; none means `cuda` when present, else `cpu` |
| `--out` | `.` | Folder for `VOLUME-Z-Y-X-SIZE.npz` and `.json` (created if missing) |

### `python3 spaces/scroll-lens/lens.py files`

Prints each Space file (`lens.SPACE_FILES`: `README.md`, `app.py`, `lens.py`, `viewer.js`, `requirements.txt`, `LICENSE`, `NOTICE`) with its SHA-256. No options.

### `python3 spaces/scroll-lens/lens.py stage`

```
usage: lens.py stage [-h] dest
```

| Option | Default | Meaning |
| --- | --- | --- |
| `dest` | required | An empty or missing folder; the Space files are copied into it and its path is printed |

### `python3 spaces/scroll-lens/tools/deploy.py`

Runs on Chase's computer, logged in with `hf auth login`; it never logs in for you. It stages the Space files, lists them with SHA-256, says which differ from the live Space, asks y/N, then creates the Space if needed (Gradio, ZeroGPU hardware `zero-a10g`), uploads, and asks for that hardware if missing. It leaves the Space's `gallery/` alone. Safe to run twice: with nothing changed it uploads nothing. A free account may hold only two ZeroGPU Spaces: creating a third fails with HTTP 402 "Free users are limited to 2 ZeroGPU Spaces" (2026-10-17).

```
usage: deploy.py [-h] [--private] space
```

| Option | Default | Meaning |
| --- | --- | --- |
| `space` | required | The Space as `OWNER/NAME` |
| `--private` | off | Create the Space private; public otherwise. Only applies when the Space does not exist yet |

### `python3 spaces/scroll-lens/tools/build_gallery.py`

Runs on Chase's computer after the Space is live. It calls the Space's `look` endpoint with his token, so each cube's GPU time counts against his ZeroGPU quota. The plan, fixed by `--seed` and `--batch`: batch 1 is the eight Paris 4 training points and one random papyrus point per other listed scan, drawn in `lens.VOLUMES` order from one generator and interleaved so an early stop still covers several scrolls; batch K (2 or more) is one more point on each scan except Paris 4, seed `SEED + K - 1`, each scan from its own generator `default_rng([SEED + K - 1, the scan's position in lens.VOLUMES])` with 48 tries. A scan whose search finds no papyrus is skipped with a line saying so. It stops at the first quota refusal and keeps what it has; cubes already in `--out` are skipped next time. Then it lists the files and asks y/N before uploading `gallery/`.

```
usage: build_gallery.py [-h] [--batch BATCH] [--size {128,256}] [--seed SEED]
                        [--out OUT] [--dry-run] [--no-upload]
                        space
```

| Option | Default | Meaning |
| --- | --- | --- |
| `space` | required | `OWNER/NAME` of the live Scroll Lens Space |
| `--batch` | `1` | 1: the Paris 4 training points and one point per other scan; K > 1: one more point per scan except Paris 4 |
| `--size` | `256` | Cube side for every cube of this run, one of `lens.SIZES` |
| `--seed` | `2026` | Seed of batch 1; batch K uses `SEED + K - 1` |
| `--out` | `spaces/scroll-lens/gallery` | Folder for the cubes and `index.json` (created even with `--dry-run`) |
| `--dry-run` | off | Print the plan and stop. Still reads the bucket to pick random points; no token, no GPU |
| `--no-upload` | off | Build only; never ask to upload |

The live gallery (2026-10-17) is batches 1 to 4 and most of batch 5 at 256³, and the rest of batch 5 and batches 6 to 9 at 128³ (ZeroGPU would no longer start a 256³ call), 99 cubes and 736 MB, built on about 280 s of Chase's 300 s daily quota.

### `python3 spaces/scroll-lens/app.py`

Starts the page locally (queue of 256 waiting events, 8 at a time for most events, the models 2 at a time, one page run per visitor; MCP server on). Page settings, with their defaults:

| Option | Default | Meaning |
| --- | --- | --- |
| Gallery cube | the first in `gallery/index.json` | Opens on selection; Previous, Next and Random step through the list |
| Scan | `PHercParis4` | One of the twelve allowed scans |
| z, y, x | 37628, 8793, 22167 | The point, level-0 voxels (the first Paris 4 training point) |
| Cube side, voxels | 256 | 128 or 256; the CPU fallback runs the middle 128³ (`CPU_SIZE`) |
| Models to run | all three | 3D DINO, ink, surface |
| Average eight mirrorings | off | Same as `--tta` |
| Layers (viewer) | ink, your clicks, organizers' reference, crosshair on; surface, DINO colors off | Toggle at once in the browser |
| A click does (viewer) | Move only | Or More like this, or Not this |
| Opacity, Top % shown (viewer) | 0.7, 8 | 0 to 1; 1 to 40 |
| Brightness, Contrast (viewer) | 0, 0 | -100 to 100 around the automatic window (the 0.5th to 99.5th percentile of the papyrus) |
| 3D view (viewer) | off | Slices, layers as points, cube outline on; spin off |

Viewer mouse and keys: drag moves the crosshair; wheel or arrow keys step a slice (Shift: 8); Ctrl or Cmd with the wheel, a pinch, or `+` and `-` zoom; right-drag or Shift-drag pans; double-click or `0` resets the zoom; `C` centers on the cube's point; Ctrl or Cmd with `Z` (or *Undo click*) forgets the last click. In the 3D view: drag rotates, the wheel zooms, right-drag pans, a click on a slice moves the crosshair (or searches, with More like this or Not this chosen), *Reset camera* looks at the whole cube. Links: `?cube=ID`, `?v=SCAN&z=Z&y=Y&x=X&size=SIZE` (fills Your own point and opens that tab), and `&s=Z,Y,X` (the crosshair, cube voxels; *Copy link* writes it).

### Agent tools (API and MCP, since 1.1.0)

`app.py` launches with `mcp_server=True`, so each endpoint below is also an MCP tool at `https://sharpmeow-scroll-lens.hf.space/gradio_api/mcp/`. A cube is named by `cube_id` (a gallery id; no GPU) or by `scan`, `z`, `y`, `x` and `size` (runs all three models; the caller's ZeroGPU time, else the CPU fallback). The three most recent cubes stay in memory (`VIEW_CACHE_N = 3`), so a search after an inspect of the same cube runs no model. Every JSON answer has `open_in_browser`, a page link to the same cube.

| Endpoint | Inputs | Returns |
| --- | --- | --- |
| `list_scans` | none | JSON: `scans`, `paris4_training_points`, `sizes`, `layers`, `version` |
| `list_gallery` | none | JSON: `cubes` with `id`, `scan`, `title`, `note`, `point_zyx`, `size`, `open_in_browser` |
| `random_point` | scan, seed | JSON: `scan`, `z`, `y`, `x` |
| `inspect_cube` | cube_id, scan, z, y, x, size, overlays (`ink,surface,reference,dino`, any subset) | PNG of the three views through the point; JSON summary (receipt, agreement, `reference_fraction_at_tau`, `ink_voxel_fraction`, `surface_voxel_fraction`, `slices_zyx`) |
| `search_cube` | cube_id, scan, z, y, x, size, positive (`"z,y,x; ..."`), negative, concept (`.npy`), top_k (1 to 200) | PNG through the best match; JSON with `matches` (`center_zyx`, `score`) and `agreement_with_ink_model`; `concept.npy` |
| `download_cube` | cube_id, scan, z, y, x, size | The `.npz` and the JSON summary |
| `look` | vid, z, y, x, size (256), layers (`dino,ink,surface`), tta, compact, allow_cpu (all off) | The `.npz`, for batch scripts such as `tools/build_gallery.py` |

With no positive points and no concept file, `search_cube` uses the organizers' ink reference. `app.fix_mcp_multiple_outputs` patches Gradio 6.28's MCP server, which otherwise joins a queued tool's several outputs into one text, so the image reaches agents as an image. `look` reads `tta`, `compact` and `allow_cpu` strictly (the string "false" is false) and refuses before reading the bucket while the models load.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `LENS_CACHE` | `TMPDIR/scroll-lens` | Download folder for weights and code |
| `LENS_WEIGHTS` | none | Folder of local weights laid out `REPO_NAME/FILE`; still hash-checked |
| `LENS_DINOVOL` | none | Local dinovol checkout (repository root) instead of the pinned download |
| `LENS_VILLA_SRC` | none | Local villa `vesuvius/src` instead of the pinned download |
| `SPACE_HOST` | unset | Set by Hugging Face to the Space's host name; tool links (`open_in_browser`) start with it, else they are relative |
| `SPACES_ZERO_GPU` | unset | Set to `1` or `true` by Hugging Face on a ZeroGPU Space; with the `spaces` package present, `app.py` then runs models through `spaces.GPU` |

## Python API

Import with `spaces/scroll-lens` on `sys.path` (`import lens`, `import app`). The Space's agent tools are the remote API (above).

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `lens.volume_id(vid)`, `lens.volume(vid)` | The listed id; its entry of `lens.VOLUMES` | `LensError` for an unlisted scan (the message lists the ids) | Case does not matter |
| `lens.volume_url(vid, level=0)` | The level's zarr URL in the bucket | `LensError` for an unlisted scan | |
| `lens.as_int(value, name)` | int | `LensError` for None, NaN, infinity, booleans, text and fractions | Accepts integral floats and digit strings |
| `lens.cube_origin(vid, center_zyx, size)` | Tuple z, y, x: the cube corner, on the 128-voxel chunk grid where it can be, inside the scan | `LensError` for an unlisted scan, a bad size, a point outside the scan or not three whole numbers | The point always lies inside the cube; near the scan's far edge the cube ends at the edge, off the grid |
| `lens.read_cube(vid, origin, size, fetch=_get, workers=8)` | uint8 array (size, size, size) | `LensError` for a cube outside the scan, a bad chunk, a bucket refusal, or when the bucket cannot be read | Any origin inside the scan; missing chunks (HTTP 404) read as 0 |
| `lens.check_cube(cube)`, `lens.foreground(cube)` | Papyrus fraction | `check_cube`: `LensError` below `MIN_FOREGROUND` = 0.05 | |
| `lens.random_point(vid, rng, fetch=_get, tries=24, list_fetch=None)` | A z, y, x point on papyrus | `LensError` after its tries | Blind level-3 draws first, then draws among stored chunks from a bucket listing |
| `lens.parse_points(text, limit=64)`, `lens.voxel_in_cube(point_zyx, origin, size)`, `lens.top_matches(sim_tokens, origin, k=20)` | Points from `"z,y,x; ..."`; the cube voxel of a scan point; the best patches with centers and scores | `LensError` for a bad point, too many points, or a point outside the cube | Used by `search_cube` |
| `lens.Engine(cache=CACHE)` | The three models on the CPU | `RuntimeError` on a weight hash or code fetch failure | Loads once per process; `.describe()` gives models, code and `startup_s` |
| `lens.Engine().run(cube, layers=LAYERS, device="cpu", tta=False)` | Dict: `grid` float16 (Z/8, Y/8, X/8, 864), `ink` and `surface` uint8 (Z, Y, X), timings | `LensError` for an unknown layer | bf16 autocast on CUDA |
| `lens.check_size(size)`, `lens.check_layers(layers)`, `lens.gpu_seconds(size, layers, tta=False)` | The size; the layers; int seconds asked of ZeroGPU | `LensError` | ZeroGPU reserves 1.5 times `gpu_seconds` on the RTX PRO 6000 (`duration_factor`, spaces 0.51.3) |
| `lens.similarity(grid, positive, negative=None)`, `lens.concept(grid, tokens)`, `lens.unit(v)`, `lens.token_of(voxel, size)` | float32 per patch; unit mean; unit vectors; the patch holding a voxel | | Cosine to positive minus cosine to negative |
| `lens.auc(scores, labels)` | float or None | | Ties count half; None with an empty class or a NaN score |
| `lens.agreement(sim_tokens, ink_u8, threshold=0.5)` | Dict `auc`, `auc_control_shifted`, `auc_control_mean`, `auc_control_p05`, `auc_control_p95`, `ink_patch_fraction` | | Agreement with a model, not ground truth |
| `lens.load_concept(path)` | Unit-length 864-vector | `LensError` for a file over 4 MB, not a plain `.npy`, a bad shape, a header that does not match the size, non-finite or zero rows, or rows that cancel out | The header is read before the data |
| `lens.receipt(vid, origin, size, center, result, engine_info=None, extra=None)`, `lens.layers_in(result)` | The receipt dict; the layers a result holds | `LensError` for an unlisted scan | |
| `lens.save_npz(path, cube_meta, result, compact=False)`, `lens.load_npz(path)` | The path; (receipt dict, arrays dict) | `load_npz`: `LensError` on shapes that disagree with the receipt | `compact` keeps 128 embedding components and 16 levels; `load_npz` repairs pre-1.1.0 `layers` |
| `lens.grid_of(result)`, `lens.reduce_grid(grid, k=128)`, `lens.quantize(prob_u8, levels=16)`, `lens.pca_colors(grid)` | float32 embeddings (a compact cube's as an unscaled projection); (coefficients, basis); uint8; (Z, Y, X, 3) uint8 | `grid_of`: `LensError` with no DINO layer | |
| `lens.gallery(root)` | List of gallery entries from `gallery/index.json` | `LensError` on a malformed index | Empty list with no index; titles normalized to "organizers'" |
| `lens.stage(dest)`, `lens.space_files(root)`, `lens.sha256_file(path)` | The folder; the Space files; hex digest | `RuntimeError` when `dest` is not empty or Space files are missing | |
| `lens.ensure_code(cache)`, `lens.ensure_weights(cache, names)` | Code info; dict name to path | `RuntimeError` on a fetch or SHA-256 failure | `LENS_WEIGHTS`, `LENS_DINOVOL`, `LENS_VILLA_SRC` override; receipts name a local checkout without its path |
| `app.list_scans()`, `app.list_gallery()`, `app.random_point(scan, seed=0)`, `app.inspect_cube(...)`, `app.search_cube(...)`, `app.download_cube(...)`, `app.look(...)` | The agent tools, callable directly | `LensError` | Arguments and answers as in Agent tools |
| `app.Cube(key, meta, result)` | A cube's arrays for the page, with `similarity(positive, negative=None)`, `vector(voxel)`, `pca()`, `layers_file(path)`, `ref_sim` | `LensError` from `similarity`/`vector` with no DINO layer | Shared by all visitors through `app.CUBES` (`CubeCache`, `CACHE_CUBES` = 12) |
| `app.draw_slice(state, axis, overlays, top_pct, opacity)`, `app.three_views(state, overlays, top_pct)` | RGB uint8 images | | What `inspect_cube` and `search_cube` draw |

## Inputs

A scan id from `lens.VOLUMES` and a point in level-0 voxels, z y x. The cube is placed on the scans' 128-voxel chunk grid (uncompressed uint8 chunks at `{bucket}/{volume}/volumes/{scan}/0/{z}/{y}/{x}`) and must be at least 5 % inside the scroll mask. A concept upload is a `.npy` float array of shape (864,) or (K, 864), at most 4 MB, no pickles; on the page a file named `*_not*.npy` is the Not this concept. Uploads are capped at 5 MB. The agent tools take example points as text, `"z,y,x; z,y,x"` (at most 64, scan voxels inside the cube).

| Scan id | Scroll | Voxel µm |
| --- | --- | --- |
| PHercParis4 | PHerc. Paris 4 | 2.400 |
| PHerc0139 | PHerc. 139 | 2.399 |
| PHerc1667 | PHerc. 1667 | 2.399 |
| PHerc0500P2 | PHerc. 500P2 | 2.215 |
| PHerc0343P | PHerc. 343P | 2.215 |
| PHerc0814 | PHerc. 814 | 2.399 |
| PHerc0009B | PHerc. 9B | 2.401 |
| PHercMAN5 | PHerc. MAN 5 | 2.399 |
| PHerc1299 | PHerc. 1299 | 2.399 |
| PHerc0332 | PHerc. 332 | 2.399 |
| PHerc1451 | PHerc. 1451 | 2.399 |
| PHercMANB | PHerc. MAN B | 2.399 |

## Outputs

The `.npz` (no scan voxels):

| Field | Type | Meaning |
| --- | --- | --- |
| `grid` | float16 (Z/8, Y/8, X/8, 864) | Unit-length dinovol patch embeddings |
| `grid_reduced`, `grid_basis` | float16 (Z/8, Y/8, X/8, 128), float32 (864, 128) | Compact form (gallery): top 128 directions, rebuilt by `lens.grid_of` |
| `ink`, `surface` | uint8 (Z, Y, X) | Probability times 255; 16 levels when compact |
| `receipt` | JSON bytes | The receipt, below |

The receipt (also the `.json` file, what `lens.py look` prints, and the core of the agent tools' JSON summaries):

| Field | Type | Meaning |
| --- | --- | --- |
| `tool`, `version` | str | `Scroll Lens`, the version that made it |
| `volume`, `scroll`, `zarr`, `level`, `voxel_um` | str, str, str, int, float | The scan |
| `point_zyx` | 3 ints | The point asked for, level-0 voxels |
| `cube_origin_zyx`, `cube_size` | 3 ints, int | Where the cube that ran sits; after the CPU fallback, the middle 128³ (origin off the chunk grid by 64) |
| `requested_size` | int | The size asked for (page runs from 1.1.0) |
| `layers` | list | The models whose output the file holds (`dino`, `ink`, `surface`) |
| `device`, `device_name`, `tta`, `seconds` | str, str, bool, dict | Where and how long each model ran, seconds |
| `models_trained_on_this_scroll` | dict | What each model saw of this scroll in training |
| `engine` | dict | Weights (repo, revision, SHA-256) and code commits |
| `agreement_with_ink_model` | dict | `auc`, `auc_control_shifted`, `auc_control_mean`, `auc_control_p05`, `auc_control_p95`, `ink_patch_fraction` |
| `source`, `note_run`, `foreground` | str, str, float | `gpu`, `cpu`, `gallery` or `api`; why the CPU ran (empty when it ran as asked); share of the cube inside the scroll mask |
| `compact`, `gallery_id`, `note` | bool, str, str | Written by `save_npz`; the gallery id; "Model output, not a reading. A cube is smaller than one letter." |

The agent tools' summaries add `slices_zyx`, `reference_fraction_at_tau`, `ink_voxel_fraction`, `surface_voxel_fraction`, `run_note` and `open_in_browser`; `search_cube` adds `concept`, `positive_zyx`, `negative_zyx`, `matches` and `score`.

The page's Save button writes `scroll-lens-VOLUME-Z-Y-X-SIZE.npz` and `.json`, plus `concept.npy`, `concept_not.npy` (with Not this clicks) and `clicks.json` when there are clicks, in a new folder under `TMPDIR/scroll-lens-out`. The viewer's layer file (`gzip`: a 4-byte length, a JSON header naming each array, then the arrays 4-byte aligned) is described in `viewer.js` `loadLayers` and `app.Cube.layers_file`.

| Exit code | Meaning |
| --- | --- |
| `0` | Done; for `tools/` also when you answer anything but y (nothing sent) |
| `1` | `tools/` refused (bad `OWNER/NAME`, not logged in), or an uncaught `RuntimeError` in `lens.py` (weights, code fetch, `stage`) |
| `2` | Refused: unlisted scan, point outside, cube outside the scroll mask, bad size or layer; `build_gallery.py` with `--batch` below 1 |

## Failure modes

`lens.py` prints a refusal as `lens: MESSAGE` and exits 2. The page shows a refusal as a warning and leaves the views as they were; an API or MCP caller gets it as an error with the same text.

| What you see | Why | What to do |
| --- | --- | --- |
| `'VOLUME' is not one of the scans this Space may read; choose from PHercParis4, ...` | The scan is not in `lens.VOLUMES` | Pick an id from the list, or call `list_scans` |
| `point [Z, Y, X] is outside the scan, whose shape is [...]` | The point is past the scan's level-0 shape | Use a point inside the scan |
| `give the point as three whole numbers, z y x, in level-0 voxels` | Fewer or more than three coordinates, or not numbers | Give z, y and x |
| `NAME must be a whole number, not VALUE` | None, NaN, text or a fraction where a whole number belongs | Send an integer |
| `NAME must be true or false, not VALUE` | `look`'s `tta`, `compact` or `allow_cpu` was neither a boolean nor true, false, yes, no, 1 or 0 | Send a boolean |
| `cube side must be one of (128, 256) voxels, not N` | A size other than `lens.SIZES` | Use 128 or 256 |
| `cube at [...] is not inside the scan, whose shape is [...]` | `read_cube` got an origin outside the scan | Get the origin from `cube_origin` or a receipt |
| `chunk KEY has N bytes, not 2097152: not an uncompressed uint8 chunk` | The bucket object is not a raw 128³ uint8 chunk | Report it; the scan layout changed |
| `the open-data bucket refused KEY (HTTP CODE)` | The bucket answered 403 or another refusal (not a missing key, not throttling) | Try later; if it lasts, the bucket's access changed |
| `could not read the open-data bucket (ERROR); try again in a minute` | Three tries at the bucket failed or were throttled | Check the network; try again |
| `only N% of this cube is papyrus; the scan is masked to 0 outside the scroll. Pick a point on the papyrus: press Surprise me on the page, or call the random_point endpoint.` | The point is outside the scroll mask (less than 5 % papyrus) | Pick another point, press Surprise me, or call `random_point` |
| `could not find papyrus in this scan after several tries; try again` | Neither the blind draws nor the stored-chunk draws found papyrus | Try again or another seed; `build_gallery.py` skips the scan with `VOLUME: skipped (...)` |
| `unknown layer 'NAME'; choose from dino, ink, surface` | `layers` names something else | Use `dino`, `ink`, `surface`, comma-separated |
| `choose at least one model to run` | No layer chosen | Choose one or more |
| `the models are still loading (about a minute after the Space wakes up); try again shortly. The gallery works meanwhile.` | The Space loads about 3.7 GB of weights after it wakes | Wait, or use a gallery cube |
| `the models failed to load: ERROR` | Loading the engine raised, such as a weight hash mismatch or a failed code download | Read the error and fix its cause; the load is not retried until the Space restarts |
| `You have exceeded your free ZeroGPU quota (Ns requested vs. Ms left). Try again in HH:MM:SS. ...` or `You have exceeded your ZeroGPU runs limit. Authenticate with a Hugging Face token for more quota` (ZeroGPU's own text) | The caller's quota is spent, or less than 1.5 times `gpu_seconds` is left | The page and the tools run the middle 128³ on the CPU instead, with the note `ZeroGPU refused the run (...), so the models ran on the Space's CPU, on the middle 128³ voxels. ...`; `look` without `allow_cpu` see the next row |
| `ZeroGPU refused this call: TEXT Pass allow_cpu=True to run the middle 128³ on the CPU instead.` | `look` with `allow_cpu` false, and ZeroGPU refused | Wait for the quota, send a token, or pass `allow_cpu=True` |
| `the Space's CPU is busy with another fallback run; try again in a minute, or sign in to Hugging Face for more ZeroGPU time` | Another CPU fallback is running (one at a time) | Try again in a minute |
| `No GPU here, so the models ran on the CPU on the middle 128³ voxels.` (a note, not an error) | A local copy without CUDA ran a 256³ request | Expect `cube_size` 128 |
| `the models failed on the GPU (ERROR CLASS); try again, or try another point` | The models raised inside the ZeroGPU task (ZeroGPU's "ZeroGPU worker error") | Try again; report it if it repeats at the same point |
| `you already have a model run going; wait for it to finish (one at a time per visitor)` | A second Run the models from the same visitor while one runs | Wait for the first to finish |
| `no gallery cube 'ID'` | The id is not in `gallery/index.json` | Call `list_gallery`, or pick from the list |
| `pick a gallery cube`, `the gallery is empty on this copy; pick a point instead`, `the gallery is empty` | The gallery buttons with no cube chosen, or no gallery | Choose a cube, or use Your own point |
| `This link could not be followed in full: PROBLEMS.` and `The gallery cube could not be opened: ERROR` | A link with a bad scan, cube id, size or coordinate | The page opens the first gallery cube; fix the link |
| `this cube is no longer in the Space's memory (it keeps the last few); run it again` | A run cube dropped out of the page's `CUBES` (12 cubes) | Run it again |
| `give a gallery cube_id, or a scan and a point (z, y, x)` | An agent tool got neither | Pass `cube_id`, or `scan` and a point |
| `unknown overlays [...]; choose from ink, surface, clicks, reference, dino` | `inspect_cube` got another overlay name | Use those names, comma-separated |
| `not a point: 'TEXT'; write z,y,x in voxels` and `...; write z,y,x in voxels, each 0 or more` | `search_cube` points that are not three whole numbers of 0 or more | Write `"z,y,x; z,y,x"` |
| `at most 64 points` | Too many example points | Give 64 or fewer |
| `point (Z, Y, X) is outside the cube at (...) of side SIZE; points must lie inside the cube being searched` | An example point outside the searched cube | Use scan voxels inside the cube |
| `give positive points or a concept file, not both` | `search_cube` got both | Give one |
| `negative points need positive points or a concept file` | Only negatives | Add positives or a concept |
| `this cube has no DINO embeddings, so it cannot be searched` (tools), `this cube has no DINO embeddings; run it with the 3D DINO model to search it` and `this cube has no DINO embeddings; run it with the 3D DINO model to search by clicking` (page), `this cube has no DINO embeddings; run it with the 3D DINO layer` (`lens.grid_of`) | Search on a cube run without the 3D DINO model | Run it with `dino` |
| `that click is outside the cube`, `a click needs a voxel z, y, x` | A malformed click from the viewer | Reload the page |
| `This cube is no longer in this page's session; open it again to search it.` | A click on a run cube after the session ended (`STATE_TTL_S`, 6 hours without a change) or after another tab moved on; a gallery cube reopens by itself | Run the cube again |
| `a page keeps at most 512 clicks; clear some to add more` | `MAX_CLICKS` clicks in one session | Clear clicks, or save the concept and load it |
| `no click to undo` | Undo click with no clicks (a loaded concept file is not undone) | Nothing to do |
| `TYPE: MESSAGE` | Any other error, with its reason (page warning or API error) | Report it with the message |
| `nothing to save yet` | Save before any cube is shown | Open a cube first |
| `a concept file is at most 4 MB` | The uploaded concept is too big | Upload a smaller `.npy` |
| `cannot read the concept file: ERROR` | The upload could not be opened | Upload it again |
| `not a plain .npy array: ERROR` | Not readable as a `.npy` (an `.npz`, a pickle, a broken header) | Save with `np.save` of a float array |
| `a concept is a float array of shape (864,) or (K, 864), not DTYPE SHAPE` | Wrong dtype or shape, or K = 0 | Save float vectors of length 864 |
| `the concept file's size does not match its header` | The header claims more or less data than the file holds | Save the file again |
| `the concept holds non-finite or zero vectors` | NaN, infinity or an all-zero row | Remove those rows |
| `the concept's rows cancel out (their mean is close to zero)` | The rows point in opposite directions | Save a concept that means something |
| `load concept.npy too: concept_not.npy alone has nothing to look for` | Only the Not this file was uploaded | Upload `concept.npy` with it |
| `PATH: embeddings of shape SHAPE, not (N, N, N, 864)` | A `.npz` whose embeddings disagree with its receipt | Rebuild the cube |
| `PATH: reduced embeddings do not match their basis` | A compact `.npz` with mismatched `grid_reduced` and `grid_basis` | Rebuild the cube |
| `PATH: KEY is DTYPE SHAPE, not uint8 (SIZE, SIZE, SIZE)` | `ink` or `surface` has the wrong shape or type | Rebuild the cube |
| `gallery/index.json has no list of cubes`, `gallery/index.json holds an entry that is not an object` | The index is not `{"cubes": [...]}` | Rebuild it with `tools/build_gallery.py`; the page starts with an empty gallery meanwhile (`gallery not loaded: ...` in the log) |
| `gallery entry 'ID' has no KEY` | An entry lacks `id`, `volume`, `title`, `note`, `file`, `point_zyx` or `size` | Fix or rebuild the index |
| `gallery entry 'ID' is listed twice` | Two entries share an id | Remove one |
| `gallery entry 'ID' names a file outside gallery/` | Its `file` has `/` or `..` or is not `.npz` | Fix the entry |
| `gallery entry 'ID' names FILE, which is missing` | The `.npz` is not beside the index | Restore it or remove the entry |
| `gallery entry 'ID' has size SIZE, not one of (128, 256)` | A bad size | Fix the entry |
| `gallery entry 'ID' has a point_zyx outside the scan` | Not three whole numbers inside the scan | Fix the entry |
| `missing Space files: [...]` | A file of `lens.SPACE_FILES` is missing | Restore it from git |
| `DEST is not empty` | `stage` was given a folder with files in it | Give an empty or new folder |
| `REPO/FILE has SHA-256 DIGEST, not EXPECTED` | A downloaded or `LENS_WEIGHTS` file is not the pinned weight | Delete it from the cache and rerun; never edit `lens.MODELS` to match |
| `git fetched HASH, not COMMIT` | The git fetch did not land on the pinned commit; the tarball is tried next | Nothing unless the tarball also fails |
| `the tarball for COMMIT holds 'NAME'` | GitHub's tarball is not for the pinned commit | Try again later; or set `LENS_DINOVOL` or `LENS_VILLA_SRC` |
| `the tarball for COMMIT held no SUBTREE files` | The tarball lacks `dinovol_2/` or `vesuvius/src/` | As above |
| `NAME at COMMIT has no CHECKFILE` | The fetched code lacks its check file | As above |
| `Could not load this cube: ERROR. Pick it again in a minute to retry.` (in the viewer) | The browser could not read the scan chunks or the layer file | Pick the same cube again; check that the browser can reach the bucket |
| `Could not load the 3D view (ERROR); the flat views still work.` (in the viewer) | The browser could not load three.js from cdn.jsdelivr.net, or has no WebGL | Use the flat views; check the network or the browser |
| `This cube has no 3D DINO embeddings, so it cannot be searched. Run it with the 3D DINO model.` (in the viewer) | A click on a cube without DINO | Run it with the 3D DINO model |
| `This cube is still loading; click again in a moment.` (in the viewer) | A click before the scan chunks arrived | Wait for the views |
| `The Space did not answer these clicks; try again in a moment.` (in the viewer) | Three sends of the same clicks went unanswered | Click again |
| HTTP 403 `Scroll Lens does not fetch URLs for callers.` | A request to Gradio's file routes (`gradio_api/file=URL` or `gradio_api/file/URL`) with a URL: the URL proxy is closed (`app.close_url_fetching` and the `NoUrlFiles` middleware) | Fetch the URL yourself |
| `Scroll Lens downloads files only from this Space or the Hugging Face Hub` | A file argument given as a URL on another host (for example `search_cube`'s concept) | Upload the file, or pass a URL this Space or the Hub serves |
| HTTP 413 from an upload, or `An upload to Scroll Lens is at most 12 MB.` | A file over 5 MB (`max_file_size`), or more than 12 MB in one upload request (`MAX_UPLOAD_BYTES`) | Upload a smaller file |
| `Free users are limited to 2 ZeroGPU Spaces. Subscribe to PRO for up to 10` (HTTP 402) | `deploy.py` creating a third ZeroGPU Space on a free account; a paused Space still holds its slot | Free a slot (only deleting a Space does) or use PRO |
| `give the Space as OWNER/NAME` | `deploy.py` got a name without exactly one `/` | Pass `OWNER/NAME` |
| `not logged in to Hugging Face (ERROR). Run: hf auth login` | `deploy.py` found no working login | Chase runs `hf auth login`; agents never log in |
| `not logged in to Hugging Face; run: hf auth login (your token is what spends your GPU minutes)` | `build_gallery.py` found no token | As above |
| `--batch is 1 or more` | `build_gallery.py --batch 0` or less | Use 1 or more |

## How it works

1. `cube_origin` places the cube on the chunk grid around the point (nearest grid line, halves rounded up), or against the scan's far edge; `read_cube` fetches the chunks it overlaps in parallel and crops.
2. dinovol: robust normalization of the whole cube, 128³ windows overlapping by one patch with edge-tapered averaging, unit length (a port of dinovol's napari inspector). Ink: villa's `normalize_image` with the checkpoint's normalization and the EMA weights. Surface: z-score per cube, channel 1 of the softmax. bf16 autocast on CUDA. On ZeroGPU the models run inside one `spaces.GPU` call of `gpu_seconds` = 6 + (size/256)³ × (4 dino + 2 ink + 2 surface, ink and surface × 8 with mirroring) seconds; ZeroGPU reserves 1.5 times that on the RTX PRO 6000. Only ZeroGPU's refusals (titles `ZeroGPU quota exceeded`, `ZeroGPU illegal duration`, `ZeroGPU pending credits exceeded`, `ZeroGPU queue timeout`, `ZeroGPU client error`, or "GPU task aborted") fall back to the CPU, one CPU run at a time.
3. The page keeps a cube's outputs in `app.CUBES`, shared by all visitors: two pools of `CACHE_CUBES` = 12, gallery cubes (reloaded from disk when they drop out) and run cubes (so gallery opens never push out a visitor's run); a session keeps only its cube's key and clicks (at most `MAX_CLICKS` = 512, for `STATE_TTL_S` = 6 hours after its last change). The agent tools keep their own three most recent cubes (`VIEW_CACHE`), with every array, and draw with `draw_slice`.
4. The viewer: `app.viewer_value` sends the browser a small JSON (where the cube is, the URL of its layer file, the clicks and their similarity map as int16 of similarity × 8192). `viewer.js` fetches the scan chunks from the bucket (a missing key, HTTP 404, reads as empty) and the gzipped layer file, then composes each slice on a canvas: the CT windowed to its 0.5th to 99.5th percentile, DINO colors, surface, ink, the reference (top `Top %`, never below `lens.TAU` = 0.5) and the concept, each from 0.35 (`TOP_FLOOR`) to full opacity. Clicks go back with ids through `trigger('select')`, after 260 ms so that a double-click (which resets the zoom) searches nothing; the server acknowledges them in arrival order, and the viewer resends any unacknowledged after 15 s, at most three times. Each answer carries a revision that only grows, and the viewer keeps the newest.
5. The 3D view: three.js 0.160.0 (loaded on first use from cdn.jsdelivr.net) draws the three composed slices as textured planes at their slice positions (they are redrawn and moved on every slider move), the cube's outline, ink and surface voxels at 0.5 or more as points (at most `MAX_POINTS` = 160,000 per layer, thinned evenly), and the concept and reference patches as additive points; OrbitControls with damping 0.07, as in Unroll. A click on a plane is ray-cast to its voxel.
6. Similarity: cosine to the positive concept minus cosine to the negative one. A compact cube is scored in its 128-direction basis: `coef @ (basisᵀ c)`, the projection's dot product, not rescaled.
7. DINO colors: the three top eigenvectors of the embeddings' covariance, signs fixed by skew, stretched to the 1st and 99th percentiles.
8. `random_point`: 24 blind draws of level-3 chunks between 10 % and 90 % of the scroll's height, then draws among the stored chunks of one z slab at a time (an anonymous bucket listing), each looking for a bright voxel whose 256³ neighborhood is at least 90 % inside the mask.
9. Constants in `lens.py`: `CHUNK = 128`, `PATCH = 8`, `EMBED_DIM = 864`, `MIN_FOREGROUND = 0.05`, `REDUCED_DIM = 128`, `MAX_CONCEPT_BYTES` 4 MB, `CONTROL_SHIFTS = 16`, `VERSION = "1.1.0"`. In `app.py`: `CPU_SIZE = 128`, `STATE_TTL_S` 6 hours, `MAX_CLICKS = 512`, `CACHE_CUBES = 12`, `MAX_UPLOAD_BYTES` 12 MB, `SIM_SCALE = 8192`, `TOP_FLOOR = 0.35`, `VIEW_CACHE_N = 3`.

## Cost and time

Free to use and to run locally. On the Space, model runs (Run the models, `look`, and the tools on a scan point) count against the caller's own ZeroGPU quota; everything on gallery cubes is free. Measured on the Space (2026-10-17, RTX PRO 6000 Blackwell MIG 2g.48gb): a 256³ cube with all three models 3.2 to 8.0 s of model time and about 4.5 s of quota, 7 to 12 s per call; 128³ about 0.3 s of model time and 0.5 s of quota. The 99-cube gallery used about 280 s of Chase's 300 s free daily quota; the free account's "8 runs" figure was not enforced. The CPU fallback ran a 128³ cube in about 9 s on the Space; a 4-core cloud CPU took about 35 s plus 30 to 50 s of model loading (2026-10-16). Locally (M1 Pro, 2026-10-17): opening a 256³ gallery cube 1.2 s the first time (most of it writing its 5.8 MB layer file), a 128³ one 0.1 s; DINO colors on a 256³ cube 0.12 s. The browser reads 16 MB of scan chunks for a 256³ cube (2 MB for 128³), its layer file (5.8 MB and 0.6 MB) and, for the 3D view, three.js once (about 670 KB). Memory: a 256³ gallery cube holds about 42 MB in `CUBES`, a fresh 256³ run about 90 MB; each `VIEW_CACHE` cube about 116 MB. GPU work never runs on the Mac (the Modal rule, hard rule 11, applies to anything heavier).

## For agents

- **On the Space:** use the MCP tools or the API endpoints in "Agent tools" above; start with `list_gallery` and `inspect_cube` (no GPU), and hand a person the `open_in_browser` link.
- **Command:** `Client("SharpMeow/scroll-lens").predict(CUBE_ID, "", 0, 0, 0, 256, "", "", None, 20, api_name="/search_cube")` searches a gallery cube with the organizers' reference; locally, `python3 spaces/scroll-lens/lens.py look VOLUME Z Y X --size 128 --out OUT` writes the receipt as JSON beside the `.npz`.
- **Parse:** `agreement_with_ink_model.auc` against `auc_control_p95`; `matches[].center_zyx` (scan voxels) and `score`; `layers`, `cube_origin_zyx`, `cube_size` and `run_note` (set when the CPU ran the middle 128³); arrays from the `.npz` via `lens.load_npz`.
- **Rerun:** the gallery tools are safe to repeat; a tool call on a scan point spends quota unless the cube is among the three in `VIEW_CACHE`; `lens.py look` overwrites the same `.npz` and `.json` in `OUT`.
- **Success:** a result without an error; `auc` above `auc_control_p95`; `cube_size` as asked unless `run_note` says otherwise.
- **Not a pass:** an AUC inside or below the control range; any number on a cube under 5 % papyrus; anything read as letters, since a cube is smaller than one letter; a search on a Paris 4 cube the ink model trained on, taken as a test.
- **Go-ahead:** `tools/deploy.py`, `tools/build_gallery.py`, and model runs on the live Space with Chase's token (his ZeroGPU minutes) need Chase's yes; gallery cubes and anonymous use need nothing.
- **Never:** call a layer or ink map a reading; add a prize-eligible scroll to `lens.VOLUMES` (a test checks it) or a Paris 4 point beyond `PARIS4_TRAINING_POINTS` to anything Scroll Lens picks or publishes; commit gallery cubes (`spaces/scroll-lens/gallery/` is ignored); log in to Hugging Face for Chase.

## Tests

`python3 -m unittest tests.test_scroll_lens -v`: the allow-list against the prize snapshot, chunk placement and off-grid reads with a fake bucket, the bucket's 404, 403 and 503 handling, random points with the stored-chunk fallback, similarity, the AUC against a slow reference, the agreement controls, compact round trips and the reduced search, concept refusals (crafted headers, `.npz`, empty and canceling rows), whole-number parsing, points and matches for the tools, the gallery index checks, the Space card, staging, the gallery plan and its batches, the viewer's layer file format and JSON, the shared cube cache, the CPU-fallback receipt, the reference layer's floor, the agent tools on a gallery cube (inspect, search, download, refusals), `look`'s strict flags, the page text and saving. With gradio installed it also checks that the built app has exactly the seven agent tools with `look`'s documented parameters and launches with MCP; with node it checks that `viewer.js` parses as Gradio runs it. 50 tests, 7 s on an M1 Pro (2026-10-17). They do not load the models, read the real bucket, call Hugging Face, or run the viewer in a browser (it was checked by hand in a browser, flat and 3D, 2026-10-17).

## History

- 2026-10-24: Connect your tool accordion, branched from `main` at `2ce4d50` (shown on the next deploy; the Space is paused).
- 2026-10-17: v1.1.0, on top of PR #114's agent tools: the views drawn in the browser (`viewer.js`: live sliders, drag, wheel, zoom, pan, undo, hover readout), a 3D view of the cube with the slices as moving planes (three.js, as in Unroll), and fixes from a bug test of the live v1.0.0 (receipt layers, ZeroGPU durations and refusals, cube placement, the bucket's 403, random points on sparse scans, reduced-embedding similarity, the agreement control range, shared memory, the URL proxy, upload size, strict flags in `look`); `build_gallery.py --batch` (`c921ef1`, `e14e165`, [PR #115](https://github.com/ChaseHendrick/Scrolls/pull/115)).
- 2026-10-17: v1.1.0 agent tools and MCP (`list_scans`, `list_gallery`, `random_point`, `inspect_cube`, `search_cube`, `download_cube`), American spelling ([PR #114](https://github.com/ChaseHendrick/Scrolls/pull/114)).
- 2026-10-17: gallery grown to 99 cubes (batches 2 to 9) on Chase's remaining quota (Space commit `f4aa1ee`).
- 2026-10-17: v1.0.0 live on Hugging Face with the 19-cube gallery. Gallery agreement (Model output): most cubes AUC 0.67 to 0.91 with controls 0.42 to 0.59; PHerc. 500P2 0.30 (control 0.45), 343P 0.40 (0.63) and 332 0.62 (0.59) disagree ([PR #113](https://github.com/ChaseHendrick/Scrolls/pull/113)).
- 2026-10-17: tool page, docs index, map, glossary and handoff rows (`60da647`).
- 2026-10-16: built in thread "Use my 5 minutes of ZeroGPU" (Chase: "something cool and visionary and useful by both newcomers and the elite researchers, like I did and we did for Unroll") (`378bd42`, [PR #110](https://github.com/ChaseHendrick/Scrolls/pull/110)).

## Related

- [Unroll](../unroll-space.md) and its [tool page](unroll.md): 3D viewer of traced windings; Scroll Lens's 3D view follows its controls.
- The AutoPipeline ink Space (`SharpMeow/autopipeline-ink`).
- [auc](auc.md): `python -m kit auc`, scoring an ink map against labels.
- [The Space card](../../spaces/scroll-lens/README.md): what visitors and agents read, with the tool table and MCP setup.
