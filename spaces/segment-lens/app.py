"""Segment Lens on Hugging Face: the 3D page (index.html, app.js) at /, and the same atlas for AI agents and scripts
at /agents, as API endpoints (gradio_client) and MCP tools (/agents/gradio_api/mcp/).

Everything comes from the Segment Atlas dataset (SharpMeow/vesuvius-segment-atlas): atlas.jsonl, one row per
published tifxyz mesh, and lens/*.slg.gz, the decimated previews (format: "Lens files" in docs/tools/atlas.md of
ChaseHendrick/Scrolls). Nothing is written and no scan data is read. Previews exist only for scrolls on no prize
list, as on the page.

  python3 app.py            # serves on port 7860 (SEGMENT_LENS_DATA=URL/ reads another copy of the atlas)
"""

import functools
import gzip
import io
import json
import math
import os
import struct
import threading
import time
import urllib.request
from collections import OrderedDict
from pathlib import Path

VERSION = "1.1.0"
HERE = Path(__file__).resolve().parent
DATA = os.environ.get("SEGMENT_LENS_DATA",
                      "https://huggingface.co/datasets/SharpMeow/vesuvius-segment-atlas/resolve/main/")
S3 = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/"
MAGIC = b"SLG1"
ATLAS_TTL_S = 3600
LENS_CACHE = 32
SORTS = ("area_cm2", "filled_share", "within_10pct", "holes_mm2", "folds_mm2", "stretched_mm2", "grid_h", "segment")
# the page's colors (app.js COLORS), as 0-255 RGB: plain, hole, fold, stretched
COLORS = {"base": (204, 214, 219), "hole": (89, 166, 255), "fold": (255, 92, 92), "str": (255, 166, 51)}
WEB_FILES = ("index.html", "app.js", "style.css", "connect.html", "connect.json", "CONNECT.md", "onescroll.html")
SUMMARY_KEYS = ("id", "scroll", "segment", "mesh", "kind", "volume", "voxel_um", "area_cm2", "filled_share",
                "within_10pct", "holes_mm2", "folds_mm2", "stretched_mm2", "clean", "prize_lists")


class LensError(ValueError):
    """A refusal an agent can act on: unknown id, no preview, bad argument."""


# ---------------------------------------------------------------- data

def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": f"segment-lens/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


_atlas = {"rows": None, "at": 0.0}
_atlas_lock = threading.Lock()


def atlas_rows(get=_get):
    """The atlas rows, fetched at most once an hour."""
    with _atlas_lock:
        if _atlas["rows"] is None or time.time() - _atlas["at"] > ATLAS_TTL_S:
            text = get(DATA + "atlas.jsonl").decode("utf-8")
            _atlas["rows"] = [json.loads(line) for line in text.splitlines() if line.strip()]
            _atlas["at"] = time.time()
        return _atlas["rows"]


def find_row(segment_id, rows=None):
    rows = atlas_rows() if rows is None else rows
    segment_id = (segment_id or "").strip()
    for r in rows:
        if r["id"] == segment_id:
            return r
    raise LensError(f"no mesh with id {segment_id!r}; list_segments gives the ids")


def parse_lens(blob):
    """(h, w, k, xyz (h, w, 3) float64 with NaN for missing nodes, flags (h, w) uint8) from lens bytes: the reader
    of kit.atlas.read_lens and the page's parseLens."""
    import numpy as np
    raw = gzip.decompress(blob)
    if raw[:4] != MAGIC:
        raise LensError("not a Segment Lens grid (bad magic)")
    h, w, k = struct.unpack("<HHH", raw[4:10])
    v = struct.unpack("<6f", raw[10:34])
    lo, hi = np.array(v[:3]), np.array(v[3:])
    n = h * w
    if len(raw) != 34 + 7 * n:
        raise LensError("Segment Lens grid has the wrong length")
    q = np.frombuffer(raw, "<u2", 3 * n, 34).reshape(3, h, w)
    flags = np.frombuffer(raw, np.uint8, n, 34 + 6 * n).reshape(h, w)
    span = np.where(hi - lo > 0, hi - lo, 1.0)
    xyz = np.stack([lo[i] + q[i] / 65534.0 * span[i] for i in range(3)], -1)
    xyz[q[0] == 65535] = np.nan
    return h, w, k, xyz, flags


_lens = OrderedDict()
_lens_lock = threading.Lock()


def load_lens(row, get=_get):
    if not row.get("lens"):
        why = ("its scroll is on a prize list, so it has numbers but no preview (public media rule)"
               if row.get("prize_lists") else "it was not measured or has no filled nodes")
        raise LensError(f"{row['id']} has no preview: {why}")
    with _lens_lock:
        if row["lens"] in _lens:
            _lens.move_to_end(row["lens"])
            return _lens[row["lens"]]
    g = parse_lens(get(DATA + "lens/" + row["lens"]))
    with _lens_lock:
        _lens[row["lens"]] = g
        while len(_lens) > LENS_CACHE:
            _lens.popitem(last=False)
    return g


def flag_counts(flags):
    f = flags.ravel()
    return {"nodes": int(f.size), "hole": int(((f & 1) > 0).sum()), "fold": int(((f & 2) > 0).sum()),
            "stretched": int(((f & 4) > 0).sum())}


def node_colors(flags):
    """One RGB per preview node, with the page's precedence: fold over stretched over hole over plain."""
    import numpy as np
    c = np.empty(flags.shape + (3,), np.uint8)
    c[:] = COLORS["base"]
    c[(flags & 1) > 0] = COLORS["hole"]
    c[(flags & 4) > 0] = COLORS["str"]
    c[(flags & 2) > 0] = COLORS["fold"]
    return c


# ---------------------------------------------------------------- pictures

def render_grid(flags, xyz, size=512):
    """The preview grid flat (rows down, columns across), each node colored by its flag; missing nodes black."""
    import numpy as np
    from PIL import Image
    c = node_colors(flags)
    c[np.isnan(xyz[..., 0])] = (12, 16, 20)
    h, w = flags.shape
    s = max(1, size // max(h, w))
    return Image.fromarray(np.repeat(np.repeat(c, s, 0), s, 1))


def render_3d(flags, xyz, azimuth=30.0, elevation=20.0, size=512):
    """An orthographic picture of the surface from (azimuth, elevation) degrees, the scan's z up: each grid cell
    filled as two triangles' worth of points, shaded by its facing, colored by flag; nearest wins."""
    import numpy as np
    from PIL import Image
    ok = ~np.isnan(xyz[..., 0])
    if ok.sum() < 4:
        raise LensError("the preview has too few nodes to draw")
    # x, y across, z up (the page rotates the same way)
    p = xyz[..., [0, 1, 2]].copy()
    center = np.nanmean(p[ok], 0)
    p -= center
    scale = np.nanmax(np.abs(p[ok])) or 1.0
    p /= scale
    a, e = math.radians(azimuth), math.radians(elevation)
    right = np.array([math.cos(a), math.sin(a), 0.0])
    view = np.array([-math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)])
    up = np.cross(right, view)
    # normals from the grid's neighbors, for shading
    dy = np.gradient(np.nan_to_num(p), axis=0)
    dx = np.gradient(np.nan_to_num(p), axis=1)
    nrm = np.cross(dx, dy)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True) + 1e-9
    light = np.abs(nrm @ view) * 0.75 + 0.25
    # densify: 4 x 4 samples per cell, bilinear between the cell's corners
    h, w = flags.shape
    t = np.linspace(0, 1, 4, endpoint=False)
    rr, cc = np.meshgrid(t, t, indexing="ij")
    P00, P01, P10, P11 = p[:-1, :-1], p[:-1, 1:], p[1:, :-1], p[1:, 1:]
    cell_ok = ok[:-1, :-1] & ok[:-1, 1:] & ok[1:, :-1] & ok[1:, 1:]
    pts = (P00[..., None, None, :] * ((1 - rr) * (1 - cc))[..., None] + P01[..., None, None, :] * ((1 - rr) * cc)[..., None]
           + P10[..., None, None, :] * (rr * (1 - cc))[..., None] + P11[..., None, None, :] * (rr * cc)[..., None])
    pts = pts[cell_ok].reshape(-1, 3)
    col = (node_colors(flags)[:-1, :-1][cell_ok].astype(np.float32) * light[:-1, :-1][cell_ok][:, None])
    col = np.repeat(col, 16, 0)
    u = pts @ right
    v = pts @ up
    d = pts @ view
    half = size / 2 * 0.92
    px = np.clip((u * half + size / 2).astype(int), 0, size - 1)
    py = np.clip((size / 2 - v * half).astype(int), 0, size - 1)
    order = np.argsort(d)  # far first, near last, so near overwrite
    img = np.full((size, size, 3), (5, 8, 11), np.uint8)
    img[py[order], px[order]] = np.clip(col[order], 0, 255).astype(np.uint8)
    return Image.fromarray(img)


# ---------------------------------------------------------------- tools

def page_url(segment_id=""):
    host = os.environ.get("SPACE_HOST")
    base = f"https://{host}/" if host else "/"
    return base + (f"#id={segment_id}" if segment_id else "")


def kit_command(row):
    return f"python -m kit tifxyz check {row['url'].replace(S3, 's3://vesuvius-challenge-open-data/')} --png check.png"


def summary(row):
    out = {k: row.get(k) for k in SUMMARY_KEYS}
    out["has_preview"] = bool(row.get("lens"))
    return out


def list_scrolls():
    """Every scroll in the Segment Atlas, with how many top-level meshes it has, how many have a 3D preview, and
    their total area.

    Returns:
        JSON: scrolls (scroll, meshes, previews, area_cm2, prize_lists), total_meshes, version, open_in_browser.
    """
    rows = [r for r in atlas_rows() if r.get("kind") == "mesh"]
    by = {}
    for r in rows:
        s = by.setdefault(r["scroll"], {"scroll": r["scroll"], "meshes": 0, "previews": 0, "area_cm2": 0.0,
                                        "prize_lists": sorted(set(r.get("prize_lists") or []))})
        s["meshes"] += 1
        s["previews"] += bool(r.get("lens"))
        s["area_cm2"] = round(s["area_cm2"] + (r.get("area_cm2") or 0.0), 3)
    return {"scrolls": sorted(by.values(), key=lambda s: s["scroll"]), "total_meshes": len(rows),
            "version": VERSION, "open_in_browser": page_url()}


def list_segments(scroll: str = "", sort: str = "area_cm2", top: int = 50, previews_only: bool = False):
    """The measured meshes of one scroll (or all scrolls), largest first by default: each mesh's id, area, filled
    share, isometry (share of edges within 10 percent) and the area of its holes, folds and stretched cells.

    Args:
        scroll: a scroll name as list_scrolls gives it, such as PHerc0139; empty for every scroll.
        sort: one of area_cm2, filled_share, within_10pct, holes_mm2, folds_mm2, stretched_mm2, grid_h, segment.
            Numbers sort largest first, segment names A to Z.
        top: how many rows to return, 1 to 500.
        previews_only: only meshes with a 3D preview (scrolls on no prize list).

    Returns:
        JSON: segments (one summary per mesh, with has_preview), count (before the top cut), and the call's settings.
    """
    if sort not in SORTS:
        raise LensError(f"sort must be one of {', '.join(SORTS)}")
    top = int(top)
    if not 1 <= top <= 500:
        raise LensError("top must be 1 to 500")
    scroll = (scroll or "").strip()
    rows = [r for r in atlas_rows() if r.get("kind") == "mesh" and (not scroll or r["scroll"] == scroll)]
    if scroll and not rows:
        raise LensError(f"no meshes for scroll {scroll!r}; list_scrolls gives the names")
    if previews_only:
        rows = [r for r in rows if r.get("lens")]
    if sort == "segment":
        rows = sorted(rows, key=lambda r: r["segment"])
    else:
        rows = sorted(rows, key=lambda r: -(r.get(sort) if r.get(sort) is not None else -math.inf))
    return {"segments": [summary(r) for r in rows[:top]], "count": len(rows), "scroll": scroll or None,
            "sort": sort, "top": top}


def get_segment(segment_id: str):
    """Everything the Segment Atlas knows about one mesh: its open-data folder, grid size, area, isometry,
    holes, folds and stretched cells (nodes and mm2), z range, the kit command that reproduces the numbers, and,
    when it has a preview, the preview's flag counts.

    Args:
        segment_id: the mesh's id, as list_segments gives it (SCROLL/SEGMENT/MESH).

    Returns:
        JSON: the atlas row, plus kit_command, preview (grid size and flag counts, or why there is none) and
        open_in_browser.
    """
    row = find_row(segment_id)
    out = dict(row)
    out["kit_command"] = kit_command(row) if row.get("url") else None
    try:
        h, w, k, xyz, flags = load_lens(row)
        out["preview"] = {"grid_w": w, "grid_h": h, "every_kth_node": k, "flags": flag_counts(flags)}
    except LensError as exc:
        out["preview"] = {"none": str(exc)}
    out["open_in_browser"] = page_url(row["id"])
    return out


def segment_picture(segment_id: str, view: str = "3d", azimuth: float = 30.0, elevation: float = 20.0):
    """A picture of one mesh's preview with its flags painted on, as on the page: holes blue, folds red,
    stretched cells orange, plain gray. Geometry only: no CT, no ink, and a clean surface is not proof the trace
    stays on one sheet. Only meshes with a preview (scrolls on no prize list) can be drawn.

    Args:
        segment_id: the mesh's id, as list_segments gives it.
        view: "3d" for the surface seen from azimuth and elevation (the scan's z up), or "grid" for the flat grid.
        azimuth: degrees around the scan's z axis, for view 3d.
        elevation: degrees above the horizontal, -90 to 90, for view 3d.

    Returns:
        A PNG picture, and JSON: id, view, grid size, every_kth_node, flag counts, open_in_browser.
    """
    if view not in ("3d", "grid"):
        raise LensError('view must be "3d" or "grid"')
    if not -90 <= float(elevation) <= 90:
        raise LensError("elevation must be -90 to 90")
    row = find_row(segment_id)
    h, w, k, xyz, flags = load_lens(row)
    img = render_grid(flags, xyz) if view == "grid" else render_3d(flags, xyz, float(azimuth), float(elevation))
    info = {"id": row["id"], "view": view, "grid_w": w, "grid_h": h, "every_kth_node": k,
            "flags": flag_counts(flags), "open_in_browser": page_url(row["id"])}
    if view == "3d":
        info.update(azimuth=float(azimuth), elevation=float(elevation))
    return img, info


# ---------------------------------------------------------------- app

AGENTS_TEXT = """\
# Segment Lens for agents and scripts

The same Segment Atlas the [3D page](/) shows, as API endpoints and MCP tools. Every answer that names a mesh
includes `open_in_browser`, a link that opens it on the page for a person.

- `list_scrolls`: every scroll, its mesh and preview counts and total area.
- `list_segments`: one scroll's meshes (or all), sorted, with area, filled share, isometry and flagged areas.
- `get_segment`: one mesh's full atlas row, the `kit tifxyz check` command and the preview's flag counts.
- `segment_picture`: a picture of one mesh with holes, folds and stretched cells painted on (3D or flat grid).

**MCP**: add the server `{url}/agents/gradio_api/mcp/`.

**Python**:

```python
from gradio_client import Client
c = Client("{url}/agents/")
top = c.predict("PHerc0139", "area_cm2", 5, True, api_name="/list_segments")
seg = c.predict(top["segments"][0]["id"], api_name="/get_segment")
```

Geometry only: no CT, no ink, and nothing here judges whether a segment stays on one sheet. Data: Vesuvius
Challenge open data via the Segment Atlas, CC BY-NC 4.0. Segment Lens {version}.
"""


def fix_mcp_multiple_outputs():
    """Gradio 6.28's MCP server joins a queued tool's several outputs into one text (the same patch as Scroll Lens),
    so segment_picture's image would reach an agent as text. Hand them over one by one."""
    try:
        from gradio.mcp import GradioMCPServer
        from anyio.to_thread import run_sync
    except ImportError:
        return

    async def without_progress(self, job):
        result = await run_sync(job.result)
        return list(result) if isinstance(result, tuple) else [result]

    GradioMCPServer._execute_tool_without_progress = without_progress


def build_demo():
    import gradio as gr

    def guard(fn):
        # functools.wraps keeps the name, docstring and signature, which the API and the MCP tool list come from
        @functools.wraps(fn)
        def run(*a, **kw):
            try:
                return fn(*a, **kw)
            except LensError as exc:
                raise gr.Error(str(exc))
        return run

    url = page_url().rstrip("/") if page_url() != "/" else "https://sharpmeow-segment-lens.hf.space"
    with gr.Blocks(title="Segment Lens for agents") as demo:
        gr.Markdown(AGENTS_TEXT.format(url=url, version=VERSION))
        with gr.Row():
            sc = gr.Textbox(value="", label="scroll")
            so = gr.Dropdown(list(SORTS), value="area_cm2", label="sort")
            tp = gr.Number(value=50, precision=0, label="top")
            pv = gr.Checkbox(value=False, label="previews_only")
        sid = gr.Textbox(value="", label="segment_id")
        with gr.Row():
            vw = gr.Dropdown(["3d", "grid"], value="3d", label="view")
            az = gr.Number(value=30.0, label="azimuth")
            el = gr.Number(value=20.0, label="elevation")
        with gr.Row():
            b1, b2, b3, b4 = (gr.Button(n) for n in ("list_scrolls", "list_segments", "get_segment", "segment_picture"))
        pic = gr.Image(type="pil", label="picture", format="png")
        out = gr.JSON(label="answer")
        b1.click(guard(list_scrolls), None, out, api_name="list_scrolls")
        b2.click(guard(list_segments), [sc, so, tp, pv], out, api_name="list_segments")
        b3.click(guard(get_segment), [sid], out, api_name="get_segment")
        b4.click(guard(segment_picture), [sid, vw, az, el], [pic, out], api_name="segment_picture")
    return demo


def build_app():
    import gradio as gr
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, RedirectResponse

    fix_mcp_multiple_outputs()
    app = FastAPI()
    # ssr_mode=False: on Spaces (GRADIO_SSR_MODE and GRADIO_SERVER_PORT set) server-side rendering starts a
    # Node server on port 7860, so uvicorn could not bind there and the Space stopped at startup
    app = gr.mount_gradio_app(app, build_demo(), path="/agents", mcp_server=True, footer_links=["api"], ssr_mode=False)

    @app.get("/")
    def index():
        return FileResponse(HERE / "index.html")

    def serve(name):
        def f():
            return FileResponse(HERE / name)
        return f

    for name in WEB_FILES:
        app.add_api_route("/" + name, serve(name), methods=["GET"])

    @app.get("/agents")
    def agents():
        return RedirectResponse("/agents/")

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "7860")))
