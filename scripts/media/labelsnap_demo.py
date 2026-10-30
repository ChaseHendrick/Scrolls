#!/usr/bin/env python3
"""A slow GIF and a still of kit labelsnap on made-up data: the gap ladder of tests/test_snap_face.py.

Builds the ladder (three blurred 6-voxel sheets; the neighbor on the recto side, toward the axis, sits 4, 2, 1, 0.5
and 0 voxels from the middle sheet across x), puts a flat label 2.9 voxels inside the middle sheet, runs
`python -m kit labelsnap snap` on it twice (the default, then with --merged), and draws one cross section of each run:
the label line moving from where it was traced to where the snap put it, abstaining vertices staying put in gray.
It shows what the tool page says: on gaps of 2 voxels or more the snap lands on the middle sheet's recto face; under
1 voxel the default takes the neighbor's face, and --merged abstains there instead. No scan data: media label
Synthetic demo, so it may go under docs/assets/.

  python scripts/media/labelsnap_demo.py --out-dir docs/assets/labelsnap

Needs numpy, tifffile, zarr and Pillow. Every output gets a sidecar JSON (common.write_sidecar).
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import common  # noqa: E402
import snap_media as sm  # noqa: E402

SCRIPTS = ("common.py", "snap_media.py", "labelsnap_demo.py")
W, H = 960, 540
X_PX, Z_PX = 10, 5                 # pixels per voxel, across and through the sheets
Z_LO, Z_HI = 14, 48                # the z window drawn (the axis is below, at low z)
ROW = 4                            # the mesh row drawn (y = 12)
ABST = (150, 150, 150)


def build(work):
    """The ladder, the label, and the two labelsnap runs; returns the label z, the two snapped z rows and their
    abstain rows, and the ladder's cross section."""
    import numpy as np
    import tifffile
    from kit import snap
    from tests.test_snap import plane_mesh, write_zarr
    from tests.test_snap_face import GAPS, LADDER_W, ladder_volume
    vol = ladder_volume(1.0, 0.0)
    write_zarr(work / "ladder.zarr", vol)
    xs, ys, zs = plane_mesh(9, LADDER_W * len(GAPS), 30.4, step=1.0, x0=4.0, y0=8.0)
    snap.write_mesh(None, work / "label", xs, ys, zs, np.ones(xs.shape, bool), {}, "synthetic")
    runs = {}
    for name, extra in (("default", []), ("merged", ["--merged"])):
        out = work / name
        cmd = [sys.executable, "-m", "kit", "labelsnap", "snap", str(work / "label"), "--volume",
               str(work / "ladder.zarr"), "--out", str(out), "--axis-point", "20", "12", "-400", "--axis-dir", "1",
               "0", "0", "--no-label"] + extra
        subprocess.run(cmd, check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
        z = tifffile.imread(out / "snapped.tifxyz" / "z.tif")[ROW]
        ab = tifffile.imread(out / "abstain.tif")[ROW] > 0
        rec = json.loads((out / "labelsnap.json").read_text(encoding="utf-8"))
        runs[name] = {"z": z, "abstain": ab, "abstained": rec["vertices"]["abstained"],
                      "valid": rec["vertices"]["valid"]}
    y = int(round(ys[ROW, 0]))
    section = vol[:, y, :].astype("float32")         # z by x
    return xs[ROW], zs[ROW], runs, section, GAPS, LADDER_W


def panel_base(section, top, title, note):
    """The ladder's cross section, warm gray, low z at the bottom, with its heading."""
    import numpy as np
    from PIL import Image
    crop = section[Z_LO:Z_HI][::-1]                  # flip so the axis side is down
    g = np.clip(crop, 0, 255)
    rgb = np.stack([g * 0.92 + 14, g * 0.86 + 14, g * 0.74 + 16], -1).clip(0, 255).astype("uint8")
    img = Image.fromarray(rgb).resize((rgb.shape[1] * X_PX, rgb.shape[0] * Z_PX), Image.NEAREST)
    return img, top, title, note


def zpix(z, top):
    return top + (Z_HI - z) * Z_PX


def frame(t, xs, z0, runs, bases, gaps, lw, final_text):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), (250, 250, 248))
    d = ImageDraw.Draw(img)
    f_t, f_s, f_x = sm._font(19), sm._font(14), sm._font(12)
    d.text((20, 12), "kit labelsnap on a made-up gap ladder", fill=(20, 20, 20), font=f_t)
    d.text((20, 38), "Orange: the label as traced. Blue: where the snap puts it. Gray: abstained, left in place. "
                     "The axis is below.", fill=(80, 80, 78), font=f_s)
    left = 40
    for (name, (base, top, title, note)) in zip(("default", "merged"), bases):
        img.paste(base, (left, top))
        d.text((left, top - 22), title, fill=(20, 20, 20), font=f_s)
        d.text((left + 430, top - 22), note, fill=(80, 80, 78), font=f_s)
        for b, g in enumerate(gaps):
            cx = left + (4 + b * lw + lw / 2) * X_PX
            if name == "default":
                d.text((cx - 22, top + base.size[1] + 4), f"gap {g:g}", fill=(80, 80, 78), font=f_x)
        r = runs[name]
        pts = []
        for i, x in enumerate(xs):
            px = left + (x + 0.5) * X_PX
            if r["abstain"][i]:
                zz = z0[i]
            else:
                zz = z0[i] + (r["z"][i] - z0[i]) * t
            pts.append((px, zpix(zz + 0.5, top), bool(r["abstain"][i])))
        col = sm.mix(sm.PUB, sm.SNAP, t)
        for (xa, ya, aa), (xb, yb, ab) in zip(pts, pts[1:]):
            if abs(ya - yb) < 3 * Z_PX and aa == ab:
                d.line((xa, ya, xb, yb), fill=ABST if aa else col, width=4)
        for (px, py, ab) in pts[::4]:
            d.ellipse((px - 3, py - 3, px + 3, py + 3), fill=ABST if ab else col)
    d.text((20, H - 26), final_text, fill=(80, 80, 78), font=f_x)
    return img


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out-dir", required=True, help="where the GIF, the still and their sidecar go")
    ap.add_argument("--name", default="labelsnap-ladder", help="file name stem")
    a = ap.parse_args(argv)
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        xs, z0, runs, section, gaps, lw = build(Path(tmp))
    ph = (Z_HI - Z_LO) * Z_PX
    top1, top2 = 96, 96 + ph + 58
    nd, nm = runs["default"], runs["merged"]
    bases = [panel_base(section, top1, "Default", f"{nd['abstained']} of {nd['valid']} vertices abstained"),
             panel_base(section, top2, "With --merged", f"{nm['abstained']} of {nm['valid']} vertices abstained")]
    foot = ("Synthetic demo: made-up volume, no scan data. Under a 1 voxel gap the two sheets read as one band; "
            "the default then takes the neighbor's face.")
    frames, durs = [], []
    for t, sec in sm.timeline(back=True):
        frames.append(frame(t, xs, z0, runs, bases, gaps, lw, foot))
        durs.append(sec)
    gif = out_dir / (a.name + ".gif")
    png = out_dir / (a.name + ".png")
    sm.save_gif(frames, durs, gif)
    frame(1.0, xs, z0, runs, bases, gaps, lw, foot).save(png, optimize=True)
    meta = {"label": "Synthetic demo", "license": "Apache-2.0",
            "alt": "Two cross sections of a made-up stack of three papyrus sheets whose lower gap shrinks from 4 "
                   "voxels to 0 across the picture. An orange label line inside the middle sheet moves to a blue "
                   "line on the sheet's lower face where the gap is 2 voxels or more; under 1 voxel the default "
                   "drops to the neighbor's face, and with --merged those vertices stay in place in gray.",
            "caption": "Synthetic demo of kit labelsnap on the gap ladder of tests/test_snap_face.py, default and "
                       "--merged. No scan data; geometry, not a reading."}
    sm.finish([gif, png], meta, out_dir, f"python scripts/media/labelsnap_demo.py --out-dir {a.out_dir}")
    for p in (gif, png):
        print(p, p.stat().st_size)


if __name__ == "__main__":
    main()
