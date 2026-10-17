"""Scroll Lens core: everything except the web page.

A visitor picks a point inside one of the released 2.4 um scans listed in VOLUMES. Scroll Lens reads the cube of
the scan around that point from the Vesuvius Challenge open-data bucket and runs three models the Vesuvius
Challenge released with the PHerc. Paris 4 paper (Angelotti et al. 2026, arXiv:2606.29085) on it:

- dinovol, a 3D DINO model that turns every 8 x 8 x 8 voxel patch into an 864-number embedding;
- ink_3d_dino_guided, a 3D U-Net that marks ink voxels directly in the scan (made for PHerc. Paris 4);
- surface_recto_3dunet, a 3D U-Net that marks the written (recto) surface of each papyrus sheet.

Clicks then light up every patch whose embedding is close to the clicked ones: the expert-click method the
organizers used to build the reference ink embedding behind ink_3d_dino_guided. Everything here is model output,
not a reading; a cube is 0.6 mm across, smaller than one letter.

No gradio here, and torch is imported only inside the model code, so the tests run with numpy alone.

  python3 lens.py volumes                       the scans this Space may read
  python3 lens.py look PHercParis4 Z Y X [--size 128] [--layers dino,ink,surface] [--out DIR]
  python3 lens.py files                         the files of the Space, with their SHA-256
  python3 lens.py stage DEST                    copy them into DEST (absent or empty), laid out as the Space runs
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = "1.1.1"
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
CHUNK = 128                 # every listed scan is stored as uncompressed uint8 chunks of 128^3 voxels
SIZES = (128, 256)          # cube sides in voxels; 256 is the models' training patch, 128 fits a CPU
PATCH = 8                   # dinovol embeds each 8^3 voxel patch
EMBED_DIM = 864
MIN_FOREGROUND = 0.05       # a cube with less papyrus than this (the scans are masked to 0 outside it) is refused
REDUCED_DIM = 128           # gallery cubes keep this many components of each embedding (see reduce_grid)
TAU = 0.5                   # the threshold the organizers used on cosine similarity to their ink reference
MAX_CONCEPT_BYTES = 4 << 20
USER_AGENT = f"scroll-lens/{VERSION}"


class LensError(Exception):
    """A refusal with a message meant for the visitor."""


# ---------------------------------------------------------------- the scans this Space may read
#
# Only these volumes, all about 2.4 um scans at full resolution (level 0), the scale dinovol was trained on. None of
# them is on the First Letters or Grand Prize eligible lists (kit/data/prizes-2026-10-11.json). Anything else is
# refused before a byte is fetched. "role" says what each model saw of the scroll, from the model cards and the
# checkpoints' own training configs (read 16 October 2026).

INK_TEACHER = ("Not trained on this scroll, but its teacher model (stage 1) was trained on this scroll's "
               "ink labels.")
VOLUMES = {
    "PHercParis4": dict(
        scroll="PHerc. Paris 4", scan="20260411134726-2.400um-0.2m-78keV-masked.zarr", voxel_um=2.400,
        shape=(75784, 32693, 32693),
        role=dict(dino="Trained on this scan.", ink="Trained on this scroll: the model was made for it.",
                  surface="Not in its training list."),
        note="Scroll 1 of the Vesuvius Challenge. Unwrapped and read in Angelotti et al. 2026, where ink is "
             "visible in the scan itself. Its title is still an open prize."),
    "PHerc0139": dict(
        scroll="PHerc. 139", scan="20260102150214-2.399um-0.2m-78keV-masked.zarr", voxel_um=2.399,
        shape=(76953, 26511, 26511),
        role=dict(dino="Trained on this scan.", ink=INK_TEACHER, surface="Trained on this scroll."),
        note="The scroll Unroll shows in 3D, with 37 traced windings and published ink detection."),
    "PHerc1667": dict(
        scroll="PHerc. 1667 (Scroll 4)", scan="20251217075048-2.399um-0.2m-78keV-masked.zarr", voxel_um=2.399,
        shape=(37076, 15229, 15229),
        role=dict(dino="Not in its training list.", ink=INK_TEACHER, surface="Trained on this scroll."),
        note="The one scan here that dinovol never saw in training."),
    "PHerc0500P2": dict(
        scroll="PHerc. 500P2", scan="20250526151718-2.215um-0.4m-111keV-masked.zarr", voxel_um=2.215,
        shape=(28096, 18209, 18209),
        role=dict(dino="Trained on this scan.", ink=INK_TEACHER, surface="Trained on this scroll."),
        note="Seen in training by all three models."),
    "PHerc0343P": dict(
        scroll="PHerc. 343P", scan="20260304131111-2.215um-0.4m-111keV-masked.zarr", voxel_um=2.215,
        shape=(20714, 13155, 13155),
        role=dict(dino="Trained on this scan.", ink="Not in its training list.",
                  surface="Trained on this scroll."),
        note="The First Letters prize for PHerc. 343 was awarded on 8 October 2026."),
    "PHerc0814": dict(
        scroll="PHerc. 814", scan="20260309142202-2.399um-0.2m-78keV-masked.zarr", voxel_um=2.399,
        shape=(74568, 23891, 23891),
        role=dict(dino="Trained on this scan.", ink=INK_TEACHER, surface="Not in its training list."),
        note=""),
    "PHerc0009B": dict(
        scroll="PHerc. 9B", scan="20250820154339-2.401um-0.3m-77keV-masked.zarr", voxel_um=2.401,
        shape=(29112, 28259, 28259),
        role=dict(dino="Trained on this scan.", ink=INK_TEACHER, surface="Not in its training list."),
        note=""),
    "PHercMAN5": dict(
        scroll="PHerc. MAN 5", scan="20260311104824-2.399um-0.2m-78keV-masked.zarr", voxel_um=2.399,
        shape=(31640, 17495, 17495),
        role=dict(dino="Trained on this scan.", ink=INK_TEACHER, surface="Not in its training list."),
        note=""),
    "PHerc1299": dict(
        scroll="PHerc. 1299", scan="20260309130042-2.399um-0.2m-78keV-masked.zarr", voxel_um=2.399,
        shape=(49233, 20579, 20579),
        role=dict(dino="Trained on this scan.", ink="Not in its training list.",
                  surface="Not in its training list."),
        note=""),
    "PHerc0332": dict(
        scroll="PHerc. 332", scan="20251211183505-2.399um-0.2m-78keV-masked.zarr", voxel_um=2.399,
        shape=(33592, 15761, 15761),
        role=dict(dino="Trained on this scan.", ink="Not in its training list.",
                  surface="Not in its training list."),
        note=""),
    "PHerc1451": dict(
        scroll="PHerc. 1451", scan="20260319101107-2.399um-0.2m-78keV-masked.zarr", voxel_um=2.399,
        shape=(59944, 20811, 20811),
        role=dict(dino="Trained on this scan.", ink="Not in its training list.",
                  surface="Not in its training list."),
        note=""),
    "PHercMANB": dict(
        scroll="PHerc. MAN B", scan="20260323091048-2.399um-0.2m-78keV-masked.zarr", voxel_um=2.399,
        shape=(72681, 26723, 26723),
        role=dict(dino="Trained on this scan.", ink="Not in its training list.",
                  surface="Listed as MAN Bp on the model card: trained on this scroll."),
        note=""),
}

# PHerc. Paris 4's title is still an open prize, so Scroll Lens never picks Paris 4 points itself: "Surprise me" and the
# gallery use only these, the eight Paris 4 points the organizers listed for training in the ink checkpoint's own
# config (extra_patches.coords_xyz of ckpt_78k_fullsup.pth, sampled with 1024 voxels of jitter), here as z y x.
PARIS4_TRAINING_POINTS = ((37628, 8793, 22167), (35344, 19651, 19735), (70688, 19605, 10649), (41802, 16221, 12261),
                          (41652, 10039, 8270), (41652, 8812, 8006), (41652, 10476, 19310), (41778, 17662, 27405))

LAYERS = ("dino", "ink", "surface")
LAYER_TITLES = {"dino": "3D DINO embeddings", "ink": "3D ink model", "surface": "Recto surface model"}

# ---------------------------------------------------------------- the models and the code they need
#
# Weights come from the Hugging Face Hub at a pinned revision and are refused unless their SHA-256 matches.
# The model code is the organizers' own: dinovol (MIT, with DINOv2 and DINOv3 parts under their licenses) and
# villa's vesuvius package (MIT), each downloaded at a pinned commit and put on sys.path. Nothing of theirs is
# copied into this Space.

MODELS = {
    "dino": dict(repo="scrollprize/dinovol_v2_ps8_with_paris4_352500",
                 revision="6a8cccbafef191a966da815e22ff5c6eae075aae",
                 file="dinovol_v2_ps8_paris4_step352500_teacher_backbone.pt", bytes=863606099,
                 sha256="e041ca870dd2570f8a44d1dd26db1197b3f74121f62023bc774fbc9d40e51a59"),
    "ink": dict(repo="scrollprize/ink_3d_dino_guided", revision="73a79525466037432191284dfa237baf830c49ec",
                file="ckpt_78k_fullsup.pth", bytes=1703138075,
                sha256="5a148c2c1bb730bfa683f2b3e3cdfc2000424003605e42300b527ff90118b303"),
    "ink_reference": dict(repo="scrollprize/ink_3d_dino_guided",
                          revision="73a79525466037432191284dfa237baf830c49ec",
                          file="avg_ref_embedding.npy", bytes=3584,
                          sha256="61bdf93bc5e3fd956eebdbed52618985d27264b8a9e5cb043087d0f234507a81"),
    "surface": dict(repo="scrollprize/surface_recto_3dunet", revision="8ce8a4627e5104dda0af2b05aaa49820c0888774",
                    file="checkpoint_inference_ready.pth", bytes=1138388181,
                    sha256="dd36b3a89b2f4e21a6cafa14fea459f775f846a6ed036f75fb8e6b65aee3137b"),
}
CODE = {
    "dinovol": dict(repo="https://github.com/ScrollPrize/dinovol.git",
                    tarball="https://codeload.github.com/ScrollPrize/dinovol/tar.gz/{commit}",
                    commit="a72fda2b1e02389a8711b3dc6a26215237f35eca", keep="dinovol_2/",
                    check="dinovol_2/model/model.py"),
    "villa": dict(repo="https://github.com/ScrollPrize/villa.git",
                  tarball="https://codeload.github.com/ScrollPrize/villa/tar.gz/{commit}",
                  commit="b29f310957c7b29e7d332f9876e0e487819cfaa3", keep="vesuvius/src/",
                  check="vesuvius/src/vesuvius/models/build/build_network_from_config.py"),
}
CACHE = Path(os.environ.get("LENS_CACHE") or Path(tempfile.gettempdir()) / "scroll-lens")


def log(message):
    print(f"[lens {time.strftime('%H:%M:%S')}] {message}", flush=True)


# ---------------------------------------------------------------- cubes: where and how to read them

def volume_id(vid):
    """The listed scan id for `vid` (case does not matter), or a refusal that lists them."""
    if isinstance(vid, str):
        for k in VOLUMES:
            if k.lower() == vid.strip().lower():
                return k
    raise LensError(f"{vid!r} is not one of the scans this Space may read; choose from {', '.join(VOLUMES)}")


def volume(vid):
    """The listed volume `vid`, or a refusal. Nothing else is ever read."""
    return VOLUMES[volume_id(vid)]


def volume_url(vid, level=0):
    vid = volume_id(vid)
    return f"{BUCKET}/{vid}/volumes/{VOLUMES[vid]['scan']}/{int(level)}"


def cube_origin(vid, center_zyx, size):
    """The corner of the cube of side `size` around `center_zyx` (level-0 voxels, z y x), kept inside the scan. Where
    it can, the corner sits on the scan's 128-voxel chunk grid (so a 256 cube is exactly 8 stored chunks) and the
    point lies at most 64 voxels from the cube's center; near the scan's far edge the cube ends at the edge instead,
    off the grid. The point always lies inside the cube."""
    size = check_size(size)
    shape = volume(vid)["shape"]
    try:
        center = [as_int(c, "each of z, y and x") for c in center_zyx]
    except TypeError:
        raise LensError("give the point as three whole numbers, z y x, in level-0 voxels") from None
    if len(center) != 3:
        raise LensError("give the point as three whole numbers, z y x, in level-0 voxels")
    out = []
    for c, n in zip(center, shape):
        if not 0 <= c < n:
            raise LensError(f"point {center} is outside the scan, whose shape is {list(shape)}")
        o = max(0, (c - size // 2 + CHUNK // 2) // CHUNK * CHUNK)    # nearest grid line, halves rounded up
        if o + size > n:
            o = max(0, n - size)
        out.append(o)
    return tuple(out)


def as_int(value, name):
    """A whole number from an int, an integral float or a string of digits; anything else is a refusal naming it."""
    if isinstance(value, bool):
        raise LensError(f"{name} must be a whole number, not {value!r}")
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise LensError(f"{name} must be a whole number, not {value!r}") from None
    if not math.isfinite(f) or f != int(f):
        raise LensError(f"{name} must be a whole number, not {value!r}")
    return int(f)


def check_size(size):
    size = as_int(size, "the cube side")
    if size not in SIZES:
        raise LensError(f"cube side must be one of {SIZES} voxels, not {size}")
    return size


def chunk_keys(origin, size):
    """The stored chunks (z, y, x indices) that a cube at `origin` of side `size` covers."""
    ranges = [range(o // CHUNK, (o + size - 1) // CHUNK + 1) for o in origin]
    return [(a, b, c) for a in ranges[0] for b in ranges[1] for c in ranges[2]]


def _get(url, timeout=60, tries=3):
    """One object from the open-data bucket, anonymously. None for a missing key (HTTP 404): the bucket stores no
    chunk where the scan holds nothing but the masked-out outside. Throttling and server errors are retried; any
    other refusal (403 included) is an error, never read as an empty chunk."""
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code not in (429, 500, 502, 503, 504):
                raise LensError(f"the open-data bucket refused {url.rsplit('/volumes/', 1)[-1]} (HTTP {exc.code})") \
                    from None
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = exc
        time.sleep(1.5 * (attempt + 1))
    raise LensError(f"could not read the open-data bucket ({last}); try again in a minute")


def _list_keys(prefix, fetch=None):
    """The object keys under `prefix` in the open-data bucket (anonymous S3 ListObjectsV2, which this bucket
    allows), following continuation tokens."""
    import re
    import urllib.parse
    keys, token = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            q["continuation-token"] = token
        raw = (fetch or _get)(f"{BUCKET}/?{urllib.parse.urlencode(q)}")
        text = (raw or b"").decode("utf-8", "replace")
        keys += re.findall(r"<Key>([^<]+)</Key>", text)
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        if "<IsTruncated>true</IsTruncated>" not in text or not m:
            return keys
        token = m.group(1)


def read_cube(vid, origin, size, fetch=_get, workers=8):
    """The uint8 cube of side `size` at `origin` (z y x, level 0), anywhere inside the scan: an origin off the chunk
    grid (a CPU-fallback receipt's) reads the chunks it overlaps and crops. Chunks the bucket does not hold read as 0."""
    import numpy as np
    size = check_size(size)
    shape = volume(vid)["shape"]
    origin = tuple(int(o) for o in origin)
    if any(o < 0 or o + size > n for o, n in zip(origin, shape)):
        raise LensError(f"cube at {list(origin)} is not inside the scan, whose shape is {list(shape)}")
    base = volume_url(vid)
    keys = chunk_keys(origin, size)
    out = np.zeros((size, size, size), np.uint8)

    def one(key):
        raw = fetch(f"{base}/{key[0]}/{key[1]}/{key[2]}")
        if raw is None:
            return key, None
        if len(raw) != CHUNK ** 3:
            raise LensError(f"chunk {key} has {len(raw)} bytes, not {CHUNK ** 3}: not an uncompressed uint8 chunk")
        return key, np.frombuffer(raw, np.uint8).reshape(CHUNK, CHUNK, CHUNK)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for key, chunk in pool.map(one, keys):
            if chunk is None:
                continue
            lo = [max(k * CHUNK, o) for k, o in zip(key, origin)]          # overlap of chunk and cube, scan voxels
            hi = [min((k + 1) * CHUNK, o + size) for k, o in zip(key, origin)]
            dst = tuple(slice(a - o, b - o) for a, b, o in zip(lo, hi, origin))
            src = tuple(slice(a - k * CHUNK, b - k * CHUNK) for a, b, k in zip(lo, hi, key))
            out[dst] = chunk[src]
    return out


def foreground(cube):
    """Fraction of voxels that are papyrus (the listed scans are masked to 0 outside the scroll)."""
    return float((cube > 0).mean())


def check_cube(cube):
    frac = foreground(cube)
    if frac < MIN_FOREGROUND:
        raise LensError(f"only {frac:.1%} of this cube is papyrus; the scan is masked to 0 outside the scroll. "
                        "Pick a point on the papyrus: press Surprise me on the page, or call the random_point "
                        "endpoint.")
    return frac


def random_point(vid, rng, fetch=_get, tries=24, list_fetch=None):
    """A random point on papyrus: read random level-3 chunks (1/8 resolution) and pick a bright voxel in one.
    `list_fetch` reads bucket listings for the fallback (default: `fetch`)."""
    import numpy as np
    shape = volume(vid)["shape"]
    lv = 3
    f = 2 ** lv
    small = [math.ceil(n / f) for n in shape]
    nchunks = [max(1, math.ceil(n / CHUNK)) for n in small]
    base = volume_url(vid, lv)
    for _ in range(tries):
        # stay off the top and bottom tenth of the scroll, where the scan often holds no papyrus
        cz = int(rng.integers(int(nchunks[0] * 0.1), max(int(nchunks[0] * 0.9), int(nchunks[0] * 0.1) + 1)))
        cy, cx = (int(rng.integers(0, n)) for n in nchunks[1:])
        raw = fetch(f"{base}/{cz}/{cy}/{cx}")
        if raw is None or len(raw) != CHUNK ** 3:
            continue
        a = np.frombuffer(raw, np.uint8).reshape(CHUNK, CHUNK, CHUNK)
        # papyrus is the brighter part of a masked scan; a 16-voxel margin keeps the cube away from the mask edge
        inner = a[16:-16, 16:-16, 16:-16]
        idx = np.argwhere(inner > max(1, np.percentile(a[a > 0], 60) if (a > 0).any() else 255))
        if len(idx) < 50:
            continue
        for _ in range(16):
            p = idx[int(rng.integers(0, len(idx)))] + 16
            # the 256 cube around the point (16 voxels each way at this level) must lie inside the scroll mask
            win = a[p[0] - 16:p[0] + 16, p[1] - 16:p[1] + 16, p[2] - 16:p[2] + 16]
            if (win > 0).mean() < 0.9:
                continue
            zyx = [int((c * CHUNK + p[i]) * f + f // 2) for i, c in enumerate((cz, cy, cx))]
            if all(0 <= v < n for v, n in zip(zyx, shape)):
                return tuple(zyx)
    # Some scans store few level-3 chunks (most of their chunk grid lies outside the scroll), so blind draws can all
    # land on missing keys. Then draw among the chunks the bucket holds, from a listing of one z slab at a time. The
    # blind draws come first so that points drawn before this fallback existed are drawn again unchanged.
    v = volume(vid)
    prefix = f"{volume_id(vid)}/volumes/{v['scan']}/{lv}/"
    for _ in range(tries):
        cz = int(rng.integers(int(nchunks[0] * 0.1), max(int(nchunks[0] * 0.9), int(nchunks[0] * 0.1) + 1)))
        stored = set()
        for key in _list_keys(f"{prefix}{cz}/", fetch=list_fetch or fetch):
            parts = key[len(prefix):].split("/")
            if len(parts) == 3 and all(x.isdigit() for x in parts):
                stored.add((int(parts[1]), int(parts[2])))
        # chunks whose four in-plane neighbors are stored too lie inside the scroll, away from the mask edge
        inner = sorted(k for k in stored if all((k[0] + dy, k[1] + dx) in stored
                                                  for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))))
        pool = inner or sorted(stored)
        if not pool:
            continue
        cy, cx = pool[int(rng.integers(0, len(pool)))]
        raw = fetch(f"{base}/{cz}/{cy}/{cx}")
        if raw is None or len(raw) != CHUNK ** 3:
            continue
        a = np.frombuffer(raw, np.uint8).reshape(CHUNK, CHUNK, CHUNK)
        inner_a = a[16:-16, 16:-16, 16:-16]
        idx = np.argwhere(inner_a > max(1, np.percentile(a[a > 0], 60) if (a > 0).any() else 255))
        if len(idx) < 50:
            continue
        for _ in range(16):
            p = idx[int(rng.integers(0, len(idx)))] + 16
            win = a[p[0] - 16:p[0] + 16, p[1] - 16:p[1] + 16, p[2] - 16:p[2] + 16]
            if (win > 0).mean() < 0.9:
                continue
            zyx = [int((c * CHUNK + p[i]) * f + f // 2) for i, c in enumerate((cz, cy, cx))]
            if all(0 <= v < n for v, n in zip(zyx, shape)):
                return tuple(zyx)
    raise LensError("could not find papyrus in this scan after several tries; try again")


# ---------------------------------------------------------------- downloads: code and weights

def sha256_file(path, block=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for part in iter(lambda: fh.read(block), b""):
            h.update(part)
    return h.hexdigest()


def _fetch_code(name, dest):
    """One pinned repository's needed subtree: a sparse, blobless git fetch of the commit, else GitHub's tarball."""
    spec = CODE[name]
    commit = spec["commit"]
    tmp = dest.with_name(dest.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        git = ["git", "-C", str(tmp)]
        for cmd in (["init", "-q"], ["remote", "add", "origin", spec["repo"]],
                    ["sparse-checkout", "set", spec["keep"].rstrip("/")],
                    ["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", commit],
                    ["checkout", "-q", "FETCH_HEAD"]):
            subprocess.run(git + cmd, capture_output=True, text=True, check=True, timeout=900)
        head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        if head != commit:
            raise RuntimeError(f"git fetched {head}, not {commit}")
        shutil.rmtree(tmp / ".git", ignore_errors=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        log(f"git fetch of {name} failed ({getattr(exc, 'stderr', None) or exc}); trying the tarball")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        _tarball(spec, tmp)
    if not (tmp / spec["check"]).is_file():
        raise RuntimeError(f"{name} at {commit} has no {spec['check']}")
    (tmp / "COMMIT").write_text(commit + "\n")
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)


def _tarball(spec, tmp):
    """Stream GitHub's tarball of the pinned commit and keep only the needed subtree."""
    root = tmp.resolve()
    commit = spec["commit"]
    kept = 0
    req = urllib.request.Request(spec["tarball"].format(commit=commit), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=900) as resp, tarfile.open(fileobj=resp, mode="r|gz") as tf:
        for m in tf:
            top, _, rel = m.name.partition("/")
            if commit[:7] not in top:
                raise RuntimeError(f"the tarball for {commit} holds {top!r}")
            if not rel.startswith(spec["keep"]):
                continue
            target = (root / rel).resolve()
            if root not in target.parents or m.issym() or m.islnk():
                continue
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(m) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                kept += 1
    if not kept:
        raise RuntimeError(f"the tarball for {commit} held no {spec['keep']} files")


def ensure_code(cache=CACHE):
    """Put dinovol and villa's vesuvius on sys.path at their pinned commits. LENS_DINOVOL and LENS_VILLA_SRC name
    local checkouts instead (the dinovol repository root, and villa's vesuvius/src)."""
    info = {}
    for name, env, sub in (("dinovol", "LENS_DINOVOL", ""), ("villa", "LENS_VILLA_SRC", "vesuvius/src")):
        if os.environ.get(env):
            path = Path(os.environ[env]).expanduser().resolve()
            info[name] = {"source": f"local checkout ({env})", "pinned": CODE[name]["commit"]}   # no local path
        else:
            dest = Path(cache) / f"{name}-{CODE[name]['commit'][:12]}"
            if not (dest / "COMMIT").is_file():
                log(f"fetching {name} {CODE[name]['commit'][:12]}")
                _fetch_code(name, dest)
            path = dest / sub if sub else dest
            info[name] = {"source": "pinned download", "commit": (dest / "COMMIT").read_text().strip()}
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return info


def ensure_weights(cache=CACHE, names=tuple(MODELS)):
    """Each named file from the Hub at its pinned revision, refused unless its SHA-256 matches. LENS_WEIGHTS names
    a folder holding local copies laid out as REPO_NAME/FILE (their SHA-256 is still checked)."""
    paths = {}
    local = os.environ.get("LENS_WEIGHTS")
    for name in names:
        spec = MODELS[name]
        if local:
            path = Path(local).expanduser() / spec["repo"].split("/")[1] / spec["file"]
        else:
            from huggingface_hub import hf_hub_download
            path = Path(hf_hub_download(spec["repo"], spec["file"], revision=spec["revision"],
                                        cache_dir=str(Path(cache) / "hub")))
        digest = sha256_file(path)
        if digest != spec["sha256"]:
            raise RuntimeError(f"{spec['repo']}/{spec['file']} has SHA-256 {digest}, not {spec['sha256']}")
        paths[name] = path
    return paths


# ---------------------------------------------------------------- the models

class Engine:
    """The three models, on the CPU until a call moves them. Built once per process."""

    def __init__(self, cache=CACHE):
        import numpy as np
        t0 = time.time()
        self.code = ensure_code(cache)
        self.paths = ensure_weights(cache)
        self.reference = np.load(self.paths["ink_reference"], allow_pickle=False).astype(np.float32)
        self.reference /= np.linalg.norm(self.reference)
        self.dino = self._load_dino(self.paths["dino"])
        self.ink, self.ink_norm = self._load_ink(self.paths["ink"])
        self.surface = self._load_surface(self.paths["surface"])
        self.startup_s = round(time.time() - t0, 1)

    # -- loading

    @staticmethod
    def _load_dino(path):
        import torch
        from dinovol_2.model.model import DinoVitStudentTeacher, _upgrade_weight_norm_state_dict_keys
        ck = torch.load(path, map_location="cpu", weights_only=False)
        state = {k.replace("backbone.", "", 1): v for k, v in ck["teacher"].items() if k.startswith("backbone.")}
        net = DinoVitStudentTeacher._build_backbone(ck["config"]["model"])
        net.load_state_dict(_upgrade_weight_norm_state_dict_keys(state), strict=True)
        return net.eval()

    @staticmethod
    def _load_ink(path):
        import torch
        from vesuvius.ink_detection.inference.inference_runtime import TargetModel
        from vesuvius.ink_detection.models.checkpoint import config_from_checkpoint, load_model_state
        from vesuvius.ink_detection.models.model import make_model
        payload = torch.load(path, map_location="cpu", weights_only=False)
        cfg = config_from_checkpoint(payload)
        net = make_model(cfg)
        load_model_state(net, payload["ema_model"])   # the card recommends the EMA weights for inference
        return TargetModel(net.eval()).eval(), cfg.data.normalization

    @staticmethod
    def _load_surface(path):
        import torch
        from types import SimpleNamespace
        from vesuvius.models.build.build_network_from_config import NetworkFromConfig
        ck = torch.load(path, map_location="cpu", weights_only=False)
        mc = ck["model_config"]
        mgr = SimpleNamespace(targets=mc["targets"], train_patch_size=tuple(mc["train_patch_size"]),
                              train_batch_size=mc["train_batch_size"], in_channels=1, autoconfigure=False,
                              model_config=mc, op_dims=3, spacing=(1.0, 1.0, 1.0), model_name=mc["model_name"])
        net = NetworkFromConfig(mgr)
        net.load_state_dict(ck["model"], strict=True)
        return net.eval()

    def describe(self):
        return {"models": {k: {kk: v[kk] for kk in ("repo", "revision", "file", "sha256")}
                           for k, v in MODELS.items()},
                "code": self.code, "startup_s": self.startup_s}

    # -- running

    def run(self, cube, layers=LAYERS, device="cpu", tta=False):
        """The chosen layers for one cube. Returns numpy arrays: `grid` (Z/8, Y/8, X/8, 864) float16 unit vectors,
        `ink` and `surface` (Z, Y, X) uint8 probabilities times 255, and timings."""
        import numpy as np
        import torch
        layers = check_layers(layers)
        dev = torch.device(device)
        out = {"device": str(dev), "device_name": _device_name(dev), "seconds": {}, "tta": bool(tta)}
        for name in layers:
            t0 = time.time()
            if name == "dino":
                out["grid"] = self._dino_grid(cube, dev)
            elif name == "ink":
                out["ink"] = self._ink(cube, dev, tta)
            else:
                out["surface"] = self._surface(cube, dev, tta)
            if dev.type == "cuda":
                torch.cuda.synchronize()
            out["seconds"][name] = round(time.time() - t0, 3)
        return out

    def _autocast(self, dev):
        import contextlib
        import torch
        return torch.autocast("cuda", dtype=torch.bfloat16) if dev.type == "cuda" else contextlib.nullcontext()

    def _dino_grid(self, cube, dev):
        """dinovol's dense patch embeddings, as its own napari inspector computes them: robust normalization of
        the whole cube, 128^3 windows overlapping by one patch, edge-tapered averaging, unit length."""
        import numpy as np
        import torch
        import torch.nn.functional as F
        from dinovol_2.dataset.normalization import get_normalization
        net = self.dino.to(dev)
        vol = get_normalization("robust", intensityproperties=None).run(cube.astype(np.float32))
        n = cube.shape[0] // PATCH
        win = min(n, 128 // PATCH)
        starts = _window_starts(n, win, 1)
        w1 = _taper(win, 1 if win < n else 0)
        weight = w1[:, None, None] * w1[None, :, None] * w1[None, None, :]
        acc = np.zeros((n, n, n, EMBED_DIM), np.float32)
        wsum = np.zeros((n, n, n), np.float32)
        with torch.inference_mode(), self._autocast(dev):
            for z in starts:
                for y in starts:
                    for x in starts:
                        tile = vol[z * PATCH:(z + win) * PATCH, y * PATCH:(y + win) * PATCH,
                                   x * PATCH:(x + win) * PATCH]
                        t = torch.from_numpy(np.ascontiguousarray(tile))[None, None].to(dev)
                        tok = net.forward_features(t, masks=None, view_kind="global")["x_norm_patchtokens"][0]
                        tok = F.normalize(tok.float().reshape(win, win, win, -1), dim=-1).cpu().numpy()
                        acc[z:z + win, y:y + win, x:x + win] += tok * weight[..., None]
                        wsum[z:z + win, y:y + win, x:x + win] += weight
        grid = acc / np.maximum(wsum[..., None], np.finfo(np.float32).eps)
        grid /= np.maximum(np.linalg.norm(grid, axis=-1, keepdims=True), 1e-12)
        return grid.astype(np.float16)

    def _ink(self, cube, dev, tta):
        import numpy as np
        import torch
        from vesuvius.ink_detection.data.normalization import normalize_image
        net = self.ink.to(dev)
        x = torch.from_numpy(np.ascontiguousarray(normalize_image(cube.astype(np.float32), self.ink_norm)))
        x = x[None, None].to(dev)
        with torch.inference_mode(), self._autocast(dev):
            prob = _mirrored(lambda t: net(t).float().sigmoid(), x, tta)
        return _to_u8(prob[0, 0])

    def _surface(self, cube, dev, tta):
        import numpy as np
        import torch
        net = self.surface.to(dev)
        c = cube.astype(np.float32)
        x = torch.from_numpy((c - c.mean()) / max(float(c.std()), 1e-8))[None, None].to(dev)   # z-score, per cube
        with torch.inference_mode(), self._autocast(dev):
            prob = _mirrored(lambda t: torch.softmax(net(t)["surface"].float(), 1)[:, 1:2], x, tta)
        return _to_u8(prob[0, 0])


def _mirrored(fn, x, tta):
    """fn(x), or with tta the mean of fn over the eight mirrorings of x, each flipped back (villa's mirror TTA)."""
    if not tta:
        return fn(x)
    total = None
    for axes in ((), (2,), (3,), (4,), (2, 3), (2, 4), (3, 4), (2, 3, 4)):
        y = fn(x.flip(axes) if axes else x)
        y = y.flip(axes) if axes else y
        total = y if total is None else total + y
    return total / 8.0


def _to_u8(prob):
    import numpy as np
    return np.clip(np.rint(prob.float().cpu().numpy() * 255.0), 0, 255).astype(np.uint8)


def _device_name(dev):
    if dev.type == "cuda":
        import torch
        return torch.cuda.get_device_name(dev)
    import platform
    return platform.processor() or platform.machine()


def _window_starts(n, win, overlap):
    if win >= n:
        return [0]
    step = win - overlap
    starts = list(range(0, n - win + 1, step))
    if starts[-1] != n - win:
        starts.append(n - win)
    return starts


def _taper(length, overlap):
    import numpy as np
    w = np.ones(length, np.float32)
    if overlap <= 0 or length <= 1:
        return w
    r = np.arange(length, dtype=np.float32)
    return np.minimum(np.minimum(r + 1.0, length - r) / float(overlap + 1), 1.0).astype(np.float32)


def check_layers(layers):
    layers = tuple(dict.fromkeys(layers or ()))
    bad = [x for x in layers if x not in LAYERS]
    if bad:
        raise LensError(f"unknown layer {bad[0]!r}; choose from {', '.join(LAYERS)}")
    if not layers:
        raise LensError("choose at least one model to run")
    return layers


def gpu_seconds(size, layers, tta=False):
    """The duration one cube asks ZeroGPU for. ZeroGPU reserves 1.5 times this from the visitor's quota before it
    starts the call (it refused a 256 cube asking 26 s with "39s requested vs. 38s left") and then charges the time
    used. Measured on the Space (99 gallery cubes, 2026-10-17): 256 cube, all three models, 3.2 to 8.0 s of model time
    and about 4.5 s of quota; 128 cube about 0.3 s. Six seconds cover moving the models to the GPU."""
    size, layers = check_size(size), check_layers(layers)
    scale = (size / 256) ** 3
    per = {"dino": 4.0, "ink": 2.0 * (8 if tta else 1), "surface": 2.0 * (8 if tta else 1)}
    return int(math.ceil(6 + scale * sum(per[x] for x in layers)))


# ---------------------------------------------------------------- embeddings: clicks, similarity, colors

def unit(v, axis=-1):
    import numpy as np
    v = np.asarray(v, np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=axis, keepdims=True), 1e-12)


def grid_of(result):
    """The (Z/8, Y/8, X/8, 864) float32 embeddings of a result. A full result's are unit vectors. A compact (gallery)
    result's are rebuilt as the projection of each unit embedding onto the kept REDUCED_DIM directions, left as they
    are: their length is the share of the embedding kept (median 0.98 over the gallery, at least 0.68), and a dot
    product with a unit concept estimates the original cosine without the bias that rescaling to unit length adds."""
    import numpy as np
    if "grid" in result:
        return np.asarray(result["grid"], np.float32)
    if "grid_reduced" in result:
        return np.asarray(result["grid_reduced"], np.float32) @ np.asarray(result["grid_basis"], np.float32).T
    raise LensError("this cube has no DINO embeddings; run it with the 3D DINO layer")


def reduce_grid(grid, k=REDUCED_DIM):
    """Keep the top `k` directions of a cube's embeddings (uncentered SVD, so the common direction stays): 1/7 of the
    size. Returns (coefficients float16, basis (864, k) float32). grid_of() rebuilds unit vectors from them."""
    import numpy as np
    g = np.asarray(grid, np.float32).reshape(-1, EMBED_DIM)
    _, _, vt = np.linalg.svd(g[:: max(1, len(g) // 20000)], full_matrices=False)
    basis = vt[:k].T.astype(np.float32)
    coef = (g @ basis).reshape(*np.shape(grid)[:3], k)
    return coef.astype(np.float16), basis


def token_of(voxel_zyx, size):
    """The DINO patch (token) index holding a voxel of the cube."""
    n = size // PATCH
    return tuple(int(min(max(int(v) // PATCH, 0), n - 1)) for v in voxel_zyx)


def parse_points(text, limit=64):
    """Points written as "z,y,x; z,y,x" (spaces, semicolons or new lines between them) as a list of (z, y, x)."""
    text = str(text or "").replace("\n", ";").strip()
    out = []
    for part in [p for p in text.split(";") if p.strip()]:
        nums = [s for s in part.replace(" ", ",").split(",") if s]
        try:
            pt = tuple(int(float(s)) for s in nums)
        except ValueError:
            raise LensError(f"not a point: {part.strip()!r}; write z,y,x in voxels") from None
        if len(pt) != 3 or min(pt) < 0:
            raise LensError(f"not a point: {part.strip()!r}; write z,y,x in voxels, each 0 or more")
        out.append(pt)
    if len(out) > limit:
        raise LensError(f"at most {limit} points")
    return out


def voxel_in_cube(point_zyx, origin, size):
    """A scan point as a voxel of the cube at `origin`; refuses a point outside the cube."""
    v = [int(p) - int(o) for p, o in zip(point_zyx, origin)]
    if min(v) < 0 or max(v) >= size:
        raise LensError(f"point {tuple(int(p) for p in point_zyx)} is outside the cube at {tuple(origin)} of side "
                        f"{size}; points must lie inside the cube being searched")
    return v


def top_matches(sim_tokens, origin, k=20):
    """The `k` best patches of a similarity map, best first: each patch's center in scan voxels and its score."""
    import numpy as np
    k = int(min(max(int(k), 1), 200))
    flat = np.asarray(sim_tokens, np.float32).ravel()
    idx = np.argsort(-flat, kind="stable")[:k]
    out = []
    for i in idx:
        t = np.unravel_index(int(i), sim_tokens.shape)
        out.append({"center_zyx": [int(o + PATCH * a + PATCH // 2) for o, a in zip(origin, t)],
                    "score": round(float(flat[i]), 4)})
    return out


def concept(grid, tokens):
    """The organizers' recipe for a reference embedding: the unit-length mean of the clicked patches' embeddings."""
    import numpy as np
    if not tokens:
        return None
    vecs = np.stack([grid[t] for t in tokens]).astype(np.float32)
    return unit(vecs.mean(0))


def similarity(grid, positive, negative=None):
    """Per patch: cosine similarity to the positive concept, minus that to the negative one when there is one."""
    import numpy as np
    s = np.tensordot(grid, positive, axes=([-1], [0])).astype(np.float32)
    if negative is not None:
        s = s - np.tensordot(grid, negative, axes=([-1], [0])).astype(np.float32)
    return s


def pca_colors(grid):
    """The three main directions of a cube's embeddings as red, green and blue, stretched to the 1st and 99th
    percentiles: patches the model sees as alike get alike colors. (Z, Y, X, 3) uint8 at patch resolution."""
    import numpy as np
    g = np.asarray(grid, np.float32).reshape(-1, grid.shape[-1])
    g = g - g.mean(0)
    # the three main directions: the top eigenvectors of the covariance, the same as the SVD's and far cheaper
    _, vecs = np.linalg.eigh((g.T @ g).astype(np.float64))
    p = g @ vecs[:, ::-1][:, :3].astype(np.float32)
    # fix each component's sign so the colors do not flip between runs of the same cube
    p *= np.sign(np.sum(p ** 3, axis=0, keepdims=True) + 1e-12)
    lo, hi = np.percentile(p, 1, axis=0), np.percentile(p, 99, axis=0)
    p = np.clip((p - lo) / np.maximum(hi - lo, 1e-6), 0, 1)
    return (p * 255).astype(np.uint8).reshape(*grid.shape[:3], 3)


def upsample(tokens, size):
    """Patch-resolution values (Z/8, Y/8, X/8[, C]) to voxels by repetition."""
    import numpy as np
    f = size // tokens.shape[0]
    a = np.repeat(tokens, f, axis=0)
    a = np.repeat(a, f, axis=1)
    return np.repeat(a, f, axis=2)


def auc(scores, labels):
    """Probability that a positive scores above a negative (ties count half). None when a class is empty or a score
    is not a number."""
    import numpy as np
    s = np.asarray(scores, np.float64).ravel()
    y = np.asarray(labels, bool).ravel()
    n1, n0 = int(y.sum()), int((~y).sum())
    if not n1 or not n0 or not np.isfinite(s).all():
        return None
    order = np.argsort(s, kind="mergesort")
    ss = s[order]
    first = np.concatenate(([True], ss[1:] != ss[:-1]))           # start of each run of equal scores
    starts = np.flatnonzero(first)
    ends = np.append(starts[1:], len(ss)) - 1
    ranks = np.empty(len(s), np.float64)
    ranks[order] = ((starts + ends) / 2.0 + 1.0)[np.cumsum(first) - 1]   # average rank within each run
    return float((ranks[y].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


CONTROL_SHIFTS = 16     # the agreement control: the ink mask rolled by this many fixed pseudo-random shifts


def agreement(sim_tokens, ink_u8, threshold=0.5):
    """How well a patch similarity map picks out the patches the 3D ink model marks as ink (mean probability over
    the patch above `threshold`), as an AUC, beside controls that must fail: the same ink mask rolled away from its
    place, which breaks the link between place and score. `auc_control_shifted` rolls it by half the cube on every
    axis; because papyrus is layered, one roll can line the layers up again, so `auc_control_mean`, `_p05` and `_p95`
    summarize CONTROL_SHIFTS rolls between a quarter and three quarters of the cube (fixed seed). The AUC means
    something only above `auc_control_p95`. Agreement with a model, not ground truth."""
    import numpy as np
    n = sim_tokens.shape[0]
    f = ink_u8.shape[0] // n
    ink_tok = ink_u8.reshape(n, f, n, f, n, f).mean(axis=(1, 3, 5)) / 255.0 > threshold
    shifted = np.roll(ink_tok, (n // 2, n // 2, n // 2), axis=(0, 1, 2))
    rng = np.random.default_rng(20261017)
    controls = [auc(sim_tokens, np.roll(ink_tok, tuple(int(v) for v in rng.integers(n // 4, 3 * n // 4 + 1, 3)),
                                        axis=(0, 1, 2))) for _ in range(CONTROL_SHIFTS)]
    controls = [c for c in controls if c is not None]
    out = {"auc": auc(sim_tokens, ink_tok), "auc_control_shifted": auc(sim_tokens, shifted),
           "ink_patch_fraction": float(ink_tok.mean())}
    if controls:
        out.update(auc_control_mean=float(np.mean(controls)), auc_control_p05=float(np.percentile(controls, 5)),
                   auc_control_p95=float(np.percentile(controls, 95)))
    return out


def load_concept(path):
    """A concept file a visitor uploads: .npy, float, shape (864,) or (K, 864) with K at least 1, finite, at most
    4 MB, no pickles. The header is read before the data, so a file that claims a huge shape is refused without
    allocating it. Returns the unit-length mean, refused when the rows cancel out."""
    import numpy as np
    p = Path(path)
    try:
        nbytes = p.stat().st_size
    except OSError as exc:
        raise LensError(f"cannot read the concept file: {exc}") from None
    if nbytes > MAX_CONCEPT_BYTES:
        raise LensError(f"a concept file is at most {MAX_CONCEPT_BYTES >> 20} MB")
    try:
        with open(p, "rb") as fh:
            version = np.lib.format.read_magic(fh)
            if version == (1, 0):
                shape, fortran, dtype = np.lib.format.read_array_header_1_0(fh)
            else:
                shape, fortran, dtype = np.lib.format.read_array_header_2_0(fh)
            data_at = fh.tell()
    except (ValueError, OSError, EOFError) as exc:
        raise LensError(f"not a plain .npy array: {exc}") from None
    if dtype.kind != "f" or len(shape) not in (1, 2) or shape[-1] != EMBED_DIM or 0 in shape:
        raise LensError(f"a concept is a float array of shape ({EMBED_DIM},) or (K, {EMBED_DIM}), not {dtype} "
                        f"{shape}")
    if data_at + math.prod(shape) * dtype.itemsize != nbytes:
        raise LensError("the concept file's size does not match its header")
    try:
        a = np.load(p, allow_pickle=False)
    except (ValueError, OSError, EOFError) as exc:
        raise LensError(f"not a plain .npy array: {exc}") from None
    a = np.asarray(a, np.float64).reshape(-1, EMBED_DIM)
    norms = np.linalg.norm(a, axis=1)
    if not np.isfinite(a).all() or not np.isfinite(norms).all() or not norms.all():
        raise LensError("the concept holds non-finite or zero vectors")
    mean = (a / norms[:, None]).mean(0)
    if np.linalg.norm(mean) < 1e-3:
        raise LensError("the concept's rows cancel out (their mean is close to zero)")
    return unit(mean.astype(np.float32))


# ---------------------------------------------------------------- saving and the gallery

def layers_in(result):
    """The models whose output a result holds: DINO is stored as `grid` (or `grid_reduced` when compact)."""
    return [k for k in LAYERS if (k == "dino" and ("grid" in result or "grid_reduced" in result))
            or (k != "dino" and k in result)]


def receipt(vid, origin, size, center, result, engine_info=None, extra=None):
    vid = volume_id(vid)
    v = VOLUMES[vid]
    r = {"tool": "Scroll Lens", "version": VERSION, "volume": vid, "scroll": v["scroll"],
         "zarr": f"{BUCKET}/{vid}/volumes/{v['scan']}", "level": 0, "voxel_um": v["voxel_um"],
         "point_zyx": [int(c) for c in center], "cube_origin_zyx": [int(o) for o in origin], "cube_size": int(size),
         "layers": layers_in(result),
         "device": result.get("device"), "device_name": result.get("device_name"), "tta": result.get("tta", False),
         "seconds": result.get("seconds", {}), "models_trained_on_this_scroll": v["role"],
         "note": "Model output, not a reading. A cube is smaller than one letter."}
    if engine_info:
        r["engine"] = engine_info
    if extra:
        r.update(extra)
    return r


def quantize(prob_u8, levels=16):
    """uint8 probabilities rounded to `levels` evenly spaced values (0, 17, ..., 255 for 16): a compact gallery cube
    is about a quarter of the size and no probability moves by more than 8/255."""
    import numpy as np
    step = 255 // (levels - 1)
    return (np.rint(np.asarray(prob_u8, np.float32) / step) * step).clip(0, 255).astype(np.uint8)


def save_npz(path, cube_meta, result, compact=False):
    """A cube's model outputs (not the scan, which anyone can read again from the bucket): embeddings as float16
    unit vectors, ink and surface as uint8, and the receipt as JSON. `compact` (the gallery) keeps REDUCED_DIM
    components of the embeddings (see reduce_grid) and 16 levels of each probability (see quantize)."""
    import numpy as np
    meta = dict(cube_meta, compact=bool(compact))
    arrays = {"receipt": np.frombuffer(json.dumps(meta).encode(), np.uint8)}
    if "grid" in result:
        if compact:
            arrays["grid_reduced"], arrays["grid_basis"] = reduce_grid(result["grid"])
        else:
            arrays["grid"] = np.asarray(result["grid"], np.float16)
    elif "grid_reduced" in result:
        arrays["grid_reduced"], arrays["grid_basis"] = result["grid_reduced"], result["grid_basis"]
    for k in ("ink", "surface"):
        if k in result:
            arrays[k] = quantize(result[k]) if compact else np.asarray(result[k], np.uint8)
    np.savez_compressed(path, **arrays)
    return Path(path)


def load_npz(path):
    """A cube saved by save_npz, checked: the shapes agree with the receipt and nothing holds Python objects."""
    import numpy as np
    with np.load(path, allow_pickle=False) as z:
        out = {k: z[k] for k in z.files}
    meta = json.loads(bytes(out.pop("receipt")).decode())
    meta["layers"] = layers_in(out)               # receipts before 1.1.0 left dino out of this list
    size = check_size(meta["cube_size"])
    volume(meta["volume"])
    n = size // PATCH
    if "grid" in out and out["grid"].shape != (n, n, n, EMBED_DIM):
        raise LensError(f"{path}: embeddings of shape {out['grid'].shape}, not {(n, n, n, EMBED_DIM)}")
    if "grid_reduced" in out and (out["grid_reduced"].shape[:3] != (n, n, n)
                                  or out["grid_basis"].shape != (EMBED_DIM, out["grid_reduced"].shape[3])):
        raise LensError(f"{path}: reduced embeddings do not match their basis")
    for k in ("ink", "surface"):
        if k in out and (out[k].shape != (size,) * 3 or out[k].dtype != np.uint8):
            raise LensError(f"{path}: {k} is {out[k].dtype} {out[k].shape}, not uint8 {(size,) * 3}")
    return meta, out


def gallery(root=HERE / "gallery"):
    """The precomputed cubes: gallery/index.json lists them, each with its .npz beside it. Refuses an index that is
    not a list of complete, unique entries naming files that exist."""
    idx = Path(root) / "index.json"
    if not idx.is_file():
        return []
    data = json.loads(idx.read_text())
    items = data.get("cubes", []) if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise LensError("gallery/index.json has no list of cubes")
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            raise LensError("gallery/index.json holds an entry that is not an object")
        for key in ("title", "note"):     # cubes built before 1.1.0 say "organisers'"; the page uses American spelling
            if isinstance(it.get(key), str):
                it[key] = it[key].replace("rganisers", "rganizers")
        for key in ("id", "volume", "title", "note", "file", "point_zyx", "size"):
            if key not in it:
                raise LensError(f"gallery entry {it.get('id')!r} has no {key}")
        if it["id"] in seen:
            raise LensError(f"gallery entry {it['id']!r} is listed twice")
        seen.add(it["id"])
        vid = volume_id(it["volume"])
        if "/" in it["file"] or ".." in it["file"] or not it["file"].endswith(".npz"):
            raise LensError(f"gallery entry {it['id']!r} names a file outside gallery/")
        if not (Path(root) / it["file"]).is_file():
            raise LensError(f"gallery entry {it['id']!r} names {it['file']}, which is missing")
        if it["size"] not in SIZES:
            raise LensError(f"gallery entry {it['id']!r} has size {it['size']!r}, not one of {SIZES}")
        p = it["point_zyx"]
        if not (isinstance(p, list) and len(p) == 3 and all(isinstance(v, int) for v in p)
                and all(0 <= v < n for v, n in zip(p, VOLUMES[vid]["shape"]))):
            raise LensError(f"gallery entry {it['id']!r} has a point_zyx outside the scan")
    return items


# ---------------------------------------------------------------- the Space's own files

SPACE_FILES = ("README.md", "app.py", "lens.py", "viewer.js", "requirements.txt", "LICENSE", "NOTICE")


def space_files(root=HERE):
    """The code and text of the Space. The gallery is not among them: tools/build_gallery.py uploads it."""
    files = [root / f for f in SPACE_FILES]
    missing = [str(p) for p in files if not p.is_file()]
    if missing:
        raise RuntimeError(f"missing Space files: {missing}")
    return files


def stage(dest, root=HERE):
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError(f"{dest} is not empty")
    for p in space_files(root):
        rel = p.relative_to(root)
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest / rel)
    return dest


# ---------------------------------------------------------------- command line

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("volumes", help="the scans this Space may read")
    lk = sub.add_parser("look", help="run the models on one cube on this machine and save it")
    lk.add_argument("volume")
    lk.add_argument("zyx", nargs=3, type=int, help="a point in level-0 voxels, z y x")
    lk.add_argument("--size", type=int, default=128, choices=SIZES)
    lk.add_argument("--layers", default="dino,ink,surface")
    lk.add_argument("--tta", action="store_true", help="average the eight mirrorings (8x the ink and surface time)")
    lk.add_argument("--device", default=None, help="cpu or cuda (default: cuda when present)")
    lk.add_argument("--out", default=".", help="folder for CUBE.npz and CUBE.json")
    sub.add_parser("files", help="the Space's files with their SHA-256")
    st = sub.add_parser("stage", help="copy the Space's files into an empty folder")
    st.add_argument("dest")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "volumes":
            for vid, v in VOLUMES.items():
                print(f"{vid:12s} {v['scroll']:24s} {v['voxel_um']:.3f} um  {v['scan']}")
            return 0
        if a.cmd == "files":
            for p in space_files():
                print(f"{sha256_file(p)}  {p.relative_to(HERE)}")
            return 0
        if a.cmd == "stage":
            print(stage(a.dest))
            return 0
        import torch
        device = a.device or ("cuda" if torch.cuda.is_available() else "cpu")
        layers = check_layers(a.layers.split(","))
        origin = cube_origin(a.volume, a.zyx, a.size)
        cube = read_cube(a.volume, origin, a.size)
        check_cube(cube)
        eng = Engine()
        res = eng.run(cube, layers, device=device, tta=a.tta)
        meta = receipt(a.volume, origin, a.size, a.zyx, res, eng.describe())
        if "grid" in res and "ink" in res:
            meta["agreement_with_ink_model"] = agreement(similarity(res["grid"].astype("float32"), eng.reference),
                                                         res["ink"])
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        name = f"{a.volume}-{'-'.join(map(str, origin))}-{a.size}"
        save_npz(out / f"{name}.npz", meta, res)
        (out / f"{name}.json").write_text(json.dumps(meta, indent=1) + "\n")
        print(json.dumps(meta, indent=1))
        return 0
    except LensError as exc:
        print(f"lens: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
