# sqrecipe: compare two CT acquisitions of one scroll against a finer reference scan

In the same 128-voxel regions, measures whether a finer acquisition put on a coarse scan's grid keeps more sheet fidelity against an independent finer reference scan than the native coarse acquisition does, with controls that can fail.

| Field | Value |
| --- | --- |
| Id | `sqrecipe` |
| Status | Experimental |
| Kind | script, kit module |
| Area | Scoring and controls |
| Run | `python3 scripts/sqrecipe/sqrecipe.py pool`, `measure`, `dev`, `test-pool`, `test`; library `from kit import sqrecipe`, `from kit import sqfid` |
| Code | `scripts/sqrecipe/sqrecipe.py`, `kit/sqrecipe.py`, `kit/sqfid.py` |
| Tests | `tests/test_sqrecipe.py` |
| Needs | Python 3.10 or later, numpy, scipy; numcodecs only for blosc or zstd chunks (the volumes named in the script are uncompressed); network access to the two data hosts |
| Runs on | Any CPU; 2 regions with all five arms in 19.5 s on 2 processes (measured 2026-10-31, cloud container, the Quick start below) |
| Network | `data.aws.ash2txt.org` (the PHerc0332 DLS scans) and `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (the ESRF scans): `.zarray` headers and 128-voxel chunks, read into memory only |
| Writes | The pool, rows and readout JSON files named on the command line, and `ROWS-read.json` beside each rows file; `test` writes `rows.json`, `rows-read.json` and `result.json` in a new folder. No scan data |
| Go-ahead | Not needed: it reads public data and rents nothing |
| Released | Public `main` since 2026-10-31 (code, Apache-2.0) |
| Checked | 2026-10-31 against commit `0f1b080` |

## What it does

A scroll is sometimes scanned more than once, with different acquisition recipes (voxel size, beam energy, propagation distance). Whether a finer recipe, once brought down to a coarse grid, still keeps more of the papyrus sheets than a scan taken at that coarse voxel size is a question about the CT itself, and it needs no labels and no model. sqrecipe answers it region by region with a paired design that holds the papyrus fixed.

In each 128-voxel region of the coarse scan's grid, every acquisition (an **arm**) is put on that grid: the **native** arm N is the coarse scan itself, and each finer arm (B, and B70 on PHerc0332) is read at its level 1 and resampled through the catalog transform. Each arm is then compared with an independent finer **reference** scan, resampled the same way, by its **sheet fidelity** (`kit/sqfid.py`): the normalized cross-correlation (NCC) of the two cubes after a band-pass to the sheet band, at the best integer shift within a few voxels. The paired difference d = F(B) - F(N) says which arm keeps more of the sheet pattern the reference shows there.

On PHerc0332 the arms are N, the DLS 7.910 um 53 keV scan (20231117143551) at level 0; B, the DLS 3.240 um 53 keV scan (20231027191953) at level 1; B70, the DLS 3.240 um 70 keV scan (20231201141544) at level 1; the reference is the ESRF 2.399 um 78 keV scan (20251211183505) at level 1. PHerc0500P2 is also configured, as a **null pair**: its "9.362 um" scan is a 4.681 um acquisition binned by 2, so its pair with the 4.317 um scan is a near-identical recipe and no difference is expected.

It measures CT against CT. It is not an ink detector, it does not say whether text is readable, and nothing it prints is a reading. The three PHerc0332 DLS scans are under the EduceLab Data License: sqrecipe reads their chunks live from the public host and never copies or redistributes them, and its rows files hold only per-region statistics.

## When to use it

- A scroll has two acquisitions that differ in one or two recipe parameters, plus a finer third scan, with catalog transforms between them, and you want to know, region by region, which acquisition keeps more sheet structure.
- You want a sheet-fidelity number between any coarse cube and any finer scan on the same grid: use `kit.sqfid.outcome` and `kit.sqfid.fine_on_coarse` directly.

Do not use it:

- To rank regions of one scan by quality without a second scan: sqrecipe needs a reference scan, and no single-scan score is part of this release.
- To choose a recipe for a new scan in general: its one frozen test measures one acquisition pair on one scroll (see Checks and controls).
- To find ink or judge readability: use an ink model and [`auc`](auc.md) against published labels.
- On regions another test of yours holds out: pass them with `--exclude` before you build a pool.

## Quick start

A development run on two regions of PHerc0332, streamed from the public hosts:

```bash
echo '[{"name": "a", "z": [31, 31], "y": [15, 15], "x": [19, 19]}, {"name": "b", "z": [67, 67], "y": [16, 16], "x": [17, 17]}]' > BOXES.json
python3 scripts/sqrecipe/sqrecipe.py pool --scroll PHerc0332 --boxes BOXES.json --out POOL.json
python3 scripts/sqrecipe/sqrecipe.py measure --pool POOL.json --n 2 --workers 2 --out ROWS.json
python3 scripts/sqrecipe/sqrecipe.py dev --rows ROWS.json --out DEV.json
```

BOXES.json lists boxes of region indices (a region is 128 voxels of the 7.910 um grid, so z 31 starts at voxel 3968); these two regions were already read by the frozen test. POOL.json, ROWS.json and DEV.json are output paths. On 2026-10-31 it printed (stderr, then an excerpt of `dev`'s JSON):

```
03:55:30 pool PHerc0332: 2 candidates, dropped {}
03:55:48 measure PHerc0332: 2/2 regions, 2 seen, 18 s
03:55:49 wrote rows.json: 2 regions in 19.5 s
   "decision": "VOID",
   "failed": [
    "1_minimum",
    "7_signflip"
   ]
```

It worked when ROWS.json holds 2 rows with `F_N`, `F_B`, `F_B70`, `F_Np` and `F_Bdeg`. The decision is VOID because 2 regions are under the 60-region minimum, which is correct; a real development run measures 100 regions (`--n` default). The five fidelities of both regions equal those the frozen test recorded for them, to all six decimals.

## Checks and controls

Every control below can fail, and each is read on every run:

| Control | What it does | Holds when |
| --- | --- | --- |
| Outcome control, per arm | Each arm's cube against the previous region's reference (the same shift search) | The true pair wins with a cluster-bootstrap lower bound above 0.75 (`RULE["outcome_control"]["min_share_lb"]`) |
| Border check, per arm | Share of best shifts on the search border (a transform off by more than the search holds) | At most 0.10 (`BORDER_MAX`) |
| Processing control | N', the native cube sent through B's resampling chain (onto B's level-1 lattice and back), must still lose to B | share(F(B) > F(N')) lower bound above 0.5 |
| Degradation control | Bdeg, B blurred (sigma 1 voxel) and noised to N's noise level, must lose at least half of B's lead | median(F(Bdeg) - F(N)) at most half of median d |
| Sign-flip control | d's sign flipped in a seeded half of the 4 x 4 x 4 clusters, 200 draws | At most 10 % of draws pass the primary bar |

The primary bar: share(d > 0) with its 95 % cluster-bootstrap lower bound above 0.5, and median d with its lower bound above 0. `test` reads VOID when fewer than 60 regions or 10 clusters are measured or when an instrument control (outcome control or border of N or B, sign-flip) fails; PASS when the primary bar, the processing control and the degradation control all hold; FAIL otherwise.

The frozen test on PHerc0332 (rule fixed before the read, read once; results.json key `sqrecipe_test_0332_20261030`). Question: in fresh 128-voxel regions of PHerc0332's 7.910 um grid, does the DLS 3.240 um 53 keV acquisition (20231027191953), resampled onto that grid, keep more sheet fidelity against the independent ESRF 2.399 um scan (20251211183505) than the native DLS 7.910 um 53 keV acquisition (20231117143551)?

- 120 regions. B won in a share of 0.925 of them (95 % interval 0.872 to 0.968); median gain d 0.042 (0.035 to 0.055).
- Processing control share 0.942; sign-flip control 5 of 200 draws passed; the outcome controls held.
- Verdict: PASS under the rule fixed before the read.
- Attempts: this was the second freeze of the test; the first never read any region (its smoke check refused it). The outcome rule (a shift search of plus or minus 10 voxels, band-pass sigmas 0.7 and 2.0, the reference read at level 1) was amended after development looks on regions already spent, before this freeze.

Limits: one acquisition pair on one scroll. It measures CT against CT, not ink and not readability. PHerc0500P2's two scans are a near-identical recipe pair (a null pair), so there is no clean second scroll yet.

Claim label: Model output, for the frozen test's numbers above (our own measurement of the CT, CT against CT, results.json `sqrecipe_test_0332_20261030`); Interpretation, for any reading of why the binned 3.24 um acquisition keeps more sheet fidelity.

## Commands and options

### pool

```
usage: sqrecipe.py pool [-h] --scroll {PHerc0332,PHerc0500P2} --boxes BOXES [--exclude EXCLUDE] --out OUT
```

Development candidates, geometry only (it reads each volume's `0/.zarray` header and no CT). Each box's candidates are put in the box's own seeded order; boxes follow in file order.

| Option | Default | Meaning |
| --- | --- | --- |
| `--scroll` | required | The scroll whose volumes `SCROLLS` names: `PHerc0332` or `PHerc0500P2` |
| `--boxes` | required | JSON list of boxes: `name`, `z`, `y`, `x` as `[lo, hi]` region indices (inclusive), and `seed` (default 0) |
| `--exclude` | none | JSON list of exclusion boxes: `volume` (`native`, `ref` or an arm name), `z`, `y`, `x` as `[lo, hi]` level-0 voxels of that volume (hi exclusive; an axis left out spans everything), optional `name` |
| `--out` | required | Pool file to write |

### measure

```
usage: sqrecipe.py measure [-h] --pool POOL [--workers WORKERS] [--n N] [--max-candidates MAX_CANDIDATES] --out OUT
```

Streams the CT and measures every arm's fidelity in each candidate region, in the pool's order, until `--n` usable regions (every cube at least 98 % inside its mask) are measured.

| Option | Default | Meaning |
| --- | --- | --- |
| `--pool` | required | A pool file from `pool` or `test-pool` |
| `--workers` | 3 | Processes; candidates are opened in batches of 2 x workers |
| `--n` | 100 | Usable regions to measure (`DEV["n"]`) |
| `--max-candidates` | 600 | Read at most this many candidates of the pool, in its order (`DEV["max_candidates"]`) |
| `--out` | required | Rows file to write (refused if it exists) |

### dev

```
usage: sqrecipe.py dev [-h] --rows ROWS --out OUT
```

Reads out one or more rows files and prints a summary. A scroll marked `null_pair` gets `null_pair_usable` (its outcome controls and the N and B border checks hold) instead of a decision.

| Option | Default | Meaning |
| --- | --- | --- |
| `--rows` | required | A rows file from `measure` (repeatable) |
| `--out` | required | Readout file to write (overwritten) |

### test-pool

```
usage: sqrecipe.py test-pool [-h] --scroll {PHerc0332,PHerc0500P2} --bands BANDS [--exclude EXCLUDE] [--seed SEED] --out OUT
```

Test candidates, geometry only: every candidate of every band in one seeded order. Fix the bands, the seed and the readout rule in a preregistration before you build it.

| Option | Default | Meaning |
| --- | --- | --- |
| `--scroll` | required | As for `pool` |
| `--bands` | required | JSON list of bands: `name`, `z`, `y`, `x` as `[lo, hi]` region indices (inclusive) |
| `--exclude` | none | As for `pool` |
| `--seed` | 33 | Seed of the candidate order (`TEST["seed"]`) |
| `--out` | required | Pool file to write |

### test

```
usage: sqrecipe.py test [-h] --pool POOL [--workers WORKERS] [--n N] [--max-candidates MAX_CANDIDATES] --out-dir OUT_DIR
```

Measures a test pool once and writes its verdict. It refuses an existing output folder before it reads anything, so a test cannot be rerun into the same folder.

| Option | Default | Meaning |
| --- | --- | --- |
| `--pool` | required | A pool file from `test-pool` |
| `--workers` | 3 | Processes |
| `--n` | 120 | Usable regions to measure (`TEST["n"]`) |
| `--max-candidates` | 1500 | Read at most this many candidates of the pool (`TEST["max_candidates"]`) |
| `--out-dir` | required | New folder for `rows.json`, `rows-read.json` and `result.json` |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `OPENBLAS_NUM_THREADS` | 1 | One BLAS thread per process (set by the script unless already set) |
| `OMP_NUM_THREADS` | 1 | One OpenMP thread per process |
| `MKL_NUM_THREADS` | 1 | One MKL thread per process |

## Python API

`kit/sqrecipe.py`:

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `RecipeError()` | exception | | sqrecipe's own errors; the script prints them as `error: ...` and exits 1 |
| `Store(root, opener=None, tries=4)` | store | `HTTPError` after `tries` on other than 403 or 404 | A zarr store, local folder or HTTPS prefix, read in memory only. Counts requests and bytes; `opener(url)` may be replaced (tests use a dict). A missing key reads as None |
| `ZArray(store, path='')` | array reader | `RecipeError` | One zarr v2 array read chunk by chunk; `block(origin, size)` returns (cube, missing chunks), fill outside |
| `ParallelZArray(store, path='', threads=8, cache=96)` | array reader | `RecipeError` | ZArray whose block() fetches the chunks under it with `threads` parallel requests and keeps the last `cache` chunks; same output |
| `compose(*Ms)` | 3 x 4 matrix | | 3 x 4 matrices applied right to left: compose(B, A) maps p to B(A(p)). |
| `invert(M)` | 3 x 4 matrix | `LinAlgError` | The inverse of a 3 x 4 affine matrix, as 3 x 4. |
| `lattice_range(M, level, origin, R=128)` | (lo, hi) | | (lo, hi) zyx of the source-level block kit.sqfid.fine_on_coarse reads for the region (same arithmetic). |
| `mapped_corners(M, origin, R)` | 8 x 3 array | | The region's eight corners mapped by M, as level-0 zyx of the target volume (8 x 3). |
| `corners_inside(M, origin, R, shape0_zyx, margin=2)` | bool | | Every corner of the region maps inside the level-0 extent (zyx) of the volume M points into. |
| `touches(M, origin, R, box)` | bool | | Whether the bounding box of the region's mapped corners (origin and origin + R) overlaps `box`; used by `--exclude` |
| `sample_coarse(arr, pts_zyx, pad=3)` | uint8 array | | Trilinear samples of a coarse level-0 array at zyx points, 0 where the nearest voxel is outside the mask |
| `round_trip(native, M, level, origin, R=128)` | uint8 cube | `RecipeError` | The processing control N': the native coarse volume resampled onto the finer arm's source lattice, then onto the coarse grid exactly as that arm is |
| `hf_noise(x, sigma=HF_SIGMA)` | float | | Standard deviation, inside the mask (x > 0), of x - Gaussian(x, sigma) (outside voxels take the inside mean first) |
| `white_c(sigma=HF_SIGMA, n=64, seed=WHITE_SEED)` | float | | hf_noise of unit white noise (computed once per sigma). |
| `degrade_to(x, hf_target, seed, sigma=DEGRADE_SIGMA)` | (cube, noise SD) | | x blurred by sigma, then seeded Gaussian noise so its hf_noise is about hf_target (none when already noisier) |
| `paired(d, clusters, boot=None, seed=None)` | dict | | Share of d > 0 and median d, each with its cluster-bootstrap interval; `passes` is the primary bar |
| `signflip(d, clusters, cfg=None)` | dict | | Cluster sign-flip permutation: `passes`, `share`, and `holds` when the share is at most `max_pass_share` |
| `border_share(flags)` | dict | | Share of best shifts on the search border; holds when at most BORDER_MAX. |
| `rho_ci(x, y, clusters, boot=None)` | dict | | Spearman rho of the finite pairs with its cluster-bootstrap interval. |
| `processing_holds(fb, fnp, clusters)` | dict | | Processing control: B beats N' with share(F(B) > F(N')) lower bound above 0.5. |
| `degradation_holds(fdeg, fn, d_median)` | dict | | Degradation control: median(F(Bdeg) - F(N)) at most half of median(d); moot (holds None) when median(d) is not above 0 |

`kit/sqfid.py`:

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `FidError()` | exception | | sqfid's own errors |
| `canonical(obj)` | str | | Sorted, compact JSON |
| `digest(obj)` | str | | SHA-256 of canonical(obj); the rows files record the rule's digest |
| `region_code(zyx)` | int | `FidError` | One integer per region from its (z, y, x) chunk indices (each below 1024). |
| `region_index(code)` | (z, y, x) | | (z, y, x) chunk indices of a region code. |
| `cluster_of(code, rule=None)` | str | | Bootstrap cluster: the block of cluster_regions^3 regions holding the region, as 'z_y_x'. |
| `spearman(x, y)` | float | | Spearman's rank correlation with average ranks for ties; nan when either side is constant or under 3. |
| `bootstrap(stat_fns, n_items, clusters, rule=None, seed=None)` | dict of arrays | | Cluster bootstrap: resample clusters with replacement and evaluate every stat_fn(index) on the pooled members |
| `interval(vals, rule=None)` | [lo, hi] | | The central interval at rule['bootstrap']['level'] of the finite values. |
| `coarse_to_fine(affine, direction)` | 3 x 4 matrix | `FidError` | 3 x 4 matrix (xyz) from coarse level-0 voxels to fine level-0 voxels, from a published transform and its direction |
| `fine_on_coarse(arr, level, M, origin, R=128)` | uint8 cube | | The fine array (level `level`) resampled trilinearly on the coarse cube [origin, origin + R) (zyx); outside the fine mask stays 0 |
| `bandpass(x, rule=None)` | float32 cube | | Difference of Gaussians at band_sigmas of a cube (float32); outside voxels (0) take the inside mean first. |
| `best_ncc(c, f, rule=None)` | (float, shift) | `FidError` | NCC of the band-passed coarse cube's inner part against the band-passed fine cube at every integer shift within +-max_shift (direct loop) |
| `best_ncc_fast(c, f, rule=None)` | (float, shift) | `FidError` | best_ncc by FFT, the same result up to rounding |
| `outcome(coarse, fine, rule=None)` | dict | `FidError` | The region's fidelity: `fidelity`, `shift` (zyx) and `at_border` |
| `derangement(n, seed)` | list | | A seeded permutation with no fixed point (n >= 2): region i's coarse cube meets region perm[i]'s fine cube. |
| `outcome_control(true_vals, mis_vals, clusters, rule=None)` | dict | | Share of regions where the true pair's fidelity beats the mismatched pair's, with its interval; `holds` above `min_share_lb` |

```python
from kit import sqfid
res = sqfid.outcome(coarse_cube, fine_cube)   # two uint8 cubes on one grid, 0 outside the mask
print(res["fidelity"], res["shift"], res["at_border"])
```

## Inputs

- **Volumes:** OME-Zarr v2 uint8 arrays with 128-voxel chunks, read by URL; 0 is outside the scroll mask. The URLs, levels and catalog matrices are in the script's `SCROLLS`. The matrices map the native grid's level-0 voxels (x, y, z, 1) to each target volume's level-0 voxels (x, y, z), copied from the open data bucket's `metadata.json` volume transforms.
- **Boxes and bands:** JSON lists in region indices of the native grid (region index i covers voxels 128 i to 128 i + 127 on that axis). PHerc0332's native grid is 9777 x 3550 x 3400 voxels (z, y, x).
- **Exclusion boxes:** JSON lists in level-0 voxels of the named volume; a region whose mapped corners touch a box is dropped and counted under `excluded`.
- **Pool files:** `pool` or `test-pool` output; `measure` reads `scroll` and `candidates` (`code`, `box`).

## Outputs

`pool` and `test-pool` write `scroll`, `candidates` (each `code` and `box`, in measuring order), `n_candidates`, `dropped` (counts by reason: `native_extent`, `ref_extent`, `arm_extent`, `excluded`), the boxes or bands, the exclusion list, and `shapes0` (`pool`) or `seed` (`test-pool`).

`measure` writes the rows file:

| Field | Type | Meaning |
| --- | --- | --- |
| `rows` | list | One per usable region, below |
| `read` | list | Every candidate opened, usable or not, the overrun after the n-th usable one included: `code`, `box`, `region` |
| `n_read`, `seen`, `skipped_mask`, `skipped` | int, int, int, list | Candidates opened, measured, and skipped by the mask rule (with each cube's `mask_share`) |
| `rule`, `rule_digest`, `ref_level` | object, str, int | The outcome rule, its SHA-256 and the reference level |
| `wall_s`, `pool` | float, str | Wall time in seconds and the pool path |

Each row: `code`, `box`, `region` (`z_y_x`), `cluster`, `mask_share` per cube, `hf` (noise statistic per cube), `deg_noise_sd`, `ref_mean`, and per cube `F_<arm>` (fidelity, NCC from -1 to 1), `shift_<arm>` (zyx voxels), `border_<arm>` (bool), `Fmis_<arm>` (fidelity against the previous region's reference); cubes are `N`, `B`, `B70` (PHerc0332), `Np` (N') and `Bdeg`, and `Fmis` is written for the arms. `cpu_s` is the seconds spent on the controls and the fidelities. `ROWS-read.json` beside the rows file holds `read` and is rewritten before each batch is measured, so it survives a run that dies.

`dev` writes `sets`, one readout per rows file keyed by scroll: `n`, `clusters`, `median_F`, `outcome_control` and `border` per arm, `primary`, `processing` (with `gain_median`), `degradation` (with `Bdeg_vs_B`), `signflip`, `energy_B_minus_B70` and `native_vs_B70` when B70 was measured, `hf_median`, `rows_digest`, `rule_digest`, and `verdict` (`items`, `decision` GO, NO-GO or VOID, `failed`) or `null_pair_usable`. `test` writes the same readout to `result.json` with `verdict` (PASS, FAIL or VOID), `instrument`, `items`, `n_read` and `read`, and prints `verdict`, `n`, `clusters`, `n_read` and `primary`.

| Exit code | Meaning |
| --- | --- |
| `0` | The command finished; read `decision` or `verdict` for the result |
| `1` | A refusal or error, printed as `error: ...` on stderr (see Failure modes) |
| `2` | A missing or wrong argument |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `no 0/.zarray at...` | A volume URL in `SCROLLS` did not answer with its header | Check the network and that the host still serves the volume |
| `...must be a non-empty JSON list of boxes` | The boxes or bands file is not a list, or is empty | Write a JSON list of boxes |
| `...: each box needs a name and z, y, x as [lo, hi] region indices, 0 to 1023` | A box is missing a field, or a range is reversed or out of bounds | Fix the box |
| `exclusion box names unknown volume...` | An exclusion box's `volume` is not `native`, `ref` or one of the scroll's arms | Use one of those names |
| `cannot read...:...` | A pool, boxes, exclusion or rows file is missing or not JSON | Check the path |
| `pool names unknown scroll...` | The pool's `scroll` is not in `SCROLLS` | Build the pool with `pool` or `test-pool` |
| `the rows file holds fewer than 2 regions` | `dev` needs at least 2 rows for the controls | Measure more regions |
| `...exists: the test runs once` | The `test` output folder exists | Never rerun a test into its folder; a rerun is a new, disclosed test |
| `ROWS.json exists` (the path given) | `measure` refuses to overwrite a rows file | Choose a new output path |
| `no .zarray at.../...` | `ZArray` found no header at that store and level | Check the level exists |
| `round_trip: fine_on_coarse asked for another box than the lattice held` | The lattice arithmetic and fine_on_coarse disagree | A code bug; run the tests |
| `region index...outside 0 to 1023` | A region index does not fit the code | Use indices below 1024 |
| `unknown direction...` | `coarse_to_fine` takes `fine_to_coarse` or `coarse_to_fine` | Use one of those |
| `max_shift cannot exceed inner` | A rule's shift search is wider than the border left out | Raise `inner` or lower `max_shift` |
| `kit sqfid needs numpy` | numpy is not installed | `pip install numpy` |
| `kit sqfid needs scipy` | scipy is not installed | `pip install scipy` |

## How it works

1. **Pool.** For each region of the boxes, keep it when its cube lies inside the native volume, its corners map inside the reference and every arm with a 2-voxel margin (`corners_inside`), and it touches no exclusion box; shuffle with the seed.
2. **Read.** N is the native level-0 cube. The reference and each finer arm are read at level 1 and resampled trilinearly onto the native grid (`sqfid.fine_on_coarse`: level-0 voxel v sits at (v + 0.5) / 2 - 0.5 of level 1; a voxel whose nearest source voxel is 0 stays 0). A region is skipped unless every cube is at least 98 % inside its mask (`min_mask_share`).
3. **Controls.** N' (`round_trip`): N resampled onto B's level-1 lattice and back by the same arithmetic, to show that the resampling chain alone does not explain B's lead. Bdeg (`degrade_to`): B blurred with sigma 1 (`DEGRADE_SIGMA`) and given seeded noise until its noise statistic (`hf_noise`, the SD of x minus a sigma 1 Gaussian of x) matches N's.
4. **Fidelity.** `sqfid.outcome` under `sqrecipe.RULE`: each cube and the reference are band-passed by a difference of Gaussians with sigmas 0.7 and 2.0 grid voxels (`band_sigmas`), and the NCC of the cube's inner part (10-voxel border, `inner`) against the reference is taken at every integer shift within +-10 voxels (`max_shift`), by FFT; the best NCC is the fidelity, and a best shift on the border is flagged. `kit.sqfid.RULE` keeps the measure's own defaults (sigmas 1 and 3, shift +-6, border 8).
5. **Readout.** Clusters are blocks of 4 x 4 x 4 regions; intervals are 95 % cluster bootstraps with 2,000 resamples (`BOOT`); the sign-flip control uses 200 draws of 1,000 resamples (`SIGNFLIP`). The mismatched pairs for the outcome control pair region k's arms with region k - 1's reference (the first region with the last).

## Cost and time

2 regions with all five cubes in 19.5 s on 2 processes, about 20 s of reading and computing in total (measured 2026-10-31, cloud container, Quick start). Each region streams one native chunk and the level-1 chunks under the mapped region for each finer volume, about 100 to 150 MB. `measure` keeps each usable region's arm and reference cubes (2 MB each) in memory for the outcome control, so 120 regions with three arms hold about 1 GB. A 120-region run fits a 4-CPU machine in well under an hour. It rents nothing.

## For agents

- **Command:** `python3 scripts/sqrecipe/sqrecipe.py dev --rows ROWS.json --out DEV.json`, after `pool` and `measure`; for a preregistered test, `test-pool` then `test --pool POOL.json --out-dir DIR`.
- **Parse:** In `DEV.json`, `sets.<scroll>.verdict.decision` and `.failed`, and `primary.share_ci`, `primary.median_ci`; in `DIR/result.json`, `verdict` (PASS, FAIL or VOID) and `instrument`.
- **Rerun:** `pool`, `test-pool` and `dev` overwrite their output; `measure` refuses an existing rows file and `test` an existing folder.
- **Success:** Exit 0 and every control holding (`decision` GO, or `verdict` PASS).
- **Not a pass:** A positive median d with the border, processing, degradation or sign-flip control failing; any run under 60 regions or 10 clusters; a null-pair scroll read as a recipe difference.
- **Go-ahead:** Nothing: it reads public data only.
- **Never:** Call a fidelity a reading or an ink result; copy the DLS scans' chunks or cubes anywhere (they are under the EduceLab Data License: read, never redistributed); read a test's regions before its rule is fixed.

## Tests

`python3 -m unittest tests.test_sqrecipe` (about 5 s, synthetic data, no network): the fidelity's FFT search against the direct loop, the border flag, noise lowering fidelity, the transform helpers, region codes, the outcome control holding and failing, the zarr reader (parallel against serial, zlib chunks, missing chunks, a local store), the round trip, degradation to a target noise, the readouts and their bars (each control can fail), the rule's shift and blur behavior, the pool's extent and exclusion drops, the read record with its batch overrun and a run that dies, every verdict path, and `test` refusing its folder a second time. They do not read real scans; the Quick start does.

## History

- 2026-10-31: first public release (on top of `0f1b080`), code only, Apache-2.0: `kit/sqfid.py` (the fidelity measure, its control and statistics), `kit/sqrecipe.py` and the script, with the frozen PHerc0332 test's numbers.

## Related

- [`auc`](auc.md): scoring an ink map against labels, which this tool does not do.
- results.json `sqrecipe_test_0332_20261030`: the frozen test's numbers and limits.
- [GLOSSARY](../../GLOSSARY.md): sheet fidelity, acquisition recipe, arm, null pair.
