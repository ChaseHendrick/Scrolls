"""Ink Atlas: seven public ink models on the same traced surfaces of the First Letters scrolls, side by side.

The web page, the API and the MCP server for the public First Letters ink atlas (the Hugging Face dataset
SharpMeow/first-letters-ink-atlas). The page reads the dataset file by file and keeps nothing of its own; the data
work is atlasdata.py.
  python3 app.py            serve the page (on a Space, or on any computer)
Every map is model output, not a reading.
"""
import functools
import html
import json
import os
import random
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import atlasdata as A  # noqa: E402
from atlasdata import AtlasError  # noqa: E402

VERSION = "1.0.0"
SPACE = "SharpMeow/ink-atlas"
CONNECT_HTML = HERE / "connect.html"
ONESCROLL_HTML = HERE / "onescroll.html"      # python -m kit spaceconnect render writes it
THUMBS = A.OUT / "thumbs"
_ATLAS = {"atlas": None, "error": None}
_LOCK = threading.Lock()


def atlas():
    """The dataset, opened once (atlas.json, every meta.json and preview)."""
    with _LOCK:
        if _ATLAS["atlas"] is None:
            try:
                _ATLAS["atlas"] = A.Atlas(root=os.environ.get("ATLAS_ROOT") or None)
            except Exception as exc:  # noqa: BLE001
                _ATLAS["error"] = f"{type(exc).__name__}: {exc}"
                raise AtlasError(f"the atlas could not be read from {A.REPO}: {_ATLAS['error']}") from None
        return _ATLAS["atlas"]


# ----- API and MCP tools (each docstring is the tool's description and its arguments' descriptions) -----------------

def atlas_summary() -> dict:
    """What the Ink Atlas is: how many surfaces and scrolls, the seven ink models with their authors and licenses,
    what each file holds, the credits and the license. Start here.

    Returns:
        A record of the atlas. Every map is model output, not a reading.
    """
    return A.atlas_summary(atlas())


def list_scrolls() -> list:
    """Every scroll in the Ink Atlas, with how many traced surfaces it has and whether they are First Letters
    surfaces or PHerc0343 reference surfaces.

    Returns:
        One row per scroll: scroll, surfaces, role.
    """
    return A.list_scrolls(atlas())


def list_surfaces(scroll: str = "") -> list:
    """The traced surfaces of one scroll in the Ink Atlas, or of every scroll when scroll is empty.

    Args:
        scroll: a scroll id such as PHerc0483A or PHerc0343 (list_scrolls gives them); empty lists every surface.

    Returns:
        One row per surface: id, scroll, role, scan, voxel size, canvas size, the models whose maps have real spread
        there, the face check's votes and the depth order the page opens on.
    """
    return A.list_surfaces(atlas(), scroll)


def surface_info(surface_id: str) -> dict:
    """Everything about one surface of the Ink Atlas: its mesh and CT links, how it was rendered, each model's
    liveness and published training exposure, the ensemble recipe, the face check of every model pair, and direct
    URLs of all its map files.

    Args:
        surface_id: a surface id from list_surfaces, such as kbh-PHerc0343_4937_3336_11593.

    Returns:
        A record of the surface. Model output, not a reading.
    """
    return A.surface_info(atlas(), surface_id)


def get_map(surface_id: str, layer: str = "ensemble", window: str = "c+0", order: str = "", x: float = -1,
            y: float = -1, size: int = 0, colormap: str = "gray", mode: str = "map"):
    """One ink map of one surface as a picture: the ensemble, one model's map, or the CT. Whole surface, or a
    full-resolution crop around a point.

    Args:
        surface_id: a surface id from list_surfaces.
        layer: "ensemble", "ct" or a model: ink_9um-s42, ink_9um-s43, reader-v2, reader-v3, dense-native, d9v2, hecate-9.6.
        window: the depth window center in 9.6 um layers: "c-4", "c+0" or "c+4" (Hecate 9.6 has c+0 only).
        order: "forward" (depth order as stored) or "reverse"; empty uses the face check's majority.
        x: crop center across the canvas in pixels (9.6 um each); below 0 shows the whole surface.
        y: crop center down the canvas in pixels; below 0 shows the whole surface.
        size: crop side in pixels, up to 1024; 0 shows the whole surface shrunk to 1400 pixels.
        colormap: "gray" (ink bright), "papyrus" (ink dark on papyrus), "ember" or "ice".
        mode: "map" (the layer alone), "overlay" (the layer in color over the CT) or "ct".

    Returns:
        The picture (PNG) and a record: the source file's URL, the crop box, the contrast stretch.
    """
    return A.get_map(atlas(), surface_id, layer, window, order, x, y, int(size or 0), colormap, mode)


def compare_models(surface_id: str, x: float = -1, y: float = -1, size: int = 512, order: str = "",
                   window: str = "c+0"):
    """Every ink model, the ensemble and the CT on the same box of one surface, in one labeled grid at full
    resolution, with numbers for each layer in the box.

    Args:
        surface_id: a surface id from list_surfaces.
        x: box center across the canvas in pixels; below 0 uses the middle of the surface.
        y: box center down the canvas in pixels; below 0 uses the middle of the surface.
        size: box side in pixels, 256 to 1024.
        order: "forward" (as stored) or "reverse"; empty uses the face check's majority.
        window: "c-4", "c+0" or "c+4".

    Returns:
        The grid (PNG) and a record with each layer's mean, median, 99th percentile and correlation with the
        ensemble in the box. Model output, not a reading.
    """
    return A.compare_models(atlas(), surface_id, x, y, int(size or 512), order, window)


# ----- the page ---------------------------------------------------------------------------------------------------

LOOKS = [(A.RAMP_LABEL[k], k) for k in A.RAMPS]
VIEWS = [("Map", "map"), ("Overlay on CT", "overlay"), ("CT", "ct")]
WINDOW_CHOICES = [("-4", "c-4"), ("0", "c+0"), ("+4", "c+4")]
ORDER_CHOICES = [("As stored", "forward"), ("Reversed", "reverse")]


def scroll_choices():
    return [(f"{r['scroll']}  ({r['surfaces']}{' reference' if r['role'] == 'reference' else ''})", r["scroll"])
            for r in A.list_scrolls(atlas())]


def surface_choices(scroll):
    at = atlas()
    return [(A.short_id(s["id"], s["scroll"]), s["id"]) for s in sorted(at.index["surfaces"], key=lambda s: s["id"])
            if s["scroll"] == scroll]


def layer_choices(sid):
    m = atlas().meta(sid)
    out = [("Ensemble of the alive models", A.ENSEMBLE)]
    for mid, (short, _, by) in A.MODELS.items():
        if mid in m.get("models", {}):
            dead = "" if m["models"][mid].get("alive") else "  (flat here)"
            out.append((f"{short} · {by}{dead}", mid))
    return out


def thumbs():
    """Gallery thumbnails of every surface's preview (CT and ensemble side by side)."""
    at = atlas()
    THUMBS.mkdir(parents=True, exist_ok=True)
    items = []
    for s in sorted(at.index["surfaces"], key=lambda s: (s["role"] != "eligible", s["scroll"], s["id"])):
        p = THUMBS / f"{s['id']}.jpg"
        if not p.exists():
            try:
                with Image.open(at.file(f"{s['path']}/preview.jpg")) as im:
                    split(im.convert("RGB")).save(p, quality=86)
            except AtlasError:
                continue
        items.append((str(p), A.label(at, s["id"])))
    return items


def split(preview, side=360):
    """A square tile from a preview (CT and ensemble side by side): the middle of the CT on the left half, the same
    strip of the ensemble on the right, so both show the same stretch of the surface."""
    w, h = preview.size
    half = w // 2
    q = min(half, h) // 2
    cx, cy = half // 2, h // 2
    box = (cx - q // 2, cy - q, cx + q // 2, cy + q)
    left = preview.crop(box)
    right = preview.crop((box[0] + half, box[1], box[2] + half, box[3]))
    tile = Image.new("RGB", (2 * q, 2 * q), (250, 248, 244))
    tile.paste(left, (0, 0))
    r = np.asarray(right.convert("L"))
    tile.paste(Image.fromarray(A.ramp("ember")[r]), (left.width, 0))
    tile = tile.resize((side, side), Image.Resampling.LANCZOS)
    from PIL import ImageDraw
    ImageDraw.Draw(tile).line([(side // 2, 0), (side // 2, side)], fill=(246, 165, 59), width=2)
    return tile


def card(big, small, tone=0):
    return f'<div class="ia-card ia-t{tone % 4}"><div class="ia-big">{big}</div><span>{small}</span></div>'


def info_html(sid, layer, window, order):
    at = atlas()
    s, m = at.surface(sid), at.meta(sid)
    votes, opens = A.face_votes(m)
    alive = A.alive_models(m)
    h, w = m["render"]["canvas_hw"]
    um = m.get("canvas_um", 9.6)
    rel, used = A.layer_rel(at, sid, layer, window, order)
    mesh = m.get("mesh", {}).get("base", "")
    link = f"https://huggingface.co/spaces/{SPACE}?surface={sid}&layer={layer}&order={order}"
    note = (f'<p class="ia-note">Hecate 9.6 has the center window only, so this shows c+0.</p>'
            if used and used != window else "")
    ref = ('<p class="ia-note">A PHerc0343 reference surface: the scroll behind the First Letters prize awarded on '
           '8 October 2026.</p>' if s["role"] == "reference" else "")
    return f"""
<div class="ia-info">
  <div class="ia-title">{html.escape(s['scroll'])} <small>{html.escape(A.short_id(sid, s['scroll']))}</small></div>
  {ref}
  <div class="ia-cards">
    {card(f"{len(alive)}/{len(m.get('models', {}))}", "models with real spread here", 0)}
    {card(f"{w * um / 1000:.0f} x {h * um / 1000:.0f} mm", f"{w} x {h} pixels at {um} um", 1)}
    {card(f"{votes['forward']} : {votes['reverse']}", f"face check, as stored : reversed ({votes['tie']} tie)", 2)}
  </div>
  {note}
  <table class="ia-kv">
    <tr><th>Scan</th><td>{html.escape(str(m.get('scan')))} · {m.get('voxel_um')} um voxels</td></tr>
    <tr><th>Mesh</th><td><a href="{html.escape(mesh)}" target="_blank">tifxyz</a> · {html.escape(m.get('credit', ''))}</td></tr>
    <tr><th>CT</th><td><a href="{html.escape(m.get('ct', ''))}" target="_blank">OME-Zarr level 0</a> (open data)</td></tr>
    <tr><th>This layer</th><td><a href="{html.escape(at.url(rel))}" target="_blank">full-resolution PNG</a> ·
      <a href="{html.escape(at.url(s['path'] + '/meta.json'))}" target="_blank">meta.json</a></td></tr>
    <tr><th>Share</th><td><a href="{html.escape(link)}" target="_blank">link to this view</a></td></tr>
  </table>
  <p class="ia-note">Model output, not a reading. The page opens each surface on the depth order most model pairs
  agree on in the face check ({A.ORDER_LABEL[opens]} here).</p>
</div>"""


def compare_table(rec):
    rows = []
    for lid, st in rec["layers"].items():
        name = "Ensemble" if lid == A.ENSEMBLE else A.MODELS[lid][0]
        by = "" if lid == A.ENSEMBLE else A.MODELS[lid][2]
        r = "" if st["r_with_ensemble"] is None else f"{st['r_with_ensemble']:+.2f}"
        flat = "" if st["alive"] else ' <em class="ia-flat">flat here</em>'
        col = A.LAYER_COLOR.get(lid, "#5b4bd6")
        rv = st["r_with_ensemble"]
        bar = ("" if rv is None else f'<i class="ia-rbar" style="width:{max(0.0, rv) * 90:.0f}px;background:{col}"></i>')
        rows.append(f'<tr><td><b><i class="ia-dot" style="background:{col}"></i>{html.escape(name)}</b>{flat}'
                    f"<span>{html.escape(by)}</span></td>"
                    f"<td>{st['mean']:.3f}</td><td>{st['p50']:.3f}</td><td>{st['p99']:.3f}</td><td>{bar}{r}</td></tr>")
    y0, y1, x0, x1 = rec["box_y0_y1_x0_x1"]
    return (f'<table class="ia-cmp"><tr><th>Layer</th><th>Mean</th><th>Median</th><th>99th pct</th>'
            f'<th>r with ensemble</th></tr>{"".join(rows)}</table>'
            f'<p class="ia-note">Box x {x0} to {x1}, y {y0} to {y1} (canvas pixels, 9.6 um each), depth order '
            f'{A.ORDER_LABEL[rec["order"]]}, window {rec["window"]}. Values are the maps\' 0 to 1 outputs (the '
            f'ensemble\'s are z from -2 to 4 scaled to 0 to 1). Each tile is stretched on its own.</p>')


def models_html():
    rows = "".join(f'<tr><td><b><i class="ia-dot" style="background:{A.LAYER_COLOR[mid]}"></i>{html.escape(t)}</b>'
                   f"</td><td>{html.escape(b)}</td><td>MIT</td></tr>" for mid, (_, t, b) in A.MODELS.items())
    return f'<table class="ia-cmp ia-models"><tr><th>Model</th><th>By</th><th>License</th></tr>{rows}</table>'


def overview_html():
    at = atlas()
    s = A.atlas_summary(at)
    chart = at.url("assets/surfaces-per-scroll.png")
    gif = at.url("assets/models.gif")
    return f"""
<div class="ia-overview">
  <div class="ia-cards ia-cards-4">
    {card(s['surfaces'], 'traced surfaces, each on one shared 9.6 um canvas', 0)}
    {card(s['first_letters_surfaces'], 'surfaces of First Letters scrolls', 1)}
    {card(s['reference_surfaces'], 'PHerc0343 reference surfaces', 2)}
    {card(len(A.MODELS), 'public ink models, every map kept', 3)}
  </div>
  <div class="ia-two">
    <figure><img class="ia-gif" src="{html.escape(gif)}" alt="Every model on one PHerc0343 reference surface" loading="lazy">
      <figcaption>Every model, then the ensemble, on one PHerc0343 reference surface.</figcaption></figure>
    <figure><img src="{html.escape(chart)}" alt="Surfaces in this release by scroll" loading="lazy">
      <figcaption>Surfaces in this release, by scroll.</figcaption></figure>
  </div>
</div>"""


HOW_IT_WAS_MADE = """\
### How the atlas was made

1. **Surfaces.** Traced meshes from ketchupbyheinz's
   [vesuvius-scroll-survey](https://github.com/ketchupbyheinz/vesuvius-scroll-survey) (commit `1f12c1ce`), plus the
   published segments in the open-data bucket.
2. **Render.** Each mesh is rendered from level 0 of the public CT onto a 9.6 um canvas with 65 layers 9.6 um apart
   (trilinear sampling along each pixel's mesh normal, the canvas rule `vc_render_tifxyz` uses with `--scale`). One
   canvas for every scan, whether 8.64 or 9.362 um, so each 9 um model reads its own scale.
3. **Models.** All seven run through the Ink Lens comparison engine, with pinned weights and SHA-256 checks, villa's
   own flat inference and ink-sdk's Hecate adapter, at three depth windows and both depth orders. A liveness check
   marks a model alive on a surface when its map has real spread.
4. **Ensemble.** ink-sdk's ensemble, Erwin Nieuwlaar's PHerc0343 recipe: the mean of per-model z-scores.
5. **Face check.** For every pair of alive models, ketchupbyheinz's face check from
   [villa PR #2318](https://github.com/ScrollPrize/villa/pull/2318) scores whether their strongest marks agree better
   on one face than on the other.
6. **Release rule.** A rule fixed before any map existed decides which surfaces go out in this release. It flagged
   all seven PHerc0343 references, as it had to. Surfaces not in this release may be added later.

The data: [SharpMeow/first-letters-ink-atlas](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas),
CC BY-NC 4.0.
"""

HOW_TO = """\
### Reading a map

A map gives each pixel of the traced surface a number from 0 to 1: how much the model thinks it looks like ink
there. In **Gray**, bright means more ink by the model; **Papyrus** flips it to dark ink on a light ground, the way
letters look on a page. The CT next to it is the middle layer of the render, the papyrus surface itself.

Letters on these scrolls are about 2 to 4 mm tall, so 200 to 400 canvas pixels. Strokes are a few pixels wide.
Blotches much larger than a letter, or patterns that follow the papyrus fibers or cracks in the CT, are not
letters.

### The controls

| Control | What it does |
| --- | --- |
| **Click the map** | opens the loupe there: the CT and the map at full resolution, with a slider between them |
| **Layer** | the ensemble (mean z-score of the alive models), one model, or the CT |
| **Depth window** | where the model's 3D input is centered: on the traced surface (0) or 4 layers to either side |
| **Depth order** | as stored, or reversed: which face of the sheet the model reads as the writing side |
| **View** | the map alone, the map in color over the CT, or the CT alone |
| **Look** | colors, contrast (the low and high percentiles that go to black and white) and gamma |
| **Compare models** tab | every model on the loupe's box, side by side, with numbers |

### Which depth order?

Ink sits on one face of the sheet; nothing on the canvas says which. The page opens each surface on the order that
more model pairs agree on in the face check (villa PR #2318). Flip it to see the other face: a model reading the
wrong face often shows the ink of the next wrap, mirrored, or nothing.

### When a model is "flat here"

A liveness check marks a map flat when its values barely spread on this surface. A flat map is kept and shown, but
the ensemble leaves it out.

### Training exposure

None of these models' published training lists names any scroll in this atlas, PHerc0343 included (d9v2, Reader v2
and Reader V3 list PHerc0343P, a separate object). Hecate's audited training manifest is not published, so its list
rests on its committed trainer. Each surface's `meta.json` records every model's exposure as the published sources
state it.

### Keep in mind

- **Model output, not a reading.** A map can show shapes that are not letters, and miss letters that are there.
- The canvas is 9.6 um per pixel; models trained at other scales may read these surfaces less well.
- The atlas shows each surface once; mesh errors (sheet switches, folds) show up as seams or sudden texture changes.
"""

AGENTS = """\
Every view on this page is also an API endpoint and an **MCP tool**, so Claude, Cursor and other agents can browse the
atlas, pull maps and compare models for you. No key is needed.

**Add the MCP server** (streamable HTTP; older clients use `{host}/gradio_api/mcp/sse`):

```bash
claude mcp add --transport http ink-atlas {host}/gradio_api/mcp/
```

```json
{{"mcpServers": {{"ink-atlas": {{"url": "{host}/gradio_api/mcp/"}}}}}}
```

| Tool | What it returns |
| --- | --- |
| `atlas_summary` | counts, the seven models with authors and licenses, what each file holds, credits |
| `list_scrolls` | every scroll and its number of surfaces |
| `list_surfaces` | one scroll's surfaces: scan, canvas size, alive models, face check votes |
| `surface_info` | one surface: mesh and CT links, render record, liveness, exposure, face check, file URLs |
| `get_map` | a map, the ensemble or the CT as a picture: whole surface, or a full-resolution crop around a point |
| `compare_models` | every model, the ensemble and the CT on one box, in a grid, with numbers per layer |

Things to ask an agent once it is connected:

- "List the Ink Atlas surfaces of PHerc0483A, then show me the ensemble of the first one in papyrus colors."
- "Compare all models on the middle 512 pixels of kbh-PHerc0343_4937_3336_11593 and tell me which agree most with
  the ensemble."
- "Get surface_info for kbh-PHerc0358_2358_2561_4423 and download its Reader V3 maps."

**From Python** (`pip install gradio_client`):

```python
from gradio_client import Client
c = Client("{space}")
surfaces = c.predict("PHerc0343", api_name="/list_surfaces")
picture, record = c.predict(surfaces[0]["id"], "ensemble", "c+0", "", 1000, 900, 512, "papyrus", "map",
                            api_name="/get_map")
grid, numbers = c.predict(surfaces[0]["id"], 1000, 900, 512, "", "c+0", api_name="/compare_models")
```

**The files themselves**: every map is a PNG in the dataset, so tools read it directly:

```python
from huggingface_hub import snapshot_download
root = snapshot_download("SharpMeow/first-letters-ink-atlas", repo_type="dataset",
                         allow_patterns=["atlas.json", "surfaces/PHerc0343/*"])
```

Each `meta.json` links the mesh (`mesh.base`, a tifxyz folder) and the CT (`ct`, OME-Zarr), so a surface opens in
VC3D or neuroglancer from the same files the atlas used.
"""

CSS = """
:root, .dark { --ia-accent:#5b4bd6; --ia-warm:#e08a3c; }
.gradio-container { width:100% !important; max-width:1680px !important; margin:0 auto !important; }
.ia-head { display:flex; align-items:center; gap:16px; padding:10px 4px 6px; flex-wrap:wrap; }
.ia-mark { width:40px; height:40px; flex:none; border-radius:11px;
  background: radial-gradient(circle at 30% 30%, #f6a53b 0 18%, transparent 19%),
              linear-gradient(135deg, #5b4bd6, #2a56a8 55%, #1b1630); box-shadow:0 2px 10px rgba(91,75,214,.35); }
.ia-head h1 { font-family:Fraunces, Georgia, serif; font-weight:650; font-size:32px; margin:0; letter-spacing:-.015em; }
.ia-head p { margin:2px 0 0; color:var(--body-text-color-subdued); font-size:15px; }
.ia-chips { margin-left:auto; display:flex; gap:8px; flex-wrap:wrap; }
.ia-chips span { font-size:13px; padding:5px 11px; border-radius:999px; border:1px solid var(--border-color-primary);
  background:var(--block-background-fill); color:var(--body-text-color-subdued); }
.ia-chips b { color:var(--body-text-color); font-variant-numeric:tabular-nums; }
.ia-chips .mcp { border-color:#5b4bd6; color:#5b4bd6; } .dark .ia-chips .mcp { color:#a99cff; border-color:#a99cff; }
.ia-panel { gap:10px !important; }
.ia-info .ia-title { font-family:Fraunces, Georgia, serif; font-size:24px; font-weight:650; margin:2px 0 6px; }
.ia-info .ia-title small { font-family:Inter, system-ui, sans-serif; font-size:13px; font-weight:500;
  color:var(--body-text-color-subdued); margin-left:6px; }
.ia-cards { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin:8px 0; }
.ia-cards-4 { grid-template-columns:repeat(4,minmax(0,1fr)); }
.ia-card { background:var(--block-background-fill); border:1px solid var(--border-color-primary); border-radius:12px;
  padding:10px 12px; }
.ia-card span { display:block; color:var(--body-text-color-subdued); font-size:12px; margin-top:2px; line-height:1.3; }
.ia-big { font-size:22px; font-weight:650; font-variant-numeric:tabular-nums; }
.ia-kv { width:100%; border-collapse:collapse; font-size:13.5px; margin:6px 0; }
.ia-kv th { text-align:left; font-weight:600; padding:5px 10px 5px 0; white-space:nowrap; vertical-align:top;
  color:var(--body-text-color-subdued); }
.ia-kv td { padding:5px 0; border-bottom:1px solid var(--border-color-primary); }
.ia-kv a, .ia-cmp a, .ia-credit a, .ia-overview a { color:var(--ia-accent) !important; }
.dark .ia-kv a, .dark .ia-credit a { color:#a99cff !important; }
.ia-note, .ia-note p { font-size:12.5px !important; color:var(--body-text-color-subdued); margin:6px 0 !important; }
.ia-cmp { width:100%; border-collapse:collapse; font-size:14px; }
.ia-cmp th, .ia-cmp td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--border-color-primary); }
.ia-cmp td span { display:block; font-size:12px; color:var(--body-text-color-subdued); }
.ia-cmp td:not(:first-child) { font-variant-numeric:tabular-nums; }
.ia-flat { font-style:normal; font-size:11.5px; color:#b0662a; margin-left:6px; }
.ia-models { max-width:760px; }
.ia-two { display:grid; grid-template-columns:minmax(0,440px) minmax(0,1fr); gap:16px; margin-top:12px; }
.ia-two figure { margin:0; } .ia-two img { width:100%; border-radius:12px; border:1px solid var(--border-color-primary); }
.ia-two figcaption { font-size:12.5px; color:var(--body-text-color-subdued); margin-top:4px; }
.ia-legend { display:flex; align-items:center; gap:10px; font-size:12.5px; color:var(--body-text-color-subdued); }
.ia-legend .bar { height:10px; width:180px; border-radius:6px; }
.ia-prose { max-width:980px; }
.ia-credit { text-align:center; font-size:13px; color:var(--body-text-color-subdued); padding:18px 0 6px; }
#ia-main img { cursor:crosshair; }
.gradio-container { background: radial-gradient(1200px 420px at 8% -8%, rgba(91,75,214,.13), transparent 60%),
  radial-gradient(900px 380px at 96% -6%, rgba(224,138,60,.13), transparent 60%),
  radial-gradient(800px 360px at 50% 110%, rgba(194,65,143,.07), transparent 60%) !important; }
.ia-head { background: linear-gradient(110deg, rgba(91,75,214,.10), rgba(42,86,168,.08) 45%, rgba(224,138,60,.10));
  border:1px solid rgba(91,75,214,.18); border-radius:18px; padding:14px 18px !important; margin-bottom:6px; }
.ia-head h1 { background: linear-gradient(90deg, #4b3cbc, #2a56a8 55%, #c2418f); -webkit-background-clip:text;
  background-clip:text; color:transparent; }
.dark .ia-head h1 { background: linear-gradient(90deg, #b3a8ff, #8fb8ff 55%, #f39ac8); -webkit-background-clip:text;
  background-clip:text; }
.ia-chips .c0 { border-color:#3d8be0; } .ia-chips .c0 b { color:#2a56a8; }
.ia-chips .c1 { border-color:#e08a3c; } .ia-chips .c1 b { color:#c86a1c; }
.ia-chips .c2 { border-color:#c2418f; } .ia-chips .c2 b { color:#a8327a; }
.dark .ia-chips .c0 b { color:#8fb8ff; } .dark .ia-chips .c1 b { color:#f6b26b; } .dark .ia-chips .c2 b { color:#f39ac8; }
.ia-chips .mcp { background: linear-gradient(90deg, #5b4bd6, #7b2a8c); color:#fff !important; border:0; }
.ia-card { border-top:4px solid #5b4bd6 !important; }
.ia-t0 { border-top-color:#5b4bd6 !important; } .ia-t0 .ia-big { color:#4b3cbc; }
.ia-t1 { border-top-color:#3d8be0 !important; } .ia-t1 .ia-big { color:#2a56a8; }
.ia-t2 { border-top-color:#e08a3c !important; } .ia-t2 .ia-big { color:#c86a1c; }
.ia-t3 { border-top-color:#c2418f !important; } .ia-t3 .ia-big { color:#a8327a; }
.dark .ia-t0 .ia-big { color:#b3a8ff; } .dark .ia-t1 .ia-big { color:#8fb8ff; }
.dark .ia-t2 .ia-big { color:#f6b26b; } .dark .ia-t3 .ia-big { color:#f39ac8; }
.ia-info .ia-title { color:#4b3cbc; } .dark .ia-info .ia-title { color:#b3a8ff; }
.ia-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:7px; vertical-align:0; }
.ia-rbar { display:inline-block; height:8px; border-radius:4px; margin-right:8px; vertical-align:1px; opacity:.85; }
.ia-panel { background: linear-gradient(180deg, rgba(91,75,214,.06), rgba(224,138,60,.05)) !important;
  border-radius:16px; padding:8px !important; }
.ia-steps button.primary { background: linear-gradient(90deg, #5b4bd6, #c2418f) !important; border:0 !important; }
#ia-tabs button[role=tab][aria-selected=true] { color:#4b3cbc !important; }
.dark #ia-tabs button[role=tab][aria-selected=true] { color:#b3a8ff !important; }
.ia-steps { gap:6px !important; flex-wrap:nowrap !important; }
.ia-steps button { flex:1 1 0 !important; }
.ia-chead p { font-size:14px; }
.ia-gallery .caption-label { font-size:11.5px !important; }
.ia-gallery .grid-wrap { max-height:none !important; height:auto !important; overflow-y:visible !important; }
.ia-two img.ia-gif { max-width:440px; }
.ia-legend { flex-wrap:wrap; row-gap:4px; } .ia-legend span { white-space:nowrap; }
.ia-legend .bar { width:140px; flex:none; }
.ia-kv, .ia-kv tr, .ia-kv th, .ia-kv td, .ia-cmp, .ia-cmp tr, .ia-cmp th, .ia-cmp td { border-left:0 !important;
  border-right:0 !important; border-top:0 !important; background:transparent !important; }
.ia-kv { border:0 !important; } .ia-kv tr:last-child td { border-bottom:0 !important; }
@media (max-width: 900px) {
  .ia-cards, .ia-cards-4 { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .ia-two { grid-template-columns:1fr; } .ia-chips { margin-left:0; }
}
@media (max-width: 640px) { .ia-head h1 { font-size:25px; } .ia-head p { display:none; }
  .ia-cmp { font-size:12.5px; } .ia-cmp th, .ia-cmp td { padding:6px 4px; } .ia-cmp .ia-rbar { display:none; } }
"""

HEAD = """
<meta name="description" content="Ink Atlas: seven public ink models on the same traced surfaces of the First Letters
scrolls, side by side, with an API and MCP server for agents. Model output, not a reading.">
<meta property="og:title" content="Ink Atlas">
<meta property="og:description" content="Every map of seven public ink models on traced Herculaneum scroll surfaces,
on one shared 9.6 um canvas. Browse, compare, or connect an agent.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,650&display=swap" rel="stylesheet">
"""


def page_head():
    """HEAD plus onescroll.html, so the page scrolls as a whole and no frame inside it keeps a scroll bar of its own."""
    return HEAD + (ONESCROLL_HTML.read_text() if ONESCROLL_HTML.exists() else "")


def legend(cmap, mode):
    if mode == "ct":
        stops, lo, hi = A.RAMPS["gray"], "dark", "bright"
    else:
        name = cmap if not (mode == "overlay" and cmap == "gray") else "ember"
        stops, lo, hi = A.RAMPS[name], "less ink by the model", "more ink by the model"
    grad = ", ".join(stops)
    return (f'<div class="ia-legend"><span>{lo}</span><span class="bar" style="background:linear-gradient(90deg,'
            f'{grad})"></span><span>{hi}</span><span>· click the map to open the loupe there</span></div>')


def theme():
    import gradio as gr
    violet = gr.themes.Color(c50="#f2f0fe", c100="#e3defd", c200="#c9c0fa", c300="#a99cff", c400="#8676ee",
                             c500="#5b4bd6", c600="#4b3cbc", c700="#3d3199", c800="#30277a", c900="#241d5c",
                             c950="#16113a")
    t = gr.themes.Base(primary_hue=violet, secondary_hue="orange", neutral_hue="slate", radius_size="md",
                       font=(gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"),
                       font_mono=(gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"))
    return t.set(body_background_fill="#f6f5f1", body_background_fill_dark="#0d0f1a",
                 block_background_fill="#ffffff", block_background_fill_dark="#161a2b",
                 block_border_color="#e4e1f0", block_border_color_dark="#262b45",
                 button_primary_background_fill="#5b4bd6", button_primary_background_fill_dark="#7a6cf0",
                 button_primary_background_fill_hover="#4b3cbc", button_primary_background_fill_hover_dark="#8f83f5",
                 slider_color="#5b4bd6", slider_color_dark="#a99cff",
                 table_border_color="#e4e1f0", table_border_color_dark="#262b45",
                 table_even_background_fill="#ffffff", table_odd_background_fill="#faf9fd",
                 table_even_background_fill_dark="#161a2b", table_odd_background_fill_dark="#191d31")


def build_demo():
    import gradio as gr

    def guard(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except AtlasError as exc:
                raise gr.Error(str(exc)) from None
            except gr.Error:
                raise
            except Exception as exc:  # noqa: BLE001
                import traceback
                print(f"{fn.__name__} failed: {traceback.format_exc()}", flush=True)
                raise gr.Error(f"{type(exc).__name__}: {str(exc)[:400]}") from None
        return wrapped

    host = (f"https://{os.environ['SPACE_HOST']}" if os.environ.get("SPACE_HOST")
            else "https://sharpmeow-ink-atlas.hf.space")
    at = atlas()
    summary = A.atlas_summary(at)
    order_ids = [s["id"] for s in sorted(at.index["surfaces"], key=lambda s: (s["scroll"], s["id"]))]
    first = "kbh-PHerc0343_4937_3336_11593" if "kbh-PHerc0343_4937_3336_11593" in at.surfaces else order_ids[0]
    gallery_items = thumbs()
    gallery_ids = [s["id"] for s in sorted(at.index["surfaces"],
                                           key=lambda s: (s["role"] != "eligible", s["scroll"], s["id"]))]

    def center(sid):
        h, w = at.meta(sid)["render"]["canvas_hw"]
        return [w // 2, h // 2]

    def render(sid, layer, window, order, mode, cmap, lo, hi, gamma, alpha, pt, lsize):
        lo, hi = float(lo), float(hi)
        if hi <= lo:
            hi = min(100.0, lo + 0.5)
        pt = pt or center(sid)
        h, w = at.meta(sid)["render"]["canvas_hw"]
        side = A.DISPLAY
        img, _ = A.layer_picture(at, sid, layer, window, order, None, cmap, lo, hi, gamma, mode, alpha, side=side)
        box = A.region(at, sid, pt[0], pt[1], int(lsize))
        main = A.mark(img, box, img.size[0] / w)
        ct, _ = A.layer_picture(at, sid, layer, window, order, box, cmap, 0.5, 99.5, 1.0, "ct")
        loupe_mode = "map" if mode == "ct" else mode
        lp, _ = A.layer_picture(at, sid, layer if layer != A.CT else A.ENSEMBLE, window, order, box, cmap, lo, hi,
                                gamma, loupe_mode, alpha)
        return main, (ct, lp), legend(cmap, mode), info_html(sid, layer, window, order)

    def on_scroll(scroll):
        ch = surface_choices(scroll)
        return gr.update(choices=ch, value=ch[0][1] if ch else None)

    def on_surface(sid, layer):
        m = at.meta(sid)
        _, opens = A.face_votes(m)
        ch = layer_choices(sid)
        keep = layer if layer in [c[1] for c in ch] else A.ENSEMBLE
        return gr.update(choices=ch, value=keep), gr.update(value=opens), center(sid)

    def step(sid, k):
        i = order_ids.index(sid) if sid in order_ids else 0
        nid = order_ids[(i + k) % len(order_ids)] if k else random.choice(order_ids)
        s = at.surface(nid)
        return gr.update(value=s["scroll"]), gr.update(choices=surface_choices(s["scroll"]), value=nid)

    def on_click(sid, evt: gr.SelectData):
        h, w = at.meta(sid)["render"]["canvas_hw"]
        k = min(1.0, A.DISPLAY / max(h, w))            # the whole-surface picture is shrunk by k
        return [min(w - 1, int(evt.index[0] / k)), min(h - 1, int(evt.index[1] / k))]

    def on_gallery(evt: gr.SelectData):
        sid = gallery_ids[evt.index]
        s = at.surface(sid)
        return (gr.update(value=s["scroll"]), gr.update(choices=surface_choices(s["scroll"]), value=sid),
                gr.Tabs(selected="explore"))

    def on_load(request: gr.Request):
        q = dict(request.query_params) if request else {}
        sid = q.get("surface") if q.get("surface") in at.surfaces else first
        s = at.surface(sid)
        layer = q.get("layer") if q.get("layer") in [c[1] for c in layer_choices(sid)] + [A.CT] else A.ENSEMBLE
        order = q.get("order") if q.get("order") in A.ORDERS else A.face_votes(at.meta(sid))[1]
        tab = q.get("tab") if q.get("tab") in ("explore", "compare", "atlas", "howto", "agents") else "explore"
        return (gr.update(value=s["scroll"]), gr.update(choices=surface_choices(s["scroll"]), value=sid),
                gr.update(choices=layer_choices(sid), value=layer), gr.update(value=order), center(sid),
                gr.Tabs(selected=tab))

    def on_compare(sid, pt, size, order, window, cmap):
        pt = pt or center(sid)
        png, rec = A.compare_models(at, sid, pt[0], pt[1], int(size), order, window, cmap)
        s = at.surface(sid)
        head = (f"**{s['scroll']} · {A.short_id(sid, s['scroll'])}**, box of {int(size)} pixels around "
                f"x {pt[0]}, y {pt[1]}. Click the map in Explore to move it.")
        return png, compare_table(rec), head

    chips = (f'<div class="ia-chips"><span class="c0"><b>{summary["surfaces"]}</b> surfaces</span><span class="c1"><b>'
             f'{summary["scrolls"]}</b> scrolls</span><span class="c2"><b>{len(A.MODELS)}</b> models</span>'
             '<span class="mcp">MCP server</span></div>')
    with gr.Blocks(title="Ink Atlas", delete_cache=(1800, 3600)) as demo:
        gr.HTML('<div class="ia-head"><div class="ia-mark"></div><div><h1>Ink Atlas</h1><p>Seven public ink models '
                'on the same traced surfaces of the First Letters scrolls, side by side on one 9.6 um canvas.</p>'
                f'</div>{chips}</div>')
        pt = gr.State(center(first))
        with gr.Tabs(elem_id="ia-tabs") as tabs:
            with gr.Tab("Explore", id="explore"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=1, min_width=270, elem_classes="ia-panel"):
                        scroll = gr.Dropdown(scroll_choices(), value=at.surface(first)["scroll"], label="Scroll")
                        surface = gr.Dropdown(surface_choices(at.surface(first)["scroll"]), value=first,
                                              label="Surface", filterable=True)
                        with gr.Row(elem_classes="ia-steps"):
                            prev_b = gr.Button("Previous", size="sm", min_width=0)
                            rand_b = gr.Button("Surprise me", size="sm", min_width=0, variant="primary")
                            next_b = gr.Button("Next", size="sm", min_width=0)
                        layer = gr.Dropdown(layer_choices(first), value=A.ENSEMBLE, label="Layer")
                        view = gr.Radio(VIEWS, value="map", label="View")
                        order = gr.Radio(ORDER_CHOICES, value=A.face_votes(at.meta(first))[1], label="Depth order")
                        window = gr.Radio(WINDOW_CHOICES, value="c+0", label="Depth window (layers from the surface)")
                        lsize = gr.Radio([("256", 256), ("512", 512), ("1024", 1024)], value=512,
                                         label="Loupe size (pixels, 9.6 um each)")
                        with gr.Accordion("Look", open=True):
                            cmap = gr.Radio(LOOKS, value="ember", label="Colors")
                            lo = gr.Slider(0, 20, value=1, step=0.5, label="Black point (percentile)")
                            hi = gr.Slider(80, 100, value=99.5, step=0.1, label="White point (percentile)")
                            gamma = gr.Slider(0.4, 2.5, value=1.0, step=0.05, label="Gamma")
                            alpha = gr.Slider(0.1, 1.0, value=0.75, step=0.05, label="Overlay strength")
                            reset = gr.Button("Reset look", size="sm")
                    with gr.Column(scale=3, min_width=360):
                        main = gr.Image(label="Whole surface", type="pil", format="webp", interactive=False,
                                        height=760, elem_id="ia-main", buttons=["fullscreen", "download"])
                        leg = gr.HTML(legend("ember", "map"))
                    with gr.Column(scale=2, min_width=320):
                        loupe = gr.ImageSlider(label="Loupe at full resolution: CT left, map right", type="pil",
                                               format="webp", max_height=520, slider_position=50,
                                               buttons=["fullscreen", "download"])
                        info = gr.HTML()
            with gr.Tab("Compare models", id="compare") as cmp_tab:
                with gr.Row(equal_height=False):
                    with gr.Column(scale=1, min_width=260, elem_classes="ia-panel"):
                        chead = gr.Markdown(elem_classes="ia-chead")
                        csize = gr.Radio([("256", 256), ("512", 512), ("768", 768), ("1024", 1024)], value=512,
                                         label="Box size (pixels)")
                        corder = gr.Radio(ORDER_CHOICES, value="forward", label="Depth order")
                        cwin = gr.Radio(WINDOW_CHOICES, value="c+0", label="Depth window")
                        ccmap = gr.Radio(LOOKS, value="ember", label="Colors")
                    with gr.Column(scale=3, min_width=360):
                        cgrid = gr.Image(label="Every model on the same box", show_label=False, type="filepath",
                                         format="png", interactive=False, height=880,
                                         buttons=["fullscreen", "download"])
                        ctable = gr.HTML()
            with gr.Tab("The atlas", id="atlas"):
                gr.HTML(overview_html())
                gr.Markdown("### Every surface\nClick one to open it in Explore. Each tile is split: the CT on the "
                            "left, the ensemble on the right.")
                gal = gr.Gallery(gallery_items, columns=6, height="auto", object_fit="cover", allow_preview=False,
                                 show_label=False, elem_classes="ia-gallery")
                gr.Markdown("### The models")
                gr.HTML(models_html())
                gr.Markdown(HOW_IT_WAS_MADE, elem_classes="ia-prose")
            with gr.Tab("How to read it", id="howto"):
                gr.Markdown(HOW_TO, elem_classes="ia-prose")
            with gr.Tab("Agents and API", id="agents"):
                gr.Markdown(AGENTS.format(host=host, space=SPACE), elem_classes="ia-prose")
                with gr.Accordion("Connect your tool: the data by URL", open=True):
                    gr.HTML(CONNECT_HTML.read_text() if CONNECT_HTML.exists() else "")
        gr.HTML('<footer class="ia-credit">Made by <a href="https://github.com/ChaseHendrick">Chase Hendrick</a> with '
                'Ink Lens · scans: <a href="https://scrollprize.org/data">Vesuvius Challenge</a> open data · meshes: '
                'ketchupbyheinz · models: their authors (MIT) · data '
                f'<a href="{A.DATASET_URL}">CC BY-NC 4.0</a> · Ink Atlas {VERSION} · model output, not a reading'
                '</footer>')

        # hidden: the API endpoints and MCP tools for scripts and agents
        with gr.Row(visible=False):
            t_sid, t_scroll, t_layer, t_window, t_order, t_cmap, t_mode = (
                gr.Textbox(v, label=k) for k, v in (("surface_id", None), ("scroll", ""), ("layer", "ensemble"),
                                                     ("window", "c+0"), ("order", ""), ("colormap", "gray"),
                                                     ("mode", "map")))
            n_x, n_y = gr.Number(-1, label="x"), gr.Number(-1, label="y")
            n_size, n_box = gr.Number(0, precision=0, label="size"), gr.Number(512, precision=0, label="size")
            o_json, o_img = gr.JSON(), gr.Image(type="filepath", format="png")
            api_b = [gr.Button() for _ in range(6)]

        hidden = dict(api_visibility="private")
        look = [surface, layer, window, order, view, cmap, lo, hi, gamma, alpha, pt, lsize]
        outs = [main, loupe, leg, info]
        g_render = guard(render)
        scroll.input(guard(on_scroll), scroll, surface, **hidden)
        surface.change(guard(on_surface), [surface, layer], [layer, order, pt], **hidden).then(
            g_render, look, outs, **hidden)
        for c in (layer, window, order, view, cmap, lsize):
            c.input(g_render, look, outs, **hidden)
        for c in (lo, hi, gamma, alpha):
            c.release(g_render, look, outs, **hidden)
        main.select(guard(on_click), surface, pt, **hidden).then(g_render, look, outs, **hidden)
        reset.click(lambda: ("ember", 1, 99.5, 1.0, 0.75), None, [cmap, lo, hi, gamma, alpha], **hidden).then(
            g_render, look, outs, **hidden)
        prev_b.click(guard(lambda s: step(s, -1)), surface, [scroll, surface], **hidden)
        next_b.click(guard(lambda s: step(s, 1)), surface, [scroll, surface], **hidden)
        rand_b.click(guard(lambda s: step(s, 0)), surface, [scroll, surface], **hidden)
        gal.select(guard(on_gallery), None, [scroll, surface, tabs], **hidden)
        cins = [surface, pt, csize, corder, cwin, ccmap]
        couts = [cgrid, ctable, chead]
        g_cmp = guard(on_compare)
        cmp_tab.select(lambda o, w, c: (o, w, c), [order, window, cmap], [corder, cwin, ccmap], **hidden).then(
            g_cmp, cins, couts, **hidden)
        for c in (csize, corder, cwin, ccmap):
            c.input(g_cmp, cins, couts, **hidden)
        demo.load(guard(on_load), None, [scroll, surface, layer, order, pt, tabs], **hidden).then(
            g_render, look, outs, **hidden)

        for btn, fn, i, o in ((api_b[0], atlas_summary, [], o_json),
                              (api_b[1], list_scrolls, [], o_json),
                              (api_b[2], list_surfaces, [t_scroll], o_json),
                              (api_b[3], surface_info, [t_sid], o_json),
                              (api_b[4], get_map, [t_sid, t_layer, t_window, t_order, n_x, n_y, n_size, t_cmap,
                                                   t_mode], [o_img, o_json]),
                              (api_b[5], compare_models, [t_sid, n_x, n_y, n_box, t_order, t_window],
                               [o_img, o_json])):
            btn.click(guard(fn), i, o, api_name=fn.__name__, api_description=fn.__doc__.split("\n\n")[0])
    return demo


def fix_mcp_multiple_outputs():
    """Gradio 6.28's MCP server joins a queued tool's several outputs into one text; hand them over one by one, so
    get_map's picture reaches an agent as a picture (as Fiber Checker and Lasagna Fields do)."""
    try:
        from gradio.mcp import GradioMCPServer
        from anyio.to_thread import run_sync
    except ImportError:
        return

    async def without_progress(self, job):
        result = await run_sync(job.result)
        return list(result) if isinstance(result, tuple) else [result]

    GradioMCPServer._execute_tool_without_progress = without_progress


def launch_kwargs():
    A.OUT.mkdir(parents=True, exist_ok=True)
    return dict(theme=theme(), css=CSS, head=page_head(), footer_links=["api", "gradio"], mcp_server=True,
                allowed_paths=[str(A.OUT)], ssr_mode=False)


if __name__ == "__main__":
    fix_mcp_multiple_outputs()
    build_demo().queue(max_size=64, default_concurrency_limit=8).launch(**launch_kwargs())
