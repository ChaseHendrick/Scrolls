# slicechains: tell a scroll's winding direction from its surface prediction

slicechains reads a scroll's published m7 surface prediction in single z slices and calls its winding direction (CW or ACW, the `spiral_outward_sense` villa's spiral fit needs) from sheet chains that wind a full turn, with no labels.

| Field | Value |
| --- | --- |
| Id | `slicechains` |
| Status | Experimental |
| Kind | script |
| Area | Surfaces and tracing |
| Run | `python3 scripts/spiralsense/slicechains.py`, `python3 scripts/spiralsense/slicechains.py --selftest` |
| Code | `scripts/spiralsense/slicechains.py` |
| Tests | `tests/test_slicechains.py` (synthetic spirals only; skipped without its packages) |
| Needs | Python 3.10 or newer (run on 3.13 and 3.14); numpy, scipy (`ndimage`, `cKDTree`), scikit-image (`skeletonize`), numcodecs (blosc chunks). Data: a scroll's m7 surface prediction zarr (binary, `...-surface-m7-L0-th0.2.zarr`, read at level 1) and its center line |
| Runs on | Any CPU; no GPU. 24 planes of PHerc0343: 72 s wall on a 4-core cloud container (measured 2026-11-17). 400 planes: 15 to 26 minutes a scroll on one Hugging Face `cpu-upgrade` Job (measured 2026-11-16) |
| Network | The volume's host over HTTPS (for open data, `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`): the zarr's level 1 `.zarray` and the chunks of each plane's core box. Nothing else |
| Writes | The `--out` JSON. With `--cache DIR`, one `TAG_L1_zZ.npz` per plane in DIR, reused on a rerun |
| Go-ahead | Not needed: CPU only, public data, local files |
| Released | Public `main` from the merge of its pull request (prepared 17 Nov 2026), v1.0 |
| License | Apache License 2.0 ([`scripts/spiralsense/LICENSE`](../../scripts/spiralsense/LICENSE)) |
| Checked | 2026-11-17 against commit `fa9acc9` |

## What it does

villa's spiral fit needs to know which way each scroll is wound: `spiral_outward_sense` is "CW" when the sheet radius grows with atan2(y, x), where y is the zarr's middle axis and x its last, and "ACW" for the mirror. The open-data catalog gives it for some scrolls through their transforms; for the rest there was no automatic way to find it.

slicechains looks at one z slice at a time. It takes the binary m7 surface prediction inside a disc round the center line, thins the sheets to one-pixel lines, cuts them at junctions and links the pieces end to end where the ends line up. A chain that winds at least one full turn round the center votes: if its radius one turn further on is larger than here, the scroll is CW. Votes from many slices are pooled into one call, or an abstention when there are too few or they disagree.

With `--symmetric` every slice is also run mirrored and its votes are added flipped, so a mirrored scroll always gets the exact opposite answer. Thinning and pixel walking are not quite mirror-equivariant, and this removes that bias by construction.

It calls a direction of the scroll's geometry. It reads no ink and says nothing about text. Its call is model output, not catalog truth.

## When to use it

- A scroll or scan has no `spiral_outward_sense` you trust, and it has an m7 surface prediction and a center line.
- You want a second, independent check of a direction you already have.

Do not use it:

- On a scroll whose core is badly crushed: few chains make a full turn there and it abstains. Use the catalog, or a traced surface.
- As truth for scoring other direction methods: it is model output.

## Quick start

```bash
pip install numpy scipy scikit-image numcodecs
python3 scripts/spiralsense/slicechains.py --selftest
curl -sL -o line0343.json https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines/resolve/main/lines/PHerc0343/PHerc0343_20250521140437_finder_umbilicus.json
python3 scripts/spiralsense/slicechains.py \
  --m7 https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0343/representations/predictions/surfaces/20250521140437-surface-20260413222639-surface-m7-L0-th0.2.zarr \
  --line line0343.json --voxel-um 8.64 --pitch 17.84 --z-edges 2093,16031 --planes 24 --symmetric --out p0343.json
```

What it printed (17 Nov 2026, 4-core container):

```
{"selftest": "PASS", "spiral_CW": {"CW": 7, "ACW": 0}, "spiral_ACW": {"CW": 0, "ACW": 7}, "rings": {"CW": 0, "ACW": 0}}
...
20/24 z=13243 CW=4 ACW=0 59s
{"mirror": false, "planes": 24, "totals": {"CW": 28, "ACW": 2, "planes_voting": 5, "unvoting_wound_chains": 0}, "call": "CW", "secs": 72.0}
```

It worked when `call` is CW or ACW. PHerc0343 is CW in the catalog. The blind test below used 400 planes; 24 is a quick look.

`--pitch` is the sheet spacing in level-0 voxels (17.84 for PHerc0343, measured from the m7 prediction's radial autocorrelation; most scrolls sit near 15 to 20). `--z-edges` is the z range to sample. The center line can be any published umbilicus in the formats below.

## Checks and controls

**The blind test** (Model output against the open-data catalog, 16 to 17 November 2026). The rule (400 planes, `--symmetric`, at least 5 votes and a 0.8 share to decide) was fixed in writing before the run, developed on six other scrolls with known direction (6 of 6 right, 498 of 511 votes), and run once on 12 scrolls with a catalog direction. The scorer read the catalog only after the answers were committed.

| Result | Count |
| --- | --- |
| Decided, right | 9 |
| Decided, wrong | 0 |
| Abstained | 3 |
| Truth among the 12 | 5 CW, 7 ACW |

One-sided binomial p = 0.5^9 = 0.0020 (bar p < 0.01). Since the truth was mixed, always answering one way could not pass. 7 of the 12 scrolls had been scored by earlier direction tests that failed or did not resolve, so they are reused truth; the result is never called held out. The four scored scrolls that are not prize-eligible, with the planes that voted out of 400: PHerc0306B ACW (113), PHerc0343 CW (83), PHerc0814 ACW (50), PHerc0841 ACW (153), all right. The other eight are prize-eligible and not named here.

**The controls.** `--mirror` flips each plane and the center line, so the call must flip; `--symmetric` makes the mirrored call the exact opposite by construction. The self-test runs a squashed, rotated, broken Archimedean spiral of each sense (each must vote its own way only) and a set of closed rings (which must not vote).

Scope: one method version (v1.0, this file), 12 test scrolls of mixed direction, one surface model (m7). Not tested on other surface predictions or on scans without an m7 prediction.

Claim label: Model output (the calls); Measurement (the counts against the catalog).

## Commands and options

### `python3 scripts/spiralsense/slicechains.py`

```
usage: slicechains.py [-h] --m7 M7 --line LINE --voxel-um VOXEL_UM
                      --pitch PITCH --z-edges Z_EDGES [--planes PLANES]
                      [--mirror] [--symmetric] [--skip-z SKIP_Z] [--quiet]
                      [--min-votes MIN_VOTES] [--min-share MIN_SHARE]
                      [--cache CACHE] [--cache-tag CACHE_TAG] --out OUT
```

`--selftest` is read before the parser, so it is not in the usage line: `python3 scripts/spiralsense/slicechains.py --selftest`.

| Option | Default | Meaning |
| --- | --- | --- |
| `--m7` | required | URL or path of the m7 surface prediction zarr (read at level 1) |
| `--line` | required | center line file: JSON list or `points`/`control_points` of {z, y, x}, or CSV lines `z,y,x` |
| `--voxel-um` | required | voxel size in um (recorded only) |
| `--pitch` | required | sheet spacing in level-0 voxels |
| `--z-edges` | required | `z0,z1` in level-0 voxels |
| `--planes` | 104 | planes sampled evenly inside (z0, z1) |
| `--mirror` | off | flip each plane and the center line (control: the call must flip) |
| `--symmetric` | off | also run each plane mirrored and add its votes flipped (used by the blind test) |
| `--skip-z` | none | `Z0-Z1[,Z0-Z1...]` windows whose planes are dropped |
| `--quiet` | off | print no votes and no call (for logs that must stay blind) |
| `--min-votes` | 5 | fewest votes to decide |
| `--min-share` | 0.8 | share the larger side needs to decide |
| `--cache` | none | folder for fetched planes, reused on a rerun |
| `--cache-tag` | `m7` | file name prefix in the cache |
| `--out` | required | output JSON |
| `--selftest` | | run the synthetic self-test, print JSON, exit 0 on PASS |

## Python API

A script, not a package; the test file loads it with `importlib`.

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `plane_chains(img, cx, cy, pitch_px, r_px=None)` | list of chain dicts (`turns`, `gain_l0`, `consistency`, `r_median_l0`, `vote`) | nothing of its own | one binary level-1 plane; center and pitch in level-1 pixels |
| `synthetic(sense, rings=False)` | `(img, cx, cy, pitch)` | nothing of its own | the self-test's spiral of `sense` (`CW` or `ACW`), or closed rings |
| `fetch_plane(url, line, z)` | `(img, origin, centre)` | `RuntimeError('chunk Z/C failed')` after retries | reads one plane's core box |

## Inputs

- m7 surface prediction: OME-Zarr v2, uint8 binary, blosc chunks, level 1 (2x downsampled), axes z, y, x.
- Center line: level-0 voxel coordinates of the scroll's umbilicus (published lines, for example the [vesuvius-center-lines](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines) dataset).

## Outputs

Prints one line per voting plane (unless `--quiet`), then a JSON summary. The `--out` JSON:

| Field | Type | Meaning |
| --- | --- | --- |
| `call` | string | `CW`, `ACW` or `abstain` |
| `totals.CW`, `totals.ACW` | int | pooled votes (with `--symmetric`, stored plus flipped mirrored) |
| `totals.planes_voting` | int | planes with at least one vote |
| `totals.unvoting_wound_chains` | int | chains of a full turn whose sign did not hold on 0.6 of their overlap |
| `rule` | object | the constants used |
| `planes`, `planes_dropped`, `secs` | int, int, float | planes used, planes dropped by `--skip-z`, wall seconds |
| `rows[].chains[]` | list | per chain: `turns`, `gain_l0` (median radius change over one turn, level-0 voxels; positive is CW), `consistency`, `r_median_l0`, `vote` |

| Exit code | Meaning |
| --- | --- |
| `0` | ran (whatever the call), or the self-test passed |
| `1` | the self-test failed |
| `2` | wrong arguments |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `"call": "abstain"` with few votes | Crushed core or wrong pitch: few chains make a full turn | Widen `--z-edges`, add `--planes`, check `--pitch` |
| `"call": "abstain"` with many votes on both sides | Center line off the scroll's center | Check the center line against the scan |
| `RuntimeError: chunk.../...failed` after retries | The host refused or a chunk could not be read five times | Retry later; check the URL and the network |

## How it works

1. For each plane z, read the level-1 m7 chunks covering a disc of radius 1500 level-0 voxels (`R_L0`) round the center line at z.
2. Thin the sheets to lines (`skeletonize`), remove 3 by 3 pixels round every junction, keep pieces of at least 8 pixels (`MINLEN`).
3. Link piece ends greedily: gap at most 1.0 pitch (`GAP_F`), ends antiparallel within 35 degrees (`COS_MIN`), forward progress at least -1.5 pixels, lateral offset at most 0.25 pitch (`LAT_F`), no cycles.
4. For each chain that winds at least one turn (`MIN_TURNS`), sample its radius at 64 angles per turn and take the median of r(theta + 2 pi) - r(theta). It votes CW when that is positive, ACW when negative, if the sign holds on at least 0.6 of the overlap (`MIN_CONS`).
5. Pool the votes over planes; decide with at least `--min-votes` and a share of at least `--min-share`, else abstain.

## Cost and time

Measured: 72 s for 24 planes of PHerc0343 on a 4-core cloud container (2026-11-17); 15 to 26 minutes for 400 planes per scroll on Hugging Face `cpu-upgrade` (2026-11-16). Most of the time is reading chunks. Rents nothing when run locally.

## For agents

- **Command:** `python3 scripts/spiralsense/slicechains.py --m7 URL --line LINE --voxel-um V --pitch P --z-edges Z0,Z1 --planes 400 --symmetric --out OUT.json`
- **Parse:** `call` and `totals` in `OUT.json`, or the last stdout line.
- **Rerun:** safe; `--out` is overwritten; `--cache` makes reruns fast.
- **Success:** exit 0 and `call` CW or ACW with `totals` meeting the rule.
- **Not a pass:** a call from a few votes on one plane; a call with `--min-share` lowered after looking.
- **Go-ahead:** Nothing.
- **Never:** write a call into a catalog as truth; call it held out on scrolls already scored.

## Tests

`python -m unittest tests.test_slicechains -v`: each synthetic sense votes its own way, the mirror flips the vote, closed rings do not vote, and the `--selftest` CLI passes. They do not touch real data or the network.

## History

- 2026-11-17: released v1.0, the rule of the blind test (16 Nov 2026) ([#358](https://github.com/ChaseHendrick/Scrolls/pull/358), `5760897`).

## Related

- [ringleader.md](ringleader.md): labels every sheet in a slice with its winding; uses the same m7 input.
- [Center Finder](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines): center lines it needs.
- `slicechains_1116` in [results.json](../results.json): the blind test's counts.
