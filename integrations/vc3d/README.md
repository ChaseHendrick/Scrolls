# Use your tools from VC3D

VC3D, the community's viewer for the scrolls, is getting a plugin host: a folder of small JSON files, each declaring one program, the arguments it takes from what is selected in VC3D, and the file VC3D loads when it finishes. The host is villa's `apps/VC3D/plugins/` (schema `vc3d-plugin/1`), written on the vc3d-plugins lane of the combined VC3D suite; it is not in villa's main branch yet. This folder holds one such file per Scrolls tool that VC3D can start, made from the tool registry (`python -m kit tools`, [page](../../docs/tools/toolreg.md)), so the same tool runs the same way from VC3D, from a terminal and from an agent.

## Set it up once

1. Give kit an electricity rate, because every local run is costed (AGENTS.md rule 9): `export SCROLLS_ELECTRICITY_USD_PER_KWH=0.2`, or put `{"electricity_usd_per_kwh": 0.2}` in `~/.config/scrolls/local.json`.
2. Point VC3D at this folder before you start it: `export VC3D_PLUGIN_PATH=/path/to/Scrolls/integrations/vc3d/plugins`. Or copy the manifests into the folder VC3D always reads: `python -m kit tools export-vc3d ~/.vc3d/plugins` (the launcher it writes there names your checkout).
3. The launcher, `plugins/bin/scrolls-tool`, runs `python3` from your `PATH`, which needs numpy and tifffile for the map tools.

## Use it

Open a project, make a segment active and select its ink map in the Ink Detection overlay, then pick a tool from the Scrolls menu. VC3D passes the segment, the selected map and the open volume; the tool finds the map's reverse-depth control beside it (`MAP_reverse.tif`) and the segment's labels by villa's names (`SEG_inklabels.zarr`, `SEG_supervision_mask.zarr`). When something it needs is not selected, VC3D says what is missing and does not start it. A voxel size of `auto` is read from the volume's `meta.json`.

Each run gets its own folder from VC3D. VC3D loads the tool's main result when it finishes: an ink map as a new ink detection (its 8-bit view on one scale shared with its controls, placed on the whole segment canvas when the tool ran on a focus region), a surface as a segment, points, an umbilicus, or a report. A tool that may take a focus region has a second entry, "(focus region)", enabled while one is set. Ink Lens maps only a focus region; it runs in local CPU mode with downloads off, so fetch its reader once first (`python3 spaces/ink-lens/engine.py fetch d9v2`). The whole result is `vc3d-result.json` in that folder: the status, whether the control was there (`no control: not a pass` when it was not), the format checks, every output with its hash, the page's rules for reading it, and the VC3D calls that would open its outputs.

Some entries need more than VC3D's placeholders. Tools that compare segments (overlap, stackcheck) or maps (verify) ask for segment ids or ink detection labels; the launcher reads them once, read-only, from the agent bridge of the VC3D that started it (found by its parent process, never another VC3D), so start VC3D with `--agent-bridge-name NAME` for these. verify's entry asks for all three maps, the control included.

VC3D treats a non-zero exit as a failure and loads nothing, so checks whose answer may be a fail (verify, stackcheck, doctor) run with `--exit-zero`: the report always comes back, and its verdict is inside it (`verdict`, `summary.clean`, `overall:`). A run refused before it starts, such as a segment id given without a bridge, writes `vc3d-result.json` with status `bad` and the reason into the run folder VC3D names.

Work that should not start from a menu gets a "Plan:" entry instead: GPU or Modal work, a first-use download, or anything over the 10 minute rule on a Mac. It writes `plan.json` with the command, the time, the disk and a digest, and runs nothing. A tool marked for it also gets "Run planned:", which takes that digest and runs only if the inputs are still the same. The scroll center finder is one: "Plan: Find the scroll's center line in the open volume" (Scrolls, viewer) plans it on the open 1.2 m scan, opened by its bucket URL; run the plan's command from a terminal with `--yes-download` (it reads 0.25 to 0.65 GB of slices and needs torch), then bring the line back with "Open run output as umbilicus" ([umbilicus](../../docs/tools/umbilicus.md#start-from-vc3d)).

"Open run output as segment, ink overlay, points, umbilicus or file" (Scrolls, Open run output) brings back any other output of a finished run, such as a reverse-depth control or a second file: it checks the run finished ok, its format checks passed and the file is unchanged, copies it into its own folder and lets VC3D load it.

From a terminal, or for an agent, the same tools take the same selection as flags:

```bash
python -m kit tools list --door vc3d
python -m kit tools run rowscore --segment SEG --ink-overlay SEG/MAP.tif --param voxel_um=auto --volume VOL --out RUN
python -m kit tools open RUN                       # the VC3D calls a result asks for, printed
python -m kit tools open RUN --live --apply        # sent to a running VC3D started with --agent-bridge-name NAME
```

`open --live` needs a VC3D built with its agent bridge; with no name it sends only to the VC3D that started the command. It checks first that VC3D still has the run's volume open, and sends only calls that open or show something (attach a segment or volume, load points, center the view), never one that edits, saves, deletes, grows or launches, and only for files inside the run folder. Loading points replaces every point collection in that VC3D, so it is sent only with `--replace-points`.

## What it never does

- It never rents compute: GPU and Modal work is planned only, and the variables that allow Modal are removed before a tool starts.
- It never writes outside the run folder. Inputs, the segment folder and the project file are checked before and after each run; a change marks the run violated, and nothing is opened.
- It never runs a tool whose page says it needs Chase's yes or that spends quota (a ZeroGPU Space, the Anthropic API), and never downloads without `--yes-download`.
- It opens nothing that fails its format check: a tifxyz with vertices at z <= 0 that are not marked missing, points that are not three finite numbers, a map whose shape does not fit the segment's canvas (more than 2 percent off), or a project or umbilicus VC3D would not read.
- In this public repository it refuses model output and readouts of a prize-eligible scroll; those runs belong in Scrolls-private under a preregistered experiment.
- An ink map it hands over is model output, not a reading.

## Formats

The tools read and write the community's formats: tifxyz segment folders (`x.tif`, `y.tif`, `z.tif`, `meta.json`), OME-Zarr volumes, VC3D point collections (version 1), villa's label names, and the `ink-detections.json` records VC3D reads for its Ink Detection overlay. Float maps also get 8-bit copies on one shared scale (`vc3d/views/`, with `vc3d/scale.json`), because VC3D stretches a non-8-bit image to its own range and would make a flat control look as strong as the map. When a tool writes something VC3D does not open, a converter turns it into something it does inside the same run folder: boxes on a segment's canvas become a point collection of their centers on the surface (canvas-points), and a surface-volume zarr becomes the layer TIFFs v8in reads (layers). villa's own programs (vc_render_tifxyz, vc_flatten, vc_grow_seg_from_seed, vc_gen_umbilicus, vc_tifxyz_selfcross, vc_tifxyz2obj) are listed for agents (`python -m kit tools list --door native`) and never run from the Scrolls menu: VC3D runs them from its own menus, except vc_tifxyz_selfcross, which has none and runs from a terminal.

## Not tested yet

- No result has been opened in a live VC3D window; the plugin host is tested with a stand-in that follows its source (`tests/fake_vc3d_host.py`).
- The host's format for `{region}` (read here as low x, y, z then high x, y, z in level-0 voxels, VC3D's focus bounds) and `{ink_overlay}` (read as the image's path) are inferred from its source.
- VC3D's plugin host loads one result per run, so a control map comes back through "Open run output" or `open --live`. It also refuses a start when a placeholder has no value, so optional inputs need their own entry (the "(focus region)" entries); an optional placeholder in the host would remove them. Host additions that would remove that step (an ink detection result that appends the forward map and its controls together, `VC3D_AGENT_BRIDGE_SOCKET` exported to plugins, a `{selection}` placeholder) belong in the one combined VC3D suite, not a separate villa PR.
- Checked against the plugin lane at `a0c8b9e6d`, rebased on villa main `d1b95150e` (21 Oct 2026); villa #2180 to #2183 change nothing under `apps/VC3D`.

Regenerate this folder after changing a manifest: `python -m kit tools export-vc3d integrations/vc3d/plugins` (the tests fail when it is out of date).
