"""Build data/lasagna/ for the Space from a local copy of SharpMeow/pherc0175a-lasagna.

Usage: python3 tools/build_lasagna.py DATASET_DIR OUT_DIR
DATASET_DIR holds index.json and parts/*.tar as published. Each tar is read in place (nothing is extracted to
disk): level 3 chunks of cos, grad_mag, nx and ny become a 16x field, and level 2 chunks of cos, nx and ny at nine
heights become the sheet and orientation slices. Needs numpy, numcodecs and Pillow.
"""
import json
import sys
import tarfile
from pathlib import Path

import numpy as np
from numcodecs import Blosc
from PIL import Image

SLICE_Z = [1280, 2560, 3840, 5120, 6400, 7680, 8960, 10240, 11520]  # level-0 scan voxels
S3 = (1594, 1171, 1171)  # level 3 shape (8x)
S16 = tuple((s + 1) // 2 for s in S3)
S2 = (3187, 2341, 2341)  # level 2 shape (4x)
NEEDLE_XY, NEEDLE_Z = 6, 12  # needle grid in 16x voxels: every 96 and 192 scan voxels


def inside(crop, scale, idx):
    return all(crop[a][0] <= idx[a] * 64 * scale < crop[a][1] for a in range(3))


def reduce(ds):
    codec = Blosc()
    f16 = {c: np.zeros(S16, np.uint8) for c in ("cos", "nx", "ny", "grad_mag")}
    sl = {c: np.zeros((len(SLICE_Z), S2[1], S2[2]), np.uint8) for c in ("cos", "nx", "ny")}
    for p in json.loads((ds / "index.json").read_text())["parts"]:
        crop = p["crop_zyx"]
        with tarfile.open(ds / "parts" / p["tar"]) as tf:
            for m in tf:
                bits = m.name.split("/")
                if not m.isfile() or len(bits) != 5 or not bits[0].endswith(".ome.zarr"):
                    continue
                ch = bits[0].split("_", 1)[1][: -len(".ome.zarr")]
                lvl, idx = int(bits[1]), tuple(int(v) for v in bits[2:])
                if lvl == 3 and ch in f16 and inside(crop, 8, idx):
                    a = np.frombuffer(codec.decode(tf.extractfile(m).read()), np.uint8).reshape(64, 64, 64)
                    r = a[::2, ::2, ::2] if ch in ("nx", "ny") else \
                        a.reshape(32, 2, 32, 2, 32, 2).astype(np.float32).mean((1, 3, 5)).round().astype(np.uint8)
                    o = [i * 32 for i in idx]
                    n = [min(32, S16[k] - o[k]) for k in range(3)]
                    f16[ch][o[0]:o[0] + n[0], o[1]:o[1] + n[1], o[2]:o[2] + n[2]] = r[:n[0], :n[1], :n[2]]
                elif lvl == 2 and ch in sl and inside(crop, 4, idx):
                    hit = [(k, z // 4 - idx[0] * 64) for k, z in enumerate(SLICE_Z) if idx[0] * 64 <= z // 4 < idx[0] * 64 + 64]
                    if not hit:
                        continue
                    a = np.frombuffer(codec.decode(tf.extractfile(m).read()), np.uint8).reshape(64, 64, 64)
                    y0, x0 = idx[1] * 64, idx[2] * 64
                    hy, hx = min(64, S2[1] - y0), min(64, S2[2] - x0)
                    for k, zz in hit:
                        sl[ch][k, y0:y0 + hy, x0:x0 + hx] = a[zz, :hy, :hx]
        print(p["part"], "read", flush=True)
    return f16, sl


def orientation_rgb(nx, ny, val):
    """Hue from the doubled in-plane angle of the normal (so n and -n match), value from val."""
    a = (nx.astype(np.float32) - 128) / 127
    b = (ny.astype(np.float32) - 128) / 127
    h = (np.arctan2(b, a) * 2 / (2 * np.pi)) % 1.0
    s = np.clip(np.hypot(a, b), 0, 1)
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = val * (1 - s), val * (1 - f * s), val * (1 - (1 - f) * s)
    r = np.choose(i, [val, q, p, p, t, val])
    g = np.choose(i, [t, val, val, q, p, p])
    bb = np.choose(i, [p, p, t, val, val, q])
    return (np.stack([r, g, bb], -1) * 255).clip(0, 255).astype(np.uint8)


def write(f16, sl, out):
    out.mkdir(parents=True, exist_ok=True)
    for k, z in enumerate(SLICE_Z):
        c = sl["cos"][k]
        Image.fromarray(c).resize((2048, 2048), Image.LANCZOS).save(out / f"cos_{z}.webp", quality=80, method=6)
        valid = (((sl["nx"][k] > 0) | (sl["ny"][k] > 0)) & (c > 0)).astype(np.uint8) * 255
        small = lambda a: np.array(Image.fromarray(a).resize((1024, 1024), Image.BILINEAR))
        vm = small(valid).astype(np.float32) / 255
        rgb = orientation_rgb(small(sl["nx"][k]), small(sl["ny"][k]), vm * 0.95)
        Image.fromarray(rgb).save(out / f"ori_{z}.webp", quality=80, method=6)
    sub = lambda a: a[::NEEDLE_Z, ::NEEDLE_XY, ::NEEDLE_XY]
    nx, ny, gm, cos = (sub(f16[c]) for c in ("nx", "ny", "grad_mag", "cos"))
    m = ((nx > 0) | (ny > 0)) & (cos > 40) & (gm > 20)
    zz, yy, xx = np.nonzero(m)
    a = (nx[m].astype(np.float32) - 128) / 127
    b = (ny[m].astype(np.float32) - 128) / 127
    c = np.sqrt(np.clip(1 - a * a - b * b, 0, 1))
    pos = np.stack([xx * NEEDLE_XY * 16 + 8, yy * NEEDLE_XY * 16 + 8, zz * NEEDLE_Z * 16 + 8], 1).astype(np.uint16)
    nrm = (np.stack([a, b, c], 1) * 127).round().astype(np.int8)
    (out / "needles.bin").write_bytes(pos.tobytes() + nrm.tobytes() + np.clip(gm[m], 0, 255).astype(np.uint8).tobytes())
    meta = {
        "scroll": "PHerc0175A", "scan": "20250521115057", "slice_z": SLICE_Z, "slice_px": 2048, "ori_px": 1024,
        "frame": "level-0 scan voxels, x 0..9363, y 0..9363",
        "needles": {"count": int(len(zz)), "grid_voxels": [NEEDLE_XY * 16, NEEDLE_XY * 16, NEEDLE_Z * 16],
                   "layout": "uint16 x,y,z (scan voxels) * count, then int8 nx,ny,nz (x127) * count, then uint8 grad_mag * count"},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    ds, out = Path(sys.argv[1]), Path(sys.argv[2])
    write(*reduce(ds), out)
