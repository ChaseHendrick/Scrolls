"""Run records: one provenance record per run, carrying the causal links the run was launched under
(python -m kit runrecord).

A run record is a kit provenance record (schema 1: run, operator, machine, started_utc, finished_utc, code,
models, inputs, outputs, note) with these fields added, all covered by its digest:

  kind               "run"
  runrecord_schema   1
  token              the run token, YYYYMMDDTHHMMSSZ with an optional -slug; also the file name
  tool               what ran
  argv               the command line, when known
  settings_digest    sha256 of the canonical JSON of the settings, or null
  exit_code          the run's exit code (1 when a Python block raised)
  public             true only for a run on public data that may be adopted in public Scrolls
  causal             link lines (`REL REF [PIN]`, kit causal's grammar): the decision, spec, preregistration,
                     control and inputs the run was launched under (and, where a repository keeps them, its
                     approval), plus `run ap-...` for each Modal app it started
  by_reference       [{url, sha256 or null, why}] for inputs too large or too remote to hash (and outputs past
                     the hash budget)
  parent             the token of the run this one ran inside (KIT_RUN_TOKEN, set by `wrap` for its command), or
                     null
  env                {python, platform, torch (when importable without a new dependency)}

`start` validates the links (a reference that does not resolve, a preregistration pin that differs from its live
freeze, or, with --public, any private or local reference is refused) and writes work/causal/runs/TOKEN.open.json;
`finish` fingerprints the outputs (at most HASH_BUDGET bytes in all; anything past it is listed by reference) and
writes work/causal/runs/TOKEN.json; `wrap` does both around a command and writes the record even when the command
fails; `adopt` copies a finished record into docs/causal/runs/, where kit causal reads it; `check` verifies records.
`attach(record, lines)` adds causal lines to any provenance or training record and recomputes its digest.

A run record says what ran under which links. It does not say a result is right, and it never shows that a change
caused a gain: that needs a matched null arm. Keep this file byte-identical in Scrolls and Scrolls-private.
Standard library only.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from kit import causal, provenance

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = 1
WORK_RUNS = "work/causal/runs"
ADOPTED = causal.RUNS_DIR
HASH_BUDGET = 256 << 20
EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2
PRIVATE_KINDS = ("approval", "freeze", "app", "local", "public")
PARENT_ENV = "KIT_RUN_TOKEN"


class RunRecordError(ValueError):
    """A run record request is refused or a record is malformed; the CLI prints it and exits 1."""


def token(slug=None, now=None):
    """A run token: the UTC time as YYYYMMDDTHHMMSSZ, with -slug when given."""
    now = now or datetime.now(timezone.utc)
    t = now.strftime("%Y%m%dT%H%M%SZ")
    if slug:
        if not causal.RE_TOKEN.fullmatch(f"{t}-{slug}"):
            raise RunRecordError(f"slug {slug!r} must be lowercase letters, digits and hyphens")
        t = f"{t}-{slug}"
    return t


def _digest(record):
    return hashlib.sha256(provenance.canonical(record)).hexdigest()


def attach(record, lines):
    """A copy of a provenance or training record with these causal lines added (each checked with kit causal's
    grammar) and its digest recomputed over everything, as trainrecord and provenance build it."""
    lines = list(lines)
    for line in lines:
        causal.parse(line)
    out = {k: v for k, v in record.items() if k != "digest"}
    out["causal"] = list(dict.fromkeys(list(out.get("causal") or []) + lines))
    out["digest"] = _digest(out)
    return out


def _validate(root, lines, public):
    """Refuse links that do not resolve, a prereg pin that differs from its live freeze, and (public) private or
    local references."""
    parsed = [causal.parse(x) for x in lines]
    if public:
        for p in parsed:
            if p["kind"] in PRIVATE_KINDS or p["rel"] in causal.PRIVATE_RELS or "Scrolls-private" in p["ref"]:
                raise RunRecordError(f"refused with --public: {p['rel']} {p['ref']} is a private or local reference")
    for p in parsed:
        if p["kind"] == "local":
            raise RunRecordError(f"{p['ref']} is a local path; link something tracked")
    if not any(p["kind"] in causal.NODE_REFS + ("path",) for p in parsed):
        return parsed
    g = causal.load(root)
    for p in parsed:
        if p["kind"] in causal.NODE_REFS and causal._state(g, p["ref"], p["kind"]) != "ok":
            raise RunRecordError(f"{p['rel']} {p['ref']} does not resolve")
        if p["kind"] == "path" and not g.is_tracked(p["path"]):
            raise RunRecordError(f"{p['path']} is not tracked")
        if p["rel"] == "prereg" and p["kind"] == "path" and p["pin"]:
            for k, n in g.nodes.items():
                if n.get("kind") == "freeze" and n.get("own") and n.get("state") == "live" and \
                        n.get("prereg") == p["path"]:
                    live = g.nodes.get(p["path"], {}).get("pin")
                    if live and live != p["pin"]:
                        raise RunRecordError(f"prereg {p['path']} pin differs from its live freeze {k}")
    return parsed


def _fingerprints(paths, budget):
    """(fingerprints, by_reference): each path hashed with kit provenance while the budget lasts."""
    done, by_ref = [], []
    for p in paths:
        path = Path(p)
        try:
            size = path.stat().st_size if path.is_file() else sum(
                f.stat().st_size for f in path.rglob("*") if f.is_file())
        except OSError as exc:
            raise RunRecordError(f"{p} cannot be read: {exc}")
        if size > budget[0]:
            by_ref.append({"url": str(p), "sha256": None, "why": f"past the {HASH_BUDGET >> 20} MB hash budget"})
            continue
        budget[0] -= size
        try:
            done.append(provenance.fingerprint(str(p)))
        except (OSError, ValueError) as exc:
            raise RunRecordError(f"{p} cannot be fingerprinted: {exc}")
    return done, by_ref


def _by_reference(items):
    out = []
    for item in items:
        url, _, sha = item.partition("@sha256:") if "@sha256:" in item else (item, "", "")
        if sha and not causal.RE_SHA.fullmatch(f"sha256:{sha}"):
            raise RunRecordError(f"by-reference pin must be @sha256:<64 hex>: {item}")
        out.append({"url": url, "sha256": sha or None, "why": "too large or too remote to hash"})
    return out


def start(root=ROOT, tool=None, run_token=None, causal_lines=(), inputs=(), by_reference=(), settings=None,
          public=False, argv=None, note=None):
    """Begin a run: validate its links, fingerprint its inputs and write work/causal/runs/TOKEN.open.json. Returns
    the open record."""
    if not tool:
        raise RunRecordError("a run record needs --tool")
    root = Path(root)
    tok = run_token or token()
    if not causal.RE_TOKEN.fullmatch(tok):
        raise RunRecordError(f"token {tok!r} is not YYYYMMDDTHHMMSSZ with an optional -slug")
    lines = list(causal_lines)
    _validate(root, lines, public)
    budget = [HASH_BUDGET]
    fps, refs = _fingerprints(inputs, budget)
    parent = os.environ.get(PARENT_ENV) or None
    if parent and not causal.RE_TOKEN.fullmatch(parent):
        parent = None
    rec = {"kind": "run", "runrecord_schema": SCHEMA, "token": tok, "tool": tool, "argv": list(argv) if argv else None,
           "settings_digest": hashlib.sha256(causal._canonical(settings)).hexdigest() if settings is not None else None,
           "public": bool(public), "causal": lines, "inputs": fps, "parent": parent if parent != tok else None,
           "env": _env(),
           "by_reference": refs + _by_reference(by_reference), "started_utc": _utc(), "note": note,
           "budget_left": budget[0]}
    path = root / WORK_RUNS / f"{tok}.open.json"
    if path.exists() or (root / WORK_RUNS / f"{tok}.json").exists():
        raise RunRecordError(f"a run record for token {tok} already exists")
    causal._check_writable(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return rec


def _utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env():
    """{python, platform, torch}: the interpreter and platform, and torch's version only when it is already
    imported or importable (no new dependency)."""
    out = {"python": platform.python_version(), "platform": platform.platform(terse=True)}
    torch = sys.modules.get("torch")
    if torch is None:
        try:
            import importlib.util
            if importlib.util.find_spec("torch") is not None:
                import importlib.metadata
                out["torch"] = importlib.metadata.version("torch")
        except Exception:  # noqa: BLE001 - a broken torch install is not the record's problem
            pass
    else:
        out["torch"] = getattr(torch, "__version__", None)
    return out


def finish(root=ROOT, run_token=None, outputs=(), apps=(), exit_code=0):
    """End a run: fingerprint its outputs, add a `run` line for each Modal app, and write the finished record to
    work/causal/runs/TOKEN.json (removing the open file). Returns the record."""
    root = Path(root)
    open_path = root / WORK_RUNS / f"{run_token}.open.json"
    if not open_path.is_file():
        raise RunRecordError(f"no open run record for token {run_token} in {WORK_RUNS}/")
    try:
        opened = json.loads(open_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RunRecordError(f"{open_path} is not JSON: {exc}")
    budget = [opened.pop("budget_left", HASH_BUDGET)]
    outs, refs = _fingerprints(outputs, budget)
    lines = list(opened.get("causal") or [])
    for app in apps:
        if causal.ref_kind(app) != "app":
            raise RunRecordError(f"{app!r} is not a Modal app id (ap-...)")
        if opened.get("public"):
            raise RunRecordError("refused with --public: a Modal app id is a private reference")
        lines.append(f"run {app}")
    base = provenance.build(f"{opened['tool']} {run_token}", str(root), started=opened.get("started_utc"),
                            note=opened.get("note"))
    base.pop("digest")
    rec = dict(base)
    rec.update({k: opened.get(k) for k in ("kind", "runrecord_schema", "token", "tool", "argv", "settings_digest",
                                           "public", "parent", "env")})
    rec["inputs"] = opened.get("inputs") or []
    rec["outputs"] = outs
    rec["exit_code"] = int(exit_code)
    rec["causal"] = list(dict.fromkeys(lines))
    rec["by_reference"] = (opened.get("by_reference") or []) + refs
    rec["digest"] = _digest(rec)
    out = root / WORK_RUNS / f"{run_token}.json"
    causal._check_writable(root, out)
    provenance.write(rec, out)
    open_path.unlink()
    return rec


def adopt(root=ROOT, run_token=None, public=None):
    """Copy a finished record to docs/causal/runs/TOKEN.json, where kit causal reads it. A public repository
    refuses a record that is not public."""
    root = Path(root)
    src = root / WORK_RUNS / f"{run_token}.json"
    if not src.is_file():
        raise RunRecordError(f"no finished run record for token {run_token} in {WORK_RUNS}/")
    rec = json.loads(src.read_text(encoding="utf-8"))
    problems = check_record(rec, name=run_token)
    if problems:
        raise RunRecordError(f"{src}: " + "; ".join(problems))
    public = (not causal._has_ext()) if public is None else public
    if public and rec.get("public") is not True:
        raise RunRecordError("refused in a public repository: the record is not public")
    dst = root / ADOPTED / f"{run_token}.json"
    causal._check_writable(root, dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


def check_record(record, name=None):
    """Problems with one run record: shape, digest, token, schema and causal lines."""
    try:
        problems = provenance.verify(record)
    except ValueError as exc:
        return [str(exc)]
    if record.get("runrecord_schema") != SCHEMA:
        problems.append(f"runrecord_schema {record.get('runrecord_schema')!r}; this check reads {SCHEMA}")
    if not isinstance(record.get("token"), str) or not causal.RE_TOKEN.fullmatch(record["token"]):
        problems.append("token is not YYYYMMDDTHHMMSSZ with an optional -slug")
    elif name is not None and record["token"] != name:
        problems.append(f"token {record['token']} is not the file name {name}")
    for line in record.get("causal") or []:
        try:
            causal.parse(line)
        except causal.CausalError as exc:
            problems.append(str(exc))
    return problems


class Run:
    """A context manager around one run: `with runrecord.run("tool", causal=[...]) as r: ...; r.output(path)`.
    The record is written on exit, with exit_code 1 when the block raised."""

    def __init__(self, tool, argv=None, causal_lines=(), inputs=(), public=False, root=ROOT, run_token=None,
                 settings=None, by_reference=(), note=None):
        self.kw = {"root": root, "tool": tool, "run_token": run_token or token(), "causal_lines": causal_lines,
                   "inputs": inputs, "by_reference": by_reference, "settings": settings, "public": public,
                   "argv": argv, "note": note}
        self.root, self.token, self.outputs, self.apps, self.record = root, self.kw["run_token"], [], [], None

    def __enter__(self):
        start(**self.kw)
        return self

    def output(self, path):
        self.outputs.append(path)

    def app(self, app_id):
        self.apps.append(app_id)

    def __exit__(self, exc_type, exc, tb):
        self.record = finish(self.root, self.token, outputs=self.outputs, apps=self.apps,
                             exit_code=0 if exc_type is None else 1)
        return False


def run(tool, argv=None, causal_lines=(), inputs=(), public=False, **kw):
    """A Run context manager (see Run)."""
    return Run(tool, argv=argv, causal_lines=causal_lines, inputs=inputs, public=public, **kw)


# ---------------------------------------------------------------- CLI

def _start_options(a):
    a.add_argument("--tool", required=True, help="what runs, such as 'kit auc' or 'modal_job.py'")
    a.add_argument("--token", help="the run token (default: now, YYYYMMDDTHHMMSSZ)")
    a.add_argument("--causal", action="append", default=[], metavar="LINE", help="a link line (repeatable)")
    a.add_argument("--input", action="append", default=[], metavar="PATH", help="an input to fingerprint (repeatable)")
    a.add_argument("--by-reference", action="append", default=[], metavar="URL[@sha256:HEX]",
                   help="an input too large or too remote to hash (repeatable)")
    a.add_argument("--settings", help="the run's settings as JSON; the record keeps their digest")
    a.add_argument("--public", action="store_true", help="a public-data run: refuse private and local references")
    a.add_argument("--note", help="a note kept in the record")


def add_arguments(p):
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("start", help=f"begin a run record in {WORK_RUNS}/ and print its token")
    _start_options(a)
    a.add_argument("--root", default=str(ROOT), help="repository root (default: this checkout)")
    a.add_argument("--json", action="store_true", help="print the open record as JSON")
    a = actions.add_parser("finish", help="fingerprint the outputs and write the finished record")
    a.add_argument("token", help="the token start printed")
    a.add_argument("--output", action="append", default=[], metavar="PATH", help="an output (repeatable)")
    a.add_argument("--app", action="append", default=[], metavar="AP", help="a Modal app the run started (repeatable)")
    a.add_argument("--exit-code", type=int, default=0, help="the run's exit code (default 0)")
    a.add_argument("--root", default=str(ROOT), help="repository root (default: this checkout)")
    a.add_argument("--json", action="store_true", help="print the record as JSON")
    a = actions.add_parser("wrap", help="start, run a command, finish (the record is written even when it fails)")
    _start_options(a)
    a.add_argument("--output", action="append", default=[], metavar="PATH", help="an output (repeatable)")
    a.add_argument("--root", default=str(ROOT), help="repository root (default: this checkout)")
    a.add_argument("--json", action="store_true", help="print the record as JSON after the command")
    a.add_argument("command", nargs=argparse.REMAINDER, help="-- COMMAND [ARGS]")
    a = actions.add_parser("adopt", help=f"copy a finished record to {ADOPTED}/")
    a.add_argument("token", help="the record's token")
    a.add_argument("--root", default=str(ROOT), help="repository root (default: this checkout)")
    a.add_argument("--json", action="store_true", help="print JSON")
    a = actions.add_parser("check", help="verify run records: digest, shape, token and causal lines")
    a.add_argument("paths", nargs="+", help="run record files")
    a.add_argument("--json", action="store_true", help="print JSON")


def _settings(text):
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise RunRecordError(f"--settings is not JSON: {exc}")


def cli(args):
    try:
        if args.action == "start":
            rec = start(args.root, args.tool, args.token, args.causal, args.input, args.by_reference,
                        _settings(args.settings), args.public, note=args.note)
            print(json.dumps(rec, indent=2) if args.json else rec["token"])
            return EXIT_OK
        if args.action == "finish":
            rec = finish(args.root, args.token, args.output, args.app, args.exit_code)
            print(json.dumps(rec, indent=2) if args.json else f"{WORK_RUNS}/{args.token}.json {rec['digest']}")
            return EXIT_OK
        if args.action == "wrap":
            cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
            if not cmd:
                print("kit runrecord wrap: give the command after --", file=sys.stderr)
                return EXIT_USAGE
            rec = start(args.root, args.tool, args.token, args.causal, args.input, args.by_reference,
                        _settings(args.settings), args.public, argv=cmd, note=args.note)
            try:
                code = subprocess.run(cmd, env=dict(os.environ, **{PARENT_ENV: rec["token"]})).returncode
            except OSError as exc:
                print(f"kit runrecord wrap: cannot run {cmd[0]}: {exc}", file=sys.stderr)
                code = 127
            done = finish(args.root, rec["token"], args.output, (), code)
            print(json.dumps(done, indent=2) if args.json else f"{WORK_RUNS}/{rec['token']}.json {done['digest']}",
                  file=sys.stderr if not args.json else sys.stdout)
            return code
        if args.action == "adopt":
            dst = adopt(args.root, args.token)
            print(json.dumps({"adopted": str(dst)}) if args.json else str(dst))
            return EXIT_OK
        if args.action == "check":
            report, bad = {}, 0
            for p in args.paths:
                try:
                    rec = json.loads(Path(p).read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    report[p] = [f"unreadable: {exc}"]
                    bad += 1
                    continue
                report[p] = check_record(rec, name=Path(p).stem)
                bad += bool(report[p])
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                for p, problems in report.items():
                    print(f"{'ok  ' if not problems else 'FAIL'} {p}" + "".join(f"\n  {x}" for x in problems))
            return EXIT_FAIL if bad else EXIT_OK
    except (RunRecordError, causal.CausalError) as exc:
        print(f"kit runrecord: {exc}", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_USAGE


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit runrecord", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(p)
    return cli(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
