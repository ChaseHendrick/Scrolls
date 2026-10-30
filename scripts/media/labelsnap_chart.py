#!/usr/bin/env python3
"""The label snap tests as two SVG charts, from published numbers, each with a sidecar JSON.

Reads DATA.json (docs/media/label-snap-data.json, copied from label_snap_checks in docs/results.json) and writes,
into OUT_DIR, label-snap-within1.svg (the share of label vertices within 1 voxel of a finer scan's recto face, per
test, for the published label, the best community snap, kit labelsnap and kit finesnap) and label-snap-community.svg
(the pooled gain over the published label of kit labelsnap and seven community snaps, with 95 % intervals). SVG
drawings with no raster in them, in the categorical palette of docs/media/greek-restoration-by-gap-length.svg, dark
mode through prefers-color-scheme. Standard library only.

  python scripts/media/labelsnap_chart.py docs/media/label-snap-data.json docs/media
"""

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402

SCRIPTS = ("common.py", "labelsnap_chart.py")
STYLE = ("svg{font-family:system-ui,-apple-system,'Segoe UI',sans-serif}.bg{fill:#fcfcfb}.t1{fill:#0b0b0b}"
         ".t2{fill:#52514e}.grid{stroke:#e4e3df}.axis{stroke:#9c9a94}.s0{fill:#2a78d6}.s1{fill:#eb6834}"
         ".s3{fill:#eda100}.s9{fill:#a8a69f}.ci{stroke:#0b0b0b;stroke-width:1.5}.lab{fill:#fcfcfb}"
         "@media (prefers-color-scheme:dark){.bg{fill:#1a1a19}.t1{fill:#f0efec}.t2{fill:#c3c2b7}"
         ".grid{stroke:#383835}.axis{stroke:#6b6a64}.s0{fill:#3987e5}.s1{fill:#d95926}.s3{fill:#c98500}"
         ".s9{fill:#6b6a64}.ci{stroke:#f0efec}.lab{fill:#1a1a19}}")


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def head(w, h, title, subtitle):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{esc(title)}">', f"<title>{esc(title)}</title>", f"<style>{STYLE}</style>",
            f'<rect class="bg" width="{w}" height="{h}" rx="12"/>',
            f'<text class="t1" x="32" y="44" font-size="20" font-weight="650">{esc(title)}</text>',
            f'<text class="t2" x="32" y="68" font-size="13">{esc(subtitle)}</text>']


def within1(data):
    """Grouped vertical bars: one group per test, one bar per arm that the test scored."""
    w, h = 960, 540
    d = data["within1"]
    arms = d["arms"]
    out = head(w, h, "Label vertices within 1 voxel of an independent scan's recto face",
               "Fresh sites, each test's rule fixed before it ran; truth from a finer scan of the same scroll, "
               "registered per site. Model output.")
    lx = 32
    for a in arms:
        out.append(f'<rect class="{a["cls"]}" x="{lx}" y="88" width="12" height="12" rx="3"/>')
        out.append(f'<text class="t2" x="{lx + 18}" y="99" font-size="12.5">{esc(a["legend"])}</text>')
        lx += 30 + 7.2 * len(a["legend"])
    top, base, x0, x1 = 130, 470, 72, w - 32
    sy = (base - top) / 100.0
    for t in range(0, 101, 20):
        y = base - t * sy
        out.append(f'<line class="{"axis" if t == 0 else "grid"}" x1="{x0}" x2="{x1}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="t2" x="{x0 - 8}" y="{y + 4:.1f}" font-size="11.5" text-anchor="end">{t} %</text>')
    groups = d["groups"]
    gw = (x1 - x0) / len(groups)
    bw = (gw - 40) / len(arms)
    for gi, g in enumerate(groups):
        gx = x0 + gi * gw + 20
        for ai, a in enumerate(arms):
            v = g["values"].get(a["id"])
            bx = gx + ai * bw
            if v is None:
                out.append(f'<text class="t2" x="{bx + bw / 2:.1f}" y="{base - 6}" font-size="10.5" '
                           f'text-anchor="middle">n/a</text>')
                continue
            bh = v * sy
            r = min(4.0, (bw - 6) / 2)
            out.append(f'<path class="{a["cls"]}" d="M{bx + 3:.1f} {base:.1f}v{-(bh - r):.1f}a{r} {r} 0 0 1 {r} {-r}'
                       f'h{bw - 6 - 2 * r:.1f}a{r} {r} 0 0 1 {r} {r}v{bh - r:.1f}z"><title>{esc(g["name"])}, '
                       f'{esc(g["note"])}: {esc(a["legend"])} {v:.1f} %</title></path>')
            out.append(f'<text class="t1" x="{bx + bw / 2:.1f}" y="{base - bh - 6:.1f}" font-size="11.5" '
                       f'text-anchor="middle">{v:.0f}</text>')
        cx = x0 + gi * gw + gw / 2
        out.append(f'<text class="t1" x="{cx:.1f}" y="{base + 22}" font-size="13.5" font-weight="600" '
                   f'text-anchor="middle">{esc(g["name"])}</text>')
        out.append(f'<text class="t2" x="{cx:.1f}" y="{base + 40}" font-size="12" text-anchor="middle">'
                   f'{esc(g["note"])}</text>')
    out.append(f'<text class="t2" x="32" y="{h - 14}" font-size="11.5">n/a: not run in that test. Best community '
               f'snap: the highest of seven on that scroll. Numbers: label_snap_checks in docs/results.json.</text>')
    out.append("</svg>")
    return w, h, "\n".join(out) + "\n"


def community(data):
    """Horizontal bars with 95 % intervals, one row per method; an off-scale row is drawn to the edge and labeled."""
    w, h = 960, 600
    d = data["community"]
    rows = d["rows"]
    out = head(w, h, "Distance gained toward the recto face over the published label",
               "71 fresh PHerc0814 and PHerc0841 sites pooled, label-scan voxels (about 9.4 um), bars 95 % "
               "intervals; rule fixed before the run. Model output.")
    lo_ax, hi_ax = -1.0, 3.0
    x0, x1, top = 392, w - 48, 104
    rh = 44
    sx = (x1 - x0) / (hi_ax - lo_ax)

    def X(v):
        return x0 + (min(max(v, lo_ax), hi_ax) - lo_ax) * sx

    base = top + rh * len(rows)
    for t in (-1, 0, 1, 2, 3):
        out.append(f'<line class="{"axis" if t == 0 else "grid"}" x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{top - 6}" '
                   f'y2="{base}"/>')
        out.append(f'<text class="t2" x="{X(t):.1f}" y="{base + 18}" font-size="11.5" text-anchor="middle">'
                   f'{t:+d}</text>' if t else f'<text class="t2" x="{X(t):.1f}" y="{base + 18}" font-size="11.5" '
                   f'text-anchor="middle">0</text>')
    out.append(f'<text class="t2" x="{X(1):.1f}" y="{base + 38}" font-size="12" text-anchor="middle">voxels closer '
               f'to the recto face than the published label (left of 0: farther)</text>')
    for i, r in enumerate(rows):
        y = top + i * rh + 8
        bh = rh - 18
        a, b = X(0), X(r["mean"])
        left, width = min(a, b), abs(b - a)
        tip = f'{r["name"]}: {r["mean"]:+.2f} ({r["lo"]:+.2f} to {r["hi"]:+.2f})'
        out.append(f'<text class="t1" x="{x0 - 14}" y="{y + bh / 2 + 5:.1f}" font-size="13" text-anchor="end">'
                   f'{esc(r["name"])}</text>')
        out.append(f'<rect class="{r["cls"]}" x="{left:.1f}" y="{y}" width="{max(width, 1.5):.1f}" height="{bh}" '
                   f'rx="4"><title>{esc(tip)}</title></rect>')
        off = r["mean"] < lo_ax
        if not off:
            out.append(f'<line class="ci" x1="{X(r["lo"]):.1f}" x2="{X(r["hi"]):.1f}" y1="{y + bh / 2:.1f}" '
                       f'y2="{y + bh / 2:.1f}"/>')
            for e in (r["lo"], r["hi"]):
                out.append(f'<line class="ci" x1="{X(e):.1f}" x2="{X(e):.1f}" y1="{y + bh / 2 - 6:.1f}" '
                           f'y2="{y + bh / 2 + 6:.1f}"/>')
        label = f'{r["mean"]:+.2f}' + (" (off scale)" if off else "")
        lx = X(max(r["hi"], 0)) + 8 if not off else X(0) + 8
        out.append(f'<text class="t1" x="{lx:.1f}" y="{y + bh / 2 + 4:.1f}" font-size="12">{esc(label)}</text>')
    out.append(f'<text class="t2" x="32" y="{h - 38}" font-size="11.5">The fixed offset moves every vertex by '
               f'labelsnap\'s median move, to show how much one shift gives. Midline and nearest-peak snaps aim at</text>')
    out.append(f'<text class="t2" x="32" y="{h - 16}" font-size="11.5">the sheet center by design, so part of '
               f'their loss is the target, not error. Numbers: label_snap_checks in docs/results.json.</text>')
    out.append("</svg>")
    return w, h, "\n".join(out) + "\n"


CHARTS = {
    "label-snap-within1": (within1, "within1",
                           "Grouped bars for four tests on PHerc0139, PHerc0814 and PHerc0841: the published label "
                           "has 19 to 24 % of vertices within 1 voxel of the finer scan's recto face, the best "
                           "community snap 21 to 22 %, kit labelsnap 55 to 79 % and kit finesnap 85 to 91 %.",
                           "Share of surface label vertices within 1 voxel of the recto face of an independent "
                           "finer scan, on fresh sites, per test. Model output; geometry, not a reading."),
    "label-snap-community": (community, "community",
                             "Horizontal bars: kit labelsnap is 2.15 voxels closer to the recto face than the "
                             "published label; one fixed offset 0.77; seven community snaps between +0.26 and "
                             "-0.41, and vc_objrefine as shipped -9.72, off the scale.",
                             "Mean distance gained toward a finer scan's recto face over the published label, 71 "
                             "fresh sites pooled, with 95 % intervals. Model output; geometry, not a reading."),
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data", help="the charts' numbers (JSON)")
    ap.add_argument("out_dir", help="folder for the SVGs; each sidecar goes beside its SVG")
    a = ap.parse_args(argv)
    src = Path(a.data)
    data = json.loads(src.read_text(encoding="utf-8"))
    for name, (fn, key, alt, caption) in CHARTS.items():
        w, h, svg = fn(data)
        for ch in common.LONG_DASHES:
            if ch in svg:
                sys.exit("long dash in the chart text")
        if common.svg_embeds_raster(svg):
            sys.exit("the chart embeds a raster picture")
        out = Path(a.out_dir) / (name + ".svg")
        out.write_text(svg, encoding="utf-8")
        rec = {"schema": common.SCHEMA, "name": name, "label": "Chart", "claim_label": data[key]["claim_label"],
               "alt": alt, "caption": caption, "license": "Apache-2.0", "release_id": None,
               "data": {"source": str(src), "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                        "credit": data["credit"]},
               "outputs": [{"file": out.name, "bytes": out.stat().st_size, "sha256": common.sha256(out), "width": w,
                            "height": h, "kind": "svg"}],
               "made": datetime.date.today().isoformat(),
               "command": f"python scripts/media/labelsnap_chart.py {a.data} {a.out_dir}",
               "tool": {"scripts": ["scripts/media/" + s for s in SCRIPTS],
                        "scripts_sha256": common.scripts_digest(SCRIPTS), "base_commit": common.git_commit()},
               "colors": "categorical slots 1, 2 and 4 of the palette of greek-restoration-by-gap-length.svg "
                         "(blue, orange, amber) with a neutral gray for the published label and the reference; "
                         "dark mode through prefers-color-scheme"}
        out.with_suffix(".json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(out, out.stat().st_size)


if __name__ == "__main__":
    main()
