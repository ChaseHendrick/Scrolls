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
REFERENCE = None                    # the organisers' reference ink embedding, loaded before the models
GALLERY = []

OVERLAYS = ("Ink (3D ink model)", "Recto surface", "Your clicks", "Organisers' ink reference", "DINO colours")
CLICK_MODES = ("More like this", "Not this", "Move the slices here")
VIEW_NAMES = ("Top view (z)", "Front view (y)", "Side view (x)")
COLOURS = {"ink": (235, 64, 52), "surface": (64, 200, 96), "clicks": (40, 220, 235), "reference": (250, 180, 30)}
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
            return eng.run(_centre(cube, CPU_SIZE), layers, device="cpu", tta=False), note
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu" and cube.shape[0] > CPU_SIZE:
        return (eng.run(_centre(cube, CPU_SIZE), layers, device="cpu", tta=False),
                f"No GPU here, so the models ran on the CPU on the middle {CPU_SIZE}³ voxels.")
    return eng.run(cube, layers, device=device, tta=tta), ""


def _centre(cube, size):
    if cube.shape[0] <= size:
        return cube
    o = (cube.shape[0] - size) // 2
    return cube[o:o + size, o:o + size, o:o + size]


# ---------------------------------------------------------------- one cube in memory

def new_view(vid, origin, size, point, cube, result, source, note=""):
    """Everything the page needs about the cube on screen. Arrays only; it lives in the visitor's session."""
    import numpy as np
    if cube.shape[0] != size:                      # the CPU fallback ran a smaller cube at the centre
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

    def blend(colour, alpha):
        a = (np.asarray(alpha, np.float32) * opacity)[..., None]
        rgb[:] = rgb * (1 - a) + (np.asarray(colour, np.float32) / 255.0) * a

    if "DINO colours" in overlays and "grid" in view:
        if view["pca"] is None:
            view["pca"] = lens.pca_colours(view["grid"].astype(np.float32))
        pc = up(_take(view["pca"], axis, tok_i)).astype(np.float32) / 255.0
        rgb[:] = rgb * (1 - 0.6 * opacity) + pc * (0.6 * opacity)
    if "Recto surface" in overlays and "surface" in res:
        blend(COLOURS["surface"], _take(res["surface"], axis, idx) / 255.0)
    if "Ink (3D ink model)" in overlays and "ink" in res:
        blend(COLOURS["ink"], _take(res["ink"], axis, idx) / 255.0)
    if "Organisers' ink reference" in overlays and view.get("ref_sim") is not None:
        s3 = view["ref_sim"]
        blend(COLOURS["reference"], up(_top_alpha(_take(s3, axis, tok_i), s3, top_pct)))
    if "Your clicks" in overlays:
        s3 = click_sim(state)
        if s3 is not None:
            blend(COLOURS["clicks"], up(_top_alpha(_take(s3, axis, tok_i), s3, top_pct)))
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
    for kind, colour in (("pos", MARKS["pos"]), ("neg", MARKS["neg"])):
        for ck in state[kind]:
            if ck.get("cube") != cube_key(view):
                continue
            v = ck["voxel"]
            if v[axis] // lens.PATCH != tok_i:
                continue
            rr, cc = v[others[0]] * f, v[others[1]] * f
            _mark(img, rr + f // 2, cc + f // 2, colour, 5 * f // 2 + 3)
    return img


def _mark(img, r, c, colour, half):
    """A cross two pixels thick, drawn in place."""
    h, w = img.shape[:2]
    for d in range(-half, half + 1):
        for t in (0, 1):
            for (y, x) in ((r + d, c + t), (r + t, c + d)):
                if 0 <= y < h and 0 <= x < w:
                    img[y, x] = colour


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
        lines.append(f"**Check.** The organisers' ink reference picks out the patches the 3D ink model marks as ink "
                     f"with AUC {ag['auc']:.2f}; the control (ink mask moved half a cube) gives "
                     f"{ag['auc_control_shifted']:.2f} and should sit near 0.5. Ink covers "
                     f"{ag['ink_patch_fraction']:.1%} of patches. Agreement between two models, not ground truth.")
    if view.get("ref_sim") is not None:
        lines.append(f"Patches at or above the organisers' threshold (cosine {lens.TAU}) to their reference: "
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
    lines.append("_Model output, not a reading. A cube is smaller than one letter._")
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
    for key, name, colour, show in (("surface", "Recto surface", COLOURS["surface"], "Recto surface" in overlays),
                                    ("ink", "Ink", COLOURS["ink"], "Ink (3D ink model)" in overlays)):
        if not show or key not in res or res[key].max() < 128:
            continue
        verts, faces, _, _ = marching_cubes(res[key].astype(np.float32), level=127.5, step_size=step)
        fig.add_trace(go.Mesh3d(x=verts[:, 2], y=verts[:, 1], z=verts[:, 0], i=faces[:, 0], j=faces[:, 1],
                                k=faces[:, 2], color=f"rgb{colour}", opacity=0.35 if key == "surface" else 0.8,
                                name=name, showlegend=True, hoverinfo="skip"))
    for key, name, colour in (("clicks", "Your clicks", COLOURS["clicks"]),
                              ("reference", "Organisers' ink reference", COLOURS["reference"])):
        if (key == "clicks" and "Your clicks" not in overlays) or \
                (key == "reference" and "Organisers' ink reference" not in overlays):
            continue
        s3 = click_sim(state) if key == "clicks" else view.get("ref_sim")
        if s3 is None:
            continue
        thr = np.percentile(s3, 100 - top_pct)
        pts = np.argwhere(s3 >= thr) * lens.PATCH + lens.PATCH / 2
        fig.add_trace(go.Scatter3d(x=pts[:, 2], y=pts[:, 1], z=pts[:, 0], mode="markers", name=name,
                                   marker=dict(size=2.5, color=f"rgb{colour}", opacity=0.7), hoverinfo="skip"))
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
    ran = _centre(cube, ran_size(result))      # the CPU fallback runs the middle of the cube
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


def api_look(vid, z, y, x, size, layers, tta, compact, allow_cpu):
    """For scripts and agents: run the models on one cube and return its .npz (see lens.save_npz)."""
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


# ---------------------------------------------------------------- the page

INTRO = """\
**Scroll Lens** shows what three of the Vesuvius Challenge's newest 3D models see inside a carbonized Herculaneum scroll.
It reads a small cube of a public X-ray CT scan straight from the open-data bucket and runs, on that cube:

- **3D DINO embeddings** ([dinovol](https://huggingface.co/scrollprize/dinovol_v2_ps8_with_paris4_352500)): a
  self-supervised model that turns every 8 × 8 × 8 voxel patch into 864 numbers. Patches the model finds alike get
  alike numbers. *DINO colours* paints the three main directions as red, green and blue.
- **3D ink model** ([ink_3d_dino_guided](https://huggingface.co/scrollprize/ink_3d_dino_guided)): marks ink voxels
  directly in the scan, with no flattened surface.
- **Recto surface model** ([surface_recto_3dunet](https://huggingface.co/scrollprize/surface_recto_3dunet)): marks
  the written side of each papyrus sheet.

**Click to search.** With *More like this*, a click takes the embedding of the patch you clicked; every patch with a
similar embedding lights up in cyan. *Not this* subtracts a patch you do not want. This is how the organisers built
their ink reference (*Organisers' ink reference*, in amber): experts clicked ink 256 times and averaged the
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
3. **Look**: drag the three sliders to move through the cube; tick the layers to show. The white dotted lines are
   where the other two views cut this one.
4. **Search**: choose a click mode, then click a view. Raise or lower *Top % shown* to see more or fewer matches.
5. **Take it away**: **Save files** gives the model outputs (.npz), the receipt (.json) and, after clicks, your
   `concept.npy`. A link with `?v=SCAN&z=…&y=…&x=…` opens the page on a point; `?cube=ID` on a gallery cube.

Scripts can call the `look` endpoint (`gradio_client`, see the README) to get the same .npz for any listed point.
"""

CSS = """
#sl-views img { image-rendering: pixelated; cursor: crosshair; }
.sl-head { display:flex; gap:14px; align-items:baseline; flex-wrap:wrap; margin: 4px 0 2px; }
.sl-head h1 { margin:0; font-size: 1.6rem; letter-spacing: .01em; }
.sl-head span { color: var(--body-text-color-subdued); }
.sl-legend { display:flex; flex-wrap:wrap; gap:10px 16px; font-size:.86rem; margin: 2px 0 4px; }
.sl-legend i { display:inline-block; width:11px; height:11px; border-radius:2px; margin-right:5px; vertical-align:-1px; }
@media (max-width: 720px) { #sl-viewer { order: -1; } }   /* phones: the images first, the controls below */
footer.sl-credit { text-align:center; color: var(--body-text-color-subdued); font-size:.85rem; margin-top: 8px; }
"""

LEGEND = ('<div class="sl-legend">' + "".join(
    f'<span><i style="background:rgb{c}"></i>{t}</span>' for t, c in (
        ("Ink, 3D ink model", COLOURS["ink"]), ("Recto surface", COLOURS["surface"]),
        ("Like your clicks", COLOURS["clicks"]), ("Like the organisers' ink reference", COLOURS["reference"]),
        ("Your clicks: white +, Not this: magenta +", MARKS["neg"]))) + "</div>")


def theme():
    import gradio as gr
    return gr.themes.Base(primary_hue="amber", neutral_hue="slate", radius_size="sm",
                          font=("system-ui", "sans-serif"), font_mono=("ui-monospace", "monospace"))


def build_demo():
    import gradio as gr

    vol_choices = [(f"{v['scroll']} ({vid})", vid) for vid, v in lens.VOLUMES.items()]
    gal_choices = [(it["title"], it["id"]) for it in GALLERY]
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
            state[kind] = state[kind] + [{"volume": view["volume"], "cube": cube_key(view), "voxel": vox,
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
                                        label="Ready-made cube (no GPU needed)", filterable=False)
                    gbtn = gr.Button("Load cube", variant="primary")
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
                                                                       "Organisers' ink reference"],
                                                label="Layers to show")
                    mode = gr.Radio(list(CLICK_MODES), value=CLICK_MODES[0], label="Clicking a view does")
                    top_pct = gr.Slider(1, 40, value=8, step=1, label="Top % of similar patches shown")
                    opacity = gr.Slider(0, 1, value=0.7, step=0.05, label="Layer opacity")
                    with gr.Row():
                        clear = gr.Button("Clear clicks", size="sm")
                    concept_up = gr.File(label="Load a concept.npy (864 numbers)", file_types=[".npy"],
                                         type="filepath", height=90)
                with gr.Accordion("How to use it", open=False):
                    gr.Markdown(HOW_TO)
            with gr.Column(scale=3, min_width=320, elem_id="sl-viewer"):
                gr.HTML(LEGEND)
                with gr.Row(elem_id="sl-views"):
                    imgs = [gr.Image(label=VIEW_NAMES[a], interactive=False, buttons=["fullscreen"], type="numpy",
                                     min_width=220)
                            for a in range(3)]
                with gr.Row():
                    sliders = [gr.Slider(0, 255, value=128, step=1, label=n.split(" (")[1].rstrip(")") + " slice")
                               for n in VIEW_NAMES]
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
        gr.HTML('<footer class="sl-credit">Built by Chase Hendrick · models and data by the Vesuvius Challenge · '
                f'Scroll Lens {lens.VERSION}</footer>')

        # hidden: the API endpoint for scripts and agents
        with gr.Row(visible=False):
            a_vid, a_layers = gr.Textbox(), gr.Textbox(value="dino,ink,surface")
            a_z, a_y, a_x, a_size = gr.Number(precision=0), gr.Number(precision=0), gr.Number(precision=0), \
                gr.Number(256, precision=0)
            a_tta, a_compact, a_cpu = gr.Checkbox(False), gr.Checkbox(False), gr.Checkbox(False)
            a_out, a_btn = gr.File(), gr.Button()

        view_inputs = [overlays, top_pct, opacity]
        shown = imgs + [info]
        vid.change(volume_text, vid, vinfo, api_visibility="private")
        rbtn.click(on_run, [vid, z, y, x, size, layers, tta, state] + view_inputs, [state] + sliders + shown,
                   concurrency_id="models", concurrency_limit=2, api_visibility="private")
        gbtn.click(on_gallery, [gpick, state] + view_inputs, [state] + sliders + shown + [vid, z, y, x],
                   api_visibility="private")
        sbtn.click(on_surprise, vid, [z, y, x], api_visibility="private")
        for s in sliders:
            s.release(on_slices, sliders + [state] + view_inputs, shown, api_visibility="private", show_progress="hidden")
        for c in view_inputs:
            c.change(on_slices, sliders + [state] + view_inputs, shown, api_visibility="private", show_progress="hidden")
        for a in range(3):
            imgs[a].select(on_select(a), [mode, state] + view_inputs, [state] + sliders + shown + [overlays],
                           api_visibility="private", show_progress="hidden")
        clear.click(on_clear, [state] + view_inputs, [state] + shown, api_visibility="private")
        concept_up.change(on_concept, [concept_up, state] + view_inputs, [state] + shown + [overlays],
                          api_visibility="private")
        pbtn.click(lambda s, o, t: figure_3d(s, o, t), [state, overlays, top_pct], plot, api_visibility="private")
        save.click(on_save, state, [files, receipt], api_visibility="private")
        a_btn.click(guard(api_look), [a_vid, a_z, a_y, a_x, a_size, a_layers, a_tta, a_compact, a_cpu], a_out,
                    api_name="look", concurrency_id="models", concurrency_limit=2)
        demo.load(on_load, [state] + view_inputs, [state] + sliders + shown + [vid, z, y, x, size, gpick],
                  api_visibility="private")
    return demo


if __name__ == "__main__":
    startup()
    build_demo().queue(max_size=24).launch(theme=theme(), css=CSS, footer_links=["api", "gradio"])
