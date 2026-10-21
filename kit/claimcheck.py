"""Claims check: every number in the README's "Novel findings" section traced to a source with a digest.

`python -m kit.claimcheck items|trace|add|pin|check|results`.

items    the blocks of the README's "## Novel findings" section (list items and paragraphs, up to the next "## "
         heading) and the numbers each one states, after leaving out dates, years, times, issue and PR numbers,
         references such as "finding 12" or "lines 200-207", code spans, link targets and identifiers that contain digits
         (PHerc0841, w045, ink_9um, 25f3c93).
trace    one block's numbers against sources: for each number, the sources whose own numbers match it, or none.
suggest  candidate sources for one block: the repository files its links name first, then results units, chosen
         greedily by how many of the still untraced numbers each holds. A reviewer reads each before adding it.
add      write or replace one block's entry in the ledger (docs/claims/sources.json): its sources, each pinned to
         its sha256 now, and a reason for each number that is a setting, a count or a derived value rather than a
         number any source holds. It refuses an entry that leaves a number with no source and no reason.
pin      recompute every source's sha256; with --write, store the new pins (only after reading what changed).
check    exit 1 when a block that states a number has no ledger entry, a number matches none of its block's
         sources and has no reason, a source is missing or its sha256 differs from the pin, a reason names a
         number the block no longer states, or a ledger entry names a block the README no longer has; and when
         a results unit that cites no existing file is not in the ledger's baseline of such units (a ratchet).
results  the docs/results.json units that cite no existing repository file (their `source`, `evidence` or
         other string values; a community row may cite its publication's URL instead); with --write, store them
         as the baseline, which only a reviewer should do (it accepts every unsourced unit listed).

A source is a docs/results.json unit (`r:SECTION/INDEX`, `r:SECTION` for a dict section, or `r:ID` for a unit with
an explicit `id`; the digest is the unit's canonical JSON without `id` and `causal`, the same unit_sha256 kit
causal pins), or a repository file or folder (a folder's digest covers every file in it). A number matches a
source when the source holds a number that rounds to it at the README's precision (0.738 matches 0.7382, an
integer only an equal integer; "96 %" also matches 0.96), so a README number that is a rounding of a measured value
passes and one that is not fails. When docs/causal/claims.json (kit causal) exists, its `source` lines for a
Novel findings item are read as sources of that item too, so the two tools share one list of causes.

What it does not do: a match shows that a pinned source holds the number, not that it is the right quantity in
that source (a small integer can match by chance in a long log); the reasons are a reviewer's statement. It
checks the README's numbers, not its words. Standard library only.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

SCHEMA = "claimcheck/1"
README = "README.md"
LEDGER = "docs/claims/sources.json"
RESULTS = "docs/results.json"
CAUSAL_CLAIMS = "docs/causal/claims.json"
SECTION = "## Novel findings"
META_SECTIONS = frozenset({"schema", "updated", "about", "held_out", "segments", "pending"})
TEXT_SUFFIXES = (".md", ".json", ".jsonl", ".csv", ".tsv", ".txt", ".log", ".yaml", ".yml", ".xml")
TEXT_MAX = 8 << 20          # text files above this are hashed but not read for numbers
EXTERNAL_SECTIONS = ("community",)
REASON_KINDS = ("setting", "count", "derived", "external", "context")

MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December|"
          "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec")
_DROP = [
    re.compile(r"<!--.*?-->", re.S),                                    # html comments
    re.compile(r"`[^`]*`"),                                             # code spans
    re.compile(r"!?\[([^\]]*)\]\([^)]*\)"),                             # links keep their text (handled below)
    re.compile(r"https?://\S+"),                                        # bare urls
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:?\d{2}(?::?\d{2})?Z?)?\b"),  # iso dates and stamps
    re.compile(r"\b\d{8}T\d{6}Z\b"),
    re.compile(r"\b\d{1,2}(?:\s*(?:,|and|to)\s*\d{1,2})*\s+(?:" + MONTHS + r")\b(?:\s+\d{4})?"),
    re.compile(r"\b(?:" + MONTHS + r")\s+\d{1,2}(?:,\s*\d{4})?\b"),
    re.compile(r"\b(?:19|20)\d{2}\b"),                                  # years
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),                        # times
    re.compile(r"#\d+"),                                                # issue and PR numbers
    re.compile(r"\b[Ll]ines?\s+\d+(?:\s*-\s*\d+)?(?:\s*(?:,|and)\s*\d+(?:\s*-\s*\d+)?)*"),  # line references
    re.compile(r"\b(?:[Ff]indings?|[Ii]tems?|[Pp]hase|[Aa]mendment|[Ss]tep|[Rr]ule|PR|PRs|[Ii]ssue|[Ll]ane|"
               r"[Gg]ate|[Aa]rm|[Ll]evel|[Ss]ection|[Pp]art|[Tt]able|[Ff]igure|[Vv]ersion)\s+"
               r"\d+(?:\s*(?:,|and|to)\s*\d+)*\b"),
]
RE_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
RE_NUM = re.compile(r"(?<![\w.\-/])([-−+]?)(\d+(?:,\d{3})*(?:\.\d+)?)(?=x\b|[^\w]|$)(\s*%)?")
RE_SRC_NUM = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
RE_LIST = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+")
RE_BOLD = re.compile(r"\*\*(.+?)\*\*")


class ClaimError(ValueError):
    pass


# ---------------------------------------------------------------- README side

def section_blocks(text):
    """[{key, kind, line, text}] for the list items and paragraphs under the README's "## Novel findings" heading,
    up to the next level-2 heading. Blockquotes, headings and HTML comments are left out."""
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == SECTION)
    except StopIteration:
        return []
    blocks, cur = [], None

    def close():
        if cur and cur["text"].strip():
            blocks.append(cur)

    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if ln.startswith("## "):
            break
        s = ln.strip()
        if not s or s.startswith(("#", ">", "<!--")):
            close()
            cur = None
            continue
        m = RE_LIST.match(ln)
        if m and not m.group(1):
            close()
            cur = {"kind": "item", "line": i + 1, "text": ln[m.end():]}
        elif cur is None:
            cur = {"kind": "paragraph", "line": i + 1, "text": s}
        else:
            cur["text"] += " " + s
    close()
    seen = {}
    for b in blocks:
        lead = RE_BOLD.search(b["text"])
        base = _slug(lead.group(1) if lead and b["text"].lstrip().startswith("**") else b["text"])
        n = seen.get(base, 0) + 1
        seen[base] = n
        b["key"] = base if n == 1 else f"{base}-{n}"
    return blocks


def _slug(text, words=8):
    w = re.findall(r"[a-z0-9]+", RE_LINK.sub(r"\1", text).lower().replace("`", ""))
    return "-".join(w[:words]) or "block"


def _clean(text):
    text = RE_LINK.sub(r"\1", text)
    for rx in _DROP:
        text = rx.sub(" ", text)
    return text


def numbers(text):
    """[{"token", "value", "decimals", "percent"}] for each number the text states, in order."""
    out = []
    for m in RE_NUM.finditer(_clean(text)):
        sign, body, pct = m.group(1), m.group(2), m.group(3)
        digits = body.replace(",", "")
        dec = len(digits.split(".")[1]) if "." in digits else 0
        val = float(digits)
        if sign in ("-", "−"):
            val = -val
        token = ("-" if val < 0 else "") + body + ("%" if pct else "")
        out.append({"token": token, "value": val, "decimals": dec, "percent": bool(pct)})
    return out


# ---------------------------------------------------------------- sources

def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def unit_sha256(entry):
    """sha256 of a results unit's canonical JSON without `id` and `causal` (kit causal's unit_sha256)."""
    body = {k: v for k, v in entry.items() if k not in ("id", "causal")} if isinstance(entry, dict) else entry
    return _sha(_canonical(body))


def results_units(data):
    """{ref: entry} for every unit of a results file: r:SECTION for a dict section, r:SECTION/INDEX for each object
    row of a list section, and r:ID for a unit with an explicit id."""
    out = {}
    for section, value in data.items():
        if section in META_SECTIONS:
            continue
        if isinstance(value, dict):
            out[f"r:{section}"] = value
        elif isinstance(value, list):
            for i, row in enumerate(value):
                if isinstance(row, dict):
                    out[f"r:{section}/{i}"] = row
                    if isinstance(row.get("id"), str):
                        out[f"r:{row['id']}"] = row
    return out


def _walk_numbers(obj, acc):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            acc.append(float(obj))
    elif isinstance(obj, str):
        acc.extend(_finite(RE_SRC_NUM.findall(obj)))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_numbers(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk_numbers(v, acc)


def _text_numbers(path):
    if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > TEXT_MAX:
        return []
    raw = path.read_text(encoding="utf-8", errors="replace")
    acc = []
    if path.suffix.lower() == ".json":
        try:
            _walk_numbers(json.loads(raw), acc)
            return acc
        except ValueError:
            pass
    return _finite(RE_SRC_NUM.findall(raw.replace(",", ""))) + _finite(RE_SRC_NUM.findall(raw))


def _finite(tokens):
    out = []
    for t in tokens:
        v = float(t)
        if math.isfinite(v):
            out.append(v)
    return out


class Sources:
    """Resolves source refs in one repository root, caching results.json and file reads."""

    def __init__(self, root):
        self.root = Path(root)
        self._units = None
        self._cache = {}

    @property
    def units(self):
        if self._units is None:
            p = self.root / RESULTS
            self._units = results_units(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else {}
        return self._units

    def resolve(self, ref):
        """(sha256, [numbers]) for a ref; ClaimError when it names nothing."""
        if ref in self._cache:
            return self._cache[ref]
        if ref.startswith("r:"):
            if ref not in self.units:
                raise ClaimError(f"{ref} is not a unit of {RESULTS}")
            acc = []
            _walk_numbers(self.units[ref], acc)
            got = (unit_sha256(self.units[ref]), acc)
        else:
            rel = ref.split("#", 1)[0].lstrip("./")
            if rel.startswith(("/", "~")) or ".." in Path(rel).parts or "://" in ref:
                raise ClaimError(f"{ref}: a source is a results unit or a path inside the repository")
            p = self.root / rel
            if p.is_file():
                got = (_sha(p.read_bytes()), _text_numbers(p))
            elif p.is_dir():
                h, acc = hashlib.sha256(), []
                for f in sorted(x for x in p.rglob("*") if x.is_file()):
                    h.update(f"{f.relative_to(p).as_posix()}\0{_sha(f.read_bytes())}\n".encode())
                    acc.extend(_text_numbers(f))
                got = (h.hexdigest(), acc)
            else:
                raise ClaimError(f"{ref} does not exist")
        self._cache[ref] = got
        return got


def matches(num, values):
    """True when some source value rounds to the README number at its precision (an integer: equals it)."""
    v, d = num["value"], num["decimals"]
    targets = [v, abs(v)]
    for s in values:
        cands = [s, abs(s)]
        if num["percent"]:
            cands += [s * 100, abs(s) * 100]
        for c in cands:
            if d == 0:
                if c == int(c) and any(c == t for t in targets):
                    return True
            elif any(abs(round(c, d) - t) < 10 ** (-d - 3) for t in targets):
                return True
    return False


# ---------------------------------------------------------------- ledger

def load_ledger(root, path=LEDGER):
    p = Path(root) / path
    if not p.exists():
        return {"schema": SCHEMA, "readme": README, "blocks": {}, "results_baseline": []}
    doc = json.loads(p.read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA or not isinstance(doc.get("blocks"), dict):
        raise ClaimError(f"{path} must be {{\"schema\": \"{SCHEMA}\", \"blocks\": {{...}}}}")
    doc.setdefault("results_baseline", [])
    return doc


def save_ledger(root, doc, path=LEDGER):
    p = Path(root) / path
    p.parent.mkdir(parents=True, exist_ok=True)
    doc["blocks"] = dict(sorted(doc["blocks"].items()))
    doc["results_baseline"] = sorted(set(doc.get("results_baseline", [])))
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def causal_sources(root, blocks):
    """{block key: [refs]} from docs/causal/claims.json (kit causal), matched by quote; empty when absent."""
    p = Path(root) / CAUSAL_CLAIMS
    if not p.exists():
        return {}
    try:
        claims = json.loads(p.read_text(encoding="utf-8")).get("claims", [])
    except ValueError:
        return {}
    out = {}
    for c in claims:
        quote = c.get("quote") or ""
        hit = [b["key"] for b in blocks if quote and quote in b["text"]]
        if len(hit) != 1:
            continue
        for line in c.get("causal", []):
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "source":
                out.setdefault(hit[0], []).append(parts[1].rstrip("/"))
    return out


def trace_block(src, block, refs, reasons=None):
    """[{token, sources, reason}] for each number of a block against the refs (errors per ref in 'bad')."""
    reasons = reasons or {}
    vals, bad = {}, {}
    for r in refs:
        try:
            vals[r] = src.resolve(r)[1]
        except ClaimError as exc:
            bad[r] = str(exc)
    rows = []
    for n in numbers(block["text"]):
        hit = [r for r, vs in vals.items() if matches(n, vs)]
        rows.append({"token": n["token"], "sources": hit, "reason": reasons.get(n["token"])})
    return rows, bad


def _readme_blocks(root, readme, text=None):
    if text is not None:
        return section_blocks(text)
    p = Path(root) / readme
    if not p.exists():
        raise ClaimError(f"{readme} not found under {root}")
    return section_blocks(p.read_text(encoding="utf-8"))


def check(root=".", ledger=LEDGER, readme_text=None):
    """{"exit", "findings": [{code, where, text}], "counts"} for the README's Novel findings and results units
    (readme_text, when given, stands in for the README's content)."""
    doc = load_ledger(root, ledger)
    readme = doc.get("readme", README)
    blocks = _readme_blocks(root, readme, readme_text)
    src = Sources(root)
    extra = causal_sources(root, blocks)
    findings, counts = [], {"blocks": 0, "numbers": 0, "sourced": 0, "reasoned": 0, "sources": 0}

    def add(code, where, text):
        findings.append({"code": code, "where": where, "text": text})

    keys = {b["key"] for b in blocks}
    for b in blocks:
        nums = numbers(b["text"])
        if not nums:
            continue
        counts["blocks"] += 1
        where = f"{readme}:{b['line']} [{b['key']}]"
        entry = doc["blocks"].get(b["key"])
        if entry is None:
            add("C1", where, f"states {len(nums)} numbers ({', '.join(n['token'] for n in nums[:6])}"
                             f"{', ...' if len(nums) > 6 else ''}) and has no ledger entry: no claim without a "
                             f"source (python -m kit.claimcheck add {b['key']} --source REF ...)")
            continue
        pins = entry.get("sources", {})
        for ref, pin in pins.items():
            counts["sources"] += 1
            try:
                sha = src.resolve(ref)[0]
            except ClaimError as exc:
                add("C3", where, str(exc))
                continue
            if sha != pin:
                add("C4", where, f"{ref} changed since it was pinned ({pin[:12]} -> {sha[:12]}); read the change, "
                                 f"then python -m kit.claimcheck pin --write")
        reasons = entry.get("reasons", {})
        rows, _ = trace_block(src, b, list(pins) + [r for r in extra.get(b["key"], []) if r not in pins], reasons)
        tokens = {n["token"] for n in nums}
        for row in rows:
            counts["numbers"] += 1
            if row["sources"]:
                counts["sourced"] += 1
            elif row["reason"]:
                counts["reasoned"] += 1
            else:
                add("C2", where, f"{row['token']} matches none of this block's sources and has no reason")
        for tok in reasons:
            if tok not in tokens:
                add("C5", where, f"reason for {tok}, which the block no longer states; remove it")
            elif not _reason_ok(reasons[tok]):
                add("C5", where, f"reason for {tok} must start with one of {', '.join(REASON_KINDS)}:")
    for key in doc["blocks"]:
        if key not in keys:
            add("C6", f"{ledger} [{key}]", f"no block {key} in {readme}'s Novel findings; remove or rename it")
    unsourced = results_unsourced(root)
    counts["results_units"], counts["results_unsourced"] = unsourced["units"], len(unsourced["unsourced"])
    base = set(doc.get("results_baseline", []))
    for u in unsourced["unsourced"]:
        if u["sha12"] not in base:
            add("C7", f"{RESULTS} {u['ref']}", "a results unit that cites no existing repository file and is not "
                                               "in the baseline: add its source or evidence path")
    return {"exit": 1 if findings else 0, "findings": findings, "counts": counts}


def _reason_ok(text):
    return isinstance(text, str) and text.split(":", 1)[0].strip() in REASON_KINDS and ":" in text


def results_unsourced(root):
    """{"units", "unsourced": [{ref, sha12}]}: results units none of whose string values names an existing
    repository file or folder."""
    src = Sources(root)
    try:
        units = src.units
    except ValueError as exc:
        raise ClaimError(f"{RESULTS} is not JSON: {exc}") from exc
    seen, out = set(), []
    for ref, entry in units.items():
        if id(entry) in seen:
            continue
        seen.add(id(entry))
        if not _cites_file(Path(root), entry, external=ref.split("/")[0][2:] in EXTERNAL_SECTIONS):
            out.append({"ref": ref, "sha12": unit_sha256(entry)[:12]})
    return {"units": len(seen), "unsourced": out}


RE_PATHLIKE = re.compile(r"(?:docs|scripts|kit|tests|patches|seg-meta|archive|submissions|spaces|plugins)/"
                         r"[A-Za-z0-9_.\-/]+")


def _cites_file(root, obj, external=False):
    """True when a string value names an existing repository path (or, in an external section such as community,
    an http(s) URL: a published number's source is its publication)."""
    strings = []

    def walk(o):
        if isinstance(o, str):
            strings.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    for s in strings:
        if external and re.search(r"https?://", s):
            return True
        for m in RE_PATHLIKE.findall(s):
            rel = m.rstrip(".,);:")
            if (root / rel).exists():
                return True
    return False


RE_REL_LINK = re.compile(r"\]\(((?!https?:|#|mailto:)[^)\s#]+)(?:#[^)]*)?\)")


def suggest(root, key, ledger=LEDGER, limit=8):
    """{"chosen": [{ref, covers}], "left": [tokens]}: a greedy cover of one block's numbers, linked files first."""
    doc = load_ledger(root, ledger)
    block, _ = _find_block(root, doc.get("readme", README), key)
    src = Sources(root)
    nums = numbers(block["text"])
    left = list(range(len(nums)))
    linked = []
    for rel in RE_REL_LINK.findall(block["text"]):
        try:
            src.resolve(rel)
            linked.append(rel)
        except (ClaimError, OSError):
            continue
    chosen = []
    for pool in (list(dict.fromkeys(linked)), list(src.units)):
        while left and len(chosen) < limit:
            best, cov = None, []
            for ref in pool:
                if any(c["ref"] == ref for c in chosen):
                    continue
                vals = src.resolve(ref)[1]
                got = [i for i in left if matches(nums[i], vals)]
                if len(got) > len(cov):
                    best, cov = ref, got
            if not best:
                break
            chosen.append({"ref": best, "covers": [nums[i]["token"] for i in cov]})
            left = [i for i in left if i not in cov]
    return {"key": key, "chosen": chosen, "left": [nums[i]["token"] for i in left]}


# ---------------------------------------------------------------- commands

def _find_block(root, readme, key):
    blocks = _readme_blocks(root, readme)
    for b in blocks:
        if b["key"] == key:
            return b, blocks
    raise ClaimError(f"no block {key!r} in {readme}'s Novel findings (python -m kit.claimcheck items)")


def add_entry(root, key, refs, reasons=(), ledger=LEDGER, write=False):
    """Build (and with write, store) one block's ledger entry; ClaimError when a number stays untraced."""
    doc = load_ledger(root, ledger)
    block, blocks = _find_block(root, doc.get("readme", README), key)
    src = Sources(root)
    pins = {}
    for r in refs:
        pins[r] = src.resolve(r)[0]
    why = {}
    for item in reasons:
        tok, sep, text = item.partition("=")
        if not sep or not _reason_ok(text):
            raise ClaimError(f"--reason {item!r}: write TOKEN=KIND: text, KIND one of {', '.join(REASON_KINDS)}")
        why[tok] = text
    extra = [r for r in causal_sources(root, blocks).get(key, []) if r not in pins]
    rows, bad = trace_block(src, block, list(pins) + extra, why)
    if bad:
        raise ClaimError("; ".join(bad.values()))
    tokens = {r["token"] for r in rows}
    stale = [t for t in why if t not in tokens]
    if stale:
        raise ClaimError(f"--reason for {', '.join(stale)}, which block {key} does not state")
    loose = [r["token"] for r in rows if not r["sources"] and not r["reason"]]
    if loose:
        raise ClaimError(f"block {key}: {', '.join(loose)} match none of the sources and have no --reason")
    entry = {"line": block["line"], "sources": pins}
    if why:
        entry["reasons"] = why
    if write:
        doc["blocks"][key] = entry
        save_ledger(root, doc, ledger)
    return {"key": key, "entry": entry, "rows": rows, "written": write}


def pin(root, ledger=LEDGER, write=False):
    doc = load_ledger(root, ledger)
    src, changes = Sources(root), []
    for key, entry in doc["blocks"].items():
        for ref, old in entry.get("sources", {}).items():
            new = src.resolve(ref)[0]
            if new != old:
                changes.append({"block": key, "ref": ref, "old": old, "new": new})
                entry["sources"][ref] = new
    if write and changes:
        save_ledger(root, doc, ledger)
    return {"changes": changes, "written": bool(write and changes)}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kit.claimcheck", description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".", help="repository root (default: the current folder)")
    ap.add_argument("--ledger", default=LEDGER, help=f"ledger path under the root (default {LEDGER})")
    ap.add_argument("--json", action="store_true", help="print JSON")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("items", help="the Novel findings blocks and the numbers each states")
    p = sub.add_parser("trace", help="one block's numbers against sources")
    p.add_argument("key", help="the block key (from items)")
    p.add_argument("--source", action="append", default=[], help="a results unit r:ID or a repository path; "
                                                                  "repeatable (default: the ledger's)")
    p = sub.add_parser("suggest", help="candidate sources for one block, linked files first")
    p.add_argument("key")
    p = sub.add_parser("add", help="write one block's ledger entry")
    p.add_argument("key")
    p.add_argument("--source", action="append", default=[], required=True, help="r:ID or a repository path")
    p.add_argument("--reason", action="append", default=[], help="TOKEN=KIND: text for a number no source holds")
    p.add_argument("--write", action="store_true", help="store it (default: show it)")
    p = sub.add_parser("pin", help="recompute every source's sha256")
    p.add_argument("--write", action="store_true", help="store the new pins")
    sub.add_parser("check", help="exit 1 on any claim without a source, stale pin or new unsourced results unit")
    p = sub.add_parser("results", help="results units that cite no existing file")
    p.add_argument("--write", action="store_true", help="store them as the ledger's baseline")
    a = ap.parse_args(argv)
    root = a.root
    try:
        if a.cmd == "items":
            readme = load_ledger(root, a.ledger).get("readme", README)
            out = [{"key": b["key"], "line": b["line"], "numbers": [n["token"] for n in numbers(b["text"])]}
                   for b in _readme_blocks(root, readme)]
            text = "\n".join(f"{o['line']:>4} {o['key']}: {' '.join(o['numbers']) or '(none)'}" for o in out)
        elif a.cmd == "trace":
            doc = load_ledger(root, a.ledger)
            block, _ = _find_block(root, doc.get("readme", README), a.key)
            entry = doc["blocks"].get(a.key, {})
            refs = a.source or list(entry.get("sources", {}))
            rows, bad = trace_block(Sources(root), block, refs, entry.get("reasons"))
            out = {"key": a.key, "rows": rows, "bad": bad}
            text = "\n".join([f"{r['token']:>10}  " + (", ".join(r["sources"]) or
                                                        (f"reason: {r['reason']}" if r["reason"] else "NO SOURCE"))
                              for r in rows] + [f"bad source {k}: {v}" for k, v in bad.items()])
        elif a.cmd == "suggest":
            out = suggest(root, a.key, a.ledger)
            text = "\n".join([f"{c['ref']}: {' '.join(c['covers'])}" for c in out["chosen"]] +
                             [f"left: {' '.join(out['left']) or '(none)'}"])
        elif a.cmd == "add":
            out = add_entry(root, a.key, a.source, a.reason, a.ledger, a.write)
            text = json.dumps(out["entry"], indent=1) + ("\nwritten" if a.write else "\n(not written; --write)")
        elif a.cmd == "pin":
            out = pin(root, a.ledger, a.write)
            text = "\n".join(f"{c['block']} {c['ref']} {c['old'][:12]} -> {c['new'][:12]}" for c in out["changes"]) \
                or "every pin is current"
        elif a.cmd == "results":
            out = results_unsourced(root)
            if a.write:
                doc = load_ledger(root, a.ledger)
                doc["results_baseline"] = [u["sha12"] for u in out["unsourced"]]
                save_ledger(root, doc, a.ledger)
            text = "\n".join(f"{u['ref']} {u['sha12']}" for u in out["unsourced"]) + \
                f"\n{len(out['unsourced'])} of {out['units']} units cite no existing file"
        else:
            out = check(root, a.ledger)
            c = out["counts"]
            text = "\n".join(f"{f['code']} {f['where']}: {f['text']}" for f in out["findings"]) + \
                (f"\n{c['numbers']} numbers in {c['blocks']} blocks: {c['sourced']} sourced, {c['reasoned']} with a "
                 f"reason; {c['results_unsourced']} of {c['results_units']} results units cite no file "
                 f"(baseline {len(load_ledger(root, a.ledger).get('results_baseline', []))}); "
                 f"{'FAIL' if out['exit'] else 'ok'}")
    except (ClaimError, OSError, ValueError) as exc:
        print(f"claimcheck: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1) if a.json else text.strip())
    return out.get("exit", 0) if isinstance(out, dict) else 0


if __name__ == "__main__":
    sys.exit(main())
