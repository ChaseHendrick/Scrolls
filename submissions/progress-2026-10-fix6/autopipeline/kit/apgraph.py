"""Causal links for AutoPipeline runs: which stage, backend, inputs and settings made each output, and what changes
when one of them is swapped. `python -m kit autopipeline graph|why|swap|diff`, and the agent tool's actions of
the same names.

graph   a provenance graph of one run folder (graph.json, written at the end of every run and on demand): nodes
        for the plan's inputs (scan, prediction, normal grids, published axis, ink models), every stage (status,
        backend in effect, the settings it reads and their digest) and every output file (made by which stage,
        for which surface, its size and, up to 4 MB a file and 256 MB a graph, its sha256); edges read, made
        and after (each stage runs on the state the stages before it left, so every earlier stage is upstream
        of it).
why     one output's chain: the stage and backend that made it, the settings and inputs that stage read, and the
        stages upstream, each with the backends swap would take for it (not the one in use, none the swapped
        plan's checks refuse) and its swap command.
swap    a sibling run of a frozen plan with one stage's backend replaced and everything else held: the same
        resolved inputs, the other settings unchanged (a snap's check and sham and a repair's area share stay with
        the arm), `swap_of` naming the original and the swapped stage's own backend before and after. That is the
        causal test of one stage (swap one factor, hold the rest); "off" is the ablation arm. A swap to the backend
        the plan or the run already uses is refused. With reuse, the stages before the swapped one are not run
        again: their records are carried over and their files linked, so the new run starts at the swapped stage.
diff    two runs compared: the settings and backends that differ, the first stage where they diverge, and every
        stage and surface record that changed downstream (volatile fields such as times left out). It reads them as
        one factor only when one run is exactly the other's swap and the records of the stages before the first
        divergent one are the same in both (upstream_changed lists those that are not).

What this does not do: it does not decide whether a difference is real. A swap's effect on one run is one sample;
repeated traces (trace.repeats) or several scrolls are needed before a difference means anything, and every map
or score in a run is model output, not a reading. Standard library only.
"""

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

GRAPH_VERSION = 1
HASH_MAX = 4 << 20         # files up to this size are hashed
HASH_BUDGET = 256 << 20    # and no more than this in all, per graph
COPY_MAX = 16 << 20        # reuse copies files up to this size and links larger ones
SKIP = {"plan.json", "state.json", "events.jsonl", "graph.json", "state.tmp", "swap.json"}
# the settings each pipeline stage reads (kit/autopipe.py); every stage also runs on the state the earlier ones left
STAGE_SETTINGS = {
    "acquire": ("purpose", "experiment", "volume", "prediction", "segment", "external_prediction"),
    "umbilicus": ("umbilicus",),
    "seeds": ("seeds",),
    "trace": ("trace",),
    "bench": (),
    "qa": ("qa", "strict"),
    "flatten": ("flatten",),
    "render": ("render", "strict"),
    "ink": ("ink",),
    "score": ("score",),
    "report": ("triage",),
}
# the plan's resolved inputs each stage reads
STAGE_INPUTS = {
    "acquire": ("volume_url", "prediction_url", "normal_grids_url", "external_prediction"),
    "umbilicus": ("catalog_umbilicus", "normal_grids_url", "volume_url"),
    "seeds": ("prediction_url", "volume_url"),
    "trace": ("prediction_url", "normal_grids_url", "volume_url"),
    "bench": ("winding_bench",),
    "qa": ("prediction_url", "volume_url", "normal_grids_url"),
    "flatten": (),
    "render": ("volume_url", "prediction_url", "transfer"),
    "ink": (),
    "score": ("benchmark", "transfer"),
    "report": (),
}
# the stage that first writes each top-level entry of a run folder (kit/autopipe.py's self.out / "..."), and the
# later stages that write into the same entry
OUT_STAGE = {
    "segment": "acquire", "published": "acquire", "report-surfaces": "acquire", "transfer-check": "acquire",
    "labels": "acquire", "umbilicus.json": "umbilicus", "umbilicus": "umbilicus", "umbilicus-shadow": "umbilicus",
    "seeds.json": "seeds", "traces": "trace", "bench": "bench", "repaired": "qa", "flat": "flatten",
    "trims": "render", "audits": "render", "snaps": "render", "renders": "render", "transfer": "render",
    "ink": "ink", "ink-turned": "ink", "orient": "ink", "modal-job.json": "ink", "scores": "score",
    "scores.json": "score", "triage.json": "report", "report.json": "report",
}
ALSO_WRITTEN = {"labels": ("score",), "transfer": ("score",)}


def entry_writers(name, settings):
    """The stages that write a top-level entry of a run folder, first writer first. Published labels are fetched
    at acquire for score.transfer and at score for a benchmark segment."""
    first = OUT_STAGE.get(name)
    if first is None:
        return ()
    if name == "labels" and not (settings.get("score") or {}).get("transfer"):
        return ("score",)
    return (first,) + ALSO_WRITTEN.get(name, ())


# the stage that writes each key of a surface's record in state.json (a trace method's record, under the method's
# name, is the trace's too: surface_key_stage)
SURFACE_KEY_STAGE = {
    "surface": "trace", "origin": "trace", "seed_index": "trace", "repeat": "trace", "trace": "trace",
    "bench": "bench", "qa": "qa", "accepted": "qa", "repair": "qa", "surface_traced": "qa",
    "render_surface": "flatten", "flatten": "flatten", "render": "render", "transfer": "render",
    "canvas_check": "render", "report_overlap": "render", "ink": "ink", "orient": "ink",
}
# surface record keys whose files later stages read: the trace is checked and flattened, the flattened (or original)
# copy is rendered
READ_BY = {"surface": ("qa", "flatten"), "render_surface": ("render",)}
VOLATILE = {"at", "seconds", "pid", "host", "started", "elapsed", "running", "mtime"}


class GraphError(ValueError):
    pass


def _stages():
    from . import autopipe
    return list(autopipe.STAGES)


def canonical_digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def load_run(out):
    out = Path(out)
    if not (out / "plan.json").is_file():
        raise GraphError(f"{out} has no plan.json: not an AutoPipeline run folder")
    plan = json.loads((out / "plan.json").read_text())
    state = json.loads((out / "state.json").read_text()) if (out / "state.json").is_file() else {}
    return out, plan, state


def settings_slice(settings, stage):
    return {k: settings.get(k) for k in STAGE_SETTINGS.get(stage, ()) if k in settings}


def surface_key_stage(sid, key, rec=None):
    """The stage that wrote one key of a surface's record, or None. A published segment's surface is acquire's, a
    trace method's record (s_trace keeps it under the method's name) the trace's, and the surface of a trace qa
    repaired (rec, the record, holds surface_traced: Run.repair_one moved the trace there) qa's."""
    if sid == "seg" or sid.startswith("ref-"):
        if key in ("surface", "origin", "reference"):
            return "acquire"
    if key == "surface" and rec and "surface_traced" in rec:
        return "qa"
    stage = SURFACE_KEY_STAGE.get(key)
    if stage is None:
        from . import autopipe
        if key in autopipe.TRACE_METHODS:
            return "trace"
    return stage


def _paths(value, out):
    """Strings in a record that name a file or folder: absolute paths, or paths relative to the run folder that
    exist."""
    found = []
    if isinstance(value, dict):
        for v in value.values():
            found += _paths(v, out)
    elif isinstance(value, list):
        for v in value:
            found += _paths(v, out)
    elif isinstance(value, str) and len(value) < 4096 and "\n" not in value and not value.startswith(
            ("http://", "https://", "s3://")):
        p = Path(value)
        if p.is_absolute():
            if p.exists():
                found.append(p)
        elif "/" in value and (out / p).exists():
            found.append(out / p)
    return found


def _rel(p, out):
    """p relative to the run folder, or None when it lies outside. The path as written is tried before the resolved
    one: an entry a reused swap linked (swap --reuse) resolves into the original run's folder, but it is this run's
    own entry, made by the stage that made it there."""
    for a, b in ((Path(os.path.abspath(p)), Path(os.path.abspath(out))), (Path(p).resolve(), Path(out).resolve())):
        try:
            return str(a.relative_to(b))
        except ValueError:
            pass
    return None


def _file_info(p, budget):
    """{bytes, mtime, sha256} of a file (sha256 up to HASH_MAX, while budget[0] lasts), {dir: true} of a folder."""
    p = Path(p)
    info = {}
    try:
        if p.is_dir():
            info["dir"] = True
        else:
            st = p.stat()
            info["bytes"] = st.st_size
            info["mtime"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))
            if st.st_size <= HASH_MAX and budget[0] >= st.st_size:
                budget[0] -= st.st_size
                h = hashlib.sha256()
                with open(p, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                info["sha256"] = h.hexdigest()
    except OSError as exc:
        info["error"] = str(exc)
    return info


def build(out):
    """The provenance graph of one run folder (see the module docstring)."""
    from . import apbackends
    out, plan, state = load_run(out)
    s, r = plan["settings"], plan["resolved"]
    nodes, edges = {}, []
    budget = [HASH_BUDGET]

    def edge(a, b, rel):
        e = {"from": a, "to": b, "rel": rel}
        if e not in edges:
            edges.append(e)

    for stage in _stages():
        for key in STAGE_INPUTS.get(stage, ()):
            if r.get(key) is not None:
                nid = f"input:{key}"
                nodes.setdefault(nid, {"id": nid, "kind": "input", "key": key, "value": r[key]})
                edge(nid, f"stage:{stage}", "read")
    if s["ink"]["where"] != "skip":
        from . import vc3d_catalog
        for m in s["ink"]["models"]:
            nid = f"model:{m}"
            known = vc3d_catalog.KNOWN_MODELS.get(m) or {}
            # A local registration can override a downloadable model's name. The catalog alone cannot identify
            # the weights this run actually used, so never present its checksum as a verified run input.
            nodes[nid] = {"id": nid, "kind": "model", "name": m,
                          **({"catalog_reference": {k: known.get(k) for k in ("repo", "revision", "sha256")}}
                             if known else {}),
                          "note": "model name from the plan; actual weights are not verified by this graph"}
            edge(nid, "stage:ink", "read")
    prev = None
    for stage in _stages():
        st = (state.get("stages") or {}).get(stage, {})
        sl = settings_slice(s, stage)
        nodes[f"stage:{stage}"] = {
            "id": f"stage:{stage}", "kind": "stage", "stage": stage, "status": st.get("status", "not run"),
            "at": st.get("at"), "seconds": st.get("seconds"), **({"error": st["error"]} if st.get("error") else {}),
            "backend": _pipeline_backend(plan, state, stage), "settings": sl,
            "settings_digest": canonical_digest(sl)}
        if prev:
            edge(f"stage:{prev}", f"stage:{stage}", "after")
        prev = stage
    reused = state.get("reused_from") or {}
    for stage in reused.get("stages") or []:
        nodes[f"stage:{stage}"]["reused_from"] = reused.get("run")

    def file_node(p, maker, sid=None):
        rel = _rel(p, out)
        if rel is None:
            nid = f"file:{Path(p).resolve()}"
            if nid not in nodes:
                nodes[nid] = {"id": nid, "kind": "file", "path": str(Path(p).resolve()), "outside_run": True,
                              **_file_info(p, budget)}
            return nid
        writers = entry_writers(rel.split("/")[0], s)
        nid = f"file:{rel}"
        if nid not in nodes:
            nodes[nid] = {"id": nid, "kind": "file", "path": rel, "made_by": writers[0] if writers else maker,
                          **({"also_written_by": list(writers[1:])} if len(writers) > 1 else {}), **_file_info(p, budget)}
        if sid:
            nodes[nid].setdefault("surfaces", [])
            if sid not in nodes[nid]["surfaces"]:
                nodes[nid]["surfaces"].append(sid)
        return nid

    for entry in sorted(out.iterdir()) if out.is_dir() else []:
        if entry.name in SKIP or entry.name.startswith("."):
            continue
        writers = entry_writers(entry.name, s)
        nid = file_node(entry, None)
        for w in writers:
            edge(f"stage:{w}", nid, "made")
    for sid, rec in sorted((state.get("surfaces") or {}).items()):
        snid = f"surface:{sid}"
        nodes[snid] = {"id": snid, "kind": "surface", "sid": sid, "accepted": rec.get("accepted"),
                       "origin": rec.get("origin")}
        for key, value in rec.items():
            stage = surface_key_stage(sid, key, rec)
            if stage is None:
                continue
            edge(f"stage:{stage}", snid, "made")
            for p in _paths(value, out):
                nid = file_node(p, stage, sid)
                maker = nodes[nid].get("made_by")
                if nodes[nid].get("outside_run"):
                    edge(nid, f"stage:{stage}", "recorded")     # made by its tool or read: the record cannot say
                elif stage in [maker, *nodes[nid].get("also_written_by", [])] or maker is None:
                    edge(f"stage:{stage}", nid, "made")
                else:
                    edge(nid, f"stage:{stage}", "read")
                for later in READ_BY.get(key, ()):
                    if (state.get("stages") or {}).get(later, {}).get("status") in ("done", "handoff"):
                        edge(nid, f"stage:{later}", "read")
                edge(nid, snid, "of")
    graph = {"version": GRAPH_VERSION, "run": str(out), "plan_digest": plan.get("digest"),
             "sample": r.get("sample"), "volume": r.get("volume"), "swap_of": plan.get("swap_of"),
             "nodes": list(nodes.values()), "edges": edges,
             "note": "Each stage runs on the state the earlier stages left, so every earlier stage is upstream of it "
                     "('after' edges). A swap (kit autopipeline swap) changes one stage's backend and holds the rest: "
                     "the causal test of that stage on this run. Model output, not a reading."}
    graph["digest"] = canonical_digest({k: graph[k] for k in ("plan_digest", "nodes", "edges")
                                        } | {"nodes": [{k: v for k, v in n.items() if k not in VOLATILE}
                                                       for n in graph["nodes"]]})
    return graph


def write(out):
    g = build(out)
    path = Path(out) / "graph.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(g, indent=1, default=str))
    tmp.replace(path)
    return path


def why(out, path):
    """One output's causal chain: who made it, with what backend, settings and inputs, and what upstream."""
    from . import apbackends
    g = build(out)
    out, plan, state = load_run(out)
    nodes = {n["id"]: n for n in g["nodes"]}
    p = Path(path)
    rel = _rel(p if p.is_absolute() else out / p, out)
    if rel is None:
        raise GraphError(f"{path} is not inside the run folder {out}")
    hit = nodes.get(f"file:{rel}")
    if hit is None:
        cands = [n for n in g["nodes"] if n["kind"] == "file" and not n.get("outside_run")
                 and (rel + "/").startswith(n["path"] + "/")]
        hit = max(cands, key=lambda n: len(n["path"]), default=None)
    if hit is None:
        writers = entry_writers(rel.split("/")[0], plan["settings"])
        if writers:
            hit = {"id": f"file:{rel}", "kind": "file", "path": rel, "made_by": writers[0], "missing": True}
        else:
            raise GraphError(f"{rel}: no stage of this run is known to have made it")
    maker = hit.get("made_by")
    order = _stages()
    chain = []
    if maker in order:
        for stage in order[:order.index(maker) + 1]:
            n = nodes[f"stage:{stage}"]
            chain.append({k: n.get(k) for k in ("stage", "status", "backend", "settings_digest", "reused_from")
                          if n.get(k) is not None})
    made = nodes.get(f"stage:{maker}", {})
    inputs = [nodes[e["from"]] for e in g["edges"] if e["to"] == f"stage:{maker}" and e["rel"] == "read"
              and e["from"] in nodes]
    # each upstream swap that swap itself would take: not the stage's own backend in use (NothingToSwap), not one
    # the swapped plan's checks refuse (named under refused, with why), and --reuse only where reuse is offered
    tests = []
    for st in apbackends.STAGES:
        pipe = apbackends.PIPELINE_STAGE[st]
        if maker in order and pipe in order and order.index(pipe) <= order.index(maker):
            names, refused = [], {}
            for name in apbackends.choices(st):
                try:
                    _arm(plan, state, st, name)
                except NothingToSwap:
                    continue
                except GraphError as exc:
                    refused[name] = str(exc)
                    continue
                names.append(name)
            try:
                _reuse(out, state, pipe, plan.get("digest"), plan["settings"])
                reuse = True
            except GraphError:
                reuse = False
            tests.append({"stage": st, "acts_at": pipe, "try": names[:6], "refused": refused, "reuse": reuse,
                          "command": f"python -m kit autopipeline swap {out} --stage {st} --backend <name>"
                                     + (" --reuse" if reuse else "")})
    return {"output": hit, "made_by": maker, "backend": made.get("backend"), "settings": made.get("settings"),
            "inputs": inputs, "upstream": chain, "surfaces": hit.get("surfaces"), "swap_tests": tests,
            "note": "Upstream means could have affected it: every earlier stage's state reaches later ones. Which "
                    "of them did is what a swap shows."}


# ---------------------------------------------------------------- swap

class NothingToSwap(GraphError):
    """The swap names the backend the plan or the run already uses."""


def _record(state, stage):
    """A pipeline stage's record when the stage finished (what it used, as it says), else None."""
    st = (state.get("stages") or {}).get(stage) or {}
    return st.get("record") if st.get("status") == "done" else None


def in_use(plan, state, stage):
    """The backend a swappable stage used in this run (from its pipeline stage's record, when that stage finished) or
    will use (from the plan): the stage's own entry, so a snap's is the snap source and not render's renderer. A plan
    whose axis source is auto takes the scan's published axis when the catalog has one."""
    from . import apbackends
    pipe = apbackends.PIPELINE_STAGE[stage]
    rec = _record(state, pipe)
    b = apbackends.in_effect(pipe, plan["settings"], rec)
    if stage != pipe:
        b = b.get(stage) or b
    if stage == "umbilicus" and rec is None and plan["settings"]["umbilicus"]["source"] == "auto" \
            and plan["resolved"].get("catalog_umbilicus"):
        b = apbackends.describe("umbilicus", "catalog")
    return b


def _pipeline_backend(plan, state, stage):
    """A pipeline stage's backend, resolving an unrun auto axis with the same rule as swap and why."""
    from . import apbackends
    if stage == "umbilicus":
        return in_use(plan, state, stage)
    rec = ((state.get("stages") or {}).get(stage) or {}).get("record")
    return apbackends.in_effect(stage, plan["settings"], rec)


def _arm(plan, state, stage, backend, models=None):
    """(the arm's settings, the backend they replace) for a swap of one stage's backend, or GraphError with the
    reason swap refuses it: NothingToSwap when the arm would start with the backend the plan or the run already uses
    (settings that differ only in the backend's own parameters, an auto axis that took the catalog's, or an axis
    list that changes only the fallbacks after it are not a swap). models: the ink models registered on this
    machine, checked for an ink swap only, since only an ink swap brings in models make_plan has not checked."""
    from . import apbackends
    if stage not in apbackends.STAGES:
        raise GraphError(f"swap: stage is one of {', '.join(apbackends.STAGES)}")
    try:
        s = apbackends.swap_settings(plan["settings"], stage, backend)
    except apbackends.BackendError as exc:
        raise GraphError(str(exc)) from exc
    if s == plan["settings"]:
        raise NothingToSwap(f"{stage} already uses {backend} in this plan: nothing to swap")
    frm = in_use(plan, state, stage)
    to = in_use({"settings": s, "resolved": plan["resolved"]}, {}, stage)
    if frm.get("name") == to.get("name"):
        ran = _record(state, apbackends.PIPELINE_STAGE[stage]) is not None
        raise NothingToSwap(f"{stage} already {'used' if ran else 'uses'} {to.get('name')} in this "
                            f"{'run' if ran else 'plan'}: nothing to swap"
                            + (" (a later name in the list runs only when the first gives no axis)"
                               if isinstance(backend, list) else ""))
    _check_new_settings(s, plan, models if stage in ("ink", "ensemble") else None)   # an extension choice names models too
    return s, frm


def _check_new_settings(s, plan, models=None):
    """make_plan's refusals, for settings that keep the plan's resolved inputs. models: the ink models registered on
    this machine (the models tool), so a misspelled ink model is refused here as make_plan refuses it; None skips that
    check (a caller with no machine to ask)."""
    from . import apbackends, autopipe
    r = plan["resolved"]
    try:
        autopipe.check_settings(s, r["sample"], models)
        apbackends.check_settings(s, r)
    except (autopipe.AutoError, apbackends.BackendError) as exc:
        raise GraphError(f"the swapped plan is refused: {exc}") from exc
    if (s["render"].get("snap") or {}).get("source") == "pred" and not r.get("prediction_url"):
        raise GraphError("the swapped plan is refused: render.snap with source pred needs a surface prediction, and "
                         "this plan resolves none")
    if s["umbilicus"]["source"] == "catalog" and not r.get("catalog_umbilicus"):
        raise GraphError(f"the swapped plan is refused: the catalog publishes no axis for {r.get('volume')}")


def swap(out, stage, backend, new_out=None, reuse=False, created=None, models=None):
    """A sibling run folder with one stage's backend replaced (see the module docstring). Returns its record; run it
    with `kit autopipeline run NEW`. models: the ink models registered on this machine (the models tool); an ink
    swap's new models are checked against them as make_plan checks a plan's, and None leaves that check out."""
    from . import apbackends, autopipe
    out, plan, state = load_run(out)
    autopipe.check_plan(plan)
    s, frm = _arm(plan, state, stage, backend, models)
    resolved = _arm_resolved(plan, s, stage)
    new = {"version": plan["version"], "created": created or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "settings": s, "resolved": resolved}
    new["digest"] = autopipe.digest({k: new[k] for k in ("version", "settings", "resolved")})
    pipe = apbackends.PIPELINE_STAGE[stage]
    # from: the swapped stage's own backend (a snap's source, not render's renderer); a step that acts inside another
    # pipeline stage also keeps that stage's whole entry (acts_at_backend)
    new["swap_of"] = {"run": str(out), "digest": plan["digest"], "stage": stage, "acts_at": pipe, "from": frm,
                      "to": backend}
    if stage != pipe:
        new["swap_of"]["acts_at_backend"] = apbackends.in_effect(pipe, plan["settings"], _record(state, pipe))
    dest = Path(new_out) if new_out else out.parent / f"{out.name}-swap-{stage}-{_slug(backend)}"
    if dest.exists() and any(dest.iterdir()):
        raise GraphError(f"{dest} is not empty: name another folder")
    if s["purpose"] == "target" and out.parent.resolve() not in dest.resolve().parents:
        raise GraphError("a target run's swap stays beside it, under experiments/<slug>/autopipe")
    reused = []
    new_state = None
    if reuse:
        new_state, reused, links = _reuse(out, state, pipe, new["digest"], plan["settings"])
    dest.mkdir(parents=True, exist_ok=True)
    if reuse:
        for name, how in links:
            src, dst = out / name, dest / name
            if how == "link":
                os.symlink(src.resolve(), dst)
            elif src.is_dir():
                shutil.copytree(src, dst, symlinks=True)
            else:
                shutil.copy2(src, dst)
        new_state["reused_from"] = {"run": str(out), "digest": plan["digest"], "stages": reused,
                                    "linked": [n for n, h in links if h == "link"],
                                    "copied": [n for n, h in links if h == "copy"],
                                    "note": "the carried-over records name files in the original run folder: keep "
                                            "it while this run is used"}
        (dest / "state.json").write_text(json.dumps(new_state, indent=1, default=str))
    (dest / "plan.json").write_text(json.dumps(new, indent=1))
    rec = {"out": str(dest), "plan": str(dest / "plan.json"), "digest": new["digest"], "swap_of": new["swap_of"],
           "reused_stages": reused, "next": f"python -m kit autopipeline run {dest}",
           "compare": f"python -m kit autopipeline diff {out} {dest}"}
    (dest / "swap.json").write_text(json.dumps(rec, indent=1, default=str))
    return rec


def _slug(backend):
    names = backend if isinstance(backend, list) else [backend]
    return "+".join(str(n) for n in names).replace("/", "_")


def _arm_resolved(plan, settings, stage):
    """Hold the frozen inputs; only a trace swap replaces the trace method's own resolved values."""
    from . import autopipe
    resolved = dict(plan["resolved"])
    if stage == "trace":
        for key in autopipe.trace_method_resolved(plan["settings"]):
            resolved.pop(key, None)
        resolved.update(autopipe.trace_method_resolved(settings))
    return resolved


def _reuse(out, state, pipe, digest, settings):
    """The new run's state with the stages before pipe carried over, and the top-level entries to copy or link."""
    order = _stages()
    if pipe == "qa":
        raise GraphError("reuse is not offered for a qa swap: a repair replaces surfaces in their records, so run the "
                         "swap without reuse")
    keep = order[:order.index(pipe)]
    stages = {k: v for k, v in (state.get("stages") or {}).items() if k in keep}
    for k in keep:
        st = (stages.get(k) or {}).get("status")
        if st not in ("done", "skipped"):
            raise GraphError(f"reuse needs every stage before {pipe} finished in {out}; {k} is {st or 'not run'}")
    surfaces = {}
    for sid, rec in (state.get("surfaces") or {}).items():
        kept = {}
        for key, value in rec.items():
            stage = surface_key_stage(sid, key, rec)
            if stage is None:
                raise GraphError(f"reuse: surface {sid} has a record key {key!r} this version cannot place in a stage; "
                                 "run the swap without reuse")
            if stage in keep:
                kept[key] = value
        if kept:
            surfaces[sid] = kept
    new_state = {"plan_digest": digest, "stages": json.loads(json.dumps(stages)), "surfaces": surfaces}
    if "trace" in keep:
        for k in ("planned_traces", "trace_failures"):
            if k in state:
                new_state[k] = state[k]
    # an entry only the kept stages write is linked (or copied, when a small file); one a later stage also writes
    # into is copied, so the new run never writes into the original's folder
    links = []
    for entry in sorted(out.iterdir()):
        writers = entry_writers(entry.name, settings)
        if not writers or writers[0] not in keep:
            continue
        shared = any(w not in keep for w in writers)
        small = entry.is_file() and entry.stat().st_size <= COPY_MAX
        links.append((entry.name, "copy" if shared or small else "link"))
    return new_state, keep, links


# ---------------------------------------------------------------- diff

def _flat(obj, prefix="", out=None, root=None):
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in VOLATILE:
                continue
            _flat(v, f"{prefix}.{k}" if prefix else str(k), out, root)
    elif isinstance(obj, list) and len(obj) <= 64 and any(isinstance(v, (dict, list)) for v in obj):
        for i, v in enumerate(obj):
            _flat(v, f"{prefix}[{i}]", out, root)
    else:
        if isinstance(obj, str) and root:
            for r in root:
                obj = obj.replace(r, "<run>")
        out[prefix] = obj
    return out


def _changes(a, b, limit=200):
    keys = sorted(set(a) | set(b))
    ch = [{"key": k, "a": a.get(k), "b": b.get(k)} for k in keys if a.get(k) != b.get(k)]
    return ch[:limit], len(ch)


def diff(a, b, limit=200):
    """Two runs compared (see the module docstring)."""
    from . import apbackends
    a, pa, sa = load_run(a)
    b, pb, sb = load_run(b)
    roots = sorted({str(a), str(a.resolve()), str(b), str(b.resolve())}, key=len, reverse=True)
    set_changes, n_set = _changes(_flat(pa["settings"]), _flat(pb["settings"]), limit)
    all_res, n_res = _changes(_flat(pa["resolved"], root=roots), _flat(pb["resolved"], root=roots), None)
    res_changes = all_res[:limit]
    order = _stages()
    stages, first = {}, None
    for stage in order:
        ra = ((sa.get("stages") or {}).get(stage) or {})
        rb = ((sb.get("stages") or {}).get(stage) or {})
        ba = _pipeline_backend(pa, sa, stage)
        bb = _pipeline_backend(pb, sb, stage)
        set_same = settings_slice(pa["settings"], stage) == settings_slice(pb["settings"], stage)
        if first is None and (ba != bb or not set_same):
            first = stage
        ch, n = _changes(_flat(ra, root=roots), _flat(rb, root=roots), limit)
        if n or ba != bb or not set_same:
            stages[stage] = {"status": [ra.get("status"), rb.get("status")],
                             **({"backend": [ba, bb]} if ba != bb else {}),
                             **({"settings_changed": True} if not set_same else {}),
                             "record_changes": n, "changes": ch}
    surfaces = {}
    for sid in sorted(set(sa.get("surfaces") or {}) | set(sb.get("surfaces") or {})):
        ra = (sa.get("surfaces") or {}).get(sid)
        rb = (sb.get("surfaces") or {}).get(sid)
        if ra is None or rb is None:
            surfaces[sid] = {"only_in": "a" if rb is None else "b"}
            continue
        ch, n = _changes(_flat(ra, root=roots), _flat(rb, root=roots), None)
        if ch:
            by_stage = {}
            rec = ra if "surface_traced" in ra else rb
            for c in ch:
                st = surface_key_stage(sid, c["key"].split(".")[0].split("[")[0], rec) or "unknown"
                by_stage[st] = by_stage.get(st, 0) + 1
            surfaces[sid] = {"accepted": [ra.get("accepted"), rb.get("accepted")], "changes_by_stage": by_stage,
                             "record_changes": n, "changes": ch[:limit]}
    swap, orig, arm = _swap_pair(pa, pb)
    # An earlier backend can differ because a fallback changed during a rerun. It is an upstream difference,
    # even when it is also the first divergent stage; use the declared swap's stage as the boundary.
    swapped_at = apbackends.PIPELINE_STAGE.get(swap.get("stage")) if swap else None
    upstream = _upstream(order, swapped_at or first, stages, surfaces)
    beyond = _beyond_swap(orig, arm, swap) if swap else None
    one_factor = bool(swap) and first is not None and not beyond and not upstream
    if one_factor:
        reading = ("one stage's backend changed and the rest held (a swap): the changes from "
                   f"{swapped_at} on are that stage's effect on this run, one sample")
    elif swap and beyond:
        reading = (f"one run names a swap of {swap.get('stage')} to {swap.get('to')}, but {beyond}: not a one-factor "
                   "comparison, so a change downstream cannot be put on one stage")
    elif swap and upstream:
        hold = ("a qa swap is never reused, so only repeated traces (trace.repeats) or several scrolls can separate "
                "its effect" if swap.get("acts_at") == "qa" else "make the arm with swap --reuse to carry those "
                "stages over")
        reading = (f"{swap.get('stage')} was swapped and the rest of the plan held, but the records of the stages "
                   f"before {swapped_at} differ too ({', '.join(upstream)}): the arm did not hold them (not run yet, or run "
                   "again without reuse, and the tracer does not give the same surface twice), so this is not a "
                   f"one-factor comparison and a change downstream cannot be put on {swap.get('stage')}; {hold}")
    else:
        reading = (f"{n_set} settings and {n_res} resolved inputs differ: not a one-factor comparison, so a change "
                   "downstream cannot be put on one stage")
    return {"a": str(a), "b": str(b), "swap": swap, "first_divergent_stage": first,
            "settings_changes": set_changes, "settings_changed": n_set, "resolved_changes": res_changes,
            "stages": stages, "surfaces": surfaces, "upstream_changed": upstream, "one_factor": one_factor,
            "reading": reading}


def _swap_pair(pa, pb):
    """(swap_of, the original plan, the arm's plan) when one of the two plans names the other as its original, else
    three Nones."""
    for orig, arm in ((pa, pb), (pb, pa)):
        sw = arm.get("swap_of")
        if isinstance(sw, dict) and sw.get("digest") and sw.get("digest") == orig.get("digest"):
            return sw, orig, arm
    return None, None, None


def _upstream(order, first, stages, surfaces):
    """The stages before the first divergent one whose records differ between the two runs, in pipeline order
    ("unknown" for a surface record key no stage is known to write): a one-factor comparison holds them. A surface
    only one run has was made at trace (or acquire, for a published segment), so it counts there."""
    if first is None:
        return []
    cut = order.index(first)
    found = {st for st in stages if order.index(st) < cut}
    for sid, v in surfaces.items():
        if "only_in" in v:
            made = surface_key_stage(sid, "surface")
            if made in order and order.index(made) < cut:
                found.add(made)
        for st in v.get("changes_by_stage") or {}:
            if st not in order or order.index(st) < cut:
                found.add(st)
    return sorted(found, key=lambda st: order.index(st) if st in order else len(order))


def _beyond_swap(orig, arm, swap):
    """None when the arm's plan is the swap its swap_of names and nothing else: its settings are this kit's
    swap_settings of the original's, and its resolved inputs are exactly those the swap derives (including a
    trace method's own values, such as an extension's rule digest). Otherwise what differs beyond the swap."""
    from . import apbackends, autopipe
    try:
        want = apbackends.swap_settings(orig["settings"], swap["stage"], swap["to"])
    except (apbackends.BackendError, KeyError, TypeError) as exc:
        return f"this kit cannot derive that swap again ({exc})"
    if swap.get("acts_at") != apbackends.PIPELINE_STAGE[swap["stage"]]:
        return "its recorded pipeline stage does not match the swapped backend"
    try:
        autopipe.check_trace_methods(want)      # as when the arm was checked: an extension may fill in defaults
        resolved = _arm_resolved(orig, want, swap["stage"])
    except autopipe.AutoError as exc:
        return f"this kit cannot derive that swap again ({exc})"
    if want == orig["settings"]:
        return "that swap changes no setting of the original"
    if want != arm["settings"]:
        n = len(_changes(_flat(want), _flat(arm["settings"]), None)[0])
        return f"its settings differ beyond the swap ({n} more)"
    if resolved != arm["resolved"]:
        extra, _ = _changes(_flat(resolved), _flat(arm["resolved"]), 5)
        return f"its resolved inputs differ beyond the swap ({', '.join(c['key'] for c in extra)})"
    return None
