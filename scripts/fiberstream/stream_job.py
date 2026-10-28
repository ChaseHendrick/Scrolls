"""HF Job: build the stream shards of one AFV Fibers dataset, check them against the whole-scan file, and (with
--upload) open a pull request on the public dataset with them, then check the hosted copy.

  python3 stream_job.py --code DIR --scan PHerc1667 --out DIR [--upload] [--smoke]

DIR (--code) holds kit/__init__.py, kit/fiberstream.py and tests/test_fiberstream.py from public Scrolls. Needs
numpy and huggingface_hub (in the image) and pyarrow (installed at start, pinned). Writes RESULT.json under --out.
Public data only: the six public datasets SharpMeow/<scan>-afv-fibers.

The boxes are fixed here, before any shard exists: from
the dataset's tiles/index.json (counts only), the centers of the 3 tiles with the most fibers and of 2 more drawn
with seed 0 among tiles with fibers; around each, a small box (32 grid voxels on a side), a medium box (256) and a
large box (1024); one 128-voxel box on the file corner nearest the densest tile's center (8 level-0 shard files meet
there); a control box outside the scan (it must hold no fiber); and the whole scan. Verdicts: PASS when every box's
fibers (ids, rows, blocks, bounds, points) and written .afv bytes equal the full file's, the whole scan's order-free
digest matches, the control is empty both ways, the 1 mm rule reproduces the published 1 mm file's curves, and the
dropped row group breaks parity; FAIL otherwise.
"""
import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

PYARROW = "pyarrow==21.0.0"
GRID = 256
FILE_CELLS = 4


def sh(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def setup(code):
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        sh([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", PYARROW])
    sys.path.insert(0, str(code))
    from kit import fiberstream
    return fiberstream


def boxes_for(tiles, f, shape_zyx, centers=None):
    """The fixed boxes, from tile counts only (or around given centers, for the smoke run)."""
    ts = [t for t in tiles["tiles"] if (t.get("fibres") or t.get("fibers") or 0) > 0]
    ts.sort(key=lambda t: (-(t.get("fibres") or t.get("fibers")), t["id"]))
    pick = ts[:3]
    rest = sorted(ts[3:], key=lambda t: t["id"])
    pick += random.Random(0).sample(rest, min(2, len(rest)))
    out = []
    cs = centers or [[(t["box_zyx_l0"][0] + t["box_zyx_l0"][1]) // 2, (t["box_zyx_l0"][2] + t["box_zyx_l0"][3]) // 2,
                      (t["box_zyx_l0"][4] + t["box_zyx_l0"][5]) // 2] for t in pick]
    for k, c in enumerate(cs):
        for name, edge in (("small", 32), ("medium", 256), ("large", 1024)):
            h = edge * f // 2
            out.append({"name": f"{name}-{k}", "kind": name, "box": [c[0] - h, c[0] + h, c[1] - h, c[1] + h,
                                                                       c[2] - h, c[2] + h]})
    step = GRID * FILE_CELLS * f
    c = [round(v / step) * step for v in cs[0]]
    h = 64 * f
    out.append({"name": "edge-0", "kind": "edge", "box": [c[0] - h, c[0] + h, c[1] - h, c[1] + h, c[2] - h, c[2] + h]})
    out.append({"name": "control", "kind": "control", "box": [-4096 * f, -2048 * f, 0, shape_zyx[1], 0, shape_zyx[2]]})
    return out


def tiles_bytes(tiles, box):
    """Bytes of the published per-cell tiles a box needs, by the AFV Fibers Space's rule (fibers.tiles_for)."""
    n = 0
    for t in tiles:
        b = t["box_zyx_l0"]
        if b[0] < box[1] and box[0] < b[1] and b[2] < box[3] and box[2] < b[3] and b[4] < box[5] and box[4] < b[5]:
            n += t["bytes"]
    return n


def geometry_digest(fibers):
    """Ordered digest of (family, points) only: the 1 mm file numbers its fibers again, so ids and rows differ."""
    h = hashlib.sha256()
    n = 0
    for x in fibers:
        h.update(x.family.encode())
        h.update(x.points.astype("<f8").tobytes())
        n += 1
    return h.hexdigest(), n


def _geo_multiset(fibers):
    s = n = 0
    for x in fibers:
        d = hashlib.sha256(x.family.encode() + x.points.astype("<f8").tobytes()).digest()
        s = (s + int.from_bytes(d, "big")) % (1 << 256)
        n += 1
    return s, n


def _ref_part(args):
    code, afv, lo, hi, min_len = args
    fs = setup(code)
    import sqlite3
    db = sqlite3.connect(f"file:{afv}?mode=ro", uri=True)
    s = g = n = 0
    try:
        ids = [r[0] for r in db.execute("SELECT id FROM fibers WHERE id >= ? AND id < ? ORDER BY id", (lo, hi))]
        for fid in ids:
            x = fs._fiber_from_db(db, fid, check=False)
            if min_len is not None and not x.length_mm >= min_len:
                continue
            s = (s + int.from_bytes(x.digest(), "big")) % (1 << 256)
            gd = hashlib.sha256(x.family.encode() + x.points.astype("<f8").tobytes()).digest()
            g = (g + int.from_bytes(gd, "big")) % (1 << 256)
            n += 1
    finally:
        db.close()
    return s, g, n


def _stream_part(args):
    code, local, paths, min_len = args
    fs = setup(code)
    src = fs.Source(local=local)
    idx = json.loads((Path(local) / fs.INDEX).read_text())
    idx["files"] = [e for e in idx["files"] if e["path"] in set(paths)]
    s = g = n = 0
    for part in fs.iter_stream(None, src, idx, min_len=min_len, threads=2):
        for x in part:
            s = (s + int.from_bytes(x.digest(), "big")) % (1 << 256)
            gd = hashlib.sha256(x.family.encode() + x.points.astype("<f8").tobytes()).digest()
            g = (g + int.from_bytes(gd, "big")) % (1 << 256)
            n += 1
    return s, g, n


def whole(code, afv, local, workers, min_len=None):
    """Order-free digests (rows and geometry) of every fiber, from the full file and from the shards, in parallel."""
    import sqlite3
    db = sqlite3.connect(f"file:{afv}?mode=ro", uri=True)
    lo, hi = db.execute("SELECT MIN(id), MAX(id) FROM fibers").fetchone()
    db.close()
    step = (hi - lo) // (workers * 4) + 1
    parts = [(str(code), str(afv), a, a + step, min_len) for a in range(lo, hi + 1, step)]
    idx = json.loads((Path(local) / "stream/index.json").read_text())
    paths = [e["path"] for e in sorted(idx["files"], key=lambda e: -e["bytes"])]
    groups = [paths[i::workers * 2] for i in range(workers * 2)]
    t0 = time.perf_counter()
    with ProcessPoolExecutor(workers) as pool:
        ref = list(pool.map(_ref_part, parts))
        t1 = time.perf_counter()
        got = list(pool.map(_stream_part, [(str(code), str(local), g, min_len) for g in groups if g]))
    t2 = time.perf_counter()

    def total(xs):
        return (f"{sum(x[0] for x in xs) % (1 << 256):064x}", f"{sum(x[1] for x in xs) % (1 << 256):064x}",
                sum(x[2] for x in xs))

    r, s = total(ref), total(got)
    return {"reference": r, "stream": s, "equal": r == s, "reference_s": round(t1 - t0, 1),
            "stream_s": round(t2 - t1, 1)}


def onemm_geometry(fs, path, boxes):
    """Per box, the ordered geometry digest of the published 1 mm file's fibers; and the whole file's order-free
    geometry digest."""
    out = {}
    for b in boxes:
        out[b["name"]] = geometry_digest(fs.read_afv(path, b["box"], check=False))
    s = n = 0
    for x in fs.read_afv(path, None, check=False):
        d = hashlib.sha256(x.family.encode() + x.points.astype("<f8").tobytes()).digest()
        s = (s + int.from_bytes(d, "big")) % (1 << 256)
        n += 1
    return out, (f"{s:064x}", n)


def download(repo, name, dest, revision=None):
    from huggingface_hub import hf_hub_download
    t0 = time.perf_counter()
    p = hf_hub_download(repo, name, repo_type="dataset", local_dir=str(dest), revision=revision)
    return Path(p), round(time.perf_counter() - t0, 1)


def check_box(fs, afv, src_info, local, b, tmp, **kw):
    got, st, src = fs.stream(b["box"], local=local, **kw)
    ref = list(fs.read_afv(afv, b["box"], **kw))
    a, r = tmp / "s.afv", tmp / "r.afv"
    fs.write_afv(got, a, src, box=b["box"], **kw)
    fs.write_afv(ref, r, src_info, box=b["box"], **kw)
    sa, sr = hashlib.sha256(a.read_bytes()).hexdigest(), hashlib.sha256(r.read_bytes()).hexdigest()
    rd = fs.records_digest(ref)
    return {"records_equal": fs.records_digest(got) == rd, "afv_equal": sa == sr, "fibers": rd[1],
            "reference_digest": rd[0], "afv_sha256": sr, "afv_bytes": r.stat().st_size,
            "local_bytes_read": st["bytes"], "row_groups": st["row_groups"], "files": st["files"],
            "geometry": geometry_digest(ref)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", type=Path, required=True)
    ap.add_argument("--scan", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--work", type=Path, default=Path("/tmp/fstream"))
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args(argv)
    os.environ.setdefault("HF_XET_CHUNK_CACHE_SIZE_BYTES", "0")
    fs = setup(a.code)
    res = {"scan": a.scan, "smoke": a.smoke, "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    a.out.mkdir(parents=True, exist_ok=True)
    rpath = a.out / f"{a.scan}{'-smoke' if a.smoke else ''}.json"

    def save():
        rpath.write_text(json.dumps(res, indent=1) + "\n")

    t = subprocess.run([sys.executable, "-m", "unittest", "tests.test_fiberstream", "-v"], cwd=a.code,
                       capture_output=True, text=True)
    res["unit_tests"] = {"exit": t.returncode, "tail": (t.stdout + t.stderr)[-3000:]}
    print(res["unit_tests"]["tail"], flush=True)
    save()
    if t.returncode != 0:
        res["verdict"] = "FAIL: unit tests"
        save()
        return 1
    s = fs.SCANS[a.scan]
    repo, f = s["repo"], 2 ** s["level"]
    work = a.work / a.scan
    work.mkdir(parents=True, exist_ok=True)
    tiles_path, _ = download(repo, "tiles/index.json", work)
    tiles = json.loads(tiles_path.read_text())
    full_name = f"{a.scan}_afv_v2.afv"
    if a.smoke:
        # the smallest tile with at least 1,000 fibers stands in for the whole scan
        tsel = min((t for t in tiles["tiles"] if (t.get("fibres") or 0) >= 1000), key=lambda t: t["bytes"])
        afv, dl_s = download(repo, f"tiles/{tsel['id']}.afv", work)
        shape = [tsel["box_zyx_l0"][1], tsel["box_zyx_l0"][3], tsel["box_zyx_l0"][5]]
        tiles = {"tiles": [tsel]}
        full_name = afv.name
    import sqlite3
    if not a.smoke:
        # the published 1 mm file: reference geometry for the boxes and the whole set, then deleted (disk)
        mm_path, mm_s = download(repo, f"{a.scan}_afv_v2_1mm.afv", work)
        db = sqlite3.connect(f"file:{mm_path}?mode=ro", uri=True)
        meta = dict(db.execute("SELECT key, value FROM metadata"))
        db.close()
        shape = json.loads(meta["root"])["coordinate_base_shape_zyx"]
        boxes = boxes_for(tiles, f, shape)
        res["boxes"] = boxes
        t0 = time.perf_counter()
        mm_boxes, mm_whole = onemm_geometry(fs, mm_path, [b for b in boxes if b["kind"] in ("medium", "control")])
        res["one_mm"] = {"file": mm_path.name, "bytes": mm_path.stat().st_size, "download_s": mm_s,
                         "boxes": mm_boxes, "whole": mm_whole, "read_s": round(time.perf_counter() - t0, 1)}
        mm_path.unlink()
        save()
        afv, dl_s = download(repo, full_name, work)
    else:
        db = sqlite3.connect(f"file:{afv}?mode=ro", uri=True)
        rows = db.execute("SELECT (min_z + max_z) / 2, (min_y + max_y) / 2, (min_x + max_x) / 2 FROM fibers").fetchall()
        db.close()
        mid = [int(sorted(r[i] for r in rows)[len(rows) // 2]) for i in range(3)]   # the median fiber center
        boxes = boxes_for(tiles, f, shape, centers=[mid])
        boxes = [b for b in boxes if b["kind"] in ("small", "medium", "edge", "control")]
        res["boxes"] = boxes
    res["full"] = {"file": afv.name, "bytes": afv.stat().st_size, "download_s": dl_s}
    save()
    t0 = time.perf_counter()
    local = work / "ds"
    idx = fs.build(afv, local, level=s["level"], scan=a.scan, workers=a.workers)
    res["build"] = {"seconds": round(time.perf_counter() - t0, 1), "totals": idx["totals"]}
    res["verify"] = fs.verify_build(local, afv)
    save()
    src_info = fs.afv_source_info(afv)
    tmp = work / "cmp"
    tmp.mkdir(exist_ok=True)
    res["local"] = {}
    for b in boxes:
        res["local"][b["name"]] = check_box(fs, afv, src_info, local, b, tmp)
        print(b["name"], res["local"][b["name"]]["fibers"], res["local"][b["name"]]["records_equal"], flush=True)
        save()
    med = [b for b in boxes if b["kind"] == "medium"]
    res["filters"] = {}
    for b in med[:2]:
        for kw in ({"family": "H"}, {"family": "V"}, {"min_len": 1.0}):
            k = f"{b['name']}:{json.dumps(kw, sort_keys=True)}"
            res["filters"][k] = check_box(fs, afv, src_info, local, b, tmp, **kw)
    save()
    # the check must be able to fail: leave out one row group the medium box reads
    b = med[0]
    st = {}
    src = fs.Source(local=local)
    full_idx = fs.open_index(src)
    got = [x for part in fs.iter_stream(b["box"], src, full_idx, stats=st) for x in part]
    drop = tuple(st["read"][0]) if st["read"] else None     # a row group this box reads, so it holds a fiber here
    dropped = [x for part in fs.iter_stream(b["box"], src, full_idx, skip={drop}) for x in part] if drop else got
    res["drop_control"] = {"dropped": drop, "full": fs.multiset_digest(got), "with_drop": fs.multiset_digest(dropped),
                           "caught": fs.multiset_digest(got) != fs.multiset_digest(dropped)}
    save()
    if not a.smoke:
        mm = {}
        for bb in [x for x in boxes if x["kind"] in ("medium", "control")]:
            g, _, _ = fs.stream(bb["box"], local=local, min_len=1.0)
            mm[bb["name"]] = {"stream": geometry_digest(g), "published": res["one_mm"]["boxes"][bb["name"]]}
            mm[bb["name"]]["equal"] = list(mm[bb["name"]]["stream"]) == list(mm[bb["name"]]["published"])
        res["one_mm"]["parity"] = mm
        save()
    res["whole"] = whole(a.code, afv, local, a.workers)
    save()
    if not a.smoke:
        w1 = whole(a.code, afv, local, a.workers, min_len=1.0)
        res["one_mm"]["whole_parity"] = {"stream_geometry": w1["stream"][1], "stream_count": w1["stream"][2],
                                         "published": res["one_mm"]["whole"],
                                         "equal": [w1["stream"][1], w1["stream"][2]] == list(res["one_mm"]["whole"]),
                                         "reference_equal": w1["equal"]}
        save()
    ok = (t.returncode == 0 and res["verify"]["ok"] and all(v["records_equal"] and v["afv_equal"]
                                                             for v in list(res["local"].values()) +
                                                             list(res["filters"].values()))
          and res["local"]["control"]["fibers"] == 0 and res["whole"]["equal"] and res["drop_control"]["caught"])
    if not a.smoke:
        ok = ok and all(v["equal"] for v in res["one_mm"]["parity"].values()) and res["one_mm"]["whole_parity"]["equal"]
    res["local_verdict"] = "PASS" if ok else "FAIL"
    save()
    if a.upload and ok and not a.smoke:
        from huggingface_hub import HfApi
        api = HfApi()
        t0 = time.perf_counter()
        info = api.upload_folder(repo_id=repo, repo_type="dataset", folder_path=str(local), allow_patterns=["stream/**"],
                                 create_pr=True, commit_message=f"Stream shards for {a.scan} (format afv-stream 1)",
                                 commit_description="Parquet shards and stream/index.json so a box of fibers can be "
                                 "read without the whole file: python -m kit fibers stream (github.com/ChaseHendrick/"
                                 "Scrolls). Same fibers as the whole-scan .afv; existing files unchanged.")
        res["upload"] = {"seconds": round(time.perf_counter() - t0, 1), "pr_url": getattr(info, "pr_url", None),
                         "pr_revision": getattr(info, "pr_revision", None), "commit": getattr(info, "oid", None)}
        save()
        rev = res["upload"]["pr_revision"]
        hosted = {}
        tiles_all = json.loads(tiles_path.read_text())["tiles"]
        for b in boxes:
            t0 = time.perf_counter()
            got, st, _ = fs.stream(b["box"], repo=repo, revision=rev)
            secs = time.perf_counter() - t0
            tb = tiles_bytes(tiles_all, b["box"])
            hosted[b["name"]] = {"records_equal": fs.records_digest(got)[0] == res["local"][b["name"]]["reference_digest"],
                                 "fibers": len(got), "bytes": st["bytes"], "requests": st["requests"],
                                 "seconds": round(secs, 2), "tiles_bytes": tb}
            print("hosted", b["name"], hosted[b["name"]], flush=True)
            res["hosted"] = hosted
            save()
        # the whole hosted copy, without downloading it: every shard's size and sha256 as the Hub lists them
        listed = {}
        for e in api.list_repo_tree(repo, path_in_repo="stream", recursive=True, revision=rev, repo_type="dataset",
                                    expand=True):
            if getattr(e, "size", None) is not None:
                lfs = getattr(e, "lfs", None)
                listed[e.path] = (e.size, (lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)))
        want = {e["path"]: (e["bytes"], e["sha256"]) for e in idx["files"]}
        res["hosted_files"] = {"listed": len(listed), "expected": len(want) + 1,
                               "mismatch": sorted(p for p, v in want.items() if listed.get(p) != v)}
        res["hosted_verdict"] = "PASS" if (all(v["records_equal"] for v in hosted.values())
                                           and not res["hosted_files"]["mismatch"]) else "FAIL"
        save()
    res["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save()
    print(json.dumps({k: res.get(k) for k in ("scan", "local_verdict", "hosted_verdict", "upload")}), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
