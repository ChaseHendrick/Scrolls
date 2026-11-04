# expatlas: how much of each labeled segment a released ink model's training meshes already cover

`python -m kit expatlas` resolves the published training lists of ten released ink models to open-data catalog segments and measures, on meshes in one scroll frame, how much of each labeled evaluation segment their training segments already cover: a leakage matrix for fair train and test splits.

| Field | Value |
| --- | --- |
| Id | `expatlas` |
| Status | Experimental |
| Kind | kit command, kit module, data |
| Area | Scoring and controls |
| Run | `python -m kit expatlas` |
| Code | `kit/expatlas.py`, `kit/cli.py` (`cmd_expatlas`) |
| Tests | `tests/test_expatlas.py` |
| Needs | Python 3.10 or newer, numpy, scipy (cKDTree) and tifffile; imagecodecs for the LZW-compressed meshes some catalog segments have (the 4 Nov run used numpy 2.5.3, scipy 1.18.1, tifffile 2026.10.15, imagecodecs 2026.10.10). No villa, VC3D, torch or GPU |
| Runs on | Any CPU with about 1 GB free. The 4 Nov 2026 matrix (20 segments by 10 models) took 76 s and the planted checks 50 s on a Hugging Face cpu-upgrade Job (8 vCPU, 32 GB; `exposure_atlas_checks` in [results.json](../results.json)); one pair took about 4 s in a 4-core cloud container (measured 4 Nov 2026) |
| Network | HTTPS GET of the open-data bucket `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`: `metadata.json` (the catalog) and each segment's tifxyz `x.tif`, `y.tif`, `z.tif`. None for `models`, `show` or local folders |
| Writes | `matrix`: OUT/matrix.json and OUT/matrix.txt; `plant`: OUT/plant.json and the planted copies under OUT/planted/ (tifxyz folders); every mesh read from the bucket is cached under `--cache` (default `work/expatlas/cache`). `models`, `segments`, `pair` and `show` print only |
| Go-ahead | Not needed: it reads public meshes and the catalog and prints. Running it on paid compute follows the compute rule (AGENTS.md rule 11); posting the matrix to villa or the community needs Chase's yes |
| License | Apache-2.0 for the code and the registry (this repository's license); the catalog and meshes it reads are Vesuvius Challenge open data, CC BY-NC 4.0 |
| Released | Public branch `claude/exposure-atlas` since 4 Nov 2026 (open pull request, not merged) |
| Checked | 2026-11-04 against commit `7741f8b` |

## What it does

A score on a labeled segment tests an ink model only where the model never trained on that papyrus. Training lists name segments, and a name check (is this segment id in the list?) misses the same sheet traced twice under two ids, the same segment rendered from another scan or at another resolution, and two segments that overlap. The Exposure Atlas checks it on the meshes.

It has two parts. **The registry** (`kit/data/expatlas-models.json`) holds the published training lists of ink_9um, v8in, v8in-1447, d9v2, Reader v2, Reader V3, ink_canonical_2um, Hecate, TRACE v3B and A-hn, each name resolved to an open-data catalog segment id where one matches, with how it matched, its role (train, a dataset a split rule draws from, validation, validation only, checkpoint selection, the author's own test list), what each model inherits from its starting weights, and the source with its revision. **The geometry** puts every training mesh of a model on the evaluation segment's scroll into that segment's own scan (the catalog's own transformed copy where it has one, else the catalog matrix) and asks, for every vertex of the evaluation mesh, how far along the normal the nearest training surface lies, counting only spots inside that surface's own grid footprint. The share of vertices within 60 um is f_same; within 100 um, f_band (a render band of about plus or minus 100 um would hold that papyrus's CT).

This builds on dlescanogithub's proposal in [villa issue 2346](https://github.com/ScrollPrize/villa/issues/2346) (28 Oct 2026): map both surfaces to level-0 voxels of one volume, count points within a few voxels of the other surface by KD-tree nearest neighbor, and check the z ranges and render-layer offsets. The z overlap is reported per covering mesh.

It reads no labels and no CT. Each call is Model output of this geometry; the list it starts from is Sourced fact or Community report as the model's entry says. "clear" means no covering training mesh was found, not that a model is proven held out; a model whose list is not published reads "unknown", never held out.

## When to use it

- Before you trust or publish a score of a released model on a labeled segment: look up the cell, and read its `why` and `flags`.
- When you choose a train and test split among labeled segments: the matrix's evaluation pairs show which labeled segments overlap each other.
- When a new model publishes its training list: add it to the registry and rerun `matrix`.

Do not use it:
- to decide a split rule's share of supervised pixels (that needs the label masks): use [heldout](heldout.md);
- to compare two traces' ink maps: use [overlap](overlap.md) (`kit collate`);
- to check the catalog transforms themselves: use [meshaudit](meshaudit.md) (`transforms`).

## Quick start

```bash
python -m kit expatlas pair 20250925212701 20250925222237
python -m kit expatlas matrix --out OUT --scroll PHerc0009B
python -m kit expatlas show docs/data/expatlas/matrix-2026-11-04.json
```

OUT is a folder for `matrix.json` and `matrix.txt`. The first command, run on 4 Nov 2026 on two PHerc0814 training meshes (not an evaluation pair), printed `exposed, 10.2% within 60 um, 12.7% within 100 um, z overlap 96%` in about 4 s. It worked when it prints a call and the shares, and `matrix` exits 0 with one row per labeled segment.

## Checks and controls

Planted duplicates, preregistered before any matrix cell existed. 30 public PHerc0814 and PHerc0009B meshes are copied, moved to another scan's frame by the catalog matrix, displaced 0 to 3 voxels along the normal, jittered by the transform's landmark fit error and renamed; the atlas must bring each copy back through the reverse matrix. (a) Each original against its copy must be exposed; (b) the copy moved a further 100 um must not be; (c) a copy from the other scroll read as if in the same scan must not be; (d) a real pair from the catalog, PHerc0814 `20250928235953` and its copy on the 2.399 um scan `20250928235954`, must be exposed both ways. Run: `python -m kit expatlas plant --prereg docs/prereg/2026-11-04-expatlas-instrument-v2.md --out OUT` (exit 0 PASS, 3 FAIL).

Results, 4 Nov 2026 ([records](../data/expatlas/README.md)):

| Rule | (a) recall | (b) 100 um control | (c) cross-scroll | (d) real pair | Verdict |
| --- | --- | --- | --- | --- | --- |
| version 1 ([prereg](../prereg/2026-11-04-expatlas-instrument.md)), attempt 2 | 30 of 30 | 21 of 30 not exposed, bar 29 | 30 of 30 | 2 of 2 | **FAIL** |
| version 2 ([prereg](../prereg/2026-11-04-expatlas-instrument-v2.md)) | 30 of 30 (f_same 0.804 to 0.973) | 30 of 30 on free vertices, 9 at trace (up to 0.037) | 30 of 30 (at most 0.010) | 0.901 and 0.0505 (a near miss against 0.05) | PASS |

Version 1 failed because ten large auto-grown PHerc0814 meshes span neighboring windings of their own, so a copy moved 100 um lands on the mesh's own next winding (attempt 1 was killed for memory before scoring). Version 2 scores the control only on vertices with no other part of their own mesh within 160 um (`self_cover`). Its PASS is not independent of version 1: that rule came from a diagnostic of version 1's failed meshes, and 28 of its 30 source meshes are version 1's. The nine traces it leaves are 0.005 to 0.037 on free vertices; on all vertices, as matrix cells are scored, the same copies give 0.039 to 0.259. So on multi-winding meshes a cell under about 0.04 is no evidence of exposure, and one just over 0.05 is weak. Check (a) sends each copy forward and back through the same catalog matrix, so it tests the instrument, not the transforms' accuracy: only a rigid jitter of the transform's fit error stands in for it (PHerc0009B's route has a landmark leave-one-out error of 188.8 um, over the 70 um limit a matrix cell applies; the plant check does not apply that limit).

Claim label: Model output, for every call and share; Sourced fact or Community report, for each training list as its registry entry says.


## The matrix of 4 November 2026

Scope: the 20 labeled segments of PHerc0009B, PHerc0500P2, PHerc0814, PHerc0841, PHerc1667 and PHercParis4 in the catalog of 2 Nov 2026, by ten models; record [`matrix-2026-11-04.json`](../data/expatlas/matrix-2026-11-04.json), table [`matrix-2026-11-04.txt`](../data/expatlas/matrix-2026-11-04.txt). Of 200 cells: 92 trained by name, 18 exposed, 3 trace, 6 selected, 32 clear, 49 unknown. Model output of the geometry, after the version 2 instrument PASS, rerun at `913e932` after an independent review made every open end read unknown (the first run, kept in the same folder, had the same shares; ink_canonical_2um's 8 PHercParis4 cells read clear there). No cell crossed scans: every training mesh that entered a geometric cell was traced on the evaluation segment's own scan, so the transform flag and limit were exercised only by planted checks (a) and (d).

Cells where the meshes show more than the names (share of the evaluation segment's vertices within 60 um of the model's training meshes):

| Model | Segment | f_same | Covered mostly by | Note |
| --- | --- | --- | --- | --- |
| d9v2 | PHerc0009B ag487 (`auto_grown_20250919055754487_inp_hr`) | 0.430 | three PHerc0009B training traces, 0.17 to 0.27 each | in d9v2's own test list |
| d9v2 | PHerc0500P2 `-1` | 0.263 (0.707 within 100 um) | training segments `0`, `-2` and `500P2_front` | in d9v2's own test list |
| Reader v2, Reader V3 | PHerc0009B ag487 | 0.430 | the same three traces | not named in its list |
| Reader v2, Reader V3 | PHerc0500P2 `-1` | 0.086 | `500P2_front` and two z_dbg traces | |
| v8in, v8in-1447, A-hn | PHercParis4 `20230929220926` and `20231007101619` | 0.146 and 0.101 | training segment `20231005123336` | |
| v8in, v8in-1447, A-hn | PHerc1667 w023, PHerc0500P2 `-1` | 0.056 each | w018 (named in v8in's list), `500P2_front` | just over the bar: weak |
| v8in, v8in-1447, A-hn | PHerc0009B ag487 | selected | validation segment ag132115 covers 0.173 | it chose v8in's checkpoint |

Unknown, and why: TRACE v3B publishes no list (its checkpoint was chosen on PHerc0841, per the A-hn card); v8in lists Paris 4 `20231012184423`, which has no public mesh (the catalog has `20231012184424`, one second later and labeled; that they are one segment is an untested guess); ink_canonical_2um lists four PHerc1667 fragments (`l_2`, `l_3`, `l_4` and `l_6`) and two ids with no scroll (`500p2a`, `658`) that match no catalog segment, so it reads unknown wherever its names do not settle a cell. Reader V3 publishes no list of its own; its PHerc0841 cells read clear from its card's statement that PHerc0841 w00 is a never-seen scroll (Community report), its other cells from Reader v2's list.

Labeled segments that overlap each other (18 of 92 same-scroll pairs exposed, 9 trace): PHerc0841 w00 and ag896 cover each other at about 0.35; PHercParis4 pairs at 0.08 to 0.25; PHerc1667 w028 and w029 at about 0.20 although named as neighboring windings (a sheet switch, or windings closer than 60 um: the geometry cannot tell), w018 and w023 at about 0.056. A split that trains on one and tests on the other trains on part of the test papyrus.

## Commands and options

### `python -m kit expatlas models`

```
usage: python -m kit expatlas models [-h] [--registry REGISTRY] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--registry REGISTRY` | `kit/data/expatlas-models.json` | the registry file to read |
| `--json` | off | print the whole registry as JSON |

### `python -m kit expatlas segments`

```
usage: python -m kit expatlas segments [-h] [--catalog CATALOG]
                                       [--scroll SCROLL] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--catalog CATALOG` | none | metadata.json path or URL (default: the bucket's) |
| `--scroll SCROLL` | none | only this scroll (repeatable) |
| `--json` | off | print the rows as JSON |

### `python -m kit expatlas pair`

```
usage: python -m kit expatlas pair [-h] [--frame FRAME] [--px-um PX_UM]
                                   [--catalog CATALOG] [--cache CACHE]
                                   [--json]
                                   eval train
```

| Option | Default | Meaning |
| --- | --- | --- |
| `eval` | required | the evaluation segment: a catalog segment id, or a local tifxyz folder |
| `train` | required | the training segment: a catalog segment id, or a local tifxyz folder |
| `--frame FRAME` | none | volume id of the frame (default: the evaluation segment's own volume) |
| `--px-um PX_UM` | none | voxel size of the frame, for two local folders |
| `--catalog CATALOG` | none | metadata.json path or URL (default: the bucket's) |
| `--cache CACHE` | `work/expatlas/cache` | folder for meshes read from the bucket |
| `--json` | off | print the numbers as JSON |

### `python -m kit expatlas matrix`

```
usage: python -m kit expatlas matrix [-h] --out OUT [--catalog CATALOG]
                                     [--registry REGISTRY] [--scroll SCROLL]
                                     [--model MODEL] [--skip SKIP]
                                     [--cache CACHE] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--out OUT` | required | folder for matrix.json and matrix.txt |
| `--catalog CATALOG` | none | metadata.json path or URL (default: the bucket's) |
| `--registry REGISTRY` | `kit/data/expatlas-models.json` | the registry file to read |
| `--scroll SCROLL` | none | only this scroll's evaluation segments (repeatable) |
| `--model MODEL` | none | only this model (repeatable) |
| `--skip SKIP` | none | file of SCROLL/GLOB patterns: segments never read, their cells not-run |
| `--cache CACHE` | `work/expatlas/cache` | folder for meshes read from the bucket |
| `--json` | off | print matrix.json to stdout instead of the table |

### `python -m kit expatlas plant`

```
usage: python -m kit expatlas plant [-h] --prereg PREREG --out OUT
                                    [--catalog CATALOG] [--cache CACHE]
                                    [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--prereg PREREG` | required | JSON block of the preregistration (see the tool page) |
| `--out OUT` | required | folder for plant.json and the planted copies |
| `--catalog CATALOG` | none | metadata.json path or URL (default: the bucket's) |
| `--cache CACHE` | `work/expatlas/cache` | folder for meshes read from the bucket |
| `--json` | off | print plant.json to stdout instead of the summary |

### `python -m kit expatlas show`

```
usage: python -m kit expatlas show [-h] [--json] matrix
```

| Option | Default | Meaning |
| --- | --- | --- |
| `matrix` | required | a matrix.json written by `matrix` |
| `--json` | off | print it as JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `AtlasError()` | an exception | None | every refusal: bad registry, mesh without edges, missing package, no route |
| `load_registry(path=REGISTRY)` | the registry dict | AtlasError, OSError, ValueError | checks the schema, repeated ids, inherits and sources |
| `chain(registry, model_id, _seen=None)` | list of (model id, via) | AtlasError on a loop | [(model id, via)] for a model and everything it inherits; via is the path, such as 'd9v2 < ink_9um'. |
| `catalog_index(cat)` | (index, voxel sizes) | KeyError on a malformed catalog | {segment id: {scroll, suffix, volume, meshes {volume: path}, native, labeled}} and {scroll: {volume: um}}. |
| `evaluation_segments(index, scrolls=None)` | sorted segment ids with ink labels | None | optionally only the given scrolls |
| `names_of(gid, rec)` | set of the id, suffix and id-suffix | None | what skip patterns match against |
| `read_skip(path)` | list of patterns | AtlasError on a line without /, OSError | Patterns, one per line, SCROLL/GLOB matched against a segment's id, suffix and id-suffix; # starts a comment. |
| `skipped(gid, rec, pats)` | bool | None | fnmatch, case-insensitive on names |
| `transform_errors(cat)` | dict of route errors in um | None | {(scroll, from volume, to volume): landmark error in um}, leave-one-out RMS where it can be computed, else |
| `path_error(cat, errors, scroll, a, b)` | float um or None | None | Landmark error of the catalog route from volume a to b: the root sum of squares over its steps, or None. |
| `Fetcher(cache, base=BUCKET, get=None)` | an object with read(path, max_points) | OSError, urllib errors on a failed read | Reads tifxyz folders from the bucket (or a local folder) into a cache folder, once. |
| `mesh_in_frame(cat, index, gid, frame, fetch)` | (xyz, route dict) or (None, why) | None | (H, W, 3) vertices of segment gid in voxels of volume `frame`, and how they got there; (None, why) if no |
| `grid_step(xyz)` | float, grid units | AtlasError when no edge is finite | Median edge length of the grid, in its own units (the larger of the row and column medians). |
| `decimate(xyz, max_points)` | (sub-grid, stride) | None | Every k-th row and column so at most max_points valid vertices remain. |
| `Surface(xyz, name='')` | an object with points, normals, step, zrange, tree | AtlasError under 4 vertices with a normal | A training mesh ready for offset queries: vertices, unit normals, grid step and a KD-tree. |
| `eval_points(xyz, max_points=MAX_EVAL_POINTS)` | (N x 3 points, stride) | None | See the code's docstring |
| `offsets(points, surf, px_um, reach_um=REACH_UM, k=K_NEAREST)` | array of um, inf where not covered | None | \|offset\| in um along the training surface's normal for each point, inf where the surface does not cover it |
| `summarize(h)` | dict: points, f_same, f_band, f_reach, median_offset_um | None | Shares of evaluation vertices by offset to the nearest covering training surface. |
| `call(f_same)` | exposed, trace, clear or unknown | None | unknown for None |
| `zoverlap(points, zrange)` | share 0 to 1 | None | Share of the evaluation mesh's z range that the training mesh's z range also spans (villa 2346's z check). |
| `pair(eval_xyz, train_xyz, px_um, name='')` | dict of shares, call, z_overlap, stride, train step | AtlasError | One evaluation mesh against one training mesh, both in voxels of one volume of px_um. |
| `build_matrix(cat, registry, fetch, models=None, scrolls=None, skip=(), log=None)` | the matrix dict (see Outputs) | AtlasError, OSError | Every (model, evaluation segment) cell, the evaluation segments' overlaps with each other, and the settings. |
| `settings()` | dict of the thresholds | None | See the code's docstring |
| `write_tifxyz(folder, xyz, extra=None)` | None | OSError | float32, -1 for holes, a meta.json |
| `displaced(xyz, delta_vox)` | (H, W, 3) array | None | The mesh moved along its own unit normals by delta_vox (voxels); holes stay holes. |
| `self_cover(xyz, px_um, reach_um=REACH_UM, gap=4, k=24)` | array of um per valid vertex, inf where none | None | For each valid vertex (row-major order of the finite grid points, as eval_points keeps them), the offset in um |
| `plant_check(cat, prereg, fetch, out, log=None)` | the plant record with verdict | AtlasError, OSError | Run the preregistered planted-duplicate checks: (a) recall, (b) adjacent-winding control, (c) cross-scroll |
| `verdict(res, prereg)` | dict of checks and pass | KeyError on missing bars | version 1 counts or version 2 shares |
| `format_matrix(m)` | text | None | See the code's docstring |
| `format_plant(res)` | text | None | See the code's docstring |
| `format_models(reg)` | text | None | See the code's docstring |
| `build_parser(p)` | None | None | adds the actions to an argparse parser |
| `cmd_expatlas(args)` | exit code | None | catches AtlasError, KeyError, ValueError and OSError as exit 2 |
| `main(argv=None)` | exit code | None | the module's own entry point |

## Inputs

- **The catalog**: the bucket's `metadata.json` (gzip), or `--catalog PATH`. It names every segment's scroll, the volume it was traced on (`original_volume_id`), its tifxyz meshes (`tifxyz`, and `tifxyz-transformed` copies named `ID-on-VOLUME-PXum.tifxyz` in level-0 voxels of each other volume), whether it has `ink-labels`, each volume's voxel size, and the sample-level affine matrices between volumes (x, y, z order).
- **Meshes**: tifxyz folders (`x.tif`, `y.tif`, `z.tif`, float, -1 for holes) from the bucket, or local folders for `pair --px-um`. Each is read in single precision and thinned to at most 400,000 vertices that are not holes (`MAX_MESH_POINTS`); an evaluation mesh to at most 150,000 (`MAX_EVAL_POINTS`).
- **The registry**: `kit/data/expatlas-models.json` (schema `expatlas-models/1`), or `--registry`.
- **A skip file** (optional): lines `SCROLL/GLOB`, matched case-insensitively against a segment's id, suffix and id-suffix; `#` starts a comment.
- **A preregistration** for `plant`: a Markdown file whose first ```json block holds `seed`, `n`, `scrolls`, `exclude_segments`, `deltas_vox`, `shift_um`, `max_mesh_points`, `positive_pairs`, `bars`, and for version 2 `b_free_um` and `b_min_free_vertices`.

## Outputs

`matrix` prints the table (codes T trained, E exposed with its percent, t trace, S selected, . clear, ? unknown, - not run), the flags and the overlapping evaluation pairs, and writes the same as OUT/matrix.txt and OUT/matrix.json:

| Field | Type | Meaning |
| --- | --- | --- |
| `settings` | object | the thresholds the run used (`d_same_um` 60, `band_um` 100, `exposed_frac` 0.05, `trace_frac` 0.005, `transform_flag_um` 30, `transform_limit_um` 70, caps) |
| `segments[]` | list | one per labeled segment: `segment`, `scroll`, `suffix`, `frame` (volume id), `px_um`, `points`, `stride`, `status` |
| `cells[]` | list | one per model and segment: `status` (one of the calls), `why`, `flags`, `f_same` and `f_band` (shares of vertices, 0 to 1), `median_offset_um`, `transform_error_um` (worst route landmark error, um), `covering` (up to 5 training meshes with their own shares, z overlap and the model path they came through, such as `d9v2 < ink_9um`), `names` for a trained cell |
| `duplicates[]` | list | labeled segment pairs on one scroll: `segment` measured on `other`, the shares, `call` |
| `models[]` | list | each model's id, title, author, weights link, label, list status, inherits, note |

`plant` writes OUT/plant.json: the `a`, `b`, `c`, `d` rows (per planted mesh: source, copy id, scroll, delta, jitter, shares, call; version 2 adds free and all vertex counts) and `verdict` with each check's value, bar and pass.

| Exit code | Meaning |
| --- | --- |
| `0` | Success; for `plant`, the instrument PASSed |
| `2` | A bad argument, a missing package, an unreadable registry or file, or a failed read |
| `3` | `plant` only: the instrument FAILed (the record is still written) |


## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `unknown action...` | an action name the parser does not know | use models, segments, pair, matrix, plant or show |
| `...: schema is not expatlas-models/1` | the registry file is not this tool's | point `--registry` at kit/data/expatlas-models.json |
| `...: model ids repeat` | two registry models share an id | rename one |
| `inheritance loop at...` | models inherit from each other in a circle | fix `inherits` |
| `mesh has no finite edges` | a mesh of holes only, or one vertex wide | skip that segment |
| `...: no second volume with a catalog transform from...` | a planted scroll has one scan or no matrix | plant from scrolls with two scans and a catalog matrix |
| `kit expatlas:...` | a refusal with its reason (registry, catalog, package such as imagecodecs for LZW meshes) | read the reason; `pip install imagecodecs` for the LZW one |
| `kit expatlas could not read or write:...` | a network or disk error | retry; check the cache folder and space |
| `numpy is required for kit expatlas` | numpy is missing | `pip install numpy` |
| `scipy is required for kit expatlas (cKDTree)` | scipy is missing | `pip install scipy` |
| `...: fewer than 4 vertices with a normal` | a training mesh too small or too broken for normals | it is flagged and left out of the cell |
| `...:...inherits unknown model...` | an `inherits` id with no model | add the model or fix the id |
| `...:...cites unknown source...` | an entry's source key is not in `sources` | add the source |
| `two local folders need --px-um` | `pair` on two folders has no catalog voxel size | give `--px-um` |
| `no mesh in frame...:...` | one of the pair has no mesh or route to the frame | pick another `--frame` |
| `skip pattern...is not SCROLL/GLOB` | a skip line without a slash | write SCROLL/GLOB |
| `kit expatlas: segment ... is not in the catalog ...` | `pair` was given an id the catalog does not have | give a catalog segment id (`python -m kit expatlas segments`) or a local tifxyz folder |
| `kit expatlas: unknown model(s) ...; the registry has ...` | `--model` names a model the registry lacks | use one of the ids it lists |
| `kit expatlas: the frame volume has no voxel size (pixel_size_um) in the catalog` | `pair` on a volume the catalog gives no voxel size | pick another `--frame`; in `matrix` such a segment's row reads `not measured` and its cells unknown |
| A segment row `not measured: the evaluation mesh has no valid vertices` | its mesh in the catalog is all holes | nothing to measure; its cells read unknown |

## How it works

1. Index the catalog: every segment's scroll, traced-on volume, meshes per volume and whether it is labeled; each volume's voxel size.
2. For each labeled segment in scope, the frame is its traced-on volume. Read its mesh there and keep at most 150,000 vertices.
3. For each model, gather its entries and those of every model it inherits. A segment named with role train or train_split makes the cell "trained" at once.
4. Otherwise every resolved training (and validation) segment on the same scroll is read in the frame, the catalog's copy first, else through `sample_matrix`. Each becomes a `Surface`: vertices, unit normals from the grid (`meshaudit.grid_normals`), the median grid step and a KD-tree.
5. `offsets`: for each evaluation vertex, the 8 nearest training vertices within reach (300 um along the normal plus 1.5 grid steps); for each, the offset along that vertex's normal and the tangential distance; a candidate counts only if the tangential distance is at most 0.8 grid steps (`FOOTPRINT`). The smallest kept offset, over a model's meshes, is the vertex's distance.
6. Shares: f_same at 60 um (`D_SAME_UM`), f_band at 100 um (`BAND_UM`). Call: exposed at 0.05 or more, trace from 0.005, clear below; a validation segment that covers it, or a checkpoint chosen on it, makes it selected.
7. Transform error: each cross-scan mesh carries the root sum of squares of the landmark leave-one-out RMS over its catalog route (`transform_errors`, from `kit meshaudit`; the fit RMS where leave-one-out cannot be computed). Above 30 um the cell is flagged "winding uncertain"; above 70 um (half a nominal 140 um winding) a geometric call reads unknown.
8. Unknown, never clear, when exposure is left open: a model whose list, or an inherited one, is anything but fully published; names on the scroll, or train names with no scroll, that match no catalog segment; a listed id the catalog lacks; a training mesh that cannot be read; a deciding mesh whose route has no landmark error or one over the limit. One exception: an explicit `not_trained` entry, an author's cited statement that a scroll was not trained on, lets such a cell read clear, with that statement as its `why`. Shares are compared with the bars unrounded.

Same-winding against adjacent-winding: the 60 um band is below half the about 140 um pitch measured on PHerc0139 ([stackcheck log](../logs/2026-10-14-pherc0139-segment-defects.md)), and the planted control holds where no sheet lies 100 um away. Two limits stay: where windings are pressed closer than about 60 um, or a trace switches sheets, a cell can read exposed for papyrus that is on the next winding (PHerc1667 w028 and w029, named as neighboring windings, cover each other at about 0.20); and a cross-scan cell rests on a catalog transform, whose own landmark error the flag reports. Two community reports bear on those transforms: [villa 1835](https://github.com/ScrollPrize/villa/issues/1835) (kadenpool, 19 Sep 2026) found published landmarks that four transforms do not fit, with one clear miss, PHerc1667 1.129 to 2.399 um; [villa 2312](https://github.com/ScrollPrize/villa/issues/2312) (renxuhang, 26 Oct 2026) found that the PHercParis4 global affine gives no local correspondence for the surfaces it studied, while not claiming the global transform is invalid. The 4 Nov matrix has no cross-scan cell; the cross-scan route was exercised only by planted checks (a) and (d) (route error 12.8 um in (d), under the flag).

## Cost and time

Measured 4 Nov 2026 on Hugging Face cpu-upgrade Jobs (8 vCPU, 32 GB): the planted checks 47 to 50 s running, the matrix of 20 segments by 10 models 76 s; three cpu-basic smoke runs of the tests 14 to 17 s each. Memory: under 200 MB for one 400,000-vertex mesh with its search tree; a 4-core cloud container with about 1 GB free ran single pairs but not the whole check reliably.

## For agents

- **Command:** `python -m kit expatlas matrix --out OUT [--scroll S ...] --json`; one pair: `python -m kit expatlas pair EVAL TRAIN --json`
- **Parse:** `cells[]`: `status`, `f_same`, `why`, `flags`, `covering`; `duplicates[]` for labeled pairs; `plant`'s `verdict.pass` and `verdict.checks`
- **Rerun:** Safe: it overwrites OUT/matrix.json and matrix.txt and reuses the mesh cache. A `plant` rerun of a frozen preregistration is a new attempt and must be disclosed
- **Success:** Exit 0 and one `segments[]` row with status `run` per labeled segment in scope; `plant` exit 0 means the instrument PASSed
- **Not a pass:** A clear cell that rests on an author's statement (read `why`) or that carries flags; a trace or a share just over 0.05 on a multi-winding mesh; a cross-scan cell flagged winding uncertain; a matrix from a rule whose `plant` check failed
- **Go-ahead:** Nothing to run it; posting a matrix or a cell to villa, Discord or a forum needs Chase's yes
- **Never:** Call a clear cell held out or proven unexposed; call an exposed cell a reading of anything; read labels with it; run it on segments a preregistration holds for a test of ours

## Tests

`python -m unittest tests.test_expatlas` (43 tests): on synthetic cylinders and planes, the same sheet and an independent retrace on another grid are exposed, a sheet one winding (140 um) out is clear, the 60 um edge, no cover past a mesh's edge or over its holes, a crossing sheet is not exposed, partial cover reads trace, `displaced`, `decimate`, the tifxyz round trip, `self_cover` on one mesh folded over itself; the calls, skip patterns, both verdict versions; the registry's shape, inheritance, known resolutions and dashes; the matrix on a small fake catalog (a cross-scan copy exposed through the matrix, another winding clear, named and inherited, no training on the scroll, unresolved names, unpublished lists, validation cover, skip reads nothing, the text table; a partial list reads unknown, an author's statement lets it read clear, a partial list keeps exposure; a missing id, train names with no scroll and a route with no landmark error read unknown; selected by id; an unknown model is refused; no voxel size and an all-hole mesh read unknown), the bars against the unrounded share, a flat-z z overlap, and the command line. They do not reach the bucket.

## History

- 2026-11-04: Exposure Atlas: attempt 2 FAIL on the adjacent-winding control; freeze version 2 (`7741f8b`)
- 2026-11-04: Exposure Atlas: thin meshes as they are read; disclose attempt 1's memory kill (`34c3683`)
- 2026-11-04: Exposure Atlas: freeze the instrument checks before any planted copy or matrix cell (`0ec8999`)

## Related

- [heldout](heldout.md): Hecate's split rule on a segment's label masks, the measurement behind its train_split shares.
- [labels](labels.md): which label sets exist per segment, with this repository's exposure records.
- [overlap](overlap.md): two meshes at a time, with label agreement.
- [meshaudit](meshaudit.md): the catalog transforms' landmark errors this tool reports.
- [leaderboard](leaderboard.md): reads `held_out_by_reader` in results.json; this matrix can inform it.
- [Reader exposure log](../logs/2026-10-16-reader-exposure.md): the sources for the lists, read by hand on 16 Oct.
- `exposure_atlas_checks` in [results.json](../results.json); records in [data/expatlas/](../data/expatlas/README.md).
