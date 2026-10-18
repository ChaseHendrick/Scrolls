# quickstart-wip: a first CT slice, segment and ink preview from the open data, for an unreviewed Quick start guide

`scripts/quickstart/` holds two scripts written for a draft Quick start guide: one fetches a first CT slice, segment mesh and ink preview of PHerc0139 from the open-data bucket, one records the guide's terminal GIF; both are only on branch `grok/quickstart-wip`, unreviewed.

| Field | Value |
| --- | --- |
| Id | `quickstart-wip` |
| Status | Branch only |
| Kind | script folder |
| Area | Data and downloads |
| Run | `python scripts/quickstart/first_look.py {slice,segment,ink,all}`, `python scripts/quickstart/terminal_gif.py` (from the repository root of a checkout of the branch) |
| Code | `scripts/quickstart/first_look.py` (`main`, `slice_plane`, `cmd_slice`, `cmd_segment`, `cmd_ink`), `scripts/quickstart/terminal_gif.py` (`main`, `commands`), with the guide `docs/QUICKSTART.md`, all on branch `grok/quickstart-wip` |
| Tests | None. The branch's `docs/MAP.md` row names `tests/test_quickstart.py`, but the commit does not contain it |
| Needs | `first_look.py`: Python 3 (the guide says 3.10 or newer), numpy, Pillow and tifffile (the `reader` extra of `pyproject.toml` installs them). `terminal_gif.py`: Pillow, `curl`, the DejaVu Sans Mono font at `/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf` (a Linux path), and network access to the Unroll Space |
| Runs on | Any CPU. `first_look.py all` took 3.0 s wall and wrote 1.5 MB on a 4-core cloud container, Python 3.13 (measured 2026-10-16 for this page); the guide says about 6 s on a fast connection. `terminal_gif.py`: Not measured |
| Network | `first_look.py`: `vesuvius-challenge-open-data.s3.amazonaws.com` over anonymous HTTPS (zarr chunks, the w035 mesh, a bucket listing and the ink preview). `terminal_gif.py`: also `huggingface.co` (the Unroll Space's `tools/inkbench.py` and `data/bench/` images) |
| Writes | `first_look.py`: `work/quickstart/` by default (`slice-z170.png`, `w035.tifxyz/` with `meta.json`, `x.tif`, `y.tif`, `z.tif`, `slice-with-w035.png`, `w035-ink-preview.jpg`). `terminal_gif.py`: `docs/assets/quickstart-terminal.gif` and scratch files in `work/quickstart-gif/` |
| Go-ahead | Not needed to run them. Committing what `first_look.py` writes, or a GIF that shows scan imagery, to a public repository is not allowed: the data are CC BY-NC 4.0 and no scroll data goes in git |
| Released | Public branch `grok/quickstart-wip` only, since 2026-10-16; never merged or listed as a release |
| Branch | `grok/quickstart-wip` at `8681ef9` |
| Checked | 2026-10-16 against commit `8681ef9` |

## What it does

The draft guide, `docs/QUICKSTART.md` on the branch, takes a newcomer from an empty machine to three first results with about 10 MB of downloads, then to the advanced path (tracing, ink models, fast inference, AutoPipeline, Ink Bench). `scripts/quickstart/` holds the two scripts it uses.

`first_look.py` fetches small pieces of PHerc0139 from the open-data bucket with the standard library's HTTPS client, no AWS tools or zarr library. `slice` reads one z plane of the 9.362 um scan at pyramid level 5 (32 times coarser than full resolution, 207 x 207 px) chunk by chunk and saves it as a PNG. `segment` downloads the tifxyz mesh of segment w035 (one traced turn of the sheet: `x.tif`, `y.tif`, `z.tif` give one 3D point per grid cell, and `meta.json` its scale and bounding box), prints its grid and bounding box, and draws the mesh points that cross the slice in red. `ink` downloads the published ink detection preview of w035 (a JPEG, 8 times downsampled). `all` does all three.

`terminal_gif.py` remakes the guide's animated terminal recording: it runs `first_look.py all` and three Ink Bench commands from the Unroll Space, captures their text output, and draws it as GIF frames. It shows text only, never scan imagery.

The ink preview is model output, not a reading, and w035 is in the released ink models' training labels, so clear strokes there show only that the data and tools work. The commit message says the work is unreviewed and must not be merged as it is.

## Where the code is

Branch `grok/quickstart-wip` of public Scrolls, one commit on top of `main` at `0d34f92`: `8681ef9` ("WIP: QUICKSTART guide and scripts (not reviewed, do not merge as is)", 2026-10-16). Files: `scripts/quickstart/first_look.py` (149 lines), `scripts/quickstart/terminal_gif.py` (87 lines), `docs/QUICKSTART.md` (366 lines), and small additions to `GLOSSARY.md` (Ink Bench, `original_volume_downscale`, `torch.compile`), `README.md` (a tip linking the guide), `docs/MAP.md` and `docs/README.md`. No PR had been opened for it by 2026-10-16 (GitHub API). The GIF and `tests/test_quickstart.py` that the guide and the map row name are not in the commit.

```bash
git fetch origin grok/quickstart-wip
git show 8681ef9:scripts/quickstart/first_look.py > /tmp/first_look.py
git show 8681ef9:docs/QUICKSTART.md | less
```

## How to run it

From the repository root of a checkout of the branch, or with `first_look.py` saved anywhere (it needs no other file):

```bash
python -m pip install numpy pillow tifffile
python scripts/quickstart/first_look.py all --out /tmp/quickstart
```

On 2026-10-16 it printed (real open data, the script saved to a scratch folder, `--out out`):

```
wrote out/slice-z170.png: level 5 slice 170 (full-resolution z about 5440), 207 x 207 px, values 0 to 143
wrote out/w035.tifxyz: grid 262 x 291 points, 83% valid, grid step 20 voxels
bounding box in level-0 voxels (x, y, z): [1792, 2289, 2843] to [4420, 4572, 8061]
wrote out/slice-with-w035.png: 385 mesh points of w035 near slice 170, in red
wrote out/w035-ink-preview.jpg (520 kB) from PHerc0139/segments/20260317000000-w035_2026031718/ink-detection/downsampled/...-ds8.jpg
```

It worked when it exits 0 and prints the four `wrote` lines.

```
usage: first_look.py [-h] [--z Z] [--out OUT] {slice,segment,ink,all}
```

| Option | Default | Meaning |
| --- | --- | --- |
| `what` | required | `slice`, `segment`, `ink` or `all` (positional) |
| `--z Z` | `170` | Level-5 slice index, 0 to 655; 170 crosses segment w035 |
| `--out OUT` | `work/quickstart` | Output folder, created if missing |

`segment` alone also reads the slice at `--z` to draw the overlay, but does not save the slice PNG.

```
usage: terminal_gif.py [-h] [--out OUT] [--work WORK]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--out OUT` | `docs/assets/quickstart-terminal.gif` (under the repository root) | The GIF to write |
| `--work WORK` | `work/quickstart-gif` (under the repository root) | Scratch folder for the commands it runs |

`terminal_gif.py` was not run for this page.

Errors seen or read in the code: `--z must be 0 to 655 at level 5` (exit 1, seen with `--z 9999`); `missing NAME: run python -m pip install numpy pillow tifffile`; `unexpected level layout: ...` when the level's zarr header is compressed or not uint8; `no ink preview found for w035`; `refusing a URL outside the open-data bucket`. A chunk that answers 403 or 404 is taken as never written and left as 0. `terminal_gif.py` stops with a Python traceback when a command fails (`check=True`) or the font file is missing.

## Inputs and outputs

Inputs, fixed in the code: `PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr` level 5 (uncompressed uint8 chunks), `PHerc0139/segments/20260317000000-w035_2026031718/mesh/20260317000000-on-20250728140407-9.362um.tifxyz`, and the first `.jpg` under that segment's `ink-detection/downsampled/` whose key holds `2.399um` (else the first `.jpg`).

| Output | What it is |
| --- | --- |
| `slice-z<Z>.png` | Grayscale CT slice at level 5, 207 x 207 px |
| `w035.tifxyz/` | `meta.json`, `x.tif`, `y.tif`, `z.tif` as in the bucket; points at -1 or non-finite are invalid |
| `slice-with-w035.png` | The slice, 3 times enlarged, with w035's points within half a level-5 voxel of the slice in red |
| `w035-ink-preview.jpg` | The published ink preview, about 0.5 MB |

All of these are derived from CC BY-NC 4.0 scan data: they stay on your machine, in the git-ignored `work/`, never in a public commit.

## Why it is not on the default branch

The commit message says why: "WIP: QUICKSTART guide and scripts (not reviewed, do not merge as is)". The handoff's open-items row "Quick start guide" reads "In progress: a public QUICKSTART guide" with the next step "Write it and open a PR" ([`HANDOFF.md`](../HANDOFF.md)). The branch is named for Grok, which no longer works in this repository (stopped 16 October 2026); no public note records a decision to drop the guide. Known gaps: `tests/test_quickstart.py` and `docs/assets/quickstart-terminal.gif` are named but missing, and `terminal_gif.py` reads a Linux font path, so it fails on a Mac.

## For agents

- **Revive:** Safe to bring back after review: cherry-pick `8681ef9` onto a new branch, add `tests/test_quickstart.py` (offline, with the bucket stubbed), make the font path configurable, write tool pages for `scripts/quickstart/` (the tool-pages rule, hard rule 16), and open a PR; never merge it as it is. Check `docs/README.md` first, since `start-here.md` covers part of the same ground (the docs-index rule, hard rule 13).
- **Check first:** That the bucket paths still exist (the volume, the w035 mesh and its `ink-detection/downsampled/` previews); that the guide's commands and numbers still match `main`, which has moved since `0d34f92`; that the Ink Bench commands still match the Unroll Space's `tools/inkbench.py`.
- **Never:** Commit the slice, mesh, overlay or ink preview, or a GIF with scan imagery, to a public repository; call the ink preview a reading or a new result (w035 is in the models' training labels); merge the WIP commit unreviewed.

## History

- 2026-10-16: the guide and both scripts, one unreviewed commit on `grok/quickstart-wip` (`8681ef9`).

## Related

- [unroll](unroll.md): the Space whose Ink Bench the guide's first score and `terminal_gif.py` use.
- [fetch](fetch.md): `main`'s tool for mirroring a bucket prefix over HTTPS, for more than a first look.
- [`start-here.md`](../start-here.md): `main`'s guide for newcomers, the current home of that topic.
- [`HANDOFF.md`](../HANDOFF.md): the "Quick start guide" row.
