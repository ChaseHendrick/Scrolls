"""Show a volume on a sheet's surface in Neuroglancer: a tifxyz segment becomes a mesh whose vertices carry the
volume's value there, so a 3D ink prediction (or the CT itself) reads as a picture on the curved sheet.

Neuroglancer has no surface render of a volume, but its single-mesh layer draws a VTK mesh with per-vertex values
through a shader. This writes that mesh:

  build   SEGMENT --volume ZARR --out DIR: crop and thin the tifxyz grid, sample the volume along each vertex's
          normal (the max or mean over plus or minus --depth voxels, as a VC3D composite does), and write DIR/sheet.vtk
          (ASCII VTK polydata, the one format the layer reads), DIR/state.json and DIR/link.txt (a Neuroglancer state
          and link with the mesh, its shader and, for a bucket volume, the volume as a hidden image layer) and
          DIR/receipt.json (inputs, counts, value range, sha256 of the mesh)
  serve   DIR: serve DIR over http with CORS on 127.0.0.1 so the hosted Neuroglancer can load sheet.vtk, and print
          the link

Volume chunks the samples need are fetched once into --cache (only those chunks, as kit tifxyz chunks --fetch does).
Values are nearest-voxel samples of one pyramid level; the mesh shows them at its own vertex spacing, interpolated
across each triangle, so pick --stride and --upsample for the detail you need. An ink prediction is model output, not
a reading. Standard library plus numpy, tifffile and zarr.
"""

import argparse
import hashlib
import http.server
import json
import math
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from . import tifxyz
from .verify import VerifyError

VIEWER = "https://neuroglancer-demo.appspot.com/#!"
DEFAULT_CACHE = "work/sheetview/cache"
DEFAULT_PORT = 8000
MAX_VERTICES = 4_000_000       # ASCII VTK grows about 40 bytes a vertex; Neuroglancer parses it in the browser
ROW_BLOCK = 64                 # grid rows sampled at a time, to keep memory bounded
CHUNK_CACHE_BYTES = 1 << 30    # decoded chunks kept in memory while sampling
PALETTES = {"ink": ("#2a2017", "#ffd27a"), "gray": ("#000000", "#ffffff")}
_UM_OUT = {a: [1e-6, "m"] for a in ("x", "y", "z")}


def _np():
    return tifxyz._np()


def _zarr():
    try:
        import zarr
    except ImportError as exc:
        raise VerifyError("kit sheetview needs zarr to read the volume: pip install zarr") from exc
    return zarr


# ---------------------------------------------------------------- grid

def crop_grid(seg, crop=None, stride=1):
    """(xyz, valid) of the segment's grid rows r0:r1 and columns c0:c1, every stride-th node."""
    if stride < 1:
        raise VerifyError(f"--stride must be 1 or more (got {stride})")
    h, w = seg.shape
    r0, r1, c0, c1 = crop if crop else (0, h, 0, w)
    if not (0 <= r0 < r1 <= h and 0 <= c0 < c1 <= w):
        raise VerifyError(f"--crop {r0} {r1} {c0} {c1} is outside the grid of {h} rows and {w} columns")
    sl = (slice(r0, r1, stride), slice(c0, c1, stride))
    xyz, valid = seg.xyz[sl], seg.valid[sl]
    if valid.sum() < 4:
        raise VerifyError("the crop holds fewer than 4 valid nodes: nothing to draw")
    return xyz, valid


def upsample(xyz, valid, factor):
    """Bilinear refinement of the grid by an integer factor; a new node is valid when its cell's 4 corners are."""
    np = _np()
    if factor < 1:
        raise VerifyError(f"--upsample must be 1 or more (got {factor})")
    if factor == 1:
        return xyz, valid
    h, w = valid.shape
    if h < 2 or w < 2:
        raise VerifyError("--upsample needs a crop of at least 2 rows and 2 columns")
    r = np.arange((h - 1) * factor + 1) / factor
    c = np.arange((w - 1) * factor + 1) / factor
    r0 = np.minimum(np.floor(r).astype(int), h - 2)
    c0 = np.minimum(np.floor(c).astype(int), w - 2)
    fr, fc = (r - r0)[:, None, None], (c - c0)[None, :, None]
    R0, C0 = np.meshgrid(r0, c0, indexing="ij")
    q = xyz.copy()
    q[~valid] = 0.0
    out = ((1 - fr) * (1 - fc) * q[R0, C0] + (1 - fr) * fc * q[R0, C0 + 1]
           + fr * (1 - fc) * q[R0 + 1, C0] + fr * fc * q[R0 + 1, C0 + 1])
    ok = valid[R0, C0] & valid[R0, C0 + 1] & valid[R0 + 1, C0] & valid[R0 + 1, C0 + 1]
    return out, ok


def normals(xyz, valid):
    """Unit normals (column step cross row step, as kit tifxyz facing), NaN where a neighbor is missing."""
    np = _np()
    q = np.where(valid[..., None], xyz, np.nan)
    du = np.gradient(q, axis=1)
    dv = np.gradient(q, axis=0)
    n = np.cross(du, dv)
    norm = np.linalg.norm(n, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return n / norm


def triangles(valid):
    """(vertex index of each grid node or -1, (T, 3) triangles): two per cell whose 4 corners are valid."""
    np = _np()
    index = np.full(valid.shape, -1, np.int64)
    index[valid] = np.arange(int(valid.sum()))
    a, b, c, d = index[:-1, :-1], index[:-1, 1:], index[1:, :-1], index[1:, 1:]
    full = (a >= 0) & (b >= 0) & (c >= 0) & (d >= 0)
    t1 = np.stack([a[full], c[full], b[full]], -1)
    t2 = np.stack([b[full], c[full], d[full]], -1)
    return index, np.concatenate([t1, t2]).reshape(-1, 3)


# ---------------------------------------------------------------- volume

def _offsets(depth, factor):
    """Offsets along the normal in level-0 voxels: 0 and every step of one level voxel out to plus or minus depth."""
    np = _np()
    if not (depth >= 0 and math.isfinite(depth)):
        raise VerifyError(f"--depth must be 0 or more voxels (got {depth})")
    step = max(float(factor), 1.0)
    k = int(math.floor(depth / step + 1e-9))
    return np.arange(-k, k + 1, dtype=float) * step


def _sample_index(pts, nrm, offsets, factor):
    """(N, S, 3) integer z, y, x indices at the level for each point and offset; NaN normals sample offset 0 only."""
    np = _np()
    n = np.where(np.isfinite(nrm), nrm, 0.0)
    p = pts[:, None, :] + offsets[None, :, None] * n[:, None, :]            # x, y, z in level-0 voxels
    q = p[..., ::-1] / np.asarray(factor, float)                             # z, y, x at the level
    return np.rint(q).astype(np.int64)


class Volume:
    """One level of a local or bucket zarr volume, read chunk by chunk with a small in-memory cache."""

    def __init__(self, root, level=0, cache=DEFAULT_CACHE):
        self.src = tifxyz.ZarrSource(root)
        self.arr = tifxyz.zarr_level(self.src, level)
        self.level, self.root = level, str(root).rstrip("/")
        self.factor = [float(v) for v in self.arr["factor"]]
        self.chunks = [int(v) for v in self.arr["chunks"]]
        self.shape = [int(v) for v in self.arr["shape"]]
        self.local = Path(cache) / _cache_name(self.root) if self.src.remote else Path(self.root)
        self.fetched = {"chunks": 0, "bytes": 0, "absent": 0}
        self._data = None
        self._cache, self._cache_bytes = {}, 0

    def need(self, idx):
        """Unique chunk indices (M, 3) holding the in-bounds sample indices."""
        np = _np()
        flat = idx.reshape(-1, 3)
        inside = ((flat >= 0) & (flat < np.asarray(self.shape))).all(1)
        if not inside.any():
            return np.zeros((0, 3), np.int64)
        return np.unique(flat[inside] // np.asarray(self.chunks), axis=0)

    def fetch(self, chunk_ids):
        """Copy the given chunks (and the metadata) of a bucket volume into the cache; a local volume needs none."""
        if not self.src.remote or not len(chunk_ids):
            return
        keys = [tifxyz.chunk_key(self.arr, i) for i in chunk_ids]
        sizes = tifxyz._sizes(self.src, keys)
        written, _, nbytes = tifxyz.fetch_chunks(self.src, self.arr["levels"], keys, sizes, self.local)
        self.fetched["chunks"] += written
        self.fetched["bytes"] += nbytes
        self.fetched["absent"] += sum(1 for s in sizes if s is None)

    def _array(self):
        if self._data is None:
            zarr = _zarr()
            path = self.local / self.arr["path"] if self.arr["path"] else self.local
            try:
                self._data = zarr.open_array(str(path), mode="r")
            except Exception as exc:  # zarr raises several kinds for a folder it cannot open
                raise VerifyError(f"cannot open the volume level at {path}: {exc}") from exc
        return self._data

    def chunk(self, cid):
        np = _np()
        key = tuple(int(v) for v in cid)
        if key in self._cache:
            return self._cache[key]
        lo = [k * c for k, c in zip(key, self.chunks)]
        hi = [min(a + c, s) for a, c, s in zip(lo, self.chunks, self.shape)]
        block = np.asarray(self._array()[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]])
        while self._cache and self._cache_bytes + block.nbytes > CHUNK_CACHE_BYTES:
            old = self._cache.pop(next(iter(self._cache)))
            self._cache_bytes -= old.nbytes
        self._cache[key] = block
        self._cache_bytes += block.nbytes
        return block

    def sample(self, idx):
        """Values at integer (..., 3) z, y, x indices; NaN outside the volume."""
        np = _np()
        flat = idx.reshape(-1, 3)
        out = np.full(len(flat), np.nan, np.float32)
        inside = ((flat >= 0) & (flat < np.asarray(self.shape))).all(1)
        where = np.flatnonzero(inside)
        if len(where):
            cids = flat[where] // np.asarray(self.chunks)
            uniq, inv = np.unique(cids, axis=0, return_inverse=True)
            inv = inv.reshape(-1)
            for j, cid in enumerate(uniq):
                sel = where[inv == j]
                block = self.chunk(cid)
                local = flat[sel] - cid * np.asarray(self.chunks)
                out[sel] = block[local[:, 0], local[:, 1], local[:, 2]]
        return out.reshape(idx.shape[:-1])


def _cache_name(root):
    return hashlib.sha256(root.encode()).hexdigest()[:16] + "-" + Path(root.rstrip("/")).name


def sample_sheet(xyz, valid, volume, depth=0.0, reduce="max", row_block=ROW_BLOCK):
    """(H, W) float32 values of the volume on the sheet: the max or mean along each node's normal over plus or minus
    depth level-0 voxels; NaN at invalid nodes and where every sample is outside the volume."""
    np = _np()
    if reduce not in ("max", "mean"):
        raise VerifyError(f"--reduce must be max or mean (got {reduce})")
    nrm = normals(xyz, valid)
    offs = _offsets(depth, max(volume.factor))
    h = valid.shape[0]
    blocks = [(r, min(r + row_block, h)) for r in range(0, h, row_block)]
    need = []
    for r0, r1 in blocks:
        m = valid[r0:r1]
        need.append(volume.need(_sample_index(xyz[r0:r1][m], nrm[r0:r1][m], offs, volume.factor)))
    ids = np.unique(np.concatenate(need), axis=0) if any(len(n) for n in need) else np.zeros((0, 3), np.int64)
    volume.fetch(ids)
    out = np.full(valid.shape, np.nan, np.float32)
    for r0, r1 in blocks:
        m = valid[r0:r1]
        if not m.any():
            continue
        vals = volume.sample(_sample_index(xyz[r0:r1][m], nrm[r0:r1][m], offs, volume.factor))
        with warnings.catch_warnings():               # an all-NaN row (every sample outside) stays NaN
            warnings.simplefilter("ignore", RuntimeWarning)
            red = np.nanmax(vals, 1) if reduce == "max" else np.nanmean(vals, 1)
        block = out[r0:r1]
        block[m] = red
        out[r0:r1] = block
    return out, len(ids), len(offs)


# ---------------------------------------------------------------- outputs

def write_vtk(path, pts, tris, values, name="value", title="kit sheetview"):
    """ASCII VTK polydata with one SCALARS point attribute: the format Neuroglancer's vtk:// source reads."""
    np = _np()
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "w", encoding="ascii", newline="\n") as f:
        f.write(f"# vtk DataFile Version 3.0\n{title}\nASCII\nDATASET POLYDATA\n")
        f.write(f"POINTS {len(pts)} float\n")
        np.savetxt(f, pts, fmt="%.2f")
        f.write(f"POLYGONS {len(tris)} {4 * len(tris)}\n")
        np.savetxt(f, np.hstack([np.full((len(tris), 1), 3, np.int64), tris]), fmt="%d")
        f.write(f"POINT_DATA {len(pts)}\nSCALARS {name} float 1\nLOOKUP_TABLE default\n")
        np.savetxt(f, values.reshape(-1, 1), fmt="%.6g")
    tmp.replace(path)
    return path


def shader(name, lo, hi, vmin, vmax, palette="ink"):
    low, high = PALETTES[palette]
    return (f"#uicontrol float black slider(min={vmin:g}, max={vmax:g}, default={lo:g})\n"
            f"#uicontrol float white slider(min={vmin:g}, max={vmax:g}, default={hi:g})\n"
            f'#uicontrol vec3 low color(default="{low}")\n'
            f'#uicontrol vec3 high color(default="{high}")\n'
            "void main() {\n"
            f"  float v = clamp(({name} - black) / max(white - black, 1e-6), 0.0, 1.0);\n"
            "  emitRGB(mix(low, high, v));\n"
            "}\n")


def _quat(m):
    """Unit quaternion (x, y, z, w) of a 3 x 3 rotation matrix."""
    t = m[0][0] + m[1][1] + m[2][2]
    if t > 0:
        s = 2 * math.sqrt(t + 1)
        q = [(m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, s / 4]
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = 2 * math.sqrt(1 + m[0][0] - m[1][1] - m[2][2])
        q = [s / 4, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s]
    elif m[1][1] > m[2][2]:
        s = 2 * math.sqrt(1 + m[1][1] - m[0][0] - m[2][2])
        q = [(m[0][1] + m[1][0]) / s, s / 4, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s]
    else:
        s = 2 * math.sqrt(1 + m[2][2] - m[0][0] - m[1][1])
        q = [(m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, s / 4, (m[1][0] - m[0][1]) / s]
    norm = math.sqrt(sum(v * v for v in q)) or 1.0
    return [v / norm for v in q]


def face_on(du, dv):
    """The view orientation that shows the sheet as its flattened grid reads: grid columns to the right, rows down,
    looking along column step cross row step. du and dv are the mean steps along columns and rows (x, y, z)."""
    np = _np()
    ex = np.asarray(du, float)
    ex = ex / (np.linalg.norm(ex) or 1.0)
    ey = np.asarray(dv, float) - ex * float(np.dot(dv, ex))
    ey = ey / (np.linalg.norm(ey) or 1.0)
    ez = np.cross(ex, ey)
    return _quat(np.stack([ex, ey, ez], 1).tolist())


def build_state(mesh_url, voxel_um, pts, orientation, name, lo, hi, vmin, vmax, palette="ink", volume_url=None):
    """A Neuroglancer state: the sheet as a single-mesh layer on a micrometer grid, looked at face on, and the volume
    (a zarr2:// or zarr3:// source whose level 0 is in the segment's voxels) as a hidden image layer when given."""
    np = _np()
    centre = (pts.min(0) + pts.max(0)) / 2 * voxel_um
    extent = float((pts.max(0) - pts.min(0)).max() * voxel_um)
    scale = [voxel_um * 1e-6, "m"]
    layers = []
    if volume_url:
        layers.append({"type": "image", "name": "volume", "visible": False,
                       "source": {"url": volume_url, "transform": {
                           "inputDimensions": {a: list(scale) for a in ("x", "y", "z")},
                           "outputDimensions": {a: list(v) for a, v in _UM_OUT.items()}}}})
    layers.append({"type": "mesh", "name": "sheet",
                   "source": {"url": "vtk://" + mesh_url, "transform": {
                       "inputDimensions": {a: list(scale) for a in ("x", "y", "z")},
                       "outputDimensions": {a: list(v) for a, v in _UM_OUT.items()}}},
                   "shader": shader(name, lo, hi, vmin, vmax, palette)})
    return {"dimensions": {a: list(v) for a, v in _UM_OUT.items()},
            "position": [round(float(v), 2) for v in centre],
            "projectionOrientation": [round(float(v), 6) for v in orientation],
            "projectionScale": round(extent * 1.15, 1),
            "layers": layers, "layout": "3d", "showSlices": False, "showAxisLines": False,
            "showDefaultAnnotations": False, "selectedLayer": {"layer": "sheet"}}


def link(state):
    return VIEWER + quote(json.dumps(state, separators=(",", ":")), safe="")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build(segment, volume, out, level=0, crop=None, stride=1, factor=1, depth=0.0, reduce="max", name="value",
          palette="ink", base_url=None, cache=DEFAULT_CACHE, voxel_um=None, seg_cache=tifxyz.DEFAULT_CACHE,
          max_vertices=MAX_VERTICES):
    """Write sheet.vtk, state.json, link.txt and receipt.json into out; return the receipt."""
    np = _np()
    t0 = time.time()
    if palette not in PALETTES:
        raise VerifyError(f"--palette must be one of {', '.join(PALETTES)} (got {palette})")
    if not name.isidentifier():
        raise VerifyError(f"--name must be a plain identifier for the shader (got {name!r})")
    out = Path(out)
    seg = tifxyz.load(segment, seg_cache, voxel_um)
    xyz, valid = crop_grid(seg, crop, stride)
    xyz, valid = upsample(xyz, valid, factor)
    if int(valid.sum()) > max_vertices:
        raise VerifyError(f"{int(valid.sum())} vertices is above --max-vertices {max_vertices}: crop smaller or "
                          "raise --stride")
    vol = Volume(volume, level, cache)
    values, n_chunks, n_offsets = sample_sheet(xyz, valid, vol, depth, reduce)
    index, tris = triangles(valid)
    pts = xyz[valid]
    vals = values[valid]
    missing = ~np.isfinite(vals)
    fill = float(np.nanmin(vals)) if (~missing).any() else 0.0
    vals = np.where(missing, fill, vals).astype(np.float32)
    q = np.where(valid[..., None], xyz, np.nan)
    du, dv = np.nanmean(np.diff(q, axis=1), (0, 1)), np.nanmean(np.diff(q, axis=0), (0, 1))
    orientation = face_on(np.nan_to_num(du), np.nan_to_num(dv))
    lo, hi = (float(v) for v in np.percentile(vals, [1, 99.5])) if len(vals) else (0.0, 1.0)
    if hi <= lo:
        hi = lo + 1.0
    kind = np.dtype(vol.arr["dtype"])
    vmin, vmax = ((float(np.iinfo(kind).min), float(np.iinfo(kind).max)) if kind.kind in "ui"
                  else (min(lo, float(vals.min())), max(hi, float(vals.max()))))
    out.mkdir(parents=True, exist_ok=True)
    vtk = write_vtk(out / "sheet.vtk", pts, tris, vals, name)
    um = seg.voxel_um
    if not um:
        raise VerifyError("the voxel size is unknown: give --voxel-um (the segment's folder name has no -NNum)")
    mesh_url = (base_url.rstrip("/") + "/sheet.vtk") if base_url else f"http://127.0.0.1:{DEFAULT_PORT}/sheet.vtk"
    state = build_state(mesh_url, um, pts, orientation, name, lo, hi, vmin, vmax, palette,
                        (("zarr2://" if vol.arr["format"] == 2 else "zarr3://") + vol.src.base) if vol.src.remote
                        else None)
    (out / "state.json").write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    (out / "link.txt").write_text(link(state) + "\n", encoding="utf-8")
    rec = {"tool": "kit sheetview", "made": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "segment": seg.source, "segment_grid": list(seg.shape), "crop": list(crop) if crop else None,
           "stride": stride, "upsample": factor, "voxel_um": um,
           "volume": vol.root, "level": level, "level_factor_zyx": vol.factor, "depth_vox": depth,
           "samples_per_vertex": n_offsets, "reduce": reduce, "attribute": name,
           "vertices": int(len(pts)), "triangles": int(len(tris)),
           "vertices_outside_volume": int(missing.sum()), "chunks_read": n_chunks, "fetched": vol.fetched,
           "value_p1_p50_p99_5": [round(float(v), 4) for v in np.percentile(vals, [1, 50, 99.5])] if len(vals) else [],
           "shader_range": [round(lo, 4), round(hi, 4)], "mesh_url": mesh_url,
           "files": {"sheet.vtk": {"bytes": vtk.stat().st_size, "sha256": _sha256(vtk)}},
           "seconds": round(time.time() - t0, 1),
           "note": "values are model output or CT intensity sampled onto the sheet; an ink map is not a reading"}
    (out / "receipt.json").write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    return rec


# ---------------------------------------------------------------- serve

class _CORSHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):  # quiet; Neuroglancer asks often
        pass


def serve(folder, port=DEFAULT_PORT, host="127.0.0.1"):
    folder = Path(folder)
    if not (folder / "sheet.vtk").is_file():
        raise VerifyError(f"no sheet.vtk in {folder}: run kit sheetview build first")
    handler = lambda *a, **k: _CORSHandler(*a, directory=str(folder), **k)  # noqa: E731
    srv = http.server.ThreadingHTTPServer((host, port), handler)
    state_file = folder / "state.json"
    if state_file.is_file():
        state = json.loads(state_file.read_text())
        for layer in state.get("layers", []):
            if layer.get("type") == "mesh":
                layer["source"]["url"] = f"vtk://http://{host}:{srv.server_port}/sheet.vtk"
        print(link(state), flush=True)
    print(f"serving {folder} on http://{host}:{srv.server_port}/ (Ctrl-C stops)", file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


# ---------------------------------------------------------------- command line

def format_receipt(r, out):
    lines = [f"wrote {out}/sheet.vtk: {r['vertices']} vertices, {r['triangles']} triangles "
             f"({r['files']['sheet.vtk']['bytes'] / 1e6:.1f} MB)",
             f"  volume   {r['volume']} level {r['level']}, {r['samples_per_vertex']} samples per vertex "
             f"({r['reduce']} over +-{r['depth_vox']:g} voxels), {r['chunks_read']} chunks",
             f"  values   p1 {r['value_p1_p50_p99_5'][0]:g}  p50 {r['value_p1_p50_p99_5'][1]:g}  "
             f"p99.5 {r['value_p1_p50_p99_5'][2]:g}" if r["value_p1_p50_p99_5"] else "  values   none",
             f"  outside  {r['vertices_outside_volume']} vertices outside the volume",
             f"  view     python -m kit sheetview serve {out}   (then open the link it prints)"]
    return "\n".join(lines)


def add_arguments(p):
    sub = p.add_subparsers(dest="action", required=True)
    b = sub.add_parser("build", help="write a Neuroglancer mesh of a sheet with a volume sampled onto it")
    b.add_argument("segment", help="tifxyz folder, local or on the open-data bucket (https:// or s3://)")
    b.add_argument("--volume", required=True, help="zarr or OME-Zarr volume in the segment's voxels, local or bucket")
    b.add_argument("--out", required=True, help="output folder")
    b.add_argument("--level", type=int, default=0, help="pyramid level to sample (default 0)")
    b.add_argument("--crop", type=int, nargs=4, metavar=("R0", "R1", "C0", "C1"),
                   help="grid rows R0:R1 and columns C0:C1 of the tifxyz (default: all)")
    b.add_argument("--stride", type=int, default=1, help="keep every Nth grid node (default 1)")
    b.add_argument("--upsample", type=int, default=1, help="refine the grid N times bilinearly (default 1)")
    b.add_argument("--depth", type=float, default=0.0,
                   help="sample plus or minus this many level-0 voxels along the normal (default 0)")
    b.add_argument("--reduce", choices=("max", "mean"), default="max", help="how depth samples combine (default max)")
    b.add_argument("--name", default="value", help="the per-vertex attribute's name in the shader (default value)")
    b.add_argument("--palette", choices=sorted(PALETTES), default="ink",
                   help="ink: warm on dark papyrus; gray: black to white (default ink)")
    b.add_argument("--base-url", help=f"where sheet.vtk will be served (default http://127.0.0.1:{DEFAULT_PORT}/)")
    b.add_argument("--voxel-um", type=float, help="voxel size when the segment folder name lacks -NNum")
    b.add_argument("--cache", default=DEFAULT_CACHE, help=f"volume chunk cache (default {DEFAULT_CACHE})")
    b.add_argument("--seg-cache", default=tifxyz.DEFAULT_CACHE, help="tifxyz download cache")
    b.add_argument("--max-vertices", type=int, default=MAX_VERTICES,
                   help=f"refuse a mesh above this many vertices (default {MAX_VERTICES})")
    b.add_argument("--json", action="store_true", help="print the receipt as JSON")
    s = sub.add_parser("serve", help="serve a built folder with CORS for the hosted Neuroglancer and print the link")
    s.add_argument("folder")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)


def run(args):
    if args.action == "serve":
        return serve(args.folder, args.port)
    r = build(args.segment, args.volume, args.out, args.level, args.crop, args.stride, args.upsample, args.depth,
              args.reduce, args.name, args.palette, args.base_url, args.cache, args.voxel_um, args.seg_cache,
              args.max_vertices)
    print(json.dumps(r, indent=1) if args.json else format_receipt(r, args.out))
    return 0


def cmd_sheetview(args):
    """python -m kit sheetview build|serve: exit 0 when done, 2 on bad input."""
    try:
        return run(args)
    except VerifyError as exc:
        print(f"kit sheetview: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"kit sheetview could not read or write a file: {exc}", file=sys.stderr)
        return 2


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit.sheetview", description=__doc__.split("\n\n")[0])
    add_arguments(p)
    return cmd_sheetview(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
