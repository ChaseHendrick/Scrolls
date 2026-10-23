"""Research integrity checks for Vesuvius Challenge claims: `python -m kit integrity` (or `kit integrity`).

It applies the rules of the Research-Integrity skill (https://github.com/ChaseHendrick/Research-Integrity, release
1.5.0) to the claims this community makes most often: an ink score, a comparison of two readers, a sentence in a
write-up, a preregistration and a citation. Every command first plants faults and must reject each one, for its own
reason and through the same code the real check uses, before it reads anything real (skill rules 4 and 8). If a
planted fault slips through, the command exits 1 and reports no result.

  kit integrity rules [--json]
        every rule: its id, severity, what it catches, the fix and where the rule comes from
  kit integrity exposure [--results docs/results.json] [--json]
        which public ink readers trained on which labeled test groups, from results.json `held_out_by_reader`
  kit integrity ink CLAIM.json [...] [--reader R] [--segment S] [--results docs/results.json] [--json] [--strict]
        one ink-score claim per file: a claim record (fields below), or `kit auc --json` output with --reader and
        --segment
  kit integrity results [--results docs/results.json] [--json] [--strict]
        every AUC row of results.json through the ink checks
  kit integrity text FILE [...] [--json] [--strict]
        overclaim wording in Markdown or plain text
  kit integrity prereg PREREG --result FILE [...] [--json]
        the git order of a preregistration and the result files it governs
  kit integrity cite FILE [...] [--offline] [--json]
        every arXiv id the files cite exists, and each docs/papers.json-style title matches arXiv's
  kit integrity selftest [--json]
        run only the planted faults

A claim record (JSON object): `reader` (such as "ink_9um seed42"), `segment` (a results.json segment key such as
"0841-w00", or a test group: "PHerc0841", "w045"), `auc` (the forward score), `control_auc` (the same map read in
reverse depth order, on the same pixels), `mask` ("supervision" when only supervised pixels were scored),
`window` ("whole" or "crop"), `claims_held_out` (true when the write-up calls the score held out, unseen or a
generalization test), `source` ({"file": PATH, "field": "dotted.path"}: the run output the number was copied from)
and `beats` ({"reader", "auc", "window", "ci95": [low, high]} for a claim that this reader beats another; `ci95` is
the interval of the difference, such as `kit auc --compare --bootstrap` prints). A number may be given as a string
("0.7382") to state its precision; a JSON number's precision is its shortest decimal form.

Exit codes: 0 no FAIL finding (WARN findings are printed), 3 at least one FAIL (with --strict, a WARN as well),
1 bad input or a planted fault that was not caught, 2 the answer needs data this checkout does not have (a shallow
or missing git history for prereg, no network for cite).

What it does not do. A pass means the stated record survives these rules, not that the claim is true: it cannot
see pixels that were never scored, training data a model card does not list, or a sentence written in other words.
The exposure table is this repository's reading of public sources (its reasons are in results.json `held_out`).
Standard library only; `cite` alone uses the network (the arXiv export API).
"""

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from . import leaderboard

ROOT = Path(__file__).resolve().parent.parent
RESULTS = "docs/results.json"
SKILL = "https://github.com/ChaseHendrick/Research-Integrity"
PRIZES = "https://scrollprize.org/prizes"
MIN_GAP = leaderboard.MIN_GAP  # 0.10, as in kit/gate.py, where the docstring says it was set after looking
MIN_MARGIN = 0.02  # kit/gate.py: one reader beats another only by at least 0.02 mean AUC
FAIL, WARN = "FAIL", "WARN"
EXIT_OK, EXIT_BAD, EXIT_MISSING, EXIT_FINDING = 0, 1, 2, 3

RULES = [
    {"id": "ink-control", "severity": FAIL, "what": "an ink score with no reverse-depth control on the same pixels",
     "fix": "score the same reader's reverse-depth map on the same pixels (kit auc --control) and report both",
     "source": "skill rule 4; AGENTS.md hard rule 4; docs/STANDARDS.md section 1"},
    {"id": "ink-gap", "severity": FAIL,
     "what": "forward minus reverse at or below 0 (FAIL), or below 0.10 (WARN): the map may follow brightness, "
             "not ink in the depth direction",
     "fix": "report the gap beside the score; below 0.10 do not call it ink detection without more controls",
     "source": "kit/gate.py min_gap 0.10 (set after the committed gaps were seen, as its docstring says)"},
    {"id": "ink-heldout", "severity": FAIL,
     "what": "a score called held out, unseen or a generalization test on a group the reader trained on (FAIL); "
             "a score on such a group, or one with no exposure record, that does not say so (WARN)",
     "fix": "check `kit integrity exposure`; call an in-sample score a training-surface check",
     "source": "results.json held_out; Grand Prize: no overlap between training and prediction regions"},
    {"id": "ink-mask", "severity": FAIL,
     "what": "pixels outside the supervision mask scored as background (FAIL), or the mask not stated (WARN)",
     "fix": "score inside the supervision mask only: labelers marked ink and non-ink there and nowhere else",
     "source": "kit/auc.py docstring"},
    {"id": "ink-source", "severity": FAIL,
     "what": "the claimed number differs from the named field of the run that produced it (FAIL), or no run "
             "output is named (WARN)",
     "fix": "copy every number from a named field of the run output, at the precision it is quoted",
     "source": "skill rule 4: a number in a claim is copied from the run that produced it"},
    {"id": "ink-compare", "severity": FAIL,
     "what": "a 'beats' claim across different windows, or whose 95 % interval of the difference reaches 0 "
             "(FAIL); a margin under 0.02 or no interval at all (WARN)",
     "fix": "compare on the same window and edge; give the block-bootstrap interval (kit auc --compare)",
     "source": "kit/gate.py 0.02 margin; docs/STANDARDS.md: a difference smaller than the measured noise"},
    {"id": "text-reading", "severity": FAIL,
     "what": "model output described as letters, words or text found, read or recovered",
     "fix": "an ink map is model output: say what the map shows (ink-like strokes) and leave readings to "
            "papyrologists",
     "source": "AGENTS.md hard rule 2; docs/QUALITY.md: ink detected, letters visible, legible"},
    {"id": "text-heldout", "severity": FAIL,
     "what": "a sentence calling a score held out, unseen or a generalization test while naming a reader and a "
             "test group that reader trained on",
     "fix": "check `kit integrity exposure` and name the score a training-surface check",
     "source": "results.json held_out and held_out_by_reader"},
    {"id": "text-novelty", "severity": WARN,
     "what": "novelty or ranking claims: first, no prior work, state of the art, the best, beats every",
     "fix": "state novelty only within the search's reach: 'searches of X and Y found no earlier statement'",
     "source": "skill rule 3"},
    {"id": "text-review", "severity": WARN,
     "what": "independently, externally or peer reviewed or verified, without a person outside the project",
     "fix": "'read by a separate AI session in this project; not an outside review', or name the reviewer",
     "source": "skill rule 6"},
    {"id": "text-certainty", "severity": WARN, "what": "proves, definitively, guaranteed, for a measured result",
     "fix": "state the test, its power and the result, and the data it was measured on",
     "source": "skill phrase table"},
    {"id": "text-disclosure", "severity": WARN,
     "what": "possible or candidate letters, words or titles described in a public text",
     "fix": "keep possible findings private: the prize page says not to make a discovery public until the "
            "prize is officially announced",
     "source": PRIZES},
    {"id": "prereg-order", "severity": FAIL,
     "what": "a result file committed before its preregistration (FAIL), or the preregistration changed after "
             "the first result: lines removed (FAIL), lines only added (WARN, check it is a dated amendment)",
     "fix": "commit the readout rule before any map exists; change it only by a dated amendment at its end",
     "source": "AGENTS.md hard rule 3; skill rule 7"},
    {"id": "prereg-content", "severity": WARN,
     "what": "a preregistration that names no control, no decision rule or no test data",
     "fix": "name the control, the threshold and its source, and the data the test reads once",
     "source": "docs/STANDARDS.md section 1"},
    {"id": "cite-missing", "severity": FAIL, "what": "an arXiv id that arXiv does not return",
     "fix": "copy the id from the paper's page; never reconstruct it", "source": "skill rule 1"},
    {"id": "cite-title", "severity": FAIL, "what": "a recorded title that differs from arXiv's",
     "fix": "copy titles from the source, not from memory", "source": "skill rule 1"},
]
RULE_IDS = [r["id"] for r in RULES]


class IntegrityError(ValueError):
    pass


class MissingData(Exception):
    """The answer needs data this checkout does not have (exit 2)."""


def _finding(rule, severity, where, message):
    return {"rule": rule, "severity": severity, "where": where, "message": message}


# ---------- exposure ----------

def _load_results(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise IntegrityError(f"{path}: {e}")


def group_of(segment, results):
    """The held-out test group of a segment name: a key of held_out_by_reader, or the scroll of a segment key."""
    table = results.get("held_out_by_reader", {})
    groups = [g for g in table if g != "about"]
    if segment in groups:
        return segment
    seg = results.get("segments", {}).get(segment)
    if seg and seg.get("scroll") in groups:
        return seg["scroll"]
    low = segment.lower()
    for g in groups:
        if g.lower() in low:
            return g
    return None


def exposure(reader, segment, results):
    """'held out', 'possibly not held out', 'not held out', or None when no record covers the pair."""
    group = group_of(segment, results)
    if group is None:
        return None, None
    try:
        return group, leaderboard.status(reader, group, results.get("held_out_by_reader", {}))
    except leaderboard.BoardError:
        return group, None


# ---------- numbers ----------

def _decimals(value):
    s = value if isinstance(value, str) else repr(float(value))
    s = s.strip()
    if "e" in s.lower():
        return 6
    return len(s.split(".", 1)[1]) if "." in s else 0


def _number(value, what):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise IntegrityError(f"{what}: not a number: {value!r}")


def _same_at_precision(claimed, stored):
    d = _decimals(claimed)
    return abs(float(claimed) - float(stored)) <= 0.5 * 10 ** -d + 1e-12


def _field(data, dotted):
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                raise IntegrityError(f"field {dotted!r}: no item {part!r}")
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise IntegrityError(f"field {dotted!r}: no key {part!r}")
    return cur


# ---------- ink claims ----------

def claim_from(data, reader=None, segment=None):
    """A claim record from a claim file, or from `kit auc --json` output (it has 'forward')."""
    if not isinstance(data, dict):
        raise IntegrityError("a claim is a JSON object")
    if "forward" in data:
        c = {"auc": data["forward"].get("auc"),
             "control_auc": (data.get("control") or {}).get("auc"),
             "mask": "supervision" if (data.get("files") or {}).get("mask") else None,
             "window": "crop" if data.get("crop") else "whole"}
        c.update({k: v for k, v in data.items() if k in ("reader", "segment", "claims_held_out", "source", "beats")})
    else:
        c = dict(data)
    if reader:
        c["reader"] = reader
    if segment:
        c["segment"] = segment
    for k in ("reader", "segment", "auc"):
        if c.get(k) in (None, ""):
            raise IntegrityError(f"the claim has no {k!r}")
    return c


def check_ink(claim, results, where="claim", root=ROOT):
    out = []
    auc = _number(claim.get("auc"), "auc")
    ctrl = _number(claim.get("control_auc"), "control_auc")
    if ctrl is None:
        out.append(_finding("ink-control", FAIL, where, f"AUC {claim['auc']} has no reverse-depth control: an "
                           "uncontrolled score, not a pass"))
    else:
        gap = auc - ctrl
        if gap <= 0:
            out.append(_finding("ink-gap", FAIL, where, f"forward {auc:.4f} minus reverse {ctrl:.4f} = {gap:+.4f}: "
                               "the map scores as well read backwards"))
        elif gap < MIN_GAP:
            out.append(_finding("ink-gap", WARN, where, f"forward minus reverse {gap:+.4f} is under {MIN_GAP:.2f}"))
    group, status = exposure(claim["reader"], claim["segment"], results)
    held = bool(claim.get("claims_held_out"))
    if status is None:
        out.append(_finding("ink-heldout", FAIL if held else WARN, where,
                           f"no exposure record for {claim['reader']!r} on {claim['segment']!r}"
                           + (": a held-out claim needs one" if held else ": say what the reader trained on")))
    elif status != "held out":
        out.append(_finding("ink-heldout", FAIL if held else WARN, where,
                           f"{claim['reader']} is {status} on {group}"
                           + (": the claim calls it held out" if held else ": a training-surface check, "
                              "not a generalization score")))
    mask = claim.get("mask")
    if mask is None:
        out.append(_finding("ink-mask", WARN, where, "the claim does not say which pixels were scored"))
    elif str(mask).lower() != "supervision":
        out.append(_finding("ink-mask", FAIL, where, f"scored on {mask!r}, not inside the supervision mask"))
    src = claim.get("source")
    if not src:
        out.append(_finding("ink-source", WARN, where, "no run output named for the number"))
    else:
        try:
            path = Path(src["file"])
            path = path if path.is_absolute() else root / path
            stored = _field(json.loads(path.read_text()), src["field"])
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise IntegrityError(f"{where}: source {src!r}: {e}")
        if not _same_at_precision(claim["auc"], stored):
            out.append(_finding("ink-source", FAIL, where, f"claimed {claim['auc']} but {src['file']} "
                               f"{src['field']} holds {stored}"))
    beats = claim.get("beats")
    if beats:
        other = _number(beats.get("auc"), "beats.auc")
        if beats.get("window", claim.get("window")) != claim.get("window"):
            out.append(_finding("ink-compare", FAIL, where, f"window {claim.get('window')!r} compared with "
                               f"{beats.get('window')!r}: crop scores run higher than whole-map ones"))
        ci = beats.get("ci95")
        if ci:
            if float(ci[0]) <= 0:
                out.append(_finding("ink-compare", FAIL, where, f"the difference's 95 % interval [{ci[0]}, {ci[1]}] "
                                   "reaches 0: not distinguishable from sampling noise"))
        else:
            out.append(_finding("ink-compare", WARN, where, "no interval for the difference: noise not measured"))
        if other is not None and auc - other < MIN_MARGIN and not (ci and float(ci[0]) > 0):
            out.append(_finding("ink-compare", WARN, where, f"margin {auc - other:+.4f} is under {MIN_MARGIN}"))
    return out


def result_rows(results):
    """Every row of results.json that carries an AUC, as (where, claim)."""
    for key, rows in results.items():
        if not isinstance(rows, list):
            continue
        for i, r in enumerate(rows):
            if isinstance(r, dict) and r.get("auc_as_stored") is not None and r.get("reader"):
                yield f"{key}/{i}", {"reader": r["reader"], "segment": r.get("segment", ""),
                                     "auc": r["auc_as_stored"], "control_auc": r.get("auc_reversed"),
                                     "mask": "supervision", "window": r.get("window"),
                                     "source": {"file": RESULTS, "field": f"{key}.{i}.auc_as_stored"}}


# ---------- text ----------

NEGATION = re.compile(r"\b(not|never|no|nor|without|avoid|instead of|rather than|don't|do not|does not|"
                      r"did not|cannot|isn't|aren't|wasn't|weren't|nothing)\b|n't\b", re.I)
QUOTED = re.compile(r"`[^`]*`|\"[^\"]*\"|“[^”]*”|'[^'\n]{3,}'(?!\w)")
LINK = re.compile(r"\]\([^)]*\)|https?://\S+")
ALLOW = re.compile(r"<!--\s*integrity:\s*allow\s*([\w\- ,]*)-->")
SENTENCE = re.compile(r"(?<=[.!?;])\s+")
OBJECT = r"(letters?|words?|lines? of text|text|titles?|characters?|columns?|passages?)"
TEXT_PATTERNS = {
    "text-reading": [
        # passive: "letters were found", "the title was read"; bare "letters found" only for discovery verbs
        r"\b" + OBJECT + r"\s+(were|was|are|is|have been|has been|got|can be|could be)\s+(found|read|revealed|"
        r"recovered|deciphered|discovered|uncovered|decoded|identified)\b",
        r"\b" + OBJECT + r"\s+(found|revealed|discovered|uncovered)\s+(in|on|at|inside)\b",
        # active, with our side as the subject: "we read three lines", "the model found the letters"
        r"\b(we|i|the model|our model|the map|the ink map|the network)\s+(read|reads|deciphered|deciphers|decoded|"
        r"decodes|found|finds|recovered|recovers|revealed|reveals|discovered|uncovered)\s+(?:\w+\s+){0,2}"
        + OBJECT[:-1] + r"|lines?)\b",
    ],
    "text-novelty": [r"\bthis is the first\b", r"\b(is|are|was|were|be) the first (\w+ ){0,3}(to|ever)\b",
                     r"\bfirst[- ]ever\b", r"\bno prior work\b", r"\bnever been done\b",
                     r"\bstate[- ]of[- ]the[- ]art\b",
                     r"\b(is|are|was|were) the best (\w+ )?(method|model|tool|reader|pipeline|approach|result|"
                     r"submission|work|ink model|segmentation)s?\b",
                     r"\b(beats|outperforms|surpasses) (all|every|any) (other |existing |published |prior |released )?"
                     r"(methods?|models?|tools?|approach(es)?|readers?|baselines?|pipelines?)\b",
                     r"\bthe first (fully |truly |completely )?(automated|open[- ]source|public|end[- ]to[- ]end) "
                     r"(\w+[- ]){0,2}(method|tool|model|pipeline|approach|system|unwrapping|reading|segmentation)\b",
                     r"\bunprecedented\b"],
    "text-review": [r"\b(was|were|been|is|are)\s+(independently|externally)\s+(reviewed|verified|validated|"
                    r"checked|replicated|confirmed)\b"],
    "text-certainty": [r"(?<!to )\bproves?\b(?! to be)(?!\s+(little|nothing|only))", r"\bdefinitive(ly)?\b",
                       r"\bconclusively\b", r"\bbeyond (any )?doubt\b"],
    "text-disclosure": [r"\b(possible|candidate|potential|probable|likely)\s+(letters?|words?|titles?|"
                        r"characters?|text)\b(?=.*\b(PHerc|scroll|segment|column|near|region|at|in the (map|scan)))",
                        r"\b(letters?|letterforms?|words?|text|titles?)\s+(are |is |were |was |now |clearly )*"
                        r"(visible|legible|readable)\b(?=.*\b(PHerc|scroll|segment|column))"],
}
TEXT_RE = {k: [re.compile(p, re.I) for p in v] for k, v in TEXT_PATTERNS.items()}
# a sentence about others' readings (organizers, papyrologists, prizes) is not a claim of our own reading
ATTRIBUTED = re.compile(r"organi[sz]er|official|papyrolog|announced|awarded|prize|judged|review team", re.I)
EXCEPTION = re.compile(r"\bexcept|\bbut\b|\bonly\b|possibl|\bunless\b", re.I)
LEAD_IN = re.compile(r":\s*$")
# a line that opens with a negated label, such as "- **Never:** ..." or "Not a pass: ..."
NEGATED_LABEL = re.compile(r"^([-*+]\s+)?\**\s*(never|not|do not|don't|avoid|no)\b[^.:]{0,40}:", re.I)
HELDOUT_META = re.compile(r"held[- ]out (wording|words?|text|status|column|key|labels?|flag|field)", re.I)
HEADING = re.compile(r"^(#+)\s")
HELDOUT_WORDS = re.compile(r"\b(held[- ]out|unseen|generali[sz](e|ed|es|ation|ing)|out[- ]of[- ]sample)\b", re.I)
SEVERITY = {r["id"]: r["severity"] for r in RULES}


def _clean(line):
    line = LINK.sub(" ", line)
    return QUOTED.sub(" ", line)


def _negated(sentence, start):
    return bool(NEGATION.search(sentence[:start]))


def _group_names(results):
    names = {}
    for g in results.get("held_out_by_reader", {}):
        if g != "about":
            names[g] = re.compile(re.escape(g), re.I)
    for key, seg in results.get("segments", {}).items():
        if seg.get("scroll") in names:
            short = key.split("-", 1)[-1]
            names.setdefault(f"{seg['scroll']}:{short}", re.compile(r"\b" + re.escape(short) + r"\b", re.I))
    return names


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _units(raw, header):
    """The pieces of a line to judge one by one: its sentences, or a table row's cells whose column heading is not
    negated (a "Does not" column lists what a tool does not do)."""
    if not raw.lstrip().startswith("|"):
        return SENTENCE.split(_clean(raw))
    cells = _cells(raw)
    return [_clean(c) for i, c in enumerate(cells) if not (i < len(header) and NEGATION.search(header[i]))]


def check_text(text, results, where="text"):
    """Findings for overclaim wording. Skipped: code, quotations, links, block quotes, sentences negated before the
    phrase, a section whose heading is negated ("What it does not do"), the list after a negated lead-in ("Do not:"),
    table columns whose heading is negated, and lines marked <!-- integrity: allow [RULE ...] -->."""
    out, fenced, header = [], False, []
    neg_section = None  # heading level of a negated section
    neg_list = False
    lines = text.splitlines()
    groups = _group_names(results)
    table = results.get("held_out_by_reader", {})
    families = [(f, re.compile(r"(?<![\w-])" + re.escape(f) + r"(?![\w-])", re.I)) for f in leaderboard.FAMILIES]
    for n, raw in enumerate(lines, 1):
        s = raw.strip()
        if s.startswith("```") or s.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced:
            continue
        h = HEADING.match(s)
        if h:
            level = len(h.group(1))
            if neg_section is not None and level <= neg_section:
                neg_section = None
            if neg_section is None and NEGATION.search(s):
                neg_section = level
            neg_list = False
            continue
        if not s:
            continue
        is_item = bool(re.match(r"^([-*+]|\d+[.)])\s", s))
        if not is_item and not s.startswith("|"):
            neg_list = False
        if not s.startswith("|"):
            header = []
        elif n < len(lines) and "-" in lines[n] and re.match(r"^\|?[\s:|-]+\|?$", lines[n].strip()):
            header = _cells(raw)
            continue
        elif re.match(r"^\|?[\s:|-]+\|?$", s):
            continue
        lead_in = bool(LEAD_IN.search(s) and NEGATION.search(s))
        skip = (neg_section is not None or (neg_list and is_item) or s.startswith(">")
                or bool(NEGATED_LABEL.match(s)))
        if lead_in:
            neg_list = True
        if skip:
            continue
        allow = ALLOW.search(raw)
        allowed = set(re.split(r"[\s,]+", allow.group(1).strip())) - {""} if allow else set()
        if allow and not allowed:
            continue
        for sentence in _units(raw, header):
            for rule, pats in TEXT_RE.items():
                if rule in allowed or (rule == "text-reading" and ATTRIBUTED.search(sentence)):
                    continue
                for pat in pats:
                    m = pat.search(sentence)
                    if m and not _negated(sentence, m.start()):
                        out.append(_finding(rule, SEVERITY[rule], f"{where}:{n}", sentence.strip()[:200]))
                        break
            m = HELDOUT_WORDS.search(sentence)
            if (not m or "text-heldout" in allowed or NEGATION.search(sentence) or EXCEPTION.search(sentence)
                    or HELDOUT_META.search(sentence)):
                continue
            named_groups = {g.split(":")[0] for g, p in groups.items() if p.search(sentence)}
            named = [f for f, p in families if p.search(sentence)]
            for g in sorted(named_groups):
                bad = [f for f in named if table.get(g, {}).get(f) in ("not held out", "possibly not held out")]
                if bad:
                    out.append(_finding("text-heldout", FAIL, f"{where}:{n}",
                                       f"{', '.join(bad)} not held out on {g}: {sentence.strip()[:160]}"))
    return out


# ---------- preregistration order ----------

def _git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if r.returncode:
        raise IntegrityError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def _history(root, path):
    """[(commit, unix time)] of the commits that touched path, oldest first, following renames."""
    rows = _git(root, "log", "--follow", "--format=%H %ct", "--", path).split()
    return [(rows[i], int(rows[i + 1])) for i in range(0, len(rows), 2)][::-1]


def _order_findings(prereg, prereg_hist, results_hist, removed_after, added_after, where):
    """The ordering rule on plain data, so the planted faults run the same decision as the real check."""
    out = []
    first_prereg = prereg_hist[0][1]
    for path, h in results_hist.items():
        if h[0][0] == prereg_hist[0][0]:
            out.append(_finding("prereg-order", WARN, where, f"{path} arrived in the same commit as {prereg}: this "
                               "history cannot show which came first (a copy from another repository, or a squash); "
                               "point to where the rule was frozen"))
        elif h[0][1] <= first_prereg:
            out.append(_finding("prereg-order", FAIL, where, f"{path} was first committed before {prereg}"))
    if removed_after:
        out.append(_finding("prereg-order", FAIL, where, f"{prereg} lost {removed_after} line(s) in or after the commit "
                           "that added the first result"))
    elif added_after:
        out.append(_finding("prereg-order", WARN, where, f"{prereg} gained {added_after} line(s) in or after the commit "
                           "that added the first result: check they are a dated amendment"))
    return out


CONTENT = {"control": r"\bcontrols?\b|revers|baseline|\bsham|\bnull|shuffl|placebo|\bprobe", "decision rule": r"\bthreshold|\bbar\b|\bpass\b|\bfail\b|"
           r"\brule\b|\bcutoff\b", "test data": r"held[- ]out|\btest\b|unseen|\bsplit\b"}


def _content_findings(text, where):
    return [_finding("prereg-content", WARN, where, f"names no {name}") for name, pat in CONTENT.items()
            if not re.search(pat, text, re.I)]


def check_prereg(root, prereg, result_paths):
    where = prereg
    if _git(root, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise MissingData("this clone is shallow: fetch its history first (git fetch --unshallow, or a bounded "
                          "git fetch --depth=1000)")
    ph = _history(root, prereg)
    if not ph:
        raise MissingData(f"{prereg} has no commit in this clone")
    rh = {}
    for p in result_paths:
        h = _history(root, p)
        if not h:
            raise MissingData(f"{p} has no commit in this clone")
        rh[p] = h
    first_result = min(h[0][1] for h in rh.values())
    before = [c for c, t in ph if t < first_result]
    removed = added = 0
    if before and before[-1] != ph[-1][0]:
        for line in _git(root, "diff", "--numstat", before[-1], ph[-1][0], "--", prereg).splitlines():
            a, r, _ = line.split("\t", 2)
            added, removed = added + int(a), removed + int(r)
    text = (Path(root) / prereg).read_text()
    return _order_findings(prereg, ph, rh, removed, added, where) + _content_findings(text, where)


# ---------- citations ----------

ARXIV_ID = re.compile(r"(?:arXiv[: ]\s*|arxiv\.org/(?:abs|pdf)/|\[)(\d{4}\.\d{4,5})(?:v\d+)?", re.I)


def arxiv_ids(text):
    return sorted(set(ARXIV_ID.findall(text)))


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def arxiv_titles(ids, opener=urllib.request.urlopen, sleep=time.sleep):
    """{id: title} from the arXiv export API, 20 ids a request, backing off on 429."""
    titles, ns = {}, {"a": "http://www.w3.org/2005/Atom"}
    for i in range(0, len(ids), 20):
        q = urllib.parse.urlencode({"id_list": ",".join(ids[i:i + 20]), "max_results": 20})
        for wait in (0, 10, 30, 60, 120):
            sleep(wait)
            try:
                data = opener("https://export.arxiv.org/api/query?" + q, timeout=120).read()
                break
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    raise
        else:
            raise MissingData("arXiv kept answering 429; rerun later or pass --offline")
        for e in ET.fromstring(data).findall("a:entry", ns):
            aid = re.sub(r"v\d+$", "", e.find("a:id", ns).text.rsplit("/", 1)[-1])
            t = e.find("a:title", ns)
            if t is not None and t.text:
                titles[aid] = " ".join(t.text.split())
        sleep(3.5)
    return titles


def papers_titles(data):
    """{arXiv id: title} from a docs/papers.json-style file ({"entries": [{"id": "arXiv:...", "title"}]})."""
    entries = data.get("entries", []) if isinstance(data, dict) else []
    return {e["id"].split(":", 1)[1]: e.get("title", "") for e in entries
            if isinstance(e, dict) and str(e.get("id", "")).startswith("arXiv:")}


def check_citations(ids, recorded, titles, where="cite"):
    out = []
    for i in sorted(set(ids) | set(recorded)):
        if i not in titles:
            out.append(_finding("cite-missing", FAIL, where, f"arXiv {i} not returned by arXiv"))
        elif i in recorded and _norm(recorded[i]) != _norm(titles[i]):
            out.append(_finding("cite-title", FAIL, where, f"arXiv {i}: recorded {recorded[i]!r}, arXiv has "
                               f"{titles[i]!r}"))
    return out


# ---------- planted faults ----------

PLANT_RESULTS = {
    "held_out_by_reader": {"PHerc0841": {"ink_9um": "held out", "Hecate": "not held out"},
                           "w045": {"v8in": "held out", "ink_9um": "not held out"}},
    "segments": {"0841-w00": {"scroll": "PHerc0841"}, "w045": {"scroll": "PHerc0139"}},
}
CLEAN_CLAIM = {"reader": "ink_9um seed42", "segment": "0841-w00", "auc": "0.80", "control_auc": 0.45,
               "mask": "supervision", "window": "crop", "claims_held_out": True}
CLEAN_TEXT = ("The ink map is model output. ink_9um scored 0.80 on held-out PHerc0841 w00, against 0.45 reversed.\n"
              "Searches of arXiv and villa found no earlier statement; Discord history could not be searched.\n"
              "Do not write \"letters were found\": an ink map is not a reading.\n"
              "```\nletters were found\n```\n")


def _plants():
    """(name, kind, input, expected rule, expected severity[, text the message must hold]): each must produce
    that finding."""
    c = CLEAN_CLAIM
    return [
        ("no control", "ink", {**c, "control_auc": None}, "ink-control", FAIL),
        ("reverse beats forward", "ink", {**c, "control_auc": 0.81}, "ink-gap", FAIL),
        ("small gap", "ink", {**c, "control_auc": 0.75}, "ink-gap", WARN),
        ("held out on a training group", "ink", {**c, "reader": "Hecate"}, "ink-heldout", FAIL),
        ("in-sample, not called held out", "ink", {**c, "reader": "Hecate", "claims_held_out": False},
         "ink-heldout", WARN),
        ("no exposure record", "ink", {**c, "segment": "PHerc9999-x"}, "ink-heldout", FAIL),
        ("scored outside the mask", "ink", {**c, "mask": "whole surface"}, "ink-mask", FAIL),
        ("mask not stated", "ink", {**c, "mask": None}, "ink-mask", WARN),
        ("compare across windows", "ink", {**c, "beats": {"reader": "x", "auc": 0.70, "window": "whole",
                                                          "ci95": [0.05, 0.15]}}, "ink-compare", FAIL),
        ("interval reaches 0", "ink", {**c, "beats": {"reader": "x", "auc": 0.70, "ci95": [-0.01, 0.2]}},
         "ink-compare", FAIL),
        ("no interval", "ink", {**c, "beats": {"reader": "x", "auc": 0.70}}, "ink-compare", WARN, "no interval"),
        ("margin under 0.02", "ink", {**c, "beats": {"reader": "x", "auc": 0.79}}, "ink-compare", WARN, "margin"),
        ("reading claim", "text", "The model found the letters of a title in the map.\n", "text-reading", FAIL),
        ("we read", "text", "On PHerc0841 we read three lines.\n", "text-reading", FAIL),
        ("held out mislabel", "text", "ink_9um generalizes to unseen w045 with AUC 0.87.\n", "text-heldout", FAIL),
        ("novelty", "text", "This is the first tool to trace fibers.\n", "text-novelty", WARN),
        ("review", "text", "The results were independently verified.\n", "text-review", WARN),
        ("certainty", "text", "This proves the method works.\n", "text-certainty", WARN),
        ("disclosure", "text", "The map shows possible letters near the top.\n", "text-disclosure", WARN),
        ("result before prereg", "order", ([("p", 20)], {"r.json": [("r", 10)]}, 0, 0), "prereg-order", FAIL),
        ("result in the prereg's commit", "order", ([("p", 20)], {"r.json": [("p", 20)]}, 0, 0), "prereg-order",
         WARN),
        ("prereg edited after result", "order", ([("p", 10), ("p2", 30)], {"r.json": [("r", 20)]}, 3, 1),
         "prereg-order", FAIL),
        ("prereg amended after result", "order", ([("p", 10), ("p2", 30)], {"r.json": [("r", 20)]}, 0, 4),
         "prereg-order", WARN),
        ("prereg names nothing", "content", "We will run the model and look at it.", "prereg-content", WARN),
        ("missing arXiv id", "cite", (["2610.99999"], {}, {}), "cite-missing", FAIL),
        ("wrong title", "cite", ([], {"2610.30495": "Wrong title"}, {"2610.30495": "From Prose to Properties"}),
         "cite-title", FAIL),
    ]


def _run_plant(kind, value, root):
    if kind == "ink":
        return check_ink(claim_from(value), PLANT_RESULTS, "plant", root)
    if kind == "text":
        return check_text(value, PLANT_RESULTS, "plant")
    if kind == "order":
        ph, rh, removed, added = value
        return _order_findings("prereg.md", ph, rh, removed, added, "plant")
    if kind == "content":
        return _content_findings(value, "plant")
    ids, rec, titles = value
    return check_citations(ids, rec, titles, "plant")


def _selftest_core(root):
    tried = []
    for name, kind, value, rule, severity, *text in _plants():
        got = _run_plant(kind, value, root)
        if not any(f["rule"] == rule and f["severity"] == severity and all(t in f["message"] for t in text)
                   for f in got):
            raise IntegrityError(f"planted fault {name!r} was not caught as {severity} {rule}: got {got}")
        other = [f for f in got if f["rule"] != rule and f["severity"] == FAIL and kind == "ink"]
        if other:
            raise IntegrityError(f"planted fault {name!r} also failed for another reason: {other}")
        tried.append({"plant": name, "rule": rule, "severity": severity})
    clean_ink = check_ink(claim_from(CLEAN_CLAIM), PLANT_RESULTS, "clean", root)
    clean_ink = [f for f in clean_ink if f["rule"] != "ink-source"]  # the clean claim names no run file
    if clean_ink:
        raise IntegrityError(f"the clean claim was flagged: {clean_ink}")
    clean_text = check_text(CLEAN_TEXT, PLANT_RESULTS, "clean")
    if clean_text:
        raise IntegrityError(f"the clean text was flagged: {clean_text}")
    if _order_findings("p.md", [("p", 10)], {"r.json": [("r", 20)]}, 0, 0, "clean"):
        raise IntegrityError("the clean preregistration order was flagged")
    if check_citations(["2610.30495"], {"2610.30495": "From prose to properties!"},
                       {"2610.30495": "From Prose to Properties"}, "clean"):
        raise IntegrityError("the clean citation was flagged")
    covered = {t["rule"] for t in tried}
    missing = [r for r in RULE_IDS if r not in covered and r != "ink-source"]
    if missing:
        raise IntegrityError(f"rules with no planted fault: {missing}")
    return {"plants": len(tried), "caught": len(tried), "clean_controls": 4, "rules": sorted(covered)}


def _selftest_source(root):
    """ink-source needs a file: plant a run output whose number differs, and one that matches."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "auc.json"
        p.write_text(json.dumps({"forward": {"auc": 0.7382}}))
        bad = {**CLEAN_CLAIM, "auc": "0.7482", "source": {"file": str(p), "field": "forward.auc"}}
        good = {**CLEAN_CLAIM, "auc": "0.738", "source": {"file": str(p), "field": "forward.auc"}}
        got = check_ink(claim_from(bad), PLANT_RESULTS, "plant", root)
        if not any(f["rule"] == "ink-source" and f["severity"] == FAIL for f in got):
            raise IntegrityError(f"planted fault 'number not in its run' was not caught: got {got}")
        if check_ink(claim_from(good), PLANT_RESULTS, "clean", root):
            raise IntegrityError("the clean sourced claim was flagged")
    return 1


def selftest(root=ROOT):
    """Run every planted fault and the clean controls through the real checks; raise IntegrityError on the first
    one not handled. Returns {"plants", "caught", "clean_controls", "rules"}."""
    st = _selftest_core(root)
    st["plants"] += _selftest_source(root)
    st["caught"] += 1
    st["clean_controls"] += 1
    st["rules"] = sorted(set(st["rules"]) | {"ink-source"})
    return st


# ---------- command line ----------

def add_arguments(p):
    sub = p.add_subparsers(dest="action", required=True)

    def common(s, results=True, strict=True):
        if results:
            s.add_argument("--results", default=RESULTS,
                           help="results.json with held_out_by_reader and segments (the exposure table)")
        s.add_argument("--json", action="store_true", help="print one JSON object instead of lines")
        if strict:
            s.add_argument("--strict", action="store_true", help="exit 3 on a WARN finding too")

    common(sub.add_parser("rules", help="every rule, its severity, fix and source"), results=False, strict=False)
    common(sub.add_parser("exposure", help="which public ink readers trained on which labeled test groups"),
           strict=False)
    s = sub.add_parser("ink", help="check ink-score claims (claim records or kit auc --json output)")
    s.add_argument("claims", nargs="+", help="claim files (JSON): claim records or kit auc --json output")
    s.add_argument("--reader", help="the reader, for kit auc output that does not name it")
    s.add_argument("--segment", help="the segment key or test group, for kit auc output that does not name it")
    common(s)
    common(sub.add_parser("results", help="every AUC row of results.json through the ink checks"))
    s = sub.add_parser("text", help="overclaim wording in Markdown or plain text")
    s.add_argument("files", nargs="+", help="Markdown or text files to read")
    common(s)
    s = sub.add_parser("prereg", help="git order of a preregistration and its result files")
    s.add_argument("prereg", help="the preregistration, a path inside this git checkout")
    s.add_argument("--result", action="append", required=True,
                   help="a result file the preregistration governs (repeatable)")
    common(s, results=False)
    s = sub.add_parser("cite", help="arXiv ids exist and recorded titles match arXiv")
    s.add_argument("files", nargs="+", help="files to read for arXiv ids; a .json file in papers.json form also "
                                            "gives recorded titles")
    s.add_argument("--offline", action="store_true", help="list the ids only; no network")
    common(s, results=False)
    common(sub.add_parser("selftest", help="run only the planted faults"), results=False, strict=False)


def _path(p):
    p = Path(p)
    return p if p.is_absolute() or p.exists() else ROOT / p


def _report(args, findings, extra, selftest_result):
    fails = [f for f in findings if f["severity"] == FAIL]
    warns = [f for f in findings if f["severity"] == WARN]
    code = EXIT_FINDING if fails or (getattr(args, "strict", False) and warns) else EXIT_OK
    if args.json:
        print(json.dumps({"selftest": selftest_result, "findings": findings, **extra,
                          "fail": len(fails), "warn": len(warns), "exit": code}, indent=1))
        return code
    print(f"selftest: {selftest_result['caught']} of {selftest_result['plants']} planted faults caught, "
          f"{selftest_result['clean_controls']} clean controls passed")
    for k, v in extra.items():
        print(f"{k}: {v}")
    for f in findings:
        print(f"{f['severity']} {f['rule']} {f['where']}: {f['message']}")
    print(f"{len(fails)} FAIL, {len(warns)} WARN" + (" (strict)" if getattr(args, "strict", False) else ""))
    return code


def run(args):
    try:
        st = selftest()
    except IntegrityError as e:
        print(f"selftest failed, no result reported: {e}", file=sys.stderr)
        return EXIT_BAD
    try:
        if args.action == "selftest":
            if args.json:
                print(json.dumps(st, indent=1))
            else:
                print(f"{st['caught']} of {st['plants']} planted faults caught as their own rule; "
                      f"{st['clean_controls']} clean controls passed; rules covered: {', '.join(st['rules'])}")
            return EXIT_OK
        if args.action == "rules":
            if args.json:
                print(json.dumps(RULES, indent=1))
            else:
                for r in RULES:
                    print(f"{r['id']} ({r['severity']}): {r['what']}. Fix: {r['fix']}. Source: {r['source']}")
            return EXIT_OK
        if args.action == "exposure":
            table = _load_results(_path(args.results)).get("held_out_by_reader", {})
            rows = [(g, f, s) for g, fam in table.items() if g != "about" for f, s in fam.items()]
            if args.json:
                print(json.dumps([{"group": g, "reader": f, "status": s} for g, f, s in rows], indent=1))
            else:
                for g, f, s in rows:
                    print(f"{g:<10} {f:<10} {s}")
                print("reasons and sources: results.json held_out")
            return EXIT_OK
        if args.action == "ink":
            results = _load_results(_path(args.results))
            out = []
            for c in args.claims:
                try:
                    data = json.loads(Path(c).read_text())
                except (OSError, ValueError) as e:
                    raise IntegrityError(f"{c}: {e}")
                out += check_ink(claim_from(data, args.reader, args.segment), results, c, Path.cwd())
            return _report(args, out, {"claims": len(args.claims)}, st)
        if args.action == "results":
            results = _load_results(_path(args.results))
            out, n = [], 0
            for where, claim in result_rows(results):
                n += 1
                out += check_ink(claim, results, where)
            return _report(args, out, {"rows": n}, st)
        if args.action == "text":
            results = _load_results(_path(args.results))
            out = []
            for f in args.files:
                try:
                    out += check_text(Path(f).read_text(), results, f)
                except OSError as e:
                    raise IntegrityError(f"{f}: {e}")
            return _report(args, out, {"files": len(args.files)}, st)
        if args.action == "prereg":
            root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
            out = check_prereg(root, args.prereg, args.result)
            return _report(args, out, {"results": len(args.result)}, st)
        if args.action == "cite":
            ids, recorded = [], {}
            for f in args.files:
                text = Path(f).read_text()
                if f.endswith(".json"):
                    try:
                        recorded.update(papers_titles(json.loads(text)))
                    except ValueError as e:
                        raise IntegrityError(f"{f}: {e}")
                ids += arxiv_ids(text)
            ids = sorted(set(ids) | set(recorded))
            if args.offline:
                return _report(args, [], {"arxiv_ids": len(ids), "searched": "no (offline)"}, st)
            try:
                titles = arxiv_titles(ids)
            except (urllib.error.URLError, OSError) as e:
                raise MissingData(f"arXiv export API blocked: {e}")
            return _report(args, check_citations(ids, recorded, titles),
                           {"arxiv_ids": len(ids), "opened": "export.arxiv.org API"}, st)
    except MissingData as e:
        print(f"cannot answer: {e}", file=sys.stderr)
        return EXIT_MISSING
    except IntegrityError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BAD
    return EXIT_BAD


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="python -m kit.integrity", description=__doc__.splitlines()[0])
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
