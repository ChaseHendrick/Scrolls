"""Gather lane H score JSONs and per-phase timing into results.json (repo cloud-job row format)."""
import json, sys
from pathlib import Path
O, out = Path(sys.argv[1]), Path(sys.argv[2])
smoke = len(sys.argv) > 3 and sys.argv[3] not in ("", "0")
rows = []
for f in sorted((O / "scores").glob("*.json")):
    name = f.stem; shuf = name.endswith("_shuf"); base = name[:-5] if shuf else name
    model, seg = base.split("_", 1)
    rows.append({"job": "laneH-finetune", "segment": seg, "window": "crop", "inner_px": 64, "map_from": "bare-crop",
                 "reader": f"ink_9um s42 {'base' if model == 'base' else 'ft-' + model}",
                 "input": "depth-shuffled" if shuf else "as stored", "device": "cuda",
                 "smoke": smoke, "kit_auc": json.loads(f.read_text())})
timing = {}
for f in sorted((O / "timing").glob("*.jsonl")):
    ev = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    steps = {}
    for e in ev:
        steps.setdefault(e["step"], {})[e["event"]] = e["epoch_s"]
    timing[f.stem] = {k: {"seconds": v.get("end", 0) - v["start"] if "start" in v and "end" in v else None,
                          "start_epoch_s": v.get("start")} for k, v in steps.items()}
containers = [json.loads(p.read_text()) for p in sorted((O / "timing").glob("container_*.json"))]  # from modal_app.py
rows.append({"job": "laneH-finetune", "kind": "timing", "smoke": smoke, "phases": timing,
             "containers": containers})
out.write_text(json.dumps(rows, indent=1) + "\n")
print(f"{len(rows) - 1} score rows + timing -> {out}")
