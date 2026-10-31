# dinovol-embeddings: precomputed dinovol features of the whole PHerc0841 scan, readable by URL

A public Hugging Face bucket holding the Vesuvius Challenge's self-supervised dinovol model run over the whole PHerc0841 9.366 um scan, and a guide Space with a click-to-search demo, so anyone can search, cluster or segment by feature similarity without a GPU.

| Field | Value |
| --- | --- |
| Id | `dinovol-embeddings` |
| Status | Current |
| Kind | data, app |
| Area | Data and downloads |
| Run | [huggingface.co/spaces/SharpMeow/dinovol-embeddings](https://huggingface.co/spaces/SharpMeow/dinovol-embeddings) (the guide page and demo); `zarr.open_group(zarr.storage.FsspecStore.from_url(URL, read_only=True), mode="r", zarr_format=2)` on the bucket URL below; the bucket's `README.md` has a worked example |
| Code | `spaces/dinovol-embeddings/build.py` (builds the guide Space from the bucket); the data lives in the public bucket SharpMeow/dinovol-embeddings with its README and index file |
| Tests | None here: before release one 24 x 48 x 48 token block from every slab was read back by URL, logged out (see Checks and controls) |
| Needs | `zarr` 3 with `fsspec` and `aiohttp`; `numpy` |
| Runs on | Any machine with a network. The quick start reads a 4 x 32 x 32 token block (about 2 MB) from a 4-core cloud container (2026-10-24; not timed) |
| Network | `huggingface.co` (the bucket and Space); the build also reads the open-data CT |
| Writes | Nothing when you read; `build.py OUT` writes the Space's files into OUT |
| Go-ahead | Not needed to use. Making the bucket public and the guide Space were Chase's yes (24 Oct 2026); changing the bucket needs his yes per change, the Space redeploys from merged `main` under the standing yes (rule 8) |
| Released | Public on Hugging Face since 2026-10-24 (bucket and guide Space); README "Released tools" entry `dinovol-embeddings` |
| License | CC BY-NC 4.0, the same as the scan; model `scrollprize/dinovol_8um_ps192_102126` (its Hugging Face page states no license) and villa's dinovol code (MIT), credit to their authors |
| Checked | 2026-10-24 against commit `d425839` |

## What it does

dinovol is the Vesuvius Challenge's self-supervised 3D model ([`scrollprize/dinovol_8um_ps192_102126`](https://huggingface.co/scrollprize/dinovol_8um_ps192_102126), checkpoint `teacher_step_640000.pt`). It turns each small cube of a CT scan into a vector, so that cubes that look alike get similar vectors. Running it over a whole scan takes about 48 GPU hours on an L4.

The bucket holds that output for the whole PHerc0841 scan `20250821151531-9.366um-1.2m-113keV-masked.zarr`: one zarr v2 group with `tokens_unit` (480 numbers per 8 voxel cube), `dense` (64 per 4 voxel cube) and `ink` (32 per 4 voxel cube, from the model's ink head). Each vector is stored as int8 with one float16 scale; after scaling it has unit length, so a dot product is a cosine similarity. That is enough for click-a-point concept search, clustering and few-click segmentation on a laptop.

They are raw model output that nobody has checked by eye. They are features, not a reading of any text.

## When to use it

- To find everywhere in PHerc0841 that looks like a point you pick (cosine similarity on `tokens_unit`).
- To train a small classifier or segmenter on frozen features without running the model.
- Beside the PHerc0841 lasagna field ([lasagna-fields](lasagna-fields.md)) for geometry work on the same scan.

Do not use it:

- On another scan: run villa's `embed_volume.py` yourself; only PHerc0841 is here.
- As a test of the model: these are its outputs, with no accuracy check.

## Quick start

```bash
pip install "zarr>=3" fsspec aiohttp numpy
python3 -c "import zarr; g = zarr.open_group(zarr.storage.FsspecStore.from_url('https://huggingface.co/buckets/SharpMeow/dinovol-embeddings/resolve/PHerc0841/20250821151531-dinovol_8um_ps192_102126.zarr', read_only=True), mode='r', zarr_format=2); print(g['tokens_unit'].shape, g['dense'].shape)"
```

Run on 2026-10-24, logged out, it printed:

```text
(2448, 963, 963, 480) (4896, 1926, 1926, 64)
```

It worked when it prints those two shapes. The bucket's `README.md` continues with a cosine similarity example around one voxel.

## Checks and controls

Before release, read back by URL with no token: one 24 x 48 x 48 token block from each of the 102 slabs (5.6 million cells, 4.5 million inside the scroll). No nonzero vector was off unit length by more than 1 percent after scaling, and the nonzero cells matched the nonzero CT voxels at pyramid level 3 exactly (the last slab, past the scan's end, was checked for norms only). The same check passed before the bucket was made public. These checks can fail (a missing chunk, a misplaced slab or bad scales would show), and they show the files are complete and aligned with the scan; they say nothing about how well the features separate sheets, ink or fibers.

Claim label: Model output (the features); Measurement (the read-back checks).

## Commands and options

### `spaces/dinovol-embeddings/build.py`

```
usage: build.py [-h] out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | Folder to write the Space into (uploaded as is) |

Reads one slice (z 9,600) of the bucket and the CT by URL, logged out, and writes `index.html` (this folder's page with its numbers filled in), `assets/ct.webp`, `assets/tokens.webp`, `assets/dense.webp`, `assets/search.i8` (32 numbers per cell, the slice's main directions, int8) and `assets/mask.u8`, plus the README, NOTICE, LICENSE and connect files. Needs `zarr` 3, `fsspec`, `aiohttp`, `numpy` and `pillow`; about a minute on a cloud container. The pictures are model output of PHerc0841 and live only on the Space, never in git.

### The guide Space

[huggingface.co/spaces/SharpMeow/dinovol-embeddings](https://huggingface.co/spaces/SharpMeow/dinovol-embeddings): what the features are, a slider between the CT and the features as color, a click-to-search demo on that slice (it compares 32 numbers per cell, not 480; on 60 random points its similarity tracked the full one with median correlation 0.989, lowest 0.88), a Connect your tool panel, the format and credit.

### Read

`zarr.open_group(zarr.storage.FsspecStore.from_url(URL, read_only=True), mode="r", zarr_format=2)`, where URL is `https://huggingface.co/buckets/SharpMeow/dinovol-embeddings/resolve/PHerc0841/20250821151531-dinovol_8um_ps192_102126.zarr`. Arrays: `tokens_unit`, `tokens_unit_scale`, `dense`, `dense_scale`, `ink`, `ink_scale`. A vector is `array[z, y, x].astype(float32) * scale[z, y, x]`.

### Download

`hf buckets sync hf://buckets/SharpMeow/dinovol-embeddings/PHerc0841/20250821151531-dinovol_8um_ps192_102126.zarr/ARRAY/Z/Y DIR/ARRAY/Z/Y` copies one strip of chunk files, logged out (the `hf` command comes with `pip install -U huggingface_hub`). Chunk folders follow the scan for every array: Z = z // 192, Y = y // 96, X = x // 96 in scan voxels. Take the matching `_scale` folder too, and fetch `.zgroup`, `.zattrs` and each array's `.zarray` with curl; the copy then opens with `zarr.open_group(DIR, mode="r", zarr_format=2)`. Sizes: `tokens_unit` with its scales 179 GB, `dense` 238 GB, `ink` 122 GB, everything 539 GB in about 940,000 files. For everything, log in first (`hf auth login`): listing the whole store logged out was rate limited (HTTP 429) on 2026-10-24. The guide Space's Download section has the commands; the strip at z 9,600, y 3,840 (40 MB) took 7 s logged out and read back as unit vectors.

### Color volume

`https://huggingface.co/buckets/SharpMeow/dinovol-embeddings/resolve/PHerc0841/20250821151531-dinovol_8um_ps192_102126-rgb.ome.zarr`: every `tokens_unit` cube as one color (the scan-wide three main directions, 1st to 99th percentile to 1..255; 0 outside the scroll), a multiscale OME-Zarr (zarr v2, uint8, axes c, z, y, x, four levels). The guide Space's Open in neuroglancer button streams it with an RGB shader. Made from the bucket by Scrolls-private's `colorvol.py` on six CPU Jobs.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| None | | | Read the arrays with `zarr` |

## Inputs

Nothing: the features are ready made, from the masked level-0 PHerc0841 scan in the open data, with the model's robust normalization and fixed scan-wide statistics.

## Outputs

| Array | Shape (z, y, x, channels) | dtype | One vector per |
| --- | --- | --- | --- |
| `tokens_unit` | 2448 x 963 x 963 x 480 | int8 | 8 x 8 x 8 voxels |
| `tokens_unit_scale` | 2448 x 963 x 963 | float16 | |
| `dense` | 4896 x 1926 x 1926 x 64 | int8 | 4 x 4 x 4 voxels |
| `dense_scale` | 4896 x 1926 x 1926 | float16 | |
| `ink` | 4896 x 1926 x 1926 x 32 | int8 | 4 x 4 x 4 voxels |
| `ink_scale` | 4896 x 1926 x 1926 | float16 | |
| `..-rgb.ome.zarr/L` (color volume) | 3 x (2448, 963, 963 halved L times) | uint8 | one color per (8 x 2^L)^3 voxels |

Index `i` covers scan voxels `[i * step, (i + 1) * step)`. Cells outside the scroll are zero and their chunks are not stored. `index.json` counts the chunk files (156,480 per array); the group's `.zattrs` records the model, its sha256, villa's commit, the lattice and the normalization. The total is 539 GB.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `HTTPFileSystem requires "requests" and "aiohttp"` | Streaming needs fsspec's HTTP back end | `pip install aiohttp requests` |
| `AttributeError` on `zarr.storage.FsspecStore` | zarr 2 is installed | `pip install "zarr>=3"` |
| Vectors read as zeros | Outside the scroll | Pick a point inside the scan's nonzero voxels |
| Values step slightly at multiples of z 192 | The scan was embedded in 192-slice slabs, each on its own | Expected; average across the seam if it matters |

## How it works

The scan was cut into 102 slabs of 192 slices. Each slab ran villa's `dinovol/dinovol_2/eval/embed_volume.py` (commit `4ea26d9c`, branch dinovol-refactor) on Hugging Face Jobs with L4 GPUs, 192 voxel tiles on a 96 voxel lattice whose tiles read 32 voxels past the slab's edges, outputs stored as int8 per vector. The slab outputs were then renamed, not rewritten, into the scan-wide arrays (slab k is z chunk k) and checked by URL.

## Cost and time

Free to use: users rent nothing, and a region reads only the chunks it touches. Making it took 22 L4 Jobs, about 48 GPU hours. The color volume took 7 CPU Jobs, 2.5 CPU hours.

## For agents

- **Command:** the quick start's `python3 -c`; then slice the arrays you need.
- **Parse:** arrays as above; multiply by the matching `_scale` array.
- **Rerun:** Safe; reads only.
- **Success:** the two shapes print, and vectors inside the scroll have unit length.
- **Not a pass:** features that load are not a check of the model.
- **Go-ahead:** Nothing to use it. Any change to the bucket needs Chase's yes.
- **Never:** call the features a reading, or rehost them without the CC BY-NC 4.0 terms and credit.

## Tests

None in this repository. The read-back check above ran on 2026-10-24 before and after the bucket was made public; the quick start was run as written.

## History

- 2026-10-24: bucket public with the whole PHerc0841 scan; README "Released tools" entry added ([PR #206](https://github.com/ChaseHendrick/Scrolls/pull/206)).
- 2026-10-24: color volume (`-rgb.ome.zarr`) public beside the embeddings, opened in neuroglancer from the Space; Download section with tested commands and sizes ([PR #211](https://github.com/ChaseHendrick/Scrolls/pull/211)).
- 2026-10-24: guide Space `SharpMeow/dinovol-embeddings` with a click-to-search demo; bucket README gains a plain-words intro and links it ([PR #206](https://github.com/ChaseHendrick/Scrolls/pull/206)).
- 2026-10-27: one page scroll bar (user decision, 27 October 2026): code blocks grow to their full height instead of scrolling inside the page at 380 px (300 px in the Download cards), keeping only a sideways scroll for long lines, and the head carries the one-scroll fragment from `python -m kit spaceconnect render` ([PR #253](https://github.com/ChaseHendrick/Scrolls/pull/253)).
- 2026-10-28: phone fix ([PR #254](https://github.com/ChaseHendrick/Scrolls/pull/254)), found by `python -m kit spaceconnect scroll --width 390` and the live checks after the 27 October deploy: links wrap, so the model link in How it was made no longer makes the page pan sideways by 9 px at 390 px. Deployed as Space commit `26a40791`.
- 2026-10-31: [PR #310](https://github.com/ChaseHendrick/Scrolls/pull/310). the saved theme (the Theme button, `dv-theme`) is set in the head, before the first paint, so the page no longer opens in the system theme and then switches (Chase asked on 31 Oct for every Space to remember the reader's theme). A static Space gets no theme from Hugging Face, so there is nothing else to follow.

## Related

- [lasagna-fields](lasagna-fields.md): the lasagna field of the same scan.
