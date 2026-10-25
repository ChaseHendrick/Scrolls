"""AutoPipeline's ink step as a Hugging Face Space (Gradio).

A visitor picks a public sample crop of a released segment, or uploads a small surface volume, and gets two ink
maps from Reader V3 (Domenico Russo's community ink model, an ink_9um-format checkpoint named in samples.json): the
layers in their stored order, and the same layers reversed (the control). Where the crop has published ink labels,
both maps get a pixel AUC. An ink map is model output, not a reading.

The inference is villa's own flat ink inference (vesuvius.ink_detection.inference.infer, at the commit pinned in
samples.json), called in this process: villa's configure_model loads the checkpoint, and villa's
FlatPatchReader, FlatBlockDataset, iter_blocks, run_block_inference, ChunkAccumulator and iter_probability_tiles
make each map, as villa's command line does with `--direction both` on a zarr of the same crop. The one change is
where the voxels come from: an array in memory, not a zarr path. AutoPipeline's ink step (scripts/vc3d/ink.py)
runs the same villa code as a separate process; here it runs in process, because the Space attaches the GPU
only to the decorated function `infer_pair`. Everything else runs on the CPU.

Locally: `python3 app.py` serves the page; `python3 app.py --sample 0841-w00 --size 256` runs one crop on this
machine and prints the receipt. VILLA_SRC names a local villa vesuvius/src instead of the pinned download;
INK_CACHE is where downloads are kept (default ~/.cache/autopipeline-ink, or under XDG_CACHE_HOME; it must belong to
you and be writable by no one else, since villa's code is imported from it); INK_CHECKPOINT names a local copy of
the checkpoint (its SHA-256 is still checked). The checkpoint is read once, its SHA-256 checked on those bytes, and
the same bytes loaded with torch's weights-only unpickler (villa's own loader would run any pickle code in a file).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

try:
    import spaces  # first, before torch: on the Space it attaches the GPU to spaces.GPU functions
except ImportError:
    spaces = None

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import inkspace  # noqa: E402

ROOT = inkspace.on_path()
CATALOG = inkspace.load_samples()
CHECKPOINT = CATALOG["checkpoint"]
VILLA_COMMIT = CATALOG["villa_commit"]
VILLA_REPO = "https://github.com/ScrollPrize/villa.git"
VILLA_TARBALL = "https://codeload.github.com/ScrollPrize/villa/tar.gz/{commit}"
CACHE = Path(os.environ.get("INK_CACHE") or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
             / "autopipeline-ink")
BATCH = 4
ENGINE = None
# Gradio refuses a bigger upload while it streams in, before the whole file is on disk.
LAUNCH = {"max_file_size": inkspace.MAX_UPLOAD_BYTES}


def log(message):
    print(f"[ink {time.strftime('%H:%M:%S')}] {message}", flush=True)


# ---------------------------------------------------------------- villa and the checkpoint

def private_cache(cache=CACHE):
    """The cache folder, created 0700 when missing, and refused unless it is a real folder of this user that no one
    else can write: villa's code is imported from it and the checkpoint read from it, so another local user who
    could write there (a shared /tmp, say) could run code as you."""
    cache = Path(cache)
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = os.lstat(cache)
    if not stat.S_ISDIR(st.st_mode):
        raise RuntimeError(f"the ink cache {cache} is not a folder (a link?); set INK_CACHE to a folder of yours")
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise RuntimeError(f"the ink cache {cache} belongs to uid {st.st_uid}, not you ({os.getuid()}); "
                           "set INK_CACHE to a folder of yours")
    if st.st_mode & 0o022:
        raise RuntimeError(f"the ink cache {cache} is writable by others (mode {stat.S_IMODE(st.st_mode):o}); "
                           f"run chmod go-w on it or set INK_CACHE to a private folder")
    return cache


def _git_commit(path):
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _fetch_villa(dest, commit=VILLA_COMMIT):
    """villa's vesuvius/src at one commit: a sparse, blobless git fetch of that commit, else GitHub's tarball."""
    tmp = dest.with_name(dest.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        git = ["git", "-C", str(tmp)]
        for cmd in (["init", "-q"], ["remote", "add", "origin", VILLA_REPO], ["sparse-checkout", "set", "vesuvius/src"],
                    ["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", commit],
                    ["checkout", "-q", "FETCH_HEAD"]):
            subprocess.run(git + cmd, capture_output=True, text=True, check=True, timeout=600)
        if _git_commit(tmp) != commit:
            raise RuntimeError(f"git fetched {_git_commit(tmp)}, not {commit}")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        log(f"git fetch of villa failed ({getattr(exc, 'stderr', None) or exc}); trying the tarball")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        _villa_tarball(tmp, commit)
    (tmp / "COMMIT").write_text(commit + "\n")
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)


def _villa_tarball(tmp, commit):
    """Stream GitHub's tarball of the commit and keep only vesuvius/src."""
    root = tmp.resolve()
    kept = 0
    req = urllib.request.Request(VILLA_TARBALL.format(commit=commit), headers={"User-Agent": "autopipeline-ink"})
    with urllib.request.urlopen(req, timeout=600) as resp, tarfile.open(fileobj=resp, mode="r|gz") as tf:
        for m in tf:
            top, _, rel = m.name.partition("/")
            if not top.endswith(commit[:7]) and commit not in top:
                raise RuntimeError(f"the villa tarball for {commit} holds {top!r}")
            if not rel.startswith("vesuvius/src/"):
                continue
            target = (root / rel).resolve()
            if root not in target.parents or m.issym() or m.islnk():
                continue
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(m) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                kept += 1
    if not kept:
        raise RuntimeError(f"the villa tarball for {commit} held no vesuvius/src files")


def ensure_villa(cache=CACHE):
    """Put villa's vesuvius on sys.path: VILLA_SRC when set, else the pinned commit, downloaded once."""
    if os.environ.get("VILLA_SRC"):
        src, how = Path(os.environ["VILLA_SRC"]).expanduser().resolve(), "VILLA_SRC"
        commit = _git_commit(src)
    else:
        dest = private_cache(cache) / f"villa-{VILLA_COMMIT[:12]}"
        if not (dest / "COMMIT").is_file():
            log(f"fetching villa {VILLA_COMMIT[:12]}")
            _fetch_villa(dest)
        src, how, commit = dest / "vesuvius" / "src", "pinned download", (dest / "COMMIT").read_text().strip()
    if not (src / "vesuvius" / "ink_detection" / "inference" / "infer.py").is_file():
        raise RuntimeError(f"{src} holds no villa vesuvius package")
    if commit != VILLA_COMMIT:
        log(f"warning: villa at {src} is {commit}, not the pinned {VILLA_COMMIT}")
    if str(src) not in sys.path:
        sys.path.append(str(src))   # last: villa's folder must not shadow torch or another installed package
    return {"source": how, "commit": commit, "pinned": VILLA_COMMIT, "src": str(src)}


def ensure_checkpoint(cache=CACHE):
    """The checkpoint's path (samples.json names it), its SHA-256 and its bytes: downloaded once, read once, and refused unless the
    SHA-256 of the bytes read matches samples.json (and, where the repository's readers.tsv is present, that file
    too). The caller loads these bytes, never the file again, so the file cannot change between check and load."""
    row = inkspace.readers_row(CHECKPOINT["name"], ROOT)
    if row is not None and (row["sha256"], row["url"]) != (CHECKPOINT["sha256"], CHECKPOINT["url"]):
        raise RuntimeError(f"samples.json and readers.tsv disagree about {CHECKPOINT['name']}")
    if os.environ.get("INK_CHECKPOINT"):
        path = Path(os.environ["INK_CHECKPOINT"]).expanduser()
    else:
        path = private_cache(cache) / CHECKPOINT["name"] / CHECKPOINT["file"]
        if not path.is_file():
            log(f"downloading {CHECKPOINT['url']}")
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_name(path.name + ".part")
            req = urllib.request.Request(CHECKPOINT["url"], headers={"User-Agent": "autopipeline-ink"})
            with urllib.request.urlopen(req, timeout=600) as resp, open(part, "wb") as out:
                shutil.copyfileobj(resp, out, 1 << 20)
            os.replace(part, path)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != CHECKPOINT["sha256"]:
        raise RuntimeError(f"{path} has SHA-256 {digest}, expected {CHECKPOINT['sha256']}; refusing it")
    return path, digest, data


def checked_loader(torch, path, data):
    """A stand-in for villa's load_checkpoint that returns the checked bytes, unpickled weights-only, for the
    checkpoint and refuses to load any other file."""
    def load_checkpoint(asked, *args, **kwargs):
        if Path(str(asked)).expanduser().resolve() != Path(path).expanduser().resolve():
            raise RuntimeError(f"villa asked to load {asked}, not the checked checkpoint {path}")
        return torch.load(io.BytesIO(data), map_location="cpu", weights_only=True)
    return load_checkpoint


def use_checked_loader(loader):
    """Put loader in place of villa's load_checkpoint in every villa module that holds it."""
    from vesuvius.ink_detection.models import checkpoint
    unsafe = checkpoint.load_checkpoint
    for name, mod in list(sys.modules.items()):
        if name.split(".")[0] == "vesuvius" and getattr(mod, "load_checkpoint", None) is unsafe:
            mod.load_checkpoint = loader
    checkpoint.load_checkpoint = loader


class Engine:
    """The checkpoint in villa's flat inference, loaded once at start."""

    def __init__(self, cache=CACHE):
        t0 = time.time()
        self.villa = ensure_villa(cache)
        self.checkpoint, self.sha256, data = ensure_checkpoint(cache)
        import torch
        from vesuvius.ink_detection.inference import infer
        src = Path(self.villa.pop("src")).resolve()
        if src not in Path(infer.__file__).resolve().parents:
            raise RuntimeError(f"vesuvius was imported from {infer.__file__}, not from villa at {src}: another "
                               "vesuvius is installed in this Python; uninstall it or set VILLA_SRC to it")
        use_checked_loader(checked_loader(torch, self.checkpoint, data))
        self.torch, self.infer = torch, infer
        self.cm = infer.configure_model(argparse.Namespace(checkpoint=self.checkpoint, amp_dtype="auto"))
        del data
        got = (int(self.cm.patch_size), int(self.cm.input_depth))
        if got != (inkspace.PATCH, inkspace.INPUT_DEPTH):
            raise RuntimeError(f"checkpoint has patch and depth {got}, the Space is sized for "
                               f"{(inkspace.PATCH, inkspace.INPUT_DEPTH)}")
        self.model = self.cm.model.eval()
        if torch.cuda.is_available():
            self.model.to("cuda")   # on the Space, placed at start as the platform asks; real only inside a GPU call
        self.stride = infer.resolve_patch_stride(patch_size=self.cm.patch_size, overlap=0.5, explicit_stride=None)
        if self.stride != inkspace.STRIDE:
            raise RuntimeError(f"villa's stride is {self.stride}, the Space is sized for {inkspace.STRIDE}")
        self.startup_s = round(time.time() - t0, 1)

    def describe(self):
        return {"checkpoint": {k: CHECKPOINT[k] for k in ("repo", "file", "sha256", "license")},
                "villa": self.villa, "patch": int(self.cm.patch_size), "input_depth": int(self.cm.input_depth),
                "stride": int(self.stride), "blend": "hann", "preprocessing": self.cm.preprocessing,
                "amp_on_cuda": str(self.cm.amp_dtype).replace("torch.", ""), "batch": BATCH,
                "torch": self.torch.__version__}

    def run_pair(self, volume):
        """Forward and reversed uint8 maps of one (layers, height, width) array, by villa's flat inference."""
        import numpy as np
        torch, infer, cm = self.torch, self.infer, self.cm
        from torch.utils.data import DataLoader
        t0 = time.perf_counter()
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = self.model.to(device)
        depth, height, width = (int(v) for v in volume.shape)
        patch = int(cm.patch_size)
        # villa's schedule for a zarr whose only level is this crop: occupancy from the crop itself, scale 1
        occupancy = infer.compute_nonempty_mask_from_lowres_array(volume)
        blocks = infer.iter_blocks((height, width), patch, self.stride, occupancy, (1, 1))
        weight_map = infer.compute_importance_map_2d(patch_size=(patch, patch), mode="hann").numpy()
        tile = (patch, patch)
        chunk = (min(tile[0], height), min(tile[1], width))
        maps, layers = {}, {}
        for direction in ("forward", "reverse"):
            idx = infer.select_layer_indices(depth, layer_start=None, layer_end=None, output_depth=cm.input_depth,
                                             direction=direction)
            layers[direction] = [int(i) for i in idx]
            reader = infer.FlatPatchReader(input_path="memory", resolution="0", depth_axis_first=True, height=height,
                                           width=width, layer_indices=idx, output_depth=cm.input_depth,
                                           preprocessing=cm.preprocessing)
            reader._array = volume   # villa reads this array instead of opening input_path
            dataset = infer.FlatBlockDataset(reader=reader, blocks=blocks, patch_size=patch,
                                             preprocessing=cm.preprocessing)
            loader = DataLoader(dataset, batch_size=BATCH, shuffle=False, num_workers=0,
                                pin_memory=device.type == "cuda", drop_last=False)
            psum = np.zeros((height, width), np.float32)
            wsum = np.zeros((height, width), np.float32)
            acc = infer.ChunkAccumulator(shape=(height, width), chunk_shape=chunk, prob_sum_store=psum,
                                         weight_sum_store=wsum,
                                         contribution_counts=infer.compute_chunk_contribution_counts(
                                             blocks, chunk_shape=chunk))
            if blocks:
                infer.run_block_inference(loader=loader, model=model, accumulator=acc, weight_map=weight_map,
                                          mask=None, device=device, amp_dtype=cm.amp_dtype, tta_axes=(),
                                          tta_batch_size=None)
                acc.flush_remaining()
            out = np.zeros((height, width), np.uint8)
            tiles = infer.iter_probability_tiles(psum, wsum, tile)
            for y0 in range(0, height, tile[0]):
                for x0 in range(0, width, tile[1]):
                    t = next(tiles)
                    out[y0:y0 + t.shape[0], x0:x0 + t.shape[1]] = t
            maps[direction] = out
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        name = torch.cuda.get_device_name(device) if device.type == "cuda" else (platform.processor() or
                                                                                  platform.machine())
        return {"forward": maps["forward"], "reverse": maps["reverse"], "layers": layers, "patches": len(blocks),
                "device": str(device), "device_name": name, "seconds": round(time.perf_counter() - t0, 2)}


def startup(cache=CACHE):
    global ENGINE
    if ENGINE is None:
        ENGINE = Engine(cache)
        log(f"ready in {ENGINE.startup_s} s: {json.dumps(ENGINE.describe())}")
    return ENGINE


# ---------------------------------------------------------------- the one GPU call

def _gpu_seconds(volume):
    return inkspace.gpu_seconds(int(volume.shape[1]), int(volume.shape[2]))


def _on_gpu(fn):
    return fn if spaces is None else spaces.GPU(duration=_gpu_seconds)(fn)


@_on_gpu
def infer_pair(volume):
    """Both directions of one crop in one GPU call: the forward map never runs without its control."""
    return ENGINE.run_pair(volume)


# ---------------------------------------------------------------- jobs

def run_job(volume, sample=None, box=None, source=None):
    import numpy as np
    t0 = time.time()
    volume = np.ascontiguousarray(volume)
    inkspace.check_volume(volume.shape, volume.dtype)
    requested = _gpu_seconds(volume)
    if ENGINE is None:
        raise inkspace.SpaceError("the model is still loading; try again in a minute")
    result = infer_pair(volume)
    forward, reverse = inkspace.require_pair(result)
    surface = volume[volume.shape[0] // 2] > 0
    comparison = inkspace.check_maps(forward, reverse, surface, ROOT)
    scores = None
    if sample is not None:
        ink, supervised = inkspace.labels_for(sample, box, forward.shape)
        scores = inkspace.score_pair(forward, reverse, ink, supervised)
    receipt = {"model": ENGINE.describe(), "input": source or {"upload": True, "kept": False},
               "shape": [int(v) for v in volume.shape], "dtype": str(volume.dtype),
               "layers": result["layers"], "patches_per_direction": result["patches"],
               "device": result["device"], "device_name": result["device_name"],
               "gpu_seconds_requested": requested, "inference_seconds": result["seconds"],
               "total_seconds": round(time.time() - t0, 2), "forward_vs_control": comparison, "auc": scores,
               "note": "model output, not a reading"}
    out = {"forward": forward, "reverse": reverse, "ct": inkspace.display(volume[volume.shape[0] // 2]),
           "scores": scores, "sample": sample, "box": list(box) if box else None, "receipt": receipt}
    out["summary"] = inkspace.summary(out)
    return out


def run_sample(key, size=None):
    sample = inkspace.sample_by(key, CATALOG)
    box = inkspace.window(sample, size)
    volume, source = inkspace.read_crop(sample, box)
    return run_job(volume, sample, box, {"sample": sample["id"], **source})


def run_upload(path):
    if not path:
        raise inkspace.SpaceError("choose a file first")
    return run_job(inkspace.read_upload(path))


# ---------------------------------------------------------------- the page

# Component styling uses owned IDs and HTML classes. Shell gutters also account for Gradio's main wrapper.
CSS = """
.gradio-container {max-width:1540px!important; padding:0 clamp(16px,calc(100vw - 640px),32px) 28px!important; background:#f3f5f7;
    color:#182633; --body-background-fill:#f3f5f7; --body-background-fill-dark:#f3f5f7;
    --body-text-color:#182633; --body-text-color-dark:#182633; color-scheme:light;}
/* Gradio scopes selectors inside @media to .contain, so shell gutters use clamp instead. */
.gradio-container > .main {padding-inline:clamp(0px,calc(100vw - 640px),32px)!important;}
.ap-header {display:flex; align-items:center; justify-content:space-between; gap:24px;
    padding:22px 0 20px; border-bottom:1px solid #d7e0e7; margin-bottom:6px;}
.ap-brand {display:flex; align-items:center; gap:12px;}
.ap-mark {width:34px;height:34px;display:grid;place-items:center;background:#285f85;color:#fff;border-radius:5px;}
.ap-brand strong {display:block;font-size:17px;font-weight:650;letter-spacing:-.3px;}
.ap-brand small {display:block;font-size:12px;color:#637484;margin-top:2px;}
.ap-header-note {font-size:12px;color:#637484;text-align:right;}
.ap-header-note strong {display:block;font:12px ui-monospace,SFMono-Regular,Consolas,monospace;color:#334c60;}
.ap-page-heading {display:flex;align-items:end;justify-content:space-between;gap:20px;padding:20px 0 18px;}
.ap-page-heading h1 {font-size:24px;line-height:1.25;font-weight:600;letter-spacing:-.6px;margin:0 0 6px;}
.ap-page-heading p {font-size:14px;color:#637484;margin:0;line-height:1.6;}
.ap-step {font-size:12px;color:#637484;white-space:nowrap;padding-bottom:3px;}
#ap-workspace {gap:24px;align-items:flex-start;}
#ap-source {background:#fff;border:1px solid #d7e0e7;border-radius:6px;padding:20px;gap:15px;}
#ap-source-title h2 {font-size:14px;letter-spacing:0;margin:0;font-weight:650;}
#ap-source-title p {color:#637484;font-size:12px;margin-top:5px;}
#ap-source-tabs {border:0;padding:0;}
#ap-sample-tab,#ap-upload-tab {padding:16px 0 0!important;border:0!important;}
#ap-sample-note {font-size:12px;line-height:1.65;color:#637484;}
#ap-source label,#ap-source input,#ap-source textarea,#ap-source select {color:#243b4f!important;}
#ap-source input::placeholder,#ap-source textarea::placeholder {color:#637484!important;opacity:1;}
#ap-sample-run,#ap-upload-run {margin-top:5px;min-height:42px;font-size:13px;font-weight:600;}
.ap-source-meta {border-top:1px solid #e3e8ed;padding-top:16px;}
.ap-source-meta h3 {margin:0 0 12px;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#637484;}
.ap-source-meta dl {display:grid;grid-template-columns:1fr auto;gap:9px 12px;margin:0;font-size:12px;}
.ap-source-meta dt {color:#637484;}.ap-source-meta dd {margin:0;text-align:right;color:#243b4f;}
.ap-source-meta p {font-size:11px;line-height:1.65;color:#637484;margin:16px 0 0;}
#ap-analysis {gap:16px;min-width:0;}
.ap-viewer-heading {display:flex;justify-content:space-between;align-items:center;gap:12px;
    padding:1px 0 12px;border-bottom:1px solid #d7e0e7;}
.ap-viewer-heading h2 {font-size:14px;font-weight:650;margin:0;}
.ap-viewer-heading span {font:11px ui-monospace,SFMono-Regular,Consolas,monospace;color:#637484;}
.ap-figures {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;}
.ap-figure {margin:0!important;min-width:0;border:1px solid #cfd9e2;border-radius:5px;overflow:hidden;background:#fff;}
.ap-figure-head {display:flex;justify-content:space-between;align-items:center;gap:8px;padding:12px 13px;
    font-size:12px;color:#23384a;border-bottom:1px solid #d7e0e7;}
.ap-figure-head strong {font-weight:600;}.ap-figure-head span {color:#788b9b;font:10px ui-monospace,monospace;}
.ap-image-well {position:relative;aspect-ratio:1;background:#111820;display:grid;place-items:center;overflow:hidden;}
.ap-image-well img {display:block;width:100%;height:100%;object-fit:contain;margin:0!important;}
.ap-empty {text-align:center;padding:18px;color:#92a5b5;font-size:11px;line-height:1.7;}
.ap-empty svg {display:block;margin:0 auto 12px;opacity:.65;}
.ap-figure figcaption {padding:11px 13px!important;font-size:11px;line-height:1.5;color:#637484;
    min-height:51px;background:#fff;}
.ap-viewer-status {display:flex;align-items:center;gap:8px;margin:12px 0 0;font-size:12px;color:#637484;}
.ap-status-dot {width:6px;height:6px;background:#8b9dab;border-radius:50%;flex-shrink:0;}
.ap-result-status {display:flex;flex-wrap:wrap;gap:5px 18px;font-size:12px;color:#637484;padding:13px 0;}
.ap-result-status strong {font-weight:600;color:#243b4f;}
.ap-metrics {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid #d7e0e7;
    background:#fff;border-radius:5px;margin-top:15px;}
.ap-metric {padding:15px 16px;border-right:1px solid #e3e8ed;min-width:0;}
.ap-metric:last-child {border-right:0;}.ap-metric dt {font-size:11px;color:#637484;margin-bottom:7px;}
.ap-metric dd {font:23px ui-monospace,SFMono-Regular,Consolas,monospace;color:#243b4f;margin:0;letter-spacing:-.7px;}
.ap-metric dd small {font-size:12px;color:#637484;letter-spacing:0;}
.ap-result-note {font-size:12px;line-height:1.65;color:#637484;margin:10px 0 0;}
#ap-score-details,#ap-receipt,#ap-about {border:1px solid #d7e0e7;border-radius:5px;background:#fff;}
#ap-footnote {font-size:12px;line-height:1.65;color:#637484;border-top:1px solid #d7e0e7;padding-top:13px;}
#ap-footnote p {margin:0;}
.ap-credit {margin-top:24px;padding:18px 0 0;border-top:1px solid #d7e0e7;text-align:center;font-size:12px;color:#637484;}
@media(max-width:1050px) {#ap-workspace {gap:18px;}.ap-figure-head{padding:10px 9px;}.ap-figure figcaption{padding:9px!important;}}
@media(max-width:760px) {.ap-header-note,.ap-step{display:none;}.ap-page-heading{padding:18px 0;}
    #ap-source{padding:16px;flex-basis:100%;flex-grow:1!important;}.ap-figures{grid-template-columns:1fr;gap:14px;}
    .ap-image-well{max-height:420px;aspect-ratio:auto;min-height:230px;}
    .ap-image-well img{max-height:420px;object-fit:contain;}.ap-metrics{grid-template-columns:repeat(2,minmax(0,1fr));}
    .ap-metric:nth-child(2){border-right:0;}.ap-metric:nth-child(-n+2){border-bottom:1px solid #e3e8ed;}
    .ap-viewer-heading span{display:none;}}
"""


def theme():
    """Local system fonts and a restrained, high-contrast workbench palette. No font/CDN requests."""
    import gradio as gr
    return gr.themes.Base(primary_hue="blue", neutral_hue="slate", radius_size="sm",
                          font=("system-ui", "sans-serif"), font_mono=("ui-monospace", "monospace")).set(
        body_background_fill="#f3f5f7", body_background_fill_dark="#f3f5f7",
        body_text_color="#182633", body_text_color_dark="#182633",
        body_text_color_subdued="#637484", body_text_color_subdued_dark="#637484",
        background_fill_primary="#ffffff", background_fill_primary_dark="#ffffff",
        background_fill_secondary="#f3f5f7", background_fill_secondary_dark="#f3f5f7",
        border_color_primary="#d7e0e7", border_color_primary_dark="#d7e0e7",
        block_background_fill="#ffffff", block_background_fill_dark="#ffffff",
        block_border_color="#d7e0e7", block_border_color_dark="#d7e0e7",
        block_label_text_color="#334c60", block_label_text_color_dark="#334c60",
        block_title_text_color="#334c60", block_title_text_color_dark="#334c60",
        block_info_text_color="#637484", block_info_text_color_dark="#637484",
        input_background_fill="#ffffff", input_background_fill_dark="#ffffff",
        input_border_color="#c5d1dc", input_border_color_dark="#c5d1dc",
        input_placeholder_color="#637484", input_placeholder_color_dark="#637484",
        button_primary_background_fill="#285f85", button_primary_background_fill_dark="#285f85",
        button_primary_background_fill_hover="#214f70", button_primary_background_fill_hover_dark="#214f70",
        button_primary_text_color="#ffffff", button_primary_text_color_dark="#ffffff",
        button_primary_border_color="#285f85", button_primary_border_color_dark="#285f85",
        code_background_fill="#eef2f5", code_background_fill_dark="#eef2f5",
        shadow_drop="none", shadow_drop_lg="none", block_shadow="none")


def figures(ct, forward, reverse):
    """The three images of a run, side by side, as PNG data inside the page."""
    return inkspace.figures_html([("CT, middle layer", ct), ("Ink map, layers in stored order", forward),
                                  ("Control, layers reversed", reverse)])


def build_demo():
    import gradio as gr
    titles = [s["title"] for s in CATALOG["samples"]]
    notes = {s["title"]: s["note"] for s in CATALOG["samples"]}
    brief_notes = {}
    for sample in CATALOG["samples"]:
        if sample["role"] == "development":
            brief = ("Development crop. The model was not trained on PHerc0841, but its author benchmarked "
                     "PHerc0841 while choosing its recipe. This crop was selected using published labels; its "
                     "AUC is not a blind test.")
        elif sample["id"] == "0139-w045":
            brief = ("Training segment. Reader V3 was trained on this segment and on a 2.4 µm render of it. "
                     "This check is not held out.")
        else:
            brief = ("Training segment. The model was trained on this segment. A high AUC checks that the "
                     "pipeline runs; it is not an independent test.")
        brief_notes[sample["title"]] = brief

    def page(result):
        forward, reverse = inkspace.require_pair(result)
        return (figures(result["ct"], forward, reverse) + inkspace.metrics_html(result),
                result["summary"], result["receipt"])

    def on_sample(title):
        try:
            return page(run_sample(title))
        except inkspace.SpaceError as exc:
            raise gr.Error(str(exc)) from None

    def on_upload(path):
        try:
            return page(run_upload(path))
        except inkspace.SpaceError as exc:
            raise gr.Error(str(exc)) from None

    with gr.Blocks(title="AutoPipeline ink step",
                   delete_cache=(inkspace.CACHE_SWEEP_S, inkspace.UPLOAD_MAX_AGE_S)) as demo:
        gr.HTML('''<header class="ap-header"><div class="ap-brand"><span class="ap-mark" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M4 6h14M4 11h14M4 16h14M7 3v16M15 3v16"/></svg></span>
            <div><strong>AutoPipeline</strong><small>Vesuvius research tools</small></div></div>
            <div class="ap-header-note"><strong>Reader V3</strong>Community model · Paired control</div></header>
            <div class="ap-page-heading"><div><h1>Ink analysis</h1>
            <p>Inspect a surface volume alongside its ink map and reversed-layer control.</p></div>
            <span class="ap-step">Surface volume → Ink inference → Comparison</span></div>''')
        with gr.Row(elem_id="ap-workspace"):
            with gr.Column(scale=0, min_width=286, elem_id="ap-source"):
                gr.Markdown("## Source\nChoose a released crop or your own surface volume.", elem_id="ap-source-title")
                with gr.Tabs(elem_id="ap-source-tabs"):
                    with gr.Tab("Sample crop", elem_id="ap-sample-tab"):
                        choices = [(s["title"].split(" (")[0], s["title"]) for s in CATALOG["samples"]]
                        pick = gr.Dropdown(choices=choices, value=titles[0], label="Released segment",
                                           filterable=False, elem_id="ap-sample")
                        note = gr.Markdown(brief_notes[titles[0]], elem_id="ap-sample-note")
                        run_one = gr.Button("Run analysis", variant="primary", elem_id="ap-sample-run")
                    with gr.Tab("Upload", elem_id="ap-upload-tab"):
                        upload = gr.File(label="Surface volume", file_types=[".npy", ".tif", ".tiff"],
                                         type="filepath", elem_id="ap-upload")
                        gr.Markdown(f"`.npy` or multipage `.tif` · Maximum {inkspace.MAX_UPLOAD_BYTES // 2 ** 20} MB\n\n"
                                    f"{inkspace.MIN_LAYERS} to {inkspace.MAX_LAYERS} layers, layers first. "
                                    f"{inkspace.MIN_SIDE} to {inkspace.MAX_SIDE} px per side. {' or '.join(inkspace.DTYPES)}.")
                        with gr.Accordion("File handling", open=False):
                            gr.Markdown(inkspace.UPLOAD_TEXT)
                        run_up = gr.Button("Analyze upload", variant="primary", elem_id="ap-upload-run")
                gr.HTML('''<section class="ap-source-meta" aria-label="Inference settings"><h3>Run settings</h3>
                    <dl><dt>Model</dt><dd>Reader V3</dd><dt>Depth</dt><dd>Middle 17 layers</dd>
                    <dt>Directions</dt><dd>Stored + reversed</dd><dt>Sample crop</dt><dd>640 × 640 px</dd></dl>
                    <p>Sample data loads when you run. Both directions use the same model and settings.
                    GPU time counts against your Space quota.</p></section>''')
            with gr.Column(scale=1, min_width=420, elem_id="ap-analysis"):
                gr.HTML('<div class="ap-viewer-heading"><h2>Image comparison</h2>'
                        '<span>CT / STORED ORDER / REVERSED CONTROL</span></div>')
                images = gr.HTML(inkspace.empty_figures_html(), elem_id="ap-images")
                with gr.Accordion("Score details", open=False, elem_id="ap-score-details"):
                    text = gr.Markdown("Run an analysis to see scores. Uploaded volumes have no labels or AUC.")
                with gr.Accordion("Run receipt", open=False, elem_id="ap-receipt"):
                    receipt = gr.JSON(label="Model, inputs, settings and timings")
                gr.Markdown("**Model output, not a reading.** Compare the ink map with its reversed-layer control. "
                            "Brightness alone does not establish legible ink.", elem_id="ap-footnote")
                with gr.Accordion("Connect your tool", open=False, elem_id="ap-connect"):
                    # The data's URLs and ready snippets, rendered by public Scrolls' spaceconnect tool and uploaded
                    # beside the Space's files; empty when they are not there
                    gr.HTML((HERE / "connect.html").read_text() if (HERE / "connect.html").exists() else "")
                with gr.Accordion("About this workflow", open=False, elem_id="ap-about"):
                    gr.Markdown(inkspace.INTRO)
                    gr.Markdown("### Selected sample")
                    sample_detail = gr.Markdown(notes[titles[0]])
        gr.HTML('<footer class="ap-credit">Built by Chase Hendrick</footer>')
        outputs = [images, text, receipt]
        pick.change(lambda t: (brief_notes.get(t, ""), notes.get(t, "")), pick, [note, sample_detail])
        run_one.click(on_sample, pick, outputs, concurrency_id="ink-analysis", concurrency_limit=1)
        run_up.click(on_upload, upload, outputs, concurrency_id="ink-analysis", concurrency_limit=1)
    return demo


def main(argv=None):
    ap = argparse.ArgumentParser(description="AutoPipeline ink step: serve the page, or run one sample here")
    ap.add_argument("--sample", help="run this sample (id or title) once and print the receipt, without the page")
    ap.add_argument("--size", type=int, help="with --sample: a square of this many px at the crop's centre")
    ap.add_argument("--out", help="with --sample: also write the two maps here as .npy")
    a = ap.parse_args(argv)
    startup()
    if a.sample:
        res = run_sample(a.sample, a.size)
        if a.out:
            import numpy as np
            Path(a.out).mkdir(parents=True, exist_ok=True)
            np.save(Path(a.out) / "forward.npy", res["forward"])
            np.save(Path(a.out) / "reverse.npy", res["reverse"])
        print(json.dumps(res["receipt"], indent=1))
        print(res["summary"])
        return 0
    build_demo().queue(max_size=16).launch(theme=theme(), css=CSS, **LAUNCH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
