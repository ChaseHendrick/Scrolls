# ScrollSim Hard Cases: exact 3D hard-case sheet layouts

Makes exact 3D papyrus sheet layouts of the hard cases (hairpins, U folds, bends, accordions, crushed mush, delamination, cracks, frayed edges, contact, spiral centers) as continuous fields, with a physics CT render and training tiles in the Synthetic-Slices format.

| Field | Value |
| --- | --- |
| Id | `hardcases` |
| Status | Experimental |
| Kind | kit module |
| Area | Surfaces and tracing |
| Run | `python -m kit hardcases tiles OUT.npz --n N --seed S`, `python -m kit hardcases volume OUT.npz --kind K --seed S --shape Z,Y,X`, `python -m kit hardcases info`; library `from kit import hardcases` |
| Code | `kit/hardcases.py` |
| Tests | `tests/test_hardcases.py` |
| Needs | Python 3.10 or newer, numpy, scipy (ndimage). No scroll data |
| Runs on | CPU. One 256 px tile (layout, raster, render) 0.15 to 0.4 s in a 4-core cloud container (24 Nov 2026); 2,000 tiles about 2 minutes on 4 workers |
| Network | None |
| Writes | `tiles`: one `.npz` shard; `volume`: one `.npz` with `ct`, `sheet`, `lines`, `air`, `crack`, `zone` |
| Go-ahead | Not needed |
| Released | Scrolls kit, with ScrollSim (25 Nov 2026) |
| Checked | 2026-11-25 against commit `4536292` plus this module (14 tests, 4 s; the quick start's output below) |

## What it does

Synthetic-Slices v0.2 (vincentl065, code MIT, [repository](https://github.com/vincentl065/Synthetic-Slices), read 24 Nov 2026) draws exact 2D sheet layouts for hard cases and paints CT around them. Its own limits list "2D slices only. No spiral centres and no 3D volumes yet". Hard Cases rebuilds those hard cases as 3D fields for ScrollSim: each layout is a function of continuous position (z, y, x) giving a sheet coordinate f, with sheets centered on fixed levels of f. Any block, any slice direction (axial or side) and any grid gives the same sheets, and every sheet keeps one exact id (a hairpin's folded sheet keeps its id round the fold).

Kinds (`KINDS`): plain, spiral (flattened spiral with its center in or near the box), hairpin, tight_u, tight_bend (offsets of an arc with tangent arms), accordion (rounded zig-zag, optionally compact), mush (crushed, short weak waviness), delamination (one sheet's plies part over a lens, both keeping the id), crack (jagged fault, sheets cut, offset and receding, the opening is air), edge (outer edge, last sheets ending raggedly, air beyond). Extras: contact (two neighbors pressed together over a patch by a monotone level squeeze, lines still at least 3 px apart) and a crushed patch.

Beside the labels it writes a hard-case zone map (`ZONES`: fold, contact, delamination, crack, crushed, edge, center bits), so a detector or tracer can be scored per hard case. The physics render draws two plies per sheet, a fiber texture, gap debris, the crushed look, inclusions and debris, point spread, a phase-contrast rim, white, ramp and correlated noise and slow gain, all randomized per tile.

Version 1.1 (26 Nov 2026) adds two context managers that change the render's draw bounds without changing anything else: `realism(sd=, psf=, ply_w=, rim=, gap=, pitch=)` sets the noise level, point spread, ply width, phase rim, gap fill and a sheet-spacing factor, and `dense(fill=, core=)` sets how much of each gap a sheet fills and how bright the core between its plies is. With no bounds set the tiles are the version 1.0 tiles bit for bit (tested). [simreal](simreal.md) measures real CT from its grey values and fits these bounds; [simcritic](simcritic.md) judges how real the result looks.

It is a simulator. A score on its tiles is model output on synthetic data and says nothing about a real scroll.

## When to use it

- To make training or test tiles with exact sheet lines and instance ids for a sheet detector or a tracer.
- To make a 3D block of one hard case with exact labels (`volume`).
- To score a method per hard case on synthetic data, with the zone map.
- To render tiles closer to one scan's look, with bounds from [simreal](simreal.md) (`tiles(..., dense_look=simreal.PRESETS["343p"])`).

Do not use it:

- for a whole rolled scroll with windings, ink and a scan model: use [scrollsim2](scrollsim2.md);
- as evidence about real CT: a detector trained here needs its own test on real labels, with a ridge filter as the baseline.

## Quick start

```bash
python -m kit hardcases tiles /tmp/t.npz --n 4 --seed 5
python -m kit hardcases volume /tmp/v.npz --kind hairpin --seed 3 --shape 32,128,128
```

It printed (25 Nov 2026, Scrolls `main` plus this module): `{"out": "/tmp/t.npz", "n": 4, "kinds": {"edge": 1, "plain+contact": 1, "tight_bend": 1, "tight_bend_compact": 1}}`. Success: exit 0 and every key of the shard present with N tiles.

## Checks and controls

The tests check that every kind rasterizes with lines of different sheets at least 3 px apart (spirals excepted, whose winding ids meet at the branch cut and are relabeled per connected piece in tiles), that a block cut from a bigger block and an axial slice equal the bigger block voxel for voxel, that the level maps used for contact and delamination are monotone, that cracks hold no sheet or line, that the edge has air beyond the last sheet, that delamination's opening is bordered by the same sheet id on both sides, and that rendered sheets are brighter than air.

Cross-scroll validation: not applicable to the generator itself (it reads no scroll). Any claim that a detector trained on these tiles transfers to real CT needs a frozen test on real labels from more than one scroll, with a ridge filter and a shifted-label control; none is published here.

Claim label: Model output (synthetic data) for everything it makes.

## Commands and options

### `python -m kit hardcases tiles`

```
usage: python -m kit hardcases tiles [-h] [--n N] [--seed SEED] [--size SIZE]
                                     [--side SIDE] [--kinds KINDS] [--k0 K0]
                                     out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | Write N training tiles to the shard `out` (`.npz`) |
| `--n N` | `100` | Tiles to make |
| `--seed SEED` | `1` | Run seed; tile K is the same for the same seed |
| `--size SIZE` | `256` | Tile side in voxels |
| `--side SIDE` | `0.3` | Share of side (z by x) slices; the rest are axial |
| `--kinds KINDS` | none | Comma list of kinds, equal shares; none means the `RECIPE` shares |
| `--k0 K0` | `0` | First tile index (to split a run into parts) |

### `python -m kit hardcases volume`

```
usage: python -m kit hardcases volume [-h]
                                      [--kind {plain,spiral,hairpin,tight_u,tight_bend,accordion,mush,delamination,crack,edge}]
                                      [--seed SEED] [--shape SHAPE]
                                      out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | One 3D block of a layout with its CT |
| `--kind KIND` | `hairpin` | The kind |
| `--seed SEED` | `1` | Layout and render seed |
| `--shape SHAPE` | `64,256,256` | z,y,x voxels |

### `python -m kit hardcases info`

```
usage: python -m kit hardcases info [-h]
```

No options. Prints the kinds, recipe, extras and scale as JSON.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `Layout(kind, seed, size=(1, 256, 256), extras=None)` | a layout | `SimError` | `field(z, y, x)` gives (f, masks); `levels`, `thick`; `describe()` a dict; EXTRAS overrides `EXTRAS` shares |
| `raster(lay, plane='z', origin=(0, 0, 0), shape=(256, 256), eps=0.25)` | dict of arrays | `SimError` (plane) | plane `z` (axial), `y` (side, z by x) or `vol`; keys `sheet`, `lines`, `q`, `air`, `crack`, `opening`, `crushed`, `zone`, `levels`, `thick` |
| `render(r, seed, crushed=0, inclusions=False, debris=False)` | uint8 array | | physics CT of a raster, 2D or 3D |
| `tile(seed, k, size=256, recipe=None, side=0.3, extras=None)` | dict | `SimError` after 20 failed draws | one tile with Synthetic-Slices fields |
| `tiles(n, seed, size=256, recipe=None, side=0.3, k0=0, progress=None, dense_look=None)` | shard dict | `SimError` | deterministic in (seed, k); DENSE_LOOK, a dict of `fill`, `core` and any `REAL_KEYS` bounds, draws the tiles inside `dense()` and `realism()` |
| `realism(**bounds)` | context manager | `SimError` (unknown setting, bounds out of range) | (lo, hi) draw bounds for `sd`, `psf`, `ply_w`, `rim`, `gap` and a `pitch` factor (`REAL_KEYS` holds the defaults); none set gives the default tiles bit for bit; setting `pitch`, even to (1, 1), takes one extra draw and so changes later draws |
| `dense(fill=None, core=None)` | context manager | `SimError` (bounds) | sheet thickness as a fraction of the nearest gap (`FILL`) and ply core brightness (`CORE`); none gives the default tiles |
| `volume(kind, seed, shape=(64, 256, 256), extras=None)` | (layout, raster, ct) | `SimError` | |
| `line_separation(lines)` | float | | smallest distance between lines of different ids |
| `Wave(rng, scale, n=8, zscale=None)` | callable field | | smooth random field of unit variance |
| `pitch_draw(rng, n, compact=False)` | float array | | sheet gaps in voxels |
| `kind_name(lay)` | str | | Synthetic-Slices style kind label |
| `SimError` | exception | | refusals |
| `build_parser(ap)` | the parser | | the `kit hardcases` arguments on `ap` (kit.cli defers here) |
| `cmd_hardcases(a)` | exit code | | runs one parsed command |
| `main(argv=None)` | exit code | | the command line |

## Inputs

None but the arguments. The grid is 9.362 um per voxel (`VOXEL_UM`, Synthetic-Slices' scale); sheet pitch is lognormal about 15.5 voxels (`PITCH_P50`, sigma `PITCH_SIGMA` 0.37, at least `PITCH_MIN` 9), from their m7 percentiles 4.75, 7.75 and 16 px at 18.7 um, doubled.

## Outputs

`tiles` shard keys: `image` (uint8 N x H x W), `lines` (0/1), `sheet_id` (uint16, sheet id plus 1 on lines), `dist` (uint8, distance to a line, clipped at 255), `crack`, `air`, `crushed_mask`, `zone` (uint8 bits of `ZONES`), `crushed` (0 none, 1 whole tile, 2 patch), `kind` (base kind with `_compact`, `+contact`, `+crushed`), `plane` (`z` or `y`), `guidance` (1.0 plain and spiral, 1.6 otherwise, the guidance a learned painter such as Synthetic-Slices' sampler would use), `layout` (JSON of `describe()`). It prints one JSON line with the counts per kind.

| Exit code | Meaning |
| --- | --- |
| `0` | written |
| `2` | refused (`kit hardcases: ...`) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `unknown kind...; one of ...` or `unknown kinds` | a name not in `KINDS` | use `python -m kit hardcases info` |
| `unknown plane` | `raster` plane not `z`, `y` or `vol` | use one of those |
| `tile...: no valid layout after 20 tries` | every draw had too few lines or lines closer than 3 px | change the seed, the size or the recipe |
| `kit hardcases: ...` | any refusal below, printed with exit 2 | read the rest of the line |
| `layout has fewer than two sheets`, `sheet levels are not increasing` | a broken custom recipe or a bug | report it with the seed |
| `realism: unknown setting 'x' (known: [...])` | a `realism()` bound outside `REAL_KEYS` | use `sd`, `psf`, `ply_w`, `rim`, `gap` or `pitch` |
| `realism: sd bounds (0.5, 0.1) out of range` | a `realism()` bound with lo above hi, or outside 0 to 50 | pass (lo, hi) with lo at most hi |
| `fill bounds (0.9, 1.2) out of range` | a `dense()` bound outside 0 to 1 (fill) or 0 to 2 (core), or lo above hi | pass (lo, hi) inside the range |

## How it works

Each kind defines f in px with unit gradient across sheets: plain and its variants as an undulating, slowly turning stack whose pitch varies; spiral as elliptical radius (with a radial warp) minus pitch times angle over 2 pi; folds as signed distance to an arc of radius R spanning the fold angle plus two tangent rays; accordion as v minus a rounded triangle wave; mush with Synthetic-Slices' waviness. Contact narrows a level span with a monotone map (`_squeeze`); delamination opens one (`_open`) and puts a line on each ply where they part by 2 voxels or more; a crack adds an offset on one side of a jagged fault and makes the opening air. Rasterizing takes the nearest level, the normal distance (level difference over the gradient, by central differences on the field) and marks sheet voxels inside half the sheet's thickness and median-line voxels within half a voxel of the level in the grid's plane.

## Cost and time

Measured 24 Nov 2026 in a 4-core cloud container: 0.15 to 0.38 s per 256 px tile by kind; tests 5 s. A 256^3 `vol` raster evaluates the field seven times over 16 M points: use blocks of 64 slices or less.

## For agents

- **Command:** `python -m kit hardcases tiles OUT.npz --n 2000 --seed 11`
- **Parse:** the printed JSON (`n`, `kinds`); load the shard with numpy
- **Rerun:** safe; the same seed gives the same tiles, the file is overwritten
- **Success:** exit 0 and N tiles in the shard
- **Not a pass:** a good score on these tiles is no evidence about real CT
- **Go-ahead:** Nothing
- **Never:** call a detector trained here "validated" without a real-data test

## Tests

`python -m unittest tests.test_hardcases` (16 tests, about 5 s): layouts, block independence, determinism, folds, cracks, edges, delamination, contact, level maps, shards, render, and `dense()` (default tiles unchanged, denser sheets fill more, bounds checked). `tests.test_simreal` checks `realism()` (default tiles unchanged, bounds take effect, the pitch factor spreads sheets, bad bounds refused). Not covered: realism of the render; [simcritic](simcritic.md) measures that.

## History

- 2026-11-26: version 1.1: `realism()` and `dense()` render bounds, default tiles unchanged; fitted with [simreal](simreal.md).
- 2026-11-25: released in the Scrolls kit on base `4536292`: the hard cases of Synthetic-Slices v0.2 rebuilt as 3D fields, with spiral centers and a zone map.

## Related

- [scrollsim2](scrollsim2.md): the full-scale rolled scroll
- [simreal](simreal.md): measures real CT and fits the render bounds
- [simcritic](simcritic.md): judges how real the tiles look
- [Synthetic-Slices v0.2](https://github.com/vincentl065/Synthetic-Slices) (vincentl065, MIT): the 2D generator these hard cases come from
