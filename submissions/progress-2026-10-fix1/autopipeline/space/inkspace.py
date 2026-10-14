"""The parts of the AutoPipeline ink Space that need no model: the samples and the allow-list, crop sizing, the
bucket reads, the checks on the maps, scoring, the page text and the list of files the Space is made of.

No torch and no gradio here, so the tests run without them. numpy and kit are imported where they are used.

  python3 inkspace.py files        the files of the Space, with their SHA-256
  python3 inkspace.py stage DEST   copy them into DEST (absent or empty), laid out as the Space runs them
"""

from __future__ import annotations

import base64
import hashlib
import html
import importlib.util
import json
import math
import os
import re
import shutil
import struct
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLES_FILE = HERE / "samples.json"
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"

# The only segments the Space reads, with what each one is to ink_9um. Anything else is refused before a byte is
# fetched, so a sample file edited by mistake cannot point the Space at other data.
ALLOWED = {
    ("PHerc0841", "20260220213127-w00"): "development",
    ("PHerc0841", "20260220214732-auto_grown_20260220144552896"): "development",
    ("PHerc0139", "20260317000000-w035_2026031718"): "training",
    ("PHerc0139", "20260126000000-w045_2026012619"): "training",
}

# villa's flat inference for ink_9um: 128 px patches, villa's default overlap 0.5 (stride 64), Hann blending.
PATCH = 128
STRIDE = 64
INPUT_DEPTH = 17
INNER = 64            # edge left out of the AUC: a crop sees less context there than the whole segment does
LABEL_LEVEL = "2"     # the 2.4 um labels' level 2 is the 9 um surface grid up to a uniform scale (kit/auc.py)
FEW_PX = 100_000      # below this many scored pixels (about 3 mm square) the page says the AUC is noisy

MIN_SIDE, MAX_SIDE = PATCH, 768
MIN_LAYERS, MAX_LAYERS = INPUT_DEPTH, 65
MAX_UPLOAD_BYTES = 64 * 2 ** 20
DTYPES = ("uint8", "uint16")
# The page's images (the CT layer and both maps) go to the browser as PNG data inside the page, so they are never
# written to the Space's disk. Gradio writes an upload to its cache when it is chosen; read_upload deletes it on Run.
# An upload never run is deleted by Gradio's sweep: every CACHE_SWEEP_S it deletes uploads older than UPLOAD_MAX_AGE_S.
# The age is well above a run's time in the queue; an upload deleted while it waited is refused with a request to
# upload it again.
CACHE_SWEEP_S, UPLOAD_MAX_AGE_S = 60, 600
UNRUN_UPLOAD_MINUTES = (CACHE_SWEEP_S + UPLOAD_MAX_AGE_S) // 60

# One GPU call per run, both directions. Seconds per 128 px patch inside the call: villa's per-patch normalisation,
# which runs in the call too (measured at about 0.03 s on a 4-core CPU, 13 Oct 2026), and the model's forward pass
# (about 0.01 to 0.02 s on half an RTX Pro 6000 at batch 1). The overhead covers moving the model and starting CUDA.
SEC_PER_PATCH = 0.06
OVERHEAD_S = 10.0
MIN_GPU_S, MAX_GPU_S = 20, 60

SPACE_FILES = ("README.md", "app.py", "inkspace.py", "samples.json", "requirements.txt")
KIT_MODULES = ("__init__", "auc", "fetch", "layers", "s3retry", "vc3d_audit", "vc3d_io", "vc3d_region", "verify")
EXTRA_FILES = ("scripts/vc3d/ink.py", "LICENSE")

INTRO = """# AutoPipeline ink step

Pick a crop of a released segment, or upload a small surface volume. The Space runs the released `ink_9um` ink
model on it twice: once with the layers in their stored order, and once with the layers reversed. The reversed map
is the control. A model that reads ink in depth order should do worse on it. Where the crop has published ink
labels, both maps get a pixel AUC.

AutoPipeline runs villa's pipeline from a released scan to a scored ink map, with checks that can fail at every
step. This is its last step only.

**An ink map is model output, not a reading.**
"""

UPLOAD_TEXT = (f"A surface volume as `.npy` or a multi-page `.tif`, layers first (layers x height x width), "
               f"{' or '.join(DTYPES)}, {MIN_SIDE} to {MAX_SIDE} px a side, {MIN_LAYERS} to {MAX_LAYERS} layers, "
               f"at most {MAX_UPLOAD_BYTES // 2 ** 20} MB. When you press Analyze upload it is read into memory and "
               f"its upload "
               f"file is deleted; a file you upload but do not run is deleted within {UNRUN_UPLOAD_MINUTES} minutes. "
               f"The images of it (its middle layer and the two maps) are sent inside the page and never written to "
               f"the Space's disk. Uploads get maps but no AUC, since there are no labels for them.")

AUC_TEXT = ("AUC: the chance that a labelled ink pixel scores above a labelled background pixel, inside the "
            f"labelled area, leaving out a {INNER} px edge. 0.5 is chance.")


class SpaceError(ValueError):
    """A request the Space refuses; the message is shown to the visitor as it is."""


# ---------------------------------------------------------------- where things are

def find_root(start=HERE):
    """The folder holding kit/: the Space itself once staged, else the release (or repository) it sits in."""
    start = Path(start).resolve()
    for folder in (start, *start.parents):
        if (folder / "kit" / "__init__.py").is_file():
            return folder
    raise SpaceError(f"kit/ is neither in {start} nor above it")


def on_path(root=None):
    root = str(root or find_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    return Path(root)


def sha256_file(path, bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def readers_row(name, root=None):
    """The row of scripts/firstletters/readers.tsv (the repository's list of released readers and their SHA-256)
    for one reader, or None when that file is not here (the staged Space carries the checkpoint in samples.json)."""
    try:
        path = Path(root or find_root()) / "scripts" / "firstletters" / "readers.tsv"
    except SpaceError:
        return None
    if not path.is_file():
        return None
    lines = path.read_text().splitlines()
    head = lines[0].split("\t")
    for line in lines[1:]:
        row = dict(zip(head, line.split("\t")))
        if row.get("name") == name:
            return row
    return None


# ---------------------------------------------------------------- samples and the allow-list

def _relative(part):
    return bool(part) and "://" not in part and not part.startswith("/") and ".." not in part.split("/")


def check_sample(sample, bucket=BUCKET):
    """Refuse a sample outside the allow-list, with the wrong role, off the open-data bucket, or with a crop that
    is off its surface or outside the size limits. Returns the sample."""
    key = (sample.get("scroll"), sample.get("segment"))
    role = ALLOWED.get(key)
    if role is None:
        raise SpaceError(f"{key[0]} {key[1]} is not one of the segments this Space may read")
    if sample.get("role") != role:
        raise SpaceError(f"{sample.get('id')}: role {sample.get('role')!r}, but this segment is {role!r} data")
    if bucket != BUCKET:
        raise SpaceError(f"samples must come from {BUCKET}, not {bucket}")
    for part in ("surface_volume", "labels"):
        if not _relative(sample.get(part, "")):
            raise SpaceError(f"{sample.get('id')}: {part} must be a plain path inside the segment")
    if not sample.get("note") or not sample.get("title") or not sample.get("id"):
        raise SpaceError("every sample needs an id, a title and a note saying what it is")
    H, W = (int(v) for v in sample["surface_shape"])
    y0, y1, x0, x1 = (int(v) for v in sample["crop"])
    if not (0 <= y0 < y1 <= H and 0 <= x0 < x1 <= W):
        raise SpaceError(f"{sample['id']}: crop {sample['crop']} is outside the {H} x {W} surface")
    check_side(y1 - y0, x1 - x0)
    return sample


def load_samples(path=SAMPLES_FILE):
    data = json.loads(Path(path).read_text())
    seen = set()
    for sample in data["samples"]:
        check_sample(sample, data.get("bucket"))
        if sample["id"] in seen or sample["title"] in seen:
            raise SpaceError(f"sample {sample['id']} is listed twice")
        seen.update((sample["id"], sample["title"]))
    ck = data["checkpoint"]
    if not re.fullmatch(r"[0-9a-f]{64}", ck.get("sha256", "")):
        raise SpaceError("the checkpoint needs its SHA-256")
    return data


def sample_by(key, data=None):
    data = data or load_samples()
    for sample in data["samples"]:
        if key in (sample["id"], sample["title"]):
            return sample
    raise SpaceError(f"no sample {key!r}")


def segment_url(sample, part="surface_volume", bucket=BUCKET):
    return f"{bucket}/{sample['scroll']}/segments/{sample['segment']}/{sample[part]}"


def label_prefix(sample):
    return f"{sample['scroll']}/segments/{sample['segment']}/{sample['labels']}"


def window(sample, size=None):
    """The sample's crop, or a size x size square at its centre (a quicker run on the same labelled window)."""
    y0, y1, x0, x1 = (int(v) for v in sample["crop"])
    if size is None:
        return y0, y1, x0, x1
    size = int(size)
    if not MIN_SIDE <= size <= min(y1 - y0, x1 - x0):
        raise SpaceError(f"size {size} must be {MIN_SIDE} to {min(y1 - y0, x1 - x0)} px for {sample['id']}")
    top, left = (y0 + y1) // 2 - size // 2, (x0 + x1) // 2 - size // 2
    return top, top + size, left, left + size


# ---------------------------------------------------------------- sizing the GPU call

def positions(length, patch=PATCH, stride=STRIDE):
    """Patch starts along one axis, the last one flush with the end (villa's _sliding_positions_1d)."""
    if length <= patch:
        return [0]
    out = list(range(0, length - patch + 1, max(1, stride)))
    if out[-1] != length - patch:
        out.append(length - patch)
    return out


def patches(height, width):
    """Patches villa schedules per direction on a fully occupied height x width crop."""
    return len(positions(height)) * len(positions(width))


def gpu_seconds(height, width):
    """The duration one call asks for: both directions of a height x width crop. Refuses a crop that would need
    more than MAX_GPU_S."""
    need = OVERHEAD_S + 2 * patches(height, width) * SEC_PER_PATCH
    if need > MAX_GPU_S:
        raise SpaceError(f"a {height} x {width} crop needs about {need:.0f} GPU seconds, more than the "
                         f"{MAX_GPU_S} s one call may ask for; use a smaller crop")
    return int(max(MIN_GPU_S, math.ceil(need)))


def check_side(height, width):
    for name, side in (("height", height), ("width", width)):
        if not MIN_SIDE <= side <= MAX_SIDE:
            raise SpaceError(f"{name} {side} px: crops must be {MIN_SIDE} to {MAX_SIDE} px a side")
    return gpu_seconds(height, width)


def check_volume(shape, dtype):
    """Refuse a volume that is not (layers, height, width), not uint8 or uint16, or outside the size limits."""
    if len(shape) != 3:
        raise SpaceError(f"a surface volume has 3 axes (layers, height, width), this one has {len(shape)}")
    if str(dtype) not in DTYPES:
        raise SpaceError(f"type {dtype}: use {' or '.join(DTYPES)}")
    layers, height, width = (int(v) for v in shape)
    if not MIN_LAYERS <= layers <= MAX_LAYERS:
        raise SpaceError(f"{layers} layers: use {MIN_LAYERS} to {MAX_LAYERS}, layers first")
    check_side(height, width)
    return layers, height, width


def _read_npy(path):
    """A .npy whose header passes check_volume, then its data. The shape and type come from the header, so a file
    that claims a huge array is refused before anything is allocated."""
    import numpy as np
    fmt = np.lib.format
    readers = {(1, 0): fmt.read_array_header_1_0, (2, 0): fmt.read_array_header_2_0}
    with open(path, "rb") as fh:
        try:
            version = fmt.read_magic(fh)
            if version not in readers:
                raise ValueError(f".npy format version {version[0]}.{version[1]}")
            shape, _, dtype = readers[version](fh)
        except (ValueError, OSError, SyntaxError) as exc:
            raise SpaceError(f"not a plain .npy array: {exc}") from None
    if dtype.hasobject:
        raise SpaceError("not a plain .npy array: it holds Python objects")
    check_volume(shape, dtype)
    try:
        return np.load(path, allow_pickle=False)
    except ValueError as exc:
        raise SpaceError(f"not a plain .npy array: {exc}") from None


def _read_tif(path):
    """A multi-page .tif whose first series passes check_volume, then its pixels. The shape and type come from the
    TIFF's tags, so a small compressed file that would decode to a huge array is refused before it is decoded."""
    import tifffile
    try:
        with tifffile.TiffFile(str(path)) as tif:
            series = tif.series[0]
            check_volume(series.shape, series.dtype)
            return series.asarray()
    except SpaceError:
        raise
    except Exception as exc:   # tifffile raises many kinds on a broken file
        raise SpaceError(f"not a readable .tif: {type(exc).__name__}: {exc}") from None


def read_upload(path, delete=True):
    """An uploaded .npy or multi-page .tif as a (layers, height, width) array in memory. Its shape and type are
    checked from the file's header before its data are read or decoded. The upload file is deleted as soon as it is
    read (or refused), so nothing of it is kept on disk."""
    path = Path(path)
    try:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            raise SpaceError(f"the upload file is gone (an upload not run within {UPLOAD_MAX_AGE_S // 60} minutes "
                             "is deleted); upload it again") from None
        if size > MAX_UPLOAD_BYTES:
            raise SpaceError(f"the upload is {size / 2 ** 20:.1f} MB; the limit is {MAX_UPLOAD_BYTES // 2 ** 20} MB")
        suffix = path.suffix.lower()
        import numpy as np
        if suffix == ".npy":
            arr = _read_npy(path)
        elif suffix in (".tif", ".tiff"):
            arr = _read_tif(path)
        else:
            raise SpaceError(f"{suffix or 'no extension'}: upload a .npy or a .tif")
        arr = np.ascontiguousarray(arr)
    finally:
        if delete:
            try:
                path.unlink()
            except OSError:
                pass
    check_volume(arr.shape, arr.dtype)
    return arr


# ---------------------------------------------------------------- reading the bucket

def read_crop(sample, box):
    """The crop's voxels, all layers, from the open-data bucket through kit's region reader (anonymous HTTPS; a 404
    counts as a missing chunk only when S3 says NoSuchKey). Refuses a crop with a missing chunk."""
    on_path()
    from kit import vc3d_region
    url = segment_url(sample)
    vol = vc3d_region.Volume(url)
    shape = vol.shape(0)
    if [int(v) for v in shape[1:]] != [int(v) for v in sample["surface_shape"]]:
        raise SpaceError(f"{url} is {shape[1:]}, the sample says {sample['surface_shape']}")
    y0, y1, x0, x1 = box
    data = vol.read(0, [[0, shape[0]], [y0, y1], [x0, x1]])
    info = {"url": url, "box": [y0, y1, x0, x1], "layers": int(shape[0]), "chunks_read": vol.chunks_read,
            "missing_chunks": vol.missing, "requests": vol.store.requests, "false_404s": vol.store.false_404s}
    if vol.missing:
        raise SpaceError(f"{vol.missing} chunks under this crop are missing from the bucket; the map would have holes")
    return data, info


def labels_for(sample, box, map_shape):
    """Ink and supervision of the crop on the map's own grid: kit/fetch.py copies the segment's label folder
    (about 0.5 MB) into a temporary folder, kit/auc.py maps it onto the crop, and the folder is removed."""
    on_path()
    from kit import auc, fetch
    with tempfile.TemporaryDirectory(prefix="ink-labels-") as tmp:
        fetch.fetch_prefix(label_prefix(sample), tmp)
        ink, supervised = auc.labels_on_map(Path(tmp) / "inklabels.zarr", Path(tmp) / "supervision.zarr",
                                            LABEL_LEVEL, tuple(int(v) for v in sample["surface_shape"]), tuple(box),
                                            tuple(map_shape))
    return ink, supervised


# ---------------------------------------------------------------- the maps

def require_pair(result):
    """The forward map and its control, or a refusal: the Space never shows a forward map alone."""
    forward, reverse = result.get("forward"), result.get("reverse")
    if forward is None or reverse is None:
        raise SpaceError("the run did not return both the forward map and its reversed control; nothing is shown")
    if getattr(forward, "shape", None) != getattr(reverse, "shape", None):
        raise SpaceError("the forward map and its control differ in shape; nothing is shown")
    return forward, reverse


def ink_checks(root=None):
    """scripts/vc3d/ink.py, the repository's ink step, for its checks on maps (unreadable, compare)."""
    path = Path(root or find_root()) / "scripts" / "vc3d" / "ink.py"
    spec = importlib.util.spec_from_file_location("autopipeline_ink_checks", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_maps(forward, reverse, surface, root=None):
    """ink.py's checks: refuse a constant or non-finite map, or a forward map identical to its control (what a
    broken GPU run writes). Returns ink.py's comparison of the two maps on the surface."""
    ink = ink_checks(root)
    probs = {"f": ink.probability(forward), "r": ink.probability(reverse)}
    reasons = ink.unreadable(probs, surface)
    if reasons:
        raise SpaceError("the maps cannot be read: " + "; ".join(reasons) + ". " + ink.advice(reasons))
    return ink.compare(probs["f"], probs["r"], surface)


def score_pair(forward, reverse, ink, supervised, inner=INNER):
    """kit/auc.py's pixel AUC of the forward map and of its control on the same pixels."""
    on_path()
    from kit import auc
    out = {"forward": auc.score_array(forward, ink, supervised, inner=inner),
           "reverse": auc.score_array(reverse, ink, supervised, inner=inner), "inner": inner}
    f, r = out["forward"]["auc"], out["reverse"]["auc"]
    out["difference"] = None if f is None or r is None else round(f - r, 4)
    return out


def display(arr):
    """A 2-D array as uint8 for the page: uint8 as it is, anything else stretched between its 1st and 99th
    percentiles."""
    import numpy as np
    a = np.asarray(arr)
    if a.dtype == np.uint8:
        return a
    lo, hi = np.percentile(a, [1, 99]) if a.size else (0, 1)
    scaled = (a.astype(np.float32) - lo) / max(float(hi - lo), 1e-6)
    return (np.clip(scaled, 0, 1) * 255).astype(np.uint8)


def png_bytes(gray):
    """A 2-D uint8 array as a greyscale PNG, made in memory (zlib only, no imaging library and no file)."""
    import numpy as np
    a = np.asarray(gray)
    if a.ndim != 2 or a.dtype != np.uint8 or not a.size:
        raise SpaceError(f"an image for the page is a non-empty 2-D uint8 array, not {a.dtype} {a.shape}")
    h, w = a.shape
    rows = np.zeros((h, w + 1), np.uint8)   # each row starts with filter type 0
    rows[:, 1:] = a

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows.tobytes(), 6)) + chunk(b"IEND", b""))


def figures_html(images):
    """[(caption, 2-D array)] as one row of figures whose images are PNG data inside the HTML: what the page shows
    is sent to the browser and never written to the Space's disk."""
    parts = []
    heads = ("CT surface", "Stored order", "Reversed control")
    notes = ("Middle layer of the surface volume", "Ink model output", "Same volume, opposite depth order")
    for i, (caption, arr) in enumerate(images):
        uri = "data:image/png;base64," + base64.b64encode(png_bytes(display(arr))).decode("ascii")
        cap = html.escape(caption)
        title = heads[i] if i < len(heads) else cap
        note = notes[i] if i < len(notes) else cap
        parts.append(f'<figure class="ap-figure"><div class="ap-figure-head"><strong>{title}</strong>'
                     f'<span>{i + 1:02d}</span></div><div class="ap-image-well"><img src="{uri}" alt="{cap}" '
                     f'width="{arr.shape[1]}" height="{arr.shape[0]}"></div><figcaption>{note}</figcaption></figure>')
    return '<div class="ap-figures" aria-label="CT, ink map and control comparison">' + "".join(parts) + "</div>"


def empty_figures_html():
    """A useful initial comparison workspace, with no fake images or scores."""
    parts = []
    for i, (title, text, note) in enumerate((
        ("CT surface", "Surface volume", "Middle layer of the surface volume"),
        ("Stored order", "Ink map", "Ink model output"),
        ("Reversed control", "Control map", "Same volume, opposite depth order"),
    )):
        parts.append(f'<figure class="ap-figure"><div class="ap-figure-head"><strong>{title}</strong>'
                     f'<span>{i + 1:02d}</span></div><div class="ap-image-well"><div class="ap-empty">'
                     '<svg width="34" height="34" viewBox="0 0 34 34" fill="none" stroke="currentColor" '
                     'stroke-width="1" aria-hidden="true"><rect x="4.5" y="4.5" width="25" height="25" rx="2"/>'
                     '<path d="M9 12h16M9 17h16M9 22h16"/></svg>'
                     f'{text}<br>Available after analysis</div></div><figcaption>{note}</figcaption></figure>')
    return ('<div class="ap-figures" aria-label="Empty comparison workspace">' + "".join(parts) + '</div>'
            '<p class="ap-viewer-status" role="status"><span class="ap-status-dot" aria-hidden="true"></span>'
            'Choose a source, then run analysis. Both maps will appear together.</p>')


def metrics_html(result):
    """A compact result strip beside the full scoring explanation and receipt. No inferred scores."""
    sample, scores, receipt = result.get("sample"), result.get("scores"), result.get("receipt", {})
    title = html.escape(sample["title"] if sample else "Uploaded volume")
    shape = receipt.get("shape", [])
    dims = " × ".join(str(int(n)) for n in shape[1:]) if len(shape) == 3 else ""
    seconds = receipt.get("inference_seconds")
    timing = f"{float(seconds):.2f} s inference" if seconds is not None else ""
    status = (f'<div class="ap-result-status" role="status"><strong>{title}</strong><span>{dims} px</span>'
              f'<span>{timing}</span></div>')
    if not scores:
        return status + '<p class="ap-result-note">No labels for this volume. Maps are shown without AUC.</p>'
    f, r = scores["forward"], scores["reverse"]
    count = f["ink_px"] + f["background_px"]
    metrics = (("Stored-order AUC", _fmt(f["auc"])), ("Control AUC", _fmt(r["auc"])),
               ("AUC difference", _fmt(scores["difference"])), ("Scored pixels", f"{count:,}"))
    cells = "".join(f'<div class="ap-metric"><dt>{name}</dt><dd>{html.escape(value)}</dd></div>'
                    for name, value in metrics)
    note = ("Both maps scored on the same labelled pixels. AUC 0.5 is chance. "
            "See score details for the crop, sample role and evaluation limits.")
    if count < FEW_PX:
        note = f"Only {count:,} pixels were scored. AUC on this small area is noisy. " + note
    return status + '<dl class="ap-metrics" aria-label="Paired scores">' + cells + '</dl>' + (
        f'<p class="ap-result-note">{note}</p>')


def summary(result):
    """The text under the maps."""
    lines = []
    sample, scores = result.get("sample"), result.get("scores")
    if sample:
        lines.append(f"**{sample['title']}**, crop rows {result['box'][0]} to {result['box'][1]}, "
                     f"columns {result['box'][2]} to {result['box'][3]}. {sample['note']}")
    else:
        lines.append("**Uploaded volume.** No labels, so no AUC.")
    if scores:
        f, r = scores["forward"], scores["reverse"]
        lines += ["", "| Map | AUC | Ink px | Background px |", "| --- | --- | --- | --- |",
                  f"| Layers in stored order | {_fmt(f['auc'])} | {f['ink_px']} | {f['background_px']} |",
                  f"| Control, layers reversed | {_fmt(r['auc'])} | {r['ink_px']} | {r['background_px']} |",
                  "", f"Forward minus control: {_fmt(scores['difference'])}. {AUC_TEXT}"]
        if f["ink_px"] + f["background_px"] < FEW_PX:
            lines += ["", f"Only {f['ink_px'] + f['background_px']} px were scored. An AUC on so small an area is "
                          "mostly noise; the full 640 px crop scores 512 x 512 px."]
    lines += ["", "An ink map is model output, not a reading."]
    return "\n".join(lines)


def _fmt(v):
    return "none" if v is None else f"{v:.4f}"


# ---------------------------------------------------------------- the files of the Space

def staged_files(root=None):
    """{path in the Space: source file}: this folder's files, the kit modules they import, ink.py and the license."""
    root = Path(root or find_root())
    files = {name: HERE / name for name in SPACE_FILES}
    files.update({f"kit/{m}.py": root / "kit" / f"{m}.py" for m in KIT_MODULES})
    files.update({p: root / p for p in EXTRA_FILES})
    missing = [f"{k} ({v})" for k, v in files.items() if not Path(v).is_file()]
    if missing:
        raise SpaceError("missing: " + ", ".join(missing))
    return files


def kit_imports(path):
    """kit modules a kit module imports (`from . import x`, `from .x import`)."""
    src = Path(path).read_text()
    names = re.findall(r"^\s*from \.(\w+) import", src, flags=re.M)
    groups = re.findall(r"^\s*from \. import \(([^)]*)\)", src, flags=re.M)
    groups += re.findall(r"^[ \t]*from \. import ([\w, \t]+)$", src, flags=re.M)
    for group in groups:
        names += [n.strip().split(" as ")[0].strip() for n in group.replace("\n", " ").split(",") if n.strip()]
    return sorted(set(names))


def stage(dest, root=None):
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise SpaceError(f"{dest} is not empty")
    files = staged_files(root)
    for target, source in sorted(files.items()):
        out = dest / target
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, out)
    return sorted(files)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["files"] and len(argv) == 1:
        files = staged_files()
        print(json.dumps([{"path": k, "sha256": sha256_file(v), "bytes": os.path.getsize(v)}
                          for k, v in sorted(files.items())], indent=1))
        return 0
    if argv[:1] == ["stage"] and len(argv) == 2:
        print(json.dumps(stage(argv[1]), indent=1))
        return 0
    print(__doc__.strip().split("\n\n")[-1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
