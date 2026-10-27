"""A fast lasagna preview: the student over a region of a scan, written in villa's field layout (NAME.lasagna.json,
NAME_{cos,grad_mag,nx,ny}.ome.zarr: cos at scaledown 2, the others at 4, coarser levels where the region is aligned
to their chunks), so whatever reads a published lasagna field can read it. Model output, a preview of the teacher's
field; never a replacement for villa's own field where exact values matter.

  python scripts/lasagnetta/preview.py --checkpoint release --ct CT_LEVEL_DIR --region Z0 Z1 Y0 Y1 X0 X1 \
      --out DIR --name NAME [--self-check] [--input-level 0] [--base-shape Z Y X] [--tile 256 | --tile Z Y X]
      [--batch N] [--device cuda] [--pyramid auto|gpu|cpu] [--no-stream]

--checkpoint release uses the released average (Hugging Face SharpMeow/lasagnetta) and its recipe. --self-check
first scores it against villa's net on a few spots of the region (selfcheck.py) and exits 3, writing no field, when
the agreement is too low, so the caller can run villa's predict3d instead.

--ct is the zarr v2 folder of the CT level the student reads (a local folder, or s3://BUCKET/... on the open-data
bucket through HTTPS). The region is in that level's voxels and is rounded out to multiples of 128. Tiles of 256
(--tile: one size or Z Y X sizes, each a multiple of 32) keep their middle (32 voxels of context each side) and step
by that middle, so tiles never blend.

Speed: CT chunks are read in parallel threads; the GPU skips empty tiles from one check per slab; each batch's
products copy back to the host while the next batch runs; the finest level's chunks are written while later tiles
run (--no-stream waits for the end); the coarser levels are pooled on the GPU when there is one (--pyramid cpu: numpy,
byte for byte as 0.1.0).
"""
import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lgcommon as C  # noqa: E402
import lasnet as M  # noqa: E402

TILE, CORE, MARGIN = 256, 192, 32
ALIGN = 128
CHUNK = 32
BLOSC = {"id": "blosc", "cname": "lz4", "clevel": 5, "shuffle": 1, "blocksize": 0}
GROUPS = ("cos", "grad_mag", "nx", "ny")
SD = {"cos": 2, "grad_mag": 4, "nx": 4, "ny": 4}          # each product's scaledown from the input level


# The released average (Hugging Face SharpMeow/lasagnetta): three students, one plain forward each, then a 0.5 voxel
# cos blur and a 0.04 cos offset. --checkpoint release fetches it and sets that recipe.
RELEASE = {"repo": "SharpMeow/lasagnetta", "files": ["lasagnetta-l32n.pt", "lasagnetta-xl.pt", "lasagnetta-w24.pt"],
           "cos_blur": [0.5, 0.5, 0.5], "cos_offset": 0.04}


def usable_cpus(cgroup="/sys/fs/cgroup"):
    """The CPUs this process may use: its cgroup quota when one is set, since os.cpu_count() gives the host's (a
    cloud GPU container can report far more CPUs than its quota)."""
    n = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 8)
    for path, parse in ((Path(cgroup) / "cpu.max", lambda t: t.split()),
                        (Path(cgroup) / "cpu" / "cpu.cfs_quota_us", None)):
        try:
            if parse:
                quota, period = parse(path.read_text())
            else:
                quota, period = path.read_text().strip(), (path.parent / "cpu.cfs_period_us").read_text().strip()
            if quota not in ("max", "-1") and int(period) > 0:
                n = min(n, max(1, math.ceil(int(quota) / int(period))))
                break
        except (OSError, ValueError):
            continue
    return n


def resolve(a, dest=Path.home() / ".cache" / "lasagnetta"):
    """--checkpoint release: download the released files (once) and use the released recipe."""
    if a.checkpoint != "release":
        return a
    from huggingface_hub import hf_hub_download
    a.checkpoint = ",".join(str(hf_hub_download(RELEASE["repo"], f, local_dir=str(dest))) for f in RELEASE["files"])
    a.cos_blur, a.cos_offset = list(RELEASE["cos_blur"]), RELEASE["cos_offset"]
    return a


def load(checkpoint, device):
    """One student, or an ensemble (lasnet.Ensemble) from checkpoint paths joined by commas; returns (net, config)."""
    paths = str(checkpoint).split(",")
    nets, configs = [], []
    for path in paths:
        ck = torch.load(path, map_location="cpu", weights_only=True)      # config, steps and tensors only
        net = M.build(ck["config"])
        net.load_state_dict(ck["state_dict"])
        net = net.to(device).eval()
        if device.type == "cuda":
            net = net.to(memory_format=torch.channels_last_3d)
        nets.append(net)
        configs.append(ck["config"])
    if len(nets) == 1:
        return nets[0], configs[0]
    return M.Ensemble(nets).eval(), "ens(" + ",".join(configs) + ")"


def source(ct):
    if ct.startswith("s3://"):
        prefix = ct.split("/", 3)[3]
        meta = C.zarray(prefix)
        sep = meta.get("dimension_separator", ".")
        return meta, (lambda key: C.http_get(f"{prefix}/{sep.join(map(str, key))}"))
    return C.local_zarr(ct)


def round_region(region, shape):
    out = []
    for (a, b), n in zip(region, shape):
        a = max(0, a // ALIGN * ALIGN)
        b = min(n, -(-b // ALIGN) * ALIGN)
        out.append((a, b))
    return tuple(out)


def positions(a, b, core=CORE, margin=MARGIN):
    """Tile origins along one axis so the cores [p + margin, p + margin + core) cover [a, b)."""
    ps, p = [], a - margin
    while p + margin < b:
        ps.append(p)
        p += core
    return ps


@torch.no_grad()
def finalize(maps):
    """lasnet.to_maps or predict_maps maps to stored uint8 products (villa's encodings: cos * 255, grad_mag as
    trained, nx and ny at 127 * n + 128 with n flipped so nz >= 0)."""
    cos = (maps["cos"].float() * 255.0).round().clamp(0, 255).to(torch.uint8)
    gm = (maps["gm"].float() * 255.0).round().clamp(0, 255).to(torch.uint8)
    n = F.normalize(maps["normal"].float(), dim=1, eps=1e-6)        # components (x, y, z)
    n = n * torch.where(n[:, 2:3] < 0, -1.0, 1.0)
    enc = lambda c: (c * 127.0 + 128.0).round().clamp(0, 255).to(torch.uint8)
    return cos[:, 0], gm[:, 0], enc(n[:, 0]), enc(n[:, 1])


@torch.no_grad()
def run(net, meta, get, region, device, batch=0, log=print, flips=((),), cos_blur=(0, 0, 0), cos_offset=0.0,
        tile=TILE, margin=MARGIN, on_rows=None, stats=None):
    """The products over the region: cos (region / 2), grad_mag, nx, ny (region / 4), uint8, and the tile count.
    flips and cos_blur are the inference recipe (lasnet.predict_maps, with cos_offset), applied per tile before its
    core is kept. tile is one size or (z, y, x) sizes. on_rows(res, z) is called each time rows [0, z) of the region
    (input-level voxels) are final, last with z = the region's depth. stats, a dict, gets seconds spent waiting on CT
    reads, uploading slabs, waiting on the GPU and placing cores."""
    tile = tuple(tile) if isinstance(tile, (list, tuple)) else (tile,) * 3
    core = tuple(t - 2 * margin for t in tile)
    if any(t % 32 or c <= 0 or c % 4 for t, c in zip(tile, core)) or margin % 4:
        raise SystemExit(f"tile {tile}: each a multiple of 32, with a core past 2 x {margin} a multiple of 4")
    batch = batch or max(1, round(4 * TILE ** 3 / math.prod(tile)))
    cuda = device.type == "cuda"
    size = [b - a for a, b in region]
    res = {"cos": np.zeros([s // 2 for s in size], np.uint8)}
    for k in ("grad_mag", "nx", "ny"):
        res[k] = np.zeros([s // 4 for s in size], np.uint8)
    pz, py, px = (positions(a, b, c, margin) for (a, b), c in zip(region, core))
    ybox = (py[0], py[-1] + tile[1])
    xbox = (px[0], px[-1] + tile[2])
    read_pool = ThreadPoolExecutor(max(4, usable_cpus()))
    st = dict.fromkeys(("read_wait_s", "upload_s", "gpu_wait_s", "place_s"), 0.0)
    cut = [tuple(slice(margin // SD[g], (margin + c) // SD[g]) for c in core) for g in GROUPS]
    host = None
    if cuda:                          # two pinned sets, so one batch copies back while the one before is placed
        host = [[torch.empty((batch,) + tuple(c // SD[g] for c in core), dtype=torch.uint8, pin_memory=True)
                 for g in GROUPS] for _ in range(2)]
    pending = []

    def read(z):
        arr, _ = C.read_box_from(meta, get, ((z, z + tile[0]), ybox, xbox), read_pool)
        return arr

    def place(p, prods):
        """One tile's cores into the region arrays, clipped to the region."""
        for name, arr in zip(GROUPS, prods):
            sd = SD[name]
            src, dst = [], []
            for d, q in enumerate(p):
                c0 = q + margin
                lo, hi = max(c0, region[d][0]), min(c0 + core[d], region[d][1])
                src.append(slice((lo - c0) // sd, (hi - c0) // sd))
                dst.append(slice((lo - region[d][0]) // sd, (hi - region[d][0]) // sd))
            res[name][tuple(dst)] = arr[tuple(src)]

    def drain(keep=0):
        while len(pending) > keep:
            ev, z, part, arrs = pending.pop(0)
            t = time.perf_counter()
            if ev is not None:
                ev.synchronize()
            st["gpu_wait_s"] += time.perf_counter() - t
            t = time.perf_counter()
            for b, (y, x) in enumerate(part):
                place((z, y, x), [a[b] for a in arrs])
            st["place_s"] += time.perf_counter() - t

    ahead = ThreadPoolExecutor(1)
    nxt = ahead.submit(read, pz[0])
    tiles = issued = 0
    for i, z in enumerate(pz):
        t = time.perf_counter()
        slab = nxt.result()
        st["read_wait_s"] += time.perf_counter() - t
        if i + 1 < len(pz):
            nxt = ahead.submit(read, pz[i + 1])
        t = time.perf_counter()
        g = torch.from_numpy(slab).to(device)
        view = lambda y, x: g[:, y - ybox[0]:y - ybox[0] + tile[1], x - xbox[0]:x - xbox[0] + tile[2]]
        coords = [(y, x) for y in py for x in px]
        occupied = torch.stack([view(y, x).amax() for y, x in coords]).cpu().tolist()
        coords = [c for c, o in zip(coords, occupied) if o > 0]     # no CT: leave fill, as predict3d skips them
        st["upload_s"] += time.perf_counter() - t
        if i:
            drain()
            if on_rows:
                on_rows(res, min(size[0], max(0, z + margin - region[0][0])))
        for j in range(0, len(coords), batch):
            part = coords[j:j + batch]
            xb = torch.stack([view(y, x) for y, x in part])[:, None].float().div_(255.0)
            if cuda:
                xb = xb.contiguous(memory_format=torch.channels_last_3d)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=cuda):
                maps = M.predict_maps(net, xb, flips, cos_blur, cos_offset)
            prods = [p[(slice(None),) + c].contiguous() for p, c in zip(finalize(maps), cut)]
            if cuda:
                bufs = [h[:len(part)] for h in host[issued % 2]]
                for h, p in zip(bufs, prods):
                    h.copy_(p, non_blocking=True)
                ev = torch.cuda.Event()
                ev.record()
                pending.append((ev, z, part, [h.numpy() for h in bufs]))
            else:
                pending.append((None, z, part, [p.numpy() for p in prods]))
            issued += 1
            drain(1)
            tiles += len(part)
        log(f"slab {i + 1}/{len(pz)}: {tiles} tiles so far")
    drain()
    if on_rows:
        on_rows(res, size[0])
    read_pool.shutdown(); ahead.shutdown()
    if stats is not None:
        stats.update({k: round(v, 2) for k, v in st.items()})
    return res, tiles


def pool2(a, kind):
    """One pyramid step (2x mean; normals by the principal axis of the mean outer product)."""
    d = [s // 2 for s in a.shape[-3:]]
    if kind == "scalar":
        b = a[:d[0] * 2, :d[1] * 2, :d[2] * 2].astype(np.float32).reshape(d[0], 2, d[1], 2, d[2], 2)
        return np.round(b.mean(axis=(1, 3, 5))).astype(np.uint8)
    nx, ny = a
    n = C.decode_normal(nx, ny)[:, :d[0] * 2, :d[1] * 2, :d[2] * 2]
    n = n.reshape(3, d[0], 2, d[1], 2, d[2], 2)
    outer = np.einsum("i...,j...->...ij", n, n).mean(axis=(1, 3, 5))      # (z, y, x, 3, 3)
    w, v = np.linalg.eigh(outer)
    p = np.moveaxis(v[..., :, -1], -1, 0)
    return np.stack(C.encode_normal(p))


def pool2_par(a, kind, pool):
    """pool2 over slabs of 16 output z rows in parallel; the same bytes as pool2 (each 2x2x2 block is pooled on its
    own, and numpy's eigh and mean loops release the GIL)."""
    n = a.shape[-3] // 2
    if n <= 16:
        return pool2(a, kind)
    def part(z):
        return pool2(a[..., 2 * z:2 * min(n, z + 16), :, :], kind)
    return np.concatenate(list(pool.map(part, range(0, n, 16))), axis=-3)


def principal_axis(a, batch=1 << 16):
    """The unit eigenvector of the largest eigenvalue of each symmetric 3x3 of a (k, 3, 3), in batches (cuSOLVER's
    batched solver refuses millions at once)."""
    return torch.cat([torch.linalg.eigh(a[s:s + batch]).eigenvectors[..., :, -1] for s in range(0, a.shape[0], batch)])


@torch.no_grad()
def pool2_torch(t, kind, rows=32):
    """pool2 on a uint8 torch tensor, on its device, in slabs of `rows` output z rows. Scalars give the same bytes
    as pool2 (a mean of 8 integers is exact in float32, and both round half to even). Normals take the same principal
    axis from torch.linalg.eigh, which can differ from numpy's by one uint8 step where float rounding lands on a .5,
    and anywhere the two largest eigenvalues tie."""
    d = [s // 2 for s in t.shape[-3:]]
    if kind == "scalar":
        out = torch.empty(d, dtype=torch.uint8, device=t.device)
        for z0 in range(0, d[0], rows):
            z1 = min(d[0], z0 + rows)
            part = t[None, None, 2 * z0:2 * z1, :2 * d[1], :2 * d[2]].float()
            out[z0:z1] = torch.round(F.avg_pool3d(part, 2)[0, 0]).to(torch.uint8)
        return out
    out = torch.empty((2, *d), dtype=torch.uint8, device=t.device)
    pairs = ((0, 0), (0, 1), (0, 2), (1, 1), (1, 2), (2, 2))
    full = (0, 1, 2, 1, 3, 4, 2, 4, 5)                              # the 3x3 matrix from its 6 unique entries
    for z0 in range(0, d[0], rows):
        z1 = min(d[0], z0 + rows)
        part = t[:, 2 * z0:2 * z1, :2 * d[1], :2 * d[2]].float()
        nx, ny = (part[0] - 128.0) / 127.0, (part[1] - 128.0) / 127.0
        nz = torch.sqrt(torch.clamp(1.0 - nx * nx - ny * ny, 0.0, 1.0))
        n = torch.stack([nx, ny, nz])
        n = n / (torch.linalg.vector_norm(n, dim=0, keepdim=True) + 1e-8)
        m = F.avg_pool3d(torch.stack([n[i] * n[j] for i, j in pairs])[None], 2)[0]   # (6, z, y, x)
        a = m.reshape(6, -1)[list(full)].T.reshape(-1, 3, 3)
        v = principal_axis(a)                                                       # (k, 3)
        v = v / (torch.linalg.vector_norm(v, dim=1, keepdim=True) + 1e-8)
        v = v * torch.where(v[:, 2:3] < 0, -1.0, 1.0)
        enc = torch.clamp(torch.round(v[:, :2] * 127.0 + 128.0), 0, 255).to(torch.uint8)
        out[:, z0:z1] = enc.T.reshape(2, z1 - z0, d[1], d[2])
    return out


class LevelWriter:
    """One zarr v2 level, chunks 32 and blosc lz4 as villa writes them, holding only the region's chunks."""

    def __init__(self, root, level, region_out, full_shape):
        from numcodecs import get_codec
        self.codec = get_codec(BLOSC)
        self.d = Path(root) / str(level)
        self.d.mkdir(parents=True, exist_ok=True)
        (self.d / ".zarray").write_text(json.dumps({
            "shape": list(full_shape), "chunks": [CHUNK] * 3, "dtype": "|u1", "fill_value": 0, "order": "C",
            "filters": None, "dimension_separator": "/", "compressor": BLOSC, "zarr_format": 2}, indent=1))
        self.o = [a for a, _ in region_out]

    def chunk(self, arr, i, j, k):
        """Write the chunk whose corner is voxel (i, j, k) of the region's array: 1, or 0 when it is all fill."""
        block = np.zeros((CHUNK,) * 3, np.uint8)
        part = arr[i:i + CHUNK, j:j + CHUNK, k:k + CHUNK]
        block[:part.shape[0], :part.shape[1], :part.shape[2]] = part
        if not block.any():
            return 0
        key = [(self.o[0] + i) // CHUNK, (self.o[1] + j) // CHUNK, (self.o[2] + k) // CHUNK]
        f = self.d / "/".join(map(str, key))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(self.codec.encode(np.ascontiguousarray(block)))
        return 1

    def submit_rows(self, pool, arr, i0, i1):
        """Futures writing every chunk of array rows [i0, i1) (i0 and i1 on the chunk grid, or i1 the end)."""
        return [pool.submit(self.chunk, arr, i, j, k) for i in range(i0, i1, CHUNK)
                for j in range(0, arr.shape[1], CHUNK) for k in range(0, arr.shape[2], CHUNK)]


def write_level(root, level, arr, region_out, full_shape, pool=None):
    """One whole level. With a pool, returns the chunk futures (each 1 if written) instead of waiting."""
    lw = LevelWriter(root, level, region_out, full_shape)
    if pool is not None:
        return lw.submit_rows(pool, arr, 0, arr.shape[0])
    with ThreadPoolExecutor(16) as own:
        return sum(f.result() for f in lw.submit_rows(own, arr, 0, arr.shape[0]))


class FieldWriter:
    """The field in villa's layout. Array level L has scale 2**L of the scan's level 0; the student read input level
    input_level, so cos lands at L = input_level + 1 and the rest at input_level + 2. rows(res, z) queues the finest
    level's chunks lying in rows [0, z) of the region (input-level voxels) once they are final; finish(res) queues
    the rest, pools the coarser levels (each pyramid once, the normal's serving nx and ny; with torch on `device`
    when it is CUDA, else numpy in parallel slabs), writes the metadata and waits. Every chunk goes through one
    thread pool."""

    def __init__(self, out, name, region, input_level, base_shape, levels=4, workers=None, device=None):
        self.out, self.name, self.region = Path(out), name, region
        self.out.mkdir(parents=True, exist_ok=True)
        self.input_level, self.base_shape, self.levels = input_level, list(base_shape), levels
        self.base = 2 ** input_level
        self.device = device
        self.pool = ThreadPoolExecutor(workers or max(8, 2 * usable_cpus()))
        self.futures, self.writers = {}, {}
        self.queued = dict.fromkeys(GROUPS, 0)              # finest-level rows queued, per product
        self.plans = {g: self.kept_levels(input_level + (1 if g == "cos" else 2)) for g in GROUPS}

    def kept_levels(self, first):
        """The levels written: the first, then each coarser one while the region sits on its chunk lines."""
        lv = []
        for lvl in range(first, self.levels + 1):
            reg = [(a * self.base // 2 ** lvl, b * self.base // 2 ** lvl) for a, b in self.region]
            if any(a % CHUNK for a, _ in reg) or (lvl > first and any((b - a) % CHUNK for a, b in reg)):
                break                                   # region not on this level's chunk lines
            lv.append((lvl, reg))
        return lv

    def level(self, group, lvl, reg):
        if (group, lvl) not in self.writers:
            s = 2 ** lvl
            self.writers[group, lvl] = LevelWriter(self.out / f"{self.name}_{group}.ome.zarr", lvl, reg,
                                                   [-(-n // s) for n in self.base_shape])
        return self.writers[group, lvl]

    def queue(self, group, lvl, reg, arr, i0, i1):
        if i1 > i0:
            fs = self.level(group, lvl, reg).submit_rows(self.pool, arr, i0, i1)
            self.futures.setdefault(f"{group}/{lvl}", []).extend(fs)

    def rows(self, res, z):
        depth = self.region[0][1] - self.region[0][0]
        for g in GROUPS:
            if not self.plans[g]:
                continue
            arr = res[g]
            end = arr.shape[0] if z >= depth else z // SD[g] // CHUNK * CHUNK
            lvl, reg = self.plans[g][0]
            self.queue(g, lvl, reg, arr, self.queued[g], end)
            self.queued[g] = max(self.queued[g], end)

    def pyramid(self, arr, kind, n):
        """n coarser levels of arr (uint8), each a 2x pool of the one before."""
        if n <= 0:
            return []
        if self.device is not None and self.device.type == "cuda":
            t, out = torch.from_numpy(np.ascontiguousarray(arr)).to(self.device), []
            for _ in range(n):
                t = pool2_torch(t, kind)
                out.append(t.cpu().numpy())
            return out
        out, cur = [], arr
        with ThreadPoolExecutor(max(4, usable_cpus())) as compute:
            for _ in range(n):
                cur = pool2_par(cur, kind, compute)
                out.append(cur)
        return out

    def finish(self, res):
        self.rows(res, self.region[0][1] - self.region[0][0])
        for kind, groups in (("scalar", ("cos",)), ("scalar", ("grad_mag",)), ("normal", ("nx", "ny"))):
            lv = self.plans[groups[0]]
            arr = res[groups[0]] if kind == "scalar" else np.stack([res["nx"], res["ny"]])
            for (lvl, reg), p in zip(lv[1:], self.pyramid(arr, kind, len(lv) - 1)):
                for gi, g in enumerate(groups):
                    cur = p if kind == "scalar" else p[gi]
                    self.queue(g, lvl, reg, cur, 0, cur.shape[0])
        for g in GROUPS:
            root = self.out / f"{self.name}_{g}.ome.zarr"
            root.mkdir(parents=True, exist_ok=True)
            (root / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
            datasets = [{"path": str(lvl), "coordinateTransformations": [{"type": "scale",
                                                                          "scale": [float(2 ** lvl)] * 3}]}
                        for lvl, _ in self.plans[g]]
            (root / ".zattrs").write_text(json.dumps({"multiscales": [{
                "version": "0.4", "name": g, "axes": [{"name": a, "type": "space", "unit": "pixel"} for a in "zyx"],
                "datasets": datasets}]}, indent=1))
        written = {k: sum(f.result() for f in fs) for k, fs in self.futures.items()}
        self.pool.shutdown()
        lv = self.input_level
        groups = {g: {"zarr": f"{self.name}_{g}.ome.zarr/{lv + (1 if g == 'cos' else 2)}",
                      "scaledown": lv + (1 if g == "cos" else 2), "channels": [g]} for g in GROUPS}
        (self.out / f"{self.name}.lasagna.json").write_text(json.dumps({
            "version": 2, "source_to_base": 1.0, "grad_mag_encode_scale": 1000.0, "grad_mag_factor": 1.0 / self.base,
            "umbilicus_json": "", "groups": groups, "base_shape_zyx": self.base_shape,
            "preview": {"model": "Lasagnetta (scripts/lasagnetta)", "region_input_level": [list(r) for r in self.region],
                        "input_level": lv, "note": "model output; a preview of villa's lasagna field"}},
            indent=2) + "\n")
        return written


def write_field(out, name, res, region, input_level, base_shape, levels=4, workers=None, device=None):
    """The whole field at once (FieldWriter without streaming); numpy's pyramid unless device is CUDA."""
    return FieldWriter(out, name, region, input_level, base_shape, levels, workers, device).finish(res)


def self_check(a, net, meta, get, region, device):
    """selfcheck.check on the region with the preview's recipe; the record is written to OUT/selfcheck.json."""
    import selfcheck as S
    import teacher as TF
    teacher = TF.Teacher(a.teacher or C.teacher_checkpoint(Path("/tmp/lasagnetta-teacher")), device)
    rec = S.check(net, teacher, meta, get, region, device, a.self_check_spots, a.self_check_threshold,
                  cos_blur=tuple(a.cos_blur), cos_offset=a.cos_offset, coarse=S.coarse_fraction(source, a.ct))
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "selfcheck.json").write_text(json.dumps(rec, indent=1, default=float) + "\n")
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--checkpoint", required=True,
                    help="a student's .pt, several joined by commas (averaged), or release (the released average and "
                    "its recipe, from Hugging Face)")
    ap.add_argument("--ct", required=True)
    ap.add_argument("--region", type=int, nargs=6, required=True, metavar=("Z0", "Z1", "Y0", "Y1", "X0", "X1"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--input-level", type=int, default=0)
    ap.add_argument("--base-shape", type=int, nargs=3)
    ap.add_argument("--levels", type=int, default=4)
    ap.add_argument("--tile", type=int, nargs="+", default=[TILE], help="tile size: one, or Z Y X (multiples of 32)")
    ap.add_argument("--batch", type=int, help="tiles per forward (default 4 at tile 256 on CUDA, fewer for larger "
                    "tiles; 1 elsewhere: 4 tiles of the released average took over 15 GB on CPU)")
    ap.add_argument("--pyramid", choices=("auto", "gpu", "cpu"), default="auto",
                    help="where the coarser levels are pooled (auto: the GPU when there is one)")
    ap.add_argument("--no-stream", action="store_true", help="write every chunk after the last tile, as 0.1.0 did")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--flips", choices=sorted(M.FLIP_SETS), default="none", help="flip averaging")
    ap.add_argument("--cos-blur", type=float, nargs=3, default=[0.0, 0.0, 0.0], metavar=("SZ", "SY", "SX"),
                    help="Gaussian sigmas of cos along z, y, x in cos voxels, after flip averaging")
    ap.add_argument("--cos-offset", type=float, default=0.0,
                    help="lowers cos by this after the blur, clipped to 0..1 (fitted on training crops)")
    ap.add_argument("--self-check", action="store_true",
                    help="first score the student against villa's net on a few spots of the region (selfcheck.py); "
                    "when it falls short, write selfcheck.json, no field, and exit 3 so the caller runs villa")
    ap.add_argument("--self-check-spots", type=int, default=12)
    ap.add_argument("--self-check-threshold", type=float, default=0.82)
    ap.add_argument("--teacher", help="villa's lasagna checkpoint for --self-check (default: scrollprize/lasagna)")
    a = resolve(ap.parse_args(argv))
    t0 = time.time()
    device = torch.device(a.device)
    if len(a.tile) not in (1, 3):
        ap.error("--tile takes one size or three (Z Y X)")
    tile = tuple(a.tile) if len(a.tile) == 3 else a.tile[0]
    a.batch = a.batch or (0 if device.type == "cuda" else 1)
    net, config = load(a.checkpoint, device)
    meta, get = source(a.ct)
    r = a.region
    region = round_region(((r[0], r[1]), (r[2], r[3]), (r[4], r[5])), meta["shape"])
    check = None
    if a.self_check:
        check = self_check(a, net, meta, get, region, device)
        if check["decision"] != "student":
            print(json.dumps({k: v for k, v in check.items() if k != "rows"}, default=float), flush=True)
            sys.exit(3)
    base_shape = a.base_shape or [n * 2 ** a.input_level for n in meta["shape"]]
    gpu_pyr = a.pyramid == "gpu" or (a.pyramid == "auto" and device.type == "cuda")
    writer = FieldWriter(a.out, a.name, region, a.input_level, base_shape, a.levels,
                         device=device if gpu_pyr else None)
    t1 = time.time()
    stats = {}
    res, tiles = run(net, meta, get, region, device, a.batch, flips=M.FLIP_SETS[a.flips], cos_blur=tuple(a.cos_blur),
                     cos_offset=a.cos_offset, tile=tile, on_rows=None if a.no_stream else writer.rows, stats=stats)
    t2 = time.time()
    written = writer.finish(res)
    t3 = time.time()
    rec = {"config": config, "flips": a.flips, "cos_blur": a.cos_blur, "cos_offset": a.cos_offset,
           "region": [list(x) for x in region], "tile": list(tile) if isinstance(tile, tuple) else tile,
           "stream": not a.no_stream, "pyramid": "gpu" if gpu_pyr else "cpu", "tiles": tiles,
           "load_s": round(t1 - t0, 2), "predict_s": round(t2 - t1, 2), "write_s": round(t3 - t2, 2),
           "total_s": round(t3 - t0, 2), "predict_parts_s": stats, "chunks_written": written}
    if check:
        rec["self_check"] = {k: v for k, v in check.items() if k != "rows"}
    (Path(a.out) / "preview.json").write_text(json.dumps(rec, indent=1) + "\n")
    print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    main()
