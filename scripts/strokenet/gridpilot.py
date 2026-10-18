"""Grid pilot: does a finer tile stride remove the organizers' 6.4 px tile grid?

The organizers' PHerc. Paris 4 ink maps are predicted in 256 px tiles at stride 128 on the 2.4 um
grid, blended with a Hann window; pooled to 48 um they carry a grid every 6.4 px that repeats every
32 px (docs/prereg/2026-10-14-strokenet.md, "The tile grid"). This pilot re-renders one region of
one training segment with the same public checkpoint and recipe at strides 128, 64 and 32 and
measures how much the output depends on where the tiles fall: each stride is rendered twice, with
the tile origins shifted by half a stride the second time, and the difference of the two, which
holds no ink content, is the tiling effect. Rules: docs/prereg/2026-10-14-gridpilot.md. Cloud
runner: scripts/strokenet/modal_gridpilot.py.

The recipe follows villa's ink-detection/optimized_inference at a4979b99 (inference.py hann2d,
_grid_1d and predict_fn; entrypoint.py's uint8 conversion): layers [23, 85) of the 109-layer
surface volume, clip 0..200 and divide by 200, 256 px tiles, sigmoid of the network output resized
bilinearly to the tile, Hann-weighted overlap-add over tiles with any nonzero voxel, divided by
the summed weights, clipped to 0..1, times 255, truncated to uint8. Numpy only, except render(),
which takes the network as a function.
"""
import json
import math
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data as D  # noqa: E402

SEGMENT = "w028-037"                 # the first training segment in the fixed order
REGION = 192                         # pooled pixels (9.2 mm), a multiple of the 32 px grid repeat
LATTICE = 32                         # region corners on the 32 px lattice (640 native px)
TILE = 256
MARGIN = 3 * 128                     # native px read around the region: every region pixel gets
                                     # its full set of tiles at every stride and both offsets
STRIDES = (128, 64, 32)
Z0, Z1 = 23, 85                      # production layer window (62 layers, centered on the surface)
CLIP = 200
CHUNK = 128                          # surface volume chunks: (109, 128, 128) uint8, uncompressed
DEPTH = 109
PERIOD = 32                          # pooled px: a tiling pattern repeats every 32 px at every stride here
DETECT = 2.0                         # a tiling effect is seen when it is over DETECT times the noise
FLOOR = 0.1                          # least noise assumed, in 0..255 pooled units (a repeat can match exactly)
REDUCED = 0.5                        # a finer stride "reduces" the effect at or below this share of stride 128's
MIN_R = 0.95                         # reproduction and content checks
BATCH = 32
# Tiles a full re-render of the 27 maps would forward at each stride (full_render_tiles on the
# organizers' pooled maps, 14 October 2026); stride 128 is the published render.
FULL_TILES = {128: 17608559, 64: 70433274, 32: 281728900}
ZARR = ("https://data.aws.ash2txt.org/samples/PHercParis4/segments/{stamp}-{seg}/surface-volumes/"
        "2.4um-0.22m-78keV-volume-20260411134726.zarr/0")
CHECKPOINT = {"repo": "scrollprize/ink_canonical_2um", "revision": "075855bc69317ef6febf39a0d9d687b27d2b7c29",
              "file": "r152_3ddec_v2_l5_epoch13.ckpt", "bytes": 1549556213,
              "sha256": "36dd0de84b7b7aa6590184192c7415466cd8a1ba7c1e59f42c6373846373c3e0"}
VILLA = {"repo": "https://github.com/ScrollPrize/villa", "commit": "a4979b99004934955784ea19b30da66cfe5f9ead",
         "dir": "ink-detection/optimized_inference",
         "files": {"model_resnet3d_3d_decoder.py": "7b2b2cfc6c7fb963a3da1bf128543ceadf8ad887f32a319bc0a38fb378f9e2ca",
                   "models/resnetall.py": "2b49ac430d77bae189cf002ed9c2748f940a6cd92b809a23db6f7dba381afbf6",
                   "models/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}}


# ------------------------------------------------------------------ region
def choose_region(label, size=REGION, lattice=LATTICE):
    """Top-left (y, x), in pooled px, of the size x size window on the lattice with the most usable
    pixels (label > 0); ties go to the most text (label 2), then the smaller y, then x. Windows
    in the first or last lattice step of either axis are left out, so the native margin read
    around the region stays inside the segment and the render's tiles sit where the
    published map's tiles sat."""
    lab = np.asarray(label)
    usable = np.pad((lab > 0).astype(np.int64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    text = np.pad((lab == 2).astype(np.int64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)

    def box(s, y, x):
        return s[y + size, x + size] - s[y, x + size] - s[y + size, x] + s[y, x]

    best = None
    for y in range(lattice, lab.shape[0] - size - lattice + 1, lattice):
        for x in range(lattice, lab.shape[1] - size - lattice + 1, lattice):
            key = (-box(usable, y, x), -box(text, y, x), y, x)
            if best is None or key < best:
                best = key
    if best is None:
        raise ValueError("the map is smaller than the region")
    return best[2], best[3]


# ------------------------------------------------------------------ reading the surface volume
def chunk_range(z0=Z0, z1=Z1, chunk=CHUNK):
    """Byte range of layers [z0, z1) inside one C-ordered (DEPTH, chunk, chunk) uint8 chunk."""
    return z0 * chunk * chunk, z1 * chunk * chunk - 1


def http_fetch(url, byte_range, retries=5, timeout=120):
    """Bytes of one chunk's layer range, or None for a chunk the store does not have (fill 0)."""
    req = urllib.request.Request(url, headers={"Range": f"bytes={byte_range[0]}-{byte_range[1]}"})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            if i == retries - 1:
                raise
        except OSError:
            if i == retries - 1:
                raise
    return None


def read_crop(base, y, x, h, w, fetch=http_fetch, z0=Z0, z1=Z1, workers=32):
    """Native crop [y, y + h) x [x, x + w) of layers [z0, z1) as (h, w, z1 - z0) uint8, read
    chunk by chunk with byte ranges; corners must lie on the chunk grid. Missing chunks are 0."""
    if y % CHUNK or x % CHUNK or h % CHUNK or w % CHUNK or y < 0 or x < 0:
        raise ValueError("the crop must lie on the 128 px chunk grid")
    out = np.zeros((h, w, z1 - z0), np.uint8)
    rng = chunk_range(z0, z1)
    keys = [(cy, cx) for cy in range(y // CHUNK, (y + h) // CHUNK) for cx in range(x // CHUNK, (x + w) // CHUNK)]

    def one(k):
        b = fetch(f"{base}/0/{k[0]}/{k[1]}", rng)
        return k, b

    with ThreadPoolExecutor(workers) as ex:
        for (cy, cx), b in ex.map(one, keys):
            if b is None:
                continue
            a = np.frombuffer(b, np.uint8)
            if a.size != (z1 - z0) * CHUNK * CHUNK:
                raise IOError(f"chunk {cy}/{cx}: {a.size} bytes, expected {(z1 - z0) * CHUNK * CHUNK}")
            oy, ox = cy * CHUNK - y, cx * CHUNK - x
            out[oy:oy + CHUNK, ox:ox + CHUNK] = a.reshape(z1 - z0, CHUNK, CHUNK).transpose(1, 2, 0)
    return out


# ------------------------------------------------------------------ rendering (villa's recipe)
def hann2d(h, w):
    """villa inference.hann2d: normalized 2D Hann window (sum 1)."""
    k = np.outer(np.hanning(h).astype(np.float32), np.hanning(w).astype(np.float32))
    s = k.sum()
    return k / (s if s > 0 else 1.0)


def grid_1d(L, tile, stride):
    """villa inference._grid_1d: positions covering [0, L), the last tile touching the border."""
    xs = list(range(0, max(1, L - tile + 1), stride))
    end = max(0, L - tile)
    if not xs or xs[-1] != end:
        xs.append(end)
    return xs


def axis_positions(L, stride, offset, lo, hi, tile=TILE):
    """Tile starts offset + k * stride inside [0, L - tile] that overlap [lo, hi). With lo and hi
    at least a tile from the ends, every pixel of [lo, hi) gets every tile of the infinite grid
    that covers it, as in a render of the whole segment."""
    if lo < tile or hi > L - tile:
        raise ValueError("the region needs a tile of margin on each side")
    return [p for p in range(offset, L - tile + 1, stride) if lo - tile < p < hi]


def to_input(xb):
    """villa's input from raw voxels: (B, tile, tile, C) uint8 to (B, C, tile, tile) float32,
    clipped to 0..CLIP and divided by CLIP (A.ToFloat(max_value=200) after np.clip)."""
    return np.minimum(xb, CLIP).astype(np.float32).transpose(0, 3, 1, 2) / CLIP


def render(arr, net, ys, xs, tile=TILE, batch=BATCH, valid=None, on_batch=None):
    """uint8 prediction of arr (H, W, C) uint8 from tiles at ys x xs. net maps raw voxels
    (B, tile, tile, C) uint8 to probabilities (B, tile, tile); the network wrapper does villa's
    input scaling (to_input, or the same on the GPU), the sigmoid and the resize. Per pixel, a voxel
    column with no nonzero value gets no weight (valid, computed here when not given); a batch with
    none at all is not forwarded, as villa skips it. Pixels no tile covers are 0."""
    H, W, _ = arr.shape
    if valid is None:
        valid = np.any(arr != 0, axis=-1)
    pred = np.zeros((H, W), np.float32)
    count = np.zeros((H, W), np.float32)
    wt = hann2d(tile, tile).astype(np.float32)
    pos = [(y, x) for y in ys for x in xs]
    stats = {"tiles": len(pos), "forwarded": 0}
    for i in range(0, len(pos), batch):
        part = pos[i:i + batch]
        v = [valid[y:y + tile, x:x + tile].astype(np.float32) for y, x in part]
        if any(m.any() for m in v):
            p = np.asarray(net(np.stack([arr[y:y + tile, x:x + tile] for y, x in part])), np.float32)
            stats["forwarded"] += len(part)
            for (y, x), pi, m in zip(part, p, v):
                pred[y:y + tile, x:x + tile] += pi * wt * m
                count[y:y + tile, x:x + tile] += wt * m
        if on_batch is not None:
            on_batch(min(i + batch, len(pos)), len(pos))
    out = np.clip(pred / np.clip(count, 1e-6, None), 0, 1)
    return (out * 255).astype(np.uint8), stats


def plan(L, lo, hi, strides=STRIDES, tile=TILE):
    """The renders in the order they run: (name, stride, offset). Stride 128 at offset 0 is the
    published tiling; its repeat measures the numerical noise; each stride is then rendered at
    offset 0 and at half a stride."""
    out = [("A128", 128, 0), ("R128", 128, 0), ("B128", 128, 64)]
    for s in strides:
        if s != 128:
            out += [(f"A{s}", s, 0), (f"B{s}", s, s // 2)]
    return [(n, s, o, len(axis_positions(L, s, o, lo, hi, tile)) ** 2) for n, s, o in out]


# ------------------------------------------------------------------ measuring
def rms(a, b, mask):
    d = np.asarray(a, np.float64)[mask] - np.asarray(b, np.float64)[mask]
    return float(np.sqrt(np.mean(d * d)))


def pearson(a, b, mask):
    a = np.asarray(a, np.float64)[mask]
    b = np.asarray(b, np.float64)[mask]
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / math.sqrt((a * a).sum() * (b * b).sum()))


def phase_profile(d, usable, period=PERIOD):
    """Mean |d| over usable pixels by position modulo period, rows and columns pooled: where in
    the 32 px repeat a tiling difference sits (reported, not part of the readout)."""
    a = np.abs(np.asarray(d, np.float64))
    u = np.asarray(usable, bool)
    s, n = np.zeros(period), np.zeros(period)
    ph = np.arange(a.shape[1]) % period
    np.add.at(s, ph, (a * u).sum(0))
    np.add.at(n, ph, u.sum(0))
    ph = np.arange(a.shape[0]) % period
    np.add.at(s, ph, (a * u).sum(1))
    np.add.at(n, ph, u.sum(1))
    return (s / np.maximum(n, 1)).round(4).tolist()


def verdict(published, maps, usable):
    """The preregistered readout. published: the organizers' pooled map over the region; maps:
    pooled renders by name (A128, R128, B128, A64, B64, A32, B32; missing ones were not run);
    usable: the region's usable mask. Units are 0..255 pooled values."""
    u = np.asarray(usable, bool)
    out = {"strides": {}}
    if not all(k in maps for k in ("A128", "R128", "B128")):
        out["void"] = "the stride-128 renders did not all run"
        out["line"] = "VOID: " + out["void"]
        return out
    noise = rms(maps["A128"], maps["R128"], u)
    out["noise"] = noise
    out["r_published"] = pearson(maps["A128"], published, u)
    out["rms_published"] = rms(maps["A128"], published, u)
    floor = DETECT * max(noise, FLOOR)
    for s in STRIDES:
        a, b = maps.get(f"A{s}"), maps.get(f"B{s}")
        if a is None or b is None:
            continue
        g = {"effect": rms(a, b, u), "r_stride128": pearson(a, maps["A128"], u),
             "profile": phase_profile(np.asarray(a, np.float64) - np.asarray(b, np.float64), u)}
        out["strides"][s] = g
    e128 = out["strides"][128]["effect"]
    if out["r_published"] < MIN_R:
        out["void"] = (f"the stride-128 render does not reproduce the published map "
                       f"(r {out['r_published']:.3f} < {MIN_R})")
    elif e128 <= floor:
        out["void"] = f"no tiling effect at stride 128 (RMS {e128:.3f}, noise {noise:.3f})"
    if "void" in out:
        out["line"] = "VOID: " + out["void"]
        return out
    parts = [f"stride 128: tiling effect RMS {e128:.3f} (noise {noise:.3f}, r with published {out['r_published']:.3f})"]
    for s in sorted(out["strides"], reverse=True):
        if s == 128:
            continue
        g = out["strides"][s]
        g["share"] = g["effect"] / e128
        g["status"] = ("gone" if g["effect"] <= floor else "reduced" if g["share"] <= REDUCED else "not reduced")
        g["content_kept"] = g["r_stride128"] >= MIN_R
        parts.append(f"stride {s}: {g['status']} (RMS {g['effect']:.3f}, {g['share']:.2f} of stride 128), "
                     f"r with stride 128 {g['r_stride128']:.3f}")
    missing = [s for s in STRIDES if s not in out["strides"]]
    if missing:
        parts.append("not run: stride " + ", ".join(map(str, missing)))
    out["line"] = "; ".join(parts)
    return out


def full_render_tiles(pooled_maps, stride, tile=TILE):
    """Tiles a full re-render would forward: for each map, the tiles at this stride that hold any
    nonzero pooled pixel (a 48 um pixel stands for 20 x 20 native px), summed."""
    total = 0
    for m in pooled_maps:
        nz = np.asarray(m) > 0
        H, W = nz.shape[0] * D.POOL, nz.shape[1] * D.POOL
        sat = np.pad(nz.astype(np.int64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        p = D.POOL
        ys, xs = np.array(grid_1d(H, tile, stride)), np.array(grid_1d(W, tile, stride))
        y0, y1 = ys // p, np.minimum((ys + tile + p - 1) // p, nz.shape[0])
        x0, x1 = xs // p, np.minimum((xs + tile + p - 1) // p, nz.shape[1])
        s = sat[y1][:, x1] - sat[y0][:, x1] - sat[y1][:, x0] + sat[y0][:, x0]
        total += int((s > 0).sum())
    return total


def projection(tiles_per_s, usd_per_h):
    """GPU hours and USD a full re-render would take at the measured rate, by stride."""
    out = {}
    for s, n in FULL_TILES.items():
        h = n / tiles_per_s / 3600
        out[s] = {"tiles": n, "gpu_hours": round(h, 1), "usd": round(h * usd_per_h)}
    return out


def dumps(obj):
    return json.dumps(obj, indent=1, default=float) + "\n"
