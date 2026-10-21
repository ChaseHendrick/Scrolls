# toolreg: one registry of tools for the command line, VC3D and AutoPipeline

`python -m kit tools` reads one manifest per tool (what it takes, what it writes, its command and its safety rules) and runs it the same way from the command line, from VC3D's plugin host or as an AutoPipeline backend, with a write audit and a VC3D handoff.

| Field | Value |
| --- | --- |
| Id | `toolreg` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Pipeline and agents |
| Run | `python -m kit tools list`, `python -m kit tools show`, `python -m kit tools check`, `python -m kit tools availability`, `python -m kit tools selection`, `python -m kit tools plan`, `python -m kit tools run`, `python -m kit tools confirm`, `python -m kit tools take`, `python -m kit tools open`, `python -m kit tools exec`, `python -m kit tools export-vc3d` |
| Code | `kit/toolreg.py`, `kit/data/registry/`, `integrations/vc3d/`, `kit/cli.py` (`cmd_tools`), `kit/tooldocs.py` (`registry_problems`, `write_index`), `kit/localcost.py` (`run`) |
| Tests | `tests/test_toolreg.py`, `tests/fake_vc3d_host.py`, `tests/test_localcost.py` |
| Needs | Python 3.10 or newer, standard library only; numpy and tifffile for the 8-bit views of float maps and for turning a VC3D focus region into a box on a segment's canvas (both skipped with a warning without them). Each tool needs what its own page says. Reading a running VC3D (`--from-app`, `open --live`) needs `kit/vc3d_bridge.py` (in the AutoPipeline package) and VC3D built with its agent bridge. VC3D's plugin host is villa's `apps/VC3D/plugins/` on the vc3d-plugins lane of the combined VC3D suite, not merged into villa yet |
| Runs on | Any CPU. The registry adds well under a second to a tool's own time: a synthetic 400 x 600 rowscore run took 3.2 s wall in all, 1.0 s CPU (measured 2026-10-20, cloud container) |
| Network | None. A tool it runs uses the network only as its own page and its manifest's `safety.network` say; reading a running VC3D uses its local socket |
| Writes | Each run writes only its run folder: `--out RUN`, else `work/tools/ID-DIGEST10/` (or `experiments/SLUG/tools/` for a target run in Scrolls-private): `selection.json`, `registry-run.json`, the tool's outputs, `stdout.txt` and `stderr.txt` (unless the manifest captures stdout), `tmp/`, `vc3d/` (8-bit views, `scale.json`, point collections, `open-log.json`), `provenance.json`, `graph.json` and, last, `vc3d-result.json`. One cost entry per run in the ledger record `--slug`, else `tools-YYYYMMDD` (made once), under `KIT_TOOLS_LEDGER` or kit's ledger root. `export-vc3d DIR` writes `DIR/scrolls.ID.json` and `DIR/bin/scrolls-tool`. `python -m kit.tooldocs index` rewrites each manifest's facts block |
| Go-ahead | Not needed: it runs local tools on local or public data and refuses anything that needs a yes, spends money or posts |
| Released | Not on public `main` yet: branch `claude/integration-1020` since 2026-10-20 |
| Checked | 2026-10-20 against commit `3bd77be` |

## What it does

Chase's tools were reachable three different ways: the kit command line, VC3D (the community's viewer, through its agent bridge) and AutoPipeline (AP, the end-to-end pipeline). Each way knew each tool by hand. The tool registry replaces that with one manifest per tool, `kit/data/registry/ID.json` (schema `scrolls-tool/1`), that says what the tool takes (each input with where it binds from: the open volume, the active segment, its render, the selected ink map and its reverse-depth twin, the segment's labels in villa's naming, a focus point or region, an umbilicus, or an explicit path), its parameters, its command (an argument list whose words may name only `{in.NAME}`, `{in.NAME.FIELD}`, `{param.NAME}`, `{run}` and `{python}`), its outputs (every path under `{run}/`), its compute, its safety rules, an optional AP stage and how VC3D shows it. A `facts` block is copied from the tool page by `python -m kit.tooldocs index`, so the title, status, go-ahead and the page's Success, Not a pass and Never rules travel with the manifest and never drift.

Three front doors read the same manifests. The command line, `python -m kit tools`, lists, plans and runs them (agents use the same commands with `--json`). VC3D's plugin host gets one `vc3d-plugin/1` manifest per tool VC3D can start (`export-vc3d`, committed in `integrations/vc3d/plugins/`): it passes what is selected through its placeholders, starts the launcher, and loads the declared result. AP gets every tool that fits a stage: an ink tool becomes the backend `reg:ID` of the ink stage through `exec`, and a tool that already is a stage's backend (rowscore for triage) carries its manifest digest into that backend's entry. Viewers and services stay out of the pipeline and remain reachable from the other two doors.

Every run goes through the same gates before its command starts: no paid compute (Modal and GPU work is planned only, and `KIT_ALLOW_MODAL` and `MODAL_*` are removed from the child's environment), the local time and disk rule, writes only inside the run folder, no download without `--yes-download`, nothing whose page needs a yes, and no model output or readout of a prize-eligible scroll in public Scrolls. The command runs through `kit.localcost` (AGENTS.md rule 9) with its working folder and `TMPDIR` inside the run folder; every input, segment folder and project file is stat'ed before and after, and a change marks the run violated. Then come provenance, a causal-link graph and the VC3D handoff: 8-bit views of float maps on one shared scale, point collections, and a list of allow-listed VC3D calls in `vc3d-result.json`.

After the run, the format gate checks each declared output (unless it sets `"check": false`) with its format's checker before anything opens or reaches AP: a tifxyz folder (meta.json, x, y, z as one 2-D grid, finite vertices, no z <= 0 vertex without villa's missing mark x = -1), an umbilicus as VC3D's reader takes it, a VC3D project, a point collection (version 1, three finite numbers per point), an overlay against the segment's canvas (aspect within 2 percent), and OME-Zarr (a zarr group, its multiscale levels and a voxel size in meta.json). When `kit/villafmt.py` (AP's format layer, rules cited to villa source lines) is present, its checks are used too. A failure is exit 3 and nothing opens. An output may name one converter manifest (`"convert": "ID"`, kind `converter`), which runs in `RUN/convert/NAME/`, takes that output's place and is its own stage in `graph.json`.

Work that should not run from a menu is planned there instead. A tool with GPU or Modal work, a first-use download or a typical time over the 600 s rule on Chase's Mac gets only a "Plan:" entry in VC3D, which writes `plan.json` with a digest and exits 0; a tool whose manifest sets `vc3d.confirm` also gets "Run planned:", which runs a written plan only when its inputs bind again to the same digest (`confirm`). Five "Open run output as KIND" entries (`take`) bring back any checked output of a finished run, such as a control map or a second output, without changing VC3D. VC3D's plugin host refuses to start an entry when a placeholder has no value, so a tool with an optional focus region (inkfilter, auc) gets a second entry, "LABEL (focus region)", that passes `{region}`; VC3D enables it only while a focus region is set.

What it does not do: it does not run villa's own tools (they have manifests of kind native, so the command line lists them, but VC3D runs them from its own menus), it never launches paid compute, it never posts or uploads anything, and it has not been run against a live VC3D window (the plugin host is tested with a stand-in that follows its source). An ink map it hands over is model output, not a reading.

## When to use it

- Running any registered tool on what VC3D has selected, from VC3D's Scrolls menu or from a terminal (`--segment`, `--ink-overlay`, `--point`, `--region`, or `--from-app`).
- An agent that needs one uniform way to find a tool's inputs, run it and parse its result (`list --json`, `plan --json`, `run --json`, then `vc3d-result.json`).
- Adding a tool to VC3D: write its manifest, run `python -m kit.tooldocs index` and `python -m kit tools export-vc3d integrations/vc3d/plugins`.
- Adding a model-free or community ink tool to AP's ink stage without writing to the model registry file (`exec`).

Do not use it:

- To launch GPU or Modal work: its gates plan such work only; use the job's spec and its own approval route ([compute](../compute.md)).
- To run villa's own tools: use VC3D's menus or villa's binaries.
- For AP runs: use AutoPipeline's planner ([autopipeline](autopipeline.md)); the registry only adds backends to its stages.
- For a quick one-off command you already know: `python -m kit TOOL ...` directly is fine; wrap it in `python -m kit run local` ([run-local](run-local.md)).

## Quick start

```bash
export SCROLLS_ELECTRICITY_USD_PER_KWH=0.2      # once: every local run is costed (AGENTS.md rule 9)
python -m kit tools list --door vc3d
python -m kit tools plan rowscore --segment SEG --ink-overlay SEG/MAP.tif --param voxel_um=7.91
python -m kit tools run rowscore --segment SEG --ink-overlay SEG/MAP.tif --param voxel_um=7.91 --out RUN
python -m kit tools export-vc3d ~/.vc3d/plugins  # or point VC3D_PLUGIN_PATH at integrations/vc3d/plugins
```

`SEG` is a tifxyz segment folder and `SEG/MAP.tif` an ink map on its canvas, with its reverse-depth control `SEG/MAP_reverse.tif` beside it (found by the binder). `RUN` is a new or empty folder. On a synthetic 400 x 600 map (measured 2026-10-20, cloud container), `plan` printed the command with `--reverse SEG/MAP_reverse.tif` added and each gate's verdict, and exited 4; `run` printed:

```
rowscore: ok
Score: a measurement against published labels or a control, not a reading
report: voxel_um=7.91
  run folder: RUN
```

It worked when the exit code is 0 and `RUN/vc3d-result.json` has `"status": "ok"` and `"controls": {"verdict": "present"}`.

## Checks and controls

Each manifest names the controls of its result in `safety.controls` (an input, such as the reverse-depth twin of an ink map, or an output, such as a tool's own reverse map). The runner writes `controls.verdict` into `vc3d-result.json`: `present`, or `no control: not a pass` when one is missing. A model-output tool that makes maps must declare a control output, or `kit tools check` refuses its manifest. The write audit is itself a check that can fail: the tests run a fake tool that appends to its input, and the run is marked violated with exit 5 and nothing opened.

VC3D loads a map tool's result from its 8-bit view (`vc3d/views/NAME_u8.tif`), and `take ink_overlay` copies the view of the output asked for, checked against the sha256 the run recorded. VC3D stretches an ink detection over the whole segment grid, so a map made on a box of the canvas (a focus region, `--crop`) is placed at that box on a canvas of the segment's size, 0 elsewhere, which VC3D draws transparent (`scale.json` records the box); an 8-bit forward map keeps its values. The 8-bit views share one scale, taken from the forward map (its 0.5 and 99.5 percentiles), so a flat control stays flat: VC3D stretches any non-8-bit image to its own minimum and maximum (villa `InkDetectionOverlayController.cpp`, `toU8Scalar`), which would make a flat control look as contrasty as the forward map. The tests check that a constant control's view spans at most one gray level.

Claim label: Model output (every ink map it hands over); Interpretation (the doors, gates and binding rules)

## Commands and options

### `python -m kit tools list`

```
usage: python -m kit tools list [-h] [--door {cli,mcp,vc3d,ap,native}]
                                [--accepts {volume,segment,segment.render,segment.overlay,segment.overlay.reverse,segment.labels,segment.mask,segments,point,points,region,umbilicus,project,path}]
                                [--selection SELECTION] [--from-app [NAME]]
                                [--volume VOLUME] [--segment SEGMENT]
                                [--ink-overlay INK_OVERLAY] [--point POINT]
                                [--region REGION] [--crop CROP]
                                [--umbilicus UMBILICUS] [--project PROJECT]
                                [--points POINTS] [--segments SEGMENTS]
                                [--voxel-um VOXEL_UM] [--bridge-path SOCKET]
                                [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--door DOOR` | none | only tools with this door |
| `--accepts ACCEPTS` | none | only tools with an input bound from this |
| `--selection SELECTION` | none | a vc3d-selection/1 file |
| `--from-app NAME` | none | read the selection from a running VC3D's agent bridge (read-only calls); NAME or a socket path picks one, else the newest |
| `--volume VOLUME` | none | the open volume: a local zarr folder or a URL ({volume}) |
| `--segment SEGMENT` | none | the active segment's tifxyz folder ({segment}) |
| `--ink-overlay INK_OVERLAY` | none | the selected ink detection overlay image ({ink_overlay}) |
| `--point POINT` | none | the focus point x,y,z in level-0 voxels ({point}) |
| `--region REGION` | none | the focus region x0,y0,z0,x1,y1,z1 in level-0 voxels ({region}) |
| `--crop CROP` | none | a box Y0,Y1,X0,X1 on the segment's canvas |
| `--umbilicus UMBILICUS` | none | the attached umbilicus JSON ({umbilicus}) |
| `--project PROJECT` | none | the open project, a .volpkg.json ({project}) |
| `--points POINTS` | none | a point collection file |
| `--segments SEGMENTS` | none | a tifxyz folder; repeat in order (inner to outer) |
| `--voxel-um VOXEL_UM` | none | the volume's voxel size, when it cannot be read from it |
| `--bridge-path SOCKET` | none | read segment ids and the voxel size once from this VC3D's agent bridge (read-only); VC3D's launcher passes its parent VC3D's bridge |
| `--json` | off | print one JSON document instead of lines |

### `python -m kit tools show`

```
usage: python -m kit tools show [-h] [--json] id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | the tool's id, as `list` prints it |
| `--json` | off | print one JSON document instead of lines |

### `python -m kit tools check`

```
usage: python -m kit tools check [-h] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | print one JSON document instead of lines |

### `python -m kit tools availability`

```
usage: python -m kit tools availability [-h] [--json] id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | the tool's id |
| `--json` | off | print one JSON document instead of lines |

### `python -m kit tools selection`

```
usage: python -m kit tools selection [-h] [--selection SELECTION]
                                     [--from-app [NAME]] [--volume VOLUME]
                                     [--segment SEGMENT]
                                     [--ink-overlay INK_OVERLAY]
                                     [--point POINT] [--region REGION]
                                     [--crop CROP] [--umbilicus UMBILICUS]
                                     [--project PROJECT] [--points POINTS]
                                     [--segments SEGMENTS]
                                     [--voxel-um VOXEL_UM]
                                     [--bridge-path SOCKET] [--out OUT]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--selection SELECTION` | none | a vc3d-selection/1 file |
| `--from-app NAME` | none | read the selection from a running VC3D's agent bridge (read-only calls); NAME or a socket path picks one, else the newest |
| `--volume VOLUME` | none | the open volume: a local zarr folder or a URL ({volume}) |
| `--segment SEGMENT` | none | the active segment's tifxyz folder ({segment}) |
| `--ink-overlay INK_OVERLAY` | none | the selected ink detection overlay image ({ink_overlay}) |
| `--point POINT` | none | the focus point x,y,z in level-0 voxels ({point}) |
| `--region REGION` | none | the focus region x0,y0,z0,x1,y1,z1 in level-0 voxels ({region}) |
| `--crop CROP` | none | a box Y0,Y1,X0,X1 on the segment's canvas |
| `--umbilicus UMBILICUS` | none | the attached umbilicus JSON ({umbilicus}) |
| `--project PROJECT` | none | the open project, a .volpkg.json ({project}) |
| `--points POINTS` | none | a point collection file |
| `--segments SEGMENTS` | none | a tifxyz folder; repeat in order (inner to outer) |
| `--voxel-um VOXEL_UM` | none | the volume's voxel size, when it cannot be read from it |
| `--bridge-path SOCKET` | none | read segment ids and the voxel size once from this VC3D's agent bridge (read-only); VC3D's launcher passes its parent VC3D's bridge |
| `--out OUT` | none | write it here instead of printing it |

### `python -m kit tools plan`

```
usage: python -m kit tools plan [-h] [--selection SELECTION]
                                [--from-app [NAME]] [--volume VOLUME]
                                [--segment SEGMENT]
                                [--ink-overlay INK_OVERLAY] [--point POINT]
                                [--region REGION] [--crop CROP]
                                [--umbilicus UMBILICUS] [--project PROJECT]
                                [--points POINTS] [--segments SEGMENTS]
                                [--voxel-um VOXEL_UM] [--bridge-path SOCKET]
                                [--input NAME=PATH] [--param NAME=VALUE]
                                [--purpose {benchmark,smoke,target}]
                                [--experiment EXPERIMENT]
                                [--allow-outside {volume-folder,vc3d-cache-delete,mirror,kit-home,segment-folder,destructive}]
                                [--yes-download] [--json] [--write FILE]
                                id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | the tool's id |
| `--selection SELECTION` | none | a vc3d-selection/1 file |
| `--from-app NAME` | none | read the selection from a running VC3D's agent bridge (read-only calls); NAME or a socket path picks one, else the newest |
| `--volume VOLUME` | none | the open volume: a local zarr folder or a URL ({volume}) |
| `--segment SEGMENT` | none | the active segment's tifxyz folder ({segment}) |
| `--ink-overlay INK_OVERLAY` | none | the selected ink detection overlay image ({ink_overlay}) |
| `--point POINT` | none | the focus point x,y,z in level-0 voxels ({point}) |
| `--region REGION` | none | the focus region x0,y0,z0,x1,y1,z1 in level-0 voxels ({region}) |
| `--crop CROP` | none | a box Y0,Y1,X0,X1 on the segment's canvas |
| `--umbilicus UMBILICUS` | none | the attached umbilicus JSON ({umbilicus}) |
| `--project PROJECT` | none | the open project, a .volpkg.json ({project}) |
| `--points POINTS` | none | a point collection file |
| `--segments SEGMENTS` | none | a tifxyz folder; repeat in order (inner to outer) |
| `--voxel-um VOXEL_UM` | none | the volume's voxel size, when it cannot be read from it |
| `--bridge-path SOCKET` | none | read segment ids and the voxel size once from this VC3D's agent bridge (read-only); VC3D's launcher passes its parent VC3D's bridge |
| `--input NAME=PATH` | none | bind an input explicitly |
| `--param NAME=VALUE` | none | set a param |
| `--purpose PURPOSE` | `benchmark` | target needs --experiment, a preregistered ledger record (Scrolls-private) |
| `--experiment EXPERIMENT` | none | the ledger slug of a target run |
| `--allow-outside ALLOW_OUTSIDE` | none | allow one declared write outside the run folder, for this run |
| `--yes-download` | off | allow the tool's declared first-use download |
| `--json` | off | print one JSON document instead of lines |
| `--write FILE` | none | write the plan with its digest here and exit 0 (VC3D's Plan: entry); confirm runs it |

### `python -m kit tools run`

```
usage: python -m kit tools run [-h] [--selection SELECTION]
                               [--from-app [NAME]] [--volume VOLUME]
                               [--segment SEGMENT] [--ink-overlay INK_OVERLAY]
                               [--point POINT] [--region REGION] [--crop CROP]
                               [--umbilicus UMBILICUS] [--project PROJECT]
                               [--points POINTS] [--segments SEGMENTS]
                               [--voxel-um VOXEL_UM] [--bridge-path SOCKET]
                               [--input NAME=PATH] [--param NAME=VALUE]
                               [--purpose {benchmark,smoke,target}]
                               [--experiment EXPERIMENT]
                               [--allow-outside {volume-folder,vc3d-cache-delete,mirror,kit-home,segment-folder,destructive}]
                               [--yes-download] [--json] [--out OUT] [--fresh]
                               [--slug SLUG]
                               id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | the tool's id |
| `--selection SELECTION` | none | a vc3d-selection/1 file |
| `--from-app NAME` | none | read the selection from a running VC3D's agent bridge (read-only calls); NAME or a socket path picks one, else the newest |
| `--volume VOLUME` | none | the open volume: a local zarr folder or a URL ({volume}) |
| `--segment SEGMENT` | none | the active segment's tifxyz folder ({segment}) |
| `--ink-overlay INK_OVERLAY` | none | the selected ink detection overlay image ({ink_overlay}) |
| `--point POINT` | none | the focus point x,y,z in level-0 voxels ({point}) |
| `--region REGION` | none | the focus region x0,y0,z0,x1,y1,z1 in level-0 voxels ({region}) |
| `--crop CROP` | none | a box Y0,Y1,X0,X1 on the segment's canvas |
| `--umbilicus UMBILICUS` | none | the attached umbilicus JSON ({umbilicus}) |
| `--project PROJECT` | none | the open project, a .volpkg.json ({project}) |
| `--points POINTS` | none | a point collection file |
| `--segments SEGMENTS` | none | a tifxyz folder; repeat in order (inner to outer) |
| `--voxel-um VOXEL_UM` | none | the volume's voxel size, when it cannot be read from it |
| `--bridge-path SOCKET` | none | read segment ids and the voxel size once from this VC3D's agent bridge (read-only); VC3D's launcher passes its parent VC3D's bridge |
| `--input NAME=PATH` | none | bind an input explicitly |
| `--param NAME=VALUE` | none | set a param |
| `--purpose PURPOSE` | `benchmark` | target needs --experiment, a preregistered ledger record (Scrolls-private) |
| `--experiment EXPERIMENT` | none | the ledger slug of a target run |
| `--allow-outside ALLOW_OUTSIDE` | none | allow one declared write outside the run folder, for this run |
| `--yes-download` | off | allow the tool's declared first-use download |
| `--json` | off | print one JSON document instead of lines |
| `--out OUT` | none | the run folder (new or empty); default work/tools/ID-DIGEST10 |
| `--fresh` | off | a new run folder even when an identical run is done |
| `--slug SLUG` | none | the ledger record for the cost entry (default tools-YYYYMMDD) |

### `python -m kit tools confirm`

```
usage: python -m kit tools confirm [-h] [--plan PLAN] [--tool TOOL]
                                   [--out OUT] [--slug SLUG] [--json]
                                   digest
```

| Option | Default | Meaning |
| --- | --- | --- |
| `digest` | required | the plan's digest (10 or more hex characters) |
| `--plan PLAN` | none | the plan file (default: search VC3D's plugin run folders and work/tools/plans/) |
| `--tool TOOL` | none | refuse unless the plan is for this tool |
| `--out OUT` | none | the run folder (new or empty) |
| `--slug SLUG` | none | the ledger record for the cost entry |
| `--json` | off | print one JSON document instead of lines |

### `python -m kit tools take`

```
usage: python -m kit tools take [-h] [--run RUN] [--output OUTPUT] --out OUT
                                [--json]
                                {segment,ink_overlay,points,umbilicus,file}
```

| Option | Default | Meaning |
| --- | --- | --- |
| `kind` | required | how VC3D loads it: segment, ink_overlay, points, umbilicus or file |
| `--run RUN` | none | the run folder (empty: the newest finished run VC3D started) |
| `--output OUTPUT` | none | the output's name (empty: the first that fits KIND) |
| `--out OUT` | required | where to copy it (VC3D's {output}) |
| `--json` | off | print one JSON document instead of lines |

### `python -m kit tools open`

```
usage: python -m kit tools open [-h] [--live [NAME]] [--apply]
                                [--replace-points] [--json]
                                RUN
```

| Option | Default | Meaning |
| --- | --- | --- |
| `RUN` | required | a run folder: one `run` wrote, or an AutoPipeline run folder when a handler for it is installed |
| `--live NAME` | none | a running VC3D: a bridge name or socket path; with none, only the VC3D that started this command |
| `--apply` | off | send the allow-listed calls (with --live) |
| `--replace-points` | off | also send points.load_json, which replaces every point collection in that VC3D |
| `--json` | off | print one JSON document instead of lines |

### `python -m kit tools exec`

```
usage: python -m kit tools exec [-h] [--sha256 SHA256] id [WORD ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | an ink-command tool's id (the part after `reg:`) |
| `--sha256 SHA256` | none | the manifest digest prefix the plan pinned |
| `WORD` | none | three words after `--`: INPUT OUTPUT REVERSE, the ink command engine's `{input}`, `{output}` and `{reverse}` |

### `python -m kit tools export-vc3d`

```
usage: python -m kit tools export-vc3d [-h] [--check] [--include-private] DIR
```

| Option | Default | Meaning |
| --- | --- | --- |
| `DIR` | required | a folder VC3D reads: ~/.vc3d/plugins or one in VC3D_PLUGIN_PATH |
| `--check` | off | only say which files differ (exit 1 when any) |
| `--include-private` | off | also private tools (only into a folder outside both repositories) |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_TOOLS_LEDGER` | kit's ledger root (`experiments/` in the checkout) | where registry runs record their cost |
| `KIT_TOOL_PATH` | none | more folders of manifests, separated like `PATH`; the repository's own come first |
| `SCROLLS_ELECTRICITY_USD_PER_KWH` | none | the electricity rate `kit.localcost` needs before any run |
| `SCROLLS_KIT_ROOT` | the checkout the launcher sits in | where `bin/scrolls-tool` finds kit |
| `VC3D_AGENT_BRIDGE_SOCKET` | none | the parent VC3D's bridge socket, when the plugin host exports it; the launcher uses it before `~/.vc3d/agent_bridge/PID.json` |
| `VC3D_PLUGIN_RUNS` | `~/.vc3d/plugin-runs` | VC3D's plugin run folders, where `confirm` looks for plans and `take` for the newest finished run |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `SCHEMA` | `"scrolls-tool/1"` | nothing | the manifest schema |
| `SELECTION_SCHEMA` | `"vc3d-selection/1"` | nothing | what VC3D has selected |
| `RESULT_SCHEMA` | `"vc3d-result/1"` | nothing | a run's result, written last |
| `PLUGIN_SCHEMA` | `"vc3d-plugin/1"` | nothing | villa's VC3D plugin manifest |
| `Tool(manifest, path, source)` | one manifest with `id`, `digest`, `inputs`, `outputs`, `safety`, `facts` | nothing | the digest covers the authored part only |
| `Registry(tools=None, skip=None, problems=None)` | the loaded registry; `get(id)` | `get`: `RegistryError` | iterates in id order |
| `RegistryError()` | | | a bad manifest, argument or selection (exit 2) |
| `BindError()` | | | an input that cannot be bound; the message names what is missing |
| `load(root=ROOT, env=None)` | `Registry` | nothing | bad manifests become `problems` |
| `validate_manifest(m)` | list of problems | nothing | shape only; `check` adds the page and code checks |
| `doors(tool)` | list of `cli`, `mcp`, `vc3d`, `ap` or `native` | nothing | worked out from the manifest |
| `selection_from(volume=None, segment=None, ink_overlay=None, point=None, region=None, crop=None, umbilicus=None, project=None, points=None, segments=None, render=None, voxel_um=None, source='flags', app=None)` | a `vc3d-selection/1` dict | `RegistryError` | reads the segment folder's `meta.json`, render and `ink-detections.json` |
| `selection_from_app(name=None, call=None)` | a `vc3d-selection/1` dict | `RegistryError` | read-only bridge calls: `state.get`, `segments.list` |
| `bind(tool, sel, explicit=None)` | (placeholder values, record) | `BindError` | finds the reverse twin, labels and mask by villa's names |
| `plan(tool, job, run_dir=None)` | the dry run's dict | nothing | writes nothing |
| `run(tool, job, run_dir=None, fresh=False, slug=None, root=ROOT, ledger_root=None, env=None, registry=None)` | (result dict, exit code) | `RegistryError` for a busy `--out` | gates, ledger, audit, convert steps, format gate, handoff |
| `open_run(run_dir, live=None, apply=False, replace_points=False, call=None)` | the calls and what was applied | `RegistryError` for a call off the allow-list or a path outside the run | run-folder handlers first |
| `exec_ink(tool, input_path, output, reverse, sha=None, root=ROOT, ledger_root=None)` | exit code | `RegistryError` | AP's ink command engine calls it through `exec` |
| `stage_choices(stage, registry=None)` | `{backend: entry}` | nothing | what the registry adds to an AP stage |
| `existing_backends(tool)` | list of backend names | nothing | the stage backends a tool already is: `pipeline.existing`, or every enum value of the param it names as `{param.NAME}` |
| `ink_models(registry=None)` | `{reg:ID: command-engine entry}` | nothing | in memory; never written to the model registry file |
| `plugin_manifests(registry=None, include_private=False)` | `{key: vc3d-plugin/1 dict}` | nothing | run, "(focus region)", "Plan:" and "Run planned:" entries per tool, and the five "Open run output as KIND" entries |
| `plugin_result(tool, registry=None)` | `{kind, path}` | nothing | what VC3D loads after a run: an ink detection, a segment, points, an umbilicus or a file |
| `export_vc3d(dest, registry=None, include_private=False, root=ROOT, check_only=False)` | the files written, or those that differ | `OSError` | removes stale `scrolls.*.json` |
| `check(root=ROOT, commands=None, pages=None, env=None)` | list of problems | nothing | `python -m kit.tooldocs check` runs it |
| `facts_for(page, root)` | the facts dict | nothing | from a `kit.tooldocs.Page` |
| `write_facts(root=ROOT)` | the manifests changed | nothing | `python -m kit.tooldocs index` calls it |
| `register_opener(kind, fn)` | nothing | nothing | an extension's handoff for one output kind |
| `register_run_folder(fn)` | nothing | nothing | an extension's handler for another tool's run folders |
| `register_stage_check(fn)` | nothing | nothing | an extension's check of pipeline blocks |
| `load_cached(root=ROOT)` | `Registry` | nothing | `load` with the person's environment, kept until a manifest file changes (AP asks often) |
| `vc3d_reasons(tool)` | list of reasons | nothing | why VC3D gets no entry at all (a yes, quota, writes outside, destructive, an input VC3D cannot supply) |
| `vc3d_plan_reasons(tool)` | list of reasons | nothing | why VC3D gets only a "Plan:" entry (GPU or Modal, a download, over the 600 s Mac rule) |
| `vc3d_entries(tool)` | `[]`, `["plan"]`, `["plan", "confirm"]` or `["run"]` | nothing | the VC3D menu entries a tool gets |
| `parent_bridge(ppid=None, env=None)` | `{path, how}` or `None` | nothing | the bridge of the VC3D that started this process; never the newest |
| `enrich_from_bridge(sel, sock, call=None)` | a new, re-digested selection | `RegistryError` when the bridge's volume differs | read-only `state.get` and `segments.list`; a silent bridge is recorded |
| `format_gate(tool, job, outs)` | list of `{output, format, verdict, detail}` | nothing | each output's format checker; a fail means nothing opens |
| `write_plan(tool, job, path, explicit=None, given=None, yes_download=False)` | the plan dict | `OSError` | `scrolls-tool-plan/1` with the digest and the frozen selection |
| `find_plan(digest, plan_path=None, root=ROOT, env=None)` | (path, plan) | `RegistryError` | searches VC3D's plugin run folders and `work/tools/plans/` |
| `confirm(reg, digest, plan_path=None, tool_id=None, run_dir=None, root=ROOT, ledger_root=None, slug=None, kind=None)` | (result dict, exit code) | `RegistryError` when no plan matches | a changed manifest or input is refused, exit 3 |
| `take(kind, dest, run=None, output=None, env=None)` | the `take.json` dict | `RegistryError` | copies one checked output into VC3D's run folder |
| `launch(argv, env=None, ppid=None)` | exit code | nothing | what `bin/scrolls-tool` runs: `main` plus `--bridge-path` of the parent VC3D |
| `add_arguments(parser)` | the parser | nothing | the `python -m kit tools` actions |
| `main(argv=None)` | exit code | nothing | the launcher's entry |
| `cli(args, root=ROOT, env=None)` | exit code | nothing | prints errors, exit 2 |

## Inputs

A manifest's inputs bind from a selection (`vc3d-selection/1`), from `--input NAME=PATH`, or both (explicit wins). The selection comes from `--selection FILE`, from `--from-app` (a running VC3D, read once), or from the flags VC3D's plugin host fills. Coordinates are x, y, z in the volume's level-0 voxels; a region is low x, y, z then high x, y, z (VC3D's focus bounds); `--crop Y0,Y1,X0,X1` is a box on the segment's canvas, and a focus region is turned into one through the segment's tifxyz grid and `meta.json` scale. A canvas box also carries the canvas's size (`{in.NAME.canvas_h}`, `{in.NAME.canvas_w}`, 0 without a segment), so a tool reading a map of another resolution can scale the box (auc's `--window-canvas`). A map's reverse-depth control is the segment's ink detection record with role `control:reverse` that shares its model (AutoPipeline's `kit_villafmt.model`) or its name rule, else a file beside it: `MAP_reverse`, `MAP-reverse`, or, for a name ending in a forward variant letter, the same name with `r` (`ink_f` to `ink_r`, `MODEL-f` to `MODEL-r`). Labels and masks come from records whose `kit_role` or `artifact_type` says `labels` (`ink-labels`) or `mask` (`supervision`), then from villa's names. Records are read as VC3D reads them: `ink-detections.json`, else, when it is missing or empty, `catalog-origin.json`'s `ink_detections`.

| `from` | Binds to |
| --- | --- |
| `volume` | the open volume: a local zarr folder (its `meta.json` voxelsize gives `voxel_um`) or a URL, never fetched |
| `segment` | the active segment's tifxyz folder |
| `segment.render` | its surface volume: `layers/`, `surface_volume/` or a `.zarr` beside it; refused when there is none (a render is 1 to 1.7 GB and is a separate step) |
| `segment.overlay` | the selected ink map, else the first forward record of the segment's `ink-detections.json` |
| `segment.overlay.reverse` | the forward map's reverse-depth twin: a `control:reverse` record, else `FILE_reverse.EXT` beside it |
| `segment.labels`, `segment.mask` | `SEG_inklabels` and `SEG_supervision_mask` in villa's naming, in the formats the input lists |
| `segments` | several segment folders in order (`--segments`, repeated) |
| `point`, `points`, `region`, `umbilicus`, `project` | the focus point, a point collection file, the focus region, the attached umbilicus, the project file |
| `path` | only `--input NAME=PATH` |

A manifest's params come from `--param NAME=VALUE`, their defaults, or the selection (`from: volume.voxel_um`, asked for with the value `auto`).

## Outputs

`run` prints a short summary, or with `--json` the result. The run folder holds the files listed under Writes. `vc3d-result.json` (schema `vc3d-result/1`):

| Field | Type | Meaning |
| --- | --- | --- |
| `tool`, `title`, `manifest_sha256`, `selection_sha256` | string | what ran, on what |
| `status`, `exit` | string, integer | `ok`, `failed`, `bad`, `refused`, `planned` or `violated`, and its exit code |
| `claim` | string | `Model output, not a reading` for a model-output tool; a score or a check otherwise |
| `gates` | list | each gate's rule, verdict (`pass`, `refused`, `planned`, `warn`) and detail |
| `controls` | object | `required`, `present`, `verdict` |
| `outputs` | list | name, kind, format, path, role, bytes, sha256 (up to 4 MB) |
| `views` | object | 8-bit views of the maps, one shared scale, placed on the canvas for a crop (`vc3d/scale.json`); what VC3D loads |
| `views_sha256` | object | each view's sha256, checked by `take ink_overlay` |
| `open` | list | allow-listed VC3D calls: method, params, why; `replaces` when a call would replace the person's state |
| `vc3d.plugin_result` | object | the kind and path VC3D's plugin host loads |
| `report` | object | the page's Success, Not a pass and Never rules |
| `cost`, `provenance`, `graph` | object, object, string | the ledger entry, `provenance.json` and its digest, `graph.json` |
| `warnings`, `next_steps`, `applied`, `summary` | lists | notes, paths to open by hand, calls sent by `open --live --apply`, the printed lines |

`graph.json` uses AP's causal-link vocabulary (version 1): input file nodes (`outside_run`), one stage node `stage:tool:ID` with the manifest digest, output file nodes, `read` and `made` edges, and a `derived_from` edge when an input lies inside an AP run folder.

| Exit code | Meaning |
| --- | --- |
| `0` | done: the tool exited 0, wrote its required outputs and changed nothing outside its run folder |
| `1` | the tool failed or one of its outputs is missing (`check`: a problem; `availability`: something missing; `open --apply`: a call failed) |
| `2` | bad arguments, a bad manifest, an input that cannot be bound, or no electricity rate for the ledger |
| `3` | refused by a gate before anything ran |
| `4` | planned only: `plan`, or work that belongs on Modal, a GPU or past the local time rule |
| `5` | violated: the tool changed something outside its run folder; nothing is opened |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `the 8-bit view of NAME is missing or outside its run folder` | `take ink_overlay` on a run whose view was removed or moved | Run the tool again |
| `changed after its run (sha256 differs or was not recorded); refusing` | The output or its 8-bit view was edited after the run | Run the tool again; take never copies a changed file |
| `needs an active segment (`, `needs an open volume`, `needs a focus point`, `needs an enabled focus region`, `needs an attached umbilicus`, `needs a project saved on disk`, `needs a point collection file (--points FILE)`, `needs several segments in order (--segments PATH, repeated)` | The selection lacks what an input binds from | Select it in VC3D, pass the flag, or `--input NAME=PATH` |
| `needs a selected ink detection overlay (or a forward map listed in the segment's ink-detections.json)` | No ink map is selected | Select one in VC3D's Ink Detection overlay, or pass `--ink-overlay` |
| `(FILE_reverse beside it, or a control:reverse record in ink-detections.json)` | A required reverse-depth twin was not found | Make the reverse map (the same model with the depth order reversed) and put it beside the forward map |
| `in villa's naming, format` | The segment has no labels or mask in villa's names and the listed format | Put `SEG_inklabels.zarr` and `SEG_supervision_mask.zarr` in the segment folder, or `--input labels=PATH` |
| `); render one first with villa's vc_render_tifxyz into a folder you choose (about 1 to 1.7 GB for a whole segment), then pass --input` | The tool needs the segment's surface volume and none is beside it | Render it as a separate step, then pass `--input NAME=PATH` |
| `needs a box on the segment's canvas (--crop Y0,Y1,X0,X1) or a focus region` | A canvas box is needed | Pass `--crop` or enable a focus region |
| `VC3D's focus region holds no vertex of the active segment` | The focus region misses the segment | Move the region onto the segment |
| `turning VC3D's focus region into a box on the segment's canvas needs numpy and tifffile; pass --crop Y0,Y1,X0,X1 instead` | No numpy or tifffile | Install them, or pass `--crop` |
| `cannot read the segment's tifxyz grid in` | The segment's x, y, z TIFFs or `meta.json` are missing or unreadable | Check the folder with VC3D or villa's tools |
| `: cannot bind from` | An input names a `from` the binder does not know | Correct the manifest |
| `) could not be bound: give --input` | A required input of kind `path` | Pass `--input NAME=PATH` |
| `does not exist` | A bound path is missing | Check the path |
| `; its inputs:`, `; its params:` | An `--input` or `--param` name the tool does not have | Use a name `show ID` lists |
| `is needed: --param` | A required param has no value | Pass `--param NAME=VALUE` |
| `must be one of` | A param value outside its list | Use one of the listed values |
| `is not NAME=VALUE` | A malformed `--input` or `--param` | Write `NAME=VALUE` |
| `numbers separated by commas`, `finite numbers separated by commas` | A malformed `--point`, `--region` or `--crop` | Three, six or four numbers, comma separated |
| `: Y1 must exceed Y0 and X1 must exceed X0` | An empty `--crop` box | Give Y0 < Y1 and X0 < X1 |
| `duplicate key` | A manifest or selection file names one key twice | Remove the repeat |
| `} has no value`, `} is a list; it must be a whole argument` | A manifest word names a placeholder without a value, or a list inside a longer word | Correct the manifest |
| `is not empty; give a new or empty folder` | `--out` already holds files | Give a new folder |
| `the local cost ledger refused the run` | No electricity rate, or a bad `--slug` | Set `SCROLLS_ELECTRICITY_USD_PER_KWH` once, or give an existing slug |
| `has no vc3d-result.json: not a registry run folder` | `open` on another folder | Give a run folder `run` wrote |
| `, so nothing is opened` | The run did not finish ok | Read its `warnings` and `stderr.txt` |
| `is not on the allow-list; refusing the whole result`, `, which is not on the allow-list` | A result asks VC3D for a call that edits, saves, deletes, grows or launches | Do not open it; the result was changed or an opener is wrong |
| `, outside the run folder; refusing` | A result names a path outside its run folder | Do not open it |
| `reading a running VC3D needs kit/vc3d_bridge.py (in the AutoPipeline package and Scrolls-private); pass the selection as flags or --selection FILE instead` | `--from-app` or `open --live` without the bridge client | Pass the selection as flags, or use a kit with `kit/vc3d_bridge.py` |
| `no running VC3D with its agent bridge on (start it with --agent-bridge-name NAME)`, `no running VC3D with an agent bridge named` | No live bridge found | Start VC3D with `--agent-bridge-name NAME` |
| `is not an ink-command backend` | `exec` on a tool without an ink stage block | Use a tool `list --door ap` shows |
| `'s manifest changed after the plan was made (digest` | The manifest changed between AP's plan and its run | Make a new AP plan |
| `reverse must be 0 or 1, not` | `exec` got another value | Let AP's ink command engine call it |
| `exec takes ID -- INPUT OUTPUT REVERSE (the ink command engine's {input}, {output} and {reverse})` | `exec` without three words after `--` | Use the command `ink_models` writes |
| `--include-private writes only to a folder outside the repositories` | `export-vc3d --include-private` into the checkout | Export into `~/.vc3d/plugins` or another folder outside both repositories |
| `unknown action` | An action the parser does not have | Use one of the actions above |
| `the format gate failed for` (exit 3, `refused_by: ["format-gate"]`) | An output failed its format's check: a tifxyz with z <= 0 vertices not marked missing, points that are not three finite numbers, an overlay whose aspect is more than 2 percent off the segment's canvas, a project or umbilicus VC3D would not read | Fix the tool or its convert step; nothing was opened or handed to AP |
| `: the active segment has no ink detection labelled`, `: VC3D has no loaded segment`, `takes one segment id, not` | A bridge-bound input names a label or segment id VC3D does not have | Use the label shown in VC3D's Ink Detection list, or the segment's id |
| `which needs VC3D started with --agent-bridge` | A bridge-bound input and no parent bridge | Start VC3D with `--agent-bridge-name NAME`, or pass a path |
| `: the selection changed; start the entry again`, `that VC3D has volume` | The volume VC3D has open differs from the run's or the plugin's | Open the run's volume, or start the entry again |
| `VC3D's agent bridge closed the connection during`, `VC3D's agent bridge refused` | The bridge failed a read or an open call | Check that VC3D is still running with its bridge |
| `--live with no name sends only to the VC3D that started this command (its parent); name a bridge or socket path to send elsewhere; the newest bridge is never used` | `open --live --apply` from a terminal, with no name | Pass the bridge name or socket path |
| `a plan digest is 10 to 64 lowercase hex characters (the plan's confirm line)` | `confirm` got something else | Copy the digest from the plan's `confirm` line |
| `: make one with python -m kit tools plan ID ... --write FILE, or VC3D's Plan: entry`, `plans; give more of it` | No plan, or more than one, matches | Write a plan first, or give more of the digest, or `--plan FILE` |
| `manifest changed after the plan`, `changed since the plan` (exit 3) | The manifest, an input or a param changed after the plan | Make a new plan |
| `take KIND is one of` | Another kind | Use segment, ink_overlay, points, umbilicus or file |
| `no finished run under VC3D's plugin run folders; name one with --run` | `take` with no run and none found | Pass `--run RUN` |
| `has no vc3d-result.json: not a finished registry run`, `, so nothing is taken from it`, `: its format gate failed, so nothing is taken from it` | The run is not a finished, checked registry run | Take from a run whose status is ok |
| `), not something VC3D loads as` | The named output is another kind | Use the take entry for its kind |
| `is outside its run folder; refusing`, `changed after its run (sha256 differs); refusing` | The result names a file outside the run, or the file changed since | Do not load it; run the tool again |
| `is a PNG; VC3D's ink detection loader here takes a TIFF` | `take ink_overlay` of a PNG map | Use `take file`, or have the tool write a TIFF |
| `no command given after --`, `command must be an argument list` | `kit.localcost.run` got no command or not a list (a broken manifest or caller) | Correct the manifest's `run.argv` |
| `docs/tools/README.md has no generated block; refusing to overwrite its text` | `python -m kit.tooldocs index` (which also writes the facts blocks) found a hand-made index | Restore the two marker lines in `docs/tools/README.md` |

## How it works

1. **Load.** Manifests come from `kit/data/registry/*.json`, then each `KIT_TOOL_PATH` folder, then `~/.vc3d/tools/`; the first id wins, and a bad manifest, a file not named after its id or a repeated id is a problem, never a tool. `skip.json` lists tools with a page and no manifest, each with a reason; in public Scrolls `check` wants every current, runnable tool to have one or the other. Scrolls-private's `kit/data/registry/` holds only its private tools' manifests so far, so there that coverage rule is off and each manifest is still checked against its page. A manifest may belong to another tool's page (`"page": "ID"`): one page documents several entry points, such as the VC3D agent's tools, so each gets its own manifest, takes that page's facts and counts for it in the coverage rule, and its own `title` names the entry. A Network field that begins `None for` (or `None with`, `when`, `unless`, `except`) describes a tool that reads the network only when given a remote input, so it fits a manifest whose network is `none` and one whose inputs may be URLs (`public-read`).
2. **Bind.** The binder fills each input from the selection by its `from` (table under Inputs), checks it exists and has a listed format, and turns points, regions and canvas boxes into fields (`{in.crop.y0}`). Params take `--param`, the default, or the selection.
3. **Gate.** In order: native (refused), go-ahead (a page that needs a yes is refused), paid compute (`plan-only`, Modal or GPU is planned), local time (over 600 s on a Mac or 1800 s elsewhere is planned; AGENTS.md rule 11), disk (`disk_mb` plus a 1024 MB floor), writes outside, destructive, downloads, and the target rule (a scroll named in the inputs that the dated prize snapshot lists as eligible: refused in public Scrolls; in Scrolls-private it needs `--purpose target --experiment SLUG`, a ledger record whose readout is fixed, status planned or running, for that scroll).
4. **Run.** The run folder is `--out` (new or empty) or `work/tools/ID-DIGEST10`, where the digest covers the manifest, the inputs' paths, sizes and times, and the params; a finished identical run is returned as it is. The command runs through `kit.localcost.run` with the run folder as its working folder, `TMPDIR` inside it, `PYTHONPATH` set to the kit, and `KIT_ALLOW_MODAL` and `MODAL_*` removed.
5. **Audit.** Size, mtime and inode of every watched path (inputs, segment folders, project, umbilicus; up to 20,000 entries) before and after; any change, or an output that resolves outside the run folder, is a violation.
6. **Hand over.** Maps get 8-bit views on the forward map's scale, placed on the canvas for a crop; points become a VC3D point collection (version 1, villa `core/src/PointCollections.cpp`); each output kind's opener adds allow-listed calls (`segments.attach`, `segments.activate`, `volume.attach`, `volume.select`, `points.load_json`, `viewer.set_overlay`, `viewer.center_on_point`, `workspace.switch`). `points.load_json` is marked as replacing every point collection in that VC3D, so `open --live --apply` sends it only with `--replace-points`.
7. **Record.** `provenance.json` (`kit.provenance`; inputs over a 256 MB budget or remote are listed, not hashed), `graph.json`, then `vc3d-result.json`, atomically and last.

VC3D's plugin host (`vc3d-plugin/1`, villa `apps/VC3D/plugins/PluginManifest.cpp` on the vc3d-plugins lane, read 2026-10-20) reads every `*.json` in `~/.vc3d/plugins` and in each `VC3D_PLUGIN_PATH` folder. `export-vc3d` writes, for each tool with the vc3d door, an argument list that names one placeholder per selection kind its required inputs need (so VC3D refuses to start it and says what is missing), a plugin input for each required param (`auto` for a voxel size read from the volume), `--out {output}`, and the result VC3D loads: the manifest's `vc3d.result` when it is a report, page, point collection or umbilicus, else `vc3d-result.json`, where a forward map travels with its controls. The program is `bin/scrolls-tool`, a launcher that runs `python -m kit tools` from the checkout it sits in.

The AP door: `stage_choices` adds `reg:ID` to the ink stage for each `ink-command` manifest, and annotates an existing backend (`pipeline.existing`) with the manifest digest; `pipeline.existing` may name a param as `{param.NAME}`, and then every value of that param's enum is a backend the tool already is (AutoPipeline's ink script runs any of the stage's models); `ink_models` gives AP's ink command engine an in-memory registration whose command is `python -m kit tools exec ID --sha256 DIGEST16 -- {input} {output} {reverse}`. In `pair` mode the tool runs once per input (cached beside the output, so the shuffled control's other input runs it again) and `exec` copies the forward map for reverse 0 and the control for reverse 1; in `flag` mode the manifest's flag is added for reverse 1. Merging these into `kit/apbackends.py` is done in the kit that has it (Scrolls-private), through an extension.

Extensions: each `kit/toolreg_ext_*.py` beside the module is imported and its `register(module)` called, so a kit adds openers, run-folder handlers and stage checks without changing `kit/toolreg.py`, which stays the same in both repositories.

## Cost and time

The registry adds the gates, the audit and the handoff to a tool's own time: well under a second for small inputs (a synthetic rowscore run, 3.2 s wall in all, 1.0 s CPU, $0.000012 at 0.2 USD per kWh; measured 2026-10-20, cloud container). The audit walks at most 20,000 entries; hashing stops at 4 MB a file for the result and 256 MB in all for provenance. It rents nothing.

## For agents

- **Command:** `python -m kit tools list --json`, then `python -m kit tools plan ID [SELECTION] --json` and `python -m kit tools run ID [SELECTION] --out RUN --json`; for a gated tool, `plan ... --write PLAN.json` then `confirm DIGEST --plan PLAN.json`.
- **Parse:** the printed result (or `RUN/vc3d-result.json`): `status`, `exit`, `controls.verdict`, `outputs[].path`, `gates`, `warnings`; then the tool's own report under `outputs`, read as its page says.
- **Rerun:** safe: a finished identical run is returned as it is (`"reused": true`); `--fresh` makes a new folder; `--out` must be new or empty.
- **Success:** exit 0, `status` `ok`, `controls.verdict` `present` or `not applicable`, and no `format_gate` row with verdict `fail`.
- **Not a pass:** `controls.verdict` `no control: not a pass`; exit 4 (planned, nothing ran); a `target` gate of `warn` read as a check that the scroll is not eligible; a tool's own report that its page's Not a pass rule names.
- **Go-ahead:** Nothing to run it. Sending a result to someone, or opening it in another person's VC3D session, is outward and needs Chase's yes.
- **Never:** pass `--allow-outside` or `--yes-download` without reading what the manifest says it writes or fetches; edit a manifest's facts block by hand; open a result whose status is not ok; call an ink map a reading.

## Tests

`python -m unittest tests.test_toolreg tests.test_localcost -v` (about 15 s; the map tests skip without numpy and tifffile). They cover the repository's manifests and check, the manifest shape rules, doors, selection (flags and a stand-in bridge), binding (twin, labels, mask, params, a focus region turned into a canvas box), every gate including the target rule in public and private, the runner (ledger entry, working folder, `TMPDIR`, Modal variables removed, provenance and graph), a violation, failures, refusals, reuse, controls, shared-scale views, point collections and the allow-list, the AP door (`stage_choices`, `ink_models`, `exec` in pair mode with its digest pin), the committed plugin manifests parsed and run by `tests/fake_vc3d_host.py` through the launcher, the adapters (`AdapterTest`: inkfilter from VC3D whole and by focus region with its control taken back placed and on one scale, ink detection records pairing controls by model and naming labels, 8-bit maps kept as they are, region entries, the auc window, Ink Lens bound from a selection in local offline mode, `{param.NAME}` backends), and the command line. Not covered: a live VC3D window, a real AP run with a registry backend.

## History

- 2026-10-21: a manifest may name the tool page it belongs to (`page`), with its own `title`; a conditional Network field (`None for local inputs. ...`) fits `none` and `public-read` manifests ([branch claude/integration-1020](https://github.com/ChaseHendrick/Scrolls/tree/claude/integration-1020)).
- 2026-10-21: the format gate, convert steps, plan and confirm (`plan --write`, `confirm`), `take` and its five VC3D entries, "Plan:" and "Run planned:" entries, bridge-bound inputs read once from the parent VC3D's bridge (`--bridge-path`, found by the launcher's parent pid, never the newest bridge), the inkfilter manifest (an AP ink backend, `reg:inkfilter`), quota and `axis_order`; VC3D's own `plugin-run.json` no longer makes `--out` look busy ([branch claude/integration-1020](https://github.com/ChaseHendrick/Scrolls/tree/claude/integration-1020)).
- 2026-10-20: first version: the registry, `python -m kit tools`, eight public tool manifests and four of villa's tools, the VC3D plugin manifests and launcher in `integrations/vc3d/plugins/`, the AP door through `exec`, and `kit.localcost.run` with a working folder, environment, timeout and output files ([branch claude/integration-1020](https://github.com/ChaseHendrick/Scrolls/tree/claude/integration-1020)).

## Related

- [Use your tools from VC3D](../../integrations/vc3d/README.md): the guide for people, and the plugin folder.
- [tooldocs](tooldocs.md): the pages each manifest's facts come from; `python -m kit.tooldocs check` runs the registry check.
- [run-local](run-local.md): the cost wrapper every registry run goes through.
- [autopipeline](autopipeline.md): the pipeline whose stages registry tools fill.
- [auc](auc.md), [hpscore](hpscore.md), [rowscore](rowscore.md), [verify](verify.md), [overlap](overlap.md), [stackcheck](stackcheck.md), [view](view.md), [doctor](doctor.md), [umbilicus](umbilicus.md): some of the tools with manifests (`python -m kit tools list` lists them all).
- [provenance](provenance.md): the record every run writes.
