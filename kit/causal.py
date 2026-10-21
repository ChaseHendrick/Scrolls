"""Causal links across the repository: trace every result, claim and tool output back to what caused it, and
forward to what it changed (python -m kit causal).

Chase asked on 15 October 2026 for causal links between results and what produced them, and on 20 October 2026
(about 20:14 UTC) to "create more causal links in the repos". Inside one run a causal link already meant provenance
from an output to what caused it (AutoPipeline's graph.json, kit trainrecord); this module extends that to every
registry the repository keeps, deriving first and writing only what cannot be derived:

- It reads each carrier as it is: docs/results.json, docs/DECISIONS.md, the README's "Novel findings" with
  docs/causal/claims.json, preregistrations (docs/prereg/) and run specs (docs/compute/modal-specs/), committed
  provenance, run and runner-native records (RECORD_SHAPES), docs/evidence SHA256SUMS, tool pages,
  docs/releases.json, the Modal ledger's app ids, Modal runner scripts, and docs/HANDOFF.md (read only, as
  "mentioned in"). A fixed alias map turns fields they already have into links.
- New links use one grammar, the link line `REL REF [PIN]` (schema causal/1), stored once, at the effect end: a
  "causal" list in a JSON entry, a ```causal fence in a new spec, preregistration, log or tool page, the verbs
  Replaces, Lifts and Retires D<n> in DECISIONS.md, id tokens (r:, c:, D<n>, tool:) in live pages, and
  docs/causal/edges.jsonl (append-only, merge=union) when the effect end is frozen. Effects are never stored: they
  are the graph turned around.
- A requirement is met by a hash or typed edge, directly or through a chain of run, spec, prereg, approval and
  freeze edges (transitive satisfaction); hint edges (prose, regex) never meet one.
- `check` is a shrink-only ratchet: anything added after the cutover needs its required links, while the gaps
  that existed at the cutover sit in docs/causal/baseline.json, which may only shrink. Backfill runs in named,
  bounded passes, each recorded once in the baseline's pass ledger, so nobody loops over the same gaps.

A link records what produced or cited something; it never shows that a change caused a gain, which still needs a
matched null arm (kit trainrecord compare) or an AutoPipeline swap.

Exit codes follow kit stale: 0 ok, 1 failure, 2 usage, 3 attention, 75 skipped (every carrier absent).

Keep this file byte-identical in Scrolls and Scrolls-private, as kit/stale.py: a repository that has a module
named causal_ext (Scrolls-private does) gets its extra extractors, rules and commands through HOOKS, and one
that has none (Scrolls) runs without them. Standard library only, plus kit.stale, kit.provenance and kit.tooldocs.
"""

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from kit import stale

__all__ = ["CausalError", "Graph", "parse", "ref_kind", "unit_sha256", "results_units", "load", "resolve", "why",
           "effects", "show", "requirements", "gaps", "impact", "check", "link", "add_result", "add_claim",
           "backfill", "ratchet", "add_arguments", "run", "main"]

ROOT = Path(__file__).resolve().parent.parent
EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_ATTENTION, EXIT_SKIPPED = 0, 1, 2, 3, 75
SCHEMA = "causal/1"
CLAIMS_SCHEMA = "causal-claims/1"
BASELINE_SCHEMA = "causal-baseline/1"
RUNRECORD_SCHEMA = 1

RESULTS = "docs/results.json"
DECISIONS = "docs/DECISIONS.md"
README = "README.md"
CAUSAL_DIR = "docs/causal"
EDGES = "docs/causal/edges.jsonl"
CLAIMS = "docs/causal/claims.json"
BASELINE = "docs/causal/baseline.json"
RUNS_DIR = "docs/causal/runs"
PREREG_DIR = "docs/prereg"
SPEC_DIR = "docs/compute/modal-specs"
EVIDENCE_DIR = "docs/evidence"
LOGS_DIR = "docs/logs"
TOOLS_DIR = "docs/tools"
RELEASES = "docs/releases.json"
SCRIPTS_DIR = "scripts"
WORK = "work/causal"
REPO_TEST = "tests/test_repo.py"

# The grammar: 10 core relations, and 2 kept only by repositories that have approvals and freezes (Scrolls-private;
# a public check refuses them, rule E9).
RELS = ("decision", "prereg", "spec", "run", "code", "input", "control", "source", "supersedes", "corrects")
PRIVATE_RELS = ("approval", "freeze")
ALL_RELS = RELS + PRIVATE_RELS
REMOVED_RELS = {"model": "input", "record": "run", "evidence": "source", "qualifies": "corrects"}
SUPERSESSION = ("supersedes", "corrects")
NONE = {"run": ("community-report", "literature", "upstream-report", "metadata", "pending", "no-compute"),
        "prereg": ("plumbing", "development", "benchmark-reproduction", "community-report", "not-a-readout"),
        "control": ("not-a-score", "metadata", "pending", "community-report")}
# Edge classes: only hash and typed edges meet a requirement. `via` keeps where a derived edge came from.
CLASSES = ("hash", "typed", "hint")
STRONG = ("hash", "typed")
VIAS = ("field", "alias", "join", "recorded", "fence", "overlay", "token", "default", "regex")
# Transitive satisfaction: these requirements may be met through a chain of strong edges whose relations are all
# in CHAIN_RELS (a result reaching its run, the run's record, its approval, the approval's decision).
TRANSITIVE = ("decision", "approval", "spec", "prereg", "code", "control", "input")
CHAIN_RELS = ("run", "spec", "prereg", "approval", "freeze")
LABELS = ("Sourced fact", "Organizer result", "Community report", "Model output", "Measurement", "Null",
          "Interpretation", "Untested idea")
# Results sections that hold metadata, not measured units; they need no id.
META_SECTIONS = ("schema", "updated", "about", "held_out", "held_out_by_reader", "segments")
EXTERNAL_SECTIONS = ("community",)      # other people's results: run, prereg and control default to community-report
# Never written by this module or kit runrecord (E13); docs/causal/README.md says why.
FROZEN_PREFIXES = ("docs/prereg/", "docs/evidence/", "docs/logs/", "archive/", "scripts/experiments/")
FROZEN_FILES = ("docs/HANDOFF.md", "docs/contrib/villa-1865-m1pro-comment.md")
HASH_BUDGET = 256 << 20
GAP_KINDS = ("result", "finding", "claim", "spec", "prereg", "run", "release", "decision", "script", "evidence",
             "approval", "freeze")
RULES = tuple(f"E{i}" for i in range(1, 18)) + tuple(f"A{i}" for i in range(1, 11))
PASSES = ("ids", "decision-ids", "joins", "claims", "frozen")
# A Modal runner script (a new one needs a helper sign or an exemption header, rule E14).
RUNNER_SIGNS = ("modal.App(", "@app.local_entrypoint")
HELPER_SIGNS = ("from kit import runrecord", "runrecord.run(", "kit runrecord wrap", "kit run local",
                "provenance write --causal")
EXEMPT_REASONS = ("library", "plot", "test-helper", "no-output", "frozen-copy")
# Runner-native JSON records read as typed links (via recorded): a file name and the keys, any of which marks it.
RECORD_SHAPES = (("provenance.json", ("prereg", "head", "frozen_commit", "commit")),
                 ("run_provenance.json", ("prereg", "head", "commit", "token")),
                 ("run.json", ("script_sha256", "commit", "git_commit", "token", "app_id")),
                 ("driver.json", ("token", "commit", "git_commit")),
                 ("launch.json", ("token", "app", "app_id", "commit")),
                 ("report.json", ("commit", "git_commit", "token", "app_id")),
                 ("result.json", ("token", "rule_sha256", "spec", "commit")),
                 ("receipt.json", ("kit_commit", "token", "rule_sha256", "commit")))
OWN_COMMIT_KEYS = ("commit", "head", "git_commit", "kit_commit", "frozen_commit", "code_commit", "freezing_commit")

RE_NONE = re.compile(r"none:([a-z][a-z0-9-]*)")
RE_SHA = re.compile(r"sha256:([0-9a-f]{64})")
RE_FIELD = re.compile(r"field:([A-Za-z0-9_.\[\]-]+)")
RE_PRIVATE = re.compile(r"private:([0-9a-f]{64})")
RE_RESULT_ID = re.compile(r"[a-z0-9][a-z0-9_./-]*|pending@[0-9a-f]{8}")
RE_ID = re.compile(r"[a-z0-9][a-z0-9_./-]*")
RE_DECISION = re.compile(r"D([1-9][0-9]*)")
RE_PREFIXED = re.compile(r"(tool|release|approval|freeze|finding|script):([A-Za-z0-9][A-Za-z0-9_./-]*)")
RE_CLAIM = re.compile(r"c:([a-z0-9][a-z0-9_.-]*)")
RE_APP = re.compile(r"ap-[A-Za-z0-9]{20,}")
RE_TOKEN = re.compile(r"\d{8}T\d{6}Z(?:-[a-z0-9-]+)?")
RE_PR = re.compile(r"([A-Za-z0-9-]+)/([A-Za-z0-9_-]+)#([1-9][0-9]*)")
RE_REPO_COMMIT = re.compile(r"([A-Za-z][A-Za-z0-9_-]*)@([0-9a-f]{7,40})")
RE_COMMIT = re.compile(r"[0-9a-f]{7,40}")
RE_PATH = re.compile(r"([A-Za-z0-9_.][A-Za-z0-9_.+-]*(?:/[A-Za-z0-9_.+-]+)*/?)(?:#([A-Za-z0-9_.-]+))?"
                     r"(?:@([0-9a-f]{7,40}))?")
RE_URL_TEXT = re.compile(r"https://[^\s)\]>\"'`|]+")
RE_APP_TEXT = re.compile(r"(?<![A-Za-z0-9-])ap-[A-Za-z0-9]{20,}")
RE_TOKEN_TEXT = re.compile(r"(?<![0-9A-Za-z])\d{8}T\d{6}Z(?:-[a-z0-9-]*[a-z0-9])?")
RE_HEX_TEXT = re.compile(r"(?<![0-9A-Za-z])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![0-9A-Za-z])")
RE_COMMIT_WORD = re.compile(r"\bcommits?\s+`?([0-9a-f]{7,40})\b")
RE_FROZEN_AT = re.compile(r"\bfrozen at `?([0-9a-f]{7,40})\b", re.I)
RE_REF_TEXT = re.compile(r"(?<![\w:/])(r:[a-z0-9][a-z0-9_./@-]*[a-z0-9]|c:[a-z0-9][a-z0-9_.-]*[a-z0-9]|"
                         r"approval:[A-Za-z0-9][A-Za-z0-9_.-]*[A-Za-z0-9]|freeze:[A-Za-z0-9][A-Za-z0-9_.-]*[A-Za-z0-9]|"
                         r"tool:[a-z0-9][a-z0-9_.-]*[a-z0-9])")
RE_DECISION_TEXT = re.compile(r"(?<![\w/:])D([1-9][0-9]{0,3})(?![\w/])")
RE_SUPERSEDES = re.compile(r"\b(?:Replaces|Lifts|Retires)\s+D([1-9][0-9]*)\b")
RE_SUPERSEDED_WORD = re.compile(r"\b(?:replaced|lifted|retired|superseded)\b", re.I)
RE_MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
RE_INDEX_CITE = re.compile(r"(?<![\w])([a-z][a-z0-9_]*)\[(\d{1,3})\]")
RE_MEASURE = re.compile(r"\b(?:collected|measured|scored|AUC|verdict)\b")
RE_HISTORY = re.compile(r"^- (\d{4}-\d{2}-\d{2}): ")
RE_CONTROL_KEY = re.compile(r"(?:^|_)(?:reversed|reverse|controls?|nulls?|sham|permuted|shuffled)(?:_|$)")
# SCORE_KEYS: a unit holding one of these needs a control (hard rule 4).
RE_SCORE_KEY = re.compile(r"^(?:auc|row_score|pearson)|^max_abs_diff$|_agreement$|(?:^|_)verdict$")
RE_VERDICT_KEY = re.compile(r"(?:^|_)verdict$")
RE_DATE_ROW = re.compile(r"(\d{4}-\d{2}-\d{2})(?: [a-z]+)? row\b")
RE_SET_LITERAL = re.compile(r"HASH_PINNED_WITH_DASHES\s*=\s*\{([^}]*)\}", re.S)
RE_EXEMPT = re.compile(r"^#\s*causal:\s*exempt\b\s*(.*)$")

class CausalError(ValueError):
    """A link line, a reference or a request is malformed or refused; the CLI prints it and exits 1 (2 for usage)."""


def _now():
    return datetime.now(timezone.utc)


def _today():
    return _now().strftime("%Y-%m-%d")


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _read(root, rel):
    try:
        return (Path(root) / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------- the link line

def _is_local(ref):
    return (ref.startswith(("/", "~", "work/", "experiments/")) or "/scratchpad/" in ref)


def ref_kind(ref):
    """The kind of a reference, told apart by its shape: none, sha256, field, private, public, result, decision,
    claim (c:<id>), tool, release, approval, freeze, finding, script, app, token, url, pr, commit, local, path, or
    unknown."""
    if not isinstance(ref, str) or not ref or any(ch.isspace() for ch in ref):
        return "unknown"
    if ref.startswith("none:"):
        return "none" if RE_NONE.fullmatch(ref) else "unknown"
    if ref.startswith("sha256:"):
        return "sha256" if RE_SHA.fullmatch(ref) else "unknown"
    if ref.startswith("field:"):
        return "field" if RE_FIELD.fullmatch(ref) else "unknown"
    if ref.startswith("private:"):
        return "private" if RE_PRIVATE.fullmatch(ref) else "unknown"
    if ref.startswith("public:"):
        inner = ref_kind(ref[7:])
        return "public" if inner not in ("unknown", "public", "private", "local", "none") else "unknown"
    if ref.startswith("r:"):
        return "result" if RE_RESULT_ID.fullmatch(ref[2:]) else "unknown"
    if ref.startswith("c:"):
        return "claim" if RE_CLAIM.fullmatch(ref) else "unknown"
    m = RE_PREFIXED.fullmatch(ref)
    if m:
        return m.group(1)
    if RE_DECISION.fullmatch(ref):
        return "decision"
    if RE_APP.fullmatch(ref):
        return "app"
    if RE_TOKEN.fullmatch(ref):
        return "token"
    if ref.startswith("https://"):
        return "url" if len(ref) > len("https://") else "unknown"
    if RE_PR.fullmatch(ref):
        return "pr"
    if RE_REPO_COMMIT.fullmatch(ref) or RE_COMMIT.fullmatch(ref):
        return "commit"
    if _is_local(ref):
        return "local"
    m = RE_PATH.fullmatch(ref)
    if m and ("/" in m.group(1) or "." in m.group(1)) and ".." not in m.group(1).split("/"):
        return "path"
    return "unknown"


def _split_path(ref):
    """(path without anchor, trailing slash or @commit; anchor; commit) of a path reference."""
    m = RE_PATH.fullmatch(ref)
    if not m:
        return ref, None, None
    p = m.group(1)
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/"), m.group(2), m.group(3)


def parse(line):
    """One link line `REL REF [PIN]`, with an optional note after ` # `, as a dict {rel, ref, kind, pin, at,
    path, anchor, note}. Raises CausalError (rule E1) for anything else."""
    if not isinstance(line, str):
        raise CausalError("a link line must be a string")
    text, sep, note = line.partition(" # ")
    text = text.strip()
    parts = text.split(" ")
    if len(parts) not in (2, 3) or "" in parts:
        raise CausalError(f"not a link line (REL REF [PIN], single spaces): {line!r}")
    rel, ref = parts[0], parts[1]
    pin = parts[2] if len(parts) == 3 else None
    if rel in REMOVED_RELS:
        raise CausalError(f"relation {rel!r} was folded into {REMOVED_RELS[rel]!r} before the cutover; write "
                          f"{REMOVED_RELS[rel]} {ref}")
    if rel not in ALL_RELS:
        raise CausalError(f"unknown relation {rel!r} in {line!r}; one of {', '.join(ALL_RELS)}")
    kind = ref_kind(ref)
    if kind == "unknown":
        raise CausalError(f"unknown reference {ref!r} in {line!r}")
    if pin is not None and not RE_SHA.fullmatch(pin):
        raise CausalError(f"a pin is sha256:<64 hex>, not {pin!r}")
    if kind == "none":
        reason, allowed = ref[5:], NONE.get(rel)
        if allowed is None:
            raise CausalError(f"{rel} cannot be none: in {line!r}; only {', '.join(NONE)} can")
        if reason not in allowed:
            raise CausalError(f"none:{reason} is not a {rel} reason; one of {', '.join(allowed)}")
    out = {"rel": rel, "ref": ref, "kind": kind, "pin": pin[7:] if pin else None, "at": None, "path": None,
           "anchor": None, "note": note.strip() if sep else None}
    if kind == "path":
        out["path"], out["anchor"], out["at"] = _split_path(ref)
    elif kind == "commit":
        m = RE_REPO_COMMIT.fullmatch(ref)
        out["at"] = m.group(2) if m else ref
    return out


def _node_key(ref, kind=None):
    """The graph key a reference names: paths lose their anchor, trailing slash and @commit."""
    kind = kind or ref_kind(ref)
    if kind == "path":
        return _split_path(ref)[0]
    if kind == "commit":
        m = RE_REPO_COMMIT.fullmatch(ref)
        return ref if m else ref.lower()
    return ref


def _fits(rel, kind, path=None):
    """True when a relation may point to a reference of this kind (rule E6)."""
    p = path or ""
    if rel == "decision":
        return kind in ("decision", "public", "private")
    if rel in PRIVATE_RELS:
        return kind == rel
    if rel == "spec":
        return kind == "path" and p.startswith(SPEC_DIR + "/")
    if rel == "prereg":
        return kind in ("sha256", "none") or (kind == "path" and (p.startswith(PREREG_DIR + "/") or
                                                                   "prereg" in p.rsplit("/", 1)[-1]))
    if rel == "run":
        # a Modal app, a run token, a record (its digest or its path), a private digest or none:<reason>
        return kind in ("app", "token", "private", "none", "sha256", "path")
    if rel == "code":
        return kind in ("commit", "pr")
    if rel == "input":
        return kind in ("path", "url", "sha256")
    if rel == "control":
        return kind in ("result", "field", "sha256", "path", "token", "none")
    if rel == "source":
        return kind in ("path", "url", "result", "claim", "decision", "tool")
    if rel in SUPERSESSION:
        return kind in ("result", "claim", "decision", "path", "finding")
    return False


def unit_sha256(entry):
    """sha256 of a results unit's canonical JSON without `id` and `causal`: adding links never changes it, changing
    a number does."""
    if isinstance(entry, dict):
        body = {k: v for k, v in entry.items() if k not in ("id", "causal")}
    else:
        body = entry
    return _sha256_bytes(_canonical(body))


def _frozen(rel, extra=()):
    rel = rel.lstrip("./")
    return rel.startswith(FROZEN_PREFIXES) or rel in FROZEN_FILES or rel in extra


def _hash_pinned(root):
    """Paths in tests/test_repo.py's HASH_PINNED_WITH_DASHES set (empty when the file or set is absent)."""
    text = _read(root, REPO_TEST) or ""
    m = RE_SET_LITERAL.search(text)
    return set(re.findall(r"\"([^\"]+)\"", m.group(1))) if m else set()


def _frozen_set(root):
    extra = _hash_pinned(root)
    try:
        for f in stale.load_freezes(root) or []:
            extra.update((f.get("files") or {}).keys())
            if f.get("prereg"):
                extra.add(f["prereg"])
    except stale.StaleError:
        pass
    return extra


def _check_writable(root, rel):
    """Refuse to write a frozen path (rule E13)."""
    rel = Path(rel).as_posix()
    if Path(rel).is_absolute():
        try:
            rel = Path(rel).resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            return
    if _frozen(rel, _frozen_set(root)):
        raise CausalError(f"refusing to write {rel}: it is frozen (docs/prereg, docs/evidence, docs/logs, archive, "
                          "scripts/experiments, a hash-pinned or freeze-listed file, or docs/HANDOFF.md)")


def _write_text(root, rel, text):
    _check_writable(root, rel)
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def _json_text(data, original=None):
    """JSON text in the file's own layout: the indent and ASCII setting that reproduce `original` byte for byte
    (results.json is indent 1, non-ASCII kept); CausalError when no layout does."""
    if original is None:
        return json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    old = json.loads(original)
    for ind in (1, 2, 4):
        for asc in (False, True):
            if json.dumps(old, indent=ind, ensure_ascii=asc) + "\n" == original:
                return json.dumps(data, indent=ind, ensure_ascii=asc) + "\n"
    raise CausalError("cannot rewrite a JSON file whose layout json.dumps does not reproduce; edit it by hand")


# ---------------------------------------------------------------- the graph

class _Hooks:
    """Where a repository's causal_ext module plugs in: extractors (fn(graph)), requirements (fn(graph, reqs)),
    checks (fn(graph, report, options)), why (fn(graph, key, out)), arguments (fn(actions)), commands
    ({action: fn(args)}) and passes ({pass name: fn(graph, out, write, limit)}, run after the core part of that
    backfill pass)."""

    def __init__(self):
        self.extractors, self.requirements, self.checks, self.why, self.arguments = [], [], [], [], []
        self.commands, self.passes = {}, {}


HOOKS = _Hooks()


class Graph:
    """Nodes and edges read from every carrier. Each edge is a dict {effect, rel, cause, ref, kind, pin, at, cls,
    via, carrier, line, structured}: "the effect REL the cause". cls is hash, typed or hint; via says where a
    derived edge came from (VIAS)."""

    def __init__(self, root, public=None):
        self.root = Path(root)
        self.public = (not _has_ext()) if public is None else bool(public)
        self.git = stale.Git(root)
        self.nodes, self.edges, self.findings, self.carriers = {}, [], [], {}
        self.mentions, self.digests, self.aliases, self.ambiguous = {}, {}, {}, []
        self.baseline, self.runs, self.claims_data = None, [], None
        self.results_data, self.results_text = None, None
        self._in, self._out, self._commits, self._seen = {}, {}, {}, {}
        self._tracked = self._dirs = None
        self._prereg_versions = self._path_re = self._at = None
        self.ledger, self.history, self.decisions_explicit, self.public_root = None, [], False, None
        self.repo = _repo_slug(self.git)

    # nodes and edges
    def node(self, key, kind, own=False, **attrs):
        n = self.nodes.get(key)
        if n is None:
            n = self.nodes[key] = {"key": key, "kind": kind, "own": False}
        if own:
            n["own"] = True
            n["kind"] = kind
        for k, v in attrs.items():
            if v is not None and (own or k not in n):
                n[k] = v
        return n

    def edge(self, effect, rel, cause, via, carrier, line=None, pin=None, at=None, structured=False,
             note=None, external=False, cls=None):
        kind = ref_kind(cause)
        cls = cls or ("hint" if via == "regex" else "hash" if pin else "typed")
        sig = (effect, rel, cause, via, carrier, pin, at)
        if sig in self._seen and not structured:
            return self._seen[sig]
        e = {"effect": effect, "rel": rel, "cause": _node_key(cause, kind), "ref": cause, "kind": kind, "pin": pin,
             "at": at, "cls": cls, "via": via, "carrier": carrier, "line": line, "structured": structured}
        if note:
            e["note"] = note
        if external:
            e["external"] = True
        self._seen[sig] = e
        self.edges.append(e)
        self._in.setdefault(e["effect"], []).append(e)
        self._out.setdefault(e["cause"], []).append(e)
        if e["cause"] not in self.nodes:
            self.node(e["cause"], _ref_node_kind(cause, kind))
        if effect not in self.nodes:
            self.node(effect, _ref_node_kind(effect, ref_kind(effect)))
        return e

    def causes(self, key, strong=False):
        return [e for e in self._in.get(key, []) if not strong or e["cls"] in STRONG]

    def effects(self, key, strong=False):
        return [e for e in self._out.get(key, []) if not strong or e["cls"] in STRONG]

    def find(self, rule, where, text, level=None):
        level = level or ("error" if rule.startswith("E") else "attention" if rule.startswith("A") else "info")
        self.findings.append({"rule": rule, "level": level, "where": where, "text": text})

    def carrier(self, name, status, count=0, why=None):
        self.carriers[name] = {"status": status, "count": count, **({"why": why} if why else {})}

    # the files git tracks
    def tracked(self):
        if self._tracked is None:
            files = self.git.tracked() if self.git.ok else None
            if files is None:
                files = [p.relative_to(self.root).as_posix() for p in self.root.rglob("*")
                         if p.is_file() and ".git" not in p.relative_to(self.root).parts]
            self._tracked = set(files)
            self._dirs = set()
            for rel in files:
                parts = rel.split("/")
                self._dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
        return self._tracked

    def is_tracked(self, rel):
        self.tracked()
        return rel in self._tracked or rel in self._dirs

    def is_dir(self, rel):
        self.tracked()
        return rel in self._dirs

    def tops(self):
        self.tracked()
        return sorted({p.split("/")[0] for p in self._dirs if "/" not in p})

    # commits and PRs
    def commit_state(self, ref):
        """ok, unverified (a shallow clone or a deleted branch may lack it), missing, ambiguous or external."""
        m = RE_REPO_COMMIT.fullmatch(ref)
        if m:
            if m.group(1) not in (self.repo or "").split("/")[-1:]:
                return "external"
            ref = m.group(2)
        if ref not in self._commits:
            self._resolve_commits([ref])
        return self._commits.get(ref, "unverified")

    def _resolve_commits(self, refs):
        refs = [r for r in dict.fromkeys(refs) if r not in self._commits]
        if not refs:
            return
        if not self.git.ok:
            self._commits.update({r: "unverified" for r in refs})
            return
        try:
            out = subprocess.run(["git", "-C", str(self.root), "cat-file", "--batch-check"],
                                 input="".join(f"{r}^{{commit}}\n" for r in refs), capture_output=True, text=True,
                                 timeout=120).stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired):
            out = []
        shallow = self.git.shallow()
        for r, line in zip(refs, out + [""] * (len(refs) - len(out))):
            if line.endswith(" commit") or " commit " in line:
                self._commits[r] = "ok"
            elif "ambiguous" in line:
                self._commits[r] = "ambiguous"
            else:
                self._commits[r] = "unverified" if shallow else "missing"


def _has_ext():
    try:
        return importlib.util.find_spec("kit.causal_ext") is not None
    except (ImportError, ValueError):
        return False


def _repo_slug(git):
    url = (git.run("remote", "get-url", "origin") or "").strip() if git.ok else ""
    m = re.search(r"github\.com[/:]([^/]+)/([^/\s]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _path_kind(path):
    if path.startswith(PREREG_DIR + "/"):
        return "prereg"
    if path.startswith(SPEC_DIR + "/"):
        return "spec"
    if path.startswith("docs/evidence/"):
        return "evidence"
    if path.startswith("docs/logs/"):
        return "log"
    return "file"


def _ref_node_kind(ref, kind):
    if kind == "path":
        return _path_kind(_split_path(ref)[0])
    return {"app": "run", "token": "run", "sha256": "digest", "result": "result", "pr": "pr", "claim": "claim"}.get(
        kind, kind)


def _flat_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _flat_strings(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _flat_strings(v)


def _path_regex(g):
    if g._path_re is not None:
        return g._path_re
    tops = [re.escape(t) for t in g.tops() if t not in (".git",)] or ["docs"]
    g._path_re = re.compile(r"(?<![\w/.@-])((?:%s)/[A-Za-z0-9_.@+/-]*[A-Za-z0-9_/]|README\.md|AGENTS\.md|GLOSSARY\.md)"
                      r"(?:#([A-Za-z0-9_.-]+))?" % "|".join(tops))
    return g._path_re


def _paths_in(g, text):
    """[(path ref, exact)] of repository paths and https URLs in a string; exact when the string is only that."""
    out = []
    stripped = text.strip()
    for m in RE_URL_TEXT.finditer(text):
        url = m.group(0).rstrip(".,;:")
        out.append((url, url == stripped))
    clean = RE_URL_TEXT.sub(" ", text)
    for m in _path_regex(g).finditer(clean):
        ref = m.group(0).rstrip(".,;:")
        out.append((ref, ref == stripped or ref.rstrip("/") == stripped.rstrip("/")))
    return out


def _runs_in(text):
    out = [m.group(0) for m in RE_APP_TEXT.finditer(text)]
    out += [m.group(0) for m in RE_TOKEN_TEXT.finditer(text)]
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- loading: baseline and key assignment

def _load_baseline(g):
    text = _read(g.root, BASELINE)
    if text is None:
        return
    try:
        data = json.loads(text)
    except ValueError as exc:
        g.find("E11", BASELINE, f"not JSON: {exc}")
        return
    if not isinstance(data, dict) or data.get("schema") != BASELINE_SCHEMA:
        g.find("E11", BASELINE, f'needs "schema": "{BASELINE_SCHEMA}"')
        return
    for key in ("gaps", "initial", "legacy"):
        if not isinstance(data.get(key, {}), dict):
            g.find("E11", BASELINE, f"{key} must be an object")
            return
    g.baseline = data


def _initial_keys(g):
    b = g.baseline or {}
    init = b.get("initial") or {}
    return set(init.get("gaps", {})) | set(init.get("legacy", {}))


def _assign(items, legacy, taken, prefix):
    """Give each item without an explicit id its key: the legacy key whose fingerprint it has, else its
    positional key when that key is a legacy one, else a new key. Sets key, old and matched."""
    by_fp = {}
    for k, fp in sorted(legacy.items()):
        if k.startswith(prefix):
            by_fp.setdefault(fp if isinstance(fp, str) else (fp or [None])[0], []).append(k)
    used = set(taken)
    for it in items:
        for k in by_fp.get(it["fp"], []):
            if k not in used:
                it.update(key=k, old=True, matched="fingerprint")
                used.add(k)
                break
    for it in items:
        if "key" not in it and it["pos_key"] in legacy and it["pos_key"] not in used:
            it.update(key=it["pos_key"], old=True, matched="position")
            used.add(it["pos_key"])
    for it in items:
        if "key" not in it:
            k, n = it["pos_key"], 1
            while k in used:
                n += 1
                k = f"{it['pos_key']}~new{n if n > 2 else ''}"
            it.update(key=k, old=False, matched=None)
            used.add(k)


# ---------------------------------------------------------------- extractor: docs/results.json

def results_units(data):
    """[(section, index or None, entry)] for every unit of a results file: dict sections and the object rows of
    list sections, leaving out the metadata sections; pending strings come back with their index too."""
    out = []
    for section, value in data.items():
        if section in META_SECTIONS:
            continue
        if isinstance(value, dict):
            out.append((section, None, value))
        elif isinstance(value, list):
            for i, row in enumerate(value):
                if isinstance(row, (dict, str)):
                    out.append((section, i, row))
    return out


def _results_lines(text):
    """{(section, index or None): line number} for an indent-1 results file; empty for any other layout."""
    out, section, row = {}, None, -1
    for n, line in enumerate(text.splitlines(), 1):
        m = re.match(r'^ "([^"]+)": (.)', line)
        if m:
            section, row = m.group(1), -1
            out[(section, None)] = n
            continue
        if section and (line == "  {" or re.match(r'^  "', line)):
            row += 1
            out[(section, row)] = n
    return out


def _control_required(section, entry):
    """True when a unit holds a SCORE_KEY (auc*, row_score*, pearson*, max_abs_diff, *_agreement with a number, or a
    verdict) or is a device check: it needs a control (hard rule 4)."""
    if section == "device_checks":
        return True
    for k, v in entry.items():
        if RE_VERDICT_KEY.search(k) and v not in (None, "", []):
            return True
        if RE_SCORE_KEY.search(k) and _numeric(v):
            return True
    return False


def _numeric(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, (list, dict)):
        return any(_numeric(x) for x in (v.values() if isinstance(v, dict) else v))
    return False


def _ex_results(g):
    text = _read(g.root, RESULTS)
    if text is None:
        g.carrier("results", "skipped", why=f"no {RESULTS}")
        return
    try:
        data = json.loads(text)
    except ValueError as exc:
        g.find("E2", RESULTS, f"not JSON: {exc}")
        g.carrier("results", "failed", why="not JSON")
        return
    g.results_data, g.results_text = data, text
    lines = _results_lines(text)
    legacy = (g.baseline or {}).get("legacy", {})
    initial = _initial_keys(g)
    explicit, items, pending = {}, [], 0
    for section, index, entry in results_units(data):
        if isinstance(entry, str):
            if section == "pending":
                key = f"r:pending@{_sha256_bytes(entry.encode('utf-8'))[:8]}"
                g.node(key, "pending", own=True, carrier=RESULTS, where=f"{section}[{index}]", section=section,
                       index=index, text=entry[:200], line=lines.get((section, index)))
                pending += 1
            continue
        item = {"section": section, "index": index, "entry": entry, "fp": unit_sha256(entry),
                "line": lines.get((section, index))}
        if index is None:
            item.update(key=f"r:{section}", old=(f"r:{section}" in initial or g.baseline is None), matched="key")
        elif "id" in entry:
            rid = entry["id"]
            if not isinstance(rid, str) or not RE_ID.fullmatch(rid):
                g.find("E2", f"{RESULTS} {section}[{index}]", f"id {rid!r} must match [a-z0-9][a-z0-9_./-]*")
                rid = f"{section}/{index}"
            item.update(key=f"r:{rid}", matched="id")
            item["old"] = (item["key"] in initial or any(fp == item["fp"] for fp in legacy.values())
                           or g.baseline is None)
        else:
            item["pos_key"] = f"r:{section}/{index}"
        if "key" in item:
            if item["key"] in explicit:
                g.find("E2", f"{RESULTS} {item['key']}", f"id {item['key'][2:]} is not unique")
            explicit[item["key"]] = item
        items.append(item)
    _assign([it for it in items if "pos_key" in it], legacy, set(explicit), "r:")
    for it in items:
        if "pos_key" in it and g.baseline is None:
            it["old"] = True
        _add_unit(g, it)
    g.carrier("results", "ok", count=len(items), why=f"{pending} pending strings")


def _add_unit(g, it):
    section, index, entry, key = it["section"], it["index"], it["entry"], it["key"]
    where = section if index is None else f"{section}[{index}]"
    verdict = next((entry[k] for k in entry if RE_VERDICT_KEY.search(k) and entry[k] not in (None, "", [])), None)
    g.node(key, "result", own=True, carrier=RESULTS, where=where, section=section, index=index,
           line=it.get("line"), unit_sha256=it["fp"], explicit_id="id" in entry or index is None,
           old=it["old"], matched=it["matched"], verdict=verdict is not None,
           control_required=_control_required(section, entry), entry=entry)
    carrier = f"{RESULTS} {where}"
    _alias_result(g, key, section, entry, carrier, it.get("line"))
    lines = entry.get("causal")
    if lines is not None and not isinstance(lines, list):
        g.find("E1", carrier, "causal must be a list of link lines")
        return
    written = set()
    for i, line in enumerate(lines or []):
        e = _structured(g, key, line, "field", f"{carrier} causal[{i}]", it.get("line"))
        if e is not None:
            written.add(e["rel"])
            if (e["kind"] == "none" and e["ref"] == "none:community-report" and e["rel"] == "control"
                    and section not in EXTERNAL_SECTIONS):
                g.find("E1", f"{carrier} causal[{i}]", "control none:community-report is only for the "
                                                       f"{', '.join(EXTERNAL_SECTIONS)} section(s)")
    if section in EXTERNAL_SECTIONS:
        # other people's results: derived in code, never written
        for rel in ("run", "prereg", "control"):
            if rel not in written:
                g.edge(key, rel, "none:community-report", "default", carrier, line=it.get("line"))


def _structured(g, effect, line, via, carrier, lineno=None):
    try:
        p = parse(line)
    except CausalError as exc:
        g.find("E1", carrier, str(exc))
        return None
    e = g.edge(effect, p["rel"], p["ref"], via, carrier, line=lineno, pin=p["pin"], at=p["at"],
               structured=True, note=p["note"])
    e["parsed"] = p
    return e


def _alias_result(g, key, section, entry, carrier, line):
    """Edges from the fields a results entry already has (the legacy alias map, via alias)."""
    edge = lambda rel, ref, via="alias", **kw: g.edge(key, rel, ref, via, carrier, line=line, **kw)  # noqa: E731
    for k, v in entry.items():
        if k in ("id", "causal"):
            continue
        if k in ("source", "log", "measured_by_log", "evidence", "records", "prereg", "amendment", "spec"):
            rel = {"log": "source", "measured_by_log": "source", "evidence": "source", "records": "run",
                   "amendment": "prereg"}.get(k, k)
            found = []
            for s in _flat_strings(v):
                for ref, exact in _paths_in(g, s):
                    found.append(ref)
                    pin = None
                    if k == "evidence" and isinstance(v, str) and exact:
                        pin = entry.get("evidence_sha256") if isinstance(entry.get("evidence_sha256"), str) else None
                    at = None
                    if rel == "prereg":
                        m = RE_FROZEN_AT.search(s)
                        at = m.group(1) if m else None
                    kind = ref_kind(ref)
                    if rel == "run" and kind not in ("path", "sha256"):
                        continue
                    e = edge(rel, ref, pin=pin, at=at, cls="hash" if pin else None)
                    if rel == "source" and exact and kind == "path":
                        # a source that is a preregistration or a run spec is also that link
                        sp = _split_path(ref)[0]
                        if sp.startswith(PREREG_DIR + "/"):
                            edge("prereg", ref)
                        elif sp.startswith(SPEC_DIR + "/"):
                            edge("spec", ref)
                    if not exact and k in ("prereg", "evidence"):
                        e["prose"] = True
                    if kind == "local" and rel == "source":
                        g.find("A1", carrier, f"{k} {ref} is only in a local folder (work/ or experiments/); commit "
                                              "small evidence or link a tracked copy")
            if not found and k in ("prereg", "evidence", "spec") and any(_flat_strings(v)):
                g.find("A1", carrier, f"{k} is prose with no repository path or URL: {str(v)[:80]!r}")
            elif found and k in ("prereg", "evidence") and not (isinstance(v, str) and any(
                    v.strip().rstrip("/") == f.rstrip("/") for f in found)):
                g.find("A1", carrier, f"{k} is prose, not a bare path; a causal line can pin it")
        elif k == "rule_sha256" and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v):
            edge("prereg", f"sha256:{v}", note="rule_sha256")
        elif k == "checkpoint_sha256" and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v):
            edge("input", f"sha256:{v}", note=k)
        elif k == "model" and isinstance(v, str) and ref_kind(v.strip()) in ("url", "path"):
            edge("input", v.strip(), note=k)
        elif k in ("token", "app", "app_id", "run"):
            if isinstance(v, dict):
                for kk, vv in v.items():
                    if not isinstance(vv, str):
                        continue
                    if kk in ("app", "app_id", "token") and ref_kind(vv) in ("app", "token"):
                        edge("run", vv)
                    elif kk.endswith("commit") and RE_COMMIT.fullmatch(vv):
                        edge("code", vv)
            else:
                for s in _flat_strings(v):
                    for ref in _runs_in(s):
                        edge("run", ref)
                    for m in RE_HEX_TEXT.finditer(RE_TOKEN_TEXT.sub(" ", RE_APP_TEXT.sub(" ", s))):
                        edge("code", m.group(0))
        elif k.endswith("_commit") and isinstance(v, str) and RE_COMMIT.fullmatch(v):
            external = section in EXTERNAL_SECTIONS or k.startswith("villa")
            edge("code", v, external=external)
        elif RE_CONTROL_KEY.search(k):
            edge("control", f"field:{k}")
        elif k == "measured_by":
            for s in _flat_strings(v):
                for ref in _runs_in(s):
                    edge("run", ref, "regex")
        elif isinstance(v, str) and ref_kind(v.strip()) == "path" and _split_path(v.strip())[0].startswith(
                (EVIDENCE_DIR + "/", LOGS_DIR + "/")) and g.is_tracked(_split_path(v.strip())[0]):
            edge("source", v.strip(), note=k)       # an exact evidence or log path under any other key


# ---------------------------------------------------------------- extractor: docs/DECISIONS.md

def _decision_rows(text):
    """(explicit, [(line, id or None, date, text)]) of the first decisions table, `| Date | Decision |` or
    `| Id | Date | Decision |`."""
    lines = text.splitlines()
    rows, explicit, header = [], False, None
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("|") else None
        if header is None:
            if cells and [c.lower() for c in cells[:3]] in (["date", "decision"], ["id", "date", "decision"]):
                header, explicit = i, cells[0].lower() == "id"
            continue
        if i == header + 1:
            continue
        if not line.startswith("|"):
            break
        if explicit:
            rows.append((i + 1, cells[0], cells[1], " | ".join(cells[2:])))
        else:
            rows.append((i + 1, None, cells[0], " | ".join(cells[1:])))
    return explicit, rows


def _ex_decisions(g):
    text = _read(g.root, DECISIONS)
    if text is None:
        g.carrier("decisions", "skipped", why=f"no {DECISIONS}")
        return
    explicit, rows = _decision_rows(text)
    g.decisions_explicit = explicit
    seen = set()
    for n, (line, did, date, body) in enumerate(rows, 1):
        key = did if explicit else f"D{n}"
        where = f"{DECISIONS}:{line}"
        if explicit:
            if not RE_DECISION.fullmatch(did or ""):
                g.find("E2", where, f"Id {did!r} must be D<n>")
                continue
            if did in seen:
                g.find("E2", where, f"Id {did} is not unique")
            seen.add(did)
        g.node(key, "decision", own=True, carrier=DECISIONS, line=line, date=date.split(" ")[0], text=body[:240],
               explicit_id=explicit, needs_superseded_by=bool(RE_SUPERSEDED_WORD.search(body)))
        for m in RE_SUPERSEDES.finditer(body):
            g.edge(key, "supersedes", f"D{m.group(1)}", "field", where, line=line)
        for target in RE_MD_LINK.findall(body):
            if not target.startswith(("#", "http://")):
                ref = target if target.startswith("https://") else _rel_link(DECISIONS, target)
                if ref and ref_kind(ref) in ("path", "url"):
                    g.edge(key, "source", ref, "regex", where, line=line)
    g.carrier("decisions", "ok", count=len(rows), why="Id column" if explicit else "provisional D<n> by row order")


def _rel_link(page, target):
    path = target.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return None
    base = Path(page).parent
    parts = []
    for part in (base / path).as_posix().split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts) or None


# ---------------------------------------------------------------- extractor: docs/causal/

def edge_sha8(rec):
    """The first 8 hex of the sha256 of an edges.jsonl edge object's canonical JSON: what a retraction names, so a
    union merge that reorders lines cannot retract the wrong edge."""
    return _sha256_bytes(_canonical(rec))[:8]


def _ex_causal_dir(g):
    root = g.root
    count = 0
    text = _read(root, EDGES)
    if text is not None:
        records, retracted = [], set()
        for n, raw in enumerate(text.splitlines(), 1):
            if not raw.strip():
                continue
            where = f"{EDGES}:{n}"
            try:
                rec = json.loads(raw)
            except ValueError as exc:
                g.find("E1", where, f"not JSON: {exc}")
                continue
            if not isinstance(rec, dict):
                g.find("E1", where, "each line must be a JSON object")
                continue
            records.append((n, where, rec))
            if "retract" in rec:
                if not (isinstance(rec.get("retract"), str) and re.fullmatch(r"[0-9a-f]{8}", rec["retract"])
                        and rec.get("reason")):
                    g.find("E1", where, 'a retraction needs "retract": <sha8 of the edge object> and "reason"')
                retracted.add(rec.get("retract"))
        for n, where, rec in records:
            if "retract" in rec or "repin" in rec or edge_sha8(rec) in retracted:
                continue
            if "alias" in rec:
                if not (isinstance(rec.get("alias"), str) and isinstance(rec.get("to"), str) and rec.get("basis")):
                    g.find("E1", where, 'an alias needs "alias", "to" and "basis"')
                    continue
                g.aliases[rec["alias"]] = rec["to"]
                continue
            if not (isinstance(rec.get("effect"), str) and isinstance(rec.get("line"), str) and rec.get("basis")
                    and rec.get("added")):
                g.find("E1", where, 'an edge needs "effect", "line", "basis" and "added"')
                continue
            effect = rec["effect"]
            ek = ref_kind(effect)
            if ek == "unknown":
                g.find("E1", where, f"unknown effect {effect!r}")
                continue
            e = _structured(g, _node_key(effect, ek), rec["line"], "overlay", where, n)
            if e is not None:
                e["basis"] = rec["basis"]
                e["sha8"] = edge_sha8(rec)
                count += 1
    text = _read(root, CLAIMS)
    if text is not None:
        try:
            data = json.loads(text)
        except ValueError as exc:
            data = None
            g.find("E2", CLAIMS, f"not JSON: {exc}")
        if data is not None:
            if not isinstance(data, dict) or data.get("schema") != CLAIMS_SCHEMA or not isinstance(
                    data.get("claims"), list):
                g.find("E2", CLAIMS, f'needs "schema": "{CLAIMS_SCHEMA}" and a list under "claims"')
            else:
                g.claims_data = data
                seen = set()
                for i, c in enumerate(data["claims"]):
                    where = f"{CLAIMS} claims[{i}]"
                    cid = c.get("id") if isinstance(c, dict) else None
                    if not isinstance(cid, str) or not RE_CLAIM.fullmatch(f"c:{cid}"):
                        g.find("E2", where, "a claim needs an id of lowercase letters, digits, '.', '_' or '-'")
                        continue
                    if cid in seen:
                        g.find("E2", where, f"claim id {cid} is not unique")
                    seen.add(cid)
                    key = f"c:{cid}"
                    g.node(key, "claim", own=True, carrier=CLAIMS, where=where, readme_item=c.get("readme_item"),
                           quote=c.get("quote"), label=c.get("label"))
                    for j, line in enumerate(c.get("causal") or []):
                        _structured(g, key, line, "field", f"{where} causal[{j}]")
    runs = Path(root) / RUNS_DIR
    if runs.is_dir():
        for path in sorted(runs.glob("*.json")):
            _ex_runrecord(g, path, adopted=True)
    g.carrier("causal-dir", "ok" if (Path(root) / CAUSAL_DIR).is_dir() else "skipped", count=count,
              why=None if (Path(root) / CAUSAL_DIR).is_dir() else f"no {CAUSAL_DIR}/ yet")


def _verify_digest(record):
    body = {k: v for k, v in record.items() if k != "digest"}
    return _sha256_bytes(_canonical(body)) == record.get("digest")


def _ex_runrecord(g, path, adopted=False):
    rel = path.relative_to(g.root).as_posix() if path.is_absolute() and g.root in path.parents else str(path)
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        g.find("E12", rel, f"unreadable run record: {exc}")
        return None
    if not isinstance(rec, dict) or not isinstance(rec.get("digest"), str):
        g.find("E12", rel, "a run record needs a digest")
        return None
    if not _verify_digest(rec):
        g.find("E12", rel, "digest does not match the record")
    if adopted:
        if rec.get("runrecord_schema") != RUNRECORD_SCHEMA:
            g.find("E12", rel, f"runrecord_schema {rec.get('runrecord_schema')!r}; this check reads "
                               f"{RUNRECORD_SCHEMA}")
        if rec.get("token") != path.stem:
            g.find("E12", rel, f"token {rec.get('token')!r} is not the file name {path.stem}")
        if g.public and rec.get("public") is not True:
            g.find("E12", rel, "a public repository holds only records with public true")
    key = _add_record(g, rec, rel, adopted=adopted)
    return key


def _add_record(g, rec, rel, adopted=False):
    """A provenance, run or training record as a node sha256:<digest>, with its code, inputs, outputs and causal
    lines as edges (hash class: the digest covers them)."""
    key = f"sha256:{rec['digest']}"
    kind = rec.get("kind") or ("run" if "runrecord_schema" in rec else
                               "training" if "trainrecord_schema" in rec else "provenance")
    g.node(key, "record", own=True, carrier=rel, path=rel, record_kind=kind, token=rec.get("token"),
           public=rec.get("public"), clean=_clean(rec), adopted=adopted, parent=rec.get("parent"),
           has_prereg=any(str(x).startswith("prereg ") for x in rec.get("causal") or []),
           has_causal=bool(rec.get("causal")), runrecord="runrecord_schema" in rec,
           old=(not adopted) or key in _initial_keys(g) or g.baseline is None)
    g.digests[rec["digest"]] = rel
    g.node(rel, _path_kind(rel), record=key)
    g.edge(rel, "run", key, "recorded", rel, cls="hash")
    if rec.get("token") and ref_kind(rec["token"]) == "token":
        g.node(rec["token"], "run", own=True, carrier=rel, record=key)
        g.edge(rec["token"], "run", key, "recorded", rel, cls="hash")
    for c in rec.get("code") or []:
        if isinstance(c, dict) and isinstance(c.get("commit"), str) and RE_COMMIT.fullmatch(c["commit"]):
            repo = str(c.get("repo") or "")
            external = bool(repo) and repo.rstrip("/").split("/")[-1] not in (
                "", (g.repo or "").split("/")[-1], "repo", "Scrolls", "Scrolls-private", "workspace")
            g.edge(key, "code", c["commit"], "recorded", rel, external=external, cls="hash")
    for section in ("models", "inputs"):
        for item in rec.get(section) or []:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                ref = item["path"]
                if ref_kind(ref) in ("path", "local", "url"):
                    e = g.edge(key, "input", ref, "recorded", rel, pin=item.get("sha256"))
                    e["recheck"] = item.get("kind") == "file"
    for item in rec.get("outputs") or []:
        if isinstance(item, dict) and isinstance(item.get("path"), str) and ref_kind(item["path"]) in (
                "path", "local"):
            g.edge(_node_key(item["path"]), "run", key, "recorded", rel, pin=item.get("sha256"))
    for i, line in enumerate(rec.get("causal") or []):
        e = _structured(g, key, line, "recorded", f"{rel} causal[{i}]")
        if e is not None:
            e["cls"] = "hash"
    return key


def _clean(rec):
    code = rec.get("code") or []
    first = code[0] if code and isinstance(code[0], dict) else {}
    return first.get("uncommitted_changes") is False


# ---------------------------------------------------------------- extractor: README claims

def _readme_items(text):
    """[(line, ordinal, text)] of the list items under the README's "## Novel findings" heading."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## Novel findings")
    except StopIteration:
        return None
    items = []
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith("## "):
            break
        if re.match(r"^(?:- |\d+\. )\S", line):
            items.append([i + 1, len(items) + 1, line])
        elif items and line.startswith("   ") and line.strip() and items[-1][0] + 1 == i:
            items[-1][2] += "\n" + line
    return [tuple(x) for x in items]


def _ex_readme(g):
    text = _read(g.root, README)
    items = _readme_items(text) if text is not None else None
    if items is None:
        g.carrier("readme", "skipped", why=f"no Novel findings section in {README}")
        return
    by_ordinal = {o: (ln, t) for ln, o, t in items}
    claimed = {}
    for key, n in list(g.nodes.items()):
        if n["kind"] != "claim" or not n.get("own"):
            continue
        quote, item = n.get("quote"), n.get("readme_item")
        scope = by_ordinal.get(item, (None, ""))[1] if isinstance(item, int) else text
        hits = scope.count(quote) if isinstance(quote, str) and quote else 0
        n["quote_hits"] = hits
        if hits == 1:
            if isinstance(item, int) and item in by_ordinal:
                claimed[item] = key
                n["line"] = by_ordinal[item][0]
            elif not isinstance(item, int):
                line = text.count("\n", 0, text.index(quote)) + 1
                n["line"] = line
                for ln, o, t in items:
                    if ln <= line <= ln + t.count("\n"):
                        claimed[o] = key
        for ref in RE_REF_TEXT.findall(by_ordinal.get(item, (None, ""))[1] if isinstance(item, int) else ""):
            if ref.startswith("r:"):
                g.edge(key, "source", ref, "token", README)
    legacy = (g.baseline or {}).get("legacy", {})
    pending = [{"pos_key": f"finding:{o}", "fp": _sha256_bytes(t.strip().encode("utf-8")), "line": ln,
                "ordinal": o, "text": t} for ln, o, t in items if o not in claimed]
    _assign(pending, legacy, set(), "finding:")
    for it in pending:
        g.node(it["key"], "finding", own=True, carrier=README, line=it["line"], ordinal=it["ordinal"],
               text=it["text"][:240], fingerprint=it["fp"], old=it["old"] or g.baseline is None,
               matched=it["matched"])
    g.carrier("readme", "ok", count=len(items), why=f"{len(claimed)} with a claim")


# ---------------------------------------------------------------- extractor: preregistrations and specs

def _fences(text):
    """[(line, link line)] inside ```causal fences."""
    out, inside = [], False
    for n, line in enumerate(text.splitlines(), 1):
        if not inside and re.match(r"^```causal\s*$", line):
            inside = True
            continue
        if inside and line.startswith("```"):
            inside = False
            continue
        if inside and line.strip() and not line.lstrip().startswith("#"):
            out.append((n, line.strip()))
    return out


def _ex_files(g):
    count = {"prereg": 0, "spec": 0}
    for rel in sorted(g.tracked()):
        if rel.startswith(PREREG_DIR + "/") and rel.endswith((".md", ".json")):
            kind = "prereg"
        elif rel.startswith(SPEC_DIR + "/") and rel.endswith(".md") and not rel.endswith("/README.md"):
            kind = "spec"
        else:
            continue
        count[kind] += 1
        g.node(rel, kind, own=True, carrier=rel)
        text = _read(g.root, rel)
        if text is None or not rel.endswith(".md"):
            continue
        for n, line in _fences(text):
            _structured(g, rel, line, "fence", f"{rel}:{n}", n)
        for target in RE_MD_LINK.findall(stale.FENCE.sub("", text)):
            if target.startswith("#"):
                continue
            ref = target if target.startswith("https://") else _rel_link(rel, target)
            if ref and ref_kind(ref) in ("path", "url") and ref != rel:
                g.edge(rel, "source", ref, "regex", rel)
    g.carrier("prereg", "ok" if count["prereg"] else "skipped", count=count["prereg"],
              why=None if count["prereg"] else f"no {PREREG_DIR}/")
    g.carrier("spec", "ok" if count["spec"] else "skipped", count=count["spec"],
              why=None if count["spec"] else f"no {SPEC_DIR}/")


# ---------------------------------------------------------------- extractor: committed records

def _shape(name, rec):
    """True when a JSON file matches RECORD_SHAPES: a known runner file name holding one of its marking keys."""
    for fname, keys in RECORD_SHAPES:
        if name == fname and any(k in rec for k in keys):
            return True
    return False


def _ex_records(g):
    """Committed records, read after they verify: provenance, run and training records (hash class) and
    runner-native files that match RECORD_SHAPES (typed, via recorded)."""
    n_prov = n_other = 0
    for rel in sorted(g.tracked()):
        name = rel.rsplit("/", 1)[-1]
        if not name.endswith(".json") or rel.startswith(RUNS_DIR + "/"):
            continue
        native = name in {f for f, _ in RECORD_SHAPES}
        if not (native or "provenance" in name or name.endswith((".trainrecord.json", ".runrecord.json"))):
            continue
        try:
            rec = json.loads((g.root / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        if isinstance(rec.get("digest"), str) and (isinstance(rec.get("code"), list) or "runrecord_schema" in rec
                                                   or "trainrecord_schema" in rec):
            if not _verify_digest(rec):
                g.find("E5", rel, "record digest does not match the record")
            _add_record(g, rec, rel)
            n_prov += 1
            continue
        if not (_shape(name, rec) or "provenance" in name):
            continue
        added = False
        for k, v in rec.items():
            if not isinstance(v, str):
                continue
            v = v.strip()
            if k == "prereg" and ref_kind(v) == "path":
                pin = rec.get("prereg_sha256") if isinstance(rec.get("prereg_sha256"), str) else None
                at = rec.get("frozen_commit") if isinstance(rec.get("frozen_commit"), str) and RE_COMMIT.fullmatch(
                    rec["frozen_commit"]) else None
                g.edge(rel, "prereg", v, "recorded", rel, pin=pin, at=at)
                added = True
            elif k == "rule_sha256" and re.fullmatch(r"[0-9a-f]{64}", v):
                g.edge(rel, "prereg", f"sha256:{v}", "recorded", rel, note="rule_sha256")
                added = True
            elif (k.endswith("_commit") or k in OWN_COMMIT_KEYS) and RE_COMMIT.fullmatch(v):
                g.edge(rel, "code", v, "recorded", rel, external=k not in OWN_COMMIT_KEYS)
                added = True
            elif k == "spec" and ref_kind(v) == "path":
                g.edge(rel, "spec", v, "recorded", rel)
                added = True
            elif k in ("token", "run_token", "app", "app_id") and ref_kind(v) in ("token", "app"):
                g.node(v, "run", own=ref_kind(v) == "token" or None, carrier=rel)
                g.edge(v, "run", rel, "recorded", rel)
                added = True
        if added:
            g.node(rel, "record", own=True, carrier=rel, path=rel, record_kind="runner")
            n_other += 1
    g.carrier("records", "ok" if n_prov or n_other else "skipped", count=n_prov,
              why=f"{n_other} runner-native records (RECORD_SHAPES)")


def _record_paths(g):
    """{tracked record path: graph key} for every committed record the extractors read."""
    out = {}
    for k, n in g.nodes.items():
        if n.get("kind") == "record" and n.get("own") and isinstance(n.get("path"), str):
            out[n["path"]] = n["path"]
    return out


def _derive_joins(g):
    """Single-candidate joins, after every extractor: a result citing an evidence folder (or file) that holds
    exactly one record gets `run <record>` (via join); several candidates are reported as ambiguous, never
    joined."""
    paths = sorted(_record_paths(g))
    joined = 0
    for key, n in list(g.nodes.items()):
        if n.get("kind") != "result" or not n.get("own"):
            continue
        if any(e["rel"] == "run" for e in g.causes(key, strong=True)):
            continue
        targets = {e["cause"] for e in g.causes(key, strong=True)
                   if e["rel"] == "source" and e["kind"] == "path" and e["cause"].startswith(EVIDENCE_DIR + "/")}
        for t in sorted(targets):
            hits = [p for p in paths if p == t or p.startswith(t.rstrip("/") + "/")]
            if len(hits) == 1:
                g.edge(key, "run", hits[0], "join", f"{RESULTS} {n.get('where')}", note=f"the one record in {t}")
                joined += 1
                break
            if len(hits) > 1:
                g.ambiguous.append(f"{key}: {t} holds {len(hits)} records; name the one with a run line")
    g.carrier("joins", "ok", count=joined, why="results joined to the one record in their evidence")


# ---------------------------------------------------------------- extractor: tool pages

TOKEN_SECTIONS = ("Related", "Checks and controls", "History")


def _tokens(g, effect, text, where, line=None, decisions=True):
    """Id tokens (r:, c:, tool:, and D<n> when asked) in a live page, as `source` edges (typed, via token)."""
    n = 0
    for ref in RE_REF_TEXT.findall(text):
        if ref.startswith(("r:", "c:", "tool:")) and ref != effect:
            g.edge(effect, "source", ref, "token", where, line=line)
            n += 1
    if decisions and DECISIONS.rsplit("/", 1)[-1] in text or decisions == "always":
        for m in RE_DECISION_TEXT.finditer(text):
            g.edge(effect, "source", f"D{m.group(1)}", "token", where, line=line)
            n += 1
    return n


def _ex_tools(g):
    pages_dir = g.root / TOOLS_DIR
    if not pages_dir.is_dir():
        g.carrier("tools", "skipped", why=f"no {TOOLS_DIR}/")
        return
    from kit import tooldocs
    result_ids = {n["key"][2:]: k for k, n in g.nodes.items() if n["kind"] == "result" and n.get("own")}
    count = 0
    for page in tooldocs.load_pages(pages_dir):
        key = f"tool:{page.id}"
        rel = f"{TOOLS_DIR}/{page.id}.md"
        g.node(key, "tool", own=True, carrier=rel, title=page.title)
        count += 1
        for section in TOKEN_SECTIONS:
            start = page.lines.get(section, [None])[0] or 0
            for i, line in enumerate(page.bodies.get(section, []), start + 1):
                _tokens(g, key, line, f"{rel}:{i}", line=i)
        start = page.lines.get("History", [None])[0] or 0
        for i, line in enumerate(page.bodies.get("History", []), start + 1):
            m = RE_HISTORY.match(line)
            if not m:
                continue
            where = f"{rel}:{i}"
            for hx in re.findall(r"`([0-9a-f]{7,40})`", line):
                g.edge(key, "code", hx, "field", where, line=i, note=m.group(1))
            for owner, repo, num in re.findall(r"github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_-]+)/pull/(\d+)", line):
                g.edge(key, "code", f"{owner}/{repo}#{num}", "field", where, line=i, note=m.group(1))
            for ref in _runs_in(line):
                g.edge(key, "run", ref, "regex", where, line=i)
            for ref, _ in _paths_in(g, line):
                if ref_kind(ref) == "path" and _split_path(ref)[0].startswith(EVIDENCE_DIR + "/"):
                    g.edge(key, "source", ref, "regex", where, line=i)
            g.history.append({"tool": key, "date": m.group(1), "line": i, "where": where, "text": line})
        rstart = page.lines.get("Related", [None])[0] or 0
        for i, line in enumerate(page.bodies.get("Related", []), rstart + 1):
            for target in RE_MD_LINK.findall(line):
                ref = target if target.startswith("https://") else _rel_link(rel, target)
                if ref and ref_kind(ref) in ("path", "url"):
                    g.edge(key, "source", ref, "regex", f"{rel}:{i}", line=i)
        for n, line in _fences(page.text):
            _structured(g, key, line, "fence", f"{rel}:{n}", n)
        for i, line in enumerate(page.text.splitlines(), 1):
            for span in re.findall(r"`([a-z][a-z0-9_]*(?:\[\d+\])?)`", line):
                rid = None
                m = re.fullmatch(r"([a-z][a-z0-9_]*)\[(\d+)\]", span)
                if m:
                    rid = _result_at(g, m.group(1), int(m.group(2)))
                elif span in result_ids:
                    rid = f"r:{span}"
                if rid:
                    g.edge(key, "source", rid, "regex", f"{rel}:{i}", line=i)
    g.carrier("tools", "ok", count=count)


def _result_at(g, section, index):
    if g._at is None:
        g._at = {(n.get("section"), n.get("index")): k for k, n in g.nodes.items()
                 if n["kind"] in ("result", "pending") and n.get("own") and n.get("index") is not None}
    return g._at.get((section, index))


# ---------------------------------------------------------------- extractor: releases, ledger, git, handoff

def _ex_releases(g):
    text = _read(g.root, RELEASES)
    if text is None:
        g.carrier("releases", "skipped", why=f"no {RELEASES}")
        return
    try:
        data = json.loads(text)
    except ValueError:
        g.carrier("releases", "failed", why="not JSON")
        return
    rels = data.get("releases") if isinstance(data, dict) else None
    for i, r in enumerate(rels or []):
        if not isinstance(r, dict) or not isinstance(r.get("id"), str):
            continue
        key = f"release:{r['id']}"
        where = f"{RELEASES} releases[{i}]"
        g.node(key, "release", own=True, carrier=RELEASES, where=where)
        where_ = r.get("where") if isinstance(r.get("where"), dict) else {}
        if isinstance(where_.get("commit"), str) and RE_COMMIT.fullmatch(where_["commit"]):
            g.edge(key, "code", where_["commit"], "field", where)
        for t in r.get("tools") or []:
            if isinstance(t, dict):
                if isinstance(t.get("page"), str) and ref_kind(t["page"]) == "path":
                    g.edge(key, "source", t["page"], "field", where)
                if isinstance(t.get("evidence"), str):
                    for ref, _ in _paths_in(g, t["evidence"]):
                        g.edge(key, "source", ref, "field", where)
        for j, line in enumerate(r.get("causal") or []):
            _structured(g, key, line, "field", f"{where} causal[{j}]")
    g.carrier("releases", "ok", count=len(rels or []))


def _ledger_rows(root):
    path = Path(root) / stale.LEDGER
    if not path.is_file():
        return None
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _ex_ledger(g):
    """The Modal ledger's app_id column as a join target (typed); app ids, commits and evidence paths in its notes
    are hints only."""
    try:
        rows = _ledger_rows(g.root)
    except (OSError, csv.Error) as exc:
        g.carrier("ledger", "failed", why=str(exc))
        return
    if rows is None:
        g.carrier("ledger", "skipped", why=f"no {stale.LEDGER}")
        return
    g.ledger = rows
    for i, row in enumerate(rows):
        line = i + 2
        key = f"ledger:L{line}"
        where = f"{stale.LEDGER}:{line}"
        app = (row.get("app_id") or "").strip()
        g.node(key, "ledger", own=True, carrier=stale.LEDGER, line=line, when=row.get("date_time_et"),
               purpose=(row.get("purpose") or "")[:120])
        if app and ref_kind(app) == "app":
            g.node(app, "run", own=True, carrier=stale.LEDGER, line=line)
            g.edge(app, "run", key, "join", where, line=line, note="ledger row")
        text = row.get("notes") or ""
        effect = app if app and ref_kind(app) == "app" else key
        for ref in _runs_in(text):
            if ref != app:
                g.edge(key, "run", ref, "regex", where, line=line)
        for hx in RE_COMMIT_WORD.findall(text):
            g.edge(key, "code", hx, "regex", where, line=line)
        for ref, _ in _paths_in(g, text):
            if ref.startswith(EVIDENCE_DIR + "/"):
                g.edge(key, "source", ref, "regex", where, line=line)
        for ref in RE_REF_TEXT.findall(text):
            if ref.startswith("approval:"):
                g.edge(effect, "approval", ref, "regex", where, line=line)
    g.carrier("ledger", "ok", count=len(rows))


def _exemption(text):
    """(reason or None, error or None) from a `# causal: exempt REASON` header in a script's first 15 lines."""
    for line in text.splitlines()[:15]:
        m = RE_EXEMPT.match(line.strip())
        if m:
            reason = m.group(1).strip()
            if reason in EXEMPT_REASONS:
                return reason, None
            return None, f"exemption reason {reason!r} is not one of {', '.join(EXEMPT_REASONS)}"
    return None, None


def _ex_scripts(g):
    """Modal runner scripts under scripts/ (outside scripts/experiments/), for rule E14."""
    n = 0
    for rel in sorted(g.tracked()):
        if not (rel.startswith(SCRIPTS_DIR + "/") and rel.endswith(".py")) or rel.startswith("scripts/experiments/"):
            continue
        text = _read(g.root, rel) or ""
        if not any(sign in text for sign in RUNNER_SIGNS):
            continue
        reason, err = _exemption(text)
        g.node(f"script:{rel}", "script", own=True, carrier=rel, path=rel, exempt=reason, exempt_error=err,
               helper=any(sign in text for sign in HELPER_SIGNS))
        n += 1
    g.carrier("scripts", "ok" if n else "skipped", count=n, why="Modal runner scripts")


def _evidence_units(g):
    """Evidence folders: each first-level folder of docs/evidence/, or each second-level folder of one that holds
    only folders."""
    first = {}
    for rel in g.tracked():
        if rel.startswith(EVIDENCE_DIR + "/"):
            parts = rel.split("/")
            if len(parts) >= 4:
                first.setdefault(parts[2], set()).add(parts[3] if len(parts) > 4 else None)
    units = []
    for top, subs in sorted(first.items()):
        if None in subs or not subs:
            units.append(f"{EVIDENCE_DIR}/{top}")
        else:
            units += [f"{EVIDENCE_DIR}/{top}/{s}" for s in sorted(subs)]
    return units


def _ex_evidence(g):
    """Evidence folder nodes, with whether each holds a record (for new folders, rule E10)."""
    units = _evidence_units(g)
    records = _record_paths(g)
    outputs = {e["effect"] for e in g.edges if e["rel"] == "run" and e["via"] == "recorded"
               and g.nodes.get(e["cause"], {}).get("adopted")}
    for u in units:
        has = any(p.startswith(u + "/") for p in records) or any(o.startswith(u + "/") for o in outputs) or any(
            r.startswith(u + "/") and r.endswith(("graph.json", ".trainrecord.json", ".runrecord.json"))
            for r in g.tracked())
        g.node(u, "evidence", own=True, carrier=u, has_record=has)
    g.carrier("evidence", "ok" if units else "skipped", count=len(units))


def _ex_logs(g):
    """Dated logs: ```causal fences (a log written after the cutover) and r:, c:, tool: tokens, as source edges."""
    n = 0
    for rel in sorted(g.tracked()):
        if not (rel.startswith(LOGS_DIR + "/") and rel.endswith(".md")):
            continue
        text = _read(g.root, rel) or ""
        if "```causal" not in text and "r:" not in text and "c:" not in text:
            continue
        g.node(rel, "log", carrier=rel)
        for ln, line in _fences(text):
            _structured(g, rel, line, "fence", f"{rel}:{ln}", ln)
            n += 1
        for ln, line in enumerate(stale.FENCE.sub("", text).splitlines(), 1):
            if "r:" in line or "c:" in line or "tool:" in line:
                n += _tokens(g, rel, line, f"{rel}:{ln}", line=ln, decisions=False)
    g.carrier("logs", "ok" if g.is_dir(LOGS_DIR) else "skipped", count=n, why="fence lines and id tokens")


def _ex_handoff(g):
    text = _read(g.root, stale.HANDOFF)
    if text is None:
        return
    plain = {}
    for k, n in g.nodes.items():
        if not n.get("own"):
            continue
        if n["kind"] == "result":
            plain[k[2:]] = k
        elif n["kind"] in ("approval", "freeze"):
            plain[k.split(":", 1)[1]] = k
    for n, line in enumerate(text.splitlines(), 1):
        found = set(RE_REF_TEXT.findall(line)) | set(_runs_in(line))
        found |= {plain[s] for s in re.findall(r"`([A-Za-z0-9_./-]+)`", line) if s in plain}
        for ref, _ in _paths_in(g, line):
            if ref_kind(ref) == "path":
                found.add(_split_path(ref)[0])
        for ref in found:
            g.mentions.setdefault(_node_key(ref), []).append(n)


EXTRACTORS = (_ex_decisions, _ex_causal_dir, _ex_results, _ex_readme, _ex_files, _ex_records, _ex_releases,
              _ex_ledger, _ex_tools, _ex_logs, _ex_scripts)


def load(root=ROOT, runs=(), public=None):
    """The graph of one repository, read from every carrier present. `runs` are extra run folders an extension
    may read (Scrolls-private reads AutoPipeline run folders). `public` forces the public rules (default: on when
    the repository has no causal_ext module)."""
    g = Graph(root, public=public)
    g.runs = [Path(r) for r in runs]
    _load_baseline(g)
    for fn in EXTRACTORS:
        fn(g)
    for fn in HOOKS.extractors:
        fn(g)
    _derive_joins(g)
    _ex_evidence(g)
    _ex_handoff(g)
    return g


# ---------------------------------------------------------------- states, requirements and gaps

NODE_REFS = ("result", "decision", "claim", "tool", "release", "approval", "freeze", "finding", "script")


def _state(g, ref, kind=None):
    kind = kind or ref_kind(ref)
    key = _node_key(ref, kind)
    if kind == "unknown":
        return "ok" if g.nodes.get(key, {}).get("own") else "unknown"     # internal keys such as ledger rows
    if kind == "none":
        return "none"
    if kind == "local":
        return "local"
    if kind == "url":
        return "external"
    if kind in ("private", "public"):
        return "opaque"
    if kind == "path":
        if g.is_tracked(key):
            return "frozen" if _frozen(key) else "ok"
        return "missing"
    if kind == "commit":
        return g.commit_state(key)
    if kind == "pr":
        return "unverified"
    if kind == "sha256":
        return "ok" if key[7:] in g.digests else "unverified"
    if kind == "field":
        return "ok"
    if kind in NODE_REFS:
        target = g.aliases.get(key, key)
        n = g.nodes.get(target)
        return "ok" if n is not None and n.get("own") else "missing"
    if kind in ("app", "token"):
        n = g.nodes.get(key)
        return "ok" if n is not None and n.get("own") else "unverified"
    return "unknown"


def _records_cited(g, key):
    """Record nodes a node reaches over strong run edges (its run token, a record digest or a record path)."""
    out, seen, frontier = [], {key}, [key]
    for _ in range(3):
        nxt = []
        for k in frontier:
            for e in g.causes(k, strong=True):
                if e["rel"] != "run" or e["cause"] in seen:
                    continue
                seen.add(e["cause"])
                nxt.append(e["cause"])
                if g.nodes.get(e["cause"], {}).get("kind") == "record":
                    out.append(e["cause"])
        frontier = nxt
    return out


def _direct(g, key, rel, accept=None):
    return [e for e in g.causes(key, strong=True) if e["rel"] == rel and (accept is None or accept(e))]


def _meets(g, key, rel, accept=None, depth=4):
    """How node `key` meets relation `rel`: [] when it does not, else the chain of edges (the last one is of
    `rel`). A direct hash or typed edge meets it; for rel in TRANSITIVE, so does a chain of hash or typed edges
    whose relations are all in CHAIN_RELS, ending at a node that meets it directly. Hint edges never count.
    `accept(edge)` filters the final edge (control passes only from a record that carries a control line)."""
    hit = _direct(g, key, rel, accept)
    if hit:
        return [hit[0]]
    if rel not in TRANSITIVE:
        return []
    seen, queue = {key}, deque([(key, [])])
    while queue:
        k, chain = queue.popleft()
        if len(chain) >= depth:
            continue
        for e in g.causes(k, strong=True):
            if e["rel"] not in CHAIN_RELS or e["cause"] in seen:
                continue
            seen.add(e["cause"])
            step = chain + [e]
            final = _direct(g, e["cause"], rel, accept)
            if rel == "control":
                final = [x for x in final if g.nodes.get(e["cause"], {}).get("kind") == "record"]
            if final:
                return step + [final[0]]
            queue.append((e["cause"], step))
    return []


def _path_text(chain):
    return " > ".join(f"{e['rel']} {e['ref']} ({e['cls']}, {e['via']})" for e in chain)


def _usable_source(g, e):
    if e["kind"] == "url":
        return True
    if e["kind"] == "path":
        return g.is_tracked(e["cause"])
    if e["kind"] in ("result", "claim", "decision", "tool"):
        return _state(g, e["cause"], e["kind"]) == "ok"
    return False


def _req(kind, missing, notes=None, met=None, enforceable=True):
    return {"kind": kind, "missing": missing, "notes": notes or {}, "met": met or {}, "enforceable": enforceable}


def _req_result(g, key, n):
    missing, notes, met = [], {}, {}
    src = _direct(g, key, "source", lambda e: _usable_source(g, e))
    if src:
        met["source"] = _path_text(src[:1])
    else:
        missing.append("source")
    runs = _direct(g, key, "run")
    if runs:
        met["run"] = _path_text(runs[:1])
    else:
        missing.append("run")
    run_none = bool(runs) and all(e["kind"] == "none" for e in runs)
    if runs and not run_none:
        chain = _meets(g, key, "code", lambda e: not e.get("external"))
        if chain:
            met["code"] = _path_text(chain)
        else:
            missing.append("code")
    if n.get("control_required"):
        external = n.get("section") in EXTERNAL_SECTIONS
        chain = _meets(g, key, "control", lambda e: e["kind"] != "none" or (
            external and e["ref"] == "none:community-report"))
        if chain:
            met["control"] = _path_text(chain)
        else:
            missing.append("control")
            if _direct(g, key, "control"):
                notes["control"] = ("none: is not allowed for a unit with a score or a verdict (hard rule 4), except "
                                    "community-report in " + ", ".join(EXTERNAL_SECTIONS))
    if n.get("verdict"):
        chain = _meets(g, key, "prereg", lambda e: e["kind"] == "sha256" or (
            e["kind"] == "path" and bool(e["pin"] or e["at"] or g.nodes.get(e["cause"], {}).get("pin"))))
        if chain:
            met["prereg"] = _path_text(chain)
        else:
            missing.append("prereg")
            notes["prereg"] = "a unit with a verdict needs a pinned preregistration (@commit or sha256; hard rule 3)"
    else:
        chain = _meets(g, key, "prereg")
        if chain:
            met["prereg"] = _path_text(chain)
        else:
            missing.append("prereg")
    return _req("result", missing, notes, met)


def _claim_issues(g, key, n):
    """(missing, notes) for one claims.json entry (rule E17)."""
    missing, notes = [], {}
    if n.get("quote_hits", 0) != 1:
        missing.append("quote")
        notes["quote"] = (f"the quote occurs {n.get('quote_hits', 0)} times in Novel findings item "
                          f"{n.get('readme_item')}; it must occur once")
    if n.get("label") not in LABELS:
        missing.append("label")
        notes["label"] = f"label must be one of {', '.join(LABELS)} (docs/NOVELTY.md)"
    causes = [e for e in g.causes(key, strong=True) if e["rel"] == "source"]
    units = [e for e in causes if e["kind"] == "result"]
    evidence = [e for e in causes if e["kind"] == "path" and e["cause"].startswith(EVIDENCE_DIR + "/")]
    if not units and not evidence:
        missing.append("cause")
        notes["cause"] = "at least one `source r:<id> sha256:<unit_sha256>` or docs/evidence cause"
    elif not evidence and all(g.nodes.get(e["cause"], {}).get("section") in EXTERNAL_SECTIONS for e in units):
        missing.append("cause")
        notes["cause"] = f"a claim may not rest only on {', '.join(EXTERNAL_SECTIONS)} rows"
    stale_pins = []
    for e in units:
        target = g.nodes.get(g.aliases.get(e["cause"], e["cause"]), {})
        if e["pin"] != target.get("unit_sha256"):
            stale_pins.append(e["cause"])
    if stale_pins:
        missing.append("pins")
        notes["pins"] = "; ".join(f"{key} cites {r} whose numbers changed; review and run `python -m kit causal add "
                                  f"claim --repin {key}`" for r in stale_pins)
    return missing, notes


def _req_file(g, key, n):
    """A spec needs a decision or an approval; a preregistration a decision, a spec or an approval. An approval or
    freeze that names the file counts (a reversed join), and so does a chain through CHAIN_RELS."""
    want = ("decision", "approval", "spec") if n["kind"] == "prereg" else ("decision", "approval")
    met = {}
    for rel in want:
        chain = _meets(g, key, rel)
        if chain:
            met[rel] = _path_text(chain)
            break
    if not met:
        for e in g.effects(key, strong=True):
            ek = g.nodes.get(e["effect"], {}).get("kind")
            if ek in ("approval", "freeze") and e["rel"] in ("spec", "prereg"):
                if ek == "approval" or _meets(g, e["effect"], "approval") or _meets(g, e["effect"], "spec"):
                    met["approval"] = f"named by {e['effect']} ({e['via']}, reversed)"
                    break
    missing = [] if met else ["decision"]
    return _req(n["kind"], missing, {} if met else {"decision": f"a ```causal fence (or an edges.jsonl edge) naming "
                                                                f"a {' or '.join(want)}"}, met)


def _req_decision(g, key, n):
    missing = []
    if n.get("needs_superseded_by") and not any(e["rel"] in SUPERSESSION for e in g.effects(key, strong=True)):
        missing.append("superseded_by")
    return _req("decision", missing, {"superseded_by": "the row says it was replaced, lifted or retired: the newer "
                                                       "row says `Replaces D<n>` (or Lifts, Retires)"}
                if missing else {}, enforceable=bool(n.get("explicit_id")))


def _req_release(g, key, n):
    missing = [r for r in ("decision", "code") if not _direct(g, key, r)]
    return _req("release", missing)


def _req_record(g, key, n):
    """An adopted run record: code; a decision, spec or prereg (or prereg none:development)."""
    missing = []
    if not _direct(g, key, "code"):
        missing.append("code")
    if not any(_direct(g, key, r) for r in ("decision", "spec", "prereg")) and not _meets(g, key, "approval"):
        missing.append("decision")
    return _req("run", missing, {"decision": "a decision, spec or prereg line (or prereg none:development)"}
                if "decision" in missing else {})


def requirements(g):
    """{node key: {kind, missing, notes, met, enforceable}} for every node that has required links (rule E10)."""
    reqs = {}
    for key, n in g.nodes.items():
        if not n.get("own"):
            continue
        kind = n["kind"]
        if kind == "result":
            reqs[key] = _req_result(g, key, n)
        elif kind == "finding":
            reqs[key] = _req("finding", ["claim"], {"claim": f"a {CLAIMS} entry whose quote is in this item"})
        elif kind == "claim":
            missing, notes = _claim_issues(g, key, n)
            reqs[key] = _req("claim", missing, notes)
        elif kind in ("spec", "prereg") and n.get("carrier") == key:
            reqs[key] = _req_file(g, key, n)
        elif kind == "decision":
            reqs[key] = _req_decision(g, key, n)
        elif kind == "release":
            reqs[key] = _req_release(g, key, n)
        elif kind == "record" and n.get("runrecord") and n.get("adopted"):
            reqs[key] = _req_record(g, key, n)
        elif kind == "script":
            ok = n.get("helper") or n.get("exempt")
            reqs[key] = _req("script", [] if ok else ["helper"], {} if ok else {
                "helper": f"call kit runrecord ({' or '.join(HELPER_SIGNS[:2])}) or add `# causal: exempt REASON` "
                          f"({', '.join(EXEMPT_REASONS)})"})
        elif kind == "evidence":
            reqs[key] = _req("evidence", [] if n.get("has_record") else ["record"], {} if n.get("has_record") else {
                "record": "a *.provenance.json, *.runrecord.json, graph.json, *.trainrecord.json or RECORD_SHAPES "
                          "file, or name the folder in an adopted run record's outputs"})
    for fn in HOOKS.requirements:
        fn(g, reqs)
    return reqs


def _is_old(g, key):
    """True when a node existed at the cutover (or no baseline exists yet)."""
    if g.baseline is None:
        return True
    n = g.nodes.get(key, {})
    if "old" in n:
        return bool(n["old"])
    return key in _initial_keys(g)


def _suggest(g, key, missing):
    """Weak suggestions for one gap: hint edges of the missing relation the extractors saw (prose, regex)."""
    out = []
    for e in g.causes(key):
        if e["cls"] == "hint" and e["rel"] in missing:
            out.append({"line": f"{e['rel']} {e['ref']}", "weak": True, "where": e["carrier"]})
    if "decision" in missing or "approval" in missing:
        for a in g.ambiguous:
            if a.startswith(f"{key}:"):
                out.append({"line": a, "weak": True, "where": "ambiguous join"})
    return out


def gaps(g, kinds=(), need=(), new=False, suggest=False):
    """Every (node, missing relation) pair: {"gaps": [{node, kind, missing, old, baselined, new}], "counts"}.
    `new` keeps only the pairs absent from the baseline; `suggest` adds weak suggestions (hint edges) per row.
    counts.none_lines counts the none:<reason> lines per relation, so a spray of excuses shows."""
    reqs = requirements(g)
    listed = (g.baseline or {}).get("gaps", {})
    rows, counts = [], {"nodes": 0, "pairs": 0, "by_kind": {}, "by_gap": {}, "old_pairs": 0, "new_pairs": 0,
                        "provisional": 0, "none_lines": {}, "ambiguous": len(set(g.ambiguous))}
    for e in g.edges:
        if e["structured"] and e["kind"] == "none":
            counts["none_lines"][e["rel"]] = counts["none_lines"].get(e["rel"], 0) + 1
    for key in sorted(reqs, key=_sort_key):
        r = reqs[key]
        if kinds and r["kind"] not in kinds:
            continue
        miss = [m for m in r["missing"] if not need or m in need]
        if not miss:
            continue
        old = _is_old(g, key)
        base = set(listed.get(key, [])) if old else set()
        fresh = [m for m in miss if m not in base] if g.baseline is not None and r["enforceable"] else []
        if new and not fresh:
            continue
        row = {"node": key, "kind": r["kind"], "missing": miss, "old": old, "baselined": sorted(base & set(miss)),
               "new": fresh, "enforceable": r["enforceable"]}
        if r.get("notes"):
            row["notes"] = {k: v for k, v in r["notes"].items() if k in miss}
        if suggest:
            row["suggest"] = _suggest(g, key, miss)
        rows.append(row)
        counts["nodes"] += 1
        counts["pairs"] += len(miss)
        counts["by_kind"][r["kind"]] = counts["by_kind"].get(r["kind"], 0) + 1
        for m in miss:
            counts["by_gap"][m] = counts["by_gap"].get(m, 0) + 1
        counts["new_pairs"] += len(fresh)
        if r["enforceable"]:
            counts["old_pairs"] += len(miss) - len(fresh)
        else:
            counts["provisional"] += len(miss)
    return {"gaps": rows, "counts": counts}


def _sort_key(key):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", key)]


# ---------------------------------------------------------------- resolve, why, effects, show

def resolve(g, text):
    """{"key", "kind", "candidates"} for a reference or a fuzzy description (an index citation such as
    'letter_reader_checks[5]', a dict section, a '2026-10-20 row', an app id, a token, a digest prefix, a path or a
    tool id). Raises CausalError when nothing or more than one thing matches."""
    t = (text or "").strip()
    if not t:
        raise CausalError("nothing to resolve")
    t = g.aliases.get(t, t)
    kind = ref_kind(t)
    key = _node_key(t, kind) if kind != "unknown" else t
    if key in g.nodes:
        return _resolved(g, key)
    if f"r:{t}" in g.nodes:
        return _resolved(g, f"r:{t}")
    m = re.fullmatch(r"([a-z][a-z0-9_]*)\[(\d+)\]", t)
    if m:
        k = _result_at(g, m.group(1), int(m.group(2)))
        if k:
            return _resolved(g, k)
    for prefix in ("approval:", "freeze:", "tool:", "c:", "release:", "script:"):
        if prefix + t in g.nodes:
            return _resolved(g, prefix + t)
    if kind == "path" and g.is_tracked(key):
        g.node(key, _path_kind(key))
        return _resolved(g, key)
    m = RE_DATE_ROW.search(t)
    if m:
        hits = [k for k, n in g.nodes.items() if n["kind"] == "decision" and n.get("own") and n.get("date") == m.group(1)]
        return _one(g, t, hits)
    if re.fullmatch(r"[0-9a-f]{7,64}", t):
        hits = [k for k in g.nodes if (k.startswith("sha256:") and k[7:].startswith(t)) or
                (RE_COMMIT.fullmatch(k) and (k.startswith(t) or t.startswith(k)))]
        if hits:
            return _one(g, t, hits)
    low = t.lower()
    hits = [k for k in g.nodes if low in k.lower() and g.nodes[k].get("own")]
    return _one(g, t, hits)


def _one(g, text, hits):
    hits = sorted(set(hits), key=_sort_key)
    if len(hits) == 1:
        return _resolved(g, hits[0])
    if not hits:
        raise CausalError(f"no node matches {text!r}")
    err = CausalError(f"{text!r} is ambiguous: {', '.join(hits[:20])}{' ...' if len(hits) > 20 else ''}")
    err.candidates = hits
    raise err


def _resolved(g, key):
    return {"key": key, "kind": g.nodes[key]["kind"], "candidates": [key]}


GROUPS = {"decision": "decision", "approval": "approval", "spec": "spec", "prereg": "prereg", "freeze": "freeze",
          "run": "run", "code": "code", "input": "inputs", "control": "control", "source": "source",
          "supersedes": "supersedes", "corrects": "supersedes"}


def _edge_view(g, e, frm=None, depth=None):
    out = {"ref": e["ref"], "node": e["cause"], "rel": e["rel"], "state": _state(g, e["ref"], e["kind"]),
           "cls": e["cls"], "via": e["via"], "carrier": e["carrier"]}
    for k in ("pin", "at", "note", "external", "basis"):
        if e.get(k):
            out[k] = e[k]
    if frm is not None:
        out["from"] = frm
    if depth is not None:
        out["depth"] = depth
    return out


def why(g, ref, depth=3, kinds=(), strong=False):
    """Walk back from a node to its causes, grouped by kind: {node, kind, causes, missing, met, chains}. `strong`
    keeps only hash and typed edges. A run edge is provenance, never proof that a change caused a gain."""
    key = resolve(g, ref)["key"]
    out = {"node": key, "kind": g.nodes[key]["kind"], "state": _state(g, key), "causes": {}, "missing": [],
           "chains": []}
    seen, queue = {key}, deque([(key, 0, [])])
    while queue:
        k, d, chain = queue.popleft()
        if d >= depth:
            continue
        leaf = True
        for e in g.causes(k, strong=strong):
            group = "ledger" if g.nodes.get(e["cause"], {}).get("kind") == "ledger" else GROUPS.get(e["rel"], e["rel"])
            if kinds and group not in kinds:
                continue
            leaf = False
            out["causes"].setdefault(group, []).append(_edge_view(g, e, frm=k, depth=d + 1))
            step = chain + [f"{k} {e['rel']} {e['cause']} ({e['cls']}, {e['via']})"]
            if e["cause"] in seen or d + 1 >= depth or not g.causes(e["cause"]):
                if len(out["chains"]) < 50:
                    out["chains"].append(step)
            if e["cause"] not in seen:
                seen.add(e["cause"])
                queue.append((e["cause"], d + 1, step))
        if leaf and chain and len(out["chains"]) < 50 and chain not in out["chains"]:
            out["chains"].append(chain)
    req = requirements(g).get(key)
    if req:
        out["missing"] = req["missing"]
        out["met"] = req.get("met", {})
        if req.get("notes"):
            out["notes"] = req["notes"]
    for fn in HOOKS.why:
        fn(g, key, out)
    return out


EFFECT_GROUPS = {"result": "results", "pending": "results", "claim": "claims", "finding": "claims",
                 "tool": "tool_pages", "release": "releases", "approval": "approvals", "freeze": "freezes",
                 "decision": "decisions", "record": "runs", "run": "runs", "ledger": "ledger", "spec": "specs",
                 "prereg": "preregs", "evidence": "evidence", "log": "logs", "commit": "commits", "script": "scripts"}


def effects(g, ref, depth=3):
    """Walk forward from a node over the derived edges: {node, effects: {group: [...]}, superseded_by,
    mentioned_in_handoff, stale_citers}."""
    key = resolve(g, ref)["key"]
    out = {"node": key, "kind": g.nodes[key]["kind"], "effects": {}, "superseded_by": [],
           "mentioned_in_handoff": g.mentions.get(key, []), "stale_citers": []}
    seen, queue = {key}, deque([(key, 0)])
    while queue:
        k, d = queue.popleft()
        if d >= depth:
            continue
        for e in g.effects(k):
            n = g.nodes.get(e["effect"], {})
            item = {"node": e["effect"], "rel": e["rel"], "from": k, "depth": d + 1, "cls": e["cls"],
                    "via": e["via"], "carrier": e["carrier"]}
            if n.get("kind") == "result" and n.get("entry"):
                v = next((n["entry"][x] for x in n["entry"] if RE_VERDICT_KEY.search(x)), None)
                if v is not None:
                    item["verdict"] = v if isinstance(v, (str, bool, int, float)) else json.dumps(v)[:120]
            if k == key and e["rel"] in SUPERSESSION:
                out["superseded_by"].append(item)
            if n.get("kind") == "result" and any(x["cause"] == e["effect"] and x["rel"] in SUPERSESSION
                                                 for x in g.effects(e["effect"])):
                item["superseded"] = True
            out["effects"].setdefault(EFFECT_GROUPS.get(n.get("kind"), "other"), []).append(item)
            if e["effect"] not in seen:
                seen.add(e["effect"])
                queue.append((e["effect"], d + 1))
    if out["superseded_by"]:
        newer = {s["node"] for s in out["superseded_by"]}
        for e in g.effects(key, strong=False):
            if e["rel"] in SUPERSESSION or e["effect"] in newer:
                continue
            if not any(c["cause"] in newer for c in g.causes(e["effect"])):
                out["stale_citers"].append({"node": e["effect"], "rel": e["rel"], "carrier": e["carrier"]})
    return out


def show(g, ref):
    """One node: its kind, carrier, line, state, unit hash, its edges in and out (with cls and via), and each
    requirement as met (and how, with the transitive path), missing, or baselined."""
    key = resolve(g, ref)["key"]
    n = dict(g.nodes[key])
    entry = n.pop("entry", None)
    n["state"] = _state(g, key)
    n["causes"] = [_edge_view(g, e) for e in g.causes(key)]
    n["effects"] = [{"node": e["effect"], "rel": e["rel"], "cls": e["cls"], "via": e["via"], "carrier": e["carrier"]}
                    for e in g.effects(key)]
    req = requirements(g).get(key)
    if req:
        listed = set(((g.baseline or {}).get("gaps") or {}).get(key, [])) if _is_old(g, key) else set()
        n["requirements"] = {**{r: {"status": "met", "how": how} for r, how in req.get("met", {}).items()},
                             **{r: {"status": "baselined" if r in listed else "missing",
                                    **({"note": req["notes"][r]} if r in req.get("notes", {}) else {})}
                                for r in req["missing"]}}
    if entry is not None:
        n["fields"] = sorted(entry)
    if key in g.mentions:
        n["mentioned_in_handoff"] = g.mentions[key]
    return n


# ---------------------------------------------------------------- hashing

class _Budget:
    def __init__(self, total=HASH_BUDGET):
        self.left = total
        self.skipped = 0


def _hash_path(g, rel, at=None, budget=None):
    """sha256 of a tracked file (at a commit when given), or of a folder's SHA256SUMS; None when unreadable or past
    the budget."""
    if at:
        try:
            out = subprocess.run(["git", "-C", str(g.root), "show", f"{at}:{rel}"], capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return _sha256_bytes(out.stdout) if out.returncode == 0 else None
    path = g.root / rel
    if path.is_dir():
        sums = path / "SHA256SUMS"
        return _hash_path(g, f"{rel}/SHA256SUMS", budget=budget) if sums.is_file() else None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if budget is not None:
        if size > budget.left:
            budget.skipped += 1
            return None
        budget.left -= size
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _blob_hashes(g, paths):
    """{path: {sha256 of each committed version}} for the given paths, from one git log and one git cat-file call."""
    out = {p: set() for p in paths}
    if not g.git.ok or not paths:
        return out
    raw = g.git.run("log", "--format=", "--raw", "--no-abbrev", "--", *paths) or ""
    blobs = {}
    for line in raw.splitlines():
        parts = line.split()
        if line.startswith(":") and len(parts) >= 6 and set(parts[3]) != {"0"}:
            blobs.setdefault(parts[3], set()).add(parts[-1])
    if not blobs:
        return out
    try:
        proc = subprocess.run(["git", "-C", str(g.root), "cat-file", "--batch"],
                              input="".join(f"{b}\n" for b in blobs).encode(), capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return out
    data, pos = proc.stdout, 0
    for b, names in blobs.items():
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        head = data[pos:nl].split()
        if len(head) < 3 or head[1] != b"blob":
            pos = nl + 1
            continue
        size = int(head[2])
        digest = _sha256_bytes(data[nl + 1:nl + 1 + size])
        pos = nl + 1 + size + 1
        for name in names:
            out.setdefault(name, set()).add(digest)
    return out


def _prereg_versions(g):
    """{sha256: path} for every committed version of every preregistration this clone holds, plus the files as
    they are now."""
    if g._prereg_versions is not None:
        return g._prereg_versions
    out = {}
    for path, digests in _blob_hashes(g, [PREREG_DIR]).items():
        for d in digests:
            out.setdefault(d, path)
    for rel in g.tracked():
        if rel.startswith(PREREG_DIR + "/") and (g.root / rel).is_file():
            out.setdefault(_hash_path(g, rel), rel)
    g._prereg_versions = out
    return out


# ---------------------------------------------------------------- check

def _err_new(g, key, req):
    n = g.nodes.get(key, {})
    where = f"{n.get('carrier') or key}{':' + str(n['line']) if n.get('line') else ''}"
    miss = ", ".join(req["missing"])
    hint = {"result": 'give the entry an "id" and a "causal" list, e.g. "causal": ["run TOKEN", "control '
                      'sha256:<control map>", "prereg docs/prereg/X.md@COMMIT", "code COMMIT"] (python -m kit causal '
                      'add result --from-run TOKEN)',
            "spec": "add a ```causal fence naming the decision or approval (or python -m kit causal link)",
            "prereg": "add a ```causal fence naming the decision, approval or spec (or python -m kit causal link)",
            "decision": "add `Replaces D<n>` to the newer row",
            "release": "add causal lines naming the decision and the code commit",
            "run": "add code and a decision, spec or prereg line to the run record (kit runrecord start --causal)",
            "evidence": "commit the run's record with the folder (kit runrecord adopt, or a provenance record)",
            "approval": 'add "causal": ["decision D<n>"] and a spec',
            "freeze": 'add "causal": ["approval approval:ID"] and, when spent, its evidence, token and result'}
    return where, (f"{key} is new since the causal cutover and lacks: {miss}; "
                   f"{hint.get(req['kind'], 'add the missing links')} (docs/causal/README.md)")


def _baseline_integrity(g, report, reqs, pinned_sha=None, pinned_max=None):
    b = g.baseline
    if b is None:
        report["info"].append(f"no {BASELINE}: nothing is exempt from the ratchet yet, so E10 and E11 are skipped; "
                              "start it with `python -m kit causal ratchet --write`")
        return
    init = b.get("initial") or {}
    digest = _sha256_bytes(_canonical(init))
    if digest != b.get("initial_sha256"):
        _add(report, "E11", BASELINE, f"initial_sha256 {b.get('initial_sha256')} does not match the initial set "
                                      f"({digest})")
    if pinned_sha is not None and b.get("initial_sha256") != pinned_sha:
        _add(report, "E11", BASELINE, "initial_sha256 differs from the INITIAL_SHA256 the repository test pins")
    pairs = sum(len(v) for v in (b.get("gaps") or {}).values())
    if pinned_max is not None and pairs > pinned_max:
        _add(report, "E11", BASELINE, f"{pairs} gap pairs, over BASELINE_MAX {pinned_max}")
    init_gaps, init_legacy = init.get("gaps", {}), init.get("legacy", {})
    for k, listed in b.get("gaps", {}).items():
        if k not in init_gaps:
            _add(report, "E11", BASELINE, f"{k} is not in the initial set; the baseline may only shrink")
        elif not set(listed) <= set(init_gaps[k]):
            _add(report, "E11", BASELINE, f"{k} lists {', '.join(sorted(set(listed) - set(init_gaps[k])))} that "
                                          "the initial set did not")
    for k, fp in (b.get("legacy") or {}).items():
        if init_legacy.get(k) != fp:
            _add(report, "E11", BASELINE, f"legacy {k} is not in the initial set as written")
    for k, listed in b.get("gaps", {}).items():
        target = g.aliases.get(k, k)
        if target not in reqs:
            if k.startswith("finding:"):
                _add(report, "A8", f"{BASELINE} {k}", f"{k} now has a claim: run `python -m kit causal ratchet "
                                                       "--write`")
                continue
            _add(report, "E2", BASELINE, f"{k} is listed in the baseline but no longer exists; run `python -m kit "
                                         "causal ratchet --write` to drop it, or record an alias")
            continue
        actual = set(reqs[target]["missing"])
        extra = actual - set(listed)
        if extra:
            _add(report, "E11", f"{BASELINE} {k}", f"gained {', '.join(sorted(extra))} since the cutover; the "
                                                    "baseline may only shrink, so add the links")
        done = set(listed) - actual
        if done:
            _add(report, "A8", f"{BASELINE} {k}", f"{', '.join(sorted(done))} now satisfied: run `python -m kit "
                                                   "causal ratchet --write`")


def _add(report, rule, where, text):
    level = "error" if rule.startswith("E") else "attention" if rule.startswith("A") else "info"
    report["findings"].append({"rule": rule, "level": level, "where": where, "text": text})


def _family(g, ref, kind):
    if kind in ("result", "claim", "decision", "finding"):
        return "claim" if kind == "finding" else kind
    if kind == "path":
        return "log" if ref.startswith(LOGS_DIR + "/") else "file"
    node = g.nodes.get(ref, {})
    return node.get("kind")


def _effect_slot(g, key):
    """True when the effect end carries its own links and so may not take an edges.jsonl edge."""
    kind = g.nodes.get(key, {}).get("kind") or _ref_node_kind(key, ref_kind(key))
    return kind in ("result", "pending", "approval", "freeze", "release", "claim", "finding", "record")


def _public_leak(g, e):
    p = e.get("parsed") or {}
    kind = p.get("kind") or e["kind"]
    if p.get("rel") in PRIVATE_RELS:
        return f"{p['rel']} links are kept only by repositories that have approvals and freezes"
    if kind in ("approval", "freeze", "app", "local", "public"):
        return f"{kind} references never go in public files"
    if kind == "path" and not g.is_tracked(p.get("path") or e["cause"]):
        return f"{e['cause']} is not tracked in this repository"
    if "Scrolls-private" in (p.get("ref") or ""):
        return "Scrolls-private references never go in public files"
    return None


def _record_agreement(g, report):
    """E16: an entry naming a token whose run record is adopted must not contradict the record's code, control,
    prereg pin or apps."""
    for key, n in g.nodes.items():
        if not n.get("own") or n.get("kind") not in ("result", "approval", "freeze"):
            continue
        mine = [e for e in g.causes(key, strong=True) if e["structured"] or e["via"] == "alias"]
        for e in mine:
            if e["rel"] != "run" or e["kind"] != "token":
                continue
            rk = g.nodes.get(e["cause"], {}).get("record")
            rn = g.nodes.get(rk or "", {})
            if not rn.get("adopted"):
                continue
            rec = {x["rel"]: [] for x in g.causes(rk)}
            for x in g.causes(rk):
                rec[x["rel"]].append(x)
            where = n.get("carrier") or key
            codes = [x["cause"] for x in mine if x["rel"] == "code" and not x.get("external")]
            rcodes = [x["cause"] for x in rec.get("code", []) if not x.get("external")]
            if codes and rcodes and not any(a.startswith(b) or b.startswith(a) for a in codes for b in rcodes):
                _add(report, "E16", where, f"{key} says code {', '.join(codes)} but run record {e['cause']} says "
                                           f"{', '.join(rcodes)}")
            for rel, kinds in (("run", ("app",)), ("control", ("sha256",))):
                a = {x["cause"] for x in mine if x["rel"] == rel and x["kind"] in kinds}
                b = {x["cause"] for x in rec.get(rel, []) if x["kind"] in kinds}
                if a and b and not a & b:
                    _add(report, "E16", where, f"{key} and run record {e['cause']} name different {rel} "
                                               f"references ({', '.join(sorted(a))} against {', '.join(sorted(b))})")
            pa = {x["cause"]: x["pin"] for x in mine if x["rel"] == "prereg" and x["pin"]}
            for x in rec.get("prereg", []):
                if x["pin"] and x["cause"] in pa and pa[x["cause"]] != x["pin"]:
                    _add(report, "E16", where, f"{key} pins {x['cause']} differently from run record {e['cause']}")


def check(root=ROOT, only=(), strict=False, network=False, hash_pins=True, since=None, new_only=False, runs=(),
          public=None, graph=None, pinned_sha=None, pinned_max=None):
    """Apply the check rule (E1 to E17 errors, A1 to A10 attention). Returns {"exit", "findings", "info",
    "carriers", "counts"}; errors give exit 1, attention 3 (1 with strict), all carriers absent 75. `new_only`
    checks only what was added after the cutover (the fast path for hooks)."""
    g = graph or load(root, runs=runs, public=public)
    report = {"exit": EXIT_OK, "findings": list(g.findings), "info": [], "carriers": g.carriers,
              "public": g.public}
    reqs = requirements(g)
    budget = _Budget()
    structured = [e for e in g.edges if e["structured"]]
    # E3 to E7, E9 on structured links
    for e in structured:
        p = e["parsed"]
        where = e["carrier"]
        kind = p["kind"]
        if kind in NODE_REFS and _state(g, e["cause"], kind) != "ok":
            _add(report, "E3", where, f"{p['ref']} does not resolve")
        if kind == "local":
            _add(report, "E4", where, f"{p['ref']} is a local path (work/, experiments/, /Users, /tmp, /home "
                                      "or a scratchpad); commit the file or link something tracked")
        elif kind == "path":
            path = p["path"]
            if p["at"]:
                if g.git.ok and g.commit_state(p["at"]) == "ok" and not g.git.has_path(p["at"], path):
                    _add(report, "E3", where, f"{path} is not in commit {p['at']}")
            elif not g.is_tracked(path):
                _add(report, "E4", where, f"{path} is not tracked")
        skip_hash = new_only and _is_old(g, e["effect"])
        if hash_pins and not skip_hash and p["pin"] and kind == "path" and g.is_tracked(p["path"]):
            got = _hash_path(g, p["path"], at=p["at"], budget=budget)
            if got is None and g.is_dir(p["path"]):
                try:
                    from kit import provenance
                    got = provenance.fingerprint(str(g.root / p["path"]))["sha256"]
                except (OSError, ValueError, ImportError):
                    got = None
            if got is not None and got != p["pin"]:
                _add(report, "E5", where, f"pin sha256:{p['pin'][:12]}... does not match {p['path']} "
                                          f"(sha256 {got[:12]}...)")
        if p["pin"] and kind == "result" and not str(where).startswith(CLAIMS):
            target = g.nodes.get(g.aliases.get(e["cause"], e["cause"]), {})
            if target.get("unit_sha256") and target["unit_sha256"] != p["pin"]:
                _add(report, "E5", where, f"pin on {p['ref']} differs from its current unit_sha256; its numbers "
                                          "changed, so review what cites it")
        if p["rel"] == "run" and kind == "sha256" and p["ref"][7:] not in g.digests:
            _add(report, "A2", where, f"run record {p['ref'][:19]}... is not a committed record in this clone")
        if not _fits(p["rel"], kind, p["path"]):
            _add(report, "E6", where, f"{p['rel']} cannot point to a {kind} reference ({p['ref']})")
        if p["rel"] in SUPERSESSION:
            fe = _family(g, e["effect"], ref_kind(e["effect"]))
            fc = _family(g, e["cause"], kind)
            pending_ok = fe == "result" and p["ref"].startswith("r:pending@")
            if fe != fc and not pending_ok:
                _add(report, "E8", where, f"{p['rel']} links a {fe} to a {fc}; it stays within one family")
        if e["via"] == "overlay" and _effect_slot(g, e["effect"]):
            _add(report, "E6", where, f"{e['effect']} carries its own links; put the line there, not in {EDGES}")
        if kind == "field":
            entry = g.nodes.get(e["effect"], {}).get("entry") or {}
            fk = p["ref"][6:]
            if fk not in entry:
                _add(report, "E7", where, f"field:{fk} names a key {e['effect']} does not have")
            elif p["rel"] != "control":
                _add(report, "E6", where, "field:<key> is only for control")
        if g.public:
            leak = _public_leak(g, e)
            if leak:
                _add(report, "E9", where, leak)
    # A1: a causal line that restates a field the alias map already reads
    for e in structured:
        if e["via"] != "field" or not str(e["carrier"]).startswith(RESULTS):
            continue
        if any(x is not e and not x["structured"] and x["rel"] == e["rel"] and x["cause"] == e["cause"] and
               x["cls"] in STRONG and not e["pin"] and not e["at"] for x in g.causes(e["effect"])):
            _add(report, "A1", e["carrier"], f"{e['rel']} {e['ref']} restates a field the entry already has; drop "
                                             "the line or add a pin")
    # E5: legacy *_sha256 pairs in results
    if hash_pins and not new_only:
        for key, n in g.nodes.items():
            entry = n.get("entry") if n.get("kind") == "result" and n.get("own") else None
            for k, v in (entry or {}).items():
                base = k[:-7] if k.endswith("_sha256") else None
                if not base or not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v):
                    continue
                target = entry.get(base)
                if not (isinstance(target, str) and ref_kind(target.strip()) == "path"):
                    continue
                rel = _split_path(target.strip())[0]
                if not g.is_tracked(rel):
                    continue
                got = _hash_path(g, rel, budget=budget)
                if got is not None and got != v:
                    _add(report, "E5", f"{n['carrier']} {n['where']}", f"{k} does not match {rel}")
        versions = _prereg_versions(g)
        for e in g.edges:
            if e.get("note") == "rule_sha256" and e["cause"][7:] not in versions:
                _add(report, "A1", e["carrier"], f"rule_sha256 {e['cause'][7:19]}... matches no committed version "
                                                 "of any preregistration in this clone")
        if budget.skipped:
            report["info"].append(f"{budget.skipped} pins not hashed: past the {HASH_BUDGET >> 20} MB hash budget")
    # E8: supersession cycles
    sup = {}
    for e in g.edges:
        if e["rel"] in SUPERSESSION and e["cls"] in STRONG:
            sup.setdefault(e["effect"], set()).add(e["cause"])
    for start in sup:
        stack, seen = [start], set()
        while stack:
            k = stack.pop()
            for nxt in sup.get(k, ()):
                if nxt == start:
                    _add(report, "E8", start, f"{start} is in a supersedes/corrects cycle")
                    stack = []
                    break
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
    # E17: claims, old or new (no baseline holds a claim's problems)
    for key, r in sorted(reqs.items(), key=lambda kv: _sort_key(kv[0])):
        if r["kind"] == "claim" and r["missing"]:
            n = g.nodes.get(key, {})
            for m in r["missing"]:
                _add(report, "E17", n.get("where") or CLAIMS, r["notes"].get(m) or f"{key} lacks {m}")
        if r["kind"] == "script" and g.nodes.get(key, {}).get("exempt_error"):
            _add(report, "E14", g.nodes[key]["path"], g.nodes[key]["exempt_error"])
    # E10, E11, E14, E17: the ratchet
    made = (g.baseline or {}).get("made")
    if g.baseline is not None:
        listed = g.baseline.get("gaps", {})
        renamed = {new: old for old, new in g.aliases.items()}
        for key, r in sorted(reqs.items(), key=lambda kv: _sort_key(kv[0])):
            if not r["missing"] or not r["enforceable"] or r["kind"] == "claim":
                continue
            if _is_old(g, key) or renamed.get(key) in listed:
                if key not in listed and renamed.get(key) not in listed:
                    _add(report, "E11", f"{BASELINE} {key}", f"existed at the cutover with no gaps and now lacks "
                                                             f"{', '.join(r['missing'])}; add the links")
                continue
            where, text = _err_new(g, key, r)
            rule = {"script": "E14", "finding": "E17"}.get(r["kind"], "E10")
            if r["kind"] == "script":
                text = (f"{key[7:]} defines a Modal app and is new since the cutover: "
                        f"{r['notes'].get('helper', 'call the run record helper')}")
            elif r["kind"] == "finding":
                text = f"{key} is a Novel findings item added after the cutover without a {CLAIMS} entry"
            _add(report, rule, where, text)
        for key, n in g.nodes.items():
            if n.get("kind") == "result" and n.get("own") and not n.get("old") and not n.get("explicit_id"):
                _add(report, "E2", f"{RESULTS} {n['where']}", f"{key} is a results entry added after the cutover "
                                                              'without an "id"')
        # tool History bullets dated after the cutover that report a measurement
        for h in g.history:
            if made and h["date"] > made and RE_MEASURE.search(h["text"]) and not (
                    RE_REF_TEXT.search(h["text"]) or RE_TOKEN_TEXT.search(h["text"]) or
                    EVIDENCE_DIR + "/" in h["text"]):
                _add(report, "E10", h["where"], "a History bullet dated after the cutover reports a measurement but "
                                                "names no r:<id>, run token or docs/evidence path")
    _baseline_integrity(g, report, reqs, pinned_sha, pinned_max)
    provisional = [k for k, r in reqs.items() if r["missing"] and not r["enforceable"]]
    if provisional:
        report["info"].append(f"{len(provisional)} decision rows need a supersedes link but {DECISIONS} has no Id "
                              "column yet (python -m kit causal backfill --pass decision-ids)")
    _record_agreement(g, report)
    # A10: run records with no prereg line, or with no causal lines at all
    for key, n in g.nodes.items():
        if n.get("kind") == "record" and n.get("own") and n.get("runrecord") and n.get("adopted"):
            if not n.get("has_causal"):
                _add(report, "A10", n.get("path") or key, f"{key} was recorded without --causal lines")
            elif not n.get("has_prereg"):
                _add(report, "A10", n.get("path") or key, f"{key} has no prereg line (a pinned prereg, or prereg "
                                                          "none:<reason>)")
    if g.ambiguous and not new_only:
        _add(report, "A2", "joins", f"{len(set(g.ambiguous))} joins have several candidates and were not made: "
                                    + "; ".join(sorted(set(g.ambiguous))[:4]) + (" ..." if len(set(g.ambiguous)) > 4
                                                                                 else ""))
    # A2: commits this clone cannot reach
    commits = [e for e in g.edges if e["kind"] == "commit" and e["cls"] in STRONG and not e.get("external")]
    if not new_only:
        g._resolve_commits([e["cause"] for e in commits])
        unreachable = sorted({e["cause"] for e in commits if g.commit_state(e["cause"]) in ("unverified", "missing")})
        if unreachable:
            if network:
                for c in unreachable:
                    if _gh_commit(g, c) is False:
                        _add(report, "E3", "network", f"commit {c} is on neither remote")
            else:
                _add(report, "A2", "git", f"{len(unreachable)} commits this clone cannot reach (shallow clone or "
                                          f"deleted branch): {', '.join(unreachable[:12])}"
                                          f"{' ...' if len(unreachable) > 12 else ''}; --network checks them")
    # A3: forward staleness
    for e in g.edges:
        if e["rel"] in SUPERSESSION and e["cls"] in STRONG:
            old, newer = e["cause"], e["effect"]
            for c in g.effects(old, strong=True):
                if c["rel"] in SUPERSESSION or c["effect"] == newer:
                    continue
                kind = g.nodes.get(c["effect"], {}).get("kind")
                if kind in ("claim", "tool", "release", "result") and not any(
                        x["cause"] == newer for x in g.causes(c["effect"])):
                    _add(report, "A3", c["carrier"], f"{c['effect']} cites {old}, which {newer} {e['rel']}, "
                                                     f"without citing {newer}")
    if since:
        try:
            imp = impact(g.root, since, graph=g)
            for r in imp["results"]:
                _add(report, "A3", RESULTS, f"{r['key']} {r['change']} since {since}; effects to review: "
                                            f"{', '.join(sorted(r['effects'])) or 'none'}")
        except CausalError as exc:
            report["info"].append(str(exc))
    # A4: index citations on live pages
    if not new_only:
        sections = {n.get("section") for n in g.nodes.values()
                    if n.get("kind") in ("result", "pending") and n.get("own") and n.get("index") is not None}
        for rel in stale.live_pages(g.root):
            if rel == stale.HANDOFF:
                continue
            text = _read(g.root, rel) or ""
            for n, line in enumerate(text.splitlines(), 1):
                if "[" not in line:
                    continue
                for m in RE_INDEX_CITE.finditer(line):
                    if m.group(1) in sections:
                        k = _result_at(g, m.group(1), int(m.group(2)))
                        _add(report, "A4", f"{rel}:{n}", f"index citation {m.group(0)}; cite {k or 'the unit id'} "
                                                         "instead (indexes move)")
    # A6: old provenance records whose files match no committed version
    if hash_pins and not new_only:
        a6 = _recheck_records(g, budget)
        if a6:
            _add(report, "A6", "records", f"{len(a6)} record inputs match neither HEAD nor a committed version "
                                          f"(recorded from an uncommitted working state): {', '.join(a6[:6])}"
                                          f"{' ...' if len(a6) > 6 else ''}")
    for fn in HOOKS.checks:
        fn(g, report, {"network": network, "hash_pins": hash_pins, "new_only": new_only,
                       "public_root": getattr(g, "public_root", None)})
    if new_only:
        report["findings"] = [f for f in report["findings"] if f["level"] == "error"]
    if only:
        report["findings"] = [f for f in report["findings"] if f["rule"] in only]
    levels = {f["level"] for f in report["findings"]}
    statuses = {c["status"] for name, c in g.carriers.items() if name not in ("joins",)}
    if "error" in levels:
        report["exit"] = EXIT_FAIL
    elif "attention" in levels:
        report["exit"] = EXIT_FAIL if strict else EXIT_ATTENTION
    elif statuses and statuses <= {"skipped"}:
        report["exit"] = EXIT_SKIPPED
    counts = {}
    for f in report["findings"]:
        counts[f["rule"]] = counts.get(f["rule"], 0) + 1
    report["counts"] = counts
    report["errors"] = sum(1 for f in report["findings"] if f["level"] == "error")
    report["attention"] = sum(1 for f in report["findings"] if f["level"] == "attention")
    return report


def _gh_commit(g, sha):
    """True when a remote has the commit, False when every remote answers that it does not, None when it cannot
    say. Reads both remotes when the clone names Scrolls and Scrolls-private."""
    repos = [g.repo] if g.repo else []
    if g.repo:
        owner, name = g.repo.split("/", 1)
        other = name[:-8] if name.endswith("-private") else name + "-private"
        repos.append(f"{owner}/{other}")
    answers = []
    for repo in repos:
        try:
            out = subprocess.run(["gh", "api", f"repos/{repo}/commits/{sha}", "--jq", ".sha"], capture_output=True,
                                 text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if out.returncode == 0:
            return True
        answers.append(False if "Not Found" in out.stderr or "No commit found" in out.stderr else None)
    return False if answers and all(a is False for a in answers) else None


def _recheck_records(g, budget):
    """Record inputs (repository files) whose recorded sha256 matches neither the file at HEAD nor any committed
    version of it."""
    todo = []
    for e in g.edges:
        if not e.get("recheck") or e["kind"] != "path" or not e.get("pin"):
            continue
        rel = e["cause"]
        if not g.is_tracked(rel) or g.is_dir(rel):
            continue
        if _hash_path(g, rel, budget=budget) != e["pin"]:
            todo.append(e)
    history = _blob_hashes(g, sorted({e["cause"] for e in todo}))
    return sorted({f"{e['cause']} ({e['carrier']})" for e in todo if e["pin"] not in history.get(e["cause"], ())})


# ---------------------------------------------------------------- impact (effects --since)

def _units_at(text):
    data = json.loads(text)
    out = {}
    for section, index, entry in results_units(data):
        if isinstance(entry, str):
            continue
        key = f"r:{section}" if index is None else (f"r:{entry['id']}" if isinstance(entry.get("id"), str)
                                                     else f"r:{section}/{index}")
        out[key] = unit_sha256(entry)
    return out


def impact(root=ROOT, since="HEAD~1", graph=None):
    """Everything downstream of what changed since REV, for review: results units whose hash differs (added,
    changed, removed) and every changed file that is a node or carries nodes, each with its effects."""
    g = graph or load(root)
    old_text = g.git.run("show", f"{since}:{RESULTS}") if g.git.ok else None
    if old_text is None and g.git.ok and g.git.run("rev-parse", "--verify", f"{since}^{{commit}}") is None:
        raise CausalError(f"cannot read revision {since}")
    try:
        before = _units_at(old_text) if old_text else {}
    except ValueError:
        raise CausalError(f"{RESULTS} at {since} is not JSON")
    now = {k: n["unit_sha256"] for k, n in g.nodes.items() if n.get("kind") == "result" and n.get("own")}
    before_fp, now_fp = set(before.values()), set(now.values())
    results = []
    for k, fp in sorted(now.items(), key=lambda kv: _sort_key(kv[0])):
        if fp in before_fp:
            continue
        change = "changed" if k in before else "added"
        eff = effects(g, k, depth=2)["effects"]
        results.append({"key": k, "change": change, "effects": {grp: [x["node"] for x in v] for grp, v in eff.items()}})
    for k, fp in sorted(before.items(), key=lambda kv: _sort_key(kv[0])):
        if fp not in now_fp and k not in now:
            results.append({"key": k, "change": "removed", "effects": {}})
    names = (g.git.run("diff", "--name-only", since, "HEAD") or "").split()
    by_carrier = {}
    for k, n in g.nodes.items():
        if n.get("own") and isinstance(n.get("carrier"), str) and n["carrier"] != RESULTS:
            by_carrier.setdefault(n["carrier"], []).append(k)
    files = []
    for rel in names:
        keys = ([rel] if rel in g.nodes else []) + by_carrier.get(rel, [])
        eff = {}
        for key in dict.fromkeys(keys):
            for grp, v in effects(g, key, depth=2)["effects"].items():
                eff.setdefault(grp, []).extend(x["node"] for x in v)
        if keys:
            files.append({"path": rel, "nodes": list(dict.fromkeys(keys)),
                          "effects": {grp: list(dict.fromkeys(v)) for grp, v in eff.items()}})
    return {"since": since, "results": results, "files": files}


# ---------------------------------------------------------------- writers: link, add, backfill, ratchet

def _append_edges(root, record):
    _check_writable(root, EDGES)
    path = Path(root) / EDGES
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def link(root=ROOT, effect=None, line=None, basis=None, dry_run=False, alias=None, retract=None, reason=None,
         public=None, graph=None, by=None):
    """The only writer of docs/causal/edges.jsonl: an edge (effect, line, basis), an alias (alias=(OLD, NEW),
    basis) or a retraction (retract=SHA8 of the edge object, reason). Returns the record; dry_run writes nothing."""
    g = graph or load(root, public=public)
    if retract is not None:
        if not reason:
            raise CausalError("a retraction needs --reason")
        live = {e.get("sha8") for e in g.edges if e.get("via") == "overlay"}
        if retract not in live:
            raise CausalError(f"{EDGES} has no live edge whose sha8 is {retract}")
        rec = {"retract": retract, "reason": reason, "added": _today()}
    elif alias is not None:
        old, new = alias
        if not basis:
            raise CausalError("an alias needs --basis")
        if _state(g, new) != "ok":
            raise CausalError(f"{new} does not resolve")
        rec = {"alias": old, "to": new, "basis": basis, "added": _today()}
    else:
        if not basis:
            raise CausalError("an edge needs --basis: file:line, a URL, review, or owner (Chase's words with the "
                              "UTC time)")
        p = parse(line)
        if not effect:
            raise CausalError("an edge needs an EFFECT")
        key = _node_key(effect) if ref_kind(effect) == "path" else resolve(g, effect)["key"]
        if ref_kind(key) == "path" and not g.is_tracked(key):
            raise CausalError(f"{key} is not tracked")
        if _effect_slot(g, key) and not (ref_kind(key) == "path" and _frozen(key, _frozen_set(root))):
            raise CausalError(f"{key} carries its own links; write the line there, not in {EDGES}")
        if p["kind"] == "local":
            raise CausalError(f"{p['ref']} is a local path; link something tracked")
        if p["kind"] in NODE_REFS and _state(g, p["ref"], p["kind"]) != "ok":
            raise CausalError(f"{p['ref']} does not resolve")
        if p["kind"] == "path" and not g.is_tracked(p["path"]):
            raise CausalError(f"{p['path']} is not tracked")
        if not _fits(p["rel"], p["kind"], p["path"]):
            raise CausalError(f"{p['rel']} cannot point to a {p['kind']} reference ({p['ref']})")
        if g.public:
            leak = _public_leak(g, {"parsed": p, "kind": p["kind"], "cause": _node_key(p["ref"], p["kind"])})
            if leak:
                raise CausalError(f"refused in a public repository: {leak}")
        for e in g.causes(key):
            if e["via"] == "overlay" and e.get("parsed", {}).get("ref") == p["ref"] and e["rel"] == p["rel"]:
                raise CausalError(f"{key} already has {p['rel']} {p['ref']} in {EDGES}")
        rec = {"effect": key, "line": line, "basis": basis, "added": _today()}
        if by:
            rec["by"] = by
    if not dry_run:
        _append_edges(root, rec)
    out = {"written": not dry_run, "record": rec, "file": EDGES}
    if "effect" in rec:
        out["sha8"] = edge_sha8(rec)
    return out


def _find_runrecord(root, token):
    for rel in (f"{RUNS_DIR}/{token}.json", f"{WORK}/runs/{token}.json"):
        path = Path(root) / rel
        if path.is_file():
            try:
                return rel, json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                raise CausalError(f"{rel} is not JSON")
    raise CausalError(f"no run record for token {token} in {RUNS_DIR}/ or {WORK}/runs/")


def add_result(root=ROOT, section=None, from_run=None, rid=None, row=None, write=False):
    """An id and a causal list taken from a run record, for a results entry; with write, put them on the entry
    (the section's last row, or `row`; a dict section takes them itself) and adopt the record into
    docs/causal/runs/ in the same change."""
    rel, rec = _find_runrecord(root, from_run)
    if not _verify_digest(rec):
        raise CausalError(f"{rel}: digest does not match the record")
    lines = list(rec.get("causal") or [])
    if rec.get("token") and not any(x.split(" ", 2)[:2] == ["run", rec["token"]] for x in lines):
        lines.append(f"run {rec['token']}")
    code = rec.get("code") or []
    if code and isinstance(code[0], dict) and code[0].get("commit") and not any(x.startswith("code ") for x in lines):
        lines.append(f"code {code[0]['commit']}")
    for x in lines:
        parse(x)
    text = _read(root, RESULTS)
    if text is None:
        raise CausalError(f"no {RESULTS}")
    data = json.loads(text)
    if section not in data or section in META_SECTIONS:
        raise CausalError(f"{RESULTS} has no results section {section!r}")
    value = data[section]
    if isinstance(value, dict):
        target, new_id = value, None
    else:
        if not value:
            raise CausalError(f"section {section} has no rows; add the row first")
        idx = len(value) - 1 if row is None else row
        if not (0 <= idx < len(value)) or not isinstance(value[idx], dict):
            raise CausalError(f"section {section} has no object row {idx}")
        target = value[idx]
        new_id = rid or target.get("id") or f"{section}/{idx}"
        if not RE_ID.fullmatch(new_id):
            raise CausalError(f"id {new_id!r} must match [a-z0-9][a-z0-9_./-]*")
    out = {"section": section, "id": new_id, "causal": lines, "from": rel, "written": False, "adopted": None}
    if write:
        merged = list(dict.fromkeys(list(target.get("causal") or []) + lines))
        if new_id is not None:
            rebuilt = {"id": new_id, **{k: v for k, v in target.items() if k not in ("id", "causal")},
                       "causal": merged}
            value[value.index(target)] = rebuilt
        else:
            target["causal"] = merged
        _write_text(root, RESULTS, _json_text(data, text))
        out["written"] = True
        if not rel.startswith(RUNS_DIR + "/"):
            dst = f"{RUNS_DIR}/{rec['token']}.json"
            _write_text(root, dst, (Path(root) / rel).read_text(encoding="utf-8"))
            out["adopted"] = dst
    return out


def _claim_label(text):
    low = text.lower()
    for label in LABELS:
        if re.search(r"\b" + re.escape(label.lower()) + r"\b", low):
            return label
    return None


def _claims_doc(root):
    text = _read(root, CLAIMS)
    if text is None:
        return {"schema": CLAIMS_SCHEMA, "claims": []}
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
        raise CausalError(f"{CLAIMS} must hold a list under \"claims\"")
    return data


def _cause_line(g, ref):
    """`source REF sha256:PIN` for a claim cause: r:<id> pinned to its unit_sha256, a docs/evidence path pinned
    to its folder's SHA256SUMS (or the file's sha256)."""
    kind = ref_kind(ref)
    if kind == "result":
        n = g.nodes.get(g.aliases.get(ref, ref), {})
        if n.get("kind") != "result" or not n.get("own"):
            raise CausalError(f"{ref} is not a results unit")
        return f"source {ref} sha256:{n['unit_sha256']}"
    if kind == "path" and _split_path(ref)[0].startswith(EVIDENCE_DIR + "/"):
        p = _split_path(ref)[0]
        if not g.is_tracked(p):
            raise CausalError(f"{p} is not tracked")
        pin = _hash_path(g, p)
        return f"source {ref} sha256:{pin}" if pin else f"source {ref}"
    raise CausalError(f"a claim cause is r:<id> or a docs/evidence path, not {ref!r}")


def add_claim(root=ROOT, item=None, quote=None, label=None, causes=(), cid=None, repin=None, write=False,
              graph=None):
    """A docs/causal/claims.json entry for README Novel findings item ITEM (its number): the quote must occur
    exactly once in the item, the label is from NOVELTY.md, and each cause is pinned. With repin=c:<id>, rewrite
    that claim's pins to the cited units' current unit_sha256, printing old and new for review."""
    g = graph or load(root)
    data = _claims_doc(root)
    if repin:
        cid_ = repin[2:] if repin.startswith("c:") else repin
        entry = next((c for c in data["claims"] if c.get("id") == cid_), None)
        if entry is None:
            raise CausalError(f"{repin} is not a claim in {CLAIMS}")
        changes, lines = [], []
        for line in entry.get("causal") or []:
            p = parse(line)
            if p["kind"] == "result":
                n = g.nodes.get(g.aliases.get(p["ref"], p["ref"]), {})
                new = n.get("unit_sha256")
                if new and new != p["pin"]:
                    changes.append({"cause": p["ref"], "old": p["pin"], "new": new,
                                    "unit": {k: v for k, v in (n.get("entry") or {}).items() if k != "causal"}})
                    line = f"source {p['ref']} sha256:{new}"
            lines.append(line)
        entry["causal"] = lines
        if write and changes:
            _write_text(root, CLAIMS, json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        return {"claim": f"c:{cid_}", "changes": changes, "written": bool(write and changes)}
    text = _read(root, README) or ""
    items = {o: t for ln, o, t in (_readme_items(text) or [])}
    if item not in items:
        raise CausalError(f"{README} Novel findings has no item {item}")
    if not quote or items[item].count(quote) != 1:
        raise CausalError(f"the quote must occur exactly once in item {item}")
    if label not in LABELS:
        raise CausalError(f"label must be one of {', '.join(LABELS)}")
    if not causes:
        raise CausalError("a claim needs at least one --cause (r:<id> or a docs/evidence path)")
    lines = [_cause_line(g, c) for c in causes]
    cid = cid or "-".join(re.findall(r"[a-z0-9]+", quote.lower())[:6]) or f"finding-{item}"
    have = {c.get("id") for c in data["claims"]}
    if cid in have:
        raise CausalError(f"claim id {cid} is taken")
    if not RE_CLAIM.fullmatch(f"c:{cid}"):
        raise CausalError(f"claim id {cid!r} must be lowercase letters, digits, '.', '_' or '-'")
    entry = {"id": cid, "readme_item": item, "quote": quote, "label": label, "causal": lines}
    if write:
        data["claims"].append(entry)
        _write_text(root, CLAIMS, json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return {"claim": f"c:{cid}", "entry": entry, "written": write}


def _set_lines(data, unit_lines):
    """Add causal lines to results units in place: {(section, index or None): [lines]}; returns how many added."""
    added = 0
    for (section, index), lines in unit_lines.items():
        target = data[section] if index is None else data[section][index]
        have = list(target.get("causal") or [])
        new = [x for x in lines if x not in have]
        if new:
            target["causal"] = have + new
            added += len(new)
    return added


def _pass_joins(g, out, limit):
    """Core joins: an unpinned preregistration path a results unit cites, which exactly one freeze lists with its
    freezing commit, becomes `prereg PATH@COMMIT` on that unit."""
    try:
        freezes = stale.load_freezes(g.root) or []
    except stale.StaleError:
        freezes = []
    by_prereg = {}
    for f in freezes:
        if isinstance(f.get("prereg"), str) and isinstance(f.get("freezing_commit"), str):
            by_prereg.setdefault(f["prereg"], set()).add(f["freezing_commit"])
    lines = {}
    for key, n in g.nodes.items():
        if n.get("kind") != "result" or not n.get("own"):
            continue
        for e in g.causes(key, strong=True):
            if e["rel"] == "prereg" and e["kind"] == "path" and not (e["pin"] or e["at"]):
                commits = by_prereg.get(e["cause"], set())
                if len(commits) == 1:
                    line = f"prereg {e['cause']}@{next(iter(commits))[:12]}"
                    lines.setdefault((n["section"], n.get("index")), []).append(line)
                    out["changes"].append({"node": key, "line": line, "basis": f"{stale.FREEZES} freezing_commit"})
        if len(out["changes"]) >= limit:
            break
    return lines


def _pass_frozen(g, out, limit, write):
    """Frozen effect ends, in edges.jsonl: a frozen preregistration whose requirement is still missing, named by
    exactly one freeze that has a spec, gets `spec SPEC` with that freeze as its basis."""
    try:
        freezes = stale.load_freezes(g.root) or []
    except stale.StaleError:
        freezes = []
    reqs = requirements(g)
    by_prereg = {}
    for f in freezes:
        if isinstance(f.get("prereg"), str):
            by_prereg.setdefault(f["prereg"], []).append(f)
    for prereg, fs in sorted(by_prereg.items()):
        r = reqs.get(prereg)
        if not r or not r["missing"] or len(fs) != 1 or not isinstance(fs[0].get("spec"), str):
            continue
        if not g.is_tracked(fs[0]["spec"]):
            continue
        rec = {"effect": prereg, "line": f"spec {fs[0]['spec']}", "basis": f"{stale.FREEZES} {fs[0]['id']}",
               "added": _today(), "by": "backfill --pass frozen"}
        out["changes"].append(rec)
        if write:
            _append_edges(g.root, rec)
        if len(out["changes"]) >= limit:
            break


def backfill(root=ROOT, pass_name="ids", write=False, limit=200, again=False, reason=None, graph=None):
    """One named, mechanical backfill pass (PASSES): ids (results ids on list rows), decision-ids (the DECISIONS
    Id column), joins (single-candidate joins written as causal lines), claims (claims.json entries for README
    findings), frozen (edges.jsonl for frozen effect ends). A dry run unless write; never reads prose to invent a
    link; stops at `limit`. A pass with write records itself in the baseline's pass ledger; running a recorded pass
    again needs again=True and a reason, which is recorded too. Returns {pass, write, changes, review, exit}."""
    if pass_name not in PASSES:
        raise CausalError(f"unknown pass {pass_name!r}; one of {', '.join(PASSES)}")
    g = graph or load(root)
    ledger = ((g.baseline or {}).get("passes") or {})
    out = {"pass": pass_name, "write": write, "changes": [], "review": [], "exit": EXIT_OK}
    if pass_name in ledger and not again:
        out.update(exit=EXIT_ATTENTION, recorded=ledger[pass_name],
                   message=f"pass {pass_name} already ran ({ledger[pass_name].get('utc')}); its leftovers stay in "
                           "the baseline. Run it again only with --again --reason TEXT")
        return out
    if again and not reason:
        raise CausalError("--again needs --reason")
    if write and g.baseline is None:
        raise CausalError(f"no {BASELINE}: create it with python -m kit causal ratchet --write first, so the pass "
                          "ledger has a home")
    if pass_name == "ids" and g.results_data is not None:
        data = json.loads(g.results_text)
        for key, n in sorted(g.nodes.items(), key=lambda kv: _sort_key(kv[0])):
            if n.get("kind") != "result" or not n.get("own") or n.get("index") is None or n["entry"].get("id"):
                continue
            if len(out["changes"]) >= limit:
                break
            rid = key[2:].split("~", 1)[0]
            out["changes"].append({"where": n["where"], "id": rid})
            row = data[n["section"]][n["index"]]
            data[n["section"]][n["index"]] = {"id": rid, **row}
        if write and out["changes"]:
            _write_text(root, RESULTS, _json_text(data, g.results_text))
    elif pass_name == "decision-ids":
        text = _read(root, DECISIONS)
        if text is not None:
            explicit, rows = _decision_rows(text)
            out["changes"] = [] if explicit else [{"line": ln, "id": f"D{i}"} for i, (ln, _, _, _) in
                                                  enumerate(rows, 1)]
            if write and not explicit and rows:
                lines = text.splitlines(keepends=True)
                first = rows[0][0] - 1
                header, sep = first - 2, first - 1
                lines[header] = "| Id " + lines[header]
                lines[sep] = "| --- " + lines[sep]
                for i, (ln, _, _, _) in enumerate(rows, 1):
                    lines[ln - 1] = f"| D{i} " + lines[ln - 1]
                _write_text(root, DECISIONS, "".join(lines))
    elif pass_name == "joins":
        lines = _pass_joins(g, out, limit)
        fn = HOOKS.passes.get("joins")
        if fn:
            for k, v in (fn(g, out, write, limit) or {}).items():
                lines.setdefault(k, []).extend(v)
        if write and lines and g.results_data is not None:
            data = json.loads(g.results_text)
            if _set_lines(data, lines):
                _write_text(root, RESULTS, _json_text(data, g.results_text))
    elif pass_name == "claims":
        text = _read(root, README) or ""
        items = _readme_items(text) or []
        doc = _claims_doc(root)
        have = {c.get("id") for c in doc["claims"]}
        cites = {}
        for k, n in g.nodes.items():
            if n.get("kind") == "result" and n.get("own"):
                for e in g.causes(k, strong=True):
                    if e["rel"] == "source" and e["kind"] == "path":
                        cites.setdefault(e["cause"], set()).add(k)
        for key, n in sorted(g.nodes.items(), key=lambda kv: _sort_key(kv[0])):
            if n.get("kind") != "finding" or not n.get("own") or len(out["changes"]) >= limit:
                continue
            item = next((t for ln, o, t in items if o == n["ordinal"]), "")
            m = re.search(r"\*\*(.+?)\*\*", item)
            quote = (m.group(1) if m else re.sub(r"^(?:- |\d+\. )", "", item))[:200]
            if item.count(quote) != 1:
                quote = item[:200]
            causal_lines = []
            for target in RE_MD_LINK.findall(item):
                ref = target if target.startswith("https://") else _rel_link(README, target)
                if not ref or ref_kind(ref) != "path":
                    continue
                p = _split_path(ref)[0]
                try:
                    if p.startswith(EVIDENCE_DIR + "/"):
                        causal_lines.append(_cause_line(g, p))
                    elif len(cites.get(p, ())) == 1:
                        causal_lines.append(_cause_line(g, next(iter(cites[p]))))
                except CausalError:
                    continue
            label = _claim_label(item)
            words = re.findall(r"[a-z0-9]+", quote.lower())[:6]
            cid = "-".join(words) or f"finding-{n['ordinal']}"
            while cid in have:
                cid += "-2"
            entry = {"id": cid, "readme_item": n["ordinal"], "quote": quote, "label": label,
                     "causal": list(dict.fromkeys(causal_lines))}
            if label is None or not causal_lines:
                out["review"].append({"node": key, "proposal": entry,
                                      "why": "no NOVELTY label in the item" if label is None else
                                      "no single results unit or evidence holds its number"})
                continue
            have.add(cid)
            out["changes"].append(entry)
        if write and out["changes"]:
            doc["claims"] += out["changes"]
            _write_text(root, CLAIMS, json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    elif pass_name == "frozen":
        _pass_frozen(g, out, limit, write)
        fn = HOOKS.passes.get("frozen")
        if fn:
            fn(g, out, write, limit)
    if write:
        b = json.loads(_read(root, BASELINE))
        b.setdefault("passes", {})[pass_name] = {
            "commit": ((g.git.run("rev-parse", "--short=12", "HEAD") or "").strip() or None) if g.git.ok else None,
            "utc": _now().strftime("%Y-%m-%dT%H:%M:%SZ"), "wrote": len(out["changes"]), "reason": reason}
        _write_text(root, BASELINE, json.dumps(b, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    return out


def _baseline_counts(listed, reqs):
    """{"by_kind", "by_gap", "pairs"} over the baseline's gap lists."""
    by_kind, by_gap = {}, {}
    for k, miss in listed.items():
        kind = (reqs.get(k) or {}).get("kind") or k.split(":", 1)[0]
        by_kind[kind] = by_kind.get(kind, 0) + 1
        for m in miss:
            by_gap[m] = by_gap.get(m, 0) + 1
    return {"by_kind": dict(sorted(by_kind.items())), "by_gap": dict(sorted(by_gap.items())),
            "pairs": sum(len(v) for v in listed.values())}


def ratchet(root=ROOT, write=False, repin=False, reason=None, graph=None):
    """Create the baseline (when absent) or shrink it: drop gaps now satisfied and nodes now gone, never add.
    With repin and a reason, rebuild it from the tree as it stands (the repository test's INITIAL_SHA256 and
    BASELINE_MAX then change in the same commit), keeping the pass ledger and recording the reason."""
    g = graph or load(root)
    reqs = requirements(g)
    current = {k: sorted(r["missing"]) for k, r in reqs.items()
               if r["missing"] and r["enforceable"] and r["kind"] != "claim"}
    if repin and not reason:
        raise CausalError("--repin needs --reason")
    if g.baseline is None or repin:
        legacy = {}
        for k, n in g.nodes.items():
            if not n.get("own"):
                continue
            if n["kind"] == "result" and n.get("index") is not None and not n["entry"].get("id"):
                legacy[k] = n["unit_sha256"]
            elif n["kind"] == "finding":
                legacy[k] = n["fingerprint"]
        initial = {"gaps": current, "legacy": legacy}
        data = {"schema": BASELINE_SCHEMA, "made": _today(),
                "commit": ((g.git.run("rev-parse", "HEAD") or "").strip() or None) if g.git.ok else None,
                "initial_sha256": _sha256_bytes(_canonical(initial)), "keys": len(current),
                "counts": _baseline_counts(current, reqs), "gaps": current, "legacy": legacy,
                "ambiguous": sorted(set(g.ambiguous)), "initial": initial,
                "passes": (g.baseline or {}).get("passes") or {}}
        if repin:
            data["made"] = (g.baseline or {}).get("made") or data["made"]
            data["repins"] = list((g.baseline or {}).get("repins") or []) + [
                {"utc": _now().strftime("%Y-%m-%dT%H:%M:%SZ"), "reason": reason,
                 "old_initial_sha256": (g.baseline or {}).get("initial_sha256")}]
        if write:
            _write_text(root, BASELINE, json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        return {"created": g.baseline is None, "repinned": bool(repin), "written": write, "keys": len(current),
                "legacy": len(legacy), "initial_sha256": data["initial_sha256"], "counts": data["counts"]}
    b = g.baseline
    dropped, shrunk, kept = [], [], {}
    for k, listed in b.get("gaps", {}).items():
        target = g.aliases.get(k, k)
        if target not in reqs:
            dropped.append(k)
            continue
        actual = set(reqs[target]["missing"])
        keep = sorted(set(listed) & actual)
        if not keep:
            dropped.append(k)
        else:
            if len(keep) < len(listed):
                shrunk.append(k)
            kept[k] = keep
    if write and (dropped or shrunk):
        b["gaps"] = kept
        b["keys"] = len(kept)
        b["counts"] = _baseline_counts(kept, reqs)
        _write_text(root, BASELINE, json.dumps(b, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    return {"created": False, "written": write and bool(dropped or shrunk), "dropped": sorted(dropped, key=_sort_key),
            "shrunk": sorted(shrunk, key=_sort_key), "keys": len(kept),
            "pairs": sum(len(v) for v in kept.values())}


# ---------------------------------------------------------------- CLI

def _common(a):
    a.add_argument("--root", default=str(ROOT), help="repository root (default: this checkout)")
    a.add_argument("--json", action="store_true", help="print JSON (the dict the Python API returns)")


def _csv(text):
    return tuple(k.strip() for k in (text or "").split(",") if k.strip())


def add_arguments(p):
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("why", help="walk back from a node to its causes; an ambiguous REF lists candidates")
    a.add_argument("ref", help="a node: r:ID, c:ID, D<n>, tool:ID, a path, an app id, a token, a commit, or fuzzy "
                               "text such as '2026-10-20 row' or a short hash")
    a.add_argument("--depth", type=int, default=3, help="how many links to walk (default 3)")
    a.add_argument("--kind", help="comma-separated cause groups to keep: decision,approval,spec,prereg,freeze,run,"
                                  "ledger,code,inputs,control,source,supersedes")
    a.add_argument("--strong", action="store_true", help="only hash and typed edges")
    a.add_argument("--runs", action="append", default=[], help="a run folder an extension may read (repeatable)")
    _common(a)
    a = actions.add_parser("effects", help="walk forward from a node, or list what is downstream of changes")
    a.add_argument("ref", nargs="?", help="a node, as for why")
    a.add_argument("--depth", type=int, default=3, help="how many links to walk (default 3)")
    a.add_argument("--since", metavar="REV", help="everything downstream of the files changed since REV")
    _common(a)
    a = actions.add_parser("show", help="one node, its edges in and out, and how each requirement is met")
    a.add_argument("ref", help="a node, as for why")
    _common(a)
    a = actions.add_parser("gaps", help="every (node, missing relation) pair")
    a.add_argument("--kind", help=f"comma-separated node kinds: {','.join(GAP_KINDS)}")
    a.add_argument("--need", help="comma-separated missing relations to keep, such as control,prereg")
    a.add_argument("--new", action="store_true", help="only pairs absent from the baseline")
    a.add_argument("--suggest", action="store_true", help="attach weak suggestions (hint edges) to each gap")
    a.add_argument("--counts", action="store_true", help="print only the counts, with none: use per relation")
    a.add_argument("--limit", type=int, default=25, help="rows to print (default 25; 0 prints all)")
    _common(a)
    a = actions.add_parser("check", help="the check rule: E1 to E17 fail, A1 to A10 need a look")
    a.add_argument("--new", action="store_true", help="only what was added after the cutover (fast, for hooks)")
    a.add_argument("--only", action="append", default=[], choices=RULES, help="report only this rule (repeatable)")
    a.add_argument("--strict", action="store_true", help="attention fails too (exit 1)")
    a.add_argument("--since", help="also list results units changed since this revision (A3)")
    a.add_argument("--network", action="store_true", help="confirm commits this clone lacks with gh api (read only)")
    a.add_argument("--no-hash", action="store_true", help="skip pin hashing and record rechecks")
    a.add_argument("--runs", action="append", default=[], help="a run folder an extension may read (repeatable)")
    _common(a)
    a = actions.add_parser("parse", help="check one link line")
    a.add_argument("line", help="'REL REF [PIN]'")
    a.add_argument("--json", action="store_true", help="print JSON")
    a = actions.add_parser("link", help=f"append an edge, alias or retraction to {EDGES}")
    a.add_argument("effect", nargs="?", help="the effect end: a frozen prereg, spec, log or evidence path, a "
                                             "decision, a commit or a run")
    a.add_argument("line", nargs="?", help="the link line, 'REL REF [PIN]'")
    a.add_argument("--basis", help="path:line, a URL, review, or owner (Chase's words with the UTC time)")
    a.add_argument("--alias", nargs=2, metavar=("OLD", "NEW"), help="record that OLD now resolves to NEW")
    a.add_argument("--retract", metavar="SHA8", help=f"retract the edge of {EDGES} whose sha8 this is")
    a.add_argument("--reason", help="why an edge is retracted")
    a.add_argument("--by", help="who adds the edge (kept in the record)")
    a.add_argument("--dry-run", action="store_true", help="print the record, write nothing")
    _common(a)
    a = actions.add_parser("add", help="a results unit's id and links from a run record, or a README claim")
    a.add_argument("what", choices=("result", "claim"), help="what to add")
    a.add_argument("item", nargs="?", type=int, help="claim: the Novel findings item number")
    a.add_argument("--section", help="result: the results section")
    a.add_argument("--from-run", metavar="TOKEN", help="result: the run record's token")
    a.add_argument("--row", type=int, help="result: the row to fill (default the section's last row)")
    a.add_argument("--id", help="result: the id (default SECTION/INDEX); claim: the claim id")
    a.add_argument("--quote", help="claim: text that occurs exactly once in the item")
    a.add_argument("--label", choices=LABELS, help="claim: its NOVELTY.md label")
    a.add_argument("--cause", action="append", default=[], metavar="REF",
                   help="claim: r:<id> or a docs/evidence path (repeatable); pinned automatically")
    a.add_argument("--repin", metavar="c:ID", help="claim: re-pin a reviewed claim to its units' current hashes")
    a.add_argument("--write", action="store_true", help="write the change (default: dry run)")
    _common(a)
    a = actions.add_parser("backfill", help="one named, bounded, recorded backfill pass")
    a.add_argument("--pass", dest="pass_name", required=True, choices=PASSES, help="the pass to run")
    a.add_argument("--limit", type=int, default=200, help="stop after this many changes (default 200)")
    a.add_argument("--write", action="store_true", help="write the changes and record the pass (default: dry run)")
    a.add_argument("--again", action="store_true", help="run a pass the ledger already records (needs --reason)")
    a.add_argument("--reason", help="why the pass runs again (recorded)")
    _common(a)
    a = actions.add_parser("ratchet", help=f"create or shrink {BASELINE}")
    a.add_argument("--write", action="store_true", help="write the baseline (default: dry run)")
    a.add_argument("--repin", action="store_true", help="rebuild the baseline from the tree (needs --reason)")
    a.add_argument("--reason", help="why the baseline is rebuilt (recorded)")
    _common(a)
    for fn in HOOKS.arguments:
        fn(actions)


def _print(args, obj, text):
    if getattr(args, "json", False):
        print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
    else:
        print(text)


def _fmt_check(rep):
    lines = [f"kit causal check: {rep['errors']} errors, {rep['attention']} need a look"]
    for name, c in rep["carriers"].items():
        lines.append(f"  {c['status']:<8} {name:<12} {c.get('count', 0):>5}  {c.get('why', '')}")
    for f in rep["findings"]:
        lines.append(f"{f['rule']:<4} {f['level']:<9} {f['where']}: {f['text']}")
    lines += [f"info {x}" for x in rep["info"]]
    return "\n".join(lines)


def _fmt_walk(out, key):
    lines = [f"{out['node']} ({out['kind']})"]
    for group, items in out.get(key, {}).items():
        lines.append(f"  {group}:")
        for it in items:
            extra = f" [{it.get('state')}]" if it.get("state") else ""
            target = it.get("ref") or it.get("node")
            lines.append(f"    {'  ' * (it.get('depth', 1) - 1)}{it['rel']} {target}{extra} ({it['cls']}, "
                         f"{it['via']}, {it['carrier']})")
    for rel, how in (out.get("met") or {}).items():
        lines.append(f"  met {rel}: {how}")
    if out.get("missing"):
        lines.append(f"  missing: {', '.join(out['missing'])}")
    for s in out.get("superseded_by", []):
        lines.append(f"  superseded by: {s['node']} ({s['rel']})")
    if out.get("mentioned_in_handoff"):
        lines.append(f"  mentioned in {stale.HANDOFF} lines: {', '.join(map(str, out['mentioned_in_handoff']))}")
    return "\n".join(lines)


def _fmt_gaps(out, limit, counts_only):
    c = out["counts"]
    text = [f"{c['nodes']} nodes, {c['pairs']} missing links ({c['old_pairs']} at the cutover, {c['new_pairs']} new, "
            f"{c['provisional']} not enforced yet), {c['ambiguous']} ambiguous joins",
            "by kind: " + ", ".join(f"{k} {v}" for k, v in sorted(c["by_kind"].items())),
            "by gap: " + ", ".join(f"{k} {v}" for k, v in sorted(c["by_gap"].items())),
            "none: lines: " + (", ".join(f"{k} {v}" for k, v in sorted(c["none_lines"].items())) or "none")]
    if counts_only:
        return "\n".join(text)
    rows = out["gaps"] if not limit else out["gaps"][:limit]
    for r in rows:
        text.append(f"  {r['node']}: {', '.join(r['missing'])}{'' if r['old'] else '  (new)'}")
        for sgg in r.get("suggest", []):
            text.append(f"      weak: {sgg['line']} ({sgg['where']})")
    if limit and len(out["gaps"]) > limit:
        text.append(f"  ... {len(out['gaps']) - limit} more (--limit 0 prints all)")
    return "\n".join(text)


def run(args):
    root = Path(getattr(args, "root", None) or ROOT)
    action = args.action
    try:
        if action in HOOKS.commands:
            return HOOKS.commands[action](args)
        if action == "parse":
            p = parse(args.line)
            if p["kind"] == "none":
                p["none_reasons"] = list(NONE.get(p["rel"], ()))
            _print(args, p, f"ok: {p['rel']} -> {p['ref']} ({p['kind']})" + (f" pin {p['pin'][:12]}..." if p["pin"]
                                                                              else ""))
            return EXIT_OK
        if action == "check":
            g = load(root, runs=args.runs)
            for name in ("public_root",):
                if getattr(args, name, None):
                    setattr(g, name, getattr(args, name))
            rep = check(root, only=tuple(args.only), strict=args.strict, network=args.network,
                        hash_pins=not args.no_hash, since=args.since, new_only=args.new, graph=g)
            _print(args, rep, _fmt_check(rep))
            return rep["exit"]
        if action == "link":
            if args.retract is None and args.alias is None and not (args.effect and args.line):
                print("kit causal link: give EFFECT and LINE, or --alias OLD NEW, or --retract SHA8", file=sys.stderr)
                return EXIT_USAGE
            out = link(root, args.effect, args.line, args.basis, dry_run=args.dry_run,
                       alias=tuple(args.alias) if args.alias else None, retract=args.retract, reason=args.reason,
                       by=args.by)
            _print(args, out, f"{'wrote' if out['written'] else 'would write'} to {EDGES}: "
                              f"{json.dumps(out['record'], ensure_ascii=False)}")
            return EXIT_OK
        if action == "add":
            if args.what == "result":
                if not (args.section and args.from_run):
                    print("kit causal add result: give --section and --from-run", file=sys.stderr)
                    return EXIT_USAGE
                out = add_result(root, args.section, args.from_run, rid=args.id, row=args.row, write=args.write)
            else:
                if not args.repin and args.item is None:
                    print("kit causal add claim: give ITEM with --quote, --label and --cause, or --repin c:ID",
                          file=sys.stderr)
                    return EXIT_USAGE
                out = add_claim(root, args.item, args.quote, args.label, tuple(args.cause), cid=args.id,
                                repin=args.repin, write=args.write)
            _print(args, out, json.dumps(out, indent=1, ensure_ascii=False))
            return EXIT_OK
        if action == "backfill":
            out = backfill(root, args.pass_name, write=args.write, limit=args.limit, again=args.again,
                           reason=args.reason)
            text = out.get("message") or (f"{'wrote' if args.write else 'dry run'}: pass {out['pass']}, "
                                          f"{len(out['changes'])} changes, {len(out['review'])} to review")
            _print(args, out, text)
            return out["exit"]
        if action == "effects" and args.since:
            out = impact(root, args.since)
            _print(args, out, "\n".join([f"since {out['since']}:"] + [f"  {r['change']:<8} {r['key']}  effects: "
                                         f"{', '.join(sorted(r['effects'])) or 'none'}" for r in out["results"]] +
                                        [f"  file     {f['path']}  nodes: {', '.join(f['nodes'][:6])}  effects: "
                                         f"{', '.join(sorted(f['effects'])) or 'none'}" for f in out["files"]]))
            return EXIT_OK
        g = load(root, runs=getattr(args, "runs", ()))
        if action in ("why", "effects", "show"):
            if not args.ref:
                print(f"kit causal {action}: give REF", file=sys.stderr)
                return EXIT_USAGE
            try:
                resolve(g, args.ref)
            except CausalError as exc:
                if getattr(exc, "candidates", None):
                    _print(args, {"ambiguous": args.ref, "candidates": exc.candidates},
                           "\n".join([f"{args.ref!r} is ambiguous; candidates:"] + [f"  {c}" for c in exc.candidates]))
                    return EXIT_ATTENTION
                raise
        if action == "why":
            out = why(g, args.ref, depth=args.depth, kinds=_csv(args.kind), strong=args.strong)
            _print(args, out, _fmt_walk(out, "causes"))
        elif action == "effects":
            out = effects(g, args.ref, depth=args.depth)
            _print(args, out, _fmt_walk(out, "effects"))
        elif action == "show":
            out = show(g, args.ref)
            _print(args, out, json.dumps(out, indent=1, ensure_ascii=False, default=str))
        elif action == "gaps":
            out = gaps(g, kinds=_csv(args.kind), need=_csv(args.need), new=args.new, suggest=args.suggest)
            if args.json and args.counts:
                out = {"counts": out["counts"]}
            _print(args, out, _fmt_gaps(out, args.limit, args.counts))
        elif action == "ratchet":
            out = ratchet(root, write=args.write, repin=args.repin, reason=args.reason, graph=g)
            _print(args, out, json.dumps(out, indent=1, ensure_ascii=False))
        return EXIT_OK
    except CausalError as exc:
        print(f"kit causal: {exc}", file=sys.stderr)
        return EXIT_FAIL


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit causal", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(p)
    return run(p.parse_args(argv))


if importlib.util.find_spec("kit.causal_ext") is not None:     # Scrolls-private's extractors and rules
    from kit import causal_ext  # noqa: E402,F401


if __name__ == "__main__":
    sys.exit(main())
