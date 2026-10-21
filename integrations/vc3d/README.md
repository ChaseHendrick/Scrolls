# AutoPipeline and VC3D, both ways

`ap_vc3d.py` links AutoPipeline (AP), the released package that runs villa's VC3D tools and ink detection on one scan, with VC3D, villa's viewer and editor. Pick a point in VC3D and plan an AutoPipeline run seeded there. Then open what the run accepted back in VC3D. It is one file, standard library only, and it works with the released AutoPipeline 0.1.5. People's guide: [`docs/autopipeline/guide.md`](../../docs/autopipeline/guide.md). Tool page: [`docs/tools/autopipeline-vc3d.md`](../../docs/tools/autopipeline-vc3d.md).

Every surface and map it moves is model output, not a reading.

## What works today, and what waits for villa

| Part | Needs | State |
| --- | --- | --- |
| `here`, `start`, `load` from a terminal | The AutoPipeline 0.1.5 environment (`scrolls-kit` on `PATH`, or `--kit`) | Works now |
| `here --bridge` and `open`: read the point from VC3D, attach results in VC3D | VC3D from villa `main` started with `--agent-bridge` (villa's agent bridge, `apps/VC3D/agent_bridge/SPEC.md`), Linux or macOS | Works with villa `main`; not yet run against a live VC3D window here (the tests use a stand-in bridge) |
| `manifests`: the four entries of a Plugins > AutoPipeline menu | VC3D's plugin host, part of the combined VC3D change Chase will post to villa | **Waits for villa.** VC3D on `main` has no Plugins menu; it ignores these files until that change is merged |
| Ink maps as VC3D overlays | VC3D needs the map on the segment's own grid; AutoPipeline's maps are on the render canvas | Not done. Open ink maps in an image viewer |

## Setup

```bash
# 1. AutoPipeline 0.1.5 in its own environment (see the guide for details)
git clone --depth 1 --branch submission/progress-2026-10-fix5 https://github.com/ChaseHendrick/Scrolls.git scrolls-autopipeline
cd scrolls-autopipeline/submissions/progress-2026-10-fix5/autopipeline
python3 -m venv .venv && . .venv/bin/activate && python -m pip install -e .
# 2. This script: one file from Scrolls main
mkdir -p ~/ap-vc3d && curl -fsSL -o ~/ap-vc3d/ap_vc3d.py \
  https://raw.githubusercontent.com/ChaseHendrick/Scrolls/main/integrations/vc3d/ap_vc3d.py
export AP_VC3D="python3 $HOME/ap-vc3d/ap_vc3d.py"
```

`ap_vc3d.py` finds `scrolls-kit` through `--kit PATH`, then `AP_KIT`, then `PATH`. It keeps its own small records in `~/.autopipeline-vc3d` (set `AP_VC3D_HOME` to move them): `last.json`, the plan made last, and `runs/`, each started run's log and process id.

## VC3D to AutoPipeline

Click on the papyrus in VC3D, read the focus point (x, y, z in full-resolution voxels), and plan a run seeded there:

```bash
$AP_VC3D here --point 3960,3700,9500 \
  --volume https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr/
```

```text
AutoPipeline plan made. Nothing was computed or launched.
Scan: PHerc0841, volume 20250821151531
Seed point (x,y,z, full-resolution voxels): 3960,3700,9500
Run folder: .../work/autopipe/PHerc0841-20250821151531-1a064eceed
Plan digest: 1a064eceed518d326dde681ad249f91f81655c3d8e3d9aa26207960917dce59c
```

With VC3D started as `VC3D --agent-bridge`, `$AP_VC3D here --bridge` reads the focus point and the open volume itself. The volume must be an open-data catalog scan (`.../SAMPLE/volumes/ID-....zarr`, as a URL or a local copy that keeps that layout), because AutoPipeline plans only catalog scans. Settings over AutoPipeline's defaults go in `--settings '{"trace": {"repeats": 2}}'`.

Then start exactly that plan. `start` checks the digest you saw, refuses if a run of it is already going, starts it in the background and returns:

```bash
$AP_VC3D start --run last --digest last
scrolls-kit autopipeline monitor RUN --open     # RUN is the run folder it printed
```

Nothing paid starts. Without a GPU environment for ink, the run stops at ink with a handoff file (`modal-job.json`).

## AutoPipeline to VC3D

```bash
$AP_VC3D load --run last --dest ~/ap-for-vc3d   # copies accepted surfaces to segments/, seeds to seeds.json
```

Then in VC3D: File > Attach Remote Zarr... with the volume URL it prints, File > Attach Segments... with `~/ap-for-vc3d/segments`, and Load in the Point Collections panel with `~/ap-for-vc3d/seeds.json`. Or let it do those steps in a running VC3D:

```bash
$AP_VC3D open --run last
```

`open` asks VC3D which bridge methods it has (`rpc.describe`) and calls only those: `volume.attach`, `segments.attach`, `points.load_json` and `viewer.center_on_point` on the first seed. Open or create a project in VC3D first. Only surfaces the run's rule accepted are copied, as tifxyz folders, so VC3D's own tools can edit, render or flatten them.

## The Plugins menu (after the combined VC3D change lands)

VC3D's plugin host, written for the combined VC3D change and not yet in villa, adds a **Plugins** menu that runs an outside program on what is open and loads what it writes back. A plugin is one JSON file in `~/.vc3d/plugins/` or a folder on `VC3D_PLUGIN_PATH`. VC3D shows the full command and asks before every run, passes arguments with no shell, and loads only files the run wrote into its own fresh folder.

```bash
$AP_VC3D manifests                                  # print the four manifests
$AP_VC3D manifests --install ~/.vc3d/plugins        # or any folder on VC3D_PLUGIN_PATH
```

| Menu entry | Runs | VC3D loads |
| --- | --- | --- |
| Plan an AutoPipeline run here | `here --point {point} --volume {volume}` | `plan.txt` (file) |
| Start the planned AutoPipeline run | `start --run last --digest last` | `started.txt` (file) |
| Load AutoPipeline surfaces | `load --need segments` | `segments/` (segment) |
| Load AutoPipeline seed points | `load --need seeds` | `seeds.json` (points) |

Each manifest has this machine's Python, this script and `scrolls-kit` written in as absolute paths, so run `manifests --install` again (with `--force`) after moving any of them. It refuses to replace a manifest that differs from what it would write unless you pass `--force`, so read an edited file first. Keep only manifests in a plugin folder: VC3D reads every `*.json` there.

### Add your own tool

Any program that takes arguments and writes a file can become a menu entry. A minimal manifest:

```json
{
  "schema": "vc3d-plugin/1",
  "id": "me.surface-report",
  "name": "Report on the active segment",
  "program": "/usr/bin/python3",
  "args": ["/home/me/tools/report.py", "{segment}", "--out", "{output}/report.txt"],
  "result": {"kind": "file", "path": "{output}/report.txt"}
}
```

Placeholders include `{volume}`, `{segment}`, `{point}`, `{region}`, `{ink_overlay}`, `{umbilicus}`, `{output}` and `{input:NAME}` for a value VC3D asks for. Result kinds are `none`, `file`, `segment` (a tifxyz folder), `ink_overlay` (an image on the segment's grid), `points` (a point collection file, as `seeds.json` here) and `umbilicus`. The full rules will be in villa's `docs/plugins.md` once the change is merged. Check a manifest without VC3D with the stand-in host in [`tests/vc3d_plugin_host.py`](../../tests/vc3d_plugin_host.py):

```bash
python3 -c "import sys; sys.path.insert(0, 'tests'); import vc3d_plugin_host as h; print(h.parse(open('MY.json').read(), 'MY.json')['id'])"
```

## Tests

```bash
python -m unittest tests.test_integrations_vc3d -v
VILLA_ROOT=PATH/TO/villa python -m unittest tests.test_integrations_vc3d.AgainstVilla   # a villa with the plugin host
```

They use a stand-in `scrolls-kit`, the stand-in plugin host and a stand-in VC3D bridge on a Unix socket, so they need neither VC3D nor AutoPipeline. They do not show that a real VC3D window accepts the calls or the manifests.
