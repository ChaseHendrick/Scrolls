#!/usr/bin/env python3
"""Replay a kit scroll2ink run as a terminal page, for a GIF, an MP4 and stills.

    python scripts/media/scroll2ink_replay.py RUN_DIR --out-dir PAGE [--ct-window 384]
    python scripts/media/capture_web.py PAGE/replay.html --out-dir FRAMES --actions PAGE/actions.json --width 1280 --height 720
    python scripts/media/capture_web.py PAGE/replay.html --out-dir SHOTS --actions PAGE/stills.json --width 1280 --height 720
    python scripts/media/scroll2ink_replay.py --publish SHOTS --assets docs/assets/scroll2ink \\
        --meta scripts/media/captures/scroll2ink-run.meta.json
    python scripts/media/encode.py FRAMES --fps 15 --gif-fps 15 --gif OUT.gif --mp4 OUT.mp4 \\
        --meta scripts/media/captures/scroll2ink-run.meta.json --made-with "..."

RUN_DIR is a scroll2ink run folder as the HF Jobs runner leaves it: state.json and settings.json, plus the runner's
timed logs beside it (scroll2ink-vc.log and scroll2ink-ink.log, each line prefixed with the seconds since that part
started). Every line, time and number on the page is read from those files, never typed here. The page shows the
lines in their recorded order, each with its recorded time, but does not wait those times (the trace took minutes).

The only picture is CT: a slice of the scan through the seed point, read straight from the open-data bucket (the
volume's raw level-0 chunks). The surface the tracer grew from the surface prediction and every ink map stay numbers:
they are model output, which the public media rule keeps out of public Scrolls (docs/media/README.md). The run must be
on a public scan that is on none of the prize lists (PHerc0139 here), so the slice is a Real data render. Standard
library only, except numpy for the slice.
"""

import argparse
import base64
import io
import json
import re
import shutil
import struct
import sys
import urllib.request
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402

KEEP = re.compile(r"^\s*([\d.]+) (\[\d+/\d+\] .*|vc_grow_seg_from_seed: .*|run folder .*|surface .*|stopped .*|"
                  r"An ink map .*|scroll2ink: .*)$")


def timed_lines(path):
    """(seconds, text) for the lines a viewer should see, from one part's timed log (pure apart from the read)."""
    rows = []
    for line in Path(path).read_text(errors="replace").splitlines():
        m = KEEP.match(line)
        if m:
            text = re.sub(r"; \d+ GridStore cache warnings left out", "", m.group(2)).replace("/tmp/s2i/", "")
            # runs before 25 Oct printed the ink stage's device record whole; show the device as later runs do
            text = re.sub(r"on \{'asked': '(\w+)', 'reported': (?:None|'(\w+)')\}", lambda d: "on " + (d.group(2) or
                                                                                                    d.group(1)), text)
            rows.append((float(m.group(1)), text))
    return rows


def thin_progress(rows, keep_every=6):
    """Keep every keep_every-th tracer progress line (and the last), so a long trace replays in a few seconds."""
    out, prog = [], [i for i, r in enumerate(rows) if r[1].startswith("vc_grow_seg_from_seed:")]
    keep = set(prog[::keep_every]) | ({prog[-1]} if prog else set())
    for i, r in enumerate(rows):
        if i in keep or i not in prog:
            out.append(r)
    return out


def png_gray(arr):
    """A grayscale PNG of a 2-D uint8 numpy array (standard library zlib)."""
    h, w = arr.shape
    raw = b"".join(b"\x00" + arr[i].tobytes() for i in range(h))

    def chunk(kind, data):
        c = kind + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ct_slice(volume_url, x, y, z, half):
    """The level-0 z slice through (x, y, z), 2*half wide, from an uncompressed zarr v2 volume; contrast stretched
    from its 1st to 99th percentile. Returns (uint8 array, window [x0, y0, x1, y1])."""
    import numpy as np
    base = volume_url.rstrip("/") + "/0/"
    meta = json.loads(urllib.request.urlopen(base + ".zarray", timeout=60).read())
    if meta.get("compressor") is not None or meta["dtype"] != "|u1":
        raise SystemExit(f"{base}: expected an uncompressed uint8 zarr, got {meta.get('compressor')} {meta['dtype']}")
    cz, cy, cx = meta["chunks"]
    sep = meta.get("dimension_separator", ".")
    x0, y0, x1, y1 = x - half, y - half, x + half, y + half
    out = np.zeros((y1 - y0, x1 - x0), np.uint8)
    for ky in range(y0 // cy, (y1 - 1) // cy + 1):
        for kx in range(x0 // cx, (x1 - 1) // cx + 1):
            key = sep.join(str(k) for k in (z // cz, ky, kx))
            try:
                data = urllib.request.urlopen(base + key, timeout=60).read()
            except urllib.error.HTTPError:
                continue
            block = np.frombuffer(data, np.uint8).reshape(cz, cy, cx)[z % cz]
            ya, yb = max(y0, ky * cy), min(y1, (ky + 1) * cy)
            xa, xb = max(x0, kx * cx), min(x1, (kx + 1) * cx)
            out[ya - y0:yb - y0, xa - x0:xb - x0] = block[ya - ky * cy:yb - ky * cy, xa - kx * cx:xb - kx * cx]
    lo, hi = np.percentile(out, (1, 99))
    img = np.clip((out.astype(float) - lo) / max(1.0, hi - lo) * 255, 0, 255).astype(np.uint8)
    return img, [x0, y0, x1, y1]


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>scroll2ink replay</title><style>
:root{--bg:#14110e;--panel:#1d1915;--ink:#efe6d6;--dim:#a8998a;--accent:#d49a5a;--ok:#9cc38a;--line:#3a322a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 ui-monospace,Menlo,
"DejaVu Sans Mono",monospace;width:1280px;height:720px;overflow:hidden}
.wrap{display:grid;grid-template-columns:820px 1fr;gap:18px;padding:22px;height:100%}
.term{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;overflow:hidden;
display:flex;flex-direction:column}
.bar{display:flex;gap:7px;margin-bottom:12px}.bar i{width:11px;height:11px;border-radius:50%;background:var(--line)}
.cmd{color:var(--accent);white-space:pre-wrap;margin-bottom:10px}.cmd b{color:var(--dim);font-weight:400}
#log{flex:1;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-end}
.l{white-space:pre-wrap;word-break:break-word}.l .t{color:var(--dim);display:inline-block;width:96px}
.l.done{color:var(--ok)}.l.prog{color:var(--dim)}.l.fail{color:#e08070}
.side{display:flex;flex-direction:column;gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.card h2{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--dim);margin:0 0 8px;font-weight:600}
.ct{position:relative;width:100%;aspect-ratio:1}.ct img{width:100%;height:100%;display:block;image-rendering:auto;
border-radius:6px}.ct .dot{position:absolute;left:50%;top:50%;width:16px;height:16px;margin:-8px;border:2px solid
var(--accent);border-radius:50%;box-shadow:0 0 0 3px rgba(212,154,90,.25)}
.cap{color:var(--dim);font-size:12px;margin-top:8px;line-height:1.35}
.st{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}.st span{font-size:12px;text-align:center;padding:4px 0;
border-radius:5px;background:#26201b;color:var(--dim)}.st span.on{background:#3b2f22;color:var(--accent)}
.st span.ok{background:#25331f;color:var(--ok)}.st span.skip{background:#26201b;color:#7d7064;text-decoration:line-through}
</style></head><body><div class="wrap"><div class="term"><div class="bar"><i></i><i></i><i></i></div>
<div class="cmd"><b>$</b> __CMD__</div><div id="log"></div></div>
<div class="side"><div class="card"><h2>Seed on the CT</h2><div class="ct"><img src="data:image/png;base64,__CT__"
alt="__ALT__"><div class="dot"></div></div><div class="cap">__CAP__</div></div>
<div class="card"><h2>Stages</h2><div class="st" id="st"></div></div></div></div>
<script>
const ROWS = __ROWS__, STAGES = __STAGES__, STATUS = __STATUS__;
const log = document.getElementById("log"), st = document.getElementById("st");
STAGES.forEach(s => { const e = document.createElement("span"); e.id = "s-" + s; e.textContent = s; st.appendChild(e); });
function fmt(s) { const m = Math.floor(s / 60), r = Math.round(s - 60 * m); return m ? m + "m" + String(r).padStart(2, "0")
  + "s" : r + "s"; }
function seek(t) {
  const n = Math.round(t * ROWS.length); log.innerHTML = "";
  let prog = null;
  for (const [i, r] of ROWS.slice(0, n).entries()) {
    const isProg = r[2].startsWith("vc_grow_seg_from_seed:");
    if (isProg && prog) { prog.querySelector(".x").textContent = r[2]; prog.querySelector(".t").textContent = r[0] + " " + fmt(r[1]);
      continue; }
    const d = document.createElement("div");
    d.className = "l" + (/ (done|skipped) /.test(r[2]) ? " done" : "") + (isProg ? " prog" : "") +
      (/FAILED|scroll2ink:/.test(r[2]) ? " fail" : "");
    d.innerHTML = '<span class="t"></span><span class="x"></span>';
    d.querySelector(".t").textContent = r[0] + " " + fmt(r[1]); d.querySelector(".x").textContent = r[2];
    log.appendChild(d); prog = isProg ? d : null;
  }
  for (const s of STAGES) {
    const e = document.getElementById("s-" + s); e.className = "";
    const hit = ROWS.slice(0, n).filter(r => r[2].includes("] " + s.padEnd(8)));
    if (!hit.length) continue;
    const last = hit[hit.length - 1][2];
    e.className = / done /.test(last) ? "ok" : / skipped /.test(last) ? "skip" : "on";
  }
}
seek(0);
</script></body></html>"""


def build(run_dir, out_dir, half):
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    root = run_dir.parent if (run_dir / "state.json").is_file() and not (run_dir / "scroll2ink-vc.log").is_file() \
        else run_dir
    state_dir = run_dir if (run_dir / "state.json").is_file() else run_dir / "run"
    settings = json.loads((state_dir / "settings.json").read_text())
    state = json.loads((state_dir / "state.json").read_text())["stages"]
    rows = []
    for part in ("vc", "ink"):
        log = root / f"scroll2ink-{part}.log"
        if log.is_file():
            rows += [(part.upper(), s, t) for s, t in thin_progress(timed_lines(log))]
    inp = state["inputs"]
    x, y, z = (int(round(v)) for v in settings["seed"])
    img, win = ct_slice(inp["ct"], x, y, z, half)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ct.png").write_bytes(png_gray(img))
    cmd = (f"python -m kit scroll2ink run --sample {settings['sample']} --seed {x} {y} {z} "
           f"--volume {inp['volume']} --device cuda")
    cap = (f"{settings['sample']}, volume {inp['volume']} ({inp['voxel_um']} um), CT slice z {z}, x {win[0]} to "
           f"{win[2]}, y {win[1]} to {win[3]}; the ring is the seed. {common.DATA_CREDIT}.")
    alt = f"A CT slice of {settings['sample']} with a ring marking the seed point at x {x}, y {y}, z {z}."
    page = (PAGE.replace("__CMD__", cmd).replace("__CT__", base64.b64encode(png_gray(img)).decode())
            .replace("__ALT__", alt).replace("__CAP__", cap).replace("__ROWS__", json.dumps(rows))
            .replace("__STAGES__", json.dumps(["inputs", "seed", "trace", "check", "extend", "flatten", "render",
                                               "ink", "preview", "report"]))
            .replace("__STATUS__", json.dumps({k: v.get("status") for k, v in state.items()})))
    (out_dir / "replay.html").write_text(page)
    n = max(90, 6 * len(rows))
    (out_dir / "actions.json").write_text(json.dumps([{"wait": 300}, {"step": {"js": "seek({t})", "n": n}},
                                                      {"hold": 45}]) + "\n")
    (out_dir / "stills.json").write_text(json.dumps([{"wait": 300}, {"eval": "seek(1)"}, {"wait": 200},
                                                     {"shot": "scroll2ink-end"}, {"eval": "seek(0.35)"},
                                                     {"wait": 200}, {"shot": "scroll2ink-trace"}]) + "\n")
    facts = {"rows": len(rows), "window": win, "seed": [x, y, z], "volume": inp["ct"], "frames": n + 45,
             "data": {"scan": settings["sample"], "voxel_size": f"{inp['voxel_um']} um", "labels": "none",
                      "credit": common.DATA_CREDIT, "volume": inp["volume"]}, "alt": alt, "caption": cap}
    (out_dir / "facts.json").write_text(json.dumps(facts, indent=1) + "\n")
    print(f"wrote {out_dir / 'replay.html'}: {len(rows)} lines, CT window {win}")
    return 0


STILLS = (("scroll2ink-end", "the run's last lines: the ink step on a GPU with its reverse control, the previews and the "
                              "report, with every stage lit"),
          ("scroll2ink-trace", "the run part way: the trace grown and checked, the extension under way"))


def publish(shots, assets, meta_path):
    """Copy the stills captured into SHOTS to ASSETS, each with its sidecar, under the public media rule's guards."""
    assets, meta = Path(assets), json.loads(Path(meta_path).read_text())
    assets.mkdir(parents=True, exist_ok=True)
    rel = assets.resolve().relative_to(common.ROOT).as_posix() if assets.resolve().is_relative_to(common.ROOT) \
        else str(assets)
    cmd = ("python scripts/media/scroll2ink_replay.py RUN_DIR --out-dir PAGE && python scripts/media/capture_web.py "
           "PAGE/replay.html --out-dir SHOTS --actions PAGE/stills.json --width 1280 --height 720 && python "
           f"scripts/media/scroll2ink_replay.py --publish SHOTS --assets {rel} --meta {meta_path}")
    for name, what in STILLS:
        src, dest = Path(shots) / f"{name}.png", assets / f"{name}.png"
        m = {**meta, "alt": f"A still of the kit scroll2ink replay, {what}; on the right a CT slice of the scan "
                            "through the seed point with a ring on the seed.",
             "caption": meta["caption"].replace("a replay of", f"a still of the replay of", 1)}
        common.write_guard(m["label"], dest, m)
        shutil.copyfile(src, dest)
        w, h = common.media_size(dest)
        common.size_guard(dest, w)
        out = common.output_record(dest, w, h, kind="still", format="png")
        common.write_sidecar(assets / f"{name}.json", m, [out], command=cmd,
                             scripts=["scroll2ink_replay.py", "capture_web.py", "common.py"])
        print(dest)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--out-dir")
    ap.add_argument("--ct-window", type=int, default=384, help="half width of the CT slice in voxels (default 384)")
    ap.add_argument("--publish", metavar="SHOTS", help="copy the stills captured into SHOTS to --assets, with sidecars")
    ap.add_argument("--assets", help="where --publish puts the stills (under docs/assets/)")
    ap.add_argument("--meta", help="the clip's meta JSON (label, data, sources, caption) for the stills' sidecars")
    a = ap.parse_args(argv)
    if a.publish:
        if not (a.assets and a.meta):
            ap.error("--publish needs --assets and --meta")
        return publish(a.publish, a.assets, a.meta)
    if not (a.run_dir and a.out_dir):
        ap.error("give RUN_DIR and --out-dir (or --publish SHOTS --assets DIR --meta META)")
    return build(a.run_dir, a.out_dir, a.ct_window)


if __name__ == "__main__":
    sys.exit(main())
