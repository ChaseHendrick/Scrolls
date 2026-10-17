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
STATE_TTL_S = 6 * 3600              # a visitor's session state (a cube key and clicks) is dropped after this
MAX_CLICKS = 512                    # clicks a session keeps, More like this and Not this together
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


def _gpu_text(exc):
    """A ZeroGPU error's own message (gr.Error's str() is its repr, with quotes)."""
    return str(getattr(exc, "message", None) or exc).strip().strip("'\"").strip()


def _is_gpu_refusal(exc):
    return (str(getattr(exc, "title", "") or "") in GPU_REFUSALS or "GPU task aborted" in str(exc)
            or "No GPU was available" in str(exc))


def cpu_run(eng, cube, layers, focus=None):
    if not CPU_SLOT.acquire(blocking=False):
        raise LensError("the Space's CPU is busy with another fallback run; try again in a minute, or sign in to "
                        "Hugging Face for more ZeroGPU time")
    try:
        import torch
        torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))     # leave a core for the page
        return eng.run(_window(cube, CPU_SIZE, focus), layers, device="cpu", tta=False)
    finally:
        CPU_SLOT.release()


def run_models(cube, layers, tta, allow_cpu=True, focus=None):
    """Run on the GPU when there is one; on ZeroGPU fall back to the CPU when the GPU is refused, on the CPU_SIZE
    window around `focus` (the point, in cube voxels; see window_offset). Returns the result and a note for the
    visitor (empty when it ran as asked)."""
    eng = engine()
    import torch
    if ON_ZERO_GPU:
        try:
            return gpu_run(cube, tuple(layers), bool(tta)), ""
        except Exception as exc:  # noqa: BLE001
            if not _is_gpu_refusal(exc):
                if str(getattr(exc, "title", "")) == "ZeroGPU worker error":
                    raise LensError(f"the models failed on the GPU ({_gpu_text(exc)[:200]}); try again, or try "
                                    "another point") from None
                raise
            if not allow_cpu:
                raise LensError(f"ZeroGPU refused this call: {_gpu_text(exc)[:300]} Pass allow_cpu=True to run "
                                f"the {CPU_SIZE}³ around the point on the CPU instead.") from None
            log(f"GPU refused ({exc}); running on the CPU")
            note = (f"ZeroGPU refused the run ({_gpu_text(exc).rstrip('. ')[:200]}), so the models ran on the "
                    f"Space's CPU, on the {CPU_SIZE}³ voxels around your point. ZeroGPU time comes back each day; "
                    "signing in to Hugging Face gives more.")
            return cpu_run(eng, cube, layers, focus), note
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu" and cube.shape[0] > CPU_SIZE:
        return (cpu_run(eng, cube, layers, focus),
                f"No GPU here, so the models ran on the CPU on the {CPU_SIZE}³ voxels around your point.")
    return eng.run(cube, layers, device=device, tta=tta), ""


# One model run at a time per visitor or caller, so one script cannot hold the GPU and the queue for everyone.
RUNNING = collections.Counter()
RUN_LOCK = threading.Lock()


def client_of(request):
    if request is None:
        return None
    user = getattr(request, "username", None)
    if user:
        return f"user:{user}"
    headers = getattr(request, "headers", None) or {}
    # the last X-Forwarded-For entry is the one the Space's own proxy adds; earlier ones are what the caller sent
    forwarded = (headers.get("x-forwarded-for") or "").split(",")[-1].strip()
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


def window_offset(size, n, focus=None):
    """Where the CPU fallback's n³ window sits in a size³ cube: around `focus` (the point, in cube voxels), on the
    8-voxel patch grid and inside the cube, so the point is always in it (near a scan's edge the cube is not centered
    on the point); the middle when no point is given."""
    if n >= size:
        return (0, 0, 0)
    if focus is None:
        return ((size - n) // 2,) * 3
    return tuple(int(min(max((int(f) - n // 2) // lens.PATCH * lens.PATCH, 0), size - n)) for f in focus)


def _window(cube, n, focus=None):
    o = window_offset(cube.shape[0], n, focus)
    return cube[o[0]:o[0] + n, o[1]:o[1] + n, o[2]:o[2] + n]


def _local(point, origin):
    return tuple(int(p) - int(o) for p, o in zip(point, origin))


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

    def reference_agreement(self):
        """The organizers' reference against the 3D ink model for this cube, with the control range (lens.agreement),
        worked out once from the arrays held here."""
        if self.ref_sim is None or "ink" not in self.result:
            return None
        if getattr(self, "_ref_agreement", None) is None:
            self._ref_agreement = lens.agreement(self.ref_sim, self.result["ink"])
        return self._ref_agreement

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
            tmp = Path(f"{path}.{uuid.uuid4().hex[:8]}.part")      # concurrent first opens never share it
            tmp.write_bytes(gzip.compress(body + b"".join(blobs), compresslevel=3, mtime=0))
            os.replace(tmp, path)
            self.data_path = str(path)
            return self.data_path


class CubeCache:
    """Two least-recently-used pools: gallery cubes (reloaded from disk when they drop out) and cubes the models ran
    on now (lost when they drop out), so opening gallery cubes never pushes out a visitor's run."""

    def __init__(self, size=CACHE_CUBES):
        self.size = size
        self.pools = {"gallery": collections.OrderedDict(), "run": collections.OrderedDict()}
        self.lock = threading.Lock()

    def _pool(self, key):
        return self.pools["gallery" if key.startswith("gallery:") else "run"]

    @property
    def items(self):
        return {**self.pools["gallery"], **self.pools["run"]}

    def get(self, key):
        with self.lock:
            pool = self._pool(key)
            if key in pool:
                pool.move_to_end(key)
                return pool[key]
        if key.startswith("gallery:"):
            return self.put(gallery_cube(key.split(":", 1)[1]))
        raise LensError("this cube is no longer in the Space's memory (it keeps the last few); run it again")

    def put(self, cube):
        with self.lock:
            pool = self._pool(cube.key)
            pool[cube.key] = cube
            pool.move_to_end(cube.key)
            while len(pool) > self.size:
                key, old = pool.popitem(last=False)
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
    return {"view": None, "pos": [], "neg": [], "acked": [], "keys": [], "view_ticket": 0, "rev": 0}


_REV_LOCK = threading.Lock()
_LAST_REV = [0]


def next_rev():
    """A number larger than every one before, also across restarts of the Space (microseconds since 1970, below
    2**53 so the browser reads it exactly). Every answer to the viewer carries one, and the viewer shows only the
    newest; opens take one as their ticket (show_view)."""
    with _REV_LOCK:
        _LAST_REV[0] = max(_LAST_REV[0] + 1, time.time_ns() // 1000)
        return _LAST_REV[0]


def cube_key(view):
    return f"{view['volume']}:{','.join(map(str, view['origin']))}:{view['size']}"


def place_of(cube):
    """cube_key for a cube in CUBES (its scan, origin and size), for clicks on a cube no longer on screen."""
    origin = [int(v) for v in cube.meta["cube_origin_zyx"]]
    return f"{cube.meta['volume']}:{','.join(map(str, origin))}:{cube.size}"


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


def ack_only(key, clicks):
    """A viewer answer that only acknowledges click ids, for clicks the server cannot use (viewer.js onValue)."""
    return json.dumps({"key": key, "rev": next_rev(), "ack_only": True,
                       "clicks": {"acked": [str(c.get("id")) for c in clicks]}})


# ---------------------------------------------------------------- a visitor's page state, changed in place
#
# Gradio hands every event of one visitor the same state dict, and keeps whatever the event returns. An event that
# rebuilt the dict from what it read when it started would put that old copy back when it finished late: clicks made
# during a 20-second model run would be lost, and a click answered after the visitor opened another cube would bring
# the old cube back. So the page events change that one dict in place, under STATE_LOCK, only once their slow part
# (reading a cube, the models) is done, and the viewer orders their answers by revision.

STATE_LOCK = threading.RLock()
KEEP_KEYS = 16                      # the cubes a page has shown that its clicks may still name
KEEP_ACKS = 256


def snapshot(state, rev=True):
    """A copy of the visitor's state to draw from (viewer_value, numbers, save_files), with a new revision."""
    with STATE_LOCK:
        if rev:
            state["rev"] = next_rev()
        return dict(state, pos=list(state["pos"]), neg=list(state["neg"]), acked=list(state.get("acked", [])),
                    keys=list(state.get("keys", [])))


def show_view(state, view, ticket, force=False):
    """Put `view` on screen unless the visitor has since opened another cube (a later ticket, from next_rev when
    the open began). A finished model run always shows (`force`): it spent the visitor's GPU time. Returns whether
    `view` is on screen now."""
    with STATE_LOCK:
        if not force and ticket < state.get("view_ticket", 0):
            return False
        state["view"] = view
        state["view_ticket"] = max(ticket, state.get("view_ticket", 0))
        state["keys"] = ([k for k in state.get("keys", []) if k != view["cache"]] + [view["cache"]])[-KEEP_KEYS:]
        return True


def _ack(state, ids):
    acked = list(state.get("acked", []))
    seen = set(acked)
    acked += [i for i in dict.fromkeys(str(i) for i in ids) if i not in seen]
    state["acked"] = acked[-KEEP_ACKS:]                 # in arrival order: the newest ids stay


def take_clicks(state, key, clicks):
    """Add the viewer's clicks on the cube `key` (a CUBES key) to the visitor's concept. The viewer resends every
    click until it is acknowledged, so the ids stop a click counting twice; a click on a cube this page has moved on
    from still counts (a concept spans cubes) but never brings that cube back. Returns (taken, problem): whether the
    clicks could be used, and why some were refused."""
    with STATE_LOCK:
        view = state["view"]
        known = key in state.get("keys", []) or (view is not None and key == view["cache"])
    if not known:
        with STATE_LOCK:
            _ack(state, [c.get("id") for c in clicks])
        return False, "This cube is no longer in this page's session; open it again to search it."
    try:
        cube = CUBES.get(key)               # a gallery cube reloads from disk; a run cube may have dropped out
    except LensError as exc:
        with STATE_LOCK:
            _ack(state, [c.get("id") for c in clicks])
        return False, str(exc)
    place, problem = place_of(cube), None
    with STATE_LOCK:
        seen = set(state.get("acked", []))
        for click in clicks:
            cid = str(click.get("id"))
            if cid in seen:
                continue
            seen.add(cid)
            _ack(state, [cid])              # acknowledged even when refused, so the viewer does not resend it
            if len(state["pos"]) + len(state["neg"]) >= MAX_CLICKS:
                problem = f"a page keeps at most {MAX_CLICKS} clicks; clear some to add more"
                continue
            try:
                vox = [int(v) for v in click.get("index")]
                if len(vox) != 3 or not all(0 <= v < cube.size for v in vox):
                    raise LensError("that click is outside the cube")
                vec = cube.vector(vox)
            except (TypeError, ValueError, LensError) as exc:
                problem = str(exc) if isinstance(exc, LensError) else "a click needs a voxel z, y, x"
                continue
            kind = "neg" if click.get("value") == "neg" else "pos"
            origin = [int(v) for v in cube.meta["cube_origin_zyx"]]
            state["tick"] = state.get("tick", 0) + 1
            state[kind] = state[kind] + [{"id": cid, "volume": cube.meta["volume"], "cube": place, "voxel": vox,
                                          "t": state["tick"], "voxel_zyx": [v + o for v, o in zip(vox, origin)],
                                          "vec": vec}]
    return True, problem


def undo_click(state, cid=None):
    """Forget the click with id `cid` (one still on its way is dropped when it arrives), or else the most recent
    click (More like this or Not this) on any cube."""
    with STATE_LOCK:
        if cid:
            cid = str(cid)
            for kind in ("pos", "neg"):
                if any(c.get("id") == cid for c in state[kind]):
                    state[kind] = [c for c in state[kind] if c.get("id") != cid]
                    return
            _ack(state, [cid])
            return
        clicks = [(c.get("t", 0), kind, i) for kind in ("pos", "neg") for i, c in enumerate(state[kind])
                  if c["cube"] != "file"]
        if not clicks:
            raise LensError("no click to undo")
        _, kind, i = max(clicks)
        state[kind] = state[kind][:i] + state[kind][i + 1:]


def clear_clicks(state, ids=()):
    """Forget every click and loaded concept; `ids` are clicks the viewer sent but has no answer for yet, dropped
    when they arrive."""
    with STATE_LOCK:
        state["pos"], state["neg"] = [], []
        _ack(state, list(ids)[:KEEP_ACKS])


def set_concept(state, pos, neg):
    """Replace the visitor's clicks with a loaded concept.npy (and concept_not.npy), or with `pos` and `neg` None
    drop the loaded files and keep the clicks."""
    with STATE_LOCK:
        if pos is None:
            state["pos"] = [c for c in state["pos"] if c["cube"] != "file"]
            state["neg"] = [c for c in state["neg"] if c["cube"] != "file"]
        else:
            state["pos"], state["neg"] = list(pos), list(neg)


# ---------------------------------------------------------------- drawing on the server (the agent tools)

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
        blend(COLORS["reference"], up(_top_alpha(_take(s3, axis, tok_i), s3, top_pct, floor=lens.TAU)))
    if "Your clicks" in overlays:
        s3 = tool_click_sim(state)
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


def scale_of(size):
    return max(1, 512 // int(size))


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
    ag = cube.reference_agreement()
    if ag and ag.get("auc") is not None:
        lines.append(f"**Check.** The organizers' ink reference picks out the patches the 3D ink model marks as ink "
                     f"with AUC {ag['auc']:.2f}; controls (the ink mask moved away from its place) give "
                     f"{ag['auc_control_p05']:.2f} to {ag['auc_control_p95']:.2f}, and the AUC means something only "
                     f"above that range. Ink covers {ag['ink_patch_fraction']:.1%} of patches. Agreement between two "
                     "models, not ground truth.")
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
                         f"(controls {a.get('auc_control_p05', 0):.2f} to {a.get('auc_control_p95', 0):.2f}).")
        clicked = {c["cube"] for c in state["pos"] + state["neg"] if c["cube"] != "file"}
        loaded = any(c["cube"] == "file" for c in state["pos"])
        loaded_not = any(c["cube"] == "file" for c in state["neg"])
        lines.append(f"**Your concept:** {len([c for c in state['pos'] if c['cube'] != 'file'])} positive and "
                     f"{len([c for c in state['neg'] if c['cube'] != 'file'])} negative clicks from {len(clicked)} "
                     f"cube(s){', plus your concept.npy' if loaded else ''}"
                     f"{' and concept_not.npy' if loaded_not else ''}.{extra}")
    lines.append("_Model output, not a reading. A cube is smaller than one letter._")
    return "\n\n".join(lines)


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
    focus = _local(point, origin)
    result, note = run_models(ct, layers, bool(tta), allow_cpu=allow_cpu, focus=focus)
    n = ran_size(result)
    if n != size:                                  # the CPU fallback ran the window around the point
        origin = tuple(int(o + d) for o, d in zip(origin, window_offset(size, n, focus)))
        fg = lens.foreground(_window(ct, n, focus))
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
    """The dropdown shows the title alone, on one line; the point and size are in the readout below the views."""
    return it["title"]


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


# ---------------------------------------------------------------- the agent tools' cubes
#
# The agent tools below (PR #114) keep their own view of a cube, with every array in it; the page uses CUBES.

def tool_new_view(vid, origin, size, point, cube, result, source, note=""):
    """Everything the agent tools need about one cube: the scan cube and all arrays (kept in VIEW_CACHE, three at a
    time). The page keeps its cubes in CUBES instead."""
    import numpy as np
    if cube.shape[0] != size:                      # the CPU fallback ran a smaller cube around the point
        off = window_offset(size, cube.shape[0], _local(point, origin))
        origin = tuple(int(v + d) for v, d in zip(origin, off))
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


def tool_click_sim(state):
    view = state["view"]
    p, n = click_concept(state)
    if view is None or p is None or "grid" not in view:
        return None
    import numpy as np
    return lens.similarity(view["grid"].astype(np.float32), p, n)


def tool_load_point(vid, z, y, x, size, layers, tta):
    import numpy as np
    size = lens.check_size(size)
    layers = lens.check_layers([{"3D DINO embeddings": "dino", "3D ink model": "ink",
                                 "Recto surface model": "surface"}.get(k, k) for k in layers])
    point = (int(z), int(y), int(x))
    origin = lens.cube_origin(vid, point, size)
    cube = lens.read_cube(vid, origin, size)
    lens.check_cube(cube)
    result, note = run_models(cube, layers, tta, focus=_local(point, origin))
    src = "gpu" if result.get("device", "").startswith("cuda") else "cpu"
    ran = _window(cube, ran_size(result), _local(point, origin))      # the CPU fallback runs around the point
    return tool_new_view(vid, origin, size, point, np.ascontiguousarray(ran), result, src, note)


def tool_load_gallery(cube_id):
    for it in GALLERY:
        if it["id"] == cube_id:
            meta, arrays = lens.load_npz(HERE / "gallery" / it["file"])
            origin, size = tuple(meta["cube_origin_zyx"]), int(meta["cube_size"])
            cube = lens.read_cube(meta["volume"], origin, size)
            result = dict(arrays, seconds=meta.get("seconds", {}), device=meta.get("device"),
                          device_name=meta.get("device_name"), tta=meta.get("tta", False))
            view = tool_new_view(meta["volume"], origin, size, tuple(meta["point_zyx"]), cube, result, "gallery",
                            it.get("note", ""))
            view["receipt"]["gallery_id"] = cube_id
            return view
    raise LensError(f"no gallery cube {cube_id!r}")


def tool_save_files(state):
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
        allow_cpu: when ZeroGPU refuses, run the 128 cube around the point on the Space's CPU instead of failing.

    Returns:
        The .npz file.
    """
    import numpy as np
    tta, compact, allow_cpu = as_bool(tta, "tta"), as_bool(compact, "compact"), as_bool(allow_cpu, "allow_cpu")
    size = lens.check_size(size)
    layers = lens.check_layers([s.strip() for s in str(layers).split(",") if s.strip()])
    point = check_point(z, y, x)
    engine()                                       # refuse before reading the bucket while the models load
    origin = lens.cube_origin(vid, point, size)
    cube = lens.read_cube(vid, origin, size)
    lens.check_cube(cube)
    focus = _local(point, origin)
    result, note = run_models(cube, layers, tta, allow_cpu=allow_cpu, focus=focus)
    n = ran_size(result)
    if n != size:                                  # the CPU fallback ran the window around the point
        origin = tuple(int(o + d) for o, d in zip(origin, window_offset(size, n, focus)))
    meta = lens.receipt(vid, origin, n, point, result, ENGINE.describe(), {"source": "api", "note_run": note,
                                                                          "foreground": lens.foreground(cube)})
    if "grid" in result and "ink" in result:
        meta["agreement_with_ink_model"] = lens.agreement(
            lens.similarity(np.asarray(result["grid"], np.float32), REFERENCE), result["ink"])
    OUT.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(dir=OUT))
    return str(lens.save_npz(d / f"{vid}-{'-'.join(map(str, origin))}-{n}.npz", meta, result, compact=compact))


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
    view = tool_load_gallery(cube_id) if cube_id else tool_load_point(scan, point[0], point[1], point[2], size,
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
    paths = tool_save_files({"view": view, "pos": [], "neg": []})
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
1. **Gallery** (no GPU needed): pick a ready-made cube; it opens at once. *Previous*, *Next* and *Random* step
   through the list, and you can type in the list to search it.
2. **Your own point**: pick a scan, type a point in voxels (z, y, x) or press **Surprise me**, then **Run the models**.
   A 256³ cube is the models' own working size and uses about 5 seconds of ZeroGPU time (with ZeroGPU's own
   overhead, a call is about 10 seconds). When your daily ZeroGPU time runs out, Scroll Lens runs a 128³ cube on the
   CPU instead (about 10 seconds).
3. **Look**: drag a slider under a view, or drag inside a view to move the crosshair; the other views follow as you
   move. The wheel or the arrow keys step one slice (Shift: 8). Ctrl or Cmd with the wheel, or a pinch, zooms;
   right-drag or Shift-drag pans; double-click resets. The line under the views reads out what is under the pointer.
4. **Search**: a click only moves the crosshair until you choose *More like this*; then click a patch.
   *Not this* subtracts one; *Undo click* (or Ctrl or Cmd with Z) forgets the last one.
   *Top % shown* sets how many of the most similar patches light up.
5. **3D view**: turns the three views into one 3D space: the three slices as planes through the cube (they move
   as you drag the sliders), ink and surface as points, and the patches like your concept or the organizers'
   reference glowing. Drag to rotate, wheel to zoom, right-drag to pan, *Spin* to turn it slowly; click a slice to
   move there (or search there, with *More like this* chosen). *Flat views* goes back.
6. **Take it away**: **Save files** gives the model outputs (.npz), the receipt (.json) and, after clicks, your
   `concept.npy`. *Copy link* gives a link that opens this cube at this crosshair.

Scripts and agents: see *For scripts and agents* below, or the README.
"""

AGENTS_TEXT = """\
Everything on this page is also an API endpoint and an MCP tool, so an AI agent or a script can use Scroll Lens
the way a person does. Every answer includes `open_in_browser`, a link that opens the same cube here for a person.

- `list_scans`: the twelve scans, their sizes, and what each model saw of them in training. No GPU.
- `list_gallery`: the ready-made cubes. No GPU.
- `random_point`: a point on the papyrus of a scan. No GPU.
- `inspect_cube`: three slice views with overlays, and the cube's numbers and checks. No GPU for a gallery cube.
- `search_cube`: places like your example points or concept file (or the organizers' ink reference). No GPU for a
  gallery cube.
- `download_cube`: the models' outputs as arrays (.npz). No GPU for a gallery cube.
- `look`: the .npz for any point, for batch scripts. Uses the GPU.

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
#sl-gpick input { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
#sl-gpick [role=option] { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.sl-head { display:flex; gap:14px; align-items:baseline; flex-wrap:wrap; margin: 4px 0 2px; }
.sl-head h1 { margin:0; font-size: 1.6rem; letter-spacing: .01em; }
.sl-head span { color: var(--body-text-color-subdued); }
footer.sl-credit { text-align:center; color: var(--body-text-color-subdued); font-size:.85rem; margin-top: 8px; }
#sl-viewer-html .slv { display:flex; flex-direction:column; gap:8px; }
#sl-viewer-html .slv-bar { display:flex; flex-direction:column; gap:6px; font-size:.86rem; }
#sl-viewer-html .slv-group { display:flex; flex-wrap:wrap; gap:4px 8px; align-items:center; }
#sl-viewer-html .slv-chip { display:inline-flex; align-items:center; gap:5px; padding:2px 9px; border:1px solid var(--border-color-primary);
  border-radius:999px; cursor:pointer; user-select:none; background: var(--block-background-fill); }
#sl-viewer-html .slv-chip input { margin:0; }
#sl-viewer-html .slv-chip i { width:10px; height:10px; border-radius:2px; display:inline-block; }
#sl-viewer-html .slv-label { color: var(--body-text-color-subdued); margin-right: 2px; }
#sl-viewer-html .slv-sliders label { display:inline-flex; align-items:center; gap:5px; margin-right: 8px; }
#sl-viewer-html .slv-sliders input[type=range] { width:96px; }
#sl-viewer-html .slv-buttons button { font-size:.8rem; padding:3px 10px; border:1px solid var(--border-color-primary); border-radius:6px;
  background: var(--button-secondary-background-fill); color: var(--button-secondary-text-color); cursor:pointer; }
#sl-viewer-html .slv-buttons button:hover { background: var(--button-secondary-background-fill-hover); }
#sl-viewer-html .slv-status { display:flex; gap:10px; align-items:center; font-size:.86rem; color: var(--body-text-color-subdued);
  min-height:1.4em; word-break: break-all; }
#sl-viewer-html .slv-status progress { width:160px; flex: none; }
#sl-viewer-html .slv-views { display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:8px; }
@media (max-width: 900px) { #sl-viewer-html .slv-views { grid-template-columns: 1fr; } }
#sl-viewer-html .slv-view { display:flex; flex-direction:column; gap:4px; min-width:0; }
#sl-viewer-html .slv-title { font-size:.85rem; display:flex; justify-content:space-between; color: var(--body-text-color-subdued); }
#sl-viewer-html .slv-view canvas { display:block; background:#0b0f14; border-radius:6px; touch-action:none; cursor:crosshair;
  outline:none; }
#sl-viewer-html .slv-view canvas:focus-visible { box-shadow: 0 0 0 2px var(--color-accent); }
#sl-viewer-html .slv-view input[type=range] { width:100%; }
#sl-viewer-html .slv-more { display:flex; flex-direction:column; gap:6px; }
#sl-viewer-html .slv-more > summary { cursor:pointer; color: var(--body-text-color-subdued); font-size:.84rem; }
@media (min-width: 601px) { #sl-viewer-html .slv-more > summary { display:none !important; } }
#sl-viewer-html .slv-views[hidden], #sl-viewer-html .slv-3d[hidden] { display:none !important; }
#sl-viewer-html .slv-3d { display:flex; flex-direction:column; gap:6px; }
#sl-viewer-html .slv-3d-canvas { display:block; width:100%; border-radius:6px; background:#0b0f14; touch-action:none; cursor:grab; }
#sl-viewer-html .slv-3d-canvas:active { cursor:grabbing; }
#sl-viewer-html .slv-3d-sliders label { display:inline-flex; align-items:center; gap:6px; flex:1 1 30%; min-width:150px; }
#sl-viewer-html .slv-3d-sliders input[type=range] { flex:1; }
#sl-viewer-html .slv-3d-toggle { font-weight:600; }
#sl-viewer-html .slv-readout { font-family: ui-monospace, monospace; font-size:.8rem; min-height:1.3em; }
#sl-viewer-html .slv-help { font-size:.78rem; color: var(--body-text-color-subdued); }
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

    def shown(state):                 # the visitor's own state dict, and what the viewer and the text show of it
        snap = snapshot(state)
        return [state, viewer_value(snap), numbers(snap)]

    def fresh():                      # a new cube: clear the old saved files and receipt
        return [None, None]

    @soft(5)
    def on_run(vid, z, y, x, size, layers, tta, state, request: gr.Request):
        ticket = next_rev()
        with one_run(request):
            view = load_point(vid, z, y, x, size, layers, tta)
        show_view(state, view, ticket, force=True)
        return shown(state) + fresh()

    def open_gallery(cube_id, state):
        if not cube_id:
            raise LensError("pick a gallery cube")
        ticket = next_rev()
        view = load_gallery(cube_id)
        if not show_view(state, view, ticket):
            return [gr.skip()] * 11           # the visitor opened another cube meanwhile, and that one stays
        p = view["point"]
        return shown(state) + fresh() + [view["volume"], p[0], p[1], p[2], view["size"], cube_id]

    @soft(11)
    def on_gallery(cube_id, state):
        return open_gallery(cube_id, state)

    @soft(11)
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
        is being handled (take_clicks)."""
        data = getattr(evt, "_data", None) or {}
        key = str(data.get("key") or "")
        clicks = [c for c in (data.get("clicks") or [])[:64] if isinstance(c, dict)]
        if state["view"] is None and key.startswith("gallery:"):
            ticket = next_rev()             # the session expired while the browser kept showing this gallery cube
            try:
                show_view(state, load_gallery(key.split(":", 1)[1]), ticket)
            except LensError:
                pass
        taken, problem = take_clicks(state, key, clicks)
        if problem:
            gr.Warning(problem)
        if not taken:
            return [state, ack_only(key, clicks), gr.skip()]
        return shown(state)

    @soft(3)
    def on_undo(state, evt: gr.EventData):
        """Forget a click: the one the viewer names (it may still be on its way), else the most recent on any cube."""
        data = getattr(evt, "_data", None) or {}
        undo_click(state, data.get("id"))
        return shown(state)

    @soft(3)
    def on_clear(state, evt: gr.EventData):
        data = getattr(evt, "_data", None) or {}
        clear_clicks(state, [str(i) for i in (data.get("ids") or []) if isinstance(i, (str, int))])
        return shown(state)

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
            set_concept(state, None, None)
            return shown(state)
        pos, neg = [], []
        for p in paths[:2]:
            item = {"volume": "file", "cube": "file", "voxel": None, "voxel_zyx": None, "vec": lens.load_concept(p)}
            (neg if "_not" in Path(p).name.lower() else pos).append(item)
        if not pos:
            raise LensError("load concept.npy too: concept_not.npy alone has nothing to look for")
        set_concept(state, pos, neg)
        return shown(state)

    @soft(2)
    def on_save(state):
        snap = snapshot(state, rev=False)
        return save_files(snap), (snap["view"] or {}).get("receipt")

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
                ok = {k: str(q.get(k, "")).isascii() and str(q.get(k, "")).isdigit() for k in "zyx"}
                fields = [vid] + [int(q[k]) if ok[k] else gr.skip() for k in "zyx"]
                bad = [k for k in "zyx" if not ok[k]]
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
        ticket = next_rev()
        try:
            view = load_gallery(cube_id)
        except (LensError, OSError) as exc:
            log(f"link not loaded: {exc}")
            gr.Warning(f"The gallery cube could not be opened: {exc}")
            return shown(state) + fields + [size, gr.skip(), tab]
        if not show_view(state, view, ticket):       # the visitor already opened another cube
            return [gr.skip()] * 3 + fields + [size, gr.skip(), tab]
        if not q.get("v"):
            p = view["point"]
            fields = [view["volume"], p[0], p[1], p[2]]
        if not q.get("size"):
            size = gr.update(value=view["size"])
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
                                            filterable=True, elem_id="sl-gpick")
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
                    concept_up = gr.UploadButton("Load concept.npy (and concept_not.npy): replaces your clicks",
                                                 file_types=[".npy"], file_count="multiple", type="filepath", size="sm")
                    save = gr.Button("Save files", size="sm")
                    files = gr.File(label="Model outputs, receipt and your concept", file_count="multiple")
                    receipt = gr.JSON(label="Receipt")
                with gr.Accordion("How to use it", open=False):
                    gr.Markdown(HOW_TO)
                with gr.Accordion("For agents and scripts", open=False, elem_id="sl-agents"):
                    gr.Markdown(AGENTS_TEXT.format(url=page_url().rstrip("/") if page_url() != "/" else
                                                   "https://sharpmeow-scroll-lens.hf.space"))
            with gr.Column(scale=3, min_width=320, elem_id="sl-viewer"):
                viewer = gr.HTML("", html_template='<div class="slv-mount"></div>', js_on_load=viewer_js(),
                                 apply_default_css=False, elem_id="sl-viewer-html")
                info = gr.Markdown(numbers(empty_state()))
                with gr.Accordion("About", open=False):
                    gr.Markdown(INTRO)
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

        out = [state, viewer, info]
        stale = [files, receipt]
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
        viewer.clear(on_clear, state, out, show_progress="hidden", **hidden)
        viewer.undo(on_undo, state, out, show_progress="hidden", **hidden)
        viewer.apply(on_viewer_use, None, [vid, z, y, x, tabs], show_progress="hidden", **hidden)
        concept_up.upload(on_concept, [concept_up, state], out, **hidden)
        save.click(on_save, state, [files, receipt], **hidden)
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
        demo.load(on_load, state, out + [vid, z, y, x, size, gpick, tabs], **hidden)
    return demo


class NoUrlFiles:
    """ASGI middleware, a second guard beside close_url_fetching: refuse Gradio's file routes when they name a URL
    (/file=URL, /file/URL), and uploads of more than MAX_UPLOAD_BYTES in one request (max_file_size counts each file
    of a request on its own)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            from urllib.parse import unquote
            path = unquote(unquote(scope.get("path", ""))).lower()
            if any(t in path for t in ("/file=http:", "/file=https:", "/file=//", "/file/http:", "/file/https:",
                                       "/file//")):
                return await self.refuse(send, 403, b"Scroll Lens does not fetch URLs for callers.")
            if scope.get("method") == "POST" and path.rstrip("/").endswith("/upload"):
                length = dict(scope.get("headers") or []).get(b"content-length")
                if length is not None and length.isdigit() and int(length) > MAX_UPLOAD_BYTES:
                    return await self.refuse(send, 413, b"An upload to Scroll Lens is at most 12 MB.")
        await self.app(scope, receive, send)

    @staticmethod
    async def refuse(send, status, body):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": body})


MAX_UPLOAD_BYTES = 12 << 20


HEAD = """
<meta name="description" content="Scroll Lens: look inside Herculaneum scroll CT scans with the Vesuvius Challenge's
3D DINO, 3D ink and recto surface models; click to search. API and MCP server for agents.">
<meta property="og:title" content="Scroll Lens">
<meta property="og:description" content="Look inside a Herculaneum scroll with the Vesuvius Challenge's 3D models,
and click to search. Model output, not a reading.">
"""


def close_url_fetching():
    """Gradio streams any public URL through its file routes (/file=URL and the older /file/URL) and downloads any URL
    a caller puts in a file input, with no size limit. This Space serves its own files only, and downloads a file input
    only from itself or the Hugging Face Hub (an agent may pass back a concept.npy this Space gave it)."""
    import gradio.processing_utils as pu
    import gradio.route_utils as ru
    import gradio.routes as rt
    from urllib.parse import urlparse
    from fastapi import HTTPException

    async def refuse_stream(url, request):
        raise HTTPException(status_code=403, detail="Scroll Lens does not fetch URLs for callers.")
    rt.secure_url_stream_response = ru.secure_url_stream_response = refuse_stream
    try:
        import gradio.static_server as ss
        ss.secure_url_stream_response = refuse_stream
    except ImportError:
        pass
    allowed = {h for h in (os.environ.get("SPACE_HOST"), "huggingface.co", "hf.co") if h}
    original = getattr(pu.async_ssrf_protected_download, "__wrapped_original__", pu.async_ssrf_protected_download)

    async def download(url, cache_dir):
        if (urlparse(url).hostname or "").lower() not in allowed:
            raise PermissionError("Scroll Lens downloads files only from this Space or the Hugging Face Hub")
        return await original(url, cache_dir)
    download.__wrapped_original__ = original
    pu.async_ssrf_protected_download = download


def launch_kwargs():
    from starlette.middleware import Middleware
    close_url_fetching()
    VIEW_DIR.mkdir(parents=True, exist_ok=True)
    return dict(theme=theme(), css=CSS, head=HEAD, footer_links=["api", "gradio"], allowed_paths=[str(VIEW_DIR)],
                mcp_server=True, max_file_size="5mb", app_kwargs={"middleware": [Middleware(NoUrlFiles)]})


if __name__ == "__main__":
    startup()
    fix_mcp_multiple_outputs()
    build_demo().queue(max_size=256, default_concurrency_limit=8).launch(**launch_kwargs())
