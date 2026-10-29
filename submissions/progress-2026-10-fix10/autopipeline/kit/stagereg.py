"""The stage registry: every option we know for each stage of reading a scroll (ours, public and private; the
community's; the organisers' team models; released versions), in one list that every workflow chooses from, so a
tracer, a surface model, an ink model (2.5D or 3D) or a letter reader can be swapped by name, never by editing a
workflow (decided 25 Oct 2026: every workflow may swap any stage, wherever and whenever needed).

    python -m kit stages list [STAGE] [--workflow W] [--json]   every option: origin, licence, maturity, workflows
    python -m kit stages show STAGE NAME [--json]                one option in full
    python -m kit stages pick STAGE --workflow W [--use NAME] [--json]   what a workflow would use, and why
    python -m kit stages check [--json]                          the catalogue against its rules (the tests run it)

Where the options come from. A workflow that already has a backend table keeps it, and the registry reads it, so
nothing is listed twice: each extension module kit/stagereg_ext_NAME.py reads one (its rows() returns (rows,
defaults), its WORKFLOWS names the workflows it adds), so a copy lists what its own workflows can run. The data files add what no code table lists and the facts a table does
not carry (licence, maturity and its evidence): kit/data/stages.json ships in public copies; a note of the source repository
and the extensions a copy keeps to itself are simply absent elsewhere. A row in a data file whose stage and name a
code table also lists annotates that row, and a later file may annotate an earlier file's row.

Choosing. pick(stage, workflow, name) returns the named option, else the one KIT_STAGE_<STAGE> names (for example
KIT_STAGE_INK=d9v2), else the workflow's default; an option a workflow cannot run is refused with the
workflows that can. Naming an option is the opt-in: an experimental, pending or failed option runs when named, and
its maturity goes into the record (record()) so a result never hides what made it. A frozen test still runs only what
its preregistration names (rule 3). Workflows add --use STAGE=NAME with add_arguments() and read it with uses().

Maturity, the one scale (MATURITY): default (what a workflow runs when nothing is named), validated (a held-out or
published benchmark with its control, in our records or its authors'), experimental (runs; no passing held-out result
here yet), pending (a slot for a model still in development checks; not runnable until it passes), failed (failed a
frozen test or its controls; kept for comparisons). Licences are stated per option; code with no licence is only
ever fetched and run from its own host at run time, never copied (fetch: "runtime").

Standard library only.
"""

import argparse
import json
import os
import sys
from pathlib import Path

SCHEMA = "scrolls-stages/1"
DATA = Path(__file__).resolve().parent / "data"
FILES = ("stages.json", "stages-private.json")
MATURITY = ("default", "validated", "experimental", "pending", "failed")
ORIGINS = ("ours", "community", "team", "published")
WORKFLOWS = ["autopipeline", "scroll2ink", "cli", "vc3d"]       # extensions add their own
# The registry's stage names, in the order a scroll is read; each workflow's own stage names map onto them
STAGES = {
    "umbilicus": "the scroll's centre line",
    "surface": "the surface prediction a tracer follows (a 3D volume of sheet likelihood)",
    "lasagna": "the lasagna field: predicted sheet structure (cos, gradient, normals) for surface fitting",
    "spiral": "one deformed spiral fitted to the whole roll",
    "pick": "where to look: a region or seed rule",
    "trace": "growing a surface (a tifxyz mesh) along one sheet",
    "repair": "what happens to a trace that hops onto the touching sheet",
    "snap": "moving a mesh onto the sheet before render",
    "flatten": "flattening the surface before render",
    "render": "sampling the CT along the surface's normals into a layer stack",
    "ink": "the ink reader: 2.5D (reads the render's layers) or 3D (reads the scan around the mesh)",
    "ensemble": "combining several ink readers' maps",
    "check": "controls on an ink map",
    "triage": "ranking maps for a human to look at",
    "legibility": "how text-like an ink map is",
    "crackle": "Crackle Check's gate on a surface's maps",
    "stackcheck": "the stack check over accepted traces",
    "letters": "the letter reader: letter hypotheses from an ink map",
    "match": "testing letter hypotheses against Greek",
    "writeup": "the report",
}


class StageError(ValueError):
    pass


# ---------------------------------------------------------------- the catalogue

def _data(files=FILES, folder=DATA):
    rows, defaults = [], {}
    for name in files:
        path = Path(folder) / name
        if not path.is_file():
            continue
        try:
            d = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise StageError(f"{path}: not JSON ({exc})") from None
        if d.get("schema") != SCHEMA:
            raise StageError(f"{path}: schema is not {SCHEMA}")
        for r in d.get("options") or []:
            rows.append({**r, "source": name})
        for wf, stages in (d.get("defaults") or {}).items():
            defaults.setdefault(wf, {}).update(stages)
    return rows, defaults


_EXT = []


def _extensions():
    """The loaded extension modules (kit/stagereg_ext_*.py), each once; one that fails to import lists nothing."""
    if not _EXT:
        import importlib
        _EXT.append([])
        for path in sorted(Path(__file__).resolve().parent.glob("stagereg_ext_*.py")):
            try:
                mod = importlib.import_module(f"{__package__}.{path.stem}")
            except Exception:  # noqa: BLE001 - an extension that cannot load here adds nothing
                continue
            for wf in getattr(mod, "WORKFLOWS", ()):
                if wf not in WORKFLOWS:
                    WORKFLOWS.append(wf)
            _EXT[0].append(mod)
    return _EXT[0]


def _extension_rows():
    rows, defaults = [], {}
    for mod in _extensions():
        try:
            r, d = mod.rows()
        except Exception:  # noqa: BLE001
            continue
        rows += r
        for wf, st in (d or {}).items():
            defaults.setdefault(wf, {}).update(st)
    return rows, defaults


def _merge_row(base, extra):
    out = dict(base)
    for k, v in extra.items():
        if k == "use":
            out["use"] = {**(base.get("use") or {}), **(v or {})}
        elif k == "source":
            out["source"] = f"{base.get('source')} + {v}" if base.get("source") else v
        elif v is not None:
            out[k] = v
    return out


_CACHE = {}


def catalogue(refresh=False, files=FILES, folder=DATA):
    """{(stage, name): option} and {workflow: {stage: default name}} from every source."""
    key = (tuple(files), str(folder))
    if key in _CACHE and not refresh:
        return _CACHE[key]
    rows, defaults = [], {}
    ext, extd = _extension_rows()
    rows += ext
    for wf, st in extd.items():
        defaults.setdefault(wf, {}).update(st)
    data, data_defaults = _data(files, folder)
    out = {}
    for r in rows:
        k = (r["stage"], r["name"])
        out[k] = _merge_row(out[k], r) if k in out else r
    for r in data:
        k = (r.get("stage"), r.get("name"))
        if k in out:
            out[k] = _merge_row(out[k], r)
        elif r.get("by"):                  # a row with no `by` only annotates a code table's option: when this copy
            out[k] = r                     # has no such table (a public copy without AutoPipeline), it lists nothing
    for wf, st in data_defaults.items():
        defaults.setdefault(wf, {}).update(st)
    for (stage, name), r in out.items():
        if not r.get("maturity"):
            # an off switch has nothing to prove; any other option is experimental until its data row says more
            r["maturity"] = "validated" if r.get("kind") == "off" else "experimental"
            if r.get("kind") == "off":
                r.setdefault("why", "turns the step off: the ablation arm of a swap")
        if any(defaults.get(wf, {}).get(stage) == name for wf in (r.get("use") or {})):
            r["maturity"] = "default" if r["maturity"] in ("experimental", "validated", None) else r["maturity"]
    _CACHE[key] = (out, defaults)
    return out, defaults


def options(stage=None, workflow=None):
    """The options of a stage (or every stage), those a workflow can run when one is named, in a stable order."""
    cat, _ = catalogue()
    rows = [r for (s, _), r in sorted(cat.items()) if (stage is None or s == stage)
            and (workflow is None or workflow in (r.get("use") or {}) or "any" in (r.get("use") or {}))]
    return rows


def find(stage, name):
    if stage not in STAGES:
        raise StageError(f"no stage {stage}; stages: {', '.join(STAGES)}")
    cat, _ = catalogue()
    r = cat.get((stage, name))
    if r is None:
        known = sorted(n for (s, n) in cat if s == stage)
        raise StageError(f"{stage}: no option {name}; options: {', '.join(known) or 'none listed'}")
    return r


def default(stage, workflow):
    _, d = catalogue()
    return (d.get(workflow) or {}).get(stage)


def env_name(stage):
    return f"KIT_STAGE_{stage.upper()}"


def pick(stage, workflow, name=None, env=None):
    """The option a workflow uses for a stage: the one named, else KIT_STAGE_<STAGE>'s, else the workflow's default.
    Refuses an unknown option, one this workflow cannot run (naming the workflows that can), and a pending one (its
    slot holds no runnable model yet). Returns the option with picked_by and, for a non-default maturity, a warning."""
    env = os.environ if env is None else env
    how = "named"
    if not name and env.get(env_name(stage)):
        name, how = env[env_name(stage)], f"{env_name(stage)}"
    if not name:
        name, how = default(stage, workflow), "default"
    if not name:
        raise StageError(f"{workflow} has no default for {stage}: name one (--use {stage}=NAME)")
    names = [n.strip() for n in str(name).split(",") if n.strip()]
    picked = []
    for n in names:
        r = find(stage, n)
        use = r.get("use") or {}
        if r.get("maturity") == "pending":
            raise StageError(f"{stage} {n} is pending ({r.get('why') or 'still in development checks'}): it runs "
                             "once it passes and its maturity changes")
        if workflow not in use and "any" not in use:
            reach = f"; to reach it: {r['reach']}" if r.get("reach") else ""
            raise StageError(f"{stage} {n} is listed but {workflow} cannot run it; it runs in "
                             f"{', '.join(sorted(use)) or 'no workflow yet'}{reach}")
        rec = {**r, "picked_by": how}
        if r.get("maturity") not in ("default", "validated"):
            rec["warning"] = f"{stage} {n} is {r.get('maturity')}: {r.get('why') or 'no passing held-out result'}"
        picked.append(rec)
    return picked[0] if len(picked) == 1 else picked


def record(option):
    """What a run's record keeps about the option it used."""
    opts = option if isinstance(option, list) else [option]
    out = [{k: o.get(k) for k in ("stage", "name", "origin", "by", "licence", "maturity", "dims", "picked_by",
                                  "warning") if o.get(k) is not None} for o in opts]
    return out[0] if len(out) == 1 else out


# ---------------------------------------------------------------- workflows

def add_arguments(parser):
    parser.add_argument("--use", action="append", default=[], metavar="STAGE=NAME",
                        help="pick a stage's option by name from the stage registry (python -m kit stages list); "
                             "repeatable, NAME may list several with commas (ink=reader-v3,team-3d-paris4); "
                             "KIT_STAGE_<STAGE> does the same from the environment")
    return parser


def uses(values):
    """{stage: name} from --use STAGE=NAME values; refuses a malformed one or a stage named twice."""
    out = {}
    for v in values or []:
        stage, sep, name = str(v).partition("=")
        stage, name = stage.strip(), name.strip()
        if not sep or not stage or not name:
            raise StageError(f"--use {v!r}: give STAGE=NAME")
        if stage not in STAGES:
            raise StageError(f"--use {v!r}: no stage {stage}; stages: {', '.join(STAGES)}")
        if stage in out:
            raise StageError(f"--use names {stage} twice")
        out[stage] = name
    return out


def picks(values, workflow, env=None, stages=None):
    """{stage: picked option} for every stage named by --use (or the environment), checked for this workflow."""
    env = os.environ if env is None else env
    named = uses(values)
    out = {s: pick(s, workflow, n, env) for s, n in named.items()}
    for s in STAGES:
        if s not in named and env.get(env_name(s)) and (stages is None or s in stages):
            out[s] = pick(s, workflow, None, env)          # recorded as picked by KIT_STAGE_<STAGE>
    return out


def ap_settings(picked):
    """AutoPipeline settings for the picked options: {"backends": AutoPipeline's backends shorthand, plus any plain
    settings an option stands for}, what `kit autopipeline plan --use` lays over --settings. Refuses an option
    AutoPipeline cannot run."""
    backends, settings = {}, {}
    for stage, opt in picked.items():
        opts = opt if isinstance(opt, list) else [opt]
        names = []
        for o in opts:
            ap = (o.get("use") or {}).get("autopipeline")
            if not isinstance(ap, dict):
                raise StageError(f"{stage} {o['name']}: AutoPipeline cannot run it")
            if ap.get("backend"):
                names.append(ap["backend"])
            for k, v in (ap.get("settings") or {}).items():
                settings[k] = {**settings.get(k, {}), **v} if isinstance(v, dict) else v
        if names:
            backends[stage] = names if stage in ("ink", "umbilicus") else names[0] if len(names) == 1 else names
    return {**settings, **({"backends": backends} if backends else {})}


# ---------------------------------------------------------------- the rules

def check(files=FILES, folder=DATA):
    """Problems with the catalogue: every option names a known stage, a maturity on the scale, an origin and a
    licence (or says why none); an option no workflow can run says how it is reached; each workflow default exists
    and that workflow can run it; no data row repeats another."""
    problems = []
    seen = set()
    data, defaults = _data(files, folder)
    for r in data:
        # a later file may annotate an earlier file's option (a row with no `by`: the private file's facts about a
        # public option); a row that lists the option again, or a file that lists it twice, is a mistake
        k = (r.get("stage"), r.get("name"))
        if (k, r.get("source")) in seen or (k in {s for s, _ in seen} and r.get("by")):
            problems.append(f"{r.get('source')}: {k[0]} {k[1]} is listed twice")
        seen.add((k, r.get("source")))
    cat, alld = catalogue(refresh=True, files=files, folder=folder)
    for (stage, name), r in sorted(cat.items()):
        where = f"{stage} {name} ({r.get('source')})"
        if stage not in STAGES:
            problems.append(f"{where}: no stage {stage}")
        if r.get("maturity") not in MATURITY:
            problems.append(f"{where}: maturity {r.get('maturity')!r} is not one of {', '.join(MATURITY)}")
        if r.get("origin") not in ORIGINS and r.get("kind") != "off" and r.get("origin") != "off":
            problems.append(f"{where}: origin {r.get('origin')!r} is not one of {', '.join(ORIGINS)}")
        if r.get("source", "").startswith("stages") and not r.get("licence"):
            problems.append(f"{where}: no licence (say \"none stated\" and fetch: runtime for unlicensed code)")
        if r.get("licence") and "none stated" in str(r["licence"]).lower() and r.get("fetch") != "runtime":
            problems.append(f"{where}: unlicensed code is fetched at run time only (fetch: runtime)")
        if r.get("maturity") in ("failed", "experimental", "pending") and r.get("source", "").startswith("stages") \
                and not r.get("why"):
            problems.append(f"{where}: a {r['maturity']} option says why")
        for wf in r.get("use") or {}:
            if wf not in WORKFLOWS and wf != "any":
                problems.append(f"{where}: workflow {wf} is not one of {', '.join(WORKFLOWS)}")
        if not r.get("use") and not r.get("reach"):
            problems.append(f"{where}: no workflow runs it and no reach says how to get it")
    for wf, st in alld.items():
        for stage, name in st.items():
            r = cat.get((stage, name))
            if r is None:
                problems.append(f"default {wf} {stage}: no option {name}")
            elif wf not in (r.get("use") or {}) and "any" not in (r.get("use") or {}):
                problems.append(f"default {wf} {stage}: {wf} cannot run {name}")
    return problems


# ---------------------------------------------------------------- command line

def _line(r):
    dims = f", {r['dims']}" if r.get("dims") else ""
    wf = ", ".join(sorted(r.get("use") or {})) or ("reach: " + str(r.get("reach")) if r.get("reach") else "none")
    return (f"  {r['name']}: {r.get('maturity')}{dims}; {r.get('origin') or 'off'}; "
            f"{r.get('licence') or 'licence n/a'}; runs in {wf}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit stages", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list", help="every option of every stage (or of one)")
    s.add_argument("stage", nargs="?")
    s.add_argument("--workflow")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("show", help="one option in full")
    s.add_argument("stage")
    s.add_argument("name")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("pick", help="what a workflow would use for a stage, and why")
    s.add_argument("stage")
    s.add_argument("--workflow", required=True)
    s.add_argument("--use", dest="name")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("check", help="the catalogue against its rules")
    s.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        if a.cmd == "list":
            if a.stage and a.stage not in STAGES:
                raise StageError(f"no stage {a.stage}; stages: {', '.join(STAGES)}")
            rows = options(a.stage, a.workflow)
            if a.json:
                print(json.dumps(rows, indent=1, default=str))
                return 0
            for stage in STAGES:
                these = [r for r in rows if r["stage"] == stage]
                if not these:
                    continue
                d = {wf: st.get(stage) for wf, st in catalogue()[1].items() if st.get(stage)}
                print(f"{stage}: {STAGES[stage]}" + (f" (defaults: {', '.join(f'{k} {v}' for k, v in d.items())})"
                                                     if d else ""))
                for r in these:
                    print(_line(r))
            return 0
        if a.cmd == "show":
            r = find(a.stage, a.name)
            print(json.dumps(r, indent=1, default=str) if a.json else
                  "\n".join(f"{k}: {json.dumps(v, default=str) if isinstance(v, (dict, list)) else v}"
                            for k, v in r.items()))
            return 0
        if a.cmd == "pick":
            r = pick(a.stage, a.workflow, a.name)
            rec = record(r)
            print(json.dumps(rec, indent=1) if a.json else json.dumps(rec))
            return 0
        problems = check()
        if a.json:
            print(json.dumps({"problems": problems}, indent=1))
        else:
            print("\n".join(problems) if problems else "stage registry: no problems")
        return 1 if problems else 0
    except StageError as exc:
        print(f"kit stages: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
