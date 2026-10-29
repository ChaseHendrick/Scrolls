#!/usr/bin/env python3
"""windlabel-box's frozen winding tests as one SVG chart (two panels), from published numbers, with a sidecar JSON.

Reads DATA.json (docs/media/windlabel-box-heldout-data.json: per frozen test the split chains' step accuracy, its
one-sided 95 % lower bound and the verdict; per 29 October comparison windlabel-box's and the community tool's
accuracy) and writes an SVG drawing with no raster in it, in the categorical palette of
docs/media/greek-restoration-by-gap-length.svg, dark mode through prefers-color-scheme. Standard library only.

  python scripts/media/windings_chart.py docs/media/windlabel-box-heldout-data.json docs/media/windlabel-box-heldout.svg
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402
from barrier_chart import STYLE, esc  # noqa: E402

SCRIPTS = ("common.py", "barrier_chart.py", "windings_chart.py")
W, H = 960, 520
LO, HI = 0.88, 1.0
TICKS = (0.88, 0.90, 0.92, 0.94, 0.96, 0.98, 1.0)
EXTRA = (".ring{fill:#fcfcfb;stroke:#2a78d6;stroke-width:2}.wh{stroke:#2a78d6;stroke-width:2}"
         ".link{stroke:#9c9a94;stroke-width:2}.barl{stroke:#52514e;stroke-width:1.5;stroke-dasharray:5 4}"
         "@media (prefers-color-scheme:dark){.ring{fill:#1a1a19;stroke:#3987e5}.wh{stroke:#3987e5}"
         ".link{stroke:#6b6a64}.barl{stroke:#c3c2b7}}")


def left(out, data, x0, top, base, pw):
    out.append(f'<text class="t1" x="{x0}" y="{top - 22}" font-size="15" font-weight="600">Six frozen tests, three scrolls</text>')
    out.append(f'<text class="t2" x="{x0}" y="{top - 6}" font-size="12">step accuracy (dot) and its lower bound (whisker)</text>')
    sy = (base - top) / (HI - LO)

    def y(v):
        return base - (v - LO) * sy
    for t in TICKS:
        out.append(f'<line class="grid" x1="{x0 + 40}" x2="{x0 + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="t2" x="{x0 + 34}" y="{y(t) + 4:.1f}" font-size="11" text-anchor="end">{t:.2f}</text>')
    yb = y(data["bar"])
    out.append(f'<line class="barl" x1="{x0 + 40}" x2="{x0 + pw}" y1="{yb:.1f}" y2="{yb:.1f}"/>')
    out.append(f'<text class="t2" x="{x0 + pw}" y="{yb + 15:.1f}" font-size="11" text-anchor="end">'
               f'bar: lower bound above {data["bar"]:.2f}</text>')
    tests = data["tests"]
    gw = (pw - 48) / len(tests)
    for i, t in enumerate(tests):
        cx = x0 + 48 + gw * (i + 0.5)
        tip = (f'{t["label"]}, {t["date"]}, {t["sub"]}: {t["acc"]:.4f} of {t["steps"]:,} judged steps, lower bound {t["lb"]:.4f}, '
               f'{t["verdict"]}' + (f' ({t["why"]})' if t.get("why") else ""))
        out.append(f'<line class="wh" x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(t["acc"]):.1f}" y2="{y(t["lb"]):.1f}"/>')
        out.append(f'<line class="wh" x1="{cx - 6:.1f}" x2="{cx + 6:.1f}" y1="{y(t["lb"]):.1f}" y2="{y(t["lb"]):.1f}"/>')
        cls = "s0" if t["verdict"] == "PASS" else "ring"
        out.append(f'<circle class="{cls}" cx="{cx:.1f}" cy="{y(t["acc"]):.1f}" r="6"><title>{esc(tip)}</title></circle>')
        out.append(f'<text class="t1" x="{cx:.1f}" y="{y(t["acc"]) - 12:.1f}" font-size="11" text-anchor="middle">'
                   f'{t["acc"]:g}</text>')
        if t["verdict"] != "PASS":
            out.append(f'<text class="t2" x="{cx:.1f}" y="{y(t["lb"]) + 16:.1f}" font-size="10" text-anchor="middle">'
                       f'{esc(t["verdict"])}: {esc(t["why"])}</text>')
        out.append(f'<text class="t1" x="{cx:.1f}" y="{base + 18}" font-size="11" text-anchor="middle">{esc(t["label"])}</text>')
        out.append(f'<text class="t2" x="{cx:.1f}" y="{base + 32}" font-size="10" text-anchor="middle">{esc(t["date"])}</text>')
        out.append(f'<text class="t2" x="{cx:.1f}" y="{base + 45}" font-size="10" text-anchor="middle">{esc(t["sub"])}</text>')


def right(out, data, x0, top, base, pw):
    out.append(f'<text class="t1" x="{x0}" y="{top - 22}" font-size="15" font-weight="600">'
               'Against community tools, same boxes (29 Oct)</text>')
    out.append(f'<text class="t2" x="{x0}" y="{top - 6}" font-size="12">step accuracy on the items both judged</text>')
    lab = 104
    ax0, ax1 = x0 + lab, x0 + pw
    sx = (ax1 - ax0) / (HI - LO)

    def x(v):
        return ax0 + (v - LO) * sx
    for t in (0.88, 0.92, 0.96, 1.0):
        out.append(f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top}" y2="{base}"/>')
        out.append(f'<text class="t2" x="{x(t):.1f}" y="{base + 16}" font-size="11" text-anchor="middle">{t:.2f}</text>')
    arms = {a["id"]: a for a in data["arms"]}
    pairs = data["pairs"]
    rh = (base - top - 12) / len(pairs)
    for i, p in enumerate(pairs):
        cy = top + 12 + rh * (i + 0.5)
        arm = arms[p["arm"]]
        first = i == 0 or pairs[i - 1]["label"] != p["label"]
        if first:
            out.append(f'<text class="t1" x="{x0}" y="{cy - rh / 2 + 10:.1f}" font-size="12" font-weight="600">{esc(p["label"])}</text>')
        short = "E1" if p["arm"] == "E1" else "winding-phase"
        out.append(f'<text class="t2" x="{ax0 - 8}" y="{cy + 4:.1f}" font-size="11" text-anchor="end">vs {short}</text>')
        if p.get("comparable", True) is False:
            out.append(f'<text class="t2" x="{ax0 + 6}" y="{cy + 4:.1f}" font-size="11" font-style="italic">'
                       f'{esc(p["why"])}</text>')
            continue
        tip = (f'{p["label"]}: windlabel-box {p["ours"]:.3f} against {arm["legend"]} {p["other"]:.3f}, '
               f'lower bound of the lead +{p["lead_lb"]:.3f}')
        out.append(f'<line class="link" x1="{x(p["other"]):.1f}" x2="{x(p["ours"]):.1f}" y1="{cy:.1f}" y2="{cy:.1f}"/>')
        out.append(f'<circle class="{arm["cls"]}" cx="{x(p["other"]):.1f}" cy="{cy:.1f}" r="6"><title>{esc(tip)}</title></circle>')
        out.append(f'<circle class="s0" cx="{x(p["ours"]):.1f}" cy="{cy:.1f}" r="6"><title>{esc(tip)}</title></circle>')
        out.append(f'<text class="t2" x="{x(p["other"]) - 10:.1f}" y="{cy + 4:.1f}" font-size="10" text-anchor="end">'
                   f'{p["other"]:g}</text>')
        out.append(f'<text class="t1" x="{x(p["ours"]) + 10:.1f}" y="{cy + 4:.1f}" font-size="10">{p["ours"]:g}</text>')


def render(data):
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
           'aria-labelledby="t d">', f'<title id="t">{esc(data["title"])}</title>', f'<desc id="d">{esc(data["desc"])}</desc>',
           f"<style>{STYLE}{EXTRA}</style>", f'<rect class="bg" width="{W}" height="{H}" rx="8"/>',
           f'<text class="t1" x="24" y="34" font-size="18" font-weight="600">{esc(data["title"])}</text>',
           f'<text class="t2" x="24" y="56" font-size="13">{esc(data["subtitle"])}</text>']
    lx = 24
    for arm in data["arms"]:
        out.append(f'<circle class="{arm["cls"]}" cx="{lx + 6}" cy="78" r="6"/>')
        out.append(f'<text class="t2" x="{lx + 17}" y="82" font-size="12">{esc(arm["legend"])}</text>')
        lx += 30 + int(6.4 * len(arm["legend"]))
    out.append(f'<circle class="ring" cx="{lx + 6}" cy="78" r="5"/>')
    out.append(f'<text class="t2" x="{lx + 17}" y="82" font-size="12">failed its own bar</text>')
    left(out, data, 24, 140, 420, 440)
    right(out, data, 500, 140, 420, 436)
    out.append(f'<text class="t2" x="24" y="{H - 14}" font-size="11">{esc(data["foot"])}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data", help="the chart's numbers (JSON)")
    ap.add_argument("out", help="the SVG to write; its sidecar goes beside it")
    a = ap.parse_args(argv)
    src = Path(a.data)
    data = json.loads(src.read_text(encoding="utf-8"))
    svg = render(data)
    for ch in common.LONG_DASHES:
        if ch in svg:
            sys.exit("long dash in the chart text")
    if common.svg_embeds_raster(svg):
        sys.exit("the chart embeds a raster picture")
    out = Path(a.out)
    out.write_text(svg, encoding="utf-8")
    rec = {"schema": common.SCHEMA, "name": out.stem, "label": "Chart", "claim_label": data["claim_label"],
           "alt": data["alt"], "caption": data["caption"], "license": "Apache-2.0", "release_id": None,
           "data": {"source": str(src), "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                    "credit": data["credit"]},
           "outputs": [{"file": out.name, "bytes": out.stat().st_size, "sha256": common.sha256(out), "width": W,
                        "height": H, "kind": "svg"}],
           "made": __import__("datetime").date.today().isoformat(),
           "command": f"python scripts/media/windings_chart.py {a.data} {a.out}",
           "tool": {"scripts": ["scripts/media/" + s for s in SCRIPTS], "scripts_sha256": common.scripts_digest(SCRIPTS),
                    "base_commit": common.git_commit()},
           "colors": "categorical slots 1 to 3 of the palette of greek-restoration-by-gap-length.svg (blue, orange, "
                     "green; blue for windlabel-box); dark mode through prefers-color-scheme"}
    out.with_suffix(".json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(out, out.stat().st_size)


if __name__ == "__main__":
    main()
