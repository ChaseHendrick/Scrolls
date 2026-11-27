"""Which public surfaces has Reader V3 seen? A registry of its published training list, and a site check.

  python -m kit.readerseen check --reader reader-v3 --scroll PHerc0139 --segment w045 [--json]
  python -m kit.readerseen list [--reader reader-v3] [--scroll PHerc0500P2] [--json]
  python -m kit.readerseen readers
  python -m kit.readerseen verify
  python -m kit.readerseen build [--config RV3.json] [--rv2-config RV2.json] [--ink9um-readme README.md] [--out PATH]

What it reads. Only published metadata: Reader V3's train_config.json (github.com/DomRusso2/reader-v3 at 4a9f1c63,
sha256 2d71d6d5...), Reader v2's (huggingface.co/domenicor046/reader-v2 at 72633d8, sha256 a69e9cf2...) and the
ink_9um label dataset's README (hf://buckets/scrollprize/datasets/ink_9um/README.md, sha256 c9a88ff9...), whose
source-volume table maps the annotation names in the 2.4 um "aligned" folders to public segment ids. Copies of the
three files are in docs/evidence/readerseen/ and `build` refuses any other bytes. No label, CT layer, preview, mesh
or map is opened, by build or by check. The registry is kit/data/readerseen.json; `verify` rebuilds it from the
copies and fails on any drift.

Lineage (Sourced fact for the files; Community report that they are what was trained). Reader V3's description says
"Reader v2 continued on 256 px tiles (30k it), then on 384 px tiles (20k it, this config) ... same data + labels",
and its checkpoint field names the 256 px run. Reader v2's config lists the same 99 dataset keys and starts from a
checkpoint of a run on "the full corpus contract (29 representations across 4 scrolls)", which is ink_9um's 24
aligned and 5 native label sets (its README). Every ink_9um set is also one of Reader V3's keys, so Reader V3's
own list is the union. Readers fine-tuned from Reader V3 (such as Argus V2) have seen all of it plus their own
data, which this registry does not list.

Identity. Every training key is resolved to the public segment it was drawn on: the key itself where it is a public
id (PHerc0139 native v2 block, PHerc0814, PHerc0500P2, PHerc0343P, PHerc0172), the bare 14-digit stamp for the
PHerc0009B block, and the README table for the aligned and native9 names (pherc0139-w016 is public w029,
pherc0139-w029 public w045). The pseudo-label folder `pseudo/aligned-scrollprizeorg-21slices` reuses three
annotation names, pherc0139-w017, -w028 and -w029; read by the README's table (Interpretation: the folder copies
ink_9um's aligned naming, its surface keys are the annotation numbers) they are public w030, w044 and w045, and
the other reading, public w017, w028 and w029, is kept as a "possible" row so a check on public w017 is never
called fresh. Segment names meet when one equals the other or one of a row's training names (so the organizers'
"pherc0139-w029" meets public w045), when they share a winding window however padded ("w45", "w045" and
"20260126000000-w045_2026012619"), or when a short id such as "46527" or a 14-digit stamp is one part of the other.

Verdicts (fixed 27 Nov 2026):
  TRAINED            a named segment is a training surface (human or pseudo labels) by name or alias  exit 5
  TRAINED-POSSIBLE   it meets only the other reading of an ambiguous training name                    exit 5
  SELECTED           not trained, but the author scored it before release (results/suite files);
                     a whole-scroll query on a scroll that holds such units                               exit 4
  SAME-SCROLL        the scroll has training surfaces (or selected units) and no name meets them: different
                     traces can be one sheet, so this is not held out until a geometric check against the
                     training meshes shows the surface apart                                             exit 3
  SAME-ROLL          another piece of the same roll (PHerc0343 against PHerc0343P) was trained on        exit 3
  DERIVED-UNKNOWN    a reader fine-tuned from Reader V3 on a site Reader V3 never saw: its own data decides exit 3
  FRESH-BY-LIST      no training surface, selection row or roll piece on that scroll                        exit 0
A whole-scroll query (no segment) on a training scroll is TRAINED. The overall verdict is the worst over the named
segments. FRESH-BY-LIST is by list only: "held out" in a write-up still needs the reader's own exposure label.
Exit 2: bad input (unknown reader, registry out of step).
"""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "kit" / "data" / "readerseen.json"
EVIDENCE = ROOT / "docs" / "evidence" / "readerseen"
SCHEMA = "readerseen/1"

SOURCES = {
    "reader_v3_config": {
        "file": "reader-v3-train_config.json",
        "url": "https://raw.githubusercontent.com/DomRusso2/reader-v3/4a9f1c633d2f30d9b522922ec1cb52c082013183/"
               "train_config.json",
        "sha256": "2d71d6d54cc975e4ab25c0c8a789bde5ab18879eaf9f2095e849526b29e10661",
        "read": "2026-11-27", "label": "Sourced fact for the file; Community report that it is what was trained"},
    "reader_v2_config": {
        "file": "reader-v2-train_config.json",
        "url": "https://huggingface.co/domenicor046/reader-v2/resolve/72633d8aa6d40e9e737ccea4c9928fbc624dab45/"
               "train_config.json",
        "sha256": "a69e9cf23263d4b17a85f05501333408f923f67f65b6f4ebc6c4539ceb1e81ec",
        "read": "2026-11-27", "label": "Sourced fact for the file; Community report that it is what was trained"},
    "ink9um_readme": {
        "file": "ink_9um-README.md",
        "url": "https://huggingface.co/buckets/scrollprize/datasets/resolve/ink_9um/README.md",
        "sha256": "c9a88ff970594fcef3788eb588bb75dbbd0e6436f4812f89074e26c0d9fef7a5",
        "read": "2026-11-27", "label": "Sourced fact"},
}

SCROLLS = {"0139": "PHerc0139", "1667": "PHerc1667", "Paris4": "PHercParis4", "0814": "PHerc0814",
           "0009B": "PHerc0009B", "0343P": "PHerc0343P", "0500P2": "PHerc0500P2", "0172": "PHerc0172"}
README_SCROLLS = {"PHerc. 0139": "PHerc0139", "Scroll 1667": "PHerc1667", "PHerc. Paris 4": "PHercParis4",
                  "PHerc. 0814": "PHerc0814"}

# The pseudo-label names whose other reading is kept as a possible row (module docstring, "Identity").
AMBIGUOUS_PSEUDO = {"PHerc0139": {"pherc0139-w017": "w017", "pherc0139-w028": "w028", "pherc0139-w029": "w029"}}

READERS = {
    "reader-v3": {"aliases": ["reader-v3", "readerv3", "rv3", "reader v3", "v3-base", "v3base", "plain-reader-v3"],
                  "weights": "reader-v3", "derived": False,
                  "note": "DomRusso2/reader-v3 (MIT); weights domenicor046/reader-v3"},
    "reader-v2": {"aliases": ["reader-v2", "readerv2", "rv2", "reader v2"], "weights": "reader-v2", "derived": False,
                  "note": "domenicor046/reader-v2; the same 99 training keys as Reader V3 (its train_config.json). "
                          "The selection rows are Reader V3's author suite and are listed for Reader V3 only"},
    "argus-v2": {"aliases": ["argus-v2", "argusv2"], "weights": "argus-v2", "derived": True,
                 "note": "Reader V3 fine-tuned by ruiconte on native 8 to 9 um scans (ruiconte/argus-v2); its own "
                         "fine-tune segments are not in this registry"},
}

SUITE = "https://github.com/DomRusso2/reader-v3/tree/main/results"
DERIVED = ["reader-v3", "argus-v2"]

# Selection rows: units Reader V3's author scored before release (results/suite_*.json), without training on them.
SELECTION = [
    {"readers": DERIVED, "scroll": "PHerc0841",
     "segments": ["20260220213127-w00", "w00", "20260220214732-auto_grown_20260220144552896", "ag896",
                  "20260221022814-auto_grown_20260220174252405", "ag405"],
     "by": "Reader V3's author: suite rows 0841_w00, 0841_ag1, 0841_ag2 (which of ag896 and ag405 are ag1 and ag2 is "
           "not stated, so both are listed)", "source": SUITE, "label": "Community report"},
    {"readers": DERIVED, "scroll": "PHerc0009B", "segments": ["20250919125754", "ag487"],
     "by": "Reader V3's author: suite row 0009B_125754", "source": SUITE, "label": "Community report"},
    {"readers": DERIVED, "scroll": "PHerc1447",
     "segments": ["w058", "w060", "20251210153304-w058_20251210153304503_flatboi",
                  "20251207123912-w060_20251207123912611_flatboi"],
     "by": "Reader V3's author: suite rows w058, w060", "source": SUITE, "label": "Community report"},
    {"readers": DERIVED, "scroll": "PHerc0139",
     "segments": ["20260206000001-w047_2026020613", "w047", "20260220000000-w053_2026022021", "w053"],
     "by": "Reader V3's author: suite rows w047 (ink) and w053 (blank papyrus)", "source": SUITE,
     "label": "Community report"},
]

ALIASES = []    # names that mean a training surface although no name rule links them, each from a public record

EXIT = {"TRAINED": 5, "TRAINED-POSSIBLE": 5, "SELECTED": 4, "SAME-SCROLL": 3, "SAME-ROLL": 3,
        "DERIVED-UNKNOWN": 3, "FRESH-BY-LIST": 0}
RANK = {"FRESH-BY-LIST": 0, "DERIVED-UNKNOWN": 2, "SAME-ROLL": 3, "SAME-SCROLL": 4,
        "SELECTED": 5, "TRAINED-POSSIBLE": 6, "TRAINED": 7}

class SeenError(Exception):
    pass


# ---------------------------------------------------------------- build

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pinned(path, key):
    got = _sha(path)
    if got != SOURCES[key]["sha256"]:
        raise SeenError(f"{path}: sha256 {got[:12]}... is not the pinned {SOURCES[key]['sha256'][:12]}... "
                        f"({SOURCES[key]['url']})")
    return Path(path).read_bytes()


_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*\[([^\]\s·]+)\s*·\s*([0-9.]+)\s*µm\]\(([^)]+)\)")


def parse_readme(text):
    """The README's source-volume table: {(scroll, annotation name, set): public segment id}, set aligned or
    native9 by the heading above the row."""
    out, which = {}, None
    for line in text.splitlines():
        low = line.lower()
        if low.startswith("aligned public"):
            which = "aligned"
        elif low.startswith("native 9.362"):
            which = "native9"
        m = _ROW.match(line)
        if m and which:
            name, scroll, public = m.group(1), m.group(2), m.group(3)
            if scroll not in README_SCROLLS:
                raise SeenError(f"README row {name}: unknown scroll {scroll!r}")
            out[(README_SCROLLS[scroll], name, which)] = public
    return out


def _block_set(seg_path):
    tail = seg_path.split("/data/", 1)[-1]
    if "native9-" in tail:
        return "native9"
    if "aligned-" in tail:
        return "aligned"
    return None


def _labels(seg_path):
    return "pseudo" if "/pseudo/" in seg_path or seg_path.split("/data/", 1)[-1].startswith("pseudo/") else "human"


def build(cfg_path, rv2_path, readme_path):
    """The registry dict from the three pinned files."""
    cfg = json.loads(_pinned(cfg_path, "reader_v3_config"))
    rv2 = json.loads(_pinned(rv2_path, "reader_v2_config"))
    table = parse_readme(_pinned(readme_path, "ink9um_readme").decode())
    keys3 = {(d["segments_path"], s) for d in cfg["datasets"] for s in d["segments"]}
    keys2 = {(d["segments_path"], s) for d in rv2["datasets"] for s in d["segments"]}
    surfaces, possible = {}, []
    for i, ds in enumerate(cfg["datasets"]):
        scroll = SCROLLS.get(ds.get("sampling_scroll"))
        if not scroll:
            raise SeenError(f"dataset {i}: unknown sampling_scroll {ds.get('sampling_scroll')!r}")
        which, labels = _block_set(ds["segments_path"]), _labels(ds["segments_path"])
        for name in ds["segments"]:
            if which:
                public = table.get((scroll, name, which))
                if public is None:
                    raise SeenError(f"dataset {i}: {name} is not in the ink_9um README's {which} table")
                mapping = ("ink_9um README source-volume table" + (
                    " (Interpretation: the pseudo folder copies ink_9um's aligned naming)" if labels == "pseudo"
                    else ""))
            else:
                public, mapping = name, ("the key is the public segment id" if not re.fullmatch(r"\d{14}", name)
                                         else "the key is the public segment's 14-digit stamp")
            row = surfaces.setdefault((scroll, public), {
                "scroll": scroll, "public_segment": public, "names": [], "physical_keys": [], "blocks": []})
            if name not in row["names"]:
                row["names"].append(name)
            pk = ds.get("sampling_physical_segment_keys", {}).get(name)
            if pk and pk not in row["physical_keys"]:
                row["physical_keys"].append(pk)
            vol = ds.get("surface_volume_paths", {}).get(name, "")
            row["blocks"].append({"dataset": i, "segments_path": ds["segments_path"].split("<ROOT>/", 1)[-1],
                                  "source_family": ds.get("source_family"), "labels": labels,
                                  "volume": vol.split("<ROOT>/", 1)[-1], "mapping": mapping,
                                  "in_reader_v2": (ds["segments_path"], name) in keys2,
                                  "in_ink_9um": bool(which) and labels == "human"})
            alt = AMBIGUOUS_PSEUDO.get(scroll, {}).get(name)
            if alt and labels == "pseudo":
                possible.append({"scroll": scroll, "public_segment": alt, "names": [name], "dataset": i,
                                 "why": f"the other reading of pseudo-label name {name}: public {alt} if the folder "
                                        f"used public numbering (Interpretation)"})
    rows = sorted(surfaces.values(), key=lambda r: (r["scroll"], r["public_segment"]))
    ink9_public = {(s, p) for (s, _n, _w), p in table.items()}
    for r in rows:
        r["labels"] = sorted({b["labels"] for b in r["blocks"]})
        in9 = (r["scroll"], r["public_segment"]) in ink9_public
        if in9 and "human" not in r["labels"]:
            r["inherited_human_labels"] = "ink_9um's human labels of this surface, through Reader v2's initial run"
        r["readers"] = sorted({"reader-v3", "argus-v2"}
                              | ({"reader-v2"} if any(b["in_reader_v2"] for b in r["blocks"]) else set())
                              | ({"ink_9um"} if in9 else set()))
    counts = {}
    for r in rows:
        c = counts.setdefault(r["scroll"], {"public_segments": 0, "representations": 0})
        c["public_segments"] += 1
        c["representations"] += len(r["blocks"])
    reg = {
        "schema": SCHEMA,
        "about": "Every surface Reader V3 trained on, resolved to public segment ids, with the units its author "
                 "scored before release; built by `python -m kit.readerseen build` from the pinned files in "
                 "docs/evidence/readerseen/ (metadata only: no label, CT, preview, mesh or map). Never edit "
                 "by hand; `python -m kit.readerseen verify` rebuilds it and fails on drift.",
        "sources": SOURCES,
        "lineage": [
            {"reader": "ink_9um", "trained_on": "its README's 24 aligned and 5 native label sets",
             "label": "Sourced fact"},
            {"reader": "reader-v2", "init": rv2.get("checkpoint", "").split("<ROOT>/", 1)[-1],
             "description": rv2.get("description"), "keys": len(keys2), "label": "Sourced fact for the file"},
            {"reader": "reader-v3", "init": cfg.get("checkpoint", "").split("<ROOT>/", 1)[-1],
             "description": cfg.get("description"), "keys": len(keys3), "same_keys_as_reader_v2": keys2 == keys3,
             "label": "Sourced fact for the file"},
        ],
        "ink_9um_sets_all_in_reader_v3": ink9_public <= set(surfaces),
        "readers": READERS,
        "counts": {"keys": len(keys3), "public_segments": len(rows),
                   "representations": sum(len(r["blocks"]) for r in rows), "per_scroll": counts},
        "surfaces": rows,
        "possible": possible,
        "aliases": ALIASES,
        "selection": SELECTION,
        "same_roll_rule": "another piece of a roll a reader trained on is not called fresh: pieces share the "
                          "roll's number (PHerc0343P and PHerc0343; Interpretation)",
    }
    reg["digest"] = digest(reg)
    return reg


def digest(reg):
    body = {k: v for k, v in reg.items() if k != "digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write(reg, out=REGISTRY):
    Path(out).write_text(json.dumps(reg, indent=1, ensure_ascii=False) + "\n")


_REG = None


def load(path=None):
    global _REG
    if path:
        return json.loads(Path(path).read_text())
    if _REG is None:
        _REG = json.loads(REGISTRY.read_text())
        if _REG.get("schema") != SCHEMA or _REG.get("digest") != digest(_REG):
            raise SeenError(f"{REGISTRY}: digest out of step; run python -m kit.readerseen build")
    return _REG


# ---------------------------------------------------------------- names

def _fold(s):
    """NFKC, format characters and combining marks dropped, casefold: a full-width or zero-width-split spelling is
    the plain one."""
    t = unicodedata.normalize("NFKC", str(s))
    t = "".join(ch for ch in t if unicodedata.category(ch) not in ("Cf", "Mn"))
    return unicodedata.normalize("NFKC", t.casefold())


def norm(s):
    return re.sub(r"[^0-9a-z]", "", _fold(s))


_SPLIT = re.compile(r"[^0-9a-z]+")
_WIN = re.compile(r"w0*(\d+)(?:[a-z][0-9a-z]*)?")
_TAG = re.compile(r"(v\d+|\d+um|try\d+)")
_ORG = re.compile(r"pherc\w*$")         # an organizer annotation name starts with its scroll: pherc0139-w029


def _tokens(name):
    return [t for t in _SPLIT.split(_fold(name)) if t]


def _windows(name):
    """The winding windows a name holds ("w45", "w045v2" and "...-w045_2026012619" all hold w45). An organizer
    annotation name (pherc0139-w029) gives none: its number is not the public one."""
    toks = _tokens(name)
    out = set()
    for i, t in enumerate(toks):
        m = _WIN.fullmatch(t)
        if m and not (i and _ORG.match(toks[i - 1])):
            out.add(f"w{int(m.group(1))}")
    return out


def _short_ids(name):
    """Tokens that can stand for a segment on their own: at least 4 characters with a digit, not a window or a tag."""
    return {t for t in _tokens(name) if len(t) >= 4 and any(c.isdigit() for c in t)
            and not _WIN.fullmatch(t) and not _TAG.fullmatch(t)}


def name_meets(query, public, names=()):
    """True when a queried segment name means the public segment (or one of its training names)."""
    q = norm(query)
    if q == norm(public) or q in {norm(n) for n in names}:
        return True
    if _windows(query) & _windows(public):
        return True
    a, b = _short_ids(query), _short_ids(public)
    qt, pt = set(_tokens(query)), set(_tokens(public))
    return bool((len(qt) == 1 and a & pt) or (len(pt) == 1 and b & qt))


def scroll_key(s):
    """A scroll name folded: PHerc numbers zero-padded to four digits ("0139", "PHerc139" and "PHerc0139" meet),
    Paris 4 and Scroll 1 as PHercParis4."""
    k = norm(str(s or "").strip())
    k = {"paris4": "phercparis4", "scroll1": "phercparis4"}.get(k, k)
    m = re.fullmatch(r"(?:pherc)?0*(\d{3,4})([a-z]\w*)?", k)
    if m and (k.startswith("pherc") or len(m.group(1).lstrip("0")) >= 3):
        return f"pherc{int(m.group(1)):04d}{m.group(2) or ''}"
    m = re.fullmatch(r"pherc0*(\d{1,4})([a-z]\w*)?", k)
    return f"pherc{int(m.group(1)):04d}{m.group(2) or ''}" if m else k


def roll_of(s):
    """The roll a scroll name belongs to: its PHerc number, or the Paris roll for a Paris fragment."""
    k = scroll_key(s)
    m = re.match(r"(pherc(?:paris)?)0*(\d+)", k)
    return f"{m.group(1)}{int(m.group(2))}" if m else k


def reader_of(name, reg=None):
    reg = reg or load()
    want = re.sub(r"[\s_]+", "-", str(name or "").strip().lower())
    for rid, r in reg["readers"].items():
        if want == rid or want in [re.sub(r"[\s_]+", "-", a.lower()) for a in r["aliases"]]:
            return rid
    raise SeenError(f"no registry for reader {name!r}: this covers {', '.join(reg['readers'])} "
                    f"(check any other reader against its own published list)")


def _meets_any(seg, names):
    return any(name_meets(seg, n) for n in names or [])


def check(reader, scroll, segments=(), reg=None):
    """The verdict record for one site: reader (any alias), scroll and segment names."""
    reg = reg or load()
    rid = reader_of(reader, reg)
    meta = reg["readers"][rid]
    sk, rk = scroll_key(scroll), roll_of(scroll)
    if not sk:
        raise SeenError("a scroll is needed")
    train = [r for r in reg["surfaces"] if scroll_key(r["scroll"]) == sk]
    poss = [r for r in reg["possible"] if scroll_key(r["scroll"]) == sk]
    roll = sorted({r["scroll"] for r in reg["surfaces"] if roll_of(r["scroll"]) == rk and scroll_key(r["scroll"]) != sk})
    sel = [s for s in reg["selection"] if rid in s["readers"] and scroll_key(s["scroll"]) == sk]
    sel_roll = [s for s in reg["selection"] if rid in s["readers"] and roll_of(s["scroll"]) == rk
                and scroll_key(s["scroll"]) != sk]
    out = {"reader": rid, "asked_reader": reader, "scroll": scroll, "segments": [],
           "training_surfaces_on_scroll": len(train), "other_roll_pieces_trained": roll,
           "registry_digest": reg["digest"]}
    whole_sel = [s["by"] for s in sel if s["segments"] is None]

    def scroll_level(whole):
        if whole_sel:
            return "SELECTED", whole_sel
        if sel and whole:
            return "SELECTED", [f"the scroll holds selected units: {s['by']}" for s in sel]
        if sel:
            return "SAME-SCROLL", [f"selected units on this scroll ({s['by']}); different traces can be one sheet, "
                                   f"so check the site's geometry against them" for s in sel]
        if roll:
            return "SAME-ROLL", [f"Reader V3 trained on {', '.join(roll)}, another piece of this roll"]
        if sel_roll:
            return "SAME-ROLL", [f"selected on {s['scroll']}: {s['by']}" for s in sel_roll]
        return "FRESH-BY-LIST", ["no training surface, selection row or roll piece on this scroll"]

    verdicts = []
    for seg in segments:
        hits = [t for t in train if name_meets(seg, t["public_segment"], t["names"])]
        via = [al for al in reg.get("aliases", []) if scroll_key(al["scroll"]) == sk
               and norm(seg) in {norm(n) for n in al["names"]}]
        hits += [t for al in via for t in train if t["public_segment"] == al["public_segment"] and t not in hits]
        rec = {"segment": seg}
        if hits:
            exact = any(norm(seg) == norm(h["public_segment"]) for h in hits)
            rec.update(verdict="TRAINED",
                       match="exact" if exact else (f"registry alias, {via[0]['label']}: {via[0]['why']}" if via
                                                    else "training name, winding window or short id"),
                       surfaces=[{"public_segment": h["public_segment"], "names": h["names"],
                                  "labels": h["labels"], "datasets": [b["dataset"] for b in h["blocks"]]}
                                 for h in hits])
        elif any(name_meets(seg, p["public_segment"]) for p in poss):
            rec.update(verdict="TRAINED-POSSIBLE",
                       why=[p["why"] for p in poss if name_meets(seg, p["public_segment"])])
        elif any(s["segments"] and _meets_any(seg, s["segments"]) for s in sel):
            rec.update(verdict="SELECTED", why=[s["by"] for s in sel if s["segments"] and _meets_any(seg, s["segments"])])
        elif train and whole_sel:
            rec.update(verdict="SELECTED", why=whole_sel)
        elif train:
            rec.update(verdict="SAME-SCROLL",
                       why=[f"{len(train)} training surfaces on this scroll and none meets this name; check the "
                            f"site's geometry against the training meshes before calling it held out"])
        else:
            v, why = scroll_level(False)
            rec.update(verdict=v, why=why)
        out["segments"].append(rec)
        verdicts.append(rec["verdict"])
    if not segments:
        if train:
            verdicts.append("TRAINED")
            out["why"] = [f"the whole scroll holds {len(train)} training surfaces"]
        else:
            v, why = scroll_level(True)
            verdicts.append(v)
            out["why"] = why
    worst = max(verdicts, key=RANK.get)
    if meta.get("derived") and EXIT[worst] == 0:
        worst = "DERIVED-UNKNOWN"
        out.setdefault("why", []).append(f"{rid} is fine-tuned from Reader V3 on its own data: {meta['note']}")
    out["verdict"] = worst
    out["exit"] = EXIT[worst]
    out["held_out_by_list"] = EXIT[worst] == 0
    return out


def fmt(res):
    lines = [f"{res['verdict']}  {res['reader']} on {res['scroll']}"]
    for s in res["segments"]:
        extra = ""
        if s.get("surfaces"):
            extra = "; ".join(f"{h['public_segment']} ({'/'.join(h['labels'])}, datasets "
                              f"{','.join(map(str, h['datasets']))})" for h in s["surfaces"])
        how = f" [{s['match']}]" if s.get("match") and s["match"] != "exact" else ""
        lines.append(f"  {s['verdict']:<16} {s['segment']}{how}  {extra or '; '.join(s.get('why', []))}")
    for w in res.get("why", []):
        lines.append(f"  {w}")
    if res.get("other_roll_pieces_trained"):
        lines.append(f"  other pieces of this roll trained on: {', '.join(res['other_roll_pieces_trained'])}")
    lines.append(f"  training surfaces on this scroll: {res['training_surfaces_on_scroll']}; exit {res['exit']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def build_parser(p):
    sub = p.add_subparsers(dest="readerseen_cmd", required=True)
    c = sub.add_parser("check", help="verdict for a site: TRAINED, SELECTED, SAME-SCROLL, SAME-ROLL or FRESH")
    c.add_argument("--reader", required=True, help="reader-v3, reader-v2, argus-v2")
    c.add_argument("--scroll", required=True, help="scroll id, e.g. PHerc0139")
    c.add_argument("--segment", action="append", default=[], help="segment name (repeat for several)")
    c.add_argument("--json", action="store_true", help="print the verdict record as JSON")
    l = sub.add_parser("list", help="the training surfaces and selection rows")
    l.add_argument("--reader", default="reader-v3", help="which reader's selection rows to show")
    l.add_argument("--scroll", help="only this scroll")
    l.add_argument("--json", action="store_true", help="the rows as JSON")
    sub.add_parser("readers", help="the readers this registry covers and their aliases")
    sub.add_parser("verify", help="rebuild from the pinned copies and fail on any drift")
    b = sub.add_parser("build", help="write the registry from the three pinned files")
    b.add_argument("--config", default=str(EVIDENCE / SOURCES["reader_v3_config"]["file"]),
                   help="Reader V3's list; must match the pinned sha256")
    b.add_argument("--rv2-config", default=str(EVIDENCE / SOURCES["reader_v2_config"]["file"]),
                   help="Reader v2's list (lineage and key comparison)")
    b.add_argument("--ink9um-readme", default=str(EVIDENCE / SOURCES["ink9um_readme"]["file"]),
                   help="the annotation name to public segment table")
    b.add_argument("--out", default=str(REGISTRY), help="where to write the registry")
    p.set_defaults(func=cmd_readerseen)
    return p


def cmd_readerseen(a):
    try:
        if a.readerseen_cmd == "build":
            reg = build(a.config, a.rv2_config, a.ink9um_readme)
            write(reg, a.out)
            print(f"{a.out}: {reg['counts']['public_segments']} public segments, "
                  f"{reg['counts']['representations']} representations, {reg['counts']['keys']} keys; "
                  f"digest {reg['digest'][:16]}")
            return 0
        if a.readerseen_cmd == "verify":
            fresh = build(*(EVIDENCE / SOURCES[k]["file"] for k in ("reader_v3_config", "reader_v2_config",
                                                                    "ink9um_readme")))
            have = json.loads(REGISTRY.read_text())
            if have != fresh:
                print(f"{REGISTRY.relative_to(ROOT)}: differs from a rebuild of the pinned copies; run "
                      f"python -m kit.readerseen build", file=sys.stderr)
                return 1
            print(f"ok: {fresh['counts']['public_segments']} public segments, digest {fresh['digest'][:16]}")
            return 0
        reg = load()
        if a.readerseen_cmd == "readers":
            for rid, r in reg["readers"].items():
                print(f"{rid}: {', '.join(r['aliases'])}\n  {r['note']}")
            return 0
        if a.readerseen_cmd == "list":
            rid = reader_of(a.reader, reg)
            rows = [r for r in reg["surfaces"] if not a.scroll or scroll_key(r["scroll"]) == scroll_key(a.scroll)]
            sel = [s for s in reg["selection"] if rid in s["readers"]
                   and (not a.scroll or scroll_key(s["scroll"]) == scroll_key(a.scroll))]
            if a.json:
                print(json.dumps({"reader": rid, "surfaces": rows, "selection": sel}, indent=1, ensure_ascii=False))
                return 0
            for r in rows:
                print(f"{r['scroll']:<12} {r['public_segment']:<46} {'/'.join(r['labels']):<12} "
                      f"as {', '.join(r['names'])}")
            for s in sel:
                print(f"{s['scroll']:<12} SELECTED {', '.join(s['segments'] or ['whole scroll'])}: {s['by']}")
            print(f"{len(rows)} training surfaces, {len(sel)} selection rows ({rid})")
            return 0
        if a.readerseen_cmd == "check":
            res = check(a.reader, a.scroll, a.segment, reg)
            print(json.dumps(res, indent=1, ensure_ascii=False) if a.json else fmt(res))
            return res["exit"]
    except (SeenError, ValueError, OSError) as exc:
        print(f"readerseen: {exc}", file=sys.stderr)
        return 2
    return 2


def main(argv=None):
    p = build_parser(argparse.ArgumentParser(prog="python -m kit.readerseen"))
    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
