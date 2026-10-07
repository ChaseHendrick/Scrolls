"""Run H3 (seeded plan) and H3b (PHerc1667 cross-vs-cross) from docs/plans/2026-10-07-mesh-hypothesis.md.

Usage: python scripts/experiments/2026-10-07-mesh-hypothesis/run_depth.py CATALOGUE PLAN OUT
Writes one JSON with every segment-pair result; derived numbers only.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, ".")
from kit import meshaudit as ma  # noqa: E402

H3B = {"sample": "PHerc1667", "reference": "20251217075048", "cross": "20260323082859"}


def main(cat_path, plan_path, out_path):
    cat = ma.load_catalogue(cat_path)
    plan = json.load(open(plan_path))
    jobs = []
    for p in plan:
        for gid in p["segments"]:
            jobs.append(("H3", p["sample"], gid, [p["cross_volume"]], None))
    s = cat["samples"][H3B["sample"]]
    elig = []
    for gid, g in sorted(s["segments"].items()):
        sv, _ = ma.segment_entries(g)
        vols = {ma._volume_id_in(x.split("/")[-1]) for x in sv}
        if {H3B["reference"], H3B["cross"]} <= vols:
            elig.append(gid)
    rng = np.random.default_rng(ma.SEED)
    pick = sorted(rng.choice(elig, size=min(5, len(elig)), replace=False).tolist())
    for gid in pick:
        jobs.append(("H3b", H3B["sample"], gid, [H3B["cross"]], H3B["reference"]))

    def run(job):
        kind, sid, gid, cross, ref = job
        t = time.time()
        r = ma.depth_segment(ma.BUCKET, sid, cat["samples"][sid]["segments"][gid], cross_ids=cross,
                             n_tiles=32, seed=ma.SEED, reference=ref)
        r["kind"] = kind
        r["segment_id"] = gid
        r["seconds"] = round(time.time() - t, 1)
        print(kind, sid, gid, cross, [(p.get("delta_median_um"), p.get("location_control_pass")) for p in r["pairs"]],
              r["seconds"], flush=True)
        return r

    with ThreadPoolExecutor(3) as ex:
        results = list(ex.map(run, jobs))
    out = {"catalogue_sha256_note": "see docs/data/mesh-hypothesis/README.md", "h3b_eligible": len(elig),
           "results": results}
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:4])
