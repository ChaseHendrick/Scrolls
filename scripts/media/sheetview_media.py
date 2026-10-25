#!/usr/bin/env python3
"""A still and an orbit clip of a kit sheetview mesh in the hosted Neuroglancer, for its tool page.

    python -m kit sheetview build SEGMENT --volume CT --out SHEET ...            # a public scan off the prize lists
    python -m kit sheetview serve SHEET &                                       # serves SHEET/sheet.vtk on :8000
    python scripts/media/sheetview_media.py actions SHEET/state.json --out-dir PLAN
    python scripts/media/capture_web.py "$(cat PLAN/url.txt)" --webgl --out-dir FRAMES --actions PLAN/orbit.json \\
        --width 960 --height 540
    python scripts/media/capture_web.py "$(cat PLAN/url.txt)" --webgl --out-dir SHOTS --actions PLAN/stills.json \\
        --width 1600 --height 900
    python scripts/media/encode.py FRAMES --gif docs/assets/sheetview/sheetview-orbit.gif \\
        --meta scripts/media/captures/sheetview-orbit.meta.json
    python scripts/media/sheetview_media.py publish SHOTS --assets docs/assets/sheetview \\
        --meta scripts/media/captures/sheetview-orbit.meta.json

actions writes PLAN/url.txt (the Neuroglancer link to the served mesh, with the cross-section planes off) and the
capture steps: orbit.json swings the camera N degrees to each side of face on and back, one frame per step, by
changing the link's orientation in place (Neuroglancer follows its URL), and stills.json takes one shot face on and
one tilted. publish copies the two shots into the assets folder with sidecars, under the public media rule's guards
(common.write_guard and common.size_guard): CT of a public scan off the prize lists only, never model output, so a
3D ink mesh is shown privately and never published from here. Standard library only.
"""

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402

VIEWER = "https://neuroglancer-demo.appspot.com/#!"
SCRIPTS = ("common.py", "sheetview_media.py")
LOAD_MS = 30000      # the hosted viewer fetches and parses the mesh before the first frame
STEP_MS = 900


def _mul(a, b):
    x1, y1, z1, w1 = a
    x2, y2, z2, w2 = b
    return [w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2, w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2]


def _axis(axis, deg):
    h = math.radians(deg) / 2
    s = math.sin(h)
    return [axis[0] * s, axis[1] * s, axis[2] * s, math.cos(h)]


def turned(state, yaw, pitch=0.0):
    """The state's orientation turned yaw degrees about the screen's vertical and pitch about its horizontal."""
    q = state["projectionOrientation"]
    q = _mul(q, _axis((0, 1, 0), yaw))
    return [round(v, 6) for v in _mul(q, _axis((1, 0, 0), pitch))]


def _hash_js(state):
    return "location.hash = '#!' + " + json.dumps(quote(json.dumps(state, separators=(",", ":")), safe="")) + ";"


def plan(state, frames=48, swing=35.0, pitch=12.0):
    """(url, orbit actions, still actions) for capture_web.py."""
    state = dict(state, showSlices=False)
    url = VIEWER + quote(json.dumps(state, separators=(",", ":")), safe="")
    orbit = [{"wait": LOAD_MS}]
    for i in range(frames):
        t = i / frames
        s = dict(state, projectionOrientation=turned(state, swing * math.sin(2 * math.pi * t),
                                                     pitch * math.sin(math.pi * t) ** 2))
        orbit += [{"eval": _hash_js(s)}, {"wait": STEP_MS}, {"frame": 1}]
    tilt = dict(state, projectionOrientation=turned(state, swing, pitch))
    stills = [{"wait": LOAD_MS}, {"shot": "sheetview-face"}, {"eval": _hash_js(tilt)}, {"wait": 3 * STEP_MS},
              {"shot": "sheetview-tilt"}]
    return url, orbit, stills


def publish(shots, assets, meta_file):
    """Copy the two stills from SHOTS into ASSETS with sidecars, under the public media rule's guards."""
    base = json.loads(Path(meta_file).read_text(encoding="utf-8"))
    assets = Path(assets)
    assets.mkdir(parents=True, exist_ok=True)
    rel = assets.resolve().relative_to(common.ROOT).as_posix() if assets.resolve().is_relative_to(common.ROOT) \
        else str(assets)
    cmd = ("python scripts/media/sheetview_media.py actions SHEET/state.json --out-dir PLAN && python "
           "scripts/media/capture_web.py \"$(cat PLAN/url.txt)\" --webgl --out-dir SHOTS --actions PLAN/stills.json "
           f"--width 1600 --height 900 && python scripts/media/sheetview_media.py publish SHOTS --assets {rel} "
           f"--meta {Path(meta_file).as_posix()}")
    made = []
    for name, alt in (("sheetview-face", base["still_alts"]["face"]), ("sheetview-tilt", base["still_alts"]["tilt"])):
        meta = {k: base[k] for k in ("label", "license", "release_id", "data", "sources")}
        meta.update(alt=alt, caption=base["still_caption"])
        src, dest = Path(shots) / f"{name}.png", assets / f"{name}.png"
        common.write_guard(meta["label"], dest, meta)
        shutil.copyfile(src, dest)
        w, h = common.media_size(dest)
        common.size_guard(dest, w)
        out = common.output_record(dest, w, h, kind="still", format="png")
        common.write_sidecar(assets / f"{name}.json", meta, [out], command=cmd, scripts=SCRIPTS)
        made.append(str(dest))
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="action", required=True)
    a = sub.add_parser("actions", help="write the link and capture steps for a built sheet")
    a.add_argument("state", help="state.json from kit sheetview build")
    a.add_argument("--out-dir", required=True)
    a.add_argument("--frames", type=int, default=48)
    a.add_argument("--swing", type=float, default=35.0, help="degrees to each side of face on (default 35)")
    a.add_argument("--port", type=int, default=8000, help="where kit sheetview serve runs (default 8000)")
    p = sub.add_parser("publish", help="copy the stills into docs/assets/ with sidecars")
    p.add_argument("shots")
    p.add_argument("--assets", required=True)
    p.add_argument("--meta", required=True, help="the clip's meta JSON, with still_alts and still_caption")
    args = ap.parse_args(argv)
    if args.action == "publish":
        print(json.dumps(publish(args.shots, args.assets, args.meta), indent=1))
        return 0
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    for layer in state.get("layers", []):
        if layer.get("type") == "mesh":
            layer["source"]["url"] = f"vtk://http://127.0.0.1:{args.port}/sheet.vtk"
    url, orbit, stills = plan(state, args.frames, args.swing)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "url.txt").write_text(url + "\n", encoding="utf-8")
    (out / "orbit.json").write_text(json.dumps(orbit) + "\n", encoding="utf-8")
    (out / "stills.json").write_text(json.dumps(stills) + "\n", encoding="utf-8")
    print(json.dumps({"url_chars": len(url), "frames": args.frames, "out_dir": str(out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
