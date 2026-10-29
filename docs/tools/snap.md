# snap: move a tifxyz mesh along its normals onto a predicted sheet, the CT sheet midline or a band face

`python -m kit snap` moves each vertex of a tifxyz mesh along its normal onto the nearest predicted sheet (the PHerc. 343 winner's snap), the CT band midline (RectoRefine) or a CT band face such as the recto, with a self-check and a sham; `kit.snaptruth` scores snaps against a second scan.

| Field | Value |
| --- | --- |
| Id | `snap` |
| Status | Experimental |
| Kind | kit command, kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit snap`, `from kit import snap`, `from kit import snaptruth` |
| Code | `kit/snap.py`, `kit/snaptruth.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_snap.py`, `tests/test_snap_face.py`, `tests/test_snaptruth.py`, `tests/test_snap_support.py` |
| Needs | Python 3 (run here on 3.13) and numpy. Optional: tifffile (reads the mesh TIFFs; without it kit's own reader in `kit/vc3d_io.py`), numcodecs (for blosc, zstd or lz4 zarr chunks), scipy (only for the tests' cross-checks). No zarr package: zarr v2 and v3 stores are read by `kit/vc3d_region.py`. Data: a tifxyz mesh and a surface prediction or CT zarr on the same level-0 voxel grid |
| Runs on | Any CPU. A 62,500-vertex synthetic mesh took 4.2 s of CPU to snap onto a prediction, 7.5 to 11.7 s for `--check`, and 36 s in CT midline mode (measured 2026-10-16, 4-core Intel Xeon cloud container). On the published PHerc0841 w00 and ag896 meshes one `--check` took 88 to 182 s and 0.7 to 1.7 GB (9 Oct 2026, 4 shared cloud cores) |
| Network | None for a local `--volume`. An `https://` or `s3://` volume (`s3://BUCKET/KEY` is read as `https://BUCKET.s3.amazonaws.com/KEY`) is read anonymously over HTTPS from that host, chunk by chunk, retried on errors, with a 192-chunk cache |
| Writes | With `--out OUT`: `OUT/<mesh>/x.tif`, `y.tif`, `z.tif` and `meta.json` per mesh (replaced), `OUT/snap_report.tsv` (appended) and `OUT/snap_report.json` (replaced). With `--check`: no meshes, and `OUT/snap_check.json` only when `--out` is given. It never changes its inputs |
| Go-ahead | Not needed for a local run or a read of the public open-data bucket |
| Released | Public `main` from the pull request that adds this page (October 2026); `kit/snap.py` shipped earlier inside the AutoPipeline package since 2026-10-14 (branch `submission/progress-2026-10` and its fix releases, the latest `submission/progress-2026-10-fix10`) |
| Guide | [labelsnap](labelsnap.md) and [finesnap](finesnap.md), the label snaps built on the band face snap |
| Checked | 2026-10-29 against commit `afcc05a` |

## What it does

A traced or fitted surface is stored as a tifxyz mesh: a folder with three float32 TIFFs, `x.tif`, `y.tif` and `z.tif`, holding the level-0 voxel coordinates of each grid node (-1 where there is no vertex), and a `meta.json`. Such a mesh can sit a few voxels off the papyrus sheet it follows, and a render taken off the sheet sees less ink. `kit snap` moves every vertex a short distance along its normal onto a sheet, smooths the moves so neighbors cannot land on different sheets, and writes a new tifxyz folder per mesh with the bounding box recomputed. It never edits its input.

It has three targets. With `--source pred` (the default; technique A in the module) it snaps onto the nearest run of predicted sheet voxels in a surface prediction (a zarr where values at or above `--threshold` mark sheet, such as the m7 prediction): a port of Erwin Nieuwlaar's `mesh/snap_meshes.py` at commit `e8370f1` from [his PHerc. 343 submission repository](https://github.com/Nieuwlaar/pherc343-first-letters) (MIT). His meshes were snapped with these defaults at level 0 (Sourced fact, his `mesh/README.md`); the prize was awarded on 2026-10-08 (Sourced fact, [the organizers' post](https://scrollprize.substack.com/p/50k-first-letters-prize-awarded-for)). With `--source ct --mode midline` (technique B) it snaps onto the midline of the bright CT band: a numpy port of the "midline" variant of RectoRefine, pass 2 of ScrollFiesta's `scroll_snap`, at commit `bce8a65` from [scrollfiesta_public](https://github.com/Hob3rMallow/scrollfiesta_public) (MIT, Ben Kyles). The recto-edge variant is not ported: its authors measured it harmful on their core (depth seams 1.95 % to 5.39 %, 2026-09-02, `recto_refine.h` lines 50 to 57; Community report).

With `--source ct --mode recto`, or `--mode face --face-target recto|mid|verso` (technique D, ours, `snap_face`), it snaps onto a face of the nearest bright CT band instead. Per vertex it reads a trilinear CT profile along the normal (plus or minus 12 voxels at 0.25 voxel steps), finds the bands at a level half way between the profile's 10th and 90th percentiles (`kit.snaptruth.sheet_faces`), and moves the vertex onto the nearest band's recto face, midline or verso face at sub-voxel precision. The recto face is the face toward the scroll axis, the inner side of a rolled sheet, where the writing is (Interpretation, the usual papyrological convention; module docstring). The side comes from `--umbilicus`, `--axis-point` with `--axis-dir`, or `--recto-sign`; a recto or verso target without one is refused. `--face-target mid` uses the same band finder for the midline, so recto and mid differ only in the target. [labelsnap](labelsnap.md) runs this snap in its per-vertex form and adds an abstain mask, a surface label and a review queue; that is the form measured against independent scans.

Two controls are ours, and both work in all three modes. `--check` (technique C) plants a known smooth displacement, snaps it back and requires most vertices to return within a tolerance, while a volume shifted so the sheet appears on the planted side, and a volume with no sheet, must both fail to pull the mesh back; it writes no meshes and exits 1 when the check fails. `--sham` writes the control arm of a snapped render: every vertex moved by minus the displacement the snap gave it.

`kit/snaptruth.py` is a library, with no command, for scoring a snap against an independent scan: it registers profiles of the second scan along each label normal, finds the papyrus band's faces on them, and turns the before and after errors into gains with a site bootstrap. A snapped mesh is geometry. An ink map rendered on it is model output, never a reading, and a snap that lands on a sheet does not show that the sheet is the inked one. Status is Experimental because the prediction and midline snaps have not passed the check on real data: it failed on the published PHerc0841 w00 and ag896 meshes in both modes (Checks and controls). Both aim at the sheet's middle, not its recto face.

## When to use it

- Before any snap is used, to see whether it can recover a planted offset on this mesh and volume: `--check`, with `--check-reference snapped` for a mesh that may not sit on a sheet.
- To make a snapped copy and its sham for a comparison fixed in advance, such as an ink AUC of snapped against unsnapped renders. AutoPipeline's `render.snap` runs exactly this (`--check --check-reference snapped`, then the snap or `--sham`, defaults `max_off` 15, `threshold` 1.0, `jump` 6.0, `sigma` 1.0, level 0).
- To reproduce the PHerc. 343 winner's mesh step on his meshes.
- `kit.snaptruth`: to score any label or mesh snap against an independent, finer scan, with registration that leaves out the sheet being snapped to.

Do not use it:

- To put a surface label on the recto face: use [labelsnap](labelsnap.md), or [finesnap](finesnap.md) where a finer scan exists; both were measured against independent scans.
- To fix a mesh that jumps between sheets or sits far off: the prediction snap searches only plus or minus 15 voxels, the midline snap moves at most 3 and the face snap abstains past 4 (`--face-max-move`). Check the wrap in VC3D first.
- In CT mode on a remote scroll volume: the PHerc0841 w00 check did not finish in 50 minutes over HTTPS. Copy the band of level-0 chunks around the mesh to local disk first (about 1,600 chunks, 3.2 GB for that mesh).

## Quick start

```bash
python -m kit snap MESH --volume PRED.zarr --check --check-reference snapped --json
python -m kit snap MESH --volume PRED.zarr --out OUT
python -m kit snap MESH --volume PRED.zarr --out OUT_SHAM --sham
```

- `MESH`: a tifxyz folder (`x.tif`, `y.tif`, `z.tif`, `meta.json`) in the level-0 voxels of the volume.
- `PRED.zarr`: the surface prediction on that grid, a local folder or an `https://` or `s3://` URL. For the CT midline add `--source ct` and give the CT instead, with `--umbilicus U.json` (or `--axis-point X Y Z --axis-dir X Y Z`) so the outward sense is known.
- `OUT`, `OUT_SHAM`: new folders for the snapped mesh and its sham; each gets `OUT/<mesh name>/`.

For the recto face of the CT band (technique D), check and snap the same way:

```bash
python -m kit snap MESH --volume CT.zarr --source ct --mode recto --umbilicus U.json --check --check-reference snapped --json
python -m kit snap MESH --volume CT.zarr --source ct --mode recto --umbilicus U.json --out OUT
```

On synthetic data made with the test helpers in `tests/test_snap.py` (a 48 x 40 x 40 uint8 prediction with a sheet on z planes 29 to 31, and a 12 x 12 mesh, 2 voxels between nodes, at z 26), run on 2026-10-29, the snap printed its report line, the same row it appends to `snap_report.tsv` (columns `winding n_valid frac_with_sheet frac_snapped median_abs_off p90_abs_off frac_rejected frac_already_on`):

```
w01	144	1.000	1.000	4.00	4.00	0.000	0.000
done 1 meshes in 0s -> OUT
```

Every vertex moved 4 voxels, onto z 30, the sheet's center; the sham moved them to z 22. `--check` on a mesh already on the sheet (z 30) and on one 15 voxels off it (z 45):

```
on	PASS	planted median 4.0	residual median 0.2699 p90 0.3992 within 1.0: 1.0	shifted control median 3.0012 (caught)	empty control moved 0.0 (caught)
off	FAIL	planted median 4.0	residual median 4.0 p90 4.4301 within 1.0: 0.0	shifted control median 10.505 (caught)	empty control moved 0.0 (caught)
```

The first exited 0 and the second 1. A snap worked when the exit code is 0, `frac_with_sheet` is high and `median_abs_off` is a few voxels; it can be trusted only after its check passed on the same mesh and volume.

## Checks and controls

**The self-check (`--check`).** A smooth field (`--check-shift` voxels, 4 for pred and -2 for ct, varying by `--check-vary` 1 with a slope of at most 0.05) is planted along the normals (pred) or RectoRefine's outward lines (ct), the displaced mesh is snapped, and its distance to the reference (the input, or with `--check-reference snapped` the snap of the undisplaced input) is measured over the vertices that have a planting direction. It passes only when all three hold:

- recovery: the median residual is at most `--check-tol` (1 voxel) and at least `--check-frac` (0.8) of vertices are within it;
- shifted control caught: the same snap against the volume read so the sheet appears `--control-shift` (3) voxels from the input on the planted side does not also recover;
- empty control caught: against a volume that reads 0 everywhere, no vertex moves at all.

The check presumes the input already sits on a sheet. On a mesh 3 voxels off the sheet (synthetic, 62,500 vertices) the original reference failed with the shifted control "NOT caught" (it put the sheet where the input was), and `--check-reference snapped` passed (residual median 0.18, all within 1 voxel). On a rough mesh a planted move also slides vertices sideways, so the check fails there although each vertex may land on a sheet: on noisy synthetic grids the pred check passed at a median neighbor normal angle of 24 degrees and failed from 31 (Interpretation, module docstring).

**Real results of the check (Model output).** On the published PHerc0841 meshes with the m7 prediction (read over HTTPS) and the CT, each run once on 4 shared cloud cores on 9 Oct 2026 :

| Mesh | Snap onto | Reference | Recovery median, p90 (voxels) | Within 1 voxel | Controls | Passed |
| --- | --- | --- | --- | ---: | --- | --- |
| w00 | m7 prediction | original | 2.86, 7.61 | 24.2 % | both caught | no |
| w00 | m7 prediction | snapped | 1.44, 8.42 | 44.2 % | both caught | no |
| ag896 | m7 prediction | original | 3.38, 8.16 | 19.8 % | both caught | no |
| ag896 | m7 prediction | snapped | 1.99, 9.83 | 37.9 % | both caught | no |
| w00 | CT midline | original | 1.73, 2.56 | 19.5 % | both caught | no |
| w00 | CT midline | snapped | 1.91, 3.25 | 16.1 % | both caught | no |
| ag896 | CT midline | original | 1.73, 2.59 | 20.0 % | both caught | no |
| ag896 | CT midline | snapped | 1.91, 3.30 | 16.3 % | both caught | no |

None passed, so these rows show only that the check can fail.

**The sham (`--sham`).** A snapped render that reads ink no better than its sham says any gain is not from landing on the sheet ([bars plan](../plans/2026-10-09-autopipeline-bars.md), stage 1). No snapped-against-sham ink comparison of these two snaps has run here: they never passed the check that admits them.

**Against independent truth.** The band face snap in its per-vertex form, run through [labelsnap](labelsnap.md) and [finesnap](finesnap.md), was scored against the recto face of independent finer scans of PHerc0139, PHerc0814 and PHerc0841; those numbers are on their pages. The prediction and midline snaps aim at the sheet's middle by design; in the comparison on the labelsnap page both were farther from the recto face than the published label.

Claim label: Model output, for every check and truth-test number above, each for the named meshes, volumes and settings; a snapped mesh is geometry, and nothing here is ink or a reading.

## Commands and options

### `python -m kit snap`

```
usage: python -m kit snap [-h] [--volume VOLUME] [--out OUT]
                          [--windings WINDINGS] [--source {pred,ct}]
                          [--mode {nearest,midline,face,recto}]
                          [--level LEVEL] [--centres] [--batch BATCH] [--json]
                          [--sham] [--max-off MAX_OFF] [--threshold THRESHOLD]
                          [--jump JUMP] [--sigma SIGMA]
                          [--umbilicus UMBILICUS]
                          [--umbilicus-scale UMBILICUS_SCALE]
                          [--axis-point X Y Z] [--axis-dir X Y Z]
                          [--window LO HI] [--band-frac BAND_FRAC]
                          [--range RANGE] [--sample-step SAMPLE_STEP]
                          [--edge-half EDGE_HALF]
                          [--min-edge-frac MIN_EDGE_FRAC]
                          [--distance-bias DISTANCE_BIAS]
                          [--normal-blend NORMAL_BLEND]
                          [--data-weight DATA_WEIGHT]
                          [--anchor-weight ANCHOR_WEIGHT]
                          [--smooth-mu SMOOTH_MU] [--max-slope MAX_SLOPE]
                          [--damping DAMPING] [--max-step MAX_STEP]
                          [--max-total MAX_TOTAL] [--occ-thresh OCC_THRESH]
                          [--local-r LOCAL_R] [--outer-iters OUTER_ITERS]
                          [--inner-iters INNER_ITERS] [--tol TOL]
                          [--min-thick MIN_THICK] [--max-thick MAX_THICK]
                          [--face-target {recto,mid,verso}]
                          [--recto-sign RECTO_SIGN] [--face-per-vertex]
                          [--face-half FACE_HALF] [--face-step FACE_STEP]
                          [--face-max-move FACE_MAX_MOVE]
                          [--face-level FACE_LEVEL]
                          [--face-min-radial FACE_MIN_RADIAL]
                          [--face-jump FACE_JUMP] [--face-sigma FACE_SIGMA]
                          [--face-min-support FACE_MIN_SUPPORT]
                          [--face-min-contrast FACE_MIN_CONTRAST]
                          [--face-contrast-frac FACE_CONTRAST_FRAC]
                          [--face-level-frac FACE_LEVEL_FRAC] [--check]
                          [--check-shift CHECK_SHIFT]
                          [--check-vary CHECK_VARY] [--check-tol CHECK_TOL]
                          [--check-frac CHECK_FRAC]
                          [--control-shift CONTROL_SHIFT]
                          [--check-reference {original,snapped}]
                          MESH [MESH ...]
```

General options:

| Option | Default | Meaning |
| --- | --- | --- |
| `MESH` | required | One or more tifxyz folders. Each folder's name is its output folder and its `winding` in the report, so names must differ. With `--windings`, exactly one folder that holds the meshes |
| `--volume VOLUME` | none | The surface prediction (`--source pred`) or the CT (`--source ct`): an OME-Zarr group or bare array, zarr v2 or unsharded v3, as a local folder or an `https://` or `s3://` URL. Its level 0 must be the mesh's coordinate frame. Without it, `SURF_ZARR` is used |
| `--out OUT` | none | Output folder, created if missing: `OUT/<mesh>/` per mesh plus `snap_report.tsv` and `snap_report.json`. Required unless `--check`; with `--check` it receives only `snap_check.json`. Refused when `OUT/<mesh>` is the input folder |
| `--windings WINDINGS` | none | A text file naming the meshes inside the one `MESH` folder, one per line (his layout); blank lines and lines starting with `#` are skipped, and a name with no `x.tif` under the folder is reported on stderr and skipped |
| `--source SOURCE` | `pred` | `pred`: snap onto the nearest predicted sheet (technique A). `ct`: snap onto the CT band, its midline (technique B) or with `--mode face` or `recto` a face (technique D) |
| `--mode MODE` | none | `nearest` (the only mode for `pred`); for `ct`, `midline` (RectoRefine, technique B), `face` (the band face snap, technique D, target from `--face-target`) or `recto` (`face` with the recto target). Left out, `nearest` for `pred` and `midline` for `ct`. Any other pairing is refused |
| `--level LEVEL` | `0` | Pyramid level of the volume to sample, 0 the finest. Level-0 points are mapped to it as point / 2**level (his rule), or with `--centres` |
| `--centres` | off | Map level-0 points with voxel centers aligned, (p + 0.5) x f - 0.5 (`Volume.to_level`), instead of his p / 2**level; a quarter voxel apart at level 1 |
| `--batch BATCH` | `4000000` | Sample points per batch (`DEFAULT_BATCH`); a memory bound only. Pred reads `BATCH // (2 x MAX_OFF + 1)` vertices per batch |
| `--json` | off | Print the full result object (Outputs) instead of one line per mesh; the files are the same |
| `--sham` | off | Write the sham instead of the snap: each vertex at 2 x input minus snapped. Its `meta.json` record has `"sham": true`. Refused with `--check` |

Prediction snap (`--source pred`, his `snap_meshes.py`):

| Option | Default | Meaning |
| --- | --- | --- |
| `--max-off MAX_OFF` | `15` | K: samples at whole-voxel offsets -K to K along the normal, and the final offset is clipped to plus or minus K. At least 1 |
| `--threshold THRESHOLD` | `1.0` | A sample is sheet when its value is at least this, compared in the volume's own dtype (1 is his v > 0 on an integer prediction) |
| `--jump JUMP` | `6.0` | Reject an offset more than this many voxels from the nan-median of its 5 x 5 grid neighborhood |
| `--sigma SIGMA` | `1.0` | Smoothing of the offset field, a Gaussian in grid cells (mesh nodes), not voxels. Holes are filled with max(SIGMA, 1); 0 skips the final smoothing |

CT midline snap (`--source ct`, RectoRefine). For the options marked so, 0 or less means the default, as in `recto_refine.c`:

| Option | Default | Meaning |
| --- | --- | --- |
| `--umbilicus UMBILICUS` | none | The scroll axis as a villa umbilicus file (JSON, or text lines `z, y, x`), level-0 voxels. The outward direction at a vertex is then horizontal, away from the axis at that height. A path that is not a file is parsed as umbilicus text itself |
| `--umbilicus-scale UMBILICUS_SCALE` | `1.0` | Multiply the umbilicus points by this (for one drawn at another binning) |
| `--axis-point X Y Z` | none | A point on a straight scroll axis, level-0 voxels; needs `--axis-dir`. `--umbilicus` wins when both are given. With no axis, the outward line is the mesh normal as stored |
| `--axis-dir X Y Z` | none | The straight axis' direction |
| `--window LO HI` | none | The CT contrast window. Without it: the 1st to 99th percentile of the CT at the input vertices (a 256-bin rule for uint8 volumes), or 0 to 255 when that window is empty |
| `--band-frac BAND_FRAC` | `0.35` | The band's isovalue as a share of the window, clamped to 0.05 to 0.95 |
| `--range RANGE` | `3.0` | Signed search radius for the rising edge, voxels (0 or less: default) |
| `--sample-step SAMPLE_STEP` | `0.25` | Spacing of profile samples, voxels (0 or less: default) |
| `--edge-half EDGE_HALF` | `0.5` | Half-width of the edge derivative, voxels (0 or less: default) |
| `--min-edge-frac MIN_EDGE_FRAC` | `0.08` | Smallest accepted edge, as a share of the window (0 or less: default) |
| `--distance-bias DISTANCE_BIAS` | `4.0` | Score penalty per voxel of distance from the vertex, so the nearer rising edge wins |
| `--normal-blend NORMAL_BLEND` | `0.85` | Outward line = (1 - blend) x radial + blend x normal (normal flipped outward); 0 radial only, 1 normal only, clamped to 0 to 1 |
| `--data-weight DATA_WEIGHT` | `12.0` | Weight of a found target, scaled by 0.35 + 0.65 x its edge confidence (0 or less: default) |
| `--anchor-weight ANCHOR_WEIGHT` | `24.0` | Weight pulling a vertex with no target to its input position (0 or less: default) |
| `--smooth-mu SMOOTH_MU` | `1.0` | One-ring smoothness weight (0 or less: default) |
| `--max-slope MAX_SLOPE` | `0.55` | Largest difference of neighboring displacements per unit of original edge length (0 or less: default) |
| `--damping DAMPING` | `0.7` | Share of the solved move taken per outer iteration (0 or less: default) |
| `--max-step MAX_STEP` | `0.85` | Largest move per outer iteration, voxels (0 or less: default) |
| `--max-total MAX_TOTAL` | `3.0` | Largest total displacement from the input, voxels (0 or less: default) |
| `--occ-thresh OCC_THRESH` | `0.9` | A move is reverted when it lands within this many voxels of another part of the input mesh (0 or less: default) |
| `--local-r LOCAL_R` | `2.0` | Input vertices within this radius of the vertex's own input position, or in its one-ring, do not count as another part (0 or less: default) |
| `--outer-iters OUTER_ITERS` | `4` | Outer iterations, each with fresh normals and targets; 0 or less also means 4, as in `recto_refine.c` (ScrollFiesta's `recto_iters` 0 skips the pass, which is no snap) |
| `--inner-iters INNER_ITERS` | `48` | Jacobi sweeps per outer iteration (0 or less: default) |
| `--tol TOL` | `0.02` | Stop when the mean accepted step is below this, voxels |
| `--min-thick MIN_THICK` | `1.0` | A band thinner than this, voxels, abstains (0 or less: default) |
| `--max-thick MAX_THICK` | `6.0` | How far past the rising edge to look for the falling edge, voxels; none found means abstain (0 or less: default) |

CT face snap (`--source ct --mode face` or `--mode recto`, technique D, `snap_face`). Each `--face-*` option left out keeps `FACE_SNAP_DEFAULTS` (or the per-vertex preset); `--umbilicus`, `--umbilicus-scale`, `--axis-point` and `--axis-dir` above also name the recto side here. The face options are ignored in the other modes:

| Option | Default | Meaning |
| --- | --- | --- |
| `--face-target {recto,mid,verso}` | none | Left out, `recto`. With `--mode face`: the band face toward the scroll axis (`recto`), the band midline (`mid`) or the face away from the axis (`verso`). With `--mode recto` only `recto` is accepted |
| `--recto-sign RECTO_SIGN` | none | Instead of an axis: +1 when the recto face lies at negative offsets along the stored normal (normals point outward), -1 when at positive ones. 0 names no side, so every vertex abstains. Refused together with an axis |
| `--face-per-vertex` | off | `FACE_SNAP_PER_VERTEX`: no jump rejection and no support rule (`jump` 1e9, `min_support` 1); holes are still filled from neighbors |
| `--face-half FACE_HALF` | none | Left out, `12.0`. Profile half-length along the normal, voxels |
| `--face-step FACE_STEP` | none | Left out, `0.25`. Profile sample step, voxels |
| `--face-max-move FACE_MAX_MOVE` | none | Left out, `4.0`. A band farther than this from the vertex abstains, voxels (0 when the vertex is inside it) |
| `--face-level FACE_LEVEL` | none | One global CT level for the band. Left out, each profile's own level, half way between its 10th and 90th percentiles |
| `--face-min-radial FACE_MIN_RADIAL` | none | Left out, `0.3`. Recto or verso target with an axis: a vertex whose \|normal . radial\| is below this abstains (its side is not named) |
| `--face-jump FACE_JUMP` | none | Left out, `2.0` (1e9 with `--face-per-vertex`). Reject an offset more than this many voxels from its 5 x 5 nan-median |
| `--face-sigma FACE_SIGMA` | none | Left out, `0.0`. Smoothing of the offset field, grid cells; 0 smooths nothing beyond filling holes |
| `--face-min-support FACE_MIN_SUPPORT` | none | Left out, `3` (1 with `--face-per-vertex`). Measured offsets an offset needs in its 5 x 5 window (itself included), and a hole needs around it before it is filled |
| `--face-min-contrast FACE_MIN_CONTRAST` | none | Least profile contrast (90th minus 10th percentile), CT units; a band below it abstains |
| `--face-contrast-frac FACE_CONTRAST_FRAC` | none | Left out, `0.25`. Without `--face-min-contrast`: the contrast floor as this share of the 1st to 99th percentile window of every profile sample of the mesh |
| `--face-level-frac FACE_LEVEL_FRAC` | none | Left out, `0.5`. The face level between the profile's 10th (0) and 90th (1) percentiles (`kit.snaptruth` `FACE_DEFAULTS` `level`); 0.5 is the half-maximum edge |

Self-check:

| Option | Default | Meaning |
| --- | --- | --- |
| `--check` | off | Plant, snap back and run both controls for each mesh; print PASS or FAIL per mesh; exit 1 unless every mesh passes. Writes no meshes |
| `--check-shift CHECK_SHIFT` | none | The planted displacement, voxels; left out, `DEFAULT_CHECK_SHIFT`: 4 for pred (along the normal), 2 for ct face or recto (along the normal, inside `--face-max-move` 4 so the band stays the nearest) and -2 for ct midline (along the outward line, toward the recto side, where the midline search starts within `--range`) |
| `--check-vary CHECK_VARY` | `1.0` | Amplitude of the planted field's smooth variation, voxels |
| `--check-tol CHECK_TOL` | `1.0` | A vertex counts as recovered within this many voxels of the reference |
| `--check-frac CHECK_FRAC` | `0.8` | Share of vertices that must be within `--check-tol`, together with a median at most `--check-tol` |
| `--control-shift CONTROL_SHIFT` | `3.0` | The shifted control reads the volume so the sheet appears this many voxels from the input, on the planted side, along the mean planting direction |
| `--check-reference CHECK_REFERENCE` | `original` | `original`: measure recovery against the input mesh (presumes it sits on a sheet). `snapped`: against the snap of the undisplaced input |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `SURF_ZARR` | unset | The volume to read when `--volume` is not given |
| `KIT_HTTP_REUSE` | `1` | Read by `kit/keepalive.py` for remote volumes: `0` (or `false`, `no`, `off`) opens a new connection per request instead of reusing kept-alive connections |

## Python API

```python
from kit import snap, snaptruth
xs, ys, zs, valid = snap.load_mesh("MESH")
sampler = snap.Sampler(snap.open_volume("PRED.zarr"), level=0)
res = snap.snap_pred(xs, ys, zs, valid, sampler)            # res["xs"], res["report"]
chk = snap.self_check(xs, ys, zs, valid, sampler, lambda *a: snap.snap_pred(*a))
faces = snaptruth.sheet_faces(t, profile, recto_sign=+1)     # t: offsets along the normal, profile: intensities
```

`kit.snap`:

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `SnapError` | An exception class (a `ValueError`) | Nothing | Every refusal of the module; the command prints it as `kit snap: ...` and exits 2 |
| `load_mesh(folder)` | `(xs, ys, zs, valid)`: float32 grids and a bool grid, valid where all three coordinates are above -0.5 and finite | `SnapError` with no `x.tif` or grids of different shapes; `OSError` for unreadable files | Reads with tifffile, or kit's own TIFF reader without it |
| `write_mesh(src, out, xs, ys, zs, valid, record, note)` | The output folder as a `Path` | `SnapError` when `src/meta.json` is not JSON (checked before anything is written) | Writes float32 `x.tif`, `y.tif`, `z.tif` (-1 where not valid) and `meta.json`: the source's, or a new `{"format": "tifxyz", "type": "seg"}`, with `bbox` recomputed, `note` appended to `source`, and `record` under `snap` |
| `normals(xs, ys, zs, valid)` | `(n, ok)`: float32 unit normals (H, W, 3) and where they exist | Nothing | His normals: central differences, one-sided at edges and holes; n = cross(d/dcol, d/drow) |
| `gaussian_kernel1d(sigma, radius)` | A float64 kernel of length 2 x radius + 1 summing to 1 | Nothing | scipy's order-0 kernel |
| `gaussian_filter(a, sigma, truncate=4.0)` | An array of `a`'s dtype | Nothing | `scipy.ndimage.gaussian_filter` in mode reflect, bit for bit with scipy 1.18.1 on the tested cases; sigma at most 1e-15 returns a copy |
| `nanmedian_filter(d, size=5)` | A float array of `d`'s shape | Nothing | Median over a size x size window ignoring nan; nan outside the grid |
| `normconv(d, sigma)` | An array like `d` | Nothing | Gaussian of the finite values over the Gaussian of their mask; nan where the mask weight is at most 1e-3 |
| `Sampler(vol, level=0, centres=False, shift=None, empty=False)` | A sampler: `.nearest(xyz)` (volume dtype, 0 outside), `.trilinear(xyz)` (float64, nan with no corner inside), `.gather(zyx)`, `.derive(shift=None, empty=False)` | `SnapError` for a missing level or a level that is not 3D; `RegionError` from reads (such as a sharded store) | Points are level-0 (x, y, z). `shift` adds a constant vector (the shifted control); `empty` reads 0 everywhere (the empty control) |
| `open_volume(location)` | A `kit.vc3d_region.Volume` | `SnapError` "cannot open ..." | Local folder or `https://`, `s3://` URL |
| `choose_offsets(prof, K)` | `(d, has)`: float32 offsets (nan where no sheet) and a bool per vertex | Nothing | His run choice and parabola, vectorized; `prof` is vertices x (2K + 1) booleans |
| `regularise(D, K, jump=6.0, sigma=1.0)` | `(D3, filled, rejected)` grids | Nothing | His jump rejection, hole filling and smoothing, clipped to plus or minus K |
| `snap_pred(xs, ys, zs, valid, sampler, max_off=15, threshold=1.0, jump=6.0, sigma=1.0, batch=DEFAULT_BATCH)` | A dict: `xs`, `ys`, `zs` (moved, float32), `valid`, `D3`, `apply`, `report` (the report fields), `record` (for `meta.json`), `note` | `SnapError` for `max_off` below 1; read errors from the sampler | Technique A on one mesh |
| `stretch_window(vals, dtype, pct_lo=1.0, pct_hi=99.0)` | `(lo, hi)` floats | Nothing | Their 256-bin rule for uint8, numpy percentiles otherwise; `(0.0, 255.0)` with no values or an empty window |
| `find_targets(sampler, P, Dd, o, band, min_edge, batch=DEFAULT_BATCH)` | `(offset, gradient, found)` per vertex | Read errors from the sampler | RectoRefine's `rr_find_target` with midline on, vectorized; `o` is a `MIDLINE_DEFAULTS`-like dict |
| `snap_midline(xs, ys, zs, valid, sampler, opts=None, axis=None, window=None, batch=DEFAULT_BATCH)` | A dict like `snap_pred`'s (no `D3`) plus `recto` (the statistics under Outputs) | Read errors from the sampler | Technique B on one mesh. `opts` overrides `MIDLINE_DEFAULTS`; `axis` is `("line", point, direction)`, `("umbilicus", points)` or None |
| `snap_face(xs, ys, zs, valid, sampler, axis=None, recto_sign=None, opts=None, face_opts=None, batch=DEFAULT_BATCH)` | A dict like `snap_pred`'s | `SnapError` when `opts["target"]` is not `recto`, `mid` or `verso`; read errors from the sampler | Technique D on one mesh: each vertex moves along its normal onto a face (or the midline) of the nearest bright CT band, found at sub-voxel precision on a trilinear profile by `kit.snaptruth.sheet_faces` (`face_opts` overrides its `FACE_DEFAULTS`), or at one global level when `opts["level"]` is set. The recto face is the one toward the scroll axis, from `axis` (as for `snap_midline`) or `recto_sign`. Offsets are then regularized (`jump`, `min_support`, hole filling, optional `sigma`). `opts` overrides `FACE_SNAP_DEFAULTS` (target `recto`, half 12.0, step 0.25, max_move 4.0, min_radial 0.3, jump 2.0, sigma 0.0). A vertex abstains when the band is ambiguous, off the profile, below the contrast floor, farther than `max_move`, or (recto or verso target) when its normal is nearly tangent to the radial direction |
| `face_options(args)` | The `opts` dict for `snap_face` from parsed arguments: the per-vertex preset when `--face-per-vertex`, `target` (`recto` for `--mode recto`, else `--face-target` or `recto`), then every `--face-*` value given | `SnapError` "--mode recto snaps to the recto face; for TARGET use --mode face --face-target TARGET" | Values left out are not set, so `snap_face` takes them from `FACE_SNAP_DEFAULTS`. `--face-level-frac` is not in it: it goes to `snap_face`'s `face_opts` |
| `planted_field(shape, shift, vary, step_r=1.0, step_c=1.0, max_slope=CHECK_MAX_SLOPE)` | A float32 (H, W) field in voxels | Nothing | shift + vary x sin(2 pi u / Lr) x cos(2 pi v / Lc), wavelengths long enough to keep the slope at most `max_slope` (0.05) |
| `grid_steps(xs, ys, zs, valid)` | `[row step, column step]`, voxels | Nothing | Median node spacing; 1 where there are no neighbors |
| `outward_lines(xs, ys, zs, valid, axis=None, blend=MIDLINE_DEFAULTS['normal_blend'])` | `(dirs, ok)`: float32 (H, W, 3) and bool | Nothing | RectoRefine's outward line per vertex; the planting direction of the ct check |
| `self_check(xs, ys, zs, valid, sampler, snap, shift=4.0, vary=1.0, tol=1.0, min_frac=0.8, control_shift=3.0, reference='original', plant=None)` | One `checks` entry (Outputs) without `mesh` | `SnapError` "no vertex has a normal: nothing to check" | `snap(xs, ys, zs, valid, sampler)` must return a dict with `xs`, `ys`, `zs`; `plant` gives the planting directions (default `normals`) |
| `sham_of(original, snapped)` | Three float64 grids, 2 x original minus snapped | Nothing | The sham arm |
| `run(args)` | `0`, or `1` when a `--check` failed | `SnapError` and read errors | The command without its error handling |
| `build_parser(p)` | `p` | Nothing | Adds the arguments; numpy is not imported, so `--help` works without it |
| `cmd_snap(args)` | `0`, `1` or `2` | Anything not listed under exit code 2 (Outputs) | What the command runs |

`kit.snaptruth` (numpy only, no I/O; profiles are rows of intensities at offsets `t` along a normal, uniform step):

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `smooth(p, sigma)` | float64 array of `p`'s shape | Nothing | Gaussian along the last axis, sigma in samples, edges reflected; sigma at most 0 returns a copy |
| `shifted(t_ext, prof_ext, t, s)` | (lines, len(t)) float64 | Nothing | The profiles read at t + s by linear interpolation; nan outside `t_ext` |
| `register_shift(t, ref, t_ext, mov_ext, mask, s_max=4.0, step=0.05)` | A dict: `shift` (parabola-refined), `peak` (mean NCC there), `edge` (peak at the end of the range: do not trust), `lines`, `curve` | Nothing | Mean per-line normalized cross correlation over the samples `mask` keeps (a line needs at least 8); all scores nan gives `shift` nan and `edge` true |
| `bands(t, p, opts=None)` | `(list of (lower face, upper face), level, contrast)` | Nothing | Papyrus bands of one profile; a face off the profile's end is nan |
| `sheet_faces(t, p, recto_sign, at=0.0, opts=None)` | A dict: `recto`, `verso`, `mid`, `thick`, `dist`, `second`, `gap_recto`, `gap_verso`, `split`, `contrast`, `n_bands`, `ok`, `why` (`no band`, `band runs off the profile`, `two bands about as near`, or empty) | Nothing | The band nearest `at`. `recto_sign` +1 means t grows outward, so the recto face is the lower face (Interpretation: rolls are written on the inside) |
| `gradient_faces(t, p, recto_sign, at=0.0, opts=None)` | A dict like `sheet_faces`'s, with the faces at the steepest rise and fall of the band nearest `at` (sub-sample, by a parabola) | Nothing | A second face definition (the steepest edge), with `GRAD_DEFAULTS` (`grad_sigma` 1.0) smoothing before the derivative; the tests against independent scans report it beside the half-level faces |
| `depth(x, recto, verso)` | float64 array | Nothing | 0 at the recto face, 1 at the verso face |
| `offsheet(x, recto, verso)` | float64 array | Nothing | Distance outside the sheet, 0 inside |
| `gains(x_arm, x_id, truth)` | float64 array | Nothing | \|x_id - truth\| - \|x_arm - truth\| per vertex; positive means the arm moved closer |
| `site_means(values, sites)` | `(site ids, means, counts)` | Nothing | Per site, ignoring nan |
| `site_bootstrap(site_values, n_boot=10000, seed=0, level=0.95)` | `{"mean", "lo", "hi", "n_sites"}` | Nothing | Percentile interval over sites; nan with no finite value |
| `classify(ci, margin)` | `GAIN`, `HARM`, `NULL`, `INCONCLUSIVE` or `NO DATA` | Nothing | GAIN: lo above 0 and mean at least margin; HARM: hi below 0 and mean at most -margin; NULL: the interval inside plus or minus margin |

Constants: `FACE_SNAP_DEFAULTS` (technique D's settings, listed in the `snap_face` row), `FACE_SNAP_PER_VERTEX` (`{"jump": 1e9, "min_support": 1}`), `DEFAULT_CHECK_SHIFT` (`{"nearest": 4.0, "midline": -2.0, "face": 2.0}`), `FACE_TARGET_NAMES` (the `snapped_to` text per target) and `FACE_SOURCE_NOTE`.

`FACE_DEFAULTS` holds the band finder's settings (How it works). On the synthetic profile of a single band centered at +1.5 with half width 3, `sheet_faces` returned recto -1.628, verso 4.628, mid 1.5, thick 6.256, ok true (run 2026-10-16).

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| Mesh | A tifxyz folder: `x.tif`, `y.tif`, `z.tif`, 2D grids of one shape (rows, columns), any float dtype, read as float32; `meta.json` optional | Coordinates are (x, y, z) in level-0 voxels of the volume. A vertex is valid when all three are above -0.5 and finite. A vertex VC3D hides (z at most 0, or masked by `mask.tif`) still takes part, and `mask.tif` is not copied |
| Surface prediction (`pred`) | Zarr, 3D (z, y, x) per level, any numeric dtype | Values at or above `--threshold` are sheet. The m7 predictions in the open-data bucket are on the scan's level-0 grid |
| CT (`ct`) | Zarr, 3D (z, y, x), any numeric dtype | Sampled trilinearly; a missing chunk reads 0. uint8 volumes get their 256-bin window rule |
| Umbilicus | A file: JSON (a list of `[z, y, x]`, or an object with `points` or `control_points` holding `{x, y, z}` entries) or villa's text (`z, y, x` per line, `#` comments) | Level-0 voxels, times `--umbilicus-scale` |
| Windings file | Text, one mesh name per line | Only with `--windings` |

A volume is opened as an OME-Zarr group (levels from its `multiscales`) or a bare array (one level). Points outside [0, size - 0.5) on any axis read 0 in pred mode. Size limit: memory for one mesh's sample batch (`--batch`) and for the mesh's grids; the volume is read chunk by chunk.

## Outputs

Per mesh, with `--out OUT` and without `--check`, folder `OUT/<mesh>/`:

- `x.tif`, `y.tif`, `z.tif`: float32, the moved coordinates, -1 where the input had no vertex. A vertex the snap does not move keeps its position (pred: no normal, or no finite offset after filling; ct: no move accepted).
- `meta.json`: the input's, with `bbox` recomputed over valid vertices (`[[min x, min y, min z], [max x, max y, max z]]`), `source` with a note appended (` + snap_meshes_local (...)`, ` + kit snap midline (...)`, ` + kit snap face (...)`, and `; sham: ...` for a sham), and a `snap` record:

| Field | Type | Meaning |
| --- | --- | --- |
| `snap.max_off`, `snap.jump`, `snap.sigma` | int, float, float | Pred settings |
| `snap.mode`, `snap.max_total`, `snap.range`, `snap.band_frac`, `snap.outer_iters` | str, float, float, float, int | Ct settings (`mode` is also set for pred, `nearest`) |
| `snap.frac_snapped`, `snap.median_abs_off` | float, float or null | As in the report |
| `snap.target`, `snap.max_move`, `snap.jump`, `snap.sigma` | str, float, float, float | Face mode (`mode` `face`): the target, and the settings used. `max_move` here is the offset guard, `--face-max-move` plus `--face-half` (16 at the defaults), not `--face-max-move` itself |
| `snap.tool`, `snap.snapped_to`, `snap.level`, `snap.centres`, `snap.volume` | str, str, int, bool, str | `kit snap`; `predicted sheet`, `CT band midline`, or in face mode `CT band recto face`, `CT band midline (face snap)` or `CT band verso face`; the pyramid level (in face mode it replaces the record's own `level`, so a `--face-level` value is not kept), `--centres` and the volume read |
| `snap.threshold` | float | Pred only |
| `snap.recto` | object | Ct only: the `recto` statistics below |
| `snap.sham` | bool | `true`, only with `--sham` |

`OUT/snap_report.tsv`: a header line of the eight `REPORT_COLUMNS`, written only when the file is empty, then one row per mesh per run (appended, as his script does; `nan` for null). `OUT/snap_report.json`: the result object below, replaced each run.

Printed: one TSV row per mesh, then `done N meshes in Ss -> OUT`; with `--check`, one line per mesh (`NAME`, `PASS` or `FAIL`, the planted median, the residual median, p90 and share within tolerance, the shifted control's median with `caught` or `NOT caught`, the empty control's largest move with `caught` or `NOT caught`). With `--json`, the result object instead:

| Field | Type | Meaning |
| --- | --- | --- |
| `tool`, `source`, `mode`, `snapped_to`, `volume`, `level` | str, str, str, str, str, int | What ran; `mode` is `nearest`, `midline` or `face` (also for `--mode recto`), `snapped_to` as in `meta.json` |
| `seconds` | float | Wall time of the run, 2 decimals |
| `meshes[]` | list | Without `--check`: one row per mesh |
| `meshes[].winding`, `.n_valid` | str, int | Folder name; valid vertices |
| `meshes[].frac_with_sheet` | float or null | Pred: share of vertices with a normal that found sheet within plus or minus K. Ct midline: share of valid vertices with a target in the first outer iteration. Face: share of vertices with a normal that got a face target |
| `meshes[].frac_snapped` | float | Pred: share of valid vertices moved, counting vertices whose offset was only filled in from neighbors, so read it beside `frac_with_sheet`. Ct: share moved more than 1e-5 voxels |
| `meshes[].median_abs_off`, `.p90_abs_off` | float or null | Median and 90th percentile of the move of moved vertices, voxels |
| `meshes[].frac_rejected` | float | Pred: offsets rejected by `--jump`, over vertices with sheet. Ct midline: vertices whose move was ever reverted by the occupancy guard, over valid vertices. Face: offsets rejected by `--face-jump` or the support rule, over vertices with a target |
| `meshes[].frac_already_on` | float | Pred: vertices with a normal whose chosen offset was within 2 voxels, over vertices with a normal. Ct: first-iteration targets within 2 voxels, over valid vertices |
| `meshes[].abstained` | object | Face only: vertices that got no target, by reason: `no band`, `ambiguous or off the profile`, `too far`, `side not named`, `missing data`, `low contrast` |
| `meshes[].sham` | bool | `true` with `--sham` only |
| `meshes[].recto` | object | Ct only: `recto_iterations`, `recto_supported` (vertices that ever had a target), `recto_moved`, `recto_reverted` (reverted moves, summed over iterations), `recto_slope_limited` (vertices the slope limit ever clipped), `recto_mean_disp` and `recto_max_disp` (voxels), `mean_abs_step` and `mean_recto_gradient` (last iteration), `window` [lo, hi], `band` (isovalue), `min_edge` |
| `checks[]` | list | With `--check`: one per mesh |
| `checks[].reference` | str | `original` or `snapped` |
| `checks[].planted` | object | `shift`, `vary`, `grid_step` [rows, columns] (voxels), and the planted mesh's distance to the reference: `n`, `median`, `p90`, `frac_within_tol`, `max` |
| `checks[].recovery` | object | The snapped mesh's distance to the reference (same fields), plus `along_median` and `along_p90` (the part along the planting direction), `tol`, `min_frac`, `passed` |
| `checks[].control_shifted` | object | `shift_xyz` (the read shift, level-0 voxels), `control_shift`, the same distance fields, `recovered`, `caught` (true is good) |
| `checks[].control_empty` | object | `max_movement` (voxels), `caught` (true when nothing moved) |
| `checks[].passed`, `.why`, `.mesh` | bool, list of str, str | The verdict, its reasons, the mesh path |
| `passed` | bool | With `--check`: every mesh passed. Also written to `OUT/snap_check.json` when `--out` is given |

| Exit code | Meaning |
| --- | --- |
| `0` | Snapped and written, or with `--check`, every mesh passed |
| `1` | With `--check`, at least one mesh failed (recovery failed or a control recovered); or an error the command does not catch, with a Python traceback |
| `2` | Refused (`kit snap: ...` on stderr): a `SnapError`, a mesh or TIFF format error, an `OSError`, or a zarr store or read error; or a usage error from the argument parser |

## Failure modes

All refusals print `kit snap: MESSAGE` on stderr and exit 2.

| What you see | Why | What to do |
| --- | --- | --- |
| `face target must be recto, mid or verso, not 'X'` | `snap_face` was given an `opts["target"]` other than those three | Use `recto` (the band face toward the scroll axis), `mid` (its midline) or `verso` |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit snap: MESSAGE`, exit code 2 | Any refusal below, a mesh or TIFF format error, an `OSError`, or a zarr store or read error, with its message | Read the message; the rows below cover the module's own refusals |
| `kit snap needs numpy (pip install numpy, or run inside villa's environment)` | numpy is not installed (`--help` still works) | Install numpy |
| `give --volume ZARR (or set SURF_ZARR to the surface prediction zarr)` | No `--volume` and no `SURF_ZARR` | Pass `--volume` |
| `give --out DIR for the snapped meshes (or --check to test the snap without writing them)` | Neither `--out` nor `--check` | Add one |
| `two meshes share a folder name: [...]` | Two `MESH` folders with the same last name would write the same `OUT/<mesh>` | Rename or run them separately |
| `--sham writes the control mesh; --check plants and controls its own displacements` | `--sham` with `--check` (checked after `OUT` is created) | Run the check and the sham separately |
| `--source pred snaps to the nearest predicted sheet (--mode nearest)` | `--mode midline`, `face` or `recto` without `--source ct` | Add `--source ct`, or drop `--mode` |
| `--source ct takes --mode midline (RectoRefine), face or recto (the band face snap); RectoRefine's own recto-edge variant measured harmful and is not ported` | `--source ct --mode nearest` | Drop `--mode`, or pick `midline`, `face` or `recto` |
| `--mode recto snaps to the recto face; for TARGET use --mode face --face-target TARGET` | `--mode recto` with `--face-target mid` or `verso` | Use `--mode face --face-target TARGET`, or drop `--face-target` |
| `give the scroll axis (--umbilicus or --axis-point/--axis-dir) or --recto-sign, not both` | Face mode with both an axis and `--recto-sign` | Keep one: the axis when the mesh has a scroll axis |
| `the recto face is named by its side toward the scroll axis: give --umbilicus, --axis-point with --axis-dir, or --recto-sign` (or `the verso face ...`) | `--mode recto`, or `--mode face` with target `recto` or `verso`, with no axis and no `--recto-sign` | Give the umbilicus or the axis; for a mesh with neither, `--recto-sign` +1 when its normals point outward, or `--face-target mid` |
| Face mode report row with `frac_with_sheet` near 0, and `abstained` (with `--json`) mostly `side not named` | `--recto-sign 0`, or normals nearly tangent to the radial direction (below `--face-min-radial`) | Check the axis against the mesh, and the sign |
| `--windings names meshes inside one folder: give exactly one MESH folder with it` | `--windings` with several `MESH` folders | Give the one parent folder |
| `NAME: missing under FOLDER` on stderr, run goes on | A name in the windings file has no `x.tif` under the folder | Fix the name; that mesh is skipped |
| `no meshes` | No name in the windings file was found | Check the file and the folder |
| `[Errno 2] No such file or directory: ...` | A missing windings file, or another unreadable file | Fix the path |
| `PATH: no x.tif (not a tifxyz folder)` | A `MESH` path that is not a tifxyz folder | Point at the folder holding `x.tif` |
| `PATH: x, y and z tifs must be 2-D grids of one size` | The three TIFFs differ in shape or are not 2D | Repair the mesh |
| `PATH/meta.json: not JSON (...)` | A broken `meta.json`; nothing is written for that mesh | Fix or remove `meta.json` (a mesh without one gets a new one) |
| `MESH: the output would overwrite the input; give another --out` | `OUT/<mesh>` is the input folder | Choose another `--out` |
| `cannot open LOCATION: ...` | The volume is not a folder, not reachable, or has no zarr metadata at its root | Check the path or URL |
| `VOLUME: no level N (it has M)` | `--level` past the pyramid | Pick a level below M |
| `VOLUME level N: expected a 3-D array, shape [...]` | The level is not 3D | Point at a 3D volume |
| `VOLUME level 0: sharded arrays are not read here` | A sharded zarr v3 store read where only unsharded chunks are read | Use an unsharded copy of the volume |
| Other `VOLUME level N chunk ...: does not decode (...)` messages | A chunk codec kit cannot decode (blosc, zstd or lz4 without numcodecs) or a corrupt chunk | Install numcodecs; check the store |
| `--max-off must be at least 1` | `--max-off` 0 or less | Use 1 or more |
| `--umbilicus: umbilicus has no points` (or `--umbilicus has no points`) | An empty umbilicus file | Give a file with points |
| `--umbilicus: umbilicus line 1: expected z, y, x` | A path that is not a file is parsed as umbilicus text, or a text line without three values | Fix the path or the file |
| `json.decoder.JSONDecodeError: ...` and a traceback, exit code 1 | An umbilicus file that starts like JSON but is not valid JSON | Fix the JSON |
| `give --axis-point and --axis-dir together` | Only one of the two | Give both, or `--umbilicus` |
| `no vertex has a normal: nothing to check` | `--check` on a mesh with no vertex that has two valid neighbors in both directions (such as a 1 x 1 grid) | Check a real mesh |
| `NAME FAIL ... shifted control median M (NOT caught)`, exit code 1 | The snap pulls the mesh back even when the sheet is shifted, often because the input is not on a sheet | Rerun with `--check-reference snapped`; if it still fails, do not use the snap |
| `NAME FAIL ... residual median R ...`, exit code 1 | The snap does not recover the planted offset (as on the PHerc0841 meshes) | Do not use the snap on this mesh and volume |
| Report row with `frac_with_sheet` near 0 and `frac_snapped` 0 | No sheet within reach: wrong `--threshold`, a volume on another grid, or (ct) the band out of `--range` or on the other side | Check the volume's grid, the threshold, and the outward sense |
| A CT run over HTTPS that seems to hang | The band's chunks are read again and again through the 192-chunk cache | Copy the band of chunks to local disk first |

## How it works

**Technique A, onto the predicted sheet (`snap_pred`):**

1. Load the mesh; valid vertices have all three coordinates above -0.5 and finite.
2. Normals: central differences along rows and columns where both neighbors are valid, one-sided otherwise; n = cross(d/dcol, d/drow), normalized; vertices with no finite normal keep their place.
3. For each vertex with a normal, read 2K + 1 nearest-voxel values (K = `--max-off`, 15) at whole-voxel offsets -K to K along n, in batches of `--batch` points. Level coordinates are p / 2**level; a point outside [0, size - 0.5) or in a missing chunk reads 0.
4. Sheet = value at least `--threshold`. Of the runs of sheet samples, take the one whose center is nearest offset 0 (the first on a tie), and refine it with a parabola through the [1, 2, 1]-smoothed profile at the rounded center; the offset is the mean of the run center and the parabola's vertex, or the run center alone when the vertex is more than half a sample away.
5. Regularize on the grid: reject offsets more than `--jump` (6) voxels from the 5 x 5 nan-median; fill rejected and missing offsets by normalized convolution with a Gaussian of max(`--sigma`, 1) grid cells; smooth by normalized convolution with `--sigma` (1); clip to plus or minus K.
6. Move each vertex that has a normal and finite filled and final offsets by offset x n.

The Gaussian is scipy's `gaussian_filter` (mode reflect, truncate 4.0) re-implemented in numpy and bit-identical to scipy 1.18.1 on the tested cases. Deviations from his script, all deliberate (module docstring): volumes are read through `kit.vc3d_region.Volume` (local or HTTPS, zarr v2 or v3, false S3 404s retried) instead of a process pool, points are grouped by their full chunk index (his packed key can give two chunks one key once a grid is more than 300 chunks wide in x), and values keep the volume's dtype (his copy into uint8 read a uint16 multiple of 256 as background). The whole pipeline equals his bit for bit on rough synthetic fixtures (`HisPipelineTest`).

**Technique B, onto the CT band midline (`snap_midline`):**

1. Triangulate the grid (two triangles per cell, each kept when its three vertices are valid) and take its one-ring edges.
2. The contrast window is `--window`, or `stretch_window` of the CT at the input vertices (1st to 99th percentile; a 256-bin rule for uint8). band = lo + `--band-frac` x contrast; min_edge = `--min-edge-frac` x contrast.
3. Each outer iteration (`--outer-iters`, 4): area-weighted normals; the outward line blends the radial direction from the axis with the normal flipped outward (`--normal-blend` 0.85), or is the normal alone with no axis.
4. Along the line, samples from -`--range` to +`--range` (3 voxels) every `--sample-step` (0.25): the rising crossing of the band with an edge of at least min_edge, scored by edge strength minus `--distance-bias` (4) per voxel of distance. From the best one, walk outward up to `--max-thick` (6 voxels) to the falling crossing; the target is the midpoint. No falling crossing, or a band thinner than `--min-thick` (1), means abstain.
5. Solve one displacement per vertex along its line with `--inner-iters` (48) Jacobi sweeps of sum w (d - target)^2 + mu sum (d_i - d_j)^2: weight `--data-weight` (12) x (0.35 + 0.65 x confidence) for a target, `--anchor-weight` (24) toward the input position otherwise, each value clipped so neighbors differ by at most `--max-slope` (0.55) x the original edge length.
6. Take `--damping` (0.70) of the move, at most `--max-step` (0.85) voxels, the total from the input capped at `--max-total` (3); revert a move that lands within `--occ-thresh` (0.9) voxels of another part of the input mesh (an input vertex farther than `--local-r`, 2, from the vertex's input position and outside its one-ring).
7. Stop when nothing moved or the mean step is below `--tol` (0.02).

Defaults are `RectoRefineOpts_default` (`recto_refine.c` lines 29 to 61) and `scroll_snap`'s pass-2 settings (`MIDLINE_DEFAULTS`). On synthetic bands, folds and volume edges the port agreed with `recto_refine.c`, built with a stub sampler over the same voxels, within 2e-5 voxels (module docstring; the First Letters guide gives 1.1e-5 after review); the C values are pinned in `MidlineRulesTest`. Deviations: the tifxyz grid instead of an OBJ, an umbilicus taken as vertical at each vertex, a hash grid instead of a KD-tree for the occupancy guard, a missing chunk read as 0, numpy instead of OpenMP.

**Technique D, onto a face of the CT band (`snap_face`):**

1. Normals as in technique A; vertices without one keep their place.
2. The side: with an axis, the radial direction at each vertex; a vertex whose \|normal . radial\| is below `--face-min-radial` (0.3) has no named side and abstains, unless the target is `mid`. With `--recto-sign`, its sign for every vertex.
3. A trilinear CT profile along the normal from -`--face-half` to +`--face-half` (12 voxels) every `--face-step` (0.25).
4. Bands: `kit.snaptruth.sheet_faces` on each profile (level `--face-level-frac`, 0.5, between the 10th and 90th percentiles after light smoothing), or with `--face-level` the runs at or above that one level. The nearest band is taken; it abstains when ambiguous (a second band at most 2 voxels farther than the nearest), running off the profile, below the contrast floor (`--face-min-contrast`, or `--face-contrast-frac` 0.25 of the mesh's 1st to 99th percentile window), or more than `--face-max-move` (4) voxels away.
5. The target is the recto face, the verso face or the midpoint of the two faces.
6. Regularize on the grid: drop an offset with fewer than `--face-min-support` (3) measured offsets in its 5 x 5 window; reject offsets more than `--face-jump` (2) from the 5 x 5 nan-median; fill holes by normalized convolution with a Gaussian of 1 grid cell where enough neighbors were measured; with `--face-sigma` above 0, smooth as technique A does.
7. Move each supported vertex by offset x n.

`--face-per-vertex` turns off steps 6's support rule and jump rejection. The code's comment records why: stored meshes wander off the sheet by more than 2 voxels between neighboring vertices, so true offsets look like outliers to the 5 x 5 rule (Interpretation). [labelsnap](labelsnap.md) uses the per-vertex form. The module docstring warns that where bands are only a few voxels thick with narrow gaps the nearest band is often ambiguous, so `--check` may fail on a real mesh although every control is caught; read its recovery share, not only its verdict.

**Technique C, the self-check (`self_check`):** plant `planted_field` (the shift plus vary x sin x cos over the grid, wavelengths at least the mesh's extent and long enough to keep the slope at most `CHECK_MAX_SLOPE` = 0.05) along the normals (pred and face) or outward lines (ct midline); snap; compare with the reference. The shifted control snaps the same displaced mesh against the volume read at p + v, v = -sign(shift) x `--control-shift` x the mean unit planting direction, so the sheet appears on the planted side; the empty control reads 0 everywhere.

**The sham (`sham_of`):** 2 x input minus snapped, per coordinate.

**`kit.snaptruth`:** (1) `register_shift` tries shifts from -`s_max` to `s_max` (4) every `step` (0.05), scores each by the mean per-line normalized cross correlation over the masked samples (leaving out the band |t| < E around the label means the sheet being snapped to never places the truth), and refines the best by a parabola. (2) `bands` smooths a profile (`FACE_DEFAULTS`: `sigma` 0.5 t units), sets a level halfway (`level` 0.5) between its 10th and 90th percentiles (`lo_pct`, `hi_pct`), closes dips shorter than `fill` (1.0), drops runs shorter than `min_band` (1.0), and finds each band's faces at sub-sample crossings; `sheet_faces` takes the band nearest the label, calls it ambiguous when a second is within `ambiguous` (2.0) farther, and flags a split when the finer profile (`split_sigma` 0.25) dips below the level for at least `split_len` (1.0) inside it. (3) `gains` is |error before| minus |error after| per vertex; `site_bootstrap` resamples sites (10,000 draws) and `classify` names the result against a margin (such as 0.1 voxels). [labelsnap](labelsnap.md) and [finesnap](finesnap.md) use face smoothing sigma 1.

## Cost and time

Measured 2026-10-16 in a 4-core Intel Xeon cloud container (lscpu: 2.80 GHz) while it was shared (load average 10 to 24), on synthetic local zarrs, through `python -m kit snap` in a child process:

| Run | Mesh | CPU time | Wall time | Peak memory |
| --- | --- | --- | --- | --- |
| Pred snap | 12 x 12 (144 vertices) | 0.41 s | 1.5 s | 53 MB |
| Ct midline snap | 9 x 9 (81 vertices) | 0.55 s | 2.3 s | 57 MB |
| Pred snap | 250 x 250 (62,500 vertices), volume 64 x 512 x 512 | 4.2 s | 16.8 s | 367 MB |
| Pred `--check` | same | 7.5 s | 32.1 s | 408 MB |
| Pred `--check --check-reference snapped` | same | 11.7 s | 20.9 s | 408 MB |
| Ct midline snap | same, 1 voxel below the sheet center | 36.2 s | 164.9 s | 899 MB |

On real meshes (PHerc0841 w00 and ag896, 9 Oct 2026, 4 shared cloud cores): pred `--check` 88 to 132 s and 1.6 to 1.7 GB with the prediction read over HTTPS; ct `--check` 101 to 182 s and 0.7 GB from a local copy of the band (1,604 chunks, 3.2 GB, fetched in 81 s with 8 parallel requests); over HTTPS the w00 ct check did not finish in 50 minutes.

It needs no GPU and rents nothing. A batch of meshes that would take over 10 minutes on a laptop goes to Hugging Face (the where-jobs-run rule, hard rule 11).

## For agents

- **Command:** first `python -m kit snap MESH --volume PRED.zarr --check --check-reference snapped --json`; only if that passes, `python -m kit snap MESH --volume PRED.zarr --out OUT --json`, and for the control arm the same with `--sham` and another `--out`. CT midline: add `--source ct --umbilicus U.json` and a local CT copy as `--volume`. CT recto face: add `--source ct --mode recto --umbilicus U.json` instead, or use `python -m kit labelsnap snap` for labels.
- **Parse:** with `--check`, top-level `passed`, and per mesh `checks[].recovery.median`, `.frac_within_tol`, `checks[].control_shifted.caught`, `checks[].control_empty.caught` and `checks[].why`. For a snap, `meshes[].frac_with_sheet`, `frac_snapped`, `median_abs_off`, `frac_rejected`, in ct midline mode `meshes[].recto.recto_supported`, and in face mode `meshes[].abstained`.
- **Rerun:** Safe for the inputs, which are never changed. A rerun to the same `--out` replaces `OUT/<mesh>/` and `snap_report.json` and appends rows to `snap_report.tsv`; `--check --out` replaces `snap_check.json`.
- **Success:** Exit code 0. With `--check`, `passed` true, which needs recovery passed and both controls caught.
- **Not a pass:** a snap whose check did not pass on the same mesh and volume; `frac_snapped` 1.0 alone (it counts vertices filled in from neighbors); a check passed with the original reference on a mesh not on a sheet, or with the shifted control `NOT caught`; a passing unit test or synthetic check (the real PHerc0841 meshes failed); any ink gain of a snapped render not compared with its sham.
- **Go-ahead:** Nothing for local runs and reads of the public bucket.
- **Never:** Call a snapped mesh "on the sheet" or better without its check and truth numbers; call an ink map rendered on it a reading or say letters were found; turn on `render.snap` by default.

## Tests

```bash
python -m unittest tests.test_snap tests.test_snap_face tests.test_snaptruth tests.test_snap_support -v
```

`tests/test_snap_face.py` covers technique D on synthetic bands: faces and midline of one band, `recto_sign` without an axis, a global level, two bands about as near, a far band and a bad target, the lone-hop rejection and hole filling, the per-vertex form, noise with no sheet, tangent normals, smoothing and invalid vertices. `tests/test_snap.py` uses synthetic OME-Zarr v2 volumes and tifxyz grids in temporary folders: `--help` without numpy; the numpy Gaussian against scipy bit for bit; `nanmedian_filter` bit for bit against `np.nanmedian`; the vectorized run choice against his loop; sheet centers for odd and even thickness, sub-voxel starts, curved sheets, rejection of a second sheet, hole filling, vertices with no sheet staying put, his level-1 coordinates and `--centres`; files, holes, bbox and the `meta.json` record; the sham; the windings layout and appended report; command-line refusals; the midline snap moving onto the band smoothly, abstaining out of range, its sign, holes, window rule and occupancy guard; the check passing on the sheet, failing off it and failing when a cheating snap passes the controls, and its exit codes; his whole pipeline bit for bit at levels 0 and 1 (`HisPipelineTest`, needs scipy); and RectoRefine rules pinned to the compiled C's values (`MidlineRulesTest`). `tests/test_snaptruth.py` covers smoothing, shifted reads, registration recovering a planted shift and refusing structureless profiles, faces, ambiguity, splits and gaps, gains, a random-sign control and the bootstrap classes. `tests/test_snap_support.py` covers the box reads, nearest samples and umbilicus files underneath. The tests skip without numpy (and the scipy cross-checks without scipy). They do not use real scroll data, remote volumes or sharded stores.

## History

- 2026-10-29: on public `main` with kit labelsnap and kit finesnap (on top of `afcc05a`); the code is the AutoPipeline 0.1.10 copy (`eea2df5`).
- 2026-10-21: `snap_face` also returns `detail`: per-vertex grids of the vertex's own measured offset, its reason (`FACE_REASONS`), the profile contrast, band thickness and band separation, with the contrast floor and thickness cap; existing outputs are unchanged. [labelsnap](labelsnap.md) builds its abstain mask and confidence on them (`eea2df5`).
- 2026-10-16: technique D with a command line: `--source ct --mode recto` and `--mode face --face-target recto|mid|verso`, `--recto-sign`, the `--face-*` options and a default `--check` plant of 2 voxels for it; `nanmedian_filter` sorts the window stack itself, with the same values bit for bit (`eea2df5`).
- 2026-10-14: `kit/snap.py` and its tests released publicly inside AutoPipeline (public Scrolls commit `faada83`, branch `submission/progress-2026-10`); each AutoPipeline fix release carries them.
- 2026-10-09: `--sham` added, the control arm for snapped renders; the same day `--check` was run on the PHerc0841 meshes and failed in both modes (`faada83`).
- 2026-10-08: first version: his prediction snap, the RectoRefine midline port, and `--check` (`faada83`).

## Related

- [labelsnap](labelsnap.md): the band face snap in its per-vertex form, with an abstain mask, a surface label and a review queue; measured against independent scans.
- [finesnap](finesnap.md): the same on a finer registered scan of the same scroll.
- [snapped-labels](snapped-labels.md): the released dataset of snapped labels.
- [autopipeline](autopipeline.md): `render.snap`, which runs the check and then the snap or sham.
- [Bars plan](../plans/2026-10-09-autopipeline-bars.md): why a snapped render needs its sham.
