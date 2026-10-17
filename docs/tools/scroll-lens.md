# scroll-lens: look inside a scan cube with the organisers' 3D DINO, ink and surface models

A Hugging Face ZeroGPU Space that reads a 128³ or 256³ cube of a public 2.2 to 2.4 µm scroll scan and shows what three Vesuvius Challenge 3D models see in it, with click search over the 3D DINO embeddings and a CPU fallback.

| Field | Value |
| --- | --- |
| Id | `scroll-lens` |
| Status | Current |
| Kind | App (Gradio Space) and command line |
| Area | Viewing and exploration |
| Run | `python3 spaces/scroll-lens/app.py` (page) or `python3 spaces/scroll-lens/lens.py look VOLUME Z Y X` |
| Code | [`spaces/scroll-lens/`](../../spaces/scroll-lens/): `app.py` (page), `lens.py` (everything else), `tools/deploy.py`, `tools/build_gallery.py` |
| Tests | [`tests/test_scroll_lens.py`](../../tests/test_scroll_lens.py), 29 tests, numpy only |
| Needs | Python 3.12 (3.10 or newer works), the pins in `spaces/scroll-lens/requirements.txt` (torch 2.13.0, timm 1.0.30, numpy 2.5.2, zarr 3.4.1, gradio 6.28.0 for the page); downloads dinovol at commit `a72fda2` and villa's `vesuvius/src` at `b29f310` itself |
| Runs on | ZeroGPU (an NVIDIA RTX PRO 6000 Blackwell MIG 2g.48gb slice): a 256³ cube with all three models in 3.5 to 5.8 s of model time, 7 to 12 s per call, about 4.5 s of quota (19 gallery cubes, 2026-10-17). CPU: a 128³ cube in about 35 s plus 30 to 50 s of model loading (2026-10-16, 4-core cloud CPU) |
| Network | `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (scan chunks), `huggingface.co` (weights at pinned revisions), `github.com` or `codeload.github.com` (model code at pinned commits) |
| Writes | Model weights and code under `$LENS_CACHE` (default `TMPDIR/scroll-lens`, about 3.7 GB); `look` writes `VOLUME-Z-Y-X-SIZE.npz` and `.json` to `--out`; the page writes saved files under `TMPDIR/scroll-lens-out` |
| Go-ahead | Needed for `tools/deploy.py` (creates or pushes the Space) and `tools/build_gallery.py` (spends Chase's ZeroGPU minutes and uploads `gallery/`); both ask y/N; not needed to run locally |
| Released | Space [`SharpMeow/scroll-lens`](https://huggingface.co/spaces/SharpMeow/scroll-lens) since 2026-10-17 (v1.0.0, 19 gallery cubes); source on public `main` since PR #110 |
| Checked | 2026-10-16 against commit `378bd42` |

## What it does

The Vesuvius Challenge released three 3D models with its PHerc. Paris 4 work (Angelotti et al. 2026, [arXiv:2606.29085](https://arxiv.org/abs/2606.29085)): `scrollprize/dinovol_v2_ps8_with_paris4_352500`, a self-supervised 3D ViT that gives each 8 × 8 × 8 voxel patch 864 numbers (an embedding); `scrollprize/ink_3d_dino_guided`, which marks ink voxels directly in the scan; and `scrollprize/surface_recto_3dunet`, which marks the written (recto) side of each sheet. Scroll Lens reads one cube of a scan from the open-data bucket, runs any of the three on it, and shows the results as overlays on three slice views and in a 3D plot.

Click search: a click in "More like this" mode takes the embedding of the clicked patch and lights up the cube's most similar patches; "Not this" subtracts a patch. The concept is the unit-length mean of the clicked embeddings, the same recipe the organisers used for their reference ink embedding (`avg_ref_embedding.npy`, 256 expert clicks), which the page also shows. The concept follows the visitor to other cubes and scans and downloads as `concept.npy`.

Everything shown is model output, not a reading. A cube is at most 0.6 mm across, smaller than one letter. Scroll Lens reads only twelve listed scans (below), none on the First Letters or Grand Prize eligible lists. On PHerc. Paris 4, whose title is an open prize, Scroll Lens itself picks only the eight points listed in the ink checkpoint's training config.

## When to use it

- To see what the organisers' 3D models mark in a piece of a scan, without installing villa or dinovol.
- To try few-click labelling with 3D DINO embeddings, then carry the concept to another scan or a script.
- To get the models' outputs for a cube as arrays (`look` endpoint or `lens.py look`).

Do not use it:

- To read text or judge a candidate: use flattened surface renders and the ink tools; Scroll Lens is a 0.6 mm window.
- On a target or prize-eligible scroll: it refuses them, and such work belongs in Scrolls-private.
- To score an ink map against labels: use `python -m kit auc`.

## Quick start

```bash
cd spaces/scroll-lens
python3 lens.py look PHercParis4 37628 8793 22167 --size 128 --out OUT
```

`OUT` is any folder. On 2026-10-16 (4-core CPU) this read the cube at z 37504, y 8704, x 22144 and printed a receipt ending with:

```
 "agreement_with_ink_model": {
  "auc": 0.7075366381879422,
  "auc_control_shifted": 0.4785939706546452,
  "ink_patch_fraction": 0.073974609375
 }
```

It worked if `OUT` holds the `.npz` and `.json` and the control sits near or below 0.5. For the page: `python3 app.py`, then open the printed local address.

## Checks and controls

- Agreement with a control that must fail: `lens.agreement` gives the AUC with which a similarity map (the organisers' reference, or the visitor's concept) picks out the patches the 3D ink model marks as ink (mean probability over 0.5), beside the same ink mask rolled by half the cube on every axis. Paris 4 cube above: 0.71 against control 0.48; PHerc. 1667 cube at z 17984, y 7488, x 7488, 128³: 0.76 against 0.45 (Model output, 2026-10-16). A control near the real AUC means the agreement is not about place.
- Port check: on a 128³ Paris 4 block, `Engine._dino_grid` matched dinovol's napari inspector (`compute_patch_embedding_grid`) to a cosine of at least 0.99990 per patch.
- Pinned inputs: weights are refused unless their SHA-256 matches `lens.MODELS`; code is fetched at `lens.CODE` commits.

Claim label: Model output, for every number and overlay the tool shows.

## Commands and options

`python3 lens.py volumes` lists the scans. `python3 lens.py look VOLUME Z Y X` runs one cube: `--size 128|256` (default 128), `--layers dino,ink,surface`, `--tta` (average the eight mirrorings for ink and surface, 8 times their time), `--device cpu|cuda`, `--out DIR`. `python3 lens.py files` lists the Space files with SHA-256; `python3 lens.py stage DEST` copies them into an empty folder.

`python3 tools/deploy.py OWNER/NAME [--private]` and `python3 tools/build_gallery.py OWNER/NAME [--size 256] [--seed 2026] [--dry-run] [--no-upload]` run on Chase's computer; see their docstrings.

Environment: `LENS_CACHE` (download folder), `LENS_WEIGHTS` (local weights laid out `REPO_NAME/FILE`, still hash-checked), `LENS_DINOVOL` and `LENS_VILLA_SRC` (local checkouts instead of pinned downloads).

## Python API

`lens.read_cube(volume, origin, size)`, `lens.cube_origin(volume, point, size)`, `lens.Engine().run(cube, layers, device, tta)`, `lens.similarity(grid, positive, negative)`, `lens.agreement(sim, ink)`, `lens.save_npz` and `lens.load_npz`. The Space's `look` endpoint takes (volume, z, y, x, size, layers, tta, compact, allow_cpu) and returns the `.npz`; see the Space README for a `gradio_client` example.

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

| Exit code | Meaning |
| --- | --- |
| `0` | Done |
| `2` | Refused: unlisted scan, point outside, cube outside the scroll mask, bad size or layer |

## Failure modes

- "only N% of this cube is papyrus": the point is outside the scroll mask; pick another or press Surprise me.
- "models are still loading": the Space loads about 3.7 GB of weights after it wakes; the gallery works meanwhile.
- ZeroGPU quota used up or no GPU free: the page says so and runs the middle 128³ on the CPU; `look` does the same only with `allow_cpu`.
- A weight with the wrong SHA-256 or a code download without its check file stops start-up with a message naming it.

## How it works

1. `cube_origin` snaps the cube to the chunk grid; `read_cube` fetches the 1 or 8 chunks in parallel.
2. dinovol: robust normalisation of the whole cube, 128³ windows overlapping by one patch with edge-tapered averaging, unit length (a port of dinovol's napari inspector). Ink: villa's `normalize_image` with the checkpoint's normalisation and the EMA weights. Surface: z-score per cube, channel 1 of the softmax. bf16 autocast on CUDA.
3. Similarity: cosine to the positive concept minus cosine to the negative one; the page shows the top `Top %` patches. The organisers' threshold `lens.TAU = 0.5` is reported for their reference.
4. `gpu_seconds` asks ZeroGPU for 12 s plus 6 (dino), 4 (ink) and 4 (surface) times (size/256)³, ink and surface times 8 with mirroring.

## Cost and time

Free to run locally. On the Space, a visitor's runs count against their own ZeroGPU quota. The gallery (`tools/build_gallery.py`, 2026-10-17) holds 19 compact 256³ cubes, 213 MB: the 8 Paris 4 training points and one random papyrus point per other scan. It used 84.8 s of Chase's 300 s daily quota, about 4.5 s per cube. `gpu_seconds` still asks 26 s for a 256³ cube; ZeroGPU counts the time used.

## For agents

Never deploy or upload without Chase's yes for that push. Keep the allow-list free of prize-eligible scrolls (a test checks it) and never add Paris 4 points beyond `PARIS4_TRAINING_POINTS` to anything Scroll Lens picks or publishes. Gallery cubes are model output and stay out of git (`spaces/scroll-lens/gallery/` is ignored).

## Tests

`python3 -m unittest tests.test_scroll_lens -v`: allow-list against the prize snapshot, chunk snapping and reading with a fake bucket, random points, similarity, AUC and the failing control, compact round trips, concept upload refusals, gallery index checks, the Space card, staging, the gallery plan, and the page's drawing and text without gradio.

## History

- 2026-10-17: v1.0.0 live on Hugging Face with the 19-cube gallery. Gallery agreement (Model output): most cubes AUC 0.67 to 0.91 with controls 0.42 to 0.59; PHerc. 500P2 0.30 (control 0.45), 343P 0.40 (0.63) and 332 0.62 (0.59) disagree.
- 2026-10-16: built in thread "Use my 5 minutes of ZeroGPU" (Chase: "something cool and visionary and useful by both newcomers and the elite researchers, like I did and we did for Unroll").

## Related

[Unroll](../unroll-space.md) (3D viewer of traced windings); the AutoPipeline ink Space (`SharpMeow/autopipeline-ink`); `python -m kit auc`.
