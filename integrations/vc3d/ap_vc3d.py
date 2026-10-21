#!/usr/bin/env python3
"""AutoPipeline and VC3D, both ways, for the released AutoPipeline package (0.1.5) and VC3D from villa main.

    python3 ap_vc3d.py here --point X,Y,Z --volume URL      # plan a run seeded at a VC3D point; computes nothing
    python3 ap_vc3d.py here --bridge                         # the same, reading the point and volume from VC3D
    python3 ap_vc3d.py start --run last --digest last        # start that exact plan in the background
    python3 ap_vc3d.py load --run last --dest DIR            # copy accepted surfaces and seed points for VC3D
    python3 ap_vc3d.py open --run last                       # load, then attach them in a running VC3D
    python3 ap_vc3d.py manifests [--install DIR]             # plugin files for VC3D's Plugins menu (not in villa yet)

Standard library only. It never imports AutoPipeline: it runs the `scrolls-kit` command that `pip install -e .` puts
in the AutoPipeline package's environment (or the one named by --kit or AP_KIT), so it works with any AutoPipeline
release that has `autopipeline plan`, `run` and `status`. The VC3D side uses villa's agent bridge (villa
apps/VC3D/agent_bridge/SPEC.md), which VC3D on villa main serves when started with --agent-bridge, and, once the
combined VC3D change lands, VC3D's plugin manifests (schema vc3d-plugin/1). Every surface and map it moves is model
output, not a reading. Guide: docs/autopipeline/guide.md; page: docs/tools/autopipeline-vc3d.md.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

VERSION = "1"
MANIFEST_SCHEMA = "vc3d-plugin/1"
POINTS_VERSION = "1"
# An open-data catalog volume: .../<sample>/volumes/<14-digit volume id>-<anything>.zarr, as a URL or a local mirror.
VOLUME_PATTERN = re.compile(r"(?:^|/)(?P<sample>PHerc[A-Za-z0-9.]+)/volumes/(?P<volume>\d{14})-[^/]*\.zarr/?$")
BRIDGE_TIMEOUT = 30.0
FORBIDDEN_SETTINGS = ("segment", "external_prediction")
DETACHED = []  # background runs started by this process; kept so Python does not warn about them while it runs


class Refusal(Exception):
    """A refusal with a message for the person; exit code 2."""


def home():
    return Path(os.environ.get("AP_VC3D_HOME") or Path.home() / ".autopipeline-vc3d")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def kit_command(given=None):
    """The scrolls-kit command as an argv prefix: --kit, then AP_KIT, then scrolls-kit on PATH."""
    cmd = given or os.environ.get("AP_KIT") or shutil.which("scrolls-kit")
    if not cmd:
        raise Refusal("no scrolls-kit command: activate the AutoPipeline environment, or pass --kit PATH or set "
                      "AP_KIT to its scrolls-kit")
    return [cmd]


def parse_point(text):
    try:
        xyz = [float(v) for v in str(text).split(",")]
    except ValueError:
        xyz = []
    if len(xyz) != 3 or not all(math.isfinite(v) and v >= 0 for v in xyz):
        raise Refusal(f"the point must be x,y,z: three numbers at or above 0 in full-resolution voxels, not {text!r}")
    return xyz


def catalog_volume(volume):
    """(sample, volume id) of an open-data catalog volume URL or a local copy that keeps the bucket's layout."""
    m = VOLUME_PATTERN.search(str(volume).strip())
    if not m:
        raise Refusal(f"{volume!r} is not an open-data catalog volume (.../SAMPLE/volumes/ID-....zarr); AutoPipeline "
                      "plans only catalog scans")
    return m.group("sample"), m.group("volume")


def plan_settings(settings_text, volume_id, xyz):
    """The user's settings with the volume and one seed point added; refuses settings that would ignore the point."""
    try:
        settings = json.loads(settings_text or "{}")
    except json.JSONDecodeError as exc:
        raise Refusal(f"the settings are not JSON: {exc}") from exc
    if not isinstance(settings, dict):
        raise Refusal("the settings must be a JSON object")
    for key in FORBIDDEN_SETTINGS:
        if settings.get(key) not in (None, False):
            raise Refusal(f"setting {key!r} replaces the seed point; plan it with scrolls-kit autopipeline plan instead")
    if settings.get("volume") not in (None, volume_id):
        raise Refusal(f"setting volume {settings['volume']!r} differs from the volume open in VC3D ({volume_id})")
    seeds = settings.get("seeds") or {}
    if not isinstance(seeds, dict):
        raise Refusal("setting seeds must be a JSON object")
    if seeds.get("points"):
        raise Refusal("setting seeds.points is filled from the VC3D point; leave it out")
    return dict(settings, volume=volume_id, seeds=dict(seeds, points=[xyz]))


def run_kit(kit, args, timeout=600):
    try:
        proc = subprocess.run(kit + args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise Refusal(f"cannot run {kit[0]}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise Refusal(f"{' '.join(kit + args[:2])} did not finish in {timeout} s") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        raise Refusal(f"autopipeline {args[1]} exited {proc.returncode}: {' | '.join(tail) or 'no output'}")
    return proc.stdout


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_last():
    f = home() / "last.json"
    if not f.is_file():
        raise Refusal(f"no plan made here yet ({f} is missing); run ap_vc3d.py here first, or name the run folder")
    return json.loads(f.read_text(encoding="utf-8"))


def run_folder(run):
    folder = Path(load_last()["out"] if run in (None, "last") else run).expanduser()
    if not (folder / "plan.json").is_file():
        raise Refusal(f"{folder} has no plan.json; name an AutoPipeline run folder")
    return folder.resolve()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


# ---------------------------------------------------------------- VC3D's agent bridge (villa main)

def bridge_socket(given=None, registry=None):
    """An explicit socket, else the newest live record VC3D wrote under ~/.vc3d/agent_bridge/."""
    if given:
        return given
    registry = Path(registry or Path.home() / ".vc3d" / "agent_bridge")
    best = None
    for f in sorted(registry.glob("*.json")) if registry.is_dir() else []:
        rec = read_json(f, {})
        if not isinstance(rec, dict) or not rec.get("path") or not isinstance(rec.get("pid"), int):
            continue
        try:
            os.kill(rec["pid"], 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            pass
        if best is None or float(rec.get("startedAt") or 0) > float(best.get("startedAt") or 0):
            best = rec
    if best is None:
        raise Refusal("no running VC3D bridge: start VC3D with --agent-bridge, or pass --socket PATH")
    return best["path"]


class Bridge:
    """Newline-delimited JSON-RPC 2.0 over VC3D's Unix socket (SPEC.md, Wire protocol)."""

    def __init__(self, path, timeout=BRIDGE_TIMEOUT):
        self.path, self.timeout, self.next_id, self.calls = path, timeout, 0, []

    def call(self, method, params=None):
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(self.timeout)
            try:
                s.connect(self.path)
            except OSError as exc:
                raise Refusal(f"cannot reach VC3D's bridge at {self.path}: {exc}") from exc
            s.sendall((json.dumps(msg) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        self.calls.append(method)
        try:
            reply = json.loads(buf.decode("utf-8").splitlines()[0])
        except (IndexError, json.JSONDecodeError) as exc:
            raise Refusal(f"VC3D's bridge gave no reply to {method}") from exc
        if reply.get("error"):
            err = reply["error"]
            raise Refusal(f"VC3D refused {method}: {err.get('message')} ({err.get('code')})")
        return reply.get("result")

    def methods(self):
        desc = self.call("rpc.describe") or {}
        return set(desc.get("methods") or {})


def point_from_bridge(bridge):
    state = bridge.call("state.get") or {}
    volume = (state.get("volume") or {}).get("path")
    poi = (state.get("focusPoi") or {}).get("position")
    if not volume:
        raise Refusal("VC3D has no volume open")
    if not poi:
        raise Refusal("VC3D has no focus point; click on the papyrus first")
    if isinstance(poi, dict):
        poi = [poi.get("x"), poi.get("y"), poi.get("z")]
    return ",".join(str(v) for v in poi), volume


# ---------------------------------------------------------------- commands

def cmd_here(args):
    kit = kit_command(args.kit)
    point, volume = args.point, args.volume
    if args.bridge:
        point, volume = point_from_bridge(Bridge(bridge_socket(args.socket)))
    if not point or not volume:
        raise Refusal("give --point and --volume, or --bridge to read them from VC3D")
    xyz = parse_point(point)
    sample, volume_id = catalog_volume(volume)
    settings = plan_settings(args.settings, volume_id, xyz)
    out = json.loads(run_kit(kit, ["autopipeline", "plan", sample, "--settings", json.dumps(settings)]))
    rec = {"tool": "ap_vc3d", "version": VERSION, "at": now(), "sample": sample, "volume": volume_id,
           "volume_location": volume, "point_xyz": xyz, "out": out["out"], "digest": out["digest"],
           "volume_url": out.get("resolved", {}).get("volume_url"), "kit": kit[0], "settings": settings}
    write_text(home() / "last.json", json.dumps(rec, indent=1))
    start = f"python3 {Path(__file__).resolve()} start --run {out['out']} --digest {out['digest'][:16]}"
    lines = [
        "AutoPipeline plan made. Nothing was computed or launched.",
        f"Scan: {sample}, volume {volume_id}",
        f"Seed point (x,y,z, full-resolution voxels): {xyz[0]:g},{xyz[1]:g},{xyz[2]:g}",
        f"Run folder: {out['out']}",
        f"Plan digest: {out['digest']}",
        "Cost: a local run costs time only. Ink with no GPU environment stops at a handoff file (modal-job.json);",
        "nothing paid is started. AutoPipeline 0.1.5 prints no price.",
        "Start exactly this plan:",
        f"  {start}",
        "Every surface, map and score a run makes is model output, not a reading.",
    ]
    rec["start_command"] = start
    finish(args, "\n".join(lines) + "\n", rec)
    return 0


def pid_alive(pid_file):
    try:
        pid = int(Path(pid_file).read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return None
    return pid


def cmd_start(args):
    kit = kit_command(args.kit)
    folder = run_folder(args.run)
    want = load_last()["digest"] if args.digest in (None, "last") else args.digest.strip().lower()
    have = (read_json(folder / "plan.json", {}) or {}).get("digest", "")
    if len(want) < 10 or not have.startswith(want):
        raise Refusal(f"the plan in {folder} has digest {have[:16]}..., not {want[:16]}...; plan again with "
                      "ap_vc3d.py here")
    runs = home() / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    pid_file, log = runs / f"{have[:16]}.pid", runs / f"{have[:16]}.log"
    alive = pid_alive(pid_file)
    if alive:
        raise Refusal(f"a run of this plan is already going (process {alive}); watch it with scrolls-kit "
                      f"autopipeline status {folder}")
    with open(log, "ab") as fh:
        proc = subprocess.Popen(kit + ["autopipeline", "run", str(folder)], stdin=subprocess.DEVNULL, stdout=fh,
                                stderr=subprocess.STDOUT, start_new_session=True)
    DETACHED.append(proc)
    write_text(pid_file, f"{proc.pid}\n")
    rec = {"tool": "ap_vc3d", "version": VERSION, "at": now(), "out": str(folder), "digest": have,
           "pid": proc.pid, "log": str(log)}
    lines = [
        f"Started AutoPipeline in the background (process {proc.pid}).",
        f"Run folder: {folder}",
        f"Log: {log}",
        f"Watch: scrolls-kit autopipeline monitor {folder} --open",
        f"Status: scrolls-kit autopipeline status {folder}",
        f"When surfaces are accepted: python3 {Path(__file__).resolve()} open --run {folder}",
        "Ink with no GPU environment stops at a handoff file; nothing paid is started.",
    ]
    finish(args, "\n".join(lines) + "\n", rec)
    return 0


def seed_points(folder):
    seeds = (read_json(folder / "seeds.json", {}) or {}).get("seeds") or []
    return [s["xyz"] for s in seeds if isinstance(s, dict) and isinstance(s.get("xyz"), list) and len(s["xyz"]) == 3]


def points_document(name, points):
    """VC3D's point collection file (vc_pointcollections_json_version 1), as its Point Collections panel saves it."""
    return {"vc_pointcollections_json_version": POINTS_VERSION,
            "collections": {"1": {"name": name, "color": [0.72, 0.48, 0.33],
                                  "points": {str(i + 1): {"p": [float(v) for v in p]} for i, p in enumerate(points)}}}}


def cmd_load(args, dest=None):
    folder = run_folder(args.run)
    plan = read_json(folder / "plan.json", {})
    state = read_json(folder / "state.json", {}) or {}
    digest = plan.get("digest", "")
    dest = Path(dest or args.dest).expanduser().resolve()
    seg_dir = dest / "segments"
    copied, skipped = [], []
    for sid, s in sorted((state.get("surfaces") or {}).items()):
        src = Path(s.get("surface") or "")
        if not s.get("accepted"):
            skipped.append({"surface": sid, "why": "not accepted by the run's rule"})
            continue
        if not (src / "meta.json").is_file():
            skipped.append({"surface": sid, "why": f"no tifxyz at {src}"})
            continue
        target = seg_dir / f"ap-{digest[:10]}-{sid}"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target)
        copied.append({"surface": sid, "segment": str(target)})
    points = seed_points(folder)
    seeds_file = None
    if points:
        seeds_file = dest / "seeds.json"
        write_text(seeds_file, json.dumps(points_document(f"AutoPipeline seeds {digest[:10]}", points), indent=1))
    need = getattr(args, "need", "any")
    if (need == "segments" and not copied) or (need == "seeds" and not seeds_file) or not (copied or seeds_file):
        what = {"segments": "no accepted surface", "seeds": "no seed points"}.get(need, "no accepted surface and no "
                                                                                     "seed points")
        raise Refusal(f"{folder} has {what} yet; check scrolls-kit autopipeline status {folder}")
    rec = {"tool": "ap_vc3d", "version": VERSION, "at": now(), "out": str(folder), "digest": digest,
           "volume_url": (plan.get("resolved") or {}).get("volume_url"), "segments_dir": str(seg_dir) if copied else None,
           "segments": copied, "skipped": skipped, "seeds": str(seeds_file) if seeds_file else None,
           "seed_points": points, "note": "Every surface is model output, not a reading."}
    write_text(dest / "load.json", json.dumps(rec, indent=1))
    if args.command == "open":
        return rec
    lines = [f"Copied {len(copied)} accepted surface(s) to {seg_dir}" + (f"; skipped {len(skipped)}" if skipped else "")]
    if seeds_file:
        lines.append(f"Wrote {len(points)} seed point(s) to {seeds_file}")
    url = rec["volume_url"] or ""
    attach = "File > Attach Remote Zarr..." if url.startswith(("http://", "https://", "s3://")) else "File > Attach Volume..."
    lines.append(f"VC3D: {attach} {url}, then File > Attach Segments... {seg_dir}")
    if seeds_file:
        lines.append(f"Seed points: the Point Collections panel, Load, {seeds_file}")
    finish(args, "\n".join(lines) + "\n", rec)
    return 0


def cmd_open(args):
    folder = run_folder(args.run)
    digest = (read_json(folder / "plan.json", {}) or {}).get("digest", "")
    dest = Path(args.dest).expanduser() if args.dest else home() / "open" / digest[:16]
    rec = cmd_load(args, dest=dest)
    bridge = Bridge(bridge_socket(args.socket))
    have = bridge.methods()
    steps = []
    plan = [("volume.attach", {"location": rec["volume_url"]}, bool(rec["volume_url"])),
            ("segments.attach", {"location": rec["segments_dir"], "select": True}, bool(rec["segments_dir"])),
            ("points.load_json", {"path": rec["seeds"]}, bool(rec["seeds"]))]
    first = (rec["seed_points"] or [None])[0]
    if first:
        plan.append(("viewer.center_on_point", {"point": dict(zip("xyz", first))}, True))
    for method, params, wanted in plan:
        if not wanted:
            continue
        if method not in have:
            steps.append({"method": method, "done": False, "why": "this VC3D does not offer it (rpc.describe)"})
            continue
        bridge.call(method, params)
        steps.append({"method": method, "done": True})
    rec["bridge_calls"] = steps
    done = [s["method"] for s in steps if s["done"]]
    lines = [f"Opened in VC3D: {', '.join(done) or 'nothing'}"]
    lines += [f"Skipped {s['method']}: {s['why']}" for s in steps if not s["done"]]
    finish(args, "\n".join(lines) + "\n", rec)
    return 0


def manifests(kit_path, script=None, python=None):
    """The plugin manifests (schema vc3d-plugin/1) with this machine's Python, this script and scrolls-kit written in."""
    script, python = str(script or Path(__file__).resolve()), str(python or os.path.abspath(sys.executable))
    guide = "https://github.com/ChaseHendrick/Scrolls/blob/main/docs/autopipeline/guide.md"
    common = {"schema": MANIFEST_SCHEMA, "menu": "AutoPipeline", "program": python, "homepage": guide,
              "license": "Apache-2.0"}
    settings = {"name": "settings", "label": "AutoPipeline settings over the defaults (a JSON object)", "default": "{}"}
    run = {"name": "run", "label": "Run folder (last: the plan made last from VC3D)", "default": "last"}
    return [
        dict(common, id="autopipeline.here", name="Plan an AutoPipeline run here",
             description="Plans an AutoPipeline run seeded at the focus point on the open catalog scan and writes "
                         "its folder, digest and start command. Computes nothing and starts nothing.",
             args=[script, "here", "--point", "{point}", "--volume", "{volume}", "--settings", "{input:settings}",
                   "--kit", kit_path, "--summary", "{output}/plan.txt"],
             inputs=[settings], result={"kind": "file", "path": "{output}/plan.txt"}),
        dict(common, id="autopipeline.start", name="Start the planned AutoPipeline run",
             description="Starts the plan made last from VC3D, after checking its digest, in the background, and "
                         "returns. Ink with no GPU environment stops at a handoff file; nothing paid is started.",
             args=[script, "start", "--run", "{input:run}", "--digest", "last", "--kit", kit_path,
                   "--summary", "{output}/started.txt"],
             inputs=[run], result={"kind": "file", "path": "{output}/started.txt"}),
        dict(common, id="autopipeline.surfaces", name="Load AutoPipeline surfaces",
             description="Copies the surfaces an AutoPipeline run accepted and attaches them as segments. "
                         "A surface is model output, not a reading.",
             args=[script, "load", "--run", "{input:run}", "--dest", "{output}", "--need", "segments",
                   "--summary", "{output}/load.txt"],
             inputs=[run], result={"kind": "segment", "path": "{output}/segments"}),
        dict(common, id="autopipeline.seeds", name="Load AutoPipeline seed points",
             description="Adds the seed points of an AutoPipeline run as a point collection.",
             args=[script, "load", "--run", "{input:run}", "--dest", "{output}", "--need", "seeds",
                   "--summary", "{output}/load.txt"],
             inputs=[run], result={"kind": "points", "path": "{output}/seeds.json"}),
    ]


def cmd_manifests(args):
    kit = kit_command(args.kit)[0]
    kit = str(Path(shutil.which(kit) or kit).resolve())
    docs = manifests(kit)
    if not args.install:
        finish(args, json.dumps(docs, indent=1) + "\n", {"manifests": docs})
        return 0
    folder = Path(args.install).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for doc in docs:
        target = folder / f"{doc['id'].replace('.', '-')}.json"
        text = json.dumps(doc, indent=1) + "\n"
        if target.exists() and target.read_text(encoding="utf-8") != text and not args.force:
            raise Refusal(f"{target} exists and differs; read it, then pass --force to replace it")
        write_text(target, text)
        written.append({"file": str(target), "sha256": hashlib.sha256(text.encode()).hexdigest()})
    lines = [f"Wrote {len(written)} plugin manifests to {folder}"]
    lines += [f"  {w['file']}" for w in written]
    lines.append(f"VC3D reads them from ~/.vc3d/plugins or VC3D_PLUGIN_PATH={folder} once its plugin host is in "
                 "villa; Plugins > Reload Plugins picks them up.")
    finish(args, "\n".join(lines) + "\n", {"manifests": written})
    return 0


def finish(args, text, rec):
    if getattr(args, "summary", None):
        write_text(args.summary, text)
    sys.stdout.write(json.dumps(rec, indent=1) + "\n" if getattr(args, "json", False) else text)


def build_parser():
    p = argparse.ArgumentParser(prog="ap_vc3d.py", description="AutoPipeline and VC3D, both ways.")
    sub = p.add_subparsers(dest="command", required=True)

    def common(a, kit=True):
        if kit:
            a.add_argument("--kit", help="the scrolls-kit command of the AutoPipeline environment (default: AP_KIT, "
                                         "then scrolls-kit on PATH)")
        a.add_argument("--summary", help="also write the printed text to this file")
        a.add_argument("--json", action="store_true", help="print one JSON object instead of text")

    a = sub.add_parser("here", help="plan a run seeded at a VC3D point on a catalog scan; computes nothing")
    a.add_argument("--point", help="x,y,z in full-resolution voxels (VC3D's {point})")
    a.add_argument("--volume", help="the open volume's URL or path (VC3D's {volume})")
    a.add_argument("--settings", default="{}", help="AutoPipeline settings over the defaults, a JSON object")
    a.add_argument("--bridge", action="store_true", help="read the point and volume from a running VC3D")
    a.add_argument("--socket", help="VC3D bridge socket (default: the newest live one)")
    common(a)
    a = sub.add_parser("start", help="start a planned run in the background after checking its digest")
    a.add_argument("--run", default="last", help="run folder, or last (default)")
    a.add_argument("--digest", default="last", help="the plan digest you saw (at least 10 characters), or last")
    common(a)
    a = sub.add_parser("load", help="copy a run's accepted surfaces and seed points for VC3D")
    a.add_argument("--run", default="last", help="run folder, or last (default)")
    a.add_argument("--dest", required=True, help="folder to write segments/, seeds.json and load.json into")
    a.add_argument("--need", choices=["any", "segments", "seeds"], default="any",
                   help="refuse unless this was written (default any)")
    common(a, kit=False)
    a = sub.add_parser("open", help="load a run, then attach it in a running VC3D over its bridge")
    a.add_argument("--run", default="last", help="run folder, or last (default)")
    a.add_argument("--dest", help="folder for the copies (default: AP_VC3D_HOME/open/DIGEST)")
    a.add_argument("--socket", help="VC3D bridge socket (default: the newest live one)")
    common(a, kit=False)
    a = sub.add_parser("manifests", help="print or install VC3D plugin manifests for these commands")
    a.add_argument("--install", help="write them into this folder instead of printing them")
    a.add_argument("--force", action="store_true", help="replace manifests that differ")
    common(a)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return {"here": cmd_here, "start": cmd_start, "load": cmd_load, "open": cmd_open,
                "manifests": cmd_manifests}[args.command](args)
    except Refusal as exc:
        print(f"ap_vc3d: {exc}", file=sys.stderr)
        if getattr(args, "summary", None):
            write_text(args.summary, f"Refused: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
