"""Frame check: does a rendered surface volume sit in the frame of its mesh and its CT?

The rule is gpchain's (github.com/jo-tud/vesuvius-gpchain, MIT, `tools/gpchain/render_contract.py` `frame_check`,
read 27 Nov 2026 at 3733791), reimplemented with numpy only. A render pixel p of a tifxyz piece with grid scale s sits
at the piece's node (p + 0.5) * s (bilinear between the four nodes around it). The check samples `n` random pixels
whose four nodes are valid (seed fixed), takes the mean of the two middle render layers there, samples the CT
trilinearly at the same pixels' 3D positions, and asks for Pearson r >= `bar` (0.95) on the pixels where the render
has data. A rim gate goes with it: villa leaves the outer half node cell of a piece unrendered, so every render pixel
with no data (0 in every layer) must lie in the mask's edge band of width max(rim_px, ceil(rim_cells / s)) pixels,
and their share of mesh-valid pixels must not pass the band's own share.

What it catches: a render made from another scan or level, a wrong voxel size, a render shifted by a node cell,
another piece's render, a flipped or transposed render (on a villa spiral-fit piece of public PHerc0343: correct
r 0.9987; four planted errors 0.05 to 0.43). What it does not: sub-pixel registration (half a pixel off still gave
r 0.987) and whether the mesh follows one sheet. A pass is a contract check, not a result; nothing here is a reading.

`window` limits the sampled pixels to a centered square of that many render pixels, so only the CT chunks under it
are read (a whole 3 by 2.6 cm piece touched 411 chunks, 0.82 GB; a 768 px window a few dozen).

The CT is a zarr v2 level read chunk by chunk: an https URL, an s3:// URL on the open-data bucket, an open-data key
(`PHerc0343/volumes/...zarr`) or a local folder. The chunk getter is injectable (get(relpath) -> bytes or None), so
tests run with no network.
"""

import gzip
import json
import math
import threading
import time
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BAR = 0.95
N = 100_000
SEED = 3453
RIM_PX = 3
RIM_CELLS = 0.5


class FrameError(ValueError):
    pass


def _np():
    try:
        import numpy as np
    except ImportError as e:  # pragma: no cover - numpy is in every map environment
        raise FrameError("framecheck needs numpy") from e
    return np


OPEN_DATA = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
S3_PREFIX = "s3://vesuvius-challenge-open-data/"


def resolve_volume(volume):
    """The volume's base location: an https URL or a local folder."""
    v = str(volume or "").strip().rstrip("/")
    if not v:
        raise FrameError("no volume: pass --volume URL, open-data key or folder")
    if v.startswith(S3_PREFIX):
        return f"{OPEN_DATA}/{v[len(S3_PREFIX):]}"
    if v.startswith(("https://", "http://")):
        return v
    if Path(v).is_dir():
        return str(Path(v))
    if "/volumes/" in v and v.endswith(".zarr"):
        return f"{OPEN_DATA}/{v}"
    raise FrameError(f"volume {v!r} is not a URL, an open-data key or a folder")


def http_getter(base, timeout=120, tries=6, sleep=time.sleep):
    """get(relpath) -> bytes, or None for a missing chunk (HTTP 403 or 404); other errors are retried."""
    def get(rel):
        url = f"{base}/{rel}"
        last = None
        for i in range(tries):
            try:
                with urllib.request.urlopen(url, timeout=timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    return None
                last = e
            except (urllib.error.URLError, OSError) as e:
                last = e
            sleep(min(30, 2 * (i + 1)))
        raise FrameError(f"{url}: failed after {tries} tries ({last})")
    return get


def dir_getter(root):
    root = Path(root)

    def get(rel):
        p = root / rel
        return p.read_bytes() if p.is_file() else None
    return get


def getter_for(base):
    return dir_getter(base) if not base.startswith(("https://", "http://")) else http_getter(base)


def _decoder(comp):
    if comp is None:
        return lambda b: b
    cid = comp.get("id")
    if cid == "zlib":
        return zlib.decompress
    if cid == "gzip":
        return gzip.decompress
    try:
        import numcodecs
    except ImportError as e:
        raise FrameError(f"compressor {cid!r} needs numcodecs (pip install numcodecs)") from e
    codec = numcodecs.get_codec(comp)
    return lambda b: bytes(codec.decode(b))


def level_info(get, level):
    """The level's .zarray as {shape, chunks, dtype, sep, decode}; refuses what the sampler cannot read."""
    np = _np()
    raw = get(f"{level}/.zarray")
    if raw is None:
        raise FrameError(f"level {level}: no .zarray (the volume needs a zarr v2 multiscale with that level)")
    try:
        za = json.loads(raw)
    except ValueError as e:
        raise FrameError(f"level {level}: .zarray is not JSON ({e})") from e
    if za.get("zarr_format") != 2:
        raise FrameError(f"level {level}: zarr_format {za.get('zarr_format')!r}; only zarr v2 is read")
    if za.get("filters"):
        raise FrameError(f"level {level}: zarr filters are not supported")
    if za.get("order", "C") != "C":
        raise FrameError(f"level {level}: chunk order {za.get('order')!r}; only C order is read")
    shape, chunks = [int(s) for s in za["shape"]], [int(c) for c in za["chunks"]]
    if len(shape) != 3 or len(chunks) != 3:
        raise FrameError(f"level {level}: a 3-D (z, y, x) array is needed, got shape {shape}")
    return {"shape": shape, "chunks": chunks, "dtype": np.dtype(za["dtype"]),
            "sep": za.get("dimension_separator", "."), "decode": _decoder(za.get("compressor"))}


def load_piece(folder):
    """(grid (H, W, 3) float64 in x, y, z, valid mask, grid scale) of a tifxyz folder."""
    np = _np()
    folder = Path(folder)
    try:
        import tifffile
        arrs = [np.asarray(tifffile.imread(folder / f"{c}.tif"), np.float64) for c in "xyz"]
    except ImportError:
        from . import vc3d_io
        grids = [vc3d_io.read_tiff(folder / f"{c}.tif") for c in "xyz"]
        arrs = [np.asarray(gr.data, np.float64).reshape(gr.h, gr.w) for gr in grids]
    if len({a.shape for a in arrs}) != 1 or arrs[0].ndim != 2:
        raise FrameError(f"{folder}: x, y and z grids differ in size")
    g = np.stack(arrs, -1)
    v = np.all(np.isfinite(g), -1) & ~np.all(g == -1, -1) & (g[..., 2] >= 0)
    meta = json.loads((folder / "meta.json").read_text())
    s = float((meta.get("scale") or [0])[0])
    if not s > 0:
        raise FrameError(f"{folder}/meta.json: no positive scale")
    return g, v, s


def px_valid(v, shape, s, half=0.5):
    """Render pixels whose four surrounding nodes are valid; pixel p sits at node (p + half) * s."""
    np = _np()
    vv = v[:-1, :-1] & v[1:, :-1] & v[:-1, 1:] & v[1:, 1:]
    r = np.floor((np.arange(shape[0]) + half) * s).astype(int)
    c = np.floor((np.arange(shape[1]) + half) * s).astype(int)
    ok_r, ok_c = r < vv.shape[0], c < vv.shape[1]
    out = np.zeros(shape, bool)
    out[np.ix_(ok_r, ok_c)] = vv[np.ix_(r[ok_r], c[ok_c])]
    return out


def px_xyz(g, rr, cc, s, half=0.5):
    """(n, 3) x, y, z at render pixels (rr, cc), bilinear in the node grid at (p + half) * s."""
    np = _np()
    u, w = (rr + half) * s, (cc + half) * s
    i = np.clip(np.floor(u).astype(int), 0, g.shape[0] - 2)
    j = np.clip(np.floor(w).astype(int), 0, g.shape[1] - 2)
    fu, fw = (u - i)[:, None], (w - j)[:, None]
    return ((1 - fu) * (1 - fw) * g[i, j] + fu * (1 - fw) * g[i + 1, j] + (1 - fu) * fw * g[i, j + 1]
            + fu * fw * g[i + 1, j + 1])


def erode(mask, k):
    """Binary erosion by k steps of the 4-neighbor cross; outside the array counts as False."""
    np = _np()
    m = mask.copy()
    for _ in range(k):
        p = np.pad(m, 1, constant_values=False)
        m = p[1:-1, 1:-1] & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    return m


class ChunkVolume:
    """Trilinear samples of one level of a zarr v2 volume (local folder, URL or open-data key)
    with cval 0 outside and in missing chunks; chunks are kept in memory, fetched on `threads` threads."""

    def __init__(self, volume, level=0, threads=8, get=None):
        self.base = resolve_volume(volume)
        self.get = get or getter_for(self.base)
        self.info = level_info(self.get, level)
        self.level, self.threads = level, threads
        self.cache, self.lock = {}, threading.Lock()
        self.fetched = self.missing = 0

    def _chunk(self, key):
        np = _np()
        with self.lock:
            if key in self.cache:
                return self.cache[key]
        i = self.info
        sep = i["sep"]
        raw = self.get(f"{self.level}/{sep.join(str(k) for k in key)}")
        if raw is None:
            arr = None
        else:
            arr = np.frombuffer(i["decode"](raw), i["dtype"]).reshape(i["chunks"])
        with self.lock:
            self.cache[key] = arr
            self.fetched += 1
            self.missing += arr is None
        return arr

    def sample(self, xyz):
        """Trilinear CT at (n, 3) points in this level's x, y, z voxels."""
        np = _np()
        p = np.asarray(xyz, np.float64)[:, ::-1]           # z, y, x
        f = np.floor(p).astype(np.int64)
        t = p - f
        shape, ch = np.array(self.info["shape"]), np.array(self.info["chunks"])
        corners = [(dz, dy, dx) for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)]
        keys = set()
        for d in corners:
            q = f + d
            ok = np.all((q >= 0) & (q < shape), 1)
            keys |= set(map(tuple, (q[ok] // ch).tolist()))
        with ThreadPoolExecutor(self.threads) as ex:
            list(ex.map(self._chunk, sorted(keys)))
        out = np.zeros(len(p))
        for d in corners:
            q = f + d
            wgt = np.prod(np.where(np.array(d) == 1, t, 1 - t), 1)
            ok = np.all((q >= 0) & (q < shape), 1)
            val = np.zeros(len(p))
            kk = q // ch
            loc = q - kk * ch
            idx = np.nonzero(ok)[0]
            if len(idx):
                uk, inv = np.unique(kk[idx], axis=0, return_inverse=True)
                for n, k in enumerate(uk):
                    arr = self.cache.get(tuple(k.tolist()))
                    if arr is None:
                        continue
                    sel = idx[inv.ravel() == n]
                    l = loc[sel]
                    val[sel] = arr[l[:, 0], l[:, 1], l[:, 2]].astype(np.float64)
            out += wgt * val
        return out


def _pearson(a, b):
    np = _np()
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def check(piece, layers, volume, n=N, seed=SEED, bar=BAR, mid=None, window=None, rim_px=RIM_PX, rim_cells=RIM_CELLS,
          coord_scale=1.0, render_scale=1.0):
    """The frame check of one rendered piece. piece: tifxyz folder (or (grid, valid, scale)); layers: (L, H, W)
    array; volume: an object with sample(xyz) (ChunkVolume). mid: the two layers averaged (default the middle two).
    coord_scale multiplies the mesh coordinates first (2 ** -level for a level-0 mesh on level `level`); render_scale
    is the render's output pixels per voxel (vc_render_tifxyz --scale), so a pixel sits at node (p + 0.5) * s / k."""
    np = _np()
    g, v, s = load_piece(piece) if not isinstance(piece, tuple) else piece
    s = s / float(render_scale)
    V = np.asarray(layers)
    if V.ndim != 3 or V.shape[0] < 2:
        raise FrameError(f"layers: a (layers, rows, cols) stack of at least 2 layers is needed, got {V.shape}")
    L = V.shape[0]
    mid = list(mid) if mid is not None else [L // 2 - 1, L // 2]
    if len(mid) != 2 or not all(0 <= m < L for m in mid):
        raise FrameError(f"mid {mid}: two layer indices in 0..{L - 1}")
    ok = px_valid(v, V.shape[1:], s)
    if not ok.any():
        raise FrameError("no render pixel has four valid nodes: the render's shape does not match the piece")
    nodata = ok & (V == 0).all(0)
    width = max(int(rim_px), int(math.ceil(round(rim_cells / s, 6))))
    edge = ok & ~erode(ok, width)
    rim_share = float(nodata.sum() / ok.sum())
    band_share = float(edge.sum() / ok.sum())
    at_edge = float((nodata & edge).sum() / nodata.sum()) if nodata.any() else 1.0
    pick = ok.copy()
    if window:
        h, w = V.shape[1:]
        r0, c0 = max(0, (h - window) // 2), max(0, (w - window) // 2)
        box = np.zeros_like(ok)
        box[r0:r0 + window, c0:c0 + window] = True
        pick &= box
        if not pick.any():
            raise FrameError(f"window {window}: no mesh-valid pixel in the centered window")
    rr, cc = np.nonzero(pick)
    rng = np.random.default_rng(seed)
    k = rng.choice(len(rr), min(int(n), len(rr)), replace=False)
    rr, cc = rr[k], cc[k]
    m = np.mean([V[k][rr, cc].astype(np.float64) for k in mid], 0)   # the middle layers' mean
    d = ~nodata[rr, cc]
    x = volume.sample(px_xyz(g, rr, cc, s, 0.5) * coord_scale)
    x0 = volume.sample(px_xyz(g, rr, cc, s, 0.0) * coord_scale)
    r = _pearson(x[d], m[d])
    passed = bool(r == r and r >= bar and rim_share <= band_share and at_edge == 1.0)
    return {"schema": "scrolls-framecheck/1", "rule": "gpchain frame_check (render_contract.py at 3733791), numpy port",
            "render_shape": list(V.shape), "nodes": list(v.shape), "scale": s, "mid_layers": mid,
            "window": window, "n_sampled": int(len(rr)), "n": int(d.sum()), "seed": seed, "r": r, "bar": bar,
            "rim": {"share": rim_share, "band_share": band_share, "at_edge": at_edge, "px": width,
                    "rim_px": rim_px, "rim_cells": rim_cells},
            "reading": {"r_all_px": _pearson(x, m), "r_half_px_off_data_px": _pearson(x0[d], m[d])},
            "chunks": {"fetched": getattr(volume, "fetched", None), "missing": getattr(volume, "missing", None)},
            "ok": passed,
            "note": "contract check of render, mesh and CT frames; not a check that the mesh follows one sheet, "
                    "and not a reading"}


def load_layers(path):
    """A render stack: a .npy file, or an OME-Zarr folder (its level 0) or zarr array (needs zarr)."""
    np = _np()
    p = Path(path)
    if p.suffix == ".npy":
        return np.load(p, mmap_mode="r")
    try:
        import zarr
    except ImportError as e:
        raise FrameError(f"{p}: reading a zarr render needs the zarr package") from e
    z = zarr.open(str(p), mode="r")
    if hasattr(z, "shape"):
        return np.asarray(z[:])
    if "0" in z:
        return np.asarray(z["0"][:])
    raise FrameError(f"{p}: neither a zarr array nor an OME-Zarr group with level 0")


def build_parser(ap):
    ap.add_argument("piece", help="the tifxyz folder the render was made from")
    ap.add_argument("layers", help="the render: layers.zarr (OME-Zarr), a zarr array or a .npy stack")
    ap.add_argument("--volume", required=True, help="the CT the render sampled: URL, open-data key or folder")
    ap.add_argument("--level", type=int, default=0, help="the volume level the render sampled (default 0)")
    ap.add_argument("--render-scale", type=float, default=1.0,
                    help="the render's output pixels per voxel (vc_render_tifxyz --scale; default 1)")
    ap.add_argument("--n", type=int, default=N, help=f"pixels sampled (default {N})")
    ap.add_argument("--seed", type=int, default=SEED, help=f"sampling seed (default {SEED})")
    ap.add_argument("--bar", type=float, default=BAR, help=f"pass at Pearson r of at least this (default {BAR})")
    ap.add_argument("--mid", type=int, nargs=2, help="the two layers averaged (default the middle two)")
    ap.add_argument("--window", type=int, help="sample only a centered square of this many render pixels")
    ap.add_argument("--threads", type=int, default=8, help="chunk fetch threads (default 8)")
    ap.add_argument("--out", help="also write the result JSON here")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    return ap


def cmd_framecheck(a):
    try:
        vol = ChunkVolume(a.volume, a.level, a.threads)
        res = check(a.piece, load_layers(a.layers), vol, n=a.n, seed=a.seed, bar=a.bar, mid=a.mid, window=a.window,
                    coord_scale=2.0 ** -a.level, render_scale=a.render_scale)
    except Exception as e:  # noqa: BLE001 - every refusal is one line and exit 2
        print(f"framecheck: {type(e).__name__}: {e}")
        return 2
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"framecheck: {'PASS' if res['ok'] else 'FAIL'} r {res['r']:.4f} (bar {res['bar']}) on {res['n']} px; "
              f"rim {res['rim']['share']:.4f} of mesh px, band {res['rim']['band_share']:.4f}, "
              f"at edge {res['rim']['at_edge']:.3f}; chunks {res['chunks']['fetched']}")
    return 0 if res["ok"] else 1


def main(argv=None):
    import argparse
    ap = build_parser(argparse.ArgumentParser(prog="python -m kit.framecheck", description=__doc__.split("\n")[0]))
    return cmd_framecheck(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
