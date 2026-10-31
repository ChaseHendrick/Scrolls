"""Fetch whole z-slices of a published binary surface prediction from the open-data bucket; by default PHerc0139's
m7 (frame 20250728140407, 9.362 um).

Only the chunk layers that hold the requested slices are read; each chunk is decoded once and only the requested
slices are kept, so memory is about 44 MB per m7 slice.

    python3 scripts/ringleader/m7slices.py work/ringleader/m7 --z 3000 3004 3008 7000

writes work/ringleader/m7/z03000.npy ... (uint8, 0 or 255 for m7, shape 6621 x 6621, y then x). --zarr reads another
zarr v2 array (a URL or a local folder holding .zarray and its chunks, z y x order, one byte per voxel).
"""

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import rlcommon  # noqa: E402

M7 = rlcommon.P0139["m7"]


def _read(base, key, tries=4):
    """Bytes of base/key (URL or folder), or None when the chunk is absent (an empty chunk)."""
    if not str(base).startswith(("http://", "https://")):
        f = Path(base) / key
        return f.read_bytes() if f.is_file() else None
    try:
        return rlcommon._get(f"{base}/{key}", tries)
    except Exception as e:  # noqa: BLE001
        if getattr(e, "code", None) in (403, 404):
            return None
        raise


def meta(base):
    """(shape, chunks, codec) of a zarr v2 array."""
    import numcodecs
    raw = _read(base, ".zarray")
    if raw is None:
        raise SystemExit(f"{base}: no .zarray")
    m = json.loads(raw)
    if np.dtype(m["dtype"]).itemsize != 1:
        raise SystemExit(f"{base}: dtype {m['dtype']}, expected one byte per voxel")
    if m.get("order", "C") != "C" or m.get("filters"):
        raise SystemExit(f"{base}: only C order without filters is read here")
    codec = numcodecs.get_codec(m["compressor"]) if m.get("compressor") else None
    sep = m.get("dimension_separator", ".")
    return tuple(m["shape"]), tuple(m["chunks"]), codec, sep


def fetch_slices(zs, workers=16, log=print, base=M7):
    zs = sorted(set(int(z) for z in zs))
    shape, ch, codec, sep = meta(base)
    if not all(0 <= z < shape[0] for z in zs):
        raise SystemExit(f"z must lie in 0 to {shape[0] - 1}")
    out = {z: np.zeros(shape[1:], np.uint8) for z in zs}
    layers = sorted({z // ch[0] for z in zs})
    ny, nx = -(-shape[1] // ch[1]), -(-shape[2] // ch[2])
    t0 = time.time()
    for L in layers:
        want = [z for z in zs if z // ch[0] == L]
        jobs = [(L, j, i) for j in range(ny) for i in range(nx)]

        def work(job):
            L_, j, i = job
            raw = _read(base, sep.join(str(v) for v in (L_, j, i)))
            if raw is None:
                return job, None
            buf = codec.decode(raw) if codec else raw
            a = np.frombuffer(buf, np.uint8).reshape(ch)
            return job, {z: a[z - L_ * ch[0]].copy() for z in want}

        n = 0
        with concurrent.futures.ThreadPoolExecutor(workers) as pool:
            for (L_, j, i), d in pool.map(work, jobs):
                if d is None:
                    continue
                n += 1
                y0, x0 = j * ch[1], i * ch[2]
                for z, s in d.items():
                    h, w = min(ch[1], shape[1] - y0), min(ch[2], shape[2] - x0)
                    out[z][y0:y0 + h, x0:x0 + w] = s[:h, :w]
        log(f"layer {L} (z {L * ch[0]} to {L * ch[0] + ch[0] - 1}): {n} chunks, {time.time() - t0:.0f} s")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dest")
    ap.add_argument("--z", type=int, nargs="+", required=True)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--zarr", default=M7, help="zarr v2 array to read (default PHerc0139's m7 level 0)")
    ap.add_argument("--exclude-z", default=None, help="z ranges never to fetch, lo:hi,lo:hi or a file of them")
    a = ap.parse_args()
    rlcommon.check_z(a.z, rlcommon.parse_ranges(a.exclude_z))
    dest = Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    zs = [z for z in a.z if not (dest / f"z{z:05d}.npy").is_file()]
    if not zs:
        return
    for z, s in fetch_slices(zs, a.workers, log=lambda m: print(m, flush=True), base=a.zarr).items():
        np.save(dest / f"z{z:05d}.npy", s)
    print(json.dumps({"saved": zs}))


if __name__ == "__main__":
    main()
