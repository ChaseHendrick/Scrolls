"""Score an automatically traced surface against the published PHerc0139 hand windings: `kit surfbench`.

The measuring stick for the unwrapping steps still left to a person: growing whole windings, repairing sheet
switches and predicting a surface for a new scan. A candidate tifxyz in the frame of PHerc0139 volume
20250728140407 (9.362 um) is labelled vertex by vertex with the reference winding it lies on (point to plane,
inside that winding's footprint), then scored by how much of it lies on one winding, how much of that winding it
covers, and where its labels switch. The references are the published windings w023 to w059 in that frame;
geometry decides their order, duplicates and gaps, never their names.

  refs      download the windings and build the reference manifest: winding order and pitch from normal offsets,
            near-duplicates (w045/w046, w041/w042) resolved into a kept part, a dropped copy and a no-reference
            mask, gaps in the stack (no-reference intervals), partial windings, contact zones, the split
  audit     seating of every reference on the m7 surface prediction (recto-090 as an independent cross-check) in
            a seeded, bounded sample of chunks; regions whose peak sits more than 2 voxels off are unseated
  score     metrics of one candidate with the controls run beside it, under the frozen rule; a run whose
            controls fail is invalid and gets no verdict
  controls  the controls at one site per reference, and neighbour substitution for every adjacent pair
  predscore contact separation of a surface prediction (m7, recto-090, a candidate zarr) on the contact lines of
            adjacent windings 5 to 8 voxels apart, in a seeded chunk sample or box-only, with guards (seating, fill
            between sheets, continuity of both sheets, volume and band thickness), a paired cluster bootstrap against
            every bar arm and a matched-budget erosion null, and controls (an A/A read through a second reader,
            dilated, lattice-cut, CT-thresholded and shifted maps, displaced lines, a reference oracle on development
            chunks); PRED_RULE version 2, version 1 kept (--rule-version 1)
  framecheck  is a released local map in m7's frame on its box (Dice with m7 at shifts up to 4 voxels)
  gscore    per-winding credit G_w of a trace for AutoPipeline's tracing stage (kit/gscore.py): the labelled area
            of its winding in the band z 4352 to 4864 covered by the part reached from its seed (seams followed,
            transverse switches not), gated on switch line and self-crossings against the reference's own, with
            planted controls that set the gate thresholds and must be able to fail

RULE holds every distance, mask and the acceptance bar. Every score and controls run carries the SHA-256 digest of
the whole rule; the manifest carries the digest of the parts the references depend on and the audit that of the
parts seating depends on, so references or an audit built under other settings are refused. PHerc0139 volumes and
segments are in villa's neural tracing training configs, so this is a pipeline benchmark (a note of the source repository).
Every label here comes from published traces and model output; nothing here is a reading. Needs numpy and scipy.
"""

import collections
import concurrent.futures
import hashlib
import html
import json
import math
import re
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from . import kithome

SAMPLE = "PHerc0139"
VOLUME = "20250728140407"
VOXEL_UM = 9.362
VOXEL_TAG = "9.362um"
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
PRED_DIR = f"{SAMPLE}/representations/predictions/surfaces"
PRED_M7 = f"{PRED_DIR}/20250728140407-surface-20260413222639-surface-m7-L0-th0.2.zarr"
PRED_RECTO = f"{PRED_DIR}/20250728140407-surface-20250701154204-surface-recto-090.zarr"
REL_ROOT = Path("work") / "surfbench"            # under the kit home (KIT_HOME; kit/kithome.py)
REL_REFS = REL_ROOT / "refs" / f"{SAMPLE}-{VOLUME}"
DEFAULT_ROOT = kithome.home() / REL_ROOT
DEFAULT_REFS = DEFAULT_ROOT / "refs" / f"{SAMPLE}-{VOLUME}"
DEFAULT_CACHE = DEFAULT_ROOT / "cache"
MESH_FILES = ("x.tif", "y.tif", "z.tif", "meta.json")
TUNE = [f"w{n:03d}" for n in range(23, 41)]
REPORT = [f"w{n:03d}" for n in range(43, 60)]
BLOCK = 128                 # voxels: coarse occupancy blocks for picking which references can be near a point

# Frozen before any automatic trace was scored. The acceptance bar comes only from the controls and the
# reference properties measured on the real stack (a note of the source repository, "The frozen rule").
RULE = {
    # version 2 (review, 9 October 2026): chain steps and pitch from the direct pair offsets, not the least-squares
    # positions; a gap side needs the next sheet absent or, when it is not an adjacent winding across a non-gap
    # step, farther than gap_factor pitches; the off-sheet drift control; displaced moves scored against the
    # references near where they land
    "version": 2,
    "frame": {"sample": SAMPLE, "volume": VOLUME, "voxel_um": VOXEL_UM},
    "distance": {
        "primary_vox": 4.0,            # d for the acceptance metric, in seated or unaudited regions
        "secondary_vox": 2.0,          # d reported beside it, in audited seated regions only
        "upsample": 2,                 # reference grids made 2x denser (bilinear) before point-to-plane matching
        "footprint_steps": 1.5,        # inside a footprint: lateral offset within 1.5 dense grid steps
        "neighbour_max_vox": 64.0,     # farthest normal offset a match counts at
        "blend_vertices": 4,           # offset blended over this many nearest vertices of one part
    },
    "references": {
        "coincide_vox": 2.0,           # duplicate test distance
        "duplicate_share": 0.25,       # pairs with this share of either mesh within 2 voxels are one sheet
        "strip_vox": 4.0,              # a duplicate's vertices this close to the kept mesh are dropped
        "part_spread_vox": 4.0,        # a duplicate's departing part is one sheet when its offsets cluster this tight
        "part_consistent_share": 0.6,  # ... over this share of it
        "part_min_offset_vox": 6.0,    # ... and it sits at least this far from the kept mesh
        "part_min_vertices": 200,
        "contact_vox": 8.0,            # contact zone: another winding within 2 d
        "gap_factor": 1.5,             # a gap: chain step, or next sheet not an adjacent winding, over 1.5 pitches
        "partial_inside_share": 0.8,   # partial: a chain neighbour projects under 80 % inside it
        "min_pair_matches": 500,
        "self_far_cells": 4,           # two vertices of one mesh this many native cells apart are different parts
        "match_k": 8,                  # nearest dense vertices looked at for another part of the same mesh
    },
    "seating": {
        "prediction": PRED_M7,
        "cross_check": PRED_RECTO,
        "threshold": 128,
        "max_offset_vox": 8,
        "seated_vox": 2,               # peak more than 2 voxels off along the normal: unseated
        "min_peak_share": 0.2,         # a peak under this share is weak (the prediction barely sees the sheet)
        "chunks_per_winding": 40,
        "recto_per_winding": 8,
        "min_chunk_vertices": 20,
        "chunk_margin_vox": 10,
        "seed": 0,
    },
    "scoring": {"bridge_vertices": 5, "noref_near_vox": 8.0},
    "accept": {"metric": "dominant_precision_d4", "bar": 0.8, "min_scored_share": 0.5,
               "bar_margin": 0.05, "bar_step": 0.05},   # choose_bar: midpoint of the controls, floored to a step
    "controls": {
        "positive_min": 0.98,
        "offsets_vox": [1.0, 2.0, 3.0],
        "offset_bands": [[0.95, 1.0], [0.3, 0.7], [0.0, 0.05]],
        "offset_jitter_vox": 0.5,
        "tolerance_vox": 2.0,
        "displace_z_vox": [200.0, 400.0, 800.0],
        "planted_share": [0.3, 0.7],
        "planted_label_tolerance": 0.15,
        "planted_row_share": 0.5,
        "ramp_cols": 4,
        "drift_clear_vox": 1.0,        # drift: moved to the midpoint where it lies over d4 + 1 from both windings
        "drift_off_min": 0.8,          # ... and at least this share of the moved vertices must be scored off
        "neighbour_margin": 0.05,
        "min_neighbour_cover": 0.3,
        "window": [40, 100],
        "global_window": 64,
        "seed": 0,
    },
    "split": {"tune": TUNE, "report": REPORT,
              "note": "tune trace settings on w023 to w040, report on w043 to w059; w041/w042 lie between"},
}

CONTROL_KEYS = ("positive", "offset_sweep", "displaced", "planted_hard", "planted_ramp", "planted_drift", "neighbour")
NOREF, DROPPED = -1, -2                  # reference vertex labels besides a winding id
ON, OFF, OUTSIDE, GAP, NOREFC, UNSEATED, UNAUDITED = 1, 0, -1, -2, -3, -4, -5
CLASS_NAMES = {OUTSIDE: "outside", GAP: "gap", NOREFC: "no_reference", UNSEATED: "unseated", UNAUDITED: "unaudited"}
SEAT_UNAUDITED, SEATED, SEAT_OFF, SEAT_WEAK = 0, 1, 2, 3
SEAT_NAMES = {SEATED: "seated", SEAT_OFF: "unseated", SEAT_WEAK: "weak"}


class BenchError(ValueError):
    """A problem the caller can fix: missing references, a changed rule, an unreadable surface."""


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def digest(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def rule_digest(rule=None):
    """Digest of the whole rule: what a score is reported under."""
    return digest(RULE if rule is None else rule)


REFS_PARTS = ("version", "frame", "distance", "references", "split")
SEAT_PARTS = REFS_PARTS + ("seating",)


def part_digest(rule, parts):
    """Digest of the parts of the rule a stage depends on. The references depend on REFS_PARTS and the audit
    on SEAT_PARTS, so the acceptance bar can be frozen from the controls on built references without
    rebuilding them; any change to those parts still forces a rebuild."""
    rule = RULE if rule is None else rule
    return digest({k: rule[k] for k in parts})


RULE_DIGEST = rule_digest()


def _np():
    try:
        import numpy
    except ImportError as exc:
        raise BenchError("kit surfbench needs numpy and scipy") from exc
    return numpy


def _kdtree():
    try:
        from scipy.spatial import cKDTree
    except ImportError as exc:
        raise BenchError("kit surfbench needs scipy (cKDTree)") from exc
    return cKDTree


def _r(x, n=4):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else (x if math.isinf(x) else round(x, n))


def _say(log, msg):
    if log:
        log(msg)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- grids

def read_tifxyz(path):
    """(xyz (H, W, 3) float64, valid (H, W), meta) of a tifxyz folder; -1, NaN and all-zero vertices are holes."""
    np = _np()
    from . import snap
    try:
        xs, ys, zs, valid = snap.load_mesh(path)
    except snap.SnapError as exc:
        raise BenchError(str(exc)) from exc
    xyz = np.stack([xs, ys, zs], -1).astype(np.float64)
    valid = valid & (xyz.sum(-1) > 0)
    meta = {}
    mp = Path(path) / "meta.json"
    if mp.is_file():
        try:
            meta = json.loads(mp.read_text())
        except json.JSONDecodeError:
            meta = {}
    return xyz, valid, meta


def write_tifxyz(path, xyz, valid, meta=None):
    """x/y/z.tif (float32, -1 at holes) and meta.json, with kit's standard-library TIFF writer."""
    np = _np()
    from . import vc3d_io
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate("xyz"):
        a = np.where(valid, xyz[..., i], -1.0).astype(np.float32)
        vc3d_io.write_tiff(path / f"{c}.tif", vc3d_io.raster_from_numpy(a))
    m = dict(meta or {"format": "tifxyz", "type": "seg", "scale": [0.05, 0.05]})
    if valid.any():
        p = xyz[valid]
        m["bbox"] = [p.min(0).tolist(), p.max(0).tolist()]
    (path / "meta.json").write_text(json.dumps(m, indent=2))
    return path


def grid_geometry(xyz, valid):
    """(normals (H, W, 3), area per vertex in voxels^2, ok, median edge length) of a grid: central differences
    where both neighbours are valid, else one-sided (as kit snap); ok = valid with a finite normal."""
    np = _np()
    P = np.where(valid[..., None], xyz, np.nan)
    with np.errstate(invalid="ignore"):
        def grad(axis):
            n = P.shape[axis]
            fwd = np.full_like(P, np.nan)
            bwd = np.full_like(P, np.nan)
            sl = [slice(None)] * 3
            lo, hi = list(sl), list(sl)
            lo[axis], hi[axis] = slice(0, n - 1), slice(1, n)
            fwd[tuple(lo)] = P[tuple(hi)] - P[tuple(lo)]
            bwd[tuple(hi)] = P[tuple(hi)] - P[tuple(lo)]
            f_ok = np.isfinite(fwd).all(-1)
            b_ok = np.isfinite(bwd).all(-1)
            return np.where((f_ok & b_ok)[..., None], 0.5 * (fwd + bwd), np.where(f_ok[..., None], fwd, bwd))

        tu, tv = grad(1), grad(0)
        n = np.cross(tu, tv)
        nn = np.linalg.norm(n, axis=-1)
        ok = valid & np.isfinite(nn) & (nn > 1e-9)
        normals = np.where(ok[..., None], n / np.where(ok, nn, 1.0)[..., None], np.nan)
        area = np.where(ok, nn, 0.0)
        edges = [np.linalg.norm(np.diff(P, axis=a), axis=-1) for a in (0, 1)]
    el = np.concatenate([e[np.isfinite(e)] for e in edges])
    return normals, area, ok, (float(np.median(el)) if el.size else float("nan"))


def upsample(xyz, valid, k):
    """A k-times denser grid by bilinear interpolation: rows i + a/k, cols j + b/k. A new vertex is valid when
    every corner it uses is; original vertices are kept exactly. Returns (xyz, valid, src) where src is the flat
    index of the top-left native vertex each one came from."""
    np = _np()
    H, W = valid.shape
    idx = np.arange(H * W).reshape(H, W)
    if k <= 1:
        return xyz, valid, idx
    Hu, Wu = (H - 1) * k + 1, (W - 1) * k + 1
    out = np.full((Hu, Wu, 3), np.nan)
    ov = np.zeros((Hu, Wu), bool)
    src = np.zeros((Hu, Wu), np.int64)
    for a in range(k):
        for b in range(k):
            h, w = (H if a == 0 else H - 1), (W if b == 0 else W - 1)
            if h <= 0 or w <= 0:
                continue
            fa, fb = a / k, b / k
            acc = (1 - fa) * (1 - fb) * xyz[:h, :w]
            v = valid[:h, :w].copy()
            if a:
                acc = acc + fa * (1 - fb) * xyz[1:h + 1, :w]
                v &= valid[1:h + 1, :w]
            if b:
                acc = acc + (1 - fa) * fb * xyz[:h, 1:w + 1]
                v &= valid[:h, 1:w + 1]
            if a and b:
                acc = acc + fa * fb * xyz[1:h + 1, 1:w + 1]
                v &= valid[1:h + 1, 1:w + 1]
            out[a::k, b::k] = acc
            ov[a::k, b::k] = v
            src[a::k, b::k] = idx[:h, :w]
    out[~ov] = np.nan
    return out, ov, src


def block_keys(points):
    """Codes of the BLOCK^3 boxes holding (x, y, z) points."""
    np = _np()
    b = np.floor(np.asarray(points)[:, ::-1] / BLOCK).astype(np.int64)
    return (b[:, 0] << 20) | (b[:, 1] << 10) | b[:, 2]


def dilate_keys(keys):
    np = _np()
    u = np.unique(keys)
    z, y, x = u >> 20, (u >> 10) & 1023, u & 1023
    out = [((z + dz) << 20) | ((y + dy) << 10) | (x + dx)
           for dz in (-1, 0, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    return np.unique(np.concatenate(out))


class Ref:
    """One reference (or candidate) surface: its native grid, per-vertex labels and attributes, and its dense
    scoring points with a KD-tree built on first use."""

    def __init__(self, name, gid, xyz, valid, rule=None, label=None):
        np = _np()
        rule = rule or RULE
        D = rule["distance"]
        self.name, self.gid = name, gid
        self.xyz, self.valid = xyz, valid
        self.normals, self.area, self.ok, self.step = grid_geometry(xyz, valid)
        self.label = (np.where(valid, gid, DROPPED).astype(np.int32) if label is None
                      else np.asarray(label, dtype=np.int32))
        self.seat = np.zeros(valid.shape, np.int8)
        self.attrs = {}
        self.k, self.foot_steps, self.neigh = int(D["upsample"]), float(D["footprint_steps"]), float(D["neighbour_max_vox"])
        self.match_k, self.far_cells = int(rule["references"]["match_k"]), int(rule["references"]["self_far_cells"])
        self.blend = int(D["blend_vertices"])
        self._pts = self._tree = self._keys = None

    def reset(self):
        self._pts = self._tree = self._keys = None

    def usable(self):
        """Native vertices that take part in matching: a normal, and not dropped as a duplicate."""
        return self.ok & (self.label != DROPPED)

    def labelled(self):
        return self.ok & (self.label == self.gid)

    def scoring(self):
        """(points, normals, native source index, dense step) of the dense grid."""
        if self._pts is None:
            keep = self.valid & (self.label != DROPPED)
            up, uv, src = upsample(self.xyz, keep, self.k)
            un, _, uok, ustep = grid_geometry(up, uv)
            if not math.isfinite(ustep):
                ustep = self.step / max(self.k, 1) if math.isfinite(self.step) else 1.0
            self._pts = (up[uok], un[uok], src[uok], ustep)
        return self._pts

    def footprint(self):
        return self.foot_steps * self.scoring()[3]

    def tree(self):
        if self._tree is None:
            self._tree = _kdtree()(self.scoring()[0])
        return self._tree

    def keys(self):
        if self._keys is None:
            u = self.usable()
            self._keys = dilate_keys(block_keys(self.xyz[u])) if u.any() else _np().zeros(0, _np().int64)
        return self._keys


def match(P, ref, workers=2, dist=False):
    """Each point against one reference: the signed offset s along the reference normal at its nearest dense
    vertex (point to plane, blended over the nearest blend_vertices of that part of the mesh), whether it
    projects inside the footprint (lateral offset within the footprint and |s| within neighbour_max_vox), that
    vertex's native index, and its normal. With dist (off by default, 14 October 2026), also the straight-line
    distance from each point to that dense vertex (NaN where none was found), as a fifth element."""
    np = _np()
    dist_out = bool(dist)
    P = np.asarray(P, dtype=np.float64).reshape(-1, 3)
    pts, nrm, src, _ = ref.scoring()
    n = len(P)
    if n == 0 or len(pts) == 0:
        out = (np.full(n, np.nan), np.zeros(n, bool), np.zeros(n, np.int64), np.zeros((n, 3)))
        return out + (np.full(n, np.nan),) if dist_out else out
    foot = ref.footprint()
    upper = math.hypot(ref.neigh, foot) + 1e-6
    k = max(1, int(ref.match_k))
    dist, j = ref.tree().query(P, k=k, distance_upper_bound=upper, workers=workers)
    if k == 1:
        dist, j = dist[:, None], j[:, None]
    found = np.isfinite(dist)
    jj = np.where(found, j, 0)
    v = P[:, None, :] - pts[jj]
    s = np.einsum("ikj,ikj->ik", v, nrm[jj])
    lat2 = np.einsum("ikj,ikj->ik", v, v) - s * s
    inside = found & (lat2 <= foot * foot) & (np.abs(s) <= ref.neigh)
    pick = np.zeros(n, np.int64)
    if k > 1:
        # Where a mesh overlaps itself (a winding traced past its seam, a fold), the nearest dense vertex can
        # belong to the other part. Among the k nearest, a vertex of another part of the mesh (more than
        # self_far_cells native cells from the nearest) that lies inside the footprint and nearer along its
        # normal is taken instead: the distance is to the nearer part, not to the nearer vertex.
        W = ref.valid.shape[1]
        r0, c0 = np.divmod(src[jj[:, :1]], W)
        rr, cc = np.divmod(src[jj], W)
        far = np.maximum(np.abs(rr - r0), np.abs(cc - c0)) > ref.far_cells
        alt = inside & far & (np.abs(s) < np.abs(s[:, :1]))
        score = np.where(alt, np.abs(s), np.inf)
        best = np.argmin(score, axis=1)
        pick = np.where(np.isfinite(score[np.arange(n), best]), best, 0)
    ar = np.arange(n)
    jp = jj[ar, pick]
    sp = s[ar, pick]
    fp = found[ar, pick]
    if k > 1 and ref.blend > 1:
        # the offset is blended over the `blend` nearest vertices of the chosen part (inverse square distance),
        # which follows the surface between vertices better than the nearest vertex's plane alone
        W = ref.valid.shape[1]
        rr, cc = np.divmod(src[jj], W)
        rp, cp = np.divmod(src[jp], W)
        same = found & (np.maximum(np.abs(rr - rp[:, None]), np.abs(cc - cp[:, None])) <= ref.far_cells)
        same &= np.cumsum(same, axis=1) <= ref.blend
        w = np.where(same, 1.0 / np.maximum(np.where(found, dist, 1.0), 1e-6) ** 2, 0.0)
        tot = w.sum(1)
        sb_ = np.where(tot > 0, (w * np.where(found, s, 0.0)).sum(1) / np.where(tot > 0, tot, 1.0), sp)
        sp = np.where(fp, sb_, sp)
    out = (np.where(fp, sp, np.nan), inside[ar, pick], src[jp], nrm[jp])
    return out + (np.where(fp, dist[ar, pick], np.nan),) if dist_out else out


# ---------------------------------------------------------------- listing and download

def _list(prefix, opener=None):
    """(sub-prefixes, keys) one level under a bucket prefix, through kit/s3retry.py."""
    from . import s3retry
    dirs, keys, token, seen = [], [], None, set()
    while True:
        url = (f"{BUCKET}/?list-type=2&max-keys=1000&delimiter=%2F&prefix={urllib.parse.quote(prefix)}"
               + (f"&continuation-token={urllib.parse.quote(token, safe='')}" if token else ""))
        with s3retry.open_url(url, opener, 60) as resp:
            xml = resp.read().decode("utf-8", "replace")
        dirs += [html.unescape(p) for p in re.findall(r"<CommonPrefixes><Prefix>([^<]+)</Prefix>", xml)]
        keys += [html.unescape(k) for k in re.findall(r"<Key>([^<]+)</Key>", xml)]
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", xml)
        if not m:
            return dirs, keys
        token = html.unescape(m.group(1))
        if token in seen:
            raise BenchError("bucket listing repeated a continuation token")
        seen.add(token)


def find_meshes(opener=None, sample=SAMPLE, volume=VOLUME, voxel_tag=VOXEL_TAG):
    """The winding folders of a sample's segments and, for each, the bucket prefix of its tifxyz in the given
    volume's frame. Returns (found [{name, folder, prefix}], skipped [{folder, reason}])."""
    dirs, _ = _list(f"{sample}/segments/", opener)
    found, skipped, used = [], [], set()
    for d in sorted(dirs):
        folder = d.rstrip("/").rsplit("/", 1)[-1]
        m = re.search(r"-(w\d{3})_", folder)
        if not m:
            skipped.append({"folder": folder, "reason": "not a winding (no wNNN in its name)"})
            continue
        sub, _ = _list(d + "mesh/", opener)
        hit = [s for s in sub if s.rstrip("/").endswith(f"-on-{volume}-{voxel_tag}.tifxyz")]
        if not hit:
            skipped.append({"folder": folder, "reason": f"no tifxyz in the frame of {volume}"})
            continue
        name = m.group(1)
        if name in used:
            name = f"{name}-{folder.split('-')[0]}"
        used.add(name)
        found.append({"name": name, "folder": folder, "prefix": hit[0].rstrip("/")})
    return found, skipped


def _download(url, dest, opener=None, optional=False):
    from . import autopipe
    try:
        return autopipe.download(url, dest, opener, optional=optional)
    except autopipe.AutoError as exc:
        raise BenchError(str(exc)) from exc


def build_refs(dest=DEFAULT_REFS, opener=None, log=None, workers=2, rule=None):
    """Download the windings of PHerc0139 in the 20250728140407 frame into dest/meshes/<wNNN>/, then build the
    reference manifest (build_manifest). Returns the manifest."""
    dest = Path(dest)
    t0 = time.time()
    found, skipped = find_meshes(opener)
    _say(log, f"surfbench: {len(found)} winding meshes in frame {VOLUME}, {len(skipped)} folders skipped")
    jobs = [(m, f) for m in found for f in MESH_FILES]

    def get(job):
        m, f = job
        out = dest / "meshes" / m["name"] / f
        if out.is_file() and out.stat().st_size > 0:
            return 0
        _download(f"{BUCKET}/{urllib.parse.quote(m['prefix'])}/{f}", out, opener)
        return 1

    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        fetched = sum(pool.map(get, jobs))
    _say(log, f"surfbench: fetched {fetched} files ({time.time() - t0:.0f} s)")
    sources = {m["name"]: {"folder": m["folder"], "prefix": m["prefix"]} for m in found}
    return build_manifest(dest, {m["name"]: dest / "meshes" / m["name"] for m in found}, sources=sources,
                          skipped=skipped, rule=rule, log=log, workers=workers)


# ---------------------------------------------------------------- the reference manifest

def _pair_stats(A, B, sel, m, labelled_only=False):
    np = _np()
    s, inside, src, nb = m
    nA = int(A.labelled().sum() if labelled_only else A.ok.sum())
    if labelled_only:
        keep = (A.label[sel] == A.gid) & (B.label.ravel()[src] == B.gid)
        inside = inside & keep
    si = s[inside]
    dots = np.einsum("ij,ij->i", A.normals[sel][inside], nb[inside])
    out = {"n": nA, "matched": int(inside.sum())}
    if nA:
        out.update({"inside": float(inside.sum() / nA), "cov2": float((np.abs(si) <= 2).sum() / nA),
                    "cov4": float((np.abs(si) <= 4).sum() / nA), "cov8": float((np.abs(si) <= 8).sum() / nA)})
    if si.size:
        out["median_s"] = float(np.median(si))
        out["orient"] = 1 if float(np.median(dots)) >= 0 else -1
    return out


def _all_pairs(refs, log, workers, labelled_only=False, per_vertex=None):
    """Directed pair statistics A -> B (A's vertices against B's tree) for every pair whose blocks meet. When
    per_vertex is given, per_vertex(A, B, sel, m) is called for each pair as well."""
    np = _np()
    stats = {}
    for B in refs:
        if not B.usable().any():
            continue
        dil = B.keys()
        for A in refs:
            if A is B:
                continue
            base = A.labelled() if labelled_only else A.usable()
            if not base.any():
                continue
            sel = base.copy()
            sel[base] = np.isin(block_keys(A.xyz[base]), dil)
            if not sel.any():
                continue
            m = match(A.xyz[sel], B, workers)
            stats[(A.gid, B.gid)] = _pair_stats(A, B, sel, m, labelled_only)
            if per_vertex is not None:
                per_vertex(A, B, sel, m)
        _say(log, f"surfbench:   pairs against {B.name} done")
    return stats


def _orient(refs, stats, min_pairs):
    """+1/-1 per reference so that normals agree across overlapping meshes (spanning tree from the largest), then
    flipped as a whole so they point away from the slice centroids (outward) on average."""
    np = _np()
    n = len(refs)
    adj = collections.defaultdict(list)
    for (a, b), st in stats.items():
        if st.get("matched", 0) >= min_pairs and "orient" in st:
            adj[a].append((st["matched"], b, st["orient"]))
            adj[b].append((st["matched"], a, st["orient"]))
    orient = [0] * n
    order = sorted(range(n), key=lambda i: -float(refs[i].area.sum()))
    for root in order:
        if orient[root]:
            continue
        orient[root] = 1
        queue = [root]
        while queue:
            cur = queue.pop(0)
            for _, nb, sg in sorted(adj[cur], reverse=True):
                if not orient[nb]:
                    orient[nb] = orient[cur] * sg
                    queue.append(nb)
    conflicts = sum(1 for (a, b), st in stats.items()
                    if st.get("matched", 0) >= min_pairs and "orient" in st and orient[a] * orient[b] != st["orient"])
    pts = np.concatenate([r.xyz[r.ok] for r in refs if r.ok.any()])
    slab = np.floor(pts[:, 2] / 256).astype(np.int64)
    u, inv = np.unique(slab, return_inverse=True)
    cx = np.bincount(inv, pts[:, 0]) / np.bincount(inv)
    cy = np.bincount(inv, pts[:, 1]) / np.bincount(inv)
    vote = 0.0
    for r, o in zip(refs, orient):
        if not r.ok.any():
            continue
        p, nr = r.xyz[r.ok], r.normals[r.ok]
        k = np.searchsorted(u, np.floor(p[:, 2] / 256).astype(np.int64))
        rad = np.stack([p[:, 0] - cx[k], p[:, 1] - cy[k]], 1)
        rad /= np.maximum(np.linalg.norm(rad, axis=1, keepdims=True), 1e-9)
        vote += o * float(np.mean(nr[:, 0] * rad[:, 0] + nr[:, 1] * rad[:, 1]))
    if vote < 0:
        orient = [-o for o in orient]
    return orient, conflicts


def _resolve_duplicates(refs, stats, orient, R, log, workers):
    """Group near-duplicate meshes, choose which one keeps the shared sheet, drop the copy's coincident vertices
    and label or mask what departs from it. Returns the group records."""
    np = _np()
    by_gid = {r.gid: r for r in refs}
    parent = {r.gid: r.gid for r in refs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for (a, b), st in stats.items():
        back = stats.get((b, a), {})
        if max(st.get("cov2", 0), back.get("cov2", 0)) >= R["duplicate_share"]:
            parent[find(a)] = find(b)
    groups = collections.defaultdict(list)
    for g in parent:
        groups[find(g)].append(g)
    records = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda g: -float(by_gid[g].area.sum()))
        primary = _choose_primary([by_gid[g] for g in members], refs, stats, R, workers)
        P = primary
        rec = {"members": [by_gid[g].name for g in members], "kept": P.name,
               "pairs": {f"{by_gid[a].name}->{by_gid[b].name}": _r(stats.get((a, b), {}).get("cov2"))
                         for a in members for b in members if a != b}, "copies": []}
        for g in members:
            S = by_gid[g]
            if S is P:
                continue
            rec["copies"].append(_split_copy(P, S, orient[P.gid], R, workers))
        records.append(rec)
        _say(log, f"surfbench: duplicates {rec['members']}: kept {P.name}; "
                  + "; ".join(f"{c['name']} {c['outcome']}" for c in rec["copies"]))
    return records


def _choose_primary(members, refs, stats, R, workers):
    """The member that stays on one sheet where the members disagree: its offset to the nearest other winding is
    the same where it departs from the others as where it coincides with them. Ties go to the larger area."""
    np = _np()
    gids = {m.gid for m in members}
    scores = []
    for M in members:
        others = [o for o in members if o is not M]
        nbrs = sorted(((st.get("matched", 0), b) for (a, b), st in stats.items()
                       if a == M.gid and b not in gids), reverse=True)
        if not nbrs or not others:
            scores.append((math.inf, M))
            continue
        N = next(r for r in refs if r.gid == nbrs[0][1])
        sel = M.usable()
        P = M.xyz[sel]
        dep = np.ones(len(P), bool)
        for O in others:
            s, ins, _, _ = match(P, O, workers)
            dep &= ~(ins & (np.abs(s) <= R["strip_vox"]))
        s, ins, _, _ = match(P, N, workers)
        a, b = s[ins & dep], s[ins & ~dep]
        if a.size < R["part_min_vertices"] or b.size < R["part_min_vertices"]:
            scores.append((math.inf, M))
            continue
        scores.append((abs(float(np.median(a)) - float(np.median(b))), M))
    best = min(s for s, _ in scores)
    if not math.isfinite(best):
        return members[0]
    return next(M for s, M in scores if s == best)


def _split_copy(P, S, orient_p, R, workers):
    """S's vertices within strip_vox of P are dropped. What departs is kept as S's own partial sheet when its
    offsets from P cluster at one distance (a copy moved one winding, like w046), else it and the part of P under
    it become no-reference masks (an ambiguous pair, like w041/w042)."""
    np = _np()
    sel = S.usable()
    s, ins, _, _ = match(S.xyz[sel], P, workers)
    coinc = ins & (np.abs(s) <= R["strip_vox"])
    dep = ~coinc
    dep_in = dep & ins
    o = orient_p * s
    lab = S.label.copy()
    flat = np.flatnonzero(sel.ravel())
    lab.ravel()[flat[coinc]] = DROPPED
    out = {"name": S.name, "dropped_share": _r(coinc.mean()), "departing_vertices": int(dep.sum())}
    if dep.sum() < R["part_min_vertices"]:
        lab.ravel()[flat[dep]] = NOREF
        out["outcome"] = "a copy: coincident part dropped, the rest masked"
        S.label = lab
        S.reset()
        return out
    med = float(np.median(o[dep_in])) if dep_in.any() else float("nan")
    near = dep_in & (np.abs(o - med) <= R["part_spread_vox"])
    share = float(near.sum() / max(dep_in.sum(), 1))
    out.update({"departing_median_offset_vox": _r(med, 2), "departing_clustered_share": _r(share)})
    consistent = dep_in.any() and share >= R["part_consistent_share"] and abs(med) >= R["part_min_offset_vox"]
    if consistent:
        keep = near | (dep & ~ins)
        lab.ravel()[flat[dep & ~keep]] = NOREF
        out["outcome"] = "moved part kept as its own partial winding"
        out["kept_part_share"] = _r(keep.sum() / max(sel.sum(), 1))
        S.label = lab
        S.reset()
        return out
    lab.ravel()[flat[dep]] = NOREF
    S.label = lab
    S.reset()
    tmp = Ref(S.name, S.gid, S.xyz, S.valid, label=np.where(lab == NOREF, S.gid, DROPPED))
    tmp.k, tmp.foot_steps, tmp.neigh = S.k, S.foot_steps, S.neigh
    psel = P.usable()
    _, pin, _, _ = match(P.xyz[psel], tmp, workers)
    plab = P.label.copy()
    pflat = np.flatnonzero(psel.ravel())
    plab.ravel()[pflat[pin]] = NOREF
    P.label = plab
    P.reset()
    out["outcome"] = "ambiguous: the disputed parts of both are no-reference masks"
    out["masked_share_of_kept"] = _r(pin.sum() / max(psel.sum(), 1))
    return out


def _positions(refs, stats, orient, min_pairs, neigh):
    """Normal position of every labelled reference (voxels, outward positive) by least squares over the median
    offsets of overlapping pairs; None for references linked to no other."""
    np = _np()
    ids = [r.gid for r in refs if r.labelled().any()]
    eqs = []
    for (a, b), st in stats.items():
        if a in ids and b in ids and st.get("matched", 0) >= min_pairs and abs(st.get("median_s", 1e9)) <= neigh:
            eqs.append((a, b, orient[b] * st["median_s"], math.sqrt(st["matched"])))
    adj = collections.defaultdict(set)
    for a, b, _, _ in eqs:
        adj[a].add(b)
        adj[b].add(a)
    pos, comp = {}, {}
    for start in ids:
        if start in comp:
            continue
        cid = len(set(comp.values()))
        stack, members = [start], []
        comp[start] = cid
        while stack:
            x = stack.pop()
            members.append(x)
            for y in adj[x]:
                if y not in comp:
                    comp[y] = cid
                    stack.append(y)
        if len(members) == 1:
            pos[start] = None if not adj[start] else 0.0
            continue
        col = {g: i for i, g in enumerate(sorted(members))}
        rows, rhs = [], []
        for a, b, o, w in eqs:
            if a in col and b in col:
                row = np.zeros(len(col))
                row[col[a]], row[col[b]] = w, -w
                rows.append(row)
                rhs.append(w * o)
        row = np.zeros(len(col))
        row[col[min(members)]] = 1.0
        rows.append(row)
        rhs.append(0.0)
        x, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
        for g, i in col.items():
            pos[g] = float(x[i])
    return pos, comp, eqs


def self_overlap(ref, workers=2):
    """Per native vertex: the distance along the normal to another part of the same mesh (more than
    self_far_cells native cells away in the grid) that lies inside the footprint, or inf. A winding traced past
    its seam overlaps itself; the offset says whether it went on to the next turn (about one pitch) or traced its
    own sheet twice (a few voxels)."""
    np = _np()
    out = np.full(ref.valid.shape, np.inf, np.float32)
    sel = ref.usable()
    if not sel.any():
        return out
    pts, nrm, src, _ = ref.scoring()
    P = ref.xyz[sel]
    rc = np.argwhere(sel)
    W = ref.valid.shape[1]
    foot = ref.footprint()
    k = max(2, int(ref.match_k) * 2)
    dist, j = ref.tree().query(P, k=k, distance_upper_bound=math.hypot(ref.neigh, foot) + 1e-6, workers=workers)
    found = np.isfinite(dist)
    jj = np.where(found, j, 0)
    rr, cc = np.divmod(src[jj], W)
    far = found & (np.maximum(np.abs(rr - rc[:, :1]), np.abs(cc - rc[:, 1:])) > ref.far_cells)
    v = P[:, None, :] - pts[jj]
    s = np.einsum("ikj,ikj->ik", v, nrm[jj])
    lat2 = np.einsum("ikj,ikj->ik", v, v) - s * s
    hit = far & (lat2 <= foot * foot)
    out[sel] = np.where(hit, np.abs(s), np.inf).min(1)
    return out


def build_manifest(dest, meshes, sources=None, skipped=None, rule=None, log=None, workers=2):
    """The reference manifest of a set of tifxyz windings in one frame (meshes: {name: folder}). Writes
    dest/attrs/<name>.npz (per-vertex labels, contact zones, gaps) and dest/manifest.json; returns the manifest."""
    np = _np()
    rule = rule or RULE
    D, R = rule["distance"], rule["references"]
    dest = Path(dest)
    t0 = time.time()
    names = sorted(meshes)
    if len(names) < 2:
        raise BenchError("a reference stack needs at least two windings")
    refs = []
    for gid, name in enumerate(names):
        xyz, valid, _ = read_tifxyz(meshes[name])
        refs.append(Ref(name, gid, xyz, valid, rule))
    _say(log, f"surfbench: {len(refs)} meshes read ({time.time() - t0:.0f} s); pass 1 (whole meshes)")
    stats1 = _all_pairs(refs, log, workers)
    orient, conflicts = _orient(refs, stats1, R["min_pair_matches"])
    groups = _resolve_duplicates(refs, stats1, orient, R, log, workers)

    # pass 2: labelled parts, per-vertex neighbours
    shape = {r.gid: r.valid.shape for r in refs}
    g_pos = {r.gid: np.full(shape[r.gid], np.inf, np.float32) for r in refs}
    g_neg = {r.gid: np.full(shape[r.gid], np.inf, np.float32) for r in refs}
    l_pos = {r.gid: np.full(shape[r.gid], -9, np.int32) for r in refs}
    l_neg = {r.gid: np.full(shape[r.gid], -9, np.int32) for r in refs}
    near_other = {r.gid: np.full(shape[r.gid], np.inf, np.float32) for r in refs}

    def per_vertex(A, B, sel, m):
        s, ins, src, nb = m
        flat = np.flatnonzero(sel.ravel())
        labB = B.label.ravel()[src]
        sg = np.sign(np.einsum("ij,ij->i", A.normals[sel], nb))
        t = -s * np.where(sg == 0, 1, sg)
        own = A.label.ravel()[flat]
        for side, gg, ll in ((1, g_pos[A.gid], l_pos[A.gid]), (-1, g_neg[A.gid], l_neg[A.gid])):
            tt = side * t
            cand = ins & (tt >= 0) & (tt < gg.ravel()[flat])
            gg.ravel()[flat[cand]] = tt[cand]
            ll.ravel()[flat[cand]] = labB[cand]
        diff = ins & (labB != own)
        no = near_other[A.gid].ravel()
        cur = no[flat[diff]]
        no[flat[diff]] = np.minimum(cur, np.abs(t[diff]))

    _say(log, f"surfbench: pass 2 (labelled parts) ({time.time() - t0:.0f} s)")
    _all_pairs(refs, log, workers, per_vertex=per_vertex)
    # two references on one sheet: where another winding lies within coincide_vox, neither can be told from the
    # other (a winding traced past its seam onto the next one's start, or a local copy); both become no-reference
    coincident = {}
    for r in refs:
        lab = r.labelled()
        hit = lab & (((g_pos[r.gid] <= R["coincide_vox"]) & (l_pos[r.gid] >= 0)) |
                     ((g_neg[r.gid] <= R["coincide_vox"]) & (l_neg[r.gid] >= 0)))
        coincident[r.gid] = (int(hit.sum()), int(lab.sum()))
        r.label[hit] = NOREF
    for r in refs:
        r.reset()
    selfov = {r.gid: self_overlap(r, workers) for r in refs}
    _say(log, f"surfbench: coincident parts masked, self-overlap measured ({time.time() - t0:.0f} s)")
    stats2 = _all_pairs(refs, None, workers, labelled_only=True)
    pos, comp, eqs = _positions(refs, stats2, orient, R["min_pair_matches"], D["neighbour_max_vox"])

    # the chain: labelled references in normal order (least-squares positions), each step measured directly
    # (the median offset of the two windings where they overlap, both ways), local pitch, gaps. The least-squares
    # positions order the windings but compress the steps: offsets to windings two or more turns away are
    # medians over the parts within neighbour_max_vox and inside the footprint, so the fit pulls the positions
    # together (on PHerc0139 every adjacent step came out 0.9 to 7.0 voxels shorter than measured directly).
    ordered = sorted((g for g in pos if pos[g] is not None), key=lambda g: (comp[g], pos[g]))
    by_gid = {r.gid: r for r in refs}
    chain = []
    for a, b in zip(ordered, ordered[1:]):
        if comp[a] != comp[b]:
            continue
        direct = [orient[b] * stats2[(a, b)]["median_s"]] if (a, b) in stats2 and "median_s" in stats2[(a, b)] else []
        if (b, a) in stats2 and "median_s" in stats2[(b, a)]:
            direct.append(-orient[a] * stats2[(b, a)]["median_s"])
        d_off = -float(np.mean(direct)) if direct else None
        chain.append({"inner": by_gid[a].name, "outer": by_gid[b].name, "offset_vox": pos[b] - pos[a],
                      "direct_offset_vox": d_off, "step_vox": d_off if d_off is not None else pos[b] - pos[a],
                      "cov2": stats2.get((b, a), {}).get("cov2"), "cov4": stats2.get((b, a), {}).get("cov4"),
                      "cov4_inner_to_outer": stats2.get((a, b), {}).get("cov4"),
                      "inside_outer_in_inner": stats2.get((b, a), {}).get("inside"),
                      "inside_inner_in_outer": stats2.get((a, b), {}).get("inside"),
                      "_ids": (a, b), "_comp": comp[a]})
    steps = [c["step_vox"] for c in chain]
    for i, c in enumerate(chain):
        local = [steps[j] for j in range(max(0, i - 2), min(len(steps), i + 3))
                 if j != i and chain[j]["_comp"] == c["_comp"]]
        c["local_pitch_vox"] = float(np.median(local)) if local else None
        c["gap"] = bool(local) and c["step_vox"] > R["gap_factor"] * c["local_pitch_vox"]
    pitch = {}
    for g in ordered:
        idx = [i for i, c in enumerate(chain) if g in c["_ids"]]
        win = [chain[j] for j in range(max(0, min(idx) - 1), min(len(chain), max(idx) + 2))
               if chain[j]["_comp"] == comp[g]] if idx else []
        vals = [c["step_vox"] for c in win if not c["gap"]] or [c["step_vox"] for c in win]
        pitch[g] = float(np.median(vals)) if vals else None
    neighbours = collections.defaultdict(list)
    adjacent = collections.defaultdict(set)        # chain neighbours across a step that is not a gap
    for c in chain:
        a, b = c.pop("_ids")
        c.pop("_comp")
        neighbours[a].append(b)
        neighbours[b].append(a)
        if not c["gap"]:
            adjacent[a].add(b)
            adjacent[b].add(a)

    attrs_dir = dest / "attrs"
    attrs_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    split_of = {n: "tune" for n in rule["split"]["tune"]}
    split_of.update({n: "report" for n in rule["split"]["report"]})
    for r in refs:
        lab = r.labelled()
        p = pitch.get(r.gid)
        gp, gn = g_pos[r.gid], g_neg[r.gid]
        if p:
            # a side is a gap where no sheet was found on it, or where the nearest sheet on it is not an adjacent
            # winding (across a step that is not a gap) and lies more than gap_factor pitches away: a winding
            # with no reference there. Where the adjacent winding is the next sheet, the space between is not a
            # gap however wide (local spacing has a long tail, a note of the source repository), so a candidate off every
            # winding there is scored.
            good = np.array(sorted(adjacent[r.gid]), dtype=np.int64)
            far = R["gap_factor"] * p
            gap_pos = lab & (~np.isfinite(gp) | ((gp > far) & ~np.isin(l_pos[r.gid], good)))
            gap_neg = lab & (~np.isfinite(gn) | ((gn > far) & ~np.isin(l_neg[r.gid], good)))
        else:
            gap_pos = gap_neg = np.zeros_like(lab)
        contact = r.usable() & (near_other[r.gid] <= R["contact_vox"])
        f = attrs_dir / f"{r.name}.npz"
        np.savez_compressed(f, label=r.label, contact=contact, g_pos=gp, g_neg=gn, lab_pos=l_pos[r.gid],
                            lab_neg=l_neg[r.gid], gap_pos=gap_pos, gap_neg=gap_neg, self_s=selfov[r.gid])
        nlab = int(lab.sum())
        partial_vs = {by_gid[n].name: _r(stats2.get((n, r.gid), {}).get("inside")) for n in neighbours[r.gid]}
        partial = bool(partial_vs) and min((v or 0.0) for v in partial_vs.values()) < R["partial_inside_share"]
        area_cm2 = float(r.area[lab].sum()) * (VOXEL_UM * 1e-4) ** 2
        mpath = Path(meshes[r.name])
        try:
            rel = str(mpath.resolve().relative_to(dest.resolve()))
        except ValueError:
            rel = str(mpath.resolve())
        rows.append({
            "name": r.name, "id": r.gid, "path": rel,
            "files": {fn: _sha256(mpath / fn) for fn in MESH_FILES if (mpath / fn).is_file()},
            "attrs_sha256": _sha256(f),
            "grid": list(r.valid.shape), "vertices": int(r.ok.sum()), "labelled_vertices": nlab,
            "labelled_share": _r(nlab / max(int(r.ok.sum()), 1)),
            "no_reference_share": _r(float((r.ok & (r.label == NOREF)).sum()) / max(int(r.ok.sum()), 1)),
            "dropped_share": _r(float((r.ok & (r.label == DROPPED)).sum()) / max(int(r.ok.sum()), 1)),
            "area_cm2": _r(area_cm2, 2), "grid_step_vox": _r(r.step, 2), "orient": orient[r.gid],
            "position_vox": _r(pos.get(r.gid), 2), "component": comp.get(r.gid),
            "rank": ordered.index(r.gid) if r.gid in ordered else None,
            "chain_neighbours": [by_gid[n].name for n in neighbours[r.gid]],
            "local_pitch_vox": _r(p, 2), "partial": partial, "neighbour_inside_share": partial_vs,
            "chain_adjacent": [by_gid[n].name for n in sorted(adjacent[r.gid])],
            "gap_share_outer": _r(float(((gap_pos if orient[r.gid] > 0 else gap_neg) & lab).sum()) / max(nlab, 1)),
            "gap_share_inner": _r(float(((gap_neg if orient[r.gid] > 0 else gap_pos) & lab).sum()) / max(nlab, 1)),
            # beside them: where no sheet was found on that side, and where the next sheet is over gap_factor
            # pitches away whatever it is (the old rule's gap, kept to show how wide the spacing runs)
            "no_sheet_share_outer": _r(float((lab & ~np.isfinite(gp if orient[r.gid] > 0 else gn)).sum())
                                       / max(nlab, 1)),
            "wide_share_outer": (_r(float((lab & ~((gp if orient[r.gid] > 0 else gn) <= R["gap_factor"] * p)).sum())
                                    / max(nlab, 1)) if p else None),
            "contact_share": _r(float((contact & lab).sum()) / max(nlab, 1)),
            "coincident_share": _r(coincident[r.gid][0] / max(coincident[r.gid][1], 1)),
            "self_overlap_share": _r(float((lab & (selfov[r.gid] <= R["contact_vox"])).sum()) / max(nlab, 1)),
            "self_overlap_within_d4_share": _r(float((lab & (selfov[r.gid] <= D["primary_vox"])).sum())
                                               / max(nlab, 1)),
            "split": split_of.get(r.name, "buffer"),
            **({"source": sources[r.name]} if sources and r.name in sources else {}),
        })
    tune_pos = [pos[by_name_gid] for n in rule["split"]["tune"]
                for by_name_gid in [next((r.gid for r in refs if r.name == n), None)] if pos.get(by_name_gid) is not None]
    rep_pos = [pos[g] for n in rule["split"]["report"]
               for g in [next((r.gid for r in refs if r.name == n), None)] if pos.get(g) is not None]
    separated = None
    if tune_pos and rep_pos:
        separated = max(tune_pos) < min(rep_pos) or min(tune_pos) > max(rep_pos)
    man = {
        "kind": "kit-surfbench-refs", "version": 1,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "refs_rule_digest": part_digest(rule, REFS_PARTS), "rule": {k: rule[k] for k in REFS_PARTS},
        "frame": rule["frame"],
        "references": rows,
        "order": [by_gid[g].name for g in ordered],
        "chain": [{k: (_r(v, 3) if isinstance(v, float) else v) for k, v in c.items()} for c in chain],
        "duplicates": groups,
        "orientation_conflicts": conflicts,
        "components": len(set(comp.values())),
        "split": {"tune": rule["split"]["tune"], "report": rule["split"]["report"],
                  "geometrically_separated": separated},
        "skipped_folders": skipped or [],
        "seconds": round(time.time() - t0, 1),
    }
    man["digest"] = digest({k: man[k] for k in man if k not in ("created", "seconds", "digest")})
    (dest / "manifest.json").write_text(json.dumps(man, indent=1))
    _say(log, f"surfbench: manifest written ({man['seconds']} s), digest {man['digest'][:12]}")
    return man


# ---------------------------------------------------------------- loading

def load_manifest(refs_dir, rule=None):
    p = Path(refs_dir) / "manifest.json"
    if not p.is_file():
        raise BenchError(f"{refs_dir}: no manifest.json; build it with python -m kit surfbench refs")
    man = json.loads(p.read_text())
    want = digest({k: man[k] for k in man if k not in ("created", "seconds", "digest")})
    if man.get("digest") != want:
        raise BenchError(f"{p}: the manifest does not match its digest (edited after it was built)")
    want = part_digest(rule, REFS_PARTS)
    if man.get("refs_rule_digest") != want:
        raise BenchError(f"{p}: built under rule {str(man.get('refs_rule_digest', ''))[:12]}, not the current "
                         f"rule {want[:12]}; rebuild the references (a changed rule is a new benchmark)")
    return man


def reference_scope(refs_dir, names, rule=None):
    """Validate and canonicalize a scope using metadata before opening payloads."""
    if names is None:
        return None
    if (not isinstance(names, (list, tuple)) or not names or
            any(not isinstance(n, str) or not n for n in names) or len(set(names)) != len(names)):
        raise BenchError("invalid or duplicate reference names")
    man = load_manifest(refs_dir, rule)
    available = [r["name"] for r in man["references"]]
    if set(names) - set(available):
        raise BenchError("unknown reference names")
    out = {"names": [n for n in available if n in names], "manifest_digest": man["digest"]}
    out["digest"] = digest(out)
    return out


def load_refs(refs_dir, rule=None, names=None, seat=True):
    """(manifest, [Ref]) with each reference's labels and attributes, and seating from audit.json when present."""
    np = _np()
    rule = rule or RULE
    refs_dir = Path(refs_dir)
    man = load_manifest(refs_dir, rule)
    scope = reference_scope(refs_dir, names, rule)
    if seat:
        au = load_audit(refs_dir, man, rule)
        if au and au.get("reference_scope") is not None and au["reference_scope"] != scope:
            raise BenchError("scoped seating audit requires the exact same reference scope")
    refs = []
    for rec in man["references"]:
        if names is not None and rec["name"] not in names:
            continue
        path = Path(rec["path"])
        path = path if path.is_absolute() else refs_dir / path
        xyz, valid, _ = read_tifxyz(path)
        f = refs_dir / "attrs" / f"{rec['name']}.npz"
        if _sha256(f) != rec["attrs_sha256"]:
            raise BenchError(f"{f}: changed since the manifest was built")
        with np.load(f) as a:
            attrs = {k: a[k] for k in a.files}
        r = Ref(rec["name"], rec["id"], xyz, valid, rule, label=attrs.pop("label"))
        r.attrs = attrs
        r.attrs["orient"] = rec["orient"]
        r.attrs["rank"] = rec["rank"]
        refs.append(r)
    if seat:
        apply_audit(refs_dir, refs, man, rule)
    return man, refs


def load_audit(refs_dir, man=None, rule=None):
    """audit.json checked against its digest, the manifest and the seating rule; None when absent."""
    p = Path(refs_dir) / "audit.json"
    if not p.is_file():
        return None
    au = json.loads(p.read_text())
    want = digest({k: au[k] for k in au if k not in ("created", "seconds", "digest", "chunks_read",
                                                    "cross_chunks_read")})
    if au.get("digest") != want:
        raise BenchError(f"{p}: the audit does not match its digest (edited after it was written)")
    if man is not None and au.get("manifest_digest") != man.get("digest"):
        raise BenchError(f"{p}: made for another manifest; run the audit again")
    if au.get("seat_rule_digest") != part_digest(rule, SEAT_PARTS):
        raise BenchError(f"{p}: made under another seating rule; run the audit again")
    return au


def apply_audit(refs_dir, refs, man=None, rule=None):
    """Seating status per vertex from audit.json; returns the audit or None."""
    np = _np()
    au = load_audit(refs_dir, man, rule)
    if au is None:
        return None
    C = np.array(au["chunk"], dtype=np.int64)
    for r in refs:
        regions = au["windings"].get(r.name, {}).get("regions", {})
        r.seat[:] = SEAT_UNAUDITED
        if not regions:
            continue
        code = {SEATED: [], SEAT_OFF: [], SEAT_WEAK: []}
        for key, reg in regions.items():
            st = {"seated": SEATED, "unseated": SEAT_OFF, "weak": SEAT_WEAK}[reg["status"]]
            code[st].append(tuple(int(v) for v in key.split("_")))
        zyx = np.floor(r.xyz[..., ::-1] / C).astype(np.int64)
        enc = (zyx[..., 0] << 20) | (zyx[..., 1] << 10) | zyx[..., 2]
        for st, keys in code.items():
            if keys:
                k = np.array(keys, dtype=np.int64)
                r.seat[np.isin(enc, (k[:, 0] << 20) | (k[:, 1] << 10) | k[:, 2]) & r.valid] = st
    return au


# ---------------------------------------------------------------- seating audit

class ChunkReader:
    """Level-0 chunks of a published zarr v2 prediction, cached under cache_dir. A chunk S3 reports missing
    (NoSuchKey) reads as None, the array's fill value (zeros), and is counted."""

    def __init__(self, prefix, cache_dir=DEFAULT_CACHE, opener=None):
        self.prefix, self.opener = prefix, opener
        self.root = Path(cache_dir) / prefix.rsplit("/", 1)[-1] / "0"
        meta = self.root / ".zarray"
        if not meta.is_file():
            _download(f"{BUCKET}/{prefix}/0/.zarray", meta, opener)
        self.meta = json.loads(meta.read_text())
        self.chunks = tuple(self.meta["chunks"])
        self.sep = self.meta.get("dimension_separator", ".")
        self.fetched = self.cached = self.missing = 0
        self._lock = threading.Lock()
        self._key_locks = {}

    def read(self, idx):
        # one thread at a time per chunk: two threads fetching one chunk share its .part file, and one could read
        # the chunk while the other's download is still being written into it
        key = self.sep.join(str(int(i)) for i in idx)
        with self._lock:
            lk = self._key_locks.setdefault(key, threading.Lock())
        with lk:
            return self._read(key)

    def _read(self, key):
        np = _np()
        from . import vc3d_audit
        f = self.root / key
        miss = f.with_name(f.name + ".missing")
        if miss.is_file():
            with self._lock:
                self.missing += 1
            return None
        if f.is_file():
            with self._lock:
                self.cached += 1
        else:
            if not _download(f"{BUCKET}/{self.prefix}/0/{key}", f, self.opener, optional=True):
                miss.parent.mkdir(parents=True, exist_ok=True)
                miss.write_text("")
                with self._lock:
                    self.missing += 1
                return None
            with self._lock:
                self.fetched += 1
        data = vc3d_audit._decompress(self.meta.get("compressor"), f.read_bytes())
        return np.frombuffer(data, dtype=np.dtype(self.meta["dtype"])).reshape(self.chunks)


def _profile(arr, local, nrm, offs, thr):
    np = _np()
    lim = np.array(arr.shape) - 1
    share = []
    for t in offs:
        q = np.clip(np.rint(local + t * nrm).astype(np.int64), 0, lim)
        share.append(float((arr[q[:, 0], q[:, 1], q[:, 2]] >= thr).mean()))
    return share


def _peak(share, offs):
    best = max(range(len(offs)), key=lambda i: (share[i], -abs(offs[i])))
    return int(offs[best]), share[best]


def _status(peak, peak_share, S):
    if peak_share < S["min_peak_share"]:
        return "weak"
    return "seated" if abs(peak) <= S["seated_vox"] else "unseated"


def audit(refs_dir=DEFAULT_REFS, reader=None, cross_reader=None, cache_dir=DEFAULT_CACHE, rule=None, log=None,
          opener=None, workers=2, reference_names=None, require_cross_check=False):
    """Seating of every reference on the surface prediction, region by region (one prediction chunk per region),
    in a seeded sample of at most chunks_per_winding chunks per winding (chunks read for one winding count for
    every winding they hold). Per region: share on the prediction at offset 0 and the peak offset along the
    outward normal within +-max_offset_vox. The cross-check prediction is read for the first recto_per_winding
    regions of each winding. Writes refs_dir/audit.json; returns it."""
    np = _np()
    rule = rule or RULE
    S = rule["seating"]
    refs_dir = Path(refs_dir)
    t0 = time.time()
    scope = reference_scope(refs_dir, reference_names, rule)
    man, refs = load_refs(refs_dir, rule, names=scope["names"] if scope else None, seat=False)
    reader = reader or ChunkReader(S["prediction"], cache_dir, opener)
    if cross_reader is None and S.get("cross_check"):
        try:
            cross_reader = ChunkReader(S["cross_check"], cache_dir, opener)
        except BenchError as exc:
            if require_cross_check:
                raise
            _say(log, f"surfbench: cross-check prediction not read ({exc})")
            cross_reader = None
    if require_cross_check and cross_reader is None:
        raise BenchError("required cross-check reader is unavailable")
    C = np.array(reader.chunks, dtype=np.int64)
    margin, thr = S["chunk_margin_vox"], S["threshold"]
    offs = list(range(-S["max_offset_vox"], S["max_offset_vox"] + 1))
    per = {}
    for r in refs:
        sel = r.labelled() & ~r.attrs["contact"]
        if not sel.any():
            continue
        p = r.xyz[sel][:, ::-1]
        n = r.normals[sel][:, ::-1] * r.attrs["orient"]
        key = np.floor(p / C).astype(np.int64)
        local = p - key * C
        inner = ((local >= margin) & (local < C - margin)).all(1)
        enc = (key[:, 0] << 20) | (key[:, 1] << 10) | key[:, 2]
        groups = collections.defaultdict(list)
        for i in np.flatnonzero(inner):
            groups[int(enc[i])].append(i)
        eligible = sorted(k for k, v in groups.items() if len(v) >= S["min_chunk_vertices"])
        per[r.name] = {"ref": r, "p": p, "n": n, "groups": groups, "eligible": eligible}
    rng = np.random.default_rng(S["seed"])
    chosen, order = [], {}
    chosen_set = set()
    for name in sorted(per):
        e = per[name]["eligible"]
        mine = [k for k in chosen if k in set(e)]
        for i in (rng.permutation(len(e)) if e else []):
            if len(mine) >= S["chunks_per_winding"]:
                break
            k = e[int(i)]
            if k in mine:
                continue
            mine.append(k)
            if k not in chosen_set:
                chosen.append(k)
                chosen_set.add(k)
        order[name] = mine
    _say(log, f"surfbench: audit reads {len(chosen)} prediction chunks for {len(per)} windings")

    def dec(k):
        return (k >> 20, (k >> 10) & 1023, k & 1023)

    def run(k):
        arr = reader.read(dec(k))
        rows = {}
        for name, d in per.items():
            idx = d["groups"].get(k)
            if not idx or len(idx) < S["min_chunk_vertices"]:
                continue
            idx = np.array(idx)
            local = d["p"][idx] - np.array(dec(k)) * C
            if arr is None:
                share = [0.0] * len(offs)
            else:
                share = _profile(arr, local, d["n"][idx], offs, thr)
            pk, ps = _peak(share, offs)
            rows[name] = {"n": int(len(idx)), "at0": _r(share[offs.index(0)], 3), "peak": pk,
                          "peak_share": _r(ps, 3), "status": _status(pk, ps, S),
                          "missing_chunk": arr is None}
        return k, rows

    regions = collections.defaultdict(dict)
    with concurrent.futures.ThreadPoolExecutor(max(1, workers)) as pool:
        for i, (k, rows) in enumerate(pool.map(run, chosen)):
            for name, row in rows.items():
                regions[name]["_".join(map(str, dec(k)))] = row
            if (i + 1) % 100 == 0:
                _say(log, f"surfbench:   {i + 1}/{len(chosen)} chunks ({time.time() - t0:.0f} s)")
    cross = {}
    if cross_reader is not None:
        C2 = np.array(cross_reader.chunks, dtype=np.int64)
        jobs = []
        for name in sorted(per):
            d = per[name]
            for k in order[name][:S["recto_per_winding"]]:
                idx = np.array(d["groups"][k])
                key2 = np.floor(d["p"][idx] / C2).astype(np.int64)
                enc2 = (key2[:, 0] << 20) | (key2[:, 1] << 10) | key2[:, 2]
                vals, cnt = np.unique(enc2, return_counts=True)
                k2 = int(vals[np.argmax(cnt)])
                local = d["p"][idx] - np.array(dec(k2)) * C2
                inner = ((local >= margin) & (local < C2 - margin)).all(1)
                if inner.sum() < S["min_chunk_vertices"] // 2:
                    continue
                jobs.append((name, k, k2, local[inner], d["n"][idx][inner]))

        def run2(job):
            name, k, k2, local, nrm = job
            arr = cross_reader.read(dec(k2))
            share = [0.0] * len(offs) if arr is None else _profile(arr, local, nrm, offs, thr)
            pk, ps = _peak(share, offs)
            return name, k, {"chunk": "_".join(map(str, dec(k2))), "n": int(len(local)), "peak": pk,
                             "peak_share": _r(ps, 3), "status": _status(pk, ps, S), "missing_chunk": arr is None}

        with concurrent.futures.ThreadPoolExecutor(max(1, workers)) as pool:
            for name, k, row in pool.map(run2, jobs):
                reg = regions[name].get("_".join(map(str, dec(k))))
                if reg is not None:
                    reg["cross"] = row
                    if reg["status"] != "weak" and row["status"] != "weak":
                        reg["cross_agrees"] = abs(reg["peak"] - row["peak"]) <= S["seated_vox"]
    windings = {}
    for name in sorted(per):
        regs = regions.get(name, {})
        st = collections.Counter(v["status"] for v in regs.values())
        cr = [v for v in regs.values() if "cross" in v]
        windings[name] = {
            "eligible_chunks": len(per[name]["eligible"]), "chosen": len(order.get(name, [])),
            "sampled": len(regs),
            "seated": st["seated"], "unseated": st["unseated"], "weak": st["weak"],
            "median_at0": _r(float(np.median([v["at0"] for v in regs.values()])), 3) if regs else None,
            "median_abs_peak": _r(float(np.median([abs(v["peak"]) for v in regs.values()])), 1) if regs else None,
            "cross_sampled": len(cr), "cross_agrees": sum(1 for v in cr if v.get("cross_agrees")),
            "cross_compared": sum(1 for v in cr if "cross_agrees" in v),
            "regions": dict(sorted(regs.items())),
        }
    tot = collections.Counter()
    for w in windings.values():
        tot.update({k: w[k] for k in ("sampled", "seated", "unseated", "weak", "cross_compared", "cross_agrees")})
    au = {
        "kind": "kit-surfbench-audit", "seat_rule_digest": part_digest(rule, SEAT_PARTS),
        "manifest_digest": man["digest"],
        "prediction": S["prediction"], "cross_check": S.get("cross_check") if cross_reader is not None else None,
        "chunk": [int(c) for c in C],
        "chunks_sampled": len(chosen),
        "chunks_read": {"fetched": reader.fetched if hasattr(reader, "fetched") else None,
                        "cached": reader.cached if hasattr(reader, "cached") else None,
                        "missing": reader.missing if hasattr(reader, "missing") else None},
        "cross_chunks_read": ({"fetched": cross_reader.fetched, "cached": cross_reader.cached,
                               "missing": cross_reader.missing}
                              if cross_reader is not None and hasattr(cross_reader, "fetched") else None),
        "summary": dict(tot),
        "windings": windings,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seconds": round(time.time() - t0, 1),
    }
    if scope is not None:
        au["reference_scope"] = scope
    if require_cross_check:
        au["cross_check_required"] = True
        if not any(v.get("cross_sampled", 0) for v in windings.values()):
            raise BenchError("required cross-check has no measured regions")
        if not any(not r["cross"].get("missing_chunk", True)
                   for v in windings.values() for r in v["regions"].values() if "cross" in r):
            raise BenchError("required cross-check read no available prediction chunks")
    au["digest"] = digest({k: au[k] for k in au if k not in ("created", "seconds", "digest", "chunks_read",
                                                              "cross_chunks_read")})
    (refs_dir / "audit.json").write_text(json.dumps(au, indent=1))
    _say(log, f"surfbench: audit written ({au['seconds']} s): {dict(tot)}")
    return au


# ---------------------------------------------------------------- labelling a surface

def _matches(P, refs, workers, dist=False):
    """(S, IN, J) of match for every reference, as (references, points) arrays; with dist also D, the distance
    from each point to the dense vertex it was matched to."""
    np = _np()
    R, N = len(refs), len(P)
    S = np.full((R, N), np.nan)
    IN = np.zeros((R, N), bool)
    J = np.zeros((R, N), np.int64)
    D = np.full((R, N), np.nan) if dist else None
    for i, r in enumerate(refs):
        m = match(P, r, workers, dist=True) if dist else match(P, r, workers)
        S[i], IN[i], J[i] = m[0], m[1], m[2]
        if dist:
            D[i] = m[4]
    return (S, IN, J, D) if dist else (S, IN, J)


def _classify(S, IN, J, refs, rule, d, seat_mode=None, masks=True):
    """Per vertex: class (ON, OFF or an unscored reason), the winding id it lies on (ON) or -1, the row of its
    nearest reference and the distance to it."""
    np = _np()
    R, N = S.shape
    ar = np.arange(N)
    if R == 0:
        return np.full(N, OUTSIDE, np.int8), np.full(N, -1, np.int64), np.full(N, -1), np.full(N, np.inf)
    absd = np.where(IN, np.abs(S), np.inf)
    best = np.argmin(absd, axis=0)
    bestd = absd[best, ar]
    has = np.isfinite(bestd)
    jb = J[best, ar]
    lab = np.full(N, -1, np.int64)
    seat = np.zeros(N, np.int8)
    for i, r in enumerate(refs):
        sel = has & (best == i)
        lab[sel] = r.label.ravel()[jb[sel]]
        seat[sel] = r.seat.ravel()[jb[sel]]
    cls = np.full(N, OUTSIDE, np.int8)
    on = has & (bestd <= d)
    cls[has] = OFF
    if not masks:
        cls[on] = ON
        return cls, np.where(on, lab, -1), np.where(has, best, -1), bestd
    gap = np.zeros(N, bool)
    for i, r in enumerate(refs):
        if "gap_pos" not in r.attrs:
            continue
        sel = IN[i] & ~on
        if not sel.any():
            continue
        j, s = J[i, sel], S[i, sel]
        gp, gn = r.attrs["gap_pos"].ravel()[j], r.attrs["gap_neg"].ravel()[j]
        vp, vn = r.attrs["g_pos"].ravel()[j], r.attrs["g_neg"].ravel()[j]
        gap[sel] |= (gp & (s > d) & (s < vp - d)) | (gn & (-s > d) & (-s < vn - d))
    cls[has & ~on & gap] = GAP
    cls[on] = ON
    cls[has & (lab == NOREF) & (bestd <= rule["scoring"]["noref_near_vox"])] = NOREFC
    scored = (cls == ON) | (cls == OFF)
    if seat_mode:
        cls[scored & (seat == SEAT_OFF)] = UNSEATED
        if seat_mode == "d2":
            cls[((cls == ON) | (cls == OFF)) & (seat != SEATED)] = UNAUDITED
    return cls, np.where(cls == ON, lab, -1), np.where(has, best, -1), bestd


def _crossings(grid_idx, cls, lab, S, IN, row_of, apart, contact, bridge, J=None, refs=None, sites=None):
    """Label changes along grid rows and columns between ON vertices, directly (an edge) or across at most
    `bridge` vertices that are off every winding or unscored near one (a hole or a vertex outside every
    footprint ends a bridge). A change is a switch when, at either end, the other end's winding is present (inside
    its footprint) and more than `apart` voxels away, so the two references are distinct sheets there, and
    nowhere along the crossing do the two references themselves meet (from the manifest: one has the other within
    `apart` at the vertex the surface lies over); otherwise it is a boundary crossing (a spiral seam, a
    reference's edge, or two references within `apart` of each other, which cannot be told from a seam). A switch is in a contact zone when that other winding is within
    `contact`. When `sites` is a list, each switch crossing's two end vertices (indices into the surface's valid
    vertices) are appended to it as an (n, 2) array."""
    np = _np()
    out = collections.Counter()
    rows_hit = 0
    code_of = np.zeros(len(cls), np.int8)
    code_of[cls == OUTSIDE] = 2
    code_of[cls == ON] = 1
    for axis in (1, 0):
        G = grid_idx if axis == 1 else grid_idx.T
        for line in G:
            code = np.full(len(line), 2, np.int8)
            v = line >= 0
            code[v] = code_of[line[v]]
            pos = np.flatnonzero(code == 1)
            if len(pos) < 2:
                continue
            blk = np.cumsum(code == 2)
            p1, p2 = pos[:-1], pos[1:]
            gapn = p2 - p1 - 1
            ok = (blk[p2] - blk[p1] == 0) & (gapn <= bridge)
            q1, q2, g = line[p1[ok]], line[p2[ok]], gapn[ok]
            a1, a2 = p1[ok], p2[ok]
            out["labelled_edges"] += int((g == 0).sum())
            l1, l2 = lab[q1], lab[q2]
            diff = l1 != l2
            if not diff.any():
                continue
            q1, q2, g, l1, l2, a1, a2 = q1[diff], q2[diff], g[diff], l1[diff], l2[diff], a1[diff], a2[diff]
            r1 = np.array([row_of.get(int(x), -1) for x in l1])
            r2 = np.array([row_of.get(int(x), -1) for x in l2])
            s12 = np.where(r1 >= 0, np.abs(S[np.maximum(r1, 0), q2]), np.inf)
            i12 = (r1 >= 0) & IN[np.maximum(r1, 0), q2]
            s21 = np.where(r2 >= 0, np.abs(S[np.maximum(r2, 0), q1]), np.inf)
            i21 = (r2 >= 0) & IN[np.maximum(r2, 0), q1]
            sw = (i12 & (s12 > apart)) | (i21 & (s21 > apart))
            # the two references meet somewhere along the crossing (ends and bridged vertices): a seam
            for t in (np.flatnonzero(sw) if J is not None and refs is not None else []):
                if r1[t] < 0 or r2[t] < 0:
                    continue
                path = line[a1[t]:a2[t] + 1]
                path = path[path >= 0]
                for ra, gb in ((r1[t], l2[t]), (r2[t], l1[t])):
                    at = refs[ra].attrs
                    if "g_pos" not in at:
                        continue
                    jv = J[ra, path][IN[ra, path]]
                    met = (((at["lab_pos"].ravel()[jv] == gb) & (at["g_pos"].ravel()[jv] <= apart)) |
                           ((at["lab_neg"].ravel()[jv] == gb) & (at["g_neg"].ravel()[jv] <= apart)))
                    if met.any():
                        sw[t] = False
                        break
            ct = sw & ((i12 & (s12 <= contact)) | (i21 & (s21 <= contact)))
            if sites is not None and sw.any():
                sites.append(np.stack([q1[sw], q2[sw]], 1))
            direct = g == 0
            out["switch_edges"] += int((sw & direct).sum())
            out["switch_edges_contact"] += int((ct & direct).sum())
            out["boundary_edges"] += int((~sw & direct).sum())
            out["bridged_switches"] += int((sw & ~direct).sum())
            out["bridged_switches_contact"] += int((ct & ~direct).sum())
            out["bridged_boundaries"] += int((~sw & ~direct).sum())
            if axis == 1 and sw.any():
                rows_hit += 1
    res = {k: int(out[k]) for k in ("labelled_edges", "switch_edges", "switch_edges_contact", "boundary_edges",
                                     "bridged_switches", "bridged_switches_contact", "bridged_boundaries")}
    res["switch_crossings"] = res["switch_edges"] + res["bridged_switches"]
    res["rows_with_switch"] = rows_hit
    return res


def _evaluate(xyz, valid, refs, rule, mode="full", workers=2):
    """Label a grid surface against references and measure it. mode: full (masks and seating), control (masks,
    no seating) or raw (no masks: the share within d of the given references). Returns (summary, internals)."""
    np = _np()
    D, A = rule["distance"], rule["accept"]
    d4, d2 = D["primary_vox"], D["secondary_vox"]
    P = xyz[valid]
    N = len(P)
    idx = np.full(valid.shape, -1, np.int64)
    idx[valid] = np.arange(N)
    S, IN, J = _matches(P, refs, workers)
    _, area, _, step = grid_geometry(xyz, valid)
    cm2 = (VOXEL_UM * 1e-4) ** 2
    varea = area[valid] * cm2
    by_gid = {r.gid: r for r in refs}
    row_of = {r.gid: i for i, r in enumerate(refs)}
    out = {"vertices": N, "area_cm2": _r(varea.sum(), 3), "grid_step_vox": _r(step, 2)}
    raw = mode == "raw"
    internal = {"S": S, "IN": IN, "J": J, "idx": idx}
    for key, d, seat in (("d4", d4, "d4"), ("d2", d2, "d2")):
        cls, lab, best, bestd = _classify(S, IN, J, refs, rule, d, seat if mode == "full" else None, masks=not raw)
        internal[key] = (cls, lab, best)
        scored = (cls == ON) | (cls == OFF)
        ns = int(scored.sum())
        rec = {"d_vox": d, "scored": ns, "scored_share": _r(ns / N if N else 0.0),
               "on_any": _r((cls == ON).sum() / ns) if ns else None,
               "unscored": {CLASS_NAMES[c]: _r((cls == c).sum() / N) for c in CLASS_NAMES if N and (cls == c).any()}}
        counts = collections.Counter(int(x) for x in lab[lab >= 0])
        rec["label_shares"] = {by_gid[g].name if g in by_gid else str(g): _r(c / ns)
                               for g, c in counts.most_common(5)} if ns else {}
        rec["_counts"] = counts
        out[key] = rec
    c4 = out["d4"].pop("_counts")
    c2 = out["d2"].pop("_counts")
    dom = c4.most_common(1)[0][0] if c4 else None
    out["dominant"] = by_gid[dom].name if dom is not None else None
    out["dominant_id"] = dom
    for key, c in (("d4", c4), ("d2", c2)):
        ns = out[key]["scored"]
        out[key]["dominant_precision"] = _r(c.get(dom, 0) / ns) if ns and dom is not None else None
    if dom is not None:
        cls4, lab4, _ = internal["d4"]
        out["correct_area_cm2"] = _r(varea[lab4 == dom].sum(), 3)
    if not raw:
        cls4, lab4, _ = internal["d4"]
        pairs = []
        sw = _crossings(idx, cls4, lab4, S, IN, row_of, rule["references"]["coincide_vox"],
                        rule["references"]["contact_vox"], rule["scoring"]["bridge_vertices"], J, refs, sites=pairs)
        internal["switch_pairs"] = np.concatenate(pairs) if pairs else np.zeros((0, 2), np.int64)
        step_cm = (step if math.isfinite(step) else 0.0) * VOXEL_UM * 1e-4
        scored_cm2 = float(varea[(cls4 == ON) | (cls4 == OFF)].sum())
        sw["switch_line_cm"] = _r(sw["switch_crossings"] * step_cm, 3)
        sw["switch_line_cm_per_cm2"] = _r(sw["switch_line_cm"] / scored_cm2) if scored_cm2 else None
        out["switches"] = sw
    out["accepted"] = bool(out["d4"]["scored_share"] >= A["min_scored_share"]
                           and (out["d4"]["dominant_precision"] or 0.0) >= A["bar"])
    return out, internal


def evaluate(xyz, valid, refs, rule=None, mode="full", workers=2):
    return _evaluate(xyz, valid, refs, rule or RULE, mode, workers)[0]


def near_refs(points, refs):
    np = _np()
    if len(points) == 0:
        return []
    keys = np.unique(block_keys(points))
    return [r for r in refs if np.isin(keys, r.keys()).any()]


# ---------------------------------------------------------------- controls

def _window(ref, box):
    r0, r1, c0, c1 = box
    lab = ref.labelled()[r0:r1, c0:c1]
    return ref.xyz[r0:r1, c0:c1].copy(), lab.copy(), ref.normals[r0:r1, c0:c1].copy()


def _box_around(ref, rc, size):
    H, W = ref.valid.shape
    r, c = rc
    h = min(size, H)
    w = min(size, W)
    r0 = int(min(max(0, r - h // 2), H - h))
    c0 = int(min(max(0, c - w // 2), W - w))
    return (r0, r0 + h, c0, c0 + w)


def _project(xyz, valid, B, workers):
    """Each valid vertex moved onto B along B's normal (point to plane), where it projects inside B's footprint
    and B's vertex there is labelled B. Returns (positions (H, W, 3), ok, offsets)."""
    np = _np()
    out = np.full(xyz.shape, np.nan)
    ok = np.zeros(valid.shape, bool)
    off = np.full(valid.shape, np.nan)
    if not valid.any():
        return out, ok, off
    s, ins, src, nb = match(xyz[valid], B, workers)
    good = ins & (B.label.ravel()[src] == B.gid)
    p = xyz[valid] - s[:, None] * nb
    tmp = np.full((int(valid.sum()), 3), np.nan)
    tmp[good] = p[good]
    out[valid] = tmp
    o = np.full(int(valid.sum()), np.nan)
    o[good] = s[good]
    off[valid] = o
    ok[valid] = good
    return out, ok, off


def _quarter_cells(xyz, valid, normals):
    """Points at (r + 0.25, c + 0.25) of every cell whose corners are valid, with interpolated unit normals: off
    every dense reference vertex, so a nearest-vertex distance would not pass for a point-to-plane one."""
    np = _np()
    ok = valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:]
    w = [(0.5625, xyz[:-1, :-1], normals[:-1, :-1]), (0.1875, xyz[1:, :-1], normals[1:, :-1]),
         (0.1875, xyz[:-1, 1:], normals[:-1, 1:]), (0.0625, xyz[1:, 1:], normals[1:, 1:])]
    p = sum(a * x for a, x, _ in w)
    n = sum(a * nn for a, _, nn in w)
    n = n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-9)
    return p[ok], n[ok]


def _local_contact(B, Bmask, A, d):
    """Share of B's vertices (mask) whose nearest sheet on either side is A within d (from the manifest)."""
    np = _np()
    a = B.attrs
    if "lab_pos" not in a or not Bmask.any():
        return 0.0
    hit = ((a["lab_pos"] == A.gid) & (a["g_pos"] <= d)) | ((a["lab_neg"] == A.gid) & (a["g_neg"] <= d))
    return float(hit[Bmask].mean())


def _neighbours_of(A, refs, man, key="chain_neighbours"):
    """A's neighbours in the chain (key chain_neighbours), or only those across a step that is not a gap
    (key chain_adjacent)."""
    rec = next((x for x in man["references"] if x["name"] == A.name), None)
    names = rec.get(key, []) if rec else []
    return [r for r in refs if r.name in names]


def site_controls(refs, man, A, box, rule=None, workers=2):
    """Every control at one site: a window of reference A's grid. Each control can fail; the site is valid only
    when all pass."""
    np = _np()
    rule = rule or RULE
    C, Acc = rule["controls"], rule["accept"]
    d4, d2 = rule["distance"]["primary_vox"], rule["distance"]["secondary_vox"]
    bar = Acc["bar"]
    xyz, valid, nrm = _window(A, box)
    res = {"site": {"reference": A.name, "box": [int(b) for b in box], "vertices": int(valid.sum())}}
    if valid.sum() < 50:
        res["valid"] = False
        res["failed"] = ["site has too few labelled vertices"]
        return res
    near = near_refs(xyz[valid], refs)
    if A not in near:
        near.append(A)

    def ev(x, v, mode="control", only=None):
        return evaluate(x, v, only if only is not None else near, rule, mode, workers)

    def summ(e):
        return {"dominant": e["dominant"], "dominant_precision_d4": e["d4"]["dominant_precision"],
                "on_any_d4": e["d4"]["on_any"], "scored_share_d4": e["d4"]["scored_share"],
                "switch_crossings": e.get("switches", {}).get("switch_crossings"),
                "rows_with_switch": e.get("switches", {}).get("rows_with_switch"), "accepted": e["accepted"]}

    # (e) positive control
    e = ev(xyz, valid)
    sw = e["switches"]["switch_crossings"]
    res["positive"] = {**summ(e), "pass": e["dominant"] == A.name and (e["d4"]["dominant_precision"] or 0)
                       >= C["positive_min"] and sw == 0,
                       "criterion": f"dominant {A.name}, precision@4 >= {C['positive_min']}, 0 switch crossings"}
    # (d) offset sweep: quarter-cell points moved along their normals by offset + U(-j, j), raw share within d2
    rng = np.random.default_rng(C["seed"])
    # cells where another part of A lies within contact_vox are left out: there the offset to A is not the
    # offset from this part, so the sweep's expected shares do not hold (a property of the reference)
    clean = valid.copy()
    if "self_s" in A.attrs:
        r0, r1, c0, c1 = box
        clean &= A.attrs["self_s"][r0:r1, c0:c1] > rule["references"]["contact_vox"]
    q, qn = _quarter_cells(xyz, clean, nrm)
    sweep = []
    ok = len(q) >= 20
    for off, (lo, hi) in zip(C["offsets_vox"], C["offset_bands"]):
        if not ok:
            break
        t = off + rng.uniform(-C["offset_jitter_vox"], C["offset_jitter_vox"], len(q))
        pts = q + t[:, None] * qn
        s, ins, _, _ = match(pts, A, workers)
        p = float((ins & (np.abs(s) <= d2)).mean())
        sweep.append({"offset_vox": off, "precision_d2": _r(p), "band": [lo, hi], "pass": lo <= p <= hi})
    res["offset_sweep"] = {"steps": sweep, "pass": ok and all(x["pass"] for x in sweep), "points": int(len(q)),
                           "self_overlap_left_out": _r(1 - clean.sum() / max(int(valid.sum()), 1)),
                           "criterion": "precision@2 against the site winding alone in each band"}
    # tolerance: the window moved 2 voxels along its normals, both ways, must still be accepted on A
    tol = []
    for sgn in (1, -1):
        e = ev(xyz + sgn * C["tolerance_vox"] * np.nan_to_num(nrm), valid)
        tol.append({"shift_vox": sgn * C["tolerance_vox"], **summ(e)})
    res["tolerance"] = {"shifts": tol, "accepted": all(t["dominant"] == A.name and t["accepted"] for t in tol),
                        "note": f"measured, not a gate: the site moved +-{C['tolerance_vox']} voxels along its "
                                "normals; where it is not accepted, a trace that far off its reference would fail "
                                "here (a contact zone), which is a property of the references, not of the code"}
    # (c) displaced patch: moved in z, must not be accepted; scored against the references near where it lands
    # (those near the site can miss windings there)
    zs = A.xyz[A.labelled()][:, 2]
    disp = []
    for dz in C["displace_z_vox"]:
        top = xyz[valid][:, 2].max() + dz
        sgn = 1 if top <= zs.max() else -1
        moved = xyz + np.array([0.0, 0.0, sgn * dz])
        e = ev(moved, valid, only=near_refs(moved[valid], refs))
        disp.append({"dz_vox": sgn * dz, **summ(e)})
    res["displaced"] = {"moves": disp, "pass": all(not x["accepted"] for x in disp),
                        "chance_on_any_d4": _r(max((x["on_any_d4"] or 0.0) for x in disp)),
                        "criterion": "not accepted after every move"}
    # neighbour for the planted switches and substitution
    cands = []
    for B in _neighbours_of(A, refs, man):
        pos, okB, off = _project(xyz, valid, B, workers)
        cands.append((float(okB.sum()) / max(int(valid.sum()), 1), B, pos, okB, off))
    cands.sort(key=lambda x: -x[0])
    # (f) off-sheet drift, toward the adjacent winding (across a step that is not a gap) that covers most
    adj = [c for c in cands if c[1].name in {r.name for r in _neighbours_of(A, refs, man, "chain_adjacent")}]
    if not adj or adj[0][0] < C["min_neighbour_cover"]:
        res["planted_drift"] = {"pass": False, "reason": "no adjacent winding covers enough of the site"}
    else:
        res["planted_drift"] = _drift_control(A, adj[0][1], xyz, valid, adj[0][2], adj[0][3], adj[0][4], near,
                                              rule, workers, summ)
    if not cands or cands[0][0] < C["min_neighbour_cover"]:
        for k in ("planted_hard", "planted_ramp", "neighbour"):
            res[k] = {"pass": False, "reason": "no adjacent winding covers enough of the site"}
    else:
        cover, B, posB, okB, offB = cands[0]
        res["site"]["neighbour"] = B.name
        res["site"]["neighbour_cover"] = _r(cover)
        H, W = valid.shape
        # (b) hard stitch: from the column that halves the vertices B covers, at least coincide_vox away (where
        # the two coincide a move onto B is no move), everything on B
        cols = np.arange(W)[None, :].repeat(H, 0)
        apart = rule["references"]["coincide_vox"]
        plantable = valid & okB & (np.abs(np.nan_to_num(offB, nan=0.0)) > apart)
        pc = cols[plantable]
        mid = int(np.median(pc)) if pc.size else W // 2
        moved = plantable & (cols >= mid)
        x2 = np.where(moved[..., None], posB, xyz)
        share = float(moved.sum() / valid.sum())
        rows = int(((moved.any(1)) & ((valid & (cols < mid)).any(1))).sum())
        e = ev(x2, valid)
        lab_b = e["d4"]["label_shares"].get(B.name, 0.0) or 0.0
        res["planted_hard"] = {**summ(e), "planted_share": _r(share), "share_on_neighbour": lab_b,
                               "planted_rows": rows}
        lo, hi = C["planted_share"]
        res["planted_hard"]["pass"] = bool(
            lo <= share <= hi and not e["accepted"] and abs(lab_b - share) <= C["planted_label_tolerance"]
            and e["switches"]["rows_with_switch"] >= C["planted_row_share"] * rows)
        res["planted_hard"]["criterion"] = ("planted share in range, not accepted, share on the neighbour within "
                                            f"{C['planted_label_tolerance']} of planted, switch in at least "
                                            f"{C['planted_row_share']} of planted rows")
        # (b') smooth ramp inside a contact zone
        res["planted_ramp"] = _ramp_control(refs, near, A, B, box, rule, workers, ev, summ)
        # (a) neighbour substitution
        res["neighbour"] = _neighbour_control(A, B, xyz, valid, near, rule, workers, ev)
    res["failed"] = [k for k in CONTROL_KEYS if not res.get(k, {}).get("pass")]
    res["valid"] = not res["failed"]
    return res


def _ramp_control(refs, near, A, B, box, rule, workers, ev, summ):
    """A smooth switch: over ramp_cols columns the window slides from A onto B. It goes through a contact vertex
    of A with B (2 to 8 voxels apart) whose row has A to its left and B to its right, in the column where most of
    the window's rows have A and a distinct B along the ramp, nearest the site among those; with no such vertex,
    through the site's middle column (recorded: in_contact_zone false), where only a bridged crossing can find
    it."""
    np = _np()
    C = rule["controls"]
    a = A.attrs
    contact_d = rule["references"]["contact_vox"]
    lab = A.labelled()
    apart = rule["references"]["coincide_vox"]
    hit = lab & (((a["lab_pos"] == B.gid) & (a["g_pos"] > apart) & (a["g_pos"] <= contact_d)) |
                 ((a["lab_neg"] == B.gid) & (a["g_neg"] > apart) & (a["g_neg"] <= contact_d)))
    r0, r1, c0, c1 = box
    centre = np.array([(r0 + r1) / 2, (c0 + c1) / 2])
    size = max(r1 - r0, c1 - c0)
    best, in_contact = None, False
    if hit.any():
        _, okA, _ = _project(A.xyz, lab, B, workers)
        reach = C["ramp_cols"] + 2
        right = np.ones_like(okA)
        left = np.ones_like(okA)
        for k in range(1, reach + 1):
            sh = np.zeros_like(okA)
            sh[:, :-k] = okA[:, k:]
            right &= sh
            sh = np.zeros_like(lab)
            sh[:, k:] = lab[:, :-k]
            left &= sh
        good = hit & okA & right & left
        # rows where the band around the ramp is clean: A labelled and B more than coincide_vox away all along
        # it (where the references touch, a switch cannot be told from a seam, so the ramp is not put there)
        sep = np.where(a["lab_pos"] == B.gid, a["g_pos"], np.inf)
        sep = np.minimum(sep, np.where(a["lab_neg"] == B.gid, a["g_neg"], np.inf))
        clean = lab & (sep > apart)
        band = clean.copy()
        for k in range(1, reach + 1):
            sh = np.zeros_like(clean)
            sh[:, :-k] = clean[:, k:]
            band &= sh
            sh = np.zeros_like(clean)
            sh[:, k:] = clean[:, :-k]
            band &= sh
        good &= band
        if good.any():
            rc = np.argwhere(good)
            # the share of the window's rows whose band is clean in that column, then nearness to the site
            cs = np.vstack([np.zeros((1, band.shape[1])), np.cumsum(band, axis=0)])
            half = size // 2
            lo_r = np.clip(rc[:, 0] - half, 0, band.shape[0])
            hi_r = np.clip(rc[:, 0] + half, 0, band.shape[0])
            frac = (cs[hi_r, rc[:, 1]] - cs[lo_r, rc[:, 1]]) / np.maximum(hi_r - lo_r, 1)
            near = ((rc - centre) ** 2).sum(1)
            best = rc[np.lexsort((near, -np.round(frac, 2)))[0]]
            in_contact = True
    if best is None:
        best = np.array([int(centre[0]), int(centre[1])])
    rbox = _box_around(A, best, size)
    xyz, valid, _ = _window(A, rbox)
    posB, okB, offB = _project(xyz, valid, B, workers)
    okB = okB & (np.abs(np.nan_to_num(offB, nan=0.0)) > apart)
    H, W = valid.shape
    cc = int(best[1] - rbox[2])
    half = C["ramp_cols"] / 2.0
    cols = np.arange(W)[None, :].repeat(H, 0).astype(float)
    w = np.clip((cols - (cc - half)) / max(C["ramp_cols"], 1), 0.0, 1.0)
    w = np.where(valid & okB, w, 0.0)
    x2 = xyz + w[..., None] * (np.nan_to_num(posB) - xyz) * (valid & okB)[..., None]
    full = valid & okB & (w >= 1.0)
    share = float(full.sum() / max(valid.sum(), 1))
    rows = int((full.any(1) & (valid & (w <= 0)).any(1)).sum())
    e = ev(x2, valid)
    lo, hi = C["planted_share"]
    out = {**summ(e), "box": [int(b) for b in rbox], "ramp_column": int(best[1]), "in_contact_zone": in_contact,
           "planted_share": _r(share), "planted_rows": rows,
           "contact_vertices_in_box": int(hit[rbox[0]:rbox[1], rbox[2]:rbox[3]].sum())}
    out["share_in_range"] = bool(lo <= share <= hi)
    out["pass"] = bool(share > 0.05 and rows > 0 and not (out["share_in_range"] and e["accepted"])
                       and e["switches"]["rows_with_switch"] >= C["planted_row_share"] * rows)
    out["criterion"] = ("a ramp over ramp_cols columns, through a contact vertex when there is one: switch found in "
                        f"at least {C['planted_row_share']} of planted rows, and not accepted when the planted share "
                        "is in the planted range")
    return out


def _drift_control(A, B, xyz, valid, posB, okB, offB, near, rule, workers, summ):
    """Off-sheet drift: from the median column of the vertices where B, a winding adjacent to A across a step that
    is not a gap, lies more than 2 (d4 + drift_clear_vox) voxels away, the window moved to the midpoint between A
    and B, so more than d4 + drift_clear_vox from both. Those vertices lie on no winding and the next sheet is
    present, so at least drift_off_min of them must be scored off (not hidden by the gap mask or another mask),
    and the window must not be accepted when the moved share is in the planted range. This guards the masks:
    no other control checks that a vertex off every winding counts against a trace."""
    np = _np()
    C = rule["controls"]
    d4 = rule["distance"]["primary_vox"]
    H, W = valid.shape
    cols = np.arange(W)[None, :].repeat(H, 0)
    sep = np.abs(np.nan_to_num(offB, nan=0.0))
    plantable = valid & okB & (sep > 2 * (d4 + C["drift_clear_vox"]))
    pc = cols[plantable]
    if pc.size == 0:
        return {"neighbour": B.name, "pass": False, "reason": f"{B.name} is nowhere far enough from the site"}
    moved = plantable & (cols >= int(np.median(pc)))
    x2 = np.where(moved[..., None], 0.5 * (xyz + np.nan_to_num(posB)), xyz)
    e, internal = _evaluate(x2, valid, near, rule, "control", workers)
    cls = internal["d4"][0][internal["idx"][moved]]
    share = float(moved.sum() / max(valid.sum(), 1))
    off = float((cls == OFF).mean()) if cls.size else 0.0
    names = {ON: "on", OFF: "off", **CLASS_NAMES}
    lo, hi = C["planted_share"]
    out = {**summ(e), "neighbour": B.name, "planted_share": _r(share), "moved_off_share": _r(off),
           "moved_classes": {names[int(c)]: _r((cls == c).mean()) for c in np.unique(cls)},
           "share_in_range": bool(lo <= share <= hi)}
    out["pass"] = bool(share > 0.05 and off >= C["drift_off_min"] and not (out["share_in_range"] and e["accepted"]))
    out["criterion"] = (f"at least {C['drift_off_min']} of the moved vertices scored off, and not accepted when the "
                        "planted share is in the planted range")
    return out


def _neighbour_control(A, B, xyz, valid, near, rule, workers, ev):
    """B's own vertices under the site: scored against A alone they must lie within d of A no more than the
    pair's measured local contact share plus a margin, and against all references they must be labelled B."""
    np = _np()
    C = rule["controls"]
    d4 = rule["distance"]["primary_vox"]
    tmp = Ref(A.name, A.gid, xyz, valid, rule)
    sel = B.labelled()
    s, ins, _, _ = match(B.xyz[sel], tmp, workers)
    under = np.zeros(B.valid.shape, bool)
    under[sel] = ins
    if under.sum() < 50:
        return {"pass": False, "reason": f"too few vertices of {B.name} under the site"}
    rc = np.argwhere(under)
    r0, c0 = rc.min(0)
    r1, c1 = rc.max(0) + 1
    bx = B.xyz[r0:r1, c0:c1]
    bv = under[r0:r1, c0:c1]
    s, ins, _, _ = match(bx[bv], A, workers)
    share = float((ins & (np.abs(s) <= d4)).mean())
    contact = _local_contact(B, under, A, d4)
    bar = contact + C["neighbour_margin"]
    e = ev(bx, bv)
    return {"neighbour": B.name, "vertices": int(bv.sum()), "share_within_d4_of_site": _r(share),
            "local_contact_share": _r(contact), "bar": _r(bar), "dominant": e["dominant"],
            "pass": share <= bar and e["dominant"] == B.name,
            "criterion": "share within 4 of the site winding <= local contact share + margin, and labelled as "
                         "the neighbour"}


def pair_controls(refs, man, rule=None, workers=2):
    """For every adjacent pair of the chain, both ways, on the whole overlap: the share of one winding within d4 of
    the other must not exceed the pair's contact share in the manifest plus a margin. The manifest measured that
    share with the same matching, so this is a regression check: it fails when the matching, the labels or the
    references differ from those the manifest was built with, not when the labeller is wrong in a way the
    manifest shares (the offset sweep and the site controls test that)."""
    np = _np()
    rule = rule or RULE
    d4, margin = rule["distance"]["primary_vox"], rule["controls"]["neighbour_margin"]
    by = {r.name: r for r in refs}
    out = []
    for c in man["chain"]:
        a, b = by.get(c["inner"]), by.get(c["outer"])
        if a is None or b is None:
            continue
        for X, Y, key in ((b, a, "cov4"), (a, b, "cov4_inner_to_outer")):
            sel = X.labelled()
            s, ins, src, _ = match(X.xyz[sel], Y, workers)
            share = float((ins & (np.abs(s) <= d4) & (Y.label.ravel()[src] == Y.gid)).sum() / max(sel.sum(), 1))
            bar = (c.get(key) or 0.0) + margin
            out.append({"winding": X.name, "against": Y.name, "share_within_d4": _r(share),
                        "contact_share": _r(c.get(key)), "bar": _r(bar), "pass": share <= bar})
    return out


def run_controls(refs_dir=DEFAULT_REFS, rule=None, workers=2, log=None, names=None):
    """The controls at one seeded site per labelled reference, plus the pair check for every adjacent pair. Valid
    only when every one passes. Sites are drawn from one seeded sequence in rank order, so a run limited to some
    references (names) draws other sites than the full run, and runs no pair checks."""
    np = _np()
    rule = rule or RULE
    C = rule["controls"]
    t0 = time.time()
    man, refs = load_refs(refs_dir, rule)
    rng = np.random.default_rng(C["seed"])
    size = C["global_window"]
    sites = []
    for A in sorted(refs, key=lambda r: (r.attrs.get("rank") is None, r.attrs.get("rank") or 0)):
        if names and A.name not in names:
            continue
        lab = A.labelled()
        if lab.sum() < size * size // 4:
            sites.append({"site": {"reference": A.name}, "valid": None, "skipped": "too few labelled vertices"})
            continue
        rc = np.argwhere(lab)
        box = None
        for _ in range(50):
            cand = rc[int(rng.integers(len(rc)))]
            b = _box_around(A, cand, size)
            if lab[b[0]:b[1], b[2]:b[3]].mean() >= 0.6:
                box = b
                break
        if box is None:
            sites.append({"site": {"reference": A.name}, "valid": None, "skipped": "no window 60 % labelled"})
            continue
        res = site_controls(refs, man, A, box, rule, workers)
        sites.append(res)
        _say(log, f"surfbench: controls at {A.name}: {'valid' if res['valid'] else 'FAILED ' + str(res['failed'])} "
                  f"({time.time() - t0:.0f} s)")
    pairs = pair_controls(refs, man, rule, workers) if not names else []
    ran = [s for s in sites if s.get("valid") is not None]
    out = {"kind": "kit-surfbench-controls", "rule_digest": rule_digest(rule), "manifest_digest": man["digest"],
           "sites": sites, "pairs": pairs,
           "summary": _control_summary(ran, pairs, rule),
           "bar_from_controls": choose_bar(ran, rule),
           "valid": bool(ran) and all(s["valid"] for s in ran) and all(p["pass"] for p in pairs),
           "seconds": round(time.time() - t0, 1)}
    return out


def choose_bar(sites, rule=None):
    """The acceptance bar the controls allow, from their dominant precision@4 alone (which does not depend on the
    bar): lo is the highest any negative control reached (hard and ramp switches whose planted share is in the
    planted range, every displaced move), counting only those with at least min_scored_share of their vertices
    scored (others get "not scorable" whatever the bar), hi the lowest positive control. The bar is their midpoint
    floored to bar_step, and must clear both by bar_margin; otherwise there is no bar (None) and the reason says
    why. The drift control is a gate on the masks, not one of these negatives: the formula was fixed before it
    existed."""
    rule = rule or RULE
    A_ = rule["accept"]
    neg, pos = [], []
    for st in sites:
        if st.get("valid") is None:
            continue
        p = st.get("positive", {}).get("dominant_precision_d4")
        if p is not None:
            pos.append(p)
        lo_s, hi_s = rule["controls"]["planted_share"]
        def scorable(v):
            return (v.get("scored_share_d4") is None or v["scored_share_d4"] >= A_["min_scored_share"])

        for k in ("planted_hard", "planted_ramp"):
            v = st.get(k, {})
            # a planted switch counts when its share is in the planted range: a smaller one is a defect the bar
            # is not asked to reject (switch edges report it)
            if "dominant_precision_d4" in v and lo_s <= (v.get("planted_share") or 0.0) <= hi_s and scorable(v):
                neg.append(v["dominant_precision_d4"] or 0.0)
        for m in st.get("displaced", {}).get("moves", []):
            # a move that leaves the stack (under min_scored_share scored) is "not scorable", never accepted
            if scorable(m):
                neg.append(m.get("dominant_precision_d4") or 0.0)
    out = {"negatives": len(neg), "positives": len(pos), "lo": _r(max(neg)) if neg else None,
           "hi": _r(min(pos)) if pos else None, "bar": None}
    if not neg or not pos:
        out["reason"] = "no negative or no positive control measured"
        return out
    lo, hi = max(neg), min(pos)
    step = A_["bar_step"]
    bar = math.floor(round((lo + hi) / 2 / step, 9)) * step
    if bar < lo + A_["bar_margin"] - 1e-9 or bar > hi - A_["bar_margin"] + 1e-9:
        out["reason"] = (f"the negative controls reach {lo:.3f} and the positive control {hi:.3f}: no bar clears "
                         f"both by {A_['bar_margin']}")
        return out
    out["bar"] = _r(bar)
    out["rule_bar"] = A_["bar"]
    out["rule_bar_matches"] = abs(A_["bar"] - bar) < 1e-9
    return out


def _control_summary(sites, pairs, rule):
    out = {"sites": len(sites)}
    for k in CONTROL_KEYS:
        out[k] = {"pass": sum(1 for s in sites if s.get(k, {}).get("pass")), "of": len(sites)}
    out["tolerance"] = {"accepted": sum(1 for s in sites if s.get("tolerance", {}).get("accepted")),
                        "of": len(sites)}

    def vals(k, f):
        return [f(s[k]) for s in sites if k in s and f(s[k]) is not None]

    def rng(v):
        return [_r(min(v)), _r(max(v))] if v else None

    out["positive"]["precision_d4"] = rng(vals("positive", lambda x: x.get("dominant_precision_d4")))
    out["tolerance"]["precision_d4"] = rng(vals("tolerance", lambda x: min(
        (t["dominant_precision_d4"] or 0.0) for t in x["shifts"]) if "shifts" in x else None))
    out["displaced"]["precision_d4"] = rng(vals("displaced", lambda x: max(
        (t["dominant_precision_d4"] or 0.0) for t in x["moves"]) if "moves" in x else None))
    out["displaced"]["chance_on_any_d4"] = rng(vals("displaced", lambda x: x.get("chance_on_any_d4")))
    out["planted_hard"]["precision_d4"] = rng(vals("planted_hard", lambda x: x.get("dominant_precision_d4")))
    out["planted_ramp"]["precision_d4"] = rng(vals("planted_ramp", lambda x: x.get("dominant_precision_d4")))
    out["planted_drift"]["precision_d4"] = rng(vals("planted_drift", lambda x: x.get("dominant_precision_d4")))
    out["planted_drift"]["planted_share"] = rng(vals("planted_drift", lambda x: x.get("planted_share")))
    out["planted_drift"]["moved_off_share"] = rng(vals("planted_drift", lambda x: x.get("moved_off_share")))
    out["displaced"]["scorable_moves"] = sum(1 for s in sites for m in s.get("displaced", {}).get("moves", [])
                                             if (m.get("scored_share_d4") or 0) >= rule["accept"]["min_scored_share"])
    for i, off in enumerate(rule["controls"]["offsets_vox"]):
        out["offset_sweep"][f"precision_d2_at_{off:g}"] = rng(vals("offset_sweep", lambda x, i=i: (
            x["steps"][i]["precision_d2"] if len(x.get("steps", [])) > i else None)))
    out["pairs"] = {"pass": sum(1 for p in pairs if p["pass"]), "of": len(pairs)}
    return out


# ---------------------------------------------------------------- scoring a candidate

def _selfcross(surface, tools, threads=2, out_json=None):
    """Transverse self-contacts of a tifxyz (both quad diagonals summed, as kit's check_surface does), or None."""
    import subprocess
    import tempfile
    if tools is None or not tools.has("vc_tifxyz_selfcross"):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        rep = Path(out_json) if out_json else Path(tmp) / "selfcross.json"
        try:
            subprocess.run(tools.argv("vc_tifxyz_selfcross", "--surface", surface, "-o", rep, "--threads", threads),
                           capture_output=True, timeout=1800, check=False)
            sc = json.loads(rep.read_text())
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            return {"error": str(exc)}
    return {"transverse": sum(int(c.get("transverse", 0)) for c in sc.get("census", [])),
            "clean": sc.get("clean_of_transverse_self_intersection")}


def _find_tools(tools):
    if tools is not None:
        return tools
    try:
        from . import vc3d
        return vc3d.find_tools()
    except Exception:  # noqa: BLE001 - the tools are optional here
        return None


def score(surface_path, refs_dir=DEFAULT_REFS, controls=True, selfcross=True, tools=None, rule=None, workers=2,
          log=None, reference_names=None):
    """Score one candidate tifxyz (same frame as the references) under the frozen rule. Returns a dict with the
    metrics, the controls at the candidate's site, the verdict and the digests. A run whose controls fail, or
    whose references have no seating audit, is invalid and gets no verdict. An explicit reference_names scope
    restricts payload loading and every calculation, including controls, and is recorded with its own digest."""
    np = _np()
    rule = rule or RULE
    A_ = rule["accept"]
    t0 = time.time()
    refs_dir = Path(refs_dir)
    scope = None
    if reference_names is not None:
        # Validate from metadata before any mesh or attribute payload is opened.
        if (not isinstance(reference_names, (list, tuple)) or not reference_names
                or any(not isinstance(n, str) or not n for n in reference_names)):
            raise BenchError("reference_names must be a nonempty list or tuple of winding names")
        if len(set(reference_names)) != len(reference_names):
            raise BenchError("reference_names contains duplicate winding names")
        man = load_manifest(refs_dir, rule)
        available = [r["name"] for r in man["references"]]
        unknown = set(reference_names) - set(available)
        if unknown:
            raise BenchError("unknown reference names: " + ", ".join(sorted(unknown)))
        # Manifest order keeps matching and scope digests independent of CLI order.
        reference_names = [n for n in available if n in reference_names]
        scope = {"names": reference_names, "manifest_digest": man["digest"]}
        scope["digest"] = digest(scope)
    man, refs = load_refs(refs_dir, rule, names=reference_names)
    au = load_audit(refs_dir, man, rule)
    xyz, valid, _ = read_tifxyz(surface_path)
    out = {"kind": "kit-surfbench-score", "surface": str(surface_path), "refs": str(refs_dir),
           "rule_digest": rule_digest(rule), "manifest_digest": man["digest"],
           "audit_digest": au.get("digest") if au else None, "invalid_reasons": []}
    if scope is not None:
        out["reference_scope"] = scope
    if not au:
        out["invalid_reasons"].append("no seating audit (python -m kit surfbench audit)")
    if valid.sum() == 0:
        raise BenchError(f"{surface_path}: no valid vertices")
    near = near_refs(xyz[valid], refs)
    if not near:
        out.update({"valid": False, "verdict": "not scorable", "metrics": None,
                    "invalid_reasons": out["invalid_reasons"] + ["the surface lies outside every reference"]})
        return out
    summary, internal = _evaluate(xyz, valid, near, rule, "full", workers)
    by_gid = {r.gid: r for r in refs}
    dom = summary.get("dominant_id")
    if dom is not None:
        D = by_gid[dom]
        cand = Ref("candidate", -10, xyz, valid, rule)
        sel = D.labelled()
        s, ins, _, _ = match(D.xyz[sel], cand, workers)
        cm2 = (VOXEL_UM * 1e-4) ** 2
        for key, d in (("recall_d4", rule["distance"]["primary_vox"]), ("recall_d2", rule["distance"]["secondary_vox"])):
            cov = ins & (np.abs(s) <= d)
            summary[key] = _r(cov.mean()) if cov.size else None
        cov4 = ins & (np.abs(s) <= rule["distance"]["primary_vox"])
        summary["dominant_area_cm2"] = _r(float(D.area[sel].sum()) * cm2, 2)
        summary["dominant_covered_cm2"] = _r(float(D.area[sel][cov4].sum()) * cm2, 3)
        rec = next(x for x in man["references"] if x["name"] == D.name)
        summary["dominant_split"] = rec["split"]
        summary["dominant_rank"] = rec["rank"]
        summary["dominant_partial"] = rec["partial"]
    summary.pop("dominant_id", None)
    out["metrics"] = summary
    # selfcross relative to the reference's own rate on its grid
    if selfcross:
        tools = _find_tools(tools)
        sc = _selfcross(surface_path, tools, threads=workers)
        if sc is not None and "transverse" in sc and dom is not None:
            cache = refs_dir / "selfcross" / f"{by_gid[dom].name}.json"
            if cache.is_file():
                ref_sc = json.loads(cache.read_text())
            else:
                rec = next(x for x in man["references"] if x["name"] == by_gid[dom].name)
                p = Path(rec["path"])
                ref_sc = _selfcross(p if p.is_absolute() else refs_dir / p, tools, threads=workers)
                if ref_sc and "transverse" in ref_sc:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    # the count covers the whole mesh, so the rate is per cm2 of the whole mesh, not of its
                    # labelled part (the manifest's area_cm2)
                    D = by_gid[dom]
                    ref_sc["area_cm2"] = _r(float(D.area[D.ok].sum()) * (VOXEL_UM * 1e-4) ** 2, 3)
                    cache.write_text(json.dumps(ref_sc))
            rate = sc["transverse"] / max(summary["area_cm2"], 1e-9)
            ref_rate = (ref_sc["transverse"] / max(ref_sc.get("area_cm2") or 1e-9, 1e-9)
                        if ref_sc and "transverse" in ref_sc else None)
            sc.update({"per_cm2": _r(rate), "reference": by_gid[dom].name, "reference_per_cm2": _r(ref_rate),
                       "ratio": _r(rate / ref_rate) if ref_rate else None})
        out["metrics"]["selfcross"] = sc if sc is not None else "vc_tifxyz_selfcross not found"
    # controls at the candidate's site
    if controls:
        site, box = _site_for(summary, internal, near, refs, rule)
        if site is None:
            out["controls"] = {"valid": False, "failed": ["no site for the controls"]}
        else:
            out["controls"] = site_controls(refs, man, site, box, rule, workers)
        if not out["controls"]["valid"]:
            out["invalid_reasons"].append("controls failed: " + ", ".join(out["controls"]["failed"]))
    else:
        out["invalid_reasons"].append("controls not run")
    out["valid"] = not out["invalid_reasons"]
    m4 = summary["d4"]
    if not out["valid"]:
        out["verdict"] = "invalid"
    elif m4["scored_share"] < A_["min_scored_share"]:
        out["verdict"] = "not scorable"
    elif (m4["dominant_precision"] or 0.0) >= A_["bar"]:
        out["verdict"] = "one winding"
    else:
        out["verdict"] = "not one winding"
    out["seconds"] = round(time.time() - t0, 1)
    return out


def _site_for(summary, internal, near, refs, rule):
    """The candidate's dominant winding and the window of it under the candidate (clipped to the control window
    range), or the nearest reference when no vertex lies on one."""
    np = _np()
    lo, hi = rule["controls"]["window"]
    cls, lab, best = internal["d4"]
    J = internal["J"]
    by_gid = {r.gid: r for r in refs}
    dom = summary.get("dominant_id")
    if dom is not None:
        row = next(i for i, r in enumerate(near) if r.gid == dom)
        A = by_gid[dom]
        js = J[row, lab == dom]
    else:
        have = best >= 0
        if not have.any():
            return None, None
        row = int(np.bincount(best[have]).argmax())
        A = near[row]
        js = J[row, have & (best == row)]
    W = A.valid.shape[1]
    rc = np.stack([js // W, js % W], 1)
    r0, c0 = rc.min(0)
    r1, c1 = rc.max(0) + 1
    # centred on a vertex the candidate covers (the one nearest the median), not on the middle of the bounding
    # box, which can fall in a hole or a masked part of the winding and leave the window without labelled vertices
    med = np.median(rc, axis=0)
    centre = tuple(int(v) for v in rc[int(np.argmin(((rc - med) ** 2).sum(1)))])
    size = int(min(max(max(r1 - r0, c1 - c0), lo), hi))
    return A, _box_around(A, centre, size)


# ---------------------------------------------------------------- surface prediction: contact separation

PRED_CT = f"{SAMPLE}/volumes/{VOLUME}-9.362um-1.2m-113keV-masked.zarr"
PRED_SOURCES = {"m7": PRED_M7, "recto090": PRED_RECTO, "ct": PRED_CT}
PRED_TRANSFORMS = ("dilate", "lattice", "shift", "oracle", "matched", "erode")
M7_LEVEL0 = {"shape": [20974, 6621, 6621], "dtype": "uint8"}   # m7's level 0 (and recto-090's and the CT's)

# Stage 4 of docs/plans/2026-10-09-autopipeline-bars.md (surface prediction), version 1, fixed 9 October 2026 before
# any map was scored with it. Kept as it was (digest 08e11933de66) so its development run can be reproduced:
# `predscore --rule-version 1`. The chunk sample is not a constant here: it is drawn from the references with the
# seed below and written into the run rule (pred_run_rule), whose digest every predscore run prints.
PRED_RULE_V1 = {
    "version": 1,
    "frame": {"sample": SAMPLE, "volume": VOLUME, "voxel_um": VOXEL_UM},
    "on_threshold": 128,             # a map voxel is on at >= 128 (the published maps hold 0 and 255)
    "chunk": 192,                    # sampling and bootstrap cluster: one level-0 chunk of m7
    "lines": {
        "main_vox": [5.0, 8.0],      # a counted line: A's outer adjacent winding B this far along A's outward normal
        "stratum_vox": [3.0, 5.0],   # g in [3, 5): reported apart, the two seating tolerances overlap there
        "seat_pad_vox": 2.0,         # A window [-2, g/2), B window (g/2, g + 2], disjoint
        "step_vox": 0.5,             # samples along the line
        "window_half_vox": 10,       # components in the cube of 21 voxels around the line's midpoint
        "connectivity": 26,          # a diagonal touch joins two sheets
    },
    "guards": {
        "share_margin": 0.02,        # G1, G4: interval of challenger minus bar >= -0.02 at its low end; G2 <= +0.02
        "ratio_band": [0.8, 1.25],   # volume and band thickness: the interval of challenger over bar inside this
        "fill_clear_vox": 3.0,       # G2: a fill point lies at least this far from the next sheet
        "g4_reach": 0.8,             # G4: A's component reaches this share of A's dense points in the window
        "g4_upsample": 4,
        "g4_pad_vox": 2,             # a dense point is reached when its component lies within 2 along its normal
    },
    "beat": {"cs_gain": 0.02},
    "bootstrap": {"resamples": 10000, "seed": 0, "level": 0.95},
    "controls": {
        "dilate_vox": 1,             # m7 dilated by one voxel (6-connected)
        "lattice_vox": 16,           # m7 with every 16th plane along each axis cleared
        "shift_vox": 4.0,            # m7 moved 4 voxels along the chunk's median outward normal: must fail G1
        "displace_pitch": 0.5,       # lines moved half their winding's local pitch ...
        "displace_sign": -1,         # ... inward
        "displace_drop": 0.30,       # ... must drop m7's clean share by this much, or the run is VOID
        "oracle_half_vox": 1.0,      # reference oracle: on-voxels within 1 voxel of the A to B midplane removed
        "oracle_radius_vox": 15.0,   # ... in a disc of this radius around each contact vertex's midpoint
        "headroom": 0.02,
    },
    "sample": {"seed": 0, "dev_chunks": 120, "report_chunks": 120, "min_lines": 8},
}

# Version 2, fixed 9 October 2026 on development data only, before any report chunk sample was drawn. It takes the
# review of version 1 and the owner's recommended option on the bar definitions: the volume and thickness guards are
# one-sided non-inferiority as the plan says (no extra volume or thickness; thinning is left to the matched-budget
# erosion null), G4 no longer credits a merge with continuity and is measured for both sheets, and the displaced
# control asks for a relative drop. Every key that version 1 lacks switches one behaviour on; version 1 runs as it
# did.
PRED_RULE = {
    "version": 2,
    "frame": {"sample": SAMPLE, "volume": VOLUME, "voxel_um": VOXEL_UM, "level0": M7_LEVEL0},
    "on_threshold": 128,
    "chunk": 192,
    "lines": {
        "main_vox": [5.0, 8.0],
        "stratum_vox": [3.0, 5.0],
        "seat_pad_vox": 2.0,
        "step_vox": 0.5,
        "window_half_vox": 10,
        "connectivity": 26,
        "windows": "voxel",          # each sampled voxel once: in A's window when (v - P).N < g/2, else in B's
    },
    "mask": {"ct_regions": True,     # G1 region vertices only where the CT at offset 0 is above 0
             "ct_volume": True},     # cube volumes (and the CT arm's matched volume) only where the CT is above 0
    "guards": {
        "share_margin": 0.02,
        "ratio_max": 1.25,           # volume and thickness: the interval's upper end of challenger over bar at most
        "fill_clear_vox": 3.0,
        "g4_reach": 0.8,
        "g4_upsample": 4,
        "g4_pad_vox": 2,
        "g4_sides": ["a", "b"],      # both sheets of a line must keep their continuity
        "g4_exclusive": True,        # a component that also holds the other window's samples does not count
    },
    "beat": {"cs_gain": 0.02, "erosion_null": True},
    "bootstrap": {"resamples": 10000, "seed": 0, "level": 0.95},
    "controls": {
        "dilate_vox": 1,
        "lattice_vox": 16,
        "shift_vox": 4.0,
        "displace_pitch": 0.5,
        "displace_sign": -1,
        "displace_max_ratio": 0.5,   # displaced clean share at most half the true lines' (a drop of 50 %), else VOID
        "oracle_half_vox": 1.0,
        "oracle_radius_vox": 15.0,
        "oracle_lines": "split",     # oracle patches only from lines whose two windings are both in the split
        "identity": "second_reader",  # m7 read again through LocalZarr on the cached copy, measured apart
        "headroom": 0.02,
    },
    "erosion": {"seed": 0},          # tie order of the matched-budget erosion null
    "frame_check": {"max_shift_vox": 4, "min_dice": 0.5},
    "sample": {"seed": 0, "dev_chunks": 120, "report_chunks": 120, "min_lines": 8},
    "run_rule": {"scorer_sha256": True},
}

PRED_RULES = {1: PRED_RULE_V1, 2: PRED_RULE}


def _nd():
    try:
        from scipy import ndimage
    except ImportError as exc:
        raise BenchError("kit surfbench predscore needs scipy.ndimage") from exc
    return ndimage


def _opt(prule, section, key, default=None):
    """A rule key that version 1 does not have reads as its version 1 behaviour."""
    return (prule.get(section) or {}).get(key, default)


def _enc(k):
    """Codes of (z, y, x) chunk indices, as the audit's region keys."""
    np = _np()
    k = np.asarray(k, dtype=np.int64)
    return (k[..., 0] << 20) | (k[..., 1] << 10) | k[..., 2]


def _dec(code):
    code = int(code)
    return (code >> 20, (code >> 10) & 1023, code & 1023)


def _ckey(code):
    return "_".join(map(str, _dec(code)))


class LocalZarr:
    """Level-0 chunks of a local zarr v2 array (the array folder or its multiscale root), read like ChunkReader.

    A chunk file that is not there reads as the array's fill value, as zarr defines it, and is counted in `absent`:
    it is never missing, so a candidate cannot take a sampled chunk out of the comparison by leaving it unwritten.
    The array must be in m7's frame (level-0 shape (20974, 6621, 6621)) and uint8 unless an explicit offset (the frame
    voxel where the array's voxel 0 sits) and threshold are both given; given ones are recorded in the run rule."""

    def __init__(self, path, offset=None, threshold=None, expect=None):
        np = _np()
        path = Path(path)
        if not (path / ".zarray").is_file() and (path / "0" / ".zarray").is_file():
            path = path / "0"
        if not (path / ".zarray").is_file():
            raise BenchError(f"{path}: not a zarr v2 array (no .zarray)")
        self.root = path
        self.meta = json.loads((path / ".zarray").read_text())
        if self.meta.get("order", "C") != "C":
            raise BenchError(f"{path}: only C-order chunks are read")
        self.chunks = tuple(self.meta["chunks"])
        self.sep = self.meta.get("dimension_separator", ".")
        self.dtype = np.dtype(self.meta["dtype"])
        fv = self.meta.get("fill_value")
        self.fill = 0 if fv is None else fv
        exp = expect or M7_LEVEL0
        bad = []
        if list(self.meta.get("shape", [])) != list(exp["shape"]):
            bad.append(f"level-0 shape {self.meta.get('shape')} is not m7's {exp['shape']}")
        if self.dtype != np.dtype(exp["dtype"]):
            bad.append(f"dtype {self.dtype} is not {exp['dtype']}")
        if bad and (offset is None or threshold is None):
            raise BenchError(f"{path}: " + "; ".join(bad) + ": give an explicit offset and threshold (--offset, "
                             "--threshold), which the run rule records")
        self.offset = tuple(int(v) for v in offset) if offset is not None else (0, 0, 0)
        self.threshold = threshold
        self.declared = {k: v for k, v in (("offset", list(self.offset) if offset is not None else None),
                                           ("threshold", threshold)) if v is not None}
        self.fetched = self.cached = self.missing = self.absent = 0
        self.max_value = 0
        self._lock = threading.Lock()

    def read(self, idx):
        np = _np()
        from . import vc3d_audit
        f = self.root / self.sep.join(str(int(i)) for i in idx)
        if not f.is_file():
            with self._lock:
                self.absent += 1
            return np.full(self.chunks, self.fill, self.dtype)
        data = vc3d_audit._decompress(self.meta.get("compressor"), f.read_bytes())
        arr = np.frombuffer(data, dtype=self.dtype).reshape(self.chunks)
        top = arr.max().item() if arr.size else 0
        with self._lock:
            self.cached += 1
            self.max_value = max(self.max_value, top)
        return arr


def _read_block(reader, origin, size):
    """The cube [origin, origin + size) of a reader's level-0 array (zeros past the array's ends, and before its
    start for a reader with an offset) and how many of the chunks under it are missing."""
    np = _np()
    C = np.array(reader.chunks, dtype=np.int64)
    o = np.asarray(origin, dtype=np.int64) - np.asarray(getattr(reader, "offset", None) or (0, 0, 0), dtype=np.int64)
    shape = (getattr(reader, "meta", None) or {}).get("shape")
    out, missing = None, 0
    lo, hi = o // C, (o + size - 1) // C
    for cz in range(int(lo[0]), int(hi[0]) + 1):
        for cy in range(int(lo[1]), int(hi[1]) + 1):
            for cx in range(int(lo[2]), int(hi[2]) + 1):
                c = np.array([cz, cy, cx], dtype=np.int64)
                if (c < 0).any() or (shape is not None and (c * C >= np.array(shape)).any()):
                    continue
                arr = reader.read((cz, cy, cx))
                if arr is None:
                    missing += 1
                    continue
                if out is None:
                    out = np.zeros((size,) * 3, arr.dtype)
                c0 = c * C
                a, b = np.maximum(o, c0), np.minimum(o + size, c0 + C)
                out[a[0] - o[0]:b[0] - o[0], a[1] - o[1]:b[1] - o[1], a[2] - o[2]:b[2] - o[2]] = \
                    arr[a[0] - c0[0]:b[0] - c0[0], a[1] - c0[1]:b[1] - c0[1], a[2] - c0[2]:b[2] - c0[2]]
    if out is None:
        out = np.zeros((size,) * 3, np.uint8)
    return out, missing


def _outward(A, rec):
    """(outward sign, outward offset to the nearest sheet, its label, gap flag) of a reference's vertices."""
    o = 1 if A.attrs.get("orient", rec.get("orient", 1)) > 0 else -1
    s = "pos" if o > 0 else "neg"
    return o, A.attrs[f"g_{s}"], A.attrs[f"lab_{s}"], A.attrs[f"gap_{s}"]


def _outer_adjacent(A, rec, refs, recs):
    """Ids of the windings adjacent to A on its outer side across a step that is not a gap."""
    rk = rec.get("rank")
    return [r.gid for r in refs if r.name in rec.get("chain_adjacent", []) and rk is not None
            and recs.get(r.name, {}).get("rank") is not None and recs[r.name]["rank"] > rk]


def _pred_lines(refs, man, prule):
    """Every contact line of the stack: a labelled vertex of winding A whose nearest sheet along A's outward normal
    is B, the winding adjacent to A on its outer side across a step that is not a gap, between stratum_vox[0] and
    main_vox[1] voxels away (from the manifest's per-vertex offsets). Lines are taken from the inner winding only,
    so each contact is counted once. Returns arrays: p, n (zyx), g, pitch (A's local pitch), a, b (ids), main."""
    np = _np()
    L = prule["lines"]
    lo, hi = L["stratum_vox"][0], L["main_vox"][1]
    recs = {x["name"]: x for x in man["references"]}
    cols = collections.defaultdict(list)
    for A in refs:
        rec = recs.get(A.name)
        if rec is None or rec.get("rank") is None or "g_pos" not in A.attrs:
            continue
        o, g, lab, _ = _outward(A, rec)
        outer = _outer_adjacent(A, rec, refs, recs)
        sel = A.labelled() & np.isin(lab, outer) & (g >= lo) & (g <= hi)
        if not sel.any():
            continue
        k = int(sel.sum())
        cols["p"].append(A.xyz[sel][:, ::-1])
        cols["n"].append(A.normals[sel][:, ::-1] * o)
        cols["g"].append(g[sel].astype(np.float64))
        cols["pitch"].append(np.full(k, float(rec.get("local_pitch_vox") or np.nan)))
        cols["a"].append(np.full(k, A.gid, np.int64))
        cols["b"].append(lab[sel].astype(np.int64))
    if not cols:
        z = np.zeros(0)
        return {"p": np.zeros((0, 3)), "n": np.zeros((0, 3)), "g": z, "pitch": z, "a": z.astype(np.int64),
                "b": z.astype(np.int64), "main": z.astype(bool)}
    out = {k: np.concatenate(v) for k, v in cols.items()}
    out["main"] = out["g"] >= L["main_vox"][0]
    return out


def _box(box):
    """A box (z0, z1, y0, y1, x0, x1), half-open, as a (3, 2) array, or None."""
    if box is None:
        return None
    np = _np()
    b = np.asarray(box, dtype=np.int64).ravel()
    if b.size != 6 or (b[1::2] <= b[0::2]).any():
        raise BenchError(f"box {list(box)}: z0 z1 y0 y1 x0 x1 with each end above its start")
    return b.reshape(3, 2)


def _place(P, N, g, prule, box=None):
    """Midpoint voxel of each line, its chunk code, and whether the line's window cube lies inside that chunk (and
    inside the box, when one is given)."""
    np = _np()
    h, C = int(prule["lines"]["window_half_vox"]), int(prule["chunk"])
    c = np.rint(P + (g / 2)[:, None] * N).astype(np.int64)
    key = np.floor_divide(c, C)
    inside = ((c - h) >= key * C).all(1) & ((c + h) <= key * C + C - 1).all(1)
    b = _box(box)
    if b is not None:
        inside &= ((c - h) >= b[:, 0]).all(1) & ((c + h) <= b[:, 1] - 1).all(1)
    return c, _enc(key), inside


def _split_ids(refs, rule, split):
    names = set(rule["split"]["tune" if split == "dev" else "report"])
    return sorted(r.gid for r in refs if r.name in names), names


def _report_chunks(refs, rule, lines, C):
    """Codes of the chunks that hold a point of a report winding's 2x dense grid or a point of a report line (its
    two ends and midpoint): never read on the development split."""
    np = _np()
    rep, _ = _split_ids(refs, rule, "report")
    bad = set()
    for r in refs:
        if r.gid in rep and r.valid.any():
            up, uv, _ = upsample(r.xyz, r.valid, 2)
            bad |= set(np.unique(_enc(np.floor_divide(up[uv][:, ::-1], C).astype(np.int64))).tolist())
    rl = np.isin(lines["a"], rep) | np.isin(lines["b"], rep)
    for t in (0.0, 0.5, 1.0):
        q = lines["p"][rl] + (t * lines["g"][rl])[:, None] * lines["n"][rl]
        bad |= set(np.unique(_enc(np.floor_divide(q, C).astype(np.int64))).tolist())
    return bad


def pred_sample(refs, man, split, rule=None, prule=None, lines=None, box=None):
    """The seeded chunk sample of a split: chunks holding at least min_lines counted lines (5 to 8 voxels) whose two
    windings are both in the split and whose window lies in the chunk; for dev, only chunks that hold no point of a
    report winding (its 2x dense grid) and no line of one. With a box (box-only scoring): every such chunk with at
    least one counted line whose window lies in the box, no draw. Geometry only: no map is read. Returns (codes,
    the number of eligible chunks)."""
    np = _np()
    rule, prule = rule or RULE, prule or PRED_RULE
    lines = _pred_lines(refs, man, prule) if lines is None else lines
    C = int(prule["chunk"])
    ids, _ = _split_ids(refs, rule, split)
    _, codes, inside = _place(lines["p"], lines["n"], lines["g"], prule, box)
    ok = lines["main"] & inside & np.isin(lines["a"], ids) & np.isin(lines["b"], ids)
    u, cnt = np.unique(codes[ok], return_counts=True)
    cand = u[cnt >= (1 if box is not None else prule["sample"]["min_lines"])]
    if split == "dev":
        bad = _report_chunks(refs, rule, lines, C)
        cand = np.array([k for k in cand.tolist() if k not in bad], dtype=np.int64)
    if box is not None:
        return sorted(int(k) for k in cand), int(len(cand))
    rng = np.random.default_rng(prule["sample"]["seed"])
    n = prule["sample"]["dev_chunks" if split == "dev" else "report_chunks"]
    pick = sorted(int(k) for k in cand[rng.permutation(len(cand))[:n]]) if len(cand) else []
    return pick, int(len(cand))


def pred_run_rule(split, chunks, man, rule=None, prule=None, box=None, local=None):
    """The rule a predscore run is reported under: PRED_RULE, the seating rule G1 uses, the split's windings, the
    manifest, the chunk sample itself and (version 2) the SHA-256 of this scorer's code; a box and any explicit
    offset or threshold of a local map are added when given. Its digest is printed by every run and must be
    committed before a report run (--frozen)."""
    rule, prule = rule or RULE, prule or PRED_RULE
    rr = {"kind": "kit-surfbench-predscore-rule", "pred_rule": prule, "seating": rule["seating"], "split": split,
          "windings": sorted(rule["split"]["tune" if split == "dev" else "report"]),
          "manifest_digest": man["digest"], "chunks": [_ckey(k) for k in chunks]}
    if _opt(prule, "run_rule", "scorer_sha256"):
        rr["scorer_sha256"] = _sha256(Path(__file__))
    if box is not None:
        rr["box"] = [int(v) for v in _box(box).ravel()]
    if local:
        rr["local_maps"] = {k: v for k, v in sorted(local.items()) if v}
    return rr


def _pred_regions(refs, man, ids, rule, prule, want):
    """G1 regions (the audit's): per chunk of `want`, each split winding's labelled vertices outside contact zones
    and chunk_margin_vox inside the chunk, when there are at least min_chunk_vertices of them."""
    np = _np()
    S, C = rule["seating"], int(prule["chunk"])
    recs = {x["name"]: x for x in man["references"]}
    out = collections.defaultdict(list)
    want = np.array(sorted(want), dtype=np.int64)
    for r in refs:
        if r.gid not in ids or "contact" not in r.attrs or r.name not in recs:
            continue
        o = 1 if r.attrs.get("orient", recs[r.name]["orient"]) > 0 else -1
        sel = r.labelled() & ~r.attrs["contact"]
        p = r.xyz[sel][:, ::-1]
        n = r.normals[sel][:, ::-1] * o
        key = np.floor_divide(p, C).astype(np.int64)
        local = p - key * C
        code = _enc(key)
        keep = ((local >= S["chunk_margin_vox"]) & (local < C - S["chunk_margin_vox"])).all(1) & np.isin(code, want)
        if not keep.any():
            continue
        order = np.argsort(code[keep], kind="stable")
        ck, lp, nn = code[keep][order], local[keep][order], n[keep][order]
        u, start, cnt = np.unique(ck, return_index=True, return_counts=True)
        for k, s0, c in zip(u.tolist(), start.tolist(), cnt.tolist()):
            if c >= S["min_chunk_vertices"]:
                out[k].append((r.name, lp[s0:s0 + c], nn[s0:s0 + c]))
    return out


def _pred_fill(refs, man, ids, prule, want):
    """G2 points: split windings' labelled vertices outside contact zones whose outer side is no gap and whose next
    sheet outward is the adjacent winding, moved outward by half the winding's local pitch (from the manifest),
    kept where that point is at least fill_clear_vox from the next sheet."""
    np = _np()
    C = int(prule["chunk"])
    clear = prule["guards"]["fill_clear_vox"]
    recs = {x["name"]: x for x in man["references"]}
    want = np.array(sorted(want), dtype=np.int64)
    out = collections.defaultdict(list)
    for A in refs:
        rec = recs.get(A.name)
        if A.gid not in ids or rec is None or "g_pos" not in A.attrs or not rec.get("local_pitch_vox"):
            continue
        half = 0.5 * float(rec["local_pitch_vox"])
        o, g, lab, gap = _outward(A, rec)
        outer = _outer_adjacent(A, rec, refs, recs)
        sel = (A.labelled() & ~A.attrs["contact"] & ~gap & np.isin(lab, outer) & np.isfinite(g) & (g >= half + clear))
        if not sel.any():
            continue
        q = A.xyz[sel][:, ::-1] + half * (A.normals[sel][:, ::-1] * o)
        key = np.floor_divide(q, C).astype(np.int64)
        code = _enc(key)
        keep = np.isin(code, want)
        for k in np.unique(code[keep]).tolist():
            m = keep & (code == k)
            out[k].append(q[m] - np.array(_dec(k)) * C)
    return {k: np.concatenate(v) for k, v in out.items()}


def _dense_points(A, orient, origin, C, k):
    """A's labelled grid made k times denser (bilinear), points and outward normals in chunk-local zyx, inside the
    chunk."""
    np = _np()
    lab = A.labelled()
    p = A.xyz[..., ::-1]
    near = lab & ((p >= origin - 32) & (p < origin + C + 32)).all(-1)
    if not near.any():
        return np.zeros((0, 3)), np.zeros((0, 3))
    rr, cc = np.nonzero(near)
    H, W = lab.shape
    r0, r1 = max(int(rr.min()) - 1, 0), min(int(rr.max()) + 2, H)
    c0, c1 = max(int(cc.min()) - 1, 0), min(int(cc.max()) + 2, W)
    up, uv, _ = upsample(A.xyz[r0:r1, c0:c1], lab[r0:r1, c0:c1], k)
    nrm, _, ok, _ = grid_geometry(up, uv)
    pts = up[ok][:, ::-1] - origin
    nn = nrm[ok][:, ::-1] * orient
    inn = ((pts >= 0) & (pts < C)).all(1)
    return pts[inn], nn[inn]


class _Lines:
    """The counted lines of one chunk, in chunk-local voxels: samples along each line, the two seating windows,
    the window cube and, for G4, the dense points of A (and of B, version 2) inside it.

    Version 1 splits the windows on the sample parameter t (A below g/2, B above), so after rounding one voxel can
    be in both. Version 2 assigns each sampled voxel once, by its own position: A's window when (v - P).N < g/2,
    else B's, and keeps each voxel once per window."""

    def __init__(self, P, N, g, a, main, prule, ct, dense=None, b=None, dense_b=None):
        np = _np()
        L = prule["lines"]
        h, step, pad = int(L["window_half_vox"]), L["step_vox"], L["seat_pad_vox"]
        self.W = W = 2 * h + 1
        C = ct.shape[0]
        t = np.arange(-pad, L["main_vox"][1] + pad + 1e-9, step)
        S = np.rint(P[:, None, :] + t[None, :, None] * N[:, None, :]).astype(np.int64)
        valid = t[None, :] <= g[:, None] + pad + 1e-9
        Sc = np.clip(S, 0, C - 1)
        in_ct = ((ct[Sc[..., 0], Sc[..., 1], Sc[..., 2]] > 0) | ~valid).all(1) & ((S >= 0) & (S < C)).all((1, 2))
        c = np.rint(P + (g / 2)[:, None] * N).astype(np.int64)
        keep = in_ct & ((c - h) >= 0).all(1) & ((c + h) <= C - 1).all(1)
        self.index = np.flatnonzero(keep)
        self.P, self.N, self.g, self.a, self.main = P[keep], N[keep], g[keep], a[keep], main[keep]
        self.b = b[keep] if b is not None else None
        self.S, self.valid, self.lo = S[keep], valid[keep], c[keep] - h
        self.voxel_windows = L.get("windows") == "voxel"
        if self.voxel_windows:
            proj = ((self.S - self.P[:, None, :]) * self.N[:, None, :]).sum(-1)
            in_a = proj < self.g[:, None] / 2
            self.a_win = self.valid & in_a
            self.b_win = self.valid & ~in_a
        else:
            self.a_win = self.valid & (t[None, :] < self.g[:, None] / 2)
            self.b_win = self.valid & (t[None, :] > self.g[:, None] / 2)
        self.step = step
        rel = self.S - self.lo[:, None, :]
        flat = rel[..., 0] * W * W + rel[..., 1] * W + rel[..., 2]
        uniq = np.unique if self.voxel_windows else (lambda x: x)
        self.fa = [uniq(flat[i][self.a_win[i]]) for i in range(len(self.g))]
        self.fb = [uniq(flat[i][self.b_win[i]]) for i in range(len(self.g))]
        self.ct_on = (ct > 0) if _opt(prule, "mask", "ct_volume") else None
        self.dense = self._dense(dense, self.a, prule, ct, C) if dense is not None else []
        self.dense_b = self._dense(dense_b, self.b, prule, ct, C) if dense_b is not None and self.b is not None \
            else []

    def _dense(self, dense, ids, prule, ct, C):
        np = _np()
        G = prule["guards"]
        W = self.W
        offs = np.arange(-G["g4_pad_vox"], G["g4_pad_vox"] + 1)
        V = {}
        for gid, (dp, dn) in dense.items():
            if len(dp):
                dc = np.clip(np.rint(dp).astype(np.int64), 0, C - 1)
                good = ct[dc[:, 0], dc[:, 1], dc[:, 2]] > 0
                V[gid] = np.rint(dp[good][:, None, :] + offs[None, :, None] * dn[good][:, None, :]).astype(np.int64)
        out = []
        for i in range(len(self.g)):
            v = V.get(int(ids[i]))
            if v is None:
                out.append(np.zeros((0, len(offs)), np.int64))
                continue
            r = v - self.lo[i]
            ok = ((r >= 0) & (r < W)).all((1, 2))
            r = r[ok]
            out.append(r[..., 0] * W * W + r[..., 1] * W + r[..., 2])
        return out

    def __len__(self):
        return len(self.g)


def _structure(prule):
    np = _np()
    nd = _nd()
    conn = int(prule["lines"]["connectivity"])
    if conn == 26:
        return np.ones((3, 3, 3), bool)
    if conn == 6:
        return nd.generate_binary_structure(3, 1)
    if conn == 18:
        return nd.generate_binary_structure(3, 2)
    raise BenchError(f"connectivity {conn} is not 6, 18 or 26")


def _measure_lines(arm, CL, prule, g4=True):
    """Per line on one binary map: A on (an on sample in A's window), B on, clean (both on and no component of the
    window cube holds samples of both windows), G4, on-length along the line in both windows (voxels) and
    on-voxels in the cube (version 2: where the CT is above 0).

    G4, version 1: A's components (any holding an A sample) reach g4_reach of A's dense points in the cube, so a
    component merged with B counts. Version 2: for each side in g4_sides, that side's components that hold none of
    the other window's samples reach g4_reach of its own dense points; the line keeps G4 when every side does."""
    np = _np()
    nd = _nd()
    n = len(CL)
    out = {k: np.zeros(n, bool) for k in ("a_on", "b_on", "clean", "g4", "g4_a", "g4_b")}
    out["thick"] = np.zeros(n)
    out["vol"] = np.zeros(n, np.int64)
    if n == 0:
        return out
    S = CL.S
    on = arm[np.clip(S[..., 0], 0, arm.shape[0] - 1), np.clip(S[..., 1], 0, arm.shape[1] - 1),
             np.clip(S[..., 2], 0, arm.shape[2] - 1)] & CL.valid
    out["a_on"] = (on & CL.a_win).any(1)
    out["b_on"] = (on & CL.b_win).any(1)
    out["thick"] = (on & (CL.a_win | CL.b_win)).sum(1) * CL.step
    st = _structure(prule)
    W = CL.W
    G = prule["guards"]
    reach = G["g4_reach"]
    sides = list(G.get("g4_sides", ["a"]))
    exclusive = bool(G.get("g4_exclusive", False))
    for i in range(n):
        z, y, x = (int(v) for v in CL.lo[i])
        box = arm[z:z + W, y:y + W, x:x + W]
        out["vol"][i] = int((box & CL.ct_on[z:z + W, y:y + W, x:x + W]).sum()) if CL.ct_on is not None \
            else int(box.sum())
        if not (out["a_on"][i] or ("b" in sides and out["b_on"][i])):
            continue
        lab, _ = nd.label(box, structure=st)
        flat = lab.ravel()
        la = flat[CL.fa[i]]
        ca = np.unique(la[la > 0])
        lb = flat[CL.fb[i]]
        cb = np.unique(lb[lb > 0])
        if out["a_on"][i] and out["b_on"][i]:
            out["clean"][i] = bool(ca.size and cb.size and not np.isin(ca, cb).any())
        if not g4:
            continue
        ok = True
        for side in sides:
            own, other = (ca, cb) if side == "a" else (cb, ca)
            dl = CL.dense if side == "a" else CL.dense_b
            if not (out["a_on"][i] if side == "a" else out["b_on"][i]):
                held = False
            else:
                comps = own[~np.isin(own, other)] if exclusive else own
                d = dl[i] if i < len(dl) else None
                held = bool(d is None or d.size == 0 or (comps.size and np.isin(flat[d], comps).any(1).mean()
                                                          >= reach))
            out[f"g4_{side}"][i] = held
            ok = ok and held
        out["g4"][i] = ok
    return out


def _seat_regions(arm, regions, rule):
    """G1 by the audit's rule on one map: per region the share on the map along the outward normal from
    -max_offset_vox to +max_offset_vox, its peak, and seated, unseated or weak."""
    S = rule["seating"]
    offs = list(range(-S["max_offset_vox"], S["max_offset_vox"] + 1))
    c = collections.Counter()
    for _, p, n in regions:
        pk, ps = _peak(_profile(arm, p, n, offs, 1), offs)
        c[_status(pk, ps, S)] += 1
    return c


def _lattice(shape, origin, step):
    np = _np()
    z, y, x = (((np.arange(s) + o) % step) == 0 for s, o in zip(shape, origin))
    return z[:, None, None] | y[None, :, None] | x[None, None, :]


def _oracle_cut(m, patches, prule):
    """m with its on-voxels within oracle_half_vox of the A to B midplane removed, in a disc of oracle_radius_vox
    around each contact vertex's midpoint (patches: (midpoint, normal) in chunk-local voxels). It reads the
    references, so it is a control, never a candidate."""
    np = _np()
    Cc = prule["controls"]
    R, half = float(Cc["oracle_radius_vox"]), float(Cc["oracle_half_vox"])
    out = m.copy()
    r = int(math.ceil(R))
    grid = np.stack(np.meshgrid(*[np.arange(-r, r + 1)] * 3, indexing="ij"), -1).reshape(-1, 3)
    shape = np.array(m.shape)
    for mid, nrm in patches:
        c = np.rint(mid).astype(np.int64)
        v = grid + c
        rel = v - mid
        d = rel @ nrm
        lat2 = (rel * rel).sum(1) - d * d
        hit = (np.abs(d) <= half) & (lat2 <= R * R) & ((v >= 0) & (v < shape)).all(1)
        v = v[hit]
        out[v[:, 0], v[:, 1], v[:, 2]] = False
    return out


def _oracle_patches(lines, in_split, origin, C, prule):
    """(midpoint, normal) of the contact lines whose oracle disc can reach the chunk. Version 2 takes only lines
    whose two windings are both in the run's split, so no other split's references reach a control arm."""
    R = prule["controls"]["oracle_radius_vox"]
    near = ((lines["mid"] >= origin - R - 1) & (lines["mid"] < origin + C + R + 1)).all(1)
    if _opt(prule, "controls", "oracle_lines", "all") == "split":
        near = near & in_split
    return [(mm - origin, nn) for mm, nn in zip(lines["mid"][near], lines["n"][near])]


def _erode_matched(m, chal, union, prule):
    """The matched-budget erosion null: m with as many of its on-voxels inside `union` (the counted lines' window
    cubes) removed as the challenger removed there (on in m, off in the challenger), peeled from both faces of
    every sheet at once: in order of the Euclidean distance to the nearest off voxel of m, ties in a seeded random
    order. Returns (map, budget)."""
    np = _np()
    budget = int((m & ~chal & union).sum())
    if budget == 0:
        return m.copy(), 0
    d = _nd().distance_transform_edt(m)
    cand = np.flatnonzero((m & union).ravel())
    tie = np.random.default_rng(int(_opt(prule, "erosion", "seed", 0))).random(cand.size)
    order = np.lexsort((tie, d.ravel()[cand]))
    out = m.copy()
    out.reshape(-1)[cand[order[:budget]]] = False
    return out, budget


def _parse_arm(spec):
    base, _, tr = str(spec).rpartition(":")
    if base and tr in PRED_TRANSFORMS:
        return base, tr
    return str(spec), None


def _arm_map(spec, blocks, ctx, prule):
    """One arm's binary map of a chunk: a source thresholded at on_threshold (or a local map's own threshold), or
    one transformed by a control or the erosion null."""
    np = _np()
    nd = _nd()
    base, tr = _parse_arm(spec)
    Cc = prule["controls"]
    if tr == "matched":
        if base != "ct":
            raise BenchError("only the CT is thresholded at m7's volume (ct:matched)")
        return blocks["ct"] >= ctx["ct_tau"]
    thr = (ctx.get("thresholds") or {}).get(base)
    m = blocks[base] >= (prule["on_threshold"] if thr is None else thr)
    if tr is None:
        return m
    if tr == "dilate":
        return nd.binary_dilation(m, structure=nd.generate_binary_structure(3, 1), iterations=int(Cc["dilate_vox"]))
    if tr == "lattice":
        return m & ~_lattice(m.shape, ctx["origin"], int(Cc["lattice_vox"]))
    if tr == "shift":
        vec = float(Cc["shift_vox"]) * ctx["normal"]
        return nd.shift(m.astype(np.uint8), vec, order=0, mode="constant", cval=0) > 0
    if tr == "oracle":
        return _oracle_cut(m, ctx["patches"], prule)
    if tr == "erode":
        out, budget = _erode_matched(m, ctx["challenger_map"], ctx["union"], prule)
        ctx.setdefault("erode_budget", {})[spec] = budget
        return out
    raise BenchError(f"unknown transform {tr}")


def _ct_tau(ct, m7, CL, mask_ct=False):
    """The CT level whose on-volume inside the line windows comes closest to m7's there (version 2: m7's counted
    where the CT is above 0, as the arms' volumes are)."""
    np = _np()
    W = CL.W
    union = np.zeros(ct.shape, bool)
    for lo in CL.lo:
        z, y, x = (int(v) for v in lo)
        union[z:z + W, y:y + W, x:x + W] = True
    if not union.any():
        return 255
    target = int(m7[union & (ct > 0)].sum()) if mask_ct else int(m7[union].sum())
    hist = np.bincount(ct[union].astype(np.int64).ravel(), minlength=int(ct.max()) + 2)
    above = np.cumsum(hist[::-1])[::-1]          # above[v] = voxels with CT >= v
    lv = np.arange(1, len(above))
    return int(lv[np.argmin(np.abs(above[1:] - target))])


def _cube_union(CL, shape, main_only=True):
    np = _np()
    W = CL.W
    union = np.zeros(shape, bool)
    for i, lo in enumerate(CL.lo):
        if main_only and not CL.main[i]:
            continue
        z, y, x = (int(v) for v in lo)
        union[z:z + W, y:y + W, x:x + W] = True
    return union


def _in_box_local(pts, origin, box):
    """Which chunk-local points lie inside the box (all of them without a box)."""
    np = _np()
    if box is None or not len(pts):
        return np.ones(len(pts), bool)
    q = np.asarray(pts) + origin
    return ((q >= box[:, 0]) & (q < box[:, 1])).all(1)


def _pred_chunk(code, ctx):
    """Every arm on one sampled chunk. Excluded (for every arm) when a published source (m7, recto-090, the CT) has a
    chunk S3 reports missing under it; a local map has no missing chunks (an absent one reads as its fill value)."""
    np = _np()
    prule, rule = ctx["prule"], ctx["rule"]
    C = int(prule["chunk"])
    origin = np.array(_dec(code), dtype=np.int64) * C
    box = ctx.get("box")
    blocks, missing = {}, {}
    # the second reader of m7 reads the files the first one has just cached
    for name in sorted(ctx["readers"], key=lambda k: (k == "m7copy", k)):
        blocks[name], missing[name] = _read_block(ctx["readers"][name], origin, C)
    rec = {"chunk": _ckey(code)}
    if any(missing.values()):
        rec["excluded"] = {k: v for k, v in missing.items() if v}
        return rec
    ct = blocks["ct"]
    lines = ctx["lines"]
    sel = (ctx["codes"] == code) & ctx["inside"] & ctx["in_split"]
    P = lines["p"][sel] - origin
    N, g, a, b, main = lines["n"][sel], lines["g"][sel], lines["a"][sel], lines["b"][sel], lines["main"][sel]
    k4 = int(prule["guards"]["g4_upsample"])
    both = "b" in prule["guards"].get("g4_sides", ["a"])
    gids = np.unique(np.concatenate([a, b]) if both else a).tolist()
    dense = {gid: _dense_points(ctx["by_gid"][gid], ctx["orient"][gid], origin, C, k4) for gid in gids}
    CL = _Lines(P, N, g, a, main, prule, ct, dense, b=b, dense_b=dense if both else None)
    regions = ctx["regions"].get(code, [])
    if _opt(prule, "mask", "ct_regions") or box is not None:
        S = rule["seating"]
        kept = []
        for name, p, n in regions:
            q = np.clip(np.rint(p).astype(np.int64), 0, C - 1)
            ok = _in_box_local(p, origin, box)
            if _opt(prule, "mask", "ct_regions"):
                ok &= ct[q[:, 0], q[:, 1], q[:, 2]] > 0
            if ok.sum() >= S["min_chunk_vertices"]:
                kept.append((name, p[ok], n[ok]))
        rec["regions_masked"] = len(regions) - len(kept)
        regions = kept
    fill = ctx["fill"].get(code, np.zeros((0, 3)))
    fill = fill[_in_box_local(fill, origin, box)] if len(fill) else fill
    if len(fill):
        fi = np.clip(np.rint(fill).astype(np.int64), 0, C - 1)
        fi = fi[ct[fi[:, 0], fi[:, 1], fi[:, 2]] > 0]
    else:
        fi = np.zeros((0, 3), np.int64)
    rec.update({"lines": int(CL.main.sum()), "stratum_lines": int((~CL.main).sum()), "regions": len(regions),
                "region_vertices": int(sum(len(p) for _, p, _ in regions)), "fill_points": int(len(fi))})
    nrm = np.median(CL.N, axis=0) if len(CL) else (np.median(np.concatenate([n for _, _, n in regions]), axis=0)
                                                   if regions else np.array([0.0, 0.0, 1.0]))
    nrm = nrm / max(float(np.linalg.norm(nrm)), 1e-9)
    m7 = blocks["m7"] >= prule["on_threshold"]
    actx = {"origin": origin, "normal": nrm, "thresholds": ctx.get("thresholds") or {}}
    arms = ctx["arms"]
    if any(_parse_arm(s)[1] == "oracle" for s in arms + [ctx.get("challenger")]):
        actx["patches"] = _oracle_patches(lines, ctx["in_split"], origin, C, prule)
    if any(_parse_arm(s)[1] == "matched" for s in arms):
        actx["ct_tau"] = _ct_tau(ct, m7, CL, bool(_opt(prule, "mask", "ct_volume")))
        rec["ct_tau"] = actx["ct_tau"]
    maps = {}

    def arm(spec):
        if spec not in maps:
            maps[spec] = m7 if spec == "m7" else _arm_map(spec, blocks, actx, prule)
        return maps[spec]

    if any(_parse_arm(s)[1] == "erode" for s in arms):
        actx["challenger_map"] = arm(ctx["challenger"])
        actx["union"] = _cube_union(CL, m7.shape)
    rec["arms"] = {}
    sides_b = "b" in prule["guards"].get("g4_sides", ["a"])
    for spec in arms:
        m = arm(spec)
        r = _measure_lines(m, CL, prule)
        sc = _seat_regions(m, regions, rule)
        mn, st = CL.main, ~CL.main
        rec["arms"][spec] = {
            "clean": int(r["clean"][mn].sum()), "a_on": int(r["a_on"][mn].sum()), "b_on": int(r["b_on"][mn].sum()),
            "g4": int(r["g4"][mn].sum()), "thick": float(r["thick"][mn].sum()), "vol": int(r["vol"][mn].sum()),
            "s_clean": int(r["clean"][st].sum()),
            "seated": sc["seated"], "unseated": sc["unseated"], "weak": sc["weak"],
            "fill_on": int(m[fi[:, 0], fi[:, 1], fi[:, 2]].sum()) if len(fi) else 0}
        if sides_b:
            rec["arms"][spec].update({"g4_a": int(r["g4_a"][mn].sum()), "g4_b": int(r["g4_b"][mn].sum())})
    if actx.get("erode_budget"):
        rec["erode_budget"] = actx["erode_budget"]
    if ctx["displace"]:
        Cc = prule["controls"]
        base = CL.main & np.isfinite(lines["pitch"][sel][CL.index])
        idx = np.flatnonzero(base)
        shift = (Cc["displace_sign"] * Cc["displace_pitch"] * lines["pitch"][sel][CL.index][idx])[:, None] * CL.N[idx]
        D = _Lines(CL.P[idx] + shift, CL.N[idx], CL.g[idx], CL.a[idx], CL.main[idx], prule, ct)
        keep = idx[D.index]
        r0 = _measure_lines(m7, CL, prule, g4=False)
        r1 = _measure_lines(m7, D, prule, g4=False)
        rec["displaced"] = {"pairs": int(len(keep)), "base_clean": int(r0["clean"][keep].sum()),
                            "displaced_clean": int(r1["clean"].sum())}
    return rec


def _boot_index(n, prule):
    np = _np()
    B = prule["bootstrap"]
    return np.random.default_rng(B["seed"]).integers(0, n, size=(int(B["resamples"]), n)) if n else None


def _ci(vals, prule):
    np = _np()
    a = (1 - prule["bootstrap"]["level"]) / 2
    v = vals[np.isfinite(vals)]
    return [_r(np.percentile(v, 100 * a)), _r(np.percentile(v, 100 * (1 - a)))] if v.size else [None, None]


def _share(num, den, idx, prule):
    np = _np()
    num, den = np.asarray(num, float), np.asarray(den, float)
    out = {"value": _r(num.sum() / den.sum()) if den.sum() else None, "n": _r(den.sum(), 1)}
    if idx is not None and den.sum():
        with np.errstate(invalid="ignore", divide="ignore"):
            out["ci"] = _ci(num[idx].sum(1) / den[idx].sum(1), prule)
    return out


def _diff(nc, nb, den, idx, prule):
    np = _np()
    nc, nb, den = (np.asarray(x, float) for x in (nc, nb, den))
    if not den.sum():
        return {"diff": None, "ci": [None, None]}
    with np.errstate(invalid="ignore", divide="ignore"):
        bt = (nc[idx].sum(1) - nb[idx].sum(1)) / den[idx].sum(1)
    return {"challenger": _r(nc.sum() / den.sum()), "bar": _r(nb.sum() / den.sum()),
            "diff": _r((nc.sum() - nb.sum()) / den.sum()), "ci": _ci(bt, prule)}


def _ratio(nc, nb, idx, prule):
    np = _np()
    nc, nb = np.asarray(nc, float), np.asarray(nb, float)
    if not nb.sum():
        return {"ratio": None, "ci": [None, None]}
    with np.errstate(invalid="ignore", divide="ignore"):
        bt = nc[idx].sum(1) / nb[idx].sum(1)
    return {"ratio": _r(nc.sum() / nb.sum()), "ci": _ci(bt, prule)}


def _arm_counts(chunks, spec, field):
    np = _np()
    return np.array([c["arms"][spec][field] for c in chunks], float)


def _geo(chunks, field):
    np = _np()
    return np.array([c[field] for c in chunks], float)


def _arm_summary(chunks, spec, prule):
    idx = _boot_index(len(chunks), prule)
    lines, regions = _geo(chunks, "lines"), _geo(chunks, "regions")
    a = lambda f: _arm_counts(chunks, spec, f)  # noqa: E731
    out = {"cs": _share(a("clean"), lines, idx, prule),
           "cs_stratum_3_4": _share(a("s_clean"), _geo(chunks, "stratum_lines"), None, prule),
           "a_on": _share(a("a_on"), lines, None, prule), "b_on": _share(a("b_on"), lines, None, prule),
           "g1_seated": _share(a("seated"), regions, None, prule),
           "g1_unseated": _share(a("unseated"), regions, None, prule),
           "g2_fill": _share(a("fill_on"), _geo(chunks, "fill_points"), None, prule),
           "g4_continuity": _share(a("g4"), lines, None, prule),
           "band_thickness_vox": _r(a("thick").sum() / max(lines.sum(), 1), 3),
           "window_volume_share": _r(a("vol").sum() / max(lines.sum() * (2 * prule["lines"]["window_half_vox"] + 1)
                                                         ** 3, 1))}
    if chunks and "g4_a" in chunks[0]["arms"][spec]:
        out["g4_a"] = _share(a("g4_a"), lines, None, prule)
        out["g4_b"] = _share(a("g4_b"), lines, None, prule)
    return out


def pred_compare(chunks, challenger, bar, prule=None):
    """Challenger against bar on the same lines, paired, with a cluster bootstrap over chunks: CS gain, the guards
    (G1 seated share and G4 continuity not lower, G2 fill not higher than the share margin at the interval's end;
    volume and band thickness: version 1, ratios inside ratio_band; version 2, the upper end of the ratio's interval
    at most ratio_max, no extra volume or thickness) and whether it beats (gain >= cs_gain with the interval above 0
    and every guard held)."""
    prule = prule or PRED_RULE
    G = prule["guards"]
    idx = _boot_index(len(chunks), prule)
    a = lambda s, f: _arm_counts(chunks, s, f)  # noqa: E731
    if idx is None:
        return {"challenger": challenger, "bar": bar, "beats": False, "reason": "no chunk measured"}
    lines, regions, fill = _geo(chunks, "lines"), _geo(chunks, "regions"), _geo(chunks, "fill_points")
    out = {"challenger": challenger, "bar": bar,
           "cs": _diff(a(challenger, "clean"), a(bar, "clean"), lines, idx, prule),
           "g1_seated": _diff(a(challenger, "seated"), a(bar, "seated"), regions, idx, prule),
           "g2_fill": _diff(a(challenger, "fill_on"), a(bar, "fill_on"), fill, idx, prule),
           "g4_continuity": _diff(a(challenger, "g4"), a(bar, "g4"), lines, idx, prule),
           "volume_ratio": _ratio(a(challenger, "vol"), a(bar, "vol"), idx, prule),
           "thickness_ratio": _ratio(a(challenger, "thick"), a(bar, "thick"), idx, prule)}
    m = G["share_margin"]

    def low(x):
        return x["ci"][0] if x.get("ci") and x["ci"][0] is not None else -math.inf

    def high(x):
        return x["ci"][1] if x.get("ci") and x["ci"][1] is not None else math.inf

    if "ratio_max" in G:
        rmax = G["ratio_max"]

        def ratio_held(x):
            return high(x) <= rmax + 1e-12
    else:
        lo, hi = G["ratio_band"]

        def ratio_held(x):
            return lo - 1e-12 <= low(x) and high(x) <= hi + 1e-12

    held = {"g1": low(out["g1_seated"]) >= -m - 1e-12,
            "g2": high(out["g2_fill"]) <= m + 1e-12 if out["g2_fill"].get("diff") is not None else True,
            "g4": low(out["g4_continuity"]) >= -m - 1e-12,
            "volume": ratio_held(out["volume_ratio"]),
            "thickness": ratio_held(out["thickness_ratio"])}
    if out["g1_seated"].get("diff") is None:
        held["g1"] = True
    cs = out["cs"]
    out["guards_held"] = held
    out["cs_gain_met"] = bool(cs.get("diff") is not None and cs["diff"] >= prule["beat"]["cs_gain"] - 1e-12
                              and low(cs) > 0)
    out["beats"] = bool(out["cs_gain_met"] and all(held.values()))
    return out


def _identity_ok(cmp):
    """Every difference 0 and every ratio 1, with collapsed intervals."""
    for k in ("cs", "g1_seated", "g2_fill", "g4_continuity"):
        v = cmp.get(k, {})
        if v.get("diff") not in (None, 0.0) or any(x not in (None, 0.0) for x in v.get("ci", [])):
            return False
    for k in ("volume_ratio", "thickness_ratio"):
        v = cmp.get(k, {})
        if v.get("ratio") not in (None, 1.0) or any(x not in (None, 1.0) for x in v.get("ci", [])):
            return False
    return not cmp.get("beats")


def _displaced(chunks, prule):
    """The displaced-line control. Version 1: m7's clean share drops by at least displace_drop. Version 2: the
    displaced lines' clean share is at most displace_max_ratio of the true lines' (and the true share above 0)."""
    Cc = prule["controls"]
    pairs = sum(ch.get("displaced", {}).get("pairs", 0) for ch in chunks)
    b = sum(ch.get("displaced", {}).get("base_clean", 0) for ch in chunks)
    d = sum(ch.get("displaced", {}).get("displaced_clean", 0) for ch in chunks)
    drop = (b - d) / pairs if pairs else None
    out = {"pairs": pairs, "base_cs": _r(b / pairs) if pairs else None,
           "displaced_cs": _r(d / pairs) if pairs else None, "drop": _r(drop)}
    if "displace_max_ratio" in Cc:
        ratio = d / b if b else None
        out.update({"ratio": _r(ratio), "relative_drop": _r(1 - ratio) if ratio is not None else None,
                    "pass": bool(b > 0 and ratio is not None and ratio <= Cc["displace_max_ratio"] + 1e-12),
                    "criterion": f"lines moved {Cc['displace_pitch']} local pitch keep at most "
                                 f"{Cc['displace_max_ratio']} of m7's clean share on the true lines (which must be "
                                 "above 0), else the run is VOID"})
    else:
        out.update({"pass": bool(drop is not None and drop >= Cc["displace_drop"] - 1e-12),
                    "criterion": f"lines moved {Cc['displace_pitch']} local pitch drop m7's clean share "
                                 f"by at least {Cc['displace_drop']}, else the run is VOID"})
    return out


def pred_controls(chunks, prule=None):
    """The stage's controls on measured chunks (arms m7, m7copy (version 2), m7:dilate, m7:lattice, m7:shift,
    ct:matched, m7:oracle (development only) and the displaced lines): identity gives zero, the dilated, lattice
    and CT maps do not beat m7, the shifted map fails G1, displaced lines drop m7's clean share (else VOID), and
    the oracle's headroom."""
    prule = prule or PRED_RULE
    Cc = prule["controls"]
    have = set(chunks[0]["arms"]) if chunks else set()
    out = {}
    if _opt(prule, "controls", "identity") == "second_reader":
        if "m7copy" not in have:
            raise BenchError("version 2's identity control needs the m7copy arm (m7 read through a second reader)")
        ident = pred_compare(chunks, "m7copy", "m7", prule)
        crit = "m7 read through a second, independent reader and measured apart: every difference 0, every ratio 1, " \
               "intervals collapsed"
    else:
        ident = pred_compare(chunks, "m7", "m7", prule)
        crit = "m7 against itself: every difference 0, every ratio 1, intervals collapsed"
    out["identity"] = {"arm": ident["challenger"], "pass": _identity_ok(ident), "cs": ident.get("cs"),
                       "criterion": crit}
    for name, spec in (("dilate", "m7:dilate"), ("lattice", "m7:lattice"), ("ct_matched", "ct:matched")):
        c = pred_compare(chunks, spec, "m7", prule)
        out[name] = {"arm": spec, "beats": c["beats"], "pass": not c["beats"], "comparison": c,
                     "criterion": "does not beat m7"}
    c = pred_compare(chunks, "m7:shift", "m7", prule)
    out["shift"] = {"arm": "m7:shift", "g1_held": c["guards_held"]["g1"], "pass": not c["guards_held"]["g1"],
                    "g1_seated": c["g1_seated"], "criterion": f"m7 moved {Cc['shift_vox']} voxels fails G1"}
    out["displaced"] = _displaced(chunks, prule)
    if "m7:oracle" in have:
        o = pred_compare(chunks, "m7:oracle", "m7", prule)
        gain = o["cs"].get("diff")
        out["headroom"] = {"arm": "m7:oracle", "gain": gain, "ci": o["cs"].get("ci"),
                           "enough": bool(gain is not None and gain >= Cc["headroom"] - 1e-12),
                           "comparison": o,
                           "criterion": f"the reference-oracle midplane cut gains at least {Cc['headroom']} over m7"}
        if not out["headroom"]["enough"]:
            out["headroom"]["statement"] = ("the reference-oracle midplane cut gains under "
                                            f"+{Cc['headroom']} over m7 on these chunks: contact separation cannot be "
                                            "beaten by post-processing here")
    else:
        out["headroom"] = {"run": False, "reason": "the reference oracle reads the references: development only"}
    out["void"] = not out["displaced"]["pass"]
    out["valid"] = all(out[k]["pass"] for k in ("identity", "dilate", "lattice", "ct_matched", "shift")) \
        and not out["void"]
    out["failed"] = [k for k in ("identity", "dilate", "lattice", "ct_matched", "shift", "displaced")
                     if not out[k]["pass"]]
    return out


CONTROL_ARMS_V1 = ("m7", "recto090", "m7:dilate", "m7:lattice", "m7:shift", "ct:matched", "m7:oracle")
CONTROL_ARMS = ("m7", "m7copy", "recto090", "m7:dilate", "m7:lattice", "m7:shift", "ct:matched", "m7:oracle")


def _control_arms(prule, split):
    arms = CONTROL_ARMS if _opt(prule, "controls", "identity") == "second_reader" else CONTROL_ARMS_V1
    return [a for a in arms if split == "dev" or _parse_arm(a)[1] != "oracle"]


def _reader(base, cache_dir, opener, local=None):
    if base in PRED_SOURCES:
        return ChunkReader(PRED_SOURCES[base], cache_dir, opener)
    if base == "m7copy":
        # the A/A control: m7's own cached files read by the reader a candidate uses, not by ChunkReader
        return LocalZarr(Path(cache_dir) / PRED_M7.rsplit("/", 1)[-1] / "0")
    kw = (local or {}).get(base) or {}
    return LocalZarr(base, offset=kw.get("offset"), threshold=kw.get("threshold"))


def predscore(pred, against=None, split="dev", controls=False, refs_dir=DEFAULT_REFS, cache_dir=DEFAULT_CACHE,
              rule=None, prule=None, workers=2, log=None, readers=None, frozen=None, opener=None, rule_only=False,
              box=None, local=None):
    """Contact separation of one surface prediction on the counted lines of a split's chunk sample, with guards,
    optionally against one or more bars and with the stage's controls. m7, recto-090 and the CT are always read, so
    the lines (inside the CT mask, no chunk missing in a published source) are the same in every run of one rule.
    With a box, only the chunks under it and lines whose window lies in it are scored (box-only scoring). `local`
    gives a local map's explicit offset and threshold ({path: {"offset": [z, y, x], "threshold": t}}), recorded in
    the run rule. A report run needs the run rule's digest (frozen) committed before it, and refuses the reference
    oracle."""
    np = _np()
    rule, prule = rule or RULE, prule or PRED_RULE
    t0 = time.time()
    if split not in ("dev", "report"):
        raise BenchError(f"split {split}: dev or report")
    bars = [] if against is None else ([against] if isinstance(against, str) else list(against))
    asked = [pred] + bars
    if split == "report" and any(_parse_arm(a)[1] == "oracle" for a in asked):
        raise BenchError("the reference oracle reads the references: it runs on development chunks only")
    if _parse_arm(pred)[1] == "erode":
        raise BenchError("the erosion null is a bar (--against BASE:erode), matched to the challenger's budget")
    bx = _box(box)
    local = {k: dict(v) for k, v in (local or {}).items()}
    man, refs = load_refs(refs_dir, rule)
    lines = _pred_lines(refs, man, prule)
    chunks, eligible = pred_sample(refs, man, split, rule, prule, lines, box=bx)
    rr = pred_run_rule(split, chunks, man, rule, prule, box=box, local=local)
    rd = digest(rr)
    _say(log, f"surfbench predscore: {split} sample {len(chunks)} of {eligible} eligible chunks, run rule {rd}")
    head = {"kind": "kit-surfbench-predscore", "run_rule_digest": rd, "pred_rule_digest": digest(prule),
            "pred_rule_version": prule.get("version"), "manifest_digest": man["digest"], "split": split,
            "eligible_chunks": eligible, "sampled_chunks": len(chunks)}
    if rule_only:
        return {**head, "run_rule": rr}
    if split == "report" and frozen != rd:
        raise BenchError(f"a report run needs --frozen {rd} (the run rule's digest, committed before the run)")
    if not chunks:
        what = " under the box" if bx is not None else ""
        raise BenchError(f"no {split} chunk{what} holds {1 if bx is not None else prule['sample']['min_lines']} "
                         "counted lines" + (" (development chunks hold no report-winding geometry)"
                                            if split == "dev" else ""))
    arms = asked + (_control_arms(prule, split) if controls else [])
    arms = list(dict.fromkeys(["m7"] + arms))
    bases = {"m7", "recto090", "ct"} | {_parse_arm(a)[0] for a in arms}
    readers = dict(readers or {})
    for b in sorted(bases, key=lambda k: (k == "m7copy", k)):
        if b not in readers:
            readers[b] = _reader(b, cache_dir, opener, local)
    thresholds = {k: getattr(v, "threshold", None) for k, v in readers.items()
                  if getattr(v, "threshold", None) is not None}
    ids, _ = _split_ids(refs, rule, split)
    _, codes, inside = _place(lines["p"], lines["n"], lines["g"], prule, bx)
    lines["mid"] = lines["p"] + (lines["g"] / 2)[:, None] * lines["n"]
    want = set(chunks)
    recs = {x["name"]: x for x in man["references"]}
    ctx = {"prule": prule, "rule": rule, "readers": readers, "arms": arms, "lines": lines, "codes": codes,
           "inside": inside, "in_split": np.isin(lines["a"], ids) & np.isin(lines["b"], ids),
           "by_gid": {r.gid: r for r in refs},
           "orient": {r.gid: (1 if r.attrs.get("orient", recs.get(r.name, {}).get("orient", 1)) > 0 else -1)
                      for r in refs},
           "regions": _pred_regions(refs, man, ids, rule, prule, want),
           "fill": _pred_fill(refs, man, ids, prule, want), "displace": bool(controls),
           "challenger": pred, "box": bx, "thresholds": thresholds}
    done = []
    with concurrent.futures.ThreadPoolExecutor(max(1, workers)) as pool:
        for i, rec in enumerate(pool.map(lambda k: _pred_chunk(k, ctx), chunks)):
            done.append(rec)
            if (i + 1) % 10 == 0:
                _say(log, f"surfbench predscore:   {i + 1}/{len(chunks)} chunks ({time.time() - t0:.0f} s)")
    for b, rd_ in readers.items():
        if isinstance(rd_, LocalZarr):
            thr = rd_.threshold if rd_.threshold is not None else prule["on_threshold"]
            if 0 < rd_.max_value < thr:
                raise BenchError(f"{b}: no voxel reaches the on threshold {thr} (largest value {rd_.max_value}); "
                                 "give the map's own threshold (--threshold)")
    measured = [c for c in done if "arms" in c]
    out = {**head, "pred": pred, "against": bars[0] if len(bars) == 1 else (bars or None), "arms": arms,
           "excluded_chunks": {c["chunk"]: c["excluded"] for c in done if "excluded" in c},
           "measured_chunks": len(measured),
           "lines": int(sum(c["lines"] for c in measured)),
           "stratum_lines": int(sum(c["stratum_lines"] for c in measured)),
           "regions": int(sum(c["regions"] for c in measured)),
           "fill_points": int(sum(c["fill_points"] for c in measured)),
           "summary": {a: _arm_summary(measured, a, prule) for a in arms} if measured else {}}
    if bars and measured:
        cmps = {b: pred_compare(measured, pred, b, prule) for b in bars}
        out["comparison"] = cmps[bars[0]]
        if len(bars) > 1:
            out["comparisons"] = cmps
            out["beats_all"] = all(c["beats"] for c in cmps.values())
    if controls and measured:
        out["controls"] = pred_controls(measured, prule)
        out["recto090_vs_m7"] = pred_compare(measured, "recto090", "m7", prule)
        out["m7_vs_recto090"] = pred_compare(measured, "m7", "recto090", prule)
    out["readers"] = {k: {kk: getattr(v, kk, None) for kk in ("fetched", "cached", "missing", "absent")}
                      for k, v in readers.items()}
    out["per_chunk"] = done
    out["run_rule"] = rr
    out["seconds"] = round(time.time() - t0, 1)
    return out


def pred_framecheck(pred, box, refs_dir=DEFAULT_REFS, cache_dir=DEFAULT_CACHE, rule=None, prule=None, readers=None,
                    opener=None, offset=None, threshold=None, log=None):
    """Is a local map in m7's frame on its box? On every m7 chunk under the box that holds no report-winding geometry
    (the development exclusion), the overlap (Dice) of the map with m7 over the part of the box in that chunk, less
    max_shift_vox at every side, at every integer shift of m7 up to max_shift_vox along each axis. It passes when the
    peak is at zero shift and its Dice is at least min_dice. Reads the references' geometry only."""
    np = _np()
    rule, prule = rule or RULE, prule or PRED_RULE
    F = prule.get("frame_check") or PRED_RULE["frame_check"]
    s, need = int(F["max_shift_vox"]), float(F["min_dice"])
    bx = _box(box)
    C = int(prule["chunk"])
    man, refs = load_refs(refs_dir, rule)
    lines = _pred_lines(refs, man, prule)
    bad = _report_chunks(refs, rule, lines, C)
    under = [(z, y, x) for z in range(int(bx[0, 0]) // C, (int(bx[0, 1]) - 1) // C + 1)
             for y in range(int(bx[1, 0]) // C, (int(bx[1, 1]) - 1) // C + 1)
             for x in range(int(bx[2, 0]) // C, (int(bx[2, 1]) - 1) // C + 1)]
    use = [k for k in under if int(_enc(k)) not in bad]
    readers = dict(readers or {})
    if "m7" not in readers:
        readers["m7"] = ChunkReader(PRED_M7, cache_dir, opener)
    if pred not in readers:
        readers[pred] = LocalZarr(pred, offset=offset, threshold=threshold)
    thr = getattr(readers[pred], "threshold", None)
    thr = prule["on_threshold"] if thr is None else thr
    shifts = [(dz, dy, dx) for dz in range(-s, s + 1) for dy in range(-s, s + 1) for dx in range(-s, s + 1)]
    ov = collections.Counter()
    nm = collections.Counter()
    nc = vox = 0
    used = []
    for k in use:
        origin = np.array(k, dtype=np.int64) * C
        lo = np.maximum(origin, bx[:, 0]) + s - origin
        hi = np.minimum(origin + C, bx[:, 1]) - s - origin
        if (hi <= lo).any():
            continue
        mb, mm = _read_block(readers["m7"], origin, C)
        cb, cm = _read_block(readers[pred], origin, C)
        if mm or cm:
            continue
        m7 = mb >= prule["on_threshold"]
        cand = cb >= thr
        R = tuple(slice(int(a), int(b)) for a, b in zip(lo, hi))
        cr = cand[R]
        nc += int(cr.sum())
        vox += int(cr.size)
        for d in shifts:
            Rd = tuple(slice(int(a) + dd, int(b) + dd) for a, b, dd in zip(lo, hi, d))
            mr = m7[Rd]
            ov[d] += int((cr & mr).sum())
            nm[d] += int(mr.sum())
        used.append(_ckey(int(_enc(k))))
    dice = {d: (2 * ov[d] / (nc + nm[d]) if nc + nm[d] else 0.0) for d in shifts}
    zero = (0, 0, 0)
    best = max(shifts, key=lambda d: (dice[d], -sum(abs(v) for v in d)))
    other = max((dice[d] for d in shifts if d != zero), default=0.0)
    ok = bool(nc and nm[zero] and best == zero and dice[zero] >= need)
    out = {"kind": "kit-surfbench-framecheck", "pred": str(pred), "box": [int(v) for v in bx.ravel()],
           "rule": F, "chunks_under_box": len(under), "chunks_used": used,
           "chunks_skipped_report_geometry": len(under) - len(use), "voxels": vox,
           "on_candidate": nc, "on_m7": nm[zero], "dice_at_zero": _r(dice[zero]), "best_shift": list(best),
           "best_dice": _r(dice[best]), "best_other_dice": _r(other), "pass": ok,
           "dice_by_radius": {str(r): {"max": _r(max(dice[d] for d in shifts if max(map(abs, d)) == r)),
                                       "min": _r(min(dice[d] for d in shifts if max(map(abs, d)) == r))}
                              for r in range(s + 1)},
           "criterion": f"Dice peak over shifts up to {s} voxels at zero shift, and at least {need}"}
    if not used:
        out["reason"] = "no chunk under the box is free of report-winding geometry"
    elif not nc or not nm[zero]:
        out["reason"] = "no map voxel in the part of the box checked"
    _say(log, f"surfbench framecheck: {'PASS' if ok else 'FAIL'} dice {out['dice_at_zero']} best {out['best_shift']}")
    return out


# ---------------------------------------------------------------- command line

def build_parser(p):
    sub = p.add_subparsers(dest="surfbench_cmd", required=True)
    r = sub.add_parser("refs", help="download the PHerc0139 windings (frame 20250728140407) and build the manifest")
    r.add_argument("--dest", default=str(DEFAULT_REFS))
    r.add_argument("--from-dir", help="build from local tifxyz folders (one per winding, named wNNN) instead")
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--json", action="store_true")
    a = sub.add_parser("audit", help="seating of every reference on the m7 prediction in a seeded chunk sample")
    a.add_argument("--refs", default=str(DEFAULT_REFS))
    a.add_argument("--cache", default=str(DEFAULT_CACHE))
    a.add_argument("--workers", type=int, default=2, help="threads that read and profile chunks")
    a.add_argument("--json", action="store_true")
    s = sub.add_parser("score", help="score one tifxyz against the references, with its controls")
    s.add_argument("surface")
    s.add_argument("--refs", default=str(DEFAULT_REFS))
    s.add_argument("--reference-names", nargs="+", metavar="WINDING",
                   help="load and score only these references, including controls; record a separate scope digest")
    s.add_argument("--no-controls", action="store_true", help="skip the controls (the run is then invalid)")
    s.add_argument("--no-selfcross", action="store_true")
    s.add_argument("--workers", type=int, default=2)
    s.add_argument("--out", help="also write the result here")
    s.add_argument("--json", action="store_true")
    c = sub.add_parser("controls", help="the controls at one site per reference and for every adjacent pair")
    c.add_argument("--refs", default=str(DEFAULT_REFS))
    c.add_argument("--only", nargs="*", help="only these references' sites (no pair controls)")
    c.add_argument("--workers", type=int, default=2)
    c.add_argument("--out", help="also write the result here")
    c.add_argument("--json", action="store_true")
    q = sub.add_parser("predscore", help="contact separation of a surface prediction on the windings' contact lines, "
                                         "with guards, bars and the controls (AutoPipeline stage 4)")
    q.add_argument("pred", help="m7, recto090, ct:matched or a local zarr in the 20250728140407 frame; a suffix "
                                ":dilate, :lattice, :shift or :oracle transforms it as the controls do")
    q.add_argument("--against", nargs="+", help="the bars, named the same way (BASE:erode is the matched-budget "
                                                "erosion null of BASE); paired cluster bootstrap by chunk")
    q.add_argument("--split", choices=("dev", "report"), default="dev")
    q.add_argument("--frozen", help="the run rule digest committed before a report run (required with --split report)")
    q.add_argument("--controls", action="store_true", help="also the controls and (dev) the reference-oracle headroom")
    q.add_argument("--rule-only", action="store_true", help="print the run rule (the chunk sample) and its digest only")
    q.add_argument("--rule-version", type=int, choices=sorted(PRED_RULES), default=PRED_RULE["version"],
                   help="score under an earlier version of the rule (version 1 reproduces its development run)")
    q.add_argument("--box", nargs=6, type=int, metavar=("Z0", "Z1", "Y0", "Y1", "X0", "X1"),
                   help="box-only scoring: the chunks under this box and the lines whose window lies in it")
    q.add_argument("--offset", nargs=3, type=int, metavar=("Z", "Y", "X"),
                   help="frame voxel of the local map's voxel 0 (recorded in the run rule)")
    q.add_argument("--threshold", type=float, help="the local map's own on threshold (recorded in the run rule)")
    q.add_argument("--refs", default=str(DEFAULT_REFS))
    q.add_argument("--cache", default=str(DEFAULT_CACHE))
    q.add_argument("--workers", type=int, default=2, help="chunks measured at once")
    q.add_argument("--out", help="also write the result here")
    q.add_argument("--json", action="store_true")
    g = sub.add_parser("gscore", help="per-winding credit G_w of a traced surface in the band z [4352, 4864), with the "
                                      "switch and self-crossing gates and the planted controls (AutoPipeline stage 2)")
    g.add_argument("surface", nargs="?", help="a tifxyz in the 20250728140407 frame")
    g.add_argument("--winding", nargs="+", help="the winding(s) to credit (default: the one its seed lies on)")
    g.add_argument("--seed", nargs=3, type=float, metavar=("X", "Y", "Z"),
                   help="the seed point (default: the seed in the surface's meta.json; with none, G_w is 0); refused "
                        "for report windings")
    g.add_argument("--best", action="store_true",
                   help="no seed: credit the best component on each winding (controls and perfect surfaces only; "
                        "refused for report windings)")
    g.add_argument("--rule-version", type=int, choices=[1, 2], default=2,
                   help="score under an earlier version of the gscore rule (version 1 reproduces its runs; report "
                        "windings only under the current one)")
    g.add_argument("--controls", action="store_true",
                   help="the planted controls on the tune windings and the gate thresholds they give")
    g.add_argument("--only", nargs="+", help="controls on these tune windings only")
    g.add_argument("--nogrid", help="a real no-grid trace (with its seed in meta.json) moved onto the rule's no-grid "
                                    "windings as a stand-in")
    g.add_argument("--rule-only", action="store_true", help="print the gscore rule, the run rule and their digests")
    g.add_argument("--frozen", help="the run rule digest committed before a report run (required for report windings)")
    g.add_argument("--refs", default=str(DEFAULT_REFS))
    g.add_argument("--cache", default=str(DEFAULT_ROOT / "gscore"), help="reference rates are cached here")
    g.add_argument("--workers", type=int, default=2)
    g.add_argument("--out", help="also write the result here")
    g.add_argument("--json", action="store_true")
    f = sub.add_parser("framecheck", help="is a local map in m7's frame on its box (overlap with m7 at shifts)")
    f.add_argument("pred", help="a local zarr")
    f.add_argument("--box", nargs=6, type=int, metavar=("Z0", "Z1", "Y0", "Y1", "X0", "X1"), required=True)
    f.add_argument("--offset", nargs=3, type=int, metavar=("Z", "Y", "X"))
    f.add_argument("--threshold", type=float)
    f.add_argument("--refs", default=str(DEFAULT_REFS))
    f.add_argument("--cache", default=str(DEFAULT_CACHE))
    f.add_argument("--out", help="also write the result here")
    f.add_argument("--json", action="store_true")
    sub.add_parser("rule", help="print the frozen rule and its digest")


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def _print(obj, as_json, short):
    if as_json:
        print(json.dumps(obj, indent=1))
    else:
        print(short(obj))


def _pred_short(r):
    out = [f"run rule {r['run_rule_digest']} (version {r.get('pred_rule_version')}, {r['split']}, "
           f"{r['sampled_chunks']} of {r['eligible_chunks']} chunks)"]
    if "summary" not in r:
        return "\n".join(out)
    out.append(f"measured {r['measured_chunks']} chunks ({len(r['excluded_chunks'])} excluded for a missing chunk), "
               f"{r['lines']} lines of 5 to 8 voxels, {r['stratum_lines']} of 3 to 4")
    for a, s in r["summary"].items():
        out.append(f"  {a}: CS {s['cs']['value']} {s['cs'].get('ci')}, G1 seated {s['g1_seated']['value']}, G2 fill "
                   f"{s['g2_fill']['value']}, G4 {s['g4_continuity']['value']}, thickness {s['band_thickness_vox']}")
    for c in (r.get("comparisons") or ({"x": r["comparison"]} if r.get("comparison") else {})).values():
        out.append(f"{c['challenger']} against {c['bar']}: CS {c['cs'].get('diff')} {c['cs'].get('ci')}, guards "
                   f"{c.get('guards_held')}, beats {c['beats']}")
    if r.get("controls"):
        k = r["controls"]
        h = k["headroom"]
        head = (f"oracle headroom {h['gain']} {h['ci']}" + ("" if h["enough"] else f": {h['statement']}")) \
            if h.get("run", True) else "oracle not run (development only)"
        out.append(f"controls {'valid' if k['valid'] else 'INVALID'}{' (VOID)' if k['void'] else ''}; failed "
                   f"{k['failed']}; {head}")
    return "\n".join(out)


def _gscore_short(r):
    out = []
    if r.get("seed"):
        s = r["seed"]
        out.append(f"seed ({s.get('source')}) {s.get('point')} -> vertex {s.get('vertex_rc')}" + (
            "" if s.get("on", True) else f", moved to {s.get('moved_to_rc')}") + (
            f"; {s['reason']}" if s.get("reason") else ""))
    if r.get("reach"):
        k = r["reach"]
        out.append(f"regions {k['regions']}, components {k['components']}, links {k['links']}, torn edges "
                   f"{k['torn_edges']}")
    for name, w in (r.get("windings") or {}).items():
        g = w.get("gates") or {}
        out.append(f"  {name}: G {w.get('G')} credit {w.get('credit')} (covered {w.get('covered_cm2')} of "
                   f"{w.get('band_cm2')} cm2; wrong {w.get('wrong_cm2')}, net {w.get('net_cm2')}, seam "
                   f"{w.get('seam_cm2')}); switch excess {(g.get('switch') or {}).get('excess')} self-crossing "
                   f"excess {(g.get('selfcross') or {}).get('excess')} gates {g.get('pass')}")
    out.append(f"valid {r.get('valid')}; {r.get('invalid_reasons')}; run rule {r.get('run_rule_digest')} (gscore rule "
               f"version {r.get('gscore_rule_version')})")
    return "\n".join(out)


def _cmd_gscore(args):
    from . import gscore as gs
    grule = gs.GRULES[getattr(args, "rule_version", None) or gs.GRULE["version"]]
    if args.rule_only:
        out = {"gscore_rule": grule, "gscore_rule_digest": gs.grule_digest(grule)}
        if (Path(args.refs) / "manifest.json").is_file():
            rr = gs.run_rule(load_manifest(args.refs), grule)
            out.update({"run_rule": rr, "run_rule_digest": digest(rr)})
        print(json.dumps(out, indent=1))
        return 0
    if args.controls:
        res = gs.run_controls(args.refs, args.only, grule=grule, cache_dir=args.cache, workers=args.workers,
                              nogrid=args.nogrid, log=_log)
        if args.out:
            Path(args.out).write_text(json.dumps(res, indent=1))
        _print(res, args.json, lambda r: f"gscore controls {'valid' if r['valid'] else 'INVALID'}: failed "
                                         f"{r['failed']}; {json.dumps(r['summary'])}; gates {json.dumps(r['gates'])}")
        return 0 if res["valid"] else 3
    if not args.surface:
        raise BenchError("gscore needs a surface, --controls or --rule-only")
    res = gs.score(args.surface, args.winding, args.refs, seed=args.seed, best=args.best, grule=grule,
                   cache_dir=args.cache, workers=args.workers, frozen=args.frozen, log=_log)
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=1))
    _print(res, args.json, _gscore_short)
    return 0 if res["valid"] else 3


def cmd_surfbench(args):
    try:
        if args.surfbench_cmd == "rule":
            print(json.dumps({"rule": RULE, "digest": RULE_DIGEST}, indent=1))
            return 0
        if args.surfbench_cmd == "refs":
            if args.from_dir:
                src = Path(args.from_dir)
                meshes = {d.name: d for d in sorted(src.iterdir()) if (d / "x.tif").is_file()}
                man = build_manifest(args.dest, meshes, log=_log, workers=args.workers)
            else:
                man = build_refs(args.dest, log=_log, workers=args.workers)
            _print(man, args.json, lambda m: "\n".join(
                [f"references {len(m['references'])}, order {' '.join(m['order'])}",
                 f"duplicates: {[(g['members'], g['kept'], [c['outcome'] for c in g['copies']]) for g in m['duplicates']]}",
                 "gaps: " + ", ".join(f"{c['inner']}->{c['outer']} step {c['step_vox']} (local pitch "
                                      f"{c['local_pitch_vox']})" for c in m["chain"] if c["gap"]),
                 "partial: " + ", ".join(r["name"] for r in m["references"] if r["partial"]),
                 f"digest {m['digest']}"]))
            return 0
        if args.surfbench_cmd == "audit":
            au = audit(args.refs, cache_dir=args.cache, log=_log, workers=args.workers)
            _print(au, args.json, lambda a: f"audit: {a['summary']} chunks {a['chunks_sampled']} digest {a['digest']}")
            return 0
        if args.surfbench_cmd == "score":
            res = score(args.surface, args.refs, controls=not args.no_controls, selfcross=not args.no_selfcross,
                        workers=args.workers, log=_log, reference_names=args.reference_names)
            if args.out:
                Path(args.out).write_text(json.dumps(res, indent=1))
            _print(res, args.json, lambda r: (
                f"{r['verdict']}; dominant {r['metrics'] and r['metrics']['dominant']}, precision@4 "
                f"{r['metrics'] and r['metrics']['d4']['dominant_precision']}, scored "
                f"{r['metrics'] and r['metrics']['d4']['scored_share']}; invalid: {r['invalid_reasons']}"))
            return 0 if res["valid"] else 3
        if args.surfbench_cmd == "controls":
            res = run_controls(args.refs, workers=args.workers, log=_log, names=args.only)
            if args.out:
                Path(args.out).write_text(json.dumps(res, indent=1))
            _print(res, args.json, lambda r: f"controls {'valid' if r['valid'] else 'INVALID'}: "
                                             f"{json.dumps(r['summary'])}")
            return 0 if res["valid"] else 3
        if args.surfbench_cmd == "predscore":
            local = None
            if args.offset is not None or args.threshold is not None:
                local = {args.pred: {k: v for k, v in (("offset", args.offset), ("threshold", args.threshold))
                                     if v is not None}}
            res = predscore(args.pred, args.against, args.split, args.controls, args.refs, args.cache,
                            prule=PRED_RULE if args.rule_version == PRED_RULE.get("version") else
                            PRED_RULES[args.rule_version], workers=args.workers, log=_log, frozen=args.frozen,
                            rule_only=args.rule_only, box=args.box, local=local)
            if args.out:
                Path(args.out).write_text(json.dumps(res, indent=1))
            _print(res, args.json, _pred_short)
            return 3 if res.get("controls") and not res["controls"]["valid"] else 0
        if args.surfbench_cmd == "gscore":
            return _cmd_gscore(args)
        if args.surfbench_cmd == "framecheck":
            res = pred_framecheck(args.pred, args.box, args.refs, args.cache, offset=args.offset,
                                  threshold=args.threshold, log=_log)
            if args.out:
                Path(args.out).write_text(json.dumps(res, indent=1))
            _print(res, args.json, lambda r: f"frame check {'PASS' if r['pass'] else 'FAIL'}: Dice at zero "
                                             f"{r['dice_at_zero']}, best shift {r['best_shift']} ({r['best_dice']}), "
                                             f"chunks {r['chunks_used']}" + (f"; {r['reason']}" if 'reason' in r
                                                                            else ""))
            return 0 if res["pass"] else 3
    except BenchError as exc:
        print(f"surfbench: {exc}", file=sys.stderr)
        return 2
    return 2
