"""Add the level-0 shape of each 9 um surface volume to inventory_mrg.py's output (reads only the
`0/.zarray` metadata file of each zarr) and print totals per scroll.

    python inventory_shapes.py MRG.json OUT.json
"""
import json
import re
import sys
import urllib.request
from collections import defaultdict

BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
# Held out or otherwise not for training (see docs/plans/2026-10-07-training.md and the
# nestorvfx pretraining set's evaluation segments).
EXCLUDE = {("PHerc0139", "w045"): "held-out test segment",
           ("PHerc0139", "w016"): "nestorvfx evaluation segment",
           ("PHerc0814", "46527"): "nestorvfx evaluation segment",
           ("PHerc1667", "w029"): "nestorvfx evaluation segment"}


def main():
    src, out = sys.argv[1], sys.argv[2]
    data = json.load(open(src))
    totals = defaultdict(lambda: {"segments": 0, "excluded": 0, "cm2": 0.0, "bytes_9um": 0, "bytes_mrg": 0})
    for row in data["rows"]:
        # Recomputed here: an earlier inventory_mrg.py regex also matched 2.399um volumes.
        row["surface_9um"] = [p for p in row["surface_volumes"] if re.search(r"/9\.\d+um-[^/]*/$", p)]
        if not row["surface_9um"]:
            row["exclude"] = "no 9 um surface volume"
            totals[row["scroll"]]["excluded"] += 1
            continue
        zarr = row["surface_9um"][0]
        with urllib.request.urlopen(f"{BUCKET}/{zarr}0/.zarray", timeout=60) as r:
            meta = json.load(r)
        depth, h, w = meta["shape"]
        um = float(zarr.rstrip("/").split("/")[-1].split("um")[0])
        row["shape_9um"] = meta["shape"]
        row["compressor"] = meta["compressor"]
        row["area_cm2_bbox"] = round(h * w * (um * 1e-4) ** 2, 2)
        row["bytes_9um_level0_max"] = depth * h * w
        name = row["segment"].rstrip("/").split("/")[-1]
        why = [v for (scroll, token), v in EXCLUDE.items() if scroll == row["scroll"] and token in name]
        row["exclude"] = why[0] if why else None
        t = totals[row["scroll"]]
        if why:
            t["excluded"] += 1
            continue
        t["segments"] += 1
        t["cm2"] += row["area_cm2_bbox"]
        t["bytes_9um"] += row["bytes_9um_level0_max"]
        t["bytes_mrg"] += sum(m["bytes"] for m in row["mrg"])
    data["totals"] = totals
    json.dump(data, open(out, "w"), indent=1)
    for k, t in totals.items():
        print(k, t["segments"], "used,", t["excluded"], "excluded,", round(t["cm2"], 1), "cm2 bbox,",
              round(t["bytes_9um"] / 1e9, 2), "GB 9um level 0 (max),", round(t["bytes_mrg"] / 1e9, 2), "GB mrg")


if __name__ == "__main__":
    main()
