"""Scroll to ink in one command: a public scan and a seed point in, a grown, flattened, rendered surface and its ink
map (with the reverse-depth control) out.

It runs nothing of its own. Every step is a tool of Headless VC3D (the `vc3d-agent` package, 1.1.1 or newer), which
calls villa's VC3D command line tools and villa's ink inference and checks what they return:

  inputs   catalog: the scan's CT, its surface prediction and the prediction's normal grids
  seed     seed_check: the seed is on the prediction and on papyrus, not air
  trace    trace: vc_grow_seg_from_seed from the seed, with the normal grids
  check    check_surface: no self-crossings, seated on a sheet (a surface that fails stops the run)
  extend   extend: vc_extend_edge grows the checked surface past its edges; the extension is kept only when it
           passes check_surface too (skipped when this build has no vc_extend_edge)
  flatten  flatten: vc_flatten (ABF++)
  render   render: vc_render_tifxyz along the flat surface, in the team's layer order
  ink      ink: the forward map and the reverse-depth control
  preview  preview: PNGs of the rendered layers and both maps, on one fixed scale
  report   summary.json and report.md in the run folder

    python -m kit scroll2ink run --sample PHerc0139 --seed 4121 3935 5477 [--until STAGE] [--json]
    python -m kit scroll2ink status RUN_DIR [--json]

A run lives in one folder (state.json records each stage); a finished stage is not repeated, so an interrupted or
split run (--until render on a CPU machine, then the rest where a GPU is) resumes. An ink map is model output, not a
reading. On a prize-eligible scan the ink stage needs a preregistered experiment (--experiment SLUG), as the vc3d-agent
`ink` tool requires for a target. Standard library only.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import prizes

STAGES = ("inputs", "seed", "trace", "check", "extend", "flatten", "render", "ink", "preview", "report")
AGENT_ENV = "SCROLL2INK_AGENT"
INSTALL = ("install Headless VC3D: git clone --branch submission/progress-2026-10-vc3d-agent-1-1-1 --depth 1 "
           "https://github.com/ChaseHendrick/Scrolls.git && pip install -e "
           "'Scrolls/submissions/progress-2026-10-vc3d-agent-1-1-1/vc3d-agent[maps]', then set VC_APPIMAGE "
           "(python scripts/get_vc3d.py in that folder) or VC_BIN; or pass --agent 'CMD'")
DEFAULTS = {"generations": 200, "trace_minutes": 60, "extend_rounds": 4, "extend_cells": 10, "check_windows": 5,
            "model": "reader-v2"}
TRACE_GRACE_S = 300      # seconds past --trace-minutes before a tracer that ignores its time limit is stopped
# where and how fast, not what: these may differ between the parts of a split run (CPU for VC3D, a GPU for ink)
RUNTIME = ("device", "threads")


class Scroll2InkError(RuntimeError):
    """A stage could not run or its result failed a check; the message says which and why."""


def eligible_prizes(sample, snapshot=None):
    """The prizes whose eligible list holds `sample` (a scroll named without its A or B part counts when either part
    is listed). Pure apart from reading the dated snapshot."""
    snap = snapshot or prizes.load()
    want = prizes.normalize_scroll(sample)
    hits = []
    for prize in snap["prizes"]:
        for entry in prize.get("eligible") or []:
            name = prizes.normalize_scroll(entry.get("scroll", ""))
            if name == want or (name.rstrip("AB") == want and name != want):
                hits.append(prize["id"])
                break
    return hits


def agent_command(given=None, env=None):
    """argv prefix that runs Headless VC3D: --agent, else $SCROLL2INK_AGENT, else `vc3d-agent` on PATH."""
    env = os.environ if env is None else env
    text = given or env.get(AGENT_ENV)
    if text:
        return shlex.split(text)
    found = shutil.which("vc3d-agent")
    if found:
        return [found]
    raise Scroll2InkError(f"Headless VC3D (vc3d-agent) not found: {INSTALL}")


def call(agent, tool, args, log=None):
    """Run one vc3d-agent tool; returns (exit, result). Exit 0 is success, 1 a tool that ran and failed, 2 bad
    arguments or a refusal (the package's own codes). Its stderr (progress) goes to `log` or ours."""
    argv = [*agent, "vc3d", "call", tool, json.dumps(args)]
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=log or sys.stderr, text=True)
    except OSError as exc:
        raise Scroll2InkError(f"could not start {argv[0]}: {exc}. {INSTALL}") from exc
    try:
        result = json.loads(p.stdout) if p.stdout.strip() else {}
    except json.JSONDecodeError:
        result = {"error": "not JSON", "stdout_tail": p.stdout[-2000:]}
    return p.returncode, result


def pick_volume(volumes, wanted=None):
    """The catalog volume to trace in: `wanted` (id or long id), else the first with both a surface prediction and its
    normal grids. Returns (volume, prediction_url, normal_grids_url) (pure; tested)."""
    rows = volumes.get("volumes") or []
    for v in rows:
        if wanted and wanted not in (v.get("volume"), v.get("long_id")):
            continue
        grids = {g.get("model"): g["url"] for g in v.get("normal_grids") or []}
        for pred in v.get("surface_prediction_zarr") or []:
            if pred.get("model") in grids:
                return v, pred["url"], grids[pred["model"]]
        if wanted:
            preds = v.get("surface_prediction_zarr") or []
            if preds:
                return v, preds[-1]["url"], None
            raise Scroll2InkError(f"volume {wanted} has no surface prediction in the catalog")
    if wanted:
        raise Scroll2InkError(f"volume {wanted} is not in the catalog of {volumes.get('sample')}")
    raise Scroll2InkError(f"no volume of {volumes.get('sample')} has a surface prediction with normal grids; "
                          "name one with --volume")


def preset_for(voxel_um):
    """vc3d-agent render preset for a scan's voxel size (pure; tested)."""
    if voxel_um is None or voxel_um >= 5:
        return "9um"
    return "2um" if voxel_um >= 1.8 else "1um"


def run_dir(root, sample, volume, seed):
    x, y, z = (int(round(v)) for v in seed)
    return Path(root) / f"{sample}-{volume or 'auto'}-{x}_{y}_{z}"


class Run:
    """One run folder: settings.json (fixed at the first call), state.json (one record per stage), logs/."""

    def __init__(self, folder, settings=None, runtime=None):
        self.dir = Path(folder).resolve()
        self.state_path = self.dir / "state.json"
        self.settings_path = self.dir / "settings.json"
        if settings is not None:
            self.dir.mkdir(parents=True, exist_ok=True)
            if self.settings_path.is_file():
                old = json.loads(self.settings_path.read_text())
                changed = sorted(k for k in settings if k in old and old[k] != settings[k])
                if changed:
                    raise Scroll2InkError(f"{self.dir} was started with other settings ({', '.join(changed)}); use "
                                          "a new --out folder, so a result already seen is never mixed with new ones")
                settings = {**settings, **old}
            self._write(self.settings_path, settings)
        if not self.settings_path.is_file():
            raise Scroll2InkError(f"{self.dir} is not a scroll2ink run folder (no settings.json)")
        self.settings = {"device": "cpu", "threads": None, **json.loads(self.settings_path.read_text()),
                         **(runtime or {})}
        self.state = json.loads(self.state_path.read_text()) if self.state_path.is_file() else {"stages": {}}

    @staticmethod
    def _write(path, data):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1) + "\n")
        tmp.replace(path)

    def save(self):
        self._write(self.state_path, self.state)

    def stage(self, name):
        return self.state["stages"].get(name) or {}

    def done(self, name):
        return self.stage(name).get("status") in ("done", "skipped")

    def record(self, name, status, seconds, **fields):
        self.state["stages"][name] = {"status": status, "seconds": round(seconds, 1), **fields}
        self.save()


def _surface(result):
    """Path and area of the surface a trace, extend or flatten result names."""
    surf = result.get("surface")
    if isinstance(surf, dict):
        return surf.get("path") or result.get("out"), surf.get("area_cm2")
    rows = [s for s in result.get("surfaces") or [] if not s.get("error")]
    if rows:
        return rows[-1].get("path"), rows[-1].get("area_cm2")
    return None, None


def stage_inputs(run, agent, log):
    s = run.settings
    rc, res = call(agent, "catalog", {"action": "volumes", "sample": s["sample"]}, log)
    if rc != 0:
        raise Scroll2InkError(f"catalog: {res.get('error') or res}")
    vol, pred, grids = pick_volume(res, s.get("volume"))
    return {"volume": vol["volume"], "long_id": vol.get("long_id"), "ct": vol["url"], "voxel_um": vol.get("voxel_um"),
            "prediction": pred, "normal_grids": grids, "license": vol.get("license"),
            "eligible_prizes": eligible_prizes(s["sample"])}


def stage_seed(run, agent, log, inp):
    rc, res = call(agent, "seed_check", {"volume": inp["prediction"], "seed": run.settings["seed"],
                                         "ct": inp["ct"], "horizon": True}, log)
    if rc == 2 or "error" in res:
        raise Scroll2InkError(f"seed_check: {res.get('error') or res}")
    ok = bool(res.get("ok"))
    if not ok and not run.settings.get("snap_seed"):
        raise Scroll2InkError(f"the seed is not on the surface prediction or not on papyrus (nearest point on it: "
                              f"{res.get('nearest_on')}, {res.get('nearest_distance')} voxels away; CT says "
                              f"{(res.get('ct') or {}).get('verdict')}). Move it, or pass --snap-seed")
    return {"ok": ok, "value": res.get("value"), "nearest_on": res.get("nearest_on"),
            "ct": (res.get("ct") or {}).get("verdict"), "horizon": (res.get("horizon") or {}).get("class")}


def stage_trace(run, agent, log, inp):
    s = run.settings
    args = {"volume": inp["prediction"], "mode": "seed", "seed": s["seed"], "ct": inp["ct"],
            "generations": s["generations"], "out": str(run.dir / "trace"), "name": "trace",
            "time_limit_s": s["trace_minutes"] * 60, "snapshot_interval": 10,
            # a tracer without villa's time limit is stopped here instead, keeping its last snapshot
            "timeout": s["trace_minutes"] * 60 + TRACE_GRACE_S}
    if s.get("snap_seed"):
        args["snap_seed"] = True
    if inp.get("normal_grids"):
        args["normal_grids"] = inp["normal_grids"]
    if inp.get("voxel_um"):
        args["voxel_um"] = inp["voxel_um"]
    # no threads: the tracer does not scale past a few, so the tool's own default (min(4, CPUs)) stays
    rc, res = call(agent, "trace", args, log)
    path, area = _surface(res)
    if rc != 0 or not path:
        raise Scroll2InkError(f"trace: {res.get('error') or res.get('note') or 'no surface'} (log {res.get('log')})")
    stop = res.get("stop") or {}
    return {"surface": path, "area_cm2": area, "stop": stop.get("kind") or stop.get("reason"),
            "partial": stop.get("partial"), "generations_done": stop.get("generations_done"),
            "time_limit": res.get("time_limit"), "data_term": res.get("data_term"), "note": res.get("note"),
            "seconds_tool": res.get("seconds")}


def check(agent, log, surface, inp, windows, out):
    rc, res = call(agent, "check_surface", {"surface": surface, "volume": inp["ct"], "windows": windows, "out": out},
                   log)
    if rc == 2 or "error" in res:
        raise Scroll2InkError(f"check_surface: {res.get('error') or res}")
    seat = res.get("seating") or {}
    return {"verdict": res.get("verdict"), "findings": res.get("findings") or [],
            "seated_windows": seat.get("seated_windows"), "seating": seat.get("verdict"),
            "selfcross": (res.get("selfcross") or {}).get("transverse")}


def stage_check(run, agent, log, inp, tr):
    c = check(agent, log, tr["surface"], inp, run.settings["check_windows"], str(run.dir / "check-trace"))
    if c["verdict"] != "ok" and not run.settings.get("force"):
        raise Scroll2InkError(f"check_surface says {c['verdict']!r}: {'; '.join(c['findings'])}. The surface may "
                              "have left its sheet, so it is not rendered; try another seed, or --force to go on")
    return c


def stage_extend(run, agent, log, inp, tr):
    s = run.settings
    if not s["extend_rounds"]:
        return "skipped", {"why": "--extend-rounds 0", "surface": tr["surface"], "area_cm2": tr["area_cm2"]}
    args = {"surface": tr["surface"], "normals": inp["prediction"], "rounds": s["extend_rounds"],
            "cells": s["extend_cells"], "out": str(run.dir / "extend" / "extended")}
    if s.get("threads"):
        args["threads"] = s["threads"]
    rc, res = call(agent, "extend", args, log)
    if "vc_extend_edge is not in" in str(res.get("error", "")):
        return "skipped", {"why": "this VC3D build has no vc_extend_edge", "surface": tr["surface"],
                           "area_cm2": tr["area_cm2"]}
    path, area = _surface(res)
    if rc != 0 or not path:
        return "skipped", {"why": f"extend failed: {res.get('error') or res.get('log_tail', '')[-300:]}",
                           "surface": tr["surface"], "area_cm2": tr["area_cm2"]}
    c = check(agent, log, path, inp, s["check_windows"], str(run.dir / "check-extend"))
    if c["verdict"] != "ok":
        return "done", {"kept": False, "why": f"the extension failed check_surface ({c['verdict']}: "
                        f"{'; '.join(c['findings'])}), so the checked trace goes on", "extended": path,
                        "extended_area_cm2": area, "check": c, "surface": tr["surface"], "area_cm2": tr["area_cm2"],
                        "seconds_tool": res.get("seconds")}
    return "done", {"kept": True, "surface": path, "area_cm2": area, "check": c, "seconds_tool": res.get("seconds")}


def stage_flatten(run, agent, log, surf):
    rc, res = call(agent, "flatten", {"surface": surf, "out": str(run.dir / "flat" / "flat")}, log)
    path, area = _surface(res)
    if rc != 0 or not path:
        raise Scroll2InkError(f"flatten: {res.get('error') or res.get('log_tail', '')[-500:]}")
    return {"surface": path, "area_cm2": area}


def stage_render(run, agent, log, inp, flat):
    args = {"surface": flat, "volume": inp["ct"], "preset": preset_for(inp.get("voxel_um")), "auto_crop": True,
            "out": str(run.dir / "render")}
    if inp.get("voxel_um"):
        args["voxel_um"] = inp["voxel_um"]
    if run.settings.get("threads"):
        args["threads"] = run.settings["threads"]
    rc, res = call(agent, "render", args, log)
    if rc != 0 or not res.get("zarr"):
        raise Scroll2InkError(f"render: {res.get('error') or res.get('log_tail', '')[-500:]}")
    return {"zarr": res["zarr"], "shape": res.get("shape"), "order": res.get("order"),
            "warnings": res.get("warnings") or []}


def stage_ink(run, agent, log, inp, rnd):
    s = run.settings
    eligible = inp.get("eligible_prizes") or []
    if eligible and not s.get("experiment"):
        raise Scroll2InkError(f"{s['sample']} is prize-eligible ({', '.join(eligible)}): ink on it needs a "
                              "preregistered experiment, --experiment SLUG (python -m kit run init)")
    rc, known = call(agent, "models", {"action": "list"}, log)
    names = known.get("models") or {}
    if s["model"] not in names and s["model"] not in [m.get("name") for m in names if isinstance(m, dict)]:
        rc, res = call(agent, "fetch_model", {"name": s["model"]}, log)
        if rc != 0:
            raise Scroll2InkError(f"fetch_model {s['model']}: {res.get('error') or res}")
    args = {"input": rnd["zarr"], "purpose": "target" if eligible else "benchmark", "model": s["model"],
            "device": s["device"], "variants": ["f", "r"]}
    if eligible:
        args["experiment"] = s["experiment"]
    else:
        args["out"] = str(run.dir / "ink")
    if s.get("threads"):
        args["threads"] = s["threads"]
    rc, res = call(agent, "ink", args, log)
    maps = {k: (v or {}).get("path") for k, v in (res.get("maps") or {}).items()}
    if rc != 0 or not maps.get("f") or not maps.get("r"):
        raise Scroll2InkError(f"ink: {res.get('error') or res.get('log_tail', '')[-500:]}")
    return {"maps": maps, "comparison": res.get("comparison"), "device": res.get("device"), "out": res.get("out"),
            "model": s["model"], "warnings": res.get("warnings") or []}


def stage_preview(run, agent, log, rnd, ink):
    out = run.dir / "previews"
    out.mkdir(exist_ok=True)
    shots = {"layers_max": {"path": rnd["zarr"], "mode": "max"}, "layer_mid": {"path": rnd["zarr"], "mode": "layer"}}
    if ink:
        for k, name in (("f", "ink_forward"), ("r", "ink_reverse")):
            # one fixed scale for both maps, so the control compares by eye (uint8 maps, villa's encoding)
            shots[name] = {"path": ink["maps"][k], "range": [0, 255]}
    pngs = {}
    for name, args in shots.items():
        rc, res = call(agent, "preview", {**args, "out": str(out / f"{name}.png"), "max_side": 1600}, log)
        if rc == 0 and res.get("png"):
            pngs[name] = res["png"]
        else:
            pngs[name] = None
    return {"pngs": pngs}


def summary(run):
    st, s = run.state["stages"], run.settings
    inp = st.get("inputs", {})
    final = st.get("extend", {}) if st.get("extend", {}).get("surface") else st.get("trace", {})
    return {"sample": s["sample"], "volume": inp.get("volume"), "voxel_um": inp.get("voxel_um"), "seed": s["seed"],
            "surface": final.get("surface"), "area_cm2": final.get("area_cm2"),
            "extension_kept": st.get("extend", {}).get("kept"),
            "check": (st.get("check") or {}).get("verdict"), "render": (st.get("render") or {}).get("zarr"),
            "ink_maps": (st.get("ink") or {}).get("maps"), "ink_comparison": (st.get("ink") or {}).get("comparison"),
            "previews": (st.get("preview") or {}).get("pngs"),
            "seconds": {k: v.get("seconds") for k, v in st.items()},
            "stages": {k: v.get("status") for k, v in st.items()},
            "note": "An ink map is model output, not a reading. The reverse-depth map is its control."}


def report_md(sm):
    lines = [f"# scroll2ink: {sm['sample']} {sm['volume']}, seed {sm['seed']}", "",
             "| Stage | Status | Seconds |", "| --- | --- | --- |"]
    for k in STAGES:
        if k in sm["stages"]:
            lines.append(f"| {k} | {sm['stages'][k]} | {sm['seconds'].get(k)} |")
    lines += ["", f"Surface: `{sm['surface']}`, {sm['area_cm2']} cm2; check_surface: {sm['check']}; extension kept: "
              f"{sm['extension_kept']}.", f"Render: `{sm['render']}`.", f"Ink maps: {sm['ink_maps']}.",
              f"Forward against reverse: {json.dumps(sm['ink_comparison'])}.", "", sm["note"], ""]
    return "\n".join(lines)


def execute(run, agent, until=None, say=print, log=None):
    """Run every stage not yet done, in order, up to and including `until`. Returns the summary dict; raises
    Scroll2InkError at the first stage that fails (recorded in state.json as failed)."""
    st = run.state["stages"]
    last = STAGES.index(until) if until else len(STAGES) - 1
    for i, name in enumerate(STAGES[:last + 1]):
        if run.done(name):
            say(f"[{i + 1}/{len(STAGES)}] {name:8} already {run.stage(name)['status']}")
            continue
        say(f"[{i + 1}/{len(STAGES)}] {name:8} running")
        t = time.time()
        status = "done"
        try:
            if name == "inputs":
                out = stage_inputs(run, agent, log)
            elif name == "seed":
                out = stage_seed(run, agent, log, st["inputs"])
            elif name == "trace":
                out = stage_trace(run, agent, log, st["inputs"])
            elif name == "check":
                out = stage_check(run, agent, log, st["inputs"], st["trace"])
            elif name == "extend":
                status, out = stage_extend(run, agent, log, st["inputs"], st["trace"])
            elif name == "flatten":
                out = stage_flatten(run, agent, log, st["extend"]["surface"])
            elif name == "render":
                out = stage_render(run, agent, log, st["inputs"], st["flatten"]["surface"])
            elif name == "ink":
                out = stage_ink(run, agent, log, st["inputs"], st["render"])
            elif name == "preview":
                out = stage_preview(run, agent, log, st["render"], st.get("ink"))
            else:
                sm = summary(run)
                (run.dir / "summary.json").write_text(json.dumps(sm, indent=1) + "\n")
                (run.dir / "report.md").write_text(report_md(sm))
                out = {"summary": str(run.dir / "summary.json"), "report": str(run.dir / "report.md")}
        except Scroll2InkError as exc:
            run.record(name, "failed", time.time() - t, error=str(exc))
            say(f"[{i + 1}/{len(STAGES)}] {name:8} FAILED after {time.time() - t:.0f} s: {exc}")
            raise
        run.record(name, status, time.time() - t, **out)
        say(f"[{i + 1}/{len(STAGES)}] {name:8} {status} in {time.time() - t:.0f} s" + _brief(name, out))
    return summary(run)


def _brief(name, out):
    if name == "inputs":
        return f": {out['long_id']}, {out['voxel_um']} um"
    if name in ("trace", "flatten") or (name == "extend" and out.get("area_cm2")):
        return f": {out.get('area_cm2')} cm2" + ("" if name != "extend" or out.get("kept", True) else " (not kept)")
    if name == "check":
        return f": {out['verdict']}, {out['seated_windows']} windows seated"
    if name == "render":
        return f": {out.get('shape')}"
    if name == "ink":
        return f": {out['model']} on {out['device']}, forward and reverse"
    return ""


def settings_from(args):
    """The run's fixed settings (settings.json) and its runtime options (pure; tested)."""
    s = {"sample": args.sample, "seed": [float(v) for v in args.seed], "volume": args.volume}
    for k in DEFAULTS:
        s[k] = getattr(args, k)
    s.update(snap_seed=args.snap_seed, force=args.force, experiment=args.experiment)
    return s, {k: getattr(args, k) for k in RUNTIME}


def add_arguments(p):
    sub = p.add_subparsers(dest="action", required=True)
    r = sub.add_parser("run", help="run (or resume) every stage from a seed point to an ink map")
    r.add_argument("--sample", required=True, help="open-data sample, such as PHerc0139")
    r.add_argument("--seed", required=True, nargs=3, type=float, metavar=("X", "Y", "Z"),
                   help="seed point in level-0 voxels of the volume")
    r.add_argument("--volume", help="volume id (default: the first with a surface prediction and normal grids)")
    r.add_argument("--out", help="run folder (default work/scroll2ink/SAMPLE-VOLUME-X_Y_Z)")
    r.add_argument("--until", choices=STAGES, help="stop after this stage (resume later with the same command)")
    r.add_argument("--generations", type=int, default=DEFAULTS["generations"], help="tracer generations (default 200)")
    r.add_argument("--trace-minutes", type=int, default=DEFAULTS["trace_minutes"],
                   help="trace time limit; a stopped trace keeps its last snapshot (default 60)")
    r.add_argument("--extend-rounds", type=int, default=DEFAULTS["extend_rounds"],
                   help="vc_extend_edge rounds, 0 to skip (default 4)")
    r.add_argument("--extend-cells", type=int, default=DEFAULTS["extend_cells"], help="cells per side per round (10)")
    r.add_argument("--check-windows", type=int, default=DEFAULTS["check_windows"],
                   help="check_surface windows spread over the surface (default 5)")
    r.add_argument("--model", default=DEFAULTS["model"],
                   help="ink model known to vc3d-agent (reader-v2, ink_9um-seed42, ink_9um-seed43, d9v2, v8in)")
    r.add_argument("--device", default="cpu", help="ink device: cpu (default), cuda or mps (may change on resume)")
    r.add_argument("--threads", type=int, help="threads for each tool (may change on resume)")
    r.add_argument("--snap-seed", action="store_true", help="move a seed off the prediction to the nearest point on it")
    r.add_argument("--force", action="store_true", help="go on when check_surface does not say ok")
    r.add_argument("--experiment", help="preregistered experiment slug: required for ink on a prize-eligible scan")
    r.add_argument("--agent", help="command that runs Headless VC3D (default $SCROLL2INK_AGENT or vc3d-agent)")
    r.add_argument("--dry-run", action="store_true", help="print the run folder and settings; run nothing")
    r.add_argument("--json", action="store_true", help="print the summary as JSON")
    s = sub.add_parser("status", help="what a run folder holds, stage by stage")
    s.add_argument("dir")
    s.add_argument("--json", action="store_true")


def run_cli(args, root=None):
    if args.action == "status":
        try:
            run = Run(args.dir)
        except Scroll2InkError as exc:
            print(exc, file=sys.stderr)
            return 2
        sm = summary(run)
        if args.json:
            print(json.dumps(sm, indent=1))
        else:
            for k in STAGES:
                rec = run.stage(k)
                extra = f": {rec['error']}" if rec.get("error") else ""
                print(f"{k:8} {rec.get('status', 'not started'):12} {rec.get('seconds', '')}{extra}")
        return 0
    root = Path(root or os.environ.get("KIT_HOME") or Path(__file__).resolve().parents[1])
    folder = Path(args.out) if args.out else run_dir(root / "work" / "scroll2ink", args.sample, args.volume, args.seed)
    settings, runtime = settings_from(args)
    if args.dry_run:
        print(json.dumps({"run": str(folder), "settings": settings, "runtime": runtime, "stages": list(STAGES)},
                         indent=1))
        return 0
    say = (lambda m: print(m, file=sys.stderr)) if args.json else print
    try:
        agent = agent_command(args.agent)
        run = Run(folder, settings, runtime)
        say(f"run folder {run.dir}")
        sm = execute(run, agent, until=args.until, say=say)
    except Scroll2InkError as exc:
        print(f"scroll2ink: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(sm, indent=1))
    elif sm["stages"].get("report") == "done":
        print(f"surface {sm['area_cm2']} cm2, check {sm['check']}; report {run.dir / 'report.md'}")
        print(sm["note"])
    else:
        print(f"stopped after {args.until}; the same command resumes from the next stage")
    return 0
