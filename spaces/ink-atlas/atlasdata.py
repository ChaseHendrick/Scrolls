"""Ink Atlas data: the public First Letters ink atlas (the Hugging Face dataset SharpMeow/first-letters-ink-atlas),
read file by file, and the pictures and records the page and its API make from it.

No gradio here, so the tests and your own scripts can use it:

  import atlasdata as A
  atlas = A.Atlas()                                  # the dataset on the Hub; Atlas(root=DIR) reads a local copy
  png, record = A.get_map(atlas, "kbh-PHerc0343_4937_3336_11593", "ensemble")

Every map is model output, not a reading.
"""
import collections
import functools
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = os.environ.get("ATLAS_REPO", "SharpMeow/first-letters-ink-atlas")
REVISION = os.environ.get("ATLAS_REVISION") or None        # a commit to pin; None reads main
DATASET_URL = f"https://huggingface.co/datasets/{REPO}"
OUT = Path(tempfile.gettempdir()) / "ink-atlas-out"

ENSEMBLE, CT = "ensemble", "ct"
WINDOWS = ("c-4", "c+0", "c+4")
ORDERS = ("forward", "reverse")
ORDER_LABEL = {"forward": "as stored", "reverse": "reversed"}
DISPLAY = 1400                    # longest side of a whole-surface picture
CROP_SIZES = (256, 384, 512, 768, 1024)
MAX_CROP = 1024
MODELS = {                        # id: (short name, full title, by); the order the page and the grids use
    "ink_9um-s42": ("ink_9um s42", "ink_9um seed 42, step 75,000", "Vesuvius Challenge"),
    "ink_9um-s43": ("ink_9um s43", "ink_9um seed 43, step 75,000", "Vesuvius Challenge"),
    "reader-v2": ("Reader v2", "Reader v2", "Domenico Russo"),
    "reader-v3": ("Reader V3", "Reader V3", "Domenico Russo"),
    "dense-native": ("dense_native", "dense_native, step 16,000", "Erwin Nieuwlaar"),
    "d9v2": ("d9v2", "d9v2", "TAUIL-Abd-Elilah"),
    "hecate-9.6": ("Hecate 9.6", "Hecate 9.6 um", "Vesuvius Challenge"),
}
# color ramps, low to high; maps go 0 to 1 with high meaning more ink by the model
RAMPS = {
    "gray": ["#000000", "#ffffff"],
    "papyrus": ["#f4ecdc", "#d9c7a4", "#8a6f4e", "#3a2a26", "#120d16"],
    "ember": ["#07060f", "#2b1460", "#7b2a8c", "#d4543a", "#f6a53b", "#fff3c4"],
    "ice": ["#05070f", "#10224f", "#2a56a8", "#6ea6e6", "#e9f3ff"],
}
# one color per layer, for labels, bars and legends (balanced: blues, violets, pinks, oranges)
LAYER_COLOR = {"ct": "#64748b", "ensemble": "#5b4bd6", "ink_9um-s42": "#2a56a8", "ink_9um-s43": "#3d8be0",
               "reader-v2": "#7b2a8c", "reader-v3": "#c2418f", "dense-native": "#e08a3c", "d9v2": "#d4543a",
               "hecate-9.6": "#b7791f"}
RAMP_LABEL = {"gray": "Gray: ink bright", "papyrus": "Papyrus: ink dark", "ember": "Ember", "ice": "Ice"}
NO_SURFACE = (14, 16, 26)         # pixels the mesh does not cover


class AtlasError(Exception):
    """A request the atlas cannot answer (unknown surface, model, window or region); the message says why."""


def _hex(c):
    return [int(c[i:i + 2], 16) for i in (1, 3, 5)]


@functools.lru_cache(maxsize=None)
def ramp(name):
    """A 256 x 3 uint8 lookup table for one of RAMPS."""
    if name not in RAMPS:
        raise AtlasError(f"colormap {name!r} is not one of {', '.join(RAMPS)}")
    stops = np.array([_hex(c) for c in RAMPS[name]], np.float64)
    at = np.linspace(0, 1, len(stops))
    x = np.linspace(0, 1, 256)
    return np.stack([np.interp(x, at, stops[:, k]) for k in range(3)], 1).round().astype(np.uint8)


class Atlas:
    """The dataset: atlas.json, every surface's meta.json, and its maps fetched on demand (the Hub's own cache keeps
    them). root= reads a local copy laid out like the dataset instead (the tests, or a snapshot_download folder)."""

    def __init__(self, root=None, repo=REPO, revision=REVISION, prefetch=True):
        self.root = Path(root) if root else None
        self.repo, self.revision = repo, revision
        if self.root is None and prefetch:
            self._prefetch()
        self.index = json.loads(Path(self.file("atlas.json")).read_text())
        self.surfaces = {s["id"]: s for s in self.index["surfaces"]}
        self._meta, self._lock = {}, threading.Lock()

    def _prefetch(self):
        from huggingface_hub import snapshot_download
        try:
            self._snap = Path(snapshot_download(self.repo, repo_type="dataset", revision=self.revision,
                                                allow_patterns=["atlas.json", "surfaces/*/*/meta.json",
                                                                "surfaces/*/*/preview.jpg"]))
        except Exception:  # noqa: BLE001 (offline or rate limited: file() fetches one at a time)
            self._snap = None

    def file(self, rel):
        """A local path to one file of the dataset."""
        if self.root is not None:
            p = self.root / rel
            if not p.is_file():
                raise AtlasError(f"{rel} is not in the atlas")
            return str(p)
        snap = getattr(self, "_snap", None)
        if snap is not None and (snap / rel).is_file():
            return str(snap / rel)
        from huggingface_hub import hf_hub_download
        try:
            return hf_hub_download(self.repo, rel, repo_type="dataset", revision=self.revision)
        except Exception as exc:  # noqa: BLE001
            raise AtlasError(f"could not fetch {rel} from {self.repo}: {type(exc).__name__}") from None

    def url(self, rel):
        return f"{DATASET_URL}/resolve/{self.revision or 'main'}/{rel}"

    def surface(self, sid):
        sid = (sid or "").strip()
        if sid not in self.surfaces:
            raise AtlasError(f"no surface {sid!r} in the atlas; list_surfaces gives the ids")
        return self.surfaces[sid]

    def meta(self, sid):
        s = self.surface(sid)
        with self._lock:
            if sid not in self._meta:
                self._meta[sid] = json.loads(Path(self.file(f"{s['path']}/meta.json")).read_text())
            return self._meta[sid]

    def gray(self, rel):
        return _gray(self.file(rel))

    def valid(self, sid):
        """Where the mesh covers the canvas: the middle CT layer is not 0."""
        return self.gray(f"{self.surface(sid)['path']}/ct_mid.png") > 0


@functools.lru_cache(maxsize=40)
def _gray(path):
    with Image.open(path) as im:
        a = np.asarray(im.convert("L"))
    a.setflags(write=False)
    return a


# ----- what the atlas holds -------------------------------------------------------------------------------------

def face_votes(meta):
    """How many alive model pairs the face check (villa PR #2318) finds agreeing better as stored, reversed, or
    neither; and the depth order the page opens on (the majority, as stored on a tie)."""
    v = collections.Counter(p.get("consistent_face", "tie") for p in meta.get("face_check", {}).get("pairs", {}).values())
    votes = {"forward": v.get("forward", 0), "reverse": v.get("reverse", 0), "tie": v.get("tie", 0)}
    return votes, ("reverse" if votes["reverse"] > votes["forward"] else "forward")


def short_id(sid, scroll):
    return sid.replace("kbh-", "").replace(f"{scroll}_", "")


def label(atlas, sid):
    s = atlas.surface(sid)
    return f"{s['scroll']} · {short_id(sid, s['scroll'])}" + ("  (reference)" if s["role"] == "reference" else "")


def alive_models(meta):
    return [m for m in MODELS if meta.get("models", {}).get(m, {}).get("alive")]


def model_windows(meta, model):
    # the key is spelled the British way in every published meta.json; it stays so the published dataset still reads
    return ["c+0"] if model in meta.get("windows", {}).get("centre_only", []) else list(WINDOWS)


def atlas_summary(atlas):
    """What the atlas is: counts, the seven models with their authors and licenses, the files, credits and license.

    Every map is model output, not a reading."""
    idx = atlas.index
    scrolls = collections.Counter(s["scroll"] for s in idx["surfaces"])
    roles = collections.Counter(s["role"] for s in idx["surfaces"])
    return {
        "name": "First Letters ink atlas",
        "dataset": DATASET_URL,
        "surfaces": len(idx["surfaces"]),
        "first_letters_surfaces": roles.get("eligible", 0),
        "reference_surfaces": roles.get("reference", 0),
        "scrolls": len(scrolls),
        "canvas": "9.6 um per pixel, 65 CT layers 9.6 um apart, one shared canvas per surface",
        "windows": {"ids": list(WINDOWS), "meaning": "the model's 3D input centered 4 layers below, on, or 4 layers "
                    "above the traced surface (9.6 um layers); Hecate 9.6 has c+0 only"},
        "orders": {"forward": "depth order as stored", "reverse": "depth order reversed"},
        "ensemble": "ink-sdk ensemble (Erwin Nieuwlaar's PHerc0343 recipe): mean of per-model z-scores of the alive "
                    "models; PNGs map z from -2 to 4 onto 0 to 255",
        "models": [{"id": m, "title": t, "by": b, "license": "MIT"} for m, (_, t, b) in MODELS.items()],
        "files_per_surface": {
            "maps/MODEL/WINDOW_s1_ORDER.png": "one model's map, 8-bit, 0 to 1 as 0 to 255",
            "ensemble/forward.png, ensemble/reverse.png": "ensemble, statistics from the stored order",
            "ensemble-rev/forward.png, ensemble-rev/reverse.png": "ensemble, statistics from the reversed order",
            "ct_mid.png": "the middle CT layer of the render", "preview.jpg": "CT and ensemble side by side",
            "meta.json": "mesh and CT links, render record, liveness of every map, exposure notes, face check"},
        "license": "CC BY-NC 4.0 (derived from Vesuvius Challenge open data and ketchupbyheinz's traced meshes)",
        "credits": ["CT scans: Vesuvius Challenge open data (CC BY-NC 4.0)",
                    "Traced meshes and the face check: ketchupbyheinz (vesuvius-scroll-survey; villa PR #2318)",
                    "Models: their authors above (MIT); ensemble recipe: Erwin Nieuwlaar via LimeGS's ink-sdk",
                    "Atlas: Chase Hendrick, with Ink Lens"],
        "note": "Every map is model output, not a reading.",
    }


def list_scrolls(atlas):
    """Every scroll in the atlas with how many surfaces it has, and whether they are First Letters surfaces or
    PHerc0343 references."""
    out = collections.OrderedDict()
    for s in sorted(atlas.index["surfaces"], key=lambda s: s["scroll"]):
        r = out.setdefault(s["scroll"], {"scroll": s["scroll"], "surfaces": 0, "role": s["role"]})
        r["surfaces"] += 1
    return list(out.values())


def list_surfaces(atlas, scroll=""):
    """The surfaces of one scroll (or every surface when scroll is empty): id, scroll, scan, canvas size, the models
    whose maps have real spread there, and the face check's votes.

    Each id works with surface_info, get_map and compare_models."""
    scroll = (scroll or "").strip()
    rows = []
    for s in sorted(atlas.index["surfaces"], key=lambda s: (s["scroll"], s["id"])):
        if scroll and s["scroll"].lower() != scroll.lower():
            continue
        m = atlas.meta(s["id"])
        votes, default = face_votes(m)
        rows.append({"id": s["id"], "scroll": s["scroll"], "role": s["role"], "scan": m.get("scan"),
                     "voxel_um": m.get("voxel_um"), "canvas_hw": m["render"]["canvas_hw"],
                     "alive_models": alive_models(m), "face_check_votes": votes, "opens_on": default})
    if scroll and not rows:
        raise AtlasError(f"no scroll {scroll!r} in the atlas; list_scrolls gives them")
    return rows


def surface_info(atlas, surface_id):
    """One surface: where its mesh and CT are, how it was rendered, each model's liveness and training exposure as
    published, the ensemble, the face check of every model pair, and direct URLs of all its files."""
    s = atlas.surface(surface_id)
    m = atlas.meta(surface_id)
    votes, default = face_votes(m)
    r = m["render"]
    models = {}
    for mid in MODELS:
        mm = m.get("models", {}).get(mid)
        if not mm:
            continue
        models[mid] = {"title": mm.get("title"), "by": mm.get("by"), "license": mm.get("license"),
                       "alive": mm.get("alive"), "windows": model_windows(m, mid),
                       "exposure": (mm.get("exposure") or {}).get("status"),
                       "exposure_note": (mm.get("exposure") or {}).get("why")}
    return {
        "id": surface_id, "scroll": s["scroll"], "role": s["role"], "credit": m.get("credit"),
        "scan": m.get("scan"), "voxel_um": m.get("voxel_um"), "canvas_um": m.get("canvas_um"),
        "canvas_hw": r["canvas_hw"], "layers": r.get("layers"),
        "mesh": m.get("mesh", {}).get("base"), "ct": m.get("ct"),
        "render": {k: r.get(k) for k in ("render_scale", "layer_step_vox", "rendered_px", "chunks", "chunks_missing",
                                          "sha256", "renderer")},
        "models": models,
        "ensemble": {"members": m.get("ensemble", {}).get("ensemble", {}).get("members"),
                     "recipe": m.get("ensemble", {}).get("ensemble", {}).get("recipe"),
                     "png_z_range": m.get("ensemble_png_z_range")},
        "face_check": {"votes": votes, "opens_on": default, "mask": m.get("face_check", {}).get("mask"),
                       "pairs": m.get("face_check", {}).get("pairs", {})},
        "files": {f: atlas.url(f"{s['path']}/{f}") for f in m.get("files", [])},
        "page": f"https://huggingface.co/spaces/SharpMeow/ink-atlas?surface={surface_id}",
        "note": "Model output, not a reading.",
    }


# ----- pictures -------------------------------------------------------------------------------------------------

def layer_rel(atlas, sid, layer, window="c+0", order="forward"):
    """The file behind a layer, and the window actually used (Hecate 9.6 has the center window only)."""
    s, m = atlas.surface(sid), atlas.meta(sid)
    layer = (layer or ENSEMBLE).strip()
    order = order if order in ORDERS else "forward"
    if layer == CT:
        return f"{s['path']}/ct_mid.png", None
    if layer == ENSEMBLE:
        return (f"{s['path']}/ensemble/forward.png" if order == "forward" else
                f"{s['path']}/ensemble-rev/reverse.png"), None
    if layer not in m.get("models", {}):
        raise AtlasError(f"layer {layer!r} is not ensemble, ct or one of {', '.join(MODELS)}")
    if window not in WINDOWS:
        raise AtlasError(f"window {window!r} is not one of {', '.join(WINDOWS)}")
    if window not in model_windows(m, layer):
        window = "c+0"
    return f"{s['path']}/maps/{layer}/{window}_s1_{order}.png", window


def region(atlas, sid, x=-1, y=-1, size=0):
    """A size x size box (y0, y1, x0, x1) in canvas pixels centered on (x, y), moved inside the canvas; None for the
    whole surface (size 0 or x, y below 0)."""
    h, w = atlas.meta(sid)["render"]["canvas_hw"]
    size = int(size or 0)
    if size <= 0 or x is None or y is None or float(x) < 0 or float(y) < 0:
        return None
    size = min(size, MAX_CROP, h, w)
    x, y = int(round(float(x))), int(round(float(y)))
    if not (0 <= x < w and 0 <= y < h):
        raise AtlasError(f"({x}, {y}) is outside the {w} x {h} canvas (x across, y down)")
    y0 = min(max(0, y - size // 2), h - size)
    x0 = min(max(0, x - size // 2), w - size)
    return (y0, y0 + size, x0, x0 + size)


def stretch(a, valid, lo=1.0, hi=99.5, gamma=1.0):
    """0 to 1 floats: the lo and hi percentiles of the covered pixels go to 0 and 1."""
    v = a[valid] if valid is not None and valid.any() else a.ravel()
    if v.size > 400_000:
        v = v[:: v.size // 400_000]
    p_lo, p_hi = (np.percentile(v, [lo, hi]) if v.size else (0.0, 255.0))
    x = np.clip((a.astype(np.float32) - p_lo) / max(float(p_hi - p_lo), 1.0), 0, 1)
    if gamma and abs(gamma - 1.0) > 1e-3:
        x = x ** (1.0 / float(gamma))
    return x, (float(p_lo) / 255, float(p_hi) / 255)


def color(x01, valid, name="gray"):
    rgb = ramp(name)[(x01 * 255).astype(np.uint8)]
    if valid is not None:
        rgb[~valid] = NO_SURFACE
    return rgb


def overlay(ct01, map01, valid, name="ember", alpha=0.7):
    """The map in color over the CT in gray, each pixel as opaque as the map is high (times alpha)."""
    base = np.repeat((ct01 * 255)[..., None], 3, 2)
    top = ramp(name)[(map01 * 255).astype(np.uint8)].astype(np.float32)
    w = (alpha * map01)[..., None]
    rgb = (base * (1 - w) + top * w).round().astype(np.uint8)
    if valid is not None:
        rgb[~valid] = NO_SURFACE
    return rgb


def fit(img, side=DISPLAY):
    """Shrink a PIL image so its longest side is at most side pixels (box filter: an average, no ringing)."""
    w, h = img.size
    k = side / max(w, h)
    return img if k >= 1 else img.resize((max(1, round(w * k)), max(1, round(h * k))), Image.Resampling.BOX)


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow without FreeType sizes
        return ImageFont.load_default()


def save_png(img, stem):
    OUT.mkdir(parents=True, exist_ok=True)
    buf = img.tobytes()
    p = OUT / f"{stem}-{hashlib.sha1(buf).hexdigest()[:12]}.png"
    if not p.exists():
        img.save(p, optimize=False, compress_level=3)
    return str(p)


def shrink(a, side):
    """A uint8 array averaged down so its longest side is at most side pixels."""
    h, w = a.shape
    k = side / max(h, w)
    if k >= 1:
        return a
    return np.asarray(Image.fromarray(a).resize((max(1, round(w * k)), max(1, round(h * k))), Image.Resampling.BOX))


def layer_picture(atlas, sid, layer=ENSEMBLE, window="c+0", order="forward", box=None, colormap="gray",
                  lo=1.0, hi=99.5, gamma=1.0, mode="map", alpha=0.7, side=None):
    """A PIL picture of one layer, the whole surface or the box, and a record of how it was made. mode is map (the
    layer alone), overlay (the layer in color over the CT) or ct. side shrinks a whole-surface picture first."""
    rel, used = layer_rel(atlas, sid, CT if mode == "ct" else layer, window, order)

    def cut(a):
        if box is not None:
            return a[box[0]:box[1], box[2]:box[3]]
        return shrink(a, side) if side else a
    valid = cut(atlas.valid(sid).astype(np.uint8) * 255) > 127
    a = cut(atlas.gray(rel))
    x, (p_lo, p_hi) = stretch(a, valid, lo, hi, gamma)
    if mode == "overlay" and layer != CT:
        ct = cut(atlas.gray(layer_rel(atlas, sid, CT)[0]))
        rgb = overlay(stretch(ct, valid, 0.5, 99.5)[0], x, valid, colormap if colormap != "gray" else "ember", alpha)
    else:
        rgb = color(x, valid, "gray" if (mode == "ct" or layer == CT) else colormap)
    rec = {"surface": sid, "layer": CT if mode == "ct" else layer, "window": used, "order": order,
           "mode": mode, "source": atlas.url(rel), "box_y0_y1_x0_x1": list(box) if box else None,
           "stretch": {"low_percentile": lo, "high_percentile": hi, "low_value": round(p_lo, 4),
                       "high_value": round(p_hi, 4), "gamma": gamma},
           "covered_fraction": round(float(valid.mean()), 4)}
    return Image.fromarray(rgb), rec


def get_map(atlas, surface_id, layer=ENSEMBLE, window="c+0", order="", x=-1, y=-1, size=0, colormap="gray",
            mode="map", max_side=DISPLAY):
    """One map of one surface as a PNG: the ensemble, one model's map (by model id) or the CT. With size > 0, a
    full-resolution size x size crop centered on (x, y) in canvas pixels; otherwise the whole surface shrunk to
    max_side. order is forward (as stored) or reverse; empty uses the face check's majority. Returns the picture and
    a record (the source file's URL, the crop, the contrast stretch)."""
    m = atlas.meta(surface_id)
    order = order or face_votes(m)[1]
    box = region(atlas, surface_id, x, y, size)
    img, rec = layer_picture(atlas, surface_id, layer, window, order, box, colormap, mode=mode,
                             side=min(int(max_side or DISPLAY), 4096))
    rec["picture_wh"] = list(img.size)
    rec["note"] = "Model output, not a reading."
    return save_png(img, f"{surface_id}-{rec['layer']}"), rec


def _pearson(a, b, valid):
    a, b = a[valid].astype(np.float64), b[valid].astype(np.float64)
    if a.size < 16 or a.std() == 0 or b.std() == 0:
        return None
    return round(float(np.corrcoef(a, b)[0, 1]), 3)


def compare_picture(atlas, sid, box, order="forward", window="c+0", colormap="gray", tile=320):
    """Every model, the ensemble and the CT on the same box, each stretched on its own, in one labeled grid; and
    per-layer numbers in the box."""
    m = atlas.meta(sid)
    valid = atlas.valid(sid)[box[0]:box[1], box[2]:box[3]]
    ens = atlas.gray(layer_rel(atlas, sid, ENSEMBLE, window, order)[0])[box[0]:box[1], box[2]:box[3]]
    layers = [(CT, "CT, middle layer", None), (ENSEMBLE, "Ensemble", None)]
    layers += [(mid, MODELS[mid][0], mid) for mid in MODELS if mid in m.get("models", {})]
    ids = [lid for lid, _, _ in layers]
    tiles, stats = [], {}
    for lid, name, mid in layers:
        rel, used = layer_rel(atlas, sid, lid, window, order)
        a = atlas.gray(rel)[box[0]:box[1], box[2]:box[3]]
        x, _ = stretch(a, valid, 1.0 if lid != CT else 0.5, 99.5)
        img = Image.fromarray(color(x, valid, "gray" if lid == CT else colormap))
        alive = True if mid is None else bool(m["models"][mid].get("alive"))
        sub = ("" if mid is None or used in (None, window) else f"{used} only") + ("" if alive else " flat here")
        tiles.append((img, name, sub.strip()))
        if lid != CT:
            v = a[valid].astype(np.float64) / 255 if valid.any() else np.zeros(1)
            stats[lid] = {"alive": alive, "window": used, "mean": round(float(v.mean()), 4),
                          "p50": round(float(np.percentile(v, 50)), 4), "p99": round(float(np.percentile(v, 99)), 4),
                          "r_with_ensemble": None if lid == ENSEMBLE else _pearson(a, ens, valid)}
    cols = 3
    rows = -(-len(tiles) // cols)
    pad, head = 12, 40
    canvas = Image.new("RGB", (cols * tile + (cols + 1) * pad, rows * (tile + head) + (rows + 1) * pad), (250, 248, 244))
    d = ImageDraw.Draw(canvas)
    f, fs = font(19), font(14)
    for i, (img, name, sub) in enumerate(tiles):
        cx, cy = pad + (i % cols) * (tile + pad), pad + (i // cols) * (tile + head + pad)
        c = tuple(_hex(LAYER_COLOR.get(ids[i], "#5b4bd6")))
        d.rounded_rectangle([cx, cy + 4, cx + tile, cy + head - 4], radius=8, fill=c)
        d.text((cx + 10, cy + 10), name, fill=(255, 255, 255), font=f)
        if sub:
            d.text((cx + tile - 10, cy + 13), sub, fill=(255, 240, 220), font=fs, anchor="ra")
        canvas.paste(img.resize((tile, tile), Image.Resampling.BOX if img.width > tile else Image.Resampling.NEAREST),
                     (cx, cy + head))
    return canvas, stats


def compare_models(atlas, surface_id, x=-1, y=-1, size=512, order="", window="c+0", colormap="gray"):
    """Every model, the ensemble and the CT on the same size x size box of one surface (centered on x, y in canvas
    pixels; the middle of the surface when x or y is below 0), in one grid at full resolution, with each layer's
    mean, median and 99th percentile in the box and its correlation with the ensemble there."""
    m = atlas.meta(surface_id)
    order = order or face_votes(m)[1]
    h, w = m["render"]["canvas_hw"]
    if x is None or y is None or float(x) < 0 or float(y) < 0:
        x, y = w // 2, h // 2
    box = region(atlas, surface_id, x, y, int(size or 512))
    img, stats = compare_picture(atlas, surface_id, box, order, window, colormap)
    rec = {"surface": surface_id, "order": order, "window": window, "box_y0_y1_x0_x1": list(box),
           "layers": stats, "note": "Each tile is stretched on its own (1st to 99.5th percentile of the box). "
           "Model output, not a reading."}
    return save_png(img, f"{surface_id}-compare"), rec


def mark(img, box, scale, color_=(246, 165, 59)):
    """Draw the loupe's box on a whole-surface picture shrunk by scale."""
    if box is None:
        return img
    img = img.copy()
    y0, y1, x0, x1 = (round(v * scale) for v in box)
    d = ImageDraw.Draw(img)
    d.rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], outline=(10, 10, 20), width=5)
    d.rectangle([x0 - 2, y0 - 2, x1 + 2, y1 + 2], outline=color_, width=3)
    return img
