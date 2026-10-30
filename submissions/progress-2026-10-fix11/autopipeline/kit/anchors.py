"""Known-answer anchors for every benchmark: `python -m kit.anchors`.

  kit anchors list [--benchmark B] [--json]
        the registry, a note of the source repository: one known value per benchmark and case, with its tolerance and source
  kit anchors check ID METRIC=VALUE [METRIC=VALUE ...] [--device D] [--partial] [--json]
        check numbers a run just measured against one anchor
  kit anchors record FILE [--benchmark B] [--device D] [--json]
        check a run's anchor record, {"anchors": {ID: {METRIC: VALUE}}}: every metric the benchmark needs (all of
        its own anchors, and each value it holds a copy of, such as the Transfer Matrix's two forward AUCs) must be
        there and hold, so a run that skipped its anchor fails too
  kit anchors run [--benchmark B] [--json]
        recompute every synthetic anchor (the AUC scorer on a map with a known AUC, and meshqa, switchfix and
        surfbench on kit planted's defects) and check it
  kit anchors copies [--json]
        every copy of a real anchor's value (constants in benchmark scripts, rows of docs/results.json) still
        equals the registry
  kit anchors all [--json]
        run and copies together: the daily routine (docs/routines.json)

Exit codes: 0 every anchor holds, 3 an anchor drifted, is missing or a copy disagrees (the reason goes to stderr in
lines that start with ANCHOR DRIFT), 2 a usage or registry error.

What it is. A benchmark number means something only if the pipeline that made it still reproduces a value known in
advance. Before this registry those values lived as separate constants (in two benches, the Space check and a
label-transfer runner), each with its own tolerance and no
check that they agree. Here each one is registered once: real anchors are numbers this repository measured and
recorded in docs/results.json (ink_9um seed 42's 0.8061 on the PHerc0841 w00 crop is the first), checked whenever a
run produces them (`kit auc --anchor ID`, `kit anchors check` or `record`); synthetic anchors are answers known by
construction, recomputed on every `run` in a few seconds without data. A drift fails loudly instead of shifting
every number after it.

A real anchor on a single-use report surface (PHerc0841 ag405, the ink bar's: kit.autopipe REPORT_ONLY) carries
"never_rescore" with the reason: its value stays registered so `copies` still guards every place that repeats it,
but no run may be checked against it and no benchmark needs it (`check` refuses it, `required` leaves it out), so
the registry never asks anyone to read those labels again.

Every check can fail: a measured value outside the tolerance, a metric that a run did not report, a copy whose
constant differs from the registry and a synthetic tool whose output moves all exit 3 (a test of the source repository makes
each one happen). Real anchors read no data here; this module never downloads, never starts compute and never reads
a reserved or held-out file.
"""

import argparse
import ast
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = Path(__file__).resolve().parent / "data" / "anchors.json"
SCHEMA = "kit-anchors/1"
KINDS = ("real", "synthetic")
OK, DRIFT, MISSING, UNCHECKED = "OK", "DRIFT", "MISSING", "NOT CHECKED"
EXIT_DRIFT, EXIT_USAGE = 3, 2


class AnchorError(ValueError):
    """The registry or a request is malformed."""


class AnchorDrift(RuntimeError):
    """A measured value left its anchor's tolerance, or a required metric is missing."""

    def __init__(self, result):
        self.result = result
        super().__init__("; ".join(drift_lines(result)))


def load(path=None):
    """The registry as {"anchors": {id: anchor}, ...}, validated."""
    path = Path(path or REGISTRY)
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise AnchorError(f"cannot read the anchor registry {path}: {exc}") from exc
    if doc.get("schema") != SCHEMA:
        raise AnchorError(f"{path}: schema {doc.get('schema')!r} is not {SCHEMA}")
    out = {}
    for a in doc.get("anchors", []):
        aid = a.get("id")
        if not aid or aid in out:
            raise AnchorError(f"{path}: anchor id {aid!r} is empty or repeated")
        if a.get("kind") not in KINDS:
            raise AnchorError(f"{aid}: kind must be one of {KINDS}")
        if not a.get("benchmark") or not a.get("source"):
            raise AnchorError(f"{aid}: needs a benchmark and a source")
        m = a.get("metrics")
        if not isinstance(m, dict) or not m:
            raise AnchorError(f"{aid}: needs at least one metric")
        for k, v in m.items():
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                raise AnchorError(f"{aid}: metric {k} must be a finite number")
        for key in ("tol", "tol_same_device"):
            t = a.get(key)
            if t is not None and (not isinstance(t, (int, float)) or t < 0):
                raise AnchorError(f"{aid}: {key} must be a number >= 0")
        if a.get("tol") is None:
            raise AnchorError(f"{aid}: needs tol")
        nr = a.get("never_rescore")
        if nr is not None and (not isinstance(nr, str) or not nr.strip() or a["kind"] != "real"):
            raise AnchorError(f"{aid}: never_rescore is the reason a real anchor is never scored again (a sentence)")
        if a["kind"] == "synthetic" and a.get("runner") not in RUNNERS:
            raise AnchorError(f"{aid}: synthetic anchor needs a runner from {sorted(RUNNERS)}")
        out[aid] = a
    doc = dict(doc)
    doc["anchors"] = out
    return doc


def get(aid, registry=None):
    reg = registry or load()
    if aid not in reg["anchors"]:
        raise AnchorError(f"unknown anchor {aid!r}; anchors: {sorted(reg['anchors'])}")
    return reg["anchors"][aid]


def tolerance(anchor, device=None):
    if device and anchor.get("device") == device and anchor.get("tol_same_device") is not None:
        return float(anchor["tol_same_device"])
    return float(anchor["tol"])


def check(anchor, measured, device=None, partial=False):
    """Compare measured {metric: value} with an anchor. partial: metrics not measured are NOT CHECKED instead of
    MISSING (for a tool that measures only some of an anchor's metrics, such as kit auc without a control)."""
    if isinstance(anchor, str):
        anchor = get(anchor)
    if anchor.get("never_rescore"):
        raise AnchorError(f"{anchor['id']} is never scored again ({anchor['never_rescore']}); it only guards the "
                          "copies of its recorded value (kit anchors copies)")
    tol = tolerance(anchor, device)
    rows, status = [], OK
    for metric, want in anchor["metrics"].items():
        got = measured.get(metric)
        row = {"metric": metric, "anchor": want, "measured": got, "tol": tol}
        if got is None:
            row["status"] = UNCHECKED if partial else MISSING
        else:
            try:
                got = float(got)
            except (TypeError, ValueError):
                got = float("nan")
            delta = got - float(want)
            row["delta"] = round(delta, 10) if math.isfinite(delta) else None
            # a small epsilon so a value exactly on the tolerance (0.8161 against 0.8061 +- 0.01) holds
            row["status"] = OK if math.isfinite(delta) and abs(delta) <= tol + 1e-9 else DRIFT
        if row["status"] in (DRIFT, MISSING):
            status = DRIFT if row["status"] == DRIFT or status == DRIFT else MISSING
        rows.append(row)
    if all(r["status"] == UNCHECKED for r in rows):
        status = MISSING
    return {"id": anchor["id"], "benchmark": anchor["benchmark"], "status": status, "device": device,
            "rows": rows}


def require(aid, measured, device=None, partial=False, registry=None):
    """check() that raises AnchorDrift unless the anchor holds: the call a benchmark makes on every run."""
    res = check(get(aid, registry), measured, device, partial)
    if res["status"] != OK:
        raise AnchorDrift(res)
    return res


def drift_lines(result):
    out = []
    for r in result["rows"]:
        if r["status"] == DRIFT:
            out.append(f"ANCHOR DRIFT {result['id']} {r['metric']}: measured {r['measured']}, anchor {r['anchor']} "
                       f"+- {r['tol']} (delta {r.get('delta')})")
        elif r["status"] == MISSING:
            out.append(f"ANCHOR DRIFT {result['id']} {r['metric']}: not measured by this run (anchor {r['anchor']})")
    if result["status"] == MISSING and not out:
        out.append(f"ANCHOR DRIFT {result['id']}: none of its metrics was measured")
    return out


def required(benchmark, registry=None):
    """{anchor id: metrics a run of `benchmark` must report}: every metric of the anchors whose benchmark it is, and
    the metrics it holds a copy of (a copy's "benchmark" names the run that uses the value)."""
    reg = registry or load()
    out = {}
    for aid, a in reg["anchors"].items():
        if a.get("never_rescore"):
            continue          # a single-use report surface: no run needs it, so none rereads its labels
        if a["benchmark"] == benchmark:
            out[aid] = set(a["metrics"])
        for c in a.get("copies", []):
            if c.get("benchmark") == benchmark:
                out.setdefault(aid, set()).add(c["metric"])
    return out


def check_record(record, benchmark=None, device=None, registry=None):
    """Check a run's {"anchors": {id: {metric: value}}} record. With a benchmark, every anchor metric that benchmark
    needs (required()) must be present; any metric given is checked."""
    reg = registry or load()
    given = record.get("anchors", record) if isinstance(record, dict) else None
    if not isinstance(given, dict):
        raise AnchorError("an anchor record is {\"anchors\": {ID: {METRIC: VALUE}}}")
    device = device or (record.get("device") if isinstance(record, dict) else None)
    need = {}
    if benchmark:
        need = required(benchmark, reg)
        if not need:
            raise AnchorError(f"no anchor is registered for benchmark {benchmark!r}")
    results = []
    for aid in sorted(set(given) | set(need)):
        res = check(get(aid, reg), given.get(aid) or {}, device, partial=True)
        for row in res["rows"]:
            if row["status"] == UNCHECKED and row["metric"] in need.get(aid, ()):
                row["status"] = MISSING
        sts = [r["status"] for r in res["rows"]]
        res["status"] = DRIFT if DRIFT in sts else MISSING if (MISSING in sts or all(s == UNCHECKED for s in sts)) else OK
        results.append(res)
    return results


# ---- synthetic anchors: answers known by construction --------------------------------------------------------

def _run_auc_quarter():
    """kit auc's scorer on a map whose AUC is 3/4 by counting: ink 0.3 and 0.9 against background 0.1 and 0.5
    (pairs won: 0.3 > 0.1, 0.9 > 0.1, 0.9 > 0.5; lost: 0.3 < 0.5), and its mirror, whose AUC is 1/4."""
    import numpy as np
    from . import auc
    pred = np.array([[0.3, 0.9], [0.1, 0.5]], np.float32)
    ink = np.array([[True, True], [False, False]])
    mask = np.ones((2, 2), bool)
    return {"auc": auc.score_array(pred, ink, mask)["auc"],
            "auc_mirror": auc.score_array(1.0 - pred, ink, mask)["auc"]}


def _spiral_plants(families):
    from . import planted as pl
    base = pl.surface(pl.Sheets(), (20, 160))
    return pl, base, {f: pl.plant(base, f) for f in families}


def _run_meshqa():
    import tempfile
    from . import meshqa
    pl, base, plants = _spiral_plants(("clean", "switch", "merger"))
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for fam, p in plants.items():
            rep = meshqa.wind_audit(pl.write(p, Path(tmp) / fam), centre=p.sheets.centre, pitch=p.sheets.pitch,
                                    local_span_tol=0.5, list_limit=5000)
            m = rep["mergers"]
            out[f"{fam}_full_turn"] = m["full_turn"]
            out[f"{fam}_phase_span"] = round(float(rep["component_table"][0]["phase_span"]), 3)
            out[f"{fam}_gate_failed"] = int(bool(rep["gate"]["local_failed"]))
            if fam == "switch":
                rows = m.get("full_turn_rows") or [None, None]
                out["switch_rows_lo"], out["switch_rows_hi"] = rows[0], rows[-1]
                out["switch_mean_dr"] = round(float(m["mean_dr"]), 2)
    return out


def _run_switchfix():
    from . import planted as pl, switchfix as sf
    sheets = pl.Sheets("planes", pitch=14.0, step=4.0, zstep=4.0, z0=10.0)
    vol = pl.prediction_volume(sheets, (140, 180, 100), kmin=0, kmax=1)
    base = pl.surface(sheets, (30, 40))
    out = {}
    for fam in ("clean", "switch", "merger"):
        p = pl.plant(base, fam)
        wrong, _ = pl.masks(p)
        _, arrays = sf.detect(p.xyz, p.valid, sf.ArraySampler(vol), p.xyz[15, 2])
        fl = arrays["flagged"]
        out[f"{fam}_flagged"] = int(fl.sum())
        out[f"{fam}_missed"] = int((wrong & ~fl).sum())
    return out


def _run_surfbench():
    from . import surfbench as sb
    pl, base, plants = _spiral_plants(("clean", "switch", "lens"))
    refs = [sb.Ref(f"k{dk:+d}", i, xyz, v) for i, (dk, (xyz, v)) in enumerate(sorted(pl.neighbours(base).items()))]
    out = {}
    for fam, p in plants.items():
        e = sb.evaluate(p.xyz, p.valid, refs, mode="control")
        out[f"{fam}_dominant_precision"] = e["d4"]["dominant_precision"]
        out[f"{fam}_switch_crossings"] = e["switches"]["switch_crossings"]
    return out


RUNNERS = {"auc_quarter": _run_auc_quarter, "meshqa_planted": _run_meshqa, "switchfix_planted": _run_switchfix,
           "surfbench_planted": _run_surfbench}


def run_synthetic(benchmark=None, registry=None, runners=None):
    """Recompute and check every synthetic anchor (of one benchmark). A runner that cannot run here (numpy or scipy
    missing) is reported SKIPPED, not OK."""
    reg = registry or load()
    runners = runners or RUNNERS
    results = []
    for aid, a in sorted(reg["anchors"].items()):
        if a["kind"] != "synthetic" or (benchmark and a["benchmark"] != benchmark):
            continue
        try:
            measured = runners[a["runner"]]()
        except ImportError as exc:
            results.append({"id": aid, "benchmark": a["benchmark"], "status": "SKIPPED", "reason": str(exc),
                            "rows": []})
            continue
        results.append(check(a, measured))
    return results


# ---- copies of real anchors ----------------------------------------------------------------------------------

def _literal(path, symbol):
    tree = ast.parse(Path(path).read_text(), str(path))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == symbol for t in targets) and node.value is not None:
            return ast.literal_eval(node.value)
    raise AnchorError(f"{path}: no top-level {symbol} = <literal>")


def _follow(obj, path):
    for key in path:
        obj = obj[key]
    return obj


def _results_rows(results, spec):
    section = results.get(spec["section"])
    if not isinstance(section, list):
        raise AnchorError(f"docs/results.json has no list section {spec['section']!r}")
    where = spec["where"]
    return [r for r in section if isinstance(r, dict) and all(r.get(k) == v for k, v in where.items())]


def check_copies(registry=None, root=None):
    """[{id, where, metric, anchor, copy, status}] for every registered copy of a real anchor's value."""
    reg = registry or load()
    root = Path(root or ROOT)
    out, results = [], None
    for aid, a in sorted(reg["anchors"].items()):
        for c in a.get("copies", []):
            f = root / c["file"]
            row = {"id": aid, "where": f"{c['file']}:{c['symbol']}{c.get('path', [])}", "metric": c["metric"],
                   "anchor": a["metrics"][c["metric"]]}
            if not f.is_file():
                row.update(copy=None, status="ABSENT" if c.get("optional") else MISSING)
                out.append(row)
                continue
            try:
                val = _follow(_literal(f, c["symbol"]), c.get("path", []))
            except (AnchorError, KeyError, IndexError, TypeError, SyntaxError, ValueError) as exc:
                row.update(copy=None, status=MISSING, error=str(exc))
                out.append(row)
                continue
            row["copy"] = val
            row["status"] = OK if isinstance(val, (int, float)) and abs(val - row["anchor"]) < 1e-12 else DRIFT
            out.append(row)
        spec = a.get("results")
        if spec:
            if results is None:
                results = json.loads((root / "docs" / "results.json").read_text())
            hits = _results_rows(results, spec)
            for metric, field in spec["fields"].items():
                row = {"id": aid, "where": f"docs/results.json:{spec['section']}{spec['where']}.{field}",
                       "metric": metric, "anchor": a["metrics"][metric]}
                if len(hits) != 1:
                    row.update(copy=None, status=MISSING, error=f"{len(hits)} matching rows, need exactly 1")
                else:
                    val = hits[0].get(field)
                    row["copy"] = val
                    row["status"] = OK if isinstance(val, (int, float)) and abs(val - row["anchor"]) < 1e-12 else DRIFT
                out.append(row)
    return out


def copy_lines(rows):
    return [f"ANCHOR DRIFT copy {r['where']} ({r['id']} {r['metric']}): copy {r['copy']}, registry {r['anchor']}"
            + (f" [{r['error']}]" if r.get("error") else "") for r in rows if r["status"] in (DRIFT, MISSING)]


# ---- kit auc ---------------------------------------------------------------------------------------------------

def auc_check(result, aid, device=None, registry=None):
    """The anchor check of one `kit auc` result: forward is the map's AUC, reverse the control's when one was
    scored. Metrics the run did not measure are NOT CHECKED; any measured one outside the tolerance is DRIFT."""
    measured = {"forward": (result.get("forward") or {}).get("auc")}
    if result.get("control"):
        measured["reverse"] = result["control"].get("auc")
    return check(get(aid, registry), measured, device, partial=True)


# ---- command line ---------------------------------------------------------------------------------------------

def _parse_values(items):
    out = {}
    for it in items:
        if "=" not in it:
            raise AnchorError(f"expected METRIC=VALUE, got {it!r}")
        k, v = it.split("=", 1)
        try:
            out[k] = float(v)
        except ValueError as exc:
            raise AnchorError(f"{it!r}: {v!r} is not a number") from exc
    return out


def _say(results, copies=None, as_json=False):
    bad = [r for r in results if r["status"] not in (OK, "SKIPPED")]
    cbad = [r for r in (copies or []) if r["status"] in (DRIFT, MISSING)]
    if as_json:
        print(json.dumps({"ok": not bad and not cbad, "anchors": results, "copies": copies}, indent=2))
    else:
        for r in results:
            print(f"{r['status']:8s} {r['id']}" + (f"  ({r['reason']})" if r.get("reason") else ""))
        if copies is not None:
            n = sum(1 for r in copies if r["status"] == OK)
            print(f"copies: {n} agree, {len(cbad)} disagree, {sum(1 for r in copies if r['status'] == 'ABSENT')} "
                  f"optional copies absent")
    for r in bad:
        for line in drift_lines(r):
            print(line, file=sys.stderr)
    for line in copy_lines(cbad):
        print(line, file=sys.stderr)
    return EXIT_DRIFT if bad or cbad else 0


def build_parser(p):
    sub = p.add_subparsers(dest="anchors_cmd", required=True)
    bench = "only the anchors of this benchmark (ink-auc, meshqa, switchfix, surfbench)"
    js = "print the full result as JSON"
    s = sub.add_parser("list", help="the registered anchors")
    s.add_argument("--benchmark", help=bench)
    s.add_argument("--json", action="store_true", help=js)
    s = sub.add_parser("check", help="check measured numbers against one anchor")
    s.add_argument("id", help="anchor id, such as ink-auc/ink9um-s42/0841-w00 (kit anchors list)")
    s.add_argument("values", nargs="+", metavar="METRIC=VALUE", help="a measured metric, such as forward=0.8061")
    s.add_argument("--device", help="device the run used; the anchor's same-device tolerance applies when it matches")
    s.add_argument("--partial", action="store_true", help="metrics not given are not checked instead of missing")
    s.add_argument("--json", action="store_true", help=js)
    s = sub.add_parser("record", help="check a run's anchor record; every metric --benchmark needs must be there")
    s.add_argument("file", help='JSON record {"anchors": {ID: {METRIC: VALUE}}, "device": optional}')
    s.add_argument("--benchmark", help="require every metric this benchmark needs (its own anchors and its copies)")
    s.add_argument("--device", help="device the run used (overrides the record's device)")
    s.add_argument("--json", action="store_true", help=js)
    for name, hlp in (("run", "recompute and check every synthetic anchor"),
                      ("copies", "every copy of a real anchor's value agrees with the registry"),
                      ("all", "run and copies (the daily routine)")):
        s = sub.add_parser(name, help=hlp)
        if name != "copies":
            s.add_argument("--benchmark", help=bench)
        s.add_argument("--json", action="store_true", help=js)
    return p


def cmd_anchors(args):
    try:
        reg = load()
        c = args.anchors_cmd
        if c == "list":
            rows = [a for a in reg["anchors"].values() if not args.benchmark or a["benchmark"] == args.benchmark]
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for a in rows:
                    vals = ", ".join(f"{k} {v}" for k, v in a["metrics"].items())
                    only = ", copies only" if a.get("never_rescore") else ""
                    print(f"{a['id']}  [{a['kind']}, tol {a['tol']}{only}]  {vals}")
            return 0
        if c == "check":
            return _say([check(get(args.id, reg), _parse_values(args.values), args.device, args.partial)],
                        as_json=args.json)
        if c == "record":
            rec = json.loads(Path(args.file).read_text())
            return _say(check_record(rec, args.benchmark, args.device, reg), as_json=args.json)
        if c == "run":
            return _say(run_synthetic(args.benchmark, reg), as_json=args.json)
        if c == "copies":
            return _say([], check_copies(reg), as_json=args.json)
        return _say(run_synthetic(args.benchmark, reg), check_copies(reg), as_json=args.json)
    except (AnchorError, OSError, json.JSONDecodeError) as exc:
        print(f"kit anchors: {exc}", file=sys.stderr)
        return EXIT_USAGE


def main(argv=None):
    return cmd_anchors(build_parser(argparse.ArgumentParser(prog="kit anchors")).parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
