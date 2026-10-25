"""AutoPipeline's backends: for each stage that can be swapped, which tool does it, ours or the community's, and how
a plan picks one. `python -m kit autopipeline backends` lists them with what this machine has for each;
`python -m kit autopipeline preflight` checks a plan's choices before a run.

A plan picks backends with the setting `backends`, a shorthand that make_plan turns into the settings it stands for
before the plan is frozen ({"umbilicus": "centrenet"} is umbilicus.source "estimate" with umbilicus.estimator
"centrenet"), so the frozen plan holds only ordinary settings and its digest covers every choice. A setting given
both ways must agree, or the plan is refused. A list is a fallback order (the umbilicus stage tries each estimator
in turn and records which ran and why the others did not). "off" turns an optional stage step off, the ablation arm
of a swap comparison (kit autopipeline swap).

Each backend says where it comes from (origin: ours or community, and whose), what kind it is (published: a file
someone made; classical: a fixed algorithm; learned: trained weights), its license, what it needs on the machine
and what kind of compute it wants. The compute rule (COMPUTE): GPU work runs on a GPU host;
CPU work runs on this machine unless it would take more than about 10 minutes here, and then on a larger host.
Nothing here launches anything: preflight only says where a job belongs.

Standard library only; kit.autopipe imports this module, never the reverse at import time.
"""

import json
import os
import sys
from pathlib import Path

from . import cloudcost

# AGENTS.md rule 10 names kit.cloudcost's modal_gpu() and modal_cpu(), so the lists come from there
GPU_RULE = {"where": "modal", "gpu": cloudcost.modal_gpu(),
            "note": "GPU work runs on a GPU host (Modal's GPU list is the default; AutoPipeline launches nothing itself)"}
CPU_RULE = {"local_max_minutes": 10, "modal_cpu": list(cloudcost.modal_cpu()),
            "note": "CPU work runs on this machine unless it would take more than about 10 minutes here; then on "
                    "a larger host, such as Modal with cpu=(16, 16) and threads to match"}
COMPUTE = {"gpu": GPU_RULE, "cpu": CPU_RULE}

CENTRENET_RELEASE = "https://github.com/ChaseHendrick/Scrolls/releases/download/umbilicus-v1/"
CENTRENET_WEIGHTS = {   # scripts/umbilicus/README.md, release umbilicus-v1 of public Scrolls
    "first": ("umbilicus-first-all.pt", "c9b50aae2876e00f50b7ade5cf9a6facc84fb0f8ad9667dddf5565e5f06ae854"),
    "zoom": ("umbilicus-zoom-all.pt", "0a06fe2e108fbb5f252455f93862336ec4013a535eb922676ae8f846406fb4bb"),
}
CENTRENET_UM = (8.0, 10.0)      # the 1.2 m scans the models trained on (slices.MODES "1.2m"); predict.py's 7.91 and
                                # 2.4 um modes are not offered here
ESTIMATORS = ("villa", "centrenet", "normals")

# stage -> {"settings": what the stage reads, "default": the choice a plan makes when it names none,
#           "choices": {name: description}}. "settings" in a choice is the settings it stands for.
STAGES = {
    "umbilicus": {
        "default": "catalog when the scan has a published axis, else villa",
        "choices": {
            "centerlines": {"origin": "ours", "by": "the published center lines dataset SharpMeow/vesuvius-center-lines "
                            "(kit/centerlines.py): the scan's line at a pinned revision, people's lines first "
                            "(the organisers', Drobkov, Dopico, Abd Elilah), the scroll center finder's where nobody "
                            "had made one", "kind": "published", "licence": "CC BY-NC 4.0 collection; each line "
                            "keeps its own licence (MIT, CC BY 4.0 or CC BY-NC 4.0)", "needs": [], "compute": None,
                            "limits": "all 22 prize-eligible scans and no others; the finder's lines are model "
                                      "output, and the CT end check flagged 4 of their 18 ends (usable_ends in the "
                                      "stage record)"},
            "catalog": {"origin": "community", "by": "the organisers' published centre line in the open-data bucket "
                        "(when the scan has one)", "kind": "published", "licence": "challenge open data",
                        "needs": [], "compute": None},
            "villa": {"origin": "community", "by": "villa's vc_gen_umbilicus (villa #1823 or later) on the scan's "
                      "published normal grids, run as a binary", "kind": "classical",
                      "licence": "GPL-3.0 (called, not copied)", "needs": ["binary:vc_gen_umbilicus"],
                      "compute": "cpu", "minutes": "about a minute per scroll (Interpretation, "
                      "a note of the source repository)"},
            "centrenet": {"origin": "ours", "by": "the scroll centre finder (scripts/umbilicus: two-stage U-Nets "
                          "on CT slices, weights from public Scrolls release umbilicus-v1)", "kind": "learned",
                          "licence": "this repository", "needs": ["torch", "weights:umbilicus-v1", "source:scripts/umbilicus"],
                          "compute": "cpu or gpu",
                          "minutes": "about 13 on 4 CPU cores for PHerc1203, 7 of them reading 0.25 to 0.65 GB of "
                                     "level-3 slices (scripts/umbilicus/README.md)",
                          "limits": "8 to 10 um scans only. The released all-scroll weights trained on the 13 "
                                    "published lines, so on those 13 scrolls their answer is not held out; the "
                                    "held-out score (README) used the fold weights"},
            "normals": {"origin": "ours", "by": "kit normalaxis: a numpy estimator from the same normal grids, "
                        "written from villa's documented behaviour", "kind": "classical", "licence": "this repository",
                        "needs": ["numpy"], "compute": "cpu",
                        "limits": "version 1 is experimental: no public comparison with villa's estimator exists, so prefer "
                                  "villa's. "
                                  "It needs no villa build and no torch: use it last in a fallback list"},
        },
    },
    "trace": {
        "default": "villa",
        "choices": {
            "villa": {"origin": "community", "by": "villa's vc_grow_seg_from_seed from every seed", "kind": "classical",
                      "licence": "GPL-3.0 (called, not copied)", "needs": ["binary:vc_grow_seg_from_seed"],
                      "compute": "cpu"},
        },     # plus every trace method an extension registers (kit/autopipe_ext_*.py), ours: trace_choices()
    },
    "flatten": {
        "default": "villa",
        "choices": {
            "villa": {"origin": "community", "by": "villa's vc_flatten (ABF++), kept only when its distortion passes",
                      "kind": "classical", "licence": "GPL-3.0 (called, not copied)", "needs": ["binary:vc_flatten"],
                      "compute": "cpu", "settings": {"flatten": {"enabled": True}}},
            "off": {"origin": None, "by": "no flattening: the traced surface goes to render as it is", "kind": "off",
                    "needs": [], "compute": None, "settings": {"flatten": {"enabled": False}}},
        },
    },
    "snap": {
        "default": "off",
        "choices": {
            "pred": {"origin": "community", "by": "Erwin Nieuwlaar's snap_meshes.py onto the surface prediction "
                     "(ported in kit/snap.py)", "kind": "classical", "licence": "see kit/snap.py",
                     "needs": ["numpy"], "compute": "cpu", "settings": {"render": {"snap": {"source": "pred"}}}},
            "ct": {"origin": "community", "by": "ScrollFiesta's RectoRefine midline onto the CT band (ported in "
                   "kit/snap.py)", "kind": "classical", "licence": "see kit/snap.py", "needs": ["numpy"],
                   "compute": "cpu", "settings": {"render": {"snap": {"source": "ct"}}}},
            "off": {"origin": None, "by": "no snap", "kind": "off", "needs": [], "compute": None,
                    "settings": {"render": {"snap": None}}},
        },
    },
    "repair": {
        "default": "off",
        "choices": {
            "barrier": {"origin": "ours", "by": "kit switchfix barrier: a trace rejected for a sheet switch keeps the "
                        "seed's part under kit.sheetgap's contact barrier", "kind": "classical",
                        "licence": "this repository", "needs": ["numpy", "scipy"], "compute": "cpu",
                        "settings": {"qa": {"repair": {"method": "barrier"}}}},
            "switchfix": {"origin": "ours", "by": "kit switchfix: a trace rejected for a sheet switch is cut back to "
                          "its seed's winding", "kind": "classical", "licence": "this repository", "needs": ["numpy"],
                          "compute": "cpu", "settings": {"qa": {"repair": {"method": "switchfix"}}}},
            "off": {"origin": None, "by": "reject only", "kind": "off", "needs": [], "compute": None,
                    "settings": {"qa": {"repair": None}}},
        },
    },
    "ink": {
        "default": "reader-v3",
        "choices": {},      # the models kit can fetch (kit.vc3d_catalog.KNOWN_MODELS): ink_choices()
    },
    "triage": {
        "default": "off",
        "choices": {
            "rowscore": {"origin": "community", "by": "Bullo27's text-row periodicity score (ported in "
                         "kit/rowscore.py)", "kind": "classical", "licence": "see kit/rowscore.py",
                         "needs": ["numpy", "tifffile"], "compute": "cpu",
                         "settings": {"triage": {"method": "rowscore"}}},
            "off": {"origin": None, "by": "no triage", "kind": "off", "needs": [], "compute": None,
                    "settings": {"triage": None}},
        },
    },
    # Crackle Check (23 Oct 2026, Chase: released tools are wired into AutoPipeline): the released Space's gate on
    # each surface's maps at report (kit/crackle.py)
    "crackle": {
        "default": "off",
        "choices": {
            "gate": {"origin": "ours", "by": "Crackle Check's control-set gate (ink-lens-gate-v1, the public Space "
                     "SharpMeow/crackle-check; kit/crackle.py)", "kind": "classical",
                     "licence": "this repository", "needs": ["numpy", "tifffile"], "compute": "cpu",
                     "settings": {"crackle": {"rule": "ink-lens-gate-v1"}}},
            "off": {"origin": None, "by": "no Crackle Check", "kind": "off", "needs": [], "compute": None,
                    "settings": {"crackle": None}},
        },
    },
    # the stack check (23 Oct 2026, the same rule): public Scrolls' kit stackcheck over the accepted traces at
    # report, ordered by distance from the umbilicus (kit/apstackcheck.py)
    "stackcheck": {
        "default": "off",
        "choices": {
            "stackcheck": {"origin": "ours", "by": "public Scrolls' kit stackcheck on the accepted "
                           "traces, inner to outer (kit/apstackcheck.py)", "kind": "classical",
                           "licence": "public Scrolls", "needs": ["numpy", "tifffile", "public:stackcheck"],
                           "compute": "cpu", "settings": {"stackcheck": True}},
            "off": {"origin": None, "by": "no stack check", "kind": "off", "needs": [], "compute": None,
                    "settings": {"stackcheck": None}},
        },
    },
}
# The ink ensemble as a swappable step of the ink stage (21 Oct 2026): how the planned models' maps of each variant are
# combined into one more map, "ensemble" (kit/autopipe.py ink.ensemble). An extension (kit/autopipe_ext_*.py) may add
# choices that also name the models, with register_ensemble; ensemble_choices() lists the ones that can run here.
STAGES["ensemble"] = {
    "default": "off",
    "choices": {
        "mean": {"origin": "ours", "by": "kit ensemble: the planned models' maps averaged", "kind": "classical",
                 "licence": "this repository", "needs": ["numpy", "tifffile"], "compute": "cpu",
                 "settings": {"ink": {"ensemble": {"method": "mean"}}}},
        "rank": {"origin": "ours", "by": "kit ensemble: the planned models' maps averaged as ranks",
                 "kind": "classical", "licence": "this repository", "needs": ["numpy", "tifffile"],
                 "compute": "cpu", "settings": {"ink": {"ensemble": {"method": "rank"}}}},
        "zscore": {"origin": "community", "by": "Erwin Nieuwlaar's z-score ensemble (PHerc. 343 First Letters), run "
                   "by kit inkensemble with equal weights", "kind": "classical",
                   "licence": "MIT arithmetic ported in kit/ensemble.py", "needs": ["numpy", "tifffile"],
                   "compute": "cpu", "settings": {"ink": {"ensemble": {"method": "zscore"}}}},
        "off": {"origin": None, "by": "no ensemble map", "kind": "off", "needs": [], "compute": None,
                "settings": {"ink": {"ensemble": None}}},
    },
}
SHADOW_STAGES = ("umbilicus",)
# Which pipeline stage each swappable stage acts in (kit.autopipe.STAGES): snap at render, repair at qa, triage at
# report
PIPELINE_STAGE = {"umbilicus": "umbilicus", "trace": "trace", "flatten": "flatten", "snap": "render",
                  "repair": "qa", "ink": "ink", "ensemble": "ink", "triage": "report",
                  "crackle": "report", "stackcheck": "report"}


class BackendError(ValueError):
    pass


def trace_choices():
    from . import autopipe
    out = dict(STAGES["trace"]["choices"])
    out["villa"] = {**out["villa"], "settings": {"trace": {n: None for n in autopipe.TRACE_METHODS}}}
    for name in sorted(autopipe.TRACE_METHODS):
        m = autopipe.TRACE_METHODS[name]
        out[name] = {"origin": "ours", "by": (getattr(m, "about", None) or f"trace method {name} "
                                             "(kit/autopipe_ext_*.py)"), "kind": getattr(m, "kind", "classical"),
                     "licence": "this repository", "needs": list(getattr(m, "needs", ["binary:vc_grow_seg_from_seed"])),
                     "compute": getattr(m, "compute", "cpu"), "settings": {"trace": {name: True}}}
        # a method may stand for several backends, each one setting of it (trace.judged: one tracer alone)
        for bname, b in sorted((getattr(m, "backends", None) or {}).items()):
            if bname in out or not b:
                continue
            out[bname] = {**{k: b.get(k) for k in ("origin", "by", "kind", "licence", "compute")},
                          "needs": list(b.get("needs") or []), "settings": {"trace": {name: b["settings"]}}}
    return out


def ink_choices():
    from . import vc3d_catalog
    out = {}
    for name, b in sorted(vc3d_catalog.BUILTIN_MODELS.items()):     # shipped in kit: nothing to fetch
        out[name] = {"origin": b["origin"], "by": b["about"], "kind": b["kind"], "licence": b["licence"],
                     "needs": list(b["needs"]), "compute": b["compute"], "settings": {"ink": {"models": [name]}}}
    for name, m in sorted(vc3d_catalog.KNOWN_MODELS.items()):
        out[name] = {"origin": "community", "by": m.get("about"), "kind": "learned",
                     "licence": "see its repository", "needs": ["torch", f"model:{name}"], "compute": "gpu",
                     "settings": {"ink": {"models": [name]}}}
    return out


ENSEMBLE_EXTENSIONS = {}


def register_ensemble(name, entry):
    """Add an ensemble choice: entry() returns its backend entry, with settings naming ink.models and ink.ensemble,
    or None when it cannot run here."""
    ENSEMBLE_EXTENSIONS[name] = entry


def ensemble_choices():
    from . import autopipe       # noqa: F401 - importing it loads the extensions, which register their choices
    out = dict(STAGES["ensemble"]["choices"])
    for name, entry in ENSEMBLE_EXTENSIONS.items():
        e = entry()
        if e is not None:
            out[name] = e
    return out


def ensemble_name(s):
    """The ensemble backend a plan's settings stand for: off, mean, rank, an extension's choice (its exact models and
    weights) or zscore (any other z-score setting)."""
    ens = s["ink"].get("ensemble")
    if not ens:
        return "off"
    if ens.get("method") != "zscore":
        return ens.get("method")
    for name, t in ensemble_choices().items():
        if name not in STAGES["ensemble"]["choices"] and s["ink"].get("models") == t["settings"]["ink"]["models"] \
                and ens == t["settings"]["ink"]["ensemble"]:
            return name
    return "zscore"


def choices(stage):
    if stage not in STAGES:
        raise BackendError(f"backends: no stage {stage}; stages: {', '.join(STAGES)}")
    if stage == "trace":
        return trace_choices()
    if stage == "ink":
        return ink_choices()
    if stage == "ensemble":
        return ensemble_choices()
    return STAGES[stage]["choices"]


def describe(stage, name):
    """{name, origin, by, kind, licence, compute} of one backend, for records and the provenance graph, plus
    registry {id, manifest_sha256, manifest} when a tool registry manifest says it is that backend
    (an AutoPipeline extension may add these), so graph.json's stage node names the manifest digest."""
    c = choices(stage).get(name)
    if c is None:
        return {"name": name, "origin": "unknown", "kind": "unknown"}
    out = {"name": name, **{k: c.get(k) for k in ("origin", "by", "kind", "licence", "compute")}}
    if c.get("registry"):
        out["registry"] = c["registry"]
    return out


def _names(value, stage):
    names = value if isinstance(value, list) else [value]
    if not names or not all(isinstance(n, str) and n for n in names):
        raise BackendError(f"backends.{stage} is a name or a list of names")
    if len(set(names)) != len(names):
        raise BackendError(f"backends.{stage} names one backend twice")
    known = choices(stage)
    if stage == "ink":
        return names     # registered models are checked by make_plan (check_models)
    bad = [n for n in names if n not in known]
    if bad:
        raise BackendError(f"backends.{stage}: no backend {', '.join(bad)}; choices: {', '.join(known)}")
    return names


def translate(backends):
    """The settings a `backends` object stands for. Refuses unknown stages and names, and lists where the stage takes
    one backend."""
    if not isinstance(backends, dict):
        raise BackendError("backends is an object: {stage: backend}, e.g. {\"umbilicus\": \"centrenet\"}")
    over = {}
    for stage, value in backends.items():
        if stage == "shadow":
            continue
        names = _names(value, stage)
        if stage == "umbilicus":
            for pub in ("catalog", "centerlines"):
                if pub in names[1:]:
                    raise BackendError(f"backends.umbilicus: {pub} can only come first (it is a published axis; an "
                                       "estimator follows it when the scan has none)")
            est = [n for n in names if n not in ("catalog", "centerlines")]
            if names[0] == "catalog":
                u = {"source": "auto" if est else "catalog"}
            elif names[0] == "centerlines":
                u = {"source": "centerlines", "centerlines": True}
            else:
                u = {"source": "estimate"}
            if est:
                u["estimator"] = est[0] if len(est) == 1 else est
            _deep(over, {"umbilicus": u})
        elif stage == "ink":
            _deep(over, {"ink": {"models": list(names)}})
        else:
            if len(names) > 1:
                raise BackendError(f"backends.{stage} takes one backend; a fallback list is for umbilicus")
            _deep(over, choices(stage)[names[0]].get("settings") or {})
    ens = backends.get("ensemble")
    if isinstance(ens, str) and "ink" in backends:
        fixed = ((choices("ensemble").get(ens) or {}).get("settings") or {}).get("ink", {}).get("models")
        if fixed is not None and list(fixed) != _names(backends["ink"], "ink"):
            raise BackendError(f"backends.ensemble {ens} names its own models {fixed}, and backends.ink names "
                               f"{backends['ink']}: give the models one way")
        if fixed is not None:
            over["ink"]["models"] = list(fixed)
    shadow = backends.get("shadow")
    if shadow is not None:
        if not isinstance(shadow, dict):
            raise BackendError("backends.shadow is an object: {\"umbilicus\": [backends run beside and compared]}")
        for stage, value in shadow.items():
            if stage not in SHADOW_STAGES:
                raise BackendError(f"backends.shadow: only {', '.join(SHADOW_STAGES)} runs shadow backends so far")
            names = _names(value, stage)
            _deep(over, {"umbilicus": {"shadow": list(names)}})
    return over


def _deep(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep(base[k], v)
        else:
            base[k] = json.loads(json.dumps(v))
    return base


def apply(settings):
    """settings with its `backends` shorthand turned into the settings it stands for (make_plan, before the plan is
    frozen). A setting given both ways must agree."""
    if not settings or "backends" not in settings:
        return settings
    settings = json.loads(json.dumps(settings))
    over = translate(settings.pop("backends"))
    _overlay(settings, over, "")
    return settings


def _overlay(base, over, path):
    for k, v in over.items():
        key = f"{path}{k}"
        if k not in base:
            base[k] = v
        elif isinstance(v, dict) and isinstance(base[k], dict):
            _overlay(base[k], v, f"{key}.")
        elif base[k] != v and not (v is None and base[k] is False):
            raise BackendError(f"backends sets {key} to {json.dumps(v)}, and the settings set it to "
                               f"{json.dumps(base[k])}: give it one way")


# The settings of a swappable step that belong to the arm, not to one backend (Run.snap_one, Run.repair_one): kept
# when the step stays on and only its backend changes. A snap's check, its reference and its sham control apply to
# either source, and a repair's min_area_share to any method; a source's own parameters (pred's max_off, threshold,
# jump, sigma and level) are the new backend's defaults.
ARM_SETTINGS = {"snap": ("render", "snap", ("check", "check_reference", "sham")),
                "repair": ("qa", "repair", ("min_area_share",))}


def swap_settings(settings, stage, backend):
    """A frozen plan's settings with one stage's backend replaced, everything else held as it was: the arm of a
    swap comparison (kit autopipeline swap). The new backend takes its own defaults (a snap swapped to ct takes
    kit snap's ct settings), and the arm keeps its own (ARM_SETTINGS: a sham snap stays a sham, a required check
    stays required). backend may be a list for umbilicus."""
    from . import autopipe
    s = json.loads(json.dumps(settings))
    over = translate({stage: backend})
    if stage == "umbilicus":
        s["umbilicus"].pop("estimator", None)
        if over["umbilicus"].get("source") not in ("auto", "estimate"):
            s["umbilicus"].pop("polish", None)      # people's line (catalog) is never polished
    elif stage == "trace":
        for name in list(s["trace"]):
            if name in autopipe.TRACE_METHODS:
                del s["trace"][name]
    elif stage in ARM_SETTINGS:
        sec, key, keep = ARM_SETTINGS[stage]
        old, new = s[sec].get(key), over[sec][key]
        if isinstance(old, dict) and isinstance(new, dict):
            for k in keep:
                if k in old:
                    new.setdefault(k, old[k])
    try:
        return autopipe._merge(s, over)
    except autopipe.AutoError as exc:
        raise BackendError(str(exc)) from exc


def estimator_chain(u):
    """The umbilicus estimators a plan's umbilicus settings name, in order (villa when none is named)."""
    est = u.get("estimator", "villa") if isinstance(u, dict) else u
    if est is None:
        return ["villa"]
    return list(est) if isinstance(est, list) else [est]


def check_settings(s, resolved=None):
    """make_plan's refusals for the settings this module adds: umbilicus.estimator and umbilicus.shadow (and
    umbilicus.polish, kit/axispolish.py)."""
    u = s["umbilicus"]
    est = u.get("estimator")
    if est is not None:
        names = est if isinstance(est, list) else [est]
        if not names or not all(isinstance(n, str) for n in names) or len(set(names)) != len(names):
            raise BackendError("umbilicus.estimator is one estimator or a list of different ones")
        bad = [n for n in names if n not in ESTIMATORS]
        if bad:
            raise BackendError(f"umbilicus.estimator: no estimator {', '.join(bad)}; estimators: {', '.join(ESTIMATORS)}")
        if u["source"] not in ("auto", "estimate", "centerlines"):
            raise BackendError("umbilicus.estimator chooses how an axis is estimated: it goes with umbilicus.source "
                               "auto or estimate, or centerlines (the fallback for a scan with no line)")
    cl = u.get("centerlines")
    if (u["source"] == "centerlines") != (cl is not None):
        raise BackendError("umbilicus.centerlines and umbilicus.source centerlines go together (centerlines true "
                           "takes the pinned revision and the default order)")
    if cl is not None:
        from . import centerlines
        try:
            centerlines.check(cl)
        except centerlines.CenterlineError as exc:
            raise BackendError(str(exc)) from exc
    pol = u.get("polish")
    if pol is not None:
        from . import axispolish
        try:
            axispolish.check(pol)
        except axispolish.PolishError as exc:
            raise BackendError(str(exc)) from exc
        if u["source"] not in ("auto", "estimate", "centerlines"):
            raise BackendError("umbilicus.polish polishes an estimated axis: it goes with umbilicus.source auto or "
                               "estimate (a catalog or given line is people's and is never moved), or centerlines, "
                               "where only the fallback estimate of a scan with no line is polished")
    sh = u.get("shadow")
    if sh is not None:
        if not isinstance(sh, list) or not all(isinstance(n, str) for n in sh) or len(set(sh)) != len(sh):
            raise BackendError("umbilicus.shadow is a list of different backends")
        bad = [n for n in sh if n not in ESTIMATORS + ("catalog", "centerlines")]
        if bad:
            raise BackendError(f"umbilicus.shadow: no backend {', '.join(bad)}; backends: catalog, centerlines, "
                               f"{', '.join(ESTIMATORS)}")
    if resolved is not None:
        line = None
        if cl is not None:
            from . import centerlines
            line = centerlines.pick(resolved.get("volume"), cl)
            if line is None and u.get("estimator") is None:
                raise BackendError(f"umbilicus.source centerlines: the center lines dataset has no line for "
                                   f"{resolved.get('volume')}; name umbilicus.estimator as a fallback, or use "
                                   "another source")
        chain = estimator_chain(u) if u["source"] in ("auto", "estimate") or (cl is not None and line is None) \
            else []
        # a chain that falls back from centrenet (the new-plan default [centrenet, villa]) is not refused on a scan
        # outside its range: the stage records why centrenet did not run and uses the next estimator
        used = (chain if chain[1:] == [] or chain[-1] == "centrenet" else []) + list(sh or [])
        um = resolved.get("voxel_um")
        if "centrenet" in used and um is not None and not CENTRENET_UM[0] <= um <= CENTRENET_UM[1]:
            raise BackendError(f"centrenet takes {CENTRENET_UM[0]:g} to {CENTRENET_UM[1]:g} um scans (the models "
                               f"trained on 8.64 and 9.362 um scans); {resolved.get('volume')} is {um:g} um")


def in_effect(stage, settings, record=None):
    """The backend a pipeline stage used or will use, from the frozen settings and, when given, the stage's record:
    {"name", "origin", "kind", ...}. Stages with no swappable tool get {"name": "kit"}."""
    s = settings
    rec = record or {}
    if stage == "umbilicus":
        src = rec.get("source")
        if src == "catalog":
            return describe("umbilicus", "catalog")
        if src == "centerlines":
            return {**describe("umbilicus", "centerlines"),
                    **{k: rec[k] for k in ("line_source", "line_kind", "usable_ends") if k in rec}}
        if src == "file":
            return {"name": "file", "origin": "given", "kind": "published", "by": "the plan's own axis file"}
        if rec.get("estimator"):
            return describe("umbilicus", rec["estimator"])
        u = s["umbilicus"]
        if u["source"] == "catalog":
            return describe("umbilicus", "catalog")
        if u["source"] == "centerlines":
            d = describe("umbilicus", "centerlines")
            return {**d, "fallback": estimator_chain(u)} if u.get("estimator") is not None else d
        if u["source"] not in ("auto", "estimate"):
            return {"name": "file", "origin": "given", "kind": "published", "by": "the plan's own axis file"}
        chain = estimator_chain(u)
        d = describe("umbilicus", chain[0])
        return {**d, "fallback": chain[1:]} if len(chain) > 1 else d
    if stage == "trace":
        from . import autopipe
        m = autopipe.trace_method(s)
        return describe("trace", m.name if m else "villa")
    if stage == "flatten":
        return describe("flatten", "villa" if s["flatten"]["enabled"] else "off")
    if stage == "render":
        snap = s["render"].get("snap")
        return {"name": "villa", "origin": "community", "kind": "classical",
                "by": "villa's vc_render_tifxyz after kit's chunk audit", "snap": describe("snap", snap["source"])
                if snap else describe("snap", "off")}
    if stage == "qa":
        rp = s["qa"].get("repair")
        return {"name": "kit", "origin": "ours", "kind": "classical", "by": "kit's fixed acceptance rule",
                "repair": describe("repair", rp["method"] if rp else "off")}
    if stage == "ink":
        from . import vc3d_catalog
        b = vc3d_catalog.BUILTIN_MODELS
        origins = {(b[m]["origin"] if m in b else "community") for m in s["ink"]["models"]}
        kinds = {(b[m]["kind"] if m in b else "learned") for m in s["ink"]["models"]}
        return {"name": "+".join(s["ink"]["models"]),
                "origin": origins.pop() if len(origins) == 1 else "mixed",
                "kind": kinds.pop() if len(kinds) == 1 else "mixed",
                "models": [describe("ink", m) for m in s["ink"]["models"]],
                "ensemble": describe("ensemble", ensemble_name(s))}
    if stage == "report":
        tri = s.get("triage")
        return {"name": "kit", "origin": "ours", "kind": "classical",
                "triage": describe("triage", tri["method"] if tri else "off"),
                "crackle": describe("crackle", "gate" if s.get("crackle") else "off"),
                "stackcheck": describe("stackcheck", "stackcheck" if s.get("stackcheck") else "off")}
    return {"name": "kit", "origin": "ours", "kind": "classical"}


# ---------------------------------------------------------------- what this machine has

def _has_module(name):
    import importlib.util
    return importlib.util.find_spec(name) is not None


def need_status(need, ctx=None, agent=None):
    """(status, detail, fix) for one requirement: status ready, fetch (downloaded on first use) or missing."""
    kind, _, arg = need.partition(":")
    if kind == "binary":
        tools = ctx.tools(required=False) if ctx is not None else None
        if tools is not None and tools.has(arg):
            return "ready", f"{arg} in {tools.bindir}", None
        return "missing", f"{arg} not found", ("build villa (kit vc3d build) or set VC_BIN to a folder "
                                               f"holding {arg}")
    if kind in ("numpy", "tifffile", "zarr"):
        if _has_module(kind):
            return "ready", f"{kind} in kit's Python", None
        return "missing", f"no {kind} in kit's Python ({sys.executable})", f"python3 -m pip install {kind}"
    if kind == "torch":
        if agent is None or ctx is None:
            return ("ready", "torch in this Python", None) if _has_module("torch") else \
                ("missing", "no torch here", "set KIT_INK_PYTHON to a Python with torch")
        env = agent.ink_env(ctx)
        if env.get("torch"):
            return "ready", f"torch in {env.get('python')}", None
        return "missing", f"no torch in {env.get('python')}", "set KIT_INK_PYTHON to a Python with torch"
    if kind == "weights" and arg == "umbilicus-v1":
        folder = weights_dir(ctx)
        have = [f for f, _ in CENTRENET_WEIGHTS.values() if (folder / f).is_file()]
        if len(have) == len(CENTRENET_WEIGHTS):
            return "ready", f"in {folder}", None
        return "fetch", f"downloaded on first use from {CENTRENET_RELEASE} (sha256 checked)", None
    if kind == "source":
        from . import kithome
        try:
            return "ready", str(kithome.source_file(arg)), None
        except kithome.MissingSource as exc:
            return "missing", str(exc), "install kit from a copy of the source (pip install -e .)"
    if kind == "model":
        from . import vc3d_catalog
        try:
            key, spec = registered_model(arg, ctx, agent)
        except vc3d_catalog.CatalogError as exc:
            return "missing", str(exc), "correct the model aliases file"
        if key is not None:
            who = arg if key == arg else f"{arg} (registered as {key})"
            if not isinstance(spec, dict) or spec.get("engine") not in ("villa", "torchscript", "v8in", "command"):
                return "missing", f"{who} has an invalid engine registration", "correct its models.json entry"
            if spec["engine"] == "command" and (not isinstance(spec.get("command"), list)
                    or not spec["command"] or not all(isinstance(x, str) and x for x in spec["command"])):
                return "missing", f"{who} needs a nonempty command argument list", "correct its models.json entry"
            try:
                agent._engine(ctx, {"model": arg})  # Validate paths, engine fields and pin; never run or fetch a model.
            except (agent.ToolError, OSError, TypeError, ValueError) as exc:
                return "missing", f"{who}: {exc}", "repair the registered model's files or models.json entry"
            return "ready", f"{who} registered", None
        if vc3d_catalog.builtin_model(arg) is not None:
            return "ready", f"{arg} is built into kit (kit.vc3d_catalog.BUILTIN_MODELS)", None
        if arg in vc3d_catalog.KNOWN_MODELS:
            return "fetch", f"{arg} is fetched on first use (kit vc3d models)", None
        return "missing", f"{arg} unknown", "register it (the models tool, action add)"
    if kind == "public" and arg == "stackcheck":
        from . import surfaudit
        root = surfaudit.public_root({"public_root": os.environ.get("SCROLLS_PUBLIC_ROOT")})
        if root is not None:
            return "ready", f"{root / 'kit' / 'stackcheck.py'}", None
        return "missing", "no public Scrolls kit/stackcheck.py", "clone ChaseHendrick/Scrolls beside this repository " \
            "or set SCROLLS_PUBLIC_ROOT"
    if kind == "import":
        return ("ready", f"imported: the plan names the folder {arg} wrote (trace.judged.imports.{arg}); make_plan "
                         "checks it and freezes its digest", None)
    return "missing", f"unknown requirement {need}", None


def registered_model(name, ctx=None, agent=None):
    """(key, entry) of the model registered on this machine under name or another of its names (the aliases file,
    kit.vc3d_catalog.find_model), or (None, None). A malformed aliases file raises vc3d_catalog.CatalogError."""
    if agent is None or ctx is None:
        return None, None
    from . import vc3d_catalog
    models = agent.load_models(ctx)
    key = vc3d_catalog.find_model(name, models)
    return (key, models[key]) if key is not None else (None, None)


def weights_dir(ctx=None):
    from . import kithome
    home = getattr(ctx, "home", None) or Path(kithome.path("work", "vc3d"))
    return Path(home) / "cache" / "umbilicus-v1"


def availability(stage, name, ctx=None, agent=None):
    c = choices(stage).get(name)
    spec = None
    if stage == "ink":
        from . import vc3d_catalog
        try:
            spec = registered_model(name, ctx, agent)[1]    # by this or another of its names
        except vc3d_catalog.CatalogError:
            spec = None                                     # need_status names the malformed aliases file
        if isinstance(spec, dict) and spec.get("engine") == "command":
            c = {**(c or {}), "needs": [f"model:{name}"], "compute": "external command"}
        elif c is None:
            c = {"needs": ["torch", f"model:{name}"], "compute": "gpu"}
    if c is None:
        raise BackendError(f"no backend {name} for {stage}")
    needs = []
    for n in c.get("needs") or []:
        st, detail, fix = need_status(n, ctx, agent)
        needs.append({"need": n, "status": st, "detail": detail, **({"fix": fix} if fix else {})})
    state = "missing" if any(n["status"] == "missing" for n in needs) else \
        "fetch" if any(n["status"] == "fetch" for n in needs) else "ready"
    identity = describe(stage, name)
    if stage == "ink" and isinstance(spec, dict):
        identity = {"name": name, "origin": "registered", "kind": spec.get("engine"),
                    "compute": c.get("compute"), "catalog_reference": identity}
    return {"stage": stage, "backend": name, "status": state, "needs": needs, **identity,
            **({"limits": c["limits"]} if c.get("limits") else {}),
            **({"minutes": c["minutes"]} if c.get("minutes") else {}),
            "where": placement(c.get("compute"))}


def placement(compute):
    """Where a job of this compute kind belongs under COMPUTE (a statement, not a launch)."""
    if compute is None:
        return None
    if compute == "gpu":
        return {"kind": "gpu", **GPU_RULE}
    if compute == "cpu or gpu":
        return {"kind": "cpu or gpu", "cpu": CPU_RULE, "gpu": GPU_RULE}
    if compute == "external command":
        return {"kind": compute, "cpu": CPU_RULE, "gpu": GPU_RULE,
                "note": "the registered command defines its dependencies and compute needs"}
    return {"kind": "cpu", **CPU_RULE}


def listing(ctx=None, agent=None):
    """Every stage's backends with origin, kind, needs and their status on this machine."""
    out = {}
    for stage in STAGES:
        names = set(choices(stage))
        if stage == "ink" and ctx is not None and agent is not None:
            names.update(agent.load_models(ctx))
        out[stage] = {"default": STAGES[stage]["default"], "acts_at": PIPELINE_STAGE[stage],
                      "backends": {n: availability(stage, n, ctx, agent) for n in sorted(names)}}
    return {"stages": out, "compute": COMPUTE,
            "note": "Swap one stage's backend and hold the rest (kit autopipeline swap) to see what that stage "
                    "changes; origins are ours or community, with whose."}


def preflight(plan, ctx=None, agent=None):
    """For a frozen plan: the backend each swappable stage will use, its status here, what is missing with a fix, and
    where each part belongs under COMPUTE. ready is true when nothing is missing (fetches happen on first use)."""
    s, r = plan["settings"], plan["resolved"]
    rows = []
    u = s["umbilicus"]
    if u["source"] in ("auto", "estimate") and not (u["source"] == "auto" and r.get("catalog_umbilicus")):
        chain = estimator_chain(u)
        avail = [availability("umbilicus", n, ctx, agent) for n in chain]
        first = next((a for a in avail if a["status"] != "missing"), None)
        rows.append({"stage": "umbilicus", "chain": avail, "status": first["status"] if first else "missing",
                     "will_use": first["backend"] if first else None})
    elif u["source"] in ("auto", "catalog"):
        rows.append({"stage": "umbilicus", **availability("umbilicus", "catalog", ctx, agent)})
    elif u["source"] == "centerlines":
        from . import centerlines
        line = centerlines.pick(r.get("volume"), u["centerlines"])
        if line is not None or u.get("estimator") is None:
            rows.append({"stage": "umbilicus", **availability("umbilicus", "centerlines", ctx, agent),
                         "line": {k: line[k] for k in ("file", "source", "kind", "usable_ends")} if line else None})
        else:
            chain = estimator_chain(u)
            avail = [availability("umbilicus", n, ctx, agent) for n in chain]
            first = next((a for a in avail if a["status"] != "missing"), None)
            rows.append({"stage": "umbilicus", "chain": avail, "status": first["status"] if first else "missing",
                         "will_use": first["backend"] if first else None, "line": None})
    for n in u.get("shadow") or []:
        rows.append({"stage": "umbilicus (shadow)", **availability("umbilicus", n, ctx, agent)})
    if not s.get("segment"):
        from . import autopipe
        m = autopipe.trace_method(s)
        rows.append({"stage": "trace", **availability("trace", m.name if m else "villa", ctx, agent)})
        if s["flatten"]["enabled"]:
            rows.append({"stage": "flatten", **availability("flatten", "villa", ctx, agent)})
    snap = s["render"].get("snap")
    repair = s["qa"].get("repair")
    if repair:
        rows.append(availability("repair", repair["method"], ctx, agent))
    if snap:
        rows.append({"stage": "render (snap)", **availability("snap", snap["source"], ctx, agent)})
    if s["ink"]["where"] != "skip":
        for m in s["ink"]["models"]:
            rows.append({"stage": "ink", **availability("ink", m, ctx, agent)})
    tri = s.get("triage")
    if tri:
        rows.append({"stage": "report (triage)", **availability("triage", tri["method"], ctx, agent)})
    if s.get("crackle"):
        rows.append({"stage": "report (crackle)", **availability("crackle", "gate", ctx, agent)})
    if s.get("stackcheck"):
        rows.append({"stage": "report (stackcheck)", **availability("stackcheck", "stackcheck", ctx, agent)})
    missing = [{"stage": x["stage"], "backend": x.get("backend") or x.get("will_use"), "need": n["need"],
                "detail": n["detail"], "fix": n.get("fix")}
               for x in rows for n in (x.get("needs") or []) if n["status"] == "missing"
               and x.get("status") == "missing"]
    for x in rows:
        if "chain" in x and x["status"] == "missing":
            missing += [{"stage": "umbilicus", "backend": a["backend"], "need": n["need"], "detail": n["detail"],
                         "fix": n.get("fix")} for a in x["chain"] for n in a["needs"] if n["status"] == "missing"]
    ink_where = s["ink"]["where"]
    ink_place = placement("gpu") if ink_where != "skip" else None
    ink_rows = [x for x in rows if x["stage"] == "ink"]
    if any((x.get("where") or {}).get("kind") == "external command" for x in ink_rows):
        ink_place = {"kind": "per model", "models": {x["backend"]: x["where"] for x in ink_rows}}
    return {"plan": plan.get("digest"), "sample": r.get("sample"), "volume": r.get("volume"), "rows": rows,
            "missing": missing, "ready": not missing,
            "ink": {"where": ink_where, "placement": ink_place},
            "compute": COMPUTE}


def main_json(obj):
    print(json.dumps(obj, indent=1, default=str))


if os.environ.get("KIT_APBACKENDS_SELFTEST"):      # pragma: no cover - a quick manual look
    main_json(listing())
