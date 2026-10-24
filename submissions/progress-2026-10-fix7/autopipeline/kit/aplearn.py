"""AutoPipeline learns from its own runs, with no new compute: `python -m kit autopipeline learn ...`.

Every run already writes what it was asked to do (plan.json), what each stage did and how long it took
(state.json) and, with the hot-swap layer, which backend each stage used (graph.json). This module keeps a ledger
of those records across runs and turns it into advice for the next plan. Reading a run costs milliseconds: a few
JSON files, no map, no render, no tool. The learner never opens an ink map, a score, an AUC or a triage list, so
no label of any segment, held out, spent or not, can reach it.

ingest    one compact record per run folder into the ledger (latest wins), written by every run when it ends
          (Run.run) and on demand for older folders. Target runs are never written; a sample the reserve file holds
          (a note of the source repository) is recorded as excluded and never learned from, and a scroll or segment
          reserved later drops out of what was recorded before it (checked again on every read).
backfill  state files of past runs named in a manifest, read with the Modal presets that made them.
status    what the ledger holds, what it leaves out and why, and each trace arm's counts.
suggest   settings for the next plan of a scan, each with its evidence: how many repeats a seed needs
          (trace.repeats) for a given chance that at least one trace passes qa, never more for an arm that fails
          too often; an earlier run's estimated axis for the same scan (umbilicus.source), which skips the
          estimate; a different trace length only when the ledger says it beats the plan's with probability at
          least 0.95. What the ledger cannot support is kept as it is, and the reason is said. The scan is never
          changed. `plan --learned` applies the suggestion and leaves learned.json in the run folder; the plan's
          digest covers the settings, as for any plan.
estimate  each stage's expected seconds for a plan from measured stage times, and where the compute rule (AGENTS.md
          rule 10) puts the job.
review    a person's verdict on one traced surface (accept, reject or clear), appended to review.jsonl in its run
          folder, then the run read again.
evaluate  the check that can fail (PREREG): each unit predicted from the units known before it only, against no
          learning, with shuffled controls; only runs that start at or after CUTOFF count.

What it never does: it never changes DEFAULTS or a frozen plan, and it writes only the settings in LEARNABLE. The
acceptance rule, the flatten limits, the render audit, controls, readouts, models and random seeds are fixed rules
(a note of the source repository, "The fixed rules") and are refused in code. A suggestion is model output from past runs, not a
promise; whether following it makes runs better is what the preregistered check is for. Standard library only.
"""

import hashlib
import json
import math
import os
import platform
import random
import statistics
import time
from pathlib import Path

VERSION = 1
CUTOFF = "2026-10-17T00:00:00Z"     # runs whose first stage ends at or after this are fresh test data (PREREG)
PREREG = "a note of the source repository"
STORE = ("learn", "experience.jsonl")   # under the work home (KIT_VC3D_HOME, default <kit home>/work/vc3d)
REVIEW = "review.jsonl"                 # a person's verdicts, inside the run folder they are about
LEARNED = "learned.json"                # what `plan --learned` applied, beside plan.json
BACKFILL = "a note of the source repository"
PRESETS_FILE = "a script of the source repository"
ENV_OFF = "KIT_AUTOPIPE_LEARN"          # "0": runs write nothing to the ledger
# A folder holding any of these ran on Modal (_machine_of): the runner's own marker, written when a Modal CPU or GPU
# function starts on the folder (a script of the source repository write_runner_marker, since amendment (f)), and the
# driver's markers of a function that finished, which older folders hold alone
MODAL_MARKERS = ("runner-modal.json", "driver-cpu.json", "driver-gpu.json")

# Fixed before any data (the prereg, "Fixed constants"); changing one makes a new VERSION
PRIOR_STRENGTH = 2.0     # pseudo-traces of the pooled pass rate every arm starts from
OTHER_WEIGHT = 0.5       # the same arm's traces on other samples count half
REPEATS_TARGET = 0.8     # chance that at least one repeat of a seed passes qa
GATE = {"p_better": 0.95, "min_n": 5, "min_n_plan": 3}
FAILING = {"below": 0.2, "prob": 0.9, "min_n": 6}
FRESH_MIN = {"q1_units": 30, "q1_runs": 3, "q2_units": 20}
DETERMINISTIC = 3        # seeds traced more than once, all unanimous and none mixed: one repeat is enough
PERMUTATIONS = 999
SEED = 20261015
DRAWS = 20000            # Monte Carlo draws for posterior comparisons (seeded, so a suggestion repeats exactly)
CLIP = (0.01, 0.99)

# The only settings a suggestion may write. Everything else stays as the plan gives it (the scan too: an earlier
# axis is offered only for the scan the plan uses).
LEARNABLE = ("trace.repeats", "trace.generations", "umbilicus.source")
# Settings that decide a verdict, a readout, a control or a random draw, or that a preregistered rule set: never
# learned (refused by check_overlay even if LEARNABLE grew by mistake)
FIXED = ("purpose", "experiment", "segment", "prediction", "qa", "strict", "flatten.max_p95_stretch",
         "flatten.max_shear_deg_p95", "flatten.min_area_ratio", "flatten.max_area_ratio", "render.audit",
         "render.max_missing", "render.trim.min_area_share", "qa.repair.min_area_share", "render.snap.check",
         "render.snap.check_reference", "render.snap.sham", "ink", "score", "triage", "umbilicus.seed", "seeds.seed",
         "seeds.ct_check", "trace.timeout", "trace.min_area_cm", "external_prediction")
ARM_SKIP = ("threads", "repeats")       # how fast a trace runs and how often, not what it grows
SEEDS_SAMPLER = ("level", "radius_um", "min_spacing_um", "max_planes", "ct_check", "z_range")
UMB_SKIP = ("source", "shadow")         # an axis is reused only from a run with the same estimate settings
DECIDES = ("acquire", "umbilicus", "seeds", "trace", "bench", "qa")   # the stages that settle every trace's fate
REASONS = (("self-intersections", "self-intersections"), ("seating", "seating"), ("valid fraction", "valid fraction"),
           ("winding audit", "winding audit"), ("orientation", "orientation"), ("normal grids", "no normal grids"),
           ("loader rules", "loader rules"), ("check failed", "check failed"), ("seed check", "seed refused"),
           ("timeout", "timeout"), ("ran past", "timeout"), ("wrote no surface", "no surface"),
           ("tracer exited", "tracer exit"))


class LearnError(ValueError):
    """A request the caller can fix (a missing run folder, a setting outside LEARNABLE, a bad verdict)."""


# ---------------------------------------------------------------- small helpers

def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _flat(obj, prefix=""):
    """Dotted keys of a settings object: {"trace": {"repeats": 3}} -> {"trace.repeats": 3}. An object a key
    names whole (umbilicus.source's string, trace.params) stops the walk only where it is not a dict."""
    out = {}
    for k, v in (obj or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            out.update(_flat(v, key + "."))
        else:
            out[key] = v
    return out


def _deep(base, over):
    out = json.loads(json.dumps(base or {}))
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep(out[k], v)
        else:
            out[k] = v
    return out


def _put(obj, dotted, value):
    parts = dotted.split(".")
    for p in parts[:-1]:
        obj = obj.setdefault(p, {})
    obj[parts[-1]] = value


def given_keys(settings):
    """The dotted settings a caller named, with the backends shorthand turned into what it stands for."""
    return set(_flat(_backends_applied(settings)))


def _backends_applied(settings):
    if not settings or "backends" not in settings:
        return settings or {}
    try:
        from . import apbackends
    except ImportError:
        return settings
    try:
        return apbackends.apply(settings)
    except apbackends.BackendError as exc:
        raise LearnError(str(exc)) from exc


def merged_settings(settings):
    """A plan's settings as make_plan would merge them (DEFAULTS with the given ones over them)."""
    from . import autopipe
    try:
        return autopipe._merge(autopipe.DEFAULTS, _backends_applied(settings))
    except autopipe.AutoError as exc:
        raise LearnError(str(exc)) from exc


def check_overlay(overlay):
    """Refuse a suggestion that writes anything outside LEARNABLE, or anything under FIXED."""
    for key in _flat(overlay):
        if key not in LEARNABLE:
            raise LearnError(f"the learner writes only {', '.join(LEARNABLE)}; not {key}")
        if any(key == f or key.startswith(f + ".") for f in FIXED):
            raise LearnError(f"{key} is a fixed rule: never learned")
    return overlay


def on_modal(env):
    """True inside a Modal container: the runner's GPU chain sets KIT_AUTOPIPE_RUNNER=modal, and its CPU chains run
    `kit autopipe run` without it, but Modal sets MODAL_TASK_ID in every container it starts (the 15 Oct offline
    pilot's container records carry it)."""
    return env.get("KIT_AUTOPIPE_RUNNER") == "modal" or bool(env.get("MODAL_TASK_ID"))


def machine(env=None):
    """This machine as the ledger groups timings: {"key", "runner", "system", "arch", "cpus"}. Inside a Modal
    container the key is "modal"."""
    env = os.environ if env is None else env
    runner = "modal" if on_modal(env) else env.get("KIT_AUTOPIPE_RUNNER") or "local"
    try:
        from . import vc3d
        cpus = vc3d.cpu_limit()
    except Exception:       # noqa: BLE001 (a count is all this wants)
        cpus = os.cpu_count()
    m = {"runner": runner, "system": platform.system(), "arch": platform.machine(), "cpus": cpus}
    m["key"] = "modal" if runner == "modal" else f"{m['system']}-{m['arch']}-{cpus}cpu"
    return m


def store_path(home):
    return Path(home).joinpath(*STORE)


# ---------------------------------------------------------------- what is excluded

def _unreadable(exc):
    return LearnError(f"{exc}; the learner reads and writes nothing until it is fixed (a held-out scroll must never "
                      "slip in)")


def held_out_samples(path=None):
    """Samples the reserve file holds a segment of: whole scrolls kept for a one-time score, never learned from.
    REPORT_ONLY's report surface (0841-ag405) is excluded per segment, not per scroll. A copy without the reserve
    file (the public release) holds none. A reserve file that does not parse stops the learner (LearnError), as it
    stops planning: failing open would learn from a held-out scroll."""
    from . import autopipe
    path = Path(path) if path else autopipe.RESERVED_FILE
    if not path.exists():
        return []
    try:
        autopipe.reserved_segments(path)        # planning's own check of the file
        entries = json.loads(path.read_text())
    except (autopipe.AutoError, OSError, ValueError) as exc:
        raise _unreadable(exc) from None
    return sorted({e["sample"] for e in entries})


def reserved_why(sample, seg):
    """Why a run here never scores this segment (a BENCHMARKS key, or a segment id on sample), or None."""
    from . import autopipe
    smp = autopipe.BENCHMARKS[seg]["sample"] if seg in autopipe.BENCHMARKS else sample
    try:
        return autopipe.reserved(smp, seg)
    except autopipe.AutoError as exc:
        raise _unreadable(exc) from None


def scope(plan):
    """The published segments a plan reads or scores: what the reserve check needs again when the file grows."""
    s = plan.get("settings") or {}
    return {"segment": s.get("segment"),
            "transfer": list(((s.get("score") or {}).get("transfer") or {}).get("segments") or [])}


def _scope_why(sample, sc, held):
    if sample in held:
        return (f"{sample} holds AutoPipeline's held-out segments (a note of the source repository): nothing on "
                "this scroll is learned from")
    if sc.get("segment"):
        why = reserved_why(sample, sc["segment"])
        if why:
            return f"its segment {sc['segment']} is reserved: {why}"
    for key in sc.get("transfer") or []:
        why = reserved_why(sample, key)
        if why:
            return f"it scores the reserved segment {key}: {why}"
    return None


def in_experiment(folder):
    """Whether a folder lies where target runs go, experiments/<experiment>/autopipe/... (autopipe.run_folder),
    under any kit home: such a run is a target run's, whatever its plan says."""
    parts = Path(folder).resolve().parts
    return any(p == "experiments" and i + 2 < len(parts) and parts[i + 2] == "autopipe" for i, p in enumerate(parts))


def exclusion(plan, folder=None):
    """Why nothing of this run is learned from, or None. "target" means the run is never written at all."""
    s, r = plan.get("settings") or {}, plan.get("resolved") or {}
    if s.get("purpose") == "target" or (folder is not None and in_experiment(folder)):
        return "target"
    return _scope_why(r.get("sample"), scope(plan), set(held_out_samples()))


def excluded_now(r, held):
    """Why a ledger record is not learned from today: its own exclusion when written, or the reserve file as it is
    now (held: held_out_samples()), which may have grown since."""
    if r.get("excluded"):
        return r["excluded"]
    sc = r.get("scope")
    if not isinstance(sc, dict):    # a record from before scope was written: its segment is in planned
        sc = {"segment": (r.get("planned") or {}).get("segment"), "transfer": []}
    return _scope_why(r.get("sample"), sc, held)


# ---------------------------------------------------------------- one run's record

def trace_backend(s):
    """The trace backend in effect (kit/apbackends.py), named without loading a method this kit lacks."""
    from . import autopipe
    try:
        from . import apbackends
        return apbackends.in_effect("trace", s)["name"]
    except Exception:       # noqa: BLE001 (a plan from a kit with a trace method this one lacks)
        names = [k for k, v in (s.get("trace") or {}).items() if v is not None and k not in autopipe.DEFAULTS["trace"]
                 and f"trace.{k}" not in autopipe.PLAIN_OPTIONAL]
        return names[0] if names else "villa"


def trace_arm(s):
    """(arm, key): what decides a trace's geometry and its qa verdict, and its digest. Threads and repeats are left
    out: they change how fast and how often, not what grows."""
    t = {k: v for k, v in (s.get("trace") or {}).items() if k not in ARM_SKIP and v is not None}
    if t.get("params"):
        t["params"] = digest(t["params"])[:12]
    seeds = s.get("seeds") or {}
    arm = {"trace": trace_backend(s), "settings": t,
           "seeds": {"given": True} if seeds.get("points") else
           {"given": False, **{k: seeds.get(k) for k in SEEDS_SAMPLER}},
           "rule": digest({"qa": s.get("qa"), "strict": s.get("strict")})[:12]}
    return arm, digest(arm)[:16]


def arm_label(arm):
    t = arm["settings"]
    bits = [arm["trace"], f"{t.get('generations')} generations", f"grids {t.get('normal_grids', 'off')}",
            "given seeds" if arm["seeds"]["given"] else "sampled seeds"]
    if t.get("params"):
        bits.append(f"params {t['params']}")
    extra = sorted(set(t) - {"generations", "normal_grids", "params", "min_area_cm", "timeout"})
    bits += extra
    return ", ".join(str(b) for b in bits)


def reason_kinds(reasons):
    out = []
    for text in reasons or []:
        low = str(text).lower()
        for needle, kind in REASONS:
            if needle in low and kind not in out:
                out.append(kind)
                break
    return out


def reviews(folder):
    """{sid: the latest verdict line} from a run folder's review.jsonl. A "clear" is a verdict line too: it takes the
    verdict back, and its time stays on record so that another copy of the run cannot bring the verdict back
    (_merge_reviews)."""
    out = {}
    p = Path(folder) / REVIEW
    if not p.is_file():
        return out
    for line in p.read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict) or not isinstance(r.get("sid"), str):
            continue
        if r.get("verdict") in ("accept", "reject", "clear"):
            out[r["sid"]] = r
    return out


def _graph_backends(folder):
    g = _json(Path(folder) / "graph.json") or {}
    return {n.get("stage"): (n.get("backend") or {}).get("name") for n in g.get("nodes") or []
            if isinstance(n, dict) and n.get("kind") == "stage"}


def _stage_backend(stage, s, record, from_graph):
    if from_graph.get(stage):
        return from_graph[stage]
    try:
        from . import apbackends
        return apbackends.in_effect(stage, s, record if isinstance(record, dict) else None)["name"]
    except Exception:       # noqa: BLE001 (a record of a shape this kit does not know)
        return None


def harvest(folder, plan=None, state=None, machine_info=None, source="run", run=None):
    """(record, None) for one run folder, or (None, why) when nothing of it may be written (a target run). A run
    another rule leaves out gets a short record saying why, so status can count it."""
    from . import autopipe
    folder = Path(folder)
    if plan is None:
        plan = _json(folder / "plan.json")
        if not isinstance(plan, dict) or "settings" not in plan:
            raise LearnError(f"{folder} has no readable plan.json: not an AutoPipeline run folder")
    if state is None:
        state = _json(folder / "state.json") or {}
    s, r = plan["settings"], plan.get("resolved") or {}
    why = exclusion(plan, folder)
    if why == "target":
        return None, ("a target run: its records stay in its experiment folder and nothing of it is learned from "
                      "(AGENTS.md rule 1; its settings are frozen by its ledger experiment before any map)")
    base = {"v": VERSION, "kind": "run", "source": source,
            "run": str(run or (folder.resolve() if source == "run" else folder)), "plan_digest": plan.get("digest"),
            "plan_version": plan.get("version"), "sample": r.get("sample"), "volume": r.get("volume"),
            "scope": scope(plan), "ingested": now()}
    if why:
        return {**base, "excluded": why}, None
    stages_in = state.get("stages") or {}
    reused = set((state.get("reused_from") or {}).get("stages") or [])
    times = _times(stages_in, reused)
    graph = _graph_backends(folder) if source == "run" else {}
    stages = {}
    for st in autopipe.STAGES:
        x = stages_in.get(st)
        if not isinstance(x, dict):
            continue
        e = {"status": x.get("status"), "at": x.get("at"),
             "seconds": None if st in reused else x.get("seconds"),
             "backend": _stage_backend(st, s, x.get("record"), graph)}
        if x.get("status") == "failed":
            e["kind"] = x.get("kind") or "infrastructure"
        if st in reused:
            e["reused_from"] = (state.get("reused_from") or {}).get("run")
        stages[st] = e
    arm, key = trace_arm(s)
    surfaces = state.get("surfaces") or {}
    verdicts = reviews(folder) if source == "run" else {}
    bench_rule = bool(r.get("winding_bench"))
    traces = []
    for e in autopipe.trace_entries(state) if "trace" not in reused else []:
        sid, f = e["sid"], e["failure"] or {}
        rec = surfaces.get(sid) or {}
        qa = rec.get("qa") or {}
        grid = (qa.get("check_surface") or {}).get("grid") or {}
        reason = str(f.get("reason") or "")
        kinds = reason_kinds(qa.get("reasons") if f.get("stage") == "qa" else [reason]) if f else []
        if e["accepted"]:
            outcome, why_void = "accepted", None
        elif f.get("kind") == "ours" and f.get("stage") in ("trace", "qa"):
            outcome, why_void = "rejected", None
            if f["stage"] == "trace" and "seed check refused" in reason:
                outcome, why_void = "void", "the seed check refused the seed: a fact about the seed, not the trace"
        else:
            outcome, why_void = "void", f"infrastructure: {reason[:160]}" if reason else "not checked"
        if outcome != "void" and plan.get("version") == 1:
            outcome, why_void = "void", "plan version 1 traced without normal grids"
        if outcome != "void" and e.get("partial"):
            # a partial surface (AutoPipeline's trace.budget) stopped short of the generations its arm names: it is
            # not the trace the arm describes, so it neither counts for nor against the arm (and repeat agreement
            # never mixes stops for time with the tracer's own variation)
            stop = (rec.get("trace") or {}).get("stop") or {}
            outcome, why_void = "void", (f"partial surface ({e['partial']}): stopped after generation "
                                         f"{stop.get('generations_done')} of "
                                         f"{(stop.get('generations_planned') or 0) - 1 or 'its plan'}")
        if outcome != "void" and bench_rule:
            split = (rec.get("bench") or {}).get("dominant_split")
            if split != "tune":
                outcome, why_void = "void", (f"bench split {split or 'not scored'}: on this scan only traces on tune "
                                             "windings are learned from (the report windings belong to the tracing bar)")
        # the tracer ran it unless the trace stage never reached it (no record), the seed check stopped it first,
        # or the trace tool raised before the tracer started (trace_failure: "the trace tool could not run")
        ran = sid in surfaces or (f.get("stage") == "trace" and "seed check refused" not in reason
                                  and not reason.startswith("no record of this trace")
                                  and not reason.startswith("the trace tool could not run")
                                  and not f.get("deferred"))
        t = {"sid": sid, "seed_index": e.get("seed_index"), "repeat": e.get("repeat", 0), "outcome": outcome,
             "stage": f.get("stage"), "reasons": kinds, "rendered": bool(e.get("rendered")),
             "area_cm2": grid.get("area_cm2", (rec.get("trace") or {}).get("area_cm2")),
             "max_gen": grid.get("max_gen"), "ran": ran}
        if e.get("partial"):
            t["partial"] = e["partial"]
        if why_void:
            t["why"] = why_void
        v = verdicts.get(sid)
        if v:
            if v["verdict"] != "clear":
                t["review"] = v["verdict"]
            if isinstance(v.get("at"), str):
                t["review_at"] = v["at"]        # the verdict's own time: the latest across copies wins (load)
        traces.append(t)
    n_traced = sum(1 for t in traces if t.pop("ran"))
    # the trace stage's seconds are its last attempt's: a stage that names the traces it ran in that attempt (its
    # record's "ran", written since amendment (e)) is divided by those, so a resumed stage is not divided by
    # traces an earlier attempt made
    rec_tr = (stages_in.get("trace") or {}).get("record")
    listed = isinstance(rec_tr, dict) and isinstance(rec_tr.get("ran"), list) and "trace" not in reused
    if listed:
        n_traced = len(rec_tr["ran"])
    tr = stages.get("trace")
    if tr and tr.get("seconds") and n_traced:
        tr["per_trace"] = tr["seconds"] / n_traced      # unrounded (amendment (e)): Q2 compares exact values
        tr["traces"] = n_traced
        # where the count came from: a fresh run's trace unit needs the stage's own list (amendment (f), time_units)
        tr["traces_from"] = "ran" if listed else "outcomes"
    seeds = s.get("seeds") or {}
    if s.get("segment"):
        arm, key = None, None
    rec = {**base, "excluded": None, "purpose": s.get("purpose"), "voxel_um": r.get("voxel_um"),
           "swap_of": plan.get("swap_of"), **times, "machine": machine_info,
           "arm": arm, "arm_key": key, "arm_label": arm_label(arm) if arm else "a published segment: nothing traced",
           "planned": {"seeds": len(seeds.get("points") or []) or seeds.get("count"),
                       "repeats": (s.get("trace") or {}).get("repeats") or 1,
                       "generations": (s.get("trace") or {}).get("generations"),
                       "threads": (s.get("trace") or {}).get("threads"), "segment": s.get("segment")},
           "stages": stages, "traces": traces, "umbilicus": _umbilicus(folder, s, r, stages_in.get("umbilicus"),
                                                                     source)}
    return rec, None


def _times(stages_in, reused):
    """{"started", "decided", "ended"} of a run, from the stages it ran itself (not those carried over by swap
    --reuse). started: its first stage's end, which decides whether the run is fresh test data (a run read and
    resumed later stays what it was). decided: when the last stage that settles a trace's fate ended (DECIDES), the
    time its trace units are known. ended: its last stage's end, the report stage left out, since every resume
    writes the report again and it decides nothing."""
    own = {st: x["at"] for st, x in stages_in.items()
           if isinstance(x, dict) and isinstance(x.get("at"), str) and st not in reused}
    if not own:
        return {"started": None, "decided": None, "ended": None}
    late = [at for st, at in own.items() if st != "report"] or list(own.values())
    dec = [at for st, at in own.items() if st in DECIDES]
    return {"started": min(own.values()), "decided": max(dec) if dec else max(late), "ended": max(late)}


def _umbilicus(folder, s, r, st, source):
    """What reusing this run's axis needs: the estimate's settings and its hash-bound file. A stage receipt's
    sha256 is authoritative. Older stages without one retain file-observation compatibility, explicitly labeled
    as such: the hash then binds only the bytes seen at harvest, not what the historical stage used."""
    if not isinstance(st, dict) or st.get("status") != "done" or not isinstance(st.get("record"), dict):
        return None
    rec = st["record"]
    u = s.get("umbilicus") or {}
    out = {"source": rec.get("source"), "estimator": rec.get("estimator"), "asked": u.get("source"),
           "seconds": st.get("seconds"), "kept": rec.get("kept"),
           "settings": digest({k: v for k, v in u.items() if k not in UMB_SKIP})[:16],
           "grids": r.get("normal_grids_url"), "volume": r.get("volume"),
           # an axis from a prediction's own grids, or from one box of it (direction only), is that plan's alone
           "axis_grids": (r.get("external_prediction") or {}).get("axis_grids"), "box_axis": bool(rec.get("box_axis"))}
    p = Path(folder) / "umbilicus.json"
    if source == "run" and p.is_file():
        observed = _sha256(p)
        out["sha256_source"] = "stage_receipt" if "sha256" in rec else "file_at_harvest"
        out["sha256"] = rec["sha256"] if "sha256" in rec else observed
        if out["sha256"] != observed:
            out["reuse_refused"] = "the axis file differs from the completed stage's sha256 receipt"
        else:
            out["path"] = str(p.resolve())
    return out


# ---------------------------------------------------------------- the ledger

def append(path, records):
    """Append records to the ledger, one JSON line each, under a lock when the platform has one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in records)
    with open(path, "a", encoding="utf-8") as fh:
        try:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        fh.write(lines)
        fh.flush()


def latest(path):
    """{(source, run): that folder's latest record}. Lines that do not parse, and records of another learner
    VERSION, are skipped."""
    path = Path(path)
    best = {}
    if not path.is_file():
        return best
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not well_formed(r):
            continue
        key = (r.get("source"), r.get("run"))
        old = best.get(key)
        if old is None or (r.get("ingested") or "") >= (old.get("ingested") or ""):
            best[key] = r
    return best


def well_formed(r):
    """A ledger line this learner can read: a run record of this VERSION whose parts have the shapes harvest writes
    (a hand-edited or foreign line is skipped, never a crash in every command)."""
    if not isinstance(r, dict) or r.get("kind") != "run" or r.get("v") != VERSION:
        return False
    if not isinstance(r.get("run"), str) or r.get("source") not in ("run", "backfill"):
        return False
    for k in ("sample", "volume", "plan_digest", "started", "decided", "ended", "excluded", "arm_key", "ingested"):
        if r.get(k) is not None and not isinstance(r[k], str):
            return False
    for k in ("machine", "planned", "arm", "umbilicus", "scope"):
        if r.get(k) is not None and not isinstance(r[k], dict):
            return False
    if not isinstance(r.get("stages") or {}, dict) or not all(isinstance(e, dict) for e in (r.get("stages") or
                                                                                            {}).values()):
        return False
    for e in (r.get("stages") or {}).values():
        if not _shaped(e, str_keys=("status", "at", "machine", "kind", "reused_from", "backend", "traces_from"),
                       num_keys=("seconds", "per_trace", "traces")):
            return False
    sc = r.get("scope")
    if sc is not None and (not _shaped(sc, str_keys=("segment",)) or not isinstance(sc.get("transfer") or [], list)
                           or not all(isinstance(k, str) for k in sc.get("transfer") or [])):
        return False
    if r.get("planned") is not None and not _shaped(r["planned"], str_keys=("segment",),
                                                    num_keys=("seeds", "repeats", "generations", "threads")):
        return False
    traces = r.get("traces") or []
    return isinstance(traces, list) and all(isinstance(t, dict) and isinstance(t.get("outcome"), str)
                                            and _shaped(t, str_keys=("sid", "review", "review_at", "stage", "why"))
                                            for t in traces)


def _shaped(d, str_keys=(), num_keys=()):
    """d's named keys are absent, None, or of their type (a hand-edited nested value never crashes a command)."""
    if not isinstance(d, dict):
        return False
    for k in str_keys:
        if d.get(k) is not None and not isinstance(d[k], str):
            return False
    for k in num_keys:
        if d.get(k) is not None and (not isinstance(d[k], (int, float)) or isinstance(d[k], bool)):
            return False
    return True


def identity(r):
    """What makes two records one run: its plan's digest and its first stage's end. A folder copied, moved or synced
    keeps both; a second run of the same plan starts at another time."""
    if not r.get("plan_digest"):
        return None
    return r["plan_digest"], r.get("started") or r.get("ended")


def load(path):
    """The ledger's records, one per run. A run folder's latest record wins (a run is read again when it resumes or a
    trace is reviewed). One run read under two paths counts once: the record that got furthest (latest end, then
    latest read) is kept, and a backfilled record (a committed state file, keyed by its path) gives way to the same
    run read from its folder."""
    one, copies = {}, {}
    for r in latest(path).values():
        key = identity(r) or ("path", r.get("source"), r.get("run"))
        copies.setdefault(key, []).append(r)
        old = one.get(key)
        rank = (r.get("source") == "run", r.get("ended") or "", r.get("ingested") or "")
        if old is None or rank > (old.get("source") == "run", old.get("ended") or "", old.get("ingested") or ""):
            one[key] = r
    for key, r in one.items():
        _merge_reviews(r, copies[key])
    return sorted(one.values(), key=lambda r: (r.get("ended") or "", r.get("run") or ""))


def _merge_reviews(r, copies):
    """A verdict given on any copy of one run counts, and the latest verdict wins by its own time (the review line's
    "at"), whichever copy was read when (amendment (f); before, a copy read a second earlier than the kept one lost
    its verdict). A clear is a verdict with a time too, so a verdict cleared on one copy never comes back from
    another. A trace record from before verdicts kept their time ranks below every timed one; at equal times the
    kept copy's verdict wins, then the later read copy's."""
    def said(t):
        return t.get("review") is not None or t.get("review_at") is not None

    for t in r.get("traces") or []:
        best, rank = (t, (t.get("review_at") or "", 1, "")) if said(t) else (None, None)
        for c in copies:
            if c is r:
                continue
            u = next((u for u in c.get("traces") or [] if u.get("sid") == t.get("sid")), None)
            if u is None or not said(u):
                continue
            k = (u.get("review_at") or "", 0, c.get("ingested") or "")
            if rank is None or k > rank:
                best, rank = u, k
        if best is not None and best is not t:
            for k in ("review", "review_at"):
                t.pop(k, None)
                if best.get(k) is not None:
                    t[k] = best[k]


def ledger_digest(records):
    return digest([{k: v for k, v in r.items() if k not in ("ingested", "run")} for r in records])[:16]


def usable(records):
    """The records learned from: not excluded when written, and not excluded by the reserve file as it is now."""
    held = set(held_out_samples())
    return [r for r in records if not excluded_now(r, held)]


def stamp(rec, prior, key, ran=(), here=None):
    """Name the machine each stage ran on. A stage this process ran (ran: a run's own end names them) gets here, this
    machine's key. Otherwise a stage the ledger already holds unchanged (same status, end and seconds) keeps the
    machine it was first read with, and a stage new or changed since gets key, the folder's machine (_machine_of).
    So a review on a laptop never turns Modal's stage times into this machine's, and a Modal folder run again on a
    laptop never turns the laptop's into Modal's."""
    old = (prior or {}).get("stages") or {}
    # a record from before stages carried their machine names it once, for the whole run; the Modal runner's marker
    # in the folder (key "modal") wins over that name, which such records took from the reading machine
    was = ((prior or {}).get("machine") or {}).get("key") if isinstance((prior or {}).get("machine"), dict) else None
    if key == "modal":
        was = None
    for st, e in (rec.get("stages") or {}).items():
        if st in (ran or ()) and here:
            e["machine"] = here
            continue
        o = old.get(st) or {}
        o_key = o.get("machine") or was
        same = all(o.get(k) == e.get(k) for k in ("status", "at", "seconds")) and o_key
        e["machine"] = o_key if same else key
    return rec


def record_run(ctx, out, plan=None, state=None, ran=None):
    """Write one run's record (Run.run calls this when a run ends, with ran, the stages it ran; review when a verdict
    is added). Nothing is written inside a Modal container (on_modal: the folders come back and are read with `learn
    ingest`), with KIT_AUTOPIPE_LEARN=0, or for a target run."""
    env = ctx.env
    if env.get(ENV_OFF) == "0":
        return {"skipped": f"{ENV_OFF}=0"}
    if on_modal(env):
        return {"skipped": "inside a Modal container: read its folder with `learn ingest` once it is back"}
    here = machine(env)
    m = _machine_of(out, here)      # a Modal folder reviewed here keeps Modal's key (review item 1)
    rec, why = harvest(out, plan=plan, state=state, machine_info=m)
    if rec is None:
        return {"skipped": why}
    path = store_path(ctx.home)
    # the stages this process ran are this machine's, whatever marker the folder holds (amendment (f))
    stamp(rec, latest(path).get(("run", rec["run"])), m["key"], ran=ran, here=here["key"])
    from . import vc3d_agent
    vc3d_agent.writable(ctx, path)
    append(path, [rec])
    return {"ledger": str(path), "excluded": rec.get("excluded"), "traces": len(rec.get("traces") or [])}


def run_folders(ctx):
    """The run folders the kit home holds: work/autopipe/*. Target runs (experiments/*/autopipe/*) are not listed:
    they are never learned from."""
    base = Path(ctx.root) / "work" / "autopipe"
    return sorted(p for p in base.iterdir() if (p / "plan.json").is_file()) if base.is_dir() else []


def ingest(ctx, folders=None):
    """Read run folders into the ledger: the ones given, or every one under work/autopipe."""
    from . import vc3d_agent
    folders = [Path(f) for f in folders] if folders else run_folders(ctx)
    held_out_samples()          # an unreadable reserve file stops the whole read, before any folder
    m = machine(ctx.env)
    path = store_path(ctx.home)
    prior = latest(path)
    written, skipped = [], []
    for f in folders:
        try:
            where = _machine_of(f, m)
            rec, why = harvest(f, machine_info=where)
            if rec is not None:
                stamp(rec, prior.get(("run", rec["run"])), where["key"])
        except Exception as exc:        # noqa: BLE001 (one folder of an unknown shape never stops the others)
            skipped.append({"run": str(f), "why": exc if isinstance(exc, LearnError) else
                            f"unreadable: {type(exc).__name__}: {exc}"})
            continue
        if rec is None:
            skipped.append({"run": str(f), "why": why})
            continue
        written.append(rec)
    if written:
        vc3d_agent.writable(ctx, path)
        append(path, written)
    return {"ledger": str(path), "written": [{"run": r["run"], "excluded": r.get("excluded"),
                                              "traces": len(r.get("traces") or [])} for r in written],
            "skipped": skipped}


def _machine_of(folder, here):
    """The machine a folder's new stages ran on: Modal when one of the Modal runner's markers is in it (MODAL_MARKERS:
    runner-modal.json, written when any Modal CPU or GPU function starts on the folder, whatever its end; the driver
    markers of folders from before it), else this machine. A folder copied from another machine without them reads as
    this one; stages the ledger already held keep their machine, and stages a run's own end ran are this machine's
    (stamp)."""
    folder = Path(folder)
    if any((folder / name).is_file() for name in MODAL_MARKERS):
        return {"key": "modal", "runner": "modal"}
    return here


# ---------------------------------------------------------------- backfill

def presets(source=None):
    """The Modal presets (a script of the source repository PRESETS), read as a literal: the module imports modal."""
    import ast
    from . import kithome
    try:
        path = Path(source) if source else kithome.source_file(PRESETS_FILE, need="learn backfill")
    except kithome.MissingSource:
        raise LearnError(f"no Modal runner presets beside this kit ({PRESETS_FILE}): backfill reads past Modal "
                         "runs with them, so it needs a copy of the source that has them") from None
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PRESETS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise LearnError(f"{path} defines no PRESETS")


def backfill(ctx, manifest=None, presets_file=None):
    """Read the committed state files of past runs (BACKFILL) into the ledger, each with its preset's settings.
    plan.json was not copied back from Modal, so each plan is rebuilt from its preset over today's DEFAULTS
    (settings_source "preset"); the state's plan digest must be the preset's (or the one the manifest names). A
    relative state path is read from the repository root when the manifest is in a folder of the source repository, else
    from the manifest's own folder."""
    from . import autopipe, kithome, vc3d_agent
    pre = presets(presets_file)     # first: without the presets, no manifest helps (review item 12)
    try:
        mpath = Path(manifest) if manifest else kithome.source_file(BACKFILL, need="learn backfill")
    except kithome.MissingSource:
        raise LearnError(f"no backfill manifest beside this kit ({BACKFILL}): name one with --manifest, a JSON "
                         "{\"runs\": [{\"state\", \"preset\", \"arm\", \"volume\", \"machine\"}]}") from None
    held_out_samples()          # an unreadable reserve file stops the whole read
    man = _json(mpath)
    if not isinstance(man, dict) or not isinstance(man.get("runs"), list):
        raise LearnError(f"{mpath} is not a backfill manifest ({{\"runs\": [...]}})")
    here = mpath.resolve().parent
    root = here.parents[2] if here.parts[-3:] == ("docs", "evidence", "autopipe") else here
    written, skipped = [], []
    for e in man["runs"]:
        if not isinstance(e, dict) or not isinstance(e.get("state"), str):
            skipped.append({"state": None, "why": "an entry without a state path"})
            continue
        spath = Path(e["state"]) if Path(e["state"]).is_absolute() else root / e["state"]
        state = _json(spath)
        p = pre.get(e.get("preset"))
        if state is None or p is None:
            skipped.append({"state": e.get("state"), "why": "state file or preset missing"})
            continue
        spec = p["arms"][e["arm"]] if e.get("arm") else p
        want = e.get("digest") or spec.get("digest")
        if state.get("plan_digest") != want:
            skipped.append({"state": e["state"], "why": f"its plan digest {str(state.get('plan_digest'))[:12]} is not "
                                                       f"the preset's {str(want)[:12]}"})
            continue
        try:
            settings = autopipe._merge(autopipe.DEFAULTS, spec["settings"])
        except autopipe.AutoError as exc:
            skipped.append({"state": e["state"], "why": str(exc)})
            continue
        plan = {"version": e.get("plan_version", autopipe.PLAN_VERSION), "digest": want, "settings": settings,
                "resolved": {"sample": p["sample"], "volume": e.get("volume"),
                             **({"winding_bench": True} if e.get("winding_bench") else {})}}
        rec, why = harvest(spath.parent, plan=plan, state=state, machine_info=e.get("machine"), source="backfill",
                           run=e["state"])
        if rec is None:
            skipped.append({"state": e["state"], "why": why})
            continue
        rec["settings_source"] = "preset"
        stamp(rec, None, (e.get("machine") or {}).get("key") if isinstance(e.get("machine"), dict) else None)
        written.append(rec)
    path = store_path(ctx.home)
    if written:
        vc3d_agent.writable(ctx, path)
        append(path, written)
    return {"ledger": str(path), "written": [{"run": r["run"], "excluded": r.get("excluded"),
                                              "traces": len(r.get("traces") or [])} for r in written],
            "skipped": skipped}


# ---------------------------------------------------------------- the trace acceptance model

def units(records, outcome="qa"):
    """Every trace that counts (accepted, or rejected by AutoPipeline's own rule): [{run, sample, arm_key, y, at,
    started, seed, repeat, generations}]. at: when its run's trace fates were all known (the record's decided), the
    order the check predicts in; started: its run's first stage end, which decides whether it is fresh. outcome
    "kept" lets a person's review overrule qa (reject an accepted trace, or accept a rejected one)."""
    out = []
    for r in usable(records):
        for t in r.get("traces") or []:
            if t.get("outcome") not in ("accepted", "rejected"):
                continue
            y = 1 if t["outcome"] == "accepted" else 0
            if outcome == "kept" and t.get("review"):
                y = 1 if t["review"] == "accept" else 0
            out.append({"run": r["run"], "sample": r.get("sample"), "arm_key": r.get("arm_key"), "y": y,
                        "at": r.get("decided") or r.get("ended") or "", "started": _started(r),
                        "seed": t.get("seed_index"), "repeat": t.get("repeat"),
                        "generations": (r.get("planned") or {}).get("generations")})
    return out


def _started(r):
    return r.get("started") or r.get("ended") or ""


class Counts:
    """Running counts for the prequential check: the pooled pass rate and each arm's, per sample and elsewhere."""

    def __init__(self):
        self.S = self.N = 0
        self.arm = {}           # arm_key -> {sample: [s, n]}

    def add(self, u):
        self.S += u["y"]
        self.N += 1
        c = self.arm.setdefault(u["arm_key"], {}).setdefault(u["sample"], [0, 0])
        c[0] += u["y"]
        c[1] += 1

    def pooled(self):
        return (1 + self.S) / (2 + self.N)

    def beta(self, arm_key, sample):
        p = self.pooled()
        s = n = so = no = 0
        for smp, (a, b) in (self.arm.get(arm_key) or {}).items():
            if smp == sample:
                s, n = a, b
            else:
                so, no = so + a, no + b
        a = PRIOR_STRENGTH * p + s + OTHER_WEIGHT * so
        b = PRIOR_STRENGTH * (1 - p) + (n - s) + OTHER_WEIGHT * (no - so)
        return {"a": a, "b": b, "mean": a / (a + b), "pooled": p, "n_pooled": self.N, "sample": [s, n],
                "elsewhere": [so, no]}


def counts_of(us):
    c = Counts()
    for u in us:
        c.add(u)
    return c


def predict_accept(history, arm_key, sample):
    """The learner's chance that a trace of this arm on this sample passes qa, from earlier units only."""
    return counts_of(history).beta(arm_key, sample)


def p_at_least_one(a, b, k):
    """Beta-binomial chance that at least one of k traces passes, for a pass rate ~ Beta(a, b)."""
    none = 1.0
    for i in range(k):
        none *= (b + i) / (a + b + i)
    return 1 - none


def concordance(us, arm_key):
    """Seeds traced more than once with this arm: how many gave both outcomes (the tracer is not deterministic there)
    and how many gave one."""
    groups = {}
    for u in us:
        if u["arm_key"] == arm_key and u.get("seed") is not None:
            groups.setdefault((u["run"], u["seed"]), []).append(u["y"])
    mixed = sum(1 for ys in groups.values() if len(ys) > 1 and 0 < sum(ys) < len(ys))
    one = sum(1 for ys in groups.values() if len(ys) > 1 and sum(ys) in (0, len(ys)))
    return {"mixed": mixed, "unanimous": one}


def _rng(*parts):
    return random.Random(int(digest(list(parts))[:12], 16))


def prob_better(b1, b0, rng, draws=DRAWS):
    """P(p1 > p0) for p1 ~ Beta(b1), p0 ~ Beta(b0), by seeded Monte Carlo."""
    wins = sum(rng.betavariate(b1["a"], b1["b"]) > rng.betavariate(b0["a"], b0["b"]) for _ in range(draws))
    return wins / draws


def prob_below(b, x, rng, draws=DRAWS):
    return sum(rng.betavariate(b["a"], b["b"]) < x for _ in range(draws)) / draws


def _without_generations(arm):
    a = json.loads(json.dumps(arm))
    a["settings"].pop("generations", None)
    return a


# ---------------------------------------------------------------- the time model

def time_units(records, positive=True, cutoff=CUTOFF, apart=None):
    """Each (run, stage) done with measured seconds: [{run, stage, machine, sample, seconds, at, started,
    generations}]; the trace stage per trace, at when that stage ended, machine the one it ran on (stamp). With
    positive (the preregistered check's Q2 units) a stage that took 0 s is left out, since a log error needs a time
    above zero; an estimate keeps it. Also with positive, a fresh run's trace stage (first stage ended at or after
    cutoff) gives a unit only when the stage named the traces it ran (its record's "ran", amendment (f)): without the
    list a resumed stage would be divided by traces an earlier attempt made. Such a stage is appended to apart (a
    list, when given), so the check can count it."""
    out = []
    for r in usable(records):
        mkey = (r.get("machine") or {}).get("key")
        for st, e in (r.get("stages") or {}).items():
            if e.get("status") != "done" or not isinstance(e.get("seconds"), (int, float)):
                continue
            sec = e.get("per_trace") if st == "trace" else e["seconds"]
            if not isinstance(sec, (int, float)) or isinstance(sec, bool) or sec < 0 or (positive and sec <= 0):
                continue
            if positive and st == "trace" and e.get("traces_from") != "ran" and _started(r) >= cutoff:
                if apart is not None:
                    apart.append({"run": r["run"], "stage": st, "started": _started(r)})
                continue
            out.append({"run": r["run"], "stage": st, "machine": e.get("machine") or mkey, "sample": r.get("sample"),
                        "seconds": sec, "at": e.get("at") or r.get("ended") or "", "started": _started(r),
                        "generations": (r.get("planned") or {}).get("generations")})
    return out


def predict_seconds(history, stage, machine_key=None, sample=None, generations=None):
    """The median of the same stage's earlier units at the most specific level that has one, or None. "exact" is
    the median itself (the preregistered check compares it); "seconds" is it to 0.1 s for people. A level that needs
    a machine or a scroll is passed over when none is given."""
    same = [u for u in history if u["stage"] == stage]
    levels = (("this machine, this scroll", True, True), ("this machine", True, False),
              ("this scroll, other machines", False, True), ("all runs", False, False))
    for label, by_m, by_s in levels:
        if (by_m and machine_key is None) or (by_s and sample is None):
            continue
        pick = [u for u in same if (not by_m or u["machine"] == machine_key) and (not by_s or u["sample"] == sample)]
        if stage == "trace" and generations is not None and pick:
            gen = [u for u in pick if u["generations"] == generations]
            if gen:
                pick = gen
                label += f", {generations} generations"
            else:
                label += f", other trace lengths than {generations} generations"
        if pick:
            xs = [u["seconds"] for u in pick]
            med = statistics.median(xs)
            return {"seconds": round(med, 1), "exact": med, "n": len(xs), "range": [min(xs), max(xs)],
                    "basis": label}
    return None


def baseline_seconds(history, stage):
    xs = [u["seconds"] for u in history if u["stage"] == stage]
    return statistics.median(xs) if xs else None


# ---------------------------------------------------------------- suggest and estimate

def suggest(records, sample, settings=None, volume=None, target=REPEATS_TARGET, outcome="kept", axis=True):
    """Settings for the next plan of `sample`, each change with its evidence, and what is kept and why. The caller's
    own settings always win: a key they named is reported, never changed. axis False: the catalog has an axis for
    the scan (make_plan found one), which a plan asking "auto" takes, so no earlier estimate is offered."""
    if not isinstance(target, (int, float)) or isinstance(target, bool) or not 0 < target < 1:
        raise LearnError("target is a chance between 0 and 1")
    if outcome not in ("kept", "qa"):
        raise LearnError("outcome is kept or qa")
    given = settings or {}
    named = given_keys(given)
    s = merged_settings(given)
    used = usable(records)
    us = units(records, outcome)
    arm, key = trace_arm(s)
    arms = {r["arm_key"]: r["arm"] for r in used if r.get("arm_key")}
    arms[key] = arm
    overlay, changes, kept, warnings = {}, [], [], []
    rng = _rng(ledger_digest(records), sample, given, volume, target, outcome)
    counts = counts_of(us)

    if s.get("segment"):
        kept.append({"key": "trace", "why": "the plan reads a published segment: nothing is traced"})
    else:
        here = counts.beta(key, sample)
        n_here = here["sample"][1] + here["elsewhere"][1]
        # 1. a trace length that beats the plan's (the rest of the arm held)
        if "trace.generations" in named:
            kept.append({"key": "trace.generations", "why": "given in the settings"})
        else:
            best = None
            for k2, a2 in arms.items():
                if k2 == key or _without_generations(a2) != _without_generations(arm):
                    continue
                b2 = counts.beta(k2, sample)
                n2 = b2["sample"][1] + b2["elsewhere"][1]
                if n2 < GATE["min_n"] or n_here < GATE["min_n_plan"]:
                    kept.append({"key": "trace.generations", "why": (
                        f"{a2['settings'].get('generations')} generations has {n2} traces and the plan's "
                        f"{arm['settings'].get('generations')} has {n_here}: the gate needs {GATE['min_n']} and "
                        f"{GATE['min_n_plan']}"), "evidence": {"candidate": _ev(b2), "plan": _ev(here)}})
                    continue
                pb = prob_better(b2, here, rng)
                if pb >= GATE["p_better"] and (best is None or pb > best[0]):
                    best = (pb, k2, a2, b2)
                elif pb < GATE["p_better"]:
                    kept.append({"key": "trace.generations", "why": (
                        f"{a2['settings'].get('generations')} generations beats the plan's with probability "
                        f"{pb:.2f}, under {GATE['p_better']}"), "evidence": {"candidate": _ev(b2), "plan": _ev(here)}})
            if best:
                pb, k2, a2, b2 = best
                g = a2["settings"].get("generations")
                _put(overlay, "trace.generations", g)
                changes.append({"key": "trace.generations", "value": g, "was": arm["settings"].get("generations"),
                                "why": f"passes qa more often than the plan's trace length with probability {pb:.3f}",
                                "evidence": {"candidate": _ev(b2), "plan": _ev(here)}, "label": "Model output"})
                arm, key, here = a2, k2, b2
                n_here = here["sample"][1] + here["elsewhere"][1]
        # 2. known to fail
        failing = False
        if n_here >= FAILING["min_n"]:
            pf = prob_below(here, FAILING["below"], rng)
            if pf >= FAILING["prob"]:
                failing = True
                warnings.append({"key": "trace", "arm": arm_label(arm), "why": (
                    f"this trace arm passes qa less than {FAILING['below']:.0%} of the time with probability "
                    f"{pf:.2f} ({here['sample'][0] + here['elsewhere'][0]} of {n_here} traces passed): change the "
                    "trace settings or the seeds rather than adding repeats"), "evidence": _ev(here)})
        # 3. repeats
        repeats_now = (s.get("trace") or {}).get("repeats") or 1
        conc = concordance(us, key)
        from . import autopipe
        top = autopipe.MAX_REPEATS
        exact = {k: p_at_least_one(here["a"], here["b"], k) for k in range(1, top + 1)}
        chance = {k: round(v, 3) for k, v in exact.items()}
        if n_here == 0:
            kept.append({"key": "trace.repeats", "why": "no trace of this arm in the ledger yet",
                         "evidence": {"arm": arm_label(arm), "pooled": round(here["pooled"], 3)}})
        elif conc["unanimous"] >= DETERMINISTIC and conc["mixed"] == 0:
            want = 1
            why = (f"repeats of a seed agreed every time ({conc['unanimous']} seeds traced more than once, none mixed): "
                   "this tracer looks deterministic here, so a repeat costs time and adds nothing")
            _repeats(overlay, changes, kept, named, repeats_now, want, why, here, chance, conc)
        else:
            want = next((k for k in range(1, top + 1) if exact[k] >= target), None)
            if want is None:
                # no number of repeats reaches the target: more of a trace that fails is time, not a fix
                want = repeats_now
                why = (f"even {top} repeats give a chance of only {exact[top]:.3f} that at least one trace of a seed "
                       f"passes qa (target {target}): more repeats are not the fix, so they stay at {repeats_now}")
            elif failing and want > repeats_now:
                why = (f"{want} repeats would reach the target, but this arm is flagged as failing (the warning): "
                       f"repeats stay at {repeats_now}")
                want = repeats_now
            else:
                why = (f"with {want} repeat{'s' if want > 1 else ''} the chance that at least one trace of a seed "
                       f"passes qa is {exact[want]:.3f} (target {target})")
            _repeats(overlay, changes, kept, named, repeats_now, want, why, here, chance, conc)

    # 4. an earlier run's axis for the same scan
    u = s.get("umbilicus") or {}
    if "umbilicus.source" in named:
        kept.append({"key": "umbilicus.source", "why": "given in the settings"})
    elif not axis and u.get("source") == "auto":
        kept.append({"key": "umbilicus.source", "why": "the catalog has an axis for this scan: the plan takes it"})
    elif u.get("estimator") is not None:
        kept.append({"key": "umbilicus.source", "why": "the plan names umbilicus.estimator, which goes with an axis "
                                                       "estimated in the run, not a file"})
    elif s.get("external_prediction"):
        kept.append({"key": "umbilicus.source", "why": "the plan reads its own prediction, whose grids or box may "
                                                       "estimate another axis than an earlier run's"})
    elif u.get("source") in ("auto", "estimate"):
        want = digest({k: v for k, v in u.items() if k not in UMB_SKIP})[:16]
        vol = volume or s.get("volume")
        cands = []
        for r in used:
            um = r.get("umbilicus") or {}
            if r.get("sample") != sample or um.get("source") != "estimated" or um.get("settings") != want:
                continue
            if vol and r.get("volume") != vol:
                continue
            if um.get("box_axis") or um.get("axis_grids"):
                continue        # estimated from a prediction's own grids or one box of it: that plan's axis alone
            if u["source"] == "auto" and um.get("asked") != "auto":
                continue        # an estimate a plan forced: the catalog may have an axis this plan would take
            p = Path(um.get("path") or "")
            if not um.get("path") or not p.is_file() or _sha256(p) != um.get("sha256"):
                continue
            cands.append(r)
        if cands:
            r = max(cands, key=lambda x: x.get("ended") or "")
            um = r["umbilicus"]
            hash_source = um.get("sha256_source") or "legacy_file_observation"
            _put(overlay, "umbilicus.source", um["path"])
            changes.append({"key": "umbilicus.source", "value": um["path"], "was": u["source"],
                            "why": (f"run {Path(r['run']).name} estimated the axis of scan {r.get('volume')} with the "
                                    f"same settings ({um.get('kept')} points kept, {um.get('seconds')} s): reused, "
                                    "not estimated again" + ("" if vol else "; only for a plan of that scan (plan "
                                                             "--learned checks)") + ("" if hash_source ==
                                    "stage_receipt" else "; the file hash was observed when read, and the "
                                    "historical stage's bytes are unverified")),
                            "evidence": {"run": r["run"], "volume": r.get("volume"), "sha256": um["sha256"],
                                         "sha256_source": hash_source, "estimator": um.get("estimator"),
                                         "grids": um.get("grids")},
                            "label": "Sourced fact (the earlier run's stage receipt)" if hash_source ==
                            "stage_receipt" else "Sourced fact (file observation; historical stage unverified)"})
    check_overlay(overlay)
    out = {"sample": sample, "settings": overlay, "changes": changes, "kept": kept, "warnings": warnings,
           "ledger": {"records": len(records), "used": len(used), "units": len(us), "digest": ledger_digest(records)},
           "arm": arm_label(arm), "outcome": outcome, "version": VERSION,
           "note": ("Model output from past runs, not a promise: the settings are suggestions for a new plan, frozen "
                    "under its digest like any other. `learn evaluate` tests predictions of QA outcomes and time, "
                    "not whether applying these settings improves runs (a note of the source repository).")}
    if s.get("purpose") == "target":
        out["target"] = ("a target plan's settings are frozen in its ledger experiment before any map: record this "
                         "suggestion's digest there (kit ledger) with the plan")
    out["digest"] = digest({k: out[k] for k in ("sample", "settings", "ledger", "version")})[:16]
    return out


def _ev(b):
    return {"passed": b["sample"][0] + b["elsewhere"][0], "traces": b["sample"][1] + b["elsewhere"][1],
            "on_this_scroll": b["sample"], "elsewhere": b["elsewhere"], "mean": round(b["mean"], 3),
            "interval90": _interval(b), "pooled": round(b["pooled"], 3)}


def _interval(b, draws=4000):
    rng = random.Random(SEED)
    xs = sorted(rng.betavariate(b["a"], b["b"]) for _ in range(draws))
    return [round(xs[int(0.05 * draws)], 3), round(xs[int(0.95 * draws) - 1], 3)]


def _repeats(overlay, changes, kept, named, now_k, want, why, here, chance, conc):
    ev = {"arm": _ev(here), "at_least_one": chance, "seeds_traced_twice_or_more": conc}
    if "trace.repeats" in named:
        kept.append({"key": "trace.repeats", "why": f"given in the settings ({now_k}); the ledger would say: {why}",
                     "evidence": ev})
    elif want == now_k:
        kept.append({"key": "trace.repeats", "why": why, "evidence": ev})
    else:
        _put(overlay, "trace.repeats", want)
        changes.append({"key": "trace.repeats", "value": want, "was": now_k, "why": why, "evidence": ev,
                        "label": "Model output"})


def planned_stages(s):
    """{stage: None or why it will not run} for a plan with these settings (before the catalog is read)."""
    seg = bool(s.get("segment"))
    ink_off = (s.get("ink") or {}).get("where") == "skip"
    return {"acquire": None, "umbilicus": None, "seeds": "a published segment" if seg else None,
            "trace": "a published segment" if seg else None, "bench": None, "qa": None,
            "flatten": "a published segment is never flattened" if seg else
            None if (s.get("flatten") or {}).get("enabled") else "flatten.enabled is false",
            "render": None, "ink": "ink.where is skip" if ink_off else None,
            "score": "no ink" if ink_off else _score_skip(s), "report": None}


def _score_skip(s):
    """Why the score stage will not run, as Run.s_score decides it: only a published labeled segment, or labels
    carried by score.transfer, are scored."""
    from . import autopipe
    if s.get("purpose") == "target":
        return "target runs are never scored here"
    if ((s.get("score") or {}).get("transfer")) or (s.get("segment") and s["segment"] in autopipe.BENCHMARKS):
        return None
    return "no labels: only published labeled segments, or labels carried by score.transfer, are scored"


def estimate(records, sample, settings=None, machine_key=None):
    """Each stage's expected seconds for a plan of `sample` with these settings, from measured stages, and where the
    compute rule puts the CPU part. Which stages run comes from the plan's own settings; only bench, which runs on a
    scan with a winding bench whatever the plan says, is read from earlier runs of the scroll (of the plan's scan
    when it names one)."""
    s = merged_settings(settings or {})
    mkey = machine_key or machine()["key"]
    used = usable(records)
    hist = time_units(used, positive=False)
    seeds = s.get("seeds") or {}
    n_traces = (len(seeds.get("points") or []) or seeds.get("count") or 0) * ((s.get("trace") or {}).get("repeats") or 1)
    rows, cpu_here, cpu_other, unknown = {}, 0.0, 0.0, []
    for st, skip in planned_stages(s).items():
        if st == "bench" and not skip:
            seen = [(r.get("stages") or {}).get(st, {}).get("status") for r in used if r.get("sample") == sample
                    and (not s.get("volume") or r.get("volume") == s["volume"])]
            seen = [x for x in seen if x]
            if seen and all(x == "skipped" for x in seen):
                skip = f"skipped on every earlier run of {sample} ({len(seen)}): its scan has no winding bench"
        if skip:
            rows[st] = {"skipped": skip}
            continue
        p = predict_seconds(hist, st, mkey, sample, (s.get("trace") or {}).get("generations"))
        if p is None:
            rows[st] = {"seconds": None, "basis": "no record of this stage"}
            unknown.append(st)
            continue
        if st == "trace":
            p = {**p, "per_trace": p["seconds"], "traces": n_traces, "seconds": round(p["seconds"] * n_traces, 1)}
        rows[st] = p
        if st != "ink":
            if p["basis"].startswith("this machine"):
                cpu_here += p["seconds"]
            else:
                cpu_other += p["seconds"]
    try:
        from . import apbackends
        rule = apbackends.CPU_RULE
    except ImportError:
        rule = {"local_max_minutes": 10}
    limit = rule["local_max_minutes"] * 60
    if mkey == "modal":
        where = {"where": None, "why": (
            f"an estimate for the Modal runner (about {(cpu_here + cpu_other) / 60:.0f} minutes of CPU stages): the "
            f"compute rule decides from the time on Chase's laptop, over {rule['local_max_minutes']} minutes there "
            "means Modal"), "rule": rule}
    elif cpu_other or unknown:
        where = {"where": "unknown", "why": (
            (f"{round(cpu_other)} s of the CPU stages were measured on other machines" if cpu_other else "")
            + (f"{' and ' if cpu_other else ''}{', '.join(unknown)} never" if unknown else "")
            + f": time one run here before choosing (the line is {rule['local_max_minutes']} minutes)")}
    elif cpu_here > limit:
        where = {"where": "modal", "why": f"about {cpu_here / 60:.0f} minutes of CPU on this machine ({mkey}), over "
                                          f"the {rule['local_max_minutes']}-minute line", "rule": rule}
    else:
        where = {"where": "here", "why": (
            f"about {cpu_here / 60:.1f} minutes of CPU on this machine ({mkey}), under the "
            f"{rule['local_max_minutes']}-minute line; the rule counts time on Chase's laptop, so this places the job "
            "there only when this machine is it"), "rule": rule}
    ink = rows.get("ink") or {}
    if not ink.get("skipped"):
        where["ink"] = "GPU work runs on a GPU host (Modal's GPU list is the default; AutoPipeline launches nothing itself)"
    return {"sample": sample, "machine": mkey, "stages": rows, "cpu_seconds_here": round(cpu_here, 1),
            "cpu_seconds_measured_elsewhere": round(cpu_other, 1), "placement": where,
            "label": "Model output: medians of measured stage times; a resumed stage reads low",
            "ledger": {"records": len(records), "digest": ledger_digest(records)}}


# ---------------------------------------------------------------- review

def review(ctx, out, sid, verdict, note=None, by=None):
    """A person's verdict on one traced surface, appended to the run folder's review.jsonl, then the run read again
    (unless it is a target run, whose verdicts stay in its folder and are never learned from)."""
    from . import vc3d_agent
    out = Path(out)
    plan = _json(out / "plan.json")
    if not isinstance(plan, dict):
        raise LearnError(f"{out} has no plan.json: not an AutoPipeline run folder")
    if verdict not in ("accept", "reject", "clear"):
        raise LearnError("the verdict is accept, reject or clear")
    state = _json(out / "state.json") or {}
    surfaces = state.get("surfaces") or {}
    if sid not in surfaces:
        raise LearnError(f"{out} has no surface {sid} (it has {', '.join(sorted(surfaces)) or 'none'})")
    if not sid.startswith("t"):
        raise LearnError(f"{sid} is a published segment, not a trace of this run")
    path = vc3d_agent.writable(ctx, out / REVIEW)
    line = {"v": 1, "at": now(), "sid": sid, "verdict": verdict, "note": note, "by": by,
            "plan_digest": plan.get("digest"), "surface": surfaces[sid].get("surface")}
    append(path, [line])
    res = {"review": str(path), "sid": sid, "verdict": verdict}
    res["ledger"] = record_run(ctx, out, plan=plan, state=state)
    return res


# ---------------------------------------------------------------- status

def status(records, path=None):
    held = set(held_out_samples())
    used, excluded = [], {}
    for r in records:
        why = excluded_now(r, held)
        if why:
            excluded[why] = excluded.get(why, 0) + 1
        else:
            used.append(r)
    arms = {}
    for r in used:
        if not r.get("arm_key"):
            continue
        a = arms.setdefault(r["arm_key"], {"arm": r.get("arm_label"), "accepted": 0, "rejected": 0, "void": 0,
                                           "reviewed": 0, "samples": set(), "runs": 0})
        a["runs"] += 1
        a["samples"].add(r.get("sample"))
        for t in r.get("traces") or []:
            a[t["outcome"] if t["outcome"] in ("accepted", "rejected") else "void"] += 1
            a["reviewed"] += bool(t.get("review"))
    stages = {}
    for u in time_units(records):
        stages[u["stage"]] = stages.get(u["stage"], 0) + 1
    fresh = [r for r in used if _started(r) >= CUTOFF]
    return {"ledger": str(path) if path else None, "records": len(records), "used": len(used),
            "segment_runs": sum(1 for r in used if not r.get("arm_key")),
            "excluded": excluded, "fresh_runs": len(fresh), "cutoff": CUTOFF,
            "trace_units": len(units(records)), "stage_units": stages,
            "arms": [{**v, "key": k, "samples": sorted(x for x in v["samples"] if x)} for k, v in sorted(arms.items())],
            "digest": ledger_digest(records), "version": VERSION}


# ---------------------------------------------------------------- evaluate (the preregistered check)

def _groups(items):
    """items grouped by the time each became known ("at"), in order: a group is predicted from the groups before it
    only, so units known at the same moment never see each other."""
    out = {}
    for x in items:
        out.setdefault(x["at"], []).append(x)
    return [out[k] for k in sorted(out)]


def _clip(p):
    return min(max(p, CLIP[0]), CLIP[1])


def prequential_q1(us):
    """[(unit, learner p, baseline p, beta)] for every unit with an earlier unit to learn from."""
    c, out = Counts(), []
    for group in _groups(us):
        if c.N:
            for u in group:
                b = c.beta(u["arm_key"], u["sample"])
                out.append((u, _clip(b["mean"]), _clip(c.pooled()), b))
        for u in group:
            c.add(u)
    return out


def _logloss(rows, which):
    if not rows:
        return None
    return -sum(math.log(r[which] if r[0]["y"] else 1 - r[which]) for r in rows) / len(rows)


def _brier(rows, which):
    return sum((r[which] - r[0]["y"]) ** 2 for r in rows) / len(rows) if rows else None


def _q1_numbers(rows):
    return {"units": len(rows), "runs": len({r[0]["run"] for r in rows}),
            "log_loss": {"learner": _r(_logloss(rows, 1)), "no_learning": _r(_logloss(rows, 2))},
            "brier": {"learner": _r(_brier(rows, 1)), "no_learning": _r(_brier(rows, 2))}}


def _r(x, n=4):
    return None if x is None else round(x, n)


def prequential_q2(tu):
    """[(unit, learner seconds, baseline seconds)] for every stage unit with an earlier unit of its stage."""
    hist, out = [], []
    for group in _groups(tu):
        for u in group:
            p = predict_seconds(hist, u["stage"], u["machine"], u["sample"], u["generations"])
            b = baseline_seconds(hist, u["stage"])
            if p is not None and b is not None:
                out.append((u, p["exact"], b))
        hist += group
    return out


def _mae_log(rows, which):
    if not rows:
        return None
    return statistics.median(abs(math.log(max(r[which], 0.1) / r[0]["seconds"])) for r in rows)


def _fresh(rows, cutoff):
    return [r for r in rows if r[0]["started"] >= cutoff]


def evaluate(records, cutoff=CUTOFF, permutations=PERMUTATIONS, seed=SEED, outcome="qa"):
    """The preregistered check (PREREG): Q1 trace acceptance, Q2 stage time, Q3 repeats, each on fresh runs (whose
    first stage ended at or after cutoff) with the development runs reported apart. Verdicts compare unrounded
    numbers; the printed ones are rounded."""
    if not isinstance(permutations, int) or isinstance(permutations, bool) or not 1 <= permutations <= 99999:
        raise LearnError("permutations is a whole number from 1 to 99999: the shuffled control needs at least one")
    us = units(records, outcome)
    q1 = prequential_q1(us)
    f1 = _fresh(q1, cutoff)
    real = _logloss(f1, 1)
    p1 = None
    if f1:
        rng, ys, hits = random.Random(seed), [u["y"] for u in us], 0
        for _ in range(permutations):
            perm = ys[:]
            rng.shuffle(perm)
            shuffled = [{**u, "y": y} for u, y in zip(us, perm)]
            ll = _logloss(_fresh(prequential_q1(shuffled), cutoff), 1)
            hits += ll is not None and ll <= real
        p1 = (1 + hits) / (1 + permutations)
    q1_fresh = _q1_numbers(f1)
    q1_fresh["permutation_p"] = _r(p1)
    if q1_fresh["units"] < FRESH_MIN["q1_units"] or q1_fresh["runs"] < FRESH_MIN["q1_runs"]:
        v1 = "INSUFFICIENT"
    elif real < _logloss(f1, 2) and p1 <= 0.05:
        v1 = "EVIDENCE"
    else:
        v1 = "NO EVIDENCE"

    apart = []
    tu = time_units(records, cutoff=cutoff, apart=apart)
    q2 = prequential_q2(tu)
    f2 = _fresh(q2, cutoff)
    real2 = _mae_log(f2, 1)
    p2 = None
    if f2:
        rng, hits = random.Random(seed), 0
        by_stage = {}
        for i, u in enumerate(tu):
            by_stage.setdefault(u["stage"], []).append(i)
        for _ in range(permutations):
            secs = [u["seconds"] for u in tu]
            for idx in by_stage.values():
                vals = [secs[i] for i in idx]
                rng.shuffle(vals)
                for i, v in zip(idx, vals):
                    secs[i] = v
            m = _mae_log(_fresh(prequential_q2([{**u, "seconds": x} for u, x in zip(tu, secs)]), cutoff), 1)
            hits += m is not None and m <= real2
        p2 = (1 + hits) / (1 + permutations)
    q2_fresh = {"units": len(f2), "median_abs_log_error": {"learner": _r(real2), "no_learning": _r(_mae_log(f2, 2))},
                "permutation_p": _r(p2),
                # fresh trace stages that did not name the traces they ran: no unit, counted here (amendment (f))
                "trace_stages_without_ran": len(apart)}
    if q2_fresh["units"] < FRESH_MIN["q2_units"]:
        v2 = "INSUFFICIENT"
    elif real2 < _mae_log(f2, 2) and p2 <= 0.05:
        v2 = "EVIDENCE"
    else:
        v2 = "NO EVIDENCE"
    dev2 = [r for r in q2 if r[0]["started"] < cutoff]
    return {"cutoff": cutoff, "rule": PREREG, "version": VERSION,
            "q1_trace_acceptance": {"verdict": v1, "fresh": q1_fresh,
                                    "development": _q1_numbers([r for r in q1 if r[0]["started"] < cutoff])},
            "q2_stage_time": {"verdict": v2, "fresh": q2_fresh,
                              "development": {"units": len(dev2), "median_abs_log_error": {
                                  "learner": _r(_mae_log(dev2, 1)), "no_learning": _r(_mae_log(dev2, 2))}}},
            "q3_repeats": _q3(q1, cutoff),
            "ledger": {"records": len(records), "used": len(usable(records)), "digest": ledger_digest(records)},
            "label": "Model output on the runs named; each verdict is Interpretation within the preregistered rule"}


def _q3(q1, cutoff):
    groups = {}
    for u, _, _, b in q1:
        if u["started"] >= cutoff and u.get("seed") is not None:
            groups.setdefault((u["run"], u["seed"]), {"b": b, "ys": []})["ys"].append(u["y"])
    seeds = [g for g in groups.values() if len(g["ys"]) > 1]
    if not seeds:
        return {"seeds": 0, "note": "no fresh seed traced more than once yet"}
    pred = [p_at_least_one(g["b"]["a"], g["b"]["b"], len(g["ys"])) for g in seeds]
    return {"seeds": len(seeds), "mean_predicted_at_least_one": _r(sum(pred) / len(pred), 3),
            "observed_share": _r(sum(1 for g in seeds if any(g["ys"])) / len(seeds), 3), "verdict": None}


# ---------------------------------------------------------------- plan --learned

def for_plan(ctx, sample, settings, axis=True):
    """(settings for make_plan, the suggestion): the caller's settings with the suggestion's added under them. A target
    plan is refused: its settings come from its preregistration, fixed before the experiment starts (AGENTS.md rule
    3), so what to take from `learn suggest` goes into that file, not into the plan at the last moment."""
    if merged_settings(settings or {}).get("purpose") == "target":
        raise LearnError("a target plan's settings come from its preregistration: put what you take from `learn "
                         "suggest` into it before the experiment starts, then plan without learned")
    records = load(store_path(ctx.home))
    sug = suggest(records, sample, settings, axis=axis)
    return _deep(sug["settings"], settings or {}), sug


def took_axis(sug):
    """Whether the suggestion reuses an earlier run's axis (make_plan then checks whether the catalog has one)."""
    return any(c["key"] == "umbilicus.source" for c in sug["changes"])


def axis_conflict(sug, plan):
    """Why a plan made with the suggestion must be made again without the earlier axis, or None: the catalog has
    this scan's axis (a plan asking auto takes it), or the plan resolved another scan than the axis is of."""
    for c in sug["changes"]:
        if c["key"] != "umbilicus.source":
            continue
        r = plan.get("resolved") or {}
        if r.get("catalog_umbilicus"):
            return "the catalog has this scan's axis, which the plan takes over an earlier estimate"
        vol = (c.get("evidence") or {}).get("volume")
        if vol and r.get("volume") != vol:
            return f"the earlier axis is of scan {vol}, and the plan uses {r.get('volume')}"
    return None


def write_learned(out, sug, plan_digest):
    path = Path(out) / LEARNED
    path.write_text(json.dumps({"plan_digest": plan_digest, "suggestion": sug, "written": now()}, indent=1))
    return path


def summary(sug, path=None):
    """What `plan --learned` returns: each change with its reason, the warnings, and where the whole suggestion is."""
    return {"file": str(path) if path else None, "digest": sug["digest"],
            "changes": [{k: c.get(k) for k in ("key", "value", "was", "why", "label")}
                        for c in sug["changes"]],
            "warnings": [w["why"] for w in sug["warnings"]], "kept": len(sug["kept"]),
            "ledger": sug["ledger"], "note": sug["note"],
            **({"frozen_sha256": sug["frozen_sha256"], "frozen_file": sug.get("frozen_file"),
                "overridden": sug["overridden"]}
               if "frozen_sha256" in sug else {})}


# What each learn action of the autopipeline tool takes (beside "do"); the tool's schema lists the same
TOOL_TAKES = {"status": (), "suggest": ("sample", "settings", "volume", "target", "outcome"),
              "freeze": ("sample", "settings", "volume", "target", "outcome", "out"), "verify": ("file",),
              "estimate": ("sample", "settings", "machine"), "review": ("out", "sid", "verdict", "note", "by"),
              "ingest": ("folders",), "backfill": ("manifest",), "evaluate": ("permutations",)}


def tool_schema(OBJ, STR, NUM, INT, ARR):
    """The learn argument's JSON schema for the autopipeline tool (kit/vc3d_agent.py builders)."""
    return OBJ("learn: {\"do\": ..., ...}, what to do with the learning ledger. status; suggest and estimate (sample "
               "and settings, beside learn or inside it); review (out, sid, verdict); ingest (folders, default every "
               "run under work/autopipe); backfill (manifest, default the committed one); evaluate (permutations).",
               properties={"do": STR("the learn action", enum=list(TOOL_TAKES)),
                           "sample": STR("suggest, estimate: the scroll"),
                           "settings": OBJ("suggest, estimate: the settings the plan will have"),
                           "volume": STR("suggest: the scan the plan will use, when known"),
                           "target": NUM("suggest: chance that at least one repeat of a seed passes qa (default 0.8)"),
                           "outcome": STR("suggest: kept (a review overrules qa) or qa", enum=["kept", "qa"]),
                           "machine": STR("estimate: the machine key to estimate for (default this machine's)"),
                           "out": STR("review: the run folder; freeze: a new local advice file"),
                           "file": STR("verify: a saved local advice file"),
                           "sid": STR("review: the traced surface, such as t00"),
                           "verdict": STR("review: the verdict", enum=["accept", "reject", "clear"]),
                           "note": STR("review: why"), "by": STR("review: who"),
                           "folders": ARR("ingest: run folders", {"type": "string"}),
                           "manifest": STR("backfill: a manifest of state files and their presets"),
                           "permutations": INT("evaluate: shuffled controls (default 999)", minimum=1,
                                               maximum=99999)},
               required=["do"])


def tool_call(ctx, agent, a):
    """The autopipeline tool's learn action: a["learn"] is {"do": ..., ...}; sample, settings and out may also be given
    beside it, as for the tool's other actions."""
    spec = a.get("learn") or {}
    if not isinstance(spec, dict):
        raise agent.ToolError("learn is a JSON object: {\"do\": ...}")
    do = spec.get("do")
    if not isinstance(do, str) or do not in TOOL_TAKES:
        raise agent.ToolError(f"learn needs {{\"do\": ...}}, one of {', '.join(TOOL_TAKES)}")
    takes = TOOL_TAKES
    extra = sorted(set(spec) - {"do"} - set(takes[do]))
    if extra:
        raise agent.ToolError(f"learn {do} does not take {', '.join(extra)}; it takes {', '.join(takes[do]) or 'nothing'}")
    get = lambda k: spec.get(k, a.get(k))    # noqa: E731
    path = store_path(ctx.home)
    try:
        if do == "verify":
            from . import aplearn_frozen
            if not isinstance(spec.get("file"), str) or not spec["file"]:
                raise LearnError("verify needs file")
            obj = aplearn_frozen.read(agent.resolve(ctx, spec["file"]))
            return aplearn_frozen.verify(obj)
        if do == "ingest":
            folders = spec.get("folders")
            if folders is not None and (not isinstance(folders, list) or not folders
                                        or not all(isinstance(f, str) for f in folders)):
                raise LearnError("folders is a list of run folders (leave it out for every run under work/autopipe)")
            return ingest(ctx, [agent.resolve(ctx, f) for f in folders] if folders else None)
        if do == "backfill":
            m = spec.get("manifest")
            if m is not None and not isinstance(m, str):
                raise LearnError("manifest is the path of a backfill manifest")
            return backfill(ctx, agent.resolve(ctx, m) if m else None)
        if do == "review":
            if not get("out") or not spec.get("sid") or not spec.get("verdict"):
                raise LearnError("review needs out, sid and verdict")
            return review(ctx, agent.resolve(ctx, get("out")), spec["sid"], spec["verdict"], spec.get("note"),
                          spec.get("by"))
        records = load(path)
        if do == "status":
            return status(records, path)
        if do == "evaluate":
            n = spec.get("permutations", PERMUTATIONS)
            if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 99999:
                raise LearnError("permutations is a whole number from 1 to 99999")
            return evaluate(records, permutations=n)
        if not isinstance(get("sample"), str) or not get("sample"):
            raise LearnError(f"{do} needs sample")
        settings = get("settings")
        if settings is not None and not isinstance(settings, dict):
            raise LearnError("settings is a JSON object")
        if do == "freeze":
            from . import aplearn_frozen
            if not isinstance(get("out"), str) or not get("out"):
                raise LearnError("freeze needs out: a new local advice file")
            obj = aplearn_frozen.freeze(records, get("sample"), settings, spec.get("volume"),
                                         spec.get("target", REPEATS_TARGET), spec.get("outcome", "kept"))
            return aplearn_frozen.write(agent.resolve(ctx, get("out")), obj)
        if do == "suggest":
            return suggest(records, get("sample"), settings, spec.get("volume"),
                           spec.get("target", REPEATS_TARGET), spec.get("outcome", "kept"))
        return estimate(records, get("sample"), settings, spec.get("machine"))
    except (LearnError, OSError, ValueError) as exc:
        raise agent.ToolError(str(exc)) from exc


# ---------------------------------------------------------------- command line

def add_parser(actions):
    a = actions.add_parser("learn", help="learn from past runs: ledger, suggestions, time estimates, reviews and the "
                                         "preregistered check (kit/aplearn.py)")
    sub = a.add_subparsers(dest="learn_action", required=True)
    b = sub.add_parser("ingest", help="read run folders into the ledger (default: every one under work/autopipe)")
    b.add_argument("folders", nargs="*")
    b = sub.add_parser("backfill", help="read state files of past Modal runs, named in a manifest, into the ledger")
    b.add_argument("--manifest", help=f"default {BACKFILL}, when this copy has it")
    sub.add_parser("status", help="what the ledger holds and leaves out, and each trace arm's counts")
    b = sub.add_parser("verify", help="validate and recompute saved advice without reading the current ledger")
    b.add_argument("file", help="the saved local advice JSON file")
    for name, about in (("suggest", "settings for the next plan of a scan, each with its evidence"),
                        ("freeze", "save reproducible local advice for review; no job or evaluation"),
                        ("estimate", "each stage's expected seconds for a plan, and where the compute rule puts it")):
        b = sub.add_parser(name, help=about)
        b.add_argument("sample")
        b.add_argument("--settings", help="JSON object, or @file, of the settings the plan will have")
        if name in ("suggest", "freeze"):
            b.add_argument("--volume", help="the scan the plan will use, when known")
            b.add_argument("--target", type=float, default=REPEATS_TARGET,
                           help=f"chance that at least one repeat of a seed passes qa (default {REPEATS_TARGET})")
            b.add_argument("--outcome", choices=("kept", "qa"), default="kept",
                           help="kept: a person's review overrules qa when there is one (default); qa: qa alone")
            if name == "freeze":
                b.add_argument("--out", required=True, help="new local advice JSON file; never overwrite")
        else:
            b.add_argument("--machine", help="the machine key to estimate for (default this machine's)")
    b = sub.add_parser("review", help="a person's verdict on one traced surface of a run")
    b.add_argument("out")
    b.add_argument("sid")
    b.add_argument("verdict", choices=("accept", "reject", "clear"))
    b.add_argument("--note")
    b.add_argument("--by")
    b = sub.add_parser("evaluate", help="the preregistered check: does the ledger predict the next runs better than "
                                        "no learning?")
    b.add_argument("--permutations", type=int, default=PERMUTATIONS)


def _settings_arg(text):
    if not text:
        return None
    raw = Path(text[1:]).read_text() if text.startswith("@") else text
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise LearnError("settings are a JSON object")
    return obj


def cli(args):
    import sys
    from . import vc3d_agent
    ctx = vc3d_agent.Context()
    path = store_path(ctx.home)
    act = args.learn_action
    try:
        if act == "verify":
            from . import aplearn_frozen
            res = aplearn_frozen.verify(aplearn_frozen.read(vc3d_agent.resolve(ctx, args.file)))
        elif act == "ingest":
            res = ingest(ctx, [vc3d_agent.resolve(ctx, f) for f in args.folders] or None)
        elif act == "backfill":
            res = backfill(ctx, vc3d_agent.resolve(ctx, args.manifest) if args.manifest else None)
        elif act == "review":
            res = review(ctx, vc3d_agent.resolve(ctx, args.out), args.sid, args.verdict, args.note, args.by)
        else:
            records = load(path)
            if act == "status":
                res = status(records, path)
            elif act == "suggest":
                res = suggest(records, args.sample, _settings_arg(args.settings), args.volume, args.target,
                              args.outcome)
            elif act == "freeze":
                from . import aplearn_frozen
                obj = aplearn_frozen.freeze(records, args.sample, _settings_arg(args.settings), args.volume,
                                             args.target, args.outcome)
                res = aplearn_frozen.write(vc3d_agent.resolve(ctx, args.out), obj)
            elif act == "estimate":
                res = estimate(records, args.sample, _settings_arg(args.settings), args.machine)
            else:
                res = evaluate(records, permutations=args.permutations)
    except (LearnError, vc3d_agent.ToolError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=1, default=str))
    return 0
