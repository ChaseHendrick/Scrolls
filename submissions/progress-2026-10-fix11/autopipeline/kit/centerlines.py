"""Published center lines as an axis source: AutoPipeline's umbilicus.source "centerlines" (added 23 Oct 2026).

The Hugging Face dataset SharpMeow/vesuvius-center-lines (CC BY-NC 4.0 as a collection; each line keeps its own
licence) holds every public center line we know of for the 22 prize-eligible scans, in VC3D's umbilicus format in
the scan's level-0 voxels: the organisers' lines from the open-data bucket, Alexey Drobkov's (MIT), Iyan Dopico's
via Drobkov's repository (MIT), Abd Elilah's manual curves (CC BY 4.0), and the scroll center finder's lines for
the nine 1.2 m scans nobody had done (model output; the CT end check flagged 4 of their 18 ends, and each such
line's usable_ends says which ends to rely on). Since v2.3 it also covers public scans off the prize page, and
since v2.4 (24 Oct 2026) each of the finder's 12 lines on 1.2 m scans has a coverage-polished copy beside it
(source finder-polished, kit axispolish rule 1: jumpier than the original, ends not re-checked, usable_ends
null). kit/data/centerlines.json is the dataset's tables/lines.jsonl at
one revision (REV); a plan names that revision and an order of sources, so its digest fixes which file a scan gets,
and the stage fetches the file at that revision and refuses it unless its sha256 matches.

The default order puts people's lines before the finder's: the organisers' (the line AutoPipeline's catalog source
would take), then Drobkov, Dopico and Abd Elilah, then the finder (Interpretation: provenance, not a measured
ranking of the lines). Among the finder's lines the polished copy comes first, since it beat the original on all
ten scans of its frozen test (winding coverage, Measurement); prefer ["finder", ...] takes the original. A line is
used as it is, never polished or trimmed here.

Standard library only.
"""

import hashlib
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "centerlines.json"
DATASET = "SharpMeow/vesuvius-center-lines"
REV = "c67d4743638faf6794f7dc023910934d89a96f0e"
SOURCES = ("bucket", "drobkov", "dopico", "tauil", "finder", "finder-polished")
# People's lines first; then the finder's, its coverage-polished copy before the original: the polished line sat deeper
# in villa's traced sheet than the line before the polish on all ten scans of its frozen test (Chase's decision,
# 24 Oct 2026: the best line is the default)
DEFAULT_PREFER = ("bucket", "drobkov", "dopico", "tauil", "finder-polished", "finder")
# The plan setting (OPTIONAL["umbilicus.centerlines"] in kit/autopipe.py)
DEFAULTS = {"rev": REV, "prefer": list(DEFAULT_PREFER)}
LABEL = ("Published center line from the dataset SharpMeow/vesuvius-center-lines: a person's line, or the scroll "
         "center finder's (model output) where nobody had made one")


class CenterlineError(ValueError):
    pass


def load(path=None):
    data = json.loads(Path(path or DATA).read_text())
    if data.get("rev") != REV and path is None:
        raise CenterlineError(f"{DATA} holds revision {data.get('rev')}, not {REV}")
    return data


def check(setting):
    """Refusals for umbilicus.centerlines: the pinned revision and an order of known sources."""
    if not isinstance(setting, dict) or set(setting) != {"rev", "prefer"}:
        raise CenterlineError("umbilicus.centerlines is {\"rev\": REV, \"prefer\": [sources]} (true takes the defaults)")
    if setting["rev"] != REV:
        raise CenterlineError(f"umbilicus.centerlines.rev: this kit holds the dataset at {REV} only, not "
                              f"{setting['rev']!r}")
    pre = setting["prefer"]
    if (not isinstance(pre, list) or not pre or len(set(pre)) != len(pre)
            or not all(isinstance(p, str) for p in pre)):
        raise CenterlineError("umbilicus.centerlines.prefer is a list of different sources")
    bad = [p for p in pre if p not in SOURCES]
    if bad:
        raise CenterlineError(f"umbilicus.centerlines.prefer: no source {', '.join(bad)}; sources: {', '.join(SOURCES)}")


def scan_id(volume):
    """The scan id of a volume given by id, folder name or URL (as vc3d_catalog.umbilicus_for reads it)."""
    return str(volume).rstrip("/").split("/")[-1].split("-")[0]


def pick(volume, setting, data=None):
    """The line a plan's setting takes for a volume: the first source of setting["prefer"] that has one, or None."""
    check(setting)
    data = data or load()
    sid = scan_id(volume)
    mine = [l for l in data["lines"] if l["scan"] == sid]
    for src in setting["prefer"]:
        hit = [l for l in mine if l["source"] == src]
        if len(hit) > 1:
            raise CenterlineError(f"{data['dataset']} has {len(hit)} {src} lines for scan {sid}")
        if hit:
            return hit[0]
    return None


def url(line, rev=REV):
    return f"https://huggingface.co/datasets/{DATASET}/resolve/{rev}/{line['file']}"


def fetch(line, dest, download, rev=REV):
    """The line file into dest through download(url, dest), refused unless its sha256 is the snapshot's. Returns the
    stage's record."""
    dest = Path(dest)
    u = url(line, rev)
    download(u, dest)
    got = hashlib.sha256(dest.read_bytes()).hexdigest()
    if got != line["sha256"]:
        dest.unlink()
        raise CenterlineError(f"{u}: sha256 {got}, not the snapshot's {line['sha256']}")
    return {"source": "centerlines", "url": u, "rev": rev, "line_source": line["source"], "line_kind": line["kind"],
            "licence": line["licence"], "credit": line["credit"], "sha256": got, "usable_ends": line["usable_ends"],
            "scroll": line["scroll"], "label": LABEL}
