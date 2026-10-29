"""Join per-region AFV files into one whole-scan AFV: clip each region's curves to its core, match the pieces that meet
on a shared core face, join them, keep unmatched continuations that no neighbor covers, then drop fibers that touch
the outside of the scroll.

  python3 afv_stitch.py stitch --plan PLAN.json --regions DIR --out SCAN.afv [--tol 1.5] [--exterior EXTERIOR.npz]
        [--min-mm 0]
  python3 afv_stitch.py exterior --plan PLAN.json --out EXTERIOR.npz   (exterior-connected empty space, coarse cells)

Why: AVF_SPLINE_GENERATOR traces through one global prediction array, which does not fit a job for a whole scroll
(about 18 bytes per tracing voxel). A runner script runs it per 1,024^3 region with a 128-voxel halo and seeds only in the
core. The probabilities are identical in every region (the windows sit on one global lattice, each normalized by
itself), so the same fiber traced from two neighboring cores crosses their shared face at nearly the same point; this
step joins such crossings (same family, within `tol` voxels, directions within 45 degrees). A crossing with no partner
keeps the part of its curve beyond the face until that part comes within `tol` of a neighbor's curve of the same family.
Exterior: like Qual's CT exterior cleaning of his Paris 4 V2 set, a fiber is dropped when any point lies in or next to
an empty 16-voxel cell connected to the scan's border (an approximation of his exact 16-voxel distance rule).
With `--exterior-mode trim` the fiber is cut where it enters such a cell and its inside runs are kept ("exterior_removed"
then counts the fibers cut).
"""
import argparse
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np


def read_afv(path):
    """[(family, (N, 3) xyz float64)] of every fibre in an AFV file."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    fibres = {}
    fam = dict(db.execute("SELECT id, family FROM fibers"))
    for fid, first, blob in db.execute("SELECT fiber_id, first_segment, points FROM blocks ORDER BY fiber_id, first_segment"):
        p = np.frombuffer(blob, "<f8").reshape(-1, 3)
        if fid in fibres:
            fibres[fid].append(p[1:])
        else:
            fibres[fid] = [p]
    db.close()
    return [(fam[k], np.concatenate(v)) for k, v in fibres.items()]


def crossing(a, b, lo, hi, a_inside):
    """Point where segment a->b leaves (a inside) or enters (a outside) the box [lo, hi) (slab method)."""
    d = b - a
    if a_inside:
        t = 1.0
        for ax in range(3):
            if d[ax] > 0 and b[ax] >= hi[ax]:
                t = min(t, (hi[ax] - a[ax]) / d[ax])
            elif d[ax] < 0 and b[ax] < lo[ax]:
                t = min(t, (lo[ax] - a[ax]) / d[ax])
    else:
        t = 0.0
        for ax in range(3):
            if d[ax] > 0 and a[ax] < lo[ax]:
                t = max(t, (lo[ax] - a[ax]) / d[ax])
            elif d[ax] < 0 and a[ax] >= hi[ax]:
                t = max(t, (hi[ax] - a[ax]) / d[ax])
    return a + t * d


def clip(points, lo, hi):
    """Split a polyline at the faces of the box [lo, hi) (xyz). Returns [(inside: bool, pts)], consecutive runs; the
    runs on either side of a face share the exact crossing point."""
    inside = ((points >= lo) & (points < hi)).all(1)
    flips = np.flatnonzero(inside[1:] != inside[:-1]) + 1
    if not len(flips):
        return [(bool(inside[0]), points)] if len(points) >= 2 else []
    runs, start, q_prev = [], 0, None
    for i in flips:
        q = crossing(points[i - 1], points[i], lo, hi, bool(inside[i - 1]))
        body = points[start:i]
        run = np.vstack(([q_prev] if q_prev is not None else []) + [body, q[None]]) if q_prev is not None \
            else np.vstack([body, q[None]])
        runs.append((bool(inside[i - 1]), run))
        start, q_prev = i, q
    runs.append((bool(inside[-1]), np.vstack([q_prev[None], points[start:]])))
    return [(k, r) for k, r in runs if len(r) >= 2]


def face_of(q, lo, hi, eps=1e-3):
    for ax in range(3):
        if abs(q[ax] - lo[ax]) < eps:
            return ax, -1
        if abs(q[ax] - hi[ax]) < eps:
            return ax, 1
    return None


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def end_dir(p, at_end, k=6):
    """Outward direction at one end of a polyline from the last k points."""
    if at_end:
        return unit(p[-1] - p[max(0, len(p) - 1 - k)])
    return unit(p[0] - p[min(len(p) - 1, k)])


def exterior_runs(pts, ext, cell, min_pts=2):
    """--exterior-mode trim: the runs of a fibre's points (xyz, native voxels) outside exterior cells, each at least
    min_pts points; the fibre is cut where it enters the scroll's outside instead of being dropped whole."""
    c = np.clip((np.asarray(pts)[:, ::-1] // cell).astype(int), 0, np.array(ext.shape) - 1)
    bad = ext[c[:, 0], c[:, 1], c[:, 2]].astype(bool)
    if not bad.any():
        return [pts]
    runs, start = [], None
    for i, b in enumerate(np.r_[bad, True]):
        if not b and start is None:
            start = i
        elif b and start is not None:
            if i - start >= min_pts:
                runs.append(pts[start:i])
            start = None
    return runs


def stitch(plan, regions_dir, tol=1.5, exterior=None, say=print, exterior_mode="drop"):
    from scipy.spatial import cKDTree
    t0 = time.time()
    shape = np.array(plan["shape_zyx"])
    cores = {t["id"]: t["core"] for t in plan["tiles"]}
    pieces = []          # dicts: family, pts (inside the core), region, ends: {0/1: {face, ext}}
    missing = []
    for tid, core in cores.items():
        f = Path(regions_dir) / f"{tid}.afv"
        meta = Path(regions_dir) / f"{tid}.afv.json"
        if not f.exists():
            if meta.exists() and json.loads(meta.read_text()).get("empty"):
                continue
            missing.append(tid)
            continue
        z0, z1, y0, y1, x0, x1 = core
        lo = np.array([x0, y0, z0], float)
        hi = np.array([min(x1, shape[2]), min(y1, shape[1]), min(z1, shape[0])], float)
        for fam, pts in read_afv(f):
            runs = clip(pts, lo, hi)
            for i, (ins, r) in enumerate(runs):
                if not ins:
                    continue
                ends = {}
                for side, at_end in ((0, False), (1, True)):
                    q = r[-1] if at_end else r[0]
                    fc = face_of(q, lo, hi)
                    if fc is None:
                        continue
                    j = i + (1 if at_end else -1)
                    ext = runs[j][1] if 0 <= j < len(runs) and not runs[j][0] else None
                    if ext is not None and not at_end:
                        ext = ext[::-1]              # always ordered from the face outward
                    ends[side] = {"face": fc, "q": q, "ext": ext, "dir": end_dir(r, at_end)}
                pieces.append({"family": fam, "pts": r, "region": tid, "ends": ends})
    say(f"{len(pieces)} core pieces from {len(cores) - len(missing)} regions; missing {len(missing)}")
    # match crossings: every (piece, side) with a face, grouped by family; partners lie in another region, at the
    # same point, pointing the opposite way
    links = {}
    for fam in ("V", "H"):
        ends = [(pi, s) for pi, p in enumerate(pieces) if p["family"] == fam for s in p["ends"]]
        if not ends:
            continue
        Q = np.array([pieces[pi]["ends"][s]["q"] for pi, s in ends])
        tree = cKDTree(Q)
        cand = []
        for a, b in tree.query_pairs(tol):
            (pa, sa), (pb, sb) = ends[a], ends[b]
            if pieces[pa]["region"] == pieces[pb]["region"]:
                continue
            da, db = pieces[pa]["ends"][sa]["dir"], pieces[pb]["ends"][sb]["dir"]
            if np.dot(da, -db) < np.cos(np.radians(45)):
                continue
            cand.append((float(np.linalg.norm(Q[a] - Q[b])), (pa, sa), (pb, sb)))
        for _, ea, eb in sorted(cand):
            if ea in links or eb in links:
                continue
            links[ea], links[eb] = eb, ea
    # unmatched crossings keep their continuation until it meets a neighbour's curve of the same family
    trees = {}
    regions = sorted(cores)
    rix = {r: k for k, r in enumerate(regions)}
    for fam in ("V", "H"):
        sel = [p for p in pieces if p["family"] == fam]
        if sel:
            trees[fam] = (cKDTree(np.concatenate([p["pts"] for p in sel])),
                          np.concatenate([np.full(len(p["pts"]), rix[p["region"]]) for p in sel]))
    kept_ext = 0
    for pi, p in enumerate(pieces):
        for s, e in p["ends"].items():
            if (pi, s) in links or e["ext"] is None or len(e["ext"]) < 2:
                e["keep"] = None
                continue
            ext = e["ext"][1:]
            # the continuation stops where it reaches a curve another region traced (its own region's curves are
            # inside its core, so they are skipped)
            tree, lab = trees[p["family"]]
            own = rix[p["region"]]
            hit = [any(lab[k] != own for k in ks) for ks in tree.query_ball_point(ext, tol)]
            cut = np.flatnonzero(hit)
            n = int(cut[0]) if len(cut) else len(ext)
            e["keep"] = ext[:n] if n > 0 else None
            kept_ext += int(n > 0)
    # chains of linked pieces
    seen = set()
    fibres = []
    for start in range(len(pieces)):
        if start in seen:
            continue
        # walk to one end of the chain
        cur, side = start, 0
        guard = 0
        while (cur, side) in links and guard < 100000:
            nxt, nside = links[(cur, side)]
            cur, side = nxt, 1 - nside
            guard += 1
            if cur == start:
                break
        # cur's `side` end is a chain end: emit from there
        chain, a, s_in = [], cur, side
        while True:
            seen.add(a)
            seg = pieces[a]["pts"] if s_in == 0 else pieces[a]["pts"][::-1]
            chain.append((a, s_in, seg))
            out_side = 1 - s_in
            if (a, out_side) not in links:
                break
            b, bs = links[(a, out_side)]
            if b in seen:
                break
            a, s_in = b, bs
        parts = []
        a0, s0, _ = chain[0]
        e0 = pieces[a0]["ends"].get(s0)
        if e0 is not None and e0.get("keep") is not None:
            parts.append(e0["keep"][::-1])
        for k, (a, s_in, seg) in enumerate(chain):
            parts.append(seg if k == 0 else seg[1:])
        a1, s1, _ = chain[-1]
        e1 = pieces[a1]["ends"].get(1 - s1)
        if e1 is not None and e1.get("keep") is not None:
            parts.append(e1["keep"])
        pts = np.concatenate(parts)
        fibres.append((pieces[start]["family"], pts))
    fibres, rejoined = join_near_faces(fibres, cores, shape, tol)
    removed = 0
    if exterior is not None:
        z = np.load(exterior)
        ext, cell = z["mask"], int(z["cell"])
        keep = []
        for fam, pts in fibres:
            if exterior_mode == "trim":
                runs = exterior_runs(pts, ext, cell)
                if len(runs) != 1 or len(runs[0]) != len(pts):
                    removed += 1
                keep += [(fam, r) for r in runs]
                continue
            c = (pts[:, ::-1] // cell).astype(int)
            c = np.clip(c, 0, np.array(ext.shape) - 1)
            if ext[c[:, 0], c[:, 1], c[:, 2]].any():
                removed += 1
                continue
            keep.append((fam, pts))
        fibres = keep
    info = {"pieces": len(pieces), "links": len(links) // 2, "kept_extensions": kept_ext, "rejoined": rejoined,
            "fibres": len(fibres),
            "exterior_removed": removed, "exterior_mode": exterior_mode, "missing_regions": missing, "stitch_s": round(time.time() - t0, 1),
            "tol_voxels": tol}
    say(json.dumps(info))
    return fibres, info


def join_near_faces(fibres, cores, shape, tol, reach=4.0):
    """Second pass over the joined fibres: two fibre ends of one family that lie within `reach` voxels of a core face
    and within 2 x tol of each other, pointing at each other (within 45 degrees), become one fibre. This catches a
    fibre that one region continued into its halo up to where the neighbour's own curve begins."""
    from scipy.spatial import cKDTree
    planes = [set(), set(), set()]
    for c in cores.values():
        for ax, (lo, hi) in enumerate(((c[4], c[5]), (c[2], c[3]), (c[0], c[1]))):     # x, y, z
            planes[ax].update((lo, min(hi, shape[2 - ax])))
    planes = [np.array(sorted(p), float) for p in planes]

    def near_face(q):
        return any(np.abs(planes[ax] - q[ax]).min() <= reach for ax in range(3))

    nxt = {}
    for fam in ("V", "H"):
        ends = [(i, e) for i, (f, p) in enumerate(fibres) if f == fam for e in (0, 1)
                if near_face(p[-1] if e else p[0])]
        if len(ends) < 2:
            continue
        Q = np.array([fibres[i][1][-1] if e else fibres[i][1][0] for i, e in ends])
        D = np.array([end_dir(fibres[i][1], bool(e)) for i, e in ends])
        cand = []
        for a, b in cKDTree(Q).query_pairs(2 * tol):
            if ends[a][0] == ends[b][0] or np.dot(D[a], -D[b]) < np.cos(np.radians(45)):
                continue
            cand.append((float(np.linalg.norm(Q[a] - Q[b])), a, b))
        for _, a, b in sorted(cand):
            if ends[a] in nxt or ends[b] in nxt:
                continue
            nxt[ends[a]], nxt[ends[b]] = ends[b], ends[a]
    out, seen, joined = [], set(), 0
    for i, (fam, _) in enumerate(fibres):
        if i in seen:
            continue
        cur, e, guard = i, 0, 0              # walk to a free end of i's chain (or once round a ring)
        while (cur, e) in nxt and guard <= len(fibres):
            cur, e = nxt[(cur, e)]
            e = 1 - e
            guard += 1
            if cur == i:
                break
        parts, a, ein = [], cur, e
        while a not in seen:
            seen.add(a)
            seg = fibres[a][1] if ein == 0 else fibres[a][1][::-1]
            parts.append(seg)
            if (a, 1 - ein) not in nxt:
                break
            a, ein = nxt[(a, 1 - ein)]
        joined += len(parts) - 1
        out.append((fam, np.concatenate(parts)))
    return out, joined


def exterior_mask(plan, reach=16):
    """Exterior cells: empty (zero) cells of a coarse level, connected to the scan's border, dilated so every voxel
    within `reach` native voxels of them is covered. The coarse level is plan level + 4 (16-voxel cells) or the
    coarsest stored. Returns (mask, cell)."""
    import math
    import urllib.request
    from scipy import ndimage
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from afv_tile import fetch_box
    base = plan["ct"].rsplit("/", 1)[0]
    lv = int(plan["level"]) + 4
    while True:
        try:
            meta = json.load(urllib.request.urlopen(f"{base}/{lv}/.zarray", timeout=60))
            break
        except Exception:  # noqa: BLE001 (that level is not stored; try the next finer one)
            lv -= 1
    cell = 2 ** (lv - int(plan["level"]))
    vol, _ = fetch_box(f"{base}/{lv}", meta, [0, 0, 0], meta["shape"])
    lab, _ = ndimage.label(vol == 0)
    faces = [lab[0], lab[-1], lab[:, 0], lab[:, -1], lab[:, :, 0], lab[:, :, -1]]
    border = set(np.unique(np.concatenate([f.ravel() for f in faces]))) - {0}
    ext = np.isin(lab, list(border))
    return ndimage.binary_dilation(ext, iterations=max(1, math.ceil(reach / cell))), cell


def write_afv(fibres, out, plan, provenance, min_mm=0.0):
    """Our own AFV writer, with the schema AVF_SPLINE_GENERATOR writes (VC3D fiber collection, version 1)."""
    from avf_spline_generator.afv import SCHEMA, bounds, dumps
    import uuid
    um = float(plan["um_level"])
    shape = plan["shape_zyx"]
    out = Path(out)
    if out.exists():
        out.unlink()
    db = sqlite3.connect(str(out))
    db.executescript(SCHEMA)
    frame = {"coordinate_base_shape_zyx": list(shape), "vc_open_data_source_coordinate_level": int(plan["level"]),
             "vc_open_data_source_coordinate_scale_factor": 2 ** int(plan["level"]),
             "vc_open_data_source_original_resolution": um, "vc_open_data_coordinate_space": plan["coordinate_space"],
             "vc_open_data_source_path": plan["ct"].rsplit("/", 1)[0]}
    root = {"type": "vc3d_fiber_collection", "version": 1, "scale": 1, **frame, "coordinate_order": "XYZ",
            "coordinate_units": "voxel", "voxel_size_mm": um / 1000}
    count = npts = nblk = 0
    for fam, q in fibres:
        L = float(np.linalg.norm(np.diff(q, axis=0), axis=1).sum())
        if len(q) < 2 or L <= 0 or L * um / 1000 < min_mm:
            continue
        count += 1
        ann = {"type": "vc3d_fiber", "version": 1, "sequence": count, "filename": f"fiber_{count}.json",
               "hv_classification": {"manual_tag": fam}, "classification_source": "model_prediction_family_locked_tracing",
               "control_points": [q[0].tolist(), q[-1].tolist()], "length_voxels": L, "length_mm": L * um / 1000}
        db.execute("INSERT INTO fibers VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (count, ann["filename"], fam, len(q), L, *bounds(q), dumps(ann)))
        for first in range(0, len(q) - 1, 256):
            blk = q[first:first + 257].astype("<f8")
            nblk += 1
            db.execute("INSERT INTO blocks VALUES(?,?,?,?)", (nblk, count, first, blk.tobytes()))
            db.execute("INSERT INTO block_bounds VALUES(?,?,?,?,?,?,?)", (nblk, *bounds(blk)))
        npts += len(q)
    meta = {"complete": True, "uuid": str(uuid.uuid4()), "root": root, "frame": frame,
            "geometry": "XYZ binary64 little-endian native L0", "block_segments": 256, "source": provenance.pop("source"),
            "provenance": provenance, "fiber_count": count, "point_count": npts, "block_count": nblk,
            "minimum_length_mm": min_mm}
    db.executemany("INSERT INTO metadata VALUES(?,?)", [(k, dumps(v)) for k, v in meta.items()])
    db.execute("CREATE INDEX fibers_length ON fibers(length DESC,id)")
    db.commit()
    assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert db.execute("SELECT rtreecheck('block_bounds')").fetchone()[0] == "ok"
    db.close()
    return {"fibres": count, "points": npts, "blocks": nblk}


def tiles(afv, plan, out, size=1024):
    """The whole-scan AFV cut into viewer pieces, one per `size`^3 cell of the plan's grid: every fibre with a
    block in the cell, whole and with its whole-scan id, so a viewer reads one small file for a box. Returns the
    index (cell id, box zyx, fibres, bytes)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{afv}?mode=ro", uri=True)
    from avf_spline_generator.afv import SCHEMA
    meta = dict(src.execute("SELECT key, value FROM metadata"))
    src.close()
    Z, Y, X = plan["shape_zyx"]
    index = []
    for z0 in range(0, Z, size):
        for y0 in range(0, Y, size):
            for x0 in range(0, X, size):
                box = [z0, min(z0 + size, Z), y0, min(y0 + size, Y), x0, min(x0 + size, X)]
                cid = f"z{z0:05d}_y{y0:05d}_x{x0:05d}"
                path = out / f"{cid}.afv"
                if path.exists():
                    path.unlink()
                db = sqlite3.connect(f"file:{path}", uri=True)     # URI open, so the read-only ATTACH below is
                db.executescript(SCHEMA)                           # a URI too (builds without SQLITE_USE_URI)
                db.execute("ATTACH DATABASE ? AS s", (f"file:{afv}?mode=ro",))
                db.execute("CREATE TEMP TABLE pick AS SELECT DISTINCT b.fiber_id AS id FROM s.block_bounds r "
                           "JOIN s.blocks b ON b.id = r.id WHERE r.max_x >= ? AND r.min_x < ? AND r.max_y >= ? "
                           "AND r.min_y < ? AND r.max_z >= ? AND r.min_z < ?",
                           (box[4], box[5], box[2], box[3], box[0], box[1]))
                n = db.execute("SELECT COUNT(*) FROM pick").fetchone()[0]
                if not n:
                    db.close()
                    path.unlink()
                    continue
                db.execute("INSERT INTO fibers SELECT f.* FROM s.fibers f JOIN pick USING(id)")
                db.execute("INSERT INTO blocks SELECT b.* FROM s.blocks b JOIN pick p ON p.id = b.fiber_id")
                db.execute("INSERT INTO block_bounds SELECT r.* FROM s.block_bounds r JOIN blocks b ON b.id = r.id")
                m = {k: v for k, v in meta.items()}
                m["tile_box_zyx"] = json.dumps(box)
                m["tile_of"] = json.dumps(Path(afv).name)
                m["fiber_count"] = json.dumps(n)
                m["point_count"] = json.dumps(db.execute("SELECT COALESCE(SUM(point_count), 0) FROM fibers").fetchone()[0])
                m["block_count"] = json.dumps(db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0])
                db.executemany("INSERT INTO metadata VALUES(?,?)", list(m.items()))
                db.execute("CREATE INDEX fibers_length ON fibers(length DESC,id)")
                db.commit()
                db.execute("DETACH DATABASE s")
                db.close()
                index.append({"id": cid, "box_zyx": box, "fibres": n, "bytes": path.stat().st_size})
    (out / "index.json").write_text(json.dumps({"of": Path(afv).name, "size": size, "tiles": index}, indent=1))
    return index


def rebase(src, out, plan, l0_shape_zyx):
    """A copy of a level-k AFV in native level-0 voxels (every point, bound and voxel length times 2^k), declared
    level 0 with scale factor 1: villa's vc_object_store/scripts/import_afv.py accepts only native L0 files.
    Powers of two scale float64 exactly, so the copy holds the same geometry."""
    f = 2 ** int(plan["level"])
    out = Path(out)
    if out.exists():
        out.unlink()
    if f == 1:
        shutil.copyfile(src, out)
        return 1
    shutil.copyfile(src, out)
    db = sqlite3.connect(str(out))
    um0 = float(plan["um_level"]) / f
    top = db.execute("SELECT COALESCE(MAX(id), 0) FROM blocks").fetchone()[0]
    for lo in range(0, top + 1, 200000):        # in batches: a whole-scan file can be tens of GB
        rows = db.execute("SELECT id, points FROM blocks WHERE id >= ? AND id < ?", (lo, lo + 200000)).fetchall()
        db.executemany("UPDATE blocks SET points = ? WHERE id = ?",
                       [((np.frombuffer(b, "<f8") * f).astype("<f8").tobytes(), i) for i, b in rows])
    db.execute("UPDATE block_bounds SET min_x = min_x * ?, max_x = max_x * ?, min_y = min_y * ?, max_y = max_y * ?, "
               "min_z = min_z * ?, max_z = max_z * ?", (f,) * 6)
    ann = []
    for i, a in db.execute("SELECT id, annotation FROM fibers"):
        a = json.loads(a)
        a["control_points"] = [[v * f for v in c] for c in a["control_points"]]
        a["length_voxels"] = a["length_voxels"] * f
        ann.append((json.dumps(a, separators=(",", ":")), i))
    db.executemany("UPDATE fibers SET annotation = ? WHERE id = ?", ann)
    db.execute("UPDATE fibers SET length = length * ?, min_x = min_x * ?, max_x = max_x * ?, min_y = min_y * ?, "
               "max_y = max_y * ?, min_z = min_z * ?, max_z = max_z * ?", (f,) * 7)
    meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM metadata")}
    for d in (meta["frame"], meta["root"]):
        d["coordinate_base_shape_zyx"] = list(l0_shape_zyx)
        d["vc_open_data_source_coordinate_level"] = 0
        d["vc_open_data_source_coordinate_scale_factor"] = 1
        d["vc_open_data_source_original_resolution"] = um0
    meta["root"]["voxel_size_mm"] = um0 / 1000
    meta["geometry"] = "XYZ binary64 little-endian native L0"
    meta["provenance"]["rebased_from_level"] = int(plan["level"])
    if "tile_box_zyx" in meta:
        meta["tile_box_zyx"] = [v * f for v in meta["tile_box_zyx"]]
    db.execute("DELETE FROM metadata")
    db.executemany("INSERT INTO metadata VALUES(?,?)", [(k, json.dumps(v, separators=(",", ":"))) for k, v in meta.items()])
    db.commit()
    db.execute("VACUUM")
    assert db.execute("SELECT rtreecheck('block_bounds')").fetchone()[0] == "ok"
    db.close()
    return f


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stitch")
    s.add_argument("--plan", required=True)
    s.add_argument("--regions", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--tol", type=float, default=1.5)
    s.add_argument("--exterior")
    s.add_argument("--exterior-mode", choices=("drop", "trim"), default="drop",
                   help="drop: a fibre touching the outside is removed (Qual's rule, the default); trim: it is cut "
                        "there and its inside runs kept")
    s.add_argument("--min-mm", type=float, default=0.0)
    s.add_argument("--also-min-mm", type=float, nargs="*", default=[],
                   help="also write OUT_<mm>mm.afv keeping fibres at least this long (Qual publishes 1 mm sets)")
    t = sub.add_parser("tiles", help="cut a whole-scan AFV into one small AFV per 1024^3 cell, for viewers")
    t.add_argument("--plan", required=True)
    t.add_argument("--afv", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--size", type=int, default=1024)
    r = sub.add_parser("rebase", help="copy a level-k AFV into native level-0 voxels (villa's importer needs L0)")
    r.add_argument("--plan", required=True)
    r.add_argument("--afv", nargs="+", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--l0-shape", type=int, nargs=3, required=True, metavar=("Z", "Y", "X"))
    e = sub.add_parser("exterior")
    e.add_argument("--plan", required=True)
    e.add_argument("--out", required=True)
    a = p.parse_args(argv)
    plan = json.loads(Path(a.plan).read_text())
    if a.cmd == "rebase":
        Path(a.out_dir).mkdir(parents=True, exist_ok=True)
        for f in a.afv:
            print(f, rebase(f, Path(a.out_dir) / Path(f).name, plan, a.l0_shape))
        return 0
    if a.cmd == "tiles":
        idx = tiles(a.afv, plan, a.out, a.size)
        print(json.dumps({"tiles": len(idx), "fibres": sum(t["fibres"] for t in idx),
                          "bytes": sum(t["bytes"] for t in idx)}))
        return 0
    if a.cmd == "exterior":
        m, cell = exterior_mask(plan)
        np.savez_compressed(a.out, mask=m, cell=cell)
        print(f"exterior cells {int(m.sum())} of {m.size} ({cell}-voxel cells)")
        return 0
    fibres, info = stitch(plan, a.regions, a.tol, a.exterior, exterior_mode=a.exterior_mode)
    prov = {"source": f"{plan['scan']} AFV V2 fibres (Qualzz20/afv_fiber_9um_v2) traced per region with "
                      f"AVF_SPLINE_GENERATOR and stitched", "model": "Qualzz20/afv_fiber_9um_v2",
            "model_sha256": "b8519a4ce4044c93ed98af0c278628fdcdfdd8808275b3c8becd7211f38b7967",
            "inference": "128^3 windows, stride 64, Gaussian blending, bf16, no mirroring, per-window normalization",
            "tracing": "AVF_SPLINE_GENERATOR per 1024^3 region, 128-voxel halo, seeds in core only", "stitch": info,
            "ct_exterior_cleaning": bool(a.exterior)}
    print(json.dumps(write_afv(fibres, a.out, plan, dict(prov), a.min_mm)))
    for mm in a.also_min_mm:
        out = Path(a.out).with_name(f"{Path(a.out).stem}_{mm:g}mm.afv")
        print(json.dumps({str(out): write_afv(fibres, out, plan, dict(prov), mm)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
