"""Surface prediction for a scan the catalog has none for: the CPU side of scripts/vc3d/modal_surface.py.

The tracers (vc_grow_seg_from_seed, kit autopipe) grow on a binary recto-surface prediction and its normal grids.
The open-data catalog has them for 41 of its 74 volumes; PHerc0172, PHerc1667 and PHercParis3 have none at all
(docs/surfacepred.md). The organisers made theirs with villa's `vesuvius.predict` and `vesuvius.blend_and_finalize`
and the nnU-Net model "m7" (catalog model 20260413222639; public copy scrollprize/surface_m7_nnunet on Hugging
Face). That needs a GPU, so it runs on Modal; everything around it is here, on CPU, with tests:

  plan      the patches `vesuvius.predict --bbox` runs for a box: the sliding-window grid of the whole volume
            (villa vesuvius/utils/models/helpers.py compute_steps_for_sliding_window), kept where a patch touches
            the box (vesuvius/data/vc_dataset.py _overlapping), so a box run gives the same voxels as a full run
  level     which pyramid level of a scan the model reads: level 0 of 7.9 to 9.4 um scans, level 2 of 2.2 to
            2.4 um scans. The catalog ran m7 at level 0 of 8.64 to 9.366 um scans and level 2 of 2.215 to 2.403 um
            scans only, so a 7.91 um scan is a transfer test, not the catalog's recipe; anything else is refused
  package   final.zarr (one (1, Z, Y, X) array with dot-separated chunk keys) to the catalog's layout: a 3D
            OME-Zarr group, level 0 plus levels 1 to 5 by nearest downsampling with ceil-shaped levels (VC3D
            refuses villa's build_pyramid, whose round-half-even shapes come out one short), meta.json for VC3D
            and the run record as run.json (VC3D reads a metadata.json without a "scan" key as an error)
  check     the rules VC3D applies when it opens a volume, and optionally VC3D itself
            (`vc_gen_normalgrids generate --print-plan` opens the volume and checks every level, then exits)
  dice      our prediction against a published one over a box: Dice, recall both ways within 2 voxels, Dice per
            192^3 chunk, and controls that must score low (the published map moved 1 voxel in z, y and x and 4 in
            x, another slab of the box), each also scored on the published map itself (VOID when the box cannot
            tell a shift apart)
  grids     normal grids against published ones: the share of polyline points within 1 and 2 px of the other set
            (GridStore v3 files as vc_gen_normalgrids writes them), with a slice 100 voxels away and shifted
            copies as controls
  contrast  is a prediction on the scan's sheets at all: CT values on predicted voxels against the rest of the
            scroll, against the other half of the box's prediction laid on this half (works with no published
            data; catches a wrong level, frame or volume, not a shift of a few voxels)
  seat      is a published segment on the new prediction: the share of its vertices within 2 voxels of the
            surface, against the same vertices moved half a sheet spacing along their normals
  box       a chunk-aligned box around a segment's vertices
  fetch     an arm's package and normal grids off the Modal volume (receipt PASS only), checked, with the
            external_prediction setting a plan takes (needs KIT_ALLOW_MODAL=1)

Every prediction here is model output, not a reading, and a box on a target scroll needs its ledger experiment
first (AGENTS.md rule 3). Standard library at import; numpy (and scipy for dilation) where a command computes;
numcodecs to write blosc chunks.
"""

import json
import math
import os
import shutil
import struct
import uuid
from pathlib import Path

from . import kithome

# ---------------------------------------------------------------- the recipe

CATALOG_MODEL = "20260413222639"           # catalog model id of m7 (Dataset100_VesuviusSurface, ResEncUNetLPlans)
HF_REPO = "scrollprize/surface_m7_nnunet"
CHECKPOINT = "fold_0/checkpoint_best.pth"
CHECKPOINT_BYTES = 820_473_701             # size listed on Hugging Face (survey, 9 Oct 2026)
PATCH = 192                                # plans.json 3d_fullres patch size
CHUNK = 192                                # chunks of the published predictions
OVERLAP = 0.5                              # vesuvius.predict default; a step of 96 voxels before uniform spacing
THRESHOLD = 0.2                            # foreground probability of the catalog's "th0.2"
LEVELS = 6                                 # OME levels of the published predictions
TFLOP_PER_PATCH = 5.2                      # Interpretation: conv-only count from plans.json (survey scripts/macs.py)
LEVEL_BANDS = ((0, 7.90, 9.40), (2, 2.20, 2.40))   # (level, lowest um, highest um), voxel size to 2 decimals
NORMALGRID_FLAGS = ("--level", "0", "--spiral-step", "20", "--grid-step", "64", "--sparse-volume", "1",
                    "--prune-min-length-px", "20")   # the published .normal-grids/metadata.json
BUCKET = "vesuvius-challenge-open-data"
BUCKET_URL = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
BLOSC = {"blocksize": 0, "clevel": 1, "cname": "zstd", "id": "blosc", "shuffle": 1}   # published level 0

# Fixed before any run (docs/compute/modal-specs/2026-10-09-surface-predict.md).
RULE = {"dice_min": 0.97, "control_max": 0.93, "grid_min": 0.90, "grid_control_max": 0.20,
        "seat_min": 0.80, "seat_control_max": 0.40, "contrast_min": 0.55, "contrast_margin": 0.05,
        "fraction_min": 0.02, "fraction_max": 0.60}
MARGIN = 32           # voxels left out at the box edge when a shifted copy is compared
TOLERANCE = 2         # voxels, for recall and seating
GRID_MARGIN = 64      # px left out at the box edge for the grid comparison


class SurfacePredError(ValueError):
    pass


def _np():
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - numpy is in every environment that computes
        raise SurfacePredError("this command needs numpy") from exc
    return numpy


# ---------------------------------------------------------------- level choice

def choose_level(voxel_um):
    """(level, effective voxel um) m7 reads for a scan of this voxel size: level 0 of 7.9 to 9.4 um scans, level 2
    of 2.2 to 2.4 um scans (voxel size to two decimals, so 2.403 is 2.40), which keeps the effective voxel near the
    catalog's. The catalog ran m7 at level 0 of 8.64 to 9.366 um scans and level 2 of 2.215 to 2.403 um scans only
    (Model output: the catalog cache of 9 Oct 2026); the band reaches down to 7.9 um so the 7.91 um scans can be
    tried as a transfer test. Anything else is refused. The model card does not state m7's training voxel sizes."""
    try:
        um = round(float(voxel_um), 2)
    except (TypeError, ValueError):
        raise SurfacePredError(f"voxel size {voxel_um!r} is not a number") from None
    for level, lo, hi in LEVEL_BANDS:
        if lo <= um <= hi:
            return level, round(float(voxel_um) * 2 ** level, 4)
    raise SurfacePredError(f"no m7 recipe for {voxel_um} um voxels: kit runs m7 on level 0 of 7.9 to 9.4 um scans "
                           "and level 2 of 2.2 to 2.4 um scans only (the catalog ran it on 8.64 to 9.366 um and "
                           "2.215 to 2.403 um)")


def ceil_shape(shape, level):
    """Shape of a pyramid level by VC3D's rule (core/src/Volume.cpp ceilDivPow2): ceil(n / 2^level) per axis."""
    d = 1 << int(level)
    return [-(-int(n) // d) for n in shape]


def pyramid_shapes(shape, levels=LEVELS):
    return [ceil_shape(shape, k) for k in range(levels)]


def round_shapes(shape, levels=LEVELS):
    """Shapes villa's build_pyramid gives (int(round(0.5 * n)) per level, half to even): VC3D refuses them where
    they fall below the ceil rule. Kept to document the difference."""
    out = [list(shape)]
    for _ in range(1, levels):
        out.append([max(1, int(round(0.5 * n))) for n in out[-1]])
    return out


def shape_ok(actual, expected, chunk):
    """VC3D's paddedShapeOK: a level may be padded by less than one chunk, never short."""
    return expected <= actual < expected + max(1, chunk)


# ---------------------------------------------------------------- patch grid

def sliding_steps(extent, patch=PATCH, overlap=OVERLAP):
    """Patch starts along one axis of the whole volume: villa's compute_steps_for_sliding_window (helpers.py), with
    `overlap` the step as a fraction of the patch (vesuvius.predict passes --overlap as step_size)."""
    extent, patch = int(extent), int(patch)
    if extent < patch:
        raise SurfacePredError(f"axis of {extent} voxels is shorter than the {patch} voxel patch")
    if not 0 <= overlap <= 1:
        raise SurfacePredError(f"overlap {overlap} is not between 0 and 1")
    target = max(1, patch if overlap == 0 else int(patch * overlap))
    n = int(math.ceil((extent - patch) / target)) + 1
    top = extent - patch
    step = top / (n - 1) if n > 1 else 99999999999
    return [min(int(round(step * i)), top) for i in range(n)]   # round() is half to even, as np.round


def parse_bbox(text):
    """"z0:z1,y0:y1,x0:x1" (half-open, level voxels) as [[z0, z1], [y0, y1], [x0, x1]]; every bound given."""
    parts = str(text).split(",")
    if len(parts) != 3:
        raise SurfacePredError(f"bbox {text!r} is not z0:z1,y0:y1,x0:x1")
    out = []
    for axis, part in zip("zyx", parts):
        lo, sep, hi = part.strip().partition(":")
        if not sep:
            raise SurfacePredError(f"bbox {axis} range {part!r} has no ':'")
        try:
            a, b = int(lo), int(hi)
        except ValueError:
            raise SurfacePredError(f"bbox {axis} range {part!r} needs two integers") from None
        if b <= a or a < 0:
            raise SurfacePredError(f"bbox {axis} range {part!r} is empty or negative")
        out.append([a, b])
    return out


def format_bbox(box):
    return ",".join(f"{int(a)}:{int(b)}" for a, b in box)


def clamp_bbox(box, shape, patch=PATCH):
    """villa's VCDataset._clamp_bbox_to_image: clamp to the volume, grow an axis shorter than the patch."""
    roi = []
    for (lo, hi), dim in zip(box, shape):
        lo_c, hi_c = min(lo, dim), min(hi, dim)
        if hi_c <= lo_c:
            raise SurfacePredError(f"bbox range [{lo}, {hi}) lies outside the volume (size {dim})")
        if hi_c - lo_c < patch:
            hi_c = min(lo_c + patch, dim)
            lo_c = max(0, hi_c - patch)
        roi.append([lo_c, hi_c])
    return roi


def patch_starts(shape, box, patch=PATCH, overlap=OVERLAP):
    """Patch starts per axis (z, y, x) that `vesuvius.predict --bbox` runs: the whole-volume grid, kept where a
    patch touches the box."""
    roi = clamp_bbox(box, shape, patch)
    return [[s for s in sliding_steps(n, patch, overlap) if s < hi and s + patch > lo]
            for n, (lo, hi) in zip(shape, roi)]


def plan_box(shape, box, patch=PATCH, overlap=OVERLAP, chunk=CHUNK, tflops=(20.0, 40.0)):
    """What a box costs and covers: patch count, the chunks it writes, whether it is chunk-aligned, and GPU seconds
    for an effective throughput range (Interpretation: no m7 run has been timed here)."""
    shape = [int(n) for n in shape]
    box = [[int(a), int(b)] for a, b in box]
    if len(shape) != 3 or len(box) != 3:
        raise SurfacePredError("shape and box need three axes (z, y, x)")
    starts = patch_starts(shape, box, patch, overlap)
    n = math.prod(len(s) for s in starts)
    aligned = all(a % chunk == 0 and (b % chunk == 0 or b == dim) for (a, b), dim in zip(box, shape))
    chunks = [[a // chunk, (min(b, dim) - 1) // chunk] for (a, b), dim in zip(box, shape)]
    tf = n * TFLOP_PER_PATCH
    return {"shape": shape, "bbox": format_bbox(box), "box": box, "patch": patch, "overlap": overlap,
            "patch_starts": starts, "patches": n, "chunk_aligned": aligned, "chunks": chunks,
            "chunk_count": math.prod(b - a + 1 for a, b in chunks),
            "voxels": math.prod(b - a for a, b in box),
            "tflop": round(tf, 1), "gpu_seconds": [round(tf / t) for t in sorted(tflops, reverse=True)],
            "note": "TFLOP per patch and the throughput range are Interpretation (a conv-only count from plans.json "
                    "and 20 to 40 effective TFLOP/s on an L4); no m7 run has been timed"}


def chunk_box(center_zyx, shape, n=3, chunk=CHUNK):
    """The chunk-aligned box of n chunks per axis whose middle chunk holds the centre, moved inside the volume."""
    out = []
    for c, dim in zip(center_zyx, shape):
        count = -(-int(dim) // chunk)
        k = min(max(0, int(c) // chunk - n // 2), max(0, count - n))
        out.append([k * chunk, min((k + n) * chunk, int(dim))])
    return out


def box_at_centre(xyz, valid, shape, n=3, chunk=CHUNK, scale=1.0):
    """The chunk-aligned box around the valid vertex nearest the middle of a tifxyz grid (the rule the spec fixes
    for test D: the densest box tends to sit where a mesh folds). Returns (box, that vertex as x, y, z)."""
    np = _np()
    h, w = valid.shape
    rr, cc = np.nonzero(valid)
    if not len(rr):
        raise SurfacePredError("the surface has no valid vertex")
    k = int(np.argmin((rr - (h - 1) / 2) ** 2 + (cc - (w - 1) / 2) ** 2))
    p = xyz[rr[k], cc[k]] * float(scale)
    return chunk_box(p[::-1], shape, n, chunk), [round(float(v), 2) for v in p]


def box_from_points(points_xyz, shape, n=3, chunk=CHUNK):
    """The chunk-aligned box of n chunks per axis that holds the most of these points (x, y, z voxels of the
    level); ties go to the lowest chunk index. Returns (box, points inside)."""
    np = _np()
    p = np.asarray(points_xyz, dtype=np.float64).reshape(-1, 3)
    zyx = np.floor(p[:, ::-1]).astype(np.int64)
    counts = [-(-int(d) // chunk) for d in shape]
    ok = np.all((zyx >= 0) & (zyx < np.array(shape)), axis=1)
    idx = zyx[ok] // chunk
    if not len(idx):
        raise SurfacePredError("no point lies inside the volume")
    hist = np.zeros(counts, dtype=np.int64)
    np.add.at(hist, tuple(idx.T), 1)
    c = np.zeros([k + 1 for k in counts], dtype=np.int64)
    c[1:, 1:, 1:] = hist.cumsum(0).cumsum(1).cumsum(2)
    m = [min(n, k) for k in counts]
    a0, a1, a2 = (k - w + 1 for k, w in zip(counts, m))
    s = (c[m[0]:m[0] + a0, m[1]:m[1] + a1, m[2]:m[2] + a2] - c[:a0, m[1]:m[1] + a1, m[2]:m[2] + a2]
         - c[m[0]:m[0] + a0, :a1, m[2]:m[2] + a2] - c[m[0]:m[0] + a0, m[1]:m[1] + a1, :a2]
         + c[:a0, :a1, m[2]:m[2] + a2] + c[:a0, m[1]:m[1] + a1, :a2] + c[m[0]:m[0] + a0, :a1, :a2]
         - c[:a0, :a1, :a2])
    k = np.unravel_index(int(np.argmax(s)), s.shape)
    box = [[int(i) * chunk, min((int(i) + w) * chunk, int(d))] for i, w, d in zip(k, m, shape)]
    return box, int(s[k])


# ---------------------------------------------------------------- URLs and inputs

def s3_url(url):
    """The s3:// form of an open-data HTTPS URL (vesuvius.predict reads s3 with --input_anon)."""
    text = str(url)
    if text.startswith("s3://"):
        return text
    for host in (BUCKET_URL, f"https://{BUCKET}.s3.amazonaws.com"):
        if text.startswith(host):
            return f"s3://{BUCKET}/" + text[len(host):].lstrip("/")
    raise SurfacePredError(f"{url} is not in the open-data bucket")


def predict_input(volume_url, level):
    """--input_dir for vesuvius.predict: the OME group for level 0 (VCDataset reads its array "0"), the level's
    own array for level 2 (VCDataset's bare-array branch; untested before the first test B run)."""
    base = s3_url(volume_url).rstrip("/") + "/"
    return base if int(level) == 0 else f"{base}{int(level)}/"


def prediction_name(volume_id, level, threshold=THRESHOLD):
    """The catalog's folder name for a prediction of this volume (the folder around it says who made it)."""
    th = f"{threshold:g}"
    return f"{volume_id}-surface-{CATALOG_MODEL}-surface-m7-L{int(level)}-th{th}.zarr"


# Normalization. From villa PR #1386 (ce9f09bd, 15 Aug 2026) on, vesuvius.predict gives an nnU-Net model the
# normalization its plans declare, so at e0bbb8b m7 runs with CTNormalization (clip 0 to 212, mean 87.54, std
# 47.74) and --normalization cannot change it (models/run/inference.py 534-547). Before it, predict fell back to
# the CLI default, per-patch instance_zscore. The catalog's m7 maps were written on 13 May 2026 (S3 headers), and
# TAUIL-Abd-Elilah reproduced them with that fallback at Dice 0.9984 on PHerc0841 L0 (vesuvius-repro, 28 Jul 2026;
# Community report). "published" restores the fallback inside e0bbb8b by turning the plans lookup off; "plans"
# runs e0bbb8b as it is. #1386 is the only change to models/run/inference.py between 9e120a3 (its parent) and
# e0bbb8b; the other changes on predict's path (a copy before normalizing, anonymous S3 reads, the network
# builder's refactor) should not change its numbers (Interpretation, from the diff). The predict log tells the
# two apart: e0bbb8b prints PLANS_NOTE only when the plans win.
NORMALIZATIONS = ("published", "plans")
PLANS_NOTE = "Using model-declared normalization"
PUBLISHED_LAUNCHER = ("import sys; import vesuvius.models.run.inference as inf; "
                      "inf._nnunet_normalization_from_model_info = lambda model_info: (None, None); "
                      "sys.argv[0] = 'vesuvius.predict'; sys.exit(inf.main())")


def predict_argv(model_dir, input_dir, out_dir, bbox, batch_size=4, device="cuda", workers=8,
                 normalization="published"):
    """vesuvius.predict with the settings the catalog's published metadata.json records (no TTA, batch 4; that file
    was backfilled after the run, so it is a reconstruction, not a log), from a local model folder downloaded at a
    pinned revision; --disable_tta is explicit because the code defaults to mirroring. normalization "published"
    runs it through PUBLISHED_LAUNCHER (argv[0] is then "python"), "plans" through the console script."""
    if normalization not in NORMALIZATIONS:
        raise SurfacePredError(f"normalization {normalization!r} is not one of {', '.join(NORMALIZATIONS)}")
    flags = ["--model_path", str(model_dir), "--model_type", "nnunet", "--input_dir",
             str(input_dir), "--input_anon", "--output_dir", str(out_dir), "--bbox", bbox, "--disable_tta",
             "--overlap", str(OVERLAP),
             "--batch_size", str(batch_size), "--device", device, "--num_workers", str(workers), "--verbose"]
    if normalization == "plans":
        return ["vesuvius.predict", *flags]
    return ["python", "-c", PUBLISHED_LAUNCHER, *flags]


def normalization_problem(log_text, normalization):
    """None when a predict log shows the normalization asked for, else why not. Read only the attempt's own part
    of the log: a log that also holds an earlier run can say either."""
    said = PLANS_NOTE in log_text
    if normalization == "plans" and not said:
        return f"the log lacks {PLANS_NOTE!r}, so the plans' CT normalization was not applied"
    if normalization == "published" and said:
        return f"the log says {PLANS_NOTE!r}, so the launcher did not restore the catalog's instance_zscore"
    if normalization not in NORMALIZATIONS:
        return f"normalization {normalization!r} is not one of {', '.join(NORMALIZATIONS)}"
    return None


def finalize_argv(logits_dir, final_zarr, threshold=THRESHOLD, workers=8):
    return ["vesuvius.blend_and_finalize", str(logits_dir), str(final_zarr), "--mode", "binary", "--threshold",
            "--threshold_value", f"{threshold:g}", "--chunk_size", f"{CHUNK},{CHUNK},{CHUNK}",
            "--num_workers", str(workers)]


def normalgrids_argv(pred, out, threads=8, metrics=None):
    argv = ["vc_gen_normalgrids", "generate", "-i", str(pred), "-o", str(out), *NORMALGRID_FLAGS,
            "--io-threads", str(threads)]
    return argv + (["--metrics-json", str(metrics)] if metrics else [])


# ---------------------------------------------------------------- zarr chunks

def _header(path):
    from . import vc3d_audit
    try:
        meta = vc3d_audit.array_meta(vc3d_audit.LocalStore(path), "")
    except vc3d_audit.AuditError as exc:
        raise SurfacePredError(f"{path}: {exc}") from exc
    if meta is None:
        raise SurfacePredError(f"{path}: no zarr array at its root (.zarray or zarr.json)")
    return meta


def _codec():
    try:
        import numcodecs
    except ImportError as exc:
        raise SurfacePredError("writing blosc chunks needs numcodecs") from exc
    return numcodecs.get_codec(dict(BLOSC))


def _zarray(shape, chunks=(CHUNK, CHUNK, CHUNK)):
    return {"chunks": list(chunks), "compressor": dict(BLOSC), "dimension_separator": "/", "dtype": "|u1",
            "fill_value": 0, "filters": None, "order": "C", "shape": list(shape), "zarr_format": 2}


def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".partial")
    tmp.write_text(json.dumps(obj, indent=4) + "\n")
    tmp.replace(path)


def _chunk_files(root, meta):
    """{chunk index: path} of the chunks on disk in a v2 or v3 array."""
    from . import vc3d_audit
    out = {}
    root = Path(root)
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f in vc3d_audit.META_FILES or f.startswith(".") or f.endswith(".partial"):
                continue
            key = Path(dirpath, f).relative_to(root).as_posix()
            idx = vc3d_audit.key_index(meta, key)
            if idx is not None:
                out[idx] = Path(dirpath, f)
    return out


def _decode(meta, raw):
    np = _np()
    from . import vc3d_audit
    data = (vc3d_audit._decompress(meta["compressor"], raw) if meta["zarr_format"] == 2
            else vc3d_audit._v3_bytes_codecs(meta["codecs"], raw))
    return np.frombuffer(data, dtype=np.uint8).reshape(meta["chunks"], order=meta.get("order") or "C")


def _read_level(level_dir, idx, codec, chunk):
    np = _np()
    p = Path(level_dir, *map(str, idx))
    if not p.is_file():
        return None
    return np.frombuffer(codec.decode(p.read_bytes()), dtype=np.uint8).reshape(chunk)


def _write_chunk(level_dir, idx, arr, codec):
    p = Path(level_dir, *map(str, idx))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".partial")
    tmp.write_bytes(codec.encode(arr.tobytes()))
    tmp.replace(p)


# ---------------------------------------------------------------- packaging

def package(final_zarr, out, voxel_um, record=None, levels=LEVELS, name=None, workers=2):
    """Turn vesuvius' final.zarr into the catalog layout VC3D and kit read (see the module docstring). Level 0
    keeps every chunk byte for byte when final.zarr is zarr v2 with the published codec (only the keys change,
    "0.z.y.x" to "z/y/x"); otherwise each chunk is decoded and written again. Levels 1 to levels-1 take every
    second voxel of the level above (villa's nearest rule) with ceil shapes; chunks with no surface are not
    written (they read as the fill value 0). `record` is written as run.json. Returns a summary."""
    import concurrent.futures
    np = _np()
    final_zarr, out = Path(final_zarr), Path(out)
    meta = _header(final_zarr)
    shape, chunks = list(meta["shape"]), list(meta["chunks"])
    if len(shape) == 4:
        if shape[0] != 1 or chunks[0] != 1:
            raise SurfacePredError(f"{final_zarr}: shape {shape} chunks {chunks}; expected one channel (1, Z, Y, X)")
        shape, chunks = shape[1:], chunks[1:]
    if len(shape) != 3:
        raise SurfacePredError(f"{final_zarr}: shape {meta['shape']} is not (1, Z, Y, X) or (Z, Y, X)")
    if str(meta["dtype"]).lstrip("<>|") not in ("u1", "uint8"):
        raise SurfacePredError(f"{final_zarr}: dtype {meta['dtype']}; vc_gen_normalgrids and the tracer need uint8")
    if meta.get("fill_value") not in (0, None):
        raise SurfacePredError(f"{final_zarr}: fill_value {meta.get('fill_value')}; VC3D needs 0")
    if meta.get("inner") is not None or meta.get("filters"):
        raise SurfacePredError(f"{final_zarr}: sharded or filtered arrays are not packaged here")
    if (out / "metadata.json").exists():
        raise SurfacePredError(f"{out}: has a metadata.json; VC3D would read it as the volume's metadata")
    if out.is_dir() and any(out.iterdir()):
        raise SurfacePredError(f"{out}: not empty; chunks left from an earlier package would stay where this "
                               "prediction is empty")
    out.mkdir(parents=True, exist_ok=True)
    codec = _codec()
    same = (meta["zarr_format"] == 2 and isinstance(meta.get("compressor"), dict)
            and {k: meta["compressor"].get(k) for k in ("id", "cname", "clevel", "shuffle")}
            == {k: BLOSC[k] for k in ("id", "cname", "clevel", "shuffle")} and (meta.get("order") or "C") == "C")
    files = _chunk_files(final_zarr, meta)
    lead = len(meta["shape"]) == 4
    level0 = out / "0"
    level0.mkdir(exist_ok=True)

    def one(item):
        idx, path = item
        dest_idx = idx[1:] if lead else idx
        if lead and idx[0] != 0:
            return None
        dest = Path(level0, *map(str, dest_idx))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if same:
            shutil.copyfile(path, dest)
        else:
            arr = _decode(meta, path.read_bytes()).reshape(chunks)
            _write_chunk(level0, dest_idx, np.ascontiguousarray(arr), codec)
        return tuple(dest_idx)

    with concurrent.futures.ThreadPoolExecutor(max(1, workers)) as pool:
        present = {i for i in pool.map(one, sorted(files.items())) if i is not None}
    _write_json(level0 / ".zarray", _zarray(shape, chunks))
    counts = [len(present)]
    shapes = pyramid_shapes(shape, levels)
    prev, prev_dir = present, level0
    for k in range(1, levels):
        lshape, ldir = shapes[k], out / str(k)
        ldir.mkdir(exist_ok=True)
        parents = sorted({tuple(i // 2 for i in idx) for idx in prev})

        def down(pidx, prev_dir=prev_dir, lshape=lshape, ldir=ldir):
            block = np.zeros([2 * c for c in chunks], dtype=np.uint8)
            got = False
            for dz in (0, 1):
                for dy in (0, 1):
                    for dx in (0, 1):
                        child = (2 * pidx[0] + dz, 2 * pidx[1] + dy, 2 * pidx[2] + dx)
                        arr = _read_level(prev_dir, child, codec, chunks)
                        if arr is not None:
                            got = True
                            block[dz * chunks[0]:(dz + 1) * chunks[0], dy * chunks[1]:(dy + 1) * chunks[1],
                                  dx * chunks[2]:(dx + 1) * chunks[2]] = arr
            if not got:
                return None
            small = np.ascontiguousarray(block[::2, ::2, ::2])
            for ax in range(3):   # zero the padding past the level's edge
                valid = lshape[ax] - pidx[ax] * chunks[ax]
                if valid < chunks[ax]:
                    sl = [slice(None)] * 3
                    sl[ax] = slice(max(0, valid), None)
                    small[tuple(sl)] = 0
            if not small.any():
                return None
            _write_chunk(ldir, pidx, small, codec)
            return pidx

        with concurrent.futures.ThreadPoolExecutor(max(1, workers)) as pool:
            done = {i for i in pool.map(down, parents) if i is not None}
        _write_json(ldir / ".zarray", _zarray(lshape, chunks))
        counts.append(len(done))
        prev, prev_dir = done, ldir
    _write_json(out / ".zgroup", {"zarr_format": 2})
    _write_json(out / ".zattrs", {"multiscales": [{
        "axes": [{"name": a, "type": "space"} for a in "zyx"],
        "datasets": [{"coordinateTransformations": [{"scale": [float(2 ** k)] * 3, "type": "scale"}], "path": str(k)}
                     for k in range(levels)],
        "name": "/", "version": "0.4"}]})
    vol_meta = {"uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, str(out.resolve()))), "name": name or out.name,
                "type": "vol", "format": "zarr", "width": shape[2], "height": shape[1], "slices": shape[0],
                "voxelsize": float(voxel_um), "min": 0.0, "max": 255.0}
    _write_json(out / "meta.json", vol_meta)
    if record is not None:
        _write_json(out / "run.json", record)
    return {"out": str(out), "shape": shape, "level_shapes": shapes, "chunks_written": counts,
            "level0_copied": bool(same), "meta": vol_meta}


def check_package(out):
    """Problems VC3D would refuse the volume for, as a list (empty when it would open): meta.json and its
    dimensions, a metadata.json without "scan" when there is no meta.json (VC3D reads metadata.json only then,
    core/src/Volume.cpp 1031-1034), every listed level's header, dtype and fill, and the ceil rule for level
    shapes (core/src/Volume.cpp loadMetadata, zarrOpen)."""
    out = Path(out)
    problems = []
    meta = None
    if (out / "metadata.json").is_file() and not (out / "meta.json").is_file():
        try:
            if "scan" not in json.loads((out / "metadata.json").read_text()):
                problems.append("metadata.json has no 'scan' key: VC3D throws on it")
        except ValueError:
            problems.append("metadata.json is not JSON")
    if not (out / "meta.json").is_file():
        problems.append("no meta.json: VC3D makes one up with voxel size 0")
    else:
        try:
            meta = json.loads((out / "meta.json").read_text())
        except ValueError:
            problems.append("meta.json is not JSON")
    try:
        attrs = json.loads((out / ".zattrs").read_text())
        paths = [d["path"] for d in attrs["multiscales"][0]["datasets"]]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return problems + ["no OME multiscales in .zattrs"]
    shapes = []
    for k, p in enumerate(paths):
        try:
            z = json.loads((out / p / ".zarray").read_text())
        except (OSError, ValueError):
            problems.append(f"level {p}: no readable .zarray")
            continue
        if len(z.get("shape", [])) != 3:
            problems.append(f"level {p}: shape {z.get('shape')} is not 3D")
            continue
        if z.get("dtype") != "|u1":
            problems.append(f"level {p}: dtype {z.get('dtype')}, not |u1")
        if z.get("fill_value") != 0:
            problems.append(f"level {p}: fill_value {z.get('fill_value')}, not 0")
        shapes.append((k, z["shape"], z.get("chunks") or [CHUNK] * 3))
    if shapes and meta is not None:
        base = [meta.get("slices"), meta.get("height"), meta.get("width")]
        if base != shapes[0][1]:
            problems.append(f"meta.json slices/height/width {base} differ from level 0 shape {shapes[0][1]}")
        if not meta.get("voxelsize"):
            problems.append("meta.json has no voxel size")
        for k, s, c in shapes:
            want = ceil_shape(base if all(isinstance(v, int) for v in base) else shapes[0][1], k)
            if not all(shape_ok(a, e, ch) for a, e, ch in zip(s, want, c)):
                problems.append(f"level {k}: shape {s}, VC3D expects {want} (ceil rule)")
    return problems


def vc3d_open(out, tools=None, timeout=300):
    """Open the volume with VC3D itself: `vc_gen_normalgrids generate --print-plan` builds the Volume (meta.json
    and every level's shape check) and exits before any work. Returns (ok, output); (None, why) when no VC3D
    tools are found (VC_BIN, VC_ROOTFS or PATH, kit/vc3d.py)."""
    import subprocess
    from . import vc3d
    tools = tools or vc3d.find_tools()
    if tools is None or not tools.has("vc_gen_normalgrids"):
        return None, "no vc_gen_normalgrids (set VC_BIN to a villa build)"
    argv = tools.argv("vc_gen_normalgrids", "generate", "-i", str(out), "--level", "0", "--print-plan")
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=vc3d.headless_env(threads=1))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return r.returncode == 0, (r.stdout + r.stderr)[-2000:]


# ---------------------------------------------------------------- reading boxes

def read_box(location, box, level=0, workers=4):
    """A box [[z0, z1], [y0, y1], [x0, x1]] of a local or remote OME-Zarr (or bare array) as uint8, through
    kit/vc3d_region.py (anonymous, paced, S3's false 404s retried; a missing chunk reads as fill)."""
    from . import vc3d_region
    vol = vc3d_region.Volume(str(location), workers=workers)
    return vol.read(level, box), {"chunks_read": vol.chunks_read, "missing": vol.missing}


# ---------------------------------------------------------------- Dice

def dice(a, b):
    s = int(a.sum()) + int(b.sum())
    return round(2.0 * int((a & b).sum()) / s, 4) if s else None


def _ball(radius):
    np = _np()
    r = int(radius)
    g = np.indices((2 * r + 1,) * 3) - r
    return (g ** 2).sum(0) <= r * r


def _dilate(a, radius):
    from scipy import ndimage
    return ndimage.binary_dilation(a, structure=_ball(radius))


def shifted_dice(a, b, axis, shift, margin=MARGIN):
    """Dice of a against b moved `shift` voxels along `axis` (a voxel p of a meets b at p - shift), over the box
    less `margin` on every side."""
    if abs(shift) > margin:
        raise SurfacePredError(f"shift {shift} is larger than the margin {margin}")
    core = [slice(margin, n - margin) for n in a.shape]
    moved = list(core)
    moved[axis] = slice(margin - shift, a.shape[axis] - margin - shift)
    return dice(a[tuple(core)], b[tuple(moved)])


def compare_box(ours, published, chunk=CHUNK, margin=MARGIN, tol=TOLERANCE, rule=RULE):
    """Our binary prediction against the published one over the same box (two uint8 or bool arrays): Dice over the
    whole box and per chunk, recall both ways within `tol` voxels, and the controls of the preregistered rule
    (Dice of ours against the published map moved 1 voxel in z, y and x, 4 voxels in x, and the first half of the
    box in z against the second half), plus the published map against itself moved the same way (the levels the
    survey measured), which say whether the box can tell a shift apart at all. Verdict: dice_verdict."""
    np = _np()
    a, b = np.asarray(ours) > 0, np.asarray(published) > 0
    if a.shape != b.shape or a.ndim != 3:
        raise SurfacePredError(f"boxes differ in shape: {a.shape} and {b.shape}")
    if min(a.shape) <= 2 * margin + 8:
        raise SurfacePredError(f"box {a.shape} is too small for a {margin} voxel margin")
    out = {"shape": list(a.shape), "ours_fraction": round(float(a.mean()), 4),
           "published_fraction": round(float(b.mean()), 4), "dice": dice(a, b)}
    core = tuple(slice(margin, n - margin) for n in a.shape)
    out["dice_core"] = dice(a[core], b[core])
    da, db = _dilate(a, tol), _dilate(b, tol)
    out[f"ours_within_{tol}_of_published"] = round(float((a & db).sum() / max(1, a.sum())), 4)
    out[f"published_within_{tol}_of_ours"] = round(float((b & da).sum() / max(1, b.sum())), 4)
    del da, db
    controls, reference = {}, {}
    for name, axis, s in (("shift_z1", 0, 1), ("shift_y1", 1, 1), ("shift_x1", 2, 1), ("shift_x4", 2, 4)):
        controls[name] = shifted_dice(a, b, axis, s, margin)
        reference[name] = shifted_dice(b, b, axis, s, margin)
    h = a.shape[0] // 2
    controls["other_slab_z"] = dice(a[:h], b[h:2 * h])
    reference["other_slab_z"] = dice(b[:h], b[h:2 * h])
    out["controls"], out["published_self_controls"] = controls, reference
    best = {"shift": [0, 0, 0], "dice": out["dice_core"]}
    for axis in range(3):
        for s in (-2, -1, 1, 2):
            d = shifted_dice(a, b, axis, s, margin)
            if d is not None and best["dice"] is not None and d > best["dice"]:
                best = {"shift": [s if i == axis else 0 for i in range(3)], "dice": d}
    out["best_shift"] = best
    per = []
    n = [-(-s // chunk) for s in a.shape]
    for cz in range(n[0]):
        for cy in range(n[1]):
            for cx in range(n[2]):
                sl = (slice(cz * chunk, (cz + 1) * chunk), slice(cy * chunk, (cy + 1) * chunk),
                      slice(cx * chunk, (cx + 1) * chunk))
                per.append({"chunk": [cz, cy, cx], "dice": dice(a[sl], b[sl]), "ours": int(a[sl].sum()),
                            "published": int(b[sl].sum())})
    out["per_chunk"] = per
    scored = [p["dice"] for p in per if p["dice"] is not None]
    out["per_chunk_min"] = min(scored) if scored else None
    out["verdict"] = dice_verdict(out, rule)
    return out


def dice_verdict(res, rule=RULE):
    """VOID when the published map against itself moved (published_self_controls) reaches rule["control_max"]: the
    box cannot tell a 1 voxel shift apart, whatever our map does. PASS when Dice reaches rule["dice_min"] and our map
    against every moved published map stays under rule["control_max"]. FAIL otherwise (a map off by a voxel scores
    high on one control and low on Dice)."""
    blind = {k: v for k, v in res["published_self_controls"].items() if v is not None and v >= rule["control_max"]}
    if blind:
        return {"verdict": "VOID", "why": f"the published map against itself moved reaches {rule['control_max']}: "
                                          f"{blind}"}
    high = {k: v for k, v in res["controls"].items() if v is not None and v >= rule["control_max"]}
    if res["dice"] is not None and res["dice"] >= rule["dice_min"] and not high:
        return {"verdict": "PASS", "why": f"Dice {res['dice']} >= {rule['dice_min']}; every control under "
                                          f"{rule['control_max']}"}
    why = f"Dice {res['dice']} (bar {rule['dice_min']})"
    return {"verdict": "FAIL", "why": why + (f"; controls at or over {rule['control_max']}: {high}" if high else "")}


def threshold_order(dice_02, dice_05):
    """The preregistered threshold check: the 0.5 arm must score lower against the published 0.2 map."""
    ok = dice_02 is not None and dice_05 is not None and dice_05 < dice_02
    return {"verdict": "PASS" if ok else "FAIL", "dice_th0.2": dice_02, "dice_th0.5": dice_05}


# ---------------------------------------------------------------- CT contrast (no published prediction needed)

def _auc_u8(fg, bg):
    """Probability that a uint8 value from fg exceeds one from bg (ties count half), from histograms."""
    np = _np()
    hf = np.bincount(fg.ravel(), minlength=256).astype(np.float64)
    hb = np.bincount(bg.ravel(), minlength=256).astype(np.float64)
    if not hf.sum() or not hb.sum():
        return None
    below = np.cumsum(hb) - hb
    return round(float((hf * (below + 0.5 * hb)).sum() / (hf.sum() * hb.sum())), 4)


def ct_contrast(ct, pred, margin=MARGIN, shift=4, rule=RULE):
    """A sanity check that needs no published prediction: the AUC of CT values on predicted voxels against the
    other voxels inside the scroll (CT > 0), over the box less `margin`. Its control is the prediction of the other
    half of the box in z laid on this half's CT (a prediction unrelated to these sheets). PASS when the AUC reaches
    rule["contrast_min"] and beats that control by rule["contrast_margin"]; FAIL otherwise, which is what a
    prediction on the wrong level, frame or volume gives.

    The prediction moved `shift` voxels either way along z, y and x is reported too, but it cannot gate: on the
    published PHerc0841 m7 test A box two of the six moved copies score above the prediction itself (z-4 0.6313 and
    y-4 0.6268 against 0.6095; Model output), plausibly because a recto-surface band moved inward sits on brighter
    papyrus (Interpretation). So this check catches a prediction that is off the sheets, not one that is a few
    voxels off (docs/compute/modal-specs/2026-10-09-surface-predict.md)."""
    np = _np()
    ct = np.asarray(ct)
    if ct.dtype != np.uint8:
        raise SurfacePredError(f"CT is {ct.dtype}; the contrast check reads uint8 volumes")
    m = np.asarray(pred) > 0
    if ct.shape != m.shape or m.ndim != 3:
        raise SurfacePredError(f"boxes differ in shape: {ct.shape} and {m.shape}")
    if not 0 < shift <= margin or min(m.shape) <= 2 * margin + 8:
        raise SurfacePredError(f"box {m.shape} is too small for a {margin} voxel margin and a {shift} voxel shift")
    core = tuple(slice(margin, n - margin) for n in m.shape)
    c, inside = ct[core], ct[core] > 0

    def auc(mask):
        return _auc_u8(c[mask & inside], c[~mask & inside])

    res = {"shape": list(m.shape), "inside_fraction": round(float(inside.mean()), 4),
           "predicted_fraction": round(float(m[core][inside].mean()), 4) if inside.any() else None,
           "auc": auc(m[core]), "shift_vox": shift}
    h = m.shape[0] // 2
    lower = ct[:h] > 0
    res["other_slab_z"] = _auc_u8(ct[:h][m[h:2 * h] & lower], ct[:h][~m[h:2 * h] & lower])
    moved = {}
    for axis, name in enumerate("zyx"):
        for sign in (1, -1):
            sl = list(core)
            sl[axis] = slice(margin - sign * shift, m.shape[axis] - margin - sign * shift)
            moved[f"{name}{sign * shift:+d}"] = auc(m[tuple(sl)])
    res["moved_reported_only"] = moved
    if res["auc"] is None or res["other_slab_z"] is None:
        res["verdict"] = {"verdict": "FAIL", "why": "no predicted or no unpredicted voxel inside the scroll"}
        return res
    res["margin"] = round(res["auc"] - res["other_slab_z"], 4)
    ok = res["auc"] >= rule["contrast_min"] and res["margin"] >= rule["contrast_margin"]
    res["verdict"] = {"verdict": "PASS" if ok else "FAIL",
                      "why": f"AUC {res['auc']} (bar {rule['contrast_min']}), {res['margin']} over the other slab's "
                             f"prediction (bar {rule['contrast_margin']})"}
    return res


# ---------------------------------------------------------------- normal grids

GRID_MAGIC, GRID_VERSION = 0x56434753, 3


def read_grid(source):
    """A GridStore file (core/src/GridStore.cpp, format v3, big-endian) as (header, [polylines (N, 2) of (u, v)]).
    u, v are (x, y) for xy slices, (x, z) for xz and (y, z) for yz. An empty file is an empty slice."""
    np = _np()
    raw = source if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    if not raw:
        return None, []
    if len(raw) < 52:
        raise SurfacePredError("grid file shorter than its header")
    h = struct.unpack(">13I", raw[:52])
    magic, ver, bx, by, bw, bh, cell, nb, npaths, bio, po, jo, js = h
    if magic != GRID_MAGIC:
        raise SurfacePredError(f"not a GridStore file (magic {magic:#x})")
    if ver > GRID_VERSION:
        raise SurfacePredError(f"GridStore version {ver} is newer than {GRID_VERSION}")
    lines, cur = [], po
    while cur < jo:
        sx, sy, n = struct.unpack(">iiI", raw[cur:cur + 12])
        cur += 12
        off = np.frombuffer(raw[cur:cur + n], dtype=np.int8).reshape(-1, 2).astype(np.int64)
        cur += n
        start = np.array([[sx, sy]], dtype=np.int64)
        lines.append(np.vstack([start, np.cumsum(off, axis=0) + start]) if len(off) else start)
    meta = json.loads(raw[jo:jo + js]) if js else {}
    return {"version": ver, "bounds": [bx, by, bw, bh], "cell": cell, "buckets": nb, "paths": npaths,
            "meta": meta}, lines


def write_grid(path, lines, bounds, cell=64, meta=None):
    """Write polylines as a GridStore v3 file the way GridStore::save lays it out (used to build test inputs)."""
    np = _np()
    bx, by, bw, bh = (int(v) for v in bounds)
    gw, gh = -(-bw // cell), -(-bh // cell)
    grid = [[] for _ in range(gw * gh)]
    paths, offsets = b"", []
    for handle, line in enumerate(lines):
        p = np.asarray(line, dtype=np.int64).reshape(-1, 2)
        if len(p) < 2:
            continue
        d = np.diff(p, axis=0)
        if np.abs(d).max() > 127:
            raise SurfacePredError("a polyline step does not fit in int8")
        offsets.append(len(paths))
        paths += struct.pack(">iiI", int(p[0, 0]), int(p[0, 1]), d.size) + d.astype(np.int8).tobytes()
        cells = {int((q[1] - by) // cell) * gw + int((q[0] - bx) // cell) for q in p
                 if 0 <= (q[0] - bx) // cell < gw and 0 <= (q[1] - by) // cell < gh}
        for c in sorted(cells):
            grid[c].append(len(offsets) - 1)
    idx, flat = [0], []
    for bucket in grid:
        flat += [offsets[h] for h in bucket]
        idx.append(len(flat))
    meta_b = json.dumps(meta or {}).encode()
    bio = 52
    bpo = bio + 4 * len(idx)
    po = bpo + 4 * len(flat)
    jo = po + len(paths)
    head = struct.pack(">13I", GRID_MAGIC, GRID_VERSION, bx, by, bw, bh, cell, len(grid), len(offsets), bio, po, jo,
                       len(meta_b))
    body = struct.pack(f">{len(idx)}I", *idx) + struct.pack(f">{len(flat)}I", *flat) + paths + meta_b
    Path(path).write_bytes(head + body)


def _segments(lines, shift, window, pad):
    np = _np()
    u0, u1, v0, v1 = window
    out = []
    for p in lines:
        if len(p) < 2:
            continue
        p = p + np.asarray(shift)
        a, b = p[:-1], p[1:]
        keep = ((np.maximum(a[:, 0], b[:, 0]) >= u0 - pad) & (np.minimum(a[:, 0], b[:, 0]) < u1 + pad) &
                (np.maximum(a[:, 1], b[:, 1]) >= v0 - pad) & (np.minimum(a[:, 1], b[:, 1]) < v1 + pad))
        out.append(np.hstack([a[keep], b[keep]]))
    return np.vstack(out).astype(float) if out else np.zeros((0, 4))


def _points(lines, shift, window):
    np = _np()
    u0, u1, v0, v1 = window
    if not lines:
        return np.zeros((0, 2))
    p = np.vstack(lines).astype(float) + np.asarray(shift, dtype=float)
    return p[(p[:, 0] >= u0) & (p[:, 0] < u1) & (p[:, 1] >= v0) & (p[:, 1] < v1)]


def _seg_dist(pts, segs):
    np = _np()
    if not len(pts) or not len(segs):
        return np.full(len(pts), np.inf)
    a, b = segs[:, :2], segs[:, 2:]
    ab = b - a
    ll = (ab ** 2).sum(1)
    ll[ll == 0] = 1e-9
    out = np.empty(len(pts))
    for i in range(0, len(pts), 256):
        q = pts[i:i + 256, None, :]
        t = np.clip(((q - a) * ab).sum(-1) / ll, 0, 1)
        out[i:i + 256] = np.sqrt(((a + t[..., None] * ab - q) ** 2).sum(-1)).min(1)
    return out


def grid_agreement(lines_a, lines_b, window, shift=(0, 0), pad=8):
    """Points of each polyline set inside window (u0, u1, v0, v1) and their distance to the other set's segments
    (within the window plus pad): shares within 1 and 2 px both ways. `shift` moves set b (a control)."""
    np = _np()
    pa, pb = _points(lines_a, (0, 0), window), _points(lines_b, shift, window)
    sa, sb = _segments(lines_a, (0, 0), window, pad), _segments(lines_b, shift, window, pad)
    da, db = _seg_dist(pa, sb), _seg_dist(pb, sa)

    def share(d, t):
        return round(float((d <= t).mean()), 4) if len(d) else None

    return {"points_a": len(pa), "points_b": len(pb), "a_within_1px": share(da, 1), "a_within_2px": share(da, 2),
            "b_within_1px": share(db, 1), "b_within_2px": share(db, 2),
            "a_median_px": round(float(np.median(da)), 3) if len(da) and np.isfinite(da).any() else None}


def grid_slices(box, margin=GRID_MARGIN):
    """The fixed comparison slices for a box: xy slices z0+192, +292, +392, +492 and xz slices y0+252, y0+302 (the
    ones the survey measured for test A), with the window the box less `margin` px. Windows are (u0, u1, v0, v1)
    in the slice's own axes."""
    (z0, z1), (y0, y1), (x0, x1) = box
    xy = [z for z in (z0 + 192 + 100 * k for k in range(4)) if z < z1 - margin]
    xz = [y for y in (y0 + 252, y0 + 302) if y < y1 - margin]
    return {"xy": {"slices": xy, "window": [x0 + margin, x1 - margin, y0 + margin, y1 - margin]},
            "xz": {"slices": xz, "window": [x0 + margin, x1 - margin, z0 + margin, z1 - margin]}}


def _other_slice(s, lo, hi, away=100):
    return s + away if s + away < hi else s - away


def _pair(r):
    return [r["a_within_1px"], r["b_within_1px"]]


def _grid_controls(a, load, direction, s, other, window, shifts):
    """Agreement of polylines a with the published slice `other` and with the published slice s moved by each of
    `shifts` px along u and along v, the direction that agrees less counting (a shift along the sheets barely moves
    them: on the published PHerc0841 grids, 3 px along v kept 58 to 71 percent of points within 1 px, 3 px along u
    under 1 percent)."""
    pub = load("published", direction, s)
    controls = {f"slice_{other}": _pair(grid_agreement(a, load("published", direction, other), window))}
    detail = {}
    for d in shifts:
        along_u = _pair(grid_agreement(a, pub, window, shift=(d, 0)))
        along_v = _pair(grid_agreement(a, pub, window, shift=(0, d)))
        detail[f"shift_{d}_u"], detail[f"shift_{d}_v"] = along_u, along_v
        mean = [sum(x for x in v if x is not None) for v in (along_u, along_v)]
        controls[f"shift_{d}"] = along_u if mean[0] <= mean[1] else along_v
    return controls, detail


def _highest(controls):
    return max([x for v in controls.values() for x in v if x is not None] or [0.0])


def compare_grids(load, box, rule=RULE, shifts=(3, 6)):
    """Our grids against the published ones on grid_slices(box). load(which, direction, slice) returns the
    polylines of "ours" or "published". Each slice is compared both ways. Controls (_grid_controls): the published
    slice 100 voxels away and the published slice moved 3 and 6 px, against ours ("controls") and against the
    published slice itself ("published_self_controls", which say whether the slice can tell a shift apart).
    VOID when a self-control reaches rule["grid_control_max"]; PASS when every slice has at least
    rule["grid_min"] of its points within 1 px both ways and every control stays under rule["grid_control_max"];
    FAIL otherwise, and FAIL when no fixed slice fits inside the box."""
    plan = grid_slices(box)
    rows, worst, worst_control, worst_self = [], 1.0, 0.0, 0.0
    for direction, spec in plan.items():
        window = spec["window"]
        lo, hi = (box[0] if direction == "xy" else box[1])
        for s in spec["slices"]:
            ours, pub = load("ours", direction, s), load("published", direction, s)
            row = {"direction": direction, "slice": s, "window": window, **grid_agreement(ours, pub, window)}
            other = _other_slice(s, lo + GRID_MARGIN, hi - GRID_MARGIN)
            row["controls"], row["shift_detail"] = _grid_controls(ours, load, direction, s, other, window, shifts)
            row["published_self_controls"], _ = _grid_controls(pub, load, direction, s, other, window, shifts)
            vals = [row["a_within_1px"], row["b_within_1px"]]
            if any(v is None for v in vals):
                worst = 0.0
                row["note"] = "a slice with no polylines in the window"
            else:
                worst = min(worst, *vals)
            worst_control = max(worst_control, _highest(row["controls"]))
            worst_self = max(worst_self, _highest(row["published_self_controls"]))
            rows.append(row)
    bar = rule["grid_control_max"]
    if not rows:   # no fixed slice fits inside the box: nothing was compared, which must not read as agreement
        verdict = {"verdict": "FAIL", "why": f"no fixed slice lies inside box {format_bbox(box)} less "
                                             f"{GRID_MARGIN} px; nothing was compared"}
        worst = None
    elif worst_self >= bar:
        verdict = {"verdict": "VOID", "why": f"the published grids against themselves moved reach {worst_self} "
                                             f"(bar {bar})"}
    elif worst >= rule["grid_min"] and worst_control < bar:
        verdict = {"verdict": "PASS", "why": f"every slice >= {rule['grid_min']} within 1 px both ways (lowest "
                                             f"{worst}); controls at most {worst_control}"}
    else:
        verdict = {"verdict": "FAIL", "why": f"lowest share within 1 px {worst} (bar {rule['grid_min']}); highest "
                                             f"control {worst_control} (bar {bar})"}
    return {"slices": rows, "lowest": worst, "highest_control": worst_control, "highest_self_control": worst_self,
            "verdict": verdict}


def grid_loader(ours_dir, published, cache=None):
    """load(which, direction, slice) for compare_grids: ours from a local .normal-grids folder, published from a
    local folder or a URL (fetched with kit/autopipe.py download(), S3's false 404s retried, into `cache`)."""
    def load(which, direction, s):
        rel = f"{direction}/{int(s):06d}.grid"
        base = str(ours_dir if which == "ours" else published).rstrip("/")
        if "://" not in base:
            p = Path(base, rel)
            if not p.is_file():
                raise SurfacePredError(f"{p}: missing")
            return read_grid(p)[1]
        from . import autopipe
        dest = Path(cache or kithome.path("work", "vc3d", "predictions", "grid-cache"), rel)
        if not dest.is_file():
            if not autopipe.download(f"{base}/{rel}", dest, optional=True):
                raise SurfacePredError(f"{base}/{rel}: not published")
        return read_grid(dest)[1]
    return load


# ---------------------------------------------------------------- seating

def read_surface(tifxyz):
    """(points (H, W, 3) as x, y, z voxels, valid mask) of a tifxyz folder (x.tif, y.tif, z.tif)."""
    np = _np()
    p = Path(tifxyz)
    try:   # tifffile reads every predictor; kit's own reader lacks the floating-point one (3)
        import tifffile
        xyz = np.stack([np.asarray(tifffile.imread(str(p / f"{a}.tif")), dtype=np.float64) for a in "xyz"], -1)
    except ImportError:
        from . import vc3d_io
        ras = vc3d_io.read_tiff(p / "x.tif")
        xyz = np.stack([np.asarray(vc3d_io.read_tiff(p / f"{a}.tif").floats(), dtype=np.float64)
                        .reshape(ras.h, ras.w) for a in "xyz"], -1)
    valid = np.isfinite(xyz).all(-1) & ~(xyz == -1).all(-1) & (xyz[..., 2] > 0)
    return xyz, valid


def surface_normals(xyz, valid):
    """Unit normals from central differences of the grid; (points (N, 3), normals (N, 3)) where all four
    neighbours are valid."""
    np = _np()
    du = xyz[1:-1, 2:] - xyz[1:-1, :-2]
    dv = xyz[2:, 1:-1] - xyz[:-2, 1:-1]
    ok = valid[1:-1, 1:-1] & valid[1:-1, 2:] & valid[1:-1, :-2] & valid[2:, 1:-1] & valid[:-2, 1:-1]
    n = np.cross(du, dv)
    norm = np.linalg.norm(n, axis=-1)
    ok &= norm > 1e-9
    return xyz[1:-1, 1:-1][ok], n[ok] / norm[ok][:, None]


def _lookup(mask, origin_zyx, pts_xyz):
    np = _np()
    zyx = np.rint(pts_xyz[:, ::-1] - np.asarray(origin_zyx)).astype(np.int64)
    inside = np.all((zyx >= 0) & (zyx < np.array(mask.shape)), axis=1)
    out = np.zeros(len(pts_xyz), dtype=bool)
    out[inside] = mask[tuple(zyx[inside].T)]
    return out, inside


def sheet_spacing(pred, origin_zyx, pts, normals, reach=60, step=0.5, min_gap=2.0, sample=4000, seed=0):
    """Median distance along the normals from the sheet a vertex sits on to the next surface either side, in
    voxels: fg runs of the prediction sampled every `step` voxels out to `reach`, runs closer than `min_gap`
    merged. None when no vertex sees a neighbour."""
    np = _np()
    if not len(pts):
        return None, 0
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(pts), size=min(sample, len(pts)), replace=False)
    t = np.arange(-reach, reach + step / 2, step)
    found = []
    for i in pick:
        line = pts[i][None, :] + t[:, None] * normals[i][None, :]
        on, inside = _lookup(pred, origin_zyx, line)
        if not inside.all():
            continue
        runs, start = [], None
        for k, v in enumerate(on):
            if v and start is None:
                start = k
            if not v and start is not None:
                runs.append([t[start], t[k - 1]])
                start = None
        if start is not None:
            runs.append([t[start], t[-1]])
        merged = []
        for r in runs:
            if merged and r[0] - merged[-1][1] < min_gap:
                merged[-1][1] = r[1]
            else:
                merged.append(r)
        centres = [(a + b) / 2 for a, b in merged]
        if len(centres) < 2:
            continue
        here = int(np.argmin(np.abs(centres)))
        if abs(centres[here]) > TOLERANCE + 1:
            continue
        gaps = [abs(centres[j] - centres[here]) for j in (here - 1, here + 1) if 0 <= j < len(centres)]
        found.append(min(gaps))
    return (round(float(np.median(found)), 2) if found else None), len(found)


def seating(pred, origin_zyx, pts, normals, spacing=None, tol=TOLERANCE, rule=RULE):
    """Share of a published segment's vertices within `tol` voxels of the prediction (pred: the box as uint8 or
    bool, origin its corner in level voxels; pts, normals (N, 3) as x, y, z), against the same vertices moved half
    a sheet spacing along their normals both ways (the control). The spacing is measured from the prediction
    unless given. PASS when the seated share reaches rule["seat_min"] and both displaced shares stay at or under
    rule["seat_control_max"]; VOID when the spacing cannot be measured; FAIL otherwise."""
    np = _np()
    mask = np.asarray(pred) > 0
    if spacing is None:
        spacing, n_spacing = sheet_spacing(mask, origin_zyx, pts, normals)
    else:
        n_spacing = None
    near = _dilate(mask, tol)
    res = {"vertices": int(len(pts)), "sheet_spacing_vox": spacing, "spacing_samples": n_spacing,
           "tolerance_vox": tol}
    seated, inside = _lookup(near, origin_zyx, pts)
    res["vertices_in_box"] = int(inside.sum())
    res["seated"] = round(float(seated[inside].mean()), 4) if inside.any() else None
    if spacing is None:
        res["verdict"] = {"verdict": "VOID", "why": "no sheet spacing could be measured along the normals"}
        return res
    half = spacing / 2.0
    for sign, name in ((1, "displaced_plus"), (-1, "displaced_minus")):
        moved, inside_m = _lookup(near, origin_zyx, pts + sign * half * normals)
        both = inside & inside_m
        res[name] = round(float(moved[both].mean()), 4) if both.any() else None
    ctl = [v for v in (res["displaced_plus"], res["displaced_minus"]) if v is not None]
    if res["seated"] is None or not ctl:
        res["verdict"] = {"verdict": "VOID", "why": "no vertex inside the box"}
    elif res["seated"] >= rule["seat_min"] and max(ctl) <= rule["seat_control_max"]:
        res["verdict"] = {"verdict": "PASS", "why": f"seated {res['seated']} >= {rule['seat_min']}, displaced "
                                                    f"at most {max(ctl)}"}
    else:
        res["verdict"] = {"verdict": "FAIL", "why": f"seated {res['seated']} (bar {rule['seat_min']}), displaced "
                                                    f"{ctl} (bar {rule['seat_control_max']})"}
    return res


def surface_in_box(tifxyz, box, scale=1.0, margin=TOLERANCE + 1):
    """Vertices and normals of a tifxyz inside a box (level voxels; `scale` maps the surface's coordinates to the
    level, 0.25 for a level 2 prediction under a level 0 mesh)."""
    np = _np()
    xyz, valid = read_surface(tifxyz)
    pts, normals = surface_normals(xyz * float(scale), valid)
    lo = np.array([box[2][0], box[1][0], box[0][0]], dtype=float) + margin
    hi = np.array([box[2][1], box[1][1], box[0][1]], dtype=float) - margin
    keep = np.all((pts >= lo) & (pts < hi), axis=1)
    return pts[keep], normals[keep]


# ---------------------------------------------------------------- command line

# ---------------------------------------------------------------- off the Modal volume

MODAL_VOLUME = "surface-predict"           # scripts/vc3d/modal_surface.py's volume
MODAL_RUNS = "runs"                        # one folder per arm, with receipt.json, the package and its grids


def modal_get(volume, remote, local, run=None):
    """`modal volume get VOLUME REMOTE LOCAL`: copies a file or folder off a Modal volume. run(argv) -> exit code,
    for tests; by default the modal CLI, which needs KIT_ALLOW_MODAL=1 (AGENTS.md rule 10: Claude's cloud
    sessions cannot reach Modal, so this runs on the owner's computer or in an agent that runs Modal)."""
    argv = ["modal", "volume", "get", "--force", volume, remote, str(local)]
    if run is None:
        if os.environ.get("KIT_ALLOW_MODAL") != "1":
            raise SurfacePredError("fetching off a Modal volume needs KIT_ALLOW_MODAL=1, set by the owner on a "
                                   "machine that runs Modal (AGENTS.md rule 10)")
        import subprocess
        rc = subprocess.run(argv).returncode
    else:
        rc = run(argv)
    if rc != 0:
        raise SurfacePredError(f"{' '.join(argv)} exited {rc}")
    return argv


def _landed(stage, name):
    """The folder `modal volume get` wrote, by name: at stage/name, or one level down (the CLI keeps the remote
    folder's name under the destination)."""
    hits = [p for p in [Path(stage) / name] + sorted(Path(stage).glob(f"*/{name}")) if p.is_dir()]
    if not hits:
        raise SurfacePredError(f"modal volume get wrote no folder named {name} under {stage}")
    return hits[0]


def fetch(arm, out, volume=MODAL_VOLUME, run=None, allow_fail=False, grids=True):
    """Copy one arm's packaged prediction and its normal grids off the Modal volume into out/ and check them: the
    hand step "modal volume get surface-predict runs/testD/..." of docs/surfacepred.md. Reads the arm's
    receipt.json first and refuses an arm whose verdict is not PASS (allow_fail fetches it anyway, for a look, and
    says so), or one with no package; then fetches the package and the .normal-grids folder beside it, runs
    check_package, and returns the external_prediction setting a plan takes. Nothing is overwritten: out must be
    new or empty."""
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise SurfacePredError(f"{out} is not empty; fetch into a new folder")
    out.mkdir(parents=True, exist_ok=True)
    base = f"{MODAL_RUNS}/{arm}"
    stage = out / ".fetch"
    stage.mkdir()
    try:
        modal_get(volume, f"{base}/receipt.json", stage / "receipt.json", run)
        found = sorted(stage.rglob("receipt.json"))
        if not found:
            raise SurfacePredError(f"no receipt.json for arm {arm} on volume {volume}")
        receipt = json.loads(found[0].read_text())
        shutil.move(str(found[0]), out / "receipt.json")
        verdict = receipt.get("verdict")
        if verdict != "PASS" and not allow_fail:
            raise SurfacePredError(f"arm {arm}: receipt verdict {verdict} ({receipt.get('why')}); a prediction that "
                                   "did not pass its checks is not traced on (pass allow_fail to fetch it for a look)")
        pkg = (receipt.get("package") or {}).get("path")
        if not pkg or not pkg.endswith(".zarr"):
            raise SurfacePredError(f"arm {arm}: the receipt names no packaged .zarr")
        name = Path(pkg).name
        modal_get(volume, f"{base}/{name}", stage, run)
        shutil.move(str(_landed(stage, name)), out / name)
        res = {"arm": arm, "volume": volume, "verdict": verdict, "receipt": str(out / "receipt.json"),
               "zarr": str(out / name), "normal_grids": None, "problems": check_package(out / name)}
        if grids:
            gname = name[:-len(".zarr")] + ".normal-grids"
            modal_get(volume, f"{base}/{gname}", stage, run)
            shutil.move(str(_landed(stage, gname)), out / gname)
            res["normal_grids"] = str(out / gname)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    if verdict != "PASS":
        res["warning"] = f"fetched with receipt verdict {verdict}: not for tracing"
    res["external_prediction"] = {"zarr": res["zarr"], "normal_grids": res["normal_grids"]}
    return res


def build_parser(p):
    sub = p.add_subparsers(dest="sp_cmd", required=True)
    q = sub.add_parser("level", help="the pyramid level m7 reads for a voxel size, or a refusal")
    q.add_argument("voxel_um", type=float)
    q = sub.add_parser("plan", help="patches and chunks of a vesuvius.predict --bbox run")
    q.add_argument("--shape", type=int, nargs=3, required=True, metavar=("Z", "Y", "X"))
    q.add_argument("--bbox", required=True, help="z0:z1,y0:y1,x0:x1 in the level's voxels")
    q.add_argument("--overlap", type=float, default=OVERLAP)
    q = sub.add_parser("shapes", help="ceil-shaped pyramid levels (VC3D's rule) beside villa's round rule")
    q.add_argument("--shape", type=int, nargs=3, required=True, metavar=("Z", "Y", "X"))
    q = sub.add_parser("package", help="final.zarr to the catalog layout (levels, meta.json, run.json)")
    q.add_argument("final")
    q.add_argument("out")
    q.add_argument("--voxel-um", type=float, required=True, help="voxel size of the prediction's level 0")
    q.add_argument("--record", help="JSON file written as run.json")
    q.add_argument("--workers", type=int, default=2)
    q = sub.add_parser("check", help="would VC3D open this packaged prediction")
    q.add_argument("out")
    q.add_argument("--vc3d", action="store_true", help="also open it with vc_gen_normalgrids --print-plan")
    q = sub.add_parser("dice", help="our prediction against a published one over a box, with controls")
    q.add_argument("ours", help="local folder or URL of an OME-Zarr prediction")
    q.add_argument("published", help="local folder or URL")
    q.add_argument("--bbox", required=True)
    q = sub.add_parser("grids", help="our normal grids against published ones on the fixed slices of a box")
    q.add_argument("ours", help="local .normal-grids folder")
    q.add_argument("published", help="local folder or URL of the published .normal-grids")
    q.add_argument("--bbox", required=True)
    q.add_argument("--cache", help="where published grid files are kept (default work/vc3d/predictions/grid-cache "
                   "in the kit home)")
    q = sub.add_parser("contrast", help="is a prediction on the scan's sheets: CT contrast against moved copies")
    q.add_argument("scan", help="local folder or URL of the CT OME-Zarr")
    q.add_argument("prediction", help="local folder or URL of an OME-Zarr prediction")
    q.add_argument("--bbox", required=True, help="in the prediction's voxels")
    q.add_argument("--level", type=int, default=0, help="the scan's level the prediction was made on")
    q = sub.add_parser("seat", help="is a segment on a prediction, against the segment moved half a sheet")
    q.add_argument("prediction", help="local folder or URL of an OME-Zarr prediction")
    q.add_argument("surface", help="tifxyz folder in the scan's frame")
    q.add_argument("--bbox", required=True)
    q.add_argument("--scale", type=float, default=1.0, help="surface coordinates to prediction voxels")
    q = sub.add_parser("box", help="the chunk-aligned box around a segment's vertices")
    q.add_argument("surface", help="tifxyz folder")
    q.add_argument("--shape", type=int, nargs=3, required=True, metavar=("Z", "Y", "X"))
    q.add_argument("--chunks", type=int, default=3, help="chunks per axis (default 3: a 576 voxel cube)")
    q.add_argument("--scale", type=float, default=1.0)
    q.add_argument("--at", choices=("centre", "densest"), default="centre",
                   help="around the vertex at the grid's middle (default) or where most vertices are")
    q = sub.add_parser("fetch", help="copy an arm's package and grids off the Modal volume and check them "
                                     "(needs KIT_ALLOW_MODAL=1)")
    q.add_argument("arm", help="the arm's folder under runs/ on the volume, e.g. testD")
    q.add_argument("out", help="new or empty local folder, e.g. work/surfacepred/testD")
    q.add_argument("--volume", default=MODAL_VOLUME)
    q.add_argument("--allow-fail", action="store_true", help="fetch an arm whose receipt is not PASS, for a look")
    q.add_argument("--no-grids", action="store_true", help="the package only")


def cmd_surfacepred(args):
    c = args.sp_cmd
    if c == "level":
        level, eff = choose_level(args.voxel_um)
        res = {"voxel_um": args.voxel_um, "level": level, "effective_um": eff}
    elif c == "plan":
        res = plan_box(args.shape, parse_bbox(args.bbox), overlap=args.overlap)
    elif c == "shapes":
        res = {"ceil": pyramid_shapes(args.shape), "villa_round": round_shapes(args.shape)}
    elif c == "package":
        rec = json.loads(Path(args.record).read_text()) if args.record else None
        res = package(args.final, args.out, args.voxel_um, record=rec, workers=args.workers)
        res["problems"] = check_package(args.out)
    elif c == "check":
        res = {"problems": check_package(args.out)}
        if args.vc3d:
            ok, text = vc3d_open(args.out)
            res["vc3d_open"] = ok
            res["vc3d_output"] = text
    elif c == "fetch":
        try:
            res = fetch(args.arm, args.out, args.volume, allow_fail=args.allow_fail, grids=not args.no_grids)
        except SurfacePredError as exc:
            print(json.dumps({"error": str(exc)}, indent=1))
            return 2
    elif c == "dice":
        box = parse_bbox(args.bbox)
        ours, _ = read_box(args.ours, box)
        pub, info = read_box(args.published, box)
        res = compare_box(ours, pub)
        res["published_read"] = info
    elif c == "grids":
        res = compare_grids(grid_loader(args.ours, args.published, args.cache), parse_bbox(args.bbox))
    elif c == "contrast":
        box = parse_bbox(args.bbox)
        ct, info = read_box(args.scan, box, level=args.level)
        pred, _ = read_box(args.prediction, box)
        res = ct_contrast(ct, pred)
        res["scan_read"] = info
    elif c == "seat":
        box = parse_bbox(args.bbox)
        pred, _ = read_box(args.prediction, box)
        pts, normals = surface_in_box(args.surface, box, args.scale)
        res = seating(pred, [b[0] for b in box], pts, normals)
    else:
        np = _np()
        xyz, valid = read_surface(args.surface)
        if args.at == "densest":
            box, n = box_from_points(xyz[valid] * args.scale, args.shape, args.chunks)
            res = {"bbox": format_bbox(box), "box": box, "vertices_inside": n}
        else:
            box, centre = box_at_centre(xyz, valid, args.shape, args.chunks, scale=args.scale)
            p = xyz[valid] * args.scale
            lo = [b[0] for b in box][::-1]
            hi = [b[1] for b in box][::-1]
            res = {"bbox": format_bbox(box), "box": box, "centre_vertex_xyz": centre,
                   "vertices_inside": int(np.all((p >= lo) & (p < hi), axis=1).sum())}
        res["vertices"] = int(valid.sum())
    print(json.dumps(res, indent=1, default=str))
    verdict = (res.get("verdict") or {}).get("verdict") if isinstance(res.get("verdict"), dict) else None
    if c in ("check", "fetch"):
        return 1 if res["problems"] or res.get("vc3d_open") is False else 0
    return 1 if verdict in ("FAIL", "VOID") else 0
