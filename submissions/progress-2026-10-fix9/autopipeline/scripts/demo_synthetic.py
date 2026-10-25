#!/usr/bin/env python3
"""AutoPipeline on a synthetic scroll, end to end, in about a minute, with no download, no VC3D and no GPU.

The scroll is the test suite's fake: one papyrus sheet, a cylinder of radius 40 voxels around a known axis, in a
64 x 128 x 128 surface prediction (tests/test_autopipe.py). Its CT is drawn here: the sheet with horizontal fibers,
and on its outer face a thin denser layer in the shape of planted pen strokes, rows of capital-like shapes. The VC3D
tools are the stand-ins in tests/vc3d_fakes.py, small Python scripts that take the real tools' command lines. The
stand-in ink model below scores the dense layer on the front half of each rendered column, so the forward map shows
the planted strokes and the reversed control, whose front half is the bare back of the sheet, does not. Every stage
runs for real on those inputs: acquire, umbilicus, seeds, trace, qa, flatten, the chunk audit and render, ink with
its reverse and shuffle controls, and the report with its digest.

    python3 scripts/demo_synthetic.py                 # into a fresh temporary folder
    python3 scripts/demo_synthetic.py --out demo-run  # keep the run folder

Exit 0 when every stage ends done (bench and score are skipped: the fake scroll has no published windings or
labels), both surfaces are accepted, and both fake-model runs exit successfully with all three map files.
Nothing here is a reading of anything: the strokes were planted in a synthetic CT, and the "ink" map is a stand-in
model's sigmoid of it.
"""

import argparse
import json
import math
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

# the nearest folder above this script that holds kit/ and tests/ (the release folder, for scripts/demo_synthetic.py)
ROOT = next(p for p in Path(__file__).resolve().parents if (p / "kit").is_dir() and (p / "tests").is_dir())
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import vc3d_fakes as fakes  # noqa: E402
from test_autopipe import AXIS, RADIUS, SHAPE, scroll  # noqa: E402

from kit import autopipe, vc3d_agent  # noqa: E402

WANT = {"acquire": "done", "umbilicus": "done", "seeds": "done", "trace": "done", "bench": "skipped",
        "qa": "done", "flatten": "done", "render": "done", "ink": "done", "score": "skipped", "report": "done"}


# Planted strokes: segments in a unit box (x right, y down) for a few capital-like shapes.
_O = [((.5 + .5 * math.cos(k * math.pi / 5), .5 + .5 * math.sin(k * math.pi / 5)),
       (.5 + .5 * math.cos((k + 1) * math.pi / 5), .5 + .5 * math.sin((k + 1) * math.pi / 5))) for k in range(10)]
SHAPES = (
    [((0, 1), (.5, 0)), ((.5, 0), (1, 1)), ((.22, .6), (.78, .6))],
    [((0, 1), (0, 0)), ((0, 0), (1, 1)), ((1, 1), (1, 0))],
    _O,
    [((0, 0), (1, 0)), ((.5, 0), (.5, 1))],
    [((0, 0), (0, 1)), ((0, 0), (.9, 0)), ((0, .5), (.7, .5)), ((0, 1), (.9, 1))],
    [((0, 1), (.5, 0)), ((.5, 0), (1, 1))],
    [((0, 0), (1, 0)), ((.1, 0), (.1, 1)), ((.9, 0), (.9, 1))],
    [((1, 0), (0, 0)), ((0, 0), (.55, .5)), ((.55, .5), (0, 1)), ((0, 1), (1, 1))],
)


def strokes(seed=7, height=11.0, width=8.0, pitch=16.0, gap=3.0, z0=6.0, z1=60.0):
    """[((z, s), (z, s))]: rows of shapes picked at random, each slanted and jittered a little like a hand, over the
    whole sheet (s is arc length around the axis, in voxels)."""
    rnd = random.Random(seed)
    half = math.pi * RADIUS
    segs, z = [], z0
    while z + height <= z1:
        s = -half + rnd.uniform(0, gap)
        while s + width <= half:
            slant, w, moved = rnd.uniform(-.12, .12), width * rnd.uniform(.85, 1.1), {}
            for p0, p1 in rnd.choice(SHAPES):
                ends = []
                for p in (p0, p1):     # a point two strokes share moves with both, as a pen joins them
                    if p not in moved:
                        moved[p] = (p[0] + rnd.uniform(-.06, .06), p[1] + rnd.uniform(-.05, .05))
                    a, b = moved[p]
                    ends.append((z + b * height, s + a * w + slant * (1 - b) * height))
                segs.append(tuple(ends))
            s += w + gap
        z += pitch
    return segs


def _smooth(x, seed, period):
    """Smooth value noise in 0 to 1 along x."""
    i = math.floor(x / period)
    f = x / period - i
    f = f * f * (3 - 2 * f)
    a, b = (random.Random(k * 7919 + seed).random() for k in (i, i + 1))
    return a * (1 - f) + b * f


def papyrus_ct(segs, width=1.1):
    """value(z, y, x) of the demo's CT: air 40; the sheet (about 4 voxels thick) 168 to 184 with horizontal fibers;
    and where a planted stroke lies, a layer 0.6 to 3.4 voxels outside the sheet's middle up to 90 denser, unevenly
    as a pen leaves it."""
    rows = {}
    for seg in segs:
        for z in range(int(min(seg[0][0], seg[1][0])) - 2, int(max(seg[0][0], seg[1][0])) + 3):
            rows.setdefault(z, []).append(seg)
    cover = {}

    def ink(z, s):
        best = 9.0
        for (az, as_), (bz, bs) in rows.get(z, ()):
            dz, ds = bz - az, bs - as_
            n = dz * dz + ds * ds
            t = 0.0 if not n else max(0.0, min(1.0, ((z - az) * dz + (s - as_) * ds) / n))
            best = min(best, math.hypot(z - az - t * dz, s - as_ - t * ds))
        return max(0.0, min(1.0, width + 0.6 - best)) * (0.6 + 0.4 * _smooth(s / 9 + z / 13, 17, 1.0))

    def value(z, y, x):
        d = math.hypot(x - AXIS[0], y - AXIS[1]) - RADIUS
        if abs(d) > 4.5:
            return 40
        s = RADIUS * math.atan2(y - AXIS[1], x - AXIS[0])
        v = 40 + max(0.0, min(1.0, 2.2 - abs(d))) * (128 + 16 * _smooth(z + 2 * _smooth(s, 5, 17.0), 11, 1.7))
        if 0.6 <= d <= 3.4:
            k = (z, round(s, 1))
            if k not in cover:
                cover[k] = ink(z, s)
            v += 90 * cover[k]
        return int(min(255, v))
    return value


# The stand-in ink model: on each rendered column, the dense layer in its front half (voxels over 200) plus a little
# of the papyrus's own brightness, through a sigmoid, then a light 3 x 3 blur; 0 off the surface, where every layer is
# empty.
INK_MODEL = f'''import array, math, sys
sys.path.insert(0, {str(ROOT)!r})
from kit import vc3d_io
layers, out, reverse = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
files = vc3d_io.layer_files(layers)
if reverse:
    files = files[::-1]
planes = [vc3d_io.read_tiff(f).data for f in files]
first = vc3d_io.read_tiff(files[0])
half = len(planes) // 2
vals = array.array("f")
for i in range(first.h * first.w):
    col = [p[i] for p in planes]
    if not any(col):
        vals.append(0.0)
        continue
    dense = sum(max(0.0, v - 200) for v in col[:half])
    paper = max([v for v in col if v < 195] or [176])
    vals.append(1.0 / (1.0 + math.exp(-(dense / 40 + (paper - 176) / 25 - 1.6))))
h, w = first.h, first.w
smooth = array.array("f", vals)
for i in range(h * w):          # a light 3 x 3 blur among on-surface pixels, as a patch model's output is smooth
    if vals[i]:
        r, c = divmod(i, w)
        near = [((2 - abs(y - r)) * (2 - abs(x - c)), vals[y * w + x]) for y in range(max(0, r - 1), min(h, r + 2))
                for x in range(max(0, c - 1), min(w, c + 2)) if vals[y * w + x]]
        smooth[i] = sum(k * v for k, v in near) / sum(k for k, _ in near)
vc3d_io.write_tiff(out, vc3d_io.Raster(h, w, "f32", smooth))
print("ink model wrote", out)
'''


def result_errors(state, out):
    """Check stage completion and actual required fake-model outputs, not just the orchestration status."""
    errors = []
    if {k: v.get("status") for k, v in state.get("stages", {}).items()} != WANT:
        errors.append("a stage did not end as expected")
    surfaces = state.get("surfaces") or {}
    if len(surfaces) != 2:
        errors.append(f"expected two synthetic surfaces, got {len(surfaces)}")
    for sid, surface in sorted(surfaces.items()):
        if surface.get("accepted") is not True:
            errors.append(f"{sid}: surface was not accepted")
        model = (surface.get("ink") or {}).get("fake-ink") or {}
        if model.get("exit") != 0:
            errors.append(f"{sid}: fake ink exited {model.get('exit')}; inspect ink/{sid}/fake-ink/ink.log")
        maps = model.get("maps") or {}
        for variant in ("f", "r", "s"):
            path = (maps.get(variant) or {}).get("path")
            valid = False
            if isinstance(path, str) and path:
                try:
                    p = Path(path).resolve()
                    p.relative_to(Path(out).resolve())
                    valid = p.is_file() and p.stat().st_size > 0
                except (ValueError, OSError, RuntimeError):
                    pass
            if not valid:
                errors.append(f"{sid}: missing, empty or out-of-run {variant} map")
    return errors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", help="run folder (default: a new temporary folder)")
    a = ap.parse_args(argv)
    t0 = time.time()
    d = Path(a.out).resolve() if a.out else Path(tempfile.mkdtemp(prefix="autopipe-demo-"))
    d.mkdir(parents=True, exist_ok=True)
    home = d / "home"
    fakes.make_bin(d / "bin")
    env = fakes.env_for(d / "bin", home, FAKE_TRACE_ARC=f"{AXIS[0]},{AXIS[1]}")
    pred, ct, axis = scroll(d)
    shutil.rmtree(ct)                         # the test suite's plain CT, redrawn with fibers and planted strokes
    fakes.write_group(ct, SHAPE, papyrus_ct(strokes()))
    grids = d / "grids"                       # the stand-in tracer only needs metadata.json
    (grids / "xy").mkdir(parents=True, exist_ok=True)
    (grids / "metadata.json").write_text(json.dumps({"spiral-step": 20, "grid-step": 64}))
    model = d / "fake_ink_model.py"
    model.write_text(INK_MODEL)
    home.mkdir(parents=True, exist_ok=True)
    (home / "models.json").write_text(json.dumps({"fake-ink": {
        "engine": "command", "command": [sys.executable, str(model), "{layers}", "{output}", "{reverse}"]}}))

    settings = autopipe._merge(autopipe.DEFAULTS, {
        "purpose": "smoke", "umbilicus": {"source": str(axis)},
        "seeds": {"count": 2, "z_range": [20, 44], "radius_um": [300.0, 500.0], "level": 0, "min_spacing_um": 80.0},
        "qa": {"require_seated": "none", "windaudit": "off", "windows": 1},
        "ink": {"where": "local", "models": ["fake-ink"], "variants": ["f", "r", "s"]}})
    resolved = {"sample": "PHercSynthetic", "volume": "V1", "volume_url": str(ct), "voxel_um": 10.0,
                "shape_zyx": SHAPE, "license": None, "prediction_url": str(pred), "prediction_model": "synthetic",
                "prediction_level": 0, "normal_grids_url": str(grids), "normal_grids_model": "synthetic",
                "catalog_umbilicus": None, "benchmark": None}
    plan = {"version": autopipe.PLAN_VERSION, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "settings": settings, "resolved": resolved}
    plan["digest"] = autopipe.digest({k: plan[k] for k in ("version", "settings", "resolved")})
    out = d / "run"
    out.mkdir(exist_ok=True)
    (out / "plan.json").write_text(json.dumps(plan, indent=1))

    ctx = vc3d_agent.Context(env=env)
    try:
        st = autopipe.Run(vc3d_agent, ctx, out, plan).run()
    finally:
        ctx.close()
    status = {k: v.get("status") for k, v in st["stages"].items()}
    for k, v in status.items():
        print(f"{k:10s} {v}" + ("" if WANT.get(k) == v else f"   (expected {WANT.get(k)})"))
    for sid, s in sorted(st.get("surfaces", {}).items()):
        maps = {m: sorted((v.get("maps") or {})) for m, v in (s.get("ink") or {}).items()}
        print(f"surface {sid}: accepted={s.get('accepted')} flatten={s.get('flatten', {}).get('used')} "
              f"render={'yes' if s.get('render', {}).get('zarr') else 'no'} ink maps={maps}")
    print(f"plan digest {plan['digest'][:16]}..., run folder {out}, {time.time() - t0:.1f} s")
    errors = result_errors(st, out)
    if errors:
        print("DEMO FAIL: " + "; ".join(errors))
        print("Check state.json and the named ink.log files. Install this package's dependencies in the ink Python too.")
        return 1
    print("DEMO PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
