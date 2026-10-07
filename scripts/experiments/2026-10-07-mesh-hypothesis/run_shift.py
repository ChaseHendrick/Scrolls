"""H5 (exploratory): in-plane shift between two renders of one segment, against the shift
predicted if the stored matrix is wrong and the landmark refit right.

Usage: python scripts/experiments/2026-10-07-mesh-hypothesis/run_shift.py CATALOGUE DEPTH_JSON OUT
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "scripts/experiments/2026-10-07-mesh-hypothesis")
from kit import meshaudit as ma  # noqa: E402
from run_geometry import mesh_for  # noqa: E402

CONTROLS = [("PHerc0139", "20260102150214", "20260413113053"),
            ("PHerc0814", "20260309142202", "20260521123630"),
            ("PHercParis4", "20260411134726", "20260608103018")]
TEST = ("PHerc1667", "20251217075048", "20260323082859")
N_TILES, MAX_CAND, PSR_MIN = 24, 300, 6.0


def stored_landmarks(cat, sid, a, b):
    """(src, dst) landmarks mapping a -> b, from whichever direction is stored."""
    vols = cat["samples"][sid]["volumes"]
    for t in vols[a]["properties"].get("transforms") or []:
        if t["to_volume_id"] == b and t.get("from_landmarks"):
            return np.array(t["from_landmarks"]), np.array(t["to_landmarks"])
    for t in vols[b]["properties"].get("transforms") or []:
        if t["to_volume_id"] == a and t.get("from_landmarks"):
            return np.array(t["to_landmarks"]), np.array(t["from_landmarks"])
    return None, None


def segments_with(cat, sid, a, b):
    out = []
    for gid, g in sorted(cat["samples"][sid]["segments"].items()):
        sv, _ = ma.segment_entries(g)
        vols = {ma._volume_id_in(x.split("/")[-1]) for x in sv}
        if {a, b} <= vols and mesh_for(g, a):
            out.append(gid)
    return out


def sv_path(seg, vid):
    for p in ma.segment_entries(seg)[0]:
        if ma._volume_id_in(p.split("/")[-1]) == vid:
            return p
    return None


def run_segment(cat, kind, sid, gid, a, b):
    t = time.time()
    seg = cat["samples"][sid]["segments"][gid]
    rec = {"kind": kind, "sample": sid, "segment_id": gid, "reference_volume": a, "cross_volume": b}
    stored, _ = ma.sample_matrix(cat, sid, a, b)
    src, dst = stored_landmarks(cat, sid, b, a)  # cross -> reference landmarks
    refit_b_to_a = ma.fit_affine(src, dst)
    px_a = cat["samples"][sid]["volumes"][a]["properties"]["pixel_size_um"]
    ref_xyz = ma.read_tifxyz("%s/%s" % (ma.BUCKET, mesh_for(seg, a)))
    sva = ma.SurfaceVolume("%s/%s" % (ma.BUCKET, sv_path(seg, a)))
    svb = ma.SurfaceVolume("%s/%s" % (ma.BUCKET, sv_path(seg, b)))
    rng = np.random.default_rng(ma.SEED)
    tiles = []
    tried = 0
    while len(tiles) < N_TILES and tried < MAX_CAND:
        u, v = (float(x) for x in rng.random(2))
        tried += 1
        pa = ma.centre_patch(sva, u, v)
        if pa is None:
            continue
        pb = ma.centre_patch(svb, u, v)
        if pb is None:
            continue
        (sy, sx), psr = ma.phase_shift(pa, pb)
        pred = ma.predicted_shift_um(ref_xyz, u, v, stored, refit_b_to_a, px_a)
        tiles.append({"u": round(u, 5), "v": round(v, 5), "psr": round(psr, 2),
                      "measured_um": [round(-sy * 10.0, 2), round(-sx * 10.0, 2)],
                      "predicted_um": None if pred is None else [round(pred[0], 2), round(pred[1], 2)],
                      "predicted_3d_um": None if pred is None else round(pred[2], 2)})
    rec["candidates_tried"] = tried
    rec["tiles"] = tiles
    good = [x for x in tiles if x["psr"] >= PSR_MIN and x["predicted_um"] is not None]
    rec["tiles_kept"] = len(good)
    if good:
        m = np.array([x["measured_um"] for x in good])
        p = np.array([x["predicted_um"] for x in good])
        rec["median_measured_um"] = float(np.median(np.linalg.norm(m, axis=1)))
        rec["median_predicted_um"] = float(np.median(np.linalg.norm(p, axis=1)))
        rec["median_error_vs_prediction_um"] = float(np.median(np.linalg.norm(m - p, axis=1)))
        rec["median_measured_vector_um"] = np.median(m, axis=0).round(2).tolist()
    rec["seconds"] = round(time.time() - t, 1)
    print(kind, sid, gid, rec.get("tiles_kept"), rec.get("median_measured_um"), rec.get("median_predicted_um"),
          rec.get("median_error_vs_prediction_um"), rec["seconds"], flush=True)
    return rec


def main(cat_path, depth_path, out_path):
    cat = ma.load_catalogue(cat_path)
    depth = json.load(open(depth_path))
    jobs = [("test", TEST[0], r["segment_id"], TEST[1], TEST[2]) for r in depth["results"] if r["kind"] == "H3b"]
    for sid, a, b in CONTROLS:
        segs = segments_with(cat, sid, a, b)
        pick = sorted(np.random.default_rng(ma.SEED).choice(segs, size=min(3, len(segs)), replace=False).tolist())
        jobs += [("control", sid, g, a, b) for g in pick]

    def safe(job):
        try:
            return run_segment(cat, *job)
        except Exception as e:  # noqa: BLE001
            print("ERROR", job, e, flush=True)
            return {"kind": job[0], "sample": job[1], "segment_id": job[2], "error": str(e)[:300]}

    with ThreadPoolExecutor(3) as ex:
        results = list(ex.map(safe, jobs))
    with open(out_path, "w") as f:
        json.dump({"psr_min": PSR_MIN, "tiles": N_TILES, "results": results}, f, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:4])
