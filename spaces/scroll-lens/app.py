"""Scroll Lens: look inside a Herculaneum scroll scan with the Vesuvius Challenge's 3D models.

The web page. Everything that is not the page (reading the scans, the models, clicks and scores) is in lens.py.
On a ZeroGPU Space the GPU is attached only to `gpu_run`; when the visitor's GPU quota is used up, or no GPU is free,
the same models run on the Space's CPU on a smaller cube instead. Gallery cubes need no GPU at all.

  python3 app.py            serve the page (on a Space, or on any computer: it then runs on CUDA if present, else CPU)
"""

import functools
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    import spaces  # first, before torch: on a ZeroGPU Space it attaches the GPU to spaces.GPU functions
except ImportError:
    spaces = None

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import lens  # noqa: E402
from lens import LensError  # noqa: E402

ON_ZERO_GPU = bool(spaces) and os.environ.get("SPACES_ZERO_GPU", "").lower() in ("1", "true")
OUT = Path(tempfile.gettempdir()) / "scroll-lens-out"
CPU_SIZE = 128                      # the cube side the CPU fallback runs
STATE_TTL_S = 30 * 60               # a visitor's cube is dropped from memory after this long without use
ENGINE = None
ENGINE_ERROR = None
READY = threading.Event()
REFERENCE = None                    # the organizers' reference ink embedding, loaded before the models
GALLERY = []

OVERLAYS = ("Ink (3D ink model)", "Recto surface", "Your clicks", "Organizers' ink reference", "DINO colors")
CLICK_MODES = ("More like this", "Not this", "Move the slices here")
VIEW_NAMES = ("Top view (z)", "Front view (y)", "Side view (x)")
COLORS = {"ink": (235, 64, 52), "surface": (64, 200, 96), "clicks": (40, 220, 235), "reference": (250, 180, 30)}
MARKS = {"pos": (255, 255, 255), "neg": (255, 70, 200)}   # crosses where you clicked: More like this, Not this


def log(message):
    lens.log(message)


# ---------------------------------------------------------------- start-up

def _load_engine():
    """Load the models in the background, so the page and the gallery work while they download."""
    global ENGINE, ENGINE_ERROR
    try:
        ENGINE = lens.Engine()
        log(f"models ready in {ENGINE.startup_s} s")
    except Exception as exc:  # noqa: BLE001  (shown to visitors who try to run a model)
        ENGINE_ERROR = f"{type(exc).__name__}: {exc}"
        log(f"models failed to load: {ENGINE_ERROR}")
    finally:
        READY.set()


def startup():
    global REFERENCE, GALLERY
    import numpy as np
    REFERENCE = lens.unit(np.load(lens.ensure_weights(names=("ink_reference",))["ink_reference"],
                                  allow_pickle=False).astype(np.float32))
    GALLERY = lens.gallery()
    log(f"{len(GALLERY)} gallery cubes; ZeroGPU {'on' if ON_ZERO_GPU else 'off'}")
    threading.Thread(target=_load_engine, name="load-models", daemon=True).start()


def engine(wait_s=5.0):
    if not READY.wait(wait_s):
        raise LensError("the models are still loading (about a minute after the Space wakes up); try again shortly. "
                        "The gallery works meanwhile.")
    if ENGINE is None:
        raise LensError(f"the models failed to load: {ENGINE_ERROR}")
    return ENGINE


# ---------------------------------------------------------------- the one GPU call

def _gpu_duration(cube, layers, tta):
    return lens.gpu_seconds(int(cube.shape[0]), layers, tta)


def _on_gpu(fn):
    return spaces.GPU(duration=_gpu_duration)(fn) if ON_ZERO_GPU else fn


@_on_gpu
def gpu_run(cube, layers, tta):
    """The chosen models on one cube, on the GPU ZeroGPU attaches for this call."""
    return ENGINE.run(cube, layers, device="cuda", tta=tta)


def _is_gpu_refusal(exc):
    text = f"{type(exc).__name__} {exc} {getattr(exc, 'title', '')}".lower()
    return any(k in text for k in ("quota", "zerogpu", "no gpu", "gpu task aborted", "gpu is not available"))


def run_models(cube, layers, tta, allow_cpu=True):
    """Run on the GPU when there is one; on ZeroGPU fall back to the CPU when the GPU is refused. Returns the result
    and a note for the visitor (empty when it ran as asked)."""
    import torch
    eng = engine()
    if ON_ZERO_GPU:
        try:
            return gpu_run(cube, tuple(layers), bool(tta)), ""
        except Exception as exc:  # noqa: BLE001
            if not (allow_cpu and _is_gpu_refusal(exc)):
                raise
            log(f"GPU refused ({exc}); running on the CPU")
            note = (f"Ran on the Space's CPU, because ZeroGPU said: {str(exc).strip()[:240]} "
                    "Your GPU minutes come back each day; signing in to Hugging Face gives more.")
            return eng.run(_center(cube, CPU_SIZE), layers, device="cpu", tta=False), note
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu" and cube.shape[0] > CPU_SIZE:
        return (eng.run(_center(cube, CPU_SIZE), layers, device="cpu", tta=False),
                f"No GPU here, so the models ran on the CPU on the middle {CPU_SIZE}³ voxels.")
    return eng.run(cube, layers, device=device, tta=tta), ""


def _center(cube, size):
    if cube.shape[0] <= size:
        return cube
    o = (cube.shape[0] - size) // 2
    return cube[o:o + size, o:o + size, o:o + size]


# ---------------------------------------------------------------- one cube in memory

def new_view(vid, origin, size, point, cube, result, source, note=""):
    """Everything the page needs about the cube on screen. Arrays only; it lives in the visitor's session."""
    import numpy as np
    if cube.shape[0] != size:                      # the CPU fallback ran a smaller cube at the center
        o = (size - cube.shape[0]) // 2
        origin = tuple(int(v + o) for v in origin)
        size = int(cube.shape[0])
    nz = cube[cube > 0]
    lo, hi = (np.percentile(nz, (0.5, 99.5)) if nz.size else (0, 255))
    view = {"volume": vid, "origin": tuple(int(v) for v in origin), "size": int(size),
            "point": tuple(int(v) for v in point), "cube": cube, "lo": float(lo), "hi": float(max(hi, lo + 1)),
            "source": source, "note": note, "result": result, "pca": None, "ref_sim": None,
            "foreground": lens.foreground(cube)}
    if "grid" in result or "grid_reduced" in result:
        view["grid"] = lens.grid_of(result).astype(np.float16)
        view["ref_sim"] = lens.similarity(view["grid"].astype(np.float32), REFERENCE)
    view["slices"] = [int(min(max(p - o, 0), size - 1)) for p, o in zip(point, view["origin"])]
    view["receipt"] = lens.receipt(vid, view["origin"], size, point, result,
                                   ENGINE.describe() if ENGINE else None,
                                   {"source": source, "foreground": round(view["foreground"], 4)})
    if "ink" in result and view.get("ref_sim") is not None:
        view["receipt"]["agreement_with_ink_model"] = lens.agreement(view["ref_sim"], result["ink"])
    return view


def empty_state():
    return {"view": None, "pos": [], "neg": []}


def click_concept(state):
    """The visitor's concept: unit mean of the positive clicks' embeddings, and of the negative ones (or None)."""
    import numpy as np
    pos = [c["vec"] for c in state["pos"]]
    neg = [c["vec"] for c in state["neg"]]
    p = lens.unit(np.mean(pos, 0)) if pos else None
    n = lens.unit(np.mean(neg, 0)) if neg else None
    return p, n


def click_sim(state):
    view = state["view"]
    p, n = click_concept(state)
    if view is None or p is None or "grid" not in view:
        return None
    import numpy as np
    return lens.similarity(view["grid"].astype(np.float32), p, n)


# ---------------------------------------------------------------- drawing

def _take(a, axis, i):
    return a[i] if axis == 0 else (a[:, i] if axis == 1 else a[:, :, i])


def _top_alpha(sim2d, sim3d, top_pct):
    """Opacity of each pixel of a similarity slice: 0 below the cube's top `top_pct` percent, rising to 1 at its best."""
    import numpy as np
    thr = float(np.percentile(sim3d, 100 - top_pct))
    best = float(sim3d.max())
    return np.clip((sim2d - thr) / max(best - thr, 1e-6), 0, 1) * (sim2d >= thr)


def draw_slice(state, axis, overlays, top_pct, opacity):
    """One slice through the cube as an RGB image, scaled up so a 128 or 256 cube shows at 512 px."""
    import numpy as np
    view = state["view"]
    if view is None:
        return None
    size, cube, idx = view["size"], view["cube"], view["slices"][axis]
    ct = _take(cube, axis, idx).astype(np.float32)
    g = np.clip((ct - view["lo"]) / (view["hi"] - view["lo"]), 0, 1)
    rgb = np.repeat(g[..., None], 3, axis=2)
    res = view["result"]
    tok_i = idx // lens.PATCH

    def up(t2):
        return np.repeat(np.repeat(t2, lens.PATCH, 0), lens.PATCH, 1)

    def blend(color, alpha):
        a = (np.asarray(alpha, np.float32) * opacity)[..., None]
        rgb[:] = rgb * (1 - a) + (np.asarray(color, np.float32) / 255.0) * a

    if "DINO colors" in overlays and "grid" in view:
        if view["pca"] is None:
            view["pca"] = lens.pca_colors(view["grid"].astype(np.float32))
        pc = up(_take(view["pca"], axis, tok_i)).astype(np.float32) / 255.0
        rgb[:] = rgb * (1 - 0.6 * opacity) + pc * (0.6 * opacity)
    if "Recto surface" in overlays and "surface" in res:
        blend(COLORS["surface"], _take(res["surface"], axis, idx) / 255.0)
    if "Ink (3D ink model)" in overlays and "ink" in res:
        blend(COLORS["ink"], _take(res["ink"], axis, idx) / 255.0)
    if "Organizers' ink reference" in overlays and view.get("ref_sim") is not None:
        s3 = view["ref_sim"]
        blend(COLORS["reference"], up(_top_alpha(_take(s3, axis, tok_i), s3, top_pct)))
    if "Your clicks" in overlays:
        s3 = click_sim(state)
        if s3 is not None:
            blend(COLORS["clicks"], up(_top_alpha(_take(s3, axis, tok_i), s3, top_pct)))
    img = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    # where the other two slices cut this one: thin guide lines
    others = [a for a in range(3) if a != axis]
    r, c = view["slices"][others[0]], view["slices"][others[1]]
    f = scale_of(size)
    img = np.repeat(np.repeat(img, f, 0), f, 1)
    guide = np.array([255, 255, 255], np.uint8)
    img[r * f + f // 2, :: 3] = guide
    img[:: 3, c * f + f // 2] = guide
    # the clicks made in this cube that lie in this slice
    for kind, color in (("pos", MARKS["pos"]), ("neg", MARKS["neg"])):
        for ck in state[kind]:
            if ck.get("cube") != cube_key(view):
                continue
            v = ck["voxel"]
            if v[axis] // lens.PATCH != tok_i:
                continue
            rr, cc = v[others[0]] * f, v[others[1]] * f
            _mark(img, rr + f // 2, cc + f // 2, color, 5 * f // 2 + 3)
    return img


def _mark(img, r, c, color, half):
    """A cross two pixels thick, drawn in place."""
    h, w = img.shape[:2]
    for d in range(-half, half + 1):
        for t in (0, 1):
            for (y, x) in ((r + d, c + t), (r + t, c + d)):
                if 0 <= y < h and 0 <= x < w:
                    img[y, x] = color


def scale_of(size):
    return max(1, 512 // int(size))


def cube_key(view):
    return f"{view['volume']}:{','.join(map(str, view['origin']))}:{view['size']}"


def numbers(state, top_pct):
    """The text beside the images: what this cube is, what ran, and the checks."""
    import numpy as np
    view = state["view"]
    if view is None:
        return ("Pick a ready-made cube from the gallery, or a point in a scan, then press **Run the models**. "
                "Click the images to find similar places.")
    v = lens.volume(view["volume"])
    r = view["receipt"]
    um = v["voxel_um"] * view["size"]
    lines = [f"**{v['scroll']}**, cube of {view['size']}³ voxels ({um / 1000:.2f} mm a side) at "
             f"z {view['origin'][0]}, y {view['origin'][1]}, x {view['origin'][2]}. "
             f"{view['foreground']:.0%} of it lies inside the scan's scroll mask."]
    src = {"gallery": "Gallery cube: computed earlier, no GPU used now.", "gpu": "Ran now on the GPU.",
           "cpu": "Ran now on the CPU.", "file": "Loaded from your file."}[view["source"]]
    secs = ", ".join(f"{k} {s:.1f} s" for k, s in r.get("seconds", {}).items())
    lines.append(f"{src} {('Times: ' + secs + '.') if secs else ''} {view['note']}".strip())
    lines.append("**What each model saw of this scroll in training.** " + " ".join(
        f"{lens.LAYER_TITLES[k]}: {v['role'][k]}" for k in lens.LAYERS))
    ag = r.get("agreement_with_ink_model")
    if ag and ag["auc"] is not None:
        lines.append(f"**Check.** The organizers' ink reference picks out the patches the 3D ink model marks as ink "
                     f"with AUC {ag['auc']:.2f}; the control (ink mask moved half a cube) gives "
                     f"{ag['auc_control_shifted']:.2f} and should sit near 0.5. Ink covers "
                     f"{ag['ink_patch_fraction']:.1%} of patches. Agreement between two models, not ground truth.")
    if view.get("ref_sim") is not None:
        lines.append(f"Patches at or above the organizers' threshold (cosine {lens.TAU}) to their reference: "
                     f"{float((view['ref_sim'] >= lens.TAU).mean()):.1%}.")
    s = click_sim(state)
    if s is not None:
        extra = ""
        if "ink" in view["result"]:
            a = lens.agreement(s, view["result"]["ink"])
            if a["auc"] is not None:
                extra = (f" Against the 3D ink model your concept scores AUC {a['auc']:.2f} "
                         f"(control {a['auc_control_shifted']:.2f}).")
        lines.append(f"**Your concept:** {len(state['pos'])} positive and {len(state['neg'])} negative clicks"
                     f" from {len({c['cube'] for c in state['pos'] + state['neg']})} cube(s). Showing its top "
                     f"{top_pct:g}% of patches.{extra}")
    lines.append(f"[Link to this cube]({view_link(view)}). _Model output, not a reading. A cube is smaller than one "
                 "letter._")
    return "\n\n".join(lines)


def figure_3d(state, overlays, top_pct):
    """Ink and surface as see-through shells and the similar patches as points, in a rotatable 3D plot."""
    import numpy as np
    import plotly.graph_objects as go
    view = state["view"]
    fig = go.Figure()
    if view is None:
        return fig
    from skimage.measure import marching_cubes
    res, size = view["result"], view["size"]
    step = 2 if size <= 128 else 4
    for key, name, color, show in (("surface", "Recto surface", COLORS["surface"], "Recto surface" in overlays),
                                    ("ink", "Ink", COLORS["ink"], "Ink (3D ink model)" in overlays)):
        if not show or key not in res or res[key].max() < 128:
            continue
        verts, faces, _, _ = marching_cubes(res[key].astype(np.float32), level=127.5, step_size=step)
        fig.add_trace(go.Mesh3d(x=verts[:, 2], y=verts[:, 1], z=verts[:, 0], i=faces[:, 0], j=faces[:, 1],
                                k=faces[:, 2], color=f"rgb{color}", opacity=0.35 if key == "surface" else 0.8,
                                name=name, showlegend=True, hoverinfo="skip"))
    for key, name, color in (("clicks", "Your clicks", COLORS["clicks"]),
                              ("reference", "Organizers' ink reference", COLORS["reference"])):
        if (key == "clicks" and "Your clicks" not in overlays) or \
                (key == "reference" and "Organizers' ink reference" not in overlays):
            continue
        s3 = click_sim(state) if key == "clicks" else view.get("ref_sim")
        if s3 is None:
            continue
        thr = np.percentile(s3, 100 - top_pct)
        pts = np.argwhere(s3 >= thr) * lens.PATCH + lens.PATCH / 2
        fig.add_trace(go.Scatter3d(x=pts[:, 2], y=pts[:, 1], z=pts[:, 0], mode="markers", name=name,
                                   marker=dict(size=2.5, color=f"rgb{color}", opacity=0.7), hoverinfo="skip"))
    ax = dict(range=[0, size], showbackground=False, gridcolor="#3a4654", zerolinecolor="#3a4654",
              color="#c9d4de")
    fig.update_layout(scene=dict(xaxis=dict(ax, title="x"), yaxis=dict(ax, title="y"), zaxis=dict(ax, title="z"),
                                 aspectmode="cube", bgcolor="#11161c"),
                      paper_bgcolor="#11161c", font=dict(color="#c9d4de"), height=460,
                      margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=0.02))
    return fig


# ---------------------------------------------------------------- loading cubes

def load_point(vid, z, y, x, size, layers, tta):
    import numpy as np
    size = lens.check_size(size)
    layers = lens.check_layers([{"3D DINO embeddings": "dino", "3D ink model": "ink",
                                 "Recto surface model": "surface"}.get(k, k) for k in layers])
    point = (int(z), int(y), int(x))
    origin = lens.cube_origin(vid, point, size)
    cube = lens.read_cube(vid, origin, size)
    lens.check_cube(cube)
    result, note = run_models(cube, layers, tta)
    src = "gpu" if result.get("device", "").startswith("cuda") else "cpu"
    ran = _center(cube, ran_size(result))      # the CPU fallback runs the middle of the cube
    return new_view(vid, origin, size, point, np.ascontiguousarray(ran), result, src, note)


def ran_size(result):
    """The side of the cube a result covers, from whichever layers it holds."""
    for k in ("ink", "surface"):
        if k in result:
            return int(result[k].shape[0])
    return int(lens.grid_of(result).shape[0] * lens.PATCH)


def load_gallery(cube_id):
    for it in GALLERY:
        if it["id"] == cube_id:
            meta, arrays = lens.load_npz(HERE / "gallery" / it["file"])
            origin, size = tuple(meta["cube_origin_zyx"]), int(meta["cube_size"])
            cube = lens.read_cube(meta["volume"], origin, size)
            result = dict(arrays, seconds=meta.get("seconds", {}), device=meta.get("device"),
                          device_name=meta.get("device_name"), tta=meta.get("tta", False))
            view = new_view(meta["volume"], origin, size, tuple(meta["point_zyx"]), cube, result, "gallery",
                            it.get("note", ""))
            view["receipt"]["gallery_id"] = cube_id
            return view
    raise LensError(f"no gallery cube {cube_id!r}")


def gallery_label(it):
    z, y, x = it["point_zyx"]
    return f"{it['title']} (z {z}, y {y}, x {x}, {it['size']}³)"


def next_gallery_id(cube_id, step=1):
    ids = [it["id"] for it in GALLERY]
    if not ids:
        raise LensError("the gallery is empty")
    i = ids.index(cube_id) if cube_id in ids else -step
    return ids[(i + step) % len(ids)]


def surprise(vid, seed=None):
    import numpy as np
    rng = np.random.default_rng(seed)
    if vid == "PHercParis4":
        return lens.PARIS4_TRAINING_POINTS[int(rng.integers(0, len(lens.PARIS4_TRAINING_POINTS)))]
    return lens.random_point(vid, rng)


# ---------------------------------------------------------------- files to take away

def save_files(state):
    import numpy as np
    view = state["view"]
    if view is None:
        raise LensError("nothing to save yet")
    OUT.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(dir=OUT))
    name = f"scroll-lens-{view['volume']}-{'-'.join(map(str, view['origin']))}-{view['size']}"
    files = [lens.save_npz(d / f"{name}.npz", view["receipt"], view["result"])]
    rec = d / f"{name}.json"
    rec.write_text(json.dumps(view["receipt"], indent=1) + "\n")
    files.append(rec)
    p, n = click_concept(state)
    if p is not None:
        np.save(d / "concept.npy", p.astype(np.float32))
        files.append(d / "concept.npy")
        clicks = {"tool": "Scroll Lens", "version": lens.VERSION, "embedding": lens.MODELS["dino"]["repo"],
                  "positive": [{k: c[k] for k in ("volume", "cube", "voxel_zyx")} for c in state["pos"]],
                  "negative": [{k: c[k] for k in ("volume", "cube", "voxel_zyx")} for c in state["neg"]],
                  "note": "concept.npy is the unit-length mean of the positive clicks' 864-number dinovol embeddings"}
        (d / "clicks.json").write_text(json.dumps(clicks, indent=1) + "\n")
        files.append(d / "clicks.json")
    return [str(f) for f in files]


def look(vid: str, z: int, y: int, x: int, size: int = 256, layers: str = "dino,ink,surface", tta: bool = False,
         compact: bool = False, allow_cpu: bool = False):
    """For batch scripts: run the models on the cube around a point and return its .npz (see lens.save_npz). Uses the
    caller's ZeroGPU time; tools/build_gallery.py builds the gallery with it.

    Args:
        vid: a scan id from list_scans.
        z: the point's z in voxels.
        y: the point's y in voxels.
        x: the point's x in voxels.
        size: the cube's side in voxels, 128 or 256.
        layers: comma-separated models to run: dino, ink, surface.
        tta: average the eight mirrorings for ink and surface (8 times their GPU time).
        compact: keep 128 components of each embedding and 16 levels of each probability (about a quarter the size).
        allow_cpu: when ZeroGPU refuses, run the middle 128 cube on the Space's CPU instead of failing.

    Returns:
        The .npz file.
    """
    import numpy as np
    size = lens.check_size(size)
    layers = lens.check_layers([s.strip() for s in str(layers).split(",") if s.strip()])
    point = (int(z), int(y), int(x))
    origin = lens.cube_origin(vid, point, size)
    cube = lens.read_cube(vid, origin, size)
    lens.check_cube(cube)
    result, note = run_models(cube, layers, bool(tta), allow_cpu=bool(allow_cpu))
    n = ran_size(result)
    if n != size:
        origin = tuple(int(o + (size - n) // 2) for o in origin)
    meta = lens.receipt(vid, origin, n, point, result, ENGINE.describe(), {"source": "api", "note_run": note,
                                                                          "foreground": lens.foreground(cube)})
    if "grid" in result and "ink" in result:
        meta["agreement_with_ink_model"] = lens.agreement(
            lens.similarity(np.asarray(result["grid"], np.float32), REFERENCE), result["ink"])
    OUT.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(dir=OUT))
    return str(lens.save_npz(d / f"{vid}-{'-'.join(map(str, origin))}-{n}.npz", meta, result, compact=bool(compact)))


# ---------------------------------------------------------------- tools for agents (also the API and MCP server)
#
# Each function below is one API endpoint and one MCP tool. They keep no session: a cube is named by a gallery id, or
# by a scan and a point, and every answer carries a link that opens the same cube on the page for a person.

VIEW_CACHE = {}                     # recent cubes, so a search after an inspect does not run the models again
VIEW_CACHE_N = 3
VIEW_LOCK = threading.Lock()
AGENT_OVERLAYS = {"ink": OVERLAYS[0], "surface": OVERLAYS[1], "clicks": OVERLAYS[2], "reference": OVERLAYS[3],
                  "dino": OVERLAYS[4]}


def page_url(query=""):
    host = os.environ.get("SPACE_HOST")
    base = f"https://{host}/" if host else "/"
    return base + (f"?{query}" if query else "")


def view_link(view):
    gid = view["receipt"].get("gallery_id")
    if gid:
        return page_url(f"cube={gid}")
    z, y, x = view["point"]
    return page_url(f"v={view['volume']}&z={z}&y={y}&x={x}&size={view['size']}")


def agent_view(cube_id="", scan="", z=0, y=0, x=0, size=256):
    """A gallery cube (no GPU), or the cube around a point with all three models run on it (GPU, else CPU)."""
    cube_id = str(cube_id or "").strip()
    if cube_id:
        key = ("gallery", cube_id)
    else:
        if not scan:
            raise LensError("give a gallery cube_id, or a scan and a point (z, y, x)")
        lens.volume(scan)
        size = lens.check_size(int(size))
        point = (int(z), int(y), int(x))
        key = ("point", scan, lens.cube_origin(scan, point, size), size)
    with VIEW_LOCK:
        hit = VIEW_CACHE.pop(key, None)
        if hit is not None:
            VIEW_CACHE[key] = hit
            if cube_id:
                return hit
            hit = dict(hit, point=point)    # same cube, another point in it
            hit["receipt"] = dict(hit["receipt"], point_zyx=list(point))
            hit["slices"] = [int(min(max(p - o, 0), hit["size"] - 1)) for p, o in zip(point, hit["origin"])]
            return hit
    view = load_gallery(cube_id) if cube_id else load_point(scan, point[0], point[1], point[2], size,
                                                            list(lens.LAYERS), False)
    with VIEW_LOCK:
        VIEW_CACHE[key] = view
        while len(VIEW_CACHE) > VIEW_CACHE_N:
            VIEW_CACHE.pop(next(iter(VIEW_CACHE)))
    return view


def agent_overlays(text):
    names = [s.strip().lower() for s in str(text or "").split(",") if s.strip()]
    bad = [n for n in names if n not in AGENT_OVERLAYS]
    if bad:
        raise LensError(f"unknown overlays {bad}; choose from {', '.join(AGENT_OVERLAYS)}")
    return [AGENT_OVERLAYS[n] for n in names]


def three_views(state, overlays, top_pct):
    """The three slice views through the current slices, side by side, as one RGB image."""
    import numpy as np
    imgs = [draw_slice(state, a, overlays, top_pct, 0.7) for a in range(3)]
    gap = np.full((imgs[0].shape[0], 8, 3), 255, np.uint8)
    return np.concatenate([imgs[0], gap, imgs[1], gap, imgs[2]], axis=1)


def summary(view):
    """The receipt plus the numbers a person sees beside the images."""
    import numpy as np
    r = dict(view["receipt"])
    r["source"] = view["source"]
    r["slices_zyx"] = [int(s + o) for s, o in zip(view["slices"], view["origin"])]
    r["foreground"] = round(float(view["foreground"]), 4)
    if view.get("ref_sim") is not None:
        r["reference_fraction_at_tau"] = round(float((view["ref_sim"] >= lens.TAU).mean()), 4)
    for k in ("ink", "surface"):
        if k in view["result"]:
            r[f"{k}_voxel_fraction"] = round(float((np.asarray(view["result"][k]) >= 128).mean()), 4)
    if view["note"]:
        r["run_note"] = view["note"]
    r["open_in_browser"] = view_link(view)
    return r


def list_scans():
    """List the twelve scans Scroll Lens can read, with their size and what each model saw of them in training.

    Points are voxel coordinates (z, y, x) at full resolution. On PHerc. Paris 4, prefer the organizers' eight training
    points (`paris4_training_points`), since its text is an open prize.

    Returns:
        A JSON object: `scans` (id, scroll, voxel_um, shape_zyx, note, models_trained_on_this_scroll),
        `paris4_training_points`, `sizes`, `layers`, `version`.
    """
    scans = [{"id": vid, "scroll": v["scroll"], "voxel_um": v["voxel_um"], "shape_zyx": list(v["shape"]),
              "note": v["note"], "models_trained_on_this_scroll": v["role"]} for vid, v in lens.VOLUMES.items()]
    return {"scans": scans, "paris4_training_points": [list(p) for p in lens.PARIS4_TRAINING_POINTS],
            "sizes": list(lens.SIZES), "layers": list(lens.LAYERS), "version": lens.VERSION,
            "note": "Model output, not a reading. A cube is smaller than one letter."}


def list_gallery():
    """List the ready-made gallery cubes. Inspecting or searching a gallery cube needs no GPU.

    Returns:
        A JSON object: `cubes` (id, scan, title, note, point_zyx, size, open_in_browser).
    """
    return {"cubes": [{"id": it["id"], "scan": it["volume"], "title": it["title"], "note": it["note"],
                       "point_zyx": it["point_zyx"], "size": it["size"],
                       "open_in_browser": page_url(f"cube={it['id']}")} for it in GALLERY]}


def random_point(scan: str, seed: int = 0):
    """Pick a point on the papyrus of a scan (a window around it is at least 90% inside the scroll mask).

    Args:
        scan: a scan id from list_scans, such as PHerc0139.
        seed: any whole number; the same seed gives the same point. On PHercParis4 the point is one of the
            organizers' eight training points.

    Returns:
        A JSON object with z, y, x (voxels) and the scan.
    """
    lens.volume(scan)
    z, y, x = surprise(scan, int(seed))
    return {"scan": scan, "z": int(z), "y": int(y), "x": int(x)}


def inspect_cube(cube_id: str = "", scan: str = "", z: int = 0, y: int = 0, x: int = 0, size: int = 256,
                  overlays: str = "ink,reference"):
    """Look at one cube: three slice views through a point, with model overlays, and the cube's numbers.

    Name the cube either by a gallery `cube_id` (no GPU) or by `scan` and a point (z, y, x), which runs the three
    models on the cube around it (a few seconds of the caller's ZeroGPU time; the Space's CPU on a 128 cube when
    that is used up). The slices cut through the point, or the gallery cube's own point.

    Args:
        cube_id: a gallery cube id from list_gallery; leave empty to use scan and point.
        scan: a scan id from list_scans.
        z: the point's z in voxels.
        y: the point's y in voxels.
        x: the point's x in voxels.
        size: the cube's side in voxels, 128 or 256.
        overlays: comma-separated layers to draw: ink (red), surface (green), reference (amber, patches like the
            organizers' ink reference), dino (DINO colors). Empty for the bare scan.

    Returns:
        An image (top, front and side views left to right, a white dotted line where the others cut) and a JSON
        summary: the receipt, the ink reference agreement AUC with its control, layer fractions, and a link
        that opens the same cube on the page.
    """
    view = agent_view(cube_id, scan, z, y, x, size)
    state = {"view": view, "pos": [], "neg": []}
    return three_views(state, agent_overlays(overlays), 8), summary(view)


def search_cube(cube_id: str = "", scan: str = "", z: int = 0, y: int = 0, x: int = 0, size: int = 256,
                 positive: str = "", negative: str = "", concept: str = None, top_k: int = 20):
    """Search a cube for places like some examples: the organizers' recipe, done by clicking on the page.

    Give examples as voxel points (z, y, x) in scan coordinates inside the cube: `positive` for "more like this",
    `negative` for "not this". Or give a concept file (concept.npy, 864 numbers, from the page's Save files or an
    earlier search), which carries a concept from one cube or scan to another. With neither, the organizers' ink
    reference is the concept. Name the cube as in inspect_cube.

    Args:
        cube_id: a gallery cube id from list_gallery; leave empty to use scan and point.
        scan: a scan id from list_scans.
        z: the point's z in voxels, which picks the cube.
        y: the point's y in voxels.
        x: the point's x in voxels.
        size: the cube's side in voxels, 128 or 256.
        positive: example points like "37600,8800,22100; 37610,8790,22120" (z,y,x; separated by semicolons).
        negative: points to steer away from, written the same way.
        concept: a concept.npy file (path or URL) to use instead of positive points.
        top_k: how many best-matching patches to list (1 to 200).

    Returns:
        An image (the three views through the best match, the matching patches in cyan), a JSON summary (the
        best patches with their scan coordinates and scores, the concept's AUC against the 3D ink model with its
        control, and a link to the page), and the concept as concept.npy.
    """
    import numpy as np
    view = agent_view(cube_id, scan, z, y, x, size)
    if "grid" not in view:
        raise LensError("this cube has no DINO embeddings, so it cannot be searched")
    grid = view["grid"].astype(np.float32)
    pos = lens.parse_points(positive)
    neg = lens.parse_points(negative)
    state = {"view": dict(view), "pos": [], "neg": []}
    for kind, pts in (("pos", pos), ("neg", neg)):
        for p in pts:
            vox = lens.voxel_in_cube(p, view["origin"], view["size"])
            state[kind].append({"volume": view["volume"], "cube": cube_key(view), "voxel": vox,
                                "voxel_zyx": list(p), "vec": grid[lens.token_of(vox, view["size"])]})
    if concept:
        if pos:
            raise LensError("give positive points or a concept file, not both")
        state["pos"] = [{"volume": "file", "cube": "file", "voxel": [-1, -1, -1], "voxel_zyx": None,
                         "vec": lens.load_concept(concept)}]
    used = "clicks" if state["pos"] else "reference"
    if used == "reference":
        if neg:
            raise LensError("negative points need positive points or a concept file")
        sim = view["ref_sim"]
        vec = REFERENCE
    else:
        p_vec, n_vec = click_concept(state)
        sim = lens.similarity(grid, p_vec, n_vec)
        vec = p_vec
    matches = lens.top_matches(sim, view["origin"], int(top_k))
    best = matches[0]["center_zyx"]
    state["view"]["slices"] = lens.voxel_in_cube(best, view["origin"], view["size"])
    overlays = [AGENT_OVERLAYS["clicks" if used == "clicks" else "reference"]]
    img = three_views(state, overlays, 8)
    out = summary(state["view"])
    out.update({"concept": "your examples" if used == "clicks" else "the organizers' ink reference",
                "positive_zyx": [list(p) for p in pos], "negative_zyx": [list(p) for p in neg], "matches": matches,
                "score": "cosine to the concept, minus cosine to the negative examples when given"})
    if "ink" in view["result"]:
        out["agreement_with_ink_model"] = lens.agreement(sim, view["result"]["ink"])
    OUT.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(dir=OUT)) / "concept.npy"
    np.save(path, np.asarray(vec, np.float32))
    return img, out, str(path)


def download_cube(cube_id: str = "", scan: str = "", z: int = 0, y: int = 0, x: int = 0, size: int = 256):
    """Get a cube's model outputs as arrays: a .npz with the 3D DINO embeddings (float16, one 864-number unit vector
    per 8³ patch), the 3D ink and recto surface probabilities (uint8 per voxel) and the receipt (JSON). Name the cube
    as in inspect_cube. Read it with numpy.load(allow_pickle=False), or lens.load_npz from the Space's files.

    Args:
        cube_id: a gallery cube id from list_gallery; leave empty to use scan and point.
        scan: a scan id from list_scans.
        z: the point's z in voxels.
        y: the point's y in voxels.
        x: the point's x in voxels.
        size: the cube's side in voxels, 128 or 256.

    Returns:
        The .npz file and its receipt as JSON.
    """
    view = agent_view(cube_id, scan, z, y, x, size)
    paths = save_files({"view": view, "pos": [], "neg": []})
    return paths[0], summary(view)


# ---------------------------------------------------------------- the page

INTRO = """\
**Scroll Lens** shows what three of the Vesuvius Challenge's newest 3D models see inside a carbonized Herculaneum scroll.
It reads a small cube of a public X-ray CT scan straight from the open-data bucket and runs, on that cube:

- **3D DINO embeddings** ([dinovol](https://huggingface.co/scrollprize/dinovol_v2_ps8_with_paris4_352500)): a
  self-supervised model that turns every 8 × 8 × 8 voxel patch into 864 numbers. Patches the model finds alike get
  alike numbers. *DINO colors* paints the three main directions as red, green and blue.
- **3D ink model** ([ink_3d_dino_guided](https://huggingface.co/scrollprize/ink_3d_dino_guided)): marks ink voxels
  directly in the scan, with no flattened surface.
- **Recto surface model** ([surface_recto_3dunet](https://huggingface.co/scrollprize/surface_recto_3dunet)): marks
  the written side of each papyrus sheet.

**Click to search.** With *More like this*, a click takes the embedding of the patch you clicked; every patch with a
similar embedding lights up in cyan. *Not this* subtracts a patch you do not want. This is how the organizers built
their ink reference (*Organizers' ink reference*, in amber): experts clicked ink 256 times and averaged the
embeddings. Your concept follows you to other cubes and scans, so you can click ink in one scroll and look for its
like in another, and you can download it as `concept.npy`.

All three models come from the PHerc. Paris 4 work of the Vesuvius Challenge team
([Angelotti et al. 2026](https://arxiv.org/abs/2606.29085)). Scroll Lens reads only the twelve 2.2 to 2.4 µm scans
those models were made for, none of them eligible for the First Letters or Grand Prize. **Everything shown is model
output, not a reading:** a cube is at most 0.6 mm across, smaller than one letter.
"""

HOW_TO = """\
1. **Gallery** (no GPU needed): pick a ready-made cube and it loads at once.
2. **Your own point**: pick a scan, type a point in voxels (z, y, x) or press **Surprise me**, then **Run the models**.
   A 256³ cube is the models' own working size and uses about half a minute of GPU time; 128³ about a quarter.
   When your daily ZeroGPU time runs out, Scroll Lens runs a 128³ cube on the CPU instead (slower, about a minute).
3. **Look**: drag inside a view to move the crosshair (the other two views follow), scroll the wheel over a view to
   step through its slices (Shift for 8 at a time), or drag the sliders. Tick the layers to show. The white dotted
   lines are where the other two views cut this one.
4. **Search**: choose a click mode, then click a view. Raise or lower *Top % shown* to see more or fewer matches.
   **Undo last click** takes back one click; **Clear clicks** all of them.
5. **Take it away**: **Save files** gives the model outputs (.npz), the receipt (.json) and, after clicks, your
   `concept.npy`. A link with `?v=SCAN&z=…&y=…&x=…` opens the page on a point; `?cube=ID` on a gallery cube.

Agents and scripts can do all of this too: see **For agents and scripts** at the bottom of the page.
"""

AGENTS_TEXT = """\
Everything on this page is also an API endpoint and an MCP tool, so an AI agent or a script can use Scroll Lens
the way a person does. Every answer includes `open_in_browser`, a link that opens the same cube here for a person.

| Tool | What it does | GPU |
| --- | --- | --- |
| `list_scans` | the twelve scans, their sizes, and what each model saw of them in training | no |
| `list_gallery` | the ready-made cubes | no |
| `random_point` | a point on the papyrus of a scan | no |
| `inspect_cube` | three slice views with overlays, and the cube's numbers and checks | gallery: no |
| `search_cube` | places like your example points or concept file (or the organizers' ink reference) | gallery: no |
| `download_cube` | the models' outputs as arrays (.npz) | gallery: no |
| `look` | the .npz for any point, for batch scripts | yes |

**MCP** (Claude, Cursor and other MCP clients): add the server `{url}/gradio_api/mcp/`.
Hugging Face's own MCP settings (huggingface.co/settings/mcp) can add this Space too. Runs on a new point use the
caller's ZeroGPU minutes, so sign the client in with a Hugging Face token.

**Python**:

```python
from gradio_client import Client
lens = Client("SharpMeow/scroll-lens")                     # Client(..., token=...) to use your own GPU minutes
cubes = lens.predict(api_name="/list_gallery")["cubes"]
image, info = lens.predict(cubes[0]["id"], "", 0, 0, 0, 256, "ink,reference", api_name="/inspect_cube")
image, hits, concept = lens.predict(cubes[0]["id"], "", 0, 0, 0, 256, "", "", None, 10, api_name="/search_cube")
```

Model output, not a reading. Scroll Lens reads only the twelve listed scans, none eligible for the First Letters or
Grand Prize.
"""

CSS = """
#sl-views img { image-rendering: pixelated; cursor: crosshair; touch-action: none; user-select: none; }
.sl-head { display:flex; gap:14px; align-items:baseline; flex-wrap:wrap; margin: 4px 0 2px; }
.sl-head h1 { margin:0; font-size: 1.6rem; letter-spacing: .01em; }
.sl-head span { color: var(--body-text-color-subdued); }
.sl-legend { display:flex; flex-wrap:wrap; gap:10px 16px; font-size:.86rem; margin: 2px 0 4px; }
.sl-legend i { display:inline-block; width:11px; height:11px; border-radius:2px; margin-right:5px; vertical-align:-1px; }
@media (max-width: 720px) { #sl-viewer { order: -1; } }   /* phones: the images first, the controls below */
footer.sl-credit { text-align:center; color: var(--body-text-color-subdued); font-size:.85rem; margin-top: 8px; }
"""

# Mouse and touch on the three views. Dragging moves the crosshair: the other two slices follow the pointer. The wheel
# steps through this view's slice (Shift for 8 at a time). Both set the sliders, which redraw the views as they move. A
# click without a drag still does what "Clicking a view does" says.
GESTURES = """
<script>
(() => {
  const DRAG_PX = 4;
  let drag = null, swallowClick = false;
  const viewOf = (el) => { const v = el && el.closest && el.closest('[id^="sl-v"]'); return v ? +v.id.slice(4) : -1; };
  const range = (a) => document.querySelector('#sl-s' + a + ' input[type="range"]');
  function setSlider(a, value) {
    const r = range(a);
    if (!r) return;
    const v = Math.max(+r.min, Math.min(+r.max, Math.round(value)));
    if (+r.value === v) return;
    r.value = v;
    r.dispatchEvent(new Event('input', {bubbles: true}));
  }
  function release(a) {
    const r = range(a);
    if (r) { r.dispatchEvent(new Event('change', {bubbles: true})); r.dispatchEvent(new PointerEvent('pointerup', {bubbles: true})); }
  }
  function moveTo(d, e) {
    const box = d.img.getBoundingClientRect(), n = +range(d.axis).max + 1;
    const others = [0, 1, 2].filter((a) => a !== d.axis);
    setSlider(others[0], (e.clientY - box.top) / box.height * n);
    setSlider(others[1], (e.clientX - box.left) / box.width * n);
  }
  document.addEventListener('pointerdown', (e) => {
    const a = viewOf(e.target);
    if (a < 0 || e.target.tagName !== 'IMG' || e.button !== 0) return;
    drag = {axis: a, img: e.target, x: e.clientX, y: e.clientY, moved: false};
    e.preventDefault();
  });
  document.addEventListener('pointermove', (e) => {
    if (!drag) return;
    if (!drag.moved && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < DRAG_PX) return;
    drag.moved = true;
    moveTo(drag, e);
  });
  document.addEventListener('pointerup', () => {
    if (drag && drag.moved) {
      swallowClick = true;
      [0, 1, 2].filter((a) => a !== drag.axis).forEach(release);
      setTimeout(() => { swallowClick = false; }, 300);
    }
    drag = null;
  });
  document.addEventListener('click', (e) => {
    if (swallowClick && viewOf(e.target) >= 0) { e.stopPropagation(); e.preventDefault(); swallowClick = false; }
  }, true);
  document.addEventListener('dragstart', (e) => { if (viewOf(e.target) >= 0) e.preventDefault(); });
  let wheelTimer = null;
  document.addEventListener('wheel', (e) => {
    const a = viewOf(e.target);
    if (a < 0 || e.target.tagName !== 'IMG') return;
    e.preventDefault();
    const r = range(a);
    if (!r) return;
    setSlider(a, +r.value + Math.sign(e.deltaY) * (e.shiftKey ? 8 : 1));
    clearTimeout(wheelTimer);
    wheelTimer = setTimeout(() => release(a), 250);
  }, {passive: false});
})();
</script>
"""


def fix_mcp_multiple_outputs():
    """Gradio 6.28's MCP server joins a queued tool's several outputs into one text, so inspect_cube's image never
    reached an agent as an image. Hand them over one by one, as its unqueued path already does."""
    try:
        from gradio.mcp import GradioMCPServer
        from anyio.to_thread import run_sync
    except ImportError:
        return

    async def without_progress(self, job):
        result = await run_sync(job.result)
        return list(result) if isinstance(result, tuple) else [result]

    GradioMCPServer._execute_tool_without_progress = without_progress


LEGEND = ('<div class="sl-legend">' + "".join(
    f'<span><i style="background:rgb{c}"></i>{t}</span>' for t, c in (
        ("Ink, 3D ink model", COLORS["ink"]), ("Recto surface", COLORS["surface"]),
        ("Like your clicks", COLORS["clicks"]), ("Like the organizers' ink reference", COLORS["reference"]),
        ("Your clicks: white +, Not this: magenta +", MARKS["neg"]))) + "</div>")


def theme():
    import gradio as gr
    return gr.themes.Base(primary_hue="amber", neutral_hue="slate", radius_size="sm",
                          font=("system-ui", "sans-serif"), font_mono=("ui-monospace", "monospace"))


def build_demo():
    import gradio as gr

    vol_choices = [(f"{v['scroll']} ({vid})", vid) for vid, v in lens.VOLUMES.items()]
    gal_choices = [(gallery_label(it), it["id"]) for it in GALLERY]
    layer_names = [lens.LAYER_TITLES[k] for k in lens.LAYERS]

    def volume_text(vid):
        v = lens.volume(vid)
        z, y, x = v["shape"]
        return (f"{v['note']} Scan: {v['voxel_um']} µm voxels, {z:,} × {y:,} × {x:,} (z, y, x). "
                f"[Open data]({lens.BUCKET}/{vid}/volumes/{v['scan']}/)").strip()

    def show(state, overlays, top_pct, opacity):
        return ([draw_slice(state, a, overlays, top_pct, opacity) for a in range(3)]
                + [numbers(state, top_pct)])

    def slider_updates(state):
        view = state["view"]
        if view is None:
            return [gr.update()] * 3
        return [gr.update(maximum=view["size"] - 1, value=view["slices"][a]) for a in range(3)]

    def guard(fn):
        @functools.wraps(fn)          # keeps fn's signature, so gradio still passes SelectData and Request
        def wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except LensError as exc:
                raise gr.Error(str(exc)) from None
        return wrapped

    @guard
    def on_run(vid, z, y, x, size, layers, tta, state, overlays, top_pct, opacity):
        state = dict(state)
        state["view"] = load_point(vid, z, y, x, size, layers, tta)
        return [state] + slider_updates(state) + show(state, overlays, top_pct, opacity)

    @guard
    def on_gallery(cube_id, state, overlays, top_pct, opacity):
        if not cube_id:
            raise LensError("pick a gallery cube")
        state = dict(state)
        state["view"] = load_gallery(cube_id)
        p = state["view"]["point"]
        return ([state] + slider_updates(state) + show(state, overlays, top_pct, opacity)
                + [state["view"]["volume"], p[0], p[1], p[2]])

    @guard
    def on_surprise(vid):
        z, y, x = surprise(vid)
        return z, y, x

    @guard
    def on_slices(sz, sy, sx, state, overlays, top_pct, opacity):
        if state["view"] is not None:
            state["view"]["slices"] = [int(sz), int(sy), int(sx)]
        return show(state, overlays, top_pct, opacity)

    def on_drag(sz, sy, sx, state, overlays, top_pct, opacity):
        """The three views only, for the live redraw while a slider is dragged (the text waits for the release)."""
        view = state["view"]
        if view is None:
            return [gr.update()] * 3
        view["slices"] = [int(sz), int(sy), int(sx)]
        return [draw_slice(state, a, overlays, top_pct, opacity) for a in range(3)]

    def on_select(axis):
        @guard
        def handler(mode, state, overlays, top_pct, opacity, evt: gr.SelectData):
            view = state["view"]
            if view is None or evt.index is None:
                return [state] + slider_updates(state) + show(state, overlays, top_pct, opacity) + [overlays]
            f = scale_of(view["size"])
            col, row = int(evt.index[0]) // f, int(evt.index[1]) // f
            others = [a for a in range(3) if a != axis]
            vox = [0, 0, 0]
            vox[axis] = view["slices"][axis]
            vox[others[0]], vox[others[1]] = row, col
            vox = [int(min(max(v, 0), view["size"] - 1)) for v in vox]
            if mode == CLICK_MODES[2]:
                view["slices"] = vox
                return [state] + slider_updates(state) + show(state, overlays, top_pct, opacity) + [overlays]
            if "grid" not in view:
                raise LensError("this cube has no DINO embeddings; run it with the 3D DINO model to search by "
                                "clicking")
            tok = lens.token_of(vox, view["size"])
            vec = view["grid"][tok].astype("float32")
            kind = "pos" if mode == CLICK_MODES[0] else "neg"
            n = 1 + max([c.get("n", 0) for c in state["pos"] + state["neg"]] or [0])
            state[kind] = state[kind] + [{"n": n, "volume": view["volume"], "cube": cube_key(view), "voxel": vox,
                                          "voxel_zyx": [int(v + o) for v, o in zip(vox, view["origin"])],
                                          "vec": vec}]
            if "Your clicks" not in overlays:
                overlays = list(overlays) + ["Your clicks"]
            return [state] + slider_updates(state) + show(state, overlays, top_pct, opacity) + [overlays]
        return handler

    @guard
    def on_clear(state, overlays, top_pct, opacity):
        state = dict(state, pos=[], neg=[])
        return [state] + show(state, overlays, top_pct, opacity)

    @guard
    def on_undo(state, overlays, top_pct, opacity):
        clicks = state["pos"] + state["neg"]
        if clicks:
            last = max(clicks, key=lambda c: c.get("n", 0))
            state = dict(state, pos=[c for c in state["pos"] if c is not last],
                         neg=[c for c in state["neg"] if c is not last])
        return [state] + show(state, overlays, top_pct, opacity)

    @guard
    def on_concept(path, state, overlays, top_pct, opacity):
        if not path:
            return [state] + show(state, overlays, top_pct, opacity) + [overlays]
        vec = lens.load_concept(path)
        state = dict(state, pos=[{"volume": "file", "cube": "file", "voxel": [-1, -1, -1], "voxel_zyx": None,
                                  "vec": vec}], neg=[])
        if "Your clicks" not in overlays:
            overlays = list(overlays) + ["Your clicks"]
        return [state] + show(state, overlays, top_pct, opacity) + [overlays]

    @guard
    def on_save(state):
        return save_files(state), (state["view"] or {}).get("receipt")

    def on_load(state, overlays, top_pct, opacity, request: gr.Request):
        q = dict(request.query_params) if request else {}
        fields = [gr.update()] * 4
        try:
            if q.get("v") in lens.VOLUMES:
                fields = [q["v"]] + [int(q[k]) if str(q.get(k, "")).isdigit() else gr.update() for k in "zyx"]
            cube_id = q.get("cube") or ((not q.get("v")) and GALLERY and GALLERY[0]["id"])
            if cube_id:
                state = dict(state)
                state["view"] = load_gallery(cube_id)
                if not q.get("v"):
                    p = state["view"]["point"]
                    fields = [state["view"]["volume"], p[0], p[1], p[2]]
        except (LensError, ValueError, OSError) as exc:
            log(f"link not loaded: {exc}")
        size = gr.update(value=int(q["size"])) if q.get("size") in ("128", "256") else gr.update()
        return ([state] + slider_updates(state) + show(state, overlays, top_pct, opacity) + fields + [size]
                + [gr.update(value=state["view"] and state["view"].get("receipt", {}).get("gallery_id"))])

    with gr.Blocks(title="Scroll Lens", delete_cache=(1800, 3600)) as demo:
        state = gr.State(empty_state(), time_to_live=STATE_TTL_S)
        gr.HTML('<div class="sl-head"><h1>Scroll Lens</h1><span>Look inside a Herculaneum scroll with the '
                'Vesuvius Challenge’s 3D models: embeddings, ink and surfaces, and click to search.</span></div>')
        with gr.Row(equal_height=False):
            with gr.Column(scale=1, min_width=300, elem_id="sl-controls"):
                with gr.Tab("Gallery"):
                    gpick = gr.Dropdown(gal_choices, value=gal_choices[0][1] if gal_choices else None,
                                        label=f"Ready-made cube, {len(gal_choices)} in all (no GPU needed; "
                                              "type to filter)", filterable=True)
                    with gr.Row():
                        gprev = gr.Button("◀ Previous", size="sm", min_width=80)
                        gnext = gr.Button("Next ▶", size="sm", min_width=80)
                    if not gal_choices:
                        gr.Markdown("The gallery is empty on this copy. Pick a point instead.")
                with gr.Tab("Your own point"):
                    vid = gr.Dropdown(vol_choices, value="PHercParis4", label="Scan", filterable=False)
                    vinfo = gr.Markdown(volume_text("PHercParis4"))
                    with gr.Row():
                        z = gr.Number(37628, label="z", precision=0, minimum=0)
                        y = gr.Number(8793, label="y", precision=0, minimum=0)
                        x = gr.Number(22167, label="x", precision=0, minimum=0)
                    size = gr.Radio([128, 256], value=256, label="Cube side, voxels")
                    layers = gr.CheckboxGroup(layer_names, value=layer_names, label="Models to run")
                    tta = gr.Checkbox(False, label="Average eight mirrorings for ink and surface (slower, smoother)")
                    with gr.Row():
                        sbtn = gr.Button("Surprise me")
                        rbtn = gr.Button("Run the models", variant="primary")
                with gr.Accordion("Show and search", open=True):
                    overlays = gr.CheckboxGroup(list(OVERLAYS), value=["Ink (3D ink model)", "Your clicks",
                                                                       "Organizers' ink reference"],
                                                label="Layers to show")
                    mode = gr.Radio(list(CLICK_MODES), value=CLICK_MODES[0], label="Clicking a view does")
                    top_pct = gr.Slider(1, 40, value=8, step=1, label="Top % of similar patches shown")
                    opacity = gr.Slider(0, 1, value=0.7, step=0.05, label="Layer opacity")
                    with gr.Row():
                        undo = gr.Button("Undo last click", size="sm")
                        clear = gr.Button("Clear clicks", size="sm")
                    concept_up = gr.UploadButton("Load a concept.npy (864 numbers)", file_types=[".npy"],
                                                 type="filepath", size="sm")
                with gr.Accordion("How to use it", open=False):
                    gr.Markdown(HOW_TO)
            with gr.Column(scale=3, min_width=320, elem_id="sl-viewer"):
                gr.HTML(LEGEND)
                with gr.Row(elem_id="sl-views"):
                    imgs = [gr.Image(label=VIEW_NAMES[a], interactive=False, buttons=["fullscreen"], type="numpy",
                                     elem_id=f"sl-v{a}",
                                     min_width=220)
                            for a in range(3)]
                with gr.Row():
                    sliders = [gr.Slider(0, 255, value=128, step=1, label=n.split(" (")[1].rstrip(")") + " slice",
                                         elem_id=f"sl-s{a}")
                               for a, n in enumerate(VIEW_NAMES)]
                info = gr.Markdown(numbers(empty_state(), 8))
                with gr.Accordion("3D view", open=False):
                    plot = gr.Plot(label="Ink and surface shells, similar patches as points")
                    pbtn = gr.Button("Draw in 3D", size="sm")
                with gr.Accordion("Save files", open=False):
                    save = gr.Button("Save files", size="sm")
                    files = gr.File(label="Model outputs, receipt and your concept", file_count="multiple")
                    receipt = gr.JSON(label="Receipt")
                with gr.Accordion("About", open=False):
                    gr.Markdown(INTRO)
                with gr.Accordion("For agents and scripts", open=False):
                    gr.Markdown(AGENTS_TEXT.format(url=page_url().rstrip("/") if page_url() != "/" else
                                                   "https://sharpmeow-scroll-lens.hf.space"))
        gr.HTML('<footer class="sl-credit">Built by Chase Hendrick · models and data by the Vesuvius Challenge · '
                f'Scroll Lens {lens.VERSION}</footer>')

        # hidden: the API endpoints and MCP tools for scripts and agents
        with gr.Row(visible=False):
            a_vid, a_layers = gr.Textbox(), gr.Textbox(value="dino,ink,surface")
            a_z, a_y, a_x, a_size = gr.Number(precision=0), gr.Number(precision=0), gr.Number(precision=0), \
                gr.Number(256, precision=0)
            a_tta, a_compact, a_cpu = gr.Checkbox(False), gr.Checkbox(False), gr.Checkbox(False)
            a_out, a_btn = gr.File(), gr.Button()
            t_id, t_scan = gr.Textbox("", label="cube_id"), gr.Textbox("", label="scan")
            t_z, t_y, t_x = (gr.Number(0, precision=0, label=k) for k in "zyx")
            t_size, t_seed = gr.Number(256, precision=0, label="size"), gr.Number(0, precision=0, label="seed")
            t_over = gr.Textbox("ink,reference", label="overlays")
            t_pos, t_neg = gr.Textbox("", label="positive"), gr.Textbox("", label="negative")
            t_concept = gr.File(label="concept", file_types=[".npy"], type="filepath")
            t_k = gr.Number(20, precision=0, label="top_k")
            t_img, t_json, t_file = gr.Image(type="numpy", format="png"), gr.JSON(), gr.File()
            t_btns = [gr.Button() for _ in range(6)]

        view_inputs = [overlays, top_pct, opacity]
        shown = imgs + [info]
        vid.change(volume_text, vid, vinfo, api_visibility="private")
        rbtn.click(on_run, [vid, z, y, x, size, layers, tta, state] + view_inputs, [state] + sliders + shown,
                   concurrency_id="models", concurrency_limit=2, api_visibility="private")
        gal_out = [state] + sliders + shown + [vid, z, y, x]
        gpick.input(on_gallery, [gpick, state] + view_inputs, gal_out, api_visibility="private")
        for b, step in ((gprev, -1), (gnext, 1)):
            b.click(lambda c, s=step: next_gallery_id(c, s), gpick, gpick, api_visibility="private",
                    queue=False).then(on_gallery, [gpick, state] + view_inputs, gal_out, api_visibility="private")
        sbtn.click(on_surprise, vid, [z, y, x], api_visibility="private")
        for s in sliders:
            # redraw while the slider moves: only the newest position is drawn, so a fast drag never queues up
            s.input(on_drag, sliders + [state] + view_inputs, imgs, api_visibility="private", show_progress="hidden",
                    trigger_mode="always_last", queue=False)
            s.release(on_slices, sliders + [state] + view_inputs, shown, api_visibility="private", show_progress="hidden")
        for c in view_inputs:
            c.change(on_slices, sliders + [state] + view_inputs, shown, api_visibility="private", show_progress="hidden")
        for a in range(3):
            imgs[a].select(on_select(a), [mode, state] + view_inputs, [state] + sliders + shown + [overlays],
                           api_visibility="private", show_progress="hidden")
        clear.click(on_clear, [state] + view_inputs, [state] + shown, api_visibility="private")
        undo.click(on_undo, [state] + view_inputs, [state] + shown, api_visibility="private")
        concept_up.upload(on_concept, [concept_up, state] + view_inputs, [state] + shown + [overlays],
                          api_visibility="private")
        pbtn.click(lambda s, o, t: figure_3d(s, o, t), [state, overlays, top_pct], plot, api_visibility="private")
        save.click(on_save, state, [files, receipt], api_visibility="private")
        a_btn.click(guard(look), [a_vid, a_z, a_y, a_x, a_size, a_layers, a_tta, a_compact, a_cpu], a_out,
                    api_name="look", concurrency_id="models", concurrency_limit=2)
        cube_in = [t_id, t_scan, t_z, t_y, t_x, t_size]
        for btn, fn, ins, outs, name in (
                (t_btns[0], list_scans, [], t_json, "list_scans"),
                (t_btns[1], list_gallery, [], t_json, "list_gallery"),
                (t_btns[2], random_point, [t_scan, t_seed], t_json, "random_point"),
                (t_btns[3], inspect_cube, cube_in + [t_over], [t_img, t_json], "inspect_cube"),
                (t_btns[4], search_cube, cube_in + [t_pos, t_neg, t_concept, t_k], [t_img, t_json, t_file],
                 "search_cube"),
                (t_btns[5], download_cube, cube_in, [t_file, t_json], "download_cube")):
            models = name in ("inspect_cube", "search_cube", "download_cube")
            btn.click(guard(fn), ins, outs, api_name=name, api_description=fn.__doc__.split("\n\n")[0],
                      concurrency_id="models" if models else None, concurrency_limit=2 if models else 8)
        demo.load(on_load, [state] + view_inputs, [state] + sliders + shown + [vid, z, y, x, size, gpick],
                  api_visibility="private")
    return demo


if __name__ == "__main__":
    startup()
    fix_mcp_multiple_outputs()
    build_demo().queue(max_size=24).launch(theme=theme(), css=CSS, head=GESTURES, footer_links=["api", "gradio"],
                                           mcp_server=True)
