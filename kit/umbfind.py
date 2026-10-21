"""Scroll center finder from VC3D and the tool registry: `python -m kit.umbfind VOLUME --out RUN`.

Runs scripts/umbilicus/predict.py (two-stage U-Nets, weights from release umbilicus-v1; docs/tools/umbilicus.md) on
one open-data scan and puts its center line where VC3D's plugin host and the tool registry
(kit/data/registry/umbilicus.json) look for it:

  RUN/umbilicus.json   the line in the published format (control_points x, y, z in level-0 voxels; metadata with
                       the voxel size, the scan and, when the bucket gives it, the scan's level-0 grid), which VC3D
                       loads as an umbilicus
  RUN/predict.json     the finder's per-slice record (its SCROLL_predict.json)
  RUN/predict/         predict.py's own output folder; RUN/slices/ its slice file (0.25 to 0.65 GB of level-3
                       range reads); RUN/weights/ the released weight files when none were found (about 26 MB)

VOLUME is the scan as VC3D has it open: its open-data bucket URL (https://vesuvius-challenge-open-data.s3...
or s3://vesuvius-challenge-open-data/...), its bucket key (PHerc0125/volumes/SCAN.zarr), or a local copy kept
under the bucket's layout (.../PHercNNNN/volumes/SCAN.zarr), which names the same key. The finder reads its slices
from the bucket by that key (scripts/umbilicus/slices.py), never from a local folder; another location is refused.
It takes the 1.2 m scans, 8 to 10 um voxels (the finder's UM_RANGE), read from the scan's name.

Weights: --first FILE and --zoom FILE (their sha256 is recorded, marked not pinned: fold weights or your own), else
the two released all-scroll files found in KIT_UMBILICUS_WEIGHTS or work/umbilicus/weights of this checkout (the
guide's folder) and checked against the release's sha256 (WEIGHTS); with --download a missing one is fetched from
the release into RUN/weights and checked. The script is KIT_CENTRENET_PREDICT (the variable AutoPipeline's
centrenet backend reads) or scripts/umbilicus/predict.py of this checkout, run with this Python on the CPU
(--device cpu: GPU work belongs on Modal). Writes only inside RUN.

The line is model output: the finder's answer, not a measured or published line, and on the 13 scrolls with a
published line the all-scroll weights trained on it, so it is not held out there. Exit codes: 0 done; 1 the finder
failed or kept no point; 2 a refused volume, missing weights or a bad argument. Standard library only; the finder
itself needs numpy, scipy, requests and torch in this Python.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

KIT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = KIT_ROOT / "scripts" / "umbilicus" / "predict.py"
BUCKET = "vesuvius-challenge-open-data"
RELEASE = "https://github.com/ChaseHendrick/Scrolls/releases/download/umbilicus-v1/"
WEIGHTS = {     # scripts/umbilicus/README.md, release umbilicus-v1
    "first": ("umbilicus-first-all.pt", "c9b50aae2876e00f50b7ade5cf9a6facc84fb0f8ad9667dddf5565e5f06ae854"),
    "zoom": ("umbilicus-zoom-all.pt", "0a06fe2e108fbb5f252455f93862336ec4013a535eb922676ae8f846406fb4bb"),
}
UM_RANGE = (8.0, 10.0)      # scripts/umbilicus/predict.py UM_RANGE
ENV_WEIGHTS = "KIT_UMBILICUS_WEIGHTS"
ENV_SCRIPT = "KIT_CENTRENET_PREDICT"
CLAIM = ("Model output: the finder's center line, not a measured or published line; on the 13 scrolls with a "
         "published line the all-scroll weights trained on it, so it is not held out there")
SCROLL_RE = re.compile(r"^PHerc[0-9A-Za-z]+$")


class UmbfindError(ValueError):
    """A volume, weight file or argument this adapter refuses (exit 2)."""


def bucket_key(volume):
    """(scroll, bucket key, voxel size in um) of the scan VOLUME names: a bucket URL, a bucket key, or a local copy
    under the bucket's layout (.../SCROLL/volumes/SCAN.zarr). Raises UmbfindError for anything else."""
    v = str(volume or "").strip()
    u = urlparse(v)
    key = None
    if u.scheme == "s3" and u.netloc == BUCKET:
        key = u.path
    elif u.scheme in ("http", "https"):
        if BUCKET not in u.netloc:
            raise UmbfindError(f"{v}: the center finder reads its slices from the open-data bucket "
                               f"({BUCKET}); open the scan by its bucket URL")
        key = u.path
    elif u.scheme:
        raise UmbfindError(f"{v}: not a bucket URL, bucket key or local folder")
    else:
        parts = [p for p in Path(v).expanduser().as_posix().split("/") if p]
        if len(parts) >= 3 and parts[-2] == "volumes" and SCROLL_RE.match(parts[-3]):
            key = "/".join(parts[-3:])
        elif not Path(v).expanduser().exists() and SCROLL_RE.match(parts[0] if parts else ""):
            key = v
    if not key:
        raise UmbfindError(f"{v}: the center finder reads its slices from the open-data bucket by key; give the "
                           "scan's bucket URL, its key (PHercNNNN/volumes/SCAN.zarr) or a local copy kept under "
                           "that layout")
    key = key.strip("/")
    scroll = key.split("/")[0]
    if not SCROLL_RE.match(scroll) or "/volumes/" not in f"/{key}/":
        raise UmbfindError(f"{v}: {key} is not a scan in the bucket (SCROLL/volumes/SCAN.zarr)")
    name = key.rstrip("/").split("/")[-1]
    try:
        um = float(name.split("-")[1].replace("um", ""))
    except (IndexError, ValueError):
        raise UmbfindError(f"{v}: no voxel size in the scan name (<timestamp>-<size>um-...)") from None
    if not UM_RANGE[0] <= um <= UM_RANGE[1]:
        raise UmbfindError(f"{v}: {um:g} um voxels; the center finder takes {UM_RANGE[0]:g} to {UM_RANGE[1]:g} um "
                           "scans (the 1.2 m scans)")
    return scroll, key, um


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _weight_folders(given=None, env=None):
    env = os.environ if env is None else env
    out = [Path(given).expanduser()] if given else []
    if env.get(ENV_WEIGHTS):
        out.append(Path(env[ENV_WEIGHTS]).expanduser())
    out.append(KIT_ROOT / "work" / "umbilicus" / "weights")
    return out


def find_weights(out, first=None, zoom=None, folder=None, download=False, env=None, opener=None):
    """{stage: {"path", "sha256", "pinned"}} for the first and zoom stages: explicit files as they are (not pinned),
    else the released files found in the weight folders with the release's sha256, else (download) fetched into
    OUT/weights and checked. Raises UmbfindError naming what is missing."""
    explicit = {"first": first, "zoom": zoom}
    if bool(first) != bool(zoom):
        raise UmbfindError("give both --first and --zoom, or neither (the released all-scroll files)")
    got = {}
    for stage, (name, want) in WEIGHTS.items():
        if explicit[stage]:
            p = Path(explicit[stage]).expanduser()
            if not p.is_file():
                raise UmbfindError(f"--{stage} {p} does not exist")
            got[stage] = {"path": str(p.resolve()), "sha256": _sha256(p), "pinned": False}
            continue
        seen = []
        for d in _weight_folders(folder, env):
            f = d / name
            if f.is_file():
                h = _sha256(f)
                if h == want:
                    got[stage] = {"path": str(f.resolve()), "sha256": h, "pinned": True}
                    break
                seen.append(f"{f} (sha256 {h[:12]}, the release pins {want[:12]})")
        if stage in got:
            continue
        if not download:
            raise UmbfindError(f"{name} not found with the release's sha256 in "
                               f"{', '.join(str(d) for d in _weight_folders(folder, env))}"
                               + (f"; skipped {'; '.join(seen)}" if seen else "")
                               + f": download it from {RELEASE}{name} (the guide's curl line), or allow --download")
        dest = Path(out) / "weights" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(name + ".part")
        with (opener or urllib.request.urlopen)(RELEASE + name, timeout=120) as r, open(part, "wb") as fh:
            shutil.copyfileobj(r, fh)
        h = _sha256(part)
        if h != want:
            part.unlink()
            raise UmbfindError(f"{name}: downloaded sha256 {h[:12]}, the release pins {want[:12]}")
        os.replace(part, dest)
        got[stage] = {"path": str(dest), "sha256": h, "pinned": True, "downloaded": True}
    return got


def _points(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    cp = doc.get("control_points") if isinstance(doc, dict) else None
    return len(cp) if isinstance(cp, list) else 0


def _copy(src, dest):
    tmp = Path(str(dest) + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)


def find(volume, out, first=None, zoom=None, weights=None, download=False, env=None, python=None, opener=None,
         end_rule=True):
    """Run the finder on VOLUME into OUT. Returns (summary, exit code); never raises for the finder's own failure."""
    env = dict(os.environ if env is None else env)
    scroll, key, um = bucket_key(volume)
    out = Path(out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    w = find_weights(out, first, zoom, weights, download, env, opener)
    script = Path(env.get(ENV_SCRIPT) or SCRIPT)
    if not script.is_file():
        raise UmbfindError(f"{script} is missing: the finder ships in Scrolls under scripts/umbilicus/")
    pred = out / "predict"
    argv = [python or sys.executable, str(script), scroll, "--first", w["first"]["path"], "--zoom",
            w["zoom"]["path"], "--data", str(out / "slices"), "--out", str(pred), "--volume", key, "--device", "cpu"]
    if not end_rule:
        argv.append("--no-end-rule")
    summary = {"schema": "umbfind/1", "scroll": scroll, "volume": str(volume), "key": key, "voxel_um": um,
               "weights": {k: {"file": Path(v["path"]).name, "sha256": v["sha256"], "pinned": v["pinned"]}
                           for k, v in w.items()},
               "argv": argv, "device": "cpu", "claim": CLAIM}
    proc = subprocess.run(argv, cwd=str(out), env=env, capture_output=True, text=True)
    (out / "predict.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    line, detail = pred / f"{scroll}_umbilicus.json", pred / f"{scroll}_predict.json"
    summary["exit"] = proc.returncode
    if proc.returncode != 0 or not line.is_file():
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
        summary.update(status="failed", error=f"the finder exited {proc.returncode}: " + " | ".join(tail))
        return summary, 1
    n = _points(line)
    summary["points"] = n
    if n == 0:
        summary.update(status="failed", error="the finder kept no point (no run of slices met the end rules); VC3D "
                                              "refuses an umbilicus without points, so none is written")
        return summary, 1
    _copy(line, out / "umbilicus.json")
    if detail.is_file():
        _copy(detail, out / "predict.json")
    summary.update(status="ok", umbilicus=str(out / "umbilicus.json"),
                   predict=str(out / "predict.json") if detail.is_file() else None)
    return summary, 0


def _build_parser():
    p = argparse.ArgumentParser(prog="python -m kit.umbfind", description=__doc__.split("\n\n")[0])
    p.add_argument("volume", help="the scan: its open-data bucket URL, bucket key, or a local copy under the bucket's "
                                  "layout (SCROLL/volumes/SCAN.zarr)")
    p.add_argument("--out", required=True, help="the run folder: umbilicus.json, predict.json, predict/, slices/")
    p.add_argument("--first", help="first-stage weights to use instead of the released file (recorded, not pinned)")
    p.add_argument("--zoom", help="zoom-stage weights to use instead of the released file (recorded, not pinned)")
    p.add_argument("--weights", help="a folder holding the released umbilicus-first-all.pt and umbilicus-zoom-all.pt")
    p.add_argument("--download", action="store_true", help="fetch a missing released weight file into OUT/weights")
    p.add_argument("--no-end-rule", action="store_true", help="trim mount and caps only, without the end-point rule")
    p.add_argument("--json", action="store_true", help="accepted; the summary is always JSON")
    return p


def main(argv=None):
    a = _build_parser().parse_args(argv)
    try:
        summary, code = find(a.volume, a.out, a.first, a.zoom, a.weights, a.download, end_rule=not a.no_end_rule)
    except UmbfindError as exc:
        print(f"umbfind: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"umbfind: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=1))
    if code:
        print(f"umbfind: {summary.get('error')}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
