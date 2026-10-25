"""Shared parts of Lasagnetta, a fast preview of villa's lasagna field: zarr v2 readers for local folders and the
Vesuvius Challenge open-data bucket, villa's Gaussian pyramid, the pinned villa lasagna checkpoint, and the agreement
metrics used to score a preview against villa's own field.

villa's lasagna net (ScrollPrize/villa, `lasagna/`; weights scrollprize/lasagna, MIT) stores cos at scaledown 2 and
grad_mag, nx, ny at scaledown 4 of the CT it read. Lasagnetta writes the same grids. Agreement is measured on a
256^3 crop's inner part (32 voxels left out on each side) inside the papyrus mask: Pearson r of cos and grad_mag,
the median angle between normals, and peak F1, which matches the sheet crossings (local maxima of cos at or above
0.5 along y and x lines) within one cos voxel.
"""
import hashlib
import http.client
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

BUCKET_HTTP = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
CROP = 256                      # input voxels a side; cos 128, the others 64
SCORE_BORDER = 32               # input voxels left out of scoring on each side of a crop
COS_SD, OTHER_SD = 2, 4
# villa's lasagna checkpoint the student was trained against and the self-check runs
LAS_REPO, LAS_FILE = "scrollprize/lasagna", "model_current.pt"
LAS_REVISION = "de45f01147adea9f4ad0f621b1ccd885a1f03760"
LAS_SHA256 = "4cc0c40a846b296769b9f7982470559078662a1a0b0e1f74ff41ed9341c0d600"
_META = {}


def http_get(key, tries=4, timeout=60):
    """Bytes of one open-data object, or None when it does not exist (an unwritten chunk)."""
    if key.startswith("/"):              # a local file
        f = Path(key)
        return f.read_bytes() if f.exists() else None
    url = f"{BUCKET_HTTP}/{key}"
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                return None
            err = exc
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            err = exc
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET {url}: {err}")


def zarray(prefix):
    if prefix not in _META:
        raw = http_get(f"{prefix}/.zarray")
        if raw is None:
            raise FileNotFoundError(f"{prefix}/.zarray")
        _META[prefix] = json.loads(raw)
    return _META[prefix]


def decode_chunk(raw, meta):
    shape = tuple(meta["chunks"])
    if raw is None:
        return np.full(shape, meta.get("fill_value") or 0, dtype=np.dtype(meta["dtype"]))
    comp = meta.get("compressor")
    if comp:
        from numcodecs import get_codec
        raw = get_codec(comp).decode(raw)
    return np.frombuffer(raw, dtype=np.dtype(meta["dtype"])).reshape(shape)


def read_box_from(meta, get, box, pool=None):
    ch, shape = meta["chunks"], meta["shape"]
    out = np.zeros(tuple(b - a for a, b in box), dtype=np.dtype(meta["dtype"]))
    idx = [range(max(0, a) // c, (min(b, n) - 1) // c + 1) if min(b, n) > max(0, a) else range(0)
           for (a, b), c, n in zip(box, ch, shape)]
    keys = [(i, j, k) for i in idx[0] for j in idx[1] for k in idx[2]]
    one = lambda key: (key, get(key))
    results = (pool.map(one, keys) if pool else map(one, keys))
    present = True
    for key, raw in results:
        present &= raw is not None
        arr = decode_chunk(raw, meta)
        src, dst = [], []
        for d in range(3):
            c0 = key[d] * ch[d]
            lo, hi = max(box[d][0], c0), min(box[d][1], c0 + ch[d], shape[d])
            src.append(slice(lo - c0, hi - c0))
            dst.append(slice(lo - box[d][0], hi - box[d][0]))
        out[tuple(dst)] = arr[tuple(src)]
    return out, present


def local_zarr(path):
    """(meta, get) for a zarr v2 array folder on local disk."""
    path = Path(path)
    meta = json.loads((path / ".zarray").read_text())
    sep = meta.get("dimension_separator", ".")

    def get(key):
        f = path / sep.join(map(str, key))
        return f.read_bytes() if f.exists() else None
    return meta, get


def papyrus_mask(ct, sd):
    """True where every CT voxel of the sd^3 block is inside the scan's papyrus mask (non-zero)."""
    d = ct.shape[0] // sd
    blocks = ct[:d * sd, :d * sd, :d * sd].reshape(d, sd, d, sd, d, sd)
    return blocks.min(axis=(1, 3, 5)) > 0


def decode_normal(nx_u8, ny_u8):
    """The teacher's unit normal from its stored nx, ny (villa encode_normal_nxny_u8 flips n so that nz >= 0)."""
    nx = (nx_u8.astype(np.float32) - 128.0) / 127.0
    ny = (ny_u8.astype(np.float32) - 128.0) / 127.0
    nz = np.sqrt(np.clip(1.0 - nx * nx - ny * ny, 0.0, 1.0))
    n = np.stack([nx, ny, nz])
    return n / (np.linalg.norm(n, axis=0, keepdims=True) + 1e-8)


def encode_normal(n):
    """Stored nx, ny uint8 from a (3, ...) normal, sign fixed as villa does (nz >= 0)."""
    n = n / (np.linalg.norm(n, axis=0, keepdims=True) + 1e-8)
    flip = np.where(n[2] < 0, -1.0, 1.0)
    enc = lambda c: np.clip(np.round(c * flip * 127.0 + 128.0), 0, 255).astype(np.uint8)
    return enc(n[0]), enc(n[1])


def targets(crop):
    """Float training targets from a fetched crop: cos (1, s/2^3), gm (1, s/4^3) on 0..1 as stored / 255, normal
    (3, s/4^3), and the papyrus masks at both scaledowns."""
    return {"cos": crop["cos"][None].astype(np.float32) / 255.0,
            "gm": crop["grad_mag"][None].astype(np.float32) / 255.0,
            "normal": decode_normal(crop["nx"], crop["ny"]),
            "mask_cos": papyrus_mask(crop["ct"], COS_SD)[None],
            "mask_other": papyrus_mask(crop["ct"], OTHER_SD)[None]}


def _pearson(a, b):
    a = a.astype(np.float64) - a.mean()
    b = b.astype(np.float64) - b.mean()
    den = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return float((a * b).sum() / den) if den > 0 else float("nan")


def line_peaks(v, mask, thresh=0.5):
    """Local maxima along the last axis at or above thresh, inside mask (a sheet crossing on a line)."""
    left = np.concatenate([np.full(v.shape[:-1] + (1,), -np.inf), v[..., :-1]], axis=-1)
    right = np.concatenate([v[..., 1:], np.full(v.shape[:-1] + (1,), -np.inf)], axis=-1)
    return (v >= left) & (v > right) & (v >= thresh) & mask


def peak_counts(s, t, mask, tol=1):
    """Matched, student and teacher peak counts along every line of the last axis, peaks matched within tol."""
    ps, pt = line_peaks(s, mask), line_peaks(t, mask)
    near_s = ps.copy()
    for d in range(1, tol + 1):
        near_s[..., d:] |= ps[..., :-d]
        near_s[..., :-d] |= ps[..., d:]
    matched = int((pt & near_s).sum())
    return matched, int(ps.sum()), int(pt.sum())


def inner(a, sd, border=SCORE_BORDER):
    b = border // sd
    return a[..., b:a.shape[-3] - b, b:a.shape[-2] - b, b:a.shape[-1] - b]


def crop_metrics(pred, tgt, shift=0):
    """Agreement of one crop's student output with the teacher, on the crop's inner part and papyrus mask.
    pred: cos (1, c^3) and gm (1, o^3) on 0..1, normal (3, o^3). shift > 0 rolls the student's maps by shift cos
    voxels (shift/2 at the coarser scale, rounded up) in y and x: the control that must fail."""
    cos_s, gm_s, n_s = pred["cos"][0], pred["gm"][0], pred["normal"]
    if shift:
        so = max(1, -(-shift // 2))
        cos_s = np.roll(cos_s, (shift, shift), axis=(1, 2))
        gm_s = np.roll(gm_s, (so, so), axis=(1, 2))
        n_s = np.roll(n_s, (so, so), axis=(2, 3))
    mc = inner(tgt["mask_cos"][0], COS_SD)
    mo = inner(tgt["mask_other"][0], OTHER_SD)
    cs, ct = inner(cos_s, COS_SD), inner(tgt["cos"][0], COS_SD)
    out = {"n_cos": int(mc.sum()), "n_other": int(mo.sum())}
    if mc.sum() < 1000 or mo.sum() < 100:
        out["skipped"] = "papyrus mask too small"
        return out
    out["cos_r"] = _pearson(cs[mc], ct[mc])
    m = s = t = 0
    for axis in (1, 2):         # lines along y and along x: the scroll's sheets stand roughly along z
        a, b, mm = (np.moveaxis(x, axis, -1) for x in (cs, ct, mc))
        dm, ds, dt = peak_counts(a, b, mm)
        m, s, t = m + dm, s + ds, t + dt
    out.update(peaks_matched=m, peaks_student=s, peaks_teacher=t,
               peak_f1=(2.0 * m / (s + t)) if s + t else float("nan"))
    gs, gt = inner(gm_s, OTHER_SD), inner(tgt["gm"][0], OTHER_SD)
    out["gm_r"] = _pearson(gs[mo], gt[mo])
    ns, nt = inner(n_s, OTHER_SD), inner(tgt["normal"], OTHER_SD)
    ns = ns / (np.linalg.norm(ns, axis=0, keepdims=True) + 1e-8)
    dot = np.abs((ns * nt).sum(axis=0))[mo]
    out["normal_deg"] = float(np.median(np.degrees(np.arccos(np.clip(dot, 0.0, 1.0)))))
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def teacher_checkpoint(dest):
    """villa's pinned lasagna checkpoint, downloaded from Hugging Face into dest and checked by sha256."""
    from huggingface_hub import hf_hub_download
    ck = Path(hf_hub_download(LAS_REPO, LAS_FILE, revision=LAS_REVISION, local_dir=str(dest)))
    if sha256(ck) != LAS_SHA256:
        raise RuntimeError(f"{ck} is not the pinned villa lasagna checkpoint")
    return ck


def pyrdown(a, factor):
    """villa's tiled_predict3d._pyrdown3d on a (C, z, y, x) array: [1 4 6 4 1]/16 along each axis, reflect padding,
    every second voxel from 0, repeated for each factor of 2."""
    import torch
    import torch.nn.functional as F
    t = torch.from_numpy(np.ascontiguousarray(a, dtype=np.float32))
    k = torch.tensor([1, 4, 6, 4, 1], dtype=torch.float32) / 16.0
    f = int(factor)
    while f > 1:
        c = t.shape[0]
        for dim, pad in enumerate([(0, 0, 0, 0, 2, 2), (0, 0, 2, 2, 0, 0), (2, 2, 0, 0, 0, 0)]):
            shape = [1, 1, 1, 1, 1]
            shape[dim + 2] = 5
            kd = k.view(*shape).expand(c, 1, *shape[2:])
            t = F.conv3d(F.pad(t[None], pad, mode="reflect"), kd, groups=c)[0]
        t = t[:, ::2, ::2, ::2]
        f //= 2
    return t.numpy()


def pooled_from_raw(raw, encode):
    """villa's stored products from the blended raw channels (8, 256^3) on the device: the raw slab pooled by its
    Gaussian pyramid (cos by 2, the seven normal channels by 4), then villa's finalize."""
    cos = pyrdown(raw[:1].cpu().numpy(), 2)
    other = pyrdown(raw[1:8].cpu().numpy(), 4)
    nx, ny = encode(other[1], other[2], other[3], other[4], other[5], other[6])
    return {"cos": np.clip(cos[0] * 255.0, 0, 255).astype(np.uint8),
            "grad_mag": np.clip(other[0] * 1000.0, 0, 255).astype(np.uint8), "nx": nx, "ny": ny}
