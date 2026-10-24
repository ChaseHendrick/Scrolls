# Headless VC3D for agents

Version **1.1.1**. An MCP server and a shell command that let an AI agent (Claude Code, Codex, Claude Desktop, any MCP client, or a plain script) run villa's VC3D tools with no display: find public Vesuvius Challenge data, trace a surface, check it, render its surface volume, flatten and merge surfaces, run ink models with their controls, drive the VC3D app itself, look at every result as a PNG, and fit surfaces with villa's lasagna. It serves 46 tools with JSON schemas, progress, cancellation and images.

![A replay of a recorded agent session: tool calls appear one by one on the left with their arguments, real durations and results; on the right the segment's z coordinate, CT layers under it and a screenshot of the VC3D app.](https://raw.githubusercontent.com/ChaseHendrick/Scrolls/main/docs/assets/vc3d-agent/vc3d-agent-session.gif)

*A recorded session, replayed: 12 of the MCP calls an agent client made to this server on Hugging Face CPU Jobs on 24 October 2026, on PHerc0139 segment w035 at 9.362 µm. Every value shown is read from the session transcripts; waits are cut and the real durations are printed. Real data render: CT and mesh geometry, no labels, no ink. Vesuvius Challenge open data, CC BY-NC 4.0. [MP4 version](https://raw.githubusercontent.com/ChaseHendrick/Scrolls/main/docs/assets/vc3d-agent/vc3d-agent-session.mp4).*

It does not replace villa or VC3D. It calls their command line tools (`vc_grow_seg_from_seed`, `vc_render_tifxyz`, `vc_flatten`, `vc_tifxyz_selfcross` and the rest) and, through the `app_*` tools, the VC3D app's agent bridge, then checks what they return. The same server first shipped inside [AutoPipeline](https://github.com/ChaseHendrick/Scrolls#released-tools); this package is the server on its own, without AutoPipeline's pipeline tools (`umbilicus`, `seeds`, `distortion`, `autopipeline`).

**What 1.1.1 changes:** this README only. It now shows every tool with a real call and its result, how to connect Claude Code, Codex and other clients, the recorded session, and the failure modes we met. The code is 1.1.0's, byte for byte.

## Contents

- [Why](#why)
- [Quick start](#quick-start)
- [Connect an agent](#connect-an-agent): Claude Code, Codex, any MCP client, Python, a shell
- [A recorded session](#a-recorded-session)
- [Every tool, with a real call](#every-tool-with-a-real-call)
- [Failure modes](#failure-modes)
- [Limits](#limits)
- [Rules built in](#rules-built-in), [Tests](#tests), [License and credits](#license-and-credits)

## Why

Agents are good at calling tools and bad at knowing VC3D's conventions: which way the layers stack, which scan frame a segment is in, whether a blank render means a missing chunk. Each of those fails silently. These tools build the checks in: `render` votes on the surface normal before it trusts `--flip-normals`, `audit` finds chunks a render would read as zeros, `check_surface` asks whether the surface sits on a papyrus sheet, `landmarks` checks the affine between two scans, and `ink` always makes the reverse-depth control beside the forward map. Every result is JSON an agent can read, with the paths of what was written and a receipt.

## Quick start

Python 3.11 or newer (tested on 3.11 and 3.13). The server and most tools use only the standard library.

```bash
git clone --branch submission/progress-2026-10-vc3d-agent-1-1-1 --depth 1 https://github.com/ChaseHendrick/Scrolls.git scrolls-vc3d-agent
cd scrolls-vc3d-agent/submissions/progress-2026-10-vc3d-agent-1-1-1/vc3d-agent
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[maps]"      # the maps extra (numpy, tifffile, zarr 3, scipy) is for scoring and layer tools
export VC_APPIMAGE="$(python scripts/get_vc3d.py)"   # villa's current Linux AppImage, sha256 checked; prints its path
vc3d-agent vc3d call status
vc3d-agent vc3d call selftest
```

On macOS, or with your own villa build, set `VC_BIN` to the folder that holds `vc_render_tifxyz` instead of `VC_APPIMAGE`. `docs/vc3d-headless.md` says where to get the tools. `vc3d-agent` and `python -m kit` are the same command.

A first session from the shell, on public data. In the recording these calls took about 70 s of tool time on 8 CPU cores, most of it in `check_surface`:

```bash
SEG=$(vc3d-agent vc3d call fetch_segment '{"sample": "PHerc0139", "segment": "w035", "frame": "20250728140407"}' \
      | python3 -c 'import json, sys; print(json.load(sys.stdin)["surface"])')
VOL=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr/
vc3d-agent vc3d call inspect "{\"path\": \"$SEG\", \"voxel_um\": 9.362}"
vc3d-agent vc3d call check_surface "{\"surface\": \"$SEG\", \"volume\": \"$VOL\", \"windows\": 5, \"voxel_um\": 9.362}"
RENDER=$(vc3d-agent vc3d call render "{\"surface\": \"$SEG\", \"volume\": \"$VOL\", \"preset\": \"9um\", \"crop\": [2600, 2300, 640, 640]}" \
      | python3 -c 'import json, sys; print(json.load(sys.stdin)["zarr"])')
vc3d-agent vc3d call preview "{\"path\": \"$RENDER\", \"mode\": \"max\"}"
```

`call` prints the result as JSON and exits 0 when the tool succeeded, 1 when it ran and failed, and 2 on bad arguments or a refusal. Outputs go under `work/` of the kit home: this folder, or `KIT_HOME` if you set it.

## Connect an agent

The server speaks newline-delimited JSON-RPC 2.0 on stdio, MCP protocol versions 2024-11-05 to 2025-11-25, and offers the two guides and `AGENTS.md` as resources. Give the client the full path of `.venv/bin/vc3d-agent` with the arguments `vc3d mcp`, and pass `VC_APPIMAGE` (or `VC_BIN`) in its environment. Then ask the agent to call `status` first and `guide` for the workflow.

### Claude Code

Run in the package folder, with the venv active:

```bash
claude mcp add vc3d-agent -e VC_APPIMAGE="$VC_APPIMAGE" -- "$PWD/.venv/bin/vc3d-agent" vc3d mcp
claude mcp list        # lists vc3d-agent as connected
```

Checked on 24 October 2026: `claude mcp list` reported the server connected.

### Codex

```bash
codex mcp add vc3d-agent --env VC_APPIMAGE="$VC_APPIMAGE" -- "$PWD/.venv/bin/vc3d-agent" vc3d mcp
codex mcp list
```

That writes this to `~/.codex/config.toml`, which you can also edit by hand:

```toml
[mcp_servers.vc3d-agent]
command = "/path/to/vc3d-agent/.venv/bin/vc3d-agent"
args = ["vc3d", "mcp"]

[mcp_servers.vc3d-agent.env]
VC_APPIMAGE = "/path/to/VC3D.AppImage"
```

Checked on 24 October 2026 with Codex CLI 0.164.0: `codex mcp add` wrote that table and `codex mcp list` showed the server enabled. A Codex session itself was not run (it needs a signed-in account).

### Any other MCP client

Claude Desktop, Cursor and most other clients take a JSON entry like this one:

```json
{"mcpServers": {"vc3d-agent": {"command": "/path/to/vc3d-agent/.venv/bin/vc3d-agent", "args": ["vc3d", "mcp"],
  "env": {"VC_APPIMAGE": "/path/to/VC3D.AppImage"}}}}
```

Without the installed script, use `"command": "python3", "args": ["-m", "kit", "vc3d", "mcp"]` and add `"PYTHONPATH": "/path/to/vc3d-agent"` to `env`.

### From Python, with the official MCP SDK

```python
import asyncio, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server = StdioServerParameters(command=sys.argv[1], args=["vc3d", "mcp"], env=dict(os.environ))

async def main():
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(len(tools.tools), "tools")
            result = await session.call_tool("inspect", {"path": sys.argv[2], "voxel_um": 9.362})
            print(result.structured_content["area_cm2"], result.structured_content["render_px_at_scale_1"])

asyncio.run(main())
```

`python client.py .venv/bin/vc3d-agent "$SEG"` printed `46 tools` and `21.9692 [5820, 5240]` with MCP SDK 2.3.0 on 24 October 2026. Older 1.x SDKs name the field `structuredContent`.

### From a shell, or any language

```bash
vc3d-agent vc3d tools                       # one line per tool; --json gives the argument schemas
vc3d-agent vc3d call TOOL '{"key": "value"}'
vc3d-agent vc3d call TOOL @args.json        # arguments from a file
vc3d-agent vc3d call render @args.json --background   # then: vc3d-agent vc3d call jobs '{"action": "wait", "id": "JOB"}'
```

## A recorded session

On 24 October 2026 a small MCP client (stdio, protocol 2025-06-18) drove this server through 69 calls in four Hugging Face CPU Jobs (8 vCPU, no GPU), in a Linux container with villa's VC3D build (the app reports version `e0bbb8b-2026-10-06`). The server was the 1.0.0 package, whose 39 tools are unchanged in 1.1.x: 1.1.0 only added the seven `lasagna_*` tools. Everything ran on PHerc0139, a public scan on no prize list, with segment w035 in the 9.362 µm frame (volume `20250728140407`). The client saved each call's arguments, wall time and full result; the examples in this README and the replay above are read from those transcripts.

What the agent found, in order:

1. `status` found every VC3D tool it needs, and `selftest` passed 8 of 8 checks of the conventions the other tools rely on, in 4.8 s.
2. `fetch_segment` downloaded w035 (4 files, 915,721 bytes) in 1.1 s; `inspect` measured 21.97 cm² on a 291 by 262 grid.
3. `orientation` found the normal points outward on 99.99% of the voting area, so the team layer order is `--flip-normals`.
4. `audit` checked the 4,776 chunks under and around the surface (4,793 requests in 241 s): none missing, verdict `clean`.
5. `check_surface` found the surface seated on a sheet in 5 of 5 windows, with no self-crossings: verdict `ok`.
6. `trace` grew a new 2.09 cm² surface from a random seed on the published recto surface prediction in 28 s. Its result warned that no normal grids were given, so the tracer did not read the scan; `check_surface` then found it seated in 0 of 3 windows and said `look closer`. The checks caught a surface that should not be rendered. (A surface grown from a model's prediction is model output, so it appears here as numbers only.)
7. `render` made a 28-layer surface volume of a 640 px window of w035 in 11.9 s, and `preview` returned PNGs of its middle layer and its maximum:

![Three panels: the segment's z coordinate as a gray ramp inside its outline; the middle layer of a 28-layer render of the CT under a 640 pixel window of the segment; and the maximum over those 28 layers, a mesh of crossing fibers.](https://raw.githubusercontent.com/ChaseHendrick/Scrolls/main/docs/assets/vc3d-agent/vc3d-agent-render.png)

*Left: `preview` of w035's z coordinate. Middle and right: `preview` of the render's layer 14 of 28 and of its maximum over all layers. Real data render: CT and mesh geometry, no labels, no ink. Vesuvius Challenge open data, CC BY-NC 4.0.*

8. `flatten`, `trim`, `merge_patch` and `merge_surfaces` ran villa's tools on w035 and on halves the client cut from it; the two halves merged back with an overlap shift of 0.0 voxels.
9. `app_start` launched the VC3D app offscreen on a project naming the remote scan, `app_open` attached w035, and `app_screenshot` captured the window over the agent bridge:

![A screenshot of the VC3D app taken over its agent bridge with no display: the CT along segment w035 on the left, the scroll's cross-section and a vertical slice on the right.](https://raw.githubusercontent.com/ChaseHendrick/Scrolls/main/docs/assets/vc3d-agent/vc3d-agent-app.png)

*VC3D running offscreen, captured with `app_screenshot`: the CT along w035 in the left view, the scan from above and a vertical slice on the right. Real data render: CT, no labels, no ink. Vesuvius Challenge open data, CC BY-NC 4.0.*

10. `ink` ran the released `ink_9um` model (seed 42) on the 640 px render on CPU and did not finish its three variants within its 2,400 s timeout: no maps came back. Ink needs a GPU for anything but small windows; see [Failure modes](#failure-modes).

The replay and the stills are made from the transcripts by `scripts/media/vc3d_agent_session.py` in the [Scrolls repository](https://github.com/ChaseHendrick/Scrolls/blob/main/docs/tools/media.md).

## Every tool, with a real call

Each block below is one call from the recorded session: the tool and its arguments on the first line, then the client's wall time, then the result. Results are trimmed to the keys the text talks about; long lists keep their first items and say how many more there were. In a shell, pass the same arguments to `vc3d-agent vc3d call TOOL`. The lasagna examples come from separate runs of the 1.1.0 package, described under [Lasagna](#lasagna).

Paths and URLs are shortened with these names:

| Name | Stands for |
| --- | --- |
| `$D` | `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139` |
| `$VOL` | `$D/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr/`, the 9.362 µm scan |
| `$PRED` | `$D/representations/predictions/surfaces/20250728140407-surface-20250701154204-surface-recto-090.zarr/`, the published recto surface prediction for that scan |
| `$SEG` | the w035 surface that `fetch_segment` returned |
| `$TRACE` | the surface that `trace` grew |
| `$RENDER` | the `layers.zarr` that `render` wrote |
| `$OUT` | the client's own folder: the project file and the cut halves of w035 |
| `$KIT_HOME`, `$VC_BIN` | the kit home, and the folder that holds VC3D's tools |

| Group | Tools |
| --- | --- |
| [Setup](#setup) | `status`, `selftest`, `list_tools`, `tool_help`, `guide` |
| [Open data](#open-data) | `catalog`, `fetch_segment`, `landmarks`, `models`, `fetch_model` |
| [VC3D tools](#vc3d-tools) | `run`, `trace`, `extend`, `render`, `flatten`, `trim`, `merge_patch`, `merge_surfaces`, `volume_meta` |
| [Checks](#checks) | `inspect`, `check_surface`, `orientation`, `frame`, `audit`, `cache_check`, `seed_check`, `phantoms` |
| [Ink](#ink) | `ink` (forward and reverse-depth control always; depth-shuffled control on request), `detectability` (planted strokes of known contrast) |
| [Looking](#looking) | `preview` (a PNG returned as an image) |
| [The VC3D app](#the-vc3d-app) | `app_start`, `app_open`, `app_methods`, `app_call`, `app_screenshot`, `app_stop` |
| [Lasagna](#lasagna) | `lasagna_status`, `lasagna_configs`, `lasagna_manifest`, `lasagna_fit`, `lasagna_export`, `lasagna_selftest`, `lasagna_service` |
| [Other](#other) | `jobs`, `kit`, `modal` |

### Setup

`status` says which VC3D tools it found, what the renderer supports, which Python runs the ink models and what is running. Call it first.

```jsonc
// status {}
// result in 0.28 s
{
  "server": "kit-vc3d 1",
  "display": "none needed (QT_QPA_PLATFORM=offscreen)",
  "tools": "VC_BIN: $VC_BIN (started directly)",
  "has": {
    "vc_gen_umbilicus": true,
    "vc_grow_seg_from_seed": true,
    "vc_tifxyz_selfcross": true,
    "vc_flatten": true,
    "vc_render_tifxyz": true,
    "VC3D": true
  },
  "renderer": {
    "starts": true,
    "flip_normals": true,
    "zarr_compressor": true,
    "surface_interpolation": true,
    "remote_url": true,
    "volume_url": false
  },
  "modal_allowed": false,
  "last_selftest": "never run on this build: call selftest",
  "ink_python": {"python": "/usr/bin/python3", "version": "3.12.3", "numpy": true, "torch": false}
}
```

`selftest` renders and traces tiny synthetic volumes through the real `vc_render_tifxyz` and `vc_grow_seg_from_seed` and checks the conventions the other tools rely on: layer order, what `--flip-normals` does, sampling, pixel origin, and that a trace follows normal grids. Run it on every new machine or VC3D build.

```jsonc
// selftest {}
// result in 4.84 s
{
  "checks": [
    "render_starts: pass",
    "render_default: pass",
    "render_flip_normals: pass",
    "flip_reverses: pass",
    "flip_equals_reversed_stack: pass",
    "render_trilinear: pass",
    "render_registration: pass",
    "trace_follows_grids: pass"
  ],
  "default_order": "+N",
  "flip_normals": "supported",
  "conventions": {
    "default_order": "+N",
    "sampling": "trilinear",
    "pixel_origin": 0.5,
    "edge_loss_cells": 0.5,
    "edge_loss_bracket": [0.4375, 0.5625]
  },
  "trace": {"verdict": "PASS"},
  "verdict": "PASS"
}
```

`list_tools` lists every program in the VC3D build with its one-line summary (48 in this build); `tool_help` returns one program's `--help`.

```jsonc
// list_tools {}
// result in 23.80 s
{
  "bindir": "$VC_BIN",
  "tools": [
    {"tool": "VC3D", "summary": "the VC3D app; drive it with app_start and app_call"},
    {"tool": "vc_add_ignore_label", "summary": "vc_add_ignore_label: add ignore label to rasterized OME-Zarr"},
    "... 46 more"
  ]
}
```

```jsonc
// tool_help {"tool": "vc_tifxyz_selfcross"}
// result in 0.14 s
{
  "tool": "vc_tifxyz_selfcross",
  "exit": 0,
  "help": "Census a tifxyz surface for non-adjacent transverse self-intersections.\nReport-only: nothing is modified:\n... 21 more lines"
}
```

`guide` returns the workflow guide, or one of its 16 topics.

```jsonc
// guide {}
// result in 0.00 s
{
  "topics": [
    "Setting up",
    "Workflow",
    "Rules the tools enforce",
    "Rendering conventions",
    "Tracing",
    "Checking a surface",
    "Normal orientation",
    "Zarr integrity",
    "False 404s and VC3D's chunk cache",
    "Cross-scan transforms and their landmarks",
    "Ink detection",
    "Detectability",
    "Background jobs",
    "The VC3D app",
    "Troubleshooting",
    "Measured on public data"
  ]
}
```

```jsonc
// guide {"topic": "Normal orientation"}
// result in 0.00 s
{
  "topic": "Normal orientation",
  "text": "## Normal orientation\n\n`orientation` says which way a surface's normal points. VC3D stacks layers along N = dP/dcol x dP/drow. villa's standard segments (rows along +z, columns turning around the axis) have N pointing out of the scroll, which is why `--flip-normals` gives the team order. A grid with its rows or columns the other way, or transposed, has N pointing in, and the same flag then stacks its layers away from ..."
}
```

### Open data

`catalog` reads the open-data catalog: `samples`, a sample's `volumes` (with their surface predictions, normal grids and umbilicus files), its `segments`, one `segment` in full, the `transforms` between its volumes, and `models`.

```jsonc
// catalog {"action": "segment", "sample": "PHerc0139", "segment": "w035"}
// result in 0.48 s
{
  "segment": "20260317000000",
  "long_id": "20260317000000-w035_2026031718",
  "size_px": [6219, 8819],
  "original_volume": "20260102150214",
  "frames": ["20250728140407", "20250820105138", "20260102150214", "20260319133554", "20260413113053"],
  "surface_volumes": ["20250728140407", "20260102150214", "20260413113053"],
  "ink_maps": 2,
  "data": [
    {
      "type": "tifxyz",
      "url": "$D/segments/20260317000000-w035_2026031718/mesh/intermediate/tifxyz_original/"
    },
    "... 18 more"
  ]
}
```

```jsonc
// catalog {"action": "volumes", "sample": "PHerc0139"}
// result in 0.26 s
{
  "sample": "PHerc0139",
  "volumes": [
    {
      "volume": "20250728140407",
      "voxel_um": 9.362,
      "shape_zyx": [20974, 6621, 6621],
      "energy_keV": 113.0,
      "license": "CC BY-NC 4.0",
      "surface_prediction_zarr": 2,
      "normal_grids": 1
    },
    {
      "volume": "20250820105138",
      "voxel_um": 2.403,
      "shape_zyx": [19393, 26105, 26105],
      "energy_keV": 77.0,
      "license": "CC BY-NC 4.0"
    },
    {
      "volume": "20250822062710",
      "voxel_um": 2.403,
      "shape_zyx": [15137, 26061, 26061],
      "energy_keV": 77.0,
      "license": "CC BY-NC 4.0"
    },
    "... 7 more"
  ]
}
```

`fetch_segment` downloads a published segment in the frame you name and returns its local path and grid statistics.

```jsonc
// fetch_segment {"sample": "PHerc0139", "segment": "w035", "frame": "20250728140407"}
// result in 1.14 s
{
  "surface": "$SEG",
  "objects": 4,
  "bytes": 915721,
  "source": "$D/segments/20260317000000-w035_2026031718/mesh/20260317000000-on-20250728140407-9.362um.tifxyz/",
  "stats": {
    "grid_rows_cols": [291, 262],
    "valid_fraction": 0.8329,
    "edge_voxels": {"median": 19.992, "p95": 20.282, "max": 22.15},
    "long_edges": 0,
    "render_px_at_scale_1": [5820, 5240]
  }
}
```

`landmarks` checks the catalog's affine matrices between two scans of a sample against the landmark pairs they were fitted to, carries the surface's points across, and says how far each mapping moves when one landmark is left out. A wrong matrix puts a surface beside its sheet with no error.

```jsonc
// landmarks {"sample": "PHerc0139", "from_volume": "20250728140407", "to_volume": "20260102150214", "surface": "$SEG"}
// result in 0.29 s
{
  "from": "20250728140407",
  "to": "20260102150214",
  "tolerance_um": 75.0,
  "hops": [
    {
      "landmarks": 14,
      "points": 323,
      "jackknife_affine_median_um": 14.85,
      "jackknife_affine_max_um": 20.41,
      "inside_landmark_box_share": 0.464
    }
  ],
  "points": 323,
  "rows": [
    {
      "point": [2896.13, 2448.11, 3075.43],
      "mapped": [14178.23, 17006.3, 9470.66],
      "jackknife_affine_um": 11.13,
      "inside_target_volume": true
    },
    "... 49 more"
  ],
  "report": "$KIT_HOME/work/vc3d/checks/landmarks-20261024-055347/landmarks.json"
}
```

`models` lists, adds and removes the ink models the `ink` tool may load; `action: known` lists the ones `fetch_model` can download. `fetch_model` downloads one from Hugging Face or a GitHub release into `checkpoints/`, checks pinned files against their sha256, and registers it.

```jsonc
// models {"action": "known"}
// result in 0.00 s
{
  "known": {
    "ink_9um-seed42": "scrollprize/ink_9um",
    "ink_9um-seed43": "scrollprize/ink_9um",
    "reader-v2": "domenicor046/reader-v2",
    "d9v2": "TAUIL-Abd-Elilah/pherc0826-first-letters-search",
    "v8in": "YoussefMoNader/ink-8um-v8in"
  }
}
```

```jsonc
// fetch_model {"name": "ink_9um-seed42"}
// result in 1.66 s
{
  "model": "ink_9um-seed42",
  "repo": "scrollprize/ink_9um",
  "files": [
    {
      "path": "hybrid_3d2d-seed42/step-075000.pth",
      "bytes": 138360039,
      "sha256": "e635558ae6a1a807a7e5ec1e83adfd45bc3c0ac53883ea43f1d4e085d62a9cab",
      "sha256_checked": true
    }
  ],
  "checkpoint": "$KIT_HOME/checkpoints/ink_9um-seed42/hybrid_3d2d-seed42/step-075000.pth"
}
```

### VC3D tools

`run` starts any `vc_*` program of the build with no display and capped thread pools, passing your arguments through (S3 URLs among them go through the false-404 relay), and returns its exit code and log. Here `vc_tifxyz_selfcross` exited 1 and printed its usage; `check_surface` runs the same census for you with the right options.

```jsonc
// run {"tool": "vc_tifxyz_selfcross", "args": ["--surface", "$SEG"]}
// error result in 0.45 s
{
  "tool": "vc_tifxyz_selfcross",
  "exit": 1,
  "seconds": 0.4,
  "log": "$KIT_HOME/work/vc3d/runs/20261024-060308-vc_tifxyz_selfcross.log",
  "log_tail": "$ $VC_BIN/vc_tifxyz_selfcross --surface $SEG\nCensus a tifxyz surface for non-adjacent transverse self-intersections.\nReport-only: nothing is modified:\n... 21 more lines"
}
```

`trace` grows a surface with `vc_grow_seg_from_seed` from a seed (or a random one) on a surface prediction, reports how and why it stopped, and counts the chunks it asked for. Read `data_term`: here no normal grids were given, so the tracer only extrapolated the seed. The catalog lists normal grids for this scan (`catalog` above); pass them as `normal_grids`.

```jsonc
// trace {"volume": "$PRED", "voxel_um": 9.362, "generations": 40, "threads": 4, "params": {"min_area_cm": 0}, "name": "demo-trace", "timeout": 1500}
// result in 28.28 s
{
  "exit": 0,
  "seconds": 28.2,
  "mode": "seed",
  "surfaces": [
    {
      "path": "$TRACE",
      "grid_rows_cols": [82, 82],
      "valid_fraction": 0.9048,
      "area_cm2": 2.0924,
      "seed": [4127.97412109375, 3463.554931640625, 10834.34375]
    }
  ],
  "stop": {"reason": "generations", "generations_planned": 40, "generations_done": 39},
  "relay": {"requests": 60, "missing": 28, "false_404": 0, "network_errors": 0},
  "data_term": "none: no normal grids, so no loss of the tracer read the scan and the surface is the seed extrapolated by smoothness; give normal_grids"
}
```

`extend` grows an existing surface from its edge with `vc_extend_edge`, which villa's release does not ship yet:

```jsonc
// extend {"surface": "$SEG", "normals": "$PRED"}
// refused in 0.00 s
{
  "error": "vc_extend_edge is not in $VC_BIN (build it from the VC3D fork branch vc3d-auto-extend; villa's release does not have it yet)"
}
```

`render` makes a surface volume with `vc_render_tifxyz`, in the team layer order unless you say otherwise, through a local relay that tells a missing chunk from a false 404. `crop` is x, y, width, height in surface pixels.

```jsonc
// render {"surface": "$SEG", "volume": "$VOL", "preset": "9um", "crop": [2600, 2300, 640, 640]}
// result in 12.38 s
{
  "exit": 0,
  "seconds": 11.9,
  "attempts": 1,
  "order": "team (--flip-normals)",
  "zarr": "$RENDER",
  "shape": [28, 640, 640],
  "levels": 6,
  "relay": {"requests": 121, "missing": 19, "false_404": 0, "network_errors": 0},
  "orientation": {"checked": false, "why": "no umbilicus given and none in the catalog for this volume"},
  "receipt": "$KIT_HOME/work/vc3d/renders/7000000-w035_2026031718-on-20250728140407.tifxyz-20261024-055358/receipt.json"
}
```

`flatten` flattens a surface with `vc_flatten` (ABF++ or LSCM) into a new tifxyz you can render like any surface. The flattened w035 has 40 long edges (`long_edges`), where the original has none.

```jsonc
// flatten {"surface": "$SEG", "downsample": 2}
// result in 9.43 s
{
  "exit": 0,
  "seconds": 8.9,
  "out": "$KIT_HOME/work/vc3d/flat/7000000-w035_2026031718-on-20250728140407.tifxyz-20261024-055504",
  "surface": {
    "grid_rows_cols": [254, 287],
    "valid_fraction": 0.8621,
    "edge_voxels": {"median": 20.003, "p95": 20.521, "max": 118.759},
    "long_edges": 40
  }
}
```

`trim` copies a surface with every vertex over CT value 0 (outside the scan or its mask) made invalid, then crops the copy; the original never changes. A render over zeros is blank whatever the ink, so trim before ink. No vertex of w035 was over zero at level 3.

```jsonc
// trim {"surface": "$SEG", "ct": "$VOL", "level": 3}
// result in 2.05 s
{
  "level": 3,
  "valid_vertices": 63503,
  "trimmed_vertices": 0,
  "kept_vertices": 63503,
  "missing_chunks": 0,
  "out": "$KIT_HOME/work/vc3d/trims/7000000-w035_2026031718-on-20250728140407.tifxyz-20261024-055502/20260317000000-w035_2026031718-on-20250728140407.tifxyz"
}
```

`merge_patch` grafts a child surface into its parent with `vc_merge_patch`; `merge_surfaces` joins a grid of surfaces into one with `vc_merge_tifxyz`. The child here is a 62 by 62 piece the client cut from w035, and the two halves overlap by about 5,400 vertices, so both merges should land where they started: `merge_patch` matched all 1,133 anchors with zero residual, and `merge_surfaces` reported an overlap shift of 0.0 voxels.

```jsonc
// merge_patch {"parent": "$SEG", "child": "$OUT/cut/w035-child.tifxyz", "border_cells": 8}
// result in 4.36 s
{
  "exit": 0,
  "seconds": 3.2,
  "log_tail": "RANSAC inliers=1133/1133  thresh=5.00  sigma_in=0.00  scale=1.0000  t=[99.00, 114.00]\nfootprint_cells=3600  replaced=2500  blended=1100  parent_filled_invalid=0  no_child_neighbor=0",
  "surface": {
    "grid_rows_cols": [291, 262],
    "valid_vertices": 63503,
    "edge_voxels": {"median": 19.989, "p95": 20.338, "max": 29.599}
  }
}
```

```jsonc
// merge_surfaces {"rows": [["$OUT/cut/w035-half-a.tifxyz", "$OUT/cut/w035-half-b.tifxyz"]]}
// result in 50.66 s
{
  "exit": 0,
  "seconds": 50.1,
  "grid": [["w035-half-a.tifxyz", "w035-half-b.tifxyz"]],
  "log_tail": "w035-half-a.tifxyz overlap shift (vox): p50=0.0  p95=0.0  max=0.0  (cells=4909)\nw035-half-b.tifxyz overlap shift (vox): p50=0.0  p95=0.0  max=0.0  (cells=4908)\ntotal: 69013 verts, 136296 tris",
  "surfaces": [
    {
      "grid_rows_cols": [286, 259],
      "valid_vertices": 62826,
      "edge_voxels": {"median": 20.02, "p95": 20.294, "max": 22.017},
      "long_edges": 0
    }
  ]
}
```

`volume_meta` writes the `meta.json` VC3D reads next to a local zarr (a render, say) that has none; without it VC3D assumes voxel size 0. An existing one is never changed.

```jsonc
// volume_meta {"volume": "$KIT_HOME/work/vc3d/renders/7000000-w035_2026031718-on-20250728140407.tifxyz-20261024-060309/layers.zarr", "voxel_um": 9.362, "name": "w035-crop"}
// result in 0.00 s
{
  "written": true,
  "meta": {
    "uuid": "92f0158e-9776-5755-9a4c-e180b8d04e0f",
    "name": "w035-crop",
    "type": "vol",
    "format": "zarr",
    "width": 256,
    "height": 256,
    "slices": 28,
    "voxelsize": 9.362,
    "min": 0.0,
    "max": 255.0
  }
}
```

### Checks

`inspect` describes a tifxyz surface (grid, valid fraction, extent, edge lengths, area, render size), a zarr, a layer folder, a TIFF, an .npy or a receipt.

```jsonc
// inspect {"path": "$SEG", "voxel_um": 9.362}
// result in 0.50 s
{
  "kind": "tifxyz",
  "grid_rows_cols": [291, 262],
  "valid_fraction": 0.8329,
  "bbox_xyz": [[1792.05, 2288.9, 2843.08], [4419.92, 4572.05, 8061.26]],
  "edge_voxels": {"median": 19.992, "p95": 20.282, "max": 22.15},
  "long_edges": 0,
  "voxel_um": 9.362,
  "area_cm2": 21.9692,
  "render_px_at_scale_1": [5820, 5240]
}
```

`check_surface` asks whether a surface can be trusted: grid sanity, a self-crossing census (`vc_tifxyz_selfcross`), the normal's sign against the umbilicus when one is known, and a seating score in several windows, where the center layer of a short rendered stack must be brighter than the layers a gap away on both sides. Compare the published w035 with the new trace:

```jsonc
// check_surface {"surface": "$SEG", "volume": "$VOL", "windows": 5, "voxel_um": 9.362}
// result in 52.00 s
{
  "selfcross": {"clean": true, "transverse": 0},
  "orientation": {"checked": false, "why": "no umbilicus given and none in the catalog for this volume"},
  "seating": {
    "verdict": "seated",
    "score": 29.1,
    "contrast": 41.21,
    "coverage": 0.7062,
    "seated_windows": "5 of 5",
    "thresholds": {
      "seated_contrast": 10.0,
      "unseated_contrast": 3.0,
      "note": "an interpretation; compare frames rather than trusting one number"
    }
  },
  "findings": [],
  "verdict": "ok"
}
```

```jsonc
// check_surface {"surface": "$TRACE", "volume": "$VOL", "windows": 3, "voxel_um": 9.362}
// result in 30.71 s
{
  "selfcross": {"clean": true, "transverse": 0},
  "seating": {"verdict": "unclear", "score": 3.11, "contrast": 3.39, "coverage": 0.9179, "seated_windows": "0 of 3"},
  "findings": ["seating: unclear (0 of 3 windows seated)"],
  "verdict": "look closer"
}
```

`orientation` votes on which way the surface normal points and says which layer order that gives. With no umbilicus it fits a circle to the surface, and says the fit is unreliable.

```jsonc
// orientation {"surface": "$SEG", "volume": "$VOL"}
// result in 1.38 s
{
  "fit": {"centre_xy": [3181.7, 3522.9], "radius": 986.2, "arc_degrees": 289.9, "reliable": false},
  "normal": {"outward_share": 0.9999, "vote": "outward", "confidence": "clear"},
  "team_order": "--flip-normals",
  "advice": "+N points outward on 100% of the voting area, so layers grow toward the centre with --flip-normals",
  "layout": "villa's standard orientation (rows along +z, +N outward)",
  "folds": {"neighbour_pairs": 126411, "flipped_pairs": 0}
}
```

`frame` asks which scan frame a surface belongs to, by trying it in every volume of the sample through the catalog's matrices and scoring how well it seats in each. For w035 the best frame was the same scan's other reconstruction, with the identity matrix:

```jsonc
// frame {"surface": "$SEG", "catalog_from": "20250728140407", "scales": [1, 0.5], "points": 600}
// result in 67.83 s
{
  "best": {
    "label": "20250728140407 -> 20251107135911 (catalog matrix)",
    "verdict": "seated",
    "score": 97.0,
    "relative_score": 1.9478,
    "voxel_um": 9.362
  },
  "clear": true,
  "why": "best 1.9478 against runner-up 0.3513",
  "candidates": [
    "20250728140407 -> 20251107135911 (catalog matrix): relative 1.9478",
    "20250728140407 -> 20260413113053 (catalog matrix): relative 0.3513",
    "20250728140407 -> 20260102150214 (catalog matrix): relative 0.318",
    "20250728140407 -> 20260930100252 (catalog matrix): relative 0.318",
    "... 7 more"
  ]
}
```

`audit` checks a remote zarr and the chunks a surface will read: headers, pyramid levels and every chunk under and around the surface.

```jsonc
// audit {"volume": "$VOL", "surface": "$SEG", "max_requests": 6000}
// result in 240.89 s
{
  "store": "remote",
  "levels": 6,
  "footprint": [
    {
      "level": "0",
      "chunks_on_surface": 2577,
      "chunks_in_margin": 2199,
      "present": 4776,
      "missing_on_surface": 0,
      "missing_in_margin": 0,
      "unknown": 0
    }
  ],
  "requests": 4793,
  "defects": [],
  "warnings": [],
  "verdict": "clean",
  "report": "$KIT_HOME/work/vc3d/audits/20250728140407-9.362um-1.2m-113keV-masked.zarr-20261024-054806/audit.json"
}
```

`cache_check` checks VC3D's cache of chunks that answered 404 against the bucket and deletes the false markers, so the next read fetches the chunk (`delete: false` only reports them). `render`, `check_surface`, `trace` and `run` already do this around every run on a URL; use it after VC3D ran outside the kit.

```jsonc
// cache_check {"volume": "$VOL"}
// result in 0.00 s
{
  "volumes": [
    {
      "folder": "20250728140407-9.362um-1.2m-113keV-masked.zarr-740e7d4163dba61a",
      "markers": 0,
      "checked": 0,
      "false": [],
      "deleted": 0
    }
  ],
  "false_found": 0,
  "false_deleted": 0
}
```

`seed_check` says whether a seed point is on a surface prediction, how far the nearest on-prediction voxel is, whether the seed is trapped or near an edge, and what the CT shows there. This seed was 1.41 voxels off the prediction, in air:

```jsonc
// seed_check {"volume": "$PRED", "seed": [3104, 3420, 5400], "ct": "$VOL", "horizon": true}
// result in 0.89 s
{
  "seed": [3104.0, 3420.0, 5400.0],
  "value": 0.0,
  "on_prediction": false,
  "nearest_on": [3104, 3419, 5399],
  "nearest_distance": 1.41,
  "ok": false,
  "horizon": {
    "class": "TRAPPED",
    "inner": 0.3714,
    "outer": 0.2964,
    "thresholds": {"inner_min": 0.15, "outer_min": 0.4, "source": "villa PR #2047, PHerc1203 level 2, not calibrated here"}
  },
  "ct": {"value": 48.0, "p10": 34.0, "p90": 118.0, "verdict": "air"}
}
```

`phantoms` finds surface prediction where the CT reads 0, so no papyrus lies under it, and sorts it into `edge` (CT in the same cell), `halo` (CT one cell away) and `beyond` (no CT within a cell, which a blending halo cannot explain).

```jsonc
// phantoms {"volume": "$PRED", "ct": "$VOL", "level": 5}
// result in 5.71 s
{
  "level": 5,
  "chunks_read": 24,
  "prediction_voxels": 7136712,
  "phantom_voxels": 12499,
  "phantom_fraction": 0.0018,
  "phantom_cells": {"edge": 6253, "halo": 248, "beyond": 0},
  "missing_chunks": {"prediction": 2, "ct": 2}
}
```

### Ink

`ink` runs an ink model on a surface volume and always makes the reverse-depth control (`r`) beside the forward map (`f`); `s` adds a depth-shuffled control. Its result compares forward with the controls. In the recording it ran `ink_9um` on CPU and hit its timeout before any map was written:

```jsonc
// ink {"input": "$RENDER", "purpose": "benchmark", "model": "ink_9um-seed42", "device": "cpu", "variants": ["f", "r", "s"], "timeout": 2400}
// error result in 2400.49 s
{
  "exit": "timeout",
  "seconds": 2400.4,
  "purpose": "benchmark",
  "engine": "villa",
  "device": {"asked": "cpu", "reported": null},
  "maps": null,
  "comparison": null,
  "note": "model output, not a reading; compare forward with the controls before saying anything",
  "warnings": [
    "team order taken from VC3D's usual flag, not checked against an umbilicus (no umbilicus given and none in the catalog for this volume); the orientation tool checks it"
  ],
  "log_tail": "Using CPU device\n[2026-10-24 06:23:29,457] INFO Selected 81 patches for inference"
}
```

On a GPU machine, or with a smaller `crop` in `render`, the same call writes the maps and their comparison. On a target scroll `ink` refuses until the readout rule is preregistered (see [Failure modes](#failure-modes)).

`detectability` plants synthetic strokes of known contrast on the sheet face of a surface volume, runs the same ink model again, and reports the faintest contrast whose strokes come back: a window that recovers nothing is blind, and a null there says nothing. It takes `stack`, `purpose`, `model` and `micron_per_pixel`, and like `ink` it needs a GPU in practice. It was not run in the recording: the Job was stopped after `ink` timed out on CPU.

### Looking

`preview` turns a render, a layer stack, an ink map or a surface into a contrast-stretched PNG and returns it as an MCP image, so the agent sees what it made: one layer (the middle by default), the max, mean or min over layers, a 2-D map, or a surface's z coordinate.

```jsonc
// preview {"path": "$RENDER", "mode": "max", "max_side": 640}
// result in 2.16 s, plus 1 PNG image
{
  "png": "$KIT_HOME/work/vc3d/previews/layers.zarr-max-20261024-055413.png",
  "view": "max over layers 0..27",
  "shown_shape": [640, 640],
  "stretch": [86.0, 219.0],
  "values": {"min": 52.0, "max": 255.0, "mean": 161.2167, "nonzero_fraction": 1.0}
}
```

### The VC3D app

The `app_*` tools run the VC3D app offscreen and talk to its agent bridge, which offers 120 methods. `app_start` launches it, optionally on a project file; `app_open` starts it if needed, opens a project when given one, attaches surfaces and takes a screenshot; `app_methods` lists the bridge methods with their parameters; `app_call` calls one; `app_screenshot` returns the window as a PNG; `app_stop` ends it.

The project names the remote scan. The client wrote it with the package's format tool:

```bash
python -m kit.villafmt project w035.volpkg.json --volume "$VOL" --anonymous --voxel-um 9.362 --name PHerc0139-w035
```

```jsonc
// app_start {"open": "$OUT/w035.volpkg.json", "timeout": 180}
// result in 2.59 s
{
  "ping": {"pid": 261, "pong": true, "protocolVersion": 2, "version": "e0bbb8b-2026-10-06"},
  "opened": {"opened": true, "volumeId": "20250728140407-9.362um-1.2m-113keV-masked.zarr-740e7d4163dba61a"},
  "next": "app_call method=state.get, then app_methods to see the 120 bridge methods"
}
```

```jsonc
// app_open {"surfaces": ["$SEG"], "screenshot": true}
// result in 0.38 s, plus 1 PNG image
{
  "attached": 1,
  "of": 1,
  "active": "out",
  "status": "opened",
  "calls": ["segments.attach: ok", "segments.list: ok", "segments.activate: ok"],
  "screenshot": "$KIT_HOME/work/vc3d/previews/app-screenshot.capture-20261024-060334.png"
}
```

```jsonc
// app_methods {"prefix": "viewer."}
// result in 0.00 s
{
  "count": 10,
  "methods": [
    {
      "method": "viewer.center_on_point",
      "params": {"forceRender": "boolean", "point": "object", "viewer": ["string", "null"]},
      "required": ["point"],
      "mcp_tool": "vc3d_center_viewer"
    },
    "... 9 more"
  ],
  "coverage": {"complete": true, "described": 10, "registered": 10}
}
```

```jsonc
// app_call {"method": "state.get"}
// result in 3.48 s
{
  "volume": {
    "id": "20250728140407-9.362um-1.2m-113keV-masked.zarr-740e7d4163dba61a",
    "path": "",
    "volumeIds": ["20250728140407-9.362um-1.2m-113keV-masked.zarr-740e7d4163dba61a"],
    "voxelSize": 9.362
  },
  "vpkg": {"path": "$OUT"},
  "viewers": ["segmentation", "xy plane", "seg xz", "seg yz", "__atlas_workspace_base_mesh"],
  "focusPoi": {"normal": {"x": 0, "y": 0, "z": 1}, "position": {"x": 3310, "y": 3310, "z": 10486.5}, "surfaceId": ""}
}
```

```jsonc
// app_call {"method": "catalog.describe_sample", "params": {"sampleId": "PHerc0139"}}
// result in 1.18 s
{
  "sampleId": "PHerc0139",
  "segmentCount": 39,
  "volumes": 10,
  "representations": [
    "surface-prediction-zarr",
    "surface-prediction-zarr",
    "normal-grids",
    "lasagna",
    "lasagna",
    "lasagna",
    "surface-prediction-zarr"
  ]
}
```

```jsonc
// app_screenshot {"max_dim": 1600}
// result in 0.27 s, plus 1 PNG image
{
  "format": "png",
  "width": 796,
  "height": 796,
  "png": "$KIT_HOME/work/vc3d/previews/app-screenshot.capture-20261024-060456.png"
}
```

```jsonc
// app_stop {}
// result in 0.34 s
{"stopped": true, "pid": 261}
```

### Lasagna

The seven `lasagna_*` tools drive villa's lasagna surface fitter (`lasagna/` in villa) with no VC3D: find villa and check its Python, list its configs, write the input manifest `fit.py` needs from a published lasagna run (or mirror only the chunks under a box), run `fit.py` and `fit2tifxyz.py` and read back the loss, checkpoints and tifxyz stats, run a synthetic self-test whose check can fail, and talk to villa's fit service. They need a villa checkout and a Python with torch, numpy, zarr, tifffile and tensorstore:

```bash
export VILLA_DIR=/path/to/villa LASAGNA_PYTHON=/path/to/lasagna-venv/bin/python
```

A CPU-only torch is enough for the self-test and small fits, which run through a shim that loads a box densely instead of streaming over CUDA; real-size fits need a CUDA machine. These calls were made on 24 October 2026 from the 1.1.0 package in a Linux container with no GPU, villa main `6f202456` and a CPU-only torch, on the published PHerc0139 lasagna predictions. The shell form is shown; an agent calls `lasagna_status` and the rest with the same keys. [docs/lasagna-agents.md](docs/lasagna-agents.md) has the setup, every argument, the worked fit (where `$M`, `stages.json` and `start.tifxyz` come from) and the villa quirks the tools work around.

```jsonc
// vc3d-agent lasagna status --check-import
{
  "found": true,
  "found_by": "VILLA_DIR",
  "villa_commit": "6f2024569404a46b0f008eee292773945c07a684",
  "probe": {
    "python": "3.13.17",
    "packages": {
      "torch": "2.14.1+cpu",
      "numpy": "2.5.4",
      "zarr": "3.4.1",
      "tifffile": "2026.10.15",
      "tensorstore": "present"
    },
    "cuda": false,
    "fit_import": "ok"
  },
  "configs": 35,
  "shim": "scripts/lasagna/fit_cpu_shim.py",
  "default_device": "cpu",
  "note": "no CUDA: volume fits run through the dense shim on a box (a local or mirrored manifest, lasagna_manifest with crop), and the cos 'data' loss term needs CUDA. Real-size GPU fits need a CUDA machine: lasagna_fit with dry_run gives the exact command"
}
```

```jsonc
// vc3d-agent lasagna configs --name init_cyl.json
{
  "config": {
    "name": "init_cyl.json",
    "init_mode": "cylinder_seed",
    "total_steps": 4000,
    "stages": [
      "cyl_init: 1000",
      "cyl_grow: 1000",
      "cyl_grow_refine: 2000",
      "cyl_refine: 0",
      "cyl_polish: 0",
      "mesh_opt: 0"
    ],
    "loss_terms": ["bend", "corr", "cyl_bend", "cyl_normal", "... 13 more"],
    "needs": ["seed", "model_h", "umbilicus (the manifest's umbilicus_json)"]
  }
}
```

```jsonc
// vc3d-agent lasagna manifest --source s3://vesuvius-challenge-open-data/PHerc0139/representations/predictions/lasagna/20260102150214-lasagna-20260419180421-L2/ --crop 8000,13000,38000,512,512,512
{
  "manifest": "$KIT_HOME/work/vc3d/lasagna/inputs/PHerc0139-20260102150214-lasagna-20260724-crop-2/PHerc0139-20260102150214-lasagna-20260724.lasagna.json",
  "mode": "mirror",
  "kit_crop": [8000, 12992, 38000, 512, 528, 512],
  "problems": [],
  "crop_snapped": {
    "crop_asked": [8000, 13000, 38000, 512, 512, 512],
    "crop": [8000, 12992, 38000, 512, 528, 512],
    "why": "start clipped at 0 and edges on whole voxels of the coarsest group, so every channel's crop starts on the same grid in villa's load_3d"
  }
}
```

```jsonc
// vc3d-agent lasagna selftest
{
  "exit": 0,
  "passed": true,
  "checks": {"fits_ran": true, "progress_complete": true, "fit_turned_plane": true, "control_kept_tilt": true},
  "tilt": {"start": 0.29999998699535024, "fit": 0.008281133286891363, "control": 0.25076510249482753},
  "villa_commit": "6f2024569404a46b0f008eee292773945c07a684"
}
```

The self-test fits a synthetic start plane tilted 0.3 and passes only when the fit with the normal term brings the tilt under a quarter of that while the control, with the term off, keeps over 60 % of it, so the check can fail.

```jsonc
// vc3d-agent lasagna fit --config stages.json --input $M --mode ext --tifxyz-init start.tifxyz --device cpu --voxel-um 2.4 --out fitout --export '{"single_segment": true, "output_name": "agent.tifxyz"}'
{
  "mode": "ext",
  "device": "cpu",
  "exit": 0,
  "seconds": 3.7,
  "progress": {
    "lines": 30,
    "last_step": 30,
    "total_steps": 30,
    "first_loss": 0.4767,
    "last_loss": 0.343795,
    "min_loss": 0.343795,
    "non_finite": 0
  },
  "checkpoints": {"count": 2, "final": "fitout/model_final.pt"},
  "tifxyz": [
    {
      "path": "fitout/tifxyz/winding_0000.tifxyz",
      "grid_rows_cols": [17, 17],
      "valid_fraction": 1.0,
      "edge_voxels": {"median": 15.549, "p95": 18.394, "max": 22.491},
      "area_cm2": 0.0035
    }
  ],
  "export": {"exit": 0, "seconds": 2.1, "tifxyz": [{"path": "fitout/export/agent.tifxyz", "area_cm2": 0.0035}]}
}
```

```jsonc
// vc3d-agent lasagna export --model fitout/model_final.pt --single-segment --output-name agent2.tifxyz --voxel-um 2.4
{
  "exit": 0,
  "seconds": 2.0,
  "tifxyz": [
    {
      "path": "$KIT_HOME/work/vc3d/lasagna/exports/20261024-055235-model_final/agent2.tifxyz",
      "grid_rows_cols": [17, 17],
      "edge_voxels": {"median": 15.549, "p95": 18.394, "max": 22.491},
      "area_cm2": 0.0035
    }
  ]
}
```

`lasagna_service` talks to villa's fit service: `discover`, `health`, `datasets`, `jobs`, `submit`, `job`, `cancel` and `results`. Here the service ran on CPU, so only the read actions were tried; its fits need CUDA. `tests/test_lasagna.py` drives `submit`, `job` and `results` against a stand-in service.

```jsonc
// vc3d-agent lasagna service --action health --url http://127.0.0.1:9876
{"status": "ok", "api_version": "2", "url": "http://127.0.0.1:9876"}
```

```jsonc
// vc3d-agent lasagna service --action jobs --url http://127.0.0.1:9876
{"queue_generation": 0, "jobs": [], "api_version": "2", "url": "http://127.0.0.1:9876"}
```

### Other

`jobs` follows anything started with `"background": true`: `list`, `status`, `wait` (up to 600 s per call), `cancel` and `log`.

```jsonc
// render {"surface": "$SEG", "volume": "$VOL", "preset": "9um", "crop": [2600, 2300, 256, 256], "background": true}
// result in 0.01 s
{
  "job": "20261024-060309-render-a677",
  "status": "running",
  "next": "jobs action=wait id=20261024-060309-render-a677 (or action=status to look without waiting)"
}
```

```jsonc
// jobs {"action": "wait", "id": "20261024-060309-render-a677", "timeout": 600}
// result in 18.04 s
{
  "job": "20261024-060309-render-a677",
  "tool": "render",
  "status": "succeeded",
  "created": "2026-10-24T06:03:09+0000",
  "finished": "2026-10-24T06:03:26+0000",
  "error": null,
  "result": {"exit": 0, "seconds": 16.3, "order": "team (--flip-normals)", "shape": [28, 256, 256]}
}
```

`kit` runs the package's `python -m kit` commands (`run` for the experiment ledger, `auc`, `fetch`, `verify`, `layers`, `shuffle`, `provenance`, `prizes`) and returns their output.

```jsonc
// kit {"args": ["prizes"]}
// result in 0.23 s
{
  "args": ["prizes"],
  "exit": 0,
  "seconds": 0.2,
  "output": "$ /usr/bin/python3 -m kit prizes\nOpen prizes, snapshot checked 2026-10-11 (https://scrollprize.org/prizes)\n\n2027 Grand Prize             $1,000,000  2027-06-25  244 days left\n... 14 more lines"
}
```

`modal` would run the headless VC3D Modal app (its self-test, or one `vc_*` tool) on rented compute. It refuses unless the user starts the server with `KIT_ALLOW_MODAL=1`, and the Modal runner it would start is not part of this package.

```jsonc
// modal {"entrypoint": "selftest"}
// refused in 0.01 s
{
  "error": "Modal runs rent compute, which needs the user's go-ahead (AGENTS.md rule 8). The user enables them by starting this server with KIT_ALLOW_MODAL=1."
}
```

## Failure modes

Every message below came back from a real call: in the recording, or, where marked, from the 1.1.0 package on 24 October 2026.

| What came back | Why | What to do |
| --- | --- | --- |
| `status` with `"tools": null` and `"fix": "set VC_APPIMAGE to villa's release AppImage, or VC_BIN to a villa build's bin folder ..."` | The server found no VC3D build (this was the container used for ink, which has none) | Set `VC_APPIMAGE` or `VC_BIN`, then call `selftest` |
| `{"error": "jobs: timeout must be maximum 600"}`, exit 2 from the shell | An argument is outside its schema | Read the tool's schema with `vc3d-agent vc3d tools --json`; wait again rather than longer |
| `{"error": "give volume (a URL) or all=true"}` from `cache_check` | Nothing to check was named | Pass `volume`, or `all: true` |
| `vc_extend_edge is not in $VC_BIN (build it from the VC3D fork branch vc3d-auto-extend; villa's release does not have it yet)` | `extend` needs a tool villa has not released | Build that branch, or grow with `trace` instead |
| `run` with `"exit": 1` and the program's usage in `log_tail` | `run` passes arguments through as given, and the program rejected them | Read `log_tail` and `tool_help`; prefer the wrapped tool (`check_surface` for the self-crossing census) |
| `trace` with `"data_term": "none: no normal grids, so no loss of the tracer read the scan ..."` | No `normal_grids` were given, so the surface only extrapolates the seed | Pass the normal grids the catalog lists for the volume |
| `check_surface` with `"verdict": "look closer"` and `"seating: unclear (0 of 3 windows seated)"` | The surface is not on a sheet everywhere it was sampled | Do not render or run ink on it; retrace, or compare frames with `frame` |
| `seed_check` with `"ok": false`, `"class": "TRAPPED"`, `"verdict": "air"` | The seed is off the prediction, in empty space | Start from `nearest_on`, or pick another seed |
| `orientation` with `"reliable": false`, and `render` with `"orientation": {"checked": false, ...}` | No umbilicus was given and the catalog has none for this volume | Pass an `umbilicus`, or check the order from `orientation`'s vote |
| `app_open` with `"segments.attach: [-32000] No volume package loaded"` | The app was started without a project | Give it one: `open` on `app_start`, or `project` on `app_open`, set to a `.volpkg.json` (see [The VC3D app](#the-vc3d-app)) |
| `viewer.center_on_point failed: [-32602] point must be an object {"param": "point"}` | A list was passed where the bridge wants an object | Pass `point` as an object; `app_methods` gives each method's parameter types, and `state.get` shows positions as `{"x", "y", "z"}` |
| `ink` with `"exit": "timeout"` and `"maps": null` after 2,400 s | `ink_9um` with three variants on a 640 px, 28-layer window on 8 CPU cores did not finish | Use a GPU, a smaller `crop`, fewer `variants`, or `"background": true` with a longer `timeout` |
| `no registered model 'ink_9um-seed42'; models: none (models action=add, or fetch_model)` (1.1.0 package) | The model was never downloaded on this machine | Call `fetch_model` first |
| `ink on a target needs experiment=<slug>: fix the readout rule before any map exists (python -m kit run init SLUG ...)` (1.1.0 package) | `purpose: target` with no preregistered experiment | Preregister the readout rule with `python -m kit run init`, then pass `experiment` |
| `Modal runs rent compute, which needs the user's go-ahead ...` | Paid compute is off by default | Only the user turns it on, with `KIT_ALLOW_MODAL=1` |
| `lasagna_status` with `"found": false` and `"problem": "villa's lasagna not found ..."` (1.1.0 package) | `VILLA_DIR` or `LASAGNA_DIR` is not set | Point them at a villa checkout and set `LASAGNA_PYTHON` |

## Limits

- The tests use stand-in VC3D tools. Real VC3D builds change their options; `status` and `selftest` say what a build supports, and `selftest` checks the conventions the tools rely on.
- Ink models need a Python with numpy and torch, named by `KIT_INK_PYTHON`, and in practice a GPU: on 8 CPU cores one `ink` call on a 640 by 640 window did not finish in 40 minutes.
- The VC3D app runs offscreen; `app_screenshot` returns its window at the size the offscreen platform gives (796 by 796 pixels in the recording).
- stdio only: no HTTP transport and no authentication. Do not expose it over a network.
- A traced surface and an ink map are model output. Automatic tracers wander between sheets; check every surface before rendering it.
- Text is in US English; some argument and result field names keep their original spelling (`centre_xy`, `neighbour_pairs`) so existing callers keep working.

## Rules built in

Read [AGENTS.md](AGENTS.md). In short: tools write only under `work/`, `experiments/` and `checkpoints/` of the kit home (this folder, or `KIT_HOME`), which `.gitignore` keeps out of git; `ink` and `detectability` on a target scroll refuse to run until the readout rule is preregistered with `python -m kit run init`; every ink run makes its reverse-depth control; and an ink map is model output, not a reading.

## Tests

```bash
python -m unittest discover -s tests
```

The tests run every tool against stand-in VC3D tools written by `tests/vc3d_fakes.py`, so they need no VC3D, GPU or scan data; tests that need numpy, tifffile or zarr skip without them. `tests/test_vc3d_mcp.py` checks the protocol: version negotiation, every error code, batches, progress, cancellation (the tool's subprocess must be gone), a crashing tool, images and a real stdio session whose stdout must be pure JSON. With the official MCP Python SDK installed it also drives the server through the SDK's own client. `tests/test_lasagna.py` covers the lasagna tools against a stand-in villa and fit service.

## License and credits

Code: Apache License 2.0 ([LICENSE](LICENSE)). Data and model weights keep their own licenses and are not included. VC3D and villa are the Vesuvius Challenge's ([ScrollPrize/villa](https://github.com/ScrollPrize/villa)); the seating score in `check_surface` is ported from [axiosdevs/herculaneum-scroll-tools](https://github.com/axiosdevs/herculaneum-scroll-tools) (MIT). The pictures and examples use Vesuvius Challenge open data, CC BY-NC 4.0. Chase Hendrick, Independent Researcher, ORCID 0009-0002-9754-6087.
