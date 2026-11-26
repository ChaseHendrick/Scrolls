"""Scroll dataset card checker: SHA256SUMS, provenance, license, caveats and the spent list of a dataset release.

Checks a Hugging Face dataset, or a local folder about to be uploaded as one, against the scroll dataset card
standard (docs/standards/dataset-card.md, version 0.1). The standard asks for three files at the top of the dataset:

    README.md          the card: YAML front matter (license, pretty_name, tags) and the required sections
    SHA256SUMS         `sha256sum` lines for every data file, so `sha256sum -c SHA256SUMS` checks a download
    provenance.json    the machine-readable record: sources and their licenses, code commit, caveats, spent list

Every rule can fail: a planted bad card fails each one in tests/test_datacard.py.

    python -m kit.datacard check DIR                       # a local folder; hashes every listed file
    python -m kit.datacard check OWNER/NAME [--revision R] # a Hugging Face dataset, read only; LFS files are checked
                                                           # against the Hub's own SHA-256, small files downloaded
    python -m kit.datacard check OWNER/NAME --overlay DIR  # the Hub dataset as it will be after uploading DIR
    python -m kit.datacard sums DIR|OWNER/NAME [--overlay DIR] [--write]   # print (or write) SHA256SUMS
    python -m kit.datacard template OUT_DIR [--synthetic]  # write a skeleton README.md and provenance.json
    ... [--json]                                           # one JSON record instead of lines

Exit 0 when no rule fails (warnings allowed), 1 when one fails, 2 when the input cannot be read. Standard library
only; read only except `sums --write` and `template`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

STANDARD = "scroll-dataset-card/0.1"
EXIT_OK, EXIT_FAIL, EXIT_INPUT = 0, 1, 2
CARD, SUMS, PROV = "README.md", "SHA256SUMS", "provenance.json"
# files a SHA256SUMS need not list: the card changes with every edit, and the sums file cannot list itself
EXEMPT = {CARD, SUMS, ".gitattributes"}
KINDS = {"real-derived", "synthetic", "model-output", "labels", "geometry", "tabular", "images", "volumes"}
TRUTH_USES = {"training", "tuning", "testing", "released"}
# Hosts of the Vesuvius Challenge open data: CC BY-NC 4.0 unless otherwise noted for specific assets, and the
# EduceLab-Scrolls data under its own terms (https://scrollprize.org/data, read 26 Nov 2026)
VC_HOSTS = ("scrollprize.org", "dl.ash2txt.org", "vesuvius-challenge-open-data")
VC_LICENSE = "cc-by-nc-4.0"

# Required sections: the key, then the headings (any level, case-insensitive) that satisfy it
SECTIONS = {
    "contents": ("what is in it", "contents", "what's in it", "dataset structure"),
    "provenance": ("how it was made", "provenance", "how it is made"),
    "limits": ("limits", "uses and limits", "caveats", "limitations", "notes"),
    "spent": ("spent seeds and truth", "spent list", "spent truth", "spent seeds"),
    "license": ("license and credit", "license", "licence and credit", "credit"),
    "changelog": ("changelog", "changes", "versions"),
}
RECOMMENDED = {"citation": ("citation", "cite")}

HEX64 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
SUM_LINE = re.compile(r"^([0-9a-fA-F]{64}) [ *](.+)$")
# "letters were read", "text was found": an ink map is model output, not a reading
READING = re.compile(r"\b(letters?|text|words?|characters?|titles?)\b[^.\n]{0,40}?\b(was|were|is|are|has been|have been)"
                     r"\s+(found|read|revealed|recovered|deciphered)\b", re.I)
NEGATION = re.compile(r"\b(not|no|nothing|never|none|without|neither|nor)\b", re.I)


class InputError(Exception):
    """The dataset or folder cannot be read."""


# ------------------------------------------------------------------ parsing

def front_matter(text):
    """(metadata, body) of a card. Reads the top-level keys of the YAML block: scalars, inline lists and block lists
    of scalars; nested blocks (configs) are kept as True. Enough for license, pretty_name and tags."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    meta, key = {}, None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw.startswith((" ", "-", "\t")):
            k, _, v = raw.partition(":")
            key, v = k.strip(), v.strip()
            if v.startswith("[") and v.endswith("]"):
                meta[key] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
            elif v:
                meta[key] = v.strip("'\"")
            else:
                meta[key] = []
        elif key is not None and isinstance(meta.get(key), list):
            s = raw.strip()
            if s.startswith("- ") and ":" not in s[2:]:
                meta[key].append(s[2:].strip().strip("'\""))
            else:
                meta[key] = True     # a nested block, such as configs
    return meta, "\n".join(lines[end + 1:])


def headings(body):
    """{normalized heading: text under it up to the next heading of the same or a higher level}. Headings inside
    fenced code blocks are not headings."""
    lines, marks, in_code = body.splitlines(), [], False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        m = None if in_code else re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m:
            marks.append((i, len(m.group(1)), m.group(2).strip().lower()))
    out = {}
    for k, (i, level, name) in enumerate(marks):
        stop = next((j for j, lv, _ in marks[k + 1:] if lv <= level), len(lines))
        out.setdefault(name, "\n".join(lines[i + 1:stop]).strip())
    return out


def find_section(heads, aliases):
    """(heading, text) of the first heading matching one of the aliases (exact, or alias as a prefix)."""
    for h, text in heads.items():
        clean = re.sub(r"[`*_]", "", h).strip()
        for a in aliases:
            if clean == a or clean.startswith(a + " ") or clean.startswith(a + ":"):
                return h, text
    return None, None


def parse_sums(text):
    """([(digest, path)], [bad line numbers]). Accepts `sha256sum` text and binary marks and a leading './'."""
    rows, bad = [], []
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        m = SUM_LINE.match(line)
        if not m:
            bad.append(i)
            continue
        path = m.group(2)
        rows.append((m.group(1).lower(), path[2:] if path.startswith("./") else path))
    return rows, bad


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def seed_items(seeds):
    """[(lo, hi)] from a spent seed list of ints, "A-B" ranges and "A..B" ranges."""
    out = []
    for s in seeds:
        if isinstance(s, bool):
            raise ValueError(f"seed {s!r} is not an integer")
        if isinstance(s, int):
            out.append((s, s))
            continue
        m = re.fullmatch(r"\s*(\d+)\s*(?:-|\.\.|to)\s*(\d+)\s*", str(s))
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if hi < lo:
                raise ValueError(f"seed range {s!r} runs backward")
            out.append((lo, hi))
        elif str(s).strip().isdigit():
            out.append((int(s), int(s)))
        else:
            raise ValueError(f"seed {s!r} is neither an integer nor a range A-B")
    return out


def reading_claims(text):
    """Sentences that say letters or text were found or read, without a negation in the same sentence."""
    hits = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n\s*\n", text):
        for m in READING.finditer(sentence):
            if not NEGATION.search(sentence):
                hits.append(" ".join(sentence.split())[:160])
                break
    return hits


# ------------------------------------------------------------------ sources of files

class Folder:
    """A local dataset folder."""

    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_dir():
            raise InputError(f"{root}: not a folder")
        self.name = str(self.root)

    def read(self, rel):
        p = self.root / rel
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def files(self):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")
                      if p.is_file() and ".git" not in p.relative_to(self.root).parts
                      and ".cache" not in p.relative_to(self.root).parts)

    def digest(self, rel, budget):
        p = self.root / rel
        return (sha256_file(p), "hashed") if p.is_file() else (None, "missing")


class HubDataset:
    """A Hugging Face dataset, read over HTTPS with no token (public datasets only)."""

    API = "https://huggingface.co/api/datasets/{repo}/tree/{rev}?recursive=true&expand=false"
    RAW = "https://huggingface.co/datasets/{repo}/resolve/{rev}/{path}"

    def __init__(self, repo, revision="main", opener=None):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise InputError(f"{repo}: not OWNER/NAME")
        self.repo, self.rev, self.name = repo, revision, f"hf://datasets/{repo}@{revision}"
        self._open = opener or urllib.request.urlopen
        self._tree = None
        self._lock = threading.Lock()

    def _get(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "scrolls-kit-datacard"})
        try:
            with self._open(req, timeout=60) as r:
                return r.read(), dict(r.headers.items()) if hasattr(r, "headers") else {}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, {}
            raise InputError(f"{url}: HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise InputError(f"{url}: {e.reason}") from e

    def tree(self):
        if self._tree is None:
            url = self.API.format(repo=self.repo, rev=urllib.parse.quote(self.rev, safe=""))
            items = []
            while url:
                data, headers = self._get(url)
                if data is None:
                    raise InputError(f"{self.repo}: dataset or revision not found")
                items += [x for x in json.loads(data) if x.get("type") == "file"]
                m = re.search(r'<([^>]+)>;\s*rel="next"', headers.get("Link", headers.get("link", "")))
                url = m.group(1) if m else None
            self._tree = {x["path"]: x for x in items}
        return self._tree

    def read(self, rel):
        if rel not in self.tree():
            return None
        data, _ = self._get(self.RAW.format(repo=self.repo, rev=self.rev, path=urllib.parse.quote(rel)))
        return None if data is None else data.decode("utf-8")

    def files(self):
        return sorted(self.tree())

    def digest(self, rel, budget):
        """(sha256 or None, how): the Hub's LFS SHA-256 when the file is in LFS or Xet, else the file's own hash
        when it fits the download budget (a one-item list of bytes left)."""
        item = self.tree().get(rel)
        if item is None:
            return None, "missing"
        lfs = item.get("lfs") or {}
        if HEX64.match(str(lfs.get("oid", ""))):
            return lfs["oid"], "hub"
        size = int(item.get("size", 0))
        with self._lock:
            if size > budget[0]:
                return None, "unverified"
            budget[0] -= size
        data, _ = self._get(self.RAW.format(repo=self.repo, rev=self.rev, path=urllib.parse.quote(rel)))
        return (hashlib.sha256(data).hexdigest(), "hashed") if data is not None else (None, "missing")


class Overlay:
    """A Hub dataset as it will be once the files of a local folder are uploaded over it: the folder's files win,
    the rest come from the Hub. Lets a card, provenance.json and SHA256SUMS be checked before the upload."""

    def __init__(self, base, folder):
        self.base, self.top = base, Folder(folder)
        self.name = f"{base.name} + {self.top.name}"

    def read(self, rel):
        text = self.top.read(rel)
        return text if text is not None else self.base.read(rel)

    def files(self):
        return sorted(set(self.base.files()) | set(self.top.files()))

    def digest(self, rel, budget):
        if (self.top.root / rel).is_file():
            return self.top.digest(rel, budget)
        return self.base.digest(rel, budget)


def source_for(target, revision="main", opener=None, overlay=None):
    if Path(target).is_dir():
        if overlay:
            raise InputError("--overlay is for a Hugging Face dataset, not a folder")
        return Folder(target)
    if Path(target).exists():
        raise InputError(f"{target}: give the dataset folder, not a file")
    hub = HubDataset(target, revision, opener)
    return Overlay(hub, overlay) if overlay else hub


# ------------------------------------------------------------------ the check

def check(src, max_download_mb=20.0, workers=8):
    """Run every rule on a Folder or HubDataset. Returns {"dataset", "standard", "verdict", "findings", "counts"}."""
    findings = []

    def add(rule, level, message):
        findings.append({"rule": rule, "level": level, "message": message})

    card = src.read(CARD)
    if card is None:
        raise InputError(f"{src.name}: no {CARD}")
    meta, body = front_matter(card)
    heads = headings(body)
    files = src.files()

    # 1. front matter
    lic = meta.get("license")
    if isinstance(lic, list):
        lic = lic[0] if len(lic) == 1 else None
    if not lic or not isinstance(lic, str):
        add("front-matter.license", "fail", "front matter has no single `license` id")
        lic = None
    else:
        add("front-matter.license", "pass", f"license {lic}")
    if meta.get("pretty_name"):
        add("front-matter.pretty_name", "pass", str(meta["pretty_name"]))
    else:
        add("front-matter.pretty_name", "fail", "front matter has no `pretty_name`")
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    if "vesuvius-challenge" in tags:
        add("front-matter.tags", "pass", "tagged vesuvius-challenge")
    else:
        add("front-matter.tags", "warn", "add the tag `vesuvius-challenge` so the community can find it")

    # 2. sections
    for key, aliases in SECTIONS.items():
        h, text = find_section(heads, aliases)
        if h is None:
            add(f"section.{key}", "fail", f"no section headed {aliases[0].capitalize()!r} (or {', '.join(aliases[1:3])})")
        elif not text or not re.search(r"\w", re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)):
            add(f"section.{key}", "fail", f"section {h!r} is empty")
        else:
            add(f"section.{key}", "pass", f"section {h!r}")
    for key, aliases in RECOMMENDED.items():
        h, _ = find_section(heads, aliases)
        add(f"section.{key}", "pass" if h else "warn", f"section {h!r}" if h else f"no {key} section")
    _, limits = find_section(heads, SECTIONS["limits"])
    if limits is not None and not re.search(r"^\s*[-*] |\n\s*\d+\. ", limits, re.M):
        add("section.limits-items", "warn", "list each limit as its own bullet")
    if "sha256sum -c" in body:
        add("card.verify-command", "pass", "card shows `sha256sum -c SHA256SUMS`")
    else:
        add("card.verify-command", "warn", "card does not show users `sha256sum -c SHA256SUMS`")

    # 3. provenance.json
    prov = None
    raw = src.read(PROV)
    if raw is None:
        add("provenance.present", "fail", f"no {PROV}")
    else:
        try:
            prov = json.loads(raw)
            if not isinstance(prov, dict):
                raise ValueError("not an object")
            add("provenance.present", "pass", PROV)
        except ValueError as e:
            add("provenance.present", "fail", f"{PROV} is not a JSON object: {e}")
    if prov is not None:
        _check_provenance(prov, lic, body, card, add)

    # 4. SHA256SUMS
    raw = src.read(SUMS)
    counts = {"files": len(files), "listed": 0, "verified": 0, "unverified": 0}
    if raw is None:
        add("sums.present", "fail", f"no {SUMS}")
    else:
        rows, bad = parse_sums(raw)
        counts["listed"] = len(rows)
        if bad:
            add("sums.format", "fail", f"{len(bad)} line(s) are not `<sha256>  <path>` (first: line {bad[0]})")
        elif not rows:
            add("sums.format", "fail", f"{SUMS} lists no file")
        else:
            add("sums.format", "pass", f"{len(rows)} lines")
        paths = [p for _, p in rows]
        dup = sorted({p for p in paths if paths.count(p) > 1})
        unsafe = [p for p in paths if p.startswith("/") or ".." in Path(p).parts]
        if dup:
            add("sums.unique", "fail", f"{len(dup)} path(s) listed twice, such as {dup[0]}")
        if unsafe:
            add("sums.paths", "fail", f"{len(unsafe)} path(s) absolute or outside the dataset, such as {unsafe[0]}")
        if SUMS in paths:
            add("sums.self", "fail", f"{SUMS} lists itself, which can never check")
        if CARD in paths:
            add("sums.card", "warn", f"{SUMS} lists {CARD}: the next card edit breaks `sha256sum -c`; leave it out")
        listed = set(paths)
        unlisted = [f for f in files if f not in listed and f not in EXEMPT]
        missing = [p for p in sorted(listed) if p not in set(files)]
        if unlisted:
            add("sums.coverage", "fail", f"{len(unlisted)} file(s) not in {SUMS}, such as {unlisted[0]}")
        else:
            add("sums.coverage", "pass", f"every file but {', '.join(sorted(EXEMPT))} is listed")
        if missing:
            add("sums.missing", "fail", f"{len(missing)} listed file(s) are not in the dataset, such as {missing[0]}")
        budget = [int(max_download_mb * 1e6)]
        wanted = [(d, p) for d, p in rows if p not in missing and p != SUMS]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            got_all = list(pool.map(lambda r: src.digest(r[1], budget), wanted))
        wrong = []
        for (digest, path), (got, _how) in zip(wanted, got_all):
            if got is None:
                counts["unverified"] += 1
            elif got != digest:
                wrong.append(path)
            else:
                counts["verified"] += 1
        if wrong:
            add("sums.match", "fail", f"{len(wrong)} file(s) do not match their SHA-256, such as {wrong[0]}")
        elif counts["verified"]:
            add("sums.match", "pass", f"{counts['verified']} file(s) match")
        if counts["unverified"]:
            add("sums.unverified", "warn", f"{counts['unverified']} small file(s) past the download budget were not "
                                           "hashed; raise --max-download-mb or check a local copy")

    fails = [f for f in findings if f["level"] == "fail"]
    return {"dataset": src.name, "standard": STANDARD, "verdict": "FAIL" if fails else "PASS",
            "fails": len(fails), "warnings": sum(f["level"] == "warn" for f in findings),
            "counts": counts, "findings": findings}


def _check_provenance(prov, lic, body, card, add):
    std = prov.get("standard")
    if std != STANDARD:
        add("provenance.standard", "fail", f"`standard` is {std!r}, expected {STANDARD!r}")
    for key in ("dataset", "version", "updated"):
        if not prov.get(key):
            add(f"provenance.{key}", "fail", f"`{key}` is missing")
    if prov.get("updated") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(prov["updated"])):
        add("provenance.updated", "fail", "`updated` is not YYYY-MM-DD")

    kinds = prov.get("kind") or []
    kinds = [kinds] if isinstance(kinds, str) else kinds
    unknown = [k for k in kinds if k not in KINDS]
    if not kinds or unknown:
        add("provenance.kind", "fail", f"`kind` must list one or more of {sorted(KINDS)}"
                                       + (f"; unknown {unknown}" if unknown else ""))

    plic = prov.get("license")
    if lic and plic and str(plic).lower() != str(lic).lower():
        add("license.match", "fail", f"card says {lic}, {PROV} says {plic}")
    elif not plic:
        add("license.match", "fail", f"{PROV} has no `license`")
    else:
        add("license.match", "pass", f"card and {PROV} agree: {plic}")
    out_lic = str(plic or lic or "").lower()

    sources = prov.get("sources")
    if not isinstance(sources, list) or not sources:
        add("provenance.sources", "fail", "`sources` must list what the data came from (scans, meshes, code)")
        sources = []
    for i, s in enumerate(sources):
        if not isinstance(s, dict) or not s.get("name") or not s.get("license") or not (s.get("url") or s.get("ref")):
            add("provenance.sources", "fail", f"source {i} needs `name`, `license` and a `url` or `ref`")
            continue
        slic = str(s["license"]).lower()
        if any(h in str(s.get("url", "")) for h in VC_HOSTS) and "-nc" not in slic and slic != "other":
            add("license.vesuvius", "fail", f"source {s['name']!r} is Vesuvius Challenge open data, which is "
                                            f"{VC_LICENSE} unless noted otherwise (then `other`), not {slic}")
        if "-nc" in slic and "-nc" not in out_lic:
            add("license.inherit", "fail", f"source {s['name']!r} is noncommercial ({slic}); the dataset's "
                                           f"license {out_lic or '(none)'} drops that")
        if "-sa" in slic and "-sa" not in out_lic:
            add("license.inherit", "fail", f"source {s['name']!r} is share-alike ({slic}); the dataset's "
                                           f"license {out_lic or '(none)'} drops that")
        if "-nd" in slic:
            add("license.inherit", "fail", f"source {s['name']!r} is no-derivatives ({slic}): it cannot be "
                                           "redistributed changed")

    code = prov.get("code")
    if not isinstance(code, dict) or not code.get("repo") or not COMMIT.match(str(code.get("commit", ""))):
        add("provenance.code", "fail", "`code` needs `repo` and a hex `commit` of the code that built the release")
    else:
        add("provenance.code", "pass", f"{code['repo']} at {code['commit']}")

    caveats = prov.get("caveats")
    if not isinstance(caveats, list) or not [c for c in caveats if str(c).strip()]:
        add("provenance.caveats", "fail", "`caveats` must list at least one limit, as the card does")

    model_output = bool(prov.get("model_output")) or "model-output" in kinds
    if model_output:
        if not re.search(r"model output", body, re.I):
            add("model-output.label", "fail", "the data is model output but the card never says so")
        else:
            add("model-output.label", "pass", "card labels model output")
    claims = reading_claims(body)
    if claims:
        add("model-output.reading", "fail", f"the card says letters or text were found or read: {claims[0]!r}")

    spent = prov.get("spent")
    if not isinstance(spent, dict):
        add("spent.present", "fail", "`spent` is missing: list the seeds and truth this release used up, or say why "
                                     "none (`none_reason`)")
        return
    seeds, truth, held = spent.get("seeds") or [], spent.get("truth") or [], spent.get("held_back") or []
    if not (seeds or truth or held or str(spent.get("none_reason", "")).strip()):
        add("spent.present", "fail", "`spent` is empty and gives no `none_reason`")
    else:
        add("spent.present", "pass", f"{len(seeds)} seed item(s), {len(truth)} truth item(s), {len(held)} held back")
    if "synthetic" in kinds and not seeds:
        add("spent.seeds", "fail", "synthetic data must list the seeds it used, so no one tests on them as fresh")
    try:
        items = seed_items(seeds)
    except ValueError as e:
        add("spent.seeds", "fail", str(e))
        items = []
    flat = re.sub(r"[,_   ](?=\d{3}\b)", "", card)
    absent = [f"{lo}" if lo == hi else f"{lo}-{hi}" for lo, hi in items
              if str(lo) not in flat or str(hi) not in flat]
    if absent:
        add("spent.seeds-in-card", "fail", f"{len(absent)} spent seed item(s) are not written in the card, such as "
                                           f"{absent[0]}")
    for i, t in enumerate(truth):
        if not isinstance(t, dict) or not t.get("what") or not t.get("scope"):
            add("spent.truth", "fail", f"truth item {i} needs `what` and `scope`")
        elif t.get("use") not in TRUTH_USES:
            add("spent.truth", "fail", f"truth item {i}: `use` must be one of {sorted(TRUTH_USES)}")
    for i, t in enumerate(held):
        if not isinstance(t, dict) or not t.get("what") or not t.get("scope"):
            add("spent.held_back", "fail", f"held-back item {i} needs `what` and `scope`")


# ------------------------------------------------------------------ sums and template

def make_sums(root, max_download_mb=2000.0, workers=8):
    """SHA256SUMS text for every file of a folder, Hub dataset or overlay except the exempt ones, sorted, paths
    without './'. A Hub file's digest is the Hub's LFS SHA-256 or the hash of its download; raises InputError when
    a file cannot be hashed within the download budget, so a sums file never leaves a file out."""
    src = root if hasattr(root, "digest") else Folder(root)
    paths = [p for p in src.files() if p not in EXEMPT]
    budget = [int(max_download_mb * 1e6)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        got = list(pool.map(lambda p: src.digest(p, budget), paths))
    short = [p for p, (d, _) in zip(paths, got) if d is None]
    if short:
        raise InputError(f"{len(short)} file(s) could not be hashed (such as {short[0]}); raise --max-download-mb")
    return "".join(f"{d}  {p}\n" for p, (d, _) in zip(paths, got))


def template(synthetic=False):
    """(README.md text, provenance dict) skeletons that pass the structural rules once filled in."""
    seeds = [20270101001, "20270101101-20270101160"] if synthetic else []
    prov = {
        "standard": STANDARD,
        "dataset": "OWNER/NAME",
        "version": "1.0.0",
        "updated": "2027-01-01",
        "kind": ["synthetic", "volumes"] if synthetic else ["real-derived", "geometry"],
        "license": "cc-by-4.0" if synthetic else VC_LICENSE,
        "sources": ([{"name": "Scrolls kit simulator", "url": "https://github.com/ChaseHendrick/Scrolls",
                      "license": "apache-2.0", "ref": "kit/scrollsim2.py"}] if synthetic else
                    [{"name": "Vesuvius Challenge open data", "url": "https://scrollprize.org/data",
                      "license": VC_LICENSE, "ref": "SCROLL / VOLUME id"}]),
        "code": {"repo": "https://github.com/OWNER/REPO", "commit": "0000000",
                 "command": "python -m TOOL ..."},
        "model_output": False,
        "caveats": ["One plain sentence per limit, the same ones the card lists."],
        "spent": {"seeds": seeds,
                  "truth": [] if synthetic else [{"what": "ink labels", "scope": "SCROLL segment SEGMENT",
                                                  "use": "testing", "note": "scored in this release"}],
                  "held_back": [],
                  "none_reason": ""},
    }
    seed_line = ("Seeds 20270101001 and 20270101101 to 20270101160 built this release: do not use them as fresh "
                 "test seeds." if synthetic else
                 "The ink labels of SCROLL segment SEGMENT were used to score this release: a later test on them is "
                 "not held out.")
    readme = f"""---
license: {prov['license']}
pretty_name: NAME
tags:
- vesuvius-challenge
- herculaneum
---

# NAME

One paragraph: what this is, who it is for, and the one caveat a user must not miss.

## What is in it

| Part | What | Count | Size |
| --- | --- | ---: | ---: |

`SHA256SUMS` covers every file except this card. Check a download with:

```bash
hf download OWNER/NAME --repo-type dataset --local-dir NAME
cd NAME && sha256sum -c SHA256SUMS
```

## How it was made

Sources with their versions, the code with its commit, and the command. `provenance.json` holds the same record.

## Limits

- One bullet per limit.

## Spent seeds and truth

{seed_line}

## License and credit

The license, why (it can be no looser than its sources), and who to credit.

## Citation

```bibtex
@misc{{name2027,
  author = {{OWNER}}, title = {{NAME}}, year = {{2027}},
  howpublished = {{\\url{{https://huggingface.co/datasets/OWNER/NAME}}}}
}}
```

## Changelog

- **2027-01-01**: first release.
"""
    return readme, prov


# ------------------------------------------------------------------ command line

def _print(rec):
    print(f"{rec['dataset']}: {rec['verdict']} against {rec['standard']} "
          f"({rec['fails']} failing, {rec['warnings']} warnings)")
    order = {"fail": 0, "warn": 1, "pass": 2}
    for f in sorted(rec["findings"], key=lambda f: order[f["level"]]):
        print(f"  {f['level'].upper():4}  {f['rule']}: {f['message']}")
    c = rec["counts"]
    print(f"  files {c['files']}, listed in SHA256SUMS {c['listed']}, hashes checked {c['verified']}, "
          f"not checked {c['unverified']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kit.datacard", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="check a dataset folder or a Hugging Face dataset against the standard")
    p.add_argument("target", help="a local folder, or OWNER/NAME of a Hugging Face dataset")
    p.add_argument("--revision", default="main", help="branch, tag or commit of a Hugging Face dataset")
    p.add_argument("--max-download-mb", type=float, default=20.0,
                   help="download budget for hashing small non-LFS files of a Hub dataset (default 20)")
    p.add_argument("--overlay", metavar="DIR", help="check a Hub dataset as it will be after uploading DIR's files")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("sums", help="print SHA256SUMS for a folder or Hub dataset (every file but README.md, "
                                    "SHA256SUMS and .gitattributes)")
    p.add_argument("folder", help="a local folder, or OWNER/NAME of a Hugging Face dataset")
    p.add_argument("--revision", default="main", help="branch, tag or commit of a Hub dataset")
    p.add_argument("--overlay", metavar="DIR", help="a Hub dataset with DIR's files uploaded over it")
    p.add_argument("--max-download-mb", type=float, default=2000.0,
                   help="download budget for hashing non-LFS Hub files (default 2000)")
    p.add_argument("--write", action="store_true", help="write SHA256SUMS into the folder (or the --overlay folder)")
    p = sub.add_parser("template", help="write a skeleton README.md and provenance.json")
    p.add_argument("out")
    p.add_argument("--synthetic", action="store_true", help="a synthetic dataset: seeds instead of scans")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "check":
            rec = check(source_for(a.target, a.revision, overlay=a.overlay), a.max_download_mb)
            print(json.dumps(rec, indent=1)) if a.json else _print(rec)
            return EXIT_FAIL if rec["fails"] else EXIT_OK
        if a.cmd == "sums":
            src = source_for(a.folder, a.revision, overlay=a.overlay)
            text = make_sums(src, a.max_download_mb)
            if a.write:
                where = Path(a.overlay) if a.overlay else src.root if isinstance(src, Folder) else None
                if where is None:
                    raise InputError("--write needs a local folder or --overlay DIR")
                (where / SUMS).write_text(text, encoding="utf-8")
                print(f"wrote {where / SUMS}: {text.count(chr(10))} files")
            else:
                sys.stdout.write(text)
            return EXIT_OK
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        readme, prov = template(a.synthetic)
        for name, text in ((CARD, readme), (PROV, json.dumps(prov, indent=2) + "\n")):
            if (out / name).exists():
                print(f"{out / name} exists: left alone", file=sys.stderr)
                return EXIT_INPUT
            (out / name).write_text(text, encoding="utf-8")
            print(f"wrote {out / name}")
        return EXIT_OK
    except InputError as e:
        print(f"datacard: {e}", file=sys.stderr)
        return EXIT_INPUT


if __name__ == "__main__":
    sys.exit(main())
