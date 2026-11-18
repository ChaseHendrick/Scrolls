# scrollsim2: a full-scale synthetic scroll with exact truth

ScrollSim v2 renders a synthetic rolled, pressed and crushed papyrus scroll at full scale (100 plus windings), block by block and in parallel, as an OME-Zarr pyramid with an exact winding label volume and optional tifxyz surfaces.

| Field | Value |
| --- | --- |
| Id | `scrollsim2` |
| Status | Experimental |
| Kind | kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit.scrollsim2 make`, `estimate`, `pyramid`, `verify`, `publish`, `info`; library `from kit import scrollsim2` |
| Code | `kit/scrollsim2.py` |
| Tests | `tests/test_scrollsim2.py` |
| Needs | Python 3.10 or newer, numpy, scipy (ndimage), zarr 3 for `make` (it writes zarr format 2); all in `pip install -e ".[maps]"`. No scroll data |
| Runs on | CPU, any core count (forked workers, at most 16 by default). Smoke scroll (64 x 208 x 208, 4.8 turns): 7.2 s wall on 4 workers, 98 MB peak per process (measured 2026-11-18, 4-core cloud container) |
| Network | None |
| Writes | `make OUT`: `OUT/ct.zarr`, `OUT/truth/labels.zarr`, `OUT/truth.json`, `OUT/truth/make-key.json`, `OUT/truth/done.txt`, and with `--surfaces` `OUT/truth/surfaces/spiral-center/` and `spiral-recto/`. `publish SRC DST`: a copy in `DST`. `pyramid OUT`: rewrites CT levels 1 and up |
| Go-ahead | Not needed on a local CPU. A rented run follows hard rule 11 |
| Released | Public `main` since 2026-11-18 |
| Checked | 2026-11-18 against commit `424fb42` |

## What it does

Tracers and winding tools are hard to score on real scrolls: the true winding of every voxel is unknown. ScrollSim v2 makes a synthetic scroll where it is known exactly. It rolls one sheet into a spiral around the z axis, presses neighboring windings together in smooth contact zones, crushes the roll along one axis and bends it with a smooth displacement field, then renders a CT-like volume: two fiber plies per winding, holes, delamination, blur, a slow brightness drift, optional rings and noise, 8 bits.

What works today:

- **Full-scale geometry.** A whole cross-section of about 125 windings (the `pilot` preset, 1,024 x 1,728 x 3,264 voxels). The turn just inside each voxel is found by binary search, so a voxel costs about log2(turns) lookups instead of one per turn; a test holds it equal to the slow all-turns lookup. Fiber textures come from small periodic tiles, so a sheet millions of voxels long fits in memory. A fixed crush axis (`alpha` 0) lets the box be about half as tall as wide.
- **Block-by-block rendering.** Every block renders with a halo that covers each filter, and noise is a hash of the voxel's position, so any block size gives the same volume bit for bit (test). Blocks that hold no sheet are detected and skipped. Workers write chunk-aligned blocks in parallel, each write is checked on disk, and a stopped run resumes where it left off.
- **Exact truth.** `truth/labels.zarr` holds every sheet voxel's winding number (plus 1; 0 is air), numbered from the center line with one step across a fixed half-plane. `--surfaces` writes the whole sheet's center and recto surfaces as tifxyz, each with `winding.npy`, the winding number of every vertex. `truth.json` records the parameters, turns, center line and render timings, and the same parameters always rebuild the same scroll.

Ink is off in this release: the volume holds no ink and the label volume carries windings only.

![Synthetic demo: a ScrollSim v2 slice of about 21 windings, gray CT on the left and the same slice tinted by exact winding number on the right](../assets/scrollsim2/scrollsim2-slice.png)

*Synthetic demo: one slice of a 96 x 640 x 640 ScrollSim v2 scroll and its exact winding labels. No scan data.*

![Synthetic demo: one seed three ways, a round spiral, the same spiral with contact zones, and the roll crushed and bent](../assets/scrollsim2/scrollsim2-stages.png)

*Synthetic demo: the same seed without contacts, with contact zones (`contact_share` 0.45), and crushed and bent (`squash` 0.5, `warp` 5). The color step on the right of each spiral is where winding numbers go up by one, across the half-plane on the +x side of the center line. No scan data.*

![Synthetic demo: the whole sheet's center surface in 3D with one quarter cut away, colored by winding number](../assets/scrollsim2/scrollsim2-surface.png)

*Synthetic demo: the center surface `make --surfaces` writes as tifxyz, colored by its exact winding number. No scan data.*

![Synthetic demo: a pass through z, CT beside its winding labels](../assets/scrollsim2/scrollsim2-zscroll.gif)

*Synthetic demo: a pass through z of the same scroll. No scan data. All four are made by `python scripts/media/scrollsim2_demo.py --work WORK --out-dir docs/assets/scrollsim2`.*

What it is not: a calibrated stand-in for a real scroll. A score on its volumes is model output on synthetic data and says nothing about a real scroll. Never call an ink map made on it a reading.

## Realism: in progress

The volumes do not yet look or score like real CT. The next release adds realism, with no date promised:

- **S2, real texture.** Copy real CT texture from Vesuvius Challenge open-data scans into the synthetic sheets and the gaps between them.
- **S3, more physics.** Add more physical detail, such as compression and delamination that behave the way they do in carbonized scrolls.
- **Goal: calibration.** Tune and check the simulator so that real ink readers and tracers score on it as they do on real scrolls. Until that check passes, a ranking of methods on ScrollSim v2 volumes is not evidence about their ranking on real scrolls.

## When to use it

- To test a tracer, a winding tool or a surface pipeline end to end on a volume whose windings and surfaces are known exactly.
- To check that a pipeline handles a full-scale volume (OME-Zarr levels, chunking, 100 plus windings) before it meets real data.
- To estimate a full render's time and memory before you start it (`estimate`).

Do not use it:

- To claim anything about a real scroll, or to rank methods for real scrolls: use published labels and the scorers in [auc](auc.md).
- To train a model meant for real CT: it is not calibrated yet (see above).
- For ink: ink is off in this release.

## Quick start

```bash
python -m kit.scrollsim2 make SIM --preset smoke --workers 4 --block 64 --chunk 64 --levels 2 --surfaces
python -m kit.scrollsim2 info SIM
```

- `SIM`: a new empty folder.

On 2026-11-18 in a 4-core container `make` printed one line of JSON with `"complete": true`, `turns` 4.77, `pressed_share` 0.2898, `surface_residual_vox` 2.8e-14 and `render` blocks 16, air blocks 2, seconds 6.8. It worked when it exits 0, `SIM/ct.zarr/0` has shape 64 x 208 x 208 and `SIM/truth/labels.zarr/0` holds several winding ids.

## Tutorials

Every command below was run on 2026-11-18 in a 4-core Linux container with Python 3.13, from a fresh clone of `main`; the printed numbers are from that run.

### Make your first synthetic scroll in 2 minutes

```bash
git clone --depth 1 https://github.com/ChaseHendrick/Scrolls.git
cd Scrolls
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[maps]"
python -m kit.scrollsim2 make sim --preset smoke --workers 4 --block 64 --chunk 64 --levels 2 --surfaces
python -m kit.scrollsim2 info sim
```

`make` took about 6 s and printed `PROGRESS 16/16 blocks` on stderr; `info` prints `truth.json` without the center line. Then look inside with numpy, zarr and tifffile (all in `.[maps]`):

```bash
python - <<'EOF'
import numpy as np, tifffile, zarr
ct = zarr.open_group("sim/ct.zarr", mode="r")
labels = zarr.open_group("sim/truth/labels.zarr", mode="r")["0"]
print([ct[k].shape for k in sorted(ct.array_keys())])
print("windings in slice 32:", np.unique(labels[32])[1:].tolist())
tifffile.imwrite("slice-32.tif", ct["0"][32])
tifffile.imwrite("labels-32.tif", labels[32])
EOF
```

It printed `[(64, 208, 208), (32, 104, 104), (16, 52, 52)]` and `windings in slice 32: [1, 2, 3, 4, 5, 6]`. Labels are winding number plus 1 (0 is air). Open the two TIFFs in any image viewer, or `sim/ct.zarr` in an OME-Zarr viewer such as napari or Neuroglancer (viewers not tested here).

### Test a tracer against exact truth

The truth is the label volume, `sim/truth/labels.zarr/0`, and with `--surfaces` the whole sheet as tifxyz in `sim/truth/surfaces/spiral-center/` and `spiral-recto/`, each with `winding.npy` (the winding number of every vertex). Check a surface with the [tifxyz](tifxyz.md) tool:

```bash
python -m kit tifxyz check sim/truth/surfaces/spiral-center
```

It reports 0 holes and 0 folds, and flags about 36 percent of nodes as stretched: the grid is regular on the rolled sheet, and the crush stretches it in the volume. That is expected here, not an error.

To score a tracer, compare its winding numbers with the labels. Winding agreement below is the share of random voxel pairs, both on a sheet in the tracer's output and in the truth, whose predicted winding difference equals the true difference, so a tracer's own numbering offset does not matter. The shuffled control must score far lower. Save this toy tracer as `toy_tracer.py`; it sees only the CT and numbers each sheet voxel by how many sheets a straight ray from the center line crosses to reach it:

```python
"""A toy tracer and its winding agreement against ScrollSim v2's exact labels, on one z slice."""
import json
import sys

import numpy as np
import zarr
from scipy import ndimage

sim, z = sys.argv[1], int(sys.argv[2])
ct = np.asarray(zarr.open_group(f"{sim}/ct.zarr", mode="r")["0"][z]).astype(float)
truth = np.asarray(zarr.open_group(f"{sim}/truth/labels.zarr", mode="r")["0"][z]).astype(int) - 1   # -1 is air
cl = np.array(json.load(open(f"{sim}/truth.json"))["center_line"])
cx, cy = np.interp(z, cl[:, 2], cl[:, 0]), np.interp(z, cl[:, 2], cl[:, 1])

# The toy tracer sees only the CT: smooth, threshold halfway between the median and the bright sheets, then number each sheet voxel
# by how many sheets a straight ray from the center line crosses to reach it.
img = ndimage.gaussian_filter(ct, 1.0)
lo, hi = np.percentile(img, [50, 98])
sheet = img > (lo + hi) / 2
ys, xs = np.nonzero(sheet)
t = np.linspace(0, 1, 400)[:, None]
py = np.clip(np.rint(cy + t * (ys - cy)).astype(int), 0, sheet.shape[0] - 1)
px = np.clip(np.rint(cx + t * (xs - cx)).astype(int), 0, sheet.shape[1] - 1)
on = sheet[py, px]
pred = (on[1:] & ~on[:-1]).sum(0)                 # rising edges along the ray: sheets entered on the way out

# Winding agreement: for random pairs of voxels that both tools call sheet, how often the predicted winding
# difference equals the true one. Offsets do not matter, only relative windings. The control shuffles the
# predictions and must score far lower.
ok = truth[ys, xs] >= 0
p, w = pred[ok], truth[ys, xs][ok]
rng = np.random.default_rng(0)
i, j = rng.integers(0, len(p), (2, 200000))
agree = float(np.mean((p[i] - p[j]) == (w[i] - w[j])))
q = rng.permutation(p)
control = float(np.mean((q[i] - q[j]) == (w[i] - w[j])))
print(json.dumps({"z": z, "sheet_voxels": int(len(p)), "winding_agreement": round(agree, 3),
                  "shuffled_control": round(control, 3)}))
```

```bash
python toy_tracer.py sim 32
python -m kit.scrollsim2 make sim-apart --preset smoke --set contact_share=0 --workers 4 --block 64 --chunk 64 --levels 1
python toy_tracer.py sim-apart 32
```

| Scroll | Winding agreement | Shuffled control |
| --- | --- | --- |
| `sim` (contact zones on, the default) | 0.466 | 0.160 |
| `sim-apart` (`contact_share` 0) | 0.792 | 0.169 |

Where windings touch, the toy tracer sees one sheet instead of two and loses count, so it scores much lower with contacts on. Put your own tracer's winding numbers in place of `pred` to score it the same way. These are scores on synthetic data (Model output about the simulator), not evidence about any real scroll.

### Render at full scale on many CPUs

Estimate first, then render with as many workers as you have cores (at most 16 by default; more rarely helps, since rendering is bound by memory bandwidth). `--block` must be a multiple of `--chunk`.

```bash
python -m kit.scrollsim2 estimate --set 'shape=[128,768,768]' --workers 4 --sample 2
python -m kit.scrollsim2 make big --set 'shape=[128,768,768]' --workers 4 --block 128 --chunk 64 --levels 3 --max-blocks 8
echo $?
KIT_JOB_DEADLINE=$(( $(date +%s) + 15 )) KIT_JOB_SPARE_S=5 \
  python -m kit.scrollsim2 make big --resume --set 'shape=[128,768,768]' --workers 4 --block 128 --chunk 64 --levels 3
python -m kit.scrollsim2 make big --resume --set 'shape=[128,768,768]' --workers 4 --block 128 --chunk 64 --levels 3
python -m kit.scrollsim2 verify big
```

- `estimate` printed 27.76 turns, 36 blocks, 28 with sheet, 5.8 s per sheet block and `wall_seconds_at_workers` 42.
- `--max-blocks 8` stopped after 8 of 36 blocks with `"stopped": "max_blocks"` and exit code 75: stopped early, resume it.
- With a deadline 15 s away and 5 s kept spare, the resumed run stopped by itself at 16 blocks with `"stopped": "deadline"` and exit 75. In a batch job, set `KIT_JOB_DEADLINE` to the epoch second the job's timeout ends, so the run stops cleanly and the next job resumes.
- The last resume rendered the rest, built the pyramid and printed `"complete": true` with `verified.ok` true; `verify` printed `"ok": true`. `--resume` needs the same parameters, block, chunk and levels: anything else is refused.

The `pilot` preset (1,024 x 1,728 x 3,264, about 125 windings) is a full cross-section; estimate it before you start it (see Cost and time).

### Publish a scroll to a bucket or Hugging Face dataset

Render to a local disk, then copy with `publish`. It copies with plain file writes, removes any `.partial` file a network mount left behind, and verifies every chunk at the destination:

```bash
python -m kit.scrollsim2 publish sim mounted-bucket/scrollsim2/sim
cp -r sim/truth/surfaces mounted-bucket/scrollsim2/sim/truth/
```

`publish` printed `"ok": true` and copied `ct.zarr`, `truth/labels.zarr` and `truth.json`; it does not copy the surfaces, hence the `cp`. `mounted-bucket/` stands for any mounted bucket path; here it was a local folder. If a copy through a mount loses chunks, `publish SRC DST --levels 1 2` copies just those levels again.

To put it in a Hugging Face dataset, upload the published folder with the `hf` command line (`pip install huggingface_hub`, then `hf auth login`):

```bash
hf upload USER/DATASET mounted-bucket/scrollsim2/sim sim --repo-type dataset
```

- `USER/DATASET`: your dataset repository.

The upload itself was not run here (it publishes, and needs your account); `hf upload --help` confirms the arguments. Say in the dataset card that the volumes are synthetic, made by ScrollSim v2, and are not real CT.

## Checks and controls

The tests are the controls; each can fail:

- The binary-search turn lookup equals the reference all-turns lookup: same labels, density and angles to 1e-9 on three full slices.
- Rendering whole versus in eight blocks gives identical CT and labels, with noise, rings, correlated noise and the edge filter on.
- An air block skipped as air equals the same block rendered in full.
- Two `make` runs with different block sizes and worker counts give identical pyramids; a run stopped after 7 blocks, then stopped by a deadline, then resumed, equals one uninterrupted run.
- A chunk file that never lands on disk is caught by `verify` and by the write check, and `pyramid` repairs a lost pyramid chunk.
- Surface vertices map back onto the rolled sheet with a residual under 1e-6 voxels.

Scope: these are correctness checks on the simulator's own truth, geometry and storage. No realism or calibration check has run, so nothing here says how close a volume is to real CT.

Claim label: None (a simulator; its output is synthetic data, and scores on it are Model output about the simulator only).

## Commands and options

### `python -m kit.scrollsim2 make`

```text
usage: python -m kit.scrollsim2 make [-h] [--levels LEVELS] [--chunk CHUNK]
                                     [--surfaces] [--resume]
                                     [--max-blocks MAX_BLOCKS]
                                     [--order {zyx,middle}]
                                     [--preset {pilot,smoke}] [--set SET]
                                     [--seed SEED] [--workers WORKERS]
                                     [--block BLOCK]
                                     out
```

| Option | Meaning |
| --- | --- |
| `out` | a new empty folder (or one to resume) |
| `--levels L` | CT pyramid levels above 0 (default 5, 0 to 8) |
| `--chunk C` | zarr chunk edge, voxels (default 128) |
| `--surfaces` | also write the center and recto surfaces as tifxyz |
| `--resume` | finish a stopped run with the same settings |
| `--max-blocks N` | stop after N new blocks (a timing probe; exit 75) |
| `--order zyx|middle` | block order: index order, or blocks nearest the center first |
| `--preset NAME` | `smoke` or `pilot` |
| `--set KEY=VALUE` | override one parameter (repeatable; VALUE is JSON) |
| `--seed N` | the seed, same as `--set seed=N` |
| `--workers N` | forked worker processes (default: CPU count, at most 16) |
| `--block B` | block edge, voxels, a multiple of `--chunk` (default 128) |

### `python -m kit.scrollsim2 estimate`

```text
usage: python -m kit.scrollsim2 estimate [-h] [--sample SAMPLE]
                                         [--preset {pilot,smoke}] [--set SET]
                                         [--seed SEED] [--workers WORKERS]
                                         [--block BLOCK]
```

| Option | Meaning |
| --- | --- |
| `--sample K` | sheet blocks to time (default 4) |
| `--preset NAME` | as make |
| `--set KEY=VALUE` | as make |
| `--seed N` | as make |
| `--workers N` | workers the wall time is scaled to |
| `--block B` | block edge, as make |

### `python -m kit.scrollsim2 pyramid`

```text
usage: python -m kit.scrollsim2 pyramid [-h] [--workers WORKERS] sim
```

| Option | Meaning |
| --- | --- |
| `sim` | a complete make folder |
| `--workers N` | forked workers |

### `python -m kit.scrollsim2 verify`

```text
usage: python -m kit.scrollsim2 verify [-h] sim
```

| Option | Meaning |
| --- | --- |
| `sim` | a make folder |

### `python -m kit.scrollsim2 publish`

```text
usage: python -m kit.scrollsim2 publish [-h] [--levels LEVELS [LEVELS ...]]
                                        [--no-labels]
                                        src dst
```

| Option | Meaning |
| --- | --- |
| `src` | a finished local make folder |
| `dst` | where to copy it, for example a mounted bucket |
| `--levels L ...` | copy only these CT levels (a pyramid repair) |
| `--no-labels` | skip the label volume |

### `python -m kit.scrollsim2 info`

```text
usage: python -m kit.scrollsim2 info [-h] sim
```

| Option | Meaning |
| --- | --- |
| `sim` | a make folder; prints truth.json without its center line |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `SimError()` | | | The error every refusal raises (a `ValueError`) |
| `params(over=None, preset=None)` | dict of every parameter | `SimError` on an unknown key or preset or a value out of range | DEFAULTS, then the preset, then OVER |
| `hashed_normal(seed, z0, z1, y0, y1, x0, x1, salt=HASH_SALT['noise'])` | float32 array (z, y, x) | | Standard normal noise on the box, a function of each voxel's position and the seed only |
| `Roll(p)` | object | `SimError` when the box holds less than two windings | The sheet geometry: radius, thickness, contacts, delamination, holes and displacement fields; `voxels_all_turns(out)` is the slow reference lookup |
| `Scroll2(p)` | object | `SimError` as `params`, or when the box is too short in y for a fixed crush | Full-scale lookups and rendering: `voxels(out)`, `scan_block(z0, z1, y0, y1, x0, x1)` returns (CT uint8, labels uint16, air flag), `surface(step, which)` |
| `make(out, over=None, preset=None, workers=1, block=128, levels=5, chunk=128, surfaces=False, progress=print, resume=False, max_blocks=None, environ=None, order='zyx')` | dict (as `truth.json`) | `SimError` on a non-empty OUT without `resume`, a block that is not a multiple of the chunk, other parameters on resume, or missing chunks | Renders one scroll; see Outputs |
| `estimate(over=None, preset=None, workers=1, block=128, sample=4, seed=0, progress=print)` | dict | `SimError` as `params` | Times SAMPLE sheet blocks on one core and scales by the sheet block count over WORKERS |
| `verify(out)` | dict with `ok` | | Every CT chunk of every level on disk, no `.partial` file |
| `pyramid(out, workers=1)` | dict as `verify`, plus `seconds` | `SimError` when level 0 is incomplete | Rebuilds CT levels 1 and up from level 0 |
| `publish(src, dst, levels=None, labels=True)` | dict as `verify`, plus `copied_files` | `SimError` when SRC has no `ct.zarr` | Plain file copy (no write-then-rename), clears `.partial` files, then verifies DST |
| `write_surface(folder, surf, name)` | the folder | | One tifxyz surface and its `winding.npy` |
| `code_sha256()` | hex string | | sha256 of `kit/scrollsim2.py`; `make` refuses to resume a folder made by other code |
| `default_workers()` | int | | The CPU count, at most `MAX_WORKERS` (16) |
| `single_thread_blas(environ=None)` | None | | Sets `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and `MKL_NUM_THREADS` to 1 where unset; `main` calls it first |
| `main(argv=None)` | exit code | `SystemExit` with `scrollsim2: MESSAGE` on a `SimError` | The command line |

## Inputs

None from disk. Parameters come from `--preset` (`smoke`, 64 x 208 x 208; `pilot`, 1,024 x 1,728 x 3,264 with `alpha` 0), then `--set KEY=VALUE` (values parsed as JSON), then `--seed`. Lengths are output voxels. The main keys:

| Key | Default | Meaning |
| --- | --- | --- |
| `shape` | `[256, 512, 512]` | z, y, x of the volume |
| `pitch`, `pitch_sd` | 14, 0.12 | winding spacing where windings lie apart, and its relative smooth variation |
| `thick`, `thick_sd` | 7, 0.15 | winding thickness (two plies) and its variation |
| `contact_share`, `zone`, `touch` | 0.45, 150, 0.85 | share of interfaces pressed together, the contact field's correlation length, spacing at full contact as a share of thickness |
| `delam`, `holes` | 1.5, 0.02 | largest ply separation, share of the sheet missing |
| `squash`, `alpha` | 0.5, -1 | minor over major axis of the crush, and its angle (below 0: drawn from the seed) |
| `warp`, `warp_corr` | 5, 96 | rms and correlation length of the smooth bend |
| `blur`, `psf_z`, `psf_xy` | 0.9, 0, 0 | point spread (sigmas, combined in quadrature) |
| `noise`, `noise_corr`, `edge`, `edge_sigma`, `rings`, `bias` | 3, 0, 0, 1.5, 0, 0.08 | noise sd (gray levels), its correlation, phase-edge gain, rings, slow drift |
| `air`, `bright` | 60, 150 | gray level of air and of a ply's peak |
| `supersample` | 1 | sub-samples per axis averaged into each voxel |
| `seed` | 0 | every random field comes from it |

The defaults are set for about 8 um per voxel; they are not a calibration.

## Outputs

`make` prints one line of JSON (the `truth.json` document without its center line) and writes:

- `OUT/ct.zarr`: OME-Zarr 0.4 multiscales, zarr format 2, uint8, levels 0 to `--levels`, each half the last.
- `OUT/truth/labels.zarr/0`: uint16, winding number plus 1 per voxel, 0 for air.
- `OUT/truth/surfaces/spiral-center/` and `spiral-recto/` (with `--surfaces`): tifxyz (`x.tif`, `y.tif`, `z.tif`, `meta.json`) and `winding.npy`.
- `OUT/truth/make-key.json` and `OUT/truth/done.txt`: what `--resume` checks and the blocks already written.

| Field | Type | Meaning |
| --- | --- | --- |
| `complete` | bool | every block written, pyramid built and verified |
| `turns` | float | turns of the sheet |
| `pressed_share` | float | share of the sheet past its first turn that is pressed to a neighbor |
| `sheet_length_vox` | float | length of the sheet, voxels |
| `params` | object | every parameter used |
| `center_line` | list | (x, y, z) points of the roll's axis in the output frame (in `truth.json` only) |
| `render` | object | blocks, blocks done, air blocks, `stopped` (`deadline`, `max_blocks` or null), seconds per phase, `peak_rss_mb`, `verified` |
| `surface_residual_vox` | float | worst surface round-trip error (with `--surfaces`) |

| Exit code | Meaning |
| --- | --- |
| `0` | Success: `make` completed, or `verify`, `pyramid` or `publish` found every chunk |
| `1` | `verify`, `pyramid` or `publish` found a missing chunk or a `.partial` file |
| `75` | `make` stopped early (deadline or `--max-blocks`); rerun with `--resume` |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `...: chunk(s)...did not land after...writes` | a chunk file never appeared on disk (for example through a network mount) | render to a local disk, then `publish` |
| `supersample is 1 or more` | `supersample` below 1 | set 1 or more |
| `tex_z and tex_s are 16 or more` | texture tile too small | set 16 or more |
| `shape is three sizes of 16 voxels or more` | bad `shape` | give three sizes of at least 16 |
| `squash lies in 0.2 to 1` | crush out of range | set 0.2 to 1 |
| `contact_share lies in 0 to 1` | out of range | set 0 to below 1 |
| `pitch must exceed thick` | windings would overlap | raise `pitch` or lower `thick` |
| `...is not a scrollsim2 folder (no ct.zarr)` | `publish` source is not a make folder | point it at a finished `make OUT` |
| `...: level 0 is not complete; resume make first` | `pyramid` on a stopped run | `make OUT --resume` with the same settings |
| `...exists and is not empty` | `make` never overwrites | pick a new folder or add `--resume` |
| `--block must be a positive multiple of --chunk, so parallel writes never share a chunk` | blocks would share a chunk | make `--block` a multiple of `--chunk` |
| `--levels lies in 0 to 8` | too many levels | set 0 to 8 |
| `--order is zyx or middle` | unknown order | use one of the two |
| `unknown preset...; known:...` | unknown `--preset` | use `smoke` or `pilot` |
| `unknown parameter...` | unknown `--set` key | see Inputs |
| `...is 0 or more` | a negative scan-model value | set 0 or more |
| `the box holds less than two windings; raise shape or lower pitch` | box too small for the spiral | raise `shape` or lower `pitch` |
| `...was made with other parameters, block, chunk, levels or code; resume needs the same` | `--resume` with other settings or code | resume with the same settings, or start a new folder |
| `...: chunks missing after the pyramid:...` | a pyramid write was lost | run `pyramid OUT` |
| `--set is KEY=VALUE` | malformed `--set` | write `KEY=VALUE` |
| `scrollsim2:...` | any refusal above, from the command line | read the message |
| `which is center or recto` | bad `surface()` argument | use `center` or `recto` |
| `the box is...voxels in y; this crush needs...` | fixed crush axis and a box too short in y | raise y to the size named |
| `...is not a scrollsim2 folder to resume (no truth/make-key.json)` | `--resume` on another folder | use a folder `make` started |

## How it works

1. **Sheet.** `Roll` lays the sheet on an unwrapped angle (`ANG` = 1,024 samples per turn) and a z grid (`GZ` = 8 voxels). Each turn's radius is the last turn's plus a gap: the free spacing `pitch` (with smooth variation) where windings lie apart, `touch` times the thickness inside contact zones (a thresholded smooth field covering `contact_share` of interfaces). Thickness, delamination and holes are smooth random fields along the sheet.
2. **Frames.** Output points map back to the rolled frame through a smooth displacement field (grid `WG` = 16 voxels) and the inverse crush. The center line and surfaces map forward by fixed-point iteration.
3. **Lookup.** For each voxel `Scroll2.voxels` finds the turn just inside it by binary search over turns, then sums two Gaussian plies (sigma `ply_sigma` times a quarter thickness) for that turn and its neighbors, with periodic fiber tiles (recto along the sheet, verso along z). The label is the nearest winding whose ply band holds the voxel.
4. **Scan model.** Density maps to gray between `air` and `bright`, then blur and point spread, the phase-edge filter, slow drift, rings and noise (hashed by position, optionally correlated), then rounding to uint8.
5. **Blocks.** `make` splits the volume into blocks (`--block`, a multiple of `--chunk`), renders each with a halo of about four filter widths, skips blocks no sheet can reach, writes level 0 in parallel and checks each chunk file landed, appends the block to `done.txt`, then builds the pyramid by 2 x 2 x 2 means and verifies it. A deadline in `KIT_JOB_DEADLINE` (epoch seconds) stops new blocks once less than `KIT_JOB_SPARE_S` (default 180 s) is left.

## Cost and time

- Smoke preset, 4 workers, 4-core cloud container: 7.2 s wall, 98 MB peak per process (2026-11-18).
- Pilot preset (1,024 x 1,728 x 3,264, 125 turns), `estimate --sample 2 --workers 4` in the same container: 5.0 s per 128^3 sheet block, 2,458 sheet blocks of 2,912, about 12,300 core-seconds (about 52 minutes on 4 workers), 5.3 GB peak for the geometry, which forked workers share (2026-11-18). An estimate, not a measured full run.
- Larger runs: run `estimate` first; it times a few sheet blocks on one core and prints `wall_seconds_at_workers`. Rendering is bound by memory bandwidth, so more than about 16 workers rarely helps; `default_workers()` caps at 16 and `main` sets single-thread BLAS so forked workers do not oversubscribe cores.
- It rents nothing. A rented run follows hard rule 11.

## For agents

- **Command:** `python -m kit.scrollsim2 make OUT --preset smoke --workers 4 --block 64 --chunk 64 --levels 2 --surfaces`; preflight with `python -m kit.scrollsim2 estimate --preset NAME --sample 3 --workers N`.
- **Parse:** the one JSON line on stdout: `complete`, `turns`, `render.blocks_done`, `render.stopped`, `render.verified.ok`, `surface_residual_vox`. Progress lines `PROGRESS n/N blocks` go to stderr.
- **Rerun:** `make` never overwrites; rerun with `--resume` and the same settings to finish a stopped run. `verify` is read-only. `pyramid` rewrites levels 1 and up.
- **Success:** exit 0 and `complete` true with `render.verified.ok` true. Exit 75 means stopped early: resume it.
- **Not a pass:** a tracer or ink score on a ScrollSim v2 volume is not evidence about any real scroll, and a method ranking on it is not a real ranking until the calibration in "Realism: in progress" passes.
- **Go-ahead:** nothing for a local CPU run; a rented run follows hard rule 11.
- **Never:** call its output real CT, mix its volumes into real training or test data unlabeled, or describe an ink map on it as a reading.

Stage registry: no stage option. The registry's stages read a real scroll; ScrollSim v2 makes test inputs for them rather than running as one.

## Tests

`python -m unittest tests.test_scrollsim2 -v` (about 2 minutes on 4 cores; skips without numpy and scipy, and the make tests skip without zarr). Covered: lookup equality, determinism, parameter refusals, the narrow fixed-axis box, position-hashed noise, block independence, air skipping, make and its pyramid, stop and resume, deadline stop, lost-chunk detection and repair, publish, estimate, the worker cap and BLAS threads. Not covered: the `pilot` preset at full size, and any realism of the volumes.

## History

- 2026-11-18: pictures and four tutorials, every command run on a fresh clone (`49eb2a5`).
- 2026-11-18: first public release (version 1): full-scale geometry, block rendering and exact winding and surface truth; ink off (`49d26fe`).

## Related

- [tifxyz](tifxyz.md): reads and checks the surfaces it writes.
- [auc](auc.md): scoring on real published labels, where real claims come from.
