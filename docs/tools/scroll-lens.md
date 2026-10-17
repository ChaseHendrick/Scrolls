# scroll-lens: look inside a scan cube with the organisers' 3D DINO, ink and surface models

A Hugging Face ZeroGPU Space that reads a 128³ or 256³ cube of a public 2.2 to 2.4 µm scroll scan and shows what three Vesuvius Challenge 3D models see in it, with click search over the 3D DINO embeddings and a CPU fallback.

| Field | Value |
| --- | --- |
| Id | `scroll-lens` |
| Status | Current |
| Kind | app, script |
| Area | Viewers and apps |
| Run | `python3 spaces/scroll-lens/app.py` (the page), `python3 spaces/scroll-lens/lens.py look VOLUME Z Y X` (one cube, no page), `python3 spaces/scroll-lens/tools/deploy.py OWNER/NAME`, `python3 spaces/scroll-lens/tools/build_gallery.py OWNER/NAME`; no public URL yet |
| Code | `spaces/scroll-lens/app.py` (the page), `spaces/scroll-lens/lens.py` (everything else), `spaces/scroll-lens/tools/deploy.py`, `spaces/scroll-lens/tools/build_gallery.py`, `spaces/scroll-lens/requirements.txt`, `spaces/scroll-lens/README.md` (the Space card) |
| Tests | `tests/test_scroll_lens.py`, 29 tests, numpy only |
| Needs | Python 3.12 (3.10 or newer works), the pins in `spaces/scroll-lens/requirements.txt` (torch 2.13.0, timm 1.0.30, numpy 2.5.2, zarr 3.4.1, gradio 6.28.0 for the page); downloads dinovol at commit `a72fda2` and villa's `vesuvius/src` at `b29f310` itself. `tools/deploy.py` needs huggingface_hub; `tools/build_gallery.py` needs numpy, gradio_client and huggingface_hub |
| Runs on | ZeroGPU GPU, or CPU: 128³ cube with all three models in about 35 s plus 30 to 50 s of model loading (measured 2026-10-16, 4-core cloud CPU); GPU time per cube not measured yet |
| Network | `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (scan chunks), `huggingface.co` (weights at pinned revisions; `tools/` also the Space itself), `github.com` or `codeload.github.com` (model code at pinned commits) |
| Writes | Model weights and code under `$LENS_CACHE` (default `TMPDIR/scroll-lens`, about 3.7 GB); `look` writes `VOLUME-Z-Y-X-SIZE.npz` and `.json` to `--out`; the page writes saved files under `TMPDIR/scroll-lens-out`; `tools/build_gallery.py` writes `--out` (default `spaces/scroll-lens/gallery/`, gitignored) |
| Go-ahead | Needed for `tools/deploy.py` (creates or pushes the Space) and `tools/build_gallery.py` (spends Chase's ZeroGPU minutes and uploads `gallery/`); both ask y/N; not needed to run locally |
| Released | Code on public `main` since 2026-10-16 ([PR #110](https://github.com/ChaseHendrick/Scrolls/pull/110), built on branch `claude/project-thread-cl5mbs`); built and tested, not yet on Hugging Face; planned Space `SharpMeow/scroll-lens` |
| License | Apache 2.0 for the Space's code ([`spaces/scroll-lens/LICENSE`](../../spaces/scroll-lens/LICENSE), [`NOTICE`](../../spaces/scroll-lens/NOTICE)); the models and the scans keep their own licenses |
| Checked | 2026-10-17 against commit `caf1991` |

## What it does

The Vesuvius Challenge released three 3D models with its PHerc. Paris 4 work (Angelotti et al. 2026, [arXiv:2606.29085](https://arxiv.org/abs/2606.29085)): `scrollprize/dinovol_v2_ps8_with_paris4_352500`, a self-supervised 3D ViT that gives each 8 × 8 × 8 voxel patch 864 numbers (an embedding); `scrollprize/ink_3d_dino_guided`, which marks ink voxels directly in the scan; and `scrollprize/surface_recto_3dunet`, which marks the written (recto) side of each sheet. Scroll Lens reads one cube of a scan from the open-data bucket, runs any of the three on it, and shows the results as overlays on three slice views and in a 3D plot.

Click search: a click in "More like this" mode takes the embedding of the clicked patch and lights up the cube's most similar patches; "Not this" subtracts a patch. The concept is the unit-length mean of the clicked embeddings, the same recipe the organisers used for their reference ink embedding (`avg_ref_embedding.npy`, 256 expert clicks), which the page also shows. The concept follows the visitor to other cubes and scans and downloads as `concept.npy`.

Everything shown is model output, not a reading. A cube is at most 0.6 mm across, smaller than one letter. Scroll Lens reads only twelve listed scans (below), none on the First Letters or Grand Prize eligible lists. On PHerc. Paris 4, whose title is an open prize, Scroll Lens itself picks only the eight points listed in the ink checkpoint's training config (`lens.PARIS4_TRAINING_POINTS`).

The tool has two parts. `lens.py` holds everything except the web page: the allow-list of scans, chunk reading, the three models, similarity, the agreement check, saving, and a command line. `app.py` is the Gradio page and its hidden `look` endpoint. Two scripts in `tools/`, run on Chase's computer, put the Space on Hugging Face and build its gallery of precomputed cubes.

## When to use it

- To see what the organisers' 3D models mark in a piece of a scan, without installing villa or dinovol.
- To try few-click labelling with 3D DINO embeddings, then carry the concept to another scan or a script.
- To get the models' outputs for a cube as arrays (`look` endpoint or `lens.py look`).

Do not use it:

- To read text or judge a candidate: use flattened surface renders and the ink tools; Scroll Lens is a 0.6 mm window.
- On a target or prize-eligible scroll: it refuses them, and such work belongs in Scrolls-private.
- To score an ink map against labels: use `python -m kit auc` ([auc](auc.md)).
- To view traced windings in 3D: use [Unroll](unroll.md).

## Quick start

```bash
cd spaces/scroll-lens
python3 lens.py volumes
python3 lens.py look PHercParis4 37628 8793 22167 --size 128 --out OUT
```

`OUT` is any folder. `volumes` needs no network; on 2026-10-17 it printed twelve lines, the first:

```
PHercParis4  PHerc. Paris 4           2.400 um  20260411134726-2.400um-0.2m-78keV-masked.zarr
```

`look` downloads about 3.7 GB of weights and code on its first run. On 2026-10-16 (4-core CPU) it read the cube at z 37504, y 8704, x 22144 and printed a receipt ending with:

```
 "agreement_with_ink_model": {
  "auc": 0.7075366381879422,
  "auc_control_shifted": 0.4785939706546452,
  "ink_patch_fraction": 0.073974609375
 }
```

It worked if the exit code is 0, `OUT` holds the `.npz` and `.json`, and the control sits near or below 0.5. For the page: `python3 app.py`, then open the printed local address.

## Checks and controls

- Agreement with a control that must fail: `lens.agreement` gives the AUC with which a similarity map (the organisers' reference, or the visitor's concept) picks out the patches the 3D ink model marks as ink (mean probability over 0.5), beside the same ink mask rolled by half the cube on every axis. Paris 4 cube above: 0.71 against control 0.48; PHerc. 1667 cube at z 17984, y 7488, x 7488, 128³: 0.76 against 0.45 (Model output, 2026-10-16). A control near the real AUC means the agreement is not about place. `test_agreement_has_a_control_that_fails` checks that the control can fail.
- Port check: on a 128³ Paris 4 block, `Engine._dino_grid` matched dinovol's napari inspector (`compute_patch_embedding_grid`) to a cosine of at least 0.99990 per patch.
- Pinned inputs: weights are refused unless their SHA-256 matches `lens.MODELS`; code is fetched at `lens.CODE` commits.
- The agreement is with another model, not with ground truth; a high AUC says the DINO concept and the ink model mark the same patches, nothing more.

Claim label: Model output, for every number and overlay the tool shows.

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
| `volume` | required | A scan id from `lens.py volumes` (`lens.VOLUMES`) |
| `zyx` | required | Three integers: a point in level-0 voxels, z y x |
| `--size` | `128` | Cube side in voxels, one of `lens.SIZES` = (128, 256); 256 is the models' training patch, 128 fits a CPU |
| `--layers` | `dino,ink,surface` | Comma-separated models to run, from `lens.LAYERS`; no spaces |
| `--tta` | off | Average the eight mirrorings for ink and surface, 8 times their time |
| `--device` | none | `cpu` or `cuda`; none means `cuda` when present, else `cpu` |
| `--out` | `.` | Folder for `VOLUME-Z-Y-X-SIZE.npz` and `.json` (created if missing) |

### `python3 spaces/scroll-lens/lens.py files`

Prints each Space file (`lens.SPACE_FILES`: `README.md`, `app.py`, `lens.py`, `requirements.txt`, `LICENSE`, `NOTICE`) with its SHA-256. No options.

### `python3 spaces/scroll-lens/lens.py stage`

```
usage: lens.py stage [-h] dest
```

| Option | Default | Meaning |
| --- | --- | --- |
| `dest` | required | An empty or missing folder; the Space files are copied into it and its path is printed |

### `python3 spaces/scroll-lens/tools/deploy.py`

Runs on Chase's computer, logged in with `hf auth login`; it never logs in for you. It stages the Space files, lists them with SHA-256, says which differ from the live Space, asks y/N, then creates the Space if needed (Gradio, ZeroGPU hardware `zero-a10g`), uploads, and asks for that hardware if missing. It leaves the Space's `gallery/` alone. Safe to run twice: with nothing changed it uploads nothing.

```
usage: deploy.py [-h] [--private] space
```

| Option | Default | Meaning |
| --- | --- | --- |
| `space` | required | The Space as `OWNER/NAME` |
| `--private` | off | Create the Space private; public otherwise. Only applies when the Space does not exist yet |

### `python3 spaces/scroll-lens/tools/build_gallery.py`

Runs on Chase's computer after the Space is live. It calls the Space's `look` endpoint with his token, so each cube's GPU time counts against his ZeroGPU quota (5 minutes a day on a free account, 40 on PRO, per the script's docstring). The plan, fixed by `--seed`: the eight Paris 4 training points and one random papyrus point per other listed scan, interleaved so an early stop still covers several scrolls. It stops at the first quota refusal and keeps what it has; cubes already in `--out` are skipped next time. Then it lists the files and asks y/N before uploading `gallery/`.

```
usage: build_gallery.py [-h] [--size {128,256}] [--seed SEED] [--out OUT]
                        [--dry-run] [--no-upload]
                        space
```

| Option | Default | Meaning |
| --- | --- | --- |
| `space` | required | `OWNER/NAME` of the live Scroll Lens Space |
| `--size` | `256` | Cube side for every gallery cube, one of `lens.SIZES` |
| `--seed` | `2026` | Seed for the random papyrus points of the non-Paris 4 scans |
| `--out` | `spaces/scroll-lens/gallery` | Folder for the cubes and `index.json` (created even with `--dry-run`) |
| `--dry-run` | off | Print the plan and stop. Still reads the bucket to pick random points; no token, no GPU |
| `--no-upload` | off | Build only; never ask to upload |

### `python3 spaces/scroll-lens/app.py`

Starts the page locally (Gradio queue of 24, the `look` endpoint at most 2 at a time). Page settings, with their defaults from `app.py`:

| Option | Default | Meaning |
| --- | --- | --- |
| Scan | `PHercParis4` | One of the twelve allowed scans |
| z, y, x | 37628, 8793, 22167 | The point, level-0 voxels (the first Paris 4 training point) |
| Cube side, voxels | 256 | 128 or 256; the CPU fallback runs the middle 128³ (`CPU_SIZE`) |
| Models to run | all three | 3D DINO, ink, surface |
| Average eight mirrorings | off | Same as `--tta` |
| Clicking a view does | More like this | Or Not this, or Move the slices here |
| Top % of similar patches shown | 8 | 1 to 40 |
| Layer opacity | 0.7 | 0 to 1 |

The hidden `look` endpoint (`api_name="look"`) takes, in order: volume, z, y, x, size (default 256), layers (default `dino,ink,surface`), tta, compact, allow_cpu (all three default off), and returns the `.npz` path. See [the Space card](../../spaces/scroll-lens/README.md) for a `gradio_client` example.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `LENS_CACHE` | `TMPDIR/scroll-lens` | Download folder for weights and code |
| `LENS_WEIGHTS` | none | Folder of local weights laid out `REPO_NAME/FILE`; still hash-checked |
| `LENS_DINOVOL` | none | Local dinovol checkout (repository root) instead of the pinned download |
| `LENS_VILLA_SRC` | none | Local villa `vesuvius/src` instead of the pinned download |
| `SPACES_ZERO_GPU` | unset | Set to `1` or `true` by Hugging Face on a ZeroGPU Space; with the `spaces` package present, `app.py` then runs models through `spaces.GPU` |

## Python API

Import with `spaces/scroll-lens` on `sys.path` (`import lens`). The Space's `look` endpoint is the remote API (above).

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `lens.cube_origin(vid, center_zyx, size)` | Tuple z, y, x: the cube corner snapped to the 128-voxel chunk grid and kept inside the scan | `LensError` for an unlisted scan, a bad size or a point outside the scan | The point lies inside the cube |
| `lens.read_cube(vid, origin, size, fetch=_get, workers=8)` | uint8 array (size, size, size) | `LensError` off the chunk grid, on a bad chunk, or when the bucket cannot be read | Missing chunks read as 0; `fetch` is replaceable for tests |
| `lens.check_cube(cube)` | Papyrus fraction | `LensError` below `MIN_FOREGROUND` = 0.05 | |
| `lens.random_point(vid, rng, fetch=_get, tries=24)` | A z, y, x point on papyrus | `LensError` after 24 tries | Reads level-3 chunks |
| `lens.Engine(cache=CACHE)` | The three models on the CPU | `RuntimeError` on a weight hash or code fetch failure | Loads once per process; `.describe()` gives models, code and `startup_s` |
| `lens.Engine().run(cube, layers=LAYERS, device="cpu", tta=False)` | Dict: `grid` float16 (Z/8, Y/8, X/8, 864), `ink` and `surface` uint8 (Z, Y, X), timings | `LensError` for an unknown layer | bf16 autocast on CUDA |
| `lens.similarity(grid, positive, negative=None)` | float32 per patch | | Cosine to positive minus cosine to negative |
| `lens.agreement(sim_tokens, ink_u8, threshold=0.5)` | Dict `auc`, `auc_control_shifted`, `ink_patch_fraction` | | Agreement with a model, not ground truth |
| `lens.load_concept(path)` | Unit-length 864-vector | `LensError` for a file over 4 MB, a pickle, a bad shape or zero vectors | |
| `lens.save_npz(path, cube_meta, result, compact=False)` | The path | | `compact` keeps 128 embedding components and 16 levels |
| `lens.load_npz(path)` | Tuple (receipt dict, arrays dict) | `LensError` on shapes that disagree with the receipt | No pickles |
| `lens.grid_of(result)` | float32 embeddings, rebuilt from the compact form if needed | `LensError` with no DINO layer | |
| `lens.gallery(root)` | List of gallery entries from `gallery/index.json` | `LensError` on a malformed entry | Empty list with no index |
| `lens.stage(dest)` | The folder | `RuntimeError` when `dest` is not empty or Space files are missing | |
| `lens.gpu_seconds(size, layers, tta=False)` | int seconds asked of ZeroGPU | `LensError` on a bad size or layer | |

## Inputs

A scan id from `lens.VOLUMES` and a point in level-0 voxels, z y x. The cube is snapped to the scans' 128-voxel chunk grid (uncompressed uint8 chunks at `{bucket}/{volume}/volumes/{scan}/0/{z}/{y}/{x}`) and must be at least 5 % inside the scroll mask. A concept upload is a `.npy` float array of shape (864,) or (K, 864), at most 4 MB, no pickles.

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
| `receipt` | JSON bytes | Scan, point, cube origin and size, models with revisions and SHA-256, code commits, device, seconds, agreement, what each model saw of the scroll in training |

The receipt (also the `.json` file and what `look` prints) holds `tool`, `version`, `volume`, `scroll`, `zarr`, `level`, `voxel_um`, `point_zyx`, `cube_origin_zyx`, `cube_size`, `layers`, `device`, `device_name`, `tta`, `seconds`, `models_trained_on_this_scroll`, `note` ("Model output, not a reading. A cube is smaller than one letter."), `engine`, and, when DINO and ink both ran, `agreement_with_ink_model` with `auc`, `auc_control_shifted` and `ink_patch_fraction`.

The page's Save button writes `scroll-lens-VOLUME-Z-Y-X-SIZE.npz` and `.json`, plus `concept.npy` and `clicks.json` when there are clicks, in a new folder under `TMPDIR/scroll-lens-out`.

| Exit code | Meaning |
| --- | --- |
| `0` | Done; for `tools/` also when you answer anything but y (nothing sent) |
| `1` | `tools/` refused (bad `OWNER/NAME`, not logged in), or an uncaught `RuntimeError` in `lens.py` (weights, code fetch, `stage`) |
| `2` | Refused: unlisted scan, point outside, cube outside the scroll mask, bad size or layer |

## Failure modes

`lens.py` prints a refusal as `lens: MESSAGE` and exits 2; the page shows it as an error popup.

| What you see | Why | What to do |
| --- | --- | --- |
| `'VOLUME' is not one of the scans this Space may read` | The scan is not in `lens.VOLUMES` | Pick an id from `lens.py volumes` |
| `point [Z, Y, X] is outside the scan, whose shape is [...]` | The point is past the scan's level-0 shape | Use a point inside the scan |
| `cube side must be one of (128, 256) voxels, not N` | A size other than `lens.SIZES` (endpoint or API) | Use 128 or 256 |
| `cube at [...] is not on the chunk grid inside the scan` | `read_cube` got an origin not from `cube_origin` | Get the origin from `cube_origin` |
| `chunk KEY has N bytes, not 2097152: not an uncompressed uint8 chunk` | The bucket object is not a raw 128³ uint8 chunk | Report it; the scan layout changed |
| `could not read the open-data bucket (ERROR); try again in a minute` | Three tries at the bucket failed | Check the network; try again |
| `only N% of this cube is papyrus; the scan is masked to 0 outside the scroll. Pick a point on the papyrus, or press Surprise me.` | The point is outside the scroll mask (less than 5 % papyrus) | Pick another point or press Surprise me |
| `could not find papyrus in this scan after several tries; try again` | 24 random level-3 chunks held no papyrus | Try again |
| `unknown layer 'NAME'; choose from dino, ink, surface` | `--layers` names something else (a space after a comma counts) | Use `dino`, `ink`, `surface`, comma-separated, no spaces |
| `choose at least one model to run` | No layer chosen | Choose one or more |
| `the models are still loading (about a minute after the Space wakes up); try again shortly. The gallery works meanwhile.` | The Space loads about 3.7 GB of weights after it wakes | Wait, or open a gallery cube |
| `the models failed to load: ERROR` | Loading the engine raised, such as a weight hash mismatch or a failed code download | Read the error and fix its cause; the load is not retried until the Space restarts |
| ZeroGPU quota used up or no GPU free | The visitor's quota is spent or ZeroGPU is busy | The page says so and runs the middle 128³ on the CPU; `look` does the same only with `allow_cpu` |
| `no gallery cube 'ID'` | The id is not in `gallery/index.json` | Pick from the gallery list |
| `pick a gallery cube` | The gallery button was pressed with none chosen | Choose a cube first |
| `nothing to save yet` | Save before any cube is shown | Run or open a cube first |
| `this cube has no DINO embeddings; run it with the 3D DINO model to search by clicking` | A click search on a cube run without DINO (page) | Rerun with the 3D DINO model |
| `this cube has no DINO embeddings; run it with the 3D DINO layer` | `lens.grid_of` on a result without DINO | Rerun with `dino` in the layers |
| `a concept file is at most 4 MB` | The uploaded concept is too big | Upload a smaller `.npy` |
| `not a plain .npy array: ERROR` | Not readable by `np.load` without pickles | Save with `np.save` of a float array |
| `a concept is a float array of shape (864,) or (K, 864), not DTYPE SHAPE` | Wrong dtype or shape | Save float vectors of length 864 |
| `the concept holds non-finite or zero vectors` | NaN, infinity or an all-zero row | Remove those rows |
| `PATH: embeddings of shape SHAPE, not (N, N, N, 864)` | A `.npz` whose embeddings disagree with its receipt | Rebuild the cube |
| `PATH: reduced embeddings do not match their basis` | A compact `.npz` with mismatched `grid_reduced` and `grid_basis` | Rebuild the cube |
| `PATH: KEY is DTYPE SHAPE, not uint8 (SIZE, SIZE, SIZE)` | `ink` or `surface` has the wrong shape or type | Rebuild the cube |
| `gallery entry 'ID' has no KEY` | `gallery/index.json` lacks a required field (`id`, `title`, `note`, `file`, `point_zyx`, `size`) | Fix or rebuild the index with `tools/build_gallery.py` |
| `gallery entry 'ID' names a file outside gallery/` | Its `file` has `/` or `..` or is not `.npz` | Fix the entry |
| `missing Space files: [...]` | A file of `lens.SPACE_FILES` is missing | Restore it from git |
| `DEST is not empty` | `stage` was given a folder with files in it | Give an empty or new folder |
| `REPO/FILE has SHA-256 DIGEST, not EXPECTED` | A downloaded or `LENS_WEIGHTS` file is not the pinned weight | Delete it from the cache and rerun; never edit `lens.MODELS` to match |
| `git fetched HASH, not COMMIT` | The git fetch did not land on the pinned commit; the tarball is tried next | Nothing unless the tarball also fails |
| `the tarball for COMMIT holds 'NAME'` | GitHub's tarball is not for the pinned commit | Try again later; or set `LENS_DINOVOL` or `LENS_VILLA_SRC` |
| `the tarball for COMMIT held no SUBTREE files` | The tarball lacks `dinovol_2/` or `vesuvius/src/` | As above |
| `NAME at COMMIT has no CHECKFILE` | The fetched code lacks its check file | As above |
| `give the Space as OWNER/NAME` | `deploy.py` got a name without exactly one `/` | Pass `OWNER/NAME` |
| `not logged in to Hugging Face (ERROR). Run: hf auth login` | `deploy.py` found no working login | Chase runs `hf auth login`; agents never log in |
| `not logged in to Hugging Face; run: hf auth login (your token is what spends your GPU minutes)` | `build_gallery.py` found no token | As above |

## How it works

1. `cube_origin` snaps the cube to the chunk grid; `read_cube` fetches the 1 or 8 chunks in parallel.
2. dinovol: robust normalisation of the whole cube, 128³ windows overlapping by one patch with edge-tapered averaging, unit length (a port of dinovol's napari inspector). Ink: villa's `normalize_image` with the checkpoint's normalisation and the EMA weights. Surface: z-score per cube, channel 1 of the softmax. bf16 autocast on CUDA.
3. Similarity: cosine to the positive concept minus cosine to the negative one; the page shows the top `Top %` patches. The organisers' threshold `lens.TAU = 0.5` is reported for their reference.
4. `gpu_seconds` asks ZeroGPU for 12 s plus 6 (dino), 4 (ink) and 4 (surface) times (size/256)³, ink and surface times 8 with mirroring, rounded up.
5. Constants in `lens.py`: `CHUNK = 128`, `PATCH = 8`, `EMBED_DIM = 864`, `MIN_FOREGROUND = 0.05`, `REDUCED_DIM = 128`, `MAX_CONCEPT_BYTES` 4 MB, `VERSION = "1.0.0"`. In `app.py`: `CPU_SIZE = 128`, `STATE_TTL_S` 30 minutes.

## Cost and time

Free to run locally. On the Space, a visitor's runs count against their own ZeroGPU quota. Chase's 5 minutes are planned for the gallery (`tools/build_gallery.py`): 8 Paris 4 training points and one random papyrus point per other scan, about 12 MB per compact 256³ cube. GPU time per cube: not measured. CPU: 128³ with all three models about 35 s plus 30 to 50 s of model loading (2026-10-16, 4-core cloud CPU). 256³ on CPU: not measured. Memory: not measured.

## For agents

- **Command:** `python3 spaces/scroll-lens/lens.py look VOLUME Z Y X --size 128 --out OUT`; the receipt is printed as JSON and saved as `OUT/VOLUME-Z-Y-X-128.json` beside the `.npz`.
- **Parse:** `agreement_with_ink_model.auc` and `.auc_control_shifted` from the receipt; arrays `grid`, `ink`, `surface` from the `.npz` via `lens.load_npz`; `cube_origin_zyx` is the snapped corner, not your point.
- **Rerun:** safe; it overwrites the same `.npz` and `.json` in `OUT` and reuses the cache in `$LENS_CACHE`.
- **Success:** exit 0, both files present, and `auc_control_shifted` near or below 0.5.
- **Not a pass:** an AUC whose shifted control sits close to it; any number on a cube under 5 % papyrus; anything read as letters, since a cube is smaller than one letter.
- **Go-ahead:** `tools/deploy.py` and `tools/build_gallery.py` (uploads and Chase's ZeroGPU minutes) need Chase's yes for that push; running locally needs nothing.
- **Never:** call an overlay or ink map a reading; add a prize-eligible scroll to `lens.VOLUMES` (a test checks it) or a Paris 4 point beyond `PARIS4_TRAINING_POINTS` to anything Scroll Lens picks or publishes; commit gallery cubes (`spaces/scroll-lens/gallery/` is ignored); log in to Hugging Face for Chase.

## Tests

`python3 -m unittest tests.test_scroll_lens -v`: allow-list against the prize snapshot, chunk snapping and reading with a fake bucket, random points, similarity, AUC and the failing control, compact round trips, concept upload refusals, gallery index checks, the Space card, staging, the gallery plan, and the page's drawing and text without gradio. 29 tests, 25.6 s on a cloud CPU (2026-10-17). They do not load the models, read the real bucket, or call Hugging Face.

## History

- 2026-10-17: tool page, docs index, map, glossary and handoff rows (`60da647`).
- 2026-10-16: built in thread "Use my 5 minutes of ZeroGPU" (Chase: "something cool and visionary and useful by both newcomers and the elite researchers, like I did and we did for Unroll") (`378bd42`, [PR #110](https://github.com/ChaseHendrick/Scrolls/pull/110)).

## Related

- [Unroll](../unroll-space.md) and its [tool page](unroll.md): 3D viewer of traced windings.
- The AutoPipeline ink Space (`SharpMeow/autopipeline-ink`).
- [auc](auc.md): `python -m kit auc`, scoring an ink map against labels.
- [The Space card](../../spaces/scroll-lens/README.md): what visitors read, with the `gradio_client` example.
