"""Run the preregistered Ink Lens control check (docs/prereg/2026-10-20-ink-lens-gate.md) on public data.

  python3 tools/check_gate.py OUT.json [--maps DIR] [--device cpu]

Needs torch, zarr and this repository's kit (labels); downloads villa at the pinned commit and d9v2 (or uses
VILLA_SRC and INKLENS_D9V2). Writes one JSON with every number and the pass or fail of each check. Maps are saved
only with --maps, outside git.
"""

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import engine  # noqa: E402
import gate  # noqa: E402
import inklens  # noqa: E402

CROPS = ("0841-w00", "0841-ag896", "0841-ag405")
OFF = ("0841-w00", (0, 0))          # rows 0..640, columns 0..640 of w00: the segment's corner


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out")
    ap.add_argument("--maps")
    ap.add_argument("--device", default=None)
    a = ap.parse_args(argv)
    import numpy as np
    inklens.find_kit()
    from kit import auc
    t0 = time.time()
    eng = engine.Engine(readers=("d9v2",))
    report = {"prereg": "docs/prereg/2026-10-20-ink-lens-gate.md", "rule": gate.RULE_ID, "reader": "d9v2",
              "windows": 3, "engine": eng.describe(), "crops": {}, "swapped": {}, "no_papyrus": {},
              "note": "Development numbers on windows chosen with the labels, not a blind test. Model output, not a "
                      "reading."}
    for sid in CROPS:
        s = inklens.sample_by(sid)
        box = inklens.sample_box(s)
        vol, src = inklens.read_sample(s, box)
        run = eng.run(vol, "d9v2", windows=3, device=a.device)
        F, R = run["forward"], run["reverse"]
        d, kept, _ = inklens.analyze(F, R, vol)
        ink, sup = inklens.labels_for(s, box, F.shape)
        shares = gate.label_shares(kept, ink, sup)
        row = {"box": list(box), "gate": d, "label_shares": shares,
               "auc_forward": auc.score_array(F, ink, sup, inner=64)["auc"],
               "auc_reverse": auc.score_array(R, ink, sup, inner=64)["auc"],
               "patches": run["patches"], "seconds": run["seconds"], "device": run["device"]}
        row["pass"] = d["status"] == "ink" and bool(shares["ink_share_larger"])
        report["crops"][sid] = row
        sw = gate.decide(R, F, inklens.ct_middle(vol))
        report["swapped"][sid] = {"gate": sw, "pass": sw["status"] != "ink"}
        if a.maps:
            Path(a.maps).mkdir(parents=True, exist_ok=True)
            np.savez_compressed(Path(a.maps) / f"{sid}.npz", forward=F, reverse=R, kept=kept, ct=inklens.ct_middle(vol))
        print(sid, d["status"], d["excess"], shares, row["auc_forward"], row["auc_reverse"], "swapped", sw["status"],
              flush=True)
    sid, at = OFF
    s = inklens.sample_by(sid)
    box = inklens.sample_box(s, 640, at)
    vol, _ = inklens.read_sample(s, box)
    try:
        run = eng.run(vol, "d9v2", windows=3, device=a.device)
        d, _, _ = inklens.analyze(run["forward"], run["reverse"], vol)
        report["no_papyrus"] = {"box": list(box), "gate": d, "refused": None,
                                "nonzero_ct_share": round(float((vol > 0).mean()), 4)}
        ok = d["status"] in ("none", "too_small", "unreadable")
    except engine.EngineError as exc:
        report["no_papyrus"] = {"box": list(box), "gate": None, "refused": str(exc)}
        ok = True
    report["no_papyrus"]["pass"] = ok
    print("no papyrus", report["no_papyrus"].get("gate", {}) and report["no_papyrus"]["gate"]["status"],
          report["no_papyrus"].get("refused"), flush=True)
    report["pass"] = {"labeled_crops": all(r["pass"] for r in report["crops"].values()),
                      "swapped": all(r["pass"] for r in report["swapped"].values()), "no_papyrus": ok}
    report["pass"]["all"] = all(report["pass"].values())
    report["wall_seconds"] = round(time.time() - t0, 1)
    Path(a.out).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report["pass"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
