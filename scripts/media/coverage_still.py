"""The still for docs/tools/coverage.md: kit coverage's picture of one scan, with axis labels and a key added.

The scan must be public and on no prize list (the public media rule, docs/media/README.md): kit coverage refuses to
draw a prize-list scroll, and write_guard() refuses anything else under docs/assets/. The picture is mesh geometry
only (where traced segments lie around the center line), no CT and no ink. Writes a sidecar JSON. Needs numpy,
tifffile and Pillow.

  python scripts/media/coverage_still.py PHerc0139 --volume 20260102150214 --out-dir docs/assets/coverage
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import common  # noqa: E402
from kit import coverage, tifxyz  # noqa: E402

SCRIPTS = ("common.py", "coverage_still.py")
BG, FG, DIM = (8, 12, 16), (225, 235, 239), (122, 143, 152)


def labeled(rep, panel):
    """The panel with a title, axis labels and a key, on a canvas at most 1200 px wide."""
    from PIL import Image, ImageDraw, ImageFont
    s, w = rep["summary"], rep["summary"]["wraps"]
    left_w = 360  # coverage.picture's left panel width for the default 72 angle bins
    pad_l, pad_t, pad_b = 70, 92, 128
    img = Image.new("RGB", (pad_l + panel.shape[1] + 30, pad_t + panel.shape[0] + pad_b), BG)
    img.paste(Image.fromarray(panel), (pad_l, pad_t))
    d = ImageDraw.Draw(img)
    big, small = ImageFont.load_default(size=22), ImageFont.load_default(size=14)
    d.text((pad_l, 18), f"{rep['scroll']}: where its {s['read']} published meshes on volume {rep['volume']} lie",
           fill=FG, font=big)
    d.text((pad_l, 50), f"heights traced {s['heights_traced'] * 100:.0f} %; wrap pitch about {w['pitch_vox']:.0f} "
           f"voxels ({w.get('pitch_um', 0):.0f} um); meshes spanning {s['turns_total']:.0f} turns in all",
           fill=DIM, font=small)
    d.text((pad_l, pad_t - 20), "angle around the center line, 0 to 360 degrees", fill=DIM, font=small)
    d.text((pad_l + left_w + 16, pad_t - 20), "radius from the center line, mark every 10 bands "
           f"of {rep['grid']['r_step']:.0f} voxels", fill=DIM, font=small)
    h = panel.shape[0]
    z0, z1 = s["z_range"]
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = pad_t + int(frac * (h - 1))
        d.text((6, y - 7), f"{z0 + frac * (z1 - z0):,.0f}", fill=DIM, font=small)
    d.text((6, pad_t + h + 8), "z (slice), down", fill=DIM, font=small)
    # key for the left panel's colors: meshes tracing a cell, 1 to the most
    top = int(rep["grid"]["zt"].max())
    ramp = coverage._ramp(__import__("numpy").linspace(0, 1, 200)[None, :])
    key = Image.fromarray(__import__("numpy").repeat(ramp, 12, 0))
    ky = pad_t + h + 36
    img.paste(key, (pad_l, ky))
    d.text((pad_l, ky + 16), "1", fill=DIM, font=small)
    d.text((pad_l + 210, ky - 2), f"{top} meshes", fill=DIM, font=small)
    d.text((pad_l, ky + 36), "Left: meshes tracing each angle and height. Right: brighter where more meshes reach "
           "that radius.", fill=DIM, font=small)
    d.text((pad_l, ky + 56), "Mesh geometry only, no CT, no ink. Vesuvius Challenge open data, CC BY-NC 4.0.",
           fill=DIM, font=small)
    return img


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("scroll")
    p.add_argument("--volume", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--name", default="coverage-pherc0139")
    a = p.parse_args(argv)
    lists = coverage.may_draw(a.scroll, a.volume)
    if lists:
        raise SystemExit(f"{a.scroll} is on a prize list ({', '.join(lists)}): no picture")
    rep = coverage.run(a.scroll, a.volume)
    out = Path(a.out_dir) / f"{a.name}.png"
    meta = {"label": "Real data render", "license": "CC BY-NC 4.0",
            "alt": f"Two panels for {a.scroll}: on the left, a band of color across all 360 degrees covering the "
                   "lower third of the scan's height, with a thinner band above it, showing where traced segments "
                   "lie by angle and height; on the right, a gray cloud showing the radii from the center line "
                   "that those segments reach at each height.",
            "caption": f"Real data render: kit coverage of {a.scroll}, the {rep['summary']['read']} published "
                       f"meshes on volume {a.volume} placed around the scan's published center line. Mesh geometry "
                       "only, no CT, no ink. Vesuvius Challenge open data, CC BY-NC 4.0.",
            "data": {"scan": a.scroll, "voxel_size": f"{rep['voxel_um']} um", "labels": "none",
                     "credit": "Vesuvius Challenge open data, CC BY-NC 4.0", "segment": "all top-level meshes",
                     "volume": a.volume},
            "sources": [rep["line"]["url"]]}
    common.write_guard(meta["label"], out, meta)
    img = labeled(rep, coverage.picture(rep["grid"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    common.size_guard(out, img.size[0])
    rec = common.output_record(out, img.size[0], img.size[1], kind="still", format="png")
    command = f"python scripts/media/coverage_still.py {a.scroll} --volume {a.volume} --out-dir {a.out_dir}"
    common.write_sidecar(out.with_suffix(".json"), meta, [rec], command=command, scripts=SCRIPTS,
                         inputs=[r["id"] for r in rep["meshes"]])
    print(json.dumps({"png": str(out), "bytes": rec["bytes"], "size": list(img.size)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
