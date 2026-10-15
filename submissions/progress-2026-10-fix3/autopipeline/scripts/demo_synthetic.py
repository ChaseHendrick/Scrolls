#!/usr/bin/env python3
"""AutoPipeline on a synthetic scroll, end to end, in about a minute, with no download, no VC3D and no GPU.

The scroll is the test suite's fake: one papyrus sheet, a cylinder of radius 40 voxels around a known axis, in a
64 x 128 x 128 CT and surface prediction (tests/test_autopipe.py). The VC3D tools are the stand-ins in
tests/vc3d_fakes.py, small Python scripts that take the real tools' command lines. The ink model is the fakes'
command-engine model. Every stage runs for real on those inputs: acquire, umbilicus, seeds, trace, qa, flatten,
the chunk audit and render, ink with its reverse and shuffle controls, and the report with its digest.

    python3 scripts/demo_synthetic.py                 # into a fresh temporary folder
    python3 scripts/demo_synthetic.py --out demo-run  # keep the run folder

Exit 0 when every stage ends done (bench and score are skipped: the fake scroll has no published windings or
labels). Nothing here is a reading of anything: the "ink" is a sigmoid of the fake CT.
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

# the nearest folder above this script that holds kit/ and tests/ (the release folder, for scripts/demo_synthetic.py)
ROOT = next(p for p in Path(__file__).resolve().parents if (p / "kit").is_dir() and (p / "tests").is_dir())
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import vc3d_fakes as fakes  # noqa: E402
from test_autopipe import AXIS, SHAPE, scroll  # noqa: E402

from kit import autopipe, vc3d_agent  # noqa: E402

WANT = {"acquire": "done", "umbilicus": "done", "seeds": "done", "trace": "done", "bench": "skipped",
        "qa": "done", "flatten": "done", "render": "done", "ink": "done", "score": "skipped", "report": "done"}


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
    grids = d / "grids"                       # the stand-in tracer only needs metadata.json
    (grids / "xy").mkdir(parents=True, exist_ok=True)
    (grids / "metadata.json").write_text(json.dumps({"spiral-step": 20, "grid-step": 64}))
    model = d / "fake_ink_model.py"
    model.write_text(fakes.INK_MODEL)
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
    ok = status == WANT
    print("DEMO PASS" if ok else "DEMO FAIL: a stage did not end as expected; see state.json in the run folder")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
