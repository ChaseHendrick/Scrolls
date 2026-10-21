"""Ink Lens client: a control-checked ink map of one region of a VC3D segment, written back as VC3D's own files.

  python3 inklens.py estimate 1024 1024 [--windows 3] [--reader d9v2]
  python3 inklens.py samples
  python3 inklens.py demo 0841-w00 [--local | --space OWNER/NAME] [--size 640] [--vc3d-out DIR] [--score] [--json]
  python3 inklens.py run --segment SEGDIR (--surface-volume PATH | --volume OME_ZARR) --box X Y W H
                         [--um-per-px UM] [--local | --space OWNER/NAME] [--reader d9v2|ink_9um|both]
                         [--windows 3|1] [--no-pins] [--letter-mm 3.0] [--bridge [NAME]] [--dry-run] [--json]
  python3 inklens.py run --from-vc3d [--bridge NAME] --volume OME_ZARR --size 1024 ...
  python3 inklens.py run --segment SEGDIR --volume OME_ZARR --crop Y0 Y1 X0 X1 --local --offline --out RUN
                         (the tool registry's route: writes only into RUN, never downloads)

What run does, in order, stopping at the first refusal (exit 2):
  1. reads the region: from a surface volume that covers the segment (zarr, .npy, .npz or .tif, layers first), or
     by rendering only the region with vc_render_tifxyz (--volume; the binary ships with VC3D);
  2. pools it to about 9.6 um (2.4 um renders: 4 x 4 x 4 mean, as the organizers' prepare_9um_isotropic_input.py);
  3. runs the ink model in both depth orders over three depth windows: on a Hugging Face ZeroGPU Space with your own
     token, so your own ZeroGPU quota pays (--space, the default), or on this machine (--local: CUDA, Apple MPS or
     CPU, no account);
  4. applies the control-set threshold (gate.py) and recomputes it here from the returned maps;
  5. reads the kept map with the Scroll Text Reader (kit/letterread.py), its reverse-depth twin as the control map;
  6. writes into SEGDIR: inklens/<run>.png (the whole segment canvas, transparent except kept ink), inklens/mosaic.png
     (every run on this segment so far), records for both in ink-detections.json (existing records kept),
     inklens/<run>.pins.json (a VC3D point collection) and inklens/<run>.json (the receipt).
     With --bridge, the pins are merged into VC3D's current point collections and the view centers on the region.

With --out RUN (local mode only) step 6 writes into RUN instead and leaves SEGDIR untouched: inklens.tif and
inklens_reverse.tif (the kept ink and the reverse-depth control's kept ink, 8-bit, whole canvas), inklens.pins.json,
inklens.letters.json and inklens.json; VC3D loads them through the tool registry (python -m kit tools).

Exit codes: 0 ink or weak (and with --out, any status once the files are written), 3 none or too_small, 2 refused.
Everything it writes is model output, not a reading.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import engine  # noqa: E402
import gate  # noqa: E402
import vc3dout  # noqa: E402
import volio  # noqa: E402

VERSION = engine.VERSION
DEFAULT_SPACE = os.environ.get("INKLENS_SPACE", "SharpMeow/ink-lens")
SAMPLES_FILE = HERE / "samples.json"
EXIT_OK, EXIT_REFUSED, EXIT_NONE = 0, 2, 3
MAX_UPLOAD_BYTES = 64 << 20
LETTER_MM = 3.0
READER_WEIGHTS = "letters-v2-ccby"
NOTE = "Model output, not a reading."


class Refused(Exception):
    """A request Ink Lens refuses; the message says why (exit 2)."""


# ---------------------------------------------------------------- samples

def load_samples(path=SAMPLES_FILE):
    data = json.loads(Path(path).read_text())
    if data.get("bucket") != volio.BUCKET:
        raise Refused(f"samples must come from {volio.BUCKET}")
    seen = set()
    for s in data["samples"]:
        if s["id"] in seen:
            raise Refused(f"sample {s['id']} is listed twice")
        seen.add(s["id"])
        for part in ("surface_volume", "labels"):
            v = s.get(part, "")
            if not v or "://" in v or v.startswith("/") or ".." in v.split("/"):
                raise Refused(f"{s['id']}: {part} must be a plain path inside the segment")
        H, W = s["surface_shape"]
        y0, y1, x0, x1 = s["crop"]
        if not (0 <= y0 < y1 <= H and 0 <= x0 < x1 <= W):
            raise Refused(f"{s['id']}: crop {s['crop']} is outside the {H} x {W} surface")
    return data


def sample_by(key, data=None):
    data = data or load_samples()
    for s in data["samples"]:
        if key in (s["id"], s["title"]):
            return s
    raise Refused(f"no sample {key!r}; the samples are {', '.join(x['id'] for x in data['samples'])}")


def sample_url(s, part="surface_volume"):
    return f"{volio.BUCKET}/{s['scroll']}/segments/{s['segment']}/{s[part]}"


def sample_box(s, size=None, at=None):
    """(y0, y1, x0, x1): the sample's crop, a size x size square at its center, or at a given (y0, x0)."""
    y0, y1, x0, x1 = (int(v) for v in s["crop"])
    if at is not None:
        H, W = s["surface_shape"]
        size = int(size or (y1 - y0))
        y, x = int(at[0]), int(at[1])
        if not (0 <= y and 0 <= x and y + size <= H and x + size <= W):
            raise Refused(f"a {size} px region at rows {y}, columns {x} is outside the {H} x {W} surface")
        return y, y + size, x, x + size
    if size is None:
        return y0, y1, x0, x1
    size = int(size)
    if not engine.MIN_SIDE <= size <= min(y1 - y0, x1 - x0):
        raise Refused(f"size {size}: use {engine.MIN_SIDE} to {min(y1 - y0, x1 - x0)} px for {s['id']}")
    top, left = (y0 + y1) // 2 - size // 2, (x0 + x1) // 2 - size // 2
    return top, top + size, left, left + size


def read_sample(s, box):
    y0, y1, x0, x1 = box
    data, info = volio.read_region(sample_url(s), (y0, x0, y1 - y0, x1 - x0))
    return volio.to_uint8(data), info


def labels_for(s, box, shape):
    """Ink and supervision on the region's grid, through kit.auc (needs kit and zarr)."""
    kit = find_kit()
    if kit is None:
        raise Refused("label scoring needs this repository's kit/ (and zarr)")
    from kit import auc, fetch
    with tempfile.TemporaryDirectory(prefix="inklens-labels-") as tmp:
        fetch.fetch_prefix(f"{s['scroll']}/segments/{s['segment']}/{s['labels']}", tmp)
        return auc.labels_on_map(Path(tmp) / "inklabels.zarr", Path(tmp) / "supervision.zarr", "2",
                                 tuple(s["surface_shape"]), tuple(box), tuple(shape))


# ---------------------------------------------------------------- the lens: model, gate, letters

def find_kit():
    """Put this repository's kit/ on sys.path if Ink Lens runs from inside it; returns the root or None."""
    for folder in (HERE, *HERE.parents):
        if (folder / "kit" / "__init__.py").is_file():
            if str(folder) not in sys.path:
                sys.path.insert(0, str(folder))
            return folder
    return None


def ct_middle(volume):
    return volume[volume.shape[0] // 2]


def analyze(F, R, volume, min_papyrus=gate.MIN_PAPYRUS):
    """The gate on one region's maps: decision, kept map (float) and the control's own kept map."""
    import numpy as np
    ct = ct_middle(volume)
    d = gate.decide(F, R, ct, min_papyrus=min_papyrus)
    kept = gate.kept(F, d, ct)
    kept_r = np.zeros_like(kept)
    if d["status"] in ("ink", "weak"):
        m = gate.papyrus(ct) & (R > d["threshold"])
        kept_r[m] = R[m]
    return d, kept, kept_r


_ENGINE = {}


def local_engine(names):
    key = tuple(sorted(names))
    if key not in _ENGINE:
        _ENGINE[key] = engine.Engine(readers=names)
    return _ENGINE[key]


def run_local(volume, reader="d9v2", windows=3, device=None):
    eng = local_engine(engine.readers_of(reader))
    out = eng.run(volume, reader=reader, windows=windows, device=device)
    out["engine"] = eng.describe()
    out["where"] = "local"
    return out


def hf_token(explicit=None):
    """The user's own Hugging Face token (so ZeroGPU bills their quota): --token, HF_TOKEN, or `hf auth login`'s."""
    if explicit:
        return explicit
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    try:
        from huggingface_hub import get_token
        return get_token()
    except Exception:  # noqa: BLE001  (no huggingface_hub, or no stored token)
        return None


def pack_volume(volume, path):
    import numpy as np
    np.savez_compressed(path, volume=volume)
    size = Path(path).stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise Refused(f"the region packs to {size / 2 ** 20:.1f} MB; the Space takes at most "
                      f"{MAX_UPLOAD_BYTES >> 20} MB. Use a smaller region or --local")
    return path


def unpack_maps(path):
    import numpy as np
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def run_space(volume, space=DEFAULT_SPACE, reader="d9v2", windows=3, token=None, client_factory=None):
    """One call to the Ink Lens Space with the user's own token. Returns the run dict (maps as float32)."""
    tok = hf_token(token)
    if not tok:
        raise Refused("Space mode runs on your own ZeroGPU quota, so it needs your Hugging Face token: run "
                      "'hf auth login' or set HF_TOKEN (a read token is enough). Or use --local to run on this machine")
    if client_factory is None:
        try:
            from gradio_client import Client, handle_file
        except ImportError:
            raise Refused("Space mode needs gradio_client (pip install gradio_client), or use --local") from None
        import inspect
        kw = "hf_token" if "hf_token" in inspect.signature(Client).parameters else "token"

        def client_factory(src):
            return Client(src, **{kw: tok}, verbose=False), handle_file
    with tempfile.TemporaryDirectory(prefix="inklens-up-") as tmp:
        packed = pack_volume(volume, Path(tmp) / "region.npz")
        client, handle = client_factory(space)
        t0 = time.time()
        result, maps_file = client.predict(handle(str(packed)), reader, int(windows), api_name="/lens_region")[:2]
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict) or result.get("error"):
            raise Refused(f"the Space refused the region: {result.get('error') if isinstance(result, dict) else result}")
        maps = unpack_maps(maps_file if isinstance(maps_file, str) else maps_file["path"])
    run = {"forward": maps["forward"].astype("float32"), "reverse": maps["reverse"].astype("float32"),
           "where": f"space {space}", "space_result": result, "round_trip_s": round(time.time() - t0, 2)}
    run.update({k: result.get(k) for k in ("readers", "windows", "patches", "device", "device_name", "seconds",
                                           "gpu_seconds_requested", "engine")})
    return run


def check_space_gate(run, decision):
    """The Space's own gate must agree with the gate recomputed here from the maps it returned."""
    theirs = (run.get("space_result") or {}).get("gate")
    if theirs is None:
        return
    if theirs.get("status") != decision["status"]:
        raise Refused(f"the Space says {theirs.get('status')!r} but its own maps give {decision['status']!r} here; "
                      "nothing is written")


def letters(kept, kept_r, um_per_px, letter_mm=LETTER_MM, weights=READER_WEIGHTS):
    """The Scroll Text Reader on the kept map, the control's own kept map as its control map. None without kit.
    With downloads off (engine.offline()), weights that are not cached yet skip the pins instead of downloading."""
    if find_kit() is None:
        return None, "no kit/ next to Ink Lens: letter pins need this repository"
    from kit import letterread
    if not kept.any():
        return None, "nothing kept, so nothing to read"
    if engine.offline():
        try:
            weights = str(letterread.resolve_weights(weights, download=False))
        except (OSError, ValueError) as exc:
            return None, f"letter weights not cached and downloads are off: {exc}"
    lp = letterread.letter_px_from_units(letter_mm, um_per_px)
    res = letterread.read(kept, weights, letter_px=lp, control=kept_r, orientation=False)
    return res, None


def letter_points(res, box_render, pool):
    """Kept letters of a strong or weak read as render-pixel centers (row, column), with glyph and confidence."""
    if not res or res.get("control", {}).get("status") not in ("strong", "weak"):
        return []
    out = []
    for line in res.get("lines", []):
        for L in line.get("letters", []):
            if not L.get("kept"):
                continue
            y0, y1, x0, x1 = L["box"]
            out.append({"row": box_render[0] + (y0 + y1) / 2 * pool, "col": box_render[1] + (x0 + x1) / 2 * pool,
                        "glyph": L["glyph"], "p": L["p"]})
    return out


# ---------------------------------------------------------------- VC3D files

def run_id(reader, box):
    return f"{time.strftime('%Y%m%dT%H%M%S')}-{reader}-y{int(box[0])}-x{int(box[1])}"


def write_vc3d(segdir, rid, box_render, pool, kept_u8, decision, receipt, pins=None, xyz=None):
    """Write the run's files into the segment folder; returns their paths and the pins' voxel points."""
    seg = vc3dout.segment(segdir)
    out_dir = Path(segdir) / "inklens"
    canvas, div = vc3dout.canvas(seg, box_render, kept_u8, pool)
    png = vc3dout.png_bytes(canvas)
    run_png = vc3dout.atomic_write(out_dir / f"{rid}.png", png)
    mosaic, merged = vc3dout.merge_mosaic(out_dir / "mosaic.png", canvas)
    mosaic_png = vc3dout.atomic_write(out_dir / "mosaic.png", vc3dout.png_bytes(mosaic))
    sha = hashlib.sha256(png).hexdigest()
    label = f"Ink Lens {receipt['reader']} {decision['status']} y{int(box_render[0])} x{int(box_render[1])}"
    recs = [vc3dout.record(seg, f"inklens/{rid}.png", label, sha, canvas.shape[::-1],
                           {"status": decision["status"], "excess": decision["excess"], "run": rid}),
            vc3dout.record(seg, "inklens/mosaic.png", "Ink Lens mosaic (all runs)",
                           hashlib.sha256(mosaic_png.read_bytes()).hexdigest(), mosaic.shape[::-1])]
    rec_info = vc3dout.merge_records(segdir, recs)
    files = {"png": str(run_png), "mosaic": str(mosaic_png), "records": rec_info["file"]}
    voxels = []
    if pins:
        if xyz is None:
            xyz = vc3dout.load_xyz(segdir)
        for p in pins:
            gr, gc = vc3dout.render_to_grid(seg, p["row"], p["col"])
            v = vc3dout.grid_to_voxel(xyz, gr, gc)
            if v is not None:
                voxels.append(v)
        if voxels:
            doc = vc3dout.points_doc(f"Ink Lens {rid}", voxels, metadata={"ink_lens_run": rid})
            files["pins"] = str(vc3dout.atomic_write(out_dir / f"{rid}.pins.json", json.dumps(doc, indent=1) + "\n"))
    receipt = dict(receipt, files=files, canvas_size=list(canvas.shape[::-1]), canvas_divisor=div,
                   mosaic_merged=merged, pins_written=len(voxels), segment_key=seg["key"])
    files["receipt"] = str(vc3dout.atomic_write(out_dir / f"{rid}.json", json.dumps(receipt, indent=1) + "\n"))
    return files, voxels


def write_run_folder(out, segdir, box_render, pool, kept_u8, kept_r_u8, decision, receipt, pins=None, xyz=None,
                     letters_doc=None):
    """--out: the run's files in OUT only (the tool registry's run folder), never in the segment folder: inklens.tif
    and inklens_reverse.tif (the kept ink and its reverse-depth control's kept ink, 8-bit, on the whole segment canvas,
    0 elsewhere; VC3D draws 0 as transparent), inklens.pins.json (a VC3D point collection, when pins were placed),
    inklens.letters.json and inklens.json (the receipt). Returns their paths and the pins' voxel points."""
    import tifffile
    seg = vc3dout.segment(segdir)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    canvas, div = vc3dout.canvas(seg, box_render, kept_u8, pool)
    canvas_r, _ = vc3dout.canvas(seg, box_render, kept_r_u8, pool)
    files = {}
    for key, name, img in (("map", "inklens.tif", canvas), ("reverse", "inklens_reverse.tif", canvas_r)):
        tmp = out / (name + ".part")
        tifffile.imwrite(tmp, img)
        os.replace(tmp, out / name)
        files[key] = str(out / name)
    voxels = []
    if pins:
        xyz = vc3dout.load_xyz(segdir) if xyz is None else xyz
        for p in pins:
            v = vc3dout.grid_to_voxel(xyz, *vc3dout.render_to_grid(seg, p["row"], p["col"]))
            if v is not None:
                voxels.append(v)
        if voxels:
            doc = vc3dout.points_doc(f"Ink Lens {receipt.get('run', '')}".strip(), voxels,
                                     metadata={"ink_lens_run": receipt.get("run")})
            files["pins"] = str(vc3dout.atomic_write(out / "inklens.pins.json", json.dumps(doc, indent=1) + "\n"))
    if letters_doc:
        files["letters"] = str(vc3dout.atomic_write(out / "inklens.letters.json", json.dumps(letters_doc, indent=1)))
    receipt = dict(receipt, files=files, canvas_size=list(canvas.shape[::-1]), canvas_divisor=div,
                   pins_written=len(voxels), segment_key=seg["key"], segment=seg["dir"],
                   wrote_into_segment=False)
    files["receipt"] = str(vc3dout.atomic_write(out / "inklens.json", json.dumps(receipt, indent=1) + "\n"))
    return files, voxels


def bridge_push(name, pins_path, center):
    """Merge the pins into VC3D's current point collections (save, merge, load) and center the view."""
    import bridge
    path = bridge.discover(name)
    with bridge.Bridge(path) as br, tempfile.TemporaryDirectory(prefix="inklens-points-") as tmp:
        cur = Path(tmp) / "current.json"
        br.call("points.save_json", {"path": str(cur)})
        existing = json.loads(cur.read_text()) if cur.is_file() and cur.stat().st_size else None
        merged = vc3dout.merge_points(existing, json.loads(Path(pins_path).read_text()))
        out = Path(tmp) / "merged.json"
        out.write_text(json.dumps(merged))
        br.call("points.load_json", {"path": str(out)})
        if center:
            br.call("viewer.center_on_point", {"point": {"x": center[0], "y": center[1], "z": center[2]}})
    return {"bridge": path, "collections": len(merged["collections"])}


# ---------------------------------------------------------------- reading a region of a segment

def ome_voxel_um(path):
    """The level-0 voxel size in micrometers from an OME-Zarr's multiscales, or None."""
    try:
        raw = volio._read(str(path).rstrip("/"), ".zattrs")
        a = json.loads(raw or b"{}")
        ms = a["multiscales"][0]
        scale = ms["datasets"][0]["coordinateTransformations"][0]["scale"]
        unit = (ms.get("axes") or [{}])[-1].get("unit", "micrometer")
        f = {"micrometer": 1.0, "nanometer": 1e-3, "millimeter": 1e3}.get(unit, 1.0)
        return float(scale[-1]) * f
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, volio.VolumeError):
        return None


def render_region(segdir, volume, box_render, layers, binary=None, timeout_min=20):
    """vc_render_tifxyz on just the region (crop flags), uncompressed zarr in a temporary folder; the array."""
    exe = binary or shutil.which("vc_render_tifxyz")
    if not exe:
        raise Refused("vc_render_tifxyz is not on PATH (it ships with VC3D builds); give --render-binary, or render "
                      "the segment's surface volume yourself and pass --surface-volume")
    y, x, h, w = box_render
    with tempfile.TemporaryDirectory(prefix="inklens-render-") as tmp:
        out = Path(tmp) / "region.zarr"
        cmd = [exe, "--volume", str(volume), "--group-idx", "0", "--scale", "1", "--segmentation", str(segdir),
               "--num-slices", str(layers), "--crop-x", str(x), "--crop-y", str(y), "--crop-width", str(w),
               "--crop-height", str(h), "--zarr-output", str(out), "--zarr-compressor", "none", "--pyramid", "0",
               "--timeout", str(timeout_min)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise Refused(f"vc_render_tifxyz failed ({p.returncode}): {(p.stderr or p.stdout)[-600:]}")
        arr = volio.open_zarr(out)
        data = arr.read((0, arr.shape[0]), (0, arr.shape[1]), (0, arr.shape[2]))
    return data, {"render": " ".join(cmd[:1] + [c if c != str(out) else "TMP/region.zarr" for c in cmd[1:]])}


# ---------------------------------------------------------------- commands

def emit(obj, as_json):
    if as_json:
        print(json.dumps(obj, indent=1, default=str))
    else:
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v, default=str)
            print(f"{k}: {v}")


def exit_for(status):
    return EXIT_OK if status in ("ink", "weak") else EXIT_NONE


def lens(volume, args):
    if args.local:
        return run_local(volume, args.reader, args.windows, device=getattr(args, "device", None))
    return run_space(volume, args.space, args.reader, args.windows, token=getattr(args, "token", None))


def cmd_estimate(a):
    emit(engine.estimate(a.height, a.width, a.windows, a.reader), a.json)
    return EXIT_OK


def cmd_samples(a):
    emit({"samples": [{k: s[k] for k in ("id", "title", "role", "crop")} for s in load_samples()["samples"]]}, True)
    return EXIT_OK


def cmd_demo(a):
    """A public sample end to end: read, lens, gate, letters; with --vc3d-out, VC3D's files into a downloaded copy
    of the sample's tifxyz mesh."""
    s = sample_by(a.sample)
    box = sample_box(s, a.size, a.at)
    est = engine.estimate(box[1] - box[0], box[3] - box[2], a.windows, a.reader)
    if a.dry_run:
        emit({"sample": s["id"], "box": box, "estimate": est}, a.json)
        return EXIT_OK
    volume, src = read_sample(s, box)
    run = lens(volume, a)
    decision, kept, kept_r = analyze(run["forward"], run["reverse"], volume)
    check_space_gate(run, decision)
    out = {"sample": s["id"], "role": s["role"], "box": list(box), "where": run["where"], "gate": decision,
           "patches": run.get("patches"), "seconds": run.get("seconds"), "device": run.get("device"), "note": NOTE}
    if a.score:
        ink, sup = labels_for(s, box, run["forward"].shape)
        from kit import auc
        out["labels"] = {"shares": gate.label_shares(kept, ink, sup),
                         "auc_forward": auc.score_array(run["forward"], ink, sup, inner=64)["auc"],
                         "auc_reverse": auc.score_array(run["reverse"], ink, sup, inner=64)["auc"]}
    res, why = (None, "skipped (--no-pins)") if a.no_pins else letters(kept, kept_r, s["um_per_px"], a.letter_mm)
    out["letters"] = summarize_letters(res, why)
    if a.vc3d_out:
        if not s.get("tifxyz"):
            raise Refused(f"sample {s['id']} has no tifxyz mesh listed; pick one that does for --vc3d-out")
        segdir = fetch_tifxyz(s, Path(a.vc3d_out))
        box_render = (box[0], box[2], box[1] - box[0], box[3] - box[2])     # (y, x, h, w)
        rid = run_id(a.reader, box_render)
        receipt = make_receipt(run, decision, a, box_render=box_render, pool=1,
                               source={"sample": s["id"], **src}, letters=out["letters"])
        pins = letter_points(res, box_render, 1)
        files, voxels = write_vc3d(segdir, rid, box_render, 1, gate.to_u8(kept), decision, receipt, pins)
        out["vc3d"] = {"segment": str(segdir), "files": files, "pins": len(voxels)}
        if res:
            vc3dout.atomic_write(Path(segdir) / "inklens" / f"{rid}.letters.json", json.dumps(res, indent=1))
    if a.save_maps:
        import numpy as np
        np.savez_compressed(a.save_maps, forward=run["forward"], reverse=run["reverse"], kept=kept,
                            ct=ct_middle(volume))
    emit(out, a.json)
    return exit_for(decision["status"])


def fetch_tifxyz(s, dest):
    """Copy a public sample's tifxyz mesh (meta.json and the x, y, z bands, about 0.6 MB) into dest/<name>."""
    name = s["tifxyz"].rstrip("/").split("/")[-1]
    segdir = Path(dest) / name
    segdir.mkdir(parents=True, exist_ok=True)
    for f in ("meta.json", "x.tif", "y.tif", "z.tif"):
        target = segdir / f
        if not target.is_file():
            data = volio._get(f"{volio.BUCKET}/{s['scroll']}/segments/{s['segment']}/{s['tifxyz']}/{f}")
            if data is None:
                raise Refused(f"{s['id']}: {f} of its tifxyz mesh is missing from the bucket")
            vc3dout.atomic_write(target, data)
    return segdir


def summarize_letters(res, why):
    if res is None:
        return {"status": None, "why": why}
    c = res.get("control", {})
    return {"status": c.get("status"), "letters_kept": c.get("letters_kept"),
            "null_letters_kept": c.get("null_letters_kept"),
            "control_map_letters": (c.get("control_map") or {}).get("letters_kept"),
            "weights": READER_WEIGHTS, "note": "letter strings are hypotheses for a person, kept in the sidecar file"}


def make_receipt(run, decision, a, box_render, pool, source, letters=None):
    return {"tool": f"Ink Lens {VERSION}", "note": NOTE, "reader": a.reader, "windows": a.windows,
            "readers": run.get("readers"), "engine": run.get("engine"), "where": run.get("where"),
            "device": run.get("device"), "device_name": run.get("device_name"), "patches": run.get("patches"),
            "gpu_seconds_requested": run.get("gpu_seconds_requested"), "seconds": run.get("seconds"),
            "window_layers": run.get("window_layers"), "box_render_px": [int(v) for v in box_render],
            "pool": pool, "source": source, "gate": decision, "letters": letters,
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def cmd_run(a):
    seg = vc3dout.segment(a.segment) if a.segment else None
    center = None
    if a.from_vc3d:
        import bridge
        with bridge.Bridge(bridge.discover(a.bridge)) as br:
            if seg is None:
                seg = vc3dout.segment(bridge.active_segment(br)["path"])
            center = bridge.cursor_point(br)
        xyz = vc3dout.load_xyz(seg["dir"])
        gr, gc, dist = vc3dout.voxel_to_grid(xyz, center)
        if dist > 50:
            raise Refused(f"the cursor is {dist:.0f} voxels from the active segment; put it on the segment")
        r, c = gr / seg["scale"][1], gc / seg["scale"][0]
    if seg is None:
        raise Refused("give --segment SEGDIR (a tifxyz folder), or --from-vc3d with a running VC3D")
    um = a.um_per_px or (ome_voxel_um(a.volume) if a.volume else None)
    if um is None:
        raise Refused("give --um-per-px (the render's pixel size in micrometers)")
    pool = volio.pool_factor(um)
    if a.from_vc3d:
        side = a.size * pool
        box = (int(r - side / 2), int(c - side / 2), side, side)
    elif a.box:
        x, y, w, h = a.box
        box = (y, x, h, w)
    elif a.crop:
        y0, y1, x0, x1 = a.crop
        box = (y0, x0, y1 - y0, x1 - x0)
    else:
        raise Refused("give --box X Y W H or --crop Y0 Y1 X0 X1 (render pixels of the segment at scale 1), or "
                      "--from-vc3d")
    cw, ch = seg["canvas_px"]
    y, x, h, w = box
    if not (0 <= y and 0 <= x and y + h <= ch and x + w <= cw):
        raise Refused(f"the box rows {y}..{y + h}, columns {x}..{x + w} is outside the segment canvas {cw} x {ch}")
    mh, mw = h // pool, w // pool
    est = engine.estimate(mh, mw, a.windows, a.reader)
    if a.dry_run:
        rid = run_id(a.reader, box)
        would = ([str(Path(a.out) / n) for n in ("inklens.tif", "inklens_reverse.tif", "inklens.pins.json",
                                                 "inklens.letters.json", "inklens.json")] if a.out else
                 [f"inklens/{rid}.png", "inklens/mosaic.png", "ink-detections.json", f"inklens/{rid}.pins.json",
                  f"inklens/{rid}.json"])
        emit({"segment": seg["dir"], "box_render_px": box, "pool": pool, "map_px": [mh, mw], "estimate": est,
              "would_write": would}, a.json)
        return EXIT_OK
    if a.offline:
        os.environ["INKLENS_OFFLINE"] = "1"
    if a.out and not a.local:
        raise Refused("--out is the tool registry's route and runs only in local mode (--local); the Space spends "
                      "ZeroGPU quota, which needs a yes for each use")
    if not a.local and est.get("refused"):
        raise Refused(est["refused"])
    layers = engine.STACK * pool
    if a.surface_volume:
        data, src = volio.read_region(a.surface_volume, box)
    elif a.volume:
        data, src = render_region(seg["dir"], a.volume, box, layers, a.render_binary)
    else:
        raise Refused("give --surface-volume PATH or --volume OME_ZARR")
    volume = volio.pool(volio.to_uint8(data), pool)
    run = lens(volume, a)
    decision, kept, kept_r = analyze(run["forward"], run["reverse"], volume)
    check_space_gate(run, decision)
    res, why = (None, "skipped (--no-pins)") if a.no_pins else letters(kept, kept_r, um * pool, a.letter_mm)
    rid = run_id(a.reader, box)
    summary = summarize_letters(res, why)
    receipt = make_receipt(run, decision, a, box, pool, src, summary)
    if a.out:
        files, voxels = write_run_folder(a.out, seg["dir"], box, pool, gate.to_u8(kept), gate.to_u8(kept_r),
                                         decision, dict(receipt, run=rid), letter_points(res, box, pool),
                                         letters_doc=res)
        emit({"run": rid, "segment": seg["dir"], "gate": decision, "letters": summary, "files": files,
              "pins": len(voxels), "where": run["where"], "note": NOTE}, a.json)
        return EXIT_OK      # the gate's status is in the receipt; the files are the result, an empty map included
    files, voxels = write_vc3d(seg["dir"], rid, box, pool, gate.to_u8(kept), decision, receipt,
                               letter_points(res, box, pool))
    if res:
        vc3dout.atomic_write(Path(seg["dir"]) / "inklens" / f"{rid}.letters.json", json.dumps(res, indent=1))
    out = {"run": rid, "segment": seg["dir"], "gate": decision, "letters": summary, "files": files,
           "pins": len(voxels), "where": run["where"], "note": NOTE}
    if a.bridge is not None and files.get("pins"):
        out["bridge"] = bridge_push(a.bridge or None, files["pins"], center or voxels[0])
    elif a.bridge is not None:
        out["bridge"] = "no pins to load; in VC3D reopen the segment to see the new ink map"
    emit(out, a.json)
    return exit_for(decision["status"])


def parser():
    ap = argparse.ArgumentParser(prog="inklens", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        g = p.add_mutually_exclusive_group()
        g.add_argument("--local", action="store_true", help="run the model on this machine (CUDA, MPS or CPU)")
        g.add_argument("--space", default=DEFAULT_SPACE, help=f"Hugging Face Space (default {DEFAULT_SPACE})")
        p.add_argument("--token", help="Hugging Face token (default: HF_TOKEN or `hf auth login`)")
        p.add_argument("--device", help="local mode: cuda, mps or cpu (default: the best available)")
        p.add_argument("--reader", default="d9v2", choices=engine.READER_CHOICES)
        p.add_argument("--windows", type=int, default=3, choices=(1, 3))
        p.add_argument("--no-pins", action="store_true", help="skip the Scroll Text Reader and the letter pins")
        p.add_argument("--letter-mm", type=float, default=LETTER_MM)
        p.add_argument("--dry-run", action="store_true", help="print the plan and the GPU estimate; run nothing")
        p.add_argument("--json", action="store_true")

    e = sub.add_parser("estimate", help="patches and GPU seconds for a region")
    e.add_argument("height", type=int)
    e.add_argument("width", type=int)
    e.add_argument("--windows", type=int, default=3, choices=(1, 3))
    e.add_argument("--reader", default="d9v2", choices=engine.READER_CHOICES)
    e.add_argument("--json", action="store_true")
    e.set_defaults(fn=cmd_estimate)

    s = sub.add_parser("samples", help="the public samples")
    s.set_defaults(fn=cmd_samples)

    d = sub.add_parser("demo", help="a public sample end to end")
    d.add_argument("sample")
    d.add_argument("--size", type=int, help="a size x size square (default: the sample's 640 px crop)")
    d.add_argument("--at", type=int, nargs=2, metavar=("ROW", "COL"), help="the square's top-left corner instead")
    d.add_argument("--vc3d-out", help="download the sample's tifxyz mesh here and write VC3D's files into it")
    d.add_argument("--score", action="store_true", help="score the maps and the kept ink against the labels")
    d.add_argument("--save-maps", help="also save forward, reverse, kept and the CT layer as .npz")
    common(d)
    d.set_defaults(fn=cmd_demo)

    r = sub.add_parser("run", help="a region of a VC3D segment, written back as VC3D files")
    r.add_argument("--segment", help="the tifxyz segment folder")
    r.add_argument("--surface-volume", help="a surface volume of the whole segment (zarr, .npy, .npz, .tif)")
    r.add_argument("--volume", help="the scan's OME-Zarr: render only the region with vc_render_tifxyz")
    r.add_argument("--render-binary", help="path to vc_render_tifxyz")
    r.add_argument("--um-per-px", type=float, help="pixel size of the render (default: from the OME-Zarr)")
    r.add_argument("--box", type=int, nargs=4, metavar=("X", "Y", "W", "H"), help="region in render pixels")
    r.add_argument("--crop", type=int, nargs=4, metavar=("Y0", "Y1", "X0", "X1"),
                   help="the same region as a box on the segment's canvas (the tool registry's form)")
    r.add_argument("--out", help="write the run's files into this folder only, never into the segment folder "
                                 "(exit 0 whenever they are written; local mode only)")
    r.add_argument("--offline", action="store_true",
                   help="refuse a checkpoint, villa source or letter weights that are not cached, instead of "
                        "downloading them (fetch them once with engine.py fetch)")
    r.add_argument("--from-vc3d", action="store_true", help="center the region on VC3D's cursor (needs --bridge)")
    r.add_argument("--size", type=int, default=1024, help="with --from-vc3d: region side at 9.6 um (default 1024)")
    r.add_argument("--bridge", nargs="?", const="", default=None,
                   help="VC3D agent bridge name or socket (default: the newest live one)")
    common(r)
    r.set_defaults(fn=cmd_run)
    return ap


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        return a.fn(a)
    except (Refused, engine.EngineError, gate.GateError, vc3dout.VC3DError, volio.VolumeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ == "BridgeError":
            print(f"refused: {exc}", file=sys.stderr)
            return EXIT_REFUSED
        raise


if __name__ == "__main__":
    sys.exit(main())
