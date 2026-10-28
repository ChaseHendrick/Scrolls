"""AFV Fibers: papyrus fiber curves for six whole Herculaneum scans, made with Qual's AFV V2 model and spline
generator, to download, stream by box, or open in VC3D; and a catalog of every public fiber set we know of.

The web page and the API. The guide to the six scans is guide/index.html, shown in the first tab; reading the fibers
and CT around a point is fibers.py. Runs on a free CPU Space: nothing here runs a model, it reads the published
files.
  python3 app.py            serve the page (on a Space, or on any computer)
"""
import functools
import json
import os
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
import fibers as F  # noqa: E402
from fibers import FiberError  # noqa: E402

VERSION = "1.0.0"
OUT = Path(tempfile.gettempdir()) / "afv-fibers-out"
GUIDE = HERE / "guide" / "index.html"
CATALOG = HERE / "catalog.json"
CONNECT_HTML = HERE / "connect.html"
EXAMPLES = json.loads((HERE / "examples.json").read_text()) if (HERE / "examples.json").exists() else []


def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)


# ---------------------------------------------------------------- the API (also the page's buttons)

def list_scans():
    """The six scans with AFV fibers: each scan's dataset, CT volume, the CT level the model ran on, its voxel size
    in um, and the whole-scan files."""
    out = []
    for scan, s in F.SCANS.items():
        out.append({"scan": scan, "name": s.get("name", ""), "dataset": f"https://huggingface.co/datasets/{s['repo']}",
                    "volume": s["volume"], "volume_id": s["volume_id"], "model_level": s["level"],
                    "level0_um": s["um"], "files": {"all": F.dataset_url(scan, f"{scan}_afv_v2.afv"),
                                                    "1mm": F.dataset_url(scan, f"{scan}_afv_v2_1mm.afv"),
                                                    "tiles_index": F.dataset_url(scan, "tiles/index.json")}})
    return out


def example_points():
    """Points worth a first look on each scan (dense papyrus at mid-height), as scan, z, y, x in level-0 voxels."""
    return EXAMPLES


def fibers_box(scan, z, y, x, half=128):
    """Every fiber touching a box around a point: scan name (PHerc0139 ...), z, y, x in level-0 voxels, half the box
    edge in voxels of the grid the model ran on (16 to 256). Returns counts by family (V vertical, H horizontal), the
    tiles read, and each fiber's id, family and length in mm."""
    box = F.box_l0(scan, z, y, x, half)
    fib, tiles = F.fibers_in_box(scan, box)
    um = F.SCANS[scan]["um"]
    rows = []
    for fid, (fam, p) in sorted(fib.items()):
        L = float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum()) * um / 1000
        rows.append({"id": int(fid), "family": fam, "points": int(len(p)), "length_mm": round(L, 3)})
    return {"scan": scan, "box_zyx_level0": box, "tiles": tiles,
            "counts": {k: sum(r["family"] == k for r in rows) for k in ("V", "H")}, "fibers": rows}


def look(scan, z, y, x, half=128, axis="z"):
    """A picture of a box: the CT plane through the point (axis z: an axial slice, y: a vertical section) with the
    fibers near it drawn over (V orange, H cyan), a 3D view of every fiber in the box, and the box's fibers as a small
    .afv file. Arguments as fibers_box."""
    box = F.box_l0(scan, z, y, x, half)
    fib, tiles = F.fibers_in_box(scan, box)
    at = int(z) if axis == "z" else int(y)
    img = F.render_slice(scan, axis, at, box, fib)
    fig = F.plot3d(scan, box, fib)
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{scan}_z{int(z)}_y{int(y)}_x{int(x)}_h{int(half)}.afv"
    n = F.write_box_afv(scan, box, dest) if fib else 0
    counts = {k: sum(f == k for f, _ in fib.values()) for k in ("V", "H")}
    info = {"scan": scan, "box_zyx_level0": box, "tiles": tiles, "counts": counts, "file_fibers": n}
    return img, fig, (str(dest) if n else None), info


# ---------------------------------------------------------------- page text

def catalog_html():
    cat = json.loads(CATALOG.read_text())
    rows = []
    for e in cat["sets"]:
        links = " · ".join(f'<a href="{u}" target="_blank" rel="noopener">{k}</a>' for k, u in e["links"].items())
        rows.append(f"<tr><td><b>{e['scan']}</b><span>{e.get('scan_note', '')}</span></td><td>{e['what']}</td>"
                    f"<td>{e['by']}</td><td>{e['format']}</td><td>{links}</td></tr>")
    tools = "".join(f'<li><a href="{t["url"]}" target="_blank" rel="noopener">{t["name"]}</a>: {t["what"]}</li>'
                    for t in cat["tools"])
    return (f'<div class="af-cat"><p>{cat["intro"]}</p><div class="af-tbl"><table><thead><tr><th>Scan</th><th>What</th><th>By</th>'
            f'<th>Format</th><th>Get it</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
            f'<h3>Models and tools</h3><ul>{tools}</ul><p class="af-note">{cat["note"]}</p></div>')


def guide_html():
    if not GUIDE.exists():
        return "<p>The guide is being built.</p>"
    import html
    return (f'<div class="af-guide"><iframe srcdoc="{html.escape(GUIDE.read_text(), quote=True)}" '
            'title="AFV Fibers guide" loading="eager"></iframe></div>')


HOWTO = """
### Download a whole scan

```bash
hf download SharpMeow/pherc0139-afv-fibers --repo-type dataset --include "PHerc0139_afv_v2_1mm.afv" --local-dir .
```

Each scan's dataset holds `SCAN_afv_v2.afv` (every traced fiber), `SCAN_afv_v2_1mm.afv` (fibers 1 mm and longer, the
set most people want) and `tiles/` (one small `.afv` per 1024-voxel cell of the model's grid; `tiles/index.json`
gives each cell's box in level-0 voxels).

### Read fibers in Python (sqlite3 and NumPy only)

An `.afv` is a read-only SQLite file: `fibers` (family V or H, length, bounds), `blocks` (XYZ float64 points, up to
257 per block, consecutive blocks sharing one point) and an R-tree `block_bounds` to find blocks by box.

```python
import sqlite3, numpy as np
db = sqlite3.connect("file:PHerc0139_afv_v2_1mm.afv?mode=ro", uri=True)
x0, x1, y0, y1, z0, z1 = 3000, 3256, 3000, 3256, 10000, 10256          # level-0 voxels
ids = [r[0] for r in db.execute(
    "SELECT DISTINCT b.fiber_id FROM block_bounds r JOIN blocks b ON b.id = r.id "
    "WHERE r.max_x >= ? AND r.min_x < ? AND r.max_y >= ? AND r.min_y < ? AND r.max_z >= ? AND r.min_z < ?",
    (x0, x1, y0, y1, z0, z1))]
for fid in ids[:3]:
    blocks = [np.frombuffer(b, "<f8").reshape(-1, 3) for (b,) in
              db.execute("SELECT points FROM blocks WHERE fiber_id = ? ORDER BY first_segment", (fid,))]
    pts = np.concatenate([blocks[0]] + [b[1:] for b in blocks[1:]])
    print(fid, db.execute("SELECT family, length FROM fibers WHERE id = ?", (fid,)).fetchone(), pts.shape)
```

Every dataset also carries `load_example.py`, the same thing as a script.

### Open in VC3D

VC3D keeps fibers in an object store. villa's `vc_object_store/scripts/import_afv.py` turns an `.afv` into one; it
needs the volume id (the number at the start of the volume name, listed on each dataset card):

```bash
PYTHONPATH=build/python python3 vc_object_store/scripts/import_afv.py PHerc0139_afv_v2_1mm.afv pherc0139-fibers.vcobj \\
    --volume-id 20250728140407
```

Then attach `pherc0139-fibers.vcobj` from VC3D's File → Object Store menu with that volume open (its catalog id must
match; the script's notes say how for a local cache). All files are in native level-0 voxels with scale factor 1, the frame that importer accepts; each one was checked
with that importer's own reader before upload.

### From code or an agent

The **Agents and API** tab lists the endpoints (`list_scans`, `example_points`, `fibers_box`, `look`). This page is
also an MCP server.
"""

AGENTS = """
**Endpoints** (Gradio API, also MCP tools at `{host}/gradio_api/mcp/`):

- `list_scans()`: the six scans, their datasets and whole-scan file URLs.
- `example_points()`: a dense point per scan to start from.
- `fibers_box(scan, z, y, x, half)`: every fiber touching a box: ids, families, lengths.
- `look(scan, z, y, x, half, axis)`: the CT plane with fibers over it, a 3D view and the box as a small `.afv`.

```python
from gradio_client import Client
c = Client("SharpMeow/afv-fibers")
print(c.predict(api_name="/list_scans"))
print(c.predict("PHerc0139", 10000, 3200, 3200, 64, api_name="/fibers_box")["counts"])
```
"""


# ---------------------------------------------------------------- the page

CSS = """
:root, .dark { --af-v:#ff8a3d; --af-h:#3ad1ff; }
.gradio-container { width:100% !important; max-width:1600px !important; margin:0 auto !important; }
.af-head { display:flex; align-items:center; gap:14px; padding:6px 2px 2px; }
.af-head .mark { width:30px; height:30px; border-radius:7px; flex:none; background:
  repeating-linear-gradient(90deg, rgba(255,138,61,.85) 0 2px, transparent 2px 7px),
  repeating-linear-gradient(0deg, rgba(58,209,255,.85) 0 2px, transparent 2px 7px), #0b1220; }
.af-head h1 { white-space:nowrap; font-family:Fraunces, Georgia, serif; font-weight:650; font-size:30px; margin:0; }
.af-head span { color:var(--body-text-color-subdued); font-size:15px; }
/* no fixed height: onescroll.html fits the guide's frame to the guide, so the page scrolls and the frame does not */
.af-guide iframe { width:100%; height:1400px; border:0; border-radius:12px; background:#0b0f17; display:block; }
/* a phone scrolls the catalog sideways inside its box rather than cutting off the last columns */
.af-cat .af-tbl { overflow-x:auto; }
.af-cat table { width:100%; border-collapse:collapse; font-size:14.5px; }
.af-cat th, .af-cat td { text-align:left; vertical-align:top; padding:9px 10px;
  border-bottom:1px solid var(--border-color-primary); }
.af-cat td span { display:block; font-size:12.5px; color:var(--body-text-color-subdued); }
.af-note { font-size:13px; color:var(--body-text-color-subdued); }
.af-legend { font-size:13px; color:var(--body-text-color-subdued); }
.af-legend i { display:inline-block; width:22px; height:4px; border-radius:2px; margin:0 6px 3px 12px; }
.af-howto { max-width:1000px; margin:0 auto !important; }
.af-credit { text-align:center; font-size:13px; color:var(--body-text-color-subdued); padding:18px 0 6px; }
@media (max-width: 640px) {
  .af-head h1 { font-size:24px; } .af-head span { display:none; }
  .af-cat table { font-size:13px; }
}
"""

HEAD = """
<meta name="description" content="AFV Fibers: papyrus fiber curves for six whole Herculaneum scans (Qual's AFV V2
model), to download, stream by box or open in VC3D, plus a catalog of public fiber sets. Model output, not a reading.">
<meta property="og:title" content="AFV Fibers">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,650&display=swap" rel="stylesheet">
"""
# one page scroll bar: fits the guide's frame to its content (written by python -m kit spaceconnect render)
ONESCROLL = HERE / "onescroll.html"
HEAD += ONESCROLL.read_text() if ONESCROLL.is_file() else ""

TAB_JS = """
() => {
  const pick = (name) => {
    // by label: on a phone the later tabs sit in Gradio's overflow menu, as buttons without role="tab"
    const labels = {scans: 'Six scans', look: 'Explore a box', catalog: 'Catalog', howto: 'How-to guides',
                    agents: 'Agents and API'};
    const btns = [...document.querySelectorAll('#af-tabs button')].filter((b) => b.textContent.trim() === labels[name]);
    const btn = btns.find((b) => b.getAttribute('role') === 'tab') || btns[btns.length - 1];
    if (btn) btn.click();
  };
  window.addEventListener('message', (e) => { if (e.data && e.data.afTab) pick(e.data.afTab); });
  const q = new URLSearchParams(window.location.search).get('tab');
  if (q) setTimeout(() => pick(q), 300);
}
"""


def theme():
    import gradio as gr
    t = gr.themes.Base(primary_hue="orange", neutral_hue="slate", radius_size="md",
                       font=(gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"),
                       font_mono=(gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"))
    return t.set(body_background_fill="#f4f6f9", body_background_fill_dark="#0b0f17",
                 block_background_fill="#ffffff", block_background_fill_dark="#121826",
                 button_primary_background_fill="#e8742a", button_primary_background_fill_dark="#ff8a3d",
                 button_primary_background_fill_hover="#cf6220", button_primary_background_fill_hover_dark="#ffa264")


def build_demo():
    import gradio as gr

    def guard(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except FiberError as exc:
                raise gr.Error(str(exc)) from None
            except gr.Error:
                raise
            except Exception as exc:          # anything else: say what failed, keep the page alive
                log(f"error: {type(exc).__name__}: {exc}")
                raise gr.Error(f"{type(exc).__name__}: {exc}") from None
        return wrapped

    # the Explore tab opens on the first example already drawn, not on empty panels
    e0 = EXAMPLES[0] if EXAMPLES else {}
    first = (None, None, None, None)
    if e0:
        try:
            first = look(e0["scan"], e0["z"], e0["y"], e0["x"])
        except Exception as exc:  # noqa: BLE001 (the page still starts; the panels are just empty)
            log(f"first example not drawn: {type(exc).__name__}: {exc}")

    with gr.Blocks(title="AFV Fibers") as demo:
        host = os.environ.get("SPACE_HOST") and f"https://{os.environ['SPACE_HOST']}" or "http://localhost:7860"
        gr.HTML('<div class="af-head"><div class="mark"></div><h1>AFV Fibers</h1><span>papyrus fiber curves for '
                'six whole scans, made with Qual\'s AFV V2, plus every public fiber set we know of</span></div>')
        with gr.Tabs(elem_id="af-tabs"):
            with gr.Tab("Six scans", id="scans"):
                gr.HTML(guide_html())
            with gr.Tab("Explore a box", id="look"):
                with gr.Row():
                    with gr.Column(scale=1, min_width=300):
                        ex = gr.Dropdown([e["label"] for e in EXAMPLES], label="Start from", value=e0.get("label"))
                        scan = gr.Dropdown(list(F.SCANS), value=e0.get("scan", "PHerc0139"), label="Scan")
                        with gr.Row():
                            z = gr.Number(e0.get("z", 10000), precision=0, label="z")
                            y = gr.Number(e0.get("y", 3200), precision=0, label="y")
                            x = gr.Number(e0.get("x", 3200), precision=0, label="x")
                        gr.Markdown("Level-0 voxels of the scan, as in VC3D.", elem_classes="af-note")
                        half = gr.Slider(32, 256, 128, step=32, label="Half box (voxels of the ~9 um grid)")
                        axis = gr.Radio([("axial slice", "z"), ("vertical section", "y")], value="z", label="Plane")
                        go = gr.Button("Show fibers", variant="primary")
                        dl = gr.File(first[2], label="This box as .afv (open in VC3D or Python)")
                        info = gr.JSON(first[3], label="What was read")
                    with gr.Column(scale=3):
                        gr.HTML('<div class="af-legend"><i style="background:var(--af-v)"></i>vertical fibers'
                                '<i style="background:var(--af-h)"></i>horizontal fibers · the CT is read live from '
                                'the Vesuvius Challenge open data · model output, not a reading</div>')
                        with gr.Row():
                            pic = gr.Image(first[0], label="CT with fibers near the plane", type="pil", format="png")
                            plot = gr.Plot(first[1], label="Every fiber in the box")
            with gr.Tab("Catalog", id="catalog"):
                gr.HTML(catalog_html())
            with gr.Tab("How-to guides", id="howto"):
                gr.Markdown(HOWTO, elem_classes="af-howto")
            with gr.Tab("Agents and API", id="agents"):
                gr.Markdown(AGENTS.format(host=host))
                with gr.Accordion("Connect your tool: the fibers and scans by URL", open=True):
                    gr.HTML(CONNECT_HTML.read_text() if CONNECT_HTML.exists() else "")
        gr.HTML('<footer class="af-credit">Fiber model and spline generator by '
                '<a href="https://huggingface.co/Qualzz20/afv_fiber_9um_v2">Qual</a> (Apache 2.0) · runs and page by '
                '<a href="https://github.com/ChaseHendrick">Chase Hendrick</a> · scans: '
                '<a href="https://scrollprize.org">Vesuvius Challenge</a> open data, CC BY-NC 4.0 · '
                f'AFV Fibers {VERSION} · model output, not a reading</footer>')

        with gr.Row(visible=False):
            a_scan = gr.Textbox(label="scan")
            a_z, a_y, a_x, a_half = (gr.Number(precision=0, label=k) for k in ("z", "y", "x", "half"))
            a_axis = gr.Textbox(label="axis")
            a_json, a_img, a_plot, a_file, a_info = gr.JSON(), gr.Image(type="pil", format="png"), gr.Plot(), \
                gr.File(), gr.JSON()
            a_btns = [gr.Button() for _ in range(4)]

        hidden = dict(api_visibility="private")

        def on_example(label):
            e = next((e for e in EXAMPLES if e["label"] == label), None)
            if not e:
                return gr.update(), gr.update(), gr.update(), gr.update()
            return e["scan"], e["z"], e["y"], e["x"]
        show = guard(lambda s, z_, y_, x_, h, a: (lambda r: (r[0], r[1], r[2], r[3]))(look(s, z_, y_, x_, h, a)))
        ex.input(on_example, ex, [scan, z, y, x], **hidden).then(
            show, [scan, z, y, x, half, axis], [pic, plot, dl, info], concurrency_id="look", **hidden)
        go.click(show, [scan, z, y, x, half, axis], [pic, plot, dl, info], concurrency_id="look", concurrency_limit=4,
                 **hidden)
        for btn, fn, i, o, name in ((a_btns[0], list_scans, [], a_json, "list_scans"),
                                    (a_btns[1], example_points, [], a_json, "example_points"),
                                    (a_btns[2], fibers_box, [a_scan, a_z, a_y, a_x, a_half], a_json, "fibers_box"),
                                    (a_btns[3], look, [a_scan, a_z, a_y, a_x, a_half, a_axis],
                                     [a_img, a_plot, a_file, a_info], "look")):
            btn.click(guard(fn), i, o, api_name=name, api_description=fn.__doc__.split("\n\n")[0],
                      concurrency_id="look" if name == "look" else None, concurrency_limit=4)
        demo.load(None, None, None, js=TAB_JS)
    return demo


def fix_mcp_multiple_outputs():
    """Gradio 6.28's MCP server joins a queued tool's several outputs into one text; hand them over one by one (as
    Lasagna Fields and Fiber Checker do)."""
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
    return dict(theme=theme(), css=CSS, head=HEAD, footer_links=["api", "gradio"], mcp_server=True,
                allowed_paths=[str(OUT)])


if __name__ == "__main__":
    fix_mcp_multiple_outputs()
    build_demo().queue(max_size=64, default_concurrency_limit=8).launch(**launch_kwargs())
