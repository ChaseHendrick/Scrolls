"""Voxel exact: the data contract between the private voxel-exact scorers and the Snapped Labels Space's "Voxel exact" tab.

Chase asked on 28 October 2026 for the voxel-exact results on every scroll as a Hugging Face Space view. The Space
reads one file, vx/summary.json (schema snapped-labels/voxel-exact@1), and, for showcase segments only, one JSON per
segment under vx/show/ with its grids as plain number lists (no binary files in public Git). A private exporter writes
them from the score files with allowlisted keys only; this module checks them before they are committed to public Git, and writes a synthetic fixture that the page
can show (always under a "Synthetic fixture" banner) while no real results exist.

  python -m kit vxsummary check PATH [--deploy] [--online]   validate a summary (and the showcase files beside it);
                                                    --deploy also refuses the fixture and placeholder digests, --online
                                                    also asks Hugging Face that the dataset revision exists
  python -m kit vxsummary fixture OUT_DIR           write the synthetic fixture: OUT_DIR/summary.json and OUT_DIR/show/

Exit codes: 0 valid, 1 problems found (one per line on stderr), 2 the file could not be read.

What a summary may hold (every key is allowlisted; an unknown key is a problem, so nothing private rides along):
per scroll a claim level, "measured" (scored against a finer, independent scan, with at least one stratum that
passed), "certified" (a truth-free lower bound with its assumptions) or "not_shown" (with the reason; when a test ran
and nothing passed, its strata still carry the numbers, which then make no claim); the vertex counts by abstain.tif code; per stratum
(C0, C2, C1, C0L) the verdict, the share within 0.5, 1 and 2 label voxels with its interval, the signed residual
histogram, the published label's histogram, and the negative controls. A check refuses costs, long dashes, the word
"letter", a prize-eligible scroll (from the newest kit/data/prizes-*.json), unsafe showcase paths, counts that do not
add up, an interval that does not hold its share, and a control whose "holds" disagrees with its numbers.

A two-scan test (since 28 October 2026) adds, per stratum, "coverage": the share of drawn sites where two independent
scans both name the face and agree, with its interval, bar and verdict; its share within each tolerance then has the
basis "covered" (n is the covered count). Such a scroll states in "scope" what exact means there, names the second scan
("second_truth"), and may carry the same stratum scored against one scan alone ("single_truth"). "earlier" lists spent
tests of the same scroll that a later test replaced on the card, each with its digest and a one-line summary.

Every number in a summary is model output: the snapped meshes are geometry from a band finder, and the truth face is
itself found by a rule on the finer scan. Standard library only.
"""

import argparse
import json
import math
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCHEMA = "snapped-labels/voxel-exact@1"
SHOW_SCHEMA = "snapped-labels/voxel-exact-show@1"
CLAIMS = ("measured", "certified", "not_shown")
VERDICTS = ("PASS", "FAIL", "NOT SHOWN", "UNANSWERABLE", "VOID")
STRATA = {"C0": 0, "C2": 2, "C1": 1, "C0L": 0}
TOLERANCES = ("0.5", "1", "2")
BASES = ("itt", "scorable", "covered")
COVERAGE_VERDICTS = ("COVERED", "NOT COVERED", "UNANSWERABLE")
CONTROL_REQUIRE = ("below", "above")
ROOT = Path(__file__).resolve().parent.parent
PRIZE_DATA = ROOT / "kit" / "data"
FIXTURE_DIGEST = "0" * 64
HF_API = "https://huggingface.co/api/datasets"

TOP_KEYS = {"schema", "fixture", "generated", "dataset", "rule", "prereg", "prizes_read", "scrolls", "showcase"}
DATASET_KEYS = {"repo", "release", "revision"}
RULE_KEYS = {"primary_tolerance", "tolerances", "bar", "interval", "max_move"}
INTERVAL_KEYS = {"method", "sided", "level"}
PREREG_KEYS = {"sha256", "frozen"}
PRIZES_KEYS = {"url", "date"}
SCROLL_KEYS = {"scroll", "claim", "why_not_shown", "label_scan", "truth", "oracle", "certificate", "vertices", "void",
               "strata", "scope", "second_truth", "earlier"}
SCAN_KEYS = {"volume_id", "voxel_um"}
TRUTH_KEYS = {"kind", "volume_id", "voxel_um"}
CERT_KEYS = {"method", "lower", "level", "n", "assumptions"}
VERTEX_KEYS = {"released", "held_back", "by_code"}
STRATUM_KEYS = {"id", "code", "primary", "verdict", "instrument_limited", "why", "n_selected", "n_scorable", "within",
                "median_abs", "residual_hist", "published_hist", "controls", "coverage", "single_truth"}
COVERAGE_KEYS = {"k", "n", "share", "lower", "upper", "bar", "verdict", "what"}
SINGLE_KEYS = {"verdict", "instrument_limited", "why", "within_1", "controls"}
EARLIER_KEYS = {"prereg", "scope", "summary"}
SLOT_KEYS = {"basis", "k", "n", "share", "lower", "upper"}
HIST_KEYS = {"edges", "counts", "under", "over", "sign"}
CONTROL_KEYS = {"name", "observed", "require", "limit", "holds"}
SHOWCASE_KEYS = {"scroll", "segment", "file", "spent"}
SHOW_KEYS = {"schema", "scroll", "segment", "stride", "shape", "voxel_um", "volume", "truth_note", "planes", "residual",
             "state", "xyz", "rows"}
# numbers per grid cell (rows: per line piece: published, snapped, truth, each ax ay bx by)
SHOW_GRIDS = {"residual": 1, "state": 1, "xyz": 3, "rows": 12}

HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
SAFE_PATH = re.compile(r"show/[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")
# Words a public summary never carries: costs (no costs on public pages), long dashes (house style) and "letter" (an
# ink map is model output, not a reading; these meshes say nothing about text).
BANNED = (("USD", "a cost"), ("$", "a cost"), (chr(0x2014), "a long dash"), (chr(0x2013), "a long dash"))
BANNED_WORD = re.compile(r"\bletters?\b", re.IGNORECASE)


# ---------------------------------------------------------------- helpers

def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _share(v):
    return _num(v) and 0.0 <= v <= 1.0


def _keys(obj, allowed, where, out):
    if not isinstance(obj, dict):
        out.append(f"{where}: not an object")
        return False
    extra = sorted(set(obj) - allowed)
    if extra:
        out.append(f"{where}: keys not in the contract: {', '.join(extra)}")
    return True


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _normalize_scroll(name):
    text = re.sub(r"[\s._-]", "", str(name)).upper()
    m = re.fullmatch(r"PHERC(PARIS)?0*(\d+)([A-Z]*)", text)
    if not m:
        return text
    if m.group(1):
        return f"PHERCPARIS{int(m.group(2))}{m.group(3)}"
    return f"PHERC{int(m.group(2)):04d}{m.group(3)}"


def _eligible():
    """Normalized scroll and volume ids on the newest prize snapshot's eligible lists, or None without a snapshot."""
    snaps = sorted(PRIZE_DATA.glob("prizes-*.json"))
    if not snaps:
        return None
    names = set()
    for prize in json.loads(snaps[-1].read_text(encoding="utf-8")).get("prizes", []):
        for entry in prize.get("eligible") or []:
            for key in (entry.get("scroll"), entry.get("volume")):
                if key and key != "any":
                    names.add(_normalize_scroll(key))
    return names


def _is_eligible(name, table):
    key = _normalize_scroll(name)
    return key in table or any(re.fullmatch(re.escape(key) + r"[A-Z]+", t) for t in table)


# ---------------------------------------------------------------- parts

def _slot(slot, where, out):
    if slot is None:
        return None
    if not _keys(slot, SLOT_KEYS, where, out):
        return None
    if slot.get("basis") not in BASES:
        out.append(f"{where}.basis: one of {', '.join(BASES)}")
    k, n = slot.get("k"), slot.get("n")
    if not (_int(k) and _int(n) and 0 <= k <= n):
        out.append(f"{where}: k and n are counts with 0 <= k <= n")
        return None
    share = slot.get("share")
    if not _share(share):
        out.append(f"{where}.share: a fraction from 0 to 1")
    elif n and abs(share - k / n) > 1e-6:
        out.append(f"{where}.share is {share}, but k/n is {k / n:.6f}")
    elif not n and share != 0:
        out.append(f"{where}.share: 0 when n is 0")
    lo, hi = slot.get("lower"), slot.get("upper")
    for name, v in (("lower", lo), ("upper", hi)):
        if v is not None and not _share(v):
            out.append(f"{where}.{name}: a fraction from 0 to 1, or null")
    if _share(share) and n:
        if _share(lo) and lo > share + 1e-9:
            out.append(f"{where}: the lower bound {lo} is above the share {share}")
        if _share(hi) and hi < share - 1e-9:
            out.append(f"{where}: the upper bound {hi} is below the share {share}")
    return slot


def _hist(h, where, out, need_sign):
    if h is None:
        return
    if not _keys(h, HIST_KEYS, where, out):
        return
    edges, counts = h.get("edges"), h.get("counts")
    if not (isinstance(edges, list) and len(edges) >= 2 and all(_num(e) for e in edges)):
        out.append(f"{where}.edges: at least two numbers")
        return
    if any(b <= a for a, b in zip(edges, edges[1:])):
        out.append(f"{where}.edges: strictly increasing")
    if not (isinstance(counts, list) and len(counts) == len(edges) - 1 and all(_int(c) and c >= 0 for c in counts)):
        out.append(f"{where}.counts: one count per bin ({len(edges) - 1})")
    for key in ("under", "over"):
        if not (_int(h.get(key)) and h[key] >= 0):
            out.append(f"{where}.{key}: a count")
    if need_sign and not (isinstance(h.get("sign"), str) and h["sign"].strip()):
        out.append(f"{where}.sign: what a positive residual means, in words")


def _control(c, where, out):
    if not _keys(c, CONTROL_KEYS, where, out):
        return
    if not (isinstance(c.get("name"), str) and c["name"].strip()):
        out.append(f"{where}.name: a name")
    obs, lim, req, holds = c.get("observed"), c.get("limit"), c.get("require"), c.get("holds")
    if req not in CONTROL_REQUIRE:
        out.append(f"{where}.require: one of {', '.join(CONTROL_REQUIRE)}")
    if not _num(lim):
        out.append(f"{where}.limit: a number")
    if obs is not None and not _num(obs):
        out.append(f"{where}.observed: a number, or null when not measured")
    if not isinstance(holds, bool) and holds is not None:
        out.append(f"{where}.holds: true, false, or null when not measured")
    if _num(obs) and _num(lim) and req in CONTROL_REQUIRE and isinstance(holds, bool):
        should = obs < lim if req == "below" else obs > lim
        if should != holds:
            out.append(f"{where}: observed {obs} {req} {lim} is {should}, but holds says {holds}")
    if obs is None and holds is not None:
        out.append(f"{where}: holds is null when nothing was observed")


def _coverage(c, where, n_selected, out):
    """A two-scan test's coverage: k of the n drawn sites where both scans name the face and agree."""
    if not _keys(c, COVERAGE_KEYS, where, out):
        return None
    k, n = c.get("k"), c.get("n")
    if not (_int(k) and _int(n) and 0 <= k <= n):
        out.append(f"{where}: k and n are counts with 0 <= k <= n")
        return None
    if n_selected is not None and n != n_selected:
        out.append(f"{where}.n is {n}, but the stratum drew {n_selected} sites")
    share, lo, hi, bar = c.get("share"), c.get("lower"), c.get("upper"), c.get("bar")
    if not _share(share) or (n and abs(share - k / n) > 1e-6):
        out.append(f"{where}.share: k/n")
    for name, v in (("lower", lo), ("upper", hi)):
        if not _share(v):
            out.append(f"{where}.{name}: a fraction from 0 to 1")
    if _share(share) and _share(lo) and lo > share + 1e-9:
        out.append(f"{where}: the lower bound {lo} is above the share {share}")
    if _share(share) and _share(hi) and hi < share - 1e-9:
        out.append(f"{where}: the upper bound {hi} is below the share {share}")
    if not (_share(bar) and bar > 0):
        out.append(f"{where}.bar: the preregistered coverage bar, such as 0.40")
    verdict = c.get("verdict")
    if verdict not in COVERAGE_VERDICTS:
        out.append(f"{where}.verdict: one of {', '.join(COVERAGE_VERDICTS)}")
    elif verdict == "COVERED" and _share(lo) and _share(bar) and lo < bar:
        out.append(f"{where}: COVERED needs the lower bound {lo} at or above the bar {bar}")
    elif verdict == "NOT COVERED" and _share(lo) and _share(bar) and lo >= bar:
        out.append(f"{where}: NOT COVERED, but the lower bound {lo} clears the bar {bar}")
    if not (isinstance(c.get("what"), str) and c["what"].strip()):
        out.append(f"{where}.what: what covered means, in words")
    return c


def _single(s, where, n_selected, n_scorable, out):
    """The same stratum scored against one scan alone, beside a two-scan claim."""
    if not _keys(s, SINGLE_KEYS, where, out):
        return
    if s.get("verdict") not in VERDICTS:
        out.append(f"{where}.verdict: one of {', '.join(VERDICTS)}")
    if not isinstance(s.get("instrument_limited"), bool):
        out.append(f"{where}.instrument_limited: true or false")
    if not (isinstance(s.get("why"), str) and s["why"].strip()):
        out.append(f"{where}.why: the verdict's reason in words")
    slot = s.get("within_1")
    if slot is None:
        out.append(f"{where}.within_1: the share within 1 voxel against the one scan")
    else:
        slot = _slot(slot, f"{where}.within_1", out)
        if slot:
            want = {"itt": n_selected, "scorable": n_scorable}.get(slot.get("basis"))
            if slot.get("basis") == "covered":
                out.append(f"{where}.within_1.basis: itt or scorable (one scan has no coverage)")
            elif want is not None and slot.get("n") != want:
                out.append(f"{where}.within_1: n is {slot.get('n')}, but its basis {slot.get('basis')} has {want} sites")
    controls = s.get("controls")
    if not isinstance(controls, list):
        out.append(f"{where}.controls: a list")
    else:
        for i, c in enumerate(controls):
            _control(c, f"{where}.controls[{i}]", out)


def _stratum(s, where, claim, out, bar=None):
    if not _keys(s, STRATUM_KEYS, where, out):
        return
    sid = s.get("id")
    if sid not in STRATA:
        out.append(f"{where}.id: one of {', '.join(STRATA)}")
    elif s.get("code") != STRATA[sid]:
        out.append(f"{where}.code: {sid} is abstain.tif code {STRATA[sid]}")
    if s.get("verdict") not in VERDICTS:
        out.append(f"{where}.verdict: one of {', '.join(VERDICTS)}")
    for key in ("primary", "instrument_limited"):
        if not isinstance(s.get(key), bool):
            out.append(f"{where}.{key}: true or false")
    if not (isinstance(s.get("why"), str) and s["why"].strip()):
        out.append(f"{where}.why: the verdict's reason in words")
    sel, sco = s.get("n_selected"), s.get("n_scorable")
    if not (_int(sel) and _int(sco) and 0 <= sco <= sel):
        out.append(f"{where}: n_selected and n_scorable are counts with n_scorable <= n_selected")
        sel = sco = None
    cov = None
    if s.get("coverage") is not None:
        cov = _coverage(s.get("coverage"), f"{where}.coverage", sel, out)
        if cov and cov.get("verdict") != "COVERED" and s.get("verdict") == "PASS":
            out.append(f"{where}: a PASS needs the coverage verdict COVERED")
    if s.get("single_truth") is not None:
        _single(s.get("single_truth"), f"{where}.single_truth", sel, sco, out)
    within = s.get("within")
    if not isinstance(within, dict) or set(within) != set(TOLERANCES):
        out.append(f"{where}.within: exactly the slots {', '.join(TOLERANCES)} (null for one not measured)")
        within = {}
    for tol in TOLERANCES:
        slot = _slot(within.get(tol), f"{where}.within.{tol}", out)
        if slot and slot.get("basis") == "covered":
            if not cov:
                out.append(f"{where}.within.{tol}: basis covered needs the stratum's coverage")
            elif slot.get("n") != cov.get("k"):
                out.append(f"{where}.within.{tol}: n is {slot.get('n')}, but {cov.get('k')} sites are covered")
        elif slot and sel is not None:
            want = sel if slot.get("basis") == "itt" else sco
            if slot.get("n") != want:
                out.append(f"{where}.within.{tol}: n is {slot.get('n')}, but its basis {slot.get('basis')} "
                           f"has {want} sites")
    if claim == "measured" and s.get("primary") and within.get("1") is None:
        out.append(f"{where}: a measured scroll's primary stratum reports the share within 1 voxel")
    one = within.get("1")
    if s.get("verdict") == "PASS" and _share(bar):
        lo = one.get("lower") if isinstance(one, dict) else None
        if not _share(lo) or lo < bar - 1e-9:
            out.append(f"{where}: a PASS needs a lower bound within 1 voxel at or above the bar {bar}")
    med = s.get("median_abs")
    if med is not None and not (_num(med) and med >= 0):
        out.append(f"{where}.median_abs: a nonnegative number, or null")
    _hist(s.get("residual_hist"), f"{where}.residual_hist", out, True)
    _hist(s.get("published_hist"), f"{where}.published_hist", out, False)
    controls = s.get("controls")
    if not isinstance(controls, list):
        out.append(f"{where}.controls: a list")
    else:
        for i, c in enumerate(controls):
            _control(c, f"{where}.controls[{i}]", out)


def _scroll(sc, i, eligible, out, bar=None):
    where = f"scrolls[{i}]"
    if not _keys(sc, SCROLL_KEYS, where, out):
        return None
    name = sc.get("scroll")
    if not (isinstance(name, str) and name.strip()):
        out.append(f"{where}.scroll: a scroll id")
        name = "?"
    where = f"scrolls[{i}] ({name})"
    if eligible is not None and _is_eligible(name, eligible):
        out.append(f"{where}: prize-eligible; results on a target scroll stay in Scrolls-private")
    claim = sc.get("claim")
    if claim not in CLAIMS:
        out.append(f"{where}.claim: one of {', '.join(CLAIMS)}")
    why = sc.get("why_not_shown")
    if claim == "not_shown" and not (isinstance(why, str) and why.strip()):
        out.append(f"{where}: a scroll not shown says why (why_not_shown)")
    if claim in ("measured", "certified") and why is not None:
        out.append(f"{where}.why_not_shown: null for a {claim} scroll")
    scan = sc.get("label_scan")
    if _keys(scan, SCAN_KEYS, f"{where}.label_scan", out):
        if not (_num(scan.get("voxel_um")) and scan["voxel_um"] > 0):
            out.append(f"{where}.label_scan.voxel_um: the label scan's voxel size in um")
    for key in ("truth", "oracle"):
        t = sc.get(key)
        if t is None:
            continue
        if _keys(t, TRUTH_KEYS, f"{where}.{key}", out) and not (_num(t.get("voxel_um")) and t["voxel_um"] > 0):
            out.append(f"{where}.{key}.voxel_um: a voxel size in um")
    if claim == "measured" and sc.get("truth") is None:
        out.append(f"{where}: a measured scroll names its truth scan")
    if claim == "certified":
        if sc.get("truth") is not None:
            out.append(f"{where}: a certified scroll has no truth scan (that would make it measured)")
        cert = sc.get("certificate")
        if _keys(cert, CERT_KEYS, f"{where}.certificate", out):
            if not _share(cert.get("lower")):
                out.append(f"{where}.certificate.lower: a fraction from 0 to 1")
            if not (_share(cert.get("level")) and cert["level"] > 0):
                out.append(f"{where}.certificate.level: the confidence level, such as 0.95")
            if not (_int(cert.get("n")) and cert["n"] > 0):
                out.append(f"{where}.certificate.n: the vertices it covers")
            a = cert.get("assumptions")
            if not (isinstance(a, list) and a and all(isinstance(x, str) and x.strip() for x in a)):
                out.append(f"{where}.certificate.assumptions: the stated assumptions, one string each")
    elif sc.get("certificate") is not None:
        out.append(f"{where}.certificate: only a certified scroll carries one")
    v = sc.get("vertices")
    if _keys(v, VERTEX_KEYS, f"{where}.vertices", out):
        by = v.get("by_code")
        if not (_int(v.get("released")) and _int(v.get("held_back")) and isinstance(by, dict)
                and set(by) == {"0", "1", "2"} and all(_int(x) and x >= 0 for x in by.values())):
            out.append(f"{where}.vertices: released, held_back and by_code {{0, 1, 2}} as counts")
        elif sum(by.values()) != v["released"]:
            out.append(f"{where}.vertices: by_code adds to {sum(by.values())}, not released {v['released']}")
    void = sc.get("void")
    if not (isinstance(void, list) and all(isinstance(x, str) and x.strip() for x in void)):
        out.append(f"{where}.void: a list of reasons (empty when the test is not void)")
        void = []
    strata = sc.get("strata")
    if not isinstance(strata, list):
        out.append(f"{where}.strata: a list")
        strata = []
    if claim == "measured":
        if not any(isinstance(s, dict) and s.get("primary") for s in strata):
            out.append(f"{where}: a measured scroll has at least one primary stratum")
        if not any(isinstance(s, dict) and s.get("verdict") == "PASS" for s in strata):
            out.append(f"{where}: a measured scroll has a stratum that passed; with none it is not shown")
    if claim == "not_shown" and any(isinstance(s, dict) and s.get("verdict") == "PASS" for s in strata):
        out.append(f"{where}: a scroll not shown has no stratum that passed (a PASS makes it measured)")
    if claim == "certified" and strata:
        out.append(f"{where}: a certified scroll carries its certificate, not strata")
    ids = [s.get("id") for s in strata if isinstance(s, dict)]
    if len(ids) != len(set(ids)):
        out.append(f"{where}.strata: a stratum appears twice")
    two_scan = any(isinstance(s, dict) and s.get("coverage") is not None for s in strata)
    scope = sc.get("scope")
    if scope is not None and not (isinstance(scope, str) and scope.strip()):
        out.append(f"{where}.scope: what exact means for this scroll, in words, or null")
    if two_scan:
        if not (isinstance(scope, str) and scope.strip()):
            out.append(f"{where}: a two-scan test states in scope what exact means here")
        t2 = sc.get("second_truth")
        if not (_keys(t2, TRUTH_KEYS, f"{where}.second_truth", out) and _num(t2.get("voxel_um")) and t2["voxel_um"] > 0):
            out.append(f"{where}.second_truth: the second scan of a two-scan test, with its voxel size in um")
    elif sc.get("second_truth") is not None:
        out.append(f"{where}.second_truth: only a two-scan test names a second scan")
    earlier = sc.get("earlier", [])
    if not isinstance(earlier, list):
        out.append(f"{where}.earlier: a list (empty when no earlier test)")
        earlier = []
    for k, e in enumerate(earlier):
        w = f"{where}.earlier[{k}]"
        if not _keys(e, EARLIER_KEYS, w, out):
            continue
        pre = e.get("prereg")
        if not (_keys(pre, PREREG_KEYS, f"{w}.prereg", out) and isinstance(pre.get("sha256"), str)
                and HEX64.fullmatch(pre["sha256"]) and isinstance(pre.get("frozen"), str) and STAMP.fullmatch(pre["frozen"])):
            out.append(f"{w}.prereg: the earlier test's 64 hex digest and UTC freeze time")
        for key in ("scope", "summary"):
            if not (isinstance(e.get(key), str) and e[key].strip()):
                out.append(f"{w}.{key}: words")
    for j, s in enumerate(strata):
        _stratum(s, f"{where}.strata[{j}]", claim, out, bar)
        if void and isinstance(s, dict) and s.get("verdict") != "VOID":
            out.append(f"{where}.strata[{j}]: the test is void, so every stratum's verdict is VOID")
    return name


def _show(path, entry, out, base):
    """Check one showcase JSON: its plane index and the length and values of its grids."""
    where = f"showcase {entry.get('segment')}"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out.append(f"{where}: {path.name} cannot be read ({exc})")
        return
    if not _keys(doc, SHOW_KEYS, where, out):
        return
    if doc.get("schema") != SHOW_SCHEMA:
        out.append(f"{where}.schema: {SHOW_SCHEMA}")
    for key in ("scroll", "segment"):
        if doc.get(key) != entry.get(key):
            out.append(f"{where}.{key}: {doc.get(key)!r} differs from the summary's {entry.get(key)!r}")
    shape = doc.get("shape")
    if not (isinstance(shape, list) and len(shape) == 2 and all(_int(x) and x > 0 for x in shape)):
        out.append(f"{where}.shape: [rows, columns]")
        return
    if not (_int(doc.get("stride")) and doc["stride"] > 0):
        out.append(f"{where}.stride: the grid step of the heatmap, in mesh cells")
    if not (isinstance(doc.get("truth_note"), str) and doc["truth_note"].strip()):
        out.append(f"{where}.truth_note: how the truth face was found, in words")
    vol = doc.get("volume")
    if vol is not None and not (isinstance(vol, str) and vol.startswith("https://")):
        out.append(f"{where}.volume: an https OME-Zarr URL, or null")
    planes = doc.get("planes")
    total = 0
    if not isinstance(planes, list):
        out.append(f"{where}.planes: a list of {{z, first, count}}")
        planes = []
    for p in planes:
        if not (isinstance(p, dict) and set(p) == {"z", "first", "count"} and all(_int(p[k]) for k in p)
                and p["first"] == total and p["count"] >= 0):
            out.append(f"{where}.planes: {{z, first, count}} with each first following the last")
            break
        total += p["count"]
    cells = shape[0] * shape[1]
    for key, per in SHOW_GRIDS.items():
        v = doc.get(key)
        want = per * (total if key == "rows" else cells)
        if not isinstance(v, list) or len(v) != want:
            out.append(f"{where}.{key}: a list of {want} numbers ({per} per {'line piece' if key == 'rows' else 'cell'})")
            return
        ok = (lambda x: x is None or _num(x)) if key == "residual" else _num
        if not all(ok(x) for x in v):
            out.append(f"{where}.{key}: numbers only{' (null where there is no value)' if key == 'residual' else ''}")
            return
    state, res = doc["state"], doc["residual"]
    bad = sorted({x for x in state if x not in (0, 1, 2)})
    if bad:
        out.append(f"{where}: state holds codes {bad}; 0 measured, 1 no value, 2 held back")
    held = sum(1 for c, r in zip(state, res) if c == 2 and r is not None)
    if held:
        out.append(f"{where}: {held} held-back cells carry a residual; a held-back cell is null")
    gone = sum(1 for c, r in zip(state, res) if c == 0 and r is None)
    if gone:
        out.append(f"{where}: {gone} measured cells have no residual")


# ---------------------------------------------------------------- public

def load(path):
    """The summary at path, parsed (raises OSError or ValueError)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check(doc, deploy=False, base=None):
    """Problems with one summary, as a list of strings ([] when it is valid). base is the folder that holds it, for the
    showcase files; deploy also refuses the fixture and placeholder digests."""
    out = []
    if not _keys(doc, TOP_KEYS, "summary", out):
        return out
    if doc.get("schema") != SCHEMA:
        out.append(f"schema: {SCHEMA}")
    if not isinstance(doc.get("fixture"), bool):
        out.append("fixture: true for the synthetic fixture, false for real results")
    if not (isinstance(doc.get("generated"), str) and STAMP.fullmatch(doc["generated"])):
        out.append("generated: a UTC time such as 2026-10-28T00:00:00Z")
    ds = doc.get("dataset")
    if _keys(ds, DATASET_KEYS, "dataset", out):
        if not (isinstance(ds.get("repo"), str) and "/" in ds["repo"]):
            out.append("dataset.repo: OWNER/NAME on Hugging Face")
        if not (isinstance(ds.get("release"), str) and ds["release"].strip()):
            out.append("dataset.release: the release the vertices come from, such as 1.0.1")
        if not (isinstance(ds.get("revision"), str) and HEX40.fullmatch(ds["revision"])):
            out.append("dataset.revision: the 40 hex commit the scorer pinned")
    rule = doc.get("rule")
    if _keys(rule, RULE_KEYS, "rule", out):
        tols = rule.get("tolerances")
        if not (isinstance(tols, list) and [float(t) for t in tols if _num(t)] == [0.5, 1.0, 2.0]):
            out.append("rule.tolerances: [0.5, 1.0, 2.0]")
        if rule.get("primary_tolerance") != 1.0:
            out.append("rule.primary_tolerance: 1.0 (the claim is within one label voxel)")
        if not (_share(rule.get("bar")) and rule["bar"] > 0):
            out.append("rule.bar: the preregistered bar, such as 0.90")
        if not (_num(rule.get("max_move")) and rule["max_move"] > 0):
            out.append("rule.max_move: the largest move the snap allows, in voxels")
        _keys(rule.get("interval"), INTERVAL_KEYS, "rule.interval", out)
    pre = doc.get("prereg")
    if _keys(pre, PREREG_KEYS, "prereg", out):
        if not (isinstance(pre.get("sha256"), str) and HEX64.fullmatch(pre["sha256"])):
            out.append("prereg.sha256: the frozen preregistration's 64 hex digest")
        if not (isinstance(pre.get("frozen"), str) and STAMP.fullmatch(pre["frozen"])):
            out.append("prereg.frozen: the UTC time it was frozen")
    pr = doc.get("prizes_read")
    if _keys(pr, PRIZES_KEYS, "prizes_read", out):
        if pr.get("url") != "https://scrollprize.org/prizes":
            out.append("prizes_read.url: https://scrollprize.org/prizes")
        if not (isinstance(pr.get("date"), str) and DATE.fullmatch(pr["date"])):
            out.append("prizes_read.date: the date the prize page was read")
    eligible = _eligible()
    if eligible is None:
        out.append("no prize snapshot in kit/data: the eligible list is needed, so nothing passes without it")
    scrolls = doc.get("scrolls")
    names = []
    if not (isinstance(scrolls, list) and scrolls):
        out.append("scrolls: at least one scroll")
        scrolls = []
    for i, sc in enumerate(scrolls):
        names.append(_scroll(sc, i, eligible, out, rule.get("bar") if isinstance(rule, dict) else None))
    if len([n for n in names if n]) != len({n for n in names if n}):
        out.append("scrolls: a scroll appears twice")
    show = doc.get("showcase", [])
    if not isinstance(show, list):
        out.append("showcase: a list (empty when no residual view is public)")
        show = []
    for i, entry in enumerate(show):
        where = f"showcase[{i}]"
        if not _keys(entry, SHOWCASE_KEYS, where, out):
            continue
        if entry.get("scroll") not in names:
            out.append(f"{where}: scroll {entry.get('scroll')!r} is not in scrolls")
        if entry.get("spent") is not True:
            out.append(f"{where}.spent: true, saying the region's truth positions are public and spent for later tests")
        rel = entry.get("file")
        if not (isinstance(rel, str) and SAFE_PATH.fullmatch(rel) and ".." not in rel and rel.endswith(".json")):
            out.append(f"{where}.file: a .json path under show/")
        elif base is not None:
            _show(Path(base) / rel, entry, out, Path(base))
    for text in _strings(doc):
        for token, what in BANNED:
            if token in text:
                out.append(f"{what} in the summary ({text[:60]!r}); public pages carry none")
        if BANNED_WORD.search(text):
            out.append(f"the word 'letter' in the summary ({text[:60]!r}); these meshes say nothing about text")
    if deploy:
        if doc.get("fixture") is not False:
            out.append("--deploy: the synthetic fixture never deploys (fixture is true)")
        if isinstance(pre, dict) and pre.get("sha256") == FIXTURE_DIGEST:
            out.append("--deploy: prereg.sha256 is the fixture's placeholder")
        if any(isinstance(sc, dict) and str(sc.get("scroll", "")).upper().startswith("SYNTH") for sc in scrolls):
            out.append("--deploy: a synthetic scroll id (SYNTH-...)")
    return sorted(set(out), key=out.index)


def online_problems(doc, timeout=30):
    """Problems found over the network: the pinned dataset revision must exist on Hugging Face."""
    ds = doc.get("dataset") if isinstance(doc, dict) else None
    if not isinstance(ds, dict):
        return ["dataset: missing"]
    url = f"{HF_API}/{ds.get('repo')}/revision/{ds.get('revision')}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "kit-vxsummary"}),
                                    timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return [f"dataset revision {ds.get('revision')} on {ds.get('repo')} could not be confirmed ({exc})"]
    if body.get("sha") != ds.get("revision"):
        return [f"dataset revision: Hugging Face answered {body.get('sha')}, not {ds.get('revision')}"]
    return []


def _fixture_hist(center, spread, n, seed):
    edges = [round(-4 + 0.25 * i, 2) for i in range(33)]
    counts = [0] * 32
    under = over = 0
    x = seed
    for _ in range(n):
        x = (1103515245 * x + 12345) % (1 << 31)
        u1 = (x + 1) / (1 << 31)
        x = (1103515245 * x + 12345) % (1 << 31)
        u2 = x / (1 << 31)
        v = center + spread * math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
        if v < edges[0]:
            under += 1
        elif v >= edges[-1]:
            over += 1
        else:
            counts[int((v - edges[0]) / 0.25)] += 1
    return {"edges": edges, "counts": counts, "under": under, "over": over}


def _fixture_slot(basis, k, n, lower=None, upper=None):
    return {"basis": basis, "k": k, "n": n, "share": round(k / n, 6) if n else 0.0, "lower": lower, "upper": upper}


def fixture(out_dir):
    """Write the synthetic fixture to out_dir: summary.json and one showcase segment under show/. Every number is made
    up (deterministic), every scroll id starts with SYNTH, and fixture is true, so the page shows its banner and
    check(..., deploy=True) refuses it. Returns the summary."""
    out_dir = Path(out_dir)
    sign = "positive: the snapped point lies outward of the truth face, away from the center line"
    controls = lambda pub: [   # noqa: E731
        {"name": "published label", "observed": pub, "require": "below", "limit": 0.60, "holds": pub < 0.60},
        {"name": "planted +1.5 voxels", "observed": 0.12, "require": "below", "limit": 0.50, "holds": True},
        {"name": "planted -1.5 voxels", "observed": 0.15, "require": "below", "limit": 0.50, "holds": True},
        {"name": "planted +3 voxels", "observed": 0.02, "require": "below", "limit": 0.20, "holds": True},
        {"name": "verso face", "observed": 0.05, "require": "below", "limit": 0.30, "holds": True},
        {"name": "oracle face (2.4 um scan)", "observed": 0.97, "require": "above", "limit": 0.80, "holds": True},
    ]

    def stratum(sid, primary, verdict, why, sel, sco, k05, k1, k2, lo1, center, spread, seed, pub):
        h = _fixture_hist(center, spread, sco, seed)
        h["sign"] = sign
        return {"id": sid, "code": STRATA[sid], "primary": primary, "verdict": verdict, "instrument_limited": False,
                "why": why, "n_selected": sel, "n_scorable": sco,
                "within": {"0.5": _fixture_slot("scorable", k05, sco),
                           "1": _fixture_slot("itt", k1, sel, lo1, round(min(1.0, k1 / sel + 0.06), 4)),
                           "2": _fixture_slot("scorable", k2, sco)},
                "median_abs": round(abs(center) + 0.6745 * spread, 3), "residual_hist": h,
                "published_hist": _fixture_hist(1.9, 1.4, sco, seed + 7),
                "controls": controls(pub)}

    doc = {
        "schema": SCHEMA, "fixture": True, "generated": "2026-10-28T00:00:00Z",
        "dataset": {"repo": "SharpMeow/vesuvius-snapped-labels", "release": "1.0.1",
                    "revision": "95432ec570d6f096d754e6ac16cafdeb83ca8a04"},
        "rule": {"primary_tolerance": 1.0, "tolerances": [0.5, 1.0, 2.0], "bar": 0.90,
                 "interval": {"method": "clopper-pearson", "sided": "one", "level": 0.95}, "max_move": 16.0},
        "prereg": {"sha256": FIXTURE_DIGEST, "frozen": "2026-10-28T00:00:00Z"},
        "prizes_read": {"url": "https://scrollprize.org/prizes", "date": "2026-10-28"},
        "scrolls": [
            {"scroll": "SYNTH-A", "claim": "measured", "why_not_shown": None,
             "label_scan": {"volume_id": "synthetic-label-scan", "voxel_um": 9.0},
             "truth": {"kind": "finer_scan", "volume_id": "synthetic-fine-scan", "voxel_um": 1.1},
             "oracle": {"kind": "finer_scan", "volume_id": "synthetic-mid-scan", "voxel_um": 2.4},
             "certificate": None,
             "vertices": {"released": 120000, "held_back": 18000, "by_code": {"0": 80000, "2": 38800, "1": 1200}},
             "void": [],
             "strata": [stratum("C0", True, "PASS", "every leg holds", 60, 59, 41, 59, 59, 0.9218, 0.1, 0.45, 11,
                                0.22),
                        stratum("C2", False, "NOT SHOWN", "the lower bound is under the bar", 60, 55, 22, 44, 52,
                                0.632, 0.3, 0.9, 23, 0.25),
                        stratum("C1", False, "UNANSWERABLE", "12 selected sites, under the minimum of 30", 12, 12, 2,
                                5, 9, None, 0.9, 1.6, 31, 0.21),
                        stratum("C0L", False, "PASS", "every leg holds", 60, 59, 38, 59, 59, 0.9218, 0.2, 0.55, 41,
                                0.24)]},
            {"scroll": "SYNTH-B", "claim": "certified", "why_not_shown": None,
             "label_scan": {"volume_id": "synthetic-label-scan-b", "voxel_um": 7.9},
             "truth": None, "oracle": None,
             "certificate": {"method": "synthetic two-face agreement bound", "lower": 0.81, "level": 0.95, "n": 5000,
                             "assumptions": ["Made-up assumption one: the two faces err independently.",
                                             "Made-up assumption two: the sampled vertices represent the scroll."]},
             "vertices": {"released": 90000, "held_back": 9000, "by_code": {"0": 70000, "2": 19000, "1": 1000}},
             "void": [], "strata": []},
            {"scroll": "SYNTH-C", "claim": "not_shown", "why_not_shown":
                "no finer scan and the certificate's assumptions did not hold (synthetic example)",
             "label_scan": {"volume_id": "synthetic-label-scan-c", "voxel_um": 9.0},
             "truth": None, "oracle": None, "certificate": None,
             "vertices": {"released": 40000, "held_back": 4000, "by_code": {"0": 22000, "2": 16000, "1": 2000}},
             "void": [], "strata": []},
        ],
        "showcase": [{"scroll": "SYNTH-A", "segment": "synthetic-sheet", "file": "show/SYNTH-A/synthetic-sheet.json",
                      "spent": True}],
    }
    show = out_dir / "show" / "SYNTH-A"
    show.mkdir(parents=True, exist_ok=True)
    rows_n, cols_n = 24, 96
    res, state, xyz = [], bytearray(), []
    for i in range(rows_n):
        for j in range(cols_n):
            # a sheet wrapped on a circle around (256, 256): column j is the angle, row i is z
            ang = 2 * math.pi * j / cols_n
            rad = 150 + 6 * math.sin(3 * ang)
            xyz += [256 + rad * math.cos(ang), 256 + rad * math.sin(ang), 1000 + 16 * i]
            held = 30 <= j < 42 and 8 <= i < 16
            hole = (j + 3 * i) % 37 == 0
            v = 0.9 * math.sin(ang * 2 + i / 5) + 0.25 * math.cos(ang * 7)
            state.append(2 if held else 1 if hole else 0)
            res.append(float("nan") if held or hole else round(v, 2))
    pieces, planes = [], []
    for i in range(rows_n):
        planes.append({"z": 1000 + 16 * i, "first": len(pieces) // 12, "count": cols_n})
        for j in range(cols_n):
            pts = []
            for jj in (j, (j + 1) % cols_n):
                ang = 2 * math.pi * jj / cols_n
                rad = 150 + 6 * math.sin(3 * ang)
                r_res = 0.9 * math.sin(ang * 2 + i / 5) + 0.25 * math.cos(ang * 7)
                pts.append((rad + 2.0 + 1.5 * math.cos(ang * 5), rad, rad + r_res, ang))
            for which in range(3):   # published, snapped, truth (a positive residual: snapped outward of truth)
                for (rp, rs, rt, ang) in pts:
                    r = (rp, rs, rs - (rt - rs))[which]
                    pieces += [256 + r * math.cos(ang), 256 + r * math.sin(ang)]
    # each piece: 12 floats (published ax ay bx by, snapped ax ay bx by, truth ax ay bx by)
    assert len(pieces) == 12 * rows_n * cols_n
    meta = {"schema": SHOW_SCHEMA, "scroll": "SYNTH-A", "segment": "synthetic-sheet", "stride": 1,
            "shape": [rows_n, cols_n], "voxel_um": 9.0, "volume": None,
            "truth_note": "Synthetic: a made-up face on a made-up sheet. In real results the truth face is found by a "
                          "face rule on the finer scan and registered into the label scan, so it is model output too.",
            "planes": planes,
            "residual": [None if math.isnan(v) else v for v in res], "state": list(state),
            "xyz": [round(v, 2) for v in xyz], "rows": [round(v, 2) for v in pieces]}
    (show / "synthetic-sheet.json").write_text(json.dumps(meta, separators=(",", ":")) + "\n", encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


# ---------------------------------------------------------------- command line

def add_arguments(p):
    a = p.add_subparsers(dest="action", required=True)
    c = a.add_parser("check", help="validate a summary and its showcase files")
    c.add_argument("path", help="the summary JSON, such as spaces/snapped-labels/vx/summary.json")
    c.add_argument("--deploy", action="store_true", help="also refuse the fixture and placeholder digests")
    c.add_argument("--online", action="store_true", help="also confirm the dataset revision on Hugging Face (network)")
    f = a.add_parser("fixture", help="write the synthetic fixture (summary.json and show/)")
    f.add_argument("out_dir", help="the folder to write, such as spaces/snapped-labels/vx/fixture")


def run(args):
    if args.action == "fixture":
        fixture(args.out_dir)
        print(f"{args.out_dir}: synthetic fixture written (fixture: true; never deploys)")
        return 0
    try:
        doc = load(args.path)
    except (OSError, ValueError) as exc:
        print(f"{args.path}: cannot read the summary ({exc})", file=sys.stderr)
        return 2
    problems = check(doc, deploy=args.deploy, base=Path(args.path).parent)
    if args.online and not problems:
        problems = online_problems(doc)
    for p in problems:
        print(f"{args.path}: {p}", file=sys.stderr)
    if problems:
        return 1
    kinds = {c: sum(1 for s in doc["scrolls"] if s.get("claim") == c) for c in CLAIMS}
    print(f"{args.path}: valid ({kinds['measured']} measured, {kinds['certified']} certified, {kinds['not_shown']} not "
          f"shown{', synthetic fixture' if doc.get('fixture') else ''})")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit vxsummary", description=__doc__.split("\n\n")[0])
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
