"""Before and after stills for the how-to docs/segments-without-vc3d.md, made with kit tifxyz.

  before   x.tif of a public segment as an image viewer shows it: one gray value per grid node (its x position)
  after    the same segment shaded by kit tifxyz preview: the sheet's 3D shape, holes dark
  check    kit tifxyz check's picture on a synthetic sheet with a planted hole, fold and stretched strip
  diff     kit tifxyz diff's picture of two versions of a synthetic sheet: one grown, trimmed and nudged

The segment must be from a public scan that is not prize-eligible (the public media rule, docs/media/README.md);
write_guard() refuses anything else under docs/assets/. Each picture gets a sidecar JSON. Needs numpy and tifffile.

  python scripts/media/tifxyz_stills.py SEGMENT --scan PHerc0139 --segment w035 --out-dir docs/assets/tifxyz
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import common  # noqa: E402
from kit import tifxyz  # noqa: E402

SCRIPTS = ("common.py", "tifxyz_stills.py")


def _fit(img, size):
    h, w = img.shape[:2]
    k = max(1, -(-max(h, w) // size))
    return img[::k, ::k] if k > 1 else img


def before(seg, size):
    np = seg._np
    x = seg.xyz[..., 0]
    v = x[seg.valid]
    lo, hi = float(v.min()), float(v.max())
    g = np.where(seg.valid, 20 + 215 * (x - lo) / max(hi - lo, 1e-9), 0).astype(np.uint8)
    return _fit(np.repeat(g[..., None], 3, -1), size)


def planted():
    import numpy as np
    h, w, step = 160, 220, 20.0
    r, c = np.mgrid[0:h, 0:w].astype(float)
    xyz = np.stack([1000 + c * step, 2000 + r * step, 500 + 300 * np.sin(c / 35.0)], -1)
    xyz[60:80, 40:70] = -1                                  # a hole inside the sheet
    k = (r >= 110) & (c >= 120) & (c < 170)                 # a fold: the sheet doubles back on itself
    xyz[k, 1] = xyz[110, 0, 1] - (r[k] - 110) * step * 0.02
    xyz[k, 2] += (r[k] - 110) * step
    xyz[20:50, 160:200, 0] += 2.2 * step                    # a patch pulled 2.2 grid steps sideways
    valid = (xyz > -0.5).all(-1)
    return tifxyz.Segment(xyz, valid, {"scale": [1 / step, 1 / step]}, "planted-demo", 2.0)


def versions():
    """Two versions of one synthetic sheet on one grid: b grows 40 columns a lacked, loses a corner a had, and moves
    a patch 4 voxels along its normal (z)."""
    import numpy as np
    h, w, step = 160, 220, 20.0
    r, c = np.mgrid[0:h, 0:w].astype(float)
    a = np.stack([1000 + c * step, 2000 + r * step, 500 + 300 * np.sin(c / 35.0)], -1)
    b = a.copy()
    a[:, 180:] = -1                                         # b grew these columns
    b[:40, :50] = -1                                        # b dropped this corner
    b[90:130, 70:120, 2] += 4.0                             # b moved this patch 4 voxels
    meta = {"scale": [1 / step, 1 / step]}
    mk = lambda xyz, name: tifxyz.Segment(xyz, (xyz > -0.5).all(-1), meta, name, 2.0)  # noqa: E731
    return mk(a, "version-a"), mk(b, "version-b")


def save(path, img, meta, command, inputs=()):
    common.write_guard(meta["label"], path, meta)
    tifxyz.write_png(path, img)
    common.size_guard(path, img.shape[1])
    out = common.output_record(path, img.shape[1], img.shape[0], kind="still", format="png")
    side = Path(path).with_suffix(".json")
    common.write_sidecar(side, meta, [out], command=command, scripts=SCRIPTS, inputs=inputs)
    return side


def main(argv=None):
    p = argparse.ArgumentParser(prog="python scripts/media/tifxyz_stills.py", description=__doc__.split("\n\n")[0])
    p.add_argument("segment", help="tifxyz folder or bucket URL (kit tifxyz's argument)")
    p.add_argument("--scan", required=True, help="the scroll, for example PHerc0139")
    p.add_argument("--segment", dest="name", required=True, help="the segment, for example w035")
    p.add_argument("--cache", default=tifxyz.DEFAULT_CACHE)
    p.add_argument("--size", type=int, default=1200)
    p.add_argument("--out-dir", required=True)
    a = p.parse_args(argv)
    seg = tifxyz.load(a.segment, a.cache)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    um = f"{seg.voxel_um:g} um" if seg.voxel_um else "unknown"
    data = {"scan": a.scan, "voxel_size": um, "labels": "none", "credit": common.DATA_CREDIT,
            "segment": a.name, "volume": seg.volume}
    cmd = f"python scripts/media/tifxyz_stills.py {a.segment} --scan {a.scan} --segment {a.name} --out-dir {a.out_dir}"
    src = [a.segment] if "://" in a.segment else []
    shape = f"{seg.xyz.shape[1]} x {seg.xyz.shape[0]} node"
    made = [
        save(out / "tifxyz-before.png", before(seg, a.size), {
            "label": "Real data render", "license": common.DATA_LICENSE, "data": data, "sources": src,
            "alt": f"The x.tif of {a.scan} segment {a.name} opened as a plain image: a smooth {shape} field of gray "
                   "values (each node's x position), missing nodes black, with no sign of the sheet's ripples.",
            "caption": f"Real data render: {a.scan} {a.name}'s x.tif as an image viewer shows it, one gray value per "
                       f"grid node. Mesh geometry only, no CT, no ink. {common.DATA_CREDIT}."}, cmd),
        save(out / "tifxyz-after.png", tifxyz.shade(seg, size=a.size), {
            "label": "Real data render", "license": common.DATA_LICENSE, "data": data, "sources": src,
            "alt": f"The same {a.scan} segment {a.name} shaded by kit tifxyz preview: the papyrus sheet's ripples and "
                   "bends lit from one side, missing nodes dark.",
            "caption": f"Real data render: kit tifxyz preview of {a.scan} {a.name}, the sheet's 3D shape from its "
                       f"three TIFFs. Mesh geometry only, no CT, no ink. {common.DATA_CREDIT}."}, cmd),
    ]
    demo = planted()
    rep, masks = tifxyz.check(demo)
    made.append(save(out / "tifxyz-check-demo.png", tifxyz.shade(demo, masks, size=a.size), {
        "label": "Synthetic demo", "license": "Apache-2.0", "data": None, "sources": [],
        "alt": "A made-up wavy sheet shaded gray with kit tifxyz check's flags: a blue patch where nodes are missing "
               "inside the sheet, a red outline around a patch where the sheet folds back on itself, and an orange "
               "outline around a patch shifted sideways, where the grid edges at its border are stretched.",
        "caption": f"Synthetic demo: kit tifxyz check on a made-up sheet with a planted hole ({rep['holes']['nodes']} "
                   f"nodes, blue), fold ({rep['folds']['nodes']} nodes, red) and shifted patch whose border edges "
                   f"stretch ({rep['stretched']['nodes']} nodes, orange). No scan data."}, cmd))
    va, vb = versions()
    rep, masks = tifxyz.diff(va, vb)
    made.append(save(out / "tifxyz-diff-demo.png", tifxyz.diff_picture(vb, masks, a.size), {
        "label": "Synthetic demo", "license": "Apache-2.0", "data": None, "sources": [],
        "alt": "A made-up wavy sheet shaded gray, the newer of two versions, with kit tifxyz diff's colors: a green "
               "band on the right where the newer version grew, a red block at the top left where it lost nodes, and "
               "an orange patch in the middle that moved.",
        "caption": f"Synthetic demo: kit tifxyz diff of two versions of a made-up sheet, version b grown by "
                   f"{rep['added']} nodes (green), trimmed by {rep['removed']} (red) and with {rep['moved']} nodes "
                   f"moved {rep['displacement_vox']['p100']:g} voxels (orange). No scan data."}, cmd))
    for m in made:
        print(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
