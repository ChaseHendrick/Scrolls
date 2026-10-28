#!/usr/bin/env python3
"""The contact barrier's held-out comparison on PHerc0139 as one SVG chart (two small multiples), from published
numbers, with a sidecar JSON.

Reads DATA.json (docs/media/contact-barrier-a15-data.json: per winding and repeat, the area each arm covered on its
own winding and the area it put on other windings, in cm2, and which windings passed) and writes an SVG drawing with
no raster in it, in the categorical palette of docs/media/greek-restoration-by-gap-length.svg, dark mode through
prefers-color-scheme. Standard library only.

  python scripts/media/barrier_chart.py docs/media/contact-barrier-a15-data.json docs/media/contact-barrier-a15.svg
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402

SCRIPTS = ("common.py", "barrier_chart.py")
W, H = 960, 520
STYLE = ("svg{font-family:system-ui,-apple-system,'Segoe UI',sans-serif}.bg{fill:#fcfcfb}.t1{fill:#0b0b0b}"
         ".t2{fill:#52514e}.grid{stroke:#e4e3df}.axis{stroke:#9c9a94}.s0{fill:#2a78d6}.s1{fill:#eb6834}"
         ".s2{fill:#1baf7a}.dot{fill:#0b0b0b;stroke:#fcfcfb;stroke-width:2}"
         "@media (prefers-color-scheme:dark){.bg{fill:#1a1a19}.t1{fill:#f0efec}.t2{fill:#c3c2b7}"
         ".grid{stroke:#383835}.axis{stroke:#6b6a64}.s0{fill:#3987e5}.s1{fill:#d95926}.s2{fill:#199e70}"
         ".dot{fill:#f0efec;stroke:#1a1a19}}")


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def bar(x, y0, h, w, cls, tip):
    r = min(4.0, w / 2, h) if h > 0 else 0
    if h <= 0.5:
        return f'<rect class="{cls}" x="{x:.1f}" y="{y0 - 1.5:.1f}" width="{w:.1f}" height="1.5"><title>{esc(tip)}</title></rect>'
    return (f'<path class="{cls}" d="M{x:.1f} {y0:.1f}v{-(h - r):.1f}a{r} {r} 0 0 1 {r} {-r}h{w - 2 * r:.1f}'
            f'a{r} {r} 0 0 1 {r} {r}v{h - r:.1f}z"><title>{esc(tip)}</title></path>')


def panel(out, data, key, x0, title, ymax, ticks, unit_note):
    arms = data["arms"]
    wind = data["windings"]
    top, base = 150, 440
    pw = 420
    out.append(f'<text class="t1" x="{x0}" y="{top - 22}" font-size="15" font-weight="600">{esc(title)}</text>')
    out.append(f'<text class="t2" x="{x0}" y="{top - 6}" font-size="12">{esc(unit_note)}</text>')
    sy = (base - top - 10) / ymax
    for t in ticks:
        y = base - t * sy
        cls = "axis" if t == 0 else "grid"
        out.append(f'<line class="{cls}" x1="{x0 + 36}" x2="{x0 + pw}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="t2" x="{x0 + 30}" y="{y + 4:.1f}" font-size="11" text-anchor="end">{t:g}</text>')
    gw = (pw - 44) / len(wind)
    bw = (gw - 16) / len(arms)
    for i, w in enumerate(wind):
        gx = x0 + 44 + i * gw
        for j, arm in enumerate(arms):
            vals = [data["values"][rep][arm["id"]][w][key] for rep in data["repeats"]]
            mean = sum(vals) / len(vals)
            bx = gx + j * bw + 1
            tip = f"{arm['name']}, {w}: " + ", ".join(f"{rep} {v:.3f}" for rep, v in zip(data["repeats"], vals)) + " cm2"
            out.append(bar(bx, base, min(mean, ymax) * sy, bw - 2, arm["cls"], tip))
            for v in vals:
                cy = base - min(v, ymax) * sy
                out.append(f'<circle class="dot" cx="{bx + (bw - 2) / 2:.1f}" cy="{cy:.1f}" r="3"><title>{esc(tip)}</title></circle>')
            if key == "own" and arm["id"] == "barrier" and all(w in data["passing"][rep]["barrier"] for rep in data["repeats"]):
                out.append(f'<text class="t1" x="{bx + (bw - 2) / 2:.1f}" y="{base - max(vals) * sy - 10:.1f}" font-size="11" '
                           'font-weight="600" text-anchor="middle">pass</text>')
            if key == "wrong" and arm["id"] == "barrier":
                out.append(f'<text class="t2" x="{bx + (bw - 2) / 2:.1f}" y="{base - 8:.1f}" font-size="10" '
                           f'text-anchor="middle">{mean:.2f}</text>')
        out.append(f'<text class="t1" x="{gx + (gw - 16) / 2:.1f}" y="{base + 18}" font-size="12" text-anchor="middle">{w}</text>')
    out.append(f'<text class="t2" x="{x0 + 44 + (pw - 44) / 2:.1f}" y="{base + 36}" font-size="11" text-anchor="middle">'
               'seeded winding (bar: mean of two repeats; dots: each repeat)</text>')


def render(data):
    arms = data["arms"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
           'aria-labelledby="t d">', f'<title id="t">{esc(data["title"])}</title>', f'<desc id="d">{esc(data["desc"])}</desc>',
           f"<style>{STYLE}</style>", f'<rect class="bg" width="{W}" height="{H}" rx="8"/>',
           f'<text class="t1" x="24" y="34" font-size="18" font-weight="600">{esc(data["title"])}</text>',
           f'<text class="t2" x="24" y="56" font-size="13">{esc(data["subtitle"])}</text>']
    lx = 24
    for arm in arms:
        out.append(f'<rect class="{arm["cls"]}" x="{lx}" y="72" width="12" height="12" rx="2"/>')
        out.append(f'<text class="t2" x="{lx + 17}" y="83" font-size="12">{esc(arm["legend"])}</text>')
        lx += 26 + int(6.6 * len(arm["legend"]))
    panel(out, data, "own", 24, "On its own winding: area covered", 0.5, (0, 0.1, 0.2, 0.3, 0.4, 0.5),
          "cm2; 'pass' = both gates passed in both repeats")
    panel(out, data, "wrong", 504, "On other windings: wrong area", 8.0, (0, 2, 4, 6, 8),
          "cm2; numbers under the blue bars are its mean wrong area")
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
    out = Path(a.out)
    out.write_text(svg, encoding="utf-8")
    if common.svg_embeds_raster(svg):
        sys.exit("the chart embeds a raster picture")
    rec = {"schema": common.SCHEMA, "name": out.stem, "label": "Chart", "claim_label": data["claim_label"],
           "alt": data["alt"], "caption": data["caption"], "license": "Apache-2.0", "release_id": None,
           "data": {"source": str(src), "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                    "credit": data["credit"]},
           "outputs": [{"file": out.name, "bytes": out.stat().st_size, "sha256": common.sha256(out), "width": W,
                        "height": H, "kind": "svg"}],
           "made": __import__("datetime").date.today().isoformat(),
           "command": f"python scripts/media/barrier_chart.py {a.data} {a.out}",
           "tool": {"scripts": ["scripts/media/" + s for s in SCRIPTS], "scripts_sha256": common.scripts_digest(SCRIPTS),
                    "base_commit": common.git_commit()},
           "colors": "categorical slots 1 to 3 of the palette of greek-restoration-by-gap-length.svg; dark mode "
                     "through prefers-color-scheme"}
    out.with_suffix(".json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(out, out.stat().st_size)


if __name__ == "__main__":
    main()
