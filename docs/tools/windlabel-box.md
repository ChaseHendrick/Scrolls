# windlabel-box: relative windings in a box, from published predictions

`python -m kit windlabel-box` grows chains of sheet crossings around a point on a published surface prediction, cuts them where lasagna's grad_mag sees more than one sheet, and writes villa's `relative_windings.json` for a spiral fit; a VC3D plugin runs it at the focus point.

| Field | Value |
| --- | --- |
| Id | `windlabel-box` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit windlabel-box`, `python3 plugins/run_kit.py windlabel-box` (the VC3D plugin `plugins/scrolls-windlabel-box.json`), `from kit import windlabel_box` |
| Code | `kit/windlabel_box`, `kit/windlabel_box/__init__.py` (`cmd_windlabel_box`), `plugins/scrolls-windlabel-box.json` |
| Tests | `tests/test_windlabel_box.py`, `tests/test_plugins.py` (the manifest) |
| Needs | Python 3.10 or newer, numpy and scipy; numcodecs for blosc-compressed zarrs such as the open-data m7; a published binary surface prediction at level 0 (such as the organizers' m7) and the same scroll's published lasagna grad_mag; the scroll's umbilicus in the prediction's level-0 voxels. The plugin needs VC3D with the Plugins menu (villa branch `vc3d-plugins`, not yet in villa main) and an attached umbilicus |
| Runs on | Any CPU. Synthetic spiral (240 x 240 x 48 voxels, 30 seeds): about 1 s. PHerc0139 over HTTPS from the open-data bucket: 13 s for a 512 voxel box with 200 seeds, about 25 s with 1,000 seeds (18 boxes in 7 min 34 s; measured 2026-10-24, 4-core cloud container) |
| Network | Reads the prediction, the grad_mag and a `*.lasagna.json` manifest over HTTPS when given URLs, such as `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (anonymous); nothing with local zarrs |
| Writes | In `--out` (created): `chains.json`, `features.json`, `split.json`, `relative_windings.json`, `flags.json`, `export.json`. VC3D runs it in `~/.vc3d/plugin-runs/scrolls.windlabel-box/TIME/` and adds the windings as point collections |
| Go-ahead | Not needed to run it: it reads published predictions and writes local files. Output from prize-eligible scrolls stays private until the prize announcement |
| Released | Public `main` from the merge of its pull request (prepared 24 Oct 2026); a line of the Scrolls kit entry in the README's "Released tools", id `windlabel-box` |
| Checked | 2026-10-24 against commit `81e5ead` |

## What it does

A spiral fit of a whole scroll (villa's `spiral-fitting`) is steered by relative windings: points along a line from the core, each labeled with how many turns of papyrus (windings) it lies outward of the first. People click these in VC3D, and the organizers' winding constraints page asks for a generator that can say how sure it is. `kit windlabel-box` makes them in a box around one point from published predictions only, with no person in between.

It draws seeds on the surface prediction (a model's voxel map of where papyrus sheets are; for the open data usually m7, the organizers' binary surface model output) inside a cube of `--box` voxels centered on `--point`. From each seed it fits the local plane of the sheet, marches along the sheet's normal to the next sheet, recenters there and goes on, in both directions, counting 0 at the seed and one more per sheet outward (outward is set by the umbilicus, the scroll's center line). A step is kept only when the next sheet is thin, at a spacing in line with the chain's earlier steps and the normal turns little (chain rule version 1, digest `0e53e0ae5016`). Then it integrates lasagna's grad_mag (the published lasagna model's sheet-density channel) along every step: the median over seven parallel rays times 0.765 is about 1 for a step across one sheet. Every step above 1.0 is cut, so each piece only claims counts the grad_mag agrees with (split rule v2, digest `cd273aed7673`; `--split-rule v1` cuts above 0.95, digest `c6d2eecbebc2`). The pieces with two or more crossings become villa's relative-winding point collections; the cut steps and other places worth a look become `flags.json`.

It never computes a prediction or a grad_mag: it refuses without them. It needs the umbilicus: an axis guessed from the box's own sheets pointed the wrong way for most chains in 4 of 6 PHerc0139 boxes of 512 voxels. It does not fit a spiral, does not trace a surface and says nothing about ink. Its windings are model output from predictions, not a reading; check them with the flags, and with [windconsistency](windconsistency.md) before a fit.

## When to use it

- Making relative-winding constraints around one place of a scroll that has a published surface prediction and lasagna grad_mag, from VC3D (**Plugins > Windings > Relative windings in a box**) or the command line.
- Seeding or checking hand-clicked windings: the output loads as point collections next to them.

Do not use it:

- On a scroll with no published surface prediction or lasagna grad_mag: make or fetch them first (villa's surface and lasagna models).
- Without the scroll's umbilicus: attach one in VC3D (the [Center Finder](umbilicus.md) plugin makes one), or pass `--umbilicus`. `--estimate-axis` exists but is unreliable in small boxes.
- To check whether a set of winding counts contradicts itself: use [windconsistency](windconsistency.md).
- As a reading or as evidence about ink: it is geometry only.

## Quick start

```bash
B=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/representations/predictions
python -m kit windlabel-box \
    --prediction $B/surfaces/20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr \
    --grad-mag $B/lasagna/20260102150214-lasagna-20260419180421-L2/PHerc0139-20260102150214-lasagna-20260724_grad_mag.ome.zarr \
    --base-affine BASE.json --umbilicus UMB.json --point 4000,4100,5080 --out RUN --json
```

- `BASE.json`: `{"matrix": M}`, the 3 x 4 matrix from the m7 scan's voxels (volume `20250728140407`) to the lasagna scan's (`20260102150214`), from the open-data catalog `metadata.json` (`samples.PHerc0139.sample.properties.volume_transforms`).
- `UMB.json`: PHerc0139's umbilicus (`PHerc0139/representations/umbilicus/20260102150214-umbilicus-20260826112529.json` in the bucket) moved into the m7 scan's voxels with the inverse of that matrix, as villa's umbilicus JSON or a `[[z, y, x], ...]` list.
- `RUN`: a new folder.

On 2026-10-24 (4-core cloud container) a box like this, with 200 seeds, took 13 s and printed (excerpt):

```
"ok": true, "collections": 211, "points": 696, "pieces": 211, "steps": 485, "split_steps": 142,
"flags": {"cut": 0, "contact": 0, "spacing": 179, "split": 142},
"checks": {"relative_windings.json": {"ok": true, "issues": []}, "flags.json": {"ok": true, "issues": []}}
```

It worked when the exit code is 0 and `ok` is true: both files pass villa's and VC3D's rules. On a synthetic spiral the tests' `write_inputs` (in `tests/test_windlabel_box.py`) makes a prediction, grad_mag, manifest and umbilicus that run in about a second.

## Checks and controls

- **Second scroll, PHerc1667 (Model output, 24 Oct 2026).** Scan `20231117161658` (7.91 um), its published hand windings w028 to w041, m7 run with the organizers' published model, the published lasagna of the 2.4 um scan, the released Center Finder line as umbilicus; every rule and number fixed before any box had a prediction. Split rule v2 on 20 boxes no test had scored: **0.9786 step accuracy on 5,938 judged steps** (lower bound 0.9671 over 35 blocks), keeping 75.9 % of the uncut chains' judged steps, which scored 0.9486; random control 97.5th percentile 0.9527, skip and shift controls 0.017 and 0.077. Per box 0.738 to 1.0. Split rule v1 failed its own frozen test on 18 other PHerc1667 boxes: 0.9693 right (lower bound 0.951) but only 68.3 % kept, under the 70 % floor. The cut at 1.0 was chosen after that result, on spent boxes of both scrolls, and then tested on the fresh boxes. Evidence: [windlabel-box-1667-20261024](../evidence/windlabel-box-1667-20261024/README.md).
- **More fresh PHerc1667 boxes, against two community winding tools (Model output, 29 Oct 2026).** Same scan, published hand windings w028 to w037 (w038 to w041 left out by a stack audit fixed beforehand), m7 and published lasagna, Center Finder umbilicus, split rule v2 at commit `a77ef4a`; every rule, bar and comparison was fixed before any box had a prediction. On 24 boxes no earlier test had scored, the split chains got **0.9706 of 7,937 judged steps right** (one-sided 95 % lower bound 0.9575 over 43 blocks; bar 0.92), keeping 75.4 % of the uncut chains' judged steps (bar 70 %); random control 97.5th percentile 0.939, skip and shift controls 0.043 and 0.036. On the same boxes, truth and buffer, E1 from [pscamillo/constraint-gauge](https://github.com/pscamillo/constraint-gauge) (`a72c423`), asked for the winding count across each of the chains' own steps, was right 0.914 of the time (its answers against shuffled truth: 0.226), and the certified hops of [millerandmuller/winding-phase](https://github.com/millerandmuller/winding-phase) (`95583f3`) were right 0.927 of the time (hops re-paired at random: 0.216). windlabel-box was ahead of E1 on the blocks both judged (0.971 against 0.914, lower bound of the lead +0.043) and at matched coverage (0.971 against 0.929, +0.025), and ahead of winding-phase at matched coverage (0.978 against 0.942, lower bound +0.029). Both tools read the same lasagna through our reader, and winding-phase's density scale was calibrated on these boxes' own slices without labels. PHerc1667 is a development scroll for split rule v2, whose cut was chosen partly on the earlier PHerc1667 boxes above, so these boxes are held out by position, not by scroll. The same test on PHerc0172 read void before any of its steps was scored: its axis check found no hand-traced winding at three of the four box heights.
- **Fresh boxes on PHerc0139 (Model output, 24 Oct 2026), split rule v1.** 18 boxes of 512 voxels with 1,000 seeds, placed from the hand-traced windings alone before any chain was grown, scored against PHerc0139's published hand windings w023 to w040 with every height scored by an earlier windlabel run left out; the readout was fixed beforehand. The split chains scored **0.9758 step accuracy on 13,969 judged steps** (one-sided 95 % bootstrap lower bound 0.968 over 40 blocks of box by 30 degree sector), keeping 71.2 % of the uncut chains' judged steps, which scored 0.9223. Bar: 0.95, lower bound above 0.92, at least 70 % kept. Per box 0.939 to 1.0. On these same boxes, scored again after the PHerc1667 result (so not a fresh test), v2 keeps 77.4 % at 0.9716. One disclosure: four of the 18 reference windings are among the PHerc0139 segments now held back for evaluation. This test read them before that hold, and its steps were not saved per winding, so the score cannot be recounted without them. The PHerc1667 result does not use PHerc0139.
- **Controls that must fail.** A random control cuts as many steps as the rule but at random: median 0.9229, 97.5th percentile 0.9253, so the rule's gain is not from cutting alone. The skip control (every other crossing, counts halved, so each step really crosses two windings) scored 0.022, and the shift control (one added to every count outward of the seed) 0.065; both must be at most 0.5.
- **Where it misses.** On six earlier boxes in PHerc0139's development heights it scored 0.9415, under the bar, all of the shortfall near z 7000, where m7, lasagna and the grad_mag integral read one winding and the hand windings read two. Whether the sheets are pressed together there or the hand windings are off was not settled from the CT. The same six boxes without an umbilicus scored 0.8819.
- **Limits.** Two scrolls. On PHerc0139 the split rule was developed on the same windings, m7 and lasagna, held out in position only, and v2's numbers there are not from a fresh test; PHerc0139 is in villa's tracing training configs. Whether villa's tracing or lasagna models saw PHerc1667's windings is not known to us. Only 13 to 15 % of steps can be judged at all.
- **Inside VC3D (24 Oct 2026).** A VC3D build from the `vc3d-plugins` branch (see [vc3d-plugins](vc3d-plugins.md)) parsed, expanded and ran this manifest on a small PHerc0139 box: the command exited 0 with only JSON on stdout, and VC3D's point collection reader loaded its 227 collections and 1,001 points with no winding changed and every collection still relative; VC3D started with the plugin folder and skipped nothing. One problem in that branch: when the Plugins menu loads a point collection result it copies the points but not the collection's metadata, so these relative windings show up as absolute. A small fix (keep each collection's metadata) passed the same build test and is part E of villa PR #2219 (commit `7d205f6e4`, 2026-10-28): with it, all 227 collections loaded through the Plugins menu keep their relative windings, against 0 of 227 without it. On a build from the older `vc3d-plugins` branch, mark the collections relative by hand after loading, or open `relative_windings.json` with VC3D's own point collection loader.

Claim label: Model output, for chains, counts, cut steps and exported windings; the accuracies are against PHerc0139's and PHerc1667's published hand windings.


## Commands and options

### `python -m kit windlabel-box`

```
usage: python -m kit windlabel-box [-h] [--prediction PREDICTION]
                                   [--grad-mag GRAD_MAG]
                                   [--base-affine BASE_AFFINE]
                                   [--gm-scaledown GM_SCALEDOWN]
                                   [--gm-decode GM_DECODE] --point POINT
                                   [--box BOX] [--seeds SEEDS] [--rng RNG]
                                   [--split-rule {v1,v2}]
                                   [--umbilicus UMBILICUS] [--estimate-axis]
                                   [--workers WORKERS] --out OUT [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--prediction PREDICTION` | none | the volume's surface prediction: zarr folder or https URL (binary, level 0, sheet above 127) |
| `--grad-mag GRAD_MAG` | none | lasagna grad_mag: a manifest (.json or *.lasagna.json URL) or a grad_mag OME-Zarr |
| `--base-affine BASE_AFFINE` | `identity` | 'identity' or a JSON 3 x 4 matrix file from prediction voxels to the lasagna base grid |
| `--gm-scaledown GM_SCALEDOWN` | none | grad_mag zarr level over the base (default: the manifest's, else 4) |
| `--gm-decode GM_DECODE` | none | grad_mag stored value to density per base voxel (default: the manifest's, else 0.25 / 1000) |
| `--point POINT` | required | the box center x,y,z in level-0 voxels (VC3D's {point}) |
| `--box BOX` | `512` | box edge in voxels (default 512) |
| `--seeds SEEDS` | `200` | seed count (default 200) |
| `--rng RNG` | `0` | seed RNG (default 0) |
| `--split-rule {v1,v2}` | `v2` | split rule: v2 cuts at gm_x above 1.0, v1 at 0.95 (default v2) |
| `--umbilicus UMBILICUS` | none | villa umbilicus JSON in the prediction's level-0 voxels (VC3D's {umbilicus}); it sets which way is outward |
| `--estimate-axis` | off | without an umbilicus, estimate the axis from the seed normals (unreliable in small boxes) |
| `--workers WORKERS` | `2` | threads for grad_mag reads (default 2) |
| `--out OUT` | required | run folder (VC3D's {output}) |
| `--json` | off | print one JSON object |

## Inputs

- **Surface prediction** (`--prediction`): a zarr folder or `http(s)://` URL, OME-Zarr group or bare array, zarr v2 or v3, read at level 0; axes (z, y, x), any integer dtype, sheet where the value is above 127 (m7 is 0 or 255). Sharded arrays are read through their index; zarr filters and the transpose codec are not.
- **grad_mag** (`--grad-mag`): a lasagna manifest (a local `.json` or a `*.lasagna.json` URL; its `grad_mag` group, `scaledown`, `grad_mag_factor` and `grad_mag_encode_scale`; `source_to_base` must be 1), or a grad_mag OME-Zarr whose level 0 is the stored level `--gm-scaledown` (default 4) over the lasagna base grid, decoded by `--gm-decode` (default 0.25 / 1000).
- **Base affine** (`--base-affine`): `identity` when the prediction's voxels are the lasagna base grid, else a JSON 3 x 4 or 4 x 4 matrix (or `{"matrix": ...}`) on (x, y, z, 1) from prediction voxels to the base grid.
- **Umbilicus** (`--umbilicus`): villa's umbilicus JSON (`control_points` or `points` with x, y, z) or a `[[z, y, x], ...]` list, in the prediction's level-0 voxels. VC3D passes the attached one.
- **Point** (`--point`): x,y,z in the prediction's level-0 voxels (VC3D's focus point).

## Outputs

Files in `--out`:

| File | What it is |
| --- | --- |
| `relative_windings.json` | villa's point collections (`vc_pointcollections_json_version` "1"), one per piece of two or more crossings, points with `p` (x, y, z level-0 voxels) and `wind_a` (windings outward of the piece's first point), `metadata.winding_is_absolute` false |
| `flags.json` | point collections of places to check: `cut`, `contact` and `spacing` stops of the chains and every `split` step's midpoint |
| `chains.json` | the uncut chains: `rule`, `rule_digest`, `box`, `axis`, `axis_source`, `summary` (stop reasons) and `chains` (`seed`, `points`, `counts`, `normals`, `steps`, `stop`) |
| `features.json` | `gm_x` per step and the grad_mag source |
| `split.json` | the chains cut at the split steps |
| `export.json` | the summary below, with input hashes and timings |

It prints (one JSON object with `--json`):

| Field | Type | Meaning |
| --- | --- | --- |
| `ok` | bool | both files pass villa's and VC3D's rules |
| `files` | object | path of each file above |
| `collections`, `points` | int | point collections and points in `relative_windings.json` |
| `pieces` | int | exported pieces |
| `steps` | int | steps in the exported pieces |
| `split_steps` | int | steps the split rule cut |
| `flags` | object | flagged places by kind |
| `checks` | object | `ok` and `issues` per file |
| `vc3d` | object | `tool`, `point`, `box_edge`, `seeds`, `rng`, `prediction` (location, shape, chunks), `chain_rule_version`, `umbilicus`, `wall_seconds` |
| `note` | str | that the output is model output, not a reading |

| Exit code | Meaning |
| --- | --- |
| `0` | Written, and both files pass villa's and VC3D's rules |
| `1` | Written, but a file check failed (for example no piece of two crossings in the box); read `checks` |
| `2` | Refused before any work, or failed; the reason is on stderr after `refused:` |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `the point...is not x,y,z in level-0 voxels; set the focus point in VC3D` | `--point` is not three numbers | Set the focus point in VC3D, or give x,y,z |
| `...must be above 0, not...` | `--box` or `--seeds` is 0 or negative | Give a positive number |
| `--base-affine...is neither 'identity' nor a JSON matrix file` | `--base-affine` names no file | Give `identity` or a matrix file |
| `--base-affine...: a 3 x 4 or 4 x 4 matrix on (x, y, z, 1), not...` | The matrix file holds another shape | Write a 3 x 4 or 4 x 4 matrix |
| `no surface prediction given: open or name the volume's published surface prediction (for example its m7 zarr). This tool does not compute one` | `--prediction` is empty | Name the published prediction |
| `no grad_mag source given: name the scroll's published lasagna grad_mag (its manifest or its grad_mag zarr). This tool does not compute one` | `--grad-mag` is empty | Name the published grad_mag |
| `no umbilicus given: attach the scroll's umbilicus in VC3D (File > Attach Umbilicus) or pass --umbilicus. --estimate-axis guesses the axis from the box's own sheets instead, which got the outward direction wrong in 4 of 6 PHerc0139 boxes of 512 voxels` | No `--umbilicus` and no `--estimate-axis` | Attach the umbilicus in VC3D or pass `--umbilicus` |
| `--umbilicus...: no such file` | `--umbilicus` names no file | Give the umbilicus file |
| `kit windlabel-box needs numpy and scipy (...)` | numpy or scipy is missing | Install them |
| `...is not a number` | `--box` or `--seeds` is not a number | Give a number |
| `cannot open the surface prediction...:...:...` | The prediction does not open as a zarr (wrong path, a missing codec such as numcodecs for blosc) | Check the path and install numcodecs |
| `the base affine is a 3 x 4 or 4 x 4 matrix on (x, y, z, 1)` | The grad_mag affine has another shape | Fix the matrix |
| `...: no umbilicus points` | The umbilicus file has no points | Use a real umbilicus |
| `no usable normals for an axis estimate` | `--estimate-axis` found no sheet normals | Give `--umbilicus` |
| `too few normals in every slab for an axis estimate` | `--estimate-axis` found too few normals | Give `--umbilicus` or more seeds |
| `feature...needs a features file (records with chain, j and...)` | Internal: the export was given no features | Report it |
| `not a windlabel calibration table (kind)` | Internal: a wrong calibration table | Report it |
| `the affine is a 3 x 4 or 4 x 4 matrix on (x, y, z, 1)` | Internal: a wrong export affine | Report it |
| `--min-step-p needs a calibration table` | Internal: export called without a table | Report it |
| `--at is x,y,z in level-0 voxels` | The point did not parse for the seed box | Give x,y,z |
| `--half must be a positive number of voxels` | The box edge is not positive | Give a positive `--box` |
| `kit windlabel needs numpy` | numpy is missing | Install numpy |
| `...is not an S3 URL; give the .lasagna.json URL itself` | A grad_mag manifest URL is a folder outside S3 | Give the `.lasagna.json` URL itself |
| `...: expected one .lasagna.json in the folder, found...` | The manifest folder holds none or several manifests | Give the manifest URL itself |
| `...is not JSON:...` | The manifest is not JSON | Check the URL |
| `the two points coincide` | A step with both ends at one point | Report it |
| `kit windpair needs numpy (...)` | numpy is missing | Install numpy |
| `an affine is 3 x 4, acting on (x, y, z, 1)` | A field affine has another shape | Fix the matrix |
| `a volume needs a location or a store` | Internal: a volume opened with nothing | Report it |
| `...: a pyramid level has no header` | A zarr level lacks its `.zarray` or `zarr.json` | Check the zarr |
| `...level...: sharded arrays are not read here` | A sharded array where sharding is not read | Use an unsharded copy |
| `...level...: zarr filters...are not decoded here` | The array uses zarr filters | Rewrite the array without filters |
| `...level...: shard index codecs...are not read here` | The shard index uses codecs this reader lacks | Rewrite the array |
| `...level...inner chunk...:...values, expected...` | An inner chunk has the wrong size | Check the zarr |
| `...level...: the transpose codec is not read here` | The array uses the transpose codec | Rewrite it in C order |
| `...level...: the transpose codec changes the axis order and is not read here; rewrite the array without it, in C order` | The array uses the transpose codec | Rewrite it in C order |
| `...level...chunk...:...values, expected...` | A chunk has the wrong size | Check the zarr |
| `...: shard index has...bytes, expected...` | A shard index has the wrong size | Check the zarr |
| `...: shard index CRC32C does not match` | A shard index is corrupt | Fetch it again |
| `...level...inner chunk...: does not decode (...)` | An inner chunk does not decode (a missing codec) | Install numcodecs |
| `...: range...+...gave...` | A range read came back short | Rerun; check the network |
| `...level...chunk...: does not decode (...)` | A chunk does not decode (a missing codec such as blosc) | Install numcodecs |
| `no lasagna manifest at...` | The local manifest path does not exist | Check the path |
| `no grad_mag source given; this tool reads a published lasagna grad_mag and never computes one` | The grad_mag source is empty | Name the published grad_mag |
| `grad_mag scaledown...or decode...is not usable` | `--gm-scaledown` or `--gm-decode` is unusable | Give a level of 0 or more and a positive decode |
| `kit windlabel-split needs numpy` | numpy is missing | Install numpy |
| `...: source_to_base...is not 1` | The lasagna run is not on its base grid | Use a run with `source_to_base` 1 |
| `...: no grad_mag group` | The manifest has no grad_mag group | Use a full lasagna manifest |
| `manifest lacks a usable grad_mag_factor (...) or encode scale (...)` | The manifest's decode values are missing | Give `--gm-decode`, or use the grad_mag zarr |
| `cannot open the grad_mag zarr...:...:...` | The grad_mag zarr does not open | Check the path |
| `grad_mag: level...shape...is not ceil(.../ 2**...) =...` | The stored level does not fit the manifest's base shape | Check `--gm-scaledown` |
| `chain...: counts...and...are not one apart` | Internal: chains not grown under rule version 1 | Report it |

## How it works

1. Open the prediction (metadata only) and the grad_mag; refuse on anything missing.
2. Seeds: `--seeds` random voxels on the sheet inside the box (`seeds_on`, rng `--rng`).
3. Chains (`grow_chains`, `RULE` version 1): plane fit in a radius of 5 voxels (planarity at least 4), steps of 4 to 40 voxels along the normal sampled every 0.5 voxels over five rays 2 voxels apart, next sheet at most 9 voxels thick, spacing within 0.55 to 1.6 of the median of the last 4 steps, normal turn at most 35 degrees, at most 40 steps a side, then a trim pass.
4. gm_x per step (`features_doc`): lasagna grad_mag sampled along 7 parallel rays, integrated, the median times `k_s` 0.765.
5. Split (`split_chains`, `PARAMS_V2` `split-v2` by default): cut each step with gm_x above `abs_own` 1.0 (0.95 under `--split-rule v1`, `PARAMS` `split-v1`); pieces keep their own counts.
6. Export (`export_split`): pieces of two or more crossings as villa point collections, flags for stops and cuts, both files checked against villa's and VC3D's rules (`check_pcl`).

The code is a copy, function by function, of Scrolls-private's `kit windlabel`, `kit windlabel-split` and their helpers (only what this command runs), made by its release script and tested to write the same files.

## Cost and time

CPU only, no rented compute. Measured 2026-10-24 on a 4-core cloud container reading PHerc0139 over HTTPS: 13 s for a 512 voxel box with 200 seeds, 18 boxes with 1,000 seeds in 7 min 34 s (about 25 s each), most of it chunk downloads. Synthetic spiral: about 1 s. Memory: Not measured; chunks are cached in memory only.

## For agents

- **Command:** `python -m kit windlabel-box --prediction PRED --grad-mag GM --umbilicus UMB.json --point X,Y,Z --out RUN --json`
- **Parse:** stdout is one JSON object: `ok`, `files["relative_windings.json"]`, `collections`, `split_steps`, `checks`
- **Rerun:** Safe; it overwrites the files in `--out`. The same inputs and `--rng` give the same chains
- **Success:** exit 0 and `ok` true
- **Not a pass:** a run with `--estimate-axis` (check `chains.json` `axis_source`); a run on a scroll other than PHerc0139, where accuracy is untested; exported windings across places `flags.json` marks
- **Go-ahead:** Nothing to run it; sharing output from a prize-eligible scroll needs the owner's yes
- **Never:** call the windings a reading; compute a prediction or grad_mag inside the plugin; edit the copied rule to change its numbers (a new rule needs a new test)

## Tests

```bash
python -m unittest tests.test_windlabel_box tests.test_plugins -v
```

4 tests, about 2 s (2026-10-24, skipped without numpy and scipy): on a synthetic spiral with a grad_mag doubled from x = 150, the command exits 0, writes files VC3D loads, keeps at least 95 % of exported winding differences on the true wraps, cuts only near the doubled grad_mag and records both rule digests; split rule v2 keeps the same chains and cuts a subset of v1's steps; it refuses without a prediction, a grad_mag, an umbilicus, with a missing umbilicus file, an unopenable prediction or manifest, and bad numbers, writing nothing; `python -m kit windlabel-box --help` works. `tests.test_plugins` checks the manifest against VC3D's rules and kit's parser. They do not run on real data or in a VC3D build; the real-data and VC3D checks are in Checks and controls.

## History

- 2026-10-24: first public version, after a PASS on 18 fresh PHerc0139 boxes ([#190](https://github.com/ChaseHendrick/Scrolls/pull/190)).

## Related

- [windconsistency](windconsistency.md): check that the exported counts can all hold at once before a fit.
- [vc3d-plugins](vc3d-plugins.md): the Plugins menu and how VC3D runs this.
- [umbilicus](umbilicus.md): the Center Finder, which makes the umbilicus this needs.
- `windlabel_box_checks` in [`results.json`](../results.json): the numbers above.
