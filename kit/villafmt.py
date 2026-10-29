"""Community format adapters for villa and VC3D: `python3 -m kit.villafmt`.

Our tools write tifxyz surfaces, ink maps, seeds and ink labels into their own run folders. A community member
works in VC3D and villa's ink trainer, which find those things by fixed file names and JSON shapes. This module
checks our outputs against the rules villa's own readers apply, and writes the small files that hand them over:

  tifxyz DIR ...           check tifxyz folders as VC3D's loader reads them (meta.json fields, the three bands,
                           sample count and size; with numpy, NaN, partial -1 sentinels, z <= 0 vertices that VC3D
                           drops, and a stale bbox)
  project OUT.volpkg.json  write a VC3D project file (volumes, segments, normal grids, umbilicus, output folder),
                           every location checked as VC3D checks it and no two segments sharing the id VC3D keys
                           them by; `--from-autopipe RUN` fills it from an AutoPipeline run folder; `project --check FILE` checks an existing one
  inkmap add SEGDIR MAP    register an ink map for VC3D's Ink Detection overlay by writing SEGDIR/ink-detections.json,
                           after checking that the map's aspect matches the segment's canvas within 2 % (this catches
                           most crops, turned maps and other segments' maps, not those of the same aspect;
                           `--expect-size W H` also pins the exact size); `inkmap check`
  seeds IN --to FORMAT     convert seed points between AutoPipeline seeds.json, villa's explicit_seed JSON, VC3D point
                           collections, a tifxyz meta.json seed and plain text, and print vc_grow_seg_from_seed calls;
                           a VC3D file is checked as VC3D's loadFromJSON reads it (check_points)
  preds export MAP ...     write an ink map as villa's own prediction file: uint8 0 to 255, tiled, LZW, Big TIFF,
                           named SEGDIR/preds/<seg>_<model>_<direction>_<ddmmyy>.tif, so villa's merge_predictions
                           finds it by direction and villa's folder inference counts the segment as done; refuses
                           NaN and infinite values, records the scaling, reads the file back before it is published,
                           and with --register adds it to SEGDIR/ink-detections.json through `inkmap add`
  labels find DIR          list ink label files in villa's naming and show what villa's trainer would pick
  labels export ...        copy a label pair (an inklabels.tif and a supervision.tif made on our own canvas) to villa's
                           names <seg>_inklabels.tif, <seg>_supervision_mask.tif and <seg>_validation_mask.tif;
                           villa's trainer reads only .zarr labels, so villa's create_label_zarrs must convert them
                           before training (then `labels find` shows the pick)

Each rule cites the villa reader it follows, at villa main 8aa507c12 (VILLA_PIN, read 19 Oct 2026; Sourced fact).
Tolerances we chose (Interpretation): ASPECT_TOL for an ink map's aspect, BBOX_TOL_VOX for a stored bbox.

What this does not do: it never edits a surface, an ink map or a label image (export copies bytes); it does not
convert between voxel frames or pyramid levels (seeds, segments and volumes must already share one frame); it has not
been run against a live VC3D window here (the rules are read from the source, the GUI handoff is untested).

Standard library only, except that the pixel checks of `tifxyz` and `preds export` need numpy (reported as unmeasured
without it, or refused for `preds export`). Compressed or tiled TIFF pixels are read with tifffile or Pillow, and LZW
ones (villa's predictions) also without them. `preds export` encodes LZW with Pillow's libtiff when present, else with
the pure-Python encoder here; every TIFF reader decodes both to the same pixels. Exit status: 0 when every check
passes, 1 when a check fails (the JSON report lists errors and warnings, each with its villa source), 2 when an input
cannot be read or an argument is wrong.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import os
import shutil
import struct
import sys
import tempfile
from datetime import datetime
from pathlib import Path

VILLA_PIN = "8aa507c1215f1fa8758f13d0538f7af9710e02d7"   # ScrollPrize/villa main, read 19 Oct 2026
ASPECT_TOL = 0.02          # an ink map's aspect may differ from the segment canvas's by 2 % (rounding of the render)
BBOX_TOL_VOX = 1.0         # a stored bbox may differ from the valid vertices' extent by one voxel
SCHEMA = 1
NOTE = "Format check and handoff files only. An ink map is model output, not a reading."

VC3D_POINTS_VERSION = "1"  # core/src/PointCollections.cpp:9
ANON_TAG = "vc-remote-auth:anonymous"            # core/include/vc/core/types/VolumePkg.hpp:24-25
VOXEL_TAG = "vc-open-data-voxel-size-um:"        # core/src/VolumePkg.cpp:512-513
LABEL_KINDS = (("_inklabels", "inklabels"), ("_supervision_mask", "supervision_mask"),
               ("_validation_mask", "validation_mask"))      # vesuvius ink_detection/data/segment.py:12-16
LABEL_EXTS = (".tif", ".tiff", ".zarr")                     # segment.py:17
LABEL_DEPTH, LABEL_SLICE = 65, 32                           # vesuvius/label_zarr.py:19-20

SRC = {
    "seg_meta": "volume-cartographer/core/src/Segmentation.cpp:33-39 (type seg, uuid required)",
    "seg_dir": "volume-cartographer/core/src/Segmentation.cpp:111-114 (a segment is a folder with meta.json)",
    "seg_format": "volume-cartographer/core/src/Segmentation.cpp:133 (format must be tifxyz)",
    "seg_bands": "volume-cartographer/core/src/Segmentation.cpp:155-160 (x.tif, y.tif, z.tif must exist)",
    "placeholder": "volume-cartographer/core/src/Segmentation.cpp:10-11, 136-143 (a catalog placeholder carries "
                   "meta.json only; VC3D fetches the TIFFs when the segment is opened)",
    "scale": "volume-cartographer/core/src/QuadSurface.cpp:309-339; spiral-fitting/tifxyz.py:372-377",
    "band_samples": "volume-cartographer/core/src/QuadSurface.cpp:2774-2778 (one sample per pixel)",
    "band_bits": "volume-cartographer/core/src/QuadSurface.cpp:2779-2785 (8, 16, 32 or 64 bits)",
    "band_size": "volume-cartographer/core/src/QuadSurface.cpp:2803-2808 (band size mismatch)",
    "band_dtype": "volume-cartographer/core/src/QuadSurface.cpp:2301-2305; spiral-fitting/tifxyz.py:440-442 "
                  "(both writers write float32)",
    "dims": "volume-cartographer/core/src/QuadSurface.cpp:342-381 (tiff_dimensions, used only without TIFFs)",
    "sentinel": "volume-cartographer/core/src/QuadSurface.cpp:279 (a vertex is valid unless a coordinate is -1)",
    "z_drop": "volume-cartographer/core/src/QuadSurface.cpp:1077-1096 and 2923-2927 (ensureLoaded loads through "
              "load_quad_from_tifxyz, which turns vertices with z <= 0 into holes)",
    "bbox": "volume-cartographer/core/src/QuadSurface.cpp:1031-1035 and 2549-2554 (bbox read from meta.json at "
            "load; villa #1272)",
    "project_json": "volume-cartographer/core/src/VolumePkg.cpp:2236-2291 (toJson and fromJson)",
    "project_entry": "volume-cartographer/core/src/VolumePkg.cpp:466-503 (an entry is a string or {location, tags})",
    "project_path": "volume-cartographer/core/src/VolumePkg.cpp:74-81, 2029, 2059 (relative to the project file)",
    "project_ext": "volume-cartographer/apps/VC3D/MenuActionController.cpp:396-403 (*.volpkg.json)",
    "loc_validate": "volume-cartographer/core/src/VolumePkg.cpp:528-560 (validateLocation)",
    "zarr_dir": "volume-cartographer/core/src/VolumePkg.cpp:112-131 (isSingleZarrVolumeDir)",
    "remote_zarr": "volume-cartographer/core/src/VolumePkg.cpp:150-165 (remote volumes point at a .zarr root)",
    "normal_grids": "volume-cartographer/core/src/VolumePkg.cpp:139-149 (xy/, xz/, yz/ and metadata.json)",
    "umbilicus": "volume-cartographer/core/src/Umbilicus.cpp:272-370 (LoadJsonFile)",
    "ink_records": "volume-cartographer/apps/VC3D/OpenDataSegmentCache.cpp:651-694 and 2022-2063 "
                   "(SEGDIR/ink-detections.json, local_file relative to SEGDIR)",
    "ink_match": "volume-cartographer/apps/VC3D/overlays/InkDetectionOverlayController.cpp:52-65 and 502-510 "
                 "(segment_id or segment_long_id must equal the segment's key)",
    "ink_stretch": "volume-cartographer/apps/VC3D/overlays/InkDetectionOverlayController.cpp:399-437 (the image is "
                   "stretched over the whole grid, each axis on its own)",
    "seg_id": "volume-cartographer/core/src/Segmentation.cpp:42-56 (a local segment's id is its folder name)",
    "points": "volume-cartographer/core/src/PointCollections.cpp:36-119, 571-662 (point collection JSON v1)",
    "points_load": "volume-cartographer/core/src/PointCollections.cpp:603-645 (loadFromJSON: the version string "
                   "\"1\", a collections object, numeric keys; one malformed collection refuses the whole file), "
                   "147-166 (a collection needs a name and points, and a valid uuid when it has one), 58-69 (a point "
                   "needs p, three numbers; wind_a null or a number; creation_time a number), 20-22 and 172-181 "
                   "(color and anchor2d numbers); core/include/vc/core/util/Uuid.hpp:10-21 (isUuid)",
    "seg_dup": "volume-cartographer/core/src/VolumePkg.cpp:2086-2090 (a segment whose id is already loaded is "
               "skipped: \"Duplicate segment id\"); core/src/Segmentation.cpp:42-56 (the id is the folder name, or "
               "the uuid of an Open Data catalog representation)",
    "explicit_seed": "volume-cartographer/scripts/evaluation/eval_surface_tracer.py:102-131",
    "seed_cli": "volume-cartographer/apps/src/vc_grow_seg_from_seed.cpp:288-329 (--seed x y z)",
    "seed_zero": "volume-cartographer/apps/src/vc_grow_seg_from_seed.cpp:606-620 (with --seed, a 0 coordinate "
                 "falls through to random_seed)",
    "labels": "vesuvius/src/vesuvius/ink_detection/data/segment.py:12-120",
    "trainer_zarr": "vesuvius/src/vesuvius/ink_detection/data/segment.py:179-181 (the trainer discovers labels with "
                    "extension .zarr only); ink_detection/README.md:88-94 (create_label_zarrs converts label images)",
    "label_zarr": "vesuvius/src/vesuvius/label_zarr.py:12-67 (ZYX, depth 65, label at z 32, OME-NGFF 0.4)",
    "pred_encode": "vesuvius/src/vesuvius/ink_detection/inference/infer.py:791-812 (iter_probability_tiles: a "
                   "probability clipped to 0 to 1, times 255, truncated to uint8)",
    "pred_tiff": "vesuvius/src/vesuvius/ink_detection/inference/infer.py:815-834 (write_output_tiff: uint8, tiled, "
                 "LZW, Big TIFF); the tile edge is the model's patch size (979-981)",
    "pred_name": "vesuvius/src/vesuvius/ink_detection/inference/infer.py:1211-1213, 1223-1247 (folder inference "
                 "writes SEGDIR/preds/<prefix_><seg>_<checkpoint stem>_<direction>_<ddmmyy>.tif and skips a segment "
                 "and direction when <prefix_><seg>_<stem>_<direction>_*.tif exists)",
    "pred_surface": "vesuvius/src/vesuvius/ink_detection/inference/infer.py:1165-1189 (resolve_segment_zarr_path), "
                    "940-952 and 966-969 (the prediction has the level-0 surface volume's height and width)",
    "pred_direction": "vesuvius/src/vesuvius/ink_detection/preprocessing/merge_predictions.py:112-118 "
                      "(parse_prediction_direction: _forward_ or _reverse_ in the lower-case stem, forward first)",
    "pred_merge": "vesuvius/src/vesuvius/ink_detection/preprocessing/merge_predictions.py:27, 30, 93-136 (preds "
                  "folders; .png, .tif, .tiff files of one direction, merged_ outputs left out)",
    "pred_shape": "vesuvius/src/vesuvius/ink_detection/preprocessing/merge_predictions.py:330-340 "
                  "(validate_prediction_shapes: every file of a direction must have one shape)",
    "pred_finite": "vesuvius/src/vesuvius/ink_detection/preprocessing/merge_predictions.py:156-165, 215-227 "
                   "(non-finite float predictions are refused)",
    "ink_u8": "volume-cartographer/apps/VC3D/overlays/InkDetectionOverlayController.cpp:518, 123-137 (cv::imread "
              "unchanged; an 8-bit map is shown as stored, any other depth stretched from its minimum to maximum)",
}


class FormatError(ValueError):
    """An input that cannot be read at all, or a wrong argument (exit 2)."""


def _issue(rule, message, source=None):
    d = {"rule": rule, "message": message}
    if source:
        d["source"] = SRC.get(source, source)
    return d


def _report(**fields):
    rep = {"schema": SCHEMA, "tool": "kit.villafmt", "villa": VILLA_PIN, "note": NOTE, "ok": False,
           "errors": [], "warnings": []}
    rep.update(fields)
    return rep


def _finish(rep):
    rep["ok"] = not rep["errors"]
    return rep


def _file_mode():
    """The mode a plain open() would give a new file under the current umask (mkstemp's files are 0600)."""
    um = os.umask(0)
    os.umask(um)
    return 0o666 & ~um


def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, _file_mode())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _load_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FormatError(f"{path}: no such file ({what})") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormatError(f"{path}: cannot read {what}: {exc}") from None


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------- image headers (standard library)

_TIFF_TYPES = {1: ("B", 1), 3: ("H", 2), 4: ("I", 4), 16: ("Q", 8), 6: ("b", 1), 8: ("h", 2), 9: ("i", 4),
               17: ("q", 8)}
_TIFF_WANTED = {256, 257, 258, 259, 273, 277, 278, 279, 284, 317, 322, 323, 324, 325, 339}
_DTYPES = {(1, 8): "uint8", (1, 16): "uint16", (1, 32): "uint32", (1, 64): "uint64", (2, 8): "int8",
           (2, 16): "int16", (2, 32): "int32", (2, 64): "int64", (3, 32): "float32", (3, 64): "float64"}


def tiff_info(path):
    """First-page header of a classic or Big TIFF: width, height, samples, bits, sample_format, dtype, compression,
    predictor, tiled, planar, the strip table and the tile table. Reads no pixels."""
    path = Path(path)
    try:
        with open(path, "rb") as f:
            head = f.read(16)
            bo = {b"II": "<", b"MM": ">"}.get(head[:2])
            if bo is None or len(head) < 8:
                raise FormatError(f"{path}: not a TIFF file")
            magic = struct.unpack(bo + "H", head[2:4])[0]
            if magic == 42:
                big, ifd = False, struct.unpack(bo + "I", head[4:8])[0]
            elif magic == 43 and len(head) >= 16:
                big, ifd = True, struct.unpack(bo + "Q", head[8:16])[0]
            else:
                raise FormatError(f"{path}: not a TIFF file (magic {magic})")
            f.seek(ifd)
            raw_n = f.read(8 if big else 2)
            if len(raw_n) < (8 if big else 2):
                raise FormatError(f"{path}: truncated TIFF header")
            n = struct.unpack(bo + ("Q" if big else "H"), raw_n)[0]
            if n == 0 or n > 4096:
                raise FormatError(f"{path}: implausible TIFF directory of {n} entries")
            esz = 20 if big else 12
            raw = f.read(n * esz)
            if len(raw) < n * esz:
                raise FormatError(f"{path}: truncated TIFF directory")
            tags = {}
            for i in range(n):
                e = raw[i * esz:(i + 1) * esz]
                if big:
                    tag, typ, cnt = struct.unpack(bo + "HHQ", e[:12])
                    val, inline, ofmt = e[12:20], 8, "Q"
                else:
                    tag, typ, cnt = struct.unpack(bo + "HHI", e[:8])
                    val, inline, ofmt = e[8:12], 4, "I"
                if tag not in _TIFF_WANTED or typ not in _TIFF_TYPES:
                    continue
                fmt, size = _TIFF_TYPES[typ]
                if cnt * size <= inline:
                    data = val[:cnt * size]
                else:
                    off = struct.unpack(bo + ofmt, val[:inline])[0]
                    pos = f.tell()
                    f.seek(off)
                    data = f.read(cnt * size)
                    f.seek(pos)
                    if len(data) < cnt * size:
                        raise FormatError(f"{path}: truncated TIFF tag {tag}")
                tags[tag] = list(struct.unpack(bo + fmt * cnt, data))
    except OSError as exc:
        raise FormatError(f"{path}: cannot read: {exc}") from None
    if 256 not in tags or 257 not in tags:
        raise FormatError(f"{path}: TIFF has no width or height")
    bits = tags.get(258, [1])[0]
    fmt = tags.get(339, [1])[0]
    return {"width": int(tags[256][0]), "height": int(tags[257][0]), "samples": int(tags.get(277, [1])[0]),
            "bits": int(bits), "sample_format": int(fmt), "dtype": _DTYPES.get((fmt, bits)),
            "compression": int(tags.get(259, [1])[0]), "tiled": 322 in tags,
            "planar": int(tags.get(284, [1])[0]), "strip_offsets": tags.get(273), "strip_counts": tags.get(279),
            "rows_per_strip": int(tags[278][0]) if 278 in tags else None, "predictor": int(tags.get(317, [1])[0]),
            "tile_width": int(tags[322][0]) if 322 in tags else None,
            "tile_length": int(tags[323][0]) if 323 in tags else None,
            "tile_offsets": tags.get(324), "tile_counts": tags.get(325), "byteorder": bo, "bigtiff": big}


def image_size(path):
    """(width, height, kind) of a TIFF, PNG or JPEG from its header (the formats VC3D's overlay reads with
    cv::imread)."""
    path = Path(path)
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:2] in (b"II", b"MM"):
                info = tiff_info(path)
                return info["width"], info["height"], "tiff"
            if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h), "png"
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    b = f.read(1)
                    while b and b != b"\xff":
                        b = f.read(1)
                    while b == b"\xff":
                        b = f.read(1)
                    if not b:
                        break
                    marker = b[0]
                    seglen = f.read(2)
                    if len(seglen) < 2:
                        break
                    length = struct.unpack(">H", seglen)[0]
                    if marker in range(0xC0, 0xD0) and marker not in (0xC4, 0xC8, 0xCC):
                        sof = f.read(5)
                        h, w = struct.unpack(">HH", sof[1:5])
                        return int(w), int(h), "jpeg"
                    f.seek(length - 2, 1)
    except OSError as exc:
        raise FormatError(f"{path}: cannot read: {exc}") from None
    raise FormatError(f"{path}: not a TIFF, PNG or JPEG image")


class _PillowUnbounded:
    """Lift Pillow's decompression-bomb limit (about 179 megapixels) while reading a local map or a file just
    written here; a whole segment's ink map can be larger."""

    def __enter__(self):
        try:
            from PIL import Image
        except ImportError:
            self.image = None
            return self
        self.image, self.limit = Image, Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = None
        return self

    def __exit__(self, *exc):
        if self.image is not None:
            self.image.MAX_IMAGE_PIXELS = self.limit
        return False


def read_tiff_pixels(path):
    """A 2D numpy array of a one-sample TIFF: uncompressed strips are read here; anything else through tifffile,
    then Pillow, and an LZW TIFF without either (or with a tifffile that has no imagecodecs) through
    read_lzw_pixels."""
    import numpy as np
    info = tiff_info(path)
    if (info["compression"] == 1 and not info["tiled"] and info["samples"] == 1 and info["dtype"]
            and info["strip_offsets"] and info["strip_counts"]):
        dt = np.dtype(info["dtype"]).newbyteorder(info["byteorder"])
        need = info["width"] * info["height"] * dt.itemsize
        chunks = []
        with open(path, "rb") as f:
            for off, cnt in zip(info["strip_offsets"], info["strip_counts"]):
                f.seek(off)
                chunks.append(f.read(cnt))
        buf = b"".join(chunks)
        if len(buf) < need:
            raise FormatError(f"{path}: strips hold {len(buf)} bytes, {need} needed")
        return np.frombuffer(buf[:need], dtype=dt).reshape(info["height"], info["width"]).astype(dt.newbyteorder("="))
    try:
        import tifffile
    except ImportError:
        tifffile = None
    if tifffile is not None:
        try:
            return np.asarray(tifffile.imread(str(path)))
        except ValueError as exc:
            # tifffile decodes LZW only with imagecodecs installed ("requires the 'imagecodecs' package"); villa's
            # own prediction files are LZW, so fall through to Pillow and kit's own LZW reader
            if info["compression"] != 5 or "imagecodecs" not in str(exc):
                raise
    try:
        from PIL import Image
        with _PillowUnbounded(), Image.open(path) as im:
            return np.asarray(im)
    except ImportError:
        if info["compression"] == 5:
            return read_lzw_pixels(path, info)
        raise FormatError(f"{path}: compressed or tiled TIFF; install tifffile to read its pixels") from None
    except Exception as exc:  # Pillow raises several types for TIFF variants it lacks
        raise FormatError(f"{path}: cannot decode: {exc}") from None


# ---------------------------------------------------------------- tifxyz

def _have_numpy():
    try:
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def check_tifxyz(path, pixels=True):
    """Check one tifxyz folder against VC3D's loader; returns the report (ok, errors, warnings, grid, ...)."""
    path = Path(path)
    rep = _report(path=str(path), grid=None, scale=None, valid_vertices=None, area_vx2=None, pixels="unmeasured")
    if not path.is_dir():
        rep["errors"].append(_issue("dir", f"{path} is not a folder", "seg_dir"))
        return _finish(rep)
    meta_path = path / "meta.json"
    meta = None
    if not meta_path.is_file():
        rep["errors"].append(_issue("meta", "meta.json is missing", "seg_dir"))
    else:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            rep["errors"].append(_issue("meta", f"meta.json is not JSON: {exc}", "seg_meta"))
        if meta is not None and not isinstance(meta, dict):
            rep["errors"].append(_issue("meta", "meta.json is not a JSON object", "seg_meta"))
            meta = None
    if meta is not None:
        if meta.get("type") != "seg":
            rep["errors"].append(_issue("type", f"meta.json type is {meta.get('type')!r}, VC3D requires 'seg'",
                                        "seg_meta"))
        if "uuid" not in meta:
            rep["errors"].append(_issue("uuid", "meta.json has no uuid, VC3D requires one", "seg_meta"))
        elif not isinstance(meta["uuid"], str) or not meta["uuid"]:
            rep["warnings"].append(_issue("uuid", f"meta.json uuid is {meta['uuid']!r}, not a non-empty string",
                                          "seg_meta"))
        if meta.get("format") != "tifxyz":
            rep["errors"].append(_issue("format", f"meta.json format is {meta.get('format')!r}; VC3D loads a "
                                        "surface only when it is 'tifxyz'", "seg_format"))
        sc = meta.get("scale")
        vals = [_num(v) for v in sc] if isinstance(sc, list) else []
        if len(vals) != 2 or any(v is None or v <= 0 for v in vals):
            rep["errors"].append(_issue("scale", f"meta.json scale is {sc!r}; it must be two finite positive "
                                        "numbers (grid cells per voxel)", "scale"))
        else:
            rep["scale"] = vals
    placeholder = bool(meta) and meta.get("vc_open_data_lazy_placeholder") is True
    if placeholder:
        rep["placeholder"] = True
    infos = {}
    for band in ("x", "y", "z"):
        f = path / f"{band}.tif"
        if not f.is_file():
            if not placeholder:
                rep["errors"].append(_issue("bands", f"{band}.tif is missing", "seg_bands"))
            continue
        try:
            infos[band] = tiff_info(f)
        except FormatError as exc:
            rep["errors"].append(_issue("bands", str(exc), "seg_bands"))
    for band, info in infos.items():
        if info["samples"] != 1:
            rep["errors"].append(_issue("samples", f"{band}.tif has {info['samples']} samples per pixel, VC3D "
                                        "reads one", "band_samples"))
        if info["bits"] not in (8, 16, 32, 64):
            rep["errors"].append(_issue("bits", f"{band}.tif has {info['bits']} bits per sample", "band_bits"))
        elif info["dtype"] != "float32":
            rep["warnings"].append(_issue("dtype", f"{band}.tif is {info['dtype']}, not float32 as VC3D and "
                                          "spiral-fitting write", "band_dtype"))
    sizes = {(i["width"], i["height"]) for i in infos.values()}
    if len(sizes) > 1:
        rep["errors"].append(_issue("shape", "x.tif, y.tif and z.tif differ in size: " + ", ".join(
            f"{b} {i['width']}x{i['height']}" for b, i in infos.items()), "band_size"))
    if placeholder and not infos:
        dims = meta.get("tiff_dimensions")
        if isinstance(dims, list) and len(dims) >= 2:
            rep["grid"] = [dims[1], dims[0]]
        else:
            rep["errors"].append(_issue("tiff_dimensions", "a catalog placeholder needs tiff_dimensions [width, "
                                        "height] in meta.json", "dims"))
        rep["pixels"] = "unmeasured: catalog placeholder without TIFFs"
        return _finish(rep)
    if "x" in infos:
        w, h = infos["x"]["width"], infos["x"]["height"]
        rep["grid"] = [h, w]
        dims = meta.get("tiff_dimensions") if meta else None
        if isinstance(dims, list) and len(dims) >= 2 and [dims[0], dims[1]] != [w, h]:
            rep["warnings"].append(_issue("tiff_dimensions", f"meta.json tiff_dimensions {dims[:2]} differ from "
                                          f"x.tif's {w} x {h}", "dims"))
    if pixels and not rep["errors"] and len(infos) == 3:
        if not _have_numpy():
            rep["pixels"] = "unmeasured: numpy is not installed"
        else:
            try:
                _pixel_checks(path, meta, rep)
                rep["pixels"] = "checked"
            except FormatError as exc:
                rep["pixels"] = f"unmeasured: {exc}"
    return _finish(rep)


def _pixel_checks(path, meta, rep):
    import numpy as np
    xyz = np.stack([read_tiff_pixels(path / f"{b}.tif").astype(np.float64) for b in "xyz"], -1)
    finite = np.isfinite(xyz).all(-1)
    if not finite.all():
        rep["errors"].append(_issue("nan", f"{int((~finite).sum())} vertices hold NaN or infinite values; VC3D "
                                    "marks holes only with -1, so it would take them as valid", "sentinel"))
    neg = xyz == -1
    valid = finite & ~neg.any(-1)
    partial = neg.any(-1) & ~neg.all(-1)
    if partial.any():
        rep["warnings"].append(_issue("partial_sentinel", f"{int(partial.sum())} vertices have -1 in some but not "
                                      "all of x, y, z; VC3D treats them as holes", "sentinel"))
    zdrop = valid & (xyz[..., 2] <= 0)
    if zdrop.any():
        rep["warnings"].append(_issue("z_nonpositive", f"{int(zdrop.sum())} valid vertices have z <= 0; VC3D's "
                                      "loader turns them into holes", "z_drop"))
    valid &= ~zdrop
    n = int(valid.sum())
    rep["valid_vertices"] = n
    quads = valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:]
    if rep["scale"]:
        rep["area_vx2"] = round(float(quads.sum()) / (rep["scale"][0] * rep["scale"][1]), 3)
    if n == 0:
        rep["errors"].append(_issue("empty", "the surface has no valid vertex", "sentinel"))
        return
    pts = xyz[valid]
    lo, hi = pts.min(0).tolist(), pts.max(0).tolist()
    rep["bbox_measured"] = [[round(v, 3) for v in lo], [round(v, 3) for v in hi]]
    bb = meta.get("bbox") if meta else None
    if bb is not None:
        try:
            stored = [[float(v) for v in bb[0]], [float(v) for v in bb[1]]]
            off = max(abs(a - b) for a, b in zip(stored[0] + stored[1], lo + hi))
        except (TypeError, ValueError, IndexError):
            rep["warnings"].append(_issue("bbox", f"meta.json bbox {bb!r} is not [[x, y, z], [x, y, z]]", "bbox"))
        else:
            if off > BBOX_TOL_VOX:
                rep["warnings"].append(_issue("bbox", f"meta.json bbox differs from the valid vertices' extent by "
                                              f"up to {off:.1f} voxels; VC3D reads the stored bbox at load",
                                              "bbox"))


def find_segments(root):
    """tifxyz folders under root as VC3D's segments entry sees them: root itself, or its immediate subfolders
    holding meta.json."""
    root = Path(root)
    if (root / "meta.json").is_file():
        return [root]
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "meta.json").is_file())


def vc3d_segment_id(segdir):
    """The id VC3D keys a loaded segment by (Segmentation.cpp:42-56): the uuid of an Open Data catalog
    representation (meta.json holds vc_open_data_representation and a non-empty string uuid), else the folder
    name. VC3D loads one segment per id and skips the rest (VolumePkg.cpp:2086-2090)."""
    segdir = Path(segdir)
    try:
        meta = json.loads((segdir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        meta = None
    if isinstance(meta, dict) and "vc_open_data_representation" in meta and isinstance(meta.get("uuid"), str) \
            and meta["uuid"]:
        return meta["uuid"]
    return Path(os.path.abspath(segdir)).name


# ---------------------------------------------------------------- VC3D project

def is_remote(location):
    """VolumePkg.cpp:64-72."""
    return location.startswith(("s3://", "s3+", "http://", "https://", "sftp://"))


def _resolve(location, base):
    """VolumePkg.cpp:74-81 resolveLocalPath, normalized lexically so a project not yet written can be checked."""
    p = Path(location[len("file://"):]) if location.startswith("file://") else Path(location)
    return p if p.is_absolute() else Path(os.path.normpath(Path(base) / p))


def _is_zarr_volume_dir(d):
    """VolumePkg.cpp:112-131 isSingleZarrVolumeDir."""
    def marker(x):
        return any((x / m).exists() for m in (".zarray", ".zgroup", ".zattrs", "zarr.json"))
    if not d.is_dir():
        return False
    if (d / ".zarray").exists() or (d / "zarr.json").exists():
        return True
    if not ((d / "meta.json").exists() or (d / "metadata.json").exists() or marker(d)):
        return False
    return any(c.is_dir() and marker(c) for c in d.iterdir())


def _is_normal_grid_dir(d):
    return d.is_dir() and all((d / s).is_dir() for s in ("xy", "xz", "yz")) and (d / "metadata.json").exists()


def check_umbilicus(path):
    """Read an umbilicus file as VC3D's LoadJsonFile does (Umbilicus.cpp:272-370); returns (points, errors)."""
    errors = []
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return 0, [f"cannot read {path}: {exc}"]
    arr = None
    if isinstance(doc, list):
        arr = doc
    elif isinstance(doc, dict) and "points" in doc:
        arr = doc["points"]
    elif isinstance(doc, dict) and "control_points" in doc:
        arr = doc["control_points"]
    if not isinstance(arr, list):
        return 0, ["the root must be an array or hold a 'points' or 'control_points' array"]
    for i, e in enumerate(arr):
        if isinstance(e, list):
            ok = len(e) >= 3 and all(_num(v) is not None for v in e[:3])
        elif isinstance(e, dict):
            ok = all(k in e and _num(e[k]) is not None for k in ("z", "y", "x"))
        else:
            ok = False
        if not ok:
            errors.append(f"entry {i} is not [z, y, x] or an object with numeric z, y, x")
            break
    if not arr:
        errors.append("it holds no points")
    md = doc.get("metadata") if isinstance(doc, dict) else None
    if isinstance(doc, dict) and "metadata" in doc and md is not None and not isinstance(md, dict):
        errors.append("metadata is not an object")
    elif isinstance(md, dict):
        if "voxelsize_um" in md and not ((_num(md["voxelsize_um"]) or 0) > 0):
            errors.append(f"metadata.voxelsize_um {md['voxelsize_um']!r} is not a positive number")
        if "volume" in md and not (isinstance(md["volume"], str) and md["volume"]):
            errors.append(f"metadata.volume {md['volume']!r} is not a non-empty string")
        dims = [k for k in ("volume_width", "volume_height", "volume_slices") if k in md]
        if dims and (len(dims) != 3 or any(not isinstance(md[k], int) or isinstance(md[k], bool) or md[k] <= 0
                                           for k in dims)):
            errors.append("metadata volume_width, volume_height, volume_slices must be all three positive "
                          "integers or absent")
    return len(arr), errors


def _entries(raw, rep, key):
    if raw is None:
        return []
    if not isinstance(raw, list):
        rep["errors"].append(_issue("entries", f"{key} is not a list", "project_entry"))
        return []
    out = []
    for e in raw:
        if isinstance(e, str) and e:
            out.append((e, []))
        elif isinstance(e, dict) and isinstance(e.get("location"), str) and e["location"]:
            tags = e.get("tags", [])
            if not (isinstance(tags, list) and all(isinstance(t, str) for t in tags)):
                rep["errors"].append(_issue("entries", f"{key} entry {e['location']!r} has tags that are not a list "
                                            "of strings", "project_entry"))
                tags = []
            out.append((e["location"], tags))
        else:
            rep["warnings"].append(_issue("entries", f"{key} entry {e!r} is neither a path nor "
                                          "{{location, tags}}; VC3D skips it", "project_entry"))
    return out


def check_project(doc, base, pixels=False):
    """Check a VC3D project document (the .volpkg.json content) whose relative paths resolve against base."""
    rep = _report(volumes=[], segments=[], normal_grids=[], umbilicus=None)
    if not isinstance(doc, dict):
        rep["errors"].append(_issue("project", "the project is not a JSON object", "project_json"))
        return _finish(rep)
    if not isinstance(doc.get("name", ""), str):
        rep["warnings"].append(_issue("name", "name is not a string", "project_json"))
    vols = _entries(doc.get("volumes"), rep, "volumes")
    if not vols:
        rep["warnings"].append(_issue("volumes", "the project lists no volume", "project_json"))
    for loc, tags in vols:
        row = {"location": loc, "tags": tags, "remote": is_remote(loc)}
        if row["remote"]:
            if "://" not in loc or len(loc.split("://", 1)[1]) == 0:
                rep["errors"].append(_issue("volume", f"{loc}: remote URL without host", "loc_validate"))
            elif not loc.split("?")[0].rstrip("/").lower().endswith(".zarr"):
                rep["warnings"].append(_issue("volume", f"{loc}: a remote volume should point directly at a .zarr "
                                              "root; collection listing is not supported", "remote_zarr"))
        else:
            p = _resolve(loc, base)
            row["path"] = str(p)
            if not p.is_dir():
                rep["errors"].append(_issue("volume", f"{loc}: {p} is not a folder", "loc_validate"))
            elif not (_is_zarr_volume_dir(p) or any(c.is_dir() and _is_zarr_volume_dir(c) for c in p.iterdir())):
                rep["errors"].append(_issue("volume", f"{loc}: not a zarr volume and holds none", "zarr_dir"))
        rep["volumes"].append(row)
    ids = {}            # VC3D id -> the folder that takes it (the first one loaded, in entry order)
    for loc, tags in _entries(doc.get("segments"), rep, "segments"):
        row = {"location": loc, "found": 0, "failing": []}
        if is_remote(loc):
            rep["errors"].append(_issue("segments", f"{loc}: VC3D supports remote locations only for volumes",
                                        "loc_validate"))
        else:
            p = _resolve(loc, base)
            row["path"] = str(p)
            segs = find_segments(p)
            row["found"] = len(segs)
            if not p.is_dir():
                rep["errors"].append(_issue("segments", f"{loc}: {p} is not a folder", "loc_validate"))
            elif not segs:
                rep["errors"].append(_issue("segments", f"{loc}: no segment folder (meta.json) in it",
                                            "loc_validate"))
            for s in segs:
                r = check_tifxyz(s, pixels=pixels)
                if not r["ok"]:
                    row["failing"].append({"segment": s.name, "errors": [e["message"] for e in r["errors"]]})
                sid = vc3d_segment_id(s)
                if sid in ids and Path(ids[sid]).resolve() != s.resolve():
                    rep["errors"].append(_issue("duplicate_id", f"{loc}: {s} has the segment id {sid!r} of {ids[sid]}; "
                                                "VC3D loads the first and skips this one", "seg_dup"))
                ids.setdefault(sid, str(s))
            if row["failing"]:
                rep["errors"].append(_issue("segments", f"{loc}: {len(row['failing'])} of {len(segs)} segment "
                                            "folders fail the tifxyz check (VC3D skips or cannot load them)",
                                            "seg_meta"))
        rep["segments"].append(row)
    for loc, tags in _entries(doc.get("normal_grids"), rep, "normal_grids"):
        p = _resolve(loc, base)
        ok = not is_remote(loc) and (_is_normal_grid_dir(p) or (p.is_dir() and any(
            c.is_dir() and _is_normal_grid_dir(c) for c in p.iterdir())))
        if not ok:
            rep["errors"].append(_issue("normal_grids", f"{loc}: not a normal-grid folder (xy/, xz/, yz/ and "
                                        "metadata.json), or remote", "normal_grids"))
        rep["normal_grids"].append({"location": loc, "ok": ok})
    um = doc.get("umbilicus")
    if um is not None:
        if not isinstance(um, str) or not um:
            rep["errors"].append(_issue("umbilicus", f"umbilicus {um!r} is not a path", "project_json"))
        else:
            p = _resolve(um, base)
            n, errs = (0, [f"{p} does not exist"]) if not p.is_file() else check_umbilicus(p)
            rep["umbilicus"] = {"location": um, "path": str(p), "points": n}
            for e in errs:
                rep["errors"].append(_issue("umbilicus", f"{um}: {e}", "umbilicus"))
    out = doc.get("output_segments")
    if out is not None:
        if not isinstance(out, str) or not out or is_remote(out):
            rep["errors"].append(_issue("output_segments", f"output_segments {out!r} is not a local path",
                                        "project_json"))
        elif _resolve(out, base).exists() and not _resolve(out, base).is_dir():
            rep["errors"].append(_issue("output_segments", f"{out} exists and is not a folder", "project_json"))
    return _finish(rep)


def _entry(location, tags):
    return {"location": location, "tags": list(tags)} if tags else location


def _rel(path, base):
    p = Path(path).resolve()
    try:
        return os.path.relpath(p, Path(base).resolve())
    except ValueError:      # another drive on Windows
        return str(p)


def build_project(out, volumes=(), segments=(), normal_grids=(), umbilicus=None, output_segments=None,
                  name=None, anonymous=False, voxel_um=None):
    """The project document VolumePkg::toJson writes (VolumePkg.cpp:2236-2249), local paths relative to out's
    folder. voxel_um tags the first remote volume; anonymous tags every remote volume."""
    base = Path(out).resolve().parent
    vols = []
    for i, v in enumerate(volumes):
        v = str(v)
        if is_remote(v):
            tags = ([ANON_TAG] if anonymous else []) + ([f"{VOXEL_TAG}{voxel_um:g}"] if voxel_um and i == 0 else [])
            vols.append(_entry(v, tags))
        else:
            vols.append(_rel(v, base))
    doc = {"name": name or Path(out).name[:-len(".volpkg.json")] or "Untitled", "version": 1,
           "volumes": vols, "segments": [_rel(s, base) for s in segments],
           "normal_grids": [_rel(g, base) for g in normal_grids], "lasagna_datasets": []}
    if output_segments:
        doc["output_segments"] = _rel(output_segments, base)
    if umbilicus:
        doc["umbilicus"] = _rel(umbilicus, base)
    return doc


def from_autopipe(run):
    """Volumes, segments and umbilicus of an AutoPipeline run folder (kit/autopipe.py: plan.json resolved,
    traces/, umbilicus.json)."""
    run = Path(run)
    plan = _load_json(run / "plan.json", "AutoPipeline plan")
    res = plan.get("resolved") if isinstance(plan, dict) else None
    if not isinstance(res, dict) or not res.get("volume_url"):
        raise FormatError(f"{run}/plan.json has no resolved.volume_url: not an AutoPipeline run folder")
    vols = [res["volume_url"]] + ([res["prediction_url"]] if res.get("prediction_url") else [])
    segs = [run / "traces"] if find_segments(run / "traces") else []
    umb = run / "umbilicus.json" if (run / "umbilicus.json").is_file() else None
    return {"volumes": vols, "segments": segs, "umbilicus": umb, "voxel_um": _num(res.get("voxel_um")),
            "name": f"{res.get('sample', 'run')}-{res.get('volume', '')}".rstrip("-")}


def _run_project(a):
    if a.check:
        doc = _load_json(a.check, "VC3D project")
        rep = check_project(doc, Path(a.check).resolve().parent, pixels=a.pixels)
        rep["project"] = str(a.check)
        return rep
    if not a.out:
        raise FormatError("give OUT.volpkg.json, or --check FILE")
    out = Path(a.out)
    if not out.name.endswith(".volpkg.json"):
        raise FormatError(f"{out}: VC3D opens projects named *.volpkg.json")
    vols, segs, umb, voxel, name = list(a.volume or []), list(a.segments or []), a.umbilicus, a.voxel_um, a.name
    if a.from_autopipe:
        ap = from_autopipe(a.from_autopipe)
        vols = vols or ap["volumes"]
        segs = segs or ap["segments"]
        umb = umb or ap["umbilicus"]
        voxel = voxel or ap["voxel_um"]
        name = name or ap["name"]
    doc = build_project(out, vols, segs, a.normal_grids or [], umb, a.output_segments, name,
                        anonymous=a.anonymous, voxel_um=voxel)
    return write_project(out, doc, overwrite=a.overwrite, pixels=a.pixels)


def write_project(out, doc, overwrite=False, pixels=False):
    """Check a project document (build_project's) as `project --check` does and write it to out only when every
    check passes; FormatError when out exists and overwrite is false. Returns the report (written true or false)."""
    out = Path(out)
    if not out.name.endswith(".volpkg.json"):
        raise FormatError(f"{out}: VC3D opens projects named *.volpkg.json")
    rep = check_project(doc, out.resolve().parent, pixels=pixels)
    rep["project"] = str(out)
    rep["document"] = doc
    rep["written"] = False
    if rep["ok"]:
        if out.exists() and not overwrite:
            raise FormatError(f"{out} exists; pass --overwrite to replace it")
        _atomic_write(out, json.dumps(doc, indent=2) + "\n")
        rep["written"] = True
    return rep


# ---------------------------------------------------------------- ink map for VC3D's Ink Detection overlay

def segment_key(segdir, meta):
    """The key VC3D matches an ink record against: the catalog ids in meta.json if any, else the folder name."""
    for k in ("vc_open_data_segment_long_id", "vc_open_data_catalog_segment_lineage_id", "vc_open_data_segment_id"):
        v = meta.get(k) if isinstance(meta, dict) else None
        if isinstance(v, str) and v:
            return v
    return Path(segdir).resolve().name


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def canvas_aspect(segdir):
    """(grid rows, cols, expected width/height of a whole-grid map) for a tifxyz folder."""
    segdir = Path(segdir)
    meta = _load_json(segdir / "meta.json", "segment meta.json")
    info = tiff_info(segdir / "x.tif")
    sc = meta.get("scale") if isinstance(meta, dict) else None
    sx, sy = (float(sc[0]), float(sc[1])) if isinstance(sc, list) and len(sc) == 2 else (1.0, 1.0)
    return meta, info["height"], info["width"], (info["width"] / sx) / (info["height"] / sy)


def _canvas_px(meta, rows, cols):
    """The whole-grid render canvas in pixels, [width, height] (grid size over meta.json's scale), for --expect-size."""
    sc = meta.get("scale") if isinstance(meta, dict) else None
    sx, sy = (float(sc[0]), float(sc[1])) if isinstance(sc, list) and len(sc) == 2 else (1.0, 1.0)
    return [round(cols / sx, 1), round(rows / sy, 1)]


def _aspect_issue(mw, mh, expected, rows, cols):
    """An error message when the map's aspect is off the canvas's by more than ASPECT_TOL, else None. Only the
    aspect is compared: a crop, a turned map or another segment's map with the same aspect passes."""
    got = mw / mh
    if abs(got / expected - 1) <= ASPECT_TOL:
        return None
    hint = " (it matches the grid turned by 90 degrees: transposed?)" if abs((mh / mw) / expected - 1) <= \
        ASPECT_TOL else " (a crop of the canvas, or another segment?)"
    return (f"map is {mw} x {mh} (aspect {got:.4f}) but the segment's {cols} x {rows} grid needs aspect "
            f"{expected:.4f}{hint}; VC3D would stretch it over the whole segment")


def loadable_canvas(segdir):
    """canvas_aspect of a folder that passes the tifxyz header check; FormatError otherwise (inkmap add, preds
    export --register)."""
    segdir = Path(segdir)
    seg = check_tifxyz(segdir, pixels=False)
    if not seg["ok"]:
        raise FormatError(f"{segdir}: not a loadable tifxyz segment: " + "; ".join(e["message"]
                                                                                   for e in seg["errors"]))
    return canvas_aspect(segdir)


def add_inkmap(segdir, map_path, label=None, artifact_type="ink detection", sample_id=None, source_url=None,
               copy=False, overwrite=False, expect_size=None, extra=None):
    """Register map_path in SEGDIR/ink-detections.json for VC3D's Ink Detection overlay (the `inkmap add` command);
    extra adds fields to the record's kit_villafmt block. Returns the report."""
    segdir = Path(segdir)
    meta, rows, cols, expected = loadable_canvas(segdir)
    src = Path(map_path)
    mw, mh, kind = image_size(src)
    rep = _report(segment=str(segdir), map=str(src), map_size=[mw, mh], kind=kind, grid=[rows, cols],
                  expected_aspect=round(expected, 6), canvas_px=_canvas_px(meta, rows, cols), written=False)
    msg = _aspect_issue(mw, mh, expected, rows, cols)
    if msg:
        rep["errors"].append(_issue("aspect", msg, "ink_stretch"))
        return _finish(rep)
    if expect_size:
        ew, eh = expect_size
        rep["expect_size"] = [ew, eh]
        if (mw, mh) != (ew, eh):
            rep["errors"].append(_issue("size", f"map is {mw} x {mh} but --expect-size asks for {ew} x {eh}: a crop, "
                                        "a render at another scale, or another segment's map of the same aspect?",
                                        "ink_stretch"))
            return _finish(rep)
    if kind == "tiff":
        info = tiff_info(src)
        if info["samples"] not in (1, 3, 4):
            rep["errors"].append(_issue("samples", f"{info['samples']} samples per pixel; VC3D reads 1, 3 or 4",
                                        "ink_stretch"))
            return _finish(rep)
        if info["dtype"] != "uint8":
            rep["warnings"].append(_issue("dtype", f"the map is {info['dtype']}; VC3D stretches a non-8-bit map "
                                          "from its own minimum to maximum, so its 0 to 255 scale is lost",
                                          "ink_stretch"))
    if copy:
        dest_dir = segdir / "ink"
        dest = dest_dir / src.name
        if dest.exists() and not overwrite and _sha256(dest) != _sha256(src):
            raise FormatError(f"{dest} exists with other content; pass --overwrite")
        dest_dir.mkdir(exist_ok=True)
        if dest.resolve() != src.resolve():
            shutil.copyfile(src, dest)
        local = f"ink/{src.name}"
        target = dest
    else:
        target = src.resolve()
        try:
            local = target.relative_to(segdir.resolve()).as_posix()
        except ValueError:
            local = str(target)
    key = segment_key(segdir, meta)
    rec = {"local_file": local, "label": label or f"{key} - {src.stem}", "segment_id": key,
           "artifact_type": artifact_type, "sample_id": sample_id or "",
           "kit_villafmt": {"sha256": _sha256(target), "size": [mw, mh], "grid": [rows, cols],
                            "note": "Model output, not a reading", **(extra or {})}}
    if source_url:
        rec["original_source_uri"] = source_url
    path = segdir / "ink-detections.json"
    records = []
    if path.exists():
        records = _load_json(path, "ink-detections.json")
        if not isinstance(records, list):
            raise FormatError(f"{path} is not a JSON array; VC3D would ignore it, refusing to overwrite")
    def where(local_file):
        f = Path(local_file)
        return f if f.is_absolute() else (segdir / f).resolve()
    kept = [r for r in records if not (isinstance(r, dict) and isinstance(r.get("local_file"), str)
                                       and where(r["local_file"]) == where(local))]
    kept.append(rec)
    _atomic_write(path, json.dumps(kept, indent=2) + "\n")
    rep.update(record=rec, records=len(kept), written=True, file=str(path))
    return _finish(rep)


def _run_inkmap_add(a):
    return add_inkmap(a.segdir, a.map, label=a.label, artifact_type=a.artifact_type, sample_id=a.sample_id,
                      source_url=a.source_url, copy=a.copy, overwrite=a.overwrite, expect_size=a.expect_size)


def check_inkmaps(segdir):
    """Check SEGDIR/ink-detections.json as VC3D reads it."""
    segdir = Path(segdir)
    rep = _report(segment=str(segdir), records=[])
    path = segdir / "ink-detections.json"
    if not path.is_file():
        rep["errors"].append(_issue("records", f"{path} does not exist", "ink_records"))
        return _finish(rep)
    records = _load_json(path, "ink-detections.json")
    if not isinstance(records, list):
        rep["errors"].append(_issue("records", "ink-detections.json is not a JSON array; VC3D ignores it",
                                    "ink_records"))
        return _finish(rep)
    meta, rows, cols, expected = canvas_aspect(segdir)
    key = segment_key(segdir, meta)
    for i, r in enumerate(records):
        row = {"index": i, "ok": False}
        rep["records"].append(row)
        if not isinstance(r, dict) or not isinstance(r.get("local_file"), str) or not r["local_file"]:
            rep["errors"].append(_issue("record", f"record {i} has no local_file; VC3D skips it", "ink_records"))
            continue
        f = Path(r["local_file"])
        f = f if f.is_absolute() else segdir / f
        row["local_file"] = r["local_file"]
        if not f.is_file() or f.stat().st_size == 0:
            rep["errors"].append(_issue("record", f"record {i}: {f} is missing or empty; VC3D skips it",
                                        "ink_records"))
            continue
        if key not in (r.get("segment_id"), r.get("segment_long_id")):
            rep["errors"].append(_issue("record", f"record {i}: segment_id {r.get('segment_id')!r} does not match "
                                        f"the segment's key {key!r}; VC3D would not offer it here", "ink_match"))
            continue
        try:
            mw, mh, _ = image_size(f)
        except FormatError as exc:
            rep["errors"].append(_issue("record", f"record {i}: {exc}", "ink_records"))
            continue
        msg = _aspect_issue(mw, mh, expected, rows, cols)
        if msg:
            rep["errors"].append(_issue("aspect", f"record {i}: {msg}", "ink_stretch"))
            continue
        row["ok"] = True
    return _finish(rep)


# ---------------------------------------------------------------- ink maps as villa's prediction files (preds/)

PRED_TILE = 256            # tile edge, a multiple of 16; villa's infer.py uses the model's patch size (979-981)
PRED_SCALES = ("auto", "prob", "u8", "minmax")
PRED_DIRECTIONS = ("forward", "reverse")
PRED_DATE = "%d%m%y"                         # infer.py:1212
PRED_SUFFIXES = (".png", ".tif", ".tiff")    # merge_predictions.py:30
PRED_MERGED = "merged_"                      # merge_predictions.py:27
PROB_TOL = 1e-6            # --scale prob accepts values this far outside 0 to 1 (float rounding) and clips them
CKPT_SUFFIXES = (".ckpt", ".pt", ".pth", ".safetensors", ".bin")
SCALE_RULES = {
    "prob": "clipped to 0 to 1, times 255, truncated to uint8, as villa's inference encodes (infer.py:791-812)",
    "minmax": "(value - min) / (max - min) over the whole map, then as prob",
    "u8": "kept as 0 to 255 (float values rounded to the nearest integer)",
}


def lzw_encode(data):
    """TIFF LZW (compression 5) of a bytes object, as libtiff codes it: a clear code first, 9 to 12 bit codes written
    most significant bit first, the code width raised one code early, a clear code when the table reaches 4094
    entries, and an end code. libtiff's optional extra clear when the ratio drops is not done; every TIFF LZW decoder
    reads both."""
    out = bytearray()
    app = out.append
    acc, nb, width, maxcode = 256, 9, 9, 511          # the clear code opens the stream
    nxt = 258

    def put(code, wd):
        nonlocal acc, nb
        acc = (acc << wd) | code
        nb += wd
        while nb >= 8:
            nb -= 8
            app((acc >> nb) & 255)
        acc &= 255

    if not data:
        put(257, 9)
    else:
        table = {}
        get = table.get
        w = data[0]
        for c in data[1:]:
            key = (w << 8) | c
            code = get(key)
            if code is not None:
                w = code
                continue
            acc = (acc << width) | w
            nb += width - 8
            app((acc >> nb) & 255)
            if nb >= 8:
                nb -= 8
                app((acc >> nb) & 255)
            acc &= 255
            table[key] = nxt
            nxt += 1
            if nxt == 4094:
                put(256, width)
                table.clear()
                nxt, width, maxcode = 258, 9, 511
            elif nxt > maxcode:
                width += 1
                maxcode = (1 << width) - 1
            w = c
        put(w, width)
        nxt += 1                                       # the entry a decoder adds on reading the last code
        if nxt == 4094:
            put(256, width)
            width = 9
        elif nxt > maxcode:
            width += 1
        put(257, width)
    if nb:
        app((acc << (8 - nb)) & 255)
    return bytes(out)


def lzw_decode(data):
    """The bytes of one TIFF LZW (compression 5) stream: 9 to 12 bit codes, early change, clear and end codes."""
    out = bytearray()
    table = [bytes((i,)) for i in range(256)] + [b"", b""]
    width, mask = 9, 511
    prev = None
    acc = nb = pos = 0
    n = len(data)
    while True:
        while nb < width:
            if pos >= n:
                raise FormatError("LZW stream ends without an end code")
            acc = ((acc << 8) | data[pos]) & 0xFFFFFF
            pos += 1
            nb += 8
        nb -= width
        code = (acc >> nb) & mask
        if code == 257:
            break
        if code == 256:
            del table[258:]
            width, mask = 9, 511
            prev = None
            continue
        if prev is None:
            if code > 255:
                raise FormatError(f"LZW stream starts with code {code}, not a byte")
            entry = table[code]
        elif code < len(table):
            entry = table[code]
            table.append(prev + entry[:1])
        elif code == len(table):
            entry = prev + prev[:1]
            table.append(entry)
        else:
            raise FormatError(f"LZW code {code} is past the table of {len(table)} entries")
        out += entry
        prev = entry
        if len(table) >= mask and width < 12:
            width += 1
            mask = (1 << width) - 1
    return bytes(out)


def read_lzw_pixels(path, info=None):
    """A 2D numpy array of a one-sample LZW TIFF (tiled or in strips, no predictor), decoded here without tifffile or
    Pillow: villa's predictions (infer.py:815-834) and merged outputs (merge_predictions.py:343-346)."""
    import numpy as np
    path = Path(path)
    info = info or tiff_info(path)
    if info["compression"] != 5 or info["samples"] != 1 or not info["dtype"] or info["predictor"] != 1:
        raise FormatError(f"{path}: not a one-sample LZW TIFF without a predictor")
    dt = np.dtype(info["dtype"]).newbyteorder(info["byteorder"])
    h, w = info["height"], info["width"]
    out = np.zeros((h, w), dt)
    if info["tiled"]:
        tw, tl = info["tile_width"], info["tile_length"]
        offs, cnts = info["tile_offsets"] or [], info["tile_counts"] or []
        across = -(-w // tw)
        blocks = [((i // across) * tl, (i % across) * tw, tl, tw) for i in range(across * -(-h // tl))]
    else:
        rps = min(info["rows_per_strip"] or h, h)
        offs, cnts = info["strip_offsets"] or [], info["strip_counts"] or []
        blocks = [(y0, 0, min(rps, h - y0), w) for y0 in range(0, h, rps)]
    if len(offs) < len(blocks) or len(cnts) < len(blocks):
        raise FormatError(f"{path}: the TIFF lists {min(len(offs), len(cnts))} blocks, {len(blocks)} needed")
    with open(path, "rb") as f:
        for (y0, x0, bh, bw), off, cnt in zip(blocks, offs, cnts):
            f.seek(off)
            raw = lzw_decode(f.read(cnt))
            need = bh * bw * dt.itemsize
            if len(raw) < need:
                raise FormatError(f"{path}: a block decodes to {len(raw)} bytes, {need} needed")
            blk = np.frombuffer(raw[:need], dtype=dt).reshape(bh, bw)
            out[y0:y0 + bh, x0:x0 + bw] = blk[:min(bh, h - y0), :min(bw, w - x0)]
    return out.astype(dt.newbyteorder("="))


def _pillow_lzw():
    """(encode_tile, name) with Pillow's libtiff LZW encoder, or (None, None) when Pillow or its libtiff is missing.
    encode_tile returns None when Pillow does not give one strip, and the caller then encodes that tile itself."""
    try:
        import io
        import PIL
        from PIL import Image, features
        if not features.check("libtiff"):
            return None, None
        name = f"libtiff {features.version('libtiff')} through Pillow {PIL.__version__}"
    except Exception:  # Pillow without its compiled parts raises more than ImportError
        return None, None

    def encode(tile):
        buf = io.BytesIO()
        Image.fromarray(tile).save(buf, format="TIFF", compression="tiff_lzw", tiffinfo={278: tile.shape[0]})
        data = buf.getvalue()
        with _PillowUnbounded(), Image.open(io.BytesIO(data)) as im:
            offs, cnts, comp = im.tag_v2.get(273), im.tag_v2.get(279), im.tag_v2.get(259)
        if comp != 5 or not offs or not cnts or len(offs) != 1:
            return None
        return data[offs[0]:offs[0] + cnts[0]]
    return encode, name


def _tiff_entries(entries, ifd_at):
    """A Big TIFF directory (entries (tag, type, values), ascending tags) and the out-of-line values after it."""
    fmt = {2: ("s", 1), 3: ("H", 2), 4: ("I", 4), 16: ("Q", 8)}
    extra_at = ifd_at + 8 + 20 * len(entries) + 8
    body, extra = struct.pack("<Q", len(entries)), b""
    for tag, typ, vals in entries:
        data = vals if typ == 2 else struct.pack("<" + fmt[typ][0] * len(vals), *vals)
        count = len(vals)
        if len(data) <= 8:
            val = data.ljust(8, b"\0")
        else:
            if (extra_at + len(extra)) % 2:
                extra += b"\0"
            val = struct.pack("<Q", extra_at + len(extra))
            extra += data
        body += struct.pack("<HHQ", tag, typ, count) + val
    return body + struct.pack("<Q", 0) + extra


def write_pred_tiff(path, rows, shape=None, tile=PRED_TILE, description=None, codec="auto"):
    """Write a uint8 image as villa's ink inference writes a prediction (infer.py:815-834): one sample, tiled, LZW
    (compression 5), Big TIFF, little-endian, no predictor. rows is a 2D uint8 array, or a function rows(y0, y1)
    returning rows y0 to y1 of an image of shape (height, width). The file is written beside path under a name no
    villa tool picks up, read back (header, then every pixel, with Pillow when it is installed, else here) and only
    then renamed to path. codec "auto" encodes with Pillow's libtiff when present, "python" always here.
    Returns {"ok", "errors", "tiles", "bytes", "codec", "verified_with"}."""
    import numpy as np
    if not callable(rows):
        arr = np.asarray(rows)
        shape = arr.shape
        rows = lambda y0, y1: arr[y0:y1]  # noqa: E731
    h, w = (int(v) for v in shape)
    if h <= 0 or w <= 0:
        raise FormatError(f"an image of {w} x {h} pixels has nothing to write")
    if tile <= 0 or tile % 16:
        raise FormatError(f"tile {tile} is not a positive multiple of 16, as TIFF tiles must be")
    enc, codec_name = _pillow_lzw() if codec == "auto" else (None, None)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=str(path.parent))
    res = {"ok": False, "errors": [], "tiles": 0, "bytes": 0, "codec": codec_name or "kit pure-Python LZW",
           "verified_with": None}
    try:
        offs, cnts, fallback = [], [], 0
        with os.fdopen(fd, "wb") as f:
            f.write(b"II" + struct.pack("<HHHQ", 43, 8, 0, 0))
            for y0 in range(0, h, tile):
                band = np.asarray(rows(y0, min(h, y0 + tile)))
                if band.dtype != np.uint8 or band.shape != (min(h, y0 + tile) - y0, w):
                    raise ValueError(f"rows({y0}, ...) gave {band.dtype} {band.shape}, not uint8 rows of width {w}")
                for x0 in range(0, w, tile):
                    t = np.zeros((tile, tile), np.uint8)
                    part = band[:, x0:x0 + tile]
                    t[:part.shape[0], :part.shape[1]] = part
                    comp = enc(t) if enc else None
                    if comp is None:
                        fallback += bool(enc)
                        comp = lzw_encode(t.tobytes())
                    offs.append(f.tell())
                    cnts.append(len(comp))
                    f.write(comp)
            pad = (-f.tell()) % 8
            f.write(b"\0" * pad)
            ifd_at = f.tell()
            entries = [(256, 4, [w]), (257, 4, [h]), (258, 3, [8]), (259, 3, [5]), (262, 3, [1])]
            if description:
                entries.append((270, 2, description.encode("ascii", "replace") + b"\0"))
            entries += [(277, 3, [1]), (284, 3, [1]), (305, 2, b"kit.villafmt\0"), (322, 3, [tile]),
                        (323, 3, [tile]), (324, 16, offs), (325, 16, cnts), (339, 3, [1])]
            f.write(_tiff_entries(entries, ifd_at))
            f.seek(8)
            f.write(struct.pack("<Q", ifd_at))
        if fallback:
            res["codec"] += f" ({fallback} tiles encoded by kit's pure-Python LZW)"
        res["tiles"], res["bytes"] = len(offs), os.path.getsize(tmp)
        info = tiff_info(tmp)
        with open(tmp, "rb") as f:
            magic = struct.unpack("<H", f.read(4)[2:4])[0]
        got = {"magic": magic, "dtype": info["dtype"], "samples": info["samples"], "compression": info["compression"],
               "tiled": info["tiled"], "size": [info["width"], info["height"]], "tile": info["tile_width"]}
        want = {"magic": 43, "dtype": "uint8", "samples": 1, "compression": 5, "tiled": True, "size": [w, h],
                "tile": tile}
        for k in want:
            if got[k] != want[k]:
                res["errors"].append(f"the written header has {k} {got[k]!r}, not {want[k]!r}")
        if not res["errors"]:
            if _pillow_lzw()[0] is None:
                back = read_lzw_pixels(tmp, info)
                res["verified_with"] = "kit pure-Python LZW decoder"
            else:
                import PIL
                from PIL import Image
                try:
                    with _PillowUnbounded(), Image.open(tmp) as im:
                        back = np.asarray(im)
                    res["verified_with"] = f"Pillow {PIL.__version__} (libtiff)"
                except Exception as exc:  # Pillow raises several types for files it cannot read
                    back = None
                    res["errors"].append(f"Pillow cannot read the written file: {exc}")
            if back is not None:
                if back.shape != (h, w) or back.dtype != np.uint8:
                    res["errors"].append(f"the written file reads back as {back.dtype} {back.shape}")
                else:
                    bad = [y0 for y0 in range(0, h, tile)
                           if not np.array_equal(back[y0:y0 + tile], np.asarray(rows(y0, min(h, y0 + tile))))]
                    if bad:
                        res["errors"].append(f"the written file reads back with other pixels in {len(bad)} tile rows "
                                             f"(first at row {bad[0]})")
        if res["errors"]:
            return res
        os.chmod(tmp, _file_mode())
        os.replace(tmp, path)
        res["ok"] = True
        return res
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def pred_direction(name):
    """villa's parse_prediction_direction (merge_predictions.py:112-118): 'forward', 'reverse' or None."""
    lower = Path(name).stem.lower()
    if "_forward_" in lower or lower.endswith("_forward"):
        return "forward"
    if "_reverse_" in lower or lower.endswith("_reverse"):
        return "reverse"
    return None


def pred_name(segment, model, direction, date, prefix=""):
    """The file name villa's folder inference gives a prediction (infer.py:1213, 1224-1226, 1247)."""
    return f"{prefix + '_' if prefix else ''}{segment}_{model}_{direction}_{date}.tif"


def model_stem(name):
    """The checkpoint stem villa puts in prediction names (infer.py:1211): a path or a file name with a checkpoint
    suffix gives its stem; FormatError for a name villa's glob or a file name cannot carry."""
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    if base.lower().endswith(CKPT_SUFFIXES):
        base = base[:base.rfind(".")]
    if not base or base.startswith(".") or any(c in base for c in "*?[]") or any(ord(c) < 32 for c in base):
        raise FormatError(f"--model {name!r} is not a usable checkpoint stem: it is empty, starts with a dot, or "
                          "holds a glob character that villa's search for earlier predictions would misread")
    return base


def villa_surface(segdir):
    """villa's resolve_segment_zarr_path (infer.py:1165-1189) on SEGDIR and the height and width of the prediction
    its folder inference writes there (level 0, infer.py:940-952, 966-969), from zarr JSON alone."""
    segdir = Path(segdir)
    name = Path(os.path.abspath(segdir)).name
    found = next((c for c in (segdir / name, segdir / f"{name}.zarr", segdir / f"{name}.ome.zarr") if c.exists()),
                 None)
    if found is None:
        disc = [c for c in sorted(segdir.iterdir()) if c.is_dir() and (c.suffix == ".zarr" or any(
            (c / m).exists() for m in (".zgroup", ".zarray", "zarr.json")))]
        if len(disc) != 1:
            return {"path": None, "zarrs": [c.name for c in disc], "height": None, "width": None}
        found = disc[0]
    lay = zarr_layout(found) if found.is_dir() else {"shape": None}
    shape = lay.get("shape")
    rep = {"path": str(found), "shape": shape, "height": None, "width": None}
    if isinstance(shape, list) and len(shape) == 3 and all(isinstance(v, int) for v in shape):
        depth_first = shape.index(min(shape)) == 0
        rep["height"], rep["width"] = (shape[1], shape[2]) if depth_first else (shape[0], shape[1])
    return rep


def _load_map(path):
    """(2D array, stored shape) of an ink map: .npy (memory-mapped), TIFF, PNG or JPEG."""
    import numpy as np
    p = Path(path)
    if not p.is_file():
        raise FormatError(f"{p}: no such file (ink map)")
    ext = p.suffix.lower()
    if ext == ".npy":
        try:
            arr = np.load(p, mmap_mode="r", allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise FormatError(f"{p}: cannot read the ink map: {exc}") from None
    elif ext in (".tif", ".tiff"):
        arr = read_tiff_pixels(p)
    elif ext in (".png", ".jpg", ".jpeg"):
        try:
            from PIL import Image
        except ImportError:
            raise FormatError(f"{p}: reading a PNG or JPEG map needs Pillow") from None
        try:
            with _PillowUnbounded(), Image.open(p) as im:
                arr = np.asarray(im)
        except Exception as exc:  # Pillow raises several types for files it cannot decode
            raise FormatError(f"{p}: cannot read the ink map: {exc}") from None
    else:
        raise FormatError(f"{p}: an ink map must be .npy, .tif, .tiff, .png, .jpg or .jpeg")
    shape = [int(v) for v in arr.shape]
    if arr.ndim != 2:
        dims = [v for v in shape if v != 1]
        if len(dims) != 2:
            raise FormatError(f"{p}: the map has shape {shape}; a prediction is one 2D image, not a stack or a "
                              "color image")
        arr = arr.reshape(dims)
    if arr.dtype.kind not in "biuf":
        raise FormatError(f"{p}: the map's dtype {arr.dtype} is not boolean, integer or float")
    return arr, shape


def _map_stats(arr):
    """min, max (finite values), non-finite and non-integer counts, read in row blocks so a memory-mapped map stays
    on disk."""
    import numpy as np
    h, w = arr.shape
    step = max(1, (1 << 22) // max(1, w))
    lo, hi, bad, nonint = math.inf, -math.inf, 0, 0
    for y0 in range(0, h, step):
        b = np.asarray(arr[y0:y0 + step])
        if b.dtype.kind == "f":
            fin = np.isfinite(b)
            nf = int(b.size - np.count_nonzero(fin))
            bad += nf
            b = b[fin] if nf else b
            if not b.size:
                continue
            nonint += int(np.count_nonzero(b != np.rint(b)))
        lo, hi = min(lo, float(b.min())), max(hi, float(b.max()))
    return {"dtype": str(arr.dtype), "kind": arr.dtype.kind, "min": lo, "max": hi, "nonfinite": bad,
            "nonint": nonint}


def _scale_plan(requested, st):
    """(scale used, error message or None) for a map's statistics."""
    lo, hi, kind = st["min"], st["max"], st["kind"]
    used = requested
    if requested == "auto":
        if kind == "b" or (kind == "f" and lo >= 0 and hi <= 1):
            used = "prob"
        elif kind in "iu" and lo >= 0 and hi <= 255:
            used = "u8"
        else:
            return None, (f"values run from {lo:g} to {hi:g} ({st['dtype']}): neither probabilities (floats in 0 to "
                          "1) nor integers in 0 to 255; pass --scale prob, u8 or minmax")
    if used == "prob" and (lo < -PROB_TOL or hi > 1 + PROB_TOL):
        return used, (f"values run from {lo:g} to {hi:g}, outside 0 to 1, so --scale prob would clip them; is the "
                      "map 0 to 255 (--scale u8) or unscaled (--scale minmax)?")
    if used == "u8" and (lo < 0 or hi > 255):
        return used, f"values run from {lo:g} to {hi:g}, outside 0 to 255, so --scale u8 cannot keep them"
    if used == "minmax" and not hi > lo:
        return used, f"the map is constant ({lo:g}), so --scale minmax has no range to stretch"
    return used, None


def _encoder(arr, used, st):
    """rows(y0, y1) -> uint8 rows of the map under the scale used."""
    import numpy as np
    lo, hi = st["min"], st["max"]

    def rows(y0, y1):
        b = np.asarray(arr[y0:y1])
        if used == "u8":
            return (np.rint(b) if b.dtype.kind == "f" else b).astype(np.uint8)
        if used == "minmax":
            p = ((b.astype(np.float64) - lo) / (hi - lo)).astype(np.float32)
        else:
            p = b.astype(np.float32)
        np.clip(p, 0, 1, out=p)
        p *= 255
        return p.astype(np.uint8)
    return rows


def _preds_listing(preds_dir):
    """The files villa's merge_predictions takes from a preds folder (merge_predictions.py:121-136), with their
    direction and size."""
    out = []
    if Path(preds_dir).is_dir():
        for p in sorted(Path(preds_dir).iterdir()):
            if not p.is_file() or p.suffix.lower() not in PRED_SUFFIXES or p.stem.lower().startswith(PRED_MERGED):
                continue
            d = pred_direction(p.name)
            if d is None:
                continue
            try:
                w, h, _ = image_size(p)
                size = [w, h]
            except FormatError:
                size = None
            out.append({"name": p.name, "direction": d, "size": size})
    return out


def export_pred(map_path, segdir, model, direction, scale="auto", date=None, prefix="", tile=PRED_TILE,
                register=False, label=None, expect_size=None, overwrite=False, codec="auto", sample_id=None,
                extra=None):
    """Write an ink map as villa's prediction file SEGDIR/preds/<prefix_><seg>_<model>_<direction>_<date>.tif
    (uint8, tiled, LZW, Big TIFF) and, with register, add it to SEGDIR/ink-detections.json (sample_id and extra go
    to the record, as add_inkmap takes them). Returns the report."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        raise FormatError("preds export needs numpy") from None
    segdir = Path(segdir)
    if not segdir.is_dir():
        raise FormatError(f"{segdir} is not a folder")
    if direction not in PRED_DIRECTIONS:
        raise FormatError(f"direction {direction!r} is not forward or reverse")
    if scale not in PRED_SCALES:
        raise FormatError(f"scale {scale!r} is not one of {list(PRED_SCALES)}")
    if tile <= 0 or tile % 16:
        raise FormatError(f"tile {tile} is not a positive multiple of 16, as TIFF tiles must be")
    model = model_stem(model)
    if prefix and (prefix.startswith(".") or any(c in prefix for c in "/\\*?[]")):
        raise FormatError(f"--output-prefix {prefix!r} holds a path or glob character")
    date = date or datetime.now().strftime(PRED_DATE)
    try:
        ok_date = len(date) == 6 and date.isdigit() and bool(datetime.strptime(date, PRED_DATE))
    except ValueError:
        ok_date = False
    if not ok_date:
        raise FormatError(f"--date {date!r} is not DDMMYY, the date villa's folder inference writes (infer.py:1212)")
    seg = Path(os.path.abspath(segdir)).name
    name = pred_name(seg, model, direction, date, prefix)
    out = segdir / "preds" / name
    if out.exists() and not overwrite:
        raise FormatError(f"{out} exists; pass --overwrite to replace it")
    glob = f"{prefix + '_' if prefix else ''}{seg}_{model}_{direction}_*.tif"
    rep = _report(map=str(map_path), segment=str(segdir), segment_name=seg, model=model, direction=direction,
                  date=date, output_prefix=prefix, name=name, file=str(out), written=False, input=None, scale=None,
                  encoding=None, villa_view=None, registered=None)
    parsed = pred_direction(name)
    if parsed != direction:
        rep["errors"].append(_issue("direction", f"villa's merge_predictions would read {name} as {parsed!r}, not "
                                    f"{direction!r} (a name holding _forward_ counts as forward); rename the model",
                                    "pred_direction"))
    if name.lower().startswith(PRED_MERGED):
        rep["errors"].append(_issue("merged", f"{name} starts with {PRED_MERGED}, which villa's merge_predictions "
                                    "takes for its own output and never merges", "pred_merge"))
    if any(c in seg for c in "*?["):
        rep["warnings"].append(_issue("glob", f"the segment folder name {seg!r} holds a glob character, so villa's "
                                      "folder inference cannot find its own earlier predictions there", "pred_name"))
    arr, stored = _load_map(map_path)
    h, w = (int(v) for v in arr.shape)
    st = _map_stats(arr)
    rep["input"] = {"dtype": st["dtype"], "shape": stored, "size": [w, h],
                    "min": None if st["min"] == math.inf else st["min"],
                    "max": None if st["max"] == -math.inf else st["max"], "nonfinite": st["nonfinite"]}
    used = None
    if st["nonfinite"]:
        rep["errors"].append(_issue("nonfinite", f"{st['nonfinite']} values are NaN or infinite; villa's merge "
                                    "refuses non-finite predictions and a uint8 file cannot hold them, so fix the map "
                                    "first (for example, 0 where the model did not run)", "pred_finite"))
    else:
        used, msg = _scale_plan(scale, st)
        if msg:
            rep["errors"].append(_issue("scale", msg, "pred_encode"))
        rep["scale"] = {"requested": scale, "used": used, "rule": SCALE_RULES.get(used), "input_min": st["min"],
                        "input_max": st["max"]}
        if used == "u8" and st["nonint"]:
            rep["warnings"].append(_issue("rounded", f"{st['nonint']} values are not whole numbers and are rounded "
                                          "to the nearest", "pred_encode"))
    if expect_size and (w, h) != tuple(expect_size):
        rep["errors"].append(_issue("size", f"map is {w} x {h} but --expect-size asks for {expect_size[0]} x "
                                    f"{expect_size[1]}", "pred_surface"))
    surf = villa_surface(segdir)
    if surf["height"] is not None and (surf["height"], surf["width"]) != (h, w):
        rep["errors"].append(_issue("surface_size", f"map is {w} x {h} but villa would predict {surf['width']} x "
                                    f"{surf['height']} from {surf['path']}; villa's merge expects one size per "
                                    "segment", "pred_surface"))
    if register:
        meta, rows_, cols, expected = loadable_canvas(segdir)
        msg = _aspect_issue(w, h, expected, rows_, cols)
        if msg:
            rep["errors"].append(_issue("aspect", msg, "ink_stretch"))
    listing = _preds_listing(segdir / "preds")
    others = [f for f in listing if f["name"] != name]
    same = [f for f in others if f["direction"] == direction]
    clash = [f["name"] for f in same if f["size"] and f["size"] != [w, h]]
    if clash:
        rep["errors"].append(_issue("merge_shape", f"{len(clash)} {direction} predictions in preds/ have another size "
                                    f"({', '.join(clash[:5])}); villa's merge_predictions stops on a shape mismatch",
                                    "pred_shape"))
    unread = [f["name"] for f in others if not f["size"]]
    if unread:
        rep["warnings"].append(_issue("merge_unreadable", f"cannot read the size of {', '.join(unread[:5])} in preds/",
                                      "pred_merge"))
    if any(f["size"] and f["size"] != [w, h] for f in others if f["direction"] != direction):
        rep["warnings"].append(_issue("size_other_direction", "predictions of the other direction in preds/ have "
                                      "another size", "pred_shape"))
    earlier = [f["name"] for f in same if fnmatch.fnmatchcase(f["name"], glob)]
    if earlier:
        rep["warnings"].append(_issue("skip", f"preds/ already holds {', '.join(earlier[:5])} for this model and "
                                      "direction: villa's folder inference skips on either file, and merge_predictions "
                                      "averages all of them", "pred_name"))
    rep["villa_view"] = {"direction_of_name": parsed, "folder_inference_glob": glob,
                         "folder_inference": "skips this model and direction" if surf["path"] else
                         "finds no single surface zarr here, so it skips the whole segment",
                         "surface_volume": surf,
                         "merge_inputs": sorted([f["name"] for f in same] + [name])}
    if rep["errors"]:
        return _finish(rep)
    desc = (f"kit.villafmt preds export; scale {used}: {SCALE_RULES[used]}; input {st['dtype']} {st['min']:g} to "
            f"{st['max']:g}; villa {VILLA_PIN[:9]}; model output, not a reading")
    res = write_pred_tiff(out, _encoder(arr, used, st), (h, w), tile, desc, codec)
    rep["encoding"] = {"dtype": "uint8", "compression": 5, "compression_name": "LZW", "bigtiff": True, "magic": 43,
                       "tile": [tile, tile], "tiles": res["tiles"], "bytes": res["bytes"], "codec": res["codec"],
                       "verified_with": res["verified_with"]}
    for e in res["errors"]:
        rep["errors"].append(_issue("read_back", e, "pred_tiff"))
    if not res["ok"]:
        return _finish(rep)
    rep["written"] = True
    if register:
        r = add_inkmap(segdir, out, label=label, expect_size=expect_size, sample_id=sample_id,
                       extra={**(extra or {}), "villa_prediction": {"model": model, "direction": direction,
                                                                    "date": date, "scale": rep["scale"]}})
        rep["registered"] = {k: r.get(k) for k in ("ok", "file", "record", "records", "errors", "warnings")}
        rep["errors"] += [dict(e, message="register: " + e["message"]) for e in r["errors"]]
        rep["warnings"] += [dict(e, message="register: " + e["message"]) for e in r["warnings"]]
    return _finish(rep)


# ---------------------------------------------------------------- seeds and points

def _xyz(v, where):
    if isinstance(v, dict):
        v = v.get("xyz", v.get("p"))
    if not isinstance(v, (list, tuple)) or len(v) != 3 or any(_num(c) is None for c in v):
        raise FormatError(f"{where}: {v!r} is not three finite numbers x, y, z")
    return [float(c) for c in v]


def read_seeds(path, collection=None):
    """(points [[x, y, z], ...], detected format) from any of the supported seed and point files."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FormatError(f"{path}: cannot read: {exc}") from None
    return parse_seeds(text, str(path), collection)


def parse_seeds(text, path="<points>", collection=None):
    """read_seeds on text already in memory; path only names the source in messages."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        doc = None
    if doc is None:
        pts = []
        for n, line in enumerate(text.splitlines(), 1):
            line = line.split("#", 1)[0].replace(",", " ").strip()
            if not line:
                continue
            try:
                vals = [float(t) for t in line.split()]
            except ValueError:
                raise FormatError(f"{path}:{n}: not three numbers x y z") from None
            pts.append(_xyz(vals, f"{path}:{n}"))
        if not pts:
            raise FormatError(f"{path}: no points")
        return pts, "text"
    if isinstance(doc, dict) and "vc_pointcollections_json_version" in doc:
        if doc.get("vc_pointcollections_json_version") != VC3D_POINTS_VERSION:
            raise FormatError(f"{path}: VC3D point collection version {doc.get('vc_pointcollections_json_version')!r}"
                              f", expected {VC3D_POINTS_VERSION!r}")
        cols = doc.get("collections")
        if not isinstance(cols, dict):
            raise FormatError(f"{path}: collections is not an object")
        pts, names = [], []
        for cid in sorted(cols, key=lambda k: int(k) if str(k).isdigit() else 0):
            c = cols[cid]
            if not isinstance(c, dict) or not isinstance(c.get("name"), str):
                raise FormatError(f"{path}: collection {cid} has no name")
            names.append(c["name"])
            if collection and c["name"] != collection:
                continue
            p = c.get("points") or {}
            if not isinstance(p, dict):
                raise FormatError(f"{path}: collection {c['name']!r} points is not an object")
            for pid in sorted(p, key=lambda k: int(k) if str(k).isdigit() else 0):
                pts.append(_xyz(p[pid], f"{path} collection {c['name']!r} point {pid}"))
        if collection and collection not in names:
            raise FormatError(f"{path}: no collection named {collection!r}; it has {names}")
        if not pts:
            raise FormatError(f"{path}: the point collections hold no points")
        return pts, "vc3d"
    if isinstance(doc, dict) and "explicit_seed" in doc:
        raw = doc["explicit_seed"]
        fmt = "explicit"
    elif isinstance(doc, dict) and "seeds" in doc:
        raw = doc["seeds"]
        fmt = "autopipe"
    elif isinstance(doc, dict) and "seed" in doc and doc.get("format") == "tifxyz":
        raw = [doc["seed"]]
        fmt = "tifxyz-meta"
    elif isinstance(doc, list):
        raw = doc
        fmt = "list"
    else:
        raise FormatError(f"{path}: not a seed file this tool knows (AutoPipeline seeds.json, explicit_seed, VC3D "
                          "point collections, tifxyz meta.json with a seed, a list of [x, y, z], or text)")
    if not isinstance(raw, list) or not raw:
        raise FormatError(f"{path}: no points")
    return [_xyz(v, f"{path} point {i}") for i, v in enumerate(raw)], fmt


def vc3d_points(points, name="seeds", color=(1.0, 0.5, 0.0)):
    """A VC3D point collection document (PointCollections.cpp:36-119, 571-581) with one collection."""
    pts = {str(i + 1): {"p": list(p), "creation_time": 0, "wind_a": None} for i, p in enumerate(points)}
    return {"vc_pointcollections_json_version": VC3D_POINTS_VERSION,
            "collections": {"1": {"name": name, "points": pts, "metadata": {"winding_is_absolute": False},
                                  "color": list(color)}}}


def _is_uuid(v):
    """VC3D's isUuid (Uuid.hpp:10-21): 36 characters, hyphens at 8, 13, 18 and 23, hex digits elsewhere."""
    return isinstance(v, str) and len(v) == 36 and all(
        (c == "-") if i in (8, 13, 18, 23) else (c in "0123456789abcdefABCDEF") for i, c in enumerate(v))


def _stoull_key(k):
    """True when std::stoull reads a number from the key (PointCollections.cpp:160, 632): optional leading space and
    plus, then a digit, within 64 bits."""
    t = k.lstrip(" \t\n\r\f\v")
    t = t[1:] if t[:1] == "+" else t
    digits = len(t) - len(t.lstrip("0123456789"))
    return digits > 0 and int(t[:digits]) < 2 ** 64


def _numbers(v, n):
    """True when v is a list of at least n finite numbers (booleans refused, though nlohmann would take them)."""
    return isinstance(v, list) and len(v) >= n and all(
        isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) for c in v[:n])


def check_points(doc):
    """Check a VC3D point collection document as PointCollections::loadFromJSON reads it (PointCollections.cpp:
    603-645, 147-181, 58-69): any error means VC3D refuses the whole file and keeps the collections it had. Returns
    the report, with the collections and their point counts."""
    rep = _report(collections=[], points=0)
    def err(msg):
        rep["errors"].append(_issue("points", msg, "points_load"))
    if not isinstance(doc, dict):
        err("the file is not a JSON object")
        return _finish(rep)
    if doc.get("vc_pointcollections_json_version") != VC3D_POINTS_VERSION:
        err(f"vc_pointcollections_json_version is {doc.get('vc_pointcollections_json_version')!r}, not the string "
            f"{VC3D_POINTS_VERSION!r}")
    cols = doc.get("collections")
    if not isinstance(cols, dict):
        err("collections is missing or not an object")
        return _finish(rep)
    for cid, c in cols.items():
        where = f"collection {cid!r}"
        if not _stoull_key(cid):
            err(f"{where}: the key is not a number")
        if not isinstance(c, dict):
            err(f"{where} is not an object")
            continue
        if "uuid" in c and not _is_uuid(c["uuid"]):
            err(f"{where}: uuid {c['uuid']!r} is not a uuid")
        if not isinstance(c.get("name"), str):
            err(f"{where} has no name string")
        if "points" not in c:
            err(f"{where} has no points")
            pts = {}
        else:
            pts = c["points"] if isinstance(c["points"], dict) else {}
        for pid, pt in pts.items():
            at = f"{where} point {pid!r}"
            if not _stoull_key(pid):
                err(f"{at}: the key is not a number")
            if not isinstance(pt, dict):
                err(f"{at} is not an object")
                continue
            if not _numbers(pt.get("p"), 3):
                err(f"{at}: p is not three finite numbers")
            if pt.get("wind_a") is not None and not _numbers([pt["wind_a"]], 1):
                err(f"{at}: wind_a is neither null nor a number")
            if "creation_time" in pt and not _numbers([pt["creation_time"]], 1):
                err(f"{at}: creation_time is not a number")
        if isinstance(c.get("color"), list) and not _numbers(c["color"], 3):
            err(f"{where}: color is not three numbers")
        if c.get("anchor2d") is not None and not _numbers(c["anchor2d"], 2):
            err(f"{where}: anchor2d is not two numbers")
        rep["collections"].append({"id": cid, "name": c.get("name"), "points": len(pts)})
        rep["points"] += len(pts)
    return _finish(rep)


def seed_issues(points):
    out = []
    zero = [i for i, p in enumerate(points) if any(c == 0 for c in p)]
    if zero:
        out.append(_issue("zero", f"points {zero[:10]} have a coordinate of exactly 0; vc_grow_seg_from_seed --seed "
                          "then seeds at random instead", "seed_zero"))
    neg = [i for i, p in enumerate(points) if any(c < 0 for c in p)]
    if neg:
        out.append(_issue("negative", f"points {neg[:10]} have a negative coordinate (outside any volume)",
                          "seed_cli"))
    seen, dup = set(), []
    for i, p in enumerate(points):
        t = tuple(p)
        if t in seen:
            dup.append(i)
        seen.add(t)
    if dup:
        out.append(_issue("duplicate", f"points {dup[:10]} repeat an earlier point", "points"))
    return out


def _run_seeds(a):
    points, fmt = read_seeds(a.input, a.collection)
    rep = _report(input=str(a.input), input_format=fmt, to=a.to, points=len(points), written=None)
    for it in seed_issues(points):
        # A negative coordinate is outside every volume. A 0 coordinate only breaks the --seed form (argv); the
        # other targets reach the tracer another way, so there it is a warning.
        fatal = it["rule"] == "negative" or (it["rule"] == "zero" and a.to == "argv")
        rep["errors" if fatal else "warnings"].append(it)
    if a.to == "vc3d":
        doc = vc3d_points(points, a.name)
        back, _ = parse_seeds(json.dumps(doc), "the written point collection")
        if back != points:
            rep["errors"].append(_issue("round_trip", "the written point collection does not read back to the same "
                                        "points", "points"))
        rep["errors"] += check_points(doc)["errors"]
        text = json.dumps(doc, indent=4) + "\n"
    elif a.to == "explicit":
        text = json.dumps({"explicit_seed": points}, indent=1) + "\n"
    elif a.to == "argv":
        if not (a.volume and a.params and a.target):
            raise FormatError("--to argv needs --volume, --params and --target (vc_grow_seg_from_seed's -v, -p, -t)")
        text = "".join(f"vc_grow_seg_from_seed -v {a.volume} -t {a.target} -p {a.params} --seed "
                       f"{p[0]:g} {p[1]:g} {p[2]:g}\n" for p in points)
    else:
        text = "".join(f"{p[0]:g} {p[1]:g} {p[2]:g}\n" for p in points)
    _finish(rep)
    if a.out and rep["ok"]:
        if Path(a.out).exists() and not a.overwrite:
            raise FormatError(f"{a.out} exists; pass --overwrite to replace it")
        _atomic_write(a.out, text)
        rep["written"] = str(a.out)
    rep["output"] = None if a.out else text
    return rep


# ---------------------------------------------------------------- ink labels in villa's naming

def parse_label_name(name):
    """villa's parse_label_asset_path (segment.py:21-49): {prefix, kind, version, extension} or None."""
    p = Path(name)
    ext = p.suffix.lower()
    if ext not in LABEL_EXTS:
        return None
    stem, version = p.stem, 1
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1].startswith("v") and parts[1][1:].isdigit():
        version, stem = int(parts[1][1:]), parts[0]
    for suffix, kind in LABEL_KINDS:
        if stem.endswith(suffix):
            return {"prefix": stem[:-len(suffix)], "kind": kind, "version": version, "extension": ext}
    return None


def zarr_layout(path):
    """Shape and layout of a label zarr from its JSON metadata alone (v2 .zarray or v3 zarr.json, at the root or
    in level 0)."""
    path = Path(path)
    for cand in (path / ".zarray", path / "0" / ".zarray", path / "zarr.json", path / "0" / "zarr.json"):
        if cand.is_file():
            meta = _load_json(cand, "zarr metadata")
            shape = meta.get("shape") if isinstance(meta, dict) else None
            if isinstance(shape, list):
                layout = ("2d" if len(shape) == 2 else
                          "villa-zyx" if len(shape) == 3 and shape[0] == LABEL_DEPTH else f"{len(shape)}d")
                return {"shape": shape, "layout": layout, "array": str(cand.parent.relative_to(path)) or "."}
    return {"shape": None, "layout": "unknown", "array": None}


def find_labels(folder, segment=None, extension=".zarr", version=None):
    """villa's discover_segment_labels (segment.py:52-120) on one folder: every asset, and the selection."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FormatError(f"{folder} is not a folder")
    seg = segment or folder.name
    rep = _report(folder=str(folder), segment=seg, extension=extension, version=version, assets=[],
                  selected=None, other_prefixes=[])
    by_version, by_kind = {}, {k: {} for _, k in LABEL_KINDS}
    others, own_exts = set(), set()
    for p in sorted(folder.iterdir()):
        parsed = parse_label_name(p.name)
        if parsed is None:
            continue
        row = {"name": p.name, **parsed}
        if parsed["extension"] in (".tif", ".tiff") and p.is_file():
            try:
                info = tiff_info(p)
                row.update(width=info["width"], height=info["height"], dtype=info["dtype"], samples=info["samples"])
            except FormatError as exc:
                row["error"] = str(exc)
        elif parsed["extension"] == ".zarr":
            row.update(zarr_layout(p))
        rep["assets"].append(row)
        if parsed["prefix"] != seg:
            others.add(parsed["prefix"])
            continue
        own_exts.add(parsed["extension"])
        if parsed["extension"] != extension.lower():
            continue
        by_version.setdefault(parsed["version"], {})[parsed["kind"]] = row
        by_kind[parsed["kind"]][parsed["version"]] = row
    rep["other_prefixes"] = sorted(others)
    if others:
        rep["warnings"].append(_issue("prefix", f"label files named for {sorted(others)} are not picked for segment "
                                      f"{seg!r}: villa's trainer needs the prefix to equal the segment folder name",
                                      "labels"))
    tiffs = own_exts & {".tif", ".tiff"}
    if extension.lower() != ".zarr":
        rep["warnings"].append(_issue("trainer_zarr", f"listing {extension} files: villa's trainer reads only .zarr "
                                      "labels, so run villa's create_label_zarrs on these TIFFs before training",
                                      "trainer_zarr"))
    elif tiffs and not (by_kind["inklabels"] and by_kind["supervision_mask"]):
        rep["warnings"].append(_issue("tiff_only", f"segment {seg!r} has {'/'.join(sorted(tiffs))} labels but no "
                                      ".zarr pair: villa's trainer reads only .zarr, so run villa's create_label_zarrs "
                                      "on them first", "trainer_zarr"))
    if version:
        chosen = None
        for v, rec in by_version.items():
            if "inklabels" in rec and "supervision_mask" in rec and f"v{v}" == version:
                chosen = rec
        if chosen is None:
            rep["errors"].append(_issue("version", f"no {extension} inklabels and supervision_mask pair at version "
                                        f"{version}", "labels"))
        else:
            rep["selected"] = {k: chosen[k]["name"] if k in chosen else None for _, k in LABEL_KINDS}
    else:
        for need in ("inklabels", "supervision_mask"):
            if not by_kind[need]:
                rep["errors"].append(_issue("missing", f"no {need} {extension} file for segment {seg!r}; villa's "
                                            "trainer requires one", "labels"))
        rep["selected"] = {k: by_kind[k][max(by_kind[k])]["name"] if by_kind[k] else None for _, k in LABEL_KINDS}
        vs = {k: max(by_kind[k]) for _, k in LABEL_KINDS if by_kind[k]}
        if len(set(vs.values())) > 1:
            rep["warnings"].append(_issue("mixed_versions", f"without a version the trainer takes each kind's newest "
                                          f"file independently: {vs}", "labels"))
    sel = [r for r in rep["assets"] if rep["selected"] and r["name"] in rep["selected"].values()]
    sizes = {(r.get("width"), r.get("height")) for r in sel if r.get("width")}
    shapes = {tuple(r["shape"]) for r in sel if r.get("shape")}
    if len(sizes) > 1 or len(shapes) > 1:
        rep["errors"].append(_issue("shape", "the selected label files differ in size", "labels"))
    for r in sel:
        if r.get("samples", 1) != 1:
            rep["warnings"].append(_issue("samples", f"{r['name']} has {r['samples']} samples; villa's converter "
                                          "keeps the first", "labels"))
        if r.get("layout") not in (None, "2d", "villa-zyx"):
            rep["warnings"].append(_issue("layout", f"{r['name']} has shape {r.get('shape')}, neither 2D nor villa's "
                                          f"({LABEL_DEPTH}, H, W)", "label_zarr"))
    return _finish(rep)


def export_labels(ink, supervision, segment, out, validation=None, version=None, overwrite=False):
    """Copy a label pair (and an optional validation mask) to villa's names under out/; checks sizes first."""
    if not segment or "/" in segment or segment in (".", ".."):
        raise FormatError(f"segment {segment!r} is not a folder name")
    srcs = {"inklabels": Path(ink), "supervision_mask": Path(supervision)}
    if validation:
        srcs["validation_mask"] = Path(validation)
    rep = _report(segment=segment, out=str(out), files={}, written=False)
    infos = {}
    for kind, p in srcs.items():
        if p.suffix.lower() not in (".tif", ".tiff"):
            raise FormatError(f"{p}: export copies TIFF labels; convert other formats first")
        infos[kind] = tiff_info(p)
    sizes = {(i["width"], i["height"]) for i in infos.values()}
    if len(sizes) > 1:
        rep["errors"].append(_issue("shape", "the label files differ in size: " + ", ".join(
            f"{k} {i['width']}x{i['height']}" for k, i in infos.items()), "labels"))
    for kind, i in infos.items():
        if i["samples"] != 1:
            rep["warnings"].append(_issue("samples", f"{kind} has {i['samples']} samples; villa's converter keeps "
                                          "the first", "labels"))
        if i["dtype"] not in ("uint8", "uint16"):
            rep["warnings"].append(_issue("dtype", f"{kind} is {i['dtype']}; villa writes uint8 labels "
                                          "(the trainer reads > 0)", "labels"))
    vtag = f"_v{int(version)}" if version else ""
    names = {k: f"{segment}_{k}{vtag}.tif" for k in srcs}
    for k, n in names.items():
        parsed = parse_label_name(n)
        if not parsed or parsed["prefix"] != segment or parsed["kind"] != k or parsed["version"] != (version or 1):
            rep["errors"].append(_issue("name", f"{n} would not parse back as segment {segment!r} {k}", "labels"))
    rep["files"] = {k: str(Path(out) / n) for k, n in names.items()}
    if rep["errors"]:
        return _finish(rep)
    out = Path(out)
    for k, n in names.items():
        if (out / n).exists() and not overwrite:
            raise FormatError(f"{out / n} exists; pass --overwrite to replace it")
    out.mkdir(parents=True, exist_ok=True)
    for k, n in names.items():
        shutil.copyfile(srcs[k], out / n)
    rep["written"] = True
    rep["next"] = ["villa: uv run --extra models python -m vesuvius.ink_detection.preprocessing.create_label_zarrs "
                   "ROOT (ROOT holds the segment folders; villa's trainer reads only .zarr labels)",
                   f"python3 -m kit.villafmt labels find {out}"]
    return _finish(rep)


# ---------------------------------------------------------------- command line

def _emit(rep, out=None):
    text = json.dumps(rep, indent=1, default=str)
    if out:
        _atomic_write(out, text + "\n")
    else:
        print(text)
    return 0 if rep["ok"] else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m kit.villafmt", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("tifxyz", help="check tifxyz folders (or folders of them) as VC3D's loader reads them")
    t.add_argument("dirs", nargs="+", help="tifxyz folders, or folders holding tifxyz folders")
    t.add_argument("--no-pixels", action="store_true", help="headers and meta.json only (no numpy needed)")
    t.add_argument("--report", help="write the JSON report here instead of printing it")

    pr = sub.add_parser("project", help="write or check a VC3D project file (*.volpkg.json)")
    pr.add_argument("out", nargs="?", help="the project file to write, named *.volpkg.json")
    pr.add_argument("--check", metavar="FILE", help="check an existing project file instead of writing one")
    pr.add_argument("--volume", action="append", help="local OME-Zarr folder or remote .zarr URL (repeatable; "
                    "the first is listed first)")
    pr.add_argument("--segments", action="append", help="a folder of tifxyz folders, or one tifxyz folder "
                    "(repeatable)")
    pr.add_argument("--normal-grids", action="append", help="a local normal-grid folder (repeatable)")
    pr.add_argument("--umbilicus", help="umbilicus JSON (control_points), such as an AutoPipeline run's umbilicus.json")
    pr.add_argument("--output-segments", help="folder where VC3D writes new segments")
    pr.add_argument("--from-autopipe", metavar="RUN", help="take volumes, traces/ and umbilicus.json from an "
                    "AutoPipeline run folder (explicit options win)")
    pr.add_argument("--name", help="project name (default: the file name)")
    pr.add_argument("--anonymous", action="store_true", help=f"tag remote volumes {ANON_TAG} (public buckets)")
    pr.add_argument("--voxel-um", type=float, help="tag the first remote volume with its voxel size")
    pr.add_argument("--pixels", action="store_true", help="also run the tifxyz pixel checks on every segment")
    pr.add_argument("--overwrite", action="store_true")
    pr.add_argument("--report", help="write the JSON report here instead of printing it")

    ik = sub.add_parser("inkmap", help="show an ink map under a segment in VC3D's Ink Detection overlay")
    iks = ik.add_subparsers(dest="action", required=True)
    ia = iks.add_parser("add", help="register MAP in SEGDIR/ink-detections.json")
    ia.add_argument("segdir", help="the tifxyz segment folder the map was rendered from")
    ia.add_argument("map", help="the ink map: TIFF, PNG or JPEG covering the segment's whole render canvas")
    ia.add_argument("--label", help="name shown in VC3D (default: segment - map file stem)")
    ia.add_argument("--artifact-type", default="ink detection", help="artifact_type field (default: ink detection)")
    ia.add_argument("--sample-id", help="sample_id field (default empty)")
    ia.add_argument("--source-url", help="original_source_uri field")
    ia.add_argument("--copy", action="store_true", help="copy the map into SEGDIR/ink/ so the folder travels whole")
    ia.add_argument("--overwrite", action="store_true", help="with --copy, replace a different file of that name")
    ia.add_argument("--expect-size", nargs=2, type=int, metavar=("W", "H"),
                    help="also refuse a map that is not exactly W x H pixels (the aspect check alone passes a crop, "
                         "a turned map or another segment's map of the same aspect)")
    ia.add_argument("--report", help="write the JSON report here instead of printing it")
    ic = iks.add_parser("check", help="check SEGDIR/ink-detections.json as VC3D reads it")
    ic.add_argument("segdir")
    ic.add_argument("--report", help="write the JSON report here instead of printing it")

    pd = sub.add_parser("preds", help="ink maps as villa's own prediction files (SEGDIR/preds/)")
    pds = pd.add_subparsers(dest="action", required=True)
    pe = pds.add_parser("export", help="write MAP as SEGDIR/preds/<seg>_<model>_<direction>_<ddmmyy>.tif, villa's "
                        "uint8 tiled LZW Big TIFF")
    pe.add_argument("map", help="the ink map: .npy, TIFF, PNG or JPEG, one 2D image covering the segment")
    pe.add_argument("--segment", required=True, metavar="SEGDIR",
                    help="the segment folder: the file goes to SEGDIR/preds/ and carries SEGDIR's folder name, as "
                         "villa's folder inference names it")
    pe.add_argument("--model", required=True, metavar="NAME",
                    help="the model's checkpoint stem, as villa names predictions (a checkpoint path gives its stem)")
    pe.add_argument("--direction", required=True, choices=PRED_DIRECTIONS,
                    help="the layer order the map was inferred in (villa's merge groups files by it)")
    pe.add_argument("--scale", choices=PRED_SCALES, default="auto",
                    help="prob: floats 0 to 1, encoded as villa does (clip, times 255, truncate); u8: values already "
                         "0 to 255; minmax: stretch the map's own minimum to maximum; auto (default): prob for "
                         "floats in 0 to 1 or booleans, u8 for integers in 0 to 255, else refused")
    pe.add_argument("--date", metavar="DDMMYY", help="the date in the name (default: today, local time, as villa)")
    pe.add_argument("--output-prefix", default="", help="villa's --output-prefix: the name starts PREFIX_")
    pe.add_argument("--tile", type=int, default=PRED_TILE,
                    help=f"tile edge in pixels, a multiple of 16 (default {PRED_TILE}; villa uses the model's patch "
                         "size)")
    pe.add_argument("--register", action="store_true",
                    help="also add the file to SEGDIR/ink-detections.json for VC3D's Ink Detection overlay, through "
                         "inkmap add (SEGDIR must then be a tifxyz segment)")
    pe.add_argument("--label", help="with --register: the name VC3D shows (default: segment - file stem)")
    pe.add_argument("--expect-size", nargs=2, type=int, metavar=("W", "H"),
                    help="refuse a map that is not exactly W x H pixels")
    pe.add_argument("--overwrite", action="store_true", help="replace a prediction of the same name")
    pe.add_argument("--report", help="write the JSON report here instead of printing it")

    s = sub.add_parser("seeds", help="convert seed points between formats")
    s.add_argument("input", help="seeds.json, explicit_seed JSON, VC3D point collections, meta.json or text")
    s.add_argument("--to", choices=("vc3d", "explicit", "argv", "text"), default="vc3d",
                   help="VC3D point collections (default), villa's explicit_seed JSON, vc_grow_seg_from_seed calls, "
                        "or x y z lines")
    s.add_argument("--out", help="write the converted points here (default: in the JSON report's output field)")
    s.add_argument("--name", default="seeds", help="collection name for --to vc3d")
    s.add_argument("--collection", help="read only this collection of a VC3D point file")
    s.add_argument("--volume", help="--to argv: the OME-Zarr volume (-v)")
    s.add_argument("--params", help="--to argv: the tracer parameter JSON (-p)")
    s.add_argument("--target", help="--to argv: the output folder (-t)")
    s.add_argument("--overwrite", action="store_true")
    s.add_argument("--report", help="write the JSON report here instead of printing it")

    lb = sub.add_parser("labels", help="ink label files in villa's naming")
    lbs = lb.add_subparsers(dest="action", required=True)
    lf = lbs.add_parser("find", help="list label files and what villa's trainer would pick")
    lf.add_argument("folder", help="a segment folder holding <seg>_inklabels.* and friends")
    lf.add_argument("--segment", help="segment name (default: the folder name, as villa's trainer uses)")
    lf.add_argument("--extension", default=".zarr", choices=(".zarr", ".tif", ".tiff"),
                    help="which extension to list (default .zarr; villa's trainer reads only .zarr)")
    lf.add_argument("--version", help="an explicit label version such as v2")
    lf.add_argument("--report", help="write the JSON report here instead of printing it")
    le = lbs.add_parser("export", help="copy TIFF labels to villa's names")
    le.add_argument("--ink", required=True, help="ink label TIFF (an inklabels.tif on the segment's canvas)")
    le.add_argument("--supervision", required=True, help="supervision mask TIFF")
    le.add_argument("--validation", help="validation mask TIFF")
    le.add_argument("--segment", required=True, help="the segment folder name the trainer will see")
    le.add_argument("--out", required=True, help="the folder to write into (usually the segment folder)")
    le.add_argument("--version", type=int, help="write _vN names (default: unversioned, which villa reads as v1)")
    le.add_argument("--overwrite", action="store_true")
    le.add_argument("--report", help="write the JSON report here instead of printing it")

    a = p.parse_args(argv)
    try:
        if a.cmd == "tifxyz":
            reps = []
            for d in a.dirs:
                segs = find_segments(d) or [Path(d)]
                reps.extend(check_tifxyz(sg, pixels=not a.no_pixels) for sg in segs)
            rep = _report(segments=reps, checked=len(reps), failing=[r["path"] for r in reps if not r["ok"]])
            rep["errors"] = [dict(e, path=r["path"]) for r in reps for e in r["errors"]]
            rep["warnings"] = [dict(w, path=r["path"]) for r in reps for w in r["warnings"]]
            return _emit(_finish(rep), a.report)
        if a.cmd == "project":
            return _emit(_run_project(a), a.report)
        if a.cmd == "inkmap":
            return _emit(_run_inkmap_add(a) if a.action == "add" else check_inkmaps(a.segdir), a.report)
        if a.cmd == "preds":
            return _emit(export_pred(a.map, a.segment, a.model, a.direction, scale=a.scale, date=a.date,
                                     prefix=a.output_prefix, tile=a.tile, register=a.register, label=a.label,
                                     expect_size=a.expect_size, overwrite=a.overwrite), a.report)
        if a.cmd == "seeds":
            return _emit(_run_seeds(a), a.report)
        if a.cmd == "labels":
            if a.action == "find":
                return _emit(find_labels(a.folder, a.segment, a.extension, a.version), a.report)
            return _emit(export_labels(a.ink, a.supervision, a.segment, a.out, a.validation, a.version,
                                       a.overwrite), a.report)
    except (FormatError, OSError) as exc:
        print(f"kit villafmt: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
