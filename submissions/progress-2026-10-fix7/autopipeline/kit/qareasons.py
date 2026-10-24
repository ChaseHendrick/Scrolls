"""Why each AutoPipeline trace failed qa, as scalars: which checks failed, with the value each one measured and the
threshold it was held to, and any exception that stopped the checks. AutoPipeline's qa (kit/autopipe.py
Run.qa_one, Run.s_qa) writes these into the run's state.json and its log; a reader of a tracing run's state files
(kit labelxfer readout, or a held-out run's own reader) copies them into its results and counts them by failure kind.

Added 22 October 2026, when a tracing run's reader could not find the traces' records and wrote "failure kind
unrecorded" for every one of them: AutoPipeline had written each trace's qa reasons, but under a different trace id
than the reader looked for. make_plan now refuses a top-level dotted setting, the cause of that mismatch.

Standard library only (kit labelxfer reads state.json files with no numpy). Nothing here reads a label, a
prediction or a mesh: only the qa records AutoPipeline already wrote.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Each check AutoPipeline's qa can fail, by the prefix of the reason Run.qa_one writes for it, in qa_one's order.
# The reasons decide acceptance (rec["accepted"] is `not reasons`), so a check failed exactly when a reason of it
# stands; the structured record only adds what was measured and the threshold.
CHECKS = (
    ("data_term", ("traced without normal grids",)),
    ("valid_fraction", ("valid fraction ",)),
    ("selfcross", ("self-intersections",)),
    ("seating", ("seating: ",)),
    ("orientation", ("orientation",)),
    ("validity", ("VC3D's loader rules",)),
    ("windaudit", ("winding audit",)),
    ("check_error", ("check failed: ",)),
)
CHECK_NAMES = tuple(c for c, _ in CHECKS)
UNKNOWN_CHECK = "other"
# A failure's kind (kit/autopipe.py FAILURE_KINDS) plus the two this module adds for a reader that cannot find the
# trace's record: "not_traced", a planned row with no trace of that id in AutoPipeline's plan, and "unrecorded"
REJECTED_KINDS = ("ours", "infrastructure", "not_traced", "unrecorded")
# Keys that hold places, files or coordinates: never copied into a summary (a target scroll's are private)
_PRIVATE_KEYS = frozenset(("seed", "seeds", "xyz", "bbox_xyz", "path", "surface", "surface_traced", "traced",
                           "report", "out", "selfcross_report", "crop_inputs", "render_surface", "clipped"))


class QaReasonsError(ValueError):
    pass


def check_of(reason):
    """The check a qa reason belongs to (CHECKS), or "other"."""
    text = str(reason or "")
    for name, prefixes in CHECKS:
        if text.startswith(prefixes):
            return name
    return UNKNOWN_CHECK


def exception_record(exc):
    """{"type", "message"} of an exception, the message cut to 500 characters."""
    return {"type": type(exc).__name__, "message": str(exc)[:500]}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _seated_counts(text):
    """(seated, windows) from check_surface's "k of n" seated_windows, or (None, None)."""
    m = re.match(r"\s*(\d+)\s+of\s+(\d+)", str(text or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _measured(name, rec, qa):
    """(measured, threshold) of one check from a qa record and the plan's qa settings: scalars only."""
    qa = qa or {}
    cs = rec.get("check_surface") or {}
    if name == "data_term":
        return ({"data_term": rec.get("data_term")},
                {"require_data_term": bool(qa.get("require_data_term", False)), "needs": "normal grids"})
    if name == "valid_fraction":
        return ({"valid_fraction": _num((cs.get("grid") or {}).get("valid_fraction"))},
                {"min_valid_fraction": qa.get("min_valid_fraction")})
    if name == "selfcross":
        sc = cs.get("selfcross") or {}
        rate = rec.get("selfcross_rate") or {}
        if rate:
            return ({"transverse": _num(rate.get("transverse")), "per_cm2": _num(rate.get("per_cm2")),
                     "area_cm2": _num(rate.get("area_cm2"))},
                    {"max_per_cm2": rate.get("tolerance_per_cm2")})
        measured = {"transverse": _num(sc.get("transverse"))}
        if sc.get("transverse") is None and (sc.get("exit") is not None or sc.get("error")):
            measured.update(exit=sc.get("exit"), error=str(sc.get("error"))[:200] if sc.get("error") else None)
        return measured, {"max_transverse": qa.get("max_selfcross")}
    if name == "seating":
        seat = rec.get("seating") or {}
        k, n = _seated_counts(seat.get("seated_windows"))
        return ({"verdict": seat.get("verdict"), "seated_windows": k, "windows": n},
                {"require_seated": qa.get("require_seated")})
    if name == "orientation":
        o = rec.get("orientation") or {}
        nrm = o.get("normal") or {}
        th = nrm.get("thresholds") or {}
        return ({"checked": o.get("checked"), "vote": nrm.get("vote"), "confidence": nrm.get("confidence"),
                 "outward_share": _num(nrm.get("outward_share"))},
                {"vote": "outward", "confidence": "weak or clear",
                 "weak_share": _num(th.get("weak")), "clear_share": _num(th.get("clear"))})
    if name == "validity":
        v = rec.get("validity") or {}
        errors = sum(1 for f in v.get("findings") or [] if isinstance(f, dict) and f.get("severity") == "error")
        return {"worst": v.get("worst"), "errors": errors}, {"worst_allowed": "below error"}
    if name == "windaudit":
        w = rec.get("windaudit") or {}
        gate = w.get("gate") or {}
        measured = {"audited": w.get("audited", bool(gate)), "local_failed": gate.get("local_failed"),
                    "full_turn_fusions": _num(gate.get("full_turn_fusions")),
                    "multi_turn_skips": _num(gate.get("multi_turn_skips")),
                    "broad_fusions": _num(gate.get("broad_fusions"))}
        if w.get("pitch_fit") or w.get("error"):
            measured.update(pitch_fit=w.get("pitch_fit"), error=str(w.get("error"))[:200] if w.get("error") else None)
        return measured, {"full_turn_fusions": 0, "multi_turn_skips": 0, "broad_fusions": 0, "mode": qa.get("windaudit")}
    return {}, {}


def _ran(name, rec, qa):
    """Whether a check applies to this record at all (a check the plan turned off, or that wrote nothing, is left
    out of the list rather than shown as passed)."""
    qa = qa or {}
    if name == "data_term":
        return "data_term" in rec
    if name in ("valid_fraction", "selfcross", "seating"):
        return "check_surface" in rec
    if name == "orientation":
        return bool((rec.get("orientation") or {}).get("checked"))
    if name == "validity":
        return "validity" in rec
    if name == "windaudit":
        return "windaudit" in rec
    return False


def checks(rec, qa=None):
    """Every qa check of one AutoPipeline qa record (Run.qa_one's), in CHECKS order: [{"check", "passed",
    "measured", "threshold"}] with "reasons" (the reason strings of a failed check) and "unmeasured" (a reason that
    rests on a check that could not run). A reason no check names comes last as check "other". `qa` is the plan's
    qa settings (plan["settings"]["qa"]); without it the thresholds the record does not carry are None."""
    rec = rec or {}
    reasons = [str(r) for r in rec.get("reasons") or []]
    unmeasured = set(rec.get("unmeasured") or [])
    by_check = {}
    for r in reasons:
        by_check.setdefault(check_of(r), []).append(r)
    out = []
    for name, _ in CHECKS:
        failed = by_check.get(name)
        if not failed and not _ran(name, rec, qa):
            continue
        measured, threshold = _measured(name, rec, qa)
        row = {"check": name, "passed": not failed, "measured": measured, "threshold": threshold}
        if failed:
            row["reasons"] = [r[:300] for r in failed]
            if any(r in unmeasured for r in failed):
                row["unmeasured"] = True
        out.append(row)
    if by_check.get(UNKNOWN_CHECK):
        out.append({"check": UNKNOWN_CHECK, "passed": False, "measured": {}, "threshold": {},
                    "reasons": [r[:300] for r in by_check[UNKNOWN_CHECK]]})
    return out


def failed_checks(rec, qa=None):
    """The failed entries of checks(rec, qa); a record written before 22 Oct 2026 that holds "checks" already is
    read as it stands."""
    have = (rec or {}).get("checks")
    rows = have if isinstance(have, list) else checks(rec, qa)
    return [c for c in rows if not c.get("passed")]


def _repair_summary(rec):
    rep = (rec or {}).get("repair")
    if not isinstance(rep, dict):
        return None
    out = {k: rep.get(k) for k in ("method", "done", "taken", "area_share", "min_area_share", "flagged", "kept")
           if rep.get(k) is not None}
    for k in ("why", "error"):
        if rep.get(k):
            out[k] = str(rep[k])[:300]
    return out


def _crop_summary(rec):
    crop = (rec or {}).get("crop")
    if not isinstance(crop, dict):
        return None
    out = {k: crop.get(k) for k in ("done", "area_cm2", "kept_area_cm2", "kept_share", "accepted_cm2")
           if crop.get(k) is not None}
    if crop.get("pieces") is not None:
        out["pieces"] = len(crop["pieces"])
        out["pieces_accepted"] = sum(1 for p in crop["pieces"] if p.get("accepted"))
    if crop.get("error"):
        out["error"] = str(crop["error"])[:300]
    return out


def qa_failure(rec, qa=None):
    """What a rejected qa record says of why: {"stage": "qa", "kind", "checks": the failed checks with their values
    and thresholds, "exception" when the checks raised, "repair" and "crop" when qa.repair or qa.crop tried}. None
    for an accepted record."""
    rec = rec or {}
    if rec.get("accepted"):
        return None
    out = {"stage": "qa", "kind": (rec.get("failure") or {}).get("kind") or "ours",
           "checks": failed_checks(rec, qa)}
    if rec.get("exception"):
        out["exception"] = rec["exception"]
    rep, crop = _repair_summary(rec), _crop_summary(rec)
    if rep:
        out["repair"] = rep
    if crop:
        out["crop"] = crop
    return out


def _scalar_measured(m):
    """A short "k=v" text of a measured or threshold dict (None values left out)."""
    return ", ".join(f"{k}={v}" for k, v in (m or {}).items() if v is not None and k != "error")


def describe(failure):
    """One line of text for a failure record (qa_failure's, or any {"stage", "kind", "reason"})."""
    if not failure:
        return "accepted"
    f = failure
    parts = []
    for c in f.get("checks") or []:
        bit = c["check"]
        meas, thr = _scalar_measured(c.get("measured")), _scalar_measured(c.get("threshold"))
        if meas or thr:
            bit += f" ({meas or 'not measured'}; limit {thr or 'none recorded'})"
        if c.get("unmeasured"):
            bit += " [could not run]"
        parts.append(bit)
    if f.get("exception"):
        parts.append(f"exception {f['exception'].get('type')}: {str(f['exception'].get('message'))[:160]}")
    if f.get("repair"):
        r = f["repair"]
        parts.append("repair " + ("taken" if r.get("taken") else f"not taken ({r.get('why') or r.get('error')})"))
    if not parts and f.get("reason"):
        parts.append(str(f["reason"])[:300])
    return f"rejected at {f.get('stage') or 'qa'}, kind {f.get('kind') or 'unrecorded'}: " + "; ".join(parts)


def log_line(label, failure):
    """The one log line per trace: `qa <label>: accepted` or `qa <label>: rejected at ..., kind ...: checks`."""
    return f"qa {label}: {describe(failure)}"


def counts(failures):
    """A gate block's summary of a list of failure records (None for an accepted or surviving trace):
    {"traces", "rejected", "by_kind": {kind: n}, "by_check": {check: n}, "exceptions": {type: n}}. A trace counts
    once per kind and once for each check it failed."""
    by_kind, by_check, exc = {}, {}, {}
    rejected = 0
    failures = list(failures)
    for f in failures:
        if not f:
            continue
        rejected += 1
        kind = f.get("kind") or "unrecorded"
        by_kind[kind] = by_kind.get(kind, 0) + 1
        for c in {c.get("check") for c in f.get("checks") or [] if c.get("check")}:
            by_check[c] = by_check.get(c, 0) + 1
        if f.get("exception"):
            t = f["exception"].get("type") or "Exception"
            exc[t] = exc.get(t, 0) + 1
    out = {"traces": len(failures), "rejected": rejected, "by_kind": dict(sorted(by_kind.items())),
           "by_check": {c: by_check[c] for c in (*CHECK_NAMES, UNKNOWN_CHECK) if c in by_check}}
    if exc:
        out["exceptions"] = dict(sorted(exc.items()))
    return out


def scalars(obj):
    """obj with every place, file and coordinate key (_PRIVATE_KEYS) left out, recursively: what a report or a
    commit may carry about a target scroll's traces."""
    if isinstance(obj, dict):
        return {k: scalars(v) for k, v in obj.items() if k not in _PRIVATE_KEYS}
    if isinstance(obj, list):
        return [scalars(v) for v in obj]
    return obj


# ---------------------------------------------------------------- AutoPipeline state.json

def from_state(state, qa=None):
    """[{"sid", "seed_index", "repeat", "accepted", "failure"}] for every planned trace of an AutoPipeline
    state.json, in launch order: a qa rejection's failure carries its failed checks (qa_failure), a trace or render
    failure stays as kit autopipe trace_entries gives it. `qa` is the plan's qa settings, for the thresholds."""
    from . import autopipe
    surfaces = (state or {}).get("surfaces") or {}
    out = []
    for e in autopipe.trace_entries(state or {}):
        s = surfaces.get(e["sid"]) or {}
        f = e.get("failure")
        if (f or {}).get("stage") == "qa" and "qa" in s:
            f = {**f, **qa_failure(s["qa"], qa)}
        out.append({"sid": e["sid"], "seed_index": e.get("seed_index"), "repeat": e.get("repeat"),
                    "accepted": e.get("accepted"), "partial": e.get("partial"), "failure": f})
    return out


def _stageg():
    """An optional extra reader of the source repository, when this checkout has it (it is not part of this
    release), else None."""
    try:
        from . import qareasons_extra
    except ImportError:
        return None
    return qareasons_extra


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kit.qareasons",
                                 description="why each AutoPipeline trace failed qa: the failed checks with their "
                                             "measured values and thresholds, and any exception (scalars only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("state", help="every planned trace of one AutoPipeline state.json")
    p.add_argument("state")
    p.add_argument("--plan", help="the run's plan.json, for the qa thresholds (default: plan.json beside state.json)")
    p.add_argument("--json", action="store_true")
    stageg = _stageg()
    if stageg is not None:
        stageg.add_parser(sub)
    a = ap.parse_args(argv)
    if a.cmd == "state":
        sp = Path(a.state)
        plan_p = Path(a.plan) if a.plan else sp.parent / "plan.json"
        qa = (json.loads(plan_p.read_text()).get("settings") or {}).get("qa") if plan_p.is_file() else None
        recs = from_state(json.loads(sp.read_text()), qa)
        summary = counts(r["failure"] if not r.get("accepted") else None for r in recs)
        if a.json:
            print(json.dumps(scalars({"traces": recs, "counts": summary}), indent=1))
        else:
            for r in recs:
                print(log_line(r["sid"], None if r.get("accepted") else r["failure"]))
            print(json.dumps(summary))
        return 0
    return stageg.run(a)


if __name__ == "__main__":
    sys.exit(main())
