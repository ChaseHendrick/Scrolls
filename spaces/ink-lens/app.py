"""Ink Lens: a control-checked ink map of one region, in one ZeroGPU call, for VC3D.

The web page, the API and the MCP server. The model work is engine.py, the threshold gate.py, and the files VC3D reads
are written by the client (inklens.py) on the user's own machine: the Space keeps nothing. A region arrives as an
.npz (array "volume", uint8, layers first, about 9.6 um), is read into memory, and goes back as maps and a status.

On a ZeroGPU Space the GPU is attached only to gpu_lens, for a duration computed from the region's patch count
(engine.gpu_seconds). When ZeroGPU refuses (quota, no GPU free) a region of at most CPU_SIDE px with one window runs on
the Space's CPU instead; anything larger is pointed to local mode.

  python3 app.py            serve the page (on a Space, or on any computer: CUDA if present, else CPU)
"""

from __future__ import annotations

import functools
import json
import os
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

try:
    import spaces  # first, before torch: on a ZeroGPU Space it attaches the GPU to spaces.GPU functions
except ImportError:
    spaces = None

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import compare  # noqa: E402
import engine  # noqa: E402
import gate  # noqa: E402
import inklens  # noqa: E402
import volio  # noqa: E402
import zoo  # noqa: E402

ON_ZERO_GPU = bool(spaces) and os.environ.get("SPACES_ZERO_GPU", "").lower() in ("1", "true")
OUT = Path(tempfile.gettempdir()) / "ink-lens-out"
CPU_SIDE = 512
MAX_UPLOAD_BYTES = inklens.MAX_UPLOAD_BYTES
MAX_VOXELS = engine.MAX_SIDE * engine.MAX_SIDE * engine.MAX_LAYERS
ENGINE, ENGINE_ERROR = None, None
READY = threading.Event()
CPU_SLOT = threading.Semaphore(1)
GALLERY = HERE / "gallery"
HAS_GALLERY = (GALLERY / "index.json").is_file()   # the gallery tab and endpoint appear once one is published
COMPARE_MAX_SIDE = 512     # 9.6 um grid pixels: a 2048 px square of the 2.4 um scan, 109 layers (about 460 MB)
COMPARE_LOADED = {}
COMPARE_LOCK = threading.Lock()
GPU_REFUSALS = ("ZeroGPU quota exceeded", "ZeroGPU illegal duration", "ZeroGPU pending credits exceeded",
                "ZeroGPU queue timeout", "ZeroGPU client error")


class LensError(ValueError):
    """Shown to the caller as it is."""


def log(message):
    print(f"[ink-lens {time.strftime('%H:%M:%S')}] {message}", flush=True)


# ---------------------------------------------------------------- start-up

def _load():
    global ENGINE, ENGINE_ERROR
    try:
        # On ZeroGPU the readers stay on the CPU here: this thread is outside every spaces.GPU call, so moving them to
        # "cuda" reaches torch's low-level CUDA init, which ZeroGPU refuses. run() moves them inside the GPU call.
        ENGINE = engine.Engine(readers=tuple(engine.READERS), place_on_cuda=not ON_ZERO_GPU)
        log(f"readers ready in {ENGINE.startup_s} s")
    except Exception as exc:  # noqa: BLE001
        ENGINE_ERROR = f"{type(exc).__name__}: {exc}"
        log(f"readers failed to load: {ENGINE_ERROR}")
    finally:
        READY.set()


def startup():
    import shutil
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_load, name="load-readers", daemon=True).start()


def eng(wait_s=5.0):
    if not READY.wait(wait_s):
        raise LensError("the readers are still loading (about a minute after the Space wakes up); try again shortly")
    if ENGINE is None:
        raise LensError(f"the readers failed to load: {ENGINE_ERROR}")
    return ENGINE


# ---------------------------------------------------------------- the one GPU call

def _duration(volume, reader, windows):
    return engine.gpu_seconds(engine.patches(volume.shape[1], volume.shape[2], windows, reader))


def _on_gpu(fn):
    return spaces.GPU(duration=_duration)(fn) if ON_ZERO_GPU else fn


@_on_gpu
def gpu_lens(volume, reader, windows):
    """Both depth orders, every window, every chosen reader: one GPU call, so the map never runs without its
    control."""
    return ENGINE.run(volume, reader=reader, windows=windows, device="cuda")


def _is_refusal(exc):
    return (str(getattr(exc, "title", "") or "") in GPU_REFUSALS or "GPU task aborted" in str(exc)
            or "No GPU was available" in str(exc))


def run_engine(volume, reader, windows):
    e = eng()
    import torch
    if ON_ZERO_GPU:
        try:
            return gpu_lens(volume, reader, windows), ""
        except Exception as exc:  # noqa: BLE001
            if not _is_refusal(exc):
                raise
            note = f"ZeroGPU refused the call ({str(getattr(exc, 'message', exc))[:160]})"
    elif torch.cuda.is_available():
        return e.run(volume, reader=reader, windows=windows, device="cuda"), ""
    else:
        note = "No GPU here"
    if max(volume.shape[1:]) > CPU_SIDE or windows != 1:
        raise LensError(f"{note}. The CPU fallback takes regions up to {CPU_SIDE} px with one window; run larger "
                        "regions in local mode (python3 inklens.py run --local ...), or try again later")
    if not CPU_SLOT.acquire(blocking=False):
        raise LensError(f"{note}, and the Space's CPU is busy with another fallback run; try again in a minute")
    try:
        torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
        return e.run(volume, reader=reader, windows=windows, device="cpu"), f"{note}, so it ran on the Space's CPU."
    finally:
        CPU_SLOT.release()


# ---------------------------------------------------------------- comparison: many models, one region

def _compare_duration(volume, scan, models, centres, steps, labels=None, sample=None):
    k = 4 if scan == "2.4" else 1
    return compare.estimate(models, volume.shape[1] // k, volume.shape[2] // k, len(centres) * len(steps))


def _compare_on_gpu(fn):
    return spaces.GPU(duration=_compare_duration)(fn) if ON_ZERO_GPU else fn


@_compare_on_gpu
def gpu_compare(volume, scan, models, centres, steps, labels=None, sample=None):
    """Every chosen model, every window, both depth orders: one GPU call, so no map runs without its control."""
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return compare.run(volume, scan, models, labels=labels, centres=centres, steps=steps, loaded=COMPARE_LOADED,
                       device=device, say=log, sample=sample)


def _models_arg(models):
    names = [m.strip() for m in (models if isinstance(models, (list, tuple)) else str(models).split(",")) if m.strip()]
    if not names:
        raise LensError("choose at least one model (list_models names them)")
    bad = [n for n in names if n not in zoo.models()]
    if bad:
        raise LensError(f"unknown models {bad}; list_models names them")
    live = [n for n in names if zoo.get(n)["family"] != "ct3d"]
    if not live:
        raise LensError("the scan-space 3D models need minutes of GPU per sample and do not run live; "
                        "tools/gallery_job.py runs them on a GPU")
    return live


def _ints(text, default):
    try:
        vals = [int(v) for v in str(text).replace(",", " ").split()] if str(text).strip() else list(default)
    except ValueError:
        raise LensError(f"{text!r}: give whole numbers separated by spaces") from None
    if not vals or len(vals) > 5:
        raise LensError("give one to five values")
    return vals


def compare_volume(volume, scan, models, centres, steps, sample=None, labels=None):
    scan = str(scan)
    if scan not in compare.SCANS:
        raise LensError("scan is 2.4 (the about 2.4 um scan) or native (about 9.4 um)")
    if volume.ndim != 3 or volume.dtype.name != "uint8":
        raise LensError("a region is uint8, layers x rows x columns")
    k = 4 if scan == "2.4" else 1
    if max(volume.shape[1:]) // k > COMPARE_MAX_SIDE or min(volume.shape[1:]) // k < 128:
        raise LensError(f"a region is 128 to {COMPARE_MAX_SIDE} px a side on the 9.6 um grid "
                        f"({128 * k} to {COMPARE_MAX_SIDE * k} px of this scan)")
    models = _models_arg(models)
    with COMPARE_LOCK:        # weights load once, on the CPU, outside the GPU call
        for n in models:
            if n not in COMPARE_LOADED:
                try:
                    import runners
                    COMPARE_LOADED[n] = runners.load(n, device="cpu")
                except Exception as exc:  # noqa: BLE001  (run() reports the model's error in its row)
                    log(f"{n} failed to load: {exc}")
    requested = _compare_duration(volume, scan, models, centres, steps)
    result, maps, _ = gpu_compare(volume, scan, models, centres, steps, labels=labels, sample=sample)
    result["gpu_seconds_requested"] = requested
    import numpy as np
    order = [n for n in models if (n, "c+0_s1", "forward") in maps] + (["ensemble"] if result.get("ensemble") else [])
    cols = sorted({(kk, o) for (n, kk, o) in maps if n in order and kk.startswith("c")},
                  key=lambda t: (t[1] != "forward", int(t[0].split("_s")[1]), int(t[0][1:].split("_")[0])))
    mos = compare.mosaic(maps, order, cols, labels=labels)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"inklens-compare-{int(time.time() * 1000)}.npz"
    np.savez_compressed(path, **{"|".join(kk): np.asarray(v, np.float16) for kk, v in maps.items()})
    result["mosaic"] = {"rows": order, "columns": [f"{kk} {o}" for kk, o in cols]}
    return api_json(result), str(path), mos


def compare_sample(sample_id="0841-w00", models="ink_9um-s42,reader-v2,reader-v3,hecate-9.6", size=384, scan="2.4",
                   centres="0", steps="1"):
    """Several ink models on one public sample, side by side: same pixels, same labels, each with its own control.

    sample_id: a public sample (list_samples). models: comma-separated names from list_models (the scan-space 3D
    models are in the gallery endpoint). size: 128 to 512 px of the 9.6 um grid around the sample's crop centre.
    scan: 2.4 (default; every model reads the about 2.4 um scan at its own scale: 9 um models pooled 4x) or native
    (the 9.4 um scan, 9 um models only). centres, steps: depth windows (9.6 um layers from the middle; spacing).
    Returns the record (per model: AUC, control AUC, gap, 95 % interval, liveness, training exposure; the ensemble;
    stability), an .npz of every map, and a mosaic (rows: models; columns: windows, as stored then reversed; labelled
    ink outlined). Model output, not a reading."""
    s = inklens.sample_by(str(sample_id))
    centres, steps = _ints(centres, (0,)), _ints(steps, (1,))
    size = max(128, min(COMPARE_MAX_SIDE, int(size or 384)))
    vol, lab, info = compare.sample_inputs(s, str(scan), size=size)
    meta = {"id": s["id"], "scroll": s["scroll"], "segment": s["segment"], "box": info["box"], "grid": info["grid"]}
    return compare_volume(vol, scan, models, centres, steps, sample=meta, labels=lab)


def compare_region(volume_npz, models="ink_9um-s42,reader-v2,hecate-9.6", scan="2.4", centres="0", steps="1"):
    """Several ink models on your own region, side by side, each with its own control (no labels, so no AUC).

    volume_npz: an .npz with one array 'volume' (uint8, layers x rows x columns): scan 2.4 for an about 2.4 um
    surface volume (at least 64 layers for Hecate 2.4 and canonical; 512 to 2048 px a side), native for about 9.4
    um (28 or more layers; 128 to 512 px). Returns the record, an .npz of every map, and a mosaic."""
    if not volume_npz:
        raise LensError("upload an .npz first")
    path = volume_npz if isinstance(volume_npz, str) else volume_npz.get("path")
    return compare_volume(read_npz(path), scan, models, _ints(centres, (0,)), _ints(steps, (1,)))


def api_json(obj):
    """A record as the API returns it: every dict key "path" (a weight file inside its repo) becomes "file", because
    gradio_client takes any JSON dict holding "path" for a file to download and fails on it."""
    if isinstance(obj, dict):
        return {("file" if k == "path" else k): api_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [api_json(v) for v in obj]
    return obj


def list_models():
    """Every ink model Ink Lens compares: family, scale, depth, licence, pinned weights, the control each is judged
    against, and on which public scroll its training saw labels (with the source)."""
    return api_json({"models": zoo.listing(), "ink_sdk": f"{zoo.INK_SDK_REPO} @ {zoo.INK_SDK_COMMIT}",
            "gallery": sorted(json.loads((GALLERY / "index.json").read_text())["samples"])
            if (GALLERY / "index.json").is_file() else []})


def gallery(sample_id="0841-w00"):
    """The precomputed comparison of every model, the scan-space 3D models included, on a sample's whole 640 px crop:
    the record (scores, intervals, liveness, exposure, depth profiles, orientation check) and the mosaic."""
    idx = GALLERY / "index.json"
    if not idx.is_file():
        raise LensError("the gallery has not been published yet")
    entry = json.loads(idx.read_text())["samples"].get(str(sample_id))
    if entry is None:
        raise LensError(f"no gallery for {sample_id}")
    import numpy as np
    from PIL import Image
    rec = json.loads((GALLERY / entry["record"]).read_text())
    return api_json(rec), np.asarray(Image.open(GALLERY / entry["mosaic"]).convert("RGB"))


def compare_md(result):
    lines = [compare.table(result), ""]
    e = result.get("ensemble")
    if e:
        lines.append(f"Ensemble: {', '.join(e['members'])} (ink-sdk's z-score recipe).")
    st = result.get("stability") or {}
    if st.get("0.5"):
        lines.append(f"Stability: on average {st['0.5']['mean_share']:.0%} of the {st['0.5']['cells']} alive cells "
                     "put a pixel at or above 0.5.")
    lines += ["", f"Mosaic rows: {', '.join(result.get('mosaic', {}).get('rows', []))}; columns: "
              f"{', '.join(result.get('mosaic', {}).get('columns', []))}. Labelled ink is outlined in amber.",
              "", f"*{compare.NOTE}*"]
    return "\n".join(lines)


# ---------------------------------------------------------------- inputs

def read_npz(path):
    """The 'volume' array of an uploaded .npz, refused before decompression when it is too big or not plain."""
    import numpy as np
    p = Path(path)
    try:
        if p.stat().st_size > MAX_UPLOAD_BYTES:
            raise LensError(f"the upload is {p.stat().st_size / 2 ** 20:.1f} MB; the limit is "
                            f"{MAX_UPLOAD_BYTES >> 20} MB")
        if p.suffix.lower() != ".npz":
            raise LensError("upload an .npz with one array named 'volume' (uint8, layers x rows x columns)")
        with zipfile.ZipFile(p) as zf:
            infos = {i.filename: i for i in zf.infolist()}
            if "volume.npy" not in infos:
                raise LensError(f"the .npz holds {sorted(infos)}; it needs volume")
            if infos["volume.npy"].file_size > MAX_VOXELS + 4096:
                raise LensError("the volume is larger than a region may be (2048 x 2048 px, 65 layers)")
        with np.load(p, allow_pickle=False) as z:
            vol = z["volume"]
    except (zipfile.BadZipFile, ValueError, OSError) as exc:
        if isinstance(exc, LensError):
            raise
        raise LensError(f"not a readable .npz: {exc}") from None
    finally:
        try:
            p.unlink()
        except OSError:
            pass
    return volio.to_uint8(vol)


def preview(volume, kept_u8):
    """The region's middle CT layer in gray with kept ink in amber, as an RGB array for the page."""
    import numpy as np
    ct = inklens.ct_middle(volume).astype(np.float32)
    lo, hi = np.percentile(ct, [1, 99]) if ct.size else (0, 1)
    g = np.clip((ct - lo) / max(hi - lo, 1e-6), 0, 1)
    rgb = np.stack([g, g, g], -1)
    a = (kept_u8.astype(np.float32) / 255.0)[..., None] * 0.85
    rgb = rgb * (1 - a) + np.array([1.0, 0.62, 0.1]) * a
    return (rgb * 255).astype(np.uint8)


def lens_volume(volume, reader, windows, sample=None, box=None):
    engine.check_volume(volume, int(windows))
    reader, windows = str(reader), int(windows)
    requested = _duration(volume, reader, windows)
    run, note = run_engine(volume, reader, windows)
    decision, kept, _ = inklens.analyze(run["forward"], run["reverse"], volume)
    result = {"tool": f"Ink Lens {engine.VERSION}", "gate": decision, "readers": run["readers"],
              "windows": windows, "patches": run["patches"], "device": run["device"],
              "device_name": run["device_name"], "seconds": run["seconds"], "gpu_seconds_requested": requested,
              "window_layers": run["window_layers"], "stack_start": run.get("stack_start"),
              "shape": [int(v) for v in volume.shape], "engine": ENGINE.describe(), "note": inklens.NOTE}
    if note:
        result["fallback"] = note
    if len(run["readers"]) > 1:
        result["per_reader"] = {n: gate.decide(m["forward"], m["reverse"], inklens.ct_middle(volume))
                                for n, m in run["per_reader"].items()}
    if sample is not None:
        result["sample"] = {"id": sample["id"], "role": sample["role"], "box": list(box)}
        try:
            ink, sup = inklens.labels_for(sample, box, run["forward"].shape)
            from kit import auc
            result["labels"] = {"shares": gate.label_shares(kept, ink, sup),
                                "auc_forward": auc.score_array(run["forward"], ink, sup, inner=64)["auc"],
                                "auc_reverse": auc.score_array(run["reverse"], ink, sup, inner=64)["auc"]}
        except Exception as exc:  # noqa: BLE001  (scoring is a bonus; the map stands without it)
            result["labels"] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    import numpy as np
    OUT.mkdir(parents=True, exist_ok=True)
    maps = OUT / f"inklens-{int(time.time() * 1000)}.npz"
    np.savez_compressed(maps, forward=run["forward"], reverse=run["reverse"], kept=gate.to_u8(kept))
    return result, str(maps), preview(volume, gate.to_u8(kept))


def summary_md(result):
    g = result["gate"]
    lines = [f"**Status: {g['status']}.** {g['status_text']}.", ""]
    if g.get("excess") is not None:
        lines.append(f"Excess {g['excess']:.2f} (3 or more is ink, 1.5 to 3 weak); threshold T = {g['threshold']:.4f}, "
                     f"the 99th percentile of the reversed map on {g['papyrus_px']:,} papyrus pixels.")
    if result.get("labels", {}).get("shares"):
        s = result["labels"]["shares"]
        lines += ["", f"Labels: kept ink covers {s['ink_kept_share']:.1%} of labeled ink pixels and "
                      f"{s['background_kept_share']:.1%} of labeled background. Raw AUC {result['labels']['auc_forward']}"
                      f", reversed control {result['labels']['auc_reverse']}."]
    lines += ["", f"{result['patches']} patches on {result['device_name']} in {result['seconds']} s "
                  f"(asked ZeroGPU for {result['gpu_seconds_requested']} s).", "", "*Model output, not a reading.*"]
    if result.get("fallback"):
        lines.insert(0, f"> {result['fallback']}\n")
    return "\n".join(lines)


# ---------------------------------------------------------------- API and MCP tools

def lens_region(volume_npz, reader="d9v2", windows=3):
    """Ink map of your own region with its reverse-depth control and a status that can fail.

    volume_npz: an .npz with one array 'volume' (uint8, layers x rows x columns, about 9.6 um per pixel, 21 to 65
    layers centered on the papyrus surface, 128 to 2048 px a side). reader: d9v2 (default), ink_9um or both.
    windows: 3 (default; three depth windows averaged) or 1. Returns the result (status ink, weak, none, too_small
    or unreadable; excess; threshold), an .npz of the float maps (forward, reverse) and the kept map (uint8), and a
    preview. Model output, not a reading."""
    if not volume_npz:
        raise LensError("upload an .npz first")
    path = volume_npz if isinstance(volume_npz, str) else volume_npz.get("path")
    return lens_volume(read_npz(path), reader, windows)


def lens_sample(sample_id="0841-w00", size=640, reader="d9v2", windows=3):
    """Ink Lens on a public sample crop (PHerc0841 or PHerc0139, not prize-eligible), read from the open-data
    bucket, with the kept ink scored against the published labels. size: 128 up to the sample's 640 px crop."""
    s = inklens.sample_by(str(sample_id))
    box = inklens.sample_box(s, int(size) if size else None)
    volume, _ = inklens.read_sample(s, box)
    return lens_volume(volume, reader, windows, sample=s, box=box)


def list_samples():
    """The public samples Ink Lens can run on, with their crops and what each one is to the readers."""
    return {"samples": [{k: s[k] for k in ("id", "title", "role", "crop", "surface_shape")}
                        for s in inklens.load_samples()["samples"]],
            "readers": {n: {k: r[k] for k in ("title", "license", "source", "held_out")}
                        for n, r in engine.READERS.items()}}


def estimate(height=1024, width=1024, windows=3, reader="d9v2"):
    """Patches and the ZeroGPU seconds one call on a height x width region (9.6 um pixels) asks for."""
    return engine.estimate(int(height), int(width), int(windows), str(reader))


INTRO = """# Ink Lens

Pick a region of a segment and get an ink map **with its own control**. One ZeroGPU call runs an openly licensed
9 um ink model ([d9v2](https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search), MIT, or the Vesuvius
Challenge's [`ink_9um`](https://huggingface.co/scrollprize/ink_9um), MIT) over three depth windows, with the layers as
stored and reversed. The reversed map sets the threshold: only ink stronger than 99 % of what the control produces is
kept, and the region gets a status that can fail (`none`: no ink above the control).

The client (`inklens.py`, from [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls/tree/main/spaces/ink-lens))
renders the region from your VC3D segment, calls this Space with your own Hugging Face token (your ZeroGPU quota
pays, about 10 s for a 1 cm region) and writes the result back as VC3D's own files: an overlay in the Ink Detection
panel, and letter-candidate pins as a point collection.

**Everything shown is model output, not a reading.**
"""

AGENTS = """```python
from gradio_client import Client, handle_file
c = Client("SharpMeow/ink-lens", hf_token=YOUR_TOKEN)        # your token: your own ZeroGPU quota
result, maps, preview = c.predict(handle_file("region.npz"), "d9v2", 3, api_name="/lens_region")
result["gate"]["status"]    # ink | weak | none | too_small | unreadable
```
Compare models: `c.predict("0841-w00", "ink_9um-s42,reader-v3,hecate-9.6", 384, "2.4", "0", "1",
api_name="/compare_sample")` returns the record, every map and a mosaic; `/compare_region` takes your own .npz,
`/list_models` names every model with its training exposure.
Also `/lens_sample`, `/list_samples`, `/estimate`; every endpoint is an MCP tool at `/gradio_api/mcp/sse`."""

COMPARE_INTRO = """Every released ink model on **the same pixels, scored against the same labels**. Each sample is read
from its about 2.4 um scan, and each model reads it at its own scale (9 um models pooled 4x, as villa prepares their
training data; Hecate 2.4 and canonical 2 um natively, their maps pooled onto the 9.6 um grid the labels use). Every
map comes with its own control (the same layers reversed), passes ink-sdk's liveness check, and its row says whether
the model's training saw labels from this scroll: a score there shows the pipeline runs, not that it generalises.
Choose several depth windows to get a sweep, a stability share and a z-score ensemble. Model output, not a reading."""

GALLERY_INTRO = """Precomputed on a GPU Job: every model on each sample's whole 640 px crop, with depth sweeps, Hecate's
depth profiles, ink-sdk's label-free orientation check, and the two scan-space 3D models (the team's Paris 4 3D
model and the DINO-guided 3D model), which read the CT around the sheet and are projected onto the same mesh pixels,
judged against the sheet moved two pitches out and in."""


def build_demo():
    import gradio as gr

    def guard(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (LensError, inklens.Refused, engine.EngineError, gate.GateError, volio.VolumeError) as exc:
                raise gr.Error(str(exc)) from None
            except gr.Error:
                raise
            except Exception as exc:  # noqa: BLE001
                import traceback
                log(f"{fn.__name__} failed: {traceback.format_exc()}")
                raise gr.Error(f"{type(exc).__name__}: {str(exc)[:300]}") from None
        return wrapped

    def page_sample(sid, size, reader, windows):
        result, maps, img = guard(lens_sample)(sid, size, reader, windows)
        return summary_md(result), result, maps, img

    def page_upload(f, reader, windows):
        result, maps, img = guard(lens_region)(f, reader, windows)
        return summary_md(result), result, maps, img

    def page_compare(sid, models, size, scan, centres, steps):
        result, maps, img = guard(compare_sample)(sid, ",".join(models or []), size, scan, centres, steps)
        return compare_md(result), result, maps, img

    def page_gallery(sid):
        result, img = guard(gallery)(sid)
        return result.get("table", ""), result, img

    samples = [(s["title"], s["id"]) for s in inklens.load_samples()["samples"]]
    live_models = [(f"{zoo.get(n)['title']} ({n})", n) for n in zoo.models() if zoo.get(n)["family"] != "ct3d"]
    with gr.Blocks(title="Ink Lens") as demo:
        gr.Markdown(INTRO)
        with gr.Tab("Compare models"):
            gr.Markdown(COMPARE_INTRO)
            with gr.Row():
                with gr.Column(scale=2, min_width=300):
                    c_sid = gr.Dropdown(samples, value=samples[0][1], label="Sample")
                    c_models = gr.CheckboxGroup(live_models, value=["ink_9um-s42", "reader-v2", "reader-v3",
                                                                    "hecate-9.6"], label="Models")
                    c_size = gr.Slider(128, COMPARE_MAX_SIDE, value=384, step=64,
                                       label="Region side (px on the 9.6 um grid)")
                    c_scan = gr.Radio([("2.4 um scan (every model)", "2.4"), ("9.4 um scan (9 um models)", "native")],
                                      value="2.4", label="Scan")
                    with gr.Row():
                        c_centres = gr.Textbox("0", label="Window centres (layers from the middle)")
                        c_steps = gr.Textbox("1", label="Layer steps")
                    run_c = gr.Button("Compare", variant="primary")
                with gr.Column(scale=3, min_width=320):
                    c_img = gr.Image(label="Mosaic: rows are models, columns are depth windows", type="numpy",
                                     format="png")
                    c_md = gr.Markdown("Choose models, then compare.")
                    c_res = gr.JSON(label="Run record")
                    c_maps = gr.File(label="Every map (.npz, 9.6 um grid)")
            run_c.click(page_compare, [c_sid, c_models, c_size, c_scan, c_centres, c_steps],
                        [c_md, c_res, c_maps, c_img], api_visibility="private", concurrency_id="gpu",
                        concurrency_limit=2)
        with gr.Tab("Gallery: every model, 3D included", visible=HAS_GALLERY):
            gr.Markdown(GALLERY_INTRO)
            g_sid = gr.Dropdown(samples, value=samples[0][1], label="Sample")
            g_btn = gr.Button("Show")
            g_img = gr.Image(label="Every model on the whole crop", type="numpy", format="png")
            g_md = gr.Markdown()
            g_res = gr.JSON(label="Record")
            g_btn.click(page_gallery, [g_sid], [g_md, g_res, g_img], api_visibility="private")
        with gr.Tab("One model, gated"), gr.Row():
            with gr.Column(scale=2, min_width=300):
                with gr.Tab("Public sample"):
                    sid = gr.Dropdown(samples, value=samples[0][1], label="Sample")
                    size = gr.Slider(128, 640, value=640, step=64, label="Region side (px at 9.4 um)")
                    run_s = gr.Button("Run Ink Lens", variant="primary")
                with gr.Tab("Your region (.npz)"):
                    up = gr.File(label="region.npz (array 'volume', uint8, layers first)", file_types=[".npz"],
                                 type="filepath")
                    run_u = gr.Button("Run Ink Lens", variant="primary")
                reader = gr.Radio(list(engine.READER_CHOICES), value="d9v2", label="Reader")
                windows = gr.Radio([3, 1], value=3, label="Depth windows")
                with gr.Accordion("For agents and scripts", open=False):
                    gr.Markdown(AGENTS)
                with gr.Accordion("Connect your tool", open=False):
                    # The data's URLs and ready snippets, made by python -m kit spaceconnect render from connect.json
                    gr.HTML((HERE / "connect.html").read_text() if (HERE / "connect.html").exists() else "")
            with gr.Column(scale=3, min_width=320):
                img = gr.Image(label="Middle CT layer, kept ink in amber", type="numpy", format="png")
                md = gr.Markdown("Choose a sample or upload a region, then run.")
                res = gr.JSON(label="Result")
                maps = gr.File(label="Maps (.npz: forward, reverse, kept)")
        outs = [md, res, maps, img]
        run_s.click(page_sample, [sid, size, reader, windows], outs, api_visibility="private",
                    concurrency_id="gpu", concurrency_limit=2)
        run_u.click(page_upload, [up, reader, windows], outs, api_visibility="private", concurrency_id="gpu",
                    concurrency_limit=2)
        with gr.Row(visible=False):
            a_file = gr.File(type="filepath", file_types=[".npz"], label="volume_npz")
            a_reader, a_windows = gr.Textbox("d9v2", label="reader"), gr.Number(3, precision=0, label="windows")
            a_sid, a_size = gr.Textbox("0841-w00", label="sample_id"), gr.Number(640, precision=0, label="size")
            a_h, a_w = gr.Number(1024, precision=0, label="height"), gr.Number(1024, precision=0, label="width")
            a_json, a_maps, a_img, a_info = gr.JSON(), gr.File(), gr.Image(type="numpy", format="png"), gr.JSON()
            a_models = gr.Textbox("ink_9um-s42,reader-v2,hecate-9.6", label="models")
            a_scan = gr.Textbox("2.4", label="scan")
            a_centres, a_steps = gr.Textbox("0", label="centres"), gr.Textbox("1", label="steps")
            a_csize = gr.Number(384, precision=0, label="size")
            btns = [gr.Button() for _ in range(8)]
        for btn, fn, ins, o, conc in (
                (btns[0], lens_region, [a_file, a_reader, a_windows], [a_json, a_maps, a_img], "gpu"),
                (btns[1], lens_sample, [a_sid, a_size, a_reader, a_windows], [a_json, a_maps, a_img], "gpu"),
                (btns[2], list_samples, [], a_info, None),
                (btns[3], estimate, [a_h, a_w, a_windows, a_reader], a_info, None),
                (btns[4], compare_sample, [a_sid, a_models, a_csize, a_scan, a_centres, a_steps],
                 [a_json, a_maps, a_img], "gpu"),
                (btns[5], compare_region, [a_file, a_models, a_scan, a_centres, a_steps], [a_json, a_maps, a_img],
                 "gpu"),
                (btns[6], list_models, [], a_info, None)) + (
                ((btns[7], gallery, [a_sid], [a_json, a_img], None),) if HAS_GALLERY else ()):
            btn.click(guard(fn), ins, o, api_name=fn.__name__, api_description=fn.__doc__.split("\n\n")[0],
                      concurrency_id=conc, concurrency_limit=2 if conc else 8)
        gr.HTML('<footer style="opacity:.7;font-size:.85em">Built by Chase Hendrick · models by the Vesuvius Challenge, '
                'TAUIL-Abd-Elilah, Domenico Russo and others (each credited in its row) · comparison features after '
                '<a href="https://github.com/LimeGS/ink-sdk">ink-sdk</a> (MIT) · data by the Vesuvius Challenge '
                f'(CC BY-NC 4.0) · Ink Lens {engine.VERSION}</footer>')
    return demo


if __name__ == "__main__":
    startup()
    build_demo().queue(max_size=128, default_concurrency_limit=4).launch(
        mcp_server=True, max_file_size=f"{MAX_UPLOAD_BYTES >> 20}mb", allowed_paths=[str(OUT)])
