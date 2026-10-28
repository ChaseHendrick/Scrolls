# ink-atlas: browse and compare seven ink models on the First Letters surfaces, from a page or an agent

A Space and an MCP server over the public First Letters ink atlas: seven public ink models on 32 traced surfaces, one shared 9.6 um canvas, with a loupe, an all-model compare and six agent tools.

| Field | Value |
| --- | --- |
| Id | `ink-atlas` |
| Status | Current |
| Kind | app, agent tool, data |
| Area | Viewers and apps |
| Run | [huggingface.co/spaces/SharpMeow/ink-atlas](https://huggingface.co/spaces/SharpMeow/ink-atlas) (the page: Explore, Compare models, The atlas, How to read it, Agents and API), `Client("SharpMeow/ink-atlas").predict(..., api_name="/get_map")`, the MCP server `https://sharpmeow-ink-atlas.hf.space/gradio_api/mcp/`, `python3 spaces/ink-atlas/app.py` (the page on any computer), `import atlasdata` from `spaces/ink-atlas/` |
| Code | `spaces/ink-atlas/app.py` (the page, API and MCP tools), `spaces/ink-atlas/atlasdata.py` (reading the dataset, pictures, records), `spaces/ink-atlas/tools/deploy.py` (upload to Hugging Face). The data is the dataset [SharpMeow/first-letters-ink-atlas](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas) |
| Tests | `tests/test_ink_atlas_space.py`, 10 tests on a fake atlas laid out like the dataset (no network, no gradio) |
| Needs | A browser for the page; `gradio_client` to call it from Python; any MCP client for agents. To serve it yourself: Python 3.12, gradio 6.28.0, numpy, Pillow, huggingface_hub (`spaces/ink-atlas/requirements.txt`) |
| Runs on | The Space's free CPU. Live calls on 2026-10-27 from a cloud container: `list_surfaces` 3.2 s, a whole-surface `get_map` 2.4 s, a 512 px crop 1.6 s, `compare_models` 3.2 s the first time on a surface and 1.9 s after (maps cached) |
| Network | `huggingface.co` (the dataset's files, read on demand and cached by huggingface_hub). Links on the page point at `raw.githubusercontent.com` (meshes) and `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (CT); the page does not read them |
| Writes | Nothing of the caller's. The server writes pictures to `ink-atlas-out/` in its temp folder and keeps the dataset's files in the Hugging Face cache |
| Go-ahead | Not needed to use. Making the Space public, and every later new Space or card change, needs Chase's yes (the go-ahead rule, hard rule 8); redeploys of the approved Space from merged `main` fall under the standing yes |
| Released | Dataset and Space public on Hugging Face since 2026-10-27 (Chase's yes to each); README "Released tools" entry `ink-atlas` |
| License | Page code Apache 2.0 ([`spaces/ink-atlas/LICENSE`](../../spaces/ink-atlas/LICENSE), [`NOTICE`](../../spaces/ink-atlas/NOTICE)); the dataset CC BY-NC 4.0, derived from the Vesuvius Challenge open data and ketchupbyheinz's meshes; every model MIT |
| Checked | 2026-10-27 against commit `ff82a63` |

## What it does

Seven public ink models (ink_9um seeds 42 and 43, Reader v2, Reader V3, dense_native, d9v2 and Hecate 9.6) were run on the same traced surfaces of the First Letters scrolls. Every surface was rendered once from level 0 of the public CT onto a 9.6 um canvas, so the maps of all seven line up pixel for pixel. Each model kept both depth orders and three depth windows, and an ensemble (the mean of per-model z-scores, Erwin Nieuwlaar's PHerc0343 recipe from ink-sdk) sits beside them. The public dataset holds 32 surfaces: 25 from 13 First Letters scrolls and 7 PHerc0343 reference surfaces.

The Space makes that dataset easy to look at and to use from code. **Explore** shows any layer of any surface, as a map, an overlay on the CT or the CT alone, in four color ramps with adjustable contrast; a click opens a full-resolution loupe with a slider between CT and map. **Compare models** puts every model, the ensemble and the CT on one box in a grid, with each layer's mean, median, 99th percentile and correlation with the ensemble there. **The atlas** gives the overview and a clickable gallery; **How to read it** explains depth order, windows, liveness and exposure; **Agents and API** documents the six MCP tools and carries the Connect your tool panel.

It does not run any model: every picture comes from the dataset's PNGs. Every map is model output, not a reading. "Alive" (a model with real spread on a surface) and the face check (ketchupbyheinz's per-pair score from villa PR #2318 of which face two models' strongest marks agree on) come from the dataset's `meta.json`.

## When to use it

- To see how the seven public models differ on the same surface, at the same pixels.
- To give an agent the atlas: list surfaces, pull maps or crops, compare models, read the provenance.
- To find the right file in the dataset (each surface's `surface_info` lists every file's URL).

Do not use it:

- To run a model on your own region or segment: use [ink-lens](ink-lens.md).
- To score a map against published labels: use [auc](auc.md).
- To read text: a map is model output, not a reading.

## Quick start

```bash
pip install gradio_client
python - <<'PY'
from gradio_client import Client
c = Client("SharpMeow/ink-atlas")
s = c.predict("PHerc0483A", api_name="/list_surfaces")
print(len(s), s[0]["id"])
grid, numbers = c.predict(s[0]["id"], -1, -1, 512, "", "c+0", api_name="/compare_models")
print(grid, list(numbers["layers"])[:3])
PY
```

Run on 2026-10-27 against the Space (private then, so with `token=`; public now, so no token is needed), it printed:

```text
4 kbh-PHerc0483A_3155_3610_11128
/tmp/gradio/.../kbh-PHerc0483A_3155_3610_11128-compare-....png ['ensemble', 'ink_9um-s42', 'ink_9um-s43']
```

It worked when the grid PNG exists and `numbers["layers"]` has the ensemble and every model of that surface.

## Checks and controls

The page shows data; it makes no claim of its own. What can fail is the plumbing, and the tests check it on a fake atlas: a model built from the ensemble's signal must correlate with it above 0.8 in `compare_models`, a flat model must stay below 0.2 and be marked not alive, uncovered pixels must be painted as no surface, crops must stay inside the canvas, and Hecate's missing windows must fall back to c+0. Live, every MCP tool answered on 2026-10-27 (`get_map` returned the picture as an image).

The numbers in Compare models are each layer's own statistics in the box. A high correlation with the ensemble means a model agrees with the others there, not that either is right.

Claim label: Model output (every map and every number derived from them); None (the page itself).

## Commands and options

The page's settings and the API's tool calls; each API call is also an MCP tool with the same arguments.

### `/atlas_summary`

No arguments. Returns counts, the seven models with authors and licenses, what each file holds, credits and license.

### `/list_scrolls`

No arguments. One row per scroll: `scroll`, `surfaces`, `role`.

### `/list_surfaces`

| Option | Default | Meaning |
| --- | --- | --- |
| `scroll` | `""` | a scroll id such as `PHerc0483A`; empty lists every surface |

### `/surface_info`

| Option | Default | Meaning |
| --- | --- | --- |
| `surface_id` | required | a surface id from `list_surfaces` |

### `/get_map`

| Option | Default | Meaning |
| --- | --- | --- |
| `surface_id` | required | a surface id |
| `layer` | `ensemble` | `ensemble`, `ct` or a model id: `ink_9um-s42`, `ink_9um-s43`, `reader-v2`, `reader-v3`, `dense-native`, `d9v2`, `hecate-9.6` |
| `window` | `c+0` | depth window center in 9.6 um layers: `c-4`, `c+0`, `c+4` (Hecate 9.6 has `c+0` only) |
| `order` | `""` | `forward` (as stored) or `reverse`; empty uses the face check's majority |
| `x`, `y` | `-1` | crop center in canvas pixels (x across, y down); below 0 shows the whole surface |
| `size` | `0` | crop side in pixels, at most `MAX_CROP` = 1024; 0 shows the whole surface shrunk to `DISPLAY` = 1400 px |
| `colormap` | `gray` | `gray`, `papyrus`, `ember`, `ice` |
| `mode` | `map` | `map`, `overlay` (map in color over the CT) or `ct` |

### `/compare_models`

| Option | Default | Meaning |
| --- | --- | --- |
| `surface_id` | required | a surface id |
| `x`, `y` | `-1` | box center in canvas pixels; below 0 uses the middle of the surface |
| `size` | `512` | box side in pixels |
| `order` | `""` | as in `get_map` |
| `window` | `c+0` | as in `get_map` |

### `python3 spaces/ink-atlas/tools/deploy.py`

```text
usage: deploy.py [-h] [--private] [--yes] space
```

| Option | Default | Meaning |
| --- | --- | --- |
| `space` | required | `OWNER/NAME` of the Space |
| `--private` | off | create the Space private |
| `--yes` | off | upload without asking (only after Chase's yes) |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `SPACE_HOST` | unset | set by Hugging Face; the page's API snippets use it, else `https://sharpmeow-ink-atlas.hf.space` |
| `ATLAS_ROOT` | unset | a local folder laid out like the dataset; when set, the page reads it instead of the Hub |
| `ATLAS_REPO` | `SharpMeow/first-letters-ink-atlas` | the dataset to read |
| `ATLAS_REVISION` | unset (main) | a dataset commit to pin |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `atlasdata.Atlas(root=None, repo=REPO, revision=REVISION, prefetch=True)` | the atlas | `AtlasError` | reads `atlas.json`; `meta(id)`, `file(rel)`, `url(rel)`, `gray(rel)`, `valid(id)` |
| `atlasdata.atlas_summary(atlas)` | dict | | as `/atlas_summary` |
| `atlasdata.list_scrolls(atlas)` | list | | as `/list_scrolls` |
| `atlasdata.list_surfaces(atlas, scroll="")` | list | `AtlasError` | as `/list_surfaces` |
| `atlasdata.surface_info(atlas, surface_id)` | dict | `AtlasError` | as `/surface_info` |
| `atlasdata.get_map(atlas, surface_id, ...)` | (PNG path, dict) | `AtlasError` | as `/get_map`, plus `max_side` |
| `atlasdata.compare_models(atlas, surface_id, ...)` | (PNG path, dict) | `AtlasError` | as `/compare_models`, plus `colormap` |
| `atlasdata.layer_picture(atlas, sid, ...)` | (PIL image, dict) | `AtlasError` | the picture behind the page's views |
| `atlasdata.region(atlas, sid, x, y, size)` | (y0, y1, x0, x1) or None | `AtlasError` | a box moved inside the canvas |
| `atlasdata.face_votes(meta)` | (votes, order) | | the face check's votes and the order the page opens on |

## Inputs

The dataset's files: `atlas.json` (schema `inkatlas-atlas/1`) and per surface `meta.json` (schema `inkatlas-surface/1`), `ct_mid.png`, `ensemble/ORDER.png`, `ensemble-rev/ORDER.png` and `maps/MODEL/WINDOW_s1_ORDER.png`, all 8-bit grayscale on the surface's canvas (2016 x 2016 to 6048 x 2304 pixels at 9.6 um). Coordinates in the API are canvas pixels, x across and y down. A covered pixel is one where `ct_mid.png` is not 0.

## Outputs

Pictures are PNGs (RGB). `get_map`'s record:

| Field | Type | Meaning |
| --- | --- | --- |
| `surface`, `layer`, `window`, `order`, `mode` | string | what was drawn; `window` is the one used (c+0 for Hecate) or null for the ensemble and CT |
| `source` | string | the dataset file's URL |
| `box_y0_y1_x0_x1` | list or null | the crop in canvas pixels |
| `stretch` | dict | percentiles and the 0 to 1 values that went to black and white, and gamma |
| `covered_fraction` | number | share of covered pixels in the picture |
| `picture_wh` | list | picture width and height |

`compare_models`'s record has `layers`: per layer `alive`, `window`, `mean`, `p50`, `p99` (0 to 1 values in the box over covered pixels) and `r_with_ensemble` (Pearson r, null for the ensemble or a constant box).

| Exit code | Meaning |
| --- | --- |
| `0` | `deploy.py` uploaded the Space, or `app.py` stopped normally |
| `1` | `deploy.py`: a file is missing or the upload was declined |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `the atlas could not be read from...:...` | the Hub or `ATLAS_ROOT` could not be read at start | check the network or the folder; restart |
| `colormap...is not one of...` | an unknown color ramp | use `gray`, `papyrus`, `ember` or `ice` |
| `no scroll...in the atlas; list_scrolls gives them` | the scroll has no surface in this release | call `list_scrolls` |
| `layer...is not ensemble, ct or one of...` | an unknown layer | use `ensemble`, `ct` or a model id |
| `window...is not one of...` | an unknown window | use `c-4`, `c+0` or `c+4` |
| `(...,...) is outside the...x...canvas (x across, y down)` | the crop center is off the canvas | take the size from `surface_info`'s `canvas_hw` (height, width) |
| `no surface...in the atlas; list_surfaces gives the ids` | an unknown surface id | call `list_surfaces` |
| `...is not in the atlas` | a file missing under `ATLAS_ROOT` | copy the whole surface folder |
| `could not fetch...from...:...` | the Hub refused or timed out | retry later |

## How it works

`Atlas` downloads `atlas.json` and every surface's `meta.json` and `preview.jpg` once (`snapshot_download` with allow patterns), and fetches each map PNG on first use with `hf_hub_download`; decoded maps stay in an LRU cache of 40. A picture is the map's covered pixels stretched between two percentiles (1 and 99.5 by default), gamma-corrected, and passed through a 256-entry color ramp; whole-surface pictures are box-averaged to `DISPLAY` = 1400 px first. The overlay blends the colored map over the CT with per-pixel opacity equal to the map value times the overlay strength. The ensemble layer is `ensemble/forward.png` for the stored order and `ensemble-rev/reverse.png` for the reversed one, so each uses the statistics of its own reading side. The page opens a surface on the depth order more alive model pairs agree on in the face check, as stored on a tie.

## Cost and time

Free: a CPU Space with no GPU. Times are in Runs on. The server's memory is dominated by the cache of decoded maps (up to 40 maps of about 4 to 14 MB each); not measured on the Space.

## For agents

- **Command:** add the MCP server `https://sharpmeow-ink-atlas.hf.space/gradio_api/mcp/` (`claude mcp add --transport http ink-atlas URL`), or `Client("SharpMeow/ink-atlas").predict(..., api_name="/list_surfaces")`.
- **Parse:** `list_surfaces` rows' `id`; `get_map` and `compare_models` return (picture, record); read `record["layers"][MODEL]["r_with_ensemble"]` and `record["source"]`.
- **Rerun:** safe; reads only.
- **Success:** a picture and a record with no error.
- **Not a pass:** agreement with the ensemble is not correctness; a bright map is not ink; a model marked `alive: false` is flat on that surface.
- **Go-ahead:** Nothing to use it; Chase's yes to change the Space or its card.
- **Never:** call a map a reading or say letters were found; describe possible findings from it in public; copy maps of surfaces not in this release.

## Tests

`python -m unittest tests.test_ink_atlas_space -v` covers the data layer on a fake atlas (lists, files, crops, pictures, the compare numbers' control) and the page's tool docstrings, MCP flag, files and the one-scroll head. The Hub download path and the gradio page are not tested offline; they were checked live on 2026-10-27.

## History

- 2026-10-28: phone fix ([PR #254](https://github.com/ChaseHendrick/Scrolls/pull/254)), found by `python -m kit spaceconnect scroll --width 390` and the live checks after the 27 October deploy: Gradio gives each of the gallery's 6 columns at least 100 px, so on a 390 px phone tiles 4 to 6 of every row on The atlas were clipped out of sight; phones now get 3 columns and tablets 4. Deployed as Space commit `61521458`.
- 2026-10-27: one page scroll bar: the head carries `onescroll.html` (written by `python -m kit spaceconnect render`, [spaceconnect](spaceconnect.md)), so the page scrolls as a whole, and `tools/deploy.py` uploads it; the gallery on The atlas grows to show every surface instead of scrolling inside the page (Gradio caps a gallery at 55% of the window), and on a phone the Compare models table drops its bars and fits the screen instead of scrolling sideways; American spelling in the page, its API docstrings and code (the color helpers in `atlasdata` are now `LAYER_COLOR`, `color` and `mark(color_=)`). The published dataset's `meta.json` keeps the British spelling of its center-only windows key, and the page still reads that key.
- 2026-10-27: color: ember maps by default, a color per model in Compare and the tables, colored header and cards (`ef7e9ba`).
- 2026-10-27: first version: page, API, MCP server, Connect panel (`5d25489`).

## Related

- [ink-lens](ink-lens.md): runs the same models on your own region; the atlas used its comparison engine.
- [fibercheck](fibercheck.md): whether papyrus fibers show on a traced surface.
- [atlas](atlas.md): the Segment Atlas, geometry numbers for every published segment (a different atlas).
- [SharpMeow/first-letters-ink-atlas](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas): the data.
