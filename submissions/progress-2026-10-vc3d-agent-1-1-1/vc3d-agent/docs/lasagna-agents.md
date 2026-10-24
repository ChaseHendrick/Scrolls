# Headless lasagna for agents

Checked 24 October 2026 with villa main [`6f202456`](https://github.com/ScrollPrize/villa/commit/6f2024569404a46b0f008eee292773945c07a684). villa's lasagna (`lasagna/` in villa) fits multi-winding surface meshes to its predicted normals, `grad_mag` and `cos` volumes. VC3D drives it through an HTTP fit service, and its `fit.py` runs from a shell, but neither gives an agent a result it can read. `kit/lasagna.py` is that layer: seven tools that take JSON and return JSON, on top of villa's own code. Nothing here reimplements the fit.

| Route | Start it with | Use it for |
| --- | --- | --- |
| MCP server | `python -m kit vc3d mcp` (the `lasagna_*` tools sit beside the VC3D tools) | Agents with MCP: typed arguments, progress, cancellation |
| Shell | `python -m kit lasagna COMMAND '{...}'` or `--key value` flags; `python -m kit lasagna tools [--json]` | Agents with only a shell, scripts |
| Shell, the agent way | `python -m kit vc3d call lasagna_fit '{...}'` | The same as the MCP tools, one call at a time |

Results are JSON on stdout, progress on stderr. Exit 0 when the tool succeeded, 1 when it ran and failed (a fit that exited non-zero, a self-test that did not pass, a service job in error), 2 when it could not run: bad arguments, villa not set up (a `LASAGNA_PYTHON` that does not start included), a fit service it cannot reach or a failed download (a transfer cut off part way included), as `kit vc3d call` does; the JSON `error` says which. On the shell, flags may come before or after the JSON (or `@file.json`) arguments, an array flag may repeat (`--config a.json --config b.json`, one `--external-surfaces '{...}'` per surface), and a boolean flag takes a value only when `true` or `false` (or `1`, `0`, `yes`, `no`, `on`, `off`) follows it. Long tools (`manifest`, `fit`, `export`, `selftest`) take `"background": true` (or `--background`) and run as a job that `jobs` reads, as in [vc3d-agents.md](vc3d-agents.md#background-jobs). Outputs go under `work/vc3d/lasagna/` of the kit home (kept out of git; [AGENTS.md](../AGENTS.md) rule 6), each with a `receipt.json`; a fit's receipt also records its export (command, exit, tifxyz).

## Setting up

You need a villa checkout with `lasagna/` and `vesuvius/src/` (fit.py imports `vc3d_fiber_format` from it) and a Python with torch, numpy, zarr, tifffile and tensorstore: villa's `lasagna/scripts/bootstrap_venv.py` (`lasagna-bootstrap`) makes one. A CPU-only torch is enough for the self-test and small fits. kit itself is standard library.

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/ScrollPrize/villa.git
git -C villa sparse-checkout set lasagna vesuvius/src
python3 -m venv lasagna-venv
lasagna-venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch
lasagna-venv/bin/pip install numpy zarr tifffile tensorstore
export VILLA_DIR="$PWD/villa" LASAGNA_PYTHON="$PWD/lasagna-venv/bin/python"
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `LASAGNA_DIR` | then `VILLA_DIR/lasagna`, then `~/villa/lasagna` (VC3D's own search) | villa's lasagna folder, the one holding `fit.py` |
| `LASAGNA_PYTHON` | then `LASAGNA_DIR/.venv/bin/python` (the bootstrap's), then this Python | the Python that runs fit.py |

Then `python -m kit lasagna status --check-import` (where villa is, its commit, what its Python has, CUDA or not) and `python -m kit lasagna selftest`.

## The tools

| Tool | What it does |
| --- | --- |
| `lasagna_status` | Where villa's lasagna is and its commit; the Python, its packages, CUDA and MPS; with `check_import`, whether `import fit` works. Says which device a fit will default to |
| `lasagna_configs` | villa's shipped configs (35 at `6f202456`): each one's mode (`model-init`), init mode (a seed config without one runs villa's default `cylinder_seed`), stages and steps, loss terms, and what a run still needs from the caller (`seed` and `model_h` for a new model, as fit.py requires, plus the manifest's umbilicus for `cylinder_seed`; `corr-point-roi` works out both itself, and `approval-inpaint` works out `model_h` but needs the seed and `args` `approval-inpaint-tifxyz`; `tifxyz_init` for ext, `model_input` for model, one `external_surfaces` entry for flatten, `atlas` for atlas, `init_shell_dir` and `corr_points` for `shell-dir-crop` and `corr-point-roi`). `name` returns one in full. Invalid ones are listed with the parse error |
| `lasagna_manifest` | The local `.lasagna.json` fit.py needs. From a published run (the open data bucket publishes them under `<scroll>/representations/predictions/lasagna/`): without `crop`, the manifest plus VC3D's `lasagna-remote.json` marker, so fit.py streams the published stores (CUDA only); with `crop` (x0, y0, z0, w, h, d in base voxels), a mirror of only the chunks under that box, which any device can fit. The box grows to whole voxels of the coarsest group first (the result says `crop_snapped`), because of the `load_3d` quirk below. A local manifest is only checked, against villa's rules (channels, relative paths, levels 0 to 32, level shapes as ceil-halvings of `base_shape_zyx`, uint8, and an `umbilicus_json` that exists); villa's older flat (C, Z, Y, X) groups count. `umbilicus` (published sources only) puts an umbilicus JSON beside the new manifest for `cylinder_seed`; for a local manifest, put the file beside it and set `umbilicus_json` to its name. A mirror that fails part way says so and resumes when run again with the same `out` (copied chunks are kept) |
| `lasagna_fit` | One fit.py run: villa configs merged left to right, then kit's overrides (input, mode, seed, model size, start tifxyz or checkpoint, external surfaces, correction points, device, out-dir, progress). Returns the `PROGRESS` readout (steps, first, last and lowest loss, non-finite count), checkpoints, each tifxyz with its stats, the crop, and on failure the log tail and hints. `export` also runs fit2tifxyz as VC3D does; its keys are checked before the fit runs, and a failed export keeps the fit's result and receipt. `dry_run` writes `fit_config_merged.json` and `command.json` and runs nothing; with no device the command is for a CUDA machine |
| `lasagna_export` | villa's `fit2tifxyz.py` on a checkpoint: one tifxyz per winding, or one segment (`single_segment`, `output_name`, one plain folder name) as VC3D asks; `voxel_um` gives the area; `target_volume_shape_zyx` rescales to another pyramid frame |
| `lasagna_selftest` | A synthetic fit on CPU whose check can fail: sheets of constant y, a start plane tilted 0.3 in x. With the normal term the fit must turn the plane to under a quarter of its tilt; the control (normal term off) must keep over 60 % of it |
| `lasagna_service` | A client for villa's fit service (`lasagna-fit-service`, the API VC3D speaks, `X-Fit-Service-API-Version: 2`), here or on a GPU machine: `discover` (`~/.fit_services`), `health`, `datasets`, `jobs`, `job` (with `wait`), `submit`, `cancel`, `results` (unpacks the result tar safely and reports each tifxyz) |

## Workflow

```bash
python -m kit lasagna status --check-import
python -m kit lasagna configs --name init_cyl.json
# a published run, mirrored for a box (any device)
python -m kit lasagna manifest --source s3://vesuvius-challenge-open-data/PHerc0139/representations/predictions/lasagna/20260102150214-lasagna-20260419180421-L2/ --crop 8000,13000,38000,512,512,512
# fit a start surface in that box
python -m kit lasagna fit --config stages.json --input work/vc3d/lasagna/inputs/PHerc0139-20260102150214-lasagna-20260724-crop/PHerc0139-20260102150214-lasagna-20260724.lasagna.json \
    --mode ext --tifxyz-init start.tifxyz --device cpu --voxel-um 2.4 --export '{"single_segment": true, "output_name": "agent.tifxyz"}'
```

`stages.json` is a villa config; the check below used `{"base": {"normal": 1.0, "step": 1.0, "smooth": 1.0}, "stages": [{"name": "check", "steps": 30, "lr": 0.1, "params": ["mesh_ms"], "min_scaledown": 0}]}`. `start.tifxyz` is any tifxyz inside the box, in the manifest's base voxels.

Modes follow villa's `model-init`: `seed` (a new model from `seed` and `model_h`, its height in base voxels, which no shipped config sets; villa's default init mode is `cylinder_seed`, which needs a cylinder config such as `init_cyl.json` and the manifest's umbilicus), `ext` (from `tifxyz_init`), `model` (re-optimize `model_input`; VC3D's Re-optimize and Offset), `flatten` (one `external_surfaces` entry, no input), `atlas`. VC3D picks `init*.json` for a new model, `corr*.json` to re-optimize, `offset.json` for an offset and `flatten*.json` to flatten. `args` takes any other fit.py argument as a config's `args` does (`{"mesh-step": 50}`); `overrides` takes top-level config keys (`stages`, `base`, `external_surfaces`), merged last, where lists replace and objects merge as in fit.py. fit.py takes `model-init` and `model_init` as one argument, the later in the merged args winning; kit reads them the same way, and writes its own fields (mode, paths, device, out-dir) under every spelling so they win.

The fit service runs one job at a time and reads `data_input` and surface paths on its own host. It takes mode `ext`'s start surface as `overrides.external_surfaces: [{path, offset: 0}]`, not as `tifxyz-init`. Mode `model` needs its checkpoint as `model_input` (a path on the service's host) or `model_file` (a `.pt` here, sent with the request); the service ignores `args.model-input`. A job that ends in error or is canceled exits 1 with its error and hints. A temporary result downloads once.

## Without CUDA

fit.py loads every volume through sparse streaming caches that need CUDA (`torch.cuda.Stream`), so off CUDA `lasagna_fit` runs it through [`scripts/lasagna/fit_cpu_shim.py`](../scripts/lasagna/fit_cpu_shim.py), which swaps in villa's dense loader (`fit_data.load_3d`, torch's `grid_sample`) without editing villa. The dense loader reads a box into memory, so:

- the box is `crop`, else the manifest's `kit_crop` (a mirror's), else the start surface's box plus `margin` (128) voxels, clipped to the volume; then a negative start is clipped at 0 and the edges grow to whole voxels of the coarsest group (the `load_3d` quirks below);
- the start surface's box is taken in the manifest's frame, scaled as fit.py scales the surface (its `meta.json` `base_shape_zyx`, else the config's `vc3d_volume_shape_zyx`, against the manifest's, a power of two; an older manifest without `base_shape_zyx` takes the frame fit.py works out, the finest level array times 2**scaledown): an export written with `target_volume_shape_zyx` lands where fit.py puts it. A start surface wholly outside the box is refused, a partial one noted;
- fit.py reloads the data at every stage; the shim keeps the last load, so a fit loads its box once. fit.py's `corr-point-roi` stage calls `load_3d` itself with no crop; the shim gives it the same box, and the size check counts that second load;
- a load over 6 GiB of uint8 voxels is refused before anything runs, and so is one whose level arrays kit cannot size;
- a manifest with a `lasagna-remote.json` marker streams, so it is refused off CUDA: mirror a crop first;
- the `data` and `data_plain` (cos) loss terms use a CUDA kernel, so a config that weights them is flagged and will fail; zero them in `overrides.base`.

This is for small checks, not real fits. Real-size fits need a CUDA machine: `dry_run` (with no device, or `device` `cuda`) writes the exact merged config and command to run there, and `lasagna_service` drives a fit service running on one.

## Checked on 24 October 2026

In a 4-core Linux container with no GPU: villa main `6f202456`, CPU torch 2.14.1, Python 3.13.

| Run | Result |
| --- | --- |
| `status --check-import` | Found villa through `VILLA_DIR`, 35 configs, `import fit` ok, default device cpu; 4 s |
| `selftest` | Passed in 9 s: start tilt 0.300, fit 0.0083, control 0.251; both arms 40 of 40 steps |
| `manifest` remote, the PHerc0139 run above | Manifest plus marker in 1.3 s; cos at level 3 (9620 x 3314 x 3314), `grad_mag`, `nx` and `ny` at level 4 (4810 x 1657 x 1657), all uint8, base 76953 x 26511 x 26511, no problems |
| `manifest` mirror, crop 8000,13000,38000 and 512 on a side | Snapped to 8000,12992,38000 and 512 x 528 x 512 (the coarsest spacing is 16); 27 cos chunks and 8 per other group, 1.6 MB, about 6 s, no absent chunks |
| `fit` on that mirror, mode `ext`, a 17 x 17 plane at y 13256, 30 steps of normal, step and smooth, with `export` | 6.6 s in all on CPU; loss 0.477 to 0.344; the surface moved to y 13241 to 13271; edges median 15.5 voxels (grid step 16); the export wrote `agent.tifxyz` with its area (0.0035 cm2 at 2.4 um) |

The tests in `tests/test_lasagna.py` drive the tools against a stand-in villa (a fake fit.py, fit2tifxyz.py, fit_data and torch), so they need no torch; the shim itself runs in them. A fitted surface is geometry fitted to model predictions: model output, not a reading, and not a claim about which winding it follows.

## villa quirks found

Each was seen on villa main `6f202456` (24 October 2026).

- `lasagna/configs/offset_snap.json` is not valid JSON (Python's parser stops at line 44, column 3: a missing comma between two stages), so fit.py and the service fail on it. `lasagna_configs` lists it under `invalid`.
- fit.py's own tifxyz export has no area in non-flatten modes: `voxel_size_um` is popped from the config (fit.py line 2201) before the export reads it (line 2538). In the check above the fit's own tifxyz had no area in its `meta.json` and the export's had it. `lasagna_export` with `voxel_um`, or `lasagna_fit` with `export`, writes it, as the service does.
- `fit_data.load_3d` with a crop sets the data's origin on the finest group's grid but reads each group from `start // its own spacing`, so a crop start that is not a multiple of the coarsest group's spacing samples the coarser channels up to that spacing minus one voxel off, with no error. It also reads from `max(0, start)` but sets the origin from the start as given, so a negative start shifts every channel by that many voxels. kit clips and grows every crop (`snap_crop`), so its fits are not affected; the streaming loader on CUDA was not checked.
- A path ending in `.json` after a flag (`--input X.lasagna.json`) is taken as a config file and exits 2. kit passes every argument inside its overrides JSON, so this cannot happen through it.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `torch.cuda.Stream requires CUDA support` | You ran villa's fit.py directly off CUDA: run it through `lasagna_fit` with device `cpu` or `mps` and a local or mirrored manifest |
| `cylinder_seed missing required stage role(s)` | Mode seed defaults to `cylinder_seed`: use `init_cyl.json` (with the umbilicus), or start from a tifxyz with mode `ext` |
| `No module named 'vc3d_fiber_format'` | Point `VILLA_DIR` at a checkout with `vesuvius/src`, or install lasagna from one |
| `requires exactly one external_surfaces entry` (service) | Send the start surface as `overrides.external_surfaces` |
| A dense load over 6 GiB is refused | Give a smaller `crop` in base voxels, or `device cuda` with `dry_run` for the command to run on a CUDA machine |
| `the start surface ... lies outside crop` | The crop (or the mirror's `kit_crop`) misses the surface in the manifest's frame: give a crop around it, or mirror one |
