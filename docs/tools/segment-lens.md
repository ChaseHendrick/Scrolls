# segment-lens: turn published segments in 3D with their holes, folds and stretched edges painted on

A Hugging Face Space that shows each published tifxyz segment of a scan on no prize list as a 3D surface colored by `kit tifxyz check`'s flags, beside the Segment Atlas numbers, with a sortable table of every mesh, and the same atlas as an API and MCP server for agents.

| Field | Value |
| --- | --- |
| Id | `segment-lens` |
| Status | Current |
| Kind | app, agent tool |
| Area | Viewers and apps |
| Run | [huggingface.co/spaces/SharpMeow/segment-lens](https://huggingface.co/spaces/SharpMeow/segment-lens) (the page), `https://sharpmeow-segment-lens.hf.space/agents/` (API) and `/agents/gradio_api/mcp/` (MCP), `python3 spaces/segment-lens/app.py` (both locally, port 7860), `python3 -m http.server` in `spaces/segment-lens/` (the page locally; add `?data=URL/` to read a local atlas build) |
| Code | `spaces/segment-lens/app.js` (the page), `spaces/segment-lens/app.py` (the server: the page, the API and MCP), `spaces/segment-lens/requirements.txt`, `spaces/segment-lens/index.html`, `spaces/segment-lens/style.css`, `spaces/segment-lens/README.md` (the Space card), `spaces/segment-lens/NOTICE`, `spaces/segment-lens/LICENSE` |
| Tests | `tests/test_segment_lens.py` |
| Needs | The server: Python 3.12, gradio 6.28.0, numpy, mcp (`requirements.txt`). In the browser: WebGL, ES modules and import maps, `DecompressionStream` (gzip), three.js 0.160.0 from cdn.jsdelivr.net |
| Runs on | A free CPU Space for the server; the 3D page runs in the visitor's browser. A `segment_picture` call takes under 1 s once its preview is fetched (cloud container, 2026-10-24). Each preview is one file of about 150 to 250 KB; the table reads `atlas.jsonl` once. In headless, software-rendered Chromium on a 4-core cloud container, a local atlas of 8 PHerc0139 meshes loaded and drew its first preview within 4 s (2026-10-24) |
| Network | The server: `huggingface.co` (the same dataset files, `atlas.jsonl` cached for an hour, the last 32 previews kept in memory). The visitor's browser: `huggingface.co` (the dataset SharpMeow/vesuvius-segment-atlas: `atlas.jsonl`, `summary.json`, `lens/*.slg.gz`), `cdn.jsdelivr.net` (three.js), `fonts.googleapis.com` and `fonts.gstatic.com` |
| Writes | Nothing: the URL hash holds the selected scroll and mesh; the API's pictures are temporary files Gradio serves |
| Go-ahead | Needed to create the Space: Chase asked for it on 24 Oct 2026. Later redeploys from merged `main` with public data fall under the standing yes (AGENTS.md rule 8) |
| Released | This repository from the change that adds it (24 Oct 2026); the Space is created after the atlas dataset is published |
| License | Apache 2.0 for the page ([`LICENSE`](../../spaces/segment-lens/LICENSE), [`NOTICE`](../../spaces/segment-lens/NOTICE)); the data it reads is CC BY-NC 4.0 (Vesuvius Challenge open data, via the Segment Atlas) |
| Checked | 2026-10-24 against commit `cc03099` |

## What it does

The [Segment Atlas](atlas.md) measures every published segment, but a number such as "9 mm2 of folds" does not say where. Segment Lens draws the mesh, from the atlas's preview grid, and paints the nodes `kit tifxyz check` flags: blue at the rims of holes inside the sheet, red at folds, orange on over-stretched edges. The card beside it gives the same numbers as `kit atlas show` and a button that copies the `kit tifxyz check` command that reproduces them on the full grid.

Only scans on no prize list get a 3D preview, following the public media rule ([docs/media/README.md](../media/README.md)); scrolls on a prize list appear in the table with numbers only. The atlas decides which, from kit's dated prize snapshot. What the page shows is geometry only: no CT, no ink, and nothing here says whether a segment stays on one sheet.

## When to use it

- To see where a segment's holes, folds and stretched edges are before you trace, render or flatten it.
- To compare segments of one scroll by area and grid quality, in the table.

Do not use it:

- As proof that a segment is good: the flags are about the grid, and the preview keeps 1 in k nodes.
- For scrolls on a prize list in 3D: they have numbers only, on purpose.

## Quick start

Open the Space, pick a scroll in the bottom-left panel, then a segment (largest first). Drag to turn the surface, scroll to zoom, and switch the flag colors on or off in the card. **Table** lists every top-level mesh; click a row with "view" to open it.

Locally, after a build (see [atlas](atlas.md)):

```bash
python -m kit atlas build work/atlas --scroll PHerc0139 --limit 8 --lens
mkdir -p /tmp/lens && ln -s "$PWD/spaces/segment-lens" /tmp/lens/app && ln -s "$PWD/work/atlas" /tmp/lens/data
python3 -m http.server 8000 --directory /tmp/lens     # then open http://localhost:8000/app/index.html?data=http://localhost:8000/data/
```

On 24 Oct 2026 that showed PHerc0139 w026 on the 9.362 um volume first (40.35 cm2, 85.7 % filled, 99.3 % of edges within 10 %, no holes, 9.05 mm2 of folds in 258 nodes, 9.22 mm2 stretched in 263 nodes), drawn from a 183 x 186 preview (1 in 2 nodes).

## Checks and controls

- **Same file format on both sides.** A test writes a preview with `kit.atlas.lens_grid` and reads it with the page's own `parseLens` (run in Node.js when it is installed), and compares size, step, bounding box and flags; the page's header offsets are also checked against the Python format without Node.
- **No preview for a prize-list scroll.** The page draws only rows whose atlas entry names a preview file, and the atlas writes none for a scroll on a prize list (tested in `tests/test_atlas.py`); a test checks the page has no other path to a mesh.
- **Not covered:** the WebGL drawing, which was checked by eye in headless Chromium (2026-10-24).

Claim label: Sourced fact, for the measurements of public meshes; Interpretation, for any reading of them.

## Agent tools (API and MCP, since 1.1.0)

`app.py` serves the page at `/` and a Gradio app at `/agents/`, whose four endpoints are also MCP tools (`/agents/gradio_api/mcp/`). Every answer that names a mesh carries `open_in_browser`, a link that opens it on the page.

| Tool | Arguments | Returns |
| --- | --- | --- |
| `list_scrolls` | none | `scrolls` (scroll, meshes, previews, area_cm2, prize_lists), `total_meshes`, `version`, `open_in_browser` |
| `list_segments` | `scroll` (empty for all), `sort` (area_cm2, filled_share, within_10pct, holes_mm2, folds_mm2, stretched_mm2, grid_h, segment), `top` (1 to 500), `previews_only` | `segments` (summary rows with `has_preview`), `count` |
| `get_segment` | `segment_id` | the full atlas row, `kit_command`, `preview` (grid size and flag counts, or why there is none), `open_in_browser` |
| `segment_picture` | `segment_id`, `view` (`3d` or `grid`), `azimuth`, `elevation` | a PNG with the flags painted on, and the preview's grid size and flag counts |

```python
from gradio_client import Client
c = Client("https://sharpmeow-segment-lens.hf.space/agents/")
top = c.predict("PHerc0139", "area_cm2", 5, True, api_name="/list_segments")
seg = c.predict(top["segments"][0]["id"], api_name="/get_segment")
picture, info = c.predict(seg["id"], "3d", 30, 20, api_name="/segment_picture")
```

`segment_picture` draws only meshes with a preview, so a scroll on a prize list gets a refusal, never a picture. The 3D picture is an orthographic view with the scan's z up, shaded by how each cell faces the viewer; nearest surface wins.

## Commands and options

The server (`app.py`) reads these environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `SEGMENT_LENS_DATA` | the published dataset | Another copy of the atlas, a URL ending in `/` (a local build, for testing) |
| `PORT` | `7860` | The port the server listens on |
| `SPACE_HOST` | unset | Set by Hugging Face to the Space's host name; `open_in_browser` links start with it, else they are relative |

The page takes two URL parts: `?data=URL/` reads `atlas.jsonl`, `summary.json` and `lens/` from another folder (a local build), and the hash `#scroll=SCROLL&id=ID` selects a mesh.

## Python API

`app.py` (importable without starting the server): `list_scrolls()`, `list_segments(scroll, sort, top, previews_only)`, `get_segment(segment_id)`, `segment_picture(segment_id, view, azimuth, elevation)` as in the table above, `parse_lens(blob)` (the same reader as `kit.atlas.read_lens`), `render_3d(flags, xyz, azimuth, elevation)`, `render_grid(flags, xyz)` and `build_app()`; refusals raise `LensError`. For agents in a headless browser, `window.segmentLens` (JavaScript):

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `state()` | `{rows, selected, loaded, grid}` | nothing | `grid` is `[w, h, k]` of the loaded preview |
| `rows(scroll)` | atlas rows, all or one scroll's | nothing | The same fields as `atlas.jsonl` |
| `select(id)` | true when the id exists | nothing | Loads that mesh's preview, if it has one |
| `flags()` | `{hole, fold, stretched, nodes}` | nothing | Preview nodes carrying each flag (pooled), or null |
| `command()` | the `kit tifxyz check` command for the selected mesh | nothing | |
| `version` | the page version | nothing | A string, not a function |

## Inputs

The Segment Atlas dataset: `atlas.jsonl` (one row per mesh), `summary.json`, and the preview files `lens/NAME.slg.gz` whose format is under "Lens files" on the [atlas page](atlas.md#lens-files).

## Outputs

Pictures on screen, and the copied command. Nothing is written anywhere.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| "The atlas could not be loaded" and an HTTP code | The dataset is not reachable (or `?data=` points nowhere) | Check the dataset page; for a local build, the server and the trailing slash |
| "The preview could not be loaded: HTTP 404" | The atlas names a preview file that is missing | The next daily build makes it again |
| "The preview could not be loaded: not a Segment Lens grid" | The file is not in the Lens format | Report it; the atlas writes only that format |
| "This scroll is on a prize list, so it has numbers here but no 3D preview" | By design | Use the numbers, or `kit tifxyz` on your own machine |
| `no mesh with id '...'; list_segments gives the ids` | The API was given an id the atlas does not have | Take ids from `list_segments` |
| `... has no preview: its scroll is on a prize list, so it has numbers but no preview (public media rule)` | `segment_picture` on a prize-list scroll | Use `get_segment`'s numbers |
| `... has no preview: it was not measured or has no filled nodes` | The atlas row has no preview file | Use the numbers, or `kit tifxyz check` |
| `sort must be one of ...`, `top must be 1 to 500`, `view must be "3d" or "grid"`, `elevation must be -90 to 90` | A bad argument | Fix the argument |
| `no meshes for scroll '...'; list_scrolls gives the names` | Unknown scroll name | Take names from `list_scrolls` |
| `not a Segment Lens grid (bad magic)`, `Segment Lens grid has the wrong length`, `the preview has too few nodes to draw` | A broken or tiny preview file | Report it; the next atlas build writes it again |
| A blank canvas | No WebGL, or an old browser without `DecompressionStream` | Use a current Chrome, Edge, Firefox or Safari |

## How it works

1. Fetch `atlas.jsonl`; list scrolls with previews first.
2. For the chosen mesh, fetch its `.slg.gz`, decompress with `DecompressionStream('gzip')`, read the header and the three 16-bit planes, and rebuild positions inside the stored bounding box.
3. Two triangles per grid cell whose four corners are present; normals from three.js; the scan's z axis points up on screen.
4. Each node's color: fold over stretched over hole over plain, each switchable.

## Cost and time

Free to use. The Space is a static page on Hugging Face; the data comes from the atlas dataset.

## For agents

- **Command:** open the Space (or the local page) in headless Chromium, wait for `window.segmentLens.state().rows > 0`, then `select(id)` and wait for `state().loaded`.
- **Parse:** `flags()`, `rows(scroll)`, `command()`.
- **Rerun:** safe; the page writes nothing.
- **Success:** `state().loaded` is true for a mesh with a preview.
- **Not a pass:** a mesh with few flags is not a mesh on one sheet.
- **Go-ahead:** creating the Space or changing its card; redeploys from merged `main` are covered.
- **Never:** add previews of a scroll on a prize list; show CT or ink on this page.

## Tests

`python3 -m unittest tests.test_segment_lens -v`: the page's Lens reader against `kit.atlas.lens_grid` (in Node.js when installed), the header offsets, the card's dataset link, no long dashes, no hard-coded mesh URL, and every `window.segmentLens` call documented on this page.

## History

- 2026-10-24: 1.0.0, first version (on top of `5d217be`).
- 2026-10-24: Connect your tool panel in the Guide ([spaceconnect](spaceconnect.md)): the Segment Atlas with huggingface_hub, datasets, pandas, hf and curl snippets, an example mesh with numpy and tifffile, all run live.
- 2026-10-24: 1.1.0, opens a little more zoomed out (camera 4.0 from the segment instead of 3.2), and the same atlas becomes an API and MCP server for agents at `/agents/` (`list_scrolls`, `list_segments`, `get_segment`, `segment_picture`), as Chase asked ([#187](https://github.com/ChaseHendrick/Scrolls/pull/187)).
- 2026-10-24: 1.1.0 startup fix: the agent tools are mounted with server-side rendering off, because on Spaces it started a Node server on port 7860 and the app could not bind there ([#194](https://github.com/ChaseHendrick/Scrolls/pull/194)).

## Related

- [atlas](atlas.md): the numbers and the preview files.
- [tifxyz](tifxyz.md): the checks, on one segment, on your own machine.
- [Umbilici](umbilici.md): the sibling viewer for center lines.
