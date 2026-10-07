"""H4 (exploratory): are published cross-scan meshes the affine image of the reference mesh?

Usage: python scripts/experiments/2026-10-07-mesh-hypothesis/run_geometry.py CATALOGUE DEPTH_JSON OUT
Uses the segment pairs that H3/H3b ran (from DEPTH_JSON). Derived numbers only.
"""
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")
from kit import meshaudit as ma  # noqa: E402

LIMIT = 40 * 1024 * 1024


def size(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers.get("Content-Length", 0))


def mesh_for(seg, vid):
    for typ, p in ma.segment_entries(seg)[1]:
        if typ == "tifxyz-transformed" and ("-on-%s-" % vid) in p:
            return p
    return None


def main(cat_path, depth_path, out_path):
    cat = ma.load_catalogue(cat_path)
    depth = json.load(open(depth_path))
    jobs = []
    for r in depth["results"]:
        for p in r["pairs"]:
            jobs.append((r["kind"], r["sample"], r["segment_id"], r["native_volume"], p["cross_volume"]))

    def run(job):
        kind, sid, gid, ref, cross = job
        seg = cat["samples"][sid]["segments"][gid]
        rec = {"kind": kind, "sample": sid, "segment_id": gid, "reference_volume": ref, "cross_volume": cross}
        t = time.time()
        try:
            mr, mc = mesh_for(seg, ref), mesh_for(seg, cross)
            if not mr or not mc:
                rec["skipped"] = "no transformed mesh variant for %s" % ("reference" if not mr else "cross")
                return rec
            sizes = [size("%s/%s/x.tif" % (ma.BUCKET, m)) for m in (mr, mc)]
            rec["x_tif_bytes"] = sizes
            if max(sizes) > LIMIT:
                rec["skipped"] = "mesh TIFF over 40 MB"
                return rec
            m, path = ma.sample_matrix(cat, sid, ref, cross)
            if m is None:
                rec["skipped"] = "no sample-level matrix"
                return rec
            rec["derivation_path"] = path
            px = cat["samples"][sid]["volumes"][cross]["properties"]["pixel_size_um"]
            ref_xyz = ma.read_tifxyz("%s/%s" % (ma.BUCKET, mr))
            cross_xyz = ma.read_tifxyz("%s/%s" % (ma.BUCKET, mc))
            rec["grids"] = [list(ref_xyz.shape[:2]), list(cross_xyz.shape[:2])]
            rec.update(ma.affine_residuals(ref_xyz, cross_xyz, m, px))
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
        rec["seconds"] = round(time.time() - t, 1)
        print(kind, sid, gid, ref, cross, rec.get("normal_median_um"), rec.get("normal_p90_um"),
              rec.get("skipped") or rec.get("error") or "", flush=True)
        return rec

    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(run, jobs))
    with open(out_path, "w") as f:
        json.dump({"results": results}, f, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:4])
