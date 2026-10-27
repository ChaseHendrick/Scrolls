"""AFV fiber files for the AFV Fibers Space: which scans have them, where they live, and reading the fibers and the CT
around a point.

Every scan's fibers are one public Hugging Face dataset (SharpMeow/<scan>-afv-fibers): the whole-scan .afv, a 1 mm
set, and tiles/ with one small .afv per 1024-voxel cell of the scan grid the model ran on, so a box needs one to eight
small files, never the whole scan. The CT comes live from the Vesuvius Challenge open data at that same grid; nothing
is rehosted. All coordinates in and out are native level-0 voxels (x, y, z in the files, z, y, x in the arguments),
the frame VC3D and villa's import_afv.py use.
"""
import json
import os
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
USER_AGENT = "afv-fibers-space (huggingface.co/spaces/SharpMeow/afv-fibers)"
CACHE = Path(os.environ.get("AFV_CACHE") or Path(tempfile.gettempdir()) / "afv-fibers")
CACHE_BYTES = int(float(os.environ.get("AFV_CACHE_GB", "20")) * 1e9)
MAX_HALF = 256          # the largest box half-size, in voxels of the grid the model ran on
COLORS = {"V": (255, 138, 61), "H": (58, 209, 255)}

# The six scans. level: the CT level the model and the tracing ran on (its voxels are about 9 um); f = 2**level.
SCANS = {
    "PHerc0009B": {"volume": "20250521125136-8.640um-1.2m-116keV-masked.zarr", "level": 0, "um": 8.64},
    "PHerc0139": {"volume": "20250728140407-9.362um-1.2m-113keV-masked.zarr", "level": 0, "um": 9.362},
    "PHerc0332": {"volume": "20251211183505-2.399um-0.2m-78keV-masked.zarr", "level": 2, "um": 2.399,
                  "name": "Scroll 3"},
    "PHerc0814": {"volume": "20250804134230-9.362um-1.2m-113keV-masked.zarr", "level": 0, "um": 9.362},
    "PHerc0841": {"volume": "20250821151531-9.366um-1.2m-113keV-masked.zarr", "level": 0, "um": 9.366},
    "PHerc1667": {"volume": "20251217075048-2.399um-0.2m-78keV-masked.zarr", "level": 2, "um": 2.399,
                  "name": "Scroll 4"},
}
for _scan, _s in SCANS.items():
    _s["repo"] = f"SharpMeow/{_scan.lower()}-afv-fibers"
    _s["ct"] = f"{BUCKET}/{_scan}/volumes/{_s['volume']}"
    _s["volume_id"] = _s["volume"].split("-")[0]
    _s["f"] = 2 ** _s["level"]


class FiberError(Exception):
    """A refusal or failure shown to the visitor as is."""


def http_get(url, timeout=120, tries=5):
    """Bytes at `url`, or None for a missing object."""
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                return None
            err = exc
        except (urllib.error.URLError, OSError) as exc:
            err = exc
        time.sleep(1.5 * (i + 1))
    raise FiberError(f"could not read {url}: {err}")


def scan_info(scan):
    if scan not in SCANS:
        raise FiberError(f"no AFV fibers for {scan!r} here; scans: {', '.join(SCANS)}")
    return SCANS[scan]


def dataset_url(scan, path):
    return f"https://huggingface.co/datasets/{scan_info(scan)['repo']}/resolve/main/{path}"


_lock = threading.Lock()
_index = {}
_zarray = {}


def _download(scan, path):
    """A file of the scan's dataset in the local cache (downloaded once; the cache is trimmed to CACHE_BYTES)."""
    dest = CACHE / scan / path
    if dest.exists():
        os.utime(dest)
        return dest
    data = http_get(dataset_url(scan, path), timeout=600)
    if data is None:
        raise FiberError(f"{scan_info(scan)['repo']} has no {path} (yet)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    _trim()
    return dest


def _trim():
    files = sorted((p for p in CACHE.rglob("*.afv") if p.is_file()), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    while files and total > CACHE_BYTES:
        p = files.pop(0)
        total -= p.stat().st_size
        p.unlink(missing_ok=True)


def tile_index(scan):
    """The scan's tiles/index.json: each tile's id, box (z0, z1, y0, y1, x0, x1) in level-0 voxels and fiber count."""
    with _lock:
        if scan not in _index:
            _index[scan] = json.loads(_download(scan, "tiles/index.json").read_text())
        return _index[scan]


def box_l0(scan, z, y, x, half):
    """The box around a level-0 point, `half` voxels of the model's grid each way, in level-0 voxels."""
    s = scan_info(scan)
    half = int(min(max(int(half), 16), MAX_HALF))
    h = half * s["f"]
    return [int(z) - h, int(z) + h, int(y) - h, int(y) + h, int(x) - h, int(x) + h]


def tiles_for(scan, box):
    out = []
    for t in tile_index(scan)["tiles"]:
        b = t["box_zyx_l0"]
        if b[0] < box[1] and box[0] < b[1] and b[2] < box[3] and box[2] < b[3] and b[4] < box[5] and box[4] < b[5]:
            out.append(t)
    return out


def fibers_in_box(scan, box):
    """{id: (family, (N, 3) xyz level-0 points)} for every fiber with a block touching the level-0 box (z0, z1, y0,
    y1, x0, x1); tiles share fiber ids, so a fiber crossing tiles appears once."""
    ts = tiles_for(scan, box)
    if not ts:
        return {}, []
    with ThreadPoolExecutor(4) as pool:
        paths = list(pool.map(lambda t: _download(scan, f"tiles/{t['id']}.afv"), ts))
    out = {}
    q = ("SELECT DISTINCT b.fiber_id FROM block_bounds r JOIN blocks b ON b.id = r.id WHERE r.max_x >= ? AND "
         "r.min_x < ? AND r.max_y >= ? AND r.min_y < ? AND r.max_z >= ? AND r.min_z < ?")
    for path in paths:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for (fid,) in db.execute(q, (box[4], box[5], box[2], box[3], box[0], box[1])).fetchall():
            if fid in out:
                continue
            fam = db.execute("SELECT family FROM fibers WHERE id = ?", (fid,)).fetchone()[0]
            blocks = [np.frombuffer(b, "<f8").reshape(-1, 3) for (b,) in
                      db.execute("SELECT points FROM blocks WHERE fiber_id = ? ORDER BY first_segment", (fid,))]
            out[fid] = (fam, np.concatenate([blocks[0]] + [b[1:] for b in blocks[1:]]))
        db.close()
    return out, [t["id"] for t in ts]


def write_box_afv(scan, box, dest):
    """The fibers touching a box as their own small .afv (same schema, whole fibers, whole-scan ids), for VC3D or any
    AFV reader."""
    ts = tiles_for(scan, box)
    dest = Path(dest)
    dest.unlink(missing_ok=True)
    if not ts:
        raise FiberError("no fibers there")
    src = _download(scan, f"tiles/{ts[0]['id']}.afv")
    db = sqlite3.connect(str(dest))
    schema = [r[0] for r in sqlite3.connect(f"file:{src}?mode=ro", uri=True).execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL AND name NOT LIKE 'block_bounds_%'")]
    for sql in schema:
        db.execute(sql)
    db.execute("PRAGMA application_id=0x56434643")
    db.execute("PRAGMA user_version=1")
    meta = None
    for t in ts:
        path = _download(scan, f"tiles/{t['id']}.afv")
        db.execute("ATTACH DATABASE ? AS s", (f"file:{path}?mode=ro",))
        if meta is None:
            meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM s.metadata")}
        db.execute("CREATE TEMP TABLE IF NOT EXISTS pick(id INTEGER PRIMARY KEY)")
        db.execute("DELETE FROM pick")
        db.execute("INSERT OR IGNORE INTO pick SELECT DISTINCT b.fiber_id FROM s.block_bounds r JOIN s.blocks b ON "
                   "b.id = r.id WHERE r.max_x >= ? AND r.min_x < ? AND r.max_y >= ? AND r.min_y < ? AND r.max_z >= ? "
                   "AND r.min_z < ?", (box[4], box[5], box[2], box[3], box[0], box[1]))
        db.execute("DELETE FROM pick WHERE id IN (SELECT id FROM fibers)")
        db.execute("INSERT INTO fibers SELECT f.* FROM s.fibers f JOIN pick USING(id)")
        db.execute("INSERT INTO blocks SELECT b.* FROM s.blocks b JOIN pick p ON p.id = b.fiber_id")
        db.execute("INSERT INTO block_bounds SELECT r.* FROM s.block_bounds r JOIN s.blocks b ON b.id = r.id "
                   "JOIN pick p ON p.id = b.fiber_id")
        db.commit()
        db.execute("DETACH DATABASE s")
    meta.pop("tile_box_zyx", None)
    meta["box_zyx_l0"] = box
    meta["fiber_count"] = db.execute("SELECT COUNT(*) FROM fibers").fetchone()[0]
    meta["point_count"] = db.execute("SELECT COALESCE(SUM(point_count), 0) FROM fibers").fetchone()[0]
    meta["block_count"] = db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
    db.execute("DELETE FROM metadata")
    db.executemany("INSERT INTO metadata VALUES(?,?)", [(k, json.dumps(v, separators=(",", ":"))) for k, v in meta.items()])
    db.commit()
    db.close()
    return meta["fiber_count"]


def ct_plane(scan, axis, at, box):
    """A uint8 plane of the CT on the model's grid: axis 'z' gives rows y and columns x, 'y' gives rows z and
    columns x; `at` and `box` are level-0 voxels."""
    s = scan_info(scan)
    url = f"{s['ct']}/{s['level']}"
    with _lock:
        if url not in _zarray:
            meta = json.loads(http_get(url + "/.zarray") or b"null")
            if not meta or meta.get("compressor") is not None or meta["dtype"] not in ("|u1", "<u1"):
                raise FiberError(f"unexpected CT layout at {url}")
            _zarray[url] = meta
        meta = _zarray[url]
    f = s["f"]
    b = [v // f for v in box]
    a = int(at) // f
    lo = [a, b[2], b[4]] if axis == "z" else [b[0], a, b[4]]
    hi = [a + 1, b[3], b[5]] if axis == "z" else [b[1], a + 1, b[5]]
    shape, ch = np.array(meta["shape"]), np.array(meta["chunks"])
    lo, hi = np.array(lo), np.array(hi)
    out = np.zeros(tuple(hi - lo), np.uint8)
    c0 = np.maximum(lo, 0) // ch
    c1 = (np.minimum(hi, shape) + ch - 1) // ch
    keys = [(i, j, k) for i in range(c0[0], c1[0]) for j in range(c0[1], c1[1]) for k in range(c0[2], c1[2])]
    if len(keys) > 64:
        raise FiberError("that box needs too much CT; make it smaller")

    def get(key):
        return key, http_get(f"{url}/{key[0]}/{key[1]}/{key[2]}")

    with ThreadPoolExecutor(16) as pool:
        for key, data in pool.map(get, keys):
            if data is None:
                continue
            k = np.array(key)
            arr = np.frombuffer(data, np.uint8).reshape(tuple(ch))
            g0 = np.maximum(k * ch, lo)
            g1 = np.minimum(np.minimum((k + 1) * ch, shape), hi)
            if (g1 <= g0).any():
                continue
            out[tuple(slice(p - q, r - q) for p, q, r in zip(g0, lo, g1))] = \
                arr[tuple(slice(p - q, r - q) for p, q, r in zip(g0, k * ch, g1))]
    plane = out[0] if axis == "z" else out[:, 0, :]
    nz = plane[plane > 0]
    if nz.size:
        lo_, hi_ = np.percentile(nz, [1, 99.5])
        plane = np.clip((plane.astype(np.float32) - lo_) / max(hi_ - lo_, 1) * 255, 0, 255).astype(np.uint8)
    return plane


def render_slice(scan, axis, at, box, fibers, slab=6, width=900):
    """The CT plane with the fibers near it drawn over, each segment faded by its distance from the plane (V orange,
    H cyan). `slab` is in voxels of the model's grid."""
    from PIL import Image, ImageDraw
    s = scan_info(scan)
    f = s["f"]
    plane = ct_plane(scan, axis, at, box)
    h, w = plane.shape
    scale = width / w
    ss = 2
    W, H = int(w * scale * ss), int(h * scale * ss)
    base = Image.fromarray(plane).resize((W, H), Image.BILINEAR).convert("RGBA")
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    cut, row, col = (2, 1, 0) if axis == "z" else (1, 2, 0)
    r0, c0 = (box[2], box[4]) if axis == "z" else (box[0], box[4])
    lw = max(2, int(round(2.2 * ss * min(1.0, scale * 1.6))))
    half = slab * f
    for fam, p in fibers.values():
        dist = np.abs(p[:, cut] - at)
        X = (p[:, col] - c0) / f * scale * ss
        Y = (p[:, row] - r0) / f * scale * ss
        for i in range(len(p) - 1):
            m = max(dist[i], dist[i + 1])
            if m >= half:
                continue
            alpha = int(235 * (1 - m / half) ** 0.7)
            d.line([(X[i], Y[i]), (X[i + 1], Y[i + 1])], fill=COLORS[fam] + (alpha,), width=lw)
    img = Image.alpha_composite(base, over).convert("RGB")
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def plot3d(scan, box, fibers, max_points=250000):
    """A plotly figure of every fiber inside the box (clipped to it), V orange and H cyan, in level-0 voxels."""
    import plotly.graph_objects as go
    lo = np.array([box[4], box[2], box[0]], float)
    hi = np.array([box[5], box[3], box[1]], float)
    total = sum(len(p) for _, p in fibers.values()) or 1
    step = max(1, int(np.ceil(total / max_points)))
    traces = []
    for fam, name in (("V", "vertical fibers"), ("H", "horizontal fibers")):
        xs, ys, zs = [], [], []
        for f_, p in fibers.values():
            if f_ != fam:
                continue
            q = p[::step] if len(p) > 2 * step else p
            ins = ((q >= lo) & (q < hi)).all(1)
            if ins.sum() < 2:
                continue
            q = np.where(ins[:, None], q, np.nan)
            xs += q[:, 0].tolist() + [None]
            ys += q[:, 1].tolist() + [None]
            zs += q[:, 2].tolist() + [None]
        traces.append(go.Scatter3d(x=xs, y=ys, z=zs, mode="lines", name=name,
                                   line=dict(color="rgb(%d,%d,%d)" % COLORS[fam], width=2), hoverinfo="skip"))
    fig = go.Figure(traces)
    fig.update_layout(paper_bgcolor="#05070c", plot_bgcolor="#05070c", font_color="#d8dee9", height=620,
                      margin=dict(l=0, r=0, t=30, b=0), legend=dict(x=0.01, y=0.98),
                      scene=dict(aspectmode="data", bgcolor="#05070c",
                                 xaxis=dict(title="x", color="#7d8899"), yaxis=dict(title="y", color="#7d8899"),
                                 zaxis=dict(title="z", color="#7d8899")))
    return fig
