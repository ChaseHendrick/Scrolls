"""Scroll Lens: look inside a Herculaneum scroll scan with the Vesuvius Challenge's 3D models.

The web page and the API. Everything that is not the page (reading the scans, the models, clicks and scores) is in
lens.py, and the slice views are drawn in the visitor's browser by viewer.js. On a ZeroGPU Space the GPU is attached
only to `gpu_run`; when the visitor's GPU quota is used up, or no GPU is free, the same models run on the Space's CPU
on a smaller cube instead. Gallery cubes need no GPU at all.

  python3 app.py            serve the page (on a Space, or on any computer: it then runs on CUDA if present, else CPU)
"""

import base64
import collections
import functools
import gzip
import json
import os
import sys
import tempfile
import threading
import time
import uuid
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
VIEW_DIR = Path(tempfile.gettempdir()) / "scroll-lens-view"   # model layers for the browser viewer, served by Gradio
CPU_SIZE = 128                      # the cube side the CPU fallback runs
STATE_TTL_S = 30 * 60               # a visitor's session state is dropped after this long without use
CACHE_CUBES = 12                    # cubes whose model outputs stay in memory, shared by every visitor
SIM_SCALE = 8192                    # similarity maps travel to the browser as int16 of similarity times this
TOP_FLOOR = 0.35                    # opacity of the least similar patch still inside Top %
ENGINE = None
ENGINE_ERROR = None
READY = threading.Event()
REFERENCE = None                    # the organizers' reference ink embedding, loaded before the models
GALLERY = []

OVERLAYS = ("Ink (3D ink model)", "Recto surface", "Your clicks", "Organizers' ink reference", "DINO colors")
VIEW_NAMES = ("Top view (z)", "Front view (y)", "Side view (x)")
COLORS = {"ink": (235, 64, 52), "surface": (64, 200, 96), "clicks": (40, 220, 235), "reference": (250, 180, 30)}
MARKS = {"pos": (255, 255, 255), "neg": (255, 70, 200)}   # crosses where you clicked: More like this, Not this
LAYER_KEYS = {"ink": "Ink (3D ink model)", "surface": "Recto surface", "clicks": "Your clicks",
              "reference": "Organizers' ink reference", "pca": "DINO colors"}


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
    import shutil
    import numpy as np
    REFERENCE = lens.unit(np.load(lens.ensure_weights(names=("ink_reference",))["ink_reference"],
                                  allow_pickle=False).astype(np.float32))
    try:
        GALLERY = lens.gallery()
    except LensError as exc:                      # a broken index must not keep the page from starting
        log(f"gallery not loaded: {exc}")
        GALLERY = []
    for folder in (OUT, VIEW_DIR):                # outputs of an earlier run of this process
        shutil.rmtree(folder, ignore_errors=True)
    VIEW_DIR.mkdir(parents=True, exist_ok=True)
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


# ZeroGPU's refusals, by the titles the spaces package gives them (spaces 0.51.3, zero/client.py and wrappers.py):
# the quota, a duration it will not grant, no GPU free in time. "ZeroGPU worker error" is different: the models
# themselves failed inside the GPU task, so the CPU would fail the same way, except for "GPU task aborted" (the task
# ran past its duration).
GPU_REFUSALS = ("ZeroGPU quota exceeded", "ZeroGPU illegal duration", "ZeroGPU pending credits exceeded",
                "ZeroGPU queue timeout", "ZeroGPU client error")
CPU_SLOT = threading.Semaphore(1)       # one CPU fallback run at a time, so the page keeps answering


def _is_gpu_refusal(exc):
    return (str(getattr(exc, "title", "") or "") in GPU_REFUSALS or "GPU task aborted" in str(exc)
            or "No GPU was available" in str(exc))


def cpu_run(eng, cube, layers):
    if not CPU_SLOT.acquire(blocking=False):
        raise LensError("the Space's CPU is busy with another fallback run; try again in a minute, or sign in to "
                        "Hugging Face for more ZeroGPU time")
    try:
        import torch
        torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))     # leave a core for the page
        return eng.run(_center(cube, CPU_SIZE), layers, device="cpu", tta=False)
    finally:
        CPU_SLOT.release()


def run_models(cube, layers, tta, allow_cpu=True):
    """Run on the GPU when there is one; on ZeroGPU fall back to the CPU when the GPU is refused. Returns the result
    and a note for the visitor (empty when it ran as asked)."""
    eng = engine()
    import torch
    if ON_ZERO_GPU:
        try:
            return gpu_run(cube, tuple(layers), bool(tta)), ""
        except Exception as exc:  # noqa: BLE001
            if not _is_gpu_refusal(exc):
                if str(getattr(exc, "title", "")) == "ZeroGPU worker error":
                    raise LensError(f"the models failed on the GPU ({str(exc).strip()[:200]}); try again, or try "
                                    "another point") from None
                raise
            if not allow_cpu:
                raise LensError(f"ZeroGPU refused this call: {str(exc).strip()[:300]} Pass allow_cpu=True to run "
                                f"the middle {CPU_SIZE}³ on the CPU instead.") from None
            log(f"GPU refused ({exc}); running on the CPU")
            note = (f"ZeroGPU refused the run ({str(exc).strip().rstrip('. ')[:200]}), so the models ran on the "
                    f"Space's CPU, on the middle {CPU_SIZE}³ voxels. ZeroGPU time comes back each day; signing in "
                    "to Hugging Face gives more.")
            return cpu_run(eng, cube, layers), note
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu" and cube.shape[0] > CPU_SIZE:
        return (cpu_run(eng, cube, layers),
                f"No GPU here, so the models ran on the CPU on the middle {CPU_SIZE}³ voxels.")
    return eng.run(cube, layers, device=device, tta=tta), ""


# One model run at a time per visitor or caller, so one script cannot hold the GPU and the queue for everyone.
RUNNING = collections.Counter()
RUN_LOCK = threading.Lock()


def client_of(request):
    if request is None:
        return None
    headers = getattr(request, "headers", None) or {}
    forwarded = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
    host = getattr(getattr(request, "client", None), "host", "") or ""
    return forwarded or host or getattr(request, "session_hash", None)


class one_run:
    def __init__(self, request):
        self.key = client_of(request)

    def __enter__(self):
        with RUN_LOCK:
            if self.key and RUNNING[self.key] >= 1:
                raise LensError("you already have a model run going; wait for it to finish (one at a time per "
                                "visitor)")
            RUNNING[self.key] += 1

    def __exit__(self, *exc):
        with RUN_LOCK:
            RUNNING[self.key] -= 1
            if RUNNING[self.key] <= 0:
                del RUNNING[self.key]
        return False


def _center(cube, size):
    if cube.shape[0] <= size:
        return cube
    o = (cube.shape[0] - size) // 2
    return cube[o:o + size, o:o + size, o:o + size]


# ---------------------------------------------------------------- cubes in memory
#
# A cube's model outputs (tens of MB) live in one cache shared by every visitor; a visitor's session keeps only the
# cube's key and its clicks, so memory stays bounded however many people use the page. Gallery cubes reload from
# disk when they drop out; a cube the models ran on now does not, and asks to be run again.

class Cube:
    """One cube's model outputs and what is derived from them."""

    def __init__(self, key, meta, result):
        import numpy as np
        self.key, self.meta, self.result = key, meta, result
        self.size = int(meta["cube_size"])
        self.n = self.size // lens.PATCH
        self.lock = threading.Lock()
        self.has_dino = "grid" in result or "grid_reduced" in result
        self.norms = None
        if "grid_reduced" in result:
            coef = np.asarray(result["grid_reduced"], np.float32)
            self.norms = np.maximum(np.linalg.norm(coef, axis=-1), 1e-12)
        self.ref_sim = self.similarity(REFERENCE) if self.has_dino and REFERENCE is not None else None
        self.data_path = None

    def similarity(self, positive, negative=None):
        """Per patch: cosine to the positive concept, minus that to the negative one. A compact (gallery) cube is
        scored in its reduced basis, the same numbers as with the embeddings lens.grid_of rebuilds."""
        import numpy as np
        res = self.result
        if "grid" in res:
            return lens.similarity(np.asarray(res["grid"]), positive, negative)
        if "grid_reduced" not in res:
            raise LensError("this cube has no DINO embeddings; run it with the 3D DINO model to search it")
        basis = np.asarray(res["grid_basis"], np.float32)
        coef = np.asarray(res["grid_reduced"], np.float32)

        def cos(vec):                 # the projection's dot product, as lens.grid_of rebuilds it (no rescaling)
            return coef @ (basis.T @ np.asarray(vec, np.float32))
        s = cos(positive)
        if negative is not None:
            s = s - cos(negative)
        return s.astype(np.float32)

    def vector(self, voxel):
        """The unit 864-number embedding of the patch holding a cube voxel (z, y, x)."""
        import numpy as np
        t = lens.token_of(voxel, self.size)
        res = self.result
        if "grid" in res:
            return np.asarray(res["grid"][t], np.float32)
        if "grid_reduced" not in res:
            raise LensError("this cube has no DINO embeddings; run it with the 3D DINO model to search by clicking")
        return lens.unit(np.asarray(res["grid_basis"], np.float32) @ np.asarray(res["grid_reduced"][t], np.float32))

    def pca(self):
        import numpy as np
        res = self.result
        if "grid" in res:
            return lens.pca_colors(np.asarray(res["grid"], np.float32))
        if "grid_reduced" in res:
            # the basis is orthonormal, so unit coefficients are the unit embeddings in a rotated frame: same colors
            coef = np.asarray(res["grid_reduced"], np.float32) / self.norms[..., None]
            return lens.pca_colors(coef)
        return None

    def layers_file(self, path):
        """Write the model layers the browser viewer draws, once: ink and surface (uint8, Z Y X), DINO colors
        (uint8, Z/8 Y/8 X/8 3) and the organizers' reference similarity (float32, Z/8 Y/8 X/8), gzipped behind a
        JSON header (see viewer.js loadLayers)."""
        import numpy as np
        with self.lock:
            if self.data_path and Path(self.data_path).is_file():
                return self.data_path
            arrays = [(k, np.ascontiguousarray(self.result[k], np.uint8)) for k in ("ink", "surface") if k in self.result]
            if self.has_dino:
                arrays.append(("pca", np.ascontiguousarray(self.pca(), np.uint8)))
                if self.ref_sim is not None:
                    arrays.append(("ref", np.ascontiguousarray(self.ref_sim, "<f4")))
            header, blobs, offset = {"arrays": []}, [], 0
            for name, a in arrays:
                raw = a.tobytes()
                header["arrays"].append({"name": name, "dtype": str(a.dtype).replace("<", ""), "shape": list(a.shape),
                                         "offset": offset, "nbytes": len(raw)})
                pad = (-len(raw)) % 4
                blobs.append(raw + b"\0" * pad)
                offset += len(raw) + pad
            hjson = json.dumps(header).encode()
            body = len(hjson).to_bytes(4, "little") + hjson
            body += b"\0" * ((-len(body)) % 4)
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(f"{path}.part")
            tmp.write_bytes(gzip.compress(body + b"".join(blobs), compresslevel=3, mtime=0))
            os.replace(tmp, path)
            self.data_path = str(path)
            return self.data_path


class CubeCache:
    def __init__(self, size=CACHE_CUBES):
        self.size = size
        self.items = collections.OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        if key.startswith("gallery:"):
            return self.put(gallery_cube(key.split(":", 1)[1]))
        raise LensError("this cube is no longer in the Space's memory (it keeps the last few); run it again")

    def put(self, cube):
        with self.lock:
            self.items[cube.key] = cube
            self.items.move_to_end(cube.key)
            while len(self.items) > self.size:
                key, old = self.items.popitem(last=False)
                if key.startswith("run:") and old.data_path:
                    Path(old.data_path).unlink(missing_ok=True)
        return cube


CUBES = CubeCache()


def gallery_item(cube_id):
    for it in GALLERY:
        if it["id"] == cube_id:
            return it
    raise LensError(f"no gallery cube {cube_id!r}")


def gallery_cube(cube_id):
    it = gallery_item(cube_id)
    meta, arrays = lens.load_npz(HERE / "gallery" / it["file"])
    result = dict(arrays, seconds=meta.get("seconds", {}), device=meta.get("device"),
                  device_name=meta.get("device_name"), tta=meta.get("tta", False))
    return Cube(f"gallery:{cube_id}", meta, result)


def cube_of(view):
    return CUBES.get(view["cache"])


def layers_url(cube):
    if cube.key.startswith("gallery:"):
        path = VIEW_DIR / "gallery" / f"{cube.key.split(':', 1)[1]}-{lens.VERSION}.bin"
    else:
        path = VIEW_DIR / "runs" / f"{cube.key.split(':', 1)[1]}.bin"
    return f"gradio_api/file={cube.layers_file(path)}"


# ---------------------------------------------------------------- one cube on screen

def new_view(cube, point, source, note="", title=None, request_size=None, cube_id=None):
    """What a visitor's session keeps about the cube on screen: small values only; the arrays stay in CUBES."""
    meta = cube.meta
    vid = meta["volume"]
    origin = tuple(int(v) for v in meta["cube_origin_zyx"])
    receipt = dict(meta)
    receipt["source"] = source
    if cube_id:
        receipt["gallery_id"] = cube_id
    return {"cache": cube.key, "volume": vid, "origin": origin, "size": cube.size,
            "point": tuple(int(v) for v in point), "source": source, "note": note, "cube_id": cube_id,
            "title": title or f"{lens.volume(vid)['scroll']}, cube at z {origin[0]}, y {origin[1]}, x {origin[2]}",
            "request_size": request_size or cube.size, "foreground": meta.get("foreground"), "receipt": receipt}


def empty_state():
    return {"view": None, "pos": [], "neg": [], "rev": 0}


def cube_key(view):
    return f"{view['volume']}:{','.join(map(str, view['origin']))}:{view['size']}"


def click_concept(state):
    """The visitor's concept: unit mean of the positive clicks' embeddings, and of the negative ones (or None)."""
    import numpy as np
    pos = [c["vec"] for c in state["pos"]]
    neg = [c["vec"] for c in state["neg"]]
    p = lens.unit(np.mean(pos, 0)) if pos else None
    n = lens.unit(np.mean(neg, 0)) if neg else None
    return p, n


def click_sim(state, cube=None):
    view = state["view"]
    p, n = click_concept(state)
    if view is None or p is None:
        return None
    cube = cube or cube_of(view)
    if not cube.has_dino:
        return None
    return cube.similarity(p, n)


def encode_sim(sim):
    import numpy as np
    if sim is None:
        return None
    q = np.clip(np.rint(np.asarray(sim, np.float32) * SIM_SCALE), -32768, 32767).astype("<i2")
    return base64.b64encode(q.tobytes()).decode()


def viewer_value(state):
    """The JSON the browser viewer reads (viewer.js onValue): where to fetch the scan and the model layers, the
    cube's place, and the visitor's clicks with their similarity map."""
    view = state.get("view")
    if not view:
        return ""
    cube = cube_of(view)
    key = cube_key(view)
    marks = {kind: [c["voxel"] for c in state[kind] if c.get("cube") == key and c.get("voxel")]
             for kind in ("pos", "neg")}
    return json.dumps({
        "key": view["cache"], "rev": state.get("rev", 0), "volume": view["volume"],
        "scroll": lens.volume(view["volume"])["scroll"], "title": view["title"], "cube_id": view.get("cube_id"),
        "origin": list(view["origin"]), "size": view["size"], "point": list(view["point"]),
        "request_size": view.get("request_size"),
        "ct": {"base": lens.volume_url(view["volume"]), "chunk": lens.CHUNK},
        "data": layers_url(cube),
        "has": {"dino": cube.has_dino, "ink": "ink" in cube.result, "surface": "surface" in cube.result},
        "tau": lens.TAU,
        "clicks": {"sim": encode_sim(click_sim(state, cube)), "pos": marks["pos"], "neg": marks["neg"],
                   "acked": state.get("acked", [])},
    })


# ---------------------------------------------------------------- drawing on the server (the slice API and tests)

def _take(a, axis, i):
    return a[i] if axis == 0 else (a[:, i] if axis == 1 else a[:, :, i])


def _top_alpha(sim2d, sim3d, top_pct, floor=None):
    """Opacity of each pixel of a similarity slice: 0 below the cube's top `top_pct` percent (and below `floor`, if
    given), then from 0.35 at the threshold to 1 at the cube's best patch, so every selected patch shows (viewer.js
    draws it the same way)."""
    import numpy as np
    thr = float(np.percentile(sim3d, 100 - top_pct))
    if floor is not None:
        thr = max(thr, float(floor))
        if float(sim3d.max()) < thr:
            return np.zeros_like(sim2d, dtype=np.float32)
    best = float(sim3d.max())
    if best - thr < 1e-6 and float(sim3d.min()) == best:
        return np.zeros_like(sim2d, dtype=np.float32)          # a flat map (the concept cancels out): show nothing
    ramp = np.clip((sim2d - thr) / max(best - thr, 1e-6), 0, 1)
    return (TOP_FLOOR + (1 - TOP_FLOOR) * ramp) * (sim2d >= thr)


def render_slice(ct, cube, axis, index, overlays, top_pct=8.0, opacity=0.7, click=None, marks=None):
    """One slice through a cube as an RGB uint8 image (size x size), drawn the way the browser viewer draws it: the CT
    windowed to its 0.5th to 99.5th percentile of papyrus, then DINO colors, surface, ink, the organizers' reference
    and the visitor's concept, each blended at `opacity`. `click` is a similarity map at patch resolution."""
    import numpy as np
    size = cube.size
    index = int(min(max(int(index), 0), size - 1))
    tok_i = index // lens.PATCH
    ct2 = _take(ct, axis, index).astype(np.float32) if ct is not None else np.zeros((size, size), np.float32)
    nz = ct[ct > 0] if ct is not None else np.zeros(0)
    lo, hi = (np.percentile(nz, (0.5, 99.5)) if nz.size else (0, 255))
    g = np.clip((ct2 - lo) / max(float(hi - lo), 1.0), 0, 1)
    rgb = np.repeat(g[..., None], 3, axis=2)
    res = cube.result

    def up(t2):
        return np.repeat(np.repeat(t2, lens.PATCH, 0), lens.PATCH, 1)

    def blend(color, alpha):
        a = (np.asarray(alpha, np.float32) * opacity)[..., None]
        rgb[:] = rgb * (1 - a) + (np.asarray(color, np.float32) / 255.0) * a

    if "DINO colors" in overlays and cube.has_dino:
        pc = up(_take(cube.pca(), axis, tok_i)).astype(np.float32) / 255.0
        rgb[:] = rgb * (1 - 0.6 * opacity) + pc * (0.6 * opacity)
    if "Recto surface" in overlays and "surface" in res:
        blend(COLORS["surface"], _take(res["surface"], axis, index) / 255.0)
    if "Ink (3D ink model)" in overlays and "ink" in res:
        blend(COLORS["ink"], _take(res["ink"], axis, index) / 255.0)
    if "Organizers' ink reference" in overlays and cube.ref_sim is not None:
        s3 = cube.ref_sim
        blend(COLORS["reference"], up(_top_alpha(_take(s3, axis, tok_i), s3, top_pct, floor=lens.TAU)))
    if "Your clicks" in overlays and click is not None:
        blend(COLORS["clicks"], up(_top_alpha(_take(click, axis, tok_i), click, top_pct)))
    img = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    others = [a for a in range(3) if a != axis]
    for kind, color in (("pos", MARKS["pos"]), ("neg", MARKS["neg"])):
        for v in (marks or {}).get(kind, []):
            if v[axis] // lens.PATCH == tok_i:
                _mark(img, v[others[0]], v[others[1]], color, 4)
    return img


def _mark(img, r, c, color, half):
    """A cross two pixels thick, drawn in place."""
    h, w = img.shape[:2]
    for d in range(-half, half + 1):
        for t in (0, 1):
            for (y, x) in ((r + d, c + t), (r + t, c + d)):
                if 0 <= y < h and 0 <= x < w:
                    img[y, x] = color


def numbers(state):
    """The text beside the views: what this cube is, what ran, and the checks."""
    import numpy as np
    view = state["view"]
    if view is None:
        return ("Pick a ready-made cube from the gallery, or a point in a scan, then press **Run the models**. "
                "Click the views to find similar places.")
    cube = cube_of(view)
    v = lens.volume(view["volume"])
    r = view["receipt"]
    um = v["voxel_um"] * view["size"]
    fg = view.get("foreground")
    lines = [f"**{v['scroll']}**, cube of {view['size']}³ voxels ({um / 1000:.2f} mm a side) at "
             f"z {view['origin'][0]}, y {view['origin'][1]}, x {view['origin'][2]}."
             + (f" {fg:.0%} of it lies inside the scan's scroll mask." if fg is not None else "")]
    src = {"gallery": "Gallery cube: computed earlier, no GPU used now.", "gpu": "Ran now on the GPU.",
           "cpu": "" if view["note"] else "Ran now on the CPU.", "file": "Loaded from your file."}[view["source"]]
    secs = ", ".join(f"{k} {s:.1f} s" for k, s in r.get("seconds", {}).items())
    lines.append(f"{src} {('Model time: ' + secs + '.') if secs else ''} {view['note']}".strip())
    lines.append("**What each model saw of this scroll in training.** " + " ".join(
        f"{lens.LAYER_TITLES[k]}: {v['role'][k]}" for k in lens.LAYERS))
    ag = r.get("agreement_with_ink_model")
    if ag and ag.get("auc") is not None:
        lines.append(f"**Check.** The organizers' ink reference picks out the patches the 3D ink model marks as ink "
                     f"with AUC {ag['auc']:.2f}; the control (ink mask moved half a cube) gives "
                     f"{ag['auc_control_shifted']:.2f} and should sit near 0.5. Ink covers "
                     f"{ag['ink_patch_fraction']:.1%} of patches. Agreement between two models, not ground truth.")
    if cube.ref_sim is not None:
        lines.append(f"Patches at or above the organizers' threshold (cosine {lens.TAU}) to their reference: "
                     f"{float((cube.ref_sim >= lens.TAU).mean()):.1%}.")
    s = click_sim(state, cube)
    if s is not None:
        extra = ""
        if "ink" in cube.result:
            a = lens.agreement(s, cube.result["ink"])
            if a["auc"] is not None:
                extra = (f" Against the 3D ink model your concept scores AUC {a['auc']:.2f} "
                         f"(control {a['auc_control_shifted']:.2f}).")
        clicked = {c["cube"] for c in state["pos"] + state["neg"] if c["cube"] != "file"}
        loaded = any(c["cube"] == "file" for c in state["pos"])
        lines.append(f"**Your concept:** {len([c for c in state['pos'] if c['cube'] != 'file'])} positive and "
                     f"{len(state['neg'])} negative clicks from {len(clicked)} cube(s)"
                     f"{', plus your concept.npy' if loaded else ''}.{extra}")
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
    cube = cube_of(view)
    res, size = cube.result, view["size"]
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
        s3 = click_sim(state, cube) if key == "clicks" else cube.ref_sim
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

def run_cube(vid, z, y, x, size, layers, tta, allow_cpu=True):
    """Read the cube around a point, run the chosen models on it and keep it in CUBES. Returns (cube, note)."""
    import numpy as np
    vid = lens.volume_id(vid)
    size = check_size_arg(size)
    layers = lens.check_layers(layers)
    point = check_point(z, y, x)
    eng = engine()                                 # refuse before reading the bucket while the models load
    origin = lens.cube_origin(vid, point, size)
    ct = lens.read_cube(vid, origin, size)
    fg = lens.check_cube(ct)
    result, note = run_models(ct, layers, bool(tta), allow_cpu=allow_cpu)
    n = ran_size(result)
    if n != size:                                  # the CPU fallback ran the middle of the cube
        origin = tuple(int(o + (size - n) // 2) for o in origin)
        fg = lens.foreground(_center(ct, n))
    src = "gpu" if str(result.get("device", "")).startswith("cuda") else "cpu"
    meta = lens.receipt(vid, origin, n, point, result, eng.describe(),
                        {"source": src, "note_run": note, "foreground": round(fg, 4), "requested_size": size})
    if "grid" in result and "ink" in result:
        meta["agreement_with_ink_model"] = lens.agreement(
            lens.similarity(np.asarray(result["grid"], np.float32), REFERENCE), result["ink"])
    return CUBES.put(Cube(f"run:{uuid.uuid4().hex}", meta, result)), note


def check_point(z, y, x):
    try:
        point = tuple(int(v) for v in (z, y, x))
    except (TypeError, ValueError, OverflowError):
        raise LensError("give the point as three whole numbers, z y x, in level-0 voxels") from None
    return point


def check_size_arg(size):
    try:
        return lens.check_size(int(size))
    except (TypeError, ValueError, OverflowError):
        raise LensError(f"cube side must be one of {lens.SIZES} voxels, not {size!r}") from None


def parse_layers(layers):
    """Models to run from a comma-separated string or a list, in any case, by key or by page title."""
    titles = {v.lower(): k for k, v in lens.LAYER_TITLES.items()}
    items = layers if isinstance(layers, (list, tuple)) else str(layers or "").split(",")
    return lens.check_layers([titles.get(str(i).strip().lower(), str(i).strip().lower()) for i in items
                              if str(i).strip()])


def prune(folder, age_s=3600):
    """Delete what a folder of per-request outputs holds that is older than `age_s` (Gradio serves copies)."""
    import shutil
    now = time.time()
    for p in Path(folder).glob("*"):
        try:
            if now - p.stat().st_mtime > age_s:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        except OSError:
            pass


def load_point(vid, z, y, x, size, layers, tta):
    cube, note = run_cube(vid, z, y, x, size, parse_layers(list(layers or [])), tta)
    return new_view(cube, check_point(z, y, x), cube.meta["source"], note, request_size=int(size))


def ran_size(result):
    """The side of the cube a result covers, from whichever layers it holds."""
    for k in ("ink", "surface"):
        if k in result:
            return int(result[k].shape[0])
    return int(lens.grid_of(result).shape[0] * lens.PATCH)


def load_gallery(cube_id):
    it = gallery_item(cube_id)
    cube = CUBES.get(f"gallery:{cube_id}")
    return new_view(cube, tuple(it["point_zyx"]), "gallery", it.get("note", ""), title=it["title"],
                    cube_id=cube_id)


def gallery_label(it):
    return it["title"] if int(it.get("size", 256)) == 256 else f"{it['title']} ({it['size']}³)"


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
    cube = cube_of(view)
    OUT.mkdir(parents=True, exist_ok=True)
    prune(OUT, 900)
    d = Path(tempfile.mkdtemp(dir=OUT))
    name = f"scroll-lens-{view['volume']}-{'-'.join(map(str, view['origin']))}-{view['size']}"
    files = [lens.save_npz(d / f"{name}.npz", view["receipt"], cube.result,
                           compact="grid_reduced" in cube.result)]
    rec = d / f"{name}.json"
    rec.write_text(json.dumps(view["receipt"], indent=1) + "\n")
    files.append(rec)
    p, n = click_concept(state)
    if p is not None:
        np.save(d / "concept.npy", p.astype(np.float32))
        files.append(d / "concept.npy")
        if n is not None:
            np.save(d / "concept_not.npy", n.astype(np.float32))
            files.append(d / "concept_not.npy")
        clicks = {"tool": "Scroll Lens", "version": lens.VERSION, "embedding": lens.MODELS["dino"]["repo"],
                  "positive": [{k: c[k] for k in ("volume", "cube", "voxel_zyx")} for c in state["pos"]],
                  "negative": [{k: c[k] for k in ("volume", "cube", "voxel_zyx")} for c in state["neg"]],
                  "note": "concept.npy is the unit-length mean of the positive clicks' 864-number dinovol embeddings; "
                          "concept_not.npy, when present, that of the Not this clicks. The page scores each patch "
                          "as its cosine to concept.npy minus its cosine to concept_not.npy. Load both files "
                          "together to get the same map back."}
        (d / "clicks.json").write_text(json.dumps(clicks, indent=1) + "\n")
        files.append(d / "clicks.json")
    return [str(f) for f in files]


def as_bool(value, name):
    """True or False from a boolean, 0 or 1, or the strings true, false, yes, no, 1, 0 (a JSON caller may send
    "false", which bool() would read as True)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "yes", "1", "on"):
        return True
    if text in ("false", "no", "0", "off", "", "none"):
        return False
    raise LensError(f"{name} must be true or false, not {value!r}")


def api_look(vid, z, y, x, size, layers, tta, compact, allow_cpu, request=None):
    """For scripts and agents: run the models on one cube. Returns (cube, receipt, .npz path)."""
    with one_run(request):
        cube, _ = run_cube(vid, z, y, x, size, parse_layers(layers), as_bool(tta, "tta"),
                           allow_cpu=as_bool(allow_cpu, "allow_cpu"))
    meta = dict(cube.meta, source="api", cube_ref=cube.key)
    OUT.mkdir(parents=True, exist_ok=True)
    prune(OUT, 900)
    d = Path(tempfile.mkdtemp(dir=OUT))
    origin = meta["cube_origin_zyx"]
    path = lens.save_npz(d / f"{meta['volume']}-{'-'.join(map(str, origin))}-{cube.size}.npz", meta, cube.result,
                         compact=as_bool(compact, "compact"))
    return cube, meta, str(path)


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
1. **Gallery** (no GPU needed): pick a ready-made cube; it opens at once. *Previous*, *Next* and *Random* step
   through the list, and you can type in the list to search it.
2. **Your own point**: pick a scan, type a point in voxels (z, y, x) or press **Surprise me**, then **Run the models**.
   A 256³ cube is the models' own working size and uses about 5 seconds of ZeroGPU time (with ZeroGPU's own
   overhead, a call is about 10 seconds). When your daily ZeroGPU time runs out, Scroll Lens runs a 128³ cube on the
   CPU instead (about 10 seconds).
3. **Look**: drag a slider under a view, or drag inside a view to move the crosshair; the other views follow as you
   move. The wheel or the arrow keys step one slice (Shift: 8). Ctrl or Cmd with the wheel, or a pinch, zooms;
   right-drag or Shift-drag pans; double-click resets. The line under the views reads out what is under the pointer.
4. **Search**: with *More like this* chosen, click a patch; *Not this* subtracts one; *Undo click* (or Ctrl or Cmd
   with Z) forgets the last one. *Top % shown* sets how many of the most similar patches light up.
5. **Take it away**: **Save files** gives the model outputs (.npz), the receipt (.json) and, after clicks, your
   `concept.npy`. *Copy link* gives a link that opens this cube at this crosshair.

Scripts and agents: see *For scripts and agents* below, or the README.
"""

CSS = """
.sl-head { display:flex; gap:14px; align-items:baseline; flex-wrap:wrap; margin: 4px 0 2px; }
.sl-head h1 { margin:0; font-size: 1.6rem; letter-spacing: .01em; }
.sl-head span { color: var(--body-text-color-subdued); }
footer.sl-credit { text-align:center; color: var(--body-text-color-subdued); font-size:.85rem; margin-top: 8px; }
.slv { display:flex; flex-direction:column; gap:8px; }
.slv-bar { display:flex; flex-direction:column; gap:6px; font-size:.86rem; }
.slv-group { display:flex; flex-wrap:wrap; gap:4px 8px; align-items:center; }
.slv-chip { display:inline-flex; align-items:center; gap:5px; padding:2px 9px; border:1px solid var(--border-color-primary);
  border-radius:999px; cursor:pointer; user-select:none; background: var(--block-background-fill); }
.slv-chip input { margin:0; }
.slv-chip i { width:10px; height:10px; border-radius:2px; display:inline-block; }
.slv-label { color: var(--body-text-color-subdued); margin-right: 2px; }
.slv-sliders label { display:inline-flex; align-items:center; gap:5px; margin-right: 8px; }
.slv-sliders input[type=range] { width:96px; }
.slv-buttons button { font-size:.8rem; padding:3px 10px; border:1px solid var(--border-color-primary); border-radius:6px;
  background: var(--button-secondary-background-fill); color: var(--button-secondary-text-color); cursor:pointer; }
.slv-buttons button:hover { background: var(--button-secondary-background-fill-hover); }
.slv-status { display:flex; gap:10px; align-items:center; font-size:.86rem; color: var(--body-text-color-subdued);
  min-height:1.4em; word-break: break-all; }
.slv-status progress { width:160px; flex: none; }
.slv-views { display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:8px; }
@media (max-width: 900px) { .slv-views { grid-template-columns: 1fr; } }
.slv-view { display:flex; flex-direction:column; gap:4px; min-width:0; }
.slv-title { font-size:.85rem; display:flex; justify-content:space-between; color: var(--body-text-color-subdued); }
.slv-view canvas { display:block; background:#0b0f14; border-radius:6px; touch-action:none; cursor:crosshair;
  outline:none; }
.slv-view canvas:focus-visible { box-shadow: 0 0 0 2px var(--color-accent); }
.slv-view input[type=range] { width:100%; }
.slv-more { display:flex; flex-direction:column; gap:6px; }
.slv-more > summary { cursor:pointer; color: var(--body-text-color-subdued); font-size:.84rem; }
@media (min-width: 601px) { .slv-more > summary { display:none; } }
.slv-readout { font-family: ui-monospace, monospace; font-size:.8rem; min-height:1.3em; }
.slv-help { font-size:.78rem; color: var(--body-text-color-subdued); }
"""


def theme():
    import gradio as gr
    return gr.themes.Base(primary_hue="amber", neutral_hue="slate", radius_size="sm",
                          font=("system-ui", "sans-serif"), font_mono=("ui-monospace", "monospace"))


def viewer_js():
    return (HERE / "viewer.js").read_text(encoding="utf-8")


def build_demo():
    import gradio as gr

    vol_choices = [(f"{v['scroll']} ({vid})", vid) for vid, v in lens.VOLUMES.items()]
    gal_choices = [(gallery_label(it), it["id"]) for it in GALLERY]
    gal_ids = [it["id"] for it in GALLERY]
    layer_names = [lens.LAYER_TITLES[k] for k in lens.LAYERS]

    def volume_text(vid):
        v = lens.volume(vid)
        z, y, x = v["shape"]
        return (f"{v['note']} Scan: {v['voxel_um']} µm voxels, {z:,} × {y:,} × {x:,} (z, y, x), open data at "
                f"`{lens.BUCKET}/{vid}/volumes/{v['scan']}` ([metadata]({lens.volume_url(vid)}/.zarray))").strip()

    def guard(fn):
        @functools.wraps(fn)          # keeps fn's signature, so gradio still passes EventData and Request
        def wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except LensError as exc:
                raise gr.Error(str(exc)) from None
            except gr.Error:
                raise
            except Exception as exc:  # noqa: BLE001  (anything else still reaches the visitor with its reason)
                import traceback
                log(f"{fn.__name__} failed: {traceback.format_exc()}")
                raise gr.Error(f"{type(exc).__name__}: {str(exc)[:400]}") from None
        return wrapped

    def soft(n):
        """For the page's own events: a refusal shows as a warning and leaves the page as it was (an error would
        cover the views with error panels). The API endpoints use guard, so callers get a real error."""
        def deco(fn):
            @functools.wraps(fn)
            def wrapped(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except LensError as exc:
                    gr.Warning(str(exc))
                except gr.Error as exc:
                    gr.Warning(str(exc))
                except Exception as exc:  # noqa: BLE001
                    import traceback
                    log(f"{fn.__name__} failed: {traceback.format_exc()}")
                    gr.Warning(f"{type(exc).__name__}: {str(exc)[:300]}")
                return gr.skip() if n == 1 else [gr.skip()] * n
            return wrapped
        return deco

    def shown(state):
        return [state, viewer_value(state), numbers(state)]

    def fresh():                      # a new cube: hide the old 3D plot and clear the old saved files
        return [gr.update(value=None, visible=False), None, None]

    @soft(6)
    def on_run(vid, z, y, x, size, layers, tta, state, request: gr.Request):
        with one_run(request):
            view = load_point(vid, z, y, x, size, layers, tta)
        state = dict(state, view=view, rev=state.get("rev", 0) + 1)
        return shown(state) + fresh()

    def open_gallery(cube_id, state):
        if not cube_id:
            raise LensError("pick a gallery cube")
        state = dict(state, view=load_gallery(cube_id), rev=state.get("rev", 0) + 1)
        p = state["view"]["point"]
        return shown(state) + fresh() + [state["view"]["volume"], p[0], p[1], p[2], state["view"]["size"], cube_id]

    @soft(12)
    def on_gallery(cube_id, state):
        return open_gallery(cube_id, state)

    @soft(12)
    def on_gallery_step(cube_id, state, *, step):
        if not gal_ids:
            raise LensError("the gallery is empty on this copy; pick a point instead")
        if step == "random":
            import numpy as np
            nxt = gal_ids[int(np.random.default_rng().integers(0, len(gal_ids)))]
        else:
            i = gal_ids.index(cube_id) if cube_id in gal_ids else -1
            nxt = gal_ids[(i + (1 if step == "next" else -1)) % len(gal_ids)]
        return open_gallery(nxt, state)

    @soft(3)
    def on_surprise(vid):
        z, y, x = surprise(vid)
        return z, y, x

    @soft(3)
    def on_viewer_select(state, evt: gr.EventData):
        """Clicks from the viewer: {"key": cube, "clicks": [{"id", "index": [z, y, x], "value": "pos" or "neg"}]}.
        The viewer sends every click the server has not yet acknowledged, so none is lost when two arrive while one
        is being handled; the ids keep a resent click from counting twice."""
        data = getattr(evt, "_data", None) or {}
        view = state["view"]
        if view is None or data.get("key") != view["cache"]:
            return [gr.skip()] * 3          # clicks on a cube this session has already left
        state = dict(state, pos=list(state["pos"]), neg=list(state["neg"]))
        seen = set(state.get("acked", []))
        problem = None
        try:
            cube = cube_of(view)
        except LensError as exc:            # a run cube the Space no longer holds: say so once, take no clicks
            cube, problem = None, str(exc)
        for click in (data.get("clicks") or [])[:64]:
            cid = str(click.get("id"))
            if cid in seen:
                continue
            seen.add(cid)                   # acknowledged even when refused, so the viewer does not resend it
            if cube is None:
                continue
            try:
                vox = [int(v) for v in click.get("index")]
                if len(vox) != 3 or not all(0 <= v < view["size"] for v in vox):
                    raise LensError("that click is outside the cube")
                vec = cube.vector(vox)
            except (TypeError, ValueError, LensError) as exc:
                problem = str(exc) if isinstance(exc, LensError) else "a click needs a voxel z, y, x"
                continue
            kind = "neg" if click.get("value") == "neg" else "pos"
            state["tick"] = state.get("tick", 0) + 1
            state[kind].append({"volume": view["volume"], "cube": cube_key(view), "voxel": vox, "t": state["tick"],
                                "voxel_zyx": [int(v + o) for v, o in zip(vox, view["origin"])], "vec": vec})
        state["acked"] = sorted(seen)[-256:]
        state["rev"] = state.get("rev", 0) + 1
        if problem:
            gr.Warning(problem)
        if cube is None:
            return [state, gr.skip(), gr.skip()]
        return shown(state)

    @soft(3)
    def on_undo(state):
        """Forget the most recent click (More like this or Not this) on any cube."""
        clicks = [(c.get("t", 0), kind, i) for kind in ("pos", "neg") for i, c in enumerate(state[kind])
                  if c["cube"] != "file"]
        if not clicks:
            raise LensError("no click to undo")
        _, kind, i = max(clicks)
        state = dict(state, rev=state.get("rev", 0) + 1)
        state[kind] = state[kind][:i] + state[kind][i + 1:]
        return shown(state)

    @soft(4)
    def on_clear(state):
        state = dict(state, pos=[], neg=[], rev=state.get("rev", 0) + 1)
        return shown(state) + [None]

    @soft(1)
    def on_viewer_3d(state, evt: gr.EventData):
        data = getattr(evt, "_data", None) or {}
        if state["view"] is None:
            raise LensError("open a cube first")
        overlays = [LAYER_KEYS[k] for k in data.get("layers", ["ink", "clicks", "reference"]) if k in LAYER_KEYS]
        top = float(min(max(float(data.get("top", 8)), 1), 40))
        return gr.update(value=figure_3d(state, overlays, top), visible=True)

    @soft(5)
    def on_viewer_use(evt: gr.EventData):
        data = getattr(evt, "_data", None) or {}
        vid = data.get("volume")
        lens.volume(vid)
        z, y, x = check_point(*(data.get("point") or [None] * 3))
        return vid, z, y, x, gr.Tabs(selected="point")

    @soft(3)
    def on_concept(paths, state):
        """Load concept.npy, and concept_not.npy with it if you have one: they replace your clicks."""
        paths = [p for p in (paths if isinstance(paths, list) else [paths]) if p]
        if not paths:                         # the file was removed: drop the loaded concept, keep the clicks
            state = dict(state, pos=[c for c in state["pos"] if c["cube"] != "file"],
                         neg=[c for c in state["neg"] if c["cube"] != "file"], rev=state.get("rev", 0) + 1)
            return shown(state)
        pos, neg = [], []
        for p in paths[:2]:
            item = {"volume": "file", "cube": "file", "voxel": None, "voxel_zyx": None, "vec": lens.load_concept(p)}
            (neg if "_not" in Path(p).name.lower() else pos).append(item)
        if not pos:
            raise LensError("load concept.npy too: concept_not.npy alone has nothing to look for")
        state = dict(state, pos=pos, neg=neg, rev=state.get("rev", 0) + 1)
        return shown(state)

    @soft(2)
    def on_save(state):
        return save_files(state), (state["view"] or {}).get("receipt")

    def on_load(state, request: gr.Request):
        """Open the page from its link: ?cube=ID opens a gallery cube; ?v=SCAN&z=&y=&x=&size= fills Your own point
        (press Run the models); anything else opens the first gallery cube. A link that cannot be followed says why."""
        q = dict(request.query_params) if request else {}
        fields, tab, problems = [gr.skip()] * 4, gr.skip(), []
        size = gr.update(value=int(q["size"])) if q.get("size") in ("128", "256") else gr.skip()
        if q.get("size") and q.get("size") not in ("128", "256"):
            problems.append(f"size must be 128 or 256, not {q['size']!r}")
        cube_id = q.get("cube")
        if q.get("v"):
            try:
                vid = lens.volume_id(q["v"])
                fields = [vid] + [int(q[k]) if str(q.get(k, "")).isdigit() else gr.skip() for k in "zyx"]
                bad = [k for k in "zyx" if not str(q.get(k, "")).isdigit()]
                if bad:
                    problems.append(f"{', '.join(bad)} must be whole numbers of voxels")
                tab = gr.Tabs(selected="point")
            except LensError as exc:
                problems.append(str(exc))
        if cube_id and cube_id not in gal_ids:
            problems.append(f"no gallery cube {cube_id!r}")
            cube_id = None
        if not cube_id and gal_ids:
            cube_id = gal_ids[0]
        if problems:
            gr.Warning(f"This link could not be followed in full: {'; '.join(problems)}.")
        if not cube_id:
            return shown(state) + fields + [size, gr.skip(), tab]
        try:
            state = dict(state, view=load_gallery(cube_id), rev=state.get("rev", 0) + 1)
        except (LensError, OSError) as exc:
            log(f"link not loaded: {exc}")
            gr.Warning(f"The gallery cube could not be opened: {exc}")
            return shown(state) + fields + [size, gr.skip(), tab]
        if not q.get("v"):
            p = state["view"]["point"]
            fields = [state["view"]["volume"], p[0], p[1], p[2]]
        return shown(state) + fields + [size, cube_id, tab]

    with gr.Blocks(title="Scroll Lens", delete_cache=(1800, 3600)) as demo:
        state = gr.State(empty_state(), time_to_live=STATE_TTL_S)
        gr.HTML('<div class="sl-head"><h1>Scroll Lens</h1><span>Look inside a Herculaneum scroll with the '
                'Vesuvius Challenge’s 3D models: embeddings, ink and surfaces, and click to search.</span></div>')
        with gr.Row(equal_height=False):
            with gr.Column(scale=1, min_width=290, elem_id="sl-controls"):
                with gr.Tabs() as tabs:
                    with gr.Tab("Gallery", id="gallery"):
                        gpick = gr.Dropdown(gal_choices, value=gal_choices[0][1] if gal_choices else None,
                                            label=f"Ready-made cube, {len(gal_choices)} in all (no GPU needed)",
                                            filterable=True)
                        with gr.Row(equal_height=True):
                            gprev = gr.Button("Previous", size="sm", min_width=60)
                            grand = gr.Button("Random", size="sm", min_width=60)
                            gnext = gr.Button("Next", size="sm", min_width=60)
                        if not gal_choices:
                            gr.Markdown("The gallery is empty on this copy. Pick a point instead.")
                    with gr.Tab("Your own point", id="point"):
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
                with gr.Accordion("Your concept and files", open=False):
                    concept_up = gr.File(label="Load concept.npy, and concept_not.npy if saved (replaces your "
                                               "clicks)", file_types=[".npy"], file_count="multiple",
                                         type="filepath", height=130)
                    save = gr.Button("Save files", size="sm")
                    files = gr.File(label="Model outputs, receipt and your concept", file_count="multiple")
                    receipt = gr.JSON(label="Receipt")
                with gr.Accordion("How to use it", open=False):
                    gr.Markdown(HOW_TO)
                with gr.Accordion("For scripts and agents", open=False):
                    gr.Markdown(AGENTS_MD)
            with gr.Column(scale=3, min_width=320, elem_id="sl-viewer"):
                viewer = gr.HTML("", html_template='<div class="slv-mount"></div>', js_on_load=viewer_js(),
                                 apply_default_css=False, elem_id="sl-viewer-html")
                info = gr.Markdown(numbers(empty_state()))
                plot = gr.Plot(label="Ink and surface shells, similar patches as points", visible=False)
                with gr.Accordion("About", open=False):
                    gr.Markdown(INTRO)
        gr.HTML('<footer class="sl-credit">Built by Chase Hendrick · models and data by the Vesuvius Challenge · '
                f'Scroll Lens {lens.VERSION}</footer>')

        out = [state, viewer, info]
        stale = [plot, files, receipt]
        hidden = dict(api_visibility="private")
        vid.change(volume_text, vid, vinfo, **hidden)
        rbtn.click(on_run, [vid, z, y, x, size, layers, tta, state], out + stale, concurrency_id="models",
                   concurrency_limit=2, **hidden)
        gal_out = out + stale + [vid, z, y, x, size, gpick]
        gpick.input(on_gallery, [gpick, state], gal_out, concurrency_limit=4, **hidden)
        for btn, step in ((gprev, "previous"), (gnext, "next"), (grand, "random")):
            btn.click(functools.partial(on_gallery_step, step=step), [gpick, state], gal_out, concurrency_limit=4,
                      **hidden)
        sbtn.click(on_surprise, vid, [z, y, x], **hidden)
        viewer.select(on_viewer_select, state, out, show_progress="hidden", trigger_mode="multiple", **hidden)
        viewer.clear(on_clear, state, out + [concept_up], show_progress="hidden", **hidden)
        viewer.undo(on_undo, state, out, show_progress="hidden", **hidden)
        viewer.submit(on_viewer_3d, state, plot, **hidden)
        viewer.apply(on_viewer_use, None, [vid, z, y, x, tabs], show_progress="hidden", **hidden)
        concept_up.change(on_concept, [concept_up, state], out, **hidden)
        save.click(on_save, state, [files, receipt], **hidden)
        demo.load(on_load, state, out + [vid, z, y, x, size, gpick, tabs], **hidden)
        add_api(gr, guard)
    return demo


# ---------------------------------------------------------------- the API for scripts and agents
#
# add_api() registers one public endpoint per function: for gradio_client, for plain HTTP, and, because the app
# launches with mcp_server=True, as one MCP tool each. Gradio builds the API docs and the MCP schema from each
# function's name, type hints and docstring (the text before "Args:" describes the tool, each "name: text" line under
# "Args:" a parameter). The page's own events stay api_visibility="private", so they are neither endpoints nor tools.
# Nothing here keeps state between calls: a concept travels as scan voxels or as an 864-number vector, and a cube as
# a gallery id or the cube_ref that look returns.

SPACE_ID = os.environ.get("SPACE_ID") or "SharpMeow/scroll-lens"
PAGE_URL = f"https://huggingface.co/spaces/{SPACE_ID}"
APP_URL = f"https://{SPACE_ID.lower().replace('/', '-').replace('_', '-')}.hf.space"
GALLERY_URL = f"https://huggingface.co/spaces/{SPACE_ID}/resolve/main/gallery"
MAX_TOP_K = 200
LAYER_NAMES = {"ink": "Ink (3D ink model)", "surface": "Recto surface", "reference": "Organizers' ink reference",
               "concept": "Your clicks", "pca": "DINO colors"}


def _plain(x):
    """A JSON-ready copy: numpy scalars and arrays to Python numbers and lists, tuples to lists, floats rounded."""
    import math
    import numpy as np
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, np.ndarray):
        return _plain(x.tolist())
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return round(float(x), 6) if math.isfinite(float(x)) else None
    return x


def _cube_for(cube):
    """A cube by gallery id, or by the cube_ref look returned (kept while the Space has it in memory)."""
    cube = str(cube or "").strip()
    if not cube:
        raise LensError("give cube: a gallery id (see gallery) or the cube_ref that look returned")
    if cube.startswith("run:"):
        return CUBES.get(cube)
    gallery_item(cube)
    return CUBES.get(f"gallery:{cube}")


def _concept_of(cube, zyx_list, vector, use_reference, what):
    """(unit mean, count) of the patches holding scan voxels `zyx_list`, an 864-number vector and the reference."""
    import numpy as np
    origin = [int(v) for v in cube.meta["cube_origin_zyx"]]
    vecs = []
    for p in zyx_list or []:
        if not isinstance(p, (list, tuple)) or len(p) != 3:
            raise LensError(f"{what}_zyx holds [z, y, x] triples, not {p!r}")
        local = [lens.as_int(v, f"a {what} voxel coordinate") - o for v, o in zip(p, origin)]
        if not all(0 <= v < cube.size for v in local):
            raise LensError(f"{what} voxel {list(p)} is outside this cube, which spans {origin} to "
                            f"{[o + cube.size - 1 for o in origin]} (scan voxels, z y x)")
        vecs.append(cube.vector(local))
    if vector:
        a = np.asarray(vector, np.float64)
        if a.shape != (lens.EMBED_DIM,) or not np.isfinite(a).all() or not np.linalg.norm(a):
            raise LensError(f"{what}_vector is {lens.EMBED_DIM} finite numbers, not all zero")
        vecs.append(lens.unit(a.astype(np.float32)))
    if use_reference:
        vecs.append(REFERENCE)
    if not vecs:
        return None, 0
    mean = np.mean(np.stack(vecs), 0)
    if np.linalg.norm(mean) < 1e-3:
        raise LensError(f"the {what} concept cancels out (its parts point in opposite directions)")
    return lens.unit(mean), len(vecs)


def agent_volumes():
    return _plain({
        "volumes": [{"id": vid, "scroll": v["scroll"], "voxel_um": v["voxel_um"], "shape_zyx": list(v["shape"]),
                     "zarr": f"{lens.BUCKET}/{vid}/volumes/{v['scan']}", "level": 0, "note": v["note"],
                     "models_trained_on_this_scroll": dict(v["role"])} for vid, v in lens.VOLUMES.items()],
        "cube_sizes": list(lens.SIZES), "patch": lens.PATCH, "embed_dim": lens.EMBED_DIM,
        "models": {k: {"title": lens.LAYER_TITLES[k], "repo": lens.MODELS[k]["repo"],
                       "revision": lens.MODELS[k]["revision"]} for k in lens.LAYERS},
        "paris4_training_points_zyx": [list(p) for p in lens.PARIS4_TRAINING_POINTS],
        "note": ("Coordinates are level-0 scan voxels, z y x. None of these scans is eligible for the First Letters "
                 "or Grand Prize. PHerc. Paris 4's title is an open prize, so random_point returns only the eight "
                 "points the organizers listed for training the ink model. Model output, not a reading."),
    })


def agent_gallery(volume=""):
    vid = lens.volume_id(volume) if volume else None
    cubes = [{"id": it["id"], "volume": it["volume"], "scroll": lens.VOLUMES[it["volume"]]["scroll"],
              "title": it["title"], "note": it.get("note", ""), "size": int(it["size"]),
              "point_zyx": list(it["point_zyx"]), "npz_url": f"{GALLERY_URL}/{it['file']}",
              "page_url": f"{PAGE_URL}?cube={it['id']}"}
             for it in GALLERY if vid is None or it["volume"] == vid]
    return _plain({"count": len(cubes), "cubes": cubes,
                   "note": "Search and view these by id (no GPU). Each npz_url is the cube's .npz on the Hub."})


def cube_receipt(cube):
    """A cube's receipt for the API: the stored receipt, the agreement check worked out again now (with the control
    range, from the arrays the Space holds), and the share of patches the organizers' reference marks."""
    import numpy as np
    meta = dict(cube.meta)
    meta.pop("engine", None)
    meta["layers"] = lens.layers_in(cube.result)
    if cube.ref_sim is not None:
        meta["reference_patch_fraction_at_tau"] = float((cube.ref_sim >= lens.TAU).mean())
        if "ink" in cube.result:
            meta["agreement_with_ink_model"] = lens.agreement(np.asarray(cube.ref_sim), cube.result["ink"])
    meta["arrays"] = {k: f"{np.asarray(v).dtype} {list(np.shape(v))}" for k, v in cube.result.items()
                      if isinstance(v, np.ndarray)}
    return meta


def agent_search(cube, positive_zyx=(), negative_zyx=(), positive_vector=(), negative_vector=(), reference=False,
                 top_k=20, top_pct=8.0, return_concept=False):
    import numpy as np
    top_k = lens.as_int(top_k, "top_k")
    top_pct = float(top_pct)
    if not 1 <= top_k <= MAX_TOP_K:
        raise LensError(f"top_k is 1 to {MAX_TOP_K}")
    if not 1 <= top_pct <= 40:
        raise LensError("top_pct is 1 to 40")
    c = _cube_for(cube)
    if not c.has_dino:
        raise LensError("this cube has no DINO embeddings; run look with dino in layers to search it")
    origin = [int(v) for v in c.meta["cube_origin_zyx"]]
    pos, n_pos = _concept_of(c, positive_zyx, positive_vector, as_bool(reference, "reference"), "positive")
    neg, n_neg = _concept_of(c, negative_zyx, negative_vector, False, "negative")
    if pos is None:
        raise LensError("give a concept: positive_zyx, positive_vector or reference=true")
    sim = c.similarity(pos, neg)
    flat = sim.ravel()
    top = []
    for rank, i in enumerate(np.argsort(-flat, kind="stable")[:top_k], 1):
        t = np.unravel_index(int(i), sim.shape)
        row = {"rank": rank, "score": float(flat[i]), "patch_index_zyx": [int(v) for v in t],
               "center_zyx": [int(o + v * lens.PATCH + lens.PATCH // 2) for o, v in zip(origin, t)]}
        for k in ("ink", "surface"):
            if k in c.result:
                sl = tuple(slice(v * lens.PATCH, (v + 1) * lens.PATCH) for v in t)
                row[k] = float(np.asarray(c.result[k][sl]).mean() / 255.0)
        top.append(row)
    thr = float(np.percentile(sim, 100 - top_pct))
    out = {"cube": {"volume": c.meta["volume"], "scroll": c.meta.get("scroll"), "cube_origin_zyx": origin,
                    "cube_size": c.size, "gallery_id": c.key.split(":", 1)[1] if c.key.startswith("gallery:") else None,
                    "cube_ref": c.key if c.key.startswith("run:") else None, "patches": int(sim.size)},
           "concept": {"positive_count": n_pos, "negative_count": n_neg,
                       "reference_included": as_bool(reference, "reference")},
           "top_patches": top, "top_pct": top_pct, "threshold": thr, "match_fraction": float((sim >= thr).mean()),
           "note": "Model output, not a reading. AUCs are agreement between two models, not ground truth."}
    if neg is None:
        out.update(tau=lens.TAU, fraction_at_or_above_tau=float((sim >= lens.TAU).mean()))
    if "ink" in c.result:
        out["agreement_with_ink_model"] = lens.agreement(sim, c.result["ink"])
        if c.ref_sim is not None:
            out["reference_agreement_with_ink_model"] = lens.agreement(np.asarray(c.ref_sim), c.result["ink"])
    if as_bool(return_concept, "return_concept"):
        out["concept"].update(positive_vector=pos, negative_vector=neg)
    return _plain(out)


def agent_reference():
    spec = lens.MODELS["ink_reference"]
    return _plain({"vector": REFERENCE, "tau": lens.TAU, "embed_dim": lens.EMBED_DIM,
                   "source": {k: spec[k] for k in ("repo", "revision", "file", "sha256")},
                   "note": "Unit length. A patch's cosine similarity to it is the page's amber layer."})


SCAN_CUBES = collections.OrderedDict()      # the scan cubes view drew last, read from the bucket
SCAN_LOCK = threading.Lock()


def scan_cube(vid, origin, size):
    key = (vid, tuple(origin), size)
    with SCAN_LOCK:
        if key in SCAN_CUBES:
            SCAN_CUBES.move_to_end(key)
            return SCAN_CUBES[key]
    ct = lens.read_cube(vid, origin, size)
    ct.setflags(write=False)
    with SCAN_LOCK:
        SCAN_CUBES[key] = ct
        while len(SCAN_CUBES) > 4:
            SCAN_CUBES.popitem(last=False)
    return ct


def agent_view(cube, axis="z", index=-1, layers=("ink", "reference"), positive_zyx=(), negative_zyx=(),
               positive_vector=(), top_pct=8.0, opacity=0.7):
    """Path of a PNG of one slice, or of the three views side by side (axis "all"), drawn by render_slice and scaled
    up to 512 pixels a view."""
    import numpy as np
    from PIL import Image
    if axis not in ("z", "y", "x", "all"):
        raise LensError("axis is z, y, x or all")
    names = [str(k).strip().lower() for k in (layers or [])]
    bad = [k for k in names if k not in LAYER_NAMES]
    if bad:
        raise LensError(f"unknown layer {bad[0]!r}; choose from {', '.join(LAYER_NAMES)}")
    top_pct, opacity = float(top_pct), float(opacity)
    if not (1 <= top_pct <= 40 and 0 <= opacity <= 1):
        raise LensError("top_pct is 1 to 40 and opacity 0 to 1")
    c = _cube_for(cube)
    origin = tuple(int(v) for v in c.meta["cube_origin_zyx"])
    point = c.meta.get("point_zyx") or [o + c.size // 2 for o in origin]
    axes = [0, 1, 2] if axis == "all" else ["zyx".index(axis)]
    index = lens.as_int(index, "index")
    if axis == "all" and index >= 0:
        raise LensError("with axis all, leave index at -1: each view goes through the cube's point")
    if index >= c.size:
        raise LensError(f"index is 0 to {c.size - 1}, or -1 for the slice through the cube's point")
    picks = [index if index >= 0 else min(max(int(point[a]) - origin[a], 0), c.size - 1) for a in axes]
    click, marks = None, {"pos": [], "neg": []}
    if positive_zyx or negative_zyx or positive_vector:
        pos, _ = _concept_of(c, positive_zyx, positive_vector, False, "positive")
        neg, _ = _concept_of(c, negative_zyx, (), False, "negative")
        if pos is None:
            raise LensError("a negative concept needs a positive one")
        click = c.similarity(pos, neg)
        marks = {k: [[int(v) - o for v, o in zip(p, origin)] for p in pts or []]
                 for k, pts in (("pos", positive_zyx), ("neg", negative_zyx))}
        if "concept" not in names:
            names.append("concept")
    ct = scan_cube(c.meta["volume"], origin, c.size)
    f = max(1, 512 // c.size)
    tiles = [np.repeat(np.repeat(render_slice(ct, c, a, i, [LAYER_NAMES[k] for k in names], top_pct, opacity,
                                              click=click, marks=marks), f, 0), f, 1) for a, i in zip(axes, picks)]
    gap = np.full((tiles[0].shape[0], 8, 3), 255, np.uint8)
    img = tiles[0] if len(tiles) == 1 else np.concatenate([tiles[0], gap, tiles[1], gap, tiles[2]], axis=1)
    OUT.mkdir(parents=True, exist_ok=True)
    prune(OUT, 900)
    tag = "all" if axis == "all" else f"{axis}{picks[0]}"
    path = Path(tempfile.mkdtemp(dir=OUT)) / f"{c.meta['volume']}-{'-'.join(map(str, origin))}-{c.size}-{tag}.png"
    Image.fromarray(img).save(path)
    return str(path)


AGENTS_MD = f"""\
Everything on this page is also an API, for scripts (`gradio_client`, plain HTTP) and for agents (MCP). Only
`look` uses the GPU; everything else is instant or reads a little of the open-data bucket.

| Endpoint | What it does |
| --- | --- |
| `volumes` | The twelve scans: ids, shapes, voxel sizes, what each model saw in training |
| `gallery` | The ready-made cubes, with ids, points and download links |
| `gallery_cube` | One gallery cube's receipt and `.npz` |
| `random_point` | A random point on the papyrus of a scan (Surprise me) |
| `look` | Run the three models on the cube around a point (ZeroGPU; your quota) |
| `search` | Click search without clicking: the patches most like a concept, with the ink-model check |
| `view` | The three views (or one) as a PNG, drawn like the page |
| `reference` | The organizers' ink reference (864 numbers) |

**MCP** (Claude, Cursor and other MCP clients): `{APP_URL}/gradio_api/mcp/` (streamable HTTP), or
`{APP_URL}/gradio_api/mcp/sse`. For Claude Code: `claude mcp add --transport http scroll-lens {APP_URL}/gradio_api/mcp/`.

**Python:**

```python
from gradio_client import Client
c = Client("{SPACE_ID}")                         # add token="hf_..." to use your own ZeroGPU quota for look
cubes = c.predict(api_name="/gallery")["cubes"]
hits = c.predict(cube=cubes[0]["id"], reference=True, top_k=5, api_name="/search")
```

Full reference: the README of this Space, and `docs/tools/scroll-lens.md` in github.com/ChaseHendrick/Scrolls.
"""


def add_api(gr, guard):
    """The endpoints for scripts and agents; each is also an MCP tool (the app launches with mcp_server=True)."""
    from typing import Literal

    from gradio.data_classes import FileData

    Volume = Literal[tuple(lens.VOLUMES)]
    Layer = Literal[tuple(LAYER_NAMES)]

    def volumes() -> dict:
        """List the twelve CT scans Scroll Lens may read: shape, voxel size, notes, and what each of the three models saw of each scroll in training. Instant, no GPU. Call it first for valid volume ids.

        Returns:
            dict with volumes (id, scroll, voxel_um, shape_zyx, zarr, note, models_trained_on_this_scroll), cube_sizes, patch, embed_dim, models, paris4_training_points_zyx and note
        """
        return agent_volumes()

    def gallery(volume: Literal[("",) + tuple(lens.VOLUMES)] = "") -> dict:
        """List the ready-made gallery cubes, whose model outputs were computed earlier: searching and viewing them needs no GPU, so start here.

        Args:
            volume: Only the cubes of this scan id (see volumes); empty for all of them.
        Returns:
            dict with count and cubes (id, volume, scroll, title, note, size, point_zyx, npz_url, page_url)
        """
        return agent_gallery(volume)

    def gallery_cube(cube_id: str) -> dict:
        """Get one gallery cube: its receipt (place in the scan, models, timings, and the check of the organizers' ink reference against the 3D ink model, with its control range) and its .npz of model outputs. No GPU.

        Args:
            cube_id: A gallery id from gallery, for example paris4-train-1.
        Returns:
            dict, the receipt, with npz (the .npz file; gradio_client downloads it) and npz_url (the same file on the Hub). The .npz holds grid_reduced and grid_basis (embeddings), ink and surface (uint8 probability times 255) and receipt (JSON bytes)
        """
        it = gallery_item(str(cube_id))
        meta = cube_receipt(CUBES.get(f"gallery:{it['id']}"))
        meta.update(gallery_id=it["id"], title=it["title"], npz_url=f"{GALLERY_URL}/{it['file']}",
                    page_url=f"{PAGE_URL}?cube={it['id']}")
        return dict(_plain(meta), npz=FileData(path=str(HERE / "gallery" / it["file"])).model_dump())

    def random_point(volume: Volume, seed: int | None = None) -> dict:
        """Pick a random point on the papyrus of a scan (the page's Surprise me) to pass to look. Reads a few small chunks of the scan, no GPU. On PHercParis4 it returns one of the organizers' eight ink-training points.

        Args:
            volume: A scan id from volumes, for example PHerc0139.
            seed: Any integer for a repeatable pick; leave out for a new one (the seed used is returned).
        Returns:
            dict with volume, seed, point_zyx, cube_origin_zyx for each cube size, and page_url
        """
        import numpy as np
        vid = lens.volume_id(volume)
        seed = int(np.random.SeedSequence().entropy % (1 << 32)) if seed is None else lens.as_int(seed, "seed")
        point = surprise(vid, seed)
        return _plain({"volume": vid, "seed": seed, "point_zyx": list(point),
                       "cube_origin_zyx": {str(s): list(lens.cube_origin(vid, point, s)) for s in lens.SIZES},
                       "page_url": f"{PAGE_URL}?v={vid}&z={point[0]}&y={point[1]}&x={point[2]}"})

    def look(vid: Volume, z: int, y: int, x: int, size: int = 256, layers: str = "dino,ink,surface",
             tta: bool = False, compact: bool = False, allow_cpu: bool = False,
             request: gr.Request = None) -> dict:
        """Run the Vesuvius Challenge's 3D DINO, 3D ink and recto surface models on the cube around one point of a scan. Uses ZeroGPU: about 5 s of the caller's quota and 7 to 12 s per 256 cube, under 1 s of quota for a 128 cube; send your Hugging Face token to use your own quota. One run at a time per caller. Use a gallery cube instead when one will do.

        Args:
            vid: A scan id from volumes, for example PHerc0139.
            z: The point's z, a level-0 scan voxel; the cube is placed on the 128-voxel chunk grid around it.
            y: The point's y.
            x: The point's x.
            size: Cube side in voxels, 128 or 256 (256 is the models' own size).
            layers: Comma-separated models to run: dino (3D DINO embeddings), ink (3D ink), surface (recto surface).
            tta: Average the eight mirrorings for ink and surface (8 times their GPU time).
            compact: Keep 128 components of the embeddings and 16 levels of each probability (about a fifth of the size).
            allow_cpu: If ZeroGPU refuses (quota used up, no GPU free), run the middle 128 cube on the Space's CPU, about 10 seconds, instead of failing. Check cube_size and note_run in the answer.
        Returns:
            dict, the receipt (scan, cube_origin_zyx, cube_size, device, seconds, agreement_with_ink_model, note_run), with cube_ref (pass it to search or view while the Space keeps the cube in memory) and npz (the .npz file: grid (Z/8, Y/8, X/8, 864) float16 unit embeddings, or grid_reduced and grid_basis when compact; ink and surface (Z, Y, X) uint8; receipt as JSON bytes)
        """
        cube, meta, path = api_look(vid, z, y, x, size, layers, tta, compact, allow_cpu, request)
        out = cube_receipt(cube)
        out.update(source="api", cube_ref=cube.key)
        return dict(_plain(out), npz=FileData(path=path).model_dump())

    def search(cube: str, positive_zyx: list[list[int]] = [], negative_zyx: list[list[int]] = [],
               positive_vector: list[float] = [], negative_vector: list[float] = [], reference: bool = False,
               top_k: int = 20, top_pct: float = 8.0, return_concept: bool = False) -> dict:
        """Click search without clicking: score every 8x8x8 patch of a cube by the cosine similarity of its 3D DINO embedding to a concept, list the best patches, and check the scores against the 3D ink model (AUC beside a control range that should sit near 0.5). The concept is the unit mean of the embeddings at the positive voxels, a given 864-number vector and, if asked, the organizers' ink reference; negatives are subtracted. No GPU.

        Args:
            cube: A gallery id from gallery, or the cube_ref that look returned.
            positive_zyx: Scan voxels [[z, y, x], ...] inside the cube whose patches show the concept (the page's More like this).
            negative_zyx: Scan voxels inside the cube whose patches to subtract (the page's Not this).
            positive_vector: An 864-number concept, such as a concept.npy, reference's vector, or a concept returned for another cube.
            negative_vector: An 864-number concept to subtract.
            reference: Add the organizers' ink reference (mean embedding of 256 expert clicks on ink) to the positives.
            top_k: How many of the best patches to list, 1 to 200.
            top_pct: The page's Top % shown: the share of patches counted as matches, 1 to 40.
            return_concept: Also return the concept's 864-number vectors, to search another cube or scan with them.
        Returns:
            dict with cube, concept, top_patches (rank, score, center_zyx, patch_index_zyx, mean ink and surface probability), threshold, match_fraction, agreement_with_ink_model (auc, auc_control_shifted, auc_control_mean, auc_control_p05, auc_control_p95, ink_patch_fraction), reference_agreement_with_ink_model and note
        """
        return agent_search(cube, positive_zyx, negative_zyx, positive_vector, negative_vector, reference, top_k,
                            top_pct, return_concept)

    def reference() -> dict:
        """Get the organizers' ink reference: the unit-length mean 3D DINO embedding of 256 expert clicks on ink, the vector the 3D ink model was guided by. Instant, no GPU. Use it as search's positive_vector, or call search with reference true.

        Returns:
            dict with vector (864 numbers), tau (the cosine threshold the organizers used), embed_dim and source (repo, revision, file, sha256)
        """
        return agent_reference()

    def view(cube: str, axis: Literal["z", "y", "x", "all"] = "all", index: int = -1,
             layers: list[Layer] = ["ink", "reference"], positive_zyx: list[list[int]] = [],
             negative_zyx: list[list[int]] = [], positive_vector: list[float] = [], top_pct: float = 8.0,
             opacity: float = 0.7) -> FileData:
        """Draw a cube's slices as a PNG, like the page: the three views (top z, front y, side x) side by side, or one of them; the scan in gray, ink red, recto surface green, the organizers' ink reference amber, a concept cyan, white and magenta crosses on its voxels. Reads the scan from the open-data bucket, no GPU.

        Args:
            cube: A gallery id from gallery, or the cube_ref that look returned.
            axis: all (the three views through the cube's point, side by side), or one view: z (top), y (front) or x (side).
            index: For one view, the slice inside the cube, 0 to size - 1; -1 (and always with all) for the slice through the cube's point.
            layers: Layers to draw: ink, surface, reference, concept, pca (DINO colors).
            positive_zyx: Scan voxels [[z, y, x], ...] for the cyan concept layer.
            negative_zyx: Scan voxels to subtract from that concept.
            positive_vector: An 864-number concept for the cyan layer.
            top_pct: Share of patches lit in the reference and concept layers, 1 to 40.
            opacity: Layer opacity, 0 to 1.
        Returns:
            file, a PNG: 512 by 512 pixels for one view, 1552 by 512 for all three
        """
        return FileData(path=agent_view(cube, axis, index, layers, positive_zyx, negative_zyx, positive_vector,
                                        top_pct, opacity))

    def checked(fn):
        """guard, plus a readable refusal for input of the wrong type (gr.api passes JSON values through)."""
        inner = guard(fn)

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            try:
                return inner(*args, **kwargs)
            except gr.Error:
                raise
            except (TypeError, ValueError, KeyError) as exc:
                raise gr.Error(f"bad input: {exc}") from None
        return wrapped

    for fn in (volumes, gallery, reference):
        gr.api(checked(fn), api_name=fn.__name__, queue=False)
    for fn in (gallery_cube, search):
        gr.api(checked(fn), api_name=fn.__name__, concurrency_id="files", concurrency_limit=8)
    for fn in (random_point, view):
        gr.api(checked(fn), api_name=fn.__name__, concurrency_id="bucket", concurrency_limit=4)
    gr.api(checked(look), api_name="look", concurrency_id="models", concurrency_limit=2)


class NoUrlFiles:
    """ASGI middleware: refuse Gradio's /file=<url> route, which would otherwise fetch any public URL for anyone.
    This Space serves its own files only."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            from urllib.parse import unquote
            path = unquote(unquote(scope.get("path", ""))).lower()
            if "/file=http:" in path or "/file=https:" in path or "/file=//" in path:
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                await send({"type": "http.response.body", "body": b"Scroll Lens does not fetch URLs for callers."})
                return
        await self.app(scope, receive, send)


HEAD = """
<meta name="description" content="Scroll Lens: look inside Herculaneum scroll CT scans with the Vesuvius Challenge's
3D DINO, 3D ink and recto surface models; click to search. API and MCP server for agents.">
<meta property="og:title" content="Scroll Lens">
<meta property="og:description" content="Look inside a Herculaneum scroll with the Vesuvius Challenge's 3D models,
and click to search. Model output, not a reading.">
"""


def launch_kwargs():
    from starlette.middleware import Middleware
    VIEW_DIR.mkdir(parents=True, exist_ok=True)
    return dict(theme=theme(), css=CSS, head=HEAD, footer_links=["api", "gradio"], allowed_paths=[str(VIEW_DIR)],
                mcp_server=True, max_file_size="5mb", app_kwargs={"middleware": [Middleware(NoUrlFiles)]})


if __name__ == "__main__":
    startup()
    build_demo().queue(max_size=256, default_concurrency_limit=8).launch(**launch_kwargs())
