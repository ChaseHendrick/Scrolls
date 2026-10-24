#!/usr/bin/env python3
"""Replay a recorded Headless VC3D for agents session as a captioned page, for a GIF, an MP4 and stills.

    python scripts/media/vc3d_agent_session.py SESSION.json [MORE.json ...] --out-dir PAGE
    python scripts/media/capture_web.py PAGE/replay.html --out-dir FRAMES --actions PAGE/actions.json --width 1280 --height 800
    python scripts/media/capture_web.py PAGE/replay.html --out-dir SHOTS --actions PAGE/stills.json --width 1880 --height 1000
    python scripts/media/vc3d_agent_session.py --publish SHOTS --assets docs/assets/vc3d-agent
    python scripts/media/encode.py FRAMES --fps 10 --gif-fps 10 --gif OUT.gif --mp4 OUT.mp4 \\
        --meta scripts/media/captures/vc3d-agent-session.meta.json --made-with "..."

SESSION.json is a session transcript as the package's recorder writes it (examples/record_session.py in Headless VC3D
for agents 1.1.1): for each MCP tools/call its arguments, wall seconds, structured result and the images it returned,
saved beside the transcript under images/. Each scene below names a step of a transcript and says which of its values
to show; every number on the page is read from the transcript, never typed here. The page is a replay: it shows the
calls in their recorded order, each with its recorded duration, but does not wait those durations (the audit took
240.9 s). Paths are shortened for the page: the kit home's work/vc3d/ prefix and the bucket's host are left out.
--publish copies the two stills from SHOTS into ASSETS, each with its sidecar JSON, under the public media rule's
guards (common.write_guard and common.size_guard).

Only CT and mesh geometry are shown as pictures: a trace grown on a surface prediction and any ink map stay numbers.
The scan is PHerc0139, a public scan that is on none of the prize lists, so the GIF and stills are Real data renders
under the public media rule (docs/media/README.md). Standard library only.
"""

import argparse
import base64
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402

SCRIPTS = ("capture_web.py", "common.py", "vc3d_agent_session.py")
DATA = {"scan": "PHerc0139", "voxel_size": "9.362 um", "labels": "none", "credit": common.DATA_CREDIT,
        "segment": "w035 (20260317000000-w035_2026031718)", "volume": "20250728140407"}
SOURCES = ["https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/segments/20260317000000-w035_"
           "2026031718/mesh/20260317000000-on-20250728140407-9.362um.tifxyz/",
           "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-"
           "1.2m-113keV-masked.zarr/"]
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/"


def short(value, width=96):
    """A path or URL as the page shows it: bucket host and kit home prefix left out, long middles cut."""
    s = str(value)
    s = s.replace(BUCKET, "open-data:")
    s = re.sub(r"^.*?/work/vc3d/", "", s)
    s = re.sub(r"^/w/vc3d-agent-demo/[^/]+/", "", s)
    if len(s) > width:
        s = s[: width // 2 - 1] + "..." + s[-(width // 2 - 2):]
    return s


def shorten(v, width):
    if isinstance(v, str):
        return short(v, width)
    if isinstance(v, list):
        return [shorten(x, 40) for x in v]
    if isinstance(v, dict):
        return {k: shorten(x, 40) for k, x in v.items()}
    return v


def args_text(args):
    return " ".join(f"{k}={json.dumps(shorten(v, 70))}" for k, v in args.items())


def num(x, nd=2):
    return f"{x:,.{nd}f}" if isinstance(x, float) else f"{x:,}"


def lines_status(s):
    has = [k for k, v in s["has"].items() if v]
    return [f"tools found: {', '.join(has)}", f"display: {s['display']}, {s['cpu_limit']} CPUs",
            f"renderer: --flip-normals {'supported' if s['renderer'].get('flip_normals') else 'missing'}"]


def lines_selftest(s):
    ok = sum(1 for c in s["checks"] if c["pass"])
    return [f"verdict {s['verdict']}: {ok} of {len(s['checks'])} checks pass on synthetic volumes",
            *(f"[{'PASS' if c['pass'] else 'FAIL'}] {c['check']}" for c in s["checks"])]


def lines_fetch(s):
    st = s["stats"]
    return [f"downloaded {num(s['downloaded'])} bytes in {s['objects']} objects",
            f"grid {st['grid_rows_cols'][0]} x {st['grid_rows_cols'][1]}, {st['valid_fraction']:.1%} valid"]


def lines_orientation(s):
    n = s["normal"]
    return [f"+N points {n['vote']} on {n['outward_share']:.2%} of the voting area ({n['confidence']})",
            f"team layer order: {s['team_order']}", f"layout: {s['layout']}"]


def lines_audit(s, step):
    lv = s["footprint"]["levels"][0]
    return [f"verdict {s['verdict']} after {num(s['requests'])} requests",
            f"chunks under the surface {num(lv['chunks_on_surface'])}, in the margin {num(lv['chunks_in_margin'])}",
            f"present {num(lv['present'])}, missing {lv['missing_on_surface'] + lv['missing_in_margin']}"]


def lines_check(s, step):
    se = s["seating"]
    return [f"seating: {se['verdict']} (score {se['score']}, contrast {se['contrast']}, coverage {se['coverage']})",
            f"self-crossings: {'clean' if s['selfcross']['clean'] else 'found'}, "
            f"{s['selfcross']['transverse']} transverse"]


def lines_trace(s):
    t = s["surfaces"][0]
    return [f"vc_grow_seg_from_seed, {t['max_gen']} generations from a random seed: exit {s['exit']}",
            f"grid {t['grid_rows_cols'][0]} x {t['grid_rows_cols'][1]}, {t['area_cm2']:.2f} cm2 in {s['seconds']} s",
            "on the recto surface prediction (a model's map, so no picture here)"]


def lines_check_trace(s, step):
    se, th = s["seating"], s["seating"]["thresholds"]
    return [f"seating: {se['verdict']} (score {se['score']}, contrast {se['contrast']})",
            f"contrast between the unseated bar ({th['unseated_contrast']:g}) and the seated bar "
            f"({th['seated_contrast']:g}): not trusted as a surface"]


def lines_render(s):
    r = s["cache"]["relay"]
    return [f"layers {' x '.join(map(str, s['shape']))} in {s['seconds']} s, order {s['order']}",
            f"relay: {r['requests']} requests, {r['missing']} chunks not in the bucket, {r['false_404']} false 404s"]


def lines_preview(s):
    return [f"{s['view']}, contrast stretch {s['stretch'][0]:g} to {s['stretch'][1]:g}"]


def lines_merge(s, step):
    tail = [ln.strip() for ln in s.get("log_tail", "").splitlines() if "overlap shift" in ln or ln.strip().startswith("total")]
    return [f"exit {s['exit']}", *tail[:3]]


def lines_app(s):
    if s.get("status"):
        return [f"segments attached: {s['attached']} of {s['of']}, status {s['status']}"]
    return [f"screenshot {s.get('width')} x {s.get('height')} px"]


# (step id, file index, caption, lines(structured, step), picture: (step id, image index) or None, picture caption)
SCENES = [
    ("status", 0, "status: the agent finds villa's VC3D tools on a Linux CPU machine with no display",
     lambda s, st: lines_status(s), None, None),
    ("selftest", 0, "selftest: synthetic volumes measure this build's conventions before any real data",
     lambda s, st: lines_selftest(s), None, None),
    ("fetch_segment", 0, "fetch_segment: segment w035's mesh from the open-data bucket, in the 9.362 um scan's frame",
     lambda s, st: lines_fetch(s), ("preview_surface", 0), "w035's z coordinate (mesh geometry)"),
    ("orientation", 0, "orientation: which way the normal points, so the layers come out in the team's order",
     lambda s, st: lines_orientation(s), ("preview_surface", 0), "w035's z coordinate (mesh geometry)"),
    ("audit", 0, "audit: every chunk a render of w035 would read, checked in the bucket",
     lines_audit, ("preview_surface", 0), "w035's z coordinate (mesh geometry)"),
    ("check_surface", 0, "check_surface: is the mesh seated on a sheet, in five windows",
     lines_check, ("preview_surface", 0), "w035's z coordinate (mesh geometry)"),
    ("trace", 0, "trace: grow a new surface from a seed with VC3D's tracer",
     lambda s, st: lines_trace(s), None, None),
    ("check_trace", 0, "check_surface on the new trace: it does not pass, and the agent can tell",
     lines_check_trace, None, None),
    ("render", 0, "render: 28 layers under w035, streamed from the bucket",
     lambda s, st: lines_render(s), ("preview_layer", 0), "CT under w035: layer 14 of 28, team order"),
    ("preview_max", 0, "preview: the brightest value through the 28 layers of the render",
     lambda s, st: lines_preview(s), ("preview_max", 0), "CT under w035: maximum over 28 layers"),
    ("merge_surfaces", 1, "merge_surfaces: w035 cut by the recorder into two halves sharing 22 columns, merged back",
     lines_merge, None, None),
    ("app_open", 2, "app_open: the VC3D app itself, offscreen, with the scan open and w035 attached",
     lambda s, st: lines_app(s), ("app_screenshot2", 0), "VC3D with the 9.362 um scan open and w035 attached"),
]


def load(paths):
    out = []
    for p in paths:
        p = Path(p)
        t = json.loads(p.read_text(encoding="utf-8"))
        out.append({"dir": p.parent, "steps": {s["id"]: s for s in t["steps"]}, "tools": len(t.get("tools", [])),
                    "started": t.get("started_utc")})
    return out


def picture(sessions, idx, ref):
    """A data URI for the picture a scene names, or None when that session or step has none."""
    if ref is None or idx >= len(sessions):
        return None
    step = sessions[idx]["steps"].get(ref[0])
    if not step or len(step.get("images", [])) <= ref[1]:
        return None
    data = (sessions[idx]["dir"] / step["images"][ref[1]]).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode()


def build(sessions):
    scenes, used = [], []
    for sid, idx, caption, lines, ref, pic_caption in SCENES:
        if idx >= len(sessions) or sid not in sessions[idx]["steps"]:
            continue
        step = sessions[idx]["steps"][sid]
        if step.get("is_error") or not step.get("structured"):
            continue
        uri = picture(sessions, idx, ref)
        scenes.append({"tool": step["tool"], "args": args_text(step.get("arguments") or {}),
                       "seconds": step["seconds"], "lines": lines(step["structured"], step), "caption": caption,
                       "img": uri, "img_caption": pic_caption if uri else None})
        used.append(f"{idx}:{sid}")
    return scenes, used


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Headless VC3D for agents: a recorded session</title>
<style>
:root{--bg:#171A1C;--panel:#1f2326;--ink:#EEE7D9;--mute:#9a9385;--cu:#B77A54;--ok:#9fbf8f}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
font:15px/1.45 "DejaVu Sans Mono",ui-monospace,SFMono-Regular,Menlo,monospace}
#top{height:46px;display:flex;align-items:center;gap:14px;padding:0 22px;border-bottom:1px solid #2c3135;font-weight:700}
#top .tag{color:var(--bg);background:var(--cu);padding:2px 8px;font-size:13px}#top .sub{color:var(--mute);font-weight:400}
#main{position:absolute;top:46px;bottom:56px;left:0;right:0;display:flex}
#log{flex:1 1 auto;padding:18px 22px;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-end;gap:12px}
.card{background:var(--panel);border-left:3px solid #3a3f44;padding:10px 14px;opacity:.45}
.card.cur{opacity:1;border-left-color:var(--cu)}
.call{color:var(--ink);white-space:pre-wrap;word-break:break-all}.call b{color:var(--cu)}
.res{margin-top:6px;color:var(--ok);white-space:pre-wrap}.res .t{color:var(--mute)}
#pic{flex:0 0 46%;padding:18px 22px 18px 0;display:flex;flex-direction:column;align-items:center;justify-content:center}
#pic img{width:100%;max-height:calc(100% - 52px);object-fit:contain}
#pic .pc{margin-top:8px;color:var(--mute);font-size:13px;text-align:center}
#cap{position:absolute;left:0;right:0;bottom:0;height:56px;display:flex;align-items:center;gap:14px;padding:0 22px;
background:#0f1112;font-weight:700;font-size:16px}#cap b{color:var(--bg);background:var(--cu);padding:2px 8px}
#title{position:absolute;inset:46px 0 56px 0;display:flex;flex-direction:column;justify-content:center;padding:0 90px;gap:16px}
#title h1{margin:0;font-size:34px;color:var(--ink)}#title p{margin:0;color:var(--mute);font-size:17px;max-width:980px}
#title .cu{color:var(--cu)}
#stills{display:none;position:absolute;left:0;top:0;width:max-content;background:var(--bg);padding:24px 28px;gap:16px;
flex-direction:column}
#stills .row{display:flex;gap:22px;align-items:flex-start;justify-content:center}
#stills figure{margin:0;display:flex;flex-direction:column;align-items:center}
#stills img{border:1px solid #2c3135}#stills figcaption{margin-top:8px;color:var(--mute);font-size:14px}
#stills .foot{color:var(--mute);font-size:13px;text-align:center;width:0;min-width:100%}
</style></head><body>
<div id="top"><span class="tag">REAL SESSION</span><span>Headless VC3D for agents</span>
<span class="sub">MCP over stdio, PHerc0139 segment w035, Hugging Face CPU Job, 24 Oct 2026</span></div>
<div id="title"><h1>An agent drives VC3D with no display</h1>
<p>An MCP client called the server's tools on PHerc0139 segment w035, a public scan that is on none of the prize
lists, in three recorded sessions. Here are <span class="cu">__N__ of those calls</span>, every value read from the
transcripts. The replay skips the waits; each call shows how long it really took.</p>
<p>Pictures are CT and mesh geometry only: no ink map, no model output. Vesuvius Challenge open data, CC BY-NC 4.0.</p></div>
<div id="main" style="display:none"><div id="log"></div><div id="pic"><img id="img" alt=""><div class="pc" id="pc"></div></div></div>
<div id="cap"><b id="n">0/__N__</b><span id="ct">Real data render. Vesuvius Challenge open data, CC BY-NC 4.0.</span></div>
<div id="stills"></div>
<script>
const S = __SCENES__;
const esc = s => s.replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"})[c]);
function card(sc, t, cur) {
  const call = `<b>${esc(sc.tool)}</b> ${esc(sc.args)}`;
  const k = Math.round(sc.args.length * Math.min(1, t * 1.6));
  const shown = t >= 1 ? call : `<b>${esc(sc.tool)}</b> ${esc(sc.args.slice(0, k))}`;
  const res = t >= 1 ? `<div class="res"><span class="t">returned in ${sc.seconds} s</span>\\n${esc(sc.lines.join("\\n"))}</div>` : "";
  return `<div class="card${cur ? " cur" : ""}"><div class="call">${shown}</div>${res}</div>`;
}
function show(i, t) {
  document.getElementById("title").style.display = "none";
  document.getElementById("main").style.display = "flex";
  const log = document.getElementById("log");
  let h = "";
  for (let j = Math.max(0, i - 2); j < i; j++) h += card(S[j], 1, false);
  log.innerHTML = h + card(S[i], t, true);
  const sc = S[i], img = document.getElementById("img");
  if (sc.img) { img.src = sc.img; img.style.display = ""; document.getElementById("pc").textContent = sc.img_caption; }
  else { img.style.display = "none"; document.getElementById("pc").textContent = "numbers only"; }
  document.getElementById("n").textContent = `${i + 1}/${S.length}`;
  document.getElementById("ct").textContent = sc.caption;
}
function stills(which, h, foot) {
  const st = document.getElementById("stills"); st.style.display = "flex";
  const pick = S.filter(s => s.img && which.includes(s.img_caption));
  const seen = new Set(), figs = [];
  for (const s of pick) { if (seen.has(s.img_caption)) continue; seen.add(s.img_caption);
    figs.push(`<figure><img src="${s.img}"${h ? ` style="height:${h}px"` : ""}><figcaption>${esc(s.img_caption)}` +
      `</figcaption></figure>`); }
  st.innerHTML = `<div class="row">${figs.join("")}</div><div class="foot">${esc(foot)}</div>`;
}
</script></body></html>
"""


def actions(n):
    """capture_web.py steps: the title, then each call typed in eight frames and held while it is read."""
    acts = [{"wait": 300}, {"frame": 1}, {"hold": 59}]
    for i in range(n):
        acts.append({"step": {"js": f"show({i}, {{t}})", "n": 8}})
        acts.append({"hold": 34})
    acts.append({"hold": 26})
    return acts


# (name, picture captions, picture height in px or None for its own size, footer and caption, alt text)
STILLS = [
    ("vc3d-agent-render", ["w035's z coordinate (mesh geometry)", "CT under w035: layer 14 of 28, team order",
                           "CT under w035: maximum over 28 layers"], 560,
     "Real data render: PHerc0139 segment w035 at 9.362 um, from the preview and render tools of a recorded "
     "session. CT and mesh geometry, no labels, no ink. Vesuvius Challenge open data, CC BY-NC 4.0.",
     "Three panels from a recorded agent session on PHerc0139 segment w035: the segment's z coordinate as a gray "
     "ramp inside its outline; the middle layer of a 28-layer render of the CT under a 640 pixel window of the "
     "segment, a mottled texture of light fibers and dark patches; and the maximum over those 28 layers, a mesh of "
     "crossing fibers with a few bright specks."),
    ("vc3d-agent-app", ["VC3D with the 9.362 um scan open and w035 attached"], None,
     "Real data render: VC3D running offscreen, captured over its agent bridge (app_screenshot). PHerc0139 at "
     "9.362 um, w035 in the left view. CT, no labels, no ink. Vesuvius Challenge open data, CC BY-NC 4.0.",
     "A screenshot of the VC3D app taken over its agent bridge with no display: on the left the CT along segment "
     "w035 at full resolution, on the right the scroll's cross-section from above and a vertical slice through it "
     "at low resolution, with VC3D's own markers and scale bars."),
]


def publish(shots, assets):
    """Copy each still from SHOTS into ASSETS with its sidecar, under the public media rule's guards."""
    assets = Path(assets)
    assets.mkdir(parents=True, exist_ok=True)
    rel = assets.resolve().relative_to(common.ROOT).as_posix() if assets.resolve().is_relative_to(common.ROOT) \
        else str(assets)
    cmd = ("python scripts/media/vc3d_agent_session.py SESSION1/transcript.json SESSION2/transcript.json "
           "SESSION4/transcript.json --out-dir PAGE && python scripts/media/capture_web.py PAGE/replay.html "
           "--out-dir SHOTS --actions PAGE/stills.json --width 1880 --height 1000 && "
           f"python scripts/media/vc3d_agent_session.py --publish SHOTS --assets {rel}")
    made = []
    for name, _which, _h, caption, alt in STILLS:
        src, dest = Path(shots) / f"{name}.png", assets / f"{name}.png"
        meta = {"label": "Real data render", "license": common.DATA_LICENSE, "release_id": "vc3d-agent",
                "data": DATA, "sources": SOURCES, "alt": alt, "caption": caption}
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
    ap.add_argument("sessions", nargs="*", help="session transcripts (transcript.json), main session first")
    ap.add_argument("--out-dir", help="scratch folder for replay.html, actions.json and stills.json")
    ap.add_argument("--publish", metavar="SHOTS", help="copy the stills captured into SHOTS to --assets, with sidecars")
    ap.add_argument("--assets", help="the docs/assets/ folder for --publish")
    a = ap.parse_args(argv)
    if a.publish:
        if not a.assets:
            ap.error("--publish needs --assets")
        print(json.dumps(publish(a.publish, a.assets), indent=1))
        return 0
    if not a.sessions or not a.out_dir:
        ap.error("give session transcripts and --out-dir, or --publish SHOTS --assets DIR")
    sessions = load(a.sessions)
    scenes, used = build(sessions)
    if not scenes:
        print("vc3d_agent_session: no scene found in the transcripts", file=sys.stderr)
        return 2
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    page = PAGE.replace("__SCENES__", json.dumps(scenes)).replace("__N__", str(len(scenes)))
    (out / "replay.html").write_text(page, encoding="utf-8")
    (out / "actions.json").write_text(json.dumps(actions(len(scenes)), indent=1) + "\n", encoding="utf-8")
    shots = []
    for name, which, height, foot, _alt in STILLS:
        call = f"stills({json.dumps(which)}, {json.dumps(height)}, {json.dumps(foot)})"
        shots += [{"eval": f"() => {call}"}, {"wait": 300}, {"clip": "#stills"}, {"shot": name}]
    (out / "stills.json").write_text(json.dumps(shots, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"scenes": len(scenes), "steps": used, "page": str(out / "replay.html")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
