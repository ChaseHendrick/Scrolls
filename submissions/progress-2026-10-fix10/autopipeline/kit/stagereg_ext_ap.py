"""The stage registry's AutoPipeline source (kit/stagereg.py loads every kit/stagereg_ext_*.py): AutoPipeline's backend
tables (kit/apbackends.py), its ink models included, and kit ink3d's 3D ink models, which also run alone from the
command line. It ships with AutoPipeline; a copy without AutoPipeline runs the registry without it. Standard library
only (kit/apbackends.py and kit/ink3d.py are imported when present)."""

WORKFLOWS = ("autopipeline",)


def ap_rows():
    """AutoPipeline's backend tables, one option per choice of each of its stages, and its stage defaults."""
    try:
        from . import apbackends
    except ImportError:
        return [], {}
    rows, defaults = [], {}
    for stage in apbackends.STAGES:
        try:
            ch = apbackends.choices(stage)
        except Exception:  # noqa: BLE001 - a computed list that cannot load here lists nothing
            continue
        for name, c in ch.items():
            origin = c.get("origin") or ("off" if c.get("kind") == "off" else None)
            rows.append({"stage": stage, "name": name, "origin": origin, "by": c.get("by"), "kind": c.get("kind"),
                         "licence": c.get("licence"), "needs": c.get("needs") or [], "compute": c.get("compute"),
                         "dims": c.get("dims"), "maturity": c.get("maturity"), "why": c.get("why"),
                         "use": {"autopipeline": {"backend": name}}, "source": "kit/apbackends.py"})
        d = apbackends.STAGES[stage]["default"]
        if d in ch:
            defaults[stage] = d
    return rows, defaults


def ink3d_rows():
    """kit ink3d's 3D models, runnable alone from the command line (AutoPipeline lists them through its ink table)."""
    try:
        from . import ink3d
    except ImportError:
        return []
    return [{"stage": "ink", "name": n, "dims": "3d", "use": {"cli": {"command": ["python", "-m", "kit", "ink3d",
                                                                                "run", n]}},
             "source": "kit/ink3d.py", **{k: m.get(k) for k in ("origin", "by", "licence", "why") if m.get(k)},
             "maturity": m.get("status", "experimental")} for n, m in sorted(ink3d.models().items())]


def rows():
    from .stagereg import STAGES
    ap, defaults = ap_rows()
    out = [r for r in ap + ink3d_rows() if r["stage"] in STAGES]
    return out, ({"autopipeline": {s: d for s, d in defaults.items() if s in STAGES}} if defaults else {})
