# Headless VC3D for agents

Version **1.0.0**. An MCP server and a shell command that let an AI agent (Claude Code, Claude Desktop, any MCP client, or a plain script) run villa's VC3D tools with no display: find public Vesuvius Challenge data, trace a surface, check it, render its surface volume, flatten it, run ink models with their controls and look at every result as a PNG. It serves 39 tools with JSON schemas, progress, cancellation and images.

It does not replace villa or VC3D. It calls their command line tools (`vc_grow_seg_from_seed`, `vc_render_tifxyz`, `vc_flatten`, `vc_tifxyz_selfcross` and the rest) and, through the `app_*` tools, the VC3D app's agent bridge, then checks what they return. Until this release the same server shipped only inside [AutoPipeline](https://github.com/ChaseHendrick/Scrolls#released-tools); this package is the server on its own, without AutoPipeline's pipeline tools (`umbilicus`, `seeds`, `distortion`, `autopipeline`).

## Why

Agents are good at calling tools and bad at knowing VC3D's conventions: which way the layers stack, which scan frame a segment is in, whether a blank render means a missing chunk. Each of those fails silently. These tools build the checks in: `render` votes on the surface normal before it trusts `--flip-normals`, `audit` finds chunks a render would read as zeros, `check_surface` asks whether the surface sits on a papyrus sheet, `landmarks` checks the affine between two scans, and `ink` always makes the reverse-depth control beside the forward map.

## Install

Python 3.11 or newer (tested on 3.11 and 3.13). The server and most tools use only the standard library.

```bash
git clone --branch submission/progress-2026-10-vc3d-agent --depth 1 https://github.com/ChaseHendrick/Scrolls.git scrolls-vc3d-agent
cd scrolls-vc3d-agent/submissions/progress-2026-10-vc3d-agent/vc3d-agent
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[maps]"      # the maps extra (numpy, tifffile, zarr 3, scipy) is for scoring and layer tools
export VC_APPIMAGE="$(python scripts/get_vc3d.py)"   # villa's current Linux AppImage, sha256 checked; prints its path
python -m kit vc3d call status
python -m kit vc3d call selftest
```

On macOS, or with your own villa build, set `VC_BIN` to the folder that holds `vc_render_tifxyz` instead of `VC_APPIMAGE`. `docs/vc3d-headless.md` says where to get the tools.

## Use it from an agent

Claude Code, run in this folder:

```bash
claude mcp add vc3d-agent -e VC_APPIMAGE=/path/to/VC3D.AppImage -- python3 -m kit vc3d mcp
```

Any other MCP client: command `python3`, arguments `-m kit vc3d mcp`, with this folder as the working directory or on `PYTHONPATH`:

```json
{"mcpServers": {"vc3d-agent": {"command": "python3", "args": ["-m", "kit", "vc3d", "mcp"],
  "env": {"PYTHONPATH": "/path/to/this/folder", "VC_APPIMAGE": "/path/to/VC3D.AppImage"}}}}
```

Ask the agent to call `status` first and `guide` for the workflow. The server speaks newline-delimited JSON-RPC 2.0 on stdio, MCP protocol versions 2024-11-05 to 2025-11-25, and offers the two guides and `AGENTS.md` as resources.

## Use it from a shell

```bash
python -m kit vc3d tools                        # one line per tool; --json gives the argument schemas
python -m kit vc3d call catalog '{"action": "samples"}'
python -m kit vc3d call fetch_segment '{"sample": "PHerc0139", "segment": "w035", "frame": "20250728140407"}'
python -m kit vc3d call render @render-args.json --background
python -m kit vc3d call jobs '{"action": "wait", "id": "JOB_ID", "timeout": 600}'
```

`call` prints the result as JSON and exits 0 when the tool succeeded, 1 when it ran and failed, and 2 on bad arguments. Long calls take `"background": true` and are followed with `jobs`.

## The tools

| Group | Tools |
| --- | --- |
| Setup | `status`, `selftest`, `list_tools`, `tool_help`, `guide` |
| Open data | `catalog`, `fetch_segment`, `landmarks`, `models`, `fetch_model` |
| VC3D tools | `run`, `trace`, `extend`, `render`, `flatten`, `trim`, `merge_patch`, `merge_surfaces`, `volume_meta` |
| Checks | `inspect`, `check_surface`, `orientation`, `frame`, `audit`, `cache_check`, `seed_check`, `phantoms` |
| Ink | `ink` (forward and reverse-depth control always; depth-shuffled control on request), `detectability` (planted strokes of known contrast) |
| Looking | `preview` (a PNG returned as an image) |
| The VC3D app | `app_start`, `app_open`, `app_methods`, `app_call`, `app_screenshot`, `app_stop` |
| Other | `jobs`, `kit` (the `python -m kit` commands below), `modal` |

The command line holds `vc3d` and the commands the workflow names: `run` (the experiment ledger), `auc` (scoring against published labels with the reverse-depth map as control), `fetch` (published surface volumes), `verify`, `layers`, `shuffle`, `provenance` and `prizes`. `kit run all`, `watch` and `catalog` plan AutoPipeline runs and say so here. The `modal` tool refuses unless the user starts the server with `KIT_ALLOW_MODAL=1`, and the Modal runner it would start is not part of this package.

## Rules built in

Read [AGENTS.md](AGENTS.md). In short: tools write only under `work/`, `experiments/` and `checkpoints/` of the kit home (this folder, or `KIT_HOME`), which `.gitignore` keeps out of git; `ink` and `detectability` on a target scroll refuse to run until the readout rule is preregistered with `python -m kit run init`; every ink run makes its reverse-depth control; and an ink map is model output, not a reading.

## Tests

```bash
python -m unittest discover -s tests
```

The tests run every tool against stand-in VC3D tools written by `tests/vc3d_fakes.py`, so they need no VC3D, GPU or scan data; tests that need numpy, tifffile or zarr skip without them. `tests/test_vc3d_mcp.py` checks the protocol: version negotiation, every error code, batches, progress, cancellation (the tool's subprocess must be gone), a crashing tool, images and a real stdio session whose stdout must be pure JSON. With the official MCP Python SDK installed it also drives the server through the SDK's own client.

## Limits

- Tests use stand-in VC3D tools. Real VC3D builds change their options; `status` and `selftest` say what this build supports, and `selftest` checks the conventions the tools rely on.
- Ink models need a Python with numpy and torch, named by `KIT_INK_PYTHON`, and a GPU for anything but small windows.
- stdio only: no HTTP transport and no authentication. Do not expose it over a network.
- A traced surface and an ink map are model output. Automatic tracers wander between sheets; check every surface before rendering it.
- Text is in US English; some argument and result field names keep their original spelling (`centre_xy`) so existing callers keep working.

## License and credits

Code: Apache License 2.0 ([LICENSE](LICENSE)). Data and model weights keep their own licenses and are not included. VC3D and villa are the Vesuvius Challenge's ([ScrollPrize/villa](https://github.com/ScrollPrize/villa)); the seating score in `check_surface` is ported from [axiosdevs/herculaneum-scroll-tools](https://github.com/axiosdevs/herculaneum-scroll-tools) (MIT). Chase Hendrick, Independent Researcher, ORCID 0009-0002-9754-6087.
