"""Lasagna Fields: make villa's lasagna field (cos, grad_mag, nx, ny) for one box of a public scan.

Everything that is not the web page: the scan list (the open data's metadata.json), reading a box of CT from the
open-data bucket, running a model on it, reading the field back, the agreement check against a published field,
pictures and the download. app.py is the page and the API.

The one model today is villa's own lasagna: its `predict3d` (lasagna/preprocess_cos_omezarr.py at a pinned commit)
with the `scrollprize/lasagna` checkpoint, called in this process exactly as its command line would be, so the field
is villa's field, not a copy of it. MODELS is the slot for other models (a faster student, a better net): each entry
names its runner, and a model is offered only when its entry says it is released.

  python3 lasfield.py selftest            the plumbing on synthetic CT (no network, no model)
  python3 lasfield.py run VOLUME Z Y X [SIZE]   one field on this computer (CUDA if present, else CPU)
"""
import concurrent.futures
import gzip
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
METADATA = BUCKET + "/metadata.json"
USER_AGENT = "lasagna-fields-space (huggingface.co/spaces/SharpMeow/lasagna-fields)"
# Scans this Space never reads: PHercParis4 is kept out of every public tool of ours (Chase's rule).
REFUSED_SAMPLES = {"phercparis4"}
CACHE = Path(os.environ.get("LASFIELD_CACHE") or Path(tempfile.gettempdir()) / "lasagna-fields")

# villa's lasagna at the commit the ten whole-scan fields of this Space were made with (docs/tools/lasagna-fields.md);
# lasagna/ imports vesuvius from vesuvius/src (train_unet_3d builds the net with vesuvius' NetworkFromConfig).
VILLA = dict(repo="https://github.com/ScrollPrize/villa.git",
             tarball="https://codeload.github.com/ScrollPrize/villa/tar.gz/{commit}",
             commit="db3dbea26185a9e09ab997bfa21a2a00477f0d56", keep=("lasagna/", "vesuvius/src/"),
             check="lasagna/preprocess_cos_omezarr.py")
WEIGHTS = dict(repo="scrollprize/lasagna", revision="de45f01147adea9f4ad0f621b1ccd885a1f03760", file="model_current.pt",
               sha256="4cc0c40a846b296769b9f7982470559078662a1a0b0e1f74ff41ed9341c0d600")

TILE = 192                   # predict3d's tile at this checkpoint (its patch size), stride TILE - overlap 64
MARGIN = TILE + 16 + 4       # CT read around the box: a tile, predict3d's border and the scaledown rounding
# predict3d widens a crop to whole output chunks (64 voxels of the quarter grid: 256 input voxels), so boxes are whole
# 256-voxel blocks of the input level: anything smaller costs the same, and the field matches villa's whole-scan run.
ALIGN = 256
SIZES = (256, 512)
DEFAULT_SIZE = 256
TARGET_UM = 9.4              # the model's training resolution: 1.2 m scans at level 0, 0.2 m (2.4 um) scans at level 2
CHANNELS = ("cos", "grad_mag", "nx", "ny")


class FieldError(Exception):
    """A refusal or failure shown to the visitor as is."""


def log(message):
    print(f"[lasfield {time.strftime('%H:%M:%S')}] {message}", flush=True)


# ---------------------------------------------------------------- http

def http_get(url, timeout=60, tries=4):
    """Bytes at `url`, or None for a missing object (an unwritten chunk is a 403 or 404 on the bucket)."""
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                return None
            err = exc
        except (urllib.error.URLError, OSError) as exc:
            err = exc
        time.sleep(1.5 * (i + 1))
    raise FieldError(f"could not read {url}: {err}")


def get_json(url):
    raw = http_get(url)
    if raw is None:
        raise FieldError(f"{url} does not exist")
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw)


# ---------------------------------------------------------------- the scans

_CATALOG = {"at": 0.0, "volumes": None}
_LOCK = threading.Lock()


def level_for(um):
    """The CT level whose voxels are nearest the model's 9.4 um (0 for 8.6 to 9.4 um scans, 2 for 2.4 um)."""
    return max(0, int(round(math.log2(TARGET_UM / float(um))))) if um else 0


def catalog(refresh_s=6 * 3600):
    """Every volume of the open data's metadata.json this Space may read, by volume id."""
    with _LOCK:
        if _CATALOG["volumes"] is not None and time.time() - _CATALOG["at"] < refresh_s:
            return _CATALOG["volumes"]
        meta = get_json(METADATA)
        vols = {}
        for sid, s in sorted((meta.get("samples") or {}).items()):
            if sid.lower() in REFUSED_SAMPLES:
                continue
            for vid, v in (s.get("volumes") or {}).items():
                pr = v.get("properties") or {}
                um, shape = pr.get("pixel_size_um"), pr.get("shape")
                if not um or not v.get("long_id"):
                    continue
                vols[vid] = {"volume": vid, "sample": sid, "long_id": v["long_id"], "voxel_um": float(um),
                             "shape_zyx": shape, "level": level_for(um),
                             "superseded_by": pr.get("superseded_by"),
                             "url": f"{BUCKET}/{sid}/volumes/{v['long_id']}/"}
        _CATALOG.update(at=time.time(), volumes=vols)
        return vols


def volume(vid):
    """The catalog row for a volume id (the 14-digit id or its long name), or a refusal."""
    vid = str(vid or "").strip().rstrip("/").split("/")[-1]
    vols = catalog()
    if vid in vols:
        return vols[vid]
    for v in vols.values():
        if v["long_id"] == vid or v["long_id"].startswith(vid + "-"):
            return v
    if any(vid.lower().startswith(s) for s in REFUSED_SAMPLES):
        raise FieldError("this Space does not read PHercParis4")
    raise FieldError(f"{vid!r} is not a volume in the Vesuvius Challenge open data (metadata.json); "
                     "give its 14-digit volume id, such as 20260102150214")


def zarray(v, level):
    meta = get_json(f"{v['url']}{level}/.zarray")
    if len(meta.get("shape", ())) != 3:
        raise FieldError(f"{v['long_id']} level {level} is not a 3D array")
    return meta


_PUBLISHED = {}
# the ten whole-scan fields this Space hosts, made with the same villa commit and checkpoint as Make a field: volume id
# to (sample, run folder) in the public bucket; the check uses them where the open data has no field
OWN_BUCKET = "https://huggingface.co/buckets/SharpMeow/lasagna-fields/resolve"
OWN_FIELDS = {
    "20250521115057": ("PHerc0175A", "20250521115057-lasagna-de45f011"),
    "20250521125822": ("PHerc0175B", "20250521125822-lasagna-de45f011"),
    "20250521133212": ("PHerc0306B", "20250521133212-lasagna-de45f011"),
    "20250521140913": ("PHerc0483A", "20250521140913-lasagna-de45f011"),
    "20251124083638": ("PHerc0483B", "20251124083638-lasagna-de45f011"),
    "20250521151210": ("PHerc0490A", "20250521151210-lasagna-de45f011"),
    "20250521151215": ("PHerc0490B", "20250521151215-lasagna-de45f011"),
    "20250821151531": ("PHerc0841", "20250821151531-lasagna-de45f011"),
    "20250728152254": ("PHerc0846A", "20250728152254-lasagna-de45f011"),
    "20250804142305": ("PHerc0846B", "20250804142305-lasagna-de45f011"),
}


def published_field(v):
    """The open data's own lasagna run for this volume at its default level, if there is one: its manifest's URL
    and groups. The run folder names start with the volume id; an -L2 suffix says it read level 2."""
    key = v["volume"]
    if key in _PUBLISHED:
        return _PUBLISHED[key]
    found = _published_run(v)
    if found is None:
        # a remasked volume replaces an older one in the same voxel frame (metadata.json's superseded_by); the field
        # published for the older one is the one to check against, with the mask edge the only difference
        for old in catalog().values():
            if (old.get("superseded_by") or {}).get("volume_id") == key and old["level"] == v["level"]:
                found = _published_run(old)
                if found:
                    found = dict(found, note=f"published for {old['volume']}, which this volume replaces in the "
                                             "same voxel frame")
                    break
    if found is None and key in OWN_FIELDS and v["level"] == 0:
        found = _own_run(*OWN_FIELDS[key])
    _PUBLISHED[key] = found
    return found


def _own_run(sample, run):
    """One of this Space's ten whole-scan fields, described like an open-data run."""
    url = f"{OWN_BUCKET}/{sample}/representations/predictions/lasagna/{run}/"
    try:
        manifest = get_json(f"{url}{sample}.lasagna.json")
    except FieldError as exc:
        log(f"own field lookup for {sample} failed: {exc}")
        return None
    return {"run": run, "url": url, "manifest": f"{url}{sample}.lasagna.json", "groups": manifest.get("groups"),
            "base_shape_zyx": manifest.get("base_shape_zyx"), "source": "lasagna-fields",
            "note": "this Space's own whole-scan field, made with the same villa commit and checkpoint"}


def _published_run(v):
    found = None
    try:
        prefix = f"{v['sample']}/representations/predictions/lasagna/"
        raw = http_get(f"{BUCKET}/?list-type=2&delimiter=/&prefix={prefix}") or b""
        runs = re.findall(rb"<Prefix>([^<]+)</Prefix>", raw)
        for run in sorted(r.decode() for r in runs if r.decode() != prefix):
            name = run[len(prefix):].rstrip("/")
            tail = name.rsplit("-", 1)[-1]
            lvl = int(tail[1:]) if re.fullmatch(r"L\d", tail) else 0
            if not name.startswith(v["volume"]) or lvl != v["level"]:
                continue
            listing = http_get(f"{BUCKET}/?list-type=2&delimiter=/&prefix={run}") or b""
            js = [k.decode() for k in re.findall(rb"<Key>([^<]+\.lasagna\.json)</Key>", listing)]
            if js:
                manifest = get_json(f"{BUCKET}/{js[0]}")
                found = {"run": name, "url": f"{BUCKET}/{run}", "manifest": f"{BUCKET}/{js[0]}",
                         "groups": manifest.get("groups"), "base_shape_zyx": manifest.get("base_shape_zyx"),
                         "source": "open-data"}
    except FieldError as exc:
        log(f"published field lookup for {v['volume']} failed: {exc}")
    return found


# ---------------------------------------------------------------- a box

def plan(vid, z, y, x, size=DEFAULT_SIZE, level=None, model="lasagna"):
    """Where the field will be made: the `size`-voxel box of whole ALIGN blocks at the input level that holds
    level-0 voxel (z, y, x) (as near its middle as the grid allows), and the CT read around it. Refuses a point
    outside the scan or a size not offered."""
    v = volume(vid)
    spec = MODELS.get(model)
    if not spec or not spec["offered"]:
        raise FieldError(f"model {model!r} is not offered; choose from {', '.join(k for k, m in MODELS.items() if m['offered'])}")
    size = int(size)
    if size not in SIZES:
        raise FieldError(f"size {size} is not offered; choose from {', '.join(map(str, SIZES))}")
    level = v["level"] if level in (None, "", "auto") else int(level)
    if not 0 <= level <= 5:
        raise FieldError("level must be 0 to 5")
    base = zarray(v, 0)
    meta = zarray(v, level)
    shape = [int(s) for s in meta["shape"]]
    f = 2 ** level
    center = [int(round(float(c))) for c in (z, y, x)]
    for c, n in zip(center, base["shape"]):
        if not 0 <= c < n:
            raise FieldError(f"the point {center} is outside the scan (level-0 shape {base['shape']})")
    origin = [max(0, min((c // f - size // 2 + ALIGN // 2) // ALIGN * ALIGN, (n - 1) // ALIGN * ALIGN))
              for c, n in zip(center, shape)]
    box_size = [min(size, n - o) for o, n in zip(origin, shape)]
    read = [[max(0, o - MARGIN), min(n, o + s + MARGIN)] for o, s, n in zip(origin, box_size, shape)]
    ch = meta["chunks"]
    nchunks = math.prod((b - 1) // c - a // c + 1 for (a, b), c in zip(read, ch))
    out = {"volume": v["volume"], "sample": v["sample"], "long_id": v["long_id"], "voxel_um": v["voxel_um"],
            "url": v["url"], "level": level, "level_shape_zyx": shape, "base_shape_zyx": base["shape"],
            "center_level0_zyx": center, "origin_zyx": origin, "size_zyx": box_size,
            "origin_level0_zyx": [o * f for o in origin], "size_level0_zyx": [s * f for s in box_size],
            "read_zyx": read, "chunks": nchunks, "chunk_bytes": math.prod(ch) * np.dtype(meta["dtype"]).itemsize,
            "model": model}
    out["tiles"] = tiles(out)
    out["gpu_s"] = gpu_seconds(out, model)
    return out


def tiles(p_or_size, tile=TILE, overlap=64, border=16, sd_max=4):
    """Tiles predict3d runs for a box. predict3d puts tiles on one lattice over the whole scan (so a box's field is
    the whole-scan field there) and runs every lattice tile that touches the box plus its border; with villa loaded
    this asks villa's own _canonical_local_tile_positions, else it counts the same lattice here."""
    if isinstance(p_or_size, dict):
        f = 2 ** p_or_size["level"]
        starts = p_or_size["origin_zyx"]
        sizes = p_or_size["size_zyx"]
        shape = p_or_size["level_shape_zyx"]
    else:
        sizes, starts, shape = list(p_or_size), [10 * 1024] * 3, [100 * 1024] * 3
    stride = tile - overlap
    try:
        from tiled_predict3d import _canonical_local_tile_positions as positions
    except ImportError:
        positions = None
    n = 1
    for s0, sz, vol in zip(starts, sizes, shape):
        padded = -(-(sz + 2 * border) // sd_max) * sd_max
        if positions is not None:
            n *= len(positions(volume_size=vol, crop_start=s0, crop_padded_size=padded, tile_size=tile,
                               stride=stride, border=border, scaledown_multiple=sd_max))
        else:
            first, last = max(0, (s0 - tile) // stride), (s0 + padded) // stride
            n *= sum(1 for k in range(first, last + 1) if k * stride - s0 < padded and k * stride - s0 + tile > 0)
    return n


def gpu_seconds(p_or_size, model="lasagna"):
    """The GPU time to ask ZeroGPU for: the model's start-up plus its per-tile time, with a margin of 1.5."""
    spec = MODELS[model]
    return int(math.ceil(1.5 * (spec["startup_s"] + spec["tile_s"] * tiles(p_or_size))))


# ---------------------------------------------------------------- the CT

def stage(p, root):
    """The CT around the box on local disk, laid out like the open data: an OME-Zarr group whose level 0 is only its
    metadata (predict3d reads the scan's base shape from it) and whose input level holds the chunks it reads."""
    root = Path(root)
    shutil.rmtree(root, ignore_errors=True)
    meta0 = get_json(f"{p['url']}0/.zarray")
    meta = get_json(f"{p['url']}{p['level']}/.zarray")
    zattrs = get_json(f"{p['url']}.zattrs")
    sep = meta.get("dimension_separator", ".")
    (root / "0").mkdir(parents=True)
    (root / "0" / ".zarray").write_text(json.dumps(meta0))
    lvl = root / str(p["level"])
    lvl.mkdir(parents=True, exist_ok=True)
    (lvl / ".zarray").write_text(json.dumps(meta))
    (root / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (root / ".zattrs").write_text(json.dumps(zattrs))
    ch = meta["chunks"]
    keys = [(i, j, k) for i in range(p["read_zyx"][0][0] // ch[0], (p["read_zyx"][0][1] - 1) // ch[0] + 1)
            for j in range(p["read_zyx"][1][0] // ch[1], (p["read_zyx"][1][1] - 1) // ch[1] + 1)
            for k in range(p["read_zyx"][2][0] // ch[2], (p["read_zyx"][2][1] - 1) // ch[2] + 1)]

    def one(key):
        name = sep.join(map(str, key))
        raw = http_get(f"{p['url']}{p['level']}/{name}")
        if raw is None:
            return 0
        dest = lvl.joinpath(*name.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return len(raw)

    t = time.time()
    with concurrent.futures.ThreadPoolExecutor(32) as ex:
        sizes = list(ex.map(one, keys))
    return {"chunks": len(keys), "written": sum(1 for s in sizes if s), "bytes": sum(sizes),
            "seconds": round(time.time() - t, 2), "input": str(lvl)}


def read_box(arr_path, box):
    """One zarr array's values in a box [[z0, z1], [y0, y1], [x0, x1]] (zarr 3 reads villa's v2 output)."""
    import zarr
    a = zarr.open_array(str(arr_path), mode="r")
    return np.asarray(a[box[0][0]:box[0][1], box[1][0]:box[1][1], box[2][0]:box[2][1]])


def ct_box(p, root):
    lvl = Path(root) / str(p["level"])
    import zarr
    a = zarr.open_array(str(lvl), mode="r")
    o, s = p["origin_zyx"], p["size_zyx"]
    return np.asarray(a[o[0]:o[0] + s[0], o[1]:o[1] + s[1], o[2]:o[2] + s[2]])


# ---------------------------------------------------------------- code and weights

def sha256_file(path, block=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for part in iter(lambda: fh.read(block), b""):
            h.update(part)
    return h.hexdigest()


def _fetch_villa(dest):
    """villa's lasagna/ and vesuvius/src/ at the pinned commit: a sparse, blobless git fetch, else GitHub's tarball."""
    commit = VILLA["commit"]
    tmp = dest.with_name(dest.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        git = ["git", "-C", str(tmp)]
        for cmd in (["init", "-q"], ["remote", "add", "origin", VILLA["repo"]],
                    ["sparse-checkout", "set", *[k.rstrip("/") for k in VILLA["keep"]]],
                    ["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", commit],
                    ["checkout", "-q", "FETCH_HEAD"]):
            subprocess.run(git + cmd, capture_output=True, text=True, check=True, timeout=900)
        head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        if head != commit:
            raise RuntimeError(f"git fetched {head}, not {commit}")
        shutil.rmtree(tmp / ".git", ignore_errors=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        log(f"git fetch of villa failed ({getattr(exc, 'stderr', None) or exc}); trying the tarball")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        root = tmp.resolve()
        req = urllib.request.Request(VILLA["tarball"].format(commit=commit), headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=900) as resp, tarfile.open(fileobj=resp, mode="r|gz") as tf:
            for m in tf:
                _, _, rel = m.name.partition("/")
                if not rel.startswith(VILLA["keep"]) or m.issym() or m.islnk():
                    continue
                target = (root / rel).resolve()
                if root not in target.parents:
                    continue
                if m.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif m.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tf.extractfile(m) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
    if not (tmp / VILLA["check"]).is_file():
        raise RuntimeError(f"villa at {commit} has no {VILLA['check']}")
    (tmp / "COMMIT").write_text(commit + "\n")
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)


def ensure_villa(cache=CACHE):
    """villa's lasagna on sys.path (as top-level modules and as the `lasagna` package, the way its own install lays
    them out) with vesuvius/src beside it. LASFIELD_VILLA names a local villa checkout instead."""
    if os.environ.get("LASFIELD_VILLA"):
        root = Path(os.environ["LASFIELD_VILLA"]).expanduser().resolve()
        source = "local checkout (LASFIELD_VILLA)"
    else:
        root = Path(cache) / f"villa-{VILLA['commit'][:12]}"
        if not (root / "COMMIT").is_file():
            log(f"fetching villa {VILLA['commit'][:12]}")
            _fetch_villa(root)
        source = "pinned download"
    shim = Path(cache) / "villa-shim"
    shim.mkdir(parents=True, exist_ok=True)
    link = shim / "lasagna"
    if not link.exists():
        link.symlink_to(root / "lasagna", target_is_directory=True)
    for path in (root / "vesuvius" / "src", shim, root / "lasagna"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    os.environ["PYTHONPATH"] = os.pathsep.join([str(root / "lasagna"), str(shim), str(root / "vesuvius" / "src"),
                                                os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return {"source": source, "commit": VILLA["commit"], "path": str(root)}


def ensure_weights(cache=CACHE):
    """The checkpoint from the Hub at its pinned revision, refused unless its SHA-256 matches. LASFIELD_WEIGHTS names
    a local copy of model_current.pt instead (its SHA-256 is still checked)."""
    if os.environ.get("LASFIELD_WEIGHTS"):
        path = Path(os.environ["LASFIELD_WEIGHTS"]).expanduser()
    else:
        from huggingface_hub import hf_hub_download
        path = Path(hf_hub_download(WEIGHTS["repo"], WEIGHTS["file"], revision=WEIGHTS["revision"],
                                    cache_dir=str(Path(cache) / "hub")))
    digest = sha256_file(path)
    if digest != WEIGHTS["sha256"]:
        raise RuntimeError(f"{WEIGHTS['repo']}/{WEIGHTS['file']} has SHA-256 {digest}, not {WEIGHTS['sha256']}")
    return path


# ---------------------------------------------------------------- the models

def predict3d_argv(p, ct_input, out_json, checkpoint, device):
    """villa predict3d's command line for the box, as its CLI takes it: --crop is x y z w h d in the scan's base
    (level 0) voxels, which predict3d divides by the input level's factor (its log: base_crop, input_crop).
    Synchronous flush and accumulation (no worker processes): the stored field is the same."""
    o, s = p["origin_level0_zyx"], p["size_level0_zyx"]
    return ["predict3d", "--input", str(ct_input), "--output", str(out_json), "--unet-checkpoint", str(checkpoint),
            "--tile-size", str(TILE), "--crop", str(o[2]), str(o[1]), str(o[0]), str(s[2]), str(s[1]), str(s[0]),
            "--device", device, "--no-download", "--flush-workers", "0", "--accumulator-workers", "0"]


POOL_CPUS = 8                # pyramid processes predict3d may start (its default is every CPU of the host)


@__import__("contextlib").contextmanager
def _pool_friendly():
    """Let predict3d's OME-Zarr pyramid step start its process pool when it runs inside a daemon process (ZeroGPU
    runs a GPU call in one, and Python refuses children there), and cap that pool at POOL_CPUS. The pool's processes
    only downsample chunks on the CPU. Restored on exit."""
    import multiprocessing as mp
    proc = mp.current_process()
    was_daemon = proc._config.get("daemon")
    real = mp.cpu_count
    mp.cpu_count = lambda: max(1, min(POOL_CPUS, real()))
    if was_daemon:
        proc._config["daemon"] = False
    try:
        yield
    finally:
        mp.cpu_count = real
        if was_daemon:
            proc._config["daemon"] = was_daemon


def run_villa_lasagna(p, ct_input, out_dir, device, checkpoint):
    """villa's predict3d in this process. Returns its exit code, wall seconds and the tail of its log."""
    import contextlib
    import preprocess_cos_omezarr as pco
    out_dir = Path(out_dir)
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    out_json = out_dir / f"{p['sample']}-{p['volume']}.lasagna.json"
    argv = predict3d_argv(p, ct_input, out_json, checkpoint, device)
    buf = io.StringIO()
    t = time.time()

    class Tee(io.TextIOBase):
        def write(self, s):
            buf.write(s)
            sys.__stdout__.write(s)
            return len(s)

    try:
        with contextlib.redirect_stdout(Tee()), contextlib.redirect_stderr(Tee()), _pool_friendly():
            rc = pco.cli_main(argv)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1
    return {"exit": int(rc or 0), "wall_s": round(time.time() - t, 2), "argv": argv,
            "log_tail": buf.getvalue()[-6000:], "manifest": str(out_json)}


# The model slot. `offered` False keeps a model off the page and the API until it passes its own held-out test;
# Lasagnetta (the lasagna student) and any better net come in here with their own runner, checkpoint and costs.
MODELS = {
    "lasagna": {"title": "villa lasagna (exact)", "offered": True, "run": run_villa_lasagna,
                "about": "villa's own predict3d with the scrollprize/lasagna checkpoint (MIT): the same field villa "
                         "makes, at the same grids (cos at half, the rest at a quarter of the input level)",
                # 25 Oct 2026, L4: 310 ms a 192^3 tile end to end; the GPU here is faster, so these are ceilings
                "startup_s": 25, "tile_s": 0.35},
}


# ---------------------------------------------------------------- the field

def field_boxes(p, manifest):
    """Each channel's array path and the box covering the plan's box in that channel's grid."""
    man = json.loads(Path(manifest).read_text())
    root = Path(manifest).parent
    out = {}
    for name in CHANNELS:
        g = man["groups"][name]
        sd = 2 ** int(g["scaledown"])
        box = [[o // sd, -(-(o + s) // sd)] for o, s in zip(p["origin_level0_zyx"], p["size_level0_zyx"])]
        out[name] = {"path": root / g["zarr"], "scaledown": int(g["scaledown"]), "box": box}
    return out, man


def read_field(p, manifest):
    boxes, man = field_boxes(p, manifest)
    arrays = {n: read_box(b["path"], b["box"]) for n, b in boxes.items()}
    return arrays, boxes, man


def decode_normal(nx_u8, ny_u8):
    """The unit normal from stored nx, ny (villa's encode_normal_nxny_u8 flips n so that nz >= 0)."""
    nx = (nx_u8.astype(np.float32) - 128.0) / 127.0
    ny = (ny_u8.astype(np.float32) - 128.0) / 127.0
    nz = np.sqrt(np.clip(1.0 - nx * nx - ny * ny, 0.0, 1.0))
    n = np.stack([nx, ny, nz])
    return n / (np.linalg.norm(n, axis=0, keepdims=True) + 1e-8)


def _corr(a, b, mask):
    a, b = a[mask].astype(np.float64), b[mask].astype(np.float64)
    if a.size < 100 or a.std() == 0 or b.std() == 0:
        return None
    return round(float(np.corrcoef(a, b)[0, 1]), 4)


def compare(mine, theirs):
    """Agreement of two fields on the same grids: Pearson r of cos and grad_mag where either is non-zero, and the
    median angle between normals (sign ignored) where both are, over all those voxels and over the strong half (our
    grad_mag at or above its median there). Where the layer signal is weak the normal is barely defined and tiny
    numerical differences turn it, so the strong half is the fair test."""
    m_cos = (mine["cos"] > 0) | (theirs["cos"] > 0)
    m_oth = (mine["grad_mag"] > 0) | (theirs["grad_mag"] > 0)
    both = (mine["nx"] > 0) & (theirs["nx"] > 0)
    out = {"cos_r": _corr(mine["cos"], theirs["cos"], m_cos),
           "grad_mag_r": _corr(mine["grad_mag"], theirs["grad_mag"], m_oth), "normal_median_deg": None,
           "voxels": int(m_cos.sum())}
    if both.sum() >= 100:
        a, b = decode_normal(mine["nx"], mine["ny"]), decode_normal(theirs["nx"], theirs["ny"])
        dot = np.abs((a * b).sum(axis=0))
        out["normal_median_deg"] = round(float(np.degrees(np.arccos(np.clip(np.median(dot[both]), 0, 1)))), 2)
        g = mine["grad_mag"]
        strong = both & (g >= np.median(g[both]))
        if strong.sum() >= 100:
            out["normal_median_deg_strong"] = round(
                float(np.degrees(np.arccos(np.clip(np.median(dot[strong]), 0, 1)))), 2)
    return out


def read_published(pub, boxes, shift=(0, 0, 0)):
    """The published field's values in the same boxes, optionally shifted (in each channel's voxels)."""
    import zarr
    out = {}
    for name, b in boxes.items():
        g = (pub["groups"] or {}).get(name)
        if not g or int(g["scaledown"]) != b["scaledown"]:
            return None
        a = zarr.open_array(pub["url"] + g["zarr"], mode="r", zarr_format=2)
        box = [[lo + d, hi + d] for (lo, hi), d in zip(b["box"], shift)]
        if any(lo < 0 or hi > n for (lo, hi), n in zip(box, a.shape)):
            return None
        out[name] = np.asarray(a[box[0][0]:box[0][1], box[1][0]:box[1][1], box[2][0]:box[2][1]])
    return out


CONTROL_SHIFT = 48           # input-level voxels: the control reads the published field this far away in y and x


OPEN_DATA_NORMALS = ("cos and grad_mag should match the open data's field exactly. Its normals can differ in "
                     "parts of a box: villa changed how lasagna estimates normals after the open data's fields "
                     "were made (April 2026, by their run names), and Make a field runs the later code, the same "
                     "as this Space's ten whole-scan fields, which it matches exactly")


def agreement(p, arrays, boxes):
    """How close this field is to the open data's own lasagna field for the scan, where one exists, with a control
    that must score lower: the published field read CONTROL_SHIFT input voxels away along y and x (a few papyrus
    layers), the same physical offset on every channel's grid."""
    pub = published_field(volume(p["volume"]))
    if not pub:
        return {"published": None, "note": "the open data has no lasagna field for this volume at this level"}
    shift0 = CONTROL_SHIFT * 2 ** p["level"]
    try:
        same = read_published(pub, boxes)
        shifted = {}
        for name, b in boxes.items():
            d = shift0 // 2 ** b["scaledown"]
            r = read_published(pub, {name: b}, (0, d, d))
            if r is None:
                shifted = None
                break
            shifted[name] = r[name]
    except Exception as exc:  # noqa: BLE001  (reported, never fatal)
        return {"published": pub["run"], "error": f"{type(exc).__name__}: {exc}"[:300]}
    if same is None:
        return {"published": pub["run"], "note": "the published field uses other grids; not compared"}
    out = {"published": pub["run"], "published_url": pub["url"], "published_source": pub.get("source"),
           "same_box": compare(arrays, same)}
    if pub.get("note"):
        out["published_note"] = pub["note"]
    if pub.get("source") == "open-data":
        out["normals_note"] = OPEN_DATA_NORMALS
    if shifted is not None:
        out["control_shifted"] = compare(arrays, shifted)
        out["control_note"] = (f"the published field {CONTROL_SHIFT} input voxels away in y and x: "
                               "it must agree less than the same box")
    return out


# ---------------------------------------------------------------- pictures and the download

def _u8(img, lo=None, hi=None):
    img = img.astype(np.float32)
    lo = np.percentile(img, 1) if lo is None else lo
    hi = np.percentile(img, 99) if hi is None else hi
    return np.clip((img - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)


def _up(img, n):
    return np.repeat(np.repeat(img, n, axis=0), n, axis=1) if n > 1 else img


def _resize(img, shape):
    """An image (H, W) or (H, W, 3) uint8 resized to `shape` (H, W) with bilinear smoothing, for display only."""
    from PIL import Image
    return np.asarray(Image.fromarray(img).resize((int(shape[1]), int(shape[0])), Image.BILINEAR))


def picture(ct, arrays, boxes, axis=0):
    """One middle slice through the box along `axis` (0 z, 1 y, 2 x): CT, cos, grad_mag and the normal as color
    (|x| red, |y| green, |z| blue), side by side at the CT's grid. Returns an RGB uint8 array."""
    def mid(a):
        return np.take(a, a.shape[axis] // 2, axis=axis)
    ct_img = _u8(mid(ct))
    shape = ct_img.shape
    panels = [np.stack([ct_img] * 3, -1)]
    for name in ("cos", "grad_mag"):
        img = _u8(mid(arrays[name]), 0, 255 if name == "cos" else None)
        panels.append(np.stack([_resize(img, shape)] * 3, -1))
    n = decode_normal(mid(arrays["nx"]), mid(arrays["ny"]))
    rgb = (np.abs(np.moveaxis(n, 0, -1)) * 255).astype(np.uint8)
    rgb[mid(arrays["nx"]) == 0] = 0
    panels.append(_resize(rgb, shape))
    gap = np.full((shape[0], 6, 3), 255, np.uint8)
    row = []
    for i, t in enumerate(panels):
        row += [t] + ([gap] if i < len(panels) - 1 else [])
    return np.concatenate(row, axis=1)


PANELS = ("CT", "cos", "grad_mag", "normal")
LEGEND = "normal as color: x red, y green, z blue · villa lasagna, model output"


def compose(pictures, title="", note=LEGEND):
    """The three rows (z, y, x middle slices) under one header naming the panels, each row named on its left, on a
    white card. Text is sized for the card to be shown about 700 px wide. Returns an RGB uint8 array."""
    from PIL import Image, ImageDraw, ImageFont
    rows = [_fit(r, pictures[0].shape[:2]) if r.shape != pictures[0].shape else r for r in pictures]
    h, w = rows[0].shape[:2]
    k = max(1.0, w / 640)
    try:
        font = ImageFont.load_default(size=round(14 * k))
        bold = ImageFont.load_default(size=round(16 * k))
    except TypeError:                      # Pillow before 10.1
        font = bold = ImageFont.load_default()
    pw = (w - 18) // 4
    left, gap = round(66 * k), round(8 * k)
    top = round(26 * k) + (round(30 * k) if title else 0)
    foot = round(26 * k) if note else 0
    canvas = Image.new("RGB", (left + w + gap, top + 3 * h + 3 * gap + foot), (255, 255, 255))
    d = ImageDraw.Draw(canvas)
    if title:
        d.text((left, round(6 * k)), title, fill=(35, 32, 28), font=bold)
    for i, name in enumerate(PANELS):
        d.text((left + i * (pw + 6) + 2, top - round(21 * k)), name, fill=(93, 85, 75), font=font)
    for i, (r, name) in enumerate(zip(rows, ("z slice", "y slice", "x slice"))):
        y0 = top + i * (h + gap)
        canvas.paste(Image.fromarray(r), (left, y0))
        d.text((round(6 * k), y0 + h // 2 - round(8 * k)), name, fill=(93, 85, 75), font=font)
    if note:
        d.text((left, top + 3 * h + 2 * gap + round(4 * k)), note, fill=(93, 85, 75), font=font)
    return np.asarray(canvas)


def png(rgb):
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def package(out_dir, p, arrays, receipt, dest):
    """The download: villa's own output folder (its .lasagna.json and four OME-Zarr channels, holding only this
    box, in the scan's base coordinates, so lasagna's fit opens it as is), field.npz with the box's arrays, and the
    receipt."""
    dest = Path(dest)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(Path(out_dir).rglob("*")):
            if f.is_file():
                zf.write(f, f"villa/{f.relative_to(out_dir)}")
        buf = io.BytesIO()
        np.savez_compressed(buf, **arrays)
        zf.writestr("field.npz", buf.getvalue())
        zf.writestr("receipt.json", json.dumps(receipt, indent=1))
        zf.writestr("README.txt", README_TXT)
    return dest


README_TXT = """Lasagna field for one box, made by the Lasagna Fields Space (huggingface.co/spaces/SharpMeow/lasagna-fields).

villa/       villa lasagna predict3d's own output: SCAN.lasagna.json and SCAN_{cos,grad_mag,nx,ny}.ome.zarr. Only the
             chunks of this box are written; the arrays have the whole scan's shape, in its base (level 0) frame, so
             villa's lasagna fit (lasagna/fit.py) opens the manifest as is.
field.npz    the box as numpy arrays: cos and grad_mag, nx and ny (uint8, as villa stores them). Grids: see receipt.json
             (boxes: each channel's voxel box and scaledown from level 0).
receipt.json what ran: scan, box, model, villa commit, checkpoint SHA-256, timings, and the agreement check.

Encodings (villa): cos = clip(cos * 255); grad_mag = clip(grad_mag * 1000 * grad_mag_factor); nx, ny = the unit
normal's x and y times 127 plus 128, with the normal flipped so its z is not negative.
Scan data: Vesuvius Challenge open data, CC BY-NC 4.0. Model and code: ScrollPrize/villa lasagna, MIT.
This is model output: geometry inputs, not a reading of any text.
"""


# ---------------------------------------------------------------- one run, end to end (no GPU decorator here)

def prepare(p, work):
    """Everything before the GPU: code, weights and the CT on disk."""
    t = time.time()
    code = ensure_villa()
    ck = ensure_weights()
    st = stage(p, Path(work) / "ct")
    return {"code": code, "checkpoint": str(ck), "stage": st, "prepare_s": round(time.time() - t, 2)}


def finish(p, prep, ran, work, out_root):
    """Everything after the GPU: read the field, compare, draw, pack."""
    if ran["exit"] != 0:
        raise FieldError(f"villa predict3d exited {ran['exit']}: {ran['log_tail'][-800:]}")
    arrays, boxes, man = read_field(p, ran["manifest"])
    if not any(int(a.max()) for a in arrays.values()):
        raise FieldError("the field is empty: the box is probably outside the scroll (masked CT is all zero there)")
    ct = ct_box(p, Path(work) / "ct")
    pictures = [picture(ct, arrays, boxes, axis) for axis in (0, 1, 2)]
    agree = agreement(p, arrays, boxes)
    receipt = {"made_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "plan": p,
               "model": {"id": p["model"], "title": MODELS[p["model"]]["title"],
                         "villa_commit": VILLA["commit"], "checkpoint": f"{WEIGHTS['repo']}@{WEIGHTS['revision']}",
                         "checkpoint_file": WEIGHTS["file"], "checkpoint_sha256": WEIGHTS["sha256"]},
               "predict3d_argv": [a if not a.startswith("/") else Path(a).name for a in ran["argv"]],
               "manifest": {k: man[k] for k in man if k != "groups"},
               "boxes": {n: {"scaledown": b["scaledown"], "box_zyx": b["box"]} for n, b in boxes.items()},
               "timings": {"stage_s": prep["stage"]["seconds"], "stage_bytes": prep["stage"]["bytes"],
                           "model_s": ran["wall_s"]},
               "agreement": agree,
               "claim": "Model output: a lasagna field is geometry fitted by a model, not a reading of any text."}
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    stem = f"{p['sample']}-{p['volume']}-z{p['center_level0_zyx'][0]}-y{p['center_level0_zyx'][1]}-x{p['center_level0_zyx'][2]}-s{p['size_zyx'][0]}"
    zpath = package(Path(ran["manifest"]).parent, p, arrays, receipt, out_root / f"{stem}.zip")
    return {"receipt": receipt, "zip": str(zpath), "pictures": pictures, "arrays": arrays}


def make(p, device=None, work=None, out_root=None, runner=None):
    """One field on this computer: stage, run, finish. `runner(p, ct_input, out_dir, device, checkpoint)` replaces
    the model call (the Space passes its ZeroGPU-decorated one)."""
    import torch
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    work = Path(work or tempfile.mkdtemp(prefix="lasfield-"))
    prep = prepare(p, work)
    run = runner or MODELS[p["model"]]["run"]
    ran = run(p, prep["stage"]["input"], work / "out", device, prep["checkpoint"])
    return finish(p, prep, ran, work, out_root or work / "dl")


# ---------------------------------------------------------------- self-test (no network, no model)

def selftest():
    """The parts that need neither network nor model: grids, the tile count, the GPU ask, comparison and the
    control, decoding and pictures. Each check can fail."""
    ok = []
    assert level_for(9.362) == 0 and level_for(8.64) == 0 and level_for(2.399) == 2 and level_for(1.129) == 3
    ok.append("levels")
    assert tiles([256] * 3) < tiles([512] * 3)
    assert gpu_seconds([256] * 3) < gpu_seconds([512] * 3)
    ok.append("tiles")
    rng = np.random.default_rng(0)
    z = np.arange(64)[:, None, None] * np.ones((1, 64, 64))
    cos = (np.cos(z / 3.0) * 127 + 128).astype(np.uint8)
    f = {"cos": cos, "grad_mag": (cos // 2 + 1).astype(np.uint8), "nx": np.full_like(cos, 128),
         "ny": np.full_like(cos, 128)}
    g = {k: np.clip(v.astype(int) + rng.integers(-3, 4, v.shape), 1, 255).astype(np.uint8) for k, v in f.items()}
    c_same = compare(f, g)
    c_shift = compare(f, {k: np.roll(v, 5, axis=0) for k, v in g.items()})
    assert c_same["cos_r"] > 0.99 and c_shift["cos_r"] < 0.5, (c_same, c_shift)
    assert c_same["normal_median_deg"] < 3, c_same
    ok.append("compare and control")
    n = decode_normal(np.array([255], np.uint8), np.array([128], np.uint8))
    assert abs(n[0, 0] - 1) < 0.01 and abs(n[2, 0]) < 0.1
    ok.append("normals")
    boxes = {"cos": {"scaledown": 1}, "grad_mag": {"scaledown": 2}, "nx": {"scaledown": 2}, "ny": {"scaledown": 2}}
    ct = rng.integers(0, 255, (128, 128, 128)).astype(np.uint8)
    arr = {"cos": cos, "grad_mag": f["grad_mag"][::2, ::2, ::2], "nx": f["nx"][::2, ::2, ::2],
           "ny": f["ny"][::2, ::2, ::2]}
    pic = picture(ct, arr, boxes, 0)
    assert pic.shape == (128, 4 * 128 + 18, 3), pic.shape
    card = compose([pic, pic, pic], "test")
    assert card.shape[0] > 3 * 128 and card.shape[1] > pic.shape[1], card.shape
    ok.append("pictures")
    argv = predict3d_argv({"origin_level0_zyx": [1, 2, 3], "size_level0_zyx": [4, 5, 6]}, "in", "out.json", "ck.pt",
                          "cuda")
    assert argv[argv.index("--crop") + 1:argv.index("--crop") + 7] == ["3", "2", "1", "6", "5", "4"]
    ok.append("predict3d crop order")
    return {"passed": True, "checks": ok}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == "selftest":
        print(json.dumps(selftest(), indent=1))
        return 0
    if argv[0] == "run":
        vid, z, y, x = argv[1:5]
        size = int(argv[5]) if len(argv) > 5 else DEFAULT_SIZE
        p = plan(vid, z, y, x, size)
        log(json.dumps(p))
        r = make(p, out_root=os.environ.get("LASFIELD_OUT") or ".")
        print(json.dumps(r["receipt"], indent=1))
        print(r["zip"])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
