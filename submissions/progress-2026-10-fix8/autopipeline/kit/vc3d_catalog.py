"""The Vesuvius Challenge open-data catalog and model weights, for agents working with no display.

The catalog (https://vesuvius-challenge-open-data.s3.amazonaws.com/metadata.json, about 17 MB,
served gzip-encoded) lists every sample's scans, volumes, surface predictions, normal grids,
segments, published surface volumes, ink maps and ink labels, and the affine transforms between a
sample's volumes. It is cached under KIT_VC3D_HOME/cache/ for a day. Bucket paths become HTTPS URLs
that VC3D streams as `--volume URL` (render; builds before villa ba2bf75, 12 Oct 2026, took
`--remote-url` next to a local cache folder) or `-v URL` (trace).

Model weights come from Hugging Face over anonymous HTTPS (downloads only; nothing is posted). The
known models are the ones this repository already uses (kit/plan.py, scripts/v8in_run.py).
Standard library only.
"""

import fnmatch
import gzip
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path, PurePosixPath

from . import s3retry

CATALOG_URL = "https://vesuvius-challenge-open-data.s3.amazonaws.com/metadata.json"
BUCKET_URL = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
MAX_AGE = 86400
HF = "https://huggingface.co"

# Checkpoints this repository already runs. Revisions are pinned where the repo pinned them; "main"
# is recorded as resolved (the X-Repo-Commit header) in the download receipt when the response
# carries it, which a download redirected to Hugging Face's file store may not. Every file's sha256
# goes in the receipt, and a file listed under "sha256" must match it (every checksum here is the one
# scripts/firstletters/readers.tsv pins, a test checks they agree). A model with "host": "github-release"
# is a file of the GitHub release whose tag is its revision (a tag can be moved, so its sha256 is the pin).
KNOWN_MODELS = {
    "ink_9um-seed42": {
        "engine": "villa", "repo": "scrollprize/ink_9um", "revision": "main",
        "files": ["hybrid_3d2d-seed42/step-075000.pth"], "checkpoint": "hybrid_3d2d-seed42/step-075000.pth",
        "sha256": {"hybrid_3d2d-seed42/step-075000.pth": "e635558ae6a1a807a7e5ec1e83adfd45bc3c0ac53883ea43f1d4e085d62a9cab"},
        "about": "the team's released 9 um ink model, seed 42 at step 75,000 (kit/plan.py)"},
    "ink_9um-seed43": {
        "engine": "villa", "repo": "scrollprize/ink_9um", "revision": "main",
        "files": ["hybrid_3d2d-seed43/step-075000.pth"], "checkpoint": "hybrid_3d2d-seed43/step-075000.pth",
        "sha256": {"hybrid_3d2d-seed43/step-075000.pth": "2aeaa85a35ef28d7bc7bf3e848c4a6a91385e9132710927fdba41133c4ecb28f"},
        "about": "the team's released 9 um ink model, seed 43 at step 75,000 (kit/plan.py)"},
    "reader-v2": {
        "engine": "villa", "repo": "domenicor046/reader-v2", "revision": "main",
        "files": ["reader-v2-step040000.pth"], "checkpoint": "reader-v2-step040000.pth",
        "sha256": {"reader-v2-step040000.pth": "654ec5acec2b6c4788d9cb326e2f0b8c2c730584949a934ef775db7f6ab5d3a6"},
        "about": "Domenico Russo's ink_9um fine-tune, a drop-in ink_9um checkpoint (trained on w045)"},
    # AutoPipeline's default reader since 0.1.8 (25 Oct 2026): Reader v2 continued on 384 px tiles, the same checkpoint
    # layout, so villa's flat inference builds it from its own config (17 x 384 x 384 patches) and runs it as it runs
    # Reader v2, tile by tile
    "reader-v3": {
        "engine": "villa", "repo": "domenicor046/reader-v3", "revision": "main",
        "files": ["reader-v3.pth"], "checkpoint": "reader-v3.pth",
        "sha256": {"reader-v3.pth": "ea405417450abd8ace1b8ff79ebce3adb646c5e48ab95da46844d77efe984d8a"},
        "about": "Domenico Russo's Reader V3 (MIT), Reader v2 continued on 384 px tiles, an ink_9um-format checkpoint "
                 "run by villa's flat inference (trained on w045, like Reader v2)"},
    "d9v2": {
        "engine": "villa", "host": "github-release", "repo": "TAUIL-Abd-Elilah/pherc0826-first-letters-search",
        "revision": "v1.0", "files": ["d9v2_ft-012000.pth"], "checkpoint": "d9v2_ft-012000.pth",
        "sha256": {"d9v2_ft-012000.pth": "50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966"},
        "about": "TAUIL-Abd-Elilah's ink_9um fine-tune at step 12,000, a drop-in ink_9um checkpoint (inherits "
                 "ink_9um's training on w045's 2.4 um render)"},
    "v8in": {
        "engine": "v8in", "repo": "YoussefMoNader/ink-8um-v8in",
        "revision": "d89166b41a3f5fad7749b3d7c0fdd1bd3695d844", "snapshot": True, "exclude": ["training/*"],
        "about": "Youssef Nader's ResNet3D-50 ink model (MIT, 2026-09-28); reads a folder of layer TIFFs"},
}
# Ink tools that ship inside kit and need no download: name -> a command-engine model (scripts/vc3d/ink.py's
# Command engine fills {input}, {output} and {reverse}). AutoPipeline plans name them in ink.models like a fetched
# model; the ink tool and AutoPipeline's checks resolve them with builtin_model(). Released tools are wired into
# AutoPipeline when they are ready or released (decided 23 Oct 2026).
BUILTIN_MODELS = {
    "inkfilter": {
        "engine": "command", "kind": "classical", "needs": ["numpy"], "compute": "cpu", "origin": "ours",
        "licence": "this repository",
        "args": ["inkfilter", "{input}", "--output", "{output}", "--level", "0", "--no-control", "--pool", "2",
                 "--reverse-depth", "{reverse}"],
        "about": "Inkfilter's face-mix filter (kit inkfilter, released in public Scrolls): fixed operations, no "
                 "trained weights; reads level 0 of the render averaged 2 x 2, the grid it was chosen on for 2.4 um "
                 "scans, and writes the map back on level 0"},
    # Reader V3 through the team's koine inference (23 Oct 2026; named reader-v3 until 0.1.8, when villa's flat
    # inference of the same checkpoint took that name as the default reader): Domenico Russo's MIT reader as the
    # Crackle Check Space runs it (kit/koineink.py); run by the ink Python (KIT_INK_PYTHON, else this one), which needs
    # torch, torchvision, monai, timm and einops, and reads the whole render into memory
    "reader-v3-koine": {
        "engine": "command", "kind": "learned", "needs": ["torch", "numpy", "tifffile"], "compute": "gpu",
        "origin": "community", "licence": "MIT (weights, Domenico Russo); koine_machines is villa's",
        "module": "kit.koineink", "python": "ink",
        "args": ["{input}", "--output", "{output}", "--reverse-depth", "{reverse}", "--device", "{device}"],
        "about": "Reader V3 (Domenico Russo, MIT, domenicor046/reader-v3) through koine_machines at villa "
                 "merge-ink-pipelines 3ea17f5 (kit/koineink.py, the Crackle Check Space's engine): checkpoint SHA-256 "
                 "pinned, loaded weights_only; one koine run makes both directions and the second call reuses it"},
}
# Other names for one model, such as an old run id beside a model family's version id, so a plan's ink.models and
# the ink tool reach the same registry entry by either name. This checkout may list them in ALIASES_FILE: a JSON list
# of {"name", "aliases", "why"}, with an optional "sha256" pin that the models tool records with the checkpoint and the
# ink tool checks before every load by any of the model's names. A model kit can fetch (KNOWN_MODELS) keeps its one
# name, so no alias can stand for released weights. A released copy may ship without the file; then each name means
# only itself.
ALIASES_FILE = Path(__file__).resolve().parent / "data" / "model-aliases.json"
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class CatalogError(Exception):
    pass


def model_aliases(path=None):
    """{name: entry} for every name in the aliases file: an entry's main name and each of its aliases map to the same
    entry (name, aliases, why, optional sha256). Empty when the file is absent; a malformed file stops the caller."""
    path = Path(path) if path else ALIASES_FILE
    if not path.exists():
        return {}
    try:
        out = {}
        for e in json.loads(path.read_text()):
            names = [e.get("name")] + (e.get("aliases") if isinstance(e.get("aliases"), list) else [None])
            if not all(isinstance(n, str) and n for n in names) or not (isinstance(e.get("why"), str) and e["why"]):
                raise ValueError(f"entry {e!r} needs a non-empty name, a list of aliases and why")
            if e.get("sha256") is not None and not (isinstance(e["sha256"], str) and SHA256_HEX.fullmatch(e["sha256"])):
                raise ValueError(f"entry {e['name']!r}: sha256 is 64 lowercase hex digits")
            for n in names:
                if n in out:
                    raise ValueError(f"{n!r} is listed twice")
                if n in KNOWN_MODELS:
                    raise ValueError(f"{n!r} is a model kit can fetch, which keeps its one name")
                out[n] = e
        return out
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise CatalogError(f"model aliases: {path} is not a JSON list of {{name, aliases, why}} ({exc}); "
                           "fix it before naming models") from None


def model_names(name, aliases=None):
    """name first, then every other name the aliases file gives the same model."""
    e = (model_aliases() if aliases is None else aliases).get(name)
    return [name] + ([n for n in [e["name"]] + e["aliases"] if n != name] if e else [])


def main_name(name, aliases=None):
    """The aliases file's main name for this model (its entry's name), or name itself when the file does not list it:
    two names with one main name are one model."""
    e = (model_aliases() if aliases is None else aliases).get(name)
    return e["name"] if e else name


def find_model(name, names, aliases=None):
    """The first of model_names(name) that is in names (a registry, KNOWN_MODELS), or None."""
    return next((n for n in model_names(name, aliases) if n in names), None)


def builtin_model(name):
    """The registry entry of a model built into kit (BUILTIN_MODELS), its command run by this Python with this kit
    on the path, or None."""
    b = BUILTIN_MODELS.get(name)
    if b is None:
        return None
    import os
    import sys
    root = str(Path(__file__).resolve().parent.parent)
    module = b.get("module", "kit.cli")
    boot = f"import sys; sys.path.insert(0, {root!r}); from {module} import main; sys.exit(main())"
    python = (os.environ.get("KIT_INK_PYTHON") or sys.executable) if b.get("python") == "ink" else sys.executable
    return {"engine": b["engine"], "command": [python, "-c", boot, *b["args"]], "builtin": True,
            "notes": b["about"]}


def model_pin(name, aliases=None):
    """The sha256 the aliases file pins for this model under any of its names, or None."""
    e = (model_aliases() if aliases is None else aliases).get(name)
    return e.get("sha256") if e else None


def _open(url, opener=None, timeout=120, gzip_ok=True):
    """The response; a false 404 from S3 (NoSuchBucket for an object that exists) is asked again."""
    # Downloads ask for the bytes as stored: Hugging Face gzips small text files on request, and
    # a gzipped body written to disk fails the size check against the repository's file list.
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip" if gzip_ok else "identity",
                                               "User-Agent": "kit-vc3d"})
    return s3retry.open_url(req, opener, timeout)


def _read(resp):
    data = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def load(cache_dir, refresh=False, max_age=MAX_AGE, opener=None):
    """The parsed catalog, from the cache when it is younger than max_age seconds."""
    cache = Path(cache_dir) / "open-data-metadata.json"
    if not refresh and cache.is_file() and time.time() - cache.stat().st_mtime < max_age:
        return json.loads(cache.read_text())
    try:
        with _open(CATALOG_URL, opener) as resp:
            data = _read(resp)
    except OSError as exc:
        if cache.is_file():
            return json.loads(cache.read_text())
        raise CatalogError(f"cannot fetch {CATALOG_URL}: {exc}") from exc
    cat = json.loads(data)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    return cat


def url_of(path):
    return f"{BUCKET_URL}/{path.lstrip('/')}"


def _origin(entry):
    origins = entry.get("origins") or [{}]
    return origins[0].get("path")


def data_url(entry):
    """HTTPS URL of a data entry: its path under the access root the catalog gives (most data is in the
    open-data bucket; the 2023 scans are under https://data.aws.ash2txt.org), or None."""
    origin = (entry.get("origins") or [{}])[0]
    path = origin.get("path")
    if not path:
        return None
    for root in origin.get("access_roots") or []:
        if root.get("type") == "https" and root.get("url"):
            return f"{root['url'].rstrip('/')}/{path.lstrip('/')}"
    return url_of(path)


def _sample(cat, sample):
    samples = cat.get("samples", {})
    if sample in samples:
        return samples[sample]
    lower = {k.lower(): k for k in samples}
    if sample.lower() in lower:
        return samples[lower[sample.lower()]]
    raise CatalogError(f"no sample {sample!r}; samples: {', '.join(sorted(samples))}")


def samples(cat):
    out = []
    for sid, s in sorted(cat.get("samples", {}).items()):
        props = (s.get("sample") or {}).get("properties", {})
        out.append({"sample": sid, "type": props.get("type"), "volumes": len(s.get("volumes", {})),
                    "segments": len(s.get("segments", {}))})
    return out


def volumes(cat, sample):
    out = []
    for vid, v in sorted(_sample(cat, sample).get("volumes", {}).items()):
        props = v.get("properties", {})
        row = {"volume": vid, "long_id": v.get("long_id"), "voxel_um": props.get("pixel_size_um"),
               "shape_zyx": props.get("shape"), "energy_keV": props.get("energy_keV"),
               "superseded_by": props.get("superseded_by"), "license": (props.get("license") or {}).get("name")}
        for d in v.get("data", []):
            url = data_url(d)
            if not url:
                continue
            if d["type"] == "ome-zarr":
                row["url"] = url
            else:
                params = d.get("parameters") or {}
                # level: the pyramid level of the scan a prediction (or its normal grids) was made on; level 2
                # is quarter resolution in every axis, so its voxels are not the scan's level-0 voxels
                row.setdefault(d["type"].replace("-", "_"), []).append(
                    {"url": url, **({"model": params["model_id"]} if params.get("model_id") else {}),
                     **({"level": params["level"]} if isinstance(params.get("level"), int) else {})})
        out.append(row)
    return out


def _segment_summary(sid, seg):
    props = seg.get("properties", {})
    frames, surface_volumes, inks, labels = [], [], 0, []
    for d in seg.get("data", []):
        params = d.get("parameters") or {}
        if d["type"] == "tifxyz-transformed":
            frames.append(params.get("target_volume"))
        elif d["type"] == "layers-zarr":
            surface_volumes.append(params.get("target_volume"))
        elif d["type"] in ("ink-detection", "3d-ink-prediction"):
            inks += 1
        elif d["type"] == "ink-labels":
            labels.append(params.get("target_volume"))
    return {"segment": sid, "long_id": seg.get("long_id"), "suffix": seg.get("suffix"),
            "size_px": [props.get("width"), props.get("height")], "original_volume": seg.get("original_volume_id"),
            "frames": sorted(f for f in frames if f), "surface_volumes": sorted(v for v in surface_volumes if v),
            "ink_maps": inks, "labels_on": sorted(v for v in labels if v)}


def segments(cat, sample, query=None, limit=100):
    rows = []
    for sid, seg in sorted(_sample(cat, sample).get("segments", {}).items()):
        if query and query.lower() not in (seg.get("long_id") or "").lower():
            continue
        rows.append(_segment_summary(sid, seg))
    return rows[:limit], len(rows)


def find_segment(cat, sample, key):
    segs = _sample(cat, sample).get("segments", {})
    if key in segs:
        return key, segs[key]
    k = key.lower()
    hits = [(sid, s) for sid, s in segs.items()
            if k in ((s.get("long_id") or "").lower(), (s.get("suffix") or "").lower())]
    hits = hits or [(sid, s) for sid, s in segs.items() if k in (s.get("long_id") or "").lower()]
    if len(hits) != 1:
        names = ", ".join(s.get("long_id", sid) for sid, s in hits[:10])
        raise CatalogError(f"{len(hits)} segments of {sample} match {key!r}" + (f": {names}" if hits else ""))
    return hits[0]


def segment(cat, sample, key):
    """Everything published for one segment, with HTTPS URLs."""
    sid, seg = find_segment(cat, sample, key)
    out = _segment_summary(sid, seg)
    out["created"] = (seg.get("creation") or {}).get("date")
    out["data"] = [{"type": d["type"], "url": data_url(d), **(d.get("parameters") or {}),
                    **({"properties": d["properties"]} if d.get("properties") else {})}
                   for d in seg.get("data", []) if _origin(d)]
    return out


def tifxyz_prefix(cat, sample, key, frame=None):
    """Bucket prefix of a segment's tifxyz in the frame of volume `frame` (or as traced)."""
    sid, seg = find_segment(cat, sample, key)
    options = {}
    for d in seg.get("data", []):
        if d["type"] == "tifxyz-transformed":
            options[(d.get("parameters") or {}).get("target_volume")] = _origin(d)
        elif d["type"] == "tifxyz":
            options.setdefault(None, _origin(d))
    if frame not in options:
        raise CatalogError(f"{seg.get('long_id')} has no tifxyz in the frame of volume {frame!r}; frames: "
                           f"{sorted(str(k) for k in options if k)} (or omit frame for the original)")
    return seg.get("long_id"), options[frame]


def transforms(cat, sample, from_volume=None):
    props = (_sample(cat, sample).get("sample") or {}).get("properties", {})
    out = []
    for t in props.get("volume_transforms", []) or []:
        if from_volume and t.get("from_volume_id") != from_volume:
            continue
        for x in t.get("transforms", []):
            out.append({"from": t.get("from_volume_id"), "to": x.get("to_volume_id"), "matrix_xyz": x.get("matrix")})
    return out


def models(cat):
    return [{"model": mid, "long_id": m.get("long_id"), **{k: (m.get("properties") or {}).get(k)
                                                          for k in ("task", "architecture", "patch_size")}}
            for mid, m in sorted(cat.get("models", {}).items())]


def volume_for_url(cat, url):
    """(sample, volume row) whose ome-zarr URL is `url`, or None."""
    want = url.rstrip("/").split("vesuvius-challenge-open-data")[-1].lstrip("/").split("/", 1)[-1]
    for sid, s in cat.get("samples", {}).items():
        for v in volumes(cat, sid):
            if v.get("url") and v["url"].rstrip("/").endswith(want):
                return sid, v
    return None


def volume_by_id(cat, vid):
    """(sample, volume row) for a volume id (the timestamp that starts a volume's name), or None."""
    for sid, sample in cat.get("samples", {}).items():
        if vid in (sample.get("volumes") or {}):
            return sid, next(v for v in volumes(cat, sid) if v["volume"] == vid)
    return None


def umbilicus_for(cat, volume):
    """URL of the catalog's umbilicus for a volume given by URL, id or folder name, or None."""
    hit = volume_for_url(cat, volume) if re.match(r"^(https?|s3)://", str(volume), re.I) else None
    if hit is None:
        hit = volume_by_id(cat, str(volume).rstrip("/").split("/")[-1].split("-")[0])
    found = (hit[1].get("umbilicus") if hit else None) or []
    return found[0]["url"] if found else None


# ---------------------------------------------------------------- Hugging Face downloads

def hf_files(repo, revision, opener=None):
    """(path, size, expected hash) per file of a repository at a revision. The hash is the one Hugging Face's
    file list gives: ("sha256", lfs.oid) for a Git LFS file, else ("git-sha1", oid), the git blob id; None
    when the list gives neither."""
    url = f"{HF}/api/models/{repo}/tree/{urllib.parse.quote(revision, safe='')}?recursive=1"
    with _open(url, opener) as resp:
        entries = json.loads(_read(resp))
    out = []
    for e in entries:
        if e.get("type") != "file":
            continue
        lfs = e.get("lfs") or {}
        if re.fullmatch(r"[0-9a-f]{64}", str(lfs.get("oid") or lfs.get("sha256") or "")):
            want = ("sha256", lfs.get("oid") or lfs.get("sha256"))
        elif not lfs and re.fullmatch(r"[0-9a-f]{40}", str(e.get("oid") or "")):
            want = ("git-sha1", e["oid"])
        else:
            want = None
        out.append((e["path"], e.get("size"), want))
    return out


def file_hash(path, algo, chunk=1 << 22):
    """Hex digest of a file: algo "sha256", or "git-sha1" (the git blob id, sha1 over "blob SIZE\\0" + bytes)."""
    if algo == "sha256":
        return sha256_file(path, chunk)
    if algo != "git-sha1":
        raise CatalogError(f"unknown hash {algo!r}")
    h = hashlib.sha1(b"blob %d\0" % Path(path).stat().st_size)
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _set_aside(path):
    """Move a file that failed its hash to <name>.bad, so it never sits at the path a loader reads."""
    bad = path.with_name(path.name + ".bad")
    path.replace(bad)
    return bad


def download(url, dest, opener=None, chunk=1 << 22, expect_size=None, timeout=600, expect_hash=None):
    """Download to dest; returns (bytes, headers). With expect_hash, an (algo, hex) pair (see file_hash), a
    complete file already at dest is kept only when its hash matches (else it is moved to dest.bad and fetched
    again), and new bytes that do not match go to dest.bad, never dest. Without it, a file of expect_size is kept."""
    dest = Path(dest)
    if dest.is_file() and expect_size and dest.stat().st_size == expect_size:
        if not expect_hash:
            return dest.stat().st_size, {}
        if file_hash(dest, expect_hash[0]) == expect_hash[1]:
            return dest.stat().st_size, {}
        _set_aside(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Each call writes its own part file, so two downloads of the same file at once (two workers fetching
    # one model onto a shared volume) never write into or move each other's partial bytes.
    part = dest.with_name(f"{dest.name}.{uuid.uuid4().hex[:12]}.part")
    try:
        with _open(url, opener, timeout=timeout, gzip_ok=False) as resp, open(part, "xb") as fh:
            headers = dict(resp.headers.items())
            while True:
                block = resp.read(chunk)
                if not block:
                    break
                fh.write(block)
        size = part.stat().st_size
        if expect_size and size != expect_size:
            raise CatalogError(f"{url}: got {size} bytes, expected {expect_size}")
        if expect_hash:
            got = file_hash(part, expect_hash[0])
            if got != expect_hash[1]:
                bad = dest.with_name(dest.name + ".bad")
                part.replace(bad)
                raise CatalogError(f"{url}: {expect_hash[0]} {got}, expected {expect_hash[1]}; the file is set "
                                   f"aside at {bad} for inspection")
        part.replace(dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return size, headers


def sha256_file(path, chunk=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def file_url(spec, path):
    """Where one file of a KNOWN_MODELS entry is downloaded from: Hugging Face (default) or a GitHub release."""
    rev = urllib.parse.quote(spec["revision"], safe="")
    if spec.get("host", "huggingface") == "github-release":
        return f"https://github.com/{spec['repo']}/releases/download/{rev}/{urllib.parse.quote(path)}"
    if spec.get("host", "huggingface") != "huggingface":
        raise CatalogError(f"{spec['repo']}: unknown host {spec['host']!r}")
    return f"{HF}/{spec['repo']}/resolve/{rev}/{urllib.parse.quote(path)}"


def _inside(dest, path):
    """dest/path for a relative path from a file list, refused when it is absolute, has a .. part or
    resolves outside dest."""
    rel = PurePosixPath(str(path))
    if not str(path) or "\\" in str(path) or rel.is_absolute() or any(p in ("", ".", "..") for p in str(path).split("/")):
        raise CatalogError(f"refusing file path {path!r}: not a plain relative path")
    root = Path(dest).resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise CatalogError(f"refusing file path {path!r}: it leaves {dest}")
    return Path(dest) / rel


def fetch_model(name, dest, opener=None, log=print):
    """Download a KNOWN_MODELS entry into dest; returns a receipt dict. Every file is checked against a hash
    (the pinned sha256, else the one Hugging Face's file list gives) before it is kept, also when it is
    already on disk; a file with no hash to check is refused."""
    spec = KNOWN_MODELS[name]
    repo, rev = spec["repo"], spec["revision"]
    pins = spec.get("sha256", {})
    if spec.get("snapshot"):
        files = [(p, s, h) for p, s, h in hf_files(repo, rev, opener)
                 if not any(fnmatch.fnmatch(p, pat) for pat in spec.get("exclude", []))]
    else:
        files = [(p, None, None) for p in spec["files"]]
    files = [(p, s, ("sha256", pins[p]) if p in pins else h) for p, s, h in files]
    for path, _size, want in files:
        _inside(dest, path)
        if not want:
            raise CatalogError(f"{repo}/{path}: no pinned or listed hash to check it against; refusing it")
    got, commit = [], None
    for path, size, want in files:
        url = file_url(spec, path)
        target = _inside(dest, path)
        log(f"downloading {repo}/{path}")
        n, headers = download(url, target, opener, expect_size=size, expect_hash=want)
        commit = commit or headers.get("X-Repo-Commit") or headers.get("x-repo-commit")
        digest = sha256_file(target)
        got.append({"path": path, "bytes": n, "sha256": digest, "sha256_checked": path in pins,
                    "hash_checked": want[0]})
    return {"model": name, "repo": repo, "revision": rev, "resolved_commit": commit, "dest": str(dest),
            "files": got, "engine": spec["engine"],
            "checkpoint": str(Path(dest) / spec["checkpoint"]) if spec.get("checkpoint") else None,
            "model_dir": str(dest) if spec["engine"] == "v8in" else None}
