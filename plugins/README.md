# VC3D plugins

Manifests that put this repository's tools, and some community tools, in VC3D's **Plugins** menu. Each `.json` file declares one program, its arguments with placeholders for what VC3D has open (the volume, the active segment, the selected ink detection), and how VC3D loads what the program writes, in formats VC3D already reads: an `umbilicus.json`, an `ink-detections.json` record, a point collection, a tifxyz segment, or a file to open.

The Plugins menu is not in villa yet. It is on the villa branch `vc3d-plugins` (manifest format and trust model: `volume-cartographer/docs/plugins.md` on that branch), proposed as a villa PR. Until it is merged, these manifests need a VC3D built from that branch. Tool page: [`docs/tools/vc3d-plugins.md`](../docs/tools/vc3d-plugins.md).

## Use them

```sh
export VC3D_PLUGIN_PATH=/path/to/Scrolls/plugins
VC3D
```

VC3D also reads `~/.vc3d/plugins/`, so you can copy single manifests there instead. **Plugins > Plugin Folders...** shows what was loaded and what was skipped and why. Each run writes into `~/.vc3d/plugin-runs/<id>/<UTC time>/`, with `plugin-run.json` recording the manifest's SHA-256 and the exact command.

`python3` must be the Python that has each tool's packages (for a virtual environment, edit `program` to its full path). Manifests that call `python -m kit` go through [`run_kit.py`](run_kit.py), which runs the kit from this checkout so no install is needed.

## The manifests

| File | Menu | Runs | VC3D loads | Needs in VC3D |
| --- | --- | --- | --- | --- |
| `scrolls-umbilicus.json` | Scrolls | [scroll center finder](../docs/tools/umbilicus.md), `scripts/umbilicus/predict.py --vc3d-name` | the `umbilicus.json` it writes, as the project's umbilicus | a project; asks for the scroll id |
| `scrolls-strokenet.json` | Scrolls | [StrokeNet](../docs/tools/strokenet.md), `python -m kit strokenet` | the result JSON, to open | a selected ink detection; asks for its pixel size |
| `scrolls-letterread.json` | Scrolls | [Scroll Text Reader](../docs/tools/letterread.md), `python -m kit letterread` with `letters-v2-ccby` | the overlay PNG, to open (JSON, CSV and PAGE XML beside it) | a selected ink detection |
| `villa-gen-umbilicus.json` | Volume Cartographer | villa's `vc_gen_umbilicus` on a normal grid folder | the `umbilicus.json` it writes | a volume; asks for the normal grid folder |
| `villa-render-layers.json` | Volume Cartographer | villa's `vc_render_tifxyz`, Render segment defaults | nothing (reports the run folder) | a local volume and an active segment |
| `villa-tifxyz2obj.json` | Volume Cartographer | villa's `vc_tifxyz2obj` | the OBJ, to open | an active segment |
| `v8in-ink.json` | Ink detection | Youssef Nader's v8in ink model through [`scripts/v8in_run.py`](../docs/tools/v8in-run.md) on `{segment}/layers` | the prediction PNG, added to the segment's ink detections | an active segment with a `layers/` folder; asks for the local v8in snapshot |

Before the first run of each tool, set it up as its page says. For the scroll center finder that means the released weights in `work/umbilicus/weights/` of this checkout (its guide's Quick start); the slices it reads are cached in `work/umbilicus/slices/`. StrokeNet and the Scroll Text Reader download their released weights once, SHA-256 checked. v8in needs a local snapshot of its Hugging Face repository and its packages.

## What the results are, and are not

- An umbilicus from the scroll center finder is model output. On the 13 published scrolls the released weights trained on that scroll, so the line is not a test there. Check it on CT slices before relying on it. It is in level-0 voxels of the scroll's 1.2 m scan; VC3D places it on another pyramid level of that scan from the stamped `volume_width`, `volume_height` and `volume_slices`.
- StrokeNet scores and Scroll Text Reader output are model output, not a reading. StrokeNet needs the organizers' full-resolution 8-bit map (a downsampled JPEG preview is not a fair input). The reader run here has no reverse-depth `--control`, so its `control.status` is `no_control`, which is not a pass; run it from the command line with `--control` for a read that can fail. Never put its overlay in a prize image.
- An ink detection is model output, not a reading.
- Output from prize-eligible or unpublished scrolls stays private until the prize announcement (hard rule 1).

## Not here yet

- **stackcheck** checks an ordered stack of segments, inner to outer. VC3D plugins get one active segment, so it needs a multi-segment placeholder first.
- **inkfilter** is not on this repository's default branch ([page](../docs/tools/inkfilter.md)).
- **villa's ink detection** (`ink-detection/optimized_inference`) reads its input from S3 and is configured by environment variables, so it does not fit a local plugin as it stands.

## Trust

A plugin runs a program on your computer with your permissions. VC3D shows the full command and asks before each run, never passes arguments through a shell, and loads only the declared result from the run's own folder. Read a manifest before you put it in a plugin folder.

## Checks

`python -m unittest tests.test_plugins` checks every manifest against VC3D's rules (a mirror of its parser), that files they name in this checkout exist, that the kit commands accept their arguments, and that the script options they pass exist.
