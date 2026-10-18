"""Shared pieces of the release-media scripts: media labels, the public-tree guard and sidecar records.

Every picture, GIF and video made for a released tool says what it is, in its caption and in a sidecar JSON next to
it (Chase, 18 October 2026). The four labels are the ones in docs/assets/README.md:

  Concept illustration   procedural or generated art: no scan, no model output, no recovered text
  Real data render       pixels made from a public scan (scan, segment, voxel size and the data credit required)
  Model output           a model's map or score, never a reading
  Synthetic demo         a demo on made-up data, or a screenshot of a tool showing only made-up data

Real data renders and model output never go into public Scrolls' docs/assets/ (public Git holds no renders: the
no-scroll-data rule); write them under Scrolls-private's docs/media/ instead. write_guard() refuses any label but
Concept illustration or Synthetic demo there, and input_guard() refuses source pictures from outside the public tree.

Standard library only, so the tests can import it without numpy or Pillow.
"""

import datetime
import hashlib
import json
import subprocess
from pathlib import Path

LABELS = ("Concept illustration", "Real data render", "Model output", "Synthetic demo")
# Labels whose pixels come from scans or models; never written under a public docs/assets/ folder.
PRIVATE_ONLY = ("Real data render", "Model output")
# The only labels a file under a public docs/assets/ folder may carry (tests/test_repo.py checks the same).
PUBLIC_LABELS = ("Concept illustration", "Synthetic demo")
# Pictures a public hero or panel may be built from: files already in the public tree, which its checks cover.
PUBLIC_INPUT_DIRS = (("docs", "images"), ("docs", "assets"))
DATA_CREDIT = "Data: Vesuvius Challenge, CC BY-NC 4.0"
SCHEMA = "scrolls-media/1"
LONG_DASHES = (chr(0x2014), chr(0x2013))
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


class MediaError(ValueError):
    pass


def check_meta(meta):
    """Return meta if its label, alt text, caption, license and data fields are complete, else raise MediaError."""
    if not isinstance(meta, dict):
        raise MediaError("the media record must be a JSON object")
    label = meta.get("label")
    if label not in LABELS:
        raise MediaError(f"label must be one of {', '.join(LABELS)}, not {label!r}")
    for key in ("alt", "caption", "license"):
        value = meta.get(key)
        if not isinstance(value, str) or not value.strip() or "\n" in value:
            raise MediaError(f"{key} must be one non-empty line")
        for ch in LONG_DASHES:
            if ch in value:
                raise MediaError(f"{key} has a long dash (house style: none)")
    if not meta["caption"].startswith(label):
        raise MediaError(f"caption must start with its label, {label!r}")
    if label == "Real data render":
        data = meta.get("data")
        if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data.get(k)
                                                 for k in ("scan", "segment", "voxel_size")):
            raise MediaError("a Real data render needs data: {scan, segment, voxel_size, credit}")
        if data.get("credit") != DATA_CREDIT or DATA_CREDIT not in meta["caption"]:
            raise MediaError(f"a Real data render carries the credit {DATA_CREDIT!r} in data.credit and its caption")
    return meta


def under_assets(path):
    """True when path lies under a docs/assets/ folder (public Scrolls' media home)."""
    parts = Path(path).resolve().parts
    return any(parts[i:i + 2] == ("docs", "assets") for i in range(len(parts) - 1))


def write_guard(label, out_path):
    """Refuse to write anything but a Concept illustration or a Synthetic demo into a docs/assets/ folder: public Git
    holds no scan renders or model maps."""
    if under_assets(out_path) and label not in PUBLIC_LABELS:
        raise MediaError(f"{label} may not be written under docs/assets/ (public Git holds no scan renders or maps); "
                         "write it under Scrolls-private's docs/media/ instead")


def input_guard(inputs, out_path, root=ROOT):
    """Refuse a picture under docs/assets/ that is built from a file outside the public tree's docs/images/ or
    docs/assets/. A label is only a claim; this keeps a scan render from entering through a hero's source image."""
    if not under_assets(out_path):
        return
    allowed = [Path(root).resolve().joinpath(*d) for d in PUBLIC_INPUT_DIRS]
    for item in inputs:
        p = Path(item)
        p = (p if p.is_absolute() else Path(root) / p).resolve()
        if not any(a in p.parents for a in allowed):
            raise MediaError(f"{item} is not under docs/images/ or docs/assets/; a picture for docs/assets/ is built "
                             "only from files already in the public tree (commit the source there, with its label, "
                             "in the same reviewed change)")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git_commit(path=ROOT):
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def scripts_digest(names):
    """SHA-256 over the named files of scripts/media/, so a sidecar names the exact code that made its picture."""
    h = hashlib.sha256()
    for name in sorted(names):
        h.update(name.encode() + b"\0" + (HERE / name).read_bytes())
    return h.hexdigest()


def output_record(path, width=None, height=None, **extra):
    p = Path(path)
    rec = {"file": p.name, "bytes": p.stat().st_size, "sha256": sha256(p)}
    if width is not None:
        rec.update(width=int(width), height=int(height))
    rec.update(extra)
    return rec


def write_sidecar(path, meta, outputs, *, command, scripts, inputs=(), extra=None):
    """Write the sidecar JSON for one picture or clip: what it is, how it was made, from what, under what license."""
    check_meta(meta)
    record = {"schema": SCHEMA, "name": Path(path).stem, "label": meta["label"], "alt": meta["alt"],
              "caption": meta["caption"], "license": meta["license"], "release_id": meta.get("release_id"),
              "data": meta.get("data"), "sources": list(meta.get("sources") or []), "outputs": list(outputs),
              "inputs": list(inputs), "made": datetime.date.today().isoformat(),
              "tool": {"scripts": sorted(scripts), "scripts_sha256": scripts_digest(scripts),
                       "base_commit": git_commit()},
              "command": command}
    if extra:
        record.update(extra)
    Path(path).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record
