"""Live ink preview server: an ink model's output for the part of a segment a viewer has on screen.

A local HTTP server (it listens on 127.0.0.1 only) that a viewer asks for an ink model's probability map of the
window it is showing, with no whole-segment map made first. The server cuts the window into patches on the grid
a whole-segment map uses (villa's flat ink inference: 128 px patches, stride 64 from the canvas origin at the default
overlap 0.5, a last row and column flush to the edge), runs the patches through the model and blends them: per-patch
robust normalization, sigmoid, floored Hann weights, all-zero patches skipped (flat_contract.py). On the same voxels a
preview pixel is the pixel the whole map would hold, up to the arithmetic of the backend. Patch results are cached by
position, so a pan computes only the new patches.

A preview is model output, not a reading of a text. Variant r runs the same view with the layers reversed: the control
view. Where the forward view is high and the reversed view is as high, the response does not depend on depth order.

Two ways to give the server the voxels:
  stack mode  the viewer samples the layers under the view itself and uploads them;
  path mode   the server reads a surface volume from disk (a zarr, or a folder of layer TIFFs).

Backends: coreml (a Core ML package run by coreml_server.py, for the Apple Neural Engine), torchscript (a traced model
on CPU, Apple GPU or CUDA) and fake (a depth-weighted mean for tests; every reply says so and it never stands for a
model) run batches of patches that this server cuts, normalizes and blends. export_ckpt.py traces a villa ink
checkpoint; convert.py turns the trace into a Core ML package. inkrs (https://github.com/praveenperera/inkrs, MIT or
Apache 2.0) is a window backend: it runs a villa flat ink reader on the GPU (Metal or CUDA), normalizes, tiles and
blends by itself, and returns villa's uint8 map of a whole window. The server hands it windows on the canvas grid with
a margin (window_span) and caches stride by stride cells of its map, each only where the window rule says the
window's pixels equal the whole map's (exact_span).

Commands:
  python3 inkpreview.py serve --package ink9.mlpackage [--port 8765] [--cache-mb 256] [--allow SCROLLS]
  python3 inkpreview.py serve --backend torchscript --model traced.pt [--device auto]
  python3 inkpreview.py serve --backend inkrs --model EXPORT.safetensors [--device auto] [--batch-size N]
  python3 inkpreview.py snapshot --package P --segment SEG --x X --y Y --w W --h H --out view.tif
  python3 inkpreview.py check --segment SEG --allow SCROLLS     # exit 0 when the allow list lets it preview, 3 if not

HTTP, ink preview api 1:
  GET  /health   -> {"service": "ink-preview", "api": 1, "backend", "model", "patch", "stride", "depth", "voxel_um",
                     "max_view_px", "cache": {...}, "input_shape", "output_shape", "allow"}
  POST /preview?key=K&cw=CW&ch=CH&x=X&y=Y&w=W&h=H[&variant=f|r][&format=u8|f32|png][&scroll=ID]
                [&sx=SX&sy=SY&sw=SW&sh=SH&dtype=uint8|uint16   with a body of depth * SH * SW voxels,
                                                                 layers first, C order, little-endian]
       Stack mode. key names everything that decides the voxels under the canvas (the viewer changes it when the
       surface, the volume, the level or the layers change); cw, ch: canvas size; x, y, w, h: the view inside it;
       sx, sy, sw, sh: the canvas rectangle the body covers. Layers go up in forward order; the server reverses
       them for variant r. The body comes with a Content-Length, or chunked.
       200  the view: u8 (floor(255 p), one byte per pixel), f32 (little-endian float32) or png (8-bit gray),
            headers X-Shape: h,w, X-Backend, X-Tiles: computed,cached. Pixels no non-empty patch covers are 0.
            A window backend (inkrs) counts cells, not patches, in X-Tiles; its f32 is u8 / 255.
       409  {"need": {"x", "y", "w", "h"}, "depth": D, "missing": N}: the canvas rectangle to upload. A patch of
            the view is ready when it is cached or lies inside the uploaded rectangle; nothing is computed until
            every patch is ready. need bounds every patch of the view that is not cached (N of them), those this
            upload covers included, so the viewer samples "need" and posts again with the body.
       400  {"error": TEXT} bad request, 403 {"refused": TEXT} allow list, 413 {"error": TEXT} view over
            max_view_px, 500 {"error": TEXT} (the server stays up).
  POST /preview  with a JSON body and no query: path mode
       {"segment": PATH, "x": X, "y": Y, "w": W, "h": H, "scale": 1, "format": "f32"|"u8"|"png",
        "window": [FIRST, END], "variant": "f"|"r"}

Allow list: --allow takes scroll ids, comma-separated; the default "any" means no restriction. With a list, a request
must name a scroll on it: in the segment path (path mode) or in the scroll parameter (stack mode). A wrapper can add
rules of its own without editing this file: append callables to EXTRA_GUARDS; each gets the request as a dict and may
raise Refused.
"""
import argparse, collections, json, os, re, struct, subprocess, sys, threading, urllib.parse, zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _sibling(name):
    """A module from this folder, loaded by path so the folder needs no package and no sys.path entry."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


FC = _sibling("flat_contract")
SERVICE, API = "ink-preview", 1
MAX_VIEW_PX = 16 * 2 ** 20
DRAIN_BYTES = 64 * 2 ** 20  # an oversized body up to this size is read and dropped so the connection can go on
DEFAULT_ALLOW = "any"
FORMATS = ("u8", "f32", "png")

# Extra rules a wrapper adds: callables guard(request_info) that return nothing or raise Refused. request_info is
# {"mode": "path" or "stack", "segment": absolute path or None, "scroll": scroll id or None, "key": the client's
#  key or None, "query": the query parameters (stack mode) or JSON fields (path mode) as sent,
#  "allow": tuple of allowed scroll ids, or None for any}. They run before the allow list is checked.
EXTRA_GUARDS = []


class Refused(Exception):
    """The allow list or an extra guard says the request may not preview (HTTP 403, exit code 3)."""


class TooLarge(ValueError):
    """The view or the upload is over the server's size limit (HTTP 413)."""


class NeedStack(Exception):
    """Stack mode: patches of the view are neither cached nor inside the uploaded rectangle (HTTP 409)."""

    def __init__(self, need, depth, missing):
        Exception.__init__(self, "upload needed")
        self.need, self.depth, self.missing = need, depth, missing


class BackendError(RuntimeError):
    """The model backend failed on one request (HTTP 500 with this text); the server stays up."""


# ---------------------------------------------------------------- allow list

_PHERC = re.compile(r"(?i)pherc[_ ]?(\d{1,4}[a-z]?)")


def _pherc(tail):
    digits = re.match(r"\d+", tail).group(0)
    return "PHerc" + digits.zfill(4) + tail[len(digits):].upper()


def scroll_id(text):
    """A scroll id in its normal form, or None for an empty one: a PHerc number becomes PHerc plus four digits and an
    upper-case suffix (pherc_139 gives PHerc0139, pherc9001b gives PHerc9001B); any other id is kept as written."""
    t = str(text or "").strip()
    if not t:
        return None
    m = _PHERC.fullmatch(t)
    return _pherc(m.group(1)) if m else t


def scroll_of(path):
    """The PHerc scroll id named in a path (PHerc0139 for .../PHerc139/w035), the last one if several, or None."""
    m = _PHERC.findall(path)
    return _pherc(m[-1]) if m else None


def parse_allow(allow):
    """None for no restriction ("any"), else the tuple of allowed scroll ids in their normal form."""
    if allow is None:
        return None
    ids = allow.split(",") if isinstance(allow, str) else list(allow)
    ids = [scroll_id(s) for s in ids]
    ids = [s for s in ids if s]
    if not ids:
        raise ValueError("the allow list is empty: name at least one scroll id, or any")
    if any(s.lower() == "any" for s in ids):
        return None
    return tuple(ids)


def scroll_in_path(path, allow=None):
    """The scroll a segment path names: the PHerc id in it (the last one if several); when it has none, a folder
    called like an id on the allow list, so ids of another form can be listed too."""
    sc = scroll_of(path)
    if sc is None and allow:
        parts = [p.casefold() for p in re.split(r"[\\/]+", path) if p]
        for a in allow:
            if a.casefold() in parts:
                return a
    return sc


def request_info(mode, allow, segment=None, scroll=None, key=None, query=None):
    """The dict a guard gets (see EXTRA_GUARDS)."""
    return {"mode": mode, "segment": segment, "scroll": scroll, "key": key, "query": dict(query or {}), "allow": allow}


def guard(info):
    """Raise Refused unless the request may preview: every EXTRA_GUARDS rule, then the allow list. Returns the scroll
    id the request names, or None when it names none and there is no allow list."""
    for rule in list(EXTRA_GUARDS):
        rule(info)
    return check_allow(info)


def check_allow(info):
    """The allow list alone: raise Refused when the request names no scroll on it; returns the scroll id."""
    allow, sc = info["allow"], info["scroll"]
    if allow is None:
        return sc
    if sc is None:
        if info["mode"] == "stack":
            raise Refused("no scroll parameter; send scroll=ID so the allow list can be checked")
        raise Refused("no scroll id in the path; name the scroll (PHercNNNN) so the allow list can be checked")
    if sc.casefold() not in [a.casefold() for a in allow]:
        raise Refused("%s is not on the preview allow list %s" % (sc, ",".join(allow)))
    return sc


def path_info(seg, allow, query=None):
    seg = os.path.normpath(os.path.abspath(os.path.expanduser(seg)))
    return request_info("path", allow, segment=seg, scroll=scroll_in_path(seg, allow), query=query)


# ---------------------------------------------------------------- where the voxels come from

class Surface:
    """A surface volume on disk, read one window at a time: a zarr array (layers, rows, columns), a zarr group with
    array 0, or a folder of layer TIFFs (the folder itself or its layers/ subfolder, sorted by file name)."""

    def __init__(self, path):
        self.path = path
        if not os.path.exists(path):
            raise ValueError("no surface volume at %s" % path)
        lay = os.path.join(path, "layers") if os.path.isdir(os.path.join(path, "layers")) else path
        tifs = sorted(f for f in os.listdir(lay) if f.lower().endswith((".tif", ".tiff"))) if os.path.isdir(lay) else []
        if tifs and not path.rstrip("/").endswith(".zarr"):
            import tifffile
            self.layers = []
            for f in tifs:
                fp = os.path.join(lay, f)
                try:
                    self.layers.append(tifffile.memmap(fp, mode="r"))
                except (ValueError, TypeError):  # compressed TIFF: read once, kept as is (fine for previews)
                    self.layers.append(tifffile.imread(fp))
            self.shape = (len(self.layers),) + self.layers[0].shape[:2]
            self.arr = None
        else:
            import zarr
            a = zarr.open(path, mode="r")
            if hasattr(a, "keys") and not hasattr(a, "shape"):
                a = a["0"]
            self.arr = a
            self.shape = tuple(a.shape)
        self.dtype = (self.layers[0] if self.arr is None else self.arr).dtype

    def window(self, order, y0, y1, x0, x1):
        """The layers in order (layer indices) over rows y0:y1 and columns x0:x1, zero outside, in the volume's dtype."""
        D, H, W = self.shape
        out = np.zeros((len(order), y1 - y0, x1 - x0), self.dtype)
        ya, yb, xa, xb = max(y0, 0), min(y1, H), max(x0, 0), min(x1, W)
        if ya >= yb or xa >= xb:
            return out
        if self.arr is not None:  # zarr: one read of the window (indexing a layer first would read the whole layer)
            z0, z1 = min(order), max(order) + 1
            blk = np.asarray(self.arr[z0:z1, ya:yb, xa:xb])
            out[:, ya - y0:yb - y0, xa - x0:xb - x0] = blk[[z - z0 for z in order]]
            return out
        for i, z in enumerate(order):
            out[i, ya - y0:yb - y0, xa - x0:xb - x0] = self.layers[z][ya:yb, xa:xb]
        return out


class _PathSource:
    """Path mode: every patch can be read from the surface volume."""

    def __init__(self, surf, order, patch):
        self.surf, self.order, self.P = surf, order, patch
        self.canvas = (int(surf.shape[1]), int(surf.shape[2]))

    def ready(self, r, c):
        return True

    def patch(self, r, c):
        return self.surf.window(self.order, r, r + self.P, c, c + self.P)

    def covers(self, y0, y1, x0, x1):
        return True

    def region(self, y0, y1, x0, x1):
        """The layers in self.order over rows y0:y1 and columns x0:x1 (window backends)."""
        return self.surf.window(self.order, y0, y1, x0, x1)


class _StackSource:
    """Stack mode: the uploaded layers (depth, sh, sw) cover the canvas rectangle at column sx, row sy, or nothing
    was uploaded. A patch is ready when the part of it inside the canvas lies inside that rectangle."""

    def __init__(self, cw, ch, patch, stack=None, sx=0, sy=0, reverse=False):
        self.canvas, self.P = (ch, cw), patch
        self.stack, self.sx, self.sy, self.reverse = stack, sx, sy, reverse

    def ready(self, r, c):
        if self.stack is None:
            return False
        (H, W), P = self.canvas, self.P
        _, sh, sw = self.stack.shape
        return self.sy <= r and min(r + P, H) <= self.sy + sh and self.sx <= c and min(c + P, W) <= self.sx + sw

    def patch(self, r, c):
        (H, W), P = self.canvas, self.P
        r1, c1 = min(r + P, H), min(c + P, W)
        out = np.zeros((self.stack.shape[0], P, P), self.stack.dtype)  # zero filled past the canvas edge
        blk = self.stack[:, r - self.sy:r1 - self.sy, c - self.sx:c1 - self.sx]
        out[:, :r1 - r, :c1 - c] = blk[::-1] if self.reverse else blk
        return out

    def covers(self, y0, y1, x0, x1):
        """Whether the canvas rectangle rows y0:y1, columns x0:x1 lies inside the upload (window backends)."""
        if self.stack is None:
            return False
        _, sh, sw = self.stack.shape
        return self.sy <= y0 and y1 <= self.sy + sh and self.sx <= x0 and x1 <= self.sx + sw

    def region(self, y0, y1, x0, x1):
        """The uploaded layers over that rectangle, in forward order whatever the variant (window backends reverse
        through the layer step)."""
        return self.stack[:, y0 - self.sy:y1 - self.sy, x0 - self.sx:x1 - self.sx]


def view_positions(length, patch, stride, lo, hi):
    """The positions of flat_contract.sliding_positions(length, patch, stride) whose patch overlaps [lo, hi), in
    order, without listing the whole axis."""
    if length <= patch:
        return [0] if lo < length and hi > 0 else []
    last = length - patch
    k0 = max((lo - patch) // stride + 1, 0)
    k1 = min((hi - 1) // stride, last // stride)
    out = [k * stride for k in range(k0, k1 + 1)]
    if last % stride and last < hi and last + patch > lo:  # the flush position, when it is not a regular one
        out.append(last)
    return out


# ---------------------------------------------------------------- the window rule (window backends)
#
# A window backend tiles a window [a, e) of an axis of length L by villa's rule from the window's own origin:
# positions a, a + s, a + 2s, ... up to e - P, plus e - P when that is not one of them (P patch, s stride). The whole
# map tiles [0, L) the same way: 0, s, 2s, ... up to L - P, plus the flush L - P. A pixel's value is the blend of the
# patches that cover it, so a window pixel equals the whole map's pixel when both cover it with the same patches.
# With a on the grid (a multiple of s), the window's regular positions are positions of the whole map, and pixel p
# of the window gets exactly the whole map's patches when
#   low side:   a = 0, or p >= a + P - s           (else the map's patch at a - s also covers p);
#   high side:  e = L (the window's flush patch is the map's flush patch), or p < e - P + s when e - P is on the
#               grid, p < e - P when it is not (the window's own flush patch e - P is no patch of the map), and
#               p < L - P in both cases (else the map's flush patch, which ends at L > e, covers p).
# Rows and columns are independent, so a window's exact pixels are the rectangle exact_span(rows) x exact_span(columns).
# An axis no longer than the patch has one position 0 in the whole map, its patch zero filled past the edge: the
# window is the whole axis. The tests check both functions against an enumeration of the patch sets.

def exact_span(a, e, length, patch, stride):
    """The pixels [lo, hi) of the window [a, e) of an axis of the given length whose tiled value equals the whole
    axis's (the rule above); an empty span (a, a) when the window is off the grid, shorter than one patch, or not the
    whole of an axis no longer than the patch."""
    L, P, S = int(length), int(patch), max(1, int(stride))
    a, e = int(a), int(e)
    if L <= P:
        return (0, L) if (a, e) == (0, L) else (a, a)
    if a < 0 or e > L or a % S or e - a < P:
        return (a, a)
    lo = a if a == 0 else a + P - S
    if e == L:
        hi = L
    else:
        f = e - P
        hi = min(L - P, f + S if f % S == 0 else f)
    return (lo, max(lo, hi))


def window_span(lo, hi, length, patch, stride):
    """The smallest window [a, e) on the grid (a a multiple of the stride; e one too, or the axis end) at least one
    patch long whose exact_span holds the pixels [lo, hi) of an axis of the given length. For patch = 2 x stride the
    margin is one stride on each side that is not the axis end; the whole axis when it is no longer than the patch."""
    L, P, S = int(length), int(patch), max(1, int(stride))
    lo, hi = max(0, int(lo)), min(L, int(hi))
    if L <= P:
        return 0, L
    a = max(0, (lo - P + S) // S * S)
    if hi > L - P:  # the map's flush patch covers a kept pixel: only a window to the end has it
        e = L
    else:
        reach = hi + P - S if P % S == 0 else hi + P
        e = min(L, -(-reach // S) * S)
    if e - a < P:  # only at the axis end: start one patch before it, on the grid
        a = min(a, (L - P) // S * S)
    return a, e


def cells_inside(lo, hi, length, stride):
    """The cell indices i whose pixels [i * stride, min((i + 1) * stride, length)) lie inside [lo, hi)."""
    S = max(1, int(stride))
    out, i = [], -(-int(lo) // S)
    while i * S < hi and min((i + 1) * S, length) <= hi:
        out.append(i)
        i += 1
    return out


def upsample(y, p):
    """Bilinear resize of (n, h, w) to (n, p, p) with half-pixel centers (torch interpolate, align_corners False),
    for models whose output is smaller than the patch."""
    n, h, w = y.shape
    if (h, w) == (p, p):
        return y

    def axis(src, dst):
        c = (np.arange(dst) + 0.5) * src / dst - 0.5
        c = np.clip(c, 0, src - 1)
        i0 = np.floor(c).astype(int); i1 = np.minimum(i0 + 1, src - 1)
        return i0, i1, (c - i0).astype(np.float32)
    r0, r1, fr = axis(h, p); c0, c1, fc = axis(w, p)
    a = y[:, r0] * (1 - fr)[None, :, None] + y[:, r1] * fr[None, :, None]
    return a[:, :, c0] * (1 - fc)[None, None, :] + a[:, :, c1] * fc[None, None, :]


# ---------------------------------------------------------------- backends

class _FixedBatch:
    """Shared by the model backends: the model takes exactly ishape, so the last batch is padded with zero patches."""

    def __call__(self, batch):
        B = self.ishape[0]
        outs = []
        with self.lock:
            for s in range(0, batch.shape[0], B):
                c = batch[s:s + B]
                n = c.shape[0]
                if n < B:
                    c = np.concatenate([c, np.zeros((B - n,) + c.shape[1:], np.float32)])
                outs.append(self.run(np.ascontiguousarray(c, np.float32))[:n])
        return np.concatenate(outs)


class CoreMLBackend(_FixedBatch):
    """Runs batches through coreml_server.py in its own Python (COREML_PY, default this one)."""

    name = "coreml"

    def __init__(self, package, units="CPU_AND_NE", python=None):
        py = python or os.environ.get("COREML_PY", sys.executable)
        self.p = subprocess.Popen([py, os.path.join(HERE, "coreml_server.py"), package, units],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        line = self.p.stdout.readline().split()
        if not line or line[0] != b"READY":
            raise SystemExit("coreml_server did not start: %r" % line)
        self.ishape = tuple(int(v) for v in line[1].split(b","))
        self.oshape = tuple(int(v) for v in line[2].split(b","))
        self.lock = threading.Lock()

    def run(self, c):
        self.p.stdin.write(struct.pack("<Q", c.nbytes)); self.p.stdin.write(c.tobytes()); self.p.stdin.flush()
        m = struct.unpack("<Q", self.p.stdout.read(8))[0]
        return np.frombuffer(self.p.stdout.read(m), np.float32).reshape(self.oshape).copy()

    def close(self):
        try:
            self.p.stdin.close(); self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


class TorchScriptBackend(_FixedBatch):
    """Runs batches through a traced TorchScript model in this process, in float32, on the CPU, the Apple GPU (mps)
    or CUDA. torch is imported here and nowhere else."""

    name = "torchscript"

    def __init__(self, model, device="auto", input_shape=(16, 1, 17, 128, 128)):
        try:
            import torch
        except ImportError:
            raise SystemExit("the torchscript backend needs torch in this Python (pip install torch)")
        if device == "auto":
            mps = getattr(torch.backends, "mps", None)
            device = "cuda" if torch.cuda.is_available() else "mps" if mps is not None and mps.is_available() else "cpu"
        self.torch, self.device = torch, torch.device(device)
        self.m = torch.jit.load(model, map_location=self.device).eval()
        self.ishape = tuple(int(v) for v in input_shape)
        self.lock = threading.Lock()
        self.oshape = tuple(self.run(np.zeros(self.ishape, np.float32)).shape)  # one run on zeros gives the shape

    def run(self, c):
        with self.torch.no_grad():
            y = self.m(self.torch.from_numpy(c).to(self.device))
        if isinstance(y, dict):
            y = y["ink"] if "ink" in y else next(iter(y.values()))
        if isinstance(y, (list, tuple)):
            y = y[0]
        return y.detach().float().cpu().numpy()


class FakeBackend:
    """CPU stand-in for tests: a depth-weighted mean of each patch (deeper layers count more), as a logit. It is not
    a model and its output never stands for a map."""

    name = "fake"

    def __init__(self, batch=4, depth=17, patch=128, out_stride=1):
        self.ishape = (batch, 1, depth, patch, patch)
        self.oshape = (batch, 1, patch // out_stride, patch // out_stride)
        self.stride = out_stride
        self.calls = self.patches = 0

    def __call__(self, batch):
        self.calls += 1
        self.patches += batch.shape[0]
        d = batch.shape[2]
        wz = np.linspace(0.5, 1.5, d, dtype=np.float32) / d
        m = np.zeros(batch.shape[:2] + batch.shape[3:], np.float32)
        for z in range(d):  # a fixed order of float32 sums: a patch's result does not depend on its batch
            m += batch[:, :, z] * wz[z]
        if self.stride > 1:
            s = self.stride
            n, c, h, w = m.shape
            m = m.reshape(n, c, h // s, s, w // s, s).mean(axis=(3, 5))
        return m * np.float32(2.0)


def export_depth(weights, patch):
    """The layers an inkrs export reads: crop_size[0] in the JSON sidecar beside the safetensors file
    (inkrs.export_weights writes crop_size as [depth, patch, patch]). SystemExit when the sidecar does not say."""
    side = os.path.splitext(os.fspath(weights))[0] + ".json"
    try:
        with open(side) as fh:
            crop = json.load(fh).get("crop_size")
    except (OSError, ValueError, AttributeError) as e:
        raise SystemExit("inkrs: cannot tell how many layers %s reads: no readable export sidecar %s (%s)"
                         % (weights, side, e))
    if not (isinstance(crop, list) and len(crop) == 3 and all(isinstance(v, int) and v > 0 for v in crop)
            and crop[1] == crop[2] == patch):
        raise SystemExit("inkrs: cannot tell how many layers %s reads: crop_size %r in %s is not [depth, %d, %d]"
                         % (weights, crop, side, patch, patch))
    return crop[0]


def default_batch(model):
    """The inkrs batch (tiles per forward) when none is given: 16 for 128 px tiles, 8 for 384 px tiles (Reader V3),
    from crop_size in the sidecar beside a .safetensors export. 8 when the sidecar cannot be read (a villa .pth,
    whose export inkrs finds itself): it fits either tile size. A preview runs a few dozen tiles at a time, so a
    larger batch buys nothing and costs GPU memory; inkrs's maps do not depend on the batch."""
    try:
        with open(os.path.splitext(os.fspath(model))[0] + ".json") as fh:
            patch = int(json.load(fh)["crop_size"][-1])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return 8
    return 8 if patch >= 384 else 16


class InkrsBackend:
    """Window backend: inkrs (https://github.com/praveenperera/inkrs, MIT or Apache 2.0) runs a villa flat ink reader
    with one engine resident on the GPU (Metal on Apple Silicon, CUDA elsewhere). It normalizes, tiles and blends
    itself and returns villa's uint8 map, trunc(255 * blended p), of a whole window, so the server hands it windows
    on the canvas grid (window_span) and keeps only the pixels exact_span names. inkrs is imported here and nowhere
    else. It reads uint8 layers only."""

    name = "inkrs"
    window = True
    quantized = True
    dtypes = ("uint8",)

    def __init__(self, model, device="auto", batch_size=None):
        try:
            import inkrs
        except ImportError:
            raise SystemExit("the inkrs backend needs inkrs in this Python (pip install inkrs)")
        dev = {"auto": 0, "mps": "mps", "cuda": "cuda"}.get(device)
        if dev is None:
            raise SystemExit("the inkrs backend runs on a GPU (Metal on Apple Silicon, CUDA elsewhere): use --device "
                             "auto, mps or cuda, not %s" % device)
        if batch_size is None:
            batch_size = default_batch(model)
        try:
            eng = inkrs.Engine(model, device=dev, batch_size=batch_size)
        except inkrs.UnsupportedError as e:
            raise SystemExit("inkrs cannot run %s here (UnsupportedError): %s" % (model, e))
        except (inkrs.InkrsError, ValueError, OSError) as e:
            raise SystemExit("inkrs could not load %s: %s" % (model, e))
        if getattr(eng, "architecture", "villa") != "villa":
            raise SystemExit("inkrs: %s is a %s export, which inkrs maps only whole, by its own convention; the "
                             "preview needs villa's flat readers (Engine.run)" % (model, eng.architecture))
        self.inkrs, self.eng = inkrs, eng
        self.patch = int(eng.patch)
        self.depth = export_depth(eng.weights, self.patch)
        self.reader = getattr(eng, "reader", None)
        self.batch = int(getattr(eng, "batch_size", 0) or 0)
        self.ishape = (self.batch, 1, self.depth, self.patch, self.patch)  # the tiles inkrs runs per forward
        self.oshape = None  # inkrs returns blended maps, not model outputs
        try:
            self.gpu = inkrs.build_info().get("backend")
        except Exception:
            self.gpu = None
        self.lock = threading.Lock()

    def info(self):
        return {"version": getattr(self.inkrs, "__version__", None), "reader": self.reader, "gpu": self.gpu,
                "batch_size": self.batch, "weights": os.path.basename(os.fspath(self.eng.weights))}

    def window(self, vol, reverse, stride):
        """villa's uint8 map (h, w) of the (depth, h, w) uint8 layers vol, given in forward order and tiled from the
        window's own origin at this stride. reverse reads the layers deepest first: inkrs window (depth - 1, -1),
        villa's reverse direction. An axis shorter than one patch is zero filled to one patch (inkrs refuses a side
        under the patch; villa zero fills the one patch there) and cut back."""
        vol = np.asarray(vol)
        if vol.dtype != np.uint8:
            raise ValueError("the inkrs backend reads uint8 layers only (an inkrs limit); send dtype=uint8")
        D, h, w = vol.shape
        if D != self.depth:
            raise ValueError("the inkrs backend needs %d layers, got %d" % (self.depth, D))
        P = self.patch
        if h < P or w < P:
            pad = np.zeros((D, max(h, P), max(w, P)), np.uint8)
            pad[:, :h, :w] = vol
            vol = pad
        win = (D - 1, -1) if reverse else (0, 1)
        ik = self.inkrs
        with self.lock:
            try:
                m = self.eng.run(np.ascontiguousarray(vol), [win], stride=int(stride), occupancy=None)[0]
            except ik.UnsupportedError as e:
                raise BackendError("inkrs does not support this window (UnsupportedError): %s" % e)
            except ik.InkrsError as e:
                raise BackendError("inkrs failed on this window (InkrsError): %s" % e)
        m = np.asarray(m)
        if m.dtype != np.uint8 or m.shape != vol.shape[1:]:
            raise BackendError("inkrs returned %s %s, not a uint8 map of %s" % (m.dtype, m.shape, vol.shape[1:]))
        return m[:h, :w]


def sigmoid(v):
    return 1.0 / (1.0 + np.exp(-np.clip(v, -30, 30)))


# ---------------------------------------------------------------- patches, cache and blending

def _int(q, name, default=None):
    v = q.get(name, default)
    if v is None:
        raise ValueError("parameter %s is required" % name)
    try:
        if isinstance(v, (bool, float)) and v != int(v):
            raise ValueError
        return int(v)
    except (TypeError, ValueError):
        raise ValueError("parameter %s must be an integer, got %r" % (name, v))


def _format(fmt):
    if fmt not in FORMATS:
        raise ValueError("format must be u8, f32 or png, got %r" % (fmt,))
    return fmt


class Previewer:
    """The server's state: one backend, the patch cache and the allow list. Thread-safe (one request at a time)."""

    def __init__(self, backend, cache_mb=256, overlap=0.5, allow=None, activation="sigmoid", model_name=None,
                 voxel_um=None, max_view_px=MAX_VIEW_PX):
        self.b = backend
        _, _, self.D, self.P, _ = backend.ishape
        self.stride = max(int(round(self.P * (1 - overlap))), 1)  # 64 for 128 px patches at 0.5, villa's default
        self.windowed = bool(getattr(backend, "window", False))   # a window backend: cells of final pixels
        self.dtypes = tuple(getattr(backend, "dtypes", ("uint8", "uint16")))
        self.wmap = FC.hann2d(self.P)
        self.cache = collections.OrderedDict()
        self.cache_bytes = 0
        self.cache_cap = int(cache_mb * 2 ** 20)
        self.hits = self.misses = 0
        self.allow = parse_allow(allow)
        self.activation = activation
        self.model_name = model_name or backend.name
        self.voxel_um = voxel_um
        self.max_view_px = int(max_view_px)
        # A view's patches reach up to one patch past it on every side, so an upload may be larger than the view.
        self.max_upload_px = 2 * self.max_view_px + 16 * self.P * self.P
        self.max_body = self.D * 2 * self.max_upload_px    # bytes of the largest uint16 upload
        self.surfaces = {}
        self.lock = threading.Lock()

    def surface(self, seg):
        s = self.surfaces.get(seg)
        if s is None:
            s = self.surfaces[seg] = Surface(seg)
            if len(self.surfaces) > 4:
                self.surfaces.pop(next(iter(self.surfaces)))
        return s

    def _put(self, key, val):
        old = self.cache.pop(key, None)
        self.cache_bytes -= 0 if old is None else old.nbytes
        self.cache[key] = val
        self.cache_bytes += 0 if val is None else val.nbytes
        while self.cache_bytes > self.cache_cap and self.cache:
            _, old = self.cache.popitem(last=False)
            self.cache_bytes -= 0 if old is None else old.nbytes

    def _compute(self, src, ns, todo, got):
        """Run the patches in todo (row position, column position), a model batch at a time, into got and the cache.
        An all-zero patch is not run: it is kept as None (empty)."""
        B = self.b.ishape[0]
        run = []

        def flush():
            xs = np.stack([FC.normalize_robust(p)[None] for _, p in run]).astype(np.float32)
            y = np.asarray(self.b(xs))
            y = y.reshape(len(run), -1, y.shape[-2], y.shape[-1])[:, 0].astype(np.float32)
            if self.activation == "sigmoid":
                y = sigmoid(y)
            y = upsample(y.astype(np.float32), self.P).astype(np.float32)
            for (k, _), t in zip(run, y):
                got[k] = t = t.copy()  # its own memory, so the cache frees a patch when it drops it
                self._put((ns,) + k, t)
            del run[:]

        for k in todo:
            p = src.patch(*k)
            self.misses += 1
            if not p.any():
                got[k] = None
                self._put((ns,) + k, None)
                continue
            run.append((k, p))
            if len(run) == B:
                flush()
        if run:
            flush()

    def _view(self, src, ns, x, y, w, h):
        """Blended probabilities (h, w) for the view at column x, row y of the canvas, and (computed, cached) patch
        counts. Patches sit at villa's positions on the canvas; ns names the cache entries of this canvas."""
        (H, W), P, S = src.canvas, self.P, self.stride
        rows = view_positions(H, P, S, y, y + h)
        cols = view_positions(W, P, S, x, x + w)
        got, todo, miss = {}, [], []
        for r in rows:
            for c in cols:
                ck = (ns, r, c)
                if ck in self.cache:
                    got[(r, c)] = self.cache[ck]
                elif src.ready(r, c):
                    todo.append((r, c))
                else:
                    miss.append((r, c))
        if miss:  # stack mode only: say what to upload, compute nothing
            # need covers every patch that is not cached, also those this upload covers: the next upload replaces
            # this one, so a need of the missing patches alone would leave those uncovered again, and two viewers
            # that evict each other's patches would then trade 409s forever.
            todo += miss
            x0, y0 = min(c for _, c in todo), min(r for r, _ in todo)
            x1, y1 = max(min(c + P, W) for _, c in todo), max(min(r + P, H) for r, _ in todo)
            if (x1 - x0) * (y1 - y0) > self.max_upload_px:
                raise TooLarge("the view needs an upload of %d px, over the limit of %d px"
                               % ((x1 - x0) * (y1 - y0), self.max_upload_px))
            raise NeedStack({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}, self.D, len(todo))
        for k in got:
            self.cache.move_to_end((ns,) + k)
        self.hits += len(got)
        cached = len(got)
        self._compute(src, ns, todo, got)
        acc = np.zeros((h, w), np.float32)
        wsum = np.zeros((h, w), np.float32)
        for r in rows:  # row-major, whatever the cache held, so the float32 sums do not depend on the pan history
            for c in cols:
                t = got[(r, c)]
                if t is None:
                    continue
                a0, a1 = max(r, y), min(r + P, y + h, H)
                b0, b1 = max(c, x), min(c + P, x + w, W)
                if a0 >= a1 or b0 >= b1:
                    continue
                wt = self.wmap[a0 - r:a1 - r, b0 - c:b1 - c]
                acc[a0 - y:a1 - y, b0 - x:b1 - x] += t[a0 - r:a1 - r, b0 - c:b1 - c] * wt
                wsum[a0 - y:a1 - y, b0 - x:b1 - x] += wt
        prob = np.zeros((h, w), np.float32)
        np.divide(acc, wsum, out=prob, where=wsum > 1e-6)
        return prob, (len(todo), cached)

    def _view_cells(self, src, ns, x, y, w, h, reverse):
        """Window backends: the view as villa's uint8 map (h, w), and (computed, cached) cell counts. The cache holds
        stride by stride cells of final pixels, cell (i, j) at canvas row i * stride, column j * stride, stored only
        where exact_span says the window they came from gives the whole map's pixels. The cells the view lacks are
        computed in one window: their bounding rectangle widened by window_span on both axes. In stack mode that
        window must lie inside the upload; if it does not, NeedStack names it and nothing runs."""
        (H, W), P, S = src.canvas, self.P, self.stride
        rows = range(y // S, (y + h - 1) // S + 1)
        cols = range(x // S, (x + w - 1) // S + 1)
        got, miss = {}, []
        for i in rows:
            for j in cols:
                ck = (ns, "cell", i, j)
                if ck in self.cache:
                    got[(i, j)] = self.cache[ck]
                else:
                    miss.append((i, j))
        if miss:
            ya, yb = window_span(min(i for i, _ in miss) * S, min((max(i for i, _ in miss) + 1) * S, H), H, P, S)
            xa, xb = window_span(min(j for _, j in miss) * S, min((max(j for _, j in miss) + 1) * S, W), W, P, S)
            if (yb - ya) * (xb - xa) > self.max_upload_px:
                raise TooLarge("the view needs an upload of %d px, over the limit of %d px"
                               % ((yb - ya) * (xb - xa), self.max_upload_px))
            if not src.covers(ya, yb, xa, xb):  # stack mode only: say what to upload, compute nothing
                raise NeedStack({"x": xa, "y": ya, "w": xb - xa, "h": yb - ya}, self.D, len(miss))
        for k in got:
            self.cache.move_to_end((ns, "cell") + k)
        self.hits += len(got)
        cached = len(got)
        if miss:
            m = self.b.window(src.region(ya, yb, xa, xb), reverse, S)
            (ey0, ey1), (ex0, ex1) = exact_span(ya, yb, H, P, S), exact_span(xa, xb, W, P, S)
            for i in cells_inside(ey0, ey1, H, S):
                for j in cells_inside(ex0, ex1, W, S):
                    c = m[i * S - ya:min((i + 1) * S, H) - ya, j * S - xa:min((j + 1) * S, W) - xa]
                    c = c.copy() if c.any() else None  # an all-zero cell is kept as None (empty)
                    self._put((ns, "cell", i, j), c)
                    if i in rows and j in cols and (i, j) not in got:
                        got[(i, j)] = c
            self.misses += len(miss)
            lost = [k for k in miss if k not in got]
            if lost:  # cannot happen when window_span and exact_span agree; never serve a guess
                raise BackendError("window rule: cells %s of the window y %d:%d x %d:%d are not exact"
                                   % (lost[:4], ya, yb, xa, xb))
        out = np.zeros((h, w), np.uint8)
        for (i, j), c in got.items():
            if c is None:
                continue
            r0, c0 = i * S, j * S
            a0, a1 = max(r0, y), min(r0 + c.shape[0], y + h)
            b0, b1 = max(c0, x), min(c0 + c.shape[1], x + w)
            out[a0 - y:a1 - y, b0 - x:b1 - x] = c[a0 - r0:a1 - r0, b0 - c0:b1 - c0]
        return out, (len(miss), cached)

    def _check_view(self, w, h, variant):
        if w < 1 or h < 1:
            raise ValueError("the view must be at least 1 px wide and 1 px high")
        if w * h > self.max_view_px:
            raise TooLarge("the view has %d px, over max_view_px %d" % (w * h, self.max_view_px))
        if variant not in ("f", "r"):
            raise ValueError("variant must be f or r, got %r" % (variant,))

    # ------------------------------------------------------------ path mode

    def preview(self, seg, x, y, w, h, window=None, variant="f", scale=1):
        """Path mode: blended probabilities (h, w), float32, for the view at column x, row y of the surface volume
        at seg. window: (first, last + 1) layers the center crop is taken from (default all); variant f, or r for
        the control with the layers reversed; scale mean-pools the result. Pixels no non-empty patch covers are 0.
        A window backend gives villa's uint8 map instead (float32 probabilities u8 / 255 when scale > 1)."""
        return self.preview_path(seg, x, y, w, h, window, variant, scale)[0]

    def preview_path(self, seg, x, y, w, h, window=None, variant="f", scale=1, query=None):
        """preview() with the patch counts: (probabilities, (computed, cached))."""
        info = path_info(seg, self.allow, query)
        guard(info)
        self._check_view(w, h, variant)
        if scale < 1:
            raise ValueError("scale must be at least 1, got %r" % (scale,))
        with self.lock:
            surf = self.surface(seg)
            window = tuple(int(v) for v in window) if window else (0, surf.shape[0])
            order = FC.slice_order(window, self.D, variant)
            ns = ("path", info["segment"], tuple(int(v) for v in order))
            if self.windowed:  # forward layers; the backend reverses through the layer step
                fwd = FC.slice_order(window, self.D, "f")
                prob, counts = self._view_cells(_PathSource(surf, fwd, self.P), ns, x, y, w, h, variant == "r")
            else:
                prob, counts = self._view(_PathSource(surf, order, self.P), ns, x, y, w, h)
        if scale > 1:
            prob = as_prob(prob)
            hh, ww = h // scale * scale, w // scale * scale
            prob = prob[:hh, :ww].reshape(hh // scale, scale, ww // scale, scale).mean(axis=(1, 3))
        return prob, counts

    def path_request(self, q):
        """One path-mode request from its JSON fields: (probabilities, (computed, cached), format)."""
        seg = q.get("segment")
        if not isinstance(seg, str) or not seg:
            raise ValueError("segment is required: the path of a surface volume")
        x, y, w, h = (_int(q, k) for k in ("x", "y", "w", "h"))
        fmt = _format(q.get("format", "f32"))
        prob, counts = self.preview_path(seg, x, y, w, h, q.get("window"), q.get("variant", "f"),
                                         _int(q, "scale", 1), query=q)
        return prob, counts, fmt

    # ------------------------------------------------------------ stack mode

    def preview_stack(self, key, cw, ch, x, y, w, h, variant="f", stack=None, sx=0, sy=0, scroll=None, query=None):
        """Stack mode: (probabilities (h, w) float32, (computed, cached)) for the view at column x, row y of a cw by
        ch canvas whose voxels the client names with key. stack: None, or the (depth, sh, sw) uint8 or uint16
        layers, in forward order, of the canvas rectangle at column sx, row sy. Raises NeedStack with the rectangle
        to upload when a patch of the view is neither cached nor inside stack; nothing is computed then. A window
        backend gives villa's uint8 map (h, w) and counts cells; its NeedStack names the window to upload."""
        key = str(key or "")
        if not key or len(key) > 200:
            raise ValueError("key is required: text of at most 200 characters")
        guard(request_info("stack", self.allow, scroll=scroll_id(scroll), key=key, query=query))
        self._check_view(w, h, variant)
        if cw < 1 or ch < 1:
            raise ValueError("the canvas size cw, ch must be at least 1 by 1")
        if x < 0 or y < 0 or x + w > cw or y + h > ch:
            raise ValueError("the view must lie inside the canvas")
        if stack is not None:
            stack = np.asarray(stack)
            if stack.ndim != 3 or stack.shape[0] != self.D or stack.dtype not in (np.uint8, np.uint16):
                raise ValueError("the stack must be uint8 or uint16 of shape (%d, sh, sw)" % self.D)
            sh, sw = stack.shape[1:]
            if sw < 1 or sh < 1 or sx < 0 or sy < 0 or sx + sw > cw or sy + sh > ch:
                raise ValueError("the uploaded rectangle must be at least 1 px and lie inside the canvas")
            if sw * sh > self.max_upload_px:
                raise TooLarge("the upload has %d px, over the limit of %d px" % (sw * sh, self.max_upload_px))
            if stack.dtype.name not in self.dtypes:
                raise ValueError("the %s backend reads %s layers only; send dtype=%s"
                                 % (self.b.name, " or ".join(self.dtypes), self.dtypes[0]))
        with self.lock:
            src = _StackSource(cw, ch, self.P, stack, sx, sy, reverse=(variant == "r"))
            ns = ("stack", key, cw, ch, variant)
            if self.windowed:
                return self._view_cells(src, ns, x, y, w, h, variant == "r")
            return self._view(src, ns, x, y, w, h)

    def stack_request(self, q, body=b""):
        """One stack-mode request from its query parameters (name to text) and body: (probabilities, (computed,
        cached), format)."""
        cw, ch, x, y, w, h = (_int(q, k) for k in ("cw", "ch", "x", "y", "w", "h"))
        fmt = _format(q.get("format", "u8"))
        stack, sx, sy = None, 0, 0
        if body or any(k in q for k in ("sx", "sy", "sw", "sh")):
            if not all(k in q for k in ("sx", "sy", "sw", "sh")):
                raise ValueError("a body needs sx, sy, sw and sh: the canvas rectangle it covers")
            sx, sy, sw, sh = (_int(q, k) for k in ("sx", "sy", "sw", "sh"))
            dtype = q.get("dtype", "uint8")
            if dtype not in ("uint8", "uint16"):
                raise ValueError("dtype must be uint8 or uint16, got %r" % (dtype,))
            if sw < 1 or sh < 1:
                raise ValueError("the uploaded rectangle must be at least 1 px and lie inside the canvas")
            size = 1 if dtype == "uint8" else 2
            if len(body) != self.D * sh * sw * size:
                raise ValueError("the body has %d bytes; %d layers of %d x %d %s need %d"
                                 % (len(body), self.D, sh, sw, dtype, self.D * sh * sw * size))
            stack = np.frombuffer(body, "<u%d" % size).reshape(self.D, sh, sw).astype(dtype, copy=False)
        prob, counts = self.preview_stack(q.get("key"), cw, ch, x, y, w, h, q.get("variant", "f"), stack, sx, sy,
                                          scroll=q.get("scroll"), query=q)
        return prob, counts, fmt

    # ------------------------------------------------------------ reports

    def stats(self):
        return {"tiles": len(self.cache), "mb": round(self.cache_bytes / 2 ** 20, 1),
                "cap_mb": round(self.cache_cap / 2 ** 20), "hits": self.hits, "misses": self.misses}

    def health(self):
        h = {"service": SERVICE, "api": API, "backend": self.b.name, "model": self.model_name, "patch": self.P,
             "stride": self.stride, "depth": self.D, "voxel_um": self.voxel_um, "max_view_px": self.max_view_px,
             "cache": self.stats(), "input_shape": list(self.b.ishape),
             "output_shape": None if self.b.oshape is None else list(self.b.oshape),
             "allow": list(self.allow) if self.allow is not None else ["any"],
             "tiling": "window" if self.windowed else "patch",
             "quantized": bool(getattr(self.b, "quantized", False)), "dtypes": list(self.dtypes)}
        if hasattr(self.b, "info"):
            h["engine"] = self.b.info()
        return h


# ---------------------------------------------------------------- output

def to_u8(prob):
    """villa's uint8 convention for a probability map: clip to 0..1, times 255, truncate (floor(255 p)). A uint8
    map (a window backend's) is already in it and passes unchanged."""
    if isinstance(prob, np.ndarray) and prob.dtype == np.uint8:
        return prob
    a = np.clip(np.asarray(prob, np.float32), 0, 1)
    a *= np.float32(255)
    return a.astype(np.uint8)


def as_prob(a):
    """Float32 probabilities: a uint8 map becomes u8 / 255 (a window backend's f32, quantized); others pass."""
    if isinstance(a, np.ndarray) and a.dtype == np.uint8:
        return a.astype(np.float32) / np.float32(255)
    return a


def png_gray(prob):
    """8-bit grayscale PNG of probabilities 0..1, the pixels of to_u8 (standard library only)."""
    a = to_u8(prob)
    h, w = a.shape
    raw = b"".join(b"\x00" + a[r].tobytes() for r in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


def encode(prob, fmt):
    """(body, content type) of a view in one of FORMATS."""
    if fmt == "png":
        return png_gray(prob), "image/png"
    if fmt == "u8":
        return to_u8(prob).tobytes(), "application/octet-stream"
    return np.ascontiguousarray(as_prob(prob), "<f4").tobytes(), "application/octet-stream"


# ---------------------------------------------------------------- server

def make_handler(pv):
    from http.server import BaseHTTPRequestHandler

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keeps the viewer's connection open between requests

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype, headers=(), close=False):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            if close:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj, close=False):
            self._send(code, json.dumps(obj).encode(), "application/json", close=close)

        def do_GET(self):
            if urllib.parse.urlsplit(self.path).path.rstrip("/") == "/health":
                return self._json(200, pv.health())
            self._json(404, {"error": "unknown path"})

        def _chunked(self, limit):
            """The body of a request sent with chunked transfer encoding. ValueError when it is malformed, TooLarge
            when it is over limit bytes; the rest of the request is then unread."""
            parts, total = [], 0
            while True:
                head = self.rfile.readline(1026).split(b";", 1)[0].strip()
                try:
                    size = int(head, 16) if head.isalnum() else -1
                except ValueError:
                    size = -1
                if size < 0:
                    raise ValueError("the chunked body is malformed")
                if size == 0:
                    while self.rfile.readline(8194) not in (b"\r\n", b"\n", b""):  # trailer lines, to the blank one
                        pass
                    return b"".join(parts)
                total += size
                if total > limit:
                    raise TooLarge("the body has over %d bytes, the limit" % limit)
                data = self.rfile.read(size)
                if len(data) != size or self.rfile.readline(3) not in (b"\r\n", b"\n"):
                    raise ValueError("the chunked body is malformed")
                parts.append(data)

        def do_POST(self):
            u = urllib.parse.urlsplit(self.path)
            if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
                try:
                    body = self._chunked(pv.max_body)
                except TooLarge as e:  # the rest of the body is unread, so the connection ends with the reply
                    return self._json(413, {"error": str(e)}, close=True)
                except ValueError as e:
                    return self._json(400, {"error": str(e)}, close=True)
            else:
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    n = -1
                if n < 0:  # the body cannot be skipped, so the connection ends with the reply
                    return self._json(400, {"error": "Content-Length must be a byte count"}, close=True)
                if n > pv.max_body:  # not kept in memory: skipped when small enough, else the connection ends
                    left = n if n <= DRAIN_BYTES else 0
                    while left > 0:
                        got = self.rfile.read(min(left, 1 << 20))
                        if not got:
                            break
                        left -= len(got)
                    return self._json(413, {"error": "the body has %d bytes, over the limit of %d" % (n, pv.max_body)},
                                      close=(n > DRAIN_BYTES or left > 0))
                body = self.rfile.read(n) if n else b""
            if u.path.rstrip("/") != "/preview":
                return self._json(404, {"error": "unknown path"})
            try:
                if u.query:  # stack mode: the request is in the query, the body is voxels
                    q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query, keep_blank_values=True).items()}
                    prob, tiles, fmt = pv.stack_request(q, body)
                else:  # path mode: the request is a JSON body
                    q = json.loads(body or b"{}")
                    if not isinstance(q, dict):
                        raise ValueError("the JSON body must be an object")
                    prob, tiles, fmt = pv.path_request(q)
                out, ctype = encode(prob, fmt)
            except NeedStack as e:
                return self._json(409, {"need": e.need, "depth": e.depth, "missing": e.missing})
            except Refused as e:
                return self._json(403, {"refused": str(e)})
            except TooLarge as e:
                return self._json(413, {"error": str(e)})
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            except (KeyError, TypeError) as e:
                return self._json(400, {"error": "%s: %s" % (type(e).__name__, e)})
            except BackendError as e:  # the model backend failed on this request; the server stays up
                return self._json(500, {"error": str(e)})
            except Exception as e:  # keep the server up for the viewer
                return self._json(500, {"error": "%s: %s" % (type(e).__name__, e)})
            self._send(200, out, ctype, [("X-Shape", "%d,%d" % prob.shape), ("X-Backend", pv.b.name),
                                         ("X-Tiles", "%d,%d" % tiles)])
    return H


# ---------------------------------------------------------------- command line

def _shape5(text):
    try:
        v = tuple(int(s) for s in text.split(","))
    except ValueError:
        v = ()
    if len(v) != 5 or v[1] != 1 or v[3] != v[4] or min(v) < 1:
        raise argparse.ArgumentTypeError("the input shape must read B,1,D,P,P (such as 16,1,17,128,128)")
    return v


def _positive(text):
    try:
        v = int(text)
    except ValueError:
        v = 0
    if v < 1:
        raise argparse.ArgumentTypeError("must be a whole number of at least 1")
    return v


def _overlap(text):
    try:
        v = float(text)
    except ValueError:
        v = -1.0
    if not 0.0 <= v < 1.0:
        raise argparse.ArgumentTypeError("the overlap must be at least 0 and under 1")
    return v


def build_parser(default_allow=DEFAULT_ALLOW):
    """The argument parser; its commands attribute maps serve, snapshot and check to their subparsers, so a wrapper
    can add options of its own before calling main(argv, parser)."""
    ap = argparse.ArgumentParser(description="Live ink preview server: an ink model's output for the view on screen")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ap.commands = {}
    for name in ("serve", "snapshot", "check"):
        p = ap.commands[name] = sub.add_parser(name)
        p.add_argument("--allow", default=default_allow, metavar="SCROLLS",
                       help="scroll ids that may preview, comma-separated; any: no restriction")
        if name == "check":
            p.add_argument("--segment", required=True, help="path of a surface volume")
            continue
        p.add_argument("--backend", choices=("coreml", "torchscript", "inkrs", "fake"), default="coreml")
        p.add_argument("--package", help="coreml: the Core ML package made by export_ckpt.py and convert.py")
        p.add_argument("--units", default="CPU_AND_NE", help="coreml: compute units")
        p.add_argument("--model", help="torchscript: the traced model (export_ckpt.py's output); inkrs: the "
                                       "safetensors export (python -m inkrs.export_weights) or villa's .pth")
        p.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto",
                       help="torchscript and inkrs: device (inkrs runs on mps or cuda only)")
        p.add_argument("--batch-size", type=_positive, metavar="N",
                       help="inkrs: tiles per forward (default 16 for 128 px tiles, 8 for 384 px tiles or a .pth)")
        p.add_argument("--input-shape", type=_shape5, default=(16, 1, 17, 128, 128), metavar="B,1,D,P,P",
                       help="torchscript and fake: the model's input shape (coreml reads it from the package)")
        p.add_argument("--model-name", help="the model label /health reports (default: the model file's name)")
        p.add_argument("--voxel-um", type=float,
                       help="the voxel size the model was trained at, reported by /health (default: 9.36 when the "
                            "model label is ink_9um, else unknown)")
        p.add_argument("--cache-mb", type=float, default=256, help="memory cap of the patch cache")
        p.add_argument("--overlap", type=_overlap, default=0.5,
                       help="patch overlap; 0.5 is stride 64 for 128 px patches, villa's default grid")
        p.add_argument("--activation", choices=("sigmoid", "none"), default="sigmoid",
                       help="sigmoid for models that output logits (export_ckpt.py's do)")
        p.add_argument("--max-view-px", type=int, default=MAX_VIEW_PX, help="largest view, in pixels")
        if name == "serve":
            p.add_argument("--port", type=int, default=8765)
        else:
            for k in ("x", "y", "w", "h"):
                p.add_argument("--" + k, type=int, required=True)
            p.add_argument("--segment", required=True, help="path of a surface volume")
            p.add_argument("--window", help="FIRST,END layers the center crop comes from (default all)")
            p.add_argument("--variant", choices=("f", "r"), default="f", help="r: the control with layers reversed")
            p.add_argument("--scale", type=int, default=1, help="mean-pool the result by N")
            p.add_argument("--out", required=True, help=".tif (float32; inkrs: its uint8 map) or .png (8-bit)")
    return ap


def model_label(a, backend=None):
    """The label /health reports: --model-name, else the reader name an inkrs export records, else the model file's
    name without its extension."""
    if a.model_name:
        return a.model_name
    if getattr(backend, "reader", None):
        return backend.reader
    path = {"coreml": a.package, "torchscript": a.model, "inkrs": a.model}.get(a.backend)
    if not path:
        return a.backend
    return os.path.splitext(os.path.basename(os.path.normpath(path)))[0]


def build_backend(a):
    if a.backend == "fake":
        b, _, d, p, _ = a.input_shape
        return FakeBackend(batch=b, depth=d, patch=p)
    if a.backend == "torchscript":
        if not a.model:
            raise SystemExit("--model TRACED.pt is required for the torchscript backend")
        return TorchScriptBackend(a.model, a.device, a.input_shape)
    if a.backend == "inkrs":
        if not a.model:
            raise SystemExit("--model EXPORT.safetensors (or villa's .pth) is required for the inkrs backend")
        return InkrsBackend(a.model, a.device, a.batch_size)
    if not a.package:
        raise SystemExit("--package PATH.mlpackage is required for the coreml backend")
    return CoreMLBackend(a.package, a.units)


def run(a):
    """Run one parsed command; the exit code."""
    try:
        allow = parse_allow(a.allow)
    except ValueError as e:
        raise SystemExit("--allow: %s" % e)
    if allow is None and not EXTRA_GUARDS:  # say so on every start, so nobody takes it for a restricted server
        print("inkpreview: no allow list and no extra rules: every scroll may preview (--allow SCROLLS restricts it)",
              file=sys.stderr, flush=True)
    if a.cmd == "check":
        try:
            sc = guard(path_info(a.segment, allow))
        except Refused as e:
            print("refused: %s" % e)
            return 3
        print("ok: %s may preview" % (sc or "any scroll"))
        return 0
    b = build_backend(a)
    name = model_label(a, b)
    voxel = a.voxel_um if a.voxel_um is not None else (9.36 if name == "ink_9um" else None)
    pv = Previewer(b, a.cache_mb, a.overlap, allow, a.activation, name, voxel, a.max_view_px)
    try:
        if a.cmd == "snapshot":
            try:
                win = tuple(int(v) for v in a.window.split(",")) if a.window else None
                prob = pv.preview(a.segment, a.x, a.y, a.w, a.h, win, a.variant, a.scale)
            except Refused as e:
                print("refused: %s" % e)
                return 3
            except ValueError as e:  # a bad view, layer window or segment path
                raise SystemExit("snapshot: %s" % e)
            if a.out.endswith(".png"):
                with open(a.out, "wb") as fh:
                    fh.write(png_gray(prob))
            else:  # float32 probabilities; a window backend's uint8 map as it is (villa's map encoding)
                import tifffile
                tifffile.imwrite(a.out, prob if prob.dtype == np.uint8 else prob.astype(np.float32),
                                 compression="zlib")  # lossless deflate
            print("wrote %s %dx%d backend=%s %s" % (a.out, prob.shape[1], prob.shape[0], b.name, json.dumps(pv.stats())))
            return 0
        from http.server import ThreadingHTTPServer
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(pv))
        except OSError as e:
            raise SystemExit("cannot listen on 127.0.0.1:%d: %s" % (a.port, e))
        print("inkpreview serving http://127.0.0.1:%d backend=%s model=%s input=%s"
              % (srv.server_address[1], b.name, name, b.ishape), flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        if hasattr(b, "close"):
            b.close()


def main(argv=None, parser=None):
    if sys.stdout.isatty():  # styled terminal output where this repository's kit package is present
        try:
            sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
            from kit import termstyle
            termstyle.script()
        except Exception:
            pass
    return run((parser or build_parser()).parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
