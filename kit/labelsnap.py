"""Label snap: move a published surface label onto the papyrus recto face, with an abstain mask: `kit labelsnap`.

villa's 2026 open problems ask for surface labels "better localized on the papyrus' recto" and for zarr image and
label pairs instead of voxelized meshes (Sourced fact, https://scrollprize.org/2026_open_problems, read 21 October
2026; villa #1640 reports that surface labels mark the recto face). This command takes one tifxyz surface label and
the CT volume it lives in, and writes:

  snapped.tifxyz/      the label moved along its normals onto the recto face (or, with --target, the midline or the
                       verso face) of the nearest CT band: kit snap technique D (kit.snap.snap_face) in its
                       per-vertex form (kit.snap.FACE_SNAP_PER_VERTEX; --merged adds the merged-band rule,
                       FACE_SNAP_PER_VERTEX_MERGED, the default until 27 October 2026). A vertex
                       that measured no face of its own may still move by an offset filled in from measured
                       neighbors, or stays where it was.
  abstain.tif          uint8 grid of the mesh's shape: 0 the vertex measured its own face and moved onto it,
                       1 it abstained, 255 not a valid vertex
  reason.tif           uint8 grid: why a vertex abstained (kit.snap.FACE_REASONS; 0 measured)
  confidence.tif       float32 grid, 0 to 1 per vertex, 0 where it abstained: contrast over the floor, separation from
                       the next band and thickness under the merged-band cap, multiplied. A ranking heuristic that no
                       test has checked yet (Untested idea)
  surface_label.zarr/  OME-Zarr label in the CT's voxel frame (one level of it): 0 background, 1 surface (the snapped
                       surface where every corner of a grid cell measured its face), 2 ignore (cells with an
                       abstaining corner, and a band of --ignore-halo voxels along the normal around them, since the
                       sheet there may sit anywhere within the snap's reach). 2 is the largest value, as nnU-Net
                       wants its ignore label. Missing chunks read 0
  review.json          VC3D point collection (vc_pointcollections_json_version 1): one point per region of connected
                       abstaining vertices, largest first, at the region's vertex nearest its middle (the label's
                       position), for a person to check in VC3D; review.tsv lists the same regions
  labelsnap.json       the record: inputs, settings, the snap's report, counts per reason, the label and the review
                       queue, timings, and the self-check when asked

  kit labelsnap snap SURFACE --volume CT --out DIR (--umbilicus FILE | --axis-point X Y Z --axis-dir X Y Z |
                     --recto-sign 1|-1) [--level 0] [--target recto] [--merged] [--no-label] [--label-level 0]
                     [--ignore-halo 4] [--label-step 0.5] [--review-min 4] [--self-check] [--json]
  kit labelsnap check DIR [--json]     every output present, shapes and values consistent (exit 1 on a problem)

A snapped label is geometry, not a reading. Whether snapping helps is measured against an independent scan by
a folder of the source repository (preregistered in a note of the source repository); until that verdict exists, nothing
here claims the snapped label is closer to the papyrus than the published one.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

from . import snap as S

VERSION = 1
ABSTAIN_OK, ABSTAIN_YES, ABSTAIN_INVALID = 0, 1, 255
LABEL_BG, LABEL_SURFACE, LABEL_IGNORE = 0, 1, 2
LABEL_CHUNK = 128
MAX_BATCH_POINTS = 2_000_000   # label samples held at once (each 3 float64 plus indices: under about 150 MB)
DEFAULTS = {
    "target": "recto",
    "merged": False,         # FACE_SNAP_PER_VERTEX (True: FACE_SNAP_PER_VERTEX_MERGED, the merged-band rule). False since 27 Oct 2026
    "face_sigma": 1.0,       # the band finder's smoothing
    "ignore_halo": None,     # None: the snap's max_move (4 voxels by default)
    "label_step": 0.5,       # sample spacing on the surface for the label, voxels of the label level
    "review_min": 4,         # an abstaining region needs this many vertices to enter the review queue
    "review_max": 500,       # at most this many review points
}


class LabelSnapError(ValueError):
    pass


def _np():
    return S._numpy()


# ---------------------------------------------------------------- the snap and its per-vertex products

def face_opts(target="recto", merged=DEFAULTS["merged"], extra=None):
    """snap_face options of the label snap: the per-vertex form, with the merged-band rule when merged is True."""
    o = dict(S.FACE_SNAP_PER_VERTEX_MERGED if merged else S.FACE_SNAP_PER_VERTEX)
    o["target"] = target
    o.update(extra or {})
    return o


def confidence(detail, measured_mask):
    """Per-vertex confidence in [0, 1] from snap_face's detail grids: contrast above the floor (0 at the floor, 1 at
    twice it), separation from the next band past the ambiguity limit (0 at the limit, 1 one limit further; 1 with
    one band in view), and thickness under the merged-band cap (1 at the reference thickness, 0 at the cap; 1 with no
    cap), multiplied; 0 where the vertex did not measure its own face. Untested as a ranking (Interpretation)."""
    np = _np()
    floor = float(detail["floor"])
    amb = float(detail["ambiguous"])
    con = detail["contrast"].astype(np.float64)
    sep = detail["sep"].astype(np.float64)
    thick = detail["thick"].astype(np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        c1 = np.clip((con - floor) / floor, 0.0, 1.0) if floor > 0 else np.where(np.isfinite(con), 1.0, 0.0)
        c2 = np.where(np.isinf(sep), 1.0, np.clip((sep - amb) / amb, 0.0, 1.0)) if amb > 0 else np.ones(con.shape)
        c2 = np.where(np.isnan(sep), 1.0, c2)          # the global-level form measures no separation
        cap, ref = detail.get("cap"), detail.get("ref_thick")
        if cap is not None and ref is not None and cap > ref:
            c3 = np.clip((cap - thick) / (cap - ref), 0.0, 1.0)
        else:
            c3 = np.ones(con.shape)
    out = np.where(measured_mask, np.nan_to_num(c1 * c2 * c3, nan=0.0), 0.0)
    return out.astype(np.float32)


def label_snap(xs, ys, zs, valid, sampler, axis=None, recto_sign=None, target="recto", merged=DEFAULTS["merged"],
               face_sigma=DEFAULTS["face_sigma"], extra_opts=None, batch=S.DEFAULT_BATCH):
    """The label snap of one mesh. Returns a dict: xs, ys, zs (snapped grids), valid, abstain (uint8 grid: 0, 1 or
    255), reason (uint8, kit.snap.FACE_REASONS), confidence (float32), apply (moved), D3 (offsets along the normal),
    normals and ok (the mesh normals the snap moved along), report and record (snap_face's), detail (snap_face's
    per-vertex grids)."""
    np = _np()
    opts = face_opts(target, merged, extra_opts)
    res = S.snap_face(xs, ys, zs, valid, sampler, axis=axis, recto_sign=recto_sign, opts=opts,
                      face_opts={"sigma": float(face_sigma)}, batch=batch)
    det = res["detail"]
    n, ok = S.normals(xs, ys, zs, valid)
    measured = np.isfinite(det["measured"]) & ok
    abstain = np.full(xs.shape, ABSTAIN_INVALID, np.uint8)
    abstain[valid] = ABSTAIN_YES
    abstain[measured] = ABSTAIN_OK
    reason = det["reason"].copy()
    reason[~valid] = 9
    conf = confidence(det, measured)
    out = dict(res)
    out.update({"abstain": abstain, "reason": reason, "confidence": conf, "normals": n, "ok": ok, "opts": opts})
    return out


def reason_counts(reason, valid):
    np = _np()
    vals, cnt = np.unique(reason[valid], return_counts=True)
    return {S.FACE_REASONS.get(int(v), str(int(v))): int(c) for v, c in zip(vals, cnt)}


# ---------------------------------------------------------------- the review queue

def components(mask):
    """4-connected components of a 2-D boolean grid: (labels int32 grid, 0 outside, 1..n), by runs per row and
    union-find over overlapping runs of neighboring rows (numpy and the standard library only)."""
    np = _np()
    H, W = mask.shape
    lab = np.zeros((H, W), np.int32)
    parent = [0]

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    prev = []
    for r in range(H):
        row = mask[r]
        d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
        cur = []
        for s, e in zip(starts.tolist(), ends.tolist()):
            ids = [lid for ps, pe, lid in prev if ps < e and s < pe]
            if ids:
                root = find(ids[0])
                for other in ids[1:]:
                    ro = find(other)
                    if ro != root:
                        parent[ro] = root
                lid = root
            else:
                lid = len(parent)
                parent.append(lid)
            lab[r, s:e] = lid
            cur.append((s, e, lid))
        prev = cur
    if len(parent) > 1:
        roots = np.array([find(i) for i in range(len(parent))], np.int32)
        uniq, dense = np.unique(roots[1:], return_inverse=True)
        remap = np.concatenate([[0], dense.astype(np.int32) + 1])
        lab = remap[lab]
    return lab


def review_regions(xs, ys, zs, abstain, reason, min_size=DEFAULTS["review_min"], max_points=DEFAULTS["review_max"]):
    """Regions of connected abstaining vertices with at least min_size vertices, largest first (ties by row, then
    column): for each its size, the vertex nearest its middle in grid terms, that vertex's label position (x, y, z)
    and the commonest reason. At most max_points regions."""
    np = _np()
    lab = components(abstain == ABSTAIN_YES)
    n = int(lab.max())
    out = []
    if n == 0:
        return out
    rr, cc = np.nonzero(lab)
    ids = lab[rr, cc]
    order = np.argsort(ids, kind="stable")
    rr, cc, ids = rr[order], cc[order], ids[order]
    cuts = np.flatnonzero(np.diff(ids)) + 1
    for r_, c_ in zip(np.split(rr, cuts), np.split(cc, cuts)):
        size = len(r_)
        if size < min_size:
            continue
        mr, mc = r_.mean(), c_.mean()
        k = int(np.argmin((r_ - mr) ** 2 + (c_ - mc) ** 2))
        r0, c0 = int(r_[k]), int(c_[k])
        vals, cnt = np.unique(reason[r_, c_], return_counts=True)
        top = int(vals[int(np.argmax(cnt))])
        out.append({"size": int(size), "row": r0, "col": c0,
                    "xyz": [round(float(xs[r0, c0]), 3), round(float(ys[r0, c0]), 3), round(float(zs[r0, c0]), 3)],
                    "reason": S.FACE_REASONS.get(top, str(top)),
                    "bbox_rc": [int(r_.min()), int(r_.max()), int(c_.min()), int(c_.max())]})
    out.sort(key=lambda d: (-d["size"], d["row"], d["col"]))
    return out[:max_points]


def review_collection(regions, name="labelsnap review", meta=None):
    """The regions as a VC3D point collection document (kit.villafmt.vc3d_points' layout); `kit` holds the region
    details, which VC3D ignores."""
    from . import villafmt
    doc = villafmt.vc3d_points([r["xyz"] for r in regions], name=name, color=(1.0, 0.35, 0.0)) if regions else {
        "vc_pointcollections_json_version": villafmt.VC3D_POINTS_VERSION,
        "collections": {"1": {"name": name, "points": {}, "metadata": {"winding_is_absolute": False},
                              "color": [1.0, 0.35, 0.0]}}}
    doc["kit"] = dict(meta or {}, regions=[{k: r[k] for k in ("size", "row", "col", "reason", "bbox_rc")}
                                           for r in regions])
    return doc


# ---------------------------------------------------------------- the OME-Zarr surface label

def _cell_samples(P, N, classes, step, halo):
    """Points on the grid cells of one batch: P (k, 4, 3) corner positions (r, c), (r, c+1), (r+1, c), (r+1, c+1);
    N the corner normals; classes (k,) LABEL_SURFACE or LABEL_IGNORE. Each cell is sampled bilinearly every `step`
    or finer; an ignore cell is also sampled along its normal from -halo to +halo every `step`. Returns (points
    (m, 3), class per point)."""
    np = _np()
    e1 = np.linalg.norm(P[:, 1] - P[:, 0], axis=1)
    e2 = np.linalg.norm(P[:, 2] - P[:, 0], axis=1)
    e3 = np.linalg.norm(P[:, 3] - P[:, 2], axis=1)
    e4 = np.linalg.norm(P[:, 3] - P[:, 1], axis=1)
    nseg = np.clip(np.ceil(np.maximum.reduce([e1, e2, e3, e4]) / step), 1, 4096).astype(np.int64)
    pts, cls = [], []
    for m in np.unique(nseg):
        sel = np.nonzero(nseg == m)[0]
        u = np.linspace(0.0, 1.0, int(m) + 1)
        uu, vv = np.meshgrid(u, u, indexing="ij")
        w = np.stack([(1 - uu) * (1 - vv), (1 - uu) * vv, uu * (1 - vv), uu * vv], -1).reshape(-1, 4)
        Q = np.einsum("sj,kjd->ksd", w, P[sel])                      # (k, s, 3), rows u along r, v along c
        cl = classes[sel]
        surf = cl == LABEL_SURFACE
        if surf.any():
            pts.append(Q[surf].reshape(-1, 3))
            cls.append(np.full(int(surf.sum()) * len(w), LABEL_SURFACE, np.uint8))
        ign = ~surf
        if ign.any():
            Nq = np.einsum("sj,kjd->ksd", w, N[sel][ign])
            Nq /= np.maximum(np.linalg.norm(Nq, axis=-1, keepdims=True), 1e-9)
            offs = np.arange(-halo, halo + 0.5 * step, step) if halo > 0 else np.zeros(1)
            R = Q[ign][:, :, None, :] + offs[None, None, :, None] * Nq[:, :, None, :]
            pts.append(R.reshape(-1, 3))
            cls.append(np.full(R.shape[0] * R.shape[1] * R.shape[2], LABEL_IGNORE, np.uint8))
    if not pts:
        return np.zeros((0, 3)), np.zeros(0, np.uint8)
    return np.concatenate(pts), np.concatenate(cls)


def write_surface_label(path, xs, ys, zs, valid, abstain, normals, shape_zyx, scale=1.0, halo=4.0,
                        step=DEFAULTS["label_step"], chunk=LABEL_CHUNK, source=None, level=0):
    """Write the OME-Zarr surface label of a snapped mesh. xs, ys, zs are the snapped grids in level-0 voxels of the
    image; scale converts them to the label array's voxels (1 / 2**level for a pyramid level); shape_zyx is that
    level's shape. A cell whose four corners measured their face is surface (1), a cell with an abstaining corner is
    ignore (2) with a halo along the normal; surface wins where both touch a voxel. Written by z slabs of one chunk,
    only the chunks something touches (zlib, '/' keys). Returns a summary dict."""
    import zlib
    np = _np()
    root = Path(path)
    if root.exists():
        raise LabelSnapError(f"{root} exists: the label is never written over an old one")
    Z, Y, X = (int(v) for v in shape_zyx)
    P = np.stack([xs, ys, zs], -1).astype(np.float64) * float(scale)
    nrm = normals.astype(np.float64)
    H, W = xs.shape
    v4 = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & valid[1:, 1:]
    nf = np.isfinite(nrm).all(-1)
    n4 = nf[:-1, :-1] & nf[:-1, 1:] & nf[1:, :-1] & nf[1:, 1:]
    cr, cc = np.nonzero(v4 & n4)
    corners = [(cr, cc), (cr, cc + 1), (cr + 1, cc), (cr + 1, cc + 1)]
    Pc = np.stack([P[r, c] for r, c in corners], 1)                        # (k, 4, 3)
    Nc = np.stack([nrm[r, c] for r, c in corners], 1)
    good = np.stack([abstain[r, c] == ABSTAIN_OK for r, c in corners], 1).all(1)
    cls = np.where(good, LABEL_SURFACE, LABEL_IGNORE).astype(np.uint8)
    h = float(halo) * float(scale)
    zlo = Pc[:, :, 2].min(1) - h - 1
    zhi = Pc[:, :, 2].max(1) + h + 1
    arr = root / "0"
    arr.mkdir(parents=True)
    counts = {"surface": 0, "ignore": 0}
    chunks_written = 0
    out_of_volume = 0
    # samples per cell, to cut the cells of a slab into batches of at most MAX_BATCH_POINTS points
    edge = np.maximum.reduce([np.linalg.norm(Pc[:, a] - Pc[:, b], axis=1) for a, b in ((0, 1), (0, 2), (2, 3), (1, 3))])
    nseg = np.clip(np.ceil(edge / step), 1, 4096)
    noff = (2 * int(math.floor(h / step + 1e-9)) + 1) if h > 0 else 1
    cost = (nseg + 1) ** 2 * np.where(cls == LABEL_IGNORE, noff, 1)
    for z0 in range(0, Z, chunk):
        sel = np.nonzero((zhi >= z0) & (zlo < z0 + chunk))[0]
        if not len(sel):
            continue
        blocks = {}
        group = ((np.cumsum(cost[sel]) - 1) // MAX_BATCH_POINTS).astype(np.int64)    # nondecreasing batch ids
        for s in np.split(sel, np.flatnonzero(np.diff(group)) + 1):
            pts, pc = _cell_samples(Pc[s], Nc[s], cls[s], step, h)
            v = np.rint(pts[:, ::-1]).astype(np.int64)                     # z, y, x voxel indices
            inside = (v[:, 0] >= 0) & (v[:, 0] < Z) & (v[:, 1] >= 0) & (v[:, 1] < Y) & (v[:, 2] >= 0) & (v[:, 2] < X)
            out_of_volume += int((~inside & (v[:, 0] >= z0) & (v[:, 0] < z0 + chunk)).sum())
            keep = inside & (v[:, 0] >= z0) & (v[:, 0] < z0 + chunk)
            v, pc = v[keep], pc[keep]
            if not len(v):
                continue
            ky, kx = v[:, 1] // chunk, v[:, 2] // chunk
            key = ky * (X // chunk + 1) + kx
            for k in np.unique(key):
                m = key == k
                blk = blocks.get(int(k))
                if blk is None:
                    blk = blocks[int(k)] = np.zeros((chunk, chunk, chunk), np.uint8)
                vv, cc_ = v[m], pc[m]
                lz, ly, lx = vv[:, 0] - z0, vv[:, 1] % chunk, vv[:, 2] % chunk
                ig = cc_ == LABEL_IGNORE
                cur = blk[lz[ig], ly[ig], lx[ig]]
                blk[lz[ig], ly[ig], lx[ig]] = np.where(cur == LABEL_SURFACE, LABEL_SURFACE, LABEL_IGNORE)
                sf = ~ig
                blk[lz[sf], ly[sf], lx[sf]] = LABEL_SURFACE
        cz = z0 // chunk
        for k, blk in blocks.items():
            ky, kx = divmod(k, X // chunk + 1)
            counts["surface"] += int((blk == LABEL_SURFACE).sum())
            counts["ignore"] += int((blk == LABEL_IGNORE).sum())
            d = arr / str(cz) / str(ky)
            d.mkdir(parents=True, exist_ok=True)
            (d / str(kx)).write_bytes(zlib.compress(blk.tobytes(), 1))
            chunks_written += 1
    meta = {"zarr_format": 2, "shape": [Z, Y, X], "chunks": [chunk] * 3, "dtype": "|u1", "fill_value": 0,
            "compressor": {"id": "zlib", "level": 1}, "filters": None, "order": "C", "dimension_separator": "/"}
    (arr / ".zarray").write_text(json.dumps(meta, indent=1))
    (root / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    f = 1.0 / float(scale)
    attrs = {
        "multiscales": [{"version": "0.4", "name": "labelsnap surface label",
                         "axes": [{"name": a, "type": "space"} for a in "zyx"],
                         "datasets": [{"path": "0", "coordinateTransformations": [{"type": "scale",
                                                                                     "scale": [f, f, f]}]}]}],
        "image-label": {"version": "0.4", "source": {"image": source or ""},
                        "colors": [{"label-value": LABEL_SURFACE, "rgba": [0, 200, 255, 255]},
                                   {"label-value": LABEL_IGNORE, "rgba": [255, 128, 0, 255]}],
                        "properties": [{"label-value": LABEL_BG, "name": "background"},
                                       {"label-value": LABEL_SURFACE, "name": "surface"},
                                       {"label-value": LABEL_IGNORE, "name": "ignore"}]},
        "kit": {"tool": "kit labelsnap", "version": VERSION, "image_level": int(level), "halo_voxels": float(halo),
                "step": float(step), "values": {"0": "background", "1": "surface", "2": "ignore"}},
    }
    (root / ".zattrs").write_text(json.dumps(attrs, indent=1))
    return {"path": str(root), "shape_zyx": [Z, Y, X], "level": int(level), "chunks_written": chunks_written,
            "voxels": counts, "cells_surface": int(good.sum()), "cells_ignore": int((~good).sum()),
            "samples_outside_volume": out_of_volume}


def read_label_chunks(path):
    """(shape, {(cz, cy, cx): block}) of a label written by write_surface_label (for checks and tests)."""
    import zlib
    np = _np()
    arr = Path(path) / "0"
    meta = json.loads((arr / ".zarray").read_text())
    ch = meta["chunks"]
    out = {}
    for f in arr.glob("*/*/*"):
        if f.is_file():
            cz, cy, cx = (int(p) for p in f.relative_to(arr).parts)
            out[(cz, cy, cx)] = np.frombuffer(zlib.decompress(f.read_bytes()), np.uint8).reshape(ch)
    return meta["shape"], out


# ---------------------------------------------------------------- writing one run, and checking it

def _write_grid_tif(path, arr):
    from . import vc3d_io
    vc3d_io.write_tiff(path, vc3d_io.raster_from_numpy(arr))


def _read_grid_tif(path):
    np = _np()
    try:
        import tifffile
        return np.asarray(tifffile.imread(str(path)))
    except ImportError:
        from . import vc3d_io
        r = vc3d_io.read_tiff(path)
        return np.asarray(r.floats()).reshape(r.h, r.w)


def write_outputs(out, src, res, volume_desc, label_shape=None, label_scale=1.0, label_level=0, halo=None,
                  step=DEFAULTS["label_step"], review_min=DEFAULTS["review_min"], review_max=DEFAULTS["review_max"],
                  extra_record=None, xs0=None, ys0=None, zs0=None):
    """Write every product of one label snap result `res` (label_snap's dict) into out. xs0/ys0/zs0 are the label's
    original grids (the review points sit there; default the snapped ones). Returns the record."""
    np = _np()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    valid = res["valid"]
    S.write_mesh(src, out / "snapped.tifxyz", res["xs"], res["ys"], res["zs"], valid, res["record"],
                 " + kit labelsnap (recto-face label snap with an abstain mask)")
    _write_grid_tif(out / "abstain.tif", res["abstain"])
    _write_grid_tif(out / "reason.tif", res["reason"])
    _write_grid_tif(out / "confidence.tif", res["confidence"])
    xs0 = res["xs"] if xs0 is None else xs0
    ys0 = res["ys"] if ys0 is None else ys0
    zs0 = res["zs"] if zs0 is None else zs0
    regions = review_regions(xs0, ys0, zs0, res["abstain"], res["reason"], review_min, review_max)
    meta = {"tool": "kit labelsnap", "version": VERSION, "surface": str(src) if src else None,
            "volume": volume_desc, "review_min": int(review_min)}
    (out / "review.json").write_text(json.dumps(review_collection(regions, meta=meta), indent=1))
    lines = ["rank\tsize\trow\tcol\tx\ty\tz\treason"]
    for i, r in enumerate(regions, 1):
        lines.append("\t".join(str(v) for v in (i, r["size"], r["row"], r["col"], *r["xyz"], r["reason"])))
    (out / "review.tsv").write_text("\n".join(lines) + "\n")
    nvalid = int(valid.sum())
    nab = int((res["abstain"] == ABSTAIN_YES).sum())
    rec = {"tool": "kit labelsnap", "version": VERSION, "surface": str(src) if src else None,
           "volume": volume_desc, "opts": res["opts"], "report": res["report"],
           "vertices": {"valid": nvalid, "measured": nvalid - nab, "abstained": nab,
                        "frac_abstained": round(nab / nvalid, 4) if nvalid else None,
                        "moved": int(res["apply"].sum()),
                        "confidence_median_measured": (float(np.median(res["confidence"][res["abstain"] == 0]))
                                                       if nvalid - nab else None)},
           "reasons": reason_counts(res["reason"], valid),
           "review": {"regions": len(regions), "vertices_in_regions": int(sum(r["size"] for r in regions)),
                      "file": "review.json"}}
    if label_shape is not None:
        hal = float(res["opts"].get("max_move", 4.0) if halo is None else halo)
        rec["label"] = write_surface_label(out / "surface_label.zarr", res["xs"], res["ys"], res["zs"], valid,
                                           res["abstain"], res["normals"], label_shape, label_scale, hal, step,
                                           source=volume_desc.get("location") if isinstance(volume_desc, dict)
                                           else None, level=label_level)
    if extra_record:
        rec.update(extra_record)
    (out / "labelsnap.json").write_text(json.dumps(rec, indent=1, default=float))
    return rec


def check_outputs(out):
    """Problems with one output folder (an empty list when everything is present and consistent)."""
    np = _np()
    out = Path(out)
    probs = []
    need = ["snapped.tifxyz/x.tif", "snapped.tifxyz/y.tif", "snapped.tifxyz/z.tif", "snapped.tifxyz/meta.json",
            "abstain.tif", "reason.tif", "confidence.tif", "review.json", "review.tsv", "labelsnap.json"]
    missing = [n for n in need if not (out / n).is_file()]
    if missing:
        return [f"missing: {', '.join(missing)}"]
    rec = json.loads((out / "labelsnap.json").read_text())
    xs, ys, zs, valid = S.load_mesh(out / "snapped.tifxyz")
    ab = _read_grid_tif(out / "abstain.tif")
    rs = _read_grid_tif(out / "reason.tif")
    cf = _read_grid_tif(out / "confidence.tif")
    for name, a in (("abstain.tif", ab), ("reason.tif", rs), ("confidence.tif", cf)):
        if a.shape != xs.shape:
            probs.append(f"{name} is {a.shape}, the mesh grid is {xs.shape}")
    if probs:
        return probs
    if not set(np.unique(ab).tolist()) <= {ABSTAIN_OK, ABSTAIN_YES, ABSTAIN_INVALID}:
        probs.append("abstain.tif holds values other than 0, 1 and 255")
    if (ab[valid] == ABSTAIN_INVALID).any():
        probs.append("a valid vertex is marked invalid in abstain.tif")
    if ((ab == ABSTAIN_OK) != (rs == 0)).any():
        probs.append("abstain.tif and reason.tif disagree (reason 0 must be exactly the measured vertices)")
    if not (np.isfinite(cf).all() and cf.min() >= 0 and cf.max() <= 1):
        probs.append("confidence.tif is outside 0 to 1")
    if (cf[ab != ABSTAIN_OK] != 0).any():
        probs.append("confidence is nonzero where the vertex abstained")
    nab = int((ab == ABSTAIN_YES).sum())
    if rec.get("vertices", {}).get("abstained") != nab:
        probs.append(f"labelsnap.json counts {rec.get('vertices', {}).get('abstained')} abstaining vertices, "
                     f"abstain.tif {nab}")
    doc = json.loads((out / "review.json").read_text())
    cols = doc.get("collections") or {}
    npts = sum(len(c.get("points") or {}) for c in cols.values())
    if doc.get("vc_pointcollections_json_version") is None or len(cols) != 1:
        probs.append("review.json is not a VC3D point collection document with one collection")
    if npts != rec.get("review", {}).get("regions"):
        probs.append(f"review.json has {npts} points, labelsnap.json {rec.get('review', {}).get('regions')} regions")
    if "label" in rec:
        lp = out / "surface_label.zarr"
        if not (lp / "0" / ".zarray").is_file() or not (lp / ".zattrs").is_file():
            probs.append("surface_label.zarr is missing its array or attributes")
        else:
            shape, blocks = read_label_chunks(lp)
            vals = set()
            for b in blocks.values():
                vals |= set(np.unique(b).tolist())
            if not vals <= {LABEL_BG, LABEL_SURFACE, LABEL_IGNORE}:
                probs.append(f"surface_label.zarr holds values {sorted(vals)}, only 0, 1 and 2 are allowed")
            if (ab == ABSTAIN_OK).sum() >= 4 and rec["label"]["cells_surface"] > 0 and LABEL_SURFACE not in vals:
                probs.append("no surface voxel was written although cells measured their face")
            if len(blocks) != rec["label"]["chunks_written"]:
                probs.append(f"surface_label.zarr has {len(blocks)} chunks, labelsnap.json says "
                             f"{rec['label']['chunks_written']}")
    return probs


# ---------------------------------------------------------------- command line

def build_parser(p):
    sub = p.add_subparsers(dest="labelsnap_cmd", required=True)
    s = sub.add_parser("snap", help="snap one tifxyz surface label onto the recto face and write the label products")
    s.add_argument("surface", help="tifxyz folder (x.tif, y.tif, z.tif, meta.json) in the volume's level-0 voxels")
    s.add_argument("--volume", required=True, help="the CT the label lives in: OME-Zarr folder or http(s) URL")
    s.add_argument("--level", type=int, default=0, help="pyramid level the snap reads (coordinates stay level 0)")
    s.add_argument("--out", required=True, help="output folder (created; existing products are refused)")
    s.add_argument("--umbilicus", help="umbilicus JSON naming the scroll axis (kit snap's format)")
    s.add_argument("--umbilicus-scale", type=float, default=1.0, help="multiply the umbilicus points by this")
    s.add_argument("--axis-point", nargs=3, type=float, metavar=("X", "Y", "Z"))
    s.add_argument("--axis-dir", nargs=3, type=float, metavar=("X", "Y", "Z"))
    s.add_argument("--recto-sign", type=float, choices=(1.0, -1.0),
                   help="+1: the recto face lies at negative offsets along the mesh normal; -1: at positive ones")
    s.add_argument("--target", choices=("recto", "mid", "verso"), default="recto")
    s.add_argument("--merged", action="store_true",
                   help="add the merged-band rule (FACE_SNAP_PER_VERTEX_MERGED; the default until 27 Oct 2026)")
    s.add_argument("--no-merged", action="store_true", help="the default since 27 Oct 2026 (kept for old commands)")
    s.add_argument("--face-sigma", type=float, default=DEFAULTS["face_sigma"])
    s.add_argument("--max-move", type=float, help="snap_face's max_move (default 4 voxels)")
    s.add_argument("--no-label", action="store_true", help="skip the OME-Zarr surface label")
    s.add_argument("--label-level", type=int, default=0, help="the image level the label array matches")
    s.add_argument("--ignore-halo", type=float, help="ignore band along the normal, level-0 voxels (default max_move)")
    s.add_argument("--label-step", type=float, default=DEFAULTS["label_step"])
    s.add_argument("--review-min", type=int, default=DEFAULTS["review_min"])
    s.add_argument("--review-max", type=int, default=DEFAULTS["review_max"])
    s.add_argument("--self-check", action="store_true",
                   help="also run kit snap's self-check (plant 2 voxels, recover; shifted and empty controls)")
    s.add_argument("--json", action="store_true")
    c = sub.add_parser("check", help="check one output folder: every product present, shapes and values consistent")
    c.add_argument("out")
    c.add_argument("--json", action="store_true")


def _axis_of(args):
    ns = argparse.Namespace(umbilicus=args.umbilicus, umbilicus_scale=args.umbilicus_scale,
                            axis_point=args.axis_point, axis_dir=args.axis_dir)
    axis = S._axis(ns)
    if axis is not None and args.recto_sign is not None:
        raise LabelSnapError("give the scroll axis or --recto-sign, not both")
    if args.target != "mid" and axis is None and args.recto_sign is None:
        raise LabelSnapError("the recto face is named by its side toward the scroll axis: give --umbilicus, "
                             "--axis-point with --axis-dir, or --recto-sign")
    return axis


def level_scale(vol, level):
    """The factor write_surface_label multiplies level-0 coordinates by for the label array of an image level: that
    level's voxels per level-0 voxel (kit.vc3d_audit.factors), so 0.5 at level 1 of a halving pyramid. The label then
    follows kit snap's Sampler (level-0 coordinate / 2**level) and its OME scale is 1 / factor, with no translation.
    The writer takes one factor, so a level whose z, y and x factors differ is refused."""
    f = [float(v) for v in vol.factors[level]]
    if not f or min(f) <= 0 or max(f) - min(f) > 1e-9 * max(f):
        raise LabelSnapError(f"--label-level {level}: the level's factors {f} (z, y, x) are not one isotropic scale")
    return f[-1]


def run_snap(args):
    t0 = time.time()
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise LabelSnapError(f"{out} is not empty: write each run to a new folder")
    axis = _axis_of(args)
    xs, ys, zs, valid = S.load_mesh(args.surface)
    vol = S.open_volume(args.volume)
    sampler = S.Sampler(vol, level=args.level)
    extra = {"max_move": float(args.max_move)} if args.max_move is not None else None
    res = label_snap(xs, ys, zs, valid, sampler, axis=axis, recto_sign=args.recto_sign, target=args.target,
                     merged=bool(args.merged) and not args.no_merged, face_sigma=args.face_sigma, extra_opts=extra)
    t_snap = time.time() - t0
    extra_rec = {}
    if args.self_check:
        def snapper(a, b, c, v, smp):
            return S.snap_face(a, b, c, v, smp, axis=axis, recto_sign=args.recto_sign, opts=res["opts"],
                               face_opts={"sigma": float(args.face_sigma)})
        extra_rec["self_check"] = S.self_check(xs, ys, zs, valid, sampler, snapper, S.DEFAULT_CHECK_SHIFT["face"],
                                               1.0, 1.0, 0.8, 3.0, "snapped")
    label_shape = None
    scale = 1.0
    if not args.no_label:
        if not 0 <= args.label_level < len(vol.levels):
            raise LabelSnapError(f"--label-level {args.label_level}: the volume has {len(vol.levels)} levels")
        label_shape = vol.shape(args.label_level)
        scale = level_scale(vol, args.label_level)
    desc = {"location": str(args.volume), "level": int(args.level), "shape_zyx": vol.shape(0),
            "axis": axis[0] if axis else None, "recto_sign": args.recto_sign}
    extra_rec["seconds"] = {"snap": round(t_snap, 2)}
    rec = write_outputs(out, args.surface, res, desc, label_shape, scale, args.label_level, args.ignore_halo,
                        args.label_step, args.review_min, args.review_max, extra_rec, xs, ys, zs)
    rec["seconds"]["total"] = round(time.time() - t0, 2)
    (out / "labelsnap.json").write_text(json.dumps(rec, indent=1, default=float))
    return rec


def cmd_labelsnap(args):
    try:
        if args.labelsnap_cmd == "snap":
            rec = run_snap(args)
            probs = check_outputs(args.out)
            if args.json:
                print(json.dumps(rec, indent=1, default=float))
            else:
                v = rec["vertices"]
                print(f"labelsnap: {v['measured']} of {v['valid']} vertices measured their {rec['opts']['target']} "
                      f"face and moved onto it, {v['abstained']} abstained ({v['frac_abstained']}); "
                      f"{rec['review']['regions']} review regions; wrote {args.out}")
                if "label" in rec:
                    lb = rec["label"]
                    print(f"label: {lb['voxels']['surface']} surface and {lb['voxels']['ignore']} ignore voxels in "
                          f"{lb['chunks_written']} chunks")
                if "self_check" in rec:
                    print("self-check: " + ("passed" if rec["self_check"]["passed"] else "FAILED") + "; "
                          + "; ".join(rec["self_check"]["why"]))
            if probs:
                print("kit labelsnap: the outputs fail their own check:\n  " + "\n  ".join(probs), file=sys.stderr)
                return 1
            return 0
        probs = check_outputs(args.out)
        if args.json:
            print(json.dumps({"out": args.out, "ok": not probs, "problems": probs}, indent=1))
        else:
            print("labelsnap check: " + ("ok" if not probs else "FAILED\n  " + "\n  ".join(probs)))
        return 0 if not probs else 1
    except (LabelSnapError, S.SnapError) as exc:
        print(f"kit labelsnap: {exc}", file=sys.stderr)
        return 2


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit labelsnap", description=__doc__.split("\n\n")[0])
    build_parser(p)
    return cmd_labelsnap(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
