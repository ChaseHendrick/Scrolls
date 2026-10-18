"""Shared pieces of the release-media scripts: media labels, the public media rule, sidecar records and file sizes.

Every picture, GIF and video made for a released tool says what it is, in its caption and in a sidecar JSON next to
it (Chase, 18 October 2026). The four labels are the ones in docs/assets/README.md:

  Concept illustration   procedural or generated art: no scan, no model output, no recovered text
  Real data render       pixels made from a public scan (scan, voxel size, labels shown and the data credit required)
  Model output           a model's map or score, never a reading
  Synthetic demo         a demo on made-up data, or a screenshot of a tool showing only made-up data

The public media rule (docs/media/README.md; set by the agent on Chase's delegation, 18 October 2026) says what public
Scrolls' docs/assets/ may hold: concept illustrations, synthetic demos, and Real data renders of public open-data scans
that are not prize-eligible and show no held-out labels, every file at most 1920 px wide and 4 MB, with a sidecar.
Model output of any scroll, and every render of a prize-eligible scroll, stay in Scrolls-private's docs/media/.
write_guard() applies the rule before a file is written there, input_guard() keeps outside pictures out of
illustrations and demos, size_guard() checks a written file, and public_problems() checks a sidecar
(tests/test_repo.py runs it on every sidecar under docs/assets/). The eligible scrolls come from the newest
kit/data/prizes-*.json; without one the check fails instead of passing.

Standard library only, so the tests can import it without numpy or Pillow.
"""

import datetime
import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path

LABELS = ("Concept illustration", "Real data render", "Model output", "Synthetic demo")
# Model output of any scroll never goes under a public docs/assets/ folder (the public media rule).
PRIVATE_ONLY = ("Model output",)
# The labels a file under a public docs/assets/ folder may carry; a Real data render only when real_data_problems()
# finds nothing (tests/test_repo.py checks the same through public_problems()).
PUBLIC_LABELS = ("Concept illustration", "Synthetic demo", "Real data render")
# Pictures a public illustration, demo or panel may be built from: files already in the public tree, which its checks
# cover. A Real data render is built from scan data instead, so its data block and the rule stand in for this.
PUBLIC_INPUT_DIRS = (("docs", "images"), ("docs", "assets"))
DATA_CREDIT = "Vesuvius Challenge open data, CC BY-NC 4.0"
DATA_LICENSE = "CC BY-NC 4.0"
# Every file under docs/assets/: at most this wide and this large (the public media rule).
MAX_WIDTH = 1920
MAX_BYTES = 4_000_000
# Labels held out for evaluation, never drawn in a public render: (scroll, segment), None for every segment.
HELD_OUT_LABELS = (("PHerc1447", None), ("PHerc0841", "ag405"))
# Other names of scrolls, written as normalize_scroll() leaves them: Scroll 1 to 5 and the Paris scrolls.
SCROLL_ALIASES = {"SCROLL1": "PHERCPARIS4", "SCROLL2": "PHERCPARIS3", "SCROLL3": "PHERC0332", "SCROLL4": "PHERC1667",
                  "SCROLL5": "PHERC0172", "PARIS4": "PHERCPARIS4", "PARIS3": "PHERCPARIS3"}
# A scroll named in free text or a file name: PHerc0139, PHerc. 139, pherc0800-w003, PHerc. Paris 4, PHerc0175A,
# Paris 4, Scroll 1.
SCROLL_MENTION = re.compile(r"(?<![A-Za-z0-9])[Pp]\.?\s?(?i:herc)\.?\s*(?:(?i:paris)\.?\s*)?\d+(?:[A-Z](?![a-z]))?(?!\d)"
                            r"|(?<![A-Za-z0-9])(?i:paris)\.?\s*\d(?!\d)|(?<![A-Za-z0-9])(?i:scroll)[\s_-]*[1-5](?!\d)")
# A volume id (the scan time stamp, such as 20250821151701) named in free text or a file name.
VOLUME_ID = re.compile(r"(?<!\d)\d{14}(?!\d)")
SCHEMA = "scrolls-media/1"
LONG_DASHES = (chr(0x2014), chr(0x2013))
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PRIZE_DATA = ROOT / "kit" / "data"


class MediaError(ValueError):
    pass


def _data_block_problems(meta):
    """Problems with a Real data render's own fields: its data block, credit and license."""
    data = meta.get("data")
    if not isinstance(data, dict):
        return ["a Real data render needs data: {scan, voxel_size, labels, credit} (segment and volume when they apply)"]
    problems = [f"a Real data render names data.{key} (labels is \"none\" when no labels are drawn)"
                for key in ("scan", "voxel_size", "labels") if not isinstance(data.get(key), str) or not data[key].strip()]
    if data.get("credit") != DATA_CREDIT or DATA_CREDIT not in str(meta.get("caption") or ""):
        problems.append(f"a Real data render carries the credit {DATA_CREDIT!r} in data.credit and its caption")
    if meta.get("license") != DATA_LICENSE:
        problems.append(f"a Real data render is licensed {DATA_LICENSE!r}, the license of the scan data")
    return problems


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
        problems = _data_block_problems(meta)
        if problems:
            raise MediaError(problems[0])
    return meta


def normalize_scroll(name):
    """Map 'PHerc. 139', 'pherc0139', 'PHerc. Paris 4', 'Scroll 1' and 'PHerc0175A' to one spelling each:
    PHERC0139, PHERCPARIS4, PHERCPARIS4, PHERC0175A. Volume ids and other names come back upper-cased."""
    text = re.sub(r"[\s._-]", "", str(name)).upper()
    text = SCROLL_ALIASES.get(text, text)
    m = re.fullmatch(r"PHERC(PARIS)?0*(\d+)([A-Z]*)", text)
    if not m:
        return text
    if m.group(1):
        return f"PHERCPARIS{int(m.group(2))}{m.group(3)}"
    return f"PHERC{int(m.group(2)):04d}{m.group(3)}"


def prize_scrolls(data_dir=None):
    """({normalized scroll or volume id: [prize ids]}, checked date) from the newest kit/data/prizes-*.json: the
    Grand Prize, First Letters and title prize lists. Raises MediaError without a snapshot, so a missing list never
    lets a render through. The live page (https://scrollprize.org/prizes) wins; a new snapshot updates this."""
    data_dir = Path(data_dir) if data_dir else PRIZE_DATA
    snapshots = sorted(data_dir.glob("prizes-*.json"))
    if not snapshots:
        raise MediaError(f"no prize snapshot (prizes-*.json) in {data_dir}: the public media rule needs the eligible "
                         "list, so nothing passes without it")
    snapshot = json.loads(snapshots[-1].read_text(encoding="utf-8"))
    table = {}
    for prize in snapshot.get("prizes", []):
        for entry in prize.get("eligible") or []:
            for key in (entry.get("scroll"), entry.get("volume")):
                if key and key != "any":
                    table.setdefault(normalize_scroll(key), []).append(prize["id"])
    return table, snapshot.get("checked")


def eligible_prizes(name, table):
    """The prizes whose eligible list holds the scroll or volume `name`. A scroll named without its A or B part
    (PHerc0175 for PHerc0175A and PHerc0175B) counts as eligible when either part is."""
    key = normalize_scroll(name)
    hits = list(table.get(key, []))
    if key.startswith("PHERC"):
        for other, prizes in table.items():
            if other != key and re.fullmatch(re.escape(key) + r"[A-Z]+", other):
                hits += prizes
    return sorted(set(hits))


def real_data_problems(meta, table=None):
    """Why a Real data render may not go into public docs/assets/ under the public media rule, or [] when it may: its
    data block, credit and license; a prize-eligible scroll or volume id in its data, caption, alt text or file names; held-out
    labels drawn on it. `table` is prize_scrolls()[0], read from the snapshot when not given."""
    problems = _data_block_problems(meta)
    data = meta.get("data") if isinstance(meta.get("data"), dict) else {}
    if table is None:
        table, _ = prize_scrolls()
    files = [str(o.get("file", "")) for o in meta.get("outputs") or [] if isinstance(o, dict)]
    text = " ".join([str(meta.get(k) or "") for k in ("name", "caption", "alt")] + files
                    + [str(v) for v in data.values() if isinstance(v, str)])
    names = [data.get("scan"), data.get("volume")] + SCROLL_MENTION.findall(text) + VOLUME_ID.findall(text)
    seen = set()
    for name in names:
        if not isinstance(name, str) or not name.strip() or normalize_scroll(name) in seen:
            continue
        seen.add(normalize_scroll(name))
        prizes = eligible_prizes(name, table)
        if prizes:
            problems.append(f"{name.strip()} is prize-eligible ({', '.join(prizes)}): its real-data media stay in "
                            "Scrolls-private's docs/media/")
    labels = str(data.get("labels") or "none").strip()
    if labels.lower() != "none":
        scan = normalize_scroll(data.get("scan") or "")
        where = " ".join([str(data.get("segment") or ""), labels, text])
        for held_scan, held_segment in HELD_OUT_LABELS:
            if scan == normalize_scroll(held_scan) and (held_segment is None or held_segment in where):
                problems.append(f"it draws held-out labels ({held_scan}{' ' + held_segment if held_segment else ''}); "
                                "a public render shows none")
    return problems


def public_problems(record, table=None):
    """Why one sidecar's files may not sit in public Scrolls' docs/assets/ under the public media rule, or [] when
    they may: the schema and label, the text fields (check_meta), the command and commit that made them, every
    output's width and bytes, and for a Real data render real_data_problems() and the scripts that made it."""
    if not isinstance(record, dict):
        return ["the sidecar is not a JSON object"]
    problems = []
    if record.get("schema") != SCHEMA:
        problems.append(f"schema is {SCHEMA!r}")
    label = record.get("label")
    if label not in PUBLIC_LABELS:
        problems.append(f"label {label!r}: public docs/assets/ takes only {', '.join(PUBLIC_LABELS)}; model output of "
                        "any scroll stays in Scrolls-private's docs/media/")
    try:
        check_meta(record)
    except MediaError as exc:
        problems.append(str(exc))
    command = record.get("command")
    if not isinstance(command, str) or not command.strip():
        problems.append("command: the command that made it")
    tool = record.get("tool") if isinstance(record.get("tool"), dict) else {}
    commit = tool.get("base_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        problems.append("tool.base_commit: the commit it was made from")
    outputs = record.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        problems.append("outputs: no files listed")
    for out in outputs if isinstance(outputs, list) else []:
        out = out if isinstance(out, dict) else {}
        name, width, nbytes = out.get("file", "?"), out.get("width"), out.get("bytes")
        if not isinstance(width, int) or width <= 0:
            problems.append(f"{name}: no width")
        elif width > MAX_WIDTH:
            problems.append(f"{name}: {width} px wide, over {MAX_WIDTH}")
        if not isinstance(nbytes, int) or nbytes <= 0:
            problems.append(f"{name}: no byte count")
        elif nbytes > MAX_BYTES:
            problems.append(f"{name}: {nbytes:,} bytes, over {MAX_BYTES:,}")
    if label == "Real data render":
        problems += [p for p in real_data_problems(record, table) if p not in problems]
        if not tool.get("scripts"):
            problems.append("tool.scripts: the scripts that made it")
    return problems


def under_assets(path):
    """True when path lies under a docs/assets/ folder (public Scrolls' media home)."""
    parts = Path(path).resolve().parts
    return any(parts[i:i + 2] == ("docs", "assets") for i in range(len(parts) - 1))


def write_guard(label, out_path, meta=None):
    """Apply the public media rule before anything is written into a docs/assets/ folder: no model output of any
    scroll, and a Real data render only when real_data_problems(meta) finds nothing."""
    if not under_assets(out_path):
        return
    if label not in PUBLIC_LABELS:
        raise MediaError(f"{label} may not be written under docs/assets/ (the public media rule: no model output of any "
                         "scroll); write it under Scrolls-private's docs/media/ instead")
    if label == "Real data render":
        problems = real_data_problems(meta if isinstance(meta, dict) else {})
        if problems:
            raise MediaError("this Real data render may not be written under docs/assets/ (the public media rule, "
                             "docs/media/README.md): " + "; ".join(problems))


def input_guard(inputs, out_path, root=ROOT, label=None):
    """Refuse an illustration or demo under docs/assets/ that is built from a file outside the public tree's
    docs/images/ or docs/assets/. A label is only a claim; this keeps a scan render from entering through a hero's
    source image. A Real data render is built from scan data, so write_guard()'s rule checks stand in for this one."""
    if not under_assets(out_path) or label == "Real data render":
        return
    allowed = [Path(root).resolve().joinpath(*d) for d in PUBLIC_INPUT_DIRS]
    for item in inputs:
        p = Path(item)
        p = (p if p.is_absolute() else Path(root) / p).resolve()
        if not any(a in p.parents for a in allowed):
            raise MediaError(f"{item} is not under docs/images/ or docs/assets/; a picture for docs/assets/ is built "
                             "only from files already in the public tree (commit the source there, with its label, "
                             "in the same reviewed change)")


def size_guard(path, width=None):
    """Refuse a file just written under docs/assets/ that is wider than MAX_WIDTH or larger than MAX_BYTES; the file
    is removed, so nothing over the public media rule's limits is left there. Without `width`, it is read from the
    file's header (media_size)."""
    path = Path(path)
    if not under_assets(path):
        return
    if width is None:
        width = (media_size(path) or (None,))[0]
    nbytes = path.stat().st_size
    if (width or 0) > MAX_WIDTH or nbytes > MAX_BYTES:
        path.unlink()
        raise MediaError(f"{path.name} is {width} px wide and {nbytes:,} bytes; a file under docs/assets/ is at most "
                         f"{MAX_WIDTH} px wide and {MAX_BYTES:,} bytes (removed it)")


def media_size(path):
    """(width, height) of a PNG, GIF, JPEG, WebP or MP4 file from its header, or None; standard library only."""
    data = Path(path).read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if chunk == b"VP8L":
            b = data[21:25]
            return 1 + (((b[1] & 0x3F) << 8) | b[0]), 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
        if chunk == b"VP8X":
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    if data[4:8] == b"ftyp":
        return _mp4_size(data, 0, len(data))
    return None


def _mp4_size(data, start, end):
    """The first track header (tkhd) with a nonzero size inside data[start:end], searching moov and trak boxes."""
    i = start
    while i + 8 <= end:
        size, kind = struct.unpack(">I4s", data[i:i + 8])
        head = 8
        if size == 1:
            size, head = struct.unpack(">Q", data[i + 8:i + 16])[0], 16
        elif size == 0:
            size = end - i
        if size < head:
            return None
        if kind in (b"moov", b"trak"):
            found = _mp4_size(data, i + head, min(i + size, end))
            if found:
                return found
        elif kind == b"tkhd":
            body = i + head
            skip = 4 + (32 if data[body] == 1 else 20) + 52
            w, h = struct.unpack(">II", data[body + skip:body + skip + 8])
            if w >> 16 and h >> 16:
                return w >> 16, h >> 16
        i += size
    return None


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
