"""Gather lane H score JSONs into results.json rows (repo cloud-job row format) and apply the readout rule."""
import json, sys
from pathlib import Path
O, out = Path(sys.argv[1]), Path(sys.argv[2])
rows = []
for f in sorted((O / "scores").glob("*.json")):
    name = f.stem; shuf = name.endswith("_shuf"); base = name[:-5] if shuf else name
    model, seg = base.split("_", 1)
    r = json.loads(f.read_text())
    rows.append({"job": "laneH-finetune", "segment": seg, "window": "crop", "inner_px": 64, "map_from": "bare-crop",
                 "reader": f"ink_9um s42 {'base' if model == 'base' else 'ft-' + model}",
                 "input": "depth-shuffled" if shuf else "as stored", "device": "cuda", "kit_auc": r})
out.write_text(json.dumps(rows, indent=1) + "\n")
print(f"{len(rows)} rows -> {out}")
