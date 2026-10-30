# parting: tell the same papyrus layer from the next one where two layers touch

Parting scores, at a contact between two touching papyrus layers in a CT scan, whether a second point lies on the first point's layer or on the next one, from base dinovol tokens and CT profiles; for tracers that must not switch sheets.

| Field | Value |
| --- | --- |
| Id | `parting` |
| Status | Current |
| Kind | script folder |
| Area | Surfaces and tracing |
| Run | `python3 scripts/parting/parting.py sites`, `features`, `score`, `fit`, `compare`, `frag3` |
| Code | `scripts/parting` |
| Tests | `tests/test_parting.py` (synthetic data only) |
| Needs | Python 3.10 or newer; numpy, scipy, scikit-learn 1.9 (the released model file was written with 1.9.1) and joblib; for `features` also torch 2.x, timm 1.x, einops and huggingface_hub; numcodecs only for compressed arrays; tifffile only for tifxyz input |
| Runs on | `features`: any CUDA GPU (283 Frag3 sites in about 4 minutes on one RTX PRO 6000, measured 2026-10-30) or CPU (slow: one site plus model load took 13 s on a 1-CPU smoke, measured 2026-10-30). `sites`, `score`, `fit` and `compare`: CPU, seconds to a few minutes (the Frag3 site rebuild took 4 minutes on a 4-core cloud container, 2026-10-30) |
| Network | The scan's zarr chunks over HTTPS (any public uint8 128^3 zarr v2 level, such as `dl.ash2txt.org` or the open-data bucket); the base dinovol checkpoint from Hugging Face (`scrollprize/dinovol_ps8_9.6um_101626`, pinned revision); nine pinned source files from `raw.githubusercontent.com/jimmylomro/hercUNet` (MIT); for `frag3`, the six Frag3 layer pointsets (about 1 GB) from `dl.ash2txt.org` |
| Writes | `sites`: the site JSON at `--out`. `features`: a run folder (`results.jsonl`, `features.npz`, `run.json`). `score`: the readout JSON at `--out`. `fit`: a joblib model at `--out`. `frag3`: `OUT/pointsets/`, `OUT/frag3_sites.json`, `OUT/run/`, `OUT/readout.json`, `OUT/frag3.json`. A download cache in `PARTING_CACHE` (default `~/.cache/parting`) and the Hugging Face cache |
| Go-ahead | Not needed |
| Released | Public `main` from 2026-10-30 (code, Apache-2.0); model file [`SharpMeow/parting-v1`](https://huggingface.co/SharpMeow/parting-v1) on Hugging Face from 2026-10-30 (CC BY-NC 4.0) |
| License | Code: Apache License 2.0 ([`scripts/parting/LICENSE`](../../scripts/parting/LICENSE)); model file: CC BY-NC 4.0. It fetches, never copies: villa's dinovol model code (MIT) in the copy hercUNet vendors (MIT), and the base dinovol checkpoint, whose model page states no license |
| Checked | 2026-10-30 against commit `4966bc6` |

## What it does

Tracers follow a sheet of papyrus through the CT. Where two layers press together, the scan shows one thick band, and a tracer can step onto the neighboring layer without noticing: a sheet switch. Parting looks at one such place at a time. Give it a point `a` on one layer, a second point `a2` on the same layer and a point `b` on the next layer at the same distance from `a`, and it gives the pair (a, a2) and the pair (a, b) each a score; a higher score means "same layer".

It reads the 128^3 CT window around the three points, runs the Vesuvius Challenge's base dinovol encoder (`scrollprize/dinovol_ps8_9.6um_101626`) on it, and keeps the tokens at the three points, the CT along each point's normal, the CT along a to a2 and a to b, and base dinovol's own token cosine. A soft vote of gradient boosting and a one-layer MLP reads those 669 numbers per pair. Base dinovol's token cosine on its own is the control every result is compared against.

Parting does not trace, does not mend a trace and does not decide where a layer goes; it scores given point pairs. Its scores are model output about CT features, not a reading of the papyrus.

## When to use it

- You have two or more traced layers of one stack (pointsets, tifxyz or `.npy` grids) and want to know how well same-layer and next-layer points can be told apart where they touch.
- You build a tracer or a switch detector and want a per-contact score to test against base dinovol's cosine.
- You want to rerun the published Frag3 result from public data (`frag3`).

Do not use it:

- To find sheet switches along a whole trace: use a trace checker such as villa's own QA, or [contact-barrier](contact-barrier.md) to cut a trace back to its seed's sheet.
- Where two layers are fused (under 3 voxels apart along both normals): it adds little there (0.633 against 0.611 on 38 Frag3 sites).
- For ink: it reads no ink and makes no ink map.

## Quick start

Rerun the published Frag3 test's sites from public data, without reading any CT (CPU, about 1 GB download):

```bash
python3 scripts/parting/parting.py frag3 --model MODEL.joblib --out OUT --sites-only
```

`MODEL.joblib` is not read with `--sites-only`; any path works. `OUT` is a new folder. When it worked, it printed:

```
sites rebuilt from the pointsets match the frozen list (283 sites)
```

and `OUT/frag3.json` holds `"sites_sha256": "c67ee0de..."` with 150 touching sites over 5 layer pairs.

Features for your own sites, then a model you fit yourself and its readout:

```bash
python3 scripts/parting/parting.py sites --layer L0.vcps --layer L1.vcps --layer L2.vcps --shape Z Y X --out SITES.json
python3 scripts/parting/parting.py features --sites SITES.json --volume ZARR_LEVEL_URL --device cuda --out RUN
python3 scripts/parting/parting.py fit --run TRAIN_RUN --out MY.joblib
python3 scripts/parting/parting.py score --run RUN --model MY.joblib --trust-model --sites SITES.json --verdict --out READOUT.json
```

`L0.vcps` and so on are traced layers in stack order; `Z Y X` is the volume's shape in voxels; `ZARR_LEVEL_URL` is one level of a public uint8 zarr with 128^3 chunks (add `--resample SRC_UM:DST_UM` to read a finer level box-averaged to about 8 um voxels); `TRAIN_RUN` is a feature run on other layers than the ones you score.

## Checks and controls

Every readout carries three checks that can fail:

- **The control.** Base dinovol's own token cosine (`dino_base`) on the same rows. A result counts only as a gain over it: the gate asks for an AUC of at least 0.75, a gain of at least +0.05 over `dino_base`, and a 2.5 % bound of that gain above 0 from 20,000 resamples of layer pairs.
- **The pipeline check.** `dino_base` must score at least 0.85 on apart sites (both gaps 8 to 16 voxels); a broken read or a wrong frame fails it. On Frag3 it was 0.944.
- **The permutation gate.** The mean AUC of 1,000 label permutations must sit within 0.5 plus or minus 3 standard errors; it fails on a broken AUC or permutation (0.5004 on Frag3).

Measured strengths and limits (Model output, against the Vesuvius Challenge team's traced layer segments, each rule frozen before any of its test's 3D CT was read; [log](../logs/2026-10-29-parting-fragment-contact.md), [finding 23](../FINDINGS.md)):

| Object (fragment, scroll) | Touching sites, layer pairs | Parting | `dino_base` | Gain (2.5 % bound) | Verdict |
| --- | --- | --- | --- | --- | --- |
| PHerc1667Cr1Fr3 (PHerc1667), first tried | 203, 7 | 0.960 | 0.915 | +0.045 (+0.020) | FAIL by the margin |
| PHercParis1Fr34, Frag3 (PHerc. Paris 1), second | 150, 5 | 0.8952 | 0.8392 | +0.0560 (+0.0368) | PASS |
| PHercParis2Fr143 (PHerc. Paris 2), third | 270, 9 | 0.9754 | 0.9651 | +0.0103 (-0.0005) | FAIL |

One pass in three fragments. The gain was positive on all five Frag3 pairs, but three gained less than +0.05 alone. Where base dinovol is already near its ceiling (Paris 2, 0.965) there is little room to gain. The Frag3 scan (3.24 um) was box-averaged to 7.91 um.

Claim label: Model output, for every AUC above; Interpretation, for the ceiling remark.

## Commands and options

### sites

```
parting.py sites --layer L [--layer L ...] --shape Z Y X --out OUT [--scale S] [--row-step N] [--col-step N]
    [--seed N] [--dense N] [--spacing V] [--caps T A F M] [--stop-when-full] [--exclude-crossings VOX] [--need P]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--layer` | required | A `.vcps` pointset, an `.npy` (H, W, 3) xyz grid or a tifxyz folder; repeat in stack order |
| `--shape` | required | The volume's shape, Z Y X voxels; windows must lie inside it |
| `--out` | required | The site JSON to write |
| `--scale` | 1.0 | Multiply grid coordinates by this (a voxel size change, such as 3.24 / 7.91) |
| `--row-step`, `--col-step` | 1 | Keep every Nth grid row or column |
| `--seed` | 20261027 | The site draw's seed |
| `--dense` | 4 | Sub-steps per grid cell when densifying a layer |
| `--spacing` | 48 | Minimum voxels between two sites' `a` points in one pair |
| `--caps` | 30 30 15 10 | Sites per layer pair for touching, apart, fused, mixed |
| `--stop-when-full` | off | Leave a pair once every stratum is at its cap |
| `--exclude-crossings` | 0 (off) | Keep windows this many voxels from vertices whose next layer is not above them |
| `--need` | 0.995 | With `--exclude-crossings`: share of matched vertices whose next layer must lie above |

### features

```
parting.py features --sites SITES.json --volume URL --out RUN [--resample SRC_UM:DST_UM] [--device cpu|cuda]
    [--checkpoint teacher_305k.pt] [--threads N] [--ids ID ...] [--limit N]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--sites` | required | A site JSON from `sites` |
| `--volume` | required | One level of a public zarr v2 array, uint8, 128^3 chunks |
| `--out` | required | The run folder; an existing one is resumed |
| `--resample` | none | Read a finer level box-averaged to `DST_UM` voxels (only coarsening) |
| `--device` | cpu | `cuda` uses bf16 autocast, as the published runs did |
| `--checkpoint` | download | A local copy of `teacher_305k.pt`, checked by sha256 |
| `--threads` | torch default | CPU threads |
| `--ids`, `--limit` | all | Only these sites, or the first N |

### score

```
parting.py score --run RUN --model MODEL.joblib --out READOUT.json [--sites SITES.json] [--verdict] [--trust-model]
    [--boot N] [--permutations N]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--run`, `--model`, `--out` | required | The feature run, the model file and the readout to write |
| `--sites` | none | The site file, for the reported row of touching sites with both gaps at most 4 voxels |
| `--verdict` | off | Apply the gate (PASS, FAIL or VOID) |
| `--trust-model` | off | Load a model file whose sha256 is not a released one (loading runs pickled code) |
| `--boot` | 20000 | Layer-pair resamples for the bounds |
| `--permutations` | 1000 | Label permutations for the gate |

### fit, compare and frag3

```
parting.py fit --run RUN [--run RUN ...] --out MODEL.joblib
parting.py compare RUN_A RUN_B [--model MODEL.joblib] [--trust-model]
parting.py frag3 --model MODEL.joblib --out OUT [--device cpu|cuda] [--checkpoint F] [--threads N] [--ids ...]
    [--limit N] [--pointsets DIR] [--no-download] [--sites-only] [--trust-model]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--run` (fit) | required | A feature run to train on; repeat for more |
| `run_a`, `run_b` | required | `compare`: two feature runs of one site file |
| `--model` | required for `frag3` | The model file; with `compare`, also compare Parting's scores |
| `--pointsets` | `OUT/pointsets` | `frag3`: a folder of `SEGMENT/pointset.vcps` |
| `--no-download` | off | `frag3`: use the pointsets already in the folder |
| `--sites-only` | off | `frag3`: rebuild and check the sites, read no CT |
| `--version` | | Print `parting 1.0.0` |

`fit` trains the recipe on the touching sites of the given runs (run folder names must differ). `compare` prints the largest differences between two feature runs per group and score, and with `--model` between their Parting scores, with the share of sites whose same-or-next order agrees. `frag3` rebuilds the frozen Frag3 sites from the public pointsets (refusing any other hash), computes their features, scores them and prints the result beside the published one; with `--ids` or `--limit` it is not judged.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `PARTING_CACHE` | `~/.cache/parting` | Where the pinned encoder source files are kept |
| `HF_HOME` | Hugging Face default | Where the dinovol checkpoint is cached |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `partgeom.make_sites(grids, shape_zyx, rule)` | list of site dicts with ids | `ValueError` on bad grids | `grids`: {name: (H, W, 3) xyz} in stack order |
| `partgeom.sites_sha256(sites)` | hex string | none | Canonical JSON hash of a site list |
| `partct.open_volume(url, resample=None)` | an object with `.shape` and `.read(lo, size)` | `SystemExit` on a wrong array | zyx windows, voxels outside read as 0 |
| `partenc.Encoder(device, checkpoint=None)` | `.tokens(ct)` gives (288, 16, 16, 16) | `SystemExit` on a hash mismatch | Downloads pinned code and weights |
| `partfeat.site_features(site, ct, tokens)` | ({group: array}, {score: [same, cross]}) | none | Pure numpy |
| `partmodel.design(rows, F)` | X (2 rows per site, 669 columns), y, pair, stratum, control | none | Same pair first, then next-layer pair |
| `partmodel.readout(rows, s, y, grp, strat, ctrl, ...)` | readout dict with `verdict` | none | The gate in `partmodel.RULE` |
| `partmodel.load_model(path, trust=False)` | (model, record) | `SystemExit` for an unknown file without trust | Refuses before unpickling |

## Inputs

- **Layer grids:** VC ordered pointsets (`.vcps`), `.npy` (H, W, 3) float xyz grids or tifxyz folders (`x.tif`, `y.tif`, `z.tif`), in xyz voxels of the volume read; invalid vertices are negative or not finite. Consecutive layers must be one-sided along y for `--exclude-crossings`.
- **Sites:** JSON with a `sites` list; each site has `id`, `pair`, `stratum`, `a`, `a2`, `b` (xyz), `n_a`, `n_a2`, `n_b` (unit normals), `gap_a`, `gap_b`, `dist`, `dist_same` and `centre` (xyz voxel of the 128^3 window's center).
- **Volume:** one level of a zarr v2 array, uint8, 128^3 chunks, raw or with a numcodecs compressor, read over HTTPS. Parting's model was trained on 7.9 to 9.4 um voxels; read finer scans with `--resample`.
- **Model:** a joblib bundle with `model` and either `columns` (a mask) or `features` (669).

## Outputs

`results.jsonl`: one row per site, `id`, `pair`, `stratum` and `scores` (`dino_base` and `ct_valley`, each [same pair, next-layer pair]). `features.npz`: `ids` and one float16 array per group (`tok` (S, 3, 288), `ct_n` (S, 3, 17), `ct_seg` (S, 2, 16), `p_tok` (S, 2, 2, 16)). `run.json`: volume, resampling, encoder pins, device, torch version, wall time.

The readout JSON:

| Field | Type | Meaning |
| --- | --- | --- |
| `table` | object | Per stratum: `sites`, `pairs`, `parting` and `dino_base` AUC |
| `primary` | object | Touching sites: `parting`, `dino_base`, `delta`, `parting_bound`, `delta_bound` (2.5 % bounds) |
| `permutation_gate` | object | `k`, `mean`, `half_width`, `ok` |
| `per_pair` | object | Touching AUCs and gain per layer pair (reported, never judged) |
| `verdict` | string or null | PASS, FAIL or VOID with `--verdict`, else null |
| `void_reasons` | list | Why a run is VOID |
| `model`, `features_sha256` | object, string | What was scored |

| Exit code | Meaning |
| --- | --- |
| `0` | The command finished; for `score`, read `verdict` for the result |
| `1` | A refusal or error, with its message on stderr (see Failure modes) |
| `2` | A missing or wrong argument |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `box_weights only coarsens (ratio...< 1)` | A finer target than the source | Give `--resample SRC:DST` with DST at least SRC |
| `--resample...: need 0 < SRC_UM <= DST_UM` | The same, or a zero | As above |
| `.../.zarray: not found` | The URL is not one zarr level | Point at the level folder, such as `.../volume.zarr/0` |
| `...: need uint8 128^3 chunks, got...` | Another dtype or chunk size | Use a uint8 level with 128^3 chunks |
| `--resample...:...: only a coarser voxel is supported` | Upsampling asked | Read a coarser level instead |
| `--resample...: need SRC_UM:DST_UM, such as 3.24:7.91` | Not two numbers | Write it as in the message |
| `.../...@...: sha256...is not the pinned...` | The downloaded checkpoint changed | Do not go on; report it |
| `...: sha256...is not the pinned...(.../...)` | A local `--checkpoint` is another file | Give the pinned `teacher_305k.pt` |
| `base dinovol: missing weights...` | The checkpoint does not match the code | Use the pinned checkpoint |
| `--device cuda: no CUDA GPU here; use --device cpu` | No GPU | Use `--device cpu` (slow) or a GPU machine |
| `...: sha256...is not the pinned...` | A fetched source file changed upstream | Do not go on; report it |
| `...: no pointset.vcps with the pinned sha256 of layer(s)...; run frag3 without --no-download` | Frag3 pointsets missing or different | Run without `--no-download` |
| `crossings:...points, sha256...; the frozen run had...,...` | The rebuilt crossings differ | The pointsets or numpy changed; report it |
| `...:...values, header says...x...x...` | A truncated `.vcps` | Download it again |
| `...to...: stack order not one-sided (...matched,...positive)` | Layers out of order or crossing | Give layers in stack order |
| `...: give a .vcps pointset, an .npy grid or a tifxyz folder` | Another file type | Convert the layer |
| `...: no sites list` | Not a site JSON | Make one with `sites` |
| `give at least two --layer grids, in stack order` | One layer | Give two or more |
| `...holds sites read from another volume or resampling; use a new --out` | Resuming a run with another volume | Use a new run folder |
| `...and...share no site` | `compare` on unrelated runs | Compare runs of one site file |
| `sites made from the pointsets (sha256...) differ from the frozen site list (...)` | The Frag3 rebuild drifted | Report it; do not score |
| `.../features.npz has no...: not a Parting feature run` | Another kind of run folder | Make features with `features` |
| `...: sha256...is not a released Parting model; loading it would run its pickled code, so pass --trust-model only for a file you made or trust` | An unknown model file | Pass `--trust-model` only for your own file |
| `...: the model reads...columns, not the...of...` | A model with another layout | Use a model fit by `fit` |
| `two --run folders share a name; copy one under another name` | `fit` names runs by folder | Rename one folder |
| `no touching sites in the given runs` | Nothing to train on | Make sites with touching contacts |

## How it works

The folder's modules: `parting.py` is the command line, `partgeom.py` makes contact sites from layer grids, `partct.py` reads zarr windows and box-resamples them, `partenc.py` loads base dinovol, `partfeat.py` makes the per-site features, `partmodel.py` holds the classifier, readout and gate, and `partfrag3.py` pins the Frag3 test.

1. **Sites** (`partgeom`). Each layer grid is densified (`--dense` sub-steps per cell). For a vertex `a` on layer A, its gap to layer B is the distance along B's local normal to B's nearest densified points (median of 4). A site takes a random `b` on B 16 to 24 voxels from `a` and an `a2` on A at the same distance from `a` (within 1 voxel), so distance alone cannot tell the two pairs apart. Strata by the two normal gaps: fused (both under 3), touching (both 3 to 8), apart (both 8 to 16), mixed (the rest up to 16). The three points must fit within 40 voxels of the window center.
2. **Read** (`partct`). The 128^3 window around the site center, zyx. With `--resample`, each output voxel is the area average of the source voxels it overlaps, rounded to uint8.
3. **Tokens** (`partenc`). Base dinovol (patch 8, 288 channels) on villa's robust normalization (1 to 99 percentile clip, median and 1.4826 MAD), giving a 16^3 token grid.
4. **Features** (`partfeat`). Tokens sampled trilinearly at the three points; CT along each normal, -8 to +8 voxels, after a per-window robust scale; CT and token cosines at 16 points from `a` to `a2` and from `a` to `b`; `dino_base` (the token cosine of the two points) and `ct_valley` (the darkest CT on the segment over the mean of its ends).
5. **Rows** (`partmodel.pair_rows`). Per pair, 669 numbers that do not change when the two points swap or a normal flips sign: token product and absolute difference, even and odd parts of the profiles, and summaries of the token path.
6. **Model.** A soft vote (mean probability) of `HistGradientBoostingClassifier` (600 iterations, 31 leaves, learning rate 0.05) and a 64-unit MLP, trained on touching sites only.

Not yet in the stage registry (`python -m kit stages`): none of its stages scores contacts between layers, so Parting is run on its own. Interface gap, recorded here as the tool standard asks.

## Cost and time

Measured 2026-10-30: `features` on 283 Frag3 sites took about 4 minutes on one RTX PRO 6000 Hugging Face Job (about 0.2 USD at 2.75 USD per hour), reading about 5,700 chunks of the 3.24 um level; one site on a 1-CPU smoke took 13 s with model load. The Frag3 site rebuild took 4 minutes on a 4-core cloud container. `score` with 20,000 resamples and 1,000 permutations took under a minute on that container.

## For agents

- **Command:** `python3 scripts/parting/parting.py score --run RUN --model MODEL --sites SITES.json --verdict --out READOUT.json`; read `READOUT.json`.
- **Parse:** `verdict`, `primary.parting`, `primary.dino_base`, `primary.delta`, `primary.delta_bound`, `permutation_gate.ok`, `table.apart.dino_base` (the pipeline check).
- **Rerun:** `features` resumes a run folder and refuses another volume; `score` overwrites its `--out` only.
- **Success:** exit 0 and a `verdict`; PASS means all three gate parts held on touching sites.
- **Not a pass:** an AUC without `dino_base` beside it; a run with fewer than 100 touching sites or 5 pairs; a score on sites the model was fit on.
- **Go-ahead:** Nothing for public data. Renting a GPU follows your own compute rules.
- **Never:** call a score a reading; fit and score on the same layers; load a model file you did not make with `--trust-model`.

## Tests

`python3 -m unittest tests.test_parting -v` covers the AUC with ties, the 669-column layout and its normal-sign symmetry, box resampling (weights sum to 1, Frag3's resampled shape, a flat volume stays flat), the gate's PASS, FAIL and VOID on synthetic scores, the permutation gate, the refusal of an unknown model file, site making on two synthetic layers 5 voxels apart, the site hash and the stack-order check, and the stored feature shapes. They need numpy (and scipy for sites) and read no scan; they do not run the encoder.

## History

- 2026-10-30: first public release, code only, Apache-2.0 (Parting 1.0.0; [#292](https://github.com/ChaseHendrick/Scrolls/pull/292)).
- 2026-10-30: the trained model file, `parting-v1.joblib`, published on Hugging Face as [`SharpMeow/parting-v1`](https://huggingface.co/SharpMeow/parting-v1) (CC BY-NC 4.0).

## Related

- [Finding 23](../FINDINGS.md) and the [Frag3 log](../logs/2026-10-29-parting-fragment-contact.md): the three fragment tests in full.
- [contact-barrier](contact-barrier.md): cuts a finished trace back to its seed's sheet at touching sheets.
- [dinovol-embeddings](dinovol-embeddings.md): base dinovol features released for PHerc0841.
