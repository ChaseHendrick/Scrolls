"""Gate A, automatically: which released reader is best on PHerc0841, by the Phase 0 rule below.

The roadmap itself now lives in Scrolls-private; this docstring is the public statement of the
rule: rank readers by mean forward AUC over PHerc0841's three 640 px crops (64 px edge left out),
with the reverse AUC well below the forward AUC on each; one reader beats another only by at
least 0.02 mean AUC. "Well below" is read here as forward minus reverse of at least 0.10 on every
crop (`min_gap`). The 0.10 was set after the committed gaps had been seen, not fixed in advance:
the smallest committed gap is 0.1015 (`ink_9um` seed 42 on ag896), so that reader clears the bar
by 0.0015, and a slightly higher bar would have dropped it.

Scores come from two places: the bars committed in docs/results.json (CPU runs here), and the
`auc_*.json` files the Mac script writes under WORK/<segment>/results/. A Mac file counts only
if it was scored on the same crop with the same edge. The Mac's `ink_9um` seed 42 score must
equal the committed CPU bar to four decimals (one unit of slack for rounding); a mismatch means the crop, labels or code differ,
and is reported, and it blocks the verdict: no winner is named until it is explained. A Mac file whose control was scored
with another edge is skipped like one on another crop. A Mac result for a reader and crop that already has a committed bar
replaces that bar, and the output names every bar so replaced.

Standard library only.
"""

import json
from pathlib import Path

SEGMENTS = ("0841-w00", "0841-ag896", "0841-ag405")
MIN_LEAD = 0.02
MIN_GAP = 0.10
INNER = 64
RESULTS = Path(__file__).resolve().parent.parent / "docs" / "results.json"
MAC_NAMES = {"ink9um_s42": "ink_9um seed42 (Mac)", "ink9um_s43": "ink_9um seed43 (Mac)",
             "v8in": "v8in", "v8in1447": "v8in-1447"}


def committed(path=RESULTS):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    crops = {seg: data["segments"][seg]["crop"] for seg in SEGMENTS}
    table = {}
    for r in data["results"]:
        if (r.get("segment") in SEGMENTS and r.get("window") == "crop" and r.get("inner_px") == INNER
                and r.get("auc_as_stored") is not None):
            table.setdefault(r["reader"], {})[r["segment"]] = (r["auc_as_stored"], r.get("auc_reversed"), "results.json")
    return table, crops


def from_mac(work, crops):
    table, skipped = {}, []
    for seg in SEGMENTS:
        for f in sorted((Path(work) / seg / "results").glob("auc_*.json")):
            name = MAC_NAMES.get(f.stem[4:], f.stem[4:])
            try:
                a = json.loads(f.read_text(encoding="utf-8"))
                fwd, ctrl = a["forward"], a.get("control") or {}
            except (OSError, ValueError, KeyError, TypeError):
                skipped.append(f"{f}: unreadable")
                continue
            if not isinstance(fwd, dict) or not isinstance(ctrl, dict):
                skipped.append(f"{f}: forward and control must be objects with an auc; rescore this crop")
                continue
            if list(a.get("crop") or []) != list(crops[seg]) or fwd.get("inner") != INNER:
                skipped.append(f"{f}: not the standard crop with a {INNER} px edge (crop {a.get('crop')}, inner {fwd.get('inner')})")
                continue
            if ctrl and ctrl.get("inner", INNER) != INNER:
                skipped.append(f"{f}: control scored with a {ctrl.get('inner')} px edge, not {INNER}")
                continue
            table.setdefault(name, {})[seg] = (fwd.get("auc"), ctrl.get("auc"), str(f))
    return table, skipped


def decide(table, min_lead=MIN_LEAD, min_gap=MIN_GAP):
    ranked, incomplete = [], []
    for reader, cells in table.items():
        if not all(seg in cells and cells[seg][0] is not None for seg in SEGMENTS):
            incomplete.append(reader)
            continue
        fwd = [cells[seg][0] for seg in SEGMENTS]
        gaps = [cells[seg][0] - cells[seg][1] if cells[seg][1] is not None else None for seg in SEGMENTS]
        ranked.append({"reader": reader, "mean": round(sum(fwd) / len(fwd), 4),
                       "cells": {seg: cells[seg][:2] for seg in SEGMENTS},
                       "control_ok": all(g is not None and g >= min_gap for g in gaps),
                       "min_gap": None if None in gaps else round(min(gaps), 4)})
    ranked.sort(key=lambda r: -r["mean"])
    eligible = [r for r in ranked if r["control_ok"]]
    verdict = {"winner": None, "lead": None, "clear": False, "text": "no reader has all three crops with a clean control"}
    if eligible:
        top = eligible[0]
        verdict["winner"] = top["reader"]
        if len(eligible) == 1:
            verdict.update(clear=True, text=f"{top['reader']} is the only reader with all three crops and a clean control")
        else:
            lead = round(top["mean"] - eligible[1]["mean"], 4)
            verdict["lead"] = lead
            verdict["clear"] = lead >= min_lead
            verdict["text"] = (f"{top['reader']} leads {eligible[1]['reader']} by {lead:.4f} mean AUC: "
                               + ("a clear win (at least %.2f)" % min_lead if lead >= min_lead
                                  else "within %.2f, so not a win; prefer the reader already in use, or score more crops" % min_lead))
    return {"ranked": ranked, "incomplete": sorted(incomplete), "verdict": verdict,
            "rule": {"min_lead": min_lead, "min_gap": min_gap, "inner": INNER, "segments": list(SEGMENTS)}}


def consistency(bars, mac):
    """Mac ink_9um seed 42 against the committed CPU bar, per crop."""
    out = []
    ref, got = bars.get("ink_9um seed42", {}), mac.get("ink_9um seed42 (Mac)", {})
    for seg in SEGMENTS:
        if seg in ref and seg in got and got[seg][0] is not None:
            diff = abs(got[seg][0] - ref[seg][0])
            out.append({"segment": seg, "cpu": ref[seg][0], "mac": got[seg][0], "match": diff <= 0.0001 + 1e-9})
    return out


def run(work=None, results=RESULTS, min_lead=MIN_LEAD, min_gap=MIN_GAP):
    bars, crops = committed(results)
    mac, skipped = from_mac(work, crops) if work else ({}, [])
    table = {reader: dict(cells) for reader, cells in bars.items()}
    replaced = []
    for reader, cells in mac.items():
        for seg, cell in cells.items():
            if seg in bars.get(reader, {}):
                replaced.append({"reader": reader, "segment": seg, "committed": bars[reader][seg][0],
                                 "local": cell[0], "file": cell[2]})
        table.setdefault(reader, {}).update(cells)
    result = decide(table, min_lead, min_gap)
    result["checks"] = consistency(bars, mac)
    result["skipped"] = skipped
    result["replaced"] = replaced
    bad = [c["segment"] for c in result["checks"] if not c["match"]]
    if bad:
        result["verdict"].update(
            winner=None, lead=None, clear=False, blocked=True,
            text="blocked: the Mac's ink_9um seed 42 does not match the committed CPU bar on " + ", ".join(bad)
                 + " (crop, labels or code differ); explain the mismatch before ranking")
    return result


def format_result(result):
    segs = result["rule"]["segments"]
    lines = ["| Reader | " + " | ".join(s.replace("0841-", "") for s in segs) + " | Mean | Control |",
             "| --- | " + " | ".join("---:" for _ in segs) + " | ---: | --- |"]
    for r in result["ranked"]:
        cells = [f"{f:.4f} ({'?' if c is None else f'{c:.3f}'})" for f, c in (r["cells"][s] for s in segs)]
        ok = "ok" if r["control_ok"] else f"too close (min gap {r['min_gap']})"
        lines.append(f"| {r['reader']} | " + " | ".join(cells) + f" | {r['mean']:.4f} | {ok} |")
    lines.append("")
    lines.append("Forward AUC (reverse in brackets), 640 px crops less a %d px edge." % result["rule"]["inner"])
    if result["incomplete"]:
        lines.append("Not ranked yet (missing crops): " + ", ".join(result["incomplete"]))
    for c in result["checks"]:
        lines.append(f"check {c['segment']}: Mac ink_9um s42 {c['mac']:.4f} vs CPU {c['cpu']:.4f}: "
                     + ("match" if c["match"] else "MISMATCH (crop, labels or code differ; do not rank until explained)"))
    for r in result.get("replaced", []):
        local = "none" if r["local"] is None else f"{r['local']:.4f}"
        lines.append(f"replaced committed bar: {r['reader']} on {r['segment']}, results.json {r['committed']:.4f}, "
                     f"now the local WORK result {local} from {r['file']}")
    for s in result["skipped"]:
        lines.append(f"skipped {s}")
    lines.append("Gate A: " + result["verdict"]["text"])
    return "\n".join(lines)
