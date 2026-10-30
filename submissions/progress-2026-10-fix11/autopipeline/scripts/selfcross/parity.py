"""Parity of AutoPipeline's two self-intersection backends: villa's vc_tifxyz_selfcross and the kernel backend
(kit/selfcross.py), on the synthetic surfaces of tests/selfcross_fixtures.py, through kit's own resolver.

  VC_APPIMAGE=VC3D-7154682-....AppImage python3 scripts/selfcross/parity.py OUT [--random 40]

Needs a VC3D build that still has vc_tifxyz_selfcross (villa 7154682e1 or older; VC_APPIMAGE or VC_BIN) and a built
kernel backend (`python -m kit selfcross build`). Writes OUT/parity.json: per surface both reports' counts and what
differs, comparing clean, grid size, parameters, triangles, dropped quads, pairs tested, the three counts on both
diagonals, the contact lists (quads and triangles, in order) and each contact's penetration, angle and site (to
1e-9). Two controls must differ, or the comparison could not have failed: the kernel fed the grid with mask.tif
ignored, and fed it with x = -1 cells also invalidated (a rule VC3D's loader does not have). Exit 0 when every
surface matches and both controls differ on at least one surface.
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kit import selfcross, vc3d  # noqa: E402
import selfcross_fixtures as fx  # noqa: E402


def key(c):
    return (tuple(c["quad1"]), tuple(c["quad2"]), c["tri1"], c["tri2"])


def compare(a, b):
    diffs = []
    for k in ("clean_of_transverse_self_intersection", "grid_rows", "grid_cols"):
        if a.get(k) != b.get(k):
            diffs.append(f"{k}: {a.get(k)} vs {b.get(k)}")
    for k in ("exclude", "maxedge", "cell", "touch_tolerance", "diagonals"):
        if a["parameters"].get(k) != b["parameters"].get(k):
            diffs.append(f"parameters.{k}: {a['parameters'].get(k)} vs {b['parameters'].get(k)}")
    for da, db in zip(a["census"], b["census"]):
        d = da.get("diagonal")
        for k in ("diagonal", "triangles", "quads_dropped_for_edge_length", "pairs_tested", "transverse", "coplanar",
                  "grazing"):
            if da.get(k) != db.get(k):
                diffs.append(f"d{d}.{k}: {da.get(k)} vs {db.get(k)}")
        ca, cb = da["transverse_contacts"], db["transverse_contacts"]
        if [key(c) for c in ca] != [key(c) for c in cb]:
            diffs.append(f"d{d} contact lists differ ({len(ca)} vs {len(cb)})")
            continue
        for x, y in zip(ca, cb):
            for k in ("penetration_vx", "angle_deg"):
                if abs(x[k] - y[k]) > 1e-9 * max(1.0, abs(x[k])):
                    diffs.append(f"d{d} {k} {x[k]} vs {y[k]}")
            if max(abs(p - q) for p, q in zip(x["site"], y["site"])) > 1e-9:
                diffs.append(f"d{d} site {x['site']} vs {y['site']}")
    return diffs


def control(folder, rep, binary, rule):
    """The kernel on the grid loaded with a wrong rule (the controls)."""
    import numpy as np
    from kit import meshqa
    p = meshqa.load_patch(folder)
    xyz = np.stack([p.x, p.y, p.z], axis=-1).astype(np.float32)
    with np.errstate(invalid="ignore"):
        bad = p.z <= 0
    mask, _ = p.mask_valid()
    if rule == "x_minus_one_invalid":
        if mask is not None:
            bad |= ~mask
        bad |= p.x == -1
    elif rule != "mask_ignored":
        raise ValueError(rule)
    xyz[bad] = -1.0
    real = selfcross.load_grid
    selfcross.load_grid = lambda _s: np.ascontiguousarray(xyz)
    try:
        return selfcross.run_kernel(folder, rep, threads=2, binary=binary)
    finally:
        selfcross.load_grid = real


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out")
    ap.add_argument("--random", type=int, default=40, help="random crumpled sheets beside the named ones")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tools = vc3d.find_tools()
    if not selfcross.villa_has(tools):
        print(f"no {selfcross.VILLA_TOOL} in {tools.describe()}: set VC_APPIMAGE to a 7154682e1 or older build",
              file=sys.stderr)
        return 2
    binary, rec = selfcross.kernel_binary()
    if binary is None:
        print(f"no kernel backend: {rec}", file=sys.stderr)
        return 2
    rows, t0 = [], time.time()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name, (grid, mask) in {**fx.named(), **fx.random(a.random)}.items():
            folder = fx.write(tmp / f"{name}.tifxyz", grid, mask)
            v = selfcross.census(folder, out / f"{name}.villa.json", backend="villa", tools=tools, threads=2)
            k = selfcross.census(folder, out / f"{name}.kernel.json", backend="kernel", tools=tools, threads=2)
            if "parsed" not in v or "parsed" not in k:
                diffs = [f"no report: villa {v.get('error')}, kernel {k.get('error')}"]
                rep_v = None
            else:
                rep_v = v["parsed"]
                diffs = compare(rep_v, k["parsed"])
            ctl = {}
            for rule in ("mask_ignored", "x_minus_one_invalid"):
                c = control(folder, tmp / f"{name}.{rule}.json", binary, rule)
                ctl[rule] = bool(rep_v is not None and compare(rep_v, c))
            rows.append({"name": name, "villa_exit": v.get("exit"), "kernel_exit": k.get("exit"),
                         "villa_counts": fx.counts(rep_v) if rep_v else None, "diffs": diffs, "controls_differ": ctl,
                         "expected": fx.VILLA.get(name)})
            if name in fx.VILLA and rep_v is not None and fx.counts(rep_v) != fx.VILLA[name]:
                rows[-1]["diffs"].append(f"villa counts {fx.counts(rep_v)} are not the fixture's recorded "
                                         f"{fx.VILLA[name]}")
            print(f"{name:20s} villa {v.get('exit')} kernel {k.get('exit')} {rows[-1]['villa_counts']} "
                  f"{'MATCH' if not rows[-1]['diffs'] else 'DIFF ' + '; '.join(rows[-1]['diffs'][:3])}")
    bad = sum(1 for r in rows if r["diffs"])
    crossing = sum(1 for r in rows if r["villa_counts"] and sum(r["villa_counts"][0]))
    ctl = {rule: sum(1 for r in rows if r["controls_differ"][rule]) for rule in ("mask_ignored", "x_minus_one_invalid")}
    summary = {"surfaces": len(rows), "crossing": crossing, "differ": bad, "controls_differ": ctl,
               "villa": tools.describe(), "kernel": rec, "seconds": round(time.time() - t0, 1)}
    (out / "parity.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1) + "\n")
    print(f"{len(rows)} surfaces, {crossing} with transverse contacts, {bad} differ; controls differ on "
          f"{ctl['mask_ignored']} (mask ignored) and {ctl['x_minus_one_invalid']} (x = -1 invalidated)")
    return 0 if bad == 0 and all(ctl.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
