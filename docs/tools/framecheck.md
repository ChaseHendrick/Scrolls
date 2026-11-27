# framecheck: is a render in the frame of its mesh and its CT

Checks that a rendered surface volume matches the CT sampled at its own mesh positions (Pearson r of at least 0.95) and that its empty pixels lie only in villa's unrendered edge band: gpchain's frame check, ported to numpy.

| Field | Value |
| --- | --- |
| Id | `framecheck` |
| Status | Experimental |
| Kind | kit module |
| Area | Scoring and controls |
| Run | `python -m kit.framecheck PIECE LAYERS --volume VOLUME [--window 768] [--json]` |
| Code | `kit/framecheck.py` |
| Tests | `tests/test_framecheck.py` |
| Needs | Python 3.9 or later, numpy; tifffile to read the tifxyz quickly (else kit's own TIFF reader in `kit/vc3d_io.py`); zarr to read a `layers.zarr` render (a `.npy` stack needs nothing more); numcodecs for compressed CT chunks (zlib and gzip need nothing). No villa, no VC3D, no GPU |
| Runs on | Any CPU. One 28 by 2,640 by 3,340 render of public PHerc0343, 100,000 pixels, chunks already local: 3.7 s; a 768 px window read 71 chunks against 464 for the whole render (cloud container, 4 cores, 27 Nov 2026). Over the network the whole render's 411 chunks (0.82 GB) took about 2 min 20 s |
| Network | The CT volume's host, for the chunks under the sampled pixels (the open-data bucket for an open-data URL or key); none for a local folder |
| Writes | Nothing, unless `--out FILE` (the result JSON) |
| Go-ahead | Not needed: it reads only, and launches and sends nothing |
| Released | Not yet (planned with the November 2026 Progress Prize entry) |
| License | Apache 2.0 (this repository). The rule comes from gpchain (MIT) |
| Checked | 2026-11-27 against commit `de415de` |

## What it does

A render of a tifxyz piece is only as good as the frame it was made in: the right scan, the right level and voxel size, the mesh's pixels mapped to the right nodes. A render made with the wrong voxel size (for example 8.64 um against a 7.91 um scan) still looks like papyrus, and nothing downstream says it is wrong.

This tool reimplements the frame check of gpchain ([github.com/jo-tud/vesuvius-gpchain](https://github.com/jo-tud/vesuvius-gpchain), MIT, `tools/gpchain/render_contract.py` `frame_check`, read 27 Nov 2026 at commit `3733791`) with numpy only, so it runs on any render without gpchain's stack. The rule is theirs. It averages the two middle render layers at random render pixels, samples the CT trilinearly at the same pixels' 3D positions on the mesh, and passes when Pearson r is at least 0.95 on the pixels where the render has data. A rim gate goes with it: villa's `vc_render_tifxyz` leaves the outer half node cell of a piece unrendered, so every empty render pixel must lie in that edge band, and their share must not pass the band's.

It does not check that the mesh follows one sheet, or papyrus at all: a mesh through air or across two sheets renders in frame and passes. It does not catch sub-pixel registration (half a pixel off still gave r 0.987). A pass is a contract check of render, mesh and CT, not a result; nothing it reads is ink, and nothing here is a reading.

## When to use it

- After any render that feeds an ink model, a package or a score, to make sure the render, the mesh and the CT share one frame; especially when the scan, level, voxel size or render scale was set by hand or changed.
- When a render looks wrong and the question is whether the geometry or the render is to blame.

Do not use it:
- to check layer order (which way the stack runs): that needs the mesh normals against the scroll's center line, which this check does not look at;
- to check whether a mesh stays on one sheet;
- to check flattening distortion.

## Quick start

```bash
python -m kit.framecheck PIECE.tifxyz RENDER/layers.zarr --volume VOLUME --window 768
```

PIECE is the tifxyz the render was made from, RENDER the folder `vc_render_tifxyz` wrote, VOLUME the CT it sampled (URL, open-data key such as `PHerc0343/volumes/20250521140437-8.640um-1.2m-116keV-masked.zarr`, or local folder). Printed on 27 Nov 2026 for one piece of a villa spiral fit of public PHerc0343, rendered with villa's `vc_render_tifxyz`:

```
framecheck: PASS r 0.9988 (bar 0.95) on 98974 px; rim 0.0225 of mesh px, band 0.0332, at edge 1.000; chunks 71
```

It worked when the exit code is 0 and the line says PASS.

## Checks and controls

`tests/test_framecheck.py` builds a synthetic CT, a slanted tifxyz piece and its render, and plants frame errors: a wrong voxel size, a render shifted by one node cell, a flipped render and a transposed render must each fail, and the correct render must pass. Empty pixels inside the piece must fail the rim gate. Trilinear samples and the erosion are checked against scipy.

On real data (Model output about this tool, development only, one piece): on the PHerc0343 piece above, gpchain's own code gave the correct pair r 0.9987, and four planted frame errors all failed: mesh scaled by 7.91/8.64 r 0.138, render shifted one node cell r 0.426, another piece's render r 0.052, render flipped top to bottom r 0.109. This module gave r 0.9988 on the same pair (the quick start line, a 768 px window). PHerc0343 is public and not on the prize list; no ink model was run.

Cross-scroll validation: not applicable (a render contract check, not a scientific claim; it was tried on one PHerc0343 piece).

Claim label: Model output for the r values (measured on the named render); no scientific claim.

## Commands and options

### `python -m kit.framecheck`

```
usage: python -m kit.framecheck [-h] --volume VOLUME [--level LEVEL]
                                [--render-scale RENDER_SCALE] [--n N]
                                [--seed SEED] [--bar BAR] [--mid MID MID]
                                [--window WINDOW] [--threads THREADS]
                                [--out OUT] [--json]
                                piece layers
```

| Option | Default | Meaning |
| --- | --- | --- |
| `piece` | required | the tifxyz folder the render was made from |
| `layers` | required | the render: layers.zarr (OME-Zarr), a zarr array or a .npy stack |
| `--volume VOLUME` | required | the CT the render sampled: URL, open-data key or folder |
| `--level LEVEL` | `0` | the volume level the render sampled |
| `--render-scale RENDER_SCALE` | `1.0` | the render's output pixels per voxel (`vc_render_tifxyz --scale`) |
| `--n N` | `100000` | pixels sampled |
| `--seed SEED` | `3453` | sampling seed |
| `--bar BAR` | `0.95` | pass at Pearson r of at least this |
| `--mid MID MID` | none | the two layers averaged (default the middle two) |
| `--window WINDOW` | none | sample only a centered square of this many render pixels |
| `--threads THREADS` | `8` | chunk fetch threads |
| `--out OUT` | none | also write the result JSON here |
| `--json` | off | print the result as JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `resolve_volume(volume)` | an https URL or a local folder | `FrameError` | an s3:// URL on the open-data bucket and an open-data key become https URLs |
| `http_getter(base, timeout=120, tries=6, sleep=time.sleep)` | get(relpath) | | HTTP reader: 403 and 404 are a missing chunk (None), other errors are retried; raises `FrameError` after the last try |
| `dir_getter(root)` | get(relpath) | | reads chunks from a local folder; a missing file is None |
| `getter_for(base)` | get(relpath) -> bytes or None | | a folder reader, or an HTTP reader that retries and treats 403 and 404 as a missing chunk |
| `level_info(get, level)` | dict | `FrameError` | the level's `.zarray`: shape, chunks, dtype, separator, decoder; refuses zarr v3, filters and F order |
| `FrameError()` | exception | | Every refusal (bad inputs, shapes that do not match) |
| `load_piece(folder)` | see Notes | `FrameError` on bad input | (grid (H, W, 3) float64 in x, y, z, valid mask, grid scale) of a tifxyz folder. |
| `px_valid(v, shape, s, half=0.5)` | see Notes | `FrameError` on bad input | Render pixels whose four surrounding nodes are valid; pixel p sits at node (p + half) * s. |
| `px_xyz(g, rr, cc, s, half=0.5)` | see Notes | `FrameError` on bad input | (n, 3) x, y, z at render pixels (rr, cc), bilinear in the node grid at (p + half) * s. |
| `erode(mask, k)` | see Notes | `FrameError` on bad input | Binary erosion by k steps of the 4-neighbor cross; outside the array counts as False. |
| `ChunkVolume(volume, level=0, threads=8, get=None)` | see Notes | `FrameError` on bad input | Trilinear samples of one level of a zarr v2 volume (local folder, URL or open-data key) |
| `check(piece, layers, volume, n=N, seed=SEED, bar=BAR, mid=None, window=None, rim_px=RIM_PX, rim_cells=RIM_CELLS, coord_scale=1.0, render_scale=1.0)` | see Notes | `FrameError` on bad input | The frame check of one rendered piece. piece: tifxyz folder (or (grid, valid, scale)); layers: (L, H, W) |
| `load_layers(path)` | see Notes | `FrameError` on bad input | A render stack: a .npy file, or an OME-Zarr folder (its level 0) or zarr array (needs zarr). |
| `build_parser(ap)` | the parser | | Adds the command's arguments to an argparse parser |
| `cmd_framecheck(a)` | exit code 0, 1 or 2 | | Runs the check for parsed arguments |
| `main(argv=None)` | exit code | | `python -m kit.framecheck` |

## Inputs

- **piece**: a tifxyz folder (`x.tif`, `y.tif`, `z.tif` float grids in the volume's level-0 voxels, `meta.json` with the grid `scale`); nodes that are -1 in all three, not finite or below z 0 are invalid.
- **layers**: the render, (layers, rows, cols) uint8, as `vc_render_tifxyz` lays it out: render pixel p sits at node (p + 0.5) x scale / render scale. An OME-Zarr folder (`layers.zarr`, level 0), a zarr array or a `.npy`.
- **volume**: the CT the render sampled, a zarr v2 level (3-D, C order, no filters; uncompressed, zlib, gzip, or any numcodecs codec when numcodecs is installed). `--level L` divides the mesh coordinates by 2^L.

## Outputs

One line (PASS or FAIL, r, rim shares, chunks read), or with `--json` the record; `--out FILE` writes the record.

| Field | Type | Meaning |
| --- | --- | --- |
| `r` | float | Pearson r between the mean of `mid_layers` and the CT at the same pixels, on pixels with render data (NaN when either side is constant) |
| `bar` | float | the pass line, 0.95 by default |
| `ok` | bool | r at least `bar`, every empty pixel in the edge band (`rim.at_edge` 1.0) and `rim.share` at most `rim.band_share` |
| `rim` | object | `share` (empty pixels over mesh-valid pixels), `band_share` (edge band over mesh-valid), `at_edge` (share of empty pixels in the band), `px` (band width), `rim_px`, `rim_cells` |
| `reading` | object | `r_all_px` (r on every sampled pixel, empty ones included) and `r_half_px_off_data_px` (r with the pixel center at p, not p + 0.5): readings, not gates |
| `n_sampled`, `n` | int | pixels sampled, and of those with render data |
| `window`, `seed`, `mid_layers`, `render_shape`, `nodes`, `scale` | | the settings and shapes used |
| `chunks` | object | `fetched` and `missing` chunk counts |

| Exit code | Meaning |
| --- | --- |
| `0` | PASS: render, mesh and CT are in one frame by this rule |
| `1` | FAIL: r below the bar or empty pixels outside the edge band |
| `2` | the check could not run (one `framecheck: ...` line says why) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `: neither a zarr array nor an OME-Zarr group with level 0` | the layers path is not a render | Pass the `layers.zarr` folder the render wrote, or a `.npy` |
| `: x, y and z grids differ in size` | a damaged or partly downloaded tifxyz | Fetch the piece again |
| `/meta.json: no positive scale` | the tifxyz has no grid scale | Use the tifxyz the render was made from |
| `layers: a (layers, rows, cols) stack of at least 2 layers is needed, got` | a single image or a composite | Check a layer stack |
| `mid [0, 8]: two layer indices in 0..7` | `--mid` outside the stack | Pass two layers that exist, or leave `--mid` out |
| `no render pixel has four valid nodes: the render's shape does not match the piece` | another piece's render, or a render scale not given | Pair the render with its own piece; pass `--render-scale` when it was not 1 |
| `framecheck needs numpy` | numpy missing | Install numpy |
| `level 1: no .zarray (the volume needs a zarr v2 multiscale with that level)` | wrong volume path or level | Pass the volume's root folder or URL and a level it has |
| `volume 'PHerc0343' is not a URL, an open-data key or a folder` | a scroll name or a typo | Pass the volume's URL, its open-data key or a local folder |
| `https://.../0/.zarray: failed after 6 tries (...)` | the network or the host failed | Retry later, or copy the chunks locally |
| `no volume: pass --volume URL, open-data key or folder` | an empty `--volume` | Pass the CT the render sampled |
| `level 0: zarr_format 3; only zarr v2 is read` | a zarr v3 volume | Use the volume's zarr v2 copy, or convert it |
| `level 0: zarr filters are not supported` | the level uses zarr filters | Use an unfiltered copy |
| `level 0: chunk order 'F'; only C order is read` | Fortran-ordered chunks | Use a C-ordered copy |
| `level 0: a 3-D (z, y, x) array is needed, got shape [...]` | not a CT volume | Pass a 3-D volume |
| `level 0: .zarray is not JSON (...)` | a damaged `.zarray` or an HTML error page | Check the URL or folder |
| `compressor 'blosc' needs numcodecs (pip install numcodecs)` | compressed chunks and no numcodecs | Install numcodecs |
| `window 2: no mesh-valid pixel in the centered window` | the window falls in a hole of the piece | Use a larger window or none |
| `: reading a zarr render needs the zarr package` | zarr missing | Install zarr, or save the stack as `.npy` |
| `FAIL r nan` | the CT under the sampled pixels is constant (all missing chunks, wrong volume) | Check the volume and level; a FAIL is the right answer |

## How it works

1. Read the piece's grid and valid mask; a render pixel is valid when its four surrounding nodes are (`px_valid`, pixel p at node (p + 0.5) x scale / render scale).
2. Empty pixels: valid pixels that are 0 in every layer. Edge band: valid pixels within max(`RIM_PX` 3, ceil(`RIM_CELLS` 0.5 / scale)) steps of the mask edge (4-neighbor erosion).
3. Draw `N` 100,000 valid pixels with seed `SEED` 3453 (inside the centered window when one is given); average the two middle layers there.
4. Sample the CT trilinearly (cval 0 outside and in missing chunks) at the pixels' bilinear 3D positions, and again half a pixel off as a reading.
5. r = Pearson r on pixels with render data; pass when r is at least `BAR` 0.95 and the rim gate holds (gpchain's `rim_limit` "edge_band" rule).

Source: gpchain `render_contract.py` `frame_check` and `render_config.json` "frame" at `3733791` (MIT).

## Cost and time

CPU only, 0 USD. 27 Nov 2026, cloud container (4 cores): 3.7 s for a whole 28 by 2,640 by 3,340 render with its chunks local; the network fetch dominates otherwise (411 chunks, 0.82 GB, about 2 min 20 s from the open-data bucket). Peak memory is the render stack plus the chunks read (uint8, 2 MB per 128-cube chunk); a window keeps both small. Memory not measured further.

## For agents

- **Command:** `python -m kit.framecheck PIECE LAYERS --volume VOLUME --window 768 --json`
- **Parse:** `ok`, `r`, `rim.at_edge`, `rim.share` against `rim.band_share`
- **Rerun:** safe; only `--out` is overwritten; the same seed gives the same pixels
- **Success:** exit 0, `ok` true
- **Not a pass:** a PASS says nothing about sheet following, layer order or ink; r NaN is a FAIL; a PASS on a window covers that window's frame, which is the whole piece's unless the render was stitched
- **Go-ahead:** Nothing
- **Never:** call a PASS a result or a reading

## Tests

`python -m unittest tests.test_framecheck` (12 tests, numpy and tifffile; they skip without them): a correct synthetic render passes; a wrong voxel size, a one-cell shift, a flip and a transpose fail; empty pixels inside the piece fail the rim gate; a window reads fewer chunks; trilinear samples and the erosion match scipy; a render at scale 0.5; volume locations and refusals; the CLI's exit codes. They do not cover a real villa render (see Checks and controls).

## History

- 2026-11-27: first public version (`ee2361f`), a numpy port of gpchain's frame check with its own zarr v2 chunk reader.

## Related

- gpchain ([github.com/jo-tud/vesuvius-gpchain](https://github.com/jo-tud/vesuvius-gpchain)): the source of the rule, with its layer-order check and render contract
- [vc3d-agent](vc3d-agent.md): headless VC3D renders that this can check
