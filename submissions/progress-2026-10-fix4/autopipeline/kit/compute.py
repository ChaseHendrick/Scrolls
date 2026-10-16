"""Compute ledger: how much machine time each run took, from provenance records.

Modeled on GENChase's COMPUTE.md (https://github.com/ChaseHendrick/GENChase/blob/main/COMPUTE.md),
which is generated from job records so the cost of each result is visible. Here the records
are the `provenance*.json` files the Mac scripts write; each holds the operator, the machine,
and UTC start and finish times. Wall-clock time is what is measured; energy is an estimate
only when the caller gives a power draw (`watts`), because laptops do not report it.

Standard library only.
"""

import json
from datetime import datetime
from pathlib import Path


def _parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ") if ts else None


def collect(paths):
    """Provenance records from files or directories (searched for provenance*.json)."""
    records = []
    for p in map(Path, paths):
        files = sorted(p.rglob("provenance*.json")) if p.is_dir() else [p]
        for f in files:
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict) and "digest" in rec and "run" in rec:
                rec["_file"] = str(f)
                records.append(rec)
    return records


def rows(records, watts=None):
    out = []
    for rec in records:
        start, end = _parse(rec.get("started_utc")), _parse(rec.get("finished_utc"))
        hours = (end - start).total_seconds() / 3600 if start and end else None
        m = rec.get("machine", {})
        row = {"run": rec["run"], "operator": rec.get("operator", {}).get("name"),
               "machine": m.get("chip") or m.get("machine"), "started_utc": rec.get("started_utc"),
               "hours": None if hours is None else round(hours, 3), "digest": rec["digest"][:16]}
        if watts is not None and hours is not None:
            row["wh_estimate"] = round(hours * watts, 1)
        out.append(row)
    return sorted(out, key=lambda r: r["started_utc"] or "")


def table(rows_, watts=None):
    head = "| Run | Operator | Machine | Started (UTC) | Hours | Digest |"
    rule = "| --- | --- | --- | --- | ---: | --- |"
    if watts is not None:
        head += f" Wh at {watts:g} W |"
        rule += " ---: |"
    lines = [head, rule]
    total = 0.0
    for r in rows_:
        total += r["hours"] or 0.0
        cells = [r["run"], r["operator"] or "", r["machine"] or "", r["started_utc"] or "",
                 "" if r["hours"] is None else f"{r['hours']:.3f}", f"`{r['digest']}`"]
        if watts is not None:
            cells.append("" if r.get("wh_estimate") is None else f"{r['wh_estimate']:.1f}")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append(f"\n{len(rows_)} run{'' if len(rows_) == 1 else 's'}, {total:.2f} hours wall clock"
                 + (f", about {total * watts:.0f} Wh at {watts:g} W (an estimate, not a measurement)" if watts else "") + ".")
    return "\n".join(lines)
