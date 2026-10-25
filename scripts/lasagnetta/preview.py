"""A fast lasagna preview: the student over a region of a scan, written in villa's field layout (NAME.lasagna.json,
NAME_{cos,grad_mag,nx,ny}.ome.zarr: cos at scaledown 2, the others at 4, coarser levels where the region is aligned
to their chunks), so whatever reads a published lasagna field can read it. Model output, a preview of the teacher's
field; never a replacement for villa's own field where exact values matter.

  python scripts/lasagnetta/preview.py --checkpoint release --ct CT_LEVEL_DIR --region Z0 Z1 Y0 Y1 X0 X1 \
      --out DIR --name NAME [--self-check] [--input-level 0] [--base-shape Z Y X] [--batch 4] [--device cuda]

--checkpoint release uses the released average (Hugging Face SharpMeow/lasagnetta) and its recipe. --self-check
first scores it against villa's net on a few spots of the region (selfcheck.py) and exits 3, writing no field, when
the agreement is too low, so the caller can run villa's predict3d instead.

--ct is the zarr v2 folder of the CT level the student reads (a local folder, or s3://BUCKET/... on the open-data
bucket through HTTPS). The region is in that level's voxels and is rounded out to multiples of 128. Tiles of 256
step by 192 and keep their middle 192 (32 voxels of context each side), so tiles never blend.
"""
import argparse
import json
import os
import sys
import threading
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


# The released average (Hugging Face SharpMeow/lasagnetta): three students, one plain forward each, then a 0.5 voxel
# cos blur and a 0.04 cos offset. --checkpoint release fetches it and sets that recipe.
RELEASE = {"repo": "SharpMeow/lasagnetta", "files": ["lasagnetta-l32n.pt", "lasagnetta-xl.pt", "lasagnetta-w24.pt"],
           "cos_blur": [0.5, 0.5, 0.5], "cos_offset": 0.04}


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


def positions(a, b):
    """Tile origins along one axis so the cores [p + MARGIN, p + MARGIN + CORE) cover [a, b)."""
    ps, p = [], a - MARGIN
    while p + MARGIN < b:
        ps.append(p)
        p += CORE
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


def run(net, meta, get, region, device, batch=4, log=print, flips=((),), cos_blur=(0, 0, 0), cos_offset=0.0):
    """The products over the region: cos (region / 2), grad_mag, nx, ny (region / 4), uint8. flips and cos_blur are
    the inference recipe (lasnet.predict_maps, with cos_offset), applied per tile before its core is kept."""
    shape = meta["shape"]
    size = [b - a for a, b in region]
    res = {"cos": np.zeros([s // 2 for s in size], np.uint8)}
    for k in ("grad_mag", "nx", "ny"):
        res[k] = np.zeros([s // 4 for s in size], np.uint8)
    pz, py, px = (positions(a, b) for a, b in region)
    ybox = (py[0], py[-1] + TILE)
    xbox = (px[0], px[-1] + TILE)
    read_pool = ThreadPoolExecutor(32)
    slabs = {}

    def read(z):
        arr, _ = C.read_box_from(meta, get, ((z, z + TILE), ybox, xbox), read_pool)
        return arr

    def place(z, y, x, prods):
        """Write one tile's core into the region arrays (clipped to the region)."""
        for name, sd, arr in zip(("cos", "grad_mag", "nx", "ny"), (2, 4, 4, 4), prods):
            src, dst = [], []
            for d, p in enumerate((z, y, x)):
                lo = max(p + MARGIN, region[d][0])
                hi = min(p + MARGIN + CORE, region[d][1])
                src.append(slice((lo - p) // sd, (hi - p) // sd))
                dst.append(slice((lo - region[d][0]) // sd, (hi - region[d][0]) // sd))
            res[name][tuple(dst)] = arr[tuple(src)]

    ahead = ThreadPoolExecutor(1)
    nxt = ahead.submit(read, pz[0])
    tiles = 0
    for i, z in enumerate(pz):
        slab = nxt.result()
        if i + 1 < len(pz):
            nxt = ahead.submit(read, pz[i + 1])
        g = torch.from_numpy(slab).to(device, non_blocking=True)
        coords = [(y, x) for y in py for x in px]
        for j in range(0, len(coords), batch):
            part = coords[j:j + batch]
            keep = []
            xs = []
            for y, x in part:
                t = g[:, y - ybox[0]:y - ybox[0] + TILE, x - xbox[0]:x - xbox[0] + TILE]
                if not bool((t > 0).any()):
                    continue                    # no CT: leave fill, as predict3d skips empty tiles
                keep.append((y, x))
                xs.append(t)
            if not xs:
                continue
            xb = torch.stack(xs)[:, None].float().div_(255.0)
            if device.type == "cuda":
                xb = xb.contiguous(memory_format=torch.channels_last_3d)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                maps = M.predict_maps(net, xb, flips, cos_blur, cos_offset)
            prods = [p.cpu().numpy() for p in finalize(maps)]
            for b, (y, x) in enumerate(keep):
                place(z, y, x, [p[b] for p in prods])
            tiles += len(keep)
        log(f"slab {i + 1}/{len(pz)}: {tiles} tiles so far")
    read_pool.shutdown(); ahead.shutdown()
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


def write_level(root, level, arr, region_out, full_shape, pool=None):
    """One zarr v2 level, chunks 32 and blosc lz4 as villa writes them, with only the region's chunks. With a pool,
    returns the chunk futures (each 1 if written) instead of waiting."""
    from numcodecs import get_codec
    codec = get_codec(BLOSC)
    d = Path(root) / str(level)
    d.mkdir(parents=True, exist_ok=True)
    (d / ".zarray").write_text(json.dumps({"shape": list(full_shape), "chunks": [CHUNK] * 3, "dtype": "|u1",
                                           "fill_value": 0, "order": "C", "filters": None,
                                           "dimension_separator": "/", "compressor": BLOSC, "zarr_format": 2},
                                          indent=1))
    o = [a for a, _ in region_out]
    jobs = []
    for i in range(0, arr.shape[0], CHUNK):
        for j in range(0, arr.shape[1], CHUNK):
            for k in range(0, arr.shape[2], CHUNK):
                jobs.append((i, j, k))

    def one(ijk):
        i, j, k = ijk
        block = np.zeros((CHUNK,) * 3, np.uint8)
        part = arr[i:i + CHUNK, j:j + CHUNK, k:k + CHUNK]
        block[:part.shape[0], :part.shape[1], :part.shape[2]] = part
        if not block.any():
            return 0
        key = [(o[0] + i) // CHUNK, (o[1] + j) // CHUNK, (o[2] + k) // CHUNK]
        f = d / "/".join(map(str, key))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(codec.encode(np.ascontiguousarray(block)))
        return 1
    if pool is not None:
        return [pool.submit(one, ijk) for ijk in jobs]
    with ThreadPoolExecutor(16) as own:
        return sum(own.map(one, jobs))


def write_field(out, name, res, region, input_level, base_shape, levels=4, workers=None):
    """The field in villa's layout. Array level L has scale 2**L of the scan's level 0; the student read input level
    input_level, so cos lands at L = input_level + 1 and the rest at input_level + 2. Each pyramid is built once (the
    normal's serves nx and ny), in parallel slabs, and every chunk of every level goes through one thread pool."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    base = 2 ** input_level
    pool = ThreadPoolExecutor(workers or max(8, 2 * (os.cpu_count() or 4)))

    def kept_levels(first):
        """The levels written: the first, then each coarser one while the region sits on its chunk lines."""
        lv = []
        for lvl in range(first, levels + 1):
            reg = [(a * base // 2 ** lvl, b * base // 2 ** lvl) for a, b in region]
            if any(a % CHUNK for a, _ in reg) or (lvl > first and any((b - a) % CHUNK for a, b in reg)):
                break                                   # region not on this level's chunk lines
            lv.append((lvl, reg))
        return lv

    plans = {}
    for kind, groups, first in (("scalar", ("cos",), input_level + 1), ("scalar", ("grad_mag",), input_level + 2),
                                ("normal", ("nx", "ny"), input_level + 2)):
        lv = kept_levels(first)
        arr = res[groups[0]] if kind == "scalar" else np.stack([res["nx"], res["ny"]])
        pyr = [arr]
        for _ in lv[1:]:
            pyr.append(pool2_par(pyr[-1], kind, pool))
        for gi, group in enumerate(groups):
            plans[group] = [(lvl, reg, p if kind == "scalar" else p[gi]) for (lvl, reg), p in zip(lv, pyr)]
    futures = {}
    for group in ("cos", "grad_mag", "nx", "ny"):
        root = out / f"{name}_{group}.ome.zarr"
        datasets = []
        for lvl, reg, cur in plans[group]:
            s = 2 ** lvl
            full = [-(-n // s) for n in base_shape]
            futures[f"{group}/{lvl}"] = write_level(root, lvl, cur, reg, full, pool)
            datasets.append({"path": str(lvl), "coordinateTransformations": [{"type": "scale",
                                                                              "scale": [float(s)] * 3}]})
        root.mkdir(parents=True, exist_ok=True)
        (root / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
        (root / ".zattrs").write_text(json.dumps({"multiscales": [{
            "version": "0.4", "name": group, "axes": [{"name": a, "type": "space", "unit": "pixel"} for a in "zyx"],
            "datasets": datasets}]}, indent=1))
    written = {k: sum(f.result() for f in fs) for k, fs in futures.items()}
    pool.shutdown()
    groups = {g: {"zarr": f"{name}_{g}.ome.zarr/{input_level + (1 if g == 'cos' else 2)}",
                  "scaledown": input_level + (1 if g == "cos" else 2), "channels": [g]}
              for g in ("cos", "grad_mag", "nx", "ny")}
    (out / f"{name}.lasagna.json").write_text(json.dumps({
        "version": 2, "source_to_base": 1.0, "grad_mag_encode_scale": 1000.0, "grad_mag_factor": 1.0 / base,
        "umbilicus_json": "", "groups": groups, "base_shape_zyx": list(base_shape),
        "preview": {"model": "Lasagnetta (scripts/lasagnetta)", "region_input_level": [list(r) for r in region],
                    "input_level": input_level, "note": "model output; a preview of villa's lasagna field"}},
        indent=2) + "\n")
    return written


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
    ap.add_argument("--batch", type=int, help="tiles per forward (default 4 on CUDA, 1 elsewhere: 4 tiles of the "
                    "released average took over 15 GB on CPU)")
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
    a.batch = a.batch or (4 if device.type == "cuda" else 1)
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
    t1 = time.time()
    res, tiles = run(net, meta, get, region, device, a.batch, flips=M.FLIP_SETS[a.flips], cos_blur=tuple(a.cos_blur),
                      cos_offset=a.cos_offset)
    t2 = time.time()
    written = write_field(a.out, a.name, res, region, a.input_level, base_shape, a.levels)
    t3 = time.time()
    rec = {"config": config, "flips": a.flips, "cos_blur": a.cos_blur, "cos_offset": a.cos_offset,
           "region": [list(x) for x in region],
           "tiles": tiles, "load_s": round(t1 - t0, 2),
           "predict_s": round(t2 - t1, 2), "write_s": round(t3 - t2, 2), "total_s": round(t3 - t0, 2),
           "chunks_written": written}
    if check:
        rec["self_check"] = {k: v for k, v in check.items() if k != "rows"}
    (Path(a.out) / "preview.json").write_text(json.dumps(rec, indent=1) + "\n")
    print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    main()
