"""Read CT slices of a scroll from the open-data bucket (level 3, every 8th slice) and the published umbilici.

Standard library plus numpy and requests (scipy for smooth_z; numcodecs only for Arr and extract, the whole-chunk
reader the 13 October training runs used, which `slices.py extract` and predict.py replace with extract_ranged).
"""
import functools, json, os, re, sys, threading, time
import numpy as np
from concurrent.futures import ThreadPoolExecutor

B = "https://vesuvius-challenge-open-data.s3.amazonaws.com/"
DROBKOV = "https://raw.githubusercontent.com/AlexeyDrobkovStrikesBack/herculaneum-umbilici/{rev}/{s}_umbilicus.json"
DROBKOV_REV = os.environ.get("DROBKOV_REV", "de7642ac9b38266e95192489e22fb13b7e2d13b6")   # its files are dated 30 Sep 2026
# Published umbilici: sean's three in the bucket, Alexey Drobkov's ten (github.com/AlexeyDrobkovStrikesBack/herculaneum-umbilici)
BUCKET_UMB = {"PHerc0125": "PHerc0125/representations/umbilicus/20250821151825-umbilicus-20260808111524.json",
              "PHerc0211": "PHerc0211/representations/umbilicus/20250821151803-umbilicus-20260808112626.json",
              "PHerc0826": "PHerc0826/representations/umbilicus/20250821151701-umbilicus-20260808113303.json"}
DROBKOV_SCROLLS = ["PHerc0191", "PHerc0257", "PHerc0268", "PHerc0358", "PHerc0800", "PHerc0813", "PHerc1203",
                   "PHerc1218", "PHerc1447", "PHerc1545"]
LABELLED = list(BUCKET_UMB) + DROBKOV_SCROLLS
# Optional: scrolls with no published center line that training runs also predict (empty by default; see README.md)
UNLABELLED = []

_S = None
def _session():
    global _S
    if _S is None:
        import requests
        _S = requests.Session()
        _S.mount("https://", requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64))
    return _S

def get(url, retries=6):
    """GET with retries. None only on a real NoSuchKey (S3 sometimes answers 404 for keys it holds)."""
    last = None
    for i in range(retries):
        try:
            r = _session().get(url, timeout=60)
        except Exception as e:
            last = e; time.sleep(2 ** i); continue
        if r.status_code == 200:
            return r.content
        if r.status_code == 404 and b"NoSuchKey" in r.content:
            return None
        last = r.status_code; time.sleep(2 ** i)
    raise RuntimeError(f"{url}: {last}")

def get_range(url, lo, hi, retries=6):
    """Bytes lo..hi of url; None only on a real NoSuchKey (an absent chunk is the fill value)."""
    last = None
    for i in range(retries):
        try:
            r = _session().get(url, headers={"Range": f"bytes={lo}-{hi}"}, timeout=60)
        except Exception as e:
            last = e; time.sleep(min(2 ** i, 20)); continue
        if r.status_code in (200, 206):
            return r.content if r.status_code == 206 else r.content[lo:hi + 1]
        if r.status_code == 404 and b"NoSuchKey" in r.content:
            return None
        last = r.status_code; time.sleep(min(2 ** i, 20))
    raise RuntimeError(f"{url}: {last}")

class PlaneReader:
    """Single z planes (or windows of them) of one level of an uncompressed zarr v2 volume with 128^3 uint8 chunks,
    read with HTTP range requests: one 16 KiB request per chunk the window touches, so a level-3 plane is about 1 MB
    and a small window a few tens of KB. Outside the volume and absent chunks read as 0; `missing` counts the absent
    chunk reads (one per plane and chunk), also when planes are read from several threads."""
    C = 128
    def __init__(self, vol, level):
        self.vol, self.level = vol.rstrip("/"), level
        m = json.loads(get(B + f"{self.vol}/{level}/.zarray"))
        if not (m["compressor"] is None and m["chunks"] == [self.C] * 3 and m["dtype"] == "|u1" and m.get("order", "C") == "C"):
            raise ValueError(f"{self.vol}/{level}: needs raw 128^3 uint8 chunks, got {m['compressor']} {m['chunks']} {m['dtype']}")
        self.shape, self.sep = m["shape"], m.get("dimension_separator", ".")
        self.missing, self._lock = 0, threading.Lock()
    def plane(self, z, y0=0, y1=None, x0=0, x1=None, threads=16):
        C = self.C
        y1 = self.shape[1] if y1 is None else y1; x1 = self.shape[2] if x1 is None else x1
        out = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cz, zi = divmod(int(z), C)
        ya, yb = max(0, y0), min(self.shape[1], y1); xa, xb = max(0, x0), min(self.shape[2], x1)
        if ya >= yb or xa >= xb or not 0 <= int(z) < self.shape[0]:
            return out
        jobs = [(cy, cx) for cy in range(ya // C, (yb - 1) // C + 1) for cx in range(xa // C, (xb - 1) // C + 1)]
        def one(j):
            url = f"{B}{self.vol}/{self.level}/" + self.sep.join(map(str, (cz,) + j))
            return get_range(url, zi * C * C, (zi + 1) * C * C - 1)
        with ThreadPoolExecutor(threads) as ex:
            res = list(ex.map(one, jobs))
        absent = sum(raw is None for raw in res)
        if absent:
            with self._lock:
                self.missing += absent
        for (cy, cx), raw in zip(jobs, res):
            if raw is None:
                continue
            t = np.frombuffer(raw, np.uint8).reshape(C, C)
            gy, gx = cy * C, cx * C
            sy, ey = max(gy, ya), min(gy + C, yb); sx, ex_ = max(gx, xa), min(gx + C, xb)
            out[sy - y0:ey - y0, sx - x0:ex_ - x0] = t[sy - gy:ey - gy, sx - gx:ex_ - gx]
        return out

def level0_shape(vol):
    """[z, y, x] of level 0 of a bucket scan, from its `.zarray` (one small request); None when the bucket has no
    level-0 `.zarray` at that path. ValueError when its shape is not three positive integers."""
    raw = get(B + f"{vol.rstrip('/')}/0/.zarray")
    if raw is None:
        return None
    shape = json.loads(raw).get("shape")
    if not (isinstance(shape, list) and len(shape) == 3
            and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in shape)):
        raise ValueError(f"{vol}/0/.zarray: shape {shape!r} is not three positive integers")
    return shape

def ls(prefix):
    t = get(B + "?list-type=2&delimiter=/&prefix=" + prefix).decode()   # retries and a status check
    if "<ListBucketResult" not in t:
        raise RuntimeError(f"listing {prefix}: {t[:200]}")
    return re.findall(r"<Prefix>([^<]*)</Prefix>", t)[1:]

class Arr:
    """One level of a zarr v2 array over HTTP."""
    def __init__(self, path, level):
        import numcodecs
        self.path = path.rstrip("/") + f"/{level}"
        self.meta = json.loads(get(B + self.path + "/.zarray"))
        self.shape, self.chunks = self.meta["shape"], self.meta["chunks"]
        self.sep = self.meta.get("dimension_separator", ".")
        self.codec = numcodecs.get_codec(self.meta["compressor"]) if self.meta["compressor"] else None
        self.dtype = np.dtype(self.meta["dtype"])
    def chunk(self, idx):
        raw = get(B + self.path + "/" + self.sep.join(map(str, idx)))
        if not raw:
            return np.full(self.chunks, self.meta["fill_value"] or 0, self.dtype)
        b = self.codec.decode(raw) if self.codec else raw
        return np.frombuffer(b, self.dtype).reshape(self.chunks)
    def read_z(self, z0, z1, threads=16):
        c = self.chunks; out = np.zeros((z1 - z0, self.shape[1], self.shape[2]), self.dtype)
        jobs = [(a, b, d) for a in range(z0 // c[0], (z1 - 1) // c[0] + 1)
                for b in range(-(-self.shape[1] // c[1])) for d in range(-(-self.shape[2] // c[2]))]
        with ThreadPoolExecutor(threads) as ex:
            res = list(ex.map(self.chunk, jobs))
        for (a, b, d), ch in zip(jobs, res):
            za, ya, xa = a * c[0], b * c[1], d * c[2]
            zs, ze = max(z0, za), min(z1, za + c[0]); ye, xe = min(self.shape[1], ya + c[1]), min(self.shape[2], xa + c[2])
            out[zs - z0:ze - z0, ya:ye, xa:xe] = ch[zs - za:ze - za, :ye - ya, :xe - xa]
        return out

def smooth_z(p, win=9):
    """Running median then a quadratic Savitzky-Golay along z; NaNs filled by interpolation first."""
    from scipy.ndimage import median_filter
    from scipy.signal import savgol_filter
    p = np.array(p, float); idx = np.arange(len(p))
    for k in range(p.shape[1]):
        g = np.isfinite(p[:, k])
        if not g.any():
            return p
        p[:, k] = np.interp(idx, idx[g], p[g, k])
    q = np.stack([median_filter(p[:, k], size=win, mode="nearest") for k in range(p.shape[1])], 1)
    return savgol_filter(q, 11, 2, axis=0) if len(q) > 11 else q

@functools.lru_cache(maxsize=None)
def truth(s):
    """(volume path, control points as rows z, y, x in level-0 voxels) for a scroll with a published umbilicus.
    Cached per process; callers only read it."""
    if s in BUCKET_UMB:
        d = json.loads(get(B + BUCKET_UMB[s])); vid = BUCKET_UMB[s].split("/")[-1].split("-")[0]
        vols = [v for v in ls(s + "/volumes/") if vid in v]
        if not vols:
            raise RuntimeError(f"{s}: no volume matching {vid}")
        vol = vols[0]
    else:
        d = json.loads(get(DROBKOV.format(rev=DROBKOV_REV, s=s))); vol = d["metadata"]["source_volume"]
    cp = sorted(d["control_points"], key=lambda p: p["z"])
    return vol.rstrip("/"), np.array([[p["z"], p["y"], p["x"]] for p in cp], float)

def volume(s):
    if s in LABELLED:
        return truth(s)[0]
    vs = [v for v in ls(s + "/volumes/") if "um-1.2m" in v]
    if not vs:
        raise RuntimeError(f"{s}: no 1.2 m scan in the open-data bucket; name a scan with predict.py --volume")
    return sorted(vs)[0].rstrip("/")       # the 1.2 m (about 9 um) scan when a scroll has several

def extract(s, out, level=3, every=8):
    """Every `every`-th slice of level `level`; z in level-0 voxels. Reads whole chunks (Arr, needs numcodecs); the
    training slices were made this way. extract_ranged writes the same file with range requests (tested)."""
    vol = volume(s); a = Arr(vol, level); Z = a.shape[0]
    zs = np.arange(every // 2, Z, every); ct = np.zeros((len(zs),) + tuple(a.shape[1:]), np.uint8)
    c = a.chunks[0]
    for L in range(0, Z, c):
        sel = [i for i, z in enumerate(zs) if L <= z < L + c]
        if sel:
            blk = a.read_z(L, min(Z, L + c))
            for i in sel:
                ct[i] = blk[zs[i] - L]
    um = float(vol.split("/")[-1].split("-")[1].replace("um", ""))
    np.savez_compressed(out, ct=ct, z_l0=zs * 2 ** level, vol=vol, um=um, level=level, **_shape_l0(vol))
    return out

def _shape_l0(vol):
    """{"shape_l0": [z, y, x]} of the scan's level 0 for a slice file, or {} when the bucket has none: the
    volume dimensions an umbilicus file is stamped with (pipeline.volume_dims)."""
    try:
        shape = level0_shape(vol)
    except (RuntimeError, ValueError, OSError) as e:
        print(f"{vol}: no shape_l0 stored: level-0 metadata could not be read ({e}); CT slices are kept",
              file=sys.stderr)
        return {}
    return {} if shape is None else {"shape_l0": np.asarray(shape, np.int64)}

def extract_ranged(s, out, level=3, every=8, vol=None, threads=16):
    """extract's output (every `every`-th plane of level `level`, z in level-0 voxels) read plane by plane with
    range requests (PlaneReader): about 1 MB per level-3 plane, instead of whole 128-plane chunks. The file also holds
    `missing` (chunk reads the bucket answered with NoSuchKey, read as 0), `chunks` (all chunk reads) and, when the
    bucket has a level-0 `.zarray`, `shape_l0` (level 0's [z, y, x]). Nothing is written when every chunk read was
    absent: the scan is not at that path (or not at that level)."""
    vol = (vol or volume(s)).rstrip("/")
    r = PlaneReader(vol, level); Z = r.shape[0]
    zs = np.arange(every // 2, Z, every)
    with ThreadPoolExecutor(max(1, threads // 8)) as ex:
        ct = np.stack(list(ex.map(lambda z: r.plane(int(z), threads=8), zs)))
    chunks = len(zs) * -(-r.shape[1] // r.C) * -(-r.shape[2] // r.C)
    if r.missing >= chunks:
        raise RuntimeError(f"{vol}/{level}: all {chunks} chunk reads were absent (NoSuchKey); no slice file written")
    um = float(vol.split("/")[-1].split("-")[1].replace("um", ""))
    np.savez_compressed(out, ct=ct, z_l0=zs * 2 ** level, vol=vol, um=um, level=level, missing=r.missing, chunks=chunks,
                        **_shape_l0(vol))
    return out

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Slice files for the center finder: every 8th level-3 plane of a scan.")
    ap.add_argument("cmd", choices=["extract"]); ap.add_argument("scrolls", nargs="*", help="default: the 13 published scrolls")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for s in a.scrolls or LABELLED:
        f = os.path.join(a.out, f"{s}.npz")
        if os.path.exists(f):
            print(s, "exists"); continue
        extract_ranged(s, f + ".tmp.npz"); os.replace(f + ".tmp.npz", f)
        print(s, f, os.path.getsize(f), flush=True)
