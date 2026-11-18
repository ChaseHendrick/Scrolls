# scrollsim2: a full-scale synthetic scroll rendered block by block, with exact truth

`python -m kit.scrollsim2` rolls, presses and crushes one synthetic papyrus sheet into a whole-scroll CT volume, renders it block by block into OME-zarr, and writes the exact winding of every voxel beside it, so tracers can be scored on synthetic data.

| Field | Value |
| --- | --- |
| Id | `scrollsim2` |
| Status | Experimental |
| Kind | kit entry point, kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit.scrollsim2 make`, `python -m kit.scrollsim2 estimate`, `python -m kit.scrollsim2 stats`, `from kit import scrollsim2` |
| Code | `kit/scrollsim2.py` |
| Tests | `tests/test_scrollsim2.py` |
| Needs | Python 3.10 or newer, numpy and scipy (the `maps` extra); zarr 3 for `make`, `pyramid`, `verify` and `publish` (checked with scipy 1.18.1 and zarr 3.4.2 on Python 3.13.18). `make` forks its workers, so it needs a system with `fork` (Linux or macOS) |
| Runs on | Any CPU. The `smoke` preset (64 x 208 x 208, about 5 windings) takes 5.2 s wall on 4 workers; a `pilot` (1,024 x 1,728 x 3,264, about 150 windings) took 1,512 s for its 2,912 blocks on a 32 vCPU cloud machine (measured 2026-11-18) |
| Network | None |
| Writes | `make OUT`: `OUT/ct.zarr` (levels 0 to L), `OUT/truth/labels.zarr`, `OUT/truth/done.txt`, `OUT/truth/make-key.json`, `OUT/truth.json`, and with `--surfaces` `OUT/truth/surfaces/spiral-center/` and `spiral-recto/` (tifxyz and `winding.npy`). `publish` writes DST; `library` writes one `.npz`; `stats --out` one JSON |
| Go-ahead | Not needed locally. A run on rented machines follows hard rule 11 |
| Released | Public `main` from the PR that adds this page (2026-11-18) |
| Checked | 2026-11-18 against commit `c2cb575` |

## What it does

A tracer's winding numbers can only be scored where the true winding of every voxel is known, and on a real scroll it never is. `kit.scrollsim2` makes a synthetic scroll at full scale where it is. It rolls one sheet into a spiral around the z axis, presses neighbouring windings together in smooth contact zones (windings that touch are the hard case for tracers), varies thickness and spacing smoothly, splits plies (delamination) and cuts holes, squashes the roll along one axis and bends it with a smooth displacement field. Then it renders a CT-like volume and a label volume with each voxel's winding.

How it reaches a whole scroll:

- **Winding lookup by binary search.** It finds the turn just inside a voxel in about log2(turns) lookups instead of evaluating every turn; the test checks that it finds the same turn as a scan over all turns.
- **Tiled textures.** A 150-winding sheet is millions of voxels long, so fiber textures come from periodic tiles (`tex_z` by `tex_s`, wrap-filtered).
- **A fixed crush axis.** `alpha` 0 puts the major axis along x, so the box can be about half as tall as it is wide.
- **Block rendering that does not depend on the block.** Each block renders with a halo that covers every filter, and noise is a hash of the voxel position, so any block size gives the same volume bit for bit (test). Blocks beyond the roll are detected and skipped.
- **A scan model.** An anisotropic point spread (`psf_z`, `psf_xy`, with `blur`), correlated noise (`noise_corr`), a phase-edge filter (`edge`, `edge_sigma`), rings, slow drift, and supersampling for partial volume (`supersample`).
- **A texture library** (`library`): sheet and gap residual patches cut from a real CT crop without labels (Otsu split of the smoothed crop, gaps within 6 voxels of a sheet), scaled by the crop's sheet-to-gap contrast, and laid on a global grid of Hann-blended tiles chosen by a hash of the tile position. The default texture is synthetic; the library is optional.
- **Label-free CT statistics** (`stats`, `stats-compare`): sheet and gap run lengths, gray distributions, noise, drift, coherence and waviness of a crop, and whether a simulated crop's statistics lie inside the spread between real crops of different scans.

There is no ink. What it is not: a calibrated stand-in for a real scroll. A score on its volumes is model output on synthetic data and says nothing about any real scroll; a method's ranking here must be checked against its ranking on real truth before it is trusted. Nothing here is a reading.

## When to use it

- To test a tracer or a winding method end to end at full scroll scale, with exact winding truth for every voxel.
- To test a pipeline's handling of a whole-scroll OME-zarr (chunking, pyramids, resume) without downloading a scan.
- To compare a simulated crop's label-free statistics with real crops (`stats`, `stats-compare`).

Do not use it:

- For ink: it has none. For synthetic ink on a surface volume use [phantom](phantom.md); for planted ink in real data, [planted](planted.md).
- As evidence about a real scroll: score on real truth.

## Quick start

```bash
python -m kit.scrollsim2 make SIM --preset smoke --workers 4 --block 64 --chunk 64 --levels 2 --surfaces
python -m kit.scrollsim2 verify SIM
python -m kit.scrollsim2 estimate --preset pilot --sample 3 --workers 4
```

- `SIM`: a new empty folder.

`make` prints one line of JSON. On 2026-11-18 in a 4 logical CPU cloud container it printed `turns` 4.77, `pressed_share` 0.29, `surface_residual_vox` 2.8e-14 and `render` blocks 16, air blocks 2, seconds 4.8 (5.2 s wall); `verify` printed `"ok": true`. It worked when `SIM/ct.zarr/0` has the requested shape and `SIM/truth/labels.zarr/0` holds several winding ids.

## Checks and controls

The tool makes volumes; it scores nothing. Its own checks are exactness checks against itself:

- The binary-search lookup finds the turn a scan over every turn finds (`test_binary_search_finds_the_turn_a_full_scan_finds`).
- Any block size gives the same volume and labels at every pyramid level (`test_block_render_is_block_independent`, `test_make_writes_pyramid_and_is_deterministic`), and a stopped and resumed `make` gives the same volume as one run (`test_stop_and_resume_give_the_same_volume`).
- Skipping air blocks changes nothing (`test_air_skip_changes_nothing`).
- `verify` finds a deleted chunk and `pyramid` repairs it; a chunk that never lands is refused after three writes.
- The truth surfaces map back to the rolled sheet with a residual under 1e-6 voxel.
- The statistics are a distance of 0 from a crop to itself and grow with added noise; a crop with three times the noise lies outside the spread of two crops with equal noise.

Before release, this module rendered byte-identical CT, labels and recto surface to the code it was developed from, on a 48 x 160 x 160 test scroll with noise, rings, correlated noise, an edge filter and drift (2026-11-18).

Claim label: Model output (volumes and statistics of a simulator); Interpretation, for any use of them as a test of a method.

## Commands and options

### `python -m kit.scrollsim2`

```
usage: python -m kit.scrollsim2 [-h] {make,estimate,pyramid,verify,publish,stats,stats-compare,library,info} ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `make OUT` | required | Render one scroll into the empty folder `OUT` |
| `estimate` | | Time a few sheet blocks and extrapolate a whole `make` (prints JSON) |
| `--preset` | none | `make`, `estimate`: `smoke` (64 x 208 x 208) or `pilot` (1,024 x 1,728 x 3,264, alpha 0) |
| `--set KEY=VALUE` | none | `make`, `estimate`: any key of `DEFAULTS` (the geometry keys and the extra keys below; repeatable) |
| `--seed` | from the parameters | `make`, `estimate`: the seed |
| `--workers` | the CPU count, at most 16 (`MAX_WORKERS`) | `make`, `estimate`: forked worker processes |
| `--block` | `128` | `make`, `estimate`: block edge, voxels; a multiple of `--chunk` |
| `--levels` | `5` | `make`: pyramid levels above level 0 |
| `--chunk` | `128` | `make`: zarr chunk edge |
| `--surfaces` | off | `make`: also write the center and recto tifxyz of the whole sheet (memory grows with the sheet length) |
| `--resume` | off | `make`: continue an `OUT` made with the same parameters, block, chunk, levels and code, rendering only blocks not in `truth/done.txt` |
| `--max-blocks` | none | `make`: stop after this many new blocks (a timing probe on the target machine); exit 75 |
| `--order` | `zyx` | `make`: `zyx` renders blocks in index order; `middle` renders the blocks nearest the volume's center first (sheet blocks, so a `--max-blocks` probe times sheet, not air) |
| `--sample` | `4` | `estimate`: sheet blocks timed |
| `pyramid SIM` | required | Rebuild CT levels 1 and up from level 0 of a complete `make`, then verify; exit 1 if a chunk is still missing |
| `--workers` (pyramid) | the CPU count, at most 16 | `pyramid`: forked workers |
| `verify SIM` | required | Check every CT chunk of every level is on disk and no `.partial` temp file is left; exit 1 if not |
| `publish SRC DST` | required | Copy a finished local folder to DST with plain file writes (never zarr's write-then-rename), remove `.partial` files left in the copied arrays, then verify DST; exit 1 on a gap |
| `--levels` | all | `publish`: only these CT levels (a pyramid repair: `1 2 3 4 5`) |
| `--no-labels` | off | `publish`: skip the label volume |
| `stats CT` | required | Label-free statistics of a `.npy` CT crop (z y x), after resampling to `--target-um`; prints or writes JSON |
| `--voxel-um` | required | `stats`: the crop's voxel size |
| `--target-um` | `8.64` | `stats`: the voxel size statistics are measured at |
| `--scan` | the file stem | `stats`: the scan name, used by `stats-compare` to pair crops of different scans only |
| `--out` | stdout | `stats`, `stats-compare`: write the JSON here |
| `stats-compare` | | The real-to-real spread per statistic and, with `--sim`, the simulated crop's mean distance to the real crops and whether it lies inside |
| `--real` | required | `stats-compare`: real `stats` JSON files |
| `--sim` | none | `stats-compare`: one simulated `stats` JSON |
| `info SIM` | required | Print `truth.json` without the center line |

### `python -m kit.scrollsim2 library`

| Option | Default | Meaning |
| --- | --- | --- |
| `library CT OUT` | required | Cut a texture library from a `.npy` CT crop (z y x) into `OUT.npz` |
| `--patch` | `16` | `library`: patch edge, voxels |
| `--count` | `2000` | `library`: patches per class |
| `--seed` | `0` | `library`: sampling seed |

Extra parameter keys (beyond the geometry's):

| Key | Default | Meaning |
| --- | --- | --- |
| `alpha` | `-1.0` | Crush major axis angle, radians; below 0 draws it at random from the seed |
| `tex_z`, `tex_s` | `1024`, `16384` | Fiber tile height and length (periodic), voxels |
| `supersample` | `1` | Sub-samples per axis averaged into each voxel |
| `psf_z`, `psf_xy` | `0.0` | Extra point spread (sigma) along z and in-plane, combined with `blur` in quadrature |
| `noise_corr` | `0.0` | Noise correlation sigma, voxels |
| `edge`, `edge_sigma` | `0.0`, `1.5` | Phase-edge gain and its Gaussian, `v + edge * (v - G(v))` |
| `library` | empty | A texture library `.npz` |

Geometry and scan keys (`BASE_DEFAULTS`):

| Key | Default | Meaning |
| --- | --- | --- |
| `shape` | `[256, 512, 512]` | z, y, x of the output volume |
| `pitch`, `pitch_sd` | `14.0`, `0.12` | Winding center spacing where windings lie apart, and its relative smooth variation |
| `r0` | `24.0` | Radius of the sheet's inner end |
| `thick`, `thick_sd` | `7.0`, `0.15` | Winding thickness (two plies) and its relative variation |
| `ply_sigma` | `0.8` | Each ply's Gaussian sigma, as a share of a quarter of the thickness |
| `fiber` | `0.25` | Fiber texture amplitude in each ply |
| `contact_share` | `0.45` | Share of every interface pressed together |
| `zone` | `150.0` | Correlation length of the contact field |
| `touch` | `0.85` | Center spacing at full contact, as a share of the local thickness |
| `delam` | `1.5` | Largest ply separation where a winding has split |
| `holes` | `0.02` | Share of the sheet missing |
| `squash` | `0.5` | Minor over major axis of the global crush (1 is round; 0.2 to 1) |
| `warp`, `warp_corr` | `5.0`, `96.0` | Rms of the smooth displacement and its correlation length |
| `margin` | `10.0` | Air kept between the roll and the box edge |
| `air`, `bright` | `60.0`, `150.0` | Gray of air and of a ply's peak |
| `noise`, `blur`, `bias`, `rings` | `3.0`, `0.9`, `0.08`, `0.0` | Noise sd, Gaussian blur sigma, slow drift amplitude, ring amplitude |
| `seed` | `0` | Every random field and the hashed noise |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `params(over=None, preset=None)` | dict | `SimError` | DEFAULTS, then the preset, then `over`; the geometry's refusals too |
| `base_params(over=None)` | dict | `SimError` | The geometry keys only, checked |
| `Roll(p)` | the geometry | `SimError` | Spiral, contacts, crush and displacement from the seed; `rolled`, `forward`, `center_line`, `R_at`, `s_at`, `theta_of_s`, `face_offset`, `hole_at`, `winding_id`, `surface` |
| `Scroll2(p)` | the full-scale scroll | `SimError` | A `Roll`; adds `voxels`, `locate_turn`, `block_is_air`, `density_block`, `scan_block`, `halo` |
| `hashed_normal(seed, z0, z1, y0, y1, x0, x1, salt=13)` | float32 array | | Unit normal noise, a function of position only |
| `build_library(vol, patch=16, count=2000, seed=0, share=0.7)` | dict | `SimError` | Label-free sheet and gap residual patches |
| `make(out, over=None, preset=None, workers=1, block=128, levels=5, chunk=128, surfaces=False, progress=print, resume=False, max_blocks=None, environ=None, order='zyx')` | the `truth.json` dict | `SimError` | |
| `estimate(over=None, preset=None, workers=1, block=128, sample=4, seed=0, progress=print)` | dict | `SimError` | |
| `verify(out)` | dict (`ok`, `levels` with `chunks`, `missing`, `first_missing`; `partial`) | | Every CT chunk on disk (the CT is never all fill) and no `.partial` file |
| `publish(src, dst, levels=None, labels=True)` | the `verify` dict of DST plus `copied_files` | `SimError` | Plain copy, then verify |
| `pyramid(out, workers=1)` | the `verify` dict plus `seconds` | `SimError` | Rebuild levels 1 and up from level 0 |
| `resample(vol, voxel_um, target_um)` | float32 array | | Gaussian anti-alias (sigma 0.4 times the shrink) and linear zoom |
| `ctstats(vol, voxel_um, target_um=8.64, tile=32, step=3, seed=0)` | dict | `SimError` | Label-free; distributions as `QN` (101) quantiles; gray normalised gap 0, sheet 1 |
| `stats_distance(a, b)` | dict per statistic | | Wasserstein over the pooled interquartile range for distributions, absolute difference for scalars |
| `stats_compare(real, sim=None)` | dict (`spread`, `sim`, `inside`, `judged`) | | Spread over pairs of different scans only |
| `default_workers()` | int | | The CPU count, at most `MAX_WORKERS` (16) |
| `single_thread_blas(environ=None)` | None | | Sets `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS` to 1 where unset; `main` calls it first |
| `code_sha256()` | str | | The sha256 of `kit/scrollsim2.py`, written to `truth.json` |
| `main(argv=None)` | 0 or 75 | `SystemExit` with the refusal | |

## Inputs

- `make`, `estimate`: parameters only. Lengths in output voxels.
- `library`, `stats`: one `.npy` CT crop, z y x, any numeric type; for `library` each side at least twice the patch. Any crop you are allowed to use, such as one cut from the Vesuvius Challenge open data; no labels, traces or meshes are read.
- `KIT_JOB_DEADLINE` (the epoch second a batch job's timeout ends) and `KIT_CKPT_RESERVE_S` (seconds kept for the last writes, default 180): when a launcher sets the deadline, `make` stops new blocks before it and exits 75, ready to resume.

## Outputs

`truth.json`: `tool`, `version`, `code_sha256` (this module), `params`, `preset`, `complete`, `turns`, `alpha`, `sheet_length_vox`, `pressed_share`, `r_outer_rolled`, `center_line`, `render` (workers, block, chunk, levels, blocks, blocks_done, blocks_this_run, air_blocks_this_run, complete, stopped, seconds_init, seconds_level0, seconds_pyramid, seconds_per_sheet_block_mean, deadline, reserve_s, verified, seconds, peak_rss_mb of the parent process), and with `--surfaces` `surface_residual_vox`, `seconds_surfaces`.

`estimate` JSON: `shape`, `turns`, `block`, `blocks`, `sheet_blocks`, `sampled`, `seconds_per_sheet_block`, `seconds_init`, `seconds_classify`, `core_seconds`, `wall_seconds_at_workers`, `workers`, `voxels`, `peak_rss_mb`.

| Exit code | Meaning |
| --- | --- |
| `0` | Done |
| `75` | `make` stopped early (within `KIT_CKPT_RESERVE_S` of `KIT_JOB_DEADLINE`, or `--max-blocks`): `truth.json` has `complete` false; rerun with `--resume` |
| `1` | A refusal (`scrollsim2: ...`), an error, or `verify`, `pyramid` or `publish` found a gap |
| `2` | Bad arguments (argparse) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `unknown parameter` | A `--set` key not in `DEFAULTS` | Use a listed key |
| `--set is KEY=VALUE` | Malformed `--set` | Follow the form |
| `unknown preset NAME; known: smoke, pilot` | Not `smoke` or `pilot` | Pick one |
| `supersample is 1 or more`, `... is 0 or more`, `tex_z and tex_s are 16 or more` | Out of range | Pick a value in range |
| `the box is N voxels in y; this crush needs M` | A fixed crush axis with a box too short in y | Raise the y size or set `alpha` below 0 |
| `exists and is not empty` | `make` never overwrites | Use a new folder |
| `--block must be a positive multiple of --chunk, so parallel writes never share a chunk` | Parallel writes would share a chunk | Make the block a multiple of the chunk |
| `--levels lies in 0 to 8` | Out of range | Pick a value in range |
| `--order is zyx or middle` | Another order | Use one of the two |
| `scrollsim2: MESSAGE`, exit code 1 | Any refusal below, printed by the command line | Read the message |
| `ARR: chunk(s) KEY did not land after 3 writes` | A chunk file did not appear after its write (seen on a cloud bucket mount, where zarr's rename of its `.partial` temp file did not land) | Write to local disk and copy the folder with `publish`; never write zarr through the mount |
| `: chunks missing after the pyramid:` | `verify` found a CT chunk missing or a `.partial` file after the pyramid | Run `pyramid SIM`; if it persists, write locally |
| `the crop is ... voxels at ... um; the statistics need ... in y and x and 8 slices` | The crop is too small after resampling | Use a larger crop or a finer target |
| `is not a scrollsim2 folder (no ct.zarr)` | `publish` from a folder `make` did not write | Point at a `make` folder |
| `: level 0 is not complete; resume make first` | `pyramid` on an unfinished `make` | `make --resume` first |
| `is not a scrollsim2 folder to resume (no truth/make-key.json)` | `--resume` on a folder `make` did not start | Use a new folder without `--resume` |
| `was made with other parameters, block, chunk, levels or code; resume needs the same` | `--resume` with different settings or code | Resume with the same settings, or start a new folder |
| `the crop needs three sides of at least N voxels` | `library` crop too small | Use a larger crop or a smaller patch |
| `no sheet or no gap found in the crop`, `sheet is not brighter than gap in this crop` | The crop is air, solid, or inverted | Pick a crop that holds sheets and gaps |
| `: the library holds no sheet or no gap patches` | An empty class in the `.npz` | Rebuild with a larger crop or a lower `share` |
| `which is center or recto` | `surface()` with another face | Use `center` or `recto` |
| `unknown parameter` from the geometry, `shape is three sizes of 16 voxels or more`, `squash lies in 0.2 to 1`, `contact_share lies in 0 to 1`, `pitch must exceed thick` | A geometry value out of range | Pick a value in range |
| `the box holds less than two windings; raise shape or lower pitch` | The box is too small for the roll | Raise `shape` or lower `pitch` |

## How it works

1. `Roll.__init__` draws every random field from the seed in a fixed order: thickness, spacing and contact fields along the sheet, the spiral radius turn by turn with pressed gaps (iterated so the contact quantile is taken over the sheet actually used), delamination, holes and the displacement field. `Scroll2.__init__` builds it; with `alpha` 0 or more it builds on a square box of the requested width, then sets the crush angle, the box height and the center, and refuses a box too short for the crushed roll.
2. `locate_turn`: binary search over turn index k for the largest k with R(phi + 2 pi k, z) at most rho; R grows with k at fixed angle and height, so this equals a scan over every turn. `voxels` then sums the two plies of turns j - 1 to j + 2 and returns the distance to the nearest winding center.
3. `scan_block`: render the block plus a halo (`halo()`, 4 times the widest filter sigma plus 2) at `POINTS_PER_PASS` (2^18) points per pass; density to gray, point spread, phase edge, library texture, slow drift (coarse field from the [seed, 11] stream), rings ([seed, 12]), hashed noise (splitmix64 of the seed, salt 13 and position, Box-Muller), optionally Gaussian-correlated and rescaled to unit sd; crop the halo; quantize.
4. `make`: the worker pool forks before any zarr call (zarr 3 starts an I/O thread). Level 0 and labels go block by block in forked workers (block a multiple of the chunk, so no two workers write one chunk), in batches of twice the worker count; each batch's block indices are appended to `truth/done.txt` only after its blocks are written. Before each batch it checks the deadline and `--max-blocks`. When every block is done, each further level is built from 2 x 2 x 2 means of the level below, rounded, chunk by chunk. Every write checks that the file of each chunk holding a value other than the fill value is on disk, and retries up to `WRITE_TRIES` (3) times; `make` ends with `verify` and refuses a gap.

## Cost and time

Measured 2026-11-18 in a 4 logical CPU cloud container: smoke `make` 5.2 s wall on 4 workers (103 MB peak in the parent); smoke `estimate` 1.67 s per sheet block on one core; the tests 132 s. Pilot blocks: about 3.5 s each in a 4-core container, and 4 workers at once keep 3.3 to 3.7 s; 30.5 s and 5.3 GB peak to build the pilot geometry.

A pilot on a Hugging Face `cpu-performance` machine (32 vCPU, 2026-11-18): all 2,912 blocks in 1,512 s, pyramid 126 s, 1,660 s in all, about 17.7 s per sheet block per worker, 5.3 GB peak, CT 6.55 GB and labels 0.78 GB. That machine saturates memory bandwidth from about 8 processes: 2.08 blocks/s at 8 workers, 1.96 at 16, 1.53 at 32, so the default is at most 16 workers, and `main` sets the BLAS thread variables to 1 (an inherited OMP of 32 ran 116 times slower). Time a few blocks on the target machine (`estimate`, or `make --max-blocks N --order middle`) before sizing a run. The tool rents nothing.

## For agents

- **Command:** `python -m kit.scrollsim2 make SIM --preset pilot --workers N`; probe first with `python -m kit.scrollsim2 estimate --preset pilot --workers N`.
- **Parse:** `render.seconds`, `render.seconds_per_sheet_block_mean`, `turns`, `complete`; for `estimate`, `wall_seconds_at_workers` and `core_seconds`; for `verify`, `ok`.
- **Rerun:** `make` refuses a non-empty folder unless `--resume`; the same parameters give the same bytes whatever the block size, worker count, or stop and resume (test).
- **Success:** exit 0, `complete` true, and `verify SIM` `ok` true.
- **Not a pass:** a pretty volume. Realism is a statistics comparison with real crops of several scans (`stats-compare`), and usefulness is a method ranking that matches real truth.
- **Go-ahead:** Nothing locally; rented runs follow hard rule 11.
- **In a cloud job:** write `OUT` on the job's local disk and copy it to a bucket mount with `publish OUT DST` at the end (plain writes, then the audit). A pilot written straight through a bucket mount lost 43 of 364 level-1 chunks to `.partial` files whose rename never landed.
- **Never:** call a score on its volumes a result about a scroll, or anything in it a reading.

## Tests

```bash
python -m unittest tests.test_scrollsim2 -v
```

18 tests, 132 s with numpy, scipy and zarr (2026-11-18, 4 logical CPU cloud container): parameters and refusals, the binary-search lookup, the narrow box, position-only noise, block independence, air skipping, the texture library, `make` with its pyramid and determinism, stop and resume, `verify` and `pyramid` repair, a chunk that never lands, `publish`, `estimate`, the statistics, and the worker cap. They skip without numpy and scipy; the `make` tests skip without zarr.

## History

- 2026-11-18: released to public Scrolls (`RELEASE_COMMIT`). Before that it was developed outside this repository from earlier miniature simulators, adding the full-scale lookups, block rendering, the scan model, the texture library, the statistics and resumable OME-zarr output.

## Related

- [phantom](phantom.md): synthetic carbon-ink surface volumes with known truth.
- [planted](planted.md): planted ink in real data.
- [tifxyz](tifxyz.md): the surface format `--surfaces` writes.
