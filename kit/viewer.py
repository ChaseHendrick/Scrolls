"""One self-contained HTML file that overlays several readers' ink maps on one crop.

No server and no network: every layer is a PNG embedded as a data URI, and a few lines of
inline JavaScript switch layers, set opacity, and read out values under the cursor. Layers:
each reader's map (percentile-ranked inside the mask, so readers on different scales compare),
the disagreement between readers (per-pixel standard deviation of those ranks), the label
outline, and the supervision mask. `render_png` writes the same panels side by side as one
PNG, for a record that needs no browser.

Maps are .npy or .tif (tif needs tifffile). Output is model output, not a reading: the page
says so in its header. Never build it from a target-scroll map and commit or share the file.
"""

import base64
import html
import json
import struct
import zlib
from pathlib import Path

from .verify import VerifyError, _numpy

MAX_SIDE = 1024


def load_array(path):
    np = _numpy()
    path = Path(path)
    if path.suffix == ".npy":
        a = np.load(path)
    else:
        from .verify import load_map
        a = load_map(path)
    a = np.squeeze(a)
    if a.ndim != 2:
        raise VerifyError(f"{path}: expected a 2D array, got {a.shape}")
    return a


def png_bytes(img):
    """Encode uint8 [h,w] (grey) or [h,w,3|4] (RGB, RGBA) as PNG with the standard library."""
    np = _numpy()
    img = np.ascontiguousarray(img, dtype=np.uint8)
    if img.ndim == 2:
        img = img[:, :, None]
    h, w, c = img.shape
    ctype = {1: 0, 3: 2, 4: 6}[c]
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _step(shape, max_side):
    return max(1, -(-max(shape) // max_side))


def rank01(np, a, valid):
    """Percentile rank of each pixel among valid pixels, 0..1; 0 outside."""
    out = np.zeros(a.shape, dtype=np.float64)
    v = a[valid].astype(np.float64)
    if v.size:
        order = np.argsort(v, kind="stable")
        r = np.empty(v.size)
        r[order] = np.arange(v.size) / max(v.size - 1, 1)
        out[valid] = r
    return out


def build_layers(maps, labels=None, mask=None, max_side=MAX_SIDE):
    """maps: list of (name, 2D array) on one grid. Returns dict of uint8 layers and stats."""
    np = _numpy()
    if not maps:
        raise VerifyError("give at least one map")
    shape = maps[0][1].shape
    for name, a in maps:
        if a.shape != shape:
            raise VerifyError(f"map {name} has shape {a.shape}, expected {shape}")
    for what, a in (("labels", labels), ("mask", mask)):
        if a is not None and a.shape != shape:
            raise VerifyError(f"{what} shape {a.shape} differs from the maps' {shape}")
    s = _step(shape, max_side)
    sub = lambda a: a[::s, ::s]
    valid = np.ones(sub(maps[0][1]).shape, dtype=bool) if mask is None else sub(mask).astype(bool)
    for _, a in maps:
        valid &= sub(a) != 0
    ranks = [(n, rank01(np, sub(a), valid)) for n, a in maps]
    layers = {"readers": [(n, (r * 255).round().astype(np.uint8)) for n, r in ranks]}
    stats = {"shape": list(shape), "step": s, "valid_px": int(valid.sum())}
    if len(ranks) > 1:
        stack = np.stack([r for _, r in ranks])
        dis = stack.std(0)
        top = max(float(dis[valid].max()) if valid.any() else 0.0, 1e-9)
        layers["disagreement"] = (dis / top * 255).round().astype(np.uint8)
        stats["disagreement_mean"] = round(float(dis[valid].mean()), 4)
        corr = {}
        for i in range(len(ranks)):
            for j in range(i + 1, len(ranks)):
                c = np.corrcoef(stack[i][valid], stack[j][valid])[0, 1]
                corr[f"{ranks[i][0]} vs {ranks[j][0]}"] = round(float(c), 4)
        stats["rank_correlation"] = corr
    if labels is not None:
        lab = sub(labels).astype(bool)
        edge = lab & ~(np.roll(lab, 1, 0) & np.roll(lab, -1, 0) & np.roll(lab, 1, 1) & np.roll(lab, -1, 1))
        rgba = np.zeros(lab.shape + (4,), dtype=np.uint8)
        rgba[edge] = (0, 255, 120, 255)
        layers["labels"] = rgba
        layers["labels_bool"] = lab
        if valid.any() and lab[valid].any() and (~lab[valid]).any():
            from .auc import score_array
            stats["auc_on_view"] = {n: score_array((r * 65534 + 1).astype(np.float64), lab, valid)["auc"]
                                    for n, r in ranks}
    if mask is not None:
        m = np.zeros(valid.shape + (4,), dtype=np.uint8)
        m[~valid] = (0, 0, 0, 170)
        layers["mask"] = m
    return layers, stats


def _uri(img):
    return "data:image/png;base64," + base64.b64encode(png_bytes(img)).decode()


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title><style>
body{{font:14px system-ui,sans-serif;margin:16px;background:#111;color:#ddd}}
#stage{{position:relative;display:inline-block;image-rendering:pixelated}}
#stage img{{position:absolute;left:0;top:0;width:{w}px;height:{h}px}}
#stage img.base{{position:relative}} .ctl{{margin:6px 0}} code{{color:#9cf}}
.warn{{color:#fc6}}</style></head><body>
<h2>{title}</h2><p class="warn">Model output, not a reading. Readers are percentile ranked inside the mask.</p>
<div class="ctl">Reader: <select id="reader">{options}</select>
 Overlay: <select id="over"><option value="none">none</option>{over_opts}</select>
 opacity <input id="op" type="range" min="0" max="100" value="60">
 <label><input id="lab" type="checkbox" checked> labels</label>
 <label><input id="msk" type="checkbox" checked> mask</label></div>
<div id="stage">{imgs}</div><div class="ctl" id="read">move the cursor over the image</div>
<pre id="stats">{stats}</pre>
<script>
const R={readers_json},O={over_json},W={w},H={h},S={step};
const st=document.getElementById('stage'),cv=document.createElement('canvas');cv.width=W;cv.height=H;
const cx=cv.getContext('2d',{{willReadFrequently:true}});
function px(id,x,y){{const im=document.getElementById(id);cx.clearRect(0,0,W,H);cx.drawImage(im,0,0,W,H);return cx.getImageData(x,y,1,1).data}}
function show(){{const r=document.getElementById('reader').value,o=document.getElementById('over').value,op=document.getElementById('op').value/100;
 for(const n of R)document.getElementById('r_'+n).style.display=(n==r)?'':'none';
 for(const n of O){{const e=document.getElementById('o_'+n);e.style.display=(n==o)?'':'none';e.style.opacity=op}}
 const l=document.getElementById('labels');if(l)l.style.display=document.getElementById('lab').checked?'':'none';
 const m=document.getElementById('mask');if(m)m.style.display=document.getElementById('msk').checked?'':'none'}}
for(const id of['reader','over','op','lab','msk'])document.getElementById(id).oninput=show;
st.onmousemove=e=>{{const b=st.getBoundingClientRect(),x=Math.floor(e.clientX-b.left),y=Math.floor(e.clientY-b.top);
 if(x<0||y<0||x>=W||y>=H)return;let t='x '+x*S+', y '+y*S+' (map px): ';
 for(const n of R)t+=n+' rank '+(px('r_'+n,x,y)[0]/255).toFixed(2)+'  ';
 if(O.includes('disagreement'))t+='disagreement '+(px('o_disagreement',x,y)[0]/255).toFixed(2);
 document.getElementById('read').textContent=t}};show();
</script></body></html>"""


def build_html(maps, labels=None, mask=None, title="Ink map viewer", max_side=MAX_SIDE):
    layers, stats = build_layers(maps, labels, mask, max_side)
    h, w = layers["readers"][0][1].shape
    readers = [n for n, _ in layers["readers"]]
    imgs = []
    for i, (n, img) in enumerate(layers["readers"]):
        imgs.append(f'<img id="r_{html.escape(n)}" class="{"base" if i == 0 else ""}" src="{_uri(img)}">')
    over = []
    if "disagreement" in layers:
        d = layers["disagreement"]
        np = _numpy()
        rgba = np.zeros(d.shape + (4,), dtype=np.uint8)
        rgba[..., 0] = 255
        rgba[..., 1] = (255 - d) // 3
        rgba[..., 3] = d
        imgs.append(f'<img id="o_disagreement" src="{_uri(rgba)}">')
        over.append("disagreement")
    if len(readers) > 1:   # reader minus reader 0
        np = _numpy()
        base = layers["readers"][0][1].astype(int)
        for n, img in layers["readers"][1:]:
            diff = img.astype(int) - base
            rgba = np.zeros(diff.shape + (4,), dtype=np.uint8)
            rgba[..., 2] = np.where(diff > 0, 255, 0)
            rgba[..., 0] = np.where(diff < 0, 255, 0)
            rgba[..., 3] = np.clip(np.abs(diff), 0, 255)
            key = f"{n} minus {readers[0]}"
            imgs.append(f'<img id="o_{html.escape(key)}" src="{_uri(rgba)}">')
            over.append(key)
    if "labels" in layers:
        imgs.append(f'<img id="labels" src="{_uri(layers["labels"])}">')
    if "mask" in layers:
        imgs.append(f'<img id="mask" src="{_uri(layers["mask"])}">')
    opt = lambda names: "".join(f'<option value="{html.escape(n)}">{html.escape(n)}</option>' for n in names)
    return PAGE.format(title=html.escape(title), w=w, h=h, step=stats["step"], options=opt(readers),
                       over_opts=opt(over), imgs="".join(imgs), stats=html.escape(json.dumps(stats, indent=1)),
                       readers_json=json.dumps(readers), over_json=json.dumps(over)), stats


def render_png(maps, labels=None, mask=None, max_side=384):
    """Side-by-side panels: each reader (labels outlined), then the disagreement. uint8 RGB."""
    np = _numpy()
    layers, stats = build_layers(maps, labels, mask, max_side)
    panels = []
    for _, img in layers["readers"]:
        rgb = np.repeat(img[..., None], 3, axis=2)
        panels.append(rgb)
    if "disagreement" in layers:
        d = layers["disagreement"]
        panels.append(np.stack([d, d // 3, 255 - d], axis=2).astype(np.uint8))
    out = []
    for p in panels:
        p = p.copy()
        if "labels" in layers:
            e = layers["labels"][..., 3] > 0
            p[e] = (0, 255, 120)
        if "mask" in layers:
            outside = layers["mask"][..., 3] > 0
            p[outside] = p[outside] // 3
        out.append(p)
        out.append(np.full((p.shape[0], 6, 3), 40, dtype=np.uint8))
    return np.concatenate(out[:-1], axis=1), stats
