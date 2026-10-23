---
title: Umbilici
emoji: 🩻
colorFrom: blue
colorTo: gray
sdk: static
app_file: index.html
pinned: false
license: apache-2.0
short_description: Center lines of 22 Herculaneum scrolls, in live X-ray CT
tags:
  - vesuvius-challenge
  - herculaneum
  - computed-tomography
  - umbilicus
  - three.js
datasets:
  - SharpMeow/vesuvius-center-lines
  - SharpMeow/pherc0175a-lasagna
---

# Umbilici

A carbonized Herculaneum scroll is a sheet of papyrus wound around a center. Its center line, the umbilicus,
is where tracing tools such as VC3D and villa's lasagna start. This page draws every public center line we know
of for the 22 scans on the [Vesuvius Challenge prize page](https://scrollprize.org/prizes) (the 21 First Letters
volumes and PHerc1447, read 23 October 2026), over X-ray CT that your browser streams from the open data.

- **Array**: all 22 lines side by side, heights to scale in millimetres. Person-made lines are ice blue; the nine
  lines from Chase Hendrick's Center Finder are amber. The slider exaggerates side-to-side drift (default 3x).
- **X-ray**: one scan. A radiograph (or maximum intensity) render of the whole scan at about 0.3 mm per voxel,
  the lines inside it, and an axial slice at 70 to 80 µm per pixel with every line's crossing marked.
- **Lasagna**: PHerc0175A with villa's lasagna field: its sheet channel (cos) at nine heights, its surface
  normals as short needles coloured by orientation, and the Center Finder's line through them.
- **Data**: every number on the page as sortable tables (29 lines, 22 scans), with `lines.csv`, `scans.csv`,
  `points.csv` and `umbilici.json` downloads.
- **Guide**: five tabs for every level of reader: Start here, VC3D and villa, For researchers (every statistic
  defined), Data details (frames, pyramids, encodings) and Credits.

Each scan card has, per line, a download link and a copyable URL for the raw file, its sha256, licence, upstream
and every statistic; the scan's OME-Zarr URL and CT pyramid; each line's x, y, z at the slice you are on; a link
that reopens the exact view; and the scan's points as CSV or JSON.

## Where the lines come from

| Source | Scans | Licence |
| --- | --- | --- |
| Alexey Drobkov ([herculaneum-umbilici](https://github.com/AlexeyDrobkovStrikesBack/herculaneum-umbilici)) | 10 | MIT |
| Abd Elilah, manual curves ([umbilicus-cross-validation](https://github.com/TAUIL-Abd-Elilah/umbilicus-cross-validation)) | 6 | CC BY 4.0 |
| Iyan Dopico (PHerc1218, as shipped in Drobkov's repository) | 1 | MIT |
| Vesuvius Challenge open data (`representations/umbilicus`) | 3 | CC BY-NC 4.0 |
| Chase Hendrick's Center Finder (model output) | 9 | CC BY-NC 4.0 |

Every file, with its hash, upstream link and note, is in
[SharpMeow/vesuvius-center-lines](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines). Abd Elilah's
PHerc1203 curve is shown faded: its author withdrew it from recommended use (repository README, 16 Aug 2026).

The nine Center Finder lines are model output, made for the 1.2 m scans that had no person's line. No person has
checked their ends on CT. An automatic end check graded each one, and the page shows the grade: PASS (both ends
passed: PHerc0306B, PHerc0846A), FLAG (a problem at an end, such as a lean or a line that stops short of the
papyrus: PHerc0175A, PHerc0490A, PHerc0846B) or VOID (the tilt test failed its own control on that scan, so the
check says nothing either way: PHerc0175B, PHerc0483A, PHerc0483B, PHerc0490B). Each line's card says which
ends are usable.

## Using the lines in VC3D and villa

Each file is JSON with `control_points`, a list of `{x, y, z}` in the level-0 voxels of the scan it names. From
villa's source (`main`, read 23 Oct 2026):

- VC3D ([`volume-cartographer/core/src/Umbilicus.cpp`](https://github.com/ScrollPrize/villa/blob/main/volume-cartographer/core/src/Umbilicus.cpp))
  reads a bare array of points or an object with `points` or `control_points`, each point with x, y and z, and an
  optional `metadata` block with `voxelsize_um`, `volume` and the grid `volume_width`, `volume_height`,
  `volume_slices` (all three or none). 22 of the 29 files carry that stamp, matching their scan's grid; Abd
  Elilah's six and Iyan Dopico's are bare points. VC3D interpolates linearly between points and holds the end
  points' x and y beyond them.
- spiral-fitting ([`spiral-fitting/umbilicus.py`](https://github.com/ScrollPrize/villa/blob/main/spiral-fitting/umbilicus.py))
  sorts `control_points` by z, multiplies x, y and z by `coordinate_scale` (or 1/`downsample_factor`), ignores
  `metadata` and extrapolates linearly past both ends. A fit on pyramid level L needs a scale of 1/2^L.
- villa's [spiral tutorial](https://scrollprize.org/tutorial_spiral) (last updated 16 Sep 2026): `fit_spiral.py`
  reads `umbilicus.json` from its `--dataset` root, beside `lasagna_inputs/*.ome.zarr`; `infer_winding_volume.py`
  takes `--umbilicus`; every input must be in the fit's own voxel frame.

Because VC3D holds the ends and spiral-fitting extrapolates them, check a line's usable ends before relying on
it near the top or bottom of a scan.

## X-ray

CT is not stored on this Space. Each visitor's browser reads coarse levels of the OME-Zarr volumes straight from
the Vesuvius Challenge open-data bucket with HTTP range requests: one axial plane of each 128-voxel chunk at a
time, about 1,000 small reads for a whole-scan render and 25 to 100 for a slice. The radiograph adds up CT along
each ray, like a film X-ray. Scans: Vesuvius Challenge open data, CC BY-NC 4.0.

## Lasagna field

villa's lasagna `predict3d` over the whole PHerc0175A scan (ScrollPrize/villa db3dbea2, model
`scrollprize/lasagna` de45f011), from
[SharpMeow/pherc0175a-lasagna](https://huggingface.co/datasets/SharpMeow/pherc0175a-lasagna). This page ships a
small derivative in `data/lasagna/`, made by `tools/build_lasagna.py`: the cos channel at nine heights
(4x down, resized to 2048 px), an orientation picture per height (hue from the doubled in-plane angle of the
normal, so a normal and its opposite match) and 155,891 normals on a 96 by 96 by 192 voxel grid. It is model
output, shown so people can see what the dataset holds.

## For agents

The page is driven from the console or a headless browser through `window.umbilici`:

| Call | Returns or does |
| --- | --- |
| `scans()` | every scan: scroll, scan id, volume, voxel size, shape, prize lists, sources, end grade |
| `lines(scroll)` | that scan's lines with control points `[x, y, z]` in level-0 voxels |
| `at(scroll, z)` | each line's `[x, y]` at height `z` (linear between control points) |
| `select(scroll, mode)`, `mode('array' or 'scan' or 'lasagna')`, `setZ(z)` | change the view |
| `state()` | mode, scan, height, CT streaming progress |
| `image()`, `slice()` | PNG data URLs of the 3D view and the slice |
| `stats(scroll)` | every statistic of each line (points, z range, coverage, steps, stray, tilt, wiggle, path, stamp) and the pair gaps |
| `table('lines' or 'scans')`, `csv('lines' or 'scans' or 'points')` | the Data tables as objects or CSV text |
| `guide(tab)`, `data(tab)` | open the guide (`basics`, `vc3d`, `research`, `data`, `credits`) or the Data tables |
| `bench(n)` | renders `n` frames and returns milliseconds per frame and the pixel ratio |
| `settings(obj)` | read or change the viewer settings: `glow` (0 to 3), `radius` (0 to 1), `quality` (`auto`, `high`, `low`), `film`, `spin` |

URL parameters: `?mode=scan&scan=PHerc0191&z=10400`, `?mode=lasagna&scan=PHerc0175A&z=6400`, `?ex=5`,
`?guide=vc3d`, `?data=lines`, `?glow=1.5`. The gear button holds the settings (glow strength and spread, quality,
film grain, spin), saved in the browser.
`data/lines.json` is the page's whole line table, built by `tools/build_lines.py` from a copy of the dataset.

## Licence

Code: Apache 2.0, Chase Hendrick (`LICENSE`, `NOTICE`); three.js is MIT. Data keeps its own terms (`NOTICE`).
A sibling of [Unroll](https://huggingface.co/spaces/SharpMeow/unroll). A center line is geometry; nothing here
is a reading of any text.
